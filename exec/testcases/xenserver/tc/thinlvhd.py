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
import testcases.xenserver.tc.lunspace

class _ThinLVHDBase(xenrt.TestCase):
    """Base class of thinprovisioning TCS.
    All TC specific utilities should be implemented in this class."""

    def prepare(self, arglist=[]):
        host = self.getDefaultHost()
        self.sr = self.getThinProvisioningSRs()

    def __buildsmconfig(self, initialAlloc=None, quantumAlloc=None):
        """Create and return sm-config dict with given parameters.

        @param initialAlloc: Initial allocation
        @param quantumAlloc: Quantum allocation

        @return Dict of sm-config
        """

        smconf = {}
        if initialAlloc:
            smconf["initial_allocation"] = str(initialAlloc)
        if quantumAlloc:
            smconf["allocation_quantum"] = str(quantumAlloc)

        return smconf

    def createThinSR(self, host=None, name=None, srtype="lvmoiscsi", ietvm=False, size=0, initialAlloc=None, quantumAlloc=None):
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

        smconf = self.__buildsmconfig(initialAlloc, quantumAlloc)
        if srtype=="lvmoiscsi":
            if size:
                size /= xenrt.MEGA
            else:
                size = 100 * xenrt.KILO # 100 GiB
            if ietvm:
                lun = xenrt.ISCSIVMLun(sizeMB=size)
            else:
                lun = xenrt.ISCSITemporaryLun(size)
            sr = xenrt.lib.xenserver.ISCSIStorageRepository(host, name, True)
            sr.create(lun, subtype="lvm", physical_size=size, findSCSIID=True, noiqnset=True, smconf=smconf)

        elif srtype=="lvmohba":
            fcLun = host.lookup("SR_FCHBA", "LUN0")
            fcSRScsiid = host.lookup(["FC", fcLun, "SCSIID"], None)
            sr = xenrt.lib.xenserver.FCStorageRepository(host,  name, True)
            sr.create(fcSRScsiid, physical_size=size, smconf=smconf)

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
                log("%s type is not supported in SR instantiation." % (sr.srType(),))

        return [sr for sr in srs if sr.thinProvisioning]

    def getPhysicalUtilisation(self, sr):
        """Return physical size of sr."""

        host = self.host
        if not host:
            host = self.getDefaultHost()

        if not isinstance(sr, xenrt.lib.xenserver.StorageRepository):
            # if it is not SR object, then assumes it is sr uuid string.
            sr = xenrt.lib.xenserver.getStorageRepositoryClass(host, sr).fromExistingSR(host, sr)

        sr.scan()

        return int(sr.paramGet("physical-utilisation"))

    def fillDisk(self, guest, targetDir=None, size=512*xenrt.MEGA, source="/dev/zero"):
        """Fill target disk by creating an empty file with
        given size on the given directory.

        @param guest: Target VM
        @param targetDir: Target directory of the VM. If none is given, use tmp
            by default.
        @param size: Size of the file to create in byte. Use 512M by default.

        If failed to create file due to any reason, raise an xenrt.XRTError.
        """

        if guest.windows:
            # TODO: Windows in guest writing has not been tested.
            if not targetDir:
                targetDir = "C:\\test.bin"
            path = xenrt.TEC().lookup("LOCAL_SCRIPTDIR") + "/progs/winwrite/"
            xenrt.TEC().config.setVariable("WINDOWS_WRITE", guest.compileWindowsProgram(path) + "\\winwrite.exe") 
            data = guest.xmlrpcExec("%s %s" % (xenrt.TEC().lookup("WINDOWS_WRITE"), targetDir), returndata=True)

        else:
            if not targetDir:
                targetDir = guest.execguest("mktemp")

            timeout = 900 + ((size / xenrt.GIGA) * 300) # 15 mins + 5 mins per GIGA
            guest.execguest("dd if=%s of=%s bs=1M count=%d conv=notrunc" % (source, targetDir, size/xenrt.MEGA), timeout=timeout)

    def isThinProvisioning(self, sr):
        """Return whether given SR is thin provision'ed or not

        @param sr: SR object or sr uuid.

        @return: boolean.
        """

        if not isinstance(sr, xenrt.lib.xenserver.StorageRepository):
            sr = xenrt.lib.xenserver.getStorageRepositoryClass(self, sr).fromExistingSR(self, sr)

        return sr.thinProvisioning
        

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
        smconf["allocation"]="xlvhd"
        self._create("nfs", dconf, smconf=smconf)

