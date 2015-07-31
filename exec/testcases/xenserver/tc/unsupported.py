#
# XenRT: Test harness for Xen and the XenServer product family
#
# Smoke tests of unsupported operating systems
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy
import xenrt, xenrt.lib.xenserver

class _TC6460(xenrt.TestCase):

    DISTRO = None
    ARCH = None

    def run(self, arglist):

        distro = self.DISTRO
        arch = self.ARCH

        repository = xenrt.getLinuxRepo(distro, arch, "HTTP")
        # Get a host to install on
        host = self.getDefaultHost()

        # Choose a template
        template = host.chooseTemplate("TEMPLATE_NAME_UNSUPPORTED_HVM")

        # Create an empty guest object
        guest = host.guestFactory()(xenrt.randomGuestName(), template)
        self.uninstallOnCleanup(guest)
        self.getLogsFrom(guest)

        # Install from RPM repo into the VM
        guest.arch = arch
        guest.windows = False
        guest.setVCPUs(2)
        guest.setMemory(1024)
        guest.install(host,
                      repository=repository,
                      distro=distro,
                      method="HTTP",
                      pxe=True,
                      notools=True)
        guest.check()

        # Quick check of basic functionality
        guest.reboot()
        guest.pretendToHaveXenTools()
        guest.suspend()
        guest.resume()
        guest.check()
        guest.shutdown()
        guest.start()
        guest.check()

        # Shutdown the VM
        guest.shutdown()
        
class TC6460(_TC6460):
    """Install a RHEL5.2 32 bit VM using HVM."""
    DISTRO = "LATEST_rhel5"
    ARCH = "x86-32"

class TC6461(_TC6460):
    """Install a RHEL5.2 64 bit VM using HVM."""
    DISTRO = "LATEST_rhel5"
    ARCH = "x86-64"

