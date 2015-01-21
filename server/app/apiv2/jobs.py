from server import PageFactory
from app.apiv2 import XenRTAPIv2Page
from pyramid.httpexceptions import *

class XenRTGetJobsBase(XenRTAPIv2Page):

    def getStatus(self, status, removed):
        if removed == "yes":
            return "removed"
        else:
            return status

    def getJobs(self, limit, status=[], users=[], excludeusers=[], srs=[], ids=[], getParams=False, getResults=False):
        cur = self.getDB().cursor()
        params = []
        conditions = []
        if srs:
            joinquery = "INNER JOIN tbljobgroups g ON g.jobid = j.jobid "
            srcond = []
            for s in srs:
                srcond.append("g.gid=%s")
                params.append("SR%s" % str(s))
            conditions.append("(%s)" % " OR ".join(srcond))
        else:
            joinquery = ""

        if ids:
            conditions.append("j.jobid IN (%s)" % (", ".join(["%s"] * len(ids))))
            params.extend(ids)

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
            usercond = []
            for u in users:
                usercond.append("j.userid=%s")
                params.append(u)
            conditions.append("(%s)" % " OR ".join(usercond))

        for u in excludeusers:
            conditions.append("j.userid!=%s")
            params.append(u)
            

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

        for j in jobs.keys():
            jobs[j]['suiterun'] = jobs[j]['params'].get("TESTRUN_SR")
            jobs[j]['result'] = jobs[j]['params'].get("CHECK")
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

        if getResults:
            for j in jobs.keys():
                jobs[j]['results'] = []
            cur.execute("SELECT jobid, result, detailid, test, phase FROM tblresults WHERE jobid IN (%s) ORDER BY detailid" % jobidlist, jobs.keys())
            while True:
                rc = cur.fetchone()
                if not rc:
                    break
                jobs[rc[0]]['results'].append({
                    "result": rc[1].strip(),
                    "detailid": rc[2],
                    "test": rc[3].strip(),
                    "phase": rc[4].strip()
                })

        if not getParams: # We need to get most of the data anyway to populate the main fields, disabling this just speeds up the HTTP
            for j in jobs.keys():
                del jobs[j]['params']

        return jobs

class XenRTListJobs(XenRTGetJobsBase):

    def render(self):

        status = self.getMultiParam("status")
        ids = [int(x) for x in self.getMultiParam("jobid")]
        if not status and not ids:
            status = ['new', 'running']
        users = self.getMultiParam("user")
        excludeusers = self.getMultiParam("excludeuser")
        limit = int(self.request.params.get("limit", 100))
       
        suiteruns = self.getMultiParam("suiterun")

        limit = min(limit, 10000)

        params = self.request.params.get("params", "false") == "true"
        results = self.request.params.get("results", "false") == "true"

        return self.getJobs(limit, status=status, users=users, srs=suiteruns, excludeusers=excludeusers, ids=ids, getParams=params, getResults=results)

class XenRTGetJob(XenRTGetJobsBase):
    def render(self):
        job = int(self.request.matchdict['job'])
        jobs = self.getJobs(1, ids=[job], getParams=True, getResults=True)
        if not job in jobs:
            return HTTPNotFound()
        return jobs[job]

PageFactory(XenRTListJobs, "/api/v2/jobs", reqType="GET", contentType="application/json")
PageFactory(XenRTGetJob, "/api/v2/job/{job}", reqType="GET", contentType="application/json")
