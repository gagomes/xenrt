#
# XenRT: Test harness for Xen and the XenServer product family
#
# Agent testcases.
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import xml.dom.minidom, time, string, re, socket, urllib2, xmlrpclib, traceback, sys
import xenrt, xenrt.lib.xenserver
from cc import _CCSetup

class TC20631(xenrt.TestCase):
    def run(self, arglist):
        raise xenrt.XRTFailure("I am a blocker")
        
class TC20632(xenrt.TestCase):
    def run(self, arglist):
        pass
        
class TC8345(xenrt.TestCase):
    """Performance test for xapi."""
    
    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        if not self.host.getSRParam(self.host.getLocalSR(), "type") == "ext":
            raise xenrt.XRTError("No VHD SR found on host.")

    def run(self, arglist=None):
        sdkzip = xenrt.TEC().getFile("xe-phase-2/sdk.zip", "sdk.zip")
        if not sdkzip:
            raise xenrt.XRTError("Couldn't find xe-phase-2/sdk.zip")
        nfs = xenrt.NFSDirectory()
        xenrt.command("unzip %s -d %s" % (sdkzip, nfs.path()))
        
        self.guest = self.host.guestFactory()(\
                        xenrt.randomGuestName(),
                        host=self.host,
                        password=xenrt.TEC().lookup("ROOT_PASSWORD_SDK"))
        self.guest.importVM(self.host, "%s/sdk" % (nfs.path()))
        self.guest.paramSet("is-a-template", "true")
        nfs.remove()

        nfs = xenrt.NFSDirectory()
        xenrt.getTestTarball("apiperf", extract=True, directory=nfs.path())
        self.host.createISOSR(nfs.getMountURL("apiperf"))
        self.sr = self.host.parseListForUUID("sr-list",
                                             "name-label",
                                             "Remote ISO Library on: %s" %
                                             (nfs.getMountURL("apiperf")))
        for s in self.host.getSRs(type="iso", local=True):
            self.host.getCLIInstance().execute("sr-scan", "uuid=%s" %(s))
        time.sleep(30)
    
        self.runSubcase("test", "pool0", "Pool", "Pool0")
        self.runSubcase("test", "pool1", "Pool", "Pool1")
        self.runSubcase("test", "xendesktop", "XenDesktop", "XenDesktop")

    def test(self, scenario):
        xenrt.TEC().logverbose("Initialising pool...")
        self.host.execdom0("/opt/xensource/debug/perftest "
                           "-key xenrt -template %s -scenario %s initpool" % 
                           (self.guest.getName(), scenario), timeout=1800)   
        xenrt.TEC().logverbose("Running test...")
        self.host.execdom0("/opt/xensource/debug/perftest "
                           "-key xenrt -scenario %s run" % 
                           (scenario), timeout=1800)   
        xenrt.TEC().logverbose("Cleaning up...")
        self.host.execdom0("/opt/xensource/debug/perftest "
                           "-key xenrt -template %s destroypool" %
                           (self.guest.getName()), timeout=300) 
        data = self.host.execdom0("cat /root/perftest-xenrt.log")
        self.parseResults(data, scenario)
        file("%s/perftest-%s.xml" % 
             (xenrt.TEC().getLogdir(), scenario), "w").write(data)
        
    def handleTestNode(self, test):
        values = []
        name = test.getAttribute("name")
        subtest = test.getAttribute("subtest")
        for x in test.childNodes:
            values.append((name, subtest, x.data))
        return values

    def parseResults(self, xmldata, scenario):
        xmltree = xml.dom.minidom.parseString(xmldata)
        results = []
        for x in xmltree.childNodes:
            if x.nodeName == "testrun":
                for y in x.childNodes:
                    if y.nodeName == "tests":
                        for z in y.childNodes:
                            if z.nodeName == "test":
                                results += self.handleTestNode(z)
        for x in results:
            name, subtest, value = x
            xenrt.TEC().value("%s-%s:(%s)" % (scenario, name, subtest), value)

    def postRun(self):
        try: self.guest.uninstall()
        except: pass
        try: self.host.forgetSR(self.sr)
        except: pass

class _VBDPauseBase(xenrt.TestCase):
    """Base class for VBD pause/unpause testcases"""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.token = None
        # Pick a VBD to use
        vbds = self.host.minimalList("vbd-list",
                                     args="vm-uuid=%s currently-attached=true" %
                                          (self.guest.getUUID()))
        self.vbd = vbds[0]

    def postRun(self):
        if self.token:
            cli = self.host.getCLIInstance()
            cli.execute("vbd-unpause", "uuid=%s token=%s" % (self.vbd, self.token))

