import xenrt
import libperf

class TCha(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCha")

        self.iters = 20
        self.sr = None

    def parseArgs(self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs(self, arglist)

        # Parse arguments relating to this test
        self.iters = libperf.getArgument(arglist, "iters", int, 20)

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)

        # Create a VM with an iSCSI target
        target = self.host.createGenericLinuxGuest(allowUpdateKernel=False)
        iqn = target.installLinuxISCSITarget()
        target.createISCSITargetLun(0, 1024)

        # Create an LVMoiSCSI SR
        self.sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host, "iscsi-target")
        lun = xenrt.ISCSILunSpecified("xenrt-test/%s/%s" % (iqn, target.getIP()))
        self.sr.create(lun, subtype="lvm", findSCSIID=True)

    def measure(self, cmd, i, logfile):
        output = self.host.execdom0("time %s" % cmd)
        dur = libperf.parseTimeOutput(output)
        line = "%d	%f" % (i, dur)
        self.log(logfile, line)

    def run(self, arglist=None):
        for i in range(0, self.iters):
            self.measure("xe pool-ha-enable heartbeat-sr-uuids=%s" % self.sr.uuid, i, "enable")
            self.measure("xe pool-ha-disable", i, "disable")

    def postRun(self):
        self.finishUp()

