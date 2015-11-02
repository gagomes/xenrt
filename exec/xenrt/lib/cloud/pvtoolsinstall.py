import xenrt
import logging
import os, urllib, string
from datetime import datetime
import xenrt.lib.cloud

installerList = []

def pvToolsInstallerFactory(cloudstack, instance):
    for i in installerList:
        if i.supportedInstaller(cloudstack, instance):
            return i(cloudstack, instance)
    raise xenrt.XRTError("No PV Tools installer found")

def registerInstaller(installer):
    installerList.append(installer)

class PVToolsInstaller(object):
    def __init__(self, cloudstack, instance):
        self.cloudstack = cloudstack
        self.instance = instance

    @staticmethod
    def supportedInstaller(cloudstack, instance):
        return False

class WindowsXenServerPVToolsInstaller(PVToolsInstaller):
    
    def _loadToolsIso(self):
        self.instance.setIso("xs-tools.iso")
    
    def _installMsi(self):
        self.instance.os.cmdStart("D:\\installwizard.msi /passive /liwearcmuopvx c:\\tools_msi_install.log")

    def _pollForCompletion(self):
        deadline = xenrt.util.timenow() + 3600
        while True:
            regValue = ""
            try:
                regValue = self.instance.os.winRegLookup('HKLM', "SOFTWARE\\Wow6432Node\\Citrix\\XenToolsInstaller", "InstallStatus", healthCheckOnFailure=False)
            except:
                try:
                    regValue = self.instance.os.winRegLookup('HKLM', "SOFTWARE\\Citrix\\XenToolsInstaller", "InstallStatus", healthCheckOnFailure=False)
                except:
                    pass
                
            if xenrt.util.timenow() > deadline:
                #instanse.os.checkHealth(desc="Waiting for installer registry key to be written")
                
                if regValue and len(regValue) > 0:
                    raise xenrt.XRTFailure("Timed out waiting for installer registry key to be written. Value=%s" % regValue)
                else:
                    raise xenrt.XRTFailure("Timed out waiting for installer registry key to be written.")
            
            elif "Installed" == regValue:
                break
            else:
                xenrt.sleep(30)

class WindowsTampaXenServer(WindowsXenServerPVToolsInstaller):

    @staticmethod
    def supportedInstaller(cloudstack, instance):
        """
        @return Is the current instance support
        @rtype Boolean
        """
        hypervisor = cloudstack.instanceHypervisorTypeAndVersion(instance, nativeCloudType=True)
        if hypervisor.type != 'XenServer':
            return False
        if hypervisor.version < "6.1":
            return False
        #Name strings from /vol/xenrtdata/iso
        if next((x for x in ["w2k3", "winxp"] if instance.distro.startswith(x)), None):
            return False
        
        if not isinstance(instance.os, xenrt.lib.opsys.WindowsOS):
            return False
        
        return True

    def __waitForInstaller(self):
        deadline = xenrt.util.timenow() + 300 
        while True:
            try:
                if self.instance.os.fileExists("D:\\installwizard.msi"):
                    break
            except:
                pass
            if xenrt.util.timenow() > deadline:
                raise xenrt.XRTError("Installer did not appear")
            
            xenrt.sleep(5)

    def install(self):
        self._loadToolsIso()
        self.__waitForInstaller()
        self._installMsi()
        self._pollForCompletion()

