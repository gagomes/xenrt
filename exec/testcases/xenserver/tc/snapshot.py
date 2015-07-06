#
# XenRT: Test harness for Xen and the XenServer product family
#
# Testcases for snapshot features.
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and conditions
# as licensed by Citrix Systems, Inc. All other rights reserved.
#

import string, time, re, traceback, sys
import xml.dom.minidom
import xenrt, testcases
from xenrt.lazylog import log, step

class _VDISnapshotBase(xenrt.TestCase):
    """Base class for VDI Snapshot Tests."""

    SRTYPE = "ext"
    VDICREATE_SMCONFIG = None

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.host = None
        self.guests = []
        self.vdis = []
        # Default VDI sizes to 100Mb.
        self.size = 100*1024*1024
        self.sr = None

    def vdicommand(self, command, vdiuuid):
        sftp = self.host.sftpClient()
        sd = self.host.hostTempDir()
        t = xenrt.TempDirectory()

        s = "%s/cmd.sh" % (sd)
        filename = "%s/cmd.sh" % (t.path())

        file(filename, "w").write(command)
        sftp.copyTo("%s/cmd.sh" % (t.path()), s)
        self.host.execdom0("chmod +x %s" % (s))
        data = self.host.execdom0("/opt/xensource/debug/with-vdi %s %s" %
                                  (vdiuuid, s))
        self.host.execdom0("rm -rf %s" % (sd))
        t.remove()
        return data

    def vdichecksum(self, vdiuuid):
        checksum = "sha1sum /dev/${DEVICE}"
        vdihash = self.vdicommand(checksum, vdiuuid).splitlines()[-1].split()[0]
        xenrt.TEC().logverbose("SHA1SUM of VDI %s: %s" % (vdiuuid, vdihash))
        return vdihash

    def vdiformat(self, vdiuuid):
        format = "mkfs.ext2 /dev/${DEVICE}"
        self.vdicommand(format, vdiuuid)
        xenrt.TEC().logverbose("Formatted VDI %s." % (vdiuuid))

    def vdimodify(self, vdiuuid):
        modify = """
mount /dev/${DEVICE} /mnt
dd if=/dev/urandom of=/mnt/random bs=1M count=10
umount /mnt
"""
        self.vdicommand(modify, vdiuuid)
        xenrt.TEC().logverbose("Modified VDI %s." % (vdiuuid))

    def createguest(self):
        xenrt.TEC().logverbose("Creating test VM.")
        g = self.host.createGenericLinuxGuest(sr=self.sr)
        self.guests.append(g)
        return g

    def postRun(self):
        # For debugging purposes list the VDIs we have
        cli = self.host.getCLIInstance()
        try:
            cli.execute("vdi-list", "sr-uuid=%s" % (self.sr))
        except:
            pass
        for v in self.vdis:
            try:
                vbds = self.host.minimalList("vbd-list",
                                             args="vdi-uuid=%s" % (v))
                for vbduuid in vbds:
                    if self.host.genParamGet("vbd",
                                             vbduuid,
                                             "currently-attached") == "true":
                        cli.execute("vbd-unplug", "uuid=%s" % (vbduuid))
                    cli.execute("vbd-destroy", "uuid=%s" % (vbduuid))
                self.host.destroyVDI(v)
            except:
                pass
        for g in self.guests:
            try:
                g.shutdown(force=True)
            except:
                pass
            try:
                g.uninstall()
            except:
                pass
        try:
            cli.execute("vdi-list", "sr-uuid=%s" % (self.sr))
        except:
            pass

class _VDISnapshotStress(_VDISnapshotBase):
    """Base class for VDI snapshot stress tests."""

    ITERATIONS = 100

    def startworkload(self, guest):
        sftp = guest.sftpClient()
        t = xenrt.TempDirectory()

        script = """
CMD="/usr/local/bin/sysbench --test=fileio --validate=on --file-total-size=90M --file-test-mode=rndrw"
LOG="/tmp/work.log"
cd /mnt
${CMD} prepare 2>&1 >> ${LOG}
while [ -e /tmp/.workflag ]; do
    ${CMD} run 2>&1 >> ${LOG}
done
cd /
umount /mnt
"""
        s = "/tmp/workload.sh"
        filename = "%s/workload.sh" % (t.path())

        file(filename, "w").write(script)
        sftp.copyTo(filename, s)
        guest.execguest("chmod +x %s" % (s))

        xenrt.TEC().logverbose("Starting workload...")
        guest.execguest("touch /tmp/.workflag")
        workload = testcases.benchmarks.workloads.LinuxSysbench(guest)
        workload.cmdline = "/tmp/workload.sh &> /dev/null < /dev/null &"
        workload.start()

    def loop(self, iterations, vdiuuid):
        pass

    def run(self, arglist):
        iterations = self.ITERATIONS
        self.host = self.getDefaultHost()

        srs = self.host.getSRs(type=self.SRTYPE)
        if not srs:
            raise xenrt.XRTError("No %s SR found on host." % (self.SRTYPE))
        self.sr = srs[0]
        self.host.waitForCoalesce(self.sr)

        g = self.createguest()

        xenrt.TEC().logverbose("Creating a test VDI.")
        vdiuuid = self.host.createVDI(self.size,
                                      sruuid=self.sr,
                                      smconfig=self.VDICREATE_SMCONFIG)
        self.vdis.append(vdiuuid)

        xenrt.TEC().logverbose("Plugging VDI.")
        userdevice = g.createDisk(vdiuuid=vdiuuid)
        device = self.host.parseListForOtherParam("vbd-list",
                                                  "vm-uuid",
                                                   g.getUUID(),
                                                  "device",
                                                  "userdevice=%s" %
                                                  (userdevice))

        xenrt.TEC().logverbose("Formatting VDI within VM.")
        time.sleep(30)
        g.execguest("mkfs.ext2 /dev/%s" % (device))
        g.execguest("mount /dev/%s /mnt" % (device))

        self.startworkload(g)

        self.loop(iterations, vdiuuid)

        # Stop the workload
        g.execguest("rm -f /tmp/.workflag")

        # Check for errors in workload.
        if not g.execguest("grep -q 'Validation failed' /tmp/work.log", retval="code"):
            raise xenrt.XRTFailure("Possible data corruption detected.")

        g.execguest("killall -9 sysbench || true")

class _TC7802(_VDISnapshotStress):
    """Repeated VDI snapshot/destroy under I/O load."""

    def loop(self, iterations, vdiuuid):
        for i in range(iterations):
            xenrt.TEC().logverbose("Snapshot iteration %s." % (i))
            snapuuid = self.host.snapshotVDI(vdiuuid)
            xenrt.TEC().logverbose("Delete iteration %s." % (i))
            self.host.destroyVDI(snapuuid)

class TC7802(_TC7802):
    """Repeated VDI snapshot/destroy under I/O load."""

    ITERATIONS = 29

class TC27102(_TC7802):
    """Repeated VDI snapshot/destroy under I/O load."""

    ITERATIONS = 29
    SRTYPE = "btrfs"


class TC7966(_TC7802):
    """Repeated LVM VDI snapshot/destroy under I/O load."""

    SRTYPE = "lvm"
    ITERATIONS = 29

class TC7976(_TC7802):
    """Repeated NetApp VDI snapshot/destroy under I/O load."""

    SRTYPE = "netapp"

class TC8075(_TC7802):
    """Repeated Equallogic VDI snapshot/destroy under I/O load."""

    SRTYPE = "equal"
class TC9690(_TC7802):
    """Repeated CVSM VDI snapshot/destroy under I/O load."""

    SRTYPE = "cslg"

class TC9927(_TC7802):
    """Repeated CVSM-fc VDI snapshot/destroy under I/O load."""

    SRTYPE = "cslg"

class _TC7801(_VDISnapshotStress):
    """Repeated VDI snapshot under I/O load followed by repeated destroy."""

    def loop(self, iterations, vdiuuid):
        for i in range(iterations):
            xenrt.TEC().logverbose("Snapshot iteration %s." % (i))
            snapuuid = self.host.snapshotVDI(vdiuuid)
            self.vdis.append(snapuuid)

        for i in range(iterations):
            xenrt.TEC().logverbose("Delete iteration %s." % (i))
            self.host.destroyVDI(self.vdis[i+1])

class TC7801(_TC7801):
    """Repeated VDI snapshot under I/O load followed by repeated destroy."""

    ITERATIONS = 29

class TC27101(_TC7801):
    """Repeated VDI snapshot under I/O load followed by repeated destroy."""

    ITERATIONS = 29
    SRTYPE = "btrfs"


class TC7965(_TC7801):
    """Repeated VDI snapshot under I/O load followed by repeated destroy."""

    SRTYPE = "lvm"
    ITERATIONS = 29

class TC7975(_TC7801):
    """Repeated NetApp snapshot under I/O load followed by repeated destroy."""

    SRTYPE = "netapp"

class TC8074(_TC7801):
    """Repeated Equallogic snapshot under I/O load followed by repeated destroy."""

    SRTYPE = "equal"
    VDICREATE_SMCONFIG = "snap-reserve-percentage=10000"
class TC9691(_TC7801):
    """Repeated CVSM snapshot under I/O load followed by repeated destroy."""

    SRTYPE = "cslg"

class TC15182(_TC7801):
    """Repeated CVSM snapshot under I/O load followed by repeated destroy (SMI-S FC)."""
    SRTYPE = "cslg"
    ITERATIONS = 7

class TC9926(_TC7801):
    """Repeated CVSM-fc snapshot under I/O load followed by repeated destroy."""

    SRTYPE = "cslg"


class _TC7800(_VDISnapshotBase):
    """Multiple VDI snapshots of the same original."""

    ITERATIONS = 100

    def check(self, vdiuuid):
        check = """
mount -o ro /dev/${DEVICE} /mnt
cat /mnt/counter
sync
umount /mnt
"""
        data = self.vdicommand(check, vdiuuid).splitlines()[-1].split()[0]
        return int(data)

    def run(self, arglist):
        self.host = self.getDefaultHost()
        iterations = self.ITERATIONS

        srs = self.host.getSRs(type=self.SRTYPE)
        if not srs:
            raise xenrt.XRTError("No %s SR found on host." % (self.SRTYPE))
        self.sr = srs[0]
        self.host.waitForCoalesce(self.sr)

        g = self.createguest()

        xenrt.TEC().logverbose("Creating a test VDI.")
        vdiuuid = self.host.createVDI(self.size,
                                      sruuid=self.sr,
                                      smconfig=self.VDICREATE_SMCONFIG)
        self.vdis.append(vdiuuid)

        xenrt.TEC().logverbose("Plugging VDI.")
        userdevice = g.createDisk(vdiuuid=vdiuuid)
        device = self.host.parseListForOtherParam("vbd-list",
                                                  "vm-uuid",
                                                   g.getUUID(),
                                                  "device",
                                                  "userdevice=%s" %
                                                  (userdevice))
        xenrt.TEC().logverbose("Formatting VDI within VM.")
        time.sleep(30)
        g.execguest("mkfs.ext2 /dev/%s" % (device))
        g.execguest("mount /dev/%s /mnt" % (device))

        xenrt.TEC().progress("Running %s iterations..." % (iterations))
        for i in range(iterations):
            xenrt.TEC().progress("Starting iteration %s..." % (i))
            g.execguest("echo %s > /mnt/counter" % (i))
            g.execguest("sync")
            snapuuid = self.host.snapshotVDI(vdiuuid)
            self.vdis.append(snapuuid)
            g.execguest("echo XXX > /mnt/counter")
            g.execguest("sync")
            data = self.check(snapuuid)
            if not data == i:
                raise xenrt.XRTFailure("Wrong count. Expected %s. Got %s." %
                                       (i, data))

        g.shutdown()
        xenrt.TEC().logverbose("Deleting original VDI.")
        self.host.destroyVDI(vdiuuid)
        self.vdis.remove(vdiuuid)

        xenrt.TEC().progress("Checking snapshots after deleting original.")
        for i in range(iterations):
            xenrt.TEC().logverbose("Checking snapshot %s." % (i))
            data = self.check(self.vdis[i])
            if not data == i:
                raise xenrt.XRTFailure("Snapshot %s doesn't have the "
                                       "correct count. (%s)" % (i, data))

class TC7800(_TC7800):
    """Multiple VDI snapshots of the same original."""

    ITERATIONS = 29

class TC27100(_TC7800):
    """Multiple VDI snapshots of the same original."""

    ITERATIONS = 29
    SRTYPE = "btrfs"


class TC7964(_TC7800):
    """Multiple LVM VDI snapshots of the same original."""

    SRTYPE = "lvm"
    ITERATIONS = 29

class TC7974(_TC7800):
    """Multiple NetApp VDI snapshots of the same original."""

    SRTYPE = "netapp"

class TC8073(_TC7800):
    """Multiple Equallogic VDI snapshots of the same original."""

    SRTYPE = "equal"
    VDICREATE_SMCONFIG = "snap-reserve-percentage=10000"
class TC9692(_TC7800):
    """Multiple CVSM VDI snapshots of the same original."""

    SRTYPE = "cslg"

    def __init__(self, tcid=None):
        _TC7800.__init__(self,tcid)
        self.size=1000*1024*1024

class TC9929(_TC7800):
    """Multiple CVSM-fc VDI snapshots of the same original."""

    SRTYPE = "cslg"


class TC15181(_TC7800):
    """Multiple CVSM-fc VDI snapshots of the same original. (SMI-S FC)"""

    SRTYPE = "cslg"
    ITERATIONS = 7

class TC7799(_VDISnapshotBase):
    """Snapshot of a snapshot."""

    def run(self, arglist):
        self.host = self.getDefaultHost()

        srs = self.host.getSRs(type=self.SRTYPE)
        if not srs:
            raise xenrt.XRTError("No %s SR found on host." % (self.SRTYPE))
        self.sr = srs[0]
        self.host.waitForCoalesce(self.sr)

        xenrt.TEC().logverbose("Creating a test VDI.")
        vdiuuid = self.host.createVDI(self.size,
                                      sruuid=self.sr,
                                      smconfig=self.VDICREATE_SMCONFIG)
        self.vdis.append(vdiuuid)
        self.vdiformat(vdiuuid)
        self.vdimodify(vdiuuid)

        vdihashoriginal = self.vdichecksum(vdiuuid)
        xenrt.TEC().logverbose("Creating VDI snapshot.")
        snapuuid = self.host.snapshotVDI(vdiuuid)
        self.vdis.append(snapuuid)

        xenrt.TEC().logverbose("Creating snapshot of snapshot.")
        snapsnapuuid = self.host.snapshotVDI(snapuuid)
        self.vdis.append(snapsnapuuid)

        xenrt.TEC().logverbose("Comparing hashes after snapshotting.")
        vdihashsnap = self.vdichecksum(vdiuuid)
        snaphash = self.vdichecksum(snapuuid)
        snapsnaphash = self.vdichecksum(snapsnapuuid)
        if not vdihashsnap == vdihashoriginal:
            raise xenrt.XRTFailure("Original VDI hash has changed.")
        if not snaphash == vdihashoriginal:
            raise xenrt.XRTFailure("Snapshot hash has changed.")
        if not snapsnaphash == vdihashoriginal:
            raise xenrt.XRTFailure("Snapshot of snapshot hash has changed.")

