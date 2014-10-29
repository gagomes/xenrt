from abc import ABCMeta, abstractproperty


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

    @property
    def featureFlagValue(self):
        """
        What is the value of feature flag
        @rtype boolean
        """
        pass

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

    def featureFlagName(self):
        raise NotImplementedError()


class ReadCaching(LicencedFeature):

    def isEnabled(self):
        raise NotImplementedError()

    def featureFlagName(self):
        raise NotImplementedError()


class VirtualGPU(LicencedFeature):

    def isEnabled(self):
        raise NotImplementedError()

    def featureFlagName(self):
        raise NotImplementedError()


class Hotfixing(LicencedFeature):

    def isEnabled(self):
        raise NotImplementedError()

    def featureFlagName(self):
        raise NotImplementedError()

    @property
    def stateCanBeChecked(self):
        return False


class ExportPoolResourceList(LicencedFeature):

    def isEnabled(self):
        raise NotImplementedError()

    def featureFlagName(self):
        raise NotImplementedError()

    @property
    def stateCanBeChecked(self):
        return False
