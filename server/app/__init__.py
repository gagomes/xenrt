from server import Page
import app.db
import app.ad
import config
import time
import math
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
        self._groupCache = {}
        self._userGroupCache = {}

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
            if self.ALLOW_FAKE_USER and self._isValidUser(lcheaders['x-fake-user']):
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

    # ACL Functions
    def get_acl(self, aclid):
        db = self.getDB()
        cur = db.cursor()

        cur.execute("SELECT name, parent FROM tblacls WHERE aclid=%s", [aclid])
        rc = cur.fetchone()
        if not rc:
            raise KeyError("ACL not found")
        name = rc[0].strip()
        parent = rc[1]

        entries = []
        cur.execute("SELECT type, userid, grouplimit, grouppercent, userlimit, userpercent, maxleasehours FROM tblaclentries WHERE aclid=%s ORDER BY prio", [aclid])
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            def __int(data):
                if data is None:
                    return data
                return int(data)

            entries.append(app.acl.ACLEntry(rc[0].strip(), rc[1].strip(), __int(rc[2]), __int(rc[3]), __int(rc[4]), __int(rc[5]), __int(rc[6])))

        return app.acl.ACL(aclid, name, parent, entries)

    def get_machines_in_acl(self, aclid):
        db = self.getDB()
        machines = {}
        cur = db.cursor()
        cur.execute("SELECT m.machine, m.status, m.comment, j.userid FROM tblmachines AS m INNER JOIN tblacls AS a ON m.aclid = a.aclid LEFT JOIN tbljobs AS j ON m.jobid = j.jobid WHERE (m.aclid = %s OR a.parent = %s)",
                    (aclid, aclid))
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            if rc[1].strip() in ["scheduled", "slaved", "running"]:
                machines[rc[0]] = rc[3].strip()
            elif rc[2] is not None:
                machines[rc[0]] = rc[2].strip()
            else:
                machines[rc[0]] = None
        cur.close()

        return machines

    def check_acl(self, aclid, userid, number, leaseHours=None):
        """Returns True if the given user can have 'number' additional machines under this acl"""
        acl = self.get_acl(aclid)
        if self._check_acl(acl, userid, number, leaseHours):
            if acl.parent:
                # We have to check the parent ACL as well
                return self._check_acl(self.get_acl(acl.parent), userid, number, leaseHours)
            return True
        return False

    def _check_acl(self, acl, userid, number, leaseHours=None):
        """Returns True if the given user can have 'number' additional machines under this acl"""
        # Identify all machines that use this aclid and who the active user is in each case (including where this aclid is a parent)
        machines = self.get_machines_in_acl(acl.aclid)
        usergroups = self._groups_for_userid(userid)
        usercount = number # Count of machines this user has
        for m in machines:
            if machines[m] == userid:
                usercount += 1
        userpercent = int(math.ceil((usercount * 100.0) / len(machines)))
        groupcache = None

        # Go through the acl entries
        for e in acl.entries:
            if e.entryType == 'user':
                if e.userid != userid:
                    # Another user - remove their usage from our data
                    # otherwise we might double count them if they're a member of a group as well
                    for m in machines:
                        if machines[m] == e.userid:
                            machines[m] = None
                    continue
                else:
                    # Our user - check their usage
                    if e.userlimit is not None and usercount > e.userlimit:
                        return False
                    if e.userpercent is not None and userpercent > e.userpercent:
                        return False
                    if e.maxleasehours is not None and leaseHours and leaseHours > e.maxleasehours:
                        return False

                    # We've hit an exact user match, so we ignore any further rules
                    return True
            else:
                if e.userid in usergroups:
                    # A group our user is in - identify overall usage and per user usage for users in the acl
                    groupcount = usercount
                    for u in self._userids_for_group(e.userid):
                        if u == userid:
                            continue # Don't count our user as we've already accounted for that
                        groupcount += len(filter(lambda m: m == u, machines.values()))
                    grouppercent = int(math.ceil((groupcount * 100.0) / len(machines)))

                    if e.grouplimit is not None and groupcount > e.grouplimit:
                        return False
                    if e.grouppercent is not None and grouppercent > e.grouppercent:
                        return False

                    # Check the user limits as well
                    if e.userlimit is not None and usercount > e.userlimit:
                        return False
                    if e.userpercent is not None and userpercent > e.userpercent:
                        return False

                    # Check lease restrictions
                    if e.maxleasehours is not None and leaseHours and leaseHours > e.maxleasehours:
                        return False

                # We've hit a successful group match, so we ignore any further rules
                return True

        return True

    def _userids_for_group(self, group):
        if group in self._groupCache:
            return self._groupCache[group]
        db = self.getDB()
        cur = db.cursor()
        cur.execute("SELECT gu.userid FROM tblgroupusers gu INNER JOIN tblgroups g ON gu.groupid = g.groupid WHERE g.name=%s", [group])
        results = []
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            results.append(rc[0].strip())
        self._groupCache[group] = results
        return results

    def _groups_for_userid(self, userid):
        if userid in self._userGroupCache:
            return self._userGroupCache[userid]
        db = self.getDB()
        cur = db.cursor()
        cur.execute("SELECT g.name FROM tblgroups g INNER JOIN tblgroupusers gu ON g.groupid = gu.groupid WHERE gu.userid=%s", [userid])
        results = []
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            results.append(rc[0].strip())
        self._userGroupCache[userid] = results
        return results

import app.api
import app.apiv2
import app.ui
import app.uiv2
import app.compat
import app.signal
import app.ad
import app.acl