class ThinLVMStorageRepository(xenrt.lib.xenserver.LVMStorageRepository):

    def getDevice(self, host):
        data = host.execdom0("cat /etc/firstboot.d/data/default-storage.conf")
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
        smconf["allocation"]="xlvhd"
        self._create("lvm",  {"device":device}, smconf=smconf)

class ResetOnBootThinSRSpace(_ThinLVHDBase):
    """Verify that VM release the space when VDI on boot set to reset and VM state set to shutdown"""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.goldVM = xenrt.TestCase.getGuest(self, "GoldVM")
        self.srs = self.getThinProvisioningSRs()
        if not self.srs:
            raise xenrt.XRTError("No thin provisioning SR is found.")

        self.guest = self.goldVM.copyVM(sruuid = self.srs[0].uuid)
        self.uninstallOnCleanup(self.guest)

    def run(self, arglist=None):

        step("Set VDI to reset on boot.")
        self.guest.setState("DOWN")
        for xvdi in self.guest.asXapiObject().VDI():
            self.host.genParamSet("vdi", xvdi.uuid, "on-boot", "reset")

        srSizeBefore = self.getPhysicalUtilisation(self.srs[0])
        xenrt.TEC().logverbose("Physical SR space allocated for the VDIs before writing: %d" % (srSizeBefore))

        step("Writing some data onto VDI")
        self.guest.setState("UP")
        self.fillDisk(self.guest, size=2*xenrt.GIGA)

        step("Test trying to check SR physical space allocated for the VDI(s)")
        srSizeAfter = self.getPhysicalUtilisation(self.srs[0])
        xenrt.TEC().logverbose("Physical SR space allocated for the VDIs after writing: %d" % (srSizeAfter))

        # Now shutdown the guest
        step("Rebooting VM to release leaf of VDI") 
        self.guest.reboot()

        step("Test trying to check the SR physical space allocated for the VDI after reset-on-boot VM shutdown")
        srSizeFinal = self.getPhysicalUtilisation(self.srs[0])
        xenrt.TEC().logverbose("Physical SR space allocated for the VDI after the VM shutdown: %d" % (srSizeFinal))

        # We expect VM should release the space when it shutdown and VDI on boot set to 'reset'
        if srSizeBefore >= srSizeAfter:
            raise xenrt.XRTFailure("SR physical utilisation has not been increased after writing data in VDI.")

        if srSizeAfter >= srSizeFinal:
            raise xenrt.XRTFailure("SR Physical utilisation is not decreased after reset-on-boot VM rebooted.")


class TCThinProvisioned(_ThinLVHDBase):
    """Verify LUN creates smaller than virtual size of all VDIs contained."""

    def prepare(self, arglist=[]):

        super(TCThinProvisioned, self).prepare(arglist)
        if not self.sr:
            raise xenrt.XRTError("No thin provisioning SR found.")

    def runCase(self, sr, vms):

        log("Checking SR: %s..." % sr.name)

        origsize = self.getPhysicalUtilisation(sr)
        self.guests = []
        for vm in range(vms):
            guest = self.host.createGenericLinuxGuest(sr=sr.uuid)
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
        vms = 1
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

        log("Checking SR: %s..." % sr.name)

        guest = self.host.createGenericLinuxGuest(sr=sr.uuid)
        guest.setState("DOWN")
        guest.preCloneTailor()
        self.uninstallOnCleanup(guest)
 
        origsize = self.getPhysicalUtilisation(sr)

        self.fillDisk(guest, size = 2 * xenrt.GIGA) # filling 2 GB

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

        # Check that quantum allocation is as expected
        vdiSize = self.getPhysicalVDISize(vdiuuid, self.host)
        expectedSize = vdiSize + self.sizebytes * ( float(quantum) if quantum else self.DEFAULTQUANTUM)

        vbduuid = self.host.genParamGet("vdi", vdiuuid, "vbd-uuids")
        self.fillDisk(self.guest, targetDir = "/dev/%s" %(self.host.genParamGet("vbd", vbduuid, "device")), size = expectedSize - vdiSize)

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

    def testingThinAllocation(self, SRinitial = None, SRquantum = None):

        self.doTest(SRinitial, SRquantum)

    def run(self, arglist=[]):

        # Create thin SR with default initial/quantum
        self.sr = self.createThinSR(host = self.host, size=200, srtype = self.srtype)

        self.testingThinAllocation()

        # Test that we can change the default SR config with the custom value 
        for SRinitial, SRquantum in map(None, self.SRinitial, self.SRQuantum):
            self.testingThinAllocation(SRinitial, SRquantum )

