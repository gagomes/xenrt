from abc import ABCMeta, abstractmethod
import re
from xenrt.lazylog import log


class Controller(object):
    __metaclass__ = ABCMeta

    def __init__(self, host, vdiuuid=None):
        self._host = host
        self.__vdiuuid = vdiuuid

    def setVDIuuid(self, value):
        self.__vdiuuid = value

    def srTypeIsSupported(self):
        sr = self.srForGivenVDI()
        # Read cache only works for ext and nfs.
        return sr.srType() == 'nfs' or sr.srType() == 'ext'

    def srForGivenVDI(self):
        host = self._host.asXapiObject()
        return next((s for s in host.SR if self.vdiuuid in [v.uuid for v in s.VDIs]), None)

    @property
    def vdiuuid(self):
        return self.__vdiuuid

    @abstractmethod
    def isEnabled(self):
        pass

    @abstractmethod
    def enable(self):
        pass

    @abstractmethod
    def disable(self):
        pass


class XapiReadCacheController(Controller):

    def isEnabled(self):
        raise NotImplementedError()

    def enable(self):
        raise NotImplementedError()

    def disable(self):
        raise NotImplementedError()


class LowLevelReadCacheController(Controller):
    """
    If you're licensed and not disabled read caching then o_direct is off (RC is on)
    """
    __TAP_CTRL_FLAG = "read_caching"
    __RC_FLAG = "o_direct"

    def _searchForFlag(self, data, flag):
        regex = """[\"]*%s[\"]*: (?P<flagValue>[\w\"]+)""" % flag
        match = re.search(regex, data)
        if match:
            return match.group("flagValue").strip().replace('\"', '') == "true"
        return False

    def __fetchTapCtlFields(self, host):
        regex = re.compile("""{0}=(\w+) {1}=(\w+) {2}=(\w+) {3}=(.*)""".format("pid", "minor", "state", "args"))
        data = host.execdom0("tap-ctl list | cat")
        return regex.findall(data)

    def __getPidAndMinor(self):
        for pid, minor, state, args in self.__fetchTapCtlFields(self._host):
            if self.vdiuuid in args:
                return pid, minor
        raise RuntimeError("No PID and minor found for vdi %s" % self.vdiuuid)

    def isEnabled(self):
        pid, minor = self.__getPidAndMinor()
        readCacheDump = self._host.execdom0("tap-ctl stats -p %s -m %s" % (pid, minor))
        return self._searchForFlag(readCacheDump, self.__TAP_CTRL_FLAG)

    def enable(self):
        if self.srTypeIsSupported():
            sr = self.srForGivenVDI()
            # When o_direct is not defined, it is on by default.
            if self.__RC_FLAG in self._host.genParamGet("sr", sr.uuid, "other-config"):
                self._host.genParamRemove("sr", sr.uuid, "other-config", self.__RC_FLAG)

    def disable(self):
        if self.srTypeIsSupported():
            sr = self.srForGivenVDI()
            oc = self._host.genParamGet("sr", sr.uuid, "other-config")
            # When o_direct is not defined, it is on by default.
            if self.__RC_FLAG not in oc or 'true' not in self._host.genParamGet("sr", sr.uuid, "other-config", self.__RC_FLAG):
                self._host.genParamSet("sr", sr.uuid, "other-config", "true", self.__RC_FLAG)


class ReadCachingController(Controller):
    """
    Proxy certain methods for the other controller classes
    """
    def __init__(self, guest):
        self.__xapi = self.XapiReadCacheController(guest)
        self.__ll = self.LowLevelReadCacheController(guest)

    def isEnabled(self, LowLevel=False):
        if LowLevel:
            return self.__ll.isEnabled()
        return self.__xapi.isEnabled()

    def enable(self, LowLevel=False):
        if LowLevel:
            return self.__ll.enable()
        return self.__xapi.enable()

    def disable(self, LowLevel=False):
        if LowLevel:
            return self.__ll.disable()
        self.__xapi.disable()
