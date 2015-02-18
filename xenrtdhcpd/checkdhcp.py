#!/usr/bin/python

import os, re, time

def isLogOlderThan300s(fh):
    line = fh.read().strip()
    m = re.search("(\d\d):(\d\d):(\d\d)", line)
    if m:
        logts = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))

        mytime = time.localtime()

        myts = int(mytime.tm_hour * 3600 + mytime.tm_min * 60 + mytime.tm_sec)

        if logts > myts:
            myts += 3600*24

        if myts - 300 > logts:
            return True
        else:
            return False
    else:
        raise Exception("No log line found")

with os.popen("grep 'xenrtdhcpd :' /var/log/syslog | tail -1") as f:
    try:
        if isLogOlderThan300s(f):
            print "DHCP server not running"
            os.system("sudo /etc/init.d/xenrtdhcpd restart")
        else:
            print "DHCP activity in the last 5 minutes"
    except Exception, e:
        print e
        print "No log line found, checking age of syslog"
        with os.popen("head -1 /var/log/syslog") as g:
            if isLogOlderThan300s(g):
                print "Syslog is older than 300s with no dhcp log line, restarting DHCP"
                os.system("sudo /etc/init.d/xenrtdhcpd restart")
            else:
                print "Syslog isn't 300s old yet, not restarting yet"
                
