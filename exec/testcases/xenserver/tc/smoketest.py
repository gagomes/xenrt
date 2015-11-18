#
# XenRT: Test harness for Xen and the XenServer product family
#
# VM smoketest standalone testcases
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy, os.path, collections
import xenrt, xenrt.lib.xenserver

class _TCSmokeTest(xenrt.TestCase):
    PAUSEUNPAUSE = False
    DISTRO = None
    ROOTDISK = None

    @property
    def minimalTest(self):
        return False

    def prepare(self, arglist):

        self.memory = None
        self.postInstallMemory = None
        self.vcpus = None
        self.cps = None
        self.template = None
        

        self.host = self.getDefaultHost()
        if self.DISTRO:
            # Workaroun CA-165205
            if self.DISTRO == "generic-linux" and self.host.lookup("GENERIC_LINUX_OS") in ("etch", "debian60"):
                self.DISTRO = "rhel5x"
            (self.distro, self.arch) = xenrt.getDistroAndArch(self.DISTRO)
        elif self.tcsku.endswith("_XenApp"):
            distroarch = self.tcsku.replace("_XenApp", "")
            (self.distro, self.arch) = xenrt.getDistroAndArch(distroarch)
            self.template = self.getXenAppTemplate(self.distro)
        else:
            (self.distro, self.arch) = xenrt.getDistroAndArch(self.tcsku)

        (self.installDistro, self.special) = self.host.resolveDistroName(self.distro)
        
        self.assertHardware()
        self.getGuestParams()

        # Workaround NOV-1 - set memory back to something sensible after install
        if self.installDistro == "sles112":
            if not self.memory:
                self.postInstallMemory = self.getTemplateParams().defaultMemory
            elif self.memory < 4096:
                self.postInstallMemory = self.memory

    def getXenAppTemplate(self, distro):
        if distro.startswith("w2k3"):
            start = "TEMPLATE_NAME_CPS"
        elif distro.startswith("ws08r2"):
            start = "TEMPLATE_NAME_CPS_2008R2"
        elif distro.startswith("ws08"):
            start = "TEMPLATE_NAME_CPS_2008"
        else:
            raise xenrt.XRTError("No XenApp template for %s" % distro)

        if distro.endswith("-x64"):
            template = "%s_64" % start
        else:
            template = start
        return self.host.chooseTemplate(template)

    def getTemplateParams(self):
        if self.template:
            tname = self.template
            tuuid = self.host.minimalList("template-list", args="name-label='%s'" % tname)[0]

            defMemory = int(self.host.genParamGet("template", tuuid, "memory-static-max"))/xenrt.MEGA
            defVCPUs = int(self.host.genParamGet("template", tuuid, "VCPUs-max"))

            return collections.namedtuple("TemplateParams", ["defaultMemory", "defaultVCPUs"])(defMemory, defVCPUs)
        else:
            return self.host.getTemplateParams(self.installDistro, self.arch)

    def getGuestLimits(self):
        return xenrt.TEC().lookup(["GUEST_LIMITATIONS", self.installDistro])

    def getGuestParams(self):
        pass

    def assertHardware(self):
        pass

    def run(self, arglist):
        # Skip update tests that don't actually do an update
        if 'UpdateTo' in self.special and not self.special['UpdateTo']:
            xenrt.TEC().skip("Don't need to run a null update test")
            return

        if self.runSubcase("installOS", (), "OS", "Install") != \
                xenrt.RESULT_PASS:
            return
        if self.guest.windows:
            if self.runSubcase("installDrivers", (), "OS", "Drivers") != \
                    xenrt.RESULT_PASS:
                return
        if self.postInstallMemory:
            if self.runSubcase("setMemory", (), "OS", "SetMemory") != \
                    xenrt.RESULT_PASS:
                return
        if not self.minimalTest:
            if self.runSubcase("lifecycle", (), "OS", "Lifecycle") != \
                    xenrt.RESULT_PASS:
                return
            if self.PAUSEUNPAUSE:
                if self.runSubcase("pauseunpause", (), "OS", "PauseUnpause") != \
                        xenrt.RESULT_PASS:
                    return
            else:
                if self.runSubcase("suspendresume", (), "OS", "SuspendResume") != \
                        xenrt.RESULT_PASS:
                    return
                if self.runSubcase("migrate", ("false"), "OS", "Migrate") != \
                        xenrt.RESULT_PASS:
                    return
                if self.runSubcase("migrate", ("true"), "OS", "LiveMigrate") != \
                        xenrt.RESULT_PASS:
                    return
            if self.runSubcase("settle", (), "OS", "Settle") != \
                    xenrt.RESULT_PASS:
                return
        if self.runSubcase("shutdown", (), "OS", "Shutdown") != \
                xenrt.RESULT_PASS:
            return

    def postRun(self):
        self.host.uninstallGuestByName(self.guestName)

    def checkGuestMemory(self, expected):
        """Validate the in-guest memory is what we expect (within 4%)"""
        if expected is None:
            return

        guestMemory = self.guest.os.visibleMemory
        difference = abs(expected - guestMemory)
        diffpct = (float(difference) / float(expected)) * 100
        if diffpct > 4 and difference > 30:
            raise xenrt.XRTFailure("Guest reports %uMB memory, expecting %uMB" % (guestMemory, expected))

    def setMemory(self):
        self.guest.shutdown()
        self.guest.memset(self.postInstallMemory)
        self.guest.start()

        # Check the in-guest memory matches what we expect
        self.checkGuestMemory(self.postInstallMemory)

    def installOS(self):

        disks = []
        if self.ROOTDISK:
            disks = [("0", self.ROOTDISK, False)] 

        self.guestName = xenrt.randomGuestName(self.distro, self.arch)
        self.guest = xenrt.lib.xenserver.guest.createVM(self.host,
                    self.guestName,
                    self.distro,
                    vcpus = self.vcpus,
                    corespersocket = self.cps,
                    memory = self.memory,
                    arch = self.arch,
                    vifs = xenrt.lib.xenserver.Guest.DEFAULT,
                    template = self.template,
                    notools = self.distro.startswith("solaris"),
                    disks=disks)
        
        self.getLogsFrom(self.guest)
        self.guest.check()

        # Check the in-guest memory matches what we expect
        self.checkGuestMemory(self.memory)

    def installDrivers(self):
        self.guest.installDrivers()

    def lifecycle(self):
        # Perform some lifecycle operations
        self.guest.reboot()
        self.guest.reboot()
        self.guest.shutdown()
        self.guest.start()
        self.guest.check()

    def suspendresume(self):
        for i in xrange(2):
            self.guest.suspend()
            self.guest.resume()
            self.guest.check()

    def pauseunpause(self):
        for i in xrange(2):
            self.guest.pause()
            xenrt.sleep(10)
            self.guest.unpause()
            self.guest.check()

    def shutdown(self):
        # Shutdown the VM (it will be uninstalled by the harness)
        self.guest.shutdown()

    def migrate(self, live):
        for i in range(int(xenrt.TEC().lookup("SMOKETEST_MIGRATE_COUNT", "2"))):
            self.guest.migrateVM(self.guest.host, live=live)
            time.sleep(10)
            self.guest.check()

    def settle(self):
        # Allow the VM to settle for a while
        time.sleep(180)
        self.guest.checkHealth()

