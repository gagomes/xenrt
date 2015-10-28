import xenrt
from xenrt.lazylog import step, log
from xenrt.lib import assertions
from xenrt.lib.xenserver.licensing import XenServerLicenseFactory as LF
from xenrt.enum import XenServerLicenseSKU


class ReadCacheTestCase(xenrt.TestCase):
    """
    FQP - https://info.citrite.net/x/s4O7S
    """

    def _releaseLicense(self):
        host = self.getDefaultHost()
        license = LF().licenseForHost(host, XenServerLicenseSKU.Free)
        step("Applying license: %s" % license.getEdition())
        host.licenseApply(None, license)

    def _applyMaxLicense(self):
        host = self.getDefaultHost()
        license = LF().maxLicenseSkuHost(host)
        step("Applying license: %s" % license.getEdition())
        host.licenseApply(None, license)

    def _defaultLifeCycle(self, vm):
        step("Performing a lifecycle")
        vm.reboot()

    def prepare(self, arglist):
        self.vmName = self.parseArgsKeyValue(arglist)["vm"]
        log("Using vm %s" % self.vmName)
        self.vm = self.getGuest(self.vmName)
        self.srtype = self.vm.xapiObject.VDIs[0].SR.srType

        if self.vm.getState() != "UP":
            self.vm.start()

        self._applyMaxLicense()
        host = self.getDefaultHost()
        rcc = host.getReadCachingController()
        rcc.setVM(self.vm)
        rcc.enable()
        self._defaultLifeCycle(self.vm)

    def checkExpectedState(self, expectedState, lowlevel=False, both=False):
        step("Checking state - expected=%s, low-level=%s, bothChecks=%s" % (expectedState, lowlevel, both))
        host = self.getDefaultHost()
        rcc = host.getReadCachingController()
        rcc.setVM(self.vm)
        if both:
            step("Checking xapi status....")
            assertions.assertEquals(expectedState, rcc.isEnabled(lowLevel=False), "RC is enabled status via. xapi")
            step("Checking tapctl status....")
            assertions.assertEquals(expectedState, rcc.isEnabled(lowLevel=True), "RC is enabled status via. tap-ctl")
        else:
            step("Checking status of a single state...")
            assertions.assertEquals(expectedState, rcc.isEnabled(lowLevel=lowlevel), "RC is enabled status")

    def getArgs(self, arglist):
        args = self.parseArgsKeyValue(arglist)
        log("Args: %s" % args)
        lowlevel = args["lowlevel"] in ("yes", "true") if "lowlevel" in args else False
        both = args["bothChecks"] in ("yes", "true") if "bothChecks" in args else False
        return lowlevel, both


class TCLicensingRCEnabled(ReadCacheTestCase):

    def run(self, arglist):
        lowlevel, both = self.getArgs(arglist)
        step("Checking ReadCaching state enabled: lowLevel %s" % lowlevel)
        self.checkExpectedState(True, lowlevel, both)


class TCLicensingRCDisabled(ReadCacheTestCase):

    def run(self, arglist):
        lowlevel, both = self.getArgs(arglist)
        self._releaseLicense()
        self._defaultLifeCycle(self.vm)
        step("Checking ReadCaching state disabled: lowLevel %s" % lowlevel)
        self.checkExpectedState(False, lowlevel, both)


class TCOdirectRCDisabled(ReadCacheTestCase):

    def run(self, arglist):
        lowlevel, both = self.getArgs(arglist)
        host = self.getDefaultHost()
        rcc = host.getReadCachingController()
        rcc.setVM(self.vm)
        rcc.disable()
        self.vm.reboot()
        step("Checking ReadCaching state disabled %s" % lowlevel)
        self.checkExpectedState(False, lowlevel, both)


class TCRCForLifeCycleOps(ReadCacheTestCase):
    """
    A6. Check lifecycle ops create a new tap-disk and hence trigger readcaching
    (dis|en)ablement
    """
    def run(self, arglist):
        host = self.getDefaultHost()
        rcc = host.getReadCachingController()
        vm = self.vm
        lowlevel, both = self.getArgs(arglist)
        self.runSubcase("lifecycle", (vm, rcc, lowlevel, both, vm.reboot),
                        "Perform lifecycle", "Reboot")
        self.runSubcase("lifecycle", (vm, rcc, lowlevel, both, self.pauseResume, vm),
                        "Perform Lifecycle", "PauseResume")
        self.runSubcase("lifecycle", (vm, rcc, lowlevel, both, self.stopStart, vm),
                        "Perform Lifecycle", "StopStart")

    def stopStart(self, vm):
        vm.shutdown()
        vm.start()

    def pauseResume(self, vm):
        vm.suspend()
        vm.resume()

    def lifecycle(self, vm, rcc, lowlevel, both, op, *args):
        self._applyMaxLicense()
        rcc.setVM(vm)
        op(*args)
        self.checkExpectedState(True, lowlevel, both)
        self._releaseLicense()
        rcc.setVM(vm)
        op(*args)
        self.checkExpectedState(False, lowlevel, both)


class TCRCForSRPlug(ReadCacheTestCase):
    """
    A3. Verify SR re-attach persist status
    """

    def __init__(self):
        super(TCRCForSRPlug, self).__init__()
        self.__vdis = None

    def __storeVDIs(self):
        self.__vdis = self.vm.xapiObject.VDIs

    def __plugReplugSR(self):
        xsr = next((s for s in self.getDefaultHost().xapiObject.localSRs if s.srType == self.srtype), None)
        sr = xenrt.lib.xenserver.NFSStorageRepository.fromExistingSR(self.getDefaultHost(), xsr.uuid)
        sr.forget()
        sr.introduce()

    def __replugVm(self):
        if not self.__vdis:
            raise xenrt.Failure("Cannot find any VDI information. Are they stored before unplug SR?")

        # Plug the VDI to the VM
        xsr = next((s for s in self.getDefaultHost().xapiObject.localSRs if s.srType == self.srtype), None)
        for xvdi in self.__vdis:
            self.vm.createDisk(sizebytes=xvdi.size, sruuid=xsr.uuid, vdiuuid=xvdi.uuid, bootable=True)

    def run(self, arglist):
        lowlevel, both = self.getArgs(arglist)
        self.checkExpectedState(True, lowlevel, both)
        self.vm.shutdown()

        # Store VDI
        self.__storeVDIs()
        # Find the SR and forget/introduce
        self.__plugReplugSR()
        self.__replugVm()

        # Have a rest - you deserve it
        # At this point we could potentially have 2 vbds, one dangling and the new one, just added.
        # We need to wait for the xapi GC to kick in and clear the dangling ref otherwise we'll get an invalid handle
        xenrt.sleep(60)
        self.vm.setState("UP")
        self.vm.snapshot()
        self.checkExpectedState(True, lowlevel, both)
