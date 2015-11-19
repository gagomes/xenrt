# XenRT imports
import xenrt
from xenrt.lib.scalextreme import SXProcess

class XDPoc(xenrt.TestCase):

    def run(self, arglist):

        # Find the Windows template
        template = self.getGuest("Windows Server 2012 R2")
        host = template.getHost()
        sxp = SXProcess.getByName("XenApp and XenDesktop Proof of Concept (25)", templateDeploymentProfile="xenrt-template")

        provider = xenrt.TEC().registry.sxProviderGetDefault()

        sxp.deploy(provider['id'], host, template.getUUID(), template.password)

        # TODO: Check the correct VMs etc have been deployed
