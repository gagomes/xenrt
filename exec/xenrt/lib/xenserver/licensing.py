import xenrt
from xenrt.enum import XenServerLicenceSKU
from abc import ABCMeta, abstractmethod

__all__ = ["CreedenceLicence", "TampaLicence", "ClearwaterLicence", "XenServerLicenceFactory", "LicenceManager"]


class LicenceManager(object):
    def addLicensesToServer(self, v6, license,getLicenseInUse = True):
        licenseinUse = 0
        v6.addLicense(license.getLicenceFileName())
        if getLicenseInUse:
            totalLicenses, licenseinUse = v6.getLicenseInUse(license.getLicenceName())
        return licenseinUse

    def applyLicense(self, v6, hostOrPool, license,licenseinUse):
        hostOrPool.licenseApply(v6,license)
        self.verifyLicenseServer(license,v6,licenseinUse,hostOrPool) 

    def releaseLicense(self, hostOrPool):
        licence = XenServerLicenceFactory().licenceForPool(hostOrPool,XenServerLicenceSKU.Free)
        hostOrPool.licenseApply(None,licence)

    def verifyLicenseServer(self, license, v6, licenseinUse, hostOrPool, reset=False):

        if isinstance(hostOrPool,xenrt.lib.xenserver.Pool):
            productVersion = hostOrPool.master.productVersion
        else:
            productVersion = hostOrPool.productVersion
        xsOnlyLicences = XenServerLicenceFactory().xenserverOnlyLicences(productVersion)
        if not next((i for i in xsOnlyLicences if i.getEdition() == license.getEdition()), None):
            xenrt.TEC().logverbose("XD license is applied so no need to verify the license server")
            return

        tmp,currentLicinuse = v6.getLicenseInUse(license.getLicenceName())

        if reset:
            if licenseinUse != currentLicinuse:
                raise xenrt.XRTFailure("Not all the licenses are not returned to license server, current licenses in use %d" % (currentLicinuse))
            xenrt.TEC().logverbose("License server verified and correct no of licenses checked out")
            return

        if not ((hostOrPool.getNoOfSockets() + licenseinUse)  == currentLicinuse):
            raise xenrt.XRTFailure("No. of Licenses in use: %d, No. of socket in whole pool: %d" % (currentLicinuse, hostOrPool.getNoOfSockets()))

        xenrt.TEC().logverbose("License server verified and correct no of licenses checked out")


class Licence(object):
    __metaclass__ = ABCMeta

    def __init__(self, sku):
        self.sku = sku

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

    def verify(self):
        self.getEdition()
        self.getLicenceFileName()
        self.getLicenceName()

    def __str__(self):
        return "SKU: %s; Edition: %s; FileName: %s; LicenceServerName: %s" % (self.sku,
                                                                              self.getEdition(),
                                                                              self.getLicenceFileName(),
                                                                              self.getLicenceName())


class TampaLicence(Licence):

    def getEdition(self):
        if self.sku == XenServerLicenceSKU.XSPlatinum:
            return "platinum"
        if self.sku == XenServerLicenceSKU.XSEnterprise:
            return "enterprise"
        if self.sku == XenServerLicenceSKU.XSAdvance:
            return "advanced"
        if self.sku == XenServerLicenceSKU.XenDesktop:
            return "enterprise-xd"
        if self.sku == XenServerLicenceSKU.Free:
            return "free"
        raise ValueError("No edition found for the SKU %s" % self.sku)

    def getLicenceFileName(self):
        if self.sku == XenServerLicenceSKU.XSPlatinum:
            return "valid-platinum"
        if self.sku == XenServerLicenceSKU.XSEnterprise:
            return "valid-enterprise"
        if self.sku == XenServerLicenceSKU.XSAdvance:
            return "valid-advanced"
        if self.sku == XenServerLicenceSKU.XenDesktop:
            return "valid-enterprise-xd"
        if self.sku == XenServerLicenceSKU.Free:
            return None
        raise ValueError("No license file name found for the SKU %s" % self.sku)

    def getLicenceName(self):
        return

class ClearwaterLicence(Licence):
    
    def getEdition(self):
        if self.sku == XenServerLicenceSKU.PerSocket:
            return "per-socket"
        if self.sku == XenServerLicenceSKU.Free:
            return "free"
        if self.sku == XenServerLicenceSKU.XenDesktop:
            return "xendesktop"
        raise ValueError("No edition found for the SKU %s" % self.sku)

    def getLicenceFileName(self):
        if self.sku == XenServerLicenceSKU.PerSocket:
            return "valid-persocket"
        if self.sku == XenServerLicenceSKU.Free:
            return None
        if self.sku == XenServerLicenceSKU.XenDesktop:
            return "valid-enterprise-xd"
        raise ValueError("No license file name found for the SKU %s" % self.sku)

    def getLicenceName(self):

        if self.sku == XenServerLicenceSKU.PerSocket:
            return "CXS_STD_CCS"
        if self.sku == XenServerLicenceSKU.Free:
            return None
        if self.sku == XenServerLicenceSKU.XenDesktop:
            return "XDS_STD_CCS"
        raise ValueError("No license server name found for the SKU %s" % self.sku)  

