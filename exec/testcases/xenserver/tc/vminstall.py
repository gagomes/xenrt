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
        guest.install(self.host,
                      repository=self.repository,
                      distro=self.distro,
                      method=self.METHOD)
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

class _TC5786(xenrt.TestCase):
    DISTRO = None
    ARCH = None
    PXE = False
    NOTOOLS = False

    def run(self, arglist):

        distro = self.DISTRO
        arch = self.ARCH
        pxe = self.PXE
        notools = self.NOTOOLS
        
        # Get a host to install on
        host = self.getDefaultHost()

        # Choose a template
        template = xenrt.lib.xenserver.getTemplate(host, distro, arch=arch)

        # Create an empty guest object
        guest = host.guestFactory()(xenrt.randomGuestName(), template, host)
        self.uninstallOnCleanup(guest)
        self.getLogsFrom(guest)

        # Install from ISO into the VM
        guest.arch = arch
        guest.install(host,
                      pxe=pxe,
                      repository="cdrom",
                      distro=distro,
                      method="CDROM",
                      notools=notools,
                      isoname=xenrt.DEFAULT)
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
        
class TC17743(_TC5786):
    """Install an Ubuntu 12.04 32 bit VM from ISO."""
    DISTRO = "ubuntu1204"
    ARCH = "x86-32"

class TC17744(_TC5786):
    """Install a Ubuntu 12.04 64 bit VM from ISO."""
    DISTRO = "ubuntu1204"
    ARCH = "x86-64"

class TC5786(_TC5786):
    """Install a RHEL5 32 bit VM from ISO using kickstart."""
    DISTRO = "rhel5"
    ARCH = "x86-32"

class TC5787(_TC5786):
    """Install a RHEL5 64 bit VM from ISO using kickstart."""
    DISTRO = "rhel5"
    ARCH = "x86-64"

class TC5788(_TC5786):
    """Install a CentOS5 32 bit VM from ISO using kickstart."""
    DISTRO = "centos5"
    ARCH = "x86-32"

class TC5789(_TC5786):
    """Install a CentOS5 64 bit VM from ISO using kickstart."""
    DISTRO = "centos5"
    ARCH = "x86-64"

class TC6785(_TC5786):
    """Install a RHEL5.1 32 bit VM from ISO using kickstart."""
    DISTRO = "rhel51"
    ARCH = "x86-32"

class TC6786(_TC5786):
    """Install a RHEL5.1 64 bit VM from ISO using kickstart."""
    DISTRO = "rhel51"
    ARCH = "x86-64"

class TC7770(_TC5786):
    """Install a RHEL5.2 32 bit VM from ISO using kickstart."""
    DISTRO = "rhel52"
    ARCH = "x86-32"

class TC7771(_TC5786):
    """Install a RHEL5.2 64 bit VM from ISO using kickstart."""
    DISTRO = "rhel52"
    ARCH = "x86-64"

class TC8953(_TC5786):
    """Install a RHEL5.3 32 bit VM from ISO using kickstart."""
    DISTRO = "rhel53"
    ARCH = "x86-32"

class TC8954(_TC5786):
    """Install a RHEL5.3 64 bit VM from ISO using kickstart."""
    DISTRO = "rhel53"
    ARCH = "x86-64"

class TC10948(_TC5786):
    """Install a RHEL5.4 32 bit VM from ISO using kickstart."""
    DISTRO = "rhel54"
    ARCH = "x86-32"

class TC10951(_TC5786):
    """Install a RHEL5.4 64 bit VM from ISO using kickstart."""
    DISTRO = "rhel54"
    ARCH = "x86-64"

class TC11721(_TC5786):
    """Install a RHEL5.5 32 bit VM from ISO using kickstart."""
    DISTRO = "rhel55"
    ARCH = "x86-32"

class TC11724(_TC5786):
    """Install a RHEL5.5 64 bit VM from ISO using kickstart."""
    DISTRO = "rhel55"
    ARCH = "x86-64"

class TC13119(_TC5786):
    """Install a RHEL5.6 32 bit VM from ISO using kickstart."""
    DISTRO = "rhel56"
    ARCH = "x86-32"

class TC13120(_TC5786):
    """Install a RHEL5.6 64 bit VM from ISO using kickstart."""
    DISTRO = "rhel56"
    ARCH = "x86-64"

class TC15400(_TC5786):
    """Install a RHEL5.7 32 bit VM from ISO using kickstart."""
    DISTRO = "rhel57"
    ARCH = "x86-32"

class TC15401(_TC5786):
    """Install a RHEL5.7 64 bit VM from ISO using kickstart."""
    DISTRO = "rhel57"
    ARCH = "x86-64"

class TC11838(_TC5786):
    """Install a RHEL6.0 32 bit VM from ISO using kickstart."""
    DISTRO = "rhel6"
    ARCH = "x86-32"

class TC11841(_TC5786):
    """Install a RHEL6.0 64 bit VM from ISO using kickstart."""
    DISTRO = "rhel6"
    ARCH = "x86-64"

class TC14507(_TC5786):
    """Install a RHEL6.1 32 bit VM from ISO using kickstart."""
    DISTRO = "rhel61"
    ARCH = "x86-32"

class TC14508(_TC5786):
    """Install a RHEL6.1 64 bit VM from ISO using kickstart."""
    DISTRO = "rhel61"
    ARCH = "x86-64"

class TC17227(_TC5786):
    """Install a RHEL6.2 32 bit VM from ISO using kickstart."""
    DISTRO = "rhel62"
    ARCH = "x86-32"

class TC17228(_TC5786):
    """Install a RHEL6.2 64 bit VM from ISO using kickstart."""
    DISTRO = "rhel62"
    ARCH = "x86-64"

class TC6787(_TC5786):
    """Install a CentOS5.1 32 bit VM from ISO using kickstart."""
    DISTRO = "centos51"
    ARCH = "x86-32"

class TC6788(_TC5786):
    """Install a CentOS5.1 64 bit VM from ISO using kickstart."""
    DISTRO = "centos51"
    ARCH = "x86-64"

class TC7768(_TC5786):
    """Install a CentOS5.2 32 bit VM from ISO using kickstart."""
    DISTRO = "centos52"
    ARCH = "x86-32"

class TC7769(_TC5786):
    """Install a CentOS5.2 64 bit VM from ISO using kickstart."""
    DISTRO = "centos52"
    ARCH = "x86-64"

class TC8959(_TC5786):
    """Install a CentOS5.3 32 bit VM from ISO using kickstart."""
    DISTRO = "centos53"
    ARCH = "x86-32"

class TC8960(_TC5786):
    """Install a CentOS5.3 64 bit VM from ISO using kickstart."""
    DISTRO = "centos53"
    ARCH = "x86-64"

class TC10972(_TC5786):
    """Install a CentOS5.4 32 bit VM from ISO using kickstart."""
    DISTRO = "centos54"
    ARCH = "x86-32"

class TC10975(_TC5786):
    """Install a CentOS5.4 64 bit VM from ISO using kickstart."""
    DISTRO = "centos54"
    ARCH = "x86-64"

class TC11727(_TC5786):
    """Install a CentOS5.5 32 bit VM from ISO using kickstart."""
    DISTRO = "centos55"
    ARCH = "x86-32"

class TC11730(_TC5786):
    """Install a CentOS5.5 64 bit VM from ISO using kickstart."""
    DISTRO = "centos55"
    ARCH = "x86-64"

class TC14497(_TC5786):
    """Install a CentOS5.6 32 bit VM from ISO using kickstart."""
    DISTRO = "centos56"
    ARCH = "x86-32"

class TC14498(_TC5786):
    """Install a CentOS5.6 64 bit VM from ISO using kickstart."""
    DISTRO = "centos56"
    ARCH = "x86-64"

class TC15402(_TC5786):
    """Install a CentOS5.7 32 bit VM from ISO using kickstart."""
    DISTRO = "centos57"
    ARCH = "x86-32"

class TC15403(_TC5786):
    """Install a CentOS5.7 64 bit VM from ISO using kickstart."""
    DISTRO = "centos57"
    ARCH = "x86-64"

class TC15406(_TC5786):
    """Install a CentOS6.0 32 bit VM from ISO using kickstart."""
    DISTRO = "centos6"
    ARCH = "x86-32"

class TC15407(_TC5786):
    """Install a CentOS6.0 64 bit VM from ISO using kickstart."""
    DISTRO = "centos6"
    ARCH = "x86-64"
    
class TC15865(_TC5786):
    """Install a CentOS6.1 32 bit VM from ISO using kickstart."""
    DISTRO = "centos61"
    ARCH = "x86-32"

class TC15866(_TC5786):
    """Install a CentOS6.1 64 bit VM from ISO using kickstart."""
    DISTRO = "centos61"
    ARCH = "x86-64"

class TC17229(_TC5786):
    """Install a CentOS6.2 32 bit VM from ISO using kickstart."""
    DISTRO = "centos62"
    ARCH = "x86-32"

class TC17230(_TC5786):
    """Install a CentOS6.2 64 bit VM from ISO using kickstart."""
    DISTRO = "centos62"
    ARCH = "x86-64"

