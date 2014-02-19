#!/usr/bin/python

import sys, xmlrpclib
s = xmlrpclib.ServerProxy("http://%s:8936" % sys.argv[1])
print s.readFile("%s\\Citrix\\XenCenter\\Logs\\XenCenter.log" % s.getEnvVar("APPDATA"))
