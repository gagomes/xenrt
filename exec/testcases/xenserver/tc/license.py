#
# XenRT: Test harness for Xen and the XenServer product family
#
# XenServer licensing test cases
#
# Copyright (c) 2009 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import string, re, time, traceback, sys
import xenrt, xenrt.lib.xenserver, xenrt.lib.xenserver.cli

class _LicenseBase(xenrt.TestCase):
    """Base class for Licensing test cases"""
    # The license SKU to test (None implies use the default license on the host)
    SKU = None
    # The license edition to test
    EDITION = None
    # The feature to test
    FEATURE = None
    # Do we expect it to be allowed (or a number if it is a specific limit)
    ALLOWED = False
    # Internal fields
    # Features that require multiple hosts to test
    _REQUIRES_MULTIPLE_HOSTS = ["Pooling"]
    # Full list of known features that can be tested
    _KNOWN_FEATURES = ["ConcurrentVMs", "MaxMemory", "VLAN", "QoS", "SharedSR",
                       "Pooling", "HA", "Kirkwood", "MarathonPCI", "EmailAlerts",
                       "DMC", "Checkpoint", "CPUMask", "Caching", "VMPP", "DVSC",
                       "VGPU", "DR"]

    def prepare(self, arglist=None):
        self.allowed = self.ALLOWED

        # Before going any further, check that it's a known feature
        if not self.FEATURE in self._KNOWN_FEATURES and \
           self.FEATURE != "Multiple":
            raise xenrt.XRTError("Unknown license feature %s" % (self.FEATURE))

        # Prepare the relevant hosts, and get the right license applied
        self.host = self.getDefaultHost()
        self.otherHosts = []

        if self.FEATURE in self._REQUIRES_MULTIPLE_HOSTS:
            # We need more than one host, so get all the ones we have
            i = 1
            while True:
                h = self.getHost("RESOURCE_HOST_%d" % (i))
                if h:
                    self.otherHosts.append(h)
                else:
                    break
                i += 1

        if self.SKU:
            xenrt.TEC().logverbose("Licensing %s with %s" % 
                                   (self.host.getName(), self.SKU))
            self.host.license(sku=self.SKU)
            for h in self.otherHosts:
                xenrt.TEC().logverbose("Licensing %s with %s" %
                                       (h.getName(), self.SKU))
                h.license(sku=self.SKU)
        elif self.EDITION:
            xenrt.TEC().logverbose("Applying %s edition to %s" % (self.EDITION,
                                                           self.host.getName()))
            self.host.license(edition=self.EDITION)
            for h in self.otherHosts:
                xenrt.TEC().logverbose("Applying %s edition to %s" %
                                       (self.EDITION, h.getName()))
                h.license(edition=self.EDITION)
        else:
            # To make triage easier, display the current licenses
            cli = self.host.getCLIInstance()
            xenrt.TEC().logverbose("Retrieving license for %s" %
                                   (self.host.getName()))
            cli.execute("host-license-view","host-uuid=%s" %
                                            (self.host.getMyHostUUID()))
            for h in self.otherHosts:
                cli = h.getCLIInstance()
                xenrt.TEC().logverbose("Retreving license for %s" %
                                       (h.getName()))
                cli.execute("host-license-view","host-uuid=%s" %
                                                (h.getMyHostUUID()))

    def run(self, arglist=None):
        # Call the  method (we've already validated this is a known feature)
        actualMethod = eval("self.feature" + self.FEATURE)
        actualMethod()

    def waitForHostFreeMemory(self, needmb):
        for i in range(5):
            # Check there's enough memory on the host
            m = self.host.getFreeMemory()
            if m >= needmb:
                return m
            time.sleep(60)
        # See if we can use memory-free-computed instead
        mfc = int(self.host.getHostParam("memory-free-computed"))/xenrt.MEGA
        if mfc >= needmb:
            return mfc
        raise xenrt.XRTError("Not enough free memory on host")

    # Feature test methods
    def featureConcurrentVMs(self):
        if self.allowed == 0:
            unlimited = True
            restriction = 9
        else:
            restriction = self.allowed

        # Check there are no VMs running already
        if (len(self.host.listDomains()) - 1) > 0:
            raise xenrt.XRTError("VMs already running on host")

        # Check there's enough memory on the host
        self.waitForHostFreeMemory((restriction + 1) * 128)

        # Create the template guest        
        guest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(guest)
        guest.preCloneTailor()
        guest.shutdown()

        guests = []
        # Clone it the relevant number of times
        for i in range(restriction):
            g = guest.cloneVM()
            self.uninstallOnCleanup(g)
            guests.append(g)

        # Start the clones (this should be allowed)
        i = 1
        for g in guests:
            xenrt.TEC().logverbose("Starting VM %d/%d..." % (i, restriction))
            g.start()
            xenrt.TEC().logverbose("...Started")
            i += 1

        if not unlimited:
            # Try and start a final one (this should be blocked)
            allowed = False
            try:
                guest.lifecycleOperation("vm-start")
                allowed = True
            except xenrt.XRTFailure, e:
                pass
            if allowed:
                raise xenrt.XRTFailure("vm-start succeeded for guest %d with "
                                       "license restriction of %d" %
                                       (i, restriction))


    def featureMaxMemory(self):
        # Convert the restriction to MB
        restMB = self.allowed * 1024

        # Check we have enough memory
        self.waitForHostFreeMemory(restMB + 32)

        # Create a guest that uses the exact limit (if there is one)
        guest = self.host.createGenericLinuxGuest(start=False)
        self.uninstallOnCleanup(guest)
        if restMB > 0:
            guest.memset(restMB)
            xenrt.TEC().logverbose("Starting guest that uses exact limit of "
                                   "allowed memory...")
            guest.start()
            xenrt.TEC().logverbose("...Started")
            guest.shutdown()

        # Now try and use all the memory the host has
        if isinstance(self.host, xenrt.lib.xenserver.MNRHost):
            mem = self.host.maximumMemoryForVM(guest) - 1
        else:
            time.sleep(75) # To let the free memory recalculate
            # We expect to find at least 1G free
            mem = self.waitForHostFreeMemory(1024)
            self.host.execdom0("/opt/xensource/debug/xenops physinfo") # CA-26342

        guest.memset(mem)
        xenrt.TEC().logverbose("VM memory target is %s" %
                               (guest.paramGet("memory-target")))

        if restMB > 0:
            # We expect it to fail
            allowed = False
            try:
                guest.start()
                allowed = True
            except xenrt.XRTFailure, e:
                pass
            if allowed:
                raise xenrt.XRTFailure("Allowed to start VM using %d MB of "
                                       "memory with a restriction of %d GB" %
                                       (mem, self.allowed))
        else:
            # This should work
            xenrt.TEC().logverbose("Starting guest using all available "
                                   "memory on the host...")    
            guest.start()
            xenrt.TEC().logverbose("...Started")        


    def featureVLAN(self):
        bridge = self.host.createNetwork()
        # Can we create a VLAN
        vlan = None
        try:
            vlan = self.host.createVLAN(100, bridge, "eth0")
        except:
            pass
        if vlan:
            try:
                self.host.removeVLAN(100)
            except:
                pass
            if not self.allowed:
                raise xenrt.XRTFailure("Unexpectedly allowed to create VLAN")
        elif self.allowed:
            raise xenrt.XRTFailure("Unexpectedly not allowed to create VLAN")


    def featureQoS(self):
        try:
            g = self.host.createGenericLinuxGuest(start=False)
            self.uninstallOnCleanup(g)
            g.setCPUCredit(weight=128, cap=0)
            g.setVIFRate("eth0", 100)
            g.setDiskQoS("0", "rt", 5)
            g.start()
        except xenrt.XRTFailure, e:
            raise xenrt.XRTError("Failure while setting credit parameters: " +
                                 e.reason, e.data)

        # See if we can find the warnings
        foundcpu = self.findGuest(["Ignoring CPU QoS params due to license "
                                  "restrictions"],g)
        foundvif = self.findGuest(["Ignoring QoS on VIFs due to licensing "
                                  "restrictions", "vif QoS failed: Ignoring "
                                  "QoS due to licensing restrictions"],g)
        foundvbd = self.findGuestVBD(g)

        if self.allowed:
            if foundcpu or foundvif or foundvbd:
                raise xenrt.XRTFailure("QoS ignored when license allows it "
                                       "(1=ignored): CPU %u, VIF %u, VBD %u" %
                                       (foundcpu,foundvif,foundvbd))
        else:
            if not (foundcpu and foundvif and foundvbd):
                raise xenrt.XRTFailure("QoS used when license disallows it "
                                       "(0=used): CPU %u, VIF %u, VBD %u" %
                                       (foundcpu,foundvif,foundvbd))


    def featureSharedSR(self):
        # Try and create a shared SR
        # NFS will do
        nfs = xenrt.NFSDirectory()
        try:
            nfsHost, nfsPath = nfs.getHostAndPath("")
            sr = xenrt.lib.xenserver.NFSStorageRepository(self.host,
                                                          "LicenseTest")
            allowed = False
            try:
                sr.create(nfsHost, nfsPath)
                allowed = True
                sr.remove()
            except xenrt.XRTFailure, e:
                if self.allowed:
                    raise e
            if allowed and not self.allowed:
                raise xenrt.XRTFailure("Allowed to create shared NFS SR when "
                                       "license should disallow it")
        finally:
            pass

    def featurePooling(self):
        # Try and create a pool out of all the hosts I have
        pool = None
        allowed = False
        try:
            pool = xenrt.lib.xenserver.poolFactory(self.host.productVersion)(self.host)
            force = xenrt.TEC().lookup("POOL_JOIN_FORCE", False, boolean=True)
            for h in self.otherHosts:
                # Check it's not already a member of a pool (XRT-5586)
                if h.pool:
                    # Try and eject it
                    xenrt.TEC().logverbose("Host %s appears to be in a pool "
                                           "already, attempting to eject..." %
                                           (h.getName()))
                    try:
                        h.pool.eject(h)
                    except:
                        traceback.print_exc(file=sys.stderr)
                        raise xenrt.XRTError("Host %s already in a pool, and "
                                             "an exception occurred while "
                                             "attempting to eject" %
                                             (h.getName()))
                    xenrt.TEC().logverbose("... ejected")

                pool.addHost(h, force=force)
            allowed = True
        except xenrt.XRTFailure, e:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().logverbose("Exception: " + e.reason)
        if allowed:
            try:
                for h in self.otherHosts:
                    pool.eject(h)
            except:
                xenrt.TEC().warning("Unable to eject all hosts")
            if not self.allowed:
                raise xenrt.XRTFailure("Unexpectedly allowed to create Pool")
        elif self.allowed:
            raise xenrt.XRTFailure("Unexpectedly not allowed to create Pool")


    def featureHA(self):
        # Try to enable HA on the host

        # Set up an LVMoISCSI SR
        try:
            lun = xenrt.ISCSITemporaryLun(300)
            sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host,"HA")
            sr.create(lun, subtype="lvm", findSCSIID=True, noiqnset=True)
        except xenrt.XRTFailure, e:
            # Not a failure
            raise xenrt.XRTError(e.reason, e.data)

        # EnableHA
        try:
            pool = self.getTCPool(self.host)
            allowed = False
            try:
                pool.enableHA(srs=[sr.uuid])
                allowed = True
            except xenrt.XRTFailure, e:
                if self.allowed:
                    raise xenrt.XRTFailure("Unable to enable HA even though "
                                           "license should allow it")
            if allowed and not self.allowed:
                raise xenrt.XRTFailure("Allowed to enable HA even though "
                                       "license shouldn't allow it")

        finally:
            try:
                pool.disableHA(check=False)
            except:
                pass
            try:
                sr.remove()
                sr.release()
            except:
                pass


    def featureKirkwood(self):
        # Set up a fake kirkwood to use
        kirkwood = xenrt.lib.createFakeKirkwood()

        # Get a pool object
        pool = self.getTCPool(self.host)
        try:
            allowed = False
            try:
                pool.initialiseWLB("%s:%d" % (kirkwood.ip, kirkwood.port),
                                   "wlbuser",
                                   "wlbpass")
                allowed = True
            except xenrt.XRTFailure, e:
                if self.allowed:
                    raise xenrt.XRTFailure("Unable to initialise WLB even "
                                           "though license should allow it")
            if allowed and not self.allowed:
                raise xenrt.XRTFailure("Allowed to initialise WLB even though "
                                       "license shouldn't allow it")
        finally:
            if pool.wlbEnabled:
                try:
                    pool.deconfigureWLB()
                except:
                    pass
            kirkwood.shutdown()

    def featureMarathonPCI(self):
        guest = self.host.createGenericEmptyGuest()
        self.uninstallOnCleanup(guest)
        guest.paramSet("other-config:mtc_pci_emulations", "xrtmtcpci")

        # Start the VM (don't use the start method as it's an empty VM)
        cli = self.host.getCLIInstance()
        cli.execute("vm-start uuid=%s on=%s" %
                    (guest.getUUID(), self.host.getMyHostName()))

        # Grep for the key on the host
        result = self.host.execdom0("ps -ef | grep [x]rtmtcpci", retval="code")
        if self.allowed and result != 0:
            raise xenrt.XRTFailure("Marathon PCI parameter not passed through "
                                   "even though license should allow it")

        if result == 0 and not self.allowed:
            raise xenrt.XRTFailure("Marathon PCI parameter passed through "
                                   "even though license shouldn't allow it")

    def featureEmailAlerts(self):
        # Configure a fake email server
        self.smtpServer = xenrt.util.SimpleSMTPServer()
        self.smtpServer.start()
        pool = self.getTCPool(self.host)
        host = self.host
        pool.setPoolParam("other-config:mail-destination", "test@mail.xenrt")
        pool.setPoolParam("other-config:ssmtp-mailhub", "%s:%s" %
                                    (xenrt.TEC().lookup("XENRT_SERVER_ADDRESS"),
                                     self.smtpServer.port))

        # This functionality has changed from clearwater onwards. This has to be done to support both versions
        if isinstance(self.host, xenrt.lib.xenserver.ClearwaterHost):
            if self.allowed:
                self.prioMsgEmailChk(host, pool, testname="TC_a", testPriority=5, isReceived=True , mailMinPriority=5 )
                self.prioMsgEmailChk(host, pool, testname="TC_b", testPriority=4, isReceived=False, mailMinPriority=3 )
            else:
                self.prioMsgEmailChk(host, pool, testname="TC_a", testPriority=5, isReceived=False , mailMinPriority=5 )
                self.prioMsgEmailChk(host, pool, testname="TC_b", testPriority=4, isReceived=False , mailMinPriority=3 )
        else:
            if self.allowed:
                self.prioMsgEmailChk(host, pool, testname="TC_cLegacy", testPriority=4, isReceived=True , mailMinPriority=4 )
                self.prioMsgEmailChk(host, pool, testname="TC_dLegacy", testPriority=3, isReceived=False)
                self.prioMsgEmailChk(host, pool, testname="TC_aLegacy", testPriority=5, isReceived=True , mailMinPriority=5 )
                self.prioMsgEmailChk(host, pool, testname="TC_bLegacy", testPriority=4, isReceived=False)
            else:
                self.prioMsgEmailChk(host, pool, testname="TC_cLegacy", testPriority=4, isReceived=False , mailMinPriority=4 )
                self.prioMsgEmailChk(host, pool, testname="TC_dLegacy", testPriority=3, isReceived=False)
                self.prioMsgEmailChk(host, pool, testname="TC_aLegacy", testPriority=5, isReceived=False , mailMinPriority=5 )
                self.prioMsgEmailChk(host, pool, testname="TC_bLegacy", testPriority=4, isReceived=False)
        try:
            if self.smtpServer.isAlive():
                self.smtpServer.stop()
        except:
            pass
        try:
            pool.removePoolParam("other-config", "mail-destination")
            pool.removePoolParam("other-config", "ssmtp-mailhub")
            pool.removePoolParam("other-config", "mail-min-priority")
        except:
            pass

    # Function to create message, send it based on prioity and verify if received or not.
    def prioMsgEmailChk(self, host, pool, testname, testPriority, isReceived, mailMinPriority= None):

        # Set other-config:mail-min-priority to options.get("mail-min-priority")
        if mailMinPriority != None:
            pool.setPoolParam("other-config:mail-min-priority", mailMinPriority)

        # Create a message of priority level 'priority'
        host.messageCreate(testname, "Test message (priority %d)" % testPriority, priority=testPriority)

        #wait then check for mail and clear mailbox.
        xenrt.sleep(30)
        mail = self.smtpServer.getMail()
        self.smtpServer.clearMail()

        if isReceived == True:
            # verify an email is received
            if len(mail) == 0:
                raise xenrt.XRTFailure("%s : No email sent for priority %d message" % (testname, testPriority))
            elif len(mail) > 1:
                raise xenrt.XRTFailure("%s : Received multiple emails for one message" % testname)
        else:
            # verify email is not recieved
            if len(mail) > 0:
                raise xenrt.XRTFailure("%s : Received email for priority %d message" % (testname, testPriority))

    def featureDMC(self):
        """Feature license test for Dynamic Memory Control (DMC)"""
        guest = self.host.createGenericLinuxGuest(start=False)
        self.uninstallOnCleanup(guest)

        cli = self.host.getCLIInstance()

        # Try the various ways of setting a dynamic range
        for c, p in [("vm-memory-dynamic-range-set", "min=128MiB max=256MiB"),
                     ("vm-memory-static-range-set", "min=128MiB max=512MiB"),
                     ("vm-param-set", "memory-dynamic-min=128MiB"),
                     ("vm-param-set", "memory-static-max=512MiB"),
                     ("vm-memory-limits-set", "static-min=128MiB dynamic-min=128MiB dynamic-max=256MiB static-max=256MiB")]:

            # This should always work
            guest.setMemoryProperties(128, 256, 256, 256)

            try:
                cli.execute(c, "uuid=%s %s" % (guest.getUUID(), p))
            except xenrt.XRTFailure, e:
                if self.allowed:
                    xenrt.TEC().logverbose("Unexpected failure setting a dynamic range")
                    raise e
                # Check we got the expected exception
                if not re.search("static_min \xe2\x89\xa4 dynamic_min = dynamic_max = static_max", e.data):
                    raise xenrt.XRTFailure("Did not find expected invariant in DMC license error",
                                           data="Expecting to find static_min \xe2\x89\xa4 dynamic_min = dynamic_max = static_max")
            else:
                if not self.allowed:
                    raise xenrt.XRTFailure("Allowed to set a dynamic range when license should restrict it")                

    def featureCheckpoint(self):
        """Feature license test for checkpoint"""
        guest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(guest)

        try:
            cp = guest.checkpoint()
        except xenrt.XRTFailure, e:
            if self.allowed:
                xenrt.TEC().logverbose("Unexpected failure taking a checkpoint")
                raise e
            # Check we got the expected exception
            if not re.search("This operation is not allowed under your license", str(e)):
                raise xenrt.XRTFailure("Did not find expected license exception text",
                                       data="Expecting 'This operation is not allowed under your license'")
        else:
            if not self.allowed:
                raise xenrt.XRTFailure("Allowed to take a checkpoint when license should restrict it")

    def featureCPUMask(self):
        """Feature license test for CPU Masking"""
        cpuinfo = self.host.getCPUInfo()
        try:
            self.host.setCPUFeatures(cpuinfo['features'])
        except xenrt.XRTFailure, e:
            if self.allowed:
                if re.search("does not support masking", str(e)):
                    xenrt.TEC().logverbose("Feature call has passed the priviledge check, however the current host "
                                           "CPU doesn't support the masking technology.")
                else:
                    xenrt.TEC().logverbose("Unexpected failure setting a CPU mask")
                    raise e
            # Check we got the expected exception
            elif not re.search("The use of this feature is restricted.", str(e)):
                raise xenrt.XRTFailure("Did not find expected license restricted text",
                                       data="Expecting 'The use of this feature is restricted.'")
        else:
            if not self.allowed:
                raise xenrt.XRTFailure("Allowed to set a CPU mask when "
                                       "license should restrict it")

    def featureCaching(self):
        """Feature license test for local caching."""
        try:
            self.host.enableCaching(self.host.getLocalSR())
        except xenrt.XRTFailure, e:
            if self.allowed:
                xenrt.TEC().logverbose("Unexpected failure enabling local caching.")
                raise e
            elif not re.search("The use of this feature is restricted.", str(e)):
                raise xenrt.XRTFailure("Did not find expected license restricted text",
                                  data="Expecting 'The use of this feature is restricted.'")
        else:
            if not self.allowed:
                raise xenrt.XRTFailure("Allowed to enable local caching when license should restrict it.")

    def featureVMPP(self):
        """Feature license test for VMPP"""
        self.pool = xenrt.lib.xenserver.poolFactory(self.host.productVersion)(self.host)
        # Only platinum host can create VMPP
        vmpp = None
        try:
            try:
                vmpp = self.pool.createVMPP("lic" + self.tcid, 
                                            "snapshot", "weekly")
            except xenrt.XRTException, e:
                if self.allowed or e.reason.find("license") < 0:
                    raise e
                else:
                    self.host.license(edition="platinum")
                    vmpp = self.pool.createVMPP("lic" + self.tcid,
                                                "snapshot", "weekly")
                    if self.EDITION:
                        self.host.license(edition=self.EDITION)
                    else:
                        self.host.license(sku=self.SKU)
            else:
                if not self.allowed:
                    raise xenrt.XRTFailure("%s license shouldn't be allowed to "
                                           "create VMPP." % (self.EDITION or self.SKU))

            # any license should be able to read VMPP
            vmpps = self.pool.listVMPP()
            if vmpp not in vmpps:
                raise xenrt.XRTFailure("VMPP is missing after created")

            # any license should be able read VMPP conf
            vmppconf = self.pool.getVMPPConf(vmpp=vmpp)

            # Only platinum can set VMPP conf
            try:
                self.pool.setVMPPParam(vmpp, "backup-frequency", "daily")
            except xenrt.XRTException, e:
                if self.allowed or e.reason.find("license") < 0:
                    raise e
            else:
                if not self.allowed:
                    raise xenrt.XRTFailure("%s license shouldn't be allowed to "
                                           "set VMPP params." % (self.EDITION or self.SKU))
            # Delete should work with any license
            self.pool.deleteVMPP(vmpp)
        finally:
            if vmpp in self.pool.listVMPP():
                # Just in case
                self.host.license("platinum")
                self.pool.deleteVMPP(vmpp)
            if self.EDITION:
                self.host.license(edition=self.EDITION)
            else:
                self.host.license(sku=self.SKU)

    def featureDVSC(self):
        """Feature license test for DVS Controller."""
        cli = self.host.getCLIInstance()
        data = cli.execute("host-license-view", "host-uuid=%s" % (self.host.getMyHostUUID()))
        r = re.search(r"restrict_vswitch_controller.*: (.*)", data)
        if r:
            restricted = r.group(1) == "true"
            if not self.allowed and not restricted:
                raise xenrt.XRTFailure("Allowed to connect a DVS Controller when license should restrict it.")
            elif self.allowed and restricted:
                raise xenrt.XRTFailure("Not allowed to connect a DVS Controller, while license should not restrict it.")
        else:
            raise xenrt.XRTFailure("License key restrict_vswitch_controller not found.")

    def featureVGPU(self):
        """Feature license test for vGPU feature."""
        cli = self.host.getCLIInstance()
        lic = cli.execute("host-license-view", "host-uuid=%s" % (self.host.getMyHostUUID()))
        r = re.search(r"restrict_gpu.*: (.*)", lic)
        if r:
            restricted = r.group(1) == "true"
            if not self.allowed and not restricted:
                raise xenrt.XRTFailure("Allowed to use vGPUs when license should restrict it.")
            elif self.allowed and restricted:
                raise xenrt.XRTFailure("Not allowed to use vGPUs, while license should not restrict it.")
            vm_uuids = self.host.minimalList("vm-list") #there's always at least 1 vm (dom0)
            gpu_group_uuids = self.host.minimalList("gpu-group-list") #>0 gpu hw required for this license test
            if len(gpu_group_uuids)<1:
                raise xenrt.XRTFailure("This host does not contain a GPU group list as expected")
            try:
                data = cli.execute("vgpu-create", "gpu-group-uuid=%s vm-uuid=%s" % (gpu_group_uuids[0],vm_uuids[0]))
                # clean up vgpu list
                cli.execute("vgpu-destroy","uuid=%s" % data)
            except xenrt.XRTFailure, e:
                data = str(e)
            xenrt.TEC().logverbose("lic: %s; allowed=%s; restricted=%s; gpu-create returned: %s" % (lic,self.allowed,restricted,data))    
            if not self.allowed and restricted:
                if not re.search("is restricted",data):
                    raise xenrt.XRTFailure("Allowed to use vgpu-create when license should restrict it.")
            elif self.allowed and not restricted:
                if re.search("is restricted",data):
                    raise xenrt.XRTFailure("Not allowed to use vgpu-create when license should not restrict it.")
        else:
            raise xenrt.XRTFailure("License key restrict_gpu not found.")


    def featureDR(self):
        """Feature license test for Disaster Recovery."""
        cli = self.host.getCLIInstance()
        lic = cli.execute("host-license-view", "host-uuid=%s" % (self.host.getMyHostUUID()))
        r = re.search(r"restrict_dr.*: (.*)", lic)

        if not r:
            raise xenrt.XRTFailure("License key restrict_dr not found.")
                
        restricted = r.group(1) == "true"
        if not self.allowed and not restricted:
            raise xenrt.XRTFailure("Allowed to use DR when license should have restricted it.")
        elif self.allowed and restricted:
            raise xenrt.XRTFailure("Not allowed to use DR when license should have enabled it.")
        
        sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host, "xenrt_DR")
        lun = xenrt.ISCSITemporaryLun(300)
        sr.create(lun, subtype="lvm", multipathing=None, noiqnset=True, findSCSIID=True)
        
        try:
            data = cli.execute('sr-enable-database-replication', 'uuid=%s' % sr.uuid, strip=True)
        except xenrt.XRTFailure, e:
            data = str(e)
        else:
            cli.execute('sr-disable-database-replication', 'uuid=%s' % sr.uuid)
        xenrt.TEC().logverbose("lic: %s; allowed=%s; restricted=%s; sr-enable-database-replication returned: %s" % (lic,self.allowed,restricted,data))
        try:
            sr.forget()
        except:
            pass
        try:
            lun.release()
        except:
            pass
        if not self.allowed and restricted:
            if not re.search("operation is not allowed", data):
                raise xenrt.XRTFailure("Allowed to use sr-enable-database-replication when license should have restricted it.")
        elif self.allowed and not restricted:
            if re.search("operation is not allowed", data):
                raise xenrt.XRTFailure("Not allowed to use sr-enable-database-replication when license should have enabled it.")


    # Utility methods
    def grepLogFiles(self, pattern):
        reply1 = self.host.execdom0("grep '%s' /var/log/xensource.log | cat" %
                                    (pattern))
        reply2 = self.host.execdom0("grep '%s' /var/log/xensource.log.1 | cat" %
                                    (pattern))
        return reply1 + reply2

    def findGuest(self, texts, guest):
        for text in texts:
            try:
                data = self.grepLogFiles(text)
                datal = data.split("\n")
                for l in datal:
                    # Try even newer style
                    m = re.search("\|VM\.start(?:_on)? (\S:\S+)\|",l)
                    if m:
                        tid = m.group(1)
                    else:
                        # Try new style
                        m = re.search("\[task: VM\.start \((\S+)\)",l)
                        if m:
                            tid = m.group(1)
                        else:
                            # This line has a task ID, which we need to extract
                            tids = l.split()
                            if len(tids) < 5:
                                continue
                            tid = tids[4]
                            tid = tid[1:]

                    # Now grep for this task ID
                    runon = self.grepLogFiles(tid)
                    # Now extract the domID
                    m = re.search("Adding vif(\d+)\.0 to bridge", runon)
                    if not m:
                        m = re.search("Device.Vif.add domid=(\d+)", runon)
                        if not m:
                            continue
                    domid = m.group(1)
                    if domid == str(guest.getDomid()):
                        return True
            except xenrt.XRTFailure, e:
                # An error in these commands probably means the entry didn't exist
                pass

        return False

    def findGuestVBD(self, guest):
        try:
            data = self.grepLogFiles("vbd qos failed:")
            datal = data.split("\n")
            for l in datal:
                m = re.search("vbd qos failed: license restrictions "
                             "\(vm=(\S+),vbd=(\S+)\)",l)
                if m and m.group(1) == guest.getUUID():
                    return True
            return False
        except xenrt.XRTFailure, e:
            return False

    def getTCPool(self, host):
        # Return a pool object for this host
        pool = xenrt.lib.xenserver.poolFactory(host.productVersion)(host)
        return pool

