#
# XenRT: Test harness for Xen and the XenServer product family
#
# Test sequence specification
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

"""
Parses an XML test sequence specification.
"""

import sys, string, time, os, xml.dom.minidom, threading, traceback, re, random, json, uuid
import xenrt
import pprint

__all__ = ["Fragment",
           "SingleTestCase",
           "Serial",
           "Parallel",
           "TestSequence",
           "findSeqFile"]

def findSeqFile(seqfile):
    """
    Construct the path to the sequence files given a name of the file
    @param seqfile: the name of the sequence file
    @type seqfile: string
    @rtype: string 
    @return an absolute path to a sequence file given the basename.
    """
    SEQ_LOC = "seqs"
    path = os.path.join(xenrt.TEC().lookup("XENRT_BASE", None), SEQ_LOC)
    xenrt.TEC().logverbose("Looking for seq file in %s ..." % (path))
    filename = os.path.join(path, seqfile)
    if not os.path.exists(filename):
        raise xenrt.XRTError("Cannot find sequence file %s" % (filename))

    return filename

def _expandVar(m):
    res = xenrt.TEC().lookup(m.group(1))
    if type(res) is list:
        return ",".join(res)
    return str(res)

def expand(s, p):
    """Expand a string with parameter names"""
    if not s:
        return s
    s = str(s)
    if p:
        for k in p.keys():
            if type(p[k]) == type(""):
                s = string.replace(s, "${%s}" % (k), p[k])
    s = re.sub("%(.+?)%", _expandVar, s)
    return s

