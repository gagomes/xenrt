#
# XenRT: Test harness for Xen and the XenServer product family
#
# XenServer licensing test cases valid from Clearwater
#
# Copyright (c) 2013 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import string, re, time, traceback, sys, copy, random
import xenrt

class LicenseBase(xenrt.TestCase, object):

    UPGRADE = False

    def prepare(self,arglist):

        self.editions = None
        self.hosts = []
        self.newLicenseServerName = 'LicenseServer'
        self.oldLicenseEdition = None
        self.oldLicenseServerName = None
        if self.getDefaultPool():
            self.__sysObj =  self.getDefaultPool()
            self.hosts = self.getDefaultPool().getHosts() 
            self.__isHostObj = False
        else:
            self.__sysObj = self.getHost("RESOURCE_HOST_1")
            self.__isHostObj = True
            self.hosts.append(self.__sysObj)
        self.__parseArgs(arglist)

        self.v6 = self.licenseServer(self.newLicenseServerName)

        if not self.UPGRADE:
            self.updateLicenseObjs()
            self.verifyEditions()

    def updateLicenseObjs(self):

        self.__validLicenseObj = self.systemObj.validLicenses()
        self.__validXSLicenseObj = self.systemObj.validLicenses(xenserverOnly=True)
        xenrt.TEC().logverbose("All valid editions: %s" % self.__validLicenseObj)
        xenrt.TEC().logverbose("XS valid editions: %s" % self.__validXSLicenseObj)

    def verifyEditions(self):

        if self.editions:
            for edition in self.editions:
                if not self.__checkForValidEdition(edition=edition):
                    raise xenrt.XRTFailure("Incorrect edition given")

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
 
    def upgradePool(self):

        # Update our internal pool object before starting the upgrade 
        newP = xenrt.lib.xenserver.poolFactory(xenrt.TEC().lookup("PRODUCT_VERSION", None))(self.__sysObj.master)
        self.__sysObj.populateSubclass(newP)

        #Perform Rolling Pool Upgrade
        xenrt.TEC().logverbose("Performing rolling pool upgrade of %s" % (self.__sysObj.getName()))
        self.__sysObj = newP.upgrade(rolling=True)

        # Upgrade PV tools in guests
        if self.__sysObj.master.listGuests() != [] :
            xenrt.TEC().logverbose("Found guests in pool hence Upgrading PV tools.....")
            for g in self.__sysObj.master.listGuests():
                # The guest will have been migrated during the RPU...
                poolguest = self.__sysObj.master.getGuest(g)
                xenrt.TEC().logverbose("Finding and upgrading VM %s" % (poolguest.getName()))
                poolguest.findHost()
                if poolguest.windows:
                    poolguest.installDrivers()
                else:
                    poolguest.installTools()
                poolguest.check()

    def licenseServer(self,name):

        v6 = self.getGuest(name).getV6LicenseServer()
        v6.removeAllLicenses()

        return v6

    def __parseArgs(self,arglist):

        for arg in arglist:
            if arg.startswith('edition'):
                self.editions = arg.split('=')[1].split(',')
            if arg.startswith('newlicenseserver'):
                self.newLicenseServerName = arg.split('=')[1]
            if arg.startswith('oldlicenseserver'):
                self.oldLicenseServerName = arg.split('=')[1]
            if arg.startswith('oldlicenseedition'):
                self.oldLicenseEdition = arg.split('=')[1]
            if arg.startswith('expectededition'):
                self.expectedEditionAfterUpg = arg.split('=')[1]

    def verifyLicenseServer(self,edition,reset=False):

        if not self.__isXSEdition(edition):
            xenrt.TEC().logverbose("XD license is applied so no need to verify the license server")
            return

        tmp,currentLicinuse = self.v6.getLicenseInUse(self._getLicenseName(edition))

        if reset:
            if self.licenseinUse != currentLicinuse: 
                raise xenrt.XRTFailure("Not all the licenses are not returned to license server, current licenses in use %d" % (currentLicinuse))
            xenrt.TEC().logverbose("License server verified and correct no of licenses checked out")
            return

        if not ((self.systemObj.getNoOfSockets() + self.licenseinUse)  == currentLicinuse):
            raise xenrt.XRTFailure("No. of Licenses in use: %d, No. of socket in whole pool: %d" % (currentLicinuse, self.systemObj.getNoOfSockets()))

        xenrt.TEC().logverbose("License server verified and correct no of licenses checked out")

    def verifySystemLicenseState(self,edition='free',skipHostLevelCheck=False):
 
        if not self.isHostObj:
            self.systemObj.checkLicenseState(edition=edition)
            if not skipHostLevelCheck:
                for host in self.hosts: 
                    host.checkHostLicenseState(edition=edition)
        else:
            self.systemObj.checkHostLicenseState(edition=edition)

    def __checkForValidEdition(self,edition):

        isValidEdition = False
        validEditions = self.validLicenses

        for validEdition in validEditions:
            if edition == validEdition.getEdition():
                isValidEdition = True
                break            
        
        return isValidEdition

    def __isXSEdition(self,edition):
    
       validXSEdition = self.validXSLicenses
 
       for xsEdition in validXSEdition:
           if edition == xsEdition.getEdition():
               return True

       return False

    def _getLicenseName(self,edition):

        validEditions = self.validLicenses

        for validEdition in validEditions:
            if edition == validEdition.getEdition():
                return validEdition.getLicenceName()        

    def _getLicenseFileName(self,edition):
     
        validEditions = self.validLicenses

        for validEdition in validEditions:
            if edition == validEdition.getEdition():
                return validEdition.getLicenceFileName()

    def getLicenseObj(self,edition):

        validEditions = self.validLicenses

        for validEdition in validEditions:
            if edition == validEdition.getEdition():
                return validEdition

    def addLicenses(self,license):

        self.v6.addLicense(license.getLicenceFileName())
        tmp,self.licenseinUse = self.v6.getLicenseInUse(license.getLicenceName())

    def applyLicense(self,license):

        self.addLicenses(license)

        self.systemObj.licenseApply(self.v6,license)
 
        self.verifyLicenseServer(edition=license.getEdition())

    def releaseLicense(self,edition):

        self.systemObj.license(v6server=None,sku='free',usev6testd=False)

        self.verifyLicenseServer(edition,reset=True)

    def checkGrace(self,host):
  
        licenseInfo = host.getLicenseDetails()
        if not 'grace' in licenseInfo['grace']:
            raise xenrt.XRTFailure('Host has not got grace license')

        expiry = xenrt.util.parseXapiTime(licenseInfo['expiry'])

        if (expiry > (xenrt.timenow() + 30*25*3600 + 1)):
            raise xenrt.XRTFailure("Host has got license expiry date more than 30 days from current time, it has got expiry date: %s " % expiry)

    def run(self,arglist=None):

        self.preLicenseHook()

        for edition in self.editions:

            self.applyLicense(self.getLicenseObj(edition)) 

            self.releaseLicense(edition)

