from app.apiv2 import *
from machines import _MachineBase
from pyramid.httpexceptions import *
import app.constants
import app.utils
import calendar
import json
import jsonschema
import config
import urlparse
import StringIO
import requests
import time
import re

class _JobBase(_MachineBase):

    def getJobStatus(self, status, removed):
        if removed and removed.strip() == "yes":
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
                minJob=None,
                maxJob=None,
                getParams=False,
                getResults=False,
                getLog=False,
                exceptionIfEmpty=False):
        cur = self.getDB().cursor()
        params = []
        conditions = []
        joinquery = ""
        if srs:
            joinquery += "LEFT OUTER JOIN tbljobgroups g ON g.jobid = j.jobid "
            srcond = []
            for s in srs:
                if s.lower() == "null":
                    srcond.append("g.gid IS NULL")
                else:
                    srcond.append("g.gid=%s")
                    params.append("SR%s" % str(s))
            conditions.append("(%s)" % " OR ".join(srcond))

        if ids:
            conditions.append("j.jobid IN (%s)" % (", ".join(["%s"] * len(ids))))
            params.extend(ids)

        if minJob:
            conditions.append("j.jobid >= %s")
            params.append(minJob)

        if maxJob:
            conditions.append("j.jobid <= %s")
            params.append(maxJob)

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
                elif s != 'removed':
                    raise XenRTAPIError(self, HTTPBadRequest, "Invalid job status requested")
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

        cur.execute("SELECT j.jobid, j.version, j.revision, j.options, j.jobstatus, j.userid, j.machine, j.uploaded, j.removed, j.preemptable FROM tbljobs j %s WHERE %s ORDER BY j.jobid DESC LIMIT %%s" % (joinquery, " AND ".join(conditions)), self.expandVariables(params))
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            jobs[rc[0]] = {
                "id": rc[0],
                "params": {},
                "user": rc[5].strip(),
                "status": self.getJobStatus(rc[4].strip(), rc[8]),
                "rawstatus": rc[4].strip(),
                "removed": True if rc[8] and rc[8].strip() == "yes" else False,
                "machines": rc[6].strip().split(",") if rc[6] else [],
                "preemptable": bool(rc[9])
            }
            if rc[8] and rc[8].strip():
                jobs[rc[0]]['params']["REMOVED"] = rc[8].strip()
            if rc[1] and rc[1].strip():
                jobs[rc[0]]['params']["VERSION"] = rc[1].strip()
            if rc[2] and rc[2].strip():
                jobs[rc[0]]['params']["REVISION"] = rc[2].strip()
            if rc[3] and rc[3].strip():
                jobs[rc[0]]['params']["OPTIONS"] = rc[3].strip()
            if rc[7] and rc[7].strip():
                jobs[rc[0]]['params']["UPLOADED"] = rc[7].strip()
       
        if len(jobs.keys()) == 0:
            if exceptionIfEmpty:
                raise XenRTAPIError(self, HTTPNotFound, "Job not found")
            return jobs

        jobidlist = ", ".join(["%s"] * len(jobs.keys()))

        cur.execute("SELECT jobid, param, value FROM tbljobdetails WHERE jobid IN (%s)" % jobidlist, jobs.keys())
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            jobs[rc[0]]['params'][rc[1].strip()] = rc[2].strip()

        u = urlparse.urlparse(config.url_base)
        for j in jobs.keys():
            jobs[j]['suiterun'] = jobs[j]['params'].get("TESTRUN_SR")
            jobs[j]['result'] = jobs[j]['params'].get("CHECK")
            jobs[j]['attachmentUploadUrl'] = "%s://%s%s/api/files/v2/job/%d/attachments" % (u.scheme, jobs[j]['params'].get("LOG_SERVER"), u.path.rstrip("/"), j)
            jobs[j]['logUploadUrl'] = "%s://%s%s/api/files/v2/job/%d/log" % (u.scheme, jobs[j]['params'].get("LOG_SERVER"), u.path.rstrip("/"), j)
            if jobs[j]['params'].get('UPLOADED') == "yes":
                logUrl = "%s://%s%s/api/files/v2/fileget/%d" % (u.scheme, jobs[j]['params'].get("LOG_SERVER"), u.path.rstrip("/"), j)
                logIndexUrl = "%s://%s%s/api/files/v2/index/%d" % (u.scheme, jobs[j]['params'].get("LOG_SERVER"), u.path.rstrip("/"), j)
            else:
                logUrl = None
                logIndexUrl = None
            jobs[j]['logUrl'] = logUrl
            jobs[j]['logIndexUrl'] = logIndexUrl
            mlist = ""
            for k in ["SCHEDULEDON", "SCHEDULEDON2", "SCHEDULEDON3"]:
                if jobs[j]['params'].has_key(k):
                    mlist += jobs[j]['params'][k] + ","
                mlist = mlist.replace(" ", "")
                mlist = mlist.replace(",,",",")
                mlist = mlist.strip()
                mlist = mlist.strip(",")
            if not mlist and "MACHINE" in jobs[j]['params']:
                mlist = jobs[j]['params']["MACHINE"]
            if mlist:
                jobs[j]['machines'] = mlist.split(",")
            jobs[j]['description'] = jobs[j]['params'].get("JOBDESC", jobs[j]['params'].get("DEPS"))
            jobs[j]['id'] = j

        if getResults:
            for j in jobs.keys():
                jobs[j]['results'] = {}
            cur.execute("SELECT jobid, result, detailid, test, phase, uploaded FROM tblresults WHERE jobid IN (%s) ORDER BY detailid" % jobidlist, jobs.keys())
            detailids = {}
            while True:
                rc = cur.fetchone()
                if not rc:
                    break
                if rc[5] and rc[5].strip() == "yes":
                    logUrl = "%s://%s%s/api/files/v2/fileget/%d.test" % (u.scheme, jobs[rc[0]]['params'].get("LOG_SERVER"), u.path.rstrip("/"), rc[2])
                    logIndexUrl = "%s://%s%s/api/files/v2/index/%d.test" % (u.scheme, jobs[rc[0]]['params'].get("LOG_SERVER"), u.path.rstrip("/"), rc[2])
                else:
                    logUrl = None
                    logIndexUrl = None
                jobs[rc[0]]['results'][rc[2]] ={
                    "result": rc[1].strip(),
                    "detailid": rc[2],
                    "test": rc[3].strip(),
                    "phase": rc[4].strip(),
                    "logUploadUrl": "%s://%s%s/api/files/v2/test/%d/log" % (u.scheme, jobs[rc[0]]['params'].get("LOG_SERVER"), u.path.rstrip("/"), rc[2]),
                    "logUrl": logUrl,
                    "logIndexUrl": logIndexUrl,
                    "logUploaded": rc[5] and rc[5].strip() == "yes",
                    "jobId": rc[0]
                }
                detailids[rc[2]] = rc[0]
            if getLog:
                for j in jobs.keys():
                    jobs[j]['log'] = []
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
                            "type": rc[2].strip(),
                            "log": rc[3].strip()
                            })
                if len(jobs.keys()) > 0:
                    jobidlist = ", ".join(["%s"] * len(jobs.keys()))
                    cur.execute("SELECT job, ts, log, id, linked, completes, iserror FROM tbljoblog WHERE job IN (%s) ORDER BY ts" % jobidlist, jobs.keys())
                    while True:
                        rc = cur.fetchone()
                        if not rc:
                            break
                        jobs[rc[0]]['log'].append({
                            "ts": calendar.timegm(rc[1].timetuple()),
                            "log": rc[2].strip(),
                            "id": rc[3],
                            "linked": rc[4],
                            "completes": rc[5],
                            "iserror": bool(rc[6])
                            })


        if not getParams: # We need to get most of the data anyway to populate the main fields, disabling this just speeds up the HTTP
            for j in jobs.keys():
                del jobs[j]['params']

            

        return jobs

    def removeJob(self, jobid, commit=True, returnJobInfo=True):
        self.updateJobField(jobid, "REMOVED", "yes", commit=False)
        if self.getUser():
            self.updateJobField(jobid, "REMOVED_BY", self.getUser().userid, commit=False)
        
        if commit:
            self.getDB().commit()

        if returnJobInfo:
            jobinfo = self.getJobs(1, ids=[jobid], getParams=False,getResults=False,getLog=False, exceptionIfEmpty=True)[jobid]
            return jobinfo

    def updateJobField(self, jobid, key, value, commit=True):
        db = self.getDB()

        if key in app.constants.core_params:
            if key in app.constants.bool_params:
                value = app.utils.toBool(value)
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
                if value == None or value == "":
                    # Use empty string as a way to delete a property
                    cur.execute("DELETE FROM tbljobdetails WHERE jobid=%s "
                                "AND param=%s;", [jobid, key])
                else:
                    # Try and do an update first
                    cur.execute("UPDATE tbljobdetails SET value=%s WHERE "
                                "jobid=%s AND param=%s;", [str(value),jobid,key])
                    if cur.rowcount == 0:
                        # Parameter doesn't already exist, do an INSERT
                        cur.execute("INSERT INTO tbljobdetails (jobid,param,value) "
                                    "VALUES (%s,%s,%s);", [jobid, key, str(value)])
                if commit:
                    db.commit()
            finally:
                cur.close()
    
    def setJobStatus(self, id, status, commit=True):

        db = self.getDB()

        try:
            cur = db.cursor()
            cur.execute("UPDATE tbljobs SET jobstatus=%s WHERE jobid=%s;", [status,id])
            if commit:
                db.commit()

        finally:
            cur.close()

