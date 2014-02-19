import xenrt
import libperf
import string
import time

class TCVMInstallSnapshot(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCVMInstallSnapshot")

    def parseArgs(self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs(self, arglist)

        # Parse arguments relating to this test
        self.numvms = libperf.getArgument(arglist, "numvms", int, 500)

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)

        self.master = self.getMaster()

        if self.goldimagesruuid is None:
            # Normally we use a very fast NFS server (NetApp machine, e.g. telti)
            # to put the VM on, but in this case we use local storage:
            self.goldimagesruuid = self.master.execdom0("""xe sr-list name-label=Local\ storage  --minimal""").strip()
        self.goldvm = self.importGoldVM(self.goldimagesruuid, self.desktopimage, self.desktopvmname, self.desktopvmnetwork)

    def run(self, arglist=None):
        # Start and boot the gold VM
        xenrt.TEC().logverbose("Booting the gold VM...")
        bootwatcherLogfile = libperf.createLogName("bootwatcher")
        starterLogfile = libperf.createLogName("starter")
        self.timeStartVMs(1, [self.goldvm], starterLogfile, bootwatcherLogfile)

        # Snapshot the gold VM
        xenrt.TEC().logverbose("Snapshotting the gold VM...")
        output = self.host.execdom0("time xe vm-snapshot uuid=%s new-name-label=snapshot" % self.goldvm.uuid)
        snaptime = libperf.parseTimeOutput(output)
        line = "%f" % snaptime
        self.log("vmsnapshot", line)

        # Install n VMs from the snapshot
        xenrt.TEC().logverbose("Installing from the snapshot...")
        output = self.host.execdom0("for ((i=0; i<=%d; i++)); do time xe vm-install new-name-label=vm$i template-name-label=snapshot; done" % self.numvms)
        xenrt.TEC().logverbose("output: %s" % output)
        self.outputTimings(output, "vminstall")

    def outputTimings(self, output, logfile):
        durs = [libperf.parseMinutesSeconds(line.split('\t')[1]) for line in output.split('\n') if line.startswith('real')]
        for i, val in enumerate(durs):
            line = "%d  %f" % (i, durs[i])
            self.log(logfile, line)

    def postRun(self):
        self.finishUp()

