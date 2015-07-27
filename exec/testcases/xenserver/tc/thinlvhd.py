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

    def createThinSR(self, host=None, name=None, srtype="lvmoiscsi", ietvm=False, size=0, initialAlloc = None, quantumAlloc = None):
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
            sr = xenrt.lib.xenserver.ISCSIStorageRepository(host, name, True, initialAlloc, quantumAlloc)
            sr.create(lun, subtype="lvm", physical_size=size, findSCSIID=True, noiqnset=True)

        elif srtype=="lvmohba":
            fcLun = host.lookup("SR_FCHBA", "LUN0")
            fcSRScsiid = host.lookup(["FC", fcLun, "SCSIID"], None)
            sr = xenrt.lib.xenserver.FCStorageRepository(host,  name, True, initialAlloc, quantumAlloc)
            sr.create(fcSRScsiid, physical_size=size)

        else:
            raise xenrt.XRTException("Cannot create Thin-LVHD SR with given srtype %s." % srtype)

        return sr

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

        srs = []
        for sr in host.asXapiObject().SR(False):
            try:
                srs.append(xenrt.lib.xenserver.getStorageRepositoryClass(host, sr.uuid).fromExistingSR(host, sr.uuid))
            except:
                log("%s type does not support thin-lvhd." % (sr.srType(),))

        return [sr for sr in srs if sr.thinProvisioning]

    def getPhysicalUtilisation(self, sr):
        """Return physical size of sr."""

        host = self.host
        if not host:
            host = self.getDefaultHost()

        xsr = next((s for s in host.asXapiObject().SR() if s.uuid == sr), None)
        if not xsr:
            xenrt.XRTError("Cannot find given SR: %s" % (sr,))

        host.execdom0("xe sr-scan uuid=%s" % xsr.uuid)
        return self.xsr.getIntParam("physical-utilisation")

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

        guest.execguest("dd if=/dev/urandom of=%s bs=4096 count=%d conv=notrunc" %
            (targetDir, size/4096))

    def isThinProvisioning(self, sr):
        """Return whether given SR is thin provision'ed or not

        @param sr: SR object or sr uuid.

        @return: boolean.
        """

        if not isinstance(sr, xenrt.lib.xenserver.StorageRepository):
            sr = xenrt.lib.xenserver.getStorageRepositoryClass(self, sr).fromExistingSR(self, sr)

        return sr.thinProvisioning
        
    def changeSRsmconfig(self, SRinitial, SRquantum):
        """Change the initial/quantum to given value

        @param SRinitial : initial_allocation of the SR
        @param SRquantum : allocation_quantum of the SR

        @return : None
        """
        smconfig = {}
        if SRinitial:
            smconfig["initial_allocation"] = SRinitial
        if SRquantum:
            smconfig["allocation_quantum"] = SRquantum
        
        # TODO awaiting Dev: API is not ready yet to change the SR smconfig.
        pass

    def getPhysicalVDISize(self, vdiuuid, host=None ):
        if not host:
            host = self.getDefaultHost()
        return host.getVDIPhysicalSizeAndType(vdiuuid)[0]

class ThinProvisionVerification(_ThinLVHDBase):
    """ Verify SW thin provisioning available only on LVHD """

    def testThinSRCreation(self, srtype):

        step("Test trying to create thin provisioned %s SR " % (srtype))
        if srtype in ['lvmoiscsi', 'lvmohba']:
            try:
                sr = self.createThinSR(host=self.host, size=200, srtype= srtype)
            except Exception as e:
                xenrt.TEC().logverbose("Failed to create thin provisioned %s SR with Exception : %s " % (srtype, str(e)))
                raise
            else:
                if not self.isThinProvisioning(sr):
                    raise xenrt.XRTFailure("SR created of type %s on the host %s is not thin provisioned" % (srtype, self.host))

        elif srtype =="lvm":
            try:
                sr = ThinLVMStorageRepository(self.host, "thinlvm-sr")
                sr.create(self.host)
            except Exception:
                xenrt.TEC().logverbose("Unable to create thin provisioned lvm sr as expected")
            else:
                if self.isThinProvisioning(sr):
                    raise xenrt.XRTFailure("Created LVM SR is thin provisioned on the host %s" % (self.host))

        elif srtype =="nfs":
            try:
                sr = ThinNFSStorageRepository(self.host, "thin-nfssr")
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
            self.runSubcase("testThinSRCreation", (srtype), "ThinProvision", srtype)

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
        # TODO : Raise the exception
            pass
        xenrt.TEC().logverbose("Physical SR space for the VDI changed as expected")


