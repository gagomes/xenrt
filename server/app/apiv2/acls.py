from app.apiv2 import *
from pyramid.httpexceptions import *
import calendar
import app.utils
import json
import time
import jsonschema

class _AclBase(XenRTAPIv2Page):

    _ACLENTRIES = {
        "title": "ACL entry",
        "type": "object",
        "required": ["prio", "type"],
        "properties": {
            "prio": {
                "type": "integer",
                "description": "ACL entry priority"
            },
            "type": {
                "type": "string",
                "description": "user, group or default",
                "enum": ["user", "group", "default"]
            },
            "userid": {
                "type": "string",
                "description": "username or group CN"
            },
            "grouplimit": {
                "type": "integer",
                "description": "Absolute number of machines group can use"
            },
            "grouppercent": {
                "type": "integer",
                "description": "Percentage of machines group can use"
            },
            "userlimit": {
                "type": "integer",
                "description": "Absolute number of machines user can use"
            },
            "userpercent": {
                "type": "integer",
                "description": "Percentage of machines user can use"
            },
            "maxleasehours": {
                "type": "integer",
                "description": "Number of hours machine can be leased by this user/group"
            },
            "preemptableuse": {
                "type": "boolean",
                "description": "Allow entry to run preemptable jobs and do preemptable machine leases"
            }
        }
    }

    def getAcls(self,
                owners=[],
                ids=[],
                names=[],
                limit=None,
                offset=0,
                exceptionIfEmpty=False,
                withCounts = False):
        cur = self.getDB().cursor()
        params = []
        conditions = []

        if ids:
            conditions.append(self.generateInCondition("a.aclid", ids))
            params.extend(ids)

        if owners:
            conditions.append(self.generateInCondition("a.owner", owners))
            params.extend(owners)

        if names:
            conditions.append(self.generateInCondition("a.name", names))
            params.extend(names)

        query = "SELECT a.aclid FROM tblacls a"
        if conditions:
            query += " WHERE %s" % " AND ".join(conditions)

        cur.execute(query, self.expandVariables(params))

        aclids = []

        while True:
            rc = cur.fetchone()
            if not rc:
                break
            aclids.append(rc[0])

        if len(aclids) == 0:
            if exceptionIfEmpty:
                raise XenRTAPIError(self, HTTPNotFound, "ACL not found")

            return {}

        aclHelper = self.getACLHelper()
        ret = dict([[aclid, aclHelper.get_acl(aclid, withCounts=withCounts).toDict()] for aclid in aclids])

        if limit:
            aclsToReturn = sorted(ret.keys())[offset:offset+limit]

            for a in ret.keys():
                if not a in aclsToReturn:
                    del ret[a]

        return ret

    def newAcl(self, name, parent, owner, entries):
        db = self.getDB()
        cur = db.cursor()
        if parent:
            cur.execute("INSERT INTO tblacls (parent, owner, name) VALUES (%s, %s, %s) RETURNING aclid", [parent, owner, name])
        else:
            cur.execute("INSERT INTO tblacls (owner, name) VALUES (%s, %s) RETURNING aclid", [owner, name])
        rc = cur.fetchone()
        aclid = rc[0]

        for e in entries:
            self._insertAclEntry(cur, aclid, e)

        db.commit()
        return self.getAcls(limit=1, ids=[aclid], exceptionIfEmpty=True)

    def _insertAclEntry(self, cur, aclid, entry):
        if entry['type'] == "default":
            entry['userid'] = ""
        elif not self.validateAndCache(entry['type'], entry['userid']):
            raise XenRTAPIError(self, HTTPNotAcceptable, "Could not find %s '%s' in AD" % (entry['type'], entry['userid']))

        fields = ["aclid", "prio", "type", "userid", "preemptableuse"]
        values = [aclid, entry['prio'], entry['type'], entry['userid'], entry.get('preemptableuse', False)]
        for f in ['grouplimit', 'grouppercent', 'userlimit', 'userpercent', 'maxleasehours']:
            if entry.has_key(f) and entry[f] is not None:
                fields.append(f)
                values.append(entry[f])

        cur.execute("INSERT INTO tblaclentries (%s) VALUES (%s)" % (",".join(fields), ",".join(["%s" for i in range(len(values))])), values)

    def updateAcl(self, aclid, name, parent, entries):
        db = self.getDB()
        cur = db.cursor()
        sqlset = {}
        if name:
            sqlset['name'] = name
        if parent:
            sqlset['parent'] = parent
        if sqlset:
            sql = ",".join(map(lambda s: "%s=%%s" % s, sqlset.keys()))
            values = sqlset.values()
            values.append(aclid)
            cur.execute("UPDATE tblacls SET %s WHERE aclid=%%s" % sql, values)

        if entries:
            cur.execute("DELETE FROM tblaclentries WHERE aclid=%s", [aclid])
            for e in entries:
                self._insertAclEntry(cur, aclid, e)

        db.commit()
        return self.getAcls(limit=1, ids=[aclid], exceptionIfEmpty=True)

    def removeAcl(self, aclid):
        # Check the ACL isn't in use anywhere
        db = self.getDB()
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM tblmachines WHERE aclid=%s", [aclid])
        rc = cur.fetchone()
        count = rc[0]
        if count > 0:
            raise XenRTAPIError(self, HTTPPreconditionFailed, "ACL in use by %d machines" % count)
        cur.execute("DELETE FROM tblaclentries WHERE aclid=%s", [aclid])
        cur.execute("DELETE FROM tblacls WHERE aclid=%s", [aclid])
        db.commit()

    def checkAcl(self, aclid, user):
        """Check the ACL exists and is accessible by the given user"""

        db = self.getDB()
        cur = db.cursor()
        cur.execute("SELECT owner FROM tblacls WHERE aclid=%s", [aclid])
        rc = cur.fetchone()
        if not rc:
            raise XenRTAPIError(self, HTTPNotFound, "ACL not found")
        owner = rc[0].strip()
        if owner != user.userid and not user.admin:
            raise XenRTAPIError(self, HTTPForbidden, "You are not the owner of this ACL")

