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
    def run(self, arglist=[]):
        args = self.parseArgsKeyValue(arglist)

        linuxLunCount = int(args.get("linuxvms", "10")) * 3
        windowsLunCount = int(args.get("windowsvms", "10")) * 3

        windowsFilerName = args.get("windowsfiler", None)
        linuxFilerName = args.get("linuxfiler", None)

        linuxFiler = xenrt.StorageArrayFactory().getStorageArray(xenrt.StorageArrayVendor.NetApp, xenrt.StorageArrayType.iSCSI, specify=linuxFilerName)
        windowsFiler = xenrt.StorageArrayFactory().getStorageArray(xenrt.StorageArrayVendor.NetApp, xenrt.StorageArrayType.iSCSI, specify=windowsFilerName)


        pool = self.getDefaultHost().getPool()
        [x.enableMultipathing() for x in pool.getHosts()]
        initiators = dict((x.getName(), {'iqn': x.getIQN()}) for x in pool.getHosts())

        linuxFiler.provisionLuns(linuxLunCount, 10, initiators)
        windowsFiler.provisionLuns(windowsLunCount, 30, initiators)

        i = 0
        for lun in linuxFiler.getLuns():
            sr = xenrt.lib.xenserver.ISCSIStorageRepository(pool.master, "LinuxSR_%d" % i)
            sr.create(lun.getISCSILunObj(), noiqnset=True, subtype="lvm")
            i+=1
        i = 0
        for lun in windowsFiler.getLuns():
            sr = xenrt.lib.xenserver.ISCSIStorageRepository(pool.master, "WindowsSR_%d" % i)
            sr.create(lun.getISCSILunObj(), noiqnset=True, subtype="lvm")
            i+=1

class CopyVMs(xenrt.TestCase):
    def run(self, arglist=[]):
       
        wingold = self.getGuest("wingold")
        wingold.setState("DOWN")
        lingold = self.getGuest("lingold")
        lingold.setState("DOWN")
        host = self.getDefaultHost()

        i = 0
        while True:
            srs = host.minimalList("sr-list", args="name-label=\"LinuxSR_%d\"" % i)
            if not srs:
                break
            sr = srs[0]

            g = lingold.copyVM(name="linclone-%d" % i, sruuid=sr)
            xenrt.GEC().registry.guestPut("linclone-%d" % i, g)
            srs = host.minimalList("sr-list", args="name-label=\"LinuxSR_%d\"" % (i+1))
            if not srs:
                break
            sr = srs[0]
            g.createDisk(8*xenrt.GIGA, sruuid=sr)
            
            srs = host.minimalList("sr-list", args="name-label=\"LinuxSR_%d\"" % (i+2))
            if not srs:
                break
            sr = srs[0]
            g.createDisk(8*xenrt.GIGA, sruuid=sr)

            g.start(specifyOn=False)
            i += 3
        
        i = 0
        while True:
            srs = host.minimalList("sr-list", args="name-label=\"WindowsSR_%d\"" % i)
            if not srs:
                break
            sr = srs[0]

            g = wingold.copyVM(name="winclone-%d" % i, sruuid=sr)
            xenrt.GEC().registry.guestPut("winclone-%d" % i, g)
            
            srs = host.minimalList("sr-list", args="name-label=\"WindowsSR_%d\"" % (i+1))
            if not srs:
                break
            sr = srs[0]
            g.createDisk(8*xenrt.GIGA, sruuid=sr)
            
            srs = host.minimalList("sr-list", args="name-label=\"WindowsSR_%d\"" % (i+2))
            if not srs:
                break
            sr = srs[0]
            g.createDisk(8*xenrt.GIGA, sruuid=sr)

            g.start(specifyOn=False)
            i += 3
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
