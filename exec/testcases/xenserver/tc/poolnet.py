#
# XenRT: Test harness for Xen and the XenServer product family
#
# Pool networking testcases
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy
import xenrt, xenrt.lib.xenserver

class _TCPoolNet(xenrt.TestCase):

    SUBTESTS = []
    TOPOLOGY = None

    def prepare(self, arglist=None):
        # Prepare two independent hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        #self.host0.resetToFreshInstall()
        #self.host1.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)

    def masterSetup(self):
        self.host0.createNetworkTopology(self.TOPOLOGY)
        self.host0.checkNetworkTopology(self.TOPOLOGY)

    def slaveJoin(self):
        self.pool.addHost(self.host1)
        self.pool.check()

    def slaveCheck1(self):
        self.host1.restartToolstack()
        self.host1.checkNetworkTopology(self.TOPOLOGY,
                                        ignoremanagement=True,
                                        ignorestorage=True)

    def slaveMgmt(self):
        self.host1.addIPConfigToNetworkTopology(self.TOPOLOGY)

    def slaveCheck2(self):
        self.host1.checkNetworkTopology(self.TOPOLOGY)

    def masterCheck(self):
        self.host0.checkNetworkTopology(self.TOPOLOGY)

    def vmOps(self):
        pass

    def run(self, arglist=None):
        # Set up a networking scenario on the master
        if self.runSubcase("masterSetup", (), "Master", "Setup") != \
                xenrt.RESULT_PASS:
            return

        # Join the slave to the master
        if self.runSubcase("slaveJoin", (), "Slave", "Join") != \
                xenrt.RESULT_PASS:
            return

        # Verify network topology inheritance
        if self.runSubcase("slaveCheck1", (), "Slave", "CheckInherit") != \
                xenrt.RESULT_PASS:
            return

        # Set management and storage on the slave
        if self.runSubcase("slaveMgmt", (), "Slave", "Management") != \
                xenrt.RESULT_PASS:
            return

        # Verify network topology and management
        if self.runSubcase("slaveCheck2", (), "Slave", "Check") != \
                xenrt.RESULT_PASS:
            return

        # Verify network topology and management on the master is still OK
        if self.runSubcase("masterCheck", (), "Master", "Check") != \
                xenrt.RESULT_PASS:
            return

        # Ensure VMs can operate on the relevant networks
        if self.runSubcase("vmOps", (), "VM", "Ops") != \
                xenrt.RESULT_PASS:
            return

        # Extra tests as necessary
        for st in self.SUBTESTS:
            if self.runSubcase(st[0], st[1], st[2], st[3]) != xenrt.RESULT_PASS:
                return

class TC8143(_TCPoolNet):
    """Slave joining pool should inherit multiple VLANs on multiple bonds"""

    TOPOLOGY = """<NETWORK>
  <PHYSICAL network="NPRI">
    <NIC/>
    <NIC/>
    <VLAN network="VR01">
      <VMS/>
    </VLAN>
    <VLAN network="VR02">
      <VMS/>
    </VLAN>
    <MANAGEMENT/>
  </PHYSICAL>
  <PHYSICAL network="NSEC">
    <NIC/>
    <NIC/>
    <VLAN network="VR03">
      <VMS/>
    </VLAN>
    <VLAN network="VR04">
      <VMS/>
    </VLAN>
  </PHYSICAL>
  <PHYSICAL network="NPRI">
    <NIC/>
    <NIC/>
  </PHYSICAL>
</NETWORK>"""

class TC8147(_TCPoolNet):
    """Slave joining pool should inherit multiple VLANs (non-bonded)"""

    TOPOLOGY = """<NETWORK>
  <PHYSICAL network="NPRI">
    <NIC/>
    <VLAN network="VR01">
      <VMS/>
    </VLAN>
    <VLAN network="VR02">
      <VMS/>
    </VLAN>
    <MANAGEMENT/>
  </PHYSICAL>
  <PHYSICAL network="NSEC">
    <NIC/>
    <VLAN network="VR03">
      <VMS/>
    </VLAN>
    <VLAN network="VR04">
      <VMS/>
    </VLAN>
  </PHYSICAL>
  <PHYSICAL network="NPRI">
    <NIC/>
    <VLAN network="VR05">
      <VMS/>
    </VLAN>
    <VLAN network="VR06">
      <VMS/>
    </VLAN>
  </PHYSICAL>
</NETWORK>"""

