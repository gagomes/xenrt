#
# XenRT: Test harness for Xen and the XenServer product family
#
# Automated versions of manual test cases.
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import time, re, string
import xenrt
from xenrt.lib.xenserver.context import *

class TC401(xenrt.TestCase):
    """Check files are writable."""

    FILES = ["/etc/ssh",
             "/etc/issue",
             "/etc/lvm",
             "/etc/hosts",
             "/etc/ntp.conf",
             "/etc/resolv.conf",
             "/tmp",
             "/var"]

    def prepare(self, arglist):
        self.host = self.getDefaultHost()

    def run(self, arglist):
        for f in self.FILES:
            entry = self.host.execdom0("ls -ld %s" % (f))
            if not entry[2] == "w":
                raise xenrt.XRTFailure("No write permissions for %s. (%s)" % (f, entry))       

class TC403(xenrt.TestCase):
    """Check processes are running."""

    PROCESSES = ["xenbus",
                 "xenwatch",
                 "xenconsoled",
                 "xenstored",
                 "xapi",
                 "sshd"]    

    def prepare(self, arglist):
        self.host = self.getDefaultHost()

    def run(self, arglist):
        for p in self.PROCESSES:
            self.host.execdom0("pgrep %s" % (p))

class TC555(xenrt.TestCase):
    """Upgrade host to the same version."""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()

    def run(self, arglist):
        self.host.upgrade()

class TC640(xenrt.TestCase):
    """Memory usage by the agent."""

    DURATION = 60*60*24
    GUESTS = 6    

    def getXAPIpmem(self):
        data = self.host.execdom0("ps axo comm,pmem | grep xapi")
        return sum(map(float, re.findall("[\d\.]+", data)))

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.guests = []
        for i in range(self.GUESTS):
            g = self.host.createGenericEmptyGuest()
            self.uninstallOnCleanup(g)
            self.guests.append(g)

    def run(self, arglist):
        initial = self.getXAPIpmem()
        xenrt.TEC().logverbose("Initial XAPI pmem: %s" % (initial))
        end = xenrt.timenow() + self.DURATION
        while xenrt.timenow() < end:
            current = self.getXAPIpmem()
            xenrt.TEC().logverbose("Current XAPI pmem: %s" % (current))
            if current/initial > 1.5:
                raise xenrt.XRTFailure("XAPI may be leaking memory.")
            time.sleep(30)

class TC647(xenrt.TestCase):
    """VM state after Power On failure"""

    MEMORY = 256

    def prepare(self, arglist):
        self.host = self.getDefaultHost()

    def run(self, arglist):
        self.guests = self.host.getFreeMemory()/self.MEMORY
        xenrt.TEC().comment("Trying to start %s guests." % (self.guests))
        for i in range(self.guests):
            xenrt.TEC().logverbose("Installing guest %s." % (i))
            guest = self.host.createGenericEmptyGuest(memory=self.MEMORY) 
            self.uninstallOnCleanup(guest)
            xenrt.TEC().logverbose("Starting guest %s." % (i))
            try:
                guest.start()
            except:
                state = guest.getState() 
                if not state == "DOWN":
                    raise xenrt.XRTFailure("Guest failed to start but is in "
                                           "incorrect state. (%s)" % (state))

class TC966(xenrt.TestCase):
    """Verification of license file"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()

    def run(self, arglist):
        self.host.execdom0("touch /root/notalicensefile")

        cli = self.host.getCLIInstance()
        args = []
        args.append("license-file=/root/notalicensefile")
        args.append("host-uuid=%s" % (self.host.getMyHostUUID())) 
        try:
            cli.execute("host-license-add", string.join(args))
        except xenrt.XRTFailure, e:
            if not re.search("Failed to read license file", e.reason):
                raise e
        else:       
            raise xenrt.XRTFailure("No error raised when adding invalid license file.")

    def postRun(self):
        self.host.execdom0("rm -f /root/notalicensefile")

class TC967(xenrt.TestCase):
    """Incorrect guest name / UUID"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()

    def run(self, arglist):
        cli = self.host.getCLIInstance()
        try:
            cli.execute("vm-start", "uuid=00000000-0000-0000-0000-000000000000")
        except xenrt.XRTFailure, e:
            if not re.search("No matching VMs found", e.reason):
                raise e
        else:       
            raise xenrt.XRTFailure("No error raised when passing invalid UUID.")
        
        try:
            cli.execute("vm-start", "vm=nosuchvm")
        except xenrt.XRTFailure, e:
            if not re.search("No matching VMs found", e.reason):
                raise e
        else:       
            raise xenrt.XRTFailure("No error raised when passing invalid name.")

