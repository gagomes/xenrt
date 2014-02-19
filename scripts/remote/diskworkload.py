#!/usr/bin/python
# XenRT: Test harness for Xen and the XenServer product family
#
# Workload script
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

from datetime  import datetime
import sys,os,time
import string
import random

# We are given exactly two arguments, the filename to log to, and a file
# to write our PID to
if len(sys.argv) < 4 or len(sys.argv) > 5:
    sys.stderr.write("Invalid number of arguments\n")
    sys.exit(1)

filename = sys.argv[1]
pidfile = sys.argv[2]
workloadfile = sys.argv[3]

if len(sys.argv) >= 5:
    size = int(sys.argv[4])
else:
    size = 10

# Write out our pid
f = file(pidfile, "w")
f.write(str(os.getpid()))
f.close()

# Let's go (we are stopped by being killed...)
MB=1024 * 1024
iteration=1
f = file(filename, "w")
f.write('_________________________________________________________________________________\n')
f.write('                                                                                 \n')
f.write('            PERF: Write and Read time for ' + str(size) + 'MB of data            \n') 
f.write('_________________________________________________________________________________\n')

while True:
    
    f.write('\n')
    f.write('ITERATION: ' + str(iteration) + '\n')

    f_write=open(workloadfile,'w')
    data=(random.choice(string.letters))*size*MB
    timeBefore=datetime.now()
    f_write.write(data)
    f_write.flush()
    f_write.close()

    timeAfter = datetime.now()
    diff = str(timeAfter - timeBefore)
    totalTime = ' TIME_NOW: ' + str(datetime.now()) + ' WRITE_TIME for ' + str(size) + 'MB of data: ' + diff + '\n'
    f.write(totalTime)    
    f.flush()

    time.sleep(0.1)

    f_read=open(workloadfile,'rb')
    timeBefore=datetime.now()
    f_read.read(10*MB)
    f_read.flush()
    f_read.close()

    timeAfter=datetime.now()
    diff = str(timeAfter - timeBefore)
    totalTime = ' TIME_NOW: ' + str(datetime.now()) + ' READ_TIME  for ' + str(size) + 'MB of data: ' + diff + '\n'
    f.write(totalTime)
    f.flush()

    time.sleep(0.1)
    iteration = iteration + 1
