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

class _TCNewSmokeTest(xenrt.TestCase):
    PAUSEUNPAUSE = False

    def prepare(self, arglist):

        self.memory = None
        self.vcpus = None
        self.cps = None
        self.template = None
        

        if self.tcsku.endswith("_XenApp"):
            distroarch = self.tcsku.replace("_XenApp", "")
            (self.distro, self.arch) = xenrt.getDistroAndArch(distroarch)
            self.template = self.getXenAppTemplate(self.distro)
        else:
            (self.distro, self.arch) = xenrt.getDistroAndArch(self.tcsku)
        
        self.host = self.getDefaultHost()
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
            return "%s_64" % start
        else:
            return start

    def getTemplateParams(self):
        if self.template:
            tname = self.host.chooseTemplate(self.template)
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

    def isPV(self):
        # Windows
        if self.distro[0] in ("v", "w"):
            return False
        # Solaris
        if self.distro.startswith("sol"):
            return False
        # HVM Linux
        return not self.distro in self.host.lookup("HVM_LINUX", "").split(",")

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

class TCSmokeTestTemplateDefaults(_TCNewSmokeTest):
    # Template defaults
    def getDefaultJiraTC(self):
        if xenrt.isWindows(self.tcsku):
            return "TC-26871"
        else:
            return "TC-26870"

class TCSmokeTestTemplateDefaultsShadowPT(TCSmokeTestTemplateDefaults):
    # Template defaults on Shadow
    def getDefaultJiraTC(self):
        if xenrt.isWindows(self.tcsku):
            return "TC-26872"
        else:
            return "TC-26873"

    def assertHardware(self):
        if self.host.isHAPEnabled():
            raise xenrt.XRTError("This test requires a machine without HAP")

class TCSmokeTestTemplateDefaultsIntelEPT(TCSmokeTestTemplateDefaults):
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

class TCSmokeTestTemplateDefaultsAMDNPT(TCSmokeTestTemplateDefaults):
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

class TCSmokeTest1VCPU(_TCNewSmokeTest):
    # 1 vCPU, default memory
    def getDefaultJiraTC(self):
        if xenrt.isWindows(self.tcsku):
            return "TC-26878"
        else:
            return "TC-26879"

    def getGuestParams(self):
        self.vcpus = 1

class TCSmokeTest2VCPUs(_TCNewSmokeTest):
    # 2 vCPUs, double default memory
    def getDefaultJiraTC(self):
        if xenrt.isWindows(self.tcsku):
            return "TC-26880"
        else:
            return "TC-26881"

    def getGuestParams(self):
        self.vcpus = 2
        self.memory = self.getTemplateParams().defaultMemory * 2

class TCSmokeTestMaxMem(_TCNewSmokeTest):   
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
            guestMaxMem = glimits['MAXMEMORY']
        else:
            guestMaxMem = glimits.get("MAXMEMORY64", glimits['MAXMEMORY'])

        self.memory = min(guestMaxMem, hostMaxMem)

class TCSmokeTestMaxvCPUs(_TCNewSmokeTest):
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
            self.vcpus = min(guestMaxVCPUs, hostMaxVCPUs)
        else:
            self.vcpus = hostMaxVCPUs

        if glimits.get("MAXSOCKETS") and int(glimits["MAXSOCKETS"]) < self.vcpus:
            if isinstance(self.host, xenrt.lib.xenserver.host.CreedenceHost):
                self.cps = self.vcpus/int(glimits["MAXSOCKETS"])
            else:
                # Can only do max sockets
                self.vcpus = int(glimits["MAXSOCKETS"])

class TCSmokeTestMinConfig(_TCNewSmokeTest):
    # Min vCPUS + memory
    def getDefaultJiraTC(self):
        if xenrt.isWindows(self.tcsku):
            return "TC-26886"
        else:
            return "TC-26887"

    def getGuestParams(self):
        self.vcpus = 1
        glimits = self.getGuestLimits()

        guestMinMem = glimits['MINMEMORY']
        hostMinMem = self.host.lookup("MIN_VM_MEMORY")
        hostMinMemForGuest = int(self.host.lookup(["VM_MIN_MEMORY_LIMITS", self.distro], "0"))
        self.memory = max(guestMinMem, hostMinMem, hostMinMemForGuest)

class _TCSmoketest(xenrt.TestCase):

    VCPUS = None
    CPS = None
    MEMORY = None
    ARCH = "x86-32"
    DISTRO = None
    VARCH = None
    TEMPLATE = None
    VERIFIER = False
    HIBERNATE = True
    MIGRATETEST = True
    EXTRASUSPENDTIME = True
    ROOTDISK = xenrt.lib.xenserver.Guest.DEFAULT

    def run(self, arglist):
        
        # Get a host to install on
        self.host = self.getDefaultHost()

        if self.VARCH == "VMX" and not self.host.isVmxHardware():
            raise xenrt.XRTError("Not running on VMX hardware")
        if self.VARCH == "VMXHAP" and not self.host.isVmxHardware():
            raise xenrt.XRTError("Not running on VMX hardware")
        if self.VARCH == "SVM" and not self.host.isSvmHardware():
            raise xenrt.XRTError("Not running on SVM hardware")
        if self.VARCH == "SVMHAP" and not self.host.isSvmHardware():
            raise xenrt.XRTError("Not running on SVM hardware")

        if self.runSubcase("installOS", (), "OS", "Install") != \
                xenrt.RESULT_PASS:
            return
        if self.guest.windows:
            if self.runSubcase("installDrivers", (), "OS", "Drivers") != \
                    xenrt.RESULT_PASS:
                return
        if xenrt.TEC().lookup("WORKAROUND_CA28908", False, boolean=True) \
               and ("win7" in self.DISTRO or "ws08r2" in self.DISTRO):
            xenrt.TEC().warning("Not checking viridian flag due to "
                                "CA-28908 workaround")
        if self.runSubcase("lifecycle", (), "OS", "Lifecycle") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("suspendresume", (), "OS", "SuspendResume") != \
                xenrt.RESULT_PASS:
            return
        if self.MIGRATETEST:
            if self.runSubcase("migrate", ("false"), "OS", "Migrate") != \
                    xenrt.RESULT_PASS:
                return
            if self.runSubcase("migrate", ("true"), "OS", "LiveMigrate") != \
                    xenrt.RESULT_PASS:
                return
        if self.host.lookup("SUPPORTS_HIBERNATE", True, boolean=True) and \
               self.guest.windows and self.guest.memory < 4096:
            if float(self.guest.xmlrpcWindowsVersion()) > 5.0 and \
                    float(self.guest.xmlrpcWindowsVersion()) < 5.99 and \
                    self.HIBERNATE:
                if self.runSubcase("hibernate", (), "OS", "Hibernate") != \
                       xenrt.RESULT_PASS:
                    return
        if self.runSubcase("settle", (), "OS", "Settle") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("shutdown", (), "OS", "Shutdown") != \
                xenrt.RESULT_PASS:
            return

    def installOS(self):        
        # Install the OS

        self.guest = xenrt.lib.xenserver.guest.createVM(self.host,
                    xenrt.randomGuestName(),
                    self.DISTRO,
                    vcpus = self.VCPUS,
                    corespersocket = self.CPS,
                    memory = self.MEMORY,
                    arch = self.ARCH,
                    vifs = xenrt.lib.xenserver.Guest.DEFAULT,
                    template = self.TEMPLATE,
                    notools = self.DISTRO.startswith("solaris"))
        
        self.uninstallOnCleanup(self.guest)
        self.getLogsFrom(self.guest)
        
        self.guest.check()

    def installDrivers(self):
        # Install drivers/tools if necessary
        self.guest.installDrivers()
        self.guest.waitForAgent(180)
        if self.VERIFIER:
            time.sleep(120)
            self.guest.enableDriverVerifier()

    def lifecycle(self):
        # Perform some lifecycle operations
        self.guest.reboot()
        self.guest.waitForAgent(180)
        self.guest.reboot()
        self.guest.waitForAgent(180)
        self.guest.shutdown()
        self.guest.start()
        self.guest.check()
        self.guest.waitForAgent(180)

    def suspendresume(self):
        if self.EXTRASUSPENDTIME:
            # Some large (e.g. 64G) VMs can take just over an hour to suspend
            # This has gone to the performance team for investigation, but for
            # now extend the timeout by 30 minutes
            self.guest.suspend(extraTimeout=3600)
        else:
            self.guest.suspend()
        self.guest.resume()
        self.guest.check()
        if self.EXTRASUSPENDTIME:
            self.guest.suspend(extraTimeout=3600)
        else:
            self.guest.suspend()
        self.guest.resume()
        self.guest.check()

    def shutdown(self):
        # Shutdown the VM (it will be uninstalled by the harness)
        self.guest.shutdown()

    def migrate(self, live):
        for i in range(int(xenrt.TEC().lookup("SMOKETEST_MIGRATE_COUNT", "1"))):
            self.guest.migrateVM(self.guest.host, live=live)
            time.sleep(10)
            self.guest.check()
            self.guest.migrateVM(self.guest.host, live=live)
            time.sleep(10)
            self.guest.check()

    def hibernate(self):
        self.guest.enableHibernation()
        self.guest.hibernate()
        self.guest.start(skipsniff=True)
        time.sleep(10)
        self.guest.hibernate()
        self.guest.start(skipsniff=True)
        time.sleep(10)
        self.guest.check()

    def settle(self):
        # Allow the VM to settle for a while
        time.sleep(180)
        self.guest.checkHealth()

############################################################################
# Manually defined tests                                                   #
############################################################################

class TC6923(_TCSmoketest):
    """OS functionality test of Windows 2003 EE SP2 using the CPS template default parameters."""
    DISTRO = "w2k3eesp2"
    TEMPLATE = "TEMPLATE_NAME_CPS"

class TC6924(_TCSmoketest):
    """OS functionality test of Windows 2003 EE SP2 x64 using CPS x64 template default parameters."""
    DISTRO = "w2k3eesp2-x64"
    TEMPLATE = "TEMPLATE_NAME_CPS_64"
    
class TC11030(_TCSmoketest):
    """OS functionality test of Windows Server 2008 SP2 using the XenApp template default parameters."""
    DISTRO = "ws08sp2-x86"
    TEMPLATE = "TEMPLATE_NAME_CPS_2008"

class TC11031(_TCSmoketest):
    """OS functionality test of Windows Server 2008 SP2 x64 using the XenApp template default parameters."""
    DISTRO = "ws08sp2-x64"
    TEMPLATE = "TEMPLATE_NAME_CPS_2008_64"

class TC11032(_TCSmoketest):
    """OS functionality test of Windows Server 2008 R2 x64 using the XenApp template default parameters."""
    DISTRO = "ws08r2-x64"
    TEMPLATE = "TEMPLATE_NAME_CPS_2008R2_64"

class TC6756(_TCSmoketest):
    """OS functionality test of Windows XP SP2 with driver verifier running."""
    DISTRO = "winxpsp2"
    VERIFIER = True
    VCPUS = 2
    HIBERNATE = False

class TC12004(_TCSmoketest):
    """OS functionality test of Windows XP SP3 with driver verifier running."""
    DISTRO = "winxpsp3"
    VERIFIER = True
    VCPUS = 2
    HIBERNATE = False

class TC6758(_TCSmoketest):
    """OS functionality test of Windows Server 2003 EE SP2 with driver verifier running (MP)."""
    DISTRO = "w2k3eesp2"
    VERIFIER = True
    VCPUS = 2

class TC6759(_TCSmoketest):
    """OS functionality test of Windows Server 2003 EE SP2 x64 with driver verifier running (MP)."""
    DISTRO = "w2k3eesp2-x64"
    VERIFIER = True
    VCPUS = 2

class TC6760(_TCSmoketest):
    """OS functionality test of Vista EE SP1 with driver verifier running (MP)."""
    DISTRO = "vistaeesp1"
    VERIFIER = True
    VCPUS = 2

class TC17775(_TCSmoketest):
    """OS functionality test of Vista EE SP2 with driver verifier running (MP)."""
    DISTRO = "vistaeesp2"
    VERIFIER = True
    VCPUS = 2

class TC6761(_TCSmoketest):
    """OS functionality test of Vista EE SP1 x64 with driver verifier running (MP)."""
    DISTRO = "vistaeesp1-x64"
    VERIFIER = True
    VCPUS = 2

class TC17776(_TCSmoketest):
    """OS functionality test of Vista EE SP2 x64 with driver verifier running (MP)."""
    DISTRO = "vistaeesp2-x64"
    VERIFIER = True
    VCPUS = 2

class TC8153(_TCSmoketest):
    """OS functionality test of Windows Server 2003 EE SP2 with driver verifier running (UP)."""
    DISTRO = "w2k3eesp2"
    VERIFIER = True
    VCPUS = 1

class TC8154(_TCSmoketest):
    """OS functionality test of Windows Server 2003 EE SP2 x64 with driver verifier running (UP)."""
    DISTRO = "w2k3eesp2-x64"
    VERIFIER = True
    VCPUS = 1

class TC8155(_TCSmoketest):
    """OS functionality test of Vista EE SP1 with driver verifier running (UP)."""
    DISTRO = "vistaeesp1"
    VERIFIER = True
    VCPUS = 1

class TC17773(_TCSmoketest):
    """OS functionality test of Vista EE SP2 with driver verifier running (UP)."""
    DISTRO = "vistaeesp2"
    VERIFIER = True
    VCPUS = 1

class TC8156(_TCSmoketest):
    """OS functionality test of Vista EE SP1 x64 with driver verifier running (UP)."""
    DISTRO = "vistaeesp1-x64"
    VERIFIER = True
    VCPUS = 1

class TC17774(_TCSmoketest):
    """OS functionality test of Vista EE SP2 x64 with driver verifier running (UP)."""
    DISTRO = "vistaeesp2-x64"
    VERIFIER = True
    VCPUS = 1

class TC9975(_TCSmoketest):
    """OS functionality test of Windows Server 2008 SP2 with driver verifier running (MP)."""
    DISTRO = "ws08sp2-x86"
    VERIFIER = True
    VCPUS = 2

class TC9976(_TCSmoketest):
    """OS functionality test of Windows Server 2008 SP2 x64 with driver verifier running (MP)."""
    DISTRO = "ws08sp2-x64"
    VERIFIER = True
    VCPUS = 2

class TC9977(_TCSmoketest):
    """OS functionality test of Windows Server 2008 R2 x64 with driver verifier running (MP)."""
    DISTRO = "ws08r2-x64"
    VERIFIER = True
    VCPUS = 2

class TC17777(_TCSmoketest):
    """OS functionality test of Windows Server 2008 R2 x64 with driver verifier running (MP)."""
    DISTRO = "ws08r2sp1-x64"
    VERIFIER = True
    VCPUS = 2

class TC17778(_TCSmoketest):
    """OS functionality test of Windows Server 2008 R2 x64 with driver verifier running (MP)."""
    DISTRO = "win7sp1-x64"
    VERIFIER = True
    VCPUS = 2

class TC17779(_TCSmoketest):
    """OS functionality test of Windows Server 2008 R2 x64 with driver verifier running (MP)."""
    DISTRO = "win7sp1-x86"
    VERIFIER = True
    VCPUS = 2

class TC6907(_TCSmoketest):
    """OS functionality test of Windows Server 2003 EE SP2 on Intel VT with 5GB memory and 1 vCPU."""
    DISTRO = "w2k3eesp2"
    MEMORY = 5120
    VCPUS = 1
    VARCH = "VMX"

class TC6908(_TCSmoketest):
    """OS functionality test of Windows Server 2003 EE SP2 on Intel VT with 5GB memory and 4 vCPUs."""
    DISTRO = "w2k3eesp2"
    MEMORY = 5120
    VCPUS = 4
    VARCH = "VMX"

class TC6909(_TCSmoketest):
    """OS functionality test of Windows Server 2003 EE SP2 on Intel VT with 1GB memory and 8 vCPUs."""
    DISTRO = "w2k3eesp2"
    MEMORY = 1024
    VCPUS = 8
    VARCH = "VMX"

class TC6910(_TCSmoketest):
    """OS functionality test of Windows Server 2003 EE SP2 on Intel VT with 1GB memory and 1 vCPU."""
    DISTRO = "w2k3eesp2"
    MEMORY = 1024
    VCPUS = 1
    VARCH = "VMX"

class TC8006(_TCSmoketest):
    """Smoketest of Windows XP SP1 x64"""
    DISTRO = "winxpsp1-x64"
    MEMORY = 1024
    VCPUS = 2
    HIBERNATE = False

class TC8121(_TCSmoketest):
    """Smoketest of a Linux VM with a very large root disk."""
    DISTRO = "rhel51"
    ROOTDISK = 2093049 

class TC8120(_TCSmoketest):
    """Smoketest of a Windows 2003 Server 2003 SP2 VM with a very large root disk."""
    DISTRO = "w2k3eesp2"
    ROOTDISK = 2093049

class TC8598(_TCSmoketest):
    """Operation of RHEL 4.6 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "rhel46"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Max vCPU tests for all HVM guests
class TC21911(_TCSmoketest):
    """Operation of Windows 7 SP1 x86 with 16 vcpus (8 cores per socket)"""
    DISTRO = "win7sp1-x86"
    VCPUS = 16
    MEMORY = 4096
    CPS = 8

class TC21912(_TCSmoketest):
    """Operation of Windows 7 SP1 x64 with 16 vcpus (8 cores per socket)"""
    DISTRO = "win7sp1-x64"
    VCPUS = 16
    MEMORY = 4096
    CPS = 8

class TC21913(_TCSmoketest):
    """Operation of Windows 8 x86 with 16 vcpus (8 cores per socket)"""
    DISTRO = "win8-x86"
    VCPUS = 16
    MEMORY = 4096
    CPS = 8

class TC21914(_TCSmoketest):
    """Operation of Windows 8 x64 with 16 vcpus (8 cores per socket)"""
    DISTRO = "win8-x64"
    VCPUS = 16
    MEMORY = 4096
    CPS = 8

class TC21915(_TCSmoketest):
    """Operation of Windows 8.1 x86 with 16 vcpus (8 cores per socket)"""
    DISTRO = "win81-x86"
    VCPUS = 16
    MEMORY = 4096
    CPS = 8

class TC21916(_TCSmoketest):
    """Operation of Windows 8.1 x64 with 16 vcpus (8 cores per socket)"""
    DISTRO = "win81-x64"
    VCPUS = 16
    MEMORY = 4096
    CPS = 8

class TC21917(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise with 16 vcpus"""
    DISTRO = "w2k3eesp2"
    VCPUS = 16
    MEMORY = 4096

