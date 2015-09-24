import xenrt
from xenrt.lib.xenserver.dotnetagentlicensing import *
from xenrt.enum import XenServerLicenseSKU
from xenrt.lib.xenserver.licensing import LicenseManager, XenServerLicenseFactory

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
        self.applyLicensedHost(hostOrPool, self.unLicensedPool)

    def checkLicenseState(self,hostOrPool):
        hostOrPool.checkLicenseState(self.licensedEdition)

    def cleanupLicense(self, hostOrPool):
        self.licenseManager.releaseLicense(hostOrPool)

    def upgradeTools(self):
        pass

    def exportVM(self, vm):
        vm.setState("DOWN")
        vmName = vm.getName()
        tmp = xenrt.resources.TempDirectory()
        path = "%s/%s" % (tmp.path(), vmName)
        vm.exportVM(path)
        vm.setState("DOWN")
        vm.uninstall()

    def importVM(self,vm,host):
        pass

    def serverCleanup(self):
        server = self.getGuest("server")
        guest.execguest("rm -rf store")
        guest.execguest("rm -rf logs")
        guest.reboot()

    def setUpServer(self,guest,port):
        guest.execguest("mkdir -p store")
        guest.execguest("mkdir -p logs")
        guest.execguest(" echo \"file contents\" > store/dotNetAgent.msi")  
        msi = {"dotNetAgent" : SSFile("dotNetAgent.msi","store/")}
        guest.execguest("python -m SimpleHTTPServer {0} > logs/server{0}.log 2>&1&".format(str(port)))
        return SimpleServer(str(port), msi, guest)

class DotNetAgentTestCases(xenrt.TestCase):

    def __init__(self):
        self.adapter = DotNetAgentAdapter(self.getGuest(xenrt.TEC().lookup("LICENSE_SERVER")))

    def postRun(self):
        self.adapter.cleanupLicense(self.getDefaultPool())
        self.adapter.serverCleanup()

class TempTest(DotNetAgentTestCases):

        def run(self,arglist):
            server = adapter.setUpServer(self.getGuest("server"),"16000")
            xenrt.TEC().logverbose(server.isPinged(100))
            # adapter.applyLicense(self.getDefaultPool())


