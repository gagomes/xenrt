#
# XenRT: Test harness for Xen and the XenServer product family
#
# Supplemental Pack standalone testcases
#
# Copyright (c) 2009 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy, os, os.path
import xenrt, xenrt.lib.xenserver, testcases.xenserver.tc.upgrade

class _SupplementalPacksDuringInstall(xenrt.TestCase):

    PACKS = None
    PACK_MEM = None
    
    def checkInstalledRepos(self, host, pack):
        # Check supplemental pack entry exists under installed-repos
        data = host.execdom0("ls /etc/xensource/installed-repos/")
        reposEntry = "oem:%s" % (pack['name'])
        if not reposEntry in data:
            raise xenrt.XRTFailure("Entry not found under installed-repos: %s" %
                                   (reposEntry))

    def checkRPMS(self, host, pack):
        # Check the pack's rpms are installed
        for rpm in pack['rpms']:
            data = host.execdom0("rpm -qi %s" % rpm)
            if "is not installed" in data:
                raise xenrt.XRTFailure("RPM package %s is not installed" %
                                       (rpm))

    def checkmem(self, targetb):
        memtarget = float(self.host.genParamGet("vm", 
                                                self.dom0, 
                                                "memory-target"))
        memactual = float(self.host.genParamGet("vm", 
                                                self.dom0, 
                                                "memory-actual"))
        data = self.host.execdom0("cat /proc/meminfo")
        r = re.search(r"MemTotal:\s+(\d+)\s+kB", data)
        if not r:
            raise xenrt.XRTError("Could not parse /proc/meminfo for MemTotal")
        memtotal = float(r.group(1)) * xenrt.KILO
        for x in [("memory-target", memtarget),
                  ("memory-actual", memactual),
                  ("/proc/meminfo:MemTotal", memtotal)]:
            desc, m = x
            delta = abs(targetb - m)
            error = 100.0 * delta / targetb
            if error > 5.0:
                raise xenrt.XRTFailure("%s is not as expected" % (desc),
                                       "Target %.0f bytes, is %.0f bytes" %
                                       (targetb, m))

    def run(self, arglist=None):
        # Perform host installation with supplemental packs
        productVersion = xenrt.TEC().lookup("PRODUCT_VERSION")
        inputDir = xenrt.TEC().lookup("INPUTDIR")
        suppackcds = ",".join([pack['iso'] for pack in self.PACKS])
        self.host = xenrt.lib.xenserver.createHost(id=0,
                                                   version=inputDir,
                                                   productVersion=productVersion,
                                                   installSRType="lvm",
                                                   suppackcds=suppackcds,
                                                   addToLogCollectionList=True)

        # Check the supplemental packs are properly installed
        for pack in self.PACKS:
            self.checkInstalledRepos(self.host, pack)
            self.checkRPMS(self.host, pack)

    def uninstallPack(self, host, pack):
        for rpm in pack['rpms']:
            host.execdom0("rpm -e %s" % (rpm))
        host.execdom0("rm -rf /etc/xensource/installed-repos/oem:%s" %
                      (pack['name']))

    def postRun(self):
        # Uninstall the supplemental packs
        for pack in self.PACKS:
            try:
                self.uninstallPack(self.host, pack)
            except: pass

class TC10631(_SupplementalPacksDuringInstall):
    """Install a host with a supplemental pack"""

    PACKS = [{"name":"helloworld-user", 
              "iso":"helloworld-user.iso", 
              "rpms":["helloworld-user"]}]
    
class TC10632(_SupplementalPacksDuringInstall):
    """Install a host with multiple supplemental packs"""

    PACKS = [{"name":"helloworld-user", 
              "iso":"helloworld-user.iso",
              "rpms":["helloworld-user"]},
             {"name":"mypack", 
              "iso":"mypack.iso",
              "rpms":["mypack"]},
             {"name":"bugtool", 
              "iso":"bugtool.iso",
              "rpms":["bugtool"]}]

class TC10633(_SupplementalPacksDuringInstall):
    """Install a host with a supplemental pack that combines multiple driver-rpms and one rpm with EULA"""

    PACKS = [{"name":"combined", 
              "iso":"combined.iso",
              "rpms":["combined-data",
                      "combined-modules-xen-2.6.27.37-0.1.1.xs5.5.900.697.1020",
                      "combined-modules-kdump-2.6.27.37-0.1.1.xs5.5.900.697.1020"]}]

