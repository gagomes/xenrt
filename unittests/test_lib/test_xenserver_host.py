from testing import XenRTUnitTestCase
from mock import Mock, patch, PropertyMock
import xenrt


class TestCoresPerSocket(XenRTUnitTestCase):
    def setUp(self):
        self.__setVCPUs = Mock()
        self.__sockets = Mock()
        self.__win = PropertyMock(return_value=True)
        self.__rndCoresPerSocket = None

    def __setMocksOnHost(self, host):
        host.getCPUCores = Mock(return_value=8)
        host.getNoOfSockets = Mock(return_value=2)
        return host

    def __setMocksOnGuest(self, guest):
        guest.getMaxSupportedVCPUCount = Mock(return_value=16)
        guest.setVCPUs = self.__setVCPUs
        guest.setCoresPerSocket = self.__sockets
        guest.windows = self.__win
        return guest

    def cps_db_lookup(self, param, default=None, boolean=False):
        if param == "RND_CORES_PER_SOCKET_VAL":
            return self.__rndCoresPerSocket
        return default

    @patch("xenrt.TEC")
    @patch("random.choice")
    def testTampaDoesNotGetRandomCores(self, rand, _tec):
        """Tampa hosts don't get random called when setting sockets"""
        host = xenrt.lib.xenserver.host.TampaHost(None, None)
        guest = self.__setMocksOnGuest(xenrt.lib.xenserver.guest.TampaGuest("Guest"))
        guest.setRandomCoresPerSocket(host, 23)
        self.assertFalse(rand.called)

    @patch("random.choice")
    @patch("xenrt.GEC")
    @patch("xenrt.TEC")
    def testClearWaterGetsRandomCores(self, tec, gec, rand):
        """Clearwater hosts do get random called when setting sockets"""
        host = self.__setMocksOnHost(xenrt.lib.xenserver.host.ClearwaterHost(None, None))
        self.__rndCoresPerSocket = 0
        tec.return_value.lookup.side_effect = self.cps_db_lookup
        guest = self.__setMocksOnGuest(xenrt.lib.xenserver.guest.TampaGuest("Guest"))
        guest.setRandomCoresPerSocket(host, 23)
        self.assertTrue(rand.called)

    @patch("xenrt.GEC")
    @patch("xenrt.TEC")
    def testClearwaterGetsSocketsSet(self, tec, gec):
        """For a CLR host the number of sockets should be set"""
        host = self.__setMocksOnHost(xenrt.lib.xenserver.host.ClearwaterHost(None, None))
        self.__rndCoresPerSocket = 0
        tec.return_value.lookup.side_effect = self.cps_db_lookup
        guest = self.__setMocksOnGuest(xenrt.lib.xenserver.guest.TampaGuest("Guest"))
        guest.setRandomCoresPerSocket(host, 23)
        self.assertTrue(self.__sockets.called)

    @patch("xenrt.GEC")
    @patch("xenrt.TEC")
    def testClearwaterGetsSocketsSetWithDbValueSet(self, tec, gec):
        """For a CLR host the number of sockets should be set if the
        cores per socket value has been pulled from the database"""
        host = self.__setMocksOnHost(xenrt.lib.xenserver.host.ClearwaterHost(None, None))
        self.__rndCoresPerSocket = 4
        tec.return_value.lookup.side_effect = self.cps_db_lookup
        guest = self.__setMocksOnGuest(xenrt.lib.xenserver.guest.TampaGuest("Guest"))
        guest.setRandomCoresPerSocket(host, 23)
        self.assertTrue(self.__sockets.called)

    @patch("xenrt.GEC")
    @patch("xenrt.TEC")
    def testTampaDoesntGetSocketsSet(self, tec, gec):
        """For TAM hosts expect the number of sockets not to be set"""
        host = self.__setMocksOnHost(xenrt.lib.xenserver.host.TampaHost(None, None))
        self.__rndCoresPerSocket = 0
        tec.return_value.lookup.side_effect = self.cps_db_lookup
        guest = self.__setMocksOnGuest(xenrt.lib.xenserver.guest.TampaGuest("Guest"))
        guest.setRandomCoresPerSocket(host, 23)
        self.assertFalse(self.__sockets.called)

    @patch('xenrt.TEC')
    def testClearwaterPVGuestDoesNotGetSocketsSet(self, _tec):
        """For a CLR host given a PV guest expect the number of sockets not to be set"""
        host = self.__setMocksOnHost(xenrt.lib.xenserver.host.ClearwaterHost(None, None))
        guest = self.__setMocksOnGuest(xenrt.lib.xenserver.guest.TampaGuest("Guest"))
        guest.windows = False
        guest.setRandomCoresPerSocket(host, 23)
        self.assertFalse(self.__sockets.called)


