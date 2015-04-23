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

class SingleSkuBase(xenrt.TestCase):

    USELICENSESERVER = True
    EXPIRED = False
    LICENSEFILE = ''
    LICENSENAME = ''
    v6 = None
    NEED_LINUX_VM = True
    grace = xenrt.TEC().lookup("GRACE", default=None)

    def prepare(self,arglist=None):
    
        self.parseArgs(arglist)
        self.setParam()
        self.addLicense()
        if self.NEED_LINUX_VM:
            sampleGuest = self.getGuest("linux")      
            if sampleGuest.getState() == "DOWN":
                sampleGuest.start() 
 
    def parseArgs(self,arglist):

        self.args = {}

        for arg in arglist:
            if arg.startswith('system'):
                self.args['system'] = arg.split('=')[1]
            if arg.startswith('edition'):
                self.args['edition'] = arg.split('=')[1]

    def licenseName(self):

        return xenrt.TEC().lookup("LICENSE_NAME","CXS_STD_CCS")

    def setParam(self):

        self.param = {}

        if not self.args.has_key('system'):
            raise xenrt.XRTFailure("Site type is not defined in seq file")
        if not self.args.has_key('edition'):
            raise xenrt.XRTFailure("Edition is not defined in seq file")

        self.param['hosts'] = []

        if self.args['system'].startswith('pool'):

            self.param['system'] = "pool"
            self.param['poolObj'] = self.getDefaultPool()
            self.param['hosts'] = self.param['poolObj'].getHosts()

        elif self.args['system'].startswith('site'):

            self.param['system'] = "site"
            self.param['poolObj'] = self.getDefaultPool()
            self.param['hosts'] = self.param['poolObj'].getHosts()

        elif self.args['system'].startswith('host'):

            self.param['system'] = "host"
            self.param['hosts'] = [self.getHost("RESOURCE_HOST_1")]

        else:
            raise xenrt.XRTFailure("Unknown Site type")

        if self.LICENSEFILE:
            self.LICENSENAME = self.licenseName()
            self.param['edition'] = self.args['edition']
            return

        if (self.args['edition'].startswith('per-socket') or self.args['edition'].startswith('xendesktop') or self.args['edition'].startswith('free')):

            self.param['edition'] = self.args['edition']

            if self.param['edition'].startswith('free'):
                self.USELICENSESERVER = False   

            if self.param['edition'].startswith('xendesktop'):
                if self.param['system'].startswith('site'):
                    self.LICENSEFILE = "valid-xendesktop"
                    self.LICENSENAME = "XDS_STD_CCS"
                else:
                    raise xenrt.XRTFailure("Edition is not matching with Site")

            elif not ((self.param['edition'].startswith('per-socket') or self.param['edition'].startswith('free')) and (self.param['system'].startswith('host') or self.param['system'].startswith('pool'))):
                raise xenrt.XRTFailure("Edition is not matching with pool/host")
            else:
                if self.param['edition'].startswith('per-socket'):
                    self.LICENSEFILE = "valid-persocket"
                    self.LICENSENAME = self.licenseName()
        else:
            raise xenrt.XRTFailure("Unknown license type")
        
    def updateLicenseSerInfo(self):

        guest = self.getGuest("LicenseServer")
        self.v6 = guest.getV6LicenseServer()
  
    def updateLicenseCount(self):

        if self.USELICENSESERVER:

            self.param['totallicense'],self.param['licenseinuse'] = self.v6.getLicenseInUse(self.LICENSENAME)

    def addLicense(self):

        if self.USELICENSESERVER:
            self.licenseServer()

    def licenseServer(self):

        self.guest = self.getGuest("LicenseServer")
        self.v6 = self.guest.getV6LicenseServer()
        self.v6.removeAllLicenses()

        if self.LICENSEFILE:
            self.v6.addLicense(self.LICENSEFILE)
            self.updateLicenseCount()

    def preLicenseApplyAction(self):

        self.verifySystemLicenseState(edition='free')

    def postLicenseApplyAction(self):

        xenrt.TEC().logverbose("Not implemented")
        pass

    def applyLicense(self):

        v6server = None
        obj = None

        if self.USELICENSESERVER:
            v6server = self.v6

        edition = self.param['edition']

        if self.param['system'] == 'host':
            obj = self.param['hosts'][0]
        else:
            obj = self.param['poolObj']

        obj.license(edition= edition, v6server = v6server)

    def resetSystem(self):
       
        self.param['edition'] = 'free'
 
        self.applyLicense()

        if not self.USELICENSESERVER:
            for host in self.param['hosts']:
                host.installv6dRPM()

    def verifySystemLicenseState(self,edition = None, licensed = False):

        if not edition:
            ed = self.param['edition']
        else:
            ed = edition

        for host in self.param['hosts']:
            host.checkHostLicenseState(ed,licensed)

    def verifyLicenseServer(self,reset = False):

        if self.USELICENSESERVER:

            system = self.param['system']            

            if not self.EXPIRED :
                tmp , currentLicinuse = self.v6.getLicenseInUse(self.LICENSENAME)
                if system == 'pool' or system == 'host':

                    if system == 'pool':
                        obj = self.param['poolObj']
                    elif system == 'host':
                        obj = self.param['hosts'][0] 

                    if not reset:
                        if not ((obj.getNoOfSockets() + self.param['licenseinuse']) == currentLicinuse):
                            raise xenrt.XRTFailure("No of licenses in use: %d , no of socket in whole pool: %d,"
                                " number of licenses that were in use before operation: %d " %(currentLicinuse,obj.getNoOfSockets(),self.param['licenseinuse']))              
                    else:
                        if not (currentLicinuse == self.param['licenseinuse']):    
                            raise xenrt.XRTFailure("All the licenses are not returned to License server,"
                                "Current License in use: %d, total licenses that were in use before operation: %d " % (currentLicinuse,self.param['licenseinuse']))

                elif system == 'site':
                
                    if not (currentLicinuse == 0):
                        raise xenrt.XRTFailure("No of lincenses in use: %d" % (currentLicinuse))                      
 
    def hotfixStatus(self):
    
        allhosts = True
        anyhosts = False
        
        if self.param['system'] == 'host':
        
            obj = self.param['hosts'][0]
            return self.hotfixStatusHost(obj)
            
        elif (self.param['system'] == 'pool' or self.param['system'] == 'site'):
        
            obj = self.param['poolObj']
            restrictions = obj.getPoolParam("restrictions")
            regExp = ' restrict_hotfix_apply: (\w+)'
            match = re.search(regExp,restrictions)
            if match:
                pool_hotfix_status = match.group(1).strip()
                xenrt.TEC().logverbose("Pool restrict-hotfix-apply status is %s" %str(pool_hotfix_status))
                if pool_hotfix_status == "true":
                    pool_hotfix_status = True
                else:
                    pool_hotfix_status = False 
                    
            else:
                raise xenrt.XRTFailure("Parameter restrict_hotfix_ not found.")            
            
            for h in self.param['hosts']:
                x = self.hotfixStatusHost(h)
                allhosts = allhosts and x
                anyhosts = anyhosts or x
               
                
            if pool_hotfix_status :
                if anyhosts :
                    return pool_hotfix_status
                else :
                    raise xenrt.XRTException("Hotfix application is Restricted for pool but for all of its member hosts its Allowed")
            else :
                if not allhosts :
                    return pool_hotfix_status
                else :
                    raise xenrt.XRTException("Hotfix application is Allowed for pool but not for all of its member hosts ")
        
    def hotfixStatusHost(self , host):
    
        details = host.getLicenseDetails()
        hotfixstatushost = details["restrict_hotfix_apply"]
        xenrt.TEC().logverbose("Host %s restrict-hotfix-apply status is %s" %(host , str(hotfixstatushost)))
        if details["restrict_hotfix_apply"] == "true":
            return True
        else:
            return False
    
    def poolUpgrade(self):         
        
        xenrt.TEC().logverbose("Pool Object is %s" %(self.param['poolObj']))
        
        # Update our internal pool object before starting the upgrade
        newP = xenrt.lib.xenserver.poolFactory(xenrt.TEC().lookup("PRODUCT_VERSION", None))(self.param['poolObj'].master)        
        self.param['poolObj'].populateSubclass(newP)        
        
        #Perform Rolling Pool Upgrade 
        xenrt.TEC().logverbose("Performing rolling pool upgrade of %s" % (self.param['poolObj'].getName()))            
        self.param['poolObj'] = newP.upgrade(rolling=True)        
        self.param['hosts'] = self.param['poolObj'].getHosts()
        
        # Upgrade PV tools in guests
        if self.param['poolObj'].master.listGuests() != [] :
            xenrt.TEC().logverbose("Found guests in pool hence Upgrading PV tools.....")        
            for g in self.param['poolObj'].master.listGuests():
                # The guest will have been migrated during the RPU...
                poolguest = self.param['poolObj'].master.getGuest(g)
                xenrt.TEC().logverbose("Finding and upgrading VM %s" % (poolguest.getName()))
                poolguest.findHost()
                if poolguest.windows:
                    poolguest.installDrivers()
                else:
                    poolguest.installTools()
                poolguest.check() 
    
    def run(self, arglist=None):

        # This is used for upgrade testing, add sockets fist points, mock license daemon config for expiry testcases, setting the license expiry 
        self.preLicenseApplyAction()
     
        # This is used to apply appropriate license
        self.applyLicense()
      
        # This is to verify the state of license on host/pool/site
        self.verifySystemLicenseState(licensed = True)

        # This is to add host in a pool, grace period check, restart xapi, shutdown host,host remove from pool etc
        self.postLicenseApplyAction()

        # This is to verify the number of licenses used 
        self.verifyLicenseServer()

    def postRun(self):

        self.updateLicenseSerInfo()
        # Reset host/pool/site so that it can be reused by other testcases within the same seq file
        self.resetSystem()

        # This is to verify the state of license on host/pool/site
        self.verifySystemLicenseState(edition='free')

        # This is to verify the number of licenses used
        self.verifyLicenseServer(reset = True)

