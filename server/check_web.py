#!/usr/bin/python

import urllib2,os

try:
    urllib2.urlopen("http://localhost/share/control/blank", timeout=5)
except Exception, e:
    print "XenRT broken %s" % str(e)

    os.system("sudo /etc/init.d/xenrt-server restart")
