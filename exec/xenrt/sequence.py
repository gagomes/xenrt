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

import sys, string, time, os, xml.dom.minidom, threading, traceback, re, random, json
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
    return xenrt.TEC().lookup(m.group(1))

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
            tcsku = expand(node.getAttribute("sku"), params)
            newfrag = Serial(self,jiratc=tc,tcsku=tcsku)
            newfrag.handleXMLNode(toplevel, node, params)
            self.addStep(newfrag)
        elif node.localName == "parallel":
            tc = expand(node.getAttribute("tc"), params)
            tcsku = expand(node.getAttribute("sku"), params)
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
                marvinTestConfig = {}
                marvinTestConfig['cls'] = expand(node.getAttribute("class"), params)
                marvinTestConfig['path'] = expand(node.getAttribute("path"), params)
                marvinTestConfig['tags'] = expand(node.getAttribute("tags"), params).split(',')

                group = os.path.splitext(os.path.basename(marvinTestConfig['path']))[0]
                group = len(group) > 32 and group[len(group)-32:] or group
                name = expand(node.getAttribute("class"), params)
                name = len(name) > 32 and name[len(name)-32:] or name

            host = expand(node.getAttribute("host"), params)
            guest = expand(node.getAttribute("guest"), params)
            prios = expand(node.getAttribute("prio"), params)
            ttype = expand(node.getAttribute("ttype"), params)
            depend = expand(node.getAttribute("depends"), params)
            tc = expand(node.getAttribute("tc"), params)
            tcsku = expand(node.getAttribute("sku"), params)
            if not tc:
                tc = self.jiratc
            if not tcsku:
                tcsku = self.tcsku
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

class PrepareNode:

    def __init__(self, toplevel, node, params):
        self.toplevel = toplevel
        self.vms = []
        self.hosts = []
        self.pools = []
        self.bridges = []
        self.srs = []
        self.cloudSpec = {}
        self.networksForHosts = {}
        self.networksForPools = {}
        self.controllersForHosts = {}
        self.controllersForPools = {}
        self.preparecount = 0

        for n in node.childNodes:
            if n.localName == "pool":
                self.handlePoolNode(n, params)
            elif n.localName == "host":
                self.handleHostNode(n, params)
            elif n.localName == "sharedhost":
                self.handleSharedHostNode(n, params)
            elif n.localName == "allhosts":
                # Create a host for each machine known to this job
                if n.hasAttribute("start"):
                    i = int(n.getAttribute("start"))
                else:
                    i = 0
                if n.hasAttribute("stop"):
                    stop = int(n.getAttribute("stop"))
                else:
                    stop = None
                while xenrt.TEC().lookup("RESOURCE_HOST_%u" % (i), None):
                    host = self.handleHostNode(n, params, id=i)
                    if i == stop:
                        break
                    i = i + 1
            elif n.localName == "cloud":
                self.handleCloudNode(n, params)

    def handleCloudNode(self, node, params):
        # Load the JSON block from the sequence file
        self.cloudSpec = json.loads(node.childNodes[0].data)


        # Find allocated host IDs 
        allocatedHostIds = map(lambda x:int(x['id']), self.hosts)
        hostIdIndex = 0
        if len(allocatedHostIds) > 0:
            hostIdIndex = max(allocatedHostIds) + 1

        allocatedPoolIds = map(lambda x:int(x['id']), self.pools)
        poolIdIndex = 0
        if len(allocatedPoolIds) > 0:
            poolIdIndex = max(allocatedPoolIds) + 1

        xenrt.TEC().logverbose('Allocate Hosts from ID: %d' % (hostIdIndex))
        xenrt.TEC().logverbose('Allocate Pools from ID: %d' % (poolIdIndex))

        for zone in self.cloudSpec['zones']:
            
            for pod in zone['pods']:

                for cluster in pod['clusters']:
                    if not cluster.has_key('masterHostId'):
                        hostIds = range(hostIdIndex, hostIdIndex + cluster['hosts'])
                        poolId = poolIdIndex

                        simplePoolNode = xml.dom.minidom.Element('pool')
                        simplePoolNode.setAttribute('id', str(poolId))
                        for hostId in hostIds:
                            simpleHostNode = xml.dom.minidom.Element('host')
                            simpleHostNode.setAttribute('id', str(hostId))
                            simplePoolNode.appendChild(simpleHostNode)

