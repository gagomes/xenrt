import xenrt, os.path, os, shutil
from xenrt.lib.opsys import LinuxOS, registerOS
from xenrt.linuxanswerfiles import DebianPreseedFile
from abc import ABCMeta, abstractproperty
from zope.interface import implements

__all__ = ["DebianLinux", "UbuntuLinux"]

class DebianBasedLinux(LinuxOS):

    implements(xenrt.interfaces.InstallMethodPV, xenrt.interfaces.InstallMethodIsoWithAnswerFile)
    
    __metaclass__ = ABCMeta

    @abstractproperty
    def _mappings(self): 
        """A set of mappings for the distro"""
        pass

    @staticmethod
    def testInit(parent): raise NotImplementedError()

    def __init__(self, distro, parent):
        super(DebianBasedLinux, self).__init__(distro, parent)

        if distro.endswith("x86-32") or distro.endswith("x86-64"):
            self.distro = distro[:-7]
            self.arch = distro[-6:]
        else:
            self.distro = distro
            self.arch = "x86-64"

        self.pvBootArgs = ["console=hvc0"]
        self.cleanupdir = None

    @property
    def canonicalDistroName(self):
        return "%s_%s" % (self.distro, self.arch)

    @abstractproperty
    def isoName(self): pass

    @property
    def isoRepo(self):
        return "linux"

    @property
    def debianName(self):
        if self._mappings.has_key(self.distro):
            return self._mappings[self.distro]
        return None

    @property
    def installURL(self):
        return xenrt.TEC().lookup(["RPM_SOURCE", self.distro, self.arch, "HTTP"], None)

    @property
    def _architecture(self):
        """Convert the architecture post-fix to a string representing the installer base path"""
        if self.arch == "x86-32":
            return "i386"
        elif self.arch == "x86-64":
            return "amd64"
        else:
            raise xenrt.XRTError("Cannot identify architecture")

    @property
    def installerKernelAndInitRD(self):

        darch = self._architecture

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

    def preCloneTailor(self):
        return

    def generateIsoAnswerfile(self):
        preseedfile = "preseed-%s.cfg" % (self.parent.name)
        filename = "%s/%s" % (xenrt.TEC().getLogdir(), preseedfile)
        ps = DebianPreseedFile(self.distro,
                               xenrt.TEC().lookup(["RPM_SOURCE", self.distro, self.arch, "HTTP"]),
                               filename,
                               arch=self.arch)
        ps.generate()
        installIP = self.parent.getIP(trafficType="OUTBOUND", timeout=600)
        path = "%s/%s" % (xenrt.TEC().lookup("GUESTFILE_BASE_PATH"), installIP)
        self.cleanupdir = path
        try:
            os.makedirs(path)
        except:
            pass
        xenrt.rootops.sudo("chmod -R a+w %s" % path)
        xenrt.command("rm -f %s/preseed.stamp" % path)
        shutil.copyfile(filename, "%s/preseed" % (path))

    def waitForIsoAnswerfileAccess(self):
        installIP = self.parent.getIP(trafficType="OUTBOUND", timeout=600)
        path = "%s/%s" % (xenrt.TEC().lookup("GUESTFILE_BASE_PATH"), installIP)
        filename = "%s/preseed.stamp" % path
        xenrt.waitForFile(filename, 1800)

    def cleanupIsoAnswerfile(self):
        if self.cleanupdir:
            shutil.rmtree(self.cleanupdir)
        self.cleanupdir = None

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
        self.parent.getIP(trafficType="SSH", timeout=timeout)
        # Reduce the timeout by however long it took to get the IP
        timeout -= (xenrt.util.timenow() - startTime)
        # Now wait for an SSH response in the remaining time
        self.waitForSSH(timeout)

class DebianLinux(DebianBasedLinux):
    implements(xenrt.interfaces.InstallMethodPV, xenrt.interfaces.InstallMethodIsoWithAnswerFile)
   
    @property
    def _mappings(self):
        return {"debian60": "squeeze",
                "debian70": "wheezy"}

    @staticmethod
    def knownDistro(distro):
        return distro.startswith("debian")
    
    @staticmethod
    def testInit(parent):
        return DebianLinux("debian70", parent)
    
    @property
    def isoName(self):
        if self.distro == "debian60":
            return "deb6_%s.iso" % self.arch
        elif self.distro == "debian70":
            return "deb7_%s.iso" % self.arch

class UbuntuLinux(DebianBasedLinux):
    """ NOTE: Lucid is not supported on XS 6.2 for ISO install but should work for http install"""
    implements(xenrt.interfaces.InstallMethodPV, xenrt.interfaces.InstallMethodIsoWithAnswerFile)
    
    @property
    def _mappings(self):
        return { "ubuntu1004": "lucid",
                 "ubuntu1204": "precise"}

    @staticmethod
    def knownDistro(distro):
        return distro.startswith("ubuntu")

    @staticmethod
    def testInit(parent):
        return UbuntuLinux("ubuntu1204", parent)

    @property
    def isoName(self):
        if self.distro == "ubuntu1004":
            return "ubuntu1004_%s.iso" % self.arch
        elif self.distro == "ubuntu1204":
            return "ubuntu1204_%s.iso" % self.arch


registerOS(DebianLinux)
registerOS(UbuntuLinux)
