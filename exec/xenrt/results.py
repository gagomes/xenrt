#
# XenRT: Test harness for Xen and the XenServer product family
#
# Results parser.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, xml.dom.minidom, re, threading, traceback
import xenrt

__all__ = ["TestResults",
           "TestCaseItem",
           "TestGroup",
           "GlobalGroup",
           "GlobalResults"]

def encodeAmpersand(rematch):
    g = rematch.group(1)
    if g == "&":
        return "&amp;"
    return g

class TestCaseItem(object):
    """Represents a single test case result"""
    def __init__(self, group):
        self.group = group
        self.name = None
        self.result = xenrt.RESULT_UNKNOWN
        self.allowed = False
        self.log = None
        self.reasons = []
        self.warnings = []
        self.priority = None

    def debugPrint(self, fd):
        fd.write("    Test %-30s %s\n" %
                 (self.name, xenrt.resultDisplay(self.result)))

    def setResult(self, result, reason=None, priority=None):
        self.result = result
        if reason:
            self.reasons.append(reason.strip())
        if priority != None and self.priority == None:
            self.priority = priority

    def getResult(self):
        return self.result

    def resultWithAllowed(self, counters, topgroup, toptest):
        if self.result < len(counters):
            counters[self.result] = counters[self.result] + 1
        if self.result == xenrt.RESULT_FAIL:
            # Check if this is allowed to fail
            if self.allowed:
                return xenrt.RESULT_PASS
            if len(self.reasons) == 0:
                xenrt.TEC().comment("Disallowed failure %s/%s" %
                                    (self.group.name, self.name))
            else:
                r = string.join(self.reasons, ", ")
                xenrt.TEC().comment("Disallowed failure %s/%s: %s" %
                                    (self.group.name, self.name, r))
            
            xenrt.TEC().logverbose(traceback.format_exc())
            return xenrt.RESULT_FAIL
        elif self.result == xenrt.RESULT_ERROR:
            # Check if this is allowed to fail
            if self.allowed:
                return xenrt.RESULT_PASS
            if len(self.reasons) == 0:
                xenrt.TEC().comment("Error %s/%s" %
                                    (self.group.name, self.name))
            else:
                r = string.join(self.reasons, ", ")
                xenrt.TEC().comment("Error %s/%s: %s" %
                                    (self.group.name, self.name, r))
            return xenrt.RESULT_ERROR
        else:
            return xenrt.RESULT_PASS

    def gather(self, list, topgroup, toptest):
        """Gather all leafnode test results into a list"""
        if self.allowed:
            r = xenrt.RESULT_ALLOWED
        else:
            r = self.result
        list.append([topgroup, toptest, self.group.name, self.name, r,
                     self.priority])

    def summary(self, fd, topgroup, toptest):
        notes = []
        if self.result == xenrt.RESULT_FAIL:
            if self.allowed:
                notes.append("allowed")
        n = "%s/%s" % (self.group.name, self.name)
        if self.priority == None:
            p = "  "
        else:
            p = "P%u" % (self.priority)
        fd.write("  %-28s %s %s %s\n" % (n,
			       		xenrt.resultDisplay(self.result),
			     		p,
			   		string.join(notes)))

    def getFailures(self, reply, topgroup, toptest):
        if self.result == xenrt.RESULT_FAIL:
            reply.append((topgroup, toptest, self.group.name, self.name))

    def getTestCases(self, reply, topgroup, toptest):
        reply.append((topgroup, toptest, self.group.name, self.name))
    
    def processNode(self, node, priority=None):
        rescount = 0
        if priority:
            self.priority = priority
        for n in node.childNodes:
            if n.nodeType == n.ELEMENT_NODE:
                if n.localName == "name":
                    for a in n.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            self.name = str(a.data)
                elif n.localName == "state":
                    for a in n.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            rescount = 1
                            s = string.lower(str(a.data))
                            if s in ("pass", "success"):
                                self.result = xenrt.RESULT_PASS
                            elif s in ("warning", "warnings_issued"):
                                self.result = xenrt.RESULT_PASS
                                self.warnings = "Warning in log output"
                            elif s in ("fail", "failed"):
                                self.result = xenrt.RESULT_FAIL
                            elif s in ("skip", "skipped"):
                                self.result = xenrt.RESULT_SKIPPED
                            elif s == "xpass":
                                self.result = xenrt.RESULT_PASS
                                self.allowed = True
                            elif s == "xfail":
                                self.result = xenrt.RESULT_FAIL
                                self.allowed = True
                elif n.localName == "log":
                    for a in n.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            self.log = str(a.data)
        return rescount

    def createXMLNode(self, doc):
        t = doc.createElement("test")
        tn = doc.createElement("name")
        t.appendChild(tn)
        n = doc.createTextNode(str(self.name))
        tn.appendChild(n)
        ts = doc.createElement("state")
        t.appendChild(ts)
        tst = doc.createTextNode(str(xenrt.resultDisplay(self.result)))
        ts.appendChild(tst)
        if self.result == xenrt.RESULT_FAIL and self.allowed:
            ts = doc.createElement("allowed")
            t.appendChild(ts)
            tst = doc.createTextNode("yes")
            ts.appendChild(tst)
        if self.log:
            tl = doc.createElement("log")
            t.appendChild(tl)
            tlt = doc.createTextNode(str(self.log))
            tl.appendChild(tlt)
        for reason in self.reasons:
            tr = doc.createElement("reason")
            t.appendChild(tr)
            trt = doc.createTextNode(str(reason))
            tr.appendChild(trt)
        return t

