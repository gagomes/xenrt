import xenrt, libperf, string, threading

class TCDiskLatency(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCDiskLatency")

        self.vbds = 0       # Number of total VBDs plugged in the host
        self.rvms = 0       # Number of total number of VMs running

        # VM Data
        self.vm = [ ]
        self.host = self.getDefaultHost()
        self.edisk = ( None, 1, False )  # definition of an extra disk

    def parseArgs(self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs(self, arglist)

        # Parse other arguments
        self.vms     = libperf.getArgument(arglist, "numvms",  int, 20)
        self.edisks  = libperf.getArgument(arglist, "edisks",  int, 5)
        self.distro  = libperf.getArgument(arglist, "distro",  str, "debian60")
        self.arch    = libperf.getArgument(arglist, "arch",    str, "x86-32")
        self.bufsize = libperf.getArgument(arglist, "bufsize", int, 512)

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)

    def collectMetrics(self):
        results = self.vm[0].execguest("/root/latency -sw -b %d /dev/xvdb 60 2>/dev/null" % self.bufsize)
        for line in results.splitlines():
            self.log("latency", "%d %d %d" % (self.rvms, self.vbds, int(line)))

    def run(self, arglist=None):

        # Install 'vm00'
        xenrt.TEC().progress("Installing VM zero")
        self.vm.append(xenrt.lib.xenserver.guest.createVM(\
                    host=self.host,
                    guestname="vm00",
                    distro=self.distro,
                    arch=self.arch,
                    vifs=xenrt.lib.xenserver.Guest.DEFAULT,
                    disks=[ self.edisk ]))
        self.vbds += 2
        self.rvms += 1

        # Copy latency and stats to 'vm00'
        sftp = self.vm[0].sftpClient()
        sftp.copyTo("/home/xenrtd/felipef/latency", "/root/latency")
        sftp.copyTo("/home/xenrtd/felipef/stats", "/root/stats")

        # Populate the extra disk
        self.vm[0].execguest("dd if=/dev/zero of=/dev/xvdb bs=1M oflag=direct || true")

        # Collect reference metrics (1 VM, 2 VBDs)
        self.collectMetrics()

        # Install more VMs so that we can plug more VBDs in the host
        for i in range(1, self.vms+1):
            xenrt.TEC().progress("Installing VM %d" % i)

            # Copies original VM (much quicker than installing another one)
            self.vm[0].shutdown()
            self.vm.append(self.vm[0].copyVM(name="vm%02d" % i))
            self.vm[i].removeDisk(1)
            self.vm[0].start()
            self.vm[i].start()

            # At this point, we added one VM and plugged only one more VBD to the host
            self.rvms += 1
            self.vbds += 1

            # Recollect metrics
            self.collectMetrics()

            # Loop adding more VBDs
            for j in range(0, self.edisks):
                self.vm[i].createDisk(sizebytes=xenrt.GIGA)
                self.vbds += 1
                self.collectMetrics()
