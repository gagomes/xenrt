import xenrt
import textwrap
from collections import namedtuple
from xenrt.lib.xenserver import echoplugin
from xenrt.lib import assertions
from xenrt.lib.filesystem import DomZeroFilesystem


SnapshotResult = namedtuple('SnapshotResult', ['succeeded'])


class PluginTester(object):
    def __init__(self, host):
        self.host = host

    def _callEchoPlugin(self, request):
        return self.host.execdom0(
            'xe host-call-plugin host-uuid=$(xe host-list --minimal) '
            + echoplugin.cmdLineToCallEchoFunction(request)
            + ' || true'
        )

    def _assertNormalPluginCallWorks(self):
        sayHelloThere = echoplugin.EchoRequest(data='HELLO THERE')
        result = self._callEchoPlugin(sayHelloThere)

        assertions.assertEquals('HELLO THERE', result.strip())

    def _assertNonZeroStatus(self, response):
        if 'status: non-zero exit' not in response:
            raise xenrt.XRTFailure('Non Zero status not reported')

    def _assertStdErrCaptured(self):
        sayHelloOnError = echoplugin.EchoRequest(
            data='HELLO', stderr=True, exitCode=1)
        result = self._callEchoPlugin(sayHelloOnError)

        self._assertNonZeroStatus(result)

        assertions.assertIn('stderr: HELLO', result)

    def _assertStdOutCaptured(self):
        sayHelloOnOut = echoplugin.EchoRequest(
            data='HELLO', stdout=True, exitCode=1)
        result = self._callEchoPlugin(sayHelloOnOut)

        self._assertNonZeroStatus(result)

        assertions.assertIn('stdout: HELLO', result)

    def _assertFileWritten(self):
        sayHelloToFile = echoplugin.EchoRequest(data='HELLO',
                                                path='/var/log/echo')
        result = self._callEchoPlugin(sayHelloToFile)

        self._assertDomZeroPathContents('/var/log/echo', 'HELLO')

    def _assertDomZeroPathContents(self, path, expectedContents):
        domZerosFilesystem = DomZeroFilesystem(self.host)

        actualContents = domZerosFilesystem.getContents(path)

        if actualContents != expectedContents:
            raise xenrt.XRTFailure('File contents do not match')

    def performTests(self):
        self._assertNormalPluginCallWorks()
        self._assertStdErrCaptured()
        self._assertStdOutCaptured()
        self._assertFileWritten()


class PluginTest(xenrt.TestCase):
    def run(self, arglist=None):
        host = self.getHost('RESOURCE_HOST_0')
        domZerosFilesystem = DomZeroFilesystem(host)

        echoplugin.installTo(domZerosFilesystem)

        pluginTester = PluginTester(host)

        pluginTester.performTests()


class PluginTestWithoutSpace(xenrt.TestCase):
    def run(self, arglist=None):
        host = self.getHost('RESOURCE_HOST_0')
        domZerosFilesystem = DomZeroFilesystem(host)

        echoplugin.installTo(domZerosFilesystem)

        filesystemFiller = DomZeroFilesystemFiller(host)

        if not filesystemFiller.logDriveIsUsed():
            filesystemFiller.configureLogDrive()
            host.reboot()

        filesystemFiller.fillFileSystem()

        pluginTester = PluginTester(host)

        pluginTester.performTests()


class DomZeroFilesystemFiller(object):
    def __init__(self, host):
        self.host = host

    def logDriveIsUsed(self):
        return self.host.execdom0(
            'mount | grep -q logdrive', retval='code') == 0

    def fillFileSystem(self):
        self.host.execdom0('dd if=/dev/zero of=/fillup', retval='code')

    def unfillFileSystem(self):
        self.host.execdom0('rm -f /fillup', retval='code')

    def createLogDriveSetupScript(self, setupScriptPath):
        script = textwrap.dedent("""
        set -eux

        df /dev/sda1
        dd if=/dev/zero of=/logdrive bs=1M count=512
        df /dev/sda1

        FIRST_FREE_LOOPBACK_DEVICE=$(losetup -f)
        losetup "$FIRST_FREE_LOOPBACK_DEVICE" /logdrive

        mkfs.ext3 -q "$FIRST_FREE_LOOPBACK_DEVICE"

        losetup -d "$FIRST_FREE_LOOPBACK_DEVICE"

        sed -ie '/logdrive/d' /etc/fstab
        echo "/logdrive /var/log ext3 loop,rw 0 0" >> /etc/fstab
        """)

        self.setContents(setupScriptPath, script)

    def setContents(self, path, script):
        domZerosFilesystem = DomZeroFilesystem(self.host)
        domZerosFilesystem.setContents(path, script)

    def configureLogDrive(self):
        setupScriptPath = '/root/logdrive_setup.sh'
        self.createLogDriveSetupScript(setupScriptPath)

        self.host.execdom0('bash ' + setupScriptPath)


class SnapshotTest(xenrt.TestCase):
    def run(self, arglist=None):
        host = self.getHost('RESOURCE_HOST_0')
        guest = host.createGenericWindowsGuest(
            distro='win7sp1-x86', name='MONKEY')
        filesystemFiller = DomZeroFilesystemFiller(host)

        if not filesystemFiller.logDriveIsUsed():
            filesystemFiller.configureLogDrive()
            if guest.getState() == 'UP':
                guest.shutdown()
            host.reboot()
            guest.start()

        filesystemFiller.fillFileSystem()
        self.snapshot(guest)
        filesystemFiller.unfillFileSystem()
        snapshotAfterSpaceFreedUp = self.snapshot(guest)

        if not snapshotAfterSpaceFreedUp.succeeded:
            raise xenrt.XRTFailure(
                'Snapshot failed even after freeing up some space')

    def snapshot(self, guest):
        host = guest.getHost()
        result = host.execdom0(
            'xe vm-snapshot vm=MONKEY new-name-label=out-of-space-test',
            retval='code')

        return SnapshotResult(succeeded=result == 0)
