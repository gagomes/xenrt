#
# XenRT: Test harness for Xen and the XenServer product family
#
# XenServer licensing test cases valid from Clearwater
#
# Copyright (c) 2014 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import random
import xenrt
from xenrt.lib.xenserver.licesing import LicenceManager, XenServerLicenceFactory
from xenrt.lib import assertions
from enums import XenServerLicenceSKU

"""
TO DO:
Search for editions and replace with skus
Check upgrade cases and call the licence.verify method to verify any problems with strings being passed in
Replace addCWLicenseFiles usage
"""


class LicenseBase(xenrt.TestCase, object):

    def __init__(self):
        self.licenceManager = LicenceManager()
        self.licenceFactory = XenServerLicenceFactory()
        self.skus = []
        self.hosts = []
        self.newLicenseServerName = 'LicenseServer'
        self.oldLicenseEdition = None
        self.oldLicenseServerName = None
        self.graceExpected = True
        self.addLicFiles = True
        self.systemObj = None
        self.v6 = None

    def prepare(self,arglist):

        if self.getDefaultPool():
            self.systemObj =  self.getDefaultPool()
        else:
            self.systemObj = self.getHost("RESOURCE_HOST_1").getPool()

        self.__parseArgs(arglist)

        self.v6 = self.licenseServer(self.newLicenseServerName)

    #TO GO
    # def addCWLicenseFiles(self,v6):
    #     licenseFilename = []
    #     licenseFilename.append("valid-xendesktop")
    #     licenseFilename.append("valid-persocket")
    #     for lFile in licenseFilename:
    #         v6.addLicense(lFile)

    #TO GO
    def addTPLicenseFiles(self,v6):

        licenseFilename = []
        licenseFilename.append("valid-platinum")
        licenseFilename.append("valid-enterprise-xd")
        licenseFilename.append("valid-enterprise")
        licenseFilename.append("valid-advanced")

        for lFile in licenseFilename:
            v6.addLicense(lFile)

    #TO GO
    def addCreedenceLicenseFiles(self,v6):

        licenseFilename = []
        licenseFilename.append("valid-enterprise-persocket")
        licenseFilename.append("valid-enterprise-peruser")
        licenseFilename.append("valid-enterprise-perccu")
        #licenseFilename.append("valid-xendesktop")
        licenseFilename.append("valid-standard-persocket")
        licenseFilename.append("valid-standard-peruser")
        licenseFilename.append("valid-standard-perccu")

        for lFile in licenseFilename:
            v6.addLicense(lFile)


    def preLicenseHook(self):
        """
        Is the function that will be used to modify the host just before licenses is applied
        """
        pass


    def upgradePool(self):

        #see Line 2045 exec/testcases/xenserver/tc/hotfix.py

        # Update our internal pool object before starting the upgrade
        newP = xenrt.lib.xenserver.poolFactory(xenrt.TEC().lookup("PRODUCT_VERSION", None))(self.systemObj.master)
        self.systemObj.populateSubclass(newP)

        #Perform Rolling Pool Upgrade
        xenrt.TEC().logverbose("Performing rolling pool upgrade of %s" % (self.systemObj.getName()))
        self.systemObj = newP.upgrade(rolling=True)

        self.hosts = self.systemObj.getHosts()

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

    def licenseServer(self, name):
        v6 = self.getGuest(name).getV6LicenseServer()
        v6.removeAllLicenses()
        return v6

    def __parseArgs(self,arglist):

        for arg in arglist:
            if arg.startswith('edition'):
                self.skus = arg.split('=')[1].split(',')
            if arg.startswith('newlicenseserver'):
                self.newLicenseServerName = arg.split('=')[1]
            if arg.startswith('oldlicenseserver'):
                self.oldLicenseServerName = arg.split('=')[1]
            if arg.startswith('oldlicenseedition'):
                self.oldLicenseEdition = arg.split('=')[1]
            if arg.startswith('expectededition'):
                self.expectedEditionAfterUpg = arg.split('=')[1]
            if arg.startswith('grace'):
                self.graceExpected = False
            if arg.startswith('addlicfiles'):
                self.addLicFiles = False

    def checkLicenseExpired(self, host, edition, raiseException=False):
        """ Checking License is expired by checking feature availability.
        Checking date is pointless as TC expires license by changing date."""


        #?? Why is this checking features
        try:
            host.checkHostLicenseState(edition)
            for feature in host.licensedFeatures():
                assertions.assertFalse(feature.hostFeatureFlagValue(host), "Feature flag set for %s " % feature.name)
            return True
        except xenrt.XRTException, e:
            if raiseException:
                raise e
            else:
                xenrt.TEC().logverbose("ERROR: %s" % str(e))
                return False

    def checkGrace(self,host):

        licenseInfo = host.getLicenseDetails()
        if not 'grace' in licenseInfo['grace']:
            raise xenrt.XRTFailure('Host has not got grace license')

        expiry = xenrt.util.parseXapiTime(licenseInfo['expiry'])

        if (expiry > (xenrt.timenow() + 30*25*3600 + 1)):
            raise xenrt.XRTFailure("Host has got license expiry date more than 30 days from current time, it has got expiry date: %s " % expiry)

    def run(self,arglist=None):

        self.preLicenseHook()

        for sku in self.skus:
            licence = self.licenceFactory().licenceForPool(self.systemObj, sku)
            self.licenceManager.applyLicense(licence)
            self.licenceManager.releaseLicense(self.systemObj)

    def postRun(self):
        self.licenceManager.releaseLicense(self.systemObj)