class TC8709(_VBDPauseBase):
    """Verify basic VBD pause/unpause functionality"""

    def run(self, arglist=None):
        # First find the backend VBD path
        
        tap_or_vbd = "tap"
        if self.host.xenstoreExists("/local/domain/0/backend/vbd/%s" % self.guest.getDomid()):
            tap_or_vbd = "vbd"

        vbds = self.host.xenstoreList("/local/domain/0/backend/%s/%s" %
                                      (tap_or_vbd, self.guest.getDomid()))
        vbd = None
        vdiToFind = self.host.genParamGet("vbd", self.vbd, "vdi-uuid")
        for v in vbds:
            vdi = self.host.xenstoreRead("/local/domain/0/backend/%s/%s/"
                                         "%s/sm-data/vdi-uuid" %
                                         (tap_or_vbd, self.guest.getDomid(), v))
            if vdi == vdiToFind:
                vbd = v
                break

        if not vbd:
            raise xenrt.XRTError("Cannot find vbd path in xenstore")

        vbdPath = "/local/domain/0/backend/%s/%s/%s" % (tap_or_vbd, self.guest.getDomid(), vbd)

        token = ""
        cli = self.host.getCLIInstance()
        for i in range(100):
            cli.execute("vbd-unpause", "uuid=%s token=%s" % (self.vbd, token))
            # Check it isn't paused
            if "pause-done" in self.host.xenstoreList(vbdPath):
                raise xenrt.XRTFailure("pause-done found in xenstore when VBD "
                                       "unpaused")

            token = cli.execute("vbd-pause", "uuid=%s" % (self.vbd), strip=True)
            self.token = token
            # Check it's actually paused by looking in xenstore.
            if "pause-done" in self.host.xenstoreList(vbdPath):
                if self.host.xenstoreRead("%s/pause-token" % (vbdPath)) != self.token:
                    raise xenrt.XRTFailure("Token in xenstore does not match "
                                           "token returned by pause command")
            else:
                raise xenrt.XRTFailure("Cannot find pause-done key in xenstore")
                
class TC8710(_VBDPauseBase):
    """A VM with paused VBDs can still be force-shutdown"""

    def run(self, arglist=None):
        cli = self.host.getCLIInstance()
      
        # Pause the VBD
        self.token = cli.execute("vbd-pause", "uuid=%s" % (self.vbd), strip=True)

        # Attempt a force shutdown
        self.guest.shutdown(force=True)

        # Corresponding pause will fail with a bad powerstate
        cli = self.host.getCLIInstance()
        allowed = False
        try:
            cli.execute("vbd-unpause", "uuid=%s token=%s" % (self.vbd, self.token))
            allowed = True
        except:
            pass
        if allowed:
            raise xenrt.XRTFailure("vbd-unpause did not error with shutdown VM")

        # Start the VM
        self.guest.start()

        # Now try the unpause again
        cli.execute("vbd-unpause", "uuid=%s token=%s" % (self.vbd, self.token))

class TC8711(_VBDPauseBase):
    """Pause/unpause only work when VMs are running"""

    def run(self, arglist=None):
        # Shut the guest down
        self.guest.shutdown()
        cli = self.host.getCLIInstance()

        # Attempt to pause and unpause (both should fail)
        allowed = False
        try:
            cli.execute("vbd-pause", "uuid=%s" % (self.vbd))
            allowed = True
        except:
            pass
        if allowed:
            raise xenrt.XRTFailure("vbd-pause did not error with shutdown VM")

        try:
            cli.execute("vbd-unpause", "uuid=%s token=''" % (self.vbd))
            allowed = True
        except:
            pass
        if allowed:
            raise xenrt.XRTFailure("vbd-unpause did not error with shutdown VM")

