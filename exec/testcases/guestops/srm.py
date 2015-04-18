#
# XenRT: Test harness for Xen and the XenServer product family
#
# Save/restore/migrate test cases
#
# Copyright (c) Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import sys, string, time, re, traceback
import xenrt
import testcases.benchmarks.workloads

class TCSuspendResume(xenrt.LoopingTestCase):

    def __init__(self):
        xenrt.LoopingTestCase.__init__(self, "TCSuspendResume")
        self.initialState = "UP"
        self.workloads = None

    def run(self, arglist=None):

        # temporarily disable workloads
        if arglist and len(arglist) > 0:
            newArgList = filter(lambda x:not "workloads" in x, arglist)
        else:
            newArgList = arglist
        
        xenrt.LoopingTestCase.run(self, newArgList)
    
    def preRun(self, guest):
        self.st = xenrt.util.Timer()
        self.rt = xenrt.util.Timer()
        if guest.vcpus > 1 and guest.distro and \
                re.search(r"rhel3", guest.distro):
            xenrt.TEC().skip("Skipping suspend/resume on SMP RHEL3")
            return

    def postRun(self):
        if not self.getOverallResult() in [xenrt.RESULT_PASS, xenrt.RESULT_PARTIAL]:
            xenrt.TEC().logverbose("Attempting to recover VM")
            try:
                self.guest.reboot(force=True)
            except:
                xenrt.TEC().warning("Unable to recover VM, marking TC blocker")
                self.blocker = True
        xenrt.LoopingTestCase.postRun(self)

    def loopBody(self, guest, i):
        host = guest.host

        host.listDomains()
        skew1 = guest.getClockSkew()
        guest.suspend(timer=self.st)
        host.checkHealth()
        host.listDomains()
        skew2 = guest.resume(timer=self.rt)
        host.checkHealth()
        if skew1 != None and skew2 != None:
            delta = abs(skew2-skew1)
            note = "Before the suspend the skew from controller time was %fs" \
                   " and afterwards it was %fs" % (skew1, skew2)
            xenrt.TEC().logverbose(note)
            if delta > 2000000.0:
                raise xenrt.XRTFailure("Clock skew detected after suspend/resume",
                                       note)
            else:
                # Check skew now, in these general tests we'll allow a slight
                # delay for the clock to fix itself up
                time.sleep(5)
                skew3 = guest.getClockSkew()
                delta = abs(skew3-skew1)
                if delta > 3.0:
                    note = "Before the suspend the skew from controller " \
                           "time was %fs and afterwards it was %fs, a short " \
                           "while later it was %fs" % (skew1, skew2, skew3)
                    xenrt.TEC().warning(\
                        "Clock skew detected after suspend/resume: " + note)
            
    def finallyBody(self, guest):
        if self.st.count() > 0:
            xenrt.TEC().logverbose("Suspend times: %s" % (self.st.measurements))
            xenrt.TEC().value("SUSPEND_MAX", self.st.max())
            xenrt.TEC().value("SUSPEND_MIN", self.st.min())
            xenrt.TEC().value("SUSPEND_AVG", self.st.mean())
            xenrt.TEC().value("SUSPEND_DEV", self.st.stddev())
        if self.rt.count() > 0:
            xenrt.TEC().logverbose("Resume times: %s" % (self.rt.measurements))
            xenrt.TEC().value("RESUME_MAX", self.rt.max())
            xenrt.TEC().value("RESUME_MIN", self.rt.min())
            xenrt.TEC().value("RESUME_AVG", self.rt.mean())
            xenrt.TEC().value("RESUME_DEV", self.rt.stddev())

