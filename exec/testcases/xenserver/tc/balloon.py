#
# XenRT: Test harness for Xen and the XenServer product family
#
# Dynamic Memory Control (ballooning) test cases
#
# Copyright (c) 2009 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import xenrt, re, time, os, os.path, string, random, math, operator
from xenrt.lazylog import step, log

class _BalloonPerfBase(xenrt.TestCase):
    """Base class for balloon driver performance tests"""
    FAIL_BELOW = 0.1 # GiB/Ghz/s
    DISTRO = "winxpsp3"
    ARCH = "x86-32"
    SET_PAE = True
    LIMIT_TO_30GB = True
    HAP = "NPT"

    def __init__(self, tcid=None):
        self.WINDOWS = self.DISTRO.startswith("w") or self.DISTRO.startswith("v")
        xenrt.TestCase.__init__(self, tcid=tcid)

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        
        self.parseArgs(arglist)
        
        step("Install Guest")
        self.guest = self.installGuest()
        self.uninstallOnCleanup(self.guest)
        self.getLogsFrom(self.guest)
        log("Guest Installation complete")
        
        self.guest.shutdown()

        maxmem = int(self.host.lookup(["GUEST_LIMITATIONS", self.DISTRO, "MAXMEMORY"], self.host.lookup("MAX_VM_MEMORY", "32768")))
        if not self.SET_PAE and maxmem > 4096:
            maxmem = 4096
        if self.LIMIT_TO_30GB and maxmem > 30720:
            maxmem = 30720
        self.maxMiB = maxmem
        xenrt.TEC().comment("max = %d GiB" % (self.maxMiB / xenrt.KILO))
        self.minMiB = maxmem / 4
        xenrt.TEC().comment("min = %d GiB" % (self.minMiB / xenrt.KILO))
        self.widthGiB = (self.maxMiB - self.minMiB) / xenrt.KILO
        xenrt.TEC().comment("width = %d GiB" % (self.widthGiB))
        self.frequency = self.host.getMemorySpeed()
        xenrt.TEC().comment("frequency = %d GHz" % (float(self.frequency) / 1000))

    def run(self, arglist=None):
        self.guest.setMemoryProperties(None, self.minMiB, self.minMiB, self.maxMiB)
        self.guest.start()
        time.sleep(60)
        cli = self.guest.getCLIInstance()

        durationExpanding = {}
        durationSqueezing = {}
        for i in range(10):
            t0 = xenrt.util.timenow(float=True)
            args = []
            args.append("uuid=%s" % (self.guest.getUUID()))
            args.append("min=%sMiB" % (self.maxMiB))
            args.append("max=%sMiB" % (self.maxMiB))
            cli.execute("vm-memory-dynamic-range-set", string.join(args))
            self.guest.waitForTarget(600)
            t1 = xenrt.util.timenow(float=True)
            time.sleep(10)
            t2 = xenrt.util.timenow(float=True)
            args = []
            args.append("uuid=%s" % (self.guest.getUUID()))
            args.append("min=%sMiB" % (self.minMiB))
            args.append("max=%sMiB" % (self.minMiB))
            cli.execute("vm-memory-dynamic-range-set", string.join(args))
            self.guest.waitForTarget(600)
            t3 = xenrt.util.timenow(float=True)

            durationExpanding[i] = round(t1 - t0, 2)
            durationSqueezing[i] = round(t3 - t2, 2)

        self.guest.shutdown()
        self.guest.setMemoryProperties(None, self.maxMiB, self.maxMiB, self.maxMiB)
        self.guest.start()
        time.sleep(60)

        for i in range(10,20):
            t0 = xenrt.util.timenow(float=True)
            args = []
            args.append("uuid=%s" % (self.guest.getUUID()))
            args.append("min=%sMiB" % (self.minMiB))
            args.append("max=%sMiB" % (self.minMiB))
            cli.execute("vm-memory-dynamic-range-set", string.join(args))
            self.guest.waitForTarget(600)
            t1 = xenrt.util.timenow(float=True)
            time.sleep(10)
            t2 = xenrt.util.timenow(float=True)
            args = []
            args.append("uuid=%s" % (self.guest.getUUID()))
            args.append("min=%sMiB" % (self.maxMiB))
            args.append("max=%sMiB" % (self.maxMiB))
            cli.execute("vm-memory-dynamic-range-set", string.join(args))
            self.guest.waitForTarget(600)
            t3 = xenrt.util.timenow(float=True)

            durationSqueezing[i] = round(t1 - t0, 2)
            durationExpanding[i] = round(t3 - t2, 2)

        self.guest.shutdown()

        durExpStr = ""
        for v in durationExpanding.values():
            durExpStr += ", %.2f" % (v)
        durExpStr = durExpStr[2:]
        durSqStr = ""
        for v in durationSqueezing.values():
            durSqStr += ", %.2f" % (v)
        durSqStr = durSqStr[2:]

        xenrt.TEC().logverbose("Durations expanding: %s" % (durExpStr))
        xenrt.TEC().logverbose("Durations squeezing: %s" % (durSqStr))
        expandingMax = max(durationExpanding.values())
        squeezingMax = max(durationSqueezing.values())
        durationMax = max(expandingMax, squeezingMax)
        index = float(self.widthGiB) / (float(self.frequency) / 1000) / float(durationMax)
        index = round(index, 3)

        xenrt.TEC().value("index", index, "GiB/GHz/s")
        if index < self.FAIL_BELOW:
            raise xenrt.XRTFailure("Balloon driver performance index less than %s GiB/Ghz/s" % (self.FAIL_BELOW),
                                   data="Calculated index %s GiB/Ghz/s" % (index))
    
    def parseArgs(self, arglist):
        if arglist and len(arglist) > 0:
            for arg in arglist:
                l = string.split(arg, "=", 1)
                if l[0] == "DISTRO":
                    self.DISTRO = l[1]
                    self.WINDOWS = self.DISTRO.startswith("w") or self.DISTRO.startswith("v")
                if l[0] == "HAP":
                    self.HAP = l[1]
                if l[0] == "DO_LIFECYCLE_OPS":
                    self.DO_LIFECYCLE_OPS = l[1]
                if l[0] == "LIMIT_TO_30GB":
                    self.LIMIT_TO_30GB = l[1]
        (self.DISTRO, self.ARCH) = xenrt.getDistroAndArch(self.DISTRO)
    
    def installGuest(self):
        # Set up the VM
        guest = self.getGuest(self.DISTRO+self.ARCH)
        if guest:
            return guest
        if self.WINDOWS:
            guest = self.host.createGenericWindowsGuest(distro=self.DISTRO, 
                                                        arch=self.ARCH, vcpus=2)
            if self.SET_PAE:
                guest.forceWindowsPAE()
        else:
            guest = self.host.createBasicGuest(distro=self.DISTRO,
                                               arch=self.ARCH)
        return guest

