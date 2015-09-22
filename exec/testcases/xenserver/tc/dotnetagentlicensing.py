import xenrt
from xenrt.lib.xenserver.dotnetagentlicensing import *
from xenrt.enum import XenServerLicenseSKU
from xenrt.lib.xenserver.licensing import LicenseManager, XenServerLicenseFactory
import xenrt.lazylog

class DotNetAgentAdapter(object):

    def __init__(self,licenseServer):
        self.licenseManager = licenseManager()
        self.licenseFactory = XenServerLicenseFactory()
        self.v6 = licenseServer
        self.v6.removeAllLicenses()
        self.licensedEdition = xenrt.TEC().lookup("LICENSED_EDITION")
        self.unlicensedEdition = xenrt.TEC().lookup("UNLICENSED_EDITION")

    def applyLicense(self, hostOrPool, sku = xenrt.TEC().lookup("LICENSED_EDITION")):
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
        vm.setState("DOWN")
        vmName = vm.getName()
        tmp = xenrt.resources.TempDirectory()
        path = "%s/%s" % (tmp.path(), vmName)
        vm.exportVM(path)
        vm.setState("DOWN")
        vm.uninstall()

    def importVM(self,vm,host):
        pass

    def setUpServer(self,guest):
        host = guest.host
        host.execDom0("mkdir store")
        host.execDom0("mkdir logs")
        host.execDom0(" echo \"file contents\" > store/dotNetAgent.msi")  
        msi = {"dotNetAgent" : SSFile("dotNetAgent.msi","store/")}
        host.execDom0("python -m SimpleHTTPServer 16000 > logs/server.log 2>&1")
        return SimpleServer("16000", msi, guest)


class TempTest(xenrt.TestCase):

        def run(self,arglist):
            adapter = DotNetAgentAdapter(self.getGuest(xenrt.TEC().lookup("LICENSE_SERVER")))
            server = adapter.setUpServer(self.getGuest("server"))
            log(server.isPinged(100))
            adapter.applyLicense(self.getDefaultPool())

