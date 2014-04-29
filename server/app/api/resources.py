from server import PageFactory
from app.api import XenRTAPIPage

import traceback, StringIO, string, time, random, pgdb, json

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
                self.mutex = pgdb.connect(config.dbConnectString)
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
    def doRender(self):
        self.get_lock()
        ret = {}
        try: 
            restype = self.request.params['type']
            site = self.request.params['site']
            jobid = self.request.params['job']

            cur = self.getDB().cursor()
            cur.execute("SELECT name,data,site FROM tblresources WHERE type='%s' AND status='idle'" % restype)
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
                cur.execute("UPDATE tblresources SET status='locked',jobid=%d WHERE name='%s'" % (int(jobid), available[0]['name']))
                self.getDB().commit()
                ret = available[0]
        finally:
            self.release_lock()
        return json.dumps(ret)

class XenRTReleaseResource(XenRTResourcePage):
    def doRender(self):
        self.get_lock()
        ret = ""
        try: 
            cur = self.getDB().cursor()
            if "job" in self.request.params:
                cur.execute("UPDATE tblresources SET status='idle' WHERE jobid=%d AND status='locked'" % int(self.request.params['job']))
            else:
                cur.execute("UPDATE tblresources SET status='idle' WHERE name='%s' AND status='locked'" % self.request.params['name'])
            self.getDB().commit()
            ret = "OK"
        finally:
            self.release_lock()
        return ret


PageFactory(XenRTLockResource, "lockresource", "/api/resources/lock", contentType="application/json", compatAction="lockresource")
PageFactory(XenRTReleaseResource, "releaseresource", "/api/resources/release", contentType="text/plain", compatAction="releaseresource")