class TC7963(TC7799):
    """LVM Snapshot of a snapshot."""

    SRTYPE = "lvm"

class TC27099(TC7799):
    """SMAPIV3 Snapshot of a snapshot."""

    SRTYPE = "btrfs"


class TC7973(TC7799):
    """NetApp Snapshot of a snapshot."""

    SRTYPE = "netapp"

class TC8072(TC7799):
    """Equallogic Snapshot of a snapshot."""

    SRTYPE = "equal"
class TC9693(TC7799):
    """CVSM Snapshot of a snapshot."""

    SRTYPE = "cslg"

class TC9928(TC7799):
    """CVSM-fc Snapshot of a snapshot."""

    SRTYPE = "cslg"

class TC7798(_VDISnapshotBase):
    """Deleting the original shouldn't affect the snapshot VDI."""

    def run(self, arglist):
        self.host = self.getDefaultHost()

        srs = self.host.getSRs(type=self.SRTYPE)
        if not srs:
            raise xenrt.XRTError("No %s SR found on host." % (self.SRTYPE))
        self.sr = srs[0]
        self.host.waitForCoalesce(self.sr)

        xenrt.TEC().logverbose("Creating a test VDI.")
        vdiuuid = self.host.createVDI(self.size,
                                      sruuid=self.sr,
                                      smconfig=self.VDICREATE_SMCONFIG)
        self.vdis.append(vdiuuid)
        self.vdiformat(vdiuuid)
        self.vdimodify(vdiuuid)

        vdihashoriginal = self.vdichecksum(vdiuuid)
        xenrt.TEC().logverbose("Creating VDI snapshot.")
        snapuuid = self.host.snapshotVDI(vdiuuid)
        self.vdis.append(snapuuid)

        xenrt.TEC().logverbose("Deleting original.")
        self.host.destroyVDI(vdiuuid)

        xenrt.TEC().logverbose("Comparing hash after original deletion.")
        snaphashdel = self.vdichecksum(snapuuid)
        if not snaphashdel == vdihashoriginal:
            raise xenrt.XRTFailure("VDI hash is different after snapshot deletion.")

class TC7962(TC7798):
    """Deleting the original shouldn't affect the LVM snapshot VDI."""

    SRTYPE = "lvm"


class TC27098(TC7798):
    """Deleting the original shouldn't affect the SMAPIV3 snapshot VDI."""

    SRTYPE = "btrfs"


class TC7972(TC7798):
    """Deleting the original shouldn't affect the NetApp snapshot VDI."""

    SRTYPE = "netapp"

class TC8071(TC7798):
    """Deleting the original shouldn't affect the Equallogic snapshot VDI."""

    SRTYPE = "equal"
class TC9694(TC7798):
    """Deleting the original shouldn't affect the CVSM snapshot VDI."""

    SRTYPE = "cslg"

class TC9923(TC7798):
    """Deleting the original shouldn't affect the CVSM-fc snapshot VDI."""

    SRTYPE = "cslg"

class TC7797(_VDISnapshotBase):
    """Deleting a snapshot shouldn't affect the original VDI."""

    def run(self, arglist):
        self.host = self.getDefaultHost()

        srs = self.host.getSRs(type=self.SRTYPE)
        if not srs:
            raise xenrt.XRTError("No %s SR found on host." % (self.SRTYPE))
        self.sr = srs[0]
        self.host.waitForCoalesce(self.sr)

        xenrt.TEC().logverbose("Creating a test VDI.")
        vdiuuid = self.host.createVDI(self.size,
                                      sruuid=self.sr,
                                      smconfig=self.VDICREATE_SMCONFIG)
        self.vdis.append(vdiuuid)
        self.vdiformat(vdiuuid)
        self.vdimodify(vdiuuid)

        vdihashoriginal = self.vdichecksum(vdiuuid)
        xenrt.TEC().logverbose("Creating VDI snapshot.")
        snapuuid = self.host.snapshotVDI(vdiuuid)
        self.vdis.append(snapuuid)

        xenrt.TEC().logverbose("Deleting snapshot.")
        self.host.destroyVDI(snapuuid)

        xenrt.TEC().logverbose("Comparing hash after snapshot deletion.")
        vdihashdel = self.vdichecksum(vdiuuid)
        if not vdihashdel == vdihashoriginal:
            raise xenrt.XRTFailure("VDI hash is different after snapshot deletion.")

class TC7961(TC7797):
    """Deleting a LVM snapshot shouldn't affect the original VDI."""

    SRTYPE = "lvm"

class TC27097(TC7797):
    """Deleting a SMAPIV3 snapshot shouldn't affect the original VDI."""

    SRTYPE = "btrfs"


class TC7971(TC7797):
    """Deleting a NetApp snapshot shouldn't affect the original VDI."""

    SRTYPE = "netapp"

class TC8070(TC7797):
    """Deleting a Equallogic snapshot shouldn't affect the original VDI."""

    SRTYPE = "equal"
class TC9695(TC7797):
    """Deleting a CVSM snapshot shouldn't affect the original VDI."""

    SRTYPE = "cslg"

class TC9922(TC7797):
    """Deleting a CVSM-fc snapshot shouldn't affect the original VDI."""

    SRTYPE = "cslg"


class TC7796(_VDISnapshotBase):
    """Snapshot of a plugged VDI."""

    def run(self, arglist):
        self.host = self.getDefaultHost()
        srs = self.host.getSRs(type=self.SRTYPE)
        if not srs:
            raise xenrt.XRTError("No %s SR found on host." % (self.SRTYPE))
        self.sr = srs[0]
        g = self.createguest()

        xenrt.TEC().logverbose("Creating a test VDI.")
        vdiuuid = self.host.createVDI(self.size,
                                      sruuid=self.sr,
                                      smconfig=self.VDICREATE_SMCONFIG)
        self.vdis.append(vdiuuid)

        xenrt.TEC().logverbose("Plugging VDI.")
        userdevice = g.createDisk(vdiuuid=vdiuuid)
        device = self.host.parseListForOtherParam("vbd-list",
                                                  "vm-uuid",
                                                   g.getUUID(),
                                                  "device",
                                                  "userdevice=%s" %
                                                  (userdevice))
        xenrt.TEC().logverbose("Formatting VDI within VM.")
        time.sleep(30)
        g.execguest("mkfs.ext2 /dev/%s" % (device))

        xenrt.TEC().logverbose("Creating some random data on VDI.")
        g.execguest("mount /dev/%s /mnt" % (device))
        g.execguest("dd if=/dev/urandom of=/mnt/random bs=1M count=10")
        g.execguest("umount /mnt")

        xenrt.TEC().logverbose("Computing VDI hash from within VM.")
        vdihashvmoriginal = g.execguest("sha1sum /dev/%s" % (device)).split()[0]

        xenrt.TEC().logverbose("Creating VDI snapshot.")
        snapuuid = self.host.snapshotVDI(vdiuuid)
        self.vdis.append(snapuuid)

        g.unplugDisk(userdevice)

        xenrt.TEC().logverbose("Comparing hashes after snapshotting.")
        snaphash = self.vdichecksum(snapuuid)
        vdihashsnap = self.vdichecksum(vdiuuid)
        if not snaphash == vdihashvmoriginal:
            raise xenrt.XRTFailure("Hash of snapshot is different to original.")
        if not vdihashsnap == vdihashvmoriginal:
            raise xenrt.XRTFailure("Hash of VDI after snapshot is different to original.")

class TC7960(TC7796):
    """LVM snapshot of a plugged VDI."""

    SRTYPE = "lvm"

class TC27096(TC7796):
    """SMAPIV3 snapshot of a plugged VDI."""

    SRTYPE = "btrfs"


class TC7970(TC7796):
    """NetApp snapshot of a plugged VDI."""

    SRTYPE = "netapp"

class TC8069(TC7796):
    """Equallogic snapshot of a plugged VDI."""

    SRTYPE = "equal"
class TC9696(TC7796):
    """CVSM snapshot of a plugged VDI."""

    SRTYPE = "cslg"

class TC9925(TC7796):
    """CVSM-fc snapshot of a plugged VDI."""

    SRTYPE = "cslg"

class TC7795(_VDISnapshotBase):
    """VDI snapshot creation and operation."""

    def run(self, arglist):
        self.host = self.getDefaultHost()
        srs = self.host.getSRs(type=self.SRTYPE)
        if not srs:
            raise xenrt.XRTError("No %s SR found on host." % (self.SRTYPE))
        self.sr = srs[0]
        self.host.waitForCoalesce(self.sr)

        xenrt.TEC().logverbose("Creating a test VDI.")
        vdiuuid = self.host.createVDI(self.size,
                                      sruuid=self.sr,
                                      smconfig=self.VDICREATE_SMCONFIG)
        self.vdis.append(vdiuuid)
        self.vdiformat(vdiuuid)
        self.vdimodify(vdiuuid)

        vdihashoriginal = self.vdichecksum(vdiuuid)
        xenrt.TEC().logverbose("Creating VDI snapshot.")
        snapuuid = self.host.snapshotVDI(vdiuuid)
        self.vdis.append(snapuuid)

        xenrt.TEC().logverbose("Comparing hashes after snapshotting.")
        snaphash = self.vdichecksum(snapuuid)
        vdihashsnap = self.vdichecksum(vdiuuid)
        if not snaphash == vdihashoriginal:
            raise xenrt.XRTFailure("Hash of snapshot is different to original.")
        if not vdihashsnap == vdihashoriginal:
            raise xenrt.XRTFailure("Hash of VDI after snapshot is different to original.")

        xenrt.TEC().logverbose("Modifying original VDI.")
        self.vdimodify(vdiuuid)

        xenrt.TEC().logverbose("Comparing hashes after modification.")
        vdihashvdimod = self.vdichecksum(vdiuuid)
        snaphashvdimod = self.vdichecksum(snapuuid)
        if not snaphashvdimod == vdihashoriginal:
            raise xenrt.XRTFailure("Hash of snapshot is different to original.")
        if vdihashvdimod == vdihashoriginal:
            raise xenrt.XRTFailure("Hash of VDI after modifcation is the same as original.")

        xenrt.TEC().logverbose("Modifying snapshot.")
        self.vdimodify(snapuuid)

        xenrt.TEC().logverbose("Comparing hashes after modification.")
        vdihashsnapmod = self.vdichecksum(vdiuuid)
        snaphashsnapmod = self.vdichecksum(snapuuid)
        if snaphashsnapmod == snaphash:
            raise xenrt.XRTFailure("Hash of snapshot after modification is the same as original.")
        if not vdihashsnapmod == vdihashvdimod:
            raise xenrt.XRTFailure("Hash of VDI is different to original.")

class TC7959(TC7795):
    """LVM VDI snapshot creation and operation."""

    SRTYPE = "lvm"

class TC27095(TC7795):
    """SMAPIV3 VDI snapshot creation and operation."""

    SRTYPE = "btrfs"


class TC7969(TC7795):
    """NetApp VDI snapshot creation and operation."""

    SRTYPE = "netapp"

class TC8068(TC7795):
    """Equallogic VDI snapshot creation and operation."""

    SRTYPE = "equal"
class TC9697(TC7795):
    """CVSM VDI snapshot creation and operation."""

    SRTYPE = "cslg"

class TC9924(TC7795):
    """CVSM-fc VDI snapshot creation and operation."""

    SRTYPE = "cslg"

class TC7794(_VDISnapshotBase):
    """VDI Snapshot of an unplugged VDI."""

    def run(self, arglist):
        self.host = self.getDefaultHost()
        srs = self.host.getSRs(type=self.SRTYPE)
        if not srs:
            raise xenrt.XRTError("No %s SR found on host." % (self.SRTYPE))
        self.sr = srs[0]
        self.host.waitForCoalesce(self.sr)

        xenrt.TEC().logverbose("Creating a test VDI.")
        vdiuuid = self.host.createVDI(self.size,
                                      sruuid=self.sr,
                                      smconfig=self.VDICREATE_SMCONFIG)
        self.vdis.append(vdiuuid)
        self.vdiformat(vdiuuid)
        self.vdimodify(vdiuuid)

        vdihashoriginal = self.vdichecksum(vdiuuid)
        xenrt.TEC().logverbose("Creating VDI snapshot.")
        snapuuid = self.host.snapshotVDI(vdiuuid)
        self.vdis.append(snapuuid)

        xenrt.TEC().logverbose("Comparing hashes after snapshotting.")
        snaphash = self.vdichecksum(snapuuid)
        vdihashsnap = self.vdichecksum(vdiuuid)
        if not snaphash == vdihashoriginal:
            raise xenrt.XRTFailure("Hash of snapshot is different to original.")
        if not vdihashsnap == vdihashoriginal:
            raise xenrt.XRTFailure("Hash of VDI is different to original.")

class TC7958(TC7794):
    """LVM VDI Snapshot of an unplugged VDI."""

    SRTYPE = "lvm"

class TC27094(TC7794):
    """SMAPIV3 VDI Snapshot of an unplugged VDI."""

    SRTYPE = "btrfs"

class TC7968(TC7794):
    """NetApp VDI Snapshot of an unplugged VDI."""

    SRTYPE = "netapp"

class TC8067(TC7794):
    """Equallogic VDI Snapshot of an unplugged VDI."""

    SRTYPE = "equal"
class TC9698(TC7794):
    """CVSM VDI Snapshot of an unplugged VDI."""

    SRTYPE = "cslg"

class TC9921(TC7794):
    """CVSM-FC VDI Snapshot of an unplugged VDI."""

    SRTYPE = "cslg"

