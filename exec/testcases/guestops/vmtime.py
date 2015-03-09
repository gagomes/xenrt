#
# XenRT: Test harness for Xen and the XenServer product family
#
# Testcases for guest time operations
#
# Copyright (c) Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import sys, string, time
import xenrt

class _TCGuestTime(xenrt.TestCase):
    """Verify guest time is unchanged following a lifecycle operation"""

    # After we tweak the VM's clock how fast is it compared to the host
    # (w.r.t. seconds since epoch)
    # EXPDIFF is positive if the VM's clock is ahead
    EXPDIFF = 0

    def provideGuest(self, arglist):
        
        # Mandatory args.
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
        if not gname:
            raise xenrt.XRTError("No guest name specified")

        guest = self.getGuest(gname)
        if not guest:
            raise xenrt.XRTError("Could not find guest %s in registry" %
                                 (gname))
        return guest
    
    def prepare(self, arglist=None):
        self.guest = None
        self.host = None
        self.iwc = None

        self.guest = self.provideGuest(arglist)
        self.host = self.guest.host

        # Make sure the guest has a fresh boot
        if self.guest.getState() == "UP":
            self.guest.shutdown()
        self.guest.start()

        # Record the current guest timezone so we can go back to it in postRun
        # TODO
        if not self.guest.windows and \
               self.guest.execcmd(\
            "test -e /proc/sys/xen/independent_wallclock", retval="code") == 0:
            self.iwc = self.guest.execcmd(\
                "cat /proc/sys/xen/independent_wallclock").strip()

        # Put the guest clock into the state we want
        xenrt.TEC().logverbose("Tweaking the guest time settings")
        self.doGuestTimePrepare()

        # Check the difference before we start
        time.sleep(60)
        xenrt.TEC().logverbose("Checking the guest time offset before the "
                               "test commences")
        self.doHostCheck()

    def doGuestTimePrepare(self):
        raise xenrt.XRTError("Unimplemented")

    def doOperation(self):
        raise xenrt.XRTError("Unimplemented")

    def doHostCheck(self):
        # Read seconds since the epoch
        hosttime = self.host.getTime()
        guesttime = self.guest.getTime()
        delta = abs(guesttime - self.EXPDIFF - hosttime)
        if delta > 60:
            # (Allow a bit of time for the non-atomic lookups etc.)
            raise xenrt.XRTFailure(\
                "Difference between guest and host clock not as expected",
                "Guest time %u, host %u, expdiff %d" %
                (guesttime, hosttime, self.EXPDIFF))

    def run(self, arglist=None):
        
        # Do the operation
        if self.runSubcase("doOperation", (), "VM", "Op") != \
               xenrt.RESULT_PASS:
            return
        
        time.sleep(60)
        
        # Check the clock offset
        if self.runSubcase("doHostCheck", (), "VMClock", "AfterOp")!= \
               xenrt.RESULT_PASS:
            return

        # Wait a bit and re-check
        time.sleep(60)
        self.runSubcase("doHostCheck", (), "VMClock", "Later")

    def postRun(self):
        # Put the guest timezones back
        # TODO

        # Set the guest clock to the correct time
        self.guest.setTime(xenrt.timenow())
        if not self.guest.windows:
            try:
                self.guest.execcmd("/etc/init.d/ntpd start")
            except Exception, e:
                xenrt.TEC().logverbose("Exception starting ntpd: %s" %
                                       (str(e)))
            if self.iwc != None:
                self.guest.execcmd("echo %s > "
                                   "/proc/sys/xen/independent_wallclock" %
                                   (self.iwc))

class _GuestClockFast(object):

    EXPDIFF = 5000

    def __init__(self):
        self.guest= None

    def doGuestTimePrepare(self):
        if not self.guest.windows:
            # Turn off NTP if possible
            try:
                self.guest.execcmd("/etc/init.d/ntpd stop")
            except Exception, e:
                xenrt.TEC().logverbose("Exception stopping ntpd: %s" %
                                       (str(e)))
            # Let the clock free run
            try:
                self.guest.execcmd("echo 1 > "
                                   "/proc/sys/xen/independent_wallclock")
            except Exception, e:
                xenrt.TEC().logverbose("Exception setting "
                                       "independent_wallclock: %s" % (str(e)))
        else:
            try:
                self.guest.xmlrpcExec("sc stop w32time")
                self.guest.xmlrpcExec("w32tm /unregister")
            except Exception, e:
                xenrt.TEC().logverbose("Exception disabling w32time "
                                       "service: %s" % (str(e)))

        # Set the time to be EXPDIFF in the future
        self.guest.setTime(xenrt.timenow() + self.EXPDIFF)
            
class TCGuestTimeOffsetMig(_GuestClockFast,_TCGuestTime):
    """Verify guest time offset handling during migrate."""

    def __init__(self, tcid=None):
        _GuestClockFast.__init__(self)
        _TCGuestTime.__init__(self, tcid)
    
    def doOperation(self):
        self.guest.migrateVM(self.guest.host, live="true")


