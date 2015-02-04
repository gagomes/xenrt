from abc import ABCMeta, abstractmethod
import re


class Controller(object):
    __metaclass__ = ABCMeta

    def __init__(self, host):
        self.__host = host
        self.__vdiuuids = []

    def setVDIuuidList(self, value):
        self.__vdiuuids = value

    def setVDIuuid(self, value):
        if value != None:
            self.setVDIuuidList([value])
        else:
            self.setVDIuuidList([])

    def srTypeIsSupported(self, vdiuuid):
        sr = self.srForGivenVDI(vdiuuid)
        # Read cache only works for ext and nfs.
        return sr.srType() == 'nfs' or sr.srType() == 'ext'

    def srForGivenVDI(self, vdiuuid):
        host = self.__host.asXapiObject()
        return next((s for s in host.SR if vdiuuid in [v.uuid for v in s.VDIs]), None)

    @property
    def vdiuuids(self):
        return self.__vdiuuids

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
        regex = re.compile("""{0}=(\w+) {1}=(\w+) {2}=(\w+)""".format("pid", "minor", "args"))
        data = host.execdom0("tap-ctl list | cat")
        return regex.findall(data)

    def __getVDIuuidFromTapCtlArgs(self, args):
        if not args.startswith("vhd"):
            raise ValueError("Couldn't parse non-vhd data: %s" % args)
        return '-'.join(args.split('/')[-1].split('-')[1:])

    def isEnabled(self):
        output = skipped = []
        for pid, minor, args in self.__fetchTapCtlFields(self.__host):
            vdiuuid = self.__getVDIuuidFromTapCtlArgs(args)
            if vdiuuid in self.vdiuuids:
                readCacheDump = self.__host.execdom0("tap-ctl stats -p %s -m %s" % (pid, minor))
                output.append(self._searchForFlag(readCacheDump, self.__TAP_CTRL_FLAG))
            else:
                skipped.append(vdiuuid)

        if len(skipped) == len(self.vdiuuids) and len(self.vdiuuids) > 0:
            raise RuntimeError("Skipped all vdis set in the controller: %s" % skipped)

        return output

    def enable(self):
        for vdi in self.vdiuuids:
            if self.srTypeIsSupported(vdi):
                sr = self.srForGivenVDI(vdi)
                # When o_direct is not defined, it is on by default.
                if self.__RC_FLAG in self.__host.genParamGet("sr", sr.uuid, "other-config"):
                    self.__host.genParamRemove("sr", sr.uuid, "other-config", self.__RC_FLAG)

    def disable(self):
        for vdi in self.vdiuuids:
            if self.srTypeIsSupported(vdi):
                sr = self.srForGivenVDI(vdi)
                oc = self.__host.genParamGet("sr", sr.uuid, "other-config")
                # When o_direct is not defined, it is on by default.
                if self.__RC_FLAG not in oc or 'true' not in self.__host.genParamGet("sr", sr.uuid, "other-config", self.__RC_FLAG):
                    self.__host.genParamSet("sr", sr.uuid, "other-config", "true", self.__RC_FLAG)


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
