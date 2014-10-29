from abc import ABCMeta, abstractproperty


class LicencedFeature(object):
    """
    Class to check the licensing and actual state of a sepcific feature
    """
    __metaclass__ = ABCMeta

    @abstractproperty
    def isEnabled(self):
        pass

    @abstractproperty
    def isFeatureFlagSet(self):
        pass


class WorkloadBalancing(LicencedFeature):

    def isEnabled(self):
        raise NotImplementedError()

    def isFeatureFlagSet(self):
        raise NotImplementedError()


class ReadCaching(LicencedFeature):

    def isEnabled(self):
        raise NotImplementedError()

    def isFeatureFlagSet(self):
        raise NotImplementedError()


class VirtualGPU(LicencedFeature):

    def isEnabled(self):
        raise NotImplementedError()

    def isFeatureFlagSet(self):
        raise NotImplementedError()


class Hotfixing(LicencedFeature):

    def isEnabled(self):
        raise NotImplementedError()

    def isFeatureFlagSet(self):
        raise NotImplementedError()