class TC21468(SingleSkuBase):

    NEED_LINUX_VM = False

    def postRun(self):
        #This is for WLB functional tests which need a licensed XS.
        pass

class LicensedSystem(SingleSkuBase):

    def preLicenseApplyAction(self):
      
        SingleSkuBase.applyLicense(self)

    def applyLicense(self):

        try:
            SingleSkuBase.applyLicense(self)       
            raise xenrt.XRTFailure("License is applicable on a already licensed system")
        except:
            xenrt.TEC().logverbose("Failed as expected")

class VerifyHostSocketCount(xenrt.TestCase):

    def prepare(self,arglist=None):

        self.hosts = [self.getDefaultHost()]

    def getSocketsFromXenrt(self,host):
        resources = xenrt.GEC().dbconnect.api.get_machine(host.getName())['resources']
        if "sockets" in resources:
            return int(resources['sockets'])
        else:
            raise xenrt.XRTError("Number of sockets not defined in XenRT")

    def run(self,arglist=None):

        err = []
        for host in self.hosts: 
            xenrtCount = self.getSocketsFromXenrt(host)
            cliCount = host.getNoOfSockets()
            if not (xenrtCount == cliCount): 
                err.append("Socket count from Xenrt %d and Socket count from CLI %d are not same\n" % (xenrtCount,cliCount))

        if err:
            raise xenrt.XRTFailure("Socket count is not same %s" % err)