class Fragment(threading.Thread):
    """A test sequence fragment"""
    def __init__(self, parent, steps, isfinally=False, jiratc=None, tcsku=None):
        threading.Thread.__init__(self)
        self.blocker = False
        self.blocked = None
        self.blockedticket = None
        self.iamtc = False
        self.steps = []
        self.finallysteps = []
        self.isfinally = isfinally
        self.jiratc = jiratc
        self.tcsku = tcsku
        self.ticket = None
        self.ticketIsFailure = True
        if parent and parent.isfinally:
            self.isfinally = True
        if steps:
            for s in steps:
                self.addStep(s)
        if parent:
            self.locationHost = parent.locationHost
            self.locationGuest = parent.locationGuest
            self.group = parent.group
            self.prio = parent.prio
            self.ttype = parent.ttype
        else:
            self.locationHost = None
            self.locationGuest = None
            self.group = None
            self.prio = None
            self.ttype = None
        self.semaphore = None

    def addStep(self, step):
        """
        Add a test case step 
        @param step: Data to create a instance of Fragment from. 
        @type step: tuple of data required to construct a SingleTestCase with 2 or 3 args or an instance of Fragment
        """

        if len(step) > 2:
            tc, args, name = step
            self.steps.append(SingleTestCase(tc, args, name=name))
        elif len(step) > 1:
            tc, args = step
            self.steps.append(SingleTestCase(tc, args))
        else:
            if not hasattr(step, "runThis"):
                raise xenrt.XRTError("Type mismatch when adding a step")
            self.steps.append(step)

    def addFinally(self, step):
        if len(step) > 2:
            tc, args, name = step
            self.finallysteps.append(SingleTestCase(tc, args, name=name))
        elif len(step) > 1:
            tc, args = step
            self.finallysteps.append(SingleTestCase(tc, args))
        else:
            self.finallysteps.append(step)

    def handleSubNode(self, toplevel, node, params=None):
        if node.nodeType == node.ELEMENT_NODE:
            f = node.getAttribute("filter")
            if f and params and params.has_key("__excludes"):
                if f in params["__excludes"]:
                    return
        if node.localName == "serial":
            tc = expand(node.getAttribute("tc"), params)
            tcsku = expand(node.getAttribute("sku"), params) or self.tcsku
            newfrag = Serial(self,jiratc=tc,tcsku=tcsku)
            newfrag.handleXMLNode(toplevel, node, params)
            self.addStep(newfrag)
        elif node.localName == "parallel":
            tc = expand(node.getAttribute("tc"), params)
            tcsku = expand(node.getAttribute("sku"), params) or self.tcsku
            newfrag = Parallel(self,jiratc=tc,tcsku=tcsku)
            a = expand(node.getAttribute("workers"), params)
            if a:
                newfrag.workers = int(a)
            newfrag.handleXMLNode(toplevel, node, params)
            self.addStep(newfrag)
        elif node.localName == "action":
            action = expand(node.getAttribute("action"), params)
            args = []
            for x in node.childNodes:
                if x.nodeType == x.ELEMENT_NODE:
                    if x.localName == "arg":
                        for a in x.childNodes:
                            if a.nodeType == a.TEXT_NODE:
                                args.append(expand(str(a.data), params))
            newfrag = Action(self, action=action, args=args)
            newfrag.handleXMLNode(toplevel, node, params)
            self.addStep(newfrag)
        elif node.localName == "finally":
            if not xenrt.TEC().lookup(["CLIOPTIONS", "NOFINALLY"], False,
                                      boolean=True):
                newfrag = Finally(self)
                newfrag.handleXMLNode(toplevel, node, params)
                self.addFinally(newfrag)
        elif node.localName == "for":
            iters = string.split(expand(str(node.getAttribute("iter")),
                                        params), ',')
            valuestring = expand(str(node.getAttribute("values")), params)
            defaults = string.split(expand(str(node.getAttribute("defaults")),
                                           params), ',')
            if valuestring == "-":
                valuestring = ""
            if len(iters) == 1:
                values = string.split(valuestring, ',')
            else:
                r = re.findall(r"\(.*?\)", valuestring)
                values = map(lambda x:re.findall(r"([^,\(\)]+)", x), r)
            
            offsetstring = expand(str(node.getAttribute("offset")), params)
            if offsetstring == "-":
                offsetstring = ""
            if offsetstring:
                values = values[int(offsetstring):]

            limitstring = expand(str(node.getAttribute("limit")), params)
            if limitstring == "-":
                limitstring = ""
            if limitstring:
                values = values[:int(limitstring)]
            
            for value in values:
                newparams = {}
                if params:
                    for k in params.keys():
                        newparams[k] = params[k]
                if len(iters) == 1:
                    newparams[iters[0]] = value
                else:
                    for i in range(min(len(iters), len(value))):
                        newparams[iters[i]] = value[i]
                    for i in range(len(value), len(iters)):
                        # Use defaults for unspecified arguments
                        if len(defaults) > 1:
                            newparams[iters[i]] = defaults[i]
                        else:
                            newparams[iters[i]] = "XXX"
                for x in node.childNodes:
                    self.handleSubNode(toplevel, x, newparams)
        elif node.localName == "ifin":
            item = expand(str(node.getAttribute("item")), params)
            itemlist = string.split(expand(str(node.getAttribute("list")),
                                           params), ",")
            if item in itemlist:
                for x in node.childNodes:
                    self.handleSubNode(toplevel, x, params)
        elif node.localName == "ifnotin":
            item = expand(str(node.getAttribute("item")), params)
            itemlist = string.split(expand(str(node.getAttribute("list")),
                                           params), ",")
            if not item in itemlist:
                for x in node.childNodes:
                    self.handleSubNode(toplevel, x, params)
        elif node.localName == "ifeq":
            v1 = expand(str(node.getAttribute("x")), params)
            v2 = expand(str(node.getAttribute("y")), params)
            if v1 == v2:
                for x in node.childNodes:
                    self.handleSubNode(toplevel, x, params)
        elif node.localName == "ifnoteq":
            v1 = expand(str(node.getAttribute("x")), params)
            v2 = expand(str(node.getAttribute("y")), params)
            if v1 != v2:
                for x in node.childNodes:
                    self.handleSubNode(toplevel, x, params)
        elif node.localName == "include":
            collection = expand(str(node.getAttribute("collection")), params)
            if not collection:
                raise xenrt.XRTError("Found include without collection name "
                                     "in sequence file")
            excludes = node.getAttribute("exclude")
            if not toplevel.collections.has_key(collection):
                raise xenrt.XRTError("Collection %s not found" % (collection))
            newparams = {}
            if params:
                for k in params.keys():
                    newparams[k] = params[k]
            for x in node.childNodes:
                if x.nodeType == x.ELEMENT_NODE and x.localName == "param":
                    n = x.getAttribute("name")
                    v = x.getAttribute("value")
                    if not n:
                        sys.stderr.write("param without name\n")
                    if not v:
                        sys.stderr.write("param %s without value\n" % (n))
                    if n and v:
                        newparams[str(n)] = expand(str(v), params)
            if excludes:
                if not newparams.has_key("__excludes"):
                    newparams["__excludes"] = []
                newparams["__excludes"].extend(string.split(excludes, ","))
            for c in toplevel.collections[collection].childNodes:
                if c.nodeType == c.ELEMENT_NODE:
                    self.handleSubNode(toplevel, c, newparams)
        elif node.localName == "testcase" or node.localName == "marvintests":
            if node.localName == "testcase":
                tcid = expand(node.getAttribute("id"), params)
                name = expand(node.getAttribute("name"), params)
                group = expand(node.getAttribute("group"), params)
                marvinTestConfig = None
            else:
                tcid = 'xenrt.lib.cloud.marvinwrapper.TCMarvinTestRunner'
                group = 'MarvinGroup'
                name = 'MarvinTests'
                marvinTestConfig = {}
                if expand(node.getAttribute("path"), params) != '':
                    marvinTestConfig['path'] = expand(node.getAttribute("path"), params)
                    group = marvinTestConfig['path']
                    group = len(group) > 32 and group[len(group)-32:] or group
                if expand(node.getAttribute("class"), params) != '':
                    if not marvinTestConfig.has_key('path'):
                        raise xenrt.XRTError('marvintests does not support just specifying a class - you must also specify a path in the sequence')
                    marvinTestConfig['cls'] = expand(node.getAttribute("class"), params)
                    name = marvinTestConfig['cls']
                    name = len(name) > 32 and name[len(name)-32:] or name
                if expand(node.getAttribute("tags"), params) != '':
                    marvinTestConfig['tags'] = expand(node.getAttribute("tags"), params).split(',')

            host = expand(node.getAttribute("host"), params)
            guest = expand(node.getAttribute("guest"), params)
            prios = expand(node.getAttribute("prio"), params)
            ttype = expand(node.getAttribute("ttype"), params)
            depend = expand(node.getAttribute("depends"), params)
            tc = expand(node.getAttribute("tc"), params) or self.jiratc
            tcsku = expand(node.getAttribute("sku"), params) or self.tcsku
            blocker = None
            a = expand(node.getAttribute("blocker"), params)           
            if a:
                a = string.lower(a)
                if a[0] == "y" or a == "0" or a[0] == "t":
                    blocker = True
                elif a[0] == "n" or a == "1" or a[0] == "f":
                    blocker = False
            if prios:
                prio = int(prios)
            else:
                prio = None
            args = []
            for x in node.childNodes:
                if x.nodeType == x.ELEMENT_NODE:
                    if x.localName == "arg":
                        for a in x.childNodes:
                            if a.nodeType == a.TEXT_NODE:
                                args.append(expand(str(a.data), params))
            try:
                newtc = SingleTestCase("testcases.%s" % (tcid),
                                       args,
                                       name,
                                       self,
                                       group,
                                       host=host,
                                       guest=guest,
                                       prio=prio,
                                       ttype=ttype,
                                       depend=depend,
                                       blocker=blocker,
                                       jiratc=tc,
                                       tcsku=tcsku,
                                       marvinTestConfig=marvinTestConfig)
            except Exception as e:
                exception_type,exception_value,exception_traceback = sys.exc_info()
                xenrt.TEC().logverbose("Failed to import file %s with exception values %s,%s,%s"%(tcid,exception_type,exception_value,exception_traceback))
                if exception_type == ImportError:
                    sys.exc_clear()
                else:
                    raise exception_value

                newtc = SingleTestCase("%s" % (tcid),
                                       args,
                                       name,
                                       self,
                                       group,
                                       host=host,
                                       guest=guest,
                                       prio=prio,
                                       ttype=ttype,
                                       depend=depend,
                                       blocker=blocker,
                                       jiratc=tc,
                                       tcsku=tcsku,
                                       marvinTestConfig=marvinTestConfig)
            self.addStep(newtc)        

    def handleXMLNode(self, toplevel, node, params=None):
        a = expand(node.getAttribute("host"), params)
        if a:
            self.locationHost = a
        a =  expand(node.getAttribute("guest"), params)
        if a:
            self.locationGuest = a
        a = expand(node.getAttribute("group"), params)
        if a:
            self.group = a
        a = expand(node.getAttribute("prio"), params)
        if a:
            self.prio = int(a)
        a = expand(node.getAttribute("ttype"), params)
        if a:
            self.ttype = a
        a = expand(node.getAttribute("blocker"), params)
        if a:
            a = string.lower(a)
            if a[0] == "y" or a == "0" or a[0] == "t":
                self.blocker = True
        for i in node.childNodes:
            if i.nodeType == i.ELEMENT_NODE:
                self.handleSubNode(toplevel, i, params)

    def runThis(self):
        """Run the sequence of testcases"""
        raise xenrt.XRTError("Never call Fragment.run directly")

    def run(self):
        if self.semaphore:
            self.semaphore.acquire()
        try:
            self.runThis()
        finally:
            if self.semaphore:
                self.semaphore.release()

    def setSemaphore(self, semaphore):
        self.semaphore = semaphore

    def block(self, blocked, blockedticket):
        self.blocked = blocked
        self.blockedticket = blockedticket
        xenrt.TEC().logverbose("Blocking seq fragment %s" % (str(self)))

    def __len__(self):
        return 1

    def __str__(self):
        return "Fragment"

    def debugPrint(self, fd, indent=""):
        fd.write("%s%s\n" % (indent, str(self)))
        for s in self.steps:
            s.debugPrint(fd, indent + "  ")
        if len(self.finallysteps) > 0:
            fd.write("%sFinally:\n" % (indent))
            for s in self.finallysteps:
                s.debugPrint(fd, indent + "  ")

    def listTCs(self):
        reply = []
        if self.jiratc:
            if self.tcsku:
                reply.append("_".join([self.jiratc, self.tcsku]))
            else:
                reply.append(self.jiratc)
        for s in self.steps:
            reply.extend(s.listTCs())
        return reply

    def jiraProcess(self):
        if self.jiratc:
            try:
                # We have a TC code, so lets do something
                jl = xenrt.jiralink.getJiraLink()
                jl.processFragment(self.jiratc,self.blocked,ticket=self.ticket,
                                   ticketIsFailure=self.ticketIsFailure,blockedticket=self.blockedticket,tcsku = self.tcsku)
                self.ticket = None
            except Exception, e:
                xenrt.GEC().logverbose("Jira Link Exception: %s" % (e),
                                       pref='WARNING')

