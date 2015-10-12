#
# XenRT: Custom test case (Python) file.
#
# Testcases for validation Clearwater Configuration Limits (PR-1566)
#

import socket, re, string, time, traceback, sys, random, copy, math
import xenrt, xenrt.lib.xenserver
from xenrt.lazylog import log

class _MaxMemory(xenrt.TestCase):
    """Base class for maximum memory per VM test"""
    MEMORY = 131072
    VM_TYPE = "HVM"
    ARCH = "x86-64"
    DISTRO = ""
    
    def prepare(self, arglist=None):
        # Get a host to install on
        host = self.getDefaultHost()
        self.FREE_MEMORY = host.getFreeMemory()
        if self.MEMORY > self.FREE_MEMORY:
            raise xenrt.XRTError("Not enough free memory on host")
        if self.MEMORY == True:
            #self.MEMORY = int(host.lookup("MAX_MEM_%s" % (self.VM_TYPE)))
            self.MEMORY = int(xenrt.TEC().lookup(["VERSION_CONFIG",xenrt.TEC().lookup("PRODUCT_VERSION"),"MAX_MEM_%s" % (self.VM_TYPE)]))
        # Install the VM
        xenrt.TEC().logverbose("Installing VM...")
        self.installVM(host)
        self.uninstallOnCleanup(self.guest)
        xenrt.TEC().logverbose("...VM installed successfully")
        
    def run(self, arglist=None):
        """Do testing tasks in run"""
        xenrt.TEC().logverbose("Setting VM memory to maximum value")
        xenrt.TEC().logverbose("Shutdown VM")
        self.guest.shutdown()
        xenrt.TEC().logverbose("Set VM memory to maximum value")
        self.guest.memset(self.MEMORY)
        xenrt.TEC().logverbose("Starting guest...")
        self.guest.start()
        xenrt.TEC().logverbose("...Started")
        # Perform some lifecycle operations
        if self.runSubcase("lifecycleOperations", (), "LifecycleOperations", "LifecycleOperations") != \
            xenrt.RESULT_PASS:
            return
        #check memory of VM
        if self.guest.memget() != self.MEMORY:
            raise xenrt.XRTFailure("Memory of guest is not equal to memory alloted")
        
        
    def lifecycleOperations(self):
        xenrt.TEC().logverbose("Reboot VM")
        self.guest.reboot()
        self.guest.waitForAgent(180)
        xenrt.TEC().logverbose("Shutdown VM")
        self.guest.shutdown()
        xenrt.TEC().logverbose("Start VM")
        self.guest.start()
        self.guest.waitForAgent(180)
        xenrt.TEC().logverbose("Suspend VM")
        self.guest.suspend(extraTimeout=3600)
        xenrt.TEC().logverbose("Resume VM")
        self.guest.resume()  
    
    def installVM(self, host):
        self.guest = host.createBasicGuest(distro=self.DISTRO, arch=self.ARCH)

class TC18839(_MaxMemory):
    """maximum memory per VM test for HVM VM"""
    MEMORY = True
    VM_TYPE = "HVM"
    DISTRO = "win7-x64"

class TC18840(_MaxMemory):
    """maximum memory per VM test for PV VM 64-bit"""
    MEMORY = True
    VM_TYPE = "PV64"
    ARCH = "x86-64"
    DISTRO = "centos62"
    
class TC18841(_MaxMemory):
    """maximum memory per VM test for PV VM 32-bit"""
    MEMORY = True
    VM_TYPE = "PV32"
    ARCH = "x86-32"
    DISTRO = "oel57"