class TC7793(_VDISnapshotBase):
    """VDI Snapshot fails with a suitable error on LVM SRs."""

    SRTYPE = "lvm"

    def run(self, arglist):
        self.expected = "The SR backend does not support the operation"
        self.host = self.getDefaultHost()
        srs = self.host.getSRs(type=self.SRTYPE)
        if not srs:
            raise xenrt.XRTError("No %s SR found on host." % (self.SRTYPE))
        self.sr = srs[0]
        self.host.waitForCoalesce(self.sr)
        vdiuuid = self.host.createVDI(self.size, sruuid=self.sr)
        self.vdis.append(vdiuuid)
        failed = False
        try:
            self.host.snapshotVDI(vdiuuid)
        except Exception, e:
            failed = True
            if not re.search(self.expected, e.data):
                raise xenrt.XRTFailure("Snapshot failed with unexpected error message. (%s)" %
                                       (e.data))
        if not failed:
            raise xenrt.XRTFailure("VDI snapshot did not fail on LVM.")

class TC8079(_VDISnapshotBase):
    """Simulate a year of daily VM snapshot backups of a Linux VM on local VHD.
    """

    MINIMUM_PERIOD_MINS = 5

    def check(self, vdiuuid):
        check = """
mount /dev/${DEVICE} /mnt
cat /mnt/counter
umount /mnt
"""
        data = self.vdicommand(check, vdiuuid).splitlines()[-1].split()[0]
        return int(data)

    def run(self, arglist):
        self.host = self.getDefaultHost()
        iterations = 365

        srs = self.host.getSRs(type=self.SRTYPE)
        if not srs:
            raise xenrt.XRTError("No %s SR found on host." % (self.SRTYPE))
        self.sr = srs[0]
        self.host.waitForCoalesce(self.sr)

        g = self.createguest()

        xenrt.TEC().logverbose("Creating a test VDI.")
        vdiuuid = self.host.createVDI(self.size,
                                      sruuid=self.sr,
                                      smconfig=self.VDICREATE_SMCONFIG)
        self.vdis.append(vdiuuid)

        xenrt.TEC().logverbose("Plugging VDI.")
        userdevice = g.createDisk(vdiuuid=vdiuuid)
        device = self.host.parseListForOtherParam("vbd-list",
                                                  "vm-uuid",
                                                   g.getUUID(),
                                                  "device",
                                                  "userdevice=%s" %
                                                  (userdevice))
        xenrt.TEC().logverbose("Formatting VDI within VM.")
        time.sleep(30)
        g.execguest("mkfs.ext2 /dev/%s" % (device))
        g.execguest("mount /dev/%s /mnt" % (device))

        xenrt.TEC().progress("Running %s iterations..." % (iterations))
        for i in range(iterations):
            xenrt.TEC().progress("Starting iteration %s..." % (i))
            startiter = xenrt.timenow()

            g.execguest("echo %s > /mnt/counter" % (i))
            g.execguest("sync")

            uuid = g.snapshot()
            self.removeTemplateOnCleanup(g.host, uuid)
            snapvdiuuid = g.host.parseListForOtherParam("vbd-list",
                                                        "vm-uuid",
                                                        uuid,
                                                        "vdi-uuid",
                                                        "device=%s" % (device))

            g.execguest("echo XXX > /mnt/counter")
            g.execguest("sync")
            data = self.check(snapvdiuuid)
            if not data == i:
                raise xenrt.XRTFailure("Wrong count. Expected %s. Got %s." %
                                       (i, data))

            g.host.removeTemplate(uuid)
            foundvdi = False
            try:
                g.host.genParamGet("vdi", snapvdiuuid, "uuid")
                foundvdi = True
            except:
                pass
            if foundvdi:
                raise xenrt.XRTFailure("VDI belonging to the VM snapshot "
                                       "still exists after destroying the "
                                       "snapshot")

            # Make sure at least MINIMUM_PERIOD_MINS has elapsed before
            # starting another loop
            target = startiter + self.MINIMUM_PERIOD_MINS * 60
            now = xenrt.timenow()
            if now < target:
                t = target - now
                xenrt.TEC().logverbose("Sleeping for %d seconds before next "
                                       "iteration" % (t))
                time.sleep(t)


class TC9047(TC8079):
    """Simulate a year of daily VM snapshot backups of a Linux VM on local LVM.
    """

    SRTYPE = "lvm"


class _VMSnapshotBase(xenrt.TestCase):

    SRTYPE = None
    VMNAME = None

    # Consts: Lookup keys for args in arglist
    __GUEST_KEY = "guest"
    __XAPI_SR_KEY = "xapisrtype"

    def __parseArgs(self, arglist):
        """Parse args from arglist

        Expect these args to superseed any values sotred in the class variables

        """
        argDict = self.parseArgsKeyValue(arglist)

        if self.__GUEST_KEY in argDict:
            self.VMNAME = argDict[self.__GUEST_KEY]
        if self.__XAPI_SR_KEY in argDict:
            self.SRTYPE = argDict[self.__XAPI_SR_KEY]

    def prepare(self, arglist):

        self.__parseArgs(arglist)

        # If we have a VM already the use that, otherwise create one
        self.guest = self.getGuest(self.VMNAME)
        if not self.guest:
            xenrt.TEC().progress("Installing guest %s" % (self.VMNAME))
            host = self.getDefaultHost()
            if self.SRTYPE:
                srs = host.getSRs(type=self.SRTYPE)
                if not srs:
                    raise xenrt.XRTError("No %s SR found on host." %
                                         (self.SRTYPE))
                sruuid = srs[0]
            else:
                sruuid = None
            if re.search(r"[Ww]indows", self.VMNAME):
                self.guest = host.createGenericWindowsGuest(sr=sruuid)
            else:
                self.guest = host.createGenericLinuxGuest(sr=sruuid)
            self.uninstallOnCleanup(self.guest)
        else:
            # Check the guest is healthy and reboot if it is already up
            try:
                if self.guest.getState() == "DOWN":
                    self.guest.start()
                else:
                    # If it is suspended or anything else then that's bad
                    self.guest.reboot()
                self.guest.checkHealth()
            except xenrt.XRTFailure, e:
                raise xenrt.XRTError("Guest broken before we started: %s" %
                                     (str(e)))


class TC7849(_VMSnapshotBase):
    """VM snapshot creation of a simple halted VM"""

    VMNAME = "Windows-VM-with-drivers"

    def run(self, arglist):

        # Make sure the VM is not running.
        if self.guest.getState() == "UP":
            self.guest.shutdown()

        # Perform the snapshot.
        uuid = self.guest.snapshot()
        self.removeTemplateOnCleanup(self.guest.host, uuid)

class TC7850(_VMSnapshotBase):
    """VM snapshot creation of a simple running Windows VM"""

    VMNAME = "Windows-VM-with-drivers"

    def run(self, arglist):

        # Make sure the VM is running.
        if self.guest.getState() != "UP":
            self.guest.start()

        # Perform the snapshot.
        uuid = self.guest.snapshot()
        self.removeTemplateOnCleanup(self.guest.host, uuid)

        # Check the original VM.
        self.guest.checkHealth()

class TC8103(_VMSnapshotBase):
    """Quiesced VM snapshot creation of a simple running Windows VM"""

    VMNAME = "Windows-VM-with-drivers"

    def run(self, arglist):

        # Make sure the VM is running.
        if self.guest.getState() != "UP":
            self.guest.start()

        # Perform the snapshot.
        try:
            self.guest.disableVSS()
        except:
            pass
        self.guest.enableVSS()
        uuid = self.guest.snapshot(quiesced=True)
        self.removeTemplateOnCleanup(self.guest.host, uuid)

        # Check the original VM.
        self.guest.checkHealth()

class TC7865(_VMSnapshotBase):
    """VM snapshot creation of a simple suspended Windows VM"""

    VMNAME = "Windows-VM-with-drivers"

    def run(self, arglist):

        # Make sure the VM is running.
        if self.guest.getState() != "UP":
            self.guest.start()
        self.guest.suspend()

        # Get the list of suspend images.
        svdis1 = []
        svdis1.append(self.guest.paramGet("suspend-VDI-uuid"))

        # Perform the snapshot.
        uuid = self.guest.snapshot()
        self.removeTemplateOnCleanup(self.guest.host, uuid)

        # Get the list of suspend images.
        svdis2 = []
        svdis2.append(self.guest.paramGet("suspend-VDI-uuid"))

        # Check we haven't leaked any suspend images.
        expsvdi = len(svdis1)
        if self.guest.host.lookup("SNAPSHOT_OF_SUSPENDED_VM_IS_SUSPENDED",
                                  False,
                                  boolean=True):
            # This version creates suspended snapshots so we expect an
            # extra suspend VDI now.
            expsvdi = expsvdi + 1
        if len(svdis2) != expsvdi:
            raise xenrt.XRTFailure("An extra suspend VDI was found after "
                                   "snapshot of a suspended VM")

        # Check the original VM.
        self.guest.resume()
        self.guest.checkHealth()

    def postRun(self):
        if self.guest.getState() == "SUSPENDED":
            self.guest.resume()

class TC7866(_VMSnapshotBase):
    """VM snapshot creation of a simple running Linux VM"""

    VMNAME = "Linux-VM"

    def run(self, arglist):

        # Make sure the VM is running
        if self.guest.getState() != "UP":
            self.guest.start()

        # Perform the snapshot
        uuid = self.guest.snapshot()
        self.removeTemplateOnCleanup(self.guest.host, uuid)

        # Check the original VM
        self.guest.checkHealth()

class _VMSnapshotPerSR(_VMSnapshotBase):

    VMNAME = "Linux-VM"

    def run(self, arglist):

        # Make sure the VM is running
        if self.guest.getState() != "UP":
            self.guest.start()

        # Perform the snapshot
        uuid = self.guest.snapshot()
        self.removeTemplateOnCleanup(self.guest.host, uuid)

        # Check the original VM
        self.guest.checkHealth()

class TC7859(_VMSnapshotPerSR):
    """VM snapshot operation on local VHD"""

    SRTYPE = "ext"

class TC27103(_VMSnapshotPerSR):
    """VM snapshot operation on local VHD"""

    SRTYPE = "btrfs"

class TC7860(_VMSnapshotPerSR):
    """VM snapshot operation on local LVM"""

    SRTYPE = "lvm"

class TC7861(_VMSnapshotPerSR):
    """VM snapshot operation on iSCSI"""

    SRTYPE = "lvmoiscsi"

class TC7862(_VMSnapshotPerSR):
    """VM snapshot operation on fiber channel"""

    SRTYPE = "lvmohba"

class TC7863(_VMSnapshotPerSR):
    """VM snapshot operation on NFS"""

    SRTYPE = "nfs"

class TC20935(_VMSnapshotPerSR):
    """VM snapshot operation on filesr"""

    SRTYPE = "file"


class TC7864(_VMSnapshotPerSR):
    """VM snapshot operation on NetApp"""

    SRTYPE = "netapp"

class TC8613(_VMSnapshotPerSR):
    """VM snapshot operation on Equallogic"""

    SRTYPE = "equal"
class TC9699(_VMSnapshotPerSR):
    """VM snapshot operation on CVSM"""

    SRTYPE = "cslg"

class TC9937(_VMSnapshotPerSR):
    """VM snapshot operation on CVSM-fc"""

    SRTYPE = "cslg"

class _VMSnapshotPerOS(xenrt.TestCase):

    IN_GUEST_VSS = False
    VMNAME = None
    DISTRO = None
    SRTYPE = None

    def snapshotBoot(self):
        self.instance = self.guest.instantiateSnapshot(self.snapuuid)
        self.getLogsFrom(self.instance)
        self.instance.start()

    def prepare(self, arglist):
        self.snapuuid = None
        self.guest = None

        # If we have a VM already the use that, otherwise create one.
        if self.VMNAME:
            self.guest = self.getGuest(self.VMNAME)
            if self.guest:
                self.host = self.guest.host

        # See if we have cached a VM from an earlier test.
        vmnamebydistro = "snapshot-test-VM-%s" % (self.DISTRO)
        if self.DISTRO and not self.guest:
            self.guest = self.getGuest(vmnamebydistro)

        # Check the TC args to see if a guest name has been specified
        if not self.guest:
            for arg in arglist:
                l = string.split(arg, "=", 1)
                if l[0] == "guest":
                    self.guest = self.getGuest("%s" % l[1])

        if not self.guest:
            self.guest = self.createGuest(vmnamebydistro)
            xenrt.TEC().registry.guestPut(vmnamebydistro, self.guest)

        if self.guest:
            self.host = self.guest.host
        # Check the guest is healthy and reboot if it is already up
        try:
            if self.guest.getState() == "DOWN":
                self.guest.start()
            else:
                # If it is suspended or anything else then that's bad
                self.guest.reboot()
            self.guest.checkHealth()
        except xenrt.XRTFailure, e:
            raise xenrt.XRTError("Guest broken before we started: %s" %
                                 (str(e)))
        self.getLogsFrom(self.guest)
        if self.IN_GUEST_VSS:
            self.guest.installVSSTools()
            try:
                self.guest.disableVSS()
            except:
                pass
            self.guest.enableVSS()

        self.host.addExtraLogFile("/var/log/SMlog")
        # Capture information for use later.
        self.originalVMVDIs = self.host.minimalList("vbd-list",
                                                    "vdi-uuid",
                                                    "vm-uuid=%s type=Disk" %
                                                    (self.guest.getUUID()))

    def createGuest(self, name, distro=None):
        self.host = self.getDefaultHost()

        if not distro:
            distro = self.DISTRO

        if self.SRTYPE:
            srs = self.host.getSRs(type=self.SRTYPE)
            if not srs:
                raise xenrt.XRTError("No %s SR found on host." %
                                     (self.SRTYPE))
            sruuid = srs[0]
        else:
            sruuid = None

        # Install a VM
        if distro == "DEFAULT":
            guest = self.host.createGenericWindowsGuest(sr=sruuid)
            self.getLogsFrom(guest)
            guest.setName(name)
        else:
            guest = xenrt.lib.xenserver.guest.createVM(\
                    self.host,
                    name,
                    distro=distro,
                    sr=sruuid,
                    vifs=[("0",
                           self.host.getPrimaryBridge(),
                           xenrt.util.randomMAC(),
                           None)])
            self.getLogsFrom(guest)
            guest.installDrivers()

        # Make sure the VM is running
        if guest.getState() != "UP":
            guest.start()

        if self.IN_GUEST_VSS:
            guest.installVSSTools()
            try:
                guest.disableVSS()
            except:
                pass
            guest.enableVSS()

        # Capture information for use later
        self.originalVMVDIs = self.host.minimalList("vbd-list",
                                                    "vdi-uuid",
                                                    "vm-uuid=%s type=Disk" %
                                                    (guest.getUUID()))
        return guest

    def doShutdown(self):
        self.guest.shutdown()

    def run(self, arglist):

        # Perform the snapshot
        uuid = self.guest.snapshot()
        self.removeTemplateOnCleanup(self.guest.host, uuid)
        self.guest.checkHealth()

        # Shut down the original VM
        self.runSubcase("doShutdown", (), "Orig", "Shutdown")

    def postRun(self):
        try: self.guest.shutdown(again=True)
        except: pass
        cli = self.host.getCLIInstance()
        allsnaps = self.host.minimalList("vdi-list", "uuid",
                                         "is-a-snapshot=true")
        vbds = self.host.minimalList("vbd-list", "uuid",
                                     "vm-uuid=%s" % (self.guest.getUUID()))
        for vbd in vbds:
            vdi = self.host.genParamGet("vbd", vbd, "vdi-uuid")
            if vdi in allsnaps: cli.execute("vbd-destroy", "uuid=%s" % (vbd))
        try: self.instance.shutdown(again=True)
        except: pass
        try: self.instance.uninstall()
        except: pass

