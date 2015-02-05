import xenrt
from xenrt.lazylog import step
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
        args = self.parseArgsKeyValue(arglist)
        self._vm = self.getGuest(args["vm"])


class TCLicensingRCXapi(ReadCacheTestCase):
    """
    Use license state to switch on/off read caching and check xapi agrees
    """

    def run(self, arglist):
        host = self.getDefaultHost()
        rcc = host.readCaching()
        assertions.assertTrue(rcc.isEnabled())
        self._releaseLicense(host)
        self._vm.migrateVM(host)
        rcc.setVM(self._vm)
        assertions.assertFalse(rcc.isEnabled())


class TCXapiAndTapCtlAgree(ReadCacheTestCase):
    """
    Check low-level and xapi hooks agree
    """
    def run(self, arglist):
        host = self.getDefaultHost()
        rcc = host.readCaching()
        assertions.assertTrue(rcc.isEnabled())
        assertions.assertTrue(rcc.isEnabled(LowLevel=True))

        step("Switch off - low level")
        rcc.disable()
        self._vm.migrateVM(host)
        rcc.setVM(self._vm)
        assertions.assertFalse(rcc.isEnabled())
        assertions.assertFalse(rcc.isEnabled(LowLevel=True))

        step("Switch on - low level")
        rcc.enable()
        self._vm.migrateVM(host)
        rcc.setVM(self._vm)
        assertions.assertTrue(rcc.isEnabled())
        assertions.assertTrue(rcc.isEnabled(LowLevel=True))