class ListJobs(_JobBase):
    PATH = "/jobs"
    REQTYPE = "GET"
    SUMMARY = "Get jobs matching parameters"
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
          'type': 'boolean'},
         {'description': 'Only return jobs where the job id is >= to this',
          'in': 'query',
          'name': 'minjobid',
          'required': False,
          'type': 'integer'},
         {'description': 'Only return jobs where the job id is <= to this',
          'in': 'query',
          'name': 'maxjobid',
          'required': False,
          'type': 'integer'}]
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
        maxJob = self.request.params.get("maxjobid")
        minJob = self.request.params.get("minjobid")
        if ids:
            limit = int(self.request.params.get("limit", 0))
        else:   
            limit = int(self.request.params.get("limit", 100))

        if limit == 0:
            limit = 10000
       
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
                            minJob = minJob,
                            maxJob = maxJob,
                            getParams=params,
                            getResults=results,
                            getLog=logitems)

class GetJob(_JobBase):
    PATH = "/job/{id}"
    REQTYPE = "GET"
    SUMMARY = "Gets a specific job object"
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
        jobs = self.getJobs(1, ids=[job], getParams=True, getResults=True, getLog=logitems, exceptionIfEmpty=True)
        return jobs[job]

class GetTest(_JobBase):
    PATH = "/test/{id}"
    REQTYPE = "GET"
    SUMMARY = "Gets a specific test object"
    TAGS = ["jobs"]
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'Test detail ID to fetch',
         'type': 'integer'},
         {'default': False,
          'description': 'Return the log items for all testcases in the job. Defaults to false',
          'in': 'query',
          'name': 'logitems',
          'required': False,
          'type': 'boolean'}]
    RESPONSES = { "200": {"description": "Successful response"}}

    def render(self):
        detail = int(self.request.matchdict['id'])
        logitems = self.request.params.get("logitems", "false") == "true"
        jobs = self.getJobs(1, detailids=[detail], getResults=True, getLog=logitems, exceptionIfEmpty=True)

        return jobs.values()[0]['results'][detail]

