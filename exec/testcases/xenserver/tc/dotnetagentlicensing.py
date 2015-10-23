import xenrt
from xenrt.lib.xenserver.dotnetagentlicensing import *
from xenrt.enum import XenServerLicenseSKU
from xenrt.lib.xenserver.licensing import LicenseManager, XenServerLicenseFactory
import datetime
from xenrt.lib.xenserver.host import Host, Pool

class DotNetAgentAdapter(object):

    def __init__(self,licenseServer):
        self.licenseManager = LicenseManager()
        self.licenseFactory = XenServerLicenseFactory()
        self.v6 = licenseServer.getV6LicenseServer()
        self.licensedEdition = xenrt.TEC().lookup("LICENSED_EDITION")
        self.unlicensedEdition = xenrt.TEC().lookup("UNLICENSED_EDITION")


    def applyLicense(self, hostOrPool, sku = None):
        if sku == None:
            sku = self.licensedEdition
        if issubclass(type(hostOrPool),Pool):
            license = self.licenseFactory.licenseForPool(hostOrPool, sku)
        else:
            license = self.licenseFactory.licenseForHost(hostOrPool, sku)
        try:
            self.licenseManager.addLicensesToServer(self.v6,license, getLicenseInUse=False)
        except:
            pass
        hostOrPool.licenseApply(self.v6, license)

    def releaseLicense(self, hostOrPool):
        self.applyLicense(hostOrPool, self.unlicensedEdition)

    def checkLicenseState(self,hostOrPool):
        hostOrPool.checkLicenseState(self.licensedEdition)

    def cleanupLicense(self, hostOrPool):
        self.licenseManager.releaseLicense(hostOrPool)
        self.v6.removeAllLicenses()

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
        try:
            host.execdom0("xe pool-param-remove uuid=%s param-name=guest-agent-config param-key=auto_update_enabled"%host.getPool().getUUID())
        except Exception, e:
            xenrt.TEC().logverbose("%s"%e)
        try:
            host.execdom0("xe pool-param-remove uuid=%s param-name=guest-agent-config param-key=auto_update_url"%host.getPool().getUUID())
        except Exception, e:
            xenrt.TEC().logverbose("%s"%e)

    def nonCryptoMSIInstalled(self,guest):
        os = guest.getInstance().os
        arch = os.getArch()
        try:
            if "64" in arch:
                key = os.winRegLookup("HKLM","SOFTWARE\\Wow6432Node\\Citrix\\XenTools","UncryptographicallySignedMSI",healthCheckOnFailure=False)
            else:
                key = os.winRegLookup("HKLM","SOFTWARE\\Citrix\\XenTools","UncryptographicallySignedMSI",healthCheckOnFailure=False)
            if key:
                return True
        except:
            return False

    def getNonCryptoMSIs(self, server):
        server.guest.execguest("wget '%s/citrixguestagent-Noncrypto.tgz'"%(xenrt.TEC().lookup("TEST_TARBALL_BASE")))
        server.guest.execguest("tar -xf citrixguestagent-Noncrypto.tgz")
        server.guest.execguest("mv citrixguestagent-Noncrypto/citrixguestagentx64.msi citrixguestagentx64.msi")
        server.guest.execguest("mv citrixguestagent-Noncrypto/citrixguestagentx86.msi citrixguestagentx86.msi")

    def setUpServer(self,guest,port):
        xenrt.TEC().logverbose("-----Setting up server-----")
        guest.execguest("mkdir -p logs")
        guest.execguest("python -m SimpleHTTPServer {0} > logs/server{0}.log 2>&1&".format(str(port)))
        return SimpleServer(str(port), guest)

    def lowerDotNetAgentVersion(self, guest):
        os = guest.getInstance().os
        os.winRegAdd("HKLM","SOFTWARE\\Citrix\\XenTools","BuildVersion","DWORD",0)

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

    def _pingServer(self,trigger,server, shouldbe):
        startTime = datetime.datetime.now().time()
        trigger.execute()
        xenrt.sleep(60)
        pinged = server.isPinged(startTime)
        xenrt.TEC().logverbose("-----Server was pinged: %s-----"%str(pinged))
        if pinged and not shouldbe:
                raise xenrt.XRTFailure("Server was pinged when it shouldn't be")
        if not pinged and shouldbe:
                raise xenrt.XRTFailure("Server was not pinged when it should be")

    def _revertVMs(self):
        self.win1.revert(self.win1.asXapiObject().snapshot()[0].uuid)
        if self.win2:
            self.win2.revert(self.win2.asXapiObject().snapshot()[0].uuid)
        self.getGuest("server").revert(self.getGuest("server").asXapiObject().snapshot()[0].uuid)
        self.getGuest("server").start()
        #self.getGuest(xenrt.TEC().lookup("LICENSE_SERVER")).revert(self.getGuest(xenrt.TEC().lookup("LICENSE_SERVER")).asXapiObject().snapshot()[0].uuid)
        #self.getGuest(xenrt.TEC().lookup("LICENSE_SERVER")).start()

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
        self._pingServer(trigger,server,False)
        self._pingServer(trigger1,server,False)
        autoupdate.enable()
        self._pingServer(trigger,server,True)
        self._pingServer(trigger1,server,True)
        licTrigger = UnlicenseTrigger(self.adapter, self.getDefaultPool())
        self._pingServer(licTrigger,server,False)
        self._pingServer(trigger,server,False)
        self._pingServer(trigger1,server,False)

