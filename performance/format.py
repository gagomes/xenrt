#!/usr/bin/env python

#
# format.py
#
# Functions to create graphs, charts and tables from 
# performance data.
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import numpy, matplotlib.pyplot, string

import config, perfdata, util

class Graph:

    CONSTRAINTS = None
    DISPLAYORDER = None

    def __init__(self, data):
        """The data variable is a list of MetricResults.""" 
        self.data = data
        self.figure = None
        self.filename = string.join(map(str, map(util.ci, self.getConfiguration().values())), "-")
        matplotlib.rc("figure.subplot", bottom=config.bottomjustified)
        matplotlib.rc("figure.subplot", left=config.leftjustified)
        matplotlib.rc("figure.subplot", right=1-config.leftjustified)

    def create(self):
        pass

    def plot(self, path):
        self.figure.savefig("%s/%s" % (path, self.filename))

    def getConfiguration(self):
        return dict([ (x, getattr(self.data[0], x)) for x in self.CONSTRAINTS ])

    @classmethod 
    def sortdata(cclass, data, configuration):
        for c in cclass.CONSTRAINTS:
            data = filter(lambda x:getattr(x, c) == configuration[c], data)
        for d in cclass.DISPLAYORDER:
            data.sort(key=lambda x:getattr(x, d))
        return data

class BarChart(Graph):

    CONSTRAINTS = config.graphs
    DISPLAYORDER = config.bars

    def __init__(self, data):
        """The data variable is a list of MetricResults.""" 
        Graph.__init__(self, data)
        self.width = config.width
        self.labelpointsize = config.blabelpointsize
        self.errorcolour = config.errorcolour
        self.linewidth = config.linewidth
        self.referencecolour = config.referencecolour
        self.colour = config.colour
        self.worsecolour = config.worsecolour
        self.bettercolour = config.bettercolour

    def create(self):
        self.figure = matplotlib.pyplot.figure()
        axis = self.figure.add_subplot(1, 1, 1)
    
        errorvalues = [ x.error for x in self.data ]
        productvalues = [ x.productdata.mean for x in self.data ]
        referencevalues = [ x.referencedata.mean for x in self.data ]
        index = numpy.arange(len(productvalues))

        # Work out the colours to use for the product bars.
        colours = []
        for x in self.data:
            if x.better(): colours.append(self.bettercolour)
            elif x.significant(): colours.append(self.worsecolour)
            else: colours.append(self.colour)

        # Plot the product bars.
        axis.bar(index, 
                 productvalues, 
                 self.width, 
                 yerr=errorvalues,
                 color=colours, 
                 ecolor=self.errorcolour, 
                 linewidth=self.linewidth) 
        # Plot the reference bars next to the product bars.
        axis.bar(index+self.width, 
                 referencevalues, 
                 self.width,
                 color=self.referencecolour, 
                 ecolor=self.errorcolour, 
                 linewidth=self.linewidth) 

        # Set the axes' ranges.
        axis.set_ylim(ymin=0)

        # Spruce the graph up a bit.
        xlabels = [ string.join([ "%s %s" % (util.ci(getattr(x, y)), config.configvariables[y]) \
                        for y in config.bars ], "\n") \
                            for x in self.data ]
        axis.set_xticklabels(xlabels, size=self.labelpointsize)
        axis.set_xticks(index+self.width)
        axis.set_ylabel(self.data[0].units)
        for x in axis.get_ymajorticklabels(): x.set_size(self.labelpointsize)
        axis.set_clip_on(False)

class ForestPlot(Graph):

    CONSTRAINTS = config.fgraphs
    DISPLAYORDER = config.leaves

    def __init__(self, data):
        """The data variable is a list of MetricResults."""
        Graph.__init__(self, data)
        self.xlabel = config.fxlabel
        self.ylabel = config.fylabel
        self.normalpoints = config.pointstyle
        self.betterpoints = config.betterpointstyle
        self.worsepoints = config.worsepointstyle
        self.labelpointsize = config.flabelpointsize

    def create(self):
        self.figure = matplotlib.pyplot.figure()
        axis = self.figure.add_subplot(1, 1, 1)

        ys = numpy.arange(1, len(self.data) + 1)
        # Calculate x-values for effect size ranges.
        xmins = numpy.asarray([ x.leslim for x in self.data ])
        xmaxs = numpy.asarray([ x.ueslim for x in self.data ])
        # Calculate a map of significance values.
        bettermap = [ x.better() for x in self.data ]
        worsemap = [ x.significant() and not x.better() for x in self.data ]    
        # Split y-values into those corresponding to better and worse results.
        better = numpy.array([ y for (b,y) in zip(bettermap, ys) if b ])
        worse = numpy.array([ y for (w,y) in zip(worsemap, ys) if w ])
        
        # Set the axes' ranges.
        axis.set_ylim(min(ys) - 1, max(ys) + 1)
        axis.set_xlim(min(xmins) - 1, max(xmaxs) + 1)
        # Make sure zero is included in the x-range.
        minx, maxx = axis.get_xlim()
        if minx > -1: axis.set_xlim(xmin=-1)
        if maxx < 1: axis.set_xlim(xmax=1)

        # Spruce the graph up a bit.
        axis.set_xlabel(self.xlabel)
        axis.set_ylabel(self.ylabel)
        axis.set_yticks(ys)
        axis.set_clip_on(False)
        axis.set_yticklabels([ x.metric for x in self.data ],
                               size=self.labelpointsize)
        for x in axis.get_xmajorticklabels(): x.set_size(self.labelpointsize)

        # Add a vertical line at x == 0.
        axis.axvline()
        # Draw horizontal lines for the effect size range of each metric.
        axis.hlines(ys, xmins, xmaxs)
        # Plot the mid-points of the horizontal lines.
        axis.plot(0.5*(xmins+xmaxs), ys, self.normalpoints)
        if len(better) > 0:
            axis.plot(0.5*(xmins[better-1]+xmaxs[better-1]), better, self.betterpoints)
        if len(worse) > 0:
            axis.plot(0.5*(xmins[worse-1]+xmaxs[worse-1]), worse, self.worsepoints)

def format(data):
    """Takes a list of MetricResults."""
    # Distinct values in data for forest plot variables:
    forestcombinations = util.combinations([ util.unique(x, data) for x in config.fgraphs ])
    forestcombinations = [ dict(zip(config.fgraphs, x)) for x in forestcombinations ]
    forestcombinations = filter(lambda x:x["benchmark"] in config.forests, forestcombinations) 
    # Distinct values in data for bar chart variables:
    barcombinations = util.combinations([ util.unique(x, data) for x in config.graphs ])
    barcombinations = [ dict(zip(config.graphs, x)) for x in barcombinations ]
    barcombinations = filter(lambda x:not x["benchmark"] in config.forests, barcombinations) 
    # Filter out omitted configurations.
    allcombinations = forestcombinations + barcombinations
    for omit in config.omit:
        sieve = lambda x:not util.all([ x[y] == omit[y] for y in omit.keys() if x.has_key(y)])
        allcombinations = filter(sieve, allcombinations)
    # Create the graph objects.
    figures = []
    for configuration in allcombinations:
        if configuration in forestcombinations:
            graphtype = ForestPlot
        else:
            graphtype = BarChart
        sorteddata = graphtype.sortdata(data, configuration)
        if sorteddata: graph = graphtype(sorteddata)
        else: continue
        graph.create()
        figures.append(graph)
    return figures        
