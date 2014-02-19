import xenrt
import libperf
import string
import time

class TCVDIDelete(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCVDIDelete")
        self.numvdis = 100

    def prepare(self, arglist=None):
        # Parse generic args
        self.parseArgs(arglist)

        # Parse args relating to this test
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "numvdis":
                self.numvdis = int(l[1])

        self.initialiseHostList()
        self.configureAllHosts()

    def run(self, arglist=None):
        sruuid = self.goldimagesruuid

        createLog = "vmcreate"
        destroyLog = "vmdestroy"
        for log in createLog, destroyLog:
            self.log(log, "# i  duration")

        uuids = {}

        # Create the VDIs on the SR
        for i in range(0, self.numvdis):
            cmd = "time xe vdi-create type=user virtual-size=1MiB name-label=test%d sr-uuid=%s" % (i, sruuid)
            dur = libperf.timeCLICommand(self.host, cmd)
            line = "%d  %f" % (i, dur)
            self.log(createLog, line)

            cmd = "xe vdi-list name-label=test%d params=uuid --minimal" % i
            uuids[i] = self.host.execdom0(cmd).strip()
            xenrt.TEC().logverbose("uuid of vdi %d is %s" % (i, uuids[i]))

        # Delete the VDIs
        for i in range(0, self.numvdis):
            cmd = "time xe vdi-destroy uuid=%s" % uuids[i]
            dur = libperf.timeCLICommand(self.host, cmd)
            line = "%d  %f" % (i, dur)
            self.log(destroyLog, line)

    def postRun(self):
        self.finishUp()

