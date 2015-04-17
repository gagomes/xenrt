import xenrt

from zope.interface import implements


class HostWrapper(object):
    implements(xenrt.interfaces.OSParent)

    def __init__(self, host):
        self.host = host
        self.os = None

    @property
    def name(self):
        return self.host.name

    @property
    def hypervisorType(self):
        return xenrt.HypervisorType.native

    def poll(self, state, timeout=600, level=xenrt.RC_FAIL, pollperiod=15):
        """Poll for reaching the specified state"""
        raise xenrt.XRTError("Not supported")

    def getIP(self, trafficType=None, timeout=600, level=xenrt.RC_ERROR):
        return self.host.getIP()

    def getIPAndPort(self, trafficType, timeout=600, level=xenrt.RC_ERROR):
        return (self.host.getIP(), self.os.tcpCommunicationPorts[trafficType])

    def getPort(self, trafficType):
        return self.os.tcpCommunicationPorts[trafficType]

    def setIP(self, ip):
        raise xenrt.XRTError("Not implemented")

    def start(self, on=None, timeout=600):
        raise xenrt.XRTError("Not implemented")

    def setIso(self, isoName, isoRepo=None):
        raise xenrt.XRTError("Not implemented")

    def ejectIso(self):
        raise xenrt.XRTError("Not implemented")

__all__ = ["HostWrapper"]
