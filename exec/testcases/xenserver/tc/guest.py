#
# XenRT: Test harness for Xen and the XenServer product family
#
# Guest standalone testcases
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy, math, numpy, decimal
import textwrap
import xenrt, xenrt.lib.xenserver
from datetime import datetime
from datetime import timedelta

from xenrt.lazylog import *


class TC7475(xenrt.TestCase):
    """Suspend/resume of a diskless VM"""

    def run(self, arglist=None):
        loops = 100

        host = self.getDefaultHost()
        guest = host.createRamdiskLinuxGuest()
        self.uninstallOnCleanup(guest)

        # Check it's happy
        guest.check()

        # Do a suspend resume loop
        v = host.getHostParam("software-version", "product_version").split(".")
        success = 0
        try:
            for i in range(loops):
                guest.pretendToHaveXenTools()
                time.sleep(5)
                guest.suspend()
                guest.resume()
                guest.check()
                success += 1
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" % (success,loops))

class TC7476(xenrt.TestCase):
    """Live migrate of a diskless VM"""

    def run(self, arglist=None):
        loops = 100

        pool = self.getDefaultPool()
        guest = pool.master.createRamdiskLinuxGuest()
        self.uninstallOnCleanup(guest)

        # Check it's happy
        guest.check()

        # Do the live migrate loop
        success = 0
        current = pool.master
        dest = pool.slaves[pool.slaves.keys()[0]]
        try:
            for i in range(loops):
                xenrt.TEC().logverbose("Live migrating from %s to %s" % 
                                       (current.getName(),dest.getName()))

                # Fool the agent into thinking we have PV drivers
                guest.pretendToHaveXenTools()

                guest.migrateVM(dest,live="true")
                guest.check()
                temp = current
                current = dest
                dest = temp
                success = success + 1
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" % (success,loops))

class TC7477(xenrt.TestCase):
    """Parallel uninstall of 1000 diskless VMs"""

    def run(self, arglist=None):
        vmcount = 1000

        host = self.getDefaultHost()
        guests = []

        # Create initial guest
        guest = host.guestFactory()(xenrt.randomGuestName(), None, host)
        guest.createHVMGuest([], pxe=True)
        guest.memset(256)
        guest.createVIF(bridge=host.getPrimaryBridge())
        guests.append(guest.getUUID())

        # Clone it the required number of times
        for i in range(vmcount-1):
            g = guest.cloneVM()
            guests.append(g.getUUID())

        # Run a script in dom0 to vm-uninstall force=true the VMs
        script = "#!/bin/bash\n"
        for uuid in guests:
            script += "xe vm-uninstall force=true uuid=%s\n" % (uuid)
        wdir = xenrt.TEC().getWorkdir()
        f = file("%s/uninstall.sh" % (wdir),"w")
        f.write(script)
        f.close()
        sftp = host.sftpClient()
        sftp.copyTo("%s/uninstall.sh" % (wdir),"/root/uninstall.sh")
        host.execdom0("chmod a+x /root/uninstall.sh")
        rc = host.execdom0("/root/uninstall.sh",retval="code")
        if rc > 0:
            xenrt.TEC().warning("Mass uninstall script returned with RC %u" 
                                % (rc))

        # Verify they were all uninstalled
        vms = host.minimalList("vm-list")
        present = 0
        for vm in vms:
            if vm in guests:
                present += 1
                xenrt.TEC().logverbose("Guest %s still present" % (vm))

        if present > 0:
            xenrt.TEC().comment("%u VMs left" % (present))
            # Deliberately don't give the number left, to avoid filing new bugs
            raise xenrt.XRTFailure("Mass uninstall of %u diskless VMs left some behind" % (vmcount))

class TC8605(xenrt.TestCase):
    """Suspend of a VM without PV drivers should be prevented"""

    def prepare(self, arglist):

        self.host = self.getDefaultHost()
        self.guest = self.host.createRamdiskLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.guest.check()

    def run(self, arglist=None):

        # An attempt to suspend the VM should fail
        try:
            self.guest.suspend()
        except xenrt.XRTFailure, e:
            if not re.search(r"PV drivers.*installed", e.data):
                raise e
        else:
            raise xenrt.XRTFailure("Was able to suspend a VM without PV drivers")
        
        # The VM should still be running
        if self.guest.getState() != "UP":
            raise xenrt.XRTFailure("VM not up after rejected suspend attempt")

class TC8606(xenrt.TestCase):
    """Migrate of a VM without PV drivers should be prevented"""

    def prepare(self, arglist):

        self.host = self.getDefaultHost()
        self.guest = self.host.createRamdiskLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.guest.check()

    def run(self, arglist=None):

        # An attempt to suspend the VM should fail
        try:
            self.guest.migrateVM(self.host, live="true")
        except xenrt.XRTFailure, e:
            if not re.search(r"PV drivers.*installed", e.data):
                raise e
        else:
            raise xenrt.XRTFailure("Was able to migrate a VM without PV drivers")

class TC9971(xenrt.TestCase):
    """Verify a HVM VM with 4099MB memory can start (SCTX-315)"""

    def run(self, arglist=None):

        host = self.getDefaultHost()
        guest = host.createRamdiskLinuxGuest(memory=4099)
        self.uninstallOnCleanup(guest)

        # Check it's happy
        guest.check()


class _TCCoresPerSocket(xenrt.TestCase):

    DISTRO = None
    MAXCPS = 2
    MAXSOCKETS = 2

    def prepare(self, arglist=[]):

        args = xenrt.util.strlistToDict(arglist)
        
        self.host_entp = self.getHost("RESOURCE_HOST_0")
        self.host_free = self.getHost("RESOURCE_HOST_1")
        
        if not isinstance(self.host_entp, xenrt.lib.xenserver.ClearwaterHost):
            self.host_entp.license(edition='enterprise')
            self.host_free.license(edition='free')

        self.distro = args.get("distro") or self.DISTRO or self.host_entp.lookup(["GENERIC_WINDOWS_OS"], "win7-x86")
        self.maxcps = args.get("maxcps") or self.MAXCPS

        self.max_sockets = xenrt.TEC().lookup(["GUEST_LIMITATIONS", self.distro, "MAXSOCKETS"], None)
        self.max_cores = xenrt.TEC().lookup(["GUEST_LIMITATIONS", self.distro, "MAXCORES"], None)
        
        if self.max_sockets:
            self.max_sockets = int(self.max_sockets)
            if self.max_cores:
                self.max_cores = int(self.max_cores)
            else:
                # recent OSes are only restricted by sockets (and c-p-s implicit physical limitation)
                self.max_cores = None
        elif self.max_cores:
                # some old OSes doesn't distinguish on cores and sockets
                self.max_cores = int(self.max_cores)
                self.max_sockets = self.max_cores
        else:
            # No known restriction
            self.max_sockets = None
            self.max_cores = None
        
        xenrt.TEC().logverbose("MAXSOCKETS is %s, MAXCORES is %s" % (self.max_sockets, self.max_cores))

        self.configs = []
        
        for i in range(int(math.log(self.max_sockets or self.MAXSOCKETS, 2)) + 1):
            
            sockets = int(math.pow(2, i))
            
            for j in range(i, int(math.log(self.max_cores or
                                           sockets * self.maxcps, 2)) + 1):
                cores = int(math.pow(2, j))
                self.configs.append({ 'sockets': sockets,
                                      'cores': cores,
                                      'cps': cores / sockets })
        self.configs.insert(0, { 'cores': self.max_sockets or self.MAXSOCKETS })
        self.configs.append({ 'cores': self.max_cores or self.maxcps * (self.max_sockets or self.MAXSOCKETS) })

        xenrt.TEC().logverbose("Configurations to test:\n%s" % self.configs)

        self.guests = []        
        guests = xenrt.pfarm([xenrt.PTask(self.host_entp.createBasicGuest, self.distro, name="entp_cps"),
                              xenrt.PTask(self.host_free.createBasicGuest, self.distro, name="free_cps")])
        for g in guests:
            g.shutdown()
            self.guests.append(g)
            self.guests.append(g.cloneVM(name = g.getName() + "_no"))
        xenrt.pmap(lambda g: g.start(), self.guests, interval = 5)

    def onEnterpriseServer(self, guest):
        return guest.getName().startswith("entp") or isinstance(guest.getHost(), xenrt.lib.xenserver.ClearwaterHost)

    def isCpsGuest(self, guest):
        return guest.getName().endswith("cps")

    def cpsSet(self, guest, num):
        xenrt.TEC().logverbose("Setting cores-per-socket argument to %i" % num)
        guest.paramSet("platform:cores-per-socket", num)
    
    def cpsGet(self, guest):
        if self.isCpsGuest(guest):
            try:
                return int(guest.paramGet("platform", "cores-per-socket"))
            except xenrt.XRTFailure: 
                pass
        
    def getCPUInfo(self, guest):
        info =  { 'sockets': guest.xmlrpcGetSockets(),
                  'cores': guest.xmlrpcGetCPUs() }
        xenrt.TEC().logverbose("CPU information on %s: %s" % (guest.getName(), info))
        return info

        
    def checkCPU(self, guest, cpu_conf, cpu_info):

        cps = None
        if self.isCpsGuest(guest) and cpu_conf.get('cps'):
            cps = self.cpsGet(guest)
            assert cps == cpu_conf['cps']
        if self.onEnterpriseServer(guest) and cps:
            flag = cpu_info['sockets'] == cpu_conf['sockets'] and cpu_info['cores'] == cpu_conf['cores']
        else:
            flag = cpu_info['sockets'] == cpu_info['cores'] == min(cpu_conf['cores'], (self.max_sockets or sys.maxint))
            
        log = "On %s, CPU configuration %s and information %s are %s." % \
              (guest.getName(), cpu_conf, cpu_info, (flag and "consistent" or "inconsistent"))
        xenrt.TEC().logverbose(log)
        return flag

    def run(self, arglist=[]):

        results = []

        for cpu_conf in self.configs:
            
            for guest in self.guests:

                xenrt.TEC().progress("Testing configuration %s on %s" % (cpu_conf, guest.getName()))

                guest.shutdown()
                
                guest.cpuset(cpu_conf['cores'])
                
                if self.isCpsGuest(guest):
                    if cpu_conf.has_key('cps'):
                        self.cpsSet(guest, cpu_conf['cps'])
                    elif self.cpsGet(guest):
                        guest.paramRemove("platform", "cores-per-socket")
                
                guest.start()
                cpu_info = self.getCPUInfo(guest)
                guest.suspend()
                guest.resume(check=False)
                cpu_info_1 = self.getCPUInfo(guest)
                guest.migrateVM(guest.getHost(), live="true")
                cpu_info_2 = self.getCPUInfo(guest)
                if cpu_info == cpu_info_1 == cpu_info_2:
                    xenrt.TEC().logverbose("CPU information remained the same "
                                           "after suspend/resume and live migration")
                else:
                    raise xenrt.XRTFailure("CPU information changed during the process "
                                           "of suspend/resume and live migration",
                                           data = (cpu_info, cpu_info_1, cpu_info_2))

                results.append((guest.getName(), cpu_conf, cpu_info_2))
                
                if not self.checkCPU(guest, cpu_conf, cpu_info_2):
                    raise xenrt.XRTFailure("CPU configuration and information inconsistent "
                                           "w.r.t. cores-per-socket setting",
                                           data = (guest.getName(), cpu_conf, cpu_info_2))

        xenrt.TEC().progress("The cores-per-sockets testcase ran successfully. The final results:\n%s" % results)

