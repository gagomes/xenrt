# XenRT imports
import xenrt
from xenrt.lib.scalextreme import SXAgent


class ScaleXtremePoC(xenrt.TestCase):
    """A prototype of ScaleXtreme PoC running code."""

    def __init__(self):
        xenrt.TestCase.__init__(self)

    def prepare(self, arglist=[]):
        self.agent = SXAgent()
        for arg in arglist:
            key, value = arg.split("=")
            if key.strip() == "apikey":
                self.agent.apiKey = value.strip()
            elif key.strip() == "credential":
                self.agent.credential = value.strip()

        self.agent.agentVM = self.getGuest("SX_Agent")

    def run(self, arglist=[]):
        self.agent.installAgent()
        self.agent.setAsGateway()
        self.agent.createEnvironment(self.getDefaultHost())