class TCRestartHost(LicenseBase):

    def run(self,arglist=None):

        for sku in self.skus:
            licence = self.licenceFactory.licenceForPool(self.systemObj, sku)
            self.applyLicense(self.v6, self.systemObj, licence)

            self.systemObj.master.reboot()

            self.systemObj.checkHostLicenseState(edition=licence.getEdition())

            self.releaseLicense(self.systemObj)

class ClearwaterUpgrade(LicenseBase):

    def preLicenseHook(self):

        if self.oldLicenseEdition:
            v6 = self.licenseServer(self.oldLicenseServerName)
            if self.oldLicenseEdition != XenServerLicenceSKU.Free.lower():
                licences = self.licenceFactory.allLicences("Clearwater")
                [self.licenseManager.addLicensesToServer(v6, l) for l in licences]
            for host in self.systemObj.hosts:
                host.templicense(edition=self.oldLicenseEdition,v6server=v6)

        self.upgradePool()


    def run(self,arglist=None):

        self.preLicenseHook()

class TCCWOldLicenseServerExp(ClearwaterUpgrade):

    def preLicenseHook(self):

        super(TCCWOldLicenseServerExp, self).preLicenseHook()

        self.systemObj.checkHostLicenseState(edition=self.expectedEditionAfterUpg)

        for host in self.hosts:
            self.checkGrace(host)

        #Expire the host

class TCCWOldLicenseServerUpg(ClearwaterUpgrade):

    def preLicenseHook(self):

        super(TCCWOldLicenseServerUpg, self).preLicenseHook()

        self.systemObj.checkHostLicenseState(edition=self.expectedEditionAfterUpg)

        for host in self.hosts:
            self.checkGrace(host)

        self.applyLicense(self.getLicenseObj(self.expectedEditionAfterUpg))

        self.releaseLicense(self.expectedEditionAfterUpg)

