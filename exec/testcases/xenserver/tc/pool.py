#
# XenRT: Test harness for Xen and the XenServer product family
#
# Pool operations testcases
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy, os.path
import xenrt, xenrt.lib.xenserver

class TC7302(xenrt.TestCase):
    """Large scale parallel domain reboots (PVS scenario)"""

    def __init__(self, tcid="TC7302"):
        xenrt.TestCase.__init__(self, tcid)

    def run(self, arglist=None):
        memory = 16
        iso = "w2k3eesp2.iso"
        numclones = 250
        loops = int(xenrt.TEC().lookup("TC7302_ITERATIONS", 100))

        pool = xenrt.TEC().registry.poolGet("RESOURCE_POOL_0")
        hosts = pool.master.minimalList("host-list", "name-label")
        objects = [ xenrt.TEC().registry.hostGet(x) for x in \
                    xenrt.TEC().registry.hostList() ]
        hosts = [ x for x in objects if x.getMyHostName() in hosts ]
        for host in hosts:
            self.getLogsFrom(host)
        watchdogcount = [ int(h.execdom0("cat /var/log/messages | "
                                         "grep -c watchdog | "
                                         "cat")) for h in hosts ]
        xapirestartcount = [ int(h.execdom0("cat /var/log/messages | "
                                            "grep xapi | "
                                            "grep -c starting | "
                                            "cat")) for h in hosts ]

        # Create initial guest.
        g = pool.master.guestFactory()(xenrt.randomGuestName(), None)
        g.host = pool.master
        g.createHVMGuest([])
        g.changeCD(iso)
        g.memset(memory)
        g.createVIF(bridge=pool.master.getPrimaryBridge())
        self._guestsToUninstall.append(g)

        # Create and start clones.
        cli = pool.getCLIInstance()
        clones = []

        for i in range(numclones):
            c = g.cloneVM()
            c.host = hosts[i%len(hosts)]
            clones.append(c.getUUID())
            cli.execute("vm-start uuid=%s on=%s" % (c.getUUID(), 
                                                    c.host.getMyHostName()))
            self._guestsToUninstall.append(c)

        for i in range(loops):
            xenrt.TEC().logverbose("Starting iteration %s." % (i))

            # Wait for load average to drop below 1.
            deadline = xenrt.timenow() + 7200
            while False in [ self.isIdle(x) for x in hosts ]:
                if xenrt.timenow() > deadline:
                    raise xenrt.XRTFailure("Timed out waiting for hosts to idle")
                time.sleep(10)

            # Execute reboot command. 
            commands = []
            commands.append("for i in $(list_domains | "
                                       "cut -d '|' -f 1 | "
                                       "grep -v id | "
                                       "grep -v 0 | "
                                       "sed -e 's/\s//g') "
                            "do")
            commands.append("/opt/xensource/debug/xenops hard_shutdown_domain -domid $i -reboot;")
            commands.append("done")

            for h in hosts:
                self.startAsync(h, commands)

            # Wait for load average to drop below 1.
            deadline = xenrt.timenow() + 7200
            while False in [ self.isIdle(x) for x in hosts ]:
                if xenrt.timenow() > deadline:
                    raise xenrt.XRTFailure("Timed out waiting for hosts to idle")
                time.sleep(10) 

            # Check xapi VM state. 
            for c in clones:
                if not pool.master.genParamGet("vm", c, "power-state") == "running":
                    raise xenrt.XRTFailure("Not all VMs are marked as running by xapi.")
        
            # Check list_domains VM state.
            for h in hosts:
                domlist = h.listDomains()
                slist = [ domlist[x][3] for x in domlist.keys() if x in clones ]
                running = xenrt.objects.GenericHost.STATE_RUNNING
                blocked = xenrt.objects.GenericHost.STATE_BLOCKED
                # Unknown really means not blocked, running, pasued etc..
                # i.e. not currently scheduled
                unknown = xenrt.objects.GenericHost.STATE_UNKNOWN
                if False in map(lambda x:x == running or x == blocked or x == unknown, slist):
                    raise xenrt.XRTFailure("Not all VMs are in state running or blocked.")

            newwatchdogcount = [ int(h.execdom0("cat /var/log/messages | "
                                                "grep -c watchdog | "
                                                "cat")) for h in hosts ]
            newxapirestartcount = [ int(h.execdom0("cat /var/log/messages | "
                                                   "grep xapi | "
                                                   "grep -c starting | "
                                                   "cat")) for h in hosts ]

            if not newwatchdogcount == watchdogcount:
                xenrt.TEC().warning("Possible watchdog activity during loop.")
            if not newxapirestartcount == xapirestartcount:
                xenrt.TEC().warning("Possible xapi restart during loop.")
        
    def isIdle(self, host):
        data = host.execdom0("uptime")
        r = ".* load average: (?P<one>[0-9\.]+)"
        m = re.search(r, data)
        if float(m.group("one")) < 1.0:
            return True
        else:
            return False

class _PoolTest(xenrt.TestCase):

    def createSharedSR(self, host, name):
        self.nfs = xenrt.ExternalNFSShare()
        nfs = self.nfs.getMount()
        r = re.search(r"([0-9\.]+):(\S+)", nfs)
        if not r:
            raise xenrt.XRTError("Unable to parse NFS paths %s" % (nfs))
        sr = xenrt.lib.xenserver.NFSStorageRepository(host, name)
        sr.create(r.group(1), r.group(2))
        self.nfssr = sr
        sr.check()
        host.addSR(sr)
        return sr

    def postRun2(self):
        try:
            if self.nfssr:
                self.nfssr.remove()
                self.nfs.release()
        except:
            pass

    def checkEmergency(self,pool):
        if isinstance(pool.master, xenrt.lib.xenserver.Host):
            return True
        else:
            return pool.checkEmergency()

class TC7243(_PoolTest):
    """A host containing shared storage cannot be joined to a pool"""
    
    def prepare(self, arglist=None):
        # Prepare two independent hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)

        # Add an NFS SR to the second host
        self.createSharedSR(self.host1, "TC7243")

    def run(self, arglist=None):
        # Try to join the host with the shared SR as a slave
        failure = None
        try:
            self.pool.addHost(self.host1)
            failure = "Host with shared storage was successfully joined " \
                "to a pool"
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose("Got failure: %s" % (str(e)))
            if not re.search("The host joining the pool cannot contain "
                             "any shared storage", e.data):
                raise xenrt.XRTFailure("Unexpected response to trying to "
                                       "join a slave with shared storage "
                                       "to a pool: %s" % (e.data))
        if failure:
            raise xenrt.XRTFailure(failure)

