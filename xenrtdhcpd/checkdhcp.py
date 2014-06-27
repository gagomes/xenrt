#!/usr/bin/python

import os, re, time

with os.popen("grep 'xenrtdhcpd :' /var/log/syslog | tail -1") as f:
    line = f.read().strip()
    m = re.search("(\d\d):(\d\d):(\d\d)", line)
    if m:
        logts = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))

        mytime = time.localtime()

        myts = int(mytime.tm_hour * 3600 + mytime.tm_min * 60 + mytime.tm_sec)

        if logts > myts:
            myts += 3600*24

        if myts - 300 > logts:
            print "DHCP server not running"
        else:
            print "DHCP activity in the last 5 minutes"
    else:
        print "No log line found"
