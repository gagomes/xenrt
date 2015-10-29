from app.apiv2 import *
from pyramid.httpexceptions import *
import app.db
import json
import jsonschema

class _ResourceBase(XenRTAPIv2Page):

    def __init__(self, request):
        super(_ResourceBase, self).__init__(request)
        self.mutex = None
        self.mutex_held = False

    def get_lock(self):
        if self.mutex_held:
            self.mutex_held += 1
        else:
            if not self.mutex:
                self.mutex = app.db.dbWriteInstance()
            cur = self.mutex.cursor()
            cur.execute("LOCK TABLE resourcelock")
            self.mutex_held = 1
        
    def release_lock(self, releaseAll=False):
        self.check_mutex_held()
        self.mutex_held = self.mutex_held - 1
        if not self.mutex_held or releaseAll:
            self.mutex.commit()

    def check_mutex_held(self):
        if not self.mutex_held:
            raise Exception("Mutex not held")
        else:
            if not self.mutex:
                raise Exception("Mutex claims to be held, but no DB connection")

    def render(self):
        ret = self.doRender()
        if self.mutex:
            if self.mutex_held:
                self.release_lock(releaseAll=True)
            self.mutex.close()
        return ret

class LockResource(_ResourceBase):
    WRITE = True
    PATH = "/globalresources/lock"
    REQTYPE = "POST"
    SUMMARY = "Locks a global resource"
    TAGS = ["backend"]
    PARAMS = [
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the lock required',
         'schema': {'$ref': "#/definitions/lockresource"}
        }
    ]
    DEFINITIONS = {"lockresource": {
            "title": "Lock Resource",
            "type": "object",
            "properties": {
                "restype": {
                    "type": "string",
                    "description": "Type of lock required"
                },
                "site": {
                    "type": "string",
                    "description": "Site where the lock is required"
                },
                "job": {
                    "type": "integer",
                    "description": "Job ID requesting the lock"
                }
            },
            "required": ["restype", "site", "job"]
        }
    }
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "lock_global_resource"
    PARAM_ORDER = ['restype', 'site', 'job']

    def doRender(self):
        try: 
            params = json.loads(self.request.body)
            jsonschema.validate(params, self.DEFINITIONS['lockresource'])
        except Exception, e:
            raise XenRTAPIError(self, HTTPBadRequest, str(e).split("\n")[0])
        self.get_lock()
        ret = {}
        try: 
            restype = params['restype']
            site = params['site']
            jobid = params['job']

            cur = self.getDB().cursor()
            cur.execute("SELECT name,data,site FROM tblresources WHERE type=%s AND status='idle'", [restype])
            available = []
            while True:
                rc = cur.fetchone()
                if not rc:
                    break
                name = rc[0].strip()
                data = rc[1].strip()

                info = {"name":name, "data":json.loads(data)}

                sites = rc[2]
                if sites:
                    sites = rc[2].strip()
                    if site in sites.split(","):
                        available.append(info)
                else:
                    available.append(info)

            if len(available) > 0:
                cur.execute("UPDATE tblresources SET status='locked',jobid=%s WHERE name=%s", [jobid, available[0]['name']])
                self.getDB().commit()
                ret = available[0]
        finally:
            self.release_lock()
        return ret

class ReleaseResource(_ResourceBase):
    WRITE = True
    PATH = "/globalresources/lock"
    REQTYPE = "DELETE"
    SUMMARY = "Releases a global resource lock"
    TAGS = ["backend"]
    PARAMS = [
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the lock required',
         'schema': {'$ref': "#/definitions/releaseresource"}
        }
    ]
    DEFINITIONS = {"releaseresource": {
            "title": "Release Resource",
            "type": "object",
            "properties": {
                "job": {
                    "type": "integer",
                    "description": "Release the locks on all resources from this job"
                },
                "name": {
                    "type": "string",
                    "description": "Release the lock on this named resource"
                }
            }
        }
    }
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "release_global_resource"
    PARAM_ORDER = ['name', 'job']

    def doRender(self):
        try: 
            params = json.loads(self.request.body)
            jsonschema.validate(params, self.DEFINITIONS['releaseresource'])
        except Exception, e:
            raise XenRTAPIError(self, HTTPBadRequest, str(e).split("\n")[0])
        self.get_lock()
        ret = ""
        try: 
            cur = self.getDB().cursor()
            if "job" in params:
                print params['job']
                cur.execute("UPDATE tblresources SET status='idle', jobid=NULL WHERE jobid=%s AND status='locked'", [params['job']])
            else:
                cur.execute("UPDATE tblresources SET status='idle', jobid=NULL WHERE name=%s AND status='locked'", [params['name']])
            self.getDB().commit()
        finally:
            self.release_lock()
        return {}

class ListResources(XenRTAPIv2Page):
    SUMMARY = "List all of the global resources"
    TAGS = ["backend"]
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "get_global_resources"
    PARAMS = []
    PATH = "/globalresources"
    REQTYPE = "GET"

    def render(self):
        ret = {}
        cur = self.getDB().cursor()
        cur.execute("SELECT name,site,status,jobid,type,data FROM tblresources")
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            ret[rc[0].strip()] = {
                "name": rc[0].strip(),
                "site": rc[1].strip().split(",") if rc[1] else None,
                "status": rc[2].strip(),
                "job": rc[3],
                "type": rc[4].strip(),
                "data": json.loads(rc[5])}
        return ret

class GetResource(XenRTAPIv2Page):
    SUMMARY = "Get details of one global resource"
    TAGS = ["backend"]
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "get_global_resource"
    PARAMS = [
        {'name': 'name',
         'in': 'path',
         'required': True,
         'description': 'Resource to fetch',
         'type': 'string'}]
    PATH = "/globalresource/{name}"
    REQTYPE = "GET"

    def render(self):
        ret = ""
        cur = self.getDB().cursor()
        cur.execute("SELECT name, site, status, jobid, type, data FROM tblresources WHERE name=%s", [self.request.matchdict['name']])

        rc = cur.fetchone()
        ret = {}
        if not rc:
            raise XenRTAPIError(self, HTTPNotFound, reason="Resource %s not found" % self.request.matchdict['name'])
        ret = {
            "name": rc[0].strip(),
            "site": rc[1].strip().split(",") if rc[1] else None,
            "status": rc[2].strip(),
            "job": rc[3],
            "type": rc[4].strip(),
            "data": json.loads(rc[5])}
        return ret

        

RegisterAPI(LockResource)
RegisterAPI(ReleaseResource)
RegisterAPI(ListResources)
RegisterAPI(GetResource)
