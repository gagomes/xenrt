# Test harness for Xen and the XenServer product family

# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import socket, re, string, time, traceback, sys, random, copy, math
import xenrt, xenrt.lib.xenserver
from xenrt.lazylog import step, comment, log

class WindowsUpdateBase(xenrt.TestCase):
    
    def prepare(self, arglist=None):
        
        self.args  = self.parseArgsKeyValue(arglist)
        self.host = self.getDefaultHost()
        self.remoteHost = self.getHost("RESOURCE_HOST_1")

        if self.args.has_key('TOOLS'):
            self.Tools = self.args['TOOLS']

        self.goldVM = self.host.getGuest(self.args['guest'])
        self.guest = self.goldVM.cloneVM()

        self.guest.lifecycleOperation("vm-start")
        xenrt.sleep(50)
        self.uninstallOnCleanup(self.guest)
    
    def skipPvPkginst(self, pkgList, useGuestAgent=True):
        
        step("Take snapshot of the VM")
        snapshot = self.guest.snapshot()
        
        if useGuestAgent:
            self.guest.installFullWindowsGuestAgent()
            
        step("Install PV Drivers on the windows guest")
        self.guest.installPVPackage(packageList = pkgList)
        self.guest.reboot()
        
        self.guest.waitForDaemon(300, desc="Guest check after installation of PV Packages %s" %(pkgList))
        
        step("Revert the VM to the State before tools were uninstalled")
        self.guest.revert(snapshot)
        self.guest.removeSnapshot(snapshot)
        self.guest.lifecycleOperation("vm-start")
    
    def postRun(self):
        
        pass
    
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

class TCUpgWinCmp(WindowsUpdateBase):
    
    def run(self, arglist=None):

        step("Install Windows update compatible PV Drivers")
        self.guest.installDrivers(source = self.Tools, pvPkgSrc = "ToolsISO")
        
        self.guest.shutdown()
        
        step("Enable the Windows Updates from the Host")
        self.guest.enableWindowsPVUpdates()
        
        self.guest.start()
        
        step("Update PV Drivers on the windows guest")
        self.guest.installDrivers()

class TCUpgNonWinCmp(WindowsUpdateBase):

    def run(self, arglist=None):

        step("Install Non-Windows update compatible PV Drivers")
        self.guest.installDrivers(source = self.Tools, pvPkgSrc = "ToolsISO")
        
        step("Uninstall Non-Windows Update Compatible PV Drivers")
        self.guest.uninstallDrivers(source = self.Tools)
        
        self.guest.lifecycleOperation("vm-shutdown", force=True)
        
        step("Enable the Windows Updates from the Host")
        self.guest.enableWindowsPVUpdates()
        
        step("Install PV Drivers on the windows guest")
        self.guest.installDrivers()

class TCUpgToolsIso(WindowsUpdateBase):

    def run(self, arglist=None):
        
        step("Install the PV Drivers on the Windows Guest")
        self.guest.installDrivers(source = self.Tools)

        step("Upgrade the tools using tools.iso")
        self.guest.installDrivers(pvPkgSrc = "ToolsISO")

class TCSkipPvPkg(WindowsUpdateBase):

    def run(self, arglist=None):
        
        step("Get the list of the Pv packages ")
        pvDriverList = xenrt.TEC().lookup("PV_DRIVERS_LIST").split(';')
        
        step("Try all possible combinations by skipping each package with Guest Agent installed")
        for pkg in pvDriverList:
            self.skipPvPkginst(random.sample(pvDriverList, 4))

class TCSkipPvPkgNoAgent(WindowsUpdateBase):

    def run(self, arglist=None):
        
        step("Get the list of the Pv packages ")
        pvDriverList = xenrt.TEC().lookup("PV_DRIVERS_LIST").split(';')
        
        step("Try all possible combinations by skipping each package with Guest Agent Not installed")
        for pkg in pvDriverList:
            self.skipPvPkginst(random.sample(pvDriverList, 4), useGuestAgent=False)