class TC8708(_VBDPauseBase):
    """Check that a paused VBD will eventually prevent a VM migrate"""
    def run(self, arglist=None):
        cli = self.host.getCLIInstance()

        # 1. 'xe vbd-pause uuid=<vbd>'
        self.token = cli.execute("vbd-pause", "uuid=%s" % (self.vbd), strip=True)

        # 2. attempt a localhost migration of the VM. It will fail with
        #    OTHER_OPERATION_IN_PROGRESS after about 25s.
        allowed = False
        startTime = xenrt.util.timenow()
        try:
            args = []
            args.append("uuid=%s" % (self.guest.getUUID()))
            args.append("host-uuid=%s" % (self.host.getMyHostUUID()))
            args.append("live=true")
            cli.execute("vm-migrate", string.join(args))
            allowed = True
        except xenrt.XRTFailure, e:
            if not re.search(r"OTHER_OPERATION_IN_PROGRESS", e.reason):
                xenrt.TEC().warning("Expected migration failure but with "
                                    "unexpected error code")

        if allowed:
            raise xenrt.XRTFailure("VM migrate allowed with paused VBD")
        
        timeTaken = xenrt.util.timenow() - startTime
        if timeTaken < 20 or timeTaken > 30:
            raise xenrt.XRTFailure("VM migrate took an unexpected amount of "
                                   "time to fail with paused VBD",
                                   data="Expecting ~25s, actual %ds" %
                                        (timeTaken))

        # 3. unpause the vbd
        cli.execute("vbd-unpause", "uuid=%s token=%s" % (self.vbd, self.token))
        self.token = None

        # 4. attempt a localhost migration-- it should work now
        self.guest.migrateVM(self.host)

        # 5. pause the vbd again
        self.token = cli.execute("vbd-pause", "uuid=%s" % (self.vbd), strip=True)

        # 6. attempt a localhost migration and then (after 5s and in parallel)
        #    unpause the vbd . it should work too
        self.host.execdom0("(sleep 5 && xe vbd-unpause uuid=%s token=%s) > "
                           "/dev/null 2>&1 </dev/null &" % (self.vbd, self.token))
        self.guest.migrateVM(self.host)

class TC8714(_VBDPauseBase):
    """A paused VBD can still be unpaused even if the VM is locked"""

    def run(self, arglist=None):
        cli = self.host.getCLIInstance()

        # 1. 'xe vbd-pause uuid=<vbd>'
        self.token = cli.execute("vbd-pause","uuid=%s" % (self.vbd), strip=True)

        # 2. 'xe vm-reboot uuid=<vm>'. this command should block because the
        #    guest will be unable to flush disks etc
        # 3. (some time later in parallel with 2) 'xe vbd-unpause uuid=<vbd>
        #    token=<token>'
        #    At this point the reboot should resume and complete normally.
        self.host.execdom0("(sleep 5 && xe vbd-unpause uuid=%s token=%s) > "
                           "/dev/null 2>&1 </dev/null &" % (self.vbd, self.token))
        self.guest.reboot()

class TC8715(_VBDPauseBase):
    """Check VBD pause fails when the device shuts down"""

    def run(self, arglist=None):
        cli = self.host.getCLIInstance()

        # 1. service xapi stop
        self.host.execdom0("service xapi stop")
        # 2. run '/opt/xensource/bin/xapi -noevents' to disable the background
        #    event handling thread
        self.host.execdom0("/opt/xensource/bin/xapi -noevents -daemon")

        # 3. type 'halt' on the guest console
        self.guest.execguest("(sleep 1 && /sbin/halt) > /dev/null 2>&1 </dev/null &")

        # 4. wait for 'list_domains' to show the domain has Shutdown ('S')
        # Wait for a maximum of 2 minutes
        st = xenrt.util.timenow()
        while True:
            doms = self.host.listDomains(includeS=True)
            if not doms.has_key(self.guest.getUUID()):
                raise xenrt.XRTError("Cannot find domain in list_domains")
            if doms[self.guest.getUUID()][3] == self.host.STATE_SHUTDOWN:
                break
            time.sleep(5)
            if (xenrt.util.timenow() - st) > 120:
                raise xenrt.XRTError("Domain failed to shutdown after 2 minutes")

        if isinstance(self.host, xenrt.lib.xenserver.MNRHost):
            # vbd-pause and vbd-unpause should succeed
            self.token = cli.execute("vbd-pause", "uuid=%s" % (self.vbd), strip=True)
            cli.execute("vbd-unpause", "uuid=%s token=%s" % (self.vbd, self.token))
        else:
            # 5. attempt a 'xe vbd-pause' . it should fail immediately
            allowed = False
            try:
                self.token = cli.execute("vbd-pause", "uuid=%s" % (self.vbd), strip=True)
                allowed = True
            except:
                pass
            if allowed:
                raise xenrt.XRTFailure("vbd-pause allowed with shut down device")

    def postRun(self):
        # Attempt to get xapi running properly again
        try:
            self.host.execdom0("killall xapi")
            time.sleep(5)
            self.host.startXapi()
        except:
            pass
        
        _VBDPauseBase.postRun(self)

