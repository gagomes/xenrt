# XenRT: Test harness for Xen and the XenServer product family
#
# Test cases for LunPerVDI performance tests.
#
# Copyright (c) 2012 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt, string, re
import testcases.xenserver.tc.lunpervdi

class LunPerVDIPerfBase(testcases.xenserver.tc.lunpervdi.LunPerVDI):
    """Base class for testing the performance of Borehamwood fetaures."""

    DISTRO = "oel62" # "ws08r2-x64"
    NO_OF_VDIS = 32
    NO_OF_VMS = 8
    NO_OF_HOSTS = 1
    VDI_SIZE = 10 # GB
    VMMEMORY = 896
    ITERATIONS = 1 # IOZone

    # PostRun variables.
    CLEANUP = True
    DELETE_GUEST = True
    REMOVE_SR = True
    DESTROY_VOLUME = True

    def prepare(self, arglist=[]):
        """Preparation of the test case."""

        # Parse arglists from sequence file.
        self.parseArgLists(arglist)

        # Lock storage resource and access storage manager library functions.
        self.netAppFiler = xenrt.StorageArrayFactory().getStorageArray(xenrt.StorageArrayVendor.NetApp, 
                                                                            xenrt.StorageArrayType.FibreChannel)

        # Get all the hosts.
        self.hosts = [xenrt.TEC().registry.hostGet(hn) for hn in xenrt.TEC().registry.hostList()]
        self.hosts = list(set(self.hosts))
        self.hosts.sort()

        for host in self.hosts:
            host.scanScsiBus()
            host.enableMultipathing()
            self.checkForStaticLuns(host)

        # Setup initial storage configuration.
        self.netAppFiler.provisionLuns(self.NO_OF_VDIS, self.VDI_SIZE, self._createInitiators())
        map(lambda host : self._customiseXenServerTemplates(host), self.hosts)
        map(lambda host : host.scanScsiBus(), self.hosts)

    def parseArgLists(self, arglist):
        """Obtains performance parameters from sequence file."""

        for arg in arglist:
            if arg.startswith('hosts'):
                self.NO_OF_HOSTS = int(arg.split('=')[1])
            if arg.startswith('guests'):
                self.NO_OF_VMS = int(arg.split('=')[1])
            if arg.startswith('distro'):
                self.DISTRO = arg.split('=')[1]
            if arg.startswith('vmmemory'):
                self.VMMEMORY = int(arg.split('=')[1])
            if arg.startswith('lunsize'):
                self.VDI_SIZE = int(arg.split('=')[1])
            if arg.startswith('lunpervdis'):
                self.NO_OF_VDIS = int(arg.split('=')[1])
            if arg.startswith('iozoneiterations'):
                self.ITERATIONS = int(arg.split('=')[1])

    def run(self, arglist=[]):
        """Running the test case."""

        raise xenrt.XRTError("Run method on LunPerVDIPerfBase class is unimplemented.")

    def poolReboot(self, poolTag):
        """Reboot all the hosts in the pool."""

        xenrt.TEC().logverbose("Trying to reboot %d hosts in pool." % (self.NO_OF_HOSTS))

        # Now obtain the time taken to reboot all hosts in the pool.
        timeNow = xenrt.util.timenow()
        for host in self.hosts[::-1]: # reboot slaves first.
            xenrt.TEC().logverbose("Rebooting host %s." % (host))
            host.reboot(timeout=1800)

        xenrt.TEC().logverbose("Waiting for %d hosts to come up." % (self.NO_OF_HOSTS))

        # Waiting for the hosts to come up.
        for host in self.hosts[::-1]: # reboot slaves first.
            xenrt.TEC().logverbose("Waiting for host %s to come up." % (host))
            host.waitForSSH(300, desc=poolTag)
            host.waitForXapi(600, desc=poolTag)
            host.waitForEnabled(900, desc=poolTag)

        xenrt.TEC().logverbose("Total time taken to reboot [%s] %d hosts with %d LUNs mapped: %s seconds." % 
                                    (poolTag, self.NO_OF_HOSTS, self.NO_OF_VDIS, (xenrt.util.timenow() - timeNow)))

        xenrt.TEC().logverbose("Perform a pool check on the hosts [%s]." % (poolTag))

        # Perfrom a pool check once the servers are up.
        self.pool.check()

    def vmStart(self, vmTag):
        """Starting all the guests."""

        xenrt.TEC().logverbose("Starting %d guests in the pool of %d hosts." % (self.NO_OF_VMS, self.NO_OF_HOSTS))

        timeNow = xenrt.util.timenow()
        for guest in self.guests:
            guestTimeNow = xenrt.util.timenow()
            guest.start()
            xenrt.TEC().logverbose("Time taken to start the guest %s: %s seconds." % 
                                    (guest.getName(), (xenrt.util.timenow() - guestTimeNow)))
        xenrt.TEC().logverbose("Total time taken to start %d guests [%s] in a pool of %d hosts with %d luns mapped: %s seconds." % 
                                    (self.NO_OF_VMS, vmTag, self.NO_OF_HOSTS, self.NO_OF_VDIS, (xenrt.util.timenow() - timeNow)))

    def vmShutdown(self, vmTag):
        """Shutting down all the guests."""

        xenrt.TEC().logverbose("Shutting down %d guests in the pool of %d hosts." % (self.NO_OF_VMS, self.NO_OF_HOSTS))

        timeNow = xenrt.util.timenow()
        for guest in self.guests:
            guestTimeNow = xenrt.util.timenow()
            guest.shutdown()
            xenrt.TEC().logverbose("Time taken to shutdown the guest %s: %s seconds." % 
                                    (guest.getName(), (xenrt.util.timenow() - guestTimeNow)))
        xenrt.TEC().logverbose("Total time taken to shutdown %d guests [%s] in a pool of %d hosts with %d luns mapped: %s seconds." % 
                                    (self.NO_OF_VMS, vmTag, self.NO_OF_HOSTS, self.NO_OF_VDIS, (xenrt.util.timenow() - timeNow)))

    def vmUninstall(self, vmTag):
        """Uninstalling all the guests."""

        xenrt.TEC().logverbose("Uninstalling %d guests in the pool of %d hosts." % (self.NO_OF_VMS, self.NO_OF_HOSTS))

        timeNow = xenrt.util.timenow()
        for guest in self.guests:
            guestTimeNow = xenrt.util.timenow()
            try:
                guest.uninstall()
            except Exception, e:
                if re.search("VDI still present after uninstall", str(e)):
                    xenrt.TEC().warning("VDI still present after uninstall is expected for rawHBA guest")
                else:
                    raise e
            xenrt.TEC().logverbose("Time taken to unistall the guest %s: %s seconds." % 
                                    (guest.getName(), (xenrt.util.timenow() - guestTimeNow)))
        xenrt.TEC().logverbose("Total time taken to uninstall  %d guests [%s] in a pool of %d hosts with %d luns mapped: %s seconds." % 
                                    (self.NO_OF_VMS, vmTag, self.NO_OF_HOSTS, self.NO_OF_VDIS, (xenrt.util.timenow() - timeNow)))

    def installIOZoneAndRun(self, vm):
        """Installs and runs an IOZone test on guest."""

        # Test parameters.
        testTypes = [0]
        iozonePath = "/root/iozone/iozone"

        # Installing IOZone test tool on guest.
        xenrt.TEC().logverbose("Installing IOZone on guest %s." % vm.getName())
        vm.execguest("wget %s/iozone.tgz -O /root/iozone.tgz" %
                            (xenrt.TEC().lookup("TEST_TARBALL_BASE")))
        vm.execguest("tar xvzf /root/iozone.tgz -C /root")
        vm.execguest("cd /root/iozone && make linux")

        # Running the IOZone tests
        xenrt.TEC().logverbose("Running %d IOZone iterations on %s" % (self.ITERATIONS, vm.getName()))
        for i in range(self.ITERATIONS):
            testTypeParams = reduce(string.join, " ", ["-i %s" % (x) for x in testTypes])
            data = vm.execguest("%s %s "
                                     "-a "      # Auto mode. Required.
                                     "-w "      # Don't delete the target file.
                                     "-n 1g "   # Test files from 1 Gb.
                                     "-g 1g "   # Test files up to 2Gb.
                                     "-r 16m "  # Test only 16Mb records.
                                     "-f iozone_target" %  # iozone target file.
                                     (iozonePath, testTypeParams),
                                      timeout=3600)
            xenrt.TEC().logverbose("IOZone test data on iteration %d: %s" % (i, data))

    def startIOZoneParallely(self):
        """Install IOZone in each guests parallelly."""

        xenrt.TEC().logverbose("Starting IOZone parallelly in %d guests." % (self.NO_OF_VMS))

        timeNow = xenrt.util.timenow()
        iozoneTasks = map(lambda x: xenrt.PTask(self.installIOZoneAndRun,
                                            self.guests[x]),
                                            range(len(self.guests)))
        xenrt.TEC().logverbose("Guest IOZone Installation pTasks are %s" % iozoneTasks)
        iozoneFarm = xenrt.pfarm(iozoneTasks)
        xenrt.TEC().logverbose("Time taken to install IOZone tool on %d guests in parallel: %s seconds." % 
                                    (self.NO_OF_VMS, (xenrt.util.timenow() - timeNow)))

