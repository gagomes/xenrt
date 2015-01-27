from app.apiv2 import *
from pyramid.httpexceptions import *
import app.constants
import calendar
import json
import jsonschema
import config
import urlparse

class _JobsBase(XenRTAPIv2Page):

    def getStatus(self, status, removed):
        if removed == "yes":
            return "removed"
        else:
            return status

    def getJobs(self, 
                limit,
                status=[],
                users=[],
                excludeusers=[],
                srs=[],
                ids=[],
                detailids=[],
                machines=[],
                getParams=False,
                getResults=False,
                getLog=False):
        cur = self.getDB().cursor()
        params = []
        conditions = []
        joinquery = ""
        if srs:
            joinquery += "INNER JOIN tbljobgroups g ON g.jobid = j.jobid "
            srcond = []
            for s in srs:
                srcond.append("g.gid=%s")
                params.append("SR%s" % str(s))
            conditions.append("(%s)" % " OR ".join(srcond))

        if ids:
            conditions.append("j.jobid IN (%s)" % (", ".join(["%s"] * len(ids))))
            params.extend(ids)

        if detailids:
            joinquery += "INNER JOIN tblresults r ON r.jobid = j.jobid "
            conditions.append("r.detailid IN (%s)" % (", ").join(["%s"] * len(detailids)))
            params.extend(detailids)

        if machines:
            joinquery += "INNER JOIN tblevents e ON j.jobid=e.edata::int "
            conditions.append("e.etype='JobStart'")
            conditions.append("e.subject IN (%s)" % (", ").join(["%s"] * len(machines)))
            params.extend(machines)

        if status:
            statuscond = []
            for s in status:
                if s in ['new', 'running', 'done']:
                    statuscond.append("j.jobstatus=%s")
                    params.append(s)
            if "removed" in status:
                statuscond.append("j.removed='yes'")
            else:
                conditions.append("j.removed != 'yes'")
            conditions.append("(%s)" % " OR ".join(statuscond))

        if users:
            conditions.append("j.userid IN (%s)" % (", ").join(["%s"] * len(users)))
            params.extend(users)

        if excludeusers:
            conditions.append("j.userid NOT IN (%s)" % (", ").join(["%s"] * len(excludeusers)))
            params.extend(excludeusers)
            

        params.append(limit)

        jobs = {}

        cur.execute("SELECT j.jobid, j.version, j.revision, j.options, j.jobstatus, j.userid, j.machine, j.uploaded, j.removed FROM tbljobs j %s WHERE %s ORDER BY j.jobid DESC LIMIT %%s" % (joinquery, " AND ".join(conditions)), params)
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            jobs[rc[0]] = {
                "id": rc[0],
                "params": {
                    "VERSION": rc[1].strip(),
                    "REVISION": rc[2].strip(),
                    "OPTIONS": rc[3].strip(),
                    "UPLOADED": rc[7].strip(),
                    "REMOVED": rc[8].strip(),
                },
                "user": rc[5].strip(),
                "status": self.getStatus(rc[4].strip(), rc[8].strip()),
                "machines": rc[6].strip().split(",") if rc[6] else [],
                "results": []
           }
       
        if len(jobs.keys()) == 0:
            return jobs

        jobidlist = ", ".join(["%s"] * len(jobs.keys()))

        cur.execute("SELECT jobid, param, value FROM tbljobdetails WHERE jobid IN (%s)" % jobidlist, jobs.keys())
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            job = rc[0]
            param = rc[1].strip()
            value = rc[2].strip()
            jobs[job]['params'][param] = value

        u = urlparse.urlparse(config.url_base)
        for j in jobs.keys():
            jobs[j]['suiterun'] = jobs[j]['params'].get("TESTRUN_SR")
            jobs[j]['result'] = jobs[j]['params'].get("CHECK")
            jobs[j]['attachmentUploadUrl'] = "%s://%s%s/job/%d/attachments" % (u.scheme, jobs[j]['params'].get("LOG_SERVER"), u.path.rstrip("/"), j)
            jobs[j]['logUploadUrl'] = "%s://%s%s/job/%d/log" % (u.scheme, jobs[j]['params'].get("LOG_SERVER"), u.path.rstrip("/"), j)
            mlist = ""
            for k in ["SCHEDULEDON", "SCHEDULEDON2", "SCHEDULEDON3"]:
                if jobs[j]['params'].has_key(k):
                    mlist += jobs[j]['params'][k] + ","
                mlist = mlist.replace(" ", "")
                mlist = mlist.replace(",,",",")
                mlist = mlist.strip()
                mlist = mlist.strip(",")
            if mlist:
                jobs[j]['machines'] = mlist.split(",")
            jobs[j]['description'] = jobs[j]['params'].get("JOBDESC", jobs[j]['params'].get("DEPS"))
            jobs[j]['id'] = j

        if getResults:
            for j in jobs.keys():
                jobs[j]['results'] = {}
            cur.execute("SELECT jobid, result, detailid, test, phase FROM tblresults WHERE jobid IN (%s) ORDER BY detailid" % jobidlist, jobs.keys())
            detailids = {}
            while True:
                rc = cur.fetchone()
                if not rc:
                    break
                jobs[rc[0]]['results'][rc[2]] ={
                    "result": rc[1].strip(),
                    "detailid": rc[2],
                    "test": rc[3].strip(),
                    "phase": rc[4].strip(),
                    "logUploadUrl": "%s://%s%s/test/%d/log" % (u.scheme, jobs[j]['params'].get("LOG_SERVER"), u.path.rstrip("/"), rc[2])
                }
                detailids[rc[2]] = rc[0]
            if getLog:
                for j in jobs.keys():
                    for d in jobs[j]['results'].keys():
                        jobs[j]['results'][d]['log'] = []
                if len(detailids.keys()) > 0:
                    detailidlist = ", ".join(["%s"] * len(detailids.keys()))
                    cur.execute("SELECT detailid, ts, key, value FROM tbldetails WHERE DETAILID IN (%s) ORDER BY ts" % detailidlist, detailids.keys())
                    while True:
                        rc = cur.fetchone()
                        if not rc:
                            break
                        jobs[detailids[rc[0]]]['results'][rc[0]]['log'].append({
                            "ts": calendar.timegm(rc[1].timetuple()),
                            "type": rc[2],
                            "log": rc[3].strip()
                            })


        if not getParams: # We need to get most of the data anyway to populate the main fields, disabling this just speeds up the HTTP
            for j in jobs.keys():
                del jobs[j]['params']

        return jobs

    def updateJobField(self, jobid, key, value, commit=True, lookupExisting=True):
        db = self.getDB()

        if lookupExisting:
            jobs = self.getJobs(1, ids=[jobid], getParams=True)
            if not jobid in jobs:
                raise XenRTAPIError(HTTPNotFound, "Job not found")

            details = jobs[jobid]['params']
        else:
            details = {}

        if key in app.constants.core_params:
            cur = db.cursor()
            try:
                cur.execute("UPDATE tbljobs SET %s=%%s WHERE jobid=%%s;" % (key), 
                            [value,jobid])
                if commit:
                    db.commit()
            finally:
                cur.close()
        else:
            cur = db.cursor()
            try:
                if not details.has_key(key):
                    cur.execute("INSERT INTO tbljobdetails (jobid,param,value) "
                                "VALUES (%s,%s,%s);", [jobid, key, value])
                elif len(value) > 0:
                    cur.execute("UPDATE tbljobdetails SET value=%s WHERE "
                                "jobid=%s AND param=%s;", [value,jobid,key])
                else:
                    # Use empty string as a way to delete a property
                    cur.execute("DELETE FROM tbljobdetails WHERE jobid=%s "
                                "AND param=%s;", [jobid, key])
                if commit:
                    db.commit()
            finally:
                cur.close()
    