class TC968(xenrt.TestCase):
    """Incorrect command option"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()

    def run(self, arglist):
        cli = self.host.getCLIInstance()
        try:
            cli.execute("vm-list", "-k")
        except xenrt.XRTFailure, e:
            if "Unknown switch" in e.reason or "Syntax error" in e.reason:
                xenrt.TEC().logverbose("CLI failed with expected reason: %s" % (e.reason))
            else:
                xenrt.TEC().logverbose("CLI failed with unexpected reason.")
                raise e
        else:
            raise xenrt.XRTFailure("No error raised when passing invalid argument.")
        
class TC1224(xenrt.TestCase):
    """Run host-bugreport-upload command on master"""

    def prepare(self, arglist):
        self.pool = self.getDefaultPool()

    def run(self, arglist=None):
        host = self.pool.master
        host.uploadBugReport()
        host.checkBugReport()

class TC1225(xenrt.TestCase):
    """Run host-bugreport-upload command on slave"""

    def prepare(self, arglist):
        self.pool = self.getDefaultPool()

    def run(self, arglist=None):
        host = self.pool.slaves.values()[0]
        host.uploadBugReport()
        host.checkBugReport()

class _PIFReconfigure(xenrt.TestCase):
    """Change the IP address of slave host in pool"""

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.target = None

    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        self.cli = self.pool.master.getCLIInstance(local=True)
 
    def run(self, arglist):
        self.pool.check()

        self.pif = self.target.getPIFUUID(self.target.getDefaultInterface())   

        data = self.target.execdom0("ifconfig %s" % (self.target.getPrimaryBridge()))
        ip = re.search("inet addr:([0-9\.]+)", data).group(1)
        netmask = re.search("Mask:([0-9\.]+)", data).group(1)
       
        data = self.target.execdom0("cat /etc/resolv.conf")
        dns = re.findall("nameserver ([0-9\.]+)", data)[0] 

        data = self.target.execdom0("route")
        gateway = re.search("default\s+([0-9\.]+)", data).group(1)

        args = []
        args.append("mode=static")
        args.append("IP=%s" % (ip))
        args.append("netmask=%s" % (netmask))
        args.append("DNS=%s" % (dns))
        args.append("gateway=%s" % (gateway))
        args.append("uuid=%s" % (self.pif))
        try: self.cli.execute("pif-reconfigure-ip", string.join(args))
        except: pass
        self.target.restartToolstack()
        self.pool.master.execdom0("xe pool-recover-slaves")
        self.pool.check()
    
    def postRun(self):
        self.cli.execute("pif-reconfigure-ip", "mode=dhcp uuid=%s" % (self.pif))

class TC1228(_PIFReconfigure):

    def prepare(self, arglist):
        _PIFReconfigure.prepare(self, arglist)
        self.target = self.pool.slaves.values()[0]

class TC1229(_PIFReconfigure):

    def prepare(self, arglist):
        _PIFReconfigure.prepare(self, arglist)
        self.target = self.pool.master


class TC1730(xenrt.TestCase):
    """Detach/destroy Heartbeat SR."""

    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        self.context = Context(self.pool)
        self.context.prepare(["HAPool"])

    def run(self, arglist):
        cli = self.pool.getCLIInstance()
        statefilevdi = self.pool.master.parseListForUUID("vdi-list", "name-label", "Statefile for HA")
        statefilesr = self.pool.master.getVDISR(statefilevdi)

        try:
            self.pool.master.destroyVDI(statefilevdi)
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose("Expected failure to delete state file VDI.")
        else:
            raise xenrt.XRTFailure("Deleted state file VDI.")

        try:
            self.pool.master.destroySR(statefilesr)
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose("Expected failure to destroy state file SR.")
        else:
            raise xenrt.XRTFailure("Destroyed state file SR.")

        try:
            self.pool.master.forgetSR(statefilesr)
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose("Expected failure to forget state file SR.")
        else:
            raise xenrt.XRTFailure("Forgot state file SR.")

    def postRun(self):
        self.context.cleanup(self.context.entities)

class TC1733(xenrt.TestCase):
    """Compute host failure capacity through CLI."""

    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        self.context = Context(self.pool)
        self.context.prepare(["HAPool"])

    def run(self, arglist):
        cli = self.pool.getCLIInstance()
        result = cli.execute("pool-ha-compute-max-host-failures-to-tolerate").strip()
        xenrt.TEC().logverbose("Result: %s" % (result))
        if not result == "1":
            raise xenrt.XRTFailure("Unexpected result. (%s)" % (result))

    def postRun(self):
        self.context.cleanup(self.context.entities)