class TC10178(_TCCoresPerSocket):
    """Cores-per-socket parameter effectiveness on Windows VM"""
    pass

class _TCCoresPerSocketVariants(xenrt.TestCase):

    DISTRO = "win7-x86"
    CORES = 1
    SOCKETS = 1
    CPS = 1

    def prepare(self, arglist=[]):
        args = xenrt.util.strlistToDict(arglist)

        self.distro = args.get("distro") or self.DISTRO
        self.cps = args.get("cps") or self.CPS

        self.sockets = args.get("sockets") or self.SOCKETS
        self.cores = args.get("cores") or self.CORES

        xenrt.TEC().logverbose("SOCKETS is %s, CORES is %s" % (self.sockets, self.cores))

        self.setConfigs()

        xenrt.TEC().logverbose("Configurations to test:\n%s" % self.configs)

        self.host = self.getDefaultHost()

        self.guest = self.host.createBasicGuest(self.distro, name=self.distro)

    def setConfigs(self):
        self.configs = []
        self.configs.append({ 'sockets': int(self.sockets),
                              'cores': int(self.cores),
                              'cps': int(self.cps) }) # cores / sockets

    def cpsSet(self, num):
        xenrt.TEC().logverbose("Setting cores-per-socket argument to %i" % num)
        self.guest.paramSet("platform:cores-per-socket", num)

    def cpsGet(self):
        try:
            return int(self.guest.paramGet("platform", "cores-per-socket"))
        except xenrt.XRTFailure:
            pass

    def getCPUInfo(self):
        info =  { 'sockets': self.guest.xmlrpcGetSockets(),
                  'cores': self.guest.xmlrpcGetCPUs() }
        xenrt.TEC().logverbose("CPU information on %s: %s" % (self.guest.getName(), info))
        return info

    def run(self, arglist=[]):

        results = []

        for cpu_conf in self.configs:

            self.guest.shutdown()
            self.guest.cpuset(cpu_conf['cores'])
            self.cpsSet(cpu_conf['cps'])

            self.guest.start()
            cpu_info = self.getCPUInfo()

            self.guest.suspend()
            self.guest.resume(check=False)
            cpu_info_1 = self.getCPUInfo()

            self.guest.migrateVM(self.guest.getHost(), live="true")
            cpu_info_2 = self.getCPUInfo()

            if cpu_info == cpu_info_1 == cpu_info_2:
                xenrt.TEC().logverbose("CPU information remained the same "
                                       "after suspend/resume and live migration")
            else:
                raise xenrt.XRTFailure("CPU information changed during the process "
                                       "of suspend/resume and live migration",
                                       data = (cpu_info, cpu_info_1, cpu_info_2))

            results.append((self.guest.getName(), cpu_conf, cpu_info_2))

        xenrt.TEC().progress("The cores-per-sockets testcase ran successfully. The final results:\n%s" % results)

class TC21457(_TCCoresPerSocketVariants):
    """Verify cores-per-socket effectiveness using virtual single socket with 4 cores on Windows 8"""

    DISTRO = "win8-x64"
    CORES = 4
    SOCKETS = 1
    CPS = 4

class TC21458(_TCCoresPerSocketVariants):
    """Verify cores-per-socket effectiveness using virtual dual socket with 2 cores per socket on Windows 7"""

    DISTRO = "win7-x86"
    CORES = 4
    SOCKETS = 2
    CPS = 2

class TC21459(_TCCoresPerSocketVariants):
    """Verify cores-per-socket effectiveness using 5 cores with 3 cores per socket on Windows Server 2012 R2"""

    DISTRO = "ws12r2-x64"
    CORES = 5
    SOCKETS = 2
    CPS = 3

class TC21460(_TCCoresPerSocketVariants):
    """Verify cores-per-socket effectiveness using random configuration of cores and sockets"""

    DISTRO = "win7-x86"
    CORES = 4
    SOCKETS = 2
    CPS = 4

    def setConfigs(self):
        self.configs = []
        for i in range(int(math.log(self.sockets or self.SOCKETS, 2)) + 1):
            sockets = int(math.pow(2, i))
            for j in range(i, int(math.log(self.cores or
                                           sockets * self.cps, 2)) + 1):
                cores = int(math.pow(2, j))
                self.configs.append({ 'sockets': sockets,
                                      'cores': cores,
                                      'cps': cores / sockets })

class TC10549(xenrt.TestCase):
    """Testcase for SYMC-SFX - Preserver the Metadata on an exported VM"""
    def prepare(self):
        self.pool = self.getDefaultPool()
        guests = self.pool.master.listGuests()
        if guests == []:
            self.guest = self.pool.master.createGenericLinuxGuest()
        else:
            self.guest = self.pool.master.getGuest(guests[0])

        self.guestVIF = self.guest.getGuestVIFs()
        self.uuid = self.guest.getUUID()
        self.guestVIFuuid = self.pool.master.execdom0("xe vif-list vm-uuid=%s" % self.uuid)
        r = re.search("(\S+-\S+-\S+-\S+-\S+)", self.guestVIFuuid)
        if r:
            self.exportedVIF = r.group(0)
        self.guestVBDs = self.guest.listVBDUUIDs()
        self.srUUID = str(self.pool.master.execdom0("xe vdi-list vbd-uuids=%s | grep 'sr-uuid' | cut -d':' -f2" % (self.guestVBDs[1])))[1:-1]

    def run(self,arglist):
        self.pool.master.execdom0("xe vm-export uuid=%s filename=%s --metadata" % (self.uuid,self.guest.getName()))
        self.pool.master.execdom0("xe vm-destroy uuid=%s" % (self.uuid))
        self.pool.master.execdom0("xe vm-import filename=%s sr-uuid=%s --metadata --preserve" % (self.guest.getName(),self.srUUID))
        importedGuest = self.pool.master.execdom0("xe vm-list uuid=%s" % (self.uuid))
        importedVIF = self.pool.master.execdom0("xe vif-list vm-uuid%s" % self.uuid)
        r = re.search("(\S+-\S+-\S+-\S+-\S+)", importedVIF)
        if importedGuest == [] or r.group(0) != self.guestVIFuuid:
            raise xenrt.XRTFailure("The imported VM's UUID/VIF differs from the exported")
            
class TC13206(xenrt.TestCase):
    """Test the CD drive stay working after a migrate."""
    
    def run(self,arglist):
        
        # default sr must be lvmoiscsi
        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")
        
        g = host0.createGenericWindowsGuest()
        g.changeCD("win7-x86.iso")
        time.sleep(30)

        g.migrateVM(host1, live="true")
        time.sleep(30)
        
        # should be able to read cd-drive after migrate
        data = g.xmlrpcReadFile("D:\\autorun.inf")
        
        if not data or not "setup.exe" in data:
            raise xenrt.XRTError("Could not read from CD Drive")
            
