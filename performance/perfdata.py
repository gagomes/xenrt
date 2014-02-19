#!/usr/bin/env python

#
# perfdata.py
#
# Data model for performance data.
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import transcendental, re, string, copy

import statistics, config, util

class DataPoint:

    def __init__(self, values, jobids):
        self.values = values
        self.jobids = jobids

        self.count = len(self.values)
        self.mean = statistics.mean(self.values)
        self.stddev = statistics.stddev(self.values)
        # We sometimes get a standard deviation of zero because
        # of the granularity of our measurements. If that happens
        # set the standard deviaton to the error in the measurement.
        if self.stddev == 0:
            self.stddev = 10**(-len(re.sub("[0-9]+\.", "", str(self.mean)))/2)

class MetricResult:

    def setstats(self):
        arguments = (self.productdata.mean,
                     self.productdata.stddev,
                     self.productdata.count,
                     self.referencedata.mean,
                     self.referencedata.stddev,
                     self.referencedata.count)

        self.lclimit = statistics.lclimit(*arguments)
        self.uclimit = statistics.uclimit(*arguments)
        self.error = (self.uclimit - self.lclimit)/2
        self.effectsize = statistics.es(*arguments)
        self.ueslim = statistics.ueslim(*arguments)
        self.leslim = statistics.leslim(*arguments)
        self.relative = (self.productdata.mean/self.referencedata.mean-1)*100
        self.lower = ((self.referencedata.mean + self.lclimit)/self.referencedata.mean-1)*100
        self.upper = ((self.referencedata.mean + self.uclimit)/self.referencedata.mean-1)*100

    def significant(self):
        return self.productdata.mean - self.error > self.referencedata.mean or \
               self.productdata.mean + self.error < self.referencedata.mean

    def better(self):
        if self.significant():
            if self.productdata.mean - self.referencedata.mean < 0:
                return self.smallgood
            return not self.smallgood
        return False    

    def __str__(self):
        return "%dGUEST%dVCPU %-20s %-20s %4.1f%% < %4.1f%% < %4.1f%%" % \
               (self.guestnumber, 
                self.vcpus, 
                self.benchmark, 
                self.metric, 
                self.lower,
                self.relative,
                self.upper)

    def __eq__(self, other):
        return self.guestnumber == other.guestnumber and \
               self.vcpus == other.vcpus and \
               self.benchmark == other.benchmark and \
               self.metric == other.metric and \
               self.productversion == other.productversion and \
               self.storagetype == other.storagetype and \
               self.memory == other.memory and \
               self.extradisks == other.extradisks

    def __init__(self, item):
        self.productversion = item["productversion"]
        self.storagetype = item["storagetype"]
        self.guestversion = item["guestversion"]
        self.vcpus = item["vcpus"]
        self.memory = item["memory"]
        self.guestnumber = item["guestnumber"]
        self.extradisks = item["extradisks"]

        self.benchmark = item["benchmark"]   
        self.metric = item["metric"]
        self.units = config.unitlookup[item["units"]]
        self.smallgood = item["units"] in config.smallgood

        self.values = map(float, re.split(config.subdelimiters, item["values"]))
        self.referencevalues = map(float, re.split(config.subdelimiters, item["refvalues"]))
        self.jobids = re.split(config.subdelimiters, str(item["jobids"]))
        self.referencejobids = re.split(config.subdelimiters, str(item["refids"]))

        self.productdata = DataPoint(self.values, self.jobids)

        self.referencedata = DataPoint(self.referencevalues, self.referencejobids)

        self.setstats()

def parsedata(data):
    """Take a performance explorer CSV and return a list of MetricResults."""
    # Split into a list of data point lists.
    data = [ re.split(config.delimiters, x) for x in data ]

    # Convert anything we can to a float. This saves a lot of hassle.
    data = [ map(util.cf, x) for x in data ]

    # Parse the entries into dictionaries.
    data = [ dict(zip(config.columns, x)) for x in data ]

    # Get rid of entries with insufficient data.
    data = filter(lambda x:not x["count"] < 2, data)
    data = filter(lambda x:not x["refcount"] < 2, data)
    data = filter(lambda x:not x["refmean"] == 0, data)
    data = filter(lambda x:not x["mean"] == 0, data)

    return [ MetricResult(x) for x in data ]

def ignore(data, count):
    result = []
    for metric in data:
        if len(metric.values) > abs(count)*int(metric.guestnumber) + 1:
            new = copy.copy(metric)
            if count > 0:
                new.values = new.values[count*int(new.guestnumber):]
                new.jobids = new.jobids[count:]
            else:
                new.values = new.values[:abs(count)*int(new.guestnumber)]
                new.jobids = new.jobids[:abs(count)]
            new.productdata = DataPoint(new.values, new.jobids)
            new.setstats()
            result.append(new)
    return result

def summarise(data, better=False):
    """Produce a sorted summary of significant results in 'data'."""
    data = filter(lambda x:x.significant(), data)
    data = filter(lambda x:x.better() == better, data)
    data = sorted(data, key=lambda x:-min(abs(x.upper), abs(x.lower)))
    for result in data: 
        print result
