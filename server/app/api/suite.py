from app.api import XenRTAPIPage
from server import PageFactory

import time,string,os,re,random,urllib,json

class XenRTSuiteStatus(XenRTAPIPage):
    def render(self):
        out = ""
        form = self.request.params
        db = self.getDB()
        suiterun = None

        if form.has_key("suiterun"):
            suiterun = form["suiterun"]

        if not suiterun:
            return "ERROR You must specify a suiterun"

        if form.has_key("resources") and form["resources"] == "yes":
            # Get a list of jobs recorded for this suite run (this may not
            # be complete is TCs/seqs have been rerun)
            sql = "select s.jobid, jobstart, jobend, mreq, jg.description " \
                  "from (select jobid, " \
                  "value as jobstart from tbljobdetails where jobid in (select " \
                  "jobid from tbljobgroups where gid = %s) and param = " \
                  "'STARTED') s left join  (select jobid, value as jobend from " \
                  "tbljobdetails where jobid in (select jobid from tbljobgroups " \
                  "where gid = %s) and param = 'FINISHED') e on s.jobid = " \
                  "e.jobid left join (select jobid, value as mreq from " \
                  "tbljobdetails where jobid in (select jobid from tbljobgroups " \
                  "where gid = %s) and param = 'MACHINES_REQUIRED') m on " \
                  "s.jobid = m.jobid left join tbljobgroups jg on s.jobid = " \
                  "jg.jobid where gid = %s;"
            params = ("SR" + suiterun, "SR" + suiterun, "SR" + suiterun, "SR" + suiterun)
            cur = db.cursor()
            try:
                cur.execute(sql, params)
                descs = []
                while True:
                    rc = cur.fetchone()
                    if not rc:
                        break
                    jobid = rc[0]
                    if rc[1] and rc[2] and rc[1].strip() and rc[2].strip():
                        duration = time.mktime(time.strptime(\
                            rc[2].strip(), "%a %b %d %H:%M:%S %Y %Z")) - \
                            time.mktime(time.strptime(\
                            rc[1].strip(), "%a %b %d %H:%M:%S %Y %Z"))
                    else:
                        duration = None
                    if rc[3] and rc[3].strip():
                        machines = int(rc[3])
                    else:
                        machines = 1
                    jobdesc = rc[4].strip()
                    descs.append(jobdesc)
                    if duration:
                        durtxt = "%u" % (int(duration))
                    else:
                        durtxt = ""
                    out += "RES_%s=%u,%s,%u\n" % (jobdesc, jobid, durtxt, machines)
                out += "JOBDESCS=%s\n" % (string.join(descs, ","))
            finally:
                cur.close()

        else:
            sql = "SELECT j.jobid, g.description, j.jobstatus from tbljobgroups g INNER JOIN tbljobs j ON j.jobid = g.jobid WHERE g.gid=%s"
            cur = db.cursor()
            try:
                cur.execute(sql, ["SR" + suiterun])
                while True:
                    rc = cur.fetchone()
                    if not rc:
                        break
                    out += "%-8s %-15s %s\n" % (rc[0], rc[1], rc[2])
            finally:
                cur.close()

        return out 

PageFactory(XenRTSuiteStatus, "/api/suite/status", compatAction="suitestatus")
