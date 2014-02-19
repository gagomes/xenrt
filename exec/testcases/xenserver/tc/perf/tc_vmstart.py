import xenrt
import libperf
import string

class TCTimeVMStarts(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCTimeVMStarts")

    def parseArgs (self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs (self, arglist)

        # Parse arguments relating to this test
        self.numdesktops = libperf.getArgument (arglist,
            "numdesktops", int, 1000) # 800 = 16 hosts x 50 VMs

    def prepare(self, arglist=[]):
        self.basicPrepare (arglist)

        self.guest = self.createHelperGuest()
        self.master = self.getMaster()

        if self.goldimagesruuid is None:
            # Normally we use a very fast NFS server (NetApp machine, e.g. telti)
            # to put the VM on, but in this case we use local storage:
            self.goldimagesruuid = self.master.execdom0("""xe sr-list name-label=Local\ storage  --minimal""").strip()
        self.goldvm = self.importGoldVM(self.goldimagesruuid, self.desktopimage, self.desktopvmname, self.desktopvmnetwork)

    def run(self, arglist=None):
        # Create the clones, recording how long it takes to do so
        self.clones = self.createMPSVMs(self.numdesktops, self.goldvm)
        self.configureAllVMs()

        # Set up log files for REQ226
        bootwatcherLogfile = libperf.createLogName("bootwatcher")
        starterLogfile = libperf.createLogName("starter")
        xenrt.TEC().comment("bootwatcher logfile: %s" % bootwatcherLogfile)
        xenrt.TEC().comment("starter logfile: %s" % starterLogfile)

        # Begin to collect stats from NetApp, for REQ246,248
        self.startNetAppStatGather()
        
        # Now start the VMs, for REQ226
        numthreads = len(self.normalHosts)
        self.timeStartVMs(numthreads, self.clones, starterLogfile, bootwatcherLogfile)

        # Now gather the final stats from the NetApp, for REQ246,248
        stats = self.finishNetAppStatGather()
        netappLogFile = libperf.createLogName("netapp")
        libperf.outputToResultsFile(netappLogFile, stats)

    def postRun(self):
        self.finishUp()