class TC7244(_PoolTest):
    """A host with running VMs cannot be joined to a pool"""

    def prepare(self, arglist=None):
        # Prepare two independent hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.guest = self.host1.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        if self.guest.getState() != "UP":
            self.guest.start()

    def run(self, arglist=None):
        # Try to join the host with the running VM as a slave
        failure = None
        try:
            self.pool.addHost(self.host1)
            failure = "Host with a running VM was successfully joined " \
                "to a pool"
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose("Got failure: %s" % (str(e)))
            if not re.search("The host joining the pool cannot have any "
                             "running (or suspended |)VMs", e.data):
                raise xenrt.XRTFailure("Unexpected response to trying to "
                                       "join a slave with a running VM "
                                       "to a pool: %s" % (e.data))
        if failure:
            raise xenrt.XRTFailure(failure)

class TC7245(_PoolTest):
    """A host with suspended VMs cannot be joined to a pool"""

    def prepare(self, arglist=None):
        # Prepare two independent hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.guest = self.host1.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        if self.guest.getState() != "UP":
            self.guest.start()
        self.guest.suspend()

    def run(self, arglist=None):
        # Try to join the host with the running VM as a slave
        failure = None
        try:
            self.pool.addHost(self.host1)
            failure = "Host with a suspended VM was successfully joined " \
                "to a pool"
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose("Got failure: %s" % (str(e)))
            if not re.search("The host joining the pool cannot have any "
                             "running or suspended VMs", e.data):
                raise xenrt.XRTFailure("Unexpected response to trying to "
                                       "join a slave with a suspended VM "
                                       "to a pool: %s" % (e.data))
        if failure:
            raise xenrt.XRTFailure(failure)

class TC9364(_PoolTest):
    """A host with suspended VMs can be joined to a pool"""

    def prepare(self, arglist=None):
        # Prepare two independent hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.guest = self.host1.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        if self.guest.getState() != "UP":
            self.guest.start()
        self.guest.suspend()

    def run(self, arglist=None):
        # Try to join the host with the suspended VM as a slave
        failure = None
        self.pool.addHost(self.host1)
        self.guest.resume()

class TC7246(_PoolTest):
    """A host already in a pool cannot be joined to another pool"""

    def prepare(self, arglist=None):
        # Prepare two independent hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host2 = self.getHost("RESOURCE_HOST_2")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()
        self.host2.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.pool.addHost(self.host1, force=True)
        self.pool2 = xenrt.lib.xenserver.poolFactory(self.host2.productVersion)(self.host2)

    def run(self, arglist=None):
        # Try to join the slave from the first pool to the second pool
        failure = None
        try:
            self.pool2.addHost(self.host1)
            failure = "Slave already in a pool was successfully joined " \
                "to a new pool"
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose("Got failure: %s" % (str(e)))
            if not re.search("You cannot make regular API calls directly "
                             "on a slave", e.data):
                raise xenrt.XRTFailure("Unexpected response to trying to "
                                       "join a slave already in a pool "
                                       "to a new pool: %s" % (e.data))
        if failure:
            raise xenrt.XRTFailure(failure)

        # Try to join the master from the first pool to the second pool
        failure = None
        try:
            self.pool2.addHost(self.host0, force=True)
            failure = "Master already in a pool was successfully joined " \
                "to a new pool"
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose("Got failure: %s" % (str(e)))
            if not re.search("The host joining the pool cannot already "
                             "be a master of another pool", e.data):
                raise xenrt.XRTFailure("Unexpected response to trying to "
                                       "join a master already in a pool "
                                       "to a new pool: %s" % (e.data))
        if failure:
            raise xenrt.XRTFailure(failure)

class TC7247(_PoolTest):
    """Joining a host to a pool"""

    def prepare(self, arglist=None):
        # Prepare two independent hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)

        # Add an NFS SR to the master host
        self.mysr = self.createSharedSR(self.host0, "TC7247")

    def run(self, arglist=None):
        # Try to join a clean host as a slave
        self.pool.addHost(self.host1)
        self.pool.check()
        self.mysr.check()

class TC7248(_PoolTest):
    """A host cannot be joined to a pool using an incorrect username or
    password"""

    def prepare(self, arglist=None):
        # Prepare two independent hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)

    def run(self, arglist=None):
        cli = self.host1.getCLIInstance()
        origpassword = cli.password
        origusername = cli.username
        try:
            # Try to join the host with an incorrect username
            failure = None
            try:
                cli.username = "bogus"
                self.pool.addHost(self.host1)
                failure = "Host was successfully joined to a pool using an " \
                    "incorrect username"
            except xenrt.XRTFailure, e:
                xenrt.TEC().logverbose("Got failure: %s" % (str(e)))
                if not re.search("Authentication failed", e.data):
                    raise xenrt.XRTFailure("Unexpected response to trying to "
                                           "join a host to a pool using an "
                                           "incorrect username: %s" % (e.data))
            if failure:
                raise xenrt.XRTFailure(failure)

            # Try to join the host with an incorrect password
            failure = None
            try:
                cli.username = origusername
                cli.password = "bogus"
                self.pool.addHost(self.host1)
                failure = "Host was successfully joined to a pool using an " \
                    "incorrect password"
            except xenrt.XRTFailure, e:
                xenrt.TEC().logverbose("Got failure: %s" % (str(e)))
                if not re.search("Authentication failed", e.data):
                    raise xenrt.XRTFailure("Unexpected response to trying to "
                                           "join a host to a pool using an "
                                           "incorrect password: %s" % (e.data))
            if failure:
                raise xenrt.XRTFailure(failure)
        finally:
            cli.password = origpassword
            cli.username = origusername

class TC7249(_PoolTest):
    """Shared storage added to a pool should be visible on all hosts"""

    def prepare(self, arglist=None):
        # Prepare two independent hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()
        
        # Create the pool
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.pool.addHost(self.host1)
        self.pool.check()

    def run(self, arglist=None):
        # Add an NFS SR to the pool and verify all hosts see it
        self.mysr = self.createSharedSR(self.host0, "TC7249")
        self.mysr.check()
        self.pool.check()

