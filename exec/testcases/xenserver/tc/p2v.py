#
# XenRT: Test harness for Xen and the XenServer product family
#
# Linux P2V
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy
import xenrt, xenrt.lib.xenserver

class _TCLinuxP2V(xenrt.TestCase):

    ARCH = "x86-32"
    DISTRO = None

    def prepare(self, arglist=None):

        # Assume the target host is RESOURCE_HOST_1
        self.targethost = self.getHost("RESOURCE_HOST_1")

        # Install native Linux on the P2V host
        mname = xenrt.TEC().lookup("RESOURCE_HOST_0")
        m = xenrt.PhysicalHost(mname)
        xenrt.GEC().startLogger(m)
        self.p2vhost = xenrt.lib.native.NativeLinuxHost(m)
        self.getLogsFrom(self.p2vhost)
        self.p2vhost.installLinuxVendor(self.DISTRO)
        
    def run(self, arglist):

        if self.runSubcase("p2v", (), "P2V", "P2V") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("lifecycle", (), "VM", "Lifecycle") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("suspendresume", (), "VM", "SuspendResume") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("migrate", ("true"), "VM", "LiveMigrate") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("shutdown", (), "VM", "Shutdown") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("uninstall", (), "VM", "Uninstall") != \
                xenrt.RESULT_PASS:
            return

    def p2v(self):
        self.guest = self.targethost.p2v(xenrt.randomGuestName(),
                                         self.DISTRO,
                                         self.p2vhost)
        self.uninstallOnCleanup(self.guest)

    def lifecycle(self):
        # Perform some lifecycle operations
        self.guest.reboot()
        self.guest.waitForAgent(180)
        self.guest.reboot()
        self.guest.waitForAgent(180)
        self.guest.shutdown()
        self.guest.start()
        self.guest.check()
        self.guest.waitForAgent(180)

    def suspendresume(self):
        self.guest.suspend()
        self.guest.resume()
        self.guest.check()
        self.guest.suspend()
        self.guest.resume()
        self.guest.check()

    def migrate(self, live):
        self.guest.migrateVM(self.guest.host, live=live)
        time.sleep(10)
        self.guest.check()
        self.guest.migrateVM(self.guest.host, live=live)
        time.sleep(10)
        self.guest.check()

    def shutdown(self):
        self.guest.shutdown()

    def uninstall(self):
        self.guest.uninstall()

class TC8048(_TCLinuxP2V):
    """P2V of a RHEL3.8 host"""
    DISTRO = "rhel38"

class TC8049(_TCLinuxP2V):
    """P2V of a RHEL4.4 host"""
    DISTRO = "rhel44"

class TC8050(_TCLinuxP2V):
    """P2V of a SLES9SP2 host"""
    DISTRO = "sles92"

class TC8088(_TCLinuxP2V):
    """P2V of a RHEL4.6 host"""
    DISTRO = "rhel46"

class TC8089(_TCLinuxP2V):
    """P2V of a SLES9SP3 host"""
    DISTRO = "sles93"

class TC8090(_TCLinuxP2V):
    """P2V of a CentOS 4.6 host"""
    DISTRO = "centos46"

class TC8215(_TCLinuxP2V):
    """P2V of a SLES9SP4 host"""
    DISTRO = "sles94"