class TCSmokeTestTemplateDefaults(_TCSmokeTest):
    # Template defaults
    def getDefaultJiraTC(self):
        if xenrt.isWindows(self.tcsku):
            return "TC-26871"
        elif xenrt.isDevLinux(self.tcsku):
            return "TC-26955"
        else:
            return "TC-26870"

    @property
    def minimalTest(self):
        # Only minimal test for dev linux guests
        return xenrt.isDevLinux(self.tcsku)

class TCSmokeTestShadowPT(TCSmokeTestTemplateDefaults):
    # Template defaults on Shadow
    def getDefaultJiraTC(self):
        if xenrt.isWindows(self.tcsku):
            return "TC-26872"
        elif xenrt.isDevLinux(self.tcsku):
            return "TC-26956"
        else:
            return "TC-26873"

    def assertHardware(self):
        if self.host.isHAPEnabled():
            raise xenrt.XRTError("This test requires a machine without HAP")

class TCSmokeTestIntelEPT(TCSmokeTestTemplateDefaults):
    # Template defaults on Intel + EPT
    def getDefaultJiraTC(self):
        if xenrt.isWindows(self.tcsku):
            return "TC-26874"
        elif xenrt.isDevLinux(self.tcsku):
            return "TC-26957"
        else:
            return "TC-26875"

    def assertHardware(self):
        if not self.host.isHAPEnabled():
            raise xenrt.XRTError("This test requires a machine with HAP")
        if not self.host.isVmxHardware():
            raise xenrt.XRTError("This test requires Intel hardware")

