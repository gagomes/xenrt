import xenrt
from xenrt.lazylog import step, log
from xenrt.lib import assertions
from xenrt.lib.xenserver.licensing import XenServerLicenceFactory as LF
from xenrt.enum import XenServerLicenceSKU


class ReadCacheTestCase(xenrt.TestCase):

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
    Use license state to switch on/off read caching and check xapi agrees
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
    Check low-level and xapi hooks agree
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
    def run(self, arglist):
        host = self.getDefaultHost()
        rcc = host.readCaching()
        vm = self.vm(arglist)
        self.runSubcase(self.__lifecycle, (vm,rcc,vm.reboot), "Reboot", "Reboot")
        self.runSubcase(self.__lifecycle, (vm,rcc,self.__pauseResume,vm), "PauseResume", "PauseResume")
        self.runSubcase(self.__lifecycle, (vm,rcc,self.__stopStart,vm), "StopStart", "StopStart")
        self.runSubcase(self.__lifecycle, (vm,rcc,vm.migrateVM,host), "LocalHostMigrate", "LocalHostMigrate")

    def __stopStart(vm):
        vm.shutdown()
        vm.start()

    def __pauseResume(vm):
        vm.pause()
        vm.resume()

    def __lifecycle(self, vm, rcc, op, *args):
        self._applyMaxLicense()
        rcc.setVM(vm)
        op(*args)
        assertions.assertTrue(rcc.isEnabled(), "RC is on")
        self._releaseLicense()
        rcc.setVM(vm)
        op(*args)
        assertions.assertFalse(rcc.isEnabled(), "RC is off")
