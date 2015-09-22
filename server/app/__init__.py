from server import Page
import app.db
import app.ad
import app.acl
import app.user
import config
import time
from pyramid.httpexceptions import *

class XenRTPage(Page):
    WRITE = False
    WAIT = True
    DB_SYNC_CHECK_START_INTERVAL = 0.1
    DB_SYNC_CHECK_MAX_ATTEMPTS = 10
    REQUIRE_AUTH = False
    REQUIRE_AUTH_IF_ENABLED = False
    ALLOW_FAKE_USER = True

    def __init__(self, request):
        super(XenRTPage, self).__init__(request)
        self._db = None
        self._ad = None
        self._acl = None
        self._user = {}

    def matchdict(self, param):
        return self.request.matchdict[param].replace("%2F", "/")

    def getUserFromAPIKey(self, apiKey):
        return app.user.User.fromApiKey(self, apiKey)

    def getUserFromJWT(self, token):
        user = app.user.User.fromJWT(self, token)
        if user.valid:
            self.request.response.set_cookie("apikey", self.user.apiKey)
            return user
        else:
            return None

    def getUser(self, forceReal=False):
        if self._user.get(forceReal):
            return self._user[forceReal]

        lcheaders = dict([(k.lower(), v)  for (k,v) in self.request.headers.iteritems()])
        user = None
        if "jwt" in self.request.GET:
            user = self.getUserFromJWT(self.request.GET['jwt'])
        if not user and "apikey" in self.request.cookies:
            user = self.getUserFromAPIKey(self.request.cookies['apikey'])
        if not user and "x-api-key" in lcheaders:
            user = self.getUserFromAPIKey(lcheaders['x-api-key'])
        if not user and "apikey" in self.request.GET:
            user = self.getUserFromAPIKey(self.request.GET['apikey'])
        if not user:
            user = lcheaders.get("x-forwarded-user", "")
            if user == "(null)" or not user:
                user = None
            else:
                user = app.user.User(self, user.split("@")[0])
        
        if not user:
            return None

        if "x-fake-user" in lcheaders and not forceReal:
            if self.ALLOW_FAKE_USER: 
                fakeUser = app.user.User(self, lcheaders['x-fake-user'])
                if fakeUser.valid or True:
                    self._user[forceReal] = fakeUser
                    return fakeUser
            raise HTTPForbidden()

        self._user[forceReal] = user
        return user

    def _isValidGroup(self, name):
        db = self.getDB()
        cur = db.cursor()
        cur.execute("SELECT groupid FROM tblgroups WHERE name=%s", [name])
        rc = cur.fetchone()
        if rc:
            return True
        # Might be a new group
        if self.getAD().is_valid_group(name):
            # Cache the group members
            db = self.getWriteDB()
            cur = db.cursor()
            cur.execute("INSERT INTO tblgroups (name) VALUES (%s) RETURNING groupid", [name])
            rc = cur.fetchone()
            groupid = rc[0]
            members = self.getAD().get_all_members_of_group(name)
            for m in members:
                cur.execute("INSERT INTO tblgroupusers (groupid, userid) VALUES (%s, %s)", [groupid, m])
            db.commit()
            return True
        return False

    def validateAndCache(self, objectType, userid):
        if objectType == "user":
            return app.user.User(self, userid).valid
        elif objectType == "group":
            return self._isValidGroup(userid)
        else:
            raise Exception("Invalid object type")

    def renderWrapper(self):
        user = self.getUser()
        if (not user or user.disabled) and (self.REQUIRE_AUTH or (self.REQUIRE_AUTH_IF_ENABLED and config.auth_enabled == "yes")):
            if user and user.disabled:
                return HTTPUnauthorized("Your account is disabled")
            return HTTPUnauthorized()
        try:
            ret = self.render()
            return ret
        finally:
            try:
                if self.WRITE and self.WAIT:
                    self.waitForLocalWrite()
            finally:
                if self._db:
                    self._db.rollback()
                    self._db.close()

    def waitForLocalWrite(self):
        assert self.WRITE
        writeDb = self.getDB()
        writeDb.rollback()
        writeLoc = app.db.getWriteLocation(writeDb)
        readDb = app.db.dbReadInstance()
        i = 0
        interval = self.DB_SYNC_CHECK_START_INTERVAL
        while i < (self.DB_SYNC_CHECK_MAX_ATTEMPTS):
            # Get the current xlog replay location from the local DB. This returns none if the local DB is the master
            if app.db.getWriteLocation(readDb):
                print "Local database is master, don't need to wait for sync"
                # This means the local database is the master, so we can stop
                break
            readLoc = app.db.getReadLocation(readDb)
            print "Checking whether writes have synced, attempt %d - write=%s, read=%s" % (i, str(writeLoc), str(readLoc))
            if readLoc >= writeLoc:
                break
            i += 1
            time.sleep(interval)
            interval *= 2
        readDb.rollback()
        readDb.close()

    def getDB(self):
        if not self._db:
            if self.WRITE:
                self._db = app.db.dbWriteInstance()
            else:
                self._db = app.db.dbReadInstance()
        return self._db

    def getWriteDB(self):
        if not self.WRITE:
            self.WRITE = True
            self._db = None
        return self.getDB()

    def getAD(self):
        if not self._ad:
            self._ad = app.ad.ActiveDirectory()
        return self._ad

    def getACLHelper(self):
        if not self._acl:
            self._acl = app.acl.ACLHelper(self)
        return self._acl

    def lookup_jobid(self, detailid):
        reply = -1
        cur = self.getDB().cursor()

        cur.execute("SELECT jobid from tblResults WHERE detailid = %s", 
                    [int(detailid)])

        rc = cur.fetchone()
        if rc and rc[0]:
            reply = int(rc[0])

        cur.close()

        return reply

    def get_job(self, id):

        cur = self.getDB().cursor()    
        d = {}
        cur.execute("SELECT jobid, version, revision, options, jobStatus, "
                    "userId, uploaded, removed, preemptable FROM tbljobs WHERE " +
                    "jobId = %s;", [id])
        rc = cur.fetchone()
        if rc:
            d = app.utils.parse_job(rc,cur)
       
        cur.close()
      
        return d
    
    def lookup_detailid(self, jobid, phase, test):

        reply = -1
     
        db = self.getDB()

        cur = db.cursor()

        cur.execute("SELECT detailid from tblResults WHERE jobid = %s AND "
                    "phase = %s AND test = %s", [jobid, phase, test])

        rc = cur.fetchone()
        if rc and rc[0]:
            reply = int(rc[0])
            
        cur.close()

        return reply

import app.api
import app.apiv2
import app.ui
import app.uiv2
import app.compat
import app.signal
