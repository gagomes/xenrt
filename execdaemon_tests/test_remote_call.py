import unittest

from guest_launcher import nose_plugin
import xenrt_workarounds


class WindowsOSTestCase(unittest.TestCase):
    def getWindowsOS(self):
        guest_starter = nose_plugin.guest_starter
        ip_address = guest_starter.start()
        windows_os = xenrt_workarounds.createWindowsOS(ip_address)
        windows_os.waitForBoot(20)
        return windows_os


class TestWindowsOS(WindowsOSTestCase):
    def test_execCmd_only_command_output_returned_as_data(self):
        windows_os = self.getWindowsOS()

        windows_os.execCmd(r'echo HELLO > c:\somefile')
        contents = windows_os.execCmd(r'type c:\somefile', returndata=True)

        self.assertEquals('HELLO', contents)

    def test_execCmd_command_output_is_found_in_returned_data(self):
        windows_os = self.getWindowsOS()

        windows_os.execCmd(r'echo HELLO > c:\somefile')
        contents = windows_os.execCmd(r'type c:\somefile', returndata=True)

        self.assertIn('HELLO', contents)
