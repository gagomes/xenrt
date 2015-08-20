import xenrt
from xenrt.enum import XenServerLicenseSKU
from abc import ABCMeta, abstractmethod
from xenrt.lazylog import log

__all__ = ["DundeeLicense", "CreedenceLicense", "TampaLicense", "ClearwaterLicense", "XenServerLicenseFactory", "LicenseManager"]


class LicenseManager(object):
    def addLicensesToServer(self, v6, License,getLicenseInUse = True):
        LicenseinUse = 0
        v6.addLicense(License.getLicenseFileName())
        if getLicenseInUse:
            totalLicenses, LicenseinUse = v6.getLicenseInUse(License.getLicenseName())
        return LicenseinUse

    def applyLicense(self, v6, hostOrPool, License,LicenseinUse):
        hostOrPool.licenseApply(v6,License)
        self.verifyLicenseServer(License,v6,LicenseinUse,hostOrPool) 

    def releaseLicense(self, hostOrPool):
        license = XenServerLicenseFactory().licenseForPool(hostOrPool,XenServerLicenseSKU.Free)
        hostOrPool.licenseApply(None,license)

    def verifyLicenseServer(self, License, v6, LicenseinUse, hostOrPool, reset=False):

        if isinstance(hostOrPool,xenrt.lib.xenserver.Pool):
            productVersion = hostOrPool.master.productVersion
        else:
            productVersion = hostOrPool.productVersion
        xsOnlyLicenses = XenServerLicenseFactory().xenserverOnlyLicenses(productVersion)
        if not next((i for i in xsOnlyLicenses if i.getEdition() == License.getEdition()), None):
            xenrt.TEC().logverbose("XD License is applied so no need to verify the License server")
            return

        tmp,currentLicinuse = v6.getLicenseInUse(License.getLicenseName())
        log("tmp: %s currentlicinuse: %s sockets: %s LicenseinUse: %s "%(tmp,currentLicinuse,hostOrPool.getNoOfSockets(),LicenseinUse))
        if reset:
            if LicenseinUse != currentLicinuse:
                raise xenrt.XRTFailure("Not all the Licenses are not returned to License server, current Licenses in use %d" % (currentLicinuse))
            xenrt.TEC().logverbose("License server verified and correct no of Licenses checked out")
            return

        if not ((hostOrPool.getNoOfSockets() + LicenseinUse)  == currentLicinuse):
            raise xenrt.XRTFailure("No. of Licenses in use: %d, No. of socket in whole pool: %d" % (currentLicinuse, hostOrPool.getNoOfSockets()))

        xenrt.TEC().logverbose("License server verified and correct no of Licenses checked out")


class License(object):
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
    def getLicenseFileName(self):
        """
        File name for the given SKU
        @rtype string
        """
        pass

    @abstractmethod
    def getLicenseName(self):
        """
        License servers understanding of a given SKU
        @rtype string
        """
        pass

    def verify(self):
        self.getEdition()
        self.getLicenseFileName()
        self.getLicenseName()

    def __str__(self):
        return "SKU: %s; Edition: %s; FileName: %s; LicenseServerName: %s" % (self.sku,
                                                                              self.getEdition(),
                                                                              self.getLicenseFileName(),
                                                                              self.getLicenseName())


class TampaLicense(License):

    def getEdition(self):
        if self.sku == XenServerLicenseSKU.XSPlatinum:
            return "platinum"
        if self.sku == XenServerLicenseSKU.XSEnterprise:
            return "enterprise"
        if self.sku == XenServerLicenseSKU.XSAdvance:
            return "advanced"
        if self.sku == XenServerLicenseSKU.XenDesktop:
            return "enterprise-xd"
        if self.sku == XenServerLicenseSKU.Free:
            return "free"
        raise ValueError("No edition found for the SKU %s" % self.sku)

    def getLicenseFileName(self):
        if self.sku == XenServerLicenseSKU.XSPlatinum:
            return "valid-platinum"
        if self.sku == XenServerLicenseSKU.XSEnterprise:
            return "valid-enterprise"
        if self.sku == XenServerLicenseSKU.XSAdvance:
            return "valid-advanced"
        if self.sku == XenServerLicenseSKU.XenDesktop:
            return "valid-enterprise-xd"
        if self.sku == XenServerLicenseSKU.Free:
            return None
        raise ValueError("No License file name found for the SKU %s" % self.sku)

    def getLicenseName(self):
        return

