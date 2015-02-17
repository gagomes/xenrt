import xenrt
import os, copy, time, random, re, json, string, threading
import testcases.xenserver.guest
from xenrt.lazylog import step, comment, log, warning
from testcases.benchmarks import workloads
from testcases.benchmarks import graphics
from abc import ABCMeta, abstractmethod

"""
Enums
"""
class VGPUOS: Win7x86, Win7x64, WS2008R2, Win8x86, Win8x64, Win81x86, Win81x64, WS12x64, WS12R2x64,DEBIAN,Centos7,Rhel7,Oel7,Ubuntu1404x86,Ubuntu1404x64 = range(15)
class VGPUConfig: K100, K120, K140, K160, K180, K1PassThrough, K200, K220, K240, K260, K280, K2PassThrough = range(12)
class VGPUDistribution: BreadthFirst, DepthFirst = range(2)
class SRType: Local, NFS, ISCSI = range(3)
class VMStartMethod: OneByOne, Simultenous = range(2)
class CardType: K1, K2, PassThrough, NotAvailable = range(4)
class DriverType: Signed, Unsigned = range(2)
class DiffvGPUType: NvidiaWinvGPU, NvidiaLinuxvGPU, IntelWinvGPU = range(3)

"""
Constants
"""
NumOfPGPUPerCard = {
    CardType.K1 : 4,
    CardType.K2 : 2,
    CardType.PassThrough : 1,
    CardType.NotAvailable : 0
    }
MaxNumOfVGPUPerPGPU = {
    VGPUConfig.K100 :  8,
    VGPUConfig.K120 :  8,
    VGPUConfig.K140 :  4,
    VGPUConfig.K1PassThrough : 1,
    VGPUConfig.K200 :  8,
    VGPUConfig.K220 :  8,
    VGPUConfig.K240 :  4,
    VGPUConfig.K260 :  2,
    VGPUConfig.K2PassThrough : 1
    }

"""
Helper classes
"""
class VGPUBenchmark(object):
    __GAMING_SCORES_WIN7_X64 = {
                     VGPUConfig.K100 :  6.7,
                     VGPUConfig.K140 :  6.7,
                     VGPUConfig.K1PassThrough :  5.7,
                     VGPUConfig.K200 :  7.8,
                     VGPUConfig.K240 :  7.7,
                     VGPUConfig.K260 :  7.7,
                     VGPUConfig.K2PassThrough :  1
                   }
    __GAMING_SCORES_WIN7_X86 = {
                     VGPUConfig.K100 :  6.7,
                     VGPUConfig.K140 :  6.7,
                     VGPUConfig.K1PassThrough :  6.7,
                     VGPUConfig.K200 :  7.7,
                     VGPUConfig.K240 :  7.7,
                     VGPUConfig.K260 :  1,
                     VGPUConfig.K2PassThrough :  7.8
                   }
    __GAMING_SCORES_WS2008R2_X64 = {
                     VGPUConfig.K100 :  6.7,
                     VGPUConfig.K140 :  6.7,
                     VGPUConfig.K1PassThrough :  1,
                     VGPUConfig.K200 :  7.7,
                     VGPUConfig.K240 :  7.7,
                     VGPUConfig.K260 :  7.9,
                     VGPUConfig.K2PassThrough :  1
                   }
    __GRAPHICS_SCORES_WIN7_X64 = {
                     VGPUConfig.K100 :  6.7,
                     VGPUConfig.K140 :  5.9,
                     VGPUConfig.K1PassThrough :  5.9,
                     VGPUConfig.K200 :  7.8,
                     VGPUConfig.K240 :  7.7,
                     VGPUConfig.K260 :  7.7,
                     VGPUConfig.K2PassThrough :  7.8
                   }
    __GRAPHICS_SCORES_WIN7_X86 = {
                     VGPUConfig.K100 :  6.7,
                     VGPUConfig.K140 :  6.7,
                     VGPUConfig.K1PassThrough :  6.7,
                     VGPUConfig.K200 :  7.7,
                     VGPUConfig.K240 :  7.7,
                     VGPUConfig.K260 :  1,
                     VGPUConfig.K2PassThrough :  7.8
                   }
    __GRAPHICS_SCORES_WS2008R2_X64 = {
                     VGPUConfig.K100 :  5.9,
                     VGPUConfig.K140 :  5.9,
                     VGPUConfig.K1PassThrough :  1,
                     VGPUConfig.K200 :  7.9,
                     VGPUConfig.K240 :  7.9,
                     VGPUConfig.K260 :  7.9,
                     VGPUConfig.K2PassThrough :  7.8
                   }

    __GRAPHICS_LEEWAY = 1
    __GAMING_LEEWAY = 1

    def __init__(self, vgpuos, config):
        self.__os = vgpuos
        self.__config = config

    def __getScore(self, dictionary):
        if not self.__config in dictionary:
            raise xenrt.XRTFailure("No score found for the provided os type")
        return dictionary[self.__config]

    def __getGamingLookup(self):
        if self.__os == VGPUOS.Win7x64:
            return self.__GAMING_SCORES_WIN7_X64

        if self.__os == VGPUOS.Win7x86:
            return self.__GAMING_SCORES_WIN7_X86

        if self.__os == VGPUOS.WS2008R2:
            return self.__GAMING_SCORES_WS2008R2_X64

    def __getGraphicsLookup(self):
        if self.__os == VGPUOS.Win7x64:
            return self.__GRAPHICS_SCORES_WIN7_X64

        if self.__os == VGPUOS.Win7x86:
            return self.__GRAPHICS_SCORES_WIN7_X86

        if self.__os == VGPUOS.WS2008R2:
            return self.__GRAPHICS_SCORES_WS2008R2_X64

    def graphicsScore(self):
        return self.__getScore(self.__getGraphicsLookup())

    def gamingScore(self):
        return self.__getScore(self.__getGamingLookup())

    def gamingScoreMinimum(self):
        return self.gamingScore() - self.__GAMING_LEEWAY

    def graphicsScoreMinimum(self):
        return self.graphicsScore() - self.__GRAPHICS_LEEWAY

class VGPUInstaller(object):
    __GROUP_K1 = "K1"
    __GROUP_K2 = "K2"
    __TYPE_PT = "passthrough"


    def __init__(self, host, config, distribution=VGPUDistribution.DepthFirst):
        self.__config = config
        self.__host = host
        self._distribution = distribution
        log("Config: %s, Host: %s, Distribution: %s" % (str(self.__config), str(self.__host), str(self._distribution)))

    def groupUUID(self):
        ggman = GPUGroupManager(self.__host)
        ggman.obtainExistingGroups()
        for group in ggman.groups:
            gtype = group.getGridType()
            if self.__config == VGPUConfig.K100 or self.__config == VGPUConfig.K120 or self.__config == VGPUConfig.K140 or self.__config == VGPUConfig.K1PassThrough or self.__config == VGPUConfig.K160 or self.__config == VGPUConfig.K180:
                if self.__GROUP_K1 in gtype:
                    return group.uuid
            else:
                if self.__GROUP_K2 in gtype:
                    return group.uuid

        raise xenrt.XRTFailure("A group of config %s was required but none were found" % str(self.__config))

    def typeUUID(self):
        vGPUTypes = self.__host.getSupportedVGPUTypes()
        # Look up the string representations of the VGPUConfig members filtering them on the required config
        selectedConfigs = [attr for attr in dir(VGPUConfig()) if not callable(attr) and not attr.startswith("__") and getattr(VGPUConfig, attr) == self.__config]

        if len(selectedConfigs) < 1:
            raise xenrt.XRTFailure("No selected configs found")

        selectedConfig = selectedConfigs[0]

        if VGPUConfig.K2PassThrough == self.__config or VGPUConfig.K1PassThrough == self.__config:
            selectedConfig = self.__TYPE_PT
            # Workaround NVIDIA-132 where the host will crash if a bugtool is taken
            self.__host.execdom0("rm -rf /etc/xensource/bugtool/NVIDIA*")

        for vGPUType in vGPUTypes:
            if selectedConfig in vGPUType:
                return vGPUTypes[vGPUType]
        raise xenrt.XRTFailure("No type of %s was found in %s" % (selectedConfig, str(vGPUTypes)))

    def createOnGuest(self, guest, groupUUID = None, replacevGPU=False):

        state = guest.getState()
        if guest.getState() != "DOWN":
            guest.shutdown()

        if not self.__host.isGPUCapable():
            raise xenrt.XRTFailure("Host is not GPU capable")

        if not groupUUID:
            groupUUID = self.groupUUID()

        step("Set up vGPU distibution mode")
        if self._distribution == VGPUDistribution.DepthFirst:
            self.__host.setDepthFirstAllocationType(groupUUID)
        else:
            self.__host.setBreadthFirstAllocationType(groupUUID)

        typeUUID = self.typeUUID()

        step("Creating a vGPU on %s" % guest.getName())
        log("GPU Group UUID: %s, Type UUID: %s" % (groupUUID,typeUUID))
        if not guest.hasvGPU():
            log("No vGPU so creating one...")
            guest.createvGPU(groupUUID, typeUUID)
        elif guest.hasvGPU() and replacevGPU:
            log("vGPU found, replacing it...")
            guest.destroyvGPU()
            guest.createvGPU(groupUUID, typeUUID)
        else:
            log("vGPU found so skipping creation...")

        log("Revert guest state back to %s." % state)
        guest.setState(state)

"""
Test base classes
"""
# TODO remove multiple inheritance
class VGPUTest(xenrt.TestCase, object):
    _CONFIGURATION = {
        VGPUConfig.K100 : "K100",
        VGPUConfig.K120 : "K120",
        VGPUConfig.K140 : "K140",
        VGPUConfig.K160 : "K160",
        VGPUConfig.K180 : "K180",
        VGPUConfig.K1PassThrough : "K1PassThrough",
        VGPUConfig.K200 : "K200",
        VGPUConfig.K220 : "K220",
        VGPUConfig.K240 : "K240",
        VGPUConfig.K260 : "K260",
        VGPUConfig.K280 : "K280",
        VGPUConfig.K2PassThrough : "K2PassThrough"
    }

    _DIFFVGPUTYPE = {
        DiffvGPUType.NvidiaWinvGPU : "nvidiawinvgpu",
        DiffvGPUType.NvidiaLinuxvGPU : "nvidialinuxvgpu",
        DiffvGPUType.IntelWinvGPU : "intelwinvgpu"
    }

    def getDiffvGPUName(self, typeofvGPU):
        if not typeofvGPU in self._DIFFVGPUTYPE:
            raise xenrt.XRTError("Unexpected vGPU Type: %s" % typeofvGPU)
        return self._DIFFVGPUTYPE[typeofvGPU]

    def isNvidiaK1(self, config):
        return config in [ VGPUConfig.K100, VGPUConfig.K120, VGPUConfig.K140, VGPUConfig.K160, VGPUConfig.K180, VGPUConfig.K1PassThrough]

    def isNvidiaK2(self, config):
        return not self.isNvidiaK1(config)

    def typeOfvGPUonVM(self,vm):

        host = vm.host
        vgpuuuidList = host.minimalList("vgpu-list", args="vm-uuid=%s" % vm.getUUID())
        if not vgpuuuidList:
            log("No VGPU is attached")
            return None, None
        vgpuuuid = vgpuuuidList[0]
        typeOfVGPU = host.genParamGet("vgpu",vgpuuuid,"type-model-name")

        return typeOfVGPU, vgpuuuid

    def assertvGPURunningInWinVM(self, vm, vGPUType):
        if not self.checkvGPURunningInVM(vm, vGPUType):
            raise xenrt.XRTFailure("vGPU not running in VM %s: %s" % (vm.getName(),vm.getUUID()))

    def assertvGPUNotRunningInWinVM(self, vm, vGPUType):
        if self.checkvGPURunningInVM(vm, vGPUType):
            raise xenrt.XRTFailure("vGPU running when not expected in VM %s: %s" % (vm.getName(),vm.getUUID()))

    def checkvGPURunningInVM(self, vm, vGPUType):

        gpu = self.findGPUInVM(vm)

        if not gpu:
            log("vGPU not found on VM")
            return False

        device = "\\".join(gpu.split("\\")[0:2])
        lines = vm.devcon("status \"%s\"" % device).splitlines()

        vGPUType = vGPUType.replace("PassThrough", "$")

        for l in lines:
            if "Name" in l:
                vGPU = l.split(":")[1].strip()
                if re.search(vGPUType, vGPU):
                    log("vGPU of type %s found on VM" % (vGPU))
                    break
                else:
                    log("Desired vGPU not found instead %s is present on VM" % (vGPU))
                    return False

        for l in lines:
            if "Device has a problem" in l or "No matching devices found" in l:
                return False
            if "Driver is running" in l:
                return True
        raise xenrt.XRTError("Could not determine whether GPU is running")

    def findGPUInVM(self,vm):

        vm.waitForDaemon(1800, desc="Windows starting up")
        lines = vm.devcon("find *").splitlines()
        nvidiaDevice = "PCI.VEN_10DE.*(NVIDIA|VGA|Display).*"  #nvidia pci vendor id

        for line in lines:
            if line.startswith("PCI"):
                xenrt.TEC().logverbose("devcon: %s" % line)
                if re.search(nvidiaDevice,line) and not re.search(".*(Audio).*",line):
                    xenrt.TEC().logverbose("Found GPU device: %s" % line)
                    return line.strip()
        return None

    @property
    def driverType(self):
        useUnsigned = xenrt.TEC().lookup("UNSIGNED_VGPU_DRIVERS",
                                         default="no")
        if useUnsigned == "no":
            return DriverType.Signed
        return DriverType.Unsigned

    def installNvidiaHostDrivers(self):
        for host in self.getAllHosts():
            host.installNVIDIAHostDrivers()

    def installNvidiaWindowsDrivers(self, guest):
        guest.installNvidiaVGPUDriver(self.driverType)

    def installNvidiaLinuxDrivers(self,guest):
        guest.installPVHVMNvidiaGpuDrivers()

    def installIntelWindowsDrivers(self,guest):
        guest.installIntelGPUDriver()

    def assertvGPURunningInLinuxVM(self, vm, vGPUType, card):
        if not vm.isGPUBeingUtilized(card):
            raise xenrt.XRTFailure("vGPU not running in VM %s: %s" % (vm.getName(),vm.getUUID()))

    def assertvGPUNotRunningInLinuxVM(self, vm, vGPUType, card):
        if self.isGPUBeingUtilized(card):
            raise xenrt.XRTFailure("vGPU running when not expected in VM %s: %s" % (vm.getName(),vm.getUUID()))

    def runWindowsWorkload(self,vm):

        unigine = graphics.UnigineTropics(vm)
        unigine.install()
        unigine.runAsWorkload()
        xenrt.sleep(300)

class TCVGPUNode0Pin(xenrt.TestCase):
    def parseArgs(self, arglist):
        self.args = {}
        for a in arglist:
            (arg, value) = a.split("=", 1)
            self.args[arg] = value

    def prepare(self, arglist):
        self.parseArgs(arglist)
        self.host = self.getDefaultHost()
        self.guest = self.getGuest(self.args['guest'])
        self.guest.setState("DOWN")

    def run(self, arglist):
        ggman = GPUGroupManager(self.host)
        # Disable GPUs at PCI IDs below, which are on Node 1
        gpus = []
        #for i in ["0000:44:00.0", "0000:45:00.0", "0000:46:00.0", "0000:47:00.0"]:
        for i in ["0000:07:00.0", "0000:08:00.0", "0000:09:00.0", "0000:0a:00.0"]:
            gpus.extend(self.host.minimalList("pgpu-list", "uuid", "pci-id=%s" % i))

        for g in gpus:
            ggman.isolatePGPU(g)

        node0cpus = self.host.execdom0("xenpm get-cpu-topology | awk '{if ($4==0) { print $1} }' | sed 's/CPU//'").splitlines()

        self.guest.paramSet("VCPUs-params:mask", string.join(node0cpus, ","))
        self.guest.setState("UP")

class TCVGPUSetup(VGPUTest):
    def parseArgs(self, arglist):
        self.args = {}
        for a in arglist:
            (arg, value) = a.split("=", 1)
            self.args[arg] = value

    def prepare(self, arglist):
        self.parseArgs(arglist)
        if not self.args.has_key("host"):
            self.args['host'] = "0"
        self.host = self.getHost("RESOURCE_HOST_%s" % self.args['host'])
        self.guest = self.getGuest(self.args['guest'])
        if not self.guest:
            self.guest = self.host.createBasicGuest(name=self.args['guest'], distro=self.args['distro'])
        # If we have a clean snapshot, revert to it, otherwise create one
        snaps = self.host.minimalList("snapshot-list", "uuid", "snapshot-of=%s name-label=clean" % self.guest.uuid)
        self.guest.setState("DOWN")
        if len(snaps) == 0:
            self.guest.snapshot("clean")
        else:
            self.guest.revert(snaps[0])

    def run(self, arglist):
        self.guest.setState("DOWN")
        if not xenrt.TEC().lookup("OPTION_ENABLE_VGPU_VNC", False, boolean=True):
            self.guest.setVGPUVNCActive(False)
        self.host.installNVIDIAHostDrivers()
        #setting up dom0 mem
        self.host.execdom0("/opt/xensource/libexec/xen-cmdline --set-xen dom0_mem=4096M,max:6144M")
        self.host.reboot()
        cfg = [x for x in self._CONFIGURATION.keys() if self._CONFIGURATION[x]==self.args['vgpuconfig']][0]
        installer = VGPUInstaller(self.host, cfg)
        installer.createOnGuest(self.guest)
        self.guest.setState("UP")
        self.guest.installNvidiaVGPUDriver(self.driverType)

        if "PassThrough" in self.args['vgpuconfig']:
            autoit = self.guest.installAutoIt()
            au3path = "c:\\change_display.au3"
            au3scr = """
Send("!c")
Send("!s")
Send("{DOWN}")
Send("!m")
Send("{DOWN}")
Send("!a")
Send("!s")
Send("{DOWN}")
Send("!m")
Send("{DOWN}")
Send("!a")
Send("{LEFT}")
Send("{ENTER}")
"""
            self.guest.xmlrpcWriteFile(au3path, au3scr)
            try:
                #This command will throw error
                self.guest.xmlrpcExec("control.exe desk.cpl,Settings,@Settings")
            except:
                pass
            self.guest.xmlrpcStart("\"%s\" %s" % (autoit, au3path))
        self.assertvGPURunningInWinVM(self.guest, self.args['vgpuconfig'])

