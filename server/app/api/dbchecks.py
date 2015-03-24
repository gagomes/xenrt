from app.api import XenRTAPIPage
from server import PageFactory
import app.db

from pyramid.httpexceptions import HTTPServiceUnavailable
import requests

import config
import time


class TakeoverTime(XenRTAPIPage):
    def render(self):
        try:
            readDB = app.db.dbReadInstance()
            readLoc = app.db.getReadLocation(readDB)
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

class IsMaster(XenRTAPIPage):
    def render(self):
        master = self.isDBMaster(returnDetail=True)
        if master:
            return master
        else:
            return HTTPServiceUnavailable()

class IsUsable(XenRTAPIPage):
    def render(self):
        master = self.isDBMaster()
        if master:
            return master
        try:
            check_interval = 0.5
            timeout = 5

            writeDB = app.db.dbWriteInstance()
            readDB = app.db.dbReadInstance()

            writeLoc = app.db.getWriteLocation(writeDB)
            i = 0
            while i <= timeout/check_interval:
                readLoc = app.db.getReadLocation(readDB)
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
            
PageFactory(IsMaster, "/api/dbchecks/ismaster")
PageFactory(TakeoverTime, "/api/dbchecks/takeovertime")
PageFactory(IsUsable, "/api/dbchecks/isusable")
