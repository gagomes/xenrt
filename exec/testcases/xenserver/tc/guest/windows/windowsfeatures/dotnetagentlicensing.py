import xenrt
from xenrt.lib.guest.windows.windowsfeatures.dotnetagent import *
from xenrt.enum import XenServerLicenseSKU
from xenrt.lib.xenserver.licensing import LicenseManager, XenServerLicenseFactory
from xenrt.lib.xenserver.tools.simpleserver import *

class DotNetAgentAdapter:
    self.licenseManager = None
    self.licenseFactory = None
    self.v6 = None
    self.licensedEdition = ""
    self.unlicensedEdition = ""

    def init(self,licenseServer):
        self.licenseManager = licenseManager()
        self.licenseFactory = XenServerLicenseFactory()
        self.v6 = licenseServer(xenrt.TEC().lookup("LICENSE_SERVER"))
        self.licensedEdition = xenrt.TEC().lookup("LICENSED_EDITION")
        self.unlicensedEdition = xenrt.TEC().lookup("UNLICENSED_EDITION")

    def applyLicense(self, hostOrPool, sku = self.licensedEdition):
        license = self.licenseFactory.licenseForPool(hostOrPool, sku)
        licenseinUse = self.licenseManager.addLicensesToServer(v6,license)
        self.licenseManager.applyLicense(v6, hostOrPool, license, licenseinUse)

    def releaseLicense(self, hostOrPool):
        self.applyLicensedHost(hostOrPool, self.unLicensedPool)

    def checkLicenseState(self,hostOrPool):
        hostOrPool.checkLicenseState(self.licensedEdition)

    def upgradeTools(self):
        pass

    def exportVM(self, vm):
        pass

    def importVM(self,vm,host):
        pass

    def setUpServer(self,guest):
        guest.getHost().execDom0("mkdir store")
        guest.getHost().execDom0("mkdir logs")
        guest.getHost().execDom0(" echo \"file contents\" > store/dotNetAgent.msi")  
        msi = {"dotNetAgent" : SSFile("dotNetAgent.msi","store/")}
        guest.getHost().execDom0("python -m SimpleHTTPServer 16000 > logs/server.log 2>&1")
        return SimpleServer("16000", msi, guest)


    class TempTest(xenrt.TestCase):

            def run(self,arglist):
                adapter = DotNetAgentAdapter(self.licenseServer)
                server = adapter.setUpServer(self.getGuest("server"))
                server.isPinged(100)

