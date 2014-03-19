import xenrt, os.path, os, shutil
from xenrt.lib.opsys import LinuxOS, RegisterOS
from xenrt.linuxanswerfiles import DebianPreseedFile
from zope.interface import implements

__all__ = ["DebianBasedLinux"]

class DebianBasedLinux(LinuxOS):

    debianMappings = {"debian60": "squeeze",
                      "debian70": "wheezy"}

    implements(xenrt.interfaces.InstallMethodPV, xenrt.interfaces.InstallMethodIsoWithAnswerFile)

    @staticmethod
    def KnownDistro(distro):
        if distro.startswith("debian") or distro.startswith("ubuntu"):
            return True
        else:
            return False

    @staticmethod
    def testInit():
        return DebianBasedLinux("debian70", None)

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
    def debianName(self):
        if self.debianMappings.has_key(self.distro):
            return self.debianMappings[self.distro]
        return None

    @property
    def installURL(self):
        return xenrt.TEC().lookup(["RPM_SOURCE", self.distro, self.arch, "HTTP"], None)

    @property
    def installerKernelAndInitRD(self):
        if self.arch == "x86-32":
            darch = "i386"
        elif self.arch == "x86-64":
            darch = "amd64"
        else:
            raise xenrt.XRTError("Cannot identify architecture")

        # 32-bit Xen guests need to use a special installer kernel, 64-bit and non-Xen we
        # can just use the standard as PVops support works
        if self.arch == "x86-32" and self.parent.hypervisorType == xenrt.HypervisorType.xen:
            basePath = "%s/dists/%s/main/installer-%s/current/images/netboot/xen" % \
                       (self.installURL,
                        self.debianName,
                        darch)
            kernelName = "vmlinuz"
        else:
            basePath = "%s/dists/%s/main/installer-%s/current/images/netboot/debian-installer/%s" % \
                       (self.installURL,
                        self.debianName,
                        darch,
                        darch)
            kernelName = "linux"
        return ("%s/%s" % (basePath, kernelName), "%s/initrd.gz" % basePath)

    def generateAnswerfile(self, webdir):
        """Generate an answerfile and put it in the provided webdir, returning any command line arguments needed to boot the OS"""
        preseedfile = "preseed-%s.cfg" % (self.parent.name)
        filename = "%s/%s" % (xenrt.TEC().getLogdir(), preseedfile)

        # TODO: Use new signalling method so this works for hosts as well
        ps=DebianPreseedFile(self.distro,
                             self.installURL,
                             filename,
                             arch=self.arch)
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
    def defaultRootdisk(self):
        return 8 * xenrt.GIGA

    def waitForInstallCompleteAndFirstBoot(self):
        # Install is complete when the guest shuts down
        # TODO: Use the signalling mechanism instead
        self.parent.poll(xenrt.PowerState.down, timeout=1800)
        if self.installMethod == xenrt.InstallMethod.IsoWithAnswerFile:
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