class TC7250(_PoolTest):
    """Observation of pool default-SR"""

    def prepare(self, arglist=None):
        # Prepare two independent hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()

        # Create the pool
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.pool.addHost(self.host1)
        self.pool.check()

        # Add a shared SR
        self.mysr = self.createSharedSR(self.host0, "TC7250")
        self.mysr.check()

    def run(self, arglist=None):
        # Set the pool default SR to be the shared one
        self.pool.setPoolParam("default-SR", self.mysr.uuid)

        # Install a VM without specifying an SR
        cli = self.pool.getCLIInstance()
        template = self.host0.getTemplate("w2k3eesp1")
        name = xenrt.randomGuestName()
        uuid = None
        try:
            uuid = cli.execute("vm-install", "new-name-label=%s template=\"%s\"" %
                               (name, template), strip=True)
        
            # Check which SR the VDI(s) was created on
            vdis = self.host0.minimalList("vbd-list",
                                          "vdi-uuid",
                                          "vm-uuid=%s" % (uuid))
            for vdi in vdis:
                sruuid = self.host0.genParamGet("vdi", vdi, "sr-uuid")
                if sruuid != self.mysr.uuid: 
                    xenrt.TEC().logverbose("VM:%s VDI:%s SR:%s" %
                                           (uuid, vdi, sruuid))
                    raise xenrt.XRTFailure("A VDI was created on a SR other "
                                           "than the pool default")
        finally:
            try:
                if uuid:
                    cli.execute("vm-uninstall", "uuid=%s --force" % (uuid))
            except:
                pass

class TC7252(_PoolTest):
    """Automatic start of VMs on pool hosts"""

    def prepare(self, arglist=None):
        # Prepare two independent hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()

        # Create the pool
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.pool.addHost(self.host1)
        self.pool.check()

        # Add a shared SR
        self.mysr = self.createSharedSR(self.host0, "TC7252")
        self.mysr.check()
        self.pool.setPoolParam("default-SR", self.mysr.uuid)

        # Install VMs to the shared SR
        self.guests = []
        g = self.host0.createGenericLinuxGuest()
        self.uninstallOnCleanup(g)
        self.guests.append(g)
        g.shutdown()
        g = self.host0.createGenericLinuxGuest()
        self.uninstallOnCleanup(g)
        self.guests.append(g)
        g.shutdown()
        g = self.host0.createGenericLinuxGuest()
        self.uninstallOnCleanup(g)
        self.guests.append(g)
        g.shutdown()
        g = self.host0.createGenericLinuxGuest()
        self.uninstallOnCleanup(g)
        self.guests.append(g)
        g.shutdown()

    def run(self, arglist=None):
        cli = self.pool.getCLIInstance()

        # Ensure the VMs have no affinity set
        for g in self.guests:
            affinity = g.paramGet("affinity")
            if affinity != "<not in database>":
                raise xenrt.XRTError("VM affinity is set") 

        # Perform a vm-start of the four VMs
        for g in self.guests:
            cli.execute("vm-start", "uuid=%s" % (g.getUUID()))

        # Make sure the VMs started on both hosts and update the harness
        # metadata so we can check the reality
        hosts = []
        for g in self.guests:
            hostuuid = g.paramGet("resident-on")
            if not hostuuid in hosts:
                hosts.append(hostuuid)
                if hostuuid == self.host0.getMyHostUUID():
                    g.host = self.host0
                elif hostuuid == self.host1.getMyHostUUID():
                    g.host = self.host1
                else:
                    raise xenrt.XRTError("Unknown host UUID")
                g.check()

        if len(hosts) < 2:
            raise xenrt.XRTFailure("All VMs were started on the same host")

class TC7253(_PoolTest):
    """VM started with "on" starts on the correct host"""

    def prepare(self, arglist=None):
        # Prepare two independent hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()

        # Create the pool
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.pool.addHost(self.host1)
        self.pool.check()

        # Add a shared SR
        self.mysr = self.createSharedSR(self.host0, "TC7253")
        self.mysr.check()
        self.pool.setPoolParam("default-SR", self.mysr.uuid)

        # Install VMs to the shared SR
        self.guest = self.host0.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.guest.shutdown()

    def run(self, arglist=None):
        cli = self.pool.getCLIInstance()

        # Ensure the VM has no affinity set
        affinity = self.guest.paramGet("affinity")
        if affinity != "<not in database>":
            raise xenrt.XRTError("VM affinity is set")

        # Perform a vm-start of the VM on the master
        self.guest.host = self.host0
        self.guest.start()
        self.guest.check()
        self.guest.shutdown()

        # Perform a vm-start of the VM on the slave
        self.guest.host = self.host1
        self.guest.start()
        self.guest.check()
        self.guest.shutdown()

class TC7254(_PoolTest):
    """VM start using host affinity"""

    def prepare(self, arglist=None):
        # Prepare two independent hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()

        # Create the pool
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.pool.addHost(self.host1)
        self.pool.check()

        # Add a shared SR
        self.mysr = self.createSharedSR(self.host0, "TC7254")
        self.mysr.check()
        self.pool.setPoolParam("default-SR", self.mysr.uuid)

        # Install a VM to the shared SR
        self.guest = self.host0.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.guest.shutdown()

    def run(self, arglist=None):
        # Set the VM affinity parameter to the master
        self.guest.paramSet("affinity",self.host0.getMyHostUUID())

        # Start the VM
        self.guest.start(specifyOn=False)
        # Check the VM is running on the master
        self.guest.check()
        self.guest.shutdown()

        # Set the VM affinity parameter to the slave
        self.guest.paramSet("affinity",self.host1.getMyHostUUID())

        # Start the VM
        self.guest.host = self.host1
        self.guest.start(specifyOn=False)
        # Check the VM is running on the slave
        self.guest.check()
        self.guest.shutdown()

