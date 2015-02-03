from abc import ABCMeta, abstractmethod
import re


class Controller(object):
    __metaclass__ = ABCMeta

    def __init__(self, host):
        self.__host = host
        self.__sruuids = []

    def setSruuidList(self, value):
        self.__sruuids = value

    def setSruuid(self, value):
        if value != None:
            self.setSruuidList([value])
        else:
            self.setSruuidList([])

    def sruuids(self):
        if self.__sruuids == None or len(self.__sruuids) < 1:
            self.__sruuids = self.__host.minimalList("sr-list")
        return self.__sruuids

    def srTypeIsSupported(self, sruuid):
        # Read cache only works for ext and nfs.
        srtype = self.__host.genParamGet("sr", sruuid, "type")
        return srtype == 'nfs' or srtype == 'ext'

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
    __TAP_CTRL_FLAG = "read_caching"
    __RC_FLAG = "o_direct"

    def __fetchPidAndMinor(self, host):
        regex = re.compile("""{0}=(\w+) {1}=(\w+)""".format("pid", "minor"))
        data = host.execdom0("tap-ctl list | cat")
        return regex.findall(data)

    def isEnabled(self):
        pidAndMinors = self.__fetchPidAndMinor(self.__host)
        output = []
        for pid, minor in pidAndMinors:
            readCacheDump = self.__host.execdom0("tap-ctl stats -p %s -m %s" % (pid, minor))
            output.append(self._searchForFlag(readCacheDump, self.__TAP_CTRL_FLAG))
        return output

    def enable(self):
        for sr in self.sruuids:
            if self.srTypeIsSupported(sr):
                # When o_direct is not defined, it is on by default.
                if self.__RC_FLAG in self.__host.genParamGet("sr", sr, "other-config"):
                    self.__host.genParamRemove("sr", sr, "other-config", self.__RC_FLAG)

    def disable(self):
        for sr in self.sruuids:
            if self.srTypeIsSupported(sr):
                oc = self.__host.genParamGet("sr", sr, "other-config")
                # When o_direct is not defined, it is on by default.
                if self.__RC_FLAG not in oc or 'true' not in self.__host.genParamGet("sr", sr, "other-config", self.__RC_FLAG):
                    self.__host.genParamSet("sr", sr, "other-config", "true", self.__RC_FLAG)


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