class _PoolLicenseBase(_LicenseBase):
    """Base class for pool SKU license test cases"""
    SKU1 = "FG Free"
    SKU2 = "FG Paid"

    def prepare(self, arglist=None):
        # Before going any further, check that it's a known feature
        if not self.FEATURE in self._KNOWN_FEATURES:
            raise xenrt.XRTError("Unknown license feature %s" % (self.FEATURE))

        # Prepare the pool...
        self.pool = self.getDefaultPool()

        # License the hosts (we alternate between free and paid for)
        self.pool.master.license(sku=self.SKU1)
        self.host = self.pool.master

        skus = [self.SKU1, self.SKU2]
        skuIndex = 1
        for h in self.pool.getSlaves():
            h.license(sku=skus[skuIndex])
            skuIndex = (skuIndex + 1) % 2

        self.allowed = self.ALLOWED

    def run(self, arglist=None):
        if self.SKU1 == self.SKU2:
            # Homogenous pool, no need to test things twice!
            actualMethod = eval("self.feature" + self.FEATURE)
            actualMethod()
            return

        # Mixed pool
        # First run using the master with a free license
        if self.runSubcase("feature" + self.FEATURE, (), "MasterSKU1", self.FEATURE) != \
           xenrt.RESULT_PASS:
            return

        # Now use the master with a paid license
        # We know the first slave will have a paid for license
        self.pool.designateNewMaster(self.pool.getSlaves()[0])
        self.host = self.pool.master

        if self.runSubcase("feature" + self.FEATURE, (), "MasterSKU2", self.FEATURE) != \
            xenrt.RESULT_PASS:
            return

    def getTCPool(self, host):
        return self.pool

class _V6PoolLicenseBase(_LicenseBase):
    """Base class for V6 pool SKU license test cases"""
    EDN1 = "free"
    EDN2 = "advanced"
    EDN3 = None
    EDN4 = None

    def prepare(self, arglist=None):
        # Before going any further, check that it's a known feature
        if not self.FEATURE in self._KNOWN_FEATURES:
            raise xenrt.XRTError("Unknown license feature %s" % (self.FEATURE))

        # Prepare the pool...
        self.pool = self.getDefaultPool()

        # License the hosts
        self.pool.master.license(edition=self.EDN1)
        self.host = self.pool.master

        self.edns = [self.EDN1, self.EDN2]
        self.edns += filter(None, [self.EDN3, self.EDN4])

        ednIndex = 1
        for h in self.pool.getSlaves():
            h.license(edition=self.edns[ednIndex])
            ednIndex = (ednIndex + 1) % len(self.edns)

        self.allowed = self.ALLOWED

    def run(self, arglist=None):
        if self.EDN1 == self.EDN2 and not (self.EDN3 or self.EDN4):
            # Homogenous pool, no need to test things twice!
            actualMethod = eval("self.feature" + self.FEATURE)
            actualMethod()
            return

        # Mixed pool
        # First run using the master with a free license
        if self.runSubcase("feature" + self.FEATURE, (), "MasterEDN1", self.FEATURE) != \
           xenrt.RESULT_PASS:
            return

        # Now use the master with a paid license
        # We know the first slave will have a paid for license
        self.pool.designateNewMaster(self.pool.getSlaves()[0])
        self.host = self.pool.master

        if self.runSubcase("feature" + self.FEATURE, (), "MasterEDN2", self.FEATURE) != \
            xenrt.RESULT_PASS:
            return

        for i in range(3, len(self.edns)):
            if eval("self.EDN" + str(i)):
                self.pool.designateNewMaster(self.pool.getSlaves()[i-2])
                self.host = self.pool.master
                if (self.runSubcase("feature" + self.FEATURE, (),
                                   "MasterEDN"+str(i), self.FEATURE) !=
                    xenrt.RESULT_PASS):
                    return

    def getTCPool(self, host):
        return self.pool

class _PoolJoinBase(xenrt.TestCase):
    POOL_SKU = None
    POOL_EDNS = None
    JOIN_SKU = None
    JOIN_EDN = None
    ALLOWED = False
    LICENSES = []

    def prepare(self, arglist=None):
        # Get three hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host2 = self.getHost("RESOURCE_HOST_2")

        # License the first two with the POOL_SKU or POOL_EDNS
        if self.POOL_EDNS:
            self.host0.license(edition=self.POOL_EDNS[0])
            self.host1.license(edition=self.POOL_EDNS[0])
        else:
            self.host0.license(sku=self.POOL_SKU)
            self.host1.license(sku=self.POOL_SKU)

        # License the third with the JOIN_SKU or JOIN_EDN
        if self.JOIN_EDN:
            self.host2.license(edition=self.JOIN_EDN)
        else:
            self.host2.license(sku=self.JOIN_SKU)

        # Create a pool out of the first two
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        if self.host1.pool:
            try:
                self.host1.pool.eject(self.host1)
            except:
                traceback.print_exc(file=sys.stderr)
                raise xenrt.XRTError("Host %s already in a pool, and an eject "
                                     "raised an exception" %
                                     (self.host1.getName()))
        self.pool.addHost(self.host1)
        if self.host2.pool:
            try:
                self.host2.pool.eject(self.host2)
            except:
                traceback.print_exc(file=sys.stderr)
                raise xenrt.XRTError("Host %s already in a pool. and an eject "
                                     "raised an exception" %
                                     (self.host2.getName()))

        if self.POOL_EDNS and len(self.POOL_EDNS) > 1:
            # Relicense hsot1 with the second pool edition
            self.host1.license(edition=self.POOL_EDNS[1])

    def run(self, arglist=None):
        # Try and add the third host to the pool
        allowed = False
        try:
            self.pool.addHost(self.host2)
            allowed = True
        except:
            if self.ALLOWED:
                raise xenrt.XRTFailure("Unexpected failure joining %s host to "
                                       "pool with %s editions" % (self.JOIN_EDN, self.POOL_EDNS))
            xenrt.TEC().logverbose("Expected failure joining host to pool")
        if allowed and not self.ALLOWED:
            if self.POOL_EDNS:
                raise xenrt.XRTFailure("Allowed to join %s host to pool with "
                                       "%s editions" % (self.JOIN_EDN, self.POOL_EDNS))
            else:
                raise xenrt.XRTFailure("Allowed to join host with %s SKU to pool "
                                       "with %s SKU" % (self.JOIN_SKU,
                                                        self.POOL_SKU))

        if self.ALLOWED:
            # Don't test a force join, since the normal join will have
            # succeeded if we've got here...
            return

        # Try again using a force join
        allowed = False
        try:
            self.pool.addHost(self.host2, force=True)
            allowed = True
        except:
            xenrt.TEC().logverbose("Expected failure joining host to pool")
        if allowed:
            if self.POOL_EDNS:
                raise xenrt.XRTFailure("Allowed to force join %s host to pool with "
                                       "%s editions" % (self.JOIN_EDN, self.POOL_EDNS))
            else:
                raise xenrt.XRTFailure("Allowed to force join host with %s SKU to "
                                       "pool with %s SKU" % (self.JOIN_SKU,
                                                             self.POOL_SKU))

    def postRun(self):
        try:
            if self.pool:
                # Eject the slaves from the pool
                for h in self.pool.getSlaves(): 
                    try:
                        self.pool.eject(h)
                    except:
                        pass
        except:
            pass