class TC10954(_TC5786):
    """Install a OEL5.3 32 bit VM from ISO using kickstart."""
    DISTRO = "oel53"
    ARCH = "x86-32"

class TC10957(_TC5786):
    """Install a OEL5.3 64 bit VM from ISO using kickstart."""
    DISTRO = "oel53"
    ARCH = "x86-64"

class TC10960(_TC5786):
    """Install a OEL5.4 32 bit VM from ISO using kickstart."""
    DISTRO = "oel54"
    ARCH = "x86-32"

class TC10963(_TC5786):
    """Install a OEL5.4 64 bit VM from ISO using kickstart."""
    DISTRO = "oel54"
    ARCH = "x86-64"

class TC11734(_TC5786):
    """Install a OEL5.5 32 bit VM from ISO using kickstart."""
    DISTRO = "oel55"
    ARCH = "x86-32"

class TC11738(_TC5786):
    """Install a OEL5.5 64 bit VM from ISO using kickstart."""
    DISTRO = "oel55"
    ARCH = "x86-64"

class TC13121(_TC5786):
    """Install a OEL5.6 32 bit VM from ISO using kickstart."""
    DISTRO = "oel56"
    ARCH = "x86-32"

class TC13122(_TC5786):
    """Install a OEL5.6 64 bit VM from ISO using kickstart."""
    DISTRO = "oel56"
    ARCH = "x86-64"

class TC15404(_TC5786):
    """Install a OEL5.7 32 bit VM from ISO using kickstart."""
    DISTRO = "oel57"
    ARCH = "x86-32"

class TC15405(_TC5786):
    """Install a OEL5.7 64 bit VM from ISO using kickstart."""
    DISTRO = "oel57"
    ARCH = "x86-64"

class TC14826(_TC5786):
    """Install a OEL6.0 32 bit VM from ISO using kickstart."""
    DISTRO = "oel6"
    ARCH = "x86-32"

class TC14825(_TC5786):
    """Install a OEL6.0 64 bit VM from ISO using kickstart."""
    DISTRO = "oel6"
    ARCH = "x86-64"
    
class TC15867(_TC5786):
    """Install a OEL6.1 32 bit VM from ISO using kickstart."""
    DISTRO = "oel61"
    ARCH = "x86-32"

class TC15868(_TC5786):
    """Install a OEL6.1 64 bit VM from ISO using kickstart."""
    DISTRO = "oel61"
    ARCH = "x86-64"

class TC17231(_TC5786):
    """Install a OEL6.2 32 bit VM from ISO using kickstart."""
    DISTRO = "oel62"
    ARCH = "x86-32"

class TC17232(_TC5786):
    """Install a OEL6.2 64 bit VM from ISO using kickstart."""
    DISTRO = "oel62"
    ARCH = "x86-64"

class TC6823(_TC5786):
    """Install a RHEL4.6 32 bit VM from ISO using kickstart."""
    DISTRO = "rhel46"
    ARCH = "x86-32"

class TC7776(_TC5786):
    """Install a RHEL4.7 32 bit VM from ISO using kickstart."""
    DISTRO = "rhel47"
    ARCH = "x86-32"

class TC9558(_TC5786):
    """Install a RHEL4.8 32 bit VM from ISO using kickstart."""
    DISTRO = "rhel48"
    ARCH = "x86-32"

class TC7739(_TC5786):
    """Install a SLES10 SP1 32 bit VM from ISO using autoyast."""
    DISTRO = "sles101"
    ARCH = "x86-32"

class TC7740(_TC5786):
    """Install a SLES10 SP1 64 bit VM from ISO using autoyast."""
    DISTRO = "sles101"
    ARCH = "x86-64"

class TC7741(_TC5786):
    """Install a SLES10 SP2 32 bit VM from ISO using autoyast."""
    DISTRO = "sles102"
    ARCH = "x86-32"

class TC7742(_TC5786):
    """Install a SLES10 SP2 64 bit VM from ISO using autoyast."""
    DISTRO = "sles102"
    ARCH = "x86-64"

class TC11380(_TC5786):
    """Install a SLES10 SP3 32 bit VM from ISO using autoyast."""
    DISTRO = "sles103"
    ARCH = "x86-32"

class TC11383(_TC5786):
    """Install a SLES10 SP3 64 bit VM from ISO using autoyast."""
    DISTRO = "sles103"
    ARCH = "x86-64"
    
class TC13124(_TC5786):
    """Install a SLES10 SP4 32 bit VM from ISO using autoyast."""
    DISTRO = "sles104"
    ARCH = "x86-32"

class TC13123(_TC5786):
    """Install a SLES10 SP4 64 bit VM from ISO using autoyast."""
    DISTRO = "sles104"
    ARCH = "x86-64"

class TC9030(_TC5786):
    """Install a SLES11 32 bit VM from ISO using autoyast."""
    DISTRO = "sles11"
    ARCH = "x86-32"

class TC9031(_TC5786):
    """Install a SLES11 64 bit VM from ISO using autoyast."""
    DISTRO = "sles11"
    ARCH = "x86-64"

class TC11789(_TC5786):
    """Install a SLES11 SP1 32 bit VM from ISO using autoyast."""
    DISTRO = "sles111"
    ARCH = "x86-32"

class TC11790(_TC5786):
    """Install a SLES11 SP1 64 bit VM from ISO using autoyast."""
    DISTRO = "sles111"
    ARCH = "x86-64"

class TC7777(_TC5786):
    """Install a CentOS4.7 32 bit VM from ISO using kickstart."""
    DISTRO = "centos47"
    ARCH = "x86-32"

class TC9567(_TC5786):
    """Install a CentOS4.8 32 bit VM from ISO using kickstart."""
    DISTRO = "centos48"
    ARCH = "x86-32"


# This class should be removed once Solaris gets full agent support
# and therefore supports resume, suspend, soft shutdown, reboot etc
class _TC5786ExperimentalSolaris(_TC5786):
    def run(self, arglist):
    
        distro = self.DISTRO
        arch = self.ARCH
        pxe = self.PXE
        notools = self.NOTOOLS
        
        # Get a host to install on
        host = self.getDefaultHost()

        # Choose a template
        template = xenrt.lib.xenserver.getTemplate(host, distro, arch=arch)
    
        # Create an empty guest object
        guest = host.guestFactory()(xenrt.randomGuestName(), template, host)
        self.uninstallOnCleanup(guest)
        self.getLogsFrom(guest)
    
        # Install from ISO into the VM
        guest.arch = arch
        guest.install(host,
                      pxe=pxe,
                      repository="cdrom",
                      distro=distro,
                      method="CDROM",
                      notools=notools,
                      isoname=xenrt.DEFAULT)
        guest.check()

        # Shutdown the VM
        guest.shutdown(force=True)


class TC12515(_TC5786ExperimentalSolaris):
    """Install a Solaris 10u9 32 bit VM from ISO using jumpstart."""
    DISTRO = "solaris10u9-32"
    ARCH = "x86-32"
    PXE = False
    NOTOOLS = True

class TC12494(TC12515):
    """Install a Solaris 10u9 32 bit VM from ISO using jumpstart."""
    """Used in TC-12493 and in bostonossolaris.seq"""

class TC12518(_TC5786ExperimentalSolaris):
    """Install a Solaris 10u9 64 bit VM from ISO using jumpstart."""
    DISTRO = "solaris10u9"
    ARCH = "x86-64"
    PXE = False
    NOTOOLS = True

class TC12504(TC12518):
    """Install a Solaris 10u9 64 bit VM from ISO using jumpstart."""
    """Used in TC-12503 and in bostonossolaris.seq"""
    
class _TC6767(xenrt.TestCase):
    DISTRO = None
    ARCH = None
    METHOD = None
    PXE = False
    NOTOOLS = False

    def run(self, arglist):

        distro = self.DISTRO
        arch = self.ARCH
        method = self.METHOD
        pxe = self.PXE
        notools = self.NOTOOLS

        # Get a host to install on
        host = self.getDefaultHost()

        # Choose a template
        template = xenrt.lib.xenserver.getTemplate(host, distro, arch=arch)

        # Create an empty guest object
        guest = host.guestFactory()(xenrt.randomGuestName(), template, host)
        self.uninstallOnCleanup(guest)
        self.getLogsFrom(guest)

        # Get the repository location
        r = xenrt.TEC().lookup(["RPM_SOURCE", distro, arch, method], None)
        if not r:
            raise xenrt.XRTError("No %s repository for %s %s" %
                                 (method, arch, distro))
        repository = string.split(r)[0]

        # Install from network repository into the VM
        guest.arch = arch
        guest.install(host,
                      pxe=pxe,
                      repository=repository,
                      distro=distro,
                      notools=notools,
                      method=method)
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

class TC7744(_TC6767):
    """Install a SLES9SP4 32 bit VM from NFS repository."""
    DISTRO = "sles94"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC7745(_TC6767):
    """Install a SLES9SP4 32 bit VM from HTTP repository."""
    DISTRO = "sles94"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC6767(_TC6767):
    """Install a SLES10SP1 32 bit VM from NFS repository."""
    DISTRO = "sles101"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC6768(_TC6767):
    """Install a SLES10SP1 32 bit VM from HTTP repository."""
    DISTRO = "sles101"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC7779(_TC6767):
    """Install a SLES10SP1 64 bit VM from NFS repository."""
    DISTRO = "sles101"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC7778(_TC6767):
    """Install a SLES10SP1 64 bit VM from HTTP repository."""
    DISTRO = "sles101"
    ARCH = "x86-64"
    METHOD = "HTTP"
    
