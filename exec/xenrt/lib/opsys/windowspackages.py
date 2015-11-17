import xenrt
from abc import ABCMeta, abstractmethod
from xenrt.lib.opsys.windows import RegisterWindowsPackage
import xenrt.lib.cloud

class WindowsPackage(object):
    __metaclass__ = ABCMeta 
    NAME = None   
    REQUIRE_REBOOT = False
    REQUIRE_IMMEDIATE_REBOOT = False

    def __init__(self, os):
        self._os = os
    
    def isInstalled(self): 
        """
        @return: Is the package already installed
        @rytpe: bool
        """
        if self._os.fileExists("c:\\%s.stamp" % self.__class__.__name__):
            xenrt.TEC().logverbose("Found stamp file for %s" % self.__class__.__name__)
            return True
        else:
            return self._packageInstalled()

    def _packageInstalled(self):
        return False

    def __writeStampFile(self):
        if not self._os.fileExists("c:\\%s.stamp" % self.__class__.__name__):
            self._os.writeFile("c:\\%s.stamp" % self.__class__.__name__, "installed")

    @abstractmethod
    def _installPackage(self): 
        """Install the specific package"""
        pass

    def ensureInstalled(self):
        if not self.isInstalled():
            self._installPackage()
            ret = True
        else:
            ret = False
        self.__writeStampFile()
        return ret

