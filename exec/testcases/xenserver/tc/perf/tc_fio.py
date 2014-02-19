import xenrt
import libperf
import string

class TCfio(libperf.PerfTestCase):
    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCfio")
        self.blockSizes = ["4k", "8k", "16k", "32k", "64k", "128k","256k","512k","1m","2m","4m"]
        self.iters = 5
        self.fioSize = "128m"
        self.vdiSize = 1*xenrt.GIGA
        self.ioDepths = range(1,9)
        self.srtypeFull = "lvm"
        self.srtype = "lvm"

    def parseArgs(self, arglist):
        libperf.PerfTestCase.parseArgs(self, arglist)
        self.fioIters = libperf.getArgument(arglist, "fioiters", int, 5)
        # Allow someone to specify e.g. lvm_ssd, but when we look for the SR, just look for "lvm"
        self.srtypeFull = libperf.getArgument(arglist, "srtype", str, "lvm")
        self.srtype = self.srtypeFull.split("_")[0]

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)
        self.host = self.getDefaultHost()
        if self.host.guests.has_key("debian"):
            self.guest = self.host.guests['debian']
        else:
            self.guest = self.host.createBasicGuest(name="debian", distro="debian70")
        self.guest.setState("DOWN")
        # Destroy any additional disks the VM currently has, so we can recreate xvdb on the correct SR
        self.guest.destroyAdditionalDisks()
        # Find the SR (just based on type)
        sruuid = self.host.minimalList("sr-list", "uuid","type=%s" % self.srtype)[0]
        # Create the new VDI, and mount it in the VM
        self.guest.createDisk(sizebytes = self.vdiSize, sruuid=sruuid, userdevice=1)
        self.guest.setState("UP")
        # Allocate space on the VHD by writing /dev/urandom to it
        self.guest.execguest("dd if=/dev/urandom of=/dev/xvdb bs=1M count=%d oflag=direct" % (self.vdiSize/xenrt.MEGA))
        self.guest.reboot()
        self.guest.execguest("mkdir -p /benchmark")
        self.guest.execguest("mkfs.ext4 /dev/xvdb")
        self.guest.execguest("mount /dev/xvdb /benchmark")
        # Install fio in the VM
        self.guest.execguest("apt-get install -y --force-yes fio")

    def runfio(self, workload, blocksize, iodepth):
        self.guest.execguest("rm -f /benchmark/benchmark*")

        cmd = "fio --name=job --directory=/benchmark --filename=benchmark " \
              "--rw=%s --iodepth=%d --direct=1 --invalidate=1 --size=%s " \
              "--blocksize=%s --minimal" % (workload, iodepth, self.fioSize, blocksize)
        res = self.guest.execguest(cmd)

        self.log("fio", "%s\t%s" % (cmd.strip(), res.strip()))

        fields = res.split(";")
        # First field specifies the output format version - we're expecting version 3, which has:
        # Read bandwidth/IOPS as fields 6 and 7
        # Write bandwidth/IOPS as fields 47 and 48
        if fields[0] != "3":
            raise xenrt.XRTError("Output format of fio is not version 3")
        ret = {"read": {"bw": fields[6],"iops": fields[7]}, "write": {"bw": fields[47], "iops": fields[48]}}

        return ret

    def run(self, arglist=None):

        # CSV headings
        self.log("read", "srtype,blocksize,iodepth,iter,bw,iops")
        self.log("write", "srtype,blocksize,iodepth,iter,bw,iops")

        for i in xrange(self.fioIters):
            for b in self.blockSizes:
                for d in self.ioDepths:
                    data = self.runfio("read", b, d)["read"]
                    self.log("read", "%s,%s,%s,%s,%s,%s" % (self.srtypeFull,b,d,i,data['bw'],data['iops']))
                    data = self.runfio("write", b, d)["write"]
                    self.log("write", "%s,%s,%s,%s,%s,%s" % (self.srtypeFull,b,d,i,data['bw'],data['iops']))
