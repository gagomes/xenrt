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

    def prepare(self, arglist):

        self.memory = None
        self.vcpus = None
        self.cps = None
        self.template = None
        

        self.host = self.getDefaultHost()
        if self.tcsku.endswith("_XenApp"):
            distroarch = self.tcsku.replace("_XenApp", "")
            (self.distro, self.arch) = xenrt.getDistroAndArch(distroarch)
            self.template = self.getXenAppTemplate(self.distro)
        else:
            (self.distro, self.arch) = xenrt.getDistroAndArch(self.tcsku)
        
        self.assertHardware()
        self.getGuestParams()

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
        else:
            tname = self.host.getTemplate(distro=self.distro, arch=self.arch)

        tuuid = self.host.minimalList("template-list", args="name-label='%s'" % tname)[0]

        defMemory = int(self.host.genParamGet("template", tuuid, "memory-static-max"))/xenrt.MEGA
        defVCPUs = int(self.host.genParamGet("template", tuuid, "VCPUs-max"))

        return collections.namedtuple("TemplateParams", ["defaultMemory", "defaultVCPUs"])(defMemory, defVCPUs)

    def getGuestLimits(self):
        return xenrt.TEC().lookup(["GUEST_LIMITATIONS", self.distro])

    def getGuestParams(self):
        pass

    def assertHardware(self):
        pass

    def run(self, arglist):
        if self.runSubcase("installOS", (), "OS", "Install") != \
                xenrt.RESULT_PASS:
            return
        if self.guest.windows:
            if self.runSubcase("installDrivers", (), "OS", "Drivers") != \
                    xenrt.RESULT_PASS:
                return
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


    def installOS(self):
        self.guest = xenrt.lib.xenserver.guest.createVM(self.host,
                    xenrt.randomGuestName(self.distro, self.arch),
                    self.distro,
                    vcpus = self.vcpus,
                    corespersocket = self.cps,
                    memory = self.memory,
                    arch = self.arch,
                    vifs = xenrt.lib.xenserver.Guest.DEFAULT,
                    template = self.template,
                    notools = self.distro.startswith("solaris"))
        
        self.uninstallOnCleanup(self.guest)
        self.getLogsFrom(self.guest)
        self.guest.check()

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
        else:
            return "TC-26870"

class TCSmokeTestShadowPT(TCSmokeTestTemplateDefaults):
    # Template defaults on Shadow
    def getDefaultJiraTC(self):
        if xenrt.isWindows(self.tcsku):
            return "TC-26872"
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
        else:
            return "TC-26879"

    def getGuestParams(self):
        self.vcpus = 1

class TCSmokeTest2VCPUs(_TCSmokeTest):
    # 2 vCPUs, double default memory
    def getDefaultJiraTC(self):
        if xenrt.isWindows(self.tcsku):
            return "TC-26880"
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
        else:
            return "TC-26883"

    def getGuestParams(self):
        if xenrt.is32BitPV(self.distro, self.arch, release=self.host.productVersion):
            hostMaxMem = int(self.host.lookup("MAX_VM_MEMORY_LINUX32BIT"))
        else:
            hostMaxMem = int(self.host.lookup("MAX_VM_MEMORY"))

        glimits = self.getGuestLimits()

        if self.arch == "x86-32":
            guestMaxMem = int(glimits['MAXMEMORY'])
        else:
            guestMaxMem = int(glimits.get("MAXMEMORY64", glimits['MAXMEMORY']))

        self.memory = min(guestMaxMem, hostMaxMem)

class TCSmokeTestMaxvCPUs(_TCSmokeTest):
    # Max vCPUs, double default memory
    
    def getDefaultJiraTC(self):
        if xenrt.isWindows(self.tcsku):
            return "TC-26884"
        else:
            return "TC-26885"

    def getGuestParams(self):
        self.memory = self.getTemplateParams().defaultMemory * 2

        hostMaxVCPUs = int(self.host.lookup("MAX_VM_VCPUS"))

        glimits = self.getGuestLimits()
        
        if self.arch == "x86-32":
            guestMaxVCPUs = glimits.get('MAX_VM_VCPUS')
        else:
            guestMaxVCPUs = glimits.get("MAX_VM_VCPUS64", glimits.get("MAX_VM_CPUS"))

        if guestMaxVCPUs:
            guestMaxVCPUs = int(guestMaxVCPUs)
            self.vcpus = min(guestMaxVCPUs, hostMaxVCPUs)
        else:
            self.vcpus = hostMaxVCPUs

        if glimits.get("MAXSOCKETS") and int(glimits["MAXSOCKETS"]) < self.vcpus:
            if isinstance(self.host, xenrt.lib.xenserver.host.CreedenceHost):
                self.cps = self.vcpus/int(glimits["MAXSOCKETS"])
            else:
                # Can only do max sockets
                self.vcpus = int(glimits["MAXSOCKETS"])

class TCSmokeTestMinConfig(_TCSmokeTest):
    # Min vCPUS + memory
    def getDefaultJiraTC(self):
        if xenrt.isWindows(self.tcsku):
            return "TC-26886"
        else:
            return "TC-26887"

    def getGuestParams(self):
        self.vcpus = 1
        glimits = self.getGuestLimits()

        guestMinMem = int(glimits['MINMEMORY'])
        hostMinMem = int(self.host.lookup("MIN_VM_MEMORY"))
        hostMinMemForGuest = int(self.host.lookup(["VM_MIN_MEMORY_LIMITS", self.distro], "0"))
        self.memory = max(guestMinMem, hostMinMem, hostMinMemForGuest)