class TC21918(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise x64 with 16 vcpus"""
    DISTRO = "w2k3eesp2-x64"
    VCPUS = 16
    MEMORY = 4096

class TC21919(_TCSmoketest):
    """Operation of Windows Server 2008 with 16 vcpus"""
    DISTRO = "ws08-x86"
    VCPUS = 16
    MEMORY = 4096

class TC21920(_TCSmoketest):
    """Operation of Windows Server 2008 x64 with 16 vcpus"""
    DISTRO = "ws08-x64"
    VCPUS = 16
    MEMORY = 4096

class TC21921(_TCSmoketest):
    """Operation of Windows Server 2008 R2 SP1 x64 with 16 vcpus"""
    DISTRO = "ws08r2sp1-x64"
    VCPUS = 16
    MEMORY = 4096

class TC21922(_TCSmoketest):
    """Operation of Windows Server 2012 x64 with 16 vcpus"""
    DISTRO = "ws12-x64"
    VCPUS = 16
    MEMORY = 4096

class TC21923(_TCSmoketest):
    """Operation of Windows Server 2012 R2 x64 with 16 vcpus"""
    DISTRO = "ws12r2-x64"
    VCPUS = 16
    MEMORY = 4096

class TC21924(_TCSmoketest):
    """Operation of Windows Vista EE SP1 with 16 vcpus (8 cores per socket)"""
    DISTRO = "vistaeesp1"
    VCPUS = 16
    MEMORY = 4096
    CPS = 8

class TC21925(_TCSmoketest):
    """Operation of Windows XP SP3 with 16 vcpus (8 cores per socket)"""
    DISTRO = "winxpsp3"
    VCPUS = 16
    MEMORY = 4096
    CPS = 8

class TC21926(_TCSmoketest):
    """Operation of RHEL 7 with with 32 vcpus"""
    DISTRO = "rhel7"
    ARCH = "x86-64"
    VCPUS = 32
    MEMORY = 4096

class TC21927(_TCSmoketest):
    """Operation of CentOS 7 with with 32 vcpus"""
    DISTRO = "centos7"
    ARCH = "x86-64"
    VCPUS = 32
    MEMORY = 4096

class TC21928(_TCSmoketest):
    """Operation of OEL 7 with with 32 vcpus"""
    DISTRO = "oel7"
    ARCH = "x86-64"
    VCPUS = 32
    MEMORY = 4096

class TC21929(_TCSmoketest):
    """Operation of Ubuntu 14.04 7 with with 32 vcpus"""
    DISTRO = "ubuntu1404"
    VCPUS = 32
    MEMORY = 4096

############################################################################
# Autogenerated tests                                                      #
############################################################################

# AUTOGEN

# Autogenerated class - do not edit
class TC10801(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.4 32 bit using template defaults"""
    DISTRO = "oel54"

# Autogenerated class - do not edit
class TC10802(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.4 64 bit using template defaults"""
    DISTRO = "oel54"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC10803(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.3 32 bit using template defaults"""
    DISTRO = "oel53"

# Autogenerated class - do not edit
class TC10804(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.3 64 bit using template defaults"""
    DISTRO = "oel53"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC10805(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.4 32 bit 1GB 2 vCPUs"""
    DISTRO = "oel54"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC10806(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.4 64 bit 1GB 2 vCPUs"""
    DISTRO = "oel54"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC10807(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.3 32 bit 1GB 2 vCPUs"""
    DISTRO = "oel53"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC10808(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.3 64 bit 1GB 2 vCPUs"""
    DISTRO = "oel53"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC10891(_TCSmoketest):
    """Operation of RHEL 5.4 32 bit using template defaults"""
    DISTRO = "rhel54"

# Autogenerated class - do not edit
class TC10892(_TCSmoketest):
    """Operation of RHEL 5.4 64 bit using template defaults"""
    DISTRO = "rhel54"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC10893(_TCSmoketest):
    """Operation of RHEL 5.4 32 bit 1GB 2 vCPUs"""
    DISTRO = "rhel54"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC10894(_TCSmoketest):
    """Operation of RHEL 5.4 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel54"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC10895(_TCSmoketest):
    """Operation of RHEL 5.4 32 bit 5GB 2 vCPUs"""
    DISTRO = "rhel54"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC10896(_TCSmoketest):
    """Operation of RHEL 5.4 64 bit 5GB 2 vCPUs"""
    DISTRO = "rhel54"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC10897(_TCSmoketest):
    """Operation of RHEL 5.4 32 bit 1GB maximum vCPUs"""
    DISTRO = "rhel54"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC10898(_TCSmoketest):
    """Operation of RHEL 5.4 64 bit 1GB maximum vCPUs"""
    DISTRO = "rhel54"
    MEMORY = 1024
    VCPUS = 8
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC10899(_TCSmoketest):
    """Operation of RHEL 5.4 32 bit maximum memory 2 vCPUs"""
    DISTRO = "rhel54"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC10900(_TCSmoketest):
    """Operation of RHEL 5.4 64 bit maximum memory 2 vCPUs"""
    DISTRO = "rhel54"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC10965(_TCSmoketest):
    """Operation of CentOS 5.4 32 bit using template defaults"""
    DISTRO = "centos54"

# Autogenerated class - do not edit
class TC10966(_TCSmoketest):
    """Operation of CentOS 5.4 64 bit using template defaults"""
    DISTRO = "centos54"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC10968(_TCSmoketest):
    """Operation of CentOS 5.4 32 bit 1GB 2 vCPUs"""
    DISTRO = "centos54"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC10969(_TCSmoketest):
    """Operation of CentOS 5.4 64 bit 1GB 2 vCPUs"""
    DISTRO = "centos54"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11384(_TCSmoketest):
    """Operation of SLES10 SP3 using template defaults"""
    DISTRO = "sles103"

# Autogenerated class - do not edit
class TC11385(_TCSmoketest):
    """Operation of SLES10 SP3 64 bit using template defaults"""
    DISTRO = "sles103"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11386(_TCSmoketest):
    """Operation of SLES10 SP3 1GB 2 vCPUs"""
    DISTRO = "sles103"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC11387(_TCSmoketest):
    """Operation of SLES10 SP3 64 bit 1GB 2 vCPUs"""
    DISTRO = "sles103"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11388(_TCSmoketest):
    """Operation of SLES10 SP3 5GB 2 vCPUs"""
    DISTRO = "sles103"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC11389(_TCSmoketest):
    """Operation of SLES10 SP3 64 bit 5GB 2 vCPUs"""
    DISTRO = "sles103"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11390(_TCSmoketest):
    """Operation of SLES10 SP3 1GB maximum vCPUs"""
    DISTRO = "sles103"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC11391(_TCSmoketest):
    """Operation of SLES10 SP3 64 bit 1GB maximum vCPUs"""
    DISTRO = "sles103"
    MEMORY = 1024
    VCPUS = 8
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11392(_TCSmoketest):
    """Operation of SLES10 SP3 maximum memory 2 vCPUs"""
    DISTRO = "sles103"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC11393(_TCSmoketest):
    """Operation of SLES10 SP3 64 bit maximum memory 2 vCPUs"""
    DISTRO = "sles103"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11741(_TCSmoketest):
    """Operation of RHEL 5.5 32 bit using template defaults"""
    DISTRO = "rhel55"

# Autogenerated class - do not edit
class TC11742(_TCSmoketest):
    """Operation of RHEL 5.5 64 bit using template defaults"""
    DISTRO = "rhel55"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11743(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.5 32 bit using template defaults"""
    DISTRO = "oel55"

# Autogenerated class - do not edit
class TC11744(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.5 64 bit using template defaults"""
    DISTRO = "oel55"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11745(_TCSmoketest):
    """Operation of CentOS 5.5 32 bit using template defaults"""
    DISTRO = "centos55"

# Autogenerated class - do not edit
class TC11746(_TCSmoketest):
    """Operation of CentOS 5.5 64 bit using template defaults"""
    DISTRO = "centos55"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11747(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.5 32 bit 1GB 2 vCPUs"""
    DISTRO = "oel55"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC11748(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.5 64 bit 1GB 2 vCPUs"""
    DISTRO = "oel55"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11749(_TCSmoketest):
    """Operation of CentOS 5.5 32 bit 1GB 2 vCPUs"""
    DISTRO = "centos55"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC11750(_TCSmoketest):
    """Operation of CentOS 5.5 64 bit 1GB 2 vCPUs"""
    DISTRO = "centos55"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11751(_TCSmoketest):
    """Operation of RHEL 5.5 32 bit 1GB 2 vCPUs"""
    DISTRO = "rhel55"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC11752(_TCSmoketest):
    """Operation of RHEL 5.5 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel55"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11753(_TCSmoketest):
    """Operation of RHEL 5.5 32 bit 5GB 2 vCPUs"""
    DISTRO = "rhel55"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC11754(_TCSmoketest):
    """Operation of RHEL 5.5 64 bit 5GB 2 vCPUs"""
    DISTRO = "rhel55"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11755(_TCSmoketest):
    """Operation of RHEL 5.5 32 bit 1GB maximum vCPUs"""
    DISTRO = "rhel55"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC11756(_TCSmoketest):
    """Operation of RHEL 5.5 64 bit 1GB maximum vCPUs"""
    DISTRO = "rhel55"
    MEMORY = 1024
    VCPUS = 8
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11757(_TCSmoketest):
    """Operation of RHEL 5.5 32 bit maximum memory 2 vCPUs"""
    DISTRO = "rhel55"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC11758(_TCSmoketest):
    """Operation of RHEL 5.5 64 bit maximum memory 2 vCPUs"""
    DISTRO = "rhel55"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11796(_TCSmoketest):
    """Operation of SLES11 SP1 using template defaults"""
    DISTRO = "sles111"

# Autogenerated class - do not edit
class TC11797(_TCSmoketest):
    """Operation of SLES11 SP1 64 bit using template defaults"""
    DISTRO = "sles111"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11798(_TCSmoketest):
    """Operation of SLES11 SP1 1GB 2 vCPUs"""
    DISTRO = "sles111"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC11799(_TCSmoketest):
    """Operation of SLES11 SP1 64 bit 1GB 2 vCPUs"""
    DISTRO = "sles111"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11800(_TCSmoketest):
    """Operation of SLES11 SP1 5GB 2 vCPUs"""
    DISTRO = "sles111"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC11801(_TCSmoketest):
    """Operation of SLES11 SP1 64 bit 5GB 2 vCPUs"""
    DISTRO = "sles111"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11802(_TCSmoketest):
    """Operation of SLES11 SP1 1GB maximum vCPUs"""
    DISTRO = "sles111"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC11803(_TCSmoketest):
    """Operation of SLES11 SP1 64 bit 1GB maximum vCPUs"""
    DISTRO = "sles111"
    MEMORY = 1024
    VCPUS = 8
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11804(_TCSmoketest):
    """Operation of SLES11 SP1 maximum memory 2 vCPUs"""
    DISTRO = "sles111"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC11805(_TCSmoketest):
    """Operation of SLES11 SP1 64 bit maximum memory 2 vCPUs"""
    DISTRO = "sles111"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11806(_TCSmoketest):
    """Operation of Windows Server 2003 SP1 Enterprise 1GB 2 vCPUs"""
    DISTRO = "w2k3eesp1"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC11807(_TCSmoketest):
    """Operation of Windows Vista SP1 Enterprise 1GB 2 vCPUs"""
    DISTRO = "vistaeesp1"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC11808(_TCSmoketest):
    """Operation of Windows Vista SP1 Enterprise x64 1GB 2 vCPUs"""
    DISTRO = "vistaeesp1-x64"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC11809(_TCSmoketest):
    """Operation of Windows Server 2008 Enterprise 1GB 2 vCPUs"""
    DISTRO = "ws08-x86"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC11810(_TCSmoketest):
    """Operation of Windows Server 2008 Enterprise x64 1GB 2 vCPUs"""
    DISTRO = "ws08-x64"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC11811(_TCSmoketest):
    """Operation of Windows Server 2003 SP0 Enterprise 1GB 2 vCPUs"""
    DISTRO = "w2k3ee"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC11853(_TCSmoketest):
    """Operation of RHEL 6.0 32 bit using template defaults"""
    DISTRO = "rhel6"

# Autogenerated class - do not edit
class TC11854(_TCSmoketest):
    """Operation of RHEL 6.0 64 bit using template defaults"""
    DISTRO = "rhel6"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11855(_TCSmoketest):
    """Operation of RHEL 6.0 32 bit 1GB 2 vCPUs"""
    DISTRO = "rhel6"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC11856(_TCSmoketest):
    """Operation of RHEL 6.0 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel6"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11857(_TCSmoketest):
    """Operation of RHEL 6.0 32 bit 5GB 2 vCPUs"""
    DISTRO = "rhel6"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC11858(_TCSmoketest):
    """Operation of RHEL 6.0 64 bit 5GB 2 vCPUs"""
    DISTRO = "rhel6"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11859(_TCSmoketest):
    """Operation of RHEL 6.0 32 bit 1GB maximum vCPUs"""
    DISTRO = "rhel6"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC11860(_TCSmoketest):
    """Operation of RHEL 6.0 64 bit 1GB maximum vCPUs"""
    DISTRO = "rhel6"
    MEMORY = 1024
    VCPUS = 8
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11861(_TCSmoketest):
    """Operation of RHEL 6.0 32 bit maximum memory 2 vCPUs"""
    DISTRO = "rhel6"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC11862(_TCSmoketest):
    """Operation of RHEL 6.0 64 bit maximum memory 2 vCPUs"""
    DISTRO = "rhel6"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC11904(_TCSmoketest):
    """Operation of Windows Server 2008 R2 SP1 Enterprise x64 using template defaults"""
    DISTRO = "ws08r2sp1-x64"

# Autogenerated class - do not edit
class TC11905(_TCSmoketest):
    """Operation of Windows 7 SP1 using template defaults"""
    DISTRO = "win7sp1-x86"

# Autogenerated class - do not edit
class TC11906(_TCSmoketest):
    """Operation of Windows 7 SP1 x64 using template defaults"""
    DISTRO = "win7sp1-x64"

# Autogenerated class - do not edit
class TC11907(_TCSmoketest):
    """Operation of Windows Server 2008 R2 SP1 Enterprise x64 1GB 2 vCPUs on Intel VT"""
    DISTRO = "ws08r2sp1-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC11908(_TCSmoketest):
    """Operation of Windows 7 SP1 1GB 2 vCPUs on Intel VT"""
    DISTRO = "win7sp1-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC11909(_TCSmoketest):
    """Operation of Windows 7 SP1 x64 1GB 2 vCPUs on Intel VT"""
    DISTRO = "win7sp1-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC11910(_TCSmoketest):
    """Operation of Windows Server 2008 R2 SP1 Enterprise x64 1GB 2 vCPUs on AMD-V"""
    DISTRO = "ws08r2sp1-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC11911(_TCSmoketest):
    """Operation of Windows 7 SP1 1GB 2 vCPUs on AMD-V"""
    DISTRO = "win7sp1-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC11912(_TCSmoketest):
    """Operation of Windows 7 SP1 x64 1GB 2 vCPUs on AMD-V"""
    DISTRO = "win7sp1-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC11913(_TCSmoketest):
    """Operation of Windows Server 2008 R2 SP1 Enterprise x64 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "ws08r2sp1-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC11914(_TCSmoketest):
    """Operation of Windows 7 SP1 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "win7sp1-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC11915(_TCSmoketest):
    """Operation of Windows 7 SP1 x64 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "win7sp1-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC11916(_TCSmoketest):
    """Operation of Windows Server 2008 R2 SP1 Enterprise x64 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "ws08r2sp1-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC11917(_TCSmoketest):
    """Operation of Windows 7 SP1 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "win7sp1-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC11918(_TCSmoketest):
    """Operation of Windows 7 SP1 x64 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "win7sp1-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC11919(_TCSmoketest):
    """Operation of Windows 7 x64 1GB 2 vCPUs"""
    DISTRO = "win7-x64"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC11920(_TCSmoketest):
    """Operation of Windows Server 2008 R2 SP1 Enterprise x64 5GB 2 vCPUs"""
    DISTRO = "ws08r2sp1-x64"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC11921(_TCSmoketest):
    """Operation of Windows 7 SP1 5GB 2 vCPUs"""
    DISTRO = "win7sp1-x86"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC11922(_TCSmoketest):
    """Operation of Windows 7 SP1 x64 5GB 2 vCPUs"""
    DISTRO = "win7sp1-x64"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC11923(_TCSmoketest):
    """Operation of Windows Server 2008 R2 SP1 Enterprise x64 1GB maximum vCPUs"""
    DISTRO = "ws08r2sp1-x64"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC11924(_TCSmoketest):
    """Operation of Windows 7 SP1 1GB maximum vCPUs"""
    DISTRO = "win7sp1-x86"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC11925(_TCSmoketest):
    """Operation of Windows 7 SP1 x64 1GB maximum vCPUs"""
    DISTRO = "win7sp1-x64"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC11926(_TCSmoketest):
    """Operation of Windows Server 2008 R2 SP1 Enterprise x64 maximum memory 2 vCPUs"""
    DISTRO = "ws08r2sp1-x64"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC11927(_TCSmoketest):
    """Operation of Windows 7 SP1 maximum memory 2 vCPUs"""
    DISTRO = "win7sp1-x86"
    MIGRATETEST = False
    MEMORY = 4096
    VCPUS = 2

# Autogenerated class - do not edit
class TC11928(_TCSmoketest):
    """Operation of Windows 7 SP1 x64 maximum memory 2 vCPUs"""
    DISTRO = "win7sp1-x64"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC13160(_TCSmoketest):
    """Operation of Solaris 10u9 32 bit using template defaults"""
    DISTRO = "solaris10u9"
    def lifecycle(self): pass
    def suspendresume(self): pass
    def migrate(self, live): pass
    def hibernate(self): pass

# Autogenerated class - do not edit
class TC13161(_TCSmoketest):
    """Operation of Solaris 10u9 64 bit using template defaults"""
    DISTRO = "solaris10u9"
    ARCH = "x86-64"
    def lifecycle(self): pass
    def suspendresume(self): pass
    def migrate(self, live): pass
    def hibernate(self): pass

# Autogenerated class - do not edit
class TC13162(_TCSmoketest):
    """Operation of Solaris 10u9 32 bit 1GB 2 vCPUs"""
    DISTRO = "solaris10u9"
    MEMORY = 1024
    VCPUS = 2
    def lifecycle(self): pass
    def suspendresume(self): pass
    def migrate(self, live): pass
    def hibernate(self): pass

# Autogenerated class - do not edit
class TC13163(_TCSmoketest):
    """Operation of Solaris 10u9 64 bit 1GB 2 vCPUs"""
    DISTRO = "solaris10u9"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"
    def lifecycle(self): pass
    def suspendresume(self): pass
    def migrate(self, live): pass
    def hibernate(self): pass

# Autogenerated class - do not edit
class TC13164(_TCSmoketest):
    """Operation of Solaris 10u9 32 bit 5GB 2 vCPUs"""
    DISTRO = "solaris10u9"
    MEMORY = 5120
    VCPUS = 2
    def lifecycle(self): pass
    def suspendresume(self): pass
    def migrate(self, live): pass
    def hibernate(self): pass

# Autogenerated class - do not edit
class TC13165(_TCSmoketest):
    """Operation of Solaris 10u9 64 bit 5GB 2 vCPUs"""
    DISTRO = "solaris10u9"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"
    def lifecycle(self): pass
    def suspendresume(self): pass
    def migrate(self, live): pass
    def hibernate(self): pass

# Autogenerated class - do not edit
class TC13171(_TCSmoketest):
    """Operation of RHEL 5.6 32 bit using template defaults"""
    DISTRO = "rhel56"

# Autogenerated class - do not edit
class TC13172(_TCSmoketest):
    """Operation of RHEL 5.6 64 bit using template defaults"""
    DISTRO = "rhel56"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13173(_TCSmoketest):
    """Operation of SLES10 SP4 using template defaults"""
    DISTRO = "sles104"

# Autogenerated class - do not edit
class TC13174(_TCSmoketest):
    """Operation of SLES10 SP4 64 bit using template defaults"""
    DISTRO = "sles104"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13175(_TCSmoketest):
    """Operation of Ubuntu 10.04 32 bit using template defaults"""
    DISTRO = "ubuntu1004"

# Autogenerated class - do not edit
class TC13176(_TCSmoketest):
    """Operation of Ubuntu 10.04 64 bit using template defaults"""
    DISTRO = "ubuntu1004"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13177(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.6 32 bit using template defaults"""
    DISTRO = "oel56"

# Autogenerated class - do not edit
class TC13178(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.6 64 bit using template defaults"""
    DISTRO = "oel56"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13179(_TCSmoketest):
    """Operation of RHEL 5.6 32 bit 1GB 2 vCPUs"""
    DISTRO = "rhel56"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC13180(_TCSmoketest):
    """Operation of RHEL 5.6 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel56"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13181(_TCSmoketest):
    """Operation of SLES10 SP4 1GB 2 vCPUs"""
    DISTRO = "sles104"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC13182(_TCSmoketest):
    """Operation of SLES10 SP4 64 bit 1GB 2 vCPUs"""
    DISTRO = "sles104"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13183(_TCSmoketest):
    """Operation of Ubuntu 10.04 32 bit 1GB 2 vCPUs"""
    DISTRO = "ubuntu1004"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC13184(_TCSmoketest):
    """Operation of Ubuntu 10.04 64 bit 1GB 2 vCPUs"""
    DISTRO = "ubuntu1004"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13185(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.6 32 bit 1GB 2 vCPUs"""
    DISTRO = "oel56"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC13186(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.6 64 bit 1GB 2 vCPUs"""
    DISTRO = "oel56"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13187(_TCSmoketest):
    """Operation of RHEL 5.6 32 bit 5GB 2 vCPUs"""
    DISTRO = "rhel56"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC13188(_TCSmoketest):
    """Operation of RHEL 5.6 64 bit 5GB 2 vCPUs"""
    DISTRO = "rhel56"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13189(_TCSmoketest):
    """Operation of SLES10 SP4 5GB 2 vCPUs"""
    DISTRO = "sles104"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC13190(_TCSmoketest):
    """Operation of SLES10 SP4 64 bit 5GB 2 vCPUs"""
    DISTRO = "sles104"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13191(_TCSmoketest):
    """Operation of Ubuntu 10.04 32 bit 5GB 2 vCPUs"""
    DISTRO = "ubuntu1004"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC13192(_TCSmoketest):
    """Operation of Ubuntu 10.04 64 bit 5GB 2 vCPUs"""
    DISTRO = "ubuntu1004"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13239(_TCSmoketest):
    """Operation of Debian 6.0 32 bit using template defaults"""
    DISTRO = "debian60"

# Autogenerated class - do not edit
class TC13240(_TCSmoketest):
    """Operation of Debian 6.0 64 bit using template defaults"""
    DISTRO = "debian60"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13241(_TCSmoketest):
    """Operation of Debian 6.0 32 bit 1GB 2 vCPUs"""
    DISTRO = "debian60"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC13242(_TCSmoketest):
    """Operation of Debian 6.0 64 bit 1GB 2 vCPUs"""
    DISTRO = "debian60"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13243(_TCSmoketest):
    """Operation of Debian 6.0 32 bit 5GB 2 vCPUs"""
    DISTRO = "debian60"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC13244(_TCSmoketest):
    """Operation of Debian 6.0 64 bit 5GB 2 vCPUs"""
    DISTRO = "debian60"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13420(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "w2k3eesp2"
    MIGRATETEST = False
    MEMORY = 65536
    VCPUS = 2

# Autogenerated class - do not edit
class TC13421(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise x64 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "w2k3eesp2-x64"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2

# Autogenerated class - do not edit
class TC13422(_TCSmoketest):
    """Operation of Windows XP SP3 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "winxpsp3"
    MIGRATETEST = False
    MEMORY = 4096
    ROOTDISK = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC13423(_TCSmoketest):
    """Operation of Windows Vista SP2 Enterprise maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "vistaeesp2"
    MIGRATETEST = False
    MEMORY = 4096
    VCPUS = 2

# Autogenerated class - do not edit
class TC13424(_TCSmoketest):
    """Operation of Windows Vista SP2 Enterprise x64 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "vistaeesp2-x64"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2

# Autogenerated class - do not edit
class TC13428(_TCSmoketest):
    """Operation of Windows 7 SP1 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "win7sp1-x86"
    MIGRATETEST = False
    MEMORY = 4096
    VCPUS = 2

# Autogenerated class - do not edit
class TC13429(_TCSmoketest):
    """Operation of Windows 7 SP1 x64 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "win7sp1-x64"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2

# Autogenerated class - do not edit
class TC13430(_TCSmoketest):
    """Operation of RHEL 5.6 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel56"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13431(_TCSmoketest):
    """Operation of RHEL 6.0 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel6"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13432(_TCSmoketest):
    """Operation of SLES10 SP4 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "sles104"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13433(_TCSmoketest):
    """Operation of SLES11 SP1 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "sles111"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13434(_TCSmoketest):
    """Operation of Ubuntu 10.04 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "ubuntu1004"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13435(_TCSmoketest):
    """Operation of Debian 6.0 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "debian60"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13436(_TCSmoketest):
    """Operation of Solaris 10u9 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "solaris10u9"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2
    ARCH = "x86-64"
    def lifecycle(self): pass
    def suspendresume(self): pass
    def migrate(self, live): pass
    def hibernate(self): pass

# Autogenerated class - do not edit
class TC13438(_TCSmoketest):
    """Operation of RHEL 4.8 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel48"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC13439(_TCSmoketest):
    """Operation of SLES9 SP4 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "sles94"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC13440(_TCSmoketest):
    """Operation of Debian Lenny 5.0 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "debian50"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC13441(_TCSmoketest):
    """Operation of RHEL 5.6 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel56"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC13442(_TCSmoketest):
    """Operation of RHEL 6.0 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel6"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC13443(_TCSmoketest):
    """Operation of SLES10 SP4 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "sles104"
    MIGRATETEST = False
    MEMORY = 65536
    VCPUS = 2

# Autogenerated class - do not edit
class TC13444(_TCSmoketest):
    """Operation of SLES11 SP1 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "sles111"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC13445(_TCSmoketest):
    """Operation of Ubuntu 10.04 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "ubuntu1004"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC13446(_TCSmoketest):
    """Operation of Debian 6.0 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "debian60"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC13447(_TCSmoketest):
    """Operation of Solaris 10u9 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "solaris10u9"
    MIGRATETEST = False
    MEMORY = 65536
    VCPUS = 2
    def lifecycle(self): pass
    def suspendresume(self): pass
    def migrate(self, live): pass
    def hibernate(self): pass

# Autogenerated class - do not edit
class TC13449(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "w2k3eesp2"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC13450(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise x64 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "w2k3eesp2-x64"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC13451(_TCSmoketest):
    """Operation of Windows XP SP3 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "winxpsp3"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC13452(_TCSmoketest):
    """Operation of Windows Vista SP2 Enterprise 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "vistaeesp2"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC13453(_TCSmoketest):
    """Operation of Windows Vista SP2 Enterprise x64 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "vistaeesp2-x64"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC13457(_TCSmoketest):
    """Operation of Windows 7 SP1 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "win7sp1-x86"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC13458(_TCSmoketest):
    """Operation of Windows 7 SP1 x64 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "win7sp1-x64"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC13459(_TCSmoketest):
    """Operation of RHEL 4.8 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel48"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC13460(_TCSmoketest):
    """Operation of SLES9 SP4 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "sles94"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC13461(_TCSmoketest):
    """Operation of Debian Lenny 5.0 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "debian50"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC13462(_TCSmoketest):
    """Operation of RHEL 5.6 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel56"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC13463(_TCSmoketest):
    """Operation of RHEL 6.0 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel6"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC13464(_TCSmoketest):
    """Operation of SLES10 SP4 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "sles104"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC13465(_TCSmoketest):
    """Operation of SLES11 SP1 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "sles111"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC13466(_TCSmoketest):
    """Operation of Ubuntu 10.04 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "ubuntu1004"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC13467(_TCSmoketest):
    """Operation of Debian 6.0 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "debian60"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC13468(_TCSmoketest):
    """Operation of Solaris 10u9 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "solaris10u9"
    MEMORY = 1024
    VCPUS = 32
    def lifecycle(self): pass
    def suspendresume(self): pass
    def migrate(self, live): pass
    def hibernate(self): pass

# Autogenerated class - do not edit
class TC13469(_TCSmoketest):
    """Operation of RHEL 5.6 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel56"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13470(_TCSmoketest):
    """Operation of RHEL 6.0 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel6"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13471(_TCSmoketest):
    """Operation of SLES10 SP4 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "sles104"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13472(_TCSmoketest):
    """Operation of SLES11 SP1 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "sles111"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13473(_TCSmoketest):
    """Operation of Ubuntu 10.04 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "ubuntu1004"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13474(_TCSmoketest):
    """Operation of Debian 6.0 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "debian60"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC13475(_TCSmoketest):
    """Operation of Solaris 10u9 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "solaris10u9"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"
    def lifecycle(self): pass
    def suspendresume(self): pass
    def migrate(self, live): pass
    def hibernate(self): pass

# Autogenerated class - do not edit
class TC14019(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.6 32 bit 5GB 2 vCPUs"""
    DISTRO = "oel56"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC14020(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.6 64 bit 5GB 2 vCPUs"""
    DISTRO = "oel56"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC14021(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.6 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel56"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC14022(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.6 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel56"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC14023(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.6 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel56"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC14024(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.6 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel56"
    MIGRATETEST = False
    MEMORY = 65536
    VCPUS = 2

# Autogenerated class - do not edit
class TC14614(_TCSmoketest):
    """Operation of CentOS 5.6 32 bit using template defaults"""
    DISTRO = "centos56"

# Autogenerated class - do not edit
class TC14616(_TCSmoketest):
    """Operation of CentOS 5.6 64 bit using template defaults"""
    DISTRO = "centos56"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC14618(_TCSmoketest):
    """Operation of CentOS 5.6 32 bit 1GB 2 vCPUs"""
    DISTRO = "centos56"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC14620(_TCSmoketest):
    """Operation of CentOS 5.6 64 bit 1GB 2 vCPUs"""
    DISTRO = "centos56"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC14622(_TCSmoketest):
    """Operation of CentOS 5.6 32 bit 5GB 2 vCPUs"""
    DISTRO = "centos56"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC14624(_TCSmoketest):
    """Operation of CentOS 5.6 64 bit 5GB 2 vCPUs"""
    DISTRO = "centos56"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC14626(_TCSmoketest):
    """Operation of CentOS 5.6 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos56"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC14628(_TCSmoketest):
    """Operation of CentOS 5.6 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos56"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC14630(_TCSmoketest):
    """Operation of CentOS 5.6 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos56"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC14632(_TCSmoketest):
    """Operation of CentOS 5.6 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos56"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC14839(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.0 64 bit 1GB 2 vCPUs"""
    DISTRO = "oel6"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC14846(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.0 32 bit using template defaults"""
    DISTRO = "oel6"

# Autogenerated class - do not edit
class TC14847(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.0 64 bit using template defaults"""
    DISTRO = "oel6"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC14848(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.0 32 bit 1GB 2 vCPUs"""
    DISTRO = "oel6"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC14850(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.0 32 bit 5GB 2 vCPUs"""
    DISTRO = "oel6"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC14851(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.0 64 bit 5GB 2 vCPUs"""
    DISTRO = "oel6"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC14852(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.0 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel6"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC14853(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.0 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel6"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC14859(_TCSmoketest):
    """Operation of Windows Server 2008 R2 SP1 Datacenter x64 using template defaults"""
    DISTRO = "ws08r2dcsp1-x64"

# Autogenerated class - do not edit
class TC14860(_TCSmoketest):
    """Operation of Windows Server 2008 R2 SP1 Datacenter x64 1GB 2 vCPUs on Intel VT"""
    DISTRO = "ws08r2dcsp1-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC14861(_TCSmoketest):
    """Operation of Windows Server 2008 R2 SP1 Datacenter x64 1GB 2 vCPUs on AMD-V"""
    DISTRO = "ws08r2dcsp1-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC14862(_TCSmoketest):
    """Operation of Windows Server 2008 R2 SP1 Datacenter x64 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "ws08r2dcsp1-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC14863(_TCSmoketest):
    """Operation of Windows Server 2008 R2 SP1 Datacenter x64 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "ws08r2dcsp1-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC14864(_TCSmoketest):
    """Operation of Windows Server 2008 R2 SP1 Datacenter x64 5GB 2 vCPUs"""
    DISTRO = "ws08r2dcsp1-x64"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC14865(_TCSmoketest):
    """Operation of Windows Server 2008 R2 SP1 Datacenter x64 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "ws08r2dcsp1-x64"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC14866(_TCSmoketest):
    """Operation of Windows Server 2008 R2 SP1 Datacenter x64 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "ws08r2dcsp1-x64"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2

# Autogenerated class - do not edit
class TC14869(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Datacenter using template defaults"""
    DISTRO = "ws08dcsp2-x86"

# Autogenerated class - do not edit
class TC14870(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Datacenter x64 using template defaults"""
    DISTRO = "ws08dcsp2-x64"

# Autogenerated class - do not edit
class TC14871(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Datacenter 1GB 2 vCPUs on Intel VT"""
    DISTRO = "ws08dcsp2-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC14872(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Datacenter x64 1GB 2 vCPUs on Intel VT"""
    DISTRO = "ws08dcsp2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC14873(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Datacenter 1GB 2 vCPUs on AMD-V"""
    DISTRO = "ws08dcsp2-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC14874(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Datacenter x64 1GB 2 vCPUs on AMD-V"""
    DISTRO = "ws08dcsp2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC14875(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Datacenter 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "ws08dcsp2-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC14876(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Datacenter x64 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "ws08dcsp2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC14877(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Datacenter 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "ws08dcsp2-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC14878(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Datacenter x64 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "ws08dcsp2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC14879(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Datacenter 5GB 2 vCPUs"""
    DISTRO = "ws08dcsp2-x86"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC14880(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Datacenter x64 5GB 2 vCPUs"""
    DISTRO = "ws08dcsp2-x64"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC14881(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Datacenter 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "ws08dcsp2-x86"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC14882(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Datacenter x64 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "ws08dcsp2-x64"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC14883(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Datacenter maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "ws08dcsp2-x86"
    MIGRATETEST = False
    MEMORY = 65536
    VCPUS = 2

# Autogenerated class - do not edit
class TC14884(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Datacenter x64 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "ws08dcsp2-x64"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2

# Autogenerated class - do not edit
class TC15171(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.0 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel6"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15172(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.0 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel6"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC15424(_TCSmoketest):
    """Operation of RHEL 5.7 32 bit using template defaults"""
    DISTRO = "rhel57"

# Autogenerated class - do not edit
class TC15425(_TCSmoketest):
    """Operation of CentOS 5.7 32 bit using template defaults"""
    DISTRO = "centos57"

# Autogenerated class - do not edit
class TC15426(_TCSmoketest):
    """Operation of CentOS 6.0 32 bit using template defaults"""
    DISTRO = "centos6"

# Autogenerated class - do not edit
class TC15427(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.7 32 bit using template defaults"""
    DISTRO = "oel57"

# Autogenerated class - do not edit
class TC15428(_TCSmoketest):
    """Operation of RHEL 5.7 64 bit using template defaults"""
    DISTRO = "rhel57"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15429(_TCSmoketest):
    """Operation of CentOS 5.7 64 bit using template defaults"""
    DISTRO = "centos57"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15430(_TCSmoketest):
    """Operation of CentOS 6.0 64 bit using template defaults"""
    DISTRO = "centos6"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15431(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.7 64 bit using template defaults"""
    DISTRO = "oel57"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15432(_TCSmoketest):
    """Operation of RHEL 5.7 32 bit 1GB 2 vCPUs"""
    DISTRO = "rhel57"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC15433(_TCSmoketest):
    """Operation of CentOS 5.7 32 bit 1GB 2 vCPUs"""
    DISTRO = "centos57"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC15434(_TCSmoketest):
    """Operation of CentOS 6.0 32 bit 1GB 2 vCPUs"""
    DISTRO = "centos6"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC15435(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.7 32 bit 1GB 2 vCPUs"""
    DISTRO = "oel57"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC15436(_TCSmoketest):
    """Operation of RHEL 5.7 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel57"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15437(_TCSmoketest):
    """Operation of CentOS 5.7 64 bit 1GB 2 vCPUs"""
    DISTRO = "centos57"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15438(_TCSmoketest):
    """Operation of CentOS 6.0 64 bit 1GB 2 vCPUs"""
    DISTRO = "centos6"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15439(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.7 64 bit 1GB 2 vCPUs"""
    DISTRO = "oel57"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15440(_TCSmoketest):
    """Operation of RHEL 5.7 32 bit 5GB 2 vCPUs"""
    DISTRO = "rhel57"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC15441(_TCSmoketest):
    """Operation of CentOS 5.7 32 bit 5GB 2 vCPUs"""
    DISTRO = "centos57"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC15442(_TCSmoketest):
    """Operation of CentOS 6.0 32 bit 5GB 2 vCPUs"""
    DISTRO = "centos6"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC15443(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.7 32 bit 5GB 2 vCPUs"""
    DISTRO = "oel57"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC15444(_TCSmoketest):
    """Operation of RHEL 5.7 64 bit 5GB 2 vCPUs"""
    DISTRO = "rhel57"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15445(_TCSmoketest):
    """Operation of CentOS 5.7 64 bit 5GB 2 vCPUs"""
    DISTRO = "centos57"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15446(_TCSmoketest):
    """Operation of CentOS 6.0 64 bit 5GB 2 vCPUs"""
    DISTRO = "centos6"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15447(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.7 64 bit 5GB 2 vCPUs"""
    DISTRO = "oel57"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15448(_TCSmoketest):
    """Operation of RHEL 5.7 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel57"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC15449(_TCSmoketest):
    """Operation of CentOS 5.7 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos57"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC15450(_TCSmoketest):
    """Operation of CentOS 6.0 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos6"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC15451(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.7 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel57"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC15452(_TCSmoketest):
    """Operation of RHEL 5.7 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel57"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15453(_TCSmoketest):
    """Operation of CentOS 5.7 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos57"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15454(_TCSmoketest):
    """Operation of CentOS 6.0 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos6"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15455(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.7 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel57"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15456(_TCSmoketest):
    """Operation of RHEL 5.7 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel57"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15457(_TCSmoketest):
    """Operation of CentOS 5.7 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos57"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15458(_TCSmoketest):
    """Operation of CentOS 6.0 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos6"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15459(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.7 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel57"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15460(_TCSmoketest):
    """Operation of RHEL 5.7 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel57"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC15461(_TCSmoketest):
    """Operation of CentOS 5.7 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos57"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC15462(_TCSmoketest):
    """Operation of CentOS 6.0 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos6"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC15463(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.7 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel57"
    MIGRATETEST = False
    MEMORY = 65536
    VCPUS = 2

# Autogenerated class - do not edit
class TC15877(_TCSmoketest):
    """Operation of Windows Server Enterprise Edition SP2 with PAE Enabled using template defaults"""
    DISTRO = "w2k3eesp2pae"

# Autogenerated class - do not edit
class TC15878(_TCSmoketest):
    """Operation of Windows Server Enterprise Edition SP2 with PAE Enabled 1GB 2 vCPUs on Intel VT"""
    DISTRO = "w2k3eesp2pae"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC15879(_TCSmoketest):
    """Operation of Windows Server Enterprise Edition SP2 with PAE Enabled 1GB 2 vCPUs on AMD-V"""
    DISTRO = "w2k3eesp2pae"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC15880(_TCSmoketest):
    """Operation of Windows Server Enterprise Edition SP2 with PAE Enabled 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "w2k3eesp2pae"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC15881(_TCSmoketest):
    """Operation of Windows Server Enterprise Edition SP2 with PAE Enabled 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "w2k3eesp2pae"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC15882(_TCSmoketest):
    """Operation of Windows Server Enterprise Edition SP2 with PAE Enabled 5GB 2 vCPUs"""
    DISTRO = "w2k3eesp2pae"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC15883(_TCSmoketest):
    """Operation of Windows Server Enterprise Edition SP2 with PAE Enabled 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "w2k3eesp2pae"
    MEMORY = 1024
    VCPUS = 4

# Autogenerated class - do not edit
class TC15884(_TCSmoketest):
    """Operation of Windows Server Enterprise Edition SP2 with PAE Enabled maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "w2k3eesp2pae"
    MIGRATETEST = False
    MEMORY = 65536
    VCPUS = 2

# Autogenerated class - do not edit
class TC15885(_TCSmoketest):
    """Operation of RHEL 6.1 32 bit using template defaults"""
    DISTRO = "rhel61"

# Autogenerated class - do not edit
class TC15886(_TCSmoketest):
    """Operation of CentOS 6.1 32 bit using template defaults"""
    DISTRO = "centos61"

# Autogenerated class - do not edit
class TC15887(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.1 32 bit using template defaults"""
    DISTRO = "oel61"

# Autogenerated class - do not edit
class TC15888(_TCSmoketest):
    """Operation of RHEL 6.1 64 bit using template defaults"""
    DISTRO = "rhel61"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15889(_TCSmoketest):
    """Operation of CentOS 6.1 64 bit using template defaults"""
    DISTRO = "centos61"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15890(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.1 64 bit using template defaults"""
    DISTRO = "oel61"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15891(_TCSmoketest):
    """Operation of RHEL 6.1 32 bit 1GB 2 vCPUs"""
    DISTRO = "rhel61"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC15892(_TCSmoketest):
    """Operation of CentOS 6.1 32 bit 1GB 2 vCPUs"""
    DISTRO = "centos61"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC15893(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.1 32 bit 1GB 2 vCPUs"""
    DISTRO = "oel61"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC15894(_TCSmoketest):
    """Operation of RHEL 6.1 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel61"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15895(_TCSmoketest):
    """Operation of CentOS 6.1 64 bit 1GB 2 vCPUs"""
    DISTRO = "centos61"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15896(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.1 64 bit 1GB 2 vCPUs"""
    DISTRO = "oel61"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15897(_TCSmoketest):
    """Operation of RHEL 6.1 32 bit 5GB 2 vCPUs"""
    DISTRO = "rhel61"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC15898(_TCSmoketest):
    """Operation of CentOS 6.1 32 bit 5GB 2 vCPUs"""
    DISTRO = "centos61"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC15899(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.1 32 bit 5GB 2 vCPUs"""
    DISTRO = "oel61"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC15900(_TCSmoketest):
    """Operation of RHEL 6.1 64 bit 5GB 2 vCPUs"""
    DISTRO = "rhel61"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15901(_TCSmoketest):
    """Operation of CentOS 6.1 64 bit 5GB 2 vCPUs"""
    DISTRO = "centos61"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15902(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.1 64 bit 5GB 2 vCPUs"""
    DISTRO = "oel61"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15903(_TCSmoketest):
    """Operation of RHEL 6.1 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel61"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC15904(_TCSmoketest):
    """Operation of CentOS 6.1 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos61"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC15905(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.1 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel61"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC15906(_TCSmoketest):
    """Operation of RHEL 6.1 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel61"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15907(_TCSmoketest):
    """Operation of CentOS 6.1 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos61"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15908(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.1 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel61"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15909(_TCSmoketest):
    """Operation of RHEL 6.1 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel61"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15910(_TCSmoketest):
    """Operation of CentOS 6.1 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos61"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15911(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.1 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel61"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC15912(_TCSmoketest):
    """Operation of RHEL 6.1 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel61"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC15913(_TCSmoketest):
    """Operation of CentOS 6.1 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos61"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC15914(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.1 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel61"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC17243(_TCSmoketest):
    """Operation of RHEL 6.2 32 bit using template defaults"""
    DISTRO = "rhel62"

# Autogenerated class - do not edit
class TC17244(_TCSmoketest):
    """Operation of CentOS 6.2 32 bit using template defaults"""
    DISTRO = "centos62"

# Autogenerated class - do not edit
class TC17245(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.2 32 bit using template defaults"""
    DISTRO = "oel62"

# Autogenerated class - do not edit
class TC17246(_TCSmoketest):
    """Operation of RHEL 6.2 64 bit using template defaults"""
    DISTRO = "rhel62"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC17247(_TCSmoketest):
    """Operation of CentOS 6.2 64 bit using template defaults"""
    DISTRO = "centos62"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC17248(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.2 64 bit using template defaults"""
    DISTRO = "oel62"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC17251(_TCSmoketest):
    """Operation of RHEL 6.2 32 bit 1GB 2 vCPUs"""
    DISTRO = "rhel62"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC17252(_TCSmoketest):
    """Operation of CentOS 6.2 32 bit 1GB 2 vCPUs"""
    DISTRO = "centos62"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC17253(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.2 32 bit 1GB 2 vCPUs"""
    DISTRO = "oel62"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC17254(_TCSmoketest):
    """Operation of RHEL 6.2 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel62"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC17255(_TCSmoketest):
    """Operation of CentOS 6.2 64 bit 1GB 2 vCPUs"""
    DISTRO = "centos62"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC17256(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.2 64 bit 1GB 2 vCPUs"""
    DISTRO = "oel62"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC17259(_TCSmoketest):
    """Operation of RHEL 6.2 32 bit 5GB 2 vCPUs"""
    DISTRO = "rhel62"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC17260(_TCSmoketest):
    """Operation of CentOS 6.2 32 bit 5GB 2 vCPUs"""
    DISTRO = "centos62"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC17261(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.2 32 bit 5GB 2 vCPUs"""
    DISTRO = "oel62"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC17262(_TCSmoketest):
    """Operation of RHEL 6.2 64 bit 5GB 2 vCPUs"""
    DISTRO = "rhel62"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC17263(_TCSmoketest):
    """Operation of CentOS 6.2 64 bit 5GB 2 vCPUs"""
    DISTRO = "centos62"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC17264(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.2 64 bit 5GB 2 vCPUs"""
    DISTRO = "oel62"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC17266(_TCSmoketest):
    """Operation of RHEL 6.2 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel62"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC17267(_TCSmoketest):
    """Operation of CentOS 6.2 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos62"
    MEMORY = 1024
    VCPUS = 16

 # Autogenerated class - do not edit
class TC17268(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.2 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel62"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC17269(_TCSmoketest):
    """Operation of RHEL 6.2 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel62"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC17270(_TCSmoketest):
    """Operation of CentOS 6.2 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos62"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC17271(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.2 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel62"
    MEMORY = 1024
    VCPUS = 16
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC17272(_TCSmoketest):
    """Operation of RHEL 6.2 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel62"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC17273(_TCSmoketest):
    """Operation of CentOS 6.2 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos62"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC17274(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.2 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel62"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC17275(_TCSmoketest):
    """Operation of RHEL 6.2 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel62"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC17276(_TCSmoketest):
    """Operation of CentOS 6.2 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos62"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC17277(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.2 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel62"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC17745(_TCSmoketest):
    """Operation of Ubuntu 12.04 32 bit using template defaults"""
    DISTRO = "ubuntu1204"

# Autogenerated class - do not edit
class TC17746(_TCSmoketest):
    """Operation of Ubuntu 12.04 64 bit using template defaults"""
    DISTRO = "ubuntu1204"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC17747(_TCSmoketest):
    """Operation of Ubuntu 12.04 32 bit 1GB 2 vCPUs"""
    DISTRO = "ubuntu1204"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC17748(_TCSmoketest):
    """Operation of Ubuntu 12.04 64 bit 1GB 2 vCPUs"""
    DISTRO = "ubuntu1204"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC17749(_TCSmoketest):
    """Operation of Ubuntu 12.04 32 bit 5GB 2 vCPUs"""
    DISTRO = "ubuntu1204"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC17750(_TCSmoketest):
    """Operation of Ubuntu 12.04 64 bit 5GB 2 vCPUs"""
    DISTRO = "ubuntu1204"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC17751(_TCSmoketest):
    """Operation of Ubuntu 12.04 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "ubuntu1204"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC17752(_TCSmoketest):
    """Operation of Ubuntu 12.04 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "ubuntu1204"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC17753(_TCSmoketest):
    """Operation of Ubuntu 12.04 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "ubuntu1204"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC17754(_TCSmoketest):
    """Operation of Ubuntu 12.04 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "ubuntu1204"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC18409(_TCSmoketest):
    """Operation of Windows 8 using template defaults"""
    DISTRO = "win8-x86"

# Autogenerated class - do not edit
class TC18410(_TCSmoketest):
    """Operation of Windows 8 x64 using template defaults"""
    DISTRO = "win8-x64"

# Autogenerated class - do not edit
class TC18411(_TCSmoketest):
    """Operation of Windows Server 2012 x64 using template defaults"""
    DISTRO = "ws12-x64"

# Autogenerated class - do not edit
class TC18412(_TCSmoketest):
    """Operation of Windows Server2012 Core x64 using template defaults"""
    DISTRO = "ws12core-x64"

# Autogenerated class - do not edit
class TC18413(_TCSmoketest):
    """Operation of Windows 8 1GB 2 vCPUs on Intel VT"""
    DISTRO = "win8-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC18414(_TCSmoketest):
    """Operation of Windows 8 x64 1GB 2 vCPUs on Intel VT"""
    DISTRO = "win8-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC18415(_TCSmoketest):
    """Operation of Windows Server 2012 x64 1GB 2 vCPUs on Intel VT"""
    DISTRO = "ws12-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC18416(_TCSmoketest):
    """Operation of Windows Server2012 Core x64 1GB 2 vCPUs on Intel VT"""
    DISTRO = "ws12core-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC18417(_TCSmoketest):
    """Operation of Windows 8 1GB 2 vCPUs on AMD-V"""
    DISTRO = "win8-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC18418(_TCSmoketest):
    """Operation of Windows 8 x64 1GB 2 vCPUs on AMD-V"""
    DISTRO = "win8-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC18419(_TCSmoketest):
    """Operation of Windows Server 2012 x64 1GB 2 vCPUs on AMD-V"""
    DISTRO = "ws12-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC18420(_TCSmoketest):
    """Operation of Windows Server2012 Core x64 1GB 2 vCPUs on AMD-V"""
    DISTRO = "ws12core-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC18421(_TCSmoketest):
    """Operation of Windows 8 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "win8-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC18422(_TCSmoketest):
    """Operation of Windows 8 x64 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "win8-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC18423(_TCSmoketest):
    """Operation of Windows Server 2012 x64 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "ws12-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC18424(_TCSmoketest):
    """Operation of Windows Server2012 Core x64 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "ws12core-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC18425(_TCSmoketest):
    """Operation of Windows 8 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "win8-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC18426(_TCSmoketest):
    """Operation of Windows 8 x64 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "win8-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC18427(_TCSmoketest):
    """Operation of Windows Server 2012 x64 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "ws12-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC18428(_TCSmoketest):
    """Operation of Windows Server2012 Core x64 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "ws12core-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC18429(_TCSmoketest):
    """Operation of Windows 8 5GB 2 vCPUs"""
    DISTRO = "win8-x86"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC18430(_TCSmoketest):
    """Operation of Windows 8 x64 5GB 2 vCPUs"""
    DISTRO = "win8-x64"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC18431(_TCSmoketest):
    """Operation of Windows Server 2012 x64 5GB 2 vCPUs"""
    DISTRO = "ws12-x64"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC18432(_TCSmoketest):
    """Operation of Windows Server2012 Core x64 5GB 2 vCPUs"""
    DISTRO = "ws12core-x64"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC18433(_TCSmoketest):
    """Operation of Windows 8 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "win8-x86"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC18434(_TCSmoketest):
    """Operation of Windows 8 x64 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "win8-x64"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC18435(_TCSmoketest):
    """Operation of Windows Server 2012 x64 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "ws12-x64"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC18436(_TCSmoketest):
    """Operation of Windows Server2012 Core x64 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "ws12core-x64"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC18437(_TCSmoketest):
    """Operation of Windows 8 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "win8-x86"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2

# Autogenerated class - do not edit
class TC18438(_TCSmoketest):
    """Operation of Windows 8 x64 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "win8-x64"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2

# Autogenerated class - do not edit
class TC18439(_TCSmoketest):
    """Operation of Windows Server 2012 x64 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "ws12-x64"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2

# Autogenerated class - do not edit
class TC18440(_TCSmoketest):
    """Operation of Windows Server2012 Core x64 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "ws12core-x64"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2

# Autogenerated class - do not edit
class TC19630(_TCSmoketest):
    """Operation of RHEL 5.8 64 bit using template defaults"""
    DISTRO = "rhel58"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19631(_TCSmoketest):
    """Operation of RHEL 5.9 64 bit using template defaults"""
    DISTRO = "rhel59"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19632(_TCSmoketest):
    """Operation of RHEL 6.3 64 bit using template defaults"""
    DISTRO = "rhel63"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19633(_TCSmoketest):
    """Operation of RHEL 6.4 64 bit using template defaults"""
    DISTRO = "rhel64"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19634(_TCSmoketest):
    """Operation of CentOS 5.8 64 bit using template defaults"""
    DISTRO = "centos58"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19635(_TCSmoketest):
    """Operation of CentOS 5.9 64 bit using template defaults"""
    DISTRO = "centos59"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19636(_TCSmoketest):
    """Operation of CentOS 6.3 64 bit using template defaults"""
    DISTRO = "centos63"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19637(_TCSmoketest):
    """Operation of CentOS 6.4 64 bit using template defaults"""
    DISTRO = "centos64"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19638(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.8 64 bit using template defaults"""
    DISTRO = "oel58"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19639(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.9 64 bit using template defaults"""
    DISTRO = "oel59"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19640(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.3 64 bit using template defaults"""
    DISTRO = "oel63"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19641(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.4 64 bit using template defaults"""
    DISTRO = "oel64"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19642(_TCSmoketest):
    """Operation of SLES11 SP2 64 bit using template defaults"""
    DISTRO = "sles112"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19643(_TCSmoketest):
    """Operation of Debian 7.0 64 bit using template defaults"""
    DISTRO = "debian70"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19644(_TCSmoketest):
    """Operation of RHEL 5.8 32 bit using template defaults"""
    DISTRO = "rhel58"

# Autogenerated class - do not edit
class TC19645(_TCSmoketest):
    """Operation of RHEL 5.9 32 bit using template defaults"""
    DISTRO = "rhel59"

# Autogenerated class - do not edit
class TC19646(_TCSmoketest):
    """Operation of RHEL 6.3 32 bit using template defaults"""
    DISTRO = "rhel63"

# Autogenerated class - do not edit
class TC19647(_TCSmoketest):
    """Operation of RHEL 6.4 32 bit using template defaults"""
    DISTRO = "rhel64"

# Autogenerated class - do not edit
class TC19648(_TCSmoketest):
    """Operation of CentOS 5.8 32 bit using template defaults"""
    DISTRO = "centos58"

# Autogenerated class - do not edit
class TC19649(_TCSmoketest):
    """Operation of CentOS 5.9 32 bit using template defaults"""
    DISTRO = "centos59"

# Autogenerated class - do not edit
class TC19650(_TCSmoketest):
    """Operation of CentOS 6.3 32 bit using template defaults"""
    DISTRO = "centos63"

# Autogenerated class - do not edit
class TC19651(_TCSmoketest):
    """Operation of CentOS 6.4 32 bit using template defaults"""
    DISTRO = "centos64"

# Autogenerated class - do not edit
class TC19652(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.8 32 bit using template defaults"""
    DISTRO = "oel58"

# Autogenerated class - do not edit
class TC19653(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.9 32 bit using template defaults"""
    DISTRO = "oel59"

# Autogenerated class - do not edit
class TC19654(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.3 32 bit using template defaults"""
    DISTRO = "oel63"

# Autogenerated class - do not edit
class TC19655(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.4 32 bit using template defaults"""
    DISTRO = "oel64"

# Autogenerated class - do not edit
class TC19656(_TCSmoketest):
    """Operation of SLES11 SP2 using template defaults"""
    DISTRO = "sles112"

# Autogenerated class - do not edit
class TC19657(_TCSmoketest):
    """Operation of Debian 7.0 32 bit using template defaults"""
    DISTRO = "debian70"

# Autogenerated class - do not edit
class TC19658(_TCSmoketest):
    """Operation of RHEL 5.8 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel58"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19659(_TCSmoketest):
    """Operation of RHEL 5.9 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel59"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19660(_TCSmoketest):
    """Operation of RHEL 6.3 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel63"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19661(_TCSmoketest):
    """Operation of RHEL 6.4 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel64"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19662(_TCSmoketest):
    """Operation of CentOS 5.8 64 bit 1GB 2 vCPUs"""
    DISTRO = "centos58"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19663(_TCSmoketest):
    """Operation of CentOS 5.9 64 bit 1GB 2 vCPUs"""
    DISTRO = "centos59"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19664(_TCSmoketest):
    """Operation of CentOS 6.3 64 bit 1GB 2 vCPUs"""
    DISTRO = "centos63"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19665(_TCSmoketest):
    """Operation of CentOS 6.4 64 bit 1GB 2 vCPUs"""
    DISTRO = "centos64"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19666(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.8 64 bit 1GB 2 vCPUs"""
    DISTRO = "oel58"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19667(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.9 64 bit 1GB 2 vCPUs"""
    DISTRO = "oel59"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19668(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.3 64 bit 1GB 2 vCPUs"""
    DISTRO = "oel63"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19669(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.4 64 bit 1GB 2 vCPUs"""
    DISTRO = "oel64"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19670(_TCSmoketest):
    """Operation of SLES11 SP2 64 bit 1GB 2 vCPUs"""
    DISTRO = "sles112"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19671(_TCSmoketest):
    """Operation of Debian 7.0 64 bit 1GB 2 vCPUs"""
    DISTRO = "debian70"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19672(_TCSmoketest):
    """Operation of RHEL 5.8 32 bit 1GB 2 vCPUs"""
    DISTRO = "rhel58"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC19673(_TCSmoketest):
    """Operation of RHEL 5.9 32 bit 1GB 2 vCPUs"""
    DISTRO = "rhel59"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC19674(_TCSmoketest):
    """Operation of RHEL 6.3 32 bit 1GB 2 vCPUs"""
    DISTRO = "rhel63"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC19675(_TCSmoketest):
    """Operation of RHEL 6.4 32 bit 1GB 2 vCPUs"""
    DISTRO = "rhel64"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC19676(_TCSmoketest):
    """Operation of CentOS 5.8 32 bit 1GB 2 vCPUs"""
    DISTRO = "centos58"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC19677(_TCSmoketest):
    """Operation of CentOS 5.9 32 bit 1GB 2 vCPUs"""
    DISTRO = "centos59"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC19678(_TCSmoketest):
    """Operation of CentOS 6.3 32 bit 1GB 2 vCPUs"""
    DISTRO = "centos63"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC19679(_TCSmoketest):
    """Operation of CentOS 6.4 32 bit 1GB 2 vCPUs"""
    DISTRO = "centos64"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC19680(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.8 32 bit 1GB 2 vCPUs"""
    DISTRO = "oel58"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC19681(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.9 32 bit 1GB 2 vCPUs"""
    DISTRO = "oel59"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC19682(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.3 32 bit 1GB 2 vCPUs"""
    DISTRO = "oel63"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC19683(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.4 32 bit 1GB 2 vCPUs"""
    DISTRO = "oel64"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC19684(_TCSmoketest):
    """Operation of SLES11 SP2 1GB 2 vCPUs"""
    DISTRO = "sles112"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC19685(_TCSmoketest):
    """Operation of Debian 7.0 32 bit 1GB 2 vCPUs"""
    DISTRO = "debian70"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC19686(_TCSmoketest):
    """Operation of RHEL 5.8 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel58"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19687(_TCSmoketest):
    """Operation of RHEL 5.9 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel59"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19688(_TCSmoketest):
    """Operation of RHEL 6.3 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel63"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19689(_TCSmoketest):
    """Operation of RHEL 6.4 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel64"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19690(_TCSmoketest):
    """Operation of CentOS 5.8 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos58"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19691(_TCSmoketest):
    """Operation of CentOS 5.9 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos59"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19692(_TCSmoketest):
    """Operation of CentOS 6.3 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos63"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19693(_TCSmoketest):
    """Operation of CentOS 6.4 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos64"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19694(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.8 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel58"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19695(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.9 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel59"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19696(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.3 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel63"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19697(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.4 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel64"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19698(_TCSmoketest):
    """Operation of SLES11 SP2 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "sles112"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19699(_TCSmoketest):
    """Operation of Debian 7.0 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "debian70"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19700(_TCSmoketest):
    """Operation of RHEL 5.8 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel58"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC19701(_TCSmoketest):
    """Operation of RHEL 5.9 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel59"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC19702(_TCSmoketest):
    """Operation of RHEL 6.3 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel63"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC19703(_TCSmoketest):
    """Operation of RHEL 6.4 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel64"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC19704(_TCSmoketest):
    """Operation of CentOS 5.8 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos58"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC19705(_TCSmoketest):
    """Operation of CentOS 5.9 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos59"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC19706(_TCSmoketest):
    """Operation of CentOS 6.3 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos63"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC19707(_TCSmoketest):
    """Operation of CentOS 6.4 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos64"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC19708(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.8 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel58"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC19709(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.9 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel59"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC19710(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.3 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel63"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC19711(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.4 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel64"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC19712(_TCSmoketest):
    """Operation of SLES11 SP2 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "sles112"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC19713(_TCSmoketest):
    """Operation of Debian 7.0 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "debian70"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC19714(_TCSmoketest):
    """Operation of RHEL 5.8 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel58"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19715(_TCSmoketest):
    """Operation of RHEL 5.9 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel59"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19716(_TCSmoketest):
    """Operation of RHEL 6.3 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel63"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19717(_TCSmoketest):
    """Operation of RHEL 6.4 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel64"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19718(_TCSmoketest):
    """Operation of CentOS 5.8 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos58"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19719(_TCSmoketest):
    """Operation of CentOS 5.9 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos59"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19720(_TCSmoketest):
    """Operation of CentOS 6.3 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos63"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19721(_TCSmoketest):
    """Operation of CentOS 6.4 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos64"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19722(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.8 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel58"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19723(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.9 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel59"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19724(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.3 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel63"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19725(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.4 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel64"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19726(_TCSmoketest):
    """Operation of SLES11 SP2 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "sles112"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19727(_TCSmoketest):
    """Operation of Debian 7.0 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "debian70"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC19728(_TCSmoketest):
    """Operation of RHEL 5.8 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel58"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC19729(_TCSmoketest):
    """Operation of RHEL 5.9 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel59"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC19730(_TCSmoketest):
    """Operation of RHEL 6.3 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel63"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC19731(_TCSmoketest):
    """Operation of RHEL 6.4 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel64"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC19732(_TCSmoketest):
    """Operation of CentOS 5.8 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos58"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC19733(_TCSmoketest):
    """Operation of CentOS 5.9 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos59"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC19734(_TCSmoketest):
    """Operation of CentOS 6.3 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos63"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC19735(_TCSmoketest):
    """Operation of CentOS 6.4 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos64"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC19736(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.8 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel58"
    MIGRATETEST = False
    MEMORY = 65536
    VCPUS = 2

# Autogenerated class - do not edit
class TC19737(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.9 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel59"
    MIGRATETEST = False
    MEMORY = 65536
    VCPUS = 2

# Autogenerated class - do not edit
class TC19738(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.3 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel63"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC19739(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.4 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel64"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC19740(_TCSmoketest):
    """Operation of SLES11 SP2 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "sles112"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC19741(_TCSmoketest):
    """Operation of Debian 7.0 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "debian70"
    MIGRATETEST = False
    MEMORY = 65536
    VCPUS = 2

# Autogenerated class - do not edit
class TC20524(_TCSmoketest):
    """Operation of Windows 8.1 using template defaults"""
    DISTRO = "win81-x86"

# Autogenerated class - do not edit
class TC20525(_TCSmoketest):
    """Operation of Windows 8.1 x64 using template defaults"""
    DISTRO = "win81-x64"

# Autogenerated class - do not edit
class TC20527(_TCSmoketest):
    """Operation of Windows 8.1 1GB 2 vCPUs on Intel VT"""
    DISTRO = "win81-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC20528(_TCSmoketest):
    """Operation of Windows 8.1 x64 1GB 2 vCPUs on Intel VT"""
    DISTRO = "win81-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC20530(_TCSmoketest):
    """Operation of Windows 8.1 1GB 2 vCPUs on AMD-V"""
    DISTRO = "win81-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC20531(_TCSmoketest):
    """Operation of Windows 8.1 x64 1GB 2 vCPUs on AMD-V"""
    DISTRO = "win81-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC20533(_TCSmoketest):
    """Operation of Windows 8.1 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "win81-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC20534(_TCSmoketest):
    """Operation of Windows 8.1 x64 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "win81-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC20536(_TCSmoketest):
    """Operation of Windows 8.1 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "win81-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC20537(_TCSmoketest):
    """Operation of Windows 8.1 x64 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "win81-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC20539(_TCSmoketest):
    """Operation of Windows 8.1 5GB 2 vCPUs"""
    DISTRO = "win81-x86"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC20540(_TCSmoketest):
    """Operation of Windows 8.1 x64 5GB 2 vCPUs"""
    DISTRO = "win81-x64"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC20542(_TCSmoketest):
    """Operation of Windows 8.1 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "win81-x86"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC20543(_TCSmoketest):
    """Operation of Windows 8.1 x64 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "win81-x64"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC20545(_TCSmoketest):
    """Operation of Windows 8.1 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "win81-x86"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2

# Autogenerated class - do not edit
class TC20546(_TCSmoketest):
    """Operation of Windows 8.1 x64 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "win81-x64"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2

# Autogenerated class - do not edit
class TC20558(_TCSmoketest):
    """Operation of Windows Server 2012 R2 x64 using template defaults"""
    DISTRO = "ws12r2-x64"

# Autogenerated class - do not edit
class TC20559(_TCSmoketest):
    """Operation of Windows Server 2012 R2 Core x64 using template defaults"""
    DISTRO = "ws12r2core-x64"

# Autogenerated class - do not edit
class TC20560(_TCSmoketest):
    """Operation of Windows Server 2012 R2 x64 1GB 2 vCPUs on Intel VT"""
    DISTRO = "ws12r2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC20561(_TCSmoketest):
    """Operation of Windows Server 2012 R2 Core x64 1GB 2 vCPUs on Intel VT"""
    DISTRO = "ws12r2core-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC20562(_TCSmoketest):
    """Operation of Windows Server 2012 R2 x64 1GB 2 vCPUs on AMD-V"""
    DISTRO = "ws12r2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC20563(_TCSmoketest):
    """Operation of Windows Server 2012 R2 Core x64 1GB 2 vCPUs on AMD-V"""
    DISTRO = "ws12r2core-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC20564(_TCSmoketest):
    """Operation of Windows Server 2012 R2 x64 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "ws12r2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC20565(_TCSmoketest):
    """Operation of Windows Server 2012 R2 Core x64 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "ws12r2core-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC20566(_TCSmoketest):
    """Operation of Windows Server 2012 R2 x64 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "ws12r2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC20567(_TCSmoketest):
    """Operation of Windows Server 2012 R2 Core x64 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "ws12r2core-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC20569(_TCSmoketest):
    """Operation of Windows Server 2012 R2 x64 5GB 2 vCPUs"""
    DISTRO = "ws12r2-x64"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC20570(_TCSmoketest):
    """Operation of Windows Server 2012 R2 Core x64 5GB 2 vCPUs"""
    DISTRO = "ws12r2core-x64"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC20571(_TCSmoketest):
    """Operation of Windows Server 2012 R2 x64 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "ws12r2-x64"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC20572(_TCSmoketest):
    """Operation of Windows Server 2012 R2 Core x64 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "ws12r2core-x64"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC20573(_TCSmoketest):
    """Operation of Windows Server 2012 R2 x64 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "ws12r2-x64"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2

# Autogenerated class - do not edit
class TC20574(_TCSmoketest):
    """Operation of Windows Server 2012 R2 Core x64 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "ws12r2core-x64"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2

# Autogenerated class - do not edit
class TC20591(_TCSmoketest):
    """Operation of RHEL 5.9 32 bit 5GB 2 vCPUs"""
    DISTRO = "rhel59"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC20592(_TCSmoketest):
    """Operation of RHEL 6.4 32 bit 5GB 2 vCPUs"""
    DISTRO = "rhel64"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC20593(_TCSmoketest):
    """Operation of CentOS 5.9 32 bit 5GB 2 vCPUs"""
    DISTRO = "centos59"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC20594(_TCSmoketest):
    """Operation of CentOS 6.4 32 bit 5GB 2 vCPUs"""
    DISTRO = "centos64"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC20595(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.9 32 bit 5GB 2 vCPUs"""
    DISTRO = "oel59"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC20596(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.4 32 bit 5GB 2 vCPUs"""
    DISTRO = "oel64"
    MEMORY = 5120
    VCPUS = 2


class TC20598(_TCSmoketest):
    """Operation of Debian 7.0 32 bit 5GB 2 vCPUs"""
    DISTRO = "debian70"
    MEMORY = 5120
    VCPUS = 2


# Autogenerated class - do not edit
class TC20599(_TCSmoketest):
    """Operation of RHEL 5.9 64 bit 5GB 2 vCPUs"""
    DISTRO = "rhel59"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC20600(_TCSmoketest):
    """Operation of RHEL 6.4 64 bit 5GB 2 vCPUs"""
    DISTRO = "rhel64"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC20601(_TCSmoketest):
    """Operation of CentOS 5.9 64 bit 5GB 2 vCPUs"""
    DISTRO = "centos59"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC20602(_TCSmoketest):
    """Operation of CentOS 6.4 64 bit 5GB 2 vCPUs"""
    DISTRO = "centos64"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC20603(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.9 64 bit 5GB 2 vCPUs"""
    DISTRO = "oel59"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC20604(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.4 64 bit 5GB 2 vCPUs"""
    DISTRO = "oel64"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC20605(_TCSmoketest):
    """Operation of SLES11 SP2 64 bit 5GB 2 vCPUs"""
    DISTRO = "sles112"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"
    
class TC20606(_TCSmoketest):
    """Operation of Debian 7.0 64 bit 5GB 2 vCPUs"""
    DISTRO = "debian70"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"


# Autogenerated class - do not edit
class TC21364(_TCSmoketest):
    """Operation of RHEL 5.10 32 bit using template defaults"""
    DISTRO = "rhel510"

# Autogenerated class - do not edit
class TC21365(_TCSmoketest):
    """Operation of RHEL 6.5 32 bit using template defaults"""
    DISTRO = "rhel65"

# Autogenerated class - do not edit
class TC21366(_TCSmoketest):
    """Operation of CentOS 5.10 32 bit using template defaults"""
    DISTRO = "centos510"

# Autogenerated class - do not edit
class TC21367(_TCSmoketest):
    """Operation of CentOS 6.5 32 bit using template defaults"""
    DISTRO = "centos65"

# Autogenerated class - do not edit
class TC21368(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.10 32 bit using template defaults"""
    DISTRO = "oel510"

# Autogenerated class - do not edit
class TC21369(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.5 32 bit using template defaults"""
    DISTRO = "oel65"

# Autogenerated class - do not edit
class TC21370(_TCSmoketest):
    """Operation of SLES11 SP3 using template defaults"""
    DISTRO = "sles113"

# Autogenerated class - do not edit
class TC21371(_TCSmoketest):
    """Operation of RHEL 5.10 64 bit using template defaults"""
    DISTRO = "rhel510"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21372(_TCSmoketest):
    """Operation of RHEL 6.5 64 bit using template defaults"""
    DISTRO = "rhel65"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21373(_TCSmoketest):
    """Operation of CentOS 5.10 64 bit using template defaults"""
    DISTRO = "centos510"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21374(_TCSmoketest):
    """Operation of CentOS 6.5 64 bit using template defaults"""
    DISTRO = "centos65"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21375(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.10 64 bit using template defaults"""
    DISTRO = "oel510"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21376(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.5 64 bit using template defaults"""
    DISTRO = "oel65"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21377(_TCSmoketest):
    """Operation of SLES11 SP3 64 bit using template defaults"""
    DISTRO = "sles113"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21378(_TCSmoketest):
    """Operation of RHEL 5.10 32 bit 1GB 2 vCPUs"""
    DISTRO = "rhel510"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC21379(_TCSmoketest):
    """Operation of RHEL 6.5 32 bit 1GB 2 vCPUs"""
    DISTRO = "rhel65"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC21380(_TCSmoketest):
    """Operation of CentOS 5.10 32 bit 1GB 2 vCPUs"""
    DISTRO = "centos510"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC21381(_TCSmoketest):
    """Operation of CentOS 6.5 32 bit 1GB 2 vCPUs"""
    DISTRO = "centos65"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC21382(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.10 32 bit 1GB 2 vCPUs"""
    DISTRO = "oel510"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC21383(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.5 32 bit 1GB 2 vCPUs"""
    DISTRO = "oel65"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC21384(_TCSmoketest):
    """Operation of SLES11 SP3 1GB 2 vCPUs"""
    DISTRO = "sles113"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC21385(_TCSmoketest):
    """Operation of RHEL 5.10 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel510"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21386(_TCSmoketest):
    """Operation of RHEL 6.5 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel65"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21387(_TCSmoketest):
    """Operation of CentOS 5.10 64 bit 1GB 2 vCPUs"""
    DISTRO = "centos510"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21388(_TCSmoketest):
    """Operation of CentOS 6.5 64 bit 1GB 2 vCPUs"""
    DISTRO = "centos65"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21389(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.10 64 bit 1GB 2 vCPUs"""
    DISTRO = "oel510"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21390(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.5 64 bit 1GB 2 vCPUs"""
    DISTRO = "oel65"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21391(_TCSmoketest):
    """Operation of SLES11 SP3 64 bit 1GB 2 vCPUs"""
    DISTRO = "sles113"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21392(_TCSmoketest):
    """Operation of RHEL 5.10 32 bit 5GB 2 vCPUs"""
    DISTRO = "rhel510"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC21393(_TCSmoketest):
    """Operation of RHEL 6.5 32 bit 5GB 2 vCPUs"""
    DISTRO = "rhel65"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC21394(_TCSmoketest):
    """Operation of CentOS 5.10 32 bit 5GB 2 vCPUs"""
    DISTRO = "centos510"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC21395(_TCSmoketest):
    """Operation of CentOS 6.5 32 bit 5GB 2 vCPUs"""
    DISTRO = "centos65"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC21396(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.10 32 bit 5GB 2 vCPUs"""
    DISTRO = "oel510"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC21397(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.5 32 bit 5GB 2 vCPUs"""
    DISTRO = "oel65"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC21398(_TCSmoketest):
    """Operation of SLES11 SP3 5GB 2 vCPUs"""
    DISTRO = "sles113"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC21399(_TCSmoketest):
    """Operation of RHEL 5.10 64 bit 5GB 2 vCPUs"""
    DISTRO = "rhel510"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21400(_TCSmoketest):
    """Operation of RHEL 6.5 64 bit 5GB 2 vCPUs"""
    DISTRO = "rhel65"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21401(_TCSmoketest):
    """Operation of CentOS 5.10 64 bit 5GB 2 vCPUs"""
    DISTRO = "centos510"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21402(_TCSmoketest):
    """Operation of CentOS 6.5 64 bit 5GB 2 vCPUs"""
    DISTRO = "centos65"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21403(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.10 64 bit 5GB 2 vCPUs"""
    DISTRO = "oel510"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21404(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.5 64 bit 5GB 2 vCPUs"""
    DISTRO = "oel65"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21405(_TCSmoketest):
    """Operation of SLES11 SP3 64 bit 5GB 2 vCPUs"""
    DISTRO = "sles113"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21406(_TCSmoketest):
    """Operation of RHEL 5.10 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel510"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC21407(_TCSmoketest):
    """Operation of RHEL 6.5 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel65"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC21408(_TCSmoketest):
    """Operation of CentOS 5.10 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos510"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC21409(_TCSmoketest):
    """Operation of CentOS 6.5 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos65"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC21410(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.10 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel510"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC21411(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.5 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel65"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC21412(_TCSmoketest):
    """Operation of SLES11 SP3 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "sles113"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC21413(_TCSmoketest):
    """Operation of RHEL 5.10 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel510"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21414(_TCSmoketest):
    """Operation of RHEL 6.5 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel65"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21415(_TCSmoketest):
    """Operation of CentOS 5.10 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos510"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21416(_TCSmoketest):
    """Operation of CentOS 6.5 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos65"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21417(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.10 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel510"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21418(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.5 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel65"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21419(_TCSmoketest):
    """Operation of SLES11 SP3 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "sles113"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21420(_TCSmoketest):
    """Operation of RHEL 5.10 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel510"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21421(_TCSmoketest):
    """Operation of RHEL 6.5 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel65"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21422(_TCSmoketest):
    """Operation of CentOS 5.10 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos510"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21423(_TCSmoketest):
    """Operation of CentOS 6.5 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos65"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21424(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.10 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel510"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21425(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.5 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel65"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21426(_TCSmoketest):
    """Operation of SLES11 SP3 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "sles113"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21427(_TCSmoketest):
    """Operation of RHEL 5.10 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel510"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC21428(_TCSmoketest):
    """Operation of RHEL 6.5 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel65"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC21429(_TCSmoketest):
    """Operation of CentOS 5.10 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos510"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC21430(_TCSmoketest):
    """Operation of CentOS 6.5 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos65"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC21431(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.10 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel510"
    MIGRATETEST = False
    MEMORY = 65536
    VCPUS = 2

# Autogenerated class - do not edit
class TC21432(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.5 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel65"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC21433(_TCSmoketest):
    """Operation of SLES11 SP3 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "sles113"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2
    
# Autogenerated class - do not edit
class TC21469(_TCSmoketest):
    """Operation of CentOS 6.3 32 bit 5GB 2 vCPUs"""
    DISTRO = "centos63"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC21470(_TCSmoketest):
    """Operation of CentOS 6.3 32 bit 5GB 2 vCPUs"""
    DISTRO = "centos63"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"


# Autogenerated class - do not edit
class TC21471(_TCSmoketest):
    """Operation of Windows Server 2008 R2 Enterprise x64 1GB 2 vCPUs"""
    DISTRO = "ws08r2-x64"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC21472(_TCSmoketest):
    """Operation of Windows 7 1GB 2 vCPUs"""
    DISTRO = "win7-x86"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC21493(_TCSmoketest):
    """Operation of Ubuntu 14.04 32 bit using template defaults"""
    DISTRO = "ubuntu1404"

# Autogenerated class - do not edit
class TC21494(_TCSmoketest):
    """Operation of Ubuntu 14.04 64 bit using template defaults"""
    DISTRO = "ubuntu1404"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21495(_TCSmoketest):
    """Operation of Ubuntu 14.04 32 bit 1GB 2 vCPUs"""
    DISTRO = "ubuntu1404"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC21496(_TCSmoketest):
    """Operation of Ubuntu 14.04 64 bit 1GB 2 vCPUs"""
    DISTRO = "ubuntu1404"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21497(_TCSmoketest):
    """Operation of Ubuntu 14.04 32 bit 5GB 2 vCPUs"""
    DISTRO = "ubuntu1404"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC21498(_TCSmoketest):
    """Operation of Ubuntu 14.04 64 bit 5GB 2 vCPUs"""
    DISTRO = "ubuntu1404"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21499(_TCSmoketest):
    """Operation of Ubuntu 14.04 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "ubuntu1404"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC21500(_TCSmoketest):
    """Operation of Ubuntu 14.04 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "ubuntu1404"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21501(_TCSmoketest):
    """Operation of Ubuntu 14.04 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "ubuntu1404"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21502(_TCSmoketest):
    """Operation of Ubuntu 14.04 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "ubuntu1404"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC21650(_TCSmoketest):
    """Operation of RHEL 7.0 64 bit using template defaults"""
    DISTRO = "rhel7"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21651(_TCSmoketest):
    """Operation of CentOS 7.0 64 bit using template defaults"""
    DISTRO = "centos7"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23928(_TCSmoketest):
    """Operation of RHEL 7.1 64 bit using template defaults"""
    DISTRO = "rhel71"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21652(_TCSmoketest):
    """Operation of OEL 7.0 64 bit using template defaults"""
    DISTRO = "oel7"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21653(_TCSmoketest):
    """Operation of SLES12 64 bit using template defaults"""
    DISTRO = "sles12"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21654(_TCSmoketest):
    """Operation of RHEL 7.0 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel7"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23929(_TCSmoketest):
    """Operation of RHEL 7.1 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel71"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21655(_TCSmoketest):
    """Operation of CentOS 7.0 64 bit 1GB 2 vCPUs"""
    DISTRO = "centos7"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21656(_TCSmoketest):
    """Operation of OEL 7.0 64 bit 1GB 2 vCPUs"""
    DISTRO = "oel7"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21657(_TCSmoketest):
    """Operation of SLES12 64 bit 1GB 2 vCPUs"""
    DISTRO = "sles12"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21658(_TCSmoketest):
    """Operation of RHEL 7.0 64 bit 5GB 2 vCPUs"""
    DISTRO = "rhel7"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"


# Autogenerated class - do not edit
class TC23930(_TCSmoketest):
    """Operation of RHEL 7.1 64 bit 5GB 2 vCPUs"""
    DISTRO = "rhel71"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21659(_TCSmoketest):
    """Operation of CentOS 7.0 64 bit 5GB 2 vCPUs"""
    DISTRO = "centos7"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21660(_TCSmoketest):
    """Operation of OEL 7.0 64 bit 5GB 2 vCPUs"""
    DISTRO = "oel7"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21661(_TCSmoketest):
    """Operation of SLES12 64 bit 5GB 2 vCPUs"""
    DISTRO = "sles12"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21662(_TCSmoketest):
    """Operation of RHEL 7.0 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel7"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23971(_TCSmoketest):
    """Operation of RHEL 7.1 64 bit 1GB maximum vCPUs (XenServer guest limit 32)"""
    DISTRO = "rhel71"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21663(_TCSmoketest):
    """Operation of CentOS 7.0 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos7"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21664(_TCSmoketest):
    """Operation of OEL 7.0 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel7"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21665(_TCSmoketest):
    """Operation of SLES12 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "sles12"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21666(_TCSmoketest):
    """Operation of RHEL 7.0 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel7"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23994(_TCSmoketest):
    """Operation of RHEL 7.1 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel71"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21667(_TCSmoketest):
    """Operation of CentOS 7.0 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos7"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21668(_TCSmoketest):
    """Operation of OEL 7.0 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel7"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC21669(_TCSmoketest):
    """Operation of SLES12 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "sles12"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23501(_TCSmoketest):
    """Operation of RHEL 5.11 32 bit using template defaults"""
    DISTRO = "rhel511"

# Autogenerated class - do not edit
class TC23502(_TCSmoketest):
    """Operation of RHEL 6.6 32 bit using template defaults"""
    DISTRO = "rhel66"

# Autogenerated class - do not edit
class TC23503(_TCSmoketest):
    """Operation of CentOS 5.11 32 bit using template defaults"""
    DISTRO = "centos511"

# Autogenerated class - do not edit
class TC23504(_TCSmoketest):
    """Operation of CentOS 6.6 32 bit using template defaults"""
    DISTRO = "centos66"

# Autogenerated class - do not edit
class TC23505(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.11 32 bit using template defaults"""
    DISTRO = "oel511"

# Autogenerated class - do not edit
class TC23506(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.6 32 bit using template defaults"""
    DISTRO = "oel66"

# Autogenerated class - do not edit
class TC23507(_TCSmoketest):
    """Operation of RHEL 5.11 64 bit using template defaults"""
    DISTRO = "rhel511"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23508(_TCSmoketest):
    """Operation of RHEL 6.6 64 bit using template defaults"""
    DISTRO = "rhel66"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23509(_TCSmoketest):
    """Operation of CentOS 5.11 64 bit using template defaults"""
    DISTRO = "centos511"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23510(_TCSmoketest):
    """Operation of CentOS 6.6 64 bit using template defaults"""
    DISTRO = "centos66"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23511(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.11 64 bit using template defaults"""
    DISTRO = "oel511"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23512(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.6 64 bit using template defaults"""
    DISTRO = "oel66"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23513(_TCSmoketest):
    """Operation of RHEL 5.11 32 bit 1GB 2 vCPUs"""
    DISTRO = "rhel511"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC23514(_TCSmoketest):
    """Operation of RHEL 6.6 32 bit 1GB 2 vCPUs"""
    DISTRO = "rhel66"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC23515(_TCSmoketest):
    """Operation of CentOS 5.11 32 bit 1GB 2 vCPUs"""
    DISTRO = "centos511"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC23516(_TCSmoketest):
    """Operation of CentOS 6.6 32 bit 1GB 2 vCPUs"""
    DISTRO = "centos66"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC23517(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.11 32 bit 1GB 2 vCPUs"""
    DISTRO = "oel511"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC23518(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.6 32 bit 1GB 2 vCPUs"""
    DISTRO = "oel66"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC23519(_TCSmoketest):
    """Operation of RHEL 5.11 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel511"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23520(_TCSmoketest):
    """Operation of RHEL 6.6 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel66"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23521(_TCSmoketest):
    """Operation of CentOS 5.11 64 bit 1GB 2 vCPUs"""
    DISTRO = "centos511"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23522(_TCSmoketest):
    """Operation of CentOS 6.6 64 bit 1GB 2 vCPUs"""
    DISTRO = "centos66"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23523(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.11 64 bit 1GB 2 vCPUs"""
    DISTRO = "oel511"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23524(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.6 64 bit 1GB 2 vCPUs"""
    DISTRO = "oel66"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23525(_TCSmoketest):
    """Operation of RHEL 5.11 32 bit 5GB 2 vCPUs"""
    DISTRO = "rhel511"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC23526(_TCSmoketest):
    """Operation of RHEL 6.6 32 bit 5GB 2 vCPUs"""
    DISTRO = "rhel66"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC23527(_TCSmoketest):
    """Operation of CentOS 5.11 32 bit 5GB 2 vCPUs"""
    DISTRO = "centos511"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC23528(_TCSmoketest):
    """Operation of CentOS 6.6 32 bit 5GB 2 vCPUs"""
    DISTRO = "centos66"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC23529(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.11 32 bit 5GB 2 vCPUs"""
    DISTRO = "oel511"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC23530(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.6 32 bit 5GB 2 vCPUs"""
    DISTRO = "oel66"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC23531(_TCSmoketest):
    """Operation of RHEL 5.11 64 bit 5GB 2 vCPUs"""
    DISTRO = "rhel511"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23532(_TCSmoketest):
    """Operation of RHEL 6.6 64 bit 5GB 2 vCPUs"""
    DISTRO = "rhel66"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23533(_TCSmoketest):
    """Operation of CentOS 5.11 64 bit 5GB 2 vCPUs"""
    DISTRO = "centos511"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23534(_TCSmoketest):
    """Operation of CentOS 6.6 64 bit 5GB 2 vCPUs"""
    DISTRO = "centos66"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23535(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.11 64 bit 5GB 2 vCPUs"""
    DISTRO = "oel511"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23536(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.6 64 bit 5GB 2 vCPUs"""
    DISTRO = "oel66"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23537(_TCSmoketest):
    """Operation of RHEL 5.11 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel511"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC23538(_TCSmoketest):
    """Operation of RHEL 6.6 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel66"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC23539(_TCSmoketest):
    """Operation of CentOS 5.11 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos511"
    MEMORY = 1024
    VCPUS = 16

# Autogenerated class - do not edit
class TC23540(_TCSmoketest):
    """Operation of CentOS 6.6 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos66"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC23541(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.11 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel511"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC23542(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.6 32 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel66"
    MEMORY = 1024
    VCPUS = 32

# Autogenerated class - do not edit
class TC23543(_TCSmoketest):
    """Operation of RHEL 5.11 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel511"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23544(_TCSmoketest):
    """Operation of RHEL 6.6 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "rhel66"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23545(_TCSmoketest):
    """Operation of CentOS 5.11 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos511"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23546(_TCSmoketest):
    """Operation of CentOS 6.6 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "centos66"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23547(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.11 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel511"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23548(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.6 64 bit 1GB maximum vCPUs (XenServer guest limit 16)"""
    DISTRO = "oel66"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23549(_TCSmoketest):
    """Operation of RHEL 5.11 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel511"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23550(_TCSmoketest):
    """Operation of RHEL 6.6 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel66"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23551(_TCSmoketest):
    """Operation of CentOS 5.11 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos511"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23552(_TCSmoketest):
    """Operation of CentOS 6.6 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos66"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23553(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.11 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel511"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23554(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.6 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel66"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC23555(_TCSmoketest):
    """Operation of RHEL 5.11 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel511"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC23556(_TCSmoketest):
    """Operation of RHEL 6.6 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "rhel66"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC23557(_TCSmoketest):
    """Operation of CentOS 5.11 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos511"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC23558(_TCSmoketest):
    """Operation of CentOS 6.6 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "centos66"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC23559(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 5.11 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel511"
    MIGRATETEST = False
    MEMORY = 65536
    VCPUS = 2

# Autogenerated class - do not edit
class TC23560(_TCSmoketest):
    """Operation of Oracle Enterprise Linux 6.6 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "oel66"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC6790(_TCSmoketest):
    """Operation of Debian Sarge using template defaults"""
    DISTRO = "sarge"

# Autogenerated class - do not edit
class TC6791(_TCSmoketest):
    """Operation of Debian Etch using template defaults"""
    DISTRO = "etch"

# Autogenerated class - do not edit
class TC6792(_TCSmoketest):
    """Operation of RHEL 4.1 using template defaults"""
    DISTRO = "rhel41"

# Autogenerated class - do not edit
class TC6793(_TCSmoketest):
    """Operation of RHEL 4.4 using template defaults"""
    DISTRO = "rhel44"

# Autogenerated class - do not edit
class TC6794(_TCSmoketest):
    """Operation of RHEL 4.5 using template defaults"""
    DISTRO = "rhel45"

# Autogenerated class - do not edit
class TC6795(_TCSmoketest):
    """Operation of RHEL 4.6 using template defaults"""
    DISTRO = "rhel46"

# Autogenerated class - do not edit
class TC6796(_TCSmoketest):
    """Operation of RHEL 5.0 32 bit using template defaults"""
    DISTRO = "rhel5"

# Autogenerated class - do not edit
class TC6797(_TCSmoketest):
    """Operation of RHEL 5.0 64 bit using template defaults"""
    DISTRO = "rhel5"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC6798(_TCSmoketest):
    """Operation of RHEL 5.1 32 bit using template defaults"""
    DISTRO = "rhel51"

# Autogenerated class - do not edit
class TC6799(_TCSmoketest):
    """Operation of RHEL 5.1 64 bit using template defaults"""
    DISTRO = "rhel51"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC6800(_TCSmoketest):
    """Operation of CentOS 4.5 using template defaults"""
    DISTRO = "centos45"

# Autogenerated class - do not edit
class TC6801(_TCSmoketest):
    """Operation of CentOS 4.6 using template defaults"""
    DISTRO = "centos46"

# Autogenerated class - do not edit
class TC6802(_TCSmoketest):
    """Operation of CentOS 5.0 32 bit using template defaults"""
    DISTRO = "centos5"

# Autogenerated class - do not edit
class TC6803(_TCSmoketest):
    """Operation of CentOS 5.0 64 bit using template defaults"""
    DISTRO = "centos5"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC6804(_TCSmoketest):
    """Operation of CentOS 5.1 32 bit using template defaults"""
    DISTRO = "centos51"

# Autogenerated class - do not edit
class TC6805(_TCSmoketest):
    """Operation of CentOS 5.1 64 bit using template defaults"""
    DISTRO = "centos51"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC6806(_TCSmoketest):
    """Operation of SLES10 SP1 using template defaults"""
    DISTRO = "sles101"

# Autogenerated class - do not edit
class TC6807(_TCSmoketest):
    """Operation of Windows Server 2003 SP0 Enterprise using template defaults"""
    DISTRO = "w2k3ee"

# Autogenerated class - do not edit
class TC6808(_TCSmoketest):
    """Operation of Windows Server 2003 SP1 Enterprise using template defaults"""
    DISTRO = "w2k3eesp1"

# Autogenerated class - do not edit
class TC6809(_TCSmoketest):
    """Operation of Windows Server 2003 SP1 R2 Enterprise using template defaults"""
    DISTRO = "w2k3eer2"

# Autogenerated class - do not edit
class TC6810(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise using template defaults"""
    DISTRO = "w2k3eesp2"

# Autogenerated class - do not edit
class TC6811(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise x64 using template defaults"""
    DISTRO = "w2k3eesp2-x64"

# Autogenerated class - do not edit
class TC6812(_TCSmoketest):
    """Operation of Windows Server 2003 SP0 Standard using template defaults"""
    DISTRO = "w2k3se"

# Autogenerated class - do not edit
class TC6813(_TCSmoketest):
    """Operation of Windows Server 2003 SP1 Standard using template defaults"""
    DISTRO = "w2k3sesp1"

# Autogenerated class - do not edit
class TC6814(_TCSmoketest):
    """Operation of Windows Server 2003 SP1 R2 Standard using template defaults"""
    DISTRO = "w2k3ser2"

# Autogenerated class - do not edit
class TC6815(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Standard using template defaults"""
    DISTRO = "w2k3sesp2"

# Autogenerated class - do not edit
class TC6816(_TCSmoketest):
    """Operation of Windows Vista SP0 Enterprise using template defaults"""
    DISTRO = "vistaee"

# Autogenerated class - do not edit
class TC6817(_TCSmoketest):
    """Operation of Windows Vista SP0 Enterprise x64 using template defaults"""
    DISTRO = "vistaee-x64"

# Autogenerated class - do not edit
class TC6818(_TCSmoketest):
    """Operation of Windows Vista SP1 Enterprise using template defaults"""
    DISTRO = "vistaeesp1"

# Autogenerated class - do not edit
class TC6819(_TCSmoketest):
    """Operation of Windows Vista SP1 Enterprise x64 using template defaults"""
    DISTRO = "vistaeesp1-x64"

# Autogenerated class - do not edit
class TC6820(_TCSmoketest):
    """Operation of Windows XP SP2 using template defaults"""
    DISTRO = "winxpsp2"

# Autogenerated class - do not edit
class TC6821(_TCSmoketest):
    """Operation of Windows 2000 Server SP4 using template defaults"""
    DISTRO = "w2kassp4"
    HIBERNATE = False

# Autogenerated class - do not edit
class TC6891(_TCSmoketest):
    """Operation of Windows Server 2003 SP0 Enterprise 1GB 2 vCPUs on Intel VT"""
    DISTRO = "w2k3ee"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC6892(_TCSmoketest):
    """Operation of Windows Server 2003 SP1 Enterprise 1GB 2 vCPUs on Intel VT"""
    DISTRO = "w2k3eesp1"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC6893(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise 1GB 2 vCPUs on Intel VT"""
    DISTRO = "w2k3eesp2"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC6894(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise x64 1GB 2 vCPUs on Intel VT"""
    DISTRO = "w2k3eesp2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC6895(_TCSmoketest):
    """Operation of Windows Vista SP1 Enterprise 1GB 2 vCPUs on Intel VT"""
    DISTRO = "vistaeesp1"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC6896(_TCSmoketest):
    """Operation of Windows Vista SP1 Enterprise x64 1GB 2 vCPUs on Intel VT"""
    DISTRO = "vistaeesp1-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC6897(_TCSmoketest):
    """Operation of Windows XP SP2 1GB 2 vCPUs on Intel VT"""
    DISTRO = "winxpsp2"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC6898(_TCSmoketest):
    """Operation of Windows 2000 Server SP4 1GB 2 vCPUs on Intel VT"""
    DISTRO = "w2kassp4"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"
    HIBERNATE = False

# Autogenerated class - do not edit
class TC6899(_TCSmoketest):
    """Operation of Windows Server 2003 SP0 Enterprise 1GB 2 vCPUs on AMD-V"""
    DISTRO = "w2k3ee"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC6900(_TCSmoketest):
    """Operation of Windows Server 2003 SP1 Enterprise 1GB 2 vCPUs on AMD-V"""
    DISTRO = "w2k3eesp1"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC6901(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise 1GB 2 vCPUs on AMD-V"""
    DISTRO = "w2k3eesp2"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC6902(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise x64 1GB 2 vCPUs on AMD-V"""
    DISTRO = "w2k3eesp2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC6903(_TCSmoketest):
    """Operation of Windows Vista SP1 Enterprise 1GB 2 vCPUs on AMD-V"""
    DISTRO = "vistaeesp1"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC6904(_TCSmoketest):
    """Operation of Windows Vista SP1 Enterprise x64 1GB 2 vCPUs on AMD-V"""
    DISTRO = "vistaeesp1-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC6905(_TCSmoketest):
    """Operation of Windows XP SP2 1GB 2 vCPUs on AMD-V"""
    DISTRO = "winxpsp2"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC6906(_TCSmoketest):
    """Operation of Windows 2000 Server SP4 1GB 2 vCPUs on AMD-V"""
    DISTRO = "w2kassp4"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"
    HIBERNATE = False

# Autogenerated class - do not edit
class TC7396(_TCSmoketest):
    """Operation of Windows Server 2003 SP0 Enterprise 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "w2k3ee"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC7397(_TCSmoketest):
    """Operation of Windows Server 2003 SP1 Enterprise 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "w2k3eesp1"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC7398(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "w2k3eesp2"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC7399(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise x64 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "w2k3eesp2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC7400(_TCSmoketest):
    """Operation of Windows 2000 Server SP4 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "w2kassp4"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"
    HIBERNATE = False

# Autogenerated class - do not edit
class TC7401(_TCSmoketest):
    """Operation of Windows XP SP2 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "winxpsp2"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC7402(_TCSmoketest):
    """Operation of Windows Vista SP1 Enterprise 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "vistaeesp1"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC7403(_TCSmoketest):
    """Operation of Windows Vista SP1 Enterprise x64 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "vistaeesp1-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC7404(_TCSmoketest):
    """Operation of RHEL 4.1 1GB 2 vCPUs"""
    DISTRO = "rhel41"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7405(_TCSmoketest):
    """Operation of RHEL 4.5 1GB 2 vCPUs"""
    DISTRO = "rhel45"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7406(_TCSmoketest):
    """Operation of RHEL 5.0 32 bit 1GB 2 vCPUs"""
    DISTRO = "rhel5"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7407(_TCSmoketest):
    """Operation of RHEL 5.0 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel5"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7408(_TCSmoketest):
    """Operation of Debian Sarge 1GB 2 vCPUs"""
    DISTRO = "sarge"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7409(_TCSmoketest):
    """Operation of Windows Server 2003 SP1 R2 Enterprise 1GB 2 vCPUs"""
    DISTRO = "w2k3eer2"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7410(_TCSmoketest):
    """Operation of Windows Server 2003 SP0 Standard 1GB 2 vCPUs"""
    DISTRO = "w2k3se"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7411(_TCSmoketest):
    """Operation of Windows Server 2003 SP1 Standard 1GB 2 vCPUs"""
    DISTRO = "w2k3sesp1"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7412(_TCSmoketest):
    """Operation of Windows Server 2003 SP1 R2 Standard 1GB 2 vCPUs"""
    DISTRO = "w2k3ser2"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7413(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Standard 1GB 2 vCPUs"""
    DISTRO = "w2k3sesp2"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7414(_TCSmoketest):
    """Operation of Windows Vista SP0 Enterprise 1GB 2 vCPUs"""
    DISTRO = "vistaee"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7415(_TCSmoketest):
    """Operation of Windows Vista SP0 Enterprise x64 1GB 2 vCPUs"""
    DISTRO = "vistaee-x64"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7416(_TCSmoketest):
    """Operation of CentOS 4.5 1GB 2 vCPUs"""
    DISTRO = "centos45"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7417(_TCSmoketest):
    """Operation of CentOS 4.6 1GB 2 vCPUs"""
    DISTRO = "centos46"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7418(_TCSmoketest):
    """Operation of CentOS 5.0 32 bit 1GB 2 vCPUs"""
    DISTRO = "centos5"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7419(_TCSmoketest):
    """Operation of CentOS 5.0 64 bit 1GB 2 vCPUs"""
    DISTRO = "centos5"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7420(_TCSmoketest):
    """Operation of CentOS 5.1 32 bit 1GB 2 vCPUs"""
    DISTRO = "centos51"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7421(_TCSmoketest):
    """Operation of CentOS 5.1 64 bit 1GB 2 vCPUs"""
    DISTRO = "centos51"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7422(_TCSmoketest):
    """Operation of RHEL 4.4 1GB 2 vCPUs"""
    DISTRO = "rhel44"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7423(_TCSmoketest):
    """Operation of RHEL 4.6 1GB 2 vCPUs"""
    DISTRO = "rhel46"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7424(_TCSmoketest):
    """Operation of RHEL 5.1 32 bit 1GB 2 vCPUs"""
    DISTRO = "rhel51"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7425(_TCSmoketest):
    """Operation of RHEL 5.1 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel51"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7426(_TCSmoketest):
    """Operation of SLES10 SP1 1GB 2 vCPUs"""
    DISTRO = "sles101"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7427(_TCSmoketest):
    """Operation of Debian Etch 1GB 2 vCPUs"""
    DISTRO = "etch"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7428(_TCSmoketest):
    """Operation of Windows Server 2003 SP0 Enterprise 5GB 2 vCPUs"""
    DISTRO = "w2k3ee"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC7429(_TCSmoketest):
    """Operation of Windows Server 2003 SP1 Enterprise 5GB 2 vCPUs"""
    DISTRO = "w2k3eesp1"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC7430(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise 5GB 2 vCPUs"""
    DISTRO = "w2k3eesp2"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC7431(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise x64 5GB 2 vCPUs"""
    DISTRO = "w2k3eesp2-x64"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC7432(_TCSmoketest):
    """Operation of Windows 2000 Server SP4 5GB 2 vCPUs"""
    DISTRO = "w2kassp4"
    MEMORY = 5120
    VCPUS = 2
    HIBERNATE = False

# Autogenerated class - do not edit
class TC7433(_TCSmoketest):
    """Operation of Windows XP SP2 5GB 2 vCPUs"""
    DISTRO = "winxpsp2"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC7434(_TCSmoketest):
    """Operation of Windows Vista SP1 Enterprise 5GB 2 vCPUs"""
    DISTRO = "vistaeesp1"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC7435(_TCSmoketest):
    """Operation of Windows Vista SP1 Enterprise x64 5GB 2 vCPUs"""
    DISTRO = "vistaeesp1-x64"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC7436(_TCSmoketest):
    """Operation of RHEL 4.4 5GB 2 vCPUs"""
    DISTRO = "rhel44"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC7437(_TCSmoketest):
    """Operation of RHEL 4.6 5GB 2 vCPUs"""
    DISTRO = "rhel46"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC7438(_TCSmoketest):
    """Operation of RHEL 5.1 32 bit 5GB 2 vCPUs"""
    DISTRO = "rhel51"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC7439(_TCSmoketest):
    """Operation of RHEL 5.1 64 bit 5GB 2 vCPUs"""
    DISTRO = "rhel51"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7440(_TCSmoketest):
    """Operation of SLES10 SP1 5GB 2 vCPUs"""
    DISTRO = "sles101"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC7441(_TCSmoketest):
    """Operation of Debian Etch 5GB 2 vCPUs"""
    DISTRO = "etch"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC7442(_TCSmoketest):
    """Operation of Windows Server 2003 SP0 Enterprise 1GB maximum vCPUs"""
    DISTRO = "w2k3ee"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC7443(_TCSmoketest):
    """Operation of Windows Server 2003 SP1 Enterprise 1GB maximum vCPUs"""
    DISTRO = "w2k3eesp1"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC7444(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise 1GB maximum vCPUs"""
    DISTRO = "w2k3eesp2"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC7445(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise x64 1GB maximum vCPUs"""
    DISTRO = "w2k3eesp2-x64"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC7446(_TCSmoketest):
    """Operation of Windows 2000 Server SP4 1GB maximum vCPUs"""
    DISTRO = "w2kassp4"
    MEMORY = 1024
    VCPUS = 8
    HIBERNATE = False

# Autogenerated class - do not edit
class TC7447(_TCSmoketest):
    """Operation of Windows XP SP2 1GB maximum vCPUs"""
    DISTRO = "winxpsp2"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7448(_TCSmoketest):
    """Operation of Windows Vista SP1 Enterprise 1GB maximum vCPUs"""
    DISTRO = "vistaeesp1"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7449(_TCSmoketest):
    """Operation of Windows Vista SP1 Enterprise x64 1GB maximum vCPUs"""
    DISTRO = "vistaeesp1-x64"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7450(_TCSmoketest):
    """Operation of RHEL 4.4 1GB maximum vCPUs"""
    DISTRO = "rhel44"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC7451(_TCSmoketest):
    """Operation of RHEL 4.6 1GB maximum vCPUs"""
    DISTRO = "rhel46"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC7452(_TCSmoketest):
    """Operation of RHEL 5.1 32 bit 1GB maximum vCPUs"""
    DISTRO = "rhel51"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC7453(_TCSmoketest):
    """Operation of RHEL 5.1 64 bit 1GB maximum vCPUs"""
    DISTRO = "rhel51"
    MEMORY = 1024
    VCPUS = 8
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7454(_TCSmoketest):
    """Operation of SLES10 SP1 1GB maximum vCPUs"""
    DISTRO = "sles101"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC7455(_TCSmoketest):
    """Operation of Debian Etch 1GB maximum vCPUs"""
    DISTRO = "etch"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC7456(_TCSmoketest):
    """Operation of Windows Server 2003 SP0 Enterprise maximum memory 2 vCPUs"""
    DISTRO = "w2k3ee"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC7457(_TCSmoketest):
    """Operation of Windows Server 2003 SP1 Enterprise maximum memory 2 vCPUs"""
    DISTRO = "w2k3eesp1"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC7458(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise maximum memory 2 vCPUs"""
    DISTRO = "w2k3eesp2"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC7459(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise x64 maximum memory 2 vCPUs"""
    DISTRO = "w2k3eesp2-x64"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC7460(_TCSmoketest):
    """Operation of Windows 2000 Server SP4 maximum memory 2 vCPUs"""
    DISTRO = "w2kassp4"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2
    HIBERNATE = False

# Autogenerated class - do not edit
class TC7461(_TCSmoketest):
    """Operation of Windows XP SP2 maximum memory 2 vCPUs"""
    DISTRO = "winxpsp2"
    MIGRATETEST = False
    MEMORY = 4096
    VCPUS = 2

# Autogenerated class - do not edit
class TC7462(_TCSmoketest):
    """Operation of Windows Vista SP1 Enterprise maximum memory 2 vCPUs"""
    DISTRO = "vistaeesp1"
    MIGRATETEST = False
    MEMORY = 4096
    VCPUS = 2

# Autogenerated class - do not edit
class TC7463(_TCSmoketest):
    """Operation of Windows Vista SP1 Enterprise x64 maximum memory 2 vCPUs"""
    DISTRO = "vistaeesp1-x64"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC7464(_TCSmoketest):
    """Operation of RHEL 4.4 maximum memory 2 vCPUs"""
    DISTRO = "rhel44"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC7465(_TCSmoketest):
    """Operation of RHEL 4.6 maximum memory 2 vCPUs"""
    DISTRO = "rhel46"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC7466(_TCSmoketest):
    """Operation of RHEL 5.1 32 bit maximum memory 2 vCPUs"""
    DISTRO = "rhel51"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC7467(_TCSmoketest):
    """Operation of RHEL 5.1 64 bit maximum memory 2 vCPUs"""
    DISTRO = "rhel51"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7468(_TCSmoketest):
    """Operation of SLES10 SP1 maximum memory 2 vCPUs"""
    DISTRO = "sles101"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC7469(_TCSmoketest):
    """Operation of Debian Etch maximum memory 2 vCPUs"""
    DISTRO = "etch"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC7470(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise 1GB 3 vCPUs"""
    DISTRO = "w2k3eesp2"
    MEMORY = 1024
    VCPUS = 3

# Autogenerated class - do not edit
class TC7471(_TCSmoketest):
    """Operation of Debian Etch 1GB 3 vCPUs"""
    DISTRO = "etch"
    MEMORY = 1024
    VCPUS = 3

# Autogenerated class - do not edit
class TC7621(_TCSmoketest):
    """Operation of Windows XP SP3 using template defaults"""
    DISTRO = "winxpsp3"

# Autogenerated class - do not edit
class TC7622(_TCSmoketest):
    """Operation of Windows Server 2008 Enterprise using template defaults"""
    DISTRO = "ws08-x86"

# Autogenerated class - do not edit
class TC7623(_TCSmoketest):
    """Operation of Windows Server 2008 Enterprise x64 using template defaults"""
    DISTRO = "ws08-x64"

# Autogenerated class - do not edit
class TC7624(_TCSmoketest):
    """Operation of RHEL 4.7 using template defaults"""
    DISTRO = "rhel47"

# Autogenerated class - do not edit
class TC7625(_TCSmoketest):
    """Operation of RHEL 5.2 32 bit using template defaults"""
    DISTRO = "rhel52"

# Autogenerated class - do not edit
class TC7626(_TCSmoketest):
    """Operation of RHEL 5.2 64 bit using template defaults"""
    DISTRO = "rhel52"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7627(_TCSmoketest):
    """Operation of SLES9 SP4 using template defaults"""
    DISTRO = "sles94"

# Autogenerated class - do not edit
class TC7628(_TCSmoketest):
    """Operation of SLES10 SP1 64 bit using template defaults"""
    DISTRO = "sles101"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7629(_TCSmoketest):
    """Operation of SLES10 SP2 using template defaults"""
    DISTRO = "sles102"

# Autogenerated class - do not edit
class TC7630(_TCSmoketest):
    """Operation of SLES10 SP2 64 bit using template defaults"""
    DISTRO = "sles102"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7631(_TCSmoketest):
    """Operation of CentOS 4.7 using template defaults"""
    DISTRO = "centos47"

# Autogenerated class - do not edit
class TC7632(_TCSmoketest):
    """Operation of CentOS 5.2 32 bit using template defaults"""
    DISTRO = "centos52"

# Autogenerated class - do not edit
class TC7633(_TCSmoketest):
    """Operation of CentOS 5.2 64 bit using template defaults"""
    DISTRO = "centos52"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7634(_TCSmoketest):
    """Operation of Windows XP SP3 1GB 2 vCPUs on Intel VT"""
    DISTRO = "winxpsp3"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC7635(_TCSmoketest):
    """Operation of Windows Server 2008 Enterprise 1GB 2 vCPUs on Intel VT"""
    DISTRO = "ws08-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC7636(_TCSmoketest):
    """Operation of Windows Server 2008 Enterprise x64 1GB 2 vCPUs on Intel VT"""
    DISTRO = "ws08-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC7637(_TCSmoketest):
    """Operation of Windows XP SP3 1GB 2 vCPUs on AMD-V"""
    DISTRO = "winxpsp3"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC7638(_TCSmoketest):
    """Operation of Windows Server 2008 Enterprise 1GB 2 vCPUs on AMD-V"""
    DISTRO = "ws08-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC7639(_TCSmoketest):
    """Operation of Windows Server 2008 Enterprise x64 1GB 2 vCPUs on AMD-V"""
    DISTRO = "ws08-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC7640(_TCSmoketest):
    """Operation of Windows XP SP3 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "winxpsp3"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC7641(_TCSmoketest):
    """Operation of Windows Server 2008 Enterprise 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "ws08-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC7642(_TCSmoketest):
    """Operation of Windows Server 2008 Enterprise x64 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "ws08-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC7643(_TCSmoketest):
    """Operation of CentOS 4.7 1GB 2 vCPUs"""
    DISTRO = "centos47"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7644(_TCSmoketest):
    """Operation of CentOS 5.2 32 bit 1GB 2 vCPUs"""
    DISTRO = "centos52"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7645(_TCSmoketest):
    """Operation of CentOS 5.2 64 bit 1GB 2 vCPUs"""
    DISTRO = "centos52"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7646(_TCSmoketest):
    """Operation of RHEL 4.7 1GB 2 vCPUs"""
    DISTRO = "rhel47"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7647(_TCSmoketest):
    """Operation of RHEL 5.2 32 bit 1GB 2 vCPUs"""
    DISTRO = "rhel52"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7648(_TCSmoketest):
    """Operation of RHEL 5.2 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel52"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7649(_TCSmoketest):
    """Operation of SLES9 SP4 1GB 2 vCPUs"""
    DISTRO = "sles94"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7650(_TCSmoketest):
    """Operation of SLES10 SP1 64 bit 1GB 2 vCPUs"""
    DISTRO = "sles101"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7651(_TCSmoketest):
    """Operation of SLES10 SP2 1GB 2 vCPUs"""
    DISTRO = "sles102"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7652(_TCSmoketest):
    """Operation of SLES10 SP2 64 bit 1GB 2 vCPUs"""
    DISTRO = "sles102"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7653(_TCSmoketest):
    """Operation of Windows XP SP3 5GB 2 vCPUs"""
    DISTRO = "winxpsp3"
    MEMORY = 5120
    ROOTDISK = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC7654(_TCSmoketest):
    """Operation of Windows Server 2008 Enterprise 5GB 2 vCPUs"""
    DISTRO = "ws08-x86"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC7655(_TCSmoketest):
    """Operation of Windows Server 2008 Enterprise x64 5GB 2 vCPUs"""
    DISTRO = "ws08-x64"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC7656(_TCSmoketest):
    """Operation of RHEL 4.7 5GB 2 vCPUs"""
    DISTRO = "rhel47"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC7657(_TCSmoketest):
    """Operation of RHEL 5.2 32 bit 5GB 2 vCPUs"""
    DISTRO = "rhel52"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC7658(_TCSmoketest):
    """Operation of RHEL 5.2 64 bit 5GB 2 vCPUs"""
    DISTRO = "rhel52"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7659(_TCSmoketest):
    """Operation of SLES9 SP4 5GB 2 vCPUs"""
    DISTRO = "sles94"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC7660(_TCSmoketest):
    """Operation of SLES10 SP1 64 bit 5GB 2 vCPUs"""
    DISTRO = "sles101"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7661(_TCSmoketest):
    """Operation of SLES10 SP2 5GB 2 vCPUs"""
    DISTRO = "sles102"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC7662(_TCSmoketest):
    """Operation of SLES10 SP2 64 bit 5GB 2 vCPUs"""
    DISTRO = "sles102"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7663(_TCSmoketest):
    """Operation of Windows XP SP3 1GB maximum vCPUs"""
    DISTRO = "winxpsp3"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC7664(_TCSmoketest):
    """Operation of Windows Server 2008 Enterprise 1GB maximum vCPUs"""
    DISTRO = "ws08-x86"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC7665(_TCSmoketest):
    """Operation of Windows Server 2008 Enterprise x64 1GB maximum vCPUs"""
    DISTRO = "ws08-x64"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC7666(_TCSmoketest):
    """Operation of RHEL 4.7 1GB maximum vCPUs"""
    DISTRO = "rhel47"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC7667(_TCSmoketest):
    """Operation of RHEL 5.2 32 bit 1GB maximum vCPUs"""
    DISTRO = "rhel52"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC7668(_TCSmoketest):
    """Operation of RHEL 5.2 64 bit 1GB maximum vCPUs"""
    DISTRO = "rhel52"
    MEMORY = 1024
    VCPUS = 8
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7669(_TCSmoketest):
    """Operation of SLES9 SP4 1GB maximum vCPUs"""
    DISTRO = "sles94"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC7670(_TCSmoketest):
    """Operation of SLES10 SP1 64 bit 1GB maximum vCPUs"""
    DISTRO = "sles101"
    MEMORY = 1024
    VCPUS = 8
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7671(_TCSmoketest):
    """Operation of SLES10 SP2 1GB maximum vCPUs"""
    DISTRO = "sles102"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC7672(_TCSmoketest):
    """Operation of SLES10 SP2 64 bit 1GB maximum vCPUs"""
    DISTRO = "sles102"
    MEMORY = 1024
    VCPUS = 8
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7673(_TCSmoketest):
    """Operation of Windows XP SP3 maximum memory 2 vCPUs"""
    DISTRO = "winxpsp3"
    MIGRATETEST = False
    MEMORY = 4096
    ROOTDISK = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC7674(_TCSmoketest):
    """Operation of Windows Server 2008 Enterprise maximum memory 2 vCPUs"""
    DISTRO = "ws08-x86"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC7675(_TCSmoketest):
    """Operation of Windows Server 2008 Enterprise x64 maximum memory 2 vCPUs"""
    DISTRO = "ws08-x64"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC7676(_TCSmoketest):
    """Operation of RHEL 4.7 maximum memory 2 vCPUs"""
    DISTRO = "rhel47"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC7677(_TCSmoketest):
    """Operation of RHEL 5.2 32 bit maximum memory 2 vCPUs"""
    DISTRO = "rhel52"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC7678(_TCSmoketest):
    """Operation of RHEL 5.2 64 bit maximum memory 2 vCPUs"""
    DISTRO = "rhel52"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7679(_TCSmoketest):
    """Operation of SLES9 SP4 maximum memory 2 vCPUs"""
    DISTRO = "sles94"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC7680(_TCSmoketest):
    """Operation of SLES10 SP1 64 bit maximum memory 2 vCPUs"""
    DISTRO = "sles101"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7681(_TCSmoketest):
    """Operation of SLES10 SP2 maximum memory 2 vCPUs"""
    DISTRO = "sles102"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC7682(_TCSmoketest):
    """Operation of SLES10 SP2 64 bit maximum memory 2 vCPUs"""
    DISTRO = "sles102"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC7684(_TCSmoketest):
    """Operation of Windows XP SP2 1GB 2 vCPUs"""
    DISTRO = "winxpsp2"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC8435(_TCSmoketest):
    """Operation of Windows Server 2003 SP0 Enterprise 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "w2k3ee"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC8436(_TCSmoketest):
    """Operation of Windows Server 2003 SP1 Enterprise 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "w2k3eesp1"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC8437(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "w2k3eesp2"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC8438(_TCSmoketest):
    """Operation of Windows Server 2003 SP2 Enterprise x64 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "w2k3eesp2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC8439(_TCSmoketest):
    """Operation of Windows 2000 Server SP4 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "w2kassp4"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"
    HIBERNATE = False

# Autogenerated class - do not edit
class TC8440(_TCSmoketest):
    """Operation of Windows XP SP2 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "winxpsp2"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC8441(_TCSmoketest):
    """Operation of Windows XP SP3 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "winxpsp3"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC8442(_TCSmoketest):
    """Operation of Windows Vista SP1 Enterprise 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "vistaeesp1"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC8443(_TCSmoketest):
    """Operation of Windows Vista SP1 Enterprise x64 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "vistaeesp1-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC8444(_TCSmoketest):
    """Operation of Windows Server 2008 Enterprise 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "ws08-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC8445(_TCSmoketest):
    """Operation of Windows Server 2008 Enterprise x64 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "ws08-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC8935(_TCSmoketest):
    """Operation of RHEL 5.3 32 bit using template defaults"""
    DISTRO = "rhel53"

# Autogenerated class - do not edit
class TC8936(_TCSmoketest):
    """Operation of RHEL 5.3 64 bit using template defaults"""
    DISTRO = "rhel53"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC8937(_TCSmoketest):
    """Operation of CentOS 5.3 32 bit using template defaults"""
    DISTRO = "centos53"

# Autogenerated class - do not edit
class TC8938(_TCSmoketest):
    """Operation of CentOS 5.3 64 bit using template defaults"""
    DISTRO = "centos53"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC8939(_TCSmoketest):
    """Operation of CentOS 5.3 32 bit 1GB 2 vCPUs"""
    DISTRO = "centos53"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC8940(_TCSmoketest):
    """Operation of CentOS 5.3 64 bit 1GB 2 vCPUs"""
    DISTRO = "centos53"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC8941(_TCSmoketest):
    """Operation of RHEL 5.3 32 bit 1GB 2 vCPUs"""
    DISTRO = "rhel53"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC8942(_TCSmoketest):
    """Operation of RHEL 5.3 64 bit 1GB 2 vCPUs"""
    DISTRO = "rhel53"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC8943(_TCSmoketest):
    """Operation of RHEL 5.3 32 bit 5GB 2 vCPUs"""
    DISTRO = "rhel53"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC8944(_TCSmoketest):
    """Operation of RHEL 5.3 64 bit 5GB 2 vCPUs"""
    DISTRO = "rhel53"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC8945(_TCSmoketest):
    """Operation of RHEL 5.3 32 bit 1GB maximum vCPUs"""
    DISTRO = "rhel53"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC8946(_TCSmoketest):
    """Operation of RHEL 5.3 64 bit 1GB maximum vCPUs"""
    DISTRO = "rhel53"
    MEMORY = 1024
    VCPUS = 8
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC8947(_TCSmoketest):
    """Operation of RHEL 5.3 32 bit maximum memory 2 vCPUs"""
    DISTRO = "rhel53"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC8948(_TCSmoketest):
    """Operation of RHEL 5.3 64 bit maximum memory 2 vCPUs"""
    DISTRO = "rhel53"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC8966(_TCSmoketest):
    """Operation of Windows 7 using template defaults"""
    DISTRO = "win7-x86"

# Autogenerated class - do not edit
class TC8967(_TCSmoketest):
    """Operation of Windows 7 x64 using template defaults"""
    DISTRO = "win7-x64"

# Autogenerated class - do not edit
class TC8968(_TCSmoketest):
    """Operation of Windows 7 1GB 2 vCPUs on Intel VT"""
    DISTRO = "win7-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC8969(_TCSmoketest):
    """Operation of Windows 7 x64 1GB 2 vCPUs on Intel VT"""
    DISTRO = "win7-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC8970(_TCSmoketest):
    """Operation of Windows 7 1GB 2 vCPUs on AMD-V"""
    DISTRO = "win7-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC8971(_TCSmoketest):
    """Operation of Windows 7 x64 1GB 2 vCPUs on AMD-V"""
    DISTRO = "win7-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC8972(_TCSmoketest):
    """Operation of Windows 7 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "win7-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC8973(_TCSmoketest):
    """Operation of Windows 7 x64 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "win7-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC8974(_TCSmoketest):
    """Operation of Windows 7 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "win7-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC8975(_TCSmoketest):
    """Operation of Windows 7 x64 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "win7-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC8976(_TCSmoketest):
    """Operation of Windows 7 5GB 2 vCPUs"""
    DISTRO = "win7-x86"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC8977(_TCSmoketest):
    """Operation of Windows 7 x64 5GB 2 vCPUs"""
    DISTRO = "win7-x64"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC8978(_TCSmoketest):
    """Operation of Windows 7 1GB maximum vCPUs"""
    DISTRO = "win7-x86"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC8979(_TCSmoketest):
    """Operation of Windows 7 x64 1GB maximum vCPUs"""
    DISTRO = "win7-x64"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC8980(_TCSmoketest):
    """Operation of Windows 7 maximum memory 2 vCPUs"""
    DISTRO = "win7-x86"
    MIGRATETEST = False
    MEMORY = 4096
    VCPUS = 2

# Autogenerated class - do not edit
class TC8981(_TCSmoketest):
    """Operation of Windows 7 x64 maximum memory 2 vCPUs"""
    DISTRO = "win7-x64"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC8983(_TCSmoketest):
    """Operation of Debian Lenny 5.0 using template defaults"""
    DISTRO = "debian50"

# Autogenerated class - do not edit
class TC8984(_TCSmoketest):
    """Operation of Debian Lenny 5.0 1GB 2 vCPUs"""
    DISTRO = "debian50"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC8985(_TCSmoketest):
    """Operation of Debian Lenny 5.0 5GB 2 vCPUs"""
    DISTRO = "debian50"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC8986(_TCSmoketest):
    """Operation of Debian Lenny 5.0 1GB maximum vCPUs"""
    DISTRO = "debian50"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC8987(_TCSmoketest):
    """Operation of Debian Lenny 5.0 maximum memory 2 vCPUs"""
    DISTRO = "debian50"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC8998(_TCSmoketest):
    """Operation of SLES11 using template defaults"""
    DISTRO = "sles11"

# Autogenerated class - do not edit
class TC8999(_TCSmoketest):
    """Operation of SLES11 1GB 2 vCPUs"""
    DISTRO = "sles11"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC9000(_TCSmoketest):
    """Operation of SLES11 5GB 2 vCPUs"""
    DISTRO = "sles11"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC9001(_TCSmoketest):
    """Operation of SLES11 1GB maximum vCPUs"""
    DISTRO = "sles11"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC9002(_TCSmoketest):
    """Operation of SLES11 maximum memory 2 vCPUs"""
    DISTRO = "sles11"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2

# Autogenerated class - do not edit
class TC9003(_TCSmoketest):
    """Operation of SLES11 64 bit using template defaults"""
    DISTRO = "sles11"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC9004(_TCSmoketest):
    """Operation of SLES11 64 bit 1GB 2 vCPUs"""
    DISTRO = "sles11"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC9005(_TCSmoketest):
    """Operation of SLES11 64 bit 5GB 2 vCPUs"""
    DISTRO = "sles11"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC9006(_TCSmoketest):
    """Operation of SLES11 64 bit 1GB maximum vCPUs"""
    DISTRO = "sles11"
    MEMORY = 1024
    VCPUS = 8
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC9007(_TCSmoketest):
    """Operation of SLES11 64 bit maximum memory 2 vCPUs"""
    DISTRO = "sles11"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC9059(_TCSmoketest):
    """Operation of Windows Server 2008 R2 Enterprise x64 using template defaults"""
    DISTRO = "ws08r2-x64"

# Autogenerated class - do not edit
class TC9060(_TCSmoketest):
    """Operation of Windows Server 2008 R2 Enterprise x64 1GB 2 vCPUs on Intel VT"""
    DISTRO = "ws08r2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC9061(_TCSmoketest):
    """Operation of Windows Server 2008 R2 Enterprise x64 1GB 2 vCPUs on AMD-V"""
    DISTRO = "ws08r2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC9062(_TCSmoketest):
    """Operation of Windows Server 2008 R2 Enterprise x64 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "ws08r2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC9063(_TCSmoketest):
    """Operation of Windows Server 2008 R2 Enterprise x64 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "ws08r2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC9064(_TCSmoketest):
    """Operation of Windows Server 2008 R2 Enterprise x64 5GB 2 vCPUs"""
    DISTRO = "ws08r2-x64"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC9065(_TCSmoketest):
    """Operation of Windows Server 2008 R2 Enterprise x64 1GB maximum vCPUs"""
    DISTRO = "ws08r2-x64"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC9066(_TCSmoketest):
    """Operation of Windows Server 2008 R2 Enterprise x64 maximum memory 2 vCPUs"""
    DISTRO = "ws08r2-x64"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC9091(_TCSmoketest):
    """Operation of Windows Vista SP2 Enterprise using template defaults"""
    DISTRO = "vistaeesp2"

# Autogenerated class - do not edit
class TC9092(_TCSmoketest):
    """Operation of Windows Vista SP2 Enterprise x64 using template defaults"""
    DISTRO = "vistaeesp2-x64"

# Autogenerated class - do not edit
class TC9093(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Enterprise using template defaults"""
    DISTRO = "ws08sp2-x86"

# Autogenerated class - do not edit
class TC9094(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Enterprise x64 using template defaults"""
    DISTRO = "ws08sp2-x64"

# Autogenerated class - do not edit
class TC9095(_TCSmoketest):
    """Operation of Windows Vista SP2 Enterprise 1GB 2 vCPUs on Intel VT"""
    DISTRO = "vistaeesp2"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC9096(_TCSmoketest):
    """Operation of Windows Vista SP2 Enterprise x64 1GB 2 vCPUs on Intel VT"""
    DISTRO = "vistaeesp2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC9097(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Enterprise 1GB 2 vCPUs on Intel VT"""
    DISTRO = "ws08sp2-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC9098(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Enterprise x64 1GB 2 vCPUs on Intel VT"""
    DISTRO = "ws08sp2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC9099(_TCSmoketest):
    """Operation of Windows Vista SP2 Enterprise 1GB 2 vCPUs on AMD-V"""
    DISTRO = "vistaeesp2"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC9100(_TCSmoketest):
    """Operation of Windows Vista SP2 Enterprise x64 1GB 2 vCPUs on AMD-V"""
    DISTRO = "vistaeesp2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC9101(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Enterprise 1GB 2 vCPUs on AMD-V"""
    DISTRO = "ws08sp2-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC9102(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Enterprise x64 1GB 2 vCPUs on AMD-V"""
    DISTRO = "ws08sp2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC9103(_TCSmoketest):
    """Operation of Windows Vista SP2 Enterprise 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "vistaeesp2"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC9104(_TCSmoketest):
    """Operation of Windows Vista SP2 Enterprise x64 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "vistaeesp2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC9105(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Enterprise 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "ws08sp2-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC9106(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Enterprise x64 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "ws08sp2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC9107(_TCSmoketest):
    """Operation of Windows Vista SP2 Enterprise 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "vistaeesp2"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC9108(_TCSmoketest):
    """Operation of Windows Vista SP2 Enterprise x64 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "vistaeesp2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC9109(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Enterprise 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "ws08sp2-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC9110(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Enterprise x64 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "ws08sp2-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC9111(_TCSmoketest):
    """Operation of Windows Vista SP2 Enterprise 5GB 2 vCPUs"""
    DISTRO = "vistaeesp2"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC9112(_TCSmoketest):
    """Operation of Windows Vista SP2 Enterprise x64 5GB 2 vCPUs"""
    DISTRO = "vistaeesp2-x64"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC9113(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Enterprise 5GB 2 vCPUs"""
    DISTRO = "ws08sp2-x86"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC9114(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Enterprise x64 5GB 2 vCPUs"""
    DISTRO = "ws08sp2-x64"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC9115(_TCSmoketest):
    """Operation of Windows Vista SP2 Enterprise 1GB maximum vCPUs"""
    DISTRO = "vistaeesp2"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC9116(_TCSmoketest):
    """Operation of Windows Vista SP2 Enterprise x64 1GB maximum vCPUs"""
    DISTRO = "vistaeesp2-x64"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC9117(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Enterprise 1GB maximum vCPUs"""
    DISTRO = "ws08sp2-x86"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC9118(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Enterprise x64 1GB maximum vCPUs"""
    DISTRO = "ws08sp2-x64"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC9119(_TCSmoketest):
    """Operation of Windows Vista SP2 Enterprise maximum memory 2 vCPUs"""
    DISTRO = "vistaeesp2"
    MIGRATETEST = False
    MEMORY = 4096
    VCPUS = 2

# Autogenerated class - do not edit
class TC9120(_TCSmoketest):
    """Operation of Windows Vista SP2 Enterprise x64 maximum memory 2 vCPUs"""
    DISTRO = "vistaeesp2-x64"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC9121(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Enterprise maximum memory 2 vCPUs"""
    DISTRO = "ws08sp2-x86"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC9122(_TCSmoketest):
    """Operation of Windows Server 2008 SP2 Enterprise x64 maximum memory 2 vCPUs"""
    DISTRO = "ws08sp2-x64"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2

# Autogenerated class - do not edit
class TC9555(_TCSmoketest):
    """Operation of RHEL 4.8 using template defaults"""
    DISTRO = "rhel48"

# Autogenerated class - do not edit
class TC9556(_TCSmoketest):
    """Operation of CentOS 4.8 using template defaults"""
    DISTRO = "centos48"

# Autogenerated class - do not edit
class TC9557(_TCSmoketest):
    """Operation of CentOS 4.8 1GB 2 vCPUs"""
    DISTRO = "centos48"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC9559(_TCSmoketest):
    """Operation of RHEL 4.8 1GB 2 vCPUs"""
    DISTRO = "rhel48"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC9561(_TCSmoketest):
    """Operation of RHEL 4.8 5GB 2 vCPUs"""
    DISTRO = "rhel48"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC9563(_TCSmoketest):
    """Operation of RHEL 4.8 1GB maximum vCPUs"""
    DISTRO = "rhel48"
    MEMORY = 1024
    VCPUS = 8

# Autogenerated class - do not edit
class TC9566(_TCSmoketest):
    """Operation of RHEL 4.8 maximum memory 2 vCPUs"""
    DISTRO = "rhel48"
    MIGRATETEST = False
    MEMORY = 16384
    VCPUS = 2


# Autogenerated class - do not edit
class TC26250(_TCSmoketest):
    """Operation of Windows 10 using template defaults"""
    DISTRO = "win10-x86"
 
# Autogenerated class - do not edit
class TC26251(_TCSmoketest):
    """Operation of Windows 10 x64 using template defaults"""
    DISTRO = "win10-x64"

# Autogenerated class - do not edit
class TC26278(_TCSmoketest):
    """Operation of Windows 10 1GB 2 vCPUs on Intel VT"""
    DISTRO = "win10-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC26279(_TCSmoketest):
    """Operation of Windows 10 x64 1GB 2 vCPUs on Intel VT"""
    DISTRO = "win10-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMX"

# Autogenerated class - do not edit
class TC26280(_TCSmoketest):
    """Operation of Windows 10 1GB 2 vCPUs on AMD-V"""
    DISTRO = "win10-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC26281(_TCSmoketest):
    """Operation of Windows 10 x64 1GB 2 vCPUs on AMD-V"""
    DISTRO = "win10-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC26282(_TCSmoketest):
    """Operation of Windows 10 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "win10-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC26283(_TCSmoketest):
    """Operation of Windows 10 x64 1GB 2 vCPUs on AMD-V+NPT"""
    DISTRO = "win10-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "SVMHAP"

# Autogenerated class - do not edit
class TC26284(_TCSmoketest):
    """Operation of Windows 10 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "win10-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC26285(_TCSmoketest):
    """Operation of Windows 10 x64 1GB 2 vCPUs on VT+EPT"""
    DISTRO = "win10-x64"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXEPT"

# Autogenerated class - do not edit
class TC26312(_TCSmoketest):
    """Operation of Windows 10 5GB 2 vCPUs"""
    DISTRO = "win10-x86"
    MEMORY = 5120
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC26313(_TCSmoketest):
    """Operation of Windows 10 x64 5GB 2 vCPUs"""
    DISTRO = "win10-x64"
    MEMORY = 5120
    VCPUS = 2
    VARCH = "SVM"

# Autogenerated class - do not edit
class TC26342(_TCSmoketest):
    """Operation of Windows 10 1GB maximum vCPUs (XenServer guest limit 32)"""
    DISTRO = "win10-x86"
    MEMORY = 1024
    VCPUS = 8
    VCPUS = 2

# Autogenerated class - do not edit
class TC26343(_TCSmoketest):
    """Operation of Windows 10 x64 1GB maximum vCPUs (XenServer guest limit 32)"""
    DISTRO = "win10-x64"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC26344(_TCSmoketest):
    """Operation of Windows 10 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "win10-x86"
    MIGRATETEST = False
    MEMORY = 16384
    MEMORY = 131072
    VCPUS = 2

# Autogenerated class - do not edit
class TC26345(_TCSmoketest):
    """Operation of Windows 10 x64 maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "win10-x64"
    MIGRATETEST = False
    MEMORY = 131072
    VCPUS = 2
    
# Autogenerated class - do not edit
class TC26445(_TCSmoketest):
    """Operation of SL 5.11 32 bit using template defaults"""
    DISTRO = "sl511"

# Autogenerated class - do not edit
class TC26470(_TCSmoketest):
    """Operation of SL 5.11 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "sl511"
    MIGRATETEST = False
    MEMORY = 8192
    VCPUS = 2

# Autogenerated class - do not edit
class TC26450(_TCSmoketest):
    """Operation of SL 5.11 32 bit 1GB 2 vCPUs"""
    DISTRO = "sl511"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC26456(_TCSmoketest):
    """Operation of SL 5.11 32 bit 5GB 2 vCPUs"""
    DISTRO = "sl511"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC26462(_TCSmoketest):
    """Operation of SL 5.11 32 bit 1GB maximum vCPUs (XenServer guest limit 32)"""
    DISTRO = "sl511"
    MEMORY = 1024
    VCPUS = 16


# Autogenerated class - do not edit
class TC26448(_TCSmoketest):
    """Operation of SL 5.11 64 bit using template defaults"""
    DISTRO = "sl511"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC26468(_TCSmoketest):
    """Operation of SL 5.11 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "sl511"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC26454(_TCSmoketest):
    """Operation of SL 5.11 64 bit 1GB 2 vCPUs"""
    DISTRO = "sl511"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC26460(_TCSmoketest):
    """Operation of SL 5.11 64 bit 5GB 2 vCPUs"""
    DISTRO = "sl511"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC26465(_TCSmoketest):
    """Operation of SL 5.11 64 bit 1GB maximum vCPUs (XenServer guest limit 32)"""
    DISTRO = "sl511"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC26446(_TCSmoketest):
    """Operation of SL 6.6 32 bit using template defaults"""
    DISTRO = "sl66"

# Autogenerated class - do not edit
class TC26451(_TCSmoketest):
    """Operation of SL 6.6 32 bit 1GB 2 vCPUs"""
    DISTRO = "sl66"
    MEMORY = 1024
    VCPUS = 2

# Autogenerated class - do not edit
class TC26457(_TCSmoketest):
    """Operation of SL 6.6 32 bit 5GB 2 vCPUs"""
    DISTRO = "sl66"
    MEMORY = 5120
    VCPUS = 2

# Autogenerated class - do not edit
class TC26471(_TCSmoketest):
    """Operation of SL 6.6 32 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "sl66"
    MIGRATETEST = False
    MEMORY = 131072
    MEMORY = 8192
    VCPUS = 2
    
# Autogenerated class - do not edit
class TC26463(_TCSmoketest):
    """Operation of SL 6.6 32 bit 1GB maximum vCPUs (XenServer guest limit 32)"""
    DISTRO = "sl66"
    MEMORY = 1024
    VCPUS = 2
    VCPUS = 16

# Autogenerated class - do not edit
class TC26449(_TCSmoketest):
    """Operation of SL 6.6 64 bit using template defaults"""
    DISTRO = "sl66"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC26455(_TCSmoketest):
    """Operation of SL 6.6 64 bit 1GB 2 vCPUs"""
    DISTRO = "sl66"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC26461(_TCSmoketest):
    """Operation of SL 6.6 64 bit 5GB 2 vCPUs"""
    DISTRO = "sl66"
    MEMORY = 5120
    CPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC26466(_TCSmoketest):
    """Operation of SL 6.6 64 bit 1GB maximum vCPUs (XenServer guest limit 32)"""
    DISTRO = "sl66"
    MEMORY = 1024
    VCPUS = 16
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC26469(_TCSmoketest):
    """Operation of SL 6.6 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "sl66"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC26447(_TCSmoketest):
    """Operation of SL 7.0 64 bit using template defaults"""
    DISTRO = "sl7"
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC26453(_TCSmoketest):
    """Operation of SL 7.0 64 bit 1GB 2 vCPUs"""
    DISTRO = "sl7"
    MEMORY = 1024
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC26459(_TCSmoketest):
    """Operation of SL 7.0 64 bit 5GB 2 vCPUs"""
    DISTRO = "sl7"
    MEMORY = 5120
    VCPUS = 2
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC26464(_TCSmoketest):
    """Operation of SL 7.0 64 bit 1GB maximum vCPUs (XenServer guest limit 32)"""
    DISTRO = "sl7"
    MEMORY = 1024
    VCPUS = 32
    ARCH = "x86-64"

# Autogenerated class - do not edit
class TC26467(_TCSmoketest):
    """Operation of SL 7.0 64 bit maximum memory (XenServer guest limit 128G/64G) 2 vCPUs"""
    DISTRO = "sl7"
    MIGRATETEST = False
    MEMORY = 32768
    VCPUS = 2
    ARCH = "x86-64"

    