class _BalloonSmoketest(_BalloonPerfBase):
    """Base class for balloon driver smoketests and max range tests"""
    DISTRO = "w2k3eesp1"
    WORKLOADS = ["Prime95"]
    DO_LIFECYCLE_OPS = False
    LIMIT_TO_30GB = True
    ITERATIONS = 1
    SET_PAE = True
    HOST = "RESOURCE_HOST_0"
    HAP = None
    LOW_MEMORY = 750

    def prepare(self, arglist=None):
        # Get the host
        self.host = self.getHost(self.HOST)
        self.parseArgs(arglist)
        
        if self.HAP:
            # Check this is the right sort of host
            # XXX: At the moment we can only check if it's Intel or AMD - we
            # need a way to check if its EPT or NPT!
            if not self.HAP in ["NPT", "EPT"]:
                raise xenrt.XRTError("Unknown HAP type %s" % (self.HAP))

            if self.HAP == "NPT" and not self.host.isSvmHardware():
                raise xenrt.XRTError("Attempting to test NPT but not running on"
                                     " AMD hardware")
            elif self.HAP == "EPT" and not self.host.isVmxHardware():
                raise xenrt.XRTError("Attempting to test EPT but not running on"
                                     " Intel hardware")

        step("Sleeping to let host memory free settle...")
        time.sleep(30)
        self.hostMemory = int(self.host.paramGet("memory-free")) / xenrt.MEGA
        xenrt.TEC().logverbose("...done")
        
        step("Install Guest")
        self.guest = self.installGuest()
        self.uninstallOnCleanup(self.guest)
        self.getLogsFrom(self.guest)
        log("Guest Installation complete")

        step("Install Workloads")
        if len(self.WORKLOADS) > 0:
            self.guest.installWorkloads(self.WORKLOADS)
        self.guest.shutdown()

        step("Find the min and max supported memory for this distro")
        minmem = self.host.lookup("MIN_VM_MEMORY")
        minmem = int(xenrt.TEC().lookup(["GUEST_LIMITATIONS", self.DISTRO, "MINMEMORY"], minmem))
        self.minSupported = int(self.host.lookup(["VM_MIN_MEMORY_LIMITS", self.DISTRO], minmem))
        self.minStaticSupported = int(xenrt.TEC().lookup(["GUEST_LIMITATIONS", self.DISTRO, "STATICMINMEMORY"], self.minSupported))
        max = self.host.lookup("MAX_VM_MEMORY")
        self.maxSupported = int(xenrt.TEC().lookup(["GUEST_LIMITATIONS", self.DISTRO, "MAXMEMORY"], max))
        if not self.SET_PAE and self.maxSupported > 4096:
            self.maxSupported = 4096

        # If the max is 32GB, then drop it to 30GB/(max available memory) so we can fit on a 32GB host
        if self.LIMIT_TO_30GB and self.maxSupported > 30720:
            xenrt.TEC().comment("Limiting test to 30GB...")
            freemem = self.host.getFreeMemory()
            availablemem = freemem - self.host.predictVMMemoryOverhead(freemem, False)
            self.maxSupported = min(30720, availablemem )
        log("Minimum Supported memory =  %d" % (self.minSupported))
        log("Maximum Supported memory =  %d" % (self.maxSupported))

        # Check if we've been asked to apply a cap
        cap = xenrt.TEC().lookup("DMC_MEMORY_CAP_MIB", None)
        if cap:
            capto = int(cap)
            if self.maxSupported > capto:
                xenrt.TEC().warning("Capping test at %uMiB..." % (capto))
                self.maxSupported = capto

        step("Look up the dynamic range multiplier")
        if self.WINDOWS:
            lookup = "WIN"
        else:
            lookup = "LINUX"
        self.dmcPercent = int(self.host.lookup("DMC_%s_PERCENT" % (lookup)))
        self.dmcPercent = int(xenrt.TEC().lookup("DMC_%s_PERCENT" % (lookup), self.dmcPercent))
        log("Dynamic Range Multiplies = %s" % (self.dmcPercent))

    def run(self, arglist=None):
        # VMs have a limitation on the range they can balloon over
        # specified by the dmc multiplier
        step("Testing max supported range starting at "
                               "minimum supported RAM...")
        if self.runSubcase("runCase", (self.minSupported,
                                       self.minSupported * 100 / self.dmcPercent, "min"),
                           "MaxRange", "Min") != xenrt.RESULT_PASS:
            if self.runSubcase("recoverGuest", (), "GuestRecover", "Min") != \
               xenrt.RESULT_PASS:
                xenrt.TEC().logverbose("Unable to recover guest, other tests blocked.")
                return

        step("Trying max supported range centred over median "
                               "supported RAM...")
        midpoint = self.minSupported + ((self.maxSupported - self.minSupported) / 2)
        min = midpoint * 2 * self.dmcPercent / (100 + self.dmcPercent)
        max = min * 100 / self.dmcPercent
        if self.runSubcase("runCase", (min, max, "mid"), "MaxRange", "Mid") != \
           xenrt.RESULT_PASS:
            if self.runSubcase("recoverGuest", (), "GuestRecover", "Mid") != \
               xenrt.RESULT_PASS:
                xenrt.TEC().logverbose("Unable to recover guest, other tests blocked.")
                return

        step("Testing max supported range ending at maximum "
                               "supported RAM...")
        if self.runSubcase("runCase", (self.maxSupported * self.dmcPercent / 100,
                                       self.maxSupported, "max"), "MaxRange",
                           "Max") != xenrt.RESULT_PASS:
            xenrt.TEC().logverbose("Not checking static-min due to Max failure")
            return

        step("Verify that static-min is equal to the min supported RAM")
        self.runSubcase("checkStaticMin", (), "Verify", "StaticMin")

    def preLogs(self):
        # If it's shutdown, start it so we try and collect logs
        if self.guest and self.guest.getState() == "DOWN":
            xenrt.TEC().logverbose("Attempting to start guest for log collection")
            try:
                self.guest.start()
            except:
                pass

    def checkStaticMin(self):
        smin = int(self.guest.paramGet("memory-static-min")) / xenrt.MEGA
        if smin != self.minStaticSupported:
            raise xenrt.XRTFailure("memory-static-min does not equal minimum supported RAM",
                                   data="Expecting %dMiB, found %dMiB" % (self.minStaticSupported, smin))
        else:
            log("memory-static-min is equal to minimum supported RAM = %d" % (smin))


    def runCase(self, min, max, type):
        success = 0
        try:
            for i in range(self.ITERATIONS):
                step("Starting iteration %u/%u..." % (i+1, self.ITERATIONS))
                self.status = "fail"
                self.runCaseInner(min, max, ((i+1) == self.ITERATIONS))
                xenrt.TEC().logverbose("...done")
                success += 1
                if xenrt.GEC().abort:
                    xenrt.TEC().warning("Aborting on command")
                    break
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" % (success, self.ITERATIONS))
            if self.WINDOWS:
                if not self.SET_PAE:
                    arch = "noPAE"
                else:
                    arch = ""
            else:
                arch = self.ARCH
            logString = "DMCEnvelope,%s,%s,1,%s,%s," % (self.DISTRO, arch, max, self.dmcPercent)
            if success == self.ITERATIONS:
                self.status = "pass"
            else:
                step("Trigger a debug dump from the VM and give it some time to dump")
                if isinstance(self.host, xenrt.lib.xenserver.DundeeHost):
                    self.host.execdom0("xl debug-keys q")
                else:
                    self.host.execdom0("/opt/xensource/debug/xenops debugkeys q")
                time.sleep(30)
            logString += self.status
            logString += ",%s" % (type)
            xenrt.TEC().appresult(logString)
            

    def runCaseInner(self, minMem, maxMem, doLifecycleOps):
        try:
            step("Set dynamic-min=dynamic-max=min, static-max=max")
            self.guest.setMemoryProperties(None, minMem, minMem, maxMem)

            self.guest.start()
            self.guest.checkMemory(inGuest=True)
            self.status = "booted"

            step("Check the target has been met correctly")
            self.guest.waitForTarget(60, desc="Not at target immediately after boot")
            
            #These changes are added for EXT-119
            step("Check by what how much value can we balloon up/down the VM")
            stepSize = min((maxMem-minMem),9*self.LOW_MEMORY)
            log("Step size = %d" % stepSize)
            
            for i in range(3):
                step("Verify VM can balloon up to smax")
                memStep = minMem
                while memStep+stepSize < maxMem:
                    memStep = memStep + stepSize
                    self.guest.setDynamicMemRange(memStep, memStep)
                    self.guest.waitForTarget(800)
                    time.sleep(10)
                    self.guest.checkMemory(inGuest=True)
                self.guest.setDynamicMemRange(maxMem, maxMem)
                
                self.guest.waitForTarget(800)
                time.sleep(10)
                self.guest.checkMemory(inGuest=True)
                
                step("Verify it can balloon down to min")
                memStep = maxMem
                xenrt.TEC().logverbose(memStep)
                while memStep-stepSize > minMem:
                    memStep = memStep - stepSize
                    self.guest.setDynamicMemRange(memStep, memStep)
                    self.guest.waitForTarget(800)
                    time.sleep(10)
                    self.guest.checkMemory(inGuest=True)
                self.guest.setDynamicMemRange(minMem, minMem)
                
                self.guest.waitForTarget(800)
                time.sleep(10)
                self.guest.checkMemory(inGuest=True)

            
            # Are we meant to do lifecycle ops
            if self.DO_LIFECYCLE_OPS and doLifecycleOps:
                self.guest.setDynamicMemRange(minMem, maxMem)
                self.lifecycleOps(minMem)

            self.guest.shutdown()
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose("Caught XRTFailure...")
            #check for CA-99236 kind of failure
            #The problem is that windows is being told it has 1024 MiB of memory and so it is allocating non-pageable memory...
            #...pools based on that. If it decides to allocate more than 256 Mib to non-pageable memory(or other areas of...
            #...memory the ballooning driver does not control) then we are always going to run into problems...
            #...Windows is behaving perfectly reasonably and ballooning driver cannot...
            #...handle this situation. So modying testcase to handle this failure if it happens.
            #Change Dynamic Min to 512 and re-run the subcase.
            if self.DISTRO in ["winxpsp3", "w2k3eesp2"] and minMem == 256 and "Domain running but not reachable" in str(e):
                self.minSupported = 512
                xenrt.TEC().warning("unable to balloon so low... changing min to 512MiB")
                # Windows VMs have a limitation on the range they can balloon over
                xenrt.TEC().logverbose("Testing max supported range starting at "
                               "minimum supported RAM again...")
                try:
                    self.guest.shutdown(force=True)
                except:
                    pass
                if self.runSubcase("runCase", (self.minSupported,
                                    self.minSupported * 100 / self.dmcPercent, "min"),
                           "MaxRange", "Min- New Dynamic Min") != xenrt.RESULT_PASS:
                    if self.runSubcase("recoverGuest", (), "GuestRecover", "Min") != \
                        xenrt.RESULT_PASS:
                        xenrt.TEC().logverbose("Unable to recover guest, other tests blocked.")
                        return
                pass
            #EXT-119- The product is behaving as intended. It initiates its side of the contract 
            # which is to write a memory target for the VM to Xenstore. 
            #If the guest doesn't manage to comply with this target for any of many reasons 
            #(ranging from too busy, crashed guest, malicious guest, buggy balloon driver)
            #then the product marks the guest as uncooperative
            #Check for uncooperative tag, if found shut down the VM, print the details and proceed with the test
            elif "Target not reached within timeout" in str(e):
                res = self.host.execdom0("xenstore-ls -pf | grep memory | grep -E 'uncoop'")
                if res and "uncooperative" in res:
                    log("Caught failure: %s" % str(e))
                    log("Guest marked uncooperative")
                    log("Shut down the guest")
                    try:
                        self.guest.shutdown(force=True)
                    except:
                        pass
                else:
                    raise
            else:
                raise
               

    def lifecycleOps(self, min):
        step("Perform Lifecycle operations on the VM")
        self.guest.shutdown()
        self.guest.start()
        self.guest.reboot()
        self.guest.suspend()
        self.guest.resume()
        # We can only do a migrate if the dynamic-min is < half the hosts memory
        if min < (self.hostMemory / 2):
            # Sleep 60s before migrating the VM (CA-165995)
            xenrt.sleep(60)
            self.guest.migrateVM(self.host, live="true")
        xenrt.TEC().logverbose("...done")

    def recoverGuest(self):
        step("Attempting to recover a guest from a potentially crashed / failed state...")
        try:
            self.guest.shutdown(force=True)
        except:
            pass
        val = max(self.minSupported, 1024)
        self.guest.setMemoryProperties(None, val, val, val)
        try:
            self.guest.start()
        except:
            raise xenrt.XRTFailure("Unable to recover guest after previous failure")
        
        self.guest.shutdown()
        xenrt.TEC().logverbose("Guest recovered.")

class _P2VBalloonSmoketest(_BalloonSmoketest):
    """Base class for P2V Balloon Smoketests"""
    WORKLOADS = ["LinuxSysbench"]
    HOST = "RESOURCE_HOST_1"

    def installGuest(self):
        # We assume that the default host is the target host, and that
        # RESOURCE_HOST_0 is the native host
        mname = xenrt.TEC().lookup("RESOURCE_HOST_0")
        m = xenrt.PhysicalHost(mname)
        xenrt.GEC().startLogger(m)
        self.p2vhost = xenrt.lib.native.NativeLinuxHost(m)
        self.p2vhost.installLinuxVendor(self.DISTRO)

        guest = self.host.p2v(xenrt.randomGuestName(),
                              self.DISTRO,
                              self.p2vhost)

        return guest

    """Windows 2008 R2 SP1 x64 balloon driver performance test"""
    DISTRO = "ws08r2sp1-x64"

#
# Linux VM Balloon Driver Performance Tests (primary OS's)
#
class _LinuxBalloonPerfBase(_BalloonPerfBase):
    WORKLOADS = ["LinuxSysbench"]

class TCLinuxBalloonPerf(_LinuxBalloonPerfBase):
    """Linux balloon driver performance test"""
    pass

#
# Windows VM Balloon Driver Performance Tests
#
class TCWindowsBalloonPerf(_BalloonPerfBase):
    """Windows balloon driver performance test"""
    pass


#
# Linux VM Balloon Driver Driver Max range tests
#
class _MaxRangeBase(_BalloonSmoketest):
    """Base class for max range testcases"""
    DO_LIFECYCLE_OPS = True
    ITERATIONS = 3

class _LinuxMaxRangeBase(_MaxRangeBase):
    WORKLOADS = ["LinuxSysbench"]

class TCLinuxMaxRange(_LinuxMaxRangeBase):
    """Linux VM operations with maximum dynamic range"""
    pass
    
#
# Windows VM Balloon Driver Max range tests
#
class TCWindowsMaxRange(_MaxRangeBase):
    """Windows max range test"""
    ITERATIONS = 1

#
# VM Insatalltion test
#
class TCVmInstallation(xenrt.TestCase):
    """Install VMs passed as distros"""
    def run(self, arglist=[]):
        step("Installing Guests in parallel")
        distros = xenrt.TEC().lookup("DISTROS").split(",")
        self.host = self.getDefaultHost()
        pTasks = [xenrt.PTask(self.installGuest,distroName=d) for d in distros]
        xenrt.TEC().logverbose("Guest installation pTasks are %s" % pTasks)
        xenrt.pfarm(pTasks)

    def installGuest(self, distroName):
        # Set up the VM
        (distro, arch) = xenrt.getDistroAndArch(distroName)
        if distro.startswith("w") or distro.startswith("v"):
            guest = self.host.createGenericWindowsGuest(distro=distro, 
                                                        arch=arch, vcpus=2, name=distro+arch)
        else:
            guest = self.host.createBasicGuest(distro=distro,
                                               arch=arch, name=distro+arch)