class _SupplementalPacksPostInstall(_SupplementalPacksDuringInstall):

    def downloadPackISO(self, host, pack):
        host.execdom0("curl '%ssuppacks/%s' -o /tmp/%s" %
                      (xenrt.TEC().lookup("TEST_TARBALL_BASE"),
                      pack['iso'],
                      pack['iso']))


    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()

        # Download the supplemental pack isos
        for pack in self.PACKS:
            self.downloadPackISO(self.host, pack)

    def installPack(self, host, pack):
        # Mount the ISO and install the supplemental pack
        host.execdom0("mount -t iso9660 -o loop /tmp/%s /mnt" % (pack['iso']))
        try:
            host.execdom0("cd /mnt && ./install.sh")
        except Exception, e:
            raise xenrt.XRTFailure("Unable to install supplemental pack: %s" %
                                   (pack['name']), str(e))
        host.execdom0("umount /mnt")

    def run(self, arglist=None):
        for pack in self.PACKS:
            self.installPack(self.host, pack)
            self.checkInstalledRepos(self.host, pack)
            self.checkRPMS(self.host, pack)

    def postRun(self):
        try:
            self.host.execdom0("umount /mnt")
        except:
            pass

        # Uninstall the supplemental packs
        _SupplementalPacksDuringInstall.postRun(self)

class TC10634(_SupplementalPacksPostInstall):
    """Install a supplemental pack on a running system"""

    PACKS = [{"name":"helloworld-user",
              "iso":"helloworld-user.iso",
              "rpms":["helloworld-user"]}]

class TC10635(_SupplementalPacksPostInstall):
    """Verify installation of a supplemental pack on a running system with a missing pack dependency is blocked"""

    PACKS = [{"name":"unmet-dependency",
              "iso":"unmet-dependency.iso",
              "rpms":["unmet-dependency"]}]

    def run(self, arglist=None):
        # Mount the ISO and try to install the supplemental pack
        self.host.execdom0("mount -t iso9660 -o loop /tmp/%s /mnt" % (self.PACKS[0]['iso']))
        try:
            self.host.execdom0("cd /mnt && ./install.sh")
        except xenrt.XRTFailure, e:
            # Check we get the expected error
            if not re.search("FATAL: missing dependency oem:nonexistingpack", e.data):
                raise xenrt.XRTError("Expected failure attempting to install "
                                     "supplemental pack with missing dependency, "
                                     "but with unexpected message", data=e.data)
        else:
            raise xenrt.XRTFailure("Allowed to install a supplemental pack on a"
                                   "running system with a missing dependency")

class TC10636(_SupplementalPacksPostInstall):
    """Verify installation of a supplemental pack with an unsatisfied version dependency generates proper error message and can be aborted"""

    PACKS = [{"name":"helloworld-user",
              "iso":"helloworld-user.iso",
              "rpms":["helloworld-user"]},
             {"name":"unmet-version",
              "iso":"unmet-version.iso",
              "rpms":["unmet-version"]}]

    def run(self, arglist=None):
        # Install the helloworld-user version 1.0 pack
        self.installPack(self.host, self.PACKS[0])
        self.checkInstalledRepos(self.host, self.PACKS[0])
        self.checkRPMS(self.host, self.PACKS[0])

        # Try to install a pack that depends on helloworld-user version 99.0
        # and abort the installation
        self.host.execdom0("mount -t iso9660 -o loop /tmp/%s /mnt" % (self.PACKS[1]['iso']))
        try:
            self.host.execdom0("""cd /mnt && ./install.sh <<EOF
N
EOF""")
        except xenrt.XRTFailure, e:
            # Check we get the expected error
            if not re.search("Error: unsatisfied dependency oem:helloworld-user "
                             "eq 99.0-1", e.data):
                raise xenrt.XRTError("Installation of a supplemental pack with "
                                     "an unsatisfied version dependency was "
                                     "aborted successfully, but found unexpected "
                                     "error message", data=e.data)

        else:
            raise xenrt.XRTFailure("Failed to abort installation of supplemental "
                                   "pack with an unsatisfied version dependency ")

class TC10637(_SupplementalPacksPostInstall):
    """Install a supplemental pack with an unsatisfied version dependency"""

    PACKS = [{"name":"helloworld-user",
              "iso":"helloworld-user.iso",
              "rpms":["helloworld-user"]},
             {"name":"unmet-version",
              "iso":"unmet-version.iso",
              "rpms":["unmet-version"]}]

    def run(self, arglist=None):
        # Install the helloworld-user version 1.0 pack
        self.installPack(self.host, self.PACKS[0])
        self.checkInstalledRepos(self.host, self.PACKS[0])
        self.checkRPMS(self.host, self.PACKS[0])

        # Install the pack that depends on helloworld-user version 99.0
        self.host.execdom0("mount -t iso9660 -o loop /tmp/%s /mnt" % (self.PACKS[1]['iso']))
        try:
            self.host.execdom0("""cd /mnt && ./install.sh <<EOF
Y
EOF""")
        except Exception, e:
            raise xenrt.XRTFailure("Unable to install supplemental pack %s" %
                                   (self.PACKS[1]['name']), str(e))

        self.checkInstalledRepos(self.host, self.PACKS[1])
        self.checkRPMS(self.host, self.PACKS[1])

