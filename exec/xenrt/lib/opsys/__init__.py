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

    def getIP(self, trafficType=None, timeout=600, level=xenrt.RC_ERROR):
        return self.parent.getIP(trafficType, timeout, level)

    def getIPAndPort(self, trafficType, timeout=600, level=xenrt.RC_ERROR):
        return (self.getIP(trafficType, timeout, level), self.getPort(trafficType))

    def getPort(self, trafficType):
        return self.parent.getPort(trafficType) or self.tcpCommunicationPorts[trafficType]

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

    @classmethod
    def osDetected(cls, parent, password):
        """Return tuple of boolean (is this OS detected) and password"""
        return (True, password)

    @classmethod
    def detect(cls, parent, checked, password=None):
        if len(cls.__bases__) != 1:
            raise xenrt.XRTError("Multiple inheritance is not supported for OS classes")
        # Find out what the base class is
        base = cls.__bases__[0]
        mystr = "%s.%s" % (cls.__module__, cls.__name__)
        if mystr not in checked.keys():
            print "Checking %s" % mystr
            if base.__module__ == "__builtin__":
                # End condition of recursion
                baseret = True
            else:
                # Check the base class first
                (baseret, password) = base.detect(parent, checked, password)
            if baseret:
                # If the base class is detected, check this class
                (ret, password) = cls.osDetected(parent, password)
            else:
                ret = False
            # And update the cache
            checked[mystr] = ret
        return (checked[mystr], password)
                
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

def osFromExisting(parent, password=None):
    checked = {}
    for o in oslist:
        (detected, password) = o.detect(parent, checked, password)
        if detected:
            return o(detected, parent, password)

__all__ = ["OS", "registerOS"]

from xenrt.lib.opsys.linux import *
from xenrt.lib.opsys.debian import *
from xenrt.lib.opsys.windows import *
from xenrt.lib.opsys.windowspackages import *
from xenrt.lib.opsys.rhel import *
from xenrt.lib.opsys.sles import *
from xenrt.lib.opsys.xs import *