class TCVGPUCloneVM(VGPUTest):
    def parseArgs(self, arglist):
        self.args = {}
        for a in arglist:
            (arg, value) = a.split("=", 1)
            self.args[arg] = value

    def prepare(self, arglist):
        self.parseArgs(arglist)
        self.guest = self.getGuest(self.args['guest'])
        self.guest.setState("DOWN")

    def run(self, arglist):
        guests = []
        for i in xrange(int(self.args['clones'])):
            g = self.guest.cloneVM(name="%s-clone%d" % (self.guest.name, i), noIP=True)
            xenrt.TEC().registry.guestPut(g.name, g)
            guests.append(g)

        for g in guests:
            if not xenrt.TEC().lookup("OPTION_ENABLE_VGPU_VNC", False, boolean=True):
                self.guest.setVGPUVNCActive(False)
            g.start()

        if self.args.has_key("vgpuconfig"):
            for g in guests:
                self.assertvGPURunningInWinVM(g, self.args['vgpuconfig'])

class TCVGPUDeleteClones(xenrt.TestCase):
    def parseArgs(self, arglist):
        self.args = {}
        for a in arglist:
            (arg, value) = a.split("=", 1)
            self.args[arg] = value

    def prepare(self, arglist):
        self.parseArgs(arglist)

    def run(self, arglist):
        i = 0
        while True:
            g = self.getGuest("%s-clone%d" % (self.args['guest'], i))
            i += 1
            if not g:
                break
            g.setState("DOWN")
            g.uninstall()
            xenrt.TEC().registry.guestDelete(g.name)
        if self.args.has_key("clones") and i < int(self.args['clones']):
            raise xenrt.XRTError("Insufficient clones found to delete")

class TCGPUBootstorm(VGPUTest):
    def parseArgs(self, arglist):
        self.params = {}
        self.vgpuconfig = None
        self.guests = []
        self.args = {}
        guest = None
        clones = None
        for a in arglist:
            (arg, value) = a.split("=", 1)
            if arg=="guest":
                guest = value
            elif arg=="clones":
                clones = int(value)
            elif arg=="vgpuconfig":
                self.vgpuconfig = value
            else:
                self.args[arg] = value

        if clones:
            for i in xrange(clones):
                self.guests.append(self.getGuest("%s-clone%d" % (guest, i)))
        else:
            self.guests.append(self.getGuest(guest))

    def guestShutdown(self, guest):
        guest.setState("DOWN")

    def guestStart(self, guest):
        guest.start()
        self.times[guest.name] = xenrt.util.timenow() - self.starttime
        if self.vgpuconfig:
            self.assertvGPURunningInWinVM(guest, self.vgpuconfig)


    def prepare(self, arglist):
        self.parseArgs(arglist)
        xenrt.pfarm([xenrt.PTask(self.guestShutdown, x) for x in self.guests])

    def run(self, arglist):
        self.starttime = xenrt.util.timenow()
        self.times = {}
        xenrt.pfarm([xenrt.PTask(self.guestStart, x) for x in self.guests])
        f = open("%s/boottimes.json" % (xenrt.TEC().getLogdir()), "w")
        f.write(json.dumps(self.times))
        f.close()

class TCGPUBenchmarkInstall(VGPUTest):
    def parseArgs(self, arglist):
        self.args = {}
        self.benchmarks = []
        self.params = {}
        self.vgpuconfig = None
        self.guests = []
        self.benchmarkObjects = {}
        self.args = {}
        guest = None
        clones = None
        for a in arglist:
            (arg, value) = a.split("=", 1)
            if arg=="guest":
                guest = value
            elif arg=="clones":
                clones = int(value)
            elif arg=="params":
                self.params=json.loads(value)
            elif arg=="benchmark":
                self.benchmarks.append(value)
            elif arg=="vgpuconfig":
                self.vgpuconfig = value
            else:
                self.args[arg] = value

        if clones:
            for i in xrange(clones):
                self.guests.append(self.getGuest("%s-clone%d" % (guest, i)))
        else:
            self.guests.append(self.getGuest(guest))

    def prepare(self, arglist):
        self.parseArgs(arglist)
        for g in self.guests:
            g.setState("UP")
        if self.vgpuconfig:
            for g in self.guests:
                self.assertvGPURunningInWinVM(g, self.vgpuconfig)

    def run(self, arglist):
        for b in self.benchmarks:
            self.benchmarkObjects[b] = {}
            if b.endswith("-ScaleUp"):
                benchmarkObject = b[:-8]
            else:
                benchmarkObject = b
            for g in self.guests:
                self.benchmarkObjects[b][g.name] = eval("graphics.%s" % benchmarkObject)(g)
                try:
                    self.benchmarkObjects[b][g.name].install()
                    self.testcaseResult("InstallBenchmark", "%s-%s" % (b, g.name), xenrt.RESULT_PASS)
                except Exception, e:
                    self.testcaseResult("InstallBenchmark", "%s-%s" % (b, g.name), xenrt.RESULT_FAIL, str(e))


class TCGPUBenchmark(TCGPUBenchmarkInstall):

    def runBenchmark(self, guest):
        self.benchmarkObjects[self.currentBenchmark][guest.name].run(self.params)

    def prepareBenchmark(self, guest):
        self.benchmarkObjects[self.currentBenchmark][guest.name].prepare(self.params)

    def run(self, arglist):
        super(TCGPUBenchmark, self).run(arglist)
        for b in self.benchmarks:
            results = {}
            try:
                self.currentBenchmark = b
                if b.endswith("-ScaleUp"):
                    for i in range(len(self.guests)):
                        results[i+1] = {}
                        xenrt.pfarm([xenrt.PTask(self.prepareBenchmark, x) for x in self.guests[:i+1]])
                        xenrt.pfarm([xenrt.PTask(self.runBenchmark, x) for x in self.guests[:i+1]])
                        for g in self.guests[:i+1]:
                            self.benchmarkObjects[b][g.name].setLogSuffix("scaleup%d" % i)
                            results[i+1][g.name] = self.benchmarkObjects[b][g.name].getResults()
                else:
                    xenrt.pfarm([xenrt.PTask(self.prepareBenchmark, x) for x in self.guests])
                    xenrt.pfarm([xenrt.PTask(self.runBenchmark, x) for x in self.guests])
                    for g in self.guests:
                        results[g.name] = self.benchmarkObjects[b][g.name].getResults()
                f = open("%s/%s.json" % (xenrt.TEC().getLogdir(), b), "w")
                f.write(json.dumps(results))
                f.close()
                self.testcaseResult("RunBenchmark", b, xenrt.RESULT_PASS)

            except Exception, e:
                self.testcaseResult("RunBenchmark", b, xenrt.RESULT_FAIL, str(e))

class TCGPUWorkload(TCGPUBenchmarkInstall):
    def run(self, arglist):
        super(TCGPUWorkload, self).run(arglist)
        self.failed = []
        for b in self.benchmarks:
            for g in self.guests:
                try:
                    self.benchmarkObjects[b][g.name].runAsWorkload(self.params)
                    self.benchmarkObjects[b][g.name].checkWorkload()
                except Exception, e:
                    self.failed.append("%s-%s" % (g.name, b))
                    xenrt.TEC().reason("Workload %s failed to start on %s - %s" % (b, g.name, str(e)))

        end = xenrt.util.timenow() + int(self.args['time'])

        while xenrt.util.timenow() < end:
            xenrt.sleep(30)
            checked = False
            for b in self.benchmarks:
                for g in self.guests:
                    if "%s-%s" % (g.name, b) in self.failed:
                        continue
                    checked = True
                    try:
                        self.benchmarkObjects[b][g.name].checkWorkload()
                    except Exception, e:
                        self.failed.append("%s-%s" % (g.name, b))
                        xenrt.TEC().reason("Workload %s failed on %s - %s" % (b, g.name, str(e)))
            if checked:
                xenrt.TEC().logverbose("Checked workloads")
            else:
                xenrt.TEC().logverbose("All workloads died")
                break

        if len(self.failed) > 0:
            raise xenrt.XRTFailure("Workloads %s failed" % (",".join(self.failed)))

    def postRun(self):
        for b in self.benchmarks:
            for g in self.guests:
                self.benchmarkObjects[b][g.name].stopWorkload()


class _VGPUOwnedVMsTest(VGPUTest):
    __OPTIONS = {
                     VGPUOS.Win7x64 :  "win7sp1-x64",
                     VGPUOS.Win7x86 :  "win7sp1-x86",
                     VGPUOS.WS2008R2 : "ws08r2sp1-x64",
                     VGPUOS.Win8x86 : "win8-x86",
                     VGPUOS.Win8x64 : "win8-x64",
                     VGPUOS.Win81x86 : "win81-x86",
                     VGPUOS.Win81x64 : "win81-x64",
                     VGPUOS.WS12x64 : "ws12-x64",
                     VGPUOS.WS12R2x64 : "ws12r2-x64",
                     VGPUOS.DEBIAN : "debian",
                     VGPUOS.Centos7 : "centos7_x86-64",
                     VGPUOS.Rhel7 : "rhel7_x86-64",
                     VGPUOS.Oel7 : "oel7_x86-64",
                     VGPUOS.Ubuntu1404x86 : "ubuntu1404_x86-32",
                     VGPUOS.Ubuntu1404x64 : "ubuntu1404_x86-64"
                }

    __GUEST_MEMORY_MB = 2048
    CAPACITY_THROTTLE = 0
    VM_START = VMStartMethod.OneByOne

    """ Snapshot names for each host"""
    SNAPSHOT_PREVGPU = "preVGPU"
    SNAPSHOT_PRE_VNC_DISABLED = "preVNCDisabled"
    SNAPSHOT_PRE_GUEST_DRIVERS = "preGuestDriversInstalled"
    SNAPSHOT_POST_GUEST_DRIVERS = "postGuestDriversInstalled"

    def __init__(self, requiredEnvironmentList, configuration, distribution, vncEnabled, fillToCapacity):
        super(_VGPUOwnedVMsTest, self).__init__()
        self._requiredEnvironments = requiredEnvironmentList
        self._distribution = distribution
        self.__vncEnabled = vncEnabled
        self._guestsAndTypes = []
        self._configuration = configuration
        self._vGPUCreator = None
        self.__fillToCapacity = fillToCapacity

    def guestAndTypesStatus(self):
        """ For debugging"""
        strings = []
        for guest, os in self._guestsAndTypes:
            strings.append("Host: %s; OS: %s; Power State: %s" %(str(guest), self.getOSType(os), guest.getState()))
        strings.append("Total guests and types: %d" % len(self._guestsAndTypes))
        return strings

    def getOSType(self, vgpuos):
        if not vgpuos in self.__OPTIONS:
            raise xenrt.XRTFailure("This OS is not supported by the vGPU test")
        return self.__OPTIONS[vgpuos]

    def getConfigurationName(self, configuration):
        if not configuration in self._CONFIGURATION:
            raise xenrt.XRTError("Unexpected configuration number: %s" % configuration)
        return self._CONFIGURATION[configuration]

    def __masterVmName(self, requiredOS):
        os = self.getOSType(requiredOS)
        return "master" + str(os)

    def masterGuest(self, requiredOS, host):
        return host.guests[self.__masterVmName(requiredOS)]

    def _createGuests(self, host, requiredOS):
        masterKey = self.__masterVmName(requiredOS)
        guest = None

        guestVMs = self.host.minimalList("vm-list", params="name-label")

        if masterKey in guestVMs:
            log("VM found so cloning...")
            master = host.guests[masterKey]
            if master.getState() != "DOWN":
                master.shutdown()
            guest = master.cloneVM()
        else:
            log("No matching VM found, so create a new one....")
            guest = host.createGenericWindowsGuest(distro=self.getOSType(requiredOS), memory=self.__GUEST_MEMORY_MB, name=masterKey)

        #self.uninstallOnCleanup(guest)
        self.getLogsFrom(guest)
        return guest

    def configureVGPU(self, guest):
        self._vGPUCreator.createOnGuest(guest)

    def randomGuestFromSelection(self, requiredNumber):
        """
        Create a list of guests to install, randomly selected from the provided environment list
        """
        log("Create a random list of %d hosts from the selection %s" %(requiredNumber, self._requiredEnvironments))
        newEnvironmentList = [random.choice(list(set(self._requiredEnvironments))) for x in range(requiredNumber)]
        log("Selected the following from the provided selection: %s" % str(newEnvironmentList))
        return newEnvironmentList

    def bindConfigurationToPGPU(self, conf, count = 1):
        typeuuid = None
        for confname, uuid in self.host.getSupportedVGPUTypes().items():
            if conf.lower() in confname.lower():
                typeuuid = uuid
                break;
        if not typeuuid:
            raise xenrt.XRTError("configuration %s is not supported. (supported: %s)" % (conf, self.host.getSupportedVGPUTypes()))

        pgpulist = []
        ggman = GPUGroupManager(self.host)
        for pgpu in ggman.getPGPUUuids():
            if count < 1:
                break
            supportedTypes = self.host.genParamGet('pgpu', pgpu, 'supported-VGPU-types').replace(" ", "").split(';')
            if typeuuid in supportedTypes:
                self.host.genParamSet('pgpu', pgpu, 'enabled-VGPU-types', typeuuid)
                pgpulist.append(pgpu)
                count -= 1

        return pgpulist

    def releaseConfiguration(self, list):
        for pgpu in list:
            supportedTypes = self.host.genParamGet('pgpu',pgpu,'supported-VGPU-types').replace(";", ",").replace(" ", "")
            self.host.genParamSet('pgpu', pgpu, 'enabled-VGPU-types', supportedTypes)

    def getConfiguration(self, vm):
        vgpu = self.host.parseListForUUID("vgpu-list", "vm-uuid", vm.uuid)
        if vgpu and vgpu != "":
            return self.host.parseListForUUID("vgpu-list", "vm-uuid", vm.uuid, "params=type-uuid")
        else:
            return None

    def safeRestartGuest(self, guest, retry=3):
        self.safeStartGuest(guest, retry, True)

    def safeStartGuest(self, guest, retry=3, reboot=False):
        # A work-around for windows autologin failure.
        lasterror = None
        while retry:
            retry -= 1
            try:
                guest.start(specifyOn = False, reboot = reboot)
                return
            except xenrt.XRTException as e:
                if e.reason.startswith("Windows failed to autologon") or \
                    e.reason.startswith("Domain running but not reachable by XML-RPC"):
                    log("Windows started but failed to autologin. Retrying... (%d)" % (retry,))
                    lasterror = e
                else:
                    raise e
            reboot = True

        if lasterror:
            raise lasterror

    def startVM(self, vm):
        if vm.getState() != "UP":
            self.safeStartGuest(vm)
        #self.assertGPURunningInVM(vm, self.vendor)

    def _removeGuest(self, vm):
        host = vm.host
        host.removeGuest(vm)
        if vm.getState() != "DOWN":
            vm.shutdown()
        vm.uninstall()

    def startAllVMs(self, vmlist = None):
        if not vmlist:
            vmlist = [guest for guest, ostype in self._guestsAndTypes]
        if self.VM_START == VMStartMethod.OneByOne:
            for (vm) in vmlist:
                self.startVM(vm)
        else:
            pStart = [xenrt.PTask(self.startVM, vm) for vm in vmlist]
            xenrt.pfarm(pStart)

    def bootstormStartVM(self, vm):
        try:
            name = vm.getName()
            name = name.replace(" ", "\ ")
            cmd = "xe vm-start vm=%s" % name
            self.runAsync(self.host, cmd, timeout=3600, ignoreSSHErrors=False)
        except Exception, e:
            raise xenrt.XRTFailure("Failed to start vm %s - %s" % (vm.getName(), str(e)))

    def rebootAllVMs(self, vmlist = None):

        if not vmlist:
            vmlist = [guest for guest, ostype in self._guestsAndTypes]

        # Shutdown all the VMs
        for vm in vmlist:
            vm.shutdown()

        # Start all the VMs in chunks
        chunk = 25
        count = len(vmlist)/chunk

        for i in range(count+1):
            pt = [xenrt.PTask(self.bootstormStartVM, vm) for vm in vmlist[i*chunk:i*chunk+chunk]]
            xenrt.pfarm(pt)

        # WaitforDaemon for all VMs
        pt = [xenrt.PTask(vm.waitForDaemon, 1800) for vm in vmlist]
        xenrt.pfarm(pt)

    def prepare(self, arglist):
        self.nfs = xenrt.ExternalNFSShare()
        self.host = self.getDefaultHost()

        step("Install host drivers")
        self.installNvidiaHostDrivers()

        self._vGPUCreator = VGPUInstaller(self.host, self._configuration, self._distribution)

        if self.__fillToCapacity:
            step("Filling vGPUs to capacity")
            capacity = self.host.remainingGpuCapacity(self._vGPUCreator.groupUUID(), self._vGPUCreator.typeUUID())
            if self.CAPACITY_THROTTLE > 0 and capacity > self.CAPACITY_THROTTLE:
                step("Capacity throttle in place. Limiting capacity to %d" % self.CAPACITY_THROTTLE)
                capacity = self.CAPACITY_THROTTLE

            self._requiredEnvironments = self.randomGuestFromSelection(capacity)

        step("Create Master guests")
        guest = self._createGuests(self.host, self._requiredEnvironments[0])
        #guest.snapshot(self.SNAPSHOT_PRE_VNC_DISABLED)
        step("Set VNC enabled to %s" % str(self.__vncEnabled))
        guest.setVGPUVNCActive(self.__vncEnabled)
        #guest.snapshot(self.SNAPSHOT_PREVGPU)
        step("Configure vGPU")
        self.configureVGPU(guest)
        xenrt.sleep(10) # Give some time to settle vGPU down.
        if (guest.getState() != "UP"):
            guest.start()
        #guest.snapshot(self.SNAPSHOT_PRE_GUEST_DRIVERS)
        step("Install guest drivers for %s" % str(guest))
        self.installNvidiaWindowsDrivers(guest)
        #guest.snapshot(self.SNAPSHOT_POST_GUEST_DRIVERS)
        self._guestsAndTypes.append((guest, self._requiredEnvironments[0]))

        step("Create %d required guests" % len(self._requiredEnvironments))
        for i, requiredEnv in enumerate(self._requiredEnvironments):
            if i == 0 :
                continue
            guest = self._createGuests(self.host, requiredEnv)
            self._guestsAndTypes.append((guest, requiredEnv))


        log("Created guests: %s" % str(self._guestsAndTypes))

        step("Starting up any powered-down guests")
        self.startAllVMs([g for (g, os) in self._guestsAndTypes if g.getState() == "DOWN"])

    def postRun(self):

        #return

        for guest, osType in self._guestsAndTypes:
            step("Shutting down guest %s" % str(guest))
            try: guest.shutdown()
            except: pass

            step("Uninstalling guest %s" % str(guest))
            try:
                host = copy.copy(guest.host)
                host.removeGuest(guest)
                guest.uninstall()
            except:
                pass

        #if self.nfs:
            #try:
                #self.nfs.release()
            #except:
                #pass

        step("Destroy vGPUs")
        self.host.destroyAllvGPUs()
        step("Clearing locals")
        self._guestsAndTypes = None
        self._requiredEnvironments = None

