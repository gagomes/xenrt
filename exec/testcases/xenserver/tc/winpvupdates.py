# Test harness for Xen and the XenServer product family

# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import socket, re, string, time, traceback, sys, random, copy, math
import xenrt, xenrt.lib.xenserver
from xenrt.lazylog import step, comment, log
from testcases.xenserver.tc.upgrade import _TCCrossVersionImport
from testcases.xenserver.tc.sxm import SxmFromLowToHighVersion

class WindowsUpdateBase(xenrt.TestCase):
    
    def prepare(self, arglist=None):
        
        self.args  = self.parseArgsKeyValue(arglist)
        self.host = self.getDefaultHost()
        self.remoteHost = self.getHost("RESOURCE_HOST_1")

        if self.args.has_key('TOOLS'):
            self.Tools = self.args['TOOLS']

        self.goldVM = self.host.getGuest(self.args['guest'])
        self.guest = self.cloneVM(self.goldVM)

        self.guest.lifecycleOperation("vm-start")
        xenrt.sleep(50)
        self.uninstallOnCleanup(self.guest)

    def postRun(self):
        
        pass

    def cloneVM(self, guest):
        """ If cloned VM is windows with no tools"""
    
        g = guest.cloneVM()
        if not g.mainip:
            g.lifecycleOperation("vm-start")
            vifname, bridge, mac, ip = g.vifsN[0]
            g.mainip = self.host.arpwatch(bridge, mac, timeout=10800)
            g.lifecycleOperation("vm-shutdown", force=True)
        return g

class TCSnapRevertTools(WindowsUpdateBase):
    
    def run(self, arglist=None):
        
        step("Install PV Drivers on the windows guest")
        self.guest.installDrivers()
        
        step("Take snapshot of the VM")
        snapshot = self.guest.snapshot()
        
        step("Uninstall the PV Drivers on the Guest")
        self.guest.uninstallDrivers()
        
        step("Revert the VM to the State before tools were uninstalled")
        self.guest.revert(snapshot)
        self.guest.removeSnapshot(snapshot)
        
        self.guest.start()
        
        step("Verify tools are present after the VM is reverted to previous state")
        if self.guest.checkPVDevicesState() and not self.guest.checkPVDriversStatus(ignoreException = True):
            raise xenrt.XRTFailure("PV Tools not present after the Reverting VM to state where tools were installed ")
        
class TCSnapRevertNoTools(WindowsUpdateBase):
    
    def run(self, arglist=None):
        
        step("Take snapshot of the VM")
        snapshot = self.guest.snapshot()
        
        step("Install PV Drivers on the windows guest")
        self.guest.installDrivers()
        
        step("Revert the VM to the State before tools were uninstalled")
        self.guest.revert(snapshot)
        self.guest.removeSnapshot(snapshot)
        self.guest.lifecycleOperation("vm-start")
        
        step("Verify tools are not present after the VM is reverted to previous state")
        if not self.guest.checkPVDevicesState():
            raise xenrt.XRTFailure("PV Tools present after the Reverting VM to state where tools were not installed ")

class TestCheckpointVmOps(WindowsUpdateBase): 
     
    def run(self, arglist=None): 
         
        step("Install PV Drivers on the windows guest") 
        self.guest.installDrivers() 
         
        step("Take checkpoint of the VM") 
        checkpoint1 = self.guest.checkpoint() 
         
        step("Suspend windows guest") 
        self.guest.suspend() 
         
        step("Resuming windows guest") 
        self.guest.resume() 
        self.guest.check() 
         
        step("Removing checkpoint") 
        self.guest.removeSnapshot(checkpoint1) 
        self.guest.check() 
         
class TestMigrateSXM(WindowsUpdateBase): 
     
    def run(self, arglist=None): 
         
        step("Install PV Drivers on the windows guest") 
        self.guest.installDrivers() 
         
        step("Live Migrating windows guest") 
        self.guest.migrateVM(remote_host=self.remoteHost, live="true") 
        self.guest.check() 
         
        step("Non-Live Migrating windows guest") 
        self.guest.migrateVM(remote_host=self.host) 
        self.guest.check()
        
class TCUpgWinCmp(WindowsUpdateBase):
    
    def run(self, arglist=None):

        step("Install Windows update compatible PV Drivers")
        self.guest.installDrivers(source = self.Tools, pvPkgSrc = "ToolsISO")
        
        oldVersion = self.guest.getPVDriverVersion()
        
        self.guest.shutdown()
        
        step("Enable the Windows Updates from the Host")
        self.guest.enableWindowsPVUpdates()
        
        self.guest.start()
        
        step("Update PV Drivers on the windows guest")
        self.guest.installDrivers()
        
        newVersion = self.guest.getPVDriverVersion()
        
        if not newVersion > oldVersion:
            raise xenrt.XRTFailure("PV Drivers Failed to upgrade OldVersion > NewVersion (%s > %s)" %(oldVersion, newVersion))

class TCUpgNonWinCmp(WindowsUpdateBase):

    def run(self, arglist=None):

        step("Install Non-Windows update compatible PV Drivers")
        self.guest.installDrivers(source = self.Tools, pvPkgSrc = "ToolsISO")
        
        oldVersion = self.guest.getPVDriverVersion()
        
        step("Uninstall Non-Windows Update Compatible PV Drivers")
        self.guest.uninstallDrivers(source = self.Tools)
        
        self.guest.lifecycleOperation("vm-shutdown", force=True)
        
        step("Enable the Windows Updates from the Host")
        self.guest.enableWindowsPVUpdates()
        
        self.guest.lifecycleOperation("vm-start")
        
        step("Install PV Drivers on the windows guest")
        self.guest.installDrivers()
        
        newVersion = self.guest.getPVDriverVersion()
        
        if not newVersion > oldVersion:
            raise xenrt.XRTFailure("PV Drivers Failed to upgrade OldVersion > NewVersion (%s > %s)" %(oldVersion, newVersion))
            