class TC8148(_TCPoolNet):
    """Slave joining pool should inherit multiple bonds"""

    TOPOLOGY = """<NETWORK>
  <PHYSICAL network="NPRI">
    <NIC/>
    <NIC/>
    <VMS/>
    <MANAGEMENT/>
  </PHYSICAL>
  <PHYSICAL network="NSEC">
    <NIC/>
    <NIC/>
    <VMS/>
  </PHYSICAL>
  <PHYSICAL network="NPRI">
    <NIC/>
    <NIC/>
  </PHYSICAL>
</NETWORK>"""

class TC8164(_TCPoolNet):
    """Should be able to put management on a bond on PIFs other than the PIF that was originally the management interface when that bond has a VLAN on it."""

    TOPOLOGY = """<NETWORK>
  <PHYSICAL network="NPRI">
    <NIC/>
  </PHYSICAL>
  <PHYSICAL network="NSEC">
    <NIC/>
    <NIC/>
    <MANAGEMENT/>
    <VLAN network="VR01">
      <VMS/>
    </VLAN>
  </PHYSICAL>
</NETWORK>"""

class TC8165(_TCPoolNet):
    """Should be able to put an IP address on a bond on PIFs other than the management PIF when that bond has a VLAN on it."""

    TOPOLOGY = """<NETWORK>
  <PHYSICAL network="NPRI">
    <NIC/>
    <MANAGEMENT/>
  </PHYSICAL>
  <PHYSICAL network="NSEC">
    <NIC/>
    <NIC/>
    <STORAGE/>
    <VLAN network="VR01">
      <VMS/>
    </VLAN>
  </PHYSICAL>
</NETWORK>"""

class TC8168(_TCPoolNet):
    """Can move management interface between bond slave/master on pool-master"""
    
    TOPOLOGY = """<NETWORK>
  <PHYSICAL network="NPRI">
    <NIC/>
    <NIC/>
    <MANAGEMENT/>
  </PHYSICAL>
</NETWORK>"""

    SUBTESTS = [("mgmtToRaw", (), "Mgmt", "ToRawNIC"),
                ("mgmtToBond", (), "Mgmt", "ToBond"),
                ("mgmtToRaw", (), "Mgmt", "ToRawNIC2"),
                ("mgmtToBond", (), "Mgmt", "ToBond2"),
                ("masterCheck", (), "Mgmt", "Check")]

    USEMASTER = True

    def mgmtToRaw(self):
        """Move the management interface from the bond master PIF to the
        bond slave with the same MAC address."""

        if self.USEMASTER:
            host = self.host0
        else:
            host = self.host1

        # Get the host's management PIF
        mgmtpif = host.parseListForUUID("pif-list",
                                        "host-uuid",
                                        host.getMyHostUUID(),
                                        "management=true")
        # Get the bond
        bond = host.genParamGet("pif", mgmtpif, "bond-master-of")
        if not bond or bond == "<not in database>":
            raise xenrt.XRTError("Management PIF is not a bond master",
                                 "PIF %s" % (mgmtpif))
        
        # Find the correct slave PIF
        mac = host.genParamGet("pif", mgmtpif, "MAC")
        slavepif = host.parseListForUUID("pif-list",
                                         "MAC",
                                         mac,
                                         "physical=true")
        if not slavepif:
            raise xenrt.XRTError("Could not find a physical NIC with the same"
                                 "MAC as the bond master")
        b = host.genParamGet("pif", slavepif, "bond-slave-of")
        if b != bond:
            raise xenrt.XRTError("The slave PIF we found claims to not be one")
        
        # Move management to the bond slave PIF
        cli = host.getCLIInstance()
        cli.execute("pif-reconfigure-ip uuid=%s mode=dhcp" % (slavepif))
        try:
            cli.execute("host-management-reconfigure pif-uuid=%s" % (slavepif))
        except:
            # This will always return an error.
            pass
        time.sleep(120)

        # Make sure we can still run CLI commands
        try:
            cli.execute("vm-list")
        except:
            raise xenrt.XRTFailure("Failed to run CLI command over new "
                                   "management interface.")

        # Leave DHCP enabled on the bond master
        self.bondMasterPIF = mgmtpif
        self.bondSlavePIF = slavepif

    def mgmtToBond(self):
        """Move the management interface from the bond slave to the bond
        master."""

        if self.USEMASTER:
            host = self.host0
        else:
            host = self.host1

        # Move management to the bonf master PIF
        cli = host.getCLIInstance()
        try:
            cli.execute("host-management-reconfigure pif-uuid=%s" %
                        (self.bondMasterPIF))
        except:
            # This will always return an error.
            pass
        time.sleep(120)
        
        # Remove IP from the bond slave
        cli.execute("pif-reconfigure-ip uuid=%s mode=None" %
                    (self.bondSlavePIF))

        # Make sure we can still run CLI commands
        try:
            cli.execute("vm-list")
        except:
            raise xenrt.XRTFailure("Failed to run CLI command over new "
                                   "management interface.")

