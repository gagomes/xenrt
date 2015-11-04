import xenrt
from xenrt.lib.xenserver.dotnetagentlicensing import *
from xenrt.enum import XenServerLicenseSKU
from xenrt.lib.xenserver.licensing import LicenseManager, XenServerLicenseFactory
import datetime
from xenrt.lib.xenserver.host import Host, Pool
import xenrt.lib.assertions as assertions

class DotNetAgentAdapter(object):

    def __init__(self,licenseServer):
        self.__licenseManager = LicenseManager()
        self.__licenseFactory = XenServerLicenseFactory()
        self.__v6 = licenseServer.getV6LicenseServer()
        self.__licensedEdition = xenrt.TEC().lookup("LICENSED_EDITION")
        self.__unlicensedEdition = xenrt.TEC().lookup("UNLICENSED_EDITION")


    def applyLicense(self, hostOrPool, sku = None):
        if sku == None:
            sku = self.__licensedEdition
        if issubclass(type(hostOrPool),Pool):
            license = self.__licenseFactory.licenseForPool(hostOrPool, sku)
        else:
            license = self.__licenseFactory.licenseForHost(hostOrPool, sku)
        try:
            self.__licenseManager.addLicensesToServer(self.__v6,license, getLicenseInUse=False)
        except xenrt.XRTError, e:
            pass
        hostOrPool.licenseApply(self.__v6, license)

    def releaseLicense(self, hostOrPool):
        self.applyLicense(hostOrPool, self.__unlicensedEdition)

    def checkLicenseState(self,hostOrPool):
        hostOrPool.checkLicenseState(self.__licensedEdition)

    def cleanupLicense(self, hostOrPool):
        self.__licenseManager.releaseLicense(hostOrPool)
        self.__v6.removeAllLicenses()

    def exportVM(self, vm):
        vm.setState("DOWN")
        vmName = vm.getName()
        tmp = xenrt.resources.TempDirectory()
        path = "%s/%s" % (tmp.path(), vmName)
        vm.exportVM(path)
        vm.setState("DOWN")
        vm.uninstall()
        return path

    def importVM(self,vm,host, path):
        vm.importVM(host,path,sr=host.getLocalSR())
        vm.start()

    def settingsCleanup(self, host):
        xenrt.TEC().logverbose("-----Cleanup settings-----")
        if host.xenstoreExists("/guest_agent_features/Guest_agent_auto_update/parameters/enabled"):
            host.execdom0("xe pool-param-remove uuid=%s param-name=guest-agent-config param-key=auto_update_enabled"%host.getPool().getUUID())
        if host.xenstoreExists("/guest_agent_features/Guest_agent_auto_update/parameters/update_url"):
            host.execdom0("xe pool-param-remove uuid=%s param-name=guest-agent-config param-key=auto_update_url"%host.getPool().getUUID())

    def setUpServer(self,guest,port):
        xenrt.TEC().logverbose("-----Setting up server-----")
        guest.execguest("mkdir -p logs")
        guest.execguest("python -m SimpleHTTPServer {0} > logs/server{0}.log 2>&1&".format(str(port)))
        return SimpleServer(str(port), guest)

    def lowerDotNetAgentVersion(self, guest):
        os = guest.getInstance().os
        os.winRegAdd("HKLM","SOFTWARE\\Citrix\\XenTools","BuildVersion","DWORD",0)

class nonCrypto(object):

    @staticmethod
    def nonCryptoMSIInstalled(guest):
        os = guest.getInstance().os
        arch = os.getArch()
        if "64" in arch:
            if os.winRegExists("HKLM","SOFTWARE\\Wow6432Node\\Citrix\\XenTools","UncryptographicallySignedMSI",healthCheckOnFailure=False):
                key = os.winRegLookup("HKLM","SOFTWARE\\Wow6432Node\\Citrix\\XenTools","UncryptographicallySignedMSI",healthCheckOnFailure=False)

        if "86" in arch:
            if os.winRegExists("HKLM","SOFTWARE\\Citrix\\XenTools","UncryptographicallySignedMSI",healthCheckOnFailure=False):
                key = os.winRegLookup("HKLM","SOFTWARE\\Citrix\\XenTools","UncryptographicallySignedMSI",healthCheckOnFailure=False)
        if key:
            return True
        else:
            return False

    @staticmethod
    def getNonCryptoMSIs(server):
        server.guest.execguest("wget '%s/citrixguestagent-Noncrypto.tgz'"%(xenrt.TEC().lookup("TEST_TARBALL_BASE")))
        server.guest.execguest("tar -xf citrixguestagent-Noncrypto.tgz")
        server.guest.execguest("mv citrixguestagent-Noncrypto/managementagentx64.msi managementagentx64.msi")
        server.guest.execguest("mv citrixguestagent-Noncrypto/managementagentx86.msi managementagentx86.msi")