class RemoveJobs(_JobBase):
    WRITE = True
    PATH = "/jobs"
    REQTYPE = "DELETE"
    SUMMARY = "Removes multiple jobs"
    TAGS = ["jobs"]
    PARAMS = [
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Jobs to remove',
         'schema': { "$ref": "#/definitions/removejobs" }
        }]
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "remove_jobs"
    DEFINITIONS = {"removejobs": {
        "title": "Remove Jobs",
        "type": "object",
        "properties": {
            "jobs": {
                "type": "array",
                "description": "Jobs to remove",
                "items": {"type": "integer"}
            }
        },
        "required": ["jobs"]
    }}

    def render(self):
        try:
            if self.request.body.strip():
                j = json.loads(self.request.body)
                jsonschema.validate(j, self.DEFINITIONS['removejobs'])
            else:
                j = {}
        except Exception, e:
            raise XenRTAPIError(self, HTTPBadRequest, str(e).split("\n")[0])
        for job in j['jobs']:
            self.removeJob(job, commit=False, returnJobInfo=False)
        self.getDB().commit()
                 
        return {}

class RemoveJob(_JobBase):
    WRITE = True
    PATH = "/job/{id}"
    REQTYPE = "DELETE"
    SUMMARY = "Removes a job"
    TAGS = ["jobs"]
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'Job ID to remove',
         'type': 'integer'},
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the update',
         'schema': { "$ref": "#/definitions/removejob" }
        }]
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "remove_job"
    DEFINITIONS = {"removejob": {
        "title": "Remove Job",
        "type": "object",
        "properties": {
            "return_machines": {
                "type": "boolean",
                "description": "Whether to return the machines borrowed by this job"
            }
        }
    }}

    def render(self):
        try:
            if self.request.body.strip():
                j = json.loads(self.request.body)
                jsonschema.validate(j, self.DEFINITIONS['removejob'])
            else:
                j = {}
        except Exception, e:
            raise XenRTAPIError(self, HTTPBadRequest, str(e).split("\n")[0])
        job = int(self.request.matchdict['id'])
        jobinfo = self.removeJob(job)
        if j.get('return_machines'):
            for m in jobinfo['machines']:
                self.return_machine(m, self.getUser().userid, False, canForce=False, commit=False)
            self.getDB().commit()
                 
        return {}

