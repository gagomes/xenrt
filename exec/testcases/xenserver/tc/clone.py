#
# XenRT: Test harness for Xen and the XenServer product family
#
# Testcases for VM cloning
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and conditions
# as licensed by Citrix Systems, Inc. All other rights reserved.
#

import string, os, os.path, copy, re, time
import xenrt

class _CloneBase(xenrt.TestCase):
    """Base class for clone testcases"""
    WINDOWS = False

    def updateOriginal(self, guest):
        pass

    def prepare(self, arglist):
        # Install the VM we'll clone
        self.host = self.getDefaultHost()
        if self.WINDOWS:
            self.orig = self.host.createGenericWindowsGuest()
        else:
            self.orig = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.orig)
        self.updateOriginal(self.orig)
        self.orig.preCloneTailor()
        self.orig.shutdown()

    def cloneVM(self):
        self.clone = self.orig.cloneVM()
        self.uninstallOnCleanup(self.clone)

    def checkVM(self, original):
        if original:
            g = self.orig
        else:
            g = self.clone
        if g.getState() != "UP":
            g.start()
        g.check()

    def uninstallVM(self, original):
        if original:
            g = self.orig
        else:
            g = self.clone
        if g.getState() != "DOWN":
            g.shutdown()
        g.uninstall()

    def run(self,arglist):

        if self.runSubcase("cloneVM", (), "Original", "Clone") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("checkVM", (False), "Clone", "Check") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("checkVM", (True), "Original", "Check") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("checkVM", (False), "Clone", "Check2") != \
                xenrt.RESULT_PASS:
            return
        self.orig.shutdown()
        self.clone.shutdown()
        if self.runSubcase("uninstallVM", (True), "Original", "Uninstall") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("checkVM", (False), "Clone", "Check3") != \
                xenrt.RESULT_PASS:
            return
        self.clone.shutdown()
        if self.runSubcase("uninstallVM", (False), "Clone", "Uninstall") != \
                xenrt.RESULT_PASS:
            return

class TC6919(_CloneBase):
    """Basic cloning of a Windows VM."""
    WINDOWS = True

class TC6920(_CloneBase):
    """Basic cloning of a Linux VM."""

class TC6921(_CloneBase):
    """Clone a VM with multiple virtual devices"""

    def updateOriginal(self, guest):
        # Add additional VIF and VBD
        guest.createDisk(sizebytes=104857600) # 100MB
        guest.createVIF(None,None,None) # Defaults

        # Reboot the guest so it picks up new devices
        guest.reboot()
        return guest

class TC6922(_CloneBase):
    """Clone a VM with non-default configuration"""

    def updateOriginal(self, guest):
        # Set non default memory and vcpus
        mem = guest.memget() # in MB
        vcpus = guest.cpuget()

        # Shutdown, update settings and start (can't reboot as if we change
        # static max while its running it will be rejected in MNR+)
        guest.shutdown()
        guest.memset(mem+128)        
        guest.cpuset(vcpus+1)
        guest.start()

