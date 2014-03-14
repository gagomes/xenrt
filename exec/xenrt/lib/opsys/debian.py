import xenrt, os.path, os, shutil
from xenrt.lib.opsys import LinuxOS, RegisterOS
from xenrt.linuxanswerfiles import DebianPreseedFile

__all__ = ["DebianBasedLinux"]

class DebianBasedLinux(LinuxOS):

    @staticmethod
    def KnownDistro(distro):
        if distro.startswith("debian") or distro.startswith("ubuntu"):
            return True
        else:
            return False

    def __init__(self, distro, parent):
        super(self.__class__, self).__init__(parent)

        if distro.endswith("x86-32") or distro.endswith("x86-64"):
            self.distro = distro[:-7]
            self.arch = distro[-6:]
        else:
            self.distro = distro
            self.arch = "x86-64"

        self.pvBootArgs = ["console=hvc0"]
        self.cleanupdir = None

        # TODO: Validate distro
        # TODO: Look up / work out URLs, don't just hard code!

    @property
    def isoName(self):
        if self.distro == "debian60":
            return "deb6_%s.iso" % self.arch
        elif self.distro == "debian70":
            return "deb7_%s.iso" % self.arch

    @property
    def isoRepo(self):
        return "linux"

    @property
    def installURL(self):
        return "http://10.220.160.11/vol/xenrtdata/linux/distros/Debian/Wheezy/all/"

    @property
    def installerKernelAndInitRD(self):
        return ("http://10.220.160.11/vol/xenrtdata/linux/distros/Debian/Wheezy/all/dists/wheezy/main/installer-amd64/current/images/netboot/debian-installer/amd64/linux",
                "http://10.220.160.11/vol/xenrtdata/linux/distros/Debian/Wheezy/all/dists/wheezy/main/installer-amd64/current/images/netboot/debian-installer/amd64/initrd.gz")

    def generateAnswerfile(self, webdir):
        """Generate an answerfile and put it in the provided webdir, returning any command line arguments needed to boot the OS"""
        preseedfile = "preseed-%s.cfg" % (self.parent.name)
        filename = "%s/%s" % (xenrt.TEC().getLogdir(), preseedfile)

        # TODO: Use new signalling method so this works for hosts as well
        ps=DebianPreseedFile(self.distro,
                             "http://10.220.160.11/vol/xenrtdata/linux/distros/Debian/Wheezy/all",
                             filename,
                             arch="x86-64")
        ps.generate()
        webdir.copyIn(filename)
        url = webdir.getURL(os.path.basename(filename))

        # TODO: handle native where console is different, and handle other interfaces
        return ["vga=normal", "auto=true priority=critical", "console=hvc0", "interface=eth0", "url=%s" % url]

    def generateIsoAnswerfile(self):
        preseedfile = "preseed-%s.cfg" % (self.parent.name)
        filename = "%s/%s" % (xenrt.TEC().getLogdir(), preseedfile)
        ps = DebianPreseedFile(self.distro,
                               xenrt.TEC().lookup(["RPM_SOURCE", self.distro, self.arch, "HTTP"]),
                               filename,
                               arch=self.arch)
        ps.generate()
        installIP = self.parent.getIP(600)
        path = "%s/%s" % (xenrt.TEC().lookup("GUESTFILE_BASE_PATH"), installIP)
        self.cleanupdir = path
        try:
            os.makedirs(path)
        except:
            pass
        shutil.copyfile(filename, "%s/preseed" % (path))

    def cleanupIsoAnswerfile(self):
        if self.cleanupdir:
            shutil.rmtree(self.cleanupdir)
        self.cleanupdir = None

    @property
    def supportedInstallMethods(self):
        return ["PV", "isowithanswerfile"]

    @property
    def defaultRootdisk(self):
        return 8 * xenrt.GIGA

    def waitForInstallCompleteAndFirstBoot(self):
        # Install is complete when the guest shuts down
        # TODO: Use the signalling mechanism instead
        self.parent.poll(xenrt.PowerState.down, timeout=1800)
        if self.installMethod == "isowithanswerfile":
            self.cleanupIsoAnswerfile()
            self.parent.ejectIso()
        self.parent.start()

    def waitForBoot(self, timeout):
        # We consider boot of a Debian guest complete once it responds to SSH
        startTime = xenrt.util.timenow()
        self.parent.getIP(timeout)
        # Reduce the timeout by however long it took to get the IP
        timeout -= (xenrt.util.timenow() - startTime)
        # Now wait for an SSH response in the remaining time
        self.waitForSSH(timeout)

RegisterOS(DebianBasedLinux)
