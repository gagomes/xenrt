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
from xenrt.lib.xenserver.licensing import LicenceManager, XenServerLicenceFactory
from xenrt.lib import assertions
from xenrt.enum import XenServerLicenceSKU
from xenrt.lib.xenserver.licensedfeatures import *


class LicenseBase(xenrt.TestCase, object):

    def __init__(self):
        super(LicenseBase,self).__init__()
        self.licenceManager = LicenceManager()
        self.licenceFactory = XenServerLicenceFactory()
        self.licenceFeatureFactory = LicensedFeatureFactory()
        self.skus = []
        self.hosts = []
        self.newLicenseServerName = 'LicenseServer'
        self.oldLicenseEdition = None
        self.oldLicenseServerName = None
        self.graceExpected = False
        self.systemObj = None
        self.v6 = None
        self.addLicenseFile = False 

    def prepare(self,arglist):

        if self.getDefaultPool():
            self.systemObj =  self.getDefaultPool()
        else:
            self.systemObj = self.getHost("RESOURCE_HOST_1").getPool()

        self.__parseArgs(arglist)

        self.v6 = self.licenseServer(self.newLicenseServerName)

    def upgradePool(self):

        # Update our internal pool object before starting the upgrade
        newP = xenrt.lib.xenserver.poolFactory(xenrt.TEC().lookup("PRODUCT_VERSION", None))(self.systemObj.master)
        self.systemObj.populateSubclass(newP)

        #Perform Rolling Pool Upgrade
        xenrt.TEC().logverbose("Performing rolling pool upgrade of %s" % (self.systemObj.getName()))
        self.systemObj = newP.upgrade(rolling=True)


    def licenseServer(self, name):
        v6 = self.getGuest(name).getV6LicenseServer()
        v6.removeAllLicenses()
        return v6

    def __parseArgs(self,arglist):

        for arg in arglist:
            if arg.startswith('sku'):
                self.skus = arg.split('=')[1].split(',')
            if arg.startswith('newlicenseserver'):
                self.newLicenseServerName = arg.split('=')[1]
            if arg.startswith('oldlicenseserver'):
                self.oldLicenseServerName = arg.split('=')[1]
            if arg.startswith('oldlicensesku'):
                self.oldLicenseSku = arg.split('=')[1]
            if arg.startswith('expectedsku'):
                self.expectedSku = arg.split('=')[1]
            if arg.startswith('grace'):
                self.graceExpected = True
            if arg.startswith('addlicfiles'):
                self.addLicenseFile = True

    def checkGrace(self,host):

        licenseInfo = host.getLicenseDetails()
        if not 'grace' in licenseInfo['grace']:
            xenrt.TEC().logverbose('Host has not got grace license')
            return False

        expiry = xenrt.util.parseXapiTime(licenseInfo['expiry'])

        if (expiry > (xenrt.timenow() + 30*25*3600 + 1)):
            raise xenrt.TEC().logverbose("Host has got license expiry date more than 30 days from current time, it has got expiry date: %s " % expiry)

        return True

    def checkLicenseExpired(self,host):

        licenseInfo = host.getLicenseDetails()
        if '19700101T00:00:00Z' != licenseInfo['expiry']:
            return False

        return True

    def featureFlagValidation(self,license=None):
        #No license if license has expired or host/pool is not licensed
        err = []
        if not license:
            license = self.licenceFactory.licenceForPool(self.systemObj,XenServerLicenceSKU.Free)

        features = self.licenceFeatureFactory.allFeatureObj(self.systemObj.master)
        hosts = self.systemObj.getHosts()
        for feature in features:
            if not feature.poolFeatureFlagValue(self.systemObj) == self.licenceFeatureFactory.getFeatureState(self.systemObj.master.productVersion,
                license.sku,feature):
                err.append("Pool level feature flag for feature %s is not same as expected" % (feature.name))

            for host in hosts:
                if not feature.hostFeatureFlagValue(host) == self.licenceFeatureFactory.getFeatureState(host.productVersion,
                license.sku,feature):
                    err.append("Host level feature flag for feature %s is not same as expected" % (feature.name))

        if err:
            raise xenrt.XRTFailure(err)

    def run(self,arglist=None):

        for sku in self.skus:
            licence = self.licenceFactory.licenceForPool(self.systemObj, sku)
            licenseinUse = self.licenceManager.addLicensesToServer(self.v6,licence)
            self.licenceManager.applyLicense(self.v6, self.systemObj, licence, licenseinUse)
            self.featureFlagValidation(licence)
            self.licenceManager.releaseLicense(self.systemObj)
            self.featureFlagValidation()
            self.licenceManager.verifyLicenseServer(licence,self.v6,licenseinUse, self.systemObj,reset=True)

    def postRun(self):
        self.licenceManager.releaseLicense(self.systemObj)