class TCCWNewLicenseServer(ClearwaterUpgrade):

    def preLicenseHook(self):

        if self.oldLicenseEdition:
            v6 = self.licenseServer(self.oldLicenseServerName)

            if self.oldLicenseEdition != 'free':
                #self.addCWLicenseFiles(v6) #REPLACE
                self.addCWLicenseFiles(self.v6)

            for host in self.hosts:
                host.templicense(edition=self.oldLicenseEdition,v6server=v6)

            for host in self.hosts:
                host.templicense(edition=self.oldLicenseEdition,v6server=self.v6)

        if self.addLicFiles:
            self.addCreedenceLicenseFiles(self.v6)
        else:
            self.v6.removeAllLicenses()

        self.upgradePool()
        #self.updateLicenseObjs()
        for host in self.hosts:
            isExpRaised = False
            try:
                self.checkGrace(host)
                isExpRaised = True
            except Exception as e:
                pass
            if isExpRaised:
                raise xenrt.XRTFailure("Host has got grace license")

        self.systemObj.checkHostLicenseState(edition=self.expectedEditionAfterUpg)

        self.releaseLicense(self.expectedEditionAfterUpg,verifyLicenseServer=False)

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
                wlbprevstatus = details["restrict_wlb"]
                if self.oldLicenseEdition == "advanced" and not(wlbprevstatus == "true"):
                    raise xenrt.XRTFailure('Advance Tampa Host has wlb enabled')
                elif self.oldLicenseEdition == "platinum" and not (wlbprevstatus=="false"):
                    raise xenrt.XRTFailure('Platinum Tampa Host has wlb disabled')
        self.addCreedenceLicenseFiles(v6)

        self.upgradePool()

        #self.updateLicenseObjs()
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
        if self.expectedEditionAfterUpg != "free":
            self.applyLicense(self.getLicenseObj(self.expectedEditionAfterUpg))
            self.releaseLicense(self.expectedEditionAfterUpg,verifyLicenseServer=False)

class TCTPNewLicenseServer(TampaUpgrade):
#U3.1 , C8

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
            self.addCreedenceLicenseFiles(self.v6)

        self.upgradePool()

        #self.updateLicenseObjs()
        for host in self.hosts:
            isExpRaised = False
            try:
                self.checkGrace(host)
                isExpRaised = True
            except Exception as e:
                pass
            if isExpRaised:
                raise xenrt.XRTFailure("Host has got grace license")

        #The host will be in licensed state depending upon its previous license
        self.systemObj.checkHostLicenseState(edition=self.expectedEditionAfterUpg)
        self.releaseLicense(self.expectedEditionAfterUpg,verifyLicenseServer=False)

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


        self.upgradePool()
        #self.updateLicenseObjs()

        #Verify that the Tampa Host is having expected edition but in expired state as the creedence license files are not available in license server.
        for host in self.hosts :
            if not self.checkLicenseExpired(host, edition=self.expectedEditionAfterUpg):
                raise xenrt.XRTFailure("License is not expired properly.")

        if self.expectedEditionAfterUpg != "free":
            #Now upload creedence license files into license server and license the host
            self.applyLicense(self.getLicenseObj(self.expectedEditionAfterUpg))

            #The host gets the license depending upon its previous license
            self.systemObj.checkHostLicenseState(edition=self.expectedEditionAfterUpg)
            self.releaseLicense(self.expectedEditionAfterUpg,verifyLicenseServer=False)


