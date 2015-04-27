# Test harness for Xen and the XenServer product family

# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import socket, re, string, time, traceback, sys, random, copy, math
import xenrt, xenrt.lib.xenserver
from xenrt.lazylog import log

class WindowsUpdateBase(xenrt.TestCase):
    
    def prepare(self, arglist=None):
        
        self.args  = self.parseArgsKeyValue(arglist)
        self.host = self.getDefaultHost()
        self.guest = self.host.getGuest(self.args['guest'])
        self.snapshot = self.guest.snapshot()
        if self.args.has_key('TOOLS'):
            self.Tools = self.args['TOOLS']

    def postRun(self):
        
        log("Revert the VM back to the original state")
        self.guest.revert(self.snapshot)
        self.guest.lifecycleOperation("vm-start")
        self.guest.removeSnapshot(self.snapshot)
        
class TCSnapRevertTools(WindowsUpdateBase):
    
    def run(self, arglist=None):
        
        log("Install PV Drivers on the windows guest")
        self.guest.installDrivers()
        
        log("Take snapshot of the VM")
        snapshot = self.guest.snapshot()
        
        log("Uninstall the PV Drivers on the Guest")
        self.guest.uninstallDrivers()
        
        log("Revert the VM to the State before tools were uninstalled")
        self.guest.revert(snapshot)
        self.guest.removeSnapshot(snapshot)
        
        self.guest.start()
        
        log("Verify tools are present after the VM is reverted to previous state")
        if self.guest.checkPVDevicesState() and not self.guest.checkPVDriversStatus(ignoreException = True):
            raise xenrt.XRTFailure("PV Tools not present after the Reverting VM to state where tools were installed ")
        
class TCSnapRevertNoTools(WindowsUpdateBase):
    
    def run(self, arglist=None):
        
        log("Take snapshot of the VM")
        snapshot = self.guest.snapshot()
        
        log("Install PV Drivers on the windows guest")
        self.guest.installDrivers()
        
        log("Revert the VM to the State before tools were uninstalled")
        self.guest.revert(snapshot)
        self.guest.removeSnapshot(snapshot)
        self.guest.lifecycleOperation("vm-start")
        
        log("Verify tools are not present after the VM is reverted to previous state")
        if not self.guest.checkPVDevicesState():
            raise xenrt.XRTFailure("PV Tools present after the Reverting VM to state where tools were not installed ")

class TCUpgWinCmp(WindowsUpdateBase):
    
    def run(self, arglist=None):

        log("Install Windows update compatible PV Drivers")
        super(DundeeGuest , self).installDrivers(source = self.Tools)
        
        log("Enable the Windows Updates from the Host")
        self.guest.enableWindowsPVUpdates()
        
        log("Update PV Drivers on the windows guest")
        self.guest.installDrivers()

class TCUpgNonWinCmp(WindowsUpdateBase):

    def run(self, arglist=None):

        log("Install Non-Windows update compatible PV Drivers")
        super(DundeeGuest , self).installDrivers(source = self.Tools)
        
        log("Uninstall Non-Windows Update Compatible PV Drivers")
        super(DundeeGuest , self).uninstallDrivers()
        
        log("Enable the Windows Updates from the Host")
        self.guest.enableWindowsPVUpdates()
        
        log("Install PV Drivers on the windows guest")
        self.guest.installDrivers()

class TCUpgToolsIso(WindowsUpdateBase):

    def run(self, arglist=None):
        
        log("Install the PV Drivers on the Windows Guest")
        self.guest.installDrivers(source = self.Tools)

        log("Upgrade the tools using tools.iso")
        super(DundeeGuest , self).installDrivers(waitForDaemon)

class TCSkipPvPkg(WindowsUpdateBase):

    def skipPvPkginst(self, pkgList):
        
        log("Take snapshot of the VM")
        snapshot = self.snapshot()
        
        log("Install PV Drivers on the windows guest")
        self.installDrivers(packagesToInstall = pkgList)
        
        self.waitForDaemon(300, desc="Guest check after installation of PV Packages %s" %(pkgList))
        
        log("Revert the VM to the State before tools were uninstalled")
        self.revert(snapshot)
        self.removeSnapshot(snapshot)
        self.lifecycleOperation("vm-start")
        
    def run(self, arglist=None):

        pvDriversList = xenrt.TEC().lookup("PV_DRIVERS_LIST").split(';')
        
        for pkg in pvDriversList:
            self.guest.skipPvPkginst(random.sample(pvDriverList, 4))

class TCRemovePvpkg(WindowsUpdateBase):


    def removePvpkg(self,pvPkg):

        log("Install PV Drivers on the windows guest")
        self.uninstallDrivers(pkgToUninstall = pvPkg)
        
        self.waitForDaemon(300, desc="Guest check after Uninstallation of PV Packages %s" %(pkgList))
        
    def run(self, arglist=None):
        
        pvDriversToRm = xenrt.TEC().lookup("PV_DRIVERS_UNINSTALL_LIST").split(';')
        
        log("Install PV Drivers on the windows guest")
        self.guest.installDrivers()
        
        for pkg in pvDriversToRm:
            self.guest.removePvPkg(pkg)
