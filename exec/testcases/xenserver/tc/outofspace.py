import os
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
        ] + echoplugin.to_xapi_args(echoRequest.serialize())

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


class PluginTest(xenrt.TestCase):
    def getHostUnderTest(self):
        return self.getHost('RESOURCE_HOST_0')

    def callEchoPlugin(self, request):
        echoPlugin = EchoPlugin()
        return self.getHostUnderTest().execdom0(
            'xe host-call-plugin host-uuid=$(xe host-list --minimal) '
            + echoPlugin.cmdLineToCallEchoFunction(request)
            + ' || true'
        )

    def run(self, arglist=None):
        domZerosFilesystem = DomZeroFilesystem(self.getHostUnderTest())

        echoPlugin = EchoPlugin()
        echoPlugin.installTo(domZerosFilesystem)

        self.assertNormalPluginCallWorks()
        self.assertStdErrCaptured()
        self.assertStdOutCaptured()
        self.assertFileWritten()

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
        sayHelloOnError = echoplugin.EchoRequest(data='HELLO', exitCode=1)
        result = self.callEchoPlugin(sayHelloOnError)

        self.assertNonZeroStatus(result)

        self.assertIn('stderr: HELLO', result)

    def assertStdOutCaptured(self):
        sayHelloOnOut = echoplugin.EchoRequest(data='HELLO', exitCode=1)
        result = self.callEchoPlugin(sayHelloOnOut)

        self.assertNonZeroStatus(result)

        self.assertIn('stdout: HELLO', result)

    def assertFileWritten(self):
        sayHelloToFile = echoplugin.EchoRequest(data='HELLO',
                                                path='/var/log/echo')
        result = self.callEchoPlugin(sayHelloToFile)

        self.assertDomZeroPathContents('/var/log/echo', 'HELLO')

    def assertDomZeroPathContents(self, path, expectedContents):
        domZerosFilesystem = DomZeroFilesystem(self.getHostUnderTest())

        actualContents = domZerosFilesystem.getContents(path)

        if actualContents != expectedContents:
            raise xenrt.XRTFailure('File contents do not match')

    def assertIn(self, expectedFragment, actualData):
        if expectedFragment not in actualData:
            raise xenrt.XRTFailure(
                '%s was not found in %s' % (expectedFragment, actualData))


class SnapshotTest(xenrt.TestCase):
    def run(self, arglist=None):
        host = self.getHost('RESOURCE_HOST_0')

        if not self.logDriveIsUsed(host):
            self.configureLogDrive(host)
            self.reboot(host, 'g1')

        self.fillDomZeroFileSystem(host)
        self.snapshot(host, 'g1')
        self.unfillDomZeroFileSystem(host)
        snapshotAfterSpaceFreedUp = self.snapshot(host, 'g1')

        if not snapshotAfterSpaceFreedUp.succeeded:
            raise xenrt.XRTFailure(
                'Snapshot failed even after freeing up some space')

    def snapshot(self, host, guestName):
        result = host.execdom0(
            'xe vm-snapshot vm=%s new-name-label=out-of-space-test' %
            guestName,
            retval='code')

        return SnapshotResult(succeeded=result == 0)

    def reboot(self, host, guestName):
        guest = host.getGuest(guestName)
        if guest.getState() == 'UP':
            guest.shutdown()
        host.reboot()
        guest.start()

    def logDriveIsUsed(self, host):
        return host.execdom0('mount | grep -q logdrive', retval='code') == 0

    def fillDomZeroFileSystem(self, host):
        host.execdom0('dd if=/dev/zero of=/fillup', retval='code')

    def unfillDomZeroFileSystem(self, host):
        host.execdom0('rm -f /fillup', retval='code')

    def createLogDriveSetupScript(self, host, setupScriptPath):
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

        self.setContents(host, setupScriptPath, script)

    def setContents(self, host, path, script):
        domZerosFilesystem = DomZeroFilesystem(host)
        domZerosFilesystem.setContents(path, script)

    def configureLogDrive(self, host):
        setupScriptPath = '/root/logdrive_setup.sh'
        self.createLogDriveSetupScript(host, setupScriptPath)

        host.execdom0('bash ' + setupScriptPath)
