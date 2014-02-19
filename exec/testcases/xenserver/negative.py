#
# XenRT: Test harness for Xen and the XenServer product family
#
# XenServer negative test cases (i.e. check things error when expected)
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import string, time, re
import xenrt, xenrt.lib.xenserver, xenrt.lib.xenserver.cli
from tc.cc import _CCSetup

# ------------------------
# Memory related testcases
# ------------------------

class TCmoremem(xenrt.TestCaseWrapper):
    """Set a guest to have more memory than available and try to start it"""

    def __init__(self, tcid="TCmoremem"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="moremem")

    def run(self, arglist=None):

        # arg0 = guest, arg1 (optional) = amount of memory to add
        addmem = 100
        gname = None

        # Get the guest
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            if l[0] == "addmem":
                addmem = int(l[1])
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:    
            raise xenrt.XRTError("No guest name specified")
        guest = self.getGuest(gname)
        host = guest.host
        
        # Check it's not running
        if guest.getState() == "UP":
            guest.shutdown()

        # Sleep just over a minute to allow memory-free to be recalculated 
        # (it's done once a minute)
        time.sleep(75)

        maxmem = host.getMaxMemory()

        # Set memory
        guest.memset(maxmem+addmem)
        xenrt.TEC().comment("Set guest memory to %d MB" % (maxmem+addmem))

        # Try to start the guest            
        started = True
        try:
            guest.start()
        except xenrt.XRTFailure, e:
            r = re.search(r"^Error code: (\S+)", e.data, re.MULTILINE)
            if r == None or r.group(1) != "NOT_ENOUGH_MEMORY":
                xenrt.TEC().comment("Expected XRTFailure exception with " +
                                    "unexpected data when attempting to " +
                                    "boot guest with too much memory: " + 
                                    e.data)
                self.setResult(xenrt.RESULT_PARTIAL)
            else:
                # This would get raised if the guest failed to boot, as expected
                xenrt.TEC().comment("Expected " + r.group(1) + " exception " +
                                    "when attempting to boot guest with too " +
                                    "much memory")
            
            started = False

        if started:
            xenrt.TEC().comment("Guest booted with memory level at %d MB" % 
                                (guest.memget()))
            raise xenrt.XRTFailure("Guest booted successfully with more " +
                                   "memory than available!")

class TCzeromem(xenrt.TestCaseWrapper):
    """Try and set a guest to have 0 memory"""

    def __init__(self, tcid="TCzeromem"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="zeromem")

    def run(self, arglist=None):

        # arg0 = guest
        gname = None

        # Get the guest
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("No guest name specified")
        guest = self.getGuest(gname)

        # Check it's not running
        if guest.getState() == "UP":
            guest.shutdown()

        allowed = True
        # Set memory to 0
        try:
            guest.memset(0)
            xenrt.TEC().comment("Set guest memory to 0 MB")
        except xenrt.XRTException, e:
            allowed = False
            xenrt.TEC().comment("Expected XRTException when attempting to " +
                                "set memory to 0: " + str(e.data))

        # If it worked, now lets try starting it
        if allowed:
            xenrt.TEC().comment("Setting memory to 0 was allowed!")
            started = True
            try:
                guest.start()
            except xenrt.XRTFailure, e:
                r = re.search(r"^Error code: (\S+)", e.data, re.MULTILINE)
                if r == None or r.group(1) != "VM_MEMORY_SIZE_TOO_LOW":
                    xenrt.TEC().comment("Expected XRTFailure exception with " +
                                        "unexpected data while attempting " +
                                        "to boot guest with 0 memory: " + 
                                        e.data)
                else:
                    xenrt.TEC().comment("Expected " + r.group(1) + 
                                        " exception when attempting to boot " +
                                        "guest with 0 memory")
                started = False
                # This is a partial pass - we expected not to be allowed to
                # specify 0MB
                self.setResult(xenrt.RESULT_PARTIAL)

            if started:
                xenrt.TEC().comment("Guest booted with memory level at %d MB" %
                                    (guest.memget()))
                raise xenrt.XRTFailure("Guest booted successfully with " +
                                       "memory set to 0!")


