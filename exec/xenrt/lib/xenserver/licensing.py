from xenrt.enum import XenServerLicenceSKU
from abc import ABCMeta, abstractmethod

__all__ = ["CreedenceLicence"]

class Licence(object):
    __metaclass__ = ABCMeta

    def __init__(self, sku):
        self.__sku = sku

    @property
    def sku(self):
        """
        The SKU
        @rtype string (from XenServerLicenceSKU enum)
        """
        return self.__sku

    @abstractmethod
    def getEdition(self):
        """
        Edition used by xapi for the given sku
        @rtype string
        """
        pass

    @abstractmethod
    def getLicenceFileName(self):
        """
        File name for the given SKU
        @rtype string
        """
        pass

    @abstractmethod
    def getLicenceName(self):
        """
        License servers understanding of a given SKU
        @rtype string
        """
        pass


class CreedenceLicence(Licence):

    def getEdition(self):
        if self.sku == XenServerLicenceSKU.PerUserEnterprise or \
           self.sku == XenServerLicenceSKU.PerConcurrentUserEnterprise :
            return "enterprise-per-user"
        if self.sku == XenServerLicenceSKU.PerSocketEnterprise or \
           self.sku == XenServerLicenceSKU.PerSocket:
            return "enterprise-per-socket"
        if self.sku == XenServerLicenceSKU.XenDesktopPlatinum:
            return "xendesktop-platinum"
        if self.sku == XenServerLicenceSKU.PerSocketStandard:
            return "standard-per-socket"
        if self.sku == XenServerLicenceSKU.PerUserStandard or \
           self.sku == XenServerLicenceSKU.PerConcurrentUserStandard:
            return "standard-per-user"
        if self.sku == XenServerLicenceSKU.Free:
            return "free"
        raise ValueError("No edition found for the SKU %s" % self.sku)

    def getLicenceFileName(self):
        if self.sku == XenServerLicenceSKU.PerSocketEnterprise:
            return "licence.lic"
        if self.sku == XenServerLicenceSKU.PerUserEnterprise:
            return "licence.lic"
        if self.sku == XenServerLicenceSKU.PerConcurrentUserEnterprise:
            return "licence.lic"
        if self.sku == XenServerLicenceSKU.XenDesktopPlatinum:
            return "licence.lic"
        if self.sku == XenServerLicenceSKU.PerSocketStandard:
            return "licence.lic"
        if self.sku == XenServerLicenceSKU.PerUserStandard:
            return "licence.lic"
        if self.sku == XenServerLicenceSKU.PerConcurrentUserStandard:
            return "licence.lic"
        if self.sku == XenServerLicenceSKU.Free:
            return "licence.lic"
        if self.sku == XenServerLicenceSKU.PerSocket:
            return "licence.lic"
        raise ValueError("No license file name found for the SKU %s" % self.sku)

    def getLicenceName(self):
        if self.sku == XenServerLicenceSKU.PerSocketEnterprise:
            return "XSC_CCD"
        if self.sku == XenServerLicenceSKU.PerUserEnterprise:
            return "XSC_CCD"
        if self.sku == XenServerLicenceSKU.PerConcurrentUserEnterprise:
            return "XSC_CCD"
        if self.sku == XenServerLicenceSKU.XenDesktopPlatinum:
            return "XSC_CCD"
        if self.sku == XenServerLicenceSKU.PerSocketStandard:
            return "XSC_CCD"
        if self.sku == XenServerLicenceSKU.PerUserStandard:
            return "XSC_CCD"
        if self.sku == XenServerLicenceSKU.PerConcurrentUserStandard:
            return "XSC_CCD"
        if self.sku == XenServerLicenceSKU.Free:
            return "XSC_CCD"
        if self.sku == XenServerLicenceSKU.PerSocket:
            return "XSC_CCD"
        raise ValueError("No license server name found for the SKU %s" % self.sku)