class LunPerVDIPerfTest(LunPerVDIPerfBase):
    """Performance test on a pool of hosts with number of guests."""

    def prepare(self, arglist=[]):

        LunPerVDIPerfBase.prepare(self, arglist)

        for host in self.hosts:
            # Customise XenServer guest template support RawHBA VDIs.
            self._customiseXenServerTemplates(host)

    def vmInstall(self):
        """Installs guests in parallel using XenRT pfarm."""

        xenrt.TEC().logverbose("Installing %d guests in parallel." % (self.NO_OF_VMS))

        rootDiskVDIs = self.vdiuuids[:self.NO_OF_VMS]
        rootDiskVDIs = [list(vdi) for vdi in zip(rootDiskVDIs)] # obtaining each vdi as a list.
        xenrt.TEC().logverbose("rootDiskVDIs: %s" % rootDiskVDIs)
        xenrt.TEC().logverbose("length of rootDiskVDIs: %s" % len(rootDiskVDIs))

        timeNow = xenrt.util.timenow()
        hostIndexDevider = (self.NO_OF_VMS / self.NO_OF_HOSTS)
        pTasks = map(lambda x: xenrt.PTask(self.hosts[x/hostIndexDevider].createBasicGuest,
                                            distro=self.DISTRO,
                                            memory=self.VMMEMORY,
                                            rawHBAVDIs=rootDiskVDIs[x]),
                                            range(self.NO_OF_VMS))

        xenrt.TEC().logverbose("Guest installation pTasks are %s" % pTasks)
        self.guests = xenrt.pfarm(pTasks)
        xenrt.TEC().logverbose("Time taken to install %d guests in parallel on %d hosts with %d LUNs mapped: %s seconds." % 
                                    (self.NO_OF_VMS, self.NO_OF_HOSTS, self.NO_OF_VDIS, (xenrt.util.timenow() - timeNow)))

        if (len(self.guests) != self.NO_OF_VMS):
            raise xenrt.XRTFailure("The requisite of the test demands %d guests." % (self.NO_OF_VMS))
        else:
            xenrt.TEC().logverbose("Number of guests installed for the test: %d" % len(self.guests))

    def attachExtraDisks(self):
        """Attaches extra disks to each guest in test."""

        extraDisks = (self.NO_OF_VDIS / self.NO_OF_VMS ) -1
        xenrt.TEC().logverbose("Attaching %d extra disks to each guests." % (extraDisks))

        extraDiskVDIs = self.vdiuuids[self.NO_OF_VMS:]
        xenrt.TEC().logverbose("extraDiskVDIs: %s" % extraDiskVDIs)

        # Now attaching extra-disks to each VM from the remaining.
        timeNow = xenrt.util.timenow()
        if (extraDisks == 0):
            xenrt.TEC().logverbose("No extra disks to be added.")
        else:
            xenrt.TEC().logverbose("Attaching %d extra disks to each." %  extraDisks)
            groupedVDIList = [list(vdiTuples) for vdiTuples in zip(*(iter(extraDiskVDIs),) * extraDisks)]
            if (len(groupedVDIList) == len(self.guests)):
                for (guest, tupleList) in zip(self.guests, groupedVDIList):
                    diskTimeNow = xenrt.util.timenow()
                    for newVDI in tupleList:
                        args = []
                        # Default to lowest available device number.
                        allowed = guest.getHost().genParamGet("vm", guest.getUUID(), "allowed-VBD-devices")
                        userdevice = str(min([int(x) for x in allowed.split("; ")]))
                        args.append("device=%s" % (userdevice))
                        args.append("vdi-uuid=\"%s\"" % (newVDI))
                        args.append("vm-uuid=\"%s\"" % (guest.getUUID()))
                        args.append("mode=RW")
                        args.append("type=Disk")
                        guest.getHost().getCLIInstance().execute("vbd-create", string.join(args), ignoreerrors=True)

                        # Format the extra disk and write some thing to it.
                        xenrt.TEC().logverbose("TODO: Disk is not formatted yet!!!!")

                    xenrt.TEC().logverbose("Time taken to attach %d extra disks to guest %s: %s seconds." % 
                                            (extraDisks, guest.getName(), (xenrt.util.timenow() - diskTimeNow)))
            else:
                raise xenrt.XRTFailure("There is a mis-calculation. No. of guests %d No. of extra disks %d" %
                                        (len(self.guests), len(groupedVDIList)))
        xenrt.TEC().logverbose("Time taken to attach %d disks to %d guests in a pool of %d hosts with %d LUNs mapped: %s seconds." % 
                                    (extraDisks, self.NO_OF_VMS, self.NO_OF_HOSTS, self.NO_OF_VDIS, (xenrt.util.timenow() - timeNow)))

    def run(self, arglist=[]):

        extraDisks = (self.NO_OF_VDIS / self.NO_OF_VMS ) -1

        xenrt.TEC().logverbose("Performance testing rawHBA SR on a pool of %d hosts with %d guests, attached with %d extra disks" %
                                    (self.NO_OF_HOSTS, self.NO_OF_VMS, extraDisks))

        if (len(self.hosts) != self.NO_OF_HOSTS):
            raise xenrt.XRTFailure("The requisite of the test demands %d hosts in a pool." % (self.NO_OF_HOSTS))

        xenrt.TEC().logverbose("Creating a pool of %d hosts." % (self.NO_OF_HOSTS))

        # 1. Create the pool of servers.
        self.pool = xenrt.lib.xenserver.poolFactory(self.hosts[0].productVersion)(self.hosts[0])
        self.pool.master = self.hosts[0]

        # Add all remaining hosts to the pool.
        for host in self.hosts[1:]:
            # The host joining the pool cannot contain any shared storage.
            for sr in host.minimalList("sr-list", args="content-type=iso type=iso"):
                host.forgetSR(sr)
            self.pool.addHost(host)
        self.pool.setPoolParam("name-label", "rawHBAPool")
        self.pool.check()

        xenrt.TEC().logverbose("Creating a rawHBA SR on the pool of %d hosts." % (self.NO_OF_HOSTS))

        # 2. Create the rawHBA SR.
        timeNow = xenrt.util.timenow()
        self.createSR()
        xenrt.TEC().logverbose("Time taken to create rawHBA SR on pool master with %d LUNs mapped: %s seconds." % 
                                    (self.NO_OF_VDIS, (xenrt.util.timenow() - timeNow)))

        # Verifying the rawHBA SR.
        self.checkSR()

        # Set the pool default SR to be the RawHBA SR.
        self.pool.setPoolParam("default-SR", self.sruuid)

        xenrt.TEC().logverbose("There are %s LUN/VDIs in the test." % len(self.vdiuuids))

        if (len(self.vdiuuids) != self.NO_OF_VDIS):
            raise xenrt.XRTFailure("The requisite of the test demands %d LUN/VDIs in the system." % (self.NO_OF_VDIS))

        xenrt.TEC().logverbose("Scanning the rawHBA SR on the pool of %d hosts." % (self.NO_OF_HOSTS))

        # 3. Get time taken to scan the rawHBA SR.
        timeNow = xenrt.util.timenow()
        self.sr.scan()
        xenrt.TEC().logverbose("Time taken to scan the rawHBA SR on master with %d LUNs mapped: %s seconds." % 
                                    (self.NO_OF_VDIS, (xenrt.util.timenow() - timeNow)))

        # 4. Now find out the time taken to reboot all hosts in the pool.
        rebootTag = "After creating rawHBA SR Reboot"
        self.poolReboot(rebootTag)

        # 5. Create and install number of guessts in parallel using XenRT pfarm.
        self.vmInstall()

        # 6. Now attaching extra-disks to each VM from the remaining.
        self.attachExtraDisks()

        # 7. Installing IOZone test tool on each guest and running in parallel using XenRT pfarm.
        self.startIOZoneParallely()

        # 8. Time taken to shutdown all the guests serially with extra disks attached.
        vmTag = ("with %d extra disks attached" % (extraDisks))
        self.vmShutdown(vmTag)

        # 9. Time taken to start all the guests serially with extra disks attached.
        vmTag = ("with %d extra disks attached" % (extraDisks))
        self.vmStart(vmTag)

        # 10 Rebooting all hosts in pool with all guests installed and each guest attached with extra disks.
        rebootTag = "After installing the guests Reboot"
        self.poolReboot(rebootTag)

        # 11. Starting the guests again.
        vmTag = "after pool reboot"
        self.vmStart(vmTag)

        # 12. Time taken to shutdown the guests with extra disks attached.
        vmTag = "before un-installation"
        self.vmShutdown(vmTag)

        # 13. Time taken to uninstall the guests with extra disks attached.
        vmTag = ("with %d extra disks attached" % (extraDisks))
        self.vmUninstall(vmTag)

        xenrt.TEC().logverbose("Destroying the rawHBA SR on the pool of %d hosts." % (self.NO_OF_HOSTS))

        # 14. Destroy the rawHBA SR on the pool.
        timeNow = xenrt.util.timenow()
        self.deleteSR()
        xenrt.TEC().logverbose("Time taken to destroy the rawHBA SR on %d hosts pool: %s seconds." % 
                                    (self.NO_OF_HOSTS, (xenrt.util.timenow() - timeNow)))