# ----------------------
# vCPU related testcases
# ----------------------

class TCzerovcpus(xenrt.TestCaseWrapper):
    """Try and set guest vCPUs to 0"""

    def __init__(self, tcid="TCzerovcpus"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="zerovcpus")

    def run(self, arglist=None):

        # arg0 = guest
        gname = None

        # Get the guest
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("No guest name specified")
        guest = self.getGuest(gname)

        # Check it's not running
        if guest.getState() == "UP":
            guest.shutdown()

        allowed = True
        # Set vCPUs to 0
        try:
            guest.cpuset(0)
        except xenrt.XRTFailure, e:
            xenrt.TEC().comment("Expected XRTFailure exception when " +
                                "attempting to set vCPUs to 0: " + e.data)
            allowed = False
        
        # If it was allowed, try starting the guest
        if allowed:
            xenrt.TEC().comment("Setting vCPUs to 0 was allowed!")
            started = True
            try:
                guest.start()
            except xenrt.XRTFailure, e:
                if e.data.startswith("You need at least 1 VCPU to start a VM"):
                    xenrt.TEC().comment("Expected required VCPU exception " +
                                        "while attempting to boot guest with " +
                                        "with 0 vCPUs")
                else:
                    xenrt.TEC().comment("Expected XRTFailure exception with " +
                                        "unexpected data while attempting " +
                                        "to boot guest with 0 vCPUs: " +
                                        e.data)
                started = False
                # This is a partial pass - we expected not to be allowed to
                # specify 0 vCPUS
                self.setResult(xenrt.RESULT_PARTIAL)


            if started:
                xenrt.TEC().comment("Guest booted with %d vCPUs" % 
                                    (guest.cpuget()))
                raise xenrt.XRTFailure("Guest booted successfully with vCPUs " +
                                       "set to 0!")

class TCremoveVCPUs(xenrt.TestCaseWrapper):
    """Try and hotplug away all vCPUs of a guest"""

    def __init__(self, tcid="TCremoveVCPUs"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="removeVCPUs")

    def run(self, arglist=None):

        # arg0 = guest
        gname = None

        # Get the guest
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("No guest name specified")

        guest = self.getGuest(gname)

        # Check it's running
        if guest.getState() != "UP":
            guest.start()

        # Try the operation...
        allowed = True
        try:
            guest.cpuset(0,True)
        except xenrt.XRTFailure, e:
            xenrt.TEC().comment("Expected XRTFailure exception when " +
                                "attempting to set vCPUs to 0 on running " +
                                "guest: " + e.data)
            allowed = False

        if allowed:
            xenrt.TEC().comment("Guest now %s, vCPUs: %d" % 
                                (guest.getState(),guest.cpuget()))
            raise xenrt.XRTFailure("Allowed to set vCPUs to 0 on live guest!")

# ---------------------------
# Lifecycle related testcases
# ---------------------------

class TCstartStarted(xenrt.TestCaseWrapper):
    """Try and start an already running guest"""

    def __init__(self, tcid="TCstartStarted"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="startStarted")

    def run(self,arglist=None):

        # arg0 = guest
        gname = None

        # Get the guest
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("No guest name specified")

        guest = self.getGuest(gname)

        # Check guest is running
        if guest.getState() == "DOWN":
            guest.start()
            time.sleep(300)
        if guest.getState() == "SUSPENDED":
            guest.resume()

        # Now call start again
        allowed = True
        try:
            guest.start()
        except xenrt.XRTFailure, e:
            allowed = False
            # Check it's the exception we expect
            if e.data.startswith("You attempted an operation on a VM that " +
                                 "was not in an appropriate power state at " +
                                 "the time"):
                xenrt.TEC().comment("Expected bad power state exception when " +
                                    "attempting to start running guest")
            else:
                raise xenrt.XRTFailure("Unexpected XRTFailure exception " +
                                       "when attempting to start running " +
                                       "guest: " + e.data)

        if allowed:
            raise xenrt.XRTFailure("Start succeeded on running guest, guest " +
                                   "now: " + guest.getState())