class VerifyPoolSocketCount(VerifyHostSocketCount):

    def prepare(self,arglist=None):

        pool = self.getDefaultPool()
        self.hosts = pool.getHosts()

class RestartServices(SingleSkuBase): 

    def postLicenseApplyAction(self):

        if self.param['system'] == 'host':
            host = self.param['hosts'][0]
        elif self.param['system'] == 'pool' or self.param['system'] == "site":
            host = self.param['poolObj'].master

        host.restartToolstack()

        self.verifySystemLicenseState(licensed = True)

        host.reboot()

        #After reboot need to get the license server info again
        self.updateLicenseSerInfo()

        self.verifySystemLicenseState(licensed = True)

            
class SufficientLicenseUpgrade(SingleSkuBase):
    #Class for upgrading the licensed machine where valid clearwater licenses are already available in the License Server

    def preLicenseApplyAction(self):
        
        #Get the V6 license server , add the platinum license file to it 
        self.guest = self.getGuest("LicenseServer")
        self.v6 = self.guest.getV6LicenseServer()        

        if self.param['edition'] == 'per-socket':
            self.v6.addLicense("valid-platinum")
            preedition = "platinum"            
        elif self.param['edition'] == 'xendesktop':
            self.v6.addLicense("valid-enterprise-xd")
            preedition = "enterprise-xd"         
        
        #Apply the platinum edition to the host/pool
        for h in self.param['hosts']:
            h.license(edition=preedition, v6server=self.v6)

        
        #Upgrade the Host/Pool
        if self.param['system'] == 'host':
            xenrt.TEC().logverbose("Upgrading Host" )
            self.param['hosts'][0]=self.param['hosts'][0].upgrade()
        else:            
            self.poolUpgrade()

        self.updateLicenseSerInfo()        
        #Verify the license state just after upgrade and ensure that its licensed even before applying the licenses
        self.verifySystemLicenseState(edition = self.param['edition'] , licensed = True)        
        
        if not self.hotfixStatus():
            xenrt.TEC().logverbose("Application of Hotfix is allowed for Licensed Pool as expected" )
        else :
            raise xenrt.XRTFailure("Application of Hotfix is not allowed for Licensed Pool ")
            
