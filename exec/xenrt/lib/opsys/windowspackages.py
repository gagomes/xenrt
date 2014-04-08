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

class DotNetFour(WindowsPackage):
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

RegisterWindowsPackage(DotNetFour)