class ClearwaterUpgrade(LicenseBase):
    UPGRADE  = True

    def preLicenseHook(self):

        if self.oldLicenseEdition:
            v6 = self.licenseServer(self.oldLicenseServerName)     
            v6.addLicense(self.oldLicenseEdition)       
            for host in self.hosts:
                host.templicense(edition=self.oldLicenseEdition,v6server=v6)

        if self.isHostObj:
            self.systemObj.upgrade()
        else:
            self.upgradePool()

        self.updateLicenseObjs() 

    def run(self,arglist=None):

        self.preLicenseHook()

class TCCWOldLicenseServerExp(ClearwaterUpgrade):

    def preLicenseHook(self):

        super(TCCWOldLicenseServerExp, self).preLicenseHook()

        self.verifySystemLicenseState(edition=self.expectedEditionAfterUpg)
        
        for host in self.hosts:
            self.checkGrace(host)

        #Expire the host 

class TCCWOldLicenseServerUpg(ClearwaterUpgrade):

    def preLicenseHook(self):

        super(TCCWOldLicenseServerUpg, self).preLicenseHook()

        self.verifySystemLicenseState(edition=self.expectedEditionAfterUpg)

        for host in self.hosts:
            self.checkGrace(host)

        self.addLicenses(self.getLicenseObj(self.expectedEditionAfterUpg))

        self.applyLicense(self.getLicenseObj(self.expectedEditionAfterUpg))

        self.releaseLicense(self.expectedEditionAfterUpg)

class TCCWNewLicenseServer(ClearwaterUpgrade):

    def preLicenseHook(self):

        if self.oldLicenseEdition:
            v6 = self.licenseServer(self.oldLicenseServerName)
            v6.addLicense(self.oldLicenseEdition)
            for host in self.hosts:
                host.templicense(edition=self.oldLicenseEdition,v6server=v6)

            self.v6.addLicense(self.oldLicenseEdition)
            for host in self.hosts:
                host.templicense(edition=self.oldLicenseEdition,v6server=self.v6)

        self.addLicenses(self.getLicenseObj(self.expectedEditionAfterUpg))

        if self.isHostObj:
            self.systemObj.upgrade()
        else:
            self.upgradePool()
        self.updateLicenseObjs() 
        for host in self.hosts:
            try:
                self.checkGrace(host)
                raise xenrt.XRTFailure("Host has got grace license")
            except Exception as e:
                pass

        self.verifySystemLicenseState(edition=self.expectedEditionAfterUpg)
 
        self.releaseLicense(self.expectedEditionAfterUpg)

