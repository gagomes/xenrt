import requests
import re
import os.path
import xenrt

__all__ = [ "SXUIAPI" ]

class SXUIAPI(object):
    BASE_URL = "https://manage.citrix.com"
    SSO_URL = "https://utilityservices.citrix.com"

    def __init__(self, username, password, company=None, role=None):
        self.session = None
        self.username = username
        self.password = password
        self.company = company
        self.role = role

    def login(self):
        self.session = requests.Session()
        
        xenrt.TEC().logverbose("Signing on with SSO")
        r = self.session.get("%s/sso/saml/login" % self.BASE_URL, verify=False)
        saml = re.search("name=\"SAMLRequest\"\s+value=\"(.*?)\"", r.text).group(1)
        self.session.post("%s/Utility/STS/saml20/post-binding" % self.SSO_URL, data={"SAMLRequest": saml})
        r = self.session.post("%s/Utility/STS/Sign-In" % self.SSO_URL, params={"ReturnUrl": "/Utility/STS/saml20/post-binding-response"}, data={"userName": self.username, "password": self.password}, verify=False)
        saml = re.search("name=\"SAMLResponse\" value=\"(.*?)\"", r.text).group(1)
        self.session.post("%s/sso/saml/SSO/alias/defaultAlias" % self.BASE_URL, data={"SAMLResponse": saml, "RelayState": "%s/" % self.BASE_URL})

        xenrt.TEC().logverbose("Checking authenitcation was successful")
        r = self.session.post("%s/acl/authvalidate" % self.BASE_URL, verify=False)
        if r.json()['result'] != "SUCCESS":
            raise xenrt.XRTFailure("Failed to login to CLM")
        self.sx_csrf = r.headers['sx_csrf']
        self.userid = r.json()['data']['userID']
        self.username = r.json()['data']['name']
        
        xenrt.TEC().logverbose("Setting company")
        if not self.company:
            self.company = self.post("/acl/usercompanies")['data'][-1]['companyId']
        self.post("/acl/setcompany", data={"companyId": self.company})
        
        xenrt.TEC().logverbose("Setting role")
        if not self.role:
            self.role = self.post("/acl/userroles", data={"companyId":  self.company, "user": self.username})['data'][0]
        self.post("/acl/setrole", data={"role": self.role})

    def post(self, path, params={}, data={}):
        xenrt.TEC().logverbose("Posting to %s" % path)
        r = self.session.post("%s/%s" % (self.BASE_URL, path.lstrip("/")), params=params, data=data, headers={"sx_csrf": self.sx_csrf})
        r.raise_for_status()
        if r.json()['result'] != "SUCCESS":
            raise xenrt.XRTFailure("Result was %s" % r.json())
        return r.json()
    
    def getProviderForJob(self):
        return [x for x in self.post("/acl/getcloudproviders")['data']['data'] if x['name'] == "xenrt-%d" % xenrt.GEC().jobid()][0]

