import xenrt

class TCMelioSmoke(xenrt.TestCase):
    """Very basic smoke test of MelioFS on XenServer"""
    def run(self, arglist):
        host = self.getHost("RESOURCE_HOST_0")
        iscsiHost = self.getHost("RESOURCE_HOST_1")

        melioHelper = xenrt.lib.xenserver.MelioHelper([host], iscsiHost=iscsiHost)
        melioHelper.setup()
        melioHelper.mount("/mnt")
        host.execdom0("echo 'Testing' > /mnt/testing")
        if host.execdom0("cat /mnt/testing").strip() != "Testing":
            raise xenrt.XRTFailure("File read did not match write")

class TCSparseWrite(xenrt.TestCase):
    """Test writing a 1GB sparse file. Repeat to check for stability"""
    def run(self, arglist):
        host = self.getHost("RESOURCE_HOST_0")
        host.melioHelper.checkMount("/mnt")
        for i in range(20):
            xenrt.sleep(30)
            host.execdom0("python %s/remote/sparsewrite.py /mnt 1000" % xenrt.TEC().lookup("REMOTE_SCRIPTDIR"))

class TCDDIntegrity(xenrt.TestCase):
    def run(self, arglist):
        host = self.getHost("RESOURCE_HOST_0")
        host.melioHelper.checkMount("/mnt")
        for i in range(20):
            host.execdom0("rm -f /mnt/testdd*")
            host.execdom0("dd if=/dev/urandom of=/mnt/testdd1 oflag=direct count=100 bs=1M")
            host.execdom0("dd if=/mnt/testdd1 of=/mnt/testdd2 iflag=direct oflag=direct bs=1M")
            md5sum1 = host.execdom0("md5sum /mnt/testdd1 | awk '{print $1}'").strip()
            md5sum2 = host.execdom0("md5sum /mnt/testdd2 | awk '{print $1}'").strip()
            if md5sum1 != md5sum2:
                raise xenrt.XRTFailure("md5sums did not match")