class _VGPUBenchmarkTest(_VGPUOwnedVMsTest):
    __TIMEOUT_SECS = 1800
    __SLEEP_SECS = 10
    __GRAPHICS_SCORE_KEY = "GraphicsScore"
    __GAMING_SCORE_KEY = "GamingScore"

    def __init__(self, requiredEnvironmentList, configuration, distribution = VGPUDistribution.DepthFirst, vncEnabled = False, fillToCapacity = False):
        super(_VGPUBenchmarkTest, self).__init__(requiredEnvironmentList, configuration, distribution, vncEnabled, fillToCapacity)

    def __fetchBenchmark(self, osType, config):
        return VGPUBenchmark(osType, config)

    def __runForGuest(self, guest):
        step("Installing workload for %s" % str(guest))
        workload = workloads.WindowsExperienceIndex(guest)
        workload.install(False)

        now = time.time()
        theFuture = now + self.__TIMEOUT_SECS

        step("Starting workload for %s" % str(guest))
        workload.start()
        workloadResult = workload.check()
        futureHasArrived = self.__areWeInTheFutureYet(theFuture)

        log("Starting poll with %d sec timeout with a %d sec sleep cycle" % (self.__TIMEOUT_SECS, self.__SLEEP_SECS))
        log("Start time: %s" % str(now))
        log("Expected finish time: %s" % str(theFuture))

        while(not futureHasArrived):
            xenrt.sleep(self.__SLEEP_SECS)
            workloadResult = workload.check()
            log("Benchmark result: %s" % str(workloadResult))
            if(workloadResult != None):
                break
            futureHasArrived = self.__areWeInTheFutureYet(theFuture)
            log("Future arrived: %s" % str(futureHasArrived))

        step("Stopping workload for %s" % str(guest))

        if workloadResult == None and futureHasArrived:
            raise xenrt.XRTFailure("Workload timed out")

        if workloadResult == None:
            raise xenrt.XRTFailure("No workload data was found for %s" % str(guest))

        log("Workload result: %s" % str(workloadResult))
        return workloadResult

    def _checkBenchmark(self, measuredValue, benchmarkValue, key):

        step("Checking benchmark for %s" % key)

        score = 0
        if(key == self.__GAMING_SCORE_KEY):
            score = benchmarkValue.gamingScoreMinimum()
        elif(key == self.__GRAPHICS_SCORE_KEY):
            score = benchmarkValue.graphicsScoreMinimum()
        else:
            warning("Could not find required key: %s in measured benchmark" % key)

        log("Benchmark score is: %s" % str(score))
        log("Measured values are: %s" % str(measuredValue))

        if len(measuredValue) < 1:
            raise xenrt.XRTFailure("No measured values were given")

        step("Checking measured score against benchmark score")
        for listKey, listScore in measuredValue:
            if listKey == key:
                log("Measured workload score is: %s" % str(listScore))
                if listScore < score:
                    raise xenrt.XRTFailure("%s %s failed to meet benchmark minimum of %s" % (key, str(measuredValue[key]), str(score)))

    def __areWeInTheFutureYet(self, theFuture):
        return time.time() > theFuture

    def run(self, arglist):
        for guest, osType in self._guestsAndTypes:
            benchmark = self.__fetchBenchmark(osType, self._configuration)
            workloadResult = self.__runForGuest(guest)
            self.runSubcase("_checkBenchmark", (workloadResult, benchmark, self.__GAMING_SCORE_KEY), self.__GAMING_SCORE_KEY, "Score beats benchmark")
            self.runSubcase("_checkBenchmark", (workloadResult, benchmark, self.__GRAPHICS_SCORE_KEY), self.__GRAPHICS_SCORE_KEY, "Score beats benchmark")

class _VGPUStressTest(_VGPUBenchmarkTest):
    __THREE_DAYS_SECS = 60 * 60 * 24 * 3
    __SLEEP = 60 * 30 #30 mins

    def __init__(self, requiredEnvironmentList, configuration):
        super(_VGPUStressTest, self).__init__(requiredEnvironmentList, configuration, VGPUDistribution.DepthFirst, False, False)

    def __setupWorkloadsForGuest(self):
        runningWorkloads = []
        for guest, osType in self._guestsAndTypes:
            step("Creating workload for %s" % str(guest))
            currentWorkload = workloads.BurnintestGraphics(guest)
            currentWorkload.install(False)
            step("Starting workload for %s" % str(guest))
            currentWorkload.start()
            runningWorkloads.append(currentWorkload)
        return runningWorkloads

    def run(self, arglist):

        step("Run the WEI measurement before starting the stress test")
        super(_VGPUStressTest, self).run(arglist)

        step("Setup stress test workloads")
        workloads = self.__setupWorkloadsForGuest()

        now = time.time()
        end = now + self.__THREE_DAYS_SECS

        while time.time() < end:
            xenrt.sleep(self.__SLEEP)
            self.host.checkHealth()
            [guest.checkHealth() for guest, osType in self._guestsAndTypes]

        step("Stopping workloads")
        map(lambda wl: wl.stop(), workloads)

        step("Run the WEI measurement after stopping the stress test")
        super(_VGPUStressTest, self).run(arglist)

class _VGPUScalabilityTest(_VGPUBenchmarkTest):
    __ONE_DAY_SECS = 60 * 60
    __PAUSE_BETWEEN_REBOOTS_SECS = 60
    CAPACITY_THROTTLE = 0

    def __init__(self, requiredEnvironmentList, configuration, bootstorm):
        self.__bootstorm = bootstorm
        super(_VGPUScalabilityTest, self).__init__(requiredEnvironmentList, configuration, fillToCapacity = True)

    def _measureMetric(self):
        [guest.shutdown() for guest, ostype in self._guestsAndTypes]
        log(self.host.execdom0("cat /proc/meminfo"))

    def run(self, arglist):
        now = time.time()
        end = now + self.__ONE_DAY_SECS

        step("Shutting down all VMs and getting the /proc/meminfo")
        self._measureMetric()

        step("Starting up all VMs")
        self.startAllVMs()

        step("Reboot all hosts repeatedly for %d secs" % self.__ONE_DAY_SECS)
        while time.time() < end:
            self._runWorkload(arglist)
            if self.__bootstorm:
                log("Reboot as bootstorm")
                self.rebootAllVMs()
            else:
                log("Reboot in serial")
                [g.reboot() for g, t in self._guestsAndTypes]

            xenrt.sleep(self.__PAUSE_BETWEEN_REBOOTS_SECS)

        step("End of the test: Shutting down all VMs and getting the /proc/meminfo")
        self._measureMetric()

    def _runWorkload(self, arglist):
        super(_VGPUScalabilityTest, self).run(arglist)


"""
Single Benchmark - used to determine the benchmarking values
Not required to be run as part of a suite
"""
class SingleBenchmark(_VGPUBenchmarkTest):
    def __init__(self):
        super(SingleBenchmark, self).__init__([VGPUOS.WS2008R2], VGPUConfig.K260)

"""
Benchmarking Test Matrix
"""
class VGPUWin7x86K100(_VGPUBenchmarkTest):
    def __init__(self):
        super(VGPUWin7x86K100, self).__init__([VGPUOS.Win7x86, VGPUOS.Win7x86], VGPUConfig.K100)

class VGPUWin7x64K140(_VGPUBenchmarkTest):
    def __init__(self):
        super(VGPUWin7x64K140, self).__init__([VGPUOS.Win7x64, VGPUOS.Win7x64], VGPUConfig.K140)

class VGPUWin7x64K200(_VGPUBenchmarkTest):
    def __init__(self):
        super(VGPUWin7x64K200, self).__init__([VGPUOS.Win7x64, VGPUOS.Win7x64], VGPUConfig.K200)

class VGPUWin7x86K240(_VGPUBenchmarkTest):
    def __init__(self):
        super(VGPUWin7x86K240, self).__init__([VGPUOS.Win7x86, VGPUOS.Win7x86], VGPUConfig.K240)

class VGPUWS2k8x64K260(_VGPUBenchmarkTest):
    def __init__(self):
        super(VGPUWS2k8x64K260, self).__init__([VGPUOS.WS2008R2, VGPUOS.WS2008R2], VGPUConfig.K260)

class VGPUWin7x86K100VNC(_VGPUBenchmarkTest):
    def __init__(self):
        super(VGPUWin7x86K100VNC, self).__init__([VGPUOS.Win7x86, VGPUOS.Win7x86], VGPUConfig.K100, vncEnabled=True)

class VGPUWin7x64K200VNC(_VGPUBenchmarkTest):
    def __init__(self):
        super(VGPUWin7x64K200VNC, self).__init__([VGPUOS.Win7x64, VGPUOS.Win7x64], VGPUConfig.K200, vncEnabled=True)

class VGPUWin7x64K140BreadthFirst(_VGPUBenchmarkTest):
    def __init__(self):
        super(VGPUWin7x64K140BreadthFirst, self).__init__([VGPUOS.Win7x64, VGPUOS.Win7x64], VGPUConfig.K140, VGPUDistribution.BreadthFirst)

class VGPUWin7x86K240BreadthFirst(_VGPUBenchmarkTest):
    def __init__(self):
        super(VGPUWin7x86K240BreadthFirst, self).__init__([VGPUOS.Win7x86, VGPUOS.Win7x86], VGPUConfig.K240, VGPUDistribution.BreadthFirst)

class VGPUWin7x64K1PT(_VGPUBenchmarkTest):
    def __init__(self):
        super(VGPUWin7x64K1PT, self).__init__([VGPUOS.Win7x86], VGPUConfig.K1PassThrough)

class VGPUWin7x86K2PT(_VGPUBenchmarkTest):
    def __init__(self):
        super(VGPUWin7x86K2PT, self).__init__([VGPUOS.Win7x64], VGPUConfig.K2PassThrough)

"""
Scalability test matrix
"""
class ScalabilityVGPUWin7x86K100(_VGPUScalabilityTest):
    def __init__(self):
        super(ScalabilityVGPUWin7x86K100, self).__init__([VGPUOS.Win7x86], VGPUConfig.K100, False)

class ScalabilityVGPUWin7x64K200(_VGPUScalabilityTest):
    def __init__(self):
        super(ScalabilityVGPUWin7x64K200, self).__init__([VGPUOS.Win7x64], VGPUConfig.K200, False)

class ScalabilityVGPUWin7x86K100BS(_VGPUScalabilityTest):
    def __init__(self):
        super(ScalabilityVGPUWin7x86K100BS, self).__init__([VGPUOS.Win7x86], VGPUConfig.K100, True)

class ScalabilityVGPUWin7x64K200BS(_VGPUScalabilityTest):
    def __init__(self):
        super(ScalabilityVGPUWin7x64K200BS, self).__init__([VGPUOS.Win7x64], VGPUConfig.K200, True)

"""
Stress test matrix
"""
class StressvGPUK140(_VGPUStressTest):
    def __init__(self):
        oses = [VGPUOS.Win7x86 for x in range(14)]
        super(StressvGPUK140, self).__init__(oses, VGPUConfig.K140)

class StressvGPUK240(_VGPUStressTest):
    def __init__(self):
        oses = [VGPUOS.Win7x64 for x in range(8)]
        super(StressvGPUK240, self).__init__(oses, VGPUConfig.K240)


"""
VGPU Allocation mode Test cases.
"""