class PingTriggerStrategy(object):
    def execute(self):
        pass

class AgentTrigger(PingTriggerStrategy):
    def __init__(self,agent):
        self.__agent = agent

    def execute(self):
        self.__agent.restartAgent()

class UnlicenseTrigger(PingTriggerStrategy):
    def __init__(self, adapter, pool):
        self.__adapter = adapter
        self.__pool=pool

    def execute(self):
        self.__adapter.releaseLicense(self.__pool)

class DotNetAgentTestCases(xenrt.TestCase):

    def _pingServer(self,trigger,server):
        startTime = datetime.datetime.now().time()
        trigger.execute()
        xenrt.sleep(60)
        pinged = server.isPinged(startTime)
        xenrt.TEC().logverbose("-----Server was pinged: %s-----"%str(pinged))
        return pinged

    def _shouldBePinged(self,trigger,server):
        pinged = self._pingServer(trigger,server)
        assertions.assertTrue(pinged,"Server was not pinged when it should be")

    def _shouldNotBePinged(self,trigger,server):
        pinged = self._pingServer(trigger,server)
        assertions.assertFalse(pinged,"Server was pinged when it shouldn't be")

    def _revertVMs(self):
        self.win1.revert(self.win1.xapiObject.snapshot()[0].uuid)
        if self.win2:
            self.win2.revert(self.win2.xapiObject.snapshot()[0].uuid)
        self.getGuest("server").revert(self.getGuest("server").xapiObject.snapshot()[0].uuid)
        self.getGuest("server").start()

    def postRun(self):
        self.adapter.cleanupLicense(self.getDefaultPool())
        self.adapter.settingsCleanup(self.getHost("RESOURCE_HOST_0"))
        self._revertVMs()

    def prepare(self, arglist):
        self.parseArgs(arglist)
        self.adapter = DotNetAgentAdapter(self.getGuest(xenrt.TEC().lookup("LICENSE_SERVER")))
        self.agent = DotNetAgent(self.win1)

    def parseArgs(self,arglist):
        self.win1 = None
        self.win2 = None
        for arg in arglist:
            if arg.startswith('win1'):
                self.win1 = self.getGuest(arg.split('=')[1])
                self.win1.start()
            if arg.startswith('win2'):
                self.win2 = self.getGuest(arg.split('=')[1])
                self.win2.start()

class PoolAutoUpdateToggle(DotNetAgentTestCases):

    def run(self, arglist):
        server = self.adapter.setUpServer(self.getGuest("server"),"16000")
        agent1 = DotNetAgent(self.win2)
        trigger = AgentTrigger(self.agent)
        trigger1 = AgentTrigger(agent1)
        self.adapter.applyLicense(self.getDefaultPool())
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        autoupdate.disable()
        autoupdate.setURL("http://%s:16000"% server.getIP())
        self._shouldNotBePinged(trigger,server)
        self._shouldNotBePinged(trigger1,server)
        autoupdate.enable()
        self._shouldBePinged(trigger,server)
        self._shouldBePinged(trigger1,server)
        licTrigger = UnlicenseTrigger(self.adapter, self.getDefaultPool())
        self._shouldNotBePinged(licTrigger,server)
        self._shouldNotBePinged(trigger,server)
        self._shouldNotBePinged(trigger1,server)

class VMAutoUpdateToggle(DotNetAgentTestCases):

    def run(self,arglist):
        trigger = AgentTrigger(self.agent)
        server = self.adapter.setUpServer(self.getGuest("server"),"16000")
        self.adapter.applyLicense(self.getDefaultPool())
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        autoupdate.setUserVMUser()
        autoupdate.disable()
        autoupdate.setURL("http://%s:16000"% server.getIP())
        self._shouldNotBePinged(trigger,server)
        autoupdate.enable()
        self._shouldBePinged(trigger,server)
        self.adapter.releaseLicense(self.getDefaultPool())
        assertions.assertFalse(autoupdate.isLicensed(),"autoupdate is licensed when it shouldn't be")
        self._shouldNotBePinged(trigger,server)

class VSSQuiescedSnapshot(DotNetAgentTestCases):

    def run(self, arglist):
        self.adapter.applyLicense(self.getDefaultPool())
        vss = self.agent.getLicensedFeature("VSS")
        assertions.assertTrue(vss.isSnapshotPossible(),"snapshot failed in licensed pool")
        self.adapter.releaseLicense(self.getDefaultPool())
        assertions.assertFalse(vss.isSnapshotPossible(),"snapshot succeeded in unlicensed pool")

