import xenrt, xenrt.lib.xenserver
import sys

class TCHelloWorld(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCHelloWorld")

    def prepare(self, arglist = None):

        self.host = self.getDefaultHost()
        assert None != self.host

        # Copy the unit tests tar to dom0.
        smtests = xenrt.TEC().getFile('xe-phase-1/storage-manager-tests.tar', \
                'storage-manager-tests.tar')
        assert None != smtests
        sftp = self.host.sftpClient()
        assert None != sftp
        sftp.copyTo(smtests, '/tmp/storage-manager-tests.tar')
        sftp.close()
        self.host.execdom0('tar -xf /tmp/storage-manager-tests.tar -C /tmp')

#        self.guest = self.host.createGenericLinuxGuest()
#        assert None != self.guest
#        self.uninstallOnCleanup(self.guest)

    def run(self, arglist = None):
        self.host.execdom0('python /tmp/tests/lvhd_test/rununittests.py')
        # If we reach here then the testcase has passed
