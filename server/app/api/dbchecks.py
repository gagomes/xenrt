from app.api import XenRTAPIPage
from server import PageFactory
import app.db

from pyramid.httpexceptions import HTTPServiceUnavailable
import requests

import config

class _DBCheckBase(XenRTAPIPage):
    def isMaster(self):
        try:
            readDB = app.db.dbReadInstance()
            readLoc = self.getReadLocation(readDB)
            if not readLoc:
                if not config.partner_ha_node:
                    return "This node is connected to the master database - no partner node exists to check for split brain"
                try:
                    r = requests.get("http://%s/xenrt/api/dbchecks/takeovertime" % config.partner_ha_node)
                    r.raise_for_status()
                    remote_time = int(r.text.strip())
                except Exception, e:
                    return "This node is connected the master database - partner does not seem to be the master database - %s" % str(e)
                cur = readDB.cursor()
                cur.execute("SELECT value FROM tblconfig WHERE param='takeover_time'")
                local_time = int(cur.fetchone()[0].strip())
                if local_time > remote_time:
                    return "This node is connected the master database - remote is talking to a writable database, but local database is newer"
                else:
                    print "This node is connected to a writable database, but remote database is newer"
                    raise HTTPServiceUnavailable()
            else:
                return None
        finally:
            readDB.rollback()
            readDB.close()

        

class TakeoverTime(_DBCheckBase):
    def render(self):
        try:
            readDB = app.db.dbReadInstance()
            readLoc = self.getReadLocation(readDB)
            if not readLoc:
                cur = readDB.cursor()
                cur.execute("SELECT value FROM tblconfig WHERE param='takeover_time'")
                rc = cur.fetchone()
                return rc[0]
            else:
                return HTTPServiceUnavailable()
        finally:
            readDB.rollback()
            readDB.close()

class IsMaster(_DBCheckBase):
    def render(self):
        master = self.isMaster()
        if master:
            return master
        else:
            return HTTPServiceUnavailable()

class IsUsable(_DBCheckBase):
    def render(self):
        master = self.isMaster()
        if master:
            return master
        try:
            check_interval = 0.5
            timeout = 5

            writeDB = app.db.dbWriteInstance()
            readDB = app.db.dbReadInstance()

            writeLoc = self.getWriteLocation(writeDB)
            i = 0
            while i <= timeout/check_interval:
                readLoc = self.getReadLocation(readDB)
                assert readLoc
                if readLoc >= writeLoc:
                    return "This node is in sync, delay = %fs" % (i* check_interval)
                time.sleep(check_interval)
                i += 1
            return HTTPServiceUnavailable()
        finally:
            writeDB.rollback()
            writeDB.close()
            readDB.rollback()
            readDB.close()
            
PageFactory(IsMaster, "ismaster", "/api/dbchecks/ismaster")
PageFactory(TakeoverTime, "takeovertime", "/api/dbchecks/takeovertime")
PageFactory(IsUsable, "dbisusable", "/api/dbchecks/isusable")
