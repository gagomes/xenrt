import xenrt
from testing import XenRTUnitTestCase
from mock import Mock, PropertyMock
from xenrt.lib.opsys.windowspackages import WindowsPackage, WindowsImagingComponent, DotNet4, DotNet35, DotNet2

""" Test Doubles for dependent classes"""
class WindowsPackageDouble(WindowsPackage):
    NAME = "Fake"
    def __init__(self):
        self._os = Mock()
    def _installPackage(self): pass


"""Tests"""
class TestWindowsPackage(XenRTUnitTestCase):

    def test_packageInstalledIfNotAlready(self):
        """When ensureInstalled is called and isInstalled returns false, _installPackage should be called"""
        target = WindowsPackageDouble()
        target.isInstalled = Mock(return_value = False)
        
        mockPackage = Mock()
        target._installPackage = mockPackage
        
        target.ensureInstalled()
        
        self.assertTrue(mockPackage.called)

    def test_packageNotInstalledIfAlready(self):
        """When ensureInstalled is called and isInstalled returns true, _installPackage should not be called"""
        target = WindowsPackageDouble()
        target.isInstalled = Mock(return_value = True)
        
        mockPackage = Mock()
        target._installPackage = mockPackage
        
        target.ensureInstalled()
        
        self.assertFalse(mockPackage.called)


class TestWICPackage(XenRTUnitTestCase):
    def test_onlyW2K3isNotInstalled(self):
        """
        Given a WIC package, when a win distro is provided, then only W2K3 should be supported
        """
        data = [("w2k3", False), ("win7", True), ("win7w2k3", True),
               ("Goldfish", True)]
        self.run_for_many(data, self.__testInstanceDistroIsInstalled)

    def __setupWic(self, distro):
        os = Mock(spec=xenrt.lib.opsys.WindowsOS)
        type(os).distro = PropertyMock(return_value = distro)
        return WindowsImagingComponent(os)
 
    def __testInstanceDistroIsInstalled(self, data):
        distro, expected = data
        wic = self.__setupWic(distro)
        self.assertEqual(wic._packageInstalled(), expected)

class TestDotNet4Package(XenRTUnitTestCase):

    def test_DotNet4Installed(self):
        """
        Given a registry lookup responds, when a .NET4 is queried for installation state, then expect that message to be reported
        """
        data = [(1,True), (0, False)]
        self.run_for_many(data, self.__testDotNet4Installed)
   
    def __testDotNet4Installed(self, data):
        reg, expected = data
        os = Mock(spec=xenrt.lib.opsys.WindowsOS)
        os.winRegLookup = Mock(return_value = reg)
        dn =  DotNet4(os)
        self.assertEqual(expected, dn._packageInstalled())

    def test_DotNet4NotInstallIfExceptionRaised(self):
        """
        Given the registry lookup for .NET4 throws, when the package installation state is queried, then the response will be false
        """
        os = Mock(spec=xenrt.lib.opsys.WindowsOS)
        os.winRegLookup = Mock()
        os.winRegLookup.side_effect = Exception("Kaboom!")
        dn = DotNet4(os)
        self.assertFalse(dn._packageInstalled())

class TestDotNet35Package(XenRTUnitTestCase):

    def test_DotNet35Installed(self):
        """
        Given a registry lookup responds, when a .NET3.5 is queried for installation state, then expect that message to be reported
        """
        data = [(1,True), (0, False)]
        self.run_for_many(data, self.__testDotNet35Installed)
   
    def __testDotNet35Installed(self, data):
        reg, expected = data
        os = Mock(spec=xenrt.lib.opsys.WindowsOS)
        os.winRegLookup = Mock(return_value = reg)
        dn =  DotNet35(os)
        self.assertEqual(expected, dn._packageInstalled())

    def test_DotNet35NotInstallIfExceptionRaised(self):
        """
        Given the registry lookup for .NET3.5 throws, when the package installation state is queried, then the response will be false
        """
        os = Mock(spec=xenrt.lib.opsys.WindowsOS)
        os.winRegLookup = Mock()
        os.winRegLookup.side_effect = Exception("Kaboom!")
        dn = DotNet35(os)
        self.assertFalse(dn._packageInstalled())

class TestDotNet2Package(XenRTUnitTestCase):

    def test_DotNet2Installed(self):
        """
        Given a glob responds, when a .NET 2 is queried for installation state, then expect that message to be reported
        """
        data = [(100,True), (0, False)]
        self.run_for_many(data, self.__testDotNet2Installed)
   
    def __testDotNet2Installed(self, data):
        count, expected = data
        os = Mock(spec=xenrt.lib.opsys.WindowsOS)
        os.globPattern = Mock(return_value = range(count))
        dn =  DotNet2(os)
        self.assertEqual(expected, dn._packageInstalled())

    def test_DotNet35NotInstallIfExceptionRaised(self):
        """
        Given the registry lookup for .NET3.5 throws, when the package installation state is queried, then the response will be false
        """
        os = Mock(spec=xenrt.lib.opsys.WindowsOS)
        os.winRegLookup = Mock()
        os.winRegLookup.side_effect = Exception("Kaboom!")
        dn = DotNet35(os)
        self.assertFalse(dn._packageInstalled())
