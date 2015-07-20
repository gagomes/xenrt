#
# XenRT: Test harness for Xen and the XenServer product family
#
# xsconsole standalone testcases
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import time, re
import xenrt


class _Authenticate(xenrt.TestCase):
    """Base class for testing xsconsole authentication functions."""
    
    def authenticated(self):
        self.xsc.activate("CHANGE_PASSWORD")
        data = self.xsc.screengrab()
        self.xsc.reset()
        if re.search("Please log in", data): return False
        else: return True
    
    def changepassword(self, newpassword):
        oldpassword = self.host.password
        # Change the password.
        self.xsc.activate("CHANGE_PASSWORD")
        # Enter the old password.
        for x in list(oldpassword): self.xsc.keypress(x)
        self.xsc.keypress("KEY_ENTER")
        # Enter the new password twice.
        for x in list(newpassword): self.xsc.keypress(x)
        self.xsc.keypress("KEY_ENTER")
        for x in list(newpassword): self.xsc.keypress(x)
        self.xsc.keypress("KEY_ENTER")
        try: 
            self.host.password = newpassword
            data = self.xsc.screengrab()
        except xenrt.XRTFailure, e:
            self.host.password = oldpassword
            data = self.xsc.screengrab()
        self.xsc.keypress("KEY_ENTER")
        return data

    def getLogoutTimeout(self):
        self.xsc.activate("CHANGE_TIMEOUT")
        data = self.xsc.screengrab()
        data = data.replace("[[", "")
        data = data.replace("]]", "")
        data = data.strip()
        self.xsc.reset()
        return int(re.search("Timeout\s+\(minutes\)\s+(?P<timeout>[0-9]+)", 
                              data).group("timeout"))

    def setLogoutTimeout(self, minutes):
        self.xsc.activate("CHANGE_TIMEOUT")
        for x in list(str(minutes)): self.xsc.keypress(x)
        self.xsc.keypress("KEY_ENTER")
        data = self.xsc.screengrab()
        self.xsc.keypress("KEY_ENTER")
        return data 

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.xsc = self.host.getXSConsoleInstance()
        if self.authenticated():
            self.xsc.activate("LOGINOUT")
            self.xsc.reset()

class TC8324(_Authenticate):
    """Test changing the authentication timeout."""

    def run(self, arglist):
        times = [1,5]
        self.xsc.authenticate()        
        
        self.originaltimeout = self.getLogoutTimeout()
        xenrt.TEC().logverbose("Current auto-logout timeout is %s minutes." % 
                               (self.originaltimeout))
        for t in times:        
            xenrt.TEC().logverbose("Testing a timeout of %s minutes." % (t))
            self.xsc.authenticate()
            data = self.setLogoutTimeout(t)
            if not re.search("Timeout Change Successful", data):
                raise xenrt.XRTFailure("Unexpected response from xsconsole: %s" % (data))
            self.xsc.authenticate()
            if not self.authenticated():
                raise xenrt.XRTFailure("Not authenticated.")
            xenrt.TEC().logverbose("Waiting until just before timeout expires.")
            time.sleep(t*60-30)
            if not self.authenticated():
                raise xenrt.XRTFailure("Not authenticated near timeout expiry.")
            xenrt.TEC().logverbose("Waiting until timeout has expired.")
            time.sleep(60)
            if self.authenticated():
                raise xenrt.XRTFailure("Authenticated after timeout expiry.")

    def postRun(self):
        self.setLogoutTimeout(self.originaltimeout)

class TC8325(_Authenticate):
    """Test changing the password."""

    def run(self, arglist):
        self.savedpassword = self.host.password
        newpassword = "newpassword"
        shortpassword = "short" 

        # Try logging in with the wrong password.
        try: self.xsc.authenticate(password=newpassword) 
        except xenrt.XRTFailure, e:
            if not re.search("The system could not log you in.", str(e)):
                raise e
        # Log in.
        self.xsc.authenticate()
        data = self.changepassword(shortpassword) 
        if not re.search("New password is too short", data):
            raise xenrt.XRTFailure("XSConsole accepted a 5 letter password.")
        data = self.changepassword(newpassword)
        if not re.search("Password Change Successful", data):
            raise xenrt.XRTFailure("Password change failed.")
        # Try logging in with the old password.
        try: self.xsc.authenticate(password=self.savedpassword) 
        except xenrt.XRTFailure, e:
            if not re.search("The system could not log you in.", str(e)):
                raise e
        # Try logging in with the new password.
        self.xsc.authenticate()

    def postRun(self):
        self.changepassword(self.savedpassword)

class TC8326(_Authenticate):
    """Test logging in and logging out."""

    def run(self, arglist):
        self.xsc.activate("LOGINOUT")
        # Move to the password entry field.
        self.xsc.keypress("KEY_ENTER")
        # Enter the password.
        for x in self.host.password: self.xsc.keypress(x)
        # Log in.
        self.xsc.keypress("KEY_ENTER")
        data = self.xsc.screengrab()
        # Dismiss the success dialog.
        self.xsc.keypress("KEY_ENTER")
        self.xsc.check()
        if not re.search("Login Successful", data):
            raise xenrt.XRTFailure("Got an unexpected login response.")
        if not self.authenticated():
            raise xenrt.XRTFailure("Login failed.")
        # Log out.
        self.xsc.activate("LOGINOUT")
        data = self.xsc.screengrab()
        # Dismiss the success dialog.
        self.xsc.keypress("KEY_ENTER")
        self.xsc.check()
        if not re.search("logged out", data):
            raise xenrt.XRTFailure("Got unexpected logout response.")
        if self.authenticated():
            raise xenrt.XRTFailure("Logout failed.")

class TC8315(xenrt.TestCase):
    """Reboot a host using xsconsole."""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()

    def run(self, arglist):
        uptime = re.search("(?P<up>[0-9\.]+)\s+(?P<idle>[0-9\.]+)",
                            self.host.execdom0("cat /proc/uptime")).group("up")
        xenrt.TEC().logverbose("Uptime before reboot is %s seconds." % (uptime))

        xsc = self.host.getXSConsoleInstance()
        xsc.authenticate()
        xsc.activate("REBOOT")
        xsc.keypress("KEY_F(8)")

        time.sleep(60)
        self.host.waitForSSH(600)

        newuptime = re.search("(?P<up>[0-9]+)\s+(?P<idle>[0-9]+)",
                               self.host.execdom0("cat /proc/uptime")).group("up")
        xenrt.TEC().logverbose("Uptime after reboot is %s seconds." % (newuptime))
        if int(float(uptime)) < int(float(newuptime)):
            raise xenrt.XRTFailure("It doesn't look like the host rebooted.")
        time.sleep(60)
