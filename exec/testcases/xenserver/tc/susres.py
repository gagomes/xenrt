#
# XenRT: Test harness for Xen and the XenServer product family
#
# Testcases for suspend/resume features
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and conditions
# as licensed by Citrix Systems, Inc. All other rights reserved.
#

import time
import xenrt

class TC6855(xenrt.TestCase):
    """Intel <-> AMD Windows suspend/resume compatability tests"""

    def __init__(self, tcid="TC6855"):
        xenrt.TestCase.__init__(self, tcid)

    def run(self, arglist=None):

        stresstime = 300
        workloads = ["Prime95", "SQLIOSim"]

        versions = ["w2k3eesp2", 
                    "w2k3eesp2-x64", 
                    "vistaee"]

        h0 = self.getHost("RESOURCE_HOST_0")
        h1 = self.getHost("RESOURCE_HOST_1")
        
        for version in versions: 
            # Test both directions.
            for direction in [(h0,h1), (h1,h0)]:
                g = {"host":direction[0],
                     "guestname":xenrt.util.randomGuestName(),
                     "distro":version,
                     "vifs":[(0, None, 
                             xenrt.randomMAC(), None)]}
                guest = xenrt.lib.xenserver.guest.createVM(**g)
                guest.installDrivers()
                guest.suspend()
                guest.resume(on=direction[1])
                # Run some stress tests.
                work = guest.startWorkloads(workloads) 
                time.sleep(stresstime)
                guest.stopWorkloads(work)
                for w in work:
                    w.check()
                guest.shutdown()
