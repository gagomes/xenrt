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
    
class StorageTrimTestcase(NetappFCTrimSupport):
    """ Verify available size on lvmohba lun is updated when VDIs on lun are deleted """

    def run(self, arglist=[]):
        
        spaceUsedByGuests = {}
        spaceFreedByGuests = {}
        
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
            log("Space used: Before creating guest %s, After creating guest %s, Difference in space used %s" % (initialUsedSpace,usedSpaceAfter,diff))
        
        # Deleting Guests
        for guest in spaceUsedByGuests.keys():
            xenrt.sleep(60)
            step("Uninstalling Guest %s" % guest.getName())
            initialUsedSpace = self.lun.sizeUsed()
            guest.uninstall()
            step("Triggering TRIM on Host")
            self.cli.execute("host-call-plugin host-uuid=%s plugin=trim fn=do_trim args:sr_uuid=%s" % (self.host.getMyHostUUID(),self.sruuid))
            xenrt.sleep(240)
            usedSpaceAfter = self.lun.sizeUsed()
            diff = initialUsedSpace - usedSpaceAfter
            spaceFreedByGuests.update({guest:[initialUsedSpace,usedSpaceAfter,diff]})
            log("Space freed: Before deleting guest %s, After deleting guest %s, Difference in space used %s" % (initialUsedSpace,usedSpaceAfter,diff))
        
        # Match the space is freed on LUN
        step("Match the space used while creating and deleting guest on lun")
        for guest in spaceUsedByGuests.keys():
            if not (spaceUsedByGuests[guest][2] == spaceFreedByGuests[guest][2]):
                log("Print matrix for used space in Format : {guestInstance : [spaceUsedBeforeGuestCreation, spaceUsedAfterGuestCreation, DifferenceInSpaceUsed]}")
                log("%s" % str(spaceUsedByGuests))
                log("Print matrix for used space in Format : {guestInstance : [spaceUsedBeforeGuestDeletion, spaceUsedAfterGuestDeletion, DifferenceInSpaceUsed]}")
                log("%s" % str(spaceFreedByGuests))
                raise xenrt.XRTFailure("TRIM failed : %s bytes is not freed on lun after deleting guest" % str(spaceUsedByGuests[guest][2] - spaceFreedByGuests[guest][2]))
        
    
    def postRun(self, arglist=[]):
        # Destroy the lvmoHBA SR on the pool.
        self.destroySR()
    
class VerifyTrimTrigger(xenrt.TestCase):
    """Verify whether TRIM can be triggered on HBA and ISCSI SRs """
    
    def prepare(self, arglist):
        #Get the default host
        self.host = self.getDefaultHost()
        
    def run(self, arglist):
        if self.SR_TYPE == "lvmoiscsi":
            self.sr = self.host.getSRs(type="lvmoiscsi")
        elif self.SR_TYPE == "lvmohba":
            self.sr = self.host.getSRs(type="lvmohba")
        else:
            raise xenrt.XRTError("Invalid SR Type specified for enabling TRIM")
        
        result = self.host.execdom0("xe host-call-plugin host-uuid=%s plugin=trim fn=do_trim args:sr_uuid=%s" %(self.host.getMyHostUUID(),self.sr[0])).strip()
        
        if result == 'True':
            xenrt.TEC().logverbose("Enabling TRIM operation Successful")
        else:
            raise xenrt.XRTFailure("Failed to Enable TRIM on the %s SR of type %s with %s" %(self.sr[0],self.SR_TYPE,result))

class TC21549(VerifyTrimTrigger):
    """Verify whether TRIM can be triggered on ISCSI SR """
    SR_TYPE = "lvmoiscsi"
    
class TC21550(VerifyTrimTrigger):
    """Verify whether TRIM can be triggered on HBA SR  """
    SR_TYPE = "lvmohba"