class LunPerVDIPerfMsci(LunPerVDIPerfBase):
    """Replicating MSCI production configration on a pool of hosts with number of guests."""

    def vmInstall(self, lvmoFCSRuuid):
        """Installs guests in parallel using XenRT pfarm."""

        xenrt.TEC().logverbose("Installing %d guests in parallel." % (self.NO_OF_VMS))

        rootDiskSRUUIDs = lvmoFCSRuuid[:self.NO_OF_VMS]
        xenrt.TEC().logverbose("rootDiskSRUUIDs: %s" % rootDiskSRUUIDs)
        xenrt.TEC().logverbose("length of rootDiskSRUUIDs: %s" % len(rootDiskSRUUIDs))

        timeNow = xenrt.util.timenow()
        hostIndexDevider = (self.NO_OF_VMS / self.NO_OF_HOSTS)
        pTasks = map(lambda x: xenrt.PTask(self.hosts[x/hostIndexDevider].createBasicGuest,
                                            distro=self.DISTRO,
                                            memory=self.VMMEMORY,
                                            sr=rootDiskSRUUIDs[x]),
                                            range(self.NO_OF_VMS))
        xenrt.TEC().logverbose("Guest installation pTasks are %s" % pTasks)
        self.guests = xenrt.pfarm(pTasks)
        xenrt.TEC().logverbose("Time taken to install %d guests in parallel on %d hosts with %d LUNs mapped: %s seconds." % 
                                    (self.NO_OF_VMS, self.NO_OF_HOSTS, self.NO_OF_VDIS, (xenrt.util.timenow() - timeNow)))

        if (len(self.guests) != self.NO_OF_VMS):
            raise xenrt.XRTFailure("The requisite of the test demands %d guests." % (self.NO_OF_VMS))
        else:
            xenrt.TEC().logverbose("Number of guests installed for the test: %d" % len(self.guests))

    def attachExtraDisks(self, lvmoFCSRuuid):
        """Attaches extra disks to each guest in test."""

        extraDisks = (self.NO_OF_VDIS / self.NO_OF_VMS ) -1
        xenrt.TEC().logverbose("Attaching %d extra disks to each guests." % (extraDisks))

        extraDiskSRUUIDs = lvmoFCSRuuid[self.NO_OF_VMS:]
        xenrt.TEC().logverbose("extraDiskSRUUIDs: %s" % extraDiskSRUUIDs)

        # Now attaching extra-disks to each VM from the remaining.
        timeNow = xenrt.util.timenow()
        if (extraDisks == 0):
            xenrt.TEC().logverbose("No extra disks to be added.")
        else:
            xenrt.TEC().logverbose("Attaching %d extra disks to each." %  extraDisks)
            groupedSRUUIDList = [list(vdiTuples) for vdiTuples in zip(*(iter(extraDiskSRUUIDs),) * extraDisks)]
            if (len(groupedSRUUIDList) == len(self.guests)):
                for (guest, tupleSRList) in zip(self.guests, groupedSRUUIDList):
                    diskTimeNow = xenrt.util.timenow()
                    for sruuid in tupleSRList:
                        srsize = int(self.hosts[0].genParamGet("sr", sruuid, "physical-size"))
                        utilisation = int(self.hosts[0].genParamGet("sr", sruuid, "physical-utilisation"))
                        allowed = guest.getHost().genParamGet("vm", guest.getUUID(), "allowed-VBD-devices")
                        device = str(min([int(x) for x in allowed.split("; ")]))
                        guest.createDisk(sizebytes=(srsize-utilisation-xenrt.GIGA), sruuid=sruuid, userdevice=device)
                        # Format the extra disk and write some thing to it.
                        xenrt.TEC().logverbose("TODO: Disk is formatted. But nothing is written yet!!!!")

                    xenrt.TEC().logverbose("Time taken to attach %d extra disks to guest %s: %s seconds." % 
                                            (extraDisks, guest.getName(), (xenrt.util.timenow() - diskTimeNow)))
            else:
                raise xenrt.XRTFailure("There is a mis-calculation. No. of guests %d No. of extra disks %d" %
                                        (len(self.guests), len(groupedSRUUIDList)))
        xenrt.TEC().logverbose("Time taken to attach %d disks to %d guests in a pool of %d hosts with %d LUNs mapped: %s seconds." % 
                                    (extraDisks, self.NO_OF_VMS, self.NO_OF_HOSTS, self.NO_OF_VDIS, (xenrt.util.timenow() - timeNow)))


    def run(self, arglist=[]):

        extraDisks = (self.NO_OF_VDIS / self.NO_OF_VMS ) -1

        xenrt.TEC().logverbose("Performance testing lvmohba SR on a pool of %d hosts with %d guests, attached with %d extra disks" %
                                    (self.NO_OF_HOSTS, self.NO_OF_VMS, extraDisks))

        if (len(self.hosts) != self.NO_OF_HOSTS):
            raise xenrt.XRTFailure("The requisite of the test demands %d hosts in a pool." % (self.NO_OF_HOSTS))

        xenrt.TEC().logverbose("Creating a pool of %d hosts." % (self.NO_OF_HOSTS))

        # 1. Create the pool of servers.
        self.pool = xenrt.lib.xenserver.poolFactory(self.hosts[0].productVersion)(self.hosts[0])
        self.pool.master = self.hosts[0]

        # Add all remaining hosts to the pool.
        for host in self.hosts[1:]:
            # The host joining the pool cannot contain any shared storage.
            for sr in host.minimalList("sr-list", args="content-type=iso type=iso"):
                host.forgetSR(sr)
            self.pool.addHost(host)
        self.pool.setPoolParam("name-label", "lvmoHBAPool")
        self.pool.check()

        xenrt.TEC().logverbose("Creating %d lvmoHBA SR on the pool of %d hosts." % (self.NO_OF_VDIS, self.NO_OF_HOSTS))

        # Find the SCSIIDs by diffing /dev/disk/by-scsid
        scsiIDs = self.hosts[0].execdom0("ls /dev/disk/by-scsid").strip().split("\n")
        scsiIDs = [x for x in scsiIDs if x.startswith("360a98000")] # only netapp luns that we created for the test.
        scsiIDs.sort() # sort it before whole list comparision.

        xenrt.TEC().logverbose("Found %d SCSIDs on the master %s: %s" % (len(scsiIDs), self.hosts[0], scsiIDs))

        if (self.NO_OF_VDIS != len(scsiIDs)):
            raise xenrt.XRTFailure("We have created %d LUNs on the filer. Reported only %d SCSIDs." % (self.NO_OF_VDIS, len(scsiIDs)))

        lvmohbaSRuuid = [] # list of lvmoHBA SR uuids
        lvmohbaSRObject = []
        counter = 0
        # 2. Create lvmoHBA SRs on the master.
        timeNow = xenrt.util.timenow()
        for scsid in scsiIDs:
            fcName = ("lvmoHBASR%d" % counter)
            fcSR = xenrt.lib.xenserver.FCStorageRepository(self.hosts[0], fcName)
            lvmohbaSRObject.append(fcSR)
            fcSR.create(scsid)
            lvmohbaSRuuid.append(fcSR.uuid)
            counter = counter + 1

        xenrt.TEC().logverbose("Time taken to create %d lvmoHBA SR on master %s is %s seconds." % 
                                (self.NO_OF_VDIS, self.hosts[0], (xenrt.util.timenow() - timeNow)))

        if (self.NO_OF_VDIS != len(lvmohbaSRuuid)):
            raise xenrt.XRTFailure("We have created %d LUNs on the filer. Reported only %d lvmohbaSRuuid." % (self.NO_OF_VDIS, len(lvmohbaSRuuid)))

        xenrt.TEC().logverbose("Scanning all the lvmoHBA SR on the pool of %d hosts." % (self.NO_OF_HOSTS))

        # 3. Time taken to scan the lvmoHBA SR.
        timeNow = xenrt.util.timenow()
        for sr in lvmohbaSRObject:
            sr.scan()
        xenrt.TEC().logverbose("Time taken to scan %d lvmoHBA SR on the pool with %d LUNs mapped: %s seconds." % 
                                    (self.NO_OF_VDIS, self.NO_OF_VDIS, (xenrt.util.timenow() - timeNow)))

        # 4. Time taken to reboot all hosts in the pool after creating the SR.
        rebootTag = "After creating lvmoHBA SR Reboot"
        self.poolReboot(rebootTag)

        # 5. Create and install number of guessts in parallel using XenRT pfarm.
        self.vmInstall(lvmohbaSRuuid)

        # 6. Now attaching extra-disks to each VM from the remaining.
        self.attachExtraDisks(lvmohbaSRuuid)

        # 7. Installing IOZone test tool on each guest and running in parallel using XenRT pfarm.
        self.startIOZoneParallely()

        # 8. Time taken to shutdown all the guests serially with extra disks attached.
        vmTag = ("with %d extra disks attached" % (extraDisks))
        self.vmShutdown(vmTag)

        # 9. Time taken to start all the guests serially with extra disks attached.
        vmTag = ("with %d extra disks attached" % (extraDisks))
        self.vmStart(vmTag)

        # 10 Rebooting all hosts in pool with all guests installed and each guest attached with extra disks.
        rebootTag = "After installing the guests Reboot"
        self.poolReboot(rebootTag)

        # 11. Starting the guests again.
        vmTag = "after pool reboot"
        self.vmStart(vmTag)

        # 12. Time taken to shutdown the guests with extra disks attached.
        vmTag = "before un-installation"
        self.vmShutdown(vmTag)

        # 13. Time taken to uninstall the guests with extra disks attached.
        vmTag = ("with %d extra disks attached" % (extraDisks))
        self.vmUninstall(vmTag)

        xenrt.TEC().logverbose("Destroying the lvmoHBA SR on the pool of %d hosts." % (self.NO_OF_HOSTS))

        # 14. Destroy the lvmoHBA SR on the pool.
        timeNow = xenrt.util.timenow()
        for sruuid in lvmohbaSRuuid:
            self.hosts[0].destroySR(sruuid)
        xenrt.TEC().logverbose("Time taken to destroy the lvmoHBA SR on %d hosts pool: %s seconds." % 
                                    (self.NO_OF_HOSTS, (xenrt.util.timenow() - timeNow)))
