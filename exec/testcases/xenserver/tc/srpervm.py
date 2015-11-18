# XenRT: Test harness for Xen and the XenServer product family
#
# Test cases for issues with lots of SRs.
#
# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt, random
import testcases.benchmarks.workloads

class SetupSRsBase(xenrt.TestCase):
    PROTOCOL=None
    def run(self, arglist=[]):
        args = self.parseArgsKeyValue(arglist)

        linuxCount = int(args.get("linuxvms", "10"))
        windowsCount = int(args.get("windowsvms", "10"))

        windowsFilerName = args.get("windowsfiler", None)
        linuxFilerName = args.get("linuxfiler", None)

        dataDiskPerVM = int(args.get("datadisk", "2"))

        if linuxCount > 0:
            linuxRootFiler = xenrt.StorageArrayFactory().getStorageArray(xenrt.StorageArrayVendor.NetApp,
                                                                        self.PROTOCOL, specify=linuxFilerName)
            linuxDataFiler = xenrt.StorageArrayFactory().getStorageArray(xenrt.StorageArrayVendor.NetApp,
                                                                        self.PROTOCOL, specify=linuxFilerName)

        if windowsCount > 0:
            windowsRootFiler = xenrt.StorageArrayFactory().getStorageArray(xenrt.StorageArrayVendor.NetApp,
                                                                        self.PROTOCOL, specify=windowsFilerName)
            windowsDataFiler = xenrt.StorageArrayFactory().getStorageArray(xenrt.StorageArrayVendor.NetApp,
                                                                        self.PROTOCOL, specify=windowsFilerName)
        
        self.pool = self.getDefaultHost().getPool()
        [x.enableMultipathing() for x in self.pool.getHosts()]
       
        initiators = self.getInitiators()

        if linuxCount > 0:
            linuxRootFiler.provisionLuns(linuxCount, 10, initiators)
            linuxDataFiler.provisionLuns(linuxCount * dataDiskPerVM, 5, initiators)

        if windowsCount > 0:
            windowsRootFiler.provisionLuns(windowsCount, 30, initiators)
            windowsDataFiler.provisionLuns(windowsCount * dataDiskPerVM, 5, initiators)

        for i in range(linuxCount):
            self.createSR(linuxRootFiler.getLuns()[i], "LinuxRootSR_%d" % i)
            for j in range(dataDiskPerVM):
                self.createSR(linuxDataFiler.getLuns()[i*dataDiskPerVM + j], "LinuxDataSR_%d_%d" % (j, i))

        for i in range(windowsCount):
            self.createSR(windowsRootFiler.getLuns()[i], "WindowsRootSR_%d" % i)
            for j in range(dataDiskPerVM):
                self.createSR(windowsDataFiler.getLuns()[i*dataDiskPerVM + j], "WindowsDataSR_%d_%d" % (j, i))

    def createSR(self, lun, name): 
        raise xenrt.XRTError("Not implemented in base class")

    def getInitiators(self): 
        raise xenrt.XRTError("Not implemented in base class")

class SetupSRsiSCSI(SetupSRsBase):
    PROTOCOL = xenrt.StorageArrayType.iSCSI

    def createSR(self, lun, name):
        sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.pool.master, name)
        sr.create(lun.getISCSILunObj(), noiqnset=True, subtype="lvm")

    def getInitiators(self):
        return dict((x.getName(), {'iqn': x.getIQN()}) for x in self.pool.getHosts())

class SetupSRsFC(SetupSRsBase):
    PROTOCOL = xenrt.StorageArrayType.FibreChannel

    def createSR(self, lun, name):
        sr = xenrt.lib.xenserver.FCStorageRepository(self.pool.master, name)
        sr.create(lun)

    def getInitiators(self):
        return dict(zip(self.pool.getHosts(), [h.getFCWWPNInfo() for h in self.pool.getHosts()]))

