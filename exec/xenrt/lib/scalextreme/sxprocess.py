import xenrt
import json
from xenrt.lib.scalextreme.sxapi import SXAPI

__all__ = ["SXProcess"]

class SXProcess(object):
    """An object to represent a Scalextreme Blueprint"""

    def __init__(self, processId, processVersion, templateDeploymentProfileId=None):
        super(SXProcess, self).__init__()

        self.__processId = processId
        self.__processVersion = processVersion
        self.__templateDeploymentProfileId = templateDeploymentProfileId
        self.__apikey = xenrt.TEC().lookup("SXA_APIKEY", None)
        self.__credential = xenrt.TEC().lookup("SXA_CREDENTIAL", None)
        self.__api = None

    @staticmethod
    def getByName(name, version=None, templateDeploymentProfile=None):
        """Creates an SXProcess object for the named blueprint"""
        # First instantiate an 'empty' object which we can fill in
        p = SXProcess(None, version)
        api = p.apiHandler
        blueprints = api.execute(category="process", method="GET", params={"type":"purchased"})
        matchedBlueprints = filter(lambda b: b['processName'] == name, blueprints)
        if len(matchedBlueprints) != 1:
            raise xenrt.XRTError("Found %d matching blueprints (expected 1)" % len(matchedBlueprints))
        b = matchedBlueprints[0]
        p.__processId = b['processId']
        if not version:
            # Find the latest version
            versions = api.execute(category="process", sid=p.processId, command="versions", method="GET")
            p.__processVersion = str(max(map(lambda v: int(v['version']), versions)))
        if templateDeploymentProfile:
            # Find the id of this profile
            profiles = api.execute(category="deploymentprofile", command="list", method="POST", params={"processId": p.processId, "processVersion": p.processVersion})
            matchedProfiles = filter(lambda dp: dp['deploymentProfileName'] == templateDeploymentProfile, profiles)
            if len(matchedProfiles) != 1:
                raise xenrt.XRTError("Found %d matching deployment profiles (expected 1)" % len(matchedProfiles))
            p.__templateDeploymentProfileId = matchedProfiles[0]['deploymentProfileId']

        return p

    @property
    def processId(self):
        return self.__processId

    @property
    def processVersion(self):
        return self.__processVersion

    @property
    def templateDeploymentProfileId(self):
        return self.__templateDeploymentProfileId

    @property
    def apiKey(self):
        """API Key that is passed from sequence file."""
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
    def apiHandler(self):
        """Rest API handler. -Read only-"""
        if not self.__api:
           self.__api = SXAPI(self.apiKey, self.credential)
        return self.__api

    def _mungeDeploymentProfile(self, deploymentProfile, providerId, templateRef, templatePw, homeServerRef, networkRef, srRef):
        """Munge the deploymentProfile to specify our details"""

        profileDetails = deploymentProfile['profileDetails']

        for item in profileDetails:
            if item['attributeName'] == "SERVER_LIST":
                item['attributeValue'] = str(providerId)
    
            if not item['attributeName'].startswith("LAUNCH_SCRIPT_"):
                continue

            v = json.loads(item['attributeValue'])
            props = v['properties']
            for prop in props:
                if prop['propertyKey'] != "config":
                    continue
                propValue = json.loads(prop['propertyValue'])
                if propValue.has_key("provider_id"):
                    propValue['provider_id'] = str(providerId)
                params = propValue['params']
                if params.has_key("home_server"):
                    params['home_server'] = homeServerRef
                if params.has_key("tpl_id"):
                    params['tpl_id'] = templateRef
                if params.has_key("nics"):
                    for n in params['nics']:
                        n['network'] = networkRef
                if params.has_key("disks"):
                    for d in params['disks']:
                        d['sr_ref'] = srRef
                if params.has_key('copy_sr'):
                    params['copy_sr'] = srRef
                if params.has_key('agent'):
                    params['agent']['password'] = templatePw
                propValue['ui'] = """<ul class="sx-col"><li><strong>XenRT Job Id:</strong><span>%s</span></li></ul>""" % xenrt.GEC().jobid()
                prop['propertyValue'] = json.dumps(propValue)
            item['attributeValue'] = json.dumps(v)

        return deploymentProfile

    def deploy(self, providerId, host, template, templatePw, profileName=None):
        """Deploy the blueprint using the specified host and template"""
        # Get the OpaqueRef's we need
        xapi = host.getAPISession().xenapi
        hostRef = xapi.host.get_by_uuid(host.getMyHostUUID())
        templateRef = xapi.VM.get_by_uuid(template)

        # Identify the network and SR the template is using and get their refs
        networkUUID = host.minimalList("vif-list", "network-uuid", "vm-uuid=%s" % template)[0]
        networkRef = xapi.network.get_by_uuid(networkUUID)
        vdiUUID = host.minimalList("vbd-list", "vdi-uuid", "vm-uuid=%s empty=false" % template)[0]
        srUUID = host.genParamGet("vdi", vdiUUID, "sr-uuid")
        srRef = xapi.SR.get_by_uuid(srUUID)

        # Get the template deployment profile (we use the first one for the blueprint if not specified)
        if self.templateDeploymentProfileId is None:
            deploymentProfile = self.apiHandler.execute(category="deploymentprofile", command="list", method="POST", params={"processId": self.processId, "processVersion": self.processVersion})[0]
        else:
            deploymentProfile = self.apiHandler.execute(category="deploymentprofile", sid=str(self.templateDeploymentProfileId))

        # Munge it
        deploymentProfile = self._mungeDeploymentProfile(deploymentProfile, providerId, templateRef, templatePw, hostRef, networkRef, srRef)

        # Save it
        if not profileName:
            profileName = "xenrt-%s-%s" % (xenrt.GEC().jobid(), xenrt.randomSuffix())
        result = self.apiHandler.execute(category="deploymentprofile", method="POST", params={"processIdStr": self.processId, "processVersionStr": self.processVersion, "deploymentProfileName": profileName, "profileDetailsStr": json.dumps(deploymentProfile['profileDetails'])})
        deploymentProfileId = result['deploymentProfileId']
        
        # Trigger the deployment using the profile
        result = self.apiHandler.execute(category="deploymentprofile", sid=deploymentProfileId, command="deploy", method="POST", params={"processId": self.processId, "name": profileName})
        processinstanceId = result['jobdetailid']

        # Wait for the deployment to complete
        statuses = set()
        starttime = xenrt.util.timenow()
        while True:
            statusresult = self.apiHandler.execute(category="processinstance", sid=processinstanceId, command="processrundetails", method="GET")
            # Wait until we have all status as either complete/failed/warning
            statuses = set(map(lambda s: s['status'], statusresult))
            if len(statuses) > 0 and statuses.issubset(set(["complete","failed","warning"])):
                break
            if (xenrt.util.timenow() - starttime) > 18000:
                raise xenrt.XRTFailure("Deployment timed out")
            xenrt.sleep(60)

        if "failed" in statuses:
            raise xenrt.XRTFailure("One or more steps failed in deployment")

        return result