class _VMSnapshotPerOSQuiesced(_VMSnapshotPerOS):

    def quiescedSnapshot(self):
        self.snapuuid = self.guest.snapshot(quiesced=True)

    def run(self, arglist):

        try:
            self.guest.disableVSS()
        except:
            pass
        self.guest.enableVSS()
        # Perform the snapshot.
        if self.runSubcase("quiescedSnapshot", (), "Quiesced", "Snapshot") != \
                xenrt.RESULT_PASS:
            return
        # Try and boot an instance of the snapshot.
        if self.runSubcase("snapshotBoot", (), "Quiesced", "Boot") != \
                xenrt.RESULT_PASS:
            return
        self.guest.checkHealth()
        # Shut down the original VM
        self.runSubcase("doShutdown", (), "Orig", "Shutdown")

    def postRun(self):
        _VMSnapshotPerOS.postRun(self)
        try: self.host.removeTemplate(self.snapuuid)
        except: pass

class _VMSnapshotPerOSVSS(_VMSnapshotPerOS):

    IN_GUEST_VSS = True
    WORKLOADS = None
    ORIG_SHUTDOWN = True
    TEMPLATE = False
    SNAPSHOT_TYPE = None

    def __init__(self):
        _VMSnapshotPerOS.__init__(self)
        self.disks = ["C"]
        self.snapshotvdis = {}
        self.snapshot = None
        self.componentxml = None
        self.vssset = None
        self.flagfile = None
        self.importguest = None

    def prepare(self, arglist):
        _VMSnapshotPerOS.prepare(self, arglist)
        self.importguest = self.guest

    def vssListSets(self):
        """Return a list of VSS snapshot Set UUIDs as seen by the guest."""
        data = self.guest.xmlrpcExec("c:\\vshadow.exe -q", returndata=True)
        data = re.findall("Shadow copy Set: {(.*)}", data)
        return dict(zip(data, range(len(data)))).keys()

    def vssList(self, set=None):
        """Return a list of VSS snapshot UUIDs as seen by the guest."""
        if set:
            xenrt.TEC().logverbose("Finding all snapshot IDs in set {%s}." % (set))
            data = self.guest.xmlrpcExec("c:\\vshadow.exe -qx={%s}" % (set),
                                          returndata=True)
        else:
            xenrt.TEC().logverbose("Finding all snapshots.")
            data = self.guest.xmlrpcExec("c:\\vshadow.exe -q",
                                          returndata=True)
        snapshots = re.findall("SNAPSHOT ID = {(.*)}", data)
        xenrt.TEC().logverbose("Found %s." % (snapshots))
        return snapshots

    def vssMount(self, vssuuid, mountpoint=None):
        """Mount a VSS snapshot on mountpoint."""
        if mountpoint:
            if not self.guest.xmlrpcDirExists(self, mountpoint):
                self.guest.xmlrpcCreateDir(mountpoint)
        else:
            mountpoint = self.guest.xmlrpcTempDir()
        self.guest.xmlrpcExec("c:\\vshadow.exe -el={%s},%s" % (vssuuid, mountpoint))
        return mountpoint

    def vssParseComponent(self, component):
        componenttext = self.guest.xmlrpcReadFile(component)
        self.componentxml = str(componenttext.decode("utf-16")).strip('\0')
        xmltree = xml.dom.minidom.parseString(self.componentxml)

        snapshots = xmltree.getElementsByTagName("SNAPSHOT_DESCRIPTION")
        for snapshot in snapshots:
            descriptions = snapshot.getElementsByTagName("LUN_MAPPING")
            if not descriptions:
                raise xenrt.XRTFailure("No LUN_MAPPINGs found in VSS XML.")
            for d in descriptions:
                dstlun = d.getElementsByTagName("DESTINATION_LUN")[0]
                dstluninfo = dstlun.getElementsByTagName("LUN_INFORMATION")[0]
                snapvdi = str(dstluninfo.getAttribute("diskSignature"))
                self.snapshotvdis[snapvdi] = str(snapshot.getAttribute("snapshotId")).strip()
        sets = xmltree.getElementsByTagName("SNAPSHOT_SET_DESCRIPTION")
        if not sets:
            raise xenrt.XRTError("No SNAPSHOT_SET_DESCRIPTION found in VSS XML.")
        self.vssset = str(sets[0].getAttribute("snapshotSetId")).strip()

        componentname = "%s/vshadow-%s.xml" % (xenrt.TEC().getLogdir(), xenrt.timenow())
        file(componentname, "w").write(self.componentxml)

    def vssParseOutput(self, output):
        errortext = None
        try:
            data = self.guest.xmlrpcReadFile(output)
            match = re.search("Returned (?P<code>.*)", data)
            if match:
                xenrt.TEC().reason("Error running vshadow: %s" % (match.group("code").strip()))
            match = re.search("Error text: (?P<text>.*)", data)
            if match:
                xenrt.TEC().reason("Error running vshadow: %s" % (match.group("text").strip()))
                errortext = match.group("text").strip()
            logname = "%s/vshadow-%s.txt" % (xenrt.TEC().getLogdir(), xenrt.timenow())
            file(logname, "w").write(data)
        except Exception, e:
            xenrt.TEC().warning("Failed to retrieve vshadow trace. (%s)" % (str(e)))
        return errortext

    def vssSnapshot(self):
        localtemp = xenrt.TEC().tempDir()
        remotetemp = self.guest.xmlrpcTempDir()
        vshadowoutput = "%s\\vshadow.txt" % (remotetemp)
        componentxml = "%s\\snapshot.xml" % (remotetemp)
        disks = string.join([ x + ":" for x in self.disks ])

        command = ["c:\\vshadow.exe -tracing -p"]
        if not self.SNAPSHOT_TYPE == "non-transportable":
            command.append("-t=%s" % (componentxml))
            command.append(disks)
        command.append("> %s" % (vshadowoutput))

        for i in range(3):
            xenrt.TEC().logverbose("Attempt %s." % (i))
            text = None
            try:
                try:
                    self.guest.xmlrpcExec(string.join(command), timeout=1800)
                    break
                except:
                    # Check the guest is still OK
                    self.guest.checkHealth()
                    if i > 1:
                        text = self.vssParseOutput(vshadowoutput)
                        if text:
                            raise xenrt.XRTFailure("VSS snapshot failed: %s" %
                                                   (text))
                        else:
                            raise xenrt.XRTFailure("VSS snapshot failed")
                    xenrt.TEC().warning("VSS Snapshot attempt failed.")
                    time.sleep(300)
            finally:
                if not text:
                    self.vssParseOutput(vshadowoutput)

        if not self.SNAPSHOT_TYPE == "non-transportable":
            self.vssParseComponent(componentxml)
        self.guest.checkSnapshotVDIs(self.snapshotvdis.keys())
        self.snapshot = None
        for snapshotvdi in self.snapshotvdis:
            snapshotuuid = self.host.parseListForOtherParam("vbd-list",
                                                            "vdi-uuid",
                                                             snapshotvdi,
                                                            "vm-uuid")
            if self.TEMPLATE:
                if self.snapshot and self.snapshot != snapshotuuid:
                    raise xenrt.XRTFailure("Not all snapshot VDIs appear to belong "
                                           "to the same snapshot template.")
            self.snapshot = snapshotuuid
        if self.TEMPLATE:
            self.guest.checkSnapshot(self.snapshot)

    def vssImport(self):
        """Import a VSS snapshot into a Windows VM."""
        xenrt.TEC().logverbose(self.vssList())
        remotetemp = self.importguest.xmlrpcTempDir()
        filename = "%s\\import.xml" % (remotetemp)
        localtemp = xenrt.TEC().tempFile()
        file(localtemp, "w").write(self.componentxml.encode("utf-16"))
        self.importguest.xmlrpcSendFile(localtemp, filename)
        vshadowoutput = "%s\\vshadow.txt" % (remotetemp)

        try:
            self.importguest.xmlrpcExec("c:\\vshadow.exe -tracing -i=%s > %s" %
                                        (filename, vshadowoutput), timeout=1800)
        except Exception, e:
            self.vssParseOutput(vshadowoutput)
            xenrt.TEC().logverbose(self.vssList())
            raise xenrt.XRTFailure("Snapshot import failed! (%s)" % (str(e)))

        if not self.snapshotvdis:
            self.vssParseComponent(filename)

        # Check the snapshot VDIs now have VBDs in the VM.
        importguestvdis = self.importguest.getHost().minimalList("vbd-list",
                                                                 "vdi-uuid",
                                                                 "type=Disk "
                                                                 "vm-uuid=%s" %
                                                                 (self.importguest.getUUID()))
        for vdi in self.snapshotvdis:
            if not vdi in importguestvdis:
                raise xenrt.XRTFailure("A snapshot VDI doesn't have a "
                                       "VBD in the original VM.",
                                       "VDI %s" % (vdi))

    def vssDelete(self):
        """Delete a VSS snapshot. Leaves the template."""
        remotetemp = self.guest.xmlrpcTempDir()
        vshadowoutput = "%s\\vshadow.txt" % (remotetemp)
        snapshots = self.vssList(set=self.vssset)
        xenrt.TEC().logverbose("SNAPSHOT VDIs: %s" % (self.snapshotvdis))
        for vssuuid in snapshots:
            snapvdisbefore = self.snapshotvdis.keys()
            xenrt.TEC().logverbose("VSS snapshot VDI(s): %s" % (string.join(snapvdisbefore)))
            guestvdisbefore = self.host.minimalList("vbd-list",
                                                    "vdi-uuid",
                                                    "type=Disk "
                                                    "vm-uuid=%s" %
                                                    (self.guest.getUUID()))
            xenrt.TEC().logverbose("GUEST VDIs: %s" % (guestvdisbefore))
            # Delete the snapshot.
            start = xenrt.timenow()
            try:
                self.guest.xmlrpcExec("c:\\vshadow.exe -tracing -ds={%s} > %s" % (vssuuid, vshadowoutput),
                                       timeout=600)
            finally:
                self.vssParseOutput(vshadowoutput)
            end = xenrt.timenow()
            if end - start > 300:
                raise xenrt.XRTFailure("VSS delete took more than 5 minutes.")
            guestvdisafter = self.guest.getHost().minimalList("vbd-list",
                                                              "vdi-uuid",
                                                              "type=Disk "
                                                              "vm-uuid=%s" %
                                                             (self.guest.getUUID()))
            xenrt.TEC().logverbose("GUEST VDIs: %s" % (guestvdisafter))
            # Check original VDIs are still attached to the VM.
            for vdi in guestvdisbefore:
                if not vdi in guestvdisafter:
                    if not vdi in self.snapshotvdis:
                        raise xenrt.XRTFailure("A VDI of the original VM is no "
                                               "longer attached.",
                                               "VDI %s" % (vdi))
            # Check snapshot VDI is gone from the VM.
            for vdi in self.snapshotvdis:
                if self.snapshotvdis[vdi] == vssuuid:
                    if vdi in guestvdisafter:
                        raise xenrt.XRTFailure("A snapshot VDI doesn't seem to "
                                               "have been removed from the original VM.",
                                               "VDI %s" % (vdi))
        if self.TEMPLATE:
            # Check template is gone.
            if self.host.minimalList("template-list", args="uuid=%s" % (self.snapshot)):
                raise xenrt.XRTFailure("Snapshot template still exists.")

    def vssRead(self):
        # Get the snapshot set corresponding to the snapshot template.
        snapshots = self.vssList(set=self.vssset)
        for s in snapshots:
            mountpoint = self.vssMount(s)
            self.guest.xmlrpcExec("dir %s" % (mountpoint))
            data = self.guest.xmlrpcReadFile("%s\\%s" % (mountpoint, self.flagfile)).strip()
            if not data == self.flagfile:
                raise xenrt.XRTFailure("Incorrect data read back from snapshot.")

    def workloadsStart(self):
        self.workloads = self.guest.startWorkloads(self.WORKLOADS)

    def workloadsStop(self):
        self.guest.stopWorkloads(self.workloads)

    def createFlags(self):
        self.flagfile = "%s.flag" % (xenrt.timenow())
        for disk in self.disks:
            self.guest.xmlrpcCreateFile("%s:\\%s" % (disk, self.flagfile), self.flagfile)

    def run(self, arglist):
        # Create flag files.
        result = self.runSubcase("createFlags", (), "Flags", "Create")
        if not result == xenrt.RESULT_PASS: return result
        # Start VM workloads.
        if self.WORKLOADS:
            result = self.runSubcase("workloadsStart", (), "Workloads", "Start")
            if not result == xenrt.RESULT_PASS: return result
        # Perform the snapshot.
        result = self.runSubcase("vssSnapshot", (), "VSS", "Snapshot")
        if not result == xenrt.RESULT_PASS: return result
        # Attach the snapshot to the VM.
        result = self.runSubcase("vssImport", (), "VSS", "Import")
        if not result == xenrt.RESULT_PASS: return result
        # Read data from the snapshot within the VM.
        result = self.runSubcase("vssRead", (), "VSS", "ReadData")
        if not result == xenrt.RESULT_PASS: return result
        # Detach the snapshot from the VM.
        result = self.runSubcase("vssDelete", (), "VSS", "Delete")
        if not result == xenrt.RESULT_PASS: return result
        # Check the original VM is healthy.
        result = self.runSubcase("guest.checkHealth", (), "Check", "Original")
        if not result == xenrt.RESULT_PASS: return result
        # Stop VM workloads.
        if self.WORKLOADS:
            self.runSubcase("workloadsStop", (), "Workloads", "Stop")
        # Shut down the original VM.
        if self.ORIG_SHUTDOWN:
            self.runSubcase("doShutdown", (), "Orig", "Shutdown")

    def postRun(self):
        try: _VMSnapshotPerOS.postRun(self)
        except: pass
        if not self.SNAPSHOT_TYPE == "non-transportable":
            try: self.host.removeTemplate(self.snapshot)
            except: pass
            for v in self.snapshotvdis.keys():
                cli = self.host.getCLIInstance()
                try: cli.execute("vdi-destroy uuid=%s" % (v))
                except: pass

