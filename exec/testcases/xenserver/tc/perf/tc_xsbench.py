import xenrt, libperf, string, os, os.path
import libsynexec

class TCXSBench(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCXSBench")

        self.host = self.getDefaultHost()
        self.testname = "xsbench"

    def parseArgs(self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs(self, arglist)

        self.vm_ram = libperf.getArgument(arglist, "vm_ram", int, 4096)
        self.distro = libperf.getArgument(arglist, "distro", str, "win7sp1-x64")
        self.arch = libperf.getArgument(arglist, "arch", str, "x86-64")
        self.vcpus = libperf.getArgument(arglist, "vcpus", int, 2)
        self.postinstall = libperf.getArgument(arglist, "postinstall", str, None) # comma-separated list of guest function names

        self.dom0vcpus  = libperf.getArgument(arglist, "dom0vcpus", int, None)

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)

    def installGuest(self, guests):
        # Install 'vm-worker'
        if not self.isNameinGuests(guests, "vm-worker"):
            xenrt.TEC().progress("Installing VM worker")

            postinstall = [] if self.postinstall is None else self.postinstall.split(",")

            self.guest = xenrt.productLib(host=self.host).guest.createVM(\
                    host=self.host,
                    guestname="vm-worker",
                    vcpus=self.vcpus,
                    memory=self.vm_ram,
                    distro=self.distro,
                    arch=self.arch,
                    postinstall=postinstall,
                    vifs=self.host.guestFactory().DEFAULT)
        else:
            for vm in guests:
                if vm.getName() == "vm-worker":
                    self.guest = vm

        self.workdir = self.guest.xmlrpcTempDir()

        self.guest.xmlrpcUnpackTarball("%s/%s.tgz" %
                                  (xenrt.TEC().lookup("TEST_TARBALL_BASE"), self.testname),
                                  self.workdir)

    def run(self, arglist=None):
        self.changeNrDom0vcpus(self.host, self.dom0vcpus)

        guests = self.host.guests.values()
        self.installGuest(guests)

        results = self.guest.xmlrpcExec("%s\\%s\\%s.exe" % (self.workdir,
                                                            self.testname, self.testname),
                                        returndata=True)
        self.log("results", results)
