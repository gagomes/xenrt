#
# XenRT: Test harness for Xen and the XenServer product family
#
# Testcases for scalability
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and conditions
# as licensed by Citrix Systems, Inc. All other rights reserved.
#

import string, time, re, copy, threading, sys, traceback, urllib, random
import xml.dom.minidom
import xenrt
from xenrt.lazylog import step, comment, log, warning

class _Scalability(xenrt.TestCase):
    """Base class for all the VM/VBD/VIF Scalability tests"""

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.host = None
        self.guests = []
        self.lock = threading.Lock()

    def run(self,arglist):

        host = None

        # Parse the arglist
        if arglist and len(arglist) > 0:
            for arg in arglist:
                l = string.split(arg, "=", 1)
                if l[0] == "host":
                    host = xenrt.TEC().registry.hostGet(l[1])
                else:
                    self.parseArgument(l[0],l[1])

        if not host:
            host = self.getDefaultHost()
        self.host = host
        self.hosts = [self.host]

        # Hand off to the actual run method
        return self.runTC(host)

    def parseArgument(self,param,value):
        """Parse an argument to the testcase"""
        pass

    def runTC(self,host):
        """Actual run method of testcase"""
        pass

    def lifecycleOperations(self):
        """Perform lifecycle operations on guests"""
        for guest in self.guests:
            guest.reboot()
            guest.waitForAgent(180)
            guest.shutdown()
            guest.start()
            guest.waitForAgent(180)
            guest.suspend()
            guest.resume()



class _VMScalability(_Scalability):

    VCPUCOUNT= None #default values
    VIFCOUNT=1 #default values
    VIFS = False # No VIFs for individual VMs
    VBDCOUNT=1 #default values
    MAX = 0
    TRYMAX = False # TRY to load the MAXimum possible VMs, by disabling some features
    LOOPS = 0
    DISTRO = "debian70"
    ARCH = "x86-64"
    MEMORY=384
    CHECKHEALTH = False
    CHECKREACHABLE = False
    HATEST = False  #HA protected VMs
    DOM0MEM = False #Dom 0 Memory in MB
    NET_BRIDGE=False # Use Linux Bridge for Network Backend
    FLOW_EVT_THRESHOLD = False # set flow-eviction-threshold value (e.g.: 8192)
    POSTRUN = "forcecleanup" #CA-126090      nocleanup|cleanup|forcecleanup
    POOLED = False

    #Pin additional vCPUs for dom0. Will use this if TRYMAX is set to True
    DOM0CPUS = False
    tunevcpus = 8

    pri_bridge = False
    pool = None
    vmtemplate = "Golden-VM-Template"

    def parseArgument(self,param,value):
        """Parse an argument to the testcase"""
        if param=="vcpus":
            self.VCPUCOUNT=int(value)
        elif param=="vifs":
            self.VIFCOUNT=int(value)
            self.VIFS=True #if vif argument is provided we cannot remove vifs from VMs, thus VIFS=True
        elif param=="vbds":
            self.VBDCOUNT=int(value)
        elif param=="distro":
            self.DISTRO=value
        elif param=="arch":
            self.ARCH=value
        elif param=="memory": # memory will be accepted as argument, otherwise 256 will be used
            self.MEMORY=int(value)
        elif param=="dom0mem":
            self.DOM0MEM=int(value)
        elif param=="max":  #No.of VMs
            self.MAX=int(value)
        elif param=="postrun": #Post Run Cleanup
            self.POSTRUN=value


    #Base class for cloning VMs with worker threads
    def prepare(self, arglist=None):
        # Find the gold VMs - we'll clone from these
        # e.g. if we have 2 golden images, we'll clone half from gold0 and half from gold1
        self.gold = []
        self.masterGuest = {}
        self.pool = self.getDefaultPool()
        self.currentNbrOfGuests = 0
        if self.POOLED and not self.pool:
            raise xenrt.XRTError("Expected Pool orchestration missing")

    def installVM(self, host):
        if self.DISTRO == "LINUX":
            distro = xenrt.TEC().lookup("LINUX_DISTRO", "rhel46")
        else:
            distro = self.DISTRO
        viflist=[]
        #creating a list of vifs
        self.pri_bridge = host.getPrimaryBridge()
        for i in range(self.VIFCOUNT):
          viflist.append((str(i),self.pri_bridge,xenrt.randomMAC(),None))
        disklist=[]
        #Incase only one VBD is required a root disk of default size will be created, disklist will be empty
        #Only if additional VBDs are required disklist will get populated with userdevice no. starting from 1
        #the size of the additional VBDs are configured to be 1G, that can be made flexible
        for i in range(self.VBDCOUNT-1):
          disklist.append((str(i+1),1,False))

        #Workaround to avoid a potential script failure in case of lower memory
        mem = 256
        if self.MEMORY > 256:
            mem = self.MEMORY

        g0 = xenrt.lib.xenserver.guest.createVM(host,
                                                  self.vmtemplate+"-"+str(host.getName()),
                                                  distro,
                                                  arch=self.ARCH,
                                                  memory=mem,
                                                  vifs=viflist,
                                                  disks=disklist,
                                                  vcpus=self.VCPUCOUNT)
        if g0.windows:
            g0.installDrivers()
        g0.shutdown()
        #If memory set
        if self.MEMORY < mem:
            g0.memset(self.MEMORY)
        if self.TRYMAX:
            # post-install post-shutdown
            xenrt.TEC().logverbose("Disabling specific guest features")
            host.execdom0("xe vm-param-set uuid=%s platform:nousb=true" % g0.uuid)
            host.execdom0("xe vm-param-set uuid=%s platform:parallel=none" % g0.uuid)
            host.execdom0("xe vm-param-set uuid=%s other-config:hvm_serial=none" % g0.uuid)
            vbds = g0.listVBDUUIDs("CD")
            for vbd in vbds:
                host.execdom0("xe vbd-destroy uuid=%s" % vbd)

        #Some SKUs only allow Windows to run on two sockets. So, we should present multiple vCPUs as a single socket.
        if self.VCPUCOUNT > 2 and self.DISTRO == "winxpsp3":
            g0.paramSet("platform:cores-per-socket", self.VCPUCOUNT/2)

        return g0

    def runTC(self,host,tailor_guest=None):
        if self.MAX == True:
            self.max = int(xenrt.TEC().lookup("OVERRIDE_MAX_CONC_VMS", host.lookup("MAX_CONCURRENT_VMS")))
        else:
            self.max = self.MAX

        if self.POOLED and self.pool:
            self.host = self.pool.master
            host = self.host
            self.hosts = self.pool.getHosts()

        if self.DOM0CPUS or self.DOM0MEM or self.NET_BRIDGE:
            step("Optimizing hosts for scalability testing")
            for host in self.hosts:
                self.optimizeDom0(host)

        step("Getting existing guest information")
        self.optimizeExistingGuests(host)

        if self.HATEST:
            step("Enabling HA")
            self.doHATest()

        step("Creating a guest for each host on shared storage")
        xenrt.pfarm ([xenrt.PTask(self.createVmMasterCopy, host) for host in self.hosts])

        step("Cloning guests on each host in pool")
        self.createVmClones(tailor_guest= tailor_guest)

        if self.CHECKREACHABLE or self.CHECKHEALTH:
            step("Checking cloned guests")
            self.checkGuests()

        if self.max > 0:
            if self.nbrOfGuests < self.max:
                raise xenrt.XRTFailure("Asked to start %u VMs, only managed to "
                                       "start %u" % (self.max,self.nbrOfGuests))
        else:
            xenrt.TEC().value("maximumNumberVMs",self.nbrOfGuests)

        if self.LOOPS and self.LOOPS>0:
            step("Looping test")
            self.loopingTest()

    def optimizeDom0(self, host):
        if self.DOM0CPUS:
            #To increase I/O throughput for guest VMs, have dom0 with some exclusively-pinned vcpus
            try:
                xenrt.TEC().logverbose("Set Dom0 with %s exclusively-pinned vcpus" % self.tunevcpus)
                host.execdom0("%s set %s xpin" % (host._findXenBinary("host-cpu-tune"), self.tunevcpus),timeout=3600)
            except xenrt.XRTFailure, e:
                raise xenrt.XRTFailure("Failed to xpin Dom0 : %s" % (e))

        if self.DOM0MEM:
            #editing the extlinux.conf file to change the dom0 mem values
            xenrt.TEC().logverbose("Update the DOM0 Memory")
            host.execdom0("sed -i 's/dom0_mem=[0-9]*M/dom0_mem=%sM/g' /boot/extlinux.conf" %str(self.DOM0MEM))
            host.execdom0("sed -i 's/dom0_mem=\([0-9]*\)M,max:[0-9]*M/dom0_mem=\\1M,max:%sM/g' /boot/extlinux.conf" %str(self.DOM0MEM))

        if self.NET_BRIDGE:
            #Linux bridge on host side as Network backend
            host.execdom0("xe-switch-network-backend bridge")

        if self.DOM0CPUS or self.DOM0MEM or self.NET_BRIDGE:
            #rebooting the host
            host.reboot(timeout=7200)

    def optimizeExistingGuests(self, host):
        for gname in host.listGuests():
            if self.vmtemplate not in gname and host.getGuest(gname):
                g = host.getGuest(gname)
                self.guests.append(g)

        if self.TRYMAX:
            for g in self.guests:
                if g.getState() != "DOWN":
                    g.shutdown()
                host.execdom0("xe vm-param-set uuid=%s platform:nousb=true" % g.uuid)
                host.execdom0("xe vm-param-set uuid=%s platform:parallel=none" % g.uuid)
                host.execdom0("xe vm-param-set uuid=%s other-config:hvm_serial=none" % g.uuid)
                vbds = g.listVBDUUIDs("CD")
                for vbd in vbds:
                    host.execdom0("xe vbd-destroy uuid=%s" % vbd)

    def doHATest(self):
        try:
            if not self.POOLED:
                self.pool = xenrt.lib.xenserver.poolFactory(self.host.productVersion)(self.host)
            # Enable HA on the pool
            self.pool.enableHA()

            # Set nTol to 1
            self.pool.setPoolParam("ha-host-failures-to-tolerate", len(self.hosts))
        except xenrt.XRTFailure, e:
            raise xenrt.XRTFailure("Failed to create HA enabled Pool.. %s" % (e))

    def createVmMasterCopy(self, host):
        #VM Master Copy
        guest = None
        if self.max == 0 or len(self.guests) < self.max:
            if self.getGuest(self.vmtemplate+"-"+str(host.getName())):
                guest = self.getGuest(self.vmtemplate+"-"+str(host.getName()))
                if guest.getState() != "DOWN":
                    guest.shutdown(force=True)
                if self.TRYMAX:
                    host.execdom0("xe vm-param-set uuid=%s platform:nousb=true" % guest.uuid)
                    host.execdom0("xe vm-param-set uuid=%s platform:parallel=none" % guest.uuid)
                    host.execdom0("xe vm-param-set uuid=%s other-config:hvm_serial=none" % guest.uuid)
                    vbds = guest.listVBDUUIDs("CD")
                    for vbd in vbds:
                        host.execdom0("xe vbd-destroy uuid=%s" % vbd)


            # Create the initial VM
            else:
                guest = self.installVM(host)
                guest.preCloneTailor()
                guest.shutdown()
            if self.POSTRUN != "nocleanup":
                self.uninstallOnCleanup(guest)

        if self.pri_bridge == False:
            self.pri_bridge = host.getPrimaryBridge()
        if self.FLOW_EVT_THRESHOLD and xenrt.TEC().lookup("NETWORK_BACKEND", None) != "bridge":
            host.execdom0("ovs-vsctl set bridge %s other-config:flow-eviction-threshold=%u" % (self.pri_bridge,self.FLOW_EVT_THRESHOLD))

        if not self.VIFS and not self.CHECKREACHABLE:
            # Remove the VIF
            try:
                guest.removeVIF("0")
            except:
                pass

        self.masterGuest[host] = guest

    def createVmCloneThread(self, host, tailor_guest=None):
        while self.nbrOfFails <= self.nbrOfFailThresholds:
            if (self.max != 0 and self.currentNbrOfGuests >= self.max):
                return

            with self.lock:
                self.currentNbrOfGuests = self.currentNbrOfGuests + 1
                guestNbr = self.currentNbrOfGuests
                guestOnHostNbr = len(host.listGuests(running=True)) + 1

            g = self.masterGuest[host].cloneVM(name=str(guestNbr)+"_" + self.DISTRO )
            self.guests.append(g)
            host.addGuest(g)
            if tailor_guest:
                tailor_guest(g)
            if self.max == 0:
                try:
                    g.start(specifyOn = False)
                    if self.HATEST:
                        g.setHAPriority(order=2, protect=True, restart=False)
                        if not g.paramGet("ha-restart-priority") == "best-effort":
                            raise xenrt.XRTFailure("Guest %s not marked as protected after setting priority" % (g.getName()))
                except xenrt.XRTFailure, e:
                    xenrt.TEC().warning("Failed to start VM %u: %s" % (guestNbr, e))
                    self.nbrOfFails= self.nbrOfFails+1
                    self.failedGuests.append(g)
                    try:
                        g.uninstall()
                        self.guests.remove(g)
                        host.removeGuest(g)
                    except:
                        pass
                    #adding sleep to prevent this thread from creating more failures immediately.
                    xenrt.sleep(120)

    def createVmClones(self, tailor_guest=None):
        self.currentNbrOfGuests = len(self.guests)
        self.nbrOfFailThresholds = len(self.hosts)
        self.nbrOfFails = 0
        self.failedGuests = []
        self.vmDomid = 0
        xenrt.pfarm ([xenrt.PTask(self.createVmCloneThread, host, tailor_guest= tailor_guest) for host in self.hosts])
        self.nbrOfGuests = self.currentNbrOfGuests - self.nbrOfFails

        #To reduce the Xenserver load, due to XenRT interference, it is better to start the guests after creating all the Clones
        if self.max != 0:
            nbrOfThreads = min(5*len(self.hosts),25)
            xenrt.TEC().logverbose("Starting all Guests")
            self.guestsPendingOperation = [g for g in self.guests]
            self.nbrOfPassedGuests = 0
            xenrt.pfarm ([xenrt.PTask(self.guestOperationThread, operation="start", iterationNbr=0) for threads in range(nbrOfThreads)])

            if self.nbrOfPassedGuests<self.nbrOfGuests:
                xenrt.TEC().comment("Attempt to start guests after cloning finished with %s%% (%s/%s) success rate ."% ((self.nbrOfPassedGuests*100/self.nbrOfGuests),self.nbrOfPassedGuests,self.nbrOfGuests))
                raise xenrt.XRTFailure("Couldn't start all cloned VMs." )

            if self.HATEST:
                for g in self.guests:
                    g.setHAPriority(order=2, protect=True, restart=False)
                    if not g.paramGet("ha-restart-priority") == "best-effort":
                        raise xenrt.XRTFailure("Guest %s not marked as protected after setting priority" % (g.getName()))

    def checkGuestThread(self):
        while True:
            with self.lock:
                if len(self.guestsNotChecked)== 0:
                    return
                g = self.guestsNotChecked.pop()

            isAlive = False
            isUp = False

            if self.CHECKREACHABLE:
                try:
                    g.checkReachable()
                except:
                    xenrt.TEC().warning("Guest %s not reachable" % (g.getName()))
                else:
                    isAlive = True

            if self.CHECKHEALTH:
                try:
                    if g.getState() == "UP":
                        g.checkHealth(noreachcheck=True) #noreachcheck=True will ensure the VNC Snapshot is taken and checked
                        isUp = True
                except:
                    xenrt.TEC().warning("Guest %s not up" % (g.getName()))

            with self.lock:
                if isAlive:
                    self.nbrOfGuestsAlive = self.nbrOfGuestsAlive + 1
                if isUp:
                    self.nbrOfGuestsUp = self.nbrOfGuestsUp + 1

    def checkGuests(self):
        nbrOfThreads = min(5*len(self.hosts),25)

        self.guestsNotChecked = [g for g in self.guests]
        self.nbrOfGuestsAlive = 0
        self.nbrOfGuestsUp = 0
        xenrt.pfarm ([xenrt.PTask(self.checkGuestThread) for threads in range(nbrOfThreads)])

        if self.CHECKREACHABLE:
            xenrt.TEC().logverbose("%d/%d guests reachable" % (self.nbrOfGuestsAlive, self.nbrOfGuests))
        if self.CHECKHEALTH:
            xenrt.TEC().logverbose("%d/%d guests up" % (self.nbrOfGuestsUp, self.nbrOfGuests))

        if self.CHECKREACHABLE and self.nbrOfGuestsAlive < self.nbrOfGuests:
            raise xenrt.XRTFailure("%d guests not reachable" % (self.nbrOfGuests-self.nbrOfGuestsAlive))

        if self.CHECKHEALTH and self.nbrOfGuestsUp < self.nbrOfGuests:
            raise xenrt.XRTFailure("%d guests are not healthy" % (self.nbrOfGuests-self.nbrOfGuestsUp))

    def guestOperationThread(self, operation, iterationNbr = None):
        while True:
            with self.lock:
                if len(self.guestsPendingOperation)== 0:
                    return
                g = self.guestsPendingOperation.pop()

            passed = False

            try:
                if operation == "shutdown":
                    g.shutdown()
                elif operation == "start":
                    g.start(specifyOn = False)
                passed = True
            except Exception, e:
                if iterationNbr == None:
                    xenrt.TEC().warning("Guest %s failed to %s." % (g.getName(), operation))
                    xenrt.TEC().logverbose("Guest %s failed to %s : %s" % (g.getName(), operation, str(e)))
                else:
                    xenrt.TEC().warning("LOOP %s: Guest %s failed to %s" % (iterationNbr, g.getName(), operation))
                    xenrt.TEC().logverbose("Guest %s failed to %s : %s" % (g.getName(), operation, str(e)))
                    
            with self.lock:
                if passed:
                    self.nbrOfPassedGuests = self.nbrOfPassedGuests+1

            if g.getDomid() <= 1:
                 raise xenrt.XRTFailure("Guest %s domid %s is less than two - looks like host has crashed/rebooted" % (g.getName(),g.getDomid()))

    def loopingTest(self):
        nbrOfThreads = min(5*len(self.hosts),25)

        xenrt.TEC().logverbose("Shutting down all Guests")
        self.guestsPendingOperation = [g for g in self.guests]
        self.nbrOfPassedGuests = 0
        xenrt.pfarm ([xenrt.PTask(self.guestOperationThread, operation="shutdown", iterationNbr=0) for threads in range(nbrOfThreads)])
        xenrt.TEC().comment("Shutdown attempt finished with %s%% (%s/%s) success rate ."% ((self.nbrOfPassedGuests*100/self.nbrOfGuests),self.nbrOfPassedGuests,self.nbrOfGuests))

        try:
            for i in range(self.LOOPS):

                xenrt.TEC().logverbose("LOOP %s: Loop iteration started. Starting all Guests."% i)
                self.guestsPendingOperation = [g for g in self.guests]
                self.nbrOfPassedGuests = 0
                xenrt.pfarm ([xenrt.PTask(self.guestOperationThread, operation="start", iterationNbr=i) for threads in range(nbrOfThreads)])
                xenrt.TEC().comment("LOOP %s: start attempt finished with %s%% (%s/%s) success rate ."% (i,(self.nbrOfPassedGuests*100/self.nbrOfGuests),self.nbrOfPassedGuests,self.nbrOfGuests))

                xenrt.TEC().logverbose("LOOP %s: All guests started. Shutting them now."% i)
                self.guestsPendingOperation = [g for g in self.guests]
                self.nbrOfPassedGuests = 0
                xenrt.pfarm ([xenrt.PTask(self.guestOperationThread, operation="shutdown", iterationNbr=i) for threads in range(nbrOfThreads)])
                xenrt.TEC().logverbose("LOOP %s: Loop iteration finished"% i)
                xenrt.TEC().comment("LOOP %s: Shutdown attempt finished with %s%% (%s/%s) success rate ."% (i,(self.nbrOfPassedGuests*100/self.nbrOfGuests),self.nbrOfPassedGuests,self.nbrOfGuests))
        finally:
            self.host.execdom0("sar -A")

    def postRun(self):
        # Try and disable HA if it's running
        if self.pool and self.pool.haEnabled:
            try:
                self.pool.disableHA(check=False)
            except:
                pass

        if self.getResult(code=True) == xenrt.RESULT_FAIL or self.getResult(code=True) == xenrt.RESULT_ERROR:
            self.POSTRUN = "forcecleanup"

        if self.POSTRUN != "nocleanup":
            xenrt.TEC().logverbose("Starting Host Cleanup")
            if self.POSTRUN == "forcecleanup":
                self.host.reboot(forced=True)
            for g in self.guests:
                try:
                    g.uninstall()
                except xenrt.XRTFailure, e:
                    raise xenrt.XRTFailure("Error while uninstalling guest %s: %s" % (g.getName(),e))
                    break
        else:
            xenrt.TEC().logverbose("Skipping Host Cleanup")

