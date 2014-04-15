from mock import PropertyMock, Mock
from testing import XenRTUnitTestCase
from xenrt.lib.cloud.pvtoolsinstall import WindowsXenServer, WindowsLegacyXenServer
from xenrt.lib.opsys import WindowsOS


class TestWindowsXenServerLegacyExcludedForPVTools(XenRTUnitTestCase):
    NON_LEGACY_DISTROS = [("win7", True), ("winxp34344", False), 
                        ("dsjsdfk21312", True), ("w2k3", False)]
    
    LEGACY_DISTROS = [("win7", False), ("winxp34344", True), 
                      ("dsjsdfk21312", False), ("w2k3", True)]

    def test_LegacyDistrosReturnFalse(self):
        """Given a legacy distro, when it is provided to the tools installer, then say this is not supported"""
        self.run_for_many(self.NON_LEGACY_DISTROS, self.__testWindowsXenServerDistroSupported)
    
    def test_LegacyObjectSupportsLegacyDistro(self):
        """Given legacy distro, when asking a legacy pvtools installer, then expect only legacy os to be supported"""
        self.run_for_many(self.LEGACY_DISTROS, self.__testLegacyWindowsXenServerDistroSupported)

    def __setupMocks(self, distro):
        os = Mock(spec=WindowsOS)
        win = Mock()
        type(win).os = PropertyMock(return_value = os)
        type(win).distro = PropertyMock(return_value = distro)
        return win
        
    def __testWindowsXenServerDistroSupported(self, data):
        distro, expected = data
        win = self.__setupMocks(distro)
        self.assertEqual(expected, WindowsXenServer.supportedInstaller(None, win))

    def __testLegacyWindowsXenServerDistroSupported(self, data):
        distro, expected = data
        win = self.__setupMocks(distro)
        self.assertEqual(expected, WindowsLegacyXenServer.supportedInstaller(None, win), "OS checked = %s; expected = %s" % (distro,expected))