class TCUpgToolsIso(WindowsUpdateBase):

    def run(self, arglist=None):
        
        step("Install the PV Drivers on the Windows Guest")
        self.guest.installDrivers(source = self.Tools)
        
        oldVersion = self.guest.getPVDriverVersion()
        
        step("Upgrade the tools using tools.iso")
        self.guest.installDrivers(pvPkgSrc = "ToolsISO")
        
        newVersion = self.guest.getPVDriverVersion()
        
        if not newVersion > oldVersion:
            raise xenrt.XRTFailure("PV Drivers Failed to upgrade OldVersion > NewVersion (%s > %s)" %(oldVersion, newVersion))

class TCPVDriverDwngrd(WindowsUpdateBase):
    
    def run(self, arglist=None):
        
        step("Install PV Drivers on the windows guest")
        self.guest.installDrivers()
        
        oldVersion = self.guest.getPVDriverVersion()
        
        step("Try downgrading the tools with the older version of Tools ISO")
        self.guest.installDrivers(source = self.Tools, pvPkgSrc = "ToolsISO")
        
        newVersion = self.guest.getPVDriverVersion()
        
        if newVersion > oldVersion:
            raise xenrt.XRTFailure("PV Drivers downgrade successful from %s to %s" %(oldVersion, newVersion))


class TCSkipPvPkg(WindowsUpdateBase):

    def run(self, arglist=None):
        
        step("Get the list of the Pv packages ")
        pvDriverList = xenrt.TEC().lookup("PV_DRIVERS_LIST").split(';')
        
        self.guest.installFullWindowsGuestAgent()
        
        pkgList = random.sample(pvDriverList, 4)
        step("Install PV Drivers on the windows guest")
        self.guest.installPVPackage(packageList = pkgList )
        self.guest.reboot()
        
        self.guest.waitForDaemon(300, desc="Guest check after installation of PV Packages %s" %(pkgList))
        
        xenrt.TEC().logverbose("%s is reachable after installation of PV Packages %s" %(self.guest.getName(), pkgList))

class TCSkipPvPkgNoAgent(WindowsUpdateBase):

    def run(self, arglist=None):
        
        step("Get the list of the Pv packages ")
        pvDriverList = xenrt.TEC().lookup("PV_DRIVERS_LIST").split(';')
        
        pkgList = random.sample(pvDriverList, 4)
        step("Install PV Drivers on the windows guest")
        self.guest.installPVPackage(packageList = pkgList )
        self.guest.reboot()
        
        self.guest.waitForDaemon(300, desc="Guest check after installation of PV Packages %s" %(pkgList))
        
        xenrt.TEC().logverbose("%s is reachable after installation of PV Packages %s" %(self.guest.getName(), pkgList))

class TCHostUpgradePVChk(xenrt.TestCase):

    def prepare(self, arglist=None):

        old = xenrt.TEC().lookup("OLD_PRODUCT_VERSION")
        oldversion = xenrt.TEC().lookup("OLD_PRODUCT_INPUTDIR")
        
        self.host = xenrt.lib.xenserver.createHost(id=0,
                                                   version=oldversion,
                                                   productVersion=old,
                                                   withisos=True)
        self.guest = self.host.createGenericWindowsGuest(distro="win7sp1-x64")
        self.guest.shutdown()
        self.host.upgrade()
        
    def run(self, arglist=None):

        if self.guest.getAutoUpdateDriverState():
            raise xenrt.XRTFailure("Windows PV updates are enabled on the VM after upgrading host")

        xenrt.TEC().logverbose("Windows PV updates are disabled on the VM after upgrading host as expected")
        
class TCSxmFrmLowToHighPVChk(SxmFromLowToHighVersion):
    
    def run(self, arglist=None):
        
        step("Migrate the VM's")
        SxmFromLowToHighVersion.run(self, arglist)

        step("Verify windows pv updates are disabled after migration")
        for guest in self.guests:
            if guest.windows and guest.getAutoUpdateDriverState():
                raise xenrt.XRTFailure("Windows PV updates are enabled on the VM Migrated from Older host to Newer host")

        xenrt.TEC().logverbose("Windows PV updates are disabled on the VM Migrated from Older host to Newer host as expected")

class TCCrossVerImpPVChk(_TCCrossVersionImport):

    DISTROS = ["win7sp1-x86", "ws08sp2-x64"]
    
    def run(self, arglist=None):
        
        step("Import the VM's from Older host to Newer host")
        _TCCrossVersionImport.run(self, arglist)
        
        step("Verify windows pv updates are disabled after migration")
        guests=[self.host1.getGuest(g) for g in self.host1.listGuests()]
        for guest in guests:
            if guest.windows and guest.getAutoUpdateDriverState():
                raise xenrt.XRTFailure("Windows PV updates are enabled on the VM imported from Older host to Newer host")

        xenrt.TEC().logverbose("Windows PV updates are disabled on the VM imported from Older host to Newer host as expected ")