class TC7782(_TC6767):
    """Install a SLES10SP2 32 bit VM from NFS repository."""
    DISTRO = "sles102"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC7780(_TC6767):
    """Install a SLES10SP2 32 bit VM from HTTP repository."""
    DISTRO = "sles102"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC7783(_TC6767):
    """Install a SLES10SP2 64 bit VM from NFS repository."""
    DISTRO = "sles102"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC7781(_TC6767):
    """Install a SLES10SP2 64 bit VM from HTTP repository."""
    DISTRO = "sles102"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC11379(_TC6767):
    """Install a SLES10SP3 32 bit VM from NFS repository."""
    DISTRO = "sles103"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC11378(_TC6767):
    """Install a SLES10SP3 32 bit VM from HTTP repository."""
    DISTRO = "sles103"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC11382(_TC6767):
    """Install a SLES10SP3 64 bit VM from NFS repository."""
    DISTRO = "sles103"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC11381(_TC6767):
    """Install a SLES10SP3 64 bit VM from HTTP repository."""
    DISTRO = "sles103"
    ARCH = "x86-64"
    METHOD = "HTTP"
    
class TC13126(_TC6767):
    """Install a SLES10SP4 32 bit VM from NFS repository."""
    DISTRO = "sles104"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC13125(_TC6767):
    """Install a SLES10SP4 32 bit VM from HTTP repository."""
    DISTRO = "sles104"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC13127(_TC6767):
    """Install a SLES10SP4 64 bit VM from NFS repository."""
    DISTRO = "sles104"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC13128(_TC6767):
    """Install a SLES10SP4 64 bit VM from HTTP repository."""
    DISTRO = "sles104"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC9032(_TC6767):
    """Install a SLES11 32 bit VM from NFS repository."""
    DISTRO = "sles11"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC9034(_TC6767):
    """Install a SLES11 32 bit VM from HTTP repository."""
    DISTRO = "sles11"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC9033(_TC6767):
    """Install a SLES11 64 bit VM from NFS repository."""
    DISTRO = "sles11"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC11791(_TC6767):
    """Install a SLES11 SP1 32 bit VM from NFS repository."""
    DISTRO = "sles111"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC11793(_TC6767):
    """Install a SLES11 SP1 32 bit VM from HTTP repository."""
    DISTRO = "sles111"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC11792(_TC6767):
    """Install a SLES11 SP1 64 bit VM from NFS repository."""
    DISTRO = "sles111"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC11794(_TC6767):
    """Install a SLES11 SP1 64 bit VM from HTTP repository."""
    DISTRO = "sles111"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC9035(_TC6767):
    """Install a SLES11 64 bit VM from HTTP repository."""
    DISTRO = "sles11"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC6769(_TC6767):
    """Install a RHEL5 32 bit VM from NFS repository."""
    DISTRO = "rhel5"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC6770(_TC6767):
    """Install a RHEL5 32 bit VM from HTTP repository."""
    DISTRO = "rhel5"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC6771(_TC6767):
    """Install a RHEL5 64 bit VM from NFS repository."""
    DISTRO = "rhel5"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC6772(_TC6767):
    """Install a RHEL5 64 bit VM from HTTP repository."""
    DISTRO = "rhel5"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC6773(_TC6767):
    """Install a RHEL4.5 32 bit VM from NFS repository."""
    DISTRO = "rhel45"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC6774(_TC6767):
    """Install a RHEL4.5 32 bit VM from HTTP repository."""
    DISTRO = "rhel45"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC6775(_TC6767):
    """Install a RHEL4.6 32 bit VM from NFS repository."""
    DISTRO = "rhel46"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC6776(_TC6767):
    """Install a RHEL4.6 32 bit VM from HTTP repository."""
    DISTRO = "rhel46"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC7773(_TC6767):
    """Install a RHEL4.7 32 bit VM from NFS repository."""
    DISTRO = "rhel47"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC7775(_TC6767):
    """Install a RHEL4.7 32 bit VM from HTTP repository."""
    DISTRO = "rhel47"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC9562(_TC6767):
    """Install a RHEL4.8 32 bit VM from NFS repository."""
    DISTRO = "rhel48"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC9560(_TC6767):
    """Install a RHEL4.8 32 bit VM from HTTP repository."""
    DISTRO = "rhel48"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC6777(_TC6767):
    """Install a RHEL4.4 32 bit VM from NFS repository."""
    DISTRO = "rhel44"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC6778(_TC6767):
    """Install a RHEL4.4 32 bit VM from HTTP repository."""
    DISTRO = "rhel44"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC6779(_TC6767):
    """Install a RHEL4.1 32 bit VM from NFS repository."""
    DISTRO = "rhel41"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC6780(_TC6767):
    """Install a RHEL4.1 32 bit VM from HTTP repository."""
    DISTRO = "rhel41"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC6781(_TC6767):
    """Install a RHEL5.1 32 bit VM from NFS repository."""
    DISTRO = "rhel51"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC6782(_TC6767):
    """Install a RHEL5.1 32 bit VM from HTTP repository."""
    DISTRO = "rhel51"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC6783(_TC6767):
    """Install a RHEL5.1 64 bit VM from NFS repository."""
    DISTRO = "rhel51"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC6784(_TC6767):
    """Install a RHEL5.1 64 bit VM from HTTP repository."""
    DISTRO = "rhel51"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC7765(_TC6767):
    """Install a RHEL5.2 32 bit VM from NFS repository."""
    DISTRO = "rhel52"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC7764(_TC6767):
    """Install a RHEL5.2 32 bit VM from HTTP repository."""
    DISTRO = "rhel52"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC7767(_TC6767):
    """Install a RHEL5.2 64 bit VM from NFS repository."""
    DISTRO = "rhel52"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC7766(_TC6767):
    """Install a RHEL5.2 64 bit VM from HTTP repository."""
    DISTRO = "rhel52"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC8951(_TC6767):
    """Install a RHEL5.3 32 bit VM from NFS repository."""
    DISTRO = "rhel53"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC8949(_TC6767):
    """Install a RHEL5.3 32 bit VM from HTTP repository."""
    DISTRO = "rhel53"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC8952(_TC6767):
    """Install a RHEL5.3 64 bit VM from NFS repository."""
    DISTRO = "rhel53"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC8950(_TC6767):
    """Install a RHEL5.3 64 bit VM from HTTP repository."""
    DISTRO = "rhel53"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC10946(_TC6767):
    """Install a RHEL5.4 32 bit VM from NFS repository."""
    DISTRO = "rhel54"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC10947(_TC6767):
    """Install a RHEL5.4 32 bit VM from HTTP repository."""
    DISTRO = "rhel54"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC10949(_TC6767):
    """Install a RHEL5.4 64 bit VM from NFS repository."""
    DISTRO = "rhel54"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC10950(_TC6767):
    """Install a RHEL5.4 64 bit VM from HTTP repository."""
    DISTRO = "rhel54"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC11719(_TC6767):
    """Install a RHEL5.5 32 bit VM from NFS repository."""
    DISTRO = "rhel55"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC11720(_TC6767):
    """Install a RHEL5.5 32 bit VM from HTTP repository."""
    DISTRO = "rhel55"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC11722(_TC6767):
    """Install a RHEL5.5 64 bit VM from NFS repository."""
    DISTRO = "rhel55"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC11723(_TC6767):
    """Install a RHEL5.5 64 bit VM from HTTP repository."""
    DISTRO = "rhel55"
    ARCH = "x86-64"
    METHOD = "HTTP"
    
