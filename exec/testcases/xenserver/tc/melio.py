import xenrt

class TCMelioSetup(xenrt.TestCase):
    def setupMelio(self, sharedISCSI=True):
        allHosts = []
        i = 0
        while True:
            h = self.getHost("RESOURCE_HOST_%d" % i)
            if not h:
                break
            allHosts.append(h)
            i+=1
        if sharedISCSI:
            melioHelper = xenrt.lib.xenserver.MelioHelper(allHosts[0:-1], iscsiHost=allHosts[-1])
        else:
            melioHelper = xenrt.lib.xenserver.MelioHelper(allHosts)
        melioHelper.setup()
        return melioHelper
    
    def run(self, arglist):
        self.setupMelio(sharedISCSI=True)

class TCMelioSmoke(TCMelioSetup):
    """Very basic smoke test of MelioFS on XenServer"""
    def run(self, arglist):
        melioHelper = self.setupMelio(sharedISCSI=True)
        melioHelper.mount("/mnt")
        h1 = self.getHost("RESOURCE_HOST_0")
        h2 = h1.melioHelper.hosts[-1]

        h1.execdom0("echo 'Testing' > /mnt/testing")
        if h2.execdom0("cat /mnt/testing").strip() != "Testing":
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
        h1 = self.getHost("RESOURCE_HOST_0")
        h2 = h1.melioHelper.hosts[-1]
        h1.melioHelper.checkMount("/mnt")
        for i in range(20):
            h1.execdom0("rm -f /mnt/testdd*")
            h1.execdom0("dd if=/dev/urandom of=/mnt/testdd1 oflag=direct count=100 bs=1M")
            h2.execdom0("dd if=/mnt/testdd1 of=/mnt/testdd2 iflag=direct oflag=direct bs=1M")
            md5sum1 = h2.execdom0("md5sum /mnt/testdd1 | awk '{print $1}'").strip()
            md5sum2 = h1.execdom0("md5sum /mnt/testdd2 | awk '{print $1}'").strip()
            if md5sum1 != md5sum2:
                raise xenrt.XRTFailure("md5sums did not match")

class TCMelioSRSetup(TCMelioSetup):
    """Setup Melio SR"""
    def run(self, arglist):
        if not xenrt.TEC().lookup("FFS_RPM", None):
            raise xenrt.XRTError("FFS_RPM not specified")

        melioHelper = self.setupMelio(sharedISCSI=True)

        melioHelper.createSR(name="Melio")

class TCMelioVM(xenrt.TestCase):
    """Create VM on melio SR"""
    def run(self, arglist):
        (distro, arch) = xenrt.getDistroAndArch(self.tcsku)
        host = self.getHost("RESOURCE_HOST_0")
        g = host.createBasicGuest(distro=distro, arch=arch, sr="Melio") 
        g.uninstall()
