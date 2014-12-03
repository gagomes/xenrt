import psycopg2
import config

def dbReadInstance():
    args = connStrToArgs(config.dbConnectString)
    return psycopg2.connect(**args)

def dbWriteInstance():
    args = connStrToArgs(config.dbConnectStringWrite)
    return psycopg2.connect(**args)

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