class ReconfigureRingSize(xenrt.TestCase):
    def run(self, arglist=[]):
        args = self.parseArgsKeyValue(arglist)
        host = self.getDefaultHost()
        pool = host.getPool()
        if args.get("applyfix", None) == "yes":
            [x.execdom0("cd /opt/xensource/sm && wget -O - http://files.uk.xensource.com/usr/groups/xenrt/sm-lowmem.patch | patch -p1") for x in pool.getHosts()]
        
        srs = host.minimalList("sr-list", args="type=lvmoiscsi")
        srs.extend(host.minimalList("sr-list", args="type=lvmohba"))
        for s in srs:
            host.genParamSet("sr", s, "other-config:mem-pool-size-rings", args['ringsize']) 
            host.genParamSet("sr", s, "other-config:blkback-mem-pool-size-rings", args['ringsize']) 

class CopyVMs(xenrt.TestCase):
    def run(self, arglist=[]):
       
        wingold = self.getGuest("wingold")
        if wingold:
            wingold.setState("DOWN")
        lingold = self.getGuest("lingold")
        if lingold:
            lingold.setState("DOWN")
        host = self.getDefaultHost()

        i = 0
        while True:
            srs = host.minimalList("sr-list", args="name-label=\"LinuxRootSR_%d\"" % i)
            if not srs:
                break
            sr = srs[0]

            g = lingold.copyVM(name="linclone-%d" % i, sruuid=sr)
            xenrt.GEC().registry.guestPut("linclone-%d" % i, g)

            j =0
            while True:
                srs = host.minimalList("sr-list", args="name-label=\"LinuxDataSR_%d_%d\"" % (j,i))
                if not srs:
                    break
                sr = srs[0]
                g.createDisk(4*xenrt.GIGA, sruuid=sr)
                j += 1

            g.start(specifyOn=False)
            i += 1

        i = 0
        while True:
            srs = host.minimalList("sr-list", args="name-label=\"WindowsRootSR_%d\"" % i)
            if not srs:
                break
            sr = srs[0]

            g = wingold.copyVM(name="winclone-%d" % i, sruuid=sr)
            xenrt.GEC().registry.guestPut("winclone-%d" % i, g)

            j =0
            while True:
                srs = host.minimalList("sr-list", args="name-label=\"WindowsDataSR_%d_%d\"" % (j,i))
                if not srs:
                    break
                sr = srs[0]
                g.createDisk(4*xenrt.GIGA, sruuid=sr)
                j += 1

            g.start(specifyOn=False)
            i += 1

class TCMonitorLowMem(xenrt.TestCase):

    def startWindowsWorkload(self, guest):
        workload = testcases.benchmarks.workloads.FIOWindows(guest)
        self.workloads.append(workload)
        workload.start()
    
    def startLinuxWorkload(self, guest):
        workload = testcases.benchmarks.workloads.FIOLinux(guest)
        self.workloads.append(workload)
        workload.start()

    def prepare(self, arglist=[]):
        winguests = []
        linguests = []
        self.workloads = []
        i = 0
        while True:
            g = self.getGuest("winclone-%d" % i)
            if not g:
                break
            winguests.append(g)
            i+=1
        i = 0
        while True:
            g = self.getGuest("linclone-%d" % i)
            if not g:
                break
            linguests.append(g)
            i+=1

        pWindows = map(lambda x: xenrt.PTask(self.startWindowsWorkload, x), winguests)
        pLinux = map(lambda x: xenrt.PTask(self.startLinuxWorkload, x), linguests)
        xenrt.pfarm(pWindows, interval=10)
        xenrt.pfarm(pLinux, interval=10)

    def run(self, arglist=[]):
        args = self.parseArgsKeyValue(arglist)

        minutes = int(args.get("minutes", "10"))
        interval = int(args.get("checkinterval", "1"))

        pool = self.getDefaultHost().getPool()
        for i in xrange(minutes/interval):
            for h in pool.getHosts():
                lowmem = h.execdom0("echo 3 > /proc/sys/vm/drop_caches && grep LowFree /proc/meminfo | cut -d ':' -f 2").strip()
                xenrt.TEC().logverbose("Low Memory on %s: %s" % (h.getName(), lowmem))
            xenrt.sleep(60*interval)

    def postRun(self):
        for w in self.workloads:
            w.stop()

class RebootAllVMs(xenrt.TestCase):
    def run(self, arglist=[]):

        for os in ["win", "lin"]:
            i = 0
            while True:
                g = self.getGuest("%sclone-%d" % (os, i))
                if not g:
                    break
                g.reboot()
                i += 1

