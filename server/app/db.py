import pgdb
import config

__all__= ["dbInstance"]

def dbReadInstance():
    return pgdb.connect(config.dbConnectString)

def dbWriteInstance():
    return pgdb.connect(config.dbConnectStringWrite)