class VGPUAllocationModeBase(_VGPUOwnedVMsTest):
    """
    vGPU Allocation Mode tests.
    """

    POOL = [["K2", "K2"]]
    SR_TYPE = SRType.NFS
    REQUIRED_DISTROS = [VGPUOS.Win7x86, VGPUOS.Win7x64]
    VGPU_CONFIG = [VGPUConfig.K200]
    VGPU_DISTRIBUTION = [VGPUDistribution.DepthFirst]
    INSTALL_GUEST_DRIVER = False
    TEST_VARIANTS = [
        # initial status
        {
            "VMs" : {VGPUConfig.K200: 9},
            "Result" : [8, 1, 0, 0],
        },
        # Fisrt phase
        {
            "VMs" : {VGPUConfig.K200: 3},
            "Result" : [8, 2, 1, 1],
            "Distribution" : VGPUDistribution.BreadthFirst,
        },
        # Sencond Phase
        {
            "VMs" : {VGPUConfig.K200: 1},
            "Result" : [8, 3, 1, 1],
        }
    ]

    def __init__(self):
        super(VGPUAllocationModeBase, self).__init__(requiredEnvironmentList = self.REQUIRED_DISTROS, configuration = self.VGPU_CONFIG, distribution = self.VGPU_DISTRIBUTION, vncEnabled = False, fillToCapacity = False)
        self.gpuGroupManager = None

    def getVGPUList(self, pgpuuuid):
        return self.host.minimalList("pgpu-list", "resident-VGPUs", "uuid=%s" % (pgpuuuid,))

    def setDistributionMode(self, distribution):

        self._distribution = distribution
        for config, creator in self.vGPUCreator.items():
            groupUUID = creator.groupUUID()

            log("Set vGPU distibution mode of %s group %s configuration to %d." % (groupUUID, creator, distribution))
            if distribution == VGPUDistribution.DepthFirst:
                self.host.setDepthFirstAllocationType(groupUUID)
            else:
                self.host.setBreadthFirstAllocationType(groupUUID)

    def configureVGPU(self, config, guest, groupuuid = None):
        log("Creating %s config vgpu on %s" % (config, guest.getName()))
        self.vGPUCreator[config].createOnGuest(guest, groupuuid)

    def cloneVM(self, env, getlog=False):
        log("Cloning %s vm." % (env,))
        vm = self.masterVMs[env].cloneVM()
        self.uninstallOnCleanup(vm)
        if getlog:
            self.getLogsFrom(vm)

        return vm

    def shutdownGuest(self, configuration, count = 1):
        shdVMs = 0
        for i in range(count):
            for vm, ostype in self._guestsAndTypes:
                if self.getConfiguration(vm) == configuration.typeUUID() and vm.getState() == "UP":
                    vm.shutdown()
                    shdVMs += 1
                    break
        log("Shutdown %d VMs of %s configuration. Requesed: %d" % (shdVMs, str(configuration), count))
        return shdVMs

    def setOneCardPerHost(self):
        for host in self.getAllHosts():
            if not host:
                continue
            ggman = GPUGroupManager(host)
            pgpus = host.minimalList("pgpu-list", "", "host-uuid=%s" % (host.uuid,))
            k1list = []
            k2list = []
            for pgpu in pgpus:
                if ggman.isIsolated(pgpu):
                    continue
                device = host.genParamGet("pgpu", pgpu, "device-name")
                if "GRID K1" in device:
                    k1list.append(pgpu)
                elif "GRID K2" in device:
                    k2list.append(pgpu)
            while len(k1list) > NumOfPGPUPerCard[CardType.K1]:
                pgpu = k1list.pop()
                ggman.isolatePGPU(pgpu)
            while len(k2list) > NumOfPGPUPerCard[CardType.K2]:
                pgpu = k2list.pop()
                ggman.isolatePGPU(pgpu)

    def runTestPhase(self, variant):

        log("Running tests with variant: %s" % (variant,))
        expectError = False
        if "ExpectError" in variant:
            expectError = variant["ExpectError"]

        if "VMStart" in variant:
            self.VM_START = variant["VMStart"]

        log("Setting up %d guests" % len(self._requiredEnvironments))
        vmdict = variant["VMs"]
        envlist = self.randomGuestFromSelection(sum(vmdict.values()))
        vmlist = []
        for env in envlist:
            log("Create a %s guest" % self.getOSType(env))
            vm = self.cloneVM(self.getOSType(env))
            vmlist.append((vm, env))

        self._guestsAndTypes = self._guestsAndTypes + vmlist

        step("Configuring vGPUs onto each guests.")
        vmnum = 0
        for (config, count) in vmdict.items():
            if config == None:
                vmnum += count
                continue
            for i in range(count):
                self.configureVGPU(config, vmlist[vmnum][0])
                vmnum += 1

        if "Distribution" in variant:
            self.setDistributionMode(variant["Distribution"])
        else:
            self.setDistributionMode(VGPUDistribution.DepthFirst)

        try:
            self.startAllVMs(dict(vmlist).keys())

        except xenrt.XRTException as e:
            log("Failed to start VM due to: %s (%s)" % (e.reason, e.data))
            if expectError:
                log("Failed to start VMs as expected.")
            else:
                raise xenrt.XRTFailure("Failed to start VMs.")

        else:
            if expectError:
                raise xenrt.XRTFailure("Succeeded to start VMs")
            else:
                log("Succeeded to start VMs")

        if "Result" in variant:
            ggman = GPUGroupManager(self.host)
            expectedLayout = variant["Result"]
            pgpulist = GPUGroupManager(self.host).getPGPUUuids()
            if len(expectedLayout) != len(pgpulist):
                raise xenrt.XRTFailure("Number of GPU Groups is different from expected result. (Expected: %d / Found: %d)" % (len(expectedLayout), len(pgpulist)))
            if sorted(expectedLayout) != sorted([len(self.getVGPUList(pgpu)) for pgpu in pgpulist]):
                raise xenrt.XRTFailure("Numbers of VGPUs per each PGPUs are not as expected. (Expected %s / Found: %s)" % (sorted(expectedLayout), sorted([len(self.getVGPUList(pgpu)) for pgpu in pgpulist])))

    def createMaster(self, ostype):

        if ostype in self.masterVMs:
            log("Found %s master VM from MasterVMs list." % (ostype,))
            return self.masterVMs[ostype]

        vmname = "master" + str(ostype)

        candidate = None
        guestVMs = self.host.minimalList("vm-list", None, args="name-label=%s" % (vmname,))
        for guestuuid in guestVMs:
            guest = self.host.guestFactory()(name=vmname, host=self.host)
            guest.uuid = guestuuid
            guest.distro = ostype
            if ostype.startswith("win") or ostype.startswith("ws"):
                guest.windows = True
            # Get the new VIFs:
            guest.vifs = [ (nic, vbridge, mac, ip) for \
                       (nic, (mac, ip, vbridge)) in guest.getVIFs().items() ]
            guest.vifs.sort()
            # Default IP to the first one we find unless g has managebridge or
            # managenetwork defined.
            vifs = ((guest.managenetwork or guest.managebridge)
                and guest.getVIFs(network=guest.managenetwork, bridge=guest.managebridge).keys()
                or guest.vifs)

            ips = filter(None, map(lambda (nic, vbridge, mac, ip):ip, vifs))
            if ips:
                guest.mainip = ips[0]
            vifs.sort()
            if guest.use_ipv6 and vifs:
                guest.mainip = guest.getIPv6AutoConfAddress(device=vifs[0][0])
            elif guest.mainip:
                if re.match("169\.254\..*", guest.mainip):
                    raise xenrt.XRTFailure("VM gave itself a link-local address.")

            guest.setHostnameViaXenstore()

            candidate = guest

            listvdiuuid = guest.getHost().minimalList("vbd-list", "vdi-uuid", "device=hda vm-uuid=%s" % (guest.getUUID(),))
            if not listvdiuuid:
                listvdiuuid = guest.getHost().minimalList("vbd-list", "vdi-uuid", "device=xvda vm-uuid=%s" % (guest.getUUID(),))

            if listvdiuuid:
                vdiuuid = listvdiuuid[0]
            else:
                raise xenrt.XRTFailure("wrong device id given")

            sruuid = guest.getHost().genParamGet("vdi", vdiuuid, "sr-uuid")
            if sruuid == self.sr:
                log("Found pre created VM %s. Adding it to MasterVMs list." % (vmname,))
                self.masterVMs[ostype] = guest
                return guest

        if candidate:
            newmaster = candidate.copyVM(name=candidate.getName(), sruuid=self.sr)
            self.masterVMs[ostype] = newmaster
            log("Found pre created VM %s on different SR. Adding it to MasterVMs list." % (vmname,))
            return newmaster

        sr = None
        if self.sr:
            sr = self.sr

        if ostype == "debian" :
            guest = self.host.createGenericLinuxGuest(start=False)
        elif ostype.startswith("win") or ostype.startswith("ws"):
            guest = self.host.createGenericWindowsGuest(distro=ostype, memory=2048, name=vmname, drivers=True, start=True, sr=sr)
            guest.preCloneTailor()
            guest.xenDesktopTailor()
            self.safeRestartGuest(guest)
            xenrt.sleep(120)
            guest.shutdown()
            xenrt.sleep(30)
        else: 
            if "x86-64" in ostype:
                arch = "x86-64"
            else: 
                arch = "x86-32"

            distro = string.split(ostype, "_")[0]
            guest = self.host.createBasicGuest(name=vmname, distro=distro, arch=arch, sr=sr, vcpus=1)
            guest.preCloneTailor()
            xenrt.sleep(120)
            guest.shutdown()
            xenrt.sleep(30)
         
        self.masterVMs[ostype] = guest
        #self.uninstallOnCleanup(guest)

        return guest

    def preparePool(self):

        # if POOL is None, it means it uses existing set-up.
        if not self.POOL:
            self.pools = [self.getDefaultPool()]
            return

        hosts = sorted(list(set(self.getAllHosts())))

        cards = {}
        for host in hosts:
            if not host:
                continue
            pgpus = host.minimalList("pgpu-list", "", "host-uuid=%s" % (host.uuid,))
            k1 = k2 = 0
            for pgpu in pgpus:
                device = host.genParamGet("pgpu", pgpu, "device-name")
                if "GRID K1" in device:
                    k1 += 1
                elif "GRID K2" in device:
                    k2 += 1
            if k1 % NumOfPGPUPerCard[CardType.K1] or k2 % NumOfPGPUPerCard[CardType.K2]:
                raise xenrt.XRTError("Number of PGPU does not match with cards description. found %d K1 PGPU(s) and %d K2 PGPU(s)" % (k1, k2))
            cards[host] = {"K1" : k1 / NumOfPGPUPerCard[CardType.K1], "K2" : k2 / NumOfPGPUPerCard[CardType.K2]}
            log("Found a host with " + str(cards[host]))

        self.hosts = []
        for pool in self.POOL:
            hs = []
            for req in pool:
                for host in hosts:
                    if not host:
                        continue
                    carddict = cards[host]
                    if req == "" and carddict["K1"] == 0 and carddict["K2"] == 0:
                        hosts.remove(host)
                        self.hosts.append(host)
                        hs.append(host)
                        break
                    elif req in carddict and carddict[req] > 0:
                        hosts.remove(host)
                        self.hosts.append(host)
                        hs.append(host)
                        break
            if len(hs) != len(pool):
                message = "["
                for host in hs:
                    message = message + str(cards[host])
                message = message + "] found."
                raise xenrt.XRTError("Not enough vGPU capable hosts. " + message)

            hs[0].pool = xenrt.lib.xenserver.poolFactory(xenrt.TEC().lookup("PRODUCT_VERSION", None))(hs[0])

            for i in range(1, len(hs)):
                for sruuid in hs[i].minimalList("sr-list", "uuid", "shared=true"):
                    try:
                        hs[i].forgetSR(sruuid)
                    except:
                        pass
                hs[0].pool.addHost(slave=hs[i], force=True)

            log("Sleep for a while to give the slave(s) restart toolstack.")
            xenrt.sleep(30)

            self.pools.append(hs[0].pool)

    def prepareGPUGroups(self):

        log("Restore gpu groups to initial status.")
        if self.pools and self.pools[0] and self.pools[0].master:
            host = self.pools[0].master
        elif self.getDefaultPool() and self.getDefaultPool().master:
            host = self.getDefaultPool().master
        elif self.host:
            host = self.host
        else:
            host = self.getDefaultHost()
        ggman = GPUGroupManager(host)
        ggman.reinitialize()

        xenrt.sleep(30)

    def prepareSR(self):

        # If SR_TYPE is not defined use existing env.
        if self.SR_TYPE == None:
            self.sr = self.getDefaultHost().lookupDefaultSR()
            log("Default SR %s is seletected." % (self.sr,))
            return

        if self.pools and self.pools[0] and self.pools[0].master:
            host = self.pools[0].master
        elif self.hosts and self.hosts[0]:
            host = self.hosts[0]
        else:
            host = self.getDefaultHost()
        self.host = host

        if self.SR_TYPE == SRType.Local:
            self.sr = host.getSRs(type="lvm", local=True)[0]

        else:
            # find existing NFS
            srs = host.getSRs(type="nfs", local=False)
            # if there is not, create one.
            if len(srs) == 0:
                nfs = xenrt.resources.NFSDirectory()
                nfsdir = xenrt.command("mktemp -d %s/nfsXXXX" % (nfs.path()), strip = True)
                nfssr = xenrt.lib.xenserver.NFSStorageRepository(host, "nfssr")
                server, path = nfs.getHostAndPath(os.path.basename(nfsdir))
                nfssr.create(server, path)
                self.sr = nfssr.uuid
            else:
                self.sr = srs[0]
        #host.genParamSet("pool", self.pools[0].getUUID(), "default-SR", self.sr)

    def prepare(self, arglist):

        self.host = self.getDefaultHost()
        step("Install host drivers")
        self.installNvidiaHostDrivers()
        self.pools = []
        self.preparePool()
        self.prepareGPUGroups()
        self.prepareSR()
        self.setOneCardPerHost()

        step("Creating %d vGPUs configurations." % (len(self.VGPU_CONFIG),))
        self.vGPUCreator = {}
        for config in self.VGPU_CONFIG:
            self.vGPUCreator[config] = VGPUInstaller(self.host, config, self._distribution)

        step("Creating a Gold VM")
        self.masterVMs = {}
        for distro in self.REQUIRED_DISTROS:
            vm = self.createMaster(self.getOSType(distro))

    def run(self, arglist):

        phase = 0
        for variant in self.TEST_VARIANTS:
            log("Running Phase: %d" % (phase,))
            self.runTestPhase(variant)

    def postRun(self):
        log("Destroying all guests.")
        for guest, ostype in self._guestsAndTypes:
            try:
                guest.setState("DOWN")
                guest.uninstall()
            except:
                pass

        xenrt.sleep(30)
        if self.pools and self.POOL:
            log("Removing slave from the pool.")
            for pool in self.pools:
                for slave in pool.getSlaves():
                    pool.eject(slave)

class FunctionalBase(VGPUAllocationModeBase):

    REQUIRED_DISTROS = []
    VGPU_CONFIG = []
    TYPE_OF_VGPU = None

    def prepare(self,arglist):

        self.guests = {}
        self.masterVMs = {}
        self.masterVMsSnapshot = {}
        self.host = self.getDefaultHost()
        self.pools =[]

        self.parseArgs(arglist)

        self.typeOfvGPU = self.typeOfvGPU()

        step("Install host drivers")
        self.typeOfvGPU.installHostDrivers()

        self.sr = self.host.getSRs(type="lvm", local=True)[0]
        self.prepareGPUGroups()

    def typeOfvGPU(self):

        if not self.TYPE_OF_VGPU:
            raise xenrt.XRTFailure("Type of vGPU not defined")

        if self.TYPE_OF_VGPU == self.getDiffvGPUName(DiffvGPUType.NvidiaWinvGPU):
            return NvidiaWindowsvGPU() 
        if self.TYPE_OF_VGPU == self.getDiffvGPUName(DiffvGPUType.NvidiaLinuxvGPU):
            return NvidiaLinuxvGPU()
        if self.TYPE_OF_VGPU == self.getDiffvGPUName(DiffvGPUType.IntelWinvGPU):
            return IntelWindowsvGPU()

    def parseArgs(self,arglist):

        for arg in arglist:
            if arg.startswith('distro'):
                self.REQUIRED_DISTROS = map(int,arg.split('=')[1].split(','))
            if arg.startswith('vgpuconfig'):
                self.VGPU_CONFIG = map(int,arg.split('=')[1].split(','))
            if arg.startswith('typeofvgpu'):
                self.TYPE_OF_VGPU = map(str,arg.split('=')[1].split(','))[0]
 
    def run(self,arglist):

        for config in self.VGPU_CONFIG:

            for distro in self.REQUIRED_DISTROS:

                self.insideRun(config,distro)

            self.guests = {}

            for distro in self.REQUIRED_DISTROS:

                osType = self.getOSType(distro)

                vm = self.masterVMs[osType]

                vm.setState("UP")
                vm.revert(self.masterVMsSnapshot[osType])

    def insideRun(self,config,distro):

        log("Not Implemented")
        raise xenrt.XRTError("Function not yet implemented")

    def postRun(self):

        hosts = self.getAllHosts()

        for host in hosts:
            guests = copy.copy(host.guests)
            for g in guests:
                try:
                    host.removeGuest(g)
                    guests[g].uninstall()
                except: pass

        super(FunctionalBase, self).postRun()

class DifferentGPU(object):
    __metaclass__ = ABCMeta

    @abstractmethod
    def installHostDrivers(self):
        """
        install Host drivers in case of vGPU
        """
        pass

    @abstractmethod
    def installGuestDrivers(self):
        """
        install inguest divers on VM
        """
        pass 

    @abstractmethod
    def assertvGPURunningInVM(self, vm, vGPUType):
        """
        assert if GPU running in VM
        """
        pass

    @abstractmethod
    def assertvGPUNotRunningInVM(self, vm, vGPUType):
        """
        assert if GPU not running in VM
        """
        pass 
 
    @abstractmethod
    def runWorkload(self, vm):
        """
        Running workload on the VM
        """
        pass

class NvidiaWindowsvGPU(DifferentGPU):

    def installHostDrivers(self):
        VGPUTest().installNvidiaHostDrivers()

    def installGuestDrivers(self, guest):
        VGPUTest().installNvidiaWindowsDrivers(guest)

    def assertvGPURunningInVM(self, guest, vGPUType):
        VGPUTest().assertvGPURunningInWinVM(guest, vGPUType) 

    def assertvGPUNotRunningInVM(self, guest, vGPUType):
        VGPUTest().assertvGPUNotRunningInWinVM(guest, vGPUType)

    def runWorkload(self,vm):
        VGPUTest().runWindowsWorkload(vm)

class NvidiaLinuxvGPU(DifferentGPU):

    def installHostDrivers(self):
        xenrt.TEC().logverbose("Not implemented")
        pass

    def installGuestDrivers(self, guest):
        VGPUTest().installNvidiaLinuxDrivers(guest)

    def assertvGPURunningInVM(self, guest, vGPUType):
        VGPUTest().assertvGPURunningInLinuxVM(guest,vGPUType,"Nvidia")

    def assertvGPUNotRunningInVM(self, guest, vGPUType):
        VGPUTest().assertvGPUNotRunningInLinuxVM(guest,vGPUType,"Nvidia")

    def runWorkload(self,vm):
        xenrt.TEC().logverbose("Not implemented")
        pass

class IntelWindowsvGPU(DifferentGPU):

    def installHostDrivers(self):
        xenrt.TEC().logverbose("Not implemented")
        pass

    def installGuestDrivers(self, guest):
        VGPUTest().installIntelWindowsDrivers(guest)

    def assertvGPURunningInVM(self, guest, vGPUType):
        VGPUTest().assertvGPURunningInWinVM(guest, vGPUType)

    def assertvGPUNotRunningInVM(self, guest, vGPUType):
        VGPUTest().assertvGPUNotRunningInWinVM(guest, vGPUType)

    def runWorkload(self,vm):
        VGPUTest().runWindowsWorkload(self,vm)

""" Negative Test Cases """

class _AddPassthroughToFullGPU(_VGPUOwnedVMsTest):
    """
    Fill up a pGPUs, each with one single vGPU
    Add one more VM with a PT vGPU and check it doesn't start
    """
    __ERROR = "VGPU type is not compatible with one or more of the VGPU types currently running on this PGPU"

    def __init__(self, config):
        super(_AddPassthroughToFullGPU, self).__init__([VGPUOS.Win7x86], config, VGPUDistribution.BreadthFirst, False, False)

    def __prepareClones(self, config):

        numberRequired = len(GPUGroupManager(self.getDefaultHost()).getPGPUUuids(all = True))
        log("Number of pGPUs: %d" % numberRequired)

        self.__shutdownMaster()
        for x in range(numberRequired):
            self.__clones.append(self.__master.cloneVM())

        ptCreator = VGPUInstaller(self.getDefaultHost(), config, self._distribution)
        ptCreator.createOnGuest(self.__ptGuest, ptCreator.groupUUID(), True)

    def __shutdownMaster(self):
        if self.__master.getState() == "UP":
            self.__master.setState("DOWN")

    def run(self, arglist):
        self.__master = self.masterGuest(self._requiredEnvironments[0], self.getDefaultHost())
        self.__clones = []
        self.__shutdownMaster()
        self.__ptGuest = self.__master.cloneVM()
        log("Pass-through guest is %s" % str(self.__ptGuest))

        if self.isNvidiaK1(self._configuration):
            self.__prepareClones(VGPUConfig.K1PassThrough)
        else:
            self.__prepareClones(VGPUConfig.K2PassThrough)

        #-------------------------------------------
        step("Start all non-pass-through clones")
        #-------------------------------------------
        [vm.start() for vm in self.__clones]

        #-------------------------------------------
        step("Start the pass-through clone")
        #-------------------------------------------
        try:
            step("Start the pass-through clone")
            self.__ptGuest.start()
        except Exception, e:
            if not re.search(self.__ERROR, str(e)):
                raise xenrt.XRTFailure("Exception raised not matching expected error message: " + str(e))

            log("Pass-through VM could not be started - as expected")
            return

        raise xenrt.XRTFailure("Pass-through guest was allowed to start on a pre-used pGPU")

    def postRun(self):
        for guest in self.__clones:
            self._removeGuest(guest)
        self._removeGuest(self.__ptGuest)
        super(_AddPassthroughToFullGPU, self).postRun()

class TCAddPassthroughToFullGPUK100(_AddPassthroughToFullGPU):
     def __init__(self):
         super(TCAddPassthroughToFullGPUK100, self).__init__(VGPUConfig.K100)

class TCAddPassthroughToFullGPUK200(_AddPassthroughToFullGPU):
     def __init__(self):
         super(TCAddPassthroughToFullGPUK200, self).__init__(VGPUConfig.K200)