# TODO: Create storage if required                        if cluster.has_key('primaryStorageSRName'):
                            
                        hostIdIndex += cluster['hosts']
                        poolIdIndex += 1

                        self.handlePoolNode(simplePoolNode, params)
                        poolSpec = filter(lambda x:x['id'] == str(poolId), self.pools)[0]
                        cluster['masterHostId'] = int(poolSpec['master'].split('RESOURCE_HOST_')[1])
    

    def handlePoolNode(self, node, params):
        pool = {}

        pool["id"] = expand(node.getAttribute("id"), params)
        if not pool["id"]:
            pool["id"] = 0
        pool["name"] = expand(node.getAttribute("name"), params)
        if not pool["name"]:
            pool["name"] = "RESOURCE_POOL_%s" % (pool["id"])
        pool["master"] = expand(node.getAttribute("master"), params)
        ssl = expand(node.getAttribute("ssl"), params)
        if ssl and ssl[0] in ('y', 't', '1', 'Y', 'T'):
            pool["ssl"] = True
        else:
            pool["ssl"] = False
 
        hostNodes = []   
        otherNodes = []
        for x in node.childNodes:
            if x.nodeType == x.ELEMENT_NODE:
                if x.localName == "host" or x.localName == "allhosts":
                    hostNodes.append(x)
                else:
                    otherNodes.append(x)

        # We have to process host elements first, as we may need to
        # determine who the master is (XRT-6100 + XRT-6101)
        for x in hostNodes:
            if x.localName == "host":
                host = self.handleHostNode(x, params)
                host["pool"] = pool["name"]
                if not pool["master"]:
                    pool["master"] = "RESOURCE_HOST_%s" % (host["id"])
            elif x.localName == "allhosts":
                # Create a host for each machine known to this job
                if x.hasAttribute("start"):
                    i = int(x.getAttribute("start"))
                else:
                    i = 0
                if x.hasAttribute("stop"):
                    stop = int(x.getAttribute("stop"))
                else:
                    stop = None
                while xenrt.TEC().lookup("RESOURCE_HOST_%u" % (i), None):
                    host = self.handleHostNode(x, params, id=i)
                    host["pool"] = pool["name"]
                    if not pool["master"]:
                        pool["master"] = "RESOURCE_HOST_%s" % (i)
                    if i == stop:
                        break
                    i = i + 1

        for x in otherNodes:
            if x.localName == "storage":
                type = expand(x.getAttribute("type"), params)
                name = expand(x.getAttribute("name"), params)
                default = expand(x.getAttribute("default"), params)
                options = expand(x.getAttribute("options"), params)
                network = expand(x.getAttribute("network"), params)
                blkbackPoolSize = expand(x.getAttribute("blkbackpoolsize"), params)
                vmhost = expand(x.getAttribute("vmhost"), params)
                size = expand(x.getAttribute("size"), params)
                self.srs.append({"type":type, 
                                 "name":name, 
                                 "host":pool["master"],
                                 "default":(lambda x:x == "true")(default),
                                 "options":options,
                                 "network":network,
                                 "blkbackPoolSize":blkbackPoolSize,
                                 "vmhost":vmhost,
                                 "size":size})
            elif x.localName == "bridge":
                type = expand(x.getAttribute("type"), params)
                name = expand(x.getAttribute("name"), params)
                self.bridges.append({"type":type, 
                                     "name":name, 
                                     "host":pool["master"]})
            elif x.localName == "vm":
                vm = self.handleVMNode(x, params)
                vm["host"] = pool["master"] 
            elif x.localName == "vmgroup":
                vmgroup = self.handleVMGroupNode(x, params)
                for vm in vmgroup:
                    vm["host"] = host["name"]      
            elif x.localName == "NETWORK":
                # This is a network topology description we can use
                # with createNetworkTopology. Record the whole DOM node
                if x.getAttribute("controller"):
                    self.controllersForPools[pool["name"]] = expand(x.getAttribute("controller"), params)
                self.networksForPools[pool["name"]] = x.parentNode
        self.pools.append(pool)

        return pool

    def handleHostNode(self, node, params, id=0):
        host = {}        
        host["pool"] = None

        host["id"] = expand(node.getAttribute("id"), params)
        if not host["id"]:
            host["id"] = str(id)
        host["name"] = expand(node.getAttribute("alias"), params)
        if not host["name"]:
            host["name"] = str("RESOURCE_HOST_%s" % (host["id"]))
        host["version"] = expand(node.getAttribute("version"), params)
        if not host["version"] or host["version"] == "DEFAULT":
            host["version"] = None
        host["productType"] = expand(node.getAttribute("productType"), params)
        if not host["productType"]:
            host["productType"] = "xenserver"
        host["productVersion"] = expand(node.getAttribute("productVersion"), params)
        if not host["productVersion"] or host["productVersion"] == "DEFAULT":
            host["productVersion"] = None
        host["installSRType"] = expand(node.getAttribute("installsr"), params)
        if not host["installSRType"]:
            host["installSRType"] = None
        dhcp = expand(node.getAttribute("dhcp"), params)
        if not dhcp:
            host["dhcp"] = True
        elif dhcp[0] in ('y', 't', '1', 'Y', 'T'):
            host["dhcp"] = True
        else:
            host["dhcp"] = False
        host['ipv6'] = expand(node.getAttribute("ipv6"), params)
        noipv4 = expand(node.getAttribute("noipv4"), params)
        if not noipv4:
            host['noipv4'] = False
        elif noipv4[0] in set(['y', 't', '1', 'Y', 'T']):
            host['noipv4'] = True
        if not host['ipv6']:
            host['noipv4'] = False
        dc = expand(node.getAttribute("diskCount"), params)
        if not dc:
            dc = "1"
        host["diskCount"] = int(dc)
        license = expand(node.getAttribute("license"), params)
        if license:
            if license[0] in ('y', 't', '1', 'Y', 'T'):
                host["license"] = True
            elif license[0] in ('n', 'f', '0', 'N', 'F'):
                host["license"] = False
            else:
                host["license"] = license
        else:
            ls = xenrt.TEC().lookup("OPTION_LIC_SKU", None)
            if ls:
                host["license"] = ls
        usev6testd = expand(node.getAttribute("usev6testd"), params)
        if usev6testd:
            if usev6testd[0] in ('y', 't', '1', 'Y', 'T'):
                host["usev6testd"] = True
            else:
                host["usev6testd"] = False
        noisos = expand(node.getAttribute("noisos"), params)
        if noisos:
            if noisos[0] in ('y', 't', '1', 'Y', 'T'):
                host["noisos"] = True
            else:
                host["noisos"] = False
        host["suppackcds"] = expand(node.getAttribute("suppackcds"), params)
        disablefw = expand(node.getAttribute("disablefw"), params)
        if disablefw:
            if disablefw[0] in ('y', 't', '1', 'Y', 'T'):
                host["disablefw"] = True
            else:
                host["disablefw"] = False
        if not host["suppackcds"]:
            host["suppackcds"] = None
        for x in node.childNodes:
            if x.nodeType == x.ELEMENT_NODE:
                if x.localName == "storage":
                    type = expand(x.getAttribute("type"), params)
                    name = expand(x.getAttribute("name"), params)
                    default = expand(x.getAttribute("default"), params)
                    options = expand(x.getAttribute("options"), params)
                    network = expand(x.getAttribute("network"), params)
                    blkbackPoolSize = expand(x.getAttribute("blkbackpoolsize"), params)
                    vmhost = expand(x.getAttribute("vmhost"), params)
                    size = expand(x.getAttribute("size"), params)
                    self.srs.append({"type":type, 
                                     "name":name, 
                                     "host":host["name"],
                                     "default":(lambda x:x == "true")(default),
                                     "options":options,
                                     "network":network,
                                     "blkbackPoolSize":blkbackPoolSize,
                                     "vmhost":vmhost,
                                     "size":size})
                elif x.localName == "bridge":
                    type = expand(x.getAttribute("type"), params)
                    name = expand(x.getAttribute("name"), params)
                    self.bridges.append({"type":type, 
                                         "name":name, 
                                         "host":host})
                elif x.localName == "vm":
                    vm = self.handleVMNode(x, params)
                    vm["host"] = host["name"] 
                elif x.localName == "vmgroup":
                    vmgroup = self.handleVMGroupNode(x, params)
                    for vm in vmgroup:
                        vm["host"] = host["name"]      
                elif x.localName == "NETWORK":
                    # This is a network topology description we can use
                    # with createNetworkTopology. Record the whole DOM node
                    self.networksForHosts[host["name"]] = x.parentNode
                    if x.getAttribute("controller"):
                        self.controllersForHosts[host["name"]] = expand(x.getAttribute("controller"), params)

        self.hosts.append(host)

        return host

    def handleSharedHostNode(self, node, params):
        for x in node.childNodes:
            if x.nodeType == x.ELEMENT_NODE:
                if x.localName == "vm":
                    vm = self.handleVMNode(x, params, suffixjob=True)
                    vm["host"] = "SHARED" 

    def handleVMGroupNode(self, node, params):
        vmgroup = []
        basename = expand(node.getAttribute("basename"), params)
        number = expand(node.getAttribute("number"), params)
        for i in range(int(number)):
            node.setAttribute("name", "%s-%s" % (basename, i))
            vmgroup.append(self.handleVMNode(node, params))
        return vmgroup

    def handleVMNode(self, node, params, suffixjob=False):
        vm = {} 

        vm["guestname"] = expand(node.getAttribute("name"), params)
        vm["vifs"] = []       
        vm["disks"] = []
        vm["postinstall"] = []
        if suffixjob:
            vm["suffix"] = xenrt.GEC().dbconnect.jobid()
 
        for x in node.childNodes:
            if x.nodeType == x.ELEMENT_NODE:
                if x.localName == "distro":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            vm["distro"] = expand(str(a.data), params)
                elif x.localName == "vcpus":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            vm["vcpus"] = int(expand(str(a.data), params))
                elif x.localName == "memory":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            vm["memory"] = int(expand(str(a.data), params))
                elif x.localName == "guestparams":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            vm["guestparams"] = map(lambda x:x.split('='),  string.split(expand(str(a.data), params), ","))
                elif x.localName == "storage":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            vm["sr"] = expand(str(a.data), params)
                elif x.localName == "arch":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            vm["arch"] = expand(str(a.data), params)
                elif x.localName == "network":
                    device = expand(x.getAttribute("device"), params)
                    bridge = expand(x.getAttribute("bridge"), params)
                    vm["vifs"].append([device, bridge, xenrt.randomMAC(), None])
                elif x.localName == "disk":
                    device = expand(x.getAttribute("device"), params)
                    size = expand(x.getAttribute("size"), params)
                    format = expand(x.getAttribute("format"), params)
                    number = expand(x.getAttribute("number"), params)
                    if format == "true" or format == "yes": 
                        format = True
                    else: format = False
                    if not number: number = 1
                    for i in range(int(number)):
                        vm["disks"].append([str(int(device)+i), size, format])
                elif x.localName == "postinstall":
                    action = expand(x.getAttribute("action"), params)
                    vm["postinstall"].append(action)
                elif x.localName == "script":
                    name = expand(x.getAttribute("name"), params)
                    vm["postinstall"].append(self.toplevel.scripts[name])
                elif x.localName == "file":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            vm["filename"] = expand(str(a.data), params)
                elif x.localName == "bootparams":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            vm["bootparams"] = expand(str(a.data), params)

        self.vms.append(vm)

        return vm                    

    def debugDisplay(self):
        xenrt.TEC().logverbose("Hosts:\n" + pprint.pformat(self.hosts))
        xenrt.TEC().logverbose("Pools:\n" + pprint.pformat(self.pools))
        xenrt.TEC().logverbose("VMs:\n" + pprint.pformat(self.vms))
        xenrt.TEC().logverbose("Bridges:\n" + pprint.pformat(self.bridges))
        xenrt.TEC().logverbose("SRs:\n" + pprint.pformat(self.srs))
        xenrt.TEC().logverbose("Cloud Spec:\n" + pprint.pformat(self.cloudSpec))

    def runThis(self):
        self.preparecount = self.preparecount + 1
        xenrt.TEC().logdelimit("Sequence setup")
        self.debugDisplay()

        nohostprepare = xenrt.TEC().lookup(["CLIOPTIONS", "NOHOSTPREPARE"],
                                         False,
                                         boolean=True)

        if not nohostprepare:
            xenrt.TEC().logverbose("Resetting machines Cloudstack info")
            i = 0
            while True:
                try:
                    hostname = xenrt.TEC().lookup("RESOURCE_HOST_%d" % i)
                except:
                    break
                try:
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [hostname, "CSIP", ""])
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [hostname, "CSGUEST", ""])
                except:
                    pass
                i += 1
        
        try:
            for v in self.vms:
                if v.has_key("host") and v["host"] == "SHARED":
                    if not xenrt.TEC().registry.hostGet("SHARED"):
                        xenrt.TEC().registry.hostPut("SHARED", xenrt.resources.SharedHost().getHost())
            if not nohostprepare:
                # Install hosts in parallel to save time.
                queue = InstallWorkQueue()
                for h in self.hosts:
                    queue.add(h)
                workers = []
                for i in range(max(int(xenrt.TEC().lookup("PREPARE_WORKERS", "4")), 4)):
                    w = HostInstallWorker(queue, name="HWorker%02u" % (i))
                    workers.append(w)
                    w.start()
                    # There appears to be a strange race condition somewhere, which
                    # results in NFS directory paths getting confused, and multiple
                    # installs sharing the same completion dir! While locating it,
                    # this should prevent any problems
                    xenrt.sleep(30)
                for w in workers:
                    w.join()
                for w in workers:
                    if w.exception:
                        exc_type, exc_value, exc_traceback = w.exception_extended
                        raise exc_type, exc_value, exc_traceback

                # Work out which hosts are masters and which are going to be
                # slaves. We'll do the actual pooling later.
                slaves = []
                # Check each pool for slaves
                for p in self.pools:
                    slaves.extend(filter(lambda x:x["pool"] == p["name"] \
                                         and not x["name"] == p["master"],
                                         self.hosts))
                masters = filter(lambda x:x not in slaves, self.hosts)

                # If we have a detailed network topology set this up on the
                # master(s) now
                for master in masters:
                    if master["pool"]:
                        if self.networksForPools.has_key(master["pool"]):
                            host = xenrt.TEC().registry.hostGet(master["name"])
                            t = self.networksForPools[master["pool"]]
                            host.createNetworkTopology(t)
                            host.checkNetworkTopology(t)
                    else:
                        if self.networksForHosts.has_key(master["name"]):
                            host = xenrt.TEC().registry.hostGet(master["name"])
                            t = self.networksForHosts[master["name"]]
                            host.createNetworkTopology(t)
                            host.checkNetworkTopology(t)

                # Perform any pre-pooling network setup on slaves
                if xenrt.TEC().lookup("WORKAROUND_CA21810", False, boolean=True):
                    xenrt.TEC().warning("Using CA-21810 workaround")
                    for p in self.pools:
                        if self.networksForPools.has_key(p["name"]):
                            slaves = filter(lambda x:x["pool"] == p["name"] \
                                            and not x["name"] == p["master"],
                                            self.hosts)
                            for s in slaves:
                                t = self.networksForPools[s["pool"]]
                                host = xenrt.TEC().registry.hostGet(s["name"])
                                host.presetManagementInterfaceForTopology(t)

                # Create network bridges.
                for b in self.bridges:
                    host = xenrt.TEC().registry.hostGet(b["host"]["name"]) 
                    host.createNetwork(b["name"])

                # Add ISO SRs to pool masters and independent hosts.
                # This should only be done on the first prepare and not on
                # subsequent re-prepares.
                if self.preparecount == 1:
                    for host in masters:
                        if not host.has_key("noisos") or not host["noisos"]:
                            self.srs.append({"host":host["name"], 
                                             "name":"XenRT ISOs",
                                             "type":"iso",
                                             "path":xenrt.TEC().lookup("EXPORT_ISO_NFS"),
                                             "default":False,
                                             "blkbackPoolSize":""})
                            isos2 = xenrt.TEC().lookup("EXPORT_ISO_NFS_STATIC", None)
                            if isos2:
                                self.srs.append({"host":host["name"],
                                                 "name":"XenRT static ISOs",
                                                 "type":"iso",
                                                 "path":isos2,
                                                 "default":False,
                                                 "blkbackPoolSize":""})

                # If needed, create lun groups
                iscsihosts = {}
                for s in self.srs:
                    if (s["type"] == "lvmoiscsi" or s["type"] == "extoiscsi") and not ((s["options"] and "ietvm" in s["options"].split(",")) or (s["options"] and "iet" in s["options"].split(","))):
                        if not iscsihosts.has_key(s["host"]):
                            iscsihosts[s["host"]] = 0
                        iscsihosts[s["host"]] += 1
                for h in iscsihosts.keys():
                    if iscsihosts[h] > 1:
                        # There are multiple iSCSI SRs for this host, we need a lun group
                        host = xenrt.TEC().registry.hostGet(h) 
                        minsize = int(host.lookup("SR_ISCSI_MINSIZE", 40))
                        maxsize = int(host.lookup("SR_ISCSI_MAXSIZE", 1000000))
                        # For now we don't support jumbo frames for lun groups in sequence files
                        host.lungroup = xenrt.resources.ISCSILunGroup(iscsihosts[h], jumbo=False, minsize=minsize, maxsize=maxsize)
                        host.setIQN(host.lungroup.getInitiatorName(allocate=True))

                # Create SRs.
                for s in self.srs:
                    host = xenrt.TEC().registry.hostGet(s["host"]) 
                    if s["type"] == "lvmoiscsi":
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr = xenrt.productLib(host=host).ISCSIStorageRepository(host, s["name"])
                        if s["options"] and "iet" in s["options"].split(","):
                            # Create the SR using an IET LUN from the controller
                            lun = xenrt.ISCSITemporaryLun(300)
                            sr.create(lun, subtype="lvm", multipathing=mp, noiqnset=True, findSCSIID=True)
                        elif s["options"] and "ietvm" in s["options"].split(","):
                            # Create the SR using an IET LUN from the controller
                            lun = xenrt.ISCSIVMLun(s["vmhost"],int(s["size"])*xenrt.KILO)
                            sr.create(lun, subtype="lvm", multipathing=mp, noiqnset=True, findSCSIID=True)
                        else:
                            if s["options"] and "jumbo" in s["options"].split(","):
                                jumbo = True
                            else:
                                jumbo = False
                            if s["options"] and "mpprdac" in s["options"].split(","):
                                mpp_rdac = True
                            else:
                                mpp_rdac = False
                            initiatorcount = None
                            if s["options"]:
                                for o in s["options"].split(","):
                                    m = re.match("initiatorcount=(\d+)", o)
                                    if m:
                                        initiatorcount = int(m.group(1))
                            sr.create(subtype="lvm", multipathing=mp, jumbo=jumbo, mpp_rdac=mpp_rdac, initiatorcount = initiatorcount)
                    elif s["type"] == "extoscsi":
                        sr = xenrt.productLib(host=host).ISCSIStorageRepository(host, s["name"])
                        if s["options"] and "jumbo" in s["options"].split(","):
                            jumbo = True
                        else:
                            jumbo = False
                        sr.create(subtype="ext", jumbo=jumbo)
                    elif s["type"] == "nfs":
                        if s["options"] and "jumbo" in s["options"].split(","):
                            jumbo = True
                        else:
                            jumbo = False
                        if s["options"] and "nosubdir" in s["options"].split(","):
                            nosubdir = True
                        else:
                            nosubdir = False
                        if s["options"] and "filesr" in s["options"].split(","):
                            filesr = True
                        else:
                            filesr = False
                        if s["network"]:
                            network = s["network"]
                        else:
                            network = "NPRI"
                        server, path = xenrt.ExternalNFSShare(jumbo=jumbo, network=network).getMount().split(":")
                        if filesr:
                            sr = xenrt.productLib(host=host).FileStorageRepositoryNFS(host, s["name"])
                            sr.create(server, path)
                        else:
                            sr = xenrt.productLib(host=host).NFSStorageRepository(host, s["name"])
                            sr.create(server, path, nosubdir=nosubdir)
                    elif s["type"] == "iso":
                        sr = xenrt.productLib(host=host).ISOStorageRepository(host, s["name"])
                        server, path = s["path"].split(":")
                        sr.create(server, path)
                        sr.scan()
                    elif s["type"] == "netapp":
                        minsize = int(host.lookup("SR_NETAPP_MINSIZE", 40))
                        maxsize = int(host.lookup("SR_NETAPP_MAXSIZE", 1000000))
                        if s.has_key("options") and s["options"]:
                            options = s["options"]
                        else:
                            options = None
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        napp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
                        sr = xenrt.productLib(host=host).NetAppStorageRepository(host, s["name"])
                        sr.create(napp, options=options, multipathing=mp)
                    elif s["type"] == "eql" or s["type"] == "equal":
                        minsize = int(host.lookup("SR_EQL_MINSIZE", 40))
                        maxsize = int(host.lookup("SR_EQL_MAXSIZE", 1000000))
                        if s.has_key("options") and s["options"]:
                            options = s["options"]
                        else:
                            options = None
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        eql = xenrt.EQLTarget(minsize=minsize, maxsize=maxsize)
                        sr = xenrt.productLib(host=host).EQLStorageRepository(host, s["name"])
                        sr.create(eql, options=options, multipathing=mp)
                    elif s["type"] == "fc":
                        sr = xenrt.productLib(host=host).FCStorageRepository(host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        if s.has_key("options") and s["options"]:
                            fcsr = s["options"]
                        else:
                            fcsr = host.lookup("SR_FC", "yes")
                            if fcsr == "yes":
                                fcsr = "LUN0"
                        
                        scsiid = host.lookup(["FC", fcsr, "SCSIID"], None)
                        sr.create(scsiid, multipathing=mp)
                    elif s["type"] == "cvsmnetapp":
                        minsize = int(host.lookup("SR_NETAPP_MINSIZE", 40))
                        maxsize = int(host.lookup("SR_NETAPP_MAXSIZE", 1000000))
                        napp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
                        cvsmserver = xenrt.CVSMServer(\
                            xenrt.TEC().registry.guestGet("CVSMSERVER"))
                        cvsmserver.addStorageSystem(napp)
                        sr = xenrt.productLib(host=host).CVSMStorageRepository(\
                            host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr.create(cvsmserver,
                                  napp,
                                  protocol="iscsi",
                                  physical_size=None,
                                  multipathing=mp)
                    elif s["type"] == "cvsmeql":
                        minsize = int(host.lookup("SR_EQL_MINSIZE", 40))
                        maxsize = int(host.lookup("SR_EQL_MAXSIZE", 1000000))
                        napp = xenrt.EQLTarget(minsize=minsize, maxsize=maxsize)
                        cvsmserver = xenrt.CVSMServer(\
                            xenrt.TEC().registry.guestGet("CVSMSERVER"))
                        cvsmserver.addStorageSystem(napp)
                        sr = xenrt.productLib(host=host).CVSMStorageRepository(\
                            host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr.create(cvsmserver,
                                  napp,
                                  protocol="iscsi",
                                  physical_size=None,
                                  multipathing=mp)
                    elif s["type"] == "cvsmfc":
                        fchba = xenrt.FCHBATarget()
                        cvsmserver = xenrt.CVSMServer(\
                            xenrt.TEC().registry.guestGet("CVSMSERVER"))
                        cvsmserver.addStorageSystem(fchba)
                        sr = xenrt.productLib(host=host).CVSMStorageRepository(\
                            host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr.create(cvsmserver,
                                  fchba,
                                  protocol="fc",
                                  physical_size=None,
                                  multipathing=mp)
                    elif s["type"] == "cvsmsmisiscsi":
                        minsize = int(host.lookup("SR_SMIS_ISCSI_MINSIZE", 40))
                        maxsize = int(host.lookup("SR_SMIS_ISCSI_MAXSIZE", 1000000))
                        smisiscsi = xenrt.SMISiSCSITarget()
                        cvsmserver = xenrt.CVSMServer(\
                            xenrt.TEC().registry.guestGet("CVSMSERVER"))
                        cvsmserver.addStorageSystem(smisiscsi)
                        sr = xenrt.productLib(host=host).CVSMStorageRepository(\
                            host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr.create(cvsmserver,
                                  smisiscsi,
                                  protocol="iscsi",
                                  physical_size=None,
                                  multipathing=mp)
                    elif s["type"] == "cvsmsmisfc":
                        minsize = int(host.lookup("SR_SMIS_FC_MINSIZE", 40))
                        maxsize = int(host.lookup("SR_SMIS_FC_MAXSIZE", 1000000))
                        smisfc = xenrt.SMISFCTarget(minsize=minsize, maxsize=maxsize)
                        cvsmserver = xenrt.CVSMServer(\
                            xenrt.TEC().registry.guestGet("CVSMSERVER"))
                        cvsmserver.addStorageSystem(smisfc)
                        sr = xenrt.productLib(host=host).CVSMStorageRepository(\
                            host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr.create(cvsmserver,
                                  smisfc,
                                  protocol="fc",
                                  physical_size=None,
                                  multipathing=mp)
                    elif s["type"] == "icvsmnetapp":
                        minsize = int(host.lookup("SR_NETAPP_MINSIZE", 40))
                        maxsize = int(host.lookup("SR_NETAPP_MAXSIZE", 1000000))
                        napp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
                        sr = xenrt.productLib(host=host).IntegratedCVSMStorageRepository(\
                            host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr.create(napp,
                                  protocol="iscsi",
                                  physical_size=None,
                                  multipathing=mp)
                    elif s["type"] == "icvsmeql":
                        minsize = int(host.lookup("SR_EQL_MINSIZE", 40))
                        maxsize = int(host.lookup("SR_EQL_MAXSIZE", 1000000))
                        eql = xenrt.EQLTarget(minsize=minsize, maxsize=maxsize)
                        sr = xenrt.productLib(host=host).IntegratedCVSMStorageRepository(\
                            host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr.create(eql,
                                  protocol="iscsi",
                                  physical_size=None,
                                  multipathing=mp)
                    elif s["type"] == "icvsmfc":
                        fchba = xenrt.FCHBATarget()
                        sr = xenrt.productLib(host=host).IntegratedCVSMStorageRepository(\
                            host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr.create(fchba,
                                  protocol="fc",
                                  physical_size=None,
                                  multipathing=mp)
                    elif s["type"] == "icvsmsmisiscsi":
                        smisiscsi = xenrt.SMISiSCSITarget()
                        sr = xenrt.productLib(host=host).IntegratedCVSMStorageRepository(\
                            host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr.create(smisiscsi,
                                  protocol="iscsi",
                                  physical_size=None,
                                  multipathing=mp)
                    elif s["type"] == "icvsmsmisfc":
                        smisfc = xenrt.SMISFCTarget()
                        sr = xenrt.productLib(host=host).IntegratedCVSMStorageRepository(\
                            host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr.create(smisfc,
                                  protocol="fc",
                                  physical_size=None,
                                  multipathing=mp)
                    else:
                        raise xenrt.XRTError("Unknown storage type %s" % (s["type"]))
                    #change blkback pool size
                    if s["blkbackPoolSize"]:
                        sr.paramSet(paramName="other-config:mem-pool-size-rings", paramValue=s["blkbackPoolSize"])
                    host.addSR(sr, default=s["default"])
                    if s["default"]:
                        p = host.minimalList("pool-list")[0]
                        host.genParamSet("pool", p, "default-SR", sr.uuid)
                        host.genParamSet("pool", p, "crash-dump-SR", sr.uuid)
                        host.genParamSet("pool", p, "suspend-image-SR", sr.uuid)

                if xenrt.TEC().lookup("PAUSE_BEFORE_POOL", False, boolean=True):
                    xenrt.TEC().tc.pause("Pausing before creating pool(s)")

                # Add the slaves to the pools, they should all pick up the
                # relevant SRs and network config
                forceJoin = xenrt.TEC().lookup("POOL_JOIN_FORCE", False, boolean=True)
                totalSlaves = 0
                for p in self.pools:
                    master = xenrt.TEC().registry.hostGet(p["master"])
                    pool = xenrt.productLib(host=master).poolFactory(master.productVersion)(master)
                    if p["ssl"]:
                        pool.configureSSL()
                    slaves = filter(lambda x:x["pool"] == p["name"] \
                                     and not x["name"] == p["master"],
                                     self.hosts)
                    totalSlaves += len(slaves)
                    for s in slaves:
                        slave = xenrt.TEC().registry.hostGet(s["name"])
                        pool.addHost(slave, force=forceJoin)
                    xenrt.TEC().registry.poolPut(p["name"], pool)

                if totalSlaves > 0 and len(self.networksForPools) > 0:
                    # Allow 5 minutes for the slaves to create network objects etc CA-47814
                    
                    xenrt.sleep(300)

                # If we have a network topology definition then apply the
                # management/IP part of that to the slaves. First check them
                # have correctly inherited the VLANs/bonds
                for p in self.pools:
                    if self.networksForPools.has_key(p["name"]):
                        t = self.networksForPools[p["name"]]
                        slaves = filter(lambda x:x["pool"] == p["name"] \
                                         and not x["name"] == p["master"],
                                         self.hosts)
                        queue = InstallWorkQueue()
                        for s in slaves:
                            queue.add((s, t))
                        workers = []
                        for i in range(max(int(xenrt.TEC().lookup("PREPARE_WORKERS", "4")), 4)):
                            w = SlaveManagementWorker(queue, name="SMWorker%02u" % (i))
                            workers.append(w)
                            w.start()
                        for w in workers:
                            w.join()
                        for w in workers:
                            if w.exception:
                                raise w.exception

                # Check all hosts are marked as enabled
                xenrt.TEC().logverbose("Checking all hosts are enabled")
                hostsToCheck = []
                hostsToCheck.extend(\
                    map(lambda h:xenrt.TEC().registry.hostGet(h["name"]),
                        self.hosts))
                deadline = xenrt.util.timenow() + 1200
                while True:
                    if len(hostsToCheck) == 0:
                        break
                    for h in hostsToCheck:
                        if h.isEnabled():
                            hostsToCheck.remove(h)
                    if xenrt.util.timenow() > deadline:
                        raise xenrt.XRTFailure(\
                            "Timed out waiting for hosts to be enabled: %s" %
                            (string.join(map(lambda x:x.getName(), hostsToCheck))))
                    xenrt.sleep(30, log=False)
                    
                if xenrt.TEC().lookup("OPTION_ENABLE_REDO_LOG", False, boolean=True):
                    for p in self.pools:
                        pool = xenrt.TEC().registry.poolGet(p["name"])
                        defaultsr = pool.master.minimalList("pool-list", "default-SR")[0]
                        pool.master.getCLIInstance().execute("pool-enable-redo-log", "sr-uuid=%s" % defaultsr)

            # Run pre job tests on all hosts
            for h in map(lambda i:xenrt.TEC().registry.hostGet(i["name"]), self.hosts):
                h.preJobTests()
            xenrt.GEC().preJobTestsDone = True

            if len(self.vms) > 0:
                queue = InstallWorkQueue()
                for v in self.vms:
                    queue.add(v)
                workers = []
                for i in range(max(int(xenrt.TEC().lookup("PREPARE_WORKERS", "4")), 4)):
                    w = GuestInstallWorker(queue, name="GWorker%02u" % (i))
                    workers.append(w)
                    w.start()
                for w in workers:
                    w.join()
                for w in workers:
                    if w.exception:
                        raise w.exception
            
            if not nohostprepare:
                xenrt.TEC().logverbose("Controller configurations: %s %s" % 
                                       (self.controllersForPools, self.controllersForHosts)) 
                for p in self.controllersForPools:
                    controller = xenrt.TEC().registry.guestGet(self.controllersForPools[p])
                    pool = xenrt.TEC().registry.poolGet(p)
                    pool.associateDVS(controller.getDVSCWebServices())
                for h in self.controllersForHosts:
                    controller = xenrt.TEC().registry.guestGet(self.controllersForHosts[h])
                    host = xenrt.TEC().registry.hostGet(h)
                    host.associateDVS(controller.getDVSCWebServices())

                if self.cloudSpec:
                    xenrt.lib.cloud.deploy(self.cloudSpec)

        except Exception, e:
            sys.stderr.write(str(e))
            traceback.print_exc(file=sys.stderr)
            if xenrt.TEC().lookup("AUTO_BUG_FILE", False, boolean=True):
                # File a Jira Bug
                try:
                    jl = xenrt.jiralink.getJiraLink()
                    jl.processPrepare(xenrt.TEC(),str(e))
                except Exception, jiraE:
                    xenrt.GEC().logverbose("Jira Link Exception: %s" % (jiraE),
                                           pref='WARNING')

            raise

class InstallWorkQueue:
    """Queue of install work items to perform."""
    def __init__(self):
        self.items = []
        self.mylock = threading.Lock()

    def consume(self):
        self.mylock.acquire()
        reply = None
        try:
            if len(self.items) > 0:
                reply = self.items.pop()
        finally:
            self.mylock.release()
        return reply

    def add(self, item):
        self.mylock.acquire()
        try:
            self.items.append(item)
        finally:
            self.mylock.release()

class _InstallWorker(xenrt.XRTThread):
    """Worker thread for parallel host or guest installs (parent class)"""
    def __init__(self, queue, name=None):
        self.queue = queue
        self.exception = None
        xenrt.XRTThread.__init__(self, name=name)

    def doWork(self, work):
        pass

    def run(self):
        xenrt.TEC().logverbose("Install worker '%s' starting..." %
                               (self.getName()))
        while True:
            work = self.queue.consume()
            if not work:
                break
            try:
                self.doWork(work)
            except xenrt.XRTException, e:
                sys.stderr.write(str(e))
                traceback.print_exc(file=sys.stderr)
                self.exception = e
                self.exception_extended = sys.exc_info()
                xenrt.TEC().logverbose(str(e), pref='REASON')
                if e.data:
                    xenrt.TEC().logverbose(str(e.data)[:1024], pref='REASONPLUS')
            except Exception, e:
                reason = "Unhandled exception %s" % (str(e))
                sys.stderr.write(str(e))
                traceback.print_exc(file=sys.stderr)
                self.exception = e
                self.exception_extended = sys.exc_info()
                xenrt.TEC().logverbose(reason, pref='REASON')
                                        
class HostInstallWorker(_InstallWorker):
    """Worker thread for parallel host installs"""
    def doWork(self, work):
        if not xenrt.TEC().lookup("RESOURCE_HOST_%s" % (work["id"]), False):
            raise xenrt.XRTError("We require RESOURCE_HOST_%s but it has not been specified." % (work["id"]))
        initialVersion = xenrt.TEC().lookup("INITIAL_INSTALL_VERSION", None)
        versionPath = xenrt.TEC().lookup("INITIAL_VERSION_PATH", None)
        specProductType = "xenserver"
        specProductVersion = None
        specVersion = None
        if work.has_key("productType"):
            specProductType = work["productType"]
        if work.has_key("productVersion"):
            specProductVersion = work["productVersion"]
        if work.has_key("version"):
            specVersion = work["version"]

        if specProductType == "xenserver":
            if versionPath and not specProductVersion and not specVersion:
                # Install the specified sequence of versions and upgrades/updates
                if work.has_key("version"):
                    del work["version"]
                if work.has_key("productVersion"):
                    del work["productVersion"]
                if work.has_key("productType"):
                    del work["productType"]
                work["versionPath"] = versionPath
                xenrt.TEC().logverbose("Installing using version path %s" %
                                       (versionPath))
                host = xenrt.lib.xenserver.host.createHostViaVersionPath(**work)
            elif initialVersion and not specProductVersion and not specVersion:
                # Install this version and upgrade afterwards
                inputdir = xenrt.TEC().lookup("PRODUCT_INPUTDIR_%s" %
                                              (initialVersion.upper()), None)
                if not inputdir:
                    inputdir = xenrt.TEC().lookup("PIDIR_%s" %
                                                  (initialVersion.upper()), None)
                if not inputdir:
                    raise xenrt.XRTError("No product input directory set for %s" %
                                         (initialVersion))
                work["version"] = inputdir
                work["productVersion"] = initialVersion
                xenrt.TEC().logverbose("Installing using initial version %s" %
                                       (initialVersion))
                license = None
                if work.has_key("license"):
                    license = work["license"]
                    del work["license"]
                    xenrt.TEC().logverbose("Ignoring license information for previous version install")
                host = xenrt.lib.xenserver.host.createHost(**work)
                xenrt.TEC().setInputDir(None)
                xenrt.TEC().logverbose("Upgrading to current version")
                host = host.upgrade()
                if license:
                    xenrt.TEC().logverbose("Licensing upgraded host...")
                    if type(license) == type(""):
                        host.license(sku=license)
                    else:
                        host.license()
            else:
                # Normal install of the default or host-specified version
                xenrt.TEC().setInputDir(None)
                xenrt.lib.xenserver.host.createHost(**work)
        elif specProductType == "nativelinux":
            if specProductType is None:
                raise xenrt.XRTError("We require a ProductVersion specifying the native Linux host type.")
            work["noisos"] = True
            xenrt.lib.native.createHost(**work)
        elif specProductType == "kvm":
            xenrt.lib.kvm.createHost(**work)
        elif specProductType == "esx":
            xenrt.lib.esx.createHost(**work)
        elif specProductType == "oss":
            work["noisos"] = True
            xenrt.lib.oss.createHost(**work)
        else:
            raise xenrt.XRTError("Unknown productType: %s" % (specProductType))

class GuestInstallWorker(_InstallWorker):
    """Worker thread for parallel guest installs"""
    def doWork(self, work):
        if work.has_key("filename"):
            xenrt.productLib(hostname=work["host"]).guest.createVMFromFile(**work)
        else:
            xenrt.productLib(hostname=work["host"]).guest.createVM(**work)

class SlaveManagementWorker(_InstallWorker):
    """Worker thread for parallel slave management interface reconfigures"""
    def doWork(self, work):
        s = work[0] # Slave machine
        t = work[1] # Network topology
        slave = xenrt.TEC().registry.hostGet(s["name"])
        slave.checkNetworkTopology(t,
                                   ignoremanagement=True,
                                   ignorestorage=True)
        slave.addIPConfigToNetworkTopology(t)
        slave.checkNetworkTopology(t)
        
