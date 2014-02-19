#
# XenRT: Test harness for Xen and the XenServer product family
#
# Stress standalone testcases
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy
import xenrt, xenrt.lib.xenserver
from xenrt.lazylog import step, comment, log, warning

class TC8046(xenrt.TestCase):
    """Back to back vm-start/vm-shutdown --force of two Windows VMs
       with incomplete boots."""

    def prepare(self, arglist=None):
        self.numvms = 2
        self.duration = 24 * 60 * 60 
        self.guests = []

        self.host = self.getDefaultHost()
        for i in range(self.numvms): 
            g = self.host.createGenericWindowsGuest()
            self.getLogsFrom(g)
            self.guests.append(g)
            self.uninstallOnCleanup(g)
            g.changeCD("xs-tools.iso")
            g.shutdown()

    def run(self, arglist=None):
        start = time.time()
        iteration = 0

        while start + self.duration > time.time():
            xenrt.TEC().progress("Starting iteration %s..." % (iteration))
            self.host.lifecycleOperationMultiple(self.guests, "vm-start")
            time.sleep(5)
            self.host.lifecycleOperationMultiple(self.guests, "vm-shutdown", force=True)
            time.sleep(5)
            iteration += 1
                
        self.host.checkReachable()

class TC7007(xenrt.TestCase):
    """Back-to-back localhost live migrates of a Windows VM (1000 iterations)"""

    def prepare(self, arglist=None):
        host = self.getDefaultHost()
        self.guest = host.createGenericWindowsGuest()
        self.getLogsFrom(self.guest)
        self.uninstallOnCleanup(self.guest)
        self.guest.shutdown()
        self.guest.cpuset(2)
        self.guest.memset(512)
        self.guest.start()
        self.guest.shutdown()
        self.guest.start()

    def run(self, arglist):
        workloadsExecd = self.guest.startWorkloads()

        mt = xenrt.Timer()
        success = 0
        loops = int(xenrt.TEC().lookup("TC7007_ITERATIONS", 1000))
        try:
            for i in range(loops):
                self.guest.migrateVM(self.guest.host,
                                     live="True",
                                     fast=True,
                                     timer=mt)
                success += 1
                if xenrt.GEC().abort:
                    xenrt.TEC().warning("Aborting on command")
                    break
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" %
                                (success,loops))
            if mt.count() > 0:
                xenrt.TEC().logverbose("Migrate times: %s" % (mt.measurements))
                xenrt.TEC().value("MIGRATE_MAX", mt.max())
                xenrt.TEC().value("MIGRATE_MIN", mt.min())
                xenrt.TEC().value("MIGRATE_AVG", mt.mean())
                xenrt.TEC().value("MIGRATE_DEV", mt.stddev())

        self.guest.stopWorkloads(workloadsExecd)
        self.guest.check()
        self.guest.checkHealth()

class TC7022(TC7007):
    """Back-to-back localhost live migrates of a Linux VM (1000 iterations)"""

    def prepare(self, arglist=None):
        host = self.getDefaultHost()
        self.guest = host.createGenericLinuxGuest()
        self.getLogsFrom(self.guest)
        self.uninstallOnCleanup(self.guest)
        self.guest.shutdown()
        self.guest.cpuset(2)
        self.guest.memset(512)
        self.guest.start()