class TC7255(_PoolTest):
    """VM started on non-affine host when affine host not available"""

    def prepare(self, arglist=None):
        # Prepare two independent hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()

        # Create the pool
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.pool.addHost(self.host1)
        self.pool.check()

        # Add a shared SR
        self.mysr = self.createSharedSR(self.host0, "TC7255")
        self.mysr.check()
        self.pool.setPoolParam("default-SR", self.mysr.uuid)

        # Install VMs to the shared SR and set affinity to the master
        self.guest1 = self.host0.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest1)
        self.guest1.shutdown()
        self.guest1.paramSet("affinity",self.host0.getMyHostUUID())
        self.guest2 = self.host0.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest2)
        self.guest2.shutdown()
        self.guest2.paramSet("affinity",self.host0.getMyHostUUID())
        self.guest2.memset(512)

    def run(self, arglist=None):
        # Wait 75 seconds to let the free memory total refresh itself
        time.sleep(75)
        
        cli = self.pool.getCLIInstance()

        # Set the memory of the first VM to be all available free memory on the master
        self.guest1.memset(self.host0.maximumMemoryForVM(self.guest1))
        # Start the first VM
        self.guest1.host = self.host0
        cli.execute("vm-start","uuid=%s" % (self.guest1.uuid))
        # Verify the first VM starts on the master
        self.guest1.check()

        # Start the second VM
        self.guest2.host = self.host0
        cli.execute("vm-start","uuid=%s" % (self.guest2.uuid))
        # Verify the second VM starts on the slave 
        self.guest2.host = self.host1
        self.guest2.check()

class TC7256(_PoolTest):
    """Pool eject removes a host and leaves it in a freshly installed state"""

    def prepare(self, arglist=None):
        # Create a pool of two hosts using shared storage
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.pool.addHost(self.host1)
        self.pool.check()
        self.mysr = self.createSharedSR(self.host0, "TC7256")
        self.mysr.check()
        self.pool.setPoolParam("default-SR", self.mysr.uuid)

        # Install a VM "A" on local storage of the master
        self.guestA = self.host0.createGenericLinuxGuest(sr=self.host0.getLocalSR())
        self.uninstallOnCleanup(self.guestA)
        self.guestA.shutdown()
        # Install a VM "B" on local storage of the slave
        self.guestB = self.host1.createGenericLinuxGuest(sr=self.host1.getLocalSR())
        self.uninstallOnCleanup(self.guestB)
        self.guestB.shutdown()
        # Install a VM "C" on shared storage 
        self.guestC = self.host0.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guestC)
        self.guestC.shutdown()

    def run(self, arglist=None):
        # Verify all three VMs can start.
        self.guestA.start()
        self.guestB.start()
        self.guestC.start()
        # Shutdown all three VMs
        self.guestA.shutdown()
        self.guestB.shutdown()
        self.guestC.shutdown()

        # Eject the slave from the pool
        self.pool.eject(self.host1)
 
        # Verify that VMs A and C can start
        self.guestA.start()
        self.guestC.start()

        # Verify that VM B cannot start
        started = False
        try:
            self.guestB.start()
            started = True
        except:
            pass
        if started:
            raise xenrt.XRTFailure("VM on local storage of ejected slave "
                                   "started successfully")

        # Verify the ejected host cannot see the shared storage
        srs = self.host1.getSRs()
        if self.mysr.uuid in srs:
            raise xenrt.XRTFailure("Ejected slave can still see shared storage")

        # Verify the ejected host is like a freshly installed host
        # including having no VMs and non-ISO/udev VDIs 
        vms = self.host1.listGuests()
        if len(vms) > 0:
            raise xenrt.XRTFailure("Found %u VMs on ejected slave" % (len(vms)))
        vdis = self.host1.minimalList("vdi-list","name-label")
        for vdi in vdis:
            if not (vdi.endswith(".iso") or
                    vdi.startswith("IDE ") or
                    vdi.startswith("SCSI ") or
                    vdi.startswith("USB ")):
                raise xenrt.XRTFailure("Found non-ISO VDI %s on ejected slave" % (vdi))

        # Verify that a VM can be installed to local storage on the ejected host
        # (CA-24064)
        localGuest = self.host1.createGenericLinuxGuest()
        self.uninstallOnCleanup(localGuest)
        localGuest.check()

class TC7257(_PoolTest):
    """Crashed pool member is detected"""

    def prepare(self, arglist=None):
        # Install a pool of two hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.pool.addHost(self.host1)
        self.pool.check()
        # Install a VM to local storage on the slave
        self.guest = self.host1.createGenericLinuxGuest(sr=self.host1.getLocalSR())
        self.uninstallOnCleanup(self.guest)
        self.guest.shutdown()

    def run(self, arglist=None):
        # Start the VM
        self.guest.start()

        # Simulate a slave crash by stopping the xapi service
        self.host1.execdom0("service xapi stop")
        # Wait 11 minutes (660 seconds)
        time.sleep(660)
        # Verify the master has listed the slave host as offline
        slaves = self.pool.getSlavesStatus()
        if slaves[self.host1.getMyHostUUID()] == "true":
            raise xenrt.XRTError("Master failed to notice slave offline after "
                                 "11 minutes")
         
        # Restart the xapi service on the slave
        self.host1.startXapi()
        # Wait 1 minute (should only take ~30 seconds)
        time.sleep(60)
        # Verify the master lists the slave host as online
        slaves = self.pool.getSlavesStatus()
        if slaves[self.host1.getMyHostUUID()] == "false":
            raise xenrt.XRTError("Slave not online after starting xapi")

        # Shutdown the VM
        self.guest.shutdown()

        # Simulate a slave crash by stopping the xapi service
        self.host1.execdom0("service xapi stop")
        # Wait 11 minutes (660 seconds)
        time.sleep(660)
        # Verify the master has listed the slave host as offline
        slaves = self.pool.getSlavesStatus()
        if slaves[self.host1.getMyHostUUID()] == "true":
            raise xenrt.XRTError("Master failed to notice slave offline after "
                                 "11 minutes")

        # Try to start the VM
        # Verify the VM cannot be started
        started = False
        try:
            self.guest.start()
            started = True
        except:
            pass
        if started:
            raise xenrt.XRTFailure("VM on local storage of offline host started"
                                   " successfully")

        # Restart the xapi service on the slave
        self.host1.startXapi()
        # Wait 1 minute
        time.sleep(60)
        # Verify the master lists the slave host as online
        slaves = self.pool.getSlavesStatus()
        if slaves[self.host1.getMyHostUUID()] == "false":
            raise xenrt.XRTError("Slave not online after starting xapi")

        # Try to start the VM
        # Verify the VM starts (may take a while for the local SR to plug, so
        # try 3 times waiting a minute between each)
        count = 1
        while True:
            try:
                self.guest.start()
                xenrt.TEC().logverbose("Guest started on attempt %u" % (count))
                break
            except xenrt.XRTFailure, e:
                if count == 3:
                    raise e
                count += 1
                time.sleep(60)