class SingleTestCase(Fragment):
    def __init__(self,
                 tc,
                 args,
                 name=None,
                 parent=None,
                 group=None,
                 host=None,
                 guest=None,
                 prio=None,
                 ttype=None,
                 depend=None,
                 blocker=None,
                 jiratc=None,
                 tcsku=None,
                 marvinTestConfig=None):
        xenrt.TEC().logverbose("Creating testcase object for %s" % (tc))
        Fragment.__init__(self, parent, None)
        package = string.join(string.split(tc, ".")[:-1], ".")
        module = string.split(tc, ".")[0]
        try:
            d = dir(eval(package))
        except Exception, e:
            xenrt.TEC().logverbose(str(e))
            xenrt.TEC().logverbose("Trying to import %s." % (package))
            globals()[module] = __import__(package, globals(),  locals(), [])
            xenrt.TEC().logverbose("Imported module %s" % (package))
        self.tc = eval(tc)
        self.tcid = tc
        self.tcsku = tcsku
        self.args = args
        if group:
            self.group = group
        self.tcname = name
        self.runon = None
        if host:
            self.locationHost = host
        if guest:
            self.locationGuest = guest
        if prio:
            self.prio = prio
        if ttype:
            self.ttype = ttype
        self.depend = depend
        self.blocker = blocker
        self.jiratc = jiratc
        self.tcsku = tcsku
        self.marvinTestConfig = marvinTestConfig

    def runThis(self):
        try:
            t = xenrt.GEC().runTC(self.tc,
                              self.args,
                              blocked=self.blocked,
                              blockedticket=self.blockedticket,
                              name=self.tcname,
                              host=self.locationHost,
                              guest=self.locationGuest,
                              runon=self.runon,
                              group=self.group,
                              prio=self.prio,
                              ttype=self.ttype,
                              depend=self.depend,
                              isfinally=self.isfinally,
                              blocker=self.blocker,
                              jiratc=self.jiratc,
                              tcsku = self.tcsku,
                              marvinTestConfig = self.marvinTestConfig)
            if t and t.ticket:
                self.ticket = t.ticket
                self.ticketIsFailure = t.ticketIsFailure
        except xenrt.XRTBlocker, e:
            self.blocked = e
            t = e.testcase
            if t and t.ticket:
                self.ticket = t.ticket
                self.ticketIsFailure = t.ticketIsFailure
            raise e

    def getGrpAndTest(self):
        if self.tcname:
            name = self.tcname
        else:
            name = self.tcid.split(".")[-1]
        if self.group:
            gdisp = "%s/" % (self.group)
        else:
            gdisp = ""
        return "%s%s" % (gdisp,name)

    def __str__(self):
        if self.tcname:
            name = self.tcname
        else:
            name = self.tcid
        if self.group:
            gdisp = "%s/" % (self.group)
        else:
            gdisp = ""
        if self.prio:
            p =  "(P%u)" % (self.prio)
        else:
            p = ""
        if self.ttype:
            p = p + " (T %s)" % (self.ttype)
        return "%s%s [%s] %s" % (gdisp, name, string.join(self.args, ", "), p)

    def debugPrint(self, fd, indent=""):
        fd.write("%s%s\n" % (indent, str(self)))

    def listTCs(self):
        if self.jiratc:
            if self.tcsku:
                return ["%s_%s" % (self.jiratc, self.tcsku)]
            else:
                return [self.jiratc]
        tc = self.tc(tec=False)
        tc.setTCSKU(self.tcsku)
        if tc.getDefaultJiraTC():
            if self.tcsku:
                return ["%s_%s" % (tc.getDefaultJiraTC(), self.tcsku)]
            else:
                return [tc.getDefaultJiraTC()]
            
        r = re.search(r"\.TC(\d+)$", self.tcid)
        if r:
            if self.tcsku:
                return ["TC-%s_%s" % (r.group(1), self.tcsku)]
            else:
                return ["TC-%s" % (r.group(1))]
        return []

