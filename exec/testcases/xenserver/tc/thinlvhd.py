# Test harness for Xen and the XenServer product family
#
# Thin provisioning functional verification test cases. 
# Refer FQP : https://info.citrite.net/pages/viewpage.action?pageId=1228996737
#
# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import re, string
import xenrt, xenrt.lib.xenserver
from xenrt.lazylog import step, log
from testcases.xenserver.tc.cache import _ResetOnBootBase


class _ThinLVHDBase(xenrt.TestCase):
    """Base class of thinprovisioning TCS.
    All TC specific utilities should be implemented in this class."""

    QUANTUM_RATIO = 0.2

    def prepare(self, arglist=[]):
        host = self.getDefaultHost()
        self.sr = self.getThinProvisioningSRs()
        self.setDefaultThinProv()

    def setDefaultThinProv(self):
        """Set default provisining rate to QUANTUM_RATIO"""
        for sr in self.sr:
            sr.setDefaultVDIAllocation(self.QUANTUM_RATIO)

    def createThinSR(self, host=None, name=None, srtype="lvmoiscsi", ietvm=False, size=0):
        """Creates a SR with given parameters.

        @param host: host instance to handle.
        @param name: name of sr.
        @param srtype: (sub)type of sr.
        @param ietvm: False by default. If it is True, a VM for sr will be created. (Not yet implemented yet)
        @param size: physical size to pass to SR.create()

        @return: created SR object
        """

        if not host:
            host = self.getDefaultHost()
        if not name or len(name) == 0:
            name = srtype + "sr"

        if srtype=="lvmoiscsi":
            lun = xenrt.ISCSITemporaryLun(300)
            sr = xenrt.lib.xenserver.ISCSIStorageRepository(host, name, True)
            sr.create(lun, subtype="lvm", physical_size=size, findSCSIID=True, noiqnset=True)

        elif srtype=="lvmohba":
            fcLun = host.lookup("SR_FCHBA", "LUN0")
            fcSRScsiid = host.lookup(["FC", fcLun, "SCSIID"], None)
            fcSR = xenrt.lib.xenserver.FCStorageRepository(host,  name, True)
            fcSR.create(fcSRScsiid, physical_size=size)

        else:
            raise xenrt.XRTException("Cannot create Thin-LVHD SR with given srtype %s." % srtype)

        return None

    def getDefaultSR(self):
        """Find default SR and return SR instance."""
        host = self.host
        if not host:
            host = self.getDefaultHost()

        sruuid = host.lookupDefaultSR()
        return xenrt.lib.xenserver.getStorageRepositoryClass(host, sruuid).fromExistingSR(host, sruuid)

    def getThinProvisioningSRs(self):
        """Find all ThinProvisioning SRs
        
        @return: a list of thin provisioned SRs. [] if none exists.
        """

        host = self.host
        if not host:
            host = self.getDefaultHost()

        srs = [xenrt.lib.xenserver.getStorageRepositoryClass(host, sr.uuid).fromExistingSR(host, sr.uuid)
                for sr in host.asXapiObject().SR(False)]

        return [sr for sr in srs if sr.thinProvisioning]

    def getPhysicalSize(self, sr):
        """Return physical size of sr."""

        #Dev does not have API for this yet

        return 0

    def fillDisk(self, guest, targetDir=None, size=512*1024*1024*1024):
        """Fill target disk by creating an empty file with
        given size on the given directory.

        @param guest: Target VM
        @param targetDir: Target directory of the VM. If none is given, use tmp
            by default.
        @param size: Size of the file to create in byte. Use 512M by default.

        If failed to create file due to any reason, raise an xenrt.XRTError.
        """

        if not targetDir:
            targetDir = guest.execguest("mktemp")

        guest.execguest("dd if=/dev/zero of=%s bs=4096 count=%d conv=notrunc" %
            (targetDir, size/4096))

    def isThinProvisioning(self, sr):
        """Return whether given SR is thin provision'ed or not

        @param sr: SR object or sr uuid.

        @return: boolean.
        """

        if not isinstance(sr, xenrt.lib.xenserver.StorageRepository):
            sr = xenrt.lib.xenserver.getStorageRepositoryClass(self, sr).fromExistingSR(self, sr)

        return sr.thinProvisioning


