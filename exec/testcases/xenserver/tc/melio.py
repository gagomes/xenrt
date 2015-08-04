import xenrt

class TC27207(xenrt.TestCase):
    def run(self, arglist):
        h = self.getDefaultHost()
        h.installMelio()
        h.melio.setup()
        h.melio.mount("/mnt")
        h.execdom0("echo 'Testing' > /mnt/testing")
        if h.execdom0("cat /mnt/testing").strip() != "Testing":
            raise xenrt.XRTFailure("File read did not match write")