class TCThinProvisioned(_ThinLVHDBase):
    """Verify LUN creates smaller than virtual size of all VDIs contained."""

    def prepare(self, arglist=[]):

        self.srs = self.getThinProvisioningSRs()
        if not self.srs:
            raise xenrt.XRTError("No thin provisioning SR found.")

    def runCase(self, sr, vms):

        log("Checking SR: %s..." % sr.name())

        origsize = self.getPhysicalUtilisation(sr)
        self.guests = []
        for vm in range(vms):
            guest = self.host.createGenericLinuxGues(sr=sr.uuid)
            guest.setState("DOWN")
            guest.preCloneTailor()
            self.uninstallOnCleanup(guest)
            self.guests.append(guest)
 
        aftersize = self.getPhysicalUtilisation(sr)

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
 
        origsize = self.getPhysicalUtilisation(sr)

        self.fillDisk(guest, size=1024*1024*1024) # filling 1 GB

        aftersize = self.getPhysicalUtilisation(sr)

        if aftersize <= origsize:
            raise xenrt.XRTFailure("SR size is not growing. (SR: %s, before: %d, after: %d)" %
                (sr.uuid, origsize, aftersize))

    def run(self, arglist=[]):

        for sr in self.sr:
            self.runSubcase("runCase", (sr,), sr.name, "Check %s" % sr.name)