class Action(Fragment):
    def __init__(self, parent=None, action=None, args=None):
        Fragment.__init__(self, parent, None)
        self.action = action
        self.args = args
        self.blocker = True

    def runThis(self):
        try:
            if xenrt.GEC().abort:
                raise xenrt.XRTError("Aborting on command")
            if self.action == "sleep":
                if self.args and len(self.args) > 0:
                    d = int(self.args[0])
                xenrt.TEC().logverbose("Sleeping for %u seconds..." % (d))
                xenrt.sleep(d)
            elif self.action == "prepare":
                xenrt.TEC().logverbose("Re-preparing system...")
                xenrt.GEC().reprepare()
            else:
                raise xenrt.XRTError("Unknown action '%s'" % (self.action))
        except Exception, e:
            xenrt.TEC().logverbose("Action '%s' got exception %s" %
                                   (self.action, str(e)))
            if self.blocker:
                raise xenrt.XRTBlocker("Blocked by action: %s" % (self.action))

    def __str__(self):
        return "%s [%s]" % (self.action, string.join(self.args, ", "))

    def debugPrint(self, fd, indent=""):
        fd.write("%s%s\n" % (indent, str(self)))

    def listTCs(self):
        return ""

class Serial(Fragment):
    """A serial test sequence fragment"""
    def __init__(self, parent=None, steps=None, isfinally=False, jiratc=None, tcsku=None):
        Fragment.__init__(self, parent, steps, isfinally=isfinally, jiratc=jiratc, tcsku=tcsku)

    def runThis(self):
        """Run the sequence of testcases"""
        if xenrt.GEC().preparefailed:
            self.blocked = xenrt.GEC().preparefailed
            self.blockedticket = xenrt.GEC().prepareticket
        if xenrt.TEC().lookup("RANDOMISE_TEST_ORDER", False, boolean=True):
            random.shuffle(self.steps)
        for t in self.steps:
            try:
                if self.blocked:
                    t.block(self.blocked, self.blockedticket)
                xenrt.TEC().logverbose("Starting seq fragment %s" % (str(t)))
                t.run()
            except xenrt.XRTBlocker, e:
                self.blocked = e
                if (not self.blockedticket) and t.ticket:
                    self.blockedticket = t.ticket
                if (not self.blockedticket) and t.blockedticket:
                    self.blockedticket = t.blockedticket
                    
            if (not self.ticket) and t.ticket:
                self.ticket = t.ticket
                self.ticketIsFailure = t.ticketIsFailure
        self.jiraProcess()
        fblocked = False
        fblockedticket = None
        for t in self.finallysteps:
            try:
                if fblocked:
                    t.block(fblocked, fblockedticket)
                xenrt.TEC().logverbose("Starting seq finally fragment %s" %
                                       (str(t)))
                t.run()
            except xenrt.XRTBlocker, e:
                fblocked = e
                if (not fblockedticket) and t.ticket:
                    fblockedticket = t.ticket
                if (not fblockedticket) and t.blockedticket:
                    fblockedticket = t.blockedticket
            except Exception, e:
                sys.stderr.write(str(e))
                traceback.print_exc(file=sys.stderr)
        if self.blocked and self.blocker:
            raise self.blocked

    def __str__(self):
        return "Serial"