class _LicenseExpireBase(xenrt.TestCase):
    """Base class for license expiry test cases"""
    # SKU to test with
    SKU = None
    EDITION = None
    EXPIREDAYS = None

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        # Apply a license if necessary
        if self.SKU:
            self.host.license(sku=self.SKU, expirein=2)
        elif self.EDITION:
            self.host.license(edition=self.EDITION, expirein=2)

        # Determine the expiry time of the current license
        licenseInfo = self.host.getLicenseDetails()
        self.sku = licenseInfo['sku_type']
        self.expiry = xenrt.util.parseXapiTime(licenseInfo['expiry'])

        # Install a few VMs to test with
        self.guest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.guest.preCloneTailor()
        # Modify sysctl.conf to use an independent wallclock (CA-28025)
        self.guest.execguest("echo 'xen.independent_wallclock=1' >> /etc/sysctl.conf")
        self.guest.shutdown()
        self.guest1 = self.guest.cloneVM()
        self.uninstallOnCleanup(self.guest1)
        self.guest2 = self.guest.cloneVM()
        self.uninstallOnCleanup(self.guest2)
        self.guest3 = self.guest.cloneVM()
        self.uninstallOnCleanup(self.guest3)

    def run(self, arglist=None):
        if self.EXPIREDAYS:
            # This is a number of days the license should expire in
            # Convert the number of seconds in to days
            difference = self.expiry - xenrt.timenow()
            days = difference / 86400
            if days < (self.EXPIREDAYS - 1) or days > (self.EXPIREDAYS + 1):
                raise xenrt.XRTFailure("License does not expire when expected",
                                       data="Expecting %d days, found %d" %
                                       (self.EXPIREDAYS, days))

        # Advance the host to 5 mins before expiry
        self.host.execdom0("/etc/init.d/ntpd stop")
        expiretarget = self.expiry - 300
        expiretarget = time.gmtime(expiretarget)
        self.host.execdom0("date -u %s" %
                           (time.strftime("%m%d%H%M%Y.%S",expiretarget)))

        # Start both VMs, and then shut the first down
        try:
            self.guest1.start()
            #Advance the host to 5 mins before expiry again
            #This is to make sure that it's been more than 5 mins and
            #the license hasn't expired already (CA-92850)
            self.host.execdom0("date -u %s" %
                           (time.strftime("%m%d%H%M%Y.%S",expiretarget)))
            self.guest2.start()
            #And again
            self.host.execdom0("date -u %s" %
                           (time.strftime("%m%d%H%M%Y.%S",expiretarget)))
            self.guest3.start()
        except xenrt.XRTFailure, e:
            traceback.print_exc(file=sys.stderr)
            raise xenrt.XRTFailure("Exception starting VMs 5 minutes before "
                                   "license expiry: %s" % (e.reason),
                                   data=e.data)

        self.guest1.shutdown()

        # Wait until we get past expiry
        time.sleep(300)

        # Try and start the first VM, it should fail
        allowed = False
        try:
            self.guest1.start()
            allowed = True
        except xenrt.XRTFailure, e:
            # Check for a LICENSE_EXPIRED error
            if not re.search(r"Your license has expired", str(e)):
                xenrt.TEC().warning("VM start failed as expected but without "
                                    "expected license expired text")
        if allowed:
            raise xenrt.XRTFailure("Allowed to start VM after license expired")

        # Suspend the second VM
        try:
            self.guest2.suspend()
        except xenrt.XRTFailure, e:
            traceback.print_exc(file=sys.stderr)
            raise xenrt.XRTFailure("Exception suspending VM after license "
                                   "expiry: %s" % (e.reason), data=e.data)
        # Try and resume the second VM
        allowed = False
        try:
            self.guest2.resume()
            allowed = True
        except xenrt.XRTFailure, e:
            # Check for a LICENSE_EXPIRED error
            if not re.search(r"Your license has expired", str(e)):
                xenrt.TEC().warning("VM resume failed as expected but without "
                                    "expected license expired text")
        if allowed:
            raise xenrt.XRTFailure("Allowed to resume VM after license expired")

        # Shut down the third VM
        try:
            self.guest3.shutdown()
        except xenrt.XRTFailure, e:
            traceback.print_exc(file=sys.stderr)
            raise xenrt.XRTFailure("Exception shutting down VM after license "
                                   "expiry: %s" % (e.reason), data=e.data)

        # Now re-license the host
        self.host.license(sku=self.sku)

        # Check that we can start the first VM
        try:
            self.guest1.start()
        except xenrt.XRTFailure, e:
            traceback.print_exc(file=sys.stderr)
            raise xenrt.XRTFailure("Exception starting VM after renewing "
                                   "expired license: %s" % (e.reason),
                                   data=e.data)

        # Check we can resume the second VM
        try:
            self.guest2.resume()
        except xenrt.XRTFailure, e:
            traceback.print_exc(file=sys.stderr)
            raise xenrt.XRTFailure("Exception renewing VM after renewing "
                                   "expired license: %s" % (e.reason),
                                   data=e.data)

    def postRun(self):
        # Remove any license expiry FIST points
        self.host.execdom0("rm -f /tmp/fist_set_expiry_date || true")
        # Reset the host clock, and restart xapi to make sure it picks it up
        self.host.execdom0("ntpdate `grep -e '^server ' /etc/ntp.conf | sed q | sed 's/server //'` || true")
        self.host.execdom0("/etc/init.d/ntpd start")
        self.host.restartToolstack()
        self.host.execdom0("xe event-wait class=host uuid=%s enabled=true" % self.host.getMyHostUUID())


class _PoolLicenseExpireBase(xenrt.TestCase):
    """Base class for pool license expiry testcases"""
    SKU = ["FG Free"]
    EDITION = None
    HA = False
    MASTER = "FG Free"

    def prepare(self, arglist=None):
        # Get the pool, license appropriately
        self.pool = self.getDefaultPool()

        # Check for early release licensing (CA-82154)
        if self.pool.master.special.has_key("v6earlyrelease") and self.pool.master.special["v6earlyrelease"]:
            xenrt.TEC().skip("Not running license expiry tests with early release licensing turned on")
            return

        if self.EDITION:
            self.pool.master.license(edition=self.MASTER)
        else:
            self.pool.master.license(sku=self.MASTER)
        sIndex = 0
        for h in self.pool.getSlaves():
            if self.EDITION:
                h.license(edition=self.EDITION[sIndex])
                sIndex = (sIndex + 1) % len(self.EDITION)
            else:
                h.license(sku=self.SKU[sIndex])
                sIndex = (sIndex + 1) % len(self.SKU)

        if self.HA:
            # Set up an LVMoISCSI SR
            try:
                lun = xenrt.ISCSITemporaryLun(300)
                sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.pool.master,"HA")
                self.sr = sr
                sr.create(lun, subtype="lvm", findSCSIID=True, noiqnset=True)
            except xenrt.XRTFailure, e:
                # Not a failure
                raise xenrt.XRTError(e.reason, e.data)

            self.pool.enableHA()

        # Install the time advance plugin on each host
        plugin = """#!/usr/bin/env python

import XenAPIPlugin, os

# XenAPI plugin for setting the date
# Takes the date/time to set in the format MMDDhhmmYY
# Where MM = month, DD = day, hh = hour, mm = minute, YY = year

def main(session, args):
    if not args.has_key("date"):
        # Reset to normal (i.e. start ntp)
        rc = os.system("ntpdate `grep -e '^server ' /etc/ntp.conf | sed q | sed 's/server //'` &>/dev/null")
        rc = os.system("/etc/init.d/ntpd start &>/dev/null")
        if rc == 0:
            return "NTP enabled"
        else:
            return "Error enabling NTP"
    else:
        # First disable NTP
        rc = os.system("/etc/init.d/ntpd stop &>/dev/null")
        if rc != 0:
            return "Error disabling NTP"
        # Now set the requested date
        rc = os.system("date -u %s &>/dev/null" % (args['date']))
        if rc == 0:
            return "Date set"
        else:
            return "Error setting date"

if __name__ == "__main__":
    XenAPIPlugin.dispatch({"main": main})
"""
        fName = xenrt.TEC().tempFile()
        f = file(fName, "w")
        f.write(plugin)
        f.close()

        for h in self.pool.getHosts():
            sftp = h.sftpClient()
            try:
                sftp.copyTo(fName, "/etc/xapi.d/plugins/dateset")
            finally:
                sftp.close()
            h.execdom0("chmod +x /etc/xapi.d/plugins/dateset")

        # Configure initial placement of VMs etc
        # We want (all on shared storage) 3 VMs per host,
        # plus an additional one to test with
        self.sr = self.pool.master.lookupDefaultSR()
        self.guest = self.pool.master.createGenericLinuxGuest(sr=self.sr)
        self.uninstallOnCleanup(self.guest)
        self.guest.preCloneTailor()
        self.guest.shutdown()
        self.guests = {}
        for h in self.pool.getHosts():
            self.guests[h] = []
            for i in range(3):
                g = self.guest.cloneVM()
                self.uninstallOnCleanup(g)
                g.start()
                self.guests[h].append(g)
                if self.HA:
                    g.setHAPriority("2")

    def postRun(self):
        if self.pool:
            if self.HA:
                try:
                    self.pool.disableHA()
                    self.sr.remove()
                except:
                    pass

            for h in self.pool.getHosts():
                try:
                    h.license()
                except:
                    pass

            for h in self.pool.getHosts():
                try:
                    h.execdom0("/etc/init.d/ntpd stop || true")
                    h.execdom0("ntpdate `grep -e '^server ' /etc/ntp.conf | sed q | sed 's/server //'` || true")
                    h.execdom0("/etc/init.d/ntpd start")
                except:
                    pass
            for h in self.pool.getHosts():
                h.restartToolstack()

        time.sleep(180) # Allow 3 minutes for the hosts to report in etc

        for g in self._guestsToUninstall:
            try:
                g.shutdown(force=True)
            except:
                pass

    def runHost(self, master, sku):
        host = None
        if master:
            host = self.pool.master
        else:
            if self.EDITION:
                for h in self.pool.getSlaves():
                    if h.getLicenseDetails()["edition"] == sku:
                        host = h
                        break
            else:
                for h in self.pool.getSlaves():
                    # See what the host reports
                    lsku = h.getLicenseDetails()["sku_type"]

                    # Handle FG_Free case (CA-42943)
                    if sku == "FG Free" and lsku == "free":
                        host = h
                        break

                    # There is a mapping from logical SKU names to the ones
                    # used in the license files. Use the per-version license
                    # files was have to look this mapping up
                    keyfile = ("%s/keys/xenserver/%s/%s" %
                               (xenrt.TEC().lookup("XENRT_CONF"),
                                h.productVersion,
                                string.replace(sku, " ", "_")))
                    f = file(keyfile, "r")
                    data = f.read()
                    f.close()
                    r = re.search(r"sku_type=\"(.*?)\"", data)
                    if not r:
                        raise xenrt.XRTError(\
                            "Could not parse sku_type from example license %s" %
                            (keyfile))
                    wantsku = r.group(1)
                    wantsku = h.lookup(["LICMAP", wantsku.replace(" ", "_")],
                                       wantsku)
                    if lsku == wantsku:
                        host = h
                        break
            if not host:
                raise xenrt.XRTError("Couldn't find a host with the SKU %s" %
                                     (sku))

        # Give it an appropriate license
        if self.EDITION:
            host.license(edition=sku, expirein=5, applyEdition=False)
        else:
            host.license(sku=sku, expirein=5, applyedition=False)

        # Advance the host clocks to 10 minutes before license expires
        expires = host.getLicenseDetails()["expiry"]
        expires = xenrt.util.parseXapiTime(expires)
        advanceTo = expires - 1000
        change = advanceTo - xenrt.util.timenow()
        args = []
        args.append("plugin=dateset")
        args.append("fn=main")
        args.append("args:date=%s" % (time.strftime("%m%d%H%M%Y",
                                                    time.gmtime(advanceTo))))
        cli = self.pool.getCLIInstance()
        for h in self.pool.getHosts():
            cli.execute("host-call-plugin", "%s host-uuid=%s" %
                                            (string.join(args),
                                             h.getMyHostUUID()))
        xenrt.TEC().logverbose("Have set the host clocks to %s" %
                               (time.strftime("%Y-%m-%d %H:%M",
                                              time.gmtime(advanceTo))))

        # Restart xapi on all hosts to pick up the time change properly
        self.pool.master.restartToolstack()
        for h in self.pool.getSlaves():
            h.restartToolstack()

        # Allow 5 minutes for everything to settle down
        xenrt.TEC().logverbose("Starting 5 minute settle time")
        time.sleep(300)

        # Verify that everything still works
        xenrt.TEC().logverbose("Checking functionality before expiry")
        self.checkFunctionality(None)

        # Wait for the license to expire
        xenrt.TEC().logverbose("Waiting for license expiry")
        while True:
            if (xenrt.util.timenow() + change) >= expires:
                break
            time.sleep(60)

        # Wait 5 minutes to allow things to settle
        time.sleep(300)

        # Get license details
        host.getLicenseDetails()

        # Verify that everything works except the host
        xenrt.TEC().logverbose("Checking functionality after expiry")
        self.checkFunctionality(host)

        # Restore the license on the host
        xenrt.TEC().logverbose("Restoring license")
        if self.EDITION:
            host.license(edition=sku, applyEdition=False)
        else:
            host.license(sku=sku, applyEdition=False)

        # Re-enable HA
        if self.HA:
            host.enable()
            self.pool.enableHA()

        # Allow some settle time
        time.sleep(120)

        # Verify that the host works again
        xenrt.TEC().logverbose("Checking functionality after license restore")
        self.checkFunctionality(None)

        # Restore the clocks
        xenrt.TEC().logverbose("Resetting the clocks")
        args = []
        args.append("plugin=dateset")
        args.append("fn=main")
        for h in self.pool.getHosts():
            cli.execute("host-call-plugin", "%s host-uuid=%s" %
                                            (string.join(args),
                                             h.getMyHostUUID()))
        time.sleep(300)

    def checkFunctionality(self, expiredHost):
        if self.HA:
            # HA should still be enabled, but the expired host should be set
            # as disabled, and we shouldn't be able to re-enable it
            xenrt.TEC().logverbose("Checking HA is still enabled")
            if self.pool.getPoolParam("ha-enabled") != "true":
                raise xenrt.XRTFailure("HA became disabled")
            if expiredHost:
                xenrt.TEC().logverbose("Checking expired host is disabled")
                if expiredHost.getHostParam("enabled") != "false":
                    raise xenrt.XRTFailure("Host with expired license is "
                                           "not disabled with HA on")
                allowed = False
                try:
                    expiredHost.enable()
                    allowed = True
                except:
                    pass
                if allowed:
                    raise xenrt.XRTFailure("Able to re-enable host with "
                                           "expired license with HA on")
                
                # In guest shutdown of a running VM should cause it to restart
                # elsewhere
                xenrt.TEC().logverbose("Checking restart of VM on disabled host")
                g = self.guests[expiredHost][-1]
                g.execguest("/sbin/poweroff")
                self.pool.haLiveset.remove(expiredHost.getMyHostUUID())
                try:
                    g.findHost()
                except:
                    raise xenrt.XRTFailure("In guest shutdown of protected "
                                           "VM on expired host did not cause "
                                           "VM to restart")

                # We should be able to disable HA
                xenrt.TEC().logverbose("Disabling HA")
                self.pool.disableHA()

        # VM starts should work on all non expired hosts
        xenrt.TEC().logverbose("Checking VMs can start on enabled hosts")
        goodHost = None
        for h in self.pool.getHosts():
            if h != expiredHost:
                self.guest.host = h
                self.guest.start()
                self.guest.shutdown()
                goodHost = h

        # VM starts should fail on the expired host
        if expiredHost:
            xenrt.TEC().logverbose("Checking VM cannot start on disabled host")
            allowed = False
            try:
                self.guest.host = expiredHost
                self.guest.start()
                allowed = True
            except:
                pass
            if allowed:
                raise xenrt.XRTFailure("Allowed to start VM on host with "
                                       "expired license")

        # VMs running on the expired host should migrate away
        if expiredHost:
            xenrt.TEC().logverbose("Checking VMs can be migrated away from the disabled host")
            g = self.guests[expiredHost][0]
            try:
                g.migrateVM(goodHost)
            except:
                raise xenrt.XRTFailure("Unable to migrate VM away from host "
                                       "with expired license")

        # VMs running on the expired host should suspend
        if expiredHost:
            xenrt.TEC().logverbose("Checking VMs on the disabled host can be suspended")
            g = self.guests[expiredHost][1]
            try:
                g.suspend()
            except:
                raise xenrt.XRTFailure("Unable to suspend VM on host with "
                                       "expired license")
            suspendedGuest = g

        # Migrating VMs to the expired host should be blocked
        # if expiredHost:
        # This is not in the requirements, so don't run for now...
        if False:
            g = self.guests[goodHost][0]
            allowed = False
            try:
                g.migrateVM(expiredHost)
                allowed = True
            except:
                pass
            if allowed:
                raise xenrt.XRTFailure("Allowed to migrate VM to host with "
                                       "expired license")

        # Resuming VMs on the expired host should be blocked
        if expiredHost:
            xenrt.TEC().logverbose("Checking VMs on the expired host cannot be resumed")
            allowed = False
            try:
                suspendedGuest.resume()
                allowed = True
            except:
                pass
            if allowed:
                raise xenrt.XRTFailure("Allowed to resume suspended guest on "
                                       "host with expired license")

    def resetPool(self):
        # Reset the pool (put VMs back in the right place, enable HA if required
        # etc)
        for h in self.pool.getHosts():
            if h.getHostParam("enabled") == "false":
                h.enable()
            for g in self.guests[h]:
                if g.getState() == "DOWN":
                    g.setHost(h)
                    g.start()
                elif g.getState() == "SUSPENDED":
                    g.setHost(h)
                    g.resume()
                else:
                    g.findHost()
                    if g.getHost() != h:
                        g.migrateVM(h)

        if self.HA and not self.pool.haEnabled:
            self.pool.enableHA()

    def run(self, arglist=None):

        # First try the master
        if self.runSubcase("runHost", (True, self.MASTER), "Master", "LicenseExpire") != \
           xenrt.RESULT_PASS:
            return

        self.resetPool()

        # Repeat with a slave of each SKU type
        if self.EDITION:
            for s in self.EDITION:
                if self.runSubcase("runHost", (False, s), "Slave%s" % (string.replace(s, " ", "_")), "LicenseExpire") != \
                   xenrt.RESULT_PASS:
                    return
        else:
            for s in self.SKU:
                if self.runSubcase("runHost", (False, s), "Slave%s" % (string.replace(s, " ", "_")), "LicenseExpire") != \
                   xenrt.RESULT_PASS:
                    return

        self.resetPool()

