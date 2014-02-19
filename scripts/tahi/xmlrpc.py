#!/usr/bin/env python
import sys
import getopt
import xmlrpclib
import time

def doOperation(operation, host):
    print "Operation: %s, Host: %s" % (operation, host)
#    assert((host and operation), "Invalid Arguments")
    xmlrpc = xmlrpclib.ServerProxy('http://%s:8936' % (host))
   
    if operation == 'reboot':
        xmlrpc.reboot() 

    elif operation == 'reboot-wait':
        xmlrpc.reboot()
        
        while True:
            time.sleep(30)
            print "Check if guest is alive"
            try:
                if xmlrpc.isAlive():
                    break
            except Exception, e:
                print "Alive check failed: %s" % (str(e))

        
if __name__ == '__main__':
    operation = None
    host = None

    opts, extraparams = getopt.getopt(sys.argv[1:], '', ['op=', 'host='])
    for o,a in opts:
        if 'op' in o:
            operation = a
        if 'host' in o:
            host = a

    doOperation(operation, host)
