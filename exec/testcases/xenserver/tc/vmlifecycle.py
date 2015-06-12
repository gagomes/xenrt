#
# XenRT: Test harness for Xen and the XenServer product family
#
# VM lifecycle standalone testcases
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy, calendar
import xenrt, xenrt.util, xenrt.lib.xenserver, testcases.guestops.vmtime
from xenrt.lazylog import step, comment, log, warning
import testcases.xenserver.tc.guest

def _setVCPUMax(guest):

    guest.setState("DOWN")
    guest.paramSet("VCPUs-max", guest.getMaxSupportedVCPUCount())

    # Even if the VM was shutdown before this function was called, it is powered on
    guest.setState("UP")

class _NoNICBase(xenrt.TestCase):

    def gmlastupdate(self, timeout=120):
        start = time.time()
        while True:
            try:            
                mtime = self.host.genParamGet("vm",
                                               self.guest.getUUID(),
                                              "guest-metrics-last-updated")
                mtime = time.strptime(mtime, 
                                     "%Y%m%dT%H:%M:%SZ")
                break
            except:
                if start + timeout > time.time():
                    time.sleep(5)
                else:
                    raise xenrt.XRTFailure("Metrics weren't updated.")
        return time.mktime(mtime)

    def createGuest(self):
        raise xenrt.XRTError("Unimplemented.") 
    
    def run(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guest = self.createGuest()
        omtime = self.gmlastupdate()
        self.guest.shutdown()
        for v in self.guest.getVIFs().keys():
            xenrt.TEC().logverbose("Removing %s." % (v))
            self.guest.removeVIF(v)
        self.guest.lifecycleOperation("vm-start")
        self.guest.poll("UP", pollperiod=5)
        mtime = self.gmlastupdate(timeout=300)
        if mtime <= omtime:
            raise xenrt.XRTFailure("Guest metrics weren't updated. (%s, %s)" % 
                                   (omtime, mtime))
       
    def postRun(self): 
        try:
            self.guest.lifecycleOperation("vm-shutdown")
        except:
            pass
        try:
            self.guest.uninstall()
        except:
            pass

class TC8045(_NoNICBase):
    
    def createGuest(self):
        return self.host.createGenericLinuxGuest()

class TC8044(_NoNICBase):

    def createGuest(self):
        return self.host.createGenericWindowsGuest()

class _ClockStability(xenrt.TestCase):

    VMNAME = None

    def prepare(self, arglist):
        self.guest = self.getGuest(self.VMNAME)

    def run(self, arglist):
        self.idle = 7200 # 2 hours. 
        self.margin = 30        

        try:
            self.guest.xmlrpcExec("sc stop w32time")
            self.guest.xmlrpcExec("w32tm /unregister")
        except:
            pass

        bskew = self.guest.getClockSkew()
        xenrt.TEC().logverbose("Guest reported skew before sleep: %s" % (bskew))

        xenrt.TEC().logverbose("Sleeping for %s seconds..." % (self.idle))
        time.sleep(self.idle)

        askew = self.guest.getClockSkew()
        xenrt.TEC().logverbose("Guest reported skew after sleep: %s" % (askew))

        if abs(askew - bskew) > self.margin:
            raise xenrt.XRTFailure("Skew increased too much during sleep.")

class TC8257(_ClockStability):
    """Clock stability of Windows Server 2003 EE SP2 (idle VM)"""

    VMNAME = "w2k3eesp2"

class TC8258(_ClockStability):
    """Clock stability of Windows Server 2003 EE SP2 x64 (idle VM)"""

    VMNAME = "w2k3eesp2-x64"

class TC8259(_ClockStability):
    """Clock stability of Windows Server 2008 (idle VM)"""

    VMNAME = "ws08sp2-x86"

class TC8260(_ClockStability):
    """Clock stability of Windows Server 2008 x64 (idle VM)"""

    VMNAME = "ws08sp2-x64"

class TC9716(_ClockStability):
    """Clock stability of Windows Server 2008 R2 x64 (idle VM)"""

    VMNAME = "ws08r2sp1-x64"
    
class _ClockSkewBase(xenrt.TestCase):

    def __init__(self, tcid=None, anon=False):
        xenrt.TestCase.__init__(self, tcid=tcid, anon=anon)
        self.guest = None

    def setup(self):
        pass

    def run(self, arglist=None):
        # 4 1/2 hours.
        self.skew = 16200
        self.margin = 120
        self.loops = 20 

        self.host = self.getDefaultHost()
        self.setup()
        
        for i in range(self.loops):
            xenrt.TEC().logverbose("Starting suspend/resume iteration %s." % (i))
            self.guest.suspend()
            self.guest.resume()
            gtime = time.gmtime(self.guest.getTime())
            xenrt.TEC().logverbose("Current guest time: %s" % 
                                   (time.strftime("%c", gtime)))
            atime = time.gmtime(time.time())
            xenrt.TEC().logverbose("Current controller time: %s" % 
                                   (time.strftime("%c", atime)))
            currentskew = self.guest.getClockSkew()
            xenrt.TEC().logverbose("Current clock skew: %ss" % (currentskew))
            if abs(currentskew - self.skew) > self.margin:
                xenrt.TEC().logverbose("Difference in skews since initial "
                                       "setup %ss" %
                                       (abs(currentskew - self.skew)))
                raise xenrt.XRTFailure("Difference in VM clock skew from "
                                       "before test to now is out of limits")

class TC8004(_ClockSkewBase):

    def setup(self):
        self.distro = "w2k3eesp2"
        self.guest = xenrt.lib.xenserver.guest.createVM(self.host,
                                                        xenrt.randomGuestName(),
                                                        distro=self.distro,
                                                        vifs=[("0",
                                                                self.host.getPrimaryBridge(),
                                                                xenrt.util.randomMAC(),
                                                                None)])
        self.uninstallOnCleanup(self.guest)
        self.guest.installDrivers()
        # Disable NTP, if it's running.
        try:
            self.guest.xmlrpcExec("sc stop w32time")
            self.guest.xmlrpcExec("w32tm /unregister")
        except:
            pass
        gtime = time.gmtime(self.guest.getTime())
        xenrt.TEC().logverbose("Current guest time: %s" % (time.strftime("%c", gtime)))
        atime = time.gmtime(time.time())
        xenrt.TEC().logverbose("Current controller time: %s" % (time.strftime("%c", atime)))
        newtime = time.gmtime(calendar.timegm(atime) + self.skew)
        xenrt.TEC().logverbose("Setting time to %s." % (time.strftime("%c", newtime)))
        self.guest.xmlrpcExec("echo %s | date" % (time.strftime("%m-%d-%y", newtime)))
        self.guest.xmlrpcExec("echo %s | time" % (time.strftime("%H:%M:%S", newtime)))
        gtime = time.gmtime(self.guest.getTime())
        xenrt.TEC().logverbose("New guest time: %s" % (time.strftime("%c", gtime)))
        
class TC7481(xenrt.TestCase):
    """Graceful failure of a VM to reboot when it's memory has been increased to more than available"""

    def run(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guest = xenrt.lib.xenserver.guest.createVM(self.host,
                                                        xenrt.randomGuestName(),
                                                        distro="w2k3eesp2",
                                                        vifs=[("0",
                                                                self.host.getPrimaryBridge(),
                                                                xenrt.util.randomMAC(),
                                                                None)])
        self.guest.installDrivers()

        hmem = self.host.getTotalMemory()
        xenrt.TEC().logverbose("Host appears to have %sMb of memory." % (hmem))
        xenrt.TEC().progress("Setting guest memory to %sMb." % (hmem + 8))
        self.guest.memset(hmem + 8)
        self.guest.xmlrpcReboot()
        xenrt.TEC().logverbose("Waiting for VM to shutdown.")
        time.sleep(180)
        xenrt.TEC().logverbose("Guest state is: %s" % (self.guest.getState()))
        if self.guest.getState() != "DOWN":
            raise xenrt.XRTFailure("Guest is not halted.")

    def postRun(self):
        try:
            self.guest.shutdown()
        except:
            pass
        try:
            self.guest.uninstall()
        except:
            pass

class _TC6860(xenrt.TestCase):
    guest = None

    def suspendresume(self, workloads):
        if workloads:
            workloadsExecd = self.guest.startWorkloads()

        loops = int(xenrt.TEC().lookup("VMLIFECYCLE_ITERS", "10"))
        st = xenrt.Timer()
        rt = xenrt.Timer()
        success = 0
        try:
            for i in range(loops):
                xenrt.TEC().logdelimit("loop iteration %u..." % (i))
                self.guest.host.listDomains()
                self.guest.suspend(timer=st)
                self.guest.host.checkHealth()
                self.guest.host.listDomains()
                self.guest.resume(timer=rt)
                self.guest.host.checkHealth()
                success += 1
                if xenrt.GEC().abort:
                    xenrt.TEC().warning("Aborting on command")
                    break
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" %
                                (success,loops))
            if st.count() > 0:
                xenrt.TEC().logverbose("Suspend times: %s" % (st.measurements))
                xenrt.TEC().value("SUSPEND_MAX", st.max())
                xenrt.TEC().value("SUSPEND_MIN", st.min())
                xenrt.TEC().value("SUSPEND_AVG", st.mean())
                xenrt.TEC().value("SUSPEND_DEV", st.stddev())
            if rt.count() > 0:
                xenrt.TEC().logverbose("Resume times: %s" % (rt.measurements))
                xenrt.TEC().value("RESUME_MAX", rt.max())
                xenrt.TEC().value("RESUME_MIN", rt.min())
                xenrt.TEC().value("RESUME_AVG", rt.mean())
                xenrt.TEC().value("RESUME_DEV", rt.stddev())
        if workloads:
            self.guest.stopWorkloads(workloadsExecd)
        self.guest.check()

    def installVM(self, host):
        raise xenrt.XRTError("Unimplemented")

    def run(self, arglist):

        # Get a host to install on
        host = self.getDefaultHost()

        # Install the VM
        self.installVM(host)
        self.uninstallOnCleanup(self.guest)

        # Perform suspend/resume tests
        if self.runSubcase("suspendresume", (0), "SuspendResume", "Idle") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("suspendresume", (1), "SuspendResume", "Loaded") != \
                xenrt.RESULT_PASS:
            return

        # Shutdown the VM
        self.guest.shutdown()
        
class TC6860(_TC6860):
    """Suspend and resume a PV Linux VM"""

    def installVM(self, host):
        # Install a basic Linux VM
        self.guest = host.createGenericLinuxGuest()

class TC17438(_TC6860):
    """ Suspend/Resume of a sles 11.1 with "VCPUs-max > VCPU """
    xenrt.TEC().config.setVariable("VMLIFECYCLE_ITERS", "1")
    def installVM(self, host):
        self.guest = host.createBasicGuest(distro="sles112")
        _setVCPUMax(self.guest)

class TC6861(_TC6860):
    """Suspend and resume a Windows VM"""
    
    def installVM(self, host):
        # Install a Windows VM
        self.guest = host.createGenericWindowsGuest()

class _TC6869(xenrt.TestCase):
    guest = None

    def migrate(self, workloads, live):
        if workloads:
            workloadsExecd = self.guest.startWorkloads()

        loops = int(xenrt.TEC().lookup("VMLIFECYCLE_ITERS", "10"))
        success = 0
        try:
            for i in range(loops):
                xenrt.TEC().logdelimit("loop iteration %u..." % (i))
                self.guest.host.listDomains()
                self.guest.migrateVM(self.guest.host, live=live)
                self.guest.host.checkHealth()
                success += 1
                if xenrt.GEC().abort:
                    xenrt.TEC().warning("Aborting on command")
                    break
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" %
                                (success,loops))
        if workloads:
            self.guest.stopWorkloads(workloadsExecd)
        self.guest.check()

    def installVM(self, host):
        raise xenrt.XRTError("Unimplemented")

    def run(self, arglist):

        # Get a host to install on
        host = self.getDefaultHost()

        # Install the VM
        self.installVM(host)
        self.uninstallOnCleanup(self.guest)

        # Perform XenMotion tests
        if self.runSubcase("migrate", (0, "false"), "XenMotion", "Idle") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("migrate", (1, "false"), "XenMotion", "Loaded") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("migrate", (0, "true"), "LiveXenMotion", "Idle") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("migrate", (1, "true"), "LiveXenMotion", "Loaded") != \
                xenrt.RESULT_PASS:
            return

        # Shutdown the VM
        self.guest.shutdown()
        