class TC10638(_SupplementalPacksPostInstall):
    """Install multiple supplemental packs on a running system"""

    PACKS = [{"name":"helloworld-user",
              "iso":"helloworld-user.iso",
              "rpms":["helloworld-user"]},
             {"name":"mypack",
              "iso":"mypack.iso",
              "rpms":["mypack"]},
             {"name":"bugtool",
              "iso":"bugtool.iso",
              "rpms":["bugtool"]}]

class TC10639(_SupplementalPacksPostInstall):
    """Install two versions of a supplemental pack on a running system"""

    PACKS = [{"name":"helloworld-user",
              "iso":"helloworld-user.iso",
              "rpms":["helloworld-user"]},
             {"name":"helloworld-user",
              "iso":"helloworld-user2.0.iso",
              "rpms":["helloworld-user"]}]

    def run(self, arglist=None):
        # Install supplemental pack version 1.0
        self.installPack(self.host, self.PACKS[0])
        self.checkInstalledRepos(self.host, self.PACKS[0])
        self.checkRPMS(self.host, self.PACKS[0])

        # Install supplemental pack version 2.0
        self.host.execdom0("mount -t iso9660 -o loop /tmp/%s /mnt" % (self.PACKS[1]['iso']))
        try:
            self.host.execdom0("""cd /mnt && ./install.sh <<EOF
Y
EOF""")
        except Exception, e:
            raise xenrt.XRTFailure("Unable to install supplemental pack %s 2.0" %
                                   (self.PACKS[1]['name']), str(e))

        self.checkInstalledRepos(self.host, self.PACKS[1])

        # Check version 2.0 rpm is installed
        data = self.host.execdom0("rpm -qi %s" % self.PACKS[1]['name'])
        if not "Version     : 2.0" in data:
            raise xenrt.XRTFailure("RPM package %s 2.0 is not installed" %
                                   (self.PACKS[1]['name']))

class TC10640(_SupplementalPacksPostInstall):
    """Install a supplemental pack that combines multiple driver-rpms and one rpm with EULA on a running system"""

    PACKS = [{"name":"combined", "iso":"combined.iso", 
              "rpms":["combined-data",
                      "combined-modules-xen-2.6.27.37-0.1.1.xs5.5.900.697.1020",
                      "combined-modules-kdump-2.6.27.37-0.1.1.xs5.5.900.697.1020"]}]

    def run(self, arglist=None):
        # Install the supplemental pack
        self.host.execdom0("mount -t iso9660 -o loop /tmp/%s /mnt" % (self.PACKS[0]['iso']))
        try:
            self.host.execdom0("""cd /mnt && ./install.sh <<EOF
Y
EOF""")
        except Exception, e:
            raise xenrt.XRTFailure("Unable to install supplemental pack %s" %
                                   (self.PACKS[0]['name']), str(e))

        self.checkInstalledRepos(self.host, self.PACKS[0])
        self.checkRPMS(self.host, self.PACKS[0])

class TC10641(_SupplementalPacksPostInstall):
    """List supplemental packs installed on a system"""

    PACKS = [{"name":"helloworld-user",
              "iso":"helloworld-user.iso",
              "rpms":["helloworld-user"]},
             {"name":"mypack",
              "iso":"mypack.iso",
              "rpms":["mypack"]},
             {"name":"bugtool",
              "iso":"bugtool.iso",
              "rpms":["bugtool"]}]

    def run(self, arglist=None):
        for pack in self.PACKS:
            self.installPack(self.host, pack)
            self.checkInstalledRepos(self.host, pack)
            self.checkRPMS(self.host, pack)

        # Check the host's software-version parameter lists the packs installed
        data = self.host.paramGet("software-version")
        for pack in self.PACKS:
            reposEntry = "oem:%s" % (pack['name'])
            if not reposEntry in data:
                raise xenrt.XRTFailure("Supplemental pack is not listed in the "
                                       "host's software-version parameter: %s" %
                                       (reposEntry), 
                                       "software-version = %s" % (data))

class _SupplementalPacksBugtool(_SupplementalPacksPostInstall):
    
    PATHS = None
    
    def collectBugtool(self):
        data = self.host.execdom0("/usr/sbin/xen-bugtool -y")
        r = re.search(r"Writing tarball (\S+)", data)
        if not r:
            raise xenrt.XRTFailure("xen-bugtool did not report the tarball "
                                   "path")
        tarball = r.group(1)
        if self.host.execdom0("test -e %s" % (tarball), retval="code") != 0:
            raise xenrt.XRTFailure("Output tarball %s does not exist" %
                           (tarball))
        return tarball

    def checkPathsInTarballList(self, paths, tarballList):
        for path in paths:
            if not re.search("%s$" % (path), tarballList, re.MULTILINE):
                raise xenrt.XRTFailure("xen-bugtool tarball does not "
                                       "contain %s" % (path))

    def run(self, arglist=None):
        for pack in self.PACKS:
            self.installPack(self.host, pack)
            self.checkInstalledRepos(self.host, pack)
            self.checkRPMS(self.host, pack)

        tarball = self.collectBugtool()

        # Check the tarball contains the supplemental pack information
        tarballList = self.host.execdom0("tar -jtf %s" % (tarball))
        self.checkPathsInTarballList(self.PATHS, tarballList)

