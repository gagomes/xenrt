import unittest
import mock
import textwrap

from testing import XenRTUnitTestCase
from xenrt import ixiachariot
from xenrt import objects


def makeMockWindowsGuest(revision, architecture='x86'):
    guest = mock.Mock()
    guest.xmlrpcTempDir.return_value = 'tempdir0'
    guest.getIP.return_value = 'IP address of guest'
    guest.xmlrpcWindowsVersion.return_value = revision
    guest.xmlrpcGetArch.return_value = architecture
    return guest


def makeVista32():
    return makeMockWindowsGuest('6.0')


def makeXP32():
    return makeMockWindowsGuest('5.1')


def makeVista64():
    return makeMockWindowsGuest('6.0', 'amd64')


class TestWindowsEndpoint(XenRTUnitTestCase):
    def testInstallExtractsTarball(self):
        """
        When installing endpoint Then tarball is extracted
        """
        guest = makeVista32()
        endpoint = ixiachariot.WindowsEndpoint(guest, 'base_directory')

        endpoint.install('distmaster_dir')

        guest.xmlrpcUnpackTarball.assert_called_once_with(
            'base_directory/distmaster_dir.tgz', 'tempdir0')

    def testInstallStartsInstaller(self):
        """
        Given 32 bit Vista guest
        When installing endpoint
        Then pevista32_730.exe is executed
        """
        guest = makeVista32()
        endpoint = ixiachariot.WindowsEndpoint(guest, 'base_directory')

        endpoint.install('distmaster_dir')

        guest.xmlrpcExec.assert_called_once_with(
            r'tempdir0\distmaster_dir\pevista32_730.exe /S /v/qn'
        )

    def testIpAddress(self):
        """
        When IP address is asked Then returns the result of guest.getIP
        """
        guest = makeVista32()
        endpoint = ixiachariot.WindowsEndpoint(guest, 'base_directory')

        result = endpoint.ipAddress

        self.assertEquals('IP address of guest', result)

    def testInstallerForPreVista32(self):
        """
        Given 32 bit WindowsXP When installing endpoint
        Then pevista32_730.exe is executed
        """
        guest = makeXP32()
        endpoint = ixiachariot.WindowsEndpoint(guest, 'base_directory')

        self.assertEquals('pewindows32_730.exe', endpoint.installer)

    def testInstallerForVista64(self):
        """
        Given 64 bit Vista guest When installing endpoint
        Then pevista64_730.exe is executed
        """
        guest = makeVista64()
        endpoint = ixiachariot.WindowsEndpoint(guest, 'base_directory')

        self.assertEquals('pevista64_730.exe', endpoint.installer)


class TestPairTest(XenRTUnitTestCase):
    def testGetCommands(self):
        """
        Given TestPair When asked for the commands
        Then appropriate commands returned
        """
        pairTest = ixiachariot.PairTest('ip1', 'ip2', 'testname', 'jobid')

        self.assertEquals([
            'mkdir /cygdrive/c/tests/jobid',
            'echo "1 ip1 ip2" > /cygdrive/c/tests/jobid/clone',
            '"/cygdrive/c/Program Files/Ixia/IxChariot/clonetst" '
            + r'"C:\\tests\\testname" '
            + r'"C:\\tests\\jobid\\clone" '
            + r'"C:\\tests\\jobid\\test.tst"',
            '"/cygdrive/c/Program Files/Ixia/IxChariot/runtst" '
            + r'"C:\\tests\\jobid\\test.tst" '
            + r'"C:\\tests\\jobid\\result.tst"',
            '"/cygdrive/c/Program Files/Ixia/IxChariot/fmttst" '
            + r'"C:\\tests\\jobid\\result.tst" '
            + r'-v "C:\\tests\\jobid\\result.csv"',
        ],
            pairTest.getCommands())


class FakeHostRegistry(object):
    def getHost(self, hostName):
        fakeHost = mock.Mock()
        fakeHost.getGuest.side_effect = (
            lambda guestName: guestName + '@' + hostName
        )
        return fakeHost


class TestEndpointFactory(XenRTUnitTestCase):
    def testCreateSetsGuest(self):
        """
        When client creates an endpoint
        Then endpoint created with proper parameters
        """
        fakeHostRegistry = FakeHostRegistry()
        endpoint = ixiachariot.createEndpoint(
            'host/guest', 'distmasterBase', fakeHostRegistry)

        self.assertEquals('guest@host', endpoint.guest)
