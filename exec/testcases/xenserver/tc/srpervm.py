# XenRT: Test harness for Xen and the XenServer product family
#
# Test cases for issues with lots of SRs.
#
# Copyright (c) 2012 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt
import testcases.benchmarks.workloads

class SetupSRs(xenrt.TestCase):

    def createSR(self, lun, name):
        sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.pool.master, name)
        sr.create(lun, noiqnset=True, subtype="lvm")
        if self.ringsize != None:
            sr.paramSet("other-config:blkback-mem-pool-size-rings", self.ringsize)

    def run(self, arglist=[]):
        args = self.parseArgsKeyValue(arglist)

        linuxLunCount = int(args.get("linuxvms", "10"))
        windowsLunCount = int(args.get("windowsvms", "10"))

        windowsFilerName = args.get("windowsfiler", None)
        linuxFilerName = args.get("linuxfiler", None)
        self.ringsize = args.get("ringsize", None)

        linuxRootFiler = xenrt.StorageArrayFactory().getStorageArray(xenrt.StorageArrayVendor.NetApp, xenrt.StorageArrayType.iSCSI, specify=linuxFilerName)
        linuxDataFiler = xenrt.StorageArrayFactory().getStorageArray(xenrt.StorageArrayVendor.NetApp, xenrt.StorageArrayType.iSCSI, specify=linuxFilerName)
        windowsRootFiler = xenrt.StorageArrayFactory().getStorageArray(xenrt.StorageArrayVendor.NetApp, xenrt.StorageArrayType.iSCSI, specify=windowsFilerName)
        windowsDataFiler = xenrt.StorageArrayFactory().getStorageArray(xenrt.StorageArrayVendor.NetApp, xenrt.StorageArrayType.iSCSI, specify=windowsFilerName)


        self.pool = self.getDefaultHost().getPool()
        [x.enableMultipathing() for x in self.pool.getHosts()]
        initiators = dict((x.getName(), {'iqn': x.getIQN()}) for x in self.pool.getHosts())

        linuxRootFiler.provisionLuns(linuxLunCount, 10, initiators)
        linuxDataFiler.provisionLuns(linuxLunCount * 2, 5, initiators)
        windowsRootFiler.provisionLuns(windowsLunCount, 30, initiators)
        windowsDataFiler.provisionLuns(windowsLunCount * 2, 5, initiators)

        for i in range(linuxLunCount):
            self.createSR(linuxRootFiler.getLuns()[i].getISCSILunObj(), "LinuxRootSR_%d" % i)
            self.createSR(linuxDataFiler.getLuns()[i*2].getISCSILunObj(), "LinuxDataSR_A%d" % i)
            self.createSR(linuxDataFiler.getLuns()[i*2+1].getISCSILunObj(), "LinuxDataSR_B%d" % i)
            
        for i in range(windowsLunCount):
            self.createSR(windowsRootFiler.getLuns()[i].getISCSILunObj(), "WindowsRootSR_%d" % i)
            self.createSR(windowsDataFiler.getLuns()[i*2].getISCSILunObj(), "WindowsDataSR_A%d" % i)
            self.createSR(windowsDataFiler.getLuns()[i*2+1].getISCSILunObj(), "WindowsDataSR_B%d" % i)

class CopyVMs(xenrt.TestCase):
    def run(self, arglist=[]):
       
        wingold = self.getGuest("wingold")
        wingold.setState("DOWN")
        lingold = self.getGuest("lingold")
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
            
            sr = host.minimalList("sr-list", args="name-label=\"LinuxDataSR_A%d\"" % (i))[0]
            g.createDisk(4*xenrt.GIGA, sruuid=sr)
            
            sr = host.minimalList("sr-list", args="name-label=\"LinuxDataSR_B%d\"" % (i))[0]
            g.createDisk(4*xenrt.GIGA, sruuid=sr)

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
            
            sr = host.minimalList("sr-list", args="name-label=\"WindowsDataSR_A%d\"" % (i))[0]
            g.createDisk(4*xenrt.GIGA, sruuid=sr)
            
            sr = host.minimalList("sr-list", args="name-label=\"WindowsDataSR_B%d\"" % (i))[0]
            g.createDisk(4*xenrt.GIGA, sruuid=sr)

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
        for i in xrange(minutes):
            for h in pool.getHosts():
                lowmem = h.execdom0("echo 3 > /proc/sys/vm/drop_caches && grep LowFree /proc/meminfo | cut -d ':' -f 2").strip()
                xenrt.TEC().logverbose("Low Memory on %s: %s" % (h.getName(), lowmem))
            xenrt.sleep(60*interval)

    def postRun(self):
        for w in self.workloads:
            w.stop()