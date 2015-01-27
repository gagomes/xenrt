import xenrt
import libperf
import string
import time

class TCLMBench(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCLMBench")

        self.mb = 256
        self.runs = 4

        self.instFiledir = "/usr/share/xenrt/tests"

    def prepare(self, arglist=None):
        # Parse generic args
        self.parseArgs(arglist)

        # Parse args relating to this test
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "mb":
                self.mb = int(l[1])
            elif l[0] == "runs":
                self.runs = int(l[1])

        self.initialiseHostList()
        self.configureAllHosts()

    def run(self, arglist=None):
        sftp = self.host.sftpClient()

        # From http://downloads.sourceforge.net/project/lmbench/development/lmbench-3.0-a9/lmbench-3.0-a9.tgz
        lmbenchFilename = "lmbench.tgz"
        lmbenchSrc = "%s/%s" % (self.instFiledir, lmbenchFilename)
        lmbenchDest = "/root/%s" % lmbenchFilename

        # Install lmbench
        sftp.copyTo(lmbenchSrc, lmbenchDest)
        output = self.host.execdom0("tar xvfz /root/lmbench.tgz")
        xenrt.TEC().logverbose("output: %s" % output)
        output = self.host.execdom0("tar xvfz /root/lmbench/lmbench-3.0-a9.tgz")
        xenrt.TEC().logverbose("output: %s" % output)
        instDir = "/root/lmbench-3.0-a9"

        # Install make, gcc
        extraargs = ""
        if xenrt.productLib(host=self.host) == xenrt.lib.xenserver:
            extraargs = "--disablerepo=citrix --enablerepo=base,updates"
        cmds = [
            "yum %s install -y make" % extraargs,
            "yum %s install -y gcc" % extraargs,
        ]
        for cmd in cmds:
            output = self.host.execdom0(cmd)
            xenrt.TEC().logverbose("output: %s" % output)

        # Run the script which tells us what OS name lmbench will use -- normally "i686-pc-linux-gnu" in 32-bit dom0
        # (Note: the output from this script is different depending on pwd! Run from within scripts directory.)
        osName = self.host.execdom0("cd %s/scripts && ./os" % instDir).strip()
        xenrt.TEC().logverbose("lmbench calls the dom0 OS '%s'" % osName)

        # Install the config file
        configDestDir = "%s/bin/%s" % (instDir, osName)
        configDest = "%s/CONFIG.%s" % (configDestDir, self.host.getName())
        self.host.execdom0("mkdir -p %s" % configDestDir)
        self.host.execdom0("cp /root/lmbench/lmbench.config %s" % configDest)

        # Install the info file
        self.host.execdom0("cp %s/scripts/info-template %s/INFO.q9" % (instDir, configDestDir)) # "INFO.q9" because this is what is specified in the CONFIG file

        substitutions = [
            "s/^MB=[0-9]*$/MB=%d/" % self.mb,        # Tweak the 'MB' parameter
            "s/^OS=\"[^\"]*\"$/OS=\"%s\"/" % osName, # Tweak the 'OS' parameter
            ]

        # Perform substitutions on config file
        for sub in substitutions:
            self.host.execdom0("sed -i '%s' %s" % (sub, configDest))

        # Run the benchmark (repeatedly)
        cmds = ["make rerun"] * self.runs # use "rerun" rather than "results" so it picks up the existing CONFIG file
        for cmd in cmds:
            output = self.host.execdom0("cd %s && %s" % (instDir, cmd), timeout=7200)
            xenrt.TEC().logverbose("output: %s" % output)

        # Get the output
        remoteOutdir = "%s/results/%s" % (instDir, osName)
        self.host.execdom0("cd %s; for file in *; do newname=`echo $file | sed 's/^.*\./iter-/'`; mkdir $newname; ln -s ../$file $newname/results.log; done" % remoteOutdir)
        xenrt.TEC().logverbose("copying outdir %s to logs" % remoteOutdir)
        sftp.copyTreeFromRecurse(remoteOutdir, xenrt.TEC().getLogdir())
        xenrt.TEC().logverbose("copied outdir to logs")

    def postRun(self):
        self.finishUp()

