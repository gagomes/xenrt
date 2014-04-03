import xenrt, os.path, os, shutil
from xenrt.lib.opsys import LinuxOS, registerOS
from xenrt.linuxanswerfiles import RHELKickStartFile
from abc import ABCMeta, abstractproperty
from zope.interface import implements

__all__ = ["RHELLinux", "CentOSLinux", "OELLinux"]

class RHELBasedLinux(LinuxOS):

    implements(xenrt.interfaces.InstallMethodPV, xenrt.interfaces.InstallMethodIsoWithAnswerFile)
    
    __metaclass__ = ABCMeta

    @staticmethod
    def knownDistro(distro): raise NotImplementedError()

    @staticmethod
    def testInit(parent): raise NotImplementedError()

    def __init__(self, distro, parent):
        super(RHELBasedLinux, self).__init__(parent)

        if distro.endswith("x86-32") or distro.endswith("x86-64"):
            self.distro = distro[:-7]
            self.arch = distro[-6:]
        else:
            self.distro = distro
            self.arch = "x86-64"

        self.pvBootArgs = ["console=tty0"]
        self.cleanupdir = None
        self.nfsdir = None

        # TODO: Validate distro
        # TODO: Look up / work out URLs, don't just hard code!

    @abstractproperty
    def isoName(self): pass

    @abstractproperty
    def _maindisk(self): pass
    
    @property
    def isoRepo(self):
        return "linux"

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
        basePath = "%s/isolinux" % (self.installURL)
        return ("%s/vmlinuz" % (basePath), "%s/initrd.img" % basePath)

    def generateAnswerfile(self, webdir):
        """Generate an answerfile and put it in the provided webdir, returning any command line arguments needed to boot the OS"""
        preseedfile = "preseed-%s-kickstart.cfg" % (self.parent.name)
        filename = "%s/%s" % (xenrt.TEC().getLogdir(), preseedfile)
        
        self.nfsdir = xenrt.NFSDirectory()  
        ksf=RHELKickStartFile(self.distro,
                             self._maindisk,
                             self.nfsdir.getMountURL(""),
                             repository=self.installURL,
                             installOn=xenrt.HypervisorType.xen,
                             installXenToolsInPostInstall=True,
                             pxe=False,
                             arch=self.arch)

        ks = ksf.generate()
        f = file(filename, "w")
        f.write(ks)
        f.close()

        webdir.copyIn(filename)
        url = webdir.getURL(os.path.basename(filename))

        # TODO: handle native where console is different, and handle other interfaces
        return ["graphical", "utf8", "url=%s" % url]
       
    def generateIsoAnswerfile(self):
        preseedfile = "preseed-%s-kickstart.cfg" % (self.parent.name)
        filename = "%s/%s" % (xenrt.TEC().getLogdir(), preseedfile)
        
        self.nfsdir = xenrt.NFSDirectory()  
        ksf=RHELKickStartFile(self.distro,
                             self._maindisk,
                             self.nfsdir.getMountURL(""),
                             repository=self.installURL,
                             installOn=xenrt.HypervisorType.xen,
                             installXenToolsInPostInstall=True,
                             pxe=False,
                             arch=self.arch)

        ks = ksf.generate()
        f = file(filename, "w")
        f.write(ks)
        f.close()

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

        # Using the signalling mechanism to monitor for installation complete.
        if xenrt.TEC().lookup("EXTRA_TIME", False, boolean=True):
            installtime = 7200
        else:
            installtime = 3600
        try:
            xenrt.waitForFile("%s/.xenrtsuccess" % (self.nfsdir.path()),
                              installtime,
                              desc="RHEL based installation")
            self.parent.stop()
        except xenrt.XRTFailure, e:
            raise 
        
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

class RHELLinux(RHELBasedLinux):
    implements(xenrt.interfaces.InstallMethodPV, xenrt.interfaces.InstallMethodIsoWithAnswerFile)
   
    @staticmethod
    def knownDistro(distro):
        return distro.startswith("rhel")
    
    @staticmethod
    def testInit(parent):
        return RHELLinux("rhel6", parent)

    @property
    def _maindisk(self):
        if int(self.distro[4:5]) >= 6:
            return "xvda"

    @property
    def isoName(self):
        if self.distro == "rhel38":
            return "rhel38_%s.iso" % self.arch
        elif self.distro == "rhel41":
            return "rhel41_%s.iso" % self.arch
        elif self.distro == "rhel44":
            return "rhel44_%s.iso" % self.arch
        elif self.distro == "rhel45":
            return "rhel45_%s.iso" % self.arch
        elif self.distro == "rhel46":
            return "rhel46_%s.iso" % self.arch
        elif self.distro == "rhel47":
            return "rhel47_%s.iso" % self.arch
        elif self.distro == "rhel48":
            return "rhel48_%s.iso" % self.arch
        elif self.distro == "rhel5":
            return "rhel5_%s.iso" % self.arch
        elif self.distro == "rhel510":
            return "rhel510_%s.iso" % self.arch
        elif self.distro == "rhel51":
            return "rhel51_%s.iso" % self.arch
        elif self.distro == "rhel52":
            return "rhel52_%s.iso" % self.arch
        elif self.distro == "rhel53":
            return "rhel53_%s.iso" % self.arch
        elif self.distro == "rhel54":
            return "rhel54_%s.iso" % self.arch
        elif self.distro == "rhel55":
            return "rhel55_%s.iso" % self.arch
        elif self.distro == "rhel56":
            return "rhel56_%s.iso" % self.arch
        elif self.distro == "rhel57":
            return "rhel57_%s.iso" % self.arch
        elif self.distro == "rhel58":
            return "rhel58_%s.iso" % self.arch
        elif self.distro == "rhel59":
            return "rhel59_%s.iso" % self.arch
        elif self.distro == "rhel6":
            return "rhel6_%s.iso" % self.arch
        elif self.distro == "rhel61":
            return "rhel61_%s.iso" % self.arch
        elif self.distro == "rhel62":
            return "rhel62_%s.iso" % self.arch
        elif self.distro == "rhel63":
            return "rhel63_%s.iso" % self.arch
        elif self.distro == "rhel64":
            return "rhel64_%s.iso" % self.arch
        elif self.distro == "rhel65":
            return "rhel65_%s.iso" % self.arch

