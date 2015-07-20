import xenrt

class TCCloudstackSetup(xenrt.TestCase):
    def run(self, arglist):
        self.args = self.parseArgsKeyValue(arglist)
        if self.args.get("guest"):
            place = self.getGuest(self.args['guest'])
        else:
            place = self.getHost(self.args['host'])

        place.execcmd("ls")
