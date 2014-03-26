import xenrt
import logging
import os, urllib, string
from datetime import datetime

from xenrt.lib.cloud.windowspackages import DotNetFour, WindowsImagingComponent

import xenrt.lib.cloud
try:
    from marvin import cloudstackTestClient
    from marvin.integration.lib.base import *
    from marvin import configGenerator
except ImportError:
    pass

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
        listIsosC = listIsos.listIsosCmd()
        listIsosC.name="xs-tools.iso"
        isoId = self.cloudstack.marvin.apiClient.listIsos(listIsosC)[0].id

        attachIsoC = attachIso.attachIsoCmd()
        attachIsoC.id = isoId
        attachIsoC.virtualmachineid = self.instance.toolstackId
        self.cloudstack.marvin.apiClient.attachIso(attachIsoC)

        # Allow the CD to appear
        xenrt.sleep(30)
    
    def _installMsi(self):
        self.instance.os.startCmd("D:\\installwizard.msi /passive /liwearcmuopvx c:\\tools_msi_install.log")

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

class WindowsXenServer(WindowsXenServerPVToolsInstaller):

    @staticmethod
    def supportedInstaller(cloudstack, instance):
        """
        @return Is the current instance support
        @rtype Boolean
        """
        # TODO: Check the instance is running on XenServer

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

class WindowsLegacyXenServer(WindowsXenServerPVToolsInstaller):

    @staticmethod
    def supportedInstaller(cloudstack, instance):
        """
        @return Is the current instance support
        @rtype Boolean
        """
        #Name strings from /vol/xenrtdata/iso
        if next((x for x in ["w2k3", "winxp"] if instance.distro.startswith(x)), None):
            return True
        
        return not isinstance(instance.os, xenrt.lib.opsys.WindowsOS)

    def _dotNetInstaller(self):
        """ 
        Factory class method to get the installer for the required dot net version
        @return A appropriate .NET framework installer class
        @rtype WindowsPackage
        """
        return DotNetFour(self.instance)

    def _WIC(self):
        """ 
        Factory class method to get the Windows Imaging Component 
        @return A appropriate package to install WIC
        @rtype WindowsPackage
        """
        return WindowsImagingComponent(self.instance)

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
            u.append("""IF EXIST "%s\\xennet.inf" "c:\\devcon.exe" -r update "%s\\xennet.inf" XEN\\vif""" % (p, p))
            u.append("""IF EXIST "%s\\xeniface.inf" "c:\\devcon.exe" -r update "%s\\xeniface.inf" XEN\\iface""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon.exe" -r update "%s\\xenvif.inf" XENBUS\\CLASS^&VIF""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon.exe" -r update "%s\\xeniface.inf" XENBUS\\CLASS^&IFACE""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon.exe" -r update "%s\\xennet.inf" XENVIF\\DEVICE""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon.exe" -r update "%s\\xennet.inf" XEN\\vif""" % (p, p))
        for p in string.split(xenrt.TEC().lookup("PV_DRIVERS_DIR_64"), ";"):
            u.append("""IF EXIST "%s\\xennet.inf" "c:\\devcon64.exe" -r update "%s\\xennet.inf" XEN\\vif""" % (p, p))
            u.append("""IF EXIST "%s\\xeniface.inf" "c:\\devcon64.exe" -r update "%s\\xeniface.inf" XEN\\iface""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon64.exe" -r update "%s\\xenvif.inf" XENBUS\\CLASS^&VIF""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon64.exe" -r update "%s\\xeniface.inf" XENBUS\\CLASS^&IFACE""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon64.exe" -r update "%s\\xennet.inf" XENVIF\\DEVICE""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon64.exe" -r update "%s\\xennet.inf" XEN\\vif""" % (p, p))
        return string.join(u, "\n")

    def install(self):
        self._WIC().bestEffortInstall()
        self._dotNetInstaller().bestEffortInstall()
        self._loadToolsIso()
        self._installRunOncePVDriversInstallScript()
        self._installMsi()
        self._pollForCompletion()

registerInstaller(WindowsXenServer)
registerInstaller(WindowsLegacyXenServer)
