from app.apiv2 import *
from pyramid.httpexceptions import *
import config

class LogServer(XenRTAPIv2Page):
    PATH = "/logserver"
    REQTYPE = "GET"
    SUMMARY = "Get default log server"
    PARAMS = []
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["backend"]
    RETURN_KEY = "server"

    def render(self):
        return {"server": config.log_server }

class GetUser(XenRTAPIv2Page):
    PATH = "/loggedinuser"
    REQTYPE = "GET"
    SUMMARY = "Get the currently logged in user"
    PARAMS = []
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["misc"]

    def render(self):
        u = self.getUser()
        if not u:
            return {}
        return {"user": u.userid, "email": u.email}

class ADLookup(XenRTAPIv2Page):
    PATH = "/ad"
    REQTYPE = "GET"
    SUMMARY = "Perform an LDAP lookup"
    PARAMS = [
         {'description': 'Username / group name to search for',
          'in': 'query',
          'name': 'search',
          'required': True,
          'type': 'string'},
         {'collectionFormat': 'multi',
          'description': 'Attributes to return. Defaults to objectClass,cn,mail,sAMAccountName',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'attributes',
          'required': False,
          'default': ['objectClass','cn','mail','sAMAccountName'],
          'type': 'array'},
    ]
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["misc"]

    def render(self):
        ad = self.getAD()
        search = self.request.params.get("search")
        if not search:
            raise XenRTAPIError(HTTPBadRequest, "You must specify a search string")
        attributes = self.getMultiParam("attributes")
        if len(attributes) == 0:
            attributes = ["objectClass","cn","mail","sAMAccountName"]

        results = ad.search(search, attributes)

        return results

RegisterAPI(LogServer)
RegisterAPI(GetUser)
RegisterAPI(ADLookup)
