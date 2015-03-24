from app.api import XenRTAPIPage
from server import PageFactory

import xml.dom.minidom, string, traceback, time

import app.utils

class XenRTSubResults(XenRTAPIPage):
    WRITE = True

    def render(self):
        form = self.request.params
        """Parse XML to update tblSubResults"""
        try:
            jobid = form["jobid"]
            phase = form["phase"]
            test = form["test"]
            db = self.getDB()
            cur = db.cursor()

            detailid = self.lookup_detailid(int(jobid), phase, test)
            if detailid == -1:
                cur.execute("INSERT INTO tblResults (jobid, phase, test, result) " \
                            "VALUES (%s, %s, %s, %s);",
                            [jobid, phase, test, "unknown"])
                detailid = self.lookup_detailid(int(jobid), phase, test)
            try:
                fh = self.request.POST["file"].file
                x = xml.dom.minidom.parse(fh)
                fh.close()
            except:
                x = xml.dom.minidom.parseString(form["file"])
            for n in x.childNodes:
                if not n.nodeType == n.ELEMENT_NODE or \
                       not n.localName == "results":
                    continue
                for t in n.childNodes:
                    if not t.nodeType == t.ELEMENT_NODE or \
                           not t.localName == "test":
                        continue
                    for g in t.childNodes:
                        if not g.nodeType == g.ELEMENT_NODE or \
                               not g.localName == "group":
                            continue
                        gname = "DEFAULT"
                        for i in g.childNodes:
                            if i.nodeType == i.ELEMENT_NODE and \
                                   i.localName == "name":
                                for a in i.childNodes:
                                    if a.nodeType == a.TEXT_NODE:
                                        gname = string.strip(str(a.data))
                            elif i.nodeType == i.ELEMENT_NODE and \
                                     i.localName == "test":
                                tname = "DEFAULT"
                                result = "unknown"
                                reason = ""
                                for j in i.childNodes:
                                    if j.nodeType == j.ELEMENT_NODE and \
                                           j.localName == "name":
                                        for a in j.childNodes:
                                            if a.nodeType == a.TEXT_NODE:
                                                tname = string.strip(\
                                                    str(a.data))
                                    elif j.nodeType == j.ELEMENT_NODE and \
                                           j.localName == "state":
                                        for a in j.childNodes:
                                            if a.nodeType == a.TEXT_NODE:
                                                result = string.strip(\
                                                    str(a.data))
                                    elif j.nodeType == j.ELEMENT_NODE and \
                                           j.localName == "reason":
                                        for a in j.childNodes:
                                            if a.nodeType == a.TEXT_NODE:
                                                reason = string.strip(\
                                                    str(a.data))
                                gname = gname[0:48]
                                tname = tname[0:48]
                                reason = reason[0:48]
                                # Insert this record
                                cur.execute("SELECT subid from tblSubResults " \
                                            "WHERE detailid = %s AND subgroup = " \
                                            "%s AND subtest = %s",
                                            [detailid, gname, tname])
                                rc = cur.fetchone()
                                if rc:
                                    subid = int(rc[0])
                                    cur.execute("UPDATE tblSubResults SET result =" \
                                                " %s, reason = %s WHERE " \
                                                "subid = %s",
                                                [result, reason, subid])
                                else:
                                    cur.execute("INSERT INTO tblSubResults " \
                                                "(detailid, subgroup, subtest, " \
                                                "result, reason) VALUES " \
                                                "(%s, %s, %s, %s, %s)",
                                                [detailid, gname, tname, result, reason])
            db.commit()
            cur.close()        
            return "OK"        
        except:
            traceback.print_exc()
            return "ERROR updating database"    

class XenRTEvent(XenRTAPIPage):
    WRITE = True

    def render(self):
        form = self.request.params
        timenow = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time()))
        if not form.has_key("etype"):
            return "ERROR No event type supplied"
        etype = form["etype"]
        if not form.has_key("subject"):
            return "ERROR No subject supplied"
        subject = form["subject"]
        if not form.has_key("edata"):
            return "ERROR No event data supplied"
        edata = form["edata"]

        db = self.getDB()

        cur = db.cursor()

        try:
            cur.execute("INSERT INTO tblEvents (ts, etype, subject, edata) "
                        "VALUES (%s, %s, %s, %s);",
                        [timenow, etype, subject, edata])
            
            db.commit()
            cur.close()
            return "OK"
        except:
            return "ERROR Database error"