class TC7258(_PoolTest):
    """Crashed pool member can be forgotten"""

    def prepare(self, arglist=None):
        # Install a pool of two hosts with shared storage
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.pool.addHost(self.host1)
        self.pool.check()
        self.mysr = self.createSharedSR(self.host0, "TC7258")
        self.mysr.check()
        self.pool.setPoolParam("default-SR", self.mysr.uuid)

        # Install and start a VM on shared storage (start on slave)
        self.guest = self.host1.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.guest.shutdown()
        self.guest.host = self.host1
        self.guest.start()

    def run(self, arglist=None):
        # Simulate a slave crash by stopping the xapi service and destroying the running VM
        self.host1.execdom0("service xapi stop")
        self.host1.execdom0("xl destroy %s" % (self.guest.getDomid()))
        xenrt.sleep(5)
        # Verify the VM has stopped
        doms = self.host1.listDomains()
        if doms.has_key(self.guest.uuid):
            raise xenrt.XRTError("VM did not stop after being destroyed")
        # Wait 11 minutes (660 seconds)
        xenrt.sleep(660)
        # Verify the master has listed the slave host as offline
        slaves = self.pool.getSlavesStatus()
        if slaves[self.host1.getMyHostUUID()] == "true":
            raise xenrt.XRTFailure("Master failed to notice slave offline after"
                                   " 11 minutes")

        # Verify the master still shows the VM was running
        ps = self.host0.parseListForParam("vm-list",
                                          self.guest.uuid,
                                          "power-state")
        if ps != "running":
            raise xenrt.XRTFailure("Master believes VM to have a power-state of"
                                   " %s (expecting running)" % (ps))

        # Perform vm-reset-powerstate to mark the VM was halted
        cli = self.pool.getCLIInstance()
        cli.execute("vm-reset-powerstate","uuid=%s --force" % (self.guest.uuid))

        # Perform host-forget to remove the dead slave
        self.pool.forget(self.host1)

        # Start the VM
        self.guest.host = self.host0
        self.guest.start()
        # Verify the VM starts on the master 
        doms = self.host0.listDomains()
        if not doms.has_key(self.guest.uuid):
            raise xenrt.XRTFailure("VM did not start on master")

class TC7259(_PoolTest):
    """Pool members detect master failure and recovery"""

    def prepare(self, arglist=None):
        # Install a pool of two hosts with shared storage
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.pool.addHost(self.host1)
        self.pool.check()
        self.mysr = self.createSharedSR(self.host0, "TC7259")
        self.mysr.check()
        self.pool.setPoolParam("default-SR", self.mysr.uuid)

        # Install and start a VM on shared storage (start on slave)
        self.guest = self.host1.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.guest.shutdown()
        self.guest.host = self.host1
        self.guest.start()

    def run(self, arglist=None):
        # Simulate master failure by stopping the xapi service
        self.host0.execdom0("service xapi stop")
        # Wait 120 seconds
        time.sleep(120)
        # Verify the slave is in emergency mode
        if not self.checkEmergency(self.pool):
            raise xenrt.XRTFailure("Slave not in emergency mode after 120 seconds")

        # Verify that the vm-list CLI command cannot be run on the slave
        vml = False
        try:
            cli = self.host1.getCLIInstance(local=True)
            cli.execute("vm-list")
            vml = True
        except:
            pass
        if vml:
            raise xenrt.XRTFailure("Able to run vm-list on a slave in "
                                   "emergency mode")

        # Verify the VM is running
        try:
            self.guest.execguest("true")
        except:
            raise xenrt.XRTFailure("Unable to contact VM running on slave after"
                                   " simulated master crash")

        # Restart the xapi service on the master
        self.host0.startXapi()
        # Wait 75 seconds
        time.sleep(75)
        # Verify the slave is not in emergency mode
        if self.pool.checkEmergency():
            raise xenrt.XRTFailure("Slave still in emergency mode 75 seconds "
                                   "after master was restarted")

        # Verify that the vm-list CLI command can be run on the master
        mastercli = self.host0.getCLIInstance()
        mastercli.execute("vm-list")

        # Verify the VM is running
        self.guest.check()

class TC7260(_PoolTest):
    """Transition a slave to master after master failure"""

    def prepare(self, arglist=None):
        # Install a pool of three hosts with shared storage
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host2 = self.getHost("RESOURCE_HOST_2")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()
        self.host2.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.pool.addHost(self.host1)
        self.pool.addHost(self.host2)
        self.pool.check()
        self.mysr = self.createSharedSR(self.host0, "TC7260")
        self.mysr.check()
        self.pool.setPoolParam("default-SR", self.mysr.uuid)

        # Install and start a VM on shared storage (start on a slave)
        self.guest = self.host1.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.guest.shutdown()
        self.guest.host = self.host1
        self.guest.start()

    def run(self, arglist=None):        
        # Simulate master failure by stopping the xapi service
        self.host0.execdom0("service xapi stop")
        # Wait 120 seconds
        time.sleep(120)
        # Verify the slaves are in emergency mode
        if not self.checkEmergency(self.pool):
            raise xenrt.XRTFailure("One or more slaves are not in emergency "
                                   "mode")

        # Verify the VM is running
        try:
            self.guest.execguest("true")
        except:
            raise xenrt.XRTFailure("Unable to contact VM running on slave after"
                                   " simulated master crash")

        # On one slave "A" perform pool-emergency-transition-to-master
        self.pool.setMaster(self.host1)
        # On slave A perform pool-recover-slaves
        self.pool.recoverSlaves()

        # Verify A is now the master and the other slave is part of the pool
        if self.pool.master != self.host1:
            raise xenrt.XRTFailure("Host 1 did not become the master")
        slaves = self.pool.listSlaves()
        if not self.host2.getName() in slaves:
            raise xenrt.XRTFailure("Host 2 is no longer a part of the pool")

        # Verify the VM is running
        try:
            self.guest.execguest("true")
        except:
            raise xenrt.XRTFailure("Unable to contact VM running on slave after"
                                   " pool-emergency-transition-to-master") 

        # Verify the pool default-SR is correct
        dsr = self.pool.getPoolParam("default-SR")
        if dsr != self.mysr.uuid:
            raise xenrt.XRTFailure("Pool default-sr now %s (expecting %s)" %
                                   (dsr,self.mysr.uuid))

