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

    @property
    def stateCanBeChecked(self):
        return False

class ReadCaching(LicencedFeature):

    def isEnabled(self):
        """Checks all VBDs to see if read caching is disabled.
        If all VBDs have read caching disabled, returns True.
        If any VBDs with read caching enabled, returns False.
        If there are no VBDs, returns True.
        """
        readCacheDump = self.execdom0("tap-ctl list | cat")

        # If no VBD, have no way of knowing if it is enabled.
        if readCacheDump is "":
            # Some exception.
            pass

        if readCacheDump[0].split(" ")[-1].split("=")[0] is not "read_caching":
            # This version of Creedence does not implement hook for read caching.
            # Some exception.
            pass

        results = []
        for line in readCacheDump.split("\n"):
            results.append(line.split(" ")[-1].split("=")[-1])

        # List of 1s and 0s
        # 0 = Disabled, 1 = Enabled.
        for i in results:
            if i is "1":
                return False
        return True

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