class TrimFuncNetAppThinISCSI(testcases.xenserver.tc.lunspace.TrimFuncNetAppISCSI):
    """Test the XenServer TRIM feature on a thin provisioned iSCSI SR using NetApp array"""

    THINPROVISION = True
    SRNAME = "lvmoiscsi-thin"

class TrimFuncNetAppThinFC(testcases.xenserver.tc.lunspace.TrimFuncNetAppFC):
    """Test the XenServer TRIM feature on a thin provisioned Fibre Channel SR using NetApp array"""

    THINPROVISION = True
    SRNAME = "lvmohba-thin"
    
class TCThinLVHDSRProtection(_ThinLVHDBase):
    """ Verify protection when master is down. """

    DEFAULTVDISIZE = 10*xenrt.GIGA

    def checkVdiWrite(self, guest, device = None, size=xenrt.GIGA):
        try:
            self.fillDisk(guest, size=size, targetDir=device)
        except Exception, e:
                log("Not able to write in to device %s on the guest %s : failed with exception %s: " % (device, guest, str(e)))
                return False
        return True

    def prepare(self, arglist):
        args  = self.parseArgsKeyValue(arglist)
        self.pool = self.getDefaultPool()
        self.master = self.pool.master
        self.slave = self.pool.getSlaves()[0]
        self.backupMaster = self.pool.getSlaves()[1]
        self.sruuid = self.pool.getPoolParam("default-SR")
        self.vdisize = int(args.get("vdisize", self.DEFAULTVDISIZE))
        vmonlocalsr = bool(args.get("vmonlocalsr", False))
        if vmonlocalsr:
            localsruuid = self.slave.getLocalSR()
            self.guest = self.slave.createBasicGuest("generic-linux", sr=localsruuid)
        else:
            self.guest = self.slave.createBasicGuest("generic-linux", sr=self.sruuid)

    def run(self, arglist):
        step("Creating a virtual disk and attaching to VM...")
        device = self.guest.createDisk(sizebytes=self.vdisize, returnDevice=True)
        step("Shutting down the pool master ...")
        self.master.machine.powerctl.off()
        xenrt.sleep(180)
        step("Verify that we can write minimum 1GiB of data onto the guest when pool master is down") 
        if not self.checkVdiWrite(self.guest, device):
            raise xenrt.XRTFailure("Not able to write minimum 1 GiB of data onto the guest %s when the pool master is down" % (self.guest))
        step("Verify that we not able to write more than 3GiB of data onto the guest when the pool master is down")
        if self.checkVdiWrite(self.guest, device, size=3*xenrt.GIGA):
            raise xenrt.XRTFailure("Able to write more than 3 GiB of data onto the guest %s when the pool master is down" % (self.guest))
        step("Bringing the pool master Up again...")
        self.master.machine.powerctl.on() 
        # Wait for it to boot up
        self.master.waitForSSH(900)
        step("Verify that we can write more than 3 GiB of data onto the guest %s when the pool master is up" % (self.guest))
        if not self.checkVdiWrite(self.guest, device, size=3*xenrt.GIGA):
            raise xenrt.XRTFailure("Not able to write more than 3 GiB of data onto the guest %s when the pool master is up" % (self.guest))
        step("Eject the master from the pool ...")
        self.master.machine.powerctl.off()
        xenrt.sleep(15)
        self.pool.setMaster(self.backupMaster)
        self.pool.recoverSlaves()
        self.pool.eject(self.master)
        step("Verify that we can write more than 3 GiB of data onto the guest %s with the new pool master" % (self.guest))
        if not self.checkVdiWrite(self.guest, device, size=3*xenrt.GIGA):
            raise xenrt.XRTFailure("Not able to write more than 3 GiB onto the guest %s after elect a new pool master" % (self.DEFAULTMAXDATA))

    def postRun(self):
        self.master.machine.powerctl.on() 
        # Wait for it to boot up
        self.master.waitForSSH(900)

