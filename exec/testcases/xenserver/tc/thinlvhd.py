# Test harness for Xen and the XenServer product family
#
# Thin provisioning functional verification test cases. 
# Refer FQP : https://info.citrite.net/pages/viewpage.action?pageId=1228996737
#
# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import re,string
import xenrt,xenrt.lib.xenserver
from xenrt.lazylog import step
from testcases.xenserver.tc.cache import _ResetOnBootBase


class ThinProvisionVerification(xenrt.TestCase):
    """ Verify SW thin provisioning available only on LVHD """

    def checkThinProvisionSR(self,srtype,sr):
        if srtype in ['lvmoiscsi','lvmohba','nfs'] and not sr.thinProvisioning:
            raise xenrt.XRTFailure("SR created of type %s on the host %s is not thin provisioned" % (srtype,self.host))
        if srtype == 'lvm' and sr.thinProvisioning:
            raise xenrt.XRTFailure("Able to create thin provisioned local lvm SR on the host %s" % (self.host))

    def createThinSR(self,srtype):

        step("Test trying to create thin provisioned %s SR " %(srtype))
        if srtype=="lvmoiscsi":
            lun = xenrt.ISCSITemporaryLun(300)
            sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host,"lvmoisci",True)
            try:
                sr.create(lun, subtype="lvm", findSCSIID=True, noiqnset=True)
            except Exception:
                xenrt.TEC().logverbose("Failed to create thin provisioned lvmoiscsi SR")
                raise
            else:
                self.checkThinProvisionSR(srtype,sr)
        elif srtype=="lvmohba":
            fcLun = self.host.lookup("SR_FCHBA", "LUN0")
            fcSRScsiid = self.host.lookup(["FC", fcLun, "SCSIID"], None)
            fcSR = xenrt.lib.xenserver.FCStorageRepository(self.host, "LVHDoHBA",True)
            try:
                fcSR.create(fcSRScsiid)
            except Exception:
                xenrt.TEC().logverbose("Unable to create thin provisioned lvmohba SR")
                raise
            else:
                self.checkThinProvisionSR(srtype,sr)
        elif srtype =="lvm":
            sr = ThinLVMStorageRepository(self.host,"thinlvm-sr")
            try:
                sr.create(self.host)
            except Exception:
                xenrt.TEC().logverbose("Unable to create thin provisioned lvm sr as expected")
            else:
                self.checkThinProvisionSR(srtype,sr)
        elif srtype =="nfs":
            sr = ThinNFSStorageRepository(self.host,"thin-nfssr")
            try:
                sr.create()
            except Exception:
                xenrt.TEC().logverbose("Unable to create thin provisioned NFS SR")
                raise
            else:
                self.checkThinProvisionSR(srtype,sr)
        else:
            raise xenrt.XRTError("Unknown SR Type")

    def prepare(self, arglist=None):
        self.host= self.getDefaultHost()
        self.srtypes=arglist[0].split(",")

    def run(self, arglist=None):
        for srtype in self.srtypes:
            self.runSubcase("createThinSR",(srtype),"ThinProvision",srtype)

class ThinNFSStorageRepository(xenrt.lib.xenserver.NFSStorageRepository):

    def create(self):
        if xenrt.TEC().lookup("FORCE_NFSSR_ON_CTRL", False, boolean=True):
            # Create an SR using an NFS export from the XenRT controller.
            # This should only be used for small and low I/O throughput
            # activities - VMs should never be installed on this.
            nfsexport = xenrt.NFSDirectory()
            server, path = nfsexport.getHostAndPath("")
        else:
            # Create an SR on an external NFS file server
            share = xenrt.ExternalNFSShare()
            nfs = share.getMount()
            r = re.search(r"([0-9\.]+):(\S+)", nfs)
            server = r.group(1)
            path = r.group(2)

        self.server = server
        self.path = path
        dconf = {}
        smconf = {}
        dconf["server"] = server
        dconf["serverpath"] = path
        smconf["allocation"]="dynamic"
        self._create("nfs",dconf,smconf=smconf)

class ThinLVMStorageRepository(xenrt.lib.xenserver.LVMStorageRepository):

    def getDevice(self,host):
        data = host.execdom0("cat /etc/firstboot.d/data/default-storage.conf " "| cat")
        r = re.search(r"PARTITIONS=['\"]*([^'\"\s]+)", data)
        if r:
            device = r.group(1)
        else:
            primarydisk = string.split(host.lookup("OPTION_CARBON_DISKS","sda"))[0]
            device = xenrt.formPartition("/dev/%s" % (primarydisk),3)
        return device

    def create(self,host):

        sr = host.getSRs(type="lvm")[0]
        # forget the existing thickly provisioned lvm on the host
        host.forgetSR(sr)
        device=self.getDevice(host)
        smconf = {}
        smconf["allocation"]="dynamic"
        self._create("lvm", {"device":device},smconf=smconf)

class ResetOnBootThinSRSpace(_ResetOnBootBase):
    """Verify that VM release the space when VDI on boot set to reset and VM state set to shutdown"""

    VDI_LIST = ["reset"]

    def getSRPhysicalSize(self,vdiuuid):
        # We yet to have a API to get the actual SR space allocated for specifc VDI
        return 0

    def prepare(self, arglist=None):
        self.host=self.getDefaultHost()
        self.goldVM = xenrt.TestCase.getGuest(self, "GoldVM")
        self.sr=self.host.lookupDefaultSR()
        self.guest, self.vdi = self.createTargetVM()
        #Start the Guest
        self.guest.setState("UP")
        # Write some data to guest VDI
        self.writeVDI(self.vdi[0])

    def run(self, arglist=None):
    
        step("Test trying to check SR physical space allocated for the VDI %s " % (self.vdi[0]))
        srSizeBefore=self.getSRPhysicalSize(self.vdi[0])
        xenrt.TEC().logverbose("Physical SR space allocated for the VDI :%s is :%s" % (self.vdi[0],srSizeBefore))

        # Now shutdown the guest
        step("Test trying to shutdown the guest whose VDI on boot set to reset") 
        self.guest.setState("DOWN")

        step("Test trying to check the SR physical space allocated for the VDI :%s after the VM shutdown" % (self.vdi[0]))
        srSizeAfter=self.getSRPhysicalSize(self.vdi[0])
        xenrt.TEC().logverbose("Physical SR space allocated for the VDI : %s after the VM shutdown is : %s" % (self.vdi[0],srSizeAfter))

        # We expect VM should release the space when it shutdown and VDI on boot set to 'reset'
        if srSizeBefore<=srSizeAfter:
            raise xenrt.XRTFailure("VM did not release the space when state set to shutdown. Physical SR size before :%s and SR size after VM shutdown: %s" %(srSizeBefore,srSizeAfter))
        xenrt.TEC().logverbose("Physical SR space for the VDI changed as expected")

