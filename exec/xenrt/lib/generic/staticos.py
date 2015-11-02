import xenrt

from zope.interface import implements


class StaticOS(object):
    implements(xenrt.interfaces.OSParent)

    def __init__(self, distro, ip):
        self.distro = distro
        self.mainip = ip

        self.os = xenrt.lib.opsys.osFactory(self.distro, self)

    @property
    def name(self):
        return "Static-%s" % self.mainip

    @property
    def hypervisorType(self):
        return None

    def pollOSPowerState(self, state, timeout=600, level=xenrt.RC_FAIL, pollperiod=15):
        """Poll for reaching the specified state"""
        raise xenrt.XRTError("Not supported")

    def getIP(self, trafficType=None, timeout=600, level=xenrt.RC_ERROR):
        return self.mainip

    def getPort(self, trafficType):
        return None

    def setIP(self, ip):
        raise xenrt.XRTError("Not implemented")

    def startOS(self):
        raise xenrt.XRTError("Not implemented")

    def setIso(self, isoName, isoRepo=None):
        raise xenrt.XRTError("Not implemented")

    def ejectIso(self):
        raise xenrt.XRTError("Not implemented")

__all__ = ["StaticOS"]