class TC6870(_TC6869):
    """Localhost XenMotion of a PV Linux VM"""

    def installVM(self, host):
        # Install a basic Linux VM
        self.guest = host.createGenericLinuxGuest()

class TC6869(_TC6869):
    """Localhost XenMotion of a Windows VM"""
    
    def installVM(self, host):
        # Install a Windows VM
        self.guest = host.createGenericWindowsGuest()

class TC17439(_TC6869):
    """ Xenmotion of a sles 11.1 with "VCPUs-max > VCPU """
    xenrt.TEC().config.setVariable("VMLIFECYCLE_ITERS", "1")
    def installVM(self, host):
        sr = None
        sruuids = host.getSRs()
        for sruuid in sruuids:
            if host.getSRParam(uuid=sruuid, param='type') == 'nfs':
                sr = sruuid
                break
        if sr: 
            self.guest = host.createBasicGuest(distro="sles111",sr=sr) 
        else:
            raise xenrt.XRTFailure("NFS SR not found on host")

        _setVCPUMax(self.guest)

class TC6862(_TC6860):
    """Suspend and resume of a VM with multiple virtual devices"""

    def installVM(self, host):
        # Install a basic Linux VM
        self.guest = host.createGenericLinuxGuest()

        device = host.genParamGet("vm",
                                  self.guest.getUUID(),
                                  "allowed-VBD-devices").split("; ")[0]
        self.guest.createDisk(sizebytes=20000000,
                              sruuid=host.getLocalSR(),
                              userdevice=device)
        device = "%s%d" % (self.guest.vifstem, 
                           int(host.genParamGet(
            "vm", self.guest.getUUID(), "allowed-VIF-devices").split("; ")[0]))
        mac = xenrt.randomMAC()
        bridge = host.getPrimaryBridge()
        self.guest.createVIF(device, bridge, mac)
        self.guest.plugVIF(device)

class _BlockedOperations(xenrt.TestCase):
    """Base class for testing blocking of VM operations."""

    GUEST = "blocking-test-1"
    CONTROL = "blocking-test-2"
    MULTIPLE = True
    PREPARE = "vm-shutdown"
    OPERATION = None
    APINAME = None

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.guest = self.getGuest(self.GUEST)
        self.control = None
        if not self.guest: 
            self.guest = self.host.createGenericLinuxGuest(name=self.GUEST)
            xenrt.TEC().registry.guestPut(self.guest.getName(), self.guest)
            self.guest.shutdown()
            self.guest.paramSet("VCPUs-max", str(self.guest.getMaxSupportedVCPUCount()))
        self.guest.paramClear("blocked-operations")
        try: self.guest.lifecycleOperation(self.PREPARE)
        except: pass
        if self.MULTIPLE: 
            self.control = self.getGuest(self.CONTROL)
            if not self.control:
                self.control = self.host.createGenericLinuxGuest(name=self.CONTROL)
                xenrt.TEC().registry.guestPut(self.control.getName(),
                                              self.control)
                self.control.shutdown()
                self.control.paramSet("VCPUs-max", str(self.guest.getMaxSupportedVCPUCount()))
            self.control.paramClear("blocked-operations")
            try: self.control.lifecycleOperation(self.PREPARE)
            except: pass
        # Wait for VMs to start or stop.
        time.sleep(60)

    def run(self, arglist):
        reason = "Blocked by XenRT."

        xenrt.TEC().logverbose("Blocking operation: %s" % (self.APINAME))
        self.guest.paramSet("blocked-operations:%s" % (self.APINAME), reason) 
        xenrt.TEC().logverbose("Attempting blocked operation: %s" % (self.OPERATION))
        try:
            self.guest.lifecycleOperation(self.OPERATION)
        except xenrt.XRTFailure, e:
            if not re.search("explicitly blocked", str(e)): 
                raise xenrt.XRTFailure("Action failed but with unexpected error: %s" % (str(e)))
            else:    
                xenrt.TEC().logverbose("Caught exception with proper error message.")
        else:
            raise xenrt.XRTFailure("Blocked operation succeeded.")

        if self.MULTIPLE: 
            xenrt.TEC().logverbose("Attempting the blocked operation on multiple hosts.")
            try:
                self.host.lifecycleOperationMultiple([self.guest, self.control],
                                                      self.OPERATION)
            except xenrt.XRTFailure, e:
                if not re.search("explicitly blocked", str(e)): raise
            else: 
                xenrt.TEC().logverbose("Caught exception with proper error message.")
                xenrt.TEC().logverbose("Error: %s" % (str(e)))
            xenrt.TEC().logverbose("Control is %s." % (self.control.getState()))
            xenrt.TEC().logverbose("Guest is %s." % (self.guest.getState()))
        xenrt.TEC().logverbose("Unblocking operation: %s" % (self.OPERATION))
        self.guest.paramRemove("blocked-operations", self.APINAME)
        xenrt.TEC().logverbose("Attempting operation after unblocking. (%s)" % (self.OPERATION))
        self.guest.lifecycleOperation(self.OPERATION)

    def postRun(self):
        for g in [self.guest, self.control]:
            if g:
                try:
                    # Unblock everything to make sure we can clean up
                    g.paramClear("blocked-operations")

                    if g.getState() == "SUSPENDED":
                        g.resume()
                    if g.getState() == "UP":
                        g.shutdown()
                except Exception, e:
                    xenrt.TEC().logverbose("Exception: %s" % (str(e)))

class TC8264(_BlockedOperations):
    """Check VM start can be blocked."""

    OPERATION = "vm-start"
    APINAME = "start"

class TC8265(_BlockedOperations):
    """Check VM stop can be blocked."""

    OPERATION = "vm-shutdown"
    APINAME = "clean_shutdown"
    PREPARE = "vm-start"

class TC8266(_BlockedOperations):
    """Check VM force stop can be blocked."""

    OPERATION = "vm-shutdown --force"
    APINAME = "hard_shutdown"
    PREPARE = "vm-start"

class TC8267(_BlockedOperations):
    """Check VM reboot can be blocked."""

    OPERATION = "vm-reboot"
    APINAME = "clean_reboot"
    PREPARE = "vm-start"

class TC8268(_BlockedOperations):
    """Check VM forced reboot can be blocked."""

    OPERATION = "vm-reboot --force"
    APINAME = "hard_reboot"
    PREPARE = "vm-start"