class TC13129(_TC6767):
    """Install a RHEL5.6 32 bit VM from NFS repository."""
    DISTRO = "rhel56"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC13130(_TC6767):
    """Install a RHEL5.6 32 bit VM from HTTP repository."""
    DISTRO = "rhel56"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC13131(_TC6767):
    """Install a RHEL5.6 64 bit VM from NFS repository."""
    DISTRO = "rhel56"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC13132(_TC6767):
    """Install a RHEL5.6 64 bit VM from HTTP repository."""
    DISTRO = "rhel56"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC15408(_TC6767):
    """Install a RHEL5.7 32 bit VM from NFS repository."""
    DISTRO = "rhel57"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC15409(_TC6767):
    """Install a RHEL5.7 32 bit VM from HTTP repository."""
    DISTRO = "rhel57"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC15410(_TC6767):
    """Install a RHEL5.7 64 bit VM from NFS repository."""
    DISTRO = "rhel57"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC15411(_TC6767):
    """Install a RHEL5.7 64 bit VM from HTTP repository."""
    DISTRO = "rhel57"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC11836(_TC6767):
    """Install a RHEL6.0 32 bit VM from NFS repository."""
    DISTRO = "rhel6"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC11837(_TC6767):
    """Install a RHEL6.0 32 bit VM from HTTP repository."""
    DISTRO = "rhel6"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC11839(_TC6767):
    """Install a RHEL6.0 64 bit VM from NFS repository."""
    DISTRO = "rhel6"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC11840(_TC6767):
    """Install a RHEL6.0 64 bit VM from HTTP repository."""
    DISTRO = "rhel6"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC14503(_TC6767):
    """Install a RHEL6.1 32 bit VM from NFS repository."""
    DISTRO = "rhel61"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC14504(_TC6767):
    """Install a RHEL6.1 32 bit VM from HTTP repository."""
    DISTRO = "rhel61"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC14505(_TC6767):
    """Install a RHEL6.1 64 bit VM from NFS repository."""
    DISTRO = "rhel61"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC14506(_TC6767):
    """Install a RHEL6.1 64 bit VM from HTTP repository."""
    DISTRO = "rhel61"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC17233(_TC6767):
    """Install a RHEL6.2 32 bit VM from NFS repository."""
    DISTRO = "rhel62"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC17234(_TC6767):
    """Install a RHEL6.2 32 bit VM from HTTP repository."""
    DISTRO = "rhel62"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC17235(_TC6767):
    """Install a RHEL6.2 64 bit VM from NFS repository."""
    DISTRO = "rhel62"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC17236(_TC6767):
    """Install a RHEL6.2 64 bit VM from HTTP repository."""
    DISTRO = "rhel62"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC6880(_TC6767):
    """Install a CentOS4.5 32 bit VM from NFS repository."""
    DISTRO = "centos45"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC6879(_TC6767):
    """Install a CentOS4.5 32 bit VM from HTTP repository."""
    DISTRO = "centos45"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC6882(_TC6767):
    """Install a CentOS4.6 32 bit VM from NFS repository."""
    DISTRO = "centos46"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC6881(_TC6767):
    """Install a CentOS4.6 32 bit VM from HTTP repository."""
    DISTRO = "centos46"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC7772(_TC6767):
    """Install a CentOS4.7 32 bit VM from NFS repository."""
    DISTRO = "centos47"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC7774(_TC6767):
    """Install a CentOS4.7 32 bit VM from HTTP repository."""
    DISTRO = "centos47"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC9565(_TC6767):
    """Install a CentOS4.8 32 bit VM from NFS repository."""
    DISTRO = "centos48"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC9564(_TC6767):
    """Install a CentOS4.8 32 bit VM from HTTP repository."""
    DISTRO = "centos48"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC6884(_TC6767):
    """Install a CentOS5 32 bit VM from NFS repository."""
    DISTRO = "centos5"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC6883(_TC6767):
    """Install a CentOS5 32 bit VM from HTTP repository."""
    DISTRO = "centos5"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC6886(_TC6767):
    """Install a CentOS5 64 bit VM from NFS repository."""
    DISTRO = "centos5"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC6885(_TC6767):
    """Install a CentOS5 64 bit VM from HTTP repository."""
    DISTRO = "centos5"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC6888(_TC6767):
    """Install a CentOS5.1 32 bit VM from NFS repository."""
    DISTRO = "centos51"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC6887(_TC6767):
    """Install a CentOS5.1 32 bit VM from HTTP repository."""
    DISTRO = "centos51"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC6890(_TC6767):
    """Install a CentOS5.1 64 bit VM from NFS repository."""
    DISTRO = "centos51"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC6889(_TC6767):
    """Install a CentOS5.1 64 bit VM from HTTP repository."""
    DISTRO = "centos51"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC7760(_TC6767):
    """Install a CentOS5.2 32 bit VM from NFS repository."""
    DISTRO = "centos52"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC7761(_TC6767):
    """Install a CentOS5.2 32 bit VM from HTTP repository."""
    DISTRO = "centos52"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC7762(_TC6767):
    """Install a CentOS5.2 64 bit VM from NFS repository."""
    DISTRO = "centos52"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC7763(_TC6767):
    """Install a CentOS5.2 64 bit VM from HTTP repository."""
    DISTRO = "centos52"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC8957(_TC6767):
    """Install a CentOS5.3 32 bit VM from NFS repository."""
    DISTRO = "centos53"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC8955(_TC6767):
    """Install a CentOS5.3 32 bit VM from HTTP repository."""
    DISTRO = "centos53"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC8958(_TC6767):
    """Install a CentOS5.3 64 bit VM from NFS repository."""
    DISTRO = "centos53"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC8956(_TC6767):
    """Install a CentOS5.3 64 bit VM from HTTP repository."""
    DISTRO = "centos53"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC10970(_TC6767):
    """Install a CentOS5.4 32 bit VM from NFS repository."""
    DISTRO = "centos54"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC10971(_TC6767):
    """Install a CentOS5.4 32 bit VM from HTTP repository."""
    DISTRO = "centos54"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC10973(_TC6767):
    """Install a CentOS5.4 64 bit VM from NFS repository."""
    DISTRO = "centos54"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC10974(_TC6767):
    """Install a CentOS5.4 64 bit VM from HTTP repository."""
    DISTRO = "centos54"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC11725(_TC6767):
    """Install a CentOS5.5 32 bit VM from NFS repository."""
    DISTRO = "centos55"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC11726(_TC6767):
    """Install a CentOS5.5 32 bit VM from HTTP repository."""
    DISTRO = "centos55"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC11728(_TC6767):
    """Install a CentOS5.5 64 bit VM from NFS repository."""
    DISTRO = "centos55"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC11729(_TC6767):
    """Install a CentOS5.5 64 bit VM from HTTP repository."""
    DISTRO = "centos55"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC14499(_TC6767):
    """Install a CentOS5.6 32 bit VM from NFS repository."""
    DISTRO = "centos56"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC14500(_TC6767):
    """Install a CentOS5.6 32 bit VM from HTTP repository."""
    DISTRO = "centos56"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC14501(_TC6767):
    """Install a CentOS5.6 64 bit VM from NFS repository."""
    DISTRO = "centos56"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC14502(_TC6767):
    """Install a CentOS5.6 64 bit VM from HTTP repository."""
    DISTRO = "centos56"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC15412(_TC6767):
    """Install a CentOS5.7 32 bit VM from NFS repository."""
    DISTRO = "centos57"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC15413(_TC6767):
    """Install a CentOS5.7 32 bit VM from HTTP repository."""
    DISTRO = "centos57"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC15414(_TC6767):
    """Install a CentOS5.7 64 bit VM from NFS repository."""
    DISTRO = "centos57"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC15415(_TC6767):
    """Install a CentOS5.7 64 bit VM from HTTP repository."""
    DISTRO = "centos57"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC15420(_TC6767):
    """Install a CentOS6.0 32 bit VM from NFS repository."""
    DISTRO = "centos6"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC15421(_TC6767):
    """Install a CentOS6.0 32 bit VM from HTTP repository."""
    DISTRO = "centos6"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC15422(_TC6767):
    """Install a CentOS6.0 64 bit VM from NFS repository."""
    DISTRO = "centos6"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC15423(_TC6767):
    """Install a CentOS6.0 64 bit VM from HTTP repository."""
    DISTRO = "centos6"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC15869(_TC6767):
    """Install a CentOS6.1 32 bit VM from NFS repository."""
    DISTRO = "centos61"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC15870(_TC6767):
    """Install a CentOS6.1 32 bit VM from HTTP repository."""
    DISTRO = "centos61"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC15871(_TC6767):
    """Install a CentOS6.1 64 bit VM from NFS repository."""
    DISTRO = "centos61"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC15872(_TC6767):
    """Install a CentOS6.1 64 bit VM from HTTP repository."""
    DISTRO = "centos61"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC17237(_TC6767):
    """Install a CentOS6.2 32 bit VM from NFS repository."""
    DISTRO = "centos62"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC17238(_TC6767):
    """Install a CentOS6.2 32 bit VM from HTTP repository."""
    DISTRO = "centos62"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC17239(_TC6767):
    """Install a CentOS6.2 64 bit VM from NFS repository."""
    DISTRO = "centos62"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC17240(_TC6767):
    """Install a CentOS6.2 64 bit VM from HTTP repository."""
    DISTRO = "centos62"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC10952(_TC6767):
    """Install a OEL5.3 32 bit VM from NFS repository."""
    DISTRO = "oel53"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC10953(_TC6767):
    """Install a OEL5.3 32 bit VM from HTTP repository."""
    DISTRO = "oel53"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC10955(_TC6767):
    """Install a OEL5.3 64 bit VM from NFS repository."""
    DISTRO = "oel53"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC10956(_TC6767):
    """Install a OEL5.3 64 bit VM from HTTP repository."""
    DISTRO = "oel53"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC10958(_TC6767):
    """Install a OEL5.4 32 bit VM from NFS repository."""
    DISTRO = "oel54"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC10959(_TC6767):
    """Install a OEL5.4 32 bit VM from HTTP repository."""
    DISTRO = "oel54"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC10961(_TC6767):
    """Install a OEL5.4 64 bit VM from NFS repository."""
    DISTRO = "oel54"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC10962(_TC6767):
    """Install a OEL5.4 64 bit VM from HTTP repository."""
    DISTRO = "oel54"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC11732(_TC6767):
    """Install a OEL5.5 32 bit VM from NFS repository."""
    DISTRO = "oel55"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC11733(_TC6767):
    """Install a OEL5.5 32 bit VM from HTTP repository."""
    DISTRO = "oel55"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC11735(_TC6767):
    """Install a OEL5.5 64 bit VM from NFS repository."""
    DISTRO = "oel55"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC11737(_TC6767):
    """Install a OEL5.5 64 bit VM from HTTP repository."""
    DISTRO = "oel55"
    ARCH = "x86-64"
    METHOD = "HTTP"
    