class WindowsImagingComponent(WindowsPackage):
    NAME = "WIC"

    def _packageInstalled(self):
        """Only required on W2k3 - other versions can be treated as if this is installed"""

        return not self._os.distro.startswith("w2k3")

    def _installPackage(self):
        self._os.unpackTarball("%s/wic.tgz" %
                             (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                             "c:\\")
        exe = self._os.getArch() == "amd64" and "wic_x64_enu.exe" or "wic_x86_enu.exe"
        self._os.cmdExec("c:\\wic\\%s /quiet /norestart" % exe,
                        timeout=3600, returnerror=False)
        
        # CA-114127 - sleep to stop this interfering with .net installation later??
        xenrt.sleep(120)

RegisterWindowsPackage(WindowsImagingComponent)

class DotNet35(WindowsPackage):
    NAME = ".NET 3.5"
    REQUIRE_REBOOT = True
    REQUIRE_IMMEDIATE_REBOOT = True

    def _packageInstalled(self):
        try:
            val = self._os.winRegLookup('HKLM', 'SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v3.5', 'Install', healthCheckOnFailure=False)
        except:
            val = 0
        
        return val == 1

    def _installPackage(self):
        if self._os.distro.startswith('ws08r2'):
            filename = "c:\\xrtInstallNet35.ps1"
            fileData = """Import-Module ServerManager
Add-WindowsFeature as-net-framework"""
            self._os.writeFile(filename=filename, data=fileData)
            self._os.enablePowerShellUnrestricted()

            rData = self._os.cmdExec('%s' % (filename),
                                     desc='Install .Net 3.5',
                                     returndata=False, returnerror=True,
                                     timeout=1200, powershell=True)
        elif self._os.distro.startswith('win8') or self._os.distro.startswith('ws12'):
            self._os.parent._osParent_setIso('%s.iso' % (self._os.distro), xenrt.IsoRepository.Windows)
            self._os.cmdExec("dism.exe /online /enable-feature /featurename:NetFX3 /All /Source:D:\sources\sxs /LimitAccess",timeout=3600)
        else:
            self._os.unpackTarball("%s/dotnet35.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\", patient=True)
            self._os.cmdExec("c:\\dotnet35\\dotnetfx35.exe /q /norestart", timeout=3600, returnerror=False)

RegisterWindowsPackage(DotNet35)

class DotNet4(WindowsPackage):
    NAME = ".NET 4"
    REQUIRE_REBOOT = True
    REQUIRE_IMMEDIATE_REBOOT = True

    def _installPackage(self):
        self._os.createDir("c:\\dotnet40logs")
        self._os.unpackTarball("%s/dotnet40.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\", patient=True)
        self._os.cmdExec("c:\\dotnet40\\dotnetfx40.exe /q /norestart /log c:\\dotnet40logs\\dotnet40log", timeout=3600, returnerror=False)
    
    def _packageInstalled(self):
        val = 0
        try:
            val = self._os.winRegLookup('HKLM', 'SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v4\\Client', 'Install', healthCheckOnFailure=False)
        except: val = 0

        return val ==  1

RegisterWindowsPackage(DotNet4)

class DotNet451(WindowsPackage):
    NAME = ".NET 4.5.1"
    REQUIRE_REBOOT = True
    REQUIRE_IMMEDIATE_REBOOT = True
    
    def _installPackage(self):
        self._os.createDir("c:\\dotnet451logs")
        self._os.unpackTarball("%s/dotnet451.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\", patient=True)
        self._os.cmdExec("c:\\dotnet451\\NDP451-KB2858728-x86-x64-AllOS-ENU.exe /q /norestart /log c:\\dotnet451logs\\dotnet451log", timeout=3600, returnerror=False)
    
    def _packageInstalled(self):
        val = 0
        try:
            rawVersion = self.winRegLookup('HKLM', 'SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v4\\Full', 'Release', healthCheckOnFailure=False)
            if rawVersion == 378675 or rawVersion == 378758:
                val = 1
        except: val = 0
        
        return val
        
RegisterWindowsPackage(DotNet451)

class DotNet2(WindowsPackage):
    NAME = ".NET 2"
    REQUIRE_REBOOT = True
    REQUIRE_IMMEDIATE_REBOOT = True

    def _packageInstalled(self):
        g = self._os.globPattern("c:\\windows\\Microsoft.NET\\Framework\\v2*\\mscorlib.dll")
        return len(g) > 0

    def _installPackage(self):
        if self._os.windowsVersion() == "5.1":
            # CA-41364 need a newer version of windows installer
            self._os.installPackage("WindowsInstaller")

        self._os.unpackTarball("%s/dotnet.tgz" %
                                 (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                 "c:\\")
        exe = self._os._os.getArch() == "amd64" and "NetFx20SP2_x64.exe" or "NetFx20SP2_x86.exe"
        self._os.cmdExec("c:\\dotnet\\%s /q /norestart" % exe,
                        timeout=3600, returnerror=False)

RegisterWindowsPackage(DotNet2)

class WindowsInstaller(WindowsPackage):
    NAME = "WindowsInstaller"
    REQUIRE_REBOOT = True
    REQUIRE_IMMEDIATE_REBOOT = True

    def _installPackage(self):
        """Install Windows Installer 4.5."""
        self._os.unpackTarball("%s/wininstaller.tgz" % 
                                 (xenrt.TEC().lookup("TEST_TARBALL_BASE")), 
                                 "c:\\")
        if self._os.windowsVersion() == "6.0":
            if self._os.getArch() == "amd64":  
                self._os.cmdExec("c:\\wininstaller\\Windows6.0-KB942288-v2-x64.msu /quiet /norestart",
                                 timeout=3600, returnerror=False)
            else:
                self._os.cmdExec("c:\\wininstaller\\Windows6.0-KB942288-v2-x86.msu /quiet /norestart",
                                 timeout=3600, returnerror=False)
        elif self._os.windowsVersion() == "5.1":
            if self._os.getArch() == "amd64":
                raise xenrt.XRTError("No 64-bit XP Windows Installer available")
            self._os.cmdExec("c:\\wininstaller\\WindowsXP-KB942288-v3-x86.exe /quiet /norestart",
                            timeout=3600, returnerror=False)
        else:
            if self._os.getArch() == "amd64":  
                self._os.cmdExec("c:\\wininstaller\\WindowsServer2003-KB942288-v4-x64.exe /quiet /norestart",
                                 timeout=3600, returnerror=False)
            else:
                self._os.cmdExec("c:\\wininstaller\\WindowsServer2003-KB942288-v4-x86.exe /quiet /norestart",
                                 timeout=3600, returnerror=False)

RegisterWindowsPackage(WindowsInstaller)

class PowerShell20(WindowsPackage):
    NAME = "PowerShell 2.0"
    REQUIRE_REBOOT = True
    
    def _packageInstalled(self):
        return self._os.getPowershellVersion() >= 2.0
    
    def _installDotNetPackage(self):
        self._os.ensurePackageInstalled(".NET 2", doDelayedReboot=False)
        
    def _getExecutableForGivenArchitecture(self):
        if self._os.windowsVersion() == xenrt.WindowsVersions.ws2008:
            if self._os.getArch() == "amd64":
                return "Windows6.0-KB968930-x64.msu"
            return "Windows6.0-KB968930-x86.msu"
            
        if self._os.windowsVersion() == xenrt.WindowsVersions.ws2003AndR2:
            if self._os.getArch() == "amd64":
                return "WindowsServer2003-KB968930-x64-ENG.exe"
            return "WindowsServer2003-KB968930-x86-ENG.exe"
            
        return "WindowsXP-KB968930-x86-ENG.exe"
    
    @property
    def _packageName(self):
        return "powershell20"

    def _installPackage(self):
        if self._packageInstalled():
            xenrt.TEC().logverbose("%s or above installed." % self.NAME)
            return
        versions = [xenrt.WindowsVersions.winXP,xenrt.WindowsVersions.ws2003AndR2,xenrt.WindowsVersions.ws2008]
            
        if self._os.windowsVersion() not in versions:
            raise xenrt.XRTError("%s installer is not \
                available for Windows version %s" % (self.NAME,self._os.windowsVersion()))
            
        self._installDotNetPackage()   
        exe = self._getExecutableForGivenArchitecture()
        
        t = self._os.tempDir()
        self._os.unpackTarball("%s/%s.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE"),self._packageName), t)
        self._os.cmdExec("%s\\%s\\%s /quiet /norestart" % (t, self._packageName,exe), returnerror=False, timeout=600)
        self._os.reboot()
        
RegisterWindowsPackage(PowerShell20)

class PowerShell30(WindowsPackage):
    ''' Powershell System REquirements https://technet.microsoft.com/en-us/library/hh847769.aspx'''
    NAME = "PowerShell 3.0"
    REQUIRE_REBOOT = True

    def _packageInstalled(self):
        return self._os.getPowershellVersion() >= 3.0

    def _installDotNetPackage(self):
        self._os.ensurePackageInstalled(".NET 4", doDelayedReboot=False)
        
    def _getExecutableForGivenArchitecture(self):
        if self._os.getArch() == "amd64":
            return "Windows6.1-KB2506143-x64.msu"
        return "Windows6.1-KB2506143-x86.msu"

    @property
    def _packageName(self):
        return "powershell30"

    def _installPackage(self):
        if self._packageInstalled():
            xenrt.TEC().logverbose("%s or above installed." % self.NAME)
            return

        self._installDotNetPackage()   
        exe = self._getExecutableForGivenArchitecture()
        
        t = self._os.tempDir()
        self._os.unpackTarball("%s/%s.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE"),self._packageName), t)
        self._os.cmdExec("%s\\%s\\%s /quiet /norestart" % (t, self._packageName,exe), returnerror=False, timeout=600)
        self._os.reboot()
        
RegisterWindowsPackage(PowerShell30)

class PowerShell40(PowerShell30):
    ''' Powershell System REquirements https://technet.microsoft.com/en-us/library/hh847769.aspx'''
    NAME = "PowerShell 4.0"

    def _packageInstalled(self):
        return self._os.getPowershellVersion() >= 4.0
    
    def _installDotNetPackage(self):
        self._os.ensurePackageInstalled(".NET 4.5.1", doDelayedReboot=False)
        
    def _getExecutableForGivenArchitecture(self):
        if self._os.windowsVersion() == xenrt.WindowsVersions.win8AndWS2012:
            return "Windows8-RT-KB2799888-x64.msu"
        if self._os.getArch() == "amd64":
            return "Windows6.1-KB2819745-x64-MultiPkg.msu"
        return "Windows6.1-KB2819745-x86-MultiPkg.msu"

    @property
    def _packageName(self):
        return "powershell40"
    

RegisterWindowsPackage(PowerShell40)