class InsufficientLicenseUpgrade(SingleSkuBase):
    #Class for upgrading the licensed machine where valid clearwater licenses are NOT available in the License Server
    USELICENSESERVER = False
    
    def preLicenseApplyAction(self):
        
        #Get the V6 license server , add the platinum license file to it 
        self.guest = self.getGuest("LicenseServer")
        self.v6 = self.guest.getV6LicenseServer()        
        self.v6.removeAllLicenses()

        if self.param['edition'] == 'per-socket':
            self.v6.addLicense("valid-platinum")
            preedition = "platinum"            
        elif self.param['edition'] == 'xendesktop':
            self.v6.addLicense("valid-enterprise-xd")
            preedition = "enterprise-xd"         
        
        #Apply the platinum edition to the host/pool
        for h in self.param['hosts']:
            h.license(edition=preedition, v6server=self.v6)

        if preedition != "platinum":
            self.v6.removeAllLicenses()
        
        #Upgrade the Host/Pool
        if self.param['system'] == 'host':
            xenrt.TEC().logverbose("Upgrading Host" )
            self.param['hosts'][0]=self.param['hosts'][0].upgrade()
        else:            
            self.poolUpgrade()
       
        self.updateLicenseSerInfo() 
        #Verify the license state just after upgrade and ensure that its NOT  licensed as valid licenses are not available in License Server
        #TODO change the licensed flag to False after beta  build
        if self.grace:
            self.verifySystemLicenseState(edition = self.param['edition'], licensed = True)
        else:
            self.verifySystemLicenseState(edition = self.param['edition'], licensed = False)

        self.USELICENSESERVER = True
       
        if self.LICENSEFILE:
            self.v6.addLicense(self.LICENSEFILE)
            self.updateLicenseCount()

        #TODO remove 'not' from the if condition 
        if self.hotfixStatus():
            xenrt.TEC().logverbose("Application of Hotfix is restricted for Unlicensed machineas expected" )
        elif self.grace:
            xenrt.TEC().logverbose("Hotfix can be applied through Xencenter whic is expected")
        else:
            raise xenrt.XRTFailure("Hotfix can be applied through Xencenter for Unlicensed Machine" )
           
class FreeEdnSufficientLicenseUpgrade(SingleSkuBase):
    #Class for upgrading the free machine where valid clearwater licenses are already available in the License Server

    def preLicenseApplyAction(self):
        
        #Get the V6 license server 
        self.guest = self.getGuest("LicenseServer")
        self.v6 = self.guest.getV6LicenseServer()        
        
        #Apply the free edition to the host/pool prior to upgrade
        for h in self.param['hosts']:
            h.license(edition="free", v6server=self.v6)
        
        #Upgrade the Host/Pool
        if self.param['system'] == 'host':
            xenrt.TEC().logverbose("Upgrading Host" )
            self.param['hosts'][0]=self.param['hosts'][0].upgrade()
        else:            
            self.poolUpgrade()
        
        self.updateLicenseSerInfo()
        #Verify the license state just after upgrade and ensure that it's free edition and is not licensed 
        self.verifySystemLicenseState(edition = 'free' , licensed = False)        
        
        if self.hotfixStatus():
            xenrt.TEC().logverbose("Application of Hotfix is restricted for UnLicensed Pool as expected" )
        else :
            raise xenrt.XRTFailure("Hotfix can be applied through Xencenter for Unlicensed Machine ")
            
