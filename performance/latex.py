#!/usr/bin/env python

#
# latex.py
#
# Methods to output Latex code for XenRT performance reports.
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import string, re, os, shutil, tempfile, numpy, matplotlib.pyplot 

import config, format, util, db, perfdata
# TODO
config.templatedir = "."

TABLEROW = r"""
\rowcolor{%s} %s & %.1f & %d & %.1f & %d & %1.2f\%%
"""

INCLUDE = r"""
\%ssection{%s}
\label{%s}

\begin{figure}[htbp]
\centering
\includegraphics[width=0.8\textwidth]{%s/images/%s.pdf}
\caption{%s Results}
\input{%s/tables/%s.tex}
\end{figure}

\newpage
"""

TABLE = r"""
\vspace{10mm}
{\scriptsize
\begin{tabular}{|c|c|c|c|c|c|}
\hline
Configuration & Product & Product Count & Reference & Reference Count & Difference \\ \hline
%s
\hline
\end{tabular}}
"""

SUMMARY = r"""
\begin{itemize}
\item Metrics measured: %s
\vspace{5mm}
\item Significant results: %s (%1.1f\%%)
\item Significant performance improvements: %s (%1.1f\%%)
\item Significant performance losses: %s (%1.1f\%%)
\end{itemize}
"""

class PerformanceReport:

    def __init__(self, data, product, reference):
        self.data = data
        self.product = product
        self.reference = reference

        self.path = tempfile.mkdtemp()
        self.metrics = len(self.data)

        self.items = [ PerformanceReportItem(self.path, x) for x in format.format(self.data) ]

    def write(self, significant=True):
        print "Placing output in %s." % (self.path)

        os.makedirs("%s/images" % (self.path))
        os.makedirs("%s/tables" % (self.path))
        
        shutil.copyfile("%s/report-template.tex" % (config.templatedir), 
                        "%s/report.tex" % (self.path))    
        shutil.copyfile("%s/forestexample.pdf" % (config.templatedir), 
                        "%s/forestexample.pdf" % (self.path))    
        shutil.copyfile("%s/barexample.pdf" % (config.templatedir), 
                        "%s/barexample.pdf" % (self.path))    
 
        # Filter out the significant results if required.
        items = self.items
        if significant:
            items = filter(lambda x:True in map(lambda y:y.significant(), x.graph.data), items)
 
        # Create the graph PDFs and data tables.
        for i in items:
            i.graph.plot(self.path + "/images/")
            file("%s/tables/%s.tex" % (self.path, i.graph.filename), "w").write(i.table()) 
        
        for o in reversed(config.displayorder):
            items.sort(key=lambda x:getattr(x.graph.data[0], o))
    
        # Create the Latex markup for the results.
        marker = config.documentsections 
        fd = file("%s/data.tex" % (self.path), "w")
        for i in items:
            key = [ getattr(i.graph.data[0], x) for x in config.documentsections ]
            if not marker == key:
                firstdiff = min([ x for x in range(len(marker)) if not marker[x] == key[x]])
                for x in range(firstdiff, len(marker)):
                    fd.write("\n\\%ssection{%s}" % ("sub" * x, string.upper(key[x])))
                marker = key
            fd.write("%s\n" % (i.include()))
        fd.close()

        # Create the summary.
        n = self.metrics 
        s = filter(lambda x:x.significant(), self.data)
        b = filter(lambda x:x.better(), self.data)
        w = filter(lambda x:x.significant() and not x.better(), self.data)
        summary = SUMMARY % (n, 
                             len(s), 100*len(s)/n, 
                             len(b), 100*len(b)/n, 
                             len(w), 100*len(w)/n)
        file("%s/summary.tex" % (self.path), "w").write(summary)

        # Create distribution graphs.
        def cumulativeGraph(points): 
            width = 1.0
            values = []
            labels = []
            limit = 0 
            while True:
                count = len(filter(lambda x:abs(x.relative) > limit, points))
                if not count: break
                labels.append(limit)
                values.append(count)
                limit = limit + limit
                if not limit: limit = 1
            index = numpy.arange(len(values))
            figure = matplotlib.pyplot.figure()
            axis = figure.add_subplot(111)
            chart = axis.bar(index, values, width)
            axis.set_xticklabels(labels)
            return figure, axis    

        figure, axis = cumulativeGraph(b)
        axis.set_ylabel("Significant Performance Improvements")
        axis.set_xlabel("Magnitude of Improvement (%)")
        figure.savefig("%s/bettercount.pdf" % (self.path))
        
        figure, axis = cumulativeGraph(w)
        axis.set_ylabel("Significant Performance Losses")
        axis.set_xlabel("Magnitude of Loss (%)")
        figure.savefig("%s/worsecount.pdf" % (self.path))

        fd = file("%s/report.tex" % (self.path), "r")
        report = fd.read()
        fd.close()
        report = re.sub("PATH", self.path, report)
        report = re.sub("PRODUCT", self.product, report)
        report = re.sub("REFERENCE", self.reference, report)
        fd = file("%s/report.tex" % (self.path), "w")
        fd.write(report)
        fd.close()

        # Generate the PDF. Two runs are necessary to create the TOC.
        for i in range(2):
            os.system("pdflatex -output-directory %s %s/report.tex " \
                      "-interaction batchmode 2>&1 > %s/report-%s.err" % \
                      (self.path, self.path, self.path, i))

class PerformanceReportItem:

    def __init__(self, path, graph):
        self.path = path
        self.graph = graph

    def include(self, level=""):
        level = "sub" * len(config.documentsections)
        configuration = self.graph.getConfiguration()
        # Function to clean up the config strings.
        sanitise = lambda x:str(util.ci(x))
        caption = [] 
        for k in config.displayorder:
            if not configuration.has_key(k):
                continue
            configuration[k] = sanitise(configuration[k])
            # Don't repeat information in the report.
            #if not k in config.documentsections:
            caption.append("%s %s" % (string.upper(str(configuration[k])),
                                      config.configvariables[k]))
        caption = string.join(caption)
        caption = re.sub("_", "-", caption)
        return INCLUDE % (level,
                          caption, 
                          self.graph.filename, 
                          self.path, 
                          self.graph.filename, 
                          caption, 
                          self.path, 
                          self.graph.filename)
   
    def table(self):
        configuration = self.graph.getConfiguration()
        sanitise = lambda x:str(util.ci(x))
        # Include those variables which vary in the graph.
        headingkeys = [ x for x in config.configvariables.keys() \
                        if x not in configuration.keys() ]
        # Create a row for each data point.
        rows = []
        for x in self.graph.data:
            heading = [ "%s %s" % (util.ci(getattr(x, k)), config.configvariables[k]) \
                         for k in headingkeys ]
            heading = string.join(heading)
            colour = (x.better() and "green") or \
                     (x.significant() and "red") or "white"
            row = TABLEROW % (colour,
                              heading,
                              x.productdata.mean,
                              x.productdata.count,
                              x.referencedata.mean,
                              x.referencedata.count,
                              x.relative)
            row = re.sub("_", "\_", row)
            rows.append(row)
        rows = string.join(rows, "\\\\ \hline\n")
        rows += "\\\\ \hline\n"
        return TABLE % rows