class TC9284(xenrt.TestCase):
    """Perform a set of lifecycle operations on an overcommitted host"""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guests = []
        # Ensure the host is overcommitted
        # We want to arrange a set of VMs with a dynamic range of 256-768MB
        # We need enough that the sum of dyn-max is greater than host memory
        hostMemory = int(self.host.paramGet("memory-total")) / xenrt.MEGA
        guestsNeeded = hostMemory / 1024
        # We'll get one extra as we use the template guest

        templateGuest = self.host.createGenericLinuxGuest(memory=1024)
        self.uninstallOnCleanup(templateGuest)
        templateGuest.setDynamicMemRange(256, 1024)
        templateGuest.preCloneTailor()
        templateGuest.shutdown()
        self.guests.append(templateGuest)        
        for i in range(guestsNeeded):
            g = templateGuest.cloneVM()
            self.uninstallOnCleanup(g)
            self.guests.append(g)
        # Start them up
        for g in self.guests:
            g.start()        

        # Verify we have the required conditions
        dynMinSum = 0
        dynMaxSum = 0
        overheadSum = 0
        for g in self.guests:
            if g.getState() == "UP":
                dynMinSum += int(g.paramGet("memory-dynamic-min"))
                dynMaxSum += int(g.paramGet("memory-dynamic-max"))
                overheadSum += int(g.paramGet("memory-overhead"))
        # Add the control domain
        cd = self.host.getMyDomain0UUID()
        if isinstance(self.host, xenrt.lib.xenserver.TampaHost):
            # In Tampa, Dom0 uses static-max
            dynMinSum += int(self.host.genParamGet("vm", cd, "memory-static-max"))
            dynMaxSum += int(self.host.genParamGet("vm", cd, "memory-static-max"))
        else: 
            dynMinSum += int(self.host.genParamGet("vm", cd, "memory-dynamic-min"))
            dynMaxSum += int(self.host.genParamGet("vm", cd, "memory-dynamic-max"))
        overheadSum += int(self.host.genParamGet("vm", cd, "memory-overhead"))
        overheadSum += int(self.host.paramGet("memory-overhead"))
        self.dynMinSum = dynMinSum
        self.dynMaxSum = dynMaxSum
        self.overheadSum = overheadSum
        if dynMaxSum <= int(self.host.paramGet("memory-total")):
            raise xenrt.XRTError("Host is not overcommitted")
        if int(self.host.paramGet("memory-free")) / xenrt.MEGA > 10:
            raise xenrt.XRTError("Overcommitted host reports >10MB free "
                                 "memory")


        # Check we can fit the test VM in at its dyn-min (twice, as we're going
        # to migrate it)
        if (dynMinSum + (2*1024*xenrt.MEGA)) > int(self.host.paramGet("memory-total")):
            raise xenrt.XRTError("Host is too overcommitted")

        # Install our VM (use XP SP3 as it will fit in the memory range we want,
        # unlike 2008.
        self.guest = self.host.createGenericWindowsGuest(start=False,
                                                         distro="win7sp1-x86")
        self.uninstallOnCleanup(self.guest)
        self.guests.append(self.guest)
        # Set its parameters
        self.guest.setStaticMemRange(1024, 2048)
        self.guest.setDynamicMemRange(1280, 1792)
        self.guest.setStaticMemRange(1280, 1792)

    def run(self, arglist=None):
        tests = ["start","shutdown","forceShutdown","reboot","forceReboot",
                 "migrate","suspend","resume",
                 "susresNoncoop","suspendForceShutdown","static",
                 "dynamic","migrateNoncoop"]
        for t in tests:
            r = self.runSubcase(t, (), "TC9284", t)
            if r != xenrt.RESULT_PASS and r != xenrt.RESULT_SKIPPED:
                return

    def start(self):
        # Start
        self.guest.start()
        self.checkMemory(True)

    def shutdown(self):
        # Shutdown
        self.guest.shutdown()
        self.checkMemory(False)

    def forceShutdown(self):
        # Force Shutdown
        self.guest.start()
        self.checkMemory(True)
        self.guest.shutdown(force=True)
        self.checkMemory(False)        

    def reboot(self):
        # Reboot
        self.guest.start()
        self.checkMemory(True)
        self.guest.reboot()
        self.checkMemory(True)

    def forceReboot(self):
        # Force reboot
        self.guest.reboot(force=True)
        self.checkMemory(True)

    def migrate(self):
        # Migrate
        self.guest.migrateVM(self.host, live="true")
        self.checkMemory(True)

    def migrateNoncoop(self):
        # Make the guest non cooperative
        
        self.guest.makeCooperative(False)
        try:
            self.guest.migrateVM(self.host, live="true")
        except Exception, e:
            #CA-148483 workaround
            if "VM didn't acknowledge the need to shutdown" in str(e) or "Failed_to_acknowledge_shutdown_request" in str(e):
                xenrt.TEC().logverbose("Migration failed as expected")
                try:
                    if self.guest.getState() == "UP":
                        self.guest.lifecycleOperation("vm-reboot", force=True)
                    else:
                        self.guest.lifecycleOperation("vm-start")
                except:
                    #Start the VM if vm-reboot fails because VM went down before vm-reboot
                    self.guest.lifecycleOperation("vm-start")
            else:
                raise
        finally:
            self.guest.makeCooperative(True)
            time.sleep(30)
            self.checkMemory(True)

    def suspend(self):
        # Suspend
        self.guest.suspend()
        self.checkMemory(False)

    def resume(self):
        # Resume
        self.guest.resume()
        self.checkMemory(True)

    def susresNoncoop(self):
        # Make the guest non cooperative
        self.guest.makeCooperative(False)
        self.guest.suspend()
        self.guest.resume()
        self.guest.makeCooperative(True)
        time.sleep(5)
        self.checkMemory(True)

    def suspendForceShutdown(self):
        # Force shutdown while suspended
        self.guest.suspend()
        self.checkMemory(False)
        self.guest.shutdown(force=True)
        self.checkMemory(False)

    def hibernate(self):
        if not self.guest.windows:
            raise xenrt.XRTSkip("Hibernate is only valid for Windows Guests")

        # Start the guest
        self.guest.start()
        # Set a dynamic range
        self.guest.setDynamicMemRange(512, 512)
        self.guest.waitForTarget(600)

        # Hibernate it
        self.guest.hibernate()
        # Start it again
        self.guest.start()

        self.guest.checkMemory(inGuest=True)
        # Verify memory-actual is within 1% of memory-target
        actual = self.guest.getMemoryActual() / xenrt.MEGA
        target = self.guest.getMemoryTarget() / xenrt.MEGA
        difference = abs(actual - target)
        if difference > 4:            
            raise xenrt.XRTFailure("Windows VM resumed from hibernate did not "
                                   "return memory to Xen correctly")

    def static(self):
        # Changing static memory properties
        # Check ordering invariant enforced
        for min,max in [(600,1024),(128,1600),(1600,256)]:
            try:
                self.guest.setStaticMemRange(min, max)
            except:
                pass
            else:
                raise xenrt.XRTFailure("Allowed to set static memory range to "
                                       "invalid values %d-%d with dynamic "
                                       "range of 1280-1792 MB" % (min,max))
        # Check with valid values
        self.guest.setStaticMemRange(1024, 2048)
        # Check for invalid powerstate message
        self.guest.start()
        self.checkMemory(True)
        try:
            self.guest.setStaticMemRange(128, 1024)
        except:
            pass
        else:
            raise xenrt.XRTFailure("Able to set static memory range with VM "
                                   "running")
        self.guest.suspend()
        self.checkMemory(False)
        try:
            self.guest.setStaticMemRange(512, 2560)
        except:
            pass
        else:
            raise xenrt.XRTFailure("Able to set static memory range with VM "
                                   "suspended")
        self.guest.resume()
        self.checkMemory(True)

    def dynamic(self):
        # Changing dynamic memory properties
        # Check ordering invariant enforced
        for min,max in [(512, 1536),(1280,2560),(2048,1536)]:
            try:
                self.guest.setDynamicMemRange(min, max)
            except:
                pass
            else:
                raise xenrt.XRTFailure("Allowed to set dynamic memory range to "
                                       "invalid values %d-%d with static range "
                                       "of 1024-2048 MB" % (min,max))
        # Check with valid values
        self.guest.setDynamicMemRange(1152, 1920)
        self.checkMemory(True)
        # Check only allowed if sum of dynamic-min's and overheads is less than host memory
        #---remvoing this code as it need some changes---
        #----TC set static max above recommended limit causing problem in TC-----
        #minToUse = int(self.host.paramGet("memory-total")) - self.dynMinSum - self.overheadSum
        #minToUseMB = (minToUse / xenrt.MEGA) + 1
        #if minToUseMB > 1024:
        #    self.guest.shutdown()
        #    self.guest.setStaticMemRange(None, minToUseMB)
        #    initialdynminmax = minToUseMB / 3
        #    self.guest.setDynamicMemRange(initialdynminmax,initialdynminmax)
        #    self.guest.start()
        #try:
        #    self.guest.setDynamicMemRange(minToUseMB, minToUseMB)
        #except:
        #    pass
        #else:
        #    raise xenrt.XRTFailure("Allowed to set dynamic-min such that sum "
        #                           "of dynamic-mins is > host memory")

    def checkMemory(self, running):
        # Check the targets of all VMs are set appropriately
        # First sleep for 35 seconds to allow VMs to reach targets and RRDs to
        # update
        time.sleep(240)

        # Work out the host compression ratio, this can be approximated to:
        # r * (sum of dyn-mins) + (1-r) * (sum of dyn-maxs) = host total
        # memory - sum of host and VM overheads
        # i.e. r = (T - X - sum of dyn-maxs)/(sum of dyn-mins - sum of dyn-maxs)
        dynMinSum = self.dynMinSum
        dynMaxSum = self.dynMaxSum
        overheadSum = self.overheadSum
        if running:
            dynMinSum += int(self.guest.paramGet("memory-dynamic-min"))
            dynMaxSum += int(self.guest.paramGet("memory-dynamic-max"))
            overheadSum += int(self.guest.paramGet("memory-overhead"))
        total = int(self.host.paramGet("memory-total"))
        r = float(total - overheadSum - dynMaxSum)/float(dynMinSum - dynMaxSum)
        xenrt.TEC().logverbose("Compression ratio r = (mem-total - sum of overhead - sum of dynamic-max) / (sum of dynamic min - sum of dynamic max)")
        xenrt.TEC().logverbose("(%d - %d - %d) / (%d - %d) = %f" % (total, overheadSum, dynMaxSum, dynMinSum, dynMaxSum, r))

        # For each VM, work out what we think its target should be
        for g in self.guests:
            if g == self.guest and not running:
                continue
            dmin = int(g.paramGet("memory-dynamic-min"))
            dmax = int(g.paramGet("memory-dynamic-max"))
            expectedTarget = int(r * dmin + (1-r) * dmax)
            actualTarget = g.getMemoryTarget()
            difference = abs(expectedTarget - actualTarget)
            if difference > (30 * xenrt.MEGA):
                raise xenrt.XRTFailure("Found unexpected memory-target",
                                       data="Expecting ~%d MB, found %d MB for "
                                            "VM %s" % 
                                            ((expectedTarget/xenrt.MEGA),
                                             (actualTarget/xenrt.MEGA),
                                             g.getName()))

            # Check memory-actual is within range of memory-target
            actual = g.getMemoryActual()
            difference = abs(actual - actualTarget)
            if difference > (20 * xenrt.MEGA):
                raise xenrt.XRTFailure("Found VM with actual memory usage >8MB "
                                       "from target",
                                       data="Target %d MB, actual %d MB" %
                                            ((actualTarget/xenrt.MEGA),
                                             (actual/xenrt.MEGA)))