class _AddvGPUToFullyPassedThroughGPU(_VGPUOwnedVMsTest):
    """
    Pass-through all pGPUs
    Add one more VM with a non-PT vGPU and check it doesn't start
    """
    __ERROR = "VGPU type is not compatible with one or more of the VGPU types currently running on this PGPU"
    def __init__(self, ptConfig, vGPUConfig):
        super(_AddvGPUToFullyPassedThroughGPU, self).__init__([VGPUOS.Win7x86], ptConfig, VGPUDistribution.BreadthFirst, False, True)
        self.__vgpuConfig = vGPUConfig

    def run(self, arglist):
        vgpuCreator = VGPUInstaller(self.getDefaultHost(), self.__vgpuConfig, self._distribution)

        master = self.masterGuest(self._distribution, self.getDefaultHost())

        #-------------------------------------------
        step("Ensure master is down and clone")
        #-------------------------------------------
        if master.getState() != "DOWN":
            master.shutdown()

        self.vm = master.cloneVM()
        log("Non-PT clone is called: %s" % self.vm)
        log("Shutdown the clone if it's running")
        if self.vm.getState() != "DOWN":
            self.vm.shutdown()

        log("Restart the master")
        try:
            if master.getState() != "UP":
                master.start()
        except Exception, e:
            log("An error occured when starting the master")
            log(str(e))
            pass

        log("Status guests and types: %s" % str(self.guestAndTypesStatus()))

        #-------------------------------------------
        step("Create non-pass-through vGPU")
        #-------------------------------------------
        vgpuCreator.createOnGuest(self.vm, self._vGPUCreator.groupUUID(), True)

        log("PT vm power state is %s" % self.vm.getState())
        log("Status guests and types: %s" % str(self.guestAndTypesStatus()))
        log("Total guests = %d" % len(self.getDefaultHost().listGuests()))

        #-------------------------------------------
        step("Start the non-pass-through clone")
        #-------------------------------------------
        try:
            self.vm.start()
        except Exception, e:
            if not re.search(self.__ERROR, str(e)):
                raise xenrt.XRTFailure("Exception raised not matching expected error message: " + str(e))

            log("Non-pass-through VM could not be started - as expected")
            return

        raise xenrt.XRTFailure("Non-pass-through guest was allowed to start on a pre-used pGPU")

    def postRun(self):
        self._removeGuest(self.vm)
        super(_AddvGPUToFullyPassedThroughGPU, self).postRun()

class TCAddvGPUToFullyPThGPUK100(_AddvGPUToFullyPassedThroughGPU):
     def __init__(self):
         super(TCAddvGPUToFullyPThGPUK100, self).__init__(VGPUConfig.K1PassThrough, VGPUConfig.K100)

class TCAddvGPUToFullyPTGPUK260(_AddvGPUToFullyPassedThroughGPU):
     def __init__(self):
         super(TCAddvGPUToFullyPTGPUK260, self).__init__(VGPUConfig.K2PassThrough, VGPUConfig.K200)


class TCVerifyLackOfMobility(_VGPUOwnedVMsTest):
    """
    Check a vGPU VM is not agile

    You'll need:
    RESOURCES_REQUIRED_0=k1>=1
    RESOURCES_REQUIRED_1=k2>=1
    """

    __MIGRATE = "migrate"
    __ERROR_UP = "This operation could not be performed, because the VM has one or more virtual GPUs"

    def __init__(self):
        super(TCVerifyLackOfMobility, self).__init__([VGPUOS.Win7x64], VGPUConfig.K140, VGPUDistribution.BreadthFirst, False, False)

    def __checkAllowedOperations(self, vm):
        allowedOperations = vm.getAllowedOperations()
        log("Allowed operations: %s" % str(allowedOperations))
        for op in allowedOperations:
            if re.search(self.__MIGRATE, op):
                raise xenrt.XRTFailure("VMs allowed operations contained a migrate option with a vGPU attached")

    def __checkError(self, exception):
        log("Error found: %s, checking if it is expected....." % str(exception))
        if not re.search(self.__ERROR_UP, str(exception)):
            xenrt.XRTFailure("Error found was not expected")

        log("Error found matches expectations")
        return

    def __createSxmMap(self, vm):
        """Here be dragons"""
        #Need a dictionary of pairs where key = vdi uuid and value = sr.uuid for the VDIs to be moved
        return dict([(vdi.uuid, vdi.SR().uuid) for vdi in vm.asXapiObject().VDI()])

    def __migrateRunningHost(self, host, vm, live = "false", sxm = False):
        if vm.getState() != "UP":
            vm.setState("UP")
        try:
            if not sxm:
                vm.migrateVM(host, live)
            else:
                vm.migrateVM(live="true", remote_host=host, vdi_sr_list=self.__createSxmMap(vm).items())
        except Exception as e:
            self.__checkError(e)
            return

        xenrt.XRTFailure("No error was raised, but it should have been")

    def __liveMigrateRunningHost(self, host, vm):
        self.__migrateRunningHost(host, vm, "true")

    def run(self, arglist):
        host = self.getDefaultHost()
        slave = self.getHost("RESOURCE_HOST_1")
        vm, ostype = self._guestsAndTypes[0]

        #------------------------
        step("Ensure VM is up")
        #------------------------
        if vm.getState() != "UP":
            vm.setState("UP")

        #------------------------------------------------------------------------------
        step("Check allowed operations for migrate on the VM - VDI list is synonymous")
        #------------------------------------------------------------------------------
        self.__checkAllowedOperations(vm)

        #--------------------------------------
        step("Try a live migrate to myself")
        #--------------------------------------
        self.__liveMigrateRunningHost(host, vm)

        #--------------------------------------
        step("Try a non-live migrate to myself")
        #--------------------------------------
        self.__migrateRunningHost(host, vm)

        #--------------------------------------
        step("Try a migrate to slave")
        #--------------------------------------
        self.__migrateRunningHost(slave, vm)

        #--------------------------------------
        step("Try an SXM migrate to the slave")
        #--------------------------------------
        self.__migrateRunningHost(slave, vm, sxm=True)

class TCImportDifferentvGPU(_VGPUOwnedVMsTest):
    """
    Verify that when a VM with an incorrect vGPU type is imported it cannot be started.

    You'll need:
    RESOURCES_REQUIRED_0=k1>=1
    RESOURCES_REQUIRED_1=k2>=1
    """

    __ERROR_UP = "You attempted to run a VM on a host which doesn't have a pGPU available in the GPU group needed by the VM."

    def __init__(self):
        super(TCImportDifferentvGPU, self).__init__([VGPUOS.Win7x64], VGPUConfig.K140, VGPUDistribution.BreadthFirst, False, False)

    def __checkError(self, exception):
        log("Error found: %s, checking if it is expected....." % str(exception))
        if not re.search(self.__ERROR_UP, str(exception)):
            raise xenrt.XRTFailure("Error found was not expected")

        log("Error found matches expectations")
        return

    def run(self, arglist):
        host = self.getDefaultHost()
        slave = self.getHost("RESOURCE_HOST_1")
        vm, ostype = self._guestsAndTypes[0]

        step("Exporting the VM")
        vm.setState("DOWN")
        vmName = vm.getName()
        tmp = xenrt.resources.TempDirectory()
        path = "%s/%s" % (tmp.path(), vmName)
        vm.exportVM(path)

        step("Uninstalling the VM.")
        vm.setState("DOWN")
        vm.uninstall()

        step("Importing the VM back")
        vm.importVM(slave, path, sr = slave.lookupDefaultSR())

        try:
            vm.start()
        except Exception as e:
            self.__checkError(e)
            return

        raise xenrt.XRTFailure("No error was raised, but it should have been")

""" END Negative TestCases """

class TCNovGPUTypeGiven(FunctionalBase):

    def run(self,arglist):

        self.vGPUCreator = {}
        config = VGPUConfig.K1PassThrough
        self.vGPUCreator[config] = VGPUInstaller(self.host, config)
        groupUUID = self.vGPUCreator[config].groupUUID()

        osType = self.getOSType(self.REQUIRED_DISTROS[0])

        log("Creating Master VM of type %s" % osType)
        vm = self.createMaster(osType)

        log("Creating vGPU ")
        vm.setState("DOWN")

        vm.createvGPU(groupUUID=groupUUID)

        vm.setState("UP")

        vgpuType, vgpuuuid = self.typeOfvGPUonVM(vm)

        log("Checking the type of vGPU attached to VM")
        if not "passthrough" in vgpuType:
            raise xenrt.XRTFailure("VM has not got the passthrough but instead it has got vGPU of type %s" % vgpuType)

        log("Installing the vGPU Guest drivers")
        self.typeOfvGPU.installGuestDrivers(vm)

        log("Checking the GPU passthrough is runngin")
        self.typeOfvGPU.assertvGPURunningInVM(vm,self.getConfigurationName(config))

    def postRun(self):

        super(TCNovGPUTypeGiven,self).postRun()

class TCReuseK2PGPU(FunctionalBase):

    def prepare(self,arglist):

        super(TCReuseK2PGPU, self).prepare(arglist)

        distro = self.REQUIRED_DISTROS[0]

        step("Creating %d vGPUs configurations." % (len(self.VGPU_CONFIG)))
        self.vGPUCreator = {}

        for i in range(len(self.REQUIRED_DISTROS)):

            config = self.VGPU_CONFIG[i]
            distro = self.REQUIRED_DISTROS[i]

            self.vGPUCreator[config] = VGPUInstaller(self.host, config)

            osType = self.getOSType(distro)

            log("Creating Master VM of type %s" % osType)
            vm = self.createMaster(osType)

            log("Creating vGPU of type %s" % (self.getConfigurationName(config)))
            self.configureVGPU(config, vm)
            vm.setState("UP")

            log("Install guest drivers for %s" % str(vm))
            self.typeOfvGPU.installGuestDrivers(vm)

            log("Checking whether vGPU is runnnig on the VM or not")
            self.typeOfvGPU.assertvGPURunningInVM(vm,self.getConfigurationName(config))

            vm.setState("DOWN")

            log("Setting the enable type of all the pGPUs except 2 to passthrough")
            config = "passthrough"

            self.pGPUs = self.host.minimalList("pgpu-list", "")
            if len(self.pGPUs) > 2:
                typeUUID = self.host.getSupportedVGPUTypes()[config]
                extrapGPU = len(self.pGPUs) - 2
                for i in range(extrapGPU):
                    self.host.genParamSet('pgpu', self.pGPUs[i], 'enabled-VGPU-types', typeUUID)

    def run(self,arglist):

        #Assuming now only 2 pGPUs are available for other configs
        VMs ={}
        leftVMs = {}

        for config in self.VGPU_CONFIG:
            VMs[config] = []
            leftVMs[config] = ''

        for i in range(len(self.REQUIRED_DISTROS)):

            config = self.VGPU_CONFIG[i]
            distro = self.REQUIRED_DISTROS[i]
            osType = self.getOSType(distro)

            nVMs = MaxNumOfVGPUPerPGPU[config]

            for n in range(nVMs+1):
                log("Cloning %dth VM from Master VM" % n)
                g = self.cloneVM(osType)
                VMs[config].append(g)

        for config in self.VGPU_CONFIG:
            totalVMsUP = 0
            for vm in VMs[config]:
                if totalVMsUP < MaxNumOfVGPUPerPGPU[config]:
                    vm.setState("UP")
                    log("Checking whether vGPU is runnnig on the VM or not")
                    self.typeOfvGPU.assertvGPURunningInVM(vm,self.getConfigurationName(config))
                else:
                    leftVMs[config] = vm
                totalVMsUP = totalVMsUP + 1

        for config in leftVMs:
            try:
                leftVMs[config].setState("UP")
                raise xenrt.XRTFailure("VM is able to boot up but it should'nt be")
            except:
                pass

        for config in self.VGPU_CONFIG:
            log("Shuting down 1 VM of vGPU config %s" % self.getConfigurationName(config))
            VMs[config][0].setState("DOWN")

        for config in leftVMs:
            log("Starting the already shutdown VM")
            leftVMs[config].setState("UP")
            self.typeOfvGPU.assertvGPURunningInVM(leftVMs[config],self.getConfigurationName(config))

        for pgpu in self.pGPUs:
            supportedTypes = self.host.genParamGet('pgpu',pgpu,'supported-VGPU-types').replace(";", ",").replace(" ", "")
            self.host.genParamSet('pgpu', pgpu, 'enabled-VGPU-types', supportedTypes)

class TCRevertvGPUSnapshot(FunctionalBase):

    def prepare(self,arglist):

        super(TCRevertvGPUSnapshot, self).prepare(arglist)

        step("Creating %d vGPUs configurations." % (len(self.VGPU_CONFIG)))
        self.vGPUCreator = {}
        for config in self.VGPU_CONFIG:
            self.vGPUCreator[config] = VGPUInstaller(self.host, config)

        for distro in self.REQUIRED_DISTROS:

            osType = self.getOSType(distro)

            log("Creating Master VM of type %s" % osType)
            vm = self.createMaster(osType)

            log("Creating vGPU of type %s" % (self.getConfigurationName(self.VGPU_CONFIG[0])))
            self.configureVGPU(self.VGPU_CONFIG[0], vm)
            vm.setState("UP")

            log("Install guest drivers for %s" % str(vm))
            self.typeOfvGPU.installGuestDrivers(vm)

            log("Checking whether vGPU is runnnig on the VM or not")
            self.typeOfvGPU.assertvGPURunningInVM(vm,self.getConfigurationName(self.VGPU_CONFIG[0]))

            vm.setState("DOWN")
            log("Cloning VM from Master VM")
            g = self.cloneVM(osType)
            self.guests[osType] = g

    def run(self,arglist):

        for osType in self.guests:

            expVGPUType = self.getConfigurationName(self.VGPU_CONFIG[0])
            vm = self.guests[osType]
            snapshot = vm.snapshot()

            vm.setState("DOWN")
            vm.destroyvGPU()

            vm.setState("UP")
            self.typeOfvGPU.assertvGPUNotRunningInVM(vm,expVGPUType)

            vgpuType, vgpuuuid = self.typeOfvGPUonVM(vm)

            if vgpuType:
                raise xenrt.XRTFailure("VM has got vGPU of type %s with uuid %s" % (vgpuType,vgpuuuid))

            vm.revert(snapshot)
            vm.setState("UP")
            self.typeOfvGPU.assertvGPURunningInVM(vm,expVGPUType)

            vgpuType, vgpuuuid = self.typeOfvGPUonVM(vm)

            if not vgpuType:
                raise xenrt.XRTFailure("VM has not got any vGPU")

            if not (expVGPUType in vgpuType):
                raise xenrt.XRTFailure("VM has not got expected vGPU type which is %s" % (expVGPUType))

class TCvGPUBalloon(FunctionalBase):

    def prepare(self,arglist):

        super(TCvGPUBalloon, self).prepare(arglist)

        step("Creating %d vGPUs configurations." % (len(self.VGPU_CONFIG)))
        self.vGPUCreator = {}
        self.vms = {}

        for config in self.VGPU_CONFIG:
            self.vGPUCreator[config] = VGPUInstaller(self.host, config)

        for distro in self.REQUIRED_DISTROS:

            osType = self.getOSType(distro)

            log("Creating Master VM of type %s" % osType)
            vm = self.createMaster(osType)

            log("Creating vGPU of type %s" % (self.getConfigurationName(self.VGPU_CONFIG[0])))
            self.configureVGPU(self.VGPU_CONFIG[0], vm)
            vm.setState("UP")

            log("Install guest drivers for %s" % str(vm))
            self.typeOfvGPU.installGuestDrivers(vm)

            log("Checking vGPU should be running")
            self.typeOfvGPU.assertvGPURunningInVM(vm,self.getConfigurationName(self.VGPU_CONFIG[0]))

            vm.setState("DOWN")
            guests = []
            for i in range(2):
                log("Cloning VM from Master VM")
                guests.append(self.cloneVM(osType))
                self.vms[osType] = guests

    def run(self,arglist):

        for distro in self.REQUIRED_DISTROS:

            vms = self.vms[self.getOSType(distro)]
            host = self.getDefaultHost()

            for vm in vms:
                vm.setState("DOWN")

            #Filling up whole Memory

            remainingMem = host.getMaxMemory()
            maxStatic0 = remainingMem * 2/3
            minDynamic0 = remainingMem/3
            maxDynamic0 = maxStatic0

            maxStatic1 = remainingMem * 2/3
            minDynamic1 = remainingMem/3
            maxDynamic1 = remainingMem/2

            g0 = vms[0]
            g1 = vms[1]
            g0.setMemoryProperties(None,minDynamic0,maxDynamic0,maxStatic0)
            g1.setMemoryProperties(None,minDynamic1,maxDynamic1,maxStatic1)

            g0.setState("UP")
            domid0 = g0.getDomid()

            g1.setState("UP")

            #Checking that first VM is still UP
            if g0.getState() != "UP":
                raise xenrt.XRTFailure("VM %s is not UP" % g0.uuid)

            #Checking whether first VM is reset
            domid01 = g0.getDomid()
            if domid0 != domid01:
                raise xenrt.XRTFailure("VM %s is reset during the start of second VM" % g0.uuid)

            xenrt.sleep(120)

            #Changing Memory of both the VMs
            for i in range(5):
                g0.setDynamicMemRange(minDynamic1,maxDynamic1)
                g0.waitForTarget(600)
                xenrt.sleep(10)
                g1.setDynamicMemRange(minDynamic0,maxDynamic0)
                g1.waitForTarget(600)
                xenrt.sleep(10)
                g0.reboot()
                g1.reboot()
                temp = g0
                g0 = g1
                g1 = temp

            g0.setState("DOWN")
            g1.setState("DOWN")

            #Scale up to Max
            g0.setMemoryProperties(None,minDynamic0,remainingMem,remainingMem)
            g0.setState("UP")
            g0.setDynamicMemRange(remainingMem,remainingMem)
            g0.waitForTarget(600)
            xenrt.sleep(10)
            g0.checkMemory(inGuest=True)
            g0.reboot()

            #Scale down to Min
            g0.setDynamicMemRange(minDynamic0,minDynamic0)
            g0.waitForTarget(600)
            xenrt.sleep(10)
            g0.checkMemory(inGuest=True)

