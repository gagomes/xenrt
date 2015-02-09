import xenrt
from xenrt.lazylog import step, log
from xenrt.lib import assertions
from xenrt.lib.xenserver.licensing import XenServerLicenceFactory as LF
from xenrt.enum import XenServerLicenceSKU


class ReadCacheTestCase(xenrt.TestCase):
    """
    FQP - https://info.citrite.net/x/s4O7S
    """

    def _releaseLicense(self):
        host = self.getDefaultHost()
        licence = LF().licenceForHost(host, XenServerLicenceSKU.Free)
        step("Applying license: %s" % licence.getEdition())
        host.licenseApply(None, licence)

    def _applyMaxLicense(self):
        host = self.getDefaultHost()
        licence = LF().maxLicenceSkuHost(host)
        step("Applying license: %s" % licence.getEdition())
        host.licenseApply(None, licence)

    def prepare(self, arglist):
        names = xenrt.TEC().registry.guestList()
        self.vm = self.getGuest(names[0])
        self._applyMaxLicense()
        host = self.getDefaultHost()
        rcc = host.readCaching()
        rcc.setVM(self.vm)
        rcc.enable()
        self.vm.migrateVM(host)

    def checkExpectedState(self, expectedState, lowlevel=False, both=False):
        host = self.getDefaultHost()
        rcc = host.readCaching()
        rcc.setVM(self.vm)
        if both:
            assertions.assertEquals(expectedState, rcc.isEnabled(LowLevel=True), "RC is enabled status via. tap-ctl")
            assertions.assertEquals(expectedState, rcc.isEnabled(LowLevel=False), "RC is enabled status via. xapi")
        else:
            assertions.assertEquals(expectedState, rcc.isEnabled(LowLevel=lowlevel), "RC is enabled status")

    def getArgs(self, arglist):
        args = self.parseArgsKeyValue(arglist)
        log("Args: %s" % args)
        if args.has_key("lowlevel"):
            lowlevel = args["lowlevel"] in ("yes", "true")
        else:
            lowlevel = False

        if args.has_key("bothChecks"):
            both = args["bothChecks"] in ("yes", "true")
        else:
            both = False

        return lowlevel, both


class TCLicensingRCEnabled(ReadCacheTestCase):

    def run(self, arglist):
        lowlevel, both = self.getArgs(arglist)
        step("Checking ReadCaching state enabled: LowLevel %s" % lowlevel)
        self.vm.migrateVM(self.getDefaultHost())
        self.checkExpectedState(True, lowlevel, both)


class TCLicensingRCDisabled(ReadCacheTestCase):

    def run(self, arglist):
        lowlevel, both = self.getArgs(arglist)
        self._releaseLicense()
        self.vm.migrateVM(self.getDefaultHost())
        step("Checking ReadCaching state disabled: LowLevel %s" % lowlevel)
        self.checkExpectedState(False, lowlevel, both)


class TCOdirectRCDisabled(ReadCacheTestCase):

    def run(self, arglist):
        lowlevel, both = self.getArgs(arglist)
        host = self.getDefaultHost()
        rcc = host.readCaching()
        rcc.setVM(self.vm)
        rcc.disable()
        step("Checking ReadCaching state disabled %s" % lowlevel)
        self.checkExpectedState(False, lowlevel, both)


class TCRCForLifeCycleOps(ReadCacheTestCase):
    """
    A6. Check lifecycle ops create a new tap-disk and hence trigger readcaching
    (dis|en)ablement
    """
    def run(self, arglist):
        host = self.getDefaultHost()
        rcc = host.readCaching()
        vm = self.vm
        lowlevel, both = self.getArgs(arglist)
        self.runSubcase("lifecycle", (vm,rcc,lowlevel,both,vm.reboot), "Lifecycle", "Reboot")
        self.runSubcase("lifecycle", (vm,rcc,lowlevel,both,self.pauseResume,vm), "Lifecycle", "PauseResume")
        self.runSubcase("lifecycle", (vm,rcc,lowlevel,both,self.stopStart,vm), "Lifecycle", "StopStart")
        self.runSubcase("lifecycle", (vm,rcc,lowlevel,both,vm.migrateVM,host), "Lifecycle", "LocalHostMigrate")

    def stopStart(self, vm):
        vm.shutdown()
        vm.start()

    def pauseResume(self, vm):
        vm.pause()
        vm.resume()

    def lifecycle(self, vm, rcc, lowlevel, both, op, *args):
        host = self.getDefaultHost()
        self._applyMaxLicense(host)
        rcc.setVM(vm)
        log(*args)
        op(*args)
        self.checkExpectedState(True, lowlevel, both)
        self._releaseLicense(host)
        rcc.setVM(vm)
        op(*args)
        self.checkExpectedState(False, lowlevel, both)