class Parallel(Fragment):
    """A serial test sequence fragment"""
    def __init__(self, parent=None, steps=None, isfinally=False, jiratc=None, tcsku=None):
        Fragment.__init__(self, parent, steps, isfinally, jiratc=jiratc, tcsku=tcsku)
        self.workers = None        

    def runThis(self):
        """Run the sequence of testcases"""
        if self.workers != None:
            semaphore = threading.Semaphore(self.workers)
        else:
            semaphore = None
        if xenrt.TEC().lookup("RANDOMISE_TEST_ORDER", False, boolean=True):
            random.shuffle(self.steps)
        for s in self.steps:
            xenrt.TEC().logverbose("Starting seq fragment %s" % (str(s)))
            if semaphore:
                s.setSemaphore(semaphore)
            if self.blocked:
                s.block(self.blocked, self.blockedticket)
            s.start()
        for s in self.steps:
            s.join()
            if (not self.ticket) and s.ticket:
                self.ticket = s.ticket
                self.ticketIsFailure = s.ticketIsFailure
            if s.blocked and not self.blocked:
                self.blocked = s.blocked
                if (not self.blockedticket) and s.ticket:
                    self.blockedticket = s.ticket
                if (not self.blockedticket) and s.blockedticket:
                    self.blockedticket = s.blockedticket
        self.jiraProcess()
        fblocked = False
        fblockedticket = None
        for t in self.finallysteps:
            try:
                if fblocked:
                    t.block(fblocked, fblockedticket)
                xenrt.TEC().logverbose("Starting seq finally fragment %s" %
                                       (str(t)))
                t.run()
            except xenrt.XRTBlocker, e:
                fblocked = e
                if (not self.blockedticket) and t.ticket:
                    self.blockedticket = t.ticket
                if (not self.blockedticket) and t.blockedticket:
                    self.blockedticket = t.blockedticket
            except Exception, e:
                sys.stderr.write(str(e))
                traceback.print_exc(file=sys.stderr)
        if self.blocked and self.blocker:
            raise self.blocked

    def __str__(self):
        return "Parallel"

