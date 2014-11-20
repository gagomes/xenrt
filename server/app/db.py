import psycopg2.pool
import config

__all__= ["dbInstance"]

global _readDBPool
_readDBPool = None
global _writeDBPool
_writeDBPool = None

class PooledDBConnection(object):
    def __init__(self, pool):
        self.pool = pool
        i = 0
        # If the database is restarted, we'll need to close the connection and start a new one
        # So we do a simple query to the DB, and if that fails, we close the connection and try a new one
        # Eventually all of the stale connections will be closed, then we'll get a fresh new one
        while i <= int(config.max_db_connections):
            self.conn = pool.getconn()
            cur = self.conn.cursor()
            try:
                cur.execute("SELECT 1;")
                cur.close()
                break
            except:
                self.pool.putconn(self.conn, close=True)
            i += 1

    def close(self):
        self.pool.putconn(self.conn)

    def __getattr__(self, name):
        return getattr(self.conn, name)

def dbReadInstance():
    global _readDBPool
    if not _readDBPool:
        _readDBPool = initPool(config.dbConnectString)
    return PooledDBConnection(_readDBPool)

def dbWriteInstance():
    global _writeDBPool
    if not _writeDBPool:
        _writeDBPool = initPool(config.dbConnectStringWrite)
    ret = PooledDBConnection(_writeDBPool)
    return ret

def initPool(connStr):
    args = connStrToArgs(connStr)
    ret = psycopg2.pool.ThreadedConnectionPool(1, int(config.max_db_connections), **args)
    return ret

# Convert a connection string to a dictionary of args for psycopg2
def connStrToArgs(connStr):
    ret = {}
    params = connStr.split(":")
    ret['host'] = params[0]
    ret['database'] = params[1]
    if len(params) > 2:
        ret['user'] = params[2]
    if len(params) > 3:
        ret['password'] = params[3]
    return ret
