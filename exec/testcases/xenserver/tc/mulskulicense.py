#
# XenRT: Test harness for Xen and the XenServer product family
#
# XenServer licensing test cases valid from Clearwater
#
# Copyright (c) 2014 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import string, re, traceback, sys, copy, random, datetime
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

    def addCWLicenseFiles(self,v6):

        licenseFilename = []
        licenseFilename.append("valid-xendesktop")
        licenseFilename.append("valid-persocket")
        
        for lFile in licenseFilename:
            v6.addLicense(lFile)

    def addTPLicenseFiles(self,v6):

        licenseFilename = []
        licenseFilename.append("valid-platinum")
        licenseFilename.append("valid-enterprise-xd")
        licenseFilename.append("valid-enterprise")
        licenseFilename.append("valid-advanced")

        for lFile in licenseFilename:
            v6.addLicense(lFile)

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

        self.hosts = self.__sysObj.getHosts()

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
            
    def checkLicenseExpired(self, host, edition, raiseException=False):
        """ Checking License is expired by checking feature availability.
        Checking date is pointless as TC expires license by changing date."""

        try:
            host.checkHostLicenseState(edition)
        except xenrt.XRTException, e:
            if raiseException:
                raise e
            else:
                xenrt.TEC().logverbose("ERROR: %s" % str(e))
                return False

        licdet = host.getLicenseDetails()
        if not "restrict_wlb" in licdet:
            if raiseException:
                raise xenrt.XRTError("restrict_wlb is not in the license detail.")
            return False
        if licdet["restrict_wlb"]== "false":
            if raiseException:
                raise xenrt.XRTError("restrict_wlb is false after license is expired.")
            return False
        if not "restrict_read_caching" in licdet:
            if raiseException:
                raise xenrt.XRTError("restrict_read_caching is not in the license detail.")
            return False
        if licdet["restrict_read_caching"]== "false":
            if raiseException:
                raise xenrt.XRTError("restrict_read_caching is false after license is expired.")
            return False
        if not "restrict_vgpu" in licdet:
            if raiseException:
                raise xenrt.XRTError("restrict_vgpu is not in the license detail.")
            return False
        if licdet["restrict_vgpu"]== "false":
            if raiseException:
                raise xenrt.XRTError("restrict_vgpu is false after license is expired.")
            return False

        return True

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

    def postRun(self):
        for edition in self.editions:
            self.releaseLicense(edition)
        xenrt.TestCase.postRun(self)


class ClearwaterUpgrade(LicenseBase):
    UPGRADE  = True

    def preLicenseHook(self):

        if self.oldLicenseEdition:
            v6 = self.licenseServer(self.oldLicenseServerName)    
            if self.oldLicenseEdition != 'free':
                self.addCWLicenseFiles(v6) 
            for host in self.hosts:
                host.templicense(edition=self.oldLicenseEdition,v6server=v6)

        if self.isHostObj:
            self.systemObj.upgrade()
            self.hosts=[]
            self.hosts.append(self.systemObj)
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

            if self.oldLicenseEdition != 'free':
                self.addCWLicenseFiles(v6)
                self.addCWLicenseFiles(self.v6)

            for host in self.hosts:
                host.templicense(edition=self.oldLicenseEdition,v6server=v6)

            for host in self.hosts:
                host.templicense(edition=self.oldLicenseEdition,v6server=self.v6)

        self.addLicenses(self.getLicenseObj(self.expectedEditionAfterUpg))

        if self.isHostObj:
            self.systemObj.upgrade()
            self.hosts=[]
            self.hosts.append(self.systemObj)
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
            if self.oldLicenseEdition != 'free':
                self.addTPLicenseFiles(v6)
 
            for host in self.hosts:
                host.license(edition=self.oldLicenseEdition,usev6testd=False,v6server=v6)            
                details = host.getLicenseDetails()
                #wlbprevstatus = details["restrict_wlb"]
                #if self.oldLicenseEdition == "advanced" and not(wlbprevstatus == "true"):
                #    raise xenrt.XRTFailure('Advance Tampa Host has wlb enabled')
                #elif self.oldLicenseEdition == "platinum" and not (wlbprevstatus=="false"): 
                #    raise xenrt.XRTFailure('Platinum Tampa Host has wlb disabled')            

        if self.isHostObj:
            self.systemObj.upgrade()
            self.hosts=[]
            self.hosts.append(self.systemObj)
        else:
            self.upgradePool()
        
        self.updateLicenseObjs()    
    def run(self,arglist=None):
    
        self.preLicenseHook()
            
class TCTPOldLicenseServerUpg(TampaUpgrade):

    def preLicenseHook(self):

        super(TCTPOldLicenseServerUpg, self).preLicenseHook()

        #Verify that the Tampa Host is having expected edition but in expired state as the license server is not updated
        for host in self.hosts :
            if not self.checkLicenseExpired(host, edition=self.expectedEditionAfterUpg):
                raise xenrt.XRTFailure("License is not expired properly.")
        
        #License the creedence host with new license server
        self.applyLicense(self.getLicenseObj(self.expectedEditionAfterUpg))

        self.releaseLicense(self.expectedEditionAfterUpg)
            
