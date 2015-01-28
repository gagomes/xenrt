#
# XenRT: Test harness for Xen and the XenServer product family
#
# Config file for a test suite
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

"""
Parses an XML suite specification.
"""

import sys, string, time, os, xml.dom.minidom, threading, traceback, re, os.path, urllib
import xenrt

def expand(s):
    """Expand a string with parameter names"""
    if not s:
        return s
    return xenrt.TEC().lookup("", s)

def quoteWhereNecessary(str):
    """Wrap the string in quotes if it contains shell speciail characters."""
    if re.search(r"[\<\>\!\"\&\|\(\)]", str):
        return "'%s'" % (str)
    return str

def mergeCSLists(a, b):
    """Return a dictionary containing all the list data from the two input
    dictionaries. If the same key exists in both input dictionaries then
    the lists are appended in the output."""
    r = a.copy()
    for k in b.keys():
        if r.has_key(k):
            r[k] = r[k] + b[k]
        else:
            r[k] = b[k]
    return r

class XRTSubmitError(xenrt.XRTError):
    pass

class SuiteConfigurable:

    def __init__(self):
        self.args = []
        self.cslist = {}
        
    def handleParam(self, node):
        for a in node.childNodes:
            if a.nodeType == a.TEXT_NODE:
                if not expand(str(a.data)) in self.args:
                    self.args.append("-D")
                    self.args.append(expand(str(a.data)))
                
    def handleArg(self, node, arg):
        for a in node.childNodes:
            if a.nodeType == a.TEXT_NODE:
                if arg not in self.args:
                    self.args.append(arg)
                    self.args.append(expand(str(a.data)))

    def handleParamArg(self, node, param):
        for a in node.childNodes:
            if a.nodeType == a.TEXT_NODE:
                arg = "%s=%s" % (expand(param), expand(str(a.data)))
                if arg not in self.args:
                    self.args.append("-D")
                    self.args.append(arg)

    def handleAdditiveArg(self, node, param):
        for a in node.childNodes:
            if a.nodeType == a.TEXT_NODE:
                if not self.cslist.has_key(param):
                    self.cslist[param] = []
                items = expand(str(a.data)).split(",")
                self.cslist[param].extend(items)

    def handleConfigNode(self, node):
        if node.localName == "resources":
            self.handleArg(node, "--res")
        elif node.localName == "resources1":
            self.handleArg(node, "--res1")
        elif node.localName == "user":
            self.handleArg(node, "-U")
        elif node.localName == "version":
            self.handleArg(node, "-v")
        elif node.localName in ("email",
                                "skip",
                                "skipgroup",
                                "testcasefiles",
                                "holdfail"):
            self.handleArg(node, "--%s" % (node.localName))
        elif node.localName == "param":
            self.handleParam(node)        
        elif node.localName == "flags":
            self.handleAdditiveArg(node, "FLAGS")
        elif node.localName == "requires":
            for a in node.childNodes:
                if a.nodeType == a.TEXT_NODE:
                    p = str(a.data)
                    if p.find("/") > -1:
                        lp = string.split(p, "/")
                    else:
                        lp = p
                    try:
                        v = xenrt.TEC().lookup(lp)
                    except:
                        raise xenrt.XRTError("This suite requires that "
                                             "variable %s is defined" % (p))
                    self.args.append("-D")
                    self.args.append("%s=%s" % (p, v))
            