class LicenseExpiryBase(LicenseBase):
    """
    TC for Creedence (and later) license expiration test.
    """

    def expireLicense(self, allhosts=False):
        """Select a host and force expire the license of the host."""

        if allhosts:
            hosts = self.systemObj.getHosts()
        else:
            hosts = [random.choice(self.systemObj.getHosts())]

        expiretime = xenrt.util.timenow() + 300
        for host in hosts:
            self.__forceExpireLicense(host, expiretime)

        # return just an expired host for a reference.
        # If allhosts == True, list of expired hosts are same as hosts in the pool
        return hosts[0]

    def __forceExpireLicense(self, host, expiretime=-1):
        """ Force Expire license from a host by changing expiry date."""

        # Enable the license expires in 5 minutes
        if expiretime < 0:
            expiretime = xenrt.util.timenow() + 300
        # Convert this to a Xapi timestamp
        xapitime = xenrt.util.makeXapiTime(expiretime)
        # Write it in to the FIST file
        host.execdom0("echo '%s' > /tmp/fist_set_expiry_date" % (xapitime))
        # Restart xapi
        host.restartToolstack()
        host.waitForEnabled(300)

        # Give some time (5 mins + 30 secs) to expire the license.
        xenrt.sleep(330)

    def checkLicenseExpired(self, edition, host=None, timeout=1800):
        """ Checking license expiry while timeout period.
            Feature limit may not be applied for some time perios."""


        host = self.systemObj.master

        starttime = xenrt.util.timenow()
        while (xenrt.util.timenow() <= starttime + timeout):
            xenrt.sleep(120)
            if self.__checkLicenseTimePassed(host):
                ret = self.__checkLicenseExpiredFunc(host, edition)
                if ret:
                    return True

        xenrt.TEC().logverbose("XAPI is not updated after license expired for %d seconds." % timeout)

        return False

    def __checkLicenseTimePassed(self, host):
        """ Checking License is expired by checking time"""

        # This is hack. It is probably better to have this function in Lincese
        # class and call this from base class of TC should be better.
        # Checking parameter directly from TC is not recommendable.
        xenrt.TEC().logverbose("Checking host expiry date is passed.")
        licdet = host.getLicenseDetails()
        if not "expiry" in licdet:
            raise xenrt.XRTError("expiry field is not in the license detail.")
        if xenrt.util.timenow() > xenrt.util.parseXapiTime(licdet['expiry']):
            if not self.isHostObj:
                xenrt.TEC().logverbose("Checking pool expiry date is passed.")
                poolParams = self.systemObj.getPoolParam("license-state")
                match = re.search("expiry: ([^\s]+)", poolParams)
                if match:
                    expiry = match.groups()[0]
                    if expiry == "never":
                        xenrt.TEC().logverbose("License-state of pool has set to 'never'.")
                        return False
                    if expiry != licdet['expiry']:
                        xenrt.TEC().logverbose("Pool license expiry date mismatch with host expiry date.")

                        xenrt.TEC().logverbose("Pool license expiry: %s host expiry: %s." % (expiry, licdet['expiry']))
                        return False
                    return True
                else:
                    xenrt.TEC().logverbose("Cannot find expiry information from pool license-state.")
                    return False
            else:
                return True

        xenrt.TEC().logverbose("License has not expired yet.")
        return False

    def __checkLicenseExpiredFunc(self, host, edition):
        """ Checking License is expired by checking feature availability.
        Checking date is not reliable as TC expires license using fist point."""

        xenrt.TEC().logverbose("Checking host feature set.")
        hfeatures = [feature.hostFeatureFlagValue(host, True)
            for feature in host.licensedFeatures()]
        if hfeatures[0] and hfeatures[1] and hfeatures[2]:
            if not self.isHostObj:
                xenrt.TEC().logverbose("Checking pool feature set.")
                pfeatures = [feature.poolFeatureFlagValue(self.systemObj)
                    for feature in host.licensedFeatures()]
                if pfeatures[0] and pfeatures[1] and pfeatures[2]:
                    return True
                else:
                    xenrt.TEC().logverbose("Restriction flags of pool has not been updated while ones of host(s) are updated as expected.")
            else:
                return True
        return False

    def cleanUpFistPoint(self, host=None):
        if host:
            hosts = [host]
        else:
            hosts = self.hosts

        for host in hosts:
            host.execdom0("rm -f /tmp/fist_set_expiry_date", level=xenrt.RC_OK)

    def run(self, arglist=[]):
        pass

    def postRun(self):
        self.cleanUpFistPoint()
        super(LicenseExpiryBase, self).postRun()


class TCLicenseExpiry(LicenseExpiryBase):
    """ Expiry test case """

    def licenseExpiryTest(self, edition):

        # Assign license and verify it.
        self.applyLicense(self.getLicenseObj(edition))
        self.systemObj.checkHostLicenseState(edition=edition)

        # Check only for WLB, read cache and vgpu.
        skipped = False
        host = self.systemObj.master
        features = [feature.hostFeatureFlagValue(host) for feature in host.licensedFeatures().values()]
        xenrt.TEC().logverbose("License: %s, WLB: %s, Read cache: %s, VGPU: %s" %
            (edition, not features[0], not features[1], not features[2]))

        if features[0] and features[1] and features[2]:
            skipped = True
            xenrt.TEC().logverbose("No features are available for this license. Skipping expire test.")
        else:
            # Expiry test
            self.expireLicense(True)
            if not self.checkLicenseExpired(edition):
                raise xenrt.XRTFailure("License is not expired properly.")

        # Cleaning up.
        self.releaseLicense(edition)
        self.cleanUpFistPoint()

        if skipped:
            raise xenrt.XRTSkip("%s does not have any feature." % edition)

    def run(self, arglist=[]):

        self.preLicenseHook()

        for edition in self.skus:
            self.runSubcase("licenseExpiryTest", edition, "Expiry - %s" % edition, "Expiry")

