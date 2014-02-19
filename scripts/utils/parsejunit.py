#!/usr/bin/python
#
# XenRT: Parse a JUnit XML results file to extract the required data
#
# (C) XenSource UK Ltd. 2006
# James Bulpin, May 2006

import sys
import xml.dom.minidom
import string, getopt

usage = """
Usage: parsejunit.py [options] -F <JUnit XML results file>

  -r     Print the test results
  -f     Print only failure messages
  -c     Check for failures - returns non-zero if any failures seen
"""

printresult = 0
printfail = 0
checkfail = 0
domfile = None

try:
    optlist, optx = getopt.getopt(sys.argv[1:], 'frchF:')
    for argpair in optlist:
        (flag, value) = argpair
        if flag == "-h":
            print usage
            sys.exit(0)
        elif flag == "-r":
            printresult = 1
        elif flag == "-f":
            printfail = 1
        elif flag == "-c":
            checkfail = 1
        elif flag == "-F":
            domfile = value    

except getopt.GetoptError:
    sys.stderr.write("Unknown argument\n")
    sys.exit(1)

if not domfile:
    sys.stderr.write("Must supply an XML file to parse\n")
    sys.exit(1)

fails = 0

def handleFailure(f, usetype=0):
    message = f.getAttribute("message")
    if message:
        if usetype:
            etype = f.getAttribute("type")
            if etype:
                message = etype + " " + message
        return message
    return "no failure message available"

def handleTestCase(c):
    global fails
    name = c.getAttribute("name")
    if not name:
        name = os.path.basename(domfile)
    failmsg = None
    errormsg = None
    for i in c.childNodes:
        if i.nodeType == i.ELEMENT_NODE:
            if i.localName == "failure":
               failmsg = handleFailure(i)
            elif i.localName == "error":
               errormsg = handleFailure(i)
    if failmsg:
        fails = fails + 1
        if printresult:
            print "%s FAIL %s" % (name, failmsg)
        if printfail:
            print failmsg
    elif errormsg:
        fails = fails + 1
        if printresult:
            print "%s ERROR %s" % (name, errormsg)
        if printfail:
            print errormsg
    else:
        if printresult:
            print "%s PASS" % (name)
               
def handleTestSuite(s):
    global fails
    for i in s.childNodes:
        if i.nodeType == i.ELEMENT_NODE:
            if i.localName == "testcase":
               handleTestCase(i)
            elif i.localName == "error":
               errormsg = handleFailure(i, usetype=1)
               if errormsg:
                   fails = fails + 1
                   if printresult:
                       print "ERROR %s" % (errormsg)
                   if printfail:
                       print errormsg

def handleFile(f):
    for i in f.childNodes:
        if i.nodeType == i.ELEMENT_NODE:
            if i.localName == "testsuite":
               handleTestSuite(i)

# JUnit sometimes creates a file with a trailing '\n>' which breaks parsing.
# The loop here is a dodgy hack to deal with this.
domtext = ""
f = file(domfile, 'r')
while 1:
    line = f.readline()
    if not line:
        break
    domtext = domtext + line
f.close()
i = 0
while i < 5:
    try:
        dom = xml.dom.minidom.parseString(domtext[:0-i])
        break
    except:
        i = i + 1
        dom = None

if not dom:
    raise "Could not parse XML file"

handleFile(dom)

if checkfail and fails:
    sys.exit(1)