class SuiteSequence(SuiteConfigurable):

    def __init__(self, node):
        SuiteConfigurable.__init__(self)
        self.name = node.getAttribute("name")
        self.seq = node.getAttribute("seq")
        self.tcsku = node.getAttribute("tcsku")
        self.tc = node.getAttribute("tc")
        self.seqfile = xenrt.TestSequence(xenrt.seq.findSeqFile(self.seq), tc=self.tc, tcsku=self.tcsku)
        self.pool = "default"
        self.delay = 0
        self.machines=1
        if self.seqfile.schedulerinfo:
            self.readConfig(self.seqfile.schedulerinfo)
        self.readConfig(node)
        for a in self.args:
            m = re.match("MACHINES_REQUIRED=(\d+)", a)
            if m:
                self.machines = int(m.group(1))
            
    def readConfig(self, node):
        for i in node.childNodes:
            if i.nodeType == i.ELEMENT_NODE:
                if i.localName == "pool":
                    for a in i.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            self.pool = str(a.data)
                elif i.localName == "delay":
                    for a in i.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            self.delay = int(a.data)
                else:
                    self.handleConfigNode(i)



    def debugPrint(self, fd):
        fd.write("  Sequence %s: %s\n" % (self.name, self.seq))
        for arg in self.args:
            fd.write("    %s\n" % (arg))
        #seq = xenrt.TestSequence(xenrt.seq.findSeqFile(self.seq))
        #fd.write("    TCs: %s\n" % (seq.listTCs()))
        
    def listTCsInSequence(self, quiet=False):
        if not quiet:
            sys.stderr.write("Processing sequence %s\n" % (self.seq))
        return self.seqfile.listTCs()

    def buildSubmitCommand(self, suiteargs, suitecslist, inputs):
        args = []
        rev = xenrt.TEC().lookup(["CLIOPTIONS", "REVISION"], None)
        if rev:
            args.extend(["-r", rev])
        branch = xenrt.TEC().lookup(["CLIOPTIONS", "BRANCH"], "trunk")
        if rev and inputs:
            build = string.split(rev, "-")[-1]
            inputs = string.replace(inputs, "${BUILD}", build)
            inputs = string.replace(inputs, "${BRANCH}", branch)
            args.extend(["--inputs", inputs])
        args.extend(["-n", self.seq])
        if self.pool != "default":
            args.extend(["--pool", self.pool])
        args.extend(suiteargs)
        args.extend(self.args)
        if rev:
            args.extend(["-D", "JOBDESC=%s&%s" % (self.name, rev)])
        else:
            args.extend(["-D", "JOBDESC=%s" % (self.name)])
        cslist = mergeCSLists(self.cslist, suitecslist)
        for param in cslist.keys():
            args.extend(["-D", "%s=%s" % (param, string.join(cslist[param], ","))])
        return args

    def submit(self, suiteargs, suitecslist, inputs, testrun, debug=False, waittime=0, excllist=None, devrun=False):
        moreargs = []
        runtcs = []
        seqs = xenrt.TEC().lookup(["CLIOPTIONS", "SUITE_SEQS"], None)
        if seqs:
            if not self.name in string.split(seqs, ","):
                sys.stderr.write("Not running sequence '%s'\n" % (self.name))
                return (0, runtcs)
        if excllist and self.name in excllist:
            sys.stderr.write("Skipping sequence '%s'\n" % (self.name))
            return (0, runtcs)
        inseq = self.listTCsInSequence(quiet=True)

        tcs = xenrt.TEC().lookup(["CLIOPTIONS", "SUITE_TCS"], None)
        if tcs:
            found = []
            for tc in tcs.split(","):
                if re.search("^\d+$", tc):
                    tc = "TC-" + tc
                tc = re.sub("TC([^-])", "TC-\g<1>", tc)
                if tc in inseq:
                    found.append(re.sub("TC-", "TC", tc))
            if len(found) == 0:
                sys.stderr.write("Not running sequence '%s'\n" % (self.name))
                return (0, runtcs)
            for tc in found:
                runtcs.append(tc)
                moreargs.append("-D RUN_%s=yes" % (tc))
        else:
            runtcs = inseq

        args = self.buildSubmitCommand(suiteargs, suitecslist, inputs)
        args.extend(["-D", "TESTRUN_SR=%s" % (testrun)])
        args.extend(["-D", "JOBGROUP=SR%s" % (testrun)])
        args.extend(["-D", "JOBGROUPTAG=%s" % (self.name)])
        if self.tcsku:
            args.extend(["-D", "TESTRUN_TCSKU=%s" % (self.tcsku)])
        if devrun:
            args.extend(["-D", "JIRA_TICKET_COMPONENT_ID=%s" % xenrt.TEC().lookup("DEV_JIRA_TICKET_COMPONENT_ID", "11891")])
        if waittime or self.delay:
            minstart = xenrt.util.timenow() + waittime + (self.delay * 60)
            args.extend(["-D", "START_AFTER=%u" % (minstart)])

        args.extend(moreargs)
        if debug:
            sys.stdout.write("DEBUG: xenrt submit %s\n" %
                             (string.join(map(quoteWhereNecessary, args))))
            ret = 1
            runtcs = []
        else:
            sys.stdout.write("Starting %s... " % (self.name))
            jobid = xenrt.GEC().dbconnect.jobSubmit(args)
            if jobid == None:
                raise XRTSubmitError("Error starting job for %s" % (self.name))
            sys.stdout.write("%s\n" % (jobid))
            ret = int(jobid)
        return (ret,runtcs)