class TCRevertnonvGPUSnapshot(FunctionalBase):

    def prepare(self,arglist):

        super(TCRevertnonvGPUSnapshot, self).prepare(arglist)

        step("Creating %d vGPUs configurations." % (len(self.VGPU_CONFIG)))
        self.vGPUCreator = {}
        for config in self.VGPU_CONFIG:
            self.vGPUCreator[config] = VGPUInstaller(self.host, config)

        for distro in self.REQUIRED_DISTROS:

            osType = self.getOSType(distro)

            log("Creating Master VM of type %s" % osType)
            vm = self.createMaster(osType)

            vm.setState("DOWN")

            log("Cloning VM from Master VM")
            g = self.cloneVM(osType)
            self.guests[osType] = g

    def run(self,arglist):

        for osType in self.guests:

            expVGPUType = self.getConfigurationName(self.VGPU_CONFIG[0])
            vm = self.guests[osType]
            snapshot = vm.snapshot()

            vm.setState("DOWN")
            log("Creating vGPU of type %s" % (self.getConfigurationName(self.VGPU_CONFIG[0])))
            self.configureVGPU(self.VGPU_CONFIG[0], vm)

            vm.setState("UP")

            log("Install guest drivers for %s" % str(vm))
            self.typeOfvGPU.installGuestDrivers(vm)

            self.typeOfvGPU.assertvGPURunningInVM(vm,expVGPUType)

            vgpuType, vgpuuuid = self.typeOfvGPUonVM(vm)

            if not vgpuType:
                raise xenrt.XRTFailure("VM has not got any vGPU")

            if not (expVGPUType in vgpuType):
                raise xenrt.XRTFailure("VM has not got expected vGPU type which is %s" % (expVGPUType))

            vm.revert(snapshot)
            vm.setState("UP")
            self.typeOfvGPU.assertvGPUNotRunningInVM(vm,expVGPUType)

            vgpuType, vgpuuuid = self.typeOfvGPUonVM(vm)

            if vgpuType:
                raise xenrt.XRTFailure("VM has got vGPU of type %s with uuid %s" % (vgpuType,vgpuuuid))

class TCChangeK2vGPUType(TCRevertvGPUSnapshot):

    def run(self,arglist):

        for distro in self.REQUIRED_DISTROS:

            vm = self.guests[self.getOSType(distro)]
            for config in self.VGPU_CONFIG:

                vm.setState("DOWN")

                log("Destroying vGPU")
                vm.destroyvGPU()

                log("Creating vGPU of type %s" % (self.getConfigurationName(config)))
                self.configureVGPU(config, vm)
                vm.setState("UP")

                xenrt.sleep(300)

                vm.reboot()

                log("Checking whether vGPU is runnnig on the VM or not")
                self.typeOfvGPU.assertvGPURunningInVM(vm,self.getConfigurationName(config))

class TCBasicVerifOfAllK2config(FunctionalBase):

    def prepare(self,arglist):

        super(TCBasicVerifOfAllK2config, self).prepare(arglist)

        self.host = self.getDefaultHost()

        step("Creating %d vGPUs configurations." % (len(self.VGPU_CONFIG)))
        self.vGPUCreator = {}
        for config in self.VGPU_CONFIG:
            self.vGPUCreator[config] = VGPUInstaller(self.host, config)

        for distro in self.REQUIRED_DISTROS:

            osType = self.getOSType(distro)

            log("Creating Master VM of type %s" % osType)
            vm = self.createMaster(osType)
            vm.enlightenedDrivers = True
            vm.setState("UP")
            if vm.windows:
                vm.enableFullCrashDump()
            self.masterVMsSnapshot[osType] = vm.snapshot()

    def insideRun(self,config,distro):

            osType = self.getOSType(distro)

            vm = self.masterVMs[osType]

            expVGPUType = self.getConfigurationName(config)

            vm.setState("DOWN")
            log("Creating vGPU of type %s" % (expVGPUType))
            self.configureVGPU(config, vm)
            vm.setState("UP")

            log("Install guest drivers for %s" % str(vm))
            self.typeOfvGPU.installGuestDrivers(vm)

            log("Checking whether vGPU is runnnig on the VM or not")
            self.typeOfvGPU.assertvGPURunningInVM(vm,expVGPUType)

            vm.setState("DOWN")
            log("Cloning VM from Master VM")
            g = self.cloneVM(osType)
            self.guests[osType] = g

            g.setState("UP")
            self.typeOfvGPU.assertvGPURunningInVM(g,expVGPUType)

            self.typeOfvGPU.runWorkload(g)

            self.typeOfvGPU.assertvGPURunningInVM(g,expVGPUType)

            g.reboot()

            self.typeOfvGPU.assertvGPURunningInVM(g,expVGPUType)

            g.setState("DOWN")

            log("Uninstalling guest %s" % str(g))
            try: g.uninstall()
            except: pass

class TCAssignK2vGPUToVMhasGotvGPU(TCBasicVerifOfAllK2config):

    def insideRun(self,config,distro):

        host = self.getDefaultHost()
        string = "GRID "

        osType = self.getOSType(distro)

        vm = self.masterVMs[osType]

        expVGPUType = self.getConfigurationName(config)

        vm.setState("DOWN")
        log("Creating vGPU of type %s" % (expVGPUType))
        self.configureVGPU(config, vm)
        vm.setState("UP")

        log("Install guest drivers for %s" % str(vm))
        self.typeOfvGPU.installGuestDrivers(vm)

        log("Checking whether vGPU is runnnig on the VM or not")
        self.typeOfvGPU.assertvGPURunningInVM(vm,expVGPUType)

        vm.setState("DOWN")
        log("Cloning VM from Master VM")
        g = self.cloneVM(osType)
        self.guests[osType] = g

        g.setState("UP")
        self.typeOfvGPU.assertvGPURunningInVM(g,expVGPUType)

        actualConfig = string + expVGPUType

        if config != VGPUConfig.K200 and config != VGPUConfig.K100:
            actualConfig = actualConfig + 'Q'

        typeUUID = host.getSupportedVGPUTypes()[actualConfig]
        groupUUID = self.vGPUCreator[config].groupUUID()

        try:
            g.createvGPU(groupUUID, typeUUID)
            raise xenrt.XRTFailure("vGPU creation is successful")
        except:
            pass

        g.setState("DOWN")

        try:
            g.createvGPU(groupUUID, typeUUID)
            raise xenrt.XRTFailure("vGPU creation is successful")
        except:
            pass

        g.destroyvGPU()

        g.setState("UP")

        self.typeOfvGPU.assertvGPUNotRunningInVM(g,expVGPUType)

        g.setState("DOWN")
        log("Uninstalling guest %s" % str(g))
        try: g.uninstall()
        except: pass

class TCOpsonK2vGPUToVMhasGotvGPU(TCBasicVerifOfAllK2config):

    def insideRun(self,config,distro):

        host = self.getDefaultHost()
        string = "GRID "

        osType = self.getOSType(distro)

        vm = self.masterVMs[osType]

        expVGPUType = self.getConfigurationName(config)

        vm.setState("DOWN")
        log("Creating vGPU of type %s" % (expVGPUType))
        self.configureVGPU(config, vm)
        vm.setState("UP")

        log("Install guest drivers for %s" % str(vm))
        self.typeOfvGPU.installGuestDrivers(vm)

        log("Checking whether vGPU is runnnig on the VM or not")
        self.typeOfvGPU.assertvGPURunningInVM(vm,expVGPUType)

        vm.setState("DOWN")
        log("Cloning VM from Master VM")
        g = self.cloneVM(osType)
        self.guests[osType] = g

        g.setState("UP")
        self.typeOfvGPU.assertvGPURunningInVM(g,expVGPUType)

        try:
            g.checkpoint()
            raise xenrt.XRTFailure("Checkpoint is successful on a vGPU capable VM")
        except:
            pass

        try:
            g.suspend()
            raise xenrt.XRTFailure("VM suspend is successful on a vGPU capable VM")
        except:
            pass

        g.setState("DOWN")
        log("Uninstalling guest %s" % str(g))
        try: g.uninstall()
        except: pass

class TCCheckPerfModeAllVMs(TCBasicVerifOfAllK2config):

    def startVM(self,vm,vgpuType):

        vm.setState("UP")
        self.typeOfvGPU.assertvGPURunningInVM(vm,vgpuType)

    def insideRun(self,config,distro):

        host = self.getDefaultHost()
        num = 2

        osType = self.getOSType(distro)

        vm = self.masterVMs[osType]

        expVGPUType = self.getConfigurationName(config)

        vm.setState("DOWN")
        log("Creating vGPU of type %s" % (expVGPUType))
        self.configureVGPU(config, vm)
        vm.setState("UP")

        log("Install guest drivers for %s" % str(vm))
        self.typeOfvGPU.installGuestDrivers(vm)

        log("Checking whether vGPU is runnnig on the VM or not")
        self.typeOfvGPU.assertvGPURunningInVM(vm,expVGPUType)

        vm.setState("DOWN")
        log("Cloning VMs from Master VM")

        g =[]

        for i in range(num):
            tmpG = self.cloneVM(osType)
            self.guests[osType] = tmpG
            g.append(tmpG)
            tmpG.setState("DOWN")

        groupUUID = self.vGPUCreator[config].groupUUID()
        host.setBreadthFirstAllocationType(groupUUID)

        pStart = [xenrt.PTask(self.startVM,g[i],expVGPUType) for i in range(num)]
        xenrt.pfarm(pStart)

        vgpuResidentOn = []
        for i in range(num):
            temp,vgpu = self.typeOfvGPUonVM(g[i])
            r = host.genParamGet("vgpu",vgpu,"resident-on")
            vgpuResidentOn.append(r)

        if vgpuResidentOn[0] == vgpuResidentOn[1]:
            raise xenrt.XRTFailure("Both the vGPUs are on same physical GPU as the allocation mode is breadth first")

        for guest in g:
            guest.setState("DOWN")
            log("Uninstalling guest %s" % str(guest))
            try: guest.uninstall()
            except: pass

class TCBreadthK100K1Pass(TCBasicVerifOfAllK2config):

    NUM_VMS = [2,2]
    ALLOCATION_MODE = VGPUDistribution.BreadthFirst
    LOCK_PGPU_CONFIG = "passthrough"
    NUM_PGPU = None

    def startVM(self,vm):

        vm.setState("UP")

    def lockPGPUs(self):

        self.pGPUs = self.host.minimalList("pgpu-list", "")
        if not self.NUM_PGPU:
            return

        num = self.NUM_PGPU
        log("Setting the enable type of all the pGPUs except %s to passthrough" % (str(num)))

        config = self.LOCK_PGPU_CONFIG

        if len(self.pGPUs) > num:
            typeUUID = self.host.getSupportedVGPUTypes()[config]
            extrapGPU = len(self.pGPUs) - num
            for i in range(extrapGPU):
                self.host.genParamSet('pgpu', self.pGPUs[i], 'enabled-VGPU-types', typeUUID)

    def unlockPGPUs(self):

        for pgpu in self.pGPUs:
            supportedTypes = self.host.genParamGet('pgpu',pgpu,'supported-VGPU-types').replace(";", ",").replace(" ", "")
            self.host.genParamSet('pgpu', pgpu, 'enabled-VGPU-types', supportedTypes)

    def run(self,arglist):

        host = self.getDefaultHost()
        g = {}
        vms = []

        osType = self.getOSType(self.REQUIRED_DISTROS[0])

        vm = self.masterVMs[osType]

        for i in range(len(self.VGPU_CONFIG)):

            config = self.VGPU_CONFIG[i]
            num = self.NUM_VMS[i]

            expVGPUType = self.getConfigurationName(config)

            vm.setState("DOWN")
            log("Creating vGPU of type %s" % (expVGPUType))
            self.configureVGPU(config, vm)
            vm.setState("UP")

            log("Install guest drivers for %s" % str(vm))
            self.typeOfvGPU.installGuestDrivers(vm)

            log("Checking whether vGPU is runnnig on the VM or not")
            self.typeOfvGPU.assertvGPURunningInVM(vm,expVGPUType)

            vm.setState("DOWN")
            log("Cloning VMs from Master VM")

            key = str(config)
            g[key] = []
            for i in range(num):
                tmpG = self.cloneVM(osType)
                self.guests[osType] = tmpG
                g[key].append(tmpG)
                vms.append(tmpG)
                tmpG.setState("DOWN")

            vm.setState("UP")
            vm.revert(self.masterVMsSnapshot[osType])

        groupUUID = self.vGPUCreator[config].groupUUID()

        if self.ALLOCATION_MODE == VGPUDistribution.BreadthFirst:
            host.setBreadthFirstAllocationType(groupUUID)
        else:
            host.setDepthFirstAllocationType(groupUUID)

        self.lockPGPUs()

        pStart = [xenrt.PTask(self.startVM,vms[i]) for i in range(len(vms))]
        xenrt.pfarm(pStart)

        for key in g:
            for guest in g[key]:
                expVGPUType = self.getConfigurationName(int(key))
                self.typeOfvGPU.assertvGPURunningInVM(guest,expVGPUType)

        for guest in vms:
            guest.setState("DOWN")
            log("Uninstalling guest %s" % str(guest))
            try: guest.uninstall()
            except: pass

        self.unlockPGPUs()
        host.setDepthFirstAllocationType(groupUUID)

    def postRun(self):

        self.unlockPGPUs()
        super(TCBreadthK100K1Pass, self).postRun()

class TCDepthK100K140K1Pass(TCBreadthK100K1Pass):

    NUM_VMS = [4,4]
    ALLOCATION_MODE = VGPUDistribution.DepthFirst
    LOCK_PGPU_CONFIG = "passthrough"
    NUM_PGPU = 2

class TCDepthK1Pass(TCBreadthK100K1Pass):

    NUM_VMS = [4]
    ALLOCATION_MODE = VGPUDistribution.DepthFirst
    LOCK_PGPU_CONFIG = "GRID K100"
    NUM_PGPU = 4

class TCExportImportK2GPU(FunctionalBase):
    """
    Test the import/export functionality using a single host,
    on a guest VM with a vGPU.
    """

    def prepare(self, arglist):

        super(TCExportImportK2GPU, self).prepare(arglist)

        step("Creating %d vGPUs configurations." % (len(self.VGPU_CONFIG)))
        self.vGPUCreator = {}
        for config in self.VGPU_CONFIG:
            self.vGPUCreator[config] = VGPUInstaller(self.host, config)

        for distro in self.REQUIRED_DISTROS:

            osType = self.getOSType(distro)

            log("Creating Master VM of type %s" % osType)
            self.masterVMs[osType] = self.createMaster(osType)

            log("Creating Master VM snapshot")
            self.masterVMsSnapshot[osType] = self.masterVMs[osType].snapshot()

    def insideRun(self, config, distro):

        osType = self.getOSType(distro)

        expVGPUType = self.getConfigurationName(config)

        step("Testing OS %s with %s type vGPU" % (osType, expVGPUType))
        masterVM = self.masterVMs[osType]
        masterVM.setState("DOWN")
        self.configureVGPU(config, masterVM)
        masterVM.setState("UP")

        log("Install guest drivers for %s" % str(masterVM))
        self.typeOfvGPU.installGuestDrivers(masterVM)

        masterVM.setState("DOWN")
        vm = self.cloneVM(osType)

        step("Adding the VM in the registry")
        xenrt.TEC().registry.guestPut(vm.getName(), vm)

        step("Converting the VM into a template and cloning a VM from the template.")
        templateMaker = testcases.xenserver.guest.TCMakeTemplate()
        templateMaker.run(["guest=%s" % vm.getName()])

        vm.setState("DOWN")
        vm.uninstall()

        vm = templateMaker.newguest

        step("Starting the VM")
        vm.setState("UP")

        self.typeOfvGPU.assertvGPURunningInVM(vm, expVGPUType)

        vm.setState("DOWN")
        step("Exporting the VM")
        vmName = vm.getName()
        tmp = xenrt.resources.TempDirectory()
        path = "%s/%s" % (tmp.path(), vmName)
        vm.exportVM(path)

        step("Uninstalling the VM.")
        vm.setState("DOWN")
        vm.uninstall()

        step("Importing the VM back")
        vm.importVM(self.host, path)

        step("Starting the imported VM.")
        vm.setState("UP")

        step("Checking that the VM is using the correct vGPU.")
        self.typeOfvGPU.assertvGPURunningInVM(vm, expVGPUType)

        vm.setState("DOWN")

class TCNonWindowsK1(FunctionalBase):

    __ERROR_UP = "The VM is set up to use a feature that requires it to boot as HVM"

    def prepare(self,arglist):

        super(TCNonWindowsK1, self).prepare(arglist)

        self.host = self.getDefaultHost()

        step("Creating %d vGPUs configurations." % (len(self.VGPU_CONFIG)))
        self.vGPUCreator = {}
        for config in self.VGPU_CONFIG:
            self.vGPUCreator[config] = VGPUInstaller(self.host, config)

        for distro in self.REQUIRED_DISTROS:

            osType = self.getOSType(distro)

            log("Creating Master VM of type %s" % osType)
            vm = self.createMaster(osType)

            self.masterVMsSnapshot[osType] = vm.snapshot()

    def checkError(self, exception):
        log("Error found: %s, checking if it is expected....." % str(exception))
        if not re.search(self.__ERROR_UP, str(exception)):
            raise xenrt.XRTFailure("Error found was not expected")

        log("Error found matches expectations")
        return

    def insideRun(self,config,distro):

        osType = self.getOSType(distro)

        vm = self.masterVMs[osType]

        expVGPUType = self.getConfigurationName(config)

        vm.setState("DOWN")
        log("Creating vGPU of type %s" % (expVGPUType))
        self.configureVGPU(config, vm)

        try:
            vm.setState("UP")
        except Exception as e:
            vm.destroyvGPU()
            self.checkError(e)
            return

        vm.destroyvGPU()
        raise xenrt.XRTFailure("No error was raised, but it should have been")

class TCAlloModeK200NFS(VGPUAllocationModeBase):

    """
    A pool of 2 K2 hosts.
    K200 with Win7-x86 and Win7-x64.

    XenRT does not have enough HW for this test; hence it won't be included in any sequence.
    """
    pass

