from mock import PropertyMock, Mock
from testing import XenRTUnitTestCase
from xenrt.lib.cloud.pvtoolsinstall import WindowsTampaXenServer, LegacyWindowsTampaXenServer, WindowsPreTampaXenServer
from xenrt.lib.opsys import WindowsOS
from xenrt.lib.cloud import CloudStack
from collections import namedtuple

class TestPVToolsInstallerSupport(XenRTUnitTestCase):
    NON_LEGACY_DISTROS = [("win7", True), ("winxp34344", False), 
                        ("dsjsdfk21312", True), ("w2k3", False)]
    
    LEGACY_DISTROS = [("win7", False), ("winxp34344", True), 
                      ("dsjsdfk21312", False), ("w2k3", True)]

    
    LEGACY_XENSERVERS = ["5.6", "6.0", "6.0.2"]

    NON_LEGACY_XENSERVERS = ["6.1", "6.1.0", "6.2"]

    def test_LegacyDistrosReturnFalse(self):
        """Given a legacy distro, when it is provided to the tools installer, then say this is not supported"""
        self.run_for_many(self.NON_LEGACY_DISTROS, self.__testWindowsXenServerDistroSupported)
    
    def test_LegacyObjectSupportsLegacyDistro(self):
        """Given legacy distro, when asking a legacy pvtools installer, then expect only legacy os to be supported"""
        self.run_for_many(self.LEGACY_DISTROS, self.__testLegacyWindowsXenServerDistroSupported)

    def __setupMocks(self, hypervisor, hypervisorVersion, distro):
        os = Mock(spec=WindowsOS)
        win = Mock()
        type(win).os = PropertyMock(return_value = os)
        type(win).distro = PropertyMock(return_value = distro)
        cs = Mock()

        hypervisorInfo = namedtuple('hypervisorInfo', ['type','version'])
        hv = hypervisorInfo(hypervisor, hypervisorVersion)
        cs.instanceHypervisorTypeAndVersion = Mock(return_value=hv)
        return (cs, win)
        
    def __testWindowsXenServerDistroSupported(self, data):
        distro, expected = data
        (cs, win) = self.__setupMocks("XenServer", "6.2", distro)
        self.assertEqual(expected, WindowsTampaXenServer.supportedInstaller(cs, win))

    def __testLegacyWindowsXenServerDistroSupported(self, data):
        distro, expected = data
        (cs, win) = self.__setupMocks("XenServer", "6.2", distro)
        self.assertEqual(expected, LegacyWindowsTampaXenServer.supportedInstaller(cs, win), "OS checked = %s; expected = %s" % (distro,expected))

    def testLegacyXenServerSupported(self):
        xs = [(x, True) for x in self.LEGACY_XENSERVERS] + [(x, False) for x in self.NON_LEGACY_XENSERVERS]
        self.run_for_many(xs, self.__testLegacyXenServerSupported)

    def testNonLegacyXenServerSupportedOnLegacyWindows(self):
        xs = [(x, False) for x in self.LEGACY_XENSERVERS] + [(x, True) for x in self.NON_LEGACY_XENSERVERS]
        self.run_for_many(xs, self.__testNonLegacyXenServerSupportedOnLegacyWindows)

    def testNonLegacyXenServerSupportedOnNonLegacyWindows(self):
        xs = [(x, False) for x in self.LEGACY_XENSERVERS] + [(x, True) for x in self.NON_LEGACY_XENSERVERS]
        self.run_for_many(xs, self.__testNonLegacyXenServerSupportedOnNonLegacyWindows)

    def __testNonLegacyXenServerSupportedOnLegacyWindows(self, data):
        xs, expected = data
        (cs, win) = self.__setupMocks("XenServer", xs, "w2k3")
        self.assertEqual(expected, LegacyWindowsTampaXenServer.supportedInstaller(cs, win), "XS checked = %s; expected = %s" % (xs, expected))

    def __testNonLegacyXenServerSupportedOnNonLegacyWindows(self, data):
        xs, expected = data
        (cs, win) = self.__setupMocks("XenServer", xs, "win7sp1-x86")
        self.assertEqual(expected, WindowsTampaXenServer.supportedInstaller(cs, win), "XS checked = %s; expected = %s" % (xs, expected))

    def __testLegacyXenServerSupported(self, data):
        xs, expected = data
        cs, win = self.__setupMocks("XenServer", xs, "w2k3")
        self.assertEqual(expected, WindowsPreTampaXenServer.supportedInstaller(cs, win), "XS checked = %s; expected = %s" % (xs, expected))

    def testNonXenServer(self):
        versions = [
                    (WindowsTampaXenServer, "6.2", "win7sp1-x86"),
                    (LegacyWindowsTampaXenServer, "6.2", "w2k3"),
                    (WindowsPreTampaXenServer, "6.0.2", "win7sp1-x86")]

        self.run_for_many(versions, self.__testNonXenServerNotSupported)

    def __testNonXenServerNotSupported(self, data):
        cls, version, distro = data
        # First check it's fine with XenServer
        (cs, win) = self.__setupMocks("XenServer", version, distro)
        self.assertTrue(cls.supportedInstaller(cs, win), "Class checked against XenServer for Sanity = %s, Version = %s, Distro = %s, expected True" % (cls.__name__, version, distro))
        # Now check it doesn't work with KVM
        (cs, win) = self.__setupMocks("KVM", version, distro)
        self.assertFalse(cls.supportedInstaller(cs, win), "Class checked against KVM = %s, Version = %s, Distro = %s, expected False" % (cls.__name__, version, distro))
