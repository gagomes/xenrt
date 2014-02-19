import pgdb
import config

__all__= ["dbInstance"]

def dbInstance():
    return pgdb.connect(config.dbConnectString)
