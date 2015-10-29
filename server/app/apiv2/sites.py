from app.apiv2 import *
from app.apiv2.machines import _MachineBase
from pyramid.httpexceptions import *
import app.utils
import json
import jsonschema

class _SiteBase(_MachineBase):
    def getSites(self,
                 flags=[],
                 sites=[],
                 exceptionIfEmpty=False):

        conditions = []
        params = []

        if sites:
            conditions.append(self.generateInCondition("s.site", sites))
            params.extend(sites)
        
        query = "SELECT s.site, s.status, s.flags, s.descr, s.ctrladdr, s.maxjobs, s.sharedresources, s.location FROM tblsites s"
        if conditions:
            query += " WHERE %s" % (" AND ".join(conditions))
        
        cur = self.getDB().cursor()
        try:
            cur.execute(query, self.expandVariables(params))

            ret = {}

            while True:
                rc = cur.fetchone()
                if not rc:
                    break
                
                site = {
                    "name": rc[0].strip(),
                    "status": rc[1].strip(),
                    "flags": [],
                    "description": rc[3].strip() if rc[3] else None,
                    "ctrladdr": rc[4].strip() if rc[4] else None,
                    "maxjobs": rc[5],
                    "sharedresources": {},
                    "location": rc[7].strip() if rc[7] else None
                }

                if rc[6]:
                    for i in rc[6].strip().split("/"):
                        if "=" not in rc[6]:
                            continue
                        (key, value) = i.split("=", 1)
                        try:
                            num = int(value)
                        except:
                            continue

                        site['sharedresources'][key] = num

                if rc[2] and rc[2].strip():
                    site['flags'] = rc[2].strip().split(",")
                
                ret[site['name']] = site
        finally:
            cur.close()
       
        for s in ret.keys():
            if flags:
                if not app.utils.check_attributes(",".join(ret[s]['flags']), ",".join(flags)):
                    del ret[s]
                    continue

        if exceptionIfEmpty and not ret:
            raise XenRTAPIError(self, HTTPNotFound, "Site not found")

        return ret

class ListSites(_SiteBase):
    PATH = "/sites"
    REQTYPE = "GET"
    SUMMARY = "Get sites matching parameters"
    PARAMS = [
         {'collectionFormat': 'multi',
          'description': 'Get a specific site - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'site',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Filter on a flag - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'flag',
          'required': False,
          'type': 'array'}]
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["sites"]

    def render(self):
        return self.getSites(sites = self.getMultiParam("site"),
                             flags = self.getMultiParam("flag"))

class GetSite(_SiteBase):
    PATH = "/site/{name}"
    REQTYPE = "GET"
    SUMMARY = "Gets a specific site object"
    TAGS = ["sites"]
    PARAMS = [
        {'name': 'name',
         'in': 'path',
         'required': True,
         'description': 'Site to fetch',
         'type': 'string'}]
    RESPONSES = { "200": {"description": "Successful response"}}

    def render(self):
        site = self.request.matchdict['name']
        sites = self.getSites(sites=[site], exceptionIfEmpty=True)
        return sites[site]