class TC10643(_SupplementalPacksBugtool):
    """Collect xen-bugtool on a system with xapi running and verify it reports supplemental pack information"""

    PACKS = [{"name":"helloworld-user",
              "iso":"helloworld-user.iso",
              "rpms":["helloworld-user"]},
             {"name":"mypack",
              "iso":"mypack.iso",
              "rpms":["mypack"]},
             {"name":"bugtool",
              "iso":"bugtool.iso",
              "rpms":["bugtool"]}]

    PATHS = ['/etc/xensource/installed-repos/oem:%s/XS-REPOSITORY' % 
             (pack['name']) for pack in PACKS]
    PATHS.extend(['/etc/xensource/installed-repos/oem:%s/XS-PACKAGES' % 
                  (pack['name']) for pack in PACKS])

class TC10644(_SupplementalPacksBugtool):
    """Collect xen-bugtool on a system with xapi stopped and verify it reports supplemental pack information"""

    PACKS = [{"name":"helloworld-user",
              "iso":"helloworld-user.iso",
              "rpms":["helloworld-user"]},
             {"name":"mypack",
              "iso":"mypack.iso",
              "rpms":["mypack"]},
             {"name":"bugtool",
              "iso":"bugtool.iso",
              "rpms":["bugtool"]}]

    PATHS = ['/etc/xensource/installed-repos/oem:%s/XS-REPOSITORY' %
             (pack['name']) for pack in PACKS]
    PATHS.extend(['/etc/xensource/installed-repos/oem:%s/XS-PACKAGES' %
                  (pack['name']) for pack in PACKS])

    def prepare(self, arglist=None):
        _SupplementalPacksBugtool.prepare(self, arglist)
        self.host.execdom0("service xapi stop")

    def postRun(self):
        _SupplementalPacksBugtool.postRun(self)
        self.host.startXapi()

class TC10645(_SupplementalPacksBugtool):
    """Verify xen-bugtool collects files and directories specified by a supplemental pack"""

    PACKS = [{"name":"bugtool",
              "iso":"bugtool.iso",
              "rpms":["bugtool"]}]

    # Files and directories specified by the pack:
    # Files: 
    #   - /etc/bugtool.conf
    #   - /etc/xensource/bugtool/supp_pack/bugtool_directives.xml
    # Directories:
    #   - /usr/share/doc/bugtool/*.txt (*.txt = bugtool.txt, bugtool2.txt)
    PATHS = ['/etc/bugtool.conf',
             '/etc/xensource/bugtool/supp_pack/bugtool_directives.xml',
             '/usr/share/doc/bugtool/bugtool.txt',
             '/usr/share/doc/bugtool/bugtool2.txt']

class _SupplementalPacksBugtool2(_SupplementalPacksBugtool):

    FILENAME = None
    FILE_CONTENTS = None

    def run(self, arglist=None):
        self.installPack(self.host, self.PACKS[0])
        self.checkInstalledRepos(self.host, self.PACKS[0])
        self.checkRPMS(self.host, self.PACKS[0])

        tarball = self.collectBugtool()

        # Check tarball contains the file created by the pack's data collection routine
        tarballList = self.host.execdom0("tar -jtf %s" % (tarball))
        self.checkPathsInTarballList([self.FILENAME], tarballList)

        # Check the contents of the file
        basedir = os.path.basename(tarball).replace(".tar.bz2", "")
        self.host.execdom0("tar -jxf %s -C /tmp/ %s/%s" %
                           (tarball, basedir, self.FILENAME))
        data = self.host.execdom0("cat /tmp/%s/%s" % (basedir, self.FILENAME))
        if data != self.FILE_CONTENTS:
            raise xenrt.XRTFailure("The contents of %s differ from the expected "
                                   "output" % (self.FILENAME),
                                   "Expected file contents: \n%s"
                                   "Actual file contents: \n%s" %
                                   (self.FILE_CONTENTS, data))

class TC10646(_SupplementalPacksBugtool2):
    """Collect xen-bugtool on a system with a supplemental pack that includes its own data collection routine"""

    PACKS = [{"name":"bugtool2",
              "iso":"bugtool2.iso",
              "rpms":["bugtool2"]}]
    FILENAME = "supp_pack2.out"
    FILE_CONTENTS = """This is an example.
Version: 1.0
Release: 1
This is an example2.
Version: 1.0
Release: 1
This is the end of my bugtool data collection routine.
"""
 