class TC7004(xenrt.TestCase):
    """Perform a parallel start of the maximum supported number of VMs using cloned VHD VBDs"""

    DISTRO = "rhel44"
    ITERATIONS = 100
    TESTMODE = False
    CLITIMEOUT = 7200
    PERVMTIMEOUT = None
    POSTINSTALL = []
    MEMORY = 128

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guests = []
        self.hosts = [self.host]

        # Create the initial VM
        guest = xenrt.lib.xenserver.guest.createVM(self.host,
                                                   xenrt.randomGuestName(),
                                                   self.DISTRO,
                                                   arch="x86-32",
                                                   memory=self.MEMORY,
                                                   vifs=[("0",
                                                        self.host.getPrimaryBridge(),
                                                        xenrt.randomMAC(),
                                                        None)],
                                                   disks=[("0",1,False)],
                                                   postinstall=self.POSTINSTALL)

        self.guests.append(guest)
        guest.preCloneTailor()
        # XRT-4854 disable crond on the VM
        if not guest.windows:
            try:
                guest.execguest("/sbin/chkconfig crond off")
            except:
                pass
        guest.shutdown()

        # Do a clone loop
        if self.TESTMODE:
            max = 3
        else:
            max = int(self.host.lookup("MAX_CONCURRENT_VMS"))
        count = 0
        while count < (max - 1):
            try:
                if count > 0 and count % 20 == 0:
                    # CA-19617 Perform a vm-copy every 20 clones
                    g = guest.copyVM()
                    guest = g
                else:
                    g = guest.cloneVM()
                self.guests.append(g)
                g.start()
                g.shutdown()
            except xenrt.XRTFailure, e:
                xenrt.TEC().comment("Failed to start VM %u: %s" % (count+1,e))
                break
            count += 1

    def stepup(self):

        # Test start/shutdown using --multiple. Start with 1 VM and work up
        # to the max
        timer1 = xenrt.Timer()
        timer2 = xenrt.Timer()
        try:
            for number in range(1, len(self.guests) + 1, 10):
                xenrt.TEC().logverbose("Testing parallel start of %u VMs..." %
                                       (number))
                guestlist = self.guests[:number]
                fail = 0

                for host in self.hosts:
                    host.listDomains()
                c = copy.copy(guestlist)

                # Work out appropriate timeout
                if self.PERVMTIMEOUT:
                    tout = self.PERVMTIMEOUT * number
                else:
                    tout = self.CLITIMEOUT

                xenrt.lib.xenserver.startMulti(guestlist,
                                               no_on=True,
                                               clitimeout=tout,
                                               timer=timer1)
                for g in c:
                    if not g in guestlist:
                        fail = fail + 1
                for host in self.hosts:
                    host.checkHealth()
                    host.listDomains()
                c = copy.copy(guestlist)
                xenrt.lib.xenserver.shutdownMulti(guestlist,
                                                  clitimeout=tout,
                                                  timer=timer2)
                for g in c:
                    if not g in guestlist:
                        fail = fail + 1
                for host in self.hosts:
                    host.checkHealth()
                if guestlist == []:
                    break
                if xenrt.GEC().abort:
                    xenrt.TEC().warning("Aborting on command")
                    break
                
                if fail > 0:
                    raise xenrt.XRTFailure("%d guests failed." % (fail))
        finally:
            xenrt.TEC().logverbose("Start times: %s" % (timer1.measurements))
            xenrt.TEC().logverbose("Shutdown times: %s" % (timer2.measurements))

    def multiple(self):

        # Test start/shutdown in a loop using --multiple
        guestlist = copy.copy(self.guests)
        success = 0
        fail = 0
        loops = int(xenrt.TEC().lookup("TC7004_ITERATIONS", self.ITERATIONS))
        try:
            for i in range(loops):
                xenrt.TEC().logverbose("Starting loop iteration %u..." % (i))
                for host in self.hosts:
                    host.listDomains()
                c = copy.copy(guestlist)

                # Work out appropriate timeout
                if self.PERVMTIMEOUT:
                    tout = self.PERVMTIMEOUT * len(guestlist)
                else:
                    tout = self.CLITIMEOUT

                xenrt.lib.xenserver.startMulti(guestlist,
                                               no_on=True,
                                               clitimeout=tout)
                for g in c:
                    if not g in guestlist:
                        fail = fail + 1
                for host in self.hosts:
                    host.checkHealth()
                    host.listDomains()
                c = copy.copy(guestlist)

                # Work out appropriate timeout
                if self.PERVMTIMEOUT:
                    tout = self.PERVMTIMEOUT * len(guestlist)
                else:
                    tout = self.CLITIMEOUT

                xenrt.lib.xenserver.shutdownMulti(guestlist,
                                                  clitimeout=tout)
                for g in c:
                    if not g in guestlist:
                        fail = fail + 1
                for host in self.hosts:
                    host.checkHealth()
                if guestlist == []:
                    break
                success = success + 1
                if xenrt.GEC().abort:
                    xenrt.TEC().warning("Aborting on command")
                    break
        finally:
            self.tec.comment("%u/%u iterations successful" % (success, loops))
        if fail > 0:
            raise xenrt.XRTFailure("%d guests failed." % (fail))

    def parallel(self):

        timeout = 300 + 240 * len(self.guests)

        # Build dom0 parallel CLI command scripts
        startscript = ["#!/bin/bash"]
        stopscript = ["#!/bin/bash"]
        for g in self.guests:
            startscript.append("xe vm-start uuid=\"%s\" &" % (g.getUUID()))
            stopscript.append("xe vm-shutdown uuid=\"%s\" &" % (g.getUUID()))
        startscriptfn = "%s/startall.sh" % (xenrt.TEC().getLogdir())
        stopscriptfn = "%s/stopall.sh" % (xenrt.TEC().getLogdir())
        f = file(startscriptfn, 'w')
        f.write(string.join(startscript, "\n"))
        f.close()
        f = file(stopscriptfn, 'w')
        f.write(string.join(stopscript, "\n"))
        f.close()
        try:
            sftp = self.hosts[0].sftpClient()
            sftp.copyTo(startscriptfn, "/tmp/startall.sh")
            sftp.copyTo(stopscriptfn, "/tmp/stopall.sh")
        finally:
            sftp.close()
        self.hosts[0].execdom0("chmod +x /tmp/startall.sh /tmp/stopall.sh")

        # Test start/shutdown in a loop using parallel commands in dom0
        success = 0
        loops = int(xenrt.TEC().lookup("TC7004_ITERATIONS", self.ITERATIONS))
        try:
            for i in range(loops):
                xenrt.TEC().logverbose("Starting loop iteration %u..." % (i))
                status = {}
                for g in self.guests:
                    status[g.getName()] = "Unknown"
                for host in self.hosts:
                    host.listDomains()
                self.runAsync(self.hosts[0],
                              "/tmp/startall.sh",
                              timeout=timeout)
                # Check the list of guests, we'll remove then from the 'c'
                # list once we know they're OK
                deadline = xenrt.timenow() + timeout
                c = copy.copy(self.guests)
                time.sleep(180)
                while True:
                    if len(c) == 0:
                        # All OK
                        break
                    gueststoremove = []
                    for g in c:
                        if xenrt.timenow() > deadline:
                            for gc in c:
                                xenrt.TEC().logverbose(\
                                    "Timed out checking %s (%s): %s" %
                                    (gc.getName(),
                                     gc.getUUID(),
                                     status[gc.getName()]))
                            raise xenrt.XRTFailure(\
                                "Timed out checking %u VMs" % (len(c)))
                        if g.getState() != "UP":
                            # Not up yet
                            status[g.getName()] = "waiting for the VM to be UP"
                            continue
                        if not g.windows:
                            try:
                                g.checkReachable()
                            except:
                                # Not reachable yet
                                status[g.getName()] = "waiting for SSH"
                                continue
                        else:
                            if not g.xmlrpcIsAlive():
                                # Not reachable yet
                                status[g.getName()] = "waiting for XML-RPC"
                                continue
                        if not g.checkForWinGuestAgent():
                            # Agent not up yet
                            status[g.getName()] = "waiting for guest agent"
                            continue
                        # All OK, remove the guest from the list
                        status[g.getName()] = "OK"
                        gueststoremove.append(g)
                    for g in gueststoremove:
                        c.remove(g)
                    time.sleep(60)

                for host in self.hosts:
                    host.checkHealth()
                    host.listDomains()
                self.runAsync(self.hosts[0],
                              "/tmp/stopall.sh",
                              timeout=timeout)

                # Poll for all the VMs shutting down                
                status = [0 for g in self.guests]
                deadline = xenrt.timenow() + 300 + 60 * len(self.guests)
                while True:
                    for i in range(len(self.guests)):
                        g = self.guests[i]
                        if status[i] == 0:
                            # Waiting for this VM to be DOWN
                            if g.getState() == "DOWN":
                                status[i] = 1
                    if sum(status) == len(status):
                        # All shutdown
                        break
                    if xenrt.timenow() > deadline:
                        for i in range(len(self.guests)):
                            g = self.guests[i]
                            if status[i] == 0:
                                xenrt.TEC().logverbose("Guest %s is not yet DOWN" %
                                                       (g.name))
                            elif status[i] == 1:
                                xenrt.TEC().logverbose("Guest %s is DOWN" %
                                                       (g.name))
                        raise xenrt.XRTFailure("One or more VMs still running "
                                               "after timeout")
                    time.sleep(15)

                for host in self.hosts:
                    host.checkHealth()
                success = success + 1
                if xenrt.GEC().abort:
                    xenrt.TEC().warning("Aborting on command")
                    break
        finally:
            self.tec.comment("%u/%u iterations successful" % (success, loops))

    def run(self,arglist=None):
        if self.runSubcase("stepup", (), "StartStop", "StepUp") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("multiple", (), "StartStop", "Multiple") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("parallel", (), "StartStop", "Parallel") != \
                xenrt.RESULT_PASS:
            return

    def postRun(self):
        try: xenrt.TEC().logverbose(self.host.execdom0("sar -A"))
        except: pass
        for g in self.guests:
            try:
                try:
                    g.shutdown(force=True)
                except:
                    pass
                g.poll("DOWN", 120, level=xenrt.RC_ERROR)
                g.uninstall()
            except:
                xenrt.TEC().warning("Exception while uninstalling temp guest")

