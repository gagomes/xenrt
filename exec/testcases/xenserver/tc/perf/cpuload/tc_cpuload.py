import xenrt
import testcases.xenserver.tc.perf.libperf as libperf
from testcases.xenserver.tc.perf.tc_vmstart import TCTimeVMStarts
import string
import time, sys, os, socket

class TCCPUload(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, self.__class__.__name__)
        self._log = xenrt.TEC().logverbose
        self._log ("TCCPUload: initialized")
        remoteRunner = libperf.RemoteRunner()
        self.remoteRun = remoteRunner.remoteRun
        self.transfer = remoteRunner.transfer

    def installTools (self):
        from os.path import join
        self.transfer (self.master, *(scripts['atop.rpm']))

        # Either install or update:
        self._run0 ("rpm -i atop.rpm || rpm -F atop.rpm")

    def specificPrepare (self, arglist=[]):
        self.master = self.getMaster()
        run0 = self._run0 = self.master.execdom0
        # $! gives pid of last process sent to background in bash.
        self._run0bg = (lambda command, outfile="/dev/null":
                            (self._run0 ("nohup %s > %s 2> /dev/null & echo $!" % (command, outfile))
                             .strip()))

        self.installTools ()

        self.atopLogFile = "atop-log-file"


        self.atop_pid = self._run0bg ("atop 0 -w %s" % self.atopLogFile)
        self._log ("TCCPUload: started atop (%s)" % self.atop_pid)

        # run xentop in the background, in batch mode, redirect output
        self.xentopLogFile = "xentop-log-file"

        get = libperf.curry (libperf.getArgument, arglist)
        self.seconds_to_run = get("duration", int, 5*60)

    def prepare(self, arglist=[]):
        self.basicPrepare (arglist)

        self.specificPrepare (arglist)

    def run(self, arglist=[]):
        # ask atop for first sample.
#        self.signaller_pid = self._run0bg ("%s %s" % ('signaller',
#                                                      self.atop_pid))

        self.signaller_pid = self.remoteRun (self.master,
                scripts['signaller'], self.atop_pid, background=True)

        self.xentop_pid = self._run0bg ("xentop --batch --delay 1", self.xentopLogFile)


        time.sleep (self.seconds_to_run)

        # kill atop and xentop:
        # don't kill atop with 9!  Give it a chance to shut down
        # process accounting in the kernel with 15 (the default).
        # There's no need to kill the signaller, it will die with atop with
        #     OSError: [Errno 3] No such process

        self._log ("TCCPUload: killing atop (%s) and xentop (%s)" % (self.atop_pid, self.xentop_pid))
        self._run0 ("kill %s %s" % (self.atop_pid, self.xentop_pid))
        # wait till atop is really terminated.
        # ideas:
        # check if either /proc/[pid] no longer exists, or if new process has a different /proc/%{pid}/stat:starttime

        # using inotifywait on the logfile could also do it:
        # "inotifywait -e CLOSE_WRITE %s" % self.atopLogFile
        # but we would need to setup the inotifywait, before we send the kill (otherwise the kill might be to fast.)
        # employing `fuser' on the log-file could also work.

        # here's the hacky solution:
        time.sleep (5)
        # now we gather the logfiles:
        self._log ("TCCPUload: extracting log-files")
        logs = [self._run0 ("cat %s" % self.atopLogFile), self._run0 ("cat %s" % self.xentopLogFile)]
        local_logFiles = map(libperf.createLogName, ["atop","xentop"])

        [libperf.outputToResultsFile(logFile, log, addNewline=False)
         for (logFile, log) in zip(local_logFiles, logs)]

        self._log ("TCCPUload: Wrote log-files")

    def postRun(self):
        self.finishUp()

class TCCPUload_VMidle(TCTimeVMStarts, TCCPUload):
    def __init__(self):
        # We don't want to call TCTimeVMStarts's __init__

        # Review this decision, if TCTimeVMStarts's __init__ ever does
        # any useful work we are interested in.  At the moment it only
        # calls the super-class's __init__, and we don't want to call
        # that twice.  (Though we could probably work to make it safe
        # to call it twice.)
        TCCPUload.__init__ (self)
        self.settlingTime = 0

    def prepare(self, arglist=[]):
        TCTimeVMStarts.prepare(self, arglist)
        TCCPUload.specificPrepare (self)
        self.settlingTime = libperf.getArgument(arglist, "settlingtime", int, 0)

    def run(self, arglist=[]):
        TCTimeVMStarts.run(self, arglist)
        # Give the VMs time to settle for a bit.  (In accordance with
        # the definition of the metric.)
        xenrt.TEC().logverbose("Leaving the VMs to settle for %d seconds..." % self.settlingTime)
        time.sleep(self.settlingTime)
        TCCPUload.run(self, arglist)

        params = libperf.createLogName ("tc_cpuload_parameters")
        log = """#numdesktops
%s
""" % self.numdesktops
        libperf.outputToResultsFile(params, log, addNewline=False)
