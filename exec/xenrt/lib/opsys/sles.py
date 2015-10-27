import xenrt, os.path, os, shutil, re
from xenrt.lib.opsys import LinuxOS, registerOS
from xenrt.linuxanswerfiles import SLESAutoyastFile
from abc import ABCMeta, abstractproperty
from zope.interface import implements

__all__ = ["SLESLinux"]

class SLESBasedLinux(LinuxOS):

    implements(xenrt.interfaces.InstallMethodPV, xenrt.interfaces.InstallMethodIsoWithAnswerFile)
    
    __metaclass__ = ABCMeta

    def __init__(self, distro, parent, password=None):
        super(SLESBasedLinux, self).__init__(distro, parent, password)

        if distro.endswith("x86-32") or distro.endswith("x86-64"):
            self.distro = distro[:-7]
            self.arch = distro[-6:]
        else:
            self.distro = distro
            self.arch = "x86-64"

        self.pvBootArgs = ["console=tty0"]
        self.cleanupdir = None
        self.nfsdir = None

    @property
    def canonicalDistroName(self):
        return "%s_%s" % (self.distro, self.arch)
    
    @property
    def _maindisk(self):
        if self.parent.hypervisorType == xenrt.HypervisorType.xen:
            return "xvda"
        else:
            return "sda"

    @property
    def isoRepo(self):
        return "linux"

    @property
    def _defaultIsoName(self):
        return "%s_%s_xenrtinst.iso" % (self.distro, self.arch)

    @property
    def installURL(self):
        return xenrt.getLinuxRepo( self.distro, self.arch, "HTTP", None)

    @property
    def installerKernelAndInitRD(self):
        basePath = "%s/isolinux" % (self.installURL)
        return ("%s/vmlinuz" % (basePath), "%s/initrd.img" % basePath)

    def preCloneTailor(self):
        # TODO - see objects.py
        return

    def generateAnswerfile(self, webdir):
        """Generate an answerfile and put it in the provided webdir, returning any command line arguments needed to boot the OS"""
        autoyastfile = "autoyast-%s.cfg" % (self.parent.name)
        filename = "%s/%s" % (xenrt.TEC().getLogdir(), autoyastfile)
        xenrt.TEC().logverbose("FILENAME %s"%filename)
        
        self.nfsdir = xenrt.NFSDirectory()  
        ayf= SLESAutoyastFile(self.distro,
                             self.nfsdir.getMountURL(""),
                             self._maindisk,
                             installOn=self.parent.hypervisorType,
                             pxe=False)
#                             rebootAfterInstall = False)

        ay = ayf.generate()
        f = file(filename, "w")
        f.write(ay)
        f.close()

        webdir.copyIn(filename)
        url = webdir.getURL(os.path.basename(filename))

        # TODO: handle native where console is different, and handle other interfaces
        return ["graphical", "utf8", "ks=%s" % url]
       
    def generateIsoAnswerfile(self):
        autoyastfile = "autoyast-%s.cfg" % (self.parent.name)
        filename = "%s/%s" % (xenrt.TEC().getLogdir(), autoyastfile)
        xenrt.TEC().logverbose("FILENAME %s"%filename)
        self.nfsdir = xenrt.NFSDirectory()  
        ayf= SLESAutoyastFile(self.distro,
                             self.nfsdir.getMountURL(""),
                             self._maindisk,
                             installOn=self.parent.hypervisorType,
                             pxe=False)
#                             rebootAfterInstall = False)

        ay = ayf.generate()
        f = file(filename, "w")
        f.write(ay)
        f.close()

        installIP = self.getIP(trafficType="OUTBOUND", timeout=600)
        path = "%s/%s" % (xenrt.TEC().lookup("GUESTFILE_BASE_PATH"), installIP)
        
        self.cleanupdir = path
        try:
            os.makedirs(path)
        except:
            pass
        xenrt.rootops.sudo("chmod -R a+w %s" % path)
        xenrt.command("rm -f %s/autoyast.stamp" % path)
        shutil.copyfile(filename, "%s/autoyast" % (path))

    def waitForIsoAnswerfileAccess(self):
        installIP = self.getIP(trafficType="OUTBOUND", timeout=600)
        path = "%s/%s" % (xenrt.TEC().lookup("GUESTFILE_BASE_PATH"), installIP)
        filename = "%s/autoyast.stamp" % path
        xenrt.waitForFile(filename, 1800)

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

        xenrt.waitForFile("%s/.xenrtsuccess" % (self.nfsdir.path()),
                              installtime,
                              desc="SUSE based installation")
        if 'sles10' in self.distro:
            xenrt.TEC().logverbose("Sleeping for 240secs before removing iso")
            xenrt.sleep(240)
        else:
            self.parent.stop()
            self.parent.pollOSPowerState(xenrt.PowerState.down, timeout=1800)
        if self.installMethod == xenrt.InstallMethod.IsoWithAnswerFile:
            self.cleanupIsoAnswerfile()
            self.parent.ejectIso()
        if not 'sles10' in self.distro:
            self.parent.startOS()
            self.waitForBoot(600)

    def waitForBoot(self, timeout):
        # We consider boot of a RHEL guest complete once it responds to SSH
        startTime = xenrt.util.timenow()
        self.getIP(trafficType="SSH", timeout=timeout)
        # Reduce the timeout by however long it took to get the IP
        timeout -= (xenrt.util.timenow() - startTime)
        # Now wait for an SSH response in the remaining time
        self.waitForSSH(timeout)

    @classmethod
    def osDetected(cls, parent, password):
        return (False, password)

class SLESLinux(SLESBasedLinux):
    implements(xenrt.interfaces.InstallMethodPV, xenrt.interfaces.InstallMethodIsoWithAnswerFile)
    
    @staticmethod
    def knownDistro(distro):
        return distro.startswith("sles")

    @staticmethod
    def testInit(parent):
        return SLESLinux("sles10", parent)

    @property
    def isoName(self):
        if not SLESLinux.knownDistro(self.distro):
            return None
        return self._defaultIsoName

    @classmethod
    def osDetected(cls, parent, password):
        obj=cls("testsuse", parent, password)
        if obj.execSSH("test -e /etc/SuSE-release", retval="code") == 0:
            release = obj.execSSH("cat /etc/SuSE-release")

            releaseMatch = re.search("VERSION = (\d+)", release)
            patchMatch = re.search("PATCHLEVEL = (\d+)", release)

            if releaseMatch:
                ret = "sles"
                ret += releaseMatch.group(1)
                if patchMatch and patchMatch.group(1) != "0":
                    ret += patchMatch.group(1)
                return ("%s_%s" % (ret, obj.getArch()), password)

        return (False, password)

registerOS(SLESLinux)

