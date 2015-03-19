#
# XenRT: Test harness for Xen and the XenServer product family
#
# VM install standalone testcases
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy
import xenrt, xenrt.lib.xenserver

class _TCVMInstall(xenrt.TestCase):
    METHOD=None
    def prepare(self, arglist):
        (self.distro, self.arch) = xenrt.getDistroAndArch(self.tcsku)
        self.host = self.getDefaultHost()
        
        if self.METHOD == "CDROM":
            self.repository = "cdrom"
        else:
            r = xenrt.TEC().lookup(["RPM_SOURCE", self.distro, self.arch, self.METHOD], None)
            if not r:
                raise xenrt.XRTError("No %s repository for %s %s" %
                                     (self.METHOD, self.arch, self.distro))
            self.repository = string.split(r)[0]
      
    def run(self, arglist):
        # Choose a template
        template = xenrt.lib.xenserver.getTemplate(self.host, self.distro, arch=self.arch)

        # Create an empty guest object
        guest = self.host.guestFactory()(xenrt.randomGuestName(self.distro, self.arch), template, self.host)
        self.uninstallOnCleanup(guest)
        self.getLogsFrom(guest)

        # Install the VM
        guest.arch = self.arch
        if self.METHOD=="CDROM":
            isoname = xenrt.DEFAULT
        else:
            isoname = None
        guest.install(self.host,
                      repository=self.repository,
                      distro=self.distro,
                      method=self.METHOD,
                      isoname=isoname)
        guest.check()

        # Quick check of basic functionality
        guest.reboot()
        guest.suspend()
        guest.resume()
        guest.check()
        guest.shutdown()
        guest.start()
        guest.check()

        # Shutdown the VM
        guest.shutdown()

class TCISOInstall(_TCVMInstall):
    METHOD="CDROM"

class TCHTTPInstall(_TCVMInstall):
    METHOD="HTTP"

class TCNFSInstall(_TCVMInstall):
    METHOD="NFS"

