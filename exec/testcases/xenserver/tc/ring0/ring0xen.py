import xenrt, xenrt.lib.xenserver
from xenrt.lazylog import log, step

class XenTestRun(object):
    def __init__(self, host, name):
        self.host = host
        self.name = name

    def results(self):
        res = self.host.execdom0("grep -i 'Test Result:' /var/log/xen/guest-%s.log | tail -1 | awk -F: '{print $4}'" % self.name).strip()

#        xenrt.TEC().comment('Test %s Result: %s' % self.name, res)
        if res == "SUCCESS":
            xenrt.TEC().logverbose('Test %s Result: PASS' % self.name)
            return 0
        else:
            raise xenrt.XRTFailure('Test %s Result: FAILED' % self.name)
            return -1

    def run(self):
        self.host.execdom0("xl create /opt/xen-test-framework/%s.cfg" % self.name)
        ret = self.results()
        return ret

class TCRing0XenBase(xenrt.TestCase):
    def prepare(self, arglist):
        self.host = self.getDefaultHost()

        #install the xen-test-framework which is a prerequisite for running tests.
        step("install xen-test-framework RPM and copy other pre-requisites")
        module_path = "/tmp/xen-test-framework.rpm"
        module_rpm = xenrt.TEC().getFile("/usr/groups/build/trunk-ring0/latest/binary-packages/RPMS/domain0/RPMS/x86_64/xen-test-framework-*.rpm")

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
        self.host.execdom0("xenconsoled --log=all")

class TCRing0XenPV32Test(TCRing0XenBase):
    def run(self, arglist):
        step("32bit PV test")
        xen_pv32_test = XenTestRun(self.host, "test-pv32-example");
        xen_pv32_test.run()

class TCRing0XenPV64Test(TCRing0XenBase):
    def run(self, arglist):
        step("64bit PV Test")
        xen_pv64_test = XenTestRun(self.host, "test-pv64-example");
        xen_pv64_test.run()

class TCRing0XenHVM32Test(TCRing0XenBase):
    def run(self, arglist):
        step("32bit HVM test")
        xen_hvm32_test = XenTestRun(self.host, "test-hvm32-example");
        xen_hvm32_test.run()

class TCRing0XenHVM64Test(TCRing0XenBase):
    def run(self, arglist):
        step("64bit HVM test")
        xen_hvm64_test = XenTestRun(self.host, "test-hvm-64-example");
        xen_hvm64_test.run()