class TCHibernate(xenrt.TestCase):
    """Tests hibernate initiated from within the guest."""

    WORKLOADS = ["w_find",
                 "w_forktest2",
                 #"w_spamcons",
                 "w_memtest"]
    WINDOWS_WORKLOADS = ["Prime95",
                         "Ping",
                         "SQLIOSim",
                         "Burnintest",
                         "NetperfTX",
                         "NetperfRX",
                         "Memtest"]
    
    def __init__(self):
        xenrt.TestCase.__init__(self, "TCHibernate")
        self.blocker = True
        self.guest = None
        self.workloads = None
        self.usedclone = False

    def run(self, arglist=None):

        loops = 50
        reboot = False
        workloads = None
        gname = None
        clonevm = False

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            if l[0] == "loops":
                loops = int(l[1])
            if l[0] == "reboot":
                reboot = True
            elif l[0] == "workloads":
                if len(l) > 1:
                    workloads = l[1].split(",")
                else:
                    workloads = self.WINDOWS_WORKLOADS
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" %
                                        (matching))
                if matching:
                    gname = matching[0]
            elif l[0] == "clone":
                clonevm = True
        if not gname:    
            raise xenrt.XRTError("No guest name specified.")
        
        guest = self.getGuest(gname)
        self.guest = guest
        host = guest.host
        self.getLogsFrom(host)

        if xenrt.TEC().lookup("OPTION_USE_CLONE", False, boolean=True) or clonevm:
            xenrt.TEC().comment("Using clone to run test.")
            self.blocker = False
            if guest.getState() != "UP":
                guest.start()
            guest.preCloneTailor()
            guest.shutdown()
            clone = guest.cloneVM()
            self.guest = clone
            guest = clone
            self.usedclone = True
            self.getLogsFrom(guest)

        if guest.memory >= 4096:
            xenrt.TEC().skip("Skipping hibernate on > 4GB guest.")
            return
        if not guest.windows:
            xenrt.TEC().skip("Skipping hibernate on non-Windows guest.")
            return
        expfail = string.split(host.lookup("EXPFAIL_HIBERNATE", ""), ",")
        if guest.distro and guest.distro in expfail:
            xenrt.TEC().skip("Skipping hibernate for %s which is expected "
                             "to fail." % (guest.distro))
            return

        try:
            # Make sure the guest is up
            if guest.getState() == "DOWN":
                xenrt.TEC().comment("Starting guest before commencing loop.")
                guest.start()

            # Make sure the guest is healthy before we start.
            guest.waitForDaemon(60, desc="Guest check")
        
            # Start workloads on the guest.
            if workloads:
                if guest.windows:
                    self.workloads = guest.startWorkloads(workloads)
                else:
                    self.workloads = guest.startWorkloads(self.WORKLOADS)

        except Exception, e:
            xenrt.TEC().logverbose("Guest broken before we started (%s)." % str(e))
            raise
        
        # Enable hibernate for Tampa Guests
        if isinstance(guest, xenrt.lib.xenserver.guest.TampaGuest):
            guest.paramSet("platform:acpi_s4", "true")
            guest.reboot()
        
        # Enable hibernation.
        try:
            guest.winRegAdd("HKCU",
                            "Software\\Policies\\Microsoft\\Windows\\"
                            "System\\Power",
                            "PromptPasswordOnResume",
                            "DWORD",
                            0)
            try:
                guest.xmlrpcExec("powercfg.exe /GLOBALPOWERFLAG off /OPTION RESUMEPASSWORD")
            except:
                pass
        except:
            pass
        try:
            guest.xmlrpcExec("powercfg.exe /HIBERNATE ON")
        except:
            pass

        # Test hibernate in a loop
        success = 0
        try:
            for i in range(loops):
                xenrt.TEC().logverbose("Starting loop iteration %u..." % (i))
                host.listDomains()
                attempt = 0
                while True:
                    try:
                        # Ignore errors since we may get the connection
                        # severed on the down
                        guest.xmlrpcStart("shutdown /h")
                    except:
                        pass
                    try:
                        guest.poll("DOWN", timeout=1200)
                        break
                    except Exception, e:
                        try:
                            # See if the hibernate started, i.e. we can't ping
                            # the execdaemon.
                            guest.checkReachable()
                        except:
                            guest.checkHealth(unreachable=True)
                            raise xenrt.XRTFailure("Hibernate didn't complete")
                        guest.check()
                        if attempt == 2:
                            self.blocker = False
                            raise xenrt.XRTFailure("Hibernate didn't happen after 3 attempts")
                        else:
                            xenrt.TEC().warning("Hibernate didn't seem to happen.")
                            attempt = attempt + 1
                            continue
                time.sleep(2)
                host.listDomains()
                guest.start(skipsniff=True)
                success = success + 1
        finally:
            self.tec.comment("%u/%u iterations successful" % (success, loops))

        # Stop guest workloads.
        if workloads:
            guest.stopWorkloads(self.workloads)

        try:
            if reboot:
                guest.reboot()
        except xenrt.XRTFailure, e:
            raise xenrt.XRTError(e.reason)

    def postRun(self):
        try:
            self.guest.stopWorkloads(self.workloads)
        except:
            pass
        if self.usedclone:
            try:
                self.guest.shutdown(again=True)
            except:
                pass
            try:
                self.guest.uninstall()
            except:
                pass

