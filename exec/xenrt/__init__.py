#
# XenRT: Test harness for Xen and the XenServer product family
#
# Common datatypes and functions
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#


"""Top level XenRT harness library.
"""

import sys, string, os.path, traceback, time, tempfile, stat, threading, re
import socket, os, shutil, xml.dom.minidom, thread, glob, inspect, types, urllib2
import signal, popen2, IPy, urllib, json
from zope.interface import providedBy

def irregularName(obj):
    """Decorator to declare that the item being decorated does not have a name
    that adheres to the XenRT coding standards. XenRT code should only use this
    decorator when it isn't possible to name the item correctly. For example, 
    when deriving from a standard Python class which follows a different
    naming convention"""
    
    return obj

# General constants

KILO = 1024
MEGA = 1048576
GIGA = 1073741824

# XenRT Constants

RC_OK    = 0
RC_ERROR = 1
RC_FAIL  = 2

TCI_NEW = 0
TCI_RUNNING = 1
TCI_DONE = 2

RESULT_UNKNOWN = 0
RESULT_NOTRUN = 0
RESULT_PASS = 1
RESULT_FAIL = 2
RESULT_PARTIAL = 3
RESULT_ERROR = 4
RESULT_SKIPPED = 5
RESULT_ALLOWED = 6

RESULTS = ["notrun", "pass", "fail", "partial", "error", "skipped"]

DEFAULT = -10

STATE_DOWN = 0
STATE_UP = 1
STATE_PAUSED = 2
STATE_SUSPENDED = 3

def resultDisplay(resultcode):
    """Turn a numeric result code into a string result description."""
    global RESULTS
    if resultcode >= len(RESULTS):
        return "unknown"
    return RESULTS[resultcode]

STANDARD_LOGS = ["/var/log/messages",
                 "/var/log/daemon.log",
                 "/var/log/user.log",
                 "/var/log/xend.log",
                 "/var/log/xend-debug.log",
                 "/var/log/xen-hotplug.log",
                 "/var/log/xensource.log",
                 "/var/log/statehack.log",
                 "/var/log/tcp_dump",
                 "/var/log/xenrt-write-counter.log",
                 "/var/log/xenrt-write-counter-sda.log",
                 "/var/log/xenrt-write-counter-sdb.log",
                 "/var/log/xenrt-write-counter-sdc.log",
                 "/var/log/xenrt-write-counter-sdd.log",
                 "/var/log/xenrt-write-counter-sde.log",
                 "/var/log/xenrt-write-counter-sdf.log",
                 "/var/log/xha.log",
                 "/var/log/SMlog",
                 "/var/log/kern.log",
                 "/var/log/isl_trace.log",
                 "/var/xapi/state.db",
                 "/var/log/tapback",
                 "!/opt/xensource/libexec/sm_diagnostics",
                 "!xenstore-ls",
                 "!list_domains -all",
                 "!xn diagnostics",
                 "!df -h"]

STANDARD_LOGS_NON_PASS = ["/var/log/xen"]

STANDARD_LOGS_WINDOWS = ["c:\\Program Files\\Citrix\\XenTools\\install.log",
                         "c:\\Program Files (x86)\\Citrix\\XenTools\\install.log",
                         "c:\\Program Files\\Citrix\\XenTools\\copyvif.log.txt",
                         "c:\\Program Files (x86)\\Citrix\\XenTools\\copyvif.log.txt",
                         "c:\\ProgramData\\Citrix",
                         "c:\\windows\\inf\\setupapi.dev.log",
                         "c:\\pssnapininstall.log",
                         "c:\\tools_msi_install.log",
                         "c:\\uninst.bat",
                         "c:\\dotnet40logs",
                         "C:\\Windows\\Logs\\DISM\\dism.log",
                         "c:\\Windows\\Logs\\bluewaterUpdateInstallLogs.txt"]

STANDARD_LOGS_WINDOWS_NON_PASS = []

log_error_strings = {
    re.compile("The application-specific permission settings do not grant Local Activation permission for the COM Server application with CLSID\s+\{BA126AD1-2166-11D1-B1D0-00805FC1270E\}\s+to the user"): "IGNORE",
    re.compile("The DHCP Server sent a DHCPNACK message"): "IGNORE",
    re.compile("Configuring the Page file for crash dump failed"): "IGNORE",
    re.compile("Timed out in XenbusWaitForBackendStateChange; retry"): "IGNORE",
    re.compile("TX retrying end ring access"): "CA-17785",
    re.compile("Shutting down an adapter \S+ which wasn't properly created"): "CA-17786",
    re.compile("Waiting for backend at irql 2"): "CA-17787",
    re.compile("Failed 0xc0000056 to get PDO for TOS 0x\S+"): "CA-17788",
    re.compile("Timeout \(\d+ milliseconds\) waiting for a transaction response from the Dfs service"): "CA-17791",
    re.compile("releasing an in-use gnttab entry"): "CA-17792",
    re.compile("Unfreeze xenbus when it was already unfrozen"): "CA-17793",
    re.compile("errno 5 at tapdisk_vbd_make_response"): "CA-17794",
    re.compile("Set of unknown OID"): "CA-17795",
    re.compile("No handler for oid"): "CA-18067",
    re.compile("\[XENNET\]Failed to enable scatter-gather mode"): "CA-19893",
    re.compile("xenstored: TDB error on read: Corrupt database"): "CA-21593",
    re.compile("WARNING CA-20295"): "CA-20295",
    re.compile("ide_dma_start error: dma transfer already in progress"): "CA-24908",
    re.compile("Failed to open \\Registry\\Machine\\System\\CurrentControlSet\\Services\\NetBT\\Parameters\\Interfaces\\Tcpip"): "IGNORE CA-29805",
    re.compile(r"\\Device\\Scsi\\xenvbd1"): "IGNORE CA-31656",
    re.compile(r"DCOM got error .* attempting to start the service ImapiService"): "IGNORE CA-31947",
    re.compile(r"\\Device\\Http\\ReqQueue Kerberos"): "IGNORE CA-31948",
    re.compile(r"The Citrix Tools for Virtual Machines Service service is marked as an interactive service"): "IGNORE CA-32044",    
    re.compile(r"Installation of the Proof of Purchase failed"): "IGNORE",
    re.compile(r"vsctl\|ERR\|transaction error"): "CA-47094",
    }




import xenrt.resources, xenrt.ssh, xenrt.registry, xenrt.dbconnect, xenrt.infrastructuresetup

def version():
    """Returns the current harness version"""
    return "0.8"


#############################################################################
# Errors and failures                                                       #
#############################################################################

class XRTException(Exception):
    """Harness error. This exception should never be raised directly, use
XRTError and XRTFailure instead.
"""
    def __init__(self, reason=None, data=None):
        """Constructor.

        @param reason: the reason for the failure/error
        @param data:   arbitrary data associated with the failure/error
        """
        if reason:
            try:
                self.reason = str(reason)
            except UnicodeEncodeError:
                self.reason = reason.encode("utf-8")
        else: self.reason = None
        if data:
            try:
                self.data = str(data)
            except UnicodeEncodeError:
                self.data = data.encode("utf-8")
        else: self.data = None

    def changeReason(self, reason):
        """Update the reason text for this problem."""
        self.reason = str(reason)

    def __str__(self):
        return self.reason

class XRTError(XRTException):
    """Harness error.
    
    Used for problems which are not a failure of the testcase.
    """
    pass

class XRTSkip(XRTException):
    """Test skip (use only in subcases)."""
    pass

class XRTFailure(XRTException):
    """Test failure."""
    pass

class XRTBlocker(Exception):
    """Blocking failure"""
    def __init__(self, testcase):
        """Constructor.

        @param testcase: the testcase instance causing the blockage.
        """
        self.testcase = testcase

    def __str__(self):
        return "Blocked by %s" % (self.testcase.tcid)

def XRT(message, level, data=None, check=None):
    """Raise an exception or return an error code depending on level.

    Some utility functions support two usage models:
    
      1. raise an exception on failure
      2. return an error code on failure

    This function allows the utility functions to easily perform the
    correct action based on the level argument.

    @param message: text message to use when raising an exception
    @param level: the notification level
        1. L{xenrt.RC_ERROR} to raise a harness error
        2. L{xenrt.RC_FAIL} to raise a test failure
        3. L{xenrt.RC_OK} to raise no exception but return non-zero
    @param data: optional data to add to exception
    @param check: optional L{GenericPlace}, or list of the same, to check"""
    if level == RC_OK:
        return RC_ERROR
    if check:
        # Check one or more places for health, any failures here override
        # the failure we were going to raise. check can be an instance or a
        # list of instances of GenericPlace
        if isinstance(check, xenrt.objects.GenericPlace):
            check.checkHealth()
        else:
            for c in check:
                c.checkHealth()
    if level == RC_FAIL:
        raise XRTFailure(message, data)
    raise XRTError(message, data)

#############################################################################
# Test execution context management                                         #
#############################################################################

_anontec = None
_tecs = {}
_gec = None
_threads = {} # Maps thread names to XRTThread objects where known
def TEC():
    """Returns the TestExecutionContext instance for the current thread."""
    global _tecs, _anontec
    t = threading.currentThread().getName()
    if not _tecs.has_key(t):
        return _anontec
    return _tecs[t]

def setTec(tec=None):
    """Sets the TestExecutionContext for the current thread. If no argument
is given, or the argument is None, the thread is given the anonymous context.
"""
    global _tecs
    t = threading.currentThread().getName()
    if tec:
        _tecs[t] = tec
    elif _tecs.has_key(t):
        del _tecs[t]
    TEC().logverbose("Setting %s TEC to %s" % (t, str(tec)))

def myThread():
    """Returns the XRTThread object for the current thread or None if not
    known."""
    global _threads
    t = threading.currentThread().getName()
    if _threads.has_key(t):
        return _threads[t]
    return None

class XRTThread(threading.Thread):
    """A thread object that associates itself with the existing TEC."""

    def start(self):
        # Define a thread local configuration space. This can be queried
        # recursively until we get a hit
        self._config = {}
        
        # Maintain a mapping from thread name to XRTThread objects
        global _threads
        _threads[self.getName()] = self
        
        # Maintain a link to the parent thread
        tn = TEC()._my_thread_name
        if _threads.has_key(tn):
            self._parent_thread = _threads[tn]
        else:
            self._parent_thread = None
        
        # Update the TEC table with this thread object's name to point
        # to the same TEC as the thread we were in when starting this one
        global _tecs
        tec = TEC()
        _tecs[self.getName()] = tec
        threading.Thread.start(self)

    def lookup(self, variable):
        """Look up a variable in the configuration space. If it does not
        exists here the lookup continues to the parent thread until no
        parent can be found. If no match is found None is returned."""
        if self._config.has_key(variable):
            return self._config[variable]
        if not self._parent_thread:
            return None
        return self._parent_thread.lookup(variable)

    def setVariable(self, variable, value):
        """Set a variable in the thread local configuration space."""
        self._config[variable] = value
        xenrt.TEC().logverbose(\
            "Setting thread local variable for thread '%s': %s=%s" %
            (self.getName(), variable, value))

def GEC():
    """Returns the GlobalExecutionContext."""
    global _gec
    return _gec

def setGec(gec):
    """Sets the GlobalExecutionContext"""
    global _gec
    _gec = gec

#############################################################################

