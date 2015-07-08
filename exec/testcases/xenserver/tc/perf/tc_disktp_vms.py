import xenrt, libperf, string, threading

class TCDiskThroughput(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCDiskThroughput")

        # Test data
                         #   1sec 1KiB    2KiB    4KiB    8KiB    16KiB    32KiB    64KiB    128KiB    256KiB    512KiB    1MB        2MiB       4MiB       8MiB
        self.blocksizes  = [ 512, 1*1024, 2*1024, 4*1024, 8*1024, 16*1024, 32*1024, 64*1024, 128*1024, 256*1024, 512*1024, 1024*1024, 2*1048576, 4*1048576, 8*1048576 ]

                         #   16MiB       32MiB       64MiB
        self.blocksizes += [ 16*1048576, 32*1048576, 64*1048576 ]
        self.schedulers = [ 'noop', 'anticipatory', 'deadline', 'cfq' ]
        self.samples = 10
        self.numofdevs = 8
        self.totalsize = 64*1024*1024 # 64 MiB
        self.vdisize = "1GiB"

        # VM Data
        self.host = self.getDefaultHost()
        self.distro = "debian60"
	self.arch = "x86-32"
        self.method = "HTTP"
        self.disks = []

    def parseArgs(self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs(self, arglist)

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)

    def measureThroughput(self, path, bs, count, my_id, total, sched):
        xenrt.TEC().progress("Running thread...")
        for i in range(0, self.samples):
            self.log("dom0-%d-%d-%s-%09d" % (my_id, total, sched, bs), self.host.execdom0("/root/yngwie -w -d %s -b %Ld -c %Ld" % (path, bs, count), timeout=1800).strip())

    def vdicreate(self, arglist=None):
        sruuid = self.host.execdom0("xe sr-list name-label=Local\ storage --minimal").strip()
        dom0uuid = self.host.execdom0("xe vm-list is-control-domain=true --minimal").strip()
        vdiuuid = self.host.execdom0("xe vdi-create sr-uuid=%s virtual-size=%s type=user name-label=vdi" % (sruuid, self.vdisize)).strip()
        vbduuid = self.host.execdom0("xe vbd-create vm-uuid=%s vdi-uuid=%s device=autodetect" % (dom0uuid, vdiuuid)).strip()
        self.host.execdom0("xe vbd-plug uuid=%s" % vbduuid)
        dev = self.host.execdom0("xe vbd-param-get uuid=%s param-name=device" % vbduuid).strip()
        devpath = "/dev/%s" % dev
        self.host.execdom0("dd if=/dev/zero of=%s bs=1M || true" % devpath)
        return devpath

    def run(self, arglist=None):
        # Send yngwie to host
        sftp = self.host.sftpClient()
        sftp.copyTo("/home/xenrtd/felipef/yngwie", "/root/yngwie")

	# Initialize devpaths as an empty list of device paths
        xenrt.TEC().progress("Commencing measurements...")
        devpaths = [ ]
        vm = [ ]

        # Choose a template for the desired distro
        self.template = xenrt.lib.xenserver.getTemplate(self.host, self.distro, arch=self.arch)

        for i in range(1, self.numofdevs+1):
            xenrt.TEC().progress("Installing VM %d" % i)

            # Create an empty guest object
            vm += [ self.host.guestFactory()("vm%02d" % i, self.template, self.host) ]
            #self.uninstallOnCleanup(guest)
            #self.getLogsFrom(guest)

            # Get the repository location
            r = xenrt.getLinuxRepo(self.distro, self.arch, self.method)
            if not r:
                raise xenrt.XRTError("No NFS repository for %s %s" % (self.arch, self.distro))
            self.repo = string.split(r)[0]

            # Install from network repository into the VM
            vm[i].arch = self.arch
            vm[i].install(self.host,
                          pxe=False,
                          repository=self.repo,
                          distro=self.distro,
                          notools=False,
                          method=self.method,
                          isoname=xenrt.DEFAULT)
            vm[i].check()

            #guest.reboot()
            #guest.suspend()
            #guest.resume()
            #guest.check()
            #guest.shutdown()
            #guest.start()
            #guest.check()

            # Install VM 'i'
            #vm[i-1] = xenrt.lib.xenserver.guest.createVM(self.host, "vm%d" % i, self.distro) # , disks=self.disks)

            # Using the local SR, create a VDI, plug it to dom0 and inflate the VHD
#            devpaths += [ self.vdicreate() ]
#
#            for sched in self.schedulers:
#                self.host.execdom0("echo %s > /sys/block/sda/queue/scheduler" % sched)
#
#                for bs in self.blocksizes:
#                    count = self.totalsize / bs
#                    xenrt.TEC().progress("Running %d times" % count)
#
#                    threads = [ ]
#                    for j in range(1, i+1):
#                        xenrt.TEC().progress("Initiating thread %d with args: %s, %d, %d, %d, %d %s" % (j, devpaths[j], bs, count, j, i, sched))
#                        threads.append(threading.Thread(target=self.measureThroughput, args=(devpaths[j-1], bs, count, j, i, sched)))
#                    for j in range(1, i+1):
#                        xenrt.TEC().progress("Starting thread %d" % j)
#                        threads[j-1].start()
#                    for j in range(1, i+1):
#                        threads[j-1].join()