class TC10647(_SupplementalPacksBugtool2):
    """Collect xen-bugtool on a system with a supplemental pack that includes its own data collection routine which exits with an error"""

    PACKS = [{"name":"bugtool3",
              "iso":"bugtool3.iso",
              "rpms":["bugtool3"]}]
    FILENAME = "supp_pack3.out"
    FILE_CONTENTS = """Exiting bugtool data collection routine with an error.
"""

class TC10648(_SupplementalPacksBugtool2):
    """Collect xen-bugtool on a system with a supplemental pack that includes its own data collection routine which never returns"""

    PACKS = [{"name":"bugtool4",
              "iso":"bugtool4.iso",
              "rpms":["bugtool4"]}]
    FILENAME = "supp_pack4.out"
    FILE_CONTENTS = """This is an example.

** timeout **
"""

class _SupplementalPacksHomogeneity(_SupplementalPacksPostInstall):

    def prepare(self, arglist=None):
        # Prepare two independent hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()

        # Create the pool
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.pool.check()

        self.hosts = [self.host0, self.host1]

    def run(self, arglist=None):
        for host in self.hosts:
            for pack in self.PACKS:
                self.installPack(host, pack)
                self.checkInstalledRepos(host, pack)
                self.checkRPMS(host, pack)

        self.pool.addHost(self.host1)
        self.pool.check()

    def postRun(self):
        # Uninstall the supplemental packs
        for host in self.hosts:
            try:
                host.execdom0("umount /mnt")
            except:
                pass

            for pack in self.PACKS:
                try:
                    self.uninstallPack(host, pack)
                except:
                    pass

class TC10649(_SupplementalPacksHomogeneity):
    """Add a host with a supplemental pack that requires homogeneity to a pool with the pack installed"""

    PACKS = [{"name":"homogeneous",
              "iso":"homogeneous.iso",
              "rpms":["homogeneous"]}]

    def prepare(self, arglist=None):
        _SupplementalPacksHomogeneity.prepare(self, arglist)

        self.hosts = [self.host0, self.host1]

        # Get the supplemental pack iso on both hosts
        for host in self.hosts:
            for pack in self.PACKS:
                self.downloadPackISO(host, pack)

class TC10650(_SupplementalPacksHomogeneity):
    """Add a host with a supplemental pack that requires homogeneity to a pool without the pack installed"""

    PACKS = [{"name":"homogeneous",
              "iso":"homogeneous.iso",
              "rpms":["homogeneous"]}]

    def prepare(self, arglist=None):
        _SupplementalPacksHomogeneity.prepare(self, arglist)

        self.hosts = [self.host1]

        # Get the supplemental pack iso on the standalone host
        for host in self.hosts:
            for pack in self.PACKS:
                self.downloadPackISO(host, pack)

class TC10651(_SupplementalPacksHomogeneity):
    """Add a freshly installed host to a pool that has a supplemental pack installed that requires homogeneity"""

    PACKS = [{"name":"homogeneous",
              "iso":"homogeneous.iso",
              "rpms":["homogeneous"]}]

    def prepare(self, arglist=None):
        _SupplementalPacksHomogeneity.prepare(self, arglist)

        self.hosts = [self.host0]

        # Get the supplemental pack iso on the pool host (master)
        for host in self.hosts:
            for pack in self.PACKS:
                self.downloadPackISO(host, pack)

class TC10652(_SupplementalPacksHomogeneity):
    """Add a freshly installed host to a pool that has a supplemental pack installed that doesn't require homogeneity"""

    PACKS = [{"name":"helloworld-user",
              "iso":"helloworld-user.iso",
              "rpms":["helloworld-user"]}]

    def prepare(self, arglist=None):
        _SupplementalPacksHomogeneity.prepare(self, arglist)

        self.hosts = [self.host0]

        # Get the supplemental pack iso on the pool host (master)
        for host in self.hosts:
            for pack in self.PACKS:
                self.downloadPackISO(host, pack)

class TC10653(_SupplementalPacksHomogeneity):
    """Add a host with a supplemental pack that doesn't require homogeneity to a pool without the pack installed"""

    PACKS = [{"name":"helloworld-user",
              "iso":"helloworld-user.iso",
              "rpms":["helloworld-user"]}]

    def prepare(self, arglist=None):
        _SupplementalPacksHomogeneity.prepare(self, arglist)

        self.hosts = [self.host1]

        # Get the supplemental pack iso on the standalone host
        for host in self.hosts:
            for pack in self.PACKS:
                self.downloadPackISO(host, pack)

class TC10654(_SupplementalPacksHomogeneity):
    """Add a host with a supplemental pack that doesn't require homogeneity to a pool with the pack installed"""

    PACKS = [{"name":"helloworld-user",
              "iso":"helloworld-user.iso",
              "rpms":["helloworld-user"]}]

    def prepare(self, arglist=None):
        _SupplementalPacksHomogeneity.prepare(self, arglist)

        self.hosts = [self.host0, self.host1]

        # Get the supplemental pack iso on both hosts
        for host in self.hosts:
            for pack in self.PACKS:
                self.downloadPackISO(host, pack)

