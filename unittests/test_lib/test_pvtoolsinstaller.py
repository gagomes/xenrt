from mock import PropertyMock, Mock
from testing import XenRTUnitTestCase
from xenrt.lib.cloud.pvtoolsinstall import WindowsXenServer
from xenrt.lib.opsys import WindowsOS


class TestLegacyExcludedForPVTools(XenRTUnitTestCase):
    NON_LEGACY_DISTROS = [("win7", True), ("winxp34344", False), 
                        ("dsjsdfk21312", True), ("w2k3", False)]


    def test_LegacyDistrosReturnFalse(self):
        """Given a legacy distro, when it is provided to the tools installer, then say this is not supported"""
        self.run_for_many(self.NON_LEGACY_DISTROS, self.__testDistroPairSupported)


    def __testDistroPairSupported(self, data):
        distro, expected = data
        win = Mock(spec=WindowsOS)
        type(win).distro = PropertyMock(return_value = distro)
        self.assertEqual(expected, WindowsXenServer.supportedInstaller(None, win))
