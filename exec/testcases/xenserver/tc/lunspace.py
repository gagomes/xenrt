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
        self.host.scanFibreChannelBus()        
        self.host.enableMultipathing()
        self.getLogsFrom(self.host)        
        
        # Setup initial storage configuration, 1 LUNs of given size
        self.netAppFiler.provisionLuns(1, self.OLDSIZE,{self.host : self.host.getFCWWPNInfo()})
       
        self.lun = self.netAppFiler.getLuns()[0]
        step("The lun is %s" %self.lun)
        self.fcSR = xenrt.lib.xenserver.FCStorageRepository(self.host,"lvmoHBASR")
        self.fcSR.create(self.lun.getId())
        
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

class NetappFCTrimSupport(xenrt.TestCase):
    """ Defines the base class for XenServer TRIM Support On NetApp FC lun"""
    
    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.host = None
        self.sruuid = None
        self.cli = None
        self.netAppFiler = None
        self.lun = None
        self.lunsize = 60
    
    def prepare(self, arglist=[]):
        # Lock storage resource and access storage manager library functions.
        step("Creating netapp filer instance")
        self.netAppFiler = xenrt.StorageArrayFactory().getStorageArray(xenrt.StorageArrayVendor.NetApp,
                                                                       xenrt.StorageArrayType.FibreChannel)
        self.host = self.getDefaultHost()
        self.cli = self.host.getCLIInstance()
        self.host.scanFibreChannelBus()
        step("Enable Multipathing on Host")
        self.host.enableMultipathing()
        self.getLogsFrom(self.host)
        
        # Setup initial storage configuration.
        step("Provisioning single lun of size %s" % self.lunsize)
        self.netAppFiler.provisionLuns(1, self.lunsize, self._createInitiators())
        self.lun = self.netAppFiler.getLuns()[0]
        sr = xenrt.lib.xenserver.FCStorageRepository(self.host, "lvmoHBASR")
        step("Attaching lun to the host")
        sr.create(self.lun.getId())
        self.sruuid = sr.uuid
        log("TRIM will be tested on SR with uuid %s" % self.sruuid)
        
    def _createInitiators(self):
        return {self.host : self.host.getFCWWPNInfo()}
    
    def destroySR(self):
        step("Destroying lvmoHBA SR on host")
        self.host.destroySR(self.sruuid)
        # Releasing the fibre channel storage array
        self.netAppFiler.release()
    
class TrimFunctionalTestHBA(NetappFCTrimSupport):
    """ Verify available size on lvmohba lun is updated when VDIs on lun are deleted """

    def run(self, arglist=[]):
        
        spaceUsedByGuests = {}
        spaceFreedByGuests = {}
        delta = 2 # Keep delta as 2% space on lun which is not freed after deleting a VM
                  # Workaround for CA-139518
        
        # Creating 1 windows and 4 linux guests on Hardware HBA SR
        for i in range(5):
            xenrt.sleep(60)
            step("Creating Guest %s on Hardware HBA Storage Repository" % i)
            initialUsedSpace = self.lun.sizeUsed()
            if i == 0:
                guest = self.host.createGenericWindowsGuest(name="Windows Guest %s" % i,sr=self.sruuid)
            else:
                guest = self.host.createGenericLinuxGuest(name="Linux Guest %s" % i,sr=self.sruuid)
            guest.shutdown()
            xenrt.sleep(120)
            usedSpaceAfter = self.lun.sizeUsed()
            diff = usedSpaceAfter - initialUsedSpace
            spaceUsedByGuests.update({guest:[initialUsedSpace,usedSpaceAfter,diff]})
            log("Space used in bytes: Before creating guest %s, After creating guest %s, Difference %s" %
                                                                        (initialUsedSpace,usedSpaceAfter,diff))
        
        # Deleting Guests
        for guest in spaceUsedByGuests.keys():
            xenrt.sleep(60)
            step("Uninstalling Guest %s" % guest.getName())
            initialUsedSpace = self.lun.sizeUsed()
            guest.uninstall()
            step("Triggering TRIM on Hardware HBA SR")
            self.cli.execute("host-call-plugin host-uuid=%s plugin=trim fn=do_trim args:sr_uuid=%s" %
                                                                    (self.host.getMyHostUUID(),self.sruuid))
            xenrt.sleep(240)
            usedSpaceAfter = self.lun.sizeUsed()
            diff = initialUsedSpace - usedSpaceAfter
            spaceFreedByGuests.update({guest:[initialUsedSpace,usedSpaceAfter,diff]})
            log("Space freed in bytes: Before deleting guest %s, After deleting guest %s, Difference %s" %
                                                                        (initialUsedSpace,usedSpaceAfter,diff))
        
        # Check the space is freed on LUN
        step("Check the space used while creating and deleting guest on lun")
        for guest in spaceUsedByGuests.keys():
            if not ((spaceUsedByGuests[guest][2] - spaceFreedByGuests[guest][2]) < ((delta * spaceUsedByGuests[guest][2]) / 100)):
                log("Print in Format : {guestInstance : [spaceUsedBeforeGuestCreation, spaceUsedAfterGuestCreation, Difference]}")
                log("%s" % str(spaceUsedByGuests))
                log("Print in Format : {guestInstance : [spaceUsedBeforeGuestDeletion, spaceUsedAfterGuestDeletion, Difference]}")
                log("%s" % str(spaceFreedByGuests))
                log("TRIM failed : %s bytes is not freed on lun after deleting guest" % str(spaceUsedByGuests[guest][2] - spaceFreedByGuests[guest][2]))
                raise xenrt.XRTFailure("TRIM failed : bytes not freed on lun after deleting guest")

    def postRun(self, arglist=[]):
        # Destroy the lvmoHBA SR on the pool.
        self.destroySR()

class TrimFunctionalTestSSD(xenrt.TestCase):
    """Verify trim support on a local SR created using solid state disk"""

    def prepare(self, arglist=[]):
        self.host = self.getDefaultHost()
        self.sruuid = self.host.lookupDefaultSR()

    def run(self, arglist=[]):
        
        spaceUsedByGuests = {}
        spaceFreedByGuests = {}
        delta = 2 # 2% of space on SR is not freed after deleting a VM.
        
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