class TestGroup(object):
    """Represents a group of test cases."""
    def __init__(self):
        self.name = None
        self.tests = {}
        self.testsOrder = []

    def debugPrint(self, fd):
        fd.write("  Group %s:\n" % (self.name))
        for t in self.testsOrder:
            self.tests[t].debugPrint(fd)
            
    def setResult(self, testcase, result, reason=None, priority=None):
        if not self.tests.has_key(testcase):
            t = TestCaseItem(self)
            t.name = testcase
            self.tests[t.name] = t
            self.testsOrder.append(t.name)
        self.tests[testcase].setResult(result, reason=reason,
                                       priority=priority)

    def aggregate(self, counters, topgroup, toptest, tr):
        passed = True
        errored = False
        for tn in self.testsOrder:
            t = self.tests[tn]
            r = t.resultWithAllowed(counters, topgroup, toptest)
            if r != xenrt.RESULT_PASS:
                passed = False
                if r == xenrt.RESULT_ERROR:
                    errored = True
            # If the subcase has a higher priority than the testcase then
            # raise the testcase priority to match
            if t.priority != None and t.priority < tr.priority:
                tr.priority = t.priority
            # If the subcase has no set priority then inherit
            if t.priority != None and tr.priority == None:
                tr.priority = t.priority
        if passed:
            return xenrt.RESULT_PASS
        if errored:
            return xenrt.RESULT_ERROR
        return xenrt.RESULT_FAIL

    def gather(self, list, topgroup, toptest):
        """Gather all leafnode test results into a list"""
        for tn in self.testsOrder:
            t = self.tests[tn]
            t.gather(list, topgroup, toptest)

    def summary(self, fd, topgroup, toptest):
        for tn in self.testsOrder:
            t = self.tests[tn]
            t.summary(fd, topgroup, toptest)

    def getFailures(self, reply, topgroup, toptest):
        for tn in self.testsOrder:
            t = self.tests[tn]
            t.getFailures(reply, topgroup, toptest)
            
    def getTestCases(self, reply, topgroup, toptest):
        for tn in self.testsOrder:
            t = self.tests[tn]
            t.getTestCases(reply, topgroup, toptest)
    
    def processNode(self, node, priority=None):
        counter = 0
        rescount = 0
        for n in node.childNodes:
            if n.nodeType == n.ELEMENT_NODE:
                if n.localName == "name":
                    for a in n.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            self.name = str(a.data)
                elif n.localName == "test":
                    t = TestCaseItem(self)
                    rescount = rescount + t.processNode(n, priority=priority)
                    while not t.name:
                        # make up a test name
                        name = "testcase%u" % (counter)
                        counter = counter + 1
                        if not self.tests.has_key(name):
                            t.name = name
                    self.tests[t.name] = t
                    self.testsOrder.append(t.name)
        return rescount

    def createXMLNode(self, doc):
        g = doc.createElement("group")
        gn = doc.createElement("name")
        g.appendChild(gn)
        n = doc.createTextNode(str(self.name))
        gn.appendChild(n)
        for tn in self.testsOrder:
            t = self.tests[tn]
            tnode = t.createXMLNode(doc)
            g.appendChild(tnode)
        return g