class _LicenseUpgradeBase(_LicenseBase):
    """Base class for license upgrade testcases"""
    UPG_FROM = "FG Free"
    UPG_TO = "FG Paid"
    FEATURES = ["HA", "EmailAlerts"]
    EXPIRED = False

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        if self.EXPIRED:
            # Make it expire in 1 day
            self.host.license(sku=self.UPG_FROM, expirein=1)
            licenseInfo = self.host.getLicenseDetails()
            expiry = xenrt.util.parseXapiTime(licenseInfo['expiry'])
            # Advance the clock
            self.host.execdom0("/etc/init.d/ntpd stop")
            expiretarget = time.gmtime(expiry + 86400)
            self.host.execdom0("date -u %s" %
                           (time.strftime("%m%d%H%M%Y",expiretarget)))
            self.host.restartToolstack()
        else:
            self.host.license(sku=self.UPG_FROM)

        self.allowed = False

    def run(self, arglist=None):
        # Check the features are unavailable
        if not self.EXPIRED:
            for f in self.FEATURES:
                if self.runSubcase("feature%s" % (f), (), "PreUpgrade", f) != \
                    xenrt.RESULT_PASS:
                    return

        # Upgrade the license
        self.host.license(sku=self.UPG_TO)
        self.allowed = True

        # Check the features
        for f in self.FEATURES:
            if self.runSubcase("feature%s" % (f), (), "PostUpgrade", f) != \
               xenrt.RESULT_PASS:
                return

    def postRun(self):
        self.host.execdom0("ntpdate `grep -e '^server ' /etc/ntp.conf | sed q | sed 's/server //'` || true")
        self.host.execdom0("/etc/init.d/ntpd start")
        self.host.restartToolstack()
        _LicenseBase.postRun(self)

class _PoolLicenseUpgradeBase(_LicenseUpgradeBase):
    """Base class for pool license upgrade testcases"""
    V6 = False
    ALLOWED_BEFORE = False
    ALLOWED_AFTER = True

    def prepare(self, arglist=None):
        self.pool = self.getDefaultPool()
        self.host = self.pool.master
        for h in self.pool.getHosts():
            if self.V6:
                h.license(edition=self.UPG_FROM)
            else:
                h.license(sku=self.UPG_FROM)

        self.allowed = self.ALLOWED_BEFORE

    def run(self, arglist=None):
        # Check the features are unavailable
        for f in self.FEATURES:
            if self.runSubcase("feature%s" % (f), (), "PreUpgrade", f) != \
                xenrt.RESULT_PASS:
                return

        # Upgrade half the hosts
        hosts = self.pool.getHosts()
        half = len(hosts) / 2
        for i in range(half):
            if self.V6:
                hosts[i].license(edition=self.UPG_TO)
            else:
                hosts[i].license(sku=self.UPG_TO)

        if not self.ALLOWED_AFTER:
            # Downgrading, so as soon as we downgraded one host we shouldn't
            # allow features to work...
            self.allowed = False

        # Check the features are unavailable
        for f in self.FEATURES:
            if self.runSubcase("feature%s" % (f), (), "MidUpgrade", f) != \
                xenrt.RESULT_PASS:
                return

        # Upgrade the remaining hosts
        for h in hosts[half:]:
            if self.V6:
                h.license(edition=self.UPG_TO)
            else:
                h.license(sku=self.UPG_TO)

        self.allowed = self.ALLOWED_AFTER

        # Check the features are available
        for f in self.FEATURES:
            if self.runSubcase("feature%s" % (f), (), "PostUpgrade", f) != \
                xenrt.RESULT_PASS:
                return
           
    def getTCPool(self, host):
        return self.pool

#Default SKU
# For Rio/Miami/Orlando = XE Express
class _DefaultSKU(_LicenseBase):
    pass
class TC8722(_DefaultSKU):
    """Verify no limit on number of concurrent VMs"""
    FEATURE = "ConcurrentVMs"
    ALLOWED = 0
class TC8723(_DefaultSKU):
    """Verify no limit on maximum amount of memory that can be used"""
    FEATURE = "MaxMemory"
    ALLOWED = 0
class TC8724(_DefaultSKU):
    """Verify VLANs cannot be used"""
    FEATURE = "VLAN"
    ALLOWED = False
class TC8725(_DefaultSKU):
    """Verify QoS cannot be used"""
    FEATURE = "QoS"
    ALLOWED = False
class TC8726(_DefaultSKU):
    """Verify Shared SRs cannot be used"""
    FEATURE = "SharedSR"
    ALLOWED = False
class TC8727(_DefaultSKU):
    """Verify pooling is not allowed"""
    FEATURE = "Pooling"
    ALLOWED = False
class TC8728(_DefaultSKU):
    """Verify HA cannot be enabled"""
    FEATURE = "HA"
    ALLOWED = False
class TC8729(_DefaultSKU):
    """Verify WLB cannot be initialised"""
    FEATURE = "Kirkwood"
    ALLOWED = False

# Express edition SKU
class _XEExpressSKU(_LicenseBase):
    SKU = "XE Express"
class TC8731(_XEExpressSKU):
    """Verify no limit on number of concurrent VMs"""
    FEATURE = "ConcurrentVMs"
    ALLOWED = 0
class TC8732(_XEExpressSKU):
    """Verify no limit on maximum amount of memory that can be used"""
    FEATURE = "MaxMemory"
    ALLOWED = 0
class TC8733(_XEExpressSKU):
    """Verify VLANs cannot be used"""
    FEATURE = "VLAN"
    ALLOWED = False
class TC8734(_XEExpressSKU):
    """Verify QoS cannot be used"""
    FEATURE = "QoS"
    ALLOWED = False
class TC8735(_XEExpressSKU):
    """Verify Shared SRs cannot be used"""
    FEATURE = "SharedSR"
    ALLOWED = False
class TC8736(_XEExpressSKU):
    """Verify pooling is not allowed"""
    FEATURE = "Pooling"
    ALLOWED = False
class TC8737(_XEExpressSKU):
    """Verify HA cannot be enabled"""
    FEATURE = "HA"
    ALLOWED = False
class TC8738(_XEExpressSKU):
    """Verify WLB cannot be initialised"""
    FEATURE = "Kirkwood"
    ALLOWED = False


# Server edition SKU
class _XEServerSKU(_LicenseBase):
    SKU = "XE Server"
class TC8740(_XEServerSKU):
    """Verify no limit on number of concurrent VMs"""
    FEATURE = "ConcurrentVMs"
    ALLOWED = 0
class TC8741(_XEServerSKU):
    """Verify no limit on maximum amount of memory that can be used"""
    FEATURE = "MaxMemory"
    ALLOWED = 0
class TC8742(_XEServerSKU):
    """Verify VLANs can be used"""
    FEATURE = "VLAN"
    ALLOWED = True
class TC8743(_XEServerSKU):
    """Verify QoS cannot be used"""
    FEATURE = "QoS"
    ALLOWED = False
class TC8744(_XEServerSKU):
    """Verify Shared SRs cannot be used"""
    FEATURE = "SharedSR"
    ALLOWED = False
class TC8745(_XEServerSKU):
    """Verify pooling is not allowed"""
    FEATURE = "Pooling"
    ALLOWED = False
class TC8746(_XEServerSKU):
    """Verify HA cannot be enabled"""
    FEATURE = "HA"
    ALLOWED = False
class TC8747(_XEServerSKU):
    """Verify WLB cannot be initialised"""
    FEATURE = "Kirkwood"
    ALLOWED = False

# Enterprise edition SKU
class _XEEnterpriseSKU(_LicenseBase):
    SKU = "XE Enterprise"
class TC8749(_XEEnterpriseSKU):
    """Verify no limit on number of concurrent VMs"""
    FEATURE = "ConcurrentVMs"
    ALLOWED = 0
class TC8750(_XEEnterpriseSKU):
    """Verify no limit on maximum amount of memory that can be used"""
    FEATURE = "MaxMemory"
    ALLOWED = 0
class TC8751(_XEEnterpriseSKU):
    """Verify VLANs can be used"""
    FEATURE = "VLAN"
    ALLOWED = True
class TC8752(_XEEnterpriseSKU):
    """Verify QoS can be used"""
    FEATURE = "QoS"
    ALLOWED = True
class TC8753(_XEEnterpriseSKU):
    """Verify Shared SRs can be used"""
    FEATURE = "SharedSR"
    ALLOWED = True
class TC8754(_XEEnterpriseSKU):
    """Verify pooling is allowed"""
    FEATURE = "Pooling"
    ALLOWED = True
class TC8755(_XEEnterpriseSKU):
    """Verify HA can be enabled"""
    FEATURE = "HA"
    ALLOWED = True
class TC8756(_XEEnterpriseSKU):
    """Verify WLB can be initialised"""
    FEATURE = "Kirkwood"
    ALLOWED = True


# Floodgate+ SKUs
# ===============

# Floodgate default SKU (FG Free)
class _FGDefaultSKU(_LicenseBase):
    pass
class TC8779(_FGDefaultSKU):
    """Verify no limit on number of concurrent VMs"""
    FEATURE = "ConcurrentVMs"
    ALLOWED = 0
class TC8780(_FGDefaultSKU):
    """Verify no limit on maximum amount of memory that can be used"""
    FEATURE = "MaxMemory"
    ALLOWED = 0
class TC8781(_FGDefaultSKU):
    """Verify VLANs can be used"""
    FEATURE = "VLAN"
    ALLOWED = True
class TC8782(_FGDefaultSKU):
    """Verify QoS can be used"""
    FEATURE = "QoS"
    ALLOWED = True
class TC8783(_FGDefaultSKU):
    """Verify Shared SRs can be used"""
    FEATURE = "SharedSR"
    ALLOWED = True
class TC8784(_FGDefaultSKU):
    """Verify pooling is allowed"""
    FEATURE = "Pooling"
    ALLOWED = True
class TC8785(_FGDefaultSKU):
    """Verify HA cannot be enabled"""
    FEATURE = "HA"
    ALLOWED = False
class TC8786(_FGDefaultSKU):
    """Verify e-mail alerting cannot be enabled"""
    FEATURE = "EmailAlerts"
    ALLOWED = False
class TC8787(_FGDefaultSKU):
    """Verify Marathon PCI feature can be enabled"""
    FEATURE = "MarathonPCI"
    ALLOWED = True
class TC9054(_FGDefaultSKU):
    """Verify WLB cannot be initialised"""
    FEATURE = "Kirkwood"
    ALLOWED = False
class TC11000(_FGDefaultSKU):
    """Verify DMC cannot be used"""
    FEATURE = "DMC"
    ALLOWED = False
class TC11003(_FGDefaultSKU):
    """Verify checkpoint cannot be used"""
    FEATURE = "Checkpoint"
    ALLOWED = False

class _FGFreeSKU(_LicenseBase):
    SKU = "FG Free"
class TC8788(_FGFreeSKU):
    """Verify no limit on number of concurrent VMs"""
    FEATURE = "ConcurrentVMs"
    ALLOWED = 0
class TC8789(_FGFreeSKU):
    """Verify no limit on maximum amount of memory that can be used"""
    FEATURE = "MaxMemory"
    ALLOWED = 0
class TC8790(_FGFreeSKU):
    """Verify VLANs can be used"""
    FEATURE = "VLAN"
    ALLOWED = True
class TC8791(_FGFreeSKU):
    """Verify QoS can be used"""
    FEATURE = "QoS"
    ALLOWED = True
class TC8792(_FGFreeSKU):
    """Verify Shared SRs can be used"""
    FEATURE = "SharedSR"
    ALLOWED = True
class TC8793(_FGFreeSKU):
    """Verify pooling is allowed"""
    FEATURE = "Pooling"
    ALLOWED = True
class TC8794(_FGFreeSKU):
    """Verify HA cannot be enabled"""
    FEATURE = "HA"
    ALLOWED = False
class TC8795(_FGFreeSKU):
    """Verify e-mail alerting cannot be enabled"""
    FEATURE = "EmailAlerts"
    ALLOWED = False
class TC8796(_FGFreeSKU):
    """Verify Marathon PCI feature can be enabled"""
    FEATURE = "MarathonPCI"
    ALLOWED = True
class TC9055(_FGFreeSKU):
    """Verify WLB cannot be initialised"""
    FEATURE = "Kirkwood"
    ALLOWED = False
class TC10999(_FGFreeSKU):
    """Verify DMC cannot be used"""
    FEATURE = "DMC"
    ALLOWED = False
class TC11004(_FGFreeSKU):
    """Verify checkpoint cannot be used"""
    FEATURE = "Checkpoint"
    ALLOWED = False
class TC11334(_FGFreeSKU):
    """Verify CPU masking is not allowed"""
    FEATURE = "CPUMask"
    ALLOWED = False
class TC11943(_FGFreeSKU):
    """Verify VMPP reading is allowed while writing is not (except deleting)"""
    FEATURE = "VMPP"
    ALLOWED = False
class TC12525(_FGFreeSKU):
    """Verify DVSC can not be used"""
    FEATURE = "DVSC"
    ALLOWED = False
class TC13499(_FGFreeSKU):
    """Verify vGPUs can not be used"""
    FEATURE = "VGPU"
    ALLOWED = False
class TC14441(_FGFreeSKU):
    """Verify DR cannot be used"""
    FEATURE = "DR"
    ALLOWED = False

class _FGPaidSKU(_LicenseBase):
    SKU = "FG Paid"
class TC8797(_FGPaidSKU):
    """Verify no limit on number of concurrent VMs"""
    FEATURE = "ConcurrentVMs"
    ALLOWED = 0
class TC8798(_FGPaidSKU):
    """Verify no limit on maximum amount of memory that can be used"""
    FEATURE = "MaxMemory"
    ALLOWED = 0
class TC8799(_FGPaidSKU):
    """Verify VLANs can be used"""
    FEATURE = "VLAN"
    ALLOWED = True
class TC8800(_FGPaidSKU):
    """Verify QoS can be used"""
    FEATURE = "QoS"
    ALLOWED = True
class TC8801(_FGPaidSKU):
    """Verify Shared SRs can be used"""
    FEATURE = "SharedSR"
    ALLOWED = True
class TC8802(_FGPaidSKU):
    """Verify pooling is allowed"""
    FEATURE = "Pooling"
    ALLOWED = True
class TC8803(_FGPaidSKU):
    """Verify HA can be enabled"""
    FEATURE = "HA"
    ALLOWED = True
class TC8804(_FGPaidSKU):
    """Verify e-mail alerting can be enabled"""
    FEATURE = "EmailAlerts"
    ALLOWED = True
class TC8805(_FGPaidSKU):
    """Verify Marathon PCI feature can be enabled"""
    FEATURE = "MarathonPCI"
    ALLOWED = True
class TC9056(_FGPaidSKU):
    """Verify WLB can be initialised"""
    FEATURE = "Kirkwood"
    ALLOWED = True


class _V6AdvancedEDN(_LicenseBase):
    EDITION = "advanced"
class TC11264(_V6AdvancedEDN):
    """Verify no limit on number of concurrent VMs"""
    FEATURE = "ConcurrentVMs"
    ALLOWED = 0
class TC11265(_V6AdvancedEDN):
    """Verify no limit on maximum amount of memory that can be used"""
    FEATURE = "MaxMemory"
    ALLOWED = 0
class TC11266(_V6AdvancedEDN):
    """Verify VLANs can be used"""
    FEATURE = "VLAN"
    ALLOWED = True
class TC11267(_V6AdvancedEDN):
    """Verify QoS can be used"""
    FEATURE = "QoS"
    ALLOWED = True
class TC11268(_V6AdvancedEDN):
    """Verify Shared SRs can be used"""
    FEATURE = "SharedSR"
    ALLOWED = True
class TC11269(_V6AdvancedEDN):
    """Verify pooling is allowed"""
    FEATURE = "Pooling"
    ALLOWED = True
class TC11270(_V6AdvancedEDN):
    """Verify HA can be enabled"""
    FEATURE = "HA"
    ALLOWED = True