class TC13133(_TC6767):
    """Install a OEL5.6 32 bit VM from NFS repository."""
    DISTRO = "oel56"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC13134(_TC6767):
    """Install a OEL5.6 32 bit VM from HTTP repository."""
    DISTRO = "oel56"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC13135(_TC6767):
    """Install a OEL5.6 64 bit VM from NFS repository."""
    DISTRO = "oel56"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC13136(_TC6767):
    """Install a OEL5.6 64 bit VM from HTTP repository."""
    DISTRO = "oel56"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC15416(_TC6767):
    """Install a OEL5.7 32 bit VM from NFS repository."""
    DISTRO = "oel57"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC15417(_TC6767):
    """Install a OEL5.7 32 bit VM from HTTP repository."""
    DISTRO = "oel57"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC15418(_TC6767):
    """Install a OEL5.7 64 bit VM from NFS repository."""
    DISTRO = "oel57"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC15419(_TC6767):
    """Install a OEL5.7 64 bit VM from HTTP repository."""
    DISTRO = "oel57"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC14827(_TC6767):
    """Install a OEL6.0 32 bit VM from NFS repository."""
    DISTRO = "oel6"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC14828(_TC6767):
    """Install a OEL6.0 32 bit VM from HTTP repository."""
    DISTRO = "oel6"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC14829(_TC6767):
    """Install a OEL6.0 64 bit VM from NFS repository."""
    DISTRO = "oel6"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC14830(_TC6767):
    """Install a OEL6.0 64 bit VM from HTTP repository."""
    DISTRO = "oel6"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC15873(_TC6767):
    """Install a OEL6.1 32 bit VM from NFS repository."""
    DISTRO = "oel61"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC15874(_TC6767):
    """Install a OEL6.1 32 bit VM from HTTP repository."""
    DISTRO = "oel61"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC15875(_TC6767):
    """Install a OEL6.1 64 bit VM from NFS repository."""
    DISTRO = "oel61"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC15876(_TC6767):
    """Install a OEL6.1 64 bit VM from HTTP repository."""
    DISTRO = "oel61"
    ARCH = "x86-64"
    METHOD = "HTTP"
    
class TC17241(_TC6767):
    """Install a OEL6.2 32 bit VM from NFS repository."""
    DISTRO = "oel62"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC17224(_TC6767):
    """Install a OEL6.2 32 bit VM from HTTP repository."""
    DISTRO = "oel62"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC17225(_TC6767):
    """Install a OEL6.2 64 bit VM from NFS repository."""
    DISTRO = "oel62"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC17226(_TC6767):
    """Install a OEL6.2 64 bit VM from HTTP repository."""
    DISTRO = "oel62"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC9044(_TC6767):
    """Install a Debian Lenny 5.0 32 bit VM from NFS repository."""
    DISTRO = "debian50"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC9045(_TC6767):
    """Install a Debian Lenny 5.0 32 bit VM from HTTP repository."""
    DISTRO = "debian50"
    ARCH = "x86-32"
    METHOD = "HTTP"
    
class TC13137(_TC6767):
    """Install a Ubuntu Lucid 10.04 32 bit VM from HTTP repository."""
    DISTRO = "ubuntu1004"
    ARCH = "x86-32"
    METHOD = "HTTP"
    
class TC13138(_TC6767):
    """Install a Ubuntu Lucid 10.04 64 bit VM from HTTP repository."""
    DISTRO = "ubuntu1004"
    ARCH = "x86-64"
    METHOD = "HTTP"
    
class TC13232(_TC6767):
    """Install a Debian Squeeze 6.0 32 bit VM from NFS repository."""
    DISTRO = "debian60"
    ARCH = "x86-32"
    METHOD = "NFS"
    
class TC13233(_TC6767):
    """Install a Debian Squeeze 6.0 32 bit VM from HTTP repository."""
    DISTRO = "debian60"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC13234(_TC6767):
    """Install a Debian Squeeze 6.0 64 bit VM from NFS repository."""
    DISTRO = "debian60"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC13235(_TC6767):
    """Install a Debian Squeeze 6.0 64 bit VM from HTTP repository."""
    DISTRO = "debian60"
    ARCH = "x86-64"
    METHOD = "HTTP"
    
class TC17739(_TC6767):
    """Install Ubuntu 12.04 32 bit VM from HTTP repository."""
    DISTRO = "ubuntu1204"
    ARCH = "x86-32"
    METHOD = "HTTP"
    
class TC17740(_TC6767):
    """Install Ubuntu 12.04 64 bit VM from HTTP repository."""
    DISTRO = "ubuntu1204"
    ARCH = "x86-64"
    METHOD = "HTTP"


# This class should be removed once Solaris gets full agent support
# and therefore supports resume, suspend, soft shutdown, reboot etc
class _TC6767ExperimentalSolaris(xenrt.TestCase):
    DISTRO = None
    ARCH = None
    METHOD = None
    PXE = False
    NOTOOLS = False
    
    def run(self, arglist):

        distro = self.DISTRO
        arch = self.ARCH
        method = self.METHOD
        pxe = self.PXE
        notools = self.NOTOOLS

        # Get a host to install on
        host = self.getDefaultHost()
    
        # Choose a template
        template = xenrt.lib.xenserver.getTemplate(host, distro, arch=arch)

        # Create an empty guest object
        guest = host.guestFactory()(xenrt.randomGuestName(), template, host)
        self.uninstallOnCleanup(guest)
        self.getLogsFrom(guest)

        # Get the repository location
        r = xenrt.TEC().lookup(["RPM_SOURCE", distro, arch, method], None)
        if not r:
            raise xenrt.XRTError("No %s repository for %s %s" %
                                 (method, arch, distro))
        repository = string.split(r)[0]

        # Install from network repository into the VM
        guest.arch = arch
        guest.install(host,
                      pxe=pxe,
                      repository=repository,
                      distro=distro,
                      notools=notools,
                      method=method)
        guest.check()

        # Shutdown the VM
        guest.shutdown(force=True)

class TC12513(_TC6767ExperimentalSolaris):
    """Install Solaris 10u9 32 bit VM from NFS repository."""
    DISTRO = "solaris10u9-32"
    ARCH = "x86-32"
    METHOD = "NFS"
    PXE = True
    NOTOOLS = True

class TC12514(_TC6767ExperimentalSolaris):
    """Install Solaris 10u9 32 bit VM from HTTP repository."""
    DISTRO = "solaris10u9-32"
    ARCH = "x86-32"
    METHOD = "HTTP"
    PXE = True
    NOTOOLS = True
    
class TC12516(_TC6767ExperimentalSolaris):
    """Install Solaris 10u9 64 bit VM from NFS repository."""
    DISTRO = "solaris10u9"
    ARCH = "x86-64"
    METHOD = "NFS"
    PXE = True
    NOTOOLS = True
    
class TC12517(_TC6767ExperimentalSolaris):
    """Install Solaris 10u9 64 bit VM from HTTP repository."""
    DISTRO = "solaris10u9"
    ARCH = "x86-64"
    METHOD = "HTTP"
    PXE = True
    NOTOOLS = True

class TC19742(_TC5786):
    """Install a RHEL5.8 32 bit VM from ISO"""
    DISTRO = "rhel58"
    ARCH = "x86-32"


class TC19743(_TC6767):
    """Install a RHEL5.8 32 bit VM from HTTP"""
    DISTRO = "rhel58"
    ARCH = "x86-32"
    METHOD = "HTTP"


class TC19744(_TC6767):
    """Install a RHEL5.8 32 bit VM from NFS"""
    DISTRO = "rhel58"
    ARCH = "x86-32"
    METHOD = "NFS"


class TC19745(_TC5786):
    """Install a RHEL5.8 64 bit VM from ISO"""
    DISTRO = "rhel58"
    ARCH = "x86-64"


class TC19746(_TC6767):
    """Install a RHEL5.8 64 bit VM from HTTP"""
    DISTRO = "rhel58"
    ARCH = "x86-64"
    METHOD = "HTTP"


class TC19747(_TC6767):
    """Install a RHEL5.8 64 bit VM from NFS"""
    DISTRO = "rhel58"
    ARCH = "x86-64"
    METHOD = "NFS"


class TC19748(_TC5786):
    """Install a RHEL5.9 32 bit VM from ISO"""
    DISTRO = "rhel59"
    ARCH = "x86-32"


class TC19749(_TC6767):
    """Install a RHEL5.9 32 bit VM from HTTP"""
    DISTRO = "rhel59"
    ARCH = "x86-32"
    METHOD = "HTTP"


class TC19750(_TC6767):
    """Install a RHEL5.9 32 bit VM from NFS"""
    DISTRO = "rhel59"
    ARCH = "x86-32"
    METHOD = "NFS"