class TCLicenseGrace(LicenseExpiryBase):
    """Verify the grace license and its expiry in Creedence hosts"""

    def disableLicenseServer(self):
        """Disconnect license server"""

        self.v6.stop()
        xenrt.sleep(120)

        # Restart toostack on every hosts.
        [host.restartToolstack() for host in self.hosts]

    def enableLicenseServer(self):
        """Re-establish license server connection"""

        self.v6.start()
        xenrt.sleep(120)
        
        # Restart toostack on every hosts.
        [host.restartToolstack() for host in self.hosts]

    def checkGraceLicense(self, host, timeout=3600):
        """ Checking whether the grace license enabled"""

        starttime = xenrt.util.timenow()
        while (xenrt.util.timenow() <= starttime + timeout):
            xenrt.sleep(120)
            ret = self.checkGraceFunc(host)
            if ret:
                return True

        xenrt.TEC().logverbose("XAPI is not updated after license server is disconnected. (Took %d seconds)" % timeout)

        return False

    def checkGraceFunc(self,host):
  
        licenseInfo = host.getLicenseDetails()
        if not 'grace' in licenseInfo['grace']:
            xenrt.TEC().warning("ERROR: Host has not got grace license")
            return False

        expiry = xenrt.util.parseXapiTime(licenseInfo['expiry'])
        if (expiry > (xenrt.timenow() + 30*25*3600 + 1)):
            xenrt.TEC().warning("ERROR: Host has got license expiry date > 30 days from current time,"
                                " it has got expiry date: %s " % expiry)
            return False

        return True

    def licenseGraceTest(self, edition):

        # Assign license and verify it.
        self.applyLicense(self.getLicenseObj(edition))

        # Force the host to have grace license.
        self.disableLicenseServer()

        # Check whether the hosts obtained grace licenses.
        for host in self.hosts:
            if not self.checkGraceLicense(host):
                self.enableLicenseServer()
                self.releaseLicense(edition)
                raise xenrt.XRTFailure("The host %s is failed to aquire grace license" % host)

        # Force the hosts to regain its orignal licenses.
        self.enableLicenseServer()

        # Check whether the hosts regained the original licenses.
        self.systemObj.checkHostLicenseState(edition=edition)
        self.verifyLicenseServer(edition)

        # Again force the host to have grace license.
        self.disableLicenseServer()

        # Check whether the hosts obtained grace licenses.
        for host in self.hosts:
            if not self.checkGraceLicense(host):
                self.enableLicenseServer()
                self.releaseLicense(edition)
                raise xenrt.XRTFailure("The host %s is failed to aquire grace license again" % host)

        # Now expire one of the host license such that it cross the grace period.
        host = self.expireLicense() # for both hosts expire, provide allhosts=True

        # Check whether the license is expired.
        if not self.checkLicenseExpired(edition, host): # for all hosts just provide the param edition.
            self.enableLicenseServer()
            self.releaseLicense(edition)
            raise xenrt.XRTFailure("License is not expired properly.")

        # Check whether the hosts license expired.
        self.systemObj.checkHostLicenseState(edition=edition)

        # Cleaning up.
        self.enableLicenseServer()
        self.releaseLicense(edition)
        self.cleanUpFistPoint(host) # if any.

    def run(self, arglist=[]):

        for edition in self.skus:
            if edition == "free":
                # Free license does not require grace license test.
                xenrt.TEC().logverbose("Free license does not require grace license test")
                continue

            self.runSubcase("licenseGraceTest", edition, "Grace - %s" % edition, "Grace")