class TC11271(_V6AdvancedEDN):
    """Verify e-mail alerting can be enabled"""
    FEATURE = "EmailAlerts"
    ALLOWED = True
class TC11272(_V6AdvancedEDN):
    """Verify Marathon PCI feature can be enabled"""
    FEATURE = "MarathonPCI"
    ALLOWED = True
class TC11290(_V6AdvancedEDN):
    """Verify WLB cannot be initialised"""
    FEATURE = "Kirkwood"
    ALLOWED = False
class TC11273(_V6AdvancedEDN):
    """Verify DMC can be used"""
    FEATURE = "DMC"
    ALLOWED = True
class TC11291(_V6AdvancedEDN):
    """Verify checkpoint cannot be used"""
    FEATURE = "Checkpoint"
    ALLOWED = False
class TC11335(_V6AdvancedEDN):
    """Verify CPU masking is allowed"""
    FEATURE = "CPUMask"
    ALLOWED = True
class TC11944(_V6AdvancedEDN):
    """Verify VMPP reading is allowed while writing is not (except deleting)"""
    FEATURE = "VMPP"
    ALLOWED = False
class TC12522(_V6AdvancedEDN):
    """Verify DVSC can be used"""
    FEATURE = "DVSC"
    ALLOWED = True
class TC13500(_V6AdvancedEDN):
    """Verify vGPUs can be used"""
    FEATURE = "VGPU"
    ALLOWED = False
class TC14442(_V6AdvancedEDN):
    """Verify DR cannot be used"""
    FEATURE = "DR"
    ALLOWED = False

class _V6EnterpriseEDN(_LicenseBase):
    EDITION = "enterprise"
class TC9997(_V6EnterpriseEDN):
    """Verify no limit on number of concurrent VMs"""
    FEATURE = "ConcurrentVMs"
    ALLOWED = 0
class TC9998(_V6EnterpriseEDN):
    """Verify no limit on maximum amount of memory that can be used"""
    FEATURE = "MaxMemory"
    ALLOWED = 0
class TC9999(_V6EnterpriseEDN):
    """Verify VLANs can be used"""
    FEATURE = "VLAN"
    ALLOWED = True
class TC10000(_V6EnterpriseEDN):
    """Verify QoS can be used"""
    FEATURE = "QoS"
    ALLOWED = True
class TC10001(_V6EnterpriseEDN):
    """Verify Shared SRs can be used"""
    FEATURE = "SharedSR"
    ALLOWED = True
class TC10002(_V6EnterpriseEDN):
    """Verify pooling is allowed"""
    FEATURE = "Pooling"
    ALLOWED = True
class TC10003(_V6EnterpriseEDN):
    """Verify HA can be enabled"""
    FEATURE = "HA"
    ALLOWED = True
class TC10004(_V6EnterpriseEDN):
    """Verify e-mail alerting can be enabled"""
    FEATURE = "EmailAlerts"
    ALLOWED = True
class TC10005(_V6EnterpriseEDN):
    """Verify Marathon PCI feature can be enabled"""
    FEATURE = "MarathonPCI"
    ALLOWED = True
class TC10006(_V6EnterpriseEDN):
    """Verify WLB can be initialised"""
    FEATURE = "Kirkwood"
    ALLOWED = True
class TC11001(_V6EnterpriseEDN):
    """Verify DMC can be used"""
    FEATURE = "DMC"
    ALLOWED = True
class TC11005(_V6EnterpriseEDN):
    """Verify checkpoint can be used"""
    FEATURE = "Checkpoint"
    ALLOWED = True
class TC11336(_V6EnterpriseEDN):
    """Verify CPU masking is allowed"""
    FEATURE = "CPUMask"
    ALLOWED = True
class TC11945(_V6EnterpriseEDN):
    """Verify VMPP reading is allowed while writing is not (except deleting)"""
    FEATURE = "VMPP"
    ALLOWED = False
class TC12523(_V6EnterpriseEDN):
    """Verify DVSC can be used"""
    FEATURE = "DVSC"
    ALLOWED = True
class TC13497(_V6EnterpriseEDN):
    """Verify vGPUs can be used"""
    FEATURE = "VGPU"
    ALLOWED = True
class TC14443(_V6EnterpriseEDN):
    """Verify DR cannot be used """
    FEATURE = "DR"
    ALLOWED = False

class _V6PlatinumEDN(_LicenseBase):
    EDITION = "platinum"
class TC10008(_V6PlatinumEDN):
    """Verify no limit on number of concurrent VMs"""
    FEATURE = "ConcurrentVMs"
    ALLOWED = 0
class TC10009(_V6PlatinumEDN):
    """Verify no limit on maximum amount of memory that can be used"""
    FEATURE = "MaxMemory"
    ALLOWED = 0
class TC10010(_V6PlatinumEDN):
    """Verify VLANs can be used"""
    FEATURE = "VLAN"
    ALLOWED = True
class TC10011(_V6PlatinumEDN):
    """Verify QoS can be used"""
    FEATURE = "QoS"
    ALLOWED = True
class TC10012(_V6PlatinumEDN):
    """Verify Shared SRs can be used"""
    FEATURE = "SharedSR"
    ALLOWED = True
class TC10013(_V6PlatinumEDN):
    """Verify pooling is allowed"""
    FEATURE = "Pooling"
    ALLOWED = True
class TC10014(_V6PlatinumEDN):
    """Verify HA can be enabled"""
    FEATURE = "HA"
    ALLOWED = True
class TC10015(_V6PlatinumEDN):
    """Verify e-mail alerting can be enabled"""
    FEATURE = "EmailAlerts"
    ALLOWED = True
class TC10016(_V6PlatinumEDN):
    """Verify Marathon PCI feature can be enabled"""
    FEATURE = "MarathonPCI"
    ALLOWED = True
class TC10017(_V6PlatinumEDN):
    """Verify WLB can be initialised"""
    FEATURE = "Kirkwood"
    ALLOWED = True
class TC21479(_V6PlatinumEDN):
    """Verify WLB cannot be initialised for unlicensed host on Creedence"""
    FEATURE = "Kirkwood"
    ALLOWED = False
class TC11002(_V6PlatinumEDN):
    """Verify DMC can be used"""
    FEATURE = "DMC"
    ALLOWED = True
class TC11006(_V6PlatinumEDN):
    """Verify checkpoint can be used"""
    FEATURE = "Checkpoint"
    ALLOWED = True
class TC11337(_V6PlatinumEDN):
    """Verify CPU masking is allowed"""
    FEATURE = "CPUMask"
    ALLOWED = True
class TC11946(_V6PlatinumEDN):
    """Verify VMPP operations are all allowed"""
    FEATURE = "VMPP"
    ALLOWED = True
class TC12524(_V6PlatinumEDN):
    """Verify DVSC can be used"""
    FEATURE = "DVSC"
    ALLOWED = True
class TC13498(_V6PlatinumEDN):
    """Verify vGPUs can be used"""
    FEATURE = "VGPU"
    ALLOWED = True
class TC14444(_V6PlatinumEDN):
    """Verify DR can be used"""
    FEATURE = "DR"
    ALLOWED = True
    
class TC8879(_LicenseBase):
    """Verify an XE Server SKU is correctly treated as an FG Paid SKU"""
    FEATURE = "Multiple"
    SKU = "XE Server"
    FEATURES = {"ConcurrentVMs":0, "MaxMemory":0, "VLAN":True, "QoS":True,
                "SharedSR":True, "Pooling":True, "HA":True, "EmailAlerts":True,
                "MarathonPCI":True}

    def run(self, arglist=None):
        for f in self.FEATURES:
            self.allowed = self.FEATURES[f]
            if self.runSubcase("feature%s" % (f), (), self.SKU.replace(" ","_"),
                               f) != xenrt.RESULT_PASS:
                return
            for g in self._guestsToUninstall:
                try:
                    if g.getState() == "SUSPENDED":
                        g.resume()
                except:
                    pass
                try:
                    if g.getState() != "DOWN":
                        g.shutdown(again=True)
                except:
                    pass

class _FreePaidPool(_PoolLicenseBase):
    SKU1 = "FG Free"
    SKU2 = "FG Paid"

class TC8807(_FreePaidPool):
    """Verify HA cannot be enabled"""
    FEATURE = "HA"
    ALLOWED = False
class TC8808(_FreePaidPool):
    """Verify e-mail alerting cannot be enabled"""
    FEATURE = "EmailAlerts"
    ALLOWED = False
class TC8809(_FreePaidPool):
    """Verify Marathon PCI feature can be enabled"""
    FEATURE = "MarathonPCI"
    ALLOWED = True

class _PaidPool(_PoolLicenseBase):
    SKU1 = "FG Paid"
    SKU2 = "FG Paid"

class TC8888(_PaidPool):
    """Verify HA can be enabled"""
    FEATURE = "HA"
    ALLOWED = True
class TC8889(_PaidPool):
    """Verify e-mail alerting can be enabled"""
    FEATURE = "EmailAlerts"
    ALLOWED = True
class TC8890(_PaidPool):
    """Verify Marathon PCI feature can be enabled"""
    FEATURE = "MarathonPCI"
    ALLOWED = True
class TC9057(_PaidPool):
    """Verify WLB can be initialised"""
    FEATURE = "Kirkwood"
    ALLOWED = True

class _PaidPoolWithServer(_PoolLicenseBase):
    SKU1 = "FG Paid"
    SKU2 = "XE Server"

class TC8892(_PaidPool):
    """Verify HA can be enabled"""
    FEATURE = "HA"
    ALLOWED = True
class TC8893(_PaidPool):
    """Verify e-mail alerting can be enabled"""
    FEATURE = "EmailAlerts"
    ALLOWED = True
class TC8894(_PaidPool):
    """Verify Marathon PCI feature can be enabled"""
    FEATURE = "MarathonPCI"
    ALLOWED = True


class _FreePool(_V6PoolLicenseBase):
    EDN1 = "free"
    EDN2 = "free"
    ALLOWED = False
class TC10044(_FreePool):
    """Verify HA cannot be enabled"""
    FEATURE = "HA"
class TC10045(_FreePool):
    """Verify e-mail alerting cannot be enabled"""
    FEATURE = "EmailAlerts"
class TC10046(_FreePool):
    """Verify WLB cannot be initialised"""
    FEATURE = "Kirkwood"

class _FreeAdvancedPool(_V6PoolLicenseBase):
    EDN1 = "free"
    EDN2 = "advanced"
    ALLOWED = False
class TC11279(_FreeAdvancedPool):
    """Verify HA cannot be enabled"""
    FEATURE = "HA"
class TC11280(_FreeAdvancedPool):
    """Verify e-mail alerting cannot be enabled"""
    FEATURE = "EmailAlerts"
class TC11281(_FreeAdvancedPool):
    """Verify WLB cannot be initialised"""
    FEATURE = "Kirkwood"
    
class _FreeEnterprisePool(_V6PoolLicenseBase):
    EDN1 = "free"
    EDN2 = "enterprise"
    ALLOWED = False
class TC10041(_FreeEnterprisePool):
    """Verify HA cannot be enabled"""
    FEATURE = "HA"
class TC10042(_FreeEnterprisePool):
    """Verify e-mail alerting cannot be enabled"""
    FEATURE = "EmailAlerts"
class TC10043(_FreeEnterprisePool):
    """Verify WLB cannot be initialised"""
    FEATURE = "Kirkwood"

class _FreePlatinumPool(_V6PoolLicenseBase):
    EDN1 = "free"
    EDN2 = "platinum"
    ALLOWED = False
class TC10038(_FreePlatinumPool):
    """Verify HA cannot be enabled"""
    FEATURE = "HA"
class TC10039(_FreePlatinumPool):
    """Verify e-mail alerting cannot be enabled"""
    FEATURE = "EmailAlerts"
class TC10040(_FreePlatinumPool):
    """Verify WLB cannot be initialised"""
    FEATURE = "Kirkwood"

class _AdvancedPool(_V6PoolLicenseBase):
    EDN1 = "advanced"
    EDN2 = "advanced"
    ALLOWED = True
class TC11275(_AdvancedPool):
    """Verify HA can be enabled"""
    FEATURE = "HA"
class TC11276(_AdvancedPool):
    """Verify e-mail alerting can be enabled"""
    FEATURE = "EmailAlerts"
class TC11277(_AdvancedPool):
    """Verify WLB can be initialised"""
    FEATURE = "Kirkwood"
    ALLOWED = False

class _AdvancedEnterprisePool(_V6PoolLicenseBase):
    EDN1 = "advanced"
    EDN2 = "enterprise"
    ALLOWED = True
class TC11283(_AdvancedEnterprisePool):
    """Verify HA cannot be enabled"""
    FEATURE = "HA"
class TC11284(_AdvancedEnterprisePool):
    """Verify e-mail alerting cannot be enabled"""
    FEATURE = "EmailAlerts"
class TC11285(_AdvancedEnterprisePool):
    """Verify WLB cannot be initialised"""
    FEATURE = "Kirkwood"
    ALLOWED = False

class _AdvancedPlatinumPool(_V6PoolLicenseBase):
    EDN1 = "advanced"
    EDN2 = "platinum"
    ALLOWED = True
class TC11287(_AdvancedPlatinumPool):
    """Verify HA cannot be enabled"""
    FEATURE = "HA"
class TC11288(_AdvancedPlatinumPool):
    """Verify e-mail alerting cannot be enabled"""
    FEATURE = "EmailAlerts"
class TC11289(_AdvancedPlatinumPool):
    """Verify WLB cannot be initialised"""
    FEATURE = "Kirkwood"
    ALLOWED = False
    
class _EnterprisePool(_V6PoolLicenseBase):
    EDN1 = "enterprise"
    EDN2 = "enterprise"
    ALLOWED = True
class TC10035(_EnterprisePool):
    """Verify HA can be enabled"""
    FEATURE = "HA"
class TC10036(_EnterprisePool):
    """Verify e-mail alerting can be enabled"""
    FEATURE = "EmailAlerts"
class TC10037(_EnterprisePool):
    """Verify WLB can be initialised"""
    FEATURE = "Kirkwood"

class _PlatinumPool(_V6PoolLicenseBase):
    EDN1 = "platinum"
    EDN2 = "platinum"
    ALLOWED = True
class TC10050(_PlatinumPool):
    """Verify HA can be enabled"""
    FEATURE = "HA"
class TC10051(_PlatinumPool):
    """Verify e-mail alerting can be enabled"""
    FEATURE = "EmailAlerts"
class TC10052(_PlatinumPool):
    """Verify WLB can be initialised"""
    FEATURE = "Kirkwood"

class _EnterprisePlatinumPool(_V6PoolLicenseBase):
    EDN1 = "enterprise"
    EDN2 = "platinum"
    ALLOWED = True
class TC10047(_EnterprisePlatinumPool):
    """Verify HA can be enabled"""
    FEATURE = "HA"
class TC10048(_EnterprisePlatinumPool):
    """Verify e-mail alerting can be enabled"""
    FEATURE = "EmailAlerts"
class TC10049(_EnterprisePlatinumPool):
    """Verify WLB can be initialised"""
    FEATURE = "Kirkwood"

class _MixedPool(_V6PoolLicenseBase):
    EDN1 = "free"
    EDN2 = "advanced"
    EDN3 = "enterprise"
    EDN4 = "platinum"
    ALLOWED = False
class TC10032(_MixedPool):
    """Verify HA cannot be enabled"""
    FEATURE = "HA"
class TC10033(_MixedPool):
    """Verify e-mail alerting cannot be enabled"""
    FEATURE = "EmailAlerts"
class TC10034(_MixedPool):
    """Verify WLB cannot be initialised"""
    FEATURE = "Kirkwood"


class TC8811(_PoolJoinBase):
    """Verify pool-join of a FG Free host to an FG Paid pool is blocked"""
    POOL_SKU = "FG Paid"
    JOIN_SKU = "FG Free"
class TC8812(_PoolJoinBase):
    """Verify pool-join of an FG Paid host to an FG Free pool is blocked"""
    POOL_SKU = "FG Free"
    JOIN_SKU = "FG Paid"

# V6 pool join tests

# Joining free
class TC10070(_PoolJoinBase):
    """Verify pool-join of a free host to an enterprise pool is blocked"""
    POOL_EDNS = ["enterprise"]
    JOIN_EDN = "free"
class TC10071(_PoolJoinBase):
    """Verify pool-join of a free host to a platinum pool is blocked"""
    POOL_EDNS = ["platinum"]
    JOIN_EDN = "free"
class TC10072(_PoolJoinBase):
    """Verify pool-join of a free host to a mixed (enterprise+platinum) pool
       is blocked"""
    POOL_EDNS = ["enterprise", "platinum"]
    JOIN_EDN = "free"
class TC10073(_PoolJoinBase):
    """Verify pool-join of a free host to a mixed (free+enterprise) pool is
       allowed"""
    POOL_EDNS = ["free", "enterprise"]
    JOIN_EDN = "free"
    ALLOWED = True
class TC10074(_PoolJoinBase):
    """Verify pool-join of a free host to a mixed (free+platinum) pool is
       allowed"""
    POOL_EDNS = ["free", "platinum"]
    JOIN_EDN = "free"
    ALLOWED = True
# Joining enterprise
class TC10075(_PoolJoinBase):
    """Verify pool-join of an enterprise host to a free pool is blocked"""
    POOL_EDNS = ["free"]
    JOIN_EDN = "enterprise"
class TC10076(_PoolJoinBase):
    """Verify pool-join of an enterprise host to a mixed (free+enterprise)
       pool is blocked"""
    POOL_EDNS = ["free", "enterprise"]
    JOIN_EDN = "enterprise"