class ClearwaterLicense(License):
    
    def getEdition(self):
        if self.sku == XenServerLicenseSKU.PerSocket:
            return "per-socket"
        if self.sku == XenServerLicenseSKU.Free:
            return "free"
        if self.sku == XenServerLicenseSKU.XenDesktop:
            return "xendesktop"
        raise ValueError("No edition found for the SKU %s" % self.sku)

    def getLicenseFileName(self):
        if self.sku == XenServerLicenseSKU.PerSocket:
            return "valid-persocket"
        if self.sku == XenServerLicenseSKU.Free:
            return None
        if self.sku == XenServerLicenseSKU.XenDesktop:
            return "valid-enterprise-xd"
        raise ValueError("No License file name found for the SKU %s" % self.sku)

    def getLicenseName(self):

        if self.sku == XenServerLicenseSKU.PerSocket:
            return "CXS_STD_CCS"
        if self.sku == XenServerLicenseSKU.Free:
            return None
        if self.sku == XenServerLicenseSKU.XenDesktop:
            return "XDS_STD_CCS"
        raise ValueError("No License server name found for the SKU %s" % self.sku)  

class CreedenceLicense(License):

    def getEdition(self):
        if self.sku == XenServerLicenseSKU.PerUserEnterprise or \
           self.sku == XenServerLicenseSKU.PerConcurrentUserEnterprise:
            return "enterprise-per-user"
        if self.sku == XenServerLicenseSKU.PerSocketEnterprise or \
           self.sku == XenServerLicenseSKU.PerSocket:
            return "enterprise-per-socket"
        if self.sku == XenServerLicenseSKU.XenDesktop:
            return "desktop"
        if self.sku == XenServerLicenseSKU.PerSocketStandard:
            return "standard-per-socket"
        if self.sku == XenServerLicenseSKU.XenDesktopPlusXDS or \
            self.sku == XenServerLicenseSKU.XenDesktopPlusMPS:
            return "desktop-plus"
        if self.sku == XenServerLicenseSKU.Free:
            return "free"
        raise ValueError("No edition found for the SKU %s" % self.sku)

    def getLicenseFileName(self):
        if self.sku == XenServerLicenseSKU.PerSocketEnterprise:
            return "valid-enterprise-persocket"
        if self.sku == XenServerLicenseSKU.PerUserEnterprise:
            return "valid-enterprise-peruser"
        if self.sku == XenServerLicenseSKU.PerConcurrentUserEnterprise:
            return "valid-enterprise-perccu"
        if self.sku == XenServerLicenseSKU.XenDesktop:
            return "valid-xendesktop"
        if self.sku == XenServerLicenseSKU.PerSocketStandard:
            return "valid-standard-persocket"
        if self.sku == XenServerLicenseSKU.Free:
            return None
        if self.sku == XenServerLicenseSKU.PerSocket:
            return "valid-persocket"
        if self.sku == XenServerLicenseSKU.XenDesktopPlusXDS:
            return "valid-xendesktop-plus"
        if self.sku == XenServerLicenseSKU.XenDesktopPlusMPS:
            return "valid-xendesktop-plus-MPS"
        raise ValueError("No License file name found for the SKU %s" % self.sku)

    def getLicenseName(self):
        if self.sku == XenServerLicenseSKU.PerSocketEnterprise:
            return "CXS_ENT2_CCS"
        if self.sku == XenServerLicenseSKU.PerUserEnterprise:
            return "CXS_ENT2_UD"
        if self.sku == XenServerLicenseSKU.PerConcurrentUserEnterprise:
            return "CXS_ENT2_CCU"
        if self.sku == XenServerLicenseSKU.XenDesktop:
            return "XDS_STD_CCS"
        if self.sku == XenServerLicenseSKU.PerSocketStandard:
            return "CXS_STD2_CCS"
        if self.sku == XenServerLicenseSKU.Free:
            return None
        if self.sku == XenServerLicenseSKU.PerSocket:
            return "CXS_STD_CCS"
        if self.sku == XenServerLicenseSKU.XenDesktopPlusXDS:
            return "XDS_PLT_CCS"
        if self.sku == XenServerLicenseSKU.XenDesktopPlusMPS:
            return "MPS_PLT_CCU"
        raise ValueError("No License server name found for the SKU %s" % self.sku)


