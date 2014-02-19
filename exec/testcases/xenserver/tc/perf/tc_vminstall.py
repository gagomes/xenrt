import xenrt
import libperf
import string
import time

class TCVMInstall(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCVMInstall")

    def parseArgs(self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs(self, arglist)

        # Parse arguments relating to this test
        self.numvms = libperf.getArgument(arglist, "numvms", int, 500)

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)

    def run(self, arglist=None):
        output = self.host.execdom0("for ((i=0; i<=%d; i++)); do time xe vm-install new-name-label=vm$i template-name-label=Other\ install\ media; done" % self.numvms)
        xenrt.TEC().logverbose("output: %s" % output)
        self.outputTimings(output, "vminstall")

    def outputTimings(self, output, logfile):
        durs = [libperf.parseMinutesSeconds(line.split('\t')[1]) for line in output.split('\n') if line.startswith('real')]
        for i, val in enumerate(durs):
            line = "%d  %f" % (i, durs[i])
            self.log(logfile, line)

    def postRun(self):
        self.finishUp()