class TestCheckRpmInstalled(XenRTUnitTestCase):

    @patch('xenrt.TEC')
    def setUp(self, _tec):
        self.__cut = xenrt.lib.xenserver.host.ClearwaterHost(None, None)
        self.__exec = Mock(return_value="I am installed, honest")
        self.__cut.execdom0 = self.__exec

    def testThatExtensionIsRemoved(self):
        """Given a filename and extension, when it's presence is checked
           then expect that the extension is removed"""

        data = [("CurryMonster", "CurryMonster"),
                ("SmokeMe.A.Kipper.txt", "SmokeMe.A.Kipper"),
                ("IAmQueeg.jape", "IAmQueeg")]
        self.run_for_many(data, self.__testThatExtensionIsRemoved)

    def __testThatExtensionIsRemoved(self, data):
        fileName, expected = data
        self.__cut.checkRPMInstalled(fileName)
        checked = self.__exec.call_args
        self.assertTrue(checked.endswith(expected))

    def testReturnStringFromTheIssuedCommand(self):
        """Given a positive response from the command, when
        return value is checked, verify it's true"""
        self.__exec.return_value = "Installed, or whatever"
        self.assertTrue(self.__cut.checkRPMInstalled("GELF"))

    def testReturnStringFromTheIssuedCommandReturnsFalse(self):
        """Given a negative repsonse from the dom0 command,
        when the return value is checked, then expect false"""
        self.__exec.return_value = "I haz is not installed it"
        self.assertFalse(self.__cut.checkRPMInstalled("GELF"))

    def testCommandExceptionReturnsFalse(self):
        """Given a execption is raised from the command in dom0,
        when checkRPM is called, then expect the exception to be
        squashed and false returned"""
        self.__exec.side_effect = Exception
        self.assertFalse(self.__cut.checkRPMInstalled("Polymorph"))


class TestDundeeHost(XenRTUnitTestCase):
    @patch('xenrt.TEC')
    def testvSwitchCoverageLog(self, tec):
        host = xenrt.lib.xenserver.host.DundeeHost(None, None)
        host.vswitchAppCtl = Mock()

        host.vSwitchCoverageLog()

        host.vswitchAppCtl.assert_called_once_with('coverage/show')

    @patch('xenrt.TEC')
    def testguestFactory(self, tec):
        host = xenrt.lib.xenserver.host.DundeeHost(None, None)

        guestFactory = host.guestFactory()

        self.assertEquals('DundeeGuest', guestFactory.__name__)


class TestCreedenceHost(XenRTUnitTestCase):
    @patch('xenrt.TEC')
    def testvSwitchCoverageLog(self, tec):
        host = xenrt.lib.xenserver.host.CreedenceHost(None, None)
        host.vswitchAppCtl = Mock()

        host.vSwitchCoverageLog()

        host.vswitchAppCtl.assert_called_once_with('coverage/show')

    @patch('xenrt.TEC')
    def testguestFactory(self, tec):
        host = xenrt.lib.xenserver.host.CreedenceHost(None, None)

        guestFactory = host.guestFactory()

        self.assertEquals('CreedenceGuest', guestFactory.__name__)


class TestHostLicenseBehaviourForCreedence(XenRTUnitTestCase):

    def _getHost(self):
        return xenrt.lib.xenserver.host.CreedenceHost(None, None)

    @patch("xenrt.lib.xenserver.licensing.XenServerLicenseFactory.allLicenses")
    @patch('xenrt.TEC')
    def testAllSKUsReturnListOfLicenses(self, tec, fac):
        host = self._getHost()
        host.validLicenses()
        self.assertTrue(fac.called)

    @patch("xenrt.lib.xenserver.licensing.XenServerLicenseFactory.xenserverOnlyLicenses")
    @patch('xenrt.TEC')
    def testXenServerOnlySKUsReturnListOfLicenses(self, tec, fac):
        host = self._getHost()
        host.validLicenses(True)
        self.assertTrue(fac.called)


class TestHostLicenseBehaviourForTampa(TestHostLicenseBehaviourForCreedence):

    def _getHost(self):
        return xenrt.lib.xenserver.host.TampaHost(None, None)


class TestHostLicenseBehaviourForClearwater(TestHostLicenseBehaviourForCreedence):

    def _getHost(self):
        return xenrt.lib.xenserver.host.ClearwaterHost(None, None)


class TestUniquePatchParsing(XenRTUnitTestCase):

    @patch("xenrt.TEC")
    def testSamePatchMultipleTimes(self, tec):

        host = xenrt.lib.xenserver.host.DundeeHost(None, None)
        patchList = ["/usr/RTM-77323/XS62ESP1/XS62ESP1.xsupdate",
                     "/usr/RTM-77323/XS62ESP1/XS62ESP1.xsupdate"]
        self.assertEquals(["/usr/RTM-77323/XS62ESP1/XS62ESP1.xsupdate"], host.getUniquePatches(patchList))

    @patch("xenrt.TEC")
    def testSamePatchDifferentBuildsFails(self, tec):
        host = xenrt.lib.xenserver.host.DundeeHost(None, None)
        patchList = ["/usr/RTM-77323/XS62ESP1/XS62ESP1.xsupdate",
                     "/usr/RTM-77324/XS62ESP1/XS62ESP1.xsupdate"]
        self.assertXRTFailure(host.getUniquePatches, patchList)

    @patch("xenrt.TEC")
    def testMultiplePatchesMultipleTimes(self, tec):
        host = xenrt.lib.xenserver.host.DundeeHost(None, None)
        patchList = ["/usr/RTM-77323/XS62ESP1/XS62ESP1.xsupdate",
                     "/usr/RTM-77323/XS62ESP1/XS62ESP2.xsupdate",
                     "/usr/RTM-77324/XS62ESP1/XS62ESP3.xsupdate",
                     "/usr/RTM-77323/XS62ESP1/XS62ESP1.xsupdate"]

        expected = ["/usr/RTM-77323/XS62ESP1/XS62ESP1.xsupdate",
                    "/usr/RTM-77323/XS62ESP1/XS62ESP2.xsupdate",
                    "/usr/RTM-77324/XS62ESP1/XS62ESP3.xsupdate"]
        self.assertEquals(expected, host.getUniquePatches(patchList))