class TC9205(_VMSnapshotPerOSVSS):
    """Check importing too many snapshots fails correctly"""

    VMNAME = "Windows-VM-with-drivers"
    TEMPLATE = False

    DISKS = 15
    FAILAT = 13

    def prepare(self, arglist):
        _VMSnapshotPerOSVSS.prepare(self, arglist)
        self.disksToRemove = []
        size = 1024*1024*1024 # 1GB.

        d = self.guest.createDisk(size)
        self.disksToRemove = [d]
        disks = self.guest.xmlrpcListDisks()
        disks.remove(self.guest.xmlrpcGetRootDisk())
        for d in disks:
            letter = self.guest.xmlrpcPartition(d)
            self.guest.xmlrpcFormat(letter, timeout=1200)
        self.disks = [letter]

    def customImport(self, i):
        xenrt.TEC().logverbose("Import iteration %s." % (i))
        try:
            self.vssImport()
        except:
            if i >= self.FAILAT:
                xenrt.TEC().logverbose("Import failed as expected.")
                return
            else: raise xenrt.XRTFailure("Import failed on iteration %s." % (i))
        if i >= self.FAILAT:
            raise xenrt.XRTFailure("Import succeeded on iteration %s." % (i))
        xenrt.TEC().logverbose("Import succeeded.")


    def run(self, arglist):
        self.snaps = []
        # Take sufficient snapshots.
        for i in range(self.DISKS):
            self.snapshotvdis = {}
            self.snapshot = None
            xenrt.TEC().logverbose("Attempting snapshot %s." % (i))
            result = self.runSubcase("vssSnapshot", (), "VSS", "Snapshot-%s" % (i))
            if not result == xenrt.RESULT_PASS: return
            self.snaps.append((self.componentxml, self.snapshotvdis))
        for i in range(len(self.snaps)):
            self.componentxml, self.snapshotvdis = self.snaps[i]
            result = self.runSubcase("customImport", (i), "VSS", "Import-%s" % (i))
        #Check the version of host
        version = self.host.checkVersion(versionNumber=True)
        xenrt.TEC().logverbose("The version we got is %s" % version)
        #Get logs from zipped files
        if version >= "6.1.84":
            files = self.host.execdom0("ls /var/log/")
            totalFiles = files.split( )
            for file in totalFiles:
                if re.search("SMlog", file) and re.search(".gz", file):
                    self.host.execdom0("gunzip /var/log/%s" % file)
            self.host.execdom0("grep 'No free VBD devices found!' /var/log/SMlog*")
        else:
            self.host.execdom0("grep 'No free devs found!' /var/log/SMlog*")

    def postRun(self):
        _VMSnapshotPerOS.postRun(self)
        for i in range(len(self.snaps)):
            cxml, svdis = self.snaps[i]
            for vdi in svdis:
                cli = self.host.getCLIInstance()
                try: cli.execute("vdi-destroy uuid=%s" % (vdi))
                except: pass
        for d in self.disksToRemove:
            try: self.guest.removeDisk(d)
            except: pass

class TC9177(_VMSnapshotPerOSVSS, _VMSnapshotPerOSQuiesced):
    """Test transportable-snapshot-id parameter is valid"""

    VMNAME = "Windows-VM-with-drivers"

    def run(self, arglist):
        try: self.guest.disableVSS()
        except: pass
        self.guest.enableVSS()

        result = self.runSubcase("createFlags", (), "Flags", "Create")
        if not result == xenrt.RESULT_PASS: return result

        result = self.runSubcase("quiescedSnapshot", (), "Quiesced", "Snapshot")
        if not result == xenrt.RESULT_PASS: return

        self.componentxml = self.host.genParamGet("template",
                                                   self.snapuuid,
                                                  "transportable-snapshot-id").decode("hex").decode("utf-16").strip("\0")

        result = self.runSubcase("vssImport", (), "VSS", "Import")
        if not result == xenrt.RESULT_PASS: return

        result = self.runSubcase("vssRead", (), "VSS", "ReadData")
        if not result == xenrt.RESULT_PASS: return

        result = self.runSubcase("vssDelete", (), "VSS", "Delete")
        if not result == xenrt.RESULT_PASS: return

        result = self.runSubcase("guest.checkHealth", (), "Check", "Original")
        if not result == xenrt.RESULT_PASS: return

class TC12173(_VMSnapshotPerOSVSS):
    """Test for non-transportable VSS snapshot"""

    VMNAME = "Windows-VM-with-drivers"
    DISTRO = "ws08-x86"
    SNAPSHOT_TYPE = "non-transportable"

    def run(self, arglist):
        try: self.guest.disableVSS()
        except: pass
        self.guest.enableVSS()

        result = self.runSubcase("vssSnapshot", (), "VSS", "Snapshot")
        if not result == xenrt.RESULT_PASS: return

class TC8220(_VMSnapshotPerOSVSS):
    """Import a snapshot on another VM of the same Windows version."""

    # Distro to use for importing VM.
    DISTRO = "ws08-x86"
    VMNAME = "Windows-VM-with-drivers"

    def prepare(self, arglist):
        _VMSnapshotPerOSVSS.prepare(self, arglist)
        self.importguest = self.host.createGenericWindowsGuest(distro=self.DISTRO)
        self.importguest.installVSSTools()
        self.importguest.enableVSS()

    def vssImportFail(self):
        try:
            self.vssImport()
        except:
            pass
        else:
            raise xenrt.XRTFailure("Import succeeded.")

    def run(self, arglist):
        result = self.runSubcase("vssSnapshot", (), "VSS", "Snapshot")
        if not result == xenrt.RESULT_PASS: return

        # Try to import it.
        result = self.runSubcase("vssImportFail", (), "VSS", "ImportFail")
        if not result == xenrt.RESULT_PASS: return

        xenrt.TEC().logverbose("Enabling import.")
        self.importguest.paramSet("other-config:snapmanager", "true")

        # Try to import it.
        result = self.runSubcase("vssImport", (), "VSS", "Import")
        if not result == xenrt.RESULT_PASS: return

    def postRun(self):
        _VMSnapshotPerOSVSS.postRun(self)
        try: self.importguest.xmlrpcExec("echo y | c:\\vshadow.exe -da")
        except: pass
        try: self.importguest.shutdown()
        except: pass

class TC9136(TC8220):
    """Import a snapshot on another VM of the same Windows version."""

    TEMPLATE = True

class TC8221(TC8220):
    """Import a snapshot on another VM of a different Windows version."""

    DISTRO = "w2k3eesp2"

class TC0001(TC8221):

    TEMPLATE = False

class TC8218(_VMSnapshotPerOSVSS):
    """VSS snapshot with and without an attached ISO."""

    VMNAME = "Windows-VM-with-drivers"
    ORIG_SHUTDOWN = False

    def run(self, arglist):
        xenrt.TEC().logverbose("Testing VSS with an ISO.")
        self.guest.changeCD("xs-tools.iso")
        _VMSnapshotPerOSVSS.run(self, arglist)
        xenrt.TEC().logverbose("Testing VSS without an ISO.")
        self.snapshotvdis = {}
        self.host.getCLIInstance().execute("vm-cd-eject uuid=%s" % (self.guest.getUUID()))
        _VMSnapshotPerOSVSS.run(self, arglist)
        self.runSubcase("doShutdown", (), "Orig", "Shutdown")

class TC9134(TC8218):
    """VSS snapshot with and without an attached ISO."""

    TEMPLATE = True

class TC8219(_VMSnapshotPerOSVSS):
    """Repeated snapshot creation and deletion."""

    VMNAME = "Windows-VM-with-drivers"
    ORIG_SHUTDOWN = False

    def run(self, arglist):
        iterations = 10
        for i in range(iterations):
            xenrt.TEC().logverbose("Starting iteration %s..." % (i))
            _VMSnapshotPerOSVSS.run(self, arglist)
            self.snapshotvdis = {}
        self.runSubcase("doShutdown", (), "Orig", "Shutdown")

class TC9135(TC8219):
    """Repeated snapshot creation and deletion."""

    TEMPLATE = True

class _MultipleVBD(object):
    """VSS snapshot with multiple VBDs."""

    VMNAME = "Windows-VM-with-drivers"
    ORIG_SHUTDOWN = False

    def __init__(self):
        self.guest = None

    def run(self, arglist):
        self.disksToRemove = []
        size = 1024*1024*1024 # 1GB.

        # We only feel comfortable testing this many.
        allowed = 1
        xenrt.TEC().logverbose("Aiming for %s iterations." % (allowed))

        for i in range(allowed):
            xenrt.TEC().logverbose("Starting iteration %s..." % (i))
            d = self.guest.createDisk(size)
            self.disksToRemove.append(d)
            disks = self.guest.xmlrpcListDisks()
            xenrt.TEC().logverbose("Using %s extra disks." % (len(disks)))
            disks.remove(self.guest.xmlrpcGetRootDisk())
            self.disks = ["C"]
            for d in disks:
                letter = self.guest.xmlrpcPartition(d)
                self.guest.xmlrpcFormat(letter, timeout=1200)
                self.disks.append(letter)
            result = self.runSubcase("doTest", (), "Multi", i)
            if not result == xenrt.RESULT_PASS:
                xenrt.TEC().comment("Failed to snapshot %s disks." % (len(disks) + 1))
                break
        self.runSubcase("doShutdown", (), "Orig", "Shutdown")

    def doTest(self):
        pass

    def postRun(self):
        for d in self.disksToRemove:
            try: self.guest.removeDisk(d)
            except: pass

class TC8193(_MultipleVBD, _VMSnapshotPerOSVSS):
    """VSS snapshot with multiple VBDs."""

    def __init__(self):
        _MultipleVBD.__init__(self)
        _VMSnapshotPerOSVSS.__init__(self)

    def doTest(self):
        _VMSnapshotPerOSVSS.run(self, [])
        self.snapshotvdis = {}
        try: self.guest.start()
        except: pass

    def vssRead(self):
        if not self.vssset:
            raise xenrt.XRTFailure("Snapshot doesn't appear in a set. (%s)" % (self.snapuuid))
        snapshots = self.vssList(set=self.vssset)
        for s in snapshots:
            mountpoint = self.vssMount(s)
            self.guest.xmlrpcExec("dir %s" % (mountpoint))
            data = self.guest.xmlrpcReadFile("%s\\%s" %
                                             (mountpoint, self.flagfile))
            data = data.strip()
            if not data == self.flagfile:
                raise xenrt.XRTFailure("Incorrect data read back from snapshot.")

    def postRun(self):
        _VMSnapshotPerOSVSS.postRun(self)
        _MultipleVBD.postRun(self)

class TC9133(TC8193):
    """VSS snapshot with multiple VBDs."""

    TEMPLATE = True

class TC9070(TC8193):
    """VSS snapshot of indvidual disks"""

    TEMPLATE = False

    def doTest(self):
        saved = self.disks[:]
        try:
            for d in saved:
                if len(self.disks) == len(saved):
                    xenrt.TEC().logverbose("Skipping snapshot of all disks.")
                    self.disks.remove(d)
                    continue
                xenrt.TEC().logverbose("Trying to snapshot %s out of %s." % (self.disks, saved))
                _VMSnapshotPerOSVSS.run(self, [])
                if self.getFailures():
                    raise xenrt.XRTFailure("Snapshot test failed.")
                self.snapshotvdis = {}
                self.disks.remove(d)
        finally:
            self.disks = saved

class TC9058(_MultipleVBD, _VMSnapshotPerOSQuiesced):
    """Quiesced snapshot with multiple VBDs."""

    def __init__(self):
        _MultipleVBD.__init__(self)
        _VMSnapshotPerOSQuiesced.__init__(self)

    def doTest(self):
        for d in self.disks:
            self.guest.xmlrpcCreateFile("%s:\\xenrt.flag" % (d), d)
        _VMSnapshotPerOSQuiesced.run(self, [])
        if self.getFailures():
            raise xenrt.XRTFailure("Snapshot test failed.")
        try: self.guest.start()
        except: pass
        hidden = re.findall("Volume\s+(\d+).*Hidden",
                             self.instance.xmlrpcExec("echo list volume | diskpart",
                             returndata=True))
        for h in hidden:
            self.instance.xmlrpcAssign(h)
        xenrt.TEC().logverbose(self.instance.xmlrpcListDisks())
        self.instance.xmlrpcExec("echo list volume | diskpart", returndata=True)
        for d in self.disks:
            if not self.instance.xmlrpcReadFile("%s:\\xenrt.flag" % (d)):
                raise xenrt.XRTFailure("Error reading flag file on %s." % (d))
        try: self.instance.shutdown(again=True)
        except: pass
        try: self.instance.uninstall()
        except: pass

    def postRun(self):
        _VMSnapshotPerOSQuiesced.postRun(self)
        _MultipleVBD.postRun(self)

class TC8177(_VMSnapshotPerOSVSS):
    """VSS snapshot with a disk I/O workload running."""

    VMNAME = "Windows-VM-with-drivers"
    WORKLOADS = ["IOMeter", "SQLIOSim"]

class TC9132(TC8177):
    """VSS snapshot with a disk I/O workload running"""

    TEMPLATE = True

class _SpanningVolume(_VMSnapshotPerOS):
    """Base class for testing snapshots of Windows volumes that span multiple VBDs."""

    def __init__(self):
        _VMSnapshotPerOS.__init__(self)

    def prepare(self, arglist):
        self.disksToRemove = []
        self.disks = []
        self.letter = "E"
        self.disks.append(self.letter)
        size = 1024*1024*1024 # 1GB.
        number = 2

        _VMSnapshotPerOS.prepare(self, arglist)

        # Install KB932532.
        self.guest.installKB932532()

        # Create the disk devices.
        for i in range(number):
            d = self.guest.createDisk(size)
            self.disksToRemove.append(d)
        # Create and format a dynamic volume.
        disks = self.guest.xmlrpcListDisks()
        disks.remove(self.guest.xmlrpcGetRootDisk())
        for d in disks:
            time.sleep(30)
            try:
                online = "select disk %s\n" \
                         "online disk\n" \
                         "attributes disk clear readonly" % (d)
                self.guest.xmlrpcCreateFile("c:\\online.txt", online)
                self.guest.xmlrpcExec("diskpart /s c:\\online.txt")
            except: pass
            time.sleep(30)
            convert = "select disk %s\n" \
                      "convert dynamic" % (d)
            self.guest.xmlrpcCreateFile("c:\\convert.txt", convert)
            self.guest.xmlrpcExec("diskpart /s c:\\convert.txt")
        stripe = "create volume stripe disk=%s\n" \
                 "assign letter=%s" % (string.join(disks, ","), self.letter)
        self.guest.xmlrpcCreateFile("c:\\stripe.txt", stripe)
        self.guest.xmlrpcExec("diskpart /s c:\\stripe.txt")
        self.guest.xmlrpcFormat(self.letter, timeout=1200)

    def postRun(self):
        for d in self.disksToRemove:
            try:
                self.guest.removeDisk(d)
            except:
                pass