class TestCase(object):
    """The definition and implementation of a testcase.

    This is the parent class for all testcases."""
    iamtc = True
    SUBCASE_TICKETS = False
    
    def __init__(self, tcid=None, anon=False):
        """Constructor.

        @param tcid: testcase identifier - a text name for the testcase
        @param anon: set to C{True} to create the anonymous testcase and its context
        """
        if tcid:
            self.tcid = tcid
        else:
            # Use the name of the class
            self.tcid = self.__class__.__name__
            # Yeah baby
        self.priority = 1
        self.results = xenrt.results.TestResults(priority=self.priority)
        if xenrt.GEC().config.lookup("TEC_ALLOCATE", True, boolean=True):
            self.tec = TestExecutionContext(xenrt.GEC(), self, anon=anon)
            setTec(self.tec)
        self.basename = self.tcid
        self.state = TCI_NEW
        self.reply = None
        self.blocker = False
        self.iamtc = True
        self.subcases = {}
        self.subcasesOrder = []
        self._host = None
        self._guest = None
        self.runon = None
        self.group = None
        self.jiratc = None
        self.tcsku = None
        self.marvinTestConfig = None
        self.logsfrom = {}
        self._anon = anon
        if anon:
            self.runningtag = "Anonymous"
        else:
            self.runningtag = None
        self._started = None
        self.semclass = None
        self._bluescreenGuests = []
        self._guestsToUninstall = []
        self._guestsToShutdown = []
        self._templatesToRemove = []
        self.ticket = None
        self.ticketIsFailure = True
        self._crashdumpTickets = []
        self.xentoplogger = None
        self._fhsToClose = []
        self._initDone = True
        ### This is to provide the testcase instance to the debugger, inorder to allow the debugger to pause
        if 'xenrt.lib.debugger' in sys.modules:
            self.debugger = xenrt.lib.debugger.debuggerFunctions(self)
        return

    #########################################################################
    # Test naming, grouping, etc.

    def _setPriority(self, prio):
        """Set the integer priority of the testcase."""
        self.priority = prio
        self.results.priority = prio

    def _rename(self, name):
        """Change the text name of the testcase."""
        self.tcid = name

    def _setBaseName(self, name):
        """Sets the base name of the testcase."""
        self.basename = name

    def _setGroup(self, group):
        """Set the group the testcase belongs to."""
        self.group = group

    def getPhase(self):
        phase = getattr(self, 'group', None)
        if not phase:
            phase = "Phase 99"
        return phase

    #########################################################################
    # Result management

    def getResult(self, code=False):
        """Get the result of the testcase.

        @param code: if C{True} return the integer result code
            if C{False} return a string result description
        """
        if code:
            return self.results.getOverallResult()
        return resultDisplay(self.results.getOverallResult())

    def getOverallResult(self):
        """Return the integer result code for testcase.

        Same as getResult(code=True)
        """
        return self.results.getOverallResult()

    def setResult(self, result):
        """Set the over all test outcome.

        @param result: the integer result code for the testcase"""
        self.results.setOverallResult(result)

    def readResults(self, filename):
        """Read a test results XML file into the testcase results store."""
        return self.results.parseFile(filename)

    def testcaseResult(self, group, testcase, result, reason=None):
        """Set an individual subtestcase result.

        @param group: subcase group name
        @param testcase: subcase name
        @param result: integer result code for the subcase
        @param reason: optional reason description for failure/error
        """
        self.results.setResult(group, testcase, result, reason=reason)

    def declareTestcase(self, group, testcase):
        """Place a not-run result for a subtestcase we've yet to start."""
        self.testcaseResult(group, testcase, RESULT_NOTRUN)

    def getData(self):
        """Return a list of (key, value) pairs suitable for a database
logdata call.
"""
        return self.tec.getData()

    def summary(self, fd, pretty=True):
        """Summarise the testcase results.

        @param fd:     file descriptor to write to (must have a C{write()} method)
        @param pretty: set to C{True} to pretty-print the summary
        """
        if self.group:
            g = self.group
        else:
            g = ''
        self.results.summary(fd, g, self.basename)

    def gather(self, list):
        """Gather subtestcase results into the existing list supplied."""
        if self.group:
            g = self.group
        else:
            g = ''
        self.results.gather(list, g, self.basename)

    def getFailures(self):
        """Return a list of subtestcase failures."""
        if self.group:
            g = self.group
        else:
            g = ''
        return self.results.getFailures(g, self.basename)
    
    def getTestCases(self):
        """Return a list of subtestcases in this testcase."""
        if self.group:
            g = self.group
        else:
            g = ''
        return self.results.getTestCases(g, self.basename)

    def setJiraTC(self, jiratc):
        self.jiratc = jiratc

    def setTCSKU(self, tcsku):
        self.tcsku = tcsku

    def getDefaultJiraTC(self):
        return None

    #########################################################################
    # Testcase execution

    def prepare(self, arglist=None):
        """Method that will be called before the testcase run method.

        Testcase implementations may override this. By default nothing is
        done.

        @param arglist: list of string arguments given to the testcase
        """
        pass
    
    def _start(self, arglist=None, host=None, guest=None, isfinally=False):
        """Start the execution of this test case.

        This method is called by the testcase despatch mechanism. It should
        not be overriden by the testcase implementation.

        @param arglist: list of string arguments given to the testcase
        @param host: string host name to execute on (optional)
        @param guest: string guest name to execute on (optional)
        @param isfinally: C{True}/C{False} to determine is this testcase is part of
            a "finally" construct in a test sequence
        """
        self._host = host
        self._guest = guest
        self._started = xenrt.util.timenow()
        self._runWrapper(arglist, isfinally=isfinally)

    def run(self, arglist=None):
        """Testcase implementation method.

        The testcase implementation must provide a run() method to perform
        the testcase operations.

        @param arglist: list of string arguments given to the testcase
        """
        raise XRTError("Testcase body missing")

    def preLogs(self):
        """Method that will be called after the testcase has been run.

        This method is executed before logs are collected by the harness.

        Testcase implementations may override this. By default nothing is
        done.
        """
        pass

    def postRun(self):
        """Method that will be called after the testcase has been run.

        This method is executed after logs have been collected by the
        harness.

        Testcase implementations may override this. By default nothing is
        done.
        """
        pass

    def postRun2(self):
        """Method that will be called after the testcase has been run and
        any temporary VMs have been uninstalled.

        Testcase implementations may override this. By default nothing is
        done.
        """
        pass

    
    def _runWrapper(self, arglist, isfinally=False):
        """Execute the testcase and record the results.

        This method is called by start(). It performs the following functions:
         - (optional) waits on a per-test semaphore
         - runs the testcase prepare() method
         - runs the testcase run() method
         - record testcase result based on exceptions from run()
         - initiated interactive pauses based on result and configuration
         - runs the testcase preLogs() method
         - initiates fetch of logs from relevant host(s) and guest(s)
         - runs the testcase postRun() method

         @param arglist: list of string arguments given to the testcase
         @param isfinally: C{True}/C{False} to determine is this testcase is part of
             a "finally" construct in a test sequence
        """
        loc = []
        if self.runon:
            loc.append("host:%s" % (self.runon.getName()))
        if self._host:
            loc.append("host:%s" % (self._host))
        if self._guest:
            loc.append("host:%s" % (self._guest))
        
        GEC().dbconnect.jobLogData(self.getPhase(), str(self.basename), "comment", "Working directory %s" % self.tec.getWorkdir())
        if not self.tec.config.nologging:
            GEC().dbconnect.jobLogData(self.getPhase(), str(self.basename), "comment", "Log directory %s" % self.tec.getLogdir())
        
        xenrt.TEC().logverbose("Starting %s %s" % (self.tcid, string.join(loc)))
        self.state = TCI_RUNNING
        reason = ""
        try:
            if self.semclass:
                semclass = self.semclass
            else:
                semclass = self.basename
            GEC().semaphoreAcquire(semclass)
            
            try:
                try:
                    xenrt.TEC().logdelimit("prepare actions")
                    self.prepare(arglist)
                except XRTFailure, e:
                    # Any prepare failures become errors
                    raise XRTError, XRTError(e.reason, e.data), sys.exc_info()[2]
                try:
                    if xenrt.TEC().lookup("OPTION_COLLECT_XENTOP", False, boolean=True):
                        self.xentoplogger = xenrt.util.startXentopLogger(self.getDefaultHost(), 
                                                                        "%s/xentop.log" % 
                                                                        (xenrt.TEC().getLogdir()))
                except Exception, e:
                    xenrt.TEC().warning("Failed to start Xentop logger. (%s)" % (str(e)))
                xenrt.TEC().logdelimit("testcase body")
                xenrt.GEC().dbconnect.jobLogData(self.getPhase(), str(self.basename), "comment", "Testcase body started")

                if self.getResult(code=True) != RESULT_SKIPPED:
                    self.reply = self.run(arglist)
            finally:
                xenrt.GEC().dbconnect.jobLogData(self.getPhase(), str(self.basename), "comment", "Testcase body finished")
                if self.xentoplogger:
                    self.xentoplogger.stopLogging()
                GEC().semaphoreRelease(semclass)
            if self.group:
                g = self.group
            else:
                g = ''
            self.results.aggregate(g, self.basename)
        except XRTFailure, e:
            self.setResult(RESULT_FAIL)
            if e.reason:
                reason = str(e)
                sys.stderr.write(str(e).rstrip()+'\n')
                traceback.print_exc(file=sys.stderr)
                self.tec.logverbose(traceback.format_exc())
                self.results.reason(str(e))
                self.tec.logverbose(str(e), pref='REASON')
                if e.data:
                    self.tec.logverbose(str(e.data)[:1024], pref='REASONPLUS')
        except XRTError, e:
            self.setResult(RESULT_ERROR)
            if e.reason:
                reason = str(e)
                sys.stderr.write(str(e).rstrip()+'\n')
                traceback.print_exc(file=sys.stderr)
                self.tec.logverbose(traceback.format_exc())
                self.results.reason(str(e))
                self.tec.logverbose(str(e), pref='REASON')
                if e.data:
                    self.tec.logverbose(str(e.data)[:1024], pref='REASONPLUS')
        except Exception, e:
            reason = "Unhandled exception %s" % (str(e))
            self.results.reason(reason)
            self.tec.logverbose(reason, pref='REASON')
            sys.stderr.write(str(e).rstrip()+'\n')
            traceback.print_exc(file=sys.stderr)
            self.tec.logverbose(traceback.format_exc())
            self.setResult(RESULT_ERROR)
        self.state = TCI_DONE
        self.tec.logverbose("Test result: %s" % (self.getResult()))
        # We might want to ask the user for assistance before
        # continuing

        # We need to know if Xapi DB has locked out
        # with DB replication turned ON
        if self.tec.lookup('DEBUG_CA65062', False, boolean=True):
            r = self.getResult(code=True)
            if r != RESULT_PASS and r != RESULT_SKIPPED and \
                    r != RESULT_PARTIAL:
                if (re.search(r'\s+timed\s+out', reason)):
                    self.pause("test failed (DEBUG_CA65062)")
                    
        if (self.tec.lookup(["CLIOPTIONS", "PAUSE_ON_FAIL", "ALL"],
                            False,
                            boolean=True) or \
             self.tec.lookup(["CLIOPTIONS", "PAUSE_ON_FAIL", self.basename],
                             False,
                             boolean=True) or \
             (self.jiratc and self.tec.lookup(["CLIOPTIONS", "PAUSE_ON_FAIL", string.replace(self.jiratc,"-","")],
                             False,
                             boolean=True))) and not isfinally:
            r = self.getResult(code=True)
            if r != RESULT_PASS and r != RESULT_SKIPPED and \
                    r != RESULT_PARTIAL:
                self.pause("test failed")
        if (self.tec.lookup(["CLIOPTIONS", "PAUSE_ON_PASS", "ALL"],
                            False,
                            boolean=True) or \
             self.tec.lookup(["CLIOPTIONS", "PAUSE_ON_PASS", self.basename],
                             False,
                             boolean=True)) and not isfinally:
            if self.getResult(code=True) == RESULT_PASS or \
                    r == RESULT_PARTIAL:
                self.pause("test passed")
        # Pre logs actions
        try:
            if self.getResult(code=True) != RESULT_SKIPPED \
                and not self.tec.lookup(["CLIOPTIONS", "NOPRELOGS"], False,
                                        boolean=True):
                xenrt.TEC().logdelimit("preLogs actions")
                self.preLogs()
        except:
            pass
        if self.getResult(code=True) != RESULT_SKIPPED:
            try:
                xenrt.TEC().logdelimit("log retrieval")
                if self.tec.lookup("NO_LOGS_ON_PASS", False, boolean=True) \
                        and self.getResult(code=True) == RESULT_PASS:
                    xenrt.TEC().logverbose("Not recording logs for test pass")
                else:
                    # Flush any logging file handles we have open
                    for fh in self._fhsToClose:
                        try:
                            fh.flush()
                        except:
                            pass
                    self._getRemoteLogs()
            except Exception, e:
                self.tec.logverbose("Error fetching logs: %s" % (str(e)))

        # Post run actions
        try:
            if self.getResult(code=True) != RESULT_SKIPPED \
                and not self.tec.lookup(["CLIOPTIONS", "NOPOSTRUN"], False,
                                        boolean=True):
                xenrt.TEC().logdelimit("postRun actions")
                try:
                    self.postRun()
                except Exception, e:
                    xenrt.TEC().logverbose("TC postRun exception: %s" %
                                           (str(e)))
                for g in self._guestsToShutdown:
                    xenrt.TEC().logverbose("postRun shutdown of %s" %
                                           (g.getName()))
                    try:
                        if g.getState() == "UP":
                            g.shutdown(again=True)
                    except Exception, e:
                        xenrt.TEC().logverbose("Exception: %s" % (str(e)))
                for g in self._guestsToUninstall:
                    xenrt.TEC().logverbose("postRun uninstall of %s" %
                                           (g.getName()))
                    try:
                        if g.getState() == "SUSPENDED":
                            g.resume()
                    except Exception, e:
                        xenrt.TEC().logverbose("Exception: %s" % (str(e)))
                    try:
                        if g.getState() != "DOWN":
                            try:
                                g.shutdown(again=True)
                            except Exception, e:
                                xenrt.TEC().logverbose("Exception: %s" %
                                                       (str(e)))
                        g.uninstall()
                    except Exception, e:
                        xenrt.TEC().logverbose("Exception: %s" % (str(e)))
                    try:
                        self.tec.registry.guestDelete(g.getName())
                    except:
                        pass
                for ht in self._templatesToRemove:
                    try:
                        h, t = ht
                        h.removeTemplate(t)
                    except Exception, e:
                        xenrt.TEC().logverbose("Exception: %s" % (str(e)))
                self.postRun2()
        except Exception, e:
            xenrt.TEC().logverbose("Exception: %s" % (str(e)))

        # Close any file handles we left open
        for fh in self._fhsToClose:
            try:
                fh.close()
                self._fhsToClose.remove(fh)
            except:
                pass

    def runSubcase(self, method, args, scgroup, sctest):
        """Run a subcase test method and record its outcome.

        Subtestcases can be defined as method in the testcase class. They
        can be called via this method using reflection. This method handles
        the updating of results based on the exceptions thrown by the
        reflected method.

        @param method: string method name
        @param args: tuple of arguments to pass to the method
        @param scgroup: name of the subcase group to report this as
        @param sctest: name of the subcase testcase to report this as
        """
        self.tec.logdelimit("Running subcase %s/%s" % (scgroup, sctest))
        try:
            if args == ():
                eval("self.%s()" % (method))
            elif type(args) == type((1,2)):
                eval("self.%s(*args)" % (method))
            elif not hasattr(args, "__class__") or args.__class__.__module__ == "__builtin__":
                eval("self.%s(%s)" % (method, `args`))
            else:
                eval("self.%s(args)" % (method))
            self.testcaseResult(scgroup, sctest, RESULT_PASS)
            reply = RESULT_PASS
        except XRTFailure, e:
            self.testcaseResult(scgroup, sctest, RESULT_FAIL, str(e))
            self.tec.logverbose("%s/%s %s" % (scgroup, sctest, str(e)), pref='REASON')
            self.tec.logverbose(traceback.format_exc())
            if e.data:
                self.tec.logverbose("%s/%s %s" %
                                    (scgroup, sctest, str(e.data)[:1024]),
                                    pref='REASONPLUS')
            reply = RESULT_FAIL
        except XRTError, e:
            self.testcaseResult(scgroup, sctest, RESULT_ERROR, str(e))
            self.tec.logverbose("%s/%s %s" % (scgroup, sctest, str(e)), pref='REASON')
            self.tec.logverbose(traceback.format_exc())
            if e.data:
                self.tec.logverbose("%s/%s %s" %
                                    (scgroup, sctest, str(e.data)[:1024]),
                                    pref='REASONPLUS')
            reply = RESULT_ERROR
        except XRTSkip, e:
            self.testcaseResult(scgroup, sctest, RESULT_SKIPPED, str(e))
            self.tec.logverbose("%s/%s %s" % (scgroup, sctest, str(e)),
                                pref='REASON')
            reply = RESULT_SKIPPED
        except Exception, e:
            sys.stderr.write(str(e).rstrip()+'\n')
            self.tec.logverbose(traceback.format_exc())
            self.testcaseResult(scgroup, sctest, RESULT_ERROR, "Unknown exception")
            self.tec.logverbose("%s/%s unknown exception %s" %
                                (scgroup, sctest, str(e)))
            reply = RESULT_ERROR
        return reply
    
    def _waitfor(self):
        # TODO - currently not using asynchronous execution
        pass

    def _process(self, fd, db=None):
        """Produce a textual summary of the testcase data."""
        fd.write("Test: %s\n" % (self.getResult()))
        for i in self.results.reasons:
            try:
                fd.write("Reason: %s\n" % (i))
            except UnicodeEncodeError:
                fd.write("Reason: %s\n" % (i.encode("utf-8")))
        for i in self.results.comments:
            try:
                fd.write("Comment: %s\n" % (i))
            except UnicodeEncodeError:
                fd.write("Comment: %s\n" % (i.encode("utf-8")))
        for i in self.results.appresults:
            try:
                fd.write("Result: %s\n" % (i))
            except UnicodeEncodeError:
                fd.write("Result: %s\n" % (i.encode("utf-8")))
        for i in self.results.warnings:
            try:
                fd.write("Warning: %s\n" % (i))
            except UnicodeEncodeError:
                fd.write("Warning: %s\n" % (i.encode("utf-8")))
        for i in self.results.perfdata:
            p, v, u = i
            fd.write("Value: %s %s\n" % (str(p), str(v)))

    def pause(self, reason, text=None, email=None, indefinite=False):
        """Pause the testcase and wait for user assistance.

        @param reason: text reason for why we've paused
        @param text: text to add to the email message body
        @param email: address to send email to (default uses EMAIL variable)
        @param indefinite: pause indefinitely
        """
        xenrt.GEC().running[self.runningtag] = "Paused"
        xmlrpc = self.tec.lookup("XMLRPC", None)
        if xmlrpc:
            self.tec.comment("Pausing for user assistance (%s): %s" %
                             (xmlrpc, reason))
        else:
            self.tec.comment("Pausing for user assistance: %s" % (reason))

        if not self._anon:
            xenrt.GEC().dbconnect.jobLogData(self.getPhase(),
                                             str(self.basename),
                                             "result",
                                             "paused")
        if not email:
            email = self.tec.lookup("EMAIL", None)
        if email:
            jobid = xenrt.GEC().jobid()
            jobdesc = self.tec.lookup("JOBDESC", None)
            if not jobdesc:
                if jobid:
                    jobdesc = "JobID %s" % (jobid)
                else:
                    jobdesc = "a job"
            subject = "XenRT assistance required for %s" % (jobdesc)
            message = """
Testcase "%s" requires user intervention (%s). 
""" % (self.runningtag, reason)
            machines = []
            i = 0
            while True:
                m = xenrt.TEC().lookup("RESOURCE_HOST_%d" % (i), None)
                if not m:
                    break
                machines.append(m)
                i = i + 1
            if jobid:
                message = message + """JobID %s
Machine(s): %s

List testcases using: xenrt interact %s -l
Continue this testcase with: xenrt interact %s -c '%s'
Abort this testcase with: xenrt interact %s -n '%s'
""" % (jobid,
       string.join(machines, ","),
       jobid,
       jobid,
       self.runningtag,
       jobid,
       self.runningtag)
            xmlrpc = self.tec.lookup("XMLRPC", None)
            if xmlrpc:
                message =  message + "XML-RPC server %s\n" % (xmlrpc)
            if text:
                message = message + "\n" + text
            logdata = self.tec.readLogTail()
            message = message + "======================================"
            message = message + "======================================\n"
            message = message + "\n" + logdata
            try:
                xenrt.util.sendmail([email], subject, message)
            except Exception, e:
                xenrt.TEC().warning("Unable to send pause email '%s' Exception: '%s'" % (subject, str(e)))
        ph = int(xenrt.TEC().lookup("PAUSE_HOURS", "24"))
        deadline = xenrt.util.timenow() + (ph * 60 * 60)
        reply = False
        while True:
            if xenrt.GEC().running[self.runningtag] == "Continue":
                self.tec.comment("User intervention pause cancelled, continue")
                reply = True
                break
            elif xenrt.GEC().running[self.runningtag] == "NotContinue":
                self.tec.comment("User intervention pause cancelled, abort")
                break
            elif xenrt.GEC().running[self.runningtag] == "Indefinite" or indefinite:
                self.tec.comment("User intervention auto-unpause disabled")
                deadline = 0
            xenrt.sleep(30, log=False)
            if deadline and (xenrt.util.timenow() > deadline):
                self.tec.comment("User intervention pause timed out")
                break

        if not self._anon:
            xenrt.GEC().dbconnect.jobLogData(self.getPhase(),
                                             str(self.basename),
                                             "result",
                                             "continuing")
        return reply

    #########################################################################
    # Log management

    def _warnWithPrefix(self, text):
        """If the warning text (from a log check) matches a warning ticket
        regexp then prefix the text with the ticket ID. Log the warning
        unless the tag starts with 'IGNORE'."""
        global log_error_strings
        tag = ""
        for x in log_error_strings.keys():
            if x.search(text):
                tag = log_error_strings[x] + " "
                break
        if not "IGNORE" in tag:
            xenrt.TEC().warning(tag + text)

    def _getRemoteLogsFrom(self, obj, extraPaths=None):
        if isinstance(obj, xenrt.GenericPlace): 
            self._getRemoteLogsFromPlace(obj, extraPaths)
        elif isinstance(obj, xenrt.lib.generic.Instance):
            self._getRemoteLogsFromInstance(obj, extraPaths)
        elif xenrt.interfaces.Toolstack in providedBy(obj):
            self._getRemoteLogsFromToolstack(obj, extraPaths)

    def _getRemoteLogsFromInstance(self, instance, extraPaths):
        if xenrt.TEC().lookup("NO_GUEST_LOGS", False, boolean=True):
            return

        base = self.tec.getLogdir()
        try:
            instance.screenshot(base)
        except:
            xenrt.TEC().logverbose("Could not get screenshot from %s" % instance.name)

        d = "%s/%s" % (base, instance.name)
        if not os.path.exists(d):
            os.makedirs(d)
        instance.os.getLogs(d)

    def _getRemoteLogsFromToolstack(self, toolstack, extraPaths):
        d = "%s/%s" % (self.tec.getLogdir(), toolstack.name)
        if not os.path.exists(d):
            os.makedirs(d)
        toolstack.getLogs(d)

    def _getRemoteLogsFromPlace(self, place, extraPaths=None):
        """Fetch logs etc. from a host or guest.

        @param place: an instance of L{GenericPlace} to fetch from
        @param extraPaths: a list of extra paths for log files to capture
        """
        global log_error_strings

        if xenrt.TEC().lookup("NO_GUEST_LOGS", False, boolean=True) and isinstance(place, GenericGuest):
            return

        if isinstance(place, GenericGuest) and place.windows and \
           place.getState() == "PAUSED" and \
           not place in xenrt.TEC().tc._bluescreenGuests:
            # This is a crashed Windows guest that we don't know to have BSOD'd,
            # so check if this is the case
            xenrt.TEC().logverbose("Checking for BSOD")
            try:
                place.checkHealth()
            except:
                pass

        # Is this a guest that's bluescreened that we need to recover
        if place in xenrt.TEC().tc._bluescreenGuests:
            if not place.recoverGuest():
                # We couldn't recover it, so don't try to get other logs from it
                xenrt.TEC().warning("Unable to recover guest to check for "
                                    "dump files")
                return
            # Remove so we don't try and recover it again...
            xenrt.TEC().tc._bluescreenGuests.remove(place)

        # If place is a guest and it's not UP then don't try to contact it
        if isinstance(place, GenericGuest):
            if place.getState() != "UP":
                xenrt.TEC().logverbose("Guest %s isn't up: not getting logs" % str(place))
                return
        base = self.tec.getLogdir()
        d = "%s/%s" % (base, place.getName())
        if not os.path.exists(d):
            os.makedirs(d)
        if place.windows:
            xenrt.TEC().logverbose("Getting Windows logs for guest %s" % str(place))
            paths = []
            paths.extend(STANDARD_LOGS_WINDOWS)
            if place.extraLogsToFetch:
                paths.extend(place.extraLogsToFetch)
            if self.getResult(code=True) != RESULT_PASS:
                paths.extend(STANDARD_LOGS_WINDOWS_NON_PASS)
            if extraPaths:
                paths.extend(extraPaths)
            for lf in paths:
                if place.logFetchExclude and lf in place.logFetchExclude:
                    continue
                try:
                    if place.xmlrpcFileExists(lf, ignoreHealthCheck=True):
                        lfx = string.replace(lf, "\\", "/")
                        b = os.path.basename(lfx)
                        if place.xmlrpcDirExists(lf):
                            if not os.path.exists("%s/%s" % (d, b)):
                                os.makedirs("%s/%s" % (d, b))
                            place.xmlrpcFetchRecursive(lf, "%s/%s" % (d, b), ignoreHealthCheck=True)
                        else:
                            place.xmlrpcGetFile(lf, "%s/%s" % (d, b))
                except Exception, e:
                    traceback.print_exc(file=sys.stderr)
            # Get execdaemon log.
            try:
                place.xmlrpcGetFile("c:\\execdaemon.log", 
                                    "%s/execdaemon.log" % (d), ignoreHealthCheck=True)
            except:
                pass
            try:
                place.getWindowsEventLogs(d, ignoreHealthCheck=True)
            except Exception, e:
                xenrt.TEC().logverbose("Exception getting event logs: %s" %
                                       (str(e)))
                traceback.print_exc(file=sys.stderr)
            # parse logs for errors
            for log in ["system","application","security"]:
                if place.logFetchExclude and log in place.logFetchExclude:
                    continue
                try:
                    f = file("%s/%s.csv" % (d,log),"r")
                    lines = f.read().split("\n")
                    f.close()
                    for line in lines:
                        fields = line.split(",", 8)
                        if len(fields) == 9:
                            wecare = False
                            if fields[3] == "ERROR":
                                if fields[2] != "W32Time":
                                    wecare = True
                            elif fields[3] == "INFORMATION":
                                if fields[2] == "BugCheck":
                                    wecare = True
                            if wecare:
                                # Build up a string for thingsWeHaveReported
                                twhr = "%s,%s,%s" % (fields[1],fields[2],
                                                     fields[5])
                                if not twhr in place.thingsWeHaveReported:
                                    place.thingsWeHaveReported.append(twhr)
                                    tag = ""
                                    for x in log_error_strings.keys():
                                        if x.search(fields[8]):
                                            tag = log_error_strings[x] + " "
                                            break
                                    if "IGNORE" in tag:
                                        continue
                                    xenrt.TEC().warning(\
                                        "%sError in Windows %s log (%s): %s" % 
                                        (tag, log, fields[2], fields[8]))
                except:
                    pass
            # Check for crash dumps.
            if place.xmlrpcBigdump(ignoreHealthCheck=True):
                if not "bigdump" in place.thingsWeHaveReported:
                    place.thingsWeHaveReported.append("bigdump")
                    xenrt.TEC().warning("Found big memory dump.")
                    if xenrt.TEC().lookup("PAUSE_ON_FULL_DUMP", False, 
                                          boolean=True):
                        xenrt.TEC().tc.pause("Full dump available on %s" % 
                                             (place.name))
            for dump in place.xmlrpcMinidumps(ignoreHealthCheck=True):
                if not dump in place.thingsWeHaveReported:
                    place.xmlrpcGetFile(dump, "%s/%s" % 
                                       (d, re.sub(".*\\\\", "", dump)))
                    place.thingsWeHaveReported.append(dump)
            return
        paths = []
        paths.extend(STANDARD_LOGS)
        if place.extraLogsToFetch:
            paths.extend(place.extraLogsToFetch)
        if self.getResult(code=True) != RESULT_PASS:
            paths.extend(STANDARD_LOGS_NON_PASS)
        if extraPaths:
            paths.extend(extraPaths)
        if place.logFetchExclude:
            for lf in place.logFetchExclude:
                if lf in paths:
                    paths.remove(lf)
        cmds = filter(lambda x: x[0] == "!", paths)
        actualpaths = filter(lambda x: x not in cmds, paths)
        if not xenrt.TEC().lookup("QUICKLOGS", False, boolean=True):
            try:
                sftp = place.sftpClient()
                xenrt.TEC().logverbose("Trying to fetch %s." % (actualpaths))
                sftp.copyLogsFrom(actualpaths, d)
            except Exception, e:
                traceback.print_exc(file=sys.stderr)
                xenrt.TEC().logverbose("Exception fetching logs from %s: %s" %
                                       (place.getName(), str(e)))
            for c in cmds:
                try:
                    outfile = re.sub("\s", "_", c.lstrip("!").split("/")[-1])
                    out = place.execcmd(c.lstrip("!"))
                    f = open("%s/%s.out" % (d, outfile), "w")
                    f.write(out)
                    f.close()
                except Exception, e:
                    xenrt.TEC().logverbose("Exception running %s on %s: %s" %
                                           (c, place.getName(), str(e)))
            # parse logs for errors
            for log in ["messages", "xensource.log", "SMlog", "xha.log", "daemon.log", "kern.log", "user.log"]:
                try:
                    # See if it's there
                    if os.path.exists("%s/%s" % (d,log)):
                        f = file("%s/%s" % (d,log),"r")
                        lines = f.read().split("\n")
                        f.close()
                        for line in lines:
                            if "Kernel panic" in line:
                                if not line in place.thingsWeHaveReported:
                                    place.thingsWeHaveReported.append(line)
                                    self._warnWithPrefix("Kernel panic in %s: %s" %
                                                         (log,line))
                            if "Oops" in line:
                                if not line in place.thingsWeHaveReported:
                                    place.thingsWeHaveReported.append(line)
                                    self._warnWithPrefix("Oops in %s: %s" %
                                                         (log,line))
                            if "OOMKiller" in line:
                                if not line in place.thingsWeHaveReported:
                                    place.thingsWeHaveReported.append(line)
                                    self._warnWithPrefix("OOMKiller in %s: %s" %
                                                         (log,line))
                            # blktap checks
                            if "blk_tap:" in line or "TAPDISK ERROR:" in line or \
                               "NOTE: Couldn't find footer"\
                               " at the end of the VHD image" in line:
                                if not line in place.thingsWeHaveReported:
                                    place.thingsWeHaveReported.append(line)
                                    self._warnWithPrefix(line)
                            if "unmap_disk" in line:
                                m = re.match(".*unmap_disk: (\d+) retries.*",line)
                                if (m and int(m.group(1)) >= 250) or (not m):
                                    if not line in place.thingsWeHaveReported:
                                        place.thingsWeHaveReported.append(line)
                                        self._warnWithPrefix(line)

                            # HVMXEN checks
                            if re.match(".*HVMXEN-.*\[WARNING \]",line) or \
                               re.match(".*HVMXEN-.*\[ ERROR  \]",line):
                                if not line in place.thingsWeHaveReported:
                                    place.thingsWeHaveReported.append(line)
                                    self._warnWithPrefix(line)

                            # Checks for ssmith
                            if re.match("rate limiting domain (.*)'s access to the"
                                        " store",line) or \
                              "throttling guest access to syslog" in line:
                                if not line in place.thingsWeHaveReported:
                                    place.thingsWeHaveReported.append(line)
                                    self._warnWithPrefix(line)

                            # xha checks
                            if "Xapi healthchecker has reported an error" in line:
                                if not line in place.thingsWeHaveReported:
                                    place.thingsWeHaveReported.append(line)
                                    self._warnWithPrefix(line)

                            # SMlog checks
                            if "*  E X C E P T I O N  *" in line:
                                if not line in place.thingsWeHaveReported:
                                    place.thingsWeHaveReported.append(line)
                                    self._warnWithPrefix(line)
                                    
                            # deamon.log
                            if "RINGWATCH-ALERT" in line:
                                if not line in place.thingsWeHaveReported:
                                    place.thingsWeHaveReported.append(line)
                                    self._warnWithPrefix("RINGWATCH-ALERT in %s: %s" % (log,line))
                                    
                            if "segfault" in line:
                                if not line in place.thingsWeHaveReported:
                                    place.thingsWeHaveReported.append(line)
                                    self._warnWithPrefix("segfault in %s: %s" % (log,line))
                            
                            if "oom-killer" in line:
                                if not line in place.thingsWeHaveReported:
                                    place.thingsWeHaveReported.append(line)
                                    self._warnWithPrefix("oom-killer in %s: %s" % (log,line))
                            
                            if "Out of memory" in line:
                                if not line in place.thingsWeHaveReported:
                                    place.thingsWeHaveReported.append(line)
                                    self._warnWithPrefix("Out of memory in %s: %s" % (log,line))

                            if "crashed too quickly after start" in line:
                                if not line in place.thingsWeHaveReported:
                                    place.thingsWeHaveReported.append(line)
                                    self._warnWithPrefix("crashed too quickly after start in %s: %s" % (log,line))

                except:
                    pass
            if place.guestconsolelogs:
                if self._started:
                    threshold = self._started - 600
                else:
                    threshold = None
                sizethresh = 2097152
                try:
                    fn = xenrt.TEC().tempFile()
                    place.execcmd("%s/get_console_logs %s %s %s" % 
                                  (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"),
                                   place.guestconsolelogs,threshold,sizethresh),
                                  nolog=True,outfile=fn)
                    if os.stat(fn).st_size > 0:
                        os.system("mkdir -p %s/guest-console-logs" % (d))
                        os.system("cd %s/guest-console-logs && tar -xf %s" % (d,fn))
                except Exception, e:
                    self.tec.warning("Error running get_console_logs: %s" % (str(e)))

        # If we've got it, run xen-bugtool.
        if not xenrt.TEC().lookup("OPTION_NO_BUGTOOL", False, boolean=True) and \
               not (xenrt.TEC().lookup("QUICK_LOGS_ON_PASS", False, boolean=True) and \
                    self.getResult(code=True) == RESULT_PASS):
            if 'getBugTool' in dir(place):
                try:
                    lock = xenrt.resources.CentralResource(timeout=1200)
                    for i in range(10):
                        try:
                            xenrt.TEC().logverbose("Trying to acquire "
                                                   "BUGTOOL-%s." % 
                                                   (place.getName()))
                            lock.acquire("BUGTOOL-%s" % (place.getName()))
                            break
                        except:
                            xenrt.sleep(60)
                            if i == 9:
                                self.tec.warning("Couldn't get bugtool lock.")
                            else:
                                self.tec.logverbose("Waiting for bugtool lock.")
                    try:
                        place.getBugTool(bugdir=d)
                    except Exception, e:
                        self.tec.warning("Error running xen-bugtool: %s" % 
                                         (str(e)))
                finally:
                    lock.release()
        try:
            if isinstance(place, xenrt.GenericHost):
                diskusedpercent = int(place.execcmd("df / | awk '{print $5}' | grep -v Use | tr -d '%'"))
                if diskusedpercent > 90:
                    self.tec.warning("Disk use %d%% on %s" % (diskusedpercent, place.getName()))
                    place.execcmd("du -hax /")
        except:
            pass
        # Look for any crash dumps
        try:
            if isinstance(place, xenrt.GenericHost):
                crashdumps = string.split(place.execcmd("ls /var/crash"))
            else:
                crashdumps = []
            for cd in crashdumps:
                if cd == "scripts":
                    continue
                cdr = "crashdump:%s" % (cd)
                if place.skipNextCrashdump and not cdr in place.thingsWeHaveReported:
                    self.tec.warning("Ignoring crashdump %s" % (cdr))
                    place.skipNextCrashdump = False
                    place.thingsWeHaveReported.append(cdr)
                elif not cdr in place.thingsWeHaveReported:
                    place.thingsWeHaveReported.append(cdr)
                    self.tec.warning("Crash dump %s found" % (cd))
                    try:
                        cdd = "%s/crash-%s" % (d, cd)
                        if not os.path.exists(cdd):
                            os.mkdir(cdd)
                        sftp.copyTreeFrom("/var/crash/%s" % (cd), cdd)
                    except:
                        pass
                    # File a ticket for the crashdump
                    if self.tec.lookup("AUTO_BUG_FILE", False, boolean=True):
                        try:
                            jl = xenrt.jiralink.getJiraLink()
                            cdticket = jl.fileCrashDump(cd,"%s/crash-%s" % 
                                                           (d,cd), place)
                            self._crashdumpTickets.append(cdticket)
                        except Exception, e:
                            self.tec.warning("JiraLink Exception while filing crashdump ticket: %s" % (str(e)))
                            xenrt.TEC().logverbose(traceback.format_exc())

        except:
            pass
        # Look for any core files.
        try:
            for l in ["/core*", "/root/core*"]:
                try:
                    corefiles = string.split(place.execcmd("ls %s" % (l)))
                    for cf in corefiles:
                        cfr = "corefile:%s" % (cf)
                        if not cfr in place.thingsWeHaveReported:
                            place.thingsWeHaveReported.append(cfr)
                            xenrt.TEC().warning("Core file %s found." % (cf))
                            try:
                                cfd = "%s/core" % (d)
                                if not os.path.exists(cfd):
                                    os.mkdir(cfd)
                                sftp.copyFrom(cf, 
                                             "%s/%s" % 
                                             (cfd, os.path.basename(cf)))
                            except:
                                pass
                except:
                    pass
        except:
            pass
        # Look for any xentraces
        try:
            traces = string.split(place.execcmd("ls /tmp/xenrt-xentrace/"))
            for t in traces:
                tr = "xentrace:%s" % (t)
                if not tr in place.thingsWeHaveReported:
                    place.thingsWeHaveReported.append(tr)
                    xenrt.TEC().warning("Crash trace %s found." % (t))
                    try:
                        sftp.copyFrom("/tmp/xenrt-xentrace/%s" % (t),d)
                    except:
                        pass
        except:
            pass
        try:
            place.getExtraLogs(d)
        except:
            pass
        # If this is a dom0 with VNC output available, take some snapshots
        if not xenrt.TEC().lookup("QUICKLOGS", False, boolean=True) and \
           not (xenrt.TEC().lookup("QUICK_LOGS_ON_PASS", False, boolean=True) and \
                self.getResult(code=True) == RESULT_PASS):
            try:
                vncsnapshot = None
                if place.execcmd("test -e /usr/lib64/xen/bin/vncsnapshot",
                                 retval="code") == 0:
                    vncsnapshot = "/usr/lib64/xen/bin/vncsnapshot"
                if place.execcmd("test -e /usr/lib/xen/bin/vncsnapshot",
                                 retval="code") == 0:
                    vncsnapshot = "/usr/lib/xen/bin/vncsnapshot"
                if place.execcmd("test -e /usr/bin/vncsnapshot",
                                 retval="code") == 0:
                    vncsnapshot = "/usr/bin/vncsnapshot"
                if vncsnapshot:
                    rdir = string.strip(place.execcmd("mktemp -d "
                                                      "/tmp/distXXXXXX"))
                    place.execcmd("chmod 755 %s" % (rdir))
                    listeners = string.split(place.execcmd(\
                        "netstat -ltn | awk '{print $4}'"))
                    domids = {}
                    domnames = {}
                    vncdisplays = "%s/utils/vncdisplays" % \
                                  (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"))
                    if place.execcmd("test -e %s" % (vncdisplays),
                                     retval="code") == 0:
                        try:
                            map = place.execcmd(vncdisplays)
                            for line in string.split(map, "\n"):
                                l = string.split(line)
                                if len(l) == 2:
                                    domids[int(l[1])] = l[0]
                        except:
                            pass
                        try:
                            if isinstance(place, xenrt.GenericHost):
                                map = place.listDomains()
                                for domname in map.keys():
                                    domnames[str(map[domname][0])] = domname
                        except:
                            pass
                    for l in listeners:
                        try:
                            r = re.search(":(59\d\d)", l)
                            if r:
                                display = int(r.group(1)) - 5900
                                if display == 0 and \
                                        place.special.has_key(\
                                            'no vncsnapshot on :0'):
                                    continue
                                if domids.has_key(display):
                                    if domnames.has_key(domids[display]):
                                        domname = domnames[domids[display]]
                                        filename = "display-%u_domid-%s_%s" \
                                                   ".jpg" % \
                                                   (display,
                                                    domids[display],
                                                    domname)
                                    else:
                                        filename = "display-%u_domid-%s.jpg" \
                                                   % (display, domids[display])
                                else:
                                    filename = "display-%u.jpg" % (display)
                                try:
                                    # Send shift to wake up any screensaver running
                                    place.sendVncKeys(":%u" % (display), [0xffe1])
                                    xenrt.sleep(1)
                                    
                                    # Send WindowsKey+R to show desktop on Win 8+
                                    place.sendVncKeys(":%u" % (display), ["0x72/0xffeb"])
                                    xenrt.sleep(3)
                                except:
                                    pass
                                place.execcmd("%s -compresslevel 9 -quality 25"
                                              " -allowblank :%u  %s/%s" %
                                              (vncsnapshot,
                                               display,
                                               rdir,
                                               filename))
                        except Exception, e:
                            traceback.print_exc(file=sys.stderr)
                    vncd = "%s/vnc" % (d)
                    if not os.path.exists(vncd):
                        os.mkdir(vncd)
                    sftp.copyTreeFrom(rdir, vncd)
                    place.execcmd("rm -rf %s" % (rdir))
            except:
                pass

        # If we've got it, try and capture some HA debug output
        try:
            if place.execcmd("test -e /opt/xensource/xha/ha_query_liveset",
                             retval="code") == 0:
                if place.execcmd("PATH=$PATH:/opt/xensource/xha "
                                 "/opt/xensource/xha/ha_query_liveset > "
                                 "/tmp/ha_liveset.xml", retval="code") == 0:
                    sftp.copyFrom("/tmp/ha_liveset.xml","%s/ha_liveset.xml" % (d))
            if place.execcmd("test -e /opt/xensource/xha/dumpstatefile",
                             retval="code") == 0:
                if place.execcmd("/opt/xensource/xha/dumpstatefile "
                                 "/etc/xensource/xhad.conf > "
                                 "/tmp/ha_statefile.txt", retval="code") == 0:
                    sftp.copyFrom("/tmp/ha_statefile.txt", "%s/ha_statefile.txt" % (d))
        except:
            pass

        sftp.close()

    def getLogObjName(self, obj):
        if isinstance(obj, xenrt.GenericPlace): 
            return obj.getName()
        elif isinstance(obj, xenrt.lib.generic.Instance):
            return obj.name
        elif xenrt.interfaces.Toolstack in providedBy(obj):
            return obj.name

    def _getRemoteLogs(self):
        """Fetch logs from all hosts and guests registered for log collection.
        """
        if xenrt.TEC().lookup("NOLOGS", False, boolean=True):
            return
        xenrt.TEC().logverbose("Getting logs from %s." % 
                              ([self.getLogObjName(x) for x in self.logsfrom.keys()]))
        for h in self.logsfrom.keys():
            paths = self.logsfrom[h]
            try:
                self._getRemoteLogsFrom(h, paths)
            except Exception, e:
                traceback.print_exc(file=sys.stderr)
        if self.runon and not self.logsfrom.has_key(self.runon):
            try:
                self._getRemoteLogsFrom(self.runon)
            except:
                pass
        xenrt.TEC().logverbose("Collecting controller information")
        try:
            self.getControllerInfo()
        except:
            pass

    def getControllerInfo(self):
        """Retrieve local information on XenRT controller"""
        d = xenrt.TEC().getLogdir()
        xenrt.command("/bin/ps wwwaxf -eo pid,tty,stat,time,nice,psr,pcpu,pmem,nwchan,wchan:25,args > %s/xenrt-process-tree.txt" % (d))
        xenrt.command("TERM=linux /usr/bin/top -b -n 1 > %s/xenrt-top.txt" % (d))
        xenrt.command("/usr/sbin/arp -n > %s/xenrt-arp.txt" % (d))

    def getLogsFrom(self, obj, paths=None):
        """Register a host or guest for log collection.

        @param obj: an object to fetch from
        @param paths: a list of extra paths for log files to capture
        """
        if not isinstance(obj, xenrt.GenericPlace) \
          and not isinstance(obj, xenrt.lib.generic.Instance) \
          and not xenrt.interfaces.Toolstack in providedBy(obj): 
            raise xenrt.XRTError("Only objects extending GenericPlace, Instance or Toolstack can be registered for log collection")

        if self.logsfrom.has_key(obj):
            # Already tracked, only add paths if we have them
            if paths:
                if not self.logsfrom[obj]:
                    self.logsfrom[obj] = []
                self.logsfrom[obj].extend(paths)
        else:
            self.logsfrom[obj] = paths
        if isinstance(obj, xenrt.lib.xenserver.Host):
            if obj.pool:
                for slave in obj.pool.slaves.values():
                    if not slave == obj:
                        self.logsfrom[slave] = paths
                if not obj.pool.master == obj:
                    self.logsfrom[obj.pool.master] = paths
        if isinstance(obj, xenrt.GenericHost) and obj.machine and not xenrt.TEC().lookup("NO_TC_HOST_SERIAL_LOGS", False, boolean=True):
            # Capture host console logs. We'll close the file handle when
            # the testcase completes - the console logger will notice this
            # and stop writing to it
            d = xenrt.TEC().getLogdir()
            fn = "%s/host-serial-log-%s-from-%s.txt" % \
                 (d,
                  obj.getName(),
                  time.strftime("%Y%m%d-%H%M%S", time.gmtime()))
            fh = file(fn, "w")
            obj.machine.addConsoleLogWriter(fh)
            self._fhsToClose.append(fh)
        
    def remoteLoggingDirectory(self, place):
        """Create a directory on a place for logs.
        This will be added to the list of paths fetched on completion.

        @param place: an instance of L{GenericPlace} to create the directory on
        """
        d = place.tempDir()
        xenrt.TEC().logverbose("Creating directory %s on %s for extra logging"
                               % (d, place))
        self.getLogsFrom(place, [d])
        return d

    def _cleanup(self):
        """Perform any harness cleanup actions after a testcase has completed.

        This is different from the per-testcase postRun() method. This method
        is for harness state cleanup.
        """
        self.tec.close()

    def isSkipped(self):
        """Return True is this testcase has been skipped."""
        return self.getOverallResult() == RESULT_SKIPPED

    def isPass(self):
        """Return True if this testcase passed."""
        return self.getOverallResult() == RESULT_PASS or \
            self.getOverallResult() == RESULT_PARTIAL

    def isFail(self):
        """Return True if this testcase failed."""
        return self.getOverallResult() == RESULT_FAIL

    def isError(self):
        """Return True if this testcase generated an harness error."""
        return self.getOverallResult() == RESULT_ERROR

    def isBlocker(self):
        """Return True if this testcase is a blocking testcase."""
        return self.blocker

    #########################################################################
    # Execution location handling

    # Method to get host and guest objects - this is so we can log
    # what's been used so we can get logs later
    def getGuest(self, name):
        """Get a guest object by name. Registers the guest for log fetching."""
        g = self.tec.gec.registry.guestGet(name)
        if g:
            self.getLogsFrom(g)
            if g.host and not g.host.getName() in xenrt.TEC().lookup("SHARED_HOSTS", {}).keys():
                self.getLogsFrom(g.host)
        return g

    def getHost(self, name):
        """Get a host object by name. Registers the host for log fetching."""
        h = self.tec.gec.registry.hostGet(name)
        if h:
            self.getLogsFrom(h)
        return h    

    def getAllHosts(self):
        """Gets a list of all hosts"""
        hosts = []
        for h in self.tec.gec.registry.hostList():
            hosts.append(self.tec.gec.registry.hostGet(h))
            
        return hosts
    
    def getDefaultHost(self):
        """Get the host object of the first/only host."""
        if self._host:
            return self.getHost(self._host)
        else:
            self._host = "RESOURCE_HOST_DEFAULT"
            return self.getHost("RESOURCE_HOST_DEFAULT")

    def getDefaultToolstack(self):
        t = self.tec.gec.registry.toolstackGetDefault()
        if t:
            self.getLogsFrom(t)
        return t

    def getToolstack(self, name):
        t = self.tec.gec.registry.toolstackGet(name)
        if t:
            self.getLogsFrom(t)
        return t

    def getInstance(self, name):
        i = self.tec.gec.registry.instanceGet(name)
        if i:
            self.getLogsFrom(i)
        return i

    def getPool(self, name):
        """Get a pool object by name. Registers the hosts for log fetching."""
        p = self.tec.gec.registry.poolGet(name)
        if p:
            self.getLogsFrom(p.master)
            for slave in p.slaves.values():
                self.getLogsFrom(slave)
        return p

    def getDefaultPool(self):
        """Get the pool object of the first/only pool."""
        return self.getPool("RESOURCE_POOL_0")

    def getLocation(self):
        """Get the guest or host object for where we want to run this test.

        This is based on guest= or host= arguments from the sequence file or
        --guest or --host arguments to the command line in single-testcase
        mode.
        """
        if self.runon:
            return self.runon
        elif self._guest:
            return self.getGuest(self._guest)
        elif self._host:
            return self.getHost(self._host)
        raise xenrt.XRTError("No host or guest specified")

    #########################################################################
    # Performance database

    def perfValue(self, metric, value, units=None):
        """Record a performance result.

        @param metric: string name of a metric
        @param value: numeric result
        @param units: optional string name for units of the value
        """
        self.results.perfdata.append((metric, value, units))

    #########################################################################
    # Utility methods

    def runAsync(self, runon, commands, timeout=3600, ignoreSSHErrors=False):
        """Run a command(s) on the specified location asynchronously.

        Creates a shell script on the specified location to run the
        commands supplied. Polls for completion of the script.

        This method does nothing to check for error returns. It will
        raise an error exception if the commands are still running after
        the timeout period.

        This method uses SSH.

        @param runon: an instance of L{GenericPlace} to execute on
        @param commands: string, or list of strings, to execute
        @param timeout: timeout in seconds
        @param ignoreSSHErrors: if true treat SSH errors as the script still running
        """

        runon.execcmd("mkdir -p %s" % xenrt.TEC().lookup("LOCAL_BASE"))
        flagfile = string.strip(runon.execcmd("mktemp %s/flagXXXXXX" % xenrt.TEC().lookup("LOCAL_BASE")))
        scriptfile = string.strip(runon.execcmd("mktemp %s/scriptXXXXXX" % xenrt.TEC().lookup("LOCAL_BASE")))
        logfile = string.strip(runon.execcmd("mktemp %s/logXXXXXX" % xenrt.TEC().lookup("LOCAL_BASE")))
        ecfile = string.strip(runon.execcmd("mktemp %s/ecXXXXXX" % xenrt.TEC().lookup("LOCAL_BASE")))
        if type(commands) == type(""):
            c = commands
        else:
            c = string.join(commands, "\n")
        script = """#!/bin/bash
%s
echo $? > %s
rm -f %s
""" % (c, ecfile, flagfile)
        scrf = xenrt.TEC().tempFile()
        f = file(scrf, "w")
        f.write(script)
        f.close()
        xenrt.TEC().logverbose("Remote script %s contents: %s" %
                               (scriptfile, script))
        sftp = runon.sftpClient()
        sftp.copyTo(scrf, scriptfile)
        runon.execcmd("%s > %s 2>&1 < /dev/null &" % (scriptfile, logfile))
        now = xenrt.util.timenow()
        deadline = now + timeout
        xenrt.TEC().logverbose("Waiting for remote script to complete")
        try:
            while True:
                try:
                    if runon.execcmd("test -e %s" % (flagfile),
                                     retval="code") != 0:
                        break
                except Exception, e:
                    if ignoreSSHErrors:
                        # Treat this exception as if the script is still
                        # running. This is probably because the target
                        # is expected to become temporarily unreachable
                        # during execution.
                        xenrt.TEC().logverbose("Ignoring runAsync SSH "
                                               "exception: %s" % (str(e)))
                    else:
                        raise e.__class__, e, sys.exc_info()[2]
                now = xenrt.util.timenow()
                if now > deadline:
                    raise xenrt.XRTError("Remote script timed out")
                xenrt.sleep(60)
        finally:
            ec = 0
            try:
                ec = int(runon.execcmd("cat %s" % (ecfile)).strip())
                xenrt.TEC().logverbose("Remote command returned: %d" % (ec))
                locallogfile = xenrt.TEC().logFile()
                sftp.copyFrom(logfile, locallogfile)
                sftp.close()
            except:
                pass
            if not ec == 0:
                raise xenrt.XRTFailure("Remote command exited with non-zero "
                                       "value.")

    def startAsync(self, runon, commands):
        flagfile = string.strip(runon.execcmd("mktemp /tmp/flagXXXXXX"))
        scriptfile = string.strip(runon.execcmd("mktemp /tmp/scriptXXXXXX"))
        logfile = string.strip(runon.execcmd("mktemp /tmp/logXXXXXX"))
        ecfile = string.strip(runon.execcmd("mktemp /tmp/ecXXXXXX"))
        if type(commands) == type(""):
            c = commands
        else:
            c = string.join(commands, "\n")
        script = """#!/bin/bash
%s
echo $? > %s
rm -f %s
""" % (c, ecfile, flagfile)
        scrf = xenrt.TEC().tempFile()
        f = file(scrf, "w")
        f.write(script)
        f.close()
        sftp = runon.sftpClient()
        try:
            sftp.copyTo(scrf, scriptfile)
        finally:
            sftp.close()
        runon.execcmd("%s > %s 2>&1 < /dev/null &" % (scriptfile, logfile))
        return (runon, flagfile, ecfile, logfile)

    def pollAsync(self, handle):
        runon, flagfile, ecfile, logfile = handle
        if runon.execcmd("test -e %s" % (flagfile), retval="code") == 0:
            return False
        return True

    def completeAsync(self, handle):
        runon, flagfile, ecfile, logfile = handle
        ec = 0
        try:
            ec = int(runon.execcmd("cat %s" % (ecfile)).strip())
            xenrt.TEC().logverbose("Remote command returned: %d" % (ec))
            try:
                locallogfile = xenrt.TEC().logFile()
            except: 
                locallogfile = xenrt.TEC().tempFile()
            sftp = runon.sftpClient()
            try:
                sftp.copyFrom(logfile, locallogfile)
            finally:
                sftp.close()
        except:
            pass
        if not ec == 0:
            raise xenrt.XRTFailure("Remote command exited with non-zero value.")
        f = file(locallogfile, 'r')
        data = f.read()
        f.close()
        return data

    def uninstallOnCleanup(self, guest):
        """Register a guest object for uninstallation on testcase cleanup."""
        self._guestsToUninstall.append(guest)

    def removeTemplateOnCleanup(self, host, template):
        """Register a template UUID for removal on testcase cleanup"""
        self._templatesToRemove.append((host, template))

    def parseArgsKeyValue(self, arglist):
        kv = {}
        if arglist:
            for a in arglist:
                aa = a.split("=", 1)
                if len(aa) == 1:
                    kv[aa[0]] = None
                else:
                    kv[aa[0]] = aa[1]
        return kv

    def ticketAttachments(self):
        return []

    def getSubCaseTicketDescription(self):
        return None

    def ticketAssignee(self):
        return None

class TCAnon(TestCase):
    """The "anonymous testcase".

    This is used for a context for operations performed outside of individual
    testcases.
    """
    def __init__(self, tcid="TCAnon"):
        TestCase.__init__(self, tcid, anon=True)
        # Workaround the fact that tcid is normally the GlobalExecutionContext, which can
        # break some aspects of Jira integration
        self.basename = "TCAnon"

class JobTest(object):
    """Base class for a job level testcase"""
    TCID = None
    FAIL_MSG = "Job level test failed"

    def __init__(self, host):
        self.host = host

    def preJob(self):
        pass

    def postJob(self):
        raise xenrt.XRTError("Unimplemented")

class TestExecutionContext(object):
    """Dynamic context associated with the execution of a testcase."""
    def __init__(self, gec, tc, anon=False):
        """Constructor.

        @param gec: the L{GlobalExecutionContext}
        @param tc: the testcase instance we're executing
        @param anon: set to C{True} to create the anonymous testcase context
        """
        self.logfile = None
        
        # The test case we're executing
        self.tc = tc

        # Record our thread name.
        self._my_thread_name = threading.currentThread().getName()

        # The global execution context
        self.gec = gec
        self.registry = gec.registry
        self.config = gec.config

        # If we're the anonymous execution context, register as such
        if anon:
            global _anontec
            _anontec = self

        # Create us a local working directory and log directory
        self.workdir = xenrt.resources.WorkingDirectory()
        if not self.config.nologging:
            self.logdir = xenrt.resources.LogDirectory()
            self.logverbose("Dirs for %s: working %s, log %s" %
                            (tc.tcid, self.workdir.dir, self.logdir.dir))
        else:
            self.logdir = None
            self.logverbose("Dirs for %s: working %s, log (none)" %
                            (tc.tcid, self.workdir.dir))

        # Open a log file for command output if relevant
        if not self.config.nologging:
            self.logfilename = "%s/xenrt.log" % (self.logdir.path())
            self.logfile = file(self.logfilename, "w")

    #########################################################################
    # Log and working directories and files

    def close(self):
        """Close log files associated with this context."""
        if self.logfile:
            self.logfile.close()
            self.logfile = None
        if self.workdir:
            self.workdir.remove()
            self.workdir = None
        if self.logdir:
            self.logdir.remove()
            self.logdir = None

    def getWorkdir(self):
        """Return the path to the working directory for this context."""
        if not self.workdir:
            return None
        return self.workdir.dir

    def getLogdir(self):
        """Return the path to the log directory for this context."""
        if not self.logdir:
            return None
        return self.logdir.dir

    def flushLogs(self):
        """Flush log files associated with this context."""
        if self.logfile:
            self.logfile.flush()

    def readLogs(self):
        """Read logs for this context into a buffer."""
        if self.logfile and self.logfilename:
            self.logfile.flush()
            f = file(self.logfilename, "r")
            data = f.read()
            f.close()
            return data
        return "No log data available"

    def readLogTail(self, lines=100):
        """Read the tail of the logs for this context into a buffer."""
        if self.logfile and self.logfilename:
            self.logfile.flush()
            data = os.popen("tail -n %u %s" % (lines, self.logfilename)).read()
            data = re.sub(r"[\x80-\xff]", "", data)
            return data
        return "No log data available"

    def tempFile(self):
        """Create a local temporary file within the context working directory.
        """
        f, filename = tempfile.mkstemp("", "xenrt", self.workdir.dir)
        os.close(f)
        os.chmod(filename,
                 stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)
        return filename

    def logFile(self):
        """Create a log file within the context log directory."""
        f, filename = tempfile.mkstemp("", "log", self.logdir.dir)
        os.close(f)
        os.chmod(filename,
                 stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)
        return filename

    def tempDir(self):
        """Create a local temporary directory within the context working
directory.
"""
        dir = tempfile.mkdtemp("", "xenrt", self.workdir.dir)
        os.chmod(dir,
                 stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)
        return dir

    def log(self, data):
        """Log string data to the context main log file (xenrt.log)."""
        if self.logfile:
            # If the calling thread isn't the one that created this TEC
            # then prefix the data with the thread name. This is to help
            # in picking apart multiplexed logs from parallel operations.
            thrd = threading.currentThread()
            tname = thrd.getName()
            if tname != self._my_thread_name:
                if isinstance(thrd, xenrt.XRTThread) and thrd.lookup('nolog'):
                    return
                lines = []
                for line in data.splitlines():
                    lines.append("[%s] %s\n" % (tname, line))
                data = string.join(lines, "")
            
            try:
                self.logfile.write(data)
            except UnicodeEncodeError:
                self.logfile.write(data.encode("utf-8"))

    def logException(self, exc):
        """Log an exception backtrace to the context main log file (xenrt.log).
        """
        if self.logfile:
            traceback.print_exc(file=self.logfile)

    def copyToLogDir(self, f, target=None):
        """Copy a file to the context log directory.

        By default the basename of the source file is used as the name in the
        log directory. This can be overriden by specifying a new basename
        using the target argument.
        """
        if self.logdir:
            self.logdir.copyIn(f, target=target)

    def progress(self, str):
        """Record progress through a test case."""
        self.log(self.gec.progress(str, self.tc.tcid))

    def reason(self, str):
        """Log a reason for failure."""
        self.tc.results.reason(str)
        self.log(self.gec.logverbose(str, pref='REASON'))

    def comment(self, str):
        """Log a comment about this test execution."""
        self.tc.results.comment(str)
        self.log(self.gec.logverbose(str, pref='COMMENT'))

    def appresult(self, str):
        """Log an application specific result from this test execution."""
        self.tc.results.appresult(str)
        self.log(self.gec.logverbose(str, pref='RESULT'))

    def warning(self, str):
        """Log a warning about this test execution."""
        self.tc.results.warning(str)
        self.log(self.gec.logverbose(str, pref='WARNING'))

    def value(self, param, value, units=None):
        """Record a numeric value."""
        self.tc.perfValue(param, value, units)
        self.logverbose("Value set %s = %s" % (str(param), str(value)))
        if self.tc:
            if self.tc.group:
                g = self.tc.group
            else:
                g = "DEFAULT"
        xenrt.GEC().checkPerfValue(g, self.tc.basename, param, value)

    def getData(self):
        """Return a list of (key, value) pairs suitable for a database
logdata call."""
        reply = []
        for i in self.tc.results.reasons:
            reply.append(("reason", i))
        for i in self.tc.results.comments:
            reply.append(("comment", i))
        for i in self.tc.results.appresults:
            reply.append(("data", i))
        for i in self.tc.results.warnings:
            reply.append(("warning", i))
        for i in self.tc.results.perfdata:
            p, v, u = i
            reply.append(("V:%s" % (str(p)), str(v)))
        return reply

    def logerror(self, str):
        """Log an error encountered during test execution."""
        self.log(self.gec.logverbose(str, pref='ERROR'))
        
    def logverbose(self, str, pref='VERBOSE'):
        """Log a verbose message during test execution."""
        self.log(self.gec.logverbose(str, pref=pref))

    def logdelimit(self, tag='unnamed'):
        """Insert a break into the log file to improve readability."""
        for line in ["**", "**", "** New log section: %s" % (tag), "**", "**"]:
            self.log(self.gec.logverbose(line, pref="DELIMIT"))

    #########################################################################
    # Configuration interface

    def writeOutConfig(self, fd):
        """Write the global config out to a file descriptor."""
        self.gec.config.writeOut(fd)

    def getAllConfig(self):
        """Return the entire global configuration (non-recursive).

        Returns a multiline string of key='value' pairs.
        """
        return self.gec.config.getAll()

    def defined(self, var):
        """Returns True if the specified variable is defined."""
        return self.gec.config.defined(var)

    def lookup(self, var, default=XRTError, boolean=False):
        """Look up the specified variable.

        @param var: the variable to look up
        @param default: default value to use if the variable is not defined,
            if not specifed causes an error exception to be raised
        @param boolean: treat the value as a boolean and return C{True} or
            C{False}
        """
        return self.gec.config.lookup(var, default=default, boolean=boolean)

    def lookupLeaves(self, var):
        """Return a list of leaf values from the variable tree.

        @param var: the variable root to look up
        """
        return self.gec.config.lookupLeaves(var)

    def lookupHost(self, hostname, var, default=XRTError, boolean=False):
        """Look up the specified (per-host) variable.

        If a per-host variable is defined use that, otherwise fall back
        to a global and then the specific default (if supplied).

        @param hostname: name of the host
        @param var: the variable to look up
        @param default: default value to use if the variable is not defined,
            if not specifed causes an error exception to be raised
        @param boolean: treat the value as a boolean and return C{True} or
            C{False}
        """
        return self.gec.config.lookupHost(hostname, var, default=default,
                                          boolean=boolean)

    def lookupHostAndVersion(self, hostname, ver, var, default=XRTError,
                             boolean=False):
        """Look up the specified (per-host and per-version) variable.

        If a per-host variable is defined use that, otherwise if a
        per-product-version variable is defined use that, otherwise fall
        back to a global and then the specific default (if supplied).

        @param hostname: name of the host
        @param ver: the product version
        @param var: the variable to look up
        @param default: default value to use if the variable is not defined,
            if not specifed causes an error exception to be raised
        @param boolean:  treat the value as a boolean and return C{True} or
            C{False}
        """
        return self.gec.config.lookupHostAndVersion(hostname,
                                                    ver,
                                                    var,
                                                    default=default,
                                                    boolean=boolean)

    def setThreadLocalVariable(self, var, value, fallbackToGlobal=False):
        """Set a thread local variable."""
        t = myThread()
        if not t:
            if fallbackToGlobal:
                self.gec.config.setVariable(var, value)
            else:
                raise xenrt.XRTError("Cannot find a thread object to set ",
                                     "variable %s=%s in thread %s" %
                                     (var,
                                      value,
                                      threading.currentThread().getName()))
        else:
            t.setVariable(var, value)
        
    def skip(self, str=None):
        """Cause the test to be marked as skipped.

        This method records the data and returns. It is up to the caller to
        exit the testcase run() method.

        @param str: (optional) a reason for skipping
        """
        if str:
            self.reason(str)
        if self.tc:
            self.tc.setResult(RESULT_SKIPPED)

    def getFile(self, *filename, **kwargs):
        """Look up a name with the file manager."""
        if not self.gec.filemanager:
            raise XRTError("No filemanager object")
        replaceExistingIfDiffers = kwargs.get("replaceExistingIfDiffers", False)
        ret = None
        for f in filename:
            ret = self.gec.filemanager.getFile(f, replaceExistingIfDiffers=replaceExistingIfDiffers)
            if ret:
                break
        return ret
        
    def getFiles(self, *filename):
        """Look up a selection of names with the file manager."""
        if not self.gec.filemanager:
            raise XRTError("No filemanager object")
        ret = None
        for f in filename:
            ret = self.gec.filemanager.getFile(f, multiple=True)
            if ret:
                break
        return ret

    def fileExists(self, *filename):
        """Determine if a file exists with the file manager."""
        if not self.gec.filemanager:
            raise XRTError("No filemanager object")
        ret = None
        for f in filename:
            ret = self.gec.filemanager.fileExists(f)
            if ret:
                break
        return ret

    def getDir(self, dirname):
        """Look up a name with the file manager."""
        raise XRTError("Support for FileManager.getDir() is deprecated")

    def setInputDir(self, dirname):
        """Set (or clear if dirname is None) a temporary INPUTDIR override."""
        if not dirname:
            dirname = ""
        xenrt.TEC().setThreadLocalVariable("_THREAD_LOCAL_INPUTDIR", dirname, fallbackToGlobal=True)

    def getInputDir(self):
        # Check if there is a thread local INPUTDIR.  If not default to using the global INPUTDIR
        # If there is neither a thread local or global INPUTDIR specified this function will
        # raise an exception
        inputDir = xenrt.TEC().lookup("_THREAD_LOCAL_INPUTDIR", None)
        if not inputDir:
            inputDir = xenrt.TEC().lookup("INPUTDIR")
        return inputDir

    def isReleasedBuild(self):
        return "/release/" in self.getInputDir()

    def __str__(self):
        if self.tc:
            return "TEC:%s" % (self.tc.tcid)
        return "TEC"

class ConsoleLogger(threading.Thread):
    """Logs serial console output"""
    def __init__(self, machine, logfile):
        self.machine = machine
        self.logfile = logfile
        self.child = None
        self.handle = None
        self._writers = []
        self._loghistory = []
        self._loghistorycursor = 0
        threading.Thread.__init__(self)
        self.name = "Console-%s" % machine.name
        self.daemon = True

    def associateWithMachine(self, machine):
        self.machine = machine

    def reload(self):
        pass

    def pauseLogging(self):
        pass

    def run(self):
        raise xenrt.XRTError("Unimplemented")

    def addWriter(self, fh):
        """Add a filehandle to the list of places to write."""
        self._writers.append(fh)

    def _writeLine(self, line, timestamp=True):
        """Called by the subclass to actually write a line of log."""
        if timestamp:
            tline = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S %Z"), line)
        else:
            tline = line
        self.handle.write(tline)
        for fh in self._writers:
            try:
                if fh.closed:
                    self._writers.remove(fh)
                else:
                    fh.write(tline)
            except:
                pass
        # Add to the rotating log history.
        c = self._loghistorycursor
        l = len(self._loghistory)
        if l < 1000:
            self._loghistory.append(line)
        else:
            self._loghistory[c] = line
            c = c + 1
            if c >= 1000:
                c = 0
            self._loghistorycursor = c

    def getLogHistory(self):
        """Return the rotating log history as a list of strings."""
        reply = []
        c = self._loghistorycursor
        for i in range(c, len(self._loghistory)):
            reply.append(self._loghistory[i])
        for i in range(0, c):
            reply.append(self._loghistory[i])
        return reply

class ConsoleLoggerConserver(ConsoleLogger):
    """Logs serial console output using conserver"""
    
    def run(self):
        self.handle = file(self.logfile, "w")
        c = xenrt.TEC().lookup("CONSERVER", "console")
        consolename = string.split(self.machine.name, ".")[0]
        command = "%s -U -s %s" % (c, consolename)
        self.child = popen2.Popen4(command)
        p = self.child
        xenrt.TEC().logverbose("Logger: %s (PID %u)" % (command, p.pid))

        try:
            while 1:
                line = p.fromchild.readline()
                if line:
                    self._writeLine(line)
                rc = p.poll()
                if rc != -1:
                    while True:
                        line = p.fromchild.readline()
                        if not line:
                            break
                        self._writeLine(line)
                    break
        except:
            pass
        if self.handle:
            self.handle.close()
            self.handle = None
        self.child = None
            
    def stopLogging(self):
        if self.child:
            pid = self.child.pid
            # Kill any child processes of the process we started (which is probably just a sh)
            f = os.popen("pkill -9 -P %d" % pid)
            f.close()
            try:
                # We think that killing any child processes will also kill the parent process, but just in case:
                os.kill(pid, signal.SIGKILL)
            except:
                pass

            self.child = None

    def reload(self):
        self.consoleCommand("o")

    def pauseLogging(self):
        self.consoleCommand("d")

    def consoleCommand(self, cmd):
        cmdstring = string.join(["Ec%s" % x for x in cmd], "")

        c = xenrt.TEC().lookup("CONSERVER", "console")
        consolename = string.split(self.machine.name, ".")[0]
        try:
            xenrt.util.command("echo '%sEc.' | %s -f -eEc %s" % (cmdstring, c, consolename))
        except:
            pass

class ConsoleLoggerXapi(ConsoleLogger):
    """Logs serial console output using xapi"""

    def __init__(self, machine, logfile):
        self.finished = True
        self.stopped = False
        ConsoleLogger.__init__(self,machine,logfile)

    def run(self):
        self.finished = False
        try:
            self.handle = file(self.logfile, "w")
            self.host = xenrt.TEC().lookupHost(self.machine.name, "CONTAINER_HOST")
            self.password = self.machine.host.lookup("CONTAINER_PASSWORD", xenrt.TEC().lookup("ROOT_PASSWORD"))
            self.uuid = xenrt.ssh.SSH(self.host, "xe vm-list name-label=%s --minimal" % self.machine.name, password=self.password, retval="string", nolog=True).strip()
            self.domid = self.getDomId()
            self.first = True # Exclude the first log as it will be from a different test
            self.pollForNewDomain()
            self.domid = self.getDomId()
            self.getLog() # Get the log at the end
            if self.handle:
                self.handle.close()
                self.handle = None
        finally:
            self.finished = True

    def pollForNewDomain(self):
        count = 0
        while True:
            time.sleep(5)
            count += 1
            if self.stopped:
                break
            if count >= 24: # Poll for domain change every 2 minutes
                domid = self.getDomId()
                if domid != self.domid: # Get the log when the domain changes
                    self.getLog()
                    self.domid = domid
                count = 0

    def getDomId(self):
        try:
            domid = xenrt.ssh.SSH(self.host, "list_domains | grep '%s' | awk '{print $1}'" % self.uuid, password=self.password, retval="string", nolog=True).strip()
            if len(domid) == 0:
                return None
            else:
                return int(domid)
        except Exception, e:
            xenrt.TEC().logverbose("Warning: couldn't find domid for virtual host: %s" % str(e))
            return self.domid
            

    def getLog(self):
        if self.first:
            self.first = False
        else:
            if self.domid:
                try:
                    lines = xenrt.ssh.SSH(self.host, "cat /consoles/console.%d.log" % self.domid, password=self.password, retval="string", nolog=True).splitlines()
                    for l in lines:
                        self._writeLine("%s\n" % l, timestamp=False)
                    xenrt.ssh.SSH(self.host, "rm /consoles/console.%d.log" % self.domid, password=self.password, retval="string", nolog=True)
                except Exception, e:
                    xenrt.TEC().logverbose("Warning: couldn't get log for domid %d: %s" % (self.domid, str(e)))
    
    def addWriter(self, fh):
        pass

    def stopLogging(self):
        if not self.finished:
            tries = 0
            self.stopped = True
            while tries < 5:
                time.sleep(10)
                if self.finished:
                    break

class PhysicalHost(object):
    """A physical machine."""
    def __init__(self, name, ipaddr=None, powerctltype=None):
        """Constructor.

        @param name: text name of the machine
        @param ipaddr: static IP address of the machine
        """
        self.name = name
        self.host = None
        self.macaddr = ""
        if not ipaddr:
            try:
                ipaddr = xenrt.util.getHostAddress(name)
            except:
                ipaddr = xenrt.util.getHostAddress(name + ".testdev.hq.xensource.com")
        self.ipaddr = ipaddr        
        self.ipaddr6 = None
        self.pxeipaddr = self.ipaddr
        self.consoleLogger = None
        self.poweredOffAtExit = False
        if not powerctltype and xenrt.TEC().lookupHost(name, "CONTAINER_HOST", None): 
            powerctltype = "xapi"
        if not powerctltype:
            powerctltype = xenrt.TEC().lookupHost(name,
                                              "POWER_CONTROL",
                                              None)
        if powerctltype == "xenuse":
            self.powerctl = xenrt.powerctl.Xenuse(self)
        elif powerctltype == "askuser":
            self.powerctl = xenrt.powerctl.AskUser(self)
        elif powerctltype == "soft":
            self.powerctl = xenrt.powerctl.Soft(self)
        elif powerctltype == "APCPDU" or powerctltype == "PDU":
            self.powerctl = xenrt.powerctl.PDU(self)
        elif powerctltype == "ilo":
            self.powerctl = xenrt.powerctl.ILO(self)
        elif powerctltype == "ipmi":
            self.powerctl = xenrt.powerctl.IPMI(self)
        elif powerctltype == "ipmiapcfallback" or powerctltype == "ipmipdufallback":
            self.powerctl = xenrt.powerctl.IPMIWithPDUFallback(self)
        elif powerctltype == "custom":
            self.powerctl = xenrt.powerctl.Custom(self)
        elif powerctltype == "ciscoucs":
            self.powerctl = xenrt.powerctl.CiscoUCS(self)
        elif powerctltype == "xapi":
            self.powerctl = xenrt.powerctl.Xapi(self)
        else:
            self.powerctl = xenrt.powerctl.AskUser(self)
            xenrt.TEC().warning("Unknown power control method %s for %s" % 
                                (powerctltype,self.name))
        
        return

    def lookup(self, var, default=xenrt.XRTError, boolean=False):
        """Lookup a per-host variable"""
        return xenrt.TEC().lookupHost(self.name,
                                      var,
                                      default=default,
                                      boolean=boolean)

    def exitPowerOff(self):
        if not xenrt.TEC().lookup("NO_HOST_POWEROFF", False, boolean=True) and not self.poweredOffAtExit:
            self.poweredOffAtExit = True
            self.powerctl.off()

    def setHost(self, host):
        """Specify the host object (GenericHost) using this machine."""
        self.host = host

    def getHost(self):
        """Returns the host object (GenericHost) using this machine."""
        return self.host

    def startConsoleLogger(self, logfile):
        """Start logging serial console output"""
        if xenrt.TEC().lookupHost(self.name, "CONTAINER_HOST", None):
            if xenrt.TEC().lookupHost(self.name, "GUEST_TYPE", None) == "vxs":
                c = "xapi"
            else:
                c = None
        else:
            c = xenrt.TEC().lookupHost(self.name, "CONSOLE_LOGGER", None)
        if not c:
            return None
        if c == "conserver":
            l = ConsoleLoggerConserver(self, logfile)
            l.start()
            self.consoleLogger = l
            return l
        elif c == "xapi":
            l = ConsoleLoggerXapi(self, logfile)
            l.start()
            self.consoleLogger = l
            return l
        return None

    def addConsoleLogWriter(self, fh):
        """Additionally write console logging to this fh until it disappears."""
        if self.consoleLogger:
            self.consoleLogger.addWriter(fh)

    def getConsoleLogHistory(self):
        """Return the rotating console log history as a list of strings."""
        if self.consoleLogger:
            return self.consoleLogger.getLogHistory()
        return []

    def getVirtualMedia(self):
        """Return a VirtualMedia object for manipulating virtual media."""
        return xenrt.virtualmedia.VirtualMediaFactory(self)

def markThread():
    """Thread to run periodic mark callback methods."""
    while True:
        GEC().runMarkCallbacks()
        xenrt.sleep(60, log=False)

class GlobalExecutionContext(object):
    """Current global execution state."""
    def __init__(self, config=None):
        self.loghistory = []
        self.loghistorycursor = 0
        setGec(self)
        self.filemanager = None
        self.mycblock = threading.Lock()
        self.runningcb = False
        # Config object
        self.config = config
        self.semaphores = {}
        self.callbacks = []
        self.markCallbacks = []
        self.results = xenrt.results.GlobalResults()
        self.registry = xenrt.registry.Registry()
        self.dbconnect = xenrt.DBConnect(self.config.lookup("JOBID", None))
        self.anontec = TCAnon(self).tec
        self.skipTests = {}
        self.skipSkus = {}
        self.skipGroups = {}
        self.skipTypes = {}
        self.noSkipTests = {}
        self.noSkipSkus = {}
        self.noSkipGroups = {}
        self.priority = None
        self.harnesserror = False
        self.loggers = []
        self.running = {}
        self.abort = False
        self.perfChecks = {}
        self.perfRegresses = {}
        self.prepareonly = True 
        self.preparefailed = None
        self.prepareticket = None
        self.sequence = None
        self.knownIssues = {}
        thread.start_new_thread(markThread, ())
        self.preJobTestsDone = False
        self.locks = {}
        self.lockLock = threading.Lock()
        return

    def getLock(self, lockname):
        with self.lockLock:
            if not self.locks.has_key(lockname):
                self.locks[lockname] = threading.Lock()
        return self.locks[lockname]
        
    def getRunningTests(self):
        """List tests currently running.

        Returns a list of 2 element lists of testcase names (as group/name)
        and running status ("Started", "Finished", etc.)."""
        reply = []
        for t in self.running.keys():
            reply.append([t, self.running[t]])
        return reply

    def setRunningStatus(self, test, status):
        """Update the running status of a test.

        @param test: testcase group/name as returned by getRunningTests
        @param status: running status to change to (string)
        """
        self.running[test] = status

    def setBlockingStatus(self, test, status):
        """Set the blocking status of a running testcase.

        @param test: testcase group/name as returned by L{getRunningTests}
        @param status: blocking status to change to (I{boolean})
        """
        l = string.split(test, '/', 1)
        groupname = l[0]
        testname = l[1]
        self.results.getTC(groupname, testname).blocker = status

    def setTestResult(self, test, result):
        """Forcably set the testcase result.

        @param test: testcase group/name as returned by getRunningTests
        @param result: integer result code
        """
        l = string.split(test, '/', 1)
        groupname = l[0]
        testname = l[1]
        self.results.setResult(groupname, testname, result)

    def abortRun(self):
        """Set the abort-run flag."""
        self.abort = True

    def getFailures(self):
        """Return a list of failed testcases."""
        return self.results.getFailures()
        
    def getTestCases(self):
        """Return a list of executed testcases."""
        return self.results.getTestCases()
        
    def runCallbacks(self):
        """Run all shutdown callbacks registered."""
        self.mycblock.acquire()
        try:
            self.runningcb = True
            for clist in self.callbacks:
                for c in clist:
                    try:
                        c.callback()
                    except Exception, e:
                        traceback.print_exc(file=sys.stderr)
            self.runningcb = False
        finally:
            self.mycblock.release()

    def runMarkCallbacks(self):
        """Run all marked callbacks."""
        self.mycblock.acquire()
        try:
            for c in self.markCallbacks:
                c.mark()
        finally:
            self.mycblock.release()

    def registerCallback(self, cb, mark=False, order=2):
        """Register an object for a shutdown callback."""
        if self.runningcb:
            return
        self.mycblock.acquire()
        try:
            while len(self.callbacks) < order:
                self.callbacks.append([])
            self.callbacks[order-1].append(cb)
            if mark:
                self.markCallbacks.append(cb)
        finally:
            self.mycblock.release()

    def unregisterCallback(self, cb):
        """Unregister an object previously registered for a shutdown callback.
        """
        if self.runningcb:
            return
        self.mycblock.acquire()
        try:
            for c in self.callbacks:
                try:
                    c.remove(cb)
                except:
                    pass
            try:
                if cb in self.markCallbacks:
                    self.markCallbacks.remove(cb)
            except:
                pass
        finally:
            self.mycblock.release()

    def runTC(self,
              tcclass,
              arglist,
              blocked=False,
              blockedticket=None,
              name=None,
              host=None,
              guest=None,
              group=None,
              runon=None,
              isfinally=False,
              prio=None,
              ttype=None,
              depend=None,
              blocker=None,
              jiratc=None,
              tcsku=None,
              marvinTestConfig=None):
        """Run a test case by name.

        This method is called by the sequence execution logic or by the
        single-testcase mode dispatch code. It performs the following:
         - instantiates the testcase class
         - renames the testcase if required
         - sets the testcase data including group and priority
         - decides on whether the testcase should be skipped by job config
           or explicit dependencies
         - updates the central job database with progress information (if
           under job control)
         - starts and waits for the testcase to execute
         - uploads results and logs to the central job database (if under
           job control)
         - files a Jira bug if necessary and enabled

        This method raises XRTBlocker if the testcase is a blocking testcase
        and the testcase failed or generated a harness error.

        @param tcclass: testcase class reference to instantiate
        @param arglist: list of arguments to pass to the testcase
        @param blocked: True if this testcase is blocked by previous testcases
        @param name: optional name for testcase (defaults to the class name)
        @param host: host name to run the testcase on (for the runon mechanism)
        @param guest: guest to run the testcase on (for the runon mechanism)
        @param group: name of the group the testcase is a member of
        @param runon: instance of GenericPlace to run the testcase on
        @param isfinally: True if this is part of a finally sequence block
        @param prio: integer priority
        @param ttype: testcase type, used for filtering
        @param depend: comma-separated list of testcases this on depends on
        @param blocker: C{True} if this is a blocking testcase
        @param marvinTestConfig: dictionary config for executing Marvin tests
        """
        initfail = False
        try:
            t = tcclass()
            # Check that xenrt.TestCase.__init__ has run. If not, then various
            # things won't be set up, which can lead to XenRT exiting with an
            # unhandled exception
            if not hasattr(t, '_initDone'):
                raise XRTError("xenrt.TestCase.__init__ has not been called")
        except Exception, e:
            t = TestCase(re.sub(".*\.", "", "%s" % tcclass))
            initfail = True
            sys.stderr.write(str(e).rstrip()+'\n')
            traceback.print_exc(file=sys.stderr)
            t.results.reason(str(e))
            xenrt.TEC().logverbose(traceback.format_exc())
            xenrt.TEC().logverbose(str(e), pref='REASON')
        t.setTCSKU(tcsku)
        if not jiratc:
            jiratc = t.getDefaultJiraTC()
        t.setJiraTC(jiratc)
        t.marvinTestConfig = marvinTestConfig
        if name and group:
            t._rename("%s/%s" % (group, name))
            t._setBaseName(name)
            t._setGroup(group)
        elif name:
            t._rename(name)
            t._setBaseName(name)
        elif group:
            t._rename("%s/%s" % (group, t.tcid))
            t._setGroup(group)
        if not isfinally:
            self.results.addTest(t)
        if group:
            phase = group
        else:
            phase = "Phase 99"
        logtcid = None
        if not jiratc:
            m = re.match("TC(\d+)", t.basename)
            if m:
                logtcid = "TC-%s" % m.group(1)
        else:
            logtcid = jiratc
        if logtcid and tcsku:
            logtcid += "_%s" % tcsku
        if logtcid:
            self.dbconnect.jobLogData(phase,
                                      t.basename,
                                      "TCID",
                                      logtcid)

        self.dbconnect.jobLogData(phase,
                                  t.basename,
                                  "TCClass",
                                  "%s.%s" % (tcclass.__module__, tcclass.__name__))

        t.runon = runon
        if prio:
            t._setPriority(prio)
        if blocker != None:
            t.blocker = blocker

        # Have been asked to skip? A skip can be specified as a TC name
        # or a group/name string
        if self.abort:
            t.tec.skip("Run aborted, skipping test")
        elif t.tec.lookup("SKIPALL", False, boolean=True):
            # Check for any forced runs
            l = string.split(t.tcid, "/")
            noskip = False
            if len(l) == 1:
                # No group in the testcase
                if self.noSkipTests.has_key(t.tcid):
                    noskip = True
            else:
                # Check for group/name
                if self.noSkipTests.has_key(t.tcid):
                    noskip = True
                # Check for just the name
                if self.noSkipTests.has_key(l[-1]):
                    noskip = True
            if t.group and self.noSkipGroups.has_key(t.group):
                noskip = True
            if jiratc and self.noSkipTests.has_key(string.replace(jiratc,"-","")):
                noskip = True
            if tcsku and self.noSkipSkus.has_key(tcsku):
                noskip = True
            if not noskip:
                t.tec.skip("Skipped by SKIPALL")
        else:
            l = string.split(t.tcid, "/")
            if len(l) == 1:
                # No group in the testcase
                if self.skipTests.has_key(t.tcid):
                    t.tec.skip("Skipped by %s" % (t.tcid))
            else:
                # Check for group/name
                if self.skipTests.has_key(t.tcid):
                    t.tec.skip("Skipped by %s" % (t.tcid))
                # Check for just the name
                if self.skipTests.has_key(l[-1]):
                    t.tec.skip("Skipped by %s" % (l[-1]))
            if t.group and self.skipGroups.has_key(t.group):
                t.tec.skip("Skipped by %s" % (t.group))
            if ttype and self.skipTypes.has_key(ttype):
                t.tec.skip("Skipped by %s" % (ttype))
            if jiratc and self.skipTests.has_key(string.replace(jiratc,"-","")):
                t.tec.skip("Skipped by %s" % (jiratc))
            if tcsku and self.skipSkus.has_key(tcsku):
                t.tec.skip("Skipped by %s" % (tcsku))

        if self.priority != None and prio != None:
            if prio > self.priority:
                # Check for any forced runs
                l = string.split(t.tcid, "/")
                noskip = False
                if len(l) == 1:
                    # No group in the testcase
                    if self.noSkipTests.has_key(t.tcid):
                        noskip = True
                else:
                    # Check for group/name
                    if self.noSkipTests.has_key(t.tcid):
                        noskip = True
                    # Check for just the name
                    if self.noSkipTests.has_key(l[-1]):
                        noskip = True
                if t.group and self.noSkipGroups.has_key(t.group):
                    noskip = True
                if tcsku and self.noSkipSkus.has_key(tcsku):
                    noskip = True
                if not noskip:
                    t.tec.skip("TC prio %u < target prio %u" %
                               (self.priority, prio))

        skipDueDepend = None
        if depend:
            depends = depend.split(",")
            for dep in depends:
                # See what state the dependency's in, and see if we should skip
                dependSplit = dep.split(":")
                try:
                    depResult = self.results.getResult(dependSplit[0],
                                                       dependSplit[1])
                except:
                    t.tec.warning("Invalid dependency %s, ignoring..." % (dep))

                if (depResult != "pass"):
                    skipDueDepend = dep
                    t.tec.skip("Skipping by dependency")
                    break
        if initfail:
            t.setResult(RESULT_ERROR)

        # Put in TC description
        if not initfail: # (if init failed, we have only the base class desc)
            try:
                tcdoc = inspect.getdoc(t)
                if tcdoc:
                    xenrt.GEC().dbconnect.jobLogData(phase,
                                                     t.basename,
                                                     "description",
                                                     tcdoc)
            except:
                pass

        if t.isSkipped():
            if skipDueDepend:
                t.tec.progress("Skipping due to dependency %s state" % 
                               (skipDueDepend))
            else:
                t.tec.progress("Skipping by CLI instruction")
            if not isfinally:
                self.dbconnect.jobSetResult(phase, t.basename, "skipped")
        elif not blocked:
            if not initfail:
                t.tec.progress("Starting...")
                if not isfinally:
                    self.dbconnect.jobLogData(phase,
                                              t.basename,
                                              "result",
                                              "started")
                t.runningtag = "%s/%s" % (phase, t.basename)
                self.running[t.runningtag] = "Started"
                t._start(arglist=arglist, host=host, guest=guest,
                        isfinally=isfinally)
                t._waitfor()

            self.running[t.runningtag] = "Finished"
            respath = "%s/%s.result" % (t.tec.lookup("RESULT_DIR", "."),
                                        t.tcid)
            if not os.path.exists(os.path.dirname(respath)):
                os.makedirs(os.path.dirname(respath))
            f = file(respath, 'w')
            t._process(f)
            f.close()
            #try:
            #    if not t.isSkipped():
            #        t._getRemoteLogs()
            #except:
            #    t.tec.logverbose("Error fetching logs")
            if not isfinally:
                try:
                    self.dbconnect.jobSetResult(phase, t.basename, t.getResult())
                    t.results.generateXML("%s/results.xml" % (t.tec.getLogdir()),
                                          t)
                    self.dbconnect.jobSubResults(phase, t.basename,
                                                 "%s/results.xml" %
                                                 (t.tec.getLogdir()))
                    data = t.getData()
                    for i in data:
                        k, v = i
                        self.dbconnect.jobLogData(phase, t.basename, k, v)
                except Exception, e:
                    t.tec.logverbose("Exception writing to results database: "
                                     "%s" % (str(e)))
                    traceback.print_exc(file=sys.stderr)
                xenrt.TEC().logverbose("Trying to gather performance data.")
                t.tec.flushLogs()
                if t.tec.lookup("DB_LOGS_UPLOAD", True, boolean=True):
                    try:
                        self.dbconnect.jobUpload(t.tec.getLogdir(), phase,
                                                 t.basename)
                    except Exception, e:
                        t.tec.logverbose("Exception uploading logs: %s" %
                                         (str(e)))
                        traceback.print_exc(file=sys.stderr)
                if t.tec.lookup("AUTO_BUG_FILE", False, boolean=True):
                    try:
                        jl = xenrt.jiralink.getJiraLink()
                        t.ticket = jl.processTC(t.tec,jiratc, tcsku)
                        if t.ticket:
                            self.dbconnect.jobLogData(phase, t.basename, "comment", "Jira Ticket %s" % (t.ticket))
                            for cdt in t._crashdumpTickets:
                                jl.linkCrashdump(t.ticket,cdt)
                    except Exception, e:
                        sys.stderr.write(str(e).rstrip()+'\n')
                        traceback.print_exc(file=sys.stderr)
                        xenrt.GEC().logverbose("Jira Link Exception: %s" % (e),
                                               pref='WARNING')

                if t.tec.lookup("TESTRUN_SR", None):
                    try:
                        jl = xenrt.jiralink.getJiraLink()
                        if not jl.processTR(t.tec,t.ticket,jiratc,tcsku):
                            # We didn't file a testrun entry
                            if t.ticket:
                                if t.getResult() == "fail":
                                    t.ticketIsFailure = True
                                else:
                                    t.ticketIsFailure = False
                    except Exception, e:
                        xenrt.GEC().logverbose("TestRun Exception: %s" % (e),
                                               pref='WARNING')
        else:
            t.tec.progress(str(blocked))
            if not isfinally:
                self.dbconnect.jobSetResult(phase, t.basename, "blocked")
            if t.tec.lookup("TESTRUN_SR", None):
                try:
                    jl = xenrt.jiralink.getJiraLink()
                    jl.processTR(t.tec,blockedticket,jiratc,tcsku)
                except Exception, e:
                    sys.stderr.write(str(e).rstrip()+'\n')
                    traceback.print_exc(file=sys.stderr)
                    xenrt.GEC().logverbose("Jira Link Exception: %s" % (e),
                                           pref='WARNING')
        if t.runningtag and self.running.has_key(t.runningtag):
            del self.running[t.runningtag]
        t._cleanup()
        setTec()
        if not blocked and t.isBlocker() and not (t.isPass() or (t.isSkipped() and not t.tec.lookup("OPTION_BLOCK_ON_SKIP", False, boolean=True))):
            raise XRTBlocker(t)
        return t

    def skipTest(self, tcid):
        """Register a test case to be skipped."""
        self.skipTests[tcid] = True
        self.logverbose("Test will be skipped: %s" % (tcid))

    def skipSku(self, sku):
        """Register a test case to be skipped."""
        self.skipSkus[sku] = True
        self.logverbose("Test will be skipped: %s" % (sku))

    def skipGroup(self, group):
        """Register a test group to be skipped."""
        self.skipGroups[group] = True
        self.logverbose("Group will be skipped: %s" % (group))

    def skipType(self, ttype):
        """Register a test type to be skipped."""
        self.skipTypes[ttype] = True
        self.logverbose("Test type will be skipped: %s" % (ttype))

    def noSkipTest(self, tcid):
        """Register a test case to not be skipped."""
        self.noSkipTests[tcid] = True
        self.logverbose("Test will not be skipped: %s" % (tcid))

    def noSkipSku(self, sku):
        """Register a test case to not be skipped."""
        self.noSkipSkus[sku] = True
        self.logverbose("Test will not be skipped: %s" % (sku))

    def noSkipGroup(self, group):
        """Register a test group to not be skipped."""
        self.noSkipGroups[group] = True
        self.logverbose("Group will not be skipped: %s" % (group))

    def perfCheck(self, tc, metric, min, max):
        """Register a performance result sanity testing window."""
        self.perfChecks["%s/%s" % (tc, metric)] = (min, max)

    def perfCheckParse(self, xmlnode):
        """Parse an XML node containing perfcheck limits"""
        for m in xmlnode.childNodes:
            if m.nodeType == m.ELEMENT_NODE and m.localName == "limits":
                for t in m.childNodes:
                    if t.nodeType == t.ELEMENT_NODE and \
                           t.localName == "testcase":
                        tc = t.getAttribute("name")
                        for m in t.childNodes:
                            if m.nodeType == m.ELEMENT_NODE and \
                                   m.localName == "metric":
                                metric = m.getAttribute("name")
                                min = float(m.getAttribute("min"))
                                max = float(m.getAttribute("max"))
                                self.perfCheck(tc, metric, min, max)
                                    
    def perfRegress(self, group, tc, metric, value, units):
        """Register a previous performance result for regression checking."""
        self.perfRegresses["%s/%s/%s" % (group, tc, metric)] = \
                                      (value, units)

    def checkPerfValue(self, group, tc, metric, value):
        """Perform sanity and regression testing of a performance result.

        This checks against any sanity testing windows and previous results
        registered with perfCheck() and perfRegress().

        If PERF_STRICT is set then any failures result in a XRTFailure
        exception being raised. Otherwise warnings are issued.

        A failure is defined as:
         - a result outside of a sanity test window
         - a result more than 10% worse than a previous result

        A warning is issued if a performance regerssion of 5 to 10% is
        found.

        Performance numbers are assumed to be increasing, i.e. bigger number
        is better, unless the units are specified and are of a type known
        the be lower is better.
        """
        # Sanity check
        k = "%s/%s" % (tc, metric)
        if self.perfChecks.has_key(k):
            min, max = self.perfChecks[k]
            v = float(value)
            if v < min or v > max:
                msg = "Result %s %f is outside of window [%f %f]" % \
                      (metric, v, min, max)
                if xenrt.TEC().lookup("PERF_STRICT", False, boolean=True):
                    raise XRTFailure(msg)
                else:
                    xenrt.TEC().warning(msg)
        # Regression check
        k = "%s/%s/%s" % (group, tc, metric)
        if self.perfRegresses.has_key(k):
            rvalue, runits = self.perfRegresses[k]
            v = float(value)
            loss = 100.0 * (rvalue - v)/rvalue
            # Assume bigger numbers are better unless it's time
            if runits and runits in ["s", "seconds", "sec", "secs", "S", "ms"]:
                loss = 0.0 - loss
            if loss > 5.0:
                if runits:
                    msg = "Result %s %f is %.1f%% worse than before (%f %s)" % \
                          (metric, v, loss, rvalue, runits)
                else:
                    msg = "Result %s %f is %.1f%% worse than before (%f)" % \
                          (metric, v, loss, rvalue)
                if loss <= 10.0 or not xenrt.TEC().lookup("PERF_STRICT",
                                                          False,
                                                          boolean=True):
                    xenrt.TEC().warning(msg)
                else:
                    raise XRTFailure(msg)
            else:
                xenrt.TEC().logverbose("Result %s %f loss %.1f%%" %
                                       (metric, v, loss))

    def setPriority(self, prio):
        """Set the execution priority threshold.

        Testcases up to and including this priority will be executed.
        """
        self.priority = prio

    def harnessError(self):
        """Set a global flag noting that there was a harness error.

        This prevents the test sequence result being a pass.
        """
        self.harnesserror = True

    def startLogger(self, machine):
        """Start a physical machine console logger."""
        ld = self.anontec.getLogdir()
        if ld:
            f = "%s/console.%s.log" % (ld, machine.name)
            # See if we already have a logger for this machine
            l = None
            for logger in self.loggers:
                if logger.logfile == f:
                    l = logger
                    break
            if l:
                # Associate this logger with the PhysicalMachine objects
                l.associateWithMachine(machine)
                machine.consoleLogger = l
            else:
                l = machine.startConsoleLogger(f)
                if l:
                    self.loggers.append(l)
            
    def onExit(self, aux=False):
        """Harness program exit handler.

        This method performs the final sequence outcome check and updates
        the central database (if under job control). Summary results files
        are generated. Shutdown callbacks are executed.
        """
        
        xenrt.TEC().logverbose("Harness program exit handler called.")
        
        borrow = None
        for l in self.loggers:
            try:
                if l:
                    l.stopLogging()
            except Exception, e:
                print str(e)
        if not aux:
            if not xenrt.TEC().lookup("NOLOGS", False, boolean=True):
                # Try and collect logs from every host
                try:
                    hosts = self.config.getWithPrefix("RESOURCE_HOST_")
                    for hTuple in hosts:
                        hKey = hTuple[0]
                        h = xenrt.TEC().registry.hostGet(hKey)
                        if h:
                            try:
                                self.anontec.tc._getRemoteLogsFrom(h)
                            except Exception, ex:
                                xenrt.TEC().logverbose("Exception getting host logs: %s" % str(ex))
                            
                            try:
                                for g in [ xenrt.TEC().registry.guestGet(x) for x in h.listGuests() ]:
                                    try:
                                        self.anontec.tc._getRemoteLogsFrom(g)
                                    except Exception, e:
                                        pass
                            except Exception, ex:
                                xenrt.TEC().logverbose("Exception getting guests' logs: %s" % str(ex))
                            
                            try:
                                if self.preJobTestsDone:
                                    h.postJobTests()
                            except:
                                pass
                except Exception, ex2:
                    xenrt.TEC().logverbose("Exception getting logs: %s" % str(ex2))

                # And every toolstack
                try:
                    ts = xenrt.TEC().registry.toolstackGetAll()
                    for t in ts:
                        try:
                            self.anontec.tc._getRemoteLogsFrom(t)
                        except Exception, ex:
                            xenrt.TEC().logverbose("Exception getting toolstack logs: %s" % str(ex))
                except Exception, ex2:
                    xenrt.TEC().logverbose("Exception getting logs: %s" % str(ex2))

            try:
                logdir = self.anontec.getLogdir()
                record = xenrt.GEC().registry.getDeploymentRecord()
                with open("%s/deployment.json" % logdir, "w") as f:
                    f.write(json.dumps(record, indent=2))
                self.dbconnect.jobUpload("%s/deployment.json" % logdir, prefix="deployment.json")
            except Exception, e:
                xenrt.TEC().logverbose("Exception getting deployment record: %s" % str(e))

            self.results.report(sys.stdout)
            if self.harnesserror:
                ok = False
                regok = False
                rates = None
            else:
                ok, regok, rates = self.results.check()
            if ok:
                sys.stdout.write("Sequence: PASS\n")
                x = "OK"
                borrow = xenrt.TEC().lookup("MACHINE_HOLD_FOR_OK", None)
                if not borrow:
                    borrow = xenrt.TEC().lookup("MACHINE_HOLD_FOR", None)
            else:
                sys.stdout.write("Sequence: FAIL\n")
                x = "ERROR"
                borrow = xenrt.TEC().lookup("MACHINE_HOLD_FOR_FAIL", None)
                if not borrow:
                    borrow = xenrt.TEC().lookup("MACHINE_HOLD_FOR", None)
            
            reason = xenrt.TEC().lookup("MACHINE_HOLD_REASON", None)
            
            if rates:
                sys.stdout.write("Pass rates: %s\n" % (rates))
                self.dbconnect.jobUpdate("PASSRATES", rates)
            self.dbconnect.jobUpdate("RETURN", x)
            self.dbconnect.jobUpdate("CHECK", x)
            if borrow and self.jobid():
                for m in xenrt.TEC().lookup("MACHINE").split(","):
                    c = [m]
                    
                    if borrow == "inf":
                        c.append("-f")
                    else:
                        c.append("-h")
                        c.append("%u" % (int(borrow)/60))
                    
                    if reason:
                        c.append("-r")
                        c.append(reason)
                    
                    u = xenrt.TEC().lookup("USERID", None)
                    if u:
                        c.append("-u")
                        c.append(u)
                    xenrt.TEC().logverbose("Borrowing %s" % m)
                    self.dbconnect.jobctrl("borrow", c)
            if regok:
                sys.stdout.write("Regression: PASS\n")
                x = "OK"
            else:
                sys.stdout.write("Regression: FAIL\n")
                x = "ERROR"
            self.dbconnect.jobUpdate("REGRESSION", x)
            logdir = self.anontec.getLogdir()
            self.results.generateXML("%s/results.xml" %
                                     (logdir))
            try:
                fmtr = xenrt.formatter.Formatter()
                fmtr.processXML("%s/results.xml" % (logdir),logdir)
                for p in glob.glob("%s/*.html" % (logdir)):
                    shutil.copy(p, os.path.basename(p))
            except:
                pass
        self.anontec.flushLogs()
        if not aux:
            for l in self.loggers:
                l.stopLogging()
            if xenrt.TEC().lookup("DB_LOGS_UPLOAD", True, boolean=True):
                self.dbconnect.jobUpload(self.anontec.getLogdir())
            self.dbconnect.jobUpdate("UPLOADED", "yes")
            if xenrt.TEC().lookup("COMPLETION_EMAIL", True, boolean=True):
                self.dbconnect.jobEmail()
            jobid = xenrt.GEC().jobid()
            if jobid:
                for u in xenrt.TEC().lookupLeaves("CALLBACK_URL"):
                    details = self.dbconnect.jobctrl("status", [str(jobid)])
                    xenrt.TEC().logverbose("Calling %s" % u)
                    try:
                        urllib2.urlopen(u, urllib.urlencode(details), timeout=300)
                    except Exception, e:
                        xenrt.TEC().logverbose("WARNING: Could not load callback URL %s" % u)

        self.runCallbacks()

        if not aux:
            # XRT-3021 Disable outbound iSCSI on every host
            if xenrt.util.keepSetup():
                xenrt.TEC().logverbose("Not blocking iSCSI traffic")
            else:
                try:
                    hosts = self.config.getWithPrefix("RESOURCE_HOST_")
                    for hTuple in hosts:
                        hKey = hTuple[0]
                        h = xenrt.TEC().registry.hostGet(hKey)
                        if h and not h.machine.poweredOffAtExit:
                            try:
                                h.execdom0("logger -t XenRT XRT-3021 Installing "
                                           "iptables rule to block iSCSI traffic")
                                h.execdom0("iptables -I OUTPUT -p tcp --dport 3260 "
                                           "-j DROP")
                            except:
                                pass
                except:
                    pass

    def addToLogHistory(self, string):
        """Add a string to the rotating log history."""
        c = self.loghistorycursor
        l = len(self.loghistory)
        if l < 1000:
            self.loghistory.append(string)
        else:
            self.loghistory[c] = string
            c = c + 1
            if c >= 1000:
                c = 0
            self.loghistorycursor = c

    def getLogHistory(self):
        """Return the rotating log history as a list of strings."""
        reply = []
        c = self.loghistorycursor
        for i in range(c, len(self.loghistory)):
            reply.append(self.loghistory[i])
        for i in range(0, c):
            reply.append(self.loghistory[i])
        return reply

    def _logAnnotation(self, str):
        ips = re.findall('\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', str)
        uuids = re.findall('[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', str)
        if ips or uuids:
            all_map = {}
            all_hosts = set([self.registry.hostGet(h) for h in self.registry.hostList()])
            all_guests = set([self.registry.guestGet(g) for g in self.registry.guestList()])
            all_entities = set.union(len(all_hosts) > 1 and all_hosts or set(), all_guests)
            for e in all_entities:
                try:
                    ip = e.getIP()
                    uuid = e.uuid
                    keys = []
                    if ip in ips and not all_map.has_key(ip): keys.append(ip)
                    if uuid in uuids and not all_map.has_key(uuid): keys.append(uuid[:8])
                    for k in keys:
                        name = e.getName()
                        # Make a default first just in case of exceptions
                        all_map[k] = name
                        if isinstance(e, xenrt.GenericHost):
                            if e.pool and e.pool.master != e:
                                all_map[k] += '~>%s' % e.pool.master.getName()
                        elif isinstance(e, xenrt.GenericGuest):
                            all_map[k] += '@%s (%s)' % (e.getHost().getName(), e.distro)
                except: pass
            if all_map:
                str = "%s (%s)" % (str, ", ".join(['%s = %s' % (k, all_map[k]) for k in all_map]))
        return str
        

    def logverbose(self, strn, pref='VERBOSE'):
        """Log a verbose string with timestamp.

        @param strn: string to log
        @param pref: optional prefix tag (defaults to "VERBOSE")
        """
        s = "[%s] [%s] %s\n" % (pref, time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                                pref == 'VERBOSE' and self._logAnnotation(str(strn)) or strn)
        if self.config.isVerbose():
            try:
                sys.stderr.write(s)
            except UnicodeEncodeError:
                sys.stderr.write(s.encode("utf-8"))
        self.addToLogHistory(s)
        return s

    def progress(self, str, tcid):
        """Record progress through a test case."""
        s = "[PROGRESS] %s: %s\n" % (tcid, str)
        sys.stderr.write(s)
        self.addToLogHistory(s)
        return s

    def semaphoreAcquire(self, semclass):
        semclass = string.lower(semclass)
        if self.semaphores.has_key(semclass):
            xenrt.TEC().logverbose("Trying to acquire semaphore '%s'" %
                                   (semclass))
            self.semaphores[semclass].acquire()
            xenrt.TEC().logverbose("Semaphore '%s' acquired" % (semclass))
            
    def semaphoreRelease(self, semclass):
        semclass = string.lower(semclass)
        if self.semaphores.has_key(semclass):
            xenrt.TEC().logverbose("Releasing semaphore '%s'" % (semclass))
            self.semaphores[semclass].release()

    def semaphoreCreate(self, semclass, count=1):
        semclass = string.lower(semclass)
        self.semaphores[semclass] = threading.Semaphore(count)

    def jobid(self):
        return self.dbconnect.jobid()

    def reprepare(self):
        """Re-run the sequence prepare actions."""
        self.sequence.doPrepare()
        self.sequence.doPreprepare()

    def isKnownIssue(self, ticketid):
        """Returns True if the specified Jira ticket ID is declared a known
        issue for this run."""
        if not self.knownIssues.has_key(ticketid):
            # If we don't know about this ticket then see if we have a rule
            # for the entire project (configured as "KNOWN_<project>=yes")
            r = re.search(r"^([A-Z]+)-\d+", ticketid)
            if r:
                if self.knownIssues.has_key(r.group(1)):
                    return self.knownIssues[r.group(1)]
            return False
        # We know about this particular ticket
        return self.knownIssues[ticketid]

    def addKnownIssue(self, ticketid):
        """Adds the specified Jira ticket as a known issue for this run."""
        self.knownIssues[ticketid] = True

    def removeKnownIssue(self, ticketid):
        """Removes the specified Jira ticket as a known issue for this run."""
        self.knownIssues[ticketid] = False

    def addKnownIssueList(self, l):
        """Adds the Jira ticket IDs in a comma-separated list as known issues
        for this run."""
        for t in l.split(","):
            self.addKnownIssue(t)

############################################################################
# Debugger Methods                                                         #
############################################################################

import ast, pickle, subprocess, copy

def debuggerAction( type = 'breakpoint', condition = True):
    xenrt.TEC().logverbose('Unable to pause for Breakpoint: Debugging Mode set to false')
    





#############################################################################

def checkTarball(tarball):
    """
    Check if the specified tarball exists, return the local file path
    ("/dir/file") or remote url ("http://host/file") if found, otherwise None
    """
    path = None
    filepath = "%s/%s" % (xenrt.TEC().lookup("TEST_TARBALL_ROOT"), tarball)
    if os.path.exists(filepath):
        path = filepath
    else:
        urlpath = "%s/%s" % (xenrt.TEC().lookup("TEST_TARBALL_BASE"), tarball)
        try:
            f = urllib2.urlopen(urlpath)
            path = f.url
            f.close()
        except:
            pass
    return path
    
def getTestTarball(testname, extract=False, copy=True, directory=None):
    """Fetch and optional extract a test tarball in the local working dir.

    @param testname: test name, used as the basename stem for the tarball
    @param extract: if C{True} extract the tarball
    @param copy: if C{True} copy the tarball to the working directory
    @param directory: optional directory to use instead of the working dir
    """
    if not directory:
        directory = xenrt.TEC().getWorkdir()
    testpkg = testname + ".tgz"
    path = checkTarball(testpkg)
    if not path:
        raise XRTError("No test tarball found for %s" % (testname))
    else:
        if re.match('(https?|ftp)://', path):
            if copy:
                dstpath = "%s/%s" % (directory, testpkg)
            else:
                fd, dstpath = tempfile.mkstemp()
                os.close(fd)
            fout = open(dstpath, "wb")                
            fin = urllib2.urlopen(path)
            fout.write(fin.read())
            fin.close()
            fout.close()
        else:
            if copy:
                dstpath = "%s/%s" % (directory, testpkg)
                shutil.copy(path, dstpath)
            else:
                dstpath = path
        if extract:
            xenrt.util.command("tar -zxf %s -C %s" % (dstpath, directory))

#############################################################################

# Import all symbols from this package to our namespace. This is only
# for users of this package - internal references are to the submodules
from xenrt.enum import *
import xenrt.interfaces
from xenrt.resources import *
from xenrt.grub import *
from xenrt.legacy import *
from xenrt.tctemplates import *
from xenrt.powerctl import *
from xenrt.pxeboot import *
from xenrt.rootops import *
from xenrt.ssh import *
from xenrt.util import *
from xenrt.registry import *
from xenrt.objects import *
from xenrt.config import *
from xenrt.seq import *
from xenrt.results import *
from xenrt.formatter import *
from xenrt.filemanager import *
from xenrt.dbconnect import *
from xenrt.jiralink import *
from xenrt.filecache import *
from xenrt.tools import *
from xenrt.suite import *
from xenrt.lazylog import *
from xenrt.ssl import *
from xenrt.storageadmin import *
from xenrt.racktableslink import *
from xenrt.archive import *
from xenrt.txt import *
from xenrt.stringutils import *
from xenrt.virtualmedia import *
