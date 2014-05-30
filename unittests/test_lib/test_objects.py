from testing import XenRTUnitTestCase
import xenrt
from mock import Mock, patch


class TestType:
    Signed, Unsigned = range(2)


class TestVgpuNaming(XenRTUnitTestCase):

    def setUp(self):
        self.__arch = Mock()
        self.__guest = xenrt.GenericGuest("Fake")
        self.__guest.xmlrpcGetArch = self.__arch

    @patch("xenrt.TEC")
    def testVGPUDefaultFileExtensionMatchesPattern(self, tec):
        """
        Given a driver type and architecture, when the file name is requested
        then verify the file extension is correct
        """
        tec.lookup = Mock()
        data = [(tec, TestType.Signed, "x64", ".exe"),
                (tec, TestType.Unsigned, "x64", ".zip"),
                (tec, TestType.Unsigned, "x86", ".zip"),
                (tec, TestType.Signed, "x86", ".exe")]
        self.run_for_many(data, self.__testExtension)

    def __testExtension(self, data):
        tec, driverType, arch, ext = data
        self.__arch.return_value = arch
        self.__guest.requiredVGPUDriverName(driverType)
        name = tec.return_value.lookup.call_args[1]["default"]
        self.assertTrue(name.endswith(ext), "Name: %s does not end with %s"
                                            % (name, ext))

    @patch("xenrt.TEC")
    def testVGPUDefaultDriverNameIsApproxCorrect(self, tec):
        """
        Given a driver type and architecture, when the file name is requested
        then verify the file name contains certain features
        """
        tec.lookup = Mock()
        data = [(tec, TestType.Signed, "x64", "64bit"),
                (tec, TestType.Unsigned, "x64", "WDDM_x64"),
                (tec, TestType.Unsigned, "x86", "WDDM_x86")]
        self.run_for_many(data, self.__testName)

    def __testName(self, data):
        tec, driverType, arch, frag = data
        self.__arch.return_value = arch
        self.__guest.requiredVGPUDriverName(driverType)
        name = tec.return_value.lookup.call_args[1]["default"]
        self.assertTrue(frag in name, "Fragment not in name %s: %s" %
                                     (name, frag))

    @patch("xenrt.TEC")
    def testVGPUDriverNameIsFecthedFromTec(self, tec):
        """
        Given a driver type and architecture, when the file name is requested
        then verify the looked-up TEC filename is returned
        """
        filename = "MyLovelyHorse"
        tec.return_value.lookup = Mock(return_value=filename)
        self.__arch.return_value = "x64"
        fetchedName = self.__guest.requiredVGPUDriverName(TestType.Unsigned)
        self.assertEqual(fetchedName, filename)