class TCRestartHost(LicenseBase):

    def run(self,arglist=None):

        for sku in self.skus:
            licence = self.licenceFactory.licenceForPool(self.systemObj, sku)
            licenseinUse = self.licenceManager.addLicensesToServer(self.v6,licence)
            self.licenceManager.applyLicense(self.v6, self.systemObj, licence,licenseinUse)
            self.featureFlagValidation(licence)
            self.systemObj.master.reboot()
            self.systemObj.checkLicenseState(edition=licence.getEdition())
            self.featureFlagValidation(licence)
            self.licenceManager.releaseLicense(self.systemObj)
            self.featureFlagValidation()
            self.licenceManager.verifyLicenseServer(licence,self.v6,licenseinUse, self.systemObj,reset=True)


class TCUpgrade(LicenseBase):

    def run(self,arglist=None):

        v6 = self.v6
        hosts = self.systemObj.getHosts()
        if self.oldLicenseServerName:
            v6 = self.licenseServer(self.oldLicenseServerName)

        if self.oldLicenseSku != XenServerLicenceSKU.Free:
            licence = self.licenceFactory.licenceForPool(self.systemObj, self.oldLicenseSku)
            self.licenceManager.addLicensesToServer(v6,licence,getLicenseInUse=False)

        for host in hosts:
            host.license(edition=licence.getEdition(), usev6testd=False, v6server=v6)

        productVer = xenrt.TEC().lookup("PRODUCT_VERSION")
        licence = self.licenceFactory.licence(productVer,self.expectedSku)

        if self.addLicenseFile:
            licenseinUse = self.licenceManager.addLicensesToServer(v6,licence)
        else:
            v6.removeAllLicenses()

        self.upgradePool()
        hosts = self.systemObj.getHosts()
        if self.graceExpected:
            for host in hosts:
                if not self.checkGrace(host):
                    raise xenrt.XRTFailure("Host has not got grace licence")
                else:
                    self.featureFlagValidation(licence)
        else:
            for host in hosts:
                if self.checkGrace(host):
                    raise xenrt.XRTFailure("Host has got grace licence")

        self.systemObj.checkLicenseState(edition=licence.getEdition())
        if self.oldLicenseServerName:
            v6 = self.v6
            licenseinUse = self.licenceManager.addLicensesToServer(v6,licence)
            self.featureFlagValidation(licence)
            self.licenceManager.applyLicense(v6,self.systemObj,licence,licenseinUse)

        if self.addLicenseFile or self.oldLicenseServerName:
            self.licenceManager.verifyLicenseServer(licence,v6,licenseinUse, self.systemObj)
            self.featureFlagValidation(licence)
        else:
            for host in hosts:
                if not self.checkLicenseExpired(host):
                    raise xenrt.XRTFailure("Host License has not expired")
                else:
                    self.featureFlagValidation()


class TestFeatureBase(LicenseBase):

    def run(self, arglist=None):
        for sku in self.skus:
            xenrt.TEC().logverbose("Testing SKU: %s" % sku)
            self.confirmLicenseServerUp()

            self.licence = self.licenceFactory.licenceForHost(self.systemObj.master, sku)

            # Apply the currrent license.
            licenseinUse = self.licenceManager.addLicensesToServer(self.v6,self.licence)
            self.licenceManager.applyLicense(self.v6, self.systemObj, self.licence,licenseinUse)
            self.systemObj.checkLicenseState(edition=self.licence.getEdition())

            self.checkFeature(sku)

            self.licenceManager.releaseLicense(self.systemObj)

            xenrt.TEC().logverbose("Finished testing SKU: %s" % sku)

    def checkFeature(self, currentSKU):
        """
        Abstract, to be overwritten with feature specific test steps.
        currentSKU: The current license sku being tested.
        """
        pass

    def confirmLicenseServerUp(self):
        ls = self.getGuest(self.newLicenseServerName)
        if (ls.getState() != "UP"):
            ls.setState("UP")
        self.v6.start()