class VMAutoUpdateToggle(DotNetAgentTestCases):

    def run(self,arglist):
        trigger = AgentTrigger(self.agent)
        server = self.adapter.setUpServer(self.getGuest("server"),"16000")
        self.adapter.applyLicense(self.getDefaultPool())
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        autoupdate.setUserVMUser()
        autoupdate.disable()
        autoupdate.setURL("http://%s:16000"% server.getIP())
        self._pingServer(trigger,server,False)
        autoupdate.enable()
        self._pingServer(trigger,server,True)
        self.adapter.releaseLicense(self.getDefaultPool())
        if autoupdate.isLicensed():
            raise xenrt.XRTFailure("autoupdate is licensed when it shouldn't be")
        self._pingServer(trigger,server,False)

class VSSQuiescedSnapshot(DotNetAgentTestCases):

    def run(self, arglist):
        self.adapter.applyLicense(self.getDefaultPool())
        vss = self.agent.getLicensedFeature("VSS")
        if not vss.isSnapshotPossible():
            raise xenrt.XRTFailure("snapshot failed in licensed pool")
        self.adapter.releaseLicense(self.getDefaultPool())
        if vss.isSnapshotPossible():
            raise xenrt.XRTFailure("snapshot succeeded in unlicensed pool")

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
        self._pingServer(trigger,server,True)

class AllHostsLicensed(DotNetAgentTestCases):

    def run(self, arglist):
        self.adapter.applyLicense(self.getDefaultPool())
        vss = self.agent.getLicensedFeature("VSS")
        autoUpdate = self.agent.getLicensedFeature("AutoUpdate")
        if not vss.isLicensed():
            raise xenrt.XRTFailure("Xenstore indicates VSS is Not Licensed")
        if not autoUpdate.isLicensed():
            raise xenrt.XRTFailure("Xenstore indicates AutoUpdate is Not Licensed")
        self.adapter.releaseLicense(self.getHost("RESOURCE_HOST_1"))
        if vss.isLicensed():
            raise xenrt.XRTFailure("Xenstore indicates VSS is Licensed")
        if autoUpdate.isLicensed():
            raise xenrt.XRTFailure("Xenstore indicates AutoUpdate is Licensed")

class ToggleAUHierarchy(DotNetAgentTestCases):

    def run(self, arglist):
        trigger = AgentTrigger(self.agent)
        server = self.adapter.setUpServer(self.getGuest("server"),"16000")
        self.adapter.applyLicense(self.getDefaultPool())
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        autoupdate.disable()

        keyPresent = autoupdate.checkKeyPresent()
        updateIsActive = autoupdate.isActive()

        xenrt.TEC().logverbose(type(autoupdate.actor))
        xenrt.TEC().logverbose(dir(keyPresent))
        xenrt.TEC().logverbose(type(keyPresent))
        xenrt.TEC().logverbose(type(True))
        xenrt.TEC().logverbose("*****%s : %s*****"%(keyPresent, True ))
        if autoupdate.checkKeyPresent() and not autoupdate.isActive():
            pass
        else:
            raise xenrt.XRTFailure("Xapi does not indicate that AutoUpdate is disabled")
        autoupdate.setUserVMUser()
        if autoupdate.checkKeyPresent():
            raise xenrt.XRTFailure("DisableAutoUpdate reg key is present")
        self._pingServer(trigger,server,False)
        autoupdate.enable()
        self._pingServer(trigger,server, True)
        autoupdate.setUserPoolAdmin()
        autoupdate.disable()
        if autoupdate.checkKeyPresent() and not autoupdate.isActive():
            pass
        else:
            raise xenrt.XRTFailure("Xapi does not indicate that AutoUpdate is disabled")
        autoupdate.setUserVMUser()
        if autoupdate.checkKeyPresent() and autoupdate.isActive():
            pass
        else:
            raise xenrt.XRTFailure("registry does not indicate that AutoUpdate is enabled")
        self._pingServer(trigger,server,True)