class TC8716(_VBDPauseBase):
    """VBD pause serialisation"""

    def run(self, arglist=None):
        cli = self.host.getCLIInstance()

        # 1. 'xe vbd-pause uuid=<vbd>' should print a 'token' (uuid) and succeed
        self.token = cli.execute("vbd-pause", "uuid=%s" % (self.vbd),strip=True)

        # 2. 'xe vbd-pause uuid=<vbd>' should block
        # 3. In parallel with (2) 'xe vbd-unpause uuid=<vbd> token=<token>'
        #    should succeed and cause (2) to unblock and print a second token
        #    At this point the device should still be paused ('pause-done' in xenstore)
        self.host.execdom0("(sleep 10 && xe vbd-unpause uuid=%s token=%s) > "
                           "/dev/null 2>&1 < /dev/null &" % (self.vbd, self.token))
        st = xenrt.util.timenow()
        self.token = cli.execute("vbd-pause", "uuid=%s" % (self.vbd),strip=True)
        timeTaken = xenrt.util.timenow() - st
        if timeTaken < 5 or timeTaken > 20:
            raise xenrt.XRTFailure("vbd-pause blocked for an unexpected period",
                                   data="Expecting ~10s, actual %ds" % (timeTaken)) 

        # 4. 'xe vbd-unpause uuid=<vbd> token=<second token>' should succeed
        #    At this point the device should be unpaused (no 'pause-done' in xenstore)
        cli.execute("vbd-unpause", "uuid=%s token=%s" % (self.vbd, self.token))

        # Verify that VBD pause is unblocked by force shutdown
        self.token = cli.execute("vbd-pause", "uuid=%s" % (self.vbd),strip=True)

        self.host.execdom0("(sleep 10 && xe vm-shutdown force=true uuid=%s) > "
                           "/dev/null 2>&1 < /dev/null &" % (self.guest.getUUID()))
        allowed = False
        st = xenrt.util.timenow()
        try:
            self.token = cli.execute("vbd-pause", "uuid=%s" % (self.vbd),strip=True)
            allowed = True
        except:
            pass
        if allowed:
            raise xenrt.XRTFailure("vbd-pause did not fail as expected")
        timeTaken = xenrt.util.timenow() - st
        if timeTaken < 5 or timeTaken > 20:
            raise xenrt.XRTFailure("vbd-pause blocked for an unexpected period",
                                   data="Expecting ~10s, actual %ds" % (timeTaken))

class TC8768(_CCSetup):
    """Verify that attempts to access the remote_db_access URI are rejected"""
    LICENSE_SERVER_REQUIRED = False

    def prepare(self, arglist=None):
        _CCSetup.prepare(self, arglist)
        self.origSocketTimeout = socket.getdefaulttimeout()

    def run(self, arglist=None):
        # Set the default socket timeout to 5 seconds
        socket.setdefaulttimeout(5)

        # Check against the master
        if self.runSubcase("testAccess", (True), "TestAccess", "Master") != \
            xenrt.RESULT_PASS:
            return

        # And a slave
        if self.runSubcase("testAccess", (False), "TestAccess", "Slave") != \
            xenrt.RESULT_PASS:
            return

    def testAccess(self, master):
        if master:
            host = self.pool.master
        else:
            host = self.pool.getSlaves()[0]

        # Construct the URL
        url = "https://%s/remote_db_access" % (host.getIP())
        xenrt.TEC().logverbose("Attempting to access %s" % (url))
        try:
            u = urllib2.urlopen(url, "")
            # If we succeed then this is most likely a slave that is not
            # running the handler. Test if we can perform normal XenAPI calls
            # against it, if so the handler is not present.
            try:
                socket.setdefaulttimeout(self.origSocketTimeout)
                xenrt.TEC().logverbose("Attempting to establish API session with root / %s" % (host.password))
                xmlrpc = xmlrpclib.ServerProxy(url)
                session_id = xmlrpc.session.login_with_password("root", host.password)["Value"]
                xmlrpc.VM.get_all(session_id)
            except:
                traceback.print_exc(file=sys.stderr)
                # It's not a general XML-RPC handler
                raise xenrt.XRTFailure("Connection to remote_db_access URI was "
                                       "not rejected and handler appears to be "
                                       "present")
        except urllib2.URLError, e:
            if hasattr(e, "reason") and isinstance(e.reason, socket.timeout):
                raise xenrt.XRTFailure("CA-26044 Call to remote_db_access "
                                       "appears to block")
            elif isinstance(e, urllib2.HTTPError) and e.code in (500, 401):
                # This is the expected error
                xenrt.TEC().logverbose("Received expected HTTPError code %d" % (e.code))
            else:
                # Unexpected error                
                raise xenrt.XRTError("Unexpected URLError: %s" % (str(e)))

    def postRun(self):
        _CCSetup.postRun(self)
        try:
            socket.setdefaulttimeout(self.origSocketTimeout)
        except:
            pass
        