class TC18836(xenrt.TestCase):
    """TestCase to verify the host can have specified VCPUs"""
    
    def prepare(self, arglist=None):
        
        #Get the Host
        self.host = self.getDefaultHost()
        
        #Create the Default generic guest VM
        self.guest = self.host.createGenericLinuxGuest()
    
    def run(self, arglist=None):
        
        #Initialize the maxcount of VCPUs
        maxcount =  int(xenrt.TEC().lookup(["VERSION_CONFIG",xenrt.TEC().lookup("PRODUCT_VERSION"),"MAX_VCPU_COUNT"]))
        clones = int(maxcount/16)
        
        #Have the array for the uuids of the VMs
        countlist = []
        self.vmuuids = []
        
        try:
            #Shutdown the base VM
            self.guest.shutdown()
            self.vmuuids.append(self.guest.getUUID())
            
            #Create the 16 vcpus for the base VM
            self.guest.cpuset(16)
            
            #Clone this VM until we get 900 VCPUs on host
            for num in range(1, clones):
                guest = self.guest.cloneVM(name=None, timer=None, sruuid=None, noIP=False)
                guest.start()
                self.vmuuids.append(guest.getUUID())
                count = guest.cpuget()
                countlist.append(count)
                xenrt.TEC().logverbose("In iteration %d, VM Cloned is %s with UUID %s" % (num, guest.name, guest.uuid))
                if count != 16:
                    raise xenrt.XRTFailure("VCPUs expected for the VM %s is 16 in actual is %d" % (guest.name, count))
                    break
                    
            xenrt.TEC().logverbose("VMs are cloned successfully each having 16 VCPUs")
        
            #Initialize the last guest with 4 vcpus
            guest = self.guest.cloneVM(name=None, timer=None, sruuid=None, noIP=False)
            guest.cpuset(maxcount%16)
            guest.start()
            self.vmuuids.append(guest.getUUID())
            count = guest.cpuget()
            countlist.append(count)
            
            #Start the base VM
            self.guest.start()
            count = self.guest.cpuget()
            countlist.append(count)
            
        except xenrt.XRTFailure, e:
            raise xenrt.XRTFailure("Failed to check scalability of host to 900 VCPUs")
        
        #Check the count of vcpus on Host
        counter = 0
        for i in countlist:
            counter = i + counter
        
        if counter != maxcount:
            raise xenrt.XRTFailure("VCPUs mismatch for the Host, Expected is %d and Actual is %d" % (maxcount, counter))
        
        xenrt.TEC().logverbose("TestCase Passed, Host can have %s VCPUs" % counter)
        
        #Deleting the cloned VMs
        self.cleanup()
    
    def cleanup(self, arglist=None):
        try:
            cli = self.host.getCLIInstance()
            for vmuuid in self.vmuuids:
                if self.host.genParamGet('vm', vmuuid, 'power-state') != 'halted':
                    cli.execute('vm-shutdown', 'vm=%s --force' % vmuuid)
                cli.execute('vm-uninstall', 'vm=%s --force' % vmuuid)
                xenrt.TEC().logverbose("VM %s is deleted" % vmuuid)
            xenrt.TEC().logverbose("All VMs are deleted successfully")
        except xenrt.XRTFailure, e:
            raise xenrt.XRTFailure("Unable to delete the Cloned VMs")

