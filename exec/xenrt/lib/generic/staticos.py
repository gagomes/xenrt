import xenrt

from zope.interface import implements


class StaticOS(object):
    implements(xenrt.interfaces.OSParent)

    def __init__(self, distro, ip):
        self.distro = distro
        self.mainip = ip

        self.os = xenrt.lib.opsys.osFactory(self.distro, self)

    @property
    @xenrt.irregularName
    def _osParent_name(self):
        return "Static-%s" % self.mainip

    @property
    @xenrt.irregularName
    def _osParent_hypervisorType(self):
        return None

    @xenrt.irregularName
    def _osParent_pollPowerState(self, state, timeout=600, level=xenrt.RC_FAIL, pollperiod=15):
        """Poll for reaching the specified state"""
        raise xenrt.XRTError("Not supported")

    @xenrt.irregularName
    def _osParent_getIP(self, trafficType=None, timeout=600, level=xenrt.RC_ERROR):
        return self.mainip

    @xenrt.irregularName
    def _osParent_getPort(self, trafficType):
        return None

    @xenrt.irregularName
    def _osParent_getPowerState(self):
        raise xenrt.XRTError("Not implemented")

    @xenrt.irregularName
    def _osParent_setIP(self, ip):
        raise xenrt.XRTError("Not implemented")

    @xenrt.irregularName
    def _osParent_start(self):
        raise xenrt.XRTError("Not implemented")

    @xenrt.irregularName
    def _osParent_stop(self):
        raise xenrt.XRTError("Not implemented")

    @xenrt.irregularName
    def _osParent_setIso(self, isoName, isoRepo=None):
        raise xenrt.XRTError("Not implemented")

    @xenrt.irregularName
    def _osParent_ejectIso(self):
        raise xenrt.XRTError("Not implemented")

__all__ = ["StaticOS"]
