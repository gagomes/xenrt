import xenrt
from xenrt.lazylog import step
from xenrt.lib import assertions
from xenrt.lib.xenserver.licensing import XenServerLicenceFactory as LF
from xenrt.enum import XenServerLicenceSKU


class ReadCacheTestCase(xenrt.TestCase):
    """
    FQP - https://info.citrite.net/x/s4O7S
    """

    def _releaseLicense(self, host):
        licence = LF().licenceForHost(host, XenServerLicenceSKU.Free)
        step("Applying license: %s" % licence.getEdition())
        host.licenseApply(None, licence)

    def _applyMaxLicense(self, host):
        licence = LF().maxLicenceSkuHost(host)
        step("Applying license: %s" % licence.getEdition())
        host.licenseApply(None, licence)

    def prepare(self, arglist):
        self._applyMaxLicense(self.getDefaultHost())
        host = self.getDefaultHost()
        vm = self.vm(arglist)
        vm.migrateVM(host)

    def vm(self, arglist):
        args = self.parseArgsKeyValue(arglist)
        return self.getGuest(args["vm"])


class TCLicensingRCXapi(ReadCacheTestCase):
    """
    A1. Use license state to switch on/off read caching and check xapi agrees
    """

    def run(self, arglist):
        host = self.getDefaultHost()
        vm = self.vm(arglist)
        rcc = host.readCaching()
        rcc.setVM(vm)

        step("Check Read Caching on...")
        assertions.assertTrue(rcc.isEnabled(), "RC is enabled via xapi")
        self._releaseLicense(host)
        vm.migrateVM(host)
        rcc.setVM(vm)

        step("Check Read Caching off...")
        assertions.assertFalse(rcc.isEnabled(), "RC is disabled via xapi")


class TCXapiAndTapCtlAgree(ReadCacheTestCase):
    """
    A2. Check low-level and xapi hooks agree
    """
    def run(self, arglist):
        vm = self.vm(arglist)
        host = self.getDefaultHost()
        rcc = host.readCaching()

        step("Initial check - verify on")
        self.__check(True, host, rcc, vm)

        step("Switch off - low level")
        rcc.disable()
        self.__check(False, host, rcc, vm)

        step("Switch on - low level")
        rcc.enable()
        self.__check(True, host, rcc, vm)

    def __check(self, expected, host, rcc, vm):
        vm.migrateVM(host)
        rcc.setVM(vm)
        assertions.assertEquals(expected, rcc.isEnabled(LowLevel=True), "RC enabled via tap-ctl")
        assertions.assertEquals(expected, rcc.isEnabled(LowLevel=False), "RC enabled via xapi")


class TCRCForLifeCycleOps(ReadCacheTestCase):
    """
    A6. Check lifecycle ops create a new tap-disk and hence trigger readcaching
    (dis|en)ablement
    """
    def run(self, arglist):
        host = self.getDefaultHost()
        rcc = host.readCaching()
        vm = self.vm(arglist)
        self.runSubcase("lifecycle", (vm,rcc,vm.reboot), "Lifecycle", "Reboot")
        self.runSubcase("lifecycle", (vm,rcc,self.pauseResume,vm), "Lifecycle", "PauseResume")
        self.runSubcase("lifecycle", (vm,rcc,self.stopStart,vm), "Lifecycle", "StopStart")
        self.runSubcase("lifecycle", (vm,rcc,vm.migrateVM,host), "Lifecycle", "LocalHostMigrate")

    def stopStart(vm):
        vm.shutdown()
        vm.start()

    def pauseResume(vm):
        vm.pause()
        vm.resume()

    def lifecycle(self, vm, rcc, op, *args):
        host = self.getDefaultHost()
        self._applyMaxLicense(host)
        rcc.setVM(vm)
        op(*args)
        assertions.assertTrue(rcc.isEnabled(), "RC is on")
        self._releaseLicense(host)
        rcc.setVM(vm)
        op(*args)
        assertions.assertFalse(rcc.isEnabled(), "RC is off")