class TC8269(_BlockedOperations):
    """Check VM suspend can be blocked."""

    OPERATION = "vm-suspend"
    APINAME = "suspend"
    PREPARE = "vm-start"

    def postRun(self):
        try: self.guest.lifecycleOperation("vm-resume")
        except: pass
        _BlockedOperations.postRun(self)

class TC8270(_BlockedOperations):
    """Check VM pause can be blocked."""

    OPERATION = "vm-pause"
    APINAME = "pause"
    PREPARE = "vm-start"
    MULTIPLE = False

    def postRun(self):
        try: self.guest.lifecycleOperation("vm-unpause")
        except: pass
        _BlockedOperations.postRun(self)

class TC8271(_BlockedOperations):
    """Check VM vcpu-hotplug can be blocked."""

    OPERATION = "vm-vcpu-hotplug new-vcpus=4"
    APINAME = "changing_VCPUs_live"
    PREPARE = "vm-start"
    MULTIPLE = False

    def postRun(self):
        _BlockedOperations.postRun(self)
        try: self.guest.cpuset(1)
        except: pass

class TC8272(_BlockedOperations):
    """Check VM export can be blocked."""

    FILENAME = "/tmp/blocked-export"
    OPERATION = "vm-export filename=%s" % (FILENAME)
    APINAME = "export"
    MULTIPLE = False

    def postRun(self):
        _BlockedOperations.postRun(self)
        try: xenrt.command("rm -f %s" % (self.FILENAME))
        except: pass

class TC8273(_BlockedOperations):
    """Check VM destroy can be blocked."""
    
    OPERATION = "vm-destroy"
    APINAME = "destroy"
    MULTIPLE = False

class TC8274(_BlockedOperations):
    """Check turning a VM into a template can be blocked."""

    OPERATION = "vm-param-set is-a-template=true"
    APINAME = "make_into_template"
    MULTIPLE = False

    def postRun(self):
        _BlockedOperations.postRun(self)
        try: self.guest.paramSet("is-a-template", "false")
        except: pass

class TC8275(_BlockedOperations):
    """Check VM clone can be blocked."""

    NAME = "blocked-clone"
    OPERATION = "vm-clone new-name-label=%s" % (NAME)
    APINAME = "clone"
    MULTIPLE = False

    def postRun(self):
        _BlockedOperations.postRun(self)
        try:
            cli = self.host.getCLIInstance()
            cli.execute("vm-uninstall name-label=%s --force" % (self.NAME))
        except:
            pass

class TC8276(TC8275):
    """Check VM snapshot of a stopped VM can be blocked."""

    NAME = "blocked-snapshot"
    OPERATION = "vm-snapshot new-name-label=%s" % (NAME)
    APINAME = "snapshot"
    MULTIPLE = False 

class TC8277(TC8275):
    """Check VM snapshot of a running VM can be blocked."""

    NAME = "blocked-snapshot"
    OPERATION = "vm-snapshot new-name-label=%s" % (NAME)
    APINAME = "snapshot"
    MULTIPLE = False 
    PREPARE = "vm-start"

class TC8278(TC8275):
    """Check VM copy can be blocked."""

    NAME = "blocked-copy"
    OPERATION = "vm-copy new-name-label=%s" % (NAME)
    APINAME = "copy"
    MULTIPLE = False

class _GuestCrash(xenrt.TestCase):

    def __init__(self, tcid=None, anon=False):
        xenrt.TestCase.__init__(self, tcid=tcid, anon=anon)
        self.guest = None
        self.timeout = None

    def run(self, arglist):
        for s in ["Preserve", "Restart", "Destroy"]:
            self.runSubcase("checkCrash", s.lower(), "Guest", "Crash%s" % (s))
            try: self.guest.shutdown(again=True)
            except: pass
            self.guest.start()
            self.guest.check()

    def checkCrash(self, action):
        self.guest.paramSet("actions-after-crash", action)
        self.guest.shutdown()
        self.guest.start()

        # Wait 2 minutes to avoid being hit by the minimum_time_between_bounces
        # restriction which prevent fast boot loops. CA-32500
        time.sleep(120)

        crashAttempt = 1
        startDomid = self.guest.getDomid()
        while True:
            xenrt.TEC().logverbose("Crashing Guest %s, attempt %d" % (self.guest.getName(), crashAttempt))
            self.guest.crash()
            try: 
                self.guest.checkReachable(timeout=10, level=None)
                xenrt.TEC().logverbose("Guest %s, failed to crash on attempt %d" % (self.guest.getName(), crashAttempt))
            except:
                xenrt.TEC().logverbose("Guest %s, crashed on attempt %d" % (self.guest.getName(), crashAttempt))
                break
            if crashAttempt > 10:
                raise xenrt.XRTFailure("Guest failed to crash after %d attempts" % (crashAttempt))
            crashAttempt += 1

        xenrt.TEC().logverbose("Waiting %us after crash..." % (self.timeout))
        time.sleep(self.timeout)

        if action == "preserve":
            if not self.guest.getState() == "PAUSED":
                raise xenrt.XRTFailure("Guest not found in a paused state.")
        elif action == "restart":
            try: self.guest.checkReachable(timeout=600)
            except:
                raise xenrt.XRTFailure("Guest doesn't appear to have restarted.")
            if self.guest.getDomid() == startDomid:
                raise xenrt.XRTFailure("Guest doesn't appear to have restarted.",
                                       "Domid unchanged since before crash (%s)" % (startDomid))
        elif action == "destroy":
            if not self.guest.getState() == "DOWN":
                raise xenrt.XRTFailure("Guest wasn't destroyed.")
        else:
            raise xenrt.XRTError("Unknown action %s" % (action))

class TC8312(_GuestCrash):
    """Windows crash recovery"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericWindowsGuest()
        self._guestsToUninstall.append(self.guest)
        self.guest.xmlrpcExec("bcdedit /set {default} nocrashautoreboot false")
        self.guest.winRegAdd("HKLM",
                             "SYSTEM\\CurrentControlSet\\Control\\CrashControl",
                             "AutoReboot",
                             "DWORD",
                             1)
        self.guest.reboot()
        self.timeout = 300
        
        # Using CA-40368 workaround
        data = self.host.execdom0("dmidecode")
        if "IBM System x3550" in data:
            self.timeout = 180

class TC8313(_GuestCrash):
    """Linux crash recovery"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        #self.guest = self.host.createGenericLinuxGuest()
        distro = self.host.lookup("GENERIC_LINUX_OS_64", "centos57")
        self.guest = self.host.createBasicGuest(distro,name="Centos57-forTC8313")
        self._guestsToUninstall.append(self.guest)
        self.timeout = 60
        
class TC9314(testcases.guestops.vmtime.TCGuestTimeOffsetMig):
    """Windows VM with an offset clock should retain the offset across a live migrate"""

    def provideGuest(self, arglist):
        g = self.getDefaultHost().createGenericWindowsGuest()
        self.uninstallOnCleanup(g)
        return g
    
class _TCXenMotionNonLocal(xenrt.TestCase):

    VCPUS = None
    MEMORY = None
    ARCH = "x86-32"
    DISTRO = None
    VARCH = None
    TESTMODE = False

    LOOPITERS = 300

    def checkHostIsSuitable(self, host):
        pass

    def prepare(self, arglist=None):
        
        # Get a host to install on
        self.host = self.getDefaultHost()

        # Make sure we have a pool, use a slave as the peer
        if self.TESTMODE:
            self.peer = self.host
        else:
            if not self.host.pool:
                raise xenrt.XRTError("This test needs to run on a pool")
            self.host = self.host.pool.master
            if len(self.host.pool.getSlaves()) == 0:
                raise xenrt.XRTError("Pool has no slaves")
            self.peer = self.host.pool.getSlaves()[0]
            self.getLogsFrom(self.peer)
        self.checkHostIsSuitable(self.host)
        self.checkHostIsSuitable(self.peer)

        if self.VARCH == "VMX" and not self.host.isVmxHardware():
            raise xenrt.XRTError("Not running on VMX hardware")
        if self.VARCH == "VMXHAP" and not self.host.isVmxHardware():
            raise xenrt.XRTError("Not running on VMX hardware")
        if self.VARCH == "SVM" and not self.host.isSvmHardware():
            raise xenrt.XRTError("Not running on SVM hardware")
        if self.VARCH == "SVMHAP" and not self.host.isSvmHardware():
            raise xenrt.XRTError("Not running on SVM hardware")

        self.guest = xenrt.lib.xenserver.guest.createVM(\
            self.host,
            xenrt.randomGuestName(),
            self.DISTRO,
            vcpus=self.VCPUS,
            memory=self.MEMORY,
            vifs=xenrt.lib.xenserver.Guest.DEFAULT,
            arch=self.ARCH)
        self.getLogsFrom(self.guest)
        self.uninstallOnCleanup(self.guest)
        if self.guest.windows:
            self.guest.installDrivers()

    def doMigrate(self, workloads):
   
        # Do we have any workloads to start?
        if workloads:
            if self.guest.windows:
                workloadsExecd = self.guest.startWorkloads()
            else:
                workloadsExecd = self.guest.startWorkloads()

        # Do the loop
        success = 0
        try:
            for i in range(self.LOOPITERS):
                xenrt.TEC().logdelimit("loop iteration %u..." % (i))

                # First migrate from master to slave
                self.guest.migrateVM(self.peer, live="true")

                # Then back to the master
                self.guest.migrateVM(self.host, live="true")

                # Wait a bit (we get alternating short and long gaps between
                # migrates)
                time.sleep(15)

                success += 1
                if xenrt.GEC().abort:
                    xenrt.TEC().warning("Aborting on command")
                    break
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" %
                                (success, self.LOOPITERS))

        # Stop the workloads
        if workloads:
            self.guest.stopWorkloads(workloadsExecd)

    def run(self, arglist):
        
        doworkload = True

        for arg in arglist:
            if arg == "noworkload":
                doworkload = False

        # First test idle
        if self.runSubcase("doMigrate", (False), "XenMotion", "Idle") != \
               xenrt.RESULT_PASS:
            return
        
        # Test with stress workloads
        if doworkload:
            if self.runSubcase("doMigrate", (True), "XenMotion", "Stressed") != \
                    xenrt.RESULT_PASS:
                return