class TCTPNewLicenseServer(TampaUpgrade):
#U3.1 , C8 ,max 5 testcases

    def preLicenseHook(self):

        if self.oldLicenseEdition:
            v6 = self.licenseServer(self.oldLicenseServerName)
            if self.oldLicenseEdition != 'free':
                self.addTPLicenseFiles(v6)
                self.addTPLicenseFiles(self.v6)

            for host in self.hosts:
                host.license(edition=self.oldLicenseEdition,usev6testd=False,v6server=v6)

            for host in self.hosts:
                host.license(edition=self.oldLicenseEdition,usev6testd=False,v6server=self.v6)
                details = host.getLicenseDetails()
                #wlbprevstatus = details["restrict_wlb"]
                #if self.oldLicenseEdition == "advanced" and not(wlbprevstatus == "true"):
                #    raise xenrt.XRTFailure('Advance Tampa Host has wlb enabled')
                #elif self.oldLicenseEdition == "platinum" and not (wlbprevstatus=="false"): 
                #    raise xenrt.XRTFailure('Platinum Tampa Host has wlb disabled')
            
            #Ensure that creedence licenses are available in new license server prior to host upgrade        
            self.updateLicenseObjs()
            self.addLicenses(self.getLicenseObj(self.expectedEditionAfterUpg))         

        if self.isHostObj:
            self.systemObj.upgrade()
            self.hosts=[]
            self.hosts.append(self.systemObj)
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
            if self.oldLicenseEdition != 'free':
                self.addTPLicenseFiles(v6)
                self.addTPLicenseFiles(self.v6)

            for host in self.hosts:
                host.license(edition=self.oldLicenseEdition,usev6testd=False,v6server=v6)

            for host in self.hosts:
                host.license(edition=self.oldLicenseEdition,usev6testd=False,v6server=self.v6)
                details = host.getLicenseDetails()
                #wlbprevstatus = details["restrict_wlb"]
                #if self.oldLicenseEdition == "advanced" and not(wlbprevstatus == "true"):
                #    raise xenrt.XRTFailure('Advance Tampa Host has wlb enabled')
                #elif self.oldLicenseEdition == "platinum" and not (wlbprevstatus=="false"): 
                #    raise xenrt.XRTFailure('Platinum Tampa Host has wlb disabled')
                
        if self.isHostObj:
            self.systemObj.upgrade()
            self.hosts=[]
            self.hosts.append(self.systemObj)
        else:
            self.upgradePool()
        self.updateLicenseObjs()       
                
        #Verify that the Tampa Host is having expected edition but in expired state as the creedence license files are not available in license server.
        for host in self.hosts :
            if not self.checkLicenseExpired(host, edition=self.expectedEditionAfterUpg):
                raise xenrt.XRTFailure("License is not expired properly.")
        
        #Now upload creedence license files into license server      
        self.addLicenses(self.getLicenseObj(self.expectedEditionAfterUpg))
            
        #The host gets the license depending upon its previous license
        self.verifySystemLicenseState(edition=self.expectedEditionAfterUpg) 
        self.releaseLicense(self.expectedEditionAfterUpg)

class LicenseExpiryBase(LicenseBase):
    """
    TC for Creedence (and later) license expiration test.
    """

    def expireLicense(self):
        """Select a host and force expire the license of the host."""
        if self.isHostObj:
            host = self.systemObj
        else:
            host = random.choice(self.systemObj.getHosts())

        self.__forceExpireLicense(host)

        return host

    def __forceExpireLicense(self, host):
        """ Set next day of expiration date"""

        xenrt.TEC().logverbose("Change date and time of %s to expire license." % host.getName())
        licinfo = host.getLicenseDetails()
        host.execdom0("/etc/init.d/ntpd stop")
        expiretarget = datetime.datetime.strptime(licinfo["expiry"], "%Y%m%dT%H:%M:%SZ")
        host.execdom0("date -u %s" % expiretarget.strftime("%m%d%H%M%Y.%S"))

        # Give some time to actually expire the license.
        xenrt.sleep(60)

    def checkLicenseExpired(self, host, edition, raiseException=False):
        """ Checking License is expired by checking feature availability.
        Checking date is pointless as TC expires license by changing date."""

        try:
            host.checkHostLicenseState(edition)
        except xenrt.XRTException, e:
            if raiseException:
                raise e
            else:
                xenrt.TEC().logverbose("ERROR: %s" % str(e))
                return False

        licdet = host.getLicenseDetails()
        if not "restrict_wlb" in licdet:
            if raiseException:
                raise xenrt.XRTError("restrict_wlb is not in the license detail.")
            return False
        if licdet["restrict_wlb"]== "false":
            if raiseException:
                raise xenrt.XRTError("restrict_wlb is false after license is expired.")
            return False
        if not "restrict_read_caching" in licdet:
            if raiseException:
                raise xenrt.XRTError("restrict_read_caching is not in the license detail.")
            return False
        if licdet["restrict_read_caching"]== "false":
            if raiseException:
                raise xenrt.XRTError("restrict_read_caching is false after license is expired.")
            return False
        if not "restrict_vgpu" in licdet:
            if raiseException:
                raise xenrt.XRTError("restrict_vgpu is not in the license detail.")
            return False
        if licdet["restrict_vgpu"]== "false":
            if raiseException:
                raise xenrt.XRTError("restrict_vgpu is false after license is expired.")
            return False

        return True

    def resetTimer(self, host=None):
        """ Restart NTP daemon, so that timer of host reset on time."""
        
        hosts = []
        if not host:
            if self.isHostObj:
                hosts = [self.systemObj]
            else:
                hosts = self.systemObj.getHosts()
        else:
            hosts = [host]
                
        for host in hosts:
            xenrt.TEC().logverbose("Starting NTPD on %s" % host.getName())
            try:
                host.execdom0("/etc/init.d/ntpd start", nolog=True)
                # Give some time to resync timer.
                xenrt.sleep(30)
            except:
                # If NTPD is already running, command will raise Exception.
                # In that case no need to sleep.
                pass

    def run(self, arglist=[]):
        pass

    def postRun(self):
        self.resetTimer()
        LicenseBase.postRun(self)