class TampaUpgrade(LicenseBase):
    UPGRADE = True

    def preLicenseHook(self):

        if self.oldLicenseEdition:
            v6 = self.licenseServer(self.oldLicenseServerName)     
            v6.addLicense(self.oldLicenseEdition)       
            for host in self.hosts:
                host.license(edition=self.oldLicenseEdition,v6server=v6)            
                details = host.getLicenseDetails()
                wlbprevstatus = details["restrict_wlb"]
                if self.oldLicenseEdition == "advanced" and not(wlbprevstatus == "true"):
                    raise xenrt.XRTFailure('Advance Tampa Host has wlb enabled')
                elif self.oldLicenseEdition == "platinum" and not (wlbprevstatus=="false"): 
                    raise xenrt.XRTFailure('Platinum Tampa Host has wlb disabled')            

        if self.isHostObj:
            self.systemObj.upgrade()
        else:
            self.upgradePool()
        
        self.updateLicenseObjs()    
    def run(self,arglist=None):
    
        self.preLicenseHook()
            
class TCTPOldLicenseServerExp(TampaUpgrade):
#U3.2 , C7 ,max 4 testcase
    def preLicenseHook(self):

        super(TCTPOldLicenseServerExp, self).preLicenseHook()
        
        #verfiy that the host is in expired state  as the license server is not upgraded 
        self.verifySystemLicenseState()
        
class TCTPOldLicenseServerUpg(TampaUpgrade):

    def preLicenseHook(self):

        super(TCTPOldLicenseServerUpg, self).preLicenseHook()

        self.verifySystemLicenseState()
        
        #License the creedence host with new license server
        self.applyLicense(self.getLicenseObj(self.expectedEditionAfterUpg))

        self.releaseLicense(self.expectedEditionAfterUpg)
            
class TCTPNewLicenseServer(TampaUpgrade):
#U3.1 , C8 ,max 5 testcases

    def preLicenseHook(self):

        if self.oldLicenseEdition:
            v6 = self.licenseServer(self.oldLicenseServerName)
            v6.addLicense(self.oldLicenseEdition)
            for host in self.hosts:
                host.license(edition=self.oldLicenseEdition,v6server=v6)

            self.v6.addLicense(self.oldLicenseEdition)
            for host in self.hosts:
                host.license(edition=self.oldLicenseEdition,v6server=self.v6)
                details = host.getLicenseDetails()
                wlbprevstatus = details["restrict_wlb"]
                if self.oldLicenseEdition == "advanced" and not(wlbprevstatus == "true"):
                    raise xenrt.XRTFailure('Advance Tampa Host has wlb enabled')
                elif self.oldLicenseEdition == "platinum" and not (wlbprevstatus=="false"): 
                    raise xenrt.XRTFailure('Platinum Tampa Host has wlb disabled')
            
            #Ensure that creedence licenses are available in new license server prior to host upgrade        
            self.addLicenses(self.getLicenseObj(self.expectedEditionAfterUpg))
            #self.v6.addLicense(self._getLicenseFileName(edition))

        if self.isHostObj:
            self.systemObj.upgrade()
        else:
            self.upgradePool()
 
        self.updateLicenseObjs()
        for host in self.hosts:
            try:
                self.checkGrace(host)
                raise xenrt.XRTFailure("Host has got grace license")
            except Exception as e:
                pass
        
        #The host will be in licensed state depending upon its previous license
        self.verifySystemLicenseState(edition=self.expectedEditionAfterUpg)
 
        self.releaseLicense(self.expectedEditionAfterUpg)
        
