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

        if self.request.params.has_key("jobs") or self.request.params.has_key("detailid"):
            if self.request.params.has_key("jobs"):
                joblist = self.request.params["jobs"]
            else:
                joblist = str(self.lookup_jobid(self.request.params["detailid"]))
            for j in string.split(joblist, ","):
                ll = string.split(j, ":", 1)
                if len(ll) == 2:
                    joborder.append(`string.atoi(ll[0])`)
                    jobiddesc[`string.atoi(ll[0])`] = \
                            string.split(string.strip(ll[1]), "&")
                    if len(jobiddesc[`string.atoi(ll[0])`]) > hdgdepth:
                        hdgdepth = len(jobiddesc[`string.atoi(ll[0])`])
                elif len(ll) == 1:
                    joborder.append(`string.atoi(ll[0])`)
            if len(joborder) > 0:
                query.append("jobid in (%s)" % (string.join(joborder, ",")))
            
        querystr = "SELECT jobid, uploaded FROM tblJobs"
        if len(query) > 0:
            querystr = querystr + " WHERE " + string.join(query, " AND ")
        querystr = querystr + " ORDER BY jobid;"
        cur.execute(querystr)
        id2 = []
        jobdata = {}
        while 1:
            rc = cur.fetchone()
            if not rc:
                break
            jobid = "%s" % (rc[0])
            id2.append(jobid)
            jobdata[jobid] = {}
            if rc[1]:
                jobdata[jobid]["UPLOADED"] = string.strip(rc[1])
        ids = string.join(id2, ",")

        out = """<div id="tableContainer">"""

        # Get phase/test membership
        cur.execute("SELECT phase, test, phasedesc, testdesc FROM " +
                    "qryphasetests;")
        phases = []
        phase = None
        desc = ""
        plast = ""
        tlast = ""
        while 1:
            rc = cur.fetchone()
            if not rc:
                break
            p = string.strip(rc[0])
            t = string.strip(rc[1])
            if plast == p and tlast == t:
                continue
            plast = p
            tlast = t
            if rc[2]:
                pd = string.strip(rc[2])
            else:
                pd = ""
            if rc[3]:
                td = string.strip(rc[3])
            else:
                td = ""
            if not phase or p != phase:
                if phase:
                    phases.append((phase, tests, desc))
                desc = pd
                phase = p
                tests = []
            tests.append((t, td))
        if tests:
            phases.append((phase, tests, desc))

        # Get data for select job ids - santise the ID list first
        idlist = string.split(ids, ",")
        jobs = []
        for id in idlist:
            try:
                i = int(id)
                jobs.append(`i`)
            except ValueError:
                pass
        # Cap the number of jobs to display
        if len(jobs) > maxjobs:
            jobs = jobs[0-maxjobs:]
        idlist = string.join(jobs, ",")
        data = {}
        if idlist != "":
            cur.execute("SELECT r.jobid, r.phase, r.test, r.result, "
                        "r.detailid, r.uploaded, NULL AS worst "
                        "FROM qryResults r "
                        "WHERE r.jobid IN (%s) ORDER BY r.jobid;" %
                        (idlist))

            while 1:
                rc = cur.fetchone()
                if not rc:
                    break
                j = string.strip(`rc[0]`)
                p = string.strip(rc[1])
                if rc[2]:
                    t = string.strip(rc[2])
                else:
                    t = ""
                if not rc[3]:
                    r = ""
                else:
                    r = string.strip(rc[3])
                d = string.strip(`rc[4]`)
                if rc[5]:
                    u = string.strip(rc[5])
                else:
                    u = ""
                if rc[6]:
                    try:
                        rs = float(rc[6])
                    except:
                        rs = None
                else:
                    rs = None
                if not data.has_key(p):
                    data[p] = {}
                if not data[p].has_key(t):
                    data[p][t] = {}
                data[p][t][j] = (r, d, u, rs)

        # jobs is a list of jobids that we are actually going to display, in
        # in increasing order of id. joborder is the order specified on the job
        # list on the CGI query. These do no necessarily contain the same items
        if len(joborder) > 0:
            neworder = []
            # Remove any items from joborder not in jobs
            for j in joborder:
                if j in jobs:
                    neworder.append(j)
            # Append any items in jobs but not in joborder
            for j in jobs:
                if not j in neworder:
                    neworder.append(j)
            jobs = neworder

        # Prepare and tidy up the descriptions so that we have a jobiddesc
        # entry for every job and the number if items in the list matches
        # hdgdepth. Then work out the colspans for the higher level headings.
        # The order of the list is lowest level first
        prev = None
        colspans = []
        rng = range(hdgdepth)
        rng.reverse()
        for i in rng: 
            colspans.append([])
        for j in jobs:
            if not jobiddesc.has_key(j):
                jobiddesc[j] = [j]
            while len(jobiddesc[j]) < hdgdepth:
                jobiddesc[j].append('')

            anynew = 0
            for d in rng:
                if not prev or jobiddesc[j][d] != prev[d]:
                    colspans[d].append([0, jobiddesc[j][d]])
                    prev = None
                colspans[d][-1][0] = colspans[d][-1][0] + 1

            prev = jobiddesc[j]
        
        # Build the matrix
        m = Matrix()
        colspans.reverse()
        m.setColumns(colspans)
        m.setJobs(jobs)
        m.setJobData(jobdata)

        for phaset in phases:
            phase, tests, pdesc = phaset
            rg = m.addRowGroup(phase, pdesc)        
            for testt in tests:
                test, tdesc = testt
                row = rg.addRow(test, tdesc)

                for j in jobs:
                    try:
                        result, detailid, upld, rs = data[phase][test][j]
                        cell = row.addCell(j)
                        cell.setResult(result)
                        cell.setDetailID(detailid)
                        if upld == "yes":
                            cell.setUploaded()
                    except KeyError:
                        pass
        
        f = StringIO.StringIO()
        m.render(f)
        out += f.getvalue()
        f.close()
        out += "</div>"

        cur.close()

        return {"title": "Matrix", "main": out}