class TC7261(_PoolTest):
    """Rejoining a previously failed master to a pool with a new master should fail"""

    def prepare(self, arglist=None):
        # Install a pool of two hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.pool.addHost(self.host1)
        self.pool.check()

    def run(self, arglist=None):
        self.host0.execdom0("service xapi stop")
        # Wait 120 seconds
        time.sleep(120)
        # Verify the slave is in emergency mode
        if not self.checkEmergency(self.pool):
            raise xenrt.XRTFailure("Slave not in emergency mode after 120 seconds")

        # On slave perform pool-emergency-transition-to-master
        self.pool.setMaster(self.host1)
        # On slave perform pool-recover-slaves
        self.pool.recoverSlaves()

        # Verify slave is now the master
        if self.pool.master != self.host1:
            raise xenrt.XRTFailure("Host 1 did not become the master")

        # Reboot the old master
        self.host0.reboot()

        # Try to join the old master to the pool
        # The join should fail
        success = False
        try:
            self.pool.addHost(self.host0)
            success = True
        except:
            pass
        if success:
            raise xenrt.XRTFailure("Able to join old master to pool")

class TC7262(_PoolTest):
    """Entire pool recovery from database backup"""

    def prepare(self, arglist=None):
        # Create a pool of two hosts using shared storage
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.pool.addHost(self.host1)
        self.pool.check()
        self.mysr = self.createSharedSR(self.host0, "TC7260")
        self.mysr.check()
        self.pool.setPoolParam("default-SR", self.mysr.uuid)

        # Install 4 VMs to shared storage
        self.guests = []
        for i in range(4):
            g = self.host0.createGenericLinuxGuest()
            self.uninstallOnCleanup(g)
            g.shutdown()
            self.guests.append(g)

    def run(self, arglist=None):
        # Verify all 4 VMs can start
        for g in self.guests:
            g.start()
        # Shutdown all 4 VMs
        for g in self.guests:
            g.shutdown()

        # Perform pool-dump-database and keep the backup
        dbdumpdir = xenrt.TEC().tempDir()
        dbdump = "%s/dbdump" % (dbdumpdir)
        self.pool.dump(dbdump)

        # Reinstall the hosts with a fresh installation
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()
        # On one host restore the pool backup using pool-restore-database
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.pool.restore(dbdump)
        self.host0.waitForEnabled(300, "Xapi startup after host reboot")
        # Verify the host (now master) can see the shared storage
        srs = self.host0.getSRs()
        if not self.mysr.uuid in srs:
            raise xenrt.XRTFailure("Shared Storage SR missing after "
                                   "pool-restore-database")
        # Verify the host has the VMs listed
        vms = self.host0.minimalList("vm-list")
        for g in self.guests:
            if not g.uuid in vms:
                raise xenrt.XRTFailure("Guest missing after "
                                       "pool-restore-database")

        # Join the second host to the pool
        self.pool.addHost(self.host1)
        # Start the 4 VMs
        for g in self.guests:
            g.start()
        # Verify the VMs are running 
        for g in self.guests:
            g.check()

class TC7822(_PoolTest):
    """Joining a host to a pool that has VLANs configured."""

    def prepare(self, arglist=None):

        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")

        vlans = self.host0.availableVLANs()
        if len(vlans) == 0:
            xenrt.TEC().skip("No VLANs defined for host")
            return
        self.vlan, self.subnet, self.netmask = vlans[0]

        # Prepare two independent hosts
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()

        # Create the pool (but don't add the slave yet)
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.pool.check()

        # Add a shared SR
        self.mysr = self.createSharedSR(self.host0, "TC7822")
        self.mysr.check()
        self.pool.setPoolParam("default-SR", self.mysr.uuid)

        # Create a VLAN on the host's primary interface
        self.nic = self.host0.getDefaultInterface()
        self.vbridge = self.host0.createNetwork()
        self.host0.createVLAN(self.vlan, self.vbridge, self.nic) 
        self.host0.checkVLAN(self.vlan, self.nic)

    def run(self, arglist=None):

        # Add the slave to the pool
        self.pool.addHost(self.host1)
        self.pool.check()

        # Install a VM using the VLAN network
        bridgename = self.host0.genParamGet("network", self.vbridge, "bridge")
        g = self.host0.createGenericLinuxGuest(bridge=bridgename)
        self.uninstallOnCleanup(g)
        
        # Check the VM
        g.check()
        g.checkHealth()
        if self.subnet and self.netmask:
            ip = g.getIP()
            if xenrt.isAddressInSubnet(ip, self.subnet, self.netmask):
                xenrt.TEC().comment("%s is in %s/%s" %
                                    (ip, self.subnet, self.netmask))
            else:
                xenrt.TEC().comment("%s is not in %s/%s" %
                                    (ip, self.subnet, self.netmask))
                raise xenrt.XRTFailure("VM IP address not from VLAN subnet")
        else:
            xenrt.TEC().comment("Skipping guest IP check")

        # Migrate to the other host and recheck
        g.migrateVM(self.host1, live="true")
        g.check()
        g.checkHealth()

