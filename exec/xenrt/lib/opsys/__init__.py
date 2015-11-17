import xenrt
from zope.interface import implements, providedBy
from abc import abstractproperty, abstractmethod, ABCMeta

class abstractstatic(staticmethod):
    __slots__ = ()
    def __init__(self, function):
        super(abstractstatic, self).__init__(function)
        function.__isabstractmethod__ = True
    __isabstractmethod__ = True

oslist = []

class OSNotDetected(Exception):
    def __init__(self, msg):
        self.msg = msg

class OS(object):
    __metaclass__ = ABCMeta

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
        """Canonical distro name"""
        pass

    @abstractproperty
    def defaultRootdisk(self):
        """Default rootdisk size"""
        pass

    @abstractproperty
    def defaultVcpus(self):
        """Default number of vCPUs"""
        pass

    @abstractproperty
    def defaultMemory(self):
        """Default memory size"""
        pass

    @abstractproperty
    def tcpCommunicationPorts(self):
        """TCP ports needed for inbound communication, of type {name:port}"""
        pass

    @abstractmethod
    def waitForBoot(self, timeout):
        """Wait for the OS to boot"""
        pass
    
    @abstractstatic
    def testInit(parent):
        """Instantiate a dummy version for unit testing"""
        pass

    @abstractmethod
    def reboot(self):
        """Perform an OS-initiated reboot"""
        pass

    @abstractmethod
    def shutdown(self):
        """Perform an OS-initiated shutdown"""
        pass

    @abstractmethod
    def assertHealthy(self, quick):
        """(Quickly) verifies that the OS is in a healthy state"""
        pass

    def findPassword(self):
        """Try some passwords to determine which to use"""
        return

    def getIP(self, trafficType=None, timeout=600, level=xenrt.RC_ERROR):
        return self.parent._osParent_getIP(trafficType, timeout, level)

    def getPort(self, trafficType):
        return self.parent._osParent_getPort(trafficType) or self.tcpCommunicationPorts[trafficType]

    def populateFromExisting(self):
        """Populate class members from an existing OS installation"""
        pass

    @property
    def installMethod(self):
        """Selected installation method"""
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
    def runDetect(cls, parent, detectionState):
        # Call runDetect on the base class (stop if we reach a class without a runDetect method)
        base = cls.__bases__[0]
        if hasattr(base, "runDetect"):
            base.runDetect(parent, detectionState)
        # Assuming the base class check was successful, check this class
        # If we've previosly checked this class, don't do it again
        if str(cls) in detectionState.checked.keys():
            if detectionState.checked[str(cls)]:
                # This has previously passed the test of a non-leaf OS class, so return None
                return None
            else:
                raise OSNotDetected("%s check already failed" % str(cls))
        else:
            xenrt.TEC().logverbose("Checking %s" % str(cls))
            try:
                ret = cls.detect(parent, detectionState)
            except OSNotDetected, e:
                xenrt.TEC().logverbose("OS is not %s - %s" % (str(cls), e.msg))
                # If we can't detect this OS, raise an exception to terminate the hierarchy
                detectionState.checked[str(cls)] = False
                raise
            else:
                detectionState.checked[str(cls)] = True
                return ret
        

    @classmethod
    def detect(cls, parent, detectionState):
        """Return an instance of a leaf OS class if detected, or None for non-leaf OS classes if detectd.
        Raise OSNotDetected if OS is not detected"""
        pass

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

class DetectionState(object):
    def __init__(self, password):
        self.checked = {}
        self.password = password

def osFromExisting(parent, password=None):
    detectionState = DetectionState(password)
    for o in oslist:
        try:
            ret = o.runDetect(parent, detectionState)
        except OSNotDetected:
            continue
        else:
            xenrt.xrtAssert(ret, "No object returned for detected OS")
            return ret
    raise xenrt.XRTError("Could not determine OS")

__all__ = ["OS", "registerOS"]

from xenrt.lib.opsys.linux import *
from xenrt.lib.opsys.debian import *
from xenrt.lib.opsys.windows import *
from xenrt.lib.opsys.windowspackages import *
from xenrt.lib.opsys.rhel import *
from xenrt.lib.opsys.sles import *
from xenrt.lib.opsys.xs import *
