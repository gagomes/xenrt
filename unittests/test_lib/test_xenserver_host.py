from testing import XenRTUnitTestCase
from mock import Mock, patch, PropertyMock
import xenrt


class TestCoresPerSocket(XenRTUnitTestCase):
    def setUp(self):
        self.__guest = Mock(spec=xenrt.GenericGuest)
        self.__setVCPUs = Mock()
        self.__sockets = Mock()
        self.__guest.setVCPUs = self.__setVCPUs
        self.__guest.setCoresPerSocket = self.__sockets
        self.__win = PropertyMock(return_value=True)
        type(self.__guest).windows = self.__win

    def __setMocksOnHost(self, host):
        host.getCPUCores = Mock(return_value=8)
        host.getNoOfSockets = Mock(return_value=2)
        return host

    @patch("random.choice")
    def testTampaDoesNotGetRandomCores(self, rand):
        """Tampa hosts don't get random called when setting sockets"""
        host = xenrt.lib.xenserver.host.TampaHost(None, None)
        host.setRandomCoresPerSocket(self.__guest, 23)
        self.assertFalse(rand.called)

    @patch("random.choice")
    @patch("xenrt.GEC")
    @patch("xenrt.TEC")
    def testClearWaterGetsRandomCores(self, tec, gec, rand):
        """Clearwater hosts do get random called when setting sockets"""
        host = self.__setMocksOnHost(xenrt.lib.xenserver.host.ClearwaterHost(None, None))
        tec.return_value.lookup = Mock(return_value = 0)
        host.setRandomCoresPerSocket(self.__guest, 23)
        self.assertTrue(rand.called)

    @patch("xenrt.GEC")
    @patch("xenrt.TEC")
    def testClearwaterGetsSocketsSet(self, tec, gec):
        """For a CLR host the number of sockets should be set"""
        host = self.__setMocksOnHost(xenrt.lib.xenserver.host.ClearwaterHost(None, None))
        tec.return_value.lookup = Mock(return_value = 0)
        host.setRandomCoresPerSocket(self.__guest, 23)
        self.assertTrue(self.__sockets.called)

    @patch("xenrt.GEC")
    @patch("xenrt.TEC")
    def testClearwaterGetsSocketsSetWithDbValueSet(self, tec, gec):
        """For a CLR host the number of sockets should be set if the
        cores per socket value has been pulled from the database"""
        host = self.__setMocksOnHost(xenrt.lib.xenserver.host.ClearwaterHost(None, None))
        tec.return_value.lookup = Mock(return_value = 4)
        host.setRandomCoresPerSocket(self.__guest, 23)
        self.assertTrue(self.__sockets.called)

    @patch("xenrt.GEC")
    @patch("xenrt.TEC")
    def testTampaDoesntGetSocketsSet(self, tec, gec):
        """For TAM hosts expect the number of sockets not to be set"""
        host = self.__setMocksOnHost(xenrt.lib.xenserver.host.TampaHost(None, None))
        tec.return_value.lookup = Mock(return_value = 0)
        host.setRandomCoresPerSocket(self.__guest, 23)
        self.assertFalse(self.__sockets.called)

    def testClearwaterPVGuestDoesNotGetSocketsSet(self):
        """For a CLR host given a PV guest expect the number of sockets not to be set"""
        host = self.__setMocksOnHost(xenrt.lib.xenserver.host.ClearwaterHost(None, None))
        self.__win.return_value = False
        self.assertFalse(self.__guest.windows)
        host.setRandomCoresPerSocket(self.__guest, 23)
        self.assertFalse(self.__sockets.called)


class TestCheckRpmInstalled(XenRTUnitTestCase):

    def setUp(self):
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
