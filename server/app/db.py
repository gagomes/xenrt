import psycopg2
import config
import requests
import app.utils

class DatabaseOutOfDateException(Exception):
    def __init__(self):
        Exception.__init__(self, "This node is connected to a writable database, but remote database is newer!") 

def dbReadInstance():
    args = connStrToArgs(config.dbConnectString)
    return psycopg2.connect(**args)

def dbWriteInstance():
    args = connStrToArgs(config.dbConnectStringWrite)
    return psycopg2.connect(**args)

def isDBMaster(returnDetail=False):
    try:
        readDB = dbReadInstance()
        if getWriteLocation(readDB):
            if not config.partner_ha_node:
                if returnDetail:
                    return "This node is connected to the master database - no partner node exists to check for split brain"
                return True
            try:
                r = requests.get("https://%s/xenrt/api/dbchecks/takeovertime" % config.partner_ha_node, timeout=3)
                r.raise_for_status()
                remote_time = int(r.text.strip())
            except Exception, e:
                if returnDetail:
                    return "This node is connected the master database - partner does not seem to be the master database - %s" % str(e)
                return True
            cur = readDB.cursor()
            cur.execute("SELECT value FROM tblconfig WHERE param='takeover_time'")
            local_time = int(cur.fetchone()[0].strip())
            if local_time > remote_time:
                if returnDetail:
                    return "This node is connected the master database - remote is talking to a writable database, but local database is newer"
                return True
            else:
                raise DatabaseOutOfDateException()
        else:
            if returnDetail:
                return None
            return False
    finally:
        readDB.rollback()
        readDB.close()

def getReadLocation(db):
    cur = db.cursor()
    cur.execute("SELECT pg_last_xlog_replay_location();")
    locStr = cur.fetchone()[0]
    if locStr:
        loc = app.utils.XLogLocation(locStr)
    else:
        loc = None
    cur.close()
    return loc

def getWriteLocation(db):
    cur = db.cursor()
    # Get the current write xlog location from the master
    try:
        cur.execute("SELECT pg_current_xlog_location()")
        locStr = cur.fetchone()[0]
        loc = app.utils.XLogLocation(locStr)
    except:
        db.rollback()
        loc = None
    cur.close()
    return loc

# Convert a connection string to a dictionary of args for psycopg2
def connStrToArgs(connStr):
    ret = {}
    params = connStr.split(":")
    hostport = params[0].split(",")
    ret['host'] = hostport[0]
    if len(hostport) > 1:
        ret['port'] = hostport[1]
    ret['database'] = params[1]
    if len(params) > 2:
        ret['user'] = params[2]
    if len(params) > 3:
        ret['password'] = params[3]
    return ret