class TC10655(testcases.xenserver.tc.upgrade._SingleHostUpgrade,
              _SupplementalPacksDuringInstall):
    """Verify supplemental packs can be installed on a host during upgrade"""

    PACKS = [{"name":"helloworld-user",
              "iso":"helloworld-user.iso",
              "rpms":["helloworld-user"]},
             {"name":"mypack",
              "iso":"mypack.iso",
              "rpms":["mypack"]},
             {"name":"bugtool",
              "iso":"bugtool.iso",
              "rpms":["bugtool"]}]

    def installOld(self):
        old = xenrt.TEC().lookup("OLD_PRODUCT_VERSION")
        oldversion = xenrt.TEC().lookup("OLD_PRODUCT_INPUTDIR")
        self.host = xenrt.lib.xenserver.createHost(id=0,
                                                   version=oldversion,
                                                   productVersion=old,
                                                   installSRType="lvm",
                                                   addToLogCollectionList=True)

    def upgrade(self, newVersion):
        self.host.tailored = False
        xenrt.lib.xenserver.cli.clearCacheFor(self.host.machine)
        suppackcds = ",".join([pack['iso'] for pack in self.PACKS])
        self.host = self.host.upgrade(newVersion=newVersion, suppackcds=suppackcds)
        time.sleep(180)
        self.host.check()
        if len(self.host.listGuests()) == 0 and not self.NO_VMS:
            raise xenrt.XRTFailure("VMs missing after host upgrade")

    def run(self, arglist=None):
        self.host = None
        testcases.xenserver.tc.upgrade._SingleHostUpgrade.run(self, arglist)
        if not self.host:
            raise xenrt.XRTError("Host upgrade failed")

        # Check the supplemental packs are properly installed
        for pack in self.PACKS:
            self.checkInstalledRepos(self.host, pack)
            self.checkRPMS(self.host, pack)

    def postRun(self):
        # Uninstall the supplemental packs
        _SupplementalPacksDuringInstall.postRun(self)

class _SupplementalPacksPostInstallDom0Mem(_SupplementalPacksPostInstall):
    DEFAULT_MEM_OVER_MIN = 100 # MiB

    def prepare(self, arglist=None):
        _SupplementalPacksPostInstall.prepare(self, arglist)

        self.dom0 = self.host.getMyDomain0UUID()
        self.cli = self.host.getCLIInstance()

        # Find the current dom0 memory target
        self.original = int(self.host.genParamGet("vm", 
                                                  self.dom0, 
                                                  "memory-target"))

        # Calculate the dom0 memory target after the pack installation
        smin = int(self.host.genParamGet("vm", 
                                         self.dom0, 
                                         "memory-static-min"))
        self.target = smin + (self.PACK_MEM+self.DEFAULT_MEM_OVER_MIN)*xenrt.MEGA

        # dom0 memory target is capped at memory-static-max
        smax = int(self.host.genParamGet("vm",
                                         self.dom0,
                                         "memory-static-max"))
        if self.target > smax:
            self.target = smax

    def run(self, arglist=None):
        self.installPack(self.host, self.PACKS[0])
        self.checkInstalledRepos(self.host, self.PACKS[0])
        self.checkRPMS(self.host, self.PACKS[0])

        # Wait for dom0 to reach the new memory target
        self.cli.execute("vm-memory-target-wait", "uuid=%s" % (self.dom0))
        time.sleep(60)

        # Verify dom0 memory is set to the new target
        self.checkmem(self.target)

    def postRun(self):
        _SupplementalPacksPostInstall.postRun(self)

        self.cli.execute("vm-memory-target-set",
                         "target=%u uuid=%s" % (self.original, self.dom0))
        self.cli.execute("vm-memory-target-wait", "uuid=%s" % (self.dom0))

class TC10656(_SupplementalPacksPostInstallDom0Mem):
    """Verify dom0 memory after installing a supplemental pack on a running system with enough free memory to accommodate the additional software"""

    PACKS    = [{"name":"smallmemory",
                 "iso":"smallmemory.iso",
                 "rpms":["smallmemory"]}]
    PACK_MEM = 60  # MiB

class TC10657(_SupplementalPacksPostInstallDom0Mem):
    """Verify dom0 memory after installing a supplemental pack on a running system without enough free memory to accommodate the additional software"""

    PACKS    = [{"name":"bigmemory",
                 "iso":"bigmemory.iso",
                 "rpms":["bigmemory"]}]
    PACK_MEM = 2048  # MiB