class _VIFScalability(_Scalability):
    MAX = None
    VALIDATE = False

    def parseArgument(self,param,value):
        if param == "VIF_per_VM":
            self.MAX = int(xenrt.TEC().lookup(["VERSION_CONFIG", xenrt.TEC().lookup("PRODUCT_VERSION"), "VIF_PER_VM"]))
        else:
            _Scalability.parseArgument(self,param,value)

    def runTC(self,host):
        # Create a guest which we'll use to clone
        guest = host.createGenericLinuxGuest(memory=256)
        self.uninstallOnCleanup(guest)

        # Configure this guest to only have one VBD
        guest.execguest("sed -i 's/\/dev\/xvdb1/#\/dev\/xvdb1/g' /etc/fstab")

        guest.preCloneTailor()
        guest.shutdown()

        #guest.removeDisk(1)

        bridge = host.getPrimaryBridge()

        # Determine how many VIFs we can add to the guest
        vifdevices = host.genParamGet("vm",
                                      guest.getUUID(),
                                      "allowed-VIF-devices").split("; ")
        vifsToAdd = len(vifdevices)

        if self.MAX == True:
            max = int(host.lookup("MAX_CONCURRENT_VIFS"))
        else:
            max = self.MAX

        # Start adding VIFs, once we reach allowed VIFs, make a new clone and
        # continue
        vmCount = 0
        vifCount = 0
        while max == 0 or vifCount < max:
            try:
                if vmCount > 0 and vmCount % 20 == 0:
                    # CA-19617 Perform a vm-copy every 20 clones
                    guest = guest.copyVM()
                    self.uninstallOnCleanup(guest)
                g = guest.cloneVM()
                self.guests.append(g)
                self.uninstallOnCleanup(g)
                g.start()
                vmCount += 1
                vifCount += 1 # Each VM already has 1 vif
            except xenrt.XRTFailure, e:
                xenrt.TEC().comment("Failed to create VM %u: %s" %
                                    (vmCount+1,e))
                break

            try:
                for i in range(vifsToAdd):
                    v = g.createVIF(None,bridge,None)
                    g.plugVIF(v)
                    vifCount += 1
            except xenrt.XRTFailure, e:
                xenrt.TEC().comment("Failed to add VIF %u to VM %u: %s" %
                                    (vifCount+1,vmCount,e))
                break

        if max > 0:
            if vifCount < max:
                raise xenrt.XRTFailure("Asked to create %u VIFs, only managed "
                                       "to create %u (on %u VMs)" %
                                       (max,vifCount,vmCount))
            # Perform some lifecycle operations to check guest health
            if self.VALIDATE:
                if self.runSubcase("lifecycleOperations", (), "LifecycleOperations", "LifecycleOperations") != \
                    xenrt.RESULT_PASS:
                    return

        else:
            xenrt.TEC().value("numberVMs",vmCount)
            xenrt.TEC().value("maximumNumberVIFs",vifCount)


class TC6848(_VMScalability):
    """Test for ability to run the supported maximum number of concurrent
    VM on a host"""
    MAX = True
    MEMORY=128
    VIFS = True
    CHECKREACHABLE=True
    CHECKHEALTH=True

class TC6851(_VMScalability):
    """Determine maximum number of VMs that can run concurrently"""
    MAX = 0
    MEMORY=128

class TC23327(_VMScalability):
    """Determine maximum number of VMs that can run concurrently"""
    MAX = 0
    MEMORY=128
    DISTRO = "rhel510"
    POOLED = True
    LOOPS = 1
    DOM0CPUS = True
    FLOW_EVT_THRESHOLD = 8192

class TC6852(_VMScalability):
    """Test for consistency of number of maximum VMs"""
    MAX = True
    LOOPS = 10
    MEMORY=128

class TC6853(_VMScalability):
    """Test for ability to run the supported number of VMs with VIFs"""
    MAX = True
    VIFS = True
    CHECKREACHABLE = True
    MEMORY=128

class TC19082(_VMScalability):
    """Test for ability to run the maximum supported HA protected VMs on a host"""
    MAX = True
    HATEST = True
    VIFS = True
    CHECKREACHABLE=True
    CHECKHEALTH=True
    MEMORY=128

class TC7336(_VMScalability):
    """Test for ability to run the supported maximum number of concurrent Windows VMs on a host"""
    MAX = True
    VIFS = True
    DISTRO = "winxpsp3"
    CHECKREACHABLE = True
    CHECKHEALTH=True

class TC21642(_VMScalability):
    """Test for ability to run the supported maximum number of concurrent Ubuntu 14.04 VMs on a host"""
    MAX = True
    VIFS = True
    DISTRO = "ubuntu1404"
    CHECKREACHABLE = True
    CHECKHEALTH=True

class TC12610(_VMScalability):
    """Determine maximum number of Windows VMs that can run concurrently"""
    MAX = 0
    VIFS = True
    DISTRO = "winxpsp3"
    CHECKREACHABLE = True

class TC19270(_VMScalability):
    """Test for ability to run the supported number of Linux VMs by disabling some guest features and adjusting Dom0 memory"""
    MAX = 0
    VIFS = True
    CHECKREACHABLE=True
    CHECKHEALTH=True
    TRYMAX = True
    NET_BRIDGE = False
    MEMORY=128
    ARCH = "x86-64"
    #DOM0CPUS = False
    
    def postRun(self):
        # don't do any cleanup - it takes ages
        pass


class TC19271(_VMScalability):
    """Test for ability to run the supported number of Windows VMs by disabling some guest features and adjusting Dom0 memory"""
    MAX = 0
    VIFS = True
    CHECKREACHABLE=True
    CHECKHEALTH=True
    TRYMAX = True
    #DOM0MEM = 8192
    DISTRO = "winxpsp3"
    #NET_BRIDGE = True
    #DOM0CPUS = True
    FLOW_EVT_THRESHOLD = 8192
    
    def postRun(self):
        # don't do any cleanup - it takes ages
        pass

class TC14899(_VMScalability):
    """Test that 160 cores can all be used"""
    MAX=30
    VCPUS=8
    VIFS=True # Needed to start the guest load
    REQUIRED_CORES=160 # Check the host uses at least this number of cores
    MIN_ACTIVE=0.9 # Fraction of a processer used to be considered active
    CHECKREACHABLE=True

    def getHostRRD(self, host, seconds=30):
        xenrt.TEC().logverbose("Attempting to get RRD from %s" %
                               (host.getName()))
        host.findPassword()
        url = "http://root:%s@%s/rrd_updates?start=%d&host=true" % (host.password,
                                                    host.getIP(),
                                                    int(time.time()) - seconds)
        u = urllib.urlopen(url)
        data = u.read()
        xenrt.TEC().logverbose("RRD retrieved as: %s"%data)
        return xml.dom.minidom.parseString(data)

    def installVM(self, host):
        return host.createGenericLinuxGuest(name=xenrt.randomGuestName(),
                                                  arch="x86-32",
                                                  vcpus=self.VCPUS,
                                                  bridge=host.getPrimaryBridge(),
                                                  memory=256)

    def installXenalise(self, host):
        self.xenalise= "/root/xenalyze"
        xenrt.getTestTarball("xen", extract=True)
        sftp = host.sftpClient()
        sftp.copyTo("%s/xen/xenalyze" % (xenrt.TEC().getWorkdir()), self.xenalise)
        sftp.close()

    def runTC(self,host):
        # Install the VMs
        _VMScalability.runTC(self, host)

        live_guests = 0
        for guest in self.guests:
            if guest.getState() != "UP":
                continue
            guest.execguest("touch /tmp/doload")
            for i in range(0,self.VCPUS):
                guest.execguest("while [ -e /tmp/doload ]; do true; done > "
                             "/dev/null 2>&1 < /dev/null &")
            live_guests = live_guests + 1

        xenrt.TEC().logverbose("Allowing 100% CPU usage to continue for 90 seconds")
        time.sleep(90)
        # Get the RRD for the last 60 seconds
        dom = self.getHostRRD(host, 60)

        # Count how many pcpus were active in this RRD
        active = 0
        vals = dom.getElementsByTagName('v')
        for idx,entry in enumerate(dom.getElementsByTagName('entry')):
            data = entry.firstChild.data
            if data.startswith('AVERAGE:host:'):
                dataname = data.split(':')[-1]
                if (dataname.startswith('cpu') and float(vals[idx].firstChild.data) > self.MIN_ACTIVE):
                    active = active + 1

        # Make sure the count of cores used in the RRD is at least REQUIRED_CORES
        if (active < self.REQUIRED_CORES):
            raise xenrt.XRTFailure("Test requires for %d cores to be active, only %d were active.  We expected up to %d to be active (if they exist)"%
                                   (self.REQUIRED_CORES, active,(self.VCPUS*live_guests)) )

        xenrt.TEC().logverbose("Setting guests to be idle")
        for guest in self.guests:
            if guest.getState() != "UP":
                continue
            guest.execguest("rm -f /tmp/doload")


class TC15293(_VMScalability):

    """Test that 160 cores can be pinned"""
    MAX=20
    VCPUS=8
    VIFS=True # Needed to start the guest load
    REQUIRED_CORES=160 # Check the host uses at least this number of cores
    CHECKREACHABLE=True

    # These two variables are used for by a closure (pin_the_vm) passed to runTC.
    GUESTS_PINNING_INFO=dict()
    LAST_CPU_PINNED=0  # cpu number starts from 0

    def installVM(self, host):
        return host.createGenericLinuxGuest(name=xenrt.randomGuestName(),
                                            arch="x86-32",
                                            vcpus=self.VCPUS,
                                            bridge=host.getPrimaryBridge(),
                                            memory=256)

    def pinVm(self, guest, host):

        num_vcpus = self.VCPUS
        first_cpu = self.LAST_CPU_PINNED
        last_cpu = self.LAST_CPU_PINNED + num_vcpus
        self.LAST_CPU_PINNED = last_cpu

        mask = set(range(first_cpu, last_cpu))
        vcpus_params_mask = ("%s," * (num_vcpus - 1) + "%s") % tuple(range(first_cpu, last_cpu))

        cli = host.getCLIInstance()
        args=[]
        args.append('uuid=%s' % guest.getUUID())
        args.append('VCPUs-params:mask=\"%s\"' % vcpus_params_mask)
        cli.execute('vm-param-set', ' '.join(args))

        self.GUESTS_PINNING_INFO[guest.getName()] = mask

        return


    def checkVMPinning(self, guests, host):

        test_status = True

        for g in guests:
            if g.getState() != 'UP':
                continue

            mask = self.GUESTS_PINNING_INFO[g.getName()]
            xenrt.TEC().logverbose("Checking VM [%s] " % g.getUUID())
            domid = g.getDomid()
            vm_affinity_status = True
            for c in range(0, g.vcpus):

                data = host.execdom0("/opt/xensource/debug/xenops affinity_get -domid %s -vcpu %s" %
                                    (domid, c)).strip()
                for j in mask:
                    if not int(list(data)[j]) == 1:
                        vm_affinity_status = False

            if vm_affinity_status is False:
                xenrt.TEC().logverbose('VM [%s] has unexpected affinity expected mask = %s' %
                                       (g.getUUID(), mask))
                test_status = False

        return test_status


    def runTC(self,host):
        # Install the VMs
        self.cores = host.getCPUCores()
        if self.cores < self.REQUIRED_CORES:
            raise xenrt.XRTError("host has only %s cores, but we need a host with atleast %s cores" %
                                 (self.cores, self.REQUIRED_CORES))
        pin_the_guest = lambda g : self.pinVm(g, host)
        _VMScalability.runTC(self, host, tailor_guest=pin_the_guest)

        status = self.checkVMPinning(self.guests, host)

        if status is False:
            raise xenrt.XRTFailure('VMs have unexpected affinity')