class TCSmokeTestAMDNPT(TCSmokeTestTemplateDefaults):
    # Template defaults on AMD + NPT
    def getDefaultJiraTC(self):
        if xenrt.isWindows(self.tcsku):
            return "TC-26876"
        elif xenrt.isDevLinux(self.tcsku):
            return "TC-26958"
        else:
            return "TC-26877"

    def assertHardware(self):
        if not self.host.isHAPEnabled():
            raise xenrt.XRTError("This test requires a machine with HAP")
        if not self.host.isSvmHardware():
            raise xenrt.XRTError("This test requires AMD hardware")
        pass

class TCSmokeTest1VCPU(_TCSmokeTest):
    # 1 vCPU, default memory
    def getDefaultJiraTC(self):
        if xenrt.isWindows(self.tcsku):
            return "TC-26878"
        elif xenrt.isDevLinux(self.tcsku):
            return "TC-26959"
        else:
            return "TC-26879"

    def getGuestParams(self):
        self.vcpus = 1

class TCSmokeTest2VCPUs(_TCSmokeTest):
    # 2 vCPUs, double default memory
    def getDefaultJiraTC(self):
        if xenrt.isWindows(self.tcsku):
            return "TC-26880"
        elif xenrt.isDevLinux(self.tcsku):
            return "TC-26960"
        else:
            return "TC-26881"

    def getGuestParams(self):
        self.vcpus = 2
        self.memory = self.getTemplateParams().defaultMemory * 2

class TCSmokeTestMaxMem(_TCSmokeTest):   
    # Default vCPUs, max memory
    # Pause/Unpause instead of suspend/resume + migrate
    PAUSEUNPAUSE = True
    
    def getDefaultJiraTC(self):
        if xenrt.isWindows(self.tcsku):
            return "TC-26882"
        elif xenrt.isDevLinux(self.tcsku):
            return "TC-26961"
        else:
            return "TC-26883"

    def getGuestParams(self):
        if xenrt.is32BitPV(self.distro, self.arch, release=self.host.productVersion):
            hostMaxMem = int(self.host.lookup("MAX_VM_MEMORY_LINUX32BIT"))
        elif xenrt.is64BitHVM(self.distro, self.arch, release=self.host.productVersion):
            hostMaxMem = int(self.host.lookup("MAX_VM_MEMORY_HVM"))
        else:
            hostMaxMem = int(self.host.lookup("MAX_VM_MEMORY"))

        glimits = self.getGuestLimits()

        if self.arch == "x86-32":
            guestMaxMem = int(glimits['MAXMEMORY'])
        elif glimits.has_key("MAXMEMORY"):
            guestMaxMem = int(glimits.get("MAXMEMORY64", glimits['MAXMEMORY']))
        else:
            guestMaxMem = int(glimits['MAXMEMORY64'])

        self.memory = min(guestMaxMem, hostMaxMem)

class TCSmokeTestMaxvCPUs(_TCSmokeTest):
    # Max vCPUs, double default memory
    
    def getDefaultJiraTC(self):
        if xenrt.isWindows(self.tcsku):
            return "TC-26884"
        elif xenrt.isDevLinux(self.tcsku):
            return "TC-26962"
        else:
            return "TC-26885"

    def getGuestParams(self):
        self.memory = self.getTemplateParams().defaultMemory * 2
        self.vcpus = "MAX"

    def checkGuestMemory(self, expected):
        xenrt.TEC().logverbose("Not checking guest reported memory in max vCPU tests (CA-187775)")
        return

class TCSmokeTestMinConfig(_TCSmokeTest):
    # Min vCPUS + memory
    def getDefaultJiraTC(self):
        if xenrt.isWindows(self.tcsku):
            return "TC-26886"
        elif xenrt.isDevLinux(self.tcsku):
            return "TC-26963"
        else:
            return "TC-26887"

    def getGuestParams(self):
        self.vcpus = 1
        glimits = self.getGuestLimits()

        guestMinMem = int(glimits['MINMEMORY'])
        hostMinMem = int(self.host.lookup("MIN_VM_MEMORY"))
        hostMinMemForGuest = int(self.host.lookup(["VM_MIN_MEMORY_LIMITS", self.installDistro], "0"))
        self.postInstallMemory = max(guestMinMem, hostMinMem, hostMinMemForGuest)

class TC8121(_TCSmokeTest):
    """Smoketest of a Linux VM with a very large root disk."""
    DISTRO = "generic-linux"
    ROOTDISK = 2000

class TC8120(_TCSmokeTest):
    """Smoketest of a Windows VM with a very large root disk."""
    DISTRO = "generic-windows"
    ROOTDISK = 2000