class TestResults(object):
    """Parse a test report file."""
    def __init__(self, priority=1):
        self.overall = xenrt.RESULT_UNKNOWN
        self.allowed = False
        self.groups = {}
        self.groupsOrder = []
        self.reasons = []
        self.perfdata = []
        self.priority = priority
        self.warnings = []
        self.appresults = []
        self.comments = []

    def debugPrint(self, fd):
        fd.write("Test results:\n")
        for g in self.groupsOrder:
            self.groups[g].debugPrint(fd)

    def setOverallResult(self, result):
        self.overall = result

    def getOverallResult(self):
        return self.overall

    def setResult(self, group, testcase, result, reason=None):
        if not group:
            group = "DEFAULT"
        if not self.groups.has_key(group):
            g = TestGroup()
            g.name = group
            self.groups[g.name] = g
            self.groupsOrder.append(g.name)
        self.groups[group].setResult(testcase, result, reason=reason,
                                     priority=self.priority)

    def comment(self, comment):
        self.comments.append(comment)

    def appresult(self, appresult):
        self.appresults.append(appresult)

    def warning(self, warning):
        self.warnings.append(warning)

    def reason(self, reason):
        self.reasons.append(reason.strip())

    def aggregate(self, topgroup, toptest):
        """Declare the test outcome based on testcase results."""
        passed = True
        errored = False
        counters = []
        for i in range(len(xenrt.RESULTS)):
            counters.append(0)
        for gn in self.groupsOrder:
            g = self.groups[gn]
            r = g.aggregate(counters, topgroup, toptest, self)
            if r != xenrt.RESULT_PASS:
                passed = False
                if r == xenrt.RESULT_ERROR:
                    errored = True
        # If we've previously set an outcome then we don't change it now
        if self.overall == xenrt.RESULT_UNKNOWN:
            if passed:
                self.overall = xenrt.RESULT_PASS
            elif errored:
                self.overall = xenrt.RESULT_ERROR
            else:
                self.overall = xenrt.RESULT_FAIL
        # A failure/error should override a partial result
        elif self.overall == xenrt.RESULT_PARTIAL and not passed:
            if errored:
                self.overall = xenrt.RESULT_ERROR
            else:
                self.overall = xenrt.RESULT_FAIL
        # Check if the entire test is allowed to pass
        for i in range(len(xenrt.RESULTS)):
            xenrt.TEC().comment("Testcases %s %u" % (xenrt.resultDisplay(i),
                                                     counters[i]))

    def gather(self, list, topgroup, toptest):
        """Gather all leafnode test results into a list"""
        if len(self.groupsOrder) == 0:
            if self.allowed:
                r = xenrt.RESULT_ALLOWED
            else:
                r = self.overall
            list.append([topgroup, toptest, None, None, r, self.priority])
        else:
            for gn in self.groupsOrder:
                g = self.groups[gn]
                g.gather(list, topgroup, toptest)

    def summary(self, fd, topgroup, toptest):
        notes = []
        if self.overall == xenrt.RESULT_FAIL:
            if self.allowed:
                notes.append("allowed")
        if topgroup == '':
            n = toptest
        else:
            n = "%s/%s" % (topgroup, toptest)
        fd.write("%-30s %s P%u %s\n" % (n,
                                        xenrt.resultDisplay(self.overall),
                                        self.priority,
                                        string.join(notes)))
        for gn in self.groupsOrder:
            g = self.groups[gn]
            g.summary(fd, topgroup, toptest)

    def processResultsNode(self, node):
        counter = 0
        rescount = 0
        for n in node.childNodes:
            if n.nodeType == n.ELEMENT_NODE and n.localName == "group":
                g = TestGroup()
                rescount = rescount + g.processNode(n, priority=self.priority)
                while not g.name:
                    # make up a group name
                    name = "group%u" % (counter)
                    counter = counter + 1
                    if not self.groups.has_key(name):
                        g.name = name
                self.groups[g.name] = g
                self.groupsOrder.append(g.name)
            elif n.nodeType == n.ELEMENT_NODE and n.localName == "status":
                for a in n.childNodes:
                    if a.nodeType == a.TEXT_NODE:
                        status = str(a.data).strip()
                        if status.lower() == "running":
                            g = TestGroup()
                            g.name = "_TestCase"
                            t = TestCaseItem(g)
                            t.name = "StillRunning"
                            t.result = xenrt.RESULT_FAIL
                            g.tests[t.name] = t
                            g.testsOrder.append(t.name)
                            self.groups[g.name] = g
                            self.groupsOrder.append(g.name)
                            rescount = rescount + 1
            # In case the external test script is (incorrectly) producing
            # the XML format generated by XenRT (where the entire TC result
            # is summarised in the XML adding an extra <test> node the tree)
            # then work around it.
            if n.nodeType == n.ELEMENT_NODE and n.localName == "test":
                self.processResultsNode(n)
        return rescount

    def getFailures(self, topgroup, toptest):
        reply = []
        if self.overall == xenrt.RESULT_FAIL:
            reply.append((topgroup, toptest, 'ALL', 'ALL'))
        for gn in self.groupsOrder:
            g = self.groups[gn]
            g.getFailures(reply, topgroup, toptest)
        return reply

    def getTestCases(self, topgroup, toptest):
        reply = []
        reply.append((topgroup, toptest, 'ALL', 'ALL'))
        for gn in self.groupsOrder:
            g = self.groups[gn]
            g.getTestCases(reply, topgroup, toptest)
        return reply

    def parseFile(self, filename):
        """Parse a results file into this object."""
        # See whether we need to work around xm-test's dodgy XML
        count = 0
        f = file(filename, "r")
        line = f.readline()
        try:
            line2 = f.readline()
        except:
            line2 = ""
        f.close()
        if re.search(r"<results>", line) or \
                (re.search(r"<\?xml version", line) and
                 re.search(r"<results>", line2)):
            # Well formed XML, well, maybe...
            fn = xenrt.TEC().tempFile()
            fin = file(filename, "r")
            fout = file(fn, "w")
            while True:
                line = fin.readline()
                if not line:
                    break
                line = re.sub(r"(&[^\s&<>]*)", encodeAmpersand, line)
                fout.write(line)
            fout.close()
            fin.close()
            x = xml.dom.minidom.parse(fn)
            for n in x.childNodes:
                if n.nodeType == n.ELEMENT_NODE and n.localName == "results":
                    count = count + self.processResultsNode(n)
        else:
            # Read the whole file in and wrap
            text = "<wrapper>\n"
            tr = ""
            for i in range(256):
                if i < 32:
                    tr = tr + " "
                elif i < 128:
                    tr = tr + chr(i)
                else:
                    tr = tr + " "
            f = file(filename, "r")
            data = f.read()
            f.close()
            # Remove any control characters (from log files mainly)
            text = text + string.translate(data, tr)
            text = text + "</wrapper>\n"
            x = xml.dom.minidom.parseString(text)
            for n in x.childNodes:
                if n.nodeType == n.ELEMENT_NODE and n.localName == "wrapper":
                    for i in n.childNodes:
                        if i.nodeType == i.ELEMENT_NODE and \
                               i.localName == "results":
                            count = count + self.processResultsNode(i)
        return count

    def createXMLNode(self, doc, tc):
        t = doc.createElement("test")
        tn = doc.createElement("name")
        t.appendChild(tn)
        n = doc.createTextNode(str(tc.basename))
        tn.appendChild(n)
        ts = doc.createElement("state")
        t.appendChild(ts)
        tst = doc.createTextNode(str(xenrt.resultDisplay(self.overall)))
        ts.appendChild(tst)
        for reason in self.reasons:
            tr = doc.createElement("reason")
            t.appendChild(tr)
            trt = doc.createTextNode(str(reason))
            tr.appendChild(trt)
        for perf in self.perfdata:
            p, v, u = perf
            tr = doc.createElement("value")
            tr.setAttribute("param", str(p))
            if u:
                tr.setAttribute("units", str(u))
            t.appendChild(tr)
            trt = doc.createTextNode(str(v))
            tr.appendChild(trt)
        for gn in self.groupsOrder:
            g = self.groups[gn]
            gnode = g.createXMLNode(doc)
            t.appendChild(gnode)
        return t

    def generateXML(self, filename, tc):
        """Generate an XML file containing this test result data."""
        xenrt.TEC().progress("Writing test results to %s" % (filename))
        impl = xml.dom.minidom.getDOMImplementation()
        newdoc = impl.createDocument(None, "results", None)
        n = self.createXMLNode(newdoc, tc)
        newdoc.documentElement.appendChild(n)
        if filename:
            f = file(filename, "w")
            newdoc.writexml(f, addindent="  ", newl="\n")
            f.close()
        else:
            return newdoc.toprettyxml("  ", "\n")