class ListJobs(_JobsBase):
    PATH = "/jobs"
    REQTYPE = "GET"
    DESCRIPTION = "Get jobs matching parameters"
    PARAMS = [
         {'collectionFormat': 'multi',
          'default': 'new,running',
          'description': 'Filter on job status. Any of "new", "running", "removed", "done" - can specify multiple',
          'in': 'query',
          'items': {'enum': ['new', 'running', 'done', 'removed'], 'type': 'string'},
          'name': 'status',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Filter on user - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'user',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Exclude jobs from this user from the results. Can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'excludeuser',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Filter on suite run - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'suiterun',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Filter on machine the job was executed on - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'machine',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Get a specific job - can specify multiple',
          'in': 'query',
          'items': {'type': 'integer'},
          'name': 'jobid',
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Find a job with a specific detail ID - can specify multiple',
          'in': 'query',
          'items': {'type': 'integer'},
          'name': 'detailid',
          'type': 'array'},
         {'description': 'Limit the number of results. Defaults to 100, hard limited to 10000',
          'in': 'query',
          'name': 'limit',
          'required': False,
          'type': 'integer'},
         {'default': False,
          'description': 'Return all job parameters. Defaults to false',
          'in': 'query',
          'name': 'params',
          'required': False,
          'type': 'boolean'},
         {'default': False,
          'description': 'Return the results from all testcases in the job. Defaults to false',
          'in': 'query',
          'name': 'results',
          'required': False,
          'type': 'boolean'},
         {'default': False,
          'description': 'Return the log items for all testcases in the job. Must also specify results. Defaults to false',
          'in': 'query',
          'name': 'logitems',
          'required': False,
          'type': 'boolean'}]
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["jobs"]

    def render(self):

        status = self.getMultiParam("status")
        ids = [int(x) for x in self.getMultiParam("jobid")]
        detailids = [int(x) for x in self.getMultiParam("detailid")]
        if not status and not ids:
            status = ['new', 'running']
        users = self.getMultiParam("user")
        machines = self.getMultiParam("machine")
        excludeusers = self.getMultiParam("excludeuser")
        limit = int(self.request.params.get("limit", 100))
       
        suiteruns = self.getMultiParam("suiterun")

        limit = min(limit, 10000)

        params = self.request.params.get("params", "false") == "true"
        results = self.request.params.get("results", "false") == "true"
        logitems = self.request.params.get("logitems", "false") == "true"

        return self.getJobs(limit, 
                            status=status,
                            users=users,
                            srs=suiteruns,
                            excludeusers=excludeusers,
                            ids=ids,
                            detailids=detailids,
                            machines=machines,
                            getParams=params,
                            getResults=results,
                            getLog=logitems)

