import xenrt
import libperf
import string
import os.path
from libperf import PerfTestCase

# Broken. (Windows XP template can't be found.)
class TCTimeHVMLinuxWorkload(PerfTestCase):

    def __init__(self):
        PerfTestCase.__init__(self, "TCTimeHVMLinuxWorkload")
        # TODO: Replace with argument.
        self.numdesktops = 20 # 800 = 16 hosts x 50 VMs

    def createlinuxhvm(self, host):
        xenrt.TEC().logverbose("creating Linux HVM guest...")

        linuxhvm = host.guestFactory()(\
            "linuxhvm", host.chooseTemplate("TEMPLATE_NAME_WINDOWS_XP"))
        linuxhvm.windows = False
        linuxhvm.setMemory(256)
        method = "HTTP"
        repository = xenrt.getLinuxRepo("rhel5", "x86-32", method)
        linuxhvm.install(host,
                         distro="rhel5",
                         repository=repository,
                         method=method,
                         pxe=True,
                         extrapackages=["dosfstools"],
                         sr=sruuid)
        linuxhvm.check()
        xenrt.TEC().registry.guestPut("linuxhvm", linuxhvm)

        ltmp = string.strip(linuxhvm.execguest("mktemp -d /tmp/XXXXXX"))
        lsftp = linuxhvm.sftpClient()
        lsftp.copyTo("%s/api/rhel5/ocaml-3.09.1-1.2.el5.rf.i386.rpm" %
                     (xenrt.TEC().getWorkdir()),
                     "%s/ocaml-3.09.1-1.2.el5.rf.i386.rpm" % (ltmp))
        linuxhvm.execguest("rpm --install "
                           "%s/ocaml-3.09.1-1.2.el5.rf.i386.rpm"
                           % (ltmp))
        for f in glob.glob(linuxagentsrc):
            lsftp.copyTo(f, "%s/%s" % (ltmp, os.path.basename(f)))
        if linuxagentmake:
            linuxhvm.execguest("make -C %s" % (ltmp))
            linuxhvm.execguest("cp %s/gtserver /root/gtserver" %
                               (ltmp))
        else:
            linuxhvm.execguest("cd %s; "
                               "ocamlc -o /root/gtserver unix.cma"
                               " gtmessages.ml gtcomms.ml "
                               " gtlinuxops.ml "
                               " gtserver_linux.ml" % (ltmp))
        linuxhvm.execguest("chmod 755 /root/gtserver")
        linuxhvm.execguest("echo 'exec /root/gtserver &' >> "
                           "/etc/rc.local")
        linuxhvm.execguest("/sbin/chkconfig iptables off || true")

        return linuxhvm

    def prepare(self, arglist=None):
        # Parse generic arguments
        self.parseArgs(arglist)

        # Parse arguments relating to this test
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "numdesktops":
                self.numdesktops = int(l[1])

        self.initialiseHostList()
        self.configureAllHosts()

        # TODO create an HVM linux guest
        self.goldvm = self.createlinuxhvm(self.host)

    def run(self, arglist=None):
        # Create the clones, recording how long it takes to do so
        self.clones = self.createMPSVMs(self.numdesktops, self.goldvm)
        self.configureAllVMs()

        # Kick off a process in each


    def postRun(self):
        self.finishUp()
