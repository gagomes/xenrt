from abc import ABCMeta, abstractproperty
import re

class LicencedFeature(object):
    """
    Class to check the licensing and actual state of a sepcific feature
    """
    __metaclass__ = ABCMeta

    @abstractproperty
    def isEnabled(self):
        """
        Is the feature programmatically enabled on the server side
        @rtype boolean
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
        data = cli.execute("host-license-view","host-uuid=%s" % (host.getMyHostUUID()))
        return self.__searchForRestriction(data)

    def __searchForRestriction(self, data):
        regex = "%s: (?P<flagValue>\w+)" % self.featureFlagName
        match = re.search(regex, data)
        if match:
            return match.group("flagValue").strip() == "true"
        return False

    def poolFeatureFlagValue(self, pool):
        """
        What is the value of the host's feature flag
        @rtype boolean
        """
        poolParams = pool.getPoolParam("restrictions")
        return self.__searchForRestriction(poolParams)

    @property
    def stateCanBeChecked(self):
        """
        Can the enabled state be checked? Maybe false is this is a flagged UI feature
        @rtype boolean
        """
        return True


class WorkloadBalancing(LicencedFeature):

    def isEnabled(self):
        raise NotImplementedError()

    @property
    def featureFlagName(self):
        return "restrict_wlb"


class ReadCaching(LicencedFeature):

    def isEnabled(self):
        raise NotImplementedError()

    @property
    def featureFlagName(self):
        return "restrict_read_caching"


class VirtualGPU(LicencedFeature):

    def isEnabled(self):
        raise NotImplementedError()

    @property
    def featureFlagName(self):
        return "restrict_vgpu"


class Hotfixing(LicencedFeature):

    def isEnabled(self):
        raise NotImplementedError()

    @property
    def featureFlagName(self):
        return "restrict_hotfix_apply"

    @property
    def stateCanBeChecked(self):
        return False


class ExportPoolResourceList(LicencedFeature):

    def isEnabled(self):
        raise NotImplementedError()

    @property
    def featureFlagName(self):
        return "restrict_export_resource_data"

    @property
    def stateCanBeChecked(self):
        return False