class GetJob(_JobsBase):
    PATH = "/job/{id}"
    REQTYPE = "GET"
    DESCRIPTION = "Gets a specific job object"
    TAGS = ["jobs"]
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'Job ID to fetch',
         'type': 'integer'},
         {'default': False,
          'description': 'Return the log items for all testcases in the job. Defaults to false',
          'in': 'query',
          'name': 'logitems',
          'required': False,
          'type': 'boolean'}]
    RESPONSES = { "200": {"description": "Successful response"}}

    def render(self):
        job = int(self.request.matchdict['id'])
        logitems = self.request.params.get("logitems", "false") == "true"
        jobs = self.getJobs(1, ids=[job], getParams=True, getResults=True, getLog=logitems)
        if not job in jobs:
            raise XenRTAPIError(HTTPNotFound, "Job not found")
        return jobs[job]

class RemoveJob(_JobsBase):
    WRITE = True
    PATH = "/job/{id}"
    REQTYPE = "DELETE"
    DESCRIPTION = "Removes a job"
    TAGS = ["jobs"]
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'Job ID to remove',
         'type': 'integer'}]
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "remove_job"

    def render(self):
        self.updateJobField(int(self.request.matchdict['id']), "REMOVED", "yes")
        return {}
        
class NewJob(_JobsBase):
    WRITE = True
    PATH = "/jobs"
    REQTYPE = "POST"
    DESCRIPTION = "Submits a new job"
    TAGS = ["jobs"]
    PARAMS = [
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the lease required',
         'schema': { "$ref": "#/definitions/newjob" }
        }
    ]
    DEFINITIONS = {"newjob": {
        "title": "New Job",
        "type": "object",
        "properties": {
            "pools": {
                "type": "array",
                "items": {"type": "string"}
            },
            "specified_machines": {
                "type": "array",
                "items": {"type": "string"}
            },
            "machines": {
                "type": "integer"
            },
            "sequence": {
                "type": "string"
            },
            "custom_sequence": {
                "type": "boolean"
            },
            "job_group": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer"
                     },
                     "tag": {
                        "type": "string"
                     }
                 },
            },
            "params": {
                "type": "object"
            },
            "deployment": {
                "type": "object"
            },
            "resources": {
                "type": "array",
                "items": {"type": "string"}
            },
            "flags": {
                "type": "array",
                "items": {"type": "string"}
            },
            "email": {
                "type": "string"
            }
        }
    }}
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "new_job"
    PARAM_ORDER=["machines", "pools", "flags", "resources", "specified_machines", "sequence", "custom_sequence", "params", "deployment", "job_group", "email"]

    def updateJobField(self, field, value):
        _JobsBase.updateJobField(self, self.jobid, field, value, commit=False, lookupExisting=False)

    def newJob(self,
               pools=None,
               numberMachines=None,
               specifiedMachines=None,
               jobGroup=None,
               params=None,
               sequence=None,
               customSequence=False,
               deployment=None,
               resources=None,
               flags=None,
               email=None):

        db = self.getDB()
        cur = db.cursor()
        cur.execute("LOCK TABLE tbljobs IN EXCLUSIVE MODE")
        cur.execute("INSERT INTO tbljobs (jobstatus, userid, version, revision, options, uploaded,removed) VALUES ('new', %s, '', '', '', '', '')", [self.getUser()])
        # Lookup jobid
        cur.execute("SELECT last_value FROM jobid_seq")
        rc = cur.fetchone()
        self.jobid = int(rc[0])
        db.commit() # Commit to release the lock

        if specifiedMachines:
            self.updateJobField("MACHINE", ",".join(specifiedMachines))
            self.updateJobField("MACHINES_SPECIFIED", "yes")
            self.updateJobField("MACHINES_REQUIRED", str(len(specifiedMachines)))
        else:
            if resources:
                self.updateJobField("RESOURCES_REQUIRED", ",".join(resources))
            if flags:
                self.updateJobField("FLAGS", ",".join(flags))
            if pools:
                self.updateJobField("POOL", ",".join(pools))
            if numberMachines:
                self.updateJobField("MACHINES_REQUIRED", str(numberMachines))
            else:
                self.updateJobField("MACHINES_REQUIRED", "1")

        if sequence:
            self.updateJobField("DEPS", sequence)
            if customSequence:
                self.updateJobField("CUSTOM_SEQUENCE", "yes")

        if jobGroup:
            try:
                cur.execute("DELETE FROM tblJobGroups WHERE "
                            "gid = %s AND description = %s",
                            [jobGroup['id'], jobGroup['tag']])
            except:
                pass
            cur.execute("INSERT INTO tblJobGroups (gid, jobid, description) VALUES " \
                        "(%s, %s, %s);", [jobGroup['id'], self.jobid, jobGroup['tag']])
            

        # TODO: Handle deployment spec

        if not params:
            params = {}

        params['JOB_FILES_SERVER'] = config.log_server
        params['LOG_SERVER'] = config.log_server

        for p in params.keys():
            self.updateJobField(p, params[p])

        if email:
            self.updateJobField("EMAIL", email)

        db.commit()
        cur.close()

    def render(self):
        try:
            j = json.loads(self.request.body)
            jsonschema.validate(j, self.DEFINITIONS['newjob'])
        except Exception, e:
            raise XenRTAPIError(HTTPBadRequest, str(e).split("\n")[0])
        self.newJob(pools=j.get("pools"),
                    numberMachines=j.get("machines"),
                    specifiedMachines=j.get("specified_machines"),
                    jobGroup=j.get("job_group"),
                    params=j.get("params"),
                    sequence=j.get("sequence"),
                    customSequence=j.get("custom_sequence"),
                    deployment=j.get("deployment"),
                    resources=j.get("resources"),
                    flags=j.get("flags"),
                    email=j.get("email"))
        return self.getJobs(1, ids=[self.jobid], getParams=True,getResults=False,getLog=False)[self.jobid]

RegisterAPI(ListJobs)
RegisterAPI(GetJob)
RegisterAPI(RemoveJob)
RegisterAPI(NewJob)
