#
# XenRT: Test harness for Xen and the XenServer product family
#
# Testcases for storage features
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and conditions 
# as licensed by Citrix Systems, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy, math
import xenrt, xenrt.lib.xenserver
from xenrt.lazylog import *

class TC21547(xenrt.TestCase):
    """Verify that HBA SR size is updated after resizing the mapped NetApp lun"""

    OLDSIZE = 50 #in GB
    NEWSIZE = 80 #
    RESIZEFACTOR =10
    def prepare(self, arglist=[]):

        # Lock storage resource and access storage manager library functions.
        self.netAppFiler = xenrt.StorageArrayFactory().getStorageArray(xenrt.StorageArrayVendor.NetApp,
                                                                        xenrt.StorageArrayType.FibreChannel)
                                                                        
        self.host = self.getDefaultHost()
        self.host.scanScsiBus()        
        self.host.enableMultipathing()
        self.getLogsFrom(self.host)        
        
        # Setup initial storage configuration, 1 LUNs of given size
        self.netAppFiler.provisionLuns(1, self.OLDSIZE,{self.host : self.host.getFCWWPNInfo()})
       
        self.lun = self.netAppFiler.getLuns()[0]
        step("The lun is %s" %self.lun)
        self.fcSR = xenrt.lib.xenserver.FCStorageRepository(self.host,"lvmoHBASR", thin_prov=(self.tcsku=="thin"))
        self.fcSR.create(self.lun)
        
    def run(self, arglist=[]):

        self.guests =[]
        self.guests.append(self.host.createBasicGuest(name="ws08r2-x64",distro="ws08r2-x64",sr=self.fcSR.uuid))
        self.guests.append(self.host.createBasicGuest(name="centos64", distro="centos64", sr=self.fcSR.uuid))
        
        newSize = self.OLDSIZE        
        while newSize <= self.NEWSIZE :
            newSize = newSize + self.RESIZEFACTOR
            newSizeBytes = newSize * xenrt.GIGA 
            step("Resizing the LUN with serial number: %s to %d GB" %
                        (self.lun.getNetAppSerialNumber(),newSize))
            
            step("Currently the lun size is %s "%self.lun.size())           
            self.lun.resize(newSizeBytes/xenrt.MEGA,False)
            self.fcSR.scan()
            step("After resizing the lun size is %s "%self.lun.size())
            currentsize=self.fcSR.physicalSizeMB()
            expectednewsize = newSizeBytes/xenrt.MEGA - 12
            
            if currentsize == expectednewsize:
                step("SR physical size is equal to new size.Check that VM are functioning well after resizing the lun..")
                # Verify that VM can go through the life cycle operations                
                for guest in self.guests:
                    self.getLogsFrom(guest)
                    guest.shutdown()
                    guest.start()
                    guest.reboot()
                    guest.suspend()
                    guest.resume()
            else :
                raise xenrt.XRTFailure("SR didnt resize to the expected new size %s MB.Its Current size is %s MB" %
                                                                                            (expectednewsize,currentsize))
                
    def postRun(self, arglist=None):
        for guest in self.guests:
           guest.shutdown(force=True)
           guest.uninstall()
        self.host.destroySR(self.fcSR.uuid)
        self.netAppFiler.release()