class LifeCycleAllVMs(xenrt.TestCase):

    def run(self, arglist=[]):

        failedGuests = []
        failedHosts = []
        numOfGuests = 0

        for os in ["win", "lin"]:
            i = 0
            while True:
                g = self.getGuest("%sclone-%d" % (os, i))
                if not g:
                    break
                g.reboot()

                try:
                    if g.getState() == "UP":
                        #noreachcheck=True will ensure the VNC Snapshot is taken and checked.
                        g.checkHealth(noreachcheck=True)
                        #attachedDisks=True uses all the attached disks.
                        g.verifyGuestFunctional(migrate=True, attachedDisks=True)
                except:
                    xenrt.TEC().warning("Guest %s not up" % (g.getName()))
                    failedGuests.append(g.getName())

                i += 1
                numOfGuests +=1

        if len(failedGuests) > 0:
            raise xenrt.XRTFailure("Failed to perform health checks on %d/%d guests - %s" %
                                    (len(failedGuests), numOfGuests, ", ".join(failedGuests)))

class BaseMultipathScenario(xenrt.TestCase):
    """Base class for all multipath scenarios."""

    # The following params are totally depend on the...
    # current storage configuration on the hosts used in a pool.
    AVAILABLE_PATHS = 2
    PATH_FACTOR = 0.5 # if a path is failed, the remaining paths .
    PATH = None # This is the path connected to FAS2040 NetApp.
    EXPECTED_MPATHS = None # Will be calculated.
    ATTEMPTS = None

    FILER_NEEDED = False
    filerIP = None

    def setTestParams(self, arglist):
        """Set test case params"""

        args = self.parseArgsKeyValue(arglist)

        linuxCount = int(args.get("linuxvms", "10"))
        windowsCount = int(args.get("windowsvms", "10"))
        dataDiskPerVM = int(args.get("datadisk", "2"))
        self.ATTEMPTS = int(args.get("loop", "10"))

        linuxVMSRs = linuxCount + (linuxCount * dataDiskPerVM)
        windowsVMSRs = windowsCount + (windowsCount * dataDiskPerVM)
        self.EXPECTED_MPATHS = linuxVMSRs + windowsVMSRs

        # Obtain the pool object to retrieve its hosts.
        self.pool = self.getDefaultPool()

        if self.FILER_NEEDED:
            # Set up for specific site. Going to assume that there is only one filer.
            filerdict = xenrt.TEC().lookup("NETAPP_FILERS", None)
            filers = filerdict.keys()
            if len(filers) == 0:
                raise xenrt.XRTError("No NETAPP_FILERS defined")
            elif len(filers) > 1:
                raise xenrt.XRTError("Unexpected number of filers. Expected: 1 Present: %s" % len(filers))
            filerName = filers[0]

            self.filerIP = xenrt.TEC().lookup(["NETAPP_FILERS",
                                              filerName,
                                              "TARGET"],
                                             None)

    def checkPathCount(self, host, disabled=False):
        """Verify the host multipath path count for every device"""

        if disabled:
            expectedDevicePaths = self.AVAILABLE_PATHS - (self.PATH_FACTOR * self.AVAILABLE_PATHS)
            pathState = "disabling"
        else:
            expectedDevicePaths = self.AVAILABLE_PATHS
            pathState = "enabling"

        xenrt.TEC().logverbose("checkPathCount on %s after %s the path" % (host, pathState))

        deadline=xenrt.timenow()+ 120 # 120 seconds

        correctPathCount = False
        for attempt in range(1, self.ATTEMPTS+1):
            xenrt.TEC().logverbose("Finding the device paths. Attempt %s " % (attempt))

            mpaths = host.getMultipathInfo(onlyActive=True)

            if len(mpaths) != self.EXPECTED_MPATHS:
                raise xenrt.XRTFailure("Incorrect number of devices (attempt %s) "
                                                        " Found (%s) Expected: %s" %
                                        ((attempt), len(mpaths), self.EXPECTED_MPATHS))

            deviceMultipathCountList = [len(mpaths[scsiid]) for scsiid in mpaths.keys()]
            xenrt.TEC().logverbose("deviceMultipathCountList : %s" % str(deviceMultipathCountList))
            if not len(set(deviceMultipathCountList)) > 1: # ensures that all the entries in the list is same.
                if expectedDevicePaths in deviceMultipathCountList: # expcted paths.
                    if(xenrt.timenow() > deadline):
                        xenrt.TEC().warning("Time to report that all the paths have changed is more than 2 minutes")
                    correctPathCount = True
                    break

            xenrt.sleep(0.5)

        if not correctPathCount:
            raise xenrt.XRTFailure("Incorrect number of device paths found even after attempting %s times" % attempt)

    def disablePath(self, host):
        raise NotImplementedError("Please overwrite the specific functionality needed to disable the path.")

    def enablePath(self, host):
        raise NotImplementedError("Please overwrite the specific functionality needed to recover the path.")

    def run(self, arglist=[]):

        self.setTestParams(arglist)

        # 1. Verify multipath configuration is correct.
        [self.checkPathCount(x) for x in self.pool.getHosts()]

        startTime = xenrt.util.timenow() # used in step (12)
        overallDisableTime = xenrt.util.timenow()
        for host in self.pool.getHosts():
            disableTime = xenrt.util.timenow()
            self.disablePath(host) # 2. Note the time and cause the path to fail.
            self.checkPathCount(host, True) # 3. Wait until XenServer reports that the path has failed (and no longer)

            # 4. Report the elapsed time beween steps 2 and 3 for every host.
            xenrt.TEC().value("PathFail_%s" % host, (xenrt.util.timenow() - disableTime), "s")
            xenrt.TEC().logverbose("Time taken to fail the path on host %s is %s seconds." % 
                                                (host, (xenrt.util.timenow() - disableTime)))

        # 5. Report the elapsed time beween steps 2 and 3 for all hosts.
        xenrt.TEC().value("PathFail_AllHosts", (xenrt.util.timenow() - overallDisableTime), "s")
        xenrt.TEC().logverbose("The overall time taken to fail the path (all hosts) is %s seconds." % 
                                                    (xenrt.util.timenow() - overallDisableTime))

        overallEnableTime = xenrt.util.timenow()
        for host in self.pool.getHosts():
            enableTime = xenrt.util.timenow()
            self.enablePath(host) # 6. Cause the path to be live again.
            self.checkPathCount(host) # 7. Wait until XenServer reports that the path has recovered (and no longer)

            # 8. Report the elapsed time beween steps 6 and 7 for every host.
            xenrt.TEC().value("PathRecover_%s" % host, (xenrt.util.timenow() - enableTime), "s")
            xenrt.TEC().logverbose("Time taken to recover the path on host %s is %s seconds." % 
                                                        (host, (xenrt.util.timenow() - enableTime)))

        # 9. Report the elapsed time beween steps 7 and 8 for all hosts.
        xenrt.TEC().value("PathRecover_AllHosts", (xenrt.util.timenow() - overallEnableTime), "s")
        xenrt.TEC().logverbose("The overall time taken to recover the path (all hosts) is %s seconds." % 
                                                            (xenrt.util.timenow() - overallEnableTime))

        #11. Report the elapsed time between steps 2 and 10.
        xenrt.TEC().value("PathFail_And_Recover", (xenrt.util.timenow() - startTime), "s")
        xenrt.TEC().logverbose("The complete time between path failure and recovery is %s seconds" % 
                                                                        (xenrt.util.timenow() - startTime))