class TCshutdownStopped(xenrt.TestCaseWrapper):
    """Try and stop an already stopped guest"""

    def __init__(self, tcid="TCshutdownStopped"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="shutdownStopped")

    def run(self,arglist=None):

        # arg0 = guest
        gname = None

        # Get the guest
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("No guest name specified")

        guest = self.getGuest(gname)

        # Check guest is halted
        if guest.getState() == "UP":
            guest.shutdown()
        if guest.getState() == "SUSPENDED":
            guest.resume()
            guest.shutdown()

        # Now call stop again
        allowed = True
        try:
            guest.shutdown()
        except xenrt.XRTFailure, e:
            allowed = False
            # Check it's the exception we expect
            if e.data.startswith("You attempted an operation on a VM that " +
                                 "was not in an appropriate power state at " +
                                 "the time"):
                xenrt.TEC().comment("Expected bad power state exception when " +
                                    "attempting to shutdown stopped guest")
            else:
                raise xenrt.XRTFailure("Unexpected XRTFailure exception " +
                                       "when attempting to shutdown stopped " +
                                       "guest: " + e.data)

        if allowed:
            raise xenrt.XRTFailure("Shutdown succeeded on halted guest, " +
                                   "guest now: " + guest.getState())


class TCrebootStopped(xenrt.TestCaseWrapper):
    """Try and reboot a halted guest"""

    def __init__(self, tcid="TCrebootStopped"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="rebootStopped")

    def run(self,arglist=None):
        # arg0 = guest
        gname = None

        # Get the guest
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("No guest name specified")

        guest = self.getGuest(gname)

        # Check guest is stopped
        if guest.getState() == "UP":
            guest.shutdown()
        if guest.getState() == "SUSPENDED":
            guest.resume()
            guest.shutdown()

        # Now call reboot
        allowed = True
        try:
            guest.lifecycleOperation("vm-reboot")
        except xenrt.XRTFailure, e:
            allowed = False
            # Check it's the exception we expect
            if e.data.startswith("You attempted an operation on a VM that " +
                                 "was not in an appropriate power state at " +
                                 "the time"):
                xenrt.TEC().comment("Expected bad power state exception when " +
                                    "attempting to reboot stopped guest")
            else:
                raise xenrt.XRTFailure("Unexpected XRTFailure exception " +
                                       "when attempting to reboot stopped " +
                                       "guest: " + e.data)

        if allowed:
            raise xenrt.XRTFailure("Reboot succeeded on halted guest, guest " +
                                   "now: " + guest.getState())

class TCresumeStarted(xenrt.TestCaseWrapper):
    """Try and resume a guest that hasn't been suspended"""

    def __init__(self, tcid="TCresumeStarted"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="resumeStarted")

    def run(self,arglist=None):

        # arg0 = guest
        gname = None

        # Get the guest
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("No guest name specified")

        guest = self.getGuest(gname)

        # Check guest is running
        if guest.getState() == "DOWN":
            guest.start()
            time.sleep(300)
        if guest.getState() == "SUSPENDED":
            guest.resume()

        # Now call resume
        allowed = True
        try:
            guest.lifecycleOperation("vm-resume")
        except xenrt.XRTFailure, e:
            allowed = False
            # Check it's the exception we expect
            if e.data.startswith("You attempted an operation on a VM that " +
                                 "was not in an appropriate power state at " +
                                 "the time"):
                xenrt.TEC().comment("Expected bad power state exception when " +
                                    "attempting to resume running guest")
            else:
                raise xenrt.XRTFailure("Unexpected XRTFailure exception " +
                                       "when attempting to resume running " +
                                       "guest: " + e.data)

        if allowed:
            raise xenrt.XRTFailure("Resume succeeded on up guest, guest " +
                                   "now: " + guest.getState())

