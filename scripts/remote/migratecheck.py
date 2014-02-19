#!/usr/bin/python
# XenRT: Test harness for Xen and the XenServer product family
#
# Live migrate helper script
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys,os,time

# We are given exactly two arguments, the filename to log to, and a file
# to write our PID to
if len(sys.argv) != 3:
    sys.stderr.write("Invalid number of arguments\n")
    sys.exit(1)

filename = sys.argv[1]
pidfile = sys.argv[2]

# Write out our pid
f = file(pidfile, "w")
f.write(str(os.getpid()))
f.close()

# Let's go (we are stopped by being killed...)
f = file(filename, "w")
while True:
    f.write(str(time.time()) + "\n")
    f.flush()
    time.sleep(0.1)