class TeardownJobSimple(_JobBase):
    REQTYPE = None
    WRITE = True
    PATH = "/job/{id}/teardown/simple"
    HIDDEN = True

    def render(self):
        job = int(self.request.matchdict['id'])
        jobinfo = self.getJobs(1, ids=[job], getParams=False,getResults=False,getLog=False, exceptionIfEmpty=True)[job]
        for m in jobinfo['machines']:
            self.return_machine(m, self.getUser().userid, False, canForce=False, commit=False)
        self.getDB().commit()

class RenewJobLeaseSimple(_JobBase):
    REQTYPE = None
    WRITE = True
    PATH = "/job/{id}/renewlease/simple"
    HIDDEN = True

    def render(self):
        job = int(self.request.matchdict['id'])
        duration = int(self.request.params.get("duration", "3"))
        jobinfo = self.getJobs(1, ids=[job], getParams=False,getResults=False,getLog=False, exceptionIfEmpty=True)[job]
        for m in jobinfo['machines']:
            self.lease(m, self.getUser().userid, duration, self.request.params.get("reason", "Renewed lease"), False, commit=False)
        self.getDB().commit()


class NewJob(_JobBase):
    WRITE = True
    PATH = "/jobs"
    REQTYPE = "POST"
    SUMMARY = "Submits a new job"
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
                "items": {"type": "string"},
                "description": "Pools this job can run on"
            },
            "specified_machines": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specified list of machines for this job to run on"
            },
            "machines": {
                "type": "integer",
                "description": "Number of machines required for this job"
            },
            "sequence": {
                "type": "string",
                "description": "Sequence file name"
            },
            "custom_sequence": {
                "type": "boolean",
                "description": "Whether the sequence is in xenrt.git (false) or a custom sequence (true)"
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
                 "description": "Job group details. Members are 'id' (integer - id of job group), 'tag' (string - tag for this job"
            },
            "lease_machines": {
                "type": "object",
                "description": "Machine lease details. Members are 'duration' (integer - length of lease in hours), 'reason' (string -  reason that will be associated with the machine lease)",
                "properties": {
                    "duration": {
                        "type": "integer",
                        "description": "Duration of machine lease"
                     },
                     "reason": {
                        "type": "string",
                        "description": "Reason for machine lease"
                     },
                 }
            },
            "params": {
                "type": "object",
                "description": "Key/value pair of job parameters"
            },
            "deployment": {
                "type": "object",
                "description": "JSON deployment spec to just create a deployment"
            },
            "resources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of resources required. One such item might be memory>=4G"
            },
            "flags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of flags required. Can negate by prefixing a flag with '!'"
            },
            "email": {
                "type": "string",
                "description": "Email address to notify on completion"
            },
            "inputdir": {
                "type": "string",
                "description": "Input directory for the job"
            },
            "preemptable": {
                "type": "boolean",
                "description": "Run job on a preemptable basis - can be cancelled for scheduled testing (ACL policy dependent)"
            }
        }
    }}
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "new_job"
    PARAM_ORDER=["machines", "pools", "flags", "resources", "specified_machines", "sequence", "custom_sequence", "params", "deployment", "job_group", "email", "inputdir", "lease_machines"]

    def updateJobField(self, field, value, params={}):
        _JobBase.updateJobField(self, self.jobid, field, value, commit=False)
        if field in params:
            del params[field]

    def removeParams(self, params, keys):
        for k in keys:
            if params.has_key(k):
                del params[k]

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
               email=None,
               inputdir=None,
               lease=None,
               preemptable=None):
        
        if not params:
            params = {}

        if params.has_key("JOBGROUP") and params.has_key("JOBGROUPTAG") and not jobGroup:
            jobGroup = {"id": params['JOBGROUP'], "tag": params['JOBGROUPTAG']}

        if params.has_key("PREEMPTABLE") and preemptable is None:
            preemptable = app.utils.toBool(params["PREEMPTABLE"])
            del params["PREEMPTABLE"]

        self.removeParams(params, ["USERID", "REMOVED", "UPLOADED", "JOBSTATUS", "REMOVED_BY"])

        params["JOB_SUBMITTED"] = time.asctime(time.gmtime()) + " UTC"

        db = self.getDB()
        cur = db.cursor()
        cur.execute("INSERT INTO tbljobs (jobstatus, userid, version, revision, options, uploaded,removed,preemptable) VALUES ('new', %s, '', '', '', '', '',NULL) RETURNING jobid", [self.getUser().userid])
        rc = cur.fetchone()
        self.jobid = int(rc[0])

        if specifiedMachines:
            self.updateJobField("MACHINE", ",".join(specifiedMachines), params)
            self.updateJobField("MACHINES_SPECIFIED", "yes", params)
            self.updateJobField("MACHINES_REQUIRED", str(len(specifiedMachines)), params)
        else:
            if resources:
                self.updateJobField("RESOURCES_REQUIRED", "/".join(resources), params)
            if flags:
                self.updateJobField("FLAGS", ",".join(flags), params)
            if pools:
                self.updateJobField("POOL", ",".join(pools), params)
            if numberMachines:
                self.updateJobField("MACHINES_REQUIRED", str(numberMachines), params)
            elif not "MACHINES_REQUIRED" in params:
                self.updateJobField("MACHINES_REQUIRED", "1", params)

        if deployment:
            sequence = "deployment.seq"
            customSequence = True

        if sequence:
            self.updateJobField("DEPS", sequence, params)
            if customSequence:
                self.updateJobField("CUSTOM_SEQUENCE", "yes", params)
        
        if jobGroup:
            if not re.match("^SR\d+$", jobGroup['id']):
                raise XenRTAPIError(self, HTTPBadRequest, "Job group must be of form SRnnnnn")
            cur.execute("INSERT INTO tblJobGroups (gid, jobid, description) VALUES " \
                        "(%s, %s, %s);", [jobGroup['id'], self.jobid, jobGroup['tag']])
            params['JOBGROUP'] = jobGroup['id']
            params['JOBGROUPTAG'] = jobGroup['tag']
            
        params['JOB_FILES_SERVER'] = config.log_server
        params['LOG_SERVER'] = config.log_server

        if email:
            self.updateJobField("EMAIL", email, params)

        if inputdir:
            self.updateJobField("INPUTDIR", inputdir, params)

        if lease and lease.get("duration"):
            self.updateJobField("MACHINE_HOLD_FOR_OK", lease['duration'] * 60, params)
            self.updateJobField("MACHINE_HOLD_REASON", lease.get("reason", ""), params)

        if preemptable:
            self.updateJobField("PREEMPTABLE", True)
            # And lower the priority of the job
            params['JOBPRIO'] = str(int(params.get('JOBPRIO', 3)) + 5)

        for p in params.keys():
            self.updateJobField(p, params[p])

        db.commit()
        cur.close()
        ret = self.getJobs(1, ids=[self.jobid], getParams=True,getResults=False,getLog=False, exceptionIfEmpty=True)[self.jobid]
        if deployment:
            deploymentSeq = app.utils.create_seq_from_deployment(deployment)
            seqfile = StringIO.StringIO(deploymentSeq)
            print ret['attachmentUploadUrl']
            r = requests.post(ret['attachmentUploadUrl'], files={'file': ('deployment.seq', seqfile)})
            r.raise_for_status()

        return ret

    def render(self):
        try:
            j = json.loads(self.request.body)
            jsonschema.validate(j, self.DEFINITIONS['newjob'])
        except Exception, e:
            raise XenRTAPIError(self, HTTPBadRequest, str(e).split("\n")[0])
        return self.newJob(pools=j.get("pools"),
                           numberMachines=j.get("machines"),
                           specifiedMachines=j.get("specified_machines"),
                           jobGroup=j.get("job_group"),
                           params=j.get("params"),
                           sequence=j.get("sequence"),
                           customSequence=j.get("custom_sequence"),
                           deployment=j.get("deployment"),
                           resources=j.get("resources"),
                           flags=j.get("flags"),
                           email=j.get("email") if j.has_key("email") else self.getUser().email,
                           inputdir=j.get("inputdir"),
                           lease=j.get("lease_machines"),
                           preemptable=j.get("preemptable"))