class TC19751(_TC5786):
    """Install a RHEL5.9 64 bit VM from ISO"""
    DISTRO = "rhel59"
    ARCH = "x86-64"


class TC19752(_TC6767):
    """Install a RHEL5.9 64 bit VM from HTTP"""
    DISTRO = "rhel59"
    ARCH = "x86-64"
    METHOD = "HTTP"


class TC19753(_TC6767):
    """Install a RHEL5.9 64 bit VM from NFS"""
    DISTRO = "rhel59"
    ARCH = "x86-64"
    METHOD = "NFS"


class TC21728(_TC5786):
    """Install a RHEL5.10 32 bit VM from ISO"""
    DISTRO = "rhel510"
    ARCH = "x86-32"


class TC21729(_TC6767):
    """Install a RHEL5.10 32 bit VM from HTTP"""
    DISTRO = "rhel510"
    ARCH = "x86-32"
    METHOD = "HTTP"


class TC21731(_TC6767):
    """Install a RHEL5.10 32 bit VM from NFS"""
    DISTRO = "rhel510"
    ARCH = "x86-32"
    METHOD = "NFS"


class TC21732(_TC5786):
    """Install a RHEL5.10 64 bit VM from ISO"""
    DISTRO = "rhel510"
    ARCH = "x86-64"


class TC21733(_TC6767):
    """Install a RHEL5.10 64 bit VM from HTTP"""
    DISTRO = "rhel510"
    ARCH = "x86-64"
    METHOD = "HTTP"


class TC21734(_TC6767):
    """Install a RHEL5.10 64 bit VM from NFS"""
    DISTRO = "rhel510"
    ARCH = "x86-64"
    METHOD = "NFS"


class TC19754(_TC5786):
    """Install a RHEL6.3 32 bit VM from ISO"""
    DISTRO = "rhel63"
    ARCH = "x86-32"


class TC19755(_TC6767):
    """Install a RHEL6.3 32 bit VM from HTTP"""
    DISTRO = "rhel63"
    ARCH = "x86-32"
    METHOD = "HTTP"


class TC19756(_TC6767):
    """Install a RHEL6.3 32 bit VM from NFS"""
    DISTRO = "rhel63"
    ARCH = "x86-32"
    METHOD = "NFS"


class TC19757(_TC5786):
    """Install a RHEL6.3 64 bit VM from ISO"""
    DISTRO = "rhel63"
    ARCH = "x86-64"


class TC19758(_TC6767):
    """Install a RHEL6.3 64 bit VM from HTTP"""
    DISTRO = "rhel63"
    ARCH = "x86-64"
    METHOD = "HTTP"


class TC19759(_TC6767):
    """Install a RHEL6.3 64 bit VM from NFS"""
    DISTRO = "rhel63"
    ARCH = "x86-64"
    METHOD = "NFS"


class TC19760(_TC5786):
    """Install a RHEL6.4 32 bit VM from ISO"""
    DISTRO = "rhel64"
    ARCH = "x86-32"


class TC19761(_TC6767):
    """Install a RHEL6.4 32 bit VM from HTTP"""
    DISTRO = "rhel64"
    ARCH = "x86-32"
    METHOD = "HTTP"


class TC19762(_TC6767):
    """Install a RHEL6.4 32 bit VM from NFS"""
    DISTRO = "rhel64"
    ARCH = "x86-32"
    METHOD = "NFS"


class TC19763(_TC5786):
    """Install a RHEL6.4 64 bit VM from ISO"""
    DISTRO = "rhel64"
    ARCH = "x86-64"


class TC19764(_TC6767):
    """Install a RHEL6.4 64 bit VM from HTTP"""
    DISTRO = "rhel64"
    ARCH = "x86-64"
    METHOD = "HTTP"


class TC19765(_TC6767):
    """Install a RHEL6.4 64 bit VM from NFS"""
    DISTRO = "rhel64"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC21735(_TC5786):
    """Install a RHEL6.5 32 bit VM from ISO"""
    DISTRO = "rhel65"
    ARCH = "x86-32"


class TC21736(_TC6767):
    """Install a RHEL6.5 32 bit VM from HTTP"""
    DISTRO = "rhel65"
    ARCH = "x86-32"
    METHOD = "HTTP"


class TC21737(_TC6767):
    """Install a RHEL6.5 32 bit VM from NFS"""
    DISTRO = "rhel65"
    ARCH = "x86-32"
    METHOD = "NFS"


class TC21738(_TC5786):
    """Install a RHEL6.5 64 bit VM from ISO"""
    DISTRO = "rhel65"
    ARCH = "x86-64"


class TC21739(_TC6767):
    """Install a RHEL6.5 64 bit VM from HTTP"""
    DISTRO = "rhel65"
    ARCH = "x86-64"
    METHOD = "HTTP"


class TC21740(_TC6767):
    """Install a RHEL6.5 64 bit VM from NFS"""
    DISTRO = "rhel65"
    ARCH = "x86-64"
    METHOD = "NFS"


class TC19766(_TC5786):
    """Install a CentOS5.8 32 bit VM from ISO"""
    DISTRO = "centos58"
    ARCH = "x86-32"


class TC19767(_TC6767):
    """Install a CentOS5.8 32 bit VM from HTTP"""
    DISTRO = "centos58"
    ARCH = "x86-32"
    METHOD = "HTTP"


class TC19768(_TC6767):
    """Install a CentOS5.8 32 bit VM from NFS"""
    DISTRO = "centos58"
    ARCH = "x86-32"
    METHOD = "NFS"


class TC19769(_TC5786):
    """Install a CentOS5.8 64 bit VM from ISO"""
    DISTRO = "centos58"
    ARCH = "x86-64"


class TC19770(_TC6767):
    """Install a CentOS5.8 64 bit VM from HTTP"""
    DISTRO = "centos58"
    ARCH = "x86-64"
    METHOD = "HTTP"


class TC19771(_TC6767):
    """Install a CentOS5.8 64 bit VM from NFS"""
    DISTRO = "centos58"
    ARCH = "x86-64"
    METHOD = "NFS"


class TC19772(_TC5786):
    """Install a CentOS5.9 32 bit VM from ISO"""
    DISTRO = "centos59"
    ARCH = "x86-32"


class TC19773(_TC6767):
    """Install a CentOS5.9 32 bit VM from HTTP"""
    DISTRO = "centos59"
    ARCH = "x86-32"
    METHOD = "HTTP"


class TC19774(_TC6767):
    """Install a CentOS5.9 32 bit VM from NFS"""
    DISTRO = "centos59"
    ARCH = "x86-32"
    METHOD = "NFS"


class TC19775(_TC5786):
    """Install a CentOS5.9 64 bit VM from ISO"""
    DISTRO = "centos59"
    ARCH = "x86-64"


class TC19776(_TC6767):
    """Install a CentOS5.9 64 bit VM from HTTP"""
    DISTRO = "centos59"
    ARCH = "x86-64"
    METHOD = "HTTP"


class TC19777(_TC6767):
    """Install a CentOS5.9 64 bit VM from NFS"""
    DISTRO = "centos59"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC21741(_TC5786):
    """Install a CentOS5.10 32 bit VM from ISO"""
    DISTRO = "centos510"
    ARCH = "x86-32"

class TC21742(_TC6767):
    """Install a CentOS5.10 32 bit VM from HTTP"""
    DISTRO = "centos510"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC21743(_TC6767):
    """Install a CentOS5.10 32 bit VM from NFS"""
    DISTRO = "centos510"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC21744(_TC5786):
    """Install a CentOS5.10 64 bit VM from ISO"""
    DISTRO = "centos510"
    ARCH = "x86-64"

class TC21745(_TC6767):
    """Install a CentOS5.10 64 bit VM from HTTP"""
    DISTRO = "centos510"
    ARCH = "x86-64"
    METHOD = "HTTP"

class TC21746(_TC6767):
    """Install a CentOS5.10 64 bit VM from NFS"""
    DISTRO = "centos510"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC19778(_TC5786):
    """Install a CentOS6.3 32 bit VM from ISO"""
    DISTRO = "centos63"
    ARCH = "x86-32"


class TC19779(_TC6767):
    """Install a CentOS6.3 32 bit VM from HTTP"""
    DISTRO = "centos63"
    ARCH = "x86-32"
    METHOD = "HTTP"


class TC19780(_TC6767):
    """Install a CentOS6.3 32 bit VM from NFS"""
    DISTRO = "centos63"
    ARCH = "x86-32"
    METHOD = "NFS"


class TC19781(_TC5786):
    """Install a CentOS6.3 64 bit VM from ISO"""
    DISTRO = "centos63"
    ARCH = "x86-64"


class TC19782(_TC6767):
    """Install a CentOS6.3 64 bit VM from HTTP"""
    DISTRO = "centos63"
    ARCH = "x86-64"
    METHOD = "HTTP"


class TC19783(_TC6767):
    """Install a CentOS6.3 64 bit VM from NFS"""
    DISTRO = "centos63"
    ARCH = "x86-64"
    METHOD = "NFS"


