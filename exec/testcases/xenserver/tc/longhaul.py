#
# XenRT: Test harness for Xen and the XenServer product family
#
# Longhaul stress standalone testcases
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy
import xenrt, xenrt.lib.xenserver

class TC7234(xenrt.TestCase):
    """Windows to Linux VM network transfer for 7 days"""
    
    DURATION = 604800

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()

        # Install the VMs
        self.winguest = self.host.createGenericWindowsGuest()
        self.uninstallOnCleanup(self.winguest)
        self.winguest.shutdown()
        self.linguest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.linguest)
        self.linguest.shutdown()

        # Create a network for the guests to communicate over.
        nwuuid = self.host.createNetwork()
        self.bridge = self.host.genParamGet("network", nwuuid, "bridge")

        # Give each guest a VIF on the shared network.
        vif = self.winguest.createVIF(bridge=self.bridge)
        self.winguest.start()
        self.winguest.updateVIFDriver()
        self.winguest.configureNetwork(vif, ip="169.254.0.1",
                                            netmask="255.255.255.0",
                                            gateway="169.254.0.2",
                                            metric="100")
        vif = self.linguest.createVIF(bridge=self.bridge)
        self.linguest.start()
        xenrt.TEC().logverbose("Using interface %s." % (vif))
        self.linguest.configureNetwork(vif, ip="169.254.0.2",
                                            netmask="255.255.255.0", 
                                            gateway="169.254.0.1")
        self.linguest.execguest("ifconfig -a")

        # Install netperf
        self.winguest.installNetperf()
        self.linguest.installNetperf()
        self.linguest.execguest("netserver &")
        try:
            self.linguest.execguest("/etc/init.d/iptables stop")
        except:
            pass

    def run(self, arglist):
        # Start netperf transfers in each direction
        wintolin = self.winguest.xmlrpcStart("c:\\netperf.exe -H 169.254.0.2 "
                                             "-t TCP_STREAM -l %u -v 0 "
                                             "-P 0" % (self.DURATION))
        lintowin = self.winguest.xmlrpcStart("c:\\netperf.exe -H 169.254.0.2 "
                                             "-t TCP_MAERTS -l %u -v 0 "
                                             "-P 0" % (self.DURATION))
        started = xenrt.timenow()
        shouldend = started + self.DURATION - 300
        deadline = started + self.DURATION + 600

        # Check for VM health, continued operation and completion
        wintolindata = None
        lintowindata = None
        while True:
            # Check if tests still running
            if wintolin and self.winguest.xmlrpcPoll(wintolin):
                wintolindata = self.winguest.xmlrpcLog(wintolin)
                xenrt.TEC().logverbose("Windows to Linux output:")
                xenrt.TEC().logverbose(wintolindata)
                if xenrt.timenow() < shouldend:
                    raise xenrt.XRTFailure("Windows to Linux transfer ended "
                                           "early")
                rc = self.winguest.xmlrpcReturnCode(wintolin)
                if rc != 0:
                    raise xenrt.XRTFailure("Windows to Linux transfer returned"
                                           " %d" % (rc))
                wintolin = None
            if lintowin and self.winguest.xmlrpcPoll(lintowin):
                lintowindata = self.winguest.xmlrpcLog(lintowin)
                xenrt.TEC().logverbose("Linux to Windows output:")
                xenrt.TEC().logverbose(lintowindata)
                if xenrt.timenow() < shouldend:
                    raise xenrt.XRTFailure("Linux to Windows transfer ended "
                                           "early")
                rc = self.winguest.xmlrpcReturnCode(lintowin)
                if rc != 0:
                    raise xenrt.XRTFailure("Linux to Windows transfer returned"
                                           " %d" % (rc))
                lintowin = None
            if not wintolin and not lintowin:
                break

            # Check for timeout
            if xenrt.timenow() > deadline:
                raise xenrt.XRTFailure("Transfers still running after deadline")
            
            # Check VMs are OK
            xenrt.TEC().logverbose("Perform routine health checks")
            self.winguest.checkHealth()
            self.linguest.checkHealth()

            time.sleep(300)

class TC7234Test(TC7234):
    DURATION = 600

class TC7353(TC7234):
    """Windows to Linux VM network transfer for 14 days"""
    DURATION = 1209600