class ListAcls(_AclBase):
    PATH = "/acls"
    REQTYPE = "GET"
    SUMMARY = "Get ACLs matching parameters"
    PARAMS = [
         {'collectionFormat': 'multi',
          'description': 'Filter on ACL owner - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'owner',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Get a specific ACL - can specify multiple',
          'in': 'query',
          'items': {'type': 'integer'},
          'name': 'id',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Get a specific ACL - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'name',
          'required': False,
          'type': 'array'},
         {'description': 'Limit the number of results. Defaults to unlimited',
          'in': 'query',
          'name': 'limit',
          'required': False,
          'default': 10,
          'type': 'integer'},
         {'description': 'Offset to start the results at, for paging with limit enabled.',
          'in': 'query',
          'name': 'offset',
          'required': False,
          'type': 'integer'},
          ]
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["acls"]
   
    def render(self):
        return self.getAcls(owners = self.getMultiParam("owner"),
                            ids = self.getMultiParam("ids"),
                            names = self.getMultiParam("name"),
                            limit=int(self.request.params.get("limit", 0)),
                            offset=int(self.request.params.get("offset", 0)))

class GetAcl(_AclBase):
    PATH = "/acl/{id}"
    REQTYPE = "GET"
    SUMMARY = "Gets a specific ACL"
    TAGS = ["acls"]
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'ACL id to fetch',
         'type': 'integer'},
        {'name': 'counts',
         'in': 'query',
         'required': False,
         'description': 'Include current counts. Defaults to false',
         'type': 'boolean'},
        {'name': 'onlymine',
         'in': 'query',
         'required': False,
         'description': 'Only show ACL entries which affect you. Defaults to false',
         'type': 'boolean'}
    ]
    RESPONSES = { "200": {"description": "Successful response"},
                  "404": {"description": "ACL not found"}}

    def render(self):
        aclid = self.getIntFromMatchdict("id")
        withCounts = self.request.params.get("counts", "false") == "true"
        acls = self.getAcls(limit=1, ids=[aclid], exceptionIfEmpty=True, withCounts=withCounts)
        acl = acls[aclid]
        if self.request.params.get("onlymine", "false") == "true":
            filteredEntry = None
            user = self.getUser().userid
            groups = self.getACLHelper().groups_for_userid(user)
            for e in acl['entries']:
                if e['type'] == "user" and e['userid'] == user:
                    filteredEntry = e
                    break
                elif e['type'] == "group" and e['userid'] in groups:
                    filteredEntry = e
                    break
                elif e['type'] == "default":
                    filteredEntry = e
                    break
            if filteredEntry:
                acl['entries'] = [filteredEntry]
            else:
                acl['entries'] = []
        return acl