class FreeEdnInsuffLicenseUpgrade(SingleSkuBase):
    #Class for upgrading the Free machine where valid clearwater licenses are NOT available in the License Server
    USELICENSESERVER = False
    
    def preLicenseApplyAction(self):
        
        #Get the V6 license server , add the platinum license file to it 
        self.guest = self.getGuest("LicenseServer")
        self.v6 = self.guest.getV6LicenseServer()        
        self.v6.removeAllLicenses()
        
        #Apply the free edition to the host/pool prior to upgrade
        for h in self.param['hosts']:
            h.license(edition="free", v6server=self.v6)
        
        #Upgrade the Host/Pool
        if self.param['system'] == 'host':
            xenrt.TEC().logverbose("Upgrading Host" )
            self.param['hosts'][0]=self.param['hosts'][0].upgrade()
        else:            
            self.poolUpgrade()
        
        self.updateLicenseSerInfo()
        
        #Verify the license state just after upgrade and ensure that its NOT  licensed as valid licenses are not available in License Server
        self.verifySystemLicenseState(edition="free", licensed = False)

        if self.hotfixStatus():
            xenrt.TEC().logverbose("Application of Hotfix is restricted for Unlicensed machines expected" )
        else :
            raise xenrt.XRTFailure("Hotfix can be applied through Xencenter for Unlicensed Machine" )            
           
class HostLicExpiry(SingleSkuBase):
    EXPIRED = True    

    def postLicenseApplyAction(self):

        guest = self.getGuest("linux")
        self.affectedHost = guest.host
        licenseInfo = self.affectedHost.getLicenseDetails()        
        expiry = xenrt.util.parseXapiTime(licenseInfo['expiry'])
        self.affectedHost.execdom0("service ntpd stop")
        expiretarget = expiry - 300
        expiretarget = time.gmtime(expiretarget)
        self.affectedHost.execdom0("date -u %s" % (time.strftime("%m%d%H%M%Y.%S",expiretarget)))
        self.affectedHost.restartToolstack()
        xenrt.sleep(900)

        self.verifySystemLicense()
        #self.verifyLicenseServer(reset=True)

        if not self.hotfixStatus():
            raise xenrt.XRTFailure("Hotfix installation is allowed through Xencenter")
        
        licenseInfo = self.affectedHost.getLicenseDetails()
        if '19700101T00:00:00Z' != licenseInfo['expiry']:
            raise xenrt.XRTFailure("Host License expiry time is not epoch time")

        try:
            guest.reboot()
        except  Exception as e:
            raise xenrt.XRTFailure("Exception occurred while restarting VM")

    def verifySystemLicense(self):

        hosts=[]
        hosts = copy.copy(self.param['hosts'])
        hosts.remove(self.affectedHost)

        ed = self.param['edition']
        
        for host in self.param['hosts']:
            host.checkHostLicenseState(ed,True)

        host.checkHostLicenseState(ed,False)

class HostReboot(SingleSkuBase):

    def postLicenseApplyAction(self):

        #wait for the license to get applied before shutin down the VM
        xenrt.sleep(300)
        for host in self.param['hosts']:
            host.poweroff()

        #wait for the license server to find out that host is down.This is handshake time
        xenrt.sleep(1800)
        self.verifyLicenseServer(reset=True)

        for host in self.param['hosts']:
            host.poweron()
      
        #wait for the license server to find out that host is up. This is handshake time
        xenrt.sleep(1800)
        self.verifySystemLicenseState(licensed = True)
        self.verifyLicenseServer()