class TC9318(_TCXenMotionNonLocal):
    """Inter-host XenMotions of a multi-vCPU Windows Server 2008 32 bit VM on EPT"""
    
    DISTRO = "ws08sp2-x86"
    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXHAP"

class TC9319(TC9318):
    """Inter-host XenMotions of a multi-vCPU Windows Server 2008 64 bit VM on EPT"""
    
    DISTRO = "ws08sp2-x64"

class _TCminiStressXenMotion(_TCXenMotionNonLocal):

    MEMORY = 1024
    VCPUS = 2
    VARCH = "VMXHAP"
    LOOPITERS = 100 

class TCwin2k8x86(_TCminiStressXenMotion)
    """Inter-host XenMotions of a multi-vCPU Windows Server 2008 32 bit VM on EPT"""

    DISTRO = "ws08sp2-x86"

class TCwin2k8x64(_TCminiStressXenMotion):
    """Inter-host XenMotions of a multi-vCPU Windows Server 2008 64 bit VM on EPT"""

    DISTRO = "ws08sp2-x64"

class _TCClockDrift(xenrt.TestCase):

    HARCH = "VMX"
    HCPUS = 16
    
    VARCH = "x86-32"
    VCPUS = 2 

    DISTRO = "ws08sp2-x86"

    OCFACTOR = 0.20
    VWFACTOR = 1.0

    DURATION = 3600
    INTERVAL = 30

    DIFFWARN = 1.5
    DIFFLIMIT = 3.0

    def _logHostClock(self):
        self.host.checkReachable(timeout=300)
        ask_time = time.time()
        host_time = self.host.execdom0('echo -n "[Host System] "; date -u +%c\ \ +0.%6N\ seconds; echo -n "[Host Hardware] "; hwclock --show --utc --directisa --noadjfile', idempotent=True)
        answer_time = time.time()
        xenrt.TEC().logverbose("Scheduler System (ask): %f;  Scheduler System (answer): %f\n%s" % (ask_time, answer_time, host_time))

    def _guestMinMemory(self, host, guest_distro):
        version_limit = int(host.lookup(["VM_MIN_MEMORY_LIMITS", guest_distro], "0"))
        if version_limit > 0:
            return version_limit
        else:
            guest_limit = int(xenrt.TEC().lookup(["GUEST_LIMITATIONS", guest_distro, "MINMEMORY"], "0"))
            if guest_limit > 0:
                return guest_limit
            else:
                version_default = int(host.lookup(["MIN_VM_MEMORY"]))
                return version_default

    def prepare(self, arglist=[]):
        
        args = xenrt.util.strlistToDict(arglist)
        self.HARCH = args.get("harch") or self.HARCH
        self.HCPUS = args.get("hcpus") and int(args["hcpus"]) or self.HCPUS
        self.VARCH = args.get("varch") or self.VARCH
        self.VCPUS = args.get("vcpus") and int(args["vcpus"]) or self.VCPUS
        self.DISTRO = args.get("distro") or self.DISTRO

        self.OCFACTOR = args.has_key("ocfactor") and float(args["ocfactor"]) or self.OCFACTOR
        self.DURATION = args.has_key("duration") and int(args["duration"]) or self.DURATION
        self.INTERVAL = args.has_key("interval") and int(args["interval"]) or self.INTERVAL

        self.DIFFWARN = args.has_key("diffwarn") and float(args["diffwarn"]) or self.DIFFWARN
        self.DIFFLIMIT = args.has_key("difflimit") and float(args["difflimit"]) or self.DIFFLIMIT
        
        self.host = self.getDefaultHost()

        cpu_info = self.host.execdom0("cat /proc/cpuinfo")
        cpu_num = int(self.host.execdom0("xe host-cpu-info --minimal").strip())

        if cpu_info.find(self.HARCH.lower()) < 0:
            raise xenrt.XRTError("Not running on %s hardware" % self.HARCH)
        if cpu_num != self.HCPUS:
            raise xenrt.XRTError("Physical CPUs(cores) number is not %i, but %i" % (self.HCPUS, cpu_num))
        if not (self.DISTRO[-2:] == self.VARCH[-2:] == "64" or self.VARCH[-2:] == "32"):
            raise xenrt.XRTError("Guest distribution is not for %s arch" % self.VARCH)

        # XRT-7105 hack: WinXP isn't responsive enough on SVM
        if self.HARCH.find("SVM") >= 0 and self.DISTRO.find("xp") >=0:
            self.OCFACTOR = 0.125
            self.VCPUS = 1

        self.__doc__ = "Time drifting test of %s VM with %i VCPUs on %s host with %i CPUs" % (self.DISTRO, self.VCPUS, self.HARCH, self.HCPUS)

        self._logHostClock()

        self.guest = self.host.createBasicGuest(self.DISTRO, vcpus=self.VCPUS,
                                                memory=self._guestMinMemory(self.host, self.DISTRO) + self.VCPUS * 32,
                                                name=self.DISTRO, arch=self.VARCH)
        self.uninstallOnCleanup(self.guest)

        deadline = time.time() + 300
        while self.guest.xmlrpcExec('sc query w32time | find "FAILED"', level=xenrt.RC_OK) != 0:
            if time.time() > deadline:
                raise xenrt.XRTError("Failed to unregister w32time service on %s" % self.DISTRO)
            try:
                self.guest.xmlrpcExec("net stop w32time", level=xenrt.RC_OK)
                self.guest.xmlrpcExec("w32tm /unregister")
            except:
                self.guest.checkReachable(timeout=300)
 
        self.guest.workloads = self.guest.startWorkloads(["Prime95" for i in range(int(self.VCPUS * self.VWFACTOR))])

        self._logHostClock()
        
        self.guests = []
        vcpus_guests = int(self.HCPUS * (1 + self.OCFACTOR) + 0.5) - self.VCPUS
        
        if vcpus_guests > 0 :
            
            self.guesttpl = self.host.createGenericLinuxGuest()
            self.uninstallOnCleanup(self.guesttpl)
            self.guesttpl.preCloneTailor()
            self.guesttpl.shutdown()

            unit = 1
            guests_spec = []

            while vcpus_guests > 0:
                current = (vcpus_guests % 2) * unit
                if current > 0: guests_spec.append(current)
                vcpus_guests = vcpus_guests / 2
                unit = unit * 2

            guest_mem_base = self._guestMinMemory(self.host, self.guesttpl.distro)
            guest_mem_extra = 32

            host_mem_free = int(self.host.paramGet('memory-free-computed'))/xenrt.MEGA
            while len(guests_spec) > 1 and len(guests_spec) * guest_mem_base + sum(guests_spec) * guest_mem_extra > host_mem_free:
                guests_spec = [guests_spec[0] + guests_spec[1]] + guests_spec[2:]
            
            for i in guests_spec:
                g = self.guesttpl.cloneVM()
                self.uninstallOnCleanup(g)
                g.cpuset(i)
                g.memset(min(guest_mem_base + i * 32, int(self.host.paramGet('memory-free-computed'))/xenrt.MEGA/1.01))
                g.start()
                for _ in range(i):
                    self.guest.checkReachable(timeout=300)
                    g.startWorkloads(["LinuxSysbench"])
                self.guests.append(g)
            xenrt.TEC().logverbose("Successfully created dummy guests with vcpus = %s" % guests_spec)

        self._logHostClock()

        # Stop the NTP service on the host, so that we can know whether it's VM's clock drifting or host's hardware drifting
        self.host.execdom0("service ntpd stop")


    def run(self, arglist=[]):

        skews = 0.0
        times = 10
        for i in range(times):
            self.guest.checkReachable(timeout=300)
            ask_time = time.time()
            guest_time = self.guest.getTime()
            answer_time = time.time()
            skews += (answer_time + ask_time)/2 - guest_time
        skew = skews / times
        xenrt.TEC().logverbose("Measured skew between guest VM and local schedule is roughly %f seconds" % skew)
        if abs(skew) > 60:
            xenrt.TEC().logverbose("Measured skew (with original clock diff contained) is too big")

        self.time_base = time.time()
        self.time_records = []

        try:
            drifting = False
            time_diff = 0.0
            time_diff_prop = 0.0
            time_diff_last10 = [0.0 for i in range(10)]

            while time.time() < self.time_base + self.DURATION * (1 + abs(time_diff)/self.DIFFLIMIT):

                self.guest.checkReachable(timeout=300)
                time_ask = time.time()
                time_guest = self.guest.getTime()
                time_answer = time.time()
                time_guest_est = (time_ask + time_answer)/2 - skew

                time_diff = time_guest - time_guest_est
                time_diff_prop = time_diff/(time_answer - self.time_base)
                time_diff_last10 = time_diff_last10[1:] + [time_diff]
                self.time_records.append((time_ask, time_guest, time_answer))
                xenrt.TEC().logverbose("Ask time: %s(%f)\t Answer time: %s(%f)\t Guest time: %s(%f)\t Estimated guest time: %s(%f)\t Diff: %f seconds\t Diff(%%): %f%%"
                                       % (time.strftime("%H:%M:%S", time.gmtime(time_ask)), time_ask,
                                          time.strftime("%H:%M:%S", time.gmtime(time_answer)), time_answer,
                                          time.strftime("%H:%M:%S", time.gmtime(time_guest)), time_guest,
                                          time.strftime("%H:%M:%S", time.gmtime(time_guest_est)), time_guest_est,
                                          time_diff,
                                          time_diff_prop * 100))

                if abs(time_diff) > self.DIFFWARN:
                    xenrt.TEC().logverbose("The difference between host clock and guest clock is beyond %f seconds" % self.DIFFWARN)
                    if abs(time_diff) >= self.DIFFLIMIT:
                        xenrt.TEC().logverbose("The difference between guest clock and host clock is beyond %f seconds" % self.DIFFLIMIT)
                        # still have a chance: it might because the query took too long to finish due to workloads
                        if abs(time_diff) - (time_answer - time_ask)/2 < self.DIFFLIMIT: 
                            xenrt.TEC().logverbose("The clocks relation is still reasonable, the difference is probably due to the long querying time")
                        else:
                            xenrt.TEC().logverbose("Clock drifted here!")
                            drifting = True
                            if time_answer > self.time_base + self.DURATION : break

                time.sleep(self.INTERVAL)

            if drifting:
                raise xenrt.XRTFailure("Found clock drifting on %s running on %s host with %i CPUs" % (self.DISTRO, self.HARCH, self.HCPUS))
        finally:
            
            self._logHostClock()
 
            f = open("%s/time_stats.data" % xenrt.TEC().getLogdir(), "w")
            f.write("# To run this with gnuplot:\n")
            f.write("#     plot 'time_stats.data' u 1:1 w linespoints t 'ask', '' u 1:2 w linespoints t 'guest', '' u 1:3 w linespoints t 'answer'\n")  
            f.write("# \n")
            f.write("# Measured skew ((answer time + ask time) / 2 - guest time) is %f sec\n" % skew)
            f.write("# \n")
            f.write("# Asking time(host)\tGuest time\tGetting answer(host)\n")
            for r in self.time_records:
                r_rebase = tuple(map(lambda t: t - self.time_base, r))
                f.write("%f\t%f\t%f\n" % r_rebase)
            f.close()

    def postRun(self):
        self.host.execdom0("service ntpd start")