class NetappTrimSupportBase(xenrt.TestCase):
    """Defines a base class for testing TRIM Support on NetApp array"""

    PROTOCOL=None
    THINPROVISION = False
    SRTYPE = None

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.host = None
        self.sr = None
        self.sruuid = None
        self.cli = None
        self.netAppFiler = None
        self.lun = None

    def parseArgs(self, arglist=[]):
        """Parse the test arguments"""

        args          = self.parseArgsKeyValue(arglist)

        self.distro   = str(args.get("distro", "debian80"))
        self.arch     = str(args.get("arch", "x86-64"))

        self.vmsCount = int(args.get("vmscount", "5"))
        self.lunsize  = int(args.get("lunsize", "60"))

    def prepare(self, arglist=[]):

        self.parseArgs(arglist) # parse arg lists.

        self.host = self.getDefaultHost()
        self.cli = self.host.getCLIInstance()

        self.host.enableMultipathing()
        self.getLogsFrom(self.host)

    def configureNetAppLUN(self):
        """Configure NetApp array to obtain a LUN"""

        # Lock storage resource and access storage manager library functions.
        self.netAppFiler = xenrt.StorageArrayFactory().getStorageArray(xenrt.StorageArrayVendor.NetApp,
                                                                                            self.PROTOCOL)

        # Mapp the initiators and obtain a LUN.
        step("Provisioning single lun of size %s" % self.lunsize)
        self.netAppFiler.provisionLuns(1, self.lunsize, self.getInitiators())
        return self.netAppFiler.getLuns()[0]

    def createSR(self): 
        raise xenrt.XRTError("Not implemented in base class")

    def getInitiators(self): 
        raise xenrt.XRTError("Not implemented in base class")

    def callTrimOnSR(self):
        """Testing TRIM functionality on a storage repository"""

        spaceUsedByGuests = {}
        spaceFreedByGuests = {}
        delta = 5 #CA-179207:Keep delta as 5% space on NetApp lun which is not freed after deleting a VM.
                  # Workaround for CA-139518
        
        # Creating few linux guests.
        for i in range(1,self.vmsCount+1):
            step("Creating Guest %s on SR : %s" % (i, self.SRTYPE))
            initialUsedSpace = self.lun.sizeUsed()

            try:
                vmName = "vm%02d" % i
                guest = self.goldenVM.copyVM(vmName, sruuid=self.sruuid) # much quicker than installing another one.
            except Exception, e: 
                raise xenrt.XRTFailure("Cloning vm: %s on %s SR failed with error: %s" %
                                                                    (vmName, self.SRTYPE, str(e)))
            xenrt.sleep(120)
            usedSpaceAfter = self.lun.sizeUsed()
            diff = usedSpaceAfter - initialUsedSpace
            spaceUsedByGuests.update({guest:[initialUsedSpace,usedSpaceAfter,diff]})
            log("TRIM on %s SR: Space used in bytes: Before creating guest %s, After creating guest %s, Difference %s" %
                                                                        (self.SRTYPE, initialUsedSpace,usedSpaceAfter,diff))

        # Deleting Guests
        for guest in spaceUsedByGuests.keys():
            step("Uninstalling Guest %s from %s SR" % (guest.getName(), self.SRTYPE))
            initialUsedSpace = self.lun.sizeUsed()
            guest.uninstall()
            step("Triggering TRIM on %s SR" % self.SRTYPE)
            self.cli.execute("host-call-plugin host-uuid=%s plugin=trim fn=do_trim args:sr_uuid=%s" %
                                                                    (self.host.getMyHostUUID(),self.sruuid))
            xenrt.sleep(240)
            usedSpaceAfter = self.lun.sizeUsed()
            diff = initialUsedSpace - usedSpaceAfter
            spaceFreedByGuests.update({guest:[initialUsedSpace,usedSpaceAfter,diff]})
            log("TRIM on %s SR: Space freed in bytes: Before deleting guest %s, After deleting guest %s, Difference %s" %
                                                                            (self.SRTYPE, initialUsedSpace,usedSpaceAfter,diff))

        # Check the space is freed on the storage repository.
        step("Check the space used while creating and deleting guest on %s SR." % self.SRTYPE)
        for guest in spaceUsedByGuests.keys():
            step("Guest under consideration %s" % guest.getName())
            if not ((spaceUsedByGuests[guest][2] - spaceFreedByGuests[guest][2]) < ((delta * spaceUsedByGuests[guest][2]) / 100)):
                log("Print in Format : {guestInstance : [spaceUsedBeforeGuestCreation, spaceUsedAfterGuestCreation, Difference]}")
                log("%s" % str(spaceUsedByGuests))
                log("Print in Format : {guestInstance : [spaceUsedBeforeGuestDeletion, spaceUsedAfterGuestDeletion, Difference]}")
                log("%s" % str(spaceFreedByGuests))
                log("%s bytes is not freed on lun after deleting guest %s" % 
                    (str(spaceUsedByGuests[guest][2] - spaceFreedByGuests[guest][2]),guest.getName()))
                raise xenrt.XRTFailure("TRIM on %s SR failed : Space not freed on lun after deleting the guests" % self.SRTYPE)

    def getBaseImage(self):
        """Retrieves the golden image for the test"""

        # Check if there any golden image.
        existingGuests = self.host.listGuests() 
        if existingGuests: 
            vm = map(lambda x:self.host.getGuest(x), existingGuests) 
        else:
            raise xenrt.XRTFailure("No base images are found.")
        return vm[0] # if so, pick the first one available.

    def run(self, arglist=[]):

        # Retrieve the golden image.
        self.goldenVM = self.getBaseImage()

        if self.goldenVM.getState() == 'UP': # Make sure the guest is down.
            self.goldenVM.shutdown()

        # Configure NetApp and obtain the LUN.
        self.lun = self.configureNetAppLUN()

        # Create a SR and regard as default SR.
        self.sr = self.createSR()
        self.sruuid = self.sr.uuid
        pooluuid = self.host.minimalList("pool-list")[0] 
        self.host.genParamSet("pool", pooluuid, "default-SR", self.sruuid)

        # Test the trim functionality.
        self.callTrimOnSR()

    def postRun(self, arglist=[]):
        # Destroy the configured SR.
        self.host.destroySR(self.sruuid)
        self.netAppFiler.release()