class NewAcl(_AclBase):
    WRITE = True
    PATH = "/acls"
    REQTYPE = "POST"
    SUMMARY = "Submits a new ACL"
    TAGS = ["acls"]
    PARAMS = [
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the ACL required',
         'schema': { "$ref": "#/definitions/newacl" }
        }
    ]
    DEFINITIONS = {"newacl": {
        "title": "New ACL",
        "type": "object",
        "required": ["name", "entries"],
        "properties": {
            "name": {
                "type": "string",
                "description": "Name for new ACL"
            },
            "parent": {
                "type": "integer",
                "description": "ID of any parent ACL"
            },
            "entries": {
                "type": "array",
                "items": {
                    "$ref": "#/definitions/aclentries"
                }
            }
        },
        "definitions": {
            "aclentries": _AclBase._ACLENTRIES
        }
    }, "aclentries": _AclBase._ACLENTRIES }
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "new_acl"
    PARAM_ORDER=["name", "entries", "parent"]

    def render(self):
        try:
            j = json.loads(self.request.body)
            jsonschema.validate(j, self.DEFINITIONS['newacl'])
        except Exception, e:
            raise XenRTAPIError(self, HTTPBadRequest, str(e).split("\n")[0])
        return self.newAcl(name=j.get("name"),
                           parent=j.get("parent"),
                           owner=self.getUser().userid,
                           entries=j.get("entries"))

class UpdateAcl(_AclBase):
    WRITE = True
    PATH = "/acl/{id}"
    REQTYPE = "POST"
    SUMMARY = "Update ACL details"
    TAGS = ["acls"]
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'ACL ID to update',
         'type': 'integer'},
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the update',
         'schema': { "$ref": "#/definitions/updateacl" }
        }
    ]
    DEFINITIONS = {"updateacl": {
        "title": "Update ACL",
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of ACL"
            },
            "parent": {
                "type": "integer",
                "description": "ID of any parent ACL"
            },
            "entries": {
                "type": "array",
                "items": {
                    "$ref": "#/definitions/aclentries"
                }
            }
        },
        "definitions": {
            "aclentries": _AclBase._ACLENTRIES
        }
    }, "aclentries": _AclBase._ACLENTRIES }
    RESPONSES = { "200": {"description": "Successful response"},
                  "404": {"description": "ACL not found"},
                  "403": {"description": "No permission to update the specified ACL"}}
    OPERATION_ID = "update_acl"
    PARAM_ORDER=["id", "name", "parent", "entries"]

    def render(self):
        aclid = self.getIntFromMatchdict("id")
        self.checkAcl(aclid, self.getUser())
        try:
            j = json.loads(self.request.body)
            jsonschema.validate(j, self.DEFINITIONS['updateacl'])
        except Exception, e:
            raise XenRTAPIError(self, HTTPBadRequest, str(e).split("\n")[0])
        return self.updateAcl(aclid, name=j.get("name"), parent=j.get("parent"), entries=j.get("entries"))

class RemoveAcl(_AclBase):
    WRITE = True
    PATH = "/acl/{id}"
    REQTYPE = "DELETE"
    SUMMARY = "Removes an ACL"
    TAGS = ["acls"]
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'ACL ID to remove',
         'type': 'integer'}
    ]
    RESPONSES = { "200": {"description": "Successful response"},
                  "404": {"description": "ACL not found"},
                  "412": {"description": "ACL in use by one or more machines"},
                  "403": {"description": "No permission to remove the specified ACL"}}
    OPERATION_ID = "remove_acl"

    def render(self):
        aclid = self.getIntFromMatchdict("id")
        self.checkAcl(aclid, self.getUser())
        self.removeAcl(aclid)
        return {}

RegisterAPI(ListAcls)
RegisterAPI(GetAcl)
RegisterAPI(NewAcl)
RegisterAPI(UpdateAcl)
RegisterAPI(RemoveAcl)