class TC18838(xenrt.TestCase):
    """ Test to attach 150 Multipath LUNs to a Host"""
    MAXLUNS = 150
    CONCURRENT_MAXLUNS = 150
    LUNSIZE = 500
    MAXPATHS = 2
    SRs = []
    LUNs = []
    VBDs = []
    VDIs = []
    VMs = []
    def prepare(self, arglist=None):
        #Get the Host 0
        self.targetHost = self.getHost("RESOURCE_HOST_0")
        self.host0 = self.getHost("RESOURCE_HOST_1")
        self.MAXLUNS = int(self.host0.lookup("MAX_MULTIPATH_LUN"))
        self.CONCURRENT_MAXLUNS = int(self.host0.lookup("CONCURRENT_MAX_MULTIPATH_LUN"))
        #Loop created to have MAXLUNS luns
        for i in range(self.MAXLUNS):
            #This will create an iSCSI VM along with LUNS
            lun = xenrt.ISCSIVMLun(sizeMB = self.LUNSIZE, totalSizeMB = (self.MAXLUNS * self.LUNSIZE))
            self.LUNs.append(lun)
            #This will take the instance of SR for host0
            sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host0, "iscsi%d" % i)
            self.SRs.append(sr)
            #This will attach the iSCSI SR to the host0
            sr.create(lun, subtype="lvm", multipathing=True, noiqnset=True, findSCSIID=True)
            
            pbd = self.host0.parseListForUUID("pbd-list", "sr-uuid", sr.uuid, "host-uuid=%s" % (self.host0.getMyHostUUID()))
            scsiID = self.host0.genParamGet("pbd", pbd, "device-config", "SCSIid")
            xenrt.sleep(60)
            #Check Multipathing
            mp = self.host0.getMultipathInfo()
            if len(mp[scsiID]) != self.MAXPATHS:
                raise xenrt.XRTError("Only found %u/%u paths in multipath output" % (len(mp[scsiID]),self.MAXPATHS))
            #Check the multiple active paths
            mp = self.host0.getMultipathInfo(onlyActive=True)
            if len(mp[scsiID]) != self.MAXPATHS:
                raise xenrt.XRTError("Only %u/%u paths active before test started" % (len(mp[scsiID]),self.MAXPATHS))
            
    
    def run(self, arglist=None):
        #Verify these LUNs are accessible and have all their paths UP
        cli = self.host0.getCLIInstance()
        #Create a base VM
        guest = self.host0.createGenericLinuxGuest()
        self.VMs.append(guest)
        guest.preCloneTailor()
        guest.shutdown()
        #Loop to create the VDIs
        for i in range (self.CONCURRENT_MAXLUNS):
            
            #Need to create VMs to attach VDIs - Single VM can have 15 VDIs on 15 LUNs
            if (i % 15) == 0:
                g = guest.copyVM(name="VMcopy" + str(i))
                self.VMs.append(g)
                g.start()
            
            #Create a VDI for each LUN
            args = []
            args.append("name-label='XenRT Test VDI on %s'" % (self.SRs[i].uuid))
            args.append("sr-uuid=%s" % (self.SRs[i].uuid))
            args.append("virtual-size=268435456") # 256M
            args.append("type=user")
            vdi = cli.execute("vdi-create", string.join(args), strip=True)
            self.VDIs.append(vdi)
            
            #Attach this VDI to VM of host0
            vbd = g.createDisk(vdiuuid=vdi, returnVBD=True)
            self.VBDs.append(vbd)
            
        #Clean the setup of LUNs
        self.cleansetup()
    
    def cleansetup(self, arglist=None):
        
        cli = self.host0.getCLIInstance()
        #Delete the VDIs
        for i in range (self.CONCURRENT_MAXLUNS):
            cli.execute("vbd-unplug", "uuid=%s" % (self.VBDs[i]))
            cli.execute("vbd-destroy", "uuid=%s" % (self.VBDs[i]))
            cli.execute("vdi-destroy","uuid=%s" % (self.VDIs[i]))
        
        #Detach the iSCSI LUNS from host0
        for i in range (self.MAXLUNS):
            pbd = self.host0.minimalList("pbd-list",args="sr-uuid=%s" % (self.SRs[i].uuid))
            pbduuid = re.sub( r'\[|\]|\'', "", str(pbd))
            cli.execute("pbd-unplug","uuid=%s" % (pbduuid))
            cli.execute("sr-forget", "uuid=%s" % (self.SRs[i].uuid))
        
        #Delete the VMs
        for i in range (len(self.VMs)):
            if self.host0.genParamGet('vm', self.VMs[i].getUUID(), 'power-state') != 'halted':
                cli.execute('vm-shutdown', 'vm=%s --force' % self.VMs[i].getUUID())
            cli.execute('vm-uninstall', 'vm=%s --force' % self.VMs[i].getUUID())

class TC18837(xenrt.TestCase):
    """ Test to create 8 paths to a LUN from a Host"""
    MAXPATHS = 8
    LUNSIZE = 1024
    
    def prepare(self, arglist=None):
        #Get the target host
        self.targetHost = self.getHost("RESOURCE_HOST_0")
        #Get the host 0
        self.host0 = self.getHost("RESOURCE_HOST_1")
        
    
    def run(self, arglist=None):
        
        #This will create an iSCSI VM along with a 8 multipath LUN
        lun = xenrt.ISCSIVMLun(sizeMB = self.LUNSIZE, totalSizeMB = self.LUNSIZE)
        #This will take the instance of SR for host0
        sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host0, "iscsi0")
        sr.create(lun, subtype="lvm", multipathing=True, noiqnset=True, findSCSIID=True)
        time.sleep(5)
        
        pbd = self.host0.parseListForUUID("pbd-list", "sr-uuid", sr.uuid, "host-uuid=%s" % (self.host0.getMyHostUUID()))
        scsiID = self.host0.genParamGet("pbd", pbd, "device-config", "SCSIid")
        #Check the Count of Multipaths
        mp = self.host0.getMultipathInfo()
        if len(mp[scsiID]) != self.MAXPATHS:
            raise xenrt.XRTError("Only found %u/%u paths in multipath output" % (len(mp[scsiID]),self.MAXPATHS))
        #Check the multiple active paths
        mp = self.host0.getMultipathInfo(onlyActive=True)
        if len(mp[scsiID]) != self.MAXPATHS:
            raise xenrt.XRTError("Only %u/%u paths active before test started" % (len(mp[scsiID]),self.MAXPATHS))
        
        cli = self.host0.getCLIInstance()
        #Create a vdi to the SR
        args = []
        args.append("name-label='XenRT Test VDI on %s'" % (sr.uuid))
        args.append("sr-uuid=%s" % (sr.uuid))
        args.append("virtual-size=268435456") # 256M
        args.append("type=user")
        vdi = cli.execute("vdi-create", string.join(args), strip=True)
        
        #Attach the vdi to the DOM0
        args = []
        args.append("vm-uuid=%s" % (self.host0.getMyDomain0UUID()))
        args.append("vdi-uuid=%s" % (vdi))
        args.append("device=autodetect")
        vbd = cli.execute("vbd-create", string.join(args), strip=True)
        cli.execute("vbd-plug","uuid=%s" % (vbd))
        
        #Detach the vdi
        cli.execute("vbd-unplug", "uuid=%s" % (vbd))
        cli.execute("vbd-destroy", "uuid=%s" % (vbd))
        cli.execute("vdi-destroy","uuid=%s" % (vdi))
        
        #Forget the sr
        pbd = self.host0.minimalList("pbd-list",args="sr-uuid=%s" % (sr.uuid))
        pbduuid = re.sub( r'\[|\]|\'', "", str(pbd))
        cli.execute("pbd-unplug","uuid=%s" % (pbduuid))
        cli.execute("sr-forget", "uuid=%s" % (sr.uuid))
        time.sleep(10)