class TC10658(_SupplementalPacksPostInstallDom0Mem):
    """Verify dom0 memory at boot time after installing a supplemental pack on a running system with enough free memory to accommodate the additional software"""

    PACKS    = [{"name":"smallmemory",
                 "iso":"smallmemory.iso",
                 "rpms":["smallmemory"]}]
    PACK_MEM = 60  # MiB

    def run(self, arglist=None):
        self.installPack(self.host, self.PACKS[0])
        self.checkInstalledRepos(self.host, self.PACKS[0])
        self.checkRPMS(self.host, self.PACKS[0])

        self.host.reboot()

        # Verify dom0 memory is set to the new target
        self.checkmem(self.target)

class TC10659(_SupplementalPacksPostInstallDom0Mem):
    """Verify dom0 memory at boot time after installing a supplemental pack on a running system without enough free memory to accommodate the additional software"""

    PACKS    = [{"name":"bigmemory",
                 "iso":"bigmemory.iso",
                 "rpms":["bigmemory"]}]
    PACK_MEM = 2048  # MiB

    def run(self, arglist=None):
        self.installPack(self.host, self.PACKS[0])
        self.checkInstalledRepos(self.host, self.PACKS[0])
        self.checkRPMS(self.host, self.PACKS[0])

        self.host.reboot()

        # Verify dom0 memory is set to the new target
        self.checkmem(self.target)

class _SupplementalPacksDuringInstallDom0Mem(_SupplementalPacksDuringInstall):

    # Override _SupplementalPacksPostInstallDom0Mem's prepare method
    def prepare(self, arglist=None):
        pass

    def run(self, arglist=None):
        # Perform host installation with supplemental packs
        _SupplementalPacksDuringInstall.run(self, arglist)

        self.dom0 = self.host.getMyDomain0UUID()
        self.cli = self.host.getCLIInstance()

        # Calculate the dom0 memory target
        self.smin = int(self.host.genParamGet("vm",
                                              self.dom0,
                                              "memory-static-min"))
        self.target = self.smin + \
                      (self.PACK_MEM + self.DEFAULT_MEM_OVER_MIN) * xenrt.MEGA

        # dom0 memory target is capped at memory-static-max
        self.smax = int(self.host.genParamGet("vm",
                                              self.dom0,
                                              "memory-static-max"))
        if self.target > self.smax:
            self.target = self.smax

        # Verify dom0 memory is set to the target
        self.checkmem(self.target)

    def postRun(self):
        # Uninstall the supplemental pack
        _SupplementalPacksDuringInstall.postRun(self)

        # Dom0 memory target without the pack
        newtarget = self.smin + (self.DEFAULT_MEM_OVER_MIN * xenrt.MEGA)
        if newtarget < self.smax:
            self.cli.execute("vm-memory-target-set",
                             "target=%u uuid=%s" % (newtarget, self.dom0))
            self.cli.execute("vm-memory-target-wait", "uuid=%s" % (self.dom0))

class TC10660(_SupplementalPacksDuringInstallDom0Mem):
    """Verify dom0 memory after installing a host with a supplemental pack that has small memory requirements"""

    PACKS    = [{"name":"smallmemory",
                 "iso":"smallmemory.iso",
                 "rpms":["smallmemory"]}]
    PACK_MEM = 60  # MiB

class TC10661(_SupplementalPacksDuringInstallDom0Mem):
    """Verify dom0 memory after installing a host with a supplemental pack whose memory requirements exceed the available memory in dom0"""

    PACKS    = [{"name":"bigmemory",
                 "iso":"bigmemory.iso",
                 "rpms":["bigmemory"]}]
    PACK_MEM = 2048  # MiB

class TC10662(xenrt.TestCase):
    """Download the web page from the host on port 80 and verify its contents"""

    def run(self, arglist=None):
        host = self.getDefaultHost()
        url = "http://%s/" % (host.getIP())
        localtemp = xenrt.TEC().tempFile()
        try:
            xenrt.command("curl '%s' -o %s" % (url, localtemp))
        except Exception, e:
            raise xenrt.XRTFailure("Unable to retrieve web page from the host",
                                   str(e))
        
        page =  xenrt.command("cat %s" % (localtemp))

        # Check the page contents
        if not re.search("<body>.*XenServer", page, re.DOTALL):
            raise xenrt.XRTFailure("Web page does not contain the product name",
                                   page)

        if not re.search("<body>.*XenServer [0-9]+\.[0-9]+", page, re.DOTALL):
            raise xenrt.XRTFailure("Web page does not contain the product "
                                   "version", page)

        if not re.search("<body>.*<a href=\"(XenCenter.msi|XenCenterSetup.exe)\">", page, re.DOTALL):
            raise xenrt.XRTFailure("Web page does not contain a link to the "
                                   "XenCenter msi or exe file", page)

        if not re.search("<body>.*<a href=\"XenCenter.iso\">", page, re.DOTALL):
            raise xenrt.XRTFailure("Web page does not contain a link to the "
                                   "XenCenter iso file", page)
        
