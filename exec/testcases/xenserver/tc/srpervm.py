# XenRT: Test harness for Xen and the XenServer product family
#
# Test cases for issues with lots of SRs.
#
# Copyright (c) 2012 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt
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
        sr.create(lun.getId())

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

class FCMultipathScenario(xenrt.TestCase):
    """Base class to test multipath scenarios over fibre channel"""

    # The following params are totally depend on the current storage configuration.
    PATHS = 2
    PATH_FACTOR = 0.5
    PATH_TO_FAIL = 1 # this is the path connected to FAS2040 NetApp.

    EXPECTED_MPATHS = None # will be calculated.
    ATTEMPTS = 10
    NO_OF_SRS = None

    def setTestParams(self):
        """Set test params"""

        args = self.parseArgsKeyValue(arglist)

        linuxCount = int(args.get("linuxvms", "10"))
        windowsCount = int(args.get("windowsvms", "10"))
        dataDiskPerVM = int(args.get("datadisk", "2"))

        linuxVMSRs = linuxCount + (linuxCount * dataDiskPerVM)
        windowsVMSRs = windowsCount + (windowsCount * dataDiskPerVM)
        self.NO_OF_SRS = linuxVMSRs + windowsVMSRs

        self.pool = self.getDefaultHost().getPool()
        self.host = self.pool.master # multipathing is host specific. hence master.

    def checkMultipathsConfig(self, disabled=False):
        """Verify the multipath configuration is correct"""

        attempts = 1
        while True:
            xenrt.TEC().logverbose("Finding the total number of devices. Attempt %s " % attempts)
            mpaths = self.host.getMultipathInfo()
            if len(mpaths) != self.EXPECTED_MPATHS:
                attempts = attempts + 1
            else:
                xenrt.TEC().logverbose("Total number of devices in the system = %s" % len(mpaths))
                break # expected result.

            if attempts > self.ATTEMPTS:
                raise xenrt.XRTFailure("Incorrect number of devices even after attempting %s times"
                                                                            " Found (%s) Expected: %s" %
                                                            ((attempts-1), len(mpaths), self.EXPECTED_MPATHS))
            xenrt.sleep(30) # wait for 30 seconds.

        if disabled:
            expectedDevicePaths = self.PATHS - (self.PATH_FACTOR * self.PATHS)
        else:
            expectedDevicePaths = self.PATHS

        for scsiid in mpaths.keys():
            attempts = 1
            while True:
                xenrt.TEC().logverbose("Finding the device paths for scsiid %s. Attempt %s " % (scsiid, attempts))
                paths = len(self.host.getMultipathInfo()[scsiid])
                if paths != expectedDevicePaths:
                    attempts = attempts + 1
                else:
                    xenrt.TEC().logverbose("Number of device paths = %s" % paths)
                    break # expected result.

                if attempts > self.ATTEMPTS:
                    raise xenrt.XRTFailure("Incorrect number of device paths even after attempting %s times"
                                                                                    " Found (%s) Expected: %s" %
                                                                        ((attempts-1), paths, expectedDevicePaths))
                xenrt.sleep(15) # wait for 15 seconds.

    def waitForPathChange(self):
        """Wait until XenServer reports that the path has failed (and no longer) /recovered"""

        startTime = xenrt.util.timenow()
        deadline = startTime + 150 # to be precise, the events received during the last 120 seconds.
        found = False
        while not found:
            mpathAlert = self.host.minimalList("message-list")
            for messageUUID in mpathAlert:
                messageTitle = self.host.genParamGet("message", messageUUID, "name")
                messageTime = xenrt.parseXapiTime(self.host.genParamGet("message", messageUUID, "timestamp"))

                if messageTitle == "MULTIPATH_PERIODIC_ALERT" and messageTime > startTime:
                    xenrt.TEC().logverbose("MULTIPATH_PERIODIC_ALERT FOUND")
                    found = True # we found the required message.
                    break

            if xenrt.util.timenow() > deadline:
                raise xenrt.XRTError("The multipath alert is not received during the last 120 seconds")
            xenrt.sleep(15)

    def run(self, arglist=[]):

        args = self.parseArgsKeyValue(arglist)

        linuxCount = int(args.get("linuxvms", "10"))
        windowsCount = int(args.get("windowsvms", "10"))
        dataDiskPerVM = int(args.get("datadisk", "2"))

        linuxVMSRs = linuxCount + (linuxCount * dataDiskPerVM)
        windowsVMSRs = windowsCount + (windowsCount * dataDiskPerVM)
        self.NO_OF_SRS = linuxVMSRs + windowsVMSRs

        self.pool = self.getDefaultHost().getPool()
        self.host = self.pool.master # multipathing is host specific. hence master.
        self.EXPECTED_MPATHS = self.NO_OF_SRS

        #1. verify the multipath configuration is correct.
        self.checkMultipathsConfig()

        # 2. note the time and cause the path to fail.
        disableStartTime = xenrt.util.timenow()
        startTime = xenrt.util.timenow() # used in step 10.
        self.host.disableFCPort(self.PATH_TO_FAIL)

        # 3. wait until XenServer reports that the path has failed (and no longer)
        self.waitForPathChange()

        # 4. report the elapsed time beween steps 2 and 3.
        xenrt.TEC().logverbose("Time taken to fail the path is %s seconds." % 
                                            (xenrt.util.timenow() - disableStartTime))

        #5 verify again the multipath configuration is correct.
        self.checkMultipathsConfig(True)

        #6. cause the path to be live again.
        enableStartTime = xenrt.util.timenow()
        self.host.enableFCPort(self.PATH_TO_FAIL)

        #7. wait until XenServer reports that the path has recovered (and no longer)
        self.waitForPathChange()

        #8. report the elapsed time between steps 6 and 7.
        xenrt.TEC().logverbose("Time taken to recover the path is %s seconds." % 
                                            (xenrt.util.timenow() - enableStartTime))

        #9. verify again the multipath configuration is correct.
        self.checkMultipathsConfig()

        #10. report the elapsed time between steps 2 and 9.
        xenrt.TEC().logverbose("Time between path failure and recovery on a single host without HA enabled is %s seconds" % 
                                                                                            (xenrt.util.timenow() - startTime))