class URLHierarchy(DotNetAgentTestCases):

    def run(self, arglist):
        trigger = AgentTrigger(self.agent)
        self.adapter.applyLicense(self.getDefaultPool())
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        serverForPool = self.adapter.setUpServer(self.getGuest("server"),"16000")
        serverForVM = self.adapter.setUpServer(self.getGuest("server"),"16001")
        self.agent.restartAgent()
        xenrt.sleep(30)
        if autoupdate.checkDownloadedMSI() == None:
            raise xenrt.XRTFailure("MSI did not download from default url")
        self.adapter.filesCleanup(self.win1)
        autoupdate.enable()
        autoupdate.setURL("http://%s:16000"% serverForPool.getIP())
        self._pingServer(trigger,serverForPool,True)
        self._pingServer(trigger,serverForVM,False)
        self.agent.restartAgent()
        xenrt.sleep(30)
        if autoupdate.checkDownloadedMSI() != None:
            raise xenrt.XRTFailure("MSI was downloaded when it shouldnt be")
        self.adapter.filesCleanup(self.win1)
        autoupdate.setUserVMUser()
        autoupdate.enable()
        autoupdate.setURL("http://%s:16001"% serverForPool.getIP())
        self._pingServer(trigger,serverForPool,False)
        self._pingServer(trigger,serverForVM,True)
        self.agent.restartAgent()
        xenrt.sleep(30)
        if autoupdate.checkDownloadedMSI() != None:
            raise xenrt.XRTFailure("MSI was downloaded when it shouldnt be")
        self.adapter.filesCleanup(self.win1)
        autoupdate.setUserPoolAdmin()
        autoupdate.defaultURL()
        self._pingServer(trigger,serverForPool,False)
        self._pingServer(trigger,serverForVM,True)
        self.agent.restartAgent()
        xenrt.sleep(30)
        if autoupdate.checkDownloadedMSI() != None:
            raise xenrt.XRTFailure("MSI was downloaded when it shouldnt be")
        self.adapter.filesCleanup(self.win1)

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
        if vss.isLicensed() or autoupdate.isLicensed():
            raise xenrt.XRTFailure("Auto Update features are licensed when they shouldn't be")
        path = self.adapter.exportVM(self.win1)
        self.adapter.applyLicense(self.getDefaultPool())
        self.adapter.importVM(self.win1,self.getHost("RESOURCE_HOST_0"),path)
        vss = self.agent.getLicensedFeature("VSS")
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        if not vss.isLicensed() or not autoupdate.isLicensed():
            raise xenrt.XRTFailure("Auto Update features are not licensed when they should be")

class CheckDownloadedArch(DotNetAgentTestCases):

    def run(self, arglist):
        self.adapter.applyLicense(self.getDefaultPool())
        self.adapter.lowerDotNetAgentVersion(self.win1)
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        autoupdate.enable()
        xenrt.sleep(60)
        if not autoupdate.compareMSIArch():
            raise xenrt.XRTFailure("Downloaded MSI is wrong architecture")

class NoVSSOnNonServer(DotNetAgentTestCases):

    def run(self, arglist):
        self.adapter.applyLicense(self.getDefaultPool())
        vss = self.agent.getLicensedFeature("VSS")
        if vss.isSnapshotPossible():
            raise xenrt.XRTFailure("VSS Snapshot Taken on Non Serverclass Windows")
        self.adapter.releaseLicense(self.getDefaultPool())
        if vss.isSnapshotPossible():
            raise xenrt.XRTFailure("VSS Snapshot Taken on Non Serverclass Windows")

class AUByDefault(DotNetAgentTestCases):

    def run(self, arglist):
        self.adapter.applyLicense(self.getDefaultPool())
        self.adapter.lowerDotNetAgentVersion(self.win1)
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        version = self.agent.agentVersion()
        self.agent.restartAgent()
        xenrt.sleep(200)
        if autoupdate.checkDownloadedMSI() == None:
            xenrt.XRTFailure("Agent did not download MSI")
        if version == self.agent.agentVersion():
            xenrt.XRTFailure("Agent Did not install latest version")

class AUNoDownload(DotNetAgentTestCases):

    def run(self, arglist):
        self.adapter.applyLicense(self.getDefaultPool())
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        self.agent.restartAgent()
        xenrt.sleep(30)
        if autoupdate.checkDownloadedMSI() != None:
            xenrt.XRTFailure("Agent Downloaded MSI when it was the latest version")

class NonCryptoMSI(DotNetAgentTestCases):

    def run(self, arglist):
        server = self.adapter.setUpServer(self.getGuest("server"),"16000")
        server.createCatalog("99.0.0.0")
        self.adapter.getNonCryptoMSIs(server)
        self.adapter.applyLicense(self.getDefaultPool())
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        autoupdate.enable()
        autoupdate.setURL("http://%s:16000"%server.getIP())
        self.agent.restartAgent()
        xenrt.sleep(200)
        if autoupdate.checkDownloadedMSI() == None:
            raise xenrt.XRTFailure("msi has not downloaded")
        if self.adapter.nonCryptoMSIInstalled(self.win1):
            raise xenrt.XRTFailure("Non cryprographically signed msi installed")

class NoServerSurvive(DotNetAgentTestCases):

    def run(self, arglist):
        self.adapter.applyLicense(self.getDefaultPool())
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        autoupdate.enable()
        autoupdate.setURL("http://localhost:55555")
        self.agent.restartAgent()
        xenrt.sleep(60)
        if self.agent.isAgentAlive() == False:
            raise xenrt.XRTFailure("Agent Stopped")