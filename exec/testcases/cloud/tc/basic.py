import xenrt

class TCGuestDeploy(xenrt.TestCase):
    def run(self, arglist = []):
        cloud = self.getDefaultToolstack()
        cloud.createInstance(distro="debian70_x86-64", name="debian")

        # MarvinApi is cloud.marvin