class GraceLic(SingleSkuBase):
    
    def postRun(self):
        pass

    def postLicenseApplyAction(self):

        self.connRestrdBeforeGraceExp()
        self.connRestrdAfterGraceExp()

    def connRestrdBeforeGraceExp(self):
        #connection is restored before grace period expiry

        guest = self.getGuest("LicenseServer")
        sampleGuest = self.getGuest("linux")

        guest.shutdown()
 
        xenrt.sleep(120)          
        host = sampleGuest.host

        licenseInfo = host.getLicenseDetails()
        oldExpiry = licenseInfo['expiry']

        host.restartToolstack()
        xenrt.sleep(120)
        licenseInfo = host.getLicenseDetails()

        if not 'grace' in licenseInfo['grace']:
            raise xenrt.XRTFailure("Host does not have grace license")

        expiry = xenrt.util.parseXapiTime(licenseInfo['expiry'])

        if (expiry > (xenrt.timenow() + 30*25*3600 + 1)):
            raise xenrt.XRTFailure("Host has got license expiry date more than 30 days from current time, it has got expiry date: %s " % expiry)

        if self.hotfixStatus():
            raise xenrt.XRTFailure("Hotfix installation is not allowed through Xencenter")

        try:
            sampleGuest.reboot()
        except  Exception as e:
            raise xenrt.XRTFailure("Exception occurred while restarting VM")

        self.verifySystemLicenseState(licensed=True)
        
        guest.start()
        host.restartToolstack()
        xenrt.sleep(120)

        self.updateLicenseSerInfo()
        licenseInfo = host.getLicenseDetails()
        if 'grace' in licenseInfo['grace']:
            raise xenrt.XRTFailure("Host is still licensed with grace license, though license server is up now")

        if not ('no' in licenseInfo['grace']):
            raise xenrt.XRTFailure("Host is still having grace license")
         
        if oldExpiry != licenseInfo['expiry']:
            raise xenrt.XRTFailure("License expiry date is not same as it was before the connection with license server lost"
                                  ", old epxiry: %s, new expiry: %s" % (oldExpiry,licenseInfo['expiry']))
        
        self.verifySystemLicenseState(licensed=True)

        try:
            sampleGuest.reboot()
        except  Exception as e:
            raise xenrt.XRTFailure("Exception occurred while restarting VM")

        for host in self.param['hosts']:
            host.execdom0("ntpdate `grep -e '^server ' /etc/ntp.conf | sed q | sed 's/server //'` || true")
            host.execdom0("service ntpd start")
            host.restartToolstack()

    def connRestrdAfterGraceExp(self):
        #connection is restored before grace period expiry

        guest = self.getGuest("LicenseServer")
        sampleGuest = self.getGuest("linux")

        
        guest.execguest("echo 'xen.independent_wallclock=1' >> /etc/sysctl.conf")
        guest.shutdown()

        xenrt.sleep(120)

        for host in self.param['hosts']:
            host.restartToolstack()
            xenrt.sleep(120)

            licenseInfo = host.getLicenseDetails()

            if not 'grace' in licenseInfo['grace']:
                raise xenrt.XRTFailure("Host does not have grace license")
     
            expiry = xenrt.util.parseXapiTime(licenseInfo['expiry'])
            host.execdom0("service ntpd stop")
            expiretarget = expiry - 300
            expiretarget = time.gmtime(expiretarget)
            host.execdom0("date -u %s" % (time.strftime("%m%d%H%M%Y.%S",expiretarget)))
            host.restartToolstack()

        #wait for 10 mins extra as host takes some time to get expired
            xenrt.sleep(900)
  
            licenseInfo = host.getLicenseDetails()
            if not 'no' in licenseInfo['grace']:
                raise xenrt.XRTFailure("Host grace license has expired")
               
            if '19700101T00:00:00Z' != licenseInfo['expiry']:
                raise xenrt.XRTFailure("Host License expiry time is not epoch time")

        self.verifySystemLicenseState(licensed=False)
        
        #verify the host license state after license server is back up and ruuning 
        guest.start()
        guest.execguest("date -u")
        expirelicenseserver = expiry + 900
        expirelicenseserver = time.gmtime(expirelicenseserver)
        guest.execguest("date -u %s" %(time.strftime("%m%d%H%M%Y.%S",expirelicenseserver)))        
        guest.execguest("/etc/init.d/citrixlicensing stop")
        xenrt.sleep(10)      
        guest.execguest("/etc/init.d/citrixlicensing start > /dev/null 2>&1 < /dev/null")
        xenrt.sleep(10)        
        guest.execguest("date -u")
        
        for host in self.param['hosts']:
            host.restartToolstack()
            xenrt.sleep(120)

        xenrt.sleep(300)
        self.updateLicenseSerInfo()

        for host in self.param['hosts']:
            licenseInfo = host.getLicenseDetails()
            if not 'no' in licenseInfo['grace']:
                raise xenrt.XRTFailure("Host still has got grace license")

        try:
            sampleGuest.reboot()
        except  Exception as e:
            raise xenrt.XRTFailure("Exception occurred while restarting VM")

        self.verifySystemLicenseState(licensed=True)
        self.verifyLicenseServer()
        
        if self.hotfixStatus():
            raise xenrt.XRTFailure("Hotfix installation is not allowed through Xencenter")
        
        if not self.LICENSEFILE == "valid-xendesktop" :
            #Now fast forward the time in host to cross its license-expiry date 
            for host in self.param['hosts']:    
                licenseInfo = host.getLicenseDetails()
                expiry = xenrt.util.parseXapiTime(licenseInfo['expiry'])
                
                expiretarget = expiry + 60*24*60*60 
                expiretarget = time.gmtime(expiretarget)
                host.execdom0("date -u %s" % (time.strftime("%m%d%H%M%Y.%S",expiretarget)))            
                host.restartToolstack()        
            
            #Fast forward the time by same amount in license server too 
            expirelicenseserver = expiry + 60*24*60*60
            expirelicenseserver = time.gmtime(expirelicenseserver)
            guest.execguest("date -u %s" %(time.strftime("%m%d%H%M%Y.%S",expirelicenseserver)))        
            guest.execguest("service citrixlicensing restart" , getreply=False)        
            xenrt.sleep(20)        
            
            sampleGuest.shutdown()
            
            for host in self.param['hosts']:            
                host.reboot()            
                xenrt.sleep(15)                      
                host.restartToolstack()
                xenrt.sleep(60)            
                licenseInfo = host.getLicenseDetails()           
                if '19700101T00:00:00Z' != licenseInfo['expiry']:
                    raise xenrt.XRTFailure("Host License expiry time is not epoch time") 
                    
            self.EXPIRED = True 

            if not self.hotfixStatus():
                raise xenrt.XRTFailure("Hotfix installation is not allowed through Xencenter")

        #reset time
        for host in self.param['hosts']:
            host.execdom0("ntpdate `grep -e '^server ' /etc/ntp.conf | sed q | sed 's/server //'` || true")
            host.execdom0("service ntpd start")
            host.restartToolstack()