class TC7819(TC7004):
    """Perform a parallel start of the maximum supported number of VMs using cloned VHD VBDs (4.2+)"""
    DISTRO = "rhel46"
    ITERATIONS = 20
    
class TC7004Test(TC7004):

    ITERATIONS = 2
    TESTMODE = True
    DISTRO = "sarge"

class TC7344(TC7004):
    """Pool-wide simultaneous start and shutdown of VMs"""

    DISTRO = "rhel44"
    ITERATIONS = 100
    TESTMODE = False
    HOSTS = 8
    HOSTVMCAP = 58
    CLITIMEOUT = 14400

    def prepare(self, arglist=None):
        self.hosts = []
        for i in range(self.HOSTS):
            self.hosts.append(self.getHost("RESOURCE_HOST_%u" % (i)))
        self.guests = []
        self.originals = []

        # Create the initial VMs
        for host in self.hosts:
            guest = xenrt.lib.xenserver.guest.createVM(host,
                                                       xenrt.randomGuestName(),
                                                       self.DISTRO,
                                                       arch="x86-32",
                                                       memory=128,
                                                       vifs=[("0",
                                                              host.getPrimaryBridge(),
                                                              xenrt.randomMAC(),
                                                              None)],
                                                       disks=[("0",1,False)])

            self.guests.append(guest)
            self.originals.append(guest)
            guest.preCloneTailor()
            guest.shutdown()

        # Do a clone loop
        if self.TESTMODE:
            max = 3
        else:
            max = int(self.hosts[0].lookup("MAX_CONCURRENT_VMS"))
            if max > self.HOSTVMCAP:
                max = self.HOSTVMCAP
        for guest in self.originals:
            count = 0
            while count < (max - 1):
                try:
                    g = guest.cloneVM()
                    self.guests.append(g)
                    g.start()
                    g.shutdown()
                except xenrt.XRTFailure, e:
                    xenrt.TEC().comment("Failed to start VM %u: %s" %
                                        (count+1,e))
                    break
                count += 1