class TC10077(_PoolJoinBase):
    """Verify pool-join of an enterprise host to a mixed (free+platinum)
       pool is blocked"""
    POOL_EDNS = ["free", "platinum"]
    JOIN_EDN = "enterprise"
class TC10078(_PoolJoinBase):
    """Verify pool-join of an enterprise host to a platinum pool is blocked"""
    POOL_EDNS = ["platinum"]
    JOIN_EDN = "enterprise"
class TC10079(_PoolJoinBase):
    """Verify pool-join of an enterprise host to a mixed (enterprise+platinum) 
       pool is allowed"""
    POOL_EDNS = ["enterprise", "platinum"]
    JOIN_EDN = "enterprise"
    ALLOWED = True
class TC11220(_PoolJoinBase):
    """Verify pool-join of a XD site license host to a mixed (enterprise+platinum)
       pool is allowed"""
    POOL_EDNS = ["enterprise", "platinum"]
    JOIN_EDN = "enterprise-xd"
    ALLOWED = True
    LICENSES = ["valid-enterprise", "valid-platinum", "valid-enterprise-xd"]
# Joining platinum
class TC10080(_PoolJoinBase):
    """Verify pool-join of a platinum host to a free pool is blocked"""
    POOL_EDNS = ["free"]
    JOIN_EDN = "platinum"
class TC10081(_PoolJoinBase):
    """Verify pool-join of a platinum host to a mixed (free+enterprise) pool
       is blocked"""
    POOL_EDNS = ["free", "enterprise"]
    JOIN_EDN = "platinum"
class TC10082(_PoolJoinBase):
    """Verify pool-join of a platinum host to a mixed (free+platinum) pool
       is blocked"""
    POOL_EDNS = ["free", "platinum"]
    JOIN_EDN = "platinum"
class TC10083(_PoolJoinBase):
    """Verify pool-join of a platinum host to an enterprise pool is blocked"""
    POOL_EDNS = ["enterprise"]
    JOIN_EDN = "platinum"
class TC10084(_PoolJoinBase):
    """Verify pool-join of a platinum host to a mixed (enterprise+platinum) pool
       is blocked"""
    POOL_EDNS = ["enterprise", "platinum"]
    JOIN_EDN = "platinum"
class TC11292(_PoolJoinBase):
    """Verify pool-join of an advanced host to a free pool is blocked"""
    POOL_EDNS = ["free"]
    JOIN_EDN = "advanced"
class TC11293(_PoolJoinBase):
    """Verify pool-join of an advanced host to a enterprise pool is blocked"""
    POOL_EDNS = ["enterprise"]
    JOIN_EDN = "advanced"
class TC11294(_PoolJoinBase):
    """Verify pool-join of an advanced host to a platinum pool is blocked"""
    POOL_EDNS = ["platinum"]
    JOIN_EDN = "advanced"
class TC11295(_PoolJoinBase):
    """Verify pool-join of an advanced host to a mixed (free+advanced) pool is
    blocked"""
    POOL_EDNS = ["free", "advanced"]
    JOIN_EDN = "advanced"
class TC11298(_PoolJoinBase):
    """Verify pool-join of an advanced host to a mixed (advanced+enterprise)
    pool is allowed"""
    POOL_EDNS = ["advanced", "enterprise"]
    JOIN_EDN = "advanced"
    ALLOWED = True
class TC11299(_PoolJoinBase):
    """Verify pool-join of an advanced host to a mixed (advanced+platinum)
    pool is allowed"""
    POOL_EDNS = ["advanced", "platinum"]
    JOIN_EDN = "advanced"
    ALLOWED = True
class TC11301(_PoolJoinBase):
    """Verify pool-join of a free host to an advanced pool is blocked"""
    POOL_EDNS = ["advanced"]
    JOIN_EDN = "free"
class TC11302(_PoolJoinBase):
    """Verify pool-join of a enterprise host to an advanced pool is blocked"""
    POOL_EDNS = ["advanced"]
    JOIN_EDN = "enterprise"
class TC11303(_PoolJoinBase):
    """Verify pool-join of a platinum host to an advanced pool is blocked"""
    POOL_EDNS = ["advanced"]
    JOIN_EDN = "platinum"
class TC11304(_PoolJoinBase):
    """Verify pool-join of a free host to an mixed (free+advanced) pool is
    allowed"""
    POOL_EDNS = ["free", "advanced"]
    JOIN_EDN = "free"
    ALLOWED = True
class TC11305(_PoolJoinBase):
    """Verify pool-join of a enterprise host to an mixed (advanced+enterprise)
    pool is blocked"""
    POOL_EDNS = ["advanced","enterprise"]
    JOIN_EDN = "enterprise"
class TC11306(_PoolJoinBase):
    """Verify pool-join of a platinum host to an mixed (advanced+platinum)
    pool is blocked"""
    POOL_EDNS = ["advanced","platinum"]
    JOIN_EDN = "platinum"

class TC8816(_LicenseExpireBase):
    """Verify expiry of a default license is handled correctly"""
    SKU = None
    EXPIREDAYS = 30

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        if self.host.lookup("FG_FREE_NO_ACTIVATION", False, boolean=True):
            # No activation so no 30 day license
            pass
        else:
            # Standard Floodgate 30 day activation
            _LicenseExpireBase.prepare(self, arglist)

    def run(self, arglist):
        if self.host.lookup("FG_FREE_NO_ACTIVATION", False, boolean=True):
            # No activation so no 30 day license

            # Determine the expiry time of the current license
            licenseInfo = self.host.getLicenseDetails()
            expiry = xenrt.util.parseXapiTime(licenseInfo['expiry'])
            if expiry < 2051398800:
                raise xenrt.XRTFailure(\
                    "Default license on a build that does not use "
                    "activation expires earlier than expected")
        else:
            # Standard Floodgate 30 day activation
            _LicenseExpireBase.run(self, arglist)
        
    
class TC8817(_LicenseExpireBase):
    """Verify expiry of a FG Free license is handled correctly"""
    SKU = "FG Free"
class TC8818(_LicenseExpireBase):
    """Verify expiry of a FG Paid license is handled correctly"""
    SKU = "FG Paid"
class TC11307(_LicenseExpireBase):
    """Verify expiry of a V6 advanced license is handled correctly"""
    EDITION = "advanced"
class TC10018(_LicenseExpireBase):
    """Verify expiry of a V6 enterprise license is handled correctly"""
    EDITION = "enterprise"
class TC10019(_LicenseExpireBase):
    """Verify expiry of a V6 platinum license is handled correctly"""
    EDITION = "platinum"

class TC8836(_PoolLicenseExpireBase):
    """Verify license expiry in an FG Free pool is handled correctly"""
    SKU = ["FG Free"]
    MASTER = "FG Free"
class TC8837(_PoolLicenseExpireBase):
    """Verify license expiry in a mixed pool, with a free master is handled
       correctly"""
    SKU = ["FG Paid", "FG Free"]
    MASTER = "FG Free"
class TC8838(_PoolLicenseExpireBase):
    """Verify license expiry in a mixed pool, with a paid master is handled
       correctly"""
    SKU = ["FG Free", "FG Paid"]
    MASTER = "FG Paid"
class TC8839(_PoolLicenseExpireBase):
    """Verify license expiry in an FG Paid pool is handled correctly"""
    SKU = ["FG Paid"]
    MASTER = "FG Paid"
class TC8840(_PoolLicenseExpireBase):
    """Verify license expiry in an FG Paid pool, with HA enabled is handled
       correctly"""
    SKU = ["FG Paid"]
    MASTER = "FG Paid"
    HA = True

# V6 Pool license expiry
class TC10056(_PoolLicenseExpireBase):
    """Verify license expiry in a mixed (free+enterprise) pool, with a free
       master is handled correctly"""
    EDITION = ["free", "enterprise"]
    MASTER = "free"
class TC10057(_PoolLicenseExpireBase):
    """Verify license expiry in a mixed (free+enterprise) pool, with an enterpise
       master is handled correctly"""
    EDITION = ["free", "enterprise"]
    MASTER = "enterprise"
class TC10058(_PoolLicenseExpireBase):
    """Verify license expiry in a mixed (free+platinum) pool, with a free
       master is handled correctly"""
    EDITION = ["free", "platinum"]
    MASTER = "free"
class TC10059(_PoolLicenseExpireBase):
    """Verify license expiry in a mixed (enterprise+platinum) pool, with an
       enterprise master is handled correctly"""
    EDITION = ["enterprise", "platinum"]
    MASTER = "enterprise"
class TC10060(_PoolLicenseExpireBase):
    """Verify license expiry in a mixed (enterprise+platinum) pool, with a
       platinum master and HA enabled is handled correctly"""
    EDITION = ["enterprise", "platinum"]
    MASTER = "platinum"
    HA = True
class TC10061(_PoolLicenseExpireBase):
    """Verify license expiry in a mixed (free+enterprise+platinum) pool, with a
       free master is handled correctly"""
    EDITION = ["enterprise", "platinum"]
    MASTER = "free"
class TC10062(_PoolLicenseExpireBase):
    """Verify license expiry in a mixed (free+enterprise+platinum) pool, with an
       enterprise master is handled correctly"""
    EDITION = ["platinum", "enterprise"]
    MASTER = "enterprise"
class TC11309(_PoolLicenseExpireBase):
    """Verify license expiry in an advanced pool is handled correctly"""
    EDITION = ["advanced"]
    MASTER = "advanced"
class TC10063(_PoolLicenseExpireBase):
    """Verify license expiry in an enterprise pool is handled correctly"""
    EDITION = ["enterprise"]
    MASTER = "enterprise"
class TC10064(_PoolLicenseExpireBase):
    """Verify license expiry in a platinum pool is handled correctly"""
    EDITION = ["platinum"]
    MASTER = "platinum"
class TC11310(_PoolLicenseExpireBase):
    """Verify license expiry in a mixed (free+advanced) pool, with a free
       master is handled correctly"""
    EDITION = ["free", "advanced"]
    MASTER = "free"
class TC11311(_PoolLicenseExpireBase):
    """Verify license expiry in a mixed (free+advanced) pool, with an advanced
       master is handled correctly"""
    EDITION = ["free", "advanced"]
    MASTER = "advanced"
class TC11312(_PoolLicenseExpireBase):
    """Verify license expiry in a mixed (advanced+enterprise) pool, with an
    advanced master is handled correctly"""
    EDITION = ["advanced", "enterprise"]
    MASTER = "advanced"
class TC11313(_PoolLicenseExpireBase):
    """Verify license expiry in a mixed (advanced+enterprise) pool, with an
    enterprise master is handled correctly"""
    EDITION = ["advanced", "enterprise"]
    MASTER = "enterprise"
class TC11314(_PoolLicenseExpireBase):
    """Verify license expiry in a mixed (advanced+platinum) pool, with an
    advanced master is handled correctly"""
    EDITION = ["advanced", "platinum"]
    MASTER = "advanced"
class TC11315(_PoolLicenseExpireBase):
    """Verify license expiry in a mixed (advanced+platinum) pool, with a
    platinum master is handled correctly"""
    EDITION = ["advanced", "platinum"]
    MASTER = "platinum"
class TC11316(_PoolLicenseExpireBase):
    """Verify license expiry in a mixed (advanced+enterprise+platinum) pool,
    with an advanced master is handled correctly"""
    EDITION = ["enterprise", "platinum"]
    MASTER = "advanced"
class TC11317(_PoolLicenseExpireBase):
    """Verify license expiry in a mixed (advanced+enterprise+platinum) pool,
    with an enterprise master is handled correctly"""
    EDITION = ["advanced", "platinum"]
    MASTER = "enterprise"
class TC11318(_PoolLicenseExpireBase):
    """Verify license expiry in a mixed (advanced+enterprise+platinum) pool,
    with a platinum master is handled correctly"""
    EDITION = ["advanced", "enterprise"]
    MASTER = "platinum"


class TC8863(_LicenseUpgradeBase):
    """Upgrade valid FG Free license to FG Paid license on single host"""
    pass
class TC8864(_LicenseUpgradeBase):
    """Upgrade expired FG Free license to FG Paid license on single host"""
    EXPIRED = True
class TC8865(_PoolLicenseUpgradeBase):
    """Upgrade FG Free pool to FG Paid pool"""
    pass

# V6 Pool upgrade TCs
class _V6PoolLicenseUpgradeBase(_PoolLicenseUpgradeBase):
    """Base class for V6 pool license upgrade TCs"""
    V6 = True

class TC10065(_V6PoolLicenseUpgradeBase):
    """Upgrade free pool to enterprise pool"""
    UPG_FROM = "free"
    UPG_TO = "enterprise"
class TC10066(_V6PoolLicenseUpgradeBase):
    """Upgrade enterprise pool to platinum pool"""
    UPG_FROM = "enterprise"
    ALLOWED_BEFORE = True
    UPG_TO = "platinum"
class TC10067(_V6PoolLicenseUpgradeBase):
    """Downgrade platinum pool to enterprise pool"""
    UPG_FROM = "platinum"
    ALLOWED_BEFORE = True
    UPG_TO = "enterprise"
class TC10068(_V6PoolLicenseUpgradeBase):
    """Downgrade enterprise pool to free pool"""
    UPG_FROM = "enterprise"
    ALLOWED_BEFORE = True
    UPG_TO = "free"
    ALLOWED_AFTER = False
class TC11330(_V6PoolLicenseUpgradeBase):
    """Downgrade advanced pool to free pool"""
    UPG_FROM = "advanced"
    ALLOWED_BEFORE = True
    UPG_TO = "free"
    ALLOWED_AFTER = False
class TC11331(_V6PoolLicenseUpgradeBase):
    """Upgrade advanced pool to enterprise pool"""
    UPG_FROM = "advanced"
    ALLOWED_BEFORE = True
    UPG_TO = "enterprise"
class TC11332(_V6PoolLicenseUpgradeBase):
    """Upgrade free pool to advanced pool"""
    UPG_FROM = "free"
    UPG_TO = "advanced"
class TC11333(_V6PoolLicenseUpgradeBase):
    """Downgrade enterprise pool to advanced pool"""
    UPG_FROM = "enterprise"
    ALLOWED_BEFORE = True
    UPG_TO = "advanced"

class TC8866(xenrt.TestCase):
    """CLI host-license-view output should not contain the sockets or sku_type fields"""

    def run(self, arglist):

        host = self.getDefaultHost()
        cli = host.getCLIInstance()
        data = cli.execute("host-license-view",
                           "host-uuid=%s" % (host.getMyHostUUID()))
        found = []
        for field in ["sockets", "sku_type"]:
            if re.search("\s+%s:" % (field), data):
                found.append(field)
        if len(found) > 0:
            raise xenrt.XRTFailure("Fields found in host-license-view: %s" %
                                   (string.join(found)))
        
class TC8873(xenrt.TestCase):
    """On first boot a host should not replace a FG Free license with the 30 day trial if it exists"""

    def prepare(self, arglist):
        self.overlay = None
        
        # Build an overlay with a free license
        self.overlay =  xenrt.NFSDirectory()
        self.keyfile = ("%s/keys/xenserver/%s/FG_Free" % 
                        (xenrt.TEC().lookup("XENRT_CONF"),
                         xenrt.TEC().lookup("PRODUCT_VERSION")))
        self.overlay.copyIn(self.keyfile, "etc/xensource/license")
        self.overlay.copyIn(self.keyfile, "TC-8873")
        
        # Install the host and apply this overlay
        self.host = xenrt.lib.xenserver.createHost(license=False,
                                                   overlay=self.overlay)
        # Get logs from the host
        self.getLogsFrom(self.host)

        # Check the overlay worked
        if self.host.execdom0("test -e /TC-8873", retval="code") != 0:
            raise xenrt.XRTError("Overlay application did not work")

    def run(self, arglist):
        # Check the license used in the overlay is the one in force on
        # the host

        # Read the license we put in the overlay
        f = file(self.keyfile, "r")
        data = f.read()
        f.close()
        r = re.search(r"expiry=\"(.*?)\"", data)
        if not r:
            raise xenrt.XRTError("Could not parse expiry", data)
        expiry = r.group(1)
        r = re.search(r"serialnumber=\"(.*?)\"", data)
        if not r:
            raise xenrt.XRTError("Could not parse serialnumber", data)
        serialnumber = r.group(1)

        # Read the license reported by xapi
        ld = self.host.getLicenseDetails()

        # Compare
        if not ld.has_key("serialnumber"):
            raise xenrt.XRTError("Could not parse serialnumber from license")
        if ld["serialnumber"] != serialnumber:
            raise xenrt.XRTFailure("License serial changed from overlay",
                                   "License serial '%s' is not what we "
                                   "applied ('%s')" %
                                   (ld["serialnumber"], serialnumber))
        if not ld.has_key("expiry"):
            exp = xenrt.util.parseXapiTime(ld["expiry"])
            delta = abs(exp - int(expiry))
            if delta > 86400:
                raise xenrt.XRTFailure("License expiry changed from overlay")

    def postRun(self):
        if self.overlay:
            self.overlay.remove()
            
