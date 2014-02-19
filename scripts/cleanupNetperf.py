#!/usr/bin/python

import os,time,string

def isNumeric(str):
    try:
        x = int(str)
        return True
    except ValueError:
        pass

    return False

psHandle = os.popen("ps aux | grep [n]etserver", "r")
ps = psHandle.read()

for proc in ps.split("\n"):
    fields = proc.split()
    if len(fields) < 9:
        continue
    pid = fields[1]
    started = fields[8]
    if ":" in started:
        # Under 24 hours old, ignore...
        continue
    if isNumeric(started):
        # Only numbers - must be a year
        # Assume it started on the last day of the year
        t = time.strptime("Dec31%s" % (started),"%b%d%Y")
    else:
        # Format is MMMDD
        t = time.strptime("%s%s" % (started,time.localtime()[0]), "%b%d%Y")

    seconds = time.mktime(time.localtime()) - time.mktime(t)
    if seconds > (7 * 24 * 3600):
        # Over 7 days old, kill it
        os.system("kill -9 %s > /dev/null 2>&1 || true" % (pid))

