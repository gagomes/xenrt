import xenrt
from abc import ABCMeta, abstractmethod
from xenrt.lib.opsys.windows import RegisterWindowsPackage
import xenrt.lib.cloud

class WindowsPackage(object):
    __metaclass__ = ABCMeta 
    NAME = None    
    def __init__(self, os):
        self._os = os
    
    def isInstalled(self): 
        """
        @return: Is the package already installed
        @rytpe: bool
        """
        return False

    @abstractmethod
    def _installPackage(self): 
        """Install the specific package"""
        pass

    def ensureInstalled(self, installOptions={}):
        if not self.isInstalled(installOptions):
            self._installPackage(installOptions)

class WindowsImagingComponent(WindowsPackage):
    NAME = "WIC"

    def isInstalled(self, installOptions):
        """Only required on W2k3 - other versions can be treated as if this is installed"""

        return not self._os.distro.startswith("w2k3")

    def _installPackage(self, installOptions):
        self._os.unpackTarball("%s/wic.tgz" %
                             (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                             "c:\\")
        exe = self._os.getArch() == "amd64" and "wic_x64_enu.exe" or "wic_x86_enu.exe"
        self._os.execCmd("c:\\wic\\%s /quiet /norestart" % exe,
                        timeout=3600, returnerror=False)
        
        # CA-114127 - sleep to stop this interfering with .net installation later??
        xenrt.sleep(120)

RegisterWindowsPackage(WindowsImagingComponent)

class DotNet35(WindowsPackage):
    NAME = ".NET 3.5"

    def isInstalled(self):
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

            rData = self._os.execCmd('%s' % (filename),
                                     desc='Install .Net 3.5',
                                     returndata=False, returnerror=True,
                                     timeout=1200, powershell=True)
        elif self._os.distro.startswith('win8') or self._os.distro.startswith('ws12'):
            self._os.parent.setInstanceIso('%s.iso' % (self._os.distro), xenrt.IsoRepository.Windows)
            self._os.execCmd("dism.exe /online /enable-feature /featurename:NetFX3 /All /Source:D:\sources\sxs /LimitAccess",timeout=3600)
        else:
            self._os.unpackTarball("%s/dotnet35.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\", patient=True)
            self._os.execCmd("c:\\dotnet35\\dotnetfx35.exe /q /norestart", timeout=3600, returnerror=False)
            self._os.reboot()
            xenrt.sleep(120)
            self._os.waitForBoot(600)

RegisterWindowsPackage(DotNet35)

class DotNet4(WindowsPackage):
    NAME = ".NET 4"

    def _installPackage(self, installOptions):
        self._os.createDir("c:\\dotnet40logs")
        self._os.unpackTarball("%s/dotnet40.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\", patient=True)
        self._os.execCmd("c:\\dotnet40\\dotnetfx40.exe /q /norestart /log c:\\dotnet40logs\\dotnet40log", timeout=3600, returnerror=False)
        self._os.reboot()
        xenrt.sleep(120)
        self._os.waitForBoot(600)
    
    def isInstalled(self, installOptions):
        val = 0
        try:
            val = self._os.winRegLookup('HKLM', 'SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v4\\Client', 'Install', healthCheckOnFailure=False)
        except: val = 0

        return val ==  1

RegisterWindowsPackage(DotNet4)

class DotNet2(WindowsPackage):
    NAME = ".NET 2"

    def isInstalled(self, installOptions):
        g = self._os.globPattern("c:\\windows\\Microsoft.NET\\Framework\\v2*\\mscorlib.dll")
        return len(g) > 0

    def _installPackage(self, installOptions):
        if self._os.windowsVersion() == "5.1":
            # CA-41364 need a newer version of windows installer
            self._os.installPackage("WindowsInstaller")

        self._os.unpackTarball("%s/dotnet.tgz" %
                                 (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                 "c:\\")
        exe = self._os._os.getArch() == "amd64" and "NetFx20SP2_x64.exe" or "NetFx20SP2_x86.exe"
        self._os.execCmd("c:\\dotnet\\%s /q /norestart" % exe,
                        timeout=3600, returnerror=False)
        self._os.reboot()
        xenrt.sleep(120)
        self._os.waitForBoot(600)

RegisterWindowsPackage(DotNet2)

class WindowsInstaller(WindowsPackage):
    NAME = "WindowsInstaller"

    def _installPackage(self):
        """Install Windows Installer 4.5."""
        self._os.unpackTarball("%s/wininstaller.tgz" % 
                                 (xenrt.TEC().lookup("TEST_TARBALL_BASE")), 
                                 "c:\\")
        if self._os.windowsVersion() == "6.0":
            if self._os.getArch() == "amd64":  
                self._os.execCmd("c:\\wininstaller\\Windows6.0-KB942288-v2-x64.msu /quiet /norestart",
                                 timeout=3600, returnerror=False)
            else:
                self._os.execCmd("c:\\wininstaller\\Windows6.0-KB942288-v2-x86.msu /quiet /norestart",
                                 timeout=3600, returnerror=False)
        elif self._os.windowsVersion() == "5.1":
            if self._os.getArch() == "amd64":
                raise xenrt.XRTError("No 64-bit XP Windows Installer available")
            self._os.execCmd("c:\\wininstaller\\WindowsXP-KB942288-v3-x86.exe /quiet /norestart",
                            timeout=3600, returnerror=False)
        else:
            if self._os.getArch() == "amd64":  
                self._os.execCmd("c:\\wininstaller\\WindowsServer2003-KB942288-v4-x64.exe /quiet /norestart",
                                 timeout=3600, returnerror=False)
            else:
                self._os.execCmd("c:\\wininstaller\\WindowsServer2003-KB942288-v4-x86.exe /quiet /norestart",
                                 timeout=3600, returnerror=False)
        self._os.reboot()
        xenrt.sleep(120)
        self._os.waitForBoot(600)

RegisterWindowsPackage(WindowsInstaller)
