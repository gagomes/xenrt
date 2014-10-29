from xenrt.enum import XenServerLicenceSKU

class CreedenceLicence(object):

    def getEdition(self, sku):
        """ Rune for xapi"""
        if sku = enum value:
            return "edition"

    def getLicenceFileName(self, sku):
        if sku = enum value:
            return "filenmae.lic"

    def getLicenceName(self, sku):
        if sku = enum value:
            return "CXS_STD"


class LicenseProvider(object):
    def licence(self, host):
        if host.productVersion == "Creedence":
            return CreedenceLicence()
        raise ValueError("Variosn does not exist")
