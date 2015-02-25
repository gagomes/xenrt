from server import Page
import app.db
import app.ad
import app.acl
import config
import time
from pyramid.httpexceptions import *

class XenRTPage(Page):
    WRITE = False
    DB_SYNC_CHECK_INTERVAL = 0.1
    REQUIRE_AUTH = False
    REQUIRE_AUTH_IF_ENABLED = False
    ALLOW_FAKE_USER = True

    def __init__(self, request):
        super(XenRTPage, self).__init__(request)
        self._db = None
        self._ad = None
        self._acl = None

    def getUserFromAPIKey(self, apiKey):
        cur = self.getDB().cursor()
        cur.execute("SELECT userid FROM tblusers WHERE apikey=%s", [apiKey])
        rc = cur.fetchone()
        if rc:
            return rc[0]
        return None

    def getUser(self):
        lcheaders = dict([(k.lower(), v)  for (k,v) in self.request.headers.iteritems()])
        user = None
        if "x-api-key" in lcheaders:
            user = self.getUserFromAPIKey(lcheaders['x-api-key'])
        if not user and "apikey" in self.request.GET:
            user = self.getUserFromAPIKey(self.request.GET['apikey'])
        if not user:
            user = lcheaders.get("x-forwarded-user", "")
            if user == "(null)" or not user:
                user = None
            else:
                user = user.split("@")[0]
        
        if not user:
            return None

        if "x-fake-user" in lcheaders:
            if self.ALLOW_FAKE_USER: # and self._isValidUser(lcheaders['x-fake-user']):
                return lcheaders['x-fake-user']
            else:
                raise HTTPForbidden()

        return user

    def _isValidUser(self, userid):
        db = self.getDB()
        cur = db.cursor()
        cur.execute("SELECT userid FROM tblusers WHERE userid=%s", [userid])
        rc = cur.fetchone()
        if rc:
            return True
        # They might still be a valid user who isn't in tblusers yet
        if self.getAD().is_valid_user(userid):
            # Add them to the table for future reference
            db = self.getWriteDB()
            cur = db.cursor()
            cur.execute("INSERT INTO tblusers (userid) VALUES (%s)", [userid])
            db.commit()
            return True
        return False

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
            return self._isValidUser(userid)
        elif objectType == "group":
            return self._isValidGroup(userid)
        else:
            raise Exception("Invalid object type")

    def renderWrapper(self):
        if not self.getUser() and (self.REQUIRE_AUTH or (self.REQUIRE_AUTH_IF_ENABLED and config.auth_enabled == "yes")):
            return HTTPUnauthorized()
        try:
            ret = self.render()
            return ret
        finally:
            try:
                if self.WRITE:
                    self.waitForLocalWrite()
            finally:
                if self._db:
                    self._db.rollback()
                    self._db.close()

    def getWriteLocation(self, db):
        cur = db.cursor()
        # Get the current write xlog location from the master
        cur.execute("SELECT pg_current_xlog_location()")
        locStr = cur.fetchone()[0]
        loc = app.utils.XLogLocation(locStr)
        cur.close()
        return loc

    def getReadLocation(self, db):
        cur = db.cursor() 
        cur.execute("SELECT pg_last_xlog_replay_location();")
        locStr = cur.fetchone()[0]
        if locStr:
            loc = app.utils.XLogLocation(locStr)
        else:
            loc = None
        cur.close()
        return loc

    def waitForLocalWrite(self):
        assert self.WRITE
        writeDb = self.getDB()
        writeDb.rollback()
        writeLoc = self.getWriteLocation(writeDb)
        readDb = app.db.dbReadInstance()
        i = 0
        while i < (int(config.db_sync_timeout)/self.DB_SYNC_CHECK_INTERVAL):
            # Get the current xlog replay location from the local DB. This returns none if the local DB is the master
            readLoc = self.getReadLocation(readDb)
            if not readLoc:
                print "Local database is master, don't need to wait for sync"
                # This means the local database is the master, so we can stop
                break
            print "Checking whether writes have synced, attempt %d - write=%s, read=%s" % (i, str(writeLoc), str(readLoc))
            if readLoc >= writeLoc:
                break
            i += 1
            time.sleep(self.DB_SYNC_CHECK_INTERVAL)
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
                    "userId, uploaded, removed FROM tbljobs WHERE " +
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
