#
# XenRT: Test harness for Xen and the XenServer product family
#
# Testcases for measuring vdi copy performance metrics
#
# Copyright (c) 2014 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and conditions 
# as licensed by Citrix Systems, Inc. All other rights reserved.
#
import string, time, re, os.path, json, random, xml.dom.minidom
import sys, traceback
import xenrt
from xenrt.lazylog import *

class _VDICopyPerf(xenrt.TestCase):
    """Base class for testcases that measures vdi-copy between different SR types"""

    SCENARIO = None
    FROM_TYPE = None
    TO_TYPE = None
    SAME_HOST = True 
    GUEST_NAME = "Windows81"
    ITERATIONS = 10
    INTERVAL = 60

    def prepare(self, arglist):

        # Get the pool
        newPool = self.getDefaultPool()

        # Check we have 2 hosts
        if len(newPool.getHosts()) < 2:
            raise xenrt.XRTError("Pool must have atleast 2 hosts")

        if self.SAME_HOST:
                self.srcHost = newPool.master
                self.destHost = self.srcHost
        else:
            self.srcHost = newPool.master
            self.destHost =   self.getHost("RESOURCE_HOST_1")
            
        # Get the guest already installed on the pool.  
        self.guest = self.srcHost.getGuest(self.GUEST_NAME)
        
        if not self.guest:
            raise xenrt.XRTError("Could not find a guest with name %s" % self.GUEST_NAME)

        self.cli = self.srcHost.getCLIInstance()

        # Get the two SRs
        fromSRs = self.srcHost.getSRs(type=self.FROM_TYPE)
        if len(fromSRs) == 0:
            raise xenrt.XRTError("Could not find %s SR on the host" %
                                                        (self.FROM_TYPE))
        self.fromSR = fromSRs[0]
        
        toSRs = self.destHost.getSRs(type=self.TO_TYPE)
        if len(toSRs) == 0:
            raise xenrt.XRTError("Could not find %s SR on the host" %
                                                        (self.TO_TYPE))
        self.toSR = toSRs[0]

                # Initial set of vdi performance parameters.
        self.vdiCopyPerfResults = {}
        self.vdiCopyPerfResults["fromSR"] = self.FROM_TYPE
        self.vdiCopyPerfResults["toSR"] = self.TO_TYPE
        self.vdiCopyPerfResults["scenario"] = self.SCENARIO

    def run(self, arglist):

        # Check guest is running
        if self.guest.getState() == "DOWN":
            self.guest.start()
            time.sleep(300)

        # Retrieve the guest disk UUID.
        self.guestVdiUuid = self.guest.getAttachedVDIs()[0]
        self.guest.shutdown()
        
        self.vdi_size = int(self.srcHost.genParamGet("vdi", self.guestVdiUuid, "virtual-size"))
        self.vdiCopyPerfResults["vdi-virtual-size-in-bytes"] = self.vdi_size        
        
        # Measuring vdi copy time for performance evaluation.
        xenrt.TEC().logverbose("Scenario:[%s] Attempting to copy the VDI from %s SR to %s SR" %
                                                            (self.SCENARIO, self.FROM_TYPE, self.TO_TYPE))

        args = []
        args.append("uuid=%s" % (self.guestVdiUuid))
        args.append("sr-uuid=%s" % (self.toSR))

        timeRecords = []

        # For normalization purpose, we run the copy at least 3 times)
        assert(self.ITERATIONS >= 3)
        for i in range(self.ITERATIONS): 
            timeNow = xenrt.util.timenow(True)
            newVdiUuid = self.cli.execute("vdi-copy", string.join(args)).strip()
            self.srcHost.execdom0("sync")
            if self.destHost != self.srcHost: self.destHost.execdom0("sync")
            timeDiff =  xenrt.util.timenow(True)- timeNow
            timeRecords.append(timeDiff)
            self.cli.execute("vdi-destroy", "uuid=%s" % (newVdiUuid))
            time.sleep(self.INTERVAL)

        timeNorm = (sum(timeRecords) - max(timeRecords) - min(timeRecords)) / (self.ITERATIONS - 2)
        self.vdiCopyPerfResults["vdi-copy-time-in-seconds"] = timeRecords
        xenrt.TEC().logverbose("Time taken to copy the populated VDI (in seconds): %s " % timeRecords)
        self.vdiCopyPerfResults["vdi-copy-time-in-seconds-normalized"] = timeNorm
        xenrt.TEC().logverbose("Normalized time taken to copy the populated VDI (in seconds): %s" % timeNorm)


    def postRun(self):
        # Writing the measured vdi copy performance parameters.
        f = open("%s/vdicopytime.json" % (xenrt.TEC().getLogdir()), "w")
        f.write(json.dumps(self.vdiCopyPerfResults))
        f.close()

class TC21567(_VDICopyPerf):
    """Single host vdi copy performance test with no network storage involved"""

    SAME_HOST = True
    FROM_TYPE = "lvm"
    TO_TYPE = "lvm"
    SCENARIO = "IntraHost-LocalSR-To-LocalSR"

class TC21568(_VDICopyPerf):
    """Single host vdi copy performance test with network storage involved"""

    SAME_HOST = True
    FROM_TYPE = "lvm"
    TO_TYPE = "nfs"
    SCENARIO = "IntraHost-LocalSR-To-NetworkSR"

class TC21569(_VDICopyPerf):
    """Inter hosts vdi copy performance test between two SRs"""

    SAME_HOST = False
    FROM_TYPE = "lvm"
    TO_TYPE = "ext"
    SCENARIO = "InterHost-LocalSR-To-LocalSR"