class GlobalGroup(object):
    """A top level grouping of tests."""
    def __init__(self, name):
        self.mylock = threading.Lock()
        self.name = name
        self.tests = {}
        self.testsOrder = []

    def addTest(self, tc):
        self.mylock.acquire()
        if not self.tests.has_key(tc.basename):
            self.tests[tc.basename] = tc
            self.testsOrder.append(tc.basename)
        else:
            i = 1
            while True:
                name = "%s(%u)" % (tc.basename, i)
                if not self.tests.has_key(name):
                    tc._rename(name)
                    self.tests[tc.basename] = tc
                    self.testsOrder.append(tc.basename)
                    break
                i = i + 1
        self.mylock.release()        

    def getFailures(self, reply):
        for tn in self.testsOrder:
            t = self.tests[tn]
            for r in t.getFailures():
                reply.append(r)
            
    def getTestCases(self, reply):
        for tn in self.testsOrder:
            t = self.tests[tn]
            for r in t.getTestCases():
                reply.append(r)

    def getTopLevelTests(self, reply):
        for tn in self.testsOrder:
            t = self.tests[tn]
            reply.append(t)

    def getTC(self, testname):
        return self.tests[testname]

    def setResult(self, testname, result):
        """Set a testcase result, this is for manual intervention use"""
        self.tests[testname].setResult(result)

    def getResult(self, testname):
        """Get a testcase result"""
        return self.tests[testname].getResult()

    def createXMLNode(self, doc):
        g = doc.createElement("testgroup")
        gn = doc.createElement("name")
        g.appendChild(gn)
        n = doc.createTextNode(str(self.name))
        gn.appendChild(n)
        for tn in self.testsOrder:
            t = self.tests[tn]
            tnode = t.results.createXMLNode(doc, t)
            g.appendChild(tnode)
        return g

