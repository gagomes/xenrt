from testing import XenRTUnitTestCase
from mock import Mock
import xenrt


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
