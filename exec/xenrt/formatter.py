#!/usr/bin/python
#
# XenRT: Test harness for Xen and the XenServer product family
#
# HTML results formatter.
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys,xml.dom.minidom,tempfile,os,stat,getopt

__all__ = ["Formatter"]

class Formatter(object):
    """XenRT Results Formatter"""

    def getValue(self,node,value,unknown=None):
        # Get the contents of the value 'value' in node 'node'
        childNodes = node.childNodes
        valueNodes = node.getElementsByTagName(value)
        if (len(valueNodes) > 0 and childNodes.count(valueNodes[0]) > 0):
            return valueNodes[0].childNodes[0].data.strip()
        else:
            return unknown
    
    def getAllValues(self,node,value):
        # Get the contents of all values 'value' in node 'node'
        childNodes = node.childNodes
        valueNodes = node.getElementsByTagName(value)
        retList = []
        for node in valueNodes:
            if (childNodes.count(node) > 0):
                retList.append(node.childNodes[0].data.strip())
        return retList
    
    def getTests(self,group):
        # Get all the tests for the group, and return a list of 
        # test,result,subtests pairs
        tests = group.getElementsByTagName("test")
        childNodes = group.childNodes
        retList = []
        for test in tests:
            if (childNodes.count(test) > 0):
                name = self.getValue(test,"name")
                state = self.getValue(test,"state")
                subtests = test.getElementsByTagName("group")
                sts = []
                if (len(subtests) > 0):
                    for subtest in subtests:
                        stname = self.getValue(subtest,"name")
                        sttests = self.getTests(subtest) 
                        sts.append((stname,sttests))   
                retList.append((name,state,sts))
    
        return retList
            
    def getGroups(self,sequence):
        # Get all the groups for this sequence
        return sequence.getElementsByTagName("testgroup")
    
    def doCounts(self,seqResults):
        # Get counts
        counts = {'tcs':0,'pass':0,'partial':0,'fail':0,'error':0,'notrun':0,
                  'skipped':0}
        for group in seqResults:
            for test in group[1]:
                counts['tcs'] += 1
                counts[test[1]] += 1
                for subgroup in test[2]:
                    for subtest in subgroup[1]:
                        counts['tcs'] += 1
                        counts[subtest[1]] += 1   
    
        return counts
    
    def usage(self,fd):
        fd.write("""Usage: %s [args]
    
    --usage                     Usage Information (this message)
    
    Source Arguments:
   
     --xmlfile                   The XML file to read from
    
    Destination Arguments:

    --stdout                    Write HTML to stdout (default)

    --htmlfile                  An HTML file to write to
                                (assumes one sequence in file)

    --htmldir                   An HTML directory to write to
                                (files will be named by sequence name or
                                randomly if no name in file)

""" % (sys.argv[0]))

    def main(self):
        # Process options
        xmlFile = None
        htmlFile = None
        htmlDir = None
    
        optlist, optargs = getopt.getopt(sys.argv[1:],'',
                                         ['stdout',
                                          'xmlfile=',
                                          'htmlfile=',
                                          'htmldir=',
                                          'usage'])
        for argpair in optlist:
            (flag,value) = argpair
            if (flag == "--usage"):
                self.usage(sys.stdout)
                sys.exit(0)
            elif (flag == "--stdout"):
                htmlFile = None
                htmlDir = None
            elif (flag == "--xmlfile"):
                xmlFile = value
            elif (flag == "--htmlfile"):
                htmlFile = value
            elif (flag == "--htmldir"):
                # Trim trailing /
                if (value[-1] == "/"):
                    htmlDir = value[:-1]
                else:
                    htmlDir = value
    
        if (xmlFile == None):
            sys.stderr.write("You must specify an XML File!\n")
            self.usage(sys.stdout)
            sys.exit(1)
    
        if (htmlDir != None and htmlFile != None):
            sys.stderr.write("You cannot specify both htmlfile and htmldir\n")
            sys.exit(1)
    
        # Read in the file
        dom = xml.dom.minidom.parse(xmlFile)
    
        # Get all sequences from the file
        seqs = dom.getElementsByTagName("sequenceresults")
    
        # Generate a results page for each sequence
        for seq in seqs:
            html = self.generateHTML(seq)
            if (htmlFile == None and htmlDir == None):
                print html
            elif (htmlFile != None):
                f = open(htmlFile, "w")
                f.write(html)
                f.close()
            elif (htmlDir != None):
                self.writeDir(seq,html,htmlDir)
    
    def processXML(self,xmlFile,htmlDir):
        # Process xmlFile and store the result in htmlDir
        dom = xml.dom.minidom.parse(xmlFile)
    
        seqs = dom.getElementsByTagName("sequenceresults")
        for seq in seqs:
            html = self.generateHTML(seq)
            self.writeDir(seq,html,htmlDir)
    
    def writeDir(self,seq,html,htmlDir):
        fileName = self.getValue(seq,"name")
        if (fileName == None):
            f, fileName = tempfile.mkstemp(".html","xenrt",htmlDir)
            os.close(f)
            os.chmod(fileName,
                     stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP |
                     stat.S_IWGRP | stat.S_IROTH)
        else:
            fileName = htmlDir + "/" + fileName + ".html"
        f = open(fileName, "w")
        f.write(html)
        f.close()
    
    def generateHTML(self,seq):
        seqResults = []
        seqName = self.getValue(seq,"name","Unknown")
        seqState = self.getValue(seq,"sequence","Unknown")
        jobDetails = seq.getElementsByTagName("jobdetails")
        if (len(jobDetails) > 0):
            version = self.getValue(jobDetails[0],"version","Unknown")
            revision = self.getValue(jobDetails[0],"revision","Unknown")
            hosts = self.getAllValues(jobDetails[0],"host")
            firsthost = True
            hostsStr = ""
            for host in hosts:
                if (firsthost):
                    hostsStr = host
                    firsthost = False
                else:
                    hostsStr += ", " + host
        else:
            version = "Unknown"
            revision = "Unknown"
            hostsStr = ""
        groups = self.getGroups(seq)
        for group in groups:
            name = self.getValue(group,"name")
            seqResults.append((name,self.getTests(group)))
    
        counts = self.doCounts(seqResults)
    
        html = """<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">
<html>
  <head>
    <title>XenRT Report</title>
    <meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">
    <style type="text/css">
body {
    font: 8pt/16pt verdana,sans-serif;
    }

#header h1 {
    text-align: center;
    font: 26pt verdana,sans-serif;
    }

#summary table {
    border-width: 1px 1px 1px 1px;
    border-spacing: 2px;
    border-style: outset outset outset outset;
    boder-color: gray;
    border-collapse: separate;
    float: left;
    margin-right: 50px;
    margin-bottom: 50px;
    }
#summary th {
    text-align: left;
    }

#details {
    font: 12pt verdana,sans-serif;
    float: left;
    margin-bottom: 50px;
    }

#results {
    clear: left;
    }

#results h2 {
    font: 18pt verdana,sans-serif;
    }

.testresults {
    font: 8pt verdana,sans-serif;
    border-width: 1px 1px 1px 1px;
    border-spacing: 2px;
    border-style: outset outset outset outset;
    border-color: gray gray gray gray;
    border-collapse: separate;
    }
.testresults td {
    border-width: 1px 1px 1px 1px;
    padding: 1px 1px 1px 0px;
    border-style: inset inset inset inset;
    border-color: white white white white;
    }
.testresults th {
    border-width: 1px 1px 1px 1px;
    padding: 1px 1px 1px 1px;
    border-style: inset inset inset inset;
    border-color: white white white white;
    text-align: left;
    font: bold 12pt verdana,sans-serif;
    }
.grp {
    text-indent: 20px;
     }
.stst {
    text-indent: 40px;
    }

.testgroup {
    font: bold 14pt verdana,sans-serif;
    }
    </style>
  </head>
  <body id="xenrt_report">
  <div id="container">
    <div id="header">
      <h1><span>XenRT Report</span></h1>
    </div>
    <div id="summary">
      <table>
      <tr><th colspan="2">Summary</th></tr>
      <tr><td>Tests:</td><td>%d</td></tr>
      <tr><td>Passed:</td><td>%d</td></tr>
      <tr><td>Partialled:</td><td>%d</td></tr>
      <tr><td>Failed:</td><td>%d</td></tr>
      <tr><td>Errored:</td><td>%d</td></tr>
      <tr><td>Not run:</td><td>%d</td></tr>
      <tr><td>Skipped:</td><td>%d</td></tr>
     </table>
    </div>
    <div id="details">
      <b>Sequence:</b> %s<br>
      <b>Result:</b> %s<br>
      <b>Version:</b> %s<br>
      <b>Revision:</b> %s<br>
      <b>Hosts:</b> %s
    </div>
    <div id="results">
      <hr>
      <h2>Specific Test Results</h2>
""" % (counts['tcs'],counts['pass'],counts['partial'],counts['fail'],
       counts['error'],counts['notrun'],counts['skipped'],seqName,
       seqState,version,revision,hostsStr)

        for group in seqResults:
            html += ("""<table class="testresults">
      <tr><td colspan="2" class="testgroup"><b>%s</b></td></tr>
      <tr><th>Test</th><th>State</th></tr>""" % (group[0]))
            for test in group[1]:
                html += ("<tr><td>%s</td><td>%s</td></tr>\n" % (test[0],
                                                                test[1]))
                for sgroup in test[2]:
                    html += "<tr><td colspan=\"2\" class=\"grp\">"
                    html += ("%s</td></tr>\n" % (sgroup[0]))
                    for stest in sgroup[1]:
                        html += "<tr><td class=\"stst\">"
                        html += ("%s</td><td>%s</td></tr>\n""" % (stest[0],
                                                                  stest[1]))
            html += """</table>
      <p>&nbsp;</p>
"""
        html += """</div>
  </div>
  </body>
</html>
"""

        return html


if __name__ == '__main__':
    fmtr = Formatter()
    fmtr.main()