class NotEnoughLic(SingleSkuBase): 

    LICENSEFILE = 'valid-single-persocket'

    def preLicenseApplyAction(self):

        try:
            self.applyLicense() 
            raise xenrt.XRTFailure("Host/Pool is licensed with per socket licenses")
        except Exception as e:
            xenrt.TEC().logverbose("License application failed as expected")

        self.param['edition'] = 'free'
        self.verifySystemLicenseState(licensed=False)
        self.verifyLicenseServer(reset = True)

        self.param['edition'] = 'per-socket'
        self.LICENSEFILE = "valid-persocket"
        self.v6.addLicense(self.LICENSEFILE)
        self.updateLicenseCount()

class LicWithMulExpDates(SingleSkuBase):

    def postLicenseApplyAction(self):

        sampleGuest = self.getGuest("linux")
        host = sampleGuest.host

        licenseInfo = host.getLicenseDetails()
        expiry = xenrt.util.parseXapiTime(licenseInfo['expiry'])
        oldexpiry = time.gmtime(expiry)
        
        licensefile = "valid-persocket-expire-later"
        self.v6.addLicense(licensefile)

        host.execdom0("echo 300 > /tmp/fist_set_reapply_period")
        host.restartToolstack()
        
        xenrt.sleep(600)

        self.verifySystemLicenseState(licensed=True)

        licenseInfo = host.getLicenseDetails()
        expiry = xenrt.util.parseXapiTime(licenseInfo['expiry'])
        newexpiry = time.gmtime(expiry)

        if newexpiry <= oldexpiry:
            raise xenrt.XRTFailure("Host is still licensed with old license")

        try:
            sampleGuest.reboot()
        except  Exception as e:
            raise xenrt.XRTFailure("Exception occurred while restarting VM")
            
            
