#
# XenRT: Test harness for Xen and the XenServer product family
#
# XenServer licensing test cases valid from Clearwater
#
# Copyright (c) 2013 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import string, re, time, traceback, sys, copy
import xenrt, xenrt.lib.xenserver, xenrt.lib.xenserver.cli

class LicenseBase(xenrt.TestCase):
    __metaclass__ = ABCMeta
    __LicenseServerName = 'LicenseServer'

    def prepare(self,arglist):

        self.__parseArgs(arglist)

        if self.getDefaultPool():
            self.__sysObj =  self.getDefaultPool()
            self.hosts = self.getDefaultPool().getHosts() 
            self.__isHostObj = False
        else:
            self.__sysObj = self.getDefaultHost()
            self.__isHostObj = True

        self.__validLicenseObj = self.systemObj.validLicenses()
        self.__validXSLicenseObj = self.systemObj.validLicenses(xenserverOnly=True)
        self.__LicenseServer()

    @abstractmethod
    def preLicenseHook(self):
        """
        Is the function that will be used to modify the host just before licenses is applied
        """
        pass

    @property
    def validLicenses(self):
        """
        returns the object of all the valid licenses
        """
        return self.__validLicenseObj

    @property
    def validXSLicenses(self):
        """
        returns the object of all the valid XS licenes only (no XD ones)
        """
        return self.__validXSLicenseObj
      
    @property
    def systemObj(self):
        """
        Object of either pool or host
        """
        return self.__sysObj

    @property
    def isHostObj(self):
        """
        tells whether the system object is of pools or hosts
        """
        return self.__isHostObj
 
    def upgradeHost(self):

        # Update our internal pool object before starting the upgrade 
        newP = xenrt.lib.xenserver.poolFactory(xenrt.TEC().lookup("PRODUCT_VERSION", None))(self.systemObj.master)
        self.systemObj.populateSubclass(newP)

        #Perform Rolling Pool Upgrade
        xenrt.TEC().logverbose("Performing rolling pool upgrade of %s" % (self.systemObj.getName()))
        self.systemObj = newP.upgrade(rolling=True)

        # Upgrade PV tools in guests
        if self.systemObj.master.listGuests() != [] :
            xenrt.TEC().logverbose("Found guests in pool hence Upgrading PV tools.....")
            for g in self.systemObj.master.listGuests():
                # The guest will have been migrated during the RPU...
                poolguest = self.systemObj.master.getGuest(g)
                xenrt.TEC().logverbose("Finding and upgrading VM %s" % (poolguest.getName()))
                poolguest.findHost()
                if poolguest.windows:
                    poolguest.installDrivers()
                else:
                    poolguest.installTools()
                poolguest.check()

    def __LicenseServer(self,name=self.__LicenseServerName):

        self.v6 = self.getGuest(name).getV6LicenseServer()
        self.v6.removeAllLicenses()

    def upgradeLicenseServer(self,name):

        self.__LicenseServer(name)

    def __parseArgs(self,arglist):

        self.args = {}

        for arg in arglist:
            if arg.startswith('edition'):
                self.args['edition'] = arg.split('=')[1]
                if not self.__checkForValidEdition(edition=self.args['edition']):
                    raise xenrt.XRTFailure("Incorrect edition given")
            if arg.startswith('licenseserver'):
                self.args['licenseserver'] = arg.split('=')[1]

    def verifyLicenseServer(self,edition):

        if not self.__isXSEdition(edition):
            return

        tmp,currentLicinuse = self.v6.getLicenseInUse(self.__getLicenseName(edition))

        if not self.systemObj.getNoOfSockets() + self.licenseinUse  == currentLicinuse:
            raise xenrt.XRTFailure("No of Licenses in use: %d, no of socket in whole pool: %d" % (currentLicinuse, self.systemObj.getNoOfSockets()))

        xenrt.TEC().logverbose("License server verified and correct no of licenses checked out")

    def verifySystemLicenseState(self,edition,skipHostLevelCheck=False):
 
        if not self.isHostObj:
            self.systemObj.checkLicenseState(edition=edition)
            if not skipHostLevelCheck:
                for host in self.hosts: 
                    host.checHostLicenseState(edition=edition)
        else:
            self.systemObj.checkHostLicenseState(edition=edition)

    def __checkForValidEdition(self,edition):

        isValidEdition = False
        validEditions = self.validLicenses()

        for validEdition in validEditions:
            if edition == validEdition.getEdition:
                isValidEdition = True
                break            
        
        return isValidEdition

    def __isXSEdition(self,edition):
    
       validXSEdition = self.validXSLicenses()
 
       for xsEdition in validXSEdition:
           if edition == validEdition.getEdition:
               return True

       return False

    def __getLicenseName(self,edition):

        validEditions = self.validLicenses()

        for validEdition in validEdition:
            if edition == validEdition.getEdition:
                return validEdition.getLicenseName        

    def __getLicenseFileName(self,edition):
     
        validEditions = self.validLicenses()

        for validEdition in validEdition:
            if edition == validEdition.getEdition:
                return validEdition.getLicenseFileName

    def addLicenses(self,edition):

        self.v6.addLicense(self.__getLicenseFileName(edition))
        self.licenseinUse = self.v6.getLicenseInUse(self.__getLicenseName(edition))

    def run(self,arglist=None):

        self.preLicenseHook()

        for edition in self.editions:
 
            self.v6.addLicense(self.__getLicenseFileName(edition))

            self.systemObj.license(edition=edition,v6server=self.v6)
           
            self.verifySystemLicenseState(edition=edition)

            self.verifyLicenseServer(edition)

            #self.systemObj.releaseLicense()
 
            self.verifySystemLicenseState(edition=edition,v6server=self.v6)

            self.verifyLicenseServer(edition)