class BaseFailPath(BaseMultipathScenario):
    """Base class for the failure only case."""

    def run(self, arglist=[]):
        self.setTestParams(arglist)

        # 1. Verify multipath configuration is correct.
        [self.checkPathCount(x) for x in self.pool.getHosts()]

        overallDisableTime = xenrt.util.timenow()
        for host in self.pool.getHosts():
            disableTime = xenrt.util.timenow()
            self.disablePath(host) # 2. Note the time and cause the path to fail.
            self.checkPathCount(host, True) # 3. Wait until XenServer reports that the path has failed (and no longer)

            # 4. Report the elapsed time beween steps 2 and 3 for every host.
            xenrt.TEC().value("PathFail_%s" % host, (xenrt.util.timenow() - disableTime), "s")
            xenrt.TEC().logverbose("Time taken to fail the path on host %s is %s seconds." % 
                                                (host, (xenrt.util.timenow() - disableTime)))

        # 5. Report the elapsed time beween steps 2 and 3 for all hosts.
        xenrt.TEC().value("PathFail_AllHosts", (xenrt.util.timenow() - overallDisableTime), "s")
        xenrt.TEC().logverbose("The overall time taken to fail the path (all hosts) is %s seconds." % 
                                                (xenrt.util.timenow() - overallDisableTime))

