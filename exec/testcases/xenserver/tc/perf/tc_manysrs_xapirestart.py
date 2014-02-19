import xenrt
import libperf
import string
import time

class TCManySRs(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCManySRs")
        self.numsrs = 500

    def prepare(self, arglist=None):
        # Parse generic args
        self.parseArgs(arglist)

        # Parse args relating to this test
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "numsrs":
                self.numsrs = int(l[1])

        self.initialiseHostList()
        self.configureAllHosts()

    def run(self, arglist=None):
        logname = "durations"

        # Get uuid of a/the slave
        slaveuuid = None
        for h in map (self.tec.gec.registry.hostGet, self.normalHosts):
            if h != self.host:
                slaveuuid = h.uuid
                break
        if slaveuuid is None:
            raise Exception("Couldn't find a slave host in %s" % self.normalHosts)

        # Create lots of SRs on the slave
        cmd = "time for ((i=1; i<=%d; i++)); do xe sr-create host-uuid=%s type=dummy name-label=dummy$i; done" % (self.numsrs, slaveuuid)
        output = self.host.execdom0(cmd, timeout=1800)
        xenrt.TEC().logverbose("output: %s" % output)
        dur = libperf.parseTimeOutput(output)

        line = "create	%f" % dur
        self.log(logname, line)

        # Stop xapi on the slave
        xenrt.TEC().logverbose("stopping xapi on slave(s)...")
        for h in map (self.tec.gec.registry.hostGet, self.normalHosts):
            if h != self.host:
                xenrt.TEC().logverbose("stopping xapi on host %s" % h.getName())
                h.execdom0("service xapi stop")

        # Wait 5 minutes
        sleep = 5*60
        xenrt.TEC().logverbose("sleeping %d seconds..." % sleep)
        time.sleep(sleep)

        # Stop xapi on the master (so that it doesn't run the post-host-dead-hook before xapi startup)
        xenrt.TEC().logverbose("stopping xapi on master...")
        cmd = "service xapi stop"
        self.host.execdom0(cmd)
        
        # Wait a bit more than another 5 minutes (totalling 10 = Xapi_globs.host_assumed_dead_interval)
        sleep = 5*60 + 30
        xenrt.TEC().logverbose("sleeping %d seconds..." % sleep)
        time.sleep(sleep)

        # Now see how long it takes to restart xapi on the master -- this should cause it to run the host-post-declare-dead hook
        xenrt.TEC().logverbose("now timing duration of xapi start on master...")
        cmd = "time service xapi start"
        output = self.host.execdom0(cmd, timeout=1800)
        xenrt.TEC().logverbose("output: %s" % output)
        dur = libperf.parseTimeOutput(output)

        line = "restart	%f" % dur
        self.log(logname, line)

    def postRun(self):
        self.finishUp()

