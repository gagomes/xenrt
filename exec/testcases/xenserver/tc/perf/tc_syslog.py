import xenrt
import libperf
import string
import time

class TCSysLog(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCSysLog")

    def parseArgs(self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs(self, arglist)

        # Parse arguments relating to this test
        self.messages = libperf.getArgument(arglist, "messages", int, 100000)

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)

    def run(self, arglist=None):
        output = self.host.execdom0("n=%d; time for ((i=0; i<=$n; i++)); do logger \"test message $i of $n\"; done" % self.messages)
        xenrt.TEC().logverbose("output: %s" % output)
        dur = libperf.parseTimeOutput(output)

        line = "%d  %f" % (self.messages, dur)
        self.log("syslog", line)

    def postRun(self):
        self.finishUp()