class TCMigrate(xenrt.TestCase):
    
    WORKLOADS = ["w_find",
                 "w_memtest",
                 #"w_spamcons",
                 "w_forktest2"]

    WINDOWS_WORKLOADS = ["Prime95",
                         "Ping",
                         "SQLIOSim",
                         "Burnintest",
                         "NetperfTX",
                         "NetperfRX",
                         "Memtest"]
    
    def __init__(self):
        xenrt.TestCase.__init__(self, "TCMigrate")
        self.workloads = None 
        self.guest = None
        self.semclass = "TCMigrate"
        self.usedclone = False

    def run(self, arglist=None):
    
        loops = 50
        live = "false"
        reboot = False
        target = None
        fast = False
        workloads = None
        gname = None
        clonevm = False
        iterreboot = False

        # Mandatory args
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            if l[0] == "loops":
                loops = int(l[1])
            elif l[0] == "live":
                live = "true"
            elif l[0] == "reboot":
                reboot = True
            elif l[0] == "iterreboot":
                iterreboot = True
            elif l[0] == "to":
                if l[1] != "localhost":
                    target = l[1]
            elif l[0] == "fast":
                fast = True
            elif l[0] == "workloads":
                if len(l) > 1:
                    workloads = l[1].split(",")
                else:
                    workloads = self.WINDOWS_WORKLOADS
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" %
                                        (matching))
                if matching:
                    gname = matching[0]
            elif l[0] == "clone":
                clonevm = True
        if not gname:            
            raise xenrt.XRTError("No guest name specified")
        g = self.getGuest(gname)
        self.guest = g
        if g.distro and g.distro in string.split(\
            xenrt.TEC().lookup("SKIP_MIGRATE_DISTROS", ""), ","):
            xenrt.TEC().skip("Skipping migrate on %s" % (g.distro))
            return
        self.getLogsFrom(g.host)
        
        if xenrt.TEC().lookup("OPTION_USE_CLONE", False, boolean=True) or clonevm:
            xenrt.TEC().comment("Using clone to run test.")
            self.blocker = False
            if g.getState() != "UP":
                g.start()
            g.preCloneTailor()
            g.shutdown()
            clone = g.cloneVM()
            self.guest = clone
            g = clone
            self.usedclone = True
            self.getLogsFrom(g)

        if target:
            thost = xenrt.TEC().registry.hostGet(target)
            if not thost:
                raise xenrt.XRTError("Cannot find host %s in registry" %
                                     (target))
            self.getLogsFrom(thost)
            hostlist = [thost, g.host]
            xenrt.TEC().comment("Migrating to %s" % (thost.getName()))
        else:
            hostlist = [g.host]
            xenrt.TEC().comment("Performing localhost migrate")

        
        if live == "true":
            xenrt.TEC().progress("Running %d iterations of live migrate "
                                 "using %s." % (loops, gname))
        else:
            xenrt.TEC().progress("Running %d iterations of migrate using %s." %
                                 (loops, gname))
        if fast:
            xenrt.TEC().comment("Using back to back migrations")

        try:
            if g.getState() == "DOWN":
                xenrt.TEC().comment("Starting guest %s before commencing "
                                    "migrate." % (g.name))
                g.start()
            # Make sure the guest is healthy before we start
            if not g.windows:
                g.waitForSSH(60, desc="Guest check")
            else:
                g.waitForDaemon(60, desc="Guest check")

            # Make sure there is sufficient memory on the first target
            freemem = hostlist[0].getFreeMemory()
            if freemem < g.memory:
                if xenrt.TEC().lookup("MIGRATE_NOMEM_SKIP",
                                      False,
                                      boolean=True):
                    xenrt.TEC().skip("Skipping because of insufficent free "
                                     "memory on %s (%u < %u)" %
                                     (hostlist[0].getName(),
                                      freemem,
                                      g.memory))
                    return
                else:
                    raise xenrt.XRTError("Insufficent free "
                                         "memory on %s (%u < %u)" %
                                         (hostlist[0].getName(),
                                          freemem,
                                          g.memory))
        
            # Start workloads on the guest
            if workloads:
                if g.windows:
                    self.workloads = g.startWorkloads(workloads)
                else:
                    self.workloads = g.startWorkloads(self.WORKLOADS)

        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            raise xenrt.XRTError("Guest broken before we started (%s)" %
                                 (str(e)))


        success = 0
        mt = xenrt.util.Timer()
        try:
            for i in range(loops):
                if xenrt.GEC().abort:
                    xenrt.TEC().warning("Aborting on command")
                    break
                h = hostlist[i%len(hostlist)]
                xenrt.TEC().logverbose("Starting loop iteration %u (to %s)..."
                                       % (i, h.getName()))
                if not fast:
                    domid = g.getDomid()
                    skew1 = g.getClockSkew()
                g.migrateVM(h, live=live, fast=fast, timer=mt)
                if not fast:
                    skew2 = g.getClockSkew()
                    time.sleep(10)
                    g.check()
                    if not target:
                        # On localhost make sure we did something
                        if g.getDomid() == domid:
                            raise xenrt.XRTError("Domain ID unchanged after "
                                                 "migrate.") 
                    if skew1 != None and skew2 != None:
                        delta = abs(skew2-skew1)
                        note = "Before the migrate the skew from controller " \
                               "time was %fs and afterwards it was %fs" % \
                               (skew1, skew2)
                        xenrt.TEC().logverbose(note)
                        if delta > 2000000.0:
                            raise xenrt.XRTFailure("Clock skew detected after "
                                                   "migrate", note)
                        else:
                            # Check skew now, in these general tests we'll
                            # allow a slight delay for the clock to fix
                            # itself up
                            time.sleep(5)
                            skew3 = g.getClockSkew()
                            delta = abs(skew3-skew1)
                            if delta > 3.0:
                                note = "Before the suspend the skew from " \
                                       "controller time was %fs and " \
                                       "afterwards it was %fs, a short " \
                                       "while later it was %fs" % \
                                       (skew1, skew2, skew3)
                                xenrt.TEC().warning("Clock skew detected "
                                                    "after suspend/resume: " +
                                                    note)
                                                
                success = success + 1
                if iterreboot:
                    g.reboot()
                    if workloads:
                        if g.windows:
                            self.workloads = g.startWorkloads(workloads)
                        else:
                            self.workloads = g.startWorkloads(self.WORKLOADS)
        finally:
            xenrt.TEC().comment("%u/%u iterations successful." % (success, loops))
            if mt.count() > 0:
                xenrt.TEC().logverbose("Migrate times: %s" % (mt.measurements))
                xenrt.TEC().value("MIGRATE_MAX", mt.max())
                xenrt.TEC().value("MIGRATE_MIN", mt.min())
                xenrt.TEC().value("MIGRATE_AVG", mt.mean())
                xenrt.TEC().value("MIGRATE_DEV", mt.stddev())

        if fast:
            time.sleep(10)
            g.check()

        if workloads:
            g.stopWorkloads(self.workloads)

        try:
            if reboot:
                g.reboot()
        except xenrt.XRTFailure, e:
            raise xenrt.XRTError(e.reason)

    def postRun(self):
        if not self.getOverallResult() in [xenrt.RESULT_PASS, xenrt.RESULT_PARTIAL]:
            xenrt.TEC().logverbose("Attempting to recover VM")
            try:
                self.guest.reboot(force=True)
            except:
                xenrt.TEC().warning("Unable to recover VM, marking TC blocker")
                self.blocker = True

        try:
            self.guest.stopWorkloads(self.workloads)
        except:
            pass
        if self.usedclone:
            try:
                self.guest.shutdown(again=True)
            except:
                pass
            try:
                self.guest.uninstall()
            except:
                pass