class TC6875(_VIFScalability):
    """Test for the supported maximum number of VIFs on a host across all VMs"""
    MAX = True

    def parseArgument(self,param,value):
        if param == "max":
            self.MAX = value
        else:
            _VIFScalability.parseArgument(self,param,value)

class TC6876(_VIFScalability):
    """Determine maximum number of VIFs that can be created"""
    MAX = 0
    VALIDATE = True


class _VDIScalability(_Scalability):

    CONCURRENT = None
    SR = None

    vdis = []
    cli = None
    VALIDATE = False

    def runTC(self,host):

        if self.MAX == True:
            max = int(host.lookup("MAX_VDIS_PER_SR_%s" % (self.SR)))
        else:
            max = self.MAX

        if self.CONCURRENT == True:
            conc = int(host.lookup("MAX_ATTACHED_VDIS_PER_SR_%s" % (self.SR)))
        else:
            conc = self.CONCURRENT

        # Find the SR
        srs = host.getSRs(type=self.SR)
        if len(srs) == 0:
            raise xenrt.XRTError("Couldn't find a %s SR" % (self.SR))

        sr = srs[0]
        # If we're testing a max, make sure that we have enough space on this SR
        if max > 0:
            psize = host.getSRParam(sr,"physical-size")
            if psize > 0: # NFS etc SRs will have a size of 0
                if (10485760 * max) > psize:
                    raise xenrt.XRTError("SR is not big enough (%u MB) to test"
                                         " %u 10M VDIs" % (psize,max))

        # Get the CLI
        cli = host.getCLIInstance()
        self.cli = cli

        # Create the VDIs (not specifically allocated to VBDs at this point)
        vdiCount = 0
        while max == 0 or vdiCount < max:
            try:
                args = []
                args.append("name-label=\"VDI Scalability %u\"" % (vdiCount))
                args.append("sr-uuid=%s" % (sr))
                args.append("virtual-size=10485760") # 10MB
                args.append("type=user")
                uuid = cli.execute("vdi-create", string.join(args), strip=True)
                self.vdis.append(uuid)
                vdiCount += 1
            except xenrt.XRTFailure, e:
                # Check we haven't run out of space...
                psize = int(host.getSRParam(sr,"physical-size"))
                if psize > 0:
                    spaceleft = psize - \
                                int(host.getSRParam(sr,"physical-utilisation"))
                    if spaceleft < 10485760:
                        xenrt.TEC().warning("Ran out of space on SR, required "
                                            "10485760, had %u" % (spaceleft))

                xenrt.TEC().comment("Failed to create VDI %u: %s" %
                                    (vdiCount+1,e))
                break
            if vdiCount == 4000:
                xenrt.TEC().comment("Created 4000 VDIs, stopping now.")
                break

        if max > 0:
            if vdiCount < max:
                raise xenrt.XRTFailure("Asked to create %u VDIs, only managed "
                                       "to create %u" % (max,vdiCount))
        else:
            xenrt.TEC().value("numberVDIs",vdiCount)

        # See how long an sr-scan takes
        try:
            t = xenrt.util.Timer()
            t.startMeasurement()
            cli.execute("sr-scan","uuid=%s" % (sr))
            t.stopMeasurement()
            xenrt.TEC().value("sr-scan",t.max())
        except xenrt.XRTFailure, e:
            xenrt.TEC().warning("Exception while performing sr-scan: %s" % (e))

        # Now see if we can use them all...

        # Create a guest which we'll use to clone (we hope that the default SR
        # is not the one we've just filled or all will go wrong!)
        guest = host.createGenericLinuxGuest()
        self.uninstallOnCleanup(guest)

        guest.preCloneTailor()
        guest.shutdown()

        # Determine how many VBDs we can add to the guest
        vbddevices = host.genParamGet("vm",
                                      guest.getUUID(),
                                      "allowed-VBD-devices").split("; ")
        vbdsAvailable = len(vbddevices)

        # Start adding VBDs and plugging VDIs into them, once we reach allowed
        # VBDs, make a new clone and continue
        currentGuest = guest.cloneVM()
        self.guests.append(currentGuest)
        self.uninstallOnCleanup(currentGuest)
        currentGuest.start()
        vmCount = 1
        pluggedCount = 0
        leftOnGuest = vbdsAvailable
        vdiConcurrent = vdiCount
        if conc and conc < vdiCount:
            vdiConcurrent = conc
        else:
            vdiConcurrent = vdiCount
        for i in range(vdiConcurrent):
            if leftOnGuest == 0:
                try:
                    if vmCount > 0 and vmCount % 20 == 0:
                        # CA-19617 Perform a vm-copy every 20 clones
                        guest = guest.copyVM()
                        self.uninstallOnCleanup(guest)
                    g = guest.cloneVM()
                    self.uninstallOnCleanup(g)
                    g.start()
                    vmCount += 1
                    currentGuest = g
                    self.guests.append(currentGuest)
                    leftOnGuest = vbdsAvailable
                except xenrt.XRTFailure, e:
                    # This isn't a failure of the testcase, but does mean we
                    # can't fully test so raise an error (i.e. we need to use a
                    # better provisioned host!)
                    raise xenrt.XRTError("Failed to create VM %u (%s) required "
                                         "for testing maximum number of VDIs" %
                                         (vmCount+1,e))

            try:
                currentGuest.createDisk(vdiuuid=self.vdis[i])
                pluggedCount += 1
                leftOnGuest -= 1
            except xenrt.XRTFailure, e:
                xenrt.TEC().comment("Failed to create/plug VBD for VDI %u: %s" %
                                    (pluggedCount+1,e))
                break

        if pluggedCount < vdiConcurrent:
            raise xenrt.XRTFailure("Created %u VDIs, only able to create/plug "
                                   "VBDs for %u on %u guests" %
                                   (vdiConcurrent,pluggedCount,vmCount))
        else:
            xenrt.TEC().value("numberVMs",vmCount)
            # Perform some lifecycle operations to check guest health
            if self.VALIDATE:
                if self.runSubcase("lifecycleOperations", (), "LifecycleOperations", "LifecycleOperations") != xenrt.RESULT_PASS:
                    return

    def parseArgument(self,param,value):
        if param == "max":
            self.MAX = value
        else:
            _Scalability.parseArgument(self,param,value)

    def postRun2(self):
        # Delete the VDIs
        for vdi in self.vdis:
            try:
                self.cli.execute("vdi-destroy uuid=%s" % (vdi))
            except:
                xenrt.TEC().warning("Exception destroying VDI %s" % (vdi))

class TC6930(_VDIScalability):
    """Determine maximum number of VDIs for ext SR"""
    SR = "ext"
    MAX = 0

class TC6931(_VDIScalability):
    """Determine maximum number of VDIs for nfs SR"""
    SR = "nfs"
    MAX = 0

class TC6932(_VDIScalability):
    """Determine maximum number of VDIs for lvm SR"""
    SR = "lvm"
    MAX = 0

class TC6933(_VDIScalability):
    """Determine maximum number of VDIs for lvmohba SR"""
    SR = "lvmohba"
    MAX = 0

class TC6934(_VDIScalability):
    """Determine maximum number of VDIs for lvmoiscsi SR"""
    SR = "lvmoiscsi"
    MAX = 0

class TC6935(_VDIScalability):
    """Determine maximum number of VDIs for netapp SR"""
    SR = "netapp"
    MAX = 0

class TC6941(_VDIScalability):
    """Test for ability to use the maximum supported number of VDIs on ext SR"""
    SR = "ext"
    MAX = 250
    CONCURRENT = 150

class TC6942(_VDIScalability):
    """Test for ability to use the maximum supported number of VDIs on nfs SR"""
    SR = "nfs"
    MAX = 250
    CONCURRENT = 150

class TC6943(_VDIScalability):
    """Test for ability to use the maximum supported number of VDIs on lvm SR"""
    SR = "lvm"
    MAX = 250

class TC6944(_VDIScalability):
    """Test for ability to use the maximum supported number of VDIs on lvmohba SR"""
    SR = "lvmohba"
    MAX = 250

class TC6945(_VDIScalability):
    """Test for ability to use the maximum supported number of VDIs on lvmoiscsi SR"""
    SR = "lvmoiscsi"
    MAX = 250

class TC6946(_VDIScalability):
    """Test for ability to use the maximum supported number of VDIs on netapp SR"""
    SR = "netapp"
    MAX = 250

class TC8082(_VDIScalability):
    """Verify the supported maximum number of VDIs per SR can be created and attached (Local VHD)"""
    SR = "ext"
    MAX = True
    CONCURRENT = True

class TC8083(_VDIScalability):
    """Verify the supported maximum number of VDIs per SR can be created and attached (Local LVM)"""
    SR = "lvm"
    MAX = True
    CONCURRENT = True
    VALIDATE = True

class TC8084(_VDIScalability):
    """Verify the supported maximum number of VDIs per SR can be created and attached (NFS)"""
    SR = "nfs"
    MAX = True
    CONCURRENT = True
    VALIDATE = True

class TC8085(_VDIScalability):
    """Verify the supported maximum number of VDIs per SR can be created and attached (LVMoISCSI)"""
    SR = "lvmoiscsi"
    MAX = True
    CONCURRENT = True

class TC8086(_VDIScalability):
    """Verify the supported maximum number of VDIs per SR can be created and attached (NetApp)"""
    SR = "netapp"
    MAX = True
    CONCURRENT = True
    VALIDATE = True

class TC8087(_VDIScalability):
    """Verify the supported maximum number of VDIs per SR can be created and attached (Equallogic)"""
    SR = "equal"
    MAX = True
    CONCURRENT = True

class TC7298(_Scalability):
    """Verify the maximum length of a VHD chain"""

    # Test to see how many we can do. Take a VDI, keep cloning it, and after
    # each clone put it into a VBD and start the VM with that VBD attached.
    # If VM fails to boot, stop.

    vdis = []
    MaxLength = 1917 # Create a chain of length 1917 (= 65530 AIO slots)
    cli = None

    def runTC(self,host):

        # Create the VM now (making sure it's on local storage)
        srs = host.getSRs(type="lvm")
        if len(srs) == 0:
            raise xenrt.XRTError("Could not find a local storage (lvm) SR")
        lvmsr = srs[0]

        srs = host.getSRs(type="ext")
        if len(srs) == 0:
            raise xenrt.XRTError("Could not find an ext SR")
        extsr = srs[0]

        guest = host.createGenericLinuxGuest(sr=lvmsr,start=False)
        self.uninstallOnCleanup(guest)

        cli = host.getCLIInstance()
        self.cli = cli

        # Create the initial VDI
        args = []
        args.append("name-label=\"VHD chain length VDI\"")
        args.append("sr-uuid=%s" % (extsr))
        args.append("virtual-size=10485760") # 10MB
        args.append("type=user")
        currentVDI = cli.execute("vdi-create", string.join(args), strip=True)
        self.vdis.append(currentVDI)

        # Use MaxLength-1 to take into account the initial VHD
        for i in range(self.MaxLength-1):
            currentVDI = cli.execute("vdi-clone","uuid=%s" % (currentVDI), strip=True)
            self.vdis.append(currentVDI)

        finalVDI = currentVDI

        # Plug this VDI into the guest
        guest.createDisk(vdiuuid=finalVDI)

        # Now try and start the guest
        guest.start()

        # Check it's happy
        guest.check()

    def postRun2(self):
        # Delete the VDIs
        for vdi in self.vdis:
            try:
                self.cli.execute("vdi-destroy uuid=%s" % (vdi))
            except:
                xenrt.TEC().warning("Exception destroying VDI %s" % (vdi))

class TC8237(xenrt.TestCase):

    def __init__(self, tcid="TC8237"):
        self.vms = 255
        self.memory = 16
        self.guests = []
        self.timeout = 30
        xenrt.TestCase.__init__(self, tcid)

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.sruuid = self.host.getLocalSR()

        for i in range(self.vms):
            xenrt.TEC().logverbose("Creating tiny VM %s..." % (i))
            g = self.host.guestFactory()(xenrt.randomGuestName(), host=self.host)
            g.createHVMGuest([(8, self.sruuid),
                              (8, self.sruuid),
                              (8, self.sruuid),
                              (8, self.sruuid)])
            g.memset(self.memory)
            self.guests.append(g)

    def run(self, arglist):
        xenrt.TEC().logverbose("Running LVM command...")
        vg = self.host.execdom0("vgs --noheadings -o vg_name").strip()
        if not re.search(self.sruuid, vg):
            raise xenrt.XRTError("Failure parsing volume group id. (%s)" % (vg))
        if isinstance(self.host, xenrt.lib.xenserver.DundeeHost):
            self.host.execdom0("export LVM_SYSTEM_DIR='/etc/lvm/master'; vgchange -an %s" % (vg))
        else:
            self.host.execdom0("vgchange -an --master %s" % (vg))
        time.sleep(self.timeout)
        xenrt.TEC().logverbose("Checking if xapi has died...")
        try:
            self.host.execdom0("/etc/init.d/xapi status")
        except:
            raise xenrt.XRTFailure("It looks like xapi has died.")
        xenrt.TEC().logverbose("Checking dmesg for OOM kills...")
        try:
            data = self.host.execdom0("dmesg | grep 'Out of memory'")
            kills = re.findall("process ([0-9]+) \((.*)\)", data)
            xenrt.TEC().logverbose("OOM killed processes (PID, name): %s" % (kills))
            raise xenrt.XRTFailure("Found OOM kills.")
        except:
            pass

    def postRun(self):
        for g in self.guests:
            try:
                g.uninstall()
            except:
                pass

class _VMInstall(xenrt.XRTThread):

    def __init__(self, host, distro, vcpus, memory):
        self.host = host
        self.distro = distro
        self.vcpus = vcpus
        self.memory = memory
        self.guest = None
        self.exception = None
        xenrt.XRTThread.__init__(self)

    def run(self):
        try:
            self.guest =  xenrt.lib.xenserver.guest.createVM(\
                self.host,
                xenrt.randomGuestName(),
                self.distro,
                memory=self.memory,
                vcpus=self.vcpus,
                vifs=xenrt.lib.xenserver.Guest.DEFAULT)
            self.guest.installDrivers()
        except Exception, e:
            xenrt.TEC().logverbose("Exception while performing a VM install")
            traceback.print_exc(file=sys.stderr)
            self.exception = e