class TCAlloModeK240NFS(VGPUAllocationModeBase):

    """
    A pool of 2 K2 hosts.
    K240 with Win7-x86 and Win7-x64.

    XenRT does not have enough HW for this test; hence it won't be included in any sequence.
    """
    VGPU_CONFIG = [VGPUConfig.K240]
    TEST_VARIANTS = [
        # initial status
        {
            "VMs" : {VGPUConfig.K240: 5},
            "Result" : [4, 1, 0, 0],
        },
        # Fisrt phase
        {
            "VMs" : {VGPUConfig.K240: 3},
            "Result" : [4, 2, 1, 1],
            "Distribution" : VGPUDistribution.BreadthFirst,
        },
        # Sencond Phase
        {
            "VMs" : {VGPUConfig.K240: 1},
            "Result" : [4, 3, 1, 1],
        }
    ]

class TCAlloModeK260NFS(VGPUAllocationModeBase):

    """
    A pool of 2 K2 hosts.
    K260 with Win7-x86 and Win7-x64.

    XenRT does not have enough HW for this test; hence it won't be included in any sequence.
    """
    VGPU_CONFIG = [VGPUConfig.K260]
    TEST_VARIANTS = [
        # initial status
        {
            "VMs" : {VGPUConfig.K260: 3},
            "Result" : [2, 1, 0, 0],
        },
        # Fisrt phase
        {
            "VMs" : {VGPUConfig.K240: 3},
            "Result" : [2, 2, 1, 1],
            "Distribution" : VGPUDistribution.BreadthFirst,
        },
        # Sencond Phase
        {
            "VMs" : {VGPUConfig.K240: 1},
            "Result" : [2, 2, 2, 1],
        }
    ]

class TCAlloModeK200LVM(VGPUAllocationModeBase):

    """
    A pool of 2 K2 hosts.
    K200 with Win7-x86 and Win7-x64.

    XenRT does not have enough HW for this test; hence it won't be included in any sequence.
    """

    SR_TYPE = SRType.Local
    TEST_VARIANTS = [
        # initial status
        {
            "VMs" : {VGPUConfig.K200: 9},
            "Result" : [8, 1, 0, 0],
        },
        # Fisrt phase
        {
            "VMs" : {VGPUConfig.K200: 1},
            "Result" : [8, 2, 0, 0],
            "Distribution" : VGPUDistribution.BreadthFirst,
        },
        # Sencond Phase
        {
            "VMs" : {VGPUConfig.K200: 7},
            "Result" : [8, 8, 0, 0],
            "ExpectError" : True
        }
    ]

class TCAlloModeK240LVM(VGPUAllocationModeBase):

    """
    A pool of 2 K2 hosts.
    K240 with Win7-x86 and Win7-x64.

    XenRT does not have enough HW for this test; hence it won't be included in any sequence.
    """

    SR_TYPE = SRType.Local
    VGPU_CONFIG = [VGPUConfig.K240]
    TEST_VARIANTS = [
        # initial status
        {
            "VMs" : {VGPUConfig.K240: 5},
            "Result" : [4, 1, 0, 0],
        },
        # Fisrt phase
        {
            "VMs" : {VGPUConfig.K240: 1},
            "Result" : [4, 2, 0, 0],
            "Distribution" : VGPUDistribution.BreadthFirst,
        },
        # Sencond Phase
        {
            "VMs" : {VGPUConfig.K240: 3},
            "Result" : [4, 4, 0, 0],
            "ExpectError" : True
        }
    ]

class TCAlloModeK260LVM(VGPUAllocationModeBase):

    """
    A pool of 2 K2 hosts.
    K260 with Win7-x86 and Win7-x64.

    XenRT does not have enough HW for this test; hence it won't be included in any sequence.
    """

    SR_TYPE = SRType.Local
    VGPU_CONFIG = [VGPUConfig.K260]
    TEST_VARIANTS = [
        # initial status
        {
            "VMs" : {VGPUConfig.K260: 3},
            "Result" : [2, 1, 0, 0],
        },
        # Fisrt phase
        {
            "VMs" : {VGPUConfig.K260: 1},
            "Result" : [2, 2, 0, 0],
            "Distribution" : VGPUDistribution.BreadthFirst,
        },
        # Sencond Phase
        {
            "VMs" : {VGPUConfig.K260: 1},
            "Result" : [2, 2, 0, 0],
            "ExpectError" : True
        }
    ]

class TCAlloModeK100NFS(VGPUAllocationModeBase):

    """
    A pool of 2 K1 hosts.
    K100 with Win7-x86 and Win7-x64.
    """
    VGPU_CONFIG = [VGPUConfig.K100]
    POOL = None
    SR_TYPE = None
    TEST_VARIANTS = [
        # initial status
        {
            "VMs" : {VGPUConfig.K100: 9},
            "Result" : [8, 1, 0, 0, 0, 0, 0, 0],
        },
        # Fisrt phase
        {
            "VMs" : {VGPUConfig.K100: 7},
            "Result" : [8, 2, 1, 1, 1, 1, 1, 1],
            "Distribution" : VGPUDistribution.BreadthFirst,
        },
        # Sencond Phase
        {
            "VMs" : {VGPUConfig.K100: 1},
            "Result" : [8, 3, 1, 1, 1, 1, 1, 1],
        }
    ]

class TCAlloModeK140NFS(VGPUAllocationModeBase):

    """
    A pool of 2 K1 hosts.
    K140 with Win7-x86 and Win7-x64.
    """
    VGPU_CONFIG = [VGPUConfig.K140]
    POOL = None
    SR_TYPE = None
    TEST_VARIANTS = [
        # initial status
        {
            "VMs" : {VGPUConfig.K140: 5},
            "Result" : [4, 1, 0, 0, 0, 0, 0, 0],
        },
        # Fisrt phase
        {
            "VMs" : {VGPUConfig.K140: 7},
            "Result" : [4, 2, 1, 1, 1, 1, 1, 1],
            "Distribution" : VGPUDistribution.BreadthFirst,
        },
        # Sencond Phase
        {
            "VMs" : {VGPUConfig.K140: 1},
            "Result" : [4, 3, 1, 1, 1, 1, 1, 1],
        }
    ]

class TCAlloModeK100LVM(VGPUAllocationModeBase):

    """
    A pool of 2 K1 hosts.
    K100 with Win7-x86 and Win7-x64.
    """

    POOL = None
    SR_TYPE = SRType.Local
    VGPU_CONFIG = [VGPUConfig.K100]
    TEST_VARIANTS = [
        # initial status
        {
            "VMs" : {VGPUConfig.K100: 9},
            "Result" : [8, 1, 0, 0, 0, 0, 0, 0],
        },
        # Fisrt phase
        {
            "VMs" : {VGPUConfig.K100: 3},
            "Result" : [8, 2, 1, 1, 0, 0, 0, 0],
            "Distribution" : VGPUDistribution.BreadthFirst,
        },
        # Sencond Phase
        {
            "VMs" : {VGPUConfig.K100: 21},
            "Result" : [8, 8, 8, 8, 0, 0, 0, 0],
            "ExpectError" : True
        }
    ]

class TCAlloModeK140LVM(VGPUAllocationModeBase):

    """
    A pool of 2 K1 hosts.
    K140 with Win7-x86 and Win7-x64.
    """

    POOL = None
    SR_TYPE = SRType.Local
    VGPU_CONFIG = [VGPUConfig.K140]
    TEST_VARIANTS = [
        # initial status
        {
            "VMs" : {VGPUConfig.K140: 5},
            "Result" : [4, 1, 0, 0, 0, 0, 0, 0],
        },
        # Fisrt phase
        {
            "VMs" : {VGPUConfig.K140: 3},
            "Result" : [4, 2, 1, 1, 0, 0, 0, 0],
            "Distribution" : VGPUDistribution.BreadthFirst,
        },
        # Sencond Phase
        {
            "VMs" : {VGPUConfig.K140: 9},
            "Result" : [4, 4, 4, 4, 0, 0, 0, 0],
            "ExpectError" : True
        }
    ]

class TCAlloModeMixedPool(VGPUAllocationModeBase):

    """
    A pool of 2 hosts. K1 + K2.
    K100, K140, K200 and K240 with Win7x64, Win7x86 and WS2008R2
    """

    POOL = [["K1", "K2"]]
    REQUIRED_DISTROS = [VGPUOS.Win7x86, VGPUOS.Win81x64, VGPUOS.WS2008R2]
    VGPU_CONFIG = [VGPUConfig.K100, VGPUConfig.K140, VGPUConfig.K200, VGPUConfig.K240]
    TEST_VARIANTS = [
        # initial status
        {
            "VMs" : {VGPUConfig.K100: 2, VGPUConfig.K140: 2, VGPUConfig.K200: 1, VGPUConfig.K240: 1},
            # 4 K1 pGPUs, 2 K2 pGPUs
            "Result" : [1, 1, 1, 1, 1, 1],
            "Distribution" : VGPUDistribution.BreadthFirst,
        }
    ]

class TCAlloModeSingleConf(VGPUAllocationModeBase):

    """
    A pool of 2 hosts. K1
    K140 with Win7x64, Win7x86 and WS08R2.
    """

    POOL = None
    SR_TYPE = None
    VM_START = VMStartMethod.OneByOne
    REQUIRED_DISTROS = [VGPUOS.Win81x86, VGPUOS.Win8x64, VGPUOS.WS2008R2]
    VGPU_CONFIG = [VGPUConfig.K140]
    TEST_VARIANTS = [
        # initial status
        {
            "VMs" : {VGPUConfig.K140: 28},
            "Result" : [4, 4, 4, 4, 4, 4, 4, 0],
        },
        # Additional status
        {
            "VMs" : {VGPUConfig.K140: 4},
            "Result" : [4, 4, 4, 4, 4, 4, 4, 4],
            "VMStart" : VMStartMethod.Simultenous
        }
    ]


class TCAlloModePerfDist(VGPUAllocationModeBase):

    """
    A K1 host.
    Win7x86, Win7x64 and WS2008R2.
    """

    POOL = None
    SR_TYPE = None
    VGPU_CONFIG = [VGPUConfig.K100, VGPUConfig.K140, VGPUConfig.K1PassThrough]
    REQUIRED_DISTROS = [VGPUOS.Win7x86, VGPUOS.Win7x64, VGPUOS.WS2008R2]
    TEST_VARIANTS = [
        # bound 2 pgpu to passthrough / 1 pgpu to K140
        # initial status
        {
            "VMs" : {VGPUConfig.K1PassThrough: 2, VGPUConfig.K100: 3, VGPUConfig.K140: 1},
            "Result" : [3, 1, 1, 1],
            "Distribution" : VGPUDistribution.DepthFirst,
        },
        #shutdown K140 and release pgpu to all.
        # First Phase
        {
            "VMs" : {VGPUConfig.K100: 1},
            "Result" : [3, 1, 1, 1],
            "Distribution" : VGPUDistribution.BreadthFirst,
        },
        # Second Phase
        {
            "VMs" : {VGPUConfig.K140: 1},
            "Result" : [3, 1, 1, 1],
            "Distribution" : VGPUDistribution.BreadthFirst,
            "ExpectError" : True
        }
    ]

    def run(self, arglist):

        passthroughList = self.bindConfigurationToPGPU("passthrough", 2)
        k140List = self.bindConfigurationToPGPU("K140", 1)

        self.runTestPhase(self.TEST_VARIANTS[0])

        self.shutdownGuest(self.vGPUCreator[VGPUConfig.K140])
        self.releaseConfiguration(k140List)

        self.runTestPhase(self.TEST_VARIANTS[1])
        self.runTestPhase(self.TEST_VARIANTS[2])

"""
GPU Group related classes
"""

class GPUGroup:
    """
    Generic GPU Group class
    """

    def __init__(self, host, uuid):
        self.__gridtype__ = ""
        self.__meta__ = ""
        #self.__allocmode__ = None
        self.host = host
        self.uuid = uuid.strip()
        self.updatePGPUList()
        #self.updateAllocationMode()

    def getGridType(self):
        if self.__gridtype__ == "":
            self.updatePGPUList()
        return self.__gridtype__

    def updatePGPUList(self):
        self.gpuList = self.host.minimalList("pgpu-list", "", "gpu-group-uuid=%s" % (self.uuid,))
        log("GPU group %s has %s pgpus." % (self.uuid, self.gpuList))
        if self.__gridtype__ == "" and len(self.gpuList) > 0:
            device = self.host.genParamGet("pgpu", self.gpuList[0], "device-name")
            if "GRID K1" in device:
                self.__gridtype__ = "K1"
                return "K1"
            elif "GRID K2" in device:
                self.__gridtype__ = "K2"
                return "K2"
            else:
                self.__gridtype__ = "unknown"
                return "unknown"

    #def updateAllocationMode(self):
        #self.__allocmode__ = self.host.genParamGet("gpu-group", self.uuid, "allocation-algorithm")

    #def setAllocationMode(self, allocationMode):
        #self.host.getParamSet("gpu-group", self.uuid, "allocation-algorithm", allocationMode)
        #self.updateAllocationMode()

    def isAcceptable(self, gridtype):
        myType = self.getGridType()
        return myType == "" or myType == gridtype

class GPUGroupManager:
    """
    GPU Groups manager
    """

    UNUSED_GROUP = "__unused__"

    def __init__(self, host):
        self.host = host
        self.groups = []
        self.__restorePoint = None

    def createEmptyGroup(self, namelabel=""):
        cli = self.host.getCLIInstance()
        uuid = cli.execute("gpu-group-create", "name-label=\"%s\"" % (namelabel,))
        group = GPUGroup(self.host, uuid)
        if namelabel != self.UNUSED_GROUP:
            self.groups.append(group)
        return group

    def obtainExistingGroups(self):
        log("Finding all GPU groups.")
        gpuGroup = []
        allGroups = self.host.minimalList("gpu-group-list")
        for guuid in allGroups:
            if self.getGroupName(guuid) == self.UNUSED_GROUP:
                continue
            group = GPUGroup(self.host, guuid)
            log("Checking device type of gpu group %s: %s" % (group.uuid, group.getGridType()))
            if group.getGridType() == "K1" or group.getGridType() == "K2" or group.getGridType() == "":
                gpuGroup.append(group)
        self.groups = gpuGroup
        return gpuGroup

    def getGroupName(self, groupuuid):
        return self.host.genParamGet("gpu-group", groupuuid, "name-label")

    def listGroupTypes(self):
        return [group.getGridType() for group in self.groups]

    def findGroup(self, uuid):
        for group in self.groups:
            if group.uuid == uuid:
                return group
        group = GPUGroup(self.host, uuid)
        if not group.getGridType() == "unknown":
            self.groups.append(group)
            return group
        else:
            raise xenrt.XRTError("Group %s is not capable of vGPU" % (uuid,))

    def isolatePGPU(self, pgpuuuid):
        isolated = None
        allGroups = self.host.minimalList("gpu-group-list")
        device = self.host.genParamGet("pgpu", pgpuuuid, "device-name")
        for guuid in allGroups:
            if self.getGroupName(guuid) == self.UNUSED_GROUP:
                group = GPUGroup(self.host, guuid)
                if "GRID " + group.getGridType() in device:
                    isolated = guuid
                    break
        if isolated:
            if isolated == self.host.genParamGet("pgpu", pgpuuuid, "gpu-group-uuid"):
                return
        else:
            isolated = self.createEmptyGroup(self.UNUSED_GROUP).uuid
        self.movePGPU(pgpuuuid, isolated)

    def isIsolated(self, pgpuuuid):
        group = self.host.genParamGet("pgpu", pgpuuuid, "gpu-group-uuid")
        if self.host.genParamGet("gpu-group", group, "name-label") == self.UNUSED_GROUP:
            return True
        return False

    def movePGPU(self, pgpuuuid, groupuuid):
        #pgputype = "unknown"
        #device = self.host.genParamGet("pgpu", pgpuuuid, "device-name")
        #if "GRID K1" in device:
            #pgputype = "K1"
        #elif "GRID L2" in device:
            #pgputype = "K2"
        dest = self.findGroup(groupuuid)
        #if dest.isAcceptable(pgputype):
        srcuuid = self.host.genParamGet("pgpu", pgpuuuid, "gpu-group-uuid")
        src = self.findGroup(srcuuid)
        self.host.genParamSet("pgpu", pgpuuuid, "gpu-group-uuid", groupuuid)
        src.updatePGPUList()
        dest.updatePGPUList()
        #else:
            #raise xenrt.XRTError("Target group has tied with different type of cards. %s(dest): %s / %s(src pgpu): %s" %
                #(dest.uuid, dest.getGridType(), pgpuuuid, pgputype))

    def moveAllPGPUs(self, destgroup, srcgroup):
        #if destgroup.isAcceptable(pgputype):
            srcgroup.updatePGPUList()
            for pgpuuuid in srcgroup.gpuList:
                self.host.genParamSet("pgpu", pgpuuuid, "gpu-group-uuid", destgroup.uuid)
            destgroup.updatePGPUList()
        #else:
            #raise xenrt.XRTError("Target group has tied with different type of cards. %s(dest): %s / %s(src): %s" %
                #(destgroup.uuid, destgroup.getGridType(), srcgroup.uuid, srcgroup.getGridType()))

    def mergeGroups(self, destgroup, srcgroup):
        self.moveAllPGPUs(destgroup, srcgroup)
        self.destroyGroup(srcgroup)

    def destroyGroup(self, group):
        if group in self.groups:
            self.groups.remove(group)
        cli = self.host.getCLIInstance().execute("gpu-group-destroy", "uuid=" + group.uuid)

    def getPGPUUuids(self, all = False):
        return [pgpu for pgpu in self.host.minimalList("pgpu-list") if all or not self.isIsolated(pgpu)]

    def enableAllSupportedvGPUTypes(self, pgpuuuid):
        """
        Take all the supported types of vGPUs and set them all to be enabled
        """
        supportedTypes = self.host.genParamGet('pgpu',pgpuuuid,'supported-VGPU-types').replace(";", ",").replace(" ", "")
        self.host.genParamSet('pgpu', pgpuuuid, 'enabled-VGPU-types', supportedTypes)

    def backup(self):
        rp = []
        for group in self.groups:
            pgpulist = copy.deepcopy(group.gpuList)
            rp.append(pgpulist)
        self.__restorePoint = rp
        log("Creating gpu group restore point %s for re-initialization." % (self.__restorePoint,))

    def restore(self):
        """ Role back to 'saved' status with backup method.
            VMs should be removed before calling this method.
        """
        if not self.__restorePoint:
            log("Cannot find restore point.")
            return

        log("Reverting gpu group status to: %s" % (self.__restorePoint,))
        self.obtainExistingGroups()
        cli = self.host.getCLIInstance()
        for pgpulist in self.__restorePoint:
            groupuuid = cli.execute("gpu-group-create", "name-label=%s" % ("restore",)).strip()
            for pgpuuuid in pgpulist:
                for vgpuuuid in self.host.minimalList("vgpu-list", "resident-on=%s" % (pgpuuuid,)):
                    cli.execute("vgpu-destroy", "uuid=%s" % (vgpuuuid, ))
                self.host.genParamSet("pgpu", pgpuuuid, "gpu-group-uuid", groupuuid)
        while len(self.groups):
            self.destroyGroup(self.groups[0])

    def reinitialize(self):
        """ Re-initializing GPU Groups just like default status. """
        pgpudict = {}
        for pgpuuuid in self.getPGPUUuids(all = True):
            device = self.host.genParamGet("pgpu", pgpuuuid, "device-name")
            if not device in pgpudict:
                pgpudict[device] = self.createEmptyGroup(device + " group").uuid
            self.host.genParamSet("pgpu", pgpuuuid, "gpu-group-uuid", pgpudict[device])
            vgputypes = ",".join(self.host.genParamGet("pgpu", pgpuuuid, "supported-VGPU-types").split("; "))
            self.host.genParamSet("pgpu", pgpuuuid, "enabled-VGPU-types", vgputypes)
            self.enableAllSupportedvGPUTypes(pgpuuuid)

        cli = self.host.getCLIInstance()
        for groupuuid in self.host.minimalList(command="gpu-group-list", args="PGPU-uuids=\"\""):
            cli.execute("gpu-group-destroy", "uuid=%s" % (groupuuid, ))


