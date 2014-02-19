#
# XenRT: Test harness for Xen and the XenServer product family
#
# XenServer negative test cases (i.e. check things error when expected)
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import string, time, re
import xenrt, xenrt.lib.xenserver, xenrt.lib.xenserver.cli

class TC8187(xenrt.TestCase):
    """Try and suspend a guest into an SR of insufficient size"""

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid=tcid)
        self.host = None
        self.originalSR = None
        self.newSR = None

    def run(self, arglist=None):

        host = self.getDefaultHost()
        self.host = host

        guest = host.createGenericLinuxGuest()
        self.uninstallOnCleanup(guest)

        # Find out how much memory the guest has
        mem = guest.memget()

        # Make an SR that's half the size
        srsize = mem / 2

        # We create the SR by creating a sparse file, making a filesystem on
        # it, then mounting it loopback...
        localBase = xenrt.TEC().lookup("LOCAL_BASE")
        host.execdom0("dd if=/dev/zero of=%s/ssr bs=1k seek=%dk count=1" %
                      (localBase,srsize))
        host.execdom0("mkfs.ext3 -F %s/ssr" % (localBase))
        host.execdom0("mkdir -p %s/suspendsr" % (localBase))
        host.execdom0("mount -o loop %s/ssr %s/suspendsr" % 
                      (localBase, localBase))

        args = []
        args.append("name-label=suspendsrfull")
        args.append("physical-size=%d" % (srsize * 1048576))
        args.append("type=file")
        args.append("device-config-location=\"%s/suspendsr/sr\"" % (localBase))
        cli = host.getCLIInstance()

        try:
            self.newSR = cli.execute("sr-create",string.join(args),strip=True)
        except:
            raise xenrt.XRTError("Unable to create new SR")

        # Store where the current SR is (assume for now we're not in a pool)
        self.originalSR = host.getHostParam("suspend-image-sr-uuid")

        # Now set ours up
        host.setHostParam("suspend-image-sr-uuid", self.newSR)

        # Try suspend
        allowed = False
        try:
            cli.execute("vm-suspend", "uuid=%s" % (guest.getUUID()),
                        timeout=1200)
            allowed = True
        except xenrt.XRTFailure, e:
            if "timed out" in e.reason:
                xenrt.TEC().logverbose("vm-suspend timed out, performing "
                                       "emergency cleanup")
                host.machine.powerctl.cycle()
                host.waitForSSH(600, desc="Host boot after emergency cleanup")
                time.sleep(300)
                raise xenrt.XRTFailure("vm-suspend timed out")
            else:
                pass

        if allowed:
            raise xenrt.XRTFailure("Suspend succeeded")

        # See if the guest is (still) up
        try:
            guest.check()
        except xenrt.XRTFailure, e:
            raise xenrt.XRTFailure("Guest has gone away")

    def postRun(self):
        # Restore the original suspend sr
        if self.originalSR:
            self.host.setHostParam("suspend-image-sr-uuid",self.originalSR)
        # Destroy and cleanup the new SR
        if self.newSR:
            cli = self.host.getCLIInstance()
            pbd = self.host.minimalList("pbd-list", args="sr-uuid=%s" % 
                                                         (self.newSR))[0]
            cli.execute("pbd-unplug uuid=%s" % (pbd))
            cli.execute("pbd-destroy uuid=%s" % (pbd))
            cli.execute("sr-forget", "uuid=%s" % (self.newSR))
            localBase = xenrt.TEC().lookup("LOCAL_BASE")
            self.host.execdom0("umount %s/suspendsr" % (localBase))
            self.host.execdom0("rm -f %s/ssr" % (localBase))
            self.host.execdom0("rmdir %s/suspendsr" % (localBase))