class TC8169(TC8168):
    """Can move management interface between bond slave/master on pool-slave"""

    SUBTESTS = [("mgmtToRaw", (), "Mgmt", "ToRawNIC"),
                ("mgmtToBond", (), "Mgmt", "ToBond"),
                ("mgmtToRaw", (), "Mgmt", "ToRawNIC2"),
                ("mgmtToBond", (), "Mgmt", "ToBond2"),
                ("slaveCheck2", (), "Mgmt", "Check")]

    USEMASTER = False

class TC8174(_TCPoolNet):
    """Check bond MACs are set correctly on slave after inheriting bond across pool join."""

    TOPOLOGY = """<NETWORK>
  <PHYSICAL network="NPRI">
    <NIC/>
    <NIC/>
    <MANAGEMENT/>
  </PHYSICAL>
  <PHYSICAL network="NSEC">
    <NIC enum="1"/>
    <NIC enum="0"/>
  </PHYSICAL>
  <PHYSICAL network="NPRI">
    <NIC enum="3"/>
    <NIC enum="2"/>
  </PHYSICAL>
</NETWORK>"""

    def masterSetup(self):
        self.host0.createNetworkTopology(self.TOPOLOGY)
        self.host0.checkNetworkTopology(self.TOPOLOGY)
        self.host0.restartToolstack()

class TC8170(_TCPoolNet):
    """Bond and VLAN configurations should be retained after master and host reboots"""

    TOPOLOGY = """<NETWORK>
  <PHYSICAL network="NPRI">
    <NIC/>
    <NIC/>
    <VLAN network="VR01">
      <VMS/>
    </VLAN>
    <VLAN network="VR02">
      <VMS/>
    </VLAN>
    <MANAGEMENT/>
  </PHYSICAL>
  <PHYSICAL network="NSEC">
    <NIC/>
    <NIC/>
    <VLAN network="VR03">
      <VMS/>
    </VLAN>
    <VLAN network="VR04">
      <VMS/>
    </VLAN>
  </PHYSICAL>
  <PHYSICAL network="NPRI">
    <NIC/>
    <NIC/>
  </PHYSICAL>
</NETWORK>"""

    SUBTESTS = [("rebootSlave", (), "Reboot", "Slave"),
                ("slaveCheck2", (), "Reboot", "CheckSlave"),
                ("rebootMaster", (), "Reboot", "Master"),
                ("masterCheck", (), "Reboot", "CheckMaster")]

    def rebootMaster(self):
        self.host0.reboot()

    def rebootSlave(self):
        self.host1.reboot()

