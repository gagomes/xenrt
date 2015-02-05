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

    def _vdi(self, vm):
        return vm.asXapiObject().VDI()[0].uuid

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
