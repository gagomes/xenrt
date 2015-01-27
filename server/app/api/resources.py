from server import PageFactory
from app.api import XenRTAPIPage

import traceback, StringIO, string, time, random, json

import config, app
class XenRTResourcePage(XenRTAPIPage):

    def __init__(self, request):
        super(XenRTResourcePage, self).__init__(request)
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

class XenRTLockResource(XenRTResourcePage):
    WRITE = True

    def doRender(self):
        self.get_lock()
        ret = {}
        try: 
            restype = self.request.params['type']
            site = self.request.params['site']
            jobid = self.request.params['job']

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
                cur.execute("UPDATE tblresources SET status='locked',jobid=%s WHERE name=%s", [int(jobid), available[0]['name']])
                self.getDB().commit()
                ret = available[0]
        finally:
            self.release_lock()
        return json.dumps(ret)

class XenRTReleaseResource(XenRTResourcePage):
    WRITE = True

    def doRender(self):
        self.get_lock()
        ret = ""
        try: 
            cur = self.getDB().cursor()
            if "job" in self.request.params:
                cur.execute("UPDATE tblresources SET status='idle' WHERE jobid=%s AND status='locked'", [int(self.request.params['job'])])
            else:
                cur.execute("UPDATE tblresources SET status='idle' WHERE name=%s AND status='locked'", [self.request.params['name']])
            self.getDB().commit()
            ret = "OK"
        finally:
            self.release_lock()
        return ret

class XenRTListResources(XenRTAPIPage):
    def render(self):
        ret = ""
        cur = self.getDB().cursor()
        cur.execute("SELECT name,site,status,jobid,type FROM tblresources")
        fmt = "%-12s %-8s %-8s %-8s\n"
        if not self.request.params.has_key("quiet"):
            ret += fmt % ("Resource", "Site", "Status", "Type")
            ret += "====================================================================\n"
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            name = rc[0].strip()
            if rc[1]:
                site = rc[1].strip()
            else:
                site="(all)"
            if rc[2] == "locked":
                job = "%d" % rc[3]
            else:
                job = "idle"
            restype = rc[4].strip()
            ret += fmt % (name, site, job, restype) 
        return ret

class XenRTResource(XenRTAPIPage):
    def render(self):
        ret = ""
        cur = self.getDB().cursor()
        cur.execute("SELECT name, site, status, jobid, type, data FROM tblresources WHERE name=%s", [self.request.params['resource']])

        rc = cur.fetchone()
        ret = {}
        if rc:
            ret['name'] = rc[0].strip()
            if rc[1]:
                ret['site'] = rc[1].strip()
            else:
                ret['site'] = None
            ret['status'] = rc[2].strip()
            ret['jobid'] = rc[3]
            ret['type'] = rc[4].strip()
            ret['data'] = json.loads(rc[5])
        return json.dumps(ret)

        

PageFactory(XenRTLockResource, "/api/resources/lock", contentType="application/json", compatAction="lockresource")
PageFactory(XenRTReleaseResource, "/api/resources/release", contentType="text/plain", compatAction="releaseresource")
PageFactory(XenRTListResources, "/api/resources/list", contentType="text/plain", compatAction="resourcelist")
PageFactory(XenRTResource, "/api/resources/details", contentType="application/json", compatAction="resource")