class TC11576(xenrt.TestCase):
    """Perform a set of lifecycle and DMC operations on Linux VM"""

    TIME_TO_SLEEP = 60

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericLinuxGuest()
        self.guest.shutdown()
        self.guest.setStaticMemRange(128, 1024)
        self.uninstallOnCleanup(self.guest)
        self.guest.start()
    
        
    def testMemoryFields(self):
        
        # At this point we expect the memory (from RRD) of the VM
        # to be stable. 

        mem_RRD_1 = self.guest.getMemoryActual(fromRRD=True) / xenrt.MEGA
        time.sleep(10)
        mem_RRD_2 = self.guest.getMemoryActual(fromRRD=True) / xenrt.MEGA
        mem_actual = self.guest.getMemoryActual(fromRRD=False) / xenrt.MEGA
        
        if mem_RRD_1 == mem_RRD_2:
            if mem_RRD_2 == mem_actual:
                return True
            else:
                xenrt.TEC().logverbose("mem_RRD_1(%s) mem_RRD_2(%s) mem_actual(%s)"
                                       % (mem_RRD_1, mem_RRD_2, mem_actual))
                return False
        else:
            xenrt.TEC().logverbose("mem_RRD_1(%s) mem_RRD_2(%s) mem_actual(%s)"
                                   % (mem_RRD_1, mem_RRD_2, mem_actual))
            return False


    def waitForVMMemoryToSettle(self, new_value):
        
        # We'll wait for 10 mins ... atmost!!!
        for j in range(10):
            mem_RRD = self.guest.getMemoryActual(fromRRD=True) / xenrt.MEGA
            if mem_RRD != new_value and j == 9:
                raise xenrt.XRTFailure("memory (from RRD) is not yet updated after 10 mins")
            elif mem_RRD == new_value:
                break
            else:
                time.sleep(self.TIME_TO_SLEEP)


    def run(self, arglist=None):
        # The Purpose of the test is to verify that memory-actual is updated
        # "eventually" with the value from RRD

        xenrt.TEC().logverbose("""Perform a set of lifecycle and DMC operations on Linux VM""")
        
        for i in range(10):
            # self.guest.checkMemory()
            self.guest.setDynamicMemRange(512, 512)
            time.sleep(self.TIME_TO_SLEEP)
            self.waitForVMMemoryToSettle(512)
            
            if self.testMemoryFields() != True:
                raise xenrt.XRTFailure("memory-actual and memory (from RRD) not in sync")
            
            self.guest.setDynamicMemRange(768, 768)
            time.sleep(self.TIME_TO_SLEEP)
            self.waitForVMMemoryToSettle(768)



class TC9285(xenrt.TestCase):
    """Verify VM operations preserve DMC parameters"""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()

        # Set up a template to clone
        self.template = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.template)
        self.template.preCloneTailor()
        self.template.shutdown()
        # Deliberately use unusual numbers so as to avoid getting fooled by any
        # template defaults
        self.template.setStaticMemRange(124, 1022)
        self.template.setDynamicMemRange(254, 764)

    def run(self, arglist=None):
        # Note, clone is implicitly verified as we clone the template before
        # each operation
        tests = ["snapshot","exportImport","convertToTemplate"]
        # First try with a normal VM
        for t in tests:
            g = self.template.cloneVM()
            # Ensure the clone has preserved the parameters
            g.checkMemory()
            self.runSubcase(t, (g), "VM", t)
            try:
                g.uninstall()
            except:
                pass
        # Now a template
        tests = ["templateExportImport","createFromTemplate"]
        for t in tests:
            g = self.template.cloneVM()
            g.checkMemory()
            g.paramSet("is-a-template","true")
            self.runSubcase(t, (g), "Template", t)
            try:
                g.uninstall()
            except:
                pass
        # Now a snapshot
        tests = ["snapshotExportImport",
                 "snapshotToTemplate",
                 "createFromSnapshot"]
        for t in tests:
            g = self.template.cloneVM()
            g.checkMemory()
            snap = g.snapshot()
            self.checkSnapProperties(snap, g)
            self.runSubcase(t, (snap,g), "Snapshot", t)
            try:
                g.removeSnapshot(snap)
            except:
                pass
            try:
                g.uninstall()
            except:
                pass

    def snapshot(self, g):
        snap = g.snapshot()
        try:
            self.checkSnapProperties(snap, g)
        finally:
            g.removeSnapshot(snap)

    def checkSnapProperties(self, snap, g):
        for p in ["static-min","static-max","dynamic-min","dynamic-max"]:
            xenrt.TEC().logverbose("Comparing snapshot's %s to original VM's "
                                   "%s" % (p, p))
            expected = g.dmcProperties[p]
            actual = int(g.host.genParamGet("vm", snap, "memory-%s" % (p))) / xenrt.MEGA
            if expected != actual:
                raise xenrt.XRTFailure("Snapshot %s does not match original" %
                                       (p))

    def exportImport(self, g):
        # Create a temporary file
        tf = xenrt.TEC().tempFile()
        try:
            g.exportVM(tf)
            g.uninstall()
            g.importVM(self.host, tf)
            g.checkMemory()
        finally:
            if os.path.exists(tf):
                os.unlink(tf)

    def templateExportImport(self, g):
        # Create a temporary file
        tf = xenrt.TEC().tempFile()
        try:
            if os.path.exists(tf):
                os.unlink(tf)
            cli = self.host.getCLIInstance()
            cli.execute("template-export", "template-uuid=%s filename=%s" % (g.getUUID(), tf))
            g.paramSet("is-a-template", "false")
            g.uninstall()
            g.importVM(self.host, tf)
            g.checkMemory()
        finally:
            if os.path.exists(tf):
                os.unlink(tf)

    def snapshotExportImport(self, snap, g):
        # Create a temporary file
        tf = xenrt.TEC().tempFile()
        try:
            if os.path.exists(tf):
                os.unlink(tf)
            cli = self.host.getCLIInstance()
            cli.execute("snapshot-export-to-template", "snapshot-uuid=%s filename=%s" % (snap, tf))
            g.removeSnapshot(snap)
            snap = cli.execute("vm-import","filename=%s" % (tf),strip=True)
            self.checkSnapProperties(snap, g)
            cli.execute("snapshot-uninstall","snapshot-uuid=%s force=true" % (snap))
        finally:
            if os.path.exists(tf):
                os.unlink(tf)

    def convertToTemplate(self, g):
        g.paramSet("is-a-template", "true")
        g.checkMemory()

    def snapshotToTemplate(self, snap, g):
        cli = g.host.getCLIInstance()
        try:
            temp = cli.execute("snapshot-clone",
                               "snapshot-uuid=%s new-name-label=templateFromSnap" % (snap),
                               strip=True)
        except xenrt.XRTFailure, e:
            if re.search("Unknown command", str(e)):
                xenrt.TEC().warning("The snapshot-clone command doesn't appear to exist.")
                temp = cli.execute("snapshot-create-template",
                                   "snapshot-uuid=%s new-name-label=templateFromSnap" % (snap),
                                   strip=True)
                
            else:
                raise e
        try:
            self.checkSnapProperties(temp, g)
        finally:
            cli.execute("snapshot-uninstall", "snapshot-uuid=%s force=true" % (temp))

    def createFromTemplate(self, g):
        cli = g.host.getCLIInstance()
        args = []
        args.append("template-uuid=%s" % (g.getUUID()))
        args.append("new-name-label=vmFromTemplate")        
        vm = cli.execute("vm-install", string.join(args), strip=True)
        try:
            self.checkSnapProperties(vm, g)
        finally:
            cli.execute("vm-uninstall", "uuid=%s force=true" % (vm))

    def createFromSnapshot(self, snap, g):
        g2 = g.instantiateSnapshot(snap)
        try:
            g2.checkMemory()
        finally:
            g2.uninstall()

