from server import Page
import app.db

class XenRTPage(Page):

    def __init__(self, request):
        super(XenRTPage, self).__init__(request)
        self._db = None

    def renderWrapper(self):
        ret = self.render()
        if self._db:
            self._db.close()
        return ret

    def getDB(self):
        if not self._db:
            self._db = app.db.dbInstance()
        return self._db

    def lookup_jobid(self, detailid):
        reply = -1
        cur = self.getDB().cursor()

        cur.execute("SELECT jobid from tblResults WHERE detailid = %u", 
                    (int(detailid)))

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
                    "jobId = %u;", (id))
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
                    "phase = %s AND test = %s", (jobid, phase, test))

        rc = cur.fetchone()
        if rc and rc[0]:
            reply = int(rc[0])
            
        cur.close()

        return reply


import app.api
import app.ui
import app.compat
import app.signal