class LongHaulTestVmOperations(xenrt.TestCase):    

    def prepare(self, arglist):
        
        self.host = self.getDefaultHost() 
        self.defaultSR = self.host.lookupDefaultSR()
        self.guest0 = self.getGuest("VM")
        self.guest1 = self.getGuest("VM_Operations")
        
        assert(len(arglist) >= 1)        
        if arglist[0].startswith('duration'):
            self.duration = int(arglist[0].split('=')[1])
            xenrt.TEC().logverbose("Duration Specified %s seconds" %(self.duration))
        else:
            raise xenrt.XRTError("Must specify the duration for the testcase execution")
        
        self.vmoperationlist = ["vmopShutdownStart","vmopReboot" ,"vmopSuspendResume" ,
                                "vmopSnapshotRevert" ,"vmopCheckpointRevert","vmopClone",
                                "vmopCopy","vmopLocalHostLiveMigrate","vmopLocalHostNonLiveMigrate"]
        
        self.failures = []
    
    def run(self,arglist=None):
        self.startTime=xenrt.timenow()
        xenrt.TEC().logverbose("Initiation time %s" %(self.startTime))
        xenrt.TEC().logverbose("Start Time = %s"%(self.host.execdom0("date")))
        self.endTime = self.duration + self.startTime
        
        while self.endTime > xenrt.timenow() :
            vmop = random.randint(0,len(self.vmoperationlist)-1)
            if self.runSubcase(self.vmoperationlist[vmop], (), self.guest1.distro +"_" + self.guest1.getName() ,self.vmoperationlist[vmop]) != xenrt.RESULT_PASS:
                self.failures.append("Vm Operation %s failed " %(self.vmoperationlist[vmop]))
                self.pauseandResume()
            
                
        if len(self.failures) > 0:
            raise xenrt.XRTFailure("Multiple opearations  failed: %s" % self.failures)
        else :
            xenrt.TEC().logverbose("All VMOperations passed.") 
            
        
    def vmopShutdownStart(self) :
        self.guest1.shutdown()
        self.guest1.start()
            
    
    def vmopReboot(self):
        self.guest1.reboot()
           
    def vmopSuspendResume(self):
        self.guest1.suspend()
        self.guest1.resume()
    
    def vmopSnapshotRevert(self):
        self.guest1.shutdown()
        self.snapshot= self.guest1.snapshot("snapshot_revert")
        self.guest1.start()
        self.guest1.shutdown()
        self.guest1.revert(self.snapshot)
        self.guest1.removeSnapshot(self.snapshot)
        self.guest1.start()
    
    def vmopCheckpointRevert(self):
        self.checkpoint= self.guest1.checkpoint("checkpoint1")
        self.guest1.waitForAgent(180)
        self.guest1.revert(self.checkpoint)
        self.guest1.lifecycleOperation("vm-resume")
        self.guest1.removeSnapshot(self.checkpoint)

    def vmopClone(self):
        self.guest1.shutdown()
        self.clone_guest = self.guest1.cloneVM(self.guest1.getName() + "_clone")
        self.uninstallOnCleanup(self.clone_guest)
        self.guest1.start()
        self.clone_guest.start()
        self.clone_guest.reboot()
        self.clone_guest.shutdown()
        self.clone_guest.uninstall()
            
    def vmopCopy(self) :
        self.guest1.shutdown()
        self.copy_guest = self.guest1.copyVM(name= self.guest1.getName() + "_copy", sruuid=self.defaultSR)
        self.uninstallOnCleanup(self.copy_guest)
        self.guest1.start()
        self.copy_guest.start()
        self.copy_guest.reboot()
        self.copy_guest.shutdown()
        self.copy_guest.uninstall()
    
    def vmopLocalHostLiveMigrate(self) :
        self.guest1.migrateVM(host=self.host,live="true")
            
    def vmopLocalHostNonLiveMigrate(self) :
        self.guest1.migrateVM(host=self.host)
            
    def pauseandResume(self):
        now =  xenrt.timenow()
        try:
            xenrt.TEC().logverbose("Stoppage Time = %s"%(self.host.execdom0("date")))
        except Exception, ex:
            xenrt.TEC().logverbose("Error getting stoppage time from host " + str(ex))

        self.pause("Execution PAUSED to debug the issue ."
                   "Before you RESUME the Testcase execution ,please ENSURE that the VM is in running state " , indefinite="True")
        resume = xenrt.timenow()
        elapsed = resume - now
        self.endTime = self.endTime + elapsed #update the execution time by the time taken to debug the issue

        try:
            xenrt.TEC().logverbose("Resuming the VM operations %s"%(self.host.execdom0("date")))
        except Exception, ex:
            xenrt.TEC().logverbose("Error getting resume time from host " + str(ex))

