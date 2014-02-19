#
# XenRT: Test harness for Xen and the XenServer product family
#
# VM update tests
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy
import xenrt, xenrt.lib.xenserver

class _TCSimpleUpdate(xenrt.TestCase):

    VCPUS = 2
    MEMORY = 1024
    ARCH = "x86-32"
    DISTRO = None

    def prepare(self, arglist):

        # Get a host to install on
        self.host = self.getDefaultHost()

        # Install the VM
        self.guest = xenrt.lib.xenserver.guest.createVM(\
            self.host,
            xenrt.randomGuestName(),
            vcpus=self.VCPUS,
            memory=self.MEMORY,
            distro=self.DISTRO,
            vifs=[("0",
                   self.host.getPrimaryBridge(),
                   xenrt.util.randomMAC(),
                   None)])
        self.uninstallOnCleanup(self.guest)
        
    def run(self, arglist):

        # Check the kernel we're running now
        oldkver = self.guest.execguest("uname -r").strip()
        xenrt.TEC().comment("Old kernel version %s" % (oldkver))

        # Construct the URL for the update staging site. This is in the form
        # <stagingurl>/XenServer/<XSversion>        
        url = self.host.lookup(\
            "KERNEL_LCM_STAGING", "http://updates-int.uk.xensource.com")
        if url[0] == "/":
            url = xenrt.TEC().lookup("FORCE_HTTP_FETCH") + url

        # Perform the update
        self.guest.updateKernelFromWeb(url)
        self.guest.reboot()

        # Make sure we're running a newer kernel
        newkver = self.guest.execguest("uname -r").strip()
        if newkver == oldkver:
            raise xenrt.XRTFailure("Upgraded %s VM has the same kernel as "
                                   "before the upgrade: %s" %
                                   (self.DISTRO, oldkver))
        xenrt.TEC().comment("New kernel version %s" % (newkver))

        # Quick smoketest to make sure it looks OK
        self.guest.suspend()
        self.guest.resume()
        self.guest.check()
        self.guest.shutdown()

# XenServer 4.0.1
class TC7896(_TCSimpleUpdate):
    """Kernel update of RHEL 4.4 VM running on XenServer 4.0.1"""
    DISTRO = "rhel44"

class TC7897(_TCSimpleUpdate):
    """Kernel update of RHEL 4.5 VM running on XenServer 4.0.1"""
    DISTRO = "rhel45"

class TC7900(_TCSimpleUpdate):
    """Kernel update of CentOS 5.0 VM running on XenServer 4.0.1"""
    DISTRO = "centos5"

class TC7898(_TCSimpleUpdate):
    """Kernel update of RHEL 5.0 VM running on XenServer 4.0.1"""
    DISTRO = "rhel5"

class TC7899(_TCSimpleUpdate):
    """Kernel update of CentOS 4.5 VM running on XenServer 4.0.1"""
    DISTRO = "centos45"

class TC7902(_TCSimpleUpdate):
    """Kernel update of Debian Etch VM running on XenServer 4.0.1"""
    DISTRO = "etch"

class TC7901(_TCSimpleUpdate):
    """Kernel update of Debian Sarge VM running on XenServer 4.0.1"""
    DISTRO = "sarge"
        
# XenServer 4.1.0
class TC7903(_TCSimpleUpdate):
    """Kernel update of RHEL 4.4 VM running on XenServer 4.1.0"""
    DISTRO = "rhel44"

class TC7904(_TCSimpleUpdate):
    """Kernel update of RHEL 4.6 VM running on XenServer 4.1.0"""
    DISTRO = "rhel46"

class TC7905(_TCSimpleUpdate):
    """Kernel update of CentOS 5.1 VM running on XenServer 4.1.0"""
    DISTRO = "centos51"

class TC7906(_TCSimpleUpdate):
    """Kernel update of RHEL 5.1 VM running on XenServer 4.1.0"""
    DISTRO = "rhel51"

class TC7907(_TCSimpleUpdate):
    """Kernel update of RHEL 5.1 x86-64 VM running on XenServer 4.1.0"""
    DISTRO = "rhel51"
    ARCH = "x86-64"

class TC7908(_TCSimpleUpdate):
    """Kernel update of CentOS 5.1 x86-64 VM running on XenServer 4.1.0"""
    DISTRO = "centos51"
    ARCH = "x86-64"

class TC7909(_TCSimpleUpdate):
    """Kernel update of CentOS 4.6 VM running on XenServer 4.1.0"""
    DISTRO = "centos46"

class TC7910(_TCSimpleUpdate):
    """Kernel update of Debian Etch VM running on XenServer 4.1.0"""
    DISTRO = "etch"

class TC7911(_TCSimpleUpdate):
    """Kernel update of Debian Sarge VM running on XenServer 4.1.0"""
    DISTRO = "sarge"