class TCresumeStopped(xenrt.TestCaseWrapper):
    """Try and resume a halted guest"""

    def __init__(self, tcid="TCresumeStopped"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="resumeStopped")
    def run(self,arglist=None):

        # arg0 = guest
        gname = None

        # Get the guest
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("No guest name specified")

        guest = self.getGuest(gname)

        # Check guest isn't running
        if guest.getState() == "UP":
            guest.shutdown()
        if guest.getState() == "SUSPENDED":
            guest.resume()
            guest.shutdown()

        # Now call resume
        allowed = True
        try:
            guest.lifecycleOperation("vm-resume")
        except xenrt.XRTFailure, e:
            allowed = False
            # Check it's the exception we expect
            if e.data.startswith("You attempted an operation on a VM that " +
                                 "was not in an appropriate power state at " +
                                 "the time"):
                xenrt.TEC().comment("Expected bad power state exception when " +
                                    "attempting to resume stopped guest")
            else:
                raise xenrt.XRTFailure("Unexpected XRTFailure exception " +
                                       "when attempting to resume stopped " +
                                       "guest: " + e.data)

        if allowed:
            raise xenrt.XRTFailure("Resume succeeded on halted guest, guest " +
                                   "now: " + guest.getState())

class TCsuspendmigrateStopped(xenrt.TestCaseWrapper):
    """Try and suspend/migrate a guest that is already halted"""

    def __init__(self, tcid="TCsuspendmigrateStopped"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="suspendmigrateStopped")

    def run(self,arglist=None):

        # arg0 = guest
        gname = None

        # Get the guest
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("No guest name specified")

        guest = self.getGuest(gname)
        host = guest.host
    
        # Check guest is halted
        if guest.getState() == "UP":
            guest.shutdown()
        if guest.getState() == "SUSPENDED":
            guest.resume()
            guest.shutdown()

        allowed = True    
        try:
            guest.suspend()            
        except xenrt.XRTFailure, e:
            allowed = False
            # Check it's the exception we expect
            if e.data.startswith("You attempted an operation on a VM that " +
                                 "was not in an appropriate power state at " +
                                 "the time"):
                xenrt.TEC().comment("Expected bad power state exception when " +
                                    "attempting to suspend stopped guest")
            else:
                raise xenrt.XRTFailure("Unexpected XRTFailure exception " +
                                       "when attempting to suspend stopped " +
                                       "guest: " + e.data)

        if allowed:
            raise xenrt.XRTFailure("Suspend allowed on stopped guest, guest " +
                                   "now: " + guest.getState())

        allowed = True
        try:            
            guest.migrateVM(host,fast=True)
        except xenrt.XRTFailure, e:
            allowed = False
            # Check it's the exception we expect
            if e.data.startswith("You attempted an operation on a VM that " +
                                 "was not in an appropriate power state at " +
                                 "the time"):
                xenrt.TEC().comment("Expected bad power state exception when " +
                                    "attempting to migrate stopped guest")
            else:
                raise xenrt.XRTFailure("Unexpected XRTFailure exception " +
                                       "when attempting to migrate stopped " +
                                       "guest: " + e.data)

        if allowed:
            xenrt.TEC().reason("Migrate allowed on stopped guest, guest now: " +
                               guest.getState())
            self.setResult(xenrt.RESULT_PARTIAL) 
                                   

class TCstartSuspended(xenrt.TestCaseWrapper):
    """Try and start a suspended guest"""

    def __init__(self, tcid="TCstartSuspended"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="startSuspended")
    def run(self,arglist=None):

        # arg0 = guest
        gname = None

        # Get the guest
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("No guest name specified")

        guest = self.getGuest(gname)

        # Check guest is suspended
        if guest.getState() == "UP":
            guest.suspend()
        if guest.getState() == "DOWN":
            guest.start()
            time.sleep(300)
            guest.suspend()

        # Now call start
        allowed = True
        try:
            guest.lifecycleOperation("vm-start")
        except xenrt.XRTFailure, e:
            allowed = False
            # Check it's the exception we expect
            if e.data.startswith("You attempted an operation on a VM that " +
                                 "was not in an appropriate power state at " +
                                 "the time"):
                xenrt.TEC().comment("Expected bad power state exception when " +
                                    "attempting to start suspended guest")
            else:
                raise xenrt.XRTFailure("Unexpected XRTFailure exception " +
                                       "when attempting to start suspended " +
                                       "guest: " + e.data)

        if allowed:
            raise xenrt.XRTFailure("Start succeeded on suspended guest, " +
                                   "guest now: " + guest.getState())


