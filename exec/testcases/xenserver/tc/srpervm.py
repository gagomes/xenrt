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