class CentOSLinux(RHELBasedLinux):
    implements(xenrt.interfaces.InstallMethodPV, xenrt.interfaces.InstallMethodIsoWithAnswerFile)
    
    @staticmethod
    def knownDistro(distro):
        return distro.startswith("centos")

    @staticmethod
    def testInit(parent):
        return CentOSLinux("centos6", parent)

    @property
    def _maindisk(self):
        if int(self.distro[6:7]) >= 6:
            return "xvda"

    @property
    def isoName(self):
        if self.distro == "centos43":
            return "centos43_%s.iso" % self.arch
        elif self.distro == "centos45":
            return "centos45_%s.iso" % self.arch
        elif self.distro == "centos46":
            return "centos46_%s.iso" % self.arch
        elif self.distro == "centos47":
            return "centos47_%s.iso" % self.arch
        elif self.distro == "centos48":
            return "centos48_%s.iso" % self.arch
        elif self.distro == "centos5":
            return "centos5_%s.iso" % self.arch
        elif self.distro == "centos510":
            return "centos510_%s.iso" % self.arch
        elif self.distro == "centos51":
            return "centos51_%s.iso" % self.arch
        elif self.distro == "centos52":
            return "centos52_%s.iso" % self.arch
        elif self.distro == "centos53":
            return "centos53_%s.iso" % self.arch
        elif self.distro == "centos54":
            return "centos54_%s.iso" % self.arch
        elif self.distro == "centos55":
            return "centos55_%s.iso" % self.arch
        elif self.distro == "centos56":
            return "centos56_%s.iso" % self.arch
        elif self.distro == "centos57":
            return "centos57_%s.iso" % self.arch
        elif self.distro == "centos58":
            return "centos58_%s.iso" % self.arch
        elif self.distro == "centos59":
            return "centos59_%s.iso" % self.arch
        elif self.distro == "centos6":
            return "centos6_%s.iso" % self.arch
        elif self.distro == "centos61":
            return "centos61_%s.iso" % self.arch
        elif self.distro == "centos62":
            return "centos62_%s.iso" % self.arch
        elif self.distro == "centos63":
            return "centos63_%s.iso" % self.arch
        elif self.distro == "centos64":
            return "centos64_%s.iso" % self.arch
        elif self.distro == "centos65":
            return "centos65_%s.iso" % self.arch

class OELLinux(RHELBasedLinux):
    implements(xenrt.interfaces.InstallMethodPV, xenrt.interfaces.InstallMethodIsoWithAnswerFile)
   
    @staticmethod
    def knownDistro(distro):
        return distro.startswith("oel")
    
    @staticmethod
    def testInit(parent):
        return OELLinux("oel6", parent)

    @property
    def _maindisk(self):
        if int(self.distro[3:4]) >= 6:
            return "xvda"

    @property
    def isoName(self):
        if self.distro == "oel510":
            return "oel510_%s.iso" % self.arch
        if self.distro == "oel53":
            return "oel53_%s.iso" % self.arch
        if self.distro == "oel54":
            return "oel54_%s.iso" % self.arch
        if self.distro == "oel55":
            return "oel55_%s.iso" % self.arch
        if self.distro == "oel56":
            return "oel56_%s.iso" % self.arch
        if self.distro == "oel57":
            return "oel57_%s.iso" % self.arch
        if self.distro == "oel58":
            return "oel58_%s.iso" % self.arch
        if self.distro == "oel59":
            return "oel59_%s.iso" % self.arch
        if self.distro == "oel6":
            return "oel6_%s.iso" % self.arch
        if self.distro == "oel61":
            return "oel61_%s.iso" % self.arch
        if self.distro == "oel62":
            return "oel62_%s.iso" % self.arch
        if self.distro == "oel63":
            return "oel63_%s.iso" % self.arch
        if self.distro == "oel64":
            return "oel64_%s.iso" % self.arch
        if self.distro == "oel65":
            return "oel65_%s.iso" % self.arch

registerOS(RHELLinux)
registerOS(CentOSLinux)
registerOS(OELLinux)

