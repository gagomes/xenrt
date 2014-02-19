import xenrt
import libperf
import string
import time
from threading import Thread

class OnHostXapiResponsivenessThread(Thread):
    def __init__(self, host, cmd, delay):
        Thread.__init__(self)

        self.stopfile = "/var/stoptest"
        self.host = host
        self.cmd = cmd  # command to execute, e.g. "xe pool-list"
        self.delay = delay

        self.durs = []  # measurements are written here

    def run(self):
        xenrt.TEC().logverbose("Responsiveness thread: started")
        output = self.host.execdom0("\
            stopfile=%s; \
            rm -f $stopfile; \
            while [ ! -e \"$stopfile\" ]; do \
                time %s; \
                sleep %s; \
            done; \
            rm -f $stopfile \
        " % (self.stopfile, self.cmd, str(self.delay)), timeout=3600)

        self.durs = [libperf.parseMinutesSeconds(line.split('\t')[1]) for line in output.split('\n') if line.startswith('real')]
        xenrt.TEC().logverbose("Responsiveness thread: stopped")

    def signalStop(self):
        self.host.execdom0("touch %s" % self.stopfile)
        xenrt.TEC().logverbose("Responsiveness thread: signalled to stop")

    def getDurations(self):
        return self.durs

class TCXeVMstart(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCXeVMstart")
        self.numothervms = 0
        self.numiters = 10
        self.measureResponsiveness = False
        self.installFromScratch = False

    def prepare(self, arglist=None):
        # Parse generic args
        self.parseArgs(arglist)

        # Parse args relating to this test
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "numothervms":
                self.numothervms = int(l[1])
            elif l[0] == "numiters":
                self.numiters = int(l[1])
            elif l[0] == "measureresponsiveness":
                self.measureResponsiveness = True
            elif l[0] == "installfromscratch":
                self.installFromScratch = True

        self.initialiseHostList()
        self.configureAllHosts()

        if self.goldimagesruuid is None:
            # Normally we use a very fast NFS server (NetApp machine, e.g. telti)
            # to put the VM on, but in this case we use local storage:
            self.goldimagesruuid = self.host.execdom0("""xe sr-list name-label=Local\ storage  --minimal""").strip()

        if not self.installFromScratch:
            xenrt.TEC().logverbose("Importing VM")
            self.goldvm = self.importGoldVM(self.goldimagesruuid, self.desktopimage, self.desktopvmname, self.desktopvmnetwork)
        else:
            xenrt.TEC().logverbose("Creating VM from scratch")

            # Create and install the VM
            self.goldvm = xenrt.lib.xenserver.guest.createVM(self.host,
                xenrt.randomGuestName(),
                "ws08-x86",
                vcpus=4,
                memory=16384, # MB
                arch="x86-64",
                sr=self.goldimagesruuid,
                vifs=[("0", self.host.getPrimaryBridge(), xenrt.randomMAC(), None)],
                disks=[("0",1,False)])

            # Shut the VM down, so its start-time is ready to be measured
            xenrt.TEC().logverbose("Shutting VM down...")
            self.goldvm.shutdown()

    def measure(self, cmd, i, logfile):
        if self.measureResponsiveness:
            # Start a thread to measure xapi responsiveness
            t = OnHostXapiResponsivenessThread(self.host, "xe pool-list", 0.1)
            t.start()

        self.measurecommand(cmd, i, logfile)

        if self.measureResponsiveness:
            # Stop the thread
            t.signalStop()
            t.join()

            # Get the responsiveness measurements
            durs = t.getDurations()
            line = "%d	%s" % (i, ",".join(map(str, durs)))
            self.log("responsiveness-during-%s" % logfile, line)

    def measurecommand(self, cmd, i, logfile):
        output = self.host.execdom0("time %s" % cmd)
        dur = libperf.parseTimeOutput(output)
        line = "%d	%f" % (i, dur)
        self.log(logfile, line)

    def run(self, arglist=None):
        # Create other VMs
        xenrt.TEC().logverbose("Creating %d other halted VMs..." % self.numothervms)
        for i in range(0, self.numothervms):
            cmd = "xe vm-install new-name-label=vm%d template-name-label=Other\ install\ media" % i
            self.host.execdom0(cmd)

        startLog = "vmstart"
        shutdownLog = "vmshutdown"
        for log in startLog, shutdownLog:
            self.log(log, "# iter	duration")

        for i in range(0, self.numiters):
            # Time the duration of xe vm-start
            self.measure("xe vm-start uuid=%s" % self.goldvm.uuid, i, startLog)

            # Leave things to settle
            time.sleep(5)

            # Time the duration of xe vm-shutdown --force
            self.measure("xe vm-shutdown uuid=%s --force" % self.goldvm.uuid, i, shutdownLog)

            # Leave things to settle
            time.sleep(5)

    def postRun(self):
        self.finishUp()

