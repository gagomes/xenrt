from xenrt.lib.opsys import LinuxOS, registerOS

__all__=["XSDom0"]

class XSDom0(LinuxOS):
    def __init__(self, distro, parent):
        super(XSDom0, self).__init__(distro, parent)
    
    @staticmethod
    def knownDistro(distro):
        return distro == "XSDom0"

    @staticmethod
    def testInit(parent):
        return XSDom0("XSDom0", parent)

    def preCloneTailor(self):
        pass

    def waitForBoot(self, timeout):
        # We consider boot of XenServer complete once it responds to SSH
        startTime = xenrt.util.timenow()
        self.parent.getIP(trafficType="SSH", timeout=timeout)
        # Reduce the timeout by however long it took to get the IP
        timeout -= (xenrt.util.timenow() - startTime)
        # Now wait for an SSH response in the remaining time
        self.waitForSSH(timeout)

registerOS(XSDom0)
