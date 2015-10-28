import re
import itertools
from xenrt.lazylog import log


class ReadCachingController(object):
    """
    If you're licensed and not disabled read caching then o_direct is off (RC is on)
    """
    __TAP_CTRL_FLAG = "read_caching"
    __RC_FLAG = "o_direct"

    def __init__(self, host, vdiuuid=None):
        self._host = host
        self.__vdiuuid = vdiuuid

    @property
    def vdiuuid(self):
        return self.__vdiuuid

    def setVDIuuid(self, value):
        log("VDI uuid %s has been set" % value)
        self.__vdiuuid = value

    def setVM(self, vm, vdiIndex=0):
        self.setVDIuuid(vm.xapiObject.VDIs[vdiIndex].uuid)

    def srTypeIsSupported(self):
        sr = self.srForGivenVDI()
        # Read cache only works for ext, nfs and cifs.
        return sr.srType in ('nfs', 'ext', 'cifs')

    def srForGivenVDI(self):
        xhost = self._host.xapiObject
        return next((s for s in xhost.localSRs if self.vdiuuid in [v.uuid for v in s.VDIs]), None)

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

    def __lowLevelIsEnabled(self):
        pid, minor = self.__getPidAndMinor()
        readCacheDump = self._host.execdom0("tap-ctl stats -p %s -m %s" % (pid, minor))
        return self._searchForFlag(readCacheDump, self.__TAP_CTRL_FLAG)

    def __xapiIsEnabled(self):
        xhost = self._host.xapiObject
        vdis = list(itertools.chain(*[s.VDIs for s in xhost.localSRs]))
        vdi = next((v for v in vdis if v.uuid == self.vdiuuid), None)
        if not vdi:
            raise RuntimeError("VDI with uuid %s could not be found in the list %s" % (self.vdiuuid, vdis))
        return vdi.readcachingEnabled(xhost)

    def isEnabled(self, lowLevel=False):
        if lowLevel:
            return self.__lowLevelIsEnabled()
        return self.__xapiIsEnabled()

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