class TC18847(xenrt.TestCase):
    """Testcase to verify 2 concurrent exports via VMPR"""

    #Intialize the VMPP Configuration
    def init(self, arglist=None):
        self.vmpp1 = {
            'name': 'vmpp1',
            'btype': 'snapshot',
            'bfreq': 'hourly',
            'brtnt': 5,
            'afreq': 'always_after_backup',
            'atype': 'nfs',
            'params': {'backup-schedule:min':'0'}
            }
        
    def getnfs(self):
        rshare = xenrt.ExternalNFSShare()
        rpath =  rshare.getMount()
        lshare = xenrt.rootops.MountNFS(rpath)
        lpath = lshare.getMount()
        self._nfs = { 'rshare': rshare,
                      'rpath': rpath,
                      'lshare': lshare,
                      'lpath': lpath }
        return self._nfs
        
    
    def prepare(self, arglist=None):
        
        #Get the Pool
        self.pool = self.getDefaultPool()
        h = self.pool.getHosts()
        self.master = h[1]
        self.slave = h[0]
        
        #Create the Default generic guest VM on master
        self.guest1 = self.master.createGenericLinuxGuest()
        self.guest2 = self.slave.createGenericLinuxGuest()
        self.guestlist = []
        self.guestlist.append(self.guest1)
        self.guestlist.append(self.guest2)
        self.guest1.paramSet("name-label", "VM1")
        self.guest2.paramSet("name-label", "VM2")
        
    
    def run(self, arglist=None):
        
        #Mount the nfs SR
        nfs = self.getnfs()
        self.init()
        #Create this vmpp1 with params
        vmpp = self.pool.createVMPP(self.vmpp1['name'], self.vmpp1['btype'], self.vmpp1['bfreq'])
        self.pool.setVMPPParam(vmpp, 'backup-retention-value', str(self.vmpp1['brtnt']))
        self.pool.setVMPPParam(vmpp, 'archive-target-type', self.vmpp1['atype'])
        self.pool.setVMPPParam(vmpp, 'archive-target-config:location', nfs['rpath'])
        self.pool.setVMPPParam(vmpp, 'archive-frequency', self.vmpp1['afreq'])
        params = self.vmpp1.get('params', {})
        for key,val in params.iteritems():
            self.pool.setVMPPParam(vmpp, key, val)
        
        #Disable the policy
        self.pool.setVMPPParam(vmpp, 'is-policy-enabled', "false")
        
        #Assign VM1 and VM2 to this policy
        self.guest1.paramSet("protection-policy", vmpp)
        self.guest2.paramSet("protection-policy", vmpp)
        
        #Enable the policy
        self.pool.setVMPPParam(vmpp, 'is-policy-enabled', 'true')
        vmppconf = self.pool.getVMPPConf(vmpp=vmpp)
        
        timenow = xenrt.timenow()
        timeout = timenow + 7200
        
        #check the VMPR archive is concurrent
        while xenrt.timenow() < timeout:
            #store the output of VMPRlogs in a string
            para = self.master.execdom0("tail -10 /var/log/VMPRlog")
            xenrt.TEC().logverbose("The VMPRlog contents before strip are %s" % para)
            #parse the log to filter for the pattern matching
            subpara = re.sub( r'\d|-|:|\[|\]|\.|\$', "", str(para))
            subpara = re.sub( r'%s   localhost VMPR  ' % (time.strftime("%b", (time.localtime(time.time())))), "", str(subpara))
            xenrt.TEC().logverbose("The VMPRlog contents after strip are %s" % subpara)
            #match the pattern "In single_archive \n In single_archive"
            flag = re.search("In single_archive\nIn single_archive", subpara, flags=0)
            if flag:
                xenrt.TEC().logverbose("VMs export via VMPR are concurrent")
                break
        if not flag:
            xenrt.TEC().logverbose("VMs export via VMPR are not concurrent verified via logs")
        
        #end up the running setup
        self.waitVMPPEvent(self.pool, vmpp, "%s=/=%s" % ('backup-last-run-time', vmppconf['backup-last-run-time']))
        self.waitVMPPEvent(self.pool, vmpp, "is-backup-running=false")
        self.waitVMPPEvent(self.pool, vmpp, "%s=/=%s" % ('archive-last-run-time', vmppconf['archive-last-run-time']))
        self.waitVMPPEvent(self.pool, vmpp, "is-archive-running=false")
        self.pool.setVMPPParam(vmpp, 'is-policy-enabled', 'false')
        
        #After the test of 2 hours clean the whole setup
        self.cleanup()
    
    def waitVMPPEvent(self, pool, vmpp, condition, timeout=3600):
        start = xenrt.timenow()
        deadline = start + timeout
        freq = 300
        args = []
        args.append("class=vmpp")
        args.append("uuid=%s" % vmpp)
        args.append(condition)
        cli = pool.getCLIInstance()
        # Cope with event-wait bug
        while xenrt.timenow() < deadline:
            rc = cli.execute("event-wait", args=" ".join(args), timeout=freq, level=xenrt.RC_OK, retval="code")
            if rc == 0:
                return
        raise xenrt.XRTFailure("Wait VMPP event %s timed out" % condition)
        
    def cleanup(self, arglist=None):
        
        #Clean the archives
        xenrt.rootops.sudo("rm -rf %s/*" % self._nfs['lpath'])
        cli = self.master.getCLIInstance()
        #Clean the vms
        for guest in self.guestlist:
            if self.master.genParamGet('vm', guest.getUUID(), 'power-state') != 'halted':
                cli.execute('vm-shutdown', 'vm=%s --force' % guest.getUUID())
            cli.execute('vm-uninstall', 'vm=%s --force' % guest.getUUID())
        
        #Delete the policy
        self.pool.deleteVMPP(auto=True)
        