class TCTPNewLicServerNoLicenseFiles(TampaUpgrade):
#U3.3 , C9 
    def preLicenseHook(self):

        if self.oldLicenseEdition:
            v6 = self.licenseServer(self.oldLicenseServerName)
            v6.addLicense(self.oldLicenseEdition)
            for host in self.hosts:
                host.license(edition=self.oldLicenseEdition,v6server=v6)

            self.v6.addLicense(self.oldLicenseEdition)
            for host in self.hosts:
                host.license(edition=self.oldLicenseEdition,v6server=self.v6)
                details = host.getLicenseDetails()
                wlbprevstatus = details["restrict_wlb"]
                if self.oldLicenseEdition == "advanced" and not(wlbprevstatus == "true"):
                    raise xenrt.XRTFailure('Advance Tampa Host has wlb enabled')
                elif self.oldLicenseEdition == "platinum" and not (wlbprevstatus=="false"): 
                    raise xenrt.XRTFailure('Platinum Tampa Host has wlb disabled')
                
        if self.isHostObj:
            self.systemObj.upgrade()
        else:
            self.upgradePool()
        self.updateLicenseObjs() 
        #verfiy that the host is in expired state  as the creedence licenses are not available 
        self.verifySystemLicenseState()
        
        #Now upload creedence license files into license server      
        self.addLicenses(self.getLicenseObj(self.expectedEditionAfterUpg))
            
        #The host gets the license depending upon its previous license
        self.verifySystemLicenseState(edition=self.expectedEditionAfterUpg) 
        self.releaseLicense(self.expectedEditionAfterUpg)

class LicenseExpiryBase(LicenseBase):
    """
    TC for Creedence (and later) license expiration test.
    """

    def expireLicenseTest(self):
        """Select a host and force expire the license of the host."""
        if self.isHostObj:
            host = self.systemObj
        else:
            host = random.choice(self.systemObj.getHosts())

        self.__forceExpireLicense(host)

    def __forceExpireLicense(self, host):
        """ Set next day of expiration date"""
        
        licinfo = host.getLicenseDetails()
        host.execdom0("/etc/init.d/ntpd stop")
        expiretarget = time.gmtime(licinfo["expiry"])
        host.execdom0("date -u %s" %
                           (time.strftime("%m%d%H%M%Y.%S",expiretarget)))

        # Give some time to actually expire the license.
        xenrt.sleep(60)

    def resetTimer(self, host):
        """ Restart NTP daemon, so that timer of host reset on time."""
        host.execdom0("/etc/init.d/ntpd start")
        # Give some time to resync timer.
        xenrt.sleep(30)

    def run(self, arglist=[]):
        pass

class TCLicenseExpiry(LicenseExpiryBase):
    """ Expiry test case """

    def run(self, arglist=[]):

        self.preLicenseHook()

        for edition in self.editions:
            if edition == "free":
                # free lincese does not require expiry test.
                continue
            # Assign license and verify it.
            self.applyLicense(self.getLicenseObj(edition)) 
            self.verifySystemLicenseState(edition=edition)
            self.verifyLicenseServer(edition)

            # Expiry test
            host = self.expireLicenseTest()
            host.checkHostLicenseState("free")
            if not self.isHostObj:
                self.verifySystemLicenseState(edition, True)
            self.resetTimer(host)
            # End of expiry test

            self.releaseLicense(edition)

class LicenseGraceBase(LicenseExpiryBase):
    """Base class to verify the grace license tests"""

    def initiateGraceLicenseTest(self):
        """Shutdown license server and restart host v6d server"""

        # Shutdown the License Server.
        self.v6.stop()
        # Restart v6d service on hosts.
        for host in self.hosts:
            host.execdom0("service v6d restart")

    def revertGraceLicenseTest(self):
        """Start license server and restart host v6d server"""

        # Start the license server.
        self.v6.start()
        # Restart v6d service on hosts.
        for host in self.hosts:
            host.execdom0("service v6d restart")

    def run(self, arglist=[]):
        pass

class TCLicenseGraceBase(LicenseGraceBase):
    """Verify the grace license and its expiry in Creedence hosts"""

    def run(self, arglist=[]):

        self.preLicenseHook()

        for edition in self.editions:
            if edition == "free":
                # Free lincese does not require grace license test.
                continue

            # Assign license and verify it.
            license = self.getLicenseObj(edition)
            self.applyLicense(license)

            self.initiateGraceLicenseTest()

            # Check whether the hosts obtained grace licenses.
            for host in self.hosts:
                self.checkGrace(host)

            self.revertGraceLicenseTest()

            # Check whether the hosts regained the original licenses.
            self.verifySystemLicenseState(edition=edition)
            self.verifyLicenseServer(edition)

            self.initiateGraceLicenseTest()

            # Check whether the hosts obtained grace licenses.
            for host in self.hosts:
                self.checkGrace(host)

            # Now expire one of the host license such that it cross the grace period.
            host = self.expireLicenseTest()

            # Check whether the hosts license expired.
            self.verifySystemLicenseState(skipHostLevelCheck=True) # pool level license check.
            
            # Now reset the timer.
            self.resetTimer(host) 
            
            # At this point we do not know what is the license state.
            # Goes back to grace license again ? Or the original license?.
            # Not sure whether to release the license and verify the state again.