class _GetAttachmentUrl(_JobBase):
    REQTYPE = "GET"
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'Job ID to get file from',
         'type': 'integer'},
        {'name': 'file',
         'in': 'path',
         'required': True,
         'description': 'File to download',
         'type': 'string'}]
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["jobs"]
    RETURN_KEY="url"

    def render(self):
        job = int(self.request.matchdict['id'])
        server = self.getJobs(1, ids=[job], getParams=True, exceptionIfEmpty=True)[job]['params'][self.LOCATION_PARAM]

        url = 'https://%s/xenrt/api/files/v2/fileget/%d.%s' % (server, job, self.request.matchdict['file'])

        if self.REDIRECT:
            return HTTPFound(location=url)

        return {'url': url}

class GetAttachmentPreRun(_GetAttachmentUrl):
    LOCATION_PARAM='JOB_FILES_SERVER'
    PATH='/job/{id}/attachment/prerun/{file}'
    SUMMARY='Get URL for job attachment, uploaded before job ran'
    OPERATION_ID='get_job_attachment_pre_run'
    REDIRECT=False

class RedirectAttachmentPreRun(GetAttachmentPreRun):
    REDIRECT=True
    PATH='/redirect/job/{id}/attachment/prerun/{file}'
    SUMMARY='Redirect to job attachment, uploaded before job ran'
    OPERATION_ID="no_binding"