class Finally(Serial):
    def __init__(self, parent=None, steps=None):
        Serial.__init__(self, parent, steps, isfinally=True)
    def __str__(self):
        return "Finally"

class TestSequence(Serial):
    """An entire test sequence."""
    def __init__(self, filename, tc=None, tcsku=None):
        Serial.__init__(self)
        self.collections = {}
        self.scripts = {} 
        self.params = {}
        self.prepare = None
        self.preprepare = None
        self.schedulerinfo = None
        self.seqdir = os.path.dirname(filename)
        cfg = xml.dom.minidom.parse(filename)
        if tc:
            self.jiratc = tc
        else:
            self.jiratc = xenrt.TEC().lookup("TESTRUN_TC", None)
        self.tcsku = tcsku
        for i in cfg.childNodes:
            if i.nodeType == i.ELEMENT_NODE:
                if i.localName == "xenrt":
                    for n in i.childNodes:
                        if n.nodeType == n.ELEMENT_NODE:
                            if n.localName == "testsequence":
                                xenrt.GEC().prepareonly = False
                                self.handleXMLNode(self, n, self.params)
                            elif n.localName == "variables":
                                if not xenrt.TEC().lookup("SEQ_PARSING_ONLY", False, boolean=True):
                                    xenrt.TEC().config.parseXMLNode(n)
                            elif n.localName == "semaphores":
                                for s in n.childNodes:
                                    if s.nodeType == s.ELEMENT_NODE:
                                        semclass = str(s.localName)
                                        count = expand(s.getAttribute("count"),
                                                       self.params)
                                        if not count:
                                            count = "1"
                                        xenrt.GEC().semaphoreCreate(semclass,
                                                                    int(count))
                            elif n.localName == "collection":
                                name = n.getAttribute("name")
                                if not name:
                                    raise xenrt.XRTError("Found collection "
                                                         "without name in "
                                                         "sequence file.")
                                self.collections[name] = n
                            elif n.localName == "default":
                                name = n.getAttribute("name")
                                value = n.getAttribute("value")
                                if name == None:
                                    raise xenrt.XRTError("Found default "
                                                         "without name in "
                                                         "sequence file.")
                                if value == None:
                                    raise xenrt.XRTError("Found default "
                                                         "without value in "
                                                         "sequence file.")
                                self.params[str(name)] = \
                                                       xenrt.TEC().lookup(\
                                        str(name), str(value))
                                xenrt.TEC().config.setVariable(str(name), self.params[str(name)])
                            elif n.localName == "include":
                                iname = n.getAttribute("filename")
                                if not iname:
                                    raise xenrt.XRTError("Found include "
                                                         "without filename.")
                                self.incFile(iname)
                            elif n.localName == "script":
                                filename = n.getAttribute("filename")
                                format = n.getAttribute("type")
                                if not filename:
                                    raise xenrt.XRTError("Found script "
                                                         "without filename.")
                                self.scriptFile(filename, format)
                            elif n.localName == "prepare":
                                self.prepare = PrepareNode(self, n, self.params)
                            elif n.localName == "preprepare":
                                self.preprepare = PrepareNode(self, n, self.params)
                            elif n.localName == "perfcheck":
                                xenrt.GEC().perfCheckParse(n)
                                xenrt.TEC().logverbose(str(xenrt.GEC().perfChecks))
                            elif n.localName == "scheduler":
                                self.schedulerinfo = n
                else:
                    raise xenrt.XRTError("No 'xenrt' tag found.")
 
    def doPrepare(self):
        """Run the prepare actions. This can be called again later if we
        want to reset the system to the fresh state.""" 
        noprepare = xenrt.TEC().lookup(["CLIOPTIONS", "NOPREPARE"],
                                         False,
                                         boolean=True)
        if self.prepare and not noprepare:
            self.prepare.runThis()

    def doPreprepare(self):
        """Run the preprepare actions. This can be called again later if we
        want to reset the system to the fresh state.""" 
        noprepare = xenrt.TEC().lookup(["CLIOPTIONS", "NOPREPARE"],
                                         False,
                                         boolean=True)
        if self.preprepare and not noprepare:
            self.preprepare.runThis()

    def runThis(self):
        xenrt.GEC().sequence = self
        try:
            self.doPreprepare()
            if xenrt.TEC().lookup("PAUSE_AFTER_PREPREPARE", False, boolean=True):
                xenrt.GEC().dbconnect.jobUpdate("PREPARE_PAUSED", "yes")
                xenrt.TEC().tc.pause("Preprepare completed")
                xenrt.GEC().dbconnect.jobUpdate("PREPARE_PAUSED", "no")
            self.doPrepare()
            if xenrt.TEC().lookup("PAUSE_AFTER_PREPARE", False, boolean=True):
                xenrt.GEC().dbconnect.jobUpdate("PREPARE_PAUSED", "yes")
                xenrt.TEC().tc.pause("Prepare completed")
                xenrt.GEC().dbconnect.jobUpdate("PREPARE_PAUSED", "no")
        except Exception, e:
            xenrt.TEC().logverbose(traceback.format_exc())
            xenrt.TEC().logverbose("Prepare failed with %s" % (str(e)))
            try:
                xenrt.GEC().dbconnect.jobUpdate("PREPARE_FAILED", str(e)[:250].replace("'", ""))
            except Exception, ex:
                xenrt.TEC().logverbose("Couldn't write PREPARE_FAILED to DB: " + str(ex))
            xenrt.GEC().preparefailed = e
            if xenrt.TEC().lookup("PAUSE_ON_PREPARE_FAIL", False, boolean=True):
                xenrt.GEC().dbconnect.jobUpdate("PREPARE_PAUSED", "yes")
                xenrt.TEC().tc.pause("Prepare failed")
                xenrt.GEC().dbconnect.jobUpdate("PREPARE_PAUSED", "no")
        Serial.runThis(self)

    def findFile(self, filename):
        search = [self.seqdir]
        p = xenrt.TEC().lookup("XENRT_CONF", None)
        if p:
            search.append("%s/seqs" % (p))
        p = xenrt.TEC().lookup("XENRT_BASE", None)
        if p:
            search.append("%s/seqs" % (p))
        for p in search:
            xenrt.TEC().logverbose("Looking for file in %s ..." % (p))
            f = "%s/%s" % (p, filename)
            if os.path.exists(f):
                return f
        p = xenrt.TEC().lookup("CUSTOM_SEQUENCE", None)
        if p:
            xenrt.TEC().logverbose("Looking for file on controller ...")
            data = xenrt.GEC().dbconnect.jobDownload(filename)
            f = xenrt.TEC().tempFile()
            file(f, "w").write(data)
            return f

    def scriptFile(self, filename, format):
        """Parse a script file"""
        if not format:
            format = "cmd"
        f = self.findFile(filename)
        self.scripts[filename] = (file(f, "r").read(), format)

    def incFile(self, filename):
        """Parse an include file"""
        f = self.findFile(filename)
        cfg = xml.dom.minidom.parse(f)
        for i in cfg.childNodes:
            if i.nodeType == i.ELEMENT_NODE:
                if i.localName == "xenrt":
                    for n in i.childNodes:
                        if n.nodeType == n.ELEMENT_NODE:
                            if n.localName == "variables":
                                if not xenrt.TEC().lookup("SEQ_PARSING_ONLY", False, boolean=True):
                                    xenrt.TEC().config.parseXMLNode(n)
                            elif n.localName == "semaphores":
                                for s in n.childNodes:
                                    if s.nodeType == s.ELEMENT_NODE:
                                        semclass = str(s.localName)
                                        count = expand(s.getAttribute("count"),
                                                       self.params)
                                        if not count:
                                            count = "1"
                                        xenrt.GEC().semaphoreCreate(semclass,
                                                                    int(count))
                            elif n.localName == "collection":
                                name = n.getAttribute("name")
                                if not name:
                                    raise xenrt.XRTError("Found collection "
                                                         "without name in "
                                                         "sequence file.")
                                self.collections[name] = n
                            elif n.localName == "default":
                                name = n.getAttribute("name")
                                value = n.getAttribute("value")
                                if not name:
                                    raise xenrt.XRTError("Found default "
                                                         "without name in "
                                                         "sequence file.")
                                if value == None:
                                    raise xenrt.XRTError("Found default "
                                                         "without value in "
                                                         "sequence file.")
                                if value != None:
                                    value = expand(value, self.params)
                                if name and value != None:
                                    self.params[str(name)] = \
                                                           xenrt.TEC().lookup(\
                                        str(name), str(value))
                            elif n.localName == "include":
                                iname = n.getAttribute("filename")
                                if not iname:
                                    raise xenrt.XRTError("Found include "
                                                         "without filename.")
                                self.incFile(iname)
                else:
                    raise xenrt.XRTError("No 'xenrt' tag found.")

from xenrt.seq.prepare import *
