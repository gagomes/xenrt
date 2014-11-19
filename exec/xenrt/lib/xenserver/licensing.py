from xenrt.enum import XenServerLicenceSKU
from abc import ABCMeta, abstractmethod

__all__ = ["CreedenceLicence", "TampaLicence", "ClearwaterLicence", "XenServerLicenceFactory"]


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


"""
PLACEHOLDER CLASS
"""
class TampaLicence(Licence):
    def getEdition(self):
        return "licence"

    def getLicenceFileName(self):
        return "licence.lic"

    def getLicenceName(self):
        return "CXS_some_thing"


"""
PLACEHOLDER CLASS
"""
class ClearwaterLicence(Licence):
    def getEdition(self):
        return "licence"

    def getLicenceFileName(self):
        return "licence.lic"

    def getLicenceName(self):
        return "CXS_some_thing"


class CreedenceLicence(Licence):

    def getEdition(self):
        if self.sku == XenServerLicenceSKU.PerUserEnterprise or \
           self.sku == XenServerLicenceSKU.PerConcurrentUserEnterprise:
            return "enterprise-per-user"
        if self.sku == XenServerLicenceSKU.PerSocketEnterprise or \
           self.sku == XenServerLicenceSKU.PerSocket:
            return "enterprise-per-socket"
        if self.sku == XenServerLicenceSKU.XenDesktopPlatinum:
            return "xendesktop"
        if self.sku == XenServerLicenceSKU.PerSocketStandard:
            return "standard-per-socket"
        if self.sku == XenServerLicenceSKU.Free:
            return "free"
        raise ValueError("No edition found for the SKU %s" % self.sku)

    def getLicenceFileName(self):
        if self.sku == XenServerLicenceSKU.PerSocketEnterprise:
            return "valid-enterprise-persocket"
        if self.sku == XenServerLicenceSKU.PerUserEnterprise:
            return "valid-enterprise-peruser"
        if self.sku == XenServerLicenceSKU.PerConcurrentUserEnterprise:
            return "valid-enterprise-perccu"
        if self.sku == XenServerLicenceSKU.XenDesktopPlatinum:
            return "valid-xendesktop"
        if self.sku == XenServerLicenceSKU.PerSocketStandard:
            return "valid-standard-persocket"
        if self.sku == XenServerLicenceSKU.Free:
            return None
        if self.sku == XenServerLicenceSKU.PerSocket:
            return "valid-persocket"
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
        if self.sku == XenServerLicenceSKU.Free:
            return None
        if self.sku == XenServerLicenceSKU.PerSocket:
            return "CXS_STD_CCS"
        raise ValueError("No license server name found for the SKU %s" % self.sku)


class XenServerLicenceFactory(object):
    __TAM = "tampa"
    __CLR = "clearwater"
    __CRE = "creedence"

    def __getHostAge(self, xshost):
        return xshost.productVersion.lower()

    def xenserverOnlyLicences(self, xshost):
        lver = self.__getHostAge(xshost)
        if lver == self.__CRE:
            skus = [XenServerLicenceSKU.PerSocketEnterprise,
                    XenServerLicenceSKU.PerSocketStandard,
                    XenServerLicenceSKU.PerSocket]
            return [self.licence(xshost, s) for s in skus]

        raise ValueError("No licence object was found for the provided host version: %s" % xshost.productVersion)

    def allLicences(self, xshost):
        lver = self.__getHostAge(xshost)
        if lver == self.__CRE:
            skus = [XenServerLicenceSKU.PerSocketEnterprise, XenServerLicenceSKU.PerUserEnterprise,
                    XenServerLicenceSKU.PerConcurrentUserEnterprise, XenServerLicenceSKU.XenDesktopPlatinum,
                    XenServerLicenceSKU.PerSocketStandard, XenServerLicenceSKU.Free, XenServerLicenceSKU.PerSocket]
            return [self.licence(xshost, s) for s in skus]

        raise ValueError("No licence object was found for the provided host version: %s" % xshost.productVersion)

    def licence(self, xshost, sku):
        """
        Get the licence objects for a given host object
        """
        lver = self.__getHostAge(xshost)
        if lver == self.__TAM:
            return TampaLicence(sku)
        if lver == self.__CLR:
            return ClearwaterLicence(sku)
        if lver == self.__CRE:
            return CreedenceLicence(sku)
        raise ValueError("No licence object was found for the provided host version: %s" % xshost.productVersion)