class ExpiredUpgrade(SingleSkuBase):
    
    def preLicenseApplyAction(self):
        
        #Get the V6 license server , add the platinum license file to it 
        self.guest = self.getGuest("LicenseServer")
        self.v6 = self.guest.getV6LicenseServer()        
        
        if self.param['edition'] == 'per-socket':
            self.v6.addLicense("valid-platinum")
            preedition = "platinum"
        elif self.param['edition'] == 'xendesktop':
            self.v6.addLicense("valid-enterprise-xd")
            preedition = "enterprise-xd"
        
        #Apply the platinum edition to the host/pool
        for h in self.param['hosts']:
            h.license(edition=preedition, v6server=self.v6)        
        
        #Expire the host or master of the Pool
        host = self.param['hosts'][0]
        licenseInfo = host.getLicenseDetails()
        expiry = xenrt.util.parseXapiTime(licenseInfo['expiry'])
        host.execdom0("service ntpd stop")
        expiretarget = expiry - 300
        expiretarget = time.gmtime(expiretarget)
        host.execdom0("date -u %s" % (time.strftime("%m%d%H%M%Y.%S",expiretarget)))
        host.restartToolstack()
        xenrt.sleep(900)

        #self.verifySystemLicenseState(licensed=False)
        self.verifyLicenseServer(reset=True)
        
        #Upgrade the Host/Pool
        if self.param['system'] == 'host':
            xenrt.TEC().logverbose("Upgrading Host" )
            self.param['hosts'][0]=self.param['hosts'][0].upgrade()
            guest = self.getGuest("linux")
            guest.start()
        else:            
            self.poolUpgrade()
            guest = self.getGuest("linux1")
        
        try:
            guest.reboot()
        except  Exception as e:
            raise xenrt.XRTFailure("Exception occurred while restarting VM")    
            
        #Verify the license status after upgrade     
        self.verifySystemLicenseState(licensed=True)        
        
        self.updateLicenseSerInfo()
        
        #Verify the license state just after upgrade and ensure that its licensed even before applying the licenses
        self.verifySystemLicenseState(edition = self.param['edition'] , licensed = True)        
        
        if not self.hotfixStatus():
            xenrt.TEC().logverbose("Application of Hotfix is allowed for Licensed Pool as expected" )
        else :
            raise xenrt.XRTFailure("Application of Hotfix is not allowed for Licensed Pool ")
        
class   InsufficientExpiredUpgrade(SingleSkuBase):

    def preLicenseApplyAction(self):
        
        #Get the V6 license server , add the platinum license file to it 
        self.guest = self.getGuest("LicenseServer")
        self.v6 = self.guest.getV6LicenseServer()        
        self.v6.removeAllLicenses()

        if self.param['edition'] == 'per-socket':
            self.v6.addLicense("valid-platinum")
            preedition = "platinum"            
        elif self.param['edition'] == 'xendesktop':
            self.v6.addLicense("valid-enterprise-xd")
            preedition = "enterprise-xd"
        
        #Apply the platinum edition to the host/pool
        for h in self.param['hosts']:
            h.license(edition=preedition, v6server=self.v6)        
        
        #Expire the host or master of the Pool
        host = self.param['hosts'][0]
        licenseInfo = host.getLicenseDetails()
        expiry = xenrt.util.parseXapiTime(licenseInfo['expiry'])
        host.execdom0("service ntpd stop")
        expiretarget = expiry - 300
        expiretarget = time.gmtime(expiretarget)
        host.execdom0("date -u %s" % (time.strftime("%m%d%H%M%Y.%S",expiretarget)))
        host.restartToolstack()
        xenrt.sleep(900)
        
        self.verifyLicenseServer(reset=True)        

        if preedition != "platinum":
            self.v6.removeAllLicenses()
        
        #Upgrade the Host/Pool
        if self.param['system'] == 'host':
            xenrt.TEC().logverbose("Upgrading Host" )
            self.param['hosts'][0]=self.param['hosts'][0].upgrade()
            guest = self.getGuest("linux")
            guest.start()
        else:            
            self.poolUpgrade()
            guest = self.getGuest("linux1")        
        
        try:
            guest.reboot()
        except  Exception as e:
            raise xenrt.XRTFailure("Exception occurred while restarting VM")    
       
        self.updateLicenseSerInfo()
        #Verify the license state just after upgrade and ensure that its NOT  licensed as valid licenses are not available in License Server
        #TODO change the licensed flag to 'False' once tech preview is out
      
        if self.grace: 
            self.verifySystemLicenseState(edition = self.param['edition'], licensed = True)
        else:
            self.verifySystemLicenseState(edition = self.param['edition'], licensed = False)

        self.USELICENSESERVER = True
       
        if self.LICENSEFILE:
            self.v6.addLicense(self.LICENSEFILE)
            self.updateLicenseCount()
 
        if self.hotfixStatus():
            xenrt.TEC().logverbose("Application of Hotfix is restricted for Unlicensed machineas expected" )
        elif self.grace:
            xenrt.TEC().logverbose("Hotfix can be applied through Xencenter which is expected")
        else :
            raise xenrt.XRTFailure("Hotfix can be applied through Xencenter for Unlicensed Machine" )
            
            

                 
