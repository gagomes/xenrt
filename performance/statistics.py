#!/usr/bin/env python

#
# statistics.py
#
# Statistical functions for the XenRT performance report
# generator.
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

# TODO Check assumptions and improve documentation.

import transcendental, math

import config

def mean(values):
    """Return the mean of values."""
    return sum(values)/len(values)

def stddev(values):
    """Return the standard deviation of values."""
    xbar = mean(values)
    variance = sum((x-xbar)**2 for x in values)/(len(values)-1)
    return math.sqrt(variance)

def mdiff(xbar, ybar):
    """Return the mean difference."""
    return xbar - ybar

def df(xcount, ycount):
    """Return the degrees of freedom."""
    return xcount + ycount - 2

def pooldev(xdev, xcount, ydev, ycount):
    """Returned the pooled standard deviation."""
    return math.sqrt(((xcount-1)*xdev**2+(ycount-1)*ydev**2)/df(xcount,ycount))

def ueslim(xbar, xdev, xcount, ybar, ydev, ycount, cf=0.05):
    """Return the upper confidence limit on effect size for p = cf."""
    effectsize = es(xbar, xdev, xcount, ybar, ydev, ycount)
    eserr = eserror(xbar, xdev, xcount, ybar, ydev, ycount)
    return effectsize+eserr*transcendental.ndtri(1-(cf/2))

def leslim(xbar, xdev, xcount, ybar, ydev, ycount, cf=0.05):
    """Return the lower confidence limit on effect size for p = cf."""
    effectsize = es(xbar, xdev, xcount, ybar, ydev, ycount)
    eserr = eserror(xbar, xdev, xcount, ybar, ydev, ycount)
    return effectsize-eserr*transcendental.ndtri(1-(cf/2))

def eserror(xbar, xdev, xcount, ybar, ydev, ycount):
    """Return the standard error of the effect size estimate."""
    effectsize = es(xbar, xdev, xcount, ybar, ydev, ycount)
    return math.sqrt((xcount+ycount)/(xcount*ycount)+effectsize**2/(2*(xcount+ycount)))

def es(xbar, xdev, xcount, ybar, ydev, ycount):
    """Return the effect size."""
    es = mdiff(xbar, ybar)/pooldev(xdev, xcount, ydev, ycount)
    # Approximate bias.
    return es*(1.0 - 3.0/(4.0*df(xcount, ycount)-1.0))

def ftest(xdev, xcount, ydev, ycount, cf=0.05):
    """Perform an F-test.
       The null hypothesis is that standard deviations are equal.
       Returns False if null hypothesis is rejected."""
    if xdev == 0 or ydev == 0:
        return False
    v = transcendental.fdtr(int(ycount-1),int(xcount-1),(max(xdev,ydev)**2/min(xdev,ydev)**2))
    return v < 1-cf/2 and v > cf/2

def lclimit(xbar, xdev, xcount, ybar, ydev, ycount, cf=0.05):
    """Return the lower confidence limit with p = cf."""
    # Use the second standard deviation if it appears they
    # may not be equal.
    if ftest(xdev, xcount, ydev, ycount):
        sd = pooldev(xdev, xcount, ydev, ycount)
    else:
        sd = ycount
    # Get the inverse Student's distribution.
    invstd = transcendental.stdtri(df(xcount,ycount),1-cf/2)
    # Scale it.
    scaled = invstd*sd/math.sqrt((xcount*ycount)/(xcount+ycount))
    # Return the result relative to the mean.
    return mdiff(xbar,ybar)-scaled

def uclimit(xbar, xdev, xcount, ybar, ydev, ycount, cf=0.05):
    """Return the upper confidence limit with p = cf."""
    # Use the second standard deviation if it appears they
    # may not be equal.
    if ftest(xdev, xcount, ydev, ycount):
        sd = pooldev(xdev, xcount, ydev, ycount)
    else:
        sd = ycount
    # Get the inverse Student's distribution.
    invstd = transcendental.stdtri(df(xcount,ycount),1-cf/2)
    # Scale it.
    scaled = invstd*sd/math.sqrt((xcount*ycount)/(xcount+ycount))
    # Return the result relative to the mean.
    return mdiff(xbar,ybar)+scaled