class _VDIPerVM(xenrt.TestCase):
    """Class to test VDIs per VM (VDI and Virtual CDs)"""
    VDIs = []
    VDI = False
    MAX = False
    VCD_COUNT = 0
    SR_TYPE = "lvm"
    VDI_COUNT = 0
    MAX_SIZE = 0
    cli = None
    DISTRO = "generic-linux"
    
    def __init__(self):
        xenrt.TestCase.__init__(self)
        self.vdis = []
        self.cli = None
        
    def vbdTypeCDDestroy(self):
        cd_vbds = self.host.minimalList("vbd-list",args="vm-uuid=%s type=CD" % 
                                                       (self.guest.getUUID()))
        for vbd in cd_vbds:
            if self.host.genParamGet("vbd",vbd,"currently-attached") == "true":
                self.cli.execute("vbd-unplug", "uuid=%s" % (vbd))
                self.cli.execute("vbd-destroy", "uuid=%s" % (vbd))
    
    def prepare(self, arglist=None):
        # Get a host to install on
        self.host = self.getDefaultHost()
        # Install the VM
        xenrt.TEC().logverbose("Installing VM...")
        self.guest = self.host.createBasicGuest(distro = self.DISTRO)
        self.uninstallOnCleanup(self.guest)
        xenrt.TEC().logverbose("...VM installed successfully")
        self.cli = self.host.getCLIInstance()
        self.vbdTypeCDDestroy()
        if self.MAX == True:
            self.MAX_SIZE = int(xenrt.TEC().lookup(["VERSION_CONFIG",xenrt.TEC().lookup("PRODUCT_VERSION"),"MAX_VDI_SIZE_%s" % (self.SR_TYPE)]))
        else:
            # If size not defined than 10MB
            self.MAX_SIZE = 10
        if self.VDI == True:
            self.VDI_COUNT = int(xenrt.TEC().lookup(["VERSION_CONFIG",xenrt.TEC().lookup("PRODUCT_VERSION"),"MAX_VDIS_PER_VM"]))
        else:
            self.VDI_COUNT = 1
        
    def run(self, arglist=None):
        requiredVBDs = self.VDI_COUNT - self.VCD_COUNT
        
        # Find the SR
        srs = self.host.getSRs(type=self.SR_TYPE.lower(), local=True)
        if len(srs) == 0:
            raise xenrt.XRTError("Couldn't find any SR")
        sr = srs[0]
        
        # If we're testing a self.MAX, make sure that we have enough space on this SR
        psize = self.host.getSRParam(sr,"physical-size")
        if (self.MAX_SIZE * requiredVBDs) > psize:
            raise xenrt.XRTError("SR is not big enough (%u MB) to test"
                                         " %u required VDIs" % (psize,requiredVBDs))
        
        # Determine how many VBDs we can add to the guest
        vbddevices = self.host.genParamGet("vm",
                                      self.guest.getUUID(),
                                      "allowed-VBD-devices").split("; ")
        vbdsAvailable = len(vbddevices)
        # Fetch existing VBDs
        currentVBDs = len(self.guest.listDiskDevices())
        xenrt.TEC().logverbose("Found %d VBDs." % currentVBDs)
        
        # Create the VDIs (not specifically allocated to VBDs at this point)
        vdiCount = 0
        while vdiCount < requiredVBDs:
            try:
                args = []
                args.append("name-label=\"VDI Scalability %u\"" % (vdiCount))
                args.append("sr-uuid=%s" % (sr))
                args.append("virtual-size=%s"%(self.MAX_SIZE*1048576))
                args.append("type=user")
                uuid = self.cli.execute("vdi-create", string.join(args), strip=True)
                self.vdis.append(uuid)
                vdiCount += 1
            except xenrt.XRTFailure, e:
                xenrt.TEC().comment("Failed to create VDI %u: %s" % 
                                    (vdiCount+1,e))
                break
        
        # Plug vbds until we reach allowed VBDs
        for i in range(requiredVBDs):
            try:
                self.guest.createDisk(vdiuuid=self.vdis[i])
            except xenrt.XRTFailure, e:
                xenrt.TEC().comment("Failed to create/plug VBD for VDI %u: %s" %
                                    (i+1,e))
                break   
            
  
        # Add CD VDI
        if self.VCD_COUNT >= 1:
            self.guest.changeCD("xs-tools.iso","autodetect")
            
        # Restart VM and verify number of VDIs and size
        xenrt.TEC().logverbose("rebooting VM...")
        self.guest.reboot()
        existingVDIs = self.guest.listVBDs()
        if self.VDI_COUNT > 1:
            if len(existingVDIs) == (self.VDI_COUNT + self.VCD_COUNT):
                xenrt.TEC().logverbose("VDIs AS EXPECTED")
            else:
                raise xenrt.XRTFailure("VDIs not AS EXPECTED. Found %s VDI" %(len(existingVDIs)))
            
        # Check The Size of the VDI
        for uuid in self.vdis:
            sizeBytes = self.host.genParamGet("vdi", uuid, "virtual-size")
            if abs((int(sizeBytes))/xenrt.MEGA - self.MAX_SIZE) <= 1:
                xenrt.TEC().logverbose("VDI created successfully as expected")
            else:
                raise xenrt.XRTFailure("Vdi size Mismatch, The excepted size was %s and actual size is %s" % ((self.MAX_SIZE * 1048576), sizeBytes))
            
    def postRun(self):
        # Delete the VDIs
        for vdi in self.vdis:
            try:
                self.cli.execute("vdi-destroy uuid=%s" % (vdi))
            except:
                xenrt.TEC().warning("Exception destroying VDI %s" % (vdi))
        # Delete Virtual CD drive
        try:
            self.vbdTypeCDDestroy()
        except:
            xenrt.TEC().warning("Exception destroying Virtual CD")
        del self.vdis[:]