class TC9737(_TCClockDrift):
    HARCH = "VMX"
    HCPUS = 2
    VARCH = "x86-64"
    VCPUS = 2 
    DISTRO = "ws08sp2-x64"

class TC9749(_TCClockDrift):
    HARCH = "VMX"
    HCPUS = 2
    VARCH = "x86-32"
    VCPUS = 2 
    DISTRO = "ws08sp2-x86"

class TC9750(_TCClockDrift):
    HARCH = "VMX"
    HCPUS = 2
    VARCH = "x86-64"
    VCPUS = 2 
    DISTRO = "ws08r2-x64"

class TC9751(_TCClockDrift):
    HARCH = "VMX"
    HCPUS = 2
    VARCH = "x86-32"
    VCPUS = 2 
    DISTRO = "winxpsp3"

class TC9752(_TCClockDrift):
    HARCH = "VMX"
    HCPUS = 8
    VARCH = "x86-64"
    VCPUS = 2 
    DISTRO = "ws08sp2-x64"

class TC9753(_TCClockDrift):
    HARCH = "VMX"
    HCPUS = 8
    VARCH = "x86-32"
    VCPUS = 2 
    DISTRO = "ws08sp2-x86"

class TC9754(_TCClockDrift):
    HARCH = "VMX"
    HCPUS = 8
    VARCH = "x86-64"
    VCPUS = 2 
    DISTRO = "ws08r2-x64"

class TC9755(_TCClockDrift):
    HARCH = "VMX"
    HCPUS = 8
    VARCH = "x86-32"
    VCPUS = 2
    DISTRO = "winxpsp3"

    OCFACTOR = 0.15
    VWFACTOR = 0.5

class TC9756(_TCClockDrift):
    HARCH = "SVM"
    HCPUS = 4
    VARCH = "x86-64"
    VCPUS = 2 
    DISTRO = "ws08sp2-x64"

class TC9757(_TCClockDrift):
    HARCH = "SVM"
    HCPUS = 4
    VARCH = "x86-32"
    VCPUS = 2 
    DISTRO = "ws08sp2-x86"

class TC9758(_TCClockDrift):
    HARCH = "SVM"
    HCPUS = 4
    VARCH = "x86-64"
    VCPUS = 2 
    DISTRO = "ws08r2-x64"

class TC9759(_TCClockDrift):
    HARCH = "SVM"
    HCPUS = 4
    VARCH = "x86-32"
    VCPUS = 2 
    DISTRO = "winxpsp3"

class TC9760(_TCClockDrift):
    HARCH = "SVM"
    HCPUS = 8
    VARCH = "x86-64"
    VCPUS = 2 
    DISTRO = "ws08sp2-x64"

class TC9761(_TCClockDrift):
    HARCH = "SVM"
    HCPUS = 8
    VARCH = "x86-32"
    VCPUS = 2 
    DISTRO = "ws08sp2-x86"

class TC9762(_TCClockDrift):
    HARCH = "SVM"
    HCPUS = 8
    VARCH = "x86-64"
    VCPUS = 2 
    DISTRO = "ws08r2-x64"

class TC9763(_TCClockDrift):
    HARCH = "SVM"
    HCPUS = 8
    VARCH = "x86-32"
    VCPUS = 2
    DISTRO = "winxpsp3"

    OCFACTOR = 0.15
    VWFACTOR = 0.5

class TC20974(_TCClockDrift):
    HARCH = "SVM"
    HCPUS = 4
    VARCH = "x86-32"
    VCPUS = 2
    DISTRO = "w2k3eesp2"

class TC20975(_TCClockDrift):
    HARCH = "SVM"
    HCPUS = 4
    VARCH = "x86-64"
    VCPUS = 2
    DISTRO = "w2k3eesp2-x64"
    
class TC10054(xenrt.TestCase):
    """Windows VM time is based on dom0 time and not the hardware clock"""

    def getHWClockSkew(self):
        data = self.host.execdom0("hwclock --show --utc")
        if not "UTC" in data:
            raise xenrt.XRTError("Hardware clock did not return a UTC time")
        r = re.search(r"^(.+) (AM|PM)\s+UTC\s+([\.\+\-0-9]+) seconds$", data) 
        if not r:
            raise xenrt.XRTError("Could not parse hwclock output")
        t = time.strptime(r.group(1), "%a %d %b %Y %H:%M:%S")
        t = t[0:3] + (t[3] % 12 + 12 * int(r.group(2) == "PM"),) + t[4:]
        hwtime = int(calendar.timegm(t)) + float(r.group(3))
        return hwtime - time.time()

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericWindowsGuest()
        self.uninstallOnCleanup(self.guest)

        # Make sure our VM is using UTC
        data = self.guest.xmlrpcExec("systeminfo", returndata=True)
        if not "Monrovia, Reykjavik" in data:
            raise xenrt.XRTError("Windows VM not using UTC")

        # Disable the time service in the VM
        deadline = time.time() + 300
        while self.guest.xmlrpcExec('sc query w32time | find "FAILED"',
                                    level=xenrt.RC_OK) != 0:
            if time.time() > deadline:
                raise xenrt.XRTError("Failed to unregister w32time service")
            try:
                self.guest.xmlrpcExec("net stop w32time", level=xenrt.RC_OK)
                self.guest.xmlrpcExec("w32tm /unregister")
            except:
                self.guest.checkReachable(timeout=300)

        # Ensure the VM, dom0 and hardware clocks are all approximately the
        # same
        skewdom0 = self.host.getClockSkew()
        skewvm = self.guest.getClockSkew()
        if abs(skewdom0 - skewvm) > 300:
            raise xenrt.XRTError("VM/dom0 differences too large to "
                                 "run test")

        # Stop ntpd in dom0 and set the clock in the future
        self.guest.shutdown()
        self.host.execdom0("service ntpd stop")
        ftime = time.gmtime(xenrt.timenow() + 10000)
        if isinstance(self.host, xenrt.lib.xenserver.CreedenceHost):
            self.host.execdom0('hwclock --set --date "%s"' % (time.strftime("%b %d %H:%M:%S UTC %Y", ftime)))
            self.host.execdom0('hwclock --hctosys')
        else:
            self.host.execdom0("date -u %s" % (time.strftime("%m%d%H%M%Y", ftime)))
        # Reboot the host to cause the hardware clock to be set to the
        # future value
        self.host.reboot()

        # XRT-8130: ensure ntpd is in sync
        ntpcode = self.host.execdom0("ntpstat", retval="code")
        if ntpcode <> 2:
            xenrt.TEC().logverbose("ntpd started, stop it before syncing")
            self.host.execdom0("service ntpd stop")
        # XRT-8311: ensure local clock is in sync with ntp server right then
        self.host.execdom0("ntpd -q -gx")
        self.host.execdom0("service ntpd start")

        ntpcode = self.host.execdom0("ntpstat", retval="code")
        if ntpcode == 2:
            xenrt.TEC().logverbose("ntpd is unreachable (failed to start?), will try to restart")
            self.host.execdom0("service ntpd restart")
            ntpcode = self.host.execdom0("ntpstat", retval="code")
            if ntpcode == 2: raise xenrt.XRTError("ntpd is unreachable")
        if ntpcode == 1:
            xenrt.TEC().logverbose("ntpd is not in sync status, ignoring since local clock has been already synced.")
        elif ntpcode == 0:
            xenrt.TEC().logverbose("ntpd is in sync status")
        else:
            raise xenrt.XRTError("ntpd is in unkown status, status code: %d", ntpcode)

        # Check the dom0 time is correct (ntpd should be running now) and
        # the hardware clock is still in the future.
        skewdom0 = self.host.getClockSkew()
        if abs(skewdom0) > 300:
            raise xenrt.XRTError("Dom0 time not correct after reboot")
        skewhw = self.getHWClockSkew()
        if skewhw < 9700:
            raise xenrt.XRTError("Hardware clock is not set in the future")

    def run(self, arglist):

        # Start the VM
        self.guest.start()

        # Check that the VM time approximately matches dom0 time (which we)
        # know approximately matches controller time
        skewvm = self.guest.getClockSkew()
        if abs(skewvm) > 300:
            # Check if the VM looks to be tied to the hardware clock
            skewhw = self.getHWClockSkew()
            if abs(skewhw - skewvm) < 300:
                raise xenrt.XRTFailure("VM clock appears to match hardware "
                                       "clock and not dom0 time")
            raise xenrt.XRTFailure("VM clock considerable different to dom0")
        else:
            xenrt.TEC().logverbose("VM clock sufficiently close to dom0 time")

    def postRun(self):

        # Reboot the host and check the hwclock has been put back to a
        # reasonable value
        if self.guest.getState() == "UP":
            self.guest.shutdown()
        self.host.reboot()
        skewdom0 = self.host.getClockSkew()
        skewhw = self.getHWClockSkew()
        if abs(skewdom0) > 300:
            xenrt.TEC().warning("Dom0 time not correct after postRun reboot")
        if abs(skewhw) > 300:
            xenrt.TEC().warning("Hardware clock not correct after postRun "
                                "reboot")

