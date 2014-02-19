import xenrt
import libperf
import string
import time

class TCUnixBench(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCUnixBench")

        self.instFiledir = "/usr/share/xenrt/tests/unixbench"

        self.runs = 1

    def prepare(self, arglist=None):
        # Parse generic args
        self.parseArgs(arglist)

        self.runs = libperf.getArgument(arglist, "runs", int, 1)

        self.initialiseHostList()
        self.configureAllHosts()

    def run(self, arglist=None):
        sftp = self.host.sftpClient()

        # From http://code.google.com/p/byte-unixbench/
        unixbenchFilename = "UnixBench5.1.3.tgz"
        unixbenchSrc = "%s/%s" % (self.instFiledir, unixbenchFilename)
        unixbenchDest = "/root/%s" % unixbenchFilename

        # Install unixbench
        sftp.copyTo(unixbenchSrc, unixbenchDest)
        output = self.host.execdom0("tar xvfz %s" % unixbenchDest)
        xenrt.TEC().logverbose("output: %s" % output)
        instDir = "/root/UnixBench"

        # Install make, gcc
        cmds = [
            "yum --disablerepo=citrix --enablerepo=base,updates install -y make",
            "yum --disablerepo=citrix --enablerepo=base,updates install -y gcc",
        ]
        for cmd in cmds:
            output = self.host.execdom0(cmd)
            xenrt.TEC().logverbose("output: %s" % output)

        # Run the benchmark (n times)
        cmd = "./Run"
        for i in range(0, self.runs):
            logfile = "results.%d" % i
            output = self.host.execdom0("cd %s && %s" % (instDir, cmd), timeout=14400)
            xenrt.TEC().logverbose("output: %s" % output)
            self.log(logfile, output)

    def postRun(self):
        self.finishUp()