class GlobalResults(object):
    """A top level collection of test groups"""
    def __init__(self):
        self.mylock = threading.Lock()
        self.groups = {}
        self.groupsOrder = []
    
    def addTest(self, tc):
        gid = tc.group
        if not gid:
            gid = ""
        self.mylock.acquire()
        if not self.groups.has_key(gid):
            self.groups[gid] = GlobalGroup(gid)
            self.groupsOrder.append(gid)
        self.mylock.release()
        self.groups[gid].addTest(tc)

    def getFailures(self):
        reply = []
        for gn in self.groupsOrder:
            g = self.groups[gn]
            g.getFailures(reply)
        return reply

    def getTestCases(self):
        reply = []
        for gn in self.groupsOrder:
            g = self.groups[gn]
            g.getTestCases(reply)
        return reply

    def getTopLevelTests(self):
        reply = []
        for gn in self.groupsOrder:
            g = self.groups[gn]
            g.getTopLevelTests(reply)
        return reply

    def gather(self):
        results = []
        for tc in self.getTopLevelTests():
            tc.gather(results)
        return results

    def getTC(self, groupname, testname):
        if groupname == 'Phase 99' and not self.groups.has_key(groupname):
            groupname = ""
        return self.groups[groupname].getTC(testname)

    def setResult(self, groupname, testname, result):
        """Set a testcase result, this is for manual intervention use"""
        if groupname == 'Phase 99' and not self.groups.has_key(groupname):
            groupname = ""
        self.groups[groupname].setResult(testname, result)

    def getResult(self, groupname, testname):
        """Get a testcase result"""
        if groupname == 'Phase 99' and not self.groups.has_key(groupname):
            groupname = ""
        return self.groups[groupname].getResult(testname)

    def report(self, fd, pretty=True):
        tcs = 0
        tcpass = 0
        tcfail = 0
        tcerror = 0
        tcpartial = 0
        tcblocked = 0
        tcskipped = 0
        for tc in self.getTopLevelTests():
            tcs = tcs + 1
            if tc.getOverallResult() == xenrt.RESULT_PASS:
                tcpass = tcpass + 1
            elif tc.getOverallResult() == xenrt.RESULT_FAIL:
                tcfail = tcfail + 1
            elif tc.getOverallResult() == xenrt.RESULT_PARTIAL:
                tcpartial = tcpartial + 1
            elif tc.getOverallResult() == xenrt.RESULT_ERROR:
                tcerror = tcerror + 1
            elif tc.getOverallResult() == xenrt.RESULT_NOTRUN:
                tcblocked = tcblocked + 1
            elif tc.getOverallResult() == xenrt.RESULT_SKIPPED:
                tcskipped = tcskipped + 1
            tc.summary(fd, pretty=pretty)        
        fd.write("""
Test cases:      TOTAL   %6u
                 PASS    %6u
                 PARTIAL %6u
                 FAIL    %6u
                 ERROR   %6u
                 NOTRUN  %6u
""" % (tcs, tcpass, tcpartial, tcfail, tcerror, tcblocked + tcskipped))

    def byPriority(self, countblocked=True, counterror=False, afispass=True,
                   debugfd=None):
        """Summarise results by test priority. Returns a list of pass
        rates by priority [P1, P2, ...]

        @param countblocked: if C{True} causes blocked tests to be counted as
            failures.
        @param counterror: if C{True} causes blocked tests to be counted as
            failures.
        @param afispass: if C{True} causes allowed failures to be counted
            as passes (otherwise they get ignored)
        """
        tests = []
        passes = []
        maxp = 0
        for r in self.gather():
            # For some reason we're leaking None priorities
            if r[5] == None:
                r[5] = 1

            # Extend counter arrays for this priority level
            if r[5] >= maxp:
                for i in range(1 + r[5] - maxp):
                    tests.append(0)
                    passes.append(0)
                maxp = r[5]

            # Increment counters
            if r[4] == xenrt.RESULT_PASS or r[4] == xenrt.RESULT_PARTIAL:
                tests[r[5]] = tests[r[5]] + 1
                passes[r[5]] = passes[r[5]] + 1
            elif r[4] == xenrt.RESULT_FAIL:
                tests[r[5]] = tests[r[5]] + 1
            elif r[4] == xenrt.RESULT_ERROR and counterror:
                tests[r[5]] = tests[r[5]] + 1
            elif r[4] == xenrt.RESULT_NOTRUN and countblocked:
                tests[r[5]] = tests[r[5]] + 1
            elif r[4] == xenrt.RESULT_ALLOWED and afispass:
                tests[r[5]] = tests[r[5]] + 1
                passes[r[5]] = passes[r[5]] + 1
            # Print per-test summary
            if debugfd:
                d = []
                for x in r[0:4]:
                    if x:
                        d.append(x)
                debugfd.write("%-40s P%u %s\n" % (string.join(d, "/"),
                                                  r[5],
                                                  xenrt.resultDisplay(r[4])))
        reply = []
        for i in range(len(tests)):
            if i == 0:
                continue
            if tests[i] > 0:
                r = 100.0 * float(passes[i])/tests[i]
                #print "P%u %5u/%5u %5.1f" % (i, passes[i], tests[i], r)
                reply.append(r)
            else:
                reply.append(None)
        return reply

    def check(self):
        res = self.getTopLevelTests()
        if len(res) == 0:
            if not xenrt.GEC().prepareonly:
                return False, False, None
        regok = True
        for tc in res:
            if tc.getOverallResult() == xenrt.RESULT_FAIL or \
                   tc.getOverallResult() == xenrt.RESULT_ERROR:
                if not tc.results.allowed:
                    regok = False
        counterror = xenrt.TEC().lookup("PASS_RATE_STRICT",
                                        True,
                                        boolean=True)
        rates = self.byPriority(counterror=counterror)
        cok = True
        # Check pass criteria
        criteria = string.split(xenrt.TEC().lookup("PASS_CRITERIA", ""), ",")
        for i in range(max(len(criteria), len(rates))):
            if i < len(criteria):
                if criteria[i] == "":
                    c = 100.0
                else:
                    c = float(criteria[i])
            else:
                c = 100.0
            if i < len(rates):
                if rates[i] == None:
                    r = 100.0
                else:
                    r = float(rates[i])
            else:
                r = 100.0
            if c > r:
                cok = False
            #print "P%u %f %f" % (i + 1, c, r)

        # Pretty print the actual pass rates
        pprates = []
        for i in range(len(rates)):
            if rates[i] != None:
                pprates.append("P%u:%.1f%%" % (i + 1, float(rates[i])))
        if xenrt.GEC().preparefailed:
            cok = False
            regok = False
        return cok, regok, string.join(pprates)

    def generateXML(self, filename):
        """Generate an XML file containing all result data."""
        xenrt.TEC().progress("Writing test results to %s" % (filename))
        impl = xml.dom.minidom.getDOMImplementation()
        newdoc = impl.createDocument(None, "sequenceresults", None)

        config = xenrt.GEC().config

        # Put name of sequence in if available
        if (config.defined("SEQUENCE_NAME")):
            n = newdoc.createElement("name")
            newdoc.documentElement.appendChild(n)
            na = newdoc.createTextNode(config.lookup("SEQUENCE_NAME"))
            n.appendChild(na)

        # Job details (machines used, versions etc)
        t = newdoc.createElement("jobdetails")
        newdoc.documentElement.appendChild(t)
        hosts = config.getWithPrefix("RESOURCE_HOST_")
        for host in hosts:
            h = newdoc.createElement("host")
            t.appendChild(h)
            ho = newdoc.createTextNode(host[1]) 
            h.appendChild(ho)

        # Version and revision
        if (config.defined("VERSION")):
            v = newdoc.createElement("version")
            t.appendChild(v)
            ve = newdoc.createTextNode(config.lookup("VERSION"))
            v.appendChild(ve)
        if (config.defined("REVISION")):
            r = newdoc.createElement("revision")
            t.appendChild(r)
            re = newdoc.createTextNode(config.lookup("REVISION"))
            r.appendChild(re)

        ok, regok, rates = self.check()
        t = newdoc.createElement("sequence")
        newdoc.documentElement.appendChild(t)
        if ok: 
            to = newdoc.createTextNode("PASS")
        else:
            to = newdoc.createTextNode("FAIL")
        t.appendChild(to)
        t = newdoc.createElement("regression")
        newdoc.documentElement.appendChild(t)
        if regok: 
            to = newdoc.createTextNode("PASS")
        else:
            to = newdoc.createTextNode("FAIL")
        t.appendChild(to)
        for gn in self.groupsOrder:
            g = self.groups[gn]
            gnode = g.createXMLNode(newdoc)
            newdoc.documentElement.appendChild(gnode)
        f = file(filename, "w")
        newdoc.writexml(f, addindent="  ", newl="\n")
        f.close()