class UpdateSite(_SiteBase):
    PATH = "/site/{name}"
    WRITE = True
    REQTYPE = "POST"
    SUMMARY = "Update a site"
    TAGS = ["sites"]
    PARAMS = [
        {'name': 'name',
         'in': 'path',
         'required': True,
         'description': 'Site to update',
         'type': 'integer'},
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the site update',
         'schema': { "$ref": "#/definitions/updatesite" }
        }
    ]
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "update_site"
    PARAM_ORDER=["name", "description", "ctrladdr", "maxjobs", "flags", "addflags", "delflags", "sharedresources", "status", "location"]
    DEFINITIONS = {"updatesite": {
        "title": "Update Site",
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Description of the site"
            },
            "ctrladdr": {
                "type": "string",
                "description": "IP address of the site controller"
            },
            "maxjobs": {
                "type": "integer",
                "description": "Maximum concurrent jobs on this site"
            },
            "flags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Flags for this site"
            },
            "addflags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Flags to add to this site"
            },
            "delflags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Flags to remove from this site"
            },
            "sharedresources": {
                "type": "object",
                "description": "Key-value pair resource:value of resources to update. (set value to null to remove a resource)"
            },
            "status": {
                "type": "string",
                "description": "Status of the site"
            },
            "location": {
                "type": "string",
                "description": "Location of the site (human readable)"
            }
        }
    }}

    def updateSite(self, site, data, commit=True):
        sitedata = self.getSites(sites=[site], exceptionIfEmpty=True)[site]
        u = []
        if data.get("status"):
            u.append(("status", data['status']))
        if data.get("description"):
            u.append(("descr", data['description']))
        if data.get("ctrladdr"):
            u.append(("ctrladdr", data['ctrladdr']))
        if data.get("maxjobs"):
            u.append(("maxjobs", data['maxjobs']))
        if data.get("sharedresources"):
            res = sitedata['sharedresources']
            for r in data['sharedresources'].keys():
                if data['sharedresources'][r] == None and r in res:
                    del res[r]
                elif data['sharedresources'][r] != None:
                    res[r] = str(data['sharedresources'][r])
            u.append(("sharedresources", "/".join(["%s=%s" % (x,y) for (x,y) in res.items()])))
        if data.get("addflags"):
            data['flags'] = sitedata['flags']
            for f in data['addflags']:
                if f not in data['flags']:
                    data['flags'].append(f)
        if data.get("delflags"):
            if not "flags" in data:
                data['flags'] = sitedata['flags']
            for f in data['delflags']:
                if f in data['flags']:
                    data['flags'].remove(f)
        if data.get("flags"):
            u.append(("flags", ",".join(data['flags'])))
        if data.get("location"):
            u.append(("location", data['location']))

        if len(u) == 0:
            return
        sqlset = []
        vals = []
        for field, val in u:
            sqlset.append("%s = %%s" % field)
            vals.append(val)
        vals.append(site)
        sql = "UPDATE tblSites SET %s WHERE site = %%s" % (",".join(sqlset))

        cur = self.getDB().cursor()
        try:
            cur.execute(sql, vals)
        finally:
            cur.close()

        if commit:
            self.getDB().commit()

    def render(self):
        try:
            j = json.loads(self.request.body)
            jsonschema.validate(j, self.DEFINITIONS['updatesite'])
        except Exception, e:
            raise XenRTAPIError(self, HTTPBadRequest, str(e).split("\n")[0])

        self.updateSite(self.request.matchdict['name'], j)
        return {}


class NewSite(UpdateSite):
    PATH = "/sites"
    REQTYPE = "POST"
    SUMMARY = "Create a new site"
    TAGS = ["sites"]
    PARAMS = [
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the site',
         'schema': { "$ref": "#/definitions/newsite" }
        }
    ]
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "new_site"
    PARAM_ORDER=["name", "description", "ctrladdr", "maxjobs", "flags", "sharedresources", "location"]
    DEFINITIONS = {"newsite": {
        "title": "New Site",
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the site"
            },
            "description": {
                "type": "string",
                "description": "Description of the site"
            },
            "ctrladdr": {
                "type": "string",
                "description": "IP address of the site controller"
            },
            "maxjobs": {
                "type": "integer",
                "description": "Maximum concurrent jobs on this site"
            },
            "flags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Flags for this site"
            },
            "sharedresources": {
                "type": "object",
                "description": "Key-value pair resource:value of resources to update. (set value to null to remove a resource)"
            },
            "location": {
                "type": "string",
                "description": "Location of the site (human readable)"
            }
        },
        "required": ["name"]
    }}

    def createSite(self, data, commit=True):
        cur = self.getDB().cursor()
        name = data['name']
        try:
            cur.execute("INSERT into tblSites (site, status) VALUES (%s, 'active')", [name])
        finally:
            cur.close()

        self.addMachine("_%s" % name, name, "NOHOST", None, {}, "Pseudohost for %s" % name, commit=False)

        self.updateSite(name, data, commit=False)

        if commit:
            self.getDB().commit()
            
    
    def render(self):
        try:
            j = json.loads(self.request.body)
            jsonschema.validate(j, self.DEFINITIONS['newsite'])
        except Exception, e:
            raise XenRTAPIError(self, HTTPBadRequest, str(e).split("\n")[0])

        self.createSite(j)
        return {}

class RemoveSite(_SiteBase):
    PATH = "/site/{name}"
    REQTYPE = "DELETE"
    SUMMARY = "Removes a site"
    TAGS = ["sites"]
    PARAMS = [
        {'name': 'name',
         'in': 'path',
         'required': True,
         'description': 'Machine to remove',
         'type': 'string'}]
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "remove_site"
    WRITE=True

    def removeSite(self, site, commit=True):
        db = self.getDB()
        cur = db.cursor()
        try:
            self.removeMachine("_%s" % site, commit=False)
            cur.execute("DELETE FROM tblsites WHERE site=%s", [site])
            if commit:
                db.commit()
        finally:
            cur.close()


    def render(self):
        site = self.request.matchdict['name']
        self.getSites(sites=[site], exceptionIfEmpty=True)
        self.removeSite(site)
        return {}

RegisterAPI(ListSites)
RegisterAPI(GetSite)
RegisterAPI(NewSite)
RegisterAPI(UpdateSite)
RegisterAPI(RemoveSite)
