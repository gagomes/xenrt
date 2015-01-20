from server import PageFactory
from app import XenRTPage
import app.utils


import string,re,StringIO


class XenRTMatrix(XenRTPage):
    def render(self):
        cur = self.getDB().cursor()
        query = []
        jobiddesc = {}
        joborder = []
        hdgdepth = 1
        maxjobs = 50


        out = ""
        if self.request.params.has_key("jobs"):
            jobs = self.request.params["jobs"].split(",")
        else:
            jobs = [str(self.lookup_jobid(self.request.params["detailid"]))]
        out += "<table border=0><tr>"
        for job in jobs:
            out += "<td valign=\"top\">"
            querystr = "SELECT uploaded FROM tblJobs WHERE jobid=%s" % job
            cur.execute(querystr)
            rc = cur.fetchone()
            if not rc:
                raise Exception("Job does not exist")
        
            out += "<h2>Job %s" % job
            out += " (<a href=\"statusframe?id=%s\" target=\"jobdesc\">details</a>" % job
            if rc[0]:
                out += "- <a href=\"logs/job/%s/browse\" target=\"_blank\">logs</a>" % job
            out += ")</h2>"



            cur.execute("SELECT r.phase, r.test, r.result, "
                        "r.detailid, r.uploaded "
                        "FROM tblresults r "
                        "WHERE r.jobid = %s ORDER BY r.detailid" %
                        (job))
            out += "<table>"

            while 1:
                rc = cur.fetchone()
                if not rc:
                    break
                p = string.strip(rc[0])
                if rc[1]:
                    t = string.strip(rc[1])
                else:
                    t = ""
                if not rc[2]:
                    r = ""
                else:
                    r = string.strip(rc[2])
                d = string.strip(`rc[3]`)
                if rc[4]:
                    u = string.strip(rc[4])
                else:
                    u = ""

                out += "<tr><td>%s/%s</td><td style=\"%s\">%s</td><td><td><a href=\"detailframe?detailid=%s\" target=\"testdesc\">Details</a></td>\n" % (p, t, app.utils.colour_style(r), r, d)
                if u:
                    out += "<td><a href=\"logs/test/%s/browse\" target=\"_blank\">Logs</a></td>" % d
                else:
                    out += "<td></td>"
            out += "</table></td>"
        out += "</tr></table>"
        return {"title": "Matrix", "main": out}

PageFactory(XenRTMatrix, "/matrix", renderer="__main__:templates/default.pt")