class TC10663(xenrt.TestCase):
    """Download the XenCenter msi file from the host"""

    def run(self, arglist=None):
        host = self.getDefaultHost()
        url = "http://%s/" % (host.getIP())
        localtemp = xenrt.TEC().tempFile()
        
        # Check whether XenCenter.msi or XenCenterSetup.exe exists
        try:
            xenrt.command("curl '%s' -o %s" % (url, localtemp))
        except Exception, e:
            raise xenrt.XRTFailure("Unable to retrieve web page from the host",
                                   str(e))
        
        page =  xenrt.command("cat %s" % (localtemp))
        
        m = re.search("<body>.*<a href=\"(XenCenter.msi|XenCenterSetup.exe)\">", page, re.DOTALL)
        if m:
            url = "http://%s/%s" % (host.getIP(), m.group(1))
        else:
            xenrt.XRTFailure("Unable to retrieve XenCenter.msi or XenCenterSetup.exe files")
        
        temp = xenrt.TEC().tempFile()
        try:
            page = xenrt.command("curl '%s' -o %s" % (url, temp))
        except Exception, e:
            raise xenrt.XRTFailure("Unable to download XenCenter msi file from "
                                   "the host", str(e))

class TC10664(xenrt.TestCase):
    """Download the XenCenter ISO file from the host"""

    def run(self, arglist=None):
        host = self.getDefaultHost()
        url = "http://%s/XenCenter.iso" % (host.getIP())
        localtemp = xenrt.TEC().tempFile()
        try:
            page = xenrt.command("curl '%s' -o %s" % (url, localtemp))
        except Exception, e:
            raise xenrt.XRTFailure("Unable to download XenCenter ISO file from "
                                   "the host", str(e))

class TC10665(_SupplementalPacksPostInstall):
    """Install a supplemental pack that includes a customized web page"""

    PACKS = [{"name":"webpage",
              "iso":"webpage.iso",
              "rpms":["webpage"]}]

    FILE_CONTENTS = """<html>
  <title>My Custom Web Page</title>
<head>
</head>
<body>
  <p/>My Custom Web Page - Citrix Systems, Inc. XenServer 5.5.900
  <p/><a href="XenCenter.msi">XenCenter installer</a>
</body>
</html>
"""

    def run(self, arglist=None):
        # Backup the original index.html
        self.host.execdom0("cp /opt/xensource/www/index.html /tmp/")

        # Install the supplemental pack
        _SupplementalPacksPostInstall.run(self, arglist)

        # Check the contents of the new web page
        url = "http://%s/" % (self.host.getIP())
        localtemp = xenrt.TEC().tempFile()
        try:
            xenrt.command("curl '%s' -o %s" % (url, localtemp))
        except Exception, e:
            raise xenrt.XRTFailure("Unable to retrieve web page from the host",
                                   str(e))

        page =  xenrt.command("cat %s" % (localtemp))
        
        if page != self.FILE_CONTENTS:
            raise xenrt.XRTFailure("Unexpected web page found on the host",
                                   "Expected: \n%s"
                                   "Actual: \n%s" %
                                   (self.FILE_CONTENTS, page))
    def postRun(self):
        # Uninstall the supplemental pack
        _SupplementalPacksPostInstall.postRun(self)

        # Restore the original index.html
        self.host.execdom0("cp /tmp/index.html /opt/xensource/www/")

class _VgpuSuppackInstall(xenrt.TestCase):
    #verify vGPU suppack install on host 
    def isNvidiaVgpuSuppackInstalled(self, host):
        return "NVIDIA Corporation" in host.execdom0("xe vgpu-type-list")


class TCinstallNvidiaVgpuHostSupPacks(_VgpuSuppackInstall):
    def run(self, arglist):
        suppackISOpath = None
        suppackISOname = None
        args = self.parseArgsKeyValue(arglist)
        suppackISOpath = args['suppackISOpath']
        suppackISOname = args['suppackISOname']
        host = self.getDefaultHost()
        #check if vGPU suppack already installed
        if self.isNvidiaVgpuSuppackInstalled(host):
            xenrt.TEC().logverbose("Nvidia VGPU supplementary pack already installed")
            return
        #install suppack
        host.installHostSupPacks(suppackISOpath, suppackISOname)
        #Check installation successful or not
        if self.isNvidiaVgpuSuppackInstalled(host):
            xenrt.TEC().logverbose("Nvidia VGPU supplementary pack installed successfully")
        else:
            raise xenrt.XRTFailure("Nvidia VGPU supplementary pack not installed successfully")

class TCinstallVgpuPacksWithXenServer(_VgpuSuppackInstall):
    def run(self, arglist):
        isVgpuInstalled = False
        host = self.getDefaultHost()
        #Check installation successful or not
        if self.isNvidiaVgpuSuppackInstalled(host):
            xenrt.TEC().logverbose("Nvidia VGPU supplementary pack installation along with xenserver was successful")
        else:
            raise xenrt.XRTFailure("Nvidia VGPU supplementary pack installation along with xenserver was not successful")
