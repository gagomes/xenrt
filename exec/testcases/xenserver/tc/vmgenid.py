#
# XenRT: Custom test case (Python) file.
#
# To run this test case you will need to:
#
# 1. Create a sequence file.
# 2. Reference this class in the sequence file.
# 3. Submit a job using the sequence.

import socket, re, string, time, traceback, sys, random, copy, math
import xenrt, xenrt.lib.xenserver
from xenrt.lazylog import log

class  _VmGen(xenrt.TestCase):

    DISTRO = None

    def prepare(self, arglist=None):
        
        self.pool = self.getDefaultPool()
        
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host2 = self.getHost("RESOURCE_HOST_2")
        
        
        self.poolsrUUIDs = self.pool.master.getSRs() 
        
        self.SharedUUID=[]
        for uuids in self.poolsrUUIDs:
            if self.pool.master.getSRParam(uuids,"shared") ==  "true":
                if self.pool.master.getSRParam(uuids,"type") != "iso":
                    self.SharedUUID.append(uuids)
                    break        
        xenrt.TEC().logverbose("UUID for the shared non-iso SR %s" %(self.SharedUUID[0]))
        
        self.defaultSR = self.SharedUUID[0]
        self.vmName = self.DISTRO
        
        if "x86" in self.DISTRO :
            self.vmgenexe = "vmgenid32.exe"
        elif "x64" in self.DISTRO :
            self.vmgenexe = "vmgenid64.exe"
        else :
            raise xenrt.XRTFailure("Cant find the appropriate vmgen.exe file for distro %s" % self.DISTRO)
        
            
        self.failures = []

    
    def run(self, arglist):         
       
                   
        self.slaves = self.pool.getSlaves()
        
        #self.guest = self.host0.createGuestObject("win8-x86")         
        
        if self.runSubcase("installVM", (), self.DISTRO ,"Installing OS") != xenrt.RESULT_PASS:
           self.failures.append("Installing OS Failed ")
        
        if self.runSubcase("copyVM", (), self.DISTRO, "Copying VM") != xenrt.RESULT_PASS:        
            self.failures.append("Copying of VM failed ")
            
        if self.runSubcase("cloneVM", (), self.DISTRO, "Cloning VM") != xenrt.RESULT_PASS:        
            self.failures.append("Cloning of VM failed ")
            
        if self.runSubcase("snapshotVM", (), self.DISTRO, "VM Creation from Snapshot") != xenrt.RESULT_PASS:        
            self.failures.append("Snapshotting  of VM failed ")
            
        if self.runSubcase("checkpointVM", (), self.DISTRO, "VM Creation from Checkpoint") != xenrt.RESULT_PASS:        
            self.failures.append("Checkpoint of VM failed ")
            
        if self.runSubcase("snapshotRollback", (), self.DISTRO, "Reverting back to snapshot") != xenrt.RESULT_PASS:        
            self.failures.append("Reverting to Snapshot of VM failed ")
            
        if self.runSubcase("checkpointRollback", (), self.DISTRO, "Reverting back to Checkpoint") != xenrt.RESULT_PASS:        
            self.failures.append("Reverting to Checkpoint of VM failed ")
            
        if self.runSubcase("migrate", (), self.DISTRO, "LiveMigration of VM") != xenrt.RESULT_PASS:
            self.failures.append("LiveMigration of VM failed ")
            
        if self.runSubcase("storageXenMotion", (), self.DISTRO, "StorageXenMotion of VM") != xenrt.RESULT_PASS:        
            self.failures.append("Storage Xen Motion of VM failed ")
        
        
        if len(self.failures) > 0:
            raise xenrt.XRTFailure("Multiple subcases failed: %s" % self.failures)
        else :
            xenrt.TEC().logverbose("All subcases passed.")
        
    def installVM(self):
        # Install the OS       
       
        self.guest = self.host0.createBasicGuest(name=self.vmName, distro = self.DISTRO , sr =self.SharedUUID[0])
        self.getLogsFrom(self.guest)
        self.guest.installPowerShell()
        self.guest.enablePowerShellUnrestricted()
        self.uninstallOnCleanup(self.guest)
        self.guest.reboot()
        preVmGenId = self.guest.retreiveVmGenId()
        self.vmlifecycle(self.guest)
        newVmGenId = self.guest.retreiveVmGenId()
        if preVmGenId == newVmGenId :
            xenrt.TEC().logverbose("VmGenID remains same after performing VM Lifecycle Operations as Expected")                     
        else:
            raise xenrt.XRTFailure("VM Gen Verification failed while Installing OS" )           
            
        
        
    def copyVM(self):
        preVmGenId = self.guest.retreiveVmGenId()
        
        if self.guest.getState() == "UP":
            self.guest.shutdown()        
        self.copy_guest = self.guest.copyVM(name= self.vmName + "_copy", sruuid=self.defaultSR)
        self.uninstallOnCleanup(self.copy_guest)
        
        self.vmlifecycle(self.guest)
        newVmGenId = self.guest.retreiveVmGenId()
        if preVmGenId == newVmGenId :
            xenrt.TEC().logverbose("VmGenID remains same  after copying VM operation is done on original VM as expected")        
        else:
            raise xenrt.XRTFailure("VM Gen Verification failed after Copy VM operation is performed")
       
        self.vmlifecycle(self.copy_guest)
        newVmGenId = self.copy_guest.retreiveVmGenId()
        if preVmGenId != newVmGenId :
            xenrt.TEC().logverbose("VmGenID of a copied VM is different from Base VM as expected")
        else :
            raise xenrt.XRTFailure("VM Gen Verification failed for VM Copy")
        
        
        
    def cloneVM(self):
        preVmGenId = self.guest.retreiveVmGenId()
        
        if self.guest.getState() == "UP":
            self.guest.shutdown()            
        self.clone_guest = self.guest.cloneVM(self.vmName + "_clone")
        self.uninstallOnCleanup(self.clone_guest)
        
        self.vmlifecycle(self.guest)
        newVmGenId = self.guest.retreiveVmGenId()        
        if preVmGenId == newVmGenId :
            xenrt.TEC().logverbose("VmGenID remains same  after cloning VM operation is done on original VM as expected")
        else:            
            raise xenrt.XRTFailure("VM Gen Verification failed after Clone VM operation is performed")
            
        self.vmlifecycle(self.clone_guest)
        newVmGenId = self.clone_guest.retreiveVmGenId()
        if preVmGenId != newVmGenId :
            xenrt.TEC().logverbose("VmGenID of a cloned VM is differnet from Base VM as expected")
        else :            
            raise xenrt.XRTFailure("VM Gen Verification failed for VM Clone")
        
           
    
    def snapshotVM(self):
    
        preVmGenId = self.guest.retreiveVmGenId()
        
        vifUUID = self.guest.getVIFUUID("eth0")
        mac = self.host0.genParamGet("vif", vifUUID, "MAC")
        netuuid = self.host0.genParamGet("vif", vifUUID, "network-uuid")
        
        self.guest.shutdown()
        self.snapshot= self.guest.snapshot("snapshot")
        self.guest.start()
        self.guest.waitForAgent(180)
        self.guest.reboot()
        newVmGenId = self.guest.retreiveVmGenId()        
        if preVmGenId == newVmGenId :
            xenrt.TEC().logverbose("VmGenID remains same after taking snapshot of original VM as expected") 
        else:            
            raise xenrt.XRTFailure("VM Gen Verification failed after Snapshot operation is performed")    
            
        cli = self.host0.getCLIInstance()
        temp_uuid=cli.execute('snapshot-clone','uuid=%s new-name-label=%s' % (self.snapshot,self.vmName +"_snapshot_template")).strip()
        snapshotVM = self.host0.guestFactory()( self.vmName + "_snapshot", template=self.vmName +"_snapshot_template", host=self.host0)
        snapshotVM.createGuestFromTemplate(snapshotVM.template ,self.defaultSR )
        self.uninstallOnCleanup(snapshotVM)
        snapshotVM.removeVIF("eth0")
        snapshotVM.createVIF("eth0", bridge=netuuid, mac=xenrt.randomMAC())
        snapshotVM.enlightenedDrivers = True
        snapshotVM.windows = True
        snapshotVM.tailored = True
        snapshotVM.start()
        
        self.vmlifecycle(snapshotVM)
        newVmGenId = snapshotVM.retreiveVmGenId()
        if preVmGenId != newVmGenId :
            xenrt.TEC().logverbose("VmGenID of a snapshot VM is different from Base VM as expected ")
        else :            
            raise xenrt.XRTFailure("VM Gen Verification failed for VM Snapshot")            
                
        self.removeTemplateOnCleanup(self.host0, temp_uuid)
        self.guest.removeSnapshot(self.snapshot)
        
    def checkpointVM(self):
        preVmGenId = self.guest.retreiveVmGenId()
        
        vifUUID = self.guest.getVIFUUID("eth0")
        mac = self.host0.genParamGet("vif", vifUUID, "MAC")
        netuuid = self.host0.genParamGet("vif", vifUUID, "network-uuid")
        
        
        self.checkpoint = self.guest.checkpoint("checkpoint")
        self.guest.reboot()
        
        newVmGenId = self.guest.retreiveVmGenId()
        if preVmGenId == newVmGenId :
            xenrt.TEC().logverbose("VmGenID remains same after taking checkpoint of original VM as expected")
        else:            
            raise xenrt.XRTFailure("VM Gen Verification failed after Checkpoint operation is performed")     
            
        cli = self.host0.getCLIInstance()
        temp_uuid=cli.execute('snapshot-clone','uuid=%s new-name-label=%s' % (self.checkpoint,self.vmName +"_checkpoint_template")).strip()
        checkpointVM = self.host0.guestFactory()(self.vmName + "_checkpointVM", template=self.vmName +"_checkpoint_template", host=self.host0)
        checkpointVM.createGuestFromTemplate(checkpointVM.template ,self.defaultSR )
        self.uninstallOnCleanup(checkpointVM)
        checkpointVM.removeVIF("eth0")
        checkpointVM.createVIF("eth0", bridge=netuuid, mac=xenrt.randomMAC())
        checkpointVM.enlightenedDrivers = True
        checkpointVM.windows = True
        checkpointVM.tailored = True
        checkpointVM.start()
        
        self.vmlifecycle(checkpointVM)
        newVmGenId = checkpointVM.retreiveVmGenId()
        if preVmGenId != newVmGenId :
            xenrt.TEC().logverbose("VmGenID of a checkpoint VM is different from Base VM as expected ")
        else :            
            raise xenrt.XRTFailure("VM Gen Verification failed for VM Checkpoint")     
        self.guest.removeSnapshot(self.checkpoint)
        
        self.removeTemplateOnCleanup(self.host0, temp_uuid)
               
   
        
    def snapshotRollback(self ):
        if self.guest.getState() != "UP":
            self.guest.start()
        preVmGenId = self.guest.retreiveVmGenId()
        self.guest.shutdown()
        self.snapshot= self.guest.snapshot("snapshot_revert")
        self.guest.start()
        self.guest.waitForAgent(180)
        self.guest.shutdown()
        self.guest.revert(self.snapshot)
        self.vmlifecycle(self.guest)
        
        newVmGenId = self.guest.retreiveVmGenId()
        if preVmGenId != newVmGenId :
            xenrt.TEC().logverbose("VmGenID is different if we revert back to the snapshot") 
        else :
            raise xenrt.XRTFailure("VM Gen Verification failed for Vm reverted to its snapshot")
        self.guest.removeSnapshot(self.snapshot)
        
        
    
    def checkpointRollback(self):
        if self.guest.getState() != "UP":
            self.guest.start()
        preVmGenId = self.guest.retreiveVmGenId()
        self.checkpoint= self.guest.checkpoint("checkpoint1")
        self.guest.waitForAgent(180)
        self.guest.revert(self.checkpoint)        
        self.guest.lifecycleOperation("vm-resume")
        
        newVmGenId = self.guest.retreiveVmGenId()
        if preVmGenId != newVmGenId :
            xenrt.TEC().logverbose("VmGenID is different if we revert back to the checkpoint")
        else :            
            raise xenrt.XRTFailure("VM Gen Verification failed for Vm reverted to its checkpoint") 
        
        preVmGenId = newVmGenId
        self.vmlifecycle(self.guest)
        
        newVmGenId = self.guest.retreiveVmGenId()
        if preVmGenId == newVmGenId :
            xenrt.TEC().logverbose("VmGenID is same after reboot after revert back to checkpoint")
        else :            
            raise xenrt.XRTFailure("VM Gen Verification failed for reboot after VM reverted to its checkpoint") 
        self.guest.removeSnapshot(self.checkpoint)
        
        
        
    def migrate(self): 
        preVmGenId = self.guest.retreiveVmGenId()
        self.guest.migrateVM(self.host1 , live='true')
        time.sleep(10)
        self.vmlifecycle(self.guest)        
        self.guest.check()
        self.guest.host = self.host1
        newVmGenId = self.guest.retreiveVmGenId()
        if preVmGenId == newVmGenId :
            xenrt.TEC().logverbose("VmGenID doesnt change in case of live migrating the VM") 
        else :            
            raise xenrt.XRTFailure("VM Gen Verification failed for Live Migrated VM")    
        
        
    def storageXenMotion(self):
        
        #Detroy all the snapshots as SXM will fail with Vm having more than 1 snapshot
        snapshotlist=self.host1.minimalList("snapshot-list")
        cli = self.host0.getCLIInstance()
        for s in snapshotlist :                
                cli.execute("snapshot-destroy","uuid=%s" %(s))
                
        self.vmlifecycle(self.guest)
        preVmGenId = self.guest.retreiveVmGenId()
       
        vbd = self.host1.minimalList("vbd-list", args="vm-uuid=%s type=Disk" % self.guest.getUUID())        
        vdi = self. host1.minimalList("vdi-list", args="vbd-uuids=%s " % vbd[0])        
        
        dest_sr=self.host2.getSRs(type="lvm")[0]
        
        #Migrate Parameters
        params={'dest_host': self.host2 ,'VDI_SR_map': {vdi[0]: dest_sr}}
        
        #Call Migrate Api
        try:
            obs = self.guest.sxmVMMigrate(params,pauseAfterMigrate = False)            
        except Exception as e:
            xenrt.TEC().logverbose("INFO_SXM: Exception occurred while trying to call migrate api %s for VM %s" % (str(e),self.guest.getUUID()))            
            raise xenrt.XRTFailure("Exception occurred while trying to initiate migration")
            
        obs.waitToFinish()
        
        xenrt.TEC().logverbose(obs.getSXMResult())
        results = obs.getSXMResult()
        if results['taskResult'] != 'success' :
            raise xenrt.XRTFailure("VM Storage Migration Failed")
        else :
            self.guest.checkHealth()
            
        time.sleep(10)
        self.vmlifecycle(self.guest)
        self.guest.check()
        self.guest.host = self.host2
        newVmGenId = self.guest.retreiveVmGenId()
        if preVmGenId == newVmGenId :
            xenrt.TEC().logverbose("VmGenID doesnt change in case of live storage migration of the VM") 
        else :            
            raise xenrt.XRTFailure("VM Gen Verification failed after Storage Migration of VM")
        
    def vmlifecycle(self , guest):
        if guest.getState() != "UP":
            guest.start()
        guest.shutdown()
        guest.start()
        guest.reboot()
        guest.suspend()
        guest.resume()
        guest.pause()
        guest.lifecycleOperation("vm-unpause")
        guest.check() 

class TC19041(_VmGen):
    DISTRO = "win8-x86" 

class TC19042(_VmGen):
    DISTRO = "win8-x64"

class TC26425(_VmGen):
    DISTRO = "win10-x86" 

class TC26426(_VmGen):
    DISTRO = "win10-x64"

class TC19044(_VmGen):
    DISTRO = "ws12-x64"

class TC19045(_VmGen):
    DISTRO = "ws12core-x64"

class TC20633(_VmGen):
    DISTRO = "win81-x86"

class TC20634(_VmGen):
    DISTRO = "win81-x64"
    
class TC20635(_VmGen):
    DISTRO = "ws12r2-x64"

class TC20636(_VmGen):
    DISTRO = "ws12r2core-x64"
