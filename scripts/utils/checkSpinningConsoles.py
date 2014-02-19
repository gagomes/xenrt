#!/usr/bin/python

import subprocess, os

psout = subprocess.Popen(["/bin/ps", "-o", "pid,time,pcpu,args", "-C", "console", "--no-headers"], stdout=subprocess.PIPE).communicate()[0]
procs = psout.splitlines()
for p in procs:
    ps = p.split()
    pid = ps[0]
    time = ps[1]
    pcpu = ps[2]
    host = ps[5]
    # We declare it to be spinning if time is > 5 minutes, and pcpu is > 10.
    time = time.split("-")[-1]
    times = time.split(":")    
    if (int(times[0]) > 0 or int(times[1]) > 5) and int(float(pcpu)) > 10:
        print "Killing spinning console process %s on host %s" % (pid, host)
        os.system("kill -9 %s" % (pid))