class _VMCopy(xenrt.XRTThread):

    def __init__(self, guest, copies):
        self.guest = guest
        self.copies = copies
        self.guests = []
        self.exception = None
        xenrt.XRTThread.__init__(self)

    def run(self):
        try:
            self.guest.preCloneTailor()
            self.guest.shutdown()
            for i in range(self.copies):
                g = self.guest.cloneVM()
                g.start()
                g.shutdown()
                self.guests.append(g)
        except Exception, e:
            xenrt.TEC().logverbose("Exception while performing a VM copy")
            traceback.print_exc(file=sys.stderr)
            self.exception = e

class TC8397(xenrt.TestCase):
    """Start 16 Windows VMs each on 16 hosts"""

    # This test should be run with no shared SR and POOL_NO_DEFAULT_SR=yes

    DISTRO = "ws08sp2-x86"
    MEMORY = 384
    VCPUS = 1
    INSTALLPERHOST = 4
    COPYPERVM = 3
    CLITIMEOUT = 14400

    def installVMs(self):
        """Install a number of VMs per host."""
        workers = []
        for host in self.hosts:
            for i in range(self.INSTALLPERHOST):
                w = _VMInstall(host, self.DISTRO, self.VCPUS, self.MEMORY)
                workers.append(w)
                w.start()
        for w in workers:
            w.join()
            if w.exception:
                raise w.exception
            self.guests.append(w.guest)

    def copyVMs(self):
        """Create a number of copies of each VM."""
        workers = []
        for guest in self.guests:
            w = _VMCopy(guest, self.COPYPERVM)
            workers.append(w)
            w.start()
        for w in workers:
            w.join()
            if w.exception:
                raise w.exception
            self.guests.extend(w.guests)

    def multiple(self, reboot, iterations):

        # Test start/shutdown in a loop using --multiple
        guestlist = copy.copy(self.guests)
        success = 0
        fail = 0
        try:
            for i in range(iterations):
                xenrt.TEC().logverbose("Starting loop iteration %u..." % (i))
                for host in self.hosts:
                    host.listDomains()
                c = copy.copy(guestlist)
                # On the first iteration of a reboot test we just start
                # because the previous subcase left the VM down
                if i == 0:
                    doreboot = False
                else:
                    doreboot = reboot
                xenrt.lib.xenserver.startMulti(guestlist,
                                               reboot=doreboot,
                                               no_on=True,
                                               clitimeout=self.CLITIMEOUT)
                for g in c:
                    if not g in guestlist:
                        fail = fail + 1
                for host in self.hosts:
                    host.checkHealth()
                    host.listDomains()
                if guestlist == []:
                    break
                c = copy.copy(guestlist)
                if not reboot:
                    xenrt.lib.xenserver.shutdownMulti(guestlist,
                                                      clitimeout=self.CLITIMEOUT)
                    for g in c:
                        if not g in guestlist:
                            fail = fail + 1
                    for host in self.hosts:
                        host.checkHealth()
                if guestlist == []:
                    break
                success = success + 1
                if xenrt.GEC().abort:
                    xenrt.TEC().warning("Aborting on command")
                    break
        finally:
            self.tec.comment("%u/%u iterations successful" %
                             (success, iterations))
        if fail > 0:
            raise xenrt.XRTFailure("%d guests failed." % (fail))

    def run(self,arglist):
        # Use the pool associated with the default host
        defhost = self.getDefaultHost()
        if defhost.pool:
            self.hosts = defhost.pool.getHosts()
        else:
            self.hosts = [defhost]
        self.guests = []
        xenrt.TEC().comment("Testing with a pool of size %u" %
                            (len(self.hosts)))
        if self.runSubcase("installVMs", (), "Setup", "InstallVMs") != \
               xenrt.RESULT_PASS:
            return
        if self.runSubcase("copyVMs", (), "Setup", "CopyVMs") != \
               xenrt.RESULT_PASS:
            return
        if self.runSubcase("multiple", (False, 10), "Lifecycle", "StartStop") != \
               xenrt.RESULT_PASS:
            return
        if self.runSubcase("multiple", (True, 5), "Lifecycle", "Reboot") != \
               xenrt.RESULT_PASS:
            return

class TC8397Test(TC8397):

    # This test should be run with no shared SR and POOL_NO_DEFAULT_SR=yes

    DISTRO = "ws08sp2-x86"
    MEMORY = 384
    VCPUS = 1
    INSTALLPERHOST = 1
    COPYPERVM = 1
    CLITIMEOUT = 1800

class _TimedTestCase(xenrt.TestCase):
    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.timings = []

    def addTiming(self, timing):
        self.timings.append(timing)

    def preLogs(self, outputfile=None):
        if outputfile:
            filename = "%s/%s" % (xenrt.TEC().getLogdir(), outputfile)
        else:
            filename = "%s/xenrt-timings.log" % (xenrt.TEC().getLogdir())
        f = file(filename, "w")
        f.write("\n".join(self.timings))
        f.close()


class _TCCloneVMs(_TimedTestCase):

    def __init__(self, tcid=None):
        _TimedTestCase.__init__(self, tcid)
        self.lock = threading.Lock()

    # Base class for cloning VMs with worker threads
    def prepare(self, arglist=None):
        # Find the gold VMs - we'll clone from these
        # e.g. if we have 2 golden images, we'll clone half from gold0 and half from gold1
        self.gold = []
        i = 0
        while True:
            g = xenrt.TEC().gec.registry.guestGet('gold%d' % i)
            i += 1
            if not g:
                break
            self.gold.append(g)

        # Get the hosts
        defhost = self.getDefaultHost()
        if defhost.pool:
            self.hosts = defhost.pool.getHosts()
        else:
            self.hosts = [defhost]

        # If we're using intellicache, enable it now, on the hosts and the golden image
        if xenrt.TEC().lookup("USE_INTELLICACHE", False, boolean=True):
            for h in self.hosts:
                h.evacuate()
                h.disable()
                h.enableCaching()
                h.enable()
            for g in self.gold:
                for vdi in defhost.minimalList("vbd-list", "vdi-uuid", "vm-uuid=%s type=Disk" % (g.getUUID())):
                    defhost.genParamSet("vdi", vdi, "on-boot", "reset")
                    defhost.genParamSet("vdi", vdi, "allow-caching", "true")

    def run(self, arglist):
        threading.stack_size(65536)
        hostCount = len(self.hosts)
        vmsPerHost = None
        threads = None

        # Get the sequence variables
        if arglist and len(arglist) > 0:
            for arg in arglist:
                l = string.split(arg, "=", 1)
                if l[0] == "vmsperhost":
                    vmsPerHost = int(l[1])
                if l[0] == "threads":
                    threads = int(l[1])

        # This is the total number of VMs
        vmCount = hostCount * vmsPerHost

        # Generate the list of VM names, which host they will run on and where they're clones from
        # The name will be of the format clonex.y.z:
        #   x = host the VM will run on
        #   y = index of the VM on the host
        #   z = golden VM this VM was cloned from
        self.vmSpecs = map(lambda x: ("clone%d.%d.%d" % (x % hostCount, x / hostCount, x % len(self.gold)), self.hosts[x % hostCount], self.gold[x % len(self.gold)]), range(vmCount))

        # We'll run this with a limited number of workers (threads).
        # Each worker thread will pull a VM Spec from the list, clone it, then move onto the next one. The threads will complete when all VMs are cloned
        pClone = map(lambda x: xenrt.PTask(self.doClones), range(threads))
        xenrt.pfarm(pClone)

    def doClones(self):
        # Worker thread function for cloning VMs.
        while True:
            with self.lock:
                item = None
                # Get a VM spec from the queue
                if len(self.vmSpecs) > 0:
                    item = self.vmSpecs.pop()
            # If we didn't get a VM, then they're all cloned, so finish the thread
            if not item:
                break
            # Clone the VM. The actual mechanism for cloning is in the derived class
            (vmname, host, gold) = item
            xenrt.TEC().logverbose("Cloning VM to %s on host %s" % (vmname, host.getName()))
            vm = self.cloneVM(vmname, host, gold)
            # Put it in the registry
            with self.lock:
                xenrt.TEC().registry.guestPut(vmname, vm)
            # Set a variable to see where this VM was cloned from
            vm.special['gold'] = gold.getName()

    def cloneVM(self, vmname, host, gold):
        raise xenrt.XRTError("Unimplemented")

class TCXenDesktopCloneVMs(_TCCloneVMs):
    # How to clone a VM, "XenDesktop Style"
    def cloneVM(self, vmname, host, gold):
        self.addTiming("TIME_VM_CLONE_START_%s:%.3f" % (vmname, xenrt.util.timenow(float=True)))
        # Clone the VM
        vm = gold.cloneVM(name=vmname, noIP=True)
        self.addTiming("TIME_VM_CLONE_COMPLETE_%s:%.3f" % (vmname, xenrt.util.timenow(float=True)))
        # Set it to use IPv6
        if gold.getUseIPv6():
            vm.setUseIPv4(None)
            vm.setUseIPv6()

        # Set the host it should be started on
        vm.setHost(host)

        # Find out which SR the golden VDI is on
        goldvdi = gold.getHost().minimalList("vbd-list", args="vm-uuid=%s userdevice=0" % gold.getUUID(), params="vdi-uuid")[0]
        goldsr = gold.getHost().genParamGet("vdi", goldvdi, "sr-uuid")

        # Create extra disks (identity disk and PVD) on the same SR as the golden VDI
        vm.createDisk(sruuid=goldsr, userdevice=1, sizebytes=xenrt.GIGA)
        vm.createDisk(sruuid=goldsr, userdevice=2, sizebytes=xenrt.GIGA)

        self.addTiming("TIME_VM_CLONE_ATTACHPVD_%s:%.3f" % (vmname, xenrt.util.timenow(float=True)))

        if xenrt.TEC().lookup("OPTION_USE_VDIRESET", False, boolean=True):
            vdi = vm.getHost().minimalList("vbd-list", args="vm-uuid=%s userdevice=0" % vm.getUUID(), params="vdi-uuid")[0]
            vm.getHost().genParamSet("vdi", vdi, "on-boot", "reset")

        with self.lock:
            host.addGuest(vm)

        return vm


class _TCScaleVMOp(_TimedTestCase):

    def __init__(self, tcid=None):
        _TimedTestCase.__init__(self, tcid)
        self.lock = threading.Lock()

    # Base class for performing operations on VMs with worker threads
    def prepare(self, arglist=None):
        # Get the hosts
        defhost = self.getDefaultHost()
        if defhost.pool:
            self.hosts = defhost.pool.getHosts()
        else:
            self.hosts = [defhost]

    def run(self, arglist):
        threading.stack_size(65536)
        # Get the sequence variables
        threads = None
        iterations = 1
        if arglist and len(arglist) > 0:
            for arg in arglist:
                l = string.split(arg, "=", 1)
                if l[0] == "threads":
                    threads = int(l[1])
                if l[0] == "iterations":
                    iterations = int(l[1])


        # Get the list of VMs - this is everything that begins with "clone" (cloned in _TCCloneVMs)
        vms = map(lambda x: xenrt.TEC().registry.guestGet(x), filter(lambda x: "clone" in x, xenrt.TEC().registry.guestList()))

        self.doVMOperations(vms, threads, iterations)

    # This is a separate function so that a derived class can override self.vms
    def doVMOperations(self, vms, threads, iterations=1, func=None, timestamps=True):

        if func is None:
            func = self.doOperation

        # We'll store failed VMs here so we don't just bail out at the first failure

        self.vms = vms

        self.failedVMs = []

        # Each iteration will wait for the completion of the previous iteration before going again
        for i in range(iterations):
            # The VM operation may want to complete asynchronously (e.g. finish booting).
            # It can append a completion thread here, and at the end we'll wait for them all to complete before finishing
            self.completionThreads = []
            # Create a list which is the indexes (in self.vms) of the vms to perform operations on.
            self.vmsToOp = range(len(self.vms))
            # Shuffle the VMs for a more realistic workload
            random.shuffle(self.vmsToOp)
            if timestamps is True:
                self.addTiming("TIME_ITERATION%d_START:%.3f" % (i, xenrt.util.timenow(float=True)))
            # Start the worker threads
            pOp = map(lambda x: xenrt.PTask(self.doVMWorker, func), range(threads))

            # Wait for them to complete. The worker threads will wait for the completion threads.
            xenrt.pfarm(pOp)
            if timestamps is True:
                self.addTiming("TIME_ITERATION%d_COMPLETE:%.3f" % (i, xenrt.util.timenow(float=True)))

            # Do any post-iteration cleanup (e.g. deleting old base disks)
            self.postIterationCleanup()
            if timestamps is True:
                self.addTiming("TIME_ITERATION%d_CLEANUPCOMPLETE:%.3f" % (i, xenrt.util.timenow(float=True)))

        try:
            if len(self.failedVMs) > 0:
                raise xenrt.XRTFailure("Failed to perform operation on %d/%d VMs - %s" % (len(self.failedVMs), len(self.vms), ", ".join(self.failedVMs)))
        finally:
            # Verify that all of the hosts and guests are still functional
            if not xenrt.TEC().lookup("NO_HOST_VERIFY", False, boolean=True):
                self.failedHosts = []
                pVerify = map(lambda x: xenrt.PTask(self.verifyHost, x), self.hosts)
                xenrt.pfarm(pVerify)

                if len(self.failedHosts) > 0 and len(self.failedVMs) == 0:
                    raise xenrt.XRTFailure("Failed to verify hosts %s" % ", ".join(self.failedHosts))

    def verifyHost(self, host):
        try:
            # If we're using intellicahce, it won't let us migrate VMs
            if xenrt.TEC().lookup("USE_INTELLICACHE", True, boolean=True):
                host.verifyHostFunctional(migrateVMs=False)
            else:
                host.verifyHostFunctional(migrateVMs=True)
        except Exception,e:
            xenrt.TEC().reason("Failed to verify host %s - %s" % (host.getName(), str(e)))
            with self.lock:
                self.failedHosts.append(host.getName())


    def doVMWorker(self, func):
        # Worker thread function for performing operations on VMs.
        while True:
            with self.lock:
                vm = None
                # Get a VM from the queue
                if len(self.vmsToOp) > 0:
                    vm = self.vms[self.vmsToOp.pop()]

            if not vm:
                # If we didn't get a VM, then theye've all been operated on, so we can exit the loop
                break
            try:
                # Perform the operation on the VM. The operation may need to know where it was originally cloned from
                # (e.g. for XD clone on boot), so pass that in too.
                gold = xenrt.TEC().gec.registry.guestGet(vm.special['gold'])
                func(vm, gold)
            except Exception, e:
                xenrt.TEC().reason("Failed to perform operation on %s - %s" % (vm.getName(), str(e)))
                # Add it to the list of failed VMs, but continue for now.
                with self.lock:
                    self.failedVMs.append(vm.getName())

        # Now we wait for the completion threads to finish, then we can exit the worker thread.
        # It's the responsibility of the completion thread to implement any necessary timeouts
        # A VM operation function may have added a completion thread in order to e.g. wait for VM boot to complete,
        # having exited the function after vm-start returned
        for t in self.completionThreads:
            t.join()



    def doOperation(self, vm, gold):
        raise xenrt.XRTError("Unimplemented")

    def postIterationCleanup(self):
        pass

