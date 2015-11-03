from testing import XenRTUnitTestCase, interfaceMock
from xenrt.lib.opsys.linux import LinuxOS
from mock import Mock
import xenrt


class LinuxIsHealthy(XenRTUnitTestCase):
    def setUp(self):
        parent = interfaceMock(xenrt.interfaces.OSParent)
        parent._osParent_getPowerState = lambda: xenrt.PowerState.up
        self.__linux = LinuxOS(None, parent)
        self.__ssh = Mock()
        self.__linux.waitForSSH = Mock()
        self.__linux.execSSH = self.__ssh

    def testDiskCommandIsCalledViaSsh(self):
        """Given a call to assertHealthy, then exepct a ssh call
        containing a dd command"""
        self.__linux.assertHealthy()
        arg = self.__ssh.call_args
        self.assertTrue(arg.startswith("dd "))

    def testDiskCommandIsCalledTwice(self):
        """Given a call to assertHealthy, then exepct a ssh call
        containing a dd command twice, once for read and once for write"""
        self.__linux.assertHealthy()
        count = self.__ssh.call_count
        self.assertEqual(2, count)

    def testDiskCommandIsCalledWithDirectFlag(self):
        """Given a call to assertHealthy, then exepct a ssh call
        containing a dd command with a direct flag"""
        self.__linux.assertHealthy()
        arg = self.__ssh.call_args
        self.assertTrue("direct" in str(arg))

    def testSshExceptionPropgates(self):
        """Given the ssh command raises an exception, when assertHealthy
        is called, then expect that error to be propagated"""
        self.__ssh.side_effect = xenrt.XRTError("Kaboom")
        self.assertRaises(xenrt.XRTError, self.__linux.assertHealthy)
