#!/usr/bin/env python

#
# report.py
#
# Statistical and formatting functions for producing XenRT
# performance reports.
#

# Requires: 
#
# Transcendental library 
# http://bonsai.ims.u-tokyo.ac.jp/~mdehoon/software/python/special.html
# 
# Matplotlib
# http://matplotlib.sourceforge.net/
#
# NumPY
# http://numpy.scipy.org/
#

#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import sys, re, getopt
import db, perfdata

usage = "Usage: report.py <product> <reference>"
ignore = 0

def isProductVersion(x):
    return re.match(r"^(?P<major>\d+)\.(?P<minor>\d+).(?P<fix>\d+)-(?P<build>\d+)$", x)

try:
    optlist, otherargs = getopt.gnu_getopt(sys.argv, "", ["ignore="])
    for flag, value in optlist:
        if flag == "--ignore":
            ignore = int(value)
except:
    print usage
    sys.exit(1)

try:
    script, product, reference = otherargs 
except:
    print usage
    sys.exit(1)

if not isProductVersion(product) or not isProductVersion(reference):
    print usage
    sys.exit(1)

rawdata = db.query(product, reference)
data = perfdata.parsedata(rawdata)
if ignore:
    new = perfdata.ignore(data, ignore)
    old = perfdata.ignore(data, -ignore)
    show = [ x for x in new if x.significant() and x in old ]
else:
    show = data

print "Listing metrics that have improved from %s to %s...\n" % (reference, product)
perfdata.summarise(show, better=True)
print "\nListing metrics that have regressed from %s to %s...\n" % (reference, product)
perfdata.summarise(show, better=False)
