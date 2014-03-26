import xenrt
from abc import ABCMeta, abstractmethod

import xenrt.lib.cloud
try:
    from marvin import cloudstackTestClient
    from marvin.integration.lib.base import *
    from marvin import configGenerator
except ImportError:
    pass

class WindowsPackage(object):
    __metaclass__ = ABCMeta 
    
    def __init__(self, instance):
        self._instance = instance
    
    def isInstalled(self): 
        """
        @return: Is the package already installed
        @rytpe: bool
        """
        return False

    def isSupported(self): 
        """
        @return: Is the package supported for the current instance
        @rtype: bool
        """
        return isinstance(self._instance.os, xenrt.lib.opsys.WindowsOS)

    @abstractmethod
    def name(self): 
        """
        @return: a user friendly name for the package
        @rytpe: string
        """
        pass

    @abstractmethod
    def _installPackage(self): 
        """Install the specific package"""
        pass

    def bestEffortInstall(self):
        """ Try to install the package, squelching any XRTErrors rasied"""

        try:
            self.install()
        except xenrt.XRTError, e:
            xenrt.TEC().logverbose("Installation failed: %s" % e)

    def install(self):
        """
        Perform a set of suitability checks and then install the package
        @raise XRTError: if the package is unsuitable
        """
        if not self.isSupported():
            raise xenrt.XRTError("Package %s is not supported for the given instance" % self.name())
        
        if self.isInstalled():
            raise xenrt.XRTError("Package %s is already installed for the given instance" % self.name())
        
        self._installPackage()

class WindowsImagingComponent(WindowsPackage):
    
    def name(self):
        return "Windows Imaging Component"

    def isSupported(self):
        """Only required on W2k3"""

        if not super(self.__class__, self).isSupported():
            return False

        return self._instance.distro.startswith("w2k3")

    def _installPackage(self):
        self._instance.os.unpackTarball("%s/wic.tgz" %
                             (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                             "c:\\")
        exe = self._instance.os.getArch() == "amd64" and "wic_x64_enu.exe" or "wic_x86_enu.exe"
        self._instance.os.execCmd("c:\\wic\\%s /quiet /norestart" % exe,
                        timeout=3600, returnerror=False)
        
        # CA-114127 - sleep to stop this interfering with .net installation later??
        xenrt.sleep(120)

class DotNetFour(WindowsPackage):

    def name(self):
        return ".NET 4 framework"

    def _installPackage(self):
        self._instance.os.createDir("c:\\dotnet40logs")
        self._instance.os.unpackTarball("%s/dotnet40.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\", patient=True)
        self._instance.os.execCmd("c:\\dotnet40\\dotnetfx40.exe /q /norestart /log c:\\dotnet40logs\\dotnet40log", timeout=3600, returnerror=False)
        self._instance.reboot(osInitiated=True)
    
    def isInstalled(self):
        val = 0
        try:
            val = self._instance.os.winRegLookup('HKLM', 'SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v4\\Client', 'Install', healthCheckOnFailure=False)
        except: val = 0

        return val ==  1