class TC20607(TC10054):
    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericWindowsGuest()
        self.uninstallOnCleanup(self.guest)

        # Make sure our VM is using UTC
        data = self.guest.xmlrpcExec("systeminfo", returndata=True)
        if not "Monrovia, Reykjavik" in data:
            raise xenrt.XRTError("Windows VM not using UTC")

        # Disable the time service in the VM
        deadline = time.time() + 300
        while self.guest.xmlrpcExec('sc query w32time | find "FAILED"',
                                    level=xenrt.RC_OK) != 0:
            if time.time() > deadline:
                raise xenrt.XRTError("Failed to unregister w32time service")
            try:
                self.guest.xmlrpcExec("net stop w32time", level=xenrt.RC_OK)
                self.guest.xmlrpcExec("w32tm /unregister")
            except:
                self.guest.checkReachable(timeout=300)

        # Ensure the VM, dom0 and hardware clocks are all approximately the
        # same
        skewdom0 = self.host.getClockSkew()
        skewvm = self.guest.getClockSkew()
        if abs(skewdom0 - skewvm) > 300:
            raise xenrt.XRTError("VM/dom0 differences too large to "
                                 "run test")

        # Stop ntpd in dom0 and set the clock in the future
        self.guest.shutdown()
        self.host.execdom0("service ntpd stop")
        ftime = time.gmtime(xenrt.timenow() + 10000)
        self.host.execdom0("date -u %s" % (time.strftime("%m%d%H%M%Y", ftime)))
                           
    def run(self, arglist):
        # Start the VM
        self.guest.start()
        skewdom0 = self.host.getClockSkew()
        skewvm = self.guest.getClockSkew()
        if abs(skewvm - skewdom0) > 300:
            xenrt.TEC().logverbose("Value of skewvm - skewdom0 = %d"%(skewvm-skewdom0))
            raise xenrt.XRTFailure("VM clock does not match the dom 0 clock")
        else:
            xenrt.TEC().logverbose("Value of skewvm - skewdom0 = %d"%(skewvm-skewdom0))
            xenrt.TEC().logverbose("VM clock sufficiently close to dom0 time")


class TC10555(xenrt.TestCase):
    """Linux guest reported free memory should be accurate after a migrate"""

    WINDOWS = False

    def prepare(self, arglist):
        self.host = self.getDefaultHost()

        # Install a VM
        if self.WINDOWS:            
            self.guest = self.host.createGenericWindowsGuest()
        else:
            self.guest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)

        # Check the memory is reporting a sensible free value
        time.sleep(420)
        m = self.guest.getDataSourceValue("memory_internal_free")
        if m < 1.0:
            raise xenrt.XRTError("Memory free value not sensible before test")
        self.memory = m
            
    def run(self, arglist):

        # Perform a localhost live migrate
        self.guest.migrateVM(self.host)

        # Wait a bit and check the memory is not zero
        time.sleep(180)
        m = self.guest.getDataSourceValue("memory_internal_free")
        if m < 1.0:
            raise xenrt.XRTFailure("Free memory reported as zero after migrate")
        delta = abs(self.memory - m)
        if delta/self.memory > 0.2:
            raise xenrt.XRTFailure("Free memory changed by more than 20% "
                                   "after migrate")
        
class TC10556(TC10555):
    """Windows guest reported free memory should be accurate after a migrate"""
    WINDOWS = True
    

class TC13249(xenrt.TestCase):
    """Seamless DST transitions in Virtual Desktop disk images"""
