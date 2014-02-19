import xenrt
import libperf
import string, time, re, random, math

class TCLoginVSI(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCLoginVSI")

        self.desktopGroupCreateScript = "client-desktopgroup.py" # found in ref-base (origin: \\192.168.0.1\data\xd\register-desktops)
        self.desktopGroupDeleteScript = "client-deletegroup.py" # found in ref-base (origin: \\192.168.0.1\data\xd\register-desktops)
        self.wficaLauncherScript = "client-wfica.py" # found in ref-base (origin: \\192.168.0.1\data\xd\mylauncher)
        self.rdesktopLauncherScript = "client-rdesktop.py" # found in ref-base (origin: \\192.168.0.1\data\xd\mylauncher)
        self.launcherPingScript = "client-ping.py" # found in ref-base (origin: \\192.168.0.1\data\xd\mylauncher)
        self.restartServiceScript = "client-restart-service.py" # found in ref-base (origin: \\192.168.0.1\data\xd\restart-service)

        self.domain = "xd.net"
        self.ddc = "ddc.xd.net" # running the XML service and \\192.168.0.1\xd\data\restart-service\listen-restart-service.py
        self.launcher = "192.168.0.4" # running register-desktops\listen.py
        self.launcherport = 8000
        self.wficalauncherport = 8000
        self.rdesktoplauncherport = 8000
        self.xenhost = None # will be filled in when we've got a host
        self.xenuser = "root"
        self.xenpassword = xenrt.TEC().lookup("ROOT_PASSWORD")

        self.restartServicePort = 9000

        self.numdesktops = 5
        self.vmsperlauncher = 100000 # default: only use one launcher
        self.numhostsfordesktops = 1
        self.useXenDesktop = True

        self.cleanup = False # True -> delete the desktop group after the test, which enables future tests to use VMs with the same names as the ones in our group
        self.startwithcleanslate = False # True -> delete all desktop groups before the test

        self.numusers = self.numdesktops
        self.randomid = "%08x" % random.randint(0, 0x7fffffff)

        self.loginvsidir = "192.168.0.1:/loginvsi-data"
        self.mountpoint = "/mnt/loginvsi-data"

        self.numreadings = 5 # number of lines in each LoginVSI results files

    def prepare(self, arglist=None):
        # Parse generic arguments
        self.parseArgs(arglist)

        # Parse args relating to this test
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "numdesktops":
                self.numdesktops = int(l[1])
            elif l[0] == "vmsperlauncher":
                self.vmsperlauncher = int(l[1])
            elif l[0] == "cleanupafter":
                self.cleanup = True
            elif l[0] == "cleanupbefore":
                self.startwithcleanslate = True
            elif l[0] == "numhostsfordesktops":
                self.numhostsfordesktops = int(l[1])
            elif l[0] == "rdesktop":
                self.useXenDesktop = False

        self.initialiseHostList()
        self.configureAllHosts()

        self.numusers = self.numdesktops

        self.guest = self.createHelperGuest()

        loginvsivm = self.importGoldVM(self.goldimagesruuid, self.desktopimage, self.desktopvmname, self.desktopvmnetwork)
        xenrt.TEC().logverbose("Creating %d LoginVSI-enabled desktop VMs from image %s..." % (self.numdesktops, self.desktopimage))
        self.clones = self.createMPSVMs(self.numdesktops, loginvsivm)
        self.configureAllVMs()

        # Unset any timeoffset info on the VMs so that we can use the login times
        for vm in self.clones:
            xenrt.TEC().logverbose("Removing the timeoffset param from VM %s..." % vm.getUUID())
            cmd = "xe vm-param-remove uuid=%s param-name=platform param-key=timeoffset" % vm.getUUID()
            output = vm.getHost().execdom0(cmd)
            xenrt.TEC().logverbose("output: %s" % output)

    def run(self, arglist=None):

        self.xenhost = self.host.getIP()
        xenrt.TEC().logverbose("hostname is [%s]" % self.xenhost)

        # Restart the 'Citrix Pool Management service' on the DDC. This clears out any previous state about which hosts were in which pools.
        if self.useXenDesktop:
            self.restartPoolManagementService(self.ddc)

            # Clean up
            if self.startwithcleanslate:
                xenrt.TEC().logverbose("Deleting all existing desktop groups")
                self.deleteAllDesktopGroups()

        rundirpath = None

        # Register the VMs in a new desktop group with the DDC
        groupname = "xenrt%s" % self.randomid
        try:
            if self.useXenDesktop:
                xenrt.TEC().logverbose("Registering VMs with DDC in desktop group %s" % groupname)
                self.registerVMsWithDDC(groupname, self.clones)

            hostobjs = [self.tec.gec.registry.hostGet(h) for h in self.normalHosts]

            # Use the master for the host for the launchers
            launcherhostobj = hostobjs.pop(0)
            xenrt.TEC().logverbose("Nominated host %s as the launcher host" % launcherhostobj.getName())
            numthreads = self.numhostsfordesktops

            # Select the relevant number of hosts for desktops
            hostobjsfordesktops = hostobjs[0:self.numhostsfordesktops]
            hostnamesfordesktops = [h.getName() for h in hostobjsfordesktops]
            xenrt.TEC().logverbose("Names of hosts for desktop VMs are %s" % hostnamesfordesktops)

            # Now spin up the VMs
            xenrt.TEC().logverbose("Starting VMs")
            bootwatcherLogfile = libperf.createLogName("bootwatcher")
            starterLogfile = libperf.createLogName("starter")

            self.timeStartVMs(numthreads, self.clones, starterLogfile, bootwatcherLogfile, queueHosts=hostnamesfordesktops, awaitParam="PV_drivers_version", awaitKey="major")

            # Now make some launcher VMs
            numlaunchers = int(math.ceil(self.numdesktops / self.vmsperlauncher))
            xenrt.TEC().logverbose("VMs per launcher is %d; number of desktops is %d; hence using %d launcher VMs" % (self.vmsperlauncher, self.numdesktops, numlaunchers))

            launchers = []
            for i in range(0, numlaunchers):
                launchername = "mylauncher%d" % i
                xenrt.TEC().logverbose("Making launcher VM %d on host %s..." % (i, launcherhostobj.getName()))
                # TODO could import the first and then clone the rest?
                launchervmobj = self.makeLauncherVM(launchername, useICA=self.useXenDesktop, host=launcherhostobj)
                launchers.append(launchervmobj)

            # Create a 'run' directory. The returned path is valid on self.guest.
            rundirpath = self.createFreshResultsDir()

            # Now tell the launcher to start ICA sessions to the VMs.
            # The VMs then log in and LoginVSI kicks in.
            # (We assume that by this stage the VMs' VDAs have registered with the DDC.)

            refbasedir = self.mountRefBase(self.guest.execguest)

            # Begin to collect stats from NetApp, for REQ247,249
            self.startNetAppStatGather()

            for i in range(0, self.numdesktops):
                launcherindex = i % numlaunchers
                if self.useXenDesktop:
                    user = "test%d" % (i+1)

                    xenrt.TEC().logverbose("Logging in to desktop group %s with user %s on launcher %d" % (groupname, user, launcherindex))
                    self.logInToVMsWfica(refbasedir, launchers[launcherindex], groupname, user, "xenroot!!1!")
                else:
                    # Get the IP address of the ith desktop VM
                    xenrt.TEC().logverbose("Finding IP of %dth desktop VM..." % i)

                    # We need to know the host that the ith desktop VM is running on
                    # TODO Temporary hack: assume it's the second host in self.normalHosts!
                    h = self.normalHosts[1]
                    xenrt.TEC().logverbose("host is [%s]" % h)
                    vmuuid = self.clones[i].getUUID()
                    ip = self.getVMIP(h, vmuuid)
                    xenrt.TEC().logverbose("IP of %dth VM is %s" % (i, ip))

                    xenrt.TEC().logverbose("Logging in to %dth VM with on launcher %d" % (i, launcherindex))
                    self.logInToVMsRdesktop(refbasedir, launchers[launcherindex], ip, "Administrator", xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS", "ADMINISTRATOR_PASSWORD"]))

            xenrt.TEC().logverbose("Started all %d sessions!" % self.numdesktops)

            # Wait for the sessions to complete
            latestTime = time.time() + 50*60 # allow 50 mins for all sessions to complete
            for i in range(1, self.numdesktops+1):
                xenrt.TEC().logverbose("Waiting for the %dth session of %d to complete..." % (i, self.numdesktops))
                self.waitForResultsToAppear(rundirpath, i, self.numreadings, latestTime)

            xenrt.TEC().logverbose("All %d sessions have completed (or timed out)!" % self.numdesktops)

            # Now gather the final stats from the NetApp, for REQ247,249
            stats = self.finishNetAppStatGather()
            netappLogFile = libperf.createLogName("netapp")
            libperf.outputToResultsFile(netappLogFile, stats)

            xenrt.TEC().logverbose("All good.")
        finally:
            xenrt.TEC().logverbose("FINALLY")

            if not rundirpath is None:
                # Get the results.
                xenrt.TEC().logverbose("Copying logs from %s..." % rundirpath)
                self.copyRunDirToLogs(rundirpath)
        
            if self.useXenDesktop:
                # Clean up
                if self.cleanup:
                    xenrt.TEC().logverbose("Deleting desktop group %s" % groupname)
                    self.deleteDesktopGroup(groupname)

    def postRun(self):
        self.finishUp()

    def getVMIP(self, h, uuid):
        host = self.tec.gec.registry.hostGet(h)

        # Note: self.clones[i].getDomid() is not reliable because it assumes that the host in self.clones[i] is accurate, but it's not. So we look up the domid ourselves.
        domid = int(host.execdom0("list_domains | grep '%s' | awk -F\\| '{print $1}'" % uuid).strip())
        xenrt.TEC().logverbose("domid of VM with uuid %s is %d" % (uuid, domid))

        ip = host.xenstoreRead("/local/domain/%d/attr/eth0/ip" % domid)
        #ip = self.clones[i].getIP()  # -- seems to return None?

        return ip

    def executeRefScript(self, scriptandargs, timeout=300):
        dir = self.mountRefBase(self.guest.execguest)
        cmd = "%s/%s" % (dir, scriptandargs)
        xenrt.TEC().logverbose("Command is %s" % cmd)
        output = self.guest.execguest(cmd, timeout=timeout)
        xenrt.TEC().logverbose("Output was %s" % output)
        return output

    def restartPoolManagementService(self, address):
        # This client talks to restart-service/listen-restart-service.py
        cmd = "%s --ddc=%s --port=%d" % (self.restartServiceScript, address, self.restartServicePort)
        self.executeRefScript(cmd)

    def deleteAllDesktopGroups(self):
        cmd = "%s --ddc=%s --groupname= --launcher=%s --launcherport=%d" % (self.desktopGroupDeleteScript, self.ddc, self.launcher, self.launcherport)
        self.executeRefScript(cmd)
        
    def deleteDesktopGroup(self, groupname):
        cmd = "%s --ddc=%s --groupname=%s --launcher=%s --launcherport=%d" % (self.desktopGroupDeleteScript, self.ddc, groupname, self.launcher, self.launcherport)
        self.executeRefScript(cmd)

    def registerVMsWithDDC(self, groupname, vms):
        usernames = ["XD\\\\test%d" % i for i in range(1, self.numusers+1)] # need double-\ on command-line
        vmnames = [vm.name for vm in vms]

        # Get hostnames and UUIDs for the VMs, to create host IDs like "q12_eaadc7a5-10ad-282e-5c63-6f597a738755"
        hostids = [
            vm.getHost().getName() + "_" + vm.uuid
            for vm in vms]

        xenrt.TEC().logverbose("Users are: %s" % usernames)
        xenrt.TEC().logverbose("VMs are: %s" % vmnames)
        xenrt.TEC().logverbose("Corresponding host IDs are: %s" % hostids)

        # We need to run the XML-RPC client from within the internal network.
        # Run the 'client-desktopgroup.py' script from ref-base in the helper VM.
        # This client talks to register-desktops/listen.py.
        cmd = "%s --ddc=%s --xenhost=%s --user=%s --pw=%s --groupname=%s --usernames=%s --vms=%s --hostids=%s --launcher=%s --launcherport=%d" % (self.desktopGroupCreateScript, self.ddc, self.xenhost, self.xenuser, self.xenpassword, groupname, ",".join(usernames), ",".join(vmnames), ",".join(hostids), self.launcher, self.launcherport)
        self.executeRefScript(cmd)

    # host should be a Host object
    # useICA = True -> ICA; False -> rdesktop
    def makeLauncherVM(self, name, useICA=True, host=None):
        if host is None:
            host = self.host

        if useICA:
            self.launcherImage = "launcher.img"
            self.launcherName = "launcher-gold"
            self.launcherVMDate = "Wed Jan 13 15:55:00 GMT 2010"
            template = host.chooseTemplate("TEMPLATE_NAME_WINDOWS_XP")
        else: # rdesktop:
            self.launcherImage = "launcher-rdesktop.img"
            self.launcherName = "launcher-rdesktop"
            self.launcherVMDate = "Wed Aug 11 18:07:14 BST 2010"
            template = "NO_TEMPLATE"

        # Import the VM image
        xenrt.TEC().logverbose("Importing launcher VM %s on host %s (using template %s)" % (self.launcherImage, host.getName(), template))
        launcherVM = self.importVMFromRefBase(host, self.launcherImage, self.launcherName, self.goldimagesruuid, template)
        self.putVMonNetwork(launcherVM)

        # Rename the VM to the given name
        xenrt.TEC().logverbose("Renaming launcher VM to %s" % name)
        launcherVM.setName(name)

        # Set the timeoffset
        xenrt.TEC().logverbose("Setting timeoffset for launcher VM %s on host %s to be at '%s'..." % (name, host.getName(), self.launcherVMDate))
        cmds = [
            "then=`date -d '%s' '+%%s'`" % self.launcherVMDate,
            "now=`date '+%s'`",
            "((diff=then-now))",
            "echo diff=$diff",
            "xe vm-param-set uuid=%s platform:timeoffset=$diff" % launcherVM.getUUID(),
        ]
        output = host.execdom0("; ".join(cmds))
        xenrt.TEC().logverbose("output was: %s" % output)

        # Wait for the VM's guest agent to start.
        xenrt.TEC().logverbose("Starting launcher VM...")
        launcherVM.lifecycleOperation("vm-start")
        xenrt.TEC().logverbose("Waiting for guest agent...")
        launcherVM.waitForAgent(600) # Allow 10 mins to boot

        # Wait for the VM's IP to appear in xenstore
        maxwait = 300 # seconds
        waitsofar = 0
        interattemptsleep = 30
        while waitsofar < maxwait:
            xenrt.TEC().logverbose("Attempting to find IP address of launcher...")

            try:
                launcheraddr = host.xenstoreRead("/local/domain/%d/attr/eth0/ip" % launcherVM.getDomid())
                xenrt.TEC().logverbose("successfully read launcheraddr: %s" % launcheraddr)
                break
            except:
                xenrt.TEC().logverbose("failed to read IP address. Sleeping for %d seconds..." % interattemptsleep)
                time.sleep(interattemptsleep)
                waitsofar += interattemptsleep
        # TODO fail if waitsofar >= maxwait

        # Wait for the XML-RPC service on port 8000 to start in it.
        xenrt.TEC().logverbose("Waiting for launcher service to start on %s:%d..." % (launcheraddr, self.wficalauncherport))
        cmd = "%s --launcher=%s --launcherport=%d" % (self.launcherPingScript, launcheraddr, self.wficalauncherport)
        self.executeRefScript(cmd, timeout=300) # Allow 5 mins to start listening
        xenrt.TEC().logverbose("Launcher VM has booted")

        return launcherVM

    def logInToVMsWfica(self, dir, wficalauncher, groupname, user, pw):
        # The launcher VM was created from launcher.img
        wficalauncheraddr = wficalauncher.getHost().xenstoreRead("/local/domain/%d/attr/eth0/ip" % wficalauncher.getDomid())

        cmd = "%s/%s --ddc=%s --groupname=%s --user=%s --pw=%s --domain=%s --launcher=%s --launcherport=%d" % (dir, self.wficaLauncherScript, self.ddc, groupname, user, pw, self.domain, wficalauncheraddr, self.wficalauncherport)
        xenrt.TEC().logverbose("wfica command is %s" % cmd)
        output = self.guest.execguest(cmd, timeout=600) # 10-minute timeout
        xenrt.TEC().logverbose("output is %s" % output)

    def logInToVMsRdesktop(self, dir, launcher, ip, user, pw):
        # The launcher VM was created from launcher-rdesktop.img
        launcheraddr = launcher.getHost().xenstoreRead("/local/domain/%d/attr/eth0/ip" % launcher.getDomid())

        cmd = "%s/%s --host=%s --user=%s --pw=%s --launcher=%s --launcherport=%d" % (dir, self.rdesktopLauncherScript, ip, user, pw, launcheraddr, self.rdesktoplauncherport)
        xenrt.TEC().logverbose("rdesktop command is %s" % cmd)
        output = self.guest.execguest(cmd, timeout=600) # 10-minute timeout
        xenrt.TEC().logverbose("output is %s" % output)

    def createFreshResultsDir(self):
        cmds = [
            "mkdir -p %s" % self.mountpoint,
            "mount -t nfs %s %s" % (self.loginvsidir, self.mountpoint), 
        ]
        self.guest.execguest("; ".join(cmds))

        # Find the number of the next run
        i = int(self.guest.execguest("i=1; while [ -e \"%s/run$i\" ]; do ((i=i+1)); done; echo $i" % self.mountpoint))
        rundir = "run%d" % i
        xenrt.TEC().logverbose("rundir is %s/%s" % (self.mountpoint, rundir))
        cmds = [
            "mkdir %s/%s" % (self.mountpoint, rundir),
            "chmod 777 %s/%s" % (self.mountpoint, rundir),
            "touch %s/%s/logoff.txt" % (self.mountpoint, rundir),
        ]
        self.guest.execguest("; ".join(cmds))

        # Remove all 'isActiveTest' files
        self.guest.execguest("rm %s/\\!\\!\\!_*.IsActiveTest" % self.mountpoint, retval="code") # Suppress error in case it doesn't exist

        # Set the 'isactivetest' pointer to this one
        isactivetestfile = "!!!_%s.IsActiveTest" % rundir
        self.guest.execguest("touch %s/%s" % (self.mountpoint, isactivetestfile.replace("!", "\\!")))
        xenrt.TEC().logverbose("active test is %s" % isactivetestfile)

        return "%s/%s" % (self.mountpoint, rundir)

    def copyRunDirToLogs(self, rundirpath):
        xenrt.TEC().logverbose("copying rundir %s to logs" % rundirpath)
        sftp = self.guest.sftpClient()
        sftp.copyTreeFromRecurse(rundirpath, "%s/run" % xenrt.TEC().getLogdir())
        xenrt.TEC().logverbose("copied rundir to logs")

    # Unused.
    def readUserLoop(self, rundirpath):
        # Find out what the machine name was
        userloopfile = "%s/UserLoop/UserLoop.log" % rundirpath
        userloops = self.guest.execguest("cat %s" % userloopfile).strip()
        lines = userloops.split("\n")
        mapping = {}
        for line in lines:
            elements = line.split(";")
            user = elements[4]
            ucmachine = elements[3]
            mapping[user] = ucmachine
        return mapping

    # wait for @expectedlines to appear in the @sessionnum output file, or timeout if now() > latestTime
    def waitForResultsToAppear(self, rundirpath, sessionnum, expectedlines, latestTime):
        filename = "%s/VSI_log.%04d" % (rundirpath, sessionnum)
        
        numlines = 0
        interattemptsleep = 5 # seconds
        while numlines < expectedlines and time.time() < latestTime:
            time.sleep(interattemptsleep)
            wc = self.guest.execguest("wc -l %s || true" % filename)
            try:
                numlines = int(wc.split(" ")[0])
            except ValueError:
                numlines = 0
            xenrt.TEC().logverbose("attempt (with %.0f secs remaining): file %s, lines %d of %d expected" % (latestTime-time.time(), filename, numlines, expectedlines))
        
        if numlines >= expectedlines:
            xenrt.TEC().logverbose("session %d has completed" % sessionnum)
            return True
        else:
            xenrt.TEC().logverbose("timeout! it looks like session %d was stuck" % sessionnum)
            return False


    # Deprecated? See waitForResultsToAppear instead
    def waitForSessionToComplete(self, rundirpath):
        # Filename that's valid on self.guest.
        sessionid = 1
        loopnum = 1
        ucmachinename = "SCALE1"
        filename = "%s/DetailLogs/%04d_test1_%s_%d.txt" % (rundirpath, sessionid, ucmachinename, loopnum)

        # Wait for that file to contain a "Workload .. FINISH" line.
        # Actually, the file only appears at the end of the test anyway.
        line = ''
        interattemptsleep = 10
        attempts = 0
        maxattempts = 30*60/interattemptsleep # allow 30 minutes
        while not re.search(r";Workload;.*FINISH", line) and attempts < maxattempts:
            time.sleep(interattemptsleep)
            line = self.guest.execguest("tail -n 1 %s || true" % filename).strip()
            attempts = attempts + 1
            xenrt.TEC().logverbose("attempt %d (of max %d): file %s, last line is [%s]" % (attempts, maxattempts, filename, line))
        
        if attempts >= maxattempts:
            xenrt.TEC().logverbose("timeout!")
        else:
            xenrt.TEC().logverbose("session %d loop %d has finished" % (sessionid, loopnum))

