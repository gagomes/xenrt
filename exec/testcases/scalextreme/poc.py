# XenRT imports
import xenrt
from xenrt.lib.scalextreme import SXProcess

class SXDeployTest(xenrt.TestCase):

    def run(self, arglist):

        # Find the Debian template
        template = self.getGuest("Debian Wheezy 7.0")
        host = template.getHost()
        sxp = SXProcess("57994", "1", "2947")

        # Find our providerId (TODO: we should store this in the registry)
        providerName = "xenrt-%d" % xenrt.GEC().jobid()
        providerId = [x['providerId'] for x in sxp.apiHandler.execute(category="providers") if x['providerName'] == providerName][0]
        
        sxp.deploy(providerId, host, template.getUUID())

