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

    def __str__(self):
        return "SKU: %s; Edition: %s; FileName: %s; LicenceServerName: %s" % (self.sku,
                                                                              self.getEdition(),
                                                                              self.getLicenceFileName(),
                                                                              self.getLicenceName())


class CreedenceLicence(Licence):

    def getEdition(self):
        if self.sku == XenServerLicenceSKU.PerUserEnterprise or \
           self.sku == XenServerLicenceSKU.PerConcurrentUserEnterprise:
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
            return "valid-enterprise-persocket.lic"
        if self.sku == XenServerLicenceSKU.PerUserEnterprise:
            return "valid-enterprise-peruser.lic"
        if self.sku == XenServerLicenceSKU.PerConcurrentUserEnterprise:
            return "valid-enterprise-perccu.lic"
        if self.sku == XenServerLicenceSKU.XenDesktopPlatinum:
            return "valid-xendesktop"
        if self.sku == XenServerLicenceSKU.PerSocketStandard:
            return "valid-standard-persocket.lic"
        if self.sku == XenServerLicenceSKU.PerUserStandard:
            return "valid-standard-peruser.lic"
        if self.sku == XenServerLicenceSKU.PerConcurrentUserStandard:
            return "valid-standard-perccu.lic"
        if self.sku == XenServerLicenceSKU.Free:
            return None
        if self.sku == XenServerLicenceSKU.PerSocket:
            return "valid-persocket.lic"
        raise ValueError("No license file name found for the SKU %s" % self.sku)

    def getLicenceName(self):
        if self.sku == XenServerLicenceSKU.PerSocketEnterprise:
            return "CXS_ENT2_CCS"
        if self.sku == XenServerLicenceSKU.PerUserEnterprise:
            return "CXS_ENT2_UD"
        if self.sku == XenServerLicenceSKU.PerConcurrentUserEnterprise:
            return "CXS_ENT2_CCU"
        if self.sku == XenServerLicenceSKU.XenDesktopPlatinum:
            return "XDS_STD_CCS"
        if self.sku == XenServerLicenceSKU.PerSocketStandard:
            return "CXS_STD2_CCS"
        if self.sku == XenServerLicenceSKU.PerUserStandard:
            return "CXS_STD2_UD"
        if self.sku == XenServerLicenceSKU.PerConcurrentUserStandard:
            return "CXS_STD2_CCU"
        if self.sku == XenServerLicenceSKU.Free:
            return None
        if self.sku == XenServerLicenceSKU.PerSocket:
            return "CXS_STD_CCS"
        raise ValueError("No license server name found for the SKU %s" % self.sku)
