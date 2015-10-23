import xenrt
from zope.interface import implements, providedBy
from abc import abstractproperty

oslist = []


class OS(object):
    implements(xenrt.interfaces.OS)

    _allInstallMethods = {xenrt.interfaces.InstallMethodPV: xenrt.InstallMethod.PV,
                          xenrt.interfaces.InstallMethodIso: xenrt.InstallMethod.Iso,
                          xenrt.interfaces.InstallMethodIsoWithAnswerFile: xenrt.InstallMethod.IsoWithAnswerFile}

    def __init__(self, distro, parent, password=None):
        self.parent = xenrt.interfaces.OSParent(parent)
        self.distro = distro
        self.password = password
        self.viridian = False
        self.__installMethod = None

    def tailor(self):
        pass

    @abstractproperty
    def canonicalDistroName(self):
        pass
    
    def findPassword(self):
        """Try some passwords to determine which to use"""
        return

    def populateFromExisting(self):
        pass

    @property
    def installMethod(self):
        return self.__installMethod

    @installMethod.setter
    def installMethod(self, value):
        assert value in self.supportedInstallMethods
        self.__installMethod = value

    @property
    def supportedInstallMethods(self):
        # We base this on interfaces
        interfaces = providedBy(self)
        return [method for intf, method in self._allInstallMethods.items() if intf in interfaces]

    @staticmethod
    def knownDistro(distro):
        return False

    def assertHealthy(self, quick=False):
        raise xenrt.XRTError("Not implemented")

    def getLogs(self, path):
        pass

    def setIPs(self, ipSpec):
        raise xenrt.XRTError("Not implemented")

def registerOS(os):
    oslist.append(os)


def osFactory(distro, parent, password=None):
    for o in oslist:
        if o.knownDistro(distro):
            return o(distro, parent, password)
    raise xenrt.XRTError("No class found for distro %s" % distro)

__all__ = ["OS", "registerOS"]

from xenrt.lib.opsys.linux import *
from xenrt.lib.opsys.debian import *
from xenrt.lib.opsys.windows import *
from xenrt.lib.opsys.windowspackages import *
from xenrt.lib.opsys.rhel import *
from xenrt.lib.opsys.sles import *
from xenrt.lib.opsys.xs import *
