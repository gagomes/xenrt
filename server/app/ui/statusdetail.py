from server import PageFactory
from app import XenRTPage

import string
import app.utils

class XenRTStatusFrame(XenRTPage):
    def render(self):
        if not self.request.params.has_key("id"):
            out = "ERROR No job ID supplied"
        else:
            jid = string.atoi(self.request.params["id"])
            parsed = self.get_job(jid)

            if len(parsed) == 0:
                out = "ERROR Could not find job %d" % jid

            else:
                out = "<div id=\"contents-results\"><table>"

                # Print CHECK first (XRT-303)
                if parsed.has_key('CHECK'):
                    out += "<tr><td><b>%s</b></td><td>%s</td></tr>" % \
                          ("CHECK", parsed["CHECK"])
                for key in parsed.keys():
                    if key != "CHECK":
                        out += "<tr><td><b>%s</b></td><td>%s</td></tr>" % \
                              (key, parsed[key])

                out += "</table></div>"

        return {"title": "Job Status", "main": out}

class XenRTDetailFrame(XenRTPage):
    def render(self):
        big = 1

        if not self.request.params.has_key("detailid"):
            raise Exception("No detailid specified")

        detailid = string.atoi(self.request.params["detailid"])


        cur = self.getDB().cursor()
        out = """<div id="contents-results">"""

        cur.execute(("SELECT phase, test, result, jobid FROM tblresults " +
                     "WHERE detailid = %u") % (detailid))                
        rc = cur.fetchone()    
        if rc:
            phase = string.strip(rc[0])
            test = string.strip(rc[1])
            jobid = rc[3]
            out += "<p>%-10s %-12s %-10s</p>" % \
                  (phase, test, string.strip(rc[2]))
        else:
            jobid = None

        cur.execute("SELECT options, version FROM tblJobs WHERE jobid = %u" %
                    (jobid))
        rc = cur.fetchone()
        if rc:
            options = string.strip(rc[0])
            version = string.strip(rc[1])
        else:
            jobid = None

        sql = "SELECT d.ts, d.key, d.value, NULL, NULL, NULL FROM " \
              "tblDetails d  WHERE d.detailid = %u ORDER BY d.ts;" % \
              (detailid)

        cur.execute(sql)
        
        out += """
        <table>
        <tr>
        <td width="100px"><b>Date / Time</b></td>
        <td width="100px"><b>Key</b></td>
        <td><b>Value</b></td>
        </tr>
        """
        while 1:
            rc = cur.fetchone()
            if not rc:
                break
            key = string.strip(rc[1])
            value = string.strip(rc[2])
            if key == "result":
                col = app.utils.colour_tag(value)
            else:
                col = ""
            units = ""
            if rc[3]:
                units = " " + string.strip(rc[3])
            rel = ""
            if rc[4]:
                try:
                    v = float(rc[4]) * 100
                    if v < 0:
                        rel = " (-%.2f%%)" % (abs(v))
                    else:
                        rel = " (+%.2f%%)" % (v)
                except:
                    pass
            
            keydisp = key
            out += "<tr><td>%s</td><td>%s</td><td %s>%s%s%s</td></tr>" % \
                  (rc[0].strftime("%Y-%m-%d %H:%M:%S"), keydisp, col, value, units, rel)
                   
        out += "</table>"

        cur.close()
        return {"title": "Job Detail", "main": out}

PageFactory(XenRTStatusFrame, "/statusframe", renderer="__main__:templates/default.pt")
PageFactory(XenRTDetailFrame, "/detailframe", renderer="__main__:templates/default.pt")