class TCshutdownSuspended(xenrt.TestCaseWrapper):
    """Try and stop a suspended guest"""

    def __init__(self, tcid="TCshutdownSuspended"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="shutdownSuspended")
    def run(self,arglist=None):

        # arg0 = guest
        gname = None

        # Get the guest
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("No guest name specified")

        guest = self.getGuest(gname)

        # Check guest is suspended
        if guest.getState() == "UP":
            guest.suspend()
        if guest.getState() == "DOWN":
            guest.start()
            time.sleep(300)
            guest.suspend()

        # Now call shutdown
        allowed = True
        try:
            guest.lifecycleOperation("vm-shutdown")
        except xenrt.XRTFailure, e:
            allowed = False
            # Check it's the exception we expect
            if e.data.startswith("You attempted an operation on a VM that " +
                                 "was not in an appropriate power state at " +
                                 "the time"):
                xenrt.TEC().comment("Expected bad power state exception when " +
                                    "attempting to shutdown suspended guest")
            else:
                raise xenrt.XRTFailure("Unexpected XRTFailure exception " +
                                       "when attempting to shutdown suspended " +
                                       "guest: " + e.data)

        if allowed:
            raise xenrt.XRTFailure("Stop succeeded on suspended guest, " +
                                   "guest now: " + guest.getState())


class TCsuspendSuspended(xenrt.TestCaseWrapper):
    """Try and suspend a suspended guest"""

    def __init__(self, tcid="TCsuspendSuspended"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="suspendSuspended")
    def run(self,arglist=None):

        # arg0 = guest
        gname = None

        # Get the guest
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("No guest name specified")

        guest = self.getGuest(gname)

        # Check guest is suspended
        if guest.getState() == "UP":
            guest.suspend()
        if guest.getState() == "DOWN":
            guest.start()
            time.sleep(300)
            guest.suspend()

        # Now call shutdown
        allowed = True
        try:
            guest.lifecycleOperation("vm-suspend")
        except xenrt.XRTFailure, e:
            allowed = False
            # Check it's the exception we expect
            if e.data.startswith("You attempted an operation on a VM that " +
                                 "was not in an appropriate power state at " +
                                 "the time"):
                xenrt.TEC().comment("Expected bad power state exception when " +
                                    "attempting to suspend suspended guest")
            else:
                raise xenrt.XRTFailure("Unexpected XRTFailure exception " +
                                       "when attempting to suspend suspended " +
                                       "guest: " + e.data)

        if allowed:
            raise xenrt.XRTFailure("Suspend succeeded on suspended guest, " +
                                   "guest now: " + guest.getState())



# -----------------
# General testcases
# -----------------

class TCmissingISO(xenrt.TestCaseWrapper):
    """Try and load a non-existent ISO into a guest"""

    def __init__(self, tcid="TCmissingISO"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="missingISO")

    def run(self,arglist=None):

        # arg0 = guest
        gname = None

        # Get the guest
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("No guest name specified")

        guest = self.getGuest(gname)

        # change to doesnotexist.iso
        allowed = True
        try:
            guest.changeCD("doesnotexist.iso")
        except xenrt.XRTFailure, e:
            allowed = False
            if e.data.strip() == "Error: CD doesnotexist.iso not found!":
                xenrt.TEC().comment("Expected CD not found error when " +
                                    "loading non-existent ISO")
            else:
                xenrt.TEC().comment("Expected XRTFailure exception with " +
                                    "unexpected content when loading " +
                                    "non-existent ISO: " + e.data)

        if allowed:
            raise xenrt.XRTFailure("Loading non-existent ISO succeeded with " +
                                   "no error!")          