class DundeeLicense(CreedenceLicense):
    # For now, trunk is assumed that it has same scheme as Creedence.
    pass

class XenServerLicenseFactory(object):
    __TAM = "tampa"
    __CLR = "clearwater"
    __CRE = "creedence"
    __SAN = "sanibel"
    __BOS = "boston"
    __COW = "cowley"
    __MNR = "mnr"
    __OXF = "oxford"
    __DUN = "dundee"
    __CRM = "cream"

    def __getHostAge(self, xshost):
        return xshost.productVersion.lower()

    def xenserverOnlyLicensesForPool(self, xspool):
        return self.xenserverOnlyLicenses(xspool.master.productVersion)

    def xenserverOnlyLicensesForHost(self, xshost):
        lver = self.__getHostAge(xshost)
        return self.xenserverOnlyLicenses(lver)

    def xenserverOnlyLicenses(self, productVersion):
        lver = productVersion.lower()
        if lver == self.__CRE or lver == self.__CRM or lver == self.__DUN:
            skus = [XenServerLicenseSKU.PerSocketEnterprise,
                    XenServerLicenseSKU.PerSocketStandard,
                    XenServerLicenseSKU.PerSocket]
            return [self.license(lver, s) for s in skus]

        raise ValueError("No license object was found for the provided host version: %s" % productVersion)

    def allLicensesForPool(self, xspool):
        lver = self.__getHostAge(xspool.master)
        return self.allLicenses(lver)

    def allLicensesForHost(self, xshost):
        lver = self.__getHostAge(xshost)
        return self.allLicenses(lver)

    def allLicenses(self, productVersion):
        lver = productVersion.lower()
        if lver == self.__CRE or lver == self.__CRM or lver == self.__DUN:
            skus = [XenServerLicenseSKU.PerSocketEnterprise, XenServerLicenseSKU.PerUserEnterprise,
                    XenServerLicenseSKU.PerConcurrentUserEnterprise, XenServerLicenseSKU.XenDesktopPlatinum,
                    XenServerLicenseSKU.PerSocketStandard, XenServerLicenseSKU.Free, XenServerLicenseSKU.PerSocket]
            return [self.license(lver, s) for s in skus]

        raise ValueError("No license object was found for the provided host version: %s" % productVersion)

    def licenseForPool(self, xspool, sku):
        lver =self.__getHostAge(xspool.master)
        return self.license(lver, sku)

    def licenseForHost(self, xshost, sku):
        lver = self.__getHostAge(xshost)
        return self.license(lver, sku)

    def maxLicenseSkuHost(self,xshost):
        lver = self.__getHostAge(xshost)
        if lver == self.__TAM or lver == self.__SAN or lver == self.__BOS or lver == self.__COW or lver == self.__MNR or lver == self.__OXF:
            return TampaLicense(XenServerLicenseSKU.XSPlatinum)    
        if lver == self.__CLR:
            return ClearwaterLicense(XenServerLicenseSKU.PerSocket)
        if lver == self.__CRE or lver == self.__CRM or lver == self.__DUN:
            return CreedenceLicense(XenServerLicenseSKU.PerSocketEnterprise)
 
    def maxLicenseSkuPool(self,xspool):
        self.maxLicenseSkuHost(xspool.master)

    def license(self, productVersion, sku):
        lver = productVersion.lower()
        if lver == self.__TAM:
            return TampaLicense(sku)
        if lver == self.__CLR:
            return ClearwaterLicense(sku)
        if lver == self.__CRE or lver == self.__CRM or lver == self.__DUN:
            return CreedenceLicense(sku)
        raise ValueError("No license object was found for the provided host version: %s" % productVersion)