class XenRTLogData(XenRTAPIPage):
    WRITE = True

    def render(self):
        form = self.request.params
        db = self.getDB()
        timenow = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time()))
        if not form.has_key("id"):
            return "ERROR No job ID supplied"
        id = string.atoi(form["id"])
        if not form.has_key("phase"):
            return "ERROR No phase supplied"
        phase = form["phase"]
        if not form.has_key("test"):
            return "ERROR No test supplied"
        test = form["test"]
        if not form.has_key("key"):
            return "ERROR No key supplied"
        key = form["key"]
        if not form.has_key("value"):
            return "ERROR No value supplied"
        value = form["value"]

        cur = db.cursor()


        # Make sure we have a result field for this test
        result = ""
        if key == "result":
            result = value
        detailid = 0
        cur.execute("SELECT detailid FROM tblResults " +
                    "WHERE jobid = %s AND phase = %s AND test = %s;",
                    [id, phase, test])
        rc = cur.fetchone()
        if not rc:
            cur.execute("INSERT INTO tblResults (jobid, phase, test, result) "
                        "VALUES (%s, %s, %s, %s);",
                        [id, phase, test, result])
            cur.execute("SELECT detailid FROM tblResults " +
                        "WHERE jobid = %s AND phase = %s AND test = %s;",
                        [id, phase, test])
            rc = cur.fetchone()
            if not rc:
                return "ERROR Could not get detailid for test"
                cur.close()
                db.rollback()
                db.close()
            else:
                detailid = int(rc[0])
        else:
            detailid = int(rc[0])

        if len(key) > 24:
            key = key[0:24]
        if len(value) > 255:
            value = value[0:255]
        cur.execute("INSERT INTO tblDetails (detailid, ts, key, value) "
                    "VALUES (%s, %s, %s, %s);",
                    [detailid, timenow, key, value])

        # If the key was "result" the update the result in tblResult as well
        if key == "result":
            cur.execute("UPDATE tblResults SET result = %s WHERE jobid = %s "
                        "AND phase = %s AND test = %s;",
                        [value, id, phase, test])

        # If the key was "warning" then modify the result in tblResult
        if key == "warning":
            cur.execute("SELECT result FROM tblResults WHERE jobid = %s "
                        "AND phase = %s AND test = %s;",
                        [id, phase, test])
            rc = cur.fetchone()
            if rc and rc[0]:
                result = string.strip(rc[0])
            else:
                result = "unknown"
            if result[-2:] != "/w":
                result = result + "/w"
            cur.execute("UPDATE tblResults SET result = %s WHERE jobid = %s "
                        "AND phase = %s AND test = %s;",
                        [result, id, phase, test])
            
        db.commit()
        cur.close()
        return "OK"

class XenRTSetResult(XenRTAPIPage):
    WRITE = True

    def render(self):
        db = self.getDB()
        form = self.request.params
        timenow = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time()))
        if not form.has_key("id"):
            return "ERROR No job ID supplied"
        id = string.atoi(form["id"])
        if not form.has_key("phase"):
            return "ERROR No phase supplied"
        phase = form["phase"]
        if not form.has_key("test"):
            return "ERROR No test supplied"
        test = form["test"]
        if not form.has_key("result"):
            return "ERROR No result supplied"
        result = form["result"]

        cur = db.cursor()


        cur.execute("SELECT jobid, phase, test, result FROM tblResults "
                    "WHERE jobid = %s AND phase = %s AND test = %s;",
                    [id, phase, test])
        rc = cur.fetchone()
        if not rc:
            cur.execute("INSERT INTO tblResults (jobid, phase, test, result) "
                        "VALUES (%s, %s, %s, %s);",
                        [id, phase, test, result])
        else:
            cur.execute("UPDATE tblResults SET result = %s WHERE jobid = %s "
                        "AND phase = %s AND test = %s;",
                        [result, id, phase, test])

        # Also add to the detailed history
        cur.execute("SELECT detailid FROM tblResults "
                    "WHERE jobid = %s AND phase = %s AND test = %s;",
                    [id, phase, test])
        rc = cur.fetchone()
        if not rc:
            cur.close()
            return "ERROR Could not get detailid for test"
        else:
            detailid = int(rc[0])
            cur.execute(
                "INSERT INTO tblDetails (detailid, ts, key, value) VALUES "
                "(%s, %s, 'result', %s);", [detailid, timenow, result])
            
        db.commit()
        cur.close()
        return "OK"

PD_DLIST = 1
PD_HIDE = 2