class TC19784(_TC5786):
    """Install a CentOS6.4 32 bit VM from ISO"""
    DISTRO = "centos64"
    ARCH = "x86-32"


class TC19785(_TC6767):
    """Install a CentOS6.4 32 bit VM from HTTP"""
    DISTRO = "centos64"
    ARCH = "x86-32"
    METHOD = "HTTP"


class TC19786(_TC6767):
    """Install a CentOS6.4 32 bit VM from NFS"""
    DISTRO = "centos64"
    ARCH = "x86-32"
    METHOD = "NFS"


class TC19787(_TC5786):
    """Install a CentOS6.4 64 bit VM from ISO"""
    DISTRO = "centos64"
    ARCH = "x86-64"


class TC19788(_TC6767):
    """Install a CentOS6.4 64 bit VM from HTTP"""
    DISTRO = "centos64"
    ARCH = "x86-64"
    METHOD = "HTTP"


class TC19789(_TC6767):
    """Install a CentOS6.4 64 bit VM from NFS"""
    DISTRO = "centos64"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC21747(_TC5786):
    """Install a CentOS6.5 32 bit VM from ISO"""
    DISTRO = "centos65"
    ARCH = "x86-32"


class TC21748(_TC6767):
    """Install a CentOS6.5 32 bit VM from HTTP"""
    DISTRO = "centos65"
    ARCH = "x86-32"
    METHOD = "HTTP"


class TC21749(_TC6767):
    """Install a CentOS6.5 32 bit VM from NFS"""
    DISTRO = "centos65"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC21750(_TC5786):
    """Install a CentOS6.5 64 bit VM from ISO"""
    DISTRO = "centos65"
    ARCH = "x86-64"


class TC21751(_TC6767):
    """Install a CentOS6.5 64 bit VM from HTTP"""
    DISTRO = "centos65"
    ARCH = "x86-64"
    METHOD = "HTTP"


class TC21752(_TC6767):
    """Install a CentOS6.5 64 bit VM from NFS"""
    DISTRO = "centos65"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC19790(_TC5786):
    """Install a OEL5.8 32 bit VM from ISO"""
    DISTRO = "oel58"
    ARCH = "x86-32"


class TC19791(_TC6767):
    """Install a OEL5.8 32 bit VM from HTTP"""
    DISTRO = "oel58"
    ARCH = "x86-32"
    METHOD = "HTTP"


class TC19792(_TC6767):
    """Install a OEL5.8 32 bit VM from NFS"""
    DISTRO = "oel58"
    ARCH = "x86-32"
    METHOD = "NFS"


class TC19793(_TC5786):
    """Install a OEL5.8 64 bit VM from ISO"""
    DISTRO = "oel58"
    ARCH = "x86-64"


class TC19794(_TC6767):
    """Install a OEL5.8 64 bit VM from HTTP"""
    DISTRO = "oel58"
    ARCH = "x86-64"
    METHOD = "HTTP"


class TC19795(_TC6767):
    """Install a OEL5.8 64 bit VM from NFS"""
    DISTRO = "oel58"
    ARCH = "x86-64"
    METHOD = "NFS"


class TC19796(_TC5786):
    """Install a OEL5.9 32 bit VM from ISO"""
    DISTRO = "oel59"
    ARCH = "x86-32"


class TC19797(_TC6767):
    """Install a OEL5.9 32 bit VM from HTTP"""
    DISTRO = "oel59"
    ARCH = "x86-32"
    METHOD = "HTTP"


class TC19798(_TC6767):
    """Install a OEL5.9 32 bit VM from NFS"""
    DISTRO = "oel59"
    ARCH = "x86-32"
    METHOD = "NFS"


class TC19799(_TC5786):
    """Install a OEL5.9 64 bit VM from ISO"""
    DISTRO = "oel59"
    ARCH = "x86-64"


class TC19800(_TC6767):
    """Install a OEL5.9 64 bit VM from HTTP"""
    DISTRO = "oel59"
    ARCH = "x86-64"
    METHOD = "HTTP"


class TC19801(_TC6767):
    """Install a OEL5.9 64 bit VM from NFS"""
    DISTRO = "oel59"
    ARCH = "x86-64"
    METHOD = "NFS"


class TC21753(_TC5786):
    """Install a OEL5.10 32 bit VM from ISO"""
    DISTRO = "oel510"
    ARCH = "x86-32"


class TC21754(_TC6767):
    """Install a OEL5.10 32 bit VM from HTTP"""
    DISTRO = "oel510"
    ARCH = "x86-32"
    METHOD = "HTTP"


class TC21755(_TC6767):
    """Install a OEL5.10 32 bit VM from NFS"""
    DISTRO = "oel510"
    ARCH = "x86-32"
    METHOD = "NFS"


class TC21756(_TC5786):
    """Install a OEL5.10 64 bit VM from ISO"""
    DISTRO = "oel510"
    ARCH = "x86-64"


class TC21757(_TC6767):
    """Install a OEL5.10 64 bit VM from HTTP"""
    DISTRO = "oel510"
    ARCH = "x86-64"
    METHOD = "HTTP"


class TC21758(_TC6767):
    """Install a OEL5.10 64 bit VM from NFS"""
    DISTRO = "oel510"
    ARCH = "x86-64"
    METHOD = "NFS"


class TC19802(_TC5786):
    """Install a OEL6.3 32 bit VM from ISO"""
    DISTRO = "oel63"
    ARCH = "x86-32"


class TC19803(_TC6767):
    """Install a OEL6.3 32 bit VM from HTTP"""
    DISTRO = "oel63"
    ARCH = "x86-32"
    METHOD = "HTTP"


class TC19804(_TC6767):
    """Install a OEL6.3 32 bit VM from NFS"""
    DISTRO = "oel63"
    ARCH = "x86-32"
    METHOD = "NFS"


class TC19805(_TC5786):
    """Install a OEL6.3 64 bit VM from ISO"""
    DISTRO = "oel63"
    ARCH = "x86-64"


class TC19806(_TC6767):
    """Install a OEL6.3 64 bit VM from HTTP"""
    DISTRO = "oel63"
    ARCH = "x86-64"
    METHOD = "HTTP"


class TC19807(_TC6767):
    """Install a OEL6.3 64 bit VM from NFS"""
    DISTRO = "oel63"
    ARCH = "x86-64"
    METHOD = "NFS"


class TC19808(_TC5786):
    """Install a OEL6.4 32 bit VM from ISO"""
    DISTRO = "oel64"
    ARCH = "x86-32"


class TC19809(_TC6767):
    """Install a OEL6.4 32 bit VM from HTTP"""
    DISTRO = "oel64"
    ARCH = "x86-32"
    METHOD = "HTTP"


class TC19810(_TC6767):
    """Install a OEL6.4 32 bit VM from NFS"""
    DISTRO = "oel64"
    ARCH = "x86-32"
    METHOD = "NFS"


class TC19811(_TC5786):
    """Install a OEL6.4 64 bit VM from ISO"""
    DISTRO = "oel64"
    ARCH = "x86-64"


class TC19812(_TC6767):
    """Install a OEL6.4 64 bit VM from HTTP"""
    DISTRO = "oel64"
    ARCH = "x86-64"
    METHOD = "HTTP"


class TC19813(_TC6767):
    """Install a OEL6.4 64 bit VM from NFS"""
    DISTRO = "oel64"
    ARCH = "x86-64"
    METHOD = "NFS"


class TC21759(_TC5786):
    """Install a OEL6.5 32 bit VM from ISO"""
    DISTRO = "oel65"
    ARCH = "x86-32"


class TC21761(_TC6767):
    """Install a OEL6.5 32 bit VM from HTTP"""
    DISTRO = "oel65"
    ARCH = "x86-32"
    METHOD = "HTTP"


class TC21762(_TC6767):
    """Install a OEL6.5 32 bit VM from NFS"""
    DISTRO = "oel65"
    ARCH = "x86-32"
    METHOD = "NFS"


class TC21763(_TC5786):
    """Install a OEL6.5 64 bit VM from ISO"""
    DISTRO = "oel65"
    ARCH = "x86-64"


class TC21764(_TC6767):
    """Install a OEL6.5 64 bit VM from HTTP"""
    DISTRO = "oel65"
    ARCH = "x86-64"
    METHOD = "HTTP"


class TC21765(_TC6767):
    """Install a OEL6.5 64 bit VM from NFS"""
    DISTRO = "oel65"
    ARCH = "x86-64"
    METHOD = "NFS"


class TC19814(_TC5786):
    """Install a SLES11SP2 32 bit VM from ISO"""
    DISTRO = "sles112"
    ARCH = "x86-32"


class TC19815(_TC6767):
    """Install a SLES11SP2 32 bit VM from HTTP"""
    DISTRO = "sles112"
    ARCH = "x86-32"
    METHOD = "HTTP"


class TC19816(_TC6767):
    """Install a SLES11SP2 32 bit VM from NFS"""
    DISTRO = "sles112"
    ARCH = "x86-32"
    METHOD = "NFS"


class TC19817(_TC5786):
    """Install a SLES11SP2 64 bit VM from ISO"""
    DISTRO = "sles112"
    ARCH = "x86-64"


