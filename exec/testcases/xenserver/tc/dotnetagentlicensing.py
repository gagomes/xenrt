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
        self.v6.removeAllLicenses()
        self.licensedEdition = xenrt.TEC().lookup("LICENSED_EDITION")
        self.unlicensedEdition = xenrt.TEC().lookup("UNLICENSED_EDITION")

    def applyLicense(self, hostOrPool, sku = xenrt.TEC().lookup("LICENSED_EDITION")):
        if issubclass(type(hostOrPool),Pool):
            license = self.licenseFactory.licenseForPool(hostOrPool, sku)
        else:
            license = self.licenseFactory.licenseForHost(hostOrPool, sku)
        licenseinUse = self.licenseManager.addLicensesToServer(self.v6,license)
        self.licenseManager.applyLicense(self.v6, hostOrPool, license, licenseinUse)

    def releaseLicense(self, hostOrPool):
        self.applyLicense(hostOrPool, self.unlicensedEdition)

    def checkLicenseState(self,hostOrPool):
        hostOrPool.checkLicenseState(self.licensedEdition)

    def cleanupLicense(self, hostOrPool):
        self.licenseManager.releaseLicense(hostOrPool)

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

    def settingsCleanup(self,guest):
        xenrt.TEC().logverbose("-----Cleanup settings-----")
        host = guest.host
        os = guest.getInstance().os
        host.execdom0("xe pool-param-remove uuid=%s param-name=guest-agent-config param-key=auto_update_enabled"%host.getPool().getUUID())
        host.execdom0("xe pool-param-remove uuid=%s param-name=guest-agent-config param-key=auto_update_url"%host.getPool().getUUID())
        os.winRegDel("HKLM","SOFTWARE\\Citrix\\XenTools","DisableAutoUpdate")
        os.winRegDel("HKLM","SOFTWARE\\Citrix\\XenTools","update_url")

    def filesCleanup(self,guest):
        if self.os.fileExists("C:\\Windows\\System32\\config\\systemprofile\\AppData\\Local\\citrixguestagentx64.msi"):
            self.os.removeFile("C:\\Windows\\System32\\config\\systemprofile\\AppData\\Local\\citrixguestagentx64.msi")
        if self.os.fileExists("C:\\Windows\\System32\\config\\systemprofile\\AppData\\Local\\citrixguestagentx86.msi"):
            self.os.removeFile("C:\\Windows\\System32\\config\\systemprofile\\AppData\\Local\\citrixguestagentx86.msi")

    def serverCleanup(self,guest):
        xenrt.TEC().logverbose("----Server cleanup-----")
        guest.execguest("rm -rf store")
        guest.execguest("rm -rf logs")
        guest.reboot()

    def setUpServer(self,guest,port):
        xenrt.TEC().logverbose("-----Setting up server-----")
        guest.execguest("mkdir -p store")
        guest.execguest("mkdir -p logs")
        guest.execguest(" echo \"file contents\" > store/dotNetAgent.msi")  
        msi = {"dotNetAgent" : SSFile("dotNetAgent.msi","store/")}
        guest.execguest("python -m SimpleHTTPServer {0} > logs/server{0}.log 2>&1&".format(str(port)))
        return SimpleServer(str(port), msi, guest)

    def lowerDotNetAgentVersion(self, guest):
        self.os.winRegAdd("HKLM","SOFTWARE\\Citrix\\XenTools","BuildVersion","DWORD",0)

class DotNetAgentTestCases(xenrt.TestCase):

    def __init__(self):
        super(DotNetAgentTestCases, self).__init__()
        self.adapter = DotNetAgentAdapter(self.getGuest(xenrt.TEC().lookup("LICENSE_SERVER")))
        self.agent = DotNetAgent(self.getGuest("WS2012"))

    def _pingServer(self,agent,server, shouldbe):
        startTime = datetime.datetime.now().time()
        agent.restartAgent()
        xenrt.sleep(200)
        pinged = server.isPinged(startTime)
        xenrt.TEC().logverbose("-----Server was pinged: %s-----"%str(pinged))
        if pinged:
            if not shouldbe:
                raise xenrt.XRTFailure("Server was pinged when it shouldn't be")
        else:
            if shouldbe:
                raise xenrt.XRTFailure("Server was not pinged when it should be")     

    def postRun(self):
        self.adapter.cleanupLicense(self.getDefaultPool())
        self.adapter.serverCleanup(self.getGuest("server"))
        self.adapter.settingsCleanup(self.getGuest("WS2012"))
        self.adapter.filesCleanup(self.getGuest("WS2012"))

