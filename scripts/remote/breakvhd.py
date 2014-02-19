#!/usr/bin/python
# XenRT: Test harness for Xen and the XenServer product family
#
# TCBreakVHD helper script
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys


# We will be given two arguments, a filename, and an action, which is either
# "write" or "read"

if len(sys.argv) != 3:
    sys.stderr.write("Invalid number of arguments\n")
    sys.exit(1)

filename = sys.argv[1]
action = sys.argv[2]

size = 100

print "Filename: %s" % (filename)

if action == "write":
    print "Writing file"

    f = file(filename, "w")
    for i in range(size):
        f.seek(i*4096*1024)
        f.write(str(i))
    f.close()
    print "File written"
elif action == "read":
    print "Reading file"
    f = file(filename, "r")
    for i in range(size):
        try:
            f.seek(i*4096*1024)
            d = f.read(len(str(i)))
            if d != str(i):
                sys.stderr.write("Inconsistency with number %d\n" % (i))
                sys.exit(1)
        except Exception, e:
            sys.stderr.write("Exception while reading file: %s\n" % (str(e)))
            sys.exit(1)
    print "File is as expected"
    sys.exit(0)
else:
    sys.stderr.write("Invalid action\n")
    sys.exit(1)
