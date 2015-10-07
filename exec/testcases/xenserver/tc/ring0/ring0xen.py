import xenrt, xenrt.lib.xenserver
from xenrt.lazylog import log, step

class XenTestRun(object):
    def __init__(self, host, name):
        self.host = host
        self.name = name

class TCRing0XenBase(xenrt.TestCase):
    def prepare(self, arglist):
        self.host = self.getDefaultHost()

        #install the xen-test-framework which is a prerequisite for runnigng tests.
        module_path = "/tmp/xen-test-framework.rpm"
        module_rpm = xenrt.TEC().getFile("binary-packages/RPMS/domain0/RPMS/x86_64/xen-test-framework-*.rpm")
        try:
            xenrt.checkFileExists(module_rpm)
        except:
            raise xenrt.XRTError("xen-test-framework rpm file is not present in the build \n")

        sh = self.host.sftpClient()
        try:
            sh.copyTo(module_rpm, module_path)
        finally:
            sh.close()

        self.host.execdom0("rpm --force -Uvh %s" % (module_path))

class TCRing0XenDummyTest(xenrt.TestCase):
    def run(self, arglist):
        step("Dummy Test")