class TC8867(xenrt.TestCase):
    """Free license should have sku_marketing_name of "Citrix XenServer"."""

    SKU = "FG Free"
    EDITION = None
    EXPIREDAYS = None
    NAME = "Citrix XenServer"
    NAMEVAR = None

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        
        # Apply a license if necessary
        if self.EDITION:
            self.host.license(edition=self.EDITION)
        elif self.SKU:
            self.host.license(sku=self.SKU)
        else:
            self.host.execdom0("rm -f /etc/xensource/license")
            self.host.reboot()
            if self.EXPIREDAYS and \
                   not self.host.lookup("FG_FREE_NO_ACTIVATION",
                                        False,
                                        boolean=True):
                licenseInfo = self.host.getLicenseDetails()
                expiry = xenrt.util.parseXapiTime(licenseInfo['expiry'])

                # This is a number of days the license should expire in
                # Convert the number of seconds in to days
                difference = expiry - xenrt.timenow()
                days = difference / 86400
                if days < (self.EXPIREDAYS - 1) or days > self.EXPIREDAYS:
                    raise xenrt.XRTFailure(\
                        "License does not expire when expected",
                        data="Expecting %d days, found %d" %
                        (self.EXPIREDAYS, days))            

    def run(self, arglist):
        licenseInfo = self.host.getLicenseDetails()
        if self.NAMEVAR:
            expname = self.host.lookup(self.NAMEVAR, self.NAME)
        else:
            expname = self.NAME
        if not licenseInfo.has_key("sku_marketing_name"):
            raise xenrt.XRTFailure("No sku_marketing_name is host-license-view")
        if licenseInfo["sku_marketing_name"] != expname:
            raise xenrt.XRTFailure("License marketing name '%s' is not the "
                                   "expected '%s'" %
                                   (licenseInfo["sku_marketing_name"], expname))

class TC8868(TC8867):
    """Default (free) license should have sku_marketing_name of "Citrix XenServer" or OEM variant"""

    SKU = None
    EXPIREDAYS = 30
    NAME = "Citrix XenServer"
    NAMEVAR = "FG_FREE_MKT_SKU"
    
class TC8869(TC8867):
    """Essentials license should have sku_marketing_name of "Citrix Essentials for XenServer" or OEM variant"""

    SKU = "FG Paid"    
    NAME = "Citrix Essentials for XenServer"
    NAMEVAR = "FG_PAID_MKT_SKU"

class TC11308(TC8867):
    """V6 Advanced license should have sku_marketing_name of "Citrix XenServer Advanced Edition\""""

    EDITION = "advanced"
    NAME = "Citrix XenServer Advanced Edition"

class TC10020(TC8867):
    """V6 Enterprise license should have sku_marketing_name of "Citrix XenServer Enterprise Edition\""""

    EDITION = "enterprise"
    NAME = "Citrix XenServer Enterprise Edition"

class TC10021(TC8867):
    """V6 Platinum license should have sku_marketing_name of "Citrix XenServer Platinum Edition\""""

    EDITION = "platinum"
    NAME = "Citrix XenServer Platinum Edition"

#############################################################################
# V6 Licensing Test Cases                                                   #
#############################################################################

class TC9945(xenrt.TestCase):
    """Verify a valid V6 enterprise license can be applied to a host"""
    LICENSE = "valid-enterprise"
    EDITION = "enterprise"

    def prepare(self, arglist=None):
        guest = self.getGuest("LicenseServer")
        self.v6 = guest.getV6LicenseServer()
        self.v6.removeAllLicenses()
        self.v6.addLicense(self.LICENSE)
        self.host = self.getDefaultHost()

    def run(self, arglist=None):
        self.host.license(edition=self.EDITION, v6server=self.v6)

    def preLogs(self):
        # Collect the v6 server log
        self.v6.getLogfile()

class TC9946(TC9945):
    """Verify a valid V6 platinum license can be applied to a host"""
    LICENSE = "valid-platinum"
    EDITION = "platinum"

class TC9961(xenrt.TestCase):
    """Verify the default license after fresh install"""

    def run(self, arglist=None):
        host = self.getDefaultHost()

        problems = []

        # Check we're the free edition
        if host.paramGet("edition") != "free":
            problems.append("edition is '%s', expecting 'free'" %
                            (host.paramGet("edition")))

        details = host.getLicenseDetails()

        # Check the SKU
        if details.has_key('sku_type'):
            if details['sku_type'] != "XE Express":
                problems.append("sku_type is '%s', expecting 'XE Express'" %
                                (details['sku_type']))
        else:
            problems.append("sku_type not found, expecting 'XE Express'")

        # Check the license expires in 30 days
        if details.has_key('expiry'):
            expiry = xenrt.util.parseXapiTime(details['expiry'])
            difference = expiry - xenrt.timenow()
            days = difference / 86400
            if days < 29 or days > 30:
                problems.append("expires in %d days, expecting 29-30" % (days))

        if len(problems) > 0:
            raise xenrt.XRTFailure("Problems found with default license after "
                                   "fresh install",
                                   data=str(problems))

class _V6Transition(xenrt.TestCase):
    """Base class for V6 licensing transitions TCs"""
    FROM = "free"
    TO = "enterprise"
    HA = False
    BLOCKED = None
    TWOSERVERS = False

    def prepare(self, arglist=None):
        guest = self.getGuest("LicenseServer")
        self.v6 = guest.getV6LicenseServer()
        if self.FROM == "enterprise" or self.TO == "enterprise":
            if not "valid-enterprise" in self.v6.licenses:
                self.v6.addLicense("valid-enterprise")
        if self.FROM == "platinum" or self.TO == "platinum":
            if not "valid-platinum" in self.v6.licenses:
                self.v6.addLicense("valid-platinum")
        if self.FROM == "advanced" or self.TO == "advanced":
            if not "valid-advanced" in self.v6.licenses:
                self.v6.addLicense("valid-advanced")
        self.host = self.getDefaultHost()

        if self.host.paramGet("edition") != self.FROM:
            xenrt.TEC().logverbose("Licensing host to %s" % (self.FROM))
            self.host.license(edition=self.FROM, v6server=self.v6)

        er = ""
        if self.host.special['v6earlyrelease']:
            er = "TP"            
        self.featureFrom = None
        self.featureTo = None
        if self.FROM == "enterprise":
            self.featureFrom = "CXS%s_ENT_CCS" % (er)
        elif self.FROM == "platinum":
            self.featureFrom = "CXS%s_PLT_CCS" % (er)
        elif self.FROM == "advanced":
            self.featureFrom = "CXS%s_ADV_CCS" % (er)
        if self.TO == "enterprise":
            self.featureTo = "CXS%s_ENT_CCS" % (er)
        elif self.TO == "platinum":
            self.featureTo = "CXS%s_PLT_CCS" % (er)
        elif self.TO == "advanced":
            self.featureTo = "CXS%s_ADV_CCS" % (er)

        if self.HA:
            self.pool = xenrt.lib.xenserver.poolFactory(self.host.productVersion)(self.host)
            self.pool.enableHA()

        if self.TWOSERVERS:
            g = self.host.installLicenseServerGuest()
            self.uninstallOnCleanup(g)
            self.v6b = g.getV6LicenseServer()
            if self.TO == "enterprise":
                self.v6b.addLicense("valid-enterprise")
            elif self.TO == "platinum":
                self.v6b.addLicense("valid-platinum")
            elif self.TO == "advanced":
                self.v6b.addLicense("valid-advanced")
        else:
            self.v6b = self.v6

    def run(self, arglist=None):
        xenrt.TEC().logverbose("Transitioning host from %s to %s" % (self.FROM, self.TO))
        try:
            self.host.license(edition=self.TO, v6server=self.v6b, activateFree=False)
        except xenrt.XRTFailure, e:
            if not self.BLOCKED:
                raise e
            if not re.search("The operation could not be performed because HA is enabled on the Pool", str(e)):
                raise xenrt.XRTFailure("Didn't find expected error message when "
                                       "attempting transition to free with HA enabled")            
        else:
            if self.BLOCKED:
                failStr = "Transition from %s to %s" % (self.FROM, self.TO)
                if self.HA:
                    failStr += " with HA enabled"
                failStr += " unexpectedly allowed"
                raise xenrt.XRTFailure(failStr)

        # Verify the license has been checked back in
        if self.featureFrom:
            outcount = len(self.v6.getLicenseUsage(self.featureFrom).keys())
            if not self.BLOCKED and outcount > 0:
                raise xenrt.XRTFailure("%s license not checked back in to license server" % (self.FROM))
            if self.BLOCKED and outcount == 0:
                raise xenrt.XRTFailure("%s license checked back in to license "
                                       "server even though transition blocked "
                                       "by HA" % (self.FROM))

        # Verify a license has been checked out
        if self.featureTo:
            outcount = len(self.v6b.getLicenseUsage(self.featureTo).keys())
            if not self.BLOCKED and outcount == 0:
                raise xenrt.XRTFailure("%s license not checked out of license server" % (self.TO))
            if self.BLOCKED and outcount > 0:
                raise xenrt.XRTFailure("%s license checked out from license "
                                       "server even though transition blocked "
                                       "by HA" % (self.TO))

        if self.TO == "free" and not self.BLOCKED:
            # Check the license expires in 30 days, then activate it
            ld = self.host.getLicenseDetails()
            expiry = xenrt.util.parseXapiTime(ld['expiry'])
            difference = expiry - xenrt.util.timenow()
            days = difference / 86400
            if days < 29 or days > 30:
                raise xenrt.XRTFailure("Free license does not expire when expected",
                                       data="Expecting ~30 days, found %d" % (days))
            self.host.license(edition="free")

    def postRun(self):
        if self.HA:
            try:
                self.pool.disableHA()
            except:
                pass

class TC9951(_V6Transition):
    """Transition from a free to an enterprise V6 license"""
    FROM = "free"
    TO = "enterprise"
class TC9952(_V6Transition):
    """Transition from a free to a platinum V6 license"""
    FROM = "free"
    TO = "platinum"
class TC9953(_V6Transition):
    """Transition from an enterprise to a platinum V6 license"""
    FROM = "enterprise"
    TO = "platinum"
class TC9954(_V6Transition):
    """Transition from an enterprise to a free V6 license"""
    FROM = "enterprise"
    TO = "free"
class TC9955(_V6Transition):
    """Transition from a platinum to an enterprise V6 license"""
    FROM = "platinum"
    TO = "enterprise"
class TC9956(_V6Transition):
    """Transition from a platinum to a free V6 license"""
    FROM = "platinum"
    TO = "free"
class TC9957(_V6Transition):
    """Transition from an enterprise to a free V6 license is blocked when HA is
       enabled"""
    FROM = "enterprise"
    TO = "free"
    HA = True
    BLOCKED = "HA is enabled"
class TC9958(_V6Transition):
    """Transition from a platinum to a free V6 license is blocked when HA is
       enabled"""
    FROM = "platinum"
    TO = "free"
    HA = True
    BLOCKED = "HA is enabled"
class TC9959(_V6Transition):
    """Transition from an enterprise to a platinum V6 license when HA is
       enabled"""
    FROM = "enterprise"
    TO = "platinum"
    HA = True
class TC9960(_V6Transition):
    """Transition from a platinum to an enterprise V6 license when HA is
       enabled"""
    FROM = "platinum"
    TO = "enterprise"
    HA = True
class TC11319(_V6Transition):
    """Transition from an advanced to a free V6 license"""
    FROM = "advanced"
    TO = "free"
class TC11320(_V6Transition):
    """Transition from an advanced to an enterprise v6 license"""
    FROM = "advanced"
    TO = "enterprise"
class TC11321(_V6Transition):
    """Transition from an advanced to a platinum V6 license"""
    FROM = "advanced"
    TO = "platinum"
class TC11322(_V6Transition):
    """Transition from a free to an advanced V6 license"""
    FROM = "free"
    TO = "advanced"
class TC11323(_V6Transition):
    """Transition from an enterprise to an advanced V6 license"""
    FROM = "enterprise"
    TO = "advanced"
class TC11324(_V6Transition):
    """Transition from a platinum to an advanced V6 license"""
    FROM = "platinum"
    TO = "advanced"
class TC11325(_V6Transition):
    """Transition from an advanced to a free V6 license is blocked when HA is
       enabled"""
    FROM = "advanced"
    TO = "free"
    HA = True
    BLOCKED = "HA is enabled"
class TC11326(_V6Transition):
    """Transition from an advanced to an enterprise V6 license when HA is
    enabled"""
    FROM = "advanced"
    TO = "enterprise"
    HA = True
class TC11327(_V6Transition):
    """Transition from an advanced to a platinum V6 license when HA is
    enabled"""
    FROM = "advanced"
    TO = "platinum"
    HA = True
class TC11328(_V6Transition):
    """Transition from an enterprise to an advanced V6 license when HA is
    enabled"""
    FROM = "enterprise"
    TO = "advanced"
    HA = True
class TC11329(_V6Transition):
    """Transition from a platinum to an advanced V6 license when HA is
    enabled"""
    FROM = "platinum"
    TO = "advanced"
    HA = True

class TC10165(xenrt.TestCase):
    """Verify the Date Based Version (DBV) is correct"""

    def run(self, arglist=None):
        host = self.getDefaultHost()
        expectedDBV = host.lookup("V6_DBV", None)
        if not expectedDBV:
            raise xenrt.XRTError("Couldn't find expected Date Based Version "
                                 "(DBV) in config")

        actualDBV = host.paramGet("software-version", "dbv")
        if actualDBV != expectedDBV:
            raise xenrt.XRTFailure("Date Based Version (DBV) set to unexpected "
                                   "value", data="Expecting %s, found %s" %
                                                 (expectedDBV, actualDBV))

# V6 Upgrade TCs

class _V6UpgradeBase(xenrt.TestCase):
    """Base class for V6 licensing upgrade TCs"""
    START_SKU = "XE Enterprise"
    FINISH_EDN = "enterprise"
    GRACE = False

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        if self.START_SKU:
            self.host.license(sku=self.START_SKU)
        self.startLicense = self.host.getLicenseDetails()

    def run(self, arglist=None):
        self.host = self.host.upgrade()
        ld = self.host.getLicenseDetails()

        # Check we made the correct edition
        if ld['edition'] != self.FINISH_EDN:
            raise xenrt.XRTFailure("Host upgraded from %s SKU became %s edition"
                                   " (expecting %s)" % (self.START_SKU,
                                                        ld['edition'],
                                                        self.FINISH_EDN))
        # Check we're in the grace period if relevant
        if self.GRACE:
            expectedDays = self.host.lookup("V6_UPGRADE_GRACE_DAYS", 30)
            actual = xenrt.util.parseXapiTime(ld['expiry']) - xenrt.util.timenow()
            actualDays = actual / 86400
            if actualDays < (expectedDays - 1) or actualDays > expectedDays:
                raise xenrt.XRTFailure("Upgrade grace period is not %d days" %
                                       (expectedDays),
                                       data="License expires in ~%d days" %
                                            (actualDays))

        # Check activation date is preserved if relevant
        if self.START_SKU == "XE Express" or self.START_SKU == "FG Free" or \
           self.START_SKU == None:
           oldExpiryDate = self.startLicense['expiry'].split('T')[0]
           newExpiryDate = ld['expiry'].split('T')[0]
           if oldExpiryDate != newExpiryDate:
                raise xenrt.XRTFailure("Free license reactivation date not "
                                       "preserved across upgrade",
                                       data="Prior to upgrade %s, post %s" %
                                            (self.startLicense['expiry'],
                                             ld['expiry']))


class TC10167(_V6UpgradeBase):
    """Upgrading to V6 licensing with a default 30 day free license"""
    START_SKU = None
    FINISH_EDN = "free"

class TC10168(_V6UpgradeBase):
    """Upgrading to V6 licensing with an activated free license"""
    START_SKU = "XE Express"
    FINISH_EDN = "free"

class TC10169(_V6UpgradeBase):
    """Upgrading to V6 licensing with a server license"""
    START_SKU = "XE Server"
    FINISH_EDN = "enterprise"
    GRACE = True

class TC10170(_V6UpgradeBase):
    """Upgrading to V6 licensing with an enterprise license"""
    START_SKU = "XE Enterprise"
    FINISH_EDN = "enterprise"
    GRACE = True
    

# V6 Grace License TCs
class _V6GraceBase(xenrt.TestCase):
    """Base class for V6 grace license testcases"""
    EDITION = "enterprise"
    LICENSE = "valid-enterprise"
    FEATURE = "CXS_ENT_CCS"

    def prepare(self, arglist=None):
        guest = self.getGuest("LicenseServer")
        if not guest.windows:
            # We need the Windows one as it has to stay on the same port over
            # a restart
            raise xenrt.XRTFailure("Windows license server required for grace "
                                   "license testing")
        self.v6 = guest.getV6LicenseServer()
        self.v6.removeAllLicenses()
        self.v6.addLicense(self.LICENSE)
        self.host = self.getDefaultHost()
        self.host.license(edition=self.EDITION, v6server=self.v6)

        self.guest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.guest.shutdown()

    def run(self, arglist=None):
        raise xenrt.XRTError("Unimplemented")

    def checkGrace(self, periodMins=30*24*60, type="regular"):
        """Check we're using a grace license"""
        ld = self.host.getLicenseDetails()
        if not ld.has_key('grace') or ld['grace'] != "%s grace" % (type):
            raise xenrt.XRTFailure("Not using grace license when expected")
        untilExpiry = (xenrt.util.parseXapiTime(ld['expiry']) - xenrt.util.timenow()) / 60
        difference = periodMins - untilExpiry
        if abs(difference) > 3:
            raise xenrt.XRTFailure("License expiry not set correctly when "
                                   "using grace license",
                                   data="Expecting %d minutes, found "
                                        "%d (%s)" % (periodMins, untilExpiry, ld['expiry']))
        # Check we can start a VM
        xenrt.TEC().logverbose("Attempting to start VM")
        if self.guest.getState() == "UP":
            self.guest.shutdown()
        try:
            self.guest.start()
            self.guest.shutdown()
        except xenrt.XRTFailure, e:
            if re.search("expired", e.reason):
                raise xenrt.XRTFailure("License repoted as expired while in "
                                       "grace period when trying to start VM")
            raise e

    def checkNoLicense(self):
        """Check we have no license"""
        ld = self.host.getLicenseDetails()
        if ld.has_key('grace') and ld['grace'] != 'false' and ld['grace'] != 'no':
            raise xenrt.XRTFailure("Unexpectedly using grace license")
        if not xenrt.util.parseXapiTime(ld['expiry']) == 0:
            raise xenrt.XRTFailure("License expiry not set correctly when "
                                   "no license issued",
                                   data="Expecting 19700101T00:00:00Z, found "
                                        "%s" % (ld['expiry']))
        self.checkVMStartFails()

    def checkGraceExpired(self, type="regular"):
        """Check we have an expired grace license"""
        ld = self.host.getLicenseDetails()
        if not ld.has_key('grace') or ld['grace'] != "%s grace" % (type):
            raise xenrt.XRTFailure("Not using grace license when expected")

        # Check we can't start a VM
        self.checkVMStartFails()

    def checkVMStartFails(self):
        # Check we can't start a VM
        xenrt.TEC().logverbose("Attempting to start VM")
        if self.guest.getState() == "UP":
            self.guest.shutdown()
        try:
            self.guest.start()
            self.guest.shutdown()
        except xenrt.XRTFailure, e:
            if re.search("expired", e.reason):                
                xenrt.TEC().logverbose("Expected exception")
            else:
                raise e
        else:
            raise xenrt.XRTFailure("Allowed to start VM with no license")

    def checkLicensed(self):
        """Check we have a valid license"""
        ld = self.host.getLicenseDetails()
        if ld.has_key('grace') and ld['grace'] != 'false' and ld['grace'] != 'no':
            raise xenrt.XRTFailure("Unexpectedly using grace license")
        if xenrt.util.parseXapiTime(ld['expiry']) <= xenrt.util.timenow():
            raise xenrt.XRTFailure("License unexpectedly expired",
                                   data="Found expiry date in the past of %s" %
                                        (ld['expiry']))
        # Check we can start a VM
        xenrt.TEC().logverbose("Attempting to start VM")
        if self.guest.getState() == "UP":
            self.guest.shutdown()
        try:
            self.guest.start()
            self.guest.shutdown()
        except xenrt.XRTFailure, e:
            if re.search("expired", e.reason):
                raise xenrt.XRTFailure("License reported as expired while "
                                       "trying to start VM")
            raise e

