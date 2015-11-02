from app.apiv2 import *

import xml.dom.minidom, string, time

import app.utils
from pyramid.httpexceptions import *
import json
import jsonschema
import calendar
import time
import datetime

class UploadSubResults(XenRTAPIv2Page):
    WRITE = True
    CONSUMES = "multipart/form-data"
    PATH = "/job/{id}/tests/{phase}/{test}/subresults"
    REQTYPE = "POST"
    SUMMARY = "Add sub results to a test from an XML file"
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'Job ID to add subresults to',
         'type': 'integer'},
        {'name': 'phase',
         'in': 'path',
         'required': True,
         'description': 'Test phase to add subresults to',
         'type': 'string'},
        {'name': 'test',
         'in': 'path',
         'required': True,
         'description': 'Testcase to add subresults to',
         'type': 'string'},
        {'name': 'file',
         'in': 'formData',
         'required': True,
         'description': 'File to upload',
         'type': 'file'}]
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["backend"]
    OPERATION_ID="upload_subresults"

    def render(self):
        """Parse XML to update tblSubResults"""
        jobid = self.request.matchdict['id']
        phase = self.matchdict('phase')
        test = self.matchdict('test')

        db = self.getDB()
        cur = db.cursor()

        detailid = self.lookup_detailid(int(jobid), phase, test)
        if detailid == -1:
            cur.execute("INSERT INTO tblResults (jobid, phase, test, result) " \
                        "VALUES (%s, %s, %s, %s);",
                        [jobid, phase, test, "unknown"])
            detailid = self.lookup_detailid(int(jobid), phase, test)
        
        fh = self.request.POST["file"].file
        x = xml.dom.minidom.parse(fh)
        fh.close()
        
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
        return {} 

class NewEvent(XenRTAPIv2Page):
    WRITE = True
    PATH = "/events"
    REQTYPE = "POST"
    SUMMARY = "Add an event to the database"
    PARAMS = [
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the lease required',
         'schema': { "$ref": "#/definitions/event" }
        }]
    DEFINITIONS = { "event": {
             "title": "Lease details",
             "type": "object",
             "required": ["event_type", "subject", "data"],
             "properties": {
                "event_type": {
                    "type": "string",
                    "description": "Event type"},
                "subject": {
                    "type": "string",
                    "description": "Subject"},
                "data": {
                    "type": "string",
                    "description": "Data"}
                }
            }
        }
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["backend"]
    OPERATION_ID="new_event"
    PARAM_ORDER = ["event_type", "subject", "data"]

    def render(self):
        try: 
            params = json.loads(self.request.body)
            jsonschema.validate(params, self.DEFINITIONS['event'])
        except Exception, e:
            raise XenRTAPIError(self, HTTPBadRequest, str(e).split("\n")[0])
        timenow = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time()))
        etype = params["event_type"]
        subject = params["subject"]
        edata = params["data"]

        db = self.getDB()

        cur = db.cursor()

        cur.execute("INSERT INTO tblEvents (ts, etype, subject, edata) "
                    "VALUES (%s, %s, %s, %s);",
                    [timenow, etype, subject, edata])
        
        db.commit()
        cur.close()
        return {}

class GetEvents(XenRTAPIv2Page):
    PATH = "/events"
    REQTYPE = "GET"
    SUMMARY = "Get events from the database"
    PARAMS = [
        {'name': 'subject',
         'description': 'Event subject - can specify multiple',
         'collectionFormat': 'multi',
         'in': 'query',
         'items': 'string',
         'required': True,
         'type': 'array'},
        {'name': 'type',
         'collectionFormat': 'multi',
         'description': 'Event type - can specify multiple',
         'in': 'query',
         'items': 'string',
         'required': True,
         'type': 'array'},
        {'name': 'start',
         'description': 'Start of range',
         'in': 'query',
         'required': False,
         'type': 'integer'},
        {'name': 'end',
         'description': 'End of range. Defaults to now',
         'in': 'query',
         'required': False,
         'type': 'integer'},
        {'name': 'limit',
         'description': 'Limit on number of events returned. Hard limit 10000',
         'in': 'query',
         'required': False,
         'type': 'integer'}]
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["misc"]

    def render(self):
        subject = self.getMultiParam("subject")
        if not subject:
           raise XenRTAPIError(self, HTTPBadRequest, "No subject specified") 
        etype = self.getMultiParam("type")
        if not etype:
           raise XenRTAPIError(self, HTTPBadRequest, "No event type specified") 
        start = self.request.params.get('start')
        start = int(start) if start else None
        end = self.request.params.get('end')
        end = int(end) if end else None
        limit = self.request.params.get('limit', 0)
        if limit == 0:
            limit = 10000
        limit = min(10000, int(limit))

        params = []
        conditions = []

        conditions.append("etype IN (%s)" % (", ".join(["%s"] * len(etype))))
        params.extend(etype)
        
        conditions.append("subject IN (%s)" % (", ".join(["%s"] * len(subject))))
        params.extend(subject)

        if start:
            conditions.append("ts >= %s")
            params.append(datetime.datetime.utcfromtimestamp(start))
        if end:
            conditions.append("ts <= %s")
            params.append(datetime.datetime.utcfromtimestamp(end))

        params.append(limit)

        cur = self.getDB().cursor()
        cur.execute("SELECT ts,etype,subject,edata FROM tblevents WHERE %s ORDER BY ts DESC LIMIT %%s" % (" AND ".join(conditions)), self.expandVariables(params))


        ret = []
        while True:
            rc = cur.fetchone()
            if not rc:
                break

            ret.append({
                "ts": calendar.timegm(rc[0].timetuple()),
                "type": rc[1].strip() if rc[1] else None,
                "subject": rc[2].strip() if rc[2] else None,
                "data": rc[3].strip() if rc[3] else None})

        return ret
        


