import xenrt, libperf, string

class TCVDISnapshotRead(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCVDISnapshotRead")

        # Depth to test
        self.chaindepth = 512

        # Block size
        self.bs = 512

        # Number of samples to collect for each test
        self.samples = 100

        # Whether to pin vcpus to dom0 or not
        self.pinvcpus = 0

    def parseArgs(self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs(self, arglist)

        # Parse specific arguments
        self.pinvcpus = libperf.getArgument(arglist, "pinvcpus", int, 0)

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)

    def run(self, arglist=None):
        # Send yngwie to host
        sftp = self.host.sftpClient()
        sftp.copyTo("/home/xenrtd/felipef/yngwie", "/root/yngwie")

        # Pin VCPUS to physical CPUs
        if (self.pinvcpus == 1):
            self.host.execdom0("/usr/sbin/xl vcpu-pin 0 0 0 ; /usr/sbin/xl vcpu-pin 0 1 1 ; /usr/sbin/xl vcpu-pin 0 2 2 ; /usr/sbin/xl vcpu-pin 0 3 3")
            self.log("vcpu-list.log", "pinning: \n%s\n" % (self.host.execdom0("/usr/sbin/xl vcpu-list")))

        # Hack SM to support deeper snapshot trees
        self.host.execdom0("sed -i 's/MAX_CHAIN_SIZE = 30/MAX_CHAIN_SIZE = %d/g' /opt/xensource/sm/vhdutil.py" % (self.chaindepth + 1))

        # Prepare ramdisk md array
        dom0uuid = self.host.execdom0("xe vm-list is-control-domain=true --minimal").strip()
        self.host.execdom0("xe vm-memory-target-set uuid=%s target=5368709120" % dom0uuid)
        self.host.execdom0("mdadm --create /dev/md1 --level=0 --raid-devices=16 /dev/ram[0-9] /dev/ram1[0-5]")
        sruuid = self.host.execdom0("xe sr-create name-label=Ramdisk\ Local\ Storage content-type=user device-config:device=/dev/md1 type=ext shared=false").strip()

        # Create the initial VDI, a corresponding VBD and plug it to dom0
        vdiuuid = self.host.execdom0("xe vdi-create sr-uuid=%s type=user virtual-size=2MiB name-label=myvdi" % sruuid).strip()
        vbduuid = self.host.execdom0("xe vbd-create vm-uuid=%s type=disk mode=rw device=autodetect vdi-uuid=%s " % (dom0uuid, vdiuuid)).strip()
        self.host.execdom0("xe vbd-plug uuid=%s" % vbduuid)
        dev = self.host.execdom0("xe vbd-list params=device uuid=%s --minimal" % vbduuid).strip()

        # Loop populating the current VDI (snapshotting if necessary)
        for i in range(0, self.chaindepth):
            # We always snapshot, apart from the first level of the tree
            if (i > 0):
                self.host.execdom0("xe vdi-snapshot uuid=%s" % vdiuuid)

            # Fill the corresponding sector of the VHD file
            self.host.execdom0("/root/yngwie -w -d /dev/%s -b %d -o %d -v" % (dev, self.bs, i*self.bs))

        # Loop reading the VDI chain self.samples size
        for i in range(0, self.samples):
            for j in range(self.chaindepth-1, -1, -1):
                # Collect the time, measured 'self.samples' times (and averaged)
                time = int(self.host.execdom0("/root/yngwie -r -d /dev/%s -b %d -o %d -c %d -s | awk {'print $4'}" % (dev, self.bs, j*self.bs, self.samples)).strip())

                # attempt to use taskset, which didn't show any difference
                # time = self.host.execdom0("echo '#!/bin/bash' > /root/yng.sh ; echo 'for ((i=%d; i >= 0; i--)); do /root/yngwie -r -d /dev/%s -b %d -o $[ $i * %d ] -c %d -s |'>>/root/yng.sh ; echo \" awk {'print $4'} ; done\" >> /root/yng.sh ; chmod +x /root/yng.sh ; taskset 1 /root/yng.sh" % (i, dev, self.bs, self.bs, self.samples))

                # Log the average
                self.log("vdisnap-%03d" % j, str(time))

    def postRun(self):
        self.finishUp()
