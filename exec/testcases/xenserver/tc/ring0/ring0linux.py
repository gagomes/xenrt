import xenrt, xenrt.lib.xenserver
from xenrt.lazylog import log, step

import yaml

@xenrt.irregularName
class xst(object):
    def __init__(self, host, name):
        self.host = host
        self.name = name

        self.host.execdom0("modprobe xst_%s" % (self.name))
        self.host.execdom0("test %s" % (self.path("run")))

    def path(self, f):
        return "/sys/kernel/debug/xst/%s/%s" % (self.name, f)

    def setParams(self, params):
        for p in params:
            self.host.execdom0("echo %d > %s" % (p[1], self.path(p[0])))

    def results(self):
        res = self.host.execdom0("cat %s" % (self.path("results")))
        return yaml.load(res)

    def run(self):
        # Want to get the results even if the test fails
        self.host.execdom0("echo 1 > %s" % (self.path("run")),
                           level=xenrt.RC_OK)

        results = self.results()
        self.check(results, "pass")
        return results

    def check(self, results, status):
        if results["status"] != status:
            raise xenrt.XRTFailure("Test %s in state %s (expected %s)"
                                   % (self.name, results["status"], status))

class TCRing0LinuxBase(xenrt.TestCase):
    def prepare(self, arglist):
        self.host = self.getDefaultHost()

        # Install test modules from build output
        step("Install test-ring0-modules RPM")

        modules_path = "/tmp/test-ring0-modules.rpm"
        modules_rpm = xenrt.TEC().getFile("binary-packages/RPMS/domain0/RPMS/x86_64/test-ring0-modules-*.rpm")
        try:
            xenrt.checkFileExists(modules_rpm)
        except:
            raise xenrt.XRTError("test-ring0-modules rpm file is not present in the build")

        sh = self.host.sftpClient()
        try:
            sh.copyTo(modules_rpm, modules_path)
        finally:
            sh.close()

        self.host.execdom0("rpm --force -Uvh %s" % (modules_path))

class TCRing0LinuxMemoryType(TCRing0LinuxBase):
    def run(self, arglist):
        step("Run set_memory_uc")
        set_memory_uc = xst(self.host, "set_memory_uc")
        set_memory_uc.run()

class TCRing0LinuxAllocBalloon(TCRing0LinuxBase):
    def run(self, arglist):
        step("Run alloc_balloon")
        t = xst(self.host, "alloc_balloon")
        t.setParams([("pages", 1024)])
        t.run()