class NewLogData(XenRTAPIv2Page):
    WRITE = True
    PATH = "/job/{id}/tests/{phase}/{test}/logdata"
    REQTYPE = "POST"
    SUMMARY = "Add log data to a test"
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'Job ID to add result to',
         'type': 'integer'},
        {'name': 'phase',
         'in': 'path',
         'required': True,
         'description': 'Test phase to add result to',
         'type': 'string'},
        {'name': 'test',
         'in': 'path',
         'required': True,
         'description': 'Testcase to add result to',
         'type': 'string'},
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the log data',
         'schema': { "$ref": "#/definitions/logdata" }
        }]
    DEFINITIONS = { "logdata": {
             "title": "Log data",
             "type": "object",
             "required": ["key", "value"],
             "properties": {
                "key": {
                    "type": "string",
                    "description": "Log data key"},
                "value": {
                    "type": "string",
                    "description": "Log data value"}
                }
            }
        }
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["backend"]
    OPERATION_ID="new_logdata"
    PARAM_ORDER = ["id", "phase", "test", "key", "value"]

    def render(self):
        try: 
            params = json.loads(self.request.body)
            jsonschema.validate(params, self.DEFINITIONS['logdata'])
        except Exception, e:
            raise XenRTAPIError(self, HTTPBadRequest, str(e).split("\n")[0])
        db = self.getDB()
        timenow = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time()))
        id = string.atoi(self.request.matchdict["id"])
        phase = self.matchdict('phase')
        test = self.matchdict('test')
        key = params["key"]
        value = params["value"]

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
                cur.close()
                db.rollback()
                db.close()
                raise XenRTAPIError(self, HTTPNotFound, "Could not find test in database")
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
        return {}

class SetResult(XenRTAPIv2Page):
    WRITE = True
    PATH = "/job/{id}/tests/{phase}/{test}"
    REQTYPE = "POST"
    SUMMARY = "Set the result of a test"
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'Job ID to add result to',
         'type': 'integer'},
        {'name': 'phase',
         'in': 'path',
         'required': True,
         'description': 'Test phase to add result to',
         'type': 'string'},
        {'name': 'test',
         'in': 'path',
         'required': True,
         'description': 'Testcase to add result to',
         'type': 'string'},
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the lease required',
         'schema': { "$ref": "#/definitions/testresult" }
        }]
    DEFINITIONS = { "testresult": {
             "title": "Lease details",
             "type": "object",
             "required": ["result"],
             "properties": {
                "result": {
                    "type": "string",
                    "description": "Result of the test"}
                }
            }
        }
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["backend"]
    OPERATION_ID="set_result"
    PARAM_ORDER = ["id", "phase", "test", "result"]


    def render(self):
        try: 
            params = json.loads(self.request.body)
            jsonschema.validate(params, self.DEFINITIONS['testresult'])
        except Exception, e:
            raise XenRTAPIError(self, HTTPBadRequest, str(e).split("\n")[0])
        db = self.getDB()
        timenow = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time()))
        id = string.atoi(self.request.matchdict["id"])
        phase = self.matchdict("phase")
        test = self.matchdict("test")
        result = params["result"]

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
            raise XenRTAPIError(self, HTTPNotFound, "Could not find test in database")
        else:
            detailid = int(rc[0])
            cur.execute(
                "INSERT INTO tblDetails (detailid, ts, key, value) VALUES "
                "(%s, %s, 'result', %s);", [detailid, timenow, result])
            
        db.commit()
        cur.close()
        return {}

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

class UploadPerfData(XenRTAPIv2Page):
    WRITE = True
    CONSUMES = "multipart/form-data"
    PATH = "/perfdata"
    REQTYPE = "POST"
    SUMMARY = "Add performance data from XML file"
    PARAMS = [
        {'name': 'file',
         'in': 'formData',
         'required': True,
         'description': 'File to upload',
         'type': 'file'}]
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["backend"]
    OPERATION_ID="upload_perfdata"

    def render(self):
        """Read an uploaded XML file of one or more performance results and place
        into the database."""

        global perfdef
        timenow = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time()))
        db = self.getDB()
        cur = db.cursor()

        fh = self.request.POST["file"].file
        x = xml.dom.minidom.parse(fh)
        fh.close()
        
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
        return {}

RegisterAPI(UploadSubResults)
RegisterAPI(UploadPerfData)
RegisterAPI(SetResult)
RegisterAPI(NewEvent)
RegisterAPI(GetEvents)
RegisterAPI(NewLogData)