class TC8180(_VMSnapshotPerOSVSS, _SpanningVolume):
    """VSS snapshot of a Windows volume that spans multiple VBDs."""

    VMNAME = "Windows-VM-with-drivers"

    def prepare(self, arglist):
        _SpanningVolume.prepare(self, arglist)
        _VMSnapshotPerOSVSS.prepare(self, arglist)

    def postRun(self):
        _VMSnapshotPerOSVSS.postRun(self)
        _SpanningVolume.postRun(self)

class TC9137(TC8180):
    """VSS snapshot of a Windows volume that spans multiple VBDs."""

    TEMPLATE = False

class TC8282(_VMSnapshotPerOSQuiesced, _SpanningVolume):
    """Quiesced snapshot of a Windows volume that spans multiple VBDs."""

    VMNAME = "Windows-VM-with-drivers"

    def prepare(self, arglist):
        _SpanningVolume.prepare(self, arglist)

    def run(self, arglist):
        self.instance = None
        self.guest.xmlrpcCreateFile("%s:\\xenrt.flag" % (self.letter), self.letter)
        _VMSnapshotPerOSQuiesced.run(self, arglist)
        if self.instance:
            try:
                try:
                    hidden = re.findall("Volume\s+(\d+).*Hidden",
                                         self.instance.xmlrpcExec("echo list volume | diskpart",
                                         returndata=True))
                    for h in hidden:
                        self.instance.xmlrpcAssign(h)
                    if not self.instance.xmlrpcReadFile("%s:\\xenrt.flag" % (self.letter)) == self.letter:
                        raise xenrt.XRTFailure("Error reading flag file on %s." % (self.letter))
                except:
                    raise xenrt.XRTFailure("Error reading flag file on %s." % (self.letter))
            finally:
                try: self.instance.xmlrpcListDisks()
                except: pass

    def postRun(self):
        _VMSnapshotPerOSQuiesced.postRun(self)
        _SpanningVolume.postRun(self)

class TC8104(_VMSnapshotPerOSVSS):
    """Quiesced snapshot creation from within the guest using VSS tools."""

    VMNAME = "Windows-VM-with-drivers"

class TC9128(TC8104):
    """Quiesced snapshot creation from within the guest using VSS tools."""

    TEMPLATE = True

class TC8117(_VMSnapshotPerOSQuiesced):
    """Quiesced VM snapshot operation on NFS SR."""

    SRTYPE = "nfs"
    DISTRO = "DEFAULT"

class TC20939(_VMSnapshotPerOSQuiesced):
    """Quiesced VM snapshot operation on File SR."""

    SRTYPE = "file"
    DISTRO = "DEFAULT"


class TC8118(_VMSnapshotPerOSQuiesced):
    """Quiesced VM snapshot operation on NetApp SR."""

    SRTYPE = "netapp"
    DISTRO = "DEFAULT"

class TC8119(_VMSnapshotPerOSQuiesced):
    """Quiesced VM snapshot operation on Equallogic SR."""

    SRTYPE = "equal"
    DISTRO = "DEFAULT"
class TC9701(_VMSnapshotPerOSQuiesced):
    """Quiesced VM snapshot operation on CVSM SR."""

    SRTYPE = "cslg"
    DISTRO = "DEFAULT"
class TC9939(_VMSnapshotPerOSQuiesced):
    """Quiesced VM snapshot operation on CVSM-fc SR."""

    SRTYPE = "cslg"
    DISTRO = "DEFAULT"


class TC8617(_VMSnapshotPerOSQuiesced):
    """Quiesced VM snapshot operation on VHD SR."""

    SRTYPE = "ext"
    DISTRO = "DEFAULT"

class TC8618(_VMSnapshotPerOSQuiesced):
    """Quiesced VM snapshot operation on LVM SR."""

    SRTYPE = "lvm"
    DISTRO = "DEFAULT"

class TC8619(_VMSnapshotPerOSQuiesced):
    """Quiesced VM snapshot operation on iSCSI SR."""

    SRTYPE = "lvmoiscsi"
    DISTRO = "DEFAULT"

class TC8114(_VMSnapshotPerOSVSS):
    """Quiesced snapshot creation using VSS tools on NFS SR."""

    SRTYPE = "nfs"
    DISTRO = "DEFAULT"

class TC20938(_VMSnapshotPerOSVSS):
    """Quiesced snapshot creation using VSS tools on file SR."""

    SRTYPE = "file"
    DISTRO = "DEFAULT"


class TC0008(TC8114):

    TEMPLATE = False

class TC8115(_VMSnapshotPerOSVSS):
    """Quiesced snapshot creation using VSS tools on NetApp SR."""

    SRTYPE = "netapp"
    DISTRO = "DEFAULT"

class TC0018(TC8115):

    TEMPLATE = False

class TC8116(_VMSnapshotPerOSVSS):
    """Quiesced snapshot creation using VSS tools on Equallogic SR."""

    SRTYPE = "equal"
    DISTRO = "DEFAULT"
class TC9700(_VMSnapshotPerOSVSS):
    """Quiesced snapshot creation using VSS tools on CVSM SR."""

    SRTYPE = "cslg"
    DISTRO = "DEFAULT"

class TC9938(_VMSnapshotPerOSVSS):
    """Quiesced snapshot creation using VSS tools on CVSM-fc SR."""

    SRTYPE = "cslg"
    DISTRO = "DEFAULT"

class TC0009(TC8116):

    TEMPLATE = False

class TC8614(_VMSnapshotPerOSVSS):
    """Quiesced snapshot creation using VSS tools on VHD SR."""

    SRTYPE = "ext"
    DISTRO = "DEFAULT"

class TC0010(TC8614):

    TEMPLATE = False

class TC8615(_VMSnapshotPerOSVSS):
    """Quiesced snapshot creation using VSS tools on LVM SR."""

    SRTYPE = "lvm"
    DISTRO = "DEFAULT"

class TC0011(TC8615):

    TEMPLATE = False

class TC8616(_VMSnapshotPerOSVSS):
    """Quiesced snapshot creation using VSS tools on iSCSI SR."""

    SRTYPE = "lvmoiscsi"
    DISTRO = "DEFAULT"

class TC0012(TC8616):

    TEMPLATE = False

class TC8056(_VMSnapshotPerOSQuiesced):
    """Quiesced VM snapshot operation with Windows Server 2003 EE SP2"""

    DISTRO = "w2k3eesp2"

class TC8057(_VMSnapshotPerOSQuiesced):
    """Quiesced VM snapshot operation with Windows Server 2003 EE SP2 x64"""

    DISTRO = "w2k3eesp2-x64"

class TC8058(_VMSnapshotPerOSQuiesced):
    """Quiesced VM snapshot operation with Windows Server 2008"""

    DISTRO = "ws08-x86"

class TC8059(_VMSnapshotPerOSQuiesced):
    """Quiesced VM snapshot operation with Windows Server 2008 x64"""

    DISTRO = "ws08-x64"

class TC9703(_VMSnapshotPerOSQuiesced):
    """Quiesced VM snapshot operation with Windows Server 2008 SP2"""

    DISTRO = "ws08sp2-x86"

class TC9704(_VMSnapshotPerOSQuiesced):
    """Quiesced VM snapshot operation with Windows Server 2008 SP2 x64"""

    DISTRO = "ws08sp2-x64"

class TC9702(_VMSnapshotPerOSQuiesced):
    """Quiesced VM snapshot operation with Windows Server 2008 R2 x64"""

    DISTRO = "ws08r2-x64"

class TC20689(_VMSnapshotPerOSQuiesced):
    """Quiesced VM snapshot operation with Windows Server 2008 R2 SP1 x64"""

    DISTRO = "ws08r2sp1-x64"

class TC20553(_VMSnapshotPerOSQuiesced):
    """Quiesced VM snapshot operation with Windows 2012 R2 x64"""

    DISTRO = "ws12r2-x64"

class TC18771(_VMSnapshotPerOSQuiesced):
    """Quiesced VM snapshot operation with Windows Server 2008 R2 x64"""

    DISTRO = "ws12-x64"

class TC7851(_VMSnapshotPerOS):
    """VM snapshot operation with Windows Server 2003 EE SP2"""

    DISTRO = "w2k3eesp2"

class TC7852(_VMSnapshotPerOS):
    """VM snapshot operation with Windows Server 2003 EE SP2 x64"""

    DISTRO = "w2k3eesp2-x64"

class TC7853(_VMSnapshotPerOS):
    """VM snapshot operation with Windows Server 2008"""

    DISTRO = "ws08-x86"

class TC7854(_VMSnapshotPerOS):
    """VM snapshot operation with Windows Server 2008 x64"""

    DISTRO = "ws08-x64"

class TC9705(_VMSnapshotPerOS):
    """VM snapshot operation with Windows Server 2008 SP2"""

    DISTRO = "ws08sp2-x86"

class TC9706(_VMSnapshotPerOS):
    """VM snapshot operation with Windows Server 2008 SP2 x64"""

    DISTRO = "ws08sp2-x64"

class TC9707(_VMSnapshotPerOS):
    """VM snapshot operation with Windows Server 2008 R2 x64"""

    DISTRO = "ws08r2-x64"

class TC12559(_VMSnapshotPerOS):
    """VM snapshot operation with Windows Server 2008 R2 SP1 x64"""

    DISTRO = "ws08r2sp1-x64"

class TC7855(_VMSnapshotPerOS):
    """VM snapshot operation with Windows Vista EE SP1"""

    DISTRO = "vistaeesp1"

class TC7856(_VMSnapshotPerOS):
    """VM snapshot operation with Windows Vista EE SP1 x64"""

    DISTRO = "vistaeesp1-x64"

class TC9708(_VMSnapshotPerOS):
    """VM snapshot operation with Windows Vista EE SP2"""

    DISTRO = "vistaeesp2"

class TC9709(_VMSnapshotPerOS):
    """VM snapshot operation with Windows Vista EE SP2 x64"""

    DISTRO = "vistaeesp2-x64"

class TC7857(_VMSnapshotPerOS):
    """VM snapshot operation with Windows XP SP3"""

    DISTRO = "winxpsp3"

class TC7858(_VMSnapshotPerOS):
    """VM snapshot operation with Windows 2000 SP4"""

    DISTRO = "w2kassp4"

class TC9745(_VMSnapshotPerOS):
    """VM snapshot operation with Windows 7"""

    DISTRO = "win7-x86"

class TC9746(_VMSnapshotPerOS):
    """VM snapshot operation with Windows 7 x64"""

    DISTRO = "win7-x64"

class TC20699(_VMSnapshotPerOS):
    """VM snapshot operation with Windows 8 x86"""

    DISTRO = "win8-x86"

class TC20550(_VMSnapshotPerOS):
    """VM snapshot operation with Windows 81 x64"""

    DISTRO = "win81-x64"

class TC20554(_VMSnapshotPerOS):
    """VM snapshot operation with Windows 81 x86"""

    DISTRO = "win81-x86"

class TC26421(_VMSnapshotPerOS):
    """VM snapshot operation with Windows 10 x86"""

    DISTRO = "win10-x86"

class TC26422(_VMSnapshotPerOS):
    """VM snapshot operation with Windows 10 x64"""

    DISTRO = "win10-x64"

class TC20555(_VMSnapshotPerOS):
    """VM snapshot operation with Windows 12 R2 x64"""

    DISTRO = "ws12r2-x64"

class TC20556(_VMSnapshotPerOS):
    """VM snapshot operation with Windows 12 Core R2 x64"""

    DISTRO = "ws12r2core-x64"





class TC12560(_VMSnapshotPerOS):
    """VM snapshot operation with Windows 7 SP1"""

    DISTRO = "win7sp1-x86"

class TC12561(_VMSnapshotPerOS):
    """VM snapshot operation with Windows 7 SP1 x64"""

    DISTRO = "win7sp1-x64"

class TC18770(_VMSnapshotPerOS):
    """VM snapshot operation with Windows Server 2012 x64"""

    DISTRO = "ws12-x64"

class TC8105(_VMSnapshotPerOSVSS):
    """Quiesced snapshot operation on Windows Server 2003 EE SP2 using VSS tools"""

    DISTRO = "w2k3eesp2"

class TC9129(TC8105):

    TEMPLATE = True

class TC8106(_VMSnapshotPerOSVSS):
    """Quiesced snapshot operation on Windows Server 2003 EE SP2 x64 using VSS tools"""

    DISTRO = "w2k3eesp2-x64"

class TC9130(TC8106):

    TEMPLATE = True

class TC8107(_VMSnapshotPerOSVSS):
    """Quiesced snapshot operation on Windows Vista EE SP1 using VSS tools"""

    DISTRO = "vistaeesp1"

class TC20696(_VMSnapshotPerOSVSS):
    """Quiesced snapshot operation on Windows Vista EE SP2 using VSS tools"""

    DISTRO = "vistaeesp2"

class TC0014(TC8107):

    TEMPLATE = False

class TC8108(_VMSnapshotPerOSVSS):
    """Quiesced snapshot operation on Windows Vista EE SP1 x64 using VSS tools"""

    DISTRO = "vistaeesp1-x64"

class TC0015(TC8108):

    TEMPLATE = False

class TC8109(_VMSnapshotPerOSVSS):
    """Quiesced snapshot operation on Windows Server 2008 using VSS tools"""

    DISTRO = "ws08-x86"

class TC9710(_VMSnapshotPerOSVSS):
    """Quiesced snapshot operation on Windows Server 2008 SP2 using VSS tools"""

    DISTRO = "ws08sp2-x86"
    TEMPLATE = True

class TC0016(TC8109):

    TEMPLATE = False

class TC8110(_VMSnapshotPerOSVSS):
    """Quiesced snapshot operation on Windows Server 2008 x64 using VSS tools"""

    DISTRO = "ws08-x64"

