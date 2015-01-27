#
# XenRT: Test harness for Xen and the XenServer product family
#
# Basic guest operations test cases
#
# Copyright (c) Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import sys, string, time, re
import xenrt

class TCStartStop(xenrt.LoopingTestCase):

    def __init__(self):
        xenrt.LoopingTestCase.__init__(self, "TCStartStop")
        self.blocker = True
        self.initialState = "DOWN"
        self.workloads = None
        self.fromguest = False

    def extraArgs(self, arg):
        l = string.split(arg, "=", 1)
        if l[0] == "fromguest":
            self.fromguest = True

    def loopBody(self, guest, iteration):
        host = guest.host

        host.listDomains()
        guest.start()
        host.checkHealth()
        host.listDomains()
        time.sleep(20)
        if self.fromguest:
            guest.unenlightenedShutdown()
            guest.poll("DOWN")
        else:
            guest.shutdown()
        host.checkHealth()

class TCReboot(xenrt.LoopingTestCase):

    def __init__(self):
        xenrt.LoopingTestCase.__init__(self, "TCReboot")
        self.blocker = True
        self.extradisk = None
        self.initialState = "UP"
        self.workloads = None
        self.patterns = False
        self.injectfault = None

    def extraArgs(self, arg):
        l = string.split(arg, "=", 1)
        if l[0] == "patterns":
            self.patterns = True
        elif l[0] == "injectfault":
            self.injectfault = int(l[1])

    def preRun(self, guest):
        if guest.windows and self.patterns:
            xenrt.TEC().comment("Not using patterns on Windows guest")
            self.patterns = False

        if self.patterns:
            try:
                # Add an extra drive (only works on Rio+, so don't specify 
                # patterns for OSS etc)
                sr = guest.chooseSR()
                self.extradisk = guest.createDisk(sizebytes=2048*1024*1024, 
                                                  sruuid=sr, 
                                                  userdevice="xvdc")
                time.sleep(30)
            except:
                xenrt.TEC().warning("Exception occured when adding extra "
                                    "drive, disabling patterns")
                self.patterns = False

            # Build disktest
            guest.buildProgram("disktest")

    def loopBody(self,guest,i):
        host = guest.host

        if self.patterns:
            if self.injectfault == i:
                xenrt.TEC().comment("Injecting fault at iteration %u" % (i))
                iter = (i+1)
            else:
                iter = i
            guest.execguest("%s/guestprogs/disktest/disktest write /dev/%s %u" %
                            (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"),
                             self.extradisk, iter),timeout=3600)

        host.listDomains()
        guest.reboot()
        host.checkHealth()

        if self.patterns:
            try:
                guest.execguest("%s/guestprogs/disktest/disktest verify "
                                "/dev/%s %u" % 
                                (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"),
                                 self.extradisk, i),timeout=3600)
            except xenrt.XRTFailure, e:
                raise xenrt.XRTFailure("Disk corruption detected on "
                                       "iteration %u" % (i))
        time.sleep(20)

    def postRun(self):
        if self.extradisk:
            try:
                # Remove the extra drive we added
                vbd = self.guest.getDiskVBDUUID(self.extradisk)
                if self.guest.getState() == "UP":
                    self.guest.unplugDisk(self.extradisk)
                cli = self.guest.getCLIInstance()
                vdi = self.guest.host.genParamGet("vbd",vbd,"vdi-uuid")
                cli.execute("vbd-destroy","uuid=%s" % (vbd))
                cli.execute("vdi-destroy","uuid=%s" % (vdi))
            except:
                xenrt.TEC().warning("Exception occured in extradisk cleanup")
        xenrt.LoopingTestCase.postRun(self)