class TCThinLVHDVmOpsSpace(_ThinLVHDBase):
    """verify suspended/snapshot VDIs take space properly"""

    DEFAULTSRTYPE = "lvmoiscsi"
    GUESTMEMORY = 8192 # in MiB

    def checkVDIPhysicalSize(self, vdiuuid, expectedVdiSize):
        vdiPhysicalSize = self.getPhysicalVDISize(vdiuuid)
        if vdiPhysicalSize < expectedVdiSize:
            raise xenrt.XRTFailure("VDI Physical size not as expected. Expected at least %s bytes but found %s bytes" %
                                  (expectedVdiSize, vdiPhysicalSize))

    def checkSRPhysicalUtil(self, expectedphysicalUtil):
        step("Checking the SR physical utilization. Expected SR physical utilization is %s bytes..." % (expectedphysicalUtil))
        srPhysicalUtil = self.getPhysicalUtilisation(self.sr)
        if srPhysicalUtil < expectedphysicalUtil:
            raise xenrt.XRTFailure("SR physical utilization not as expected. Expected at least %s bytes but found %s bytes" %
                                  (expectedphysicalUtil, srPhysicalUtil))

    def checkSRPhysicalUtil2(self, expectedphysicalUtil):
        step("Checking the SR physical utilization. Expected SR physical utilization is %s bytes..." % (expectedphysicalUtil))
        srPhysicalUtil = self.getPhysicalUtilisation(self.sr)
        if srPhysicalUtil > expectedphysicalUtil:
            raise xenrt.XRTFailure("SR physical utilization not as expected. Expected at max %s bytes but found %s bytes" %
                                  (expectedphysicalUtil, srPhysicalUtil))

    def performVmOps(self):
        """ This function check's that checkpoint/suspend operation on thin-provisioned SR works as expected"""

        self.phyUtilBeforeCheckpoint = self.getPhysicalUtilisation(self.sr) + self.guestMemory
        step("Taking the vm checkpoint...")
        self.checkuuid = self.guest.checkpoint()
        vdiUuid = self.host.genParamGet("vm", self.checkuuid, "suspend-VDI-uuid")
        step("check SR Physical utilization...")
        self.checkSRPhysicalUtil(self.phyUtilBeforeCheckpoint)
        step("Test that VDI created after checkpoint is thick provisioned by checking the size...")
        self.checkVDIPhysicalSize(vdiUuid, self.guestMemory)

        expectedphysicalUtil = self.getPhysicalUtilisation(self.sr) + self.guestMemory
        step("Suspending the VM...")
        self.guest.suspend()
        suspendVdiUuid = self.guest.paramGet("suspend-VDI-uuid")
        step("check SR Physical utilization...")
        self.checkSRPhysicalUtil(expectedphysicalUtil)
        step("Test that VDI created after suspend is thick provisioned by measuring the size...")
        self.checkVDIPhysicalSize(suspendVdiUuid, self.guestMemory) 

    def revertVmOps(self):
        """This function check's that resume/revert on thin-provision SR works as expected"""
        if self.guest.getState() == "SUSPENDED":
            expectedphysicalUtil = self.getPhysicalUtilisation(self.sr) - self.guestMemory
            step("Resuming the VM...")
            self.guest.resume()
            self.guest.check()
            self.checkSRPhysicalUtil2(expectedphysicalUtil)
        if self.checkuuid:
            step("Reverting the checkpoint...")
            self.guest.revert(self.checkuuid)
            self.guest.check()
            self.checkSRPhysicalUtil2(self.phyUtilBeforeCheckpoint)

    def prepare(self, arglist=[]):
        args = self.parseArgsKeyValue(arglist)
        self.host = self.getDefaultHost()
        self.srtype = args.get("srtype", self.DEFAULTSRTYPE)
        self.guestMemory = int(args.get("guestmemory", self.GUESTMEMORY))
        self.checkuuid = None
        srs = self.getThinProvisioningSRs()
        if not srs:
            step("Creating thin provisioned SR of type %s" %(self.srtype))
            self.sr = self.createThinSR(host=self.host, size=200, srtype=self.srtype)
        else:
            self.sr = srs[0]
        if "guest" in args:
            self.guest = self.getGuest(args["guest"]) 
            self.guest.setState("UP")
        else:
            self.guestMemory = int(args.get("guestmemory", self.GUESTMEMORY))
            self.guest = self.host.createBasicGuest("generic-linux", sr=self.sr.uuid, memory=self.guestMemory)
        log("setting up the SR %s as a default SR of the host" % (self.srtype))
        self.host.addSR(self.sr, default=True)
        self.guestMemory = self.guestMemory * xenrt.MEGA
        log("Guest memory reported %s bytes" % (self.guestMemory))

    def run(self, arglist=[]):

        # Test that snapshot/suspend works as expected on thin-provisioned SR.
        if self.runSubcase("performVmOps", (), "vmops-snapshot/suspend", "Guest Memory=%s bytes"\
                            %(self.guestMemory))== xenrt.RESULT_PASS:
            # Test that resume/revert works as expected on thin-provisioned SR
            self.runSubcase("revertVmOps", (), "vmops-resume/revert", "Guest Memory=%s bytes" % (self.guestMemory))