class TC18842(_VDIPerVM):
    """Class to test VDIs per VM (16 including CD-ROM)"""
    VDI = True
    VCD_COUNT = 1
    DISTRO = "generic-linux"

class TC18843(_VDIPerVM):
    """Class to test VDI virtual size (NFS, EXT SR)"""
    SR_TYPE = "NFS"
    MAX = True
    
class TC18844(_VDIPerVM):
    """Class to test VDI virtual size (LVM SR)"""
    SR_TYPE = "LVM"
    MAX = True
    
class TCWinVDIScalability(_VDIPerVM):
    VDI =  True
    VCD_COUNT = 1
    DISTRO = "generic-windows"
    
class VLANsPerHost(xenrt.TestCase):
    """Base class for maximum VLANS per Host test"""
    MAX = 800 
    vport = 1745 #for linux bridge no limit, CA-106021-vswitch have limited vports
    host = ""
    guest = {}
    networks = {}
    hosteth0pif = {}
    hostvlans = {}
    BRIDGE_TYPE = "LINUX"
    guests = []
    vif = {}
    
    def prepare(self, arglist=None):
        # Get a host to install on
        self.host = self.getHost("RESOURCE_HOST_0")
        
        # Change network bridge type
        if self.BRIDGE_TYPE == "LINUX":
            self.host.disablevswitch()
        else:
            self.host.enablevswitch()
        
        self.MAX = int(xenrt.TEC().lookup(["VERSION_CONFIG",xenrt.TEC().lookup("PRODUCT_VERSION"),"MAX_VLANS_PER_HOST_%s" % (self.BRIDGE_TYPE)]))
        
        # Install the VM
        xenrt.TEC().logverbose("Installing VM...")
        self.guest[0] = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest[0])
        xenrt.TEC().logverbose("...VM installed successfully")
        
        
    def run(self, arglist=None):
        vportCount = 0
        guest = self.guest[0]
        guest.shutdown()
        # Find out the eth0 PIFs on each host
        self.hosteth0pif = self.host.execdom0("xe pif-list device=eth0 host-uuid=%s params=uuid --minimal" % self.host.getMyHostUUID())
        
        # Create network
        for i in range(1, self.MAX+1):
            # Create a network
            self.networks[i] = self.host.execdom0("xe network-create name-label=vlan-net-%d" % i)
            xenrt.TEC().logverbose("self.networks[%d] = %s" % (i, self.networks[i]))
            
        
        # Create VLANs
        for i in range(1, self.MAX+1):
            self.hostvlans[i] = self.host.execdom0("xe vlan-create vlan=%d network-uuid=%s pif-uuid=%s" % (i, self.networks[i].strip('\n'), self.hosteth0pif.strip('\n')))
            xenrt.TEC().logverbose("self.hostvlans[%d] = %s" % (i, self.hostvlans[i]))

            self.host.execdom0("xe pif-plug uuid=%s" % self.hostvlans[i].strip('\n'))
            vportCount = vportCount + 1
                
        numberOfVMs = (self.vport - self.MAX)/7
        
        #create VMs
        vmCount = 0
        while vmCount < numberOfVMs:
            try:
                if vmCount > 0 and vmCount % 20 == 0:
                    # CA-19617 Perform a vm-copy every 20 clones
                    guest = self.guest[0].copyVM()
                    vportCount = vportCount + 1
                    self.uninstallOnCleanup(guest)
                g = guest.cloneVM()
                vportCount = vportCount + 1
                self.guests.append(g)
                self.uninstallOnCleanup(g)
                g.start()
                vmCount += 1
            except xenrt.XRTFailure, e:
                xenrt.TEC().comment("Failed to create VM %u: %s" % 
                                    (vmCount+1,e))
                break
        
       
        # Start adding VIFs, once all vms are full delete existing vif s and add new
        vifCount = 0
        vmCount = 0
        # Determine how many VIFs we can add to the guest
        vifdevices = self.host.genParamGet("vm",
                                      self.guest[0].getUUID(),
                                      "allowed-VIF-devices").split("; ")
        vifsToAdd = len(vifdevices)
        while vifCount < self.MAX:
            initialCount = vifCount
            for i in range(0,numberOfVMs):
                g = self.guests[i]
                try:
                    for j in range(vifsToAdd):
                        # Create a VIF on the test VM and plug it. (This checks that xapi isn't cheating in VLAN.create!)
                        self.vif[vifCount] = self.host.execdom0("xe vif-create network-uuid=%s vm-uuid=%s device=%d mac=%s" % (self.networks[vifCount+1].strip('\n'), g.getUUID(), j+1, xenrt.randomMAC()))
                        self.host.execdom0("xe vif-plug uuid=%s" % self.vif[vifCount].strip('\n'))
                        vifCount += 1
                        if vifCount == self.MAX:
                            break
                except xenrt.XRTFailure, e:
                    xenrt.TEC().comment("Failed to add VIF %u to VM %u: %s" % 
                                        (vifCount+1,vmCount,e))
                    break
                if vifCount == self.MAX:
                    break
            #destroy vifs
            for i in range(initialCount, vifCount):
                self.host.execdom0("xe vif-unplug uuid=%s" % self.vif[i].strip('\n'))
                self.host.execdom0("xe vif-destroy uuid=%s" % self.vif[i].strip('\n'))
            if vifCount == self.MAX:
                break
                
        if vifCount < self.MAX:
            raise xenrt.XRTFailure("Asked to create %u VIFs, only managed "
                                       "to create %u (on %u VMs)" % 
                                       (self.MAX,vifCount,vmCount))
                
        # Check if all VLANs are installed correctly
        for i in range(1, self.MAX+1):
            self.host.checkVLAN(i)
        
        
    def postRun(self):
        del self.guests[:]
        #Destroy vifs
        for i in range(1, self.MAX+1):
            # Destroy VLANs
            self.host.execdom0("xe pif-unplug uuid=%s" % self.hostvlans[i].strip('\n'))
            self.host.execdom0("xe vlan-destroy uuid=%s" % self.hostvlans[i].strip('\n'))
        # Destroy the network
        self.host.execdom0("xe network-destroy uuid=%s" % self.networks[i].strip('\n'))