class TCThinAllocationDefault(_ThinLVHDBase):
    """Verify the initial/quantum allocation works for SR and VDI ."""

    # At present, We have 20% for initial allocation and 1% for allocation quantum as default
    DEFAULTINITIAL = 0.2
    DEFAULTQUANTUM = 0.01

    DEFAULTSRTYPE = "lvmoiscsi"

    def prepare(self, arglist=[]):
        args = self.parseArgsKeyValue(arglist)
        self.SRinitial = args.get("initial_allocation", "").split(',')
        self.SRQuantum = args.get("allocation_quantum", "").split(',')
        self.vdiInitial = args.get("vdi_initial", "").split(',')
        self.vdiQuantum = args.get("vdi_quantum", "").split(',')
        self.srtype = args.get("srtype", self.DEFAULTSRTYPE)
        guest = args.get("guest", None)
        self.sizebytes= 10 * xenrt.MEGA 
        self.host = self.getDefaultHost()
        if not guest:
            self.guest = self.host.createBasicGuest("generic-linux")
        else:
            self.guest = self.getGuest(guest)

    def removeDisk(self,vdiuuid,vbduuid):
        """ Function delete's  the VDI: unplug the VBD and destory the VDI """
        cli = self.host.getCLIInstance()
        cli.execute("vbd-unplug", "uuid=%s" % (vbduuid))
        cli.execute("vbd-destroy", "uuid=%s" % (vbduuid))
        cli.execute("vdi-destroy", "uuid=%s" % (vdiuuid))

    def createDisk(self,smconfig={}):
        """ Function Create's the VDI : create the VDI and create VBD and plug it to guest """
        step("Creating a virtual disk and attaching to VM...")
        vdiuuid = self.host.createVDI(self.sizebytes, self.sr.uuid, smconfig=smconfig)
        vbduuid = self.guest.createDisk(vdiuuid = vdiuuid, returnVBD=True)
        return vdiuuid,vbduuid

    def check(self, vdiuuid, initial = DEFAULTINITIAL, quantum = DEFAULTQUANTUM):
        """Calculate the expected size of VDI based on the initial/quantum and
           compare it with actual physical size of VDI

        @param initial : initial allocation decided 
        @param quantum : quantum allocation decided

        @return : None ( This method make the test to fail if the expectedSize is not equal to VDI physical size
        """

        # Check that initial allocation is as expected
        expectedSize = self.sizebytes * ( float(initial) if initial else self.DEFAULTINITIAL)

        # TODO awaiting Dev: compare the actual physical size of VDI with the expectedSize ( No API yet )

        # Check that quantum allocation is as expected
        vdiSize = self.getPhysicalVDISize(vdiuuid, self.host)
        expectedSize = vdiSize + self.sizebytes * ( float(quantum) if quantum else self.DEFAULTQUANTUM)

        vbduuid = self.host.genParamGet("vdi", vdiuuid, "vbd-uuids")
        self.fillDisk(self.guest, targetDir = "/dev/%s" %(self.host.genParamGet("vbd", vbduuid, "device")), size = expectedSize - vdiSize)

        # TODO awaiting Dev: compare the actual physical size of VDI with the expectedSize ( No API yet)

    def doTest(self, SRinitial, SRquantum):
        """Decides the VDI initial/quantum and initiate the VDI check

        @param SRinitial : initial_allocation of the SR
        @param SRquantum : allocation_quantum of the SR

        @return : None

        """
        smconfig = {}
        for vdiinitial,vdiquantum in map(None, self.vdiInitial, self.vdiQuantum):
            if vdiinitial:
                smconfig["initial_allocation"] = vdiinitial
            else:
                vdiinitial = SRinitial
            if vdiquantum:
                smconfig["allocation_quantum"] = vdiquantum
            else:
                vdiquantum = SRquantum 

            # Create a VDI with a given smconfig
            (vdiuuid,vbduuid) = self.createDisk(smconfig = smconfig)

            # Check initial/quantum is as expected for the VDI
            self.check(vdiuuid, vdiinitial, vdiquantum )

            # Delete the VDI created
            self.removeDisk(vdiuuid, vbduuid)


    def testThinAllocation(self, SRinitial, SRquantum, SRtype):

        smconfig = {}
        # Create thin SR with given config : initial_allocation and allocation_quantum
        self.sr = self.createThinSR(host=self.host, size=200, srtype= SRtype, initialAlloc=SRinitial, quantumAlloc=SRquantum)
 
        # Create a VDI without any smconfig
        (vdiuuid,vbduuid) = self.createDisk()

        # Check initial/quantum is as expected for the VDI
        self.check(vdiuuid, SRinitial, SRquantum)
        
        # Delete the VDI created
        self.removeDisk(vdiuuid, vbduuid)

        self.doTest(SRinitial, SRquantum)
        
        # Delete the SR
        log("Distroying SR.")
        self.sr.destroy()

    def run(self, arglist=[]):

        # Test with Default SR allocation value (initial/quantum) i.e creating SR with no allocation.
        self.runSubcase("testThinAllocation", (None, None, self.srtype,), "ThinAllocation", 'Default %s initial, Default %s quantum'
                        % (self.DEFAULTINITIAL, self.DEFAULTQUANTUM ) )

        # Test with Custom SR allocation values (initial/quantum) i.e creating SR with custom allocation.
        for SRinitial, SRquantum in map(None, self.SRinitial, self.SRQuantum) :
            self.runSubcase("testThinAllocation", (SRinitial, SRquantum, self.srtype,), "ThinAllocation", '%s initial, %s quantum'
                            % (SRinitial, SRquantum ) )

class TCThinAllocation(TCThinAllocationDefault):

    def testingThinAllocation(self, changeSmconfig = False, SRinitial = None, SRquantum = None):

        if changeSmconfig:
            self.changeSRsmconfig(SRinitial, SRquantum)

        self.doTest(SRinitial, SRquantum)

    def run(self, arglist=[]):

        # Create thin SR with default initial/quantum
        self.sr = self.createThinSR(host = self.host, size=200, srtype = self.srtype)

        self.testingThinAllocation()

        # Test that we can change the default SR config with the custom value 
        for SRinitial, SRquantum in map(None, self.SRinitial, self.SRQuantum):
            self.testingThinAllocation(True, SRinitial, SRquantum )