class TrimFuncNetAppISCSI(NetappTrimSupportBase):
    """Test the XenServer TRIM feature on iSCSI SR using NetApp array"""

    PROTOCOL = xenrt.StorageArrayType.iSCSI
    SRTYPE = "lvmoiscsi"
    SRNAME = "lvmoiscsi-thick"

    def getInitiators(self):
        return {self.host : {'iqn': self.host.getIQN()}}

    def createSR(self):
        sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host, self.SRNAME, thin_prov=self.THINPROVISION)
        sr.create(self.lun.getISCSILunObj(), noiqnset=True, subtype="lvm")
        return sr

class TrimFuncNetAppFC(NetappTrimSupportBase):
    """Test the XenServer TRIM feature on Fibre Channel SR using NetApp array"""

    PROTOCOL = xenrt.StorageArrayType.FibreChannel
    SRTYPE = "lvmohba"
    SRNAME = "lvmohba-thick"

    def getInitiators(self):
        return {self.host : self.host.getFCWWPNInfo()}

    def createSR(self):
        sr = xenrt.lib.xenserver.FCStorageRepository(self.host, self.SRNAME, thin_prov=self.THINPROVISION)
        sr.create(self.lun)
        return sr

class TrimFunctionalTestSSD(xenrt.TestCase):
    """Verify trim support on a local SR created using solid state disk"""

    def prepare(self, arglist=[]):
        self.host = self.getDefaultHost()
        self.sruuid = self.host.lookupDefaultSR()

    def run(self, arglist=[]):
        
        spaceUsedByGuests = {}
        spaceFreedByGuests = {}
        delta = 5 #CA-179207:5% of space on SR is not freed after deleting a VM.
        
        # Creating 1 windows and 4 linux guests on Local SSD SR.
        for i in range(1,3):
            xenrt.sleep(60)
            step("Creating Guest %s on local SSD SR" % i)
            initialUsedSpace = int(self.host.genParamGet("sr", self.sruuid, "virtual-allocation"))
            if i == 0:
                guest = self.host.createGenericWindowsGuest(name="Windows Guest %s" % i)
            else:
                guest = self.host.createGenericLinuxGuest(name="Linux Guest %s" % i)
            guest.shutdown()
            xenrt.sleep(120)
            usedSpaceAfter = int(self.host.genParamGet("sr", self.sruuid, "virtual-allocation"))
            diff = usedSpaceAfter - initialUsedSpace
            spaceUsedByGuests.update({guest:[initialUsedSpace,usedSpaceAfter,diff]})
            log("Space used in bytes: Before creating guest %s, After creating guest %s, Difference %s" %
                                                                        (initialUsedSpace,usedSpaceAfter,diff))
        
        # Deleting Guests
        for guest in spaceUsedByGuests.keys():
            xenrt.sleep(60)
            step("Uninstalling Guest %s" % guest.getName())
            initialUsedSpace = int(self.host.genParamGet("sr", self.sruuid, "virtual-allocation"))
            guest.uninstall()
            step("Triggering TRIM on Local SSD SR")
            self.host.execdom0("xe host-call-plugin host-uuid=%s plugin=trim fn=do_trim args:sr_uuid=%s" %
                                                                    (self.host.getMyHostUUID(),self.sruuid))
            xenrt.sleep(240)
            usedSpaceAfter = int(self.host.genParamGet("sr", self.sruuid, "virtual-allocation"))
            diff = initialUsedSpace - usedSpaceAfter
            spaceFreedByGuests.update({guest:[initialUsedSpace,usedSpaceAfter,diff]})
            log("Space freed in bytes: Before deleting guest %s, After deleting guest %s, Difference %s" %
                                                                        (initialUsedSpace,usedSpaceAfter,diff))
        
        # Check the space is freed on Local SSD SR.
        step("Check the space used while creating and deleting guest on local SR.")
        for guest in spaceUsedByGuests.keys():
            if not ((spaceUsedByGuests[guest][2] - spaceFreedByGuests[guest][2]) < ((delta * spaceUsedByGuests[guest][2]) / 100)):
                log("Print in Format : {guestInstance : [spaceUsedBeforeGuestCreation, spaceUsedAfterGuestCreation, Difference]}")
                log("%s" % str(spaceUsedByGuests))
                log("Print in Format : {guestInstance : [spaceUsedBeforeGuestDeletion, spaceUsedAfterGuestDeletion, Difference]}")
                log("%s" % str(spaceFreedByGuests))
                raise xenrt.XRTFailure("TRIM failed : %s bytes is not freed on lun after deleting guest" %
                                                        str(spaceUsedByGuests[guest][2] - spaceFreedByGuests[guest][2]))

