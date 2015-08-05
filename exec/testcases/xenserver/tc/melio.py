import xenrt

class TC27207(xenrt.TestCase):
    """Very basic smoke test of MelioFS on XenServer"""
    def run(self, arglist):
        h = self.getDefaultHost()
        h.installMelio()
        h.melioHelper.setup()
        h.melioHelper.mount("/mnt")
        h.execdom0("echo 'Testing' > /mnt/testing")
        if h.execdom0("cat /mnt/testing").strip() != "Testing":
            raise xenrt.XRTFailure("File read did not match write")
