import requests
import re
import os.path
import xenrt

__all__ = [ "SXUIAPI" ]

class SXUIAPI(object):
    BASE_URL = "https://manage.citrix.com"
    SSO_URL = "https://utilityservices.citrix.com"

    def __init__(self, username, password, company=None):
        self.session = None
        self.username = username
        self.password = password

    def login(self):
        self.session = requests.Session()
        r = self.session.get("%s/sso/saml/login" % self.BASE_URL, verify=False)
        saml = re.search("name=\"SAMLRequest\"\s+value=\"(.*?)\"", r.text).group(1)
        r = self.session.post("%s/Utility/STS/saml20/post-binding" % self.SSO_URL, data={"SAMLRequest": saml})
        r.text
        r.status_code
        r = self.session.post("%s/Utility/STS/Sign-In" % self.SSO_URL, params={"ReturnUrl": "/Utility/STS/saml20/post-binding-response"}, data={"userName": self.username, "password": self.password}, verify=False)
        r.text
        r.status_code
        saml = re.search("name=\"SAMLResponse\" value=\"(.*?)\"", r.text).group(1)
        r = self.session.post("%s/sso/saml/SSO/alias/defaultAlias" % self.BASE_URL, data={"SAMLResponse": saml, "RelayState": "%s/" % self.BASE_URL})
        r.text
        r.status_code
        r = self.session.post("%s/acl/authvalidate" % self.BASE_URL, verify=False)
        if r.json()['result'] != "SUCCESS":
            raise xenrt.XRTFailure("Failed to login to CLM")
        self.sx_csrf = r.headers['sx_csrf']
        self.userid = r.json()['data']['userID']
        self.username = r.json()['data']['name']
        company = xenrt.TEC().lookup("SX_COMPANY", None)
        if not company:
            company = self.post("/acl/usercompanies")['data'][0]['companyId']
        self.post("/acl/setcompany", data={"companyId": company})
        role = xenrt.TEC().lookup("SX_ROLE", None)
        if not role:
            role = self.post("/acl/userroles", data={"companyId":  company, "user": self.username})['data'][0]
        self.post("/acl/setrole", data={"role": role})

    def post(self, path, params={}, data={}):
        r = self.session.post("%s/%s" % (self.BASE_URL, path.lstrip("/")), params=params, data=data, headers={"sx_csrf": self.sx_csrf})
        r.raise_for_status()
        if r.json()['result'] != "SUCCESS":
            raise xenrt.XRTFailure("Result was %s" % r.json())
        return r.json()
    
    def getProviderForJob(self):
        return [x for x in self.post("/acl/getcloudproviders")['data']['data'] if x['name'] == "xenrt-%d" % xenrt.GEC().jobid()][0]

