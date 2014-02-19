import xenrt
import libperf
import string
import time

class TCSuspendResume(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCSuspendResume")
        self.memsizes = [256, 512, 1024] # MB
        self.numiters = 10
        self.vm = None

    def prepare(self, arglist=None):
        # Parse generic args
        self.parseArgs(arglist)

        # Parse args relating to this test
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "numiters":
                self.numiters = int(l[1])
            elif l[0] == "memsizes":
                self.memsizes = [int(x) for x in l[1].split(",")]

        self.initialiseHostList()
        self.configureAllHosts()

        # Import a Linux VM onto local storage
        self.vm = self.host.createGenericLinuxGuest()
        self.vm.shutdown()

    def run(self, arglist=None):
        suspendLog = "vmsuspend"
        resumeLog = "vmresume"
        for log in suspendLog, resumeLog:
            self.log(log, "# memsize    iter   duration")

        for memsize in self.memsizes:
            # Set the memory size
            self.vm.memset(memsize)

            # Start the VM
            self.vm.start()

            uuid = self.vm.getUUID()

            for i in range(0, self.numiters):
                # Suspend the VM
                cmd = "time xe vm-suspend uuid=%s" % uuid
                dur = libperf.timeCLICommand(self.host, cmd)
                line = "%d  %d  %f" % (memsize, i, dur)
                self.log(suspendLog, line)
                
                # Resume the VM
                cmd = "time xe vm-resume uuid=%s" % uuid
                dur = libperf.timeCLICommand(self.host, cmd)
                line = "%d  %d  %f" % (memsize, i, dur)
                self.log(resumeLog, line)

            # Shutdown the VM
            self.vm.shutdown()

    def postRun(self):
        self.finishUp()