class _TCScaleVMLifecycle(_TCScaleVMOp):
    def __init__(self, tcid=None):
        _TCScaleVMOp.__init__(self, tcid)

    def waitForVMBoot(self, vm):
        # Thread (called by PTask) Waiting for a VM to boot
        try:
            # Arpwatch if needed
            if not vm.getUseIPv6():
                (mac, ip, bridge) = vm.getVIFs().values()[0]
                try:
                    ip = vm.getHost().arpwatch(bridge, mac, timeout=3600)
                    vm.mainip = ip
                except:
                    (mac, ip, bridge) = vm.getVIFs().values()[0]
                    if ip:
                        vm.mainip = ip
                    else:
                        raise
            # In the Windows case, wait for the execdaemon and the guest agent
            if vm.windows:
                vm.waitForDaemon(3600, desc="Guest boot")
                self.addTiming("TIME_VM_VMAVAILABLE_%s:%.3f" % (vm.getName(), xenrt.util.timenow(float=True)))
                vm.waitForAgent(1800)
                self.addTiming("TIME_VM_AGENT_%s:%.3f" % (vm.getName(), xenrt.util.timenow(float=True)))
            # In the Linux case, just wait for SSH
            else:
                vm.waitForSSH(3600, desc="Guest boot")
                self.addTiming("TIME_VM_VMAVAILABLE_%s:%.3f" % (vm.getName(), xenrt.util.timenow(float=True)))
                self.addTiming("TIME_VM_AGENT_%s:N/A" % (vm.getName()))
        except Exception, e:
            # If it failed, continue, but mark it as failed for now.
            xenrt.TEC().reason("VM %s failed to boot - %s" % (vm.getName(), str(e)))
            with self.lock:
                self.failedVMs.append(vm.getName())

    def start(self, vm):
        # Conventional start

        self.addTiming("TIME_VM_START_%s:%.3f" % (vm.getName(), xenrt.util.timenow(float=True)))
        # Start the VM
        vm.lifecycleOperation("vm-start", specifyOn=True)

        self.addTiming("TIME_VM_STARTCOMPLETE_%s:%.3f" % (vm.getName(), xenrt.util.timenow(float=True)))
        # Asynchronously wait for it to boot
        t = xenrt.PTask(self.waitForVMBoot, vm)
        with self.lock:
            self.completionThreads.append(t)
        t.start()

    def shutdown(self, vm):
        startTime = xenrt.util.timenow(float=True)

        # Shutdown VM
        vm.shutdown()

        shutdownCompleteTime = xenrt.util.timenow(float=True)
        self.addTiming("TIME_VM_SHUTDOWN_%s:%.3f" % (vm.getName(), startTime))
        self.addTiming("TIME_VM_SHUTDOWNCOMPLETE_%s:%.3f" % (vm.getName(), shutdownCompleteTime))


class _TCScaleVMXenDesktopLifecycle(_TCScaleVMLifecycle):
    # Define the XenDesktop style lifecycle ops
    def __init__(self, tcid=None):
        _TCScaleVMLifecycle.__init__(self, tcid)
        self.vdisToDestroy = []

    def xenDesktopStart(self, vm, gold):
        # XenDesktop style start - attach a new clone from the golden image and boot

        self.addTiming("TIME_VM_START_%s:%.3f" % (vm.getName(), xenrt.util.timenow(float=True)))
        vbds = len(vm.getHost().minimalList("vbd-list", args="vm-uuid=%s userdevice=0" % vm.getUUID()))
        # A shutdown VM will need a new VDI attaching, a fresh clone won't
        if vbds == 0:
            # Create new VDI clone from the golden image
            vdiToClone = gold.getHost().minimalList("vbd-list", "vdi-uuid", "vm-uuid=%s userdevice=0" % gold.getUUID())[0]
            newVDI = vm.getHost().getCLIInstance().execute("vdi-clone", "new-name-label=%s uuid=%s" % (vm.getName(), vdiToClone)).strip()

            # Attach it to the VM
            vm.getHost().getCLIInstance().execute("vbd-create", "device=0 bootable=true vm-uuid=%s vdi-uuid=%s" % (vm.getUUID(), newVDI))

            self.addTiming("TIME_VM_DISKPREPARE_%s:%.3f" % (vm.getName(), xenrt.util.timenow(float=True)))

        else:
            self.addTiming("TIME_VM_DISKPREPARE_%s:N/A" % (vm.getName()))

        # Start the VM
        flatVMDist = xenrt.TEC().lookup("FLAT_VM_DIST", True, boolean=True)
        vm.lifecycleOperation("vm-start", specifyOn=flatVMDist, timeout=6000)

        self.addTiming("TIME_VM_STARTCOMPLETE_%s:%.3f" % (vm.getName(), xenrt.util.timenow(float=True)))
        # Asynchronously wait for it to boot
        t = xenrt.PTask(self.waitForVMBoot, vm)
        with self.lock:
            self.completionThreads.append(t)
        t.start()


    # Check for tapdisk for a specific VDI - related to XOP-228
    def checkForTapDisk(self, vdi, tdOutput):
        for t in tdOutput:
            if re.search(vdi, t):
                return True
        return False

    def xenDesktopShutdown(self, vm, gold=None, force=False, detachVDI=True):
        if xenrt.TEC().lookup("CHECK_TAPDISKS", False, boolean=True):
            # Get the attached VDIs
            vdis = vm.getAttachedVDIs()
            tds = vm.getHost().execdom0("tap-ctl list", nolog=True).splitlines()
            # Check they're all in tapdisk
            for v in vdis:
                if not self.checkForTapDisk(v, tds):
                    raise xenrt.XRTFailure("Could not see %s in tapdisk before shutdown" % v)

        startTime = xenrt.util.timenow(float=True)

        # Shutdown VM
        vm.shutdown(force=force)

        shutdownCompleteTime = xenrt.util.timenow(float=True)
        if xenrt.TEC().lookup("CHECK_TAPDISKS", False, boolean=True):
            # Check tapdisk stopped for all VDIs:
            tds = vm.getHost().execdom0("tap-ctl list", nolog=True).splitlines()
            for v in vdis:
                if self.checkForTapDisk(v, tds):
                    raise xenrt.XRTFailure("Can see %s in tapdisk after shutdown" % v)

        self.addTiming("TIME_VM_SHUTDOWN_%s:%.3f" % (vm.getName(), startTime))
        self.addTiming("TIME_VM_SHUTDOWNCOMPLETE_%s:%.3f" % (vm.getName(), shutdownCompleteTime))

        if detachVDI and not xenrt.TEC().lookup("OPTION_USE_VDIRESET", False, boolean=True):
            # Detach base disk
            vbd = vm.getHost().minimalList("vbd-list", args="vm-uuid=%s userdevice=0" % vm.getUUID())[0]
            vdiToDestroy = vm.getHost().genParamGet("vbd", vbd, "vdi-uuid")
            vm.getHost().getCLIInstance().execute("vbd-destroy", "uuid=%s" % vbd)

            diskDetachTime = xenrt.util.timenow(float=True)

            if xenrt.TEC().lookup("OPTION_ASYNC_VDIDESTROY", True, boolean=True):
                # Destroy the VDI later
                with self.lock:
                    self.vdisToDestroy.append(vdiToDestroy)
            else:
                self.hosts[0].getCLIInstance().execute("vdi-destroy", "uuid=%s" % vdiToDestroy)


            self.addTiming("TIME_VM_DISKDETACH_%s:%.3f" % (vm.getName(), diskDetachTime))
        else:
            self.addTiming("TIME_VM_DISKDETACH_%s:N/A" % (vm.getName()))

    def xenDesktopForceShutdown(self, vm, gold=None):
        self.xenDesktopShutdown(vm, force=True, detachVDI=False)

    # Delete all of the old VDIs (simulating XD asynchronous deletion)
    def postIterationCleanup(self):
        for v in self.vdisToDestroy:
            self.hosts[0].getCLIInstance().execute("vdi-destroy", "uuid=%s" % v)
        self.vdisToDestroy = []

class TCScaleVMXenDesktopStart(_TCScaleVMXenDesktopLifecycle):
    # Concrete test case to start all of the VMs, XenDesktop Style
    def doOperation(self, vm, gold):
        self.xenDesktopStart(vm, gold)

class TCScaleVMXenDesktopShutdown(_TCScaleVMXenDesktopLifecycle):
    # Concrete test case to shutdown all of the VMs, XenDesktop Style
    def doOperation(self, vm, gold):
        self.xenDesktopShutdown(vm)

class TCScaleVMXenDesktopUpdate(_TCScaleVMXenDesktopLifecycle):
    def doOperation(self, vm, gold):
        self.addTiming("TIME_VM_UPDATE_START_%s:%.3f" % (vm.getName(), xenrt.util.timenow(float=True)))
        # Detach the VDI
        vbd = vm.getHost().minimalList("vbd-list", args="vm-uuid=%s userdevice=0" % vm.getUUID())[0]
        vdiToDestroy = vm.getHost().genParamGet("vbd", vbd, "vdi-uuid")
        vm.getHost().getCLIInstance().execute("vbd-destroy", "uuid=%s" % vbd)
        self.addTiming("TIME_VM_UPDATE_DISKDETACH_%s:%.3f" % (vm.getName(), xenrt.util.timenow(float=True)))
        # Destroy the VDI
        vm.getHost().getCLIInstance().execute("vdi-destroy", "uuid=%s" % vdiToDestroy)
        self.addTiming("TIME_VM_UPDATE_DISKDESTROY_%s:%.3f" % (vm.getName(), xenrt.util.timenow(float=True)))
        # Clone the VDI
        vdiToClone = gold.getHost().minimalList("vbd-list", "vdi-uuid", "vm-uuid=%s userdevice=0" % gold.getUUID())[0]
        newVDI = vm.getHost().getCLIInstance().execute("vdi-clone", "new-name-label=%s uuid=%s" % (vm.getName(), vdiToClone)).strip()
        self.addTiming("TIME_VM_UPDATE_DISKCLONE_%s:%.3f" % (vm.getName(), xenrt.util.timenow(float=True)))
        # Attach the VDI
        vm.getHost().getCLIInstance().execute("vbd-create", "device=0 bootable=true vm-uuid=%s vdi-uuid=%s" % (vm.getUUID(), newVDI))
        self.addTiming("TIME_VM_UPDATE_COMPLETE_%s:%.3f" % (vm.getName(), xenrt.util.timenow(float=True)))

class TCScaleVMXenDesktopDelete(_TCScaleVMXenDesktopLifecycle):
    def doOperation(self, vm, gold):
        self.addTiming("TIME_VM_DELETE_START_%s:%.3f" % (vm.getName(), xenrt.util.timenow(float=True)))
        vbds = vm.getHost().minimalList("vbd-list", "uuid", "vm-uuid=%s" % vm.getUUID())
        for v in vbds:
            vm.getHost().genParamSet("vbd", v, "other-config:owner", "")
        vm.uninstall()
        self.addTiming("TIME_VM_DELETE_COMPLETE_%s:%.3f" % (vm.getName(), xenrt.util.timenow(float=True)))
        xenrt.TEC().registry.guestDelete(vm.getName())


class TCScaleVMXenDesktopReboot(_TCScaleVMXenDesktopLifecycle):

    # Concrete test case to reboot all of the VMs, XenDesktop Style
    def doOperation(self, vm, gold):
        self.xenDesktopShutdown(vm)
        self.xenDesktopStart(vm, gold)

class TCScaleXenDesktopRpu(xenrt.TestCase):

    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        self.upgrader = xenrt.lib.xenserver.host.RollingPoolUpdate(self.pool)

        self.expectedRunningVMs = 0
        for h in self.pool.getHosts():
            runningGuests = h.listGuests(running=True)
            xenrt.TEC().logverbose("Host: %s has %d running guests [%s]" % (h.getName(), len(runningGuests), runningGuests))
            self.expectedRunningVMs += len(runningGuests)
        xenrt.TEC().logverbose("Pre-upgrade running VMs: %d" % (self.expectedRunningVMs))
        self.__ejectAllCDs()


    def run(self, arglist=None):
        self.newPool = self.pool.upgrade(poolUpgrade=self.upgrader)
        self.newPool.verifyRollingPoolUpgradeInProgress(expected=False)

        postUpgradeRunningGuests = 0
        for h in self.newPool.getHosts():
            try:
                h.verifyHostFunctional(migrateVMs=False)
            except Exception, e:
                xenrt.TEC().logverbose("Functional Host Verification of host: %s failed with Exception: %s" % (h.getName(), str(e)))

            runningGuests = h.listGuests(running=True)
            xenrt.TEC().logverbose("Host: %s has %d running guests [%s]" % (h.getName(), len(runningGuests), runningGuests))
            postUpgradeRunningGuests += len(runningGuests)

        xenrt.TEC().logverbose("Post-upgrade running VMs: %d" % (postUpgradeRunningGuests))
        if self.expectedRunningVMs != postUpgradeRunningGuests:
            xenrt.TEC().logverbose("Expected VMs in running state: %d, Actual: %d" % (self.expectedRunningVMs, postUpgradeRunningGuests))
            raise xenrt.XRTFailure("Not all VMs in running state after upgrade complete")

    def __ejectAllCDs(self):
        # Check that none of the VMs have CDs inserted into their drives.
        cdList = self.pool.master.parameterList(command='cd-list', params=['name-label', 'vbd-uuids', 'uuid'])
        insertedList = filter(lambda x:x['vbd-uuids'] != '', cdList)
        if len(insertedList) > 0:
            vbdUuids = insertedList[0].get('vbd-uuids').split('; ')
            vmUUIDsWithCdsInDrives = [self.pool.master.minimalList(command='vbd-list', params='vm-uuid', args='uuid=%s' % x) for x in vbdUuids]
            flattenedList = [i for subList in vmUUIDsWithCdsInDrives for i in subList]
            log("List of VM UUIDs with CDs inserted: %s" % flattenedList)
            map(lambda x:self.pool.master.getCLIInstance().execute('vm-cd-eject uuid=%s' % (x)), flattenedList)
            log("All CDs ejected")

class TCScaleVMStart(_TCScaleVMLifecycle):
    # Concrete test case to start all of the VMs, Conventional Style
    def doOperation(self, vm, gold):
        self.start(vm)

class TCScaleVMShutdown(_TCScaleVMXenDesktopLifecycle):
    # Concrete test case to shutdown all of the VMs, Conventional Style
    def doOperation(self, vm, gold):
        self.shutdown(vm)

class TCScaleVMReboot(_TCScaleVMXenDesktopLifecycle):

    # Concrete test case to reboot all of the VMs, Conventional Style
    def doOperation(self, vm, gold):
        self.shutdown(vm)
        self.start(vm)