class HTTPRedirect(DotNetAgentTestCases):

    def run(self, arglist):
        trigger = AgentTrigger(self.agent)
        self.adapter.applyLicense(self.getDefaultPool())
        server = self.adapter.setUpServer(self.getGuest("server"),"16000")
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        autoupdate.enable()
        autoupdate.setURL("http://%s:15000"% server.getIP())
        xenrt.sleep(60)
        server.addRedirect()
        self._shouldBePinged(trigger,server)

class AllHostsLicensed(DotNetAgentTestCases):

    def run(self, arglist):
        self.adapter.applyLicense(self.getDefaultPool())
        vss = self.agent.getLicensedFeature("VSS")
        autoUpdate = self.agent.getLicensedFeature("AutoUpdate")
        assertions.assertTrue(vss.isLicensed(),"Xenstore indicates VSS is Not Licensed")
        assertions.assertTrue(autoUpdate.isLicensed(),"Xenstore indicates AutoUpdate is Not Licensed")
        self.adapter.releaseLicense(self.getHost("RESOURCE_HOST_1"))
        assertions.assertFalse(vss.isLicensed(),"Xenstore indicates VSS is Licensed")
        assertions.assertFalse(autoUpdate.isLicensed(),"Xenstore indicates AutoUpdate is Licensed")

class ToggleAUHierarchy(DotNetAgentTestCases):

    def run(self, arglist):
        trigger = AgentTrigger(self.agent)
        server = self.adapter.setUpServer(self.getGuest("server"),"16000")
        self.adapter.applyLicense(self.getDefaultPool())
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        autoupdate.disable()
        xenrt.TEC().logverbose("%s"%self.getHost("RESOURCE_HOST_0").execdom0("xenstore-ls -f /guest_agent_features"))
        xenrt.TEC().logverbose("exists %s"%self.getHost("RESOURCE_HOST_0").xenstoreExists("/guest_agent_features/Guest_agent_auto_update/parameters/enabled"))
        xenrt.TEC().logverbose("active %s"%self.getHost("RESOURCE_HOST_0").xenstoreRead("/guest_agent_features/Guest_agent_auto_update/parameters/enabled") == "1")
        #assertions.assertTrue(autoupdate.checkKeyPresent() and not autoupdate.isActive(),"Xapi does not indicate that AutoUpdate is disabled")
        assertions.assertTrue(self.getHost("RESOURCE_HOST_0").xenstoreExists("/guest_agent_features/Guest_agent_auto_update/parameters/enabled"),"Xapi does not indicate that AutoUpdate is disabled")
        autoupdate.setUserVMUser()
        test = autoupdate.checkKeyPresent()
        xenrt.TEC().logverbose("*** %s ",test)
        assertions.assertFalse(test,"DisableAutoUpdate reg key is present")
        self._shouldNotBePinged(trigger,server)
        autoupdate.enable()
        assertions.assertTrue(autoupdate.checkKeyPresent(),"DisableAutoUpdate reg key is not present")
        self._shouldNotPinged(trigger,server)
        autoupdate.setUserPoolAdmin()
        autoupdate.enable()
        assertions.assertTrue(autoupdate.checkKeyPresent() and autoupdate.isActive(),"Xapi does not indicate that AutoUpdate is enabled")
        autoupdate.setUserVMUser()
        autoupdate.disable()
        assertions.assertTrue(autoupdate.checkKeyPresent() and not autoupdate.isActive(),"registry does not indicate that AutoUpdate is disabled")
        self._shouldBePinged(trigger,server)

class URLHierarchy(DotNetAgentTestCases):

    def __defaultServerPinged(self,shouldbe):
        self.agent.restartAgent()
        xenrt.sleep(30)
        if shouldbe:
            assertions.assertNotNone(self.autoupdate.checkDownloadedMSI(),"MSI did not download from default url")
        else:
            assertions.assertNone(self.autoupdate.checkDownloadedMSI(), "MSI was downloaded when it shouldnt be")
        self.adapter.filesCleanup(self.win1)

    def __poolServerPinged(self):
        self.autoupdate.enable()
        self.autoupdate.setURL("http://%s:16000"% self.serverForPool.getIP())
        self._shouldBePinged(self.trigger,self.serverForPool)
        self._shouldNotBePinged(self.trigger,self.serverForVM)
        self.__defaultServerPinged(False)

    def __VMServerPinged(Self):
        self.autoupdate.setUserVMUser()
        self.autoupdate.enable()
        self.autoupdate.setURL("http://%s:16001"% self.serverForPool.getIP())
        self._shouldNotBePinged(self.trigger,self.serverForPool)
        self._shouldBePinged(self.trigger,self.serverForVM)
        self.__defaultServerPinged(False)

    def __defaultURLVMServerPinged(self):
        self.autoupdate.setUserPoolAdmin()
        self.autoupdate.defaultURL()
        self._shouldNotBePinged(self.trigger,self.serverForPool)
        self._shouldBePinged(self.trigger,self.serverForVM)
        self.__defaultServerPinged(False)

    def run(self, arglist):
        self.trigger = AgentTrigger(self.agent)
        self.adapter.applyLicense(self.getDefaultPool())
        self.autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        self.serverForPool = self.adapter.setUpServer(self.getGuest("server"),"16000")
        self.serverForVM = self.adapter.setUpServer(self.getGuest("server"),"16001")
        self.__defaultServerPinged(True)
        self.__poolServerPinged()
        self.__VMServerPinged()
        self.__defaultURLVMServerPinged()