class TC9286(xenrt.TestCase):
    """Verify that DMC VM continues to operate after PV driver uninstall"""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericWindowsGuest()
        self.uninstallOnCleanup(self.guest)
        self.getLogsFrom(self.guest)
        self.guest.installWorkloads(["Prime95"])
        self.guest.shutdown()
        self.guest.setMemoryProperties(512, 512, 512, 1024)
        self.guest.start()
        self.guest.paramSet("actions-after-crash", "Preserve")

        # Get the usemem_win.exe file ready
        self.workdir = self.guest.xmlrpcTempDir()
        self.guest.xmlrpcUnpackTarball("%s/utils.tgz" %
                                      (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                       self.workdir)

    def run(self, arglist=None):
        self.guest.uninstallDrivers(waitForDaemon=False)
        # We know the guest has rebooted, we expect it to crash once
        # However, if the daemon is responding, then we need to start something
        # that uses lots of memory in order to cause it to crash
        deadline = xenrt.util.timenow() + 1200
        usememStarted = False
        while True:
            if self.guest.getState() == "PAUSED":
                xenrt.TEC().logverbose("Expected crash found")
                break
            if not usememStarted and self.guest.xmlrpcIsAlive():
                # Start usemem to use 2048MiB of data
                try:
                    self.guest.xmlrpcStart("%s\\utils\\usemem_win.exe "
                                           "2147483648" % (self.workdir))
                except:
                    # Probably crashed while starting the app
                    pass
                #usememStarted = True
            if xenrt.util.timenow() >= deadline:
                raise xenrt.XRTError("Guest did not crash within 20 minutes")
            time.sleep(10)

        # Now restart it, and verify it boots normally
        self.guest.shutdown(force=True)

        self.guest.lifecycleOperation("vm-start", specifyOn=True)
        try:
            self.guest.waitForDaemon(600)
        except xenrt.XRTFailure, e:
            # See if its crashed
            if self.guest.getState() == "PAUSED":
                raise xenrt.XRTFailure("Windows VM crashed twice after "
                                       "uninstalling PV drivers with DMC")
            # No crash, so not clear what's going on
            raise xenrt.XRTFailure("Windows VM failed to boot after "
                                   "uninstalling PV drivers with DMC")




# Host choosing algorithm testcases
class _HostChooserBase(xenrt.TestCase):

    def __init__(self, tcid=None):
        self.pool = None
        xenrt.TestCase.__init__(self, tcid=tcid)

    def prepare(self, arglist=None):
        self.pool = self.getDefaultPool()

        # Check we have 4 hosts
        if len(self.pool.getHosts()) != 4:
            raise xenrt.XRTError("Pool must have 4 hosts")

        # Set up self.hostMemory - this should be the amount of memory an empty
        # host has free
        self.hostMemory = {}
        for h in self.pool.getHosts():
            self.hostMemory[h] = h.getFreeMemory()

        # Install a template guest that we'll clone as necessary
        # We assume the pool default SR is a shared one
        sr = self.pool.getPoolParam("default-SR")
        self.template = self.pool.master.createGenericLinuxGuest(sr=sr)
        self.uninstallOnCleanup(self.template)
        self.template.preCloneTailor()
        self.template.shutdown()

        self.hostGuests = {}

        # Create two VMs per host (don't start them)
        for h in self.pool.getHosts():
            self.hostGuests[h] = []
            for i in range(2):
                g = self.template.cloneVM()
                g.host = h
                self.uninstallOnCleanup(g)
                self.hostGuests[h].append(g)

        # The test VM will have a dynamic-min of 200MB, and a dynamic-max of
        # 384MB
        self.guest = self.template.cloneVM()
        self.uninstallOnCleanup(self.guest)
        self.guest.setStaticMemRange(None, 384)
        self.guest.setDynamicMemRange(200, 384)

    def configureHost(self, host, type):
        # Configure a host to be of an appropriate type
        smaxFits = False
        dmaxFits = False
        dminFits = False
        full = False
        if type == "definite":
            smaxFits = True
        elif type == "probable":
            dmaxFits = True
        elif type == "possible":
            dminFits = True
        elif type == "impossible":
            full = True
        else:
            raise xenrt.XRTError("Asked to configure host as unknown type %s" %
                                 (type))

        # First shut down any existing guests on the host
        for g in self.hostGuests[host]:
            if g.getState() == "UP":
                g.shutdown()

        if smaxFits:
            # Start up one guest
            g = self.hostGuests[host][0]
            g.setDynamicMemRange(256, 256)
            g.setStaticMemRange(None, 512)
            g.setDynamicMemRange(256, 512)
            self.startAndCheck(g, specifyOn=True)
        elif dmaxFits:
            # Configure two VMs such that the sum of their static max's is >
            # host memory
            # Make sum of dmax's equal to host memory - 512MB
            smax = self.hostMemory[host] / 2 + 128
            shadowOH = smax/128 + 1
            dmax = (self.hostMemory[host] - 512 - 2*shadowOH) / 2
            for g in self.hostGuests[host][:2]:
                g.setStaticMemRange(None, smax)
                g.setDynamicMemRange(dmax, dmax)
                self.startAndCheck(g, specifyOn=True)
        elif dminFits:
            # Configure two VMs such that the sum of their static max's is >
            # host memory
            # Make sum of dmax's > host memory
            # Make sum of dmins equal to host memory - 256MB --->changing to 270,because sometimes TC fail due to very less difference
            smax = self.hostMemory[host] / 2 + 128
            shadowOH = smax/128 + 1
            dmax = smax
            dmin = (self.hostMemory[host] - 300 - 2*shadowOH) / 2
            for g in self.hostGuests[host][:2]:
                g.setStaticMemRange(None, smax)
                g.setDynamicMemRange(dmin, dmax)
                self.startAndCheck(g, specifyOn=True)
        elif full:
            # Configure two VMs such that the sum of their static max's is > 
            # host memory
            # Make sum of dmax's > host memory
            # Make sum of dmins equal to host memory - 64MB
            smax = self.hostMemory[host] / 2 + 128
            shadowOH = smax/128 + 1
            dmax = smax
            dmin = (self.hostMemory[host] - 128 - 2*shadowOH) / 2
            for g in self.hostGuests[host][:2]:
                g.setStaticMemRange(None, smax)
                g.setDynamicMemRange(dmin, dmax)
                self.startAndCheck(g, specifyOn=True)

    def startAndCheck(self, guest, specifyOn=False, startElsewhere=False):
        # Preserver guest.host across this block.
        saved = guest.host
        guest.start(specifyOn=specifyOn)
        if startElsewhere:
            if guest.paramGet("resident-on") == saved.getMyHostUUID():
                raise xenrt.XRTFailure("Guest started on unexpected host")
        else:
            if guest.paramGet("resident-on") != saved.getMyHostUUID():
                raise xenrt.XRTFailure("Guest started on unexpected host")
        guest.host = saved

    def postRun(self):
        if self.pool:
            for h in self.pool.getHosts():
                try: h.enable()
                except: pass

class TC9305(_HostChooserBase):
    """Verify VM affinity is handled correctly by the DMC host chooser"""

    def run(self, arglist=None):
        # Set up 1 possible host (the rest will be definite)
        possible = self.pool.getHosts()[0]
        self.configureHost(possible, "possible")

        # Set our test guest's affinity to this possible host, and verify it
        # starts on it
        xenrt.TEC().logverbose("Verifying affinity is obeyed with possible "
                               "host...")
        self.guest.host = possible
        self.guest.paramSet("affinity", possible.getMyHostUUID())
        for i in range(10):
            self.startAndCheck(self.guest)
            self.guest.shutdown()    

        # Now make the possible host non-eligible (by disabling it), and make
        # sure it starts somewhere else
        xenrt.TEC().logverbose("Verifying affinity to disabled host is "
                               "ignored...")
        possible.disable()
        for i in range(10):
            self.startAndCheck(self.guest, startElsewhere=True)
            self.guest.shutdown()

        # Now make the possible host full, and verify the VM starts somewhere
        # else
        xenrt.TEC().logverbose("Verifying affinity to full host is ignored...")
        possible.enable()
        self.configureHost(possible, "impossible")
        for i in range(10):
            self.startAndCheck(self.guest, startElsewhere=True)
            self.guest.shutdown()

class TC9306(_HostChooserBase):
    """Verify DMC host chooser inter-category ranking"""

    def run(self, arglist=None):
        # Configure the four hosts
        hosts = self.pool.getHosts()
        definite = hosts[0]
        self.configureHost(definite, "definite")
        probable = hosts[1]
        self.configureHost(probable, "probable")
        possible = hosts[2]
        self.configureHost(possible, "possible")
        impossible = hosts[3]
        self.configureHost(impossible, "impossible")

        # Start the VM, verify the definite host is used
        xenrt.TEC().logverbose("Verifying definite host is used...")
        self.guest.host = definite
        for i in range(10):
            self.startAndCheck(self.guest)
            self.guest.shutdown()

        # Disable definite host, verify probable host is used
        definite.disable()
        self.guest.host = probable
        for i in range(10):
            self.startAndCheck(self.guest)
            self.guest.shutdown()

        # Disable probable host, verify possible host is used
        probable.disable()
        self.guest.host = possible
        for i in range(10):
            self.startAndCheck(self.guest)
            self.guest.shutdown()

        # Disable possible host, verify start fails sensibly
        possible.disable()
        try: self.guest.start(specifyOn=False)
        except: pass # TODO: Verify error is sensible
        else:
            raise xenrt.XRTFailure("vm-start succeeded with all hosts "
                                   "impossible")
        # Enable the host, and make the VMs uncooperative        
        possible.enable()
        # Sleep 1 minute to allow the squeezer to reset targets appropriately
        time.sleep(60)
        for g in self.hostGuests[possible]:
            if g.getState() == "UP":
                g.makeCooperative(False)
        # Now try and start, and verify it fails with sensible error
        try: self.guest.start(specifyOn=False)
        except: pass # TODO: Verify error is sensible
        else:
            raise xenrt.XRTFailure("vm-start succeeded on possible host with "
                                   "uncooperative VMs")

class _IntraCategoryBase(_HostChooserBase):
    """Base class for DMC host chooser intra-category ranking TCs"""
    CATEGORY = None
    RANKS_ON = None

    def run(self, arglist=None):
        # Configure two hosts to be in this category, the rest to be impossible
        hosts = self.pool.getHosts()
        if hosts[0].getFreeMemory() != hosts[1].getFreeMemory():
            h = [(i,int(i.getFreeMemory())) for i in hosts]
            l = [i[1] for i in h]
            hosts = [i[0] for i in sorted([(i[0], i[1], l.count(i[1])) for i in h], key=lambda x: x[2], reverse=True)]

        usedHosts = []
        for h in hosts[:2]:
            usedHosts.append(h)
            self.configureHost(h, self.CATEGORY)
        for h in hosts[2:]:
            self.configureHost(h, "impossible")

        betterHost = usedHosts[0]
        xenrt.TEC().logverbose("Configuring %s to be the better host" %
                               (betterHost.getName()))
        # Now make it so one is higher ranked than the other (by using up a
        # small amount more memory)
        if self.RANKS_ON == "static-max":
            # Decrease the static max on one of the hosts
            g = self.hostGuests[betterHost][0]
            g.shutdown()
            g.setDynamicMemRange(256, 400)
            g.setStaticMemRange(None, 400)
            self.startAndCheck(g, specifyOn=True)
        elif self.RANKS_ON == "dynamic-max":
            # Decrease the dynamic min+max on one of the hosts
            g = self.hostGuests[betterHost][0]
            dmin = int(g.paramGet("memory-dynamic-min")) / xenrt.MEGA
            dmax = int(g.paramGet("memory-dynamic-max")) / xenrt.MEGA
            g.setDynamicMemRange((dmin - 16), (dmax - 16))
        elif self.RANKS_ON == "ratio":
            # The host compression ratio, easiest way to fix this is to reduce
            # the amount a VM has to be squeezed, by decreasing dynamic max for
            # guest by 128MB
            for g in self.hostGuests[betterHost]:
                dmax = self.hostMemory[betterHost] / 2
                shadowOH = g.dmcProperties["static-max"] / 128 + 1
                dmin = (self.hostMemory[betterHost] - 300 - 2*shadowOH) / 2
                g.setDynamicMemRange(dmin, dmax)
        else:
            raise xenrt.XRTError("Unknown RANKS_ON value %s" % (self.RANKS_ON))

        # Now enable the no randomisation FIST point
        for h in self.pool.getHosts():
            h.execdom0("touch /tmp/fist_deterministic_host_selection")

        # Do 10 starts, and verify the higher ranked host is used each time
        self.guest.host = betterHost
        for i in range(10):
            self.startAndCheck(self.guest)
            self.guest.shutdown()

        # Now disable the FIST point
        for h in self.pool.getHosts():
            h.execdom0("rm -f /tmp/fist_deterministic_host_selection")

        # Do 10 starts, and verify each host is used at least once
        betterHostUsed = False
        otherHostUsed = False
        for i in range(30):
            self.guest.start(specifyOn=False)
            ro = self.guest.paramGet("resident-on")
            if ro == betterHost.getMyHostUUID():
                betterHostUsed = True
            elif ro == usedHosts[1].getMyHostUUID():
                otherHostUsed = True
            else:
                raise xenrt.XRTFailure("Unexpected host used during start loop")
            self.guest.shutdown()
            if betterHostUsed and otherHostUsed:
                break

        if not (betterHostUsed and otherHostUsed):
            raise xenrt.XRTFailure("No apparent randomness found in the DMC "
                                   "host choosing algorithm")

class TC9307(_IntraCategoryBase):
    """Verify hosts in the definite category are sorted correctly"""
    CATEGORY = "definite"
    RANKS_ON = "static-max"
class TC9308(_IntraCategoryBase):
    """Verify hosts in the probable category are sorted correctly"""
    CATEGORY = "probable"
    RANKS_ON = "dynamic-max"
class TC9309(_IntraCategoryBase):
    """Verify hosts in the possible category are sorted correctly"""
    CATEGORY = "possible"
    RANKS_ON = "ratio"

# HA interaction testcases
 
class _BalloonHABase(xenrt.TestCase):
    """Base class for ballooning vs HA testcases"""
    SUM_SMAX_FITS_ONE = False
    SUM_DMAX_FITS_ONE = True

    def prepare(self, arglist=None):
        self.pool = self.getDefaultPool()

        # Check we have 3 hosts
        if len(self.pool.getHosts()) != 3:
            raise xenrt.XRTError("Pool must have 3 hosts")
            
        #setting pool master with host having second highest memory. (CA-104367)
        hostMaster = sorted([(h,int(h.getFreeMemory())) for h in self.pool.getHosts()],key = operator.itemgetter(1,0))[-2][0]
        self.pool.designateNewMaster(hostMaster)

        # Set up self.hostMemory - this should be the amount of memory an empty
        # host has free
        # self.hostMemory = self.pool.getHosts()[0].getFreeMemory()
        self.hostMemory = self.pool.master.getFreeMemory()
        # this computed memory is returned in Mega bytes) is nothing but
        # memory-free = host.memory-total - host.memory-overhead - dom0.memory-actual - dom0.memory-overhead
        
        xenrt.TEC().logverbose("Computed Host Memory %u MiB" % (self.hostMemory))
        
        # Install a template guest that we'll clone as necessary
        # We assume the pool default SR is a shared one
        sr = self.pool.getPoolParam("default-SR")
        self.host = self.pool.master
        self.template = self.host.createGenericLinuxGuest(sr=sr)
        self.uninstallOnCleanup(self.template)
        self.template.preCloneTailor()
        self.template.shutdown()
        
        # Configure enough VMs so that the sum of static-max would fit on
        # SUM_SMAX_FITS hosts, and the sum of dynamic-max would fit on
        # SUM_DMAX_FITS hosts. sum of dynamic-min has to fit on 1 host, since
        # we will only be starting VMs on one host.
        if self.SUM_SMAX_FITS_ONE:
            smax = (self.hostMemory / 4) - 8 # 8MB fudge factor to be safe
        else:
            smax = (self.hostMemory / 4) + 64 # Should leave us 256MB over
        if self.SUM_DMAX_FITS_ONE:
            dmax = (self.hostMemory / 4) - 8
        else:
            dmax = (self.hostMemory / 4) + 64
        
        # Adjust for memory overheads (e.g. shadow)
        smax = smax - self.host.predictVMMemoryOverhead(smax, False)
        dmax = dmax - self.host.predictVMMemoryOverhead(dmax, False)

        # We need to budget for 5 VMs in dmin
        dmin = (self.hostMemory / 5) - 15 # 15MB fudge factor to be safe
        dmin = dmin - self.host.predictVMMemoryOverhead(dmin, False)
        
        self.smax = smax
        self.dmax = dmax
        self.dmin = dmin

        xenrt.TEC().logverbose("smax %u MiB" % (self.smax))
        xenrt.TEC().logverbose("dmax %u MiB" % (self.dmax))
        xenrt.TEC().logverbose("dmin %u MiB" % (self.dmin))

        self.guests = []
        for i in range(4):
            g = self.template.cloneVM()
            self.uninstallOnCleanup(g)
            self.guests.append(g)
            g.setStaticMemRange(None, smax)
            g.setDynamicMemRange(dmin, dmax)
            g.start()

    def postRun(self):
        try:
            self.pool.disableHA()
        except:
            pass

class TC9311(_BalloonHABase):        
    """Verify static-max is used for calculating nTol"""
    SUM_SMAX_FITS_ONE = False
    SUM_DMAX_FITS_ONE = True

    def run(self, arglist=None):
        # Set nTol to 0 and Enable HA
        self.pool.paramSet("ha-host-failures-to-tolerate", "0")
        self.pool.enableHA()

        # Verify that pool-ha-compute-hypothetical-max-failures-to-tolerate
        # gives us 1 (even though we're only using one host)
        cli = self.pool.getCLIInstance()
        args = []

        for g in self.guests:
            args.append("vm-uuid=%s" % (g.getUUID()))
            if isinstance(g, xenrt.lib.xenserver.guest.BostonGuest):
                args.append("restart-priority=restart")
            else:
                args.append("restart-priority=2")

        maxntol = cli.execute("pool-ha-compute-hypothetical-max-host-failures-to-tolerate",
                              string.join(args), strip=True)
        if int(maxntol) != 1:
            raise xenrt.XRTFailure("HA returned unexpected max nTol %s "
                                   "(expecting 1)" % (maxntol))

        self.pool.paramSet("ha-host-failures-to-tolerate", "1")
        # Protect the VMs
        for g in self.guests:
            g.setHAPriority("2")

        # Attempt to set nTol to 2, verify it is rejected
        try:
            self.pool.paramSet("ha-host-failures-to-tolerate", "2")
        except:
            pass
        else:
            raise xenrt.XRTFailure("Allowed to set nTol to 2 in 3-node pool "
                                   "when sum of static-max is greater than 1 "
                                   "host's memory")

class TC9312(_BalloonHABase):
    """Verify overcommit protection prevents vm-starts in DMC scenarios"""
    SUM_SMAX_FITS_ONE = False
    SUM_DMAX_FITS_ONE = False

    def run(self, arglist=None):
        # Configure HA with nTol of 1
        self.pool.paramSet("ha-host-failures-to-tolerate", "1")
        self.pool.enableHA()
        for g in self.guests:
            g.setHAPriority("2")

        # Attempt to start another VM such that the sum of static-max would be
        # > 2 hosts (but sum of dynamic-min would still allow it to fit)
        smaxsum = self.smax * 4
        newsmax = (self.hostMemory * 2) - smaxsum + 32
        g = self.template.cloneVM()
        self.uninstallOnCleanup(g)
        g.setStaticMemRange(None, newsmax)
        g.setDynamicMemRange(self.dmin, self.dmax)

        # We shouldn't be allowed to start this VM as the new sum of static-max
        # means we couldn't tolerate 1 host failure
        try:
            g.start()
            g.setHAPriority("2")
        except:
            pass
        else:
            raise xenrt.XRTFailure("Allowed to start VM with static-max "
                                   "sufficient to cause HA problems")
                
class TC9313(_BalloonHABase):
    """Verify squeezing occurs when valid with HA enabled"""
    SUM_SMAX_FITS_ONE = False
    SUM_DMAX_FITS_ONE = False

    def run(self, arglist=None):
        # Configure HA with nTol of 1
        self.pool.paramSet("ha-host-failures-to-tolerate", "1")
        self.pool.enableHA()
        for g in self.guests:
            g.setHAPriority("2")

        # Start another VM such that sum of static-max is still < 2 hosts,
        # verify squeezing occurs correctly
        # reducing the dmin further so as to fit the 5th vm in avaialble host memory.
        self.dmin = self.dmin - (2 * self.host.predictVMMemoryOverhead(self.dmin, False))
        g = self.template.cloneVM()
        self.uninstallOnCleanup(g)
        g.setStaticMemRange(None, self.smax)
        g.setDynamicMemRange(self.dmin, self.dmax)
        g.start()
        if g.findHost() != self.host:
            raise xenrt.XRTFailure("Squeezing did not occur as expected, VM "
                                   "booted on different host")



# Host upgrade
class TC9322(xenrt.TestCase):
    """Verify upgrade from non-DMC release to DMC release behaviour"""

    def prepare(self, arglist=None):
        self.pool = self.getDefaultPool()

        # Verify this is a 3 host pool
        if len(self.pool.getHosts()) != 3:
            raise xenrt.XRTError("Expecting 3 host pool")

        sr = self.pool.getPoolParam("default-SR")

        # This pool should be of the previous GA release
        # Set up some linux+windows VMs, with a variety of memory properties
        # One of each VM type per host
        xenrt.TEC().logverbose("Configuring one Windows and Linux VM per host")
        self.guests = []
        self.smaxes = {}
        self.smins = {}
        # Properties to use (list of (smin,dmin,dmax,smax) tuples in MiB)
        linuxProperties = [(256,256,256,512),(512,256,128,256),(16,128,128,384)]
        winProperties = [(512,512,512,512),(16,512,512,1024),(16,200,128,560)]
        hosts = self.pool.getHosts()
        for i in range(3):
            h = hosts[i]
            linP = linuxProperties[i]
            g = h.createGenericLinuxGuest(sr=sr, memory=linP[3])
            self.guests.append(g)
            self.smins[g] = linP[0]
            self.smaxes[g] = linP[3]
            g.paramSet("memory-static-min", linP[0] * xenrt.MEGA)
            g.paramSet("memory-dynamic-min", linP[1] * xenrt.MEGA)
            g.paramSet("memory-dynamic-max", linP[2] * xenrt.MEGA)
        
            winP = winProperties[i]
            g = h.createGenericWindowsGuest(sr=sr, memory=winP[3])
            self.guests.append(g)
            self.smins[g] = winP[0]
            self.smaxes[g] = winP[3]
            g.paramSet("memory-static-min", winP[0] * xenrt.MEGA)
            g.paramSet("memory-dynamic-min", winP[1] * xenrt.MEGA)
            g.paramSet("memory-dynamic-max", winP[2] * xenrt.MEGA)            

        # Set up one host with a different memory target
        self.targetHost = self.pool.getHosts()[0]
        xenrt.TEC().logverbose("Setting a new dom0 target for %s" %
                               (self.targetHost.getName()))
        dom0 = self.targetHost.getMyDomain0UUID()
        ctarget = int(self.targetHost.genParamGet("vm", dom0, "memory-target"))
        # Also log the other parameters for debug purposes
        cli = self.targetHost.getCLIInstance()
        cli.execute("vm-list", "uuid=%s params=name-label,memory-static-min,"
                               "memory-dynamic-min,memory-dynamic-max,"
                               "memory-static-max,memory-target,"
                               "memory-actual" % (dom0))

        # Increase it by 32MB (the test is constrained to run on a <= 8GB host)
        self.target = ctarget + (32*xenrt.MEGA)

        xenrt.TEC().logverbose("Using %u MiB for new dom0 target" %
                               (self.target/xenrt.MEGA))
        # Set the target        
        cli.execute("vm-memory-target-set", "target=%u uuid=%s" %
                                            (self.target, dom0))
        cli.execute("vm-memory-target-wait", "uuid=%s" % (dom0))
        xenrt.TEC().logverbose("Sleeping 60s to let new dom0 target settle")
        time.sleep(60)

    def run(self, arglist=None):
        # Perform a rolling upgrade of the pool
        xenrt.TEC().logverbose("Performing rolling upgrade...")
        xenrt.TEC().logverbose("Manually evacuating the master since "
                               "host-evacuate will fail with weird memory "
                               "constraints")
        slaves = self.pool.getSlaves()
        s = 0
        for g in self.guests:
            if g.host == self.pool.master:
                g.migrateVM(slaves[s], live="true")
                s += 1
                if s == len(slaves): s = 0
        self.pool.upgrade(rolling=True)
        xenrt.TEC().logverbose("...done")

        # Verify that all VMs have dynamic-min=dynamic-max=static-max and 
        # that it equals the original static-max
        xenrt.TEC().logverbose("Verifying VM memory parameters...")
        for g in self.guests:
            dmin = int(g.paramGet("memory-dynamic-min")) / xenrt.MEGA
            dmax = int(g.paramGet("memory-dynamic-max")) / xenrt.MEGA
            smax = int(g.paramGet("memory-static-max")) / xenrt.MEGA
            target = int(g.paramGet("memory-target")) / xenrt.MEGA
            if not (dmin == dmax == smax == target):
                raise xenrt.XRTFailure("dynamic-min+max and/or target were not "
                                       "set equal to static-max after upgrade",
                                       data="static-max %dMiB, dynamic-min "
                                            "%dMiB, dynamic-max %dMiB, target "
                                            "%dMiB" %
                                            (smax,dmin,dmax,target))
            smin = int(g.paramGet("memory-static-min")) / xenrt.MEGA
            expectedSmin = min(self.smaxes[g],self.smins[g])
            if not smin == expectedSmin:
                raise xenrt.XRTFailure("static-min not set to minimum of "
                                       "static-max and static-min pre-upgrade",
                                       data="Expecting %dMiB, found %dMiB" %
                                       (expectedSmin, smin))
            if not smax == self.smaxes[g]:
                raise xenrt.XRTFailure("static-max changed after upgrade",
                                       data="Pre-upgrade %dMiB, post-upgrade "
                                            "%dMiB" % (self.smaxes[g],smax))
        xenrt.TEC().logverbose("...done")

        xenrt.TEC().logverbose("Verifying all VMs can be rebooted...")
        for g in self.guests:
            g.findHost()
            g.reboot()
            g.check()
        xenrt.TEC().logverbose("...done")

        xenrt.TEC().logverbose("Updating PV drivers in all VMs...")
        newguests = []
        for g in self.guests:
            ng = g.getHost().guestFactory()(g.getName())
            g.populateSubclass(ng)
            newguests.append(ng)
        self.guests = newguests

        for g in self.guests:
            if g.windows:
                g.installDrivers()
            else:
                g.installTools()
            g.check()
        xenrt.TEC().logverbose("...done")

        xenrt.TEC().logverbose("Verifying VMs can be ballooned...")
        for g in self.guests:
            g.shutdown()
            smax = int(g.paramGet("memory-static-max")) / xenrt.MEGA
            # Set static-max to x2
            g.setMemoryProperties(smax, smax, smax, smax * 2)
            g.start()
            g.checkMemory(inGuest=True)
        xenrt.TEC().logverbose("...done")

        # Verify that the host's different memory-target has been copied in to
        # dynamic-{min,max}
        h = self.targetHost
        xenrt.TEC().logverbose("Verifying %s's dom0 target..." % (h.getName()))
        dmin = int(h.genParamGet("vm",h.getMyDomain0UUID(),"memory-dynamic-min"))
        dmax = int(h.genParamGet("vm",h.getMyDomain0UUID(),"memory-dynamic-max"))
        if dmin != dmax:
            raise xenrt.XRTFailure("Host dynamic-min+max were not equal after "
                                   "upgrade",
                                   data="dynamic-min %dMiB, dynamic-max %dMiB" %
                                        (dmin/xenrt.MEGA,dmax/xenrt.MEGA))
        if dmin != self.target:
            raise xenrt.XRTFailure("Host dynamic-min+max post-upgrade were not "
                                   "set to host memory target pre-upgrade",
                                   data="Target pre-upgrade %dMiB, dynamic-min"
                                        "+max post-upgrade %dMiB" %
                                       (self.target/xenrt.MEGA,dmin/xenrt.MEGA))
        # Verify dom0 is actually using that target by reading it from xenstore
        xstarget = int(h.xenstoreRead("/local/domain/0/memory/target")) * xenrt.KILO
        if xstarget != self.target:
            raise xenrt.XRTFailure("dom0 memory-target in xenstore doesn't "
                                   "match target in xapi db",
                                   data="Expecting %dMiB, found %dMiB" %
                                        (self.target / xenrt.MEGA, xstarget / xenrt.MEGA))
        xenrt.TEC().logverbose("...done")

class TC9354(xenrt.TestCase):
    """Verify imported VM exported from a non-DMC release has memory parameters
       set correctly"""

    def prepare(self, arglist=None):
        # We expect the old host to be RESOURCE_HOST_0, and the new host to be
        # RESOURCE_HOST_1
        self.oldHost = self.getHost("RESOURCE_HOST_0")
        self.newHost = self.getHost("RESOURCE_HOST_1")

        # Set up 1 Linux and 1 Windows VM on the old host, give them some wacky
        # memory parameters, and export

        self.oldLinuxGuest = self.oldHost.createGenericLinuxGuest(memory=256)
        self.uninstallOnCleanup(self.oldLinuxGuest)
        self.oldLinuxGuest.shutdown()
        self.oldLinuxGuest.paramSet("memory-static-min", "512MiB")
        self.oldLinuxGuest.paramSet("memory-dynamic-min", "256MiB")
        self.oldLinuxGuest.paramSet("memory-dynamic-max", "128MiB")    

        self.oldWindowsGuest = self.oldHost.createGenericWindowsGuest(memory=560)
        self.uninstallOnCleanup(self.oldWindowsGuest)
        self.oldWindowsGuest.shutdown()
        self.oldWindowsGuest.paramSet("memory-static-min", "16MiB")
        self.oldWindowsGuest.paramSet("memory-dynamic-min", "200MiB")
        self.oldWindowsGuest.paramSet("memory-dynamic-max", "128MiB")

        self.linuxExport = xenrt.TEC().tempFile()
        self.oldLinuxGuest.exportVM(self.linuxExport)
        self.winExport = xenrt.TEC().tempFile()
        self.oldWindowsGuest.exportVM(self.winExport)

    def run(self, arglist=None):
        # Import the VMs on the new host
        cli = self.newHost.getCLIInstance()

        xenrt.TEC().logverbose("Importing Linux VM (expecting 256MiB)...")
        newLinux = cli.execute("vm-import", "filename=%s" % (self.linuxExport),
                               strip=True)
        # static-min here should be reset to static-max, since 256 is the min of
        # the old static-max and static-min
        for p in ["static-min", "dynamic-min", "dynamic-max", "static-max"]:
            if (int(self.newHost.genParamGet("vm", newLinux, "memory-%s" % (p))) / xenrt.MEGA) != 256:
                raise xenrt.XRTFailure("memory-%s parameter not reset to static-max on import" % (p))

        # Try the Windows one with preserve=true in case that makes a difference
        xenrt.TEC().logverbose("Importing Windows VM with preserve=true (expecting 560MiB)...")
        newWin = cli.execute("vm-import", "filename=%s preserve=true" % (self.winExport),
                             strip=True, timeout=10800)
        for p in ["dynamic-min", "dynamic-max", "static-max"]:
            if (int(self.newHost.genParamGet("vm", newWin, "memory-%s" % (p))) / xenrt.MEGA) != 560:
                raise xenrt.XRTFailure("memory-%s parameter not reset to static-max on import" % (p))
        newStaticMin = int(self.newHost.genParamGet("vm", newWin, "memory-static-min")) / xenrt.MEGA
        if newStaticMin != 16:
            raise xenrt.XRTFailure("Valid memory-static-min not left alone on import",
                                   data="Old value 16MiB, new value %dMiB" % (newStaticMin))

    def postRun(self):
        try:
            if self.linuxExport:
                xenrt.util.command("rm -f %s || true" % (self.linuxExport))
        except:
            pass
        try:
            if self.winExport:
                xenrt.util.command("rm -f %s || true" % (self.winExport))
        except:
            pass       


class _BalloonBootTime(xenrt.TestCase):
    """Verify the extra time for booting a ballooned down VM is minimal"""
    VMNAME = "winxpsp3"
    USEMEM = 512
    ALLOWED_INCREASE = 20

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guest = self.getGuest(self.VMNAME)
        if not self.guest:
            raise xenrt.XRTError("Could not find guest %s in  registry." % (self.VMNAME))
        self.guest.shutdown()

    def run(self, arglist=None):
        xenrt.TEC().logdelimit("Performing 5 iterations of non-DMC boot...")
        self.guest.setMemoryProperties(None, self.USEMEM, self.USEMEM, self.USEMEM)
        nonDMC = xenrt.util.Timer()
        self.timeBoot(self.guest, nonDMC)
        xenrt.TEC().comment("non-DMC average time %u seconds (to the nearest 5s)" % (nonDMC.mean()))
        xenrt.TEC().logverbose("non-DMC results: %s" % (str(nonDMC.measurements)))

        xenrt.TEC().logdelimit("Performing 5 iterations of DMC boot...")
        multiplier = 100 / int(self.host.lookup("DMC_WIN_PERCENT", "50"))
        self.guest.setMemoryProperties(None, self.USEMEM, self.USEMEM, self.USEMEM * multiplier)
        DMC = xenrt.util.Timer()
        self.timeBoot(self.guest, DMC)
        xenrt.TEC().comment("DMC average time %u seconds (to the nearest 5s)" % (DMC.mean()))
        xenrt.TEC().logverbose("DMC results: %s" % (str(DMC.measurements)))

        # Decide if its good enough
        difference = DMC.mean() - nonDMC.mean()
        xenrt.TEC().logverbose("Time difference %u seconds" % (difference))
        if difference > self.ALLOWED_INCREASE:
            raise xenrt.XRTFailure("DMC slowed boot of %s by more than %d "
                                   "seconds" % (self.DISTRO, self.ALLOWED_INCREASE),
                                   data=difference)
        if difference < -5:
            # DMC shouldn't speed things up, so something crazy is obviously going on
            raise xenrt.XRTError("DMC appeared to speed up boot!",
                                 data=difference)

    def timeBoot(self, guest, timer):
        for i in range(5):
            timer.startMeasurement()
            guest.lifecycleOperation("vm-start", specifyOn=True)

            # Wait for the VM to come up.
            xenrt.TEC().progress("Waiting for the VM to enter the UP state")
            guest.poll("UP", pollperiod=5)
            guest.waitforxmlrpc(600, desc="Guest boot", sleeptime=5, reallyImpatient=True)
            # Now wait for the guest agent
            guest.waitForAgent(180)
            # VM has booted
            timer.stopMeasurement()
            # Sleep 10s before shutting the VM down (CA-32492)
            time.sleep(10)
            guest.shutdown()

class TC9527(_BalloonBootTime):
    """Verify the extra time for booting a ballooned down Windows XP sp3 VM is minimal"""
    VMNAME = "winxpsp3"
    USEMEM = 512

class TC9528(_BalloonBootTime):
    """Verify the extra time for booting a ballooned down Windows 7 x86 VM is minimal"""
    VMNAME = "win7-x86"
    USEMEM = 1024

class TC9529(_BalloonBootTime):
    """Verify the extra time for booting a ballooned down Windows 7 x64 VM is minimal"""
    VMNAME = "win7-x64"
    USEMEM = 2048

class TC12600(_BalloonBootTime):
    """Verify the extra time for booting a ballooned down Windows 7 SP1 x86 VM is minimal"""
    VMNAME = "win7sp1-x86"
    USEMEM = 2048
    #increasing extra time allowed to boot with DMC to 40 sec. CA-37461, CA-33630
    ALLOWED_INCREASE = 40

class TC12601(_BalloonBootTime):
    """Verify the extra time for booting a ballooned down Windows 7 SP1 x64 VM is minimal"""
    VMNAME = "win7sp1-x64"
    USEMEM = 2048
    ALLOWED_INCREASE = 60

class TC26440(_BalloonBootTime):
    """Verify the extra time for booting a ballooned down Windows 10 x86 VM is minimal"""
    VMNAME = "win10-x86"
    USEMEM = 2048
    ALLOWED_INCREASE = 60

class TC26441(_BalloonBootTime):
    """Verify the extra time for booting a ballooned down Windows 10 x64 VM is minimal"""
    VMNAME = "win10-x64"
    USEMEM = 2048
    ALLOWED_INCREASE = 60




class _DMCMigrateBase(xenrt.TestCase):
    """Base class for DMC Migration test cases"""
    SOURCE_FULL = False
    DEST_FULL = False
    COOPERATIVE = True
    EXPECT_FAIL = None
    LEAVE_FREE = random.randint(650, 1000)

    def prepare(self, arglist=None):
        self.pool = self.getDefaultPool()

        hosts = self.pool.getHosts()
        self.sourceHost = hosts[0]
        self.destHost = hosts[1]
        self.dynMinSum = {}
        self.dynMaxSum = {}
        self.overheadSum = {}

        # handle the control domain for each host
        for h in hosts[:2]:        
            cd = h.getMyDomain0UUID()
            self.dynMinSum[h] = int(h.genParamGet("vm", cd, "memory-dynamic-min"))
            self.dynMaxSum[h] = int(h.genParamGet("vm", cd, "memory-dynamic-max"))
            self.overheadSum[h] = int(h.genParamGet("vm", cd, "memory-overhead"))
            self.overheadSum[h] += int(h.paramGet("memory-overhead"))

        # Wait 60s for the host free memory to update
        time.sleep(60)
        if self.SOURCE_FULL:
            # Configure the source host to be full
            self.makeFullHost(self.sourceHost)
        if self.DEST_FULL:
            # Configure the dest host to be full
            self.makeFullHost(self.destHost)

        sr = self.pool.getPoolParam("default-SR")
        self.guest = self.getGuest("DMCMigrateGuest")

        self.guest.setMemoryProperties(None, 512, 1024, 1024)

        # Ensure we don't make the guest immediately uncooperative (it'll crash if we do!)
        self.guest.makeCooperative(True, xapiOnly=True)
        self.guest.host = self.sourceHost

        self.guest.start()

        if not self.COOPERATIVE:
            self.guest.makeCooperative(False)

    def makeFullHost(self, host):
        xenrt.TEC().logverbose("Configuring %s to be 'full'" % (host.getName()))
        # Configure the host to be 'full' - we need to leave a value somewhere
        # between 600 and 1000MiB free (deliberately randomise within this range)
        # Make sure that static+dynamic-max is greater
        freemem = host.getFreeMemory()
        vm = int(math.ceil((freemem + 4096)/float(32768)))
        # We start up VMs
        max = (freemem + 4096) / vm # 4GiB over the host free memory
        shadowOH =  host.predictVMMemoryOverhead(max, False) #max/128 + 1 # This takes account of the shadow overhead
        leaveFree = self.LEAVE_FREE       
        min = (freemem - leaveFree - vm*shadowOH) / vm
        for i in range(vm):
            g = host.createGenericLinuxGuest(start=False)
            self.uninstallOnCleanup(g)
            g.setMemoryProperties(None, min, max, max)
            g.start()
            self.dynMinSum[host] += min * xenrt.MEGA
            self.dynMaxSum[host] += max * xenrt.MEGA
            self.overheadSum[host] += int(g.paramGet("memory-overhead"))


    def findCompressionRatio(self, host, guest):
        dynMinSum = self.dynMinSum[host]
        dynMaxSum = self.dynMaxSum[host]
        overheadSum = self.overheadSum[host]
        if guest:
            dynMinSum += int(guest.paramGet("memory-dynamic-min"))
            dynMaxSum += int(guest.paramGet("memory-dynamic-max"))
            overheadSum += int(guest.paramGet("memory-overhead"))
        total = int(host.paramGet("memory-total"))
        r = float(total - overheadSum - dynMaxSum)/float(dynMinSum - dynMaxSum)
        return r

    def run(self, arglist=None):
        # Try the migrate
        onHost = self.sourceHost
        try:
            self.guest.migrateVM(self.destHost, live="true")
            onHost = self.destHost
        except xenrt.XRTFailure, e:
            if self.EXPECT_FAIL:
                # First verify if the VM is still running on the source
                # host
                xenrt.TEC().logverbose("Expected failure occurred, checking "
                                       "guest health")
                self.guest.checkHealth()

                # Now see if it was the failure we expected
                foundexpected = False
                for ef in self.EXPECT_FAIL:
                    if re.search(ef, e.data):
                        xenrt.TEC().logverbose("Expected failure occurred...")
                        foundexpected = True
                        break
                if not foundexpected:
                    raise xenrt.XRTFailure("Expected failure occurred with "
                                           "unexpected message", data=e.data)
            else:
                raise e
        else:
            if self.EXPECT_FAIL:
                raise xenrt.XRTError("Expected failure didn't occur...")

        # Now verify we are at the expected level
        time.sleep(60)
        mem = self.guest.getMemoryActual() / xenrt.MEGA
        if (self.EXPECT_FAIL and self.SOURCE_FULL) or \
           (not self.EXPECT_FAIL and self.DEST_FULL):
            r = self.findCompressionRatio(onHost,self.guest)
            expected = r * 512 + (1.0 - r) * 1024
            if mem < (expected - 15) or mem > (expected + 15):
                raise xenrt.XRTFailure("Found unexpected memory usage after "
                                       "migrate to full host",
                                       data="Expecting %dMiB, found %u"
                                            "MiB" % (expected,mem))
        elif abs(1024 - mem) > 2:
            raise xenrt.XRTFailure("Found unexpected memory usage after "
                                   "migrate to empty host",
                                   data="Expecting 1024MiB, found %uMiB" %
                                        (mem))

    def postRun(self):
        if self.guest:
            if self.guest.getState() != "DOWN":
                try:
                    self.guest.shutdown()
                except:
                    try:
                        self.guest.shutdown(force=True)
                    except:
                        xenrt.TEC().warning("Unable to shut down guest!")

class TC9531(_DMCMigrateBase):
    """VM migration from empty host to empty host"""
    pass
class TC9532(_DMCMigrateBase):
    """VM migration from empty host to full host"""
    DEST_FULL = True
class TC9533(_DMCMigrateBase):
    """VM migration from full host to empty host"""
    SOURCE_FULL = True
class TC9534(_DMCMigrateBase):
    """VM migration from full host to full host"""
    SOURCE_FULL = True
    DEST_FULL = True
class TC9535(_DMCMigrateBase):
    """VM migration from empty host to empty host with non-cooperative VM"""
    COOPERATIVE = False
class TC9536(_DMCMigrateBase):


    """VM migration from empty host to full host with non-cooperative VM"""
    COOPERATIVE = False
    DEST_FULL = True
    LEAVE_FREE = 550
    EXPECT_FAIL = ["HOST_NOT_ENOUGH_FREE_MEMORY", "Not enough host memory is available to perform this operation"]


class BalloonTestBase(xenrt.TestCase):
    """Utility testcase for testing individual configurations of VMs"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        args = xenrt.util.strlistToDict(arglist)
        shouldHave = ["distro", "minMiB", "maxMiB"]
        for s in shouldHave:
            if not args.has_key(s):
                raise xenrt.XRTError("%s not found in args" % (s))

        distro = args["distro"]
        isWindows = distro.startswith("w") or distro.startswith("v")
        self.min = int(args["minMiB"])
        self.max = int(args["maxMiB"])

        if isWindows:
            self.guest = self.host.createGenericWindowsGuest(distro=distro)
            if not args.has_key("PAE") or args["PAE"] == "no":
                self.guest.forceWindowsPAE()
        else:
            if args.has_key("arch"):
                arch = args["arch"]
            else:
                arch = "x86-32"
            self.guest = self.host.createBasicGuest(distro=distro, arch=arch)

        self.guest.shutdown()

    def run(self, arglist):
        self.guest.setMemoryProperties(None, self.min, self.min, self.max)
        success = 0
        try:
            for i in range(5):
                xenrt.TEC().logverbose("Starting iteration %u/5..." % (i+1))
                self.guest.start()
                self.guest.shutdown()
                success += 1
        finally:
            xenrt.TEC().comment("%u/5 iterations successful" % (success))






class TC11022(xenrt.TestCase):
    """Verify behaviour when importing a VM with a dynamic memory range in to a
       free edition host"""

    def prepare(self, arglist=None):
        # Get a host with an enterprise license
        self.host = self.getDefaultHost()
        self.host.license()

        # Set up two VMs, one to export, and one to do the export on
        self.cliguest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.cliguest)
        self.guest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.guest.preCloneTailor()
        self.guest.shutdown()
        # Give it a dynamic range
        self.guest.setMemoryProperties(128, 256, 512, 768)

        # Add a disk to do the export on to
        ud = self.cliguest.createDisk(sizebytes=30 * xenrt.GIGA)
        d = self.host.parseListForOtherParam("vbd-list",
                                             "vm-uuid",
                                             self.cliguest.getUUID(),
                                             "device",
                                             "userdevice=%s" % (ud))
        time.sleep(5)
        self.cliguest.execguest("mkdir -p /mnt/export")
        self.cliguest.execguest("mkfs.ext3 /dev/%s" % (d))
        self.cliguest.execguest("mount /dev/%s /mnt/export" % (d))

        self.cliguest.installCarbonLinuxCLI()

        # Now do the actual export
        args = []
        args.append("uuid=%s" % (self.guest.getUUID()))
        args.append("filename=/mnt/export/export.img")
        c = xenrt.lib.xenserver.buildCommandLine(self.host,
                                                     "vm-export",
                                                     string.join(args))
        self.cliguest.execcmd("xe %s" % (c), timeout=3600)

        self.guest.uninstall()


    def run(self, arglist=None):
        # Import the VM
        args = []
        args.append("sr-uuid=%s" % (self.host.getLocalSR()))
        args.append("filename=/mnt/export/export.img")
        c = xenrt.lib.xenserver.buildCommandLine(self.host,
                                                 "vm-import",
                                                 string.join(args))
        newuuid = string.strip(self.cliguest.execcmd("xe %s" % (c), timeout=3600))
        
        self.guest.uuid = newuuid
        self.guest.existing(self.host)
        self.host.addGuest(self.guest)
        self.guest.vifs[0] = self.guest.vifs[1]

        # Check the VM still has the correct DMC parameters
        newsmin = int(self.guest.paramGet("memory-static-min")) / xenrt.MEGA
        newdmin = int(self.guest.paramGet("memory-dynamic-min")) / xenrt.MEGA
        newdmax = int(self.guest.paramGet("memory-dynamic-max")) / xenrt.MEGA
        newsmax = int(self.guest.paramGet("memory-static-max")) / xenrt.MEGA
        if newsmin != 128 or newdmin != 256 or newdmax != 512 or newsmax != 768:
            raise xenrt.XRTFailure("Imported VM memory parameters changed",
                                   data="Expecting 256, 512, 768, found %d, %d"
                                        ", %d" % (newdmin, newdmax, newsmax))

        # Verify the VM still starts
        self.guest.start()

    def postRun(self):
        if self.host:
            # Ensure we have a normal license
            self.host.license()

class _OverrideBallooning(xenrt.TestCase):
   
    GUEST = None

    def prepare(self, arglist=None):
    
        self.host = self.getDefaultHost()
        for gname in self.host.listGuests(running=True):
            g = xenrt.TEC().registry.guestGet(gname)
            g.shutdown()
        xenrt.sleep(30)
        
        self.guest1 = self.getGuest("tester")
        self.guest2 = self.getGuest(self.GUEST)
        
        self.hostMemory = self.host.getFreeMemory() 
        self.smax = self.hostMemory
        self.dmax = self.smax 
        self.shadowOH =  self.host.predictVMMemoryOverhead(self.dmax, False)
        self.dmin = self.smax - 1200 - self.shadowOH
        
        xenrt.TEC().logverbose(self.smax)
        xenrt.TEC().logverbose(self.dmax)
        xenrt.TEC().logverbose(self.dmin)

        self.guest2.setMemoryProperties(None, self.dmin, self.dmax, self.smax)
        self.guest2.start()
        time.sleep(60)

    def run(self, arglist=None):
        
        self.guest2.xmlrpcExec("bcdedit /set loadoptions XEN:BALLOON=OFF")
        self.guest2.reboot()

        try:
            self.guest1.start()
        except:
            pass
        else:
            raise xenrt.XRTError("Succeeded to set dynamic memory range")
            
        self.guest2.xmlrpcExec("bcdedit /deletevalue loadoptions")
        self.guest2.reboot()
        time.sleep(60)
        
        try:
            self.guest1.start()
        except Exception, e:
            raise xenrt.XRTError("Failed to set dynamic memory range(%s)" % (e))
    
    def postRun(self):
        try: self.guest1.shutdown()
        except: pass
        try: self.guest2.shutdown()
        except: pass
    
class TC18489(_OverrideBallooning):
    """Verify the balloon overriding works well with windows vista boot load options"""
    GUEST = "vista-32"
    
class TC18536(_OverrideBallooning):
    """Verify the balloon overriding works well with windows 7 x86 boot load options"""
    GUEST = "win7-32"
    
class TC18537(_OverrideBallooning):
    """Verify the balloon overriding works well with Windows 2008 SP2 x86 boot load options"""
    GUEST = "ws08-64"
    
class TC18538(_OverrideBallooning):

    """Verify the balloon overriding works well with Windows 2008 SP2 x64 boot load options"""
    GUEST = "ws08r2-64"

class TCMemoryActual(xenrt.TestCase):
    """Verify memory actual value after VM migration"""
    #Jira TC-21565
    
    def run(self, arglist=None):
    
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")

        step("Fetch list of guests")
        guests = []
        for gname in self.host0.listGuests():
            guests.append(self.host0.getGuest(gname))

        step("set memory of guests")
        cli = self.host0.getCLIInstance()
        for g in guests:
            #Assign 4GiB memory to VM. Static min =  dynamic min = dynamic max = static max = 4096MiB
            mem = 4096
            g.shutdown()
            g.setMemoryProperties(mem, mem, mem, mem)
            cli.execute("vm-start", "uuid=%s on=%s" % (g.uuid, self.host0))

        for g in guests:
            r = self.runSubcase("memoryTest", (g), g.distro, "test")
    

    def memoryTest(self, g):
        for i in range(5):
            step("Perform vm migration to slave")
            g.migrateVM(self.host1, live="true")
            xenrt.sleep(90)
            step("Verify memory actual and memory Target are equal to 4096MiB")
            memoryActual = g.getMemoryActual() / xenrt.MEGA
            memoryTarget = g.getMemoryTarget() / xenrt.MEGA
            xenrt.TEC().logverbose("Memory Actual after Migration= %s" % memoryActual)
            xenrt.TEC().logverbose("Memory Target after Migration= %s" % memoryTarget)
            if abs(memoryActual - 4096) > 2:
                raise xenrt.XRTFailure("Unexpected memory actual after VM migration")
     
            step("Perform vm migration to master")
            g.migrateVM(self.host0, live="true")
            xenrt.sleep(90)
            step("Verify memory actual and memory target are equal to 4096MiB")
            memoryActual = g.getMemoryActual() / xenrt.MEGA
            memoryTarget = g.getMemoryTarget() / xenrt.MEGA
            xenrt.TEC().logverbose("Memory Actual after Migration= %s" % memoryActual)
            xenrt.TEC().logverbose("Memory Target after Migration= %s" % memoryTarget)
            if abs(memoryActual - 4096) > 2:
                raise xenrt.XRTFailure("Unexpected memory actual after VM migration")