class TC13496(xenrt.TestCase):
    """Test guest can't hang Xen on 2nd CPU bringup (potential DOS attack) CA-53626"""
    
    def run(self,arglist):
    
        host = self.getHost("RESOURCE_HOST_0")
        
        try:
            host.execdom0('mkdir -p /boot/guest')
        except:
            xenrt.TEC().skip("Can't write to dom0 fs. Skipping")
            return
        
        host.execdom0("wget '%s/domucrashxen.tgz' -O - | tar -zx -C /tmp" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")))
        host.execdom0("mv /tmp/domucrashxen/netbsd-domU-crashxen /boot/guest/netbsd-domU-crashxen")
        
        guest = host.createGenericLinuxGuest(start=False, vcpus=2)
        self.uninstallOnCleanup(guest)
        
        host.execdom0('xe vm-param-set uuid=%s PV-bootloader="" PV-args="" PV-kernel="/boot/guest/netbsd-domU-crashxen"' % guest.uuid)
        host.execdom0('xe vm-start uuid=%s' % guest.uuid)
        
        for i in range(10):
            time.sleep(5)
            host.checkHealth()
            
        guest2 = host.createGenericLinuxGuest(start=True)
        self.uninstallOnCleanup(guest2)
        guest2.checkHealth()
        host.checkHealth()
        
class VbdProtocolCheck(xenrt.TestCase):
    """To make sure the protocol field is defined for VBD attached for corresponding ISO -- CA-26800"""
    def __init__(self, tcid="VbdProtocolCheck"):
        xenrt.TestCase.__init__(self, tcid)
        self.guestsToClean = []
    def run(self, arglist=None):
        host = xenrt.TestCase().getHost("RESOURCE_HOST_0")
        arg = re.split("=", arglist[0])
        if arg[0] == "guest":
                guest = host.getGuest(arg[1])
        protocol_vbd = guest.host.execdom0("xenstore-ls /local/domain/%s/device/vbd | grep protocol; exit 0" % (guest.getDomid()))
        xenrt.TEC().logverbose("---> %s" % protocol_vbd)
        if(re.search(r"64", guest.execcmd("arch"))):
            if not(re.search(r"64",protocol_vbd)):
                raise xenrt.XRTFailure("VBD Protocol Field empty or not as expected")
        else :
            if not(re.search(r"32",protocol_vbd)):
                raise xenrt.XRTFailure("VBD Protocol Field empty or not as expected")
        xenrt.TEC().logverbose("Protocol field verified after stop, start")
        #Perform Suspend, Resume
        guest.host.listDomains()
        guest.suspend()
        guest.host.checkHealth()
        guest.host.listDomains()
        guest.resume()
        guest.host.checkHealth()
        protocol_vbd = guest.host.execdom0("xenstore-ls /local/domain/%s/device/vbd | grep protocol; exit 0" % (guest.getDomid()))
        xenrt.TEC().logverbose("---> %s" % protocol_vbd)
        if(re.search(r"64", guest.execcmd("arch"))):
            if not(re.search(r"64",protocol_vbd)):
                raise xenrt.XRTFailure("VBD Protocol Field empty or not as expected")
        else :
            if not(re.search(r"32",protocol_vbd)):
                raise xenrt.XRTFailure("VBD Protocol Field empty or not as expected")
        xenrt.TEC().logverbose("Protocol field verified after suspend, resume")
        #Perform Reboot
        guest.host.listDomains()
        guest.reboot()
        guest.host.checkHealth()
        protocol_vbd = guest.host.execdom0("xenstore-ls /local/domain/%s/device/vbd | grep protocol; exit 0" % (guest.getDomid()))
        xenrt.TEC().logverbose("---> %s" % protocol_vbd)
        if(re.search(r"64", guest.execcmd("arch"))):
            if not(re.search(r"64",protocol_vbd)):
                raise xenrt.XRTFailure("VBD Protocol Field empty or not as expected")
        else :
            if not(re.search(r"32",protocol_vbd)):
                raise xenrt.XRTFailure("VBD Protocol Field empty or not as expected")
        xenrt.TEC().logverbose("Protocol field verified after reboot")
        guest.host.checkHealth()
        # Perform a localhost live migrate
        guest.migrateVM(host)
        protocol_vbd = guest.host.execdom0("xenstore-ls /local/domain/%s/device/vbd | grep protocol; exit 0" % (guest.getDomid()))
        xenrt.TEC().logverbose("---> %s" % protocol_vbd)
        if(re.search(r"64", guest.execcmd("arch"))):
            if not(re.search(r"64",protocol_vbd)):
                raise xenrt.XRTFailure("VBD Protocol Field empty or not as expected")
        else :
            if not(re.search(r"32",protocol_vbd)):
                raise xenrt.XRTFailure("VBD Protocol Field empty or not as expected")
        xenrt.TEC().logverbose("Protocol field verified after Migrate")


class TC18568(xenrt.TestCase):
    """Test switching between legacy and new drivers."""
    
    def doGuest(self, g):
        try:
            xenrt.TEC().config.setVariable("USE_LEGACY_DRIVERS", "no") 
            step("Installing new drivers on " + g.getName())
            g.installDrivers()
            step("Uninstalling new drivers on " + g.getName())
            g.uninstallDrivers()
            xenrt.TEC().config.setVariable("USE_LEGACY_DRIVERS", "yes") 
            step("Installing legacy drivers on " + g.getName())
            g.installDrivers()
            xenrt.TEC().config.setVariable("USE_LEGACY_DRIVERS", "no") 
        except Exception, e:
            g.checkHealth()
            raise
    
    def run(self, arglist=None):
        for g in self.getDefaultHost().guests.values():
            self.getLogsFrom(g)
            self.runSubcase("doGuest", (g), "TC18568", g.getName())

class TCCauseBsod(xenrt.TestCase):
    """Try and cause a BSOD with the new drivers."""
    
    def run(self, arglist=None):
        for g in self.getDefaultHost().guests.values():
            
            g.installDrivers()
            g.shutdown()
            snap = g.snapshot()
            
            for i in range(100):
                try:
                    for j in range(3):
                        g.start()
                        g.shutdown()
                except Exception, e:
                    xenrt.GEC().dbconnect.jobLogData(self.getPhase(), str(self.basename), "comment", str(e))
                    if g.getState() == "UP":
                        g.shutdown(force=True)
                
                g.revert(snap)
                
                
class TCDriverInstallLoop(xenrt.TestCase):
    
    def run(self, args=None):
        gname = ""
        for arg in args:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
                break

        if len(gname) == 0:
            raise xenrt.XRTFailure("No guest")
        
        g = self.getGuest(gname)
        g.shutdown()
        snap = g.snapshot()
        
        for i in range(1000):
            g.start()
            g.installDrivers()
            g.shutdown()
            g.revert(snap)
            g.enlightenedDrivers = False
                    
class _TCToolstackRestart(xenrt.TestCase):
    XAPI_RESTART_DELAY_SECONDS = 60

    def _delayToolstackRestart(self, host):
        # Update the xe-toolstack-restart script to delay restart for N seconds
        host.execdom0('cp /opt/xensource/bin/xe-toolstack-restart /opt/xensource/bin/xe-toolstack-restart.orig')
        data = host.execdom0('cat /opt/xensource/bin/xe-toolstack-restart')
        newData = re.sub('set -e\n', 'set -e\nsleep %d\n' % (self.XAPI_RESTART_DELAY_SECONDS), data) 
        host.execdom0("echo '%s' > /opt/xensource/bin/xe-toolstack-restart" % (newData))

    def _restoreOriginalTSRestartScript(self, host):
        try:
            host.execdom0('cp /opt/xensource/bin/xe-toolstack-restart.orig /opt/xensource/bin/xe-toolstack-restart')
        except Exception, e:
            xenrt.TEC().logverbose('Failed to restore xe-toolstack-restart script: %s' % (str(e)))

    def prepare(self, arglist=[]):
        self.hosts = []
        self.guests = []
        pool = self.getDefaultPool()
        if pool:
            self.hosts = pool.getHosts()
            self.guests = []
            for host in self.hosts:
                self.guests += host.guests.values()
        else:
            self.hosts.append(self.getDefaultHost())
            self.guests = self.hosts[0].guests.values()

        if len(self.hosts) == 0:
            raise xenrt.XRTError('Failed to find any hosts')
        if len(self.guests) == 0:
            raise xenrt.XRTError('Failed to find any guests')

        xenrt.TEC().logverbose('Executing tests on host(s): %s' % (self.hosts))
        xenrt.TEC().logverbose('Executing tests on guests(s): %s' % (self.guests))

        map(lambda x:self._delayToolstackRestart(x), self.hosts)

    def _waitHostEnabled(self, host):
        while True:
            if host.paramGet('enabled') == 'true':
                break
            else:
                xenrt.sleep(1)

    def _domainRunning(self, host, guest):
        domList = host.listDomains()
        return domList.has_key(guest.getUUID())

    def postRun(self):
        map(lambda x:self._restoreOriginalTSRestartScript(x), self.hosts)

class TC18692(_TCToolstackRestart):
    
    def _guestShutdown(self, host):
        guests = filter(lambda x:x.host == host, self.guests)
        guestVdis = []
        for guest in guests:
            guestVdis += guest.getAttachedVDIs()

        xenrt.TEC().logverbose("Tapdisks present before shutdown")
        host.execdom0('tap-ctl list')
        xenrt.TEC().logverbose('Toolstack restart tests for Host: %s' % (host.getName()))
        host.execdom0('/opt/xensource/bin/xe-toolstack-restart < /dev/null > /dev/null 2>&1 &')
        # Wait for the toolstack to shutdown
        xenrt.sleep(5)

        xenrt.TEC().logverbose('Using guests: %s' % (map(lambda x:x.name, guests)))
        for guest in guests:
            if guest.windows:
                guest.xmlrpcShutdown()
            else:
                guest.execguest('shutdown -h now')

        host.waitForXapi(timeout=self.XAPI_RESTART_DELAY_SECONDS*2, local=True)
        self._waitHostEnabled(host)

        host.execdom0("list_domains -all")
        # Check that VM tap-disks have been cleaned up after shutdown.
        xenrt.TEC().logverbose("Tapdisks present after shutdown")
        tds = host.execdom0('tap-ctl list').splitlines()
        for td in tds:
            if len(filter(lambda x:x in td, guestVdis)) > 0:
                xenrt.TEC().logverbose('tap-disk not deactivated: %s' % (td))
                raise xenrt.XRTFailure('tap-disk still there after shutdown')
        map(lambda x:x.poll('DOWN'), guests)
        map(lambda x:x.start(), guests)

        host.verifyHostFunctional(migrateVMs=True)

    def run(self, arglist=[]):
        map(lambda x:self._guestShutdown(x), self.hosts)


class TC18693(_TCToolstackRestart):

    def _guestReboot(self, host):
        xenrt.TEC().logverbose('Toolstack restart tests for Host: %s' % (host.getName()))
        host.execdom0('/opt/xensource/bin/xe-toolstack-restart < /dev/null > /dev/null 2>&1 &')
        # Wait for the toolstack to shutdown
        xenrt.sleep(5)

        guests = filter(lambda x:x.host == host, self.guests)
        xenrt.TEC().logverbose('Using guests: %s' % (map(lambda x:x.name, guests)))
        for guest in guests:
            if guest.windows:
                guest.xmlrpcReboot()
            else:
                guest.execguest('shutdown -r now')

        host.waitForXapi(timeout=self.XAPI_RESTART_DELAY_SECONDS*2, local=True)
        self._waitHostEnabled(host)
        for guest in guests:
            if guest.getState() == 'DOWN':
                if self._domainRunning(host, guest):
                    xenrt.TEC().logverbose('XAPI reports Guest: %s down' % (guest.getName()))
                    raise xenrt.XRTFailure('XAPI reports guest down when running domain exists')
                else:
                    xenrt.TEC().logverbose('Guest: %s did not restart' % (guest.getName()))
                    guest.start()
            else:
                retries = 3
                while not self._domainRunning(host, guest):
                    xenrt.TEC().warning('XAPI reports Guest %s in state %s - domain not listed / shutdown' % (guest.getName(), guest.getState()))
                    if retries > 0:
                        retries -= 1
                        xenrt.sleep(10)
                    else:
                        raise xenrt.XRTFailure('Domain reported as running but not listed / shutdown in domain list')
                    
        # Wait for guests to fully reboot
        for guest in guests:
            if guest.windows:
                guest.waitForAgent(300)
            else:
                guest.waitForSSH(timeout=60)

        host.verifyHostFunctional(migrateVMs=True)

    def run(self, arglist=[]):
        map(lambda x:self._guestReboot(x), self.hosts)

class TC18694(_TCToolstackRestart):

    def _guestDelete(self, host):
        guests = filter(lambda x:x.host == host, self.guests)
        xenrt.TEC().logverbose('Toolstack restart tests for Host: %s' % (host.getName()))
        host.execdom0('/opt/xensource/bin/xe-toolstack-restart < /dev/null > /dev/null 2>&1 &')
        # Wait for the toolstack to shutdown
        xenrt.sleep(5)
        host.waitForXapi(timeout=self.XAPI_RESTART_DELAY_SECONDS*2, local=True)
        self._waitHostEnabled(host)
        # Wait for [Windows] guests to fully reboot
        map(lambda x:x.checkReachable(timeout=180), guests)

        # Shutdown the guests
        map(lambda x:x.shutdown(), guests)
        map(lambda x:x.uninstall(), guests)
        
    def run(self, arglist=[]):
        map(lambda x:self._guestDelete(x), self.hosts)

class TC18696(xenrt.TestCase):

    def prepare(self, arglist=[]):
        pool = self.getDefaultPool()
        self.master = pool.master
        self.slave = pool.slaves.values()[0]
        self.guest = filter(lambda x:x.host == self.master, self.master.guests.values())[0]
        xenrt.TEC().logverbose('Master: %s, Slave: %s, Guest: %s' % (self.master, self.slave, self.guest.name))
        
        slaveManPIFUUID = self.slave.minimalList('pif-list', 'uuid', 'management=true host-name-label=%s' % (self.slave.getName()))[0]
        self.slaveManMac = self.slave.genParamGet('pif', slaveManPIFUUID, 'MAC')

    def delayDisableNetPort(self, delay):
        xenrt.sleep(delay)
        xenrt.TEC().logverbose('Disabling NET PORT for MAC: %s' % (self.slaveManMac))
        self.slave.disableNetPort(self.slaveManMac)

    def migrateVM(self):
        xenrt.TEC().logverbose('Migrating VM: %s to host: %s' % (self.guest.name, self.slave.getName()))
        try:
            self.guest.migrateVM(self.slave, live='true')
        except Exception, e:
            xenrt.TEC().logverbose('Migration failed with error: %s' % (str(e)))

    def run(self, arglist=[]):
        pTasks = [xenrt.PTask(self.migrateVM), xenrt.PTask(self.delayDisableNetPort, 7)]
        xenrt.pfarm(pTasks)

        self.slave.enableNetPort(self.slaveManMac)
        self.slave.waitForSSH(timeout=600)
        masterDomainList = self.master.listDomains(includeS=True)
        slaveDomainList = self.slave.listDomains(includeS=True)

        xenrt.TEC().logverbose('Guest in (XAPI) state: %s after failed migrate' % (self.guest.getState()))

        if not masterDomainList.has_key(self.guest.uuid):
            xenrt.TEC().logverbose('Guest not in domain list on master after failed migrate')
        else:
            if masterDomainList[self.guest.uuid][3] != self.master.STATE_RUNNING:
                xenrt.TEC().logverbose('Guest not in running state from master domain list after failed migrate')

        if slaveDomainList.has_key(self.guest.uuid):
            raise xenrt.XRTFailure('Guest domain found on slave after failed migrate')

        if len(filter(lambda x:'deadbeef' in x, masterDomainList.keys())) != 0:
            raise xenrt.XRTFailure('DEADBEEF domain found on master after failed migrate')
        if len(filter(lambda x:'deadbeef' in x, slaveDomainList.keys())) != 0:
            raise xenrt.XRTFailure('DEADBEEF domain found on slave after failed migrate')

        if self.guest.getState() == 'SUSPENDED':
            xenrt.TEC().logverbose('Attempt to restore suspended guest')
            self.guest.shutdown(force=True)
            self.guest.start()
        elif self.guest.getState() != 'UP':
            raise xenrt.XRTFailure('Guest not in (XAPI) SUSPENDED or UP state after failed migration')

        self.master.verifyHostFunctional(migrateVMs=True)            
        self.slave.verifyHostFunctional(migrateVMs=True)            

class _WMI(xenrt.TestCase):
    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        
        # Get the sequence variables
        if arglist and len(arglist) > 0:
            for arg in arglist:
                l = string.split(arg, "=", 1)
                if l[0] == "guest":
                    guestName = l[1]

        self.guest = xenrt.TEC().registry.guestGet(guestName)
        if self.guest.getState() == "DOWN":
            self.guest.start()
        self.guest.installPowerShell20()
        self.guest.enablePowerShellUnrestricted()
        self.guest.xmlrpcSendRecursive("%s/data/tests/wmi" % (xenrt.TEC().lookup("XENRT_BASE")), "c:\\wmi")
        

class WMIPowerShell(_WMI):
    def run(self, arglist):
        data = self.guest.xmlrpcExec("powershell.exe -ExecutionPolicy ByPass -File c:\\wmi\\testwmi.ps1", returndata=True)
        xenrt.TEC().logverbose(data)
        if "Exception" in data:
            raise xenrt.XRTFailure("Unexpected return data from powershell")
            

class WMIVBS(_WMI):
    def run(self, arglist):
        data = self.guest.xmlrpcExec("cscript /NoLogo c:\\wmi\\testwmi.vbs", returndata=True)
        xenrt.TEC().logverbose(data)

class WMICheckVMName(_WMI):
    def run(self, arglist):
        data = self.guest.xmlrpcExec("powershell.exe -ExecutionPolicy ByPass -File c:\\wmi\\xenstoreread.ps1 name", returndata=True)
        xenrt.TEC().logverbose(data)
        if "Exception" in data:
            raise xenrt.XRTFailure("Unexpected return data from powershell")
        if data.strip().splitlines()[-1] != self.guest.getName():
            raise xenrt.XRTFailure("Name from WMI didn't match VM name")
 
class WMICheckVMIP(_WMI):
    def run(self, arglist):
        data = self.guest.xmlrpcExec("powershell.exe -ExecutionPolicy ByPass -File c:\\wmi\\xenstoreread.ps1 attr/eth0/ip", returndata=True)
        xenrt.TEC().logverbose(data)
        if "Exception" in data:
            raise xenrt.XRTFailure("Unexpected return data from powershell")
        if data.strip().splitlines()[-1] != self.guest.getIP():
            raise xenrt.XRTFailure("IP from WMI didn't match VM IP")

class WMICheckXenStoreRead(_WMI):
    def run(self, arglist):
        self.host.execdom0("xenstore-write /local/domain/%d/xenrt-wmireadtest xenrt-ping" % self.guest.getDomid())
        data = self.guest.xmlrpcExec("powershell.exe -ExecutionPolicy ByPass -File c:\\wmi\\xenstoreread.ps1 xenrt-wmireadtest", returndata=True)
        xenrt.TEC().logverbose(data)
        if "Exception" in data:
            raise xenrt.XRTFailure("Unexpected return data from powershell")
        if data.strip().splitlines()[-1] != "xenrt-ping":
            raise xenrt.XRTFailure("Data read using WMI didn't match data written to xenstore")

        
class WMICheckXenStoreWrite(_WMI):
    def run(self, arglist):
        data = self.guest.xmlrpcExec("powershell.exe -ExecutionPolicy ByPass -File c:\\wmi\\xenstorewrite.ps1 data/xenrt-wmiwritetest xenrt-pong", returndata=True)
        xenrt.TEC().logverbose(data)
        if "Exception" in data:
            raise xenrt.XRTFailure("Unexpected return data from powershell")
        readdata = self.host.execdom0("xenstore-read /local/domain/%d/data/xenrt-wmiwritetest" % self.guest.getDomid())
        if readdata.strip() != "xenrt-pong":
            raise xenrt.XRTFailure("Data read from xenstore didn't match data written using WMI")

class TCLotsOfKernels(xenrt.TestCase):
    """Copies and tests all kernels from /home/jbulpin/K and /home/daniellam/K"""
    
    def run(self, arglist):
        host = self.getDefaultHost()
        cli = host.getCLIInstance()
        host.execdom0("mkdir -p /boot/guest")
        td = xenrt.TEC().tempDir()
        
        xenrt.command("scp xenrtd@qa-01.uk.xensource.com:/home/jbulpin/K/* %s" % td)
        xenrt.command("scp xenrtd@qa-01.uk.xensource.com:/home/daniellam/K/* %s" % td)

        sftp = host.sftpClient()
        try:
            for k in xenrt.command("(cd %s && ls)" % td).strip().splitlines():
                if not ".sh" in k:
                    sftp.copyTo("%s/%s" % (td, k), "/boot/guest/%s" % k)
                    uuid = cli.execute('vm-create', 'name-label=%s' % k).strip()
                    cli.execute('vm-param-set', 'uuid=%s PV-kernel=/boot/guest/%s' % (uuid, k))
                    
                    try:
                        ret = cli.execute('vm-start', 'uuid=%s' % uuid)
                    except Exception, e:
                        xenrt.TEC().logverbose(str(e))
                    time.sleep(2)
                    
                    try:
                        cli.execute("vm-shutdown", "uuid=%s --force" % uuid)
                    except:
                        pass
        finally:
            sftp.close()

class TCVerifyHvmSerialRedirection(xenrt.TestCase):
    """Verify that parameter 'platform:hvm_serial' takes precedence over 'other_config:hvm_serial'.
    These parameters are used for redirecting guest serial output.
    Regression test for CA-109295"""

    def doHvmSerialRedirect(self, redirectParam, file):
        self.guest.paramSet(redirectParam, "file:%s"%file)
        self.guest.reboot()

    def checkSerialOutput(self, file):
        log('Checking guest serial output file : %s' % file)
        if self.host.execdom0('test -e %s' % file, retval="code") == 0:
            if int(self.host.execdom0("cat %s | wc -l" % file).strip()):
                return
        raise xenrt.XRTFailure("No output found in redirected guest serial output file")

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericWindowsGuest()
        self._guestsToUninstall.append(self.guest)

    def run(self, arglist):
        SerialFileOC = '/tmp/consoleUsingOtherConfig.log'
        SerialFileP = '/tmp/consoleUsingPlatform.log'

        step('Redirect guest serial output to a file using other-config:hvm_serial')
        self.doHvmSerialRedirect("other-config:hvm_serial",SerialFileOC)

        step('Check redirection is working with other-config:hvm_serial')
        self.checkSerialOutput(SerialFileOC)

        step('Redirect guest serial output to a file using platform:hvm_serial')
        self.doHvmSerialRedirect("platform:hvm_serial",SerialFileP)

        step('Check redirection is working with platform:hvm_serial')
        self.checkSerialOutput(SerialFileP)

class TCCycle(xenrt.TestCase):

    def run(self, arglist):
        
        h = self.getDefaultHost()
        g = self.getGuest("guest")
        
        if g.getState() == "UP":
            g.shutdown(force=True)
        
        h.execdom0("cd /root && wget ftp://10.80.3.21/cycle.sh")
        h.execdom0("wget ftp://10.80.3.21/sd.py")
        h.execdom0("chmod +x cycle.sh")
        h.execdom0("chmod +x sd.py")
        h.execdom0("./cycle.sh %s %s" % (g.getUUID(), g.mainip), timeout=86400)


class TCWinSMBFileTransfer(xenrt.TestCase):
    INTERNAL_TEST_NETWORK_NAME = 'internal-test-nw'
    SHARE_PATH = 'c:\\xenrtshare'

    # Address keys
    IPV4_ADDR_KEY = 'IPv4 Address'
    IPV6_ADDR_KEY = 'IPv6 Address'
    IPV4_LINK_LOCAL_ADDR_KEY = 'Autoconfiguration IPv4 Address'
    IPV6_LINK_LOCAL_ADDR_KEY = 'Link-local IPv6 Address'

    USE_LINK_LOCAL_ADDRESSES = False

    def createTestTranferFile(self, guest, path, sizeMB):
        filename = 'xenrt-%s.dat' % (''.join(random.sample(string.ascii_lowercase + string.ascii_uppercase, 6)))
        guest.xmlrpcExec('fsutil file createnew %s%s %d' % (path, filename, (sizeMB * xenrt.MEGA)))
        return filename

    def getSMBShareName(self, guest):
        return '%s-share' % (guest.getName())

    def createSMBShare(self, shareName, sharePath, guest):
        if not guest.xmlrpcDirExists(sharePath):
            guest.xmlrpcCreateDir(sharePath)
        guest.xmlrpcExec('net share %s=%s /grant:everyone,full' % (shareName, sharePath))

    def addGuestsToInternalNetwork(self, host, guests, device='1'):
        networkInfo = host.parameterList('network-list', ['name-label', 'uuid'])
        internalTestNw = filter(lambda x:x['name-label'] == self.INTERNAL_TEST_NETWORK_NAME, networkInfo)
        if len(internalTestNw) == 0:
            internalTestNwUUID = host.createNetwork(name=self.INTERNAL_TEST_NETWORK_NAME)
        else:
            internalTestNwUUID = internalTestNw[0]['uuid']

        cli = host.getCLIInstance()
        for guest in guests:
            intNwVIFs = guest.getVIFs(network=self.INTERNAL_TEST_NETWORK_NAME)
            if not intNwVIFs.keys():
                uuid = cli.execute("vif-create", "vm-uuid=%s network-uuid=%s device=%s mac=%s" % (guest.uuid, internalTestNwUUID, device, xenrt.randomMAC()), strip=True)
                cli.execute('vif-plug uuid=%s' % (uuid))

                # There seems to be a problem with VIF hot-plug - reboot the guests
                guest.reboot()

    def getInterfaceIPAddr(self, guest, device, addressKey):
        winInterfaceName = guest.getWindowsInterface(device)
        ipConfigData = guest.getWindowsIPConfigData()
        if not ipConfigData.has_key(winInterfaceName):
            raise xenrt.XRTError('Failed to get IP config data for interface: %s' % (winInterfaceName))
        interfaceIpConfig = ipConfigData[winInterfaceName]

        if not interfaceIpConfig.has_key(addressKey):
            raise xenrt.XRTError('Failed to find address key %s for interface: %s' % (addressKey, winInterfaceName))

        addr = interfaceIpConfig[addressKey].replace('(Preferred)', '')

        xenrt.TEC().logverbose('Found [%s] address for interface: %s, %s' % (addressKey, winInterfaceName, addr))
        return addr

    def installSha1SumUtility(self, guest):
        if not guest.xmlrpcFileExists("c:\\sha1sum.exe"):
            guest.xmlrpcSendFile("%s/utils/sha1sum.exe" % (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")), "c:\\sha1sum.exe")        

    def timedFileCopy(self, initiatingGuest, fromLocation, toLocation, useRoboCopy=False, robocopyFile=None, disallowRoboCopyRetries=True):
        startTime = datetime.now()

        if useRoboCopy:
            robocopyArgs = ''
            if disallowRoboCopyRetries:
                robocopyArgs += ' -R:0'
            if robocopyFile:
                robocopyArgs += ' -IF %s' % (robocopyFile)
            rcode = initiatingGuest.xmlrpcExec('robocopy %s %s %s' % (fromLocation, toLocation, robocopyArgs), returnerror=False, returnrc=True, timeout=1800)
            if rcode != 1:
                xenrt.TEC().warning('RoboCopy returned with unexpected error code: %s' % (rcode))
        else:
            initiatingGuest.xmlrpcExec('copy %s %s' % (fromLocation, toLocation), timeout=1800)

        timeDelta = datetime.now() - startTime
        xenrt.TEC().logverbose('Tranfer initiated by %s from %s to %s completed in %d seconds' % (initiatingGuest, fromLocation, toLocation, timeDelta.seconds))

        return timeDelta.seconds
   
    def getCopyDurationFromRobocopyLog(self, guest, robocopyLogFile, expectedFilesCopied=None):
        logData = guest.xmlrpcReadFile(robocopyLogFile)
        if logData:
            xenrt.TEC().logverbose(logData)
        data = map(lambda x:x.split(), logData.splitlines())
        data = filter(lambda x:len(x) > 0, data)
        filesData = filter(lambda x:x[0] == 'Files', data)
        if len(filesData) != 1:
            xenrt.TEC().logverbose('Failed to parse robocopy log')
            map(lambda x:xenrt.TEC().logverbose(x), logData.splitlines())
            raise xenrt.XRTError('Failed to parse robocopy log')
        filesData = filesData[0]
        timesData = filter(lambda x:x[0] == 'Times', data)[0] 
        
        xenrt.TEC().logverbose('Robocopy files summary: Total: %d, Copied: %d, Skipped: %d, Mismatch: %d, FAILED: %d, Extras: %d' % (int(filesData[2]),
                                                                                                                                     int(filesData[3]),
                                                                                                                                     int(filesData[4]),
                                                                                                                                     int(filesData[5]),
                                                                                                                                     int(filesData[6]),
                                                                                                                                     int(filesData[7])))
        if expectedFilesCopied != None and expectedFilesCopied != int(filesData[3]):
            raise xenrt.XRTFailure('robocopy failed to copy expected number of files')

        duration = timedelta(hours   = int(timesData[2].split(':')[0]),
                             minutes = int(timesData[2].split(':')[1]),
                             seconds = int(timesData[2].split(':')[2]))
        return duration.seconds

    def timedRobocopy(self, initiatingGuest, fromLocation, toLocation, robocopyFile=None, disallowRoboCopyRetries=True):
        durationSeconds = 0
        robocopyLogFile = 'c:\\xenrt-robocopy.log'
        robocopyArgs = '/np /njh /log:%s' % (robocopyLogFile)
        if disallowRoboCopyRetries:
            robocopyArgs += ' /r:0'
        if robocopyFile:
            robocopyArgs += ' /if %s' % (robocopyFile)

        rcode = initiatingGuest.xmlrpcExec('robocopy %s %s %s' % (fromLocation, toLocation, robocopyArgs), returnerror=False, returnrc=True, timeout=1800)
        if rcode != 1:
            xenrt.TEC().warning('RoboCopy returned with unexpected error code: %s' % (rcode))

        durationSeconds = self.getCopyDurationFromRobocopyLog(initiatingGuest, robocopyLogFile, expectedFilesCopied=1)
        xenrt.TEC().logverbose('Tranfer initiated by %s from %s to %s completed in %d seconds' % (initiatingGuest, fromLocation, toLocation, durationSeconds))

        return durationSeconds

    def pushFile(self, initiatingGuest, guestWithShare, shareAddress, sizeMB, useRoboCopy=False):
        srcFilePath = 'c:\\'
        filename = self.createTestTranferFile(initiatingGuest, srcFilePath, sizeMB)
        
        fullPathToSrcFile = '%s%s' % (srcFilePath, filename)
        fileSha1Sum = initiatingGuest.xmlrpcSha1Sum(fullPathToSrcFile)

        if useRoboCopy:
            duration = self.timedRobocopy(initiatingGuest, srcFilePath, '\\\\%s\\%s' % (shareAddress, self.getSMBShareName(guestWithShare)), robocopyFile=filename)
        else:
            duration = self.timedFileCopy(initiatingGuest, fullPathToSrcFile, '\\\\%s\\%s\\%s' % (shareAddress, self.getSMBShareName(guestWithShare), filename))

        fullPathToDestFile = '%s\\%s' % (self.SHARE_PATH, filename)
        newSha1Sum = guestWithShare.xmlrpcSha1Sum(fullPathToDestFile)
        if newSha1Sum != fileSha1Sum:
            xenrt.TEC().logverbose('Checksums do not match after file transfer.  Original: %s, New: %s' % (fileSha1Sum, newSha1Sum))
            raise xenrt.XRTFailure('Checksums do not match after file transfer')            

        initiatingGuest.xmlrpcExec('del %s' % (fullPathToSrcFile))
        guestWithShare.xmlrpcExec('del %s' % (fullPathToDestFile))
        return duration

    def pullFile(self, initiatingGuest, guestWithShare, shareAddress, sizeMB, useRoboCopy=False):
        srcFilePath = '%s\\' % (self.SHARE_PATH)
        filename = self.createTestTranferFile(guestWithShare, srcFilePath, sizeMB)

        fullPathToSrcFile = '%s%s' % (srcFilePath, filename)
        fileSha1Sum = guestWithShare.xmlrpcSha1Sum(fullPathToSrcFile)

        destFilePath = 'c:\\'
        fullPathToDestFile = '%s%s' % (destFilePath, filename)
        if useRoboCopy:
            duration = self.timedRobocopy(initiatingGuest, '\\\\%s\\%s' % (shareAddress, self.getSMBShareName(guestWithShare)), destFilePath, robocopyFile=filename)
        else:
            duration = self.timedFileCopy(initiatingGuest, '\\\\%s\\%s\\%s' % (shareAddress, self.getSMBShareName(guestWithShare), filename), fullPathToDestFile)

        newSha1Sum = initiatingGuest.xmlrpcSha1Sum(fullPathToDestFile)
        if newSha1Sum != fileSha1Sum:
            xenrt.TEC().logverbose('Checksums do not match after file transfer.  Original: %s, New: %s' % (fileSha1Sum, newSha1Sum))
            raise xenrt.XRTFailure('Checksums do not match after file transfer')

        initiatingGuest.xmlrpcExec('del %s' % (fullPathToDestFile))
        guestWithShare.xmlrpcExec('del %s' % (fullPathToSrcFile))
        return duration

    def doTransfer(self, pushFile, iterations, averageDurationThreshold, guestPair, useIPv4, sizeMB, useRoboCopy):
        operationStr = pushFile and 'Push file' or 'Pull file'
        copyTypeStr = useRoboCopy and 'RoboCopy' or 'copy'
        ipVersionStr = useIPv4 and 'IPv4' or 'IPv6'

        if self.USE_LINK_LOCAL_ADDRESSES:
            addressKey = useIPv4 and self.IPV4_LINK_LOCAL_ADDR_KEY or self.IPV6_LINK_LOCAL_ADDR_KEY
        else:
            addressKey = useIPv4 and self.IPV4_ADDR_KEY or self.IPV6_ADDR_KEY

        for (initiatingGuest, guestWithShare) in [(guestPair[0], guestPair[1]), (guestPair[1], guestPair[0])]:
            xenrt.TEC().logverbose('%s (using %s) initiated by %s to/from share on %s using %s - file size %d MB' % (operationStr, copyTypeStr, 
                                                                                                                     initiatingGuest.getName(), guestWithShare.getName(), 
                                                                                                                     ipVersionStr, sizeMB))
            shareAddress = self.getInterfaceIPAddr(guestWithShare, device='1', addressKey=addressKey)
            if self.USE_LINK_LOCAL_ADDRESSES and not useIPv4:
                initiatingGuestZoneId = self.getInterfaceIPAddr(initiatingGuest, device='1', addressKey=addressKey).split('%')[1]
                xenrt.TEC().logverbose('Using initiating guest Zone ID: %s' % (initiatingGuestZoneId))
                shareAddress = shareAddress.split('%')[0] + '%%' + initiatingGuestZoneId

            if pushFile:
                durations = map(lambda x:self.pushFile(initiatingGuest, guestWithShare, shareAddress, sizeMB, useRoboCopy), range(iterations))
            else:
                durations = map(lambda x:self.pullFile(initiatingGuest, guestWithShare, shareAddress, sizeMB, useRoboCopy), range(iterations))

            xenrt.TEC().logverbose('%d iterations, Min: %d, Max: %d, Mean: %f' % (iterations, min(durations), max(durations), numpy.mean(durations))) 
            xenrt.TEC().comment('%s (using %s) initiated by %s to/from share on %s using %s - file size %d MB: Average Duration (sec): %d' % (operationStr, copyTypeStr,
                                                                                                                  initiatingGuest.getName(), guestWithShare.getName(),
                                                                                                                  ipVersionStr, sizeMB, numpy.mean(durations)))
            if numpy.mean(durations) > averageDurationThreshold:
                xenrt.TEC().logverbose('Threshold exceeded for Windows internal network SMB file transfer. Threshold: %d, Average Duration: %f' % (averageDurationThreshold, numpy.mean(durations)))
                raise xenrt.XRTFailure('File transfer threashold exceeded')



class TCHostInternalWinSMB(TCWinSMBFileTransfer):
    USE_LINK_LOCAL_ADDRESSES = True

    def prepare(self, arglist):
        host = self.getDefaultHost()
        self.guestPair = []

        for arg in arglist:
            if arg.startswith('guestpair='):
                guestPairNames = arg.lstrip('guestpair=').split(',')
                self.guestPair = map(lambda x:host.getGuest(x), guestPairNames)

        if len(self.guestPair) == 0:
            self.guestPair = map(lambda x:host.getGuest(x), host.listGuests())

        if len(filter(lambda x:x != None, self.guestPair)) != 2: 
            raise xenrt.XRTError('2 guests are required for this test')

        xenrt.TEC().logverbose('Using guest pair: %s, %s' % (self.guestPair[0].getName(), self.guestPair[1].getName()))
        self.addGuestsToInternalNetwork(host, self.guestPair)

        map(lambda x:self.createSMBShare(self.getSMBShareName(x), self.SHARE_PATH, x), self.guestPair)
        map(lambda x:self.installSha1SumUtility(x), self.guestPair)
        map(lambda x:self.getLogsFrom(x), self.guestPair)

    def run(self, arglist):
        fileSizeMB = 1000
        iterations = 5
        averageThreshold = 60

        self.runSubcase('doTransfer', (True, iterations, averageThreshold, self.guestPair, True, fileSizeMB, False), 'PushFile', 'IPv4')
        self.runSubcase('doTransfer', (True, iterations, averageThreshold, self.guestPair, False, fileSizeMB, False), 'PushFile', 'IPv6')
        self.runSubcase('doTransfer', (True, iterations, averageThreshold, self.guestPair, True, fileSizeMB, True), 'PushFile-RoboCopy', 'IPv4')
        self.runSubcase('doTransfer', (True, iterations, averageThreshold, self.guestPair, False, fileSizeMB, True), 'PushFile-RoboCopy', 'IPv6')

        self.runSubcase('doTransfer', (False, iterations, averageThreshold, self.guestPair, True, fileSizeMB, False), 'PullFile', 'IPv4')
        self.runSubcase('doTransfer', (False, iterations, averageThreshold, self.guestPair, False, fileSizeMB, False), 'PullFile', 'IPv6')
        self.runSubcase('doTransfer', (False, iterations, averageThreshold, self.guestPair, True, fileSizeMB, True), 'PullFile-RoboCopy', 'IPv4')
        self.runSubcase('doTransfer', (False, iterations, averageThreshold, self.guestPair, False, fileSizeMB, True), 'PullFile-RoboCopy', 'IPv6')

class TCCrossHostWinSMB(TCWinSMBFileTransfer):
    USE_LINK_LOCAL_ADDRESSES = False

    def prepare(self, arglist):
        hosts = set(self.getAllHosts())
        if len(hosts) != 2:
            raise xenrt.XRTError('2 hosts required for this test')

        self.guestPair = []

        for arg in arglist:
            if arg.startswith('host0guest='):
                guestName = arg.lstrip('host0guest=')
                self.guestPair.append(self.getHost('RESOURCE_HOST_0').getGuest(guestName))
            if arg.startswith('host1guest='):
                guestName = arg.lstrip('host1guest=')
                self.guestPair.append(self.getHost('RESOURCE_HOST_1').getGuest(guestName))
                
        if len(self.guestPair) == 0: 
            for host in hosts:
                if len(host.listGuests()) != 1:
                    raise xenrt.XRTError('1 guest per host is required for this test')
                self.guestPair.append(host.getGuest(host.listGuests()[0]))

        if len(filter(lambda x:x != None, self.guestPair)) != 2:
            raise xenrt.XRTError('2 guests are required for this test')
        
        map(lambda x:x.reboot(), self.guestPair)
        map(lambda x:self.createSMBShare(self.getSMBShareName(x), self.SHARE_PATH, x), self.guestPair)
        map(lambda x:self.installSha1SumUtility(x), self.guestPair)
        map(lambda x:self.getLogsFrom(x), self.guestPair)
        
    def run(self, arglist):
        fileSizeMB = 1000
        iterations = 5
        averageThreshold = 60

        self.runSubcase('doTransfer', (True, iterations, averageThreshold, self.guestPair, True, fileSizeMB, False), 'PushFile', 'IPv4')
        self.runSubcase('doTransfer', (True, iterations, averageThreshold, self.guestPair, False, fileSizeMB, False), 'PushFile', 'IPv6')
        self.runSubcase('doTransfer', (True, iterations, averageThreshold, self.guestPair, True, fileSizeMB, True), 'PushFile-RoboCopy', 'IPv4')
        self.runSubcase('doTransfer', (True, iterations, averageThreshold, self.guestPair, False, fileSizeMB, True), 'PushFile-RoboCopy', 'IPv6')

        self.runSubcase('doTransfer', (False, iterations, averageThreshold, self.guestPair, True, fileSizeMB, False), 'PullFile', 'IPv4')
        self.runSubcase('doTransfer', (False, iterations, averageThreshold, self.guestPair, False, fileSizeMB, False), 'PullFile', 'IPv6')
        self.runSubcase('doTransfer', (False, iterations, averageThreshold, self.guestPair, True, fileSizeMB, True), 'PullFile-RoboCopy', 'IPv4')
        self.runSubcase('doTransfer', (False, iterations, averageThreshold, self.guestPair, False, fileSizeMB, True), 'PullFile-RoboCopy', 'IPv6')
        
class TC20910(xenrt.TestCase):
    """Test that Linux guest agent reports the IP address of the interface rather than the interface alias."""
    
    DISTRO = "rhel56"
    
    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guest = self.host.createBasicGuest(distro=self.DISTRO)
    
    def run(self, arglist=None):
        ip = self.guest.getIP()
        step("Setting up an ethernet alias for eth0(%s)." % ip)
        ipSplit = ip.split('.')
        
        ipSplit[3] = str(int(ipSplit[3]) + 1)    
        incrementedIP = '.'.join(ipSplit)
        try:
            self.guest.execcmd("ifconfig eth0:0 %s up" % incrementedIP)
            step("Alias eth0:0(%s) has been created." % incrementedIP) 
        except Exception, e:
            raise xenrt.XRTError("Unable to create an alias eth0:0(%s). Error message: %s" % (incrementedIP,e))
        
        try:
            self.guest.execcmd("/sbin/ip addr show eth0")
        except Exception, e:
            log("Exception: " + str(e))
        
        try:
            self.guest.execcmd("/sbin/ifconfig eth0")
        except Exception, e:
            log("Exception: " + str(e))
        
        step("Waiting for 60 seconds to allow changes to take effect in xenstore.")
        time.sleep(60)
        
        step("Checking the VM eth0 IP address that appears in xenstore...")
        visibleIP = self.host.execdom0("xenstore-ls | grep -A 1 eth0")
        if not visibleIP: 
            raise xenrt.XRTError("An unexpected error occurred - couldn't find eth0 in xenstore.")
        elif(incrementedIP in visibleIP):
            raise xenrt.XRTFailure("The visible IP changed to the alias in xenstore: %s" % visibleIP)
        else:
            log("The visible IP has not changed to the alias and is: %s" % visibleIP)
            
    def postrun(self):
        if self.guest:
            try:
                self.guest.shutdown()
            except:
                pass
            try:
                self.guest.uninstall()
            except:
                pass
                
class TCMulticastTraffic(xenrt.TestCase):
    """TC-20902: Multicast traffic to Windows guest should continue receiving post-VM migration (HFX-1011)"""
    def multicastAddressCount(self, host):
        host.execdom0('xl debug-keys q') #enabled debug-keys 
        MulticastAddressCount = host.execdom0("less /var/log/messages | grep 'Mac: MulticastAddress' | wc -l").strip()
        return MulticastAddressCount
        
    def run(self, arglist):
        host = self.getDefaultHost()
        #perform Lifecycle operation
        for g in [ xenrt.TEC().registry.guestGet(x) for x in host.listGuests() ]:
            initialAddressCount = self.multicastAddressCount(host)
            xenrt.TEC().logverbose("Multicast address count pre-suspend-resume operation is %s"% initialAddressCount) 
            g.suspend()
            g.resume()
            finalAddressCount = self.multicastAddressCount(host)
            xenrt.TEC().logverbose("Multicast address count post-suspend-resume operation is %s" % finalAddressCount)
            if int(finalAddressCount) == int(initialAddressCount):
                raise xenrt.XRTFailure("Windows guest does not receive Multicast traffic post suspend-resume operation")
            elif int(finalAddressCount) == 2 * int(initialAddressCount):
                xenrt.TEC().logverbose("Windows guest continues to receive Multicast traffic")
            else:    
                xenrt.TEC().warning("Windows guest continues receive Multicast traffic but of unequal addresses")
                xenrt.TEC().logverbose("Windows guest continues to receive Multicast traffic")
                
class TC20919(xenrt.TestCase) :
#This testcase is derived from HFX-918 in Hotfix Stratus

    def run(self, arglist):
        self.host = self.getDefaultHost()
        self.guest = self.getGuest("Win7")
        evtchn_rtm = int(self.host.execdom0("/usr/lib/xen/bin/lsevtchn | wc -l"))
        xenrt.TEC().logverbose("No of event channels before updates %s" %(evtchn_rtm))
        self.host.applyRequiredPatches()
        self.guest.start()
        evtchn_hfx = int(self.host.execdom0("/usr/lib/xen/bin/lsevtchn | wc -l"))
        xenrt.TEC().logverbose("No of event channels after updates %s" %(evtchn_hfx))
        if (evtchn_hfx - evtchn_rtm) != 1 :
            raise xenrt.XRTFailure("No of event channels failed to decrease by 1 after applying stratus hotfix")
                

class _WinTimeZone(xenrt.TestCase):
    TIME_ERROR_THRESHOLD = 30

    def logTimeRelatedXenStoreFields(self, guest, host):
        try:
            guestDomId = guest.getDomid()
            xenStoreData = host.execdom0('xenstore-ls -f').splitlines()
            releventLines = filter(lambda x:re.search('%s.*time' % (guest.uuid), x), xenStoreData)
            releventLines += filter(lambda x:re.search('%s.*rtc' % (guest.uuid), x), xenStoreData)
            releventLines += filter(lambda x:re.search('%s.*time' % (guestDomId), x), xenStoreData)

            xenrt.TEC().logverbose('Time related XenStore Entries for Guest: %s' % (guest.getName()))
            map(lambda x:xenrt.TEC().logverbose(x), list(set(releventLines)))
        except Exception, e:
            xenrt.TEC().warning('Execution of xenstore-ls -f failed with exception: %s' % (str(e)))

    def getWindowsValidTimeZones(self, guest):
        tzDict = {}
        tzdata = guest.xmlrpcExec('tzutil /l', returndata=True).splitlines()
        for index in range(2, len(tzdata), 3):
            tzDict[tzdata[index]] = tzdata[index + 1]

        return tzDict

    def getLegacyWindowsValidTimeZones(self, guest):
        regExportFile = 'xenrtRegExport.txt'
        regExportArgs = ''
        if not 'winxp' in guest.distro:
            regExportArgs = ' /y'
        guest.xmlrpcExec('reg export "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Time Zones" %s %s' % (regExportFile, regExportArgs))
        regExportData = guest.xmlrpcReadFile(regExportFile).decode('utf-16').splitlines()

        tzDict = {}
        currentTzId = None
        for line in regExportData:
            searchRes = re.search('\[HKEY_LOCAL_MACHINE\\\\SOFTWARE\\\\Microsoft\\\\Windows NT\\\\CurrentVersion\\\\Time Zones\\\\(.*)\]', line)
            if searchRes:
                currentTzId = searchRes.group(1)
                continue
            
            searchRes= re.search('"Display"="(.*)"', line)
            if searchRes:
                if not currentTzId:
                    raise xenrt.XRTError('Failed to parse registry timezone info')
                tzDict[searchRes.group(1)] = currentTzId
                currentTzId = None

        return tzDict

    def getCurrentWindowsTimeZone(self, guest):
        if not guest.usesLegacyDrivers():
            currentTZ = guest.xmlrpcExec('tzutil /g', returndata=True).splitlines()[2]
        else:
            currentTZ = guest.winRegLookup('HKLM', 'SYSTEM\\CurrentControlSet\\Control\\TimeZoneInformation', 'StandardName')
        xenrt.TEC().logverbose('Current TimeZone for guest %s: %s' % (guest.getName(), currentTZ))
        return currentTZ

    def setWindowsTimeZone(self, guest, timeZoneOffsetHours=None, timeZoneID=None, disableDST=True):
        if not guest.usesLegacyDrivers():
            if timeZoneOffsetHours != None:
                if timeZoneOffsetHours == 0:
                    timeZoneSearchStr = '(UTC)'
                elif timeZoneOffsetHours > 0:
                    timeZoneSearchStr = '(UTC+%02d:' % (timeZoneOffsetHours)
                else:
                    timeZoneSearchStr = '(UTC-%02d:' % (abs(timeZoneOffsetHours))

                tzDict = self.getWindowsValidTimeZones(guest)
                searchResults = filter(lambda x:x.startswith(timeZoneSearchStr), tzDict.keys())
                if len(searchResults) == 0:
                    raise xenrt.XRTError('Failed to find Windows TimeZone with specified offset: %d' % (timeZoneOffsetHours))
    
                tzKey = random.choice(searchResults)
                xenrt.TEC().logverbose('Using Windows TimeZone: Name: %s, ID: %s' % (tzKey, tzDict[tzKey]))
                timeZoneID = tzDict[tzKey]

            if disableDST:
                timeZoneID += '_dstoff'
            guest.xmlrpcExec('tzutil /s "%s"' % (timeZoneID))
        else:
            if timeZoneOffsetHours != None:
                if timeZoneOffsetHours == 0:
                    timeZoneSearchStr = '(GMT)'
                elif timeZoneOffsetHours > 0:
                    timeZoneSearchStr = '(GMT+%02d:' % (timeZoneOffsetHours)
                else:
                    timeZoneSearchStr = '(GMT-%02d:' % (abs(timeZoneOffsetHours))
       
                tzDict = self.getLegacyWindowsValidTimeZones(guest)
                searchResults = filter(lambda x:x.startswith(timeZoneSearchStr), tzDict.keys())
                if len(searchResults) == 0:
                    raise xenrt.XRTError('Failed to find Windows TimeZone with specified offset: %d' % (timeZoneOffsetHours))

                tzKey = random.choice(searchResults)
                xenrt.TEC().logverbose('Using Windows TimeZone: Name: %s, ID: %s' % (tzKey, tzDict[tzKey]))
                timeZoneID = tzDict[tzKey]

            guest.xmlrpcExec('control.exe timedate.cpl,,/Z %s' % (timeZoneID), returnerror=False, returnrc=True)
            guest.winRegAdd('HKLM', 'SYSTEM\\CurrentControlSet\\Control\\TimeZoneInformation', 'DisableAutoDaylightTimeSet', 'DWORD', 1)

        (winTime, hostTime) = xenrt.pfarm([
                         xenrt.PTask(self.getCurrentWindowsTime, guest),
                         xenrt.PTask(self.getTimeInDateTimeFormat, guest.host)])
        winHostTimeDiff = self.getTimeDiffInSeconds(winTime, hostTime)
        actualOffsetHours = int(decimal.Decimal(winHostTimeDiff/3600.0).to_integral_value())
        xenrt.TEC().logverbose('Actual offset hours: %d' % (actualOffsetHours))
        if timeZoneOffsetHours != None and abs(timeZoneOffsetHours - actualOffsetHours) > 1:
            # This doesn't seem like a Daylight saving difference.
            raise xenrt.XRTError('Timezone not set correctly')
        return actualOffsetHours    

    def getCurrentPlatformOffset(self, guest):
        currentOffset = int(guest.paramGet('platform', 'timeoffset'))
        xenrt.TEC().logverbose('Current Platform Offset for guest %s: %s' % (guest.getName(), currentOffset))
        return currentOffset

    def isHostTimeUTCEnabled(self, guest):
        enabled = False 
        try:
            regKey = guest.xmlrpcGetArch().endswith('64') and 'SOFTWARE\\Wow6432Node\\CITRIX\\XenTools' or 'SOFTWARE\\CITRIX\\XenTools'
            currentValue = guest.winRegLookup('HKLM', regKey, 'HostTime')
            xenrt.TEC().logverbose('HostTime registry entry for guest: %s set to %s' % (guest.getName(), currentValue))
            if currentValue == 'utc':
                enabled = True
        except:
            xenrt.TEC().logverbose('HostTime registry entry not present for guest: %s' % (guest.getName()))
        return enabled

    def setXenToolsTimeZoneOption(self, guest, useUTC=True, deleteRegKey=False):
        if useUTC and deleteRegKey:
            raise xenrt.XRTError('Invalid parameter combination')

        regKey = guest.xmlrpcGetArch().endswith('64') and 'SOFTWARE\\Wow6432Node\\CITRIX\\XenTools' or 'SOFTWARE\\CITRIX\\XenTools'
        if useUTC:
            guest.winRegAdd('HKLM', regKey, 'HostTime', 'SZ', 'utc')
        else:
            if deleteRegKey:
                guest.winRegDel('HKLM', regKey, 'HostTime')
            else:
                guest.winRegAdd('HKLM', regKey, 'HostTime', 'SZ', 'NOTutc')

    def getCurrentWindowsTime(self, guest):
        timeStr = guest.xmlrpcExec('powershell get-date -Format "dd-MM-yy#HH:mm:ss"', returndata=True).splitlines()[2]
        currentTime = datetime.strptime(timeStr, '%d-%m-%y#%H:%M:%S')
        return currentTime

    def getTimeInDateTimeFormat(self, place):
        return datetime.fromtimestamp(place.getTime())

    def getTimeDiffInSeconds(self, t1, t2):
        if t1 > t2:
            delta = t1 - t2
            return delta.seconds
        else:
            delta = t2 - t1
            return 0 - delta.seconds 

    def verifyGuestTime(self, guest, host, timeZoneOffsetHours, settleTimeout=600):
        guestTimeCorrect = False
        startTime = datetime.now()
        while (datetime.now() - startTime).seconds < settleTimeout:
            (platOffset, winTime, guestTime, hostTime) = xenrt.pfarm([
                         xenrt.PTask(self.getCurrentPlatformOffset, guest),
                         xenrt.PTask(self.getCurrentWindowsTime, guest),
                         xenrt.PTask(self.getTimeInDateTimeFormat, guest),
                         xenrt.PTask(self.getTimeInDateTimeFormat, host)])

            xenrt.TEC().logverbose('Guest Time Information for guest: %s on host: %s' % (guest.getName(), host.getName()))
            winTz = self.getCurrentWindowsTimeZone(guest)
            xenrt.TEC().logverbose(' Windows TimeZone: %s' % (winTz))
            xenrt.TEC().logverbose(' Platform Offset: %d' % (platOffset))
            xenrt.TEC().logverbose(' Windows Time: %s' % (winTime.strftime("%Y-%m-%d %H:%M:%S")))
            xenrt.TEC().logverbose(' Guest Time:   %s' % (guestTime.strftime("%Y-%m-%d %H:%M:%S")))
            xenrt.TEC().logverbose(' Host Time:    %s' % (hostTime.strftime("%Y-%m-%d %H:%M:%S")))

            hostGuestTimeDiff = self.getTimeDiffInSeconds(guestTime, hostTime)
            xenrt.TEC().logverbose('Guest is %d seconds from the host time' % (hostGuestTimeDiff))
            winHostTimeDiff = self.getTimeDiffInSeconds(winTime, hostTime)
            xenrt.TEC().logverbose('Windows is %d seconds from the host time' % (winHostTimeDiff))

            xenrt.TEC().logverbose('Expected TimeZone Offset %d hour(s)' % (timeZoneOffsetHours))
            expectedActualDiff = abs((timeZoneOffsetHours * 60 * 60) - winHostTimeDiff)
            self.logTimeRelatedXenStoreFields(guest, host)

            if expectedActualDiff < self.TIME_ERROR_THRESHOLD:
                timeToGuestTimeCorrect = (datetime.now() - startTime).seconds
                xenrt.TEC().logverbose('Guest time is correct after %d seconds' % (timeToGuestTimeCorrect))
                if timeToGuestTimeCorrect > 60:
                    xenrt.TEC().warning('Takes a long time for guest time to be correct: Time taken: %d sec' % (timeToGuestTimeCorrect))
                guestTimeCorrect = True
                break

        if not guestTimeCorrect:
            raise xenrt.XRTFailure('Guest time not correct')


class TC20928(xenrt.TestCase):
    """Verify space in filename accessed via Data Protection Manager with XenTools from 6.1 doesn't cause BSOD( Regression Test for CA-115744 )"""  
    
    def prepare(self, arglist=None):
        
        self.host = self.getDefaultHost()
        
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]

        # If we have a VM already then use that, otherwise create one
        self.guest = self.getGuest(gname)
        if not self.guest:
            xenrt.TEC().progress("Installing guest %s" % (gname))
            self.guest = self.host.createGenericWindowsGuest(distro="win7-x86")
            self.uninstallOnCleanup(self.guest)
        else:
            # Check the guest is healthy and reboot if it is already up
            try:
                if self.guest.getState() == "DOWN":
                    self.guest.start()
                else:
                    # If it is suspended or anything else then that's bad
                    self.guest.reboot()
                self.guest.checkHealth()
            except xenrt.XRTFailure, e:
                raise xenrt.XRTError("Guest broken before we start: %s" %
                                     (str(e)))

    def run(self, arglist=None):
        
        script = """
$a = gwmi -n root\wmi -cl CitrixXenStoreSession 
$a[0].log("THIS IS WHAT I EXPECT TO SEE AS PERCENTAGE S  %s") 
"""
        self.guest.xmlrpcCreateFile("c:\\test.ps1", script)
        self.guest.xmlrpcExec("powershell.exe -ExecutionPolicy ByPass -File c:\\test.ps1")
        
        xenrt.sleep(20)
        
        data = self.host.execdom0( 'grep "THIS IS WHAT I EXPECT TO SEE AS PERCENTAGE S " /var/log/daemon.log | rev |cut -c -3| rev').strip('\n')
        
        if "%s" in data:
            xenrt.TEC().logverbose("Found '%s' in /var/log/daemon.log as expected" % data )
        else:
            raise xenrt.XRTFailure("Found '%s' in /var/log/daemon.log but '%%s' was expected" % data)


class TCVerifyVMCorruption(xenrt.TestCase):
    """Verify Xapi fix to avoid VM Corruption during Migration"""  
    
    def prepare(self, arglist=None):
        
        self.host = self.getDefaultHost()
        
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]

        step("If we have a VM already then use that, otherwise create one")
        self.guest = self.getGuest(gname)
        if not self.guest:
            xenrt.TEC().progress("Installing guest %s" % (gname))
            self.guest = self.host.createGenericWindowsGuest(distro="win7-x86")
            self.uninstallOnCleanup(self.guest)
        else:
            step("Check the guest is healthy and reboot if it is already up")
            try:
                if self.guest.getState() == "DOWN":
                    self.guest.start()
                else:
                    step("If it is suspended or anything else then that's bad")
                    self.guest.reboot()
                self.guest.checkHealth()
            except xenrt.XRTFailure, e:
                raise xenrt.XRTError("Guest broken before we start: %s" %
                                     (str(e)))

    def run(self, arglist=None):
        
        step("Check the value of '/local/domain/dom-id/console/ring-ref'")
        exception = False
        try:
            self.host.execdom0("xenstore-ls -f | grep '/local/domain/%d/console/ring-ref'" %self.guest.getDomid())
        except:
            pass
        else:
            raise xenrt.XRTFailure("Xapi fix to avoid VM corruption during Migration has Failed")

class TCCentosUpgrade(xenrt.TestCase):
    """Verify a CentOS upgrade is successful"""

    def run(self, arglist):
        g = self.getGuest(arglist[0])
        # Remove the XenRT repo and reenable the centos one
        g.execguest("rm /etc/yum.repos.d/xenrt.repo")
        g.execguest("rename '.orig' '' /etc/yum.repos.d/*.orig")
        # Add a proxy if we know about one
        proxy = xenrt.TEC().lookup("HTTP_PROXY", None)
        if proxy:
            g.execguest("sed -i '/proxy/d' /etc/yum.conf")
            g.execguest("echo 'proxy=http://%s' >> /etc/yum.conf" % proxy)

        # Apply the update and reboot
        g.execguest("yum update -y", timeout=7200)
        g.reboot()

        # Now verify the guest works by doing some lifecyle ops
        g.shutdown()
        g.start()
        g.reboot()
        g.suspend()
        g.resume()
        g.migrateVM(self.getDefaultHost(), live=False)
        g.migrateVM(self.getDefaultHost(), live=True)


class TCSettingGuestNameViaXenstore(xenrt.TestCase):
    """
    This addresses SCTX-1476 which is a reinstate of the setting a host
    name via XenStore. This was removed previously and reinstated for 
    Creedence but in a recast form
    """
    def prepare(self, arglist):
        for arg in arglist:
            if arg.startswith("distro"):
                distro = arg.split("=")[-1]

        self.__host = self.getDefaultHost()
        self.__guest = self.__host.createBasicGuest(distro=distro)
        self.__distro = distro

    def run(self, arglist):
        step("Running XenStore rename for %s" % self.__distro)
        initialName = self.__guest.xmlrpcExec("hostname", returndata=True).strip()
        newName = ''.join(random.choice(string.ascii_uppercase) for _ in range(14))

        step("Setting name to %s" % newName)
        self.__guest.setNameViaXenstore(newName)
        finalName = self.__guest.xmlrpcExec("hostname", returndata=True).strip()

        step("Check name has been set")
        if newName == finalName:
            raise xenrt.XRTFailure("Initial name: %s and final name: %s do not match" % (initialName, finalName))

class TCCopyDataOnMultipleVIFsWindows(xenrt.TestCase):
    """
    This addresses SCTX-1778 which states Windows VM with 5 VIFs
    becomes unresponsive when copying data
    """
    
    FILESIZE = 8 # In GB
    THRESHOLD = 200 # Measuring 40MB/s copying speed
    
    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid=tcid)
        self.guest = None
    
    def checkTimeForCopyingData(self, fromLocation, toLocation):
        # Copy data from one drive to another drive
        log("Create a %dGB file on location %s" % (self.FILESIZE,fromLocation))
        filename = 'xenrt-%s.dat' % (''.join(random.sample(string.ascii_lowercase + string.ascii_uppercase, 6)))
        self.guest.xmlrpcExec('fsutil file createnew %s\\%s %d' % (fromLocation, filename, (self.FILESIZE * xenrt.GIGA)))
        
        log("Measure the time taken for copying file from %s to %s" % (fromLocation, toLocation))
        startTime = datetime.now()
        self.guest.xmlrpcExec('copy %s\\%s %s\\%s' % (fromLocation,filename,toLocation,filename), timeout=1800)
        timeDelta = datetime.now() - startTime
        
        log('Total time taken %d seconds' % timeDelta.seconds)
        if(timeDelta.seconds > self.THRESHOLD):
            raise xenrt.XRTFailure("File copied at slow rate, total time taken to copy %dGB is %s" % (self.FILESIZE,timeDelta.seconds))
        
        log("Remove file created and copied in %s %s" % (fromLocation, toLocation))
        self.guest.xmlrpcExec('del %s\\%s' % (fromLocation,filename))
        self.guest.xmlrpcExec('del %s\\%s' % (toLocation,filename))

    def run(self, arglist=None):
        
        step("Get the guest installed in seq")
        self.guest = self.getGuest("Windows VM")
        
        pathA = 'C:\\temp'
        pathB = 'E:\\temp'
        log("Create directories %s %s" % (pathA, pathB))
        self.guest.xmlrpcCreateDir(pathA)
        self.guest.xmlrpcCreateDir(pathB)
        
        step("Test the file copying speed from one drive to another")
        self.checkTimeForCopyingData(pathA,pathB)
        
        step("Test the file copying speed vice-versa")
        self.checkTimeForCopyingData(pathB,pathA)

