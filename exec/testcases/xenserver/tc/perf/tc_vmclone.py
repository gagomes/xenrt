import xenrt
import libperf
import string

class TCTimeVMClones(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCTimeVMClones")
        # TODO: Use getArgument
        self.numclones = 800 # 800 = 16 hosts x 50 VMs

    def importVanillaVM(self):
        if self.goldimagesruuid is None:
            # Normally we use a very fast NFS server (NetApp machine, e.g. telti)
            # to put the VM on, but in this case we use local storage:
            self.goldimagesruuid = self.host.execdom0("""xe sr-list name-label=Local\ storage  --minimal""").strip()

        vm = self.importVMFromRefBase(self.host, "winxpsp3-vanilla.img", "winxpsp3-vanilla", self.goldimagesruuid)
        self.putVMonNetwork(vm)
        return vm

    def findVanillaVM(self):
        vms = self.host.listGuests()
        xenrt.TEC().logverbose("VM name-labels: [%s]" % vms)
        vms = filter(lambda (vm): vm == 'winxpsp3-vanilla', vms)
        xenrt.TEC().logverbose("Keeping VM name-labels: [%s]" % vms)

        # Take the first one that was found
        vm = vms[0]
        xenrt.TEC().logverbose("registering VM with name-label %s" % (vm))
        g = self.host.guestFactory()(vm, "NO_TEMPLATE", self.host)
        g.existing(self.host)
        self.host.addGuest(g)

        return g

    def prepare(self, arglist=None):
        # Parse generic args
        self.parseArgs(arglist)

        # Parse args relating to this test
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "numclones":
                self.numclones = int(l[1])

        self.initialiseHostList()
        self.configureAllHosts()

        self.goldvm = self.importVanillaVM()

    def run(self, arglist=None):

        uuid = self.goldvm.getUUID()

        # Now repeatedly clone the VM
        clonerLogfile = libperf.createLogName("cloner")
        xenrt.TEC().comment("cloner logfile: %s" % clonerLogfile)
        t = libperf.Cloner(self, self.host, self.goldvm, self.numclones, clonerLogfile)
        t.start()
        t.join()

    def postRun(self):
        self.finishUp()