class GetAttachmentPostRun(_GetAttachmentUrl):
    LOCATION_PARAM='LOG_SERVER'
    PATH='/job/{id}/attachment/postrun/{file}'
    SUMMARY='Get URL for job attachment, uploaded after job ran'
    OPERATION_ID='get_job_attachment_post_run'
    REDIRECT=False

class RedirectAttachmentPostRun(GetAttachmentPostRun):
    REDIRECT=True
    PATH='/redirect/job/{id}/attachment/postrun/{file}'
    SUMMARY='Redirect to job attachment, uploaded before job ran'
    OPERATION_ID="no_binding"

class GetJobDeployment(_JobBase):
    PATH='/job/{id}/deployment'
    REQTYPE='GET'
    SUMMARY='Get deployment for job'
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'Job ID to get file from',
         'type': 'integer'}]
    TAGS = ["jobs"]
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = 'get_job_deployment'

    def render(self):
        job = int(self.request.matchdict['id'])

        try:
            server = self.getJobs(1, ids=[job], getParams=True, exceptionIfEmpty=True)[job]['params']['LOG_SERVER']
            r = requests.get('https://%s/xenrt/api/files/v2/fileget/%d.deployment.json' % (server, job))
            r.raise_for_status()
            return r.json()
        except Exception, e:
            raise XenRTAPIError(self, HTTPNotFound, str(e))

class UpdateJob(_JobBase):
    REQTYPE="POST"
    WRITE = True
    PATH = "/job/{id}"
    TAGS = ["jobs"]
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'Job ID to update',
         'type': 'integer'},
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the update',
         'schema': { "$ref": "#/definitions/updatejob" }
        }
    ]
    RESPONSES = { "200": {"description": "Successful response"}}
    DEFINITIONS = {"updatejob": {
        "title": "Update Job",
        "type": "object",
        "properties": {
            "params": {
                "type": "object",
                "description": "Key-value pairs of parameters to update (set null to delete a parameter)"
            },
            "complete": {
                "type": "boolean",
                "description": "Set to true to complete the job"
            }
        }
    }}
    OPERATION_ID = "update_job"
    PARAM_ORDER=["id", "params", "complete"]
    SUMMARY = "Update job details"

    def render(self):
        try:
            j = json.loads(self.request.body)
            jsonschema.validate(j, self.DEFINITIONS['updatejob'])
        except Exception, e:
            raise XenRTAPIError(self, HTTPBadRequest, str(e).split("\n")[0])
        if j.get('params'):
            for p in j['params'].keys():
                self.updateJobField(int(self.request.matchdict['id']), p, j['params'][p], commit=False)
        if j.get("complete"):
            self.setJobStatus(int(self.request.matchdict['id']), "done", commit=False)
        self.getDB().commit()
        return {}
    
