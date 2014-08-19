import xenrt

class TCGuestDeploy(xenrt.TestCase):
    def run(self, arglist = []):

        DISTRO = "debian70_x86-64"
        GUEST_NAME = "debian70"

        for arg in arglist:
            if arg.startswith('distro'):
                DISTRO = arg.split('=')[1].strip()
                GUEST_NAME = DISTRO.replace("_","-") # cloudstack does not like underscore.
    
        cloud = self.getDefaultToolstack()
        instance = cloud.createInstance(distro=DISTRO, name=GUEST_NAME )

        # MarvinApi is cloud.marvin

class TCCreateTemplate(xenrt.TestCase):
    def run(self, arglist):
        args = self.parseArgsKeyValue(arglist)

        cloud = self.getDefaultToolstack()
        cloud.createOSTemplate(args['distro'], hypervisorType=args.get("hypervisor"))