class TCReadCachingFeature(TestFeatureBase):

    def checkFeature(self, currentSKU):
        # Restrict read caching = True / False
        feature = ReadCaching()
        featureResctictedFlag = feature.hostFeatureFlagValue(self.systemObj.master)
        featureRestricted = self.licenceFeatureFactory.getFeatureState(self.systemObj.master.productVersion, currentSKU, feature)

        assertions.assertEquals(featureRestricted,
            featureResctictedFlag,
            "Feature flag on host does not match actual permissions. Feature allowed: %s, Feature restricted: %s" % (featureRestricted, featureResctictedFlag))

        # Check read caching values before any VMs.
        enabledList = feature.isEnabled(self.systemObj.master)
        assertions.assertFalse(True in enabledList, "Read Caching is enabled before any VMs created.")

        # Create VM..
        guest = self.systemObj.master.createGenericLinuxGuest(sr="nfsstorage")

        # Check we have the right read caching priviledge.
        enabledList = feature.isEnabled(self.systemObj.master)
        assertions.assertEquals(not featureRestricted,
            True in enabledList,
            "Read caching restriction is not as expected after creating new VM. Should be: %s" % (featureRestricted))

        # Remove License.
        self.licenceManager.releaseLicense(self.systemObj)

        # Check, should still the same RC privilidge.
        enabledList = feature.isEnabled(self.systemObj.master)
        assertions.assertEquals(not featureRestricted,
            True in enabledList,
            "Read caching restriction is not as expected after removing license, but not performing lifecycle / tootstack restart. Should be: %s" % (featureRestricted))

        guest.reboot()

        # Check flag again
        # Should be restricted after removing license.
        featureResctictedFlag = feature.hostFeatureFlagValue(self.systemObj.master)
        assertions.assertTrue(featureResctictedFlag,
            "Feature flag is not restricted after removing license. Feature restricted: %s" % (featureResctictedFlag))

        # Check that read caching is now disabled.
        enabledList = feature.isEnabled(self.systemObj.master)
        assertions.assertFalse(True in enabledList, "Read Caching is enabled after removing license and lifecycle operation.")

        guest.uninstall()

class TCWLBFeature(TestFeatureBase):

    def checkFeature(self, currentSKU):
        self.systemObj.master.execdom0("xe host-license-view")

        feature = WorkloadBalancing()
        featureRestricted = self.licenceFeatureFactory.getFeatureState(self.systemObj.master.productVersion, currentSKU, feature)

        featureResctictedFlag = feature.hostFeatureFlagValue(self.systemObj.master)
        assertions.assertEquals(featureRestricted,
            featureResctictedFlag,
            "Feature flag on host does not match actual permissions. Feature allowed: %s, Feature restricted: %s" % (featureRestricted, featureResctictedFlag))

        self.licenceManager.releaseLicense(self.systemObj)

        self.systemObj.master.execdom0("xe host-license-view")

        featureResctictedFlag = feature.hostFeatureFlagValue(self.systemObj.master)
        assertions.assertTrue(featureResctictedFlag,
            "Feature flag is not restricted after removing license. Feature restricted: %s" % (featureResctictedFlag))

class TCVirtualGPUFeature(TestFeatureBase):

    def checkFeature(self, currentSKU):
        # Check flag and feature on licensed host.
        feature =  VirtualGPU()
        featureRestricted = self.licenceFeatureFactory.getFeatureState(self.systemObj.master.productVersion, currentSKU, feature)
        featureResctictedFlag = feature.hostFeatureFlagValue(self.systemObj.master)
        assertions.assertEquals(featureRestricted,
            featureResctictedFlag,
            "Feature flag on host does not match actual permissions. Feature allowed: %s, Feature restricted: %s" % (featureRestricted, featureResctictedFlag))

        enabledList = feature.isEnabled(self.systemObj.master)
        self.confirmLicenseServerUp()
        assertions.assertEquals(not featureRestricted,
            True in enabledList,
            "vGPU privilidge is not as expected after creating new VM. Should be: %s" % (featureRestricted))

        # Unlicense host.
        self.licenceManager.releaseLicense(self.systemObj)

        # Check flag and functionality again, after removing license.
        featureResctictedFlag = feature.hostFeatureFlagValue(self.systemObj.master)
        assertions.assertTrue(featureResctictedFlag,
            "Feature flag is not restricted after removing license. Feature restricted: %s" % (featureResctictedFlag))


        enabledList = feature.isEnabled(self.systemObj.master)
        self.confirmLicenseServerUp()
        assertions.assertFalse(True in enabledList, "vGPU is enabled after removing license and lifecycle operation.")