class MatrixCell:
    def __init__(self, row):
        self.row = row
        self.result = None
        self.warning = False
        self.detailid = None
        self.uploaded = False
        self.relative = ""

    def setResult(self, r):
        self.result = r

    def setDetailID(self, d):
        self.detailid = d

    def setRelative(self, r):
        self.relative = r

    def setWarning(self, w=True):
        self.warning = w
        
    def setUploaded(self, u=True):
        self.uploaded = u

    def isActive(self):
        if self.detailid:
            return True
        return False

    def render(self, fd):
        if not self.isActive():
            matrixCellRenderEmpty(fd)
            return
        col = app.utils.colour_style(self.result, rswarn=self.warning)
        fd.write("<td class=\"results-cell\">"
                 "  <table class=\"results-innertable\">"
                 "    <tr><td style='%s'>"
                 "      <a href=\"detailframe?detailid=%s\" "
                 "         target=\"testdesc\" class=\"info\">D</a>" %
                 (col, self.detailid))
        if self.uploaded:
            fd.write(" <a href=\"logs/test/%s/browse\" target=\"_blank\">L</a>" % (self.detailid))
        fd.write("%s<br><b>%s</b></td></tr></table></td>" % (self.relative, self.result))

def matrixCellRenderEmpty(fd):
        fd.write("<td></td>")

