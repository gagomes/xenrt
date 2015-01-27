import xenrt
import libperf
import string
import time

class TCDom0Mem(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCDom0Mem")

    def parseArgs (self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs (self, arglist)

        # NB: use the 'dontusemps' argument if you don't want to use MPS

        # Parse arguments relating to this test
        self.numvms = libperf.getArgument (arglist, "numvms", int, 50)
        self.vmname = libperf.getArgument (arglist, "guest",  str, None)

    def prepare(self, arglist=[]):
        self.basicPrepare (arglist)

        if self.vmname is None:
            # Create a bunch of MPS VMs
            self.master = self.getMaster()
            if self.goldimagesruuid is None:
                # Normally we use a very fast NFS server (NetApp machine, e.g. telti)
                # to put the VM on, but in this case we use local storage:
                self.goldimagesruuid = self.master.execdom0("""xe sr-list name-label=Local\ storage  --minimal""").strip()
            self.goldvm = self.importGoldVM(self.goldimagesruuid, self.desktopimage, self.desktopvmname, self.desktopvmnetwork)

            # Clone the VM n times
            self.clones = self.createMPSVMs(self.numvms, self.goldvm)
            self.configureAllVMs()

        else:
            # Clone the VM provided by the sequence file
            vm = xenrt.TEC().registry.guestGet(self.vmname)
            xenrt.TEC().logverbose("vm with name [%s] is [%s]" % (self.vmname, vm))

            vm.shutdown()

            self.clones = [vm]
            for i in range(self.numvms-1):
                xenrt.TEC().logverbose("making clone %d..." % (i))
                self.clones.append(vm.cloneVM(name="clone%02d" % (i)))

    def sampleDom0State(self, numRunningVMs):
        xenrt.TEC().logverbose("Waiting for dom0 to settle...")

        # Wait for the system to settle
        time.sleep(30)

        xenrt.TEC().logverbose("Sampling dom0 state (with %d running VMs)" % numRunningVMs)

        cmds = [
            # Sample dom0 memory usage
            ("cat /proc/meminfo", "meminfo-%d"),
            # See what processes are running in dom0
            ("ps axuwww", "ps-axuwww-%d"),
            # list_domains
            ("list_domains -all", "list_domains-%d"),
        ]

        for cmd, logfile in cmds:
            output = self.host.execdom0(cmd)
            self.log(logfile % numRunningVMs, output)

    def run(self, arglist=None):
        # Set up log files
        bootwatcherLogfile = libperf.createLogName("bootwatcher")
        starterLogfile = libperf.createLogName("starter")
        xenrt.TEC().comment("bootwatcher logfile: %s" % bootwatcherLogfile)
        xenrt.TEC().comment("starter logfile: %s" % starterLogfile)

        self.sampleDom0State(0)

        for i in range(0, self.numvms):
            vm = self.clones[i]

            # Start the VM
            # TODO: BootWatcher will count already-booted VMs, not just those in the list of VMs to watch.
            self.timeStartVMs(1, [vm], starterLogfile, bootwatcherLogfile)
            
            # Sample dom0 state
            self.sampleDom0State(i+1)

    def postRun(self):
        self.finishUp()