class _TCExistingPoolNet(xenrt.TestCase):
    """Base class for network operations on existing pools"""

    SUBTESTS = []
    TOPOLOGY = None
    NEWTOPOLOGY = None

    def prepare(self, arglist=None):
        # Prepare two independent hosts
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        #self.host0.resetToFreshInstall()
        #self.host1.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)

        # Set up the master networking
        self.host0.createNetworkTopology(self.TOPOLOGY)
        self.host0.checkNetworkTopology(self.TOPOLOGY)

        # Join the slave
        self.pool.addHost(self.host1)
        self.pool.check()
        self.host1.checkNetworkTopology(self.TOPOLOGY,
                                        ignoremanagement=True,
                                        ignorestorage=True)

        # Complete the slave IP configuration
        self.host1.addIPConfigToNetworkTopology(self.TOPOLOGY)
        self.host1.checkNetworkTopology(self.TOPOLOGY)
        self.host0.checkNetworkTopology(self.TOPOLOGY)

    def slaveCheck(self):
        self.host1.checkNetworkTopology(self.NEWTOPOLOGY)

    def masterCheck(self):
        self.host0.checkNetworkTopology(self.NEWTOPOLOGY)

    def networkOperation(self):
        raise xenrt.XRTError("Unimplemented")

    def vmOps(self):
        # Install a VM on each bridge that was tagged for VM use, verify it
        # can boot. Do this on each host
        networks = self.host0.minimalList("network-list",
                                          "uuid",
                                          "other-config:xenrtvms=true")
        if len(networks) == 0:
            raise xenrt.XRTError("No networks found with xenrtvms=true")
        for host in [self.host0, self.host1]:
            for nw in networks:
                br = host.genParamGet("network", nw, "bridge")
                g = host.createGenericLinuxGuest(bridge=br)
                self.uninstallOnCleanup(g)
                g.reboot()
                g.shutdown()

    def run(self, arglist=None):
        # Perform the networking operation on the existing pool
        if self.runSubcase("networkOperation", (), "Pool", "NetworkOp") != \
                xenrt.RESULT_PASS:
            return

        # Verify the new network topology and management on the master is OK
        if self.runSubcase("masterCheck", (), "Master", "PostCheck") != \
                xenrt.RESULT_PASS:
            return

        # Verify the new network topology and management on the slave is OK
        if self.runSubcase("slaveCheck", (), "Slave", "PostCheck") != \
                xenrt.RESULT_PASS:
            return

        # Ensure VMs can operate on the relevant networks
        if self.runSubcase("vmOps", (), "VM", "Ops") != \
                xenrt.RESULT_PASS:
            return

        # Extra tests as necessary
        for st in self.SUBTESTS:
            if self.runSubcase(st[0], st[1], st[2], st[3]) != xenrt.RESULT_PASS:
                return

class TC7825(_TCExistingPoolNet):
    """Add a VLAN network to bonded interfaces on an existing pool"""
    
    TOPOLOGY = """<NETWORK>
  <PHYSICAL network="NPRI">
    <NIC/>
    <NIC/>
    <MANAGEMENT/>
  </PHYSICAL>
  <PHYSICAL network="NSEC">
    <NIC/>
    <NIC/>
  </PHYSICAL>
</NETWORK>"""

    NEWTOPOLOGY = """<NETWORK>
  <PHYSICAL network="NPRI">
    <NIC/>
    <NIC/>
    <MANAGEMENT/>
  </PHYSICAL>
  <PHYSICAL network="NSEC">
    <NIC/>
    <NIC/>
    <VLAN network="VR08">
      <VMS/>
    </VLAN>
  </PHYSICAL>
</NETWORK>"""

    def networkOperation(self):
        """Create a VLAN on the second bond"""
        # Get the VLAN
        vid, subnet, netmask = self.host0.getVLAN("VR08")

        # Find the network for the bond we'll put the VLAN on
        cli = self.host0.getCLIInstance()
        nwlist = self.host0.minimalList("network-list")
        netname = None
        bondnw = None
        for nw in nwlist:
            network = self.host0.genParamGet("network", nw, "name-label")
            r = re.search("(NSEC) bond of (.*)", network)
            if r:
                netname = "VLAN VR08 on %s %s" % (r.group(1), r.group(2))
                bondnw = nw
                break
        if not bondnw:
            raise xenrt.XRTError("Could not find NSEC bond network")
        
        # Create a network object. This has to have the name the topology
        # check code expects
        args = []
        args.append("name-label=\"%s\"" % (netname))
        args.append("name-description=\"Created by XenRT for TC7825\"")
        nwuuid = cli.execute("network-create", string.join(args)).strip() 
        self.host0.genParamSet("network",
                               nwuuid,
                               "other-config",
                               "true",
                               "xenrtvms")      
        # For each host find the bond PIF and create a VLAN object
        for host in [self.host0, self.host1]:
            # Find the right PIF
            bpif = host.parseListForUUID("pif-list",
                                         "network-uuid",
                                         bondnw,
                                         "host-uuid=%s" %
                                         (host.getMyHostUUID()))
            if not bpif:
                raise xenrt.XRTError("Could not find NSEC bond PIF",
                                     "host %s" % (host.getName()))

            # Create the VLAN object
            args = []
            args.append("network-uuid=%s" % (nwuuid))
            args.append("pif-uuid=%s" % (bpif))
            args.append("vlan=%u" % (vid))
            cli.execute("vlan-create", string.join(args))