class TC8604(_PoolTest):
    """Check that domain zero's memory target persists across pool join"""

    def checkmem(self, targetb, hostno):
        host = self.hosts[hostno]
        memtarget = float(host.genParamGet("vm",
                                           host.getMyDomain0UUID(),
                                           "memory-target"))
        memactual = float(host.genParamGet("vm",
                                           host.getMyDomain0UUID(),
                                           "memory-actual"))
        data = host.execdom0("cat /proc/meminfo")
        r = re.search(r"MemTotal:\s+(\d+)\s+kB", data)
        if not r:
            raise xenrt.XRTError("Could not parse /proc/meminfo for MemTotal")
        memtotal = float(r.group(1)) * 1024
        for x in [("memory-target", memtarget),
                  ("memory-actual", memactual),
                  ("/proc/meminfo:MemTotal", memtotal)]:
            desc, m = x
            delta = abs(targetb - m)
            error = 100.0 * delta / targetb
            if error > 5.0:
                raise xenrt.XRTFailure("%s is not as expected" % (desc),
                                       "Target %f bytes, is %f bytes" %
                                       (targetb, m))

    def prepare(self, arglist=None):
        # Prepare two independent hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.hosts = [self.host0, self.host1]

        # Find the current dom0 memory targets
        self.originals = [\
            int(self.host0.genParamGet("vm",
                                       self.host0.getMyDomain0UUID(),
                                       "memory-target")),
            int(self.host1.genParamGet("vm",
                                       self.host1.getMyDomain0UUID(),
                                       "memory-target"))]
        
        # Test by subtracting 50MB
        self.targets = [o - 50 * 1024 * 1024 for o in self.originals]

        # Set non-default dom0 memory targets on both hosts
        cli = self.host0.getCLIInstance()
        cli.execute("vm-memory-target-set",
                    "target=%u uuid=%s" % (self.targets[0],
                                           self.host0.getMyDomain0UUID()))
        cli.execute("vm-memory-target-wait",
                    "uuid=%s" % (self.host0.getMyDomain0UUID()))
        cli = self.host1.getCLIInstance()
        cli.execute("vm-memory-target-set",
                    "target=%u uuid=%s" % (self.targets[1],
                                           self.host1.getMyDomain0UUID()))
        cli.execute("vm-memory-target-wait",
                    "uuid=%s" % (self.host1.getMyDomain0UUID()))
        time.sleep(60)
        self.checkmem(float(self.targets[0]), 0)
        self.checkmem(float(self.targets[1]), 1)

        # Perform the pool join
        self.pool.addHost(self.host1)
        self.pool.check()

    def run(self, arglist=None):
        # As memory-target is now driven off an RRD, we need to give it some
        # time to not be 0!
        xenrt.TEC().logverbose("Sleeping 5 minutes to allow RRDs to update...")
        time.sleep(300)
        xenrt.TEC().logverbose("...done")

        # Check the domain zero memory target is still honoured
        self.runSubcase("checkmem",
                        (float(self.targets[0]), 0),
                         "Dom0Mem",
                         "Master")
        self.runSubcase("checkmem",
                        (float(self.targets[1]), 1),
                         "Dom0Mem",
                         "Slave")

class TC8608(_PoolTest):
    """Slave hosts should re-enable soon after a master xapi restart"""

    def testModeprepare(self, arglist=None):
        self.pool = self.getDefaultPool()
        self.host0 = self.pool.master
        self.host1 = self.pool.getSlaves()[0]

    def prepare(self, arglist=None):
        # Prepare a pool of two hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.pool.addHost(self.host1)
        self.pool.check()
        self.guest = self.host1.createGenericLinuxGuest(sr=self.host1.getLocalSR())
        self.uninstallOnCleanup(self.guest)
        st = xenrt.util.timenow()
        ma = None
        while True:
            ma = int(self.guest.paramGet("memory-actual"))
            if ma > 0:
                break
            if (xenrt.util.timenow() - st) > 120:
                raise xenrt.XRTError("memory-actual remaining at zero on "
                                     "initial boot")
            time.sleep(10)

    def run(self, arglist=None):

        for i in range(10):
            self.iteration()

    def iteration(self):        
        # Restart the master's xapi
        self.host0.restartToolstack()

        # Check for the slave being shown as enabled
        for attempts in range(4):
            time.sleep(30)
            enabled = self.host1.getHostParam("enabled")
            if enabled == "true":
                # Check that memory-actual is non zero
                st = xenrt.util.timenow()
                ma = 0
                while ma == 0:
                    if (xenrt.util.timenow() - st) > 120:
                        raise xenrt.XRTFailure("memory-actual still zero 2 mins"
                                               " after host became enabled")
                    ma = int(self.guest.paramGet("memory-actual"))
                return
        raise xenrt.XRTFailure("Slave still showing as disabled 2 minutes "
                               "after master xapi restart")

class TC8611(_PoolTest):
    """Slaves should re-establish host metrics soon after a master xapi restart when HA is enabled"""

    def testModePrepare(self, arglist=None):
        self.sr = None
        self.lun = None
        
        self.pool = self.getDefaultPool()
        self.host0 = self.pool.master
        self.host1 = self.pool.getSlaves()[0]

        # Set up the iSCSI HA SR
        self.lun = xenrt.ISCSITemporaryLun(300)
        self.sr = xenrt.lib.xenserver.ISCSIStorageRepository(\
            self.pool.master, "TC-8611")
        self.sr.create(self.lun, subtype="lvm", findSCSIID=True, noiqnset=True)
        self.pool.enableHA()

    def prepare(self, arglist=None):
        self.sr = None
        self.lun = None

        # Prepare a pool of two hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.pool.addHost(self.host1)
        self.pool.check()

        # Set up the iSCSI HA SR
        self.lun = xenrt.ISCSITemporaryLun(300)
        self.sr = xenrt.lib.xenserver.ISCSIStorageRepository(\
            self.pool.master, "TC-8611")
        self.sr.create(self.lun, subtype="lvm", findSCSIID=True, noiqnset=True)
        self.pool.enableHA()

    def run(self, arglist=None):

        # Restart the master's xapi
        self.host0.restartToolstack()

        # Check for the slave host-metrics-live becoming true
        for attempts in range(10):
            time.sleep(30)
            hml = self.host1.getHostParam("host-metrics-live")
            if hml == "true":
                return
        raise xenrt.XRTFailure("Slave still showing host-metrics-live=false 5 "
                               "minutes after master xapi restart")

    def postRun(self):
        # Disable HA
        try:
            self.pool.disableHA(check=False)
        except:
            pass
        # Remove the SR
        if self.sr:
            try:
                self.sr.remove()
            except:
                pass
        if self.lun:
            try:
                self.lun.release()
            except:
                pass
        _PoolTest.postRun(self)