class FailMultipath(FCMultipathScenario):
    """Test multipath failover scenarios over fibre channel"""

    def run(self, arglist=[]):

        self.setTestParams()

        self.EXPECTED_MPATHS = self.NO_OF_SRS

        # 1. verify multipath configuration is correct.
        self.checkMultipathsConfig()

        # 2. note the time and cause the path to fail.
        disableStartTime = xenrt.util.timenow()
        self.host.disableFCPort(self.PATH_TO_FAIL)

        # 3. wait until XenServer reports that the path has failed (and no longer)
        self.waitForPathChange()

        # 4. report the elapsed time beween steps 2 and 3.
        xenrt.TEC().logverbose("Time taken to fail the path is %s seconds." % 
                                            (xenrt.util.timenow() - disableStartTime))

        # 5. verify again the multipath configuration is correct.
        self.EXPECTED_MPATHS = self.NO_OF_SRS * self.PATH_FACTOR
        self.checkMultipathsConfig(True)

class RecoverMultipath(FCMultipathScenario):
    """Test multipath recover scenarios over fibre channel"""

    def run(self, arglist=[]):

        self.setTestParams()

        self.EXPECTED_MPATHS = self.NO_OF_SRS * self.PATH_FACTOR

        # 1. verify the multipath configuration is correct.
        self.checkMultipathsConfig()

        # 2. cause the path to be live again.
        enableStartTime = xenrt.util.timenow()
        self.host.enableFCPort(self.PATH_TO_FAIL)

        # 3. wait until XenServer reports that the path has recovered (and no longer)
        self.waitForPathChange()

        # 4. report the elapsed time between steps 2 and 3.
        xenrt.TEC().logverbose("Time taken to recover the path is %s seconds." % 
                                            (xenrt.util.timenow() - enableStartTime))

        # 5. verify again the multipath configuration is correct.
        self.EXPECTED_MPATHS = self.NO_OF_SRS
        self.checkMultipathsConfig()

class ISCSIMPathScenario(xenrt.TestCase):
    """Test multipath failover scenarios over iscsi"""

    def checkMultipathsConfig(self, disabled=False):
        """Verify the multipath configuration is correct"""

        mpaths = self.host.getMultipathInfo()
        xenrt.TEC().logverbose("Should be 12 SRs with current test config.")
        xenrt.TEC().logverbose("Number of active 'paths' : %s" % len(mpaths))

    def waitForPathChange(self):
        """Wait until XenServer reports that the path has failed (and no longer) /recovered"""

        startTime = xenrt.util.timenow()
        deadline = startTime + 240 # to be precise, the events received during the last 240 seconds.
        found = False
        while not found:
            mpathAlert = self.host.minimalList("message-list")
            for messageUUID in mpathAlert:
                messageTitle = self.host.genParamGet("message", messageUUID, "name")
                messageTime = xenrt.parseXapiTime(self.host.genParamGet("message", messageUUID, "timestamp"))

                xenrt.TEC().logverbose("AlertName : %s" % (messageTitle))

                if messageTitle == "MULTIPATH_PERIODIC_ALERT" and messageTime > startTime:
                    xenrt.TEC().logverbose("MULTIPATH_PERIODIC_ALERT FOUND")
                    found = True # we found the required message.
                    break

            if xenrt.util.timenow() > deadline:
                raise xenrt.XRTError("The multipath alert is not received during the last 240 seconds")
            xenrt.sleep(15)

        xenrt.TEC().logverbose("FOUND : %s" % (found))

    def run(self, arglist=[]):
        self.pool = self.getDefaultHost().getPool()
        self.host = self.pool.master

        # Port 3260, and then desired interface.
        interface = "eth0"
        port = 3260

        # Check number of paths.
        self.checkMultipathsConfig()
        
        # For each host in the pool, can do the steps.
        for host in self.pool.getHosts():
            # Fail path
            # Using IP tables block the port on interface, think it is enough for XS to pick up on.
            # host.execdom0("iptables -I INPUT -i % --destination-port %s -j DROP" % (interface, port))
            # host.execdom0("iptables -I OUTPUT -o %s --destination-port %s -j DROP" % (interface, port))
            
            host.execdom0("iptables -I INPUT -i %s -j DROP" % (interface))
            host.execdom0("iptables -I OUTPUT -o %s -j DROP" % (interface))
            
            self.waitForPathChange()
        
        self.checkMultipathsConfig()
        # Fix the path
        # self.host.execdom0("iptables -I INPUT -i %s -p tcp --destination-port %s -j ACCEPT" % (interface, port))