class LegacyWindowsTampaXenServer(WindowsXenServerPVToolsInstaller):

    @staticmethod
    def supportedInstaller(cloudstack, instance):
        """
        @return Is the current instance support
        @rtype Boolean
        """
        hypervisor = cloudstack.instanceHypervisorTypeAndVersion(instance, nativeCloudType=True)
        if hypervisor.type != 'XenServer':
            return False
        if hypervisor.version < "6.1":
            return False

        #Name strings from /vol/xenrtdata/iso
        if not next((x for x in ["w2k3", "winxp"] if instance.distro.startswith(x)), None):
            return False
        
        return isinstance(instance.os, xenrt.lib.opsys.WindowsOS)

    def _installDotNet(self):
        """ 
        Factory class method to get the installer for the required dot net version
        @return A appropriate .NET framework installer class
        @rtype WindowsPackage
        """
        self.instance.os.ensurePackageInstalled(".NET 4")

    def _installWIC(self):
        """ 
        Factory class method to get the Windows Imaging Component 
        @return A appropriate package to install WIC
        @rtype WindowsPackage
        """
        self.instance.os.ensurePackageInstalled("WIC")

    def _installRunOncePVDriversInstallScript(self):
        self.instance.os.sendFile("%s/distutils/soon.exe" % (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")),"c:\\soon.exe")
        self.instance.os.sendFile("%s/distutils/devcon.exe" % (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")), "c:\\devcon.exe")
        self.instance.os.sendFile("%s/distutils/devcon64.exe" % (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")), "c:\\devcon64.exe")
        runonce2 = xenrt.TEC().tempFile()
        
        updatecmd = self.__generateRunOnceScript()
        f = file(runonce2, "w")
        f.write("""echo R1.1 > c:\\r1.txt
REM ping 127.0.0.1 -n 60 -w 1000
echo R1.2 > c:\\r2.txt
%s
echo R1.3 > c:\\r3.txt
""" % (updatecmd))
        f.close()
        self.instance.os.sendFile(runonce2, "c:\\runoncepvdrivers2.bat")
        runonce = xenrt.TEC().tempFile()
        f = file(runonce, "w")
        f.write("""c:\\soon.exe 900 /INTERACTIVE c:\\runoncepvdrivers2.bat > c:\\xenrtlog.txt
at > c:\\xenrtatlog.txt
""")
        f.close()
        self.instance.os.sendFile(runonce, "c:\\runoncepvdrivers.bat")

        # Set the run once script
        self.instance.os.winRegAdd("HKLM",
                       "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\"
                       "RunOnce",
                       "XenRTPVDrivers",
                       "SZ",
                       "c:\\runoncepvdrivers.bat")
    
    def __generateRunOnceScript(self):
        u = []
        for p in string.split(xenrt.TEC().lookup("PV_DRIVERS_DIR"), ";"):
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon.exe" -r update "%s\\xenvif.inf" XENBUS\\CLASS^&VIF""" % (p, p))
            u.append("ping 127.0.0.1 -n 20 -w 1000")
            u.append("""IF EXIST "%s\\xeniface.inf" "c:\\devcon.exe" -r update "%s\\xeniface.inf" XENBUS\\CLASS^&IFACE""" % (p, p))
            u.append("ping 127.0.0.1 -n 20 -w 1000")
            u.append("""IF EXIST "%s\\xennet.inf" "c:\\devcon.exe" -r update "%s\\xennet.inf" XEN\\vif""" % (p, p))
        for p in string.split(xenrt.TEC().lookup("PV_DRIVERS_DIR_64"), ";"):
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon64.exe" -r update "%s\\xenvif.inf" XENBUS\\CLASS^&VIF""" % (p, p))
            u.append("ping 127.0.0.1 -n 20 -w 1000")
            u.append("""IF EXIST "%s\\xeniface.inf" "c:\\devcon64.exe" -r update "%s\\xeniface.inf" XENBUS\\CLASS^&IFACE""" % (p, p))
            u.append("ping 127.0.0.1 -n 20 -w 1000")
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon64.exe" -r update "%s\\xennet.inf" XEN\\vif""" % (p, p))
        return string.join(u, "\n")

    def install(self):
        self._installWIC()
        self._installDotNet()
        self._loadToolsIso()
        self._installRunOncePVDriversInstallScript()
        self._installMsi()
        self._pollForCompletion()

class WindowsPreTampaXenServer(LegacyWindowsTampaXenServer):
    @staticmethod
    def supportedInstaller(cloudstack, instance):
        """
        @return Is the current instance support
        @rtype Boolean
        """
        hypervisor = cloudstack.instanceHypervisorTypeAndVersion(instance, nativeCloudType=True)
        if hypervisor.type != 'XenServer':
            return False
        if hypervisor.version >= "6.1":
            return False

        return isinstance(instance.os, xenrt.lib.opsys.WindowsOS)

    def _installMsi(self):
        # Note down the VM's uptime
        self.vmuptime = self.instance.os.uptime

        # Kill the autorun version
        self.instance.os.killAll("xensetup.exe")
        self.instance.os.cmdStart("d:\\xensetup.exe /S")

    def _pollForCompletion(self):
        # Wait until we see a reduction in uptime
        deadline = xenrt.util.timenow() + 3600
        while True:
            self.instance.os.waitForDaemon(deadline - xenrt.util.timenow())
            try:
                newUptime = self.instance.os.uptime
                if newUptime < self.vmuptime:
                    break
            except:
                pass
            if xenrt.util.timenow() > deadline:
                raise xenrt.XRTError("VM did not reboot")
            
            xenrt.sleep(30)

        # Now wait for the necessary XenStore key to appear
        while True:
            try:
                if self.instance.os.xenstoreRead("attr/PVAddons/Installed").strip() == "1":
                    xenrt.TEC().logverbose("Found PVAddons evidence, sleeping 5 seconds to allow Xapi to settle")
                    xenrt.sleep(5)
                    break
            except:
                pass
            if xenrt.util.timenow() > deadline:
                raise xenrt.XRTError("Couldn't find PV driver evidence")

registerInstaller(WindowsTampaXenServer)
registerInstaller(LegacyWindowsTampaXenServer)
registerInstaller(WindowsPreTampaXenServer)