class TC7985(xenrt.TestCase):
    """Verify the pool-wide application and prechecking of example patches
       using the patch-pool-apply CLI command"""

    def prepare(self, arglist=None):
        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")
        host2 = self.getHost("RESOURCE_HOST_2")

        host0.resetToFreshInstall()
        host1.resetToFreshInstall()
        host2.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(host0.productVersion)(host0)
        self.pool.addHost(host1)
        self.pool.addHost(host2)
        self.pool.check()

    def patch1(self):
        try:
            self.pool.applyPatch(self.pool.master.getTestHotfix(1), returndata=True)
        except xenrt.XRTFailure, e:
            raise xenrt.XRTFailure("Failure while applying patch: " + e.reason)

        for h in self.pool.getHosts():
            if h.execdom0("test -e /root/hotfix-test1", retval="code") != 0:
                raise xenrt.XRTFailure("/root/hotfix-test1 does not exist after applying hotfix1")

    def patch2(self):
        try:
            self.pool.applyPatch(self.pool.master.getTestHotfix(2), returndata=True)
        except xenrt.XRTFailure, e:
            raise xenrt.XRTFailure("Failure while applying patch: " + e.reason)

        for h in self.pool.getHosts():
            if not isinstance(h, xenrt.lib.xenserver.DundeeHost) and h.execdom0("rpm -q Deployment_Guide-en-US", retval="code") != 0:
                raise xenrt.XRTFailure("Deployment_Guide-en-US RPM not found after applying hotfix2")

    def patch3(self):
        try:
            self.pool.applyPatch(self.pool.master.getTestHotfix(3), returndata=True)
        except xenrt.XRTFailure, e:
            if not re.search("It is doomed to failure", e.data):
                raise xenrt.XRTFailure("hotfix3 apply error message did not contain 'It is doomed to failure'")
        else:
            raise xenrt.XRTFailure("hotfix3 apply did not fail")

    def patch4(self):
        try:
            self.pool.applyPatch(self.pool.master.getTestHotfix(4), returndata=True)
        except xenrt.XRTFailure, e:
            if not re.search("the server is of an incorrect version", e.data):
                raise xenrt.XRTFailure("hotfix4 apply error message did not contain'the server is of an incorrect version'")
        else:
            raise xenrt.XRTFailure("hotfix4 apply did not fail")

        # Check the body wasn't executed anyway (XRT-5112)
        for h in self.pool.getHosts():
            rc = h.execdom0("ls /root/hotfix-test4", retval="code")
            if rc == 0:
                raise xenrt.XRTFailure("Body of patch executed even though precheck failed", data=h.getName())

    def patch5(self):
        try:
            self.pool.applyPatch(self.pool.master.getTestHotfix(5), returndata=True)
        except xenrt.XRTFailure, e:
            raise xenrt.XRTFailure("Failure while applying patch: " + e.reason)

    def run(self, arglist=None):
        self.runSubcase("patch1", (), "TC7985", "Test1")
        self.runSubcase("patch2", (), "TC7985", "Test2")
        self.runSubcase("patch3", (), "TC7985", "Test3")
        self.runSubcase("patch4", (), "TC7985", "Test4")
        self.runSubcase("patch5", (), "TC7985", "Test5")

class TC8758(xenrt.TestCase):
    """Regression test for CA-22596"""

    def prepare(self, arglist=None):
        # Prepare a pool of two hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
        self.pool.addHost(self.host1)
        self.pool.check()

        # Install a VM on the slave
        self.guest = self.host1.createGenericLinuxGuest(sr=self.host1.getLocalSR())
        self.uninstallOnCleanup(self.guest)
        self.guest.shutdown()

    def run(self, arglist=None):
        cli = self.pool.getCLIInstance()

        # Perform a pool-sync-database
        cli.execute("pool-sync-database")

        # Start the VM on the slave
        self.guest.start()

        # Fail the master
        self.host0.poweroff()

        # Now manually recover the pool
        self.pool.setMaster(self.host1)

        cli = self.pool.getCLIInstance()
        try:
            cli.execute("host-list")
        except:
            raise xenrt.XRTFailure("CA-22596 Xapi dead while converting slave "
                                   "with running VM into master")

    def postRun(self, arglist=None):
        try:
            if self.host0:
                self.host0.machine.powerctl.on()
                self.host0.waitForSSH(3600, desc="Host boot after power on")
        except:
            pass

class TC8905(xenrt.TestCase):
    """Verify that application to a pool of a patch that's already applied is
       rejected"""

    def prepare(self, arglist=None):
        self.pool = self.getDefaultPool()

        # Get the sample patches, and apply the simple one
        self.workdir = xenrt.TEC().getWorkdir()
        xenrt.getTestTarball("patchapply",extract=True,directory=self.workdir)

        if isinstance(self.pool.master, xenrt.lib.xenserver.Host) and self.pool.master.productVersion == 'George':
            self.hf = "hotfix-george-test1.xsupdate"
            self.hfName = "hotfix-test1"
        elif isinstance(self.pool.master, xenrt.lib.xenserver.Host) and self.pool.master.productVersion == 'Orlando':
            self.hf = "hotfix-orlando5-test1.xsupdate"
            self.hfName = "hotfix-orlando-test1"
        else:
            raise xenrt.XRTError("Can't identify correct hot-fix for this XS version")

        self.hf = "%s/patchapply/%s" % (self.workdir, self.hf)

        self.pool.applyPatch(self.hf)
        for h in self.pool.getHosts():
            h.execdom0("rm -f /root/hotfix-test1")

    def run(self, arglist=None):
        # Attempt to apply a patch again, we should get a suitable error back

        # Find the UUID
        uuid = self.pool.master.minimalList("patch-list", args="name-label=%s" %
                                                               (self.hfName))[0]
        cli = self.pool.getCLIInstance()
        allowed = False
        try:
            cli.execute("patch-pool-apply", "uuid=%s" % (uuid))
            allowed = True
        except xenrt.XRTFailure, e:
            # Check we get the expected error
            if not re.search("This patch has already been applied", e.data):
                raise xenrt.XRTError("Expected failure attempting to apply "
                                     "patch to pool for a second time, but "
                                     "with unexpected message", data=e.data)

        if allowed:
            raise xenrt.XRTFailure("Allowed to pool apply a patch that had "
                                   "already been applied")

        for h in self.pool.getHosts():
            if h.execdom0("ls /root/hotfix-test1", retval="code") == 0:
                raise xenrt.XRTFailure("Second application of patch to pool "
                                       "failed as expected, however patch "
                                       "executed anyway")