class Suite(SuiteConfigurable):

    def __init__(self, filename):
        SuiteConfigurable.__init__(self)
        self.title = "Suite"
        self.sequences = []
        self.includesuites = []
        self.exclseqs = []
        self.inputs = None
        self.id = None
        self.delay = 0
        self.sku = None
        if not os.path.exists(filename):
            f = "%s/%s" % (xenrt.TEC().lookup("SUITE_CONFIGS"), filename)
            if os.path.exists(f):
                filename = f
            else:
                raise xenrt.XRTError("Could not find suite file '%s'" %
                                     (filename))
        cfg = xml.dom.minidom.parse(filename)
        includes = []
        seqs = []
        includesuites = []
        for i in cfg.childNodes:
            if i.nodeType == i.ELEMENT_NODE:
                if i.localName == "suite":
                    self.id = i.getAttribute("id")
                    for n in i.childNodes:
                        if n.nodeType == n.ELEMENT_NODE:
                            if n.localName == "title":
                                for a in n.childNodes:
                                    if a.nodeType == a.TEXT_NODE:
                                        self.title = str(a.data)
                            elif n.localName == "include":
                                includes.append(n.getAttribute("filename"))
                            elif n.localName == "sequence":
                                seqs.append(n)
                            elif n.localName == "common":
                                for a in n.childNodes:
                                    if a.nodeType == a.ELEMENT_NODE:
                                        self.handleConfigNode(a)
                            elif n.localName == "inputs":
                                for a in n.childNodes:
                                    if a.nodeType == a.TEXT_NODE:
                                        self.inputs = str(a.data)
                            elif n.localName == "delay":
                                for a in n.childNodes:
                                    if a.nodeType == a.TEXT_NODE:
                                        self.delay = int(str(a.data))
                            elif n.localName == "includesuite":
                                includesuites.append(n)
                            elif n.localName == "exclude":
                                for a in n.childNodes:
                                    if a.nodeType == a.ELEMENT_NODE:
                                        self.handleExcludeNode(a)

        for inc in includes:
            try:
                if not os.path.exists(inc):
                    f = "%s/%s" % (xenrt.TEC().lookup("SUITE_CONFIGS"), inc)
                    if os.path.exists(f): inc = f
                    else: 
                        raise xenrt.XRTError("Could not find include file '%s'" % (inc))
                cfg = xml.dom.minidom.parse(inc)
                for n in cfg.childNodes:
                    if n.nodeType == n.ELEMENT_NODE and n.localName == "common":
                        for a in n.childNodes:
                            if a.nodeType == a.ELEMENT_NODE:
                                self.handleConfigNode(a)
            except Exception:
                sys.stderr.write("Error processing include '%s' \n" % (inc))
                raise

        for s in seqs:
            try:
                xenrt.GEC().config.setVariable("IGNORE_CONFIG_LOOKUP_FAILURES", "yes")
                xenrt.GEC().config.setVariable("SEQ_PARSING_ONLY", "yes")
                self.sequences.append(SuiteSequence(s))
                xenrt.GEC().config.setVariable("IGNORE_CONFIG_LOOKUP_FAILURES", "no")
                xenrt.GEC().config.setVariable("SEQ_PARSING_ONLY", "no")
            except Exception:
                sys.stderr.write("Error processing sequence %s (%s)\n" % (s.getAttribute("name"), s.getAttribute("seq")))
                raise
        for s in includesuites:
            try:
                suitename = s.getAttribute("id")
                suitedir = "/".join(filename.split("/")[0:-1])
                if suitedir != "":
                    suitename = "%s/%s" % (suitedir, suitename)

                self.includesuites.append((Suite(suitename),s.getAttribute("delay")))
            except Exception:
                sys.stderr.write("Error processing suite %s\n" % s.getAttribute("id"))
                raise

    def debugPrint(self, fd):
        fd.write("Test Suite: %s\n" % (self.title))
        for s in self.sequences:
            s.debugPrint(fd)

    def setSKU(self, sku):
        self.sku = sku

    def getArgs(self):
        if self.sku:
            return self.args + self.sku.args
        return self.args

    def getCSList(self):
        if not self.sku or not self.sku.cslist:
            return self.cslist
        return mergeCSLists(self.cslist, self.sku.cslist)

    def findSkippedTcs(self):
        # From the suite file
        skip = map(lambda x: re.match("SKIP_TC(\d+)=", x).group(1), filter(lambda x: re.match("SKIP_TC(\d+)=", x), self.args))
        # And if we have a sku file, add the skipped TCs from there too
        if self.sku:
            skip.extend(map(lambda x: re.match("SKIP_TC(\d+)=", x).group(1), filter(lambda x: re.match("SKIP_TC(\d+)=", x), self.sku.args)))
        return skip

    def submit(self, debug=False, delayfor=0, devrun=False):
        testrun = xenrt.TEC().lookup(["CLIOPTIONS", "SUITE_TESTRUN"], None)
        rev = xenrt.TEC().lookup(["CLIOPTIONS", "REVISION"], "unknown")
        if self.sku and self.sku.id:
            rev = rev + "-" + self.sku.id

        # Check if the build exists, we declare the existance of a manifest file
        # sufficient.
        branch = xenrt.TEC().lookup(["CLIOPTIONS", "BRANCH"], "trunk")
        build = string.split(rev, "-")[1]
        if self.sku and self.sku.inputs:
            inputs = self.sku.inputs
        else:
            inputs = self.inputs
        
        if inputs:
            inputs = string.replace(inputs, "${BUILD}", build)
            inputs = string.replace(inputs, "${BRANCH}", branch)
            manifest = "%s/manifest" % (inputs)
            if not "/release/" in inputs and not xenrt.TEC().fileExists(manifest):
                raise xenrt.XRTError("Manifest (%s) not found for build %s on branch %s" % (manifest, build, branch)) 

        try:
            j = xenrt.jiralink.getJiraLink()
        except:
            if not debug:
                raise
        devCmp = xenrt.TEC().lookup("DEV_JIRA_TICKET_COMPONENT_ID", "11891")
        if devrun or "JIRA_TICKET_COMPONENT_ID=%s" % devCmp in self.getArgs():
            devrunCalc = True
        else:
            devrunCalc = False
        if testrun:
            pass
        elif xenrt.TEC().lookup(["CLIOPTIONS", "SUITE_TESTRUN_RERUN"], None):
            # Rerun, check that we have a list of sequences or TCs to rerun, so
            # not the entire suite
            seqs = xenrt.TEC().lookup(["CLIOPTIONS", "SUITE_SEQS"], None)
            tcs = xenrt.TEC().lookup(["CLIOPTIONS", "SUITE_TCS"], None)
            rrall = xenrt.TEC().lookup(["CLIOPTIONS", "SUITE_TESTRUN_RERUN_ALL"], False, boolean=True)
            if not rrall and not (seqs or tcs):
                raise xenrt.XRTError("You must specify --suite-seqs or "
                                     "--suite-tcs when using --rerun, use "
                                     "--rerun-all to rerun the entire suite")
            testrun = j.createTRTickets(self.id,rev,None,True,branch=branch,devrun=devrunCalc)
        elif debug or not self.id:
            testrun = "1"
        else:
            testrun = j.createTRTickets(self.id,rev,None,False,branch=branch,devrun=devrunCalc)
            if not testrun:
                raise xenrt.XRTError("Unable to obtain a testrun ID")
        if not re.search(r"^\d+$", testrun):
            raise xenrt.XRTError("Testrun ID '%s' is not valid" % (testrun))
        waittime = 0
        excllist = self.exclseqs
        if self.sku:
            excllist.extend(self.sku.exclseqs)
        if self.sku and self.sku.inputs:
            inputs = self.sku.inputs
        else:
            inputs = self.inputs
        jobids = []
        alltcs = []
        try:
            for s in sorted(self.sequences, key=lambda x:x.machines, reverse=True):
                (jobid,tcs) = s.submit(self.getArgs(),
                                 self.getCSList(),
                                 inputs,
                                 testrun,
                                 debug=debug,
                                 waittime=(waittime + delayfor),
                                 excllist=excllist,
                                 devrun=devrun)
                alltcs.extend(tcs)
                if debug:
                    pass
                elif jobid == 0:
                    # Sequence was skipped
                    pass
                else:
                    # We started a job, add a delay for the next one
                    waittime = waittime + self.delay * 60
                    jobids.append(jobid)
            # Remove duplicate entries
            d = {}
            for x in alltcs:
                d[x] = 1
            alltcs = list(d.keys())
            # Remove testcases that are skipped
            skip = self.findSkippedTcs()
            for s in skip:
                if "TC-%s" % s in alltcs:
                    alltcs.remove("TC-%s" % s)
            if not debug:
                j.addTestsToSuiteRun(testrun,alltcs)
            if not xenrt.TEC().lookup(["CLIOPTIONS", "SUITE_TESTRUN_RERUN"], None):
                for (s,delay) in self.includesuites:
                    if not delay:
                        delay = 0
                    delay = delay + delayfor
                    s.setSKU(self.sku)
                    subtr = s.submit(debug,delayfor=delay,devrun=devrun)
                    print "INCLUDED SUITE %s" % subtr
        except XRTSubmitError, e:
            sys.stderr.write("Error submitting one or more jobs, aborting.\n")
            for jobid in jobids:
                sys.stderr.write("Removing job %u\n" % (jobid))
                xenrt.GEC().dbconnect.jobRemove(jobid)
            raise xenrt.XRTError("Error starting jobs for testrun %s" %
                                 (testrun))
        if not debug and not xenrt.TEC().lookup(["CLIOPTIONS", "SUITE_TESTRUN_RERUN"], None):
            self.jenkinsMonitor(testrun) 
        return testrun

    def jenkinsMonitor(self, suiterun):
        jenkins = xenrt.TEC().lookup("JENKINS_URL", None)
        if jenkins:
            jenkinsCLI = xenrt.TEC().lookup("JENKINS_CLI", None)
            jenkinsProject = xenrt.TEC().lookup("JENKINS_SUITERUN_PROJECT", None)
           
            # Get the name of the suite run we want to put in Jenkins
            u = urllib.urlopen("%s/tools/suiterunname?suiterun=%s" % (xenrt.TEC().lookup("TESTRUN_URL"), suiterun))
            np = u.read().split(",")
            srtext = "%s - %s (%s), %s (%s)" % (np[0], np[1], np[2], np[3], suiterun)
            
            # Find out what the old Jenkins build number is 
            xmltext = urllib.urlopen("%s/job/%s/api/xml/?xpath=/freeStyleProject/lastBuild/number" % (jenkins, jenkinsProject)).read()
            oldBuild = xenrt.util.getTextFromXmlNode(xml.dom.minidom.parseString(xmltext).getElementsByTagName("number")[0])
            
            emailaddr = xenrt.TEC().lookup("JENKINS_EMAIL", None)
            if emailaddr:
                email = "-p 'Email=%s'" % emailaddr
            else:
                email = ""

            # Create a new build in Jenkins
            xenrt.util.command("%s -s %s build '%s' -p 'Suite run ID=%s' %s" % (jenkinsCLI, jenkins, jenkinsProject, suiterun, email))

            # The jenkins CLI doesn't have a way of getting the build number we just built, so we need to guess based on the last build number
            # It seems that the CLI might return before the build has actually started, so we'll wait for the last build number to change
            deadline = xenrt.timenow() + 30
            while True:
                xmltext = urllib.urlopen("%s/job/%s/api/xml/?xpath=/freeStyleProject/lastBuild/number" % (jenkins, jenkinsProject)).read()
                build = xenrt.util.getTextFromXmlNode(xml.dom.minidom.parseString(xmltext).getElementsByTagName("number")[0])
                if build != oldBuild:
                    xenrt.util.command("%s -s %s set-build-display-name '%s' '%s' '%s'" % (jenkinsCLI, jenkins, jenkinsProject, build, srtext))
                    xenrt.util.command("%s -s %s set-build-description '%s' '%s' '%s'" % (jenkinsCLI, jenkins, jenkinsProject, build, string.join(sys.argv)))
                    break
                if xenrt.timenow() > deadline:
                    xenrt.TEC().warning("Could not find new build in Jenkins, not updating suite run")
                    break
                xenrt.sleep(5)

    def listTCsInSequences(self, quiet=False):
        reply = []
        for s in self.sequences:
            if s.name in self.exclseqs:
                continue
            try:
                reply.extend(s.listTCsInSequence(quiet=quiet))
            except Exception, e:
                sys.stderr.write("Error processing sequence %s (%s)\n") % (s.name, s.seq)
                raise
        filteredReply = []
        excltcs = ["TC-%s" % x for x in self.findSkippedTcs()]
        for t in reply:
            if not t in excltcs:
                filteredReply.append(t)
        return filteredReply

    def listTCsInSuite(self):
        # Open a link to Jira
        j = xenrt.jiralink.getJiraLink()
        
        # Get a list of all ticket in the suite
        suitetickets = []
        s = j.jira.issue(self.id)
        slinks = s.fields.issuelinks
        for slink in slinks:
            if slink.type.name == "Contains" and hasattr(slink, "outwardIssue"):
                c = j.jira.issue(slink.outwardIssue.key)
                if c.fields.status.name == "Open":
                    suitetickets.append(c.key)

        return suitetickets

    def checkSuite(self, fd):
        """Check the suite for consistency."""
        # Open a link to Jira
        j = xenrt.jiralink.getJiraLink()

        inseq = self.listTCsInSequences()
        insuite = self.listTCsInSuite()

        extraseq = []
        extrasuite = []

        for s in inseq:
            if not s in insuite:
                extraseq.append(s)
        for s in insuite:
            if not s in inseq:
                extrasuite.append(s)

        if len(extraseq) == 0 and len(extrasuite) == 0:
            fd.write("OK\n")
        else:
            fd.write("ERROR\n")
            if len(extraseq) > 0:
                fd.write("\nTestcases in sequences but not suite:\n")
                for s in extraseq:
                    t = j.jira.issue(s)
                    fd.write("  %s: %s\n" % (s, t.fields.summary))
            if len(extrasuite) > 0:
                fd.write("\nTestcases in suite but not sequence:\n")
                for s in extrasuite:
                    t = j.jira.issue(s)
                    fd.write("  %s: %s\n" % (s, t.fields.summary))

    def fixSuite(self, fd):
        """Check the suite for consistency."""
        # Open a link to Jira
        j = xenrt.jiralink.getJiraLink()
        
        inseq = self.listTCsInSequences()
        insuite = self.listTCsInSuite()
        
        extraseq = []
        extrasuite = []

        for s in inseq:
            if not s in insuite:
                extraseq.append(s)
        for s in insuite:
            if not s in inseq:
                extrasuite.append(s)

        if len(extraseq) > 0:
            for s in extraseq:
                t = j.jira.issue(s)
                fd.write("Adding  %s: %s\n" % (s, t.fields.summary))
                j.jira.create_issue_link("Contains", inwardIssue = self.id, outwardIssue = s)
        if len(extrasuite) > 0:
            for s in extrasuite:
                t = j.jira.issue(s)
                links = [x for x in t.fields.issuelinks if hasattr(x, "inwardIssue") and x.type.name=="Contains" and x.inwardIssue.key == self.id]
                if len(links) > 0:
                    fd.write("Deleting  %s: %s\n" % (s, t.fields.summary))
                    links[0].delete()

    def handleExcludeNode(self, node):
        if node.localName == "sequence":
            for a in node.childNodes:
                if a.nodeType == a.TEXT_NODE:
                    self.exclseqs.append(expand(str(a.data)))