class TempTest(DotNetAgentTestCases):

    def run(self,arglist):
        self.adapter.applyLicense(self.getDefaultPool())
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        autoupdate.compareMSIArch()

class PoolAutoUpdateToggle(DotNetAgentTestCases):

    def run(self, arglist):
        server = self.adapter.setUpServer(self.getGuest("server"),"16000")
        agent1 = DotNetAgent(self.getGuest("WS2012(1)"))
        self.adapter.applyLicense(self.getDefaultPool())
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        autoupdate.disable()
        autoupdate.setURL("http://%s:16000"% server.getIP())
        self._pingServer(self.agent,server,False)
        self._pingServer(agent1,server,False)
        autoupdate.enable()
        self._pingServer(self.agent,server,True)
        self._pingServer(agent1,server,True)
        self.adapter.releaseLicense(self.getDefaultPool())
        self._pingServer(self.agent,server,False)
        self._pingServer(agent1,server,False)


class VMAutoUpdateToggle(DotNetAgentTestCases):

    def run(self,arglist):
        server = self.adapter.setUpServer(self.getGuest("server"),"16000")
        self.adapter.applyLicense(self.getDefaultPool())
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        autoupdate.setUserVMUser()
        autoupdate.enable()
        autoupdate.setURL("http://%s:16000"% server.getIP())
        self._pingServer(self.agent,server,False)
        autoupdate.enable()
        self._pingServer(self.agent,server,True)
        self.adapter.releaseLicense(self.getDefaultPool())
        if autoupdate.isLicensed():
            raise xenrt.XRTFailure("autoupdate is licensed when it shouldn't be")
        self._pingServer(self.agent,server,False)

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
        self.adapter.applyLicense(self.getDefaultPool())
        server = self.adapter.setUpServer(self.getGuest("server"),"16000")
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        autoupdate.enable()
        autoupdate.setURL("http://%s:15000"% server.getIP())
        server.addRedirect()
        self._pingServer(self.agent,server,True)

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
        server = self.adapter.setUpServer(self.getGuest("server"),"16000")
        self.adapter.applyLicense(self.getDefaultPool())
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        autoupdate.disable()
        if autoupdate.checkKeyPresent() and autoupdate.isActive():
            pass
        else:
            raise xenrt.XRTFailure("Xapi does not indicate that AutoUpdate is disabled")
        autoupdate.setUserVMUser()
        if autoupdate.checkKeyPresent():
            raise xenrt.XRTFailure("DisableAutoUpdate reg key is present")
        self._pingServer(self.agent,server,False)
        autoupdate.enable()
        self._pingServer(self.agent,server, True)
        autoupdate.setUserPoolAdmin()
        if autoupdate.checkKeyPresent() and autoupdate.isActive():
            pass
        else:
            raise xenrt.XRTFailure("Xapi does not indicate that AutoUpdate is disabled")
        autoupdate.setUserVMUser()
        if autoupdate.checkKeyPresent() and autoupdate.isActive():
            pass
        else:
            raise xenrt.XRTFailure("Xapi does not indicate that AutoUpdate is disabled")
        self._pingServer(self.agent,server,True)

class URLHierarchy(DotNetAgentTestCases):

    def run(self, arglist):
        self.adapter.applyLicense(self.getDefaultPool())
        serverForPool = self.adapter.setUpServer(self.getGuest("server"),"16000")
        serverForVM = self.adapter.setUpServer(self.getGuest("server"),"16001")
