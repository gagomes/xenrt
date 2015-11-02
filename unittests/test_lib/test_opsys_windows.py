from testing import XenRTUnitTestCase
from testing import interfaceMock
from xenrt.lib.opsys import WindowsOS
from mock import Mock
import xenrt
from zope.interface import implements


class FakeRandomStringGenerator(object):
    implements(xenrt.interfaces.StringGenerator)

    def __init__(self, stringValue):
        self.__value = stringValue

    def generate(self):
        return self.__value


class WindowsIsHealthy(XenRTUnitTestCase):

    def setUp(self):
        # Set up a series of method mocks invlved in assertHealthy
        parent = interfaceMock(xenrt.interfaces.OSParent)
        parent._osParent_getPowerState = lambda: xenrt.PowerState.up
        self.__win = WindowsOS(None, parent)
        self.__randomWord = "SomeRandomStringOrOther"
        generator = FakeRandomStringGenerator(self.__randomWord)
        self.__win.randomStringGenerator = generator

        self.__create = Mock()
        self.__win.createFile = self.__create

        self.__read = Mock(return_value=self.__randomWord)
        self.__win.readFile = self.__read

        self.__remove = Mock()
        self.__win.removeFile = self.__remove

    def testAFileIsCreated(self):
        """Given and assertHealth call, then expect a file to be created"""
        self.__win.assertHealthy()
        self.assertTrue(self.__create.called)

    def testAFileIsReread(self):
        """Given and assertHealth call, then expect a file to be reread"""
        self.__win.assertHealthy()
        filename, word = self.__create.call_args
        self.__read.assert_is_called_with(filename)

    def testAFileIsRemoved(self):
        """Given and assertHealth call, then expect a file to be removed"""
        self.__win.assertHealthy()
        filename, word = self.__create.call_args
        self.__remove.assert_is_called_with(filename)

    def testAnErrorIsRaisedIfRereadNotMatched(self):
        """Given an assertHealthy request, when the reread value doesn't match
        the random string, then expect an error to be raised """
        self.__read.return_value = "AAARRGGGHHH - KABOOM"
        self.assertRaises(xenrt.XRTError, self.__win.assertHealthy)

    def testDefaultRandomGeneratorIsInvoked(self):
        """Given the default random string generator, when the assert healthy
        is called, expect an error to be raised"""
        self.__win.randomStringGenerator = None
        self.__read.return_value = "AAARRGGGHHH - KABOOM"
        self.assertRaises(xenrt.XRTError, self.__win.assertHealthy)