# 0 int, 1 char, 2 bool, 3 fp
perfdef = {'jobid': (0, "Job ID", 10, PD_DLIST),
           'jobtype': (1, "Job type", 20, PD_HIDE),
           'perfrun': (2, "Perf run?", 30, PD_HIDE),
           'machine': (1, "Machine", 40, PD_HIDE),
           'productname': (1, "Product", 50, PD_HIDE),
           'productversion': (1, "Version", 60, PD_HIDE),
           'productspecial': (1, "Product special", 70, PD_HIDE),
           'hvarch': (1, "H/v arch", 80, PD_HIDE),
           'dom0arch': (1, "Domain0 arch", 90, PD_HIDE),
           'hostdebug': (2, "Host debug?", 100, PD_HIDE),
           'hostspecial': (1, "Host special", 110, PD_HIDE),
           'guestnumber': (0, "Guest number", 115, PD_HIDE),
           'guestname': (1, "Guest name", 120, PD_HIDE),
           'guesttype': (1, "Guest type", 130, PD_HIDE),
           'domaintype': (1, "Domain type", 140, PD_HIDE),
           'domainflags': (1, "Domain flags", 150, PD_HIDE),
           'guestversion': (1, "Guest OS", 160, PD_HIDE),
           'kernelversion': (1, "Guest kernel", 170, PD_HIDE),
           'kernelproductname': (1, "Guest product", 180, PD_HIDE),
           'kernelproductversion': (1, "Guest product version", 190, PD_HIDE),
           'kernelproductspecial': (1, "Guest product special", 200, PD_HIDE),
           'guestarch': (1, "Guest arch", 210, PD_HIDE),
           'guestdebug': (2, "Guest debug?", 220, PD_HIDE),
           'pvdrivers': (1, "PV drivers?", 230, PD_HIDE),
           'vcpus': (0, "vCPUS", 240, PD_HIDE),
           'memory': (0, "Memory MB", 250, PD_HIDE),
           'storagetype': (1, "Storage type", 260, PD_HIDE),
           'guestspecial': (1, "Guest special", 270, PD_HIDE),
           'alone': (2, "Only guest?", 280, PD_HIDE),
           'benchmark': (1, "Benchmark", 400, PD_HIDE),
           'bmversion': (1, "Benchmark version", 410, PD_HIDE),
           'bmspecial': (1, "Benchmark special", 420, PD_HIDE),
           'metric': (1, "Metric", 500, PD_HIDE),
           'value': (3, "Value", 510, PD_HIDE),
           'units': (1, "Units", 520, PD_HIDE),
           'ts': (4, "Timestamp", 600, PD_HIDE)}

class XenRTPerfData(XenRTAPIPage):
    WRITE = True

    def render(self):
        form = self.request.params
        """Read an uploaded XML file of one or more performance results and place
        into the database."""

        global perfdef
        timenow = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time()))
        db = self.getDB()
        cur = db.cursor()

        try:
            try:
                fh = self.request.POST["file"].file
                x = xml.dom.minidom.parse(fh)
                fh.close()
            except:
                x = xml.dom.minidom.parseString(form["file"])
            for n in x.childNodes:
                if not n.nodeType == n.ELEMENT_NODE or \
                       not n.localName == "performance":
                    continue
                for t in n.childNodes:
                    if not t.nodeType == t.ELEMENT_NODE or \
                           not t.localName == "datapoint":
                        continue
                    dp = {}
                    for g in t.childNodes:
                        if g.nodeType == g.ELEMENT_NODE:
                            for i in g.childNodes:
                                if i.nodeType == i.TEXT_NODE:
                                    dp[str(g.localName)] = \
                                                         string.strip(str(i.data))
                    f = []
                    v = []
                    for dpi in dp.keys():
                        if perfdef.has_key(dpi):
                            f.append(dpi)
                            l, desc, order, flags = perfdef[dpi]
                            if l == 0:
                                v.append(dp[dpi])
                            elif l == 1:
                                v.append(dp[dpi])
                            elif l == 2:
                                if string.lower(dp[dpi][0]) in ("1", "y", "t"):
                                    v.append("TRUE")
                                else:
                                    v.append("FALSE")
                            elif l == 3:
                                v.append(dp[dpi])
                            elif l == 4:
                                v.append(dp[dpi])
                            else:
                                v.append(dp[dpi])
                    sql = "INSERT INTO tblPerf (ts, %s)" % string.join(f, ", ")
                    sql += " VALUES (%s"
                    for val in v:
                        sql += ", %s"
                    sql += ")"
                    v.insert(0, timenow)
                    cur.execute(sql, v)

            db.commit()
            cur.close()
            return "OK"
        except:
            traceback.print_exc()
            return "ERROR updating database"


PageFactory(XenRTSubResults, "/api/results/subresults", compatAction="subresults")
PageFactory(XenRTLogData, "/api/results/logdata", compatAction="logdata")
PageFactory(XenRTEvent, "/api/results/event", compatAction="event")
PageFactory(XenRTSetResult, "/api/results/setresult", compatAction="setresult")
PageFactory(XenRTPerfData, "/api/results/perfdata", compatAction="perfdata")