class NewJobLogItem(_JobBase):
    REQTYPE="POST"
    WRITE = True
    PATH = "/job/{id}/log"
    TAGS = ["jobs"]
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'Job ID to update',
         'type': 'integer'},
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the update',
         'schema': { "$ref": "#/definitions/addjoblogitem" }
        }
    ]
    RESPONSES = { "200": {"description": "Successful response"}}
    DEFINITIONS = {"addjoblogitem": {
        "title": "Update Job",
        "type": "object",
        "properties": {
            "log": {
                "type": "string",
                "description": "Log item to add"
            },
            "completes": {
                "type": "boolean",
                "description": "Whether this item completes the operation"
            },
            "linked": {
                "type": "integer",
                "description": "ID of linked job log item"
            },
            "iserror": {
                "type": "boolean",
                "description": "Whether this log represents an error"
            }
        },
        "required": ["log"]
    }}
    OPERATION_ID = "new_job_log_item"
    PARAM_ORDER=["id", "log", "completes", "linked", "iserror"]
    SUMMARY = "Add item to job log"
    RETURN_KEY="id"

    def render(self):
        try:
            j = json.loads(self.request.body)
            jsonschema.validate(j, self.DEFINITIONS['addjoblogitem'])
        except Exception, e:
            raise XenRTAPIError(self, HTTPBadRequest, str(e).split("\n")[0])
        db = self.getDB()
        cur = db.cursor()
        timenow = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time()))
        cur.execute("INSERT INTO tbljoblog (ts, job, log, completes, linked, iserror) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id;",
                    [timenow, self.request.matchdict['id'], j['log'], j.get('completes', False), j.get('linked', None), j.get('iserror', False)])
        logid = cur.fetchone()[0]
        db.commit()
        return {"id": logid}

class EmailJob(_JobBase):
    PATH = "/job/{id}/email"
    REQTYPE = "POST"
    SUMMARY = "Gets a specific job object"
    TAGS = ["backend"]
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'Job ID to fetch',
         'type': 'integer'}]
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "send_job_email"

    def textLog(self, job):
        out = ""
        for r in sorted(job['results'].keys(), key=int):
            out += "%s/%s: %s\n" % (
                job['results'][r]['phase'],
                job['results'][r]['test'],
                job['results'][r]['result'])
        return out

    def render(self):
        id = int(self.request.matchdict['id'])
        job = self.getJobs(1, ids=[id], getParams=True, getResults=True, getLog=False, exceptionIfEmpty=True)[id]
        if job['params'].has_key("EMAIL"):
            machine = ",".join(job['machines'])
            if not machine:
                machine = "unknown"
            result = job['result']
            if not result:
                result = "unknown"
            if job['params'].has_key("JOBDESC"):
                jobdesc = "%s (JobID %u)" % (job['params']["JOBDESC"], id)
            else:
                jobdesc = "JobID %u" % (id)
            emailto = job['params']["EMAIL"].split(",")
            subject = "[xenrt] %s %s %s" % (jobdesc, machine, result)
            summary = self.textLog(job)
            message = """
================ Summary =============================================
%s/ui/logs?jobs=%u
======================================================================
%s
======================================================================
""" % (config.url_base.rstrip("/"), id, summary.strip())
            for key in job['params'].keys():
                message =  message + "%s='%s'\n" % (key, job['params'][key])
            app.utils.sendMail(config.email_sender, emailto, subject, message, reply=emailto[0])
        return {}

RegisterAPI(ListJobs)
RegisterAPI(GetJob)
RegisterAPI(GetTest)
RegisterAPI(RemoveJob)
RegisterAPI(RemoveJobs)
RegisterAPI(NewJob)
RegisterAPI(UpdateJob)
RegisterAPI(GetAttachmentPreRun)
RegisterAPI(GetAttachmentPostRun)
RegisterAPI(RedirectAttachmentPreRun)
RegisterAPI(RedirectAttachmentPostRun)
RegisterAPI(GetJobDeployment)
RegisterAPI(EmailJob)
RegisterAPI(TeardownJobSimple)
RegisterAPI(RenewJobLeaseSimple)
RegisterAPI(NewJobLogItem)