class TCLicenseExpiry(LicenseExpiryBase):
    """ Expiry test case """

    def licenseExpiryTest(self, edition):

        # Need to reset in case previous sub case failed.
        self.resetTimer()

        # Assign license and verify it.
        self.applyLicense(self.getLicenseObj(edition))
        self.verifySystemLicenseState(edition)

        # Expiry test
        host = self.expireLicense()
        if not self.checkLicenseExpired(host, edition):
            raise xenrt.XRTFailure("License is not expired properly.")

        # Cleaning up.
        self.resetTimer(host)
        self.releaseLicense(edition)
        
    def run(self, arglist=[]):

        self.preLicenseHook()

        for edition in self.editions:
            if edition == "free":
                # free lincese does not require expiry test.
                continue

            self.runSubcase("licenseExpiryTest", edition, "Expiry - %s" % edition, "Expiry")

class LicenseGraceBase(LicenseExpiryBase):
    """Base class to verify the grace license tests"""

    def initiateGraceLicense(self):
        """Shutdown license server and restart host toolstack"""

        # Shutdown the License Server.
        self.getGuest(self.newLicenseServerName).shutdown() # self.v6.stop()

        # Restart toostack on every hosts.
        [host.restartToolstack() for host in self.hosts] # service v6d restart

    def revertGraceLicense(self):
        """Start license server and restart host toolstack"""

        # Start the license server.
        self.getGuest(self.newLicenseServerName).start() # self.v6.start()

        # Restart toostack on every hosts.
        [host.restartToolstack() for host in self.hosts] # service v6d restart

    def run(self, arglist=[]):
        pass

class TCLicenseGrace(LicenseGraceBase):
    """Verify the grace license and its expiry in Creedence hosts"""

    def licenseGraceTest(self, edition):

        # Check whether the license server is running.
        if self.getGuest(self.newLicenseServerName).getState() != "UP":
            self.getGuest(self.newLicenseServerName).start()

        # Assign license and verify it.
        self.applyLicense(self.getLicenseObj(edition))

        # Force the host to have grace license.
        self.initiateGraceLicense()

        # Check whether the hosts obtained grace licenses.
        for host in self.hosts:
            self.checkGrace(host)

        # Force the hosts to regain its orignal licenses.
        self.revertGraceLicense()

        # Check whether the hosts regained the original licenses.
        self.verifySystemLicenseState(edition=edition)
        self.verifyLicenseServer(edition)

        # Again force the host to have grace license.
        self.initiateGraceLicense()

        # Check whether the hosts obtained grace licenses.
        for host in self.hosts:
            self.checkGrace(host)

        # Now expire one of the host license such that it cross the grace period.
        host = self.expireLicense()
        if not self.checkLicenseExpired(host, edition):
            raise xenrt.XRTFailure("License is not expired properly.")

        # Check whether the hosts license expired.
        self.verifySystemLicenseState(skipHostLevelCheck=True) # pool level license check.
        
        # Now reset the timer.
        self.resetTimer(host) 
        
        # At this point we do not know what is the license state.
        # Goes back to grace license again ? Or the original license?.
        # Not sure whether to release the license and verify the state again.
        self.releaseLicense(edition)

    def run(self, arglist=[]):

        self.preLicenseHook()

        for edition in self.editions:
            if edition == "free":
                # Free lincese does not require grace license test.
                continue

            self.runSubcase("licenseGraceTest", edition, "Grace - %s" % edition, "Grace")
