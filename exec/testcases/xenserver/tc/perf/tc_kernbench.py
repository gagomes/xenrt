import xenrt, libperf, string, os, os.path
import libsynexec

def toBool(val):
    if val.lower() in ("false", "no"):
        return False
    return True

class TCKernBench(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCKernBench")

        self.host = self.getDefaultHost()

    def parseArgs(self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs(self, arglist)

        self.vm_ram = libperf.getArgument(arglist, "vm_ram", int, 4096)
        self.distro = libperf.getArgument(arglist, "distro", str, "debian70")
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

        self.guest.installKernBench()

    def run(self, arglist=None):
        self.changeNrDom0vcpus(self.host, self.dom0vcpus)

        guests = self.host.guests.values()
        self.installGuest(guests)

        self.guest.execguest("cd /root/kernbench3.10/linux; make mrproper")
        self.guest.execguest("cd /root/kernbench3.10/linux; make alldefconfig")
        self.guest.execguest("cd /root/kernbench3.10/linux; ../kernbench -H -M", timeout=10800)

        # Fetch results
        result = self.guest.execguest("cat /root/kernbench3.10/linux/kernbench.log")
        for line in result.splitlines():
            self.log("results", line)