class TC8308(xenrt.TestCase):
    """Creating a pool-wide VLAN with pool-vlan-create"""

    def prepare(self, arglist=None):
        # 1. Create a pool of two hosts
        host0 = self.getHost("RESOURCE_HOST_0")
        self.host0 = host0
        host1 = self.getHost("RESOURCE_HOST_1")
        self.host1 = host1

        self.pool = xenrt.lib.xenserver.poolFactory(host0.productVersion)(host0)
        self.pool.addHost(host1)

    def run(self, arglist=None):
        host0 = self.host0
        host1 = self.host1

        # 2. Find the UUID of the pif on the master
        primary = host0.minimalList("pif-list",
                                    args="management=true host-uuid=%s" %
                                         (host0.getMyHostUUID()))[0]
        xenrt.TEC().logverbose("Found primary PIF: %s" % (primary))
        # Note down the device
        priDev = host0.genParamGet("pif", primary, "device")

        # 3. Create a new network to use with the VLAN
        nwuuid = host0.createNetwork("VLAN Network")

        # 4. Run the pool-vlan-create CLI command
        # Figure out the vlan tag
        vlan = host0.getVLAN("VR01")
        vtag = int(vlan[0])
        cli = host0.getCLIInstance()
        cli.execute("pool-vlan-create", "pif-uuid=%s network-uuid=%s vlan=%u" %
                                        (primary, nwuuid, vtag))

        # 5. Check master and slave have correct PIFs and are attached
        # Get all PIFs on the network (we expect 2)
        pifs = host0.genParamGet("network", nwuuid, "PIF-uuids").split(";")
        if len(pifs) != 2:
            raise xenrt.XRTFailure("Found %u PIFs on network, expecting 2" %
                                   (len(pifs)))
        host0.checkVLAN(vtag, nic=priDev)
        host1.checkVLAN(vtag, nic=priDev)
            

class TC14933(xenrt.TestCase):
    """Existing static IP on slave management interface is preserved when
       joining a pool"""

    MASTERTOPOLOGY = """<NETWORK>
  <PHYSICAL network="NPRI">
    <NIC/>
    <MANAGEMENT/>
  </PHYSICAL>
</NETWORK>"""

    SLAVETOPOLOGY = """<NETWORK>
  <PHYSICAL network="NPRI">
    <NIC/>
    <MANAGEMENT mode="static"/>
  </PHYSICAL>
</NETWORK>"""

    SLAVEPOSTJOIN = SLAVETOPOLOGY

    def prepare(self, arglist=None):
        self.master = self.getHost("RESOURCE_HOST_0")
        self.slave = self.getHost("RESOURCE_HOST_1")

        # Set the master topology up
        self.master.createNetworkTopology(self.MASTERTOPOLOGY)
        self.master.checkNetworkTopology(self.MASTERTOPOLOGY)

        # Set the slave up with a static IP
        self.slave.createNetworkTopology(self.SLAVETOPOLOGY)
        self.slave.checkNetworkTopology(self.SLAVETOPOLOGY)

        self.pool = xenrt.lib.xenserver.poolFactory(self.master.productVersion)(self.master)

    def run(self, arglist=None):
        # Join the slave to the master
        self.pool.addHost(self.slave)

        # Check the network configurations are as expected
        self.slave.checkNetworkTopology(self.SLAVEPOSTJOIN)

class TC14934(TC14933):
    """Existing static IP on slave management interface is preserved when
       joining a pool with a bonded management inteface"""

    MASTERTOPOLOGY = """<NETWORK>
  <PHYSICAL network="NPRI">
    <NIC/>
    <NIC/>
    <MANAGEMENT/>
  </PHYSICAL>
</NETWORK>"""

    SLAVEPOSTJOIN = """<NETWORK>
  <PHYSICAL network="NPRI">
    <NIC/>
    <NIC/>
    <MANAGEMENT mode="static"/>
  </PHYSICAL>
</NETWORK>"""


