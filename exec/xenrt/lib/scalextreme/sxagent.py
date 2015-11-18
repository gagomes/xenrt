import xenrt
from xenrt.ssh import SSH
from xenrt.lib.scalextreme.sxapi import SXAPI

__all__ = [ "SXAgent" ]

class SXAgent(object):
    """ A object that represent SX gateway"""
    AGENT_VM_ID = "root"
    AGENT_VM_PWD = "xenroot"

    def __init__(self):
        super(SXAgent, self).__init__()

        self.__agentVM = None
        self.__apikey = xenrt.TEC().lookup("SXA_APIKEY", None)
        self.__credential = xenrt.TEC().lookup("SXA_CREDENTIAL", None)
        self.__nodeid = None
        self.__api = None

    def __getAgentURL(self):
        """Get the URL to download agent using Rest API"""
        info = self.apiHandler.execute(category="download", command="info")
        if not "data" in info or not "deb64" in info["data"]:
            raise xenrt.XRTError("Cannot retrieve download URL.")

        url = info["data"]["deb64"].replace("\\", "")
        return url

    def __executeOnAgent(self, command):
        """Execute a command on agent Linux VM via SSH"""
        if not self.__agentVM:
            raise xenrt.XRTError("Agent VM is not assigned.")

        return SSH(self.agentIP, command, timeout=120, password=self.AGENT_VM_PWD)

    @property
    def agentVM(self):
        """The Guest object of agent VM"""
        return self.__agentVM

    @agentVM.setter
    def agentVM(self, vm):
        self.__agentVM = vm

    @property
    def apiKey(self):
        """API Key that is passed from sequene file."""
        return self.__apikey

    @apiKey.setter
    def apiKey(self, key):
        self.__apikey = key

    @property
    def credential(self):
        """Client credential for authenticate."""
        return self.__credential

    @credential.setter
    def credential(self, cred):
        self.__credential = cred

    @property
    def nodeId(self):
        """Node ID. -Read only-"""
        return self.__nodeid

    @property
    def apiHandler(self):
        """Rest API handler. -Read only-"""
        if not self.__api:
           self.__api = SXAPI(self.apiKey, self.credential)
        return self.__api

    @property
    def agentIP(self):
        """The IP of agent VM. -Read only-"""
        if not self.__agentVM:
            raise xenrt.XRTError("Agent VM is not assigned.")
        return self.__agentVM.getIP()

    def installAgent(self):
        """Install agent on vm"""
        if not self.__agentVM:
            raise xenrt.XRTError("Agent VM is not assigned.")

        self.__agentVM.setState("UP")

        url = self.__getAgentURL()
        try:
            self.__executeOnAgent("wget %s -O agent.deb" % url)
            self.__executeOnAgent("dpkg -i agent.deb")
        except:
            # SSH command failure can be ignored.
            # installation will be verified in code below.
            pass

        # Try and find the nodeid (this may take some time)
        starttime = xenrt.util.timenow()
        nodeid = None
        while nodeid is None:
            if (xenrt.util.timenow() - starttime) > 600:
                raise xenrt.XRTError("Cannot find connector in node API after 10 minutes")
            xenrt.sleep(30)
            nodes = []
            offset = 0
            while True:
                newnodes = self.apiHandler.execute(category="nodes", params={'offset':offset, 'status': 'online'})
                nodes.extend(newnodes)                
                if len(newnodes) < 100:
                    # We get max 100 per request, so if we got less than 100 we know we've now run out of nodes
                    break
                offset += 100
                xenrt.sleep(5) # This is to avoid spamming SX with requests
            for node in nodes:
                for attr in node["nodeAttrList"]:
                    if attr["attributeName"] == "ip" and attr["attributeValue"] == self.agentIP:
                        nodeid = node["nodeId"]
                        break
                else:
                    continue
                break

        self.__nodeid = nodeid

    def setAsGateway(self):
        """Set this agent VM as gateway to XenServer"""

        if self.nodeId == None:
            raise xenrt.XRTError("Node Id is not set. Is agent installed properly?")

        r = self.apiHandler.execute(method="PUT", category="nodes", sid=str(self.nodeId), command="setasgateway")

        if "result" in r and r["result"] == "SUCCESS":
            return True

        return False

    def createEnvironment(self, host=None, addToRegistry=True):
        """Create environment with existing agent and XenServer"""

        if self.nodeId == None:
            raise xenrt.XRTError("Node Id is not set. Is agent installed properly?")

        if not host:
            host = self.agentVM.host

        name = xenrt.TEC().lookup("SX_ENVIRONMENT_NAME", "xenrt-%s" % xenrt.TEC().lookup("JOBID", "nojob"))

        p = self.apiHandler.execute(method="POST", category="providers",
            params = {"name": name,
                "providercode": "xenserver",
                "server": "http://" + host.getIP(),
                "username": "root",
                "password": "xenroot",
                "agentId": str(self.nodeId)
            }
        )

        if addToRegistry:
            xenrt.TEC().registry.sxProviderPut(name, p)