class TC7235(TC7004):
    """Perform a parallel start of the maximum supported number of Windows VMs"""
    DISTRO = "w2k3eesp2"
    POSTINSTALL = ["installDrivers"]

class TC8216(TC7004):
    """Perform a parallel start of the maximum supported number of Windows VMs using Server 2008"""
    DISTRO = "ws08sp2-x86"
    MEMORY = 388
    POSTINSTALL = ["installDrivers"]
    ITERATIONS = 20

class TC9589(TC7004):
    """Perform a parallel start of the maximum supported number of Windows VMs using Windows 7"""
    DISTRO = "win7-x86"
    MEMORY = 388
    POSTINSTALL = ["installDrivers"]
    ITERATIONS = 20
    PERVMTIMEOUT = 300

class TC9589big(TC9589):
    """Execute TC9589 with 1GB RAM"""
    MEMORY = 1024

class TC8189(xenrt.TestCase):
    """Repeated vm-clone/vm-uninstall loops on VHD."""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        extsr = self.host.getSRs(type="ext", local=True)
        if not extsr:
            raise xenrt.XRTError("Couldn't find an EXT SR to use.")
        self.guest = self.host.createGenericLinuxGuest(sr=extsr[0], start=False)
        self.getLogsFrom(self.guest)
        self.uninstallOnCleanup(self.guest)

    def run(self, arglist=None):
        duration = 3600 # 1 hour.    
        finishtime = xenrt.timenow() + duration

        cli = self.host.getCLIInstance()
        iteration = 0
        while True:
            xenrt.TEC().progress("Starting clone iteration %s." % (iteration))
            args = []
            args.append("uuid=%s" % (self.guest.getUUID()))
            args.append("new-name-label=clone-%s" % (iteration))
            uuid = cli.execute("vm-clone", string.join(args), strip=True) 
            args = []
            args.append("uuid=%s" % (uuid))
            args.append("--force")
            cli.execute("vm-uninstall", string.join(args))
            iteration = iteration + 1
            if xenrt.timenow() > finishtime:
                break