class MatrixRow:
    def __init__(self, rowgroup, title, desc):
        self.rowgroup = rowgroup
        self.title = title
        self.desc = desc
        self.cells = {}

    def addCell(self, jobid):
        c = MatrixCell(self)
        self.cells[jobid] = c
        return c

    def isActive(self):
        count = 0
        for c in self.cells.values():
            if c.isActive():
                count = count + 1
        return count

    def render(self, fd, tdopen, jobids):
        if not self.isActive():
            return tdopen
        if not tdopen:
            fd.write("<tr>")
            tdopen = True
        fd.write("<th class=\"column-row-header\">")
        fd.write("<a class=\"info\">%s" % (self.title))
        fd.write("<span>%s</span>" % (self.desc))
        fd.write("</a></th>")
        for j in jobids:
            if self.cells.has_key(j):
                self.cells[j].render(fd)
            else:
                matrixCellRenderEmpty(fd)
        fd.write("</tr>\n")
        tdopen = False
        return tdopen

class MatrixRowGroup:
    def __init__(self, matrix, title, desc):
        self.matrix = matrix
        self.title = title
        self.desc = desc
        self.rows = {}
        self.rowsOrder = []

    def addRow(self, title, desc):
        if not self.rows.has_key(title):
            r = MatrixRow(self, title, desc)
            self.rows[title] = r
            self.rowsOrder.append(title)
        return self.rows[title]

    def isActive(self):
        count = 0
        for rt in self.rowsOrder:
            if self.rows[rt].isActive():
                count = count + 1
        return count

    def render(self, fd, jobids):
        rows = self.isActive()
        if not rows:
            return
        fd.write("<tr><th rowspan=\"%u\" class=\"column-row-header\">" %
                 (rows))
        fd.write("<a class=\"info\">%s" % (self.title))
        fd.write("<span>%s</span>" % (self.desc))
        fd.write("</a></th>")
        tdopen = True
        for rt in self.rowsOrder:
            tdopen = self.rows[rt].render(fd, tdopen, jobids)

class Matrix:
    """Represents a results matrix to be displayed using HTML"""
    def __init__(self):
        self.columns = None
        self.jobs = None
        self.rowgroups = {}
        self.rowgroupsOrder = []

    def setColumns(self, c):
        self.columns = c

    def setJobs(self, j):
        self.jobs = j

    def setJobData(self, j):
        self.jobdata = j

    def addRowGroup(self, title, desc):
        if not self.rowgroups.has_key(title):
            rg = MatrixRowGroup(self, title, desc)
            self.rowgroups[title] = rg
            self.rowgroupsOrder.append(title)
        return self.rowgroups[title]
        
    def render(self, fd):
        fd.write("<table id=\"results-grid\">\n")
        for c in self.columns:
            fd.write("<tr><td colspan=\"2\"></td>")
            for cell in c:
                # See if this looks like a build number - if it does, link to xenbuilder
                text = cell[1]
                m = re.search("\-(\d*)", text)
                if m:
                    text = "<a href=\"http://xenbuilder.uk.xensource.com/builds?q_view=details&q_number=%s\" target=\"_blank\">%s</a>" % (m.group(1), text)
                fd.write("<th colspan=\"%u\"><span style=\"color: white;\">"
                         "%s</span></td>" % (cell[0], text))
            fd.write("</tr>\n")
    
        fd.write("<tr><td colspan=\"2\"></td>")
        for j in self.jobs:
            fd.write("<th><a href=\"statusframe?id=%s\" "
                     "target=\"jobdesc\" class=\"info\">D</a>" % (j))
            if self.jobdata.has_key(j) and \
                   self.jobdata[j].has_key("UPLOADED") and \
                   self.jobdata[j]["UPLOADED"] == "yes":
                fd.write(" <a href=\"logs/job/%s/browse\" target=\"_blank\">L</a>" % (j))
            else:
                fd.write("&nbsp;")
            fd.write("</th>")
        fd.write("</tr>\n")

        for rgtitle in self.rowgroupsOrder:
            self.rowgroups[rgtitle].render(fd, self.jobs)
        
        fd.write("</table>\n")

PageFactory(XenRTMatrix, "matrix", "/matrix", renderer="__main__:templates/default.pt")
