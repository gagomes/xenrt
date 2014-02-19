import xenrt
import libperf
import string
import time

class TCdd(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCdd")

        self.blocksizes = [1024, 4096, 1024*1024, 4*1024*1024]
        self.dditers = 20
        self.userawvdi = False
        self.ddsize = 500*1024*1024 # 500 MiB
        self.vdisize = "1GiB"

    def parseArgs(self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs(self, arglist)

        # Parse arguments relating to this test
        self.dditers = libperf.getArgument(arglist, "dditers", int, 20)
        self.userawvdi = libperf.getArgument(arglist, "userawvdi", bool, False)

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)

    def parsedd(self, s):
        # Extract the MB/s bit, which appears on the last non-empty line
        return s.strip().split("\n")[-1].split(", ")[-1]

    def measureThroughput(self, execcmd, path, stem):
        xenrt.TEC().progress("Measuring throughput to %s (logfile stem %s)" % (path, stem))

        # Check the path exists (return value == 1 implies it doesn't exist)
        if self.host.execdom0("[ -e %s ]" % path, retval="code") == 1:
            xenrt.TEC().logverbose("path %s does not exist -- skipping" % path)
        else:
            for bs in self.blocksizes:
                count = self.ddsize / bs

                for i in range(0, self.dditers):
                    throughput = self.parsedd(execcmd("dd if=/dev/zero of=%s oflag=direct bs=%Ld count=%Ld" % (path, bs, count)))
                    line = "%Ld     %s" % (bs, throughput)
                    self.log("%s-write" % stem, line)

                for i in range(0, self.dditers):
                    throughput = self.parsedd(execcmd("dd if=%s of=/dev/null iflag=direct bs=%Ld count=%Ld" % (path, bs, count)))
                    line = "%Ld     %s" % (bs, throughput)
                    self.log("%s-read" % stem, line)

    def run(self, arglist=None):
        # Use the local SR
        sruuid = self.host.execdom0("xe sr-list name-label=Local\ storage --minimal").strip()

        # Create a VDI
        if self.userawvdi:
            smconfig = "sm-config:type=raw"
        else:
            smconfig = ""
        vdiuuid = self.host.execdom0("xe vdi-create sr-uuid=%s virtual-size=%s type=user %s name-label=vdi" % (sruuid, self.vdisize, smconfig)).strip()

        # Block-attach it in dom0
        dom0uuid = self.host.execdom0("xe vm-list is-control-domain=true --minimal").strip()
        vbduuid = self.host.execdom0("xe vbd-create vm-uuid=%s vdi-uuid=%s device=autodetect" % (dom0uuid, vdiuuid)).strip()
        self.host.execdom0("xe vbd-plug uuid=%s" % vbduuid)
        dev = self.host.execdom0("xe vbd-param-get uuid=%s param-name=device" % vbduuid).strip()
        devpath = "/dev/%s" % dev

        # Fill it with zeros to fully inflate the VHD
        self.host.execdom0("dd if=/dev/zero of=%s bs=4096 || true" % devpath)

        # Create a filesystem on /dev/xvda
        self.host.execdom0("mkfs.ext3 %s" % devpath)

        # Measure sequential read & write throughput in dom0 to file on FS on /dev/xvda
        mntpath = "/mnt/vdi"
        self.host.execdom0("mkdir -p %s" % mntpath)
        self.host.execdom0("mount %s %s" % (devpath, mntpath))
        tmpfile = "%s/file" % mntpath
        self.host.execdom0("touch %s" % tmpfile)
        self.measureThroughput(self.host.execdom0, tmpfile, "dom0-file-in-ext3-on-xvda")
        self.host.execdom0("umount %s" % devpath)

        # Measure sequential read & write throughput in dom0 to /dev/xvda (block-attached to dom0)
        self.measureThroughput(self.host.execdom0, devpath, "dom0-xvda")

        # Measure sequential read & write throughput in dom0 to /dev/sm/backend/<uuid>/<uuid>
        # (does not exist prior to Cowley)
        path = "/dev/sm/backend/%s/%s" % (sruuid, vdiuuid)
        self.measureThroughput(self.host.execdom0, path, "dom0-sm-backend")

        # Measure sequential read & write throughput in dom0 to /dev/blktap/blktapN
        vgname = "VG_XenStorage-%s" % sruuid
        lvname = "VHD-%s" % vdiuuid
        lvpath = "/dev/%s/%s" % (vgname, lvname)
        
        #tapdiskminor = int(self.host.execdom0("tap-ctl list | grep %s | awk '{print $2}' | awk -F= '{print $2}'" % lvpath).strip())
        #tapdiskpath = "/dev/blktap/blktap%d" % tapdiskminor
        # Don't measure /dev/blktap/blktapN because it is busy
        #self.measureThroughput(self.host.execdom0, tapdiskpath, "dom0-blktapN")

        # Measure sequential read & write throughput in dom0 to /dev/VG_XenStorage-<uuid>/<uuid> (if local LVM)
        self.measureThroughput(self.host.execdom0, lvpath, "dom0-lv")

        # Measure sequential read & write throughput in dom0 to /dev/sda3 -- this will destroy the SR
        path = self.host.execdom0("pvs | grep %s | awk '{print $1}'" % vgname).strip()
        self.measureThroughput(self.host.execdom0, path, "dom0-sda3")

    def postRun(self):
        self.finishUp()

