from testing import XenRTUnitTestCase
import os
from xenrt.lib.xenserver import guest
from PIL import Image
from mock import Mock, patch, PropertyMock
import xenrt


def pathForDataFile(fname):
    thisFile = __file__
    thisDir = os.path.dirname(thisFile)
    dataDir = os.path.join(thisDir, '..', 'data')
    return os.path.abspath(os.path.join(dataDir, fname))


class TestIsBSODBlue(XenRTUnitTestCase):

    def testWindows7BSODisBSODBlue(self):
        screenshot = pathForDataFile('bsod-win7.jpg')
        i = Image.open(screenshot)

        self.assertTrue(guest.isBSODBlue(i))

    def testWindows8BSODisBSODBlue(self):
        screenshot = pathForDataFile('bsod-win8.jpg')
        i = Image.open(screenshot)

        self.assertTrue(guest.isBSODBlue(i))

    def testWindows03FullDesktopIsNotBSODBlue(self):
        screenshot = pathForDataFile('win03-desktop-full.jpg')
        i = Image.open(screenshot)

        self.assertFalse(guest.isBSODBlue(i))

    def testWindows08FullDesktopIsNotBSODBlue(self):
        screenshot = pathForDataFile('win8-desktop-full.jpg')
        i = Image.open(screenshot)

        self.assertFalse(guest.isBSODBlue(i))

class TestMaxSupportedVCPU(XenRTUnitTestCase):

    conf = None

    def setUp(self):
        self.conf = xenrt.Config().config

    def __lookup(self, kw, *args):
        if type(kw) == type(""):
            if self.conf.has_key(kw):
                return self.conf[kw]
            return None
        tmp = self.conf
        for key in kw:
            if not tmp.has_key(key):
                return None
            tmp = tmp[key]

        return tmp

    def testDistroLimitLowest(self):
        """Test with the distro limit as the constraint"""
        self.__test("x86", 8, 16, 12, None)

    def testXSLimitLowest(self):
        """Test with the XenServer version limit as the constraint"""
        self.__test("x86", 16, 8, 12, None)

    def testPcpuLimitLowest(self):
        """Test with the host pcpu limit as the constraint"""
        self.__test("x86", 16, 16, 8, None)

    def testDefault(self):
        """Test the default of 4"""
        self.__test("x86", None, None, None, 4)

    @patch("xenrt.TEC")
    def __test(self, arch, distroLimit, xsLimit, pcpuLimit, expected, tec):
        if distroLimit:
            self.__setupGuestLimit(arch == "x86-64" and "MAX_VM_VCPUS64" or "MAX_VM_VCPUS", distroLimit)
        if xsLimit:
            self.__setupXSLimit(xsLimit)
        if pcpuLimit:
            self.__setupPCPULimit(pcpuLimit, tec)

        if expected is None:
            expected = min(filter(lambda c: c is not None, [distroLimit, xsLimit, pcpuLimit]))
        guest = xenrt.lib.xenserver.guest.TampaGuest("Guest")
        guest.distro = "TestDistro"
        guest.arch = arch

        tec.return_value.lookup = self.__lookup
        tec.return_value.lookupHost = Mock(return_value = None)

        self.assertEqual(guest.getMaxSupportedVCPUCount(), expected)

    @patch("xenrt.TEC")
    def testWarnings(self, tec):
        """Verify warnings are generated when expected"""
        w = Mock()
        tec.return_value.warning = w
        guest = xenrt.lib.xenserver.guest.TampaGuest("Guest")
        guest.distro = "TestDistro"
        guest.arch = "x86"

        tec.return_value.lookup = self.__lookup

        # First try without a distro
        self.__setupXSLimit(16)
        self.__setupPCPULimit(16, tec)

        guest.getMaxSupportedVCPUCount()
        w.assert_called()

        # Now with distro, but without a product version
        w.reset_mock()
        self.__setupGuestLimit("MAX_VM_VCPUS", 16)
        del self.conf["PRODUCT_VERSION"]

        guest.getMaxSupportedVCPUCount()
        w.assert_called()

        # Now with just PCPUs
        w.reset_mock()
        del self.conf["GUEST_LIMITATIONS"]["TestDistro"]

        guest.getMaxSupportedVCPUCount()
        w.assert_not_called()

        # Now without PCPUs
        w.reset_mock()
        tec.return_value.registry.return_value = []

        guest.getMaxSupportedVCPUCount()
        w.assert_called()
        

    @patch("xenrt.TEC")
    def test64BitArch(self, tec):
        """Verify architecture is taken into account properly"""
        guest = xenrt.lib.xenserver.guest.TampaGuest("Guest")
        guest.distro = "TestDistro"
        guest.arch = "x86"

        tec.return_value.lookup = self.__lookup

        # First verify the 32-bit version is used
        self.conf["GUEST_LIMITATIONS"]["TestDistro"] = {}
        self.conf["GUEST_LIMITATIONS"]["TestDistro"]["MAX_VM_VCPUS"] = 8
        self.conf["GUEST_LIMITATIONS"]["TestDistro"]["MAX_VM_VCPUS64"] = 16

        self.assertEqual(guest.getMaxSupportedVCPUCount(), 8)

        # Now go 64-bit
        guest.arch = "x86-64"
        self.assertEqual(guest.getMaxSupportedVCPUCount(), 16)

        # Verify Windows uses the 32-bit one regardless
        guest.windows = True
        self.assertEqual(guest.getMaxSupportedVCPUCount(), 8)

    def __setupGuestLimit(self, param, limit):
        self.conf["GUEST_LIMITATIONS"]["TestDistro"] = {}
        self.conf["GUEST_LIMITATIONS"]["TestDistro"][param] = limit

    def __setupXSLimit(self, limit):
        self.conf["PRODUCT_VERSION"] = "TestPV"
        self.conf["VERSION_CONFIG"]["TestPV"] = {}
        self.conf["VERSION_CONFIG"]["TestPV"]["MAX_VM_VCPUS"] = limit

    def __setupPCPULimit(self, limit, tec):
        tec.return_value.registry = Mock()
        tec.return_value.registry.hostList.return_value = ["TestHost"]
        h = Mock()
        tec.return_value.registry.hostGet.return_value = h
        h.getCPUCores.return_value = limit