class TC21711(xenrt.TestCase):
    def prepare(self, arglist):
        host = self.getDefaultHost()
        self.guest = host.createBasicGuest("rhel59")

        if self.guest is None:
            raise xenrt.XRTError("Need RHEL VM for testcase. None found.")

    def run(self, arglist):
        self.guest.reboot()
        filepath = "/sys/hypervisor/uuid"
        response = self.guest.execguest("cat %s" % (filepath))

        # UUID pattern
        pattern = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

        if not re.search(pattern, response):
            raise xenrt.XRTFailure("Failure. Was not able to read uuid from %s" % (filepath))

class TCInstallDriversNoIPv6(xenrt.TestCase):
    def doGuest(self, g):
        g.disableIPv6()
        g.installDrivers()
    
    def run(self, arglist=None):
        for g in self.getDefaultHost().guests.values():
            self.getLogsFrom(g)
            self.runSubcase("doGuest", (g), "TCInstallDriversNoIPv6", g.getName())

class TCMemoryDumpBootDriverFlag(xenrt.TestCase):
    """Test case for SCTX-1421 - Verify memory dump is created"""
    #TC-23777
    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericWindowsGuest(distro="win7sp1-x64")
        self.uninstallOnCleanup(self.guest)
        
        step("Enable complete Memory dump option")
        self.guest.enableFullCrashDump()
        
        step("Set boot driver flag=1")
        self.guest.winRegAdd("HKLM",
                 "SYSTEM\\CurrentControlSet\\Control",
                 "BootDriverFlags",
                 "DWORD",
                 1)
        self.guest.reboot()
        
    def run(self, arglist):
        step("Remove any existing memory.dmp file")
        if self.guest.xmlrpcBigdump():
            self.guest.xmlrpcRemoveFile("c:\\windows\\MEMORY.DMP")
        
        step("Crash the guest")
        self.guest.crash()
        xenrt.sleep(100)
        self.guest.reboot(force=True)
        
        step("Check if crashdump file exists")
        if not self.guest.xmlrpcBigdump():
            raise xenrt.XRTFailure("Unexpected output: Crashdump is not created")
        else:
            xenrt.TEC().logverbose("Crashdump file found")
            