class VerifyTrimTrigger(xenrt.TestCase):
    """Verify whether TRIM can be triggered on storage repositories"""

    SR_TYPE = None
    TRIM_SUPPORTED_SR = ['lvm', 'lvmoiscsi', 'lvmohba']
    
    def prepare(self, arglist):
        #Get the default host
        self.host = self.getDefaultHost()
        
    def run(self, arglist):
        if self.SR_TYPE == "ext":
            self.sr = self.host.getSRs(type="ext")
        elif self.SR_TYPE == "lvm":
            self.sr = self.host.getSRs(type="lvm")
        elif self.SR_TYPE == "nfs":
            self.sr = self.host.getSRs(type="nfs")
        elif self.SR_TYPE == "lvmoiscsi":
            self.sr = self.host.getSRs(type="lvmoiscsi")
        elif self.SR_TYPE == "lvmohba":
            self.sr = self.host.getSRs(type="lvmohba")
        else:
            raise xenrt.XRTError("Invalid SR Type specified for enabling TRIM")
        
        result = self.host.execdom0("xe host-call-plugin host-uuid=%s plugin=trim fn=do_trim args:sr_uuid=%s" %
                                                                    (self.host.getMyHostUUID(),self.sr[0])).strip()
        
        if self.SR_TYPE in self.TRIM_SUPPORTED_SR:
            if (result == 'True'):
                xenrt.TEC().logverbose("Enabling TRIM on %s SR is successful" % self.SR_TYPE)
            elif re.search('Operation not supported', result):
                raise xenrt.XRTFailure("Xenserver reports TRIM is not supported")
            else:
                xenrt.TEC().logverbose("Error: %s" % result)
                raise xenrt.XRTFailure("TRIM trigger failed on supported SR %s with unknown trim exceptions" % 
                                                                                                    self.SR_TYPE)
        else: # ext or nfs
            if (result == 'True'):
                raise xenrt.XRTFailure("TRIM is triggered on an unsupported SR %s" % self.SR_TYPE)
            elif re.search('UnsupportedSRForTrim', result):
                xenrt.TEC().logverbose("TRIM is not supported on %s SR as expected" % self.SR_TYPE)
            else:
                xenrt.TEC().logverbose("Error: %s" % result)
                raise xenrt.XRTFailure("TRIM operation failed on an unsupported SR %s with unknown exceptions" %
                                                                                                        self.SR_TYPE)

class TC21549(VerifyTrimTrigger):
    """Verify enable TRIM operation on ISCSI SR"""
    SR_TYPE = "lvmoiscsi"
    
class TC21550(VerifyTrimTrigger):
    """Verify enable TRIM operation on HBA SR"""
    SR_TYPE = "lvmohba"
    
class TC21554(VerifyTrimTrigger):
    """Verify enable TRIM operation on LVHD SR"""
    SR_TYPE = "lvm"

class TC21553(VerifyTrimTrigger):
    """Verify whether TRIM can be triggered on NFS SR"""
    SR_TYPE = "nfs"

class TC21555(VerifyTrimTrigger):
    """Verify whether TRIM can be triggered on EXT SR"""
    SR_TYPE = "ext"