class LicenseExpiryBase(LicenseBase):
     #TC for Creedence (and later) license expiration test.


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

    def checkLicenseExpired(self, host=None, timeout=1800):
        """ Checking license expiry while timeout period.
            Feature limit may not be applied for some time perios."""

        if not host:
            host = self.systemObj.master
        ret = False
        starttime = xenrt.util.timenow()
        while (xenrt.util.timenow() <= starttime + timeout):
            xenrt.sleep(120)
            if self.__checkLicenseTimePassed(host):
                try:
                    self.featureFlagValidation()
                    ret = True
                except Exception, e:
                    pass 
                if ret:
                    return True

        xenrt.TEC().logverbose("XAPI is not updated after license expired for %d seconds." % timeout)

        return False

    def __checkLicenseTimePassed(self, host):
        """ Checking License is expired by checking time"""

        xenrt.TEC().logverbose("Checking host expiry date is passed.")
        licdet = host.getLicenseDetails()
        if not "expiry" in licdet:
            raise xenrt.XRTError("expiry field is not in the license detail.")
        if xenrt.util.timenow() > xenrt.util.parseXapiTime(licdet['expiry']):
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

        xenrt.TEC().logverbose("License has not expired yet.")
        return False

    def cleanUpFistPoint(self, host=None):
        if host:
            hosts = [host]
        else:
            hosts = self.systemObj.getHosts()
        for host in hosts:
            host.execdom0("rm -f /tmp/fist_set_expiry_date", level=xenrt.RC_OK)

    def run(self, arglist=[]):
        pass

    def postRun(self):
        self.cleanUpFistPoint()
        super(LicenseExpiryBase, self).postRun()


class TCLicenseExpiry(LicenseExpiryBase):
    """ Expiry test case """

    def licenseExpiryTest(self, sku):
        # Assign license and verify it.
        licence = self.licenceFactory.licenceForPool(self.systemObj, sku)
        licenseinUse = self.licenceManager.addLicensesToServer(self.v6,licence)
        self.licenceManager.applyLicense(self.v6, self.systemObj, licence,licenseinUse)
        self.featureFlagValidation(licence)
        # Expiry test
        self.expireLicense(True)
        if not self.checkLicenseExpired():
            raise xenrt.XRTFailure("License is not expired properly.")

        # Cleaning up.
        self.licenceManager.releaseLicense(self.systemObj)
        self.featureFlagValidation()
        self.licenceManager.verifyLicenseServer(licence,self.v6,licenseinUse, self.systemObj,reset=True)
        self.cleanUpFistPoint()

    def run(self, arglist=[]):
        for sku in self.skus:
            self.runSubcase("licenseExpiryTest", sku, "Expiry - %s" % sku, "Expiry")

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

    def licenseGraceTest(self, licence):

        # Assign license and verify it.
        licenseinUse = self.licenceManager.addLicensesToServer(self.v6,licence)
        self.licenceManager.applyLicense(self.v6, self.systemObj, licence,licenseinUse)
        # Force the host to have grace license.
        self.disableLicenseServer()

        # Check whether the hosts obtained grace licenses.
        for host in self.systemObj.getHosts():
            if not self.checkGraceLicense(host):
                self.enableLicenseServer()
                self.licenceManager.releaseLicense(self.systemObj)
                raise xenrt.XRTFailure("The host %s is failed to aquire grace license" % host)
            else:
                self.featureFlagValidation(licence)

        # Force the hosts to regain its orignal licenses.
        self.enableLicenseServer()

        # Check whether the hosts regained the original licenses.
        self.systemObj.checkLicenseState(edition=licence.getEdition())
        self.licenceManager.verifyLicenseServer(licence,self.v6,licenseinUse, self.systemObj)

        # Again force the host to have grace license.
        self.disableLicenseServer()

        # Check whether the hosts obtained grace licenses.
        for host in self.hosts:
            if not self.checkGraceLicense(host):
                self.enableLicenseServer()
                self.licenceManager.releaseLicense(self.systemObj)
                raise xenrt.XRTFailure("The host %s is failed to aquire grace license again" % host)
            else:
                self.featureFlagValidation(licence)

        # Now expire one of the host license such that it cross the grace period.
        host = self.expireLicense() # for both hosts expire, provide allhosts=True

        # Check whether the license is expired.
        if not self.checkLicenseExpired(host): # for all hosts just provide the param edition.
            self.enableLicenseServer()
            self.licenceManager.releaseLicense(self.systemObj)
            raise xenrt.XRTFailure("License is not expired properly.")
        else:
            self.featureFlagValidation()

        # Check whether the hosts license expired.
        self.systemObj.checkLicenseState(edition=licence.getEdition())

        # Cleaning up.
        self.enableLicenseServer()
        self.licenceManager.releaseLicense(self.systemObj)
        self.featureFlagValidation()
        self.cleanUpFistPoint(host) # if any.

    def run(self, arglist=[]):

        for sku in self.skus:
            if sku == XenServerLicenceSKU.Free:
                # Free license does not require grace license test.
                xenrt.TEC().logverbose("Free license does not require grace license test")
                continue
            licence = self.licenceFactory.licenceForPool(self.systemObj, sku) 
            self.runSubcase("licenseGraceTest", licence, "Grace - %s" % licence, "Grace")