# XenServer 5.0.0
class TC8680(_TCSimpleUpdate):
    """Kernel update of RHEL 4.7 VM running on XenServer 5.0"""
    DISTRO = "rhel47"

class TC8679(_TCSimpleUpdate):
    """Kernel update of CentOS 5.2 VM running on XenServer 5.0"""
    DISTRO = "centos52"

class TC8678(_TCSimpleUpdate):
    """Kernel update of RHEL 5.2 VM running on XenServer 5.0"""
    DISTRO = "rhel52"

class TC8677(_TCSimpleUpdate):
    """Kernel update of RHEL 5.2 x86-64 VM running on XenServer 5.0"""
    DISTRO = "rhel52"
    ARCH = "x86-64"

class TC8674(_TCSimpleUpdate):
    """Kernel update of CentOS 5.2 x86-64 VM running on XenServer 5.0"""
    DISTRO = "centos52"
    ARCH = "x86-64"

class TC8673(_TCSimpleUpdate):
    """Kernel update of CentOS 4.7 VM running on XenServer 5.0"""
    DISTRO = "centos47"

class TC8681(_TCSimpleUpdate):
    """Kernel update of Debian Etch VM running on XenServer 5.0"""
    DISTRO = "etch"

# XenServer independent

class TC9369(_TCSimpleUpdate):
    """Kernel update of RHEL 4.4 VM"""
    DISTRO = "rhel44"

class TC9370(_TCSimpleUpdate):
    """Kernel update of RHEL 4.5 VM"""
    DISTRO = "rhel45"

class TC9371(_TCSimpleUpdate):
    """Kernel update of RHEL 4.6 VM"""
    DISTRO = "rhel46"

class TC9372(_TCSimpleUpdate):
    """Kernel update of RHEL 4.7 VM"""
    DISTRO = "rhel47"

class TC9373(_TCSimpleUpdate):
    """Kernel update of CentOS 4.5 VM"""
    DISTRO = "centos45"

class TC9374(_TCSimpleUpdate):
    """Kernel update of CentOS 4.6 VM"""
    DISTRO = "centos46"

class TC9375(_TCSimpleUpdate):
    """Kernel update of CentOS 4.7 VM"""
    DISTRO = "centos47"

class TC9376(_TCSimpleUpdate):
    """Kernel update of RHEL 5.0 VM"""
    DISTRO = "rhel50"

class TC9378(_TCSimpleUpdate):
    """Kernel update of RHEL 5.1 VM"""
    DISTRO = "rhel51"

class TC9379(_TCSimpleUpdate):
    """Kernel update of RHEL 5.1 x86-64 VM"""
    DISTRO = "rhel51"
    ARCH = "x86-64"

class TC9380(_TCSimpleUpdate):
    """Kernel update of RHEL 5.2 VM"""
    DISTRO = "rhel52"

class TC9381(_TCSimpleUpdate):
    """Kernel update of RHEL 5.2 x86-64 VM"""
    DISTRO = "rhel52"
    ARCH = "x86-64"

class TC9382(_TCSimpleUpdate):
    """Kernel update of RHEL 5.3 VM"""
    DISTRO = "rhel53"

class TC9383(_TCSimpleUpdate):
    """Kernel update of RHEL 5.3 x86-64 VM"""
    DISTRO = "rhel53"
    ARCH = "x86-64"

class TC9384(_TCSimpleUpdate):
    """Kernel update of CentOS 5.0 VM"""
    DISTRO = "centos50"

class TC9385(_TCSimpleUpdate):
    """Kernel update of CentOS 5.1 VM"""
    DISTRO = "centos51"

class TC9386(_TCSimpleUpdate):
    """Kernel update of CentOS 5.1 x86-64 VM"""
    DISTRO = "centos51"
    ARCH = "x86-64"

class TC9387(_TCSimpleUpdate):
    """Kernel update of CentOS 5.2 VM"""
    DISTRO = "centos52"

class TC9388(_TCSimpleUpdate):
    """Kernel update of CentOS 5.2 x86-64 VM"""
    DISTRO = "centos52"
    ARCH = "x86-64"

class TC9389(_TCSimpleUpdate):
    """Kernel update of CentOS 5.3 VM"""
    DISTRO = "centos53"

class TC9390(_TCSimpleUpdate):
    """Kernel update of CentOS 5.3 x86-64 VM"""
    DISTRO = "centos53"
    ARCH = "x86-64"

class TC9366(_TCSimpleUpdate):
    """Kernel update of Debian Etch VM"""
    DISTRO = "etch"

class TC9367(_TCSimpleUpdate):
    """Kernel update of Debian Lenny VM"""
    DISTRO = "debian50"

class TC9368(_TCSimpleUpdate):
    """Kernel update of SLES 9 SP4 VM"""
    DISTRO = "sles94"

