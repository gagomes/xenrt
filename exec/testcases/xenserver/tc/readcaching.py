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
        assertions.assertTrue(rcc.isEnabled(), "RC is enabled")
        self._releaseLicense(host)
        vm.migrateVM(host)
        rcc.setVM(vm)
        assertions.assertFalse(rcc.isEnabled(), "RC is disabled")


class TCXapiAndTapCtlAgree(ReadCacheTestCase):
    """
    Check low-level and xapi hooks agree
    """
    def run(self, arglist):
        vm = self.vm(arglist)
        host = self.getDefaultHost()
        self._applyMaxLicense(host)
        rcc = host.readCaching()
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
        assertions.assertEquals(expected, rcc.isEnabled(LowLevel=False))
        assertions.assertEquals(expected, rcc.isEnabled(LowLevel=True))


class TCRCForLifeCycleOps(ReadCacheTestCase):
    def run(self, arglist):
        host = self.getDefaultHost()
        rcc = host.readCaching()