#   1. Install a XenServer and configure the date to occur outside DST
#      (change location to UK and date to winter time, e.g. 1st December)
#   2. Install a Windows VM with several VDIs.
#   3. Configure one of the VM's VDIs to have on-boot=reset.
#   4. Advance the XenServer clock manually to a date within DST.
#   5. Repeatedly start and restart the VM, observing that Windows does not
#      advance the clock more than once.
#   6. Check that pool restrictions contain restrict_intellicache=False.

    numberOfReboots = 3
    guestDistro = 'win7sp1-x86' # Windows version with tzutil 

    def setSummerTime(self):
        # set date/time to a winter time instant, e.g. July:
        self.setXenserverTime('Jul 1 01:00:00 UTC 2010')

    def setWinterTime(self):
        # set date/time to a winter time instant, e.g. January
        self.setXenserverTime('Jan 1 01:00:00 UTC 2010')

    def setXenserverTime(self, date):
        self.host.execdom0('hwclock --set --date "%s"' % date)
        # set system time on dom0 from hw clock
        self.host.execdom0('hwclock --hctosys')

    def formatTime(self, secondsSinceEpoch):
        t = time.gmtime(secondsSinceEpoch)
        return time.asctime(t)

    def getHostHwTime(self):
        hostHwStr = self.host.execdom0 ('hwclock --show')
        return time.mktime(
            time.strptime(re.match('(\S+\s+){6}',hostHwStr).group(0).strip(),
            "%a %d %b %Y %I:%M:%S %p")
            )

    def getGuestTimeOffset(self):
        cli = self.host.getCLIInstance()
        platform = cli.execute("vm-param-get uuid=%s  param-name=platform" %
                                                          self.guest.getUUID())
        mstr = re.search("timeoffset: (-?\d*);", platform).group(1)
        if mstr :
            return int(mstr.strip())
        else:
            return 0
  
    def getGuestTimeZone(self):
        sysInfo = self.guest.xmlrpcExec("systeminfo", returndata=True)
        return re.search('^Time Zone:\s+(.+?)\n', sysInfo, re.MULTILINE).group(1)

    def logGuestTimeZone(self):
        xenrt.TEC().logverbose("Time zone on Windows Guest: '%s'" %
                                                     self.getGuestTimeZone())
    def setGuestTimeZone(self, timezoneName):
        timeOffsetBefore = self.getGuestTimeOffset()
        self.logGuestTimeZone()
        xenrt.TEC().logverbose("Changing time zone on Windows Guest to '%s'"
                                                            % timezoneName)
        self.guest.xmlrpcExec('tzutil /s "%s"' % timezoneName)
        self.logGuestTimeZone()
        timeOffsetAfter = self.getGuestTimeOffset()
        if timeOffsetAfter == timeOffsetBefore:
            xenrt.TEC().warning("The VM time offset did not change! ")
        xenrt.TEC().logverbose("Time offsets before and after change:\nBefore: %s\nAfter: %s"
                % (timeOffsetBefore, timeOffsetAfter))
        
    def getAllTimes(self):
        times = {}
        times['host system'] = float(self.host.execdom0('date +%s.%N'))
        hostHwStr = self.host.execdom0 ('hwclock --show')
        times['host hardware'] =  time.mktime(
            time.strptime(re.match('(\S+\s+){6}',hostHwStr).group(0).strip(),
            "%a %d %b %Y %I:%M:%S %p")
            )
        # get guest time only if guest has been created
        try: self.guest
        except AttributeError : pass
        else:
            if self.guest.getState() == "UP":
                guestOffset = self.getGuestTimeOffset()
                times['guest system'] = self.guest.getTime()
                times['guest hardware'] = times['host hardware'] + guestOffset 
        # log times
        s = "Current times: \n"
        for t in sorted(times.keys()):
            s += "%s:\t%12.0f\t%s\n" % (t, times[t], self.formatTime(times[t]))
        xenrt.TEC().logverbose(s)
        return times

    def prepare(self, arglist=[]):
        self.host = self.getDefaultHost()
        self.pool = self.getDefaultPool()
        # disable NTP so the host time won't get set back to current
        self.host.execdom0("service ntpd stop")
        # print hw/sys time
        self.getAllTimes()
        # save original time
        self.origXrtTime = xenrt.timenow()
        self.origHwTime = self.getHostHwTime()
        self.setWinterTime()
        # print hw/sys time
        self.getAllTimes()
        # use nfs storage here to counter-test against Cowley
        self.guest = self.host.createGenericWindowsGuest(name="GenWin",
                   distro=self.guestDistro, sr=self.host.getSRs(type="nfs")[0])
        self.uninstallOnCleanup(self.guest)
        # print hw/sys time
        self.getAllTimes()
        # add a second disk to the Windows VM
        xenrt.TEC().logverbose("Creating additional disk on the Windows VM")
        # use nfs storage here to counter-test against Cowley
        extradisk = self.guest.createDisk(sizebytes=1024, sruuid=self.host.getSRs(type="nfs")[0])
        self.guest.reboot()
        # set timezone to London
        timeZoneName ="GMT Standard Time"
        self.setGuestTimeZone(timeZoneName)
        self.guestVDIs = self.host.minimalList("vbd-list", "vdi-uuid",
            "vm-uuid=%s type=Disk" % (self.guest.getUUID()))
        self.guest.shutdown()
        # print hw/sys time
        self.getAllTimes()

    def run(self, arglist=[]):
        cli = self.host.getCLIInstance()
        # get a list of all VDIs attached to the guest
        for vdi in self.guestVDIs:
            # set on-boot=reset on vdi
            hoffsetBefore = self.getGuestTimeOffset()
            self.guest.start()
            times_before = self.getAllTimes()
            device = self.host.parseListForOtherParam("vbd-list", "vdi-uuid",
                vdi, "device")
            self.guest.shutdown()
            xenrt.TEC().logdelimit("Setting on-boot=reset on device '%s' "
                "(vdi uuid=%s)." % (device, vdi) )
            cli.execute("vdi-param-set uuid=%s on-boot=reset other-config:timeoffset=0" % vdi)
            xenrt.TEC().logverbose("guest VM time offset after the change: %s"  %
                                 self.getGuestTimeOffset() )
            # change time on XenServer to summer time
            self.setSummerTime()
            # start and stop the guest many times
            for i in range(self.numberOfReboots):
                self.guest.start()
                times = self.getAllTimes()
                self.guest.shutdown()
            # make sure that after the reboots there is only one hour difference
            offsetBefore = times_before['host hardware'] - times_before['guest system']
            offsetAfter = times['host hardware'] - times['guest system']
            diffInSeconds = offsetAfter - offsetBefore 
            xenrt.TEC().logverbose("After %s VM reboots, the offset drifted "
                "%s seconds (%s hours)" % (self.numberOfReboots, diffInSeconds, diffInSeconds/3600))
            tolerance = 10
            if abs(diffInSeconds) > (3600+tolerance):
                raise xenrt.XRTFailure("After %s reboots the time offset change "
                    "was %s seconds (%s hours) instead of expected one hour."
                    % (self.numberOfReboots, diffInSeconds, diffInSeconds/3600) )
            hoffsetAfter = self.getGuestTimeOffset()
            hoffsetDiff = hoffsetAfter - hoffsetBefore
            if abs(hoffsetDiff) >  (3600+tolerance):
                raise xenrt.XRTFailure("After %s reboots the hardware time offset "
                    "change was %s seconds (%s hours) instead of expected one hour."
                    % (self.numberOfReboots, hoffsetDiff, hoffsetDiff/3600))
            # return to non-reset setting
            cli.execute("vdi-param-set uuid=%s on-boot=persist other-config:timeoffset=" % vdi)
            cli.execute("vdi-param-remove uuid=%s param-name=other-config param-key=timeoffset" % vdi )
            self.setWinterTime()
            
        # make sure that restrict_intellicache is set to False
        xenrt.TEC().logdelimit("Checking that restrict_intellicache is set to false")
        restrictions = self.pool.getPoolParam("restrictions")
        regExp = ' restrict_intellicache: (\w+)'
        match = re.search(regExp,restrictions)
        if match:
            value = match.group(1)
        else:
            raise xenrt.XRTFailure("Parameter restrict_intellicache not found.")
        if value != 'false':
            raise xenrt.XRTFailure("Parameter restrict_intellicache was '%s' "
                "(expected 'false')." % value)
                
        # check that VM won't start if two VDIs have on-boot=reset and other_config:timeoff=k
        
        xenrt.TEC().logdelimit(
            "Check that VM won't start if two VDIs have on-boot=reset and other_config:timeoff=k")
        xenrt.TEC().logverbose("getting current VDI parameters")
        for vdi in self.guestVDIs:
            cli.execute("vdi-param-list uuid=%s" % vdi)
        for vdi in self.guestVDIs:
            self.host.genParamSet("vdi", vdi, "on-boot", "reset")
            try:
                timeoffset = self.host.genParamGet("vdi", vdi, "other-config:timeoffset")
            except: 
                self.host.genParamSet("vdi", vdi, "other-config:timeoffset", "20")
        xenrt.TEC().logverbose("getting current VDI parameters")
        for vdi in self.guestVDIs:
            cli.execute("vdi-param-list uuid=%s" % vdi)

        try:    
            self.guest.start()
        except Exception, e:
            xenrt.TEC().logverbose("Expected exception - VM-start should fail, as VM is in inappropriate state:\n%s" % e)
        else:
            raise xenrt.XRTFailure("Host should have prevent Windows VM from starting, when the VM was in an appropriate state")

    def postRun(self):
        # revert the hardware clock to the xenrt time
        delta = xenrt.timenow() - self.origXrtTime
        newHwTime = self.origHwTime + delta
        newHwTimeStr = time.asctime(time.gmtime(newHwTime))
        self.setXenserverTime(newHwTimeStr)

class _TCWinTimeZoneLifeCycle(testcases.xenserver.tc.guest._WinTimeZone):
    """Windows TimeZone lifecycle tests"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        guestName = self.host.listGuests()[0]
        lifecycleOperation = 'shutdownStart'
        self.setHostTimeUTCUsingRegistry = True

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                guestName = l[1]
            elif l[0] == "lifecycleOperation":
                lifecycleOperation = l[1]
            elif l[0] == "hostTimeOptionAlreadySet":
                self.setHostTimeUTCUsingRegistry = False

        self.guest = self.host.getGuest(guestName)
        if not self.guest:
            raise xenrt.XRTError('No guest found')

        self.getLogsFrom(self.guest)
        if self.guest.usesLegacyDrivers():
            try:
                self.guest.setClockSync(enable=False)
            except:
                pass
        else:
            try:
                w32timeData = self.guest.xmlrpcExec('sc query w32time', returnerror=False, returndata=True)
                map(lambda x:xenrt.TEC().logverbose(x), w32timeData.splitlines())
            except Exception, e:
                xenrt.TEC().logverbose('Attepmt to see state of w32time failed with exception: %s' % (str(e)))

        self.lifecycleOperation = getattr(self, lifecycleOperation, None)
        if not callable(self.lifecycleOperation):
            raise xenrt.XRTError('Invalid / Unknow Lifecycle Operation')

    def shutdownStart(self, timeZoneOffset, iterations=2):
        for i in range(iterations):
            self.guest.shutdown()
            self.guest.start()
            self.verifyGuestTime(self.guest, self.host, timeZoneOffset)
        
    def suspendResume(self, timeZoneOffset, iterations=2):
        for i in range(iterations):
            self.guest.suspend()
            self.guest.resume()
            self.verifyGuestTime(self.guest, self.host, timeZoneOffset)
        
    def inGuestReboot(self, timeZoneOffset, iterations=2):
        for i in range(iterations):
            self.guest.xmlrpcReboot()
            xenrt.sleep(60)
            self.guest.waitForDaemon(300, desc="Wait after in-guest reboot")
            self.verifyGuestTime(self.guest, self.host, timeZoneOffset)
        
    def localhostMigrate(self, timeZoneOffset, iterations=2):
        for i in range(iterations):
            self.guest.migrateVM(self.guest.host, live='true')
            self.verifyGuestTime(self.guest, self.host, timeZoneOffset)

    def poolMigrate(self, timeZoneOffset, iterations=2):
        pool = self.getDefaultPool()
        for destHost in [pool.slaves.values()[0], pool.master] * iterations:
            self.guest.migrateVM(destHost, live='true')
            self.verifyGuestTime(self.guest, self.master, timeZoneOffset)
        

class TCWinTzHostTimeUTC(_TCWinTimeZoneLifeCycle):
    """Use the XenTools time zone option (only available from Clearwater HFX: XS62??? onwards)"""

    def run(self, arglist):
        if self.guest.usesLegacyDrivers():
            self.guest.reboot()

        TIMEZONE_TEST_LIST = [0, -12, 12, -1, 1, 0]
        if self.setHostTimeUTCUsingRegistry:
            self.setXenToolsTimeZoneOption(self.guest)

        self.setWindowsTimeZone(self.guest, timeZoneOffsetHours=0)
        self.guest.reboot()

        # Verify that the registry entry is correctly set.
        if not self.isHostTimeUTCEnabled(self.guest):
            raise xenrt.XRTFailure('HostTimeUTC feature not enabled on guest')

        for tz in TIMEZONE_TEST_LIST:
            actualOffset = self.setWindowsTimeZone(self.guest, timeZoneOffsetHours=tz)
            self.verifyGuestTime(self.guest, self.host, actualOffset)

            xenrt.TEC().logverbose('Executing %s lifecycle operation for timezone offset: %d' % (self.lifecycleOperation.__name__, actualOffset))
            self.lifecycleOperation(actualOffset)

    def postRun(self):
        if self.setHostTimeUTCUsingRegistry:
            self.setXenToolsTimeZoneOption(self.guest, useUTC=False)

    def shutdownStart(self, timeZoneOffset, iterations=2):
        for i in range(iterations):
            self.guest.shutdown()
            self.guest.paramSet('platform:timeoffset', 0)
            self.guest.start()
            self.guest.paramSet('platform:timeoffset', 0)
            self.verifyGuestTime(self.guest, self.host, timeZoneOffset)
        
    def suspendResume(self, timeZoneOffset, iterations=2):
        for i in range(iterations):
            self.guest.suspend()
            self.guest.paramSet('platform:timeoffset', 0)
            self.guest.resume()
            self.guest.paramSet('platform:timeoffset', 0)
            self.verifyGuestTime(self.guest, self.host, timeZoneOffset)
        
    def localhostMigrate(self, timeZoneOffset, iterations=2):
        for i in range(iterations):
            self.guest.paramSet('platform:timeoffset', 0)
            self.guest.migrateVM(self.guest.host, live='true')
            self.guest.paramSet('platform:timeoffset', 0)
            self.verifyGuestTime(self.guest, self.host, timeZoneOffset)

    def poolMigrate(self, timeZoneOffset, iterations=2):
        pool = self.getDefaultPool()
        for destHost in [pool.slaves.values()[0], pool.master] * iterations:
            self.guest.paramSet('platform:timeoffset', 0)
            self.guest.migrateVM(destHost, live='true')
            self.guest.paramSet('platform:timeoffset', 0)
            self.verifyGuestTime(self.guest, pool.master, timeZoneOffset)

    def inGuestReboot(self, timeZoneOffset, iterations=2):
        for i in range(iterations):
            self.guest.paramSet('platform:timeoffset', 0)
            self.guest.xmlrpcReboot()
            xenrt.sleep(60)
            self.guest.waitForDaemon(300, desc="Wait after in-guest reboot")
            self.guest.paramSet('platform:timeoffset', 0)
            self.verifyGuestTime(self.guest, self.host, timeZoneOffset)
        
class TC18175(xenrt.TestCase):
    """Correct operation of VM.platform:xenguest and :device-model overrides"""
    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        step("Install generic Windows guest")
        self.guest = self.host.createGenericWindowsGuest()
        self.uninstallOnCleanup(self.guest)
        self.guest.shutdown()
        
        step("Create alternative xenguest and device-model scripts that touch a file to record they have run then execute the default script/program")
        self.host.execdom0("mkdir -p %s/xenguest %s/device-model" % (self.host.getAlternativesDir(), self.host.getAlternativesDir()))
        myxenguest = """#!/bin/bash