class TC18846(VLANsPerHost):
    """Base class for maximum VLANS per Host(linux bridge) test"""
    BRIDGE_TYPE = "LINUX"

class TC18881(VLANsPerHost):
    """Base class for maximum VLANS per Host(vSwitch) test"""
    BRIDGE_TYPE = "VSWITCH"
    vport = 1024

class TC18845(xenrt.TestCase):
    """Base class for maximum Hosts per Pool test"""
    MAX = 16
    HA = False
    SR = None
    
    def prepare(self, arglist=None):
        self.MAX = int(self.getDefaultHost().lookup("MAX_HOSTS_PER_POOL"))
        
    def run(self, arglist=None):
        if not self.HA:
            if not arglist or len(arglist) < 2:
                raise xenrt.XRTError("Need at least a master and a pool name.")
            poolname = arglist[0]
            mastername = arglist[1]
            host = xenrt.TEC().registry.hostGet(mastername)
            if not host:
                raise xenrt.XRTError("Unable to find host %s in registry." %
                                     (mastername))
            self.getLogsFrom(host)

            # Create the pool object with the master host.
            xenrt.TEC().logverbose("Creating standalone pool...")
            pool = xenrt.lib.xenserver.poolFactory(host.productVersion)(host)
            xenrt.TEC().logverbose("...pool created")
            
            # Set the crashdump and suspend default SRs to be the shared storage.
            if not xenrt.TEC().lookup("POOL_NO_DEFAULT_SR", False, boolean=True):
                sruuid = pool.master.parseListForUUID("sr-list",
                                                      "name-label",
                                                       pool.master.defaultsr)
                pool.setPoolParam("default-SR", sruuid)
                pool.setPoolParam("crash-dump-SR", sruuid)
                pool.setPoolParam("suspend-image-SR", sruuid)
            else:
                # This is really to work around an annoying OEM trait...
                pool.clearPoolParam("crash-dump-SR")
                pool.clearPoolParam("suspend-image-SR")
            pool.setPoolParam("name-label", poolname)
            
            if xenrt.TEC().lookup("POOL_SHARED_DB", False, boolean=True):
                # Use shared DB on this pool          
                pool.setupSharedDB() 

            hostlist = xenrt.TEC().registry.hostList()
            hostlist.remove(mastername)

            xenrt.TEC().logverbose("Adding hosts to pool...")
            # Add other hosts to this pool.
            for slavename in hostlist:
                slave = xenrt.TEC().registry.hostGet(slavename)
                if not slave:
                    raise xenrt.XRTError("Unable to find host %s in registry." %
                                         (slavename))
                self.getLogsFrom(slave)
                pool.addHost(slave, force=True)
            pool.check()
            hostsAdded = pool.master.minimalList("host-list")
            if not len(hostsAdded) == self.MAX:
                raise xenrt.XRTFailure("Didnt find 16 hosts")
            xenrt.TEC().registry.poolPut(poolname, pool)
        
        elif self.HA:
            #Get the pool and the host
            pool = xenrt.TEC().registry.poolGet("mypool")
            host = xenrt.TEC().registry.hostGet("RESOURCE_HOST_0")
            
            #Attach an external nfs SR
            if self.SR == "nfs":
                xenrt.TEC().logverbose("Attaching the nfs SR to host 0")
                self.nfs = xenrt.ExternalNFSShare()
            srs = host.getSRs(type=self.SR)
            if len(srs) < 1:
                raise xenrt.XRTError("Couldn't find an %s SR" % (self.SR))
            sruuid = srs[0]
            
            #Enable HA on a pool
            pool.enableHA(srs=[sruuid])
            #Check HA is enabled on each host
            pool.checkHA()
            #Disable HA
            pool.disableHA()
            
    def postRun(self):
        pass
    
class TC18876(TC18845):
    """HA enabled pool of 16 Hosts"""
    HA = True
    SR = "nfs"