"""
VGPU Group Test cases and base.
"""

class VGPUGroupTestBase(VGPUAllocationModeBase):

    """
    VGPU Group test base class
    """

    POOL = [["K1"], ["K2"]]
    SR_TYPE = SRType.NFS
    REQUIRED_DISTROS = [VGPUOS.Win7x86]
    VGPU_CONFIG = [VGPUConfig.K100, VGPUConfig.K200]
    VGPU_DISTRIBUTION = [VGPUDistribution.DepthFirst]
    VM_START = VMStartMethod.OneByOne
    INSTALL_GUEST_DRIVER = False
    PREPARE_GPU_GROUPS = 1
    INITIAL_GPU_GROUPS = 2
    TEST_VARIANTS = [
        {
            "VMs" : {VGPUConfig.K100: 1, VGPUConfig.K200: 1},
            "Result" : [1, 1, 0, 0, 0, 0]
        },
    ]

    def __init__(self):
        super(VGPUGroupTestBase, self).__init__()

    def setDistributionMode(self, distribution):
        self._distribution = distribution
        if not self.gpuGroupManager:
            ggman = GPUGroupManager(self.host)
            ggman.obtainExistingGroups()
        else:
            ggman = self.gpuGroupManager

        for group in ggman.groups:
            groupUUID = group.uuid

            log("Set vGPU distibution mode of %s group to %d." % (groupUUID, distribution))
            if distribution == VGPUDistribution.DepthFirst:
                self.host.setDepthFirstAllocationType(groupUUID)
            else:
                self.host.setBreadthFirstAllocationType(groupUUID)

    def run(self, arglist):
        log("Obtaining current group info.")
        self.gpuGroupManager = ggman = GPUGroupManager(self.host)
        ggman.reinitialize()
        ggman.obtainExistingGroups()
        gtypes = ggman.listGroupTypes()
        log("Found group types list: " + str(gtypes))
        if len(gtypes) != self.PREPARE_GPU_GROUPS:
            raise xenrt.XRTFailure("Unexpected number of groups. Expected: %d and Found: %d" % (self.PREPARE_GPU_GROUPS, len(ggman.listGroupTypes())))

        log("Arranging Pool.")
        for sruuid in self.pools[1].master.minimalList("sr-list", "uuid", "shared=true"):
            try:
                self.pools[1].master.forgetSR(sruuid)
            except:
                pass
        self.pools[0].addHost(slave=self.pools[1].master, force=True)
        log("Sleep for a while to give the slave(s) restart toolstack.")
        xenrt.sleep(30)

        log("Obtaining current group info.")
        ggman.obtainExistingGroups()
        if (not len(ggman.listGroupTypes()) == self.INITIAL_GPU_GROUPS):
            raise xenrt.XRTFailure("Unexpected number of groups. Expected: %d and Found: %d" % (self.INITIAL_GPU_GROUPS, len(ggman.listGroupTypes())))

        self.setOneCardPerHost()
        ggman.obtainExistingGroups()

        phase = 0
        for variant in self.TEST_VARIANTS:
            log("Running Phase: %d" % (phase,))
            self.runTestPhase(variant)
        for guest, ostype in self._guestsAndTypes:
            guest.setState("DOWN")

class TCGPUGroupK1K2(VGPUGroupTestBase):

    """
    Pool of K1 + K2.
    add K1, remove K1. Add K2 remove K2.
    """
    pass

class TCGPUGroupK1K1(VGPUGroupTestBase):

    """
    Pool of K1 + K1.
    Add K1 remove K1.
    """
    POOL = [["K1"], ["K1"]]
    VGPU_CONFIG = [VGPUConfig.K100]
    PREPARE_GPU_GROUPS = 1
    INITIAL_GPU_GROUPS = 1
    TEST_VARIANTS = [
        {
            "VMs" : {VGPUConfig.K100: 5},
            "Distribution" : VGPUDistribution.BreadthFirst,
            "Result" : [1, 1, 1, 1, 1, 0, 0, 0]
        },
    ]

class TCGPUGroupK1NoVGPU(VGPUGroupTestBase):

    """
    Pool of K1 + no card.
    Pool both machine and remove no card machine.
    """
    POOL = [["K1"], [""]]
    VGPU_CONFIG = [VGPUConfig.K100]
    PREPARE_GPU_GROUPS = 1
    INITIAL_GPU_GROUPS = 1
    TEST_VARIANTS = [
        {
            "VMs" : {VGPUConfig.K100: 1, None: 1},
            "Distribution" : VGPUDistribution.BreadthFirst,
            "Result" : [1, 0, 0, 0] # 2 VMs started but only 1 of them has vgpu.
        },
    ]

class TCGPUGroupEmptyGroup(VGPUGroupTestBase):

    """
    Creating vgpu on empty group. Expected Failure.
    """
    POOL = [["K1"]]
    REQUIRED_DISTROS = [VGPUOS.Win7x86]

    def run(self, arglist):
        self.gpuGroupManager = GPUGroupManager(self.host)
        self.gpuGroupManager.obtainExistingGroups()

        log("Creating an empty group.")
        group = self.gpuGroupManager.createEmptyGroup()

        log("Creating a guest.")
        guest = self.cloneVM(self.getOSType(self.REQUIRED_DISTROS[0]))
        self._guestsAndTypes.append((guest, self.REQUIRED_DISTROS[0]))

        step("Configuring vGPUs onto created guest with the empty group.")
        step("Creating a vGPU on %s" % guest.getName())
        typeUUID= self.host.getSupportedVGPUTypes()["GRID K100"]
        log("GPU Group UUID: %s, Type UUID: %s" % (group.uuid, typeUUID))
        try:
            guest.createvGPU(group.uuid, typeUUID)
            self.safeStartGuest(guest)
            xenrt.sleep(60)
            guest.shutdown()
        except xenrt.XRTException as e:
            log("Failed to create vGPU with empty group.")
        else:
            raise xenrt.XRTFailure("Succeed to create a vGPU with empty group.")

class TCGPUGroupTiedConf(VGPUGroupTestBase):

    """
    Check gpu group tied with type of card once a vgpu with type created.
    """
    POOL = [["K1", "K2"]]
    REQUIRED_DISTROS = [VGPUOS.Win7x86]

    def run(self, arglist):
        log("Obtaining current group info.")
        self.gpuGroupManager = ggman = GPUGroupManager(self.host)
        ggman.obtainExistingGroups()

        log("Creating an empty group.")
        group = ggman.createEmptyGroup()

        gpu = src = dest = ""
        try:
            log("Moving a pgpu to empty group.")
            gpu = ggman.groups[0].gpuList[0]
            src = ggman.groups[0].uuid
            dest = group.uuid
            ggman.movePGPU(gpu, dest)

            log("Moving back to existing group.")
            src, dest = dest, src
            ggman.movePGPU(gpu, dest)
        except xenrt.XRTException as e:
            raise xenrt.XRTFailure("Faild to move a pgpu %s from group %s to group %s." % (gpu, src, dest))

        try:
            log("Moving a different type of pgpu into new group.")
            gpu = ggman.groups[1].gpuList[0]
            src = ggman.groups[1].uuid
            dest = group.uuid
            ggman.movePGPU(gpu, dest)
        except xenrt.XRTException as e:
            log("Failed to move. (Expected failure)")
        else:
            raise xenrt.XRTFailure("Succeed moving a pgpu %s from group %s to group %s after it had different type of pgpu." % (gpu, src, dest))

class TCGPUGroupMisc(VGPUGroupTestBase):
    """
    Checking actions with gpu groups.
    1. Creating a group
    2. Moving PGPUs to another group.
    3. Set new group PGPU enability.
    4. Destroying a group
    """
    POOL = [["K1"]]
    REQUIRED_DISTROS = [VGPUOS.Win7x86]
    VGPU_CONFIG = [VGPUConfig.K100, VGPUConfig.K140]

    def bindConfigurationToPGPU(self, conf, pgpu):
        typeuuid = self.vGPUCreator[conf].typeUUID()
        supportedTypes = [type.strip() for type in self.host.genParamGet('pgpu', pgpu, 'supported-VGPU-types').replace(" ", "").split(';')]
        if typeuuid in supportedTypes:
            self.host.genParamSet('pgpu', pgpu, 'enabled-VGPU-types', typeuuid)
        else:
            raise xenrt.XRTException("pgpu %s does not support %s (%s) configuration." % (pgpu, self.getConfigurationName(conf), typeuuid))

    def run(self, arglist):
        self.gpuGroupManager = ggman = GPUGroupManager(self.host)
        ggman.obtainExistingGroups()

        distro = self.getOSType(self.REQUIRED_DISTROS[0])
        novgpuguest = self.cloneVM(distro)
        self._guestsAndTypes.append((novgpuguest, self.REQUIRED_DISTROS[0]))

        self.safeStartGuest(novgpuguest)

        oldgroup = ggman.groups[0]
        newgroup = ggman.createEmptyGroup()
        ggman.movePGPU(oldgroup.gpuList[-1], newgroup.uuid)
        ggman.movePGPU(oldgroup.gpuList[-1], newgroup.uuid)

        novgpuguest.checkHealth()

        tiedpgpu= newgroup.gpuList[1]
        self.bindConfigurationToPGPU(VGPUConfig.K100, tiedpgpu)

        # Creating VMs with old group
        oldgroupguests = []
        oldgroupguests.append(self.cloneVM(distro))
        oldgroupguests.append(self.cloneVM(distro))
        self._guestsAndTypes.append((oldgroupguests[0], self.REQUIRED_DISTROS[0]))
        self._guestsAndTypes.append((oldgroupguests[1], self.REQUIRED_DISTROS[0]))
        self.configureVGPU(VGPUConfig.K140, oldgroupguests[0], oldgroup.uuid)
        self.configureVGPU(VGPUConfig.K140, oldgroupguests[1], oldgroup.uuid)

        # Creating VMs with new group.
        newgroupguests = []
        newgroupguests.append(self.cloneVM(distro))
        newgroupguests.append(self.cloneVM(distro))
        newgroupguests.append(self.cloneVM(distro))
        self._guestsAndTypes.append((newgroupguests[0], self.REQUIRED_DISTROS[0]))
        self._guestsAndTypes.append((newgroupguests[1], self.REQUIRED_DISTROS[0]))
        self._guestsAndTypes.append((newgroupguests[2], self.REQUIRED_DISTROS[0]))
        self.configureVGPU(VGPUConfig.K140, newgroupguests[0], newgroup.uuid)
        self.configureVGPU(VGPUConfig.K140, newgroupguests[1], newgroup.uuid)
        self.configureVGPU(VGPUConfig.K100, newgroupguests[2], newgroup.uuid)

        # start all vms.
        self.setDistributionMode(VGPUDistribution.BreadthFirst)
        for guest in oldgroupguests + newgroupguests:
            self.safeStartGuest(guest)

        # give some time to settle down.
        xenrt.sleep(30)

        # Trying moving pgpu while vgpu is attached and vm is running.
        # This should fail.
        try:
            ggman.movePGPU(newgroup.gpuList[0], oldgroup.uuid)
        except xenrt.XRTException as e:
            log("Failed to move a PGPU that has an allocated VGPU as expected.")
        else:
            raise xenrt.XRTFailure("Succeeded to move a PGPU that has an allocated VGPU.")

        # Trying deleting none empty group.
        # This should fail.
        try:
            ggman.destroyGroup(newgroup)
        except xenrt.XRTException as e:
            log("Failed to destroy a GPU group that has PGPUs as expected.")
        else:
            raise xenrt.XRTFailure("Succeeded to destroy a GPU group that has PGPUs.")

        for guest in newgroupguests:
            guest.shutdown()

        # give some time to settle down.
        xenrt.sleep(30)

        # Trying moving pgpu while vgpu is attached but vm is NOT running.
        try:
            ggman.mergeGroups(oldgroup, newgroup)
        except xenrt.XRTException as e:
            raise xenrt.XRTFailure("Failed to move a PGPU and delete the empty group.")
        else:
            log("Succeeded to move a PGPU and Destroyed the empty group.")

        # VMs should start well with the old group.
        self.configureVGPU(VGPUConfig.K140, newgroupguests[0], oldgroup.uuid)
        self.configureVGPU(VGPUConfig.K140, newgroupguests[1], oldgroup.uuid)
        self.configureVGPU(VGPUConfig.K100, newgroupguests[2], oldgroup.uuid)
        for guest in newgroupguests:
            self.safeStartGuest(guest)
###############################################################################################
#These classes are to automate Manual test environment
class TCinstallXDVDABrokerless(xenrt.TestCase):

    def run(self,arglist):

        vmName = None
        for arg in arglist:
            if arg.startswith('vmName'):
                vmName = arg.split('=')[1]

        if not vmName:
            raise xenrt.XRTError("VM Name not passed")

        g = self.getGuest(vmName)

        g.installXDVDABrokerLessConn()

class TCinstallNVIDIAHostDrivers(xenrt.TestCase):

    def run(self,arglist):

        hosts = self.getAllHosts()

        for host in hosts:
            host.installNVIDIAHostDrivers()

class TCinstallNVIDIAGuestDrivers(VGPUTest):

    def run(self,arglist):

        vmName = None
        for arg in arglist:
            if arg.startswith('vmName'):
                vmName = arg.split('=')[1]
            if arg.startswith('vgputype'):
                vgpuType = arg.split('=')[1]

        if not vmName:
            raise xenrt.XRTError("VM Name not passed")

        g = self.getGuest(vmName)
        g.installNvidiaVGPUDriver(self.driverType)
        self.assertvGPURunningInWinVM(g,self._CONFIGURATION[int(vgpuType)])

class TCcreatevGPU(VGPUAllocationModeBase):

    POOL = [["K1"]]
    REQUIRED_DISTROS = [VGPUOS.Win7x86]
    VGPU_CONFIG = [VGPUConfig.K120]

    def run(self,arglist):

        vgpuType = None
        startVM = "True"   #reason for being string is because we are getting string from seq file
        for arg in arglist:
            if arg.startswith('vgputype'):
                vgpuType = arg.split('=')[1]
            if arg.startswith('vmName'):
                vmName = arg.split('=')[1]
            if arg.startswith('distro'):
                self.REQUIRED_DISTROS[0] = int(arg.split('=')[1])
            if arg.startswith('startVM'):
                startVM = arg.split('=')[1]

        if not vmName:
            raise xenrt.XRTError("VM Name not passed")
        if not vgpuType:
            raise xenrt.XRTError("VGPU type not passed")

        g = self.getGuest(vmName)

        g.snapshot('beforevGPU')

        self.host = g.host

        step("Creating %d vGPUs configurations." % (len(self.VGPU_CONFIG),))
        self.vGPUCreator = {}
        self.vGPUCreator[int(vgpuType)] = VGPUInstaller(self.host, int(vgpuType))

        self.configureVGPU(int(vgpuType), g)
        if startVM == "True":
            g.setState("UP")

        g.snapshot('aftervGPU')

class TCcheckNvidiaDriver(xenrt.TestCase):
    """Sanity check to verify the NVIDIA driver is built correctly for the host kernel version"""

    def run(self, arglist):
        host = self.getDefaultHost()
        driverNotAvail = host.installNVIDIAHostDrivers(reboot=False,ignoreDistDriver=True)
        if not driverNotAvail:
            xenrt.TEC().logverbose("Driver not available in vGPU builder, so skipping the test")
            xenrt.TEC().skip("Driver not available in vGPU builder, so skipping the test")
            return
        try:
            host.execdom0("modprobe nvidia")
        except:
            # We expect this to fail if we run on a machine without NVIDIA hardware
            pass

        if host.execdom0("grep -e 'nvidia: disagrees about version of symbol' -e 'nvidia: Unknown symbol' /var/log/kern.log", retval="code") == 0:
            raise xenrt.XRTFailure("NVIDIA driver is not correctly built for the current host kernel")