class ImportAndExport(DotNetAgentTestCases):

    def prepare(self, arglist):
        self.win1Real = self.getGuest(arglist[0].split('=')[1])
        clone = self.win1Real.cloneVM(name="WSClone")
        newarglist = ["win1=%s"%clone.name]
        super(ImportAndExport, self).prepare(newarglist)

    def postRun(self):
        self.win1.uninstall()
        self.win1 = self.win1Real()
        super(ImportAndExport, self).postRun()

    def run(self, arglist):
        self.adapter.applyLicense(self.getDefaultPool())
        path = self.adapter.exportVM(self.win1)
        self.adapter.releaseLicense(self.getDefaultPool())
        self.adapter.importVM(self.win1,self.getHost("RESOURCE_HOST_1"),path)
        vss = self.agent.getLicensedFeature("VSS")
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        assertions.assertFalse(vss.isLicensed() or autoupdate.isLicensed(),"Agent features are licensed when they shouldn't be")
        path = self.adapter.exportVM(self.win1)
        self.adapter.applyLicense(self.getDefaultPool())
        self.adapter.importVM(self.win1,self.getHost("RESOURCE_HOST_0"),path)
        vss = self.agent.getLicensedFeature("VSS")
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        assertions.assertTrue(vss.isLicensed() or autoupdate.isLicensed(),"Auto Update features are not licensed when they should be")

class CheckDownloadedArch(DotNetAgentTestCases):

    def run(self, arglist):
        self.adapter.applyLicense(self.getDefaultPool())
        self.adapter.lowerDotNetAgentVersion(self.win1)
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        autoupdate.enable()
        xenrt.sleep(60)
        assertions.assertTrue(autoupdate.compareMSIArch(),"Downloaded MSI is wrong architecture")

class NoVSSOnNonServer(DotNetAgentTestCases):

    def run(self, arglist):
        self.adapter.applyLicense(self.getDefaultPool())
        vss = self.agent.getLicensedFeature("VSS")
        assertions.assertFalse(vss.isSnapshotPossible(),"VSS Snapshot Taken on Non Serverclass Windows")
        self.adapter.releaseLicense(self.getDefaultPool())
        assertions.assertFalse(vss.isSnapshotPossible(), "VSS Snapshot Taken on Non Serverclass Windows")

class AUByDefault(DotNetAgentTestCases):

    def run(self, arglist):
        self.adapter.applyLicense(self.getDefaultPool())
        self.adapter.lowerDotNetAgentVersion(self.win1)
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        version = self.agent.agentVersion()
        self.adapter.lowerDotNetAgentVersion()
        self.agent.restartAgent()
        xenrt.sleep(200)
        assertions.assertNotNone(autoupdate.checkDownloadedMSI(),"Agent did not download MSI")
        assertions.assertNotEquals(version,self.agent.agentVersion(),"Agent Did not install latest version")

class AUNoDownload(DotNetAgentTestCases):

    def run(self, arglist):
        self.adapter.applyLicense(self.getDefaultPool())
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        self.agent.restartAgent()
        xenrt.sleep(30)
        assertions.assertNone(autoupdate.checkDownloadedMSI(),"Agent Downloaded MSI when it was the latest version")

class NonCryptoMSI(DotNetAgentTestCases):

    def run(self, arglist):
        server = self.adapter.setUpServer(self.getGuest("server"),"16000")
        server.createCatalog("99.0.0.0")
        nonCrypto.getNonCryptoMSIs(server)
        self.adapter.applyLicense(self.getDefaultPool())
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        autoupdate.enable()
        autoupdate.setURL("http://%s:16000"%server.getIP())
        self.agent.restartAgent()
        xenrt.sleep(200)
        assertions.assertNotNone(autoupdate.checkDownloadedMSI(),"msi has not downloaded")
        assertions.assertFalse(nonCrypto.nonCryptoMSIInstalled(self.win1),"Non cryprographically signed msi installed")

class NoServerSurvive(DotNetAgentTestCases):

    def run(self, arglist):
        self.adapter.applyLicense(self.getDefaultPool())
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        autoupdate.enable()
        autoupdate.setURL("http://localhost:55555")
        self.agent.restartAgent()
        xenrt.sleep(60)
        assertions.assertTrue(self.agent.isAgentAlive(), "Agent Stopped")