class TC10172(_V6GraceBase):
    """Verify a grace license is issued when the license server is unreachable"""

    def run(self, arglist=None):
        # Block connections to the license server
        self.host.execdom0("iptables -I OUTPUT -d %s -j DROP" % (self.v6.place.getIP()))

        # Set the fist point for reducing the grace retry period from 1 hour to 5 minutes
        self.host.execdom0("touch /tmp/fist_reduce_grace_retry_period")

        # Restart xapi 
        self.host.restartToolstack()
        self.host.execdom0("xe event-wait class=host uuid=%s enabled=true" % self.host.getMyHostUUID())

        # Check we're using a grace license
        self.checkGrace()

        # Restart the license server so everything is checked back in
        self.v6.restart()
        # Unblock the license server, check the license gets checked out within
        # 5 minutes (so wait 6 to be safe)
        self.host.execdom0("iptables -D OUTPUT -d %s -j DROP" % (self.v6.place.getIP()))

        xenrt.TEC().logverbose("Waiting 6 minutes...")
        time.sleep(360)
        xenrt.TEC().logverbose("...done")

        # Check the license has been checked out
        feature = self.FEATURE
        if self.host.special['v6earlyrelease']:
            feature = feature.replace("CXS_","CXSTP_")
        usages = self.v6.getLicenseUsage(feature)
        if self.LICENSE.endswith("-xd"):
            if len(usages) != 0:
                raise xenrt.XRTFailure("When XenDesktop site license being "
                                       "used to license XenServer, XenDesktop "
                                       "license itself shouldn't be consumed.")
        else:
            if len(usages) == 0:
                raise xenrt.XRTFailure("License not checked out 5 minutes after "
                                       "connection to license server restored")
            elif len(usages) > 1:
                raise xenrt.XRTFailure("License checked out multiple times 5 "
                                       "minutes after connection to license server "
                                       "restored")
            
        # Check the host is licensed
        self.checkLicensed()

    def postRun(self):
        if self.host:
            self.host.execdom0("rm -f /tmp/fist_reduce_grace_retry_period || true")
            self.host.execdom0("iptables -F OUTPUT || true")


class TC11219(TC10172):
    """Verify a grace license is issued when the license server is
    unreachable"""
    EDITION = "enterprise-xd"
    LICENSE = "valid-enterprise-xd"
    FEATURE = "XDS_ENT_CCS"


class TC10173(_V6GraceBase):
    """Verify a grace license is not issued when license server has no license"""
    EDITION = "platinum"
    LICENSE = "valid-platinum"
    FEATURE = "CXS_PLT_CCS"

    def run(self,arglist=None):
        # Remove the license from the license server
        self.v6.removeLicense(self.LICENSE)

        # Restart xapi
        self.host.restartToolstack()
        self.host.execdom0("xe event-wait class=host uuid=%s enabled=true" % self.host.getMyHostUUID())

        # Check we don't have a license
        self.checkNoLicense()

        # Add the license to the license server
        self.v6.addLicense(self.LICENSE)

        # Restart xapi
        self.host.restartToolstack()
        self.host.execdom0("xe event-wait class=host uuid=%s enabled=true" % self.host.getMyHostUUID())

        # Check the license has been checked out
        feature = self.FEATURE
        if self.host.special['v6earlyrelease']:
            feature = feature.replace("CXS_","CXSTP_")
        usages = self.v6.getLicenseUsage(feature)
        if len(usages) == 0:
            raise xenrt.XRTFailure("License not checked out after license "
                                   "replaced on license server and xapi restarted")
        elif len(usages) > 1:
            raise xenrt.XRTFailure("License checked out multiple times after "
                                   "license replaced on license server and xapi "
                                   "restarted")

        # Check the host is licensed
        self.checkLicensed()

class TC10174(_V6GraceBase):
    """Check grace period expiry"""

    def run(self, arglist=None):
        # Set grace period FIST point (makes it 15mins instead of 30 days)
        self.host.execdom0("touch /tmp/fist_reduce_grace_period")

        # Block connections to the license server
        self.host.execdom0("iptables -I OUTPUT -d %s -j DROP" % (self.v6.place.getIP()))

        # Restart xapi
        self.host.restartToolstack()
        self.host.execdom0("xe event-wait class=host uuid=%s enabled=true" % self.host.getMyHostUUID())

        # Check we're using a grace license
        self.checkGrace(15)        

        # Wait 16 minutes
        xenrt.TEC().logverbose("Waiting 16 minutes for grace period to expire...")
        time.sleep(960)
        xenrt.TEC().logverbose("...done")

        # Check we have an expired license
        self.checkGraceExpired()

        # Restart xapi and check we have no license
        # Need to cheat here and tweak the host clock
        self.host.execdom0("service xapi stop")
        self.host.execdom0("service v6d stop")
        self.host.execdom0("service ntpd stop")
        # Advance clock to 30 days and 5 minutes past current time
        newtime = time.gmtime(time.time() + (30 * 24 * 3600) + 300)
        self.host.execdom0("date -u %s" % (time.strftime("%m%d%H%M%Y", newtime)))
        self.host.execdom0("service v6d start")
        xenrt.sleep(30)
        self.host.startXapi()
        xenrt.sleep(30)
        self.host.execdom0("xe event-wait class=host uuid=%s enabled=true" % self.host.getMyHostUUID())
        self.checkNoLicense()

    def postRun(self):
        if self.host:
            self.host.execdom0("ntpdate `grep -e '^server ' /etc/ntp.conf | sed q | sed 's/server //'` || true")
            self.host.execdom0("service ntpd start || true")
            self.host.execdom0("iptables -F OUTPUT || true")
            self.host.execdom0("rm -f /tmp/fist_reduce_grace_period || true")
            self.host.restartToolstack()
            self.host.execdom0("service v6d stop")
            self.host.execdom0("rm -fr /var/xapi/lpe-cache || true")
            self.host.execdom0("service v6d start")

class TC10175(_V6GraceBase):
    """Check a grace license is issued when the license server returns garbage"""

    def run(self, arglist=None):
        # Copy the garbage script on to the license server
        if not self.v6.place.xmlrpcFileExists("c:\\returngarbage.py"):
            self.v6.place.xmlrpcSendFile("%s/utils/returngarbage.py" %
                                      (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")),
                                      "c:\\returngarbage.py")

        # Stop the license server
        self.v6.stop()

        # Set up the garbage server on the same port
        ref = self.v6.place.xmlrpcStart("c:\\returngarbage.py %d" % (self.v6.getPort()))
        self.garbagePID = self.v6.place.xmlrpcGetPID(ref)

        # Set the fist point for reducing the grace retry period from 1 hour to 5 minutes
        self.host.execdom0("touch /tmp/fist_reduce_grace_retry_period")

        # Now restart Xapi
        self.host.restartToolstack()
        self.host.execdom0("xe event-wait class=host uuid=%s enabled=true" % self.host.getMyHostUUID())

        # Check we're using a grace license
        self.checkGrace()

        # Stop the garbage server (by rebooting the VM)
        self.v6.place.reboot()

        # Start the V6 server again (stop first just in case it auto-starteD)
        try:
            self.v6.stop()
        except:
            pass
        self.v6.start()

        # To be safe, changed to wait for 6 minutes instead of 5 minutes
        xenrt.TEC().logverbose("Waiting 6 minutes...")
        time.sleep(360)
        xenrt.TEC().logverbose("...done")

        # Check the license has been checked out
        feature = self.FEATURE
        if self.host.special['v6earlyrelease']:
            feature = feature.replace("CXS_","CXSTP_")
        usages = self.v6.getLicenseUsage(feature)
        if len(usages) == 0:
            raise xenrt.XRTFailure("License not checked out 5 minutes after "
                                   "connection to license server restored")
        elif len(usages) > 1:
            raise xenrt.XRTFailure("License checked out multiple times 5 "
                                   "minutes after connection to license server "
                                   "restored")

        # Check the host is licensed
        self.checkLicensed()

    def postRun(self):
        if self.host:
            self.host.execdom0("rm -f /tmp/fist_reduce_grace_retry_period || true")
        self.v6.place.reboot()

class TC10554(_V6Transition):
    """Verify a V6 license is checked back in when changing license server"""
    FROM = "enterprise"
    TO = "platinum"
    TWOSERVERS = True

class TC10755(xenrt.TestCase):
    """Verify an alert is generated when we fail to checkout a license"""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        # Give it an enterprise license using the test daemon
        self.host.license()
        self.startAlerts = self.host.minimalList("message-list")

    def run(self, arglist=None):
        # Switch back to the real v6 daemon
        self.host.execdom0("service v6d stop")
        self.host.execdom0("mv /opt/xensource/libexec/v6d.orig /opt/xensource/libexec/v6d")
        self.host.execdom0("service v6d start")

        # Try and apply edition
        cli = self.host.getCLIInstance()
        try:
            cli.execute("host-apply-edition", "edition=enterprise host-uuid=%s" % (self.host.getMyHostUUID()))
        except:
            # Expected failure
            pass

        newAlerts = self.host.minimalList("message-list")
        if (len(newAlerts) - len(self.startAlerts)) > 1:
            cli.execute("message-list") # Done to add info to logs
            raise xenrt.XRTError("Multiple new alerts generated")
        elif len(newAlerts) == len(self.startAlerts):
            raise xenrt.XRTFailure("No alert generated after checkout failure")
        elif len(newAlerts) < len(self.startAlerts):
            raise xenrt.XRTError("Alerts disappeared after checkout failure")

        for a in newAlerts:
            if a not in self.startAlerts:
                errs = {}
                # Check the various fields
                name = self.host.genParamGet("message", a, "name")
                if name != "LICENSE_SERVER_UNREACHABLE":
                    errs['name'] = "'%s' not 'LICENSE_SERVER_UNREACHABLE'" % (name)
                priority = self.host.genParamGet("message", a, "priority")
                version = xenrt.TEC().lookup("PRODUCT_VERSION")
                if version == "Dundee":
                    if priority != "2":
                        errs['priority'] = "'%s' not '2'" % (priority)
                else:
                    if priority != "1":
                        errs['priority'] = "'%s' not '1'" % (priority)
                alertClass = self.host.genParamGet("message", a, "class")
                if alertClass != "Host":
                    errs['class'] = "'%s' not 'Host'" % (alertClass)
                uuid = self.host.genParamGet("message", a, "obj-uuid")
                if uuid != self.host.getMyHostUUID():
                    errs['obj-uuid'] = "'%s' not '%s'" % (uuid, self.host.getMyHostUUID())
                body = self.host.genParamGet("message", a, "body")            
                expectedBody = "The license could not be checked out, because the license server could not be reached at the given address/port. Please check the connection details, and verify that the license server is running."
                if body.strip() != expectedBody.strip():
                    xenrt.TEC().logverbose("Expecting body %s" % (expectedBody))
                    errs['body'] = "incorrect"

                if len(errs) > 0:
                    raise xenrt.XRTFailure("Generated alert has incorrect fields: %s" %
                                           (string.join(errs.keys(), ", ")),
                                           data=str(errs))

    def postRun(self):
        if self.host:
            try:
                # Try and relicense it with the test daemon
                self.host.license()
            except:
                pass

class TC10848(xenrt.TestCase):
    """Verify early release licenses do not license the product"""
    EXPECT_FAIL = True

    def prepare(self, arglist=None):
        guest = self.getGuest("LicenseServer")
        self.v6 = guest.getV6LicenseServer(useEarlyRelease=True)        
        self.v6.removeAllLicenses()
        # In case this license server was used previously
        self.v6.changeLicenseMode(True)
        self.v6.addLicense("valid-enterprise")
        self.host = self.getDefaultHost()

    def run(self, arglist=None):
        # Try and apply an early release license and check it works
        try:
            self.host.license(edition="enterprise", v6server=self.v6)
        except:
            if not self.EXPECT_FAIL:
                raise xenrt.XRTFailure("Unexpectedly unable to apply early release license")
        else:
            if self.EXPECT_FAIL:
                raise xenrt.XRTFailure("Unexpectedly able to apply early release license")

    def postRun(self):
        if self.v6:
            self.v6.changeLicenseMode(None)

class TC10849(TC10848):
    """Verify early release licenses do license the product"""
    EXPECT_FAIL = False


class TC11218(xenrt.TestCase):

    XD_LICENSE_NAME = "valid-enterprise-xd"
    
    def prepare(self, arglist=None):

        self.host = self.getDefaultHost()
        guest = self.getGuest("LicenseServer")
        self.v6 = guest.getV6LicenseServer()
        self.v6.removeAllLicenses()

    def transition(self, edition_from, edition_to):
        licinfo = self.host.getLicenseDetails()
        if licinfo['edition'] != edition_from:
            raise xenrt.XRTException("Expected pre-edition %s, got %s"
                                     % (edition_from, licinfo['edition']))
        self.host.license(edition=edition_to,
                          v6server=self.v6)
        licinfo = self.host.getLicenseDetails()
        if licinfo['edition'] != edition_to:
            raise xenrt.XRTException("Expected post-edition %s, got %s"
                                     % (edition_to, licinfo['edition']))
        xenrt.TEC().logverbose("Transition from %s edition to %s edition "
                              "succeeded." % (edition_from, edition_to))

    def run(self, arglist=None):

        self.v6.removeAllLicenses()
        self.host.license(edition="free")
        self.v6.addLicense("valid-advanced")
        self.v6.addLicense(self.XD_LICENSE_NAME)
        self.v6.addLicense("valid-enterprise")
        self.v6.addLicense("valid-platinum")
        
        self.transition("free", "enterprise-xd")
        self.transition("enterprise-xd", "platinum")
        self.transition("platinum", "enterprise-xd")
        self.transition("enterprise-xd", "enterprise")
        self.transition("enterprise", "enterprise-xd")
        self.transition("enterprise-xd", "advanced")
        self.transition("advanced", "enterprise-xd")
        self.transition("enterprise-xd", "free")

        self.v6.removeAllLicenses()
        
class TC15193(TC11218):
    """Test that Kaviza licenses work"""
    XD_LICENSE_NAME = "valid-enterprise-xd-kaviza"
    
#Below Testcase is invlaid as per comments in CA-108916
class TC20922(xenrt.TestCase):
    """Test relicensing host with an invalid license server address (HFX-927)"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.cli = self.host.getCLIInstance()

        # Install a license server

        self.licenseGuest = self.host.installLicenseServerGuest()
        self.licenseServer = self.licenseGuest.getV6LicenseServer()
        self.licenseServer.addLicense("valid-persocket")
        # License the host against a valid license server
        self.host.license(sku="per-socket", v6server=self.licenseServer)
        if len(self.licenseServer.getLicenseUsage("CXS_STD_CCS")) != 1:
            raise xenrt.XRTError("License not in use on license server after applying license")

    def run(self, arglist):
        try:
            # License the host against an invalid license server - we expect this to throw an error as the license server is unreachable
            self.cli.execute("host-apply-edition", "edition=per-socket license-server-address=127.0.0.1 license-server-port=27000")
            raise xenrt.XRTError("Applying edition with localhost license server succeeeded")
        except:
            pass

        # But it should either
        # a. Become unlicensed (or go into grace period could be acceptable), or
        # b. Fail to move to the new server, and therefore keep a license checked out on the license server

        licensesInUse = len(self.licenseServer.getLicenseUsage("CXS_STD_CCS"))
        hostLicense = self.host.getLicenseDetails()

        hostLicensed = False
        if hostLicense['sku_type'] == "per-socket" and hostLicense['grace'] == "no":
            hostLicensed = True

        if hostLicensed and licensesInUse == 0:
            raise xenrt.XRTFailure("Host is licensed but no licenses are in use on license server")
            
