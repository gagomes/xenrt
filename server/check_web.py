#!/usr/bin/python

import urllib2,os

try:
    urllib2.urlopen("http://localhost/share/control/blank", timeout=5)
except Exception, e:
    print "XenRT broken %s" % str(e)

    os.system("sudo service xenrt-server restart")
    os.system("sudo service apache2 restart")