class ThinProvisionVerification(_ThinLVHDBase):
    """ Verify SW thin provisioning available only on LVHD """

    def createThinSR(self, srtype):

        step("Test trying to create thin provisioned %s SR " % (srtype))
        if srtype=="lvmoiscsi":
            lun = xenrt.ISCSITemporaryLun(300)
            sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host, "lvmoiscsi", True)
            try:
                sr.create(lun, subtype="lvm", findSCSIID=True, noiqnset=True)
            except Exception:
                xenrt.TEC().logverbose("Failed to create thin provisioned lvmoiscsi SR")
                raise
            else:
                if not self.isThinProvisioning(sr):
                    raise xenrt.XRTFailure("SR created of type LVMoISCSI on the host %s is not thin provisioned" % (self.host))

        elif srtype=="lvmohba":
            fcLun = self.host.lookup("SR_FCHBA", "LUN0")
            fcSRScsiid = self.host.lookup(["FC", fcLun, "SCSIID"], None)
            fcSR = xenrt.lib.xenserver.FCStorageRepository(self.host,  "LVHDoHBA", True)
            try:
                fcSR.create(fcSRScsiid)
            except Exception:
                xenrt.TEC().logverbose("Unable to create thin provisioned lvmohba SR")
                raise
            else:
                if not self.isThinProvisioning(sr):
                    raise xenrt.XRTFailure("SR created of type LVMoHBA on the host %s is not thin provisioned" % (self.host))

        elif srtype =="lvm":
            sr = ThinLVMStorageRepository(self.host, "thinlvm-sr")
            try:
                sr.create(self.host)
            except Exception:
                xenrt.TEC().logverbose("Unable to create thin provisioned lvm sr as expected")
            else:
                if not self.isThinProvisioning(sr):
                    raise xenrt.XRTFailure("Created LVM SR is thin provisioned on the host %s" % (self.host))

        elif srtype =="nfs":
            sr = ThinNFSStorageRepository(self.host, "thin-nfssr")
            try:
                sr.create()
            except Exception:
                xenrt.TEC().logverbose("Unable to create thin provisioned NFS SR")
                raise
            else:
                if not self.isThinProvisioning(sr):
                    raise xenrt.XRTFailure("SR created of type NFS on the host %s is not thin provisioned" % (self.host))

        else:
            raise xenrt.XRTError("Unknown SR Type")

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.srtypes=arglist[0].split(",")

    def run(self, arglist=None):
        for srtype in self.srtypes:
            self.runSubcase("createThinSR", (srtype), "ThinProvision", srtype)

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
        self._create("nfs", dconf, smconf=smconf)

class ThinLVMStorageRepository(xenrt.lib.xenserver.LVMStorageRepository):

    def getDevice(self, host):
        data = host.execdom0("cat /etc/firstboot.d/data/default-storage.conf " "| cat")
        r = re.search(r"PARTITIONS=['\"]*([^'\"\s]+)", data)
        if r:
            device = r.group(1)
        else:
            primarydisk = string.split(host.lookup("OPTION_CARBON_DISKS", "sda"))[0]
            device = xenrt.formPartition("/dev/%s" % (primarydisk), 3)
        return device

    def create(self, host):

        sr = host.getSRs(type="lvm")[0]
        # forget the existing thickly provisioned lvm on the host
        host.forgetSR(sr)
        device=self.getDevice(host)
        smconf = {}
        smconf["allocation"]="dynamic"
        self._create("lvm",  {"device":device}, smconf=smconf)

