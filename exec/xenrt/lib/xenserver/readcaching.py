from abc import ABCMeta, abstractmethod
import re

class Controller(object):
    __metaclass__ = ABCMeta

    def __init__(self, host):
        self.__host = host

    @abstractmethod
    def isEnabled(self):
        pass

    @abstractmethod
    def enable(self):
        pass

    @abstractmethod
    def disable(self):
        pass


class _XapiReadCacheController(Controller):

    def isEnabled(self):
        pass


    def enable(self):
        pass


    def disable(self):
        pass


class _LowLevelReadCacheController(Controller):
    __TAP_CTRL_FLAG = "read_caching"

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
        pass

    def disable(self):
        pass



class ReadCachingController(Controller):
    """
    Proxy for the other controller classes
    """
    def __init__(self, guest):
        self.__xapi = self._XapiReadCacheController(guest)
        self.__ll = self._LowLevelReadCacheController(guest)


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
        return self.__xapi.disable()