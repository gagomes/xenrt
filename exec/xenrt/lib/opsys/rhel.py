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
    def _maindisk(self): pass

    @property
    def isoRepo(self):
        return "linux"

    @property
    def isoName(self):
        return "%s_%s.iso" % (self.distro, self.arch)

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
        kickstartfile = "kickstart-%s.cfg" % (self.parent.name)
        filename = "%s/%s" % (xenrt.TEC().getLogdir(), kickstartfile)
        
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
        kickstartfile = "kickstart-%s.cfg" % (self.parent.name)
        filename = "%s/%s" % (xenrt.TEC().getLogdir(), kickstartfile)
        
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
        shutil.copyfile(filename, "%s/kickstart" % (path))

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
        # We consider boot of a RHEL guest complete once it responds to SSH
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

registerOS(RHELLinux)
registerOS(CentOSLinux)
registerOS(OELLinux)