class _TC8422(xenrt.TestCase):

    ITERATIONS = 100
    LINUX = False

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()

        # Work out how big a VM we can install
        memory = self.host.getFreeMemory() - 8
        if memory < 7000 or memory > 8200:
            raise xenrt.XRTError("Free memory found not appropriate for "
                                 "this 8GB test",
                                 str(memory))

        # Install a VM
        if self.LINUX:
            self.guest = self.host.createGenericLinuxGuest(memory=memory)
        else:
            memory = int(memory * 0.99)
            self.guest = self.host.createGenericWindowsGuest(memory=memory)
        self.getLogsFrom(self.guest)
        self.uninstallOnCleanup(self.guest)
        
    def run(self, arglist=None):

        i = 0
        try:
            while i < self.ITERATIONS:
                xenrt.TEC().logdelimit("reboot loop iteration %u" % (i))
                self.guest.reboot()
                i = i + 1
                if xenrt.GEC().abort:
                    xenrt.TEC().warning("Aborting on command")
                    break
        finally:
            xenrt.TEC().comment("%u/%u reboot iterations successful" %
                                (i, self.ITERATIONS))

        i = 0
        try:
            while i < self.ITERATIONS:
                xenrt.TEC().logdelimit("start/stop loop iteration %u" % (i))
                self.guest.shutdown()
                self.guest.start()
                i = i + 1
                if xenrt.GEC().abort:
                    xenrt.TEC().warning("Aborting on command")
                    break
        finally:
            xenrt.TEC().comment("%u/%u start/stop iterations successful" %
                                (i, self.ITERATIONS))

        self.guest.shutdown()

class TC8422(_TC8422):
    """Reboot and startup/shutdown loop using a Windows VM"""

    LINUX = False

class TC8423(_TC8422):
    """Reboot and startup/shutdown loop using a Linux VM"""

    LINUX = True