class TCShutdown(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCShutdown")
        self.blocker = True

    def run(self, arglist=None):

        again = False
        uninstall = False
        fin = False
        gname = None
        mustdo = False
        fromguest = False
        resident_on = None

        # Mandatory args.
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "again":
                again = True
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "uninstall":
                uninstall = True
            elif l[0] == "finally":
                fin = True
                again = True
            elif l[0] == "mustdo":
                mustdo = True
            elif l[0] == "fromguest":
                fromguest = True
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
            elif l[0] == "resident_on":
                resident_on = l[1]

        if not gname:
            raise xenrt.XRTError("No guest name specified")
        
        guest = None
        if resident_on:
            host = self.getHost(resident_on)
            guest = host.getGuest(gname)
        else:
            guest = self.getGuest(gname)
            
        if not guest:
            raise xenrt.XRTError("Could not find guest %s in registry" %
                                 (gname))
        if guest.getState() == "DOWN":
            if not fin:
                xenrt.TEC().skip("Guest already down")
                return
            if mustdo:
                guest.start()
        else:
            try:
                if not guest.windows:
                    guestts = int(guest.execguest("date +%s"))
                    localts = int(xenrt.command("date +%s"))
                    xenrt.TEC().comment("Guest time delta from controller is "
                                        "%d seconds" % (guestts - localts))
            except:
                pass
            self.getLogsFrom(guest.host)
            try:
                if fromguest:
                    guest.unenlightenedShutdown()
                    guest.poll("DOWN")
                else:
                    guest.shutdown(again=again)
            except Exception, e:
                if not fin:
                    raise e

        if (uninstall or fin) and xenrt.TEC().lookup("FINALLY_UNINSTALL",
                                                     False,
                                                     boolean=True):
            guest.uninstall()

class TCStart(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCStart")
        self.blocker = True

    def run(self, arglist=None):
        gname = None

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
        self.getLogsFrom(guest.host)
        guest.start()
        if not guest.windows:
            try:
                guestts = int(guest.execguest("date +%s"))
                localts = int(xenrt.command("date +%s"))
                xenrt.TEC().comment("Guest time delta from controller is %d "
                                    "seconds" % (guestts - localts))
            except:
                pass

class TCUninstall(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCUninstall")

    def run(self, arglist=None):
        gname = None

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
        self.getLogsFrom(guest.host)
        guest.uninstall()
        xenrt.TEC().registry.guestDelete(gname)

class TCGuestUpdate(xenrt.TestCase):
    """Update the VM kernel from a web update repository."""

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCGuestUpdate")
        self.blocker = True

    def run(self, arglist=None):
        gname = None

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
        self.getLogsFrom(guest.host)

        # Check the kernel we're running now
        oldkver = guest.execguest("uname -r").strip()
        xenrt.TEC().comment("Old kernel version %s" % (oldkver))

        # Construct the URL for the update staging site. This is in the form
        # <stagingurl>/XenServer/<XSversion>        
        url = guest.host.lookup(\
            "KERNEL_LCM_STAGING", "http://updates-int.uk.xensource.com")
        if url[0] == "/":
            url = xenrt.TEC().lookup("FORCE_HTTP_FETCH") + url

        # Perform the update
        guest.updateKernelFromWeb(url)
        guest.reboot()

        # Make sure we're running a newer kernel
        newkver = guest.execguest("uname -r").strip()
        if newkver == oldkver:
            raise xenrt.XRTError("Upgraded VM has the same kernel as "
                                 "before the upgrade: %s" % (oldkver))
        xenrt.TEC().comment("New kernel version %s" % (newkver))

class TCVerifyUEK(xenrt.TestCase):
    """ Verify Oracle Enterprise Linux 6.5 is UEK by default(on Creedence)"""
    
    UEK = True
    
    def __init__(self):
        xenrt.TestCase.__init__(self, "TCVerifyUEK")
        
    def run(self, arglist=None):
        gname = None

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
        host = guest.getHost()
        
        if guest.getState() == "DOWN":
            guest.start()

        self.getLogsFrom(host)

        kversion = guest.execguest("uname -r").strip()
        xenstoreEntry = host.xenstoreRead("/local/domain/%u/data/os_uname" %(guest.getDomid()))
        vmparamUname = guest.paramGet('os-version','uname')

        #OEL is UEK by default on creedence
        if isinstance(host, xenrt.lib.xenserver.CreedenceHost) and self.UEK:
            if not re.search("uek" , kversion) or not (re.search("uek" , xenstoreEntry) and re.search("uek" , vmparamUname)) or not((xenstoreEntry == kversion ) and (vmparamUname == kversion)):
                raise xenrt.XRTError("Oracle enterprise linux is not UEK by default on %s " %host.productVersion )
            xenrt.TEC().logverbose("Oracle enterprise linux is UEK by default on %s " %host.productVersion)
        
        #OEL is not UEK on upgrade from Clearwater to Creedence
        if not self.UEK:
            if re.search("uek" , kversion) or (re.search("uek" , xenstoreEntry) and re.search("uek" , vmparamUname)) or not ((xenstoreEntry == kversion ) and (vmparamUname == kversion)):
                raise xenrt.XRTError("Oracle enterprise linux is UEK on upgrade to %s " %host.productVersion )

class TCVerifyUEKonUpgrade(TCVerifyUEK):
    """Verify Oracle Enterprise Linux 6.5 is not UEK on upgrade from Clearwater to Creedence """
    
    UEK = False
