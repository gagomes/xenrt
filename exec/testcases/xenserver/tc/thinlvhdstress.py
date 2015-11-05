import xenrt
from testcases.xenserver.tc.perf import libsynexec
from xenrt.lazylog import log, warning, step

class TCParallelWriting(xenrt.TestCase):
    """Verify xenvm allocator works well and data integrity"""

    VMS = False
    VDI_COUNT = 5
    VDI_SIZE = 2 # in GiB
    SEQUENTIAL = True
    ITERATION = 1

    def getPhysicalUtil(self):
        """Utility function to check current physical-utilisation of SR"""

        sr = self.host.lookupDefaultSR()
        self.host.getCLIInstance().execute("sr-scan uuid=%s" % sr)

        stat = int(self.host.genParamGet("sr", sr, "physical-utilisation"))

        # TODO: following codes are not required after CP-14242
        if not xenrt.TEC().lookup("NO_XENVMD", False, boolean=True):
            srobj = xenrt.lib.xenserver.getStorageRepositoryClass(self.host, sr).fromExistingSR(self.host, sr)
            if srobj.thinProvisioning:
                if self.host.pool:
                    for host in self.host.pool.getHosts():
                        output = host.execRawStorageCommand(srobj, "lvs /dev/VG_XenStorage-%s --nosuffix | grep %s-free" % (sr, host.uuid))
                        stat -= int(output.split()[-1])
                else:
                    output = self.host.execRawStorageCommand(srobj, "lvs /dev/VG_XenStorage-%s --nosuffix | grep %s-free" % (sr, self.host.uuid))
                    stat -= int(output.split()[-1])

        return stat

    def getParam(self, paramname, default=None, boolean=False):
        """Utility function to get argument from seq or TEC"""

        var = self.args.get(paramname, default)
        if boolean and type(var) == type("a"):
            if var.lower().strip() in ["yes", "true"]:
                var = True
            else:
                var = False
        var = xenrt.TEC().lookup(paramname, var, boolean)
        var = xenrt.TEC().lookup(paramname.upper(), var, boolean)

        return var

    def __writeOnDom0(self):
        """Run writing concurrently."""

        # prepare scripts
        if self.sequential:
            cmd = "dd if=/dev/zero of=/dev/\\${DEVICE} bs=1M count=%d" % \
                (self.vdisize / xenrt.MEGA)
            chkcmd = "ps -efl | grep '[d]d if=/dev/zero'"
        else:
            cmd = "%s/remote/patterns.py /dev/\\${DEVICE} %d write 3" % \
                (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), self.vdisize)
            chkcmd = "ps -efl | grep '[p]atterns.py'"

        cmd = "while [ -f /tmp/hold_running ] ; do sleep 0.1 ; done ; %s" % cmd

        self.host.execdom0("echo \"%s\" > /tmp/cmd.sh" % cmd)
        self.host.execdom0("chmod u+x /tmp/cmd.sh")

        # Run all commands with bash scripts first.
        self.host.execdom0("touch /tmp/hold_running")
        for vdi in self.vdis:
            self.host.execdom0("(/opt/xensource/debug/with-vdi %s /tmp/cmd.sh) >/dev/null 2>&1 </dev/null &" % vdi)
        # Triggering all the process at once.
        self.host.execdom0("rm -f /tmp/hold_running")

        waiting = 120 # mins.
        while waiting > 0:
            xenrt.sleep(300, log=False)
            waiting -= 5
            try:
                pslist = self.host.execdom0(chkcmd).strip().splitlines()
            except:
                pslist = []
            if len(pslist) == 0:
                log("Cannot find running process.")
                break
            log("Found %d processes running." % len(pslist))

        log("Checking processes.")
        ptotal = []
        pkilled = []
        pfailed = []
        try:
            pslist = self.host.execdom0(chkcmd).strip().splitlines()
        except:
            palist = []
        for line in pslist:
            pid = line.split()[3]
            ptotal.append(pid)
            try:
                self.host.dom0("kill -9 %s" % pid)
                pkilled.append(pid)
            except:
                pfailed.append(pid)

        if ptotal:
            warning("Found %d processes are still running." % len(ptotal))
            log("Killed: %s" % pkilled)
            log("Failed to killed: %s" % pfailed)

    def __verifyOnDom0(self):
        """Verifying written data from Dom0"""

        # Because all VDIs have same data.
        refmd5 = ""
        if self.sequential:
            cmd = "md5sum /dev/\\${DEVICE}"
            for vdi in self.vdis:
                md5 = self.host.execdom0("/opt/xensource/debug/with-vdi %s /tmp/cmd.sh" % vdi).split()[0]
                if refmd5 == "":
                    refmd5 = md5
                elif refmd5 != md5:
                    raise xenrt.XRTFailure("VDIs have different data while all VDIs supposed to be filled with zero")
        else:
            cmd = "%s/remote/patterns.py /dev/\\${DEVICE} %d read 3" % \
                (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), self.vdisize)
            failed = 0
            for vdi in self.vdis:
                failed += self.host.execdom0("/opt/xensource/debug/with-vdi %s /tmp/cmd.sh" % vdi, retval="code")
            if failed > 0:
                raise xenrt.XRTFailure("%d VDIs are corrupted." % failed)

    def __writeOnGuest(self):
        """Running writing data from guests."""

        for guest in self.guests:
            if self.sequential:
                cmd = "dd if=/dev/zero of=/dev/%s bs=1M count=%d" % \
                    (guest.targetDevice, (self.vdisize / xenrt.MEGA))
            else:
                cmd = "%s/remote/patterns.py /dev/%s %d write 3" % \
                    (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), guest.targetDevice, self.vdisize)
            guest.execguest("echo \"%s\" > /tmp/cmd.sh" % cmd)
            guest.execguest("chmod u+x /tmp/cmd.sh")
            libsynexec.start_slave(guest, self.jobid)

        libsynexec.start_master_in_dom0(self.host, "/bin/bash /tmp/cmd.sh", self.jobid, self.vdicount, self.timeout)

        results = {}
        for guest in self.guests:
            results[guest.getName()] = libsynexec.get_slave_log(guest)

        log("Obtained log from guests: %s" % results)

    def __verifyOnGuest(self):
        """Verifying written data from guests."""

        # Because all VDIs have same data.
        refmd5 = ""
        if self.sequential:
            refmd5 = ""
            for guest in self.guests:
                md5 = guest.execguest("md5sum /dev/%s" % guest.targetDevice).splite()[0]
                if refmd5 == "":
                    refmd5 = md5
                elif refmd5 != md5:
                    raise xenrt.XRTFailure("VDIs have different data while all VDIs supposed to be filled with zero")

        else:
            failed = 0
            for guest in self.guests:
                failed = guest.execguest("%s/remote/patterns.py /dev/%s %d read 3" % \
                    (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), guest.targetDevice, self.vdisize), retval="code")
            if failed > 0:
                raise xenrt.XRTFailure("%d VDIs are corrupted." % failed)

    def prepareIteration(self):
        """Prepare each iterations. All VDIs will be created in this process."""

        step("Creating VDIs and attaching them")
        if self.runOnGuest:
            log("Creating VDIs and attching to test guests.")
            for guest in self.guests:
                guest.setState("UP")
                guest.targetDevice = guest.createDisk(sizebytes = self.vdisize, sruuid=self.sr, returnDevice=True)
        else:
            log("Creating VDIs")
            self.vdis = [self.host.createVDI(sizebytes = self.vdisize) for i in xrange(self.vdicount)]
            log("Created %d VDIs: %s" % (self.vdicount, self.vdis))

        log("After creating %d VDIs: %d" % (self.vdicount, self.getPhysicalUtil()))

    def finalizeIteration(self):
        """Clean up the iteration. All VDIs will be detached and destroyed."""

        step("Destroying all test VDIs")
        if self.runOnGuest:
            for guest in self.guests:
                guest.setState("DOWN")
                guest.destroyAdditionalDisks()
                guest.setState("UP")
        else:
            map(self.host.destroyVDI, self.vdis)
            self.vdis = []

    def runWritingTest(self):
        """Wrapper for writing method"""

        if self.runOnGuest:
            self.__writeOnGuest()
        else:
            self.__writeOnDom0()

    def verifyWrittenData(self):
        """Wrapper for verifying method"""

        if self.runOnGuest:
            self.__verifyOnGuest()
        else:
            self.__verifyOnDom0()

    def __obtainTestVars(self, arglist, printAfterObtain = False):
        """Setting up test vars after reading them from seq and TEC."""

        self.args = self.parseArgsKeyValue(arglist)
        self.sequential = self.getParam("sequential", self.SEQUENTIAL, True)
        self.vdisize = int(self.getParam("vdisize", self.VDI_SIZE)) * xenrt.GIGA
        self.iteration = int(self.getParam("iteration", self.ITERATION))
        self.vdicount = int(self.getParam("vdicount", self.VDI_COUNT))
        self.runOnGuest = self.getParam("vms", self.VMS, True)
        # used to identify synexec.
        # This should NOT be used in multiple TC at the same time.
        self.jobid = int(xenrt.TEC().gec.config.lookup("JOBID", None))

        if printAfterObtain:
            log("===== VARS =====")
            log("vdicount: %d" % self.vdicount)
            log("vdisize: %d" % self.vdisize)
            log("sequential: %s" % self.sequential)
            log("iteration: %d" % self.iteration)
            log("Using VM: %s" % self.runOnGuest)
            log("================")

    def prepareGuests(self, host):
        """
        Prepare given host for test env.
        """

        log("Creating new master guest on host %s." % host.getName())
        localsr = host.getLocalSR()
        master = host.createGenericLinuxGuest(sr = localsr)
        self.uninstallOnCleanup(master)

        master.setState("UP")
        libsynexec.initialise_slave(master)
        master.setState("DOWN")

        counts = self.vdicount / len(host.pool.getHosts())
        for i in xrange(counts):
            guest = master.cloneVM()
            self.uninstallOnCleanup(guest)
            guest.setState("UP")
            self.guests.append(guest)

    def prepare(self, arglist=[]):

        self.host = self.getDefaultHost()
        self.pool = self.host.pool
        if self.pool:
            self.host = self.pool.master
        self.sr = self.host.lookupDefaultSR()
        self.timeout = 180 * 60 # timeout of 3 hours per iteration.

        self.__obtainTestVars(arglist, printAfterObtain = True)

        self.guests = []
        if self.runOnGuest:
            xenrt.pfarm([xenrt.PTask(self.prepareGuests, host) for host in self.pool.getHosts()])
            libsynexec.initialise_master_in_dom0(self.host)
        else:
            log("Test are running on the host.")

    def run(self, arglist=[]):

        sruuid = self.host.lookupDefaultSR()
        log("SR param: %s" % self.host.genParamGet("sr", sruuid, "sm-config"))

        exceptions = []
        for i in xrange(self.iteration):
            log("Iteration %d..." % (i + 1))

            prev = self.getPhysicalUtil()
            log("Initial physical utilisation: %d" % prev)

            # If prepare fails, iteration won't run properly.
            # Allow raising exception and halt running.
            self.prepareIteration()
            try:
                self.runWritingTest()

                # Check VDIs' size are increased as expected.
                final = self.getPhysicalUtil()
                log("Final physical utilisation: %d" % final)
                expected = prev + (self.vdicount * self.vdisize)
                log("Expected Utilisation: %d" % expected)
                if final < expected:
                    raise xenrt.XRTFailure("After writing, SR utilisation has not increased as expected." \
                            "Expected: >= %d Found: %d" % (expected, final))

                self.verifyWrittenData()

            except Exception as e:
                warning("Iteration %d failed due to exception: %s" % ((i + 1), str(e)))
                exceptions.append(str(e))

            finally:
                # If finalizing fails, coming iteration won't run properly anyway.
                # Allow raising exception and halt running.
                self.finalizeIteration()

        if exceptions:
            log("Found following errors:")
            for exception in exceptions:
                log(exception)
            raise xenrt.XRTFailure("Failed to run %d (out of %d) iteration(s)." % (len(exceptions), self.iteration))

