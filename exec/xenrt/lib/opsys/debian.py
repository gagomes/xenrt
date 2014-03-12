import xenrt, os.path
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

        self.distro = distro
        self.pvBootArgs = ["console=hvc0"]

        # TODO: Validate distro
        # TODO: Look up / work out URLs, don't just hard code!

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

    @property
    def supportedInstallMethods(self):
        return ["PV"]

    @property
    def defaultRootdisk(self):
        return 8 * xenrt.GIGA

    def waitForInstallCompleteAndFirstBoot(self):
        # Install is complete when the guest shuts down
        # TODO: Use the signalling mechanism instead
        self.parent.poll(xenrt.State.down, timeout=1800)
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
