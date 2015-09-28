import xenrt
from xenrt.lib.xenserver.dotnetagentlicensing import *
from xenrt.enum import XenServerLicenseSKU
from xenrt.lib.xenserver.licensing import LicenseManager, XenServerLicenseFactory
import datetime

class DotNetAgentAdapter(object):

    def __init__(self,licenseServer):
        self.licenseManager = LicenseManager()
        self.licenseFactory = XenServerLicenseFactory()
        self.v6 = licenseServer.getV6LicenseServer()
        self.v6.removeAllLicenses()
        self.licensedEdition = xenrt.TEC().lookup("LICENSED_EDITION")
        self.unlicensedEdition = xenrt.TEC().lookup("UNLICENSED_EDITION")

    def applyLicense(self, hostOrPool, sku = xenrt.TEC().lookup("LICENSED_EDITION")):
        license = self.licenseFactory.licenseForPool(hostOrPool, sku)
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

class DotNetAgentTestCases(xenrt.TestCase):

    def __init__(self):
        super(DotNetAgentTestCases, self).__init__()
        self.adapter = DotNetAgentAdapter(self.getGuest(xenrt.TEC().lookup("LICENSE_SERVER")))
        self.agent = DotNetAgent(self.getGuest("WS2012"))

    def postRun(self):
        self.adapter.cleanupLicense(self.getDefaultPool())
        self.adapter.serverCleanup(self.getGuest("server"))
        self.adapter.settingsCleanup(self.getGuest("WS2012"))

class TempTest(DotNetAgentTestCases):

    def run(self,arglist):
        server = self.adapter.setUpServer(self.getGuest("server"),"16000")
        self.adapter.applyLicense(self.getDefaultPool())
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        autoupdate.setUserVMUser()
        autoupdate.enable()
        autoupdate.setURL("http://%s:16000"%server.getIP())
        startTime = datetime.datetime.now().time()
        agent.restartAgent()
        xenrt.sleep(200)
        xenrt.TEC().logverbose("Server was pinged: %s"%str(server.isPinged(startTime)))

class poolAutoUpdateToggle(DotNetAgentTestCases):

    def __pingServers(self,agent1,shouldbe):
        startTime = datetime.datetime.now().time()
        self.agent.restartAgent()
        xenrt.sleep(200)
        pinged = server.isPinged(startTime)
        xenrt.TEC().logverbose("Server was pinged: %s"%str(pinged))
        if pinged:
            if not shouldbe:
                raise xenrt.XRTFailure("Server was pinged when it shouldn't be")
        else:
            if shouldbe:
                raise xenrt.XRTFailure("Server was not pinged when it should be")
        startTime = datetime.datetime.now().time()
        agent1.restartAgent()
        xenrt.sleep(200)
        pinged = server.isPinged(startTime)
        xenrt.TEC().logverbose("Server was pinged: %s"%str(pinged))
        if pinged:
            if not shouldbe:
                raise xenrt.XRTFailure("Server was pinged when it shouldn't be")
        else:
            if shouldbe:
                raise xenrt.XRTFailure("Server was not pinged when it should be")

    def run(self, arglist):
        server = self.adapter.setUpServer(self.getGuest("server"),"16000")
        agent1 = DotNetAgent(self.getGuest("WS2012(1)"))
        self.adapter.applyLicense(self.getDefaultPool())
        autoupdate0 = self.agent.getLicensedFeature("AutoUpdate")
        autoupdate1 = agent1.getLicensedFeature("AutoUpdate")
        autoupdate0.disable()
        autoupdate1.disable()
        autoupdate0.setURL("http://%s:16000"% server.getIP())
        self.__pingServers(agent1,False)
        autoupdate0.enable()
        autoupdate1.enable()
        self.__pingServers(agent1,True)
        self.adapter.releaseLicense(self.getDefaultPool())
        self.__pingServers(agent1,False)


class VMAutoUpdateToggle(DotNetAgentTestCases):

    def run(self,arglist):
        server = self.adapter.setUpServer(self.getGuest("server"),"16000")
        self.adapter.applyLicense(self.getDefaultPool())
        autoupdate = self.agent.getLicensedFeature("AutoUpdate")
        autoupdate.setUserVMUser()
        autoupdate.enable()
        autoupdate.setURL("http://10.81.29.132:16000")
        startTime = datetime.datetime.now().time()
        self.agent.restartAgent()
        xenrt.sleep(200)
        pinged = server.isPinged(startTime)
        xenrt.TEC().logverbose("Server was pinged: %s"%str(pinged))
        if pinged:
            raise xenrt.XRTFailure("Server was pinged when it shouldn't be")
        autoupdate.enable()
        startTime = datetime.datetime.now().time()
        self.agent.restartAgent()
        xenrt.sleep(200)
        pinged = server.isPinged(startTime)
        xenrt.TEC().logverbose("Server was pinged: %s"%str(pinged))
        if not pinged:
            raise xenrt.XRTFailure("Server was not pinged when it should be")
        self.adapter.releaseLicense(self.getDefaultPool())
        if autoupdate.isLicensed():
            raise xenrt.XRTFailure("autoupdate is licensed when it shouldn't be")
        time = datetime.datetime.now()
        self.agent.restartAgent()
        xenrt.sleep(200)
        pinged = server.isPinged(startTime)
        if pinged:
            raise xenrt.XRTFailure("autoupdate tries to update when unlicensed")

class VSSQuiescedSnapshot(DotNetAgentTestCases):

    def run(self, arglist):
        self.adapter.applyLicense(self.getDefaultPool())
        vss = self.agent.getLicensedFeature("VSS")
        if not vss.isSnapshotPossible():
            raise xenrt.XRTFailure("snapshot failed in licensed pool")
        self.adapter.releaseLicense(self.getDefaultPool())
        if vss.isSnapshotPossible():
            raise xenrt.XRTFailure("snapshot succeeded in unlicensed pool")