class TCvdionreadonly(xenrt.TestCaseWrapper):
    """Try and create a virtual disk on a read-only storage repository"""

    def __init__(self, tcid="TCvdionreadonly"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="vdionreadonly")   

    def run(self,arglist=None):

        # arg0 = host

        if arglist and len(arglist) > 0:
            hname = arglist[0]
        else:
            raise xenrt.XRTError("No host specified")
        host = xenrt.TEC().registry.hostGet(hname)

        # Find an appropriate SR (the XenSource Tools one will do)
        SRs = host.getSRs(type="iso")
        XSTsr = None
        for sr in SRs:
            # Get the name
            name = host.getSRParam(sr,"name-label")
            if name == "XenSource Tools":
                XSTsr = sr
                break
            elif name == "XenServer Tools":
                XSTsr = sr
                break
        if XSTsr == None:
            raise xenrt.XRTError("Unable to find XenSource Tools SR!")

        # Now try the create
        cli = host.getCLIInstance()
        
        allowed = True
        try:
            args = ["sr-uuid=\"%s\"" % (XSTsr), 
                    "name-label=\"shouldnt_be_created\"", "type=\"user\"", 
                    "virtual-size=\"1000000\""]
            cli.execute("vdi-create",string.join(args))
        except xenrt.XRTFailure, e:
            allowed = False
            # Check we get the correct error
            if e.data.startswith("The SR backend does not support the " +
                                 "operation (check the SR's allowed " +
                                 "operations)"):
                xenrt.TEC().comment("Expected not supported exception when " +
                                    "attempting to create vdi on read-only " +
                                    "storage repository.")
            else:
                xenrt.TEC().comment("Expected XRTFailure exception when " +
                                    "attempting to create vdi on read-only " +
                                    "storage repository, with unexpected " +
                                    "data: " + e.data)
                self.setResult(xenrt.RESULT_PARTIAL)

        if allowed:
            raise xenrt.XRTFailure("Allowed to create VDI on read-only " +
                                   "storage repository!")

class TCincorrectPassword(_CCSetup):
    """Try a CLI command with an incorrect password"""
    LICENSE_SERVER_REQUIRED = False

    def run(self,arglist=None):

        # arg0 = host

        if arglist and len(arglist) > 0:
            hname = arglist[0]
        else:
            raise xenrt.XRTError("No host specified")
        host = xenrt.TEC().registry.hostGet(hname)
        machine = host.machine

        cli = xenrt.lib.xenserver.cli.Session(machine, password="incorrect")

        allowed = True

        try:
            cli.execute("vm-list")
        except xenrt.XRTFailure, e:
            allowed = False
            if e.data.startswith("Authentication failed"):
                xenrt.TEC().comment("Expected Authentication failed error " +
                                    "when executing a CLI command with an " +
                                    "invalid password")
            else:
                self.setResult(xenrt.RESULT_PARTIAL)
                xenrt.TEC().comment("Expected XRTFailure exception with " +
                                    "unexpected data when executing a CLI " +
                                    "command with an invalid password: " +
                                    e.data)

        if allowed:
            raise xenrt.XRTFailure("Allowed to execute CLI command with an " +
                                   "invalid password!")

class TCinvalidTemplate(xenrt.TestCaseWrapper):
    """Try and install a guest with an invalid template"""

    def __init__(self, tcid="TCinvalidTemplate"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="invalidTemplate")

    def run(self,arglist=None):

        # arg0 = host

        if arglist and len(arglist) > 0:
            hname = arglist[0]
        else:
            raise xenrt.XRTError("No host specified")
        host = xenrt.TEC().registry.hostGet(hname)

        # Build up command
        cmd = "vm-install"
        args = ["new-name-label=invalidTemplateTest", "template=nonexistent_template"]

        cli = host.getCLIInstance()

        allowed = True

        try:        
            uuid = cli.execute(cmd,string.join(args)) 
        except xenrt.XRTFailure, e: 
            allowed = False
            if e.data.startswith("Error: No templates matched"):
                xenrt.TEC().comment("Expected error when attempting to " +
                                    "install a VM from an invalid template")
            else:
                self.setResult(xenrt.RESULT_PARTIAL)
                xenrt.TEC().comment("Expected XRTFailure exception with " +
                                    "unexpected data when attempting to " +
                                    "install a VM from an invalid template: " +
                                    e.data)

        if allowed:
            raise xenrt.XRTFailure("Allowed to install a guest from an " +
                                   "invalid template, guest UUID: " + uuid)