def getSuites(id):
    """Return a list of suites objects for this ID. If the ID is a filename
    then use it directly as a single suite. If the ID is for a suite
    the list will contain only that suite. If the ID is for a suite group then
    the list will contains objects for each suite in the group."""

    if os.path.exists(id):
        return [Suite(id)]
    
    # Open a link to Jira
    j = xenrt.jiralink.getJiraLink()

    t = j.jira.issue(id)
    if t.fields.issuetype.name == "Suite Group":
        reply = []
        links = t.fields.issuelinks
        for link in links:
            if link.type.name == "Contains" and hasattr(link, "outwardIssue"):
                reply.append(Suite(link.outwardIssue.key))
        return reply
    else:
        return [Suite(id)]
    
class SKU(SuiteConfigurable):

    def __init__(self, filename):
        SuiteConfigurable.__init__(self)
        self.title = "SKU"
        self.id = None
        self.exclseqs = []
        self.inputs = None
        self.sequences = []
        if not os.path.exists(filename):
            f = "%s/%s" % (xenrt.TEC().lookup("SUITE_CONFIGS"), filename)
            if os.path.exists(f):
                filename = f
            else:
                raise xenrt.XRTError("Could not find sku file '%s'" %
                                     (filename))
        cfg = xml.dom.minidom.parse(filename)
        for i in cfg.childNodes:
            if i.nodeType == i.ELEMENT_NODE:
                if i.localName == "sku":
                    self.id = i.getAttribute("id")
                    for n in i.childNodes:
                        if n.nodeType == n.ELEMENT_NODE:
                            if n.localName == "title":
                                for a in n.childNodes:
                                    if a.nodeType == a.TEXT_NODE:
                                        self.title = str(a.data)
                            elif n.localName == "common":
                                for a in n.childNodes:
                                    if a.nodeType == a.ELEMENT_NODE:
                                        self.handleConfigNode(a)
                            elif n.localName == "exclude":
                                for a in n.childNodes:
                                    if a.nodeType == a.ELEMENT_NODE:
                                        self.handleExcludeNode(a)
                            elif n.localName == "inputs":
                                for a in n.childNodes:
                                    if a.nodeType == a.TEXT_NODE:
                                        self.inputs = str(a.data)

    def handleExcludeNode(self, node):
        if node.localName == "sequence":
            for a in node.childNodes:
                if a.nodeType == a.TEXT_NODE:
                    self.exclseqs.append(expand(str(a.data)))

    def debugPrint(self, fd):
        fd.write("SKU: %s\n" % (self.title))
        for s in self.sequences:
            s.debugPrint(fd)
