import xenrt
from testing import XenRTUnitTestCase
from mock import Mock, PropertyMock
from xenrt.lib.cloud.windowspackages import WindowsPackage, WindowsImagingComponent, DotNetFour

""" Test Doubles for dependent classes"""
class WindowsPackageDouble(WindowsPackage):
    def __init__(self): pass
    def name(self): "Fake"
    def _installPackage(self): pass


"""Tests"""
class TestWindowsPackage(XenRTUnitTestCase):
    def test_installThrowsIfAlreadyInstalled(self):
        """
        Given a bad environment, when a windows package is installed, then an exception will be raised
        """
        data = self.combinatorialExcluding([(False,True)],[True, False])
        self.run_for_many(data, self.__installThrows)

    def __installThrows(self, data):
        target = self.__setupMock(data)
        self.assertRaises(xenrt.XRTError, target.install)

    def test_installDoesNotThrow(self):
        """
        Given a clean environment, when a windows package is installed, then expect no problems
        """
        target = self.__setupMock((False, True))
        target.install()

    def __setupMock(self, data):
        installed, supported = data
        target  = WindowsPackageDouble()
        target.isInstalled = Mock(return_value = installed)
        target.isSupported = Mock(return_value = supported)
        return target
   
    def test_bestEffortIsSafeToCall(self):
        """
        Given any environment, when a best effort of the windows package installation is made, then expect no exceptions
        """
        data = self.combinatorial([True, False])
        self.run_for_many(data, self.__callBestEffort)
        
    def __callBestEffort(self, data):
        target = self.__setupMock(data)
        target.bestEffortInstall()

    def test_packageIsInstalledIfSituationGood(self):
        """
        Given a valid environment, when a windows package is installed, then the install package method should be called
        """
        target  = self.__setupMock((False,True))
        mockPackage = Mock()
        target._installPackage = mockPackage
        target.install()
        self.assertTrue(mockPackage.called)
       

class TestWICPackage(XenRTUnitTestCase):
    def test_onlyW2K3isSupported(self):
        """
        Given a WIC package, when a win distro is provided, then only W2K3 should be supported
        """
        data = [("w2k3", True), ("win7", False), ("win7w2k3", False),
               ("Goldfish", False)]
        self.run_for_many(data, self.__testInstanceDistroIsSupported)

    def test_alwaysIsNotInstalled(self):
        """
        Given a WIC package, when any distro is provided, then show WIC is not installed 
        """
        data = [("w2k3", False), ("win7", False), ("win7w2k3", False),
               ("Goldfish", False)]
        self.run_for_many(data, self.__testInstanceDistroIsInstalled)

    def __setupWic(self, distro):
        os = Mock(spec=xenrt.lib.opsys.WindowsOS)
        instance = Mock()
        type(instance).os = PropertyMock(return_value = os) 
        type(instance).distro = PropertyMock(return_value = distro) 
        return WindowsImagingComponent(instance)
 
    def __testInstanceDistroIsInstalled(self, data):
        distro, expected = data
        wic = self.__setupWic(distro)
        self.assertFalse(wic.isInstalled())

    def __testInstanceDistroIsSupported(self, data):
        distro, expected = data
        wic = self.__setupWic(distro)
        supported = wic.isSupported()
        self.assertEqual(expected, supported, "WIC supported %s: %s, expected: %s" %(distro,supported, expected)) 

class TestDotNetFourPackage(XenRTUnitTestCase):

    def test_DotNetFourInstalled(self):
        """
        Given a registry lookup responds, when a .NET4 is queried for installation state, then expect that message to be reported
        """
        data = [(1,True), (0, False)]
        self.run_for_many(data, self.__testDotNetFourInstalled)
   
    def __testDotNetFourInstalled(self, data):
        reg, expected = data
        os = Mock(spec=xenrt.lib.opsys.WindowsOS)
        instance = Mock()
        type(instance).os = PropertyMock(return_value = os) 
        os.winRegLookup = Mock(return_value = reg)
        dn =  DotNetFour(instance)
        self.assertEqual(expected, dn.isInstalled())

    def test_DotNetFourNotInstallIfExceptionRaised(self):
        """
        Given the registry lookup for .NET4 throws, when the package installation state is queried, then the response will be false
        """
        os = Mock(spec=xenrt.lib.opsys.WindowsOS)
        instance = Mock()
        type(instance).os = PropertyMock(return_value = os) 
        os.winRegLookup = Mock()
        os.winRegLookup.side_effect = Exception("Kaboom!")
        dn = DotNetFour(instance)
        self.assertFalse(dn.isInstalled())
        
    def test_DotNetFourIsAlwaysSupported(self):
        """
        Given any distro, when the .NET4 package is queried as to if it can be supported, then expect the answer to be true
        """
        data = [("w2k3", True), ("win7", True), ("BobsYourUncle", True)]
        self.run_for_many(data, self.__testDotNetFourIsAlwaysSupported)

    def __testDotNetFourIsAlwaysSupported(self, data):
        distro, expected = data
        os = Mock(spec=xenrt.lib.opsys.WindowsOS)
        instance = Mock()
        type(instance).os = PropertyMock(return_value = os) 
        type(instance).distro = PropertyMock(return_value = distro) 
        dn = DotNetFour(instance)
        self.assertEqual(expected, dn.isSupported())
         
