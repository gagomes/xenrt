import xenrt
import os.path
import os
import shutil
import re
from xenrt.lib.opsys import LinuxOS, registerOS, OSNotDetected
from zope.interface import implements


__all__ = ["CoreOSLinux"]


class CoreOSLinux(LinuxOS):
    """CoreOS Linux (cannot be installed through OS class)"""

    def __init__(self, distro, parent, password=None):
        super(CoreOSLinux, self).__init__(distro, parent, password)
        self.distro = distro
        self.arch = "x86-64"

    @property
    def canonicalDistroName(self):
        return "%s_%s" % (self.distro, self.arch)
    
    @property
    def _maindisk(self):
        if self.parent._osParent_hypervisorType == xenrt.HypervisorType.xen:
            return "xvda"
        else:
            return "sda"

    @property
    def isoRepo(self):
        return "linux"

    @property
    def defaultRootdisk(self):
        return 5 * xenrt.GIGA

    @property
    def defaultMemory(self):
        return 1024

    def waitForBoot(self, timeout):
        # We consider boot of a CoreOS guest complete once it responds to SSH
        startTime = xenrt.util.timenow()
        self.getIP(trafficType="SSH", timeout=timeout)
        # Reduce the timeout by however long it took to get the IP
        timeout -= (xenrt.util.timenow() - startTime)
        # Now wait for an SSH response in the remaining time
        self.waitForSSH(timeout)

    @staticmethod
    def knownDistro(distro):
        return distro.startswith("coreos")

    @staticmethod
    def testInit(parent):
        return CoreOSLinux("coreos", parent)

    @classmethod
    def detect(cls, parent, detectionState):
        obj=cls("testcoreos", parent, detectionState.password)
        if obj.execSSH("grep NAME=CoreOS /etc/os-release", retval="code") == 0:
            return cls("coreos_x86-64", parent, obj.password)
        else:
            raise OSNotDetected("OS it not CoreOS")
        
registerOS(CoreOSLinux)