logger -t TC18175 "Running myxenguest.sh"
touch /tmp/myxenguest.dat
%s "$@"
""" % self.host.getXenGuestLocation()
        mydm = """#!/bin/bash

logger -t TC18175 "Running mydm.sh"
touch /tmp/mydm.dat
%s "$@"
""" % self.host.getQemuDMWrapper()
        myxenguestfile = xenrt.TEC().tempFile()
        mydmfile = xenrt.TEC().tempFile()
        f = file(myxenguestfile, "w")
        f.write(myxenguest)
        f.close()
        f = file(mydmfile, "w")
        f.write(mydm)
        f.close()
        step("Copy myxenguest.sh and mydm.sh to host")
        sftp = self.host.sftpClient()
        try:
            sftp.copyTo(myxenguestfile, "%s/xenguest/myxenguest.sh" % self.host.getAlternativesDir())
            sftp.copyTo(mydmfile, "%s/device-model/mydm.sh" % self.host.getAlternativesDir())
        finally:
            sftp.close()
        self.host.execdom0("chmod +x %s/xenguest/myxenguest.sh %s/device-model/mydm.sh" % (self.host.getAlternativesDir(), self.host.getAlternativesDir()))
        self.host.execdom0("rm -f /tmp/myxenguest.dat /tmp/mydm.dat")

    def _checkfiles(self, checkfiles):
        missing = []
        for filename in checkfiles:
            if self.host.execdom0("test -e %s" % (filename), retval="code") != 0:
                missing.append(filename)
                xenrt.TEC().warning("Missing flag file %s" % (filename))
            else:
                xenrt.TEC().logverbose("Found expected flag file %s" % (filename))
            self.host.execdom0("rm -f %s" % (filename))
        if len(missing) > 0:
            raise xenrt.XRTFailure("%d flag files missing after VM operation" % (len(missing)))

    def startVM(self, checkfiles):
        self.guest.start()
        self.guest.check()
        self._checkfiles(checkfiles)

    def resume(self, checkfiles):
        self.guest.suspend()
        self.guest.resume()
        self.guest.check()
        self._checkfiles(checkfiles)
        
    def migrate(self, checkfiles):
        self.guest.migrateVM(self.guest.host, live=True)
        time.sleep(10)
        self.guest.check()
        self._checkfiles(checkfiles)

    def run(self, arglist):
        step("Setting platform flags so custom xenguest script gets used")
        self.guest.paramSet("platform:xenguest", "myxenguest.sh")
        if self.runSubcase("startVM", (["/tmp/myxenguest.dat"]), "xenguest", "Start") == \
                xenrt.RESULT_PASS:
            if self.runSubcase("resume", (["/tmp/myxenguest.dat"]), "xenguest", "Resume") == \
                    xenrt.RESULT_PASS:
                self.runSubcase("migrate", (["/tmp/myxenguest.dat"]), "xenguest", "Migrate")
        self.guest.shutdown()
        step("Setting platform flags so custom device model script gets used")
        self.guest.paramSet("platform:device-model", "mydm.sh")
        if self.runSubcase("startVM", (["/tmp/myxenguest.dat", "/tmp/mydm.dat"]), "Both", "Start") == \
                xenrt.RESULT_PASS:
            if self.runSubcase("resume", (["/tmp/myxenguest.dat", "/tmp/mydm.dat"]), "Both", "Resume") == \
                    xenrt.RESULT_PASS:
                self.runSubcase("migrate", (["/tmp/myxenguest.dat", "/tmp/mydm.dat"]), "Both", "Migrate")
        self.guest.shutdown()
        self.guest.paramRemove("platform", "xenguest")
        if self.runSubcase("startVM", (["/tmp/mydm.dat"]), "device-model", "Start") == \
                xenrt.RESULT_PASS:
            if self.runSubcase("resume", (["/tmp/mydm.dat"]), "device-model", "Resume") == \
                    xenrt.RESULT_PASS:
                self.runSubcase("migrate", (["/tmp/mydm.dat"]), "device-model", "Migrate")
        self.guest.shutdown()
        
    def postRun(self):
        self.host.execdom0("rm -rf %s" % self.host.getAlternativesDir())

class TC18173(xenrt.TestCase):
    """VM.platform:xenguest and :device-model should not allow the use of programs outside of specified directory"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericWindowsGuest()
        self.uninstallOnCleanup(self.guest)
        self.guest.shutdown()
        
        # Create "alternative" fraudulent xenguest and device-model scripts
        # that touch a file to record they have run
        dodgyscript = """#!/bin/bash

logger -t TC18173 "Running dodgyscript.sh"
touch /tmp/dodgyscript.dat
"""
        dodgyscriptfile = xenrt.TEC().tempFile()
        f = file(dodgyscriptfile, "w")
        f.write(dodgyscript)
        f.close()
        sftp = self.host.sftpClient()
        try:
            sftp.copyTo(dodgyscriptfile, "/tmp/dodgyscript.sh")
        finally:
            sftp.close()
        self.host.execdom0("chmod +x /tmp/dodgyscript.sh")
        self.host.execdom0("rm -f /tmp/dodgyscript.dat")
        
    def doTest(self):
        self.host.execdom0("rm -f /tmp/dodgyscript.dat")
        self.guest.start()
        self.guest.check()
        if self.host.execdom0("test -e /tmp/dodgyscript.dat", retval="code") == 0:
            raise xenrt.XRTFailure("Script ran outside of proper directory")

    def run(self, arglist):
        self.guest.paramSet("platform:xenguest", "../../../../tmp/dodgyscript.sh")
        if self.runSubcase("doTest", (), "xenguest", "relative") != \
                xenrt.RESULT_PASS:
            return
        self.guest.shutdown()
        self.guest.paramSet("platform:xenguest", "/tmp/dodgyscript.sh")
        if self.runSubcase("doTest", (), "xenguest", "absolute") != \
                xenrt.RESULT_PASS:
            return
        self.guest.shutdown()
        self.guest.paramRemove("platform", "xenguest")

        self.guest.paramSet("platform:device-model", "../../../../tmp/dodgyscript.sh")
        if self.runSubcase("doTest", (), "device-model", "relative") != \
                xenrt.RESULT_PASS:
            return
        self.guest.shutdown()
        self.guest.paramSet("platform:device-model", "/tmp/dodgyscript.sh")
        if self.runSubcase("doTest", (), "device-model", "absolute") != \
                xenrt.RESULT_PASS:
            return
        self.guest.shutdown()
        self.guest.paramRemove("platform", "device-model")

    def postRun(self):
        self.host.execdom0("rm -f /tmp/dodgyscipt.sh /tmp/dodgyscript.dat")
