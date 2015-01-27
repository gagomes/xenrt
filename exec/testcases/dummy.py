#
# XenRT: Test harness for Xen and the XenServer product family
#
# Dummy test cases for harness test and development
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, time, glob
import threading
import xenrt

class TCDummySleep(xenrt.TestCase):
    def __init__(self):
        xenrt.TestCase.__init__(self, "TCDummySleep")
        self.blocker = True

    def f(self, t, fail):
        xenrt.TEC().progress("Sleeping for %u seconds" % (t))
        xenrt.TEC().comment("Sleeping for %u seconds" % (t))
        xenrt.TEC().appresult("Sleeping for %u seconds" % (t))
        time.sleep(t)
        if fail:
            raise xenrt.XRTFailure("I was asked to fail")
        xenrt.TEC().value("Duration", t)

    def run(self, arglist=None):
        fail = False
        if arglist and len(arglist) > 0:
            t = int(arglist[0])
        else:
            t = 5
        if len(arglist) > 1:
            fail = arglist[1]
        xenrt.TEC().logverbose("About to run subcases...")
        
        self.runSubcase("f", (t, False), None, "A")
        self.runSubcase("f", (t, fail), None, "B")

class TCSleep(xenrt.TestCase):
    def __init__(self):
        xenrt.TestCase.__init__(self, "TCSleep")

    def run(self, arglist=None):
        if arglist and len(arglist) > 0:
            t = int(arglist[0])
        else:
            t = 5
        xenrt.TEC().logverbose("Sleeping for %u seconds..." % (t))
        time.sleep(t)
        if arglist and len(arglist) > 1 and arglist[1] == 'fail':
            raise xenrt.XRTFailure("Failing on command")

class TCDummyPerf(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCDummyPerf"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="dummy")

    def run(self, arglist=None):
        xenrt.TEC().logverbose("About to record perf results...")
        self.tec.value("TX", 1.23)
        self.tec.value("RX", 4.23, "MB/s")

class TCFail(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCFail"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="fail")

    def run(self, arglist=None):
        xenrt.TEC().logverbose("About to fail...")
        raise xenrt.XRTFailure("It's what I do...")

class TCError(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCError"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="error")

    def run(self, arglist=None):
        xenrt.TEC().logverbose("About to error...")
        raise xenrt.XRTError("It's what I do...")

class TCSkip(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCSkip"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="skip")

    def run(self, arglist=None):
        xenrt.TEC().logverbose("About to skip...")
        xenrt.TEC().skip("It's what I do...")
        return

class TCPause(xenrt.TestCase):

    def run(self, arglist=None):
        xenrt.TEC().logverbose("About to pause...")
        self.pause("It's what I do...")

class TCSubcaseFail(xenrt.TestCase):
    SUBCASE_TICKETS=True
    def run(self, arglist=None):
        xenrt.TEC().logverbose("Running subcases")
        self.testcaseResult("Group1", "test_1", xenrt.RESULT_PASS)
        self.testcaseResult("Group1", "test_2", xenrt.RESULT_FAIL, "tc2 failed")
        self.testcaseResult("Group2", "test_3", xenrt.RESULT_FAIL)
        self.testcaseResult("Group2", "test_4", xenrt.RESULT_ERROR, "tc4 errored")

        logdir = xenrt.TEC().getLogdir()

        with open("%s/testlog.log" % logdir, "w") as f:
            f.write("Extra log for Jira\n")

    def ticketAttachments(self):
        logdir = xenrt.TEC().getLogdir()
        return glob.glob("%s/test*.log" % logdir)

    def ticketAssignee(self):
        return "johndi"

class TCThread(xenrt.TestCase):
    def run(self, arglist=None):
        xenrt.TEC().logverbose("This is logged from the testcase body (%s)" %
                               (threading.currentThread().getName()))
        t = _Thread()
        t.start()
        t.join()
        
class _Thread(xenrt.XRTThread):

    def run(self):
        xenrt.TEC().logverbose("This is logged from the thread (%s)" %
                               (threading.currentThread().getName()))
        