class ResetOnBootThinSRSpace(_ResetOnBootBase):
    """Verify that VM release the space when VDI on boot set to reset and VM state set to shutdown"""

    VDI_LIST = ["reset"]

    def getSRPhysicalSize(self, vdiuuid):
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
        xenrt.TEC().logverbose("Physical SR space allocated for the VDI :%s is :%s" % (self.vdi[0], srSizeBefore))

        # Now shutdown the guest
        step("Test trying to shutdown the guest whose VDI on boot set to reset") 
        self.guest.setState("DOWN")

        step("Test trying to check the SR physical space allocated for the VDI :%s after the VM shutdown" % (self.vdi[0]))
        srSizeAfter=self.getSRPhysicalSize(self.vdi[0])
        xenrt.TEC().logverbose("Physical SR space allocated for the VDI : %s after the VM shutdown is : %s" % (self.vdi[0], srSizeAfter))

        # We expect VM should release the space when it shutdown and VDI on boot set to 'reset'
        if srSizeBefore<=srSizeAfter:
            raise xenrt.XRTFailure("VM did not release the space when state set to shutdown. Physical SR size before :%s and SR size after VM shutdown: %s" %(srSizeBefore, srSizeAfter))
        xenrt.TEC().logverbose("Physical SR space for the VDI changed as expected")


class TCThinProvisioned(_ThinLVHDBase):
    """Verify LUN creates smaller than virtual size of all VDIs contained."""

    def prepare(self, arglist=[]):

        self.srs = self.getThinProvisioningSRs()
        if not self.srs:
            raise xenrt.XRTError("No thin provisioning SR found.")

    def runCase(self, sr, vms):

        log("Checking SR: %s..." % sr.name())

        origsize = self.getPhysicalSize(sr)
        self.guests = []
        for vm in range(vms):
            guest = self.host.createGenericLinuxGues(sr=sr.uuid)
            guest.setState("DOWN")
            guest.preCloneTailor()
            self.uninstallOnCleanup(guest)
            self.guests.append(guest)
 
        aftersize = self.getPhysicalSize(sr)

        if aftersize <= origsize:
            raise xenrt.XRTFailure("SR size is decreased after %d VDI creation. (before: %d, after %d)" %
                    (vms, origsize, aftersize))

        vdisize = 0
        for guest in self.guests:
            for xvdi in guest.asXapiObject().VDI():
                vdisize += xvdi.size()

        if aftersize >= origsize + vdisize:
            raise xenrt.XRTFailure("SR size is bigger than sum of all VDIs on ThinLVHD. (before: %d, after: %d, vdi: %s)" %
                    (origsize, aftersize, vdisize))
        
    def run(self, arglist=[]):

        args = self.parseArgsKeyValue(arglist)
        vms = 5
        if "vms" in args:
            vms = args["vms"]

        for sr in self.sr:
            self.runSubcase("runCase", (sr, vms), sr.name, "Check %d VDIs" % vms)


class TCSRIncrement(_ThinLVHDBase):
    """Check SR is increment on VDI increase."""

    def prepare(self, arglist=[]):

        super(TCSRIncrement, self).prepare(arglist)

        if not self.sr:
            raise xenrt.XRTError("No thin provisioning SR found.")

    def runCase(self, sr):

        log("Checking SR: %s..." % sr.name())

        guest = self.host.createGenericLinuxGues(sr=sr.uuid)
        guest.setState("DOWN")
        guest.preCloneTailor()
        self.uninstallOnCleanup(guest)
 
        origsize = self.getPhysicalSize(sr)

        self.fillDisk(guest, size=1024*1024*1024) # filling 1 GB

        aftersize = self.getPhyscialSize(sr)

        if aftersize <= origsize:
            raise xenrt.XRTFailure("SR size is not growing. (SR: %s, before: %d, after: %d)" %
                (sr.uuid, origsize, aftersize))

    def run(self, arglist=[]):

        for sr in self.sr:
            self.runSubcase("runCase", (sr,), sr.name, "Check %s" % sr.name)

