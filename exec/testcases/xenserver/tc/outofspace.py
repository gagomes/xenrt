import xenrt
import textwrap
from collections import namedtuple
from testcases.xenserver.tc import echoplugin


SnapshotResult = namedtuple('SnapshotResult', ['succeeded'])


class EchoPlugin(object):
    def installTo(self, filesystem):
        targetPath = '/etc/xapi.d/plugins/%s' % echoplugin.ECHO_PLUGIN_NAME

        filesystem.setContents(targetPath, echoplugin.getSource())
        filesystem.makePathExecutable(targetPath)

    def cmdLineToCallEchoFunction(self, echoRequest):
        args = [
            'plugin=%s' % echoplugin.ECHO_PLUGIN_NAME,
            'fn=%s' % echoplugin.ECHO_FN_NAME
        ] + echoplugin.toXapiArgs(echoRequest.serialize())

        return ' '.join(args)


class DomZeroFilesystem(object):
    def __init__(self, host):
        self.host = host

    def setContents(self, path, data):
        sftpClient = self.host.sftpClient()

        remoteFile = sftpClient.client.file(path, 'w')
        remoteFile.write(data)
        remoteFile.close()

        sftpClient.close()

    def getContents(self, path):
        sftpClient = self.host.sftpClient()

        remoteFile = sftpClient.client.file(path, 'r')
        contents = remoteFile.read()
        remoteFile.close()

        sftpClient.close()

        return contents

    def makePathExecutable(self, path):
        self.host.execdom0('chmod +x %s' % path)


class PluginTester(object):
    def __init__(self, host):
        self.host = host

    def callEchoPlugin(self, request):
        echoPlugin = EchoPlugin()
        return self.host.execdom0(
            'xe host-call-plugin host-uuid=$(xe host-list --minimal) '
            + echoPlugin.cmdLineToCallEchoFunction(request)
            + ' || true'
        )

    def assertNormalPluginCallWorks(self):
        sayHelloThere = echoplugin.EchoRequest(data='HELLO THERE')
        result = self.callEchoPlugin(sayHelloThere)

        self.assertEquals('HELLO THERE', result.strip())

    def assertEquals(self, expectedValue, actualValue):
        if expectedValue != actualValue:
            raise xenrt.XRTFailure(
                '%s != %s' % (repr(expectedValue), repr(actualValue)))

    def assertNonZeroStatus(self, response):
        if 'status: non-zero exit' not in response:
            raise xenrt.XRTFailure('Non Zero status not reported')

    def assertStdErrCaptured(self):
        sayHelloOnError = echoplugin.EchoRequest(
            data='HELLO', stderr=True, exitCode=1)
        result = self.callEchoPlugin(sayHelloOnError)

        self.assertNonZeroStatus(result)

        self.assertIn('stderr: HELLO', result)

    def assertStdOutCaptured(self):
        sayHelloOnOut = echoplugin.EchoRequest(
            data='HELLO', stdout=True, exitCode=1)
        result = self.callEchoPlugin(sayHelloOnOut)

        self.assertNonZeroStatus(result)

        self.assertIn('stdout: HELLO', result)

    def assertFileWritten(self):
        sayHelloToFile = echoplugin.EchoRequest(data='HELLO',
                                                path='/var/log/echo')
        result = self.callEchoPlugin(sayHelloToFile)

        self.assertDomZeroPathContents('/var/log/echo', 'HELLO')

    def assertDomZeroPathContents(self, path, expectedContents):
        domZerosFilesystem = DomZeroFilesystem(self.host)

        actualContents = domZerosFilesystem.getContents(path)

        if actualContents != expectedContents:
            raise xenrt.XRTFailure('File contents do not match')

    def assertIn(self, expectedFragment, actualData):
        if expectedFragment not in actualData:
            raise xenrt.XRTFailure(
                '%s was not found in %s' % (expectedFragment, actualData))


class PluginTest(xenrt.TestCase):
    def run(self, arglist=None):
        host = self.getHost('RESOURCE_HOST_0')
        domZerosFilesystem = DomZeroFilesystem(host)

        echoPlugin = EchoPlugin()
        echoPlugin.installTo(domZerosFilesystem)

        pluginTester = PluginTester(host)

        pluginTester.assertNormalPluginCallWorks()
        pluginTester.assertStdErrCaptured()
        pluginTester.assertStdOutCaptured()
        pluginTester.assertFileWritten()


class PluginTestWithoutSpace(xenrt.TestCase):
    def run(self, arglist=None):
        host = self.getHost('RESOURCE_HOST_0')
        domZerosFilesystem = DomZeroFilesystem(host)

        echoPlugin = EchoPlugin()
        echoPlugin.installTo(domZerosFilesystem)

        filesystemFiller = DomZeroFilesystemFiller(host)

        if not filesystemFiller.logDriveIsUsed():
            filesystemFiller.configureLogDrive()
            host.reboot()

        filesystemFiller.fillFileSystem()

        pluginTester = PluginTester(host)

        pluginTester.assertNormalPluginCallWorks()
        pluginTester.assertStdErrCaptured()
        pluginTester.assertStdOutCaptured()
        pluginTester.assertFileWritten()


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

        FIRST_FREE_LOPPBACK_DEVICE=$(losetup -f)
        losetup "$FIRST_FREE_LOPPBACK_DEVICE" /logdrive

        mkfs.ext3 -q "$FIRST_FREE_LOPPBACK_DEVICE"

        losetup -d "$FIRST_FREE_LOPPBACK_DEVICE"

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
            rebootGuestAndHost(guest)

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


def rebootGuestAndHost(guest):
    host = guest.getHost()
    if guest.getState() == 'UP':
        guest.shutdown()
    host.reboot()
    guest.start()