class TC8424(xenrt.TestCase):
    """Parallel VM reboot and startup/shutdown loop"""

    ITERATIONS = 100
    CLITIMEOUT = 7200

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()

        # Work out how big VMs we can install
        memory = self.host.getFreeMemory() - 8
        if memory < 15000 or memory > 16400:
            raise xenrt.XRTError("Free memory found not appropriate for "
                                 "this 16GB test",
                                 str(memory))
        linmemory = int(memory/20) - 8
        winmemory = int(0.99*memory/20) - 8

        # Install one of each VM
        linguest = self.host.createGenericLinuxGuest(memory=linmemory)
        winguest = self.host.createGenericWindowsGuest(memory=winmemory)

        # Create 9 copies of each
        linguest.preCloneTailor()
        winguest.preCloneTailor()
        linguest.shutdown()
        winguest.shutdown()
        self.guests = [linguest, winguest]
        for i in range(9):
            g = linguest.copyVM()
            g.start()
            g.shutdown()
            self.guests.append(g)
            g = winguest.copyVM()
            g.start()
            g.shutdown()
            self.guests.append(g)

        for g in self.guests:
            self.getLogsFrom(g)
            #self.uninstallOnCleanup(g)
            g.start()

    def run(self, arglist=None):
        
        i = 0
        try:
            while i < self.ITERATIONS:
                xenrt.TEC().logdelimit("start/stop loop iteration %u" % (i))
                self.host.listDomains()
                c = copy.copy(self.guests)
                xenrt.lib.xenserver.shutdownMulti(c, 
                                                  clitimeout=self.CLITIMEOUT)
                if len(c) != len(self.guests):
                    raise xenrt.XRTFailure("One or more VMs did not shutdown",
                                           str(len(self.guests) - len(c)))
                self.host.listDomains()
                c = copy.copy(self.guests)
                xenrt.lib.xenserver.startMulti(c, 
                                               clitimeout=self.CLITIMEOUT)
                if len(c) != len(self.guests):
                    raise xenrt.XRTFailure("One or more VMs did not start",
                                           str(len(self.guests) - len(c)))
                i = i + 1
                if xenrt.GEC().abort:
                    xenrt.TEC().warning("Aborting on command")
                    break
        finally:
            xenrt.TEC().comment("%u/%u start/stop iterations successful" %
                                (i, self.ITERATIONS))

        i = 0
        try:
            while i < self.ITERATIONS:
                xenrt.TEC().logdelimit("reboot loop iteration %u" % (i))
                self.host.listDomains()
                c = copy.copy(self.guests)
                xenrt.lib.xenserver.startMulti(c,
                                               reboot=True,
                                               clitimeout=self.CLITIMEOUT)
                if len(c) != len(self.guests):
                    raise xenrt.XRTFailure("One or more VMs did not reboot",
                                           str(len(self.guests) - len(c)))
                i = i + 1
                if xenrt.GEC().abort:
                    xenrt.TEC().warning("Aborting on command")
                    break
        finally:
            xenrt.TEC().comment("%u/%u reboot iterations successful" %
                                (i, self.ITERATIONS))
        
        
class TCXapiSessionLeakVMPR(xenrt.TestCase):
    """Test case to check for XAPI Session leaks caused due to VMPR.
       Observe how many VMPR sessions are open every 20 minutes for around 3 hours.
       Jira TC ID: TC-20978"""
    
    def run(self,arglist=None):
        host = self.getDefaultHost()
        sessions_open = {}
        max_iterations = 10
        count = 0
        values = [] #Stores the number of sessions found open at every iteration
        step("Checking the number of open sessions every 20 minutes")
        for i in range(max_iterations): #Define the number of iterations
            xenrt.sleep(1200) #20 minutes of sleep
            step("Iteration number: %d" %(i+1))
            log("Checking which sessions get created in iteration %d" %(i+1))
            sessions_started = host.execdom0("grep 'Session.create.*uname=__dom0__vmpr' /var/log/xensource.log | true")          
            for entry in sessions_started.strip().splitlines():
                    track = re.search("trackid=(?P<id>[a-z0-9]+)", entry)
                    if not sessions_open.has_key(track.group('id')):
                        sessions_open[track.group('id')] = "open" 
                        count = count+1
            
            log("Checking which sessions are closed in iteration %d" %(i+1))
            for session in sessions_open:
                if sessions_open[session] == "open" and not host.execdom0("grep 'Session.destroy trackid=%s' /var/log/xensource.log" %session, retval="code"):
                    #The session has been successfully closed
                    sessions_open[session] = "closed"
                    count = count-1
            log("At the end of iteration %d, noticed that %d number of vmpr sessions are still open" %(i+1, count))
            values.append(count)
            
        #If the number of open sessions grows over time then we can say there's a leak.
        leak = True
        for i in range(1,len(values)):
            leak = leak and values[i]>values[i-1] #Check if the list is strictly increasing
        if leak:
            raise xenrt.XRTFailure("VMPR sessions leaked")
