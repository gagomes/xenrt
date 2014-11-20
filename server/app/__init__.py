from server import Page
import app.db
import time

class XenRTPage(Page):
    WRITE = False

    def __init__(self, request):
        super(XenRTPage, self).__init__(request)
        self._db = None

    def renderWrapper(self):
        try:
            ret = self.render()
            return ret
        finally:
            try:
                if self.WRITE:
                    self.waitForLocalWrite()
            finally:
                if self._db:
                    self._db.close()

    def waitForLocalWrite(self):
        assert self.WRITE
        writeDb = self.getDB()
        writeCur = writeDb.cursor()
        writeCur.execute("SELECT pg_current_xlog_location()")
        writeLocStr = writeCur.fetchone()[0]
        writeLoc = app.utils.XLogLocation(writeLocStr)
        readDb = app.db.dbReadInstance()
        readCur = readDb.cursor()
        i = 0
        while i < 1000:
            readCur.execute("SELECT pg_last_xlog_replay_location();")
            readLocStr = readCur.fetchone()[0]
            print "Checking whether writes have synced, attempt %d - write=%s, read=%s" % (i, writeLocStr, readLocStr)
            if not readLocStr:
                break
            readLoc = app.utils.XLogLocation(readLocStr)
            if readLoc >= writeLoc:
                break
            i += 1
            time.sleep(0.1)
        readCur.close()
        readDb.close()

    def getDB(self):
        if not self._db:
            if self.WRITE:
                self._db = app.db.dbWriteInstance()
            else:
                self._db = app.db.dbReadInstance()
        return self._db

    def lookup_jobid(self, detailid):
        reply = -1
        cur = self.getDB().cursor()

        cur.execute("SELECT jobid from tblResults WHERE detailid = %u", 
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
                    "jobId = %u;", [id])
        rc = cur.fetchone()
        if rc:
            d = app.utils.parse_job(rc,cur)
       
        cur.close()
      
        return d
    
    def lookup_detailid(self, jobid, phase, test):

        reply = -1
     
        db = self.getDB()

        cur = db.cursor()

        cur.execute("SELECT detailid from tblResults WHERE jobid = %u AND "
                    "phase = %s AND test = %s", [jobid, phase, test])

        rc = cur.fetchone()
        if rc and rc[0]:
            reply = int(rc[0])
            
        cur.close()

        return reply


import app.api
import app.ui
import app.compat
import app.signal
