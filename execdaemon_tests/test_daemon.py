import unittest
import time
import os

from guest_launcher import nose_plugin
from xenrt_loader.loader import get_xenrt_root
import xenrt_workarounds
from test_remote_call import WindowsOSTestCase


class TestWithCoverage(WindowsOSTestCase):
    def test_execute_new_remote_daemon_with_coverage(self):
        windows_agent = self.getWindowsOS()
        execdaemon_under_test = os.path.join(
            get_xenrt_root(), 'scripts', 'utils', 'execdaemon.py')

        with open(execdaemon_under_test, 'rb') as execdaemon_file:
            execdaemon_contents = execdaemon_file.read()

        execdaemon_contents = execdaemon_contents.replace('8936', '8937')

        windows_agent.execCmd(r'easy_install coverage')

        windows_agent.execCmd('netsh firewall set opmode mode=disable')
        windows_agent.createFile(
            r'c:\execdaemon_under_test.py', execdaemon_contents)
        windows_agent.startCmd(r'coverage run C:\execdaemon_under_test.py')

        time.sleep(2)

        import xmlrpclib

        proxy = xmlrpclib.ServerProxy("http://{ipaddr}:8937/".format(
            ipaddr=windows_agent.parent.getIP()))

        proxy.version()
        proxy.isAlive()
        proxy.stopDaemon("data")
        proxy.version()

        windows_agent.execCmd('coverage html')
        windows_agent._xmlrpc().createTarball(r'c:\covreport.tgz', r'htmlcov')
        windows_agent.getFile(r'c:\covreport.tgz', 'covreport.tgz')