class TC9131(TC8110):
    """Quiesced snapshot operation on Windows Server 2008 x64 using VSS tools"""

    TEMPLATE = True

class TC9711(_VMSnapshotPerOSVSS):
    """Quiesced snapshot operation on Windows Server 2008 SP2 x64 using VSS tools"""
    DISTRO = "ws08sp2-x64"
    TEMPLATE = True

class TC20549(_VMSnapshotPerOSVSS):
    """Quiesced snapshot operation on Windows 2012 R2 x64 using VSS tools"""
    DISTRO = "ws12r2-x64"
    TEMPLATE = True

class TC20557(_VMSnapshotPerOSVSS):
    """Quiesced snapshot operation on Windows 2012 R2 Core x64 using VSS tools"""
    DISTRO = "ws12r2core-x64"
    TEMPLATE = True


class TC9987(_VMSnapshotPerOSVSS):
    """Quiesced snapshot operation on Windows Server 2008 R2 x64 using VSS tools"""
    DISTRO = "ws08r2-x64"

class TC20688(_VMSnapshotPerOSVSS):
    """Quiesced snapshot operation on Windows Server 2008 R2 SP1 x64 using VSS tools"""
    DISTRO = "ws08r2sp1-x64"

class TC20698(_VMSnapshotPerOSVSS):
    """Quiesced snapshot operation on Windows XP SP3 using VSS tools"""
    DISTRO = "winxpsp3"

class TC20694(_VMSnapshotPerOSVSS):
    """Quiesced snapshot operation on Windows 7 SP1 x86 using VSS tools"""
    DISTRO = "win7sp1-x86"

class TC20701(_VMSnapshotPerOSVSS):
    """Quiesced snapshot operation on Windows 8 x86 using VSS tools"""
    DISTRO = "win8-x86"

class TC9712(TC9987):
    """Quiesced snapshot operation on Windows Server 2008 R2 x64 using VSS tools"""

    TEMPLATE = True

class TC18772(_VMSnapshotPerOSVSS):
    """Quiesced snapshot operation on Windows Server 2008 SP2 x64 using VSS tools"""
    DISTRO = "ws12-x64"
    TEMPLATE = True

class TC8190(xenrt.TestCase):
    """Testcase to check disabled means disabled for VSS."""

    DISTRO = "ws08-x86"

    def run(self, arglist):
        self.host = self.getDefaultHost()
        self.guest = xenrt.lib.xenserver.guest.createVM(\
                        self.host,
                        xenrt.randomGuestName(),
                        distro=self.DISTRO,
                        vifs=[("0",
                                self.host.getPrimaryBridge(),
                                xenrt.util.randomMAC(),
                                None)])
        self.getLogsFrom(self.guest)
        self.guest.installDrivers()
        self.guest.installVSSTools()

        data = self.guest.xmlrpcExec("c:\\vshadow.exe -p -t=test.xml c:",
                                      returndata=True, returnerror=False)
        if not re.search("VOLUME_NOT_SUPPORTED", data):
            xenrt.TEC().logverbose(data)
            raise xenrt.XRTFailure("VShadow succedeed with VSS provider "
                                   "not yet enabled.")
        self.guest.enableVSS()
        self.guest.disableVSS()

        data = self.guest.xmlrpcExec("c:\\vshadow.exe -p -t=test.xml c:",
                                      returndata=True, returnerror=False)

        if not re.search("VOLUME_NOT_SUPPORTED", data):
            xenrt.TEC().logverbose(data)
            raise xenrt.XRTFailure("VShadow succedeed with VSS provider "
                                   "turned off.")

    def postRun(self):
        try:
            self.guest.shutdown()
        except:
            pass
        try:
            self.guest.uninstall()
        except:
            pass

class TC11740(_VMSnapshotBase):
    """Verify the allowvssprovider flags are honoured"""

    VMNAME = "Windows-VM-with-drivers"

    def run(self, arglist):

        # Make sure the VM is running.
        if self.guest.getState() != "UP":
            self.guest.start()

        # Set the xenstore key to true
        self.guest.host.xenstoreWrite("/local/domain/%s/vm-data/allowvssprovider" % (self.guest.getDomid()), "true")
        xenrt.TEC().logverbose("Attempting snapshot (expected to work)...")
        self.trySnapshot()
        self.guest.checkHealth()

        # Set the xenstore key to false
        self.guest.host.xenstoreWrite("/local/domain/%s/vm-data/allowvssprovider" % (self.guest.getDomid()), "false")
        xenrt.TEC().logverbose("Attempting snapshot (expected to fail due to xenstore key)...")
        try:
            self.trySnapshot()
        except:
            pass
        else:
            raise xenrt.XRTFailure("Able to take snapshot while xenstore vm-data/allowvssprovider was set to false")

        self.guest.checkHealth()
        self.guest.host.xenstoreRm("/local/domain/%s/vm-data/allowvssprovider" % (self.guest.getDomid()))

    def postRun(self):
        try:
            self.guest.paramRemove("xenstore-data","vm-data/allowvssprovider")
        except:
            pass
        try:
            self.guest.reboot()
        except:
            pass

    def trySnapshot(self):
        # Perform the snapshot.
        try:
            self.guest.disableVSS()
        except:
            pass
        self.guest.enableVSS()
        uuid = self.guest.snapshot(quiesced=True)
        self.removeTemplateOnCleanup(self.guest.host, uuid)

class TC20976(xenrt.TestCase):
    """HFX820 Test to check cached file of base VDI image is deleted by cleanup.py -c"""
    VDISIZE="1GiB"

    def prepare(self,arglist=[]):

        self.host=self.getDefaultHost()
        g=self.host.listGuests(running=True)
        self.guest=self.host.getGuest(g[0])
        self.guest.shutdown()
        self.host.disable()
        self.host.enableCaching()
        self.host.enable()
        self.nfsuuid=self.host.getSRs(type="nfs")[0]
        self.vdiuuid=self.host.createVDI(self.VDISIZE,sruuid=self.nfsuuid,name="vdi1")
        self.host.genParamSet("vdi",self.vdiuuid,"allow-caching","true")
        self.host.genParamSet("vdi",self.vdiuuid,"on-boot","persist")


    def run(self, arglist=[]):

        step("Create vhd cache files")
        self.guest.start()
        vdiSnapshot=self.host.snapshotVDI(self.vdiuuid)
        args = ["device=%s" % "autodetect",
                "vdi-uuid=%s"  % vdiSnapshot,
                "vm-uuid=%s" % self.guest.uuid,
                ]

        cli = self.host.getCLIInstance()
        vbd = cli.execute("vbd-create", string.join(args), strip=True)

        xenrt.TEC().logverbose("Plugging VBD on %s" % self.guest.getName())
        cli.execute("vbd-plug", "uuid=%s" % vbd)
        self.cachefiles = self.host.execdom0("ls /var/run/sr-mount/%s/*.vhdcache" % \
                                           (self.host.getLocalSR())).strip().splitlines()
        if len(self.cachefiles)!=2:
            raise xenrt.XRTFailure(".vhdcache files were not generated")
        for i in self.cachefiles:
            xenrt.TEC().logverbose(i)

        step("Unplugging and deleting snapshot VDI")
        cli.execute("vbd-unplug", "uuid=%s" % vbd)
        cli.execute("vdi-destroy","uuid=%s" % vdiSnapshot)
        self.cachefiles = self.host.execdom0("ls /var/run/sr-mount/%s/*.vhdcache" % \
                                           (self.host.getLocalSR())).strip().splitlines()
        if len(self.cachefiles) != 1 :
            raise xenrt.XRTFailure("vdi-destroy didn't delete cached file")

        step("Listing cached file left in local storage")
        xenrt.TEC().logverbose(self.cachefiles[0])

        step("Updating time of host")
        self.host.execdom0("/etc/init.d/ntpd stop")
        self.host.execdom0("echo \" The current time\" `date` ")
        #Updating system time by 2 hours
        self.host.execdom0("echo \" The current time\" `date -s \"2 hours\"` ")

        step("Delete vhd cache file")
        #Deleting cached base image file that was there for more than 2 hours
        #Executing cleanup script
        self.host.execdom0("/opt/xensource/sm/cleanup.py -u %s -c 2" %(self.host.getLocalSR()))
        baseCacheFile=self.host.execdom0("test -e /var/run/sr-mount/%s/*.vhdcache", retval="code")
        if not baseCacheFile:
            raise xenrt.XRTFailure("Cached base VDI image was not deleted")

class TC17898(xenrt.TestCase):
    """ Snapshot load distribution across pool slaves """

    SPARSE_DD = "/opt/xensource/libexec/sparse_dd"

    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        self.master = self.pool.master
        cli = self.master.getCLIInstance()

        if len(self.pool.getSlaves()) != 2:
            raise xenrt.XRTFailure("This testcase requires a pool of 3 hosts.")

        sr1 = self.master.minimalList("sr-list name-label=nfs1")[0]

        self.vdiuuid = self.master.createVDI(xenrt.GIGA, sruuid=sr1, name="XenRT-VDI")

        vmuuid = self.master.getMyDomain0UUID()
        self.vbduuid = cli.execute("vbd-create vm-uuid=%s vdi-uuid=%s device=autodetect" % (vmuuid, self.vdiuuid), strip=True)
        cli.execute("vbd-plug uuid=%s" % (self.vbduuid))

        time.sleep(10)

        # expects: xvda
        dev = self.master.minimalList("vbd-list uuid=%s params=device" % (self.vbduuid))[0]

        # write 0's to inflate VDI until EOF raises exception when EOF is reached
        # and because execdom0 does not allow one to handle the exception and still get the output from it
        # we need therefore to OR it
        self.master.execdom0("dd if=/dev/zero of=/dev/%s bs=4096 || true" % (dev))

        self.master.execdom0("sync")

        cli.execute("vbd-unplug uuid=%s" % (self.vbduuid))
        cli.execute("vbd-destroy uuid=%s" % (self.vbduuid))

    def run(self, arglist=None):
        cli = self.master.getCLIInstance()

        sr2 = self.master.minimalList("sr-list name-label=nfs2")[0]

        self.master.execdom0("xe vdi-copy uuid=%s sr-uuid=%s" % (self.vdiuuid, sr2))
        self.master.execdom0("xe vdi-copy uuid=%s sr-uuid=%s" % (self.vdiuuid, sr2))

        if self.sparseRunningCount(self.master):
            raise xenrt.XRTFailure("sparse_dd found running on master.")

        count = 0
        for host in self.pool.getSlaves():
            count += self.sparseRunningCount(host)

        if count != 2:
            raise xenrt.XRTFailure(
                "vdi-copy not distributed across slaves (%d copies)" % count)


    def sparseRunningCount(self, host):
        try:
            out = host.execdom0("pgrep -fl sparse_dd").split('\n')
        except:
            xenrt.TEC().logverbose("sparseRunningCount() exception caught:\n%s" % traceback.format_exc())
            return 0

        xenrt.TEC().logverbose("the output is:\n%s" % (out))
        return len(filter(lambda l: self.SPARSE_DD not in l, out))

class TC18784(xenrt.TestCase):
    """Verify the delay when deleting snapshot on an SR that is more than a Terabytes  (HFX-664,HFX-663)"""

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid=tcid)
        self.VMNAME = "ws08sp2-x86"
        self.TIMEOUT = 10
        self.DISTRO = "ws08sp2-x86"

    def prepare(self, arglist):
        #Refer CA-112240 to understand the implementation
        vsizeGb = 1024 # VDI size in Gb

        self.host = self.getDefaultHost()

        self.sruuid = self.host.minimalList("sr-list", args="name-label=Local\ storage")
        self.guest = self.host.createGenericWindowsGuest(name=self.VMNAME, sr=self.sruuid[0], distro=self.DISTRO)

        before = self.guest.xmlrpcListDisks()

        xenrt.TEC().logverbose("Creating a VDI of size - %d Gb -" % (vsizeGb))
        self.vdiuuid = self.host.createVDI(vsizeGb*xenrt.GIGA, sruuid=self.sruuid[0], name="XenRT-VDI")
        vmuuid = self.guest.getUUID()

        xenrt.TEC().logverbose("Plugging VDI.")
        self.vbduuid = self.host.execdom0("xe vbd-create vm-uuid=%s vdi-uuid=%s device=autodetect" % (vmuuid, self.vdiuuid)).strip()
        self.host.execdom0("xe vbd-plug uuid=%s" % (self.vbduuid))

        after = self.guest.xmlrpcListDisks()
        xenrt.TEC().logverbose("Disks after attaching test VDI: %s" % (after))
        for x in before:
            after.remove(x)
        disk = after[0]
        xenrt.TEC().logverbose("Partitioning disk %s." % (disk))
        self.letter = self.guest.xmlrpcPartition(disk)
        xenrt.TEC().logverbose("Formatting disk %s." % (self.letter))
        self.guest.xmlrpcFormat(self.letter,timeout=7200, quick=True)

        #xenrt.sleep(10)
        self.uninstallOnCleanup(self.guest)

    def run(self, arglist=None):

        #Create a dummy file, before and after the VDI Snapshot
        self.guest.xmlrpcCreateEmptyFile("%s:\\%s" % (self.letter,"1.tst"),25600) #25GB file
        snapshotuuid = self.host.snapshotVDI(self.vdiuuid)
        self.guest.xmlrpcCreateEmptyFile("%s:\\%s" % (self.letter,"2.tst"),25600) #25GB file

        # Delete the VDI snapshot
        self.host.destroyVDI(snapshotuuid)

        #xenrt.sleep(10)
        # Wait for any GC to complete
        start = xenrt.timenow()
        self.host.waitForCoalesce(self.sruuid[0], self.TIMEOUT * 600)
        end = xenrt.timenow()
        xenrt.TEC().logverbose("Coalesce took approximately %u seconds" % (int(end-start)))

        tcol = 550 # Expected wait time for coalesce (Without the HFX, this number is expected to cross 1000)
        if ((int(end-start))>tcol):
            raise xenrt.XRTError("Coalesce took approximately %u seconds; expected is %u seconds " %(int(end-start),tcol))

    def postRun(self):

        if self.guest != None:
            if self.guest.getState() == "UP":
                self.guest.shutdown()

        if self.vdiuuid:
            self.host.destroyVDI(self.vdiuuid)

