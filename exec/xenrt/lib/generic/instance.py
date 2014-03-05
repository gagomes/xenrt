import xenrt

class Instance(object):

    def __init__(self, toolstack, name, distro, vcpus, memory, vifs=None, rootdisk=None, extraConfig={}):
        self.toolstack = toolstack
        self.name = name
        self.distro = distro
        self.vcpus = vcpus
        self.memory = memory
        self.extraConfig = extraConfig
        self.mainip = None

        # TODO: This should be pattern matching etc rather than a simple if
        self.os = xenrt.lib.opsys.OSFactory(self.distro, self)

        self.rootdisk = rootdisk or self.os.defaultRootdisk
        self.vifs = vifs or [("%s0" % (self.os.vifStem), None, xenrt.randomMAC(), None)]

    def poll(self, state, timeout=600, level=xenrt.RC_FAIL, pollperiod=15):
        """Poll for reaching the specified state"""
        deadline = xenrt.timenow() + timeout
        while 1:
            status = self.toolstack.getState(self)
            if state == status:
                return
            if xenrt.timenow() > deadline:
                xenrt.XRT("Timed out waiting for VM %s to be %s" %
                          (self.name, state), level)
            xenrt.sleep(15, log=False)

    def getIP(self, timeout=600, level=xenrt.RC_ERROR):
        if self.mainip:
            return self.mainip
        return self.toolstack.getIP(self, timeout, level)
        
    def start(self, on=None, timeout=600):
        self.toolstack.startInstance(self, on)
        self.os.waitForBoot(timeout)

__all__ = ["Instance"]
