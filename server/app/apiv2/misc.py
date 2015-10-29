from app.apiv2 import *
from pyramid.httpexceptions import *
import app.user
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
        return {"user": u.userid, "email": u.email, "team": u.team, "admin": u.admin, "groups": u.groups, "default_pools": ["VMX" , "SVM"], "default_flags": []}

class GetUserDetails(XenRTAPIv2Page):
    PATH = "/userdetails/{user}"
    REQTYPE = "GET"
    SUMMARY = "Get details for a XenRT user"
    PARAMS = [
        {'name': 'user',
         'in': 'path',
         'required': True,
         'description': 'User to fetch',
         'type': 'string'}]
    RESPONSES = {"200": {"description": "Successful response"}}
    TAGS = ["misc"]

    def render(self):
        u = app.user.User(self, self.matchdict('user'))
        if not u.valid:
            raise XenRTAPIError(self, HTTPNotFound, "User not found")
        return {"user": u.userid, "email": u.email, "team": u.team, "admin": u.admin, "groups": u.groups}

class GetUsersDetails(XenRTAPIv2Page):
    PATH = "/usersdetails"
    REQTYPE = "GET"
    SUMMARY = "Get details for multiple XenRT users"
    PARAMS = [
        {'name': 'user',
         'in': 'query',
         'required': True,
         'description': 'User to fetch',
         'type': 'array',
         'items': {'type': 'string'}}]
    RESPONSES = {"200": {"description": "Successful response"}}
    TAGS = ["misc"]

    def render(self):
        ret = {}
        for user in self.getMultiParam("user"):
            u = app.user.User(self, user)
            if u.valid:
                ret[u.userid] = {"user": u.userid, "email": u.email, "team": u.team, "admin": u.admin, "groups": u.groups}
        return ret

class EmailList(XenRTAPIv2Page):
    def cli(self):
        cur = self.getDB().cursor()
        cur.execute("SELECT DISTINCT(email) FROM tblusers WHERE email IS NOT NULL AND NOT disabled;")
        print "; ".join([x[0] for x in cur.fetchall()])

class GetGroupDetails(XenRTAPIv2Page):
    PATH = "/groupdetails/{group}"
    REQTYPE = "GET"
    SUMMARY = "Get details for a XenRT group"
    PARAMS = [
        {'name': 'group',
         'in': 'path',
         'required': True,
         'description': 'Group to fetch',
         'type': 'string'}]
    RESPONSES = {"200": {"description": "Successful response"}}
    TAGS = ["misc"]

    def render(self):
        cur = self.getDB().cursor()
        cur.execute("SELECT gu.userid FROM tblgroupusers gu INNER JOIN tblgroups g ON gu.groupid = g.groupid WHERE g.name=%s", [self.matchdict('group')])
        users = []
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            users.append(rc[0].strip())
        return {"group": self.matchdict('group'), "users": users}

class GetGroupsDetails(XenRTAPIv2Page):
    PATH = "/groupsdetails"
    REQTYPE = "GET"
    SUMMARY = "Get details for multiple XenRT group"
    PARAMS = [
        {'name': 'group',
         'in': 'query',
         'required': True,
         'description': 'Group to fetch',
         'type': 'array',
         'items': {'type': 'string'}}]
    RESPONSES = {"200": {"description": "Successful response"}}
    TAGS = ["misc"]

    def render(self):
        ret = {}
        for group in self.getMultiParam("group"):
            cur = self.getDB().cursor()
            cur.execute("SELECT gu.userid FROM tblgroupusers gu INNER JOIN tblgroups g ON gu.groupid = g.groupid WHERE g.name=%s", [group])
            users = []
            while True:
                rc = cur.fetchone()
                if not rc:
                    break
                users.append(rc[0].strip())
            ret[group] = {"group": group, "users": users}
        return ret

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
            raise XenRTAPIError(self, HTTPBadRequest, "You must specify a search string")
        attributes = self.getMultiParam("attributes")
        if len(attributes) == 0:
            attributes = ["objectClass","cn","mail","sAMAccountName"]

        results = ad.search(search, attributes)

        return results

RegisterAPI(LogServer)
RegisterAPI(GetUser)
RegisterAPI(ADLookup)
RegisterAPI(GetUserDetails)
RegisterAPI(GetUsersDetails)
RegisterAPI(GetGroupDetails)
RegisterAPI(GetGroupsDetails)