class TC21699(_VMSnapshotBase):
    """Verify no exceptions thrown when exporting metadata of shapshot."""

    SRTYPE = "ext"
    VMNAME = "Linux-VM"

    def run(self, arglist):
        # Default VDI sizes to 100Mb.
        self.size = 100*1024*1024
        self.vdis = []

        self.host = self.getDefaultHost()
        srs = self.host.getSRs(type=self.SRTYPE)
        if not srs:
            raise xenrt.XRTError("No %s SR found on host." % (self.SRTYPE))
        self.sr = srs[0]

        xenrt.TEC().logverbose("Creating a test VDI.")
        vdiuuid = self.host.createVDI(self.size,
                                      sruuid=self.sr)
        self.vdis.append(vdiuuid)

        xenrt.TEC().logverbose("Plugging VDI.")
        userdevice = self.guest.createDisk(vdiuuid=vdiuuid)
        device = self.host.parseListForOtherParam("vbd-list",
                                                  "vm-uuid",
                                                   self.guest.getUUID(),
                                                  "device",
                                                  "userdevice=%s" %
                                                  (userdevice))
        xenrt.TEC().logverbose("Formatting VDI within VM.")
        time.sleep(30)
        self.guest.execguest("mkfs.ext2 /dev/%s" % (device))

        self.host.execdom0("xe vm-snapshot uuid=%s new-name-label=newsnapshot" % self.guest.getUUID())
        self.host.execdom0("xe-backup-metadata -c -u %s" % self.sr)

        errorString = "Exporting metadata of a snapshot is not allowed"

        grepCode= self.host.execdom0("grep '%s' /var/log/xensource.log" %
                                        errorString, retval="code", level=xenrt.RC_OK)

        # 0 = Errors found.
        if grepCode == 0:
            raise xenrt.XRTFailure("Error relating to failed exporting of metadata found in /var/log/xensource.log")
        else:
            xenrt.TEC().logverbose("There were no problems found in the log file.")


class SnapshotVDILink(xenrt.TestCase):
    """ Snapshot links are properly reflected in "snapshot-of" params of snapshot VDIs before and after SXM """
    
    VDISIZE = 5 * xenrt.GIGA

    def __init__(self, tcid=None):
        
        xenrt.TestCase.__init__(self, tcid=tcid)

        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.snapshotVdiList = {}
        self.vmVdiList = {}
        self.snapshot = None
    
    def prepare(self, arglist):

        # Create a Guest
        self.guest = self.host0.createGenericLinuxGuest()


    def verifyLinksOnSnapshot(self):

        # Get the base VDI of the VM
        vmVdiUuid = self.host0.minimalList("vbd-list", "vdi-uuid", "type=Disk vm-uuid=%s " % (self.guest.getUUID()))[0]
        log ("Base VDI uuid is %s" % vmVdiUuid)
        self.vmVdiList["0"] = vmVdiUuid
        
        # Add 3 extra VDIs
        sruuid = self.host0.getLocalSR()
        for i in range (1,4):
            extraVdi = self.host0.createVDI(self.VDISIZE, sruuid, name="%s" % i)
            self.guest.createDisk(sruuid=sruuid, vdiuuid=extraVdi)
            log ("Extra VDI attached to VM before snapshot is %s" % extraVdi)
            self.vmVdiList["%s" % i] = extraVdi
        
        # Take VM snapshot
        self.snapshot = self.guest.snapshot()
        
        # Get the snapshot VDIs
        snapshotList = self.host0.minimalList("vbd-list", "vdi-uuid", "type=Disk vm-uuid=%s " % self.snapshot)
        for vdi in snapshotList:
            snapshotVdiName = self.host0.minimalList("vdi-param-get uuid=%s param-name=name-label" % vdi)[0]
            log ("Snapshot VDI we got is %s" % vdi)
            self.snapshotVdiList[snapshotVdiName] = vdi
    
        # Check the snapshot-of links
        for key,value in self.snapshotVdiList.items():
            snapshotLink = self.host0.minimalList("vdi-param-get uuid=%s param-name=snapshot-of" % value)[0]
            log ("After Snapshot: snapshot-of link we got for snapshot VDI %s is %s" % (value, snapshotLink))
            if snapshotLink != self.vmVdiList[key]:
                raise xenrt.XRTFailure("snapshot-of link broken, For snapshot VDI %s link is %s" % (value, snapshotLink))
    
    
    def verifyLinksOnRevert(self, ):
        
        snapshotRevertVdiList = {}
        
        # Revert to snapshot
        self.guest.revert(self.snapshot)
        
        # Get the VM VDIs after snapshot revert
        vmRevertedVdiList = self.host0.minimalList("vbd-list", "vdi-uuid", "type=Disk vm-uuid=%s " % self.guest.getUUID())
        for vdi in vmRevertedVdiList:
            newVdiName = self.host0.minimalList("vdi-param-get uuid=%s param-name=name-label" % vdi)[0]
            log ("After snapshot revert new VDI we got is %s" % vdi)
            snapshotRevertVdiList[newVdiName] = vdi
        
        # Check the snapshot-of links after snapshot revert
        for key,value in self.snapshotVdiList.items():
            snapshotLink = self.host0.minimalList("vdi-param-get uuid=%s param-name=snapshot-of" % value)[0]
            log ("After Snapshot Revert: snapshot-of link we got for snapshot VDI %s is %s" % (snapshotLink,value))
            if snapshotLink != snapshotRevertVdiList[key]:
                raise xenrt.XRTFailure("snapshot-of link broken, For snapshot VDI %s link is %s" % (value, snapshotLink))


        # Start the guest
        self.guest.start()
        
    def verifyLinksOnMigration(self, ):

        sxmVmVdiList = {}
        sxmSnapshotVdiList = {}
        
        # Migrate the VM
        self.guest.migrateVM(remote_host=self.host1)
        
        # Get the new base VDIs of the Guest after SXM
        vdiList = self.host1.minimalList("vbd-list", "vdi-uuid", "type=Disk vm-uuid=%s " % self.guest.getUUID())
        for vdi in vdiList:
            newVdiName = self.host1.minimalList("vdi-param-get uuid=%s param-name=name-label" % vdi)[0]
            log ("After SXM new VDI we got is %s" % vdi)
            sxmVmVdiList[newVdiName] = vdi
    
        # Get the new snapshot VDIs of the Guest after SXM
        vdiList = self.host1.minimalList("vbd-list", "vdi-uuid", "type=Disk vm-uuid=%s " % self.snapshot)
        for vdi in vdiList:
            newVdiName = self.host1.minimalList("vdi-param-get uuid=%s param-name=name-label" % vdi)[0]
            log ("After SXM new snapshot VDI we got is %s" % vdi)
            sxmSnapshotVdiList[newVdiName] = vdi

        # Verify snapshot link after SXM
        for key,value in sxmSnapshotVdiList.items():
            snapshotLink = self.host1.minimalList("vdi-param-get uuid=%s param-name=snapshot-of" % value)[0]
            log ("After SXM: snapshot-of link we got for snapshot VDI %s link is %s" % (value,snapshotLink))
            if snapshotLink != sxmVmVdiList[key]:
                raise xenrt.XRTFailure("snapshot-of link broken, For snapshot VDI %s link is %s" % (value, snapshotLink))
    
    def run(self, arglist):
        self.verifyLinksOnSnapshot()
        self.verifyLinksOnRevert()
        self.verifyLinksOnMigration()
    

class SnapshotLinkOnVdiDelete(SnapshotVDILink):
    """ Snapshot links are properly reflected in "snapshot-of" params of snapshot VDIs before and after SXM 
        On deleting a VM VDI before revert """
    
    DELETEVDI = "2"
    
    def deleteVmDisk(self):
        vbduuid = self.host0.genParamGet("vdi", self.vmVdiList[self.DELETEVDI], "vbd-uuids")
        cli = self.host0.getCLIInstance()
        cli.execute("vbd-unplug", "uuid=%s" % (vbduuid))
        cli.execute("vbd-destroy", "uuid=%s" % (vbduuid))
        cli.execute("vdi-destroy", "uuid=%s" % (self.vmVdiList[self.DELETEVDI]))
    

    def run(self, arglist):
        
        self.verifyLinksOnSnapshot()
        self.deleteVmDisk()
        self.verifyLinksOnRevert()
        self.verifyLinksOnMigration()
    

class RetainingVDIOnSnapshotRevert(xenrt.TestCase):
    """ Additional VDI attached to snapshot VM should not get deleted on snapshot revert """

    VDISIZE = 5 * xenrt.GIGA

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid=tcid)

    def prepare(self, arglist):

        # Create a Guest
        self.host = self.getHost("RESOURCE_HOST_0")
        self.guest = self.host.createGenericLinuxGuest()


    def run(self, arglist):

        sruuid = self.host.getLocalSR()

        # Create a new disk and attach it to VM before snapshot
        extraVdiUuid1 = self.host.createVDI(self.VDISIZE, sruuid)
        vbdUuid = self.guest.createDisk(sruuid=sruuid, vdiuuid=extraVdiUuid1, returnVBD=True)
        log ("Extra VDI uuid added before snapshot is %s" % extraVdiUuid1)

        # Detach this VDI
        self.host.getCLIInstance().execute("vbd-unplug", "uuid=%s" % vbdUuid)
        self.host.getCLIInstance().execute("vbd-destroy", "uuid=%s" % vbdUuid)

        # Create a snapshot of the VM
        snapuuid = self.guest.snapshot()

        # Create a new disk and attach it to VM after snasphot
        extraVdiUuid2 = self.host.createVDI(self.VDISIZE, sruuid)
        self.guest.createDisk(sruuid=sruuid, vdiuuid=extraVdiUuid1)
        log ("Extra VDI uuid added after snapshot is %s" % extraVdiUuid2)

        # Revert the snapshot
        self.guest.revert(snapuuid)

        # Check the extra vdi attached in not deleted
        vdis = self.host.minimalList("vdi-list", "uuid", "sr-uuid=%s " % sruuid)

        log ("VDIs on Local SR after snapshot revert are %s" % vdis)
        if not (extraVdiUuid2 in vdis):
            raise xenrt.XRTFailure("VDI %s attached to VM after snapshot got deleted after snapshot revert" % extraVdiUuid2)

        if not (extraVdiUuid1 in vdis):
            raise xenrt.XRTFailure("VDI %s attached to VM before snapshot got deleted after snapshot revert" % extraVdiUuid1)


class SnapshotVDILinkOnUpgrade(xenrt.TestCase):
    """ On Upgrade Snapshot Links should not be broken """

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid=tcid)

    def prepare(self, arglist):

        # Create a Guest
        self.pool = self.getDefaultPool()
        self.master = self.pool.master
        self.slave = self.pool.slaves.values()[0]
        self.sruuid = self.slave.getLocalSR()
        self.guest = self.slave.createGenericLinuxGuest(sr=self.sruuid)


    def run(self, arglist):

        # Get the base VDI of the Guest
        vmVdiUuid = self.slave.minimalList("vbd-list", "vdi-uuid", "type=Disk vm-uuid=%s " % (self.guest.getUUID()))[0]

        # Take a snapshot of VM
        snapshotUuid = self.guest.snapshot()

        # Get the attached VDI of snapshot
        snapshotVdiUuid = self.slave.minimalList("vbd-list", "vdi-uuid", "type=Disk vm-uuid=%s " % snapshotUuid)[0]

        # Get the snapshot-of link of snapshot VDI
        snapshotLinkVdi = self.slave.minimalList("vdi-param-get uuid=%s param-name=snapshot-of" % snapshotVdiUuid)[0]
        log ("Snapshot-of link we got for snapshot vdi %s is %s" % (snapshotVdiUuid, snapshotLinkVdi))
        if vmVdiUuid != snapshotLinkVdi:
            raise xenrt.XRTFailure("snapshot link is broken for snapshot vdi %s" % snapshotVdiUuid)

        # Apply the Cream Hotfix
        self.master.applyRequiredPatches()
        self.slave.applyRequiredPatches()

        # Get the base VDI of the Guest after Upgrade
        upgradedVmVdiUuid = self.slave.minimalList("vbd-list", "vdi-uuid", "type=Disk vm-uuid=%s " % (self.guest.getUUID()))[0]

        # Get the attached VDI of snapshot
        upgradedSnapshotVdiUuid = self.slave.minimalList("vbd-list", "vdi-uuid", "type=Disk vm-uuid=%s " % snapshotUuid)[0]

        # Get the snapshot-of link of snapshot VDI
        upgradedSnapshotLinkVdi = self.slave.minimalList("vdi-param-get uuid=%s param-name=snapshot-of" % upgradedSnapshotVdiUuid)[0]
        log ("Snapshot-of link we got for snapshot vdi %s is %s" % (upgradedSnapshotVdiUuid, upgradedSnapshotLinkVdi))
        if upgradedVmVdiUuid != upgradedSnapshotLinkVdi:
            raise xenrt.XRTFailure("snapshot link is broken for snapshot vdi %s" % upgradedSnapshotVdiUuid)

        # Revert to snapshot
        self.guest.revert(snapshotUuid)

        # Start the guest
        self.guest.start()

        # Get the new base VDI of the Guest
        vmRevertedVdiUuid = self.slave.minimalList("vbd-list", "vdi-uuid", "type=Disk vm-uuid=%s " % (self.guest.getUUID()))[0]

        # Get the new snapshot-of link of snapshot VDI
        snapshotLinkVdiAfterRevert = self.slave.minimalList("vdi-param-get uuid=%s param-name=snapshot-of" % upgradedSnapshotVdiUuid)[0]
        log ("Snapshot-of link we got for snapshot vdi %s is %s" % (upgradedSnapshotVdiUuid, snapshotLinkVdiAfterRevert))
        if vmRevertedVdiUuid != snapshotLinkVdiAfterRevert:
            raise xenrt.XRTFailure("snapshot link is broken for snapshot vdi %s" % upgradedSnapshotVdiUuid)

        # Migrate the VM
        self.guest.migrateVM(remote_host=self.master)

        # Get the new base VDI of the Guest
        vmRevertedVdiUuid = self.master.minimalList("vbd-list", "vdi-uuid", "type=Disk vm-uuid=%s " % (self.guest.getUUID()))[0]

        # Get the attached VDI of snapshot
        snapshotVdiUuid = self.master.minimalList("vbd-list", "vdi-uuid", "type=Disk vm-uuid=%s " % snapshotUuid)[0]

        # Get the snapshot-of link of snapshot VDI
        snapshotLinkVdi = self.master.minimalList("vdi-param-get uuid=%s param-name=snapshot-of" % snapshotVdiUuid)[0]
        log ("Snapshot-of link we got for snapshot vdi %s is %s" % (snapshotVdiUuid, snapshotLinkVdi))
        if vmRevertedVdiUuid != snapshotLinkVdi:
            raise xenrt.XRTFailure("snapshot link is broken for snapshot vdi %s after SXM" % snapshotVdiUuid)