class CreedenceLicence(Licence):

    def getEdition(self):
        if self.sku == XenServerLicenceSKU.PerUserEnterprise or \
           self.sku == XenServerLicenceSKU.PerConcurrentUserEnterprise:
            return "enterprise-per-user"
        if self.sku == XenServerLicenceSKU.PerSocketEnterprise or \
           self.sku == XenServerLicenceSKU.PerSocket:
            return "enterprise-per-socket"
        if self.sku == XenServerLicenceSKU.XenDesktop:
            return "desktop"
        if self.sku == XenServerLicenceSKU.PerSocketStandard:
            return "standard-per-socket"
        if self.sku == XenServerLicenceSKU.XenDesktopPlusXDS or \
            self.sku == XenServerLicenceSKU.XenDesktopPlusMPS:
            return "desktop-plus"
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
        if self.sku == XenServerLicenceSKU.XenDesktop:
            return "valid-xendesktop"
        if self.sku == XenServerLicenceSKU.PerSocketStandard:
            return "valid-standard-persocket"
        if self.sku == XenServerLicenceSKU.Free:
            return None
        if self.sku == XenServerLicenceSKU.PerSocket:
            return "valid-persocket"
        if self.sku == XenServerLicenceSKU.XenDesktopPlusXDS:
            return "valid-xendesktop-plus"
        if self.sku == XenServerLicenceSKU.XenDesktopPlusMPS:
            return "valid-xendesktop-plus-MPS"
        raise ValueError("No license file name found for the SKU %s" % self.sku)

    def getLicenceName(self):
        if self.sku == XenServerLicenceSKU.PerSocketEnterprise:
            return "CXS_ENT2_CCS"
        if self.sku == XenServerLicenceSKU.PerUserEnterprise:
            return "CXS_ENT2_UD"
        if self.sku == XenServerLicenceSKU.PerConcurrentUserEnterprise:
            return "CXS_ENT2_CCU"
        if self.sku == XenServerLicenceSKU.XenDesktop:
            return "XDS_STD_CCS"
        if self.sku == XenServerLicenceSKU.PerSocketStandard:
            return "CXS_STD2_CCS"
        if self.sku == XenServerLicenceSKU.Free:
            return None
        if self.sku == XenServerLicenceSKU.PerSocket:
            return "CXS_STD_CCS"
        if self.sku == XenServerLicenceSKU.XenDesktopPlusXDS:
            return "XDS_PLT_CCS"
        if self.sku == XenServerLicenceSKU.XenDesktopPlusMPS:
            return "MPS_PLT_CCU"
        raise ValueError("No license server name found for the SKU %s" % self.sku)


class XenServerLicenceFactory(object):
    __TAM = "tampa"
    __CLR = "clearwater"
    __CRE = "creedence"
    __SAN = "sanibel"
    __BOS = "boston"
    __COW = "cowley"
    __MNR = "mnr"
    __OXF = "oxford"

    def __getHostAge(self, xshost):
        return xshost.productVersion.lower()

    def xenserverOnlyLicencesForPool(self, xspool):
        return self.xenserverOnlyLicences(xspool.master.productVersion)

    def xenserverOnlyLicencesForHost(self, xshost):
        lver = self.__getHostAge(xshost)
        return self.xenserverOnlyLicences(lver)

    def xenserverOnlyLicences(self, productVersion):
        lver = productVersion.lower()
        if lver == self.__CRE:
            skus = [XenServerLicenceSKU.PerSocketEnterprise,
                    XenServerLicenceSKU.PerSocketStandard,
                    XenServerLicenceSKU.PerSocket]
            return [self.licence(lver, s) for s in skus]

        raise ValueError("No licence object was found for the provided host version: %s" % productVersion)

    def allLicencesForPool(self, xspool):
        lver = self.__getHostAge(xspool.master)
        return self.allLicences(lver)

    def allLicencesForHost(self, xshost):
        lver = self.__getHostAge(xshost)
        return self.allLicences(lver)

    def allLicences(self, productVersion):
        lver = productVersion.lower()
        if lver == self.__CRE:
            skus = [XenServerLicenceSKU.PerSocketEnterprise, XenServerLicenceSKU.PerUserEnterprise,
                    XenServerLicenceSKU.PerConcurrentUserEnterprise, XenServerLicenceSKU.XenDesktopPlatinum,
                    XenServerLicenceSKU.PerSocketStandard, XenServerLicenceSKU.Free, XenServerLicenceSKU.PerSocket]
            return [self.licence(lver, s) for s in skus]

        raise ValueError("No licence object was found for the provided host version: %s" % productVersion)

    def licenceForPool(self, xspool, sku):
        lver =self.__getHostAge(xspool.master)
        return self.licence(lver, sku)

    def licenceForHost(self, xshost, sku):
        lver = self.__getHostAge(xshost)
        return self.licence(lver, sku)

    def maxLicenceSkuHost(self,xshost):
        lver = self.__getHostAge(xshost)
        if lver == self.__TAM or lver == self.__SAN or lver == self.__BOS or lver == self.__COW or lver == self.__MNR or lver == self.__OXF:
            return TampaLicence(XenServerLicenceSKU.XSPlatinum)    
        if lver == self.__CLR:
            return ClearwaterLicence(XenServerLicenceSKU.PerSocket)
        if lver == self.__CRE:
            return CreedenceLicence(XenServerLicenceSKU.PerUserEnterprise)
 
    def maxLicenceSkuPool(self,xspool):
        self.maxLicenceSkuHost(xspool.master)

    def licence(self, productVersion, sku):
        lver = productVersion.lower()
        if lver == self.__TAM:
            return TampaLicence(sku)
        if lver == self.__CLR:
            return ClearwaterLicence(sku)
        if lver == self.__CRE:
            return CreedenceLicence(sku)
        raise ValueError("No licence object was found for the provided host version: %s" % productVersion)
