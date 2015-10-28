import xenrt
import requests

__all__ = [ "SXAPI" ]

class SXAPI(object):
    """ScaleXtreme Rest API handler class"""

    def __init__(self, apikey, credential, server=None, version="v0"):
        """Constructor.
        SXAPI always gets authenticated and stores access key.
        """
        self.apikey = apikey
        self.credential = credential
        if server:            
            self.server = server
        else:
            self.server = xenrt.TEC().lookup("SXAPI_SERVER", "https://lifecycle.cloud.com")
        self.version = version
        self.accessToken = None
        self.authenticate()

    def __buildURI(self, category=None, sid=None, command=None):
        """Build Rest API URO with given path."""

        def addifexist(L, var):
            if var:
                L.append(var)

        uri = [self.server, self.version]
        addifexist(uri, category)
        addifexist(uri, sid)
        addifexist(uri, command)

        if len(uri) < 3:
            raise xenrt.XRTError("At least category or command should be given.")
        return "/".join(uri)

    def execute(self, method="GET", category=None, sid=None, command=None, params={}, authFilter=False, tries=3):
        """Make an API request and return list/dict object"""
        method = method.upper()
        if method not in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
            raise xenrt.XRTError("Unknown method: %s" % method)

        # if type(args) is not "dict":
        #     raise xenrt.XRTError("Parameters to REST API should be packed in a dictionary")
        if self.accessToken:
            params["access_token"] = self.accessToken

        uri = self.__buildURI(category, sid, command)

        while tries > 0:
            tries -= 1
            xenrt.TEC().logverbose("Running URI: %s" % uri)
            if authFilter:
                r = requests.request(method, uri, auth=(self.apikey, self.credential), params=params, verify=False)
            else:
                r = requests.request(method, uri, params=params, verify=False)
            xenrt.TEC().logverbose("%d: %s" % (r.status_code, r.text))
            if r.status_code == 200:
                return eval(r.text)
            if r.status_code == 400:
                xenrt.TEC().logverbose(r.text)
                raise xenrt.XRTError("Bad input parameter or error message: %s" % params)
            if r.status_code == 401:
                xenrt.TEC().logverbose(r.text)
                xenrt.TEC().logverbose("Access Token is expired or invalid. Trying again... (%d attempt left)" % tries)
                # If access token was issued already, it can be expired. re-issue new one before retry.
                if self.accessToken:
                    self.accessToken = None
                    self.authenticate()
            if r.status_code == 500:
                xenrt.TEC().logverbose(r.text)
                xenrt.warning("Unknown server error. %d: %s (%d attempt left)" % (r.status_code, r.text, tries))

            xenrt.sleep(5)

        raise xenrt.XRTError("Failed to execute %s uri." % uri)

    def authenticate(self):
        """Get authenticated and store access key"""
        companies = self.execute(command="companies", params={"client_id": self.apikey})
        if len(companies) < 1:
            raise xenrt.XRTError("Expected at least 1 company but received %d" % len(companies))
        self.companyId = companies[-1]["companyId"]

        self.roles = self.execute(command="roles", params={"client_id": self.apikey, "company_id": self.companyId})
        if "Admin" not in self.roles:
            raise xenrt.XRTError("Given apikey does not have Admin permission.")

        token = self.execute(category="oauth", command="token", params={"grant_type": "client_credentials", "scope": "Admin,%d" % self.companyId}, authFilter=True)
        if "access_token" in token:
            self.accessToken = token["access_token"]
        elif "value" in token:
            self.accessToken = token["value"]
        else:
            raise xenrt.XRTError("Respond does not contain token info.")