class _Stability(_TCScaleVMXenDesktopLifecycle):
    """Base class for pool stability test with large number of hosts and VMs in the pool"""

    def __init__(self, tcid=None):
        _TCScaleVMXenDesktopLifecycle.__init__(self, tcid)
        self.numberOfHosts = None
        self.hosts = []
        self.hostNames = []
        self.hostsToBoot = []    #list of host objects that needs rebooting
        self.guests = [] # all "clone" VMs in the pool
        self.affectedGuests = []
        self.guestsToIgnore = [] # any guests broken at the beginning of the test
        self.failedHosts = []    #failed host after boot
        self.failedVMs = []
        self.xapiDomainMismatch = ''
        self.interactive = False
        self.failedSRProbeHosts = []


    def prepare(self, arglist=None):

        log("Sleep 10 minutes to stabilise the VMs")
        time.sleep(10*60)

        log("Get the pool host and the master")

        self.pool = self.getDefaultPool()
        self.hosts = self.pool.getHosts()
        self.hostNames = [ host.getName() for host in self.hosts]
        self.host = self.pool.master
        self.numberOfHosts = len(self.hosts)
        self.numberOfSlavesToReboot = 1
        if arglist and len(arglist) > 0:
            for arg in arglist:
                l = string.split(arg, "=", 1)
                if l[0] == "numberOfSlavesToReboot":
                    self.numberOfSlavesToReboot = int(l[1])

        log("Check that all the hosts allocated to the sequence (resource hosts) are present in the pool")

        resourceHosts = xenrt.GEC().config.getWithPrefix("RESOURCE_HOST_")
        resourceHostNames = map(lambda x: x[1], resourceHosts)
        poolHostNames = map(lambda x: x.getName(), self.hosts)

        if not self.interactive:
            if len(resourceHosts) != len(self.hosts) or set(resourceHostNames) != set(poolHostNames):
                raise xenrt.XRTError(
                    "Unexpected configuration: resource hosts list does not match the default pool members list",
                    data=("%d hosts in resources: %s ; %d pool members: %s"
                            % (len(resourceHosts), resourceHostNames, self.numberOfHosts, self.hosts )
                        )
                    )

        log("get the VMs from resources (everything beginning with 'clone')")
        guestNames = [name for name in xenrt.TEC().registry.guestList() if "clone" in name]
        self.guests = [xenrt.TEC().registry.guestGet(name) for name in  guestNames]

        log("get number of threads to use from seq file")
        threads = xenrt.TEC().lookup("NTHREADS", None)
        if threads is None:
            raise xenrt.XRTError("Could not read configuration variable THREADS")
        self.threads = int(threads)

        log("Check the guests, ignore and switch off any disfunctional ones")
        self.verifyGuestsAndHosts()

        log("Choose the host(s) to boot")
        self.setHostsToBoot()
        log("Hosts in the pool: %s"  % self.hosts)
        log("Hosts to boot: %s" % self.hostsToBoot)

        log("filter out the VMS that are on the host to boot")
        for host in self.hostsToBoot:
            prefix = "clone%d." % self.hosts.index(host)
            self.affectedGuests += [vm for vm in self.guests if prefix in vm.getName()]
        log("Affected guests: %s" % self.affectedGuests)


    def verifyOrIgnore(self, vm, gold):
        try:
            vm.verifyGuestFunctional(migrate=False)
        except Exception, e:
            self.ignoreGuest(vm)

    def findPoweredOffGuests(self):
        return [xenrt.TEC().registry.guestGet(name) for name in self.host.minimalList("vm-list", params="name-label", args="power-state=halted") if "clone" in name]

    def verifyGuestsAndHosts(self):
    # switch down guests that are not DOWN, then start all the guests
        log("verifyGuestsAndHosts: Switch off all running guests")
        vms = map(lambda x: xenrt.TEC().registry.guestGet(x), filter(lambda x: "clone" in x, xenrt.TEC().registry.guestList()))
        self.doVMOperations(vms, self.threads, func=self.verifyOrIgnore)


    def doActionBeforeHostReboot(self):
        pass

    def doActionAfterHostReboot(self):
        pass

    def ignoreGuest(self, guest):
        if guest.getState() == "UP":
            try:
                self.xenDesktopShutdown(guest, detachVDI=False)
            except Exception, e:
                log(e)
                try:
                    guest.shutdown(force=True)
                except Exception, e:
                    log(e)
                    pass
        warning('VM %s is broken - ignoring through the rest of the test' % guest.getName())
        self.guestsToIgnore.append(guest)
        self.guests.remove(guest)


    def doOperation(self, vm, gold):
        # We define doOperation XenDesktop Start, it is not the core part of the test,
        # but it will be useful for bringing up the VMs after host reboots
        self.xenDesktopStart(vm, gold)

    def postRun(self):
        # if xapi/domain mismatch was found, restart toolstack on each host
        testResult = self.getResult(code=True)
        if testResult == xenrt.RESULT_FAIL or testResult == xenrt.RESULT_ERROR:
            log('Test case failed, so restarting the toolstack on all hosts')
            for host in self.hosts:
                host.restartToolstack()

            xenrt.sleep(300)

        # power on guests if anything went wrong
        vmsToSwitchOn = self.findPoweredOffGuests()
        log("Switching on VMs %s" % [vm.getName() for vm in vmsToSwitchOn] )
        self.doVMOperations(self.findPoweredOffGuests(), self.threads, 1)
        log("Completed switching on the VMs")

    def hostReboot(self,host):
        self.addTiming("TIME_HOST_SHUTDOWN_%s:%.3f" % (host.getName(), xenrt.util.timenow(float=True)))
        host.machine.powerctl.cycle()
        self.addTiming("TIME_HOST_POWERCYCLE_DONE_%s:%.3f" % (host.getName(),xenrt.util.timenow(float=True)))
        xenrt.sleep(30)
        try:
            host.waitForSSH(600, "Host reboot")
        except Exception,e:
            xenrt.TEC().reason("Failed to Reboot host %s - %s" % (host.getName(), str(e)))
            with self.lock:
                self.failedHosts.append(host.getName())
            self.addTiming("TIME_HOST_REBOOT_FAILED_%s:%.3f" % (host.getName(),xenrt.util.timenow(float=True)))
            return
        self.addTiming("TIME_HOST_UP_%s:%.3f" % (host.getName(),xenrt.util.timenow(float=True)))
        host.waitForXapiStartup()
        host.waitForXapi(600, desc="Xapi response after host power cycle")
        host.waitForEnabled(1200, desc="Wait for power-cycled host to become enabled")
        log("Sleep for 2 minutes for host to update xapi")
        xenrt.sleep(120)

    def setHostsToBoot(self):
        raise xenrt.XRTError("Unimplemented")

    def checkSRProbe(self,host):

        args = []
        nfs=xenrt.ExternalNFSShare()
        serverPath = nfs.base
        server = nfs.address

        cli = host.getCLIInstance()
        args.append("host-uuid=%s" % (host.getMyHostUUID()))
        args.append("type=nfs")
        args.append("device-config:server=%s" % server)
        args.append("device-config:serverpath=%s" % serverPath)
        try:
            sr = cli.execute("sr-probe", string.join(args)).strip()
        except:
            xenrt.TEC().logverbose("SR Probe failed on host %s" % host.getName())
            self.failedSRProbeHosts.append(host.getName())

    def blockSR(self):

        step("Blocking SR port on each host")
        # Set the NICs to static IP before disabling the net ports
        self.setStorageNICsToStatic()

        for host in self.hosts:
            macs = []
            macs=self.getHostMac(host, "Static")
            for mac in macs:
                host.disableNetPort(mac)

    def unblockSR(self):
        step("Unblocking SR port on each host")
        for host in self.hosts:
            macs = []
            macs=self.getHostMac(host, "Static")
            for mac in macs:
                host.enableNetPort(mac)

        # Set the Storage NICs to back to DHCP after enabling the net ports
        self.setStorageNICsToDHCP()


        xenrt.sleep(60)

    def setStorageNICsToStatic(self):
        nicinfos = self.pool.master.parameterList("pif-list", ["uuid", "IP", "netmask"], "management=false IP-configuration-mode=DHCP")
        if len(nicinfos) > 0:
            self.pool.getCLIInstance().execute("pool-disable-redo-log")
            for nicinfo in nicinfos:
                self.pool.getCLIInstance().execute("pif-reconfigure-ip uuid=%s mode=static IP=%s netmask=%s" % (nicinfo['uuid'], nicinfo['IP'], nicinfo["netmask"]))
            redosrs = self.pool.master.minimalList("vdi-list", "sr-uuid", "name-label=\"Metadata redo-log\"")
            if len(redosrs) > 0:
                self.pool.getCLIInstance().execute("pool-enable-redo-log sr-uuid=%s" % redosrs[0])



    def setStorageNICsToDHCP(self):
        uuids=self.pool.master.minimalList("pif-list", "uuid", "management=false IP-configuration-mode=Static")
        if len(uuids) > 0:
            self.pool.getCLIInstance().execute("pool-disable-redo-log")
            for uuid in uuids:
                self.pool.getCLIInstance().execute("pif-reconfigure-ip uuid=%s mode=DHCP" % uuid)
            redosrs = self.pool.master.minimalList("vdi-list", "sr-uuid", "name-label=\"Metadata redo-log\"")
            if len(redosrs) > 0:
                xenrt.sleep(300) # Leave a few minutes to allow connection to the SR
                pbds = self.pool.master.minimalList("pbd-list", "uuid", "sr-uuid=%s" % redosrs[0])
                for p in pbds:
                    self.pool.getCLIInstance().execute("pbd-plug uuid=%s" % p)
                self.pool.getCLIInstance().execute("pool-enable-redo-log sr-uuid=%s" % redosrs[0])

    def getHostMac(self,host,mode):

        # 1. Get the MACs that are non-management physical interfaces with IP addresses (i.e. physical storage interfaces)
        macs = host.minimalList("pif-list", "MAC", "IP-configuration-mode=%s management=false host-uuid=%s physical=true" % (mode, host.getMyHostUUID()))
        # 2. Get the devices that are non-management VLAN interfaces with IP addresses (i.e. VLAN storage interfaces)
        vlanDevices = host.minimalList("pif-list", "device", "IP-configuration-mode=%s management=false host-uuid=%s physical=false" % (mode, host.getMyHostUUID()))
        # Now get the MACs for those devices
        for d in vlanDevices:
            m = host.minimalList("pif-list", "MAC", "device=%s host-uuid=%s physical=true" % (d, host.getMyHostUUID()))[0]
            if m not in macs:
                macs.append(m)

        return macs

    def checkXapiMatchesDomains(self, host):
    # For a given host, get a list of domains with list_domains
    # and also a list guests with resident-on=host (by xapi).
    # Check that these match each other.

        # domain list from list_domains:
        domains = host.listDomains() # this returns dictionnary with guest uuids as keys
        log('Xapi/list_domains mismatch check: Domains for host %s: %s' % (host.getName(), domains) )

        # running guest list from xapi:
        runningGuestsNames =  host.listGuests(running=True)
        runningGuests = [self.getGuest(guestName) for guestName in runningGuestsNames]
        log('Xapi/list_domains mismatch check: Running guests for host %s: %s' % (host.getName(), runningGuestsNames) )

        # remove dom0 from the domain list
        del domains[host.getMyDomain0UUID()]

        # check that xapi-found guests are listed in domains:
        for guest in runningGuests:
            # check that the guest that xapi thinks is running is indeed running:
            uuid = guest.getUUID()
            if domains.has_key(uuid):
                # remove checked guests:
                del domains[uuid]
            else: # else report an error
                with self.lock:
                    self.xapiDomainMismatch += ("Host %s: Guest %s (%s) seen as running in xapi, but corresponding domain not found in list_domains\n"
                            % (host.getName(), guest.getName(), uuid) )

        # check that all domains found by list_domains (except for dom0) were listed by xapi
        if len(domains) > 0:
            with self.lock:
                self.xapiDomainMismatch += ("Host %s: Following domains are running, but not reported as such by xapi: %s\n"
                            % (host.getName(), domains.keys() ))


    def run(self,arglist):

        #This will be used to block SR on every host and will be used in reboot everything test case
        self.doActionBeforeHostReboot()

        step("Wait for 5 minutes to stabilise the pool")
        xenrt.sleep(300)

        step("Rebooting hosts")
        pHostReboot = [ xenrt.PTask(self.hostReboot, host) for host in self.hostsToBoot ]
        xenrt.pfarm(pHostReboot)


        #This will be used to unblock SR on every host and will be used in reboot everything test case
        self.doActionAfterHostReboot()

        step("Check that xapi and list_domains have matching VM state")
        self.xapiDomainMismatch = ''
        pVerify = [ xenrt.PTask(self.checkXapiMatchesDomains, h) for h in self.hosts]
        xenrt.pfarm(pVerify)
        if self.xapiDomainMismatch != '':
            raise xenrt.XRTFailure("After the powercycle, following xapi/list_domains inconsistencies were found:\n%s"
             % self.xapiDomainMismatch )

        step("Checking the rebooted hosts")
        self.failedHosts = []
        pVerify = [ xenrt.PTask(self.verifyHost, h) for h in self.hostsToBoot]
        xenrt.pfarm(pVerify)
        if len(self.failedHosts) > 0:
            raise xenrt.XRTFailure("Failed hosts %s" % ",".join(self.failedHosts))

        step("Checking other hosts")
        self.failedHosts = []
        pVerify = [ xenrt.PTask(self.verifyHost, h) for h in self.hosts if h not in self.hostsToBoot]
        xenrt.pfarm(pVerify)
        if len(self.failedHosts) > 0:
            raise xenrt.XRTFailure("Failed hosts %s" % ",".join(self.failedHosts))

        step("Checking which VMs are DOWN")
        guestsOff = self.findPoweredOffGuests()
        log("Guests powered off: %s" % [g.getName() for g in guestsOff ] )

        step("Check that all VMs that should be affected are down ")
        affectedGuestsNotOff = [vm for vm in self.affectedGuests if vm not in guestsOff]
        log("Affected guests (expected to be down): %s" % [g.getName() for g in self.affectedGuests])
        log("Affected guests that are not off: %s" % [ g.getName() for g in affectedGuestsNotOff ])
        if affectedGuestsNotOff:
            raise xenrt.XRTFailure("Affected guests were expected to be DOWN after host reboot.",
                data="Existing hosts: %s. Following guests should be and are not DOWN:%s" % (self.hosts,[ vm.getName() for vm in affectedGuestsNotOff ]))

        step("Check if any guests outside of the rebooted hosts were affected by the reboot")
        affectedExternalGuests = [vm for vm in guestsOff if (vm not in self.affectedGuests and vm not in self.guestsToIgnore) ]
        if affectedExternalGuests:
            raise xenrt.XRTFailure("Guests not residing on rebooted hosts were found DOWN after reboot",
                data="Guests found unexpectedly DOWN: %s" % [ vm.getName() for vm in affectedExternalGuests])

        step("Bring up all guests that are down - this will raise an exception if anything goes wrong")
        self.doVMOperations(guestsOff, self.threads)

        step("Check all hosts once again, now that the VMs are up")
        pHostReboot = [ xenrt.PTask(self.verifyHost, host) for host in self.hostsToBoot ]
        xenrt.pfarm(pHostReboot)
        if len(self.failedHosts) > 0:
            raise xenrt.XRTFailure("Failed hosts %s" % ",".join(self.failedHosts))

        step('Full guest and host verify, including rebooting guests')
        guestsToIgnoreOriginal = self.guestsToIgnore[:]
        self.verifyGuestsAndHosts()
        if len(self.guestsToIgnore) > len(guestsToIgnoreOriginal) :
            raise xenrt.XRTFailure("Final guest and host check failed - see the warning above on ignored guests.")

        if len(guestsToIgnoreOriginal) > 0:
            raise xenrt.XRTFailure("The test worked, however following guests were broken and/or switched off at the beginning ",
            data = ("%s" % [g.getName() for g in guestsToIgnoreOriginal]) )


    def postIterationCleanup(self):
        pass

class TCStbltyMasterReboot(_Stability):
    """Pool master reboot for a pool of 16 hosts and > 50 VMs/host"""

    def setHostsToBoot(self):
        self.hostsToBoot = [self.pool.master]

class TCStbltySlaveReboot(_Stability):
    """Pool slave reboot for a pool of 16 hosts and > 50 VMs/host"""

    def setHostsToBoot(self):
        # choose one host and make sure it's not the pool master
        self.hostsToBoot = [ self.pool.getSlaves()[0] ]


class TCStbltyMSlaveReboot(_Stability):
    """Multiple slaves reboot for a pool of 16 hosts and > 50 VMs/host"""

    def setHostsToBoot(self):
        # reboot half of the slaves
        allSlaves = self.pool.getSlaves()[:]
        self.hostsToBoot = allSlaves[0:self.numberOfSlavesToReboot]
        random.shuffle(self.hostsToBoot)

class TCStbltyAllHostReboot(_Stability):
    """Multiple slaves reboot for a pool of 16 hosts and > 50 VMs/host"""

    def setHostsToBoot(self):
        # reboot all of the hosts
        self.hostsToBoot = self.pool.getHosts()
        random.shuffle(self.hostsToBoot)


