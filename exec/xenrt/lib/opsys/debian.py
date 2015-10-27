import xenrt, os.path, os, shutil, IPy, re
from xenrt.lib.opsys import LinuxOS, registerOS
from xenrt.linuxanswerfiles import DebianPreseedFile
from zope.interface import implements

__all__ = ["DebianLinux", "UbuntuLinux"]

class DebianBasedLinux(LinuxOS):

    implements(xenrt.interfaces.InstallMethodPV, xenrt.interfaces.InstallMethodIsoWithAnswerFile)
    

    def _mappings(self): 
        """A set of mappings for the distro"""
        pass

    def testInit(parent): raise NotImplementedError()

    def __init__(self, distro, parent, password=None):
        super(DebianBasedLinux, self).__init__(distro, parent, password)

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
        return xenrt.getLinuxRepo(self.distro, self.arch, "HTTP", None)

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
                               xenrt.getLinuxRepo(self.distro, self.arch, "HTTP"),
                               filename,
                               arch=self.arch)
        ps.generate()
        installIP = self.getIP(trafficType="OUTBOUND", timeout=600)
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
        installIP = self.getIP(trafficType="OUTBOUND", timeout=600)
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
        self.parent.pollOSPowerState(xenrt.PowerState.down, timeout=1800)
        if self.installMethod == xenrt.InstallMethod.IsoWithAnswerFile:
            self.cleanupIsoAnswerfile()
            self.parent.ejectIso()
        self.parent.startOS()
        self.waitForBoot(600)

    def waitForBoot(self, timeout):
        # We consider boot of a Debian guest complete once it responds to SSH
        startTime = xenrt.util.timenow()
        self.getIP(trafficType="SSH", timeout=timeout)
        # Reduce the timeout by however long it took to get the IP
        timeout -= (xenrt.util.timenow() - startTime)
        # Now wait for an SSH response in the remaining time
        self.waitForSSH(timeout)

    def setIPs(self, ipSpec):
        ifs = []
        ifcfgs = []
        for i in ipSpec:
            (eth, ip, masklen) = i
            ifs.append(eth)
            if ip:
                mask = IPy.IP("0.0.0.0/%s" % masklen).netmask().strNormal()
                ifcfgs.append("iface %s inet static\n\taddress %s\n\tnetmask %s\n" % (eth, ip, mask))
            else:
                ifcfgs.append("iface %s inet dhcp\n" % eth)

        content = "auto lo %s\n\n" % " ".join(ifs)
        content += "iface lo inet loopback\n\n"
        content += "\n".join(ifcfgs)
        sftp = self.sftpClient()
        f = xenrt.TEC().tempFile()
        with open(f, "w") as fh:
            fh.write(content)
        sftp.copyTo(f, "/etc/network/interfaces")
        self.execSSH("ifup -a")
        # Check we haven't broken networking
        self.execSSH("true")

    @classmethod
    def osDetected(cls, parent, password):
        obj=cls("testdeb", parent, password)
        return (obj.execSSH("test -e /etc/debian_version", retval="code") == 0, password)

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
            return "deb6_%s_xenrtinst.iso" % self.arch
        elif self.distro == "debian70":
            return "deb7_%s_xenrtinst.iso" % self.arch
        elif self.distro == "debian80":
            return "deb8_%s_xenrtinst.iso" % self.arch

    @classmethod
    def osDetected(cls, parent, password):
        obj=cls("testdeb", parent, password)
        isUbuntu = obj.execSSH("grep Ubuntu /etc/lsb-release", retval="code") == 0
        if isUbuntu:
            return (False, password)
        else:
            release = obj.execSSH("cat /etc/debian_version").strip()
            release = release.split(".")[0]
            if re.match("^debian\d+$", release):
                return ("debian%s0_%s" % (release, obj.getArch()), password)
            else:
                return (False, password)

class UbuntuLinux(DebianBasedLinux):
    """ NOTE: Lucid is not supported on XS 6.2 for ISO install but should work for http install"""
    implements(xenrt.interfaces.InstallMethodPV, xenrt.interfaces.InstallMethodIsoWithAnswerFile)
    
    @property
    def _mappings(self):
        return { "ubuntu1004": "lucid",
                 "ubuntu1204": "precise",
                 "ubuntu1404": "trusty"}

    @staticmethod
    def knownDistro(distro):
        return distro.startswith("ubuntu")

    @staticmethod
    def testInit(parent):
        return UbuntuLinux("ubuntu1204", parent)

    @property
    def isoName(self):
        return "%s_%s_xenrtinst.iso" % (self.distro, self.arch)

    @classmethod
    def osDetected(cls, parent, password):
        obj=cls("testdeb", parent, password)
        isUbuntu = obj.execSSH("grep Ubuntu /etc/lsb-release", retval="code") == 0
        if not isUbuntu:
            return (False, password)
        else:
            release = obj.execSSH("cat /etc/lsb-release | grep DISTRIB_RELEASE | cut -d = -f 2 | tr -d .")
            if re.match("^ubuntu\d+$", release):
                return ("ubuntu%s0_%s" % (release, obj.getArch()), password)
            else:
                return (False, password)

registerOS(DebianLinux)
registerOS(UbuntuLinux)