class BaseRecoverPath(BaseMultipathScenario):
    """Base class for the recover only case."""

    def run(self, arglist=[]):

        self.setTestParams(arglist)

        # 1. Verify the multipath configuration is correct.
        [self.checkPathCount(x, True) for x in self.pool.getHosts()]

        overallEnableTime = xenrt.util.timenow()
        for host in self.pool.getHosts():
            enableTime = xenrt.util.timenow()
            self.enablePath(host) # 2. Cause the path to be live again.
            self.checkPathCount(host) # 3. Wait until XenServer reports that the path has recovered (and no longer)

            # 4. Report the elapsed time beween steps 2 and 3 for every host.
            xenrt.TEC().value("PathRecover_%s" % host, (xenrt.util.timenow() - enableTime), "s")
            xenrt.TEC().logverbose("Time taken to recover the path on host %s is %s seconds." % 
                                                        (host, (xenrt.util.timenow() - enableTime)))

        # 5. Report the elapsed time beween steps 2 and 3 for all hosts.
        xenrt.TEC().value("PathRecover_AllHosts", (xenrt.util.timenow() - overallEnableTime), "s")
        xenrt.TEC().logverbose("The overall time taken to recover the path (all hosts) is %s seconds." % 
                                                            (xenrt.util.timenow() - overallEnableTime))


class FCMPathScenario(BaseMultipathScenario):
    """Base class to test multipath scenarios over fibre channel for a pool of hosts"""
    def disablePath(self, host):
        host.disableFCPort(self.PATH)

    def enablepath(self, host):
        host.enableFCPort(self.PATH)

    def run(self, arglist=[]):
        self.PATH = random.randint(0,1) # to fail & recover.
        BaseMultipathScenario.run(self)

class FCPathFail(BaseFailPath):
    """Test multipath failover scenarios over fibre channel"""
    PATH = 1

    def disablePath(self, host):
        host.disableFCPort(self.PATH)

class FCPathRecover(BaseRecoverPath):
    """Test multipath recover scenarios over fibre channel"""
    PATH = 1

    def enablepath(self, host):
        host.enableFCPort(self.PATH)
        
class ISCSIMPathScenario(BaseMultipathScenario):
    """Test multipath failover scenarios over iscsi"""

    FILER_NEEDED = True

    def disablePath(self, host):
        iptablesFirewall = host.getIpTablesFirewall()
        iptablesFirewall.blockIP(self.filerIP)

    def enablePath(self, host):
        iptablesFirewall = host.getIpTablesFirewall()
        iptablesFirewall.unblockIP(self.filerIP)

class ISCSIPathFail(BaseFailPath):

    FILER_NEEDED = True

    def disablePath(self, host):
        iptablesFirewall = host.getIpTablesFirewall()
        iptablesFirewall.blockIP(self.filerIP)

class ISCSIPathRecover(BaseRecoverPath):

    FILER_NEEDED = True

    def enablePath(self, host):
        iptablesFirewall = host.getIpTablesFirewall()
        iptablesFirewall.unblockIP(self.filerIP)

class EnableHA(xenrt.TestCase):
    """Enable HA on pool of hosts"""

    def run(self, arglist=[]):

        self.pool = self.getDefaultPool()
        self.host = self.getDefaultHost()

        # Pick the first FC SR (LUN) used in guest (either Windows or Linux) root disk as the heartbeat SR.
        srs = self.host.minimalList("sr-list", args="name-label=\"LinuxRootSR_0\"")
        if not srs:
            srs = self.host.minimalList("sr-list", args="name-label=\"WindowsRootSR_0\"")
            if not srs:
                raise xenrt.XRTFailure("No SR detected in the pool to be used as heartbeat SR")

        # Enable HA on the pool.
        self.pool.enableHA(srs=srs)