class TCStbltySRReboot(_Stability):
    """SR block on every host"""

    def setHostsToBoot(self):

        pass

    def run(self,arglist):

        self.failedGuest = []
        guestsOff = self.findPoweredOffGuests()

        step('Block SR')
        self.blockSR()

        step('Unblock SR')
        xenrt.sleep(300)
        self.unblockSR()

        step('Run SR probe or each host')
        for host in self.hosts:
            self.checkSRProbe(host)

        if len(self.failedSRProbeHosts) > 0:
            raise xenrt.XRTFailure("Failed SR Probe on host %s" % ",".join(self.failedSRProbeHosts))

        step('Force shutdown all the VMs')
        self.doVMOperations(self.guests, self.threads, func=self.xenDesktopForceShutdown)
        if len(self.failedVMs) > 0:
            log('VMs probably broken: %s' % ", ".join(self.failedVMs))

        step('Start all the VMs')
        self.doVMOperations(self.guests, self.threads, func=self.xenDesktopStart)
        if len(self.failedVMs) > 0:
            warning('These VMs seem to be broken after XenDestkop force reboot: %s' % ", ".join(self.failedVMs) )

        step('Verify that all the hosts are up and running')
        pHost = [ xenrt.PTask(self.verifyHost, host) for host in self.hosts ]
        xenrt.pfarm(pHost)
        if len(self.failedHosts) > 0:
            raise xenrt.XRTFailure("Failed hosts %s" % ",".join(self.failedHosts))

        step('Verify that all the VMs are up and running')

        pVerifyVM = [ xenrt.PTask(self.verifyGuest, guest) for guest in self.guests]
        xenrt.pfarm(pVerifyVM)

        if len(self.failedGuest) > 0:
            xenrt.XRTFailure("Failed VMs %s" % ",".join(self.failedGuest))

    def verifyGuest(self,guest):

        try:
            guest.check()
        except xenrt.XRTFailure, e:
            self.addTiming("Failed to Check VM %s: %s" % (guest.getName(),e))
            with self.lock:
                self.failedGuest.append(guest.getName())

class TCStbltyAllReboot(_Stability):
    """All host reboot and block on every host"""

    def doActionBeforeHostReboot(self):

        self.blockSR()

    def doActionAfterHostReboot(self):

        xenrt.sleep(300)
        self.unblockSR()
        pbds=self.pool.master.minimalList("pbd-list", "uuid", "currently-attached=false")
        for p in pbds:
            self.pool.getCLIInstance().execute("pbd-plug uuid=%s" % p)



    def setHostsToBoot(self):
        # reboot all the hosts
        self.hostsToBoot = self.hosts
        random.shuffle(self.hostsToBoot)

class TCPerfDiskWorkLoad(_TCScaleVMXenDesktopLifecycle):
    """Write 100 MB chunk of data continously till 1 GB is written and then read 100 MB chunk of data continously till 1 GB is read """

    def prepare(self,arglist):

        self.writeFile = 'c:\\writetime.txt'
        self.readFile = 'c:\\readtime.txt'

        guestNames = [name for name in xenrt.TEC().registry.guestList() if "clone" in name]
        self.guests = [xenrt.TEC().registry.guestGet(name) for name in  guestNames]

        self.errorMessages = []

    def run(self,arglist):

        threading.stack_size(65536)

        pWriteScript = [ xenrt.PTask(self.writeScriptWrapper, guest) for guest in self.guests ]
        xenrt.pfarm(pWriteScript)

        xenrt.sleep(30)

        pReadScript = [ xenrt.PTask(self.readScriptWrapper, guest) for guest in self.guests ]
        xenrt.pfarm(pReadScript)

        xenrt.sleep(30)

        pWriteScript = [ xenrt.PTask(self.executeWriteScript, guest) for guest in self.guests ]
        xenrt.pfarm(pWriteScript)

        xenrt.sleep(30)

        pReadScript = [ xenrt.PTask(self.executeReadScript, guest) for guest in self.guests ]
        xenrt.pfarm(pReadScript)

        xenrt.sleep(30)

        for guest in self.guests:
            self.getLogsFromVM(guest)

        if self.errorMessages:
            xenrt.TEC().logverbose(self.errorMessages)
            raise xenrt.XRTFailure("Failures occurred during disk workload test, check logs for further information")

    def getLogsFromVM(self,vm):

        try:
            writeTime = vm.xmlrpcReadFile(self.writeFile)
            readTime = vm.xmlrpcReadFile(self.readFile)
            f = file("%s/DISK_WORKLOAD_RESULT.txt" %
                     (xenrt.TEC().getLogdir()), 'a')
            f.write(str(writeTime))
            f.write(str(readTime))
            f.close()

            xenrt.TEC().logverbose("______________________________________________________________________")
            xenrt.TEC().logverbose("PERF: Write and Read time of 100 MB data for VM %s \n " % vm.getName())
            xenrt.TEC().logverbose("PERF: Write time of 100 MB data for VM %s is \n " % vm.getName())
            xenrt.TEC().logverbose("%s" % str(writeTime))
            xenrt.TEC().logverbose("PERF: Read time of 100 MB data for VM %s is \n " % vm.getName())
            xenrt.TEC().logverbose("%s" % str(readTime))
        except Exception, e:
            errorMessage = "DISK_WORKLOAD_GET_RESULT FAILED on VM %s with error %s" % (vm.getName(),str(e))
            self.errorMessages.append(errorMessage)

    def writeScriptWrapper(self,vm):

        try:
            self.copyWriteScript(vm)
        except Exception, e:
            errorMessage = "DISK_WRITE_WORKLOAD FAILED on VM %s with error %s" % (vm.getName(),str(e))
            with self.lock:
                self.errorMessages.append(errorMessage)

    def readScriptWrapper(self,vm):

        try:
            self.copyReadScript(vm)
        except Exception, e:
            errorMessage = "DISK_READ_WORKLOAD FAILED on VM %s with error %s" % (vm.getName(),str(e))
            with self.lock:
                self.errorMessages.append(errorMessage)

    def copyWriteScript(self,vm):

        writeScriptOnVM = """
from datetime  import datetime
import string
import random
MB=1024*1024
f=open('c:\\\\test','w')
f1=open('c:\\\\writetime.txt','w')
for i in range(50):
    data=(random.choice(string.letters))*10*MB
    timeBefore=datetime.now()
    f.write(data)
    timeAfter = datetime.now()
    diff = str(timeAfter - timeBefore)
    totalTime = '\\r\\n %s: WRITE_TIME: 10MB data: ' + diff
    f1.write(totalTime)
""" % (vm.getName())

        vm.xmlrpcWriteFile("c:\\writeScript.py",writeScriptOnVM)

    def executeWriteScript(self,vm):
        try:
            vm.xmlrpcExec("python c:\\writeScript.py",timeout=14400,ignoreHealthCheck=True)
        except Exception, e:
            errorMessage = "Failed to execute write script on VM %s and failed with error : %s" % (vm.getName(),e)
            with self.lock:
                self.errorMessages.append(errorMessage)

    def copyReadScript(self,vm):

        readScriptOnVM = """
from datetime import datetime
import string
MB=1024*1024
f=open('c:\\\\test','rb')
f1=open('c:\\\\readtime.txt','w')
for i in range(50):
    timeBefore=datetime.now()
    f.read(10*MB)
    timeAfter=datetime.now()
    diff = str(timeAfter - timeBefore)
    totalTime = '\\r\\n%s: READ_TIME: 10MB data: ' + diff
    f1.write(totalTime)
""" % (vm.getName())

        vm.xmlrpcWriteFile("c:\\readScript.py",readScriptOnVM)

    def executeReadScript(self,vm):

        try:
            vm.xmlrpcExec("python c:\\readScript.py",timeout=1800,ignoreHealthCheck=True)
        except Exception, e:
            errorMessage = "Failed to execute read script on VM %s and failed with error : %s" % (vm.getName(),e)
            with self.lock:
                self.errorMessages.append(errorMessage)

class TCPerfCPUWorkLoad(_TCScaleVMXenDesktopLifecycle):

    def prepare(self,arglist):

        guestNames = [name for name in xenrt.TEC().registry.guestList() if "clone" in name]
        self.guests = [xenrt.TEC().registry.guestGet(name) for name in  guestNames]
        self.cpuWorkload = "specjbb"
        self.workdir = "c:\\"
        self.jbbBase = "%s\\%s\\installed" % (self.workdir, self.cpuWorkload)
        self.jobFile = "SPECjbb.props"
        self.minheap = "300M"
        self.maxheap = "500M"

        self.errorMessages = []

    def run(self,arglist):

        threading.stack_size(65536)
        pWriteScript = [ xenrt.PTask(self.startCPUWorkLoadWrapper, guest) for guest in self.guests ]
        xenrt.pfarm(pWriteScript)

        #since cpu workload is a async call (xmlrpcStart) and in paralllel it will take somewhere around 30 mins thats why the sleep is quite high
        xenrt.sleep(3600)

        for guest in self.guests:
            self.getCPUWorkLoadResult(guest)

        if self.errorMessages:
            xenrt.TEC().logverbose(self.errorMessages)
            raise xenrt.XRTFailure("Failures occurred during cpu workload test, check logs for further information")


    def startCPUWorkLoadWrapper(self,guest):

        try:
            self.startCPUWorkLoad(guest)
        except Exception, e:
            errorMessage = "CPU_WORKLOAD FAILED on VM %s with error %s" % (guest.getName(),str(e))
            self.errorMessages.append(errorMessage)

    def startCPUWorkLoad(self, guest):

        guest.xmlrpcStart("cd %s\n"
                          "copy %s\\*.props .\n"
                          "xcopy %s\\xml xml /E /C /F /H /K /Y /I\n"
                          "set CLASSPATH=%s\\jbb.jar;"
                          "%s\\jbb_no_precompile.jar;"
                          "%s\\check.jar;%s\\reporter.jar;%%CLASSPATH%%\n"
                          "java -ms%s -mx%s spec.jbb.JBBmain -propfile %s"
                          % (self.workdir,
                             self.jbbBase,
                             self.jbbBase,
                             self.jbbBase,
                             self.jbbBase,
                             self.jbbBase,
                             self.jbbBase,
                             self.minheap,
                             self.maxheap,
                             self.jobFile))

#        #wait for 90 mins minutes
#       duration = 5400

#        # Unpack the test binaries
#        guest.xmlrpcUnpackTarball("%s/%s.tgz" %
#                          (xenrt.TEC().lookup("TEST_TARBALL_BASE"),
#                           self.cpuWorkload), self.workdir)

        # Start the test
#        id = guest.xmlrpcStart("%s\\prime95\\prime95.exe -T" % (self.workdir))
#        started = xenrt.timenow()
#        finishat = started + duration
#        time.sleep(30)
#        if guest.xmlrpcPoll(id):
#            raise xenrt.XRTError("prime95 did not start properly")

        # Wait for the specified duration
#        while finishat > xenrt.timenow():
#            if guest.xmlrpcPoll(id):
#                raise xenrt.XRTFailure("prime95 has stopped running")
#            time.sleep(30)

        # Kill it
#        guest.xmlrpcKillAll("prime95.exe")
#        time.sleep(30)
#        if not guest.xmlrpcPoll(id):
#            raise xenrt.XRTError("prime95 did not terminate properly")

    def getCPUWorkLoadResult(self,guest):

        try:
            #data = guest.xmlrpcReadFile("%s\\results\\SPECjbb.001.raw" % (self.workdir))
            #f = file("%s/%sSPECjbb_raw" % (xenrt.TEC().getLogdir(),guest.getName()), "w")
            #f.write(data)
            #f.close()
            data = guest.xmlrpcReadFile("%s\\results\\SPECjbb.001.results" %
                                        (self.workdir))
            f = file("%s/%sSPECjbb_results" % (xenrt.TEC().getLogdir(),guest.getName()), "w")
            f.write(data)
            f.close()

        except Exception, e:
            errorMessage = "CPU_WORKLOAD_GET_RESULT FAILED on VM %s with error %s" % (guest.getName(),str(e))
            self.errorMessages.append(errorMessage)

class TC18494(_Scalability):
    """Verify maximum supported limit for local physical disk size"""
    VDIs = []
    def runTC(self, host):
        #we're testing for this size (in bytes), variable read in from sequence file
        sizeToTest = int(float(host.lookup("LOCAL_DISK_TiB", "6")) *  2**40)
        #total disk size in bytes
        disksize = 0
        for ds in host.getLocalDiskSizes().values():
            disksize += ds
        if disksize < sizeToTest:
            raise xenrt.XRTError("The local disk (%s bytes) is smaller than the size we are testing (%s bytes)." %
                                    (disksize, sizeToTest))
        #get the local sr and its size
        localSr = host.getLocalSR()
        localSRSize = int(host.getSRParam(localSr, "physical-size"))
        #XenServer seems to allocate 8GB for itself and report rest as local SR
        #However, after Dom0 changes, XS allocates itself around 41GB disk space and reports rest as local SR
        #Add 8GiB to local SR size and compare to the actual size obtained in previous step
        if isinstance(host, xenrt.lib.xenserver.DundeeHost):
            expectedSrSize = disksize - 42 * xenrt.GIGA
        else:
            expectedSrSize = disksize - 8 * xenrt.GIGA
        #About 20MB seems to be the overhead (maybe LVM overhead). Subtract 20MiB from expected size too
        expectedSrSize = expectedSrSize - 20 * xenrt.MEGA
        if localSRSize < expectedSrSize:
            raise xenrt.XRTFailure("XenServer reported Local SR size to be %s bytes. The expected size is %s bytes.)" %
                                    (localSRSize, expectedSrSize))

        #to make sure the disk is usable, let's fill up the free space by creating VDIs
        #VDI size has been chosen to be 100 GiB arbitrarily
        srFreeSpace = localSRSize - int(host.getSRParam(localSr, "physical-utilisation"))
        log("%u bytes free in local SR. Creating VDIs to fill it up." % srFreeSpace)
        #create VDIs until we have only 500MB left (xapi throws error when we use 100% free space to create VDIs)
        diskToUse = srFreeSpace - 500 * xenrt.MEGA
        vdiSize = 100 * xenrt.GIGA

        try:
            while diskToUse > 0:
                if diskToUse >= vdiSize:
                    currentVdiSize = vdiSize
                else:
                    currentVdiSize = diskToUse
                log("Creating VDI of size %u bytes." % currentVdiSize)
                vdiuuid = host.createVDI(currentVdiSize, localSr)
                self.VDIs.append(vdiuuid)
                srFreeSpace = localSRSize - int(host.getSRParam(localSr, "physical-utilisation"))
                diskToUse = srFreeSpace - 500 * xenrt.MEGA
        except xenrt.XRTFailure, e:
            raise xenrt.XRTError("Failed to create VDI while trying to fill up local disk %s" %
                                    (e))

        # Create a guest which we'll use to clone (we hope that the default SR
        # is not the one we've just filled or all will go wrong!)
        guest = host.createGenericLinuxGuest()
        self.uninstallOnCleanup(guest)

        guest.preCloneTailor()
        guest.shutdown()

        # Determine how many VBDs we can add to the guest
        vbddevices = host.genParamGet("vm",
                                      guest.getUUID(),
                                      "allowed-VBD-devices").split("; ")
        vbdsAvailable = len(vbddevices)

        # Start adding VBDs and plugging VDIs into them, once we reach allowed
        # VBDs, make a new clone and continue
        currentGuest = guest.cloneVM()
        self.guests.append(currentGuest)
        self.uninstallOnCleanup(currentGuest)
        currentGuest.start()
        vmCount = 1
        pluggedCount = 0
        leftOnGuest = vbdsAvailable
        vdiConcurrent = len(self.VDIs)
        for i in range(vdiConcurrent):
            if leftOnGuest == 0:
                try:
                    if vmCount > 0 and vmCount % 20 == 0:
                        # CA-19617 Perform a vm-copy every 20 clones
                        guest = guest.copyVM()
                        self.uninstallOnCleanup(guest)
                    g = guest.cloneVM()
                    self.uninstallOnCleanup(g)
                    g.start()
                    vmCount += 1
                    currentGuest = g
                    self.guests.append(currentGuest)
                    leftOnGuest = vbdsAvailable
                except xenrt.XRTFailure, e:
                    # This isn't a failure of the testcase, but does mean we
                    # can't fully test so raise an error (i.e. we need to use a
                    # better provisioned host!)
                    raise xenrt.XRTError("Failed to create VM %u (%s) required "
                                         "for testing maximum number of VDIs" %
                                         (vmCount+1,e))

            try:
                currentGuest.createDisk(vdiuuid=self.VDIs[i])
                pluggedCount += 1
                leftOnGuest -= 1
            except xenrt.XRTFailure, e:
                xenrt.TEC().comment("Failed to create/plug VBD for VDI %u: %s" %
                                    (pluggedCount+1,e))
                break

        #verify host health
        host.verifyHostFunctional(migrateVMs=True)
        # Perform some lifecycle operations to check guest health
        if self.runSubcase("lifecycleOperations", (), "LifecycleOperations", "LifecycleOperations") != xenrt.RESULT_PASS:
            return

