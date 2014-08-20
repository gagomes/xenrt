import xenrt
import textwrap
from collections import namedtuple


SnapshotResult = namedtuple('SnapshotResult', ['succeeded'])


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
        sftpClient = host.sftpClient()

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

        remoteFile = sftpClient.client.file(setupScriptPath, 'w')
        remoteFile.write(script)
        remoteFile.close()

        sftpClient.close()

    def configureLogDrive(self, host):
        setupScriptPath = '/root/logdrive_setup.sh'
        self.createLogDriveSetupScript(host, setupScriptPath)

        host.execdom0('bash ' + setupScriptPath)
