#
# XenRT: Test harness for Xen and the XenServer product family
#
# Dell Factory standalone testcases
#
# Copyright (c) 2010 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import os.path
import xenrt, xenrt.lib.xenserver


class TC11155(xenrt.TestCase):
    """Create Dell Factory Installation image from the XenServer installation ISOs"""

    TAR  = "oem-phase-1/dell-factory-install.tar"
    TAR2 = "dell-factory-install.tar"
    OUTPUT_ZIP = "output.zip"

    def prepare(self, arglist):
        tar_ball = xenrt.TEC().getFile(self.TAR, self.TAR2)
        if tar_ball is None:
            raise xenrt.XRTError("Couldn't find %s in build output" % (self.TAR))
        self.temp_dir = xenrt.TEC().tempDir()
        xenrt.command("tar -C %s -xvf %s" % (self.temp_dir, tar_ball))

        self.output = "%s/%s" % (self.temp_dir, self.OUTPUT_ZIP)

        imageName = xenrt.TEC().lookup("CARBON_CD_IMAGE_NAME", 'main.iso')
        xenrt.TEC().logverbose("Using XS install image name: %s" % (imageName))
        cd = xenrt.TEC().getFile("xe-phase-1/%s" % (imageName), imageName) 
        if not cd:
            raise xenrt.XRTError("No main CD image supplied.")
        xenrt.checkFileExists(cd)
        self.maincd = cd

        cd = None
        cd = xenrt.TEC().getFile("linux.iso", "xe-phase-1/linux.iso")
        if not cd:
            raise xenrt.XRTError("No linux CD image supplied.")
        xenrt.checkFileExists(cd)
        self.linuxcd = cd

    def run(self, arglist):
        xenrt.command("sudo %s/build-fi-image.sh -o %s %s %s" % 
                      (self.temp_dir, self.output, self.maincd, self.linuxcd))
        xenrt.checkFileExists(self.output, level=xenrt.RC_FAIL)


class TC11156(TC11155):
    """Create Dell Factory Installation image from the XenServer installation ISOs and a supplemental pack"""

    PACKS = ["helloworld-user.iso"]

    def prepare(self, arglist):
        TC11155.prepare(self, arglist)

        self.spcds = []
        for spcdi in self.PACKS:
            # Try a fetch from the inputdir first
            spcd = xenrt.TEC().getFile(spcdi)
            if not spcd:
                # Try the local test inputs
                spcd = "%s/suppacks/%s" % (\
                    xenrt.TEC().lookup("TEST_TARBALL_ROOT"),
                    os.path.basename(spcdi))
                if not os.path.exists(spcd):
                    raise xenrt.XRTError(\
                        "Supplemental pack CD not found locally or "
                        "remotely: %s" % (spcdi))
            self.spcds.append(spcd)

    def run(self, arglist):
        xenrt.command("sudo %s/build-fi-image.sh -o %s %s %s %s" %
                      (self.temp_dir, self.output, self.maincd, self.linuxcd,
                       " ".join(self.spcds)))
        xenrt.checkFileExists(self.output, level=xenrt.RC_FAIL)

class TC11157(TC11156):
    """Create Dell Factory Installation image from the XenServer installation ISOs and multiple supplemental packs"""

    PACKS = ["helloworld-user.iso",
             "mypack.iso",
             "bugtool.iso"]

class TC11158(TC11156):
    """Create Dell Factory Installation image from the XenServer installation ISOs and a supplemental pack that combines multiple driver-rpm and rpm packages"""

    PACKS = ["combined.iso"]

class TC11159(xenrt.TestCase):
    """Verify Dell Utility Partition is preserved after XenServer installation"""

    def existsDellUtility(self, host):
        # Returns True if dell utility partition is present.
        # Returns False, otherwise.
        data = host.execdom0("fdisk -l /dev/sda | grep sda1")
        return "Dell Utility" in data

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()

        if not self.existsDellUtility(self.host):
            # Create dell utility partition
            try:
                self.host.execdom0("""fdisk /dev/sda <<EOF
d
1
n
p
1
1
+60M
t
1
de
w
EOF""")
            except Exception, e:
                pass

            # Verify dell utility partition was created successfully
            if not self.existsDellUtility(self.host):
                raise xenrt.XRTError("Unable to find dell utility partition")

    def run(self, arglist=None):
        # Perform host installation
        productVersion = xenrt.TEC().lookup("PRODUCT_VERSION")
        inputDir = xenrt.TEC().lookup("INPUTDIR")
        self.host = xenrt.lib.xenserver.createHost(id=0,
                                                   version=inputDir,
                                                   productVersion=productVersion,
                                                   installSRType="lvm",
                                                   addToLogCollectionList=True)

        # Check the Dell Utility Partition is preserved after installation
        if not self.existsDellUtility(self.host):
            raise xenrt.XRTFailure("Unable to find dell utility partition "
                                   "after XenServer installation")

class TC11160(xenrt.TestCase):
    """Verify MBR is preserved after XenServer installation"""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.workdir = xenrt.TEC().getWorkdir()

        # Get a copy of the MBR from the host prior to installation
        self.host.execdom0("dd if=/dev/sda of=/tmp/mbr1 bs=512 count=1")
        sftp = self.host.sftpClient()
        sftp.copyFrom("/tmp/mbr1", "%s/mbr1" % (self.workdir))

    def run(self, arglist=None):
        # Perform host installation
        productVersion = xenrt.TEC().lookup("PRODUCT_VERSION")
        inputDir = xenrt.TEC().lookup("INPUTDIR")
        self.host = xenrt.lib.xenserver.createHost(id=0,
                                                   version=inputDir,
                                                   productVersion=productVersion,
                                                   installSRType="lvm",
                                                   addToLogCollectionList=True)

        # Get a copy of the MBR from the host after installation
        self.host.execdom0("dd if=/dev/sda of=/tmp/mbr2 bs=512 count=1")
        sftp = self.host.sftpClient()
        sftp.copyFrom("/tmp/mbr2", "%s/mbr2" % (self.workdir))

        # Check the MBR is preserved after installation
        try:
            xenrt.command("diff %s/mbr1 %s/mbr2" %
                          (self.workdir, self.workdir))
        except Exception, e:
            raise xenrt.XRTFailure("MBR was not preserved after installation")

