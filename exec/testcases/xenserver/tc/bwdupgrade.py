# XenRT: Test harness for Xen and the XenServer product family
#
# Borehamwood Rolling Pool Upgrade (RPU)testcases
#
# Copyright (c) 2014 Citrix Systems Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#
import socket, re, string, time, traceback, sys, random, copy, os, shutil
import os.path
import IPy
import xenrt, xenrt.lib.xenserver, xenrt.lib.xenserver.call, xenrt.lib.xenserver.context
import testcases.xenserver.tc.lunpervdi

class TCRpuBwd(testcases.xenserver.tc.lunpervdi.TCBwdEnvironment):
    """Clearwater Borehamwood to Creedence rolling pool upgrade test using RawHBA SR"""

    def run(self, arglist=[]):
        # Prepare the basic borehamwood environment.
        testcases.xenserver.tc.lunpervdi.TCBwdEnvironment.run(self, arglist=[])
    
        self.upgrader = xenrt.lib.xenserver.host.RollingPoolUpdate(self.pool, 'Creedence')
        
        # Perform upgrade.
        self.newPool = self.pool.upgrade(poolUpgrade=self.upgrader) 
        self.newPool.verifyRollingPoolUpgradeInProgress(expected=False)

        # Enable borehamwood plugins after upgrade.
        for host in self.newPool.getHosts():
            self.enableBorehamwood(host)

        # Verify whether the RawHBA SR has all VDIs that is created in Clearwater environment.
        # Expecting 10 VDIs as we have created 10 LUNs by default.
        self.checkSR()

        # Check the VMs are healthy.
        for guest in self.guests:
            # Logs?
            guest.shutdown()
            guest.start()
            guest.reboot()
            guest.suspend()
            guest.resume()
            guest.shutdown()
