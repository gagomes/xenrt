from abc import ABCMeta, abstractproperty, abstractmethod
import re

__all__ = ["WorkloadBalancing", "ReadCaching",
           "VirtualGPU", "Hotfixing", "ExportPoolResourceList",
           "GPUPassthrough"]


class LicensedFeature(object):

    """
    Class to check the licensing and actual state of a sepcific feature
    """
    __metaclass__ = ABCMeta

    @abstractmethod
    def isEnabled(self, host):
        """
        Is the feature programmatically enabled on the server side
        @rtype boolean list
        """
        pass

    @abstractproperty
    def featureFlagName(self):
        """
        What is the name of the feature flag
        @rtype string
        """
        pass

    def hostFeatureFlagValue(self, host):
        """
        What is the value of the host's feature flag
        @rtype boolean
        """
        cli = host.getCLIInstance()
        data = cli.execute("host-license-view",
                           "host-uuid=%s" % (host.getMyHostUUID()))
        return self._searchForFlag(data, self.featureFlagName)

    def _searchForFlag(self, data, flag):
        """ Regex here matches:
            "my_flag": "my_data" <-TapCtl Formatted JSON
            my_flag: my_data <- xapi formatted
            and mixtures of the two
        """
        regex = """[\"]*%s[\"]*: (?P<flagValue>[\w\"]+)""" % flag
        match = re.search(regex, data)
        if match:
            return match.group("flagValue").strip().replace('\"', '') == "true"
        return False

    def poolFeatureFlagValue(self, pool):
        """
        What is the value of the host's feature flag
        @rtype boolean
        """
        poolParams = pool.getPoolParam("restrictions")
        return self._searchForFlag(poolParams, self.featureFlagName)

    @property
    def stateCanBeChecked(self):
        """
        Can the enabled state be checked? Maybe false is this
        is a flagged UI feature
        @rtype boolean
        """
        return True


class WorkloadBalancing(LicensedFeature):

    def isEnabled(self, host):
        raise NotImplementedError()

    @property
    def featureFlagName(self):
        return "restrict_wlb"

    @property
    def stateCanBeChecked(self):
        return False


class ReadCaching(LicensedFeature):

    __TAP_CTRL_FLAG = "read_caching"

    def __fetchPidAndMinor(self, host):
        regex = re.compile("""{0}=(\w+) {1}=(\w+)""".format("pid", "minor"))
        data = host.execdom0("tap-ctl list | cat")
        return regex.findall(data)

    def isEnabled(self, host):
        pidAndMinors = self.__fetchPidAndMinor(host)
        output = []
        for pid, minor in pidAndMinors:
            readCacheDump = host.execdom0("tap-ctl stats -p %s -m %s" % (pid, minor))
            output.append(self._searchForFlag(readCacheDump, self.__TAP_CTRL_FLAG))
        return output

    @property
    def featureFlagName(self):
        return "restrict_read_caching"


class VirtualGPU(LicensedFeature):

    def isEnabled(self, host):
        [vm.reboot() for vm in host.guests.values()]
        return [vm.getState() == "UP" for vm in host.guests.values()]

    @property
    def featureFlagName(self):
        return "restrict_vgpu"


class GPUPassthrough(VirtualGPU):

    @property
    def featureFlagName(self):
        return "restrict_gpu"


class Hotfixing(LicensedFeature):

    def isEnabled(self, host):
        raise NotImplementedError()

    @property
    def featureFlagName(self):
        return "restrict_hotfix_apply"

    @property
    def stateCanBeChecked(self):
        return False


class ExportPoolResourceList(LicensedFeature):

    def isEnabled(self, host):
        raise NotImplementedError()

    @property
    def featureFlagName(self):
        return "restrict_export_resource_data"

    @property
    def stateCanBeChecked(self):
        return False