class TCStbltyWorkLoadBase(_Stability):
    """Base class for performing workload testcases."""

    WORKLOAD_TYPE = "default"
    WORKLOAD_FILENAME_SUFFIX = "default"

    def getOrderedSlaves(self):
        """Returns a list of ordered slave objects"""

        orderedSlaves = sorted(self.pool.getSlaves(), key=lambda k: k.getName())

        if len(orderedSlaves) < 2:
            raise xenrt.XRTError("Insufficient number of slaves. Required a minimum of 2, but found %d only" %
        #    xenrt.TEC().logverbose("Insufficient number of slaves. Required a minimum of 2, but found %d only" %
                                                                                                len(orderedSlaves))
        return orderedSlaves

    def getOrderedGuests(self, slaveHost):
        """Returns list of all ordered guest objects from a selected slave host"""

        orderedGuests = sorted(slaveHost.guests.values(), key=lambda k: k.getName())

        if len(orderedGuests) < 2:
            raise xenrt.XRTError("Insufficient number of guests. Required a minimum of 2, but found %d only" %
                                                                                                len(orderedGuests))
        return orderedGuests

    def startDiskWorkload(self):

        # Using XML-RPC to copy and execute the script that generates disk workloads.
        lsd = xenrt.TEC().lookup("LOCAL_SCRIPTDIR")
        self.guestForWorkload.xmlrpcSendFile("%s/remote/diskworkload.py" % (lsd), "c:\\diskworkload.py")
        self.guestForWorkload.xmlrpcStart("c:\\diskworkload.py c:\\diskworkload.perf c:\\diskworkload.pid c:\\diskworkload.data 100")

    def stopDiskWorkloadAndRetrieveLogs(self):

        # Stop the disk workload script on the guest by killing the process using XML-RPC.
        pid = string.strip(self.guestForWorkload.xmlrpcReadFile("c:\\diskworkload.pid"))
        self.guestForWorkload.xmlrpcKill(int(pid))

        # Now read the logfile
        try:
            diskworkloadFile = self.guestForWorkload.xmlrpcReadFile("c:\\diskworkload.perf")
            f = file("%s/diskworkload_during_%s.log" %
                                    (xenrt.TEC().getLogdir(), self.WORKLOAD_FILENAME_SUFFIX), 'a')
            f.write(str(diskworkloadFile))
            f.close()
        except Exception, e:
            raise xenrt.XRTError("Error retrieving disk workload log from VM %s: %s" %
                                                            (self.guestForWorkload.getName(),str(e)))

        # Cleanup
        self.guestForWorkload.xmlrpcExec("del c:\\diskworkload.perf")
        self.guestForWorkload.xmlrpcExec("del c:\\diskworkload.pid")
        self.guestForWorkload.xmlrpcExec("del c:\\diskworkload.data")
        self.guestForWorkload.xmlrpcExec("del c:\\diskworkload.py")

    def startCPUWorkload(self):

        # Install and start CPU workloads.
        self.guestForWorkload.installWorkloads(["Prime95"])
        self.guestForWorkload.startWorkloads(["Prime95"])
        xenrt.sleep(30)

    def stopCPUWorkloadAndRetrieveLogs(self):

        # Terminate CPU workloads and retreive logs.
        self.guestForWorkload.stopWorkloads(["Prime95"])
        xenrt.sleep(30)
        # If stopWorkloads fails to stop the workload, retrieve logs anyway.
        #self.guestForWorkload.retrieveWorkloads(["Prime95"])

    def startWorkload(self):

        # Start the workloads.
        xenrt.TEC().logverbose("Starting the %s-bound workload on guest %s" %
                                (self.WORKLOAD_TYPE, self.guestForWorkload.getName()))
        if self.WORKLOAD_TYPE == "DISK":
            self.startDiskWorkload()
        elif self.WORKLOAD_TYPE == "CPU":
            self.startCPUWorkload()
        else:
            raise xenrt.XRTError("Invalid workload type: %s" % self.WORKLOAD_TYPE)

    def stopWorkload(self):

        # Stop the workloads and retrieve the logs.
        xenrt.TEC().logverbose("Terminating %s-bound workload to retrieve the performance logs from guest %s" %
                                                                (self.WORKLOAD_TYPE, self.guestForWorkload.getName()))
        if self.WORKLOAD_TYPE == "DISK":
            self.stopDiskWorkloadAndRetrieveLogs()
        elif self.WORKLOAD_TYPE == "CPU":
            self.stopCPUWorkloadAndRetrieveLogs()
        else:
            raise xenrt.XRTError("Invalid workload type: %s" % self.WORKLOAD_TYPE)

    def prepare(self, arglist=[]):

        _Stability.prepare(self, arglist)

        for arg in arglist:
            if arg.startswith('workloadtype'):
                self.WORKLOAD_TYPE = arg.split('=')[1]

        # Identify the slave for running the workloads
        self.slaveForWorkload = self.getOrderedSlaves()[0]

        xenrt.TEC().logverbose("Selected slave for running the workloads is %s" %
                                                        self.slaveForWorkload.getName())

        # Identify the guest for running the workloads in above slave.
        self.guestForWorkload = self.getOrderedGuests(self.slaveForWorkload)[0]

        xenrt.TEC().logverbose("Selected guest for running the workloads is %s" %
                                                        self.guestForWorkload.getName())

        # Start the workloads.
        self.startWorkload()

    def run(self, arglist=[]):

        _Stability.run(self, arglist)

        # Stop the workloads and retrieve the logs.
        self.stopWorkload()

class TCStbltyMasterRebootOnly(TCStbltyWorkLoadBase):
    """Pool master reboot for 16 hosts running 800 guests with workloads"""

    WORKLOAD_FILENAME_SUFFIX = "master_reboot"

    def setHostsToBoot(self):
        self.hostsToBoot = [self.pool.master]

class TCStbltyOneSlaveReboot(TCStbltyWorkLoadBase):
    """Single slave reboot for a pool of 16 hosts running 800 guests with workloads"""

    WORKLOAD_FILENAME_SUFFIX = "one_slave_reboot"

    def setHostsToBoot(self):
        # Reboot any one slave which is not used for installing VM workloads.
        self.hostsToBoot = [self.getOrderedSlaves()[1]] # returns all slaves including the slave where a guest with running workloads.

class TCStbltyAllSlaveRebootExceptOne(TCStbltyWorkLoadBase):
    """Many slave reboot for a pool of 16 hosts running 800 guests with workloads"""

    WORKLOAD_FILENAME_SUFFIX = "all_slave_reboot_except_one"

    def setHostsToBoot(self):
        self.hostsToBoot = self.getOrderedSlaves()[1:] # returns all slaves including the slave where a guest with running workloads.

class TCScaleVMXenDesktop49Reboot(TCStbltyWorkLoadBase):
    """Many guests reboot for a pool of 16 hosts running 800 guests with workloads"""

    ITERATIONS = 1
    THREADS = 5
    WORKLOAD_FILENAME_SUFFIX = "49_guests_reboot"

    def prepare(self, arglist=None):
        # Get the sequence variables
        for arg in arglist:
            if arg.startswith('threads'):
                self.THREADS = int(arg.split('=')[1])
            if arg.startswith('iterations'):
                self.ITERATIONS = int(arg.split('=')[1])
            if arg.startswith('workloadtype'):
                self.WORKLOAD_TYPE = arg.split('=')[1]

        # Get the pool and hosts
        self.pool = self.getDefaultPool()
        self.hosts = self.pool.getHosts()

        # Identify the slave for running the workloads
        self.slaveForWorkload = self.getOrderedSlaves()[0]

        xenrt.TEC().logverbose("Selected slave for running the workloads is %s" %
                                                        self.slaveForWorkload.getName())

        # Identify the guest for running the workloads in above slave.
        self.guestForWorkload = self.getOrderedGuests(self.slaveForWorkload)[0]

        xenrt.TEC().logverbose("Selected guest for running the workloads is %s" %
                                                        self.guestForWorkload.getName())

        # Start the workloads.
        self.startWorkload()

    def run(self, arglist):
        threading.stack_size(65536)

        # Find all the guests, except the one used for installing workloads.
        vms = self.getOrderedGuests(self.slaveForWorkload)[1:]

        self.doVMOperations(vms, self.THREADS, self.ITERATIONS)

        # Stop the workloads and retrieve the logs.
        self.stopWorkload()

    # Concrete test case to reboot all of the VMs, XenDesktop Style
    def doOperation(self, vm, gold):
        self.xenDesktopShutdown(vm)
        self.xenDesktopStart(vm, gold)

class _VBDScalability(_Scalability):

    vdis = []
    VALIDATE = False

    def runTC(self,host):
        self.cli = host.getCLIInstance()
        if self.MAX == True:
            maxVbds = int(host.lookup("MAX_VBDS_PER_HOST"))
        else:
            maxVbds = self.MAX
        xenrt.TEC().logverbose("MAX VBDS PER HOST is %s" %(maxVbds))

        vdiPerVM = int(host.lookup("MAX_VDIS_PER_VM")) + 1
        xenrt.TEC().logverbose("MAX VDIs per VM is %s " %(vdiPerVM))

        # Find the SR
        srs = host.getSRs(type=self.SR)
        if len(srs) == 0:
            raise xenrt.XRTError("Couldn't find a %s SR" % (self.SR))

        maxVdis = int(host.lookup("MAX_VDIS_PER_SR_%s" % (self.SR)))

        srCount = 0
        vdiCount = 0
        vdiPerSrCount = 0
        while vdiCount < vdiPerVM and srCount<len(srs):
            try:
                uuid = host.createVDI(sizebytes=10485760, sruuid=srs[srCount], name="VDI Scalability %u" %(vdiCount))
                self.vdis.append(uuid)
                vdiPerSrCount += 1
                vdiCount += 1
                if vdiPerSrCount >= 600:
                    srCount += 1
                    vdiPerSrCount = 0
            except xenrt.XRTFailure, e:
                psize = int(host.getSRParam(srs[srCount],"physical-size"))
                if psize > 0:
                    spaceleft = psize - \
                                int(host.getSRParam(srs[srCount],"physical-utilisation"))
                    if spaceleft < 10485760:
                        xenrt.TEC().warning("Ran out of space on SR, required "
                                             "10485760, had %u" % (spaceleft))
                        srCount = srCount+1
                        vdiPerSrCount = 0

        for sr in srs:
            # See how long an sr-scan takes
            try:
                t = xenrt.util.Timer()
                t.startMeasurement()
                self.cli.execute("sr-scan","uuid=%s" % (sr))
                t.stopMeasurement()
                xenrt.TEC().value("sr-scan",t.max())
            except xenrt.XRTFailure, e:
                xenrt.TEC().warning("Exception while performing sr-scan: %s" % (e))

        srCount = 0
        guest = host.createGenericLinuxGuest(sr = srs[srCount])
        self.uninstallOnCleanup(guest)

        guest.preCloneTailor()
        guest.shutdown()

        # Determine how many VBDs we can add to the guest
        vbddevices = host.genParamGet("vm",
                                       guest.getUUID(),
                                       "allowed-VBD-devices").split("; ")
        vbdsAvailable = len(vbddevices)
        guest.start()

        i = 0
        vmNumbers = (int ( maxVbds / vdiPerVM )) + 1
        while (vbdsAvailable > 0) :
            try:
                device = guest.createDisk(vdiuuid=self.vdis[i],returnDevice=True)
                i += 1
                vbdsAvailable -= 1
            except xenrt.XRTFailure, e:
                 xenrt.TEC().comment("Failed to create Disks")

        guest.shutdown()
        self.guests.append(guest)

        vmCount = 1

        while (vmNumbers > 1) :
            try:
                g = guest.cloneVM()
                self.uninstallOnCleanup(g)
                self.guests.append(g)
                vmNumbers -= 1
            except xenrt.XRTFailure, e:
                xenrt.TEC().comment("Failed to clone a VM")

        pluggedCount = 0
        for vmClone in self.guests:
            vmClone.start()
            vmCount += 1
            vbdUuids = self.host.minimalList("vbd-list",args="vm-uuid=%s" % (vmClone.getUUID()))

            for vbdClone in vbdUuids :
                vbdFormat = self.host.genParamGet("vbd", vbdClone, "device")
                if vbdFormat == 'xvda' :
                    pluggedCount += 1
                    continue
                try:
                    xenrt.TEC().logverbose("Formatting VDI within VM.")
                    vmClone.execguest("mkfs.ext3 /dev/%s" % (vbdFormat))
                    vmClone.execguest("mount /dev/%s /mnt" % (vbdFormat))
                    xenrt.TEC().logverbose("Creating some random data on VDI.")
                    vmClone.execguest("dd if=/dev/zero of=/mnt/random oflag=direct bs=1M count=8")
                    vmClone.execguest("umount /mnt")

                    pluggedCount += 1
                    xenrt.TEC().logverbose("Plugged VBD %s" %(pluggedCount))
                except xenrt.XRTFailure, e:
                    xenrt.TEC().comment("Failed to create/plug VBD")
                    break

        if pluggedCount < maxVbds:
            xenrt.TEC().logverbose("Plugged VBD %s" %(pluggedCount))
            raise xenrt.XRTFailure("Only able to create/plug "
                                    "VBDs for %u on %u guests" %
                                    (pluggedCount,vmCount))

        if self.VALIDATE:
                if self.runSubcase("lifecycleOperations", (), "LifecycleOperations", "LifecycleOperations") != xenrt.RESULT_PASS:
                    return

    def parseArgument(self,param,value):
        if param == "max":
            self.MAX = value
        else:
            _Scalability.parseArgument(self,param,value)

    def postRun2(self):
        # Delete the VDIs
        for vdi in self.vdis:
            try:
                self.cli.execute("vdi-destroy uuid=%s" % (vdi))
            except:
                xenrt.TEC().warning("Exception destroying VDI %s" % (vdi))

class TC21482(_VBDScalability):

    """Verify the supported maximum number of VBD's per Host can be created and attached (NFS)"""

    SR = "nfs"
    MAX = True
    VALIDATE = True

class TC26977(_VDIScalability):
    """Verify the supported maximum number of VDIs per SR can be created and attached (CIFS)"""
    SR = "smb"
    MAX = True
    CONCURRENT = True
    VALIDATE = True