class TC19818(_TC6767):
    """Install a SLES11SP2 64 bit VM from HTTP"""
    DISTRO = "sles112"
    ARCH = "x86-64"
    METHOD = "HTTP"


class TC19819(_TC6767):
    """Install a SLES11SP2 64 bit VM from NFS"""
    DISTRO = "sles112"
    ARCH = "x86-64"
    METHOD = "NFS"


class TC21767(_TC5786):
    """Install a SLES11SP3 32 bit VM from ISO"""
    DISTRO = "sles113"
    ARCH = "x86-32"

class TC21768(_TC6767):
    """Install a SLES11SP3 32 bit VM from HTTP"""
    DISTRO = "sles113"
    ARCH = "x86-32"
    METHOD = "HTTP"

class TC21769(_TC6767):
    """Install a SLES11SP3 32 bit VM from NFS"""
    DISTRO = "sles113"
    ARCH = "x86-32"
    METHOD = "NFS"

class TC21770(_TC5786):
    """Install a SLES11SP3 64 bit VM from ISO"""
    DISTRO = "sles113"
    ARCH = "x86-64"


class TC21771(_TC6767):
    """Install a SLES11SP3 64 bit VM from HTTP"""
    DISTRO = "sles113"
    ARCH = "x86-64"
    METHOD = "HTTP"


class TC21772(_TC6767):
    """Install a SLES11SP3 64 bit VM from NFS"""
    DISTRO = "sles113"
    ARCH = "x86-64"
    METHOD = "NFS"

class TC21720(_TC5786):
    """Install a Ubuntu 14.04 32 bit VM from ISO"""
    DISTRO = "ubuntu1404"
    ARCH = "x86-32"

class TC21723(_TC5786):
    """Install a Ubuntu 14.04 64 bit VM from ISO"""
    DISTRO = "ubuntu1404"
    ARCH = "x86-64"
    
class TC21773(_TC5786):
    """Install a RHEL7 64 bit VM from ISO"""
    DISTRO = "rhel7"
    ARCH = "x86-64"

class TC21774(_TC5786):
    """Install a CentOS7 64 bit VM from ISO"""
    DISTRO = "centos7"
    ARCH = "x86-64"

class TC21775(_TC5786):
    """Install a OEL7 64 bit VM from ISO"""
    DISTRO = "oel7"
    ARCH = "x86-64"

class TC23702(_TC6767):
    """Install a RedHat Enterprise Linux 5.11 64 bit VM from HTTP"""
    DISTRO="rhel511"
    ARCH="x86-64"
    METHOD="HTTP"

class TC23703(_TC6767):
    """Install a RedHat Enterprise Linux 5.11 32 bit VM from HTTP"""
    DISTRO="rhel511"
    ARCH="x86-32"
    METHOD="HTTP"

class TC23704(_TC5786):
    """Install a RedHat Enterprise Linux 5.11 64 bit VM from ISO"""
    DISTRO="rhel511"
    ARCH="x86-64"

class TC23705(_TC5786):
    """Install a RedHat Enterprise Linux 5.11 32 bit VM from ISO"""
    DISTRO="rhel511"
    ARCH="x86-32"

class TC23706(_TC6767):
    """Install a RedHat Enterprise Linux 5.11 64 bit VM from NFS"""
    DISTRO="rhel511"
    ARCH="x86-64"
    METHOD="NFS"

class TC23707(_TC6767):
    """Install a RedHat Enterprise Linux 5.11 32 bit VM from NFS"""
    DISTRO="rhel511"
    ARCH="x86-32"
    METHOD="NFS"

class TC23708(_TC6767):
    """Install a RedHat Enterprise Linux 6.6 64 bit VM from HTTP"""
    DISTRO="rhel66"
    ARCH="x86-64"
    METHOD="HTTP"

class TC23709(_TC6767):
    """Install a RedHat Enterprise Linux 6.6 32 bit VM from HTTP"""
    DISTRO="rhel66"
    ARCH="x86-32"
    METHOD="HTTP"

class TC23710(_TC5786):
    """Install a RedHat Enterprise Linux 6.6 64 bit VM from ISO"""
    DISTRO="rhel66"
    ARCH="x86-64"

class TC23711(_TC5786):
    """Install a RedHat Enterprise Linux 6.6 32 bit VM from ISO"""
    DISTRO="rhel66"
    ARCH="x86-32"

class TC23712(_TC6767):
    """Install a RedHat Enterprise Linux 6.6 64 bit VM from NFS"""
    DISTRO="rhel66"
    ARCH="x86-64"
    METHOD="NFS"

class TC23713(_TC6767):
    """Install a RedHat Enterprise Linux 6.6 32 bit VM from NFS"""
    DISTRO="rhel66"
    ARCH="x86-32"
    METHOD="NFS"

class TC23714(_TC6767):
    """Install a CentOS 5.11 64 bit VM from HTTP"""
    DISTRO="centos511"
    ARCH="x86-64"
    METHOD="HTTP"

class TC23715(_TC6767):
    """Install a CentOS 5.11 32 bit VM from HTTP"""
    DISTRO="centos511"
    ARCH="x86-32"
    METHOD="HTTP"

class TC23716(_TC5786):
    """Install a CentOS 5.11 64 bit VM from ISO"""
    DISTRO="centos511"
    ARCH="x86-64"

class TC23717(_TC5786):
    """Install a CentOS 5.11 32 bit VM from ISO"""
    DISTRO="centos511"
    ARCH="x86-32"

class TC23718(_TC6767):
    """Install a CentOS 5.11 64 bit VM from NFS"""
    DISTRO="centos511"
    ARCH="x86-64"
    METHOD="NFS"

class TC23719(_TC6767):
    """Install a CentOS 5.11 32 bit VM from NFS"""
    DISTRO="centos511"
    ARCH="x86-32"
    METHOD="NFS"

class TC23720(_TC6767):
    """Install a CentOS 6.6 64 bit VM from HTTP"""
    DISTRO="centos66"
    ARCH="x86-64"
    METHOD="HTTP"

class TC23721(_TC6767):
    """Install a CentOS 6.6 32 bit VM from HTTP"""
    DISTRO="centos66"
    ARCH="x86-32"
    METHOD="HTTP"

class TC23722(_TC5786):
    """Install a CentOS 6.6 64 bit VM from ISO"""
    DISTRO="centos66"
    ARCH="x86-64"

class TC23723(_TC5786):
    """Install a CentOS 6.6 32 bit VM from ISO"""
    DISTRO="centos66"
    ARCH="x86-32"

class TC23724(_TC6767):
    """Install a CentOS 6.6 64 bit VM from NFS"""
    DISTRO="centos66"
    ARCH="x86-64"
    METHOD="NFS"

class TC23725(_TC6767):
    """Install a CentOS 6.6 32 bit VM from NFS"""
    DISTRO="centos66"
    ARCH="x86-32"
    METHOD="NFS"

class TC23726(_TC6767):
    """Install a Oracle Enterprise Linux 5.11 64 bit VM from HTTP"""
    DISTRO="oel511"
    ARCH="x86-64"
    METHOD="HTTP"

class TC23727(_TC6767):
    """Install a Oracle Enterprise Linux 5.11 32 bit VM from HTTP"""
    DISTRO="oel511"
    ARCH="x86-32"
    METHOD="HTTP"

class TC23728(_TC5786):
    """Install a Oracle Enterprise Linux 5.11 64 bit VM from ISO"""
    DISTRO="oel511"
    ARCH="x86-64"

class TC23729(_TC5786):
    """Install a Oracle Enterprise Linux 5.11 32 bit VM from ISO"""
    DISTRO="oel511"
    ARCH="x86-32"

class TC23730(_TC6767):
    """Install a Oracle Enterprise Linux 5.11 64 bit VM from NFS"""
    DISTRO="oel511"
    ARCH="x86-64"
    METHOD="NFS"

class TC23731(_TC6767):
    """Install a Oracle Enterprise Linux 5.11 32 bit VM from NFS"""
    DISTRO="oel511"
    ARCH="x86-32"
    METHOD="NFS"

class TC23732(_TC6767):
    """Install a Oracle Enterprise Linux 6.6 64 bit VM from HTTP"""
    DISTRO="oel66"
    ARCH="x86-64"
    METHOD="HTTP"

class TC23733(_TC6767):
    """Install a Oracle Enterprise Linux 6.6 32 bit VM from HTTP"""
    DISTRO="oel66"
    ARCH="x86-32"
    METHOD="HTTP"

class TC23734(_TC5786):
    """Install a Oracle Enterprise Linux 6.6 64 bit VM from ISO"""
    DISTRO="oel66"
    ARCH="x86-64"

class TC23735(_TC5786):
    """Install a Oracle Enterprise Linux 6.6 32 bit VM from ISO"""
    DISTRO="oel66"
    ARCH="x86-32"

class TC23736(_TC6767):
    """Install a Oracle Enterprise Linux 6.6 64 bit VM from NFS"""
    DISTRO="oel66"
    ARCH="x86-64"
    METHOD="NFS"

class TC23737(_TC6767):
    """Install a Oracle Enterprise Linux 6.6 32 bit VM from NFS"""
    DISTRO="oel66"
    ARCH="x86-32"
    METHOD="NFS"