class VmRebootedOnce(xenrt.TestCase):
    """Test Case for SCTX-2017 - VM.clean_reboot is not canceled by VM.hard_reboot if VM is running on slave"""   

    def __disableSoftReboot(self, guest):
        #this Stops Soft Reboot - Only works on Debian 7 ... won't work on Debian 8 or later 
        guest.execguest("sed -i 's#.*ca:12345:ctrlaltdel:.*#ca:12345:ctrlaltdel:/bin/echo \"Oh no You Dont\"#' /etc/inittab")
        xenrt.sleep(2)
        #reload inittab
        guest.execguest("init q")
        xenrt.sleep(2)
    
    def run(self, arglist):
        for arg in arglist:
            host = self.getDefaultHost()
            vm = self.getGuest(arg)
            log("Currently working on %s" % vm)
            step("Disable Soft Reboot on VM")
            self.__disableSoftReboot(vm)
                        
            step("VM soft reboot")
            rebootCountBefore = vm.getDomid()
            log("VM has been Rebooted %s times previously" % rebootCountBefore)
            vm.rebootAsync()
            #simulate hung reboot on guest VM
            xenrt.sleep(30)
            
            step("VM hard reboot")
            vm.reboot(force=True)
            rebootCountAfter = vm.getDomid()
            log("After Last Reboot total VM reboot count is %s " % rebootCountAfter)
            
            step("Check if VM has been rebooted once")
            if rebootCountAfter - 1 != rebootCountBefore:
                raise xenrt.XRTFailure("%s rebooted more than Once" % vm)
        
        

