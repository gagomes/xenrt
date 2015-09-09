#
# XenRT: Test harness for Xen and the XenServer product family
#
# Host upgrade standalone testcases
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy, os, shutil
import os.path
import xenrt, xenrt.lib.xenserver, xenrt.lib.xenserver.call, xenrt.lib.xenserver.context
import IPy
from xenrt.lazylog import log, step

class TC6854(xenrt.TestCase):
    """Windows live migrate between XenServer v4.1 and v4"""

    def __init__(self, tcid="TC6854"):
        xenrt.TestCase.__init__(self, tcid)
        self.WORKLOADS = ["w_find",
                          "w_forktest2",
                          "w_memtest",
                          "w_spamcons"]
        self.WINDOWS_WORKLOADS = ["Prime95",
                                  "Ping",
                                  "SQLIOSim",
                                  "Burnintest",
                                  "NetperfTX",
                                  "NetperfRX",
                                  "Memtest"]

    def upgrade(self, host):
        host.tailored = False

        interfaces = []
        interfaces.append((None, "yes", "dhcp", None, None, None, None, None, None))
        disks = string.split(host.lookup("OPTION_CARBON_DISKS", "sda"))
        primarydisk=disks[0]

        xenrt.lib.xenserver.cli.clearCacheFor(host.machine)
        host.install(interfaces=interfaces,
                     primarydisk=primarydisk,
                     guestdisks=disks,
                     upgrade=True)
        time.sleep(180)
        host.check(interfaces=interfaces,
                   primarydisk=primarydisk,
                   guestdisks=disks)

    def run(self, arglist=None):
        loops = 100

        h0 = self.getHost("RESOURCE_HOST_0")
        h1 = self.getHost("RESOURCE_HOST_1")

        g = xenrt.TEC().registry.guestGet("guest-0")

        xenrt.TEC().progress("Migrating VM off master.")
        g.migrateVM(h1, live=True, fast=True)

        xenrt.TEC().progress("Upgrading master.")
        self.upgrade(h0)

        for i in range(loops):
            if g.windows:
                g.startWorkloads(self.WINDOWS_WORKLOADS)
            else:
                g.startWorkloads(self.WORKLOADS)
            g.migrateVM(h0, live=True, fast=True)
            g.shutdown()
            cli = h0.getCLIInstance()
            cli.execute("vm-start uuid=%s on=%s" % (g.getUUID(), h1.getMyHostName()))
            g.host = h1
            g.check()

class _PoolUpgrade(xenrt.TestCase):
    """Pool upgrade from previous GA version using NFS SR."""

    ops = [ "randStartVM",
            "randStopVM",
            "randRebootVM",
            "randSuspendResumeVM",
            "randIncreaseCPUs",
            "randResetCPUs" ]

    WORKLOADS = False
    SUSPEND = False
    NONROLLING = False

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.hosts = []
        self.suspendedGuests = {}
        self.vmbridge = None
        self.hostNames = []

    def checkVMs(self):
        for g in self.guests.values():
            suspended = False
            for sgs in self.suspendedGuests.values():
                if g in sgs:
                    suspended = True
                    break
            if suspended:
                if g.getState() != "SUSPENDED":
                    raise xenrt.XRTFailure("Guest %s is not suspended: '%s'" %
                                           (g.getName(), g.getState()))
                continue # Can't checkHealth a suspended VM!
            elif g.getState() != "UP":
                raise xenrt.XRTFailure("Guest %s is not up: '%s'" %
                                       (g.getName(), g.getState()))
            g.checkHealth()

    def installVMs(self):
        self.guests = {}

        windistro = xenrt.TEC().lookup("RPU_WINDOWS_VERSION", "w2k3eesp2")
        windistro2 = xenrt.TEC().lookup("RPU_WINDOWS_VERSION2", windistro)
        lindistro = xenrt.TEC().lookup("RPU_LINUX_VERSION", self.hosts[0].lookup("DEFAULT_RPU_LINUX_VERSION", "rhel45"))

        af0 = []
        af1 = []

        if windistro != "None":
            self.guests['win1'] = xenrt.lib.xenserver.guest.createVM(\
                self.hosts[0],
                "win1",
                windistro,
                vifs=[("0", self.vmbridge, xenrt.randomMAC(), None)],
                bridge=self.vmbridge)
            self.guests['win1'].installDrivers()
            af0.append('win1')
            self.guests['win2'] = xenrt.lib.xenserver.guest.createVM(\
                self.hosts[1],
                "win2",
                windistro2,
                vifs=[("0", self.vmbridge, xenrt.randomMAC(), None)],
                bridge=self.vmbridge)
            self.guests['win2'].installDrivers()
            af1.append('win2')
        if isinstance(self.hosts[0], xenrt.lib.xenserver.MNRHost) and not isinstance(self.hosts[0], xenrt.lib.xenserver.TampaHost):
            self.guests['Debian'] = xenrt.lib.xenserver.guest.createVM(\
                self.hosts[0],
                "Debian",
                "debian50",
                vifs=[("0", self.vmbridge, xenrt.randomMAC(), None)],
                bridge=self.vmbridge)
        else:
            self.guests['Debian'] = self.hosts[0].createGenericLinuxGuest(\
                name="Debian",
                bridge=self.vmbridge)
        af0.append('Debian')
        self.guests['Linux'] = xenrt.lib.xenserver.guest.createVM(\
            self.hosts[0],
            "Linux",
            lindistro,
            vifs=[("0", self.vmbridge, xenrt.randomMAC(), None)],
            bridge=self.vmbridge)
        af1.append('Linux')

        for g in self.guests.values():
            self.getLogsFrom(g)
            g.shutdown()
            g.memset(1024)
            g.start()
        self.affinity = []
        self.affinity.append(af0)
        self.affinity.append(af1)
        self.vmworkloads = {}

    def randomOps(self):
        for g in self.guests.values():
            xenrt.TEC().progress("Adding devices to VM %s" % (g.getName()))
            device = g.host.genParamGet("vm",
                                        g.getUUID(),
                                        "allowed-VBD-devices").split("; ")[0]
            g.createDisk(sizebytes=20000000,
                         sruuid="DEFAULT",
                         userdevice=device)
            device = "%s%d" % (g.vifstem,
                               int(g.host.genParamGet(\
                "vm", g.getUUID(), "allowed-VIF-devices").split("; ")[0]))
            mac = xenrt.randomMAC()
            if self.vmbridge:
                bridge = self.vmbridge
            else:
                bridge = g.host.getPrimaryBridge()
            g.createVIF(device, bridge, mac)
            g.plugVIF(device)
            time.sleep(10)
            g.updateVIFDriver()

        for g in self.guests.values():
            xenrt.TEC().progress("Performing some random ops VM %s" %
                                 (g.getName()))
            for i in range(5):
                op = self.ops[random.randint(0, len(self.ops) - 1)]
                eval("self.%s('%s')" % (op, g.getName()))

            self.setState(g.getName(), "UP")

        self.checkVMs()

    def ejectCDs(self):
        for g in self.guests.values():
            xenrt.TEC().progress("Ejecting CD from VM %s" % (g.getName()))
            g.changeCD(None)

    def startWorkloads(self):
        for g in self.guests.values():
            xenrt.TEC().progress("Starting workloads on VM %s" % (g.getName()))
            self.vmworkloads[g.getName()] = g.startWorkloads()

    def upgradePool(self):
        p = self.hosts[0].pool
        newP = xenrt.lib.xenserver.poolFactory(xenrt.TEC().lookup("PRODUCT_VERSION", None))(p.master)
        p.populateSubclass(newP)

    def migrate(self, fromHost, toHost, all):
        for gn in self.hosts[fromHost].listGuests(running=True):
            if self.guests.has_key(gn):
                if all or gn in self.affinity[toHost]:
                    g = self.guests[gn]
                    xenrt.TEC().progress("Migrating VM %s from %s to %s" %
                                         (g.getName(),
                                          self.hosts[fromHost].getName(),
                                          self.hosts[toHost].getName()))
                    g.migrateVM(self.hosts[toHost], live=True)
        self.checkVMs()

    def suspend(self, onHost):
        h = self.hosts[onHost]
        self.suspendedGuests[onHost] = []
        for gn in h.listGuests(running=True):
            if self.guests.has_key(gn):
                g = self.guests[gn]
                xenrt.TEC().progress("Suspending VM %s on %s" %
                                     (g.getName(),
                                      h.getName()))
                g.suspend()
                self.suspendedGuests[onHost].append(g)

    def resume(self, onHost):
        h = self.hosts[onHost]
        for g in self.suspendedGuests[onHost]:
            g.resume()
        self.suspendedGuests[onHost] = []

    def upgrade(self, hostid):
        host = self.hosts[hostid]
        host = host.upgrade()
        self.hosts[hostid] = host
        time.sleep(180)
        host.check()
        host.reboot()
        host.check()
        if not self.NONROLLING:
            self.checkVMs()

    def poolCheck(self):
        self.hosts[0].pool.check()
        hostNames = self.hosts[0].minimalList("host-list", "name-label")
        for hn in self.hostNames:
            if not hn in hostNames:
                raise xenrt.XRTFailure("Host %s missing from pool after "
                                       "upgrade" % (hn))

    def vmCheck1(self):
        for g in self.guests.values():
            xenrt.TEC().progress("Checking VM %s" % (g.getName()))
            g.verifyGuestFunctional()
            if self.vmworkloads.has_key(g.getName()):
                g.stopWorkloads(self.vmworkloads[g.getName()])
            g.check()
            g.checkHealth()
            g.reboot()
            g.shutdown()
            g.start()

    def vmCheck2(self):
        for g in self.guests.values():
            xenrt.TEC().progress("Checking VM %s" % (g.getName()))
            g.verifyGuestFunctional()
            g.check()
            g.suspend()
            g.resume()
            g.check()
            g.suspend()
            g.resume()
            g.check()
            g.reboot()
            g.shutdown()
            g.start()
            g.checkHealth()

    def upgradeVMs(self):

        # upgrade guest objects
        newGuests = {}
        for n,g in self.guests.iteritems():
            newGuests[n] = self.hosts[0].guestFactory()(g.getName())
            g.populateSubclass(newGuests[n])

        self.guests = newGuests

        for g in self.guests.values():
            xenrt.TEC().progress("Upgrading VM %s" % (g.getName()))
            if g.windows:
                g.installDrivers()
            else:
                # Workaround for CA-78632
                xenrt.TEC().logverbose("CA-78632 class %s template: %s" % (self.hosts[0].__class__, g.template))
                if re.search("Lenny", g.template) and isinstance(self.hosts[0], xenrt.lib.xenserver.TampaHost):
                    xenrt.TEC().logverbose("Skipping tools upgrade on %s" % (g.getName()))
                else:
                    g.installTools()
        self.checkVMs()

    def shutdown(self):
        for g in self.guests.values():
            xenrt.TEC().progress("Shutting down VM %s" % (g.getName()))
            g.shutdown()

    def start(self):
        for g in self.guests.values():
            xenrt.TEC().progress("Starting VM %s" % (g.getName()))
            g.start()

    def hostsSetup(self):
        """Override this in the testcases to perform testcase-specific setup"""
        pass

    def hostsCheck(self):
        """Override this in the testcases to perform testcase-specific checks"""
        pass

    # Random operations (stolen from TCMixops)
    def setState(self, guestname, state):
        action = {'UP'        :  { 'DOWN'      : 'shutdown',
                                   'SUSPENDED' : 'suspend'},
                  'DOWN'      :  { 'UP'        : 'start',
                                   'SUSPENDED' : 'start'},
                  'SUSPENDED' :  { 'DOWN'      : 'resume',
                                   'UP'        : 'resume'}}
        while not self.guests[guestname].getState() == state:
            eval("self.guests[guestname].%s()" %
                (action[self.guests[guestname].getState()][state]))

    def randStartVM(self, guestname):
        self.setState(guestname, "DOWN")
        self.guests[guestname].start()
        self.guests[guestname].check()

    def randStopVM(self, guestname):
        self.setState(guestname, "UP")
        self.guests[guestname].shutdown()

    def randRebootVM(self, guestname):
        self.setState(guestname, "UP")
        self.guests[guestname].start(reboot=True)
        self.guests[guestname].check()

    def randSuspendResumeVM(self, guestname):
        self.setState(guestname, "UP")
        self.guests[guestname].suspend()
        self.guests[guestname].resume()
        self.guests[guestname].check()

    def randIncreaseCPUs(self, guestname):
        if self.guests[guestname].cpuget() >= 4:
            return
        self.setState(guestname, "DOWN")
        self.guests[guestname].cpuset(self.guests[guestname].cpuget() + 1)
        self.setState(guestname, "UP")
        if self.guests[guestname].windows:
            self.setState(guestname, "DOWN")
            self.setState(guestname, "UP")
        self.guests[guestname].check()

    def randResetCPUs(self, guestname):
        self.setState(guestname, "DOWN")
        self.guests[guestname].cpuset(1)
        self.setState(guestname, "UP")
        if self.guests[guestname].windows:
            self.setState(guestname, "DOWN")
            self.setState(guestname, "UP")
        self.guests[guestname].check()

class _RollingPoolUpgrade(_PoolUpgrade):

    def run(self, arglist):
        # Assume two hosts have been previously installed using the previous
        # GA versions and set up in a pool with the appropriate SR
        self.hosts = []
        self.hosts.append(self.getHost("RESOURCE_HOST_0"))
        self.hosts.append(self.getHost("RESOURCE_HOST_1"))
        xenrt.TEC().setInputDir(None)
        self.hostNames = self.hosts[0].minimalList("host-list", "name-label")
        self.hostNames.sort()
        self.vmbridge = None
        self.suspendedGuests = {}

        # Perform testcase-specific host setup
        if self.runSubcase("hostsSetup", (), "Prep", "HostSetup") != \
                xenrt.RESULT_PASS:
            return

        # Install a selection of VMs on the pool
        if self.runSubcase("installVMs", (), "PrevGA", "VMInstalls") != \
                xenrt.RESULT_PASS:
            return

        # Perform some random operations including the addition of virtual
        # devices
        if self.runSubcase("randomOps", (), "PrevGA", "VMOps") != \
                xenrt.RESULT_PASS:
            return

        # Eject CDs from VMs before starting pool upgrade (required by
        # installation guide).
        if self.runSubcase("ejectCDs", (), "PrevGA", "EjectCDs") != \
                xenrt.RESULT_PASS:
            return

        # Start workloads on the VMs
        if self.WORKLOADS:
            if self.runSubcase("startWorkloads", (), "PrevGA", "StartWork") != \
                   xenrt.RESULT_PASS:
                return

        # Update our internal pool object
        if self.runSubcase("upgradePool", (), "Step0", "UpgPoolObject") != \
                xenrt.RESULT_PASS:
            return

        if self.SUSPEND:
            # Suspend VMs on the master
            if self.runSubcase("suspend", (0), "Step1", "Suspend") != \
                    xenrt.RESULT_PASS:
                return
        else:
            # Migrate VMs from the master to the slave
            if self.runSubcase("migrate", (0, 1, True), "Step1", "XenMotion") != \
                    xenrt.RESULT_PASS:
                return

        # Upgrade the master
        if self.runSubcase("upgrade", (0), "Step1", "Upgrade") != \
                xenrt.RESULT_PASS:
            return

        # Verify the pool has returned to normal mode
        if self.runSubcase("poolCheck", (), "Step1", "Verify") != \
                xenrt.RESULT_PASS:
            return

        if self.SUSPEND:
            # Resume VMs on the master
            if self.runSubcase("resume", (0), "Step2", "Resume") != \
                xenrt.RESULT_PASS:
                return
            # Suspend VMs on the slave
            if self.runSubcase("suspend", (1), "Step2", "Suspend") != \
                xenrt.RESULT_PASS:
                return
        else:
            # Migrate VMs from the slave to the master
            if self.runSubcase("migrate", (1, 0, True), "Step2", "XenMotion") != \
                    xenrt.RESULT_PASS:
                return

        # Upgrade the slave
        if self.runSubcase("upgrade", (1), "Step2", "Upgrade") != \
                xenrt.RESULT_PASS:
            return

        # Verify the pool has returned to normal mode
        if self.runSubcase("poolCheck", (), "Step2", "Verify") != \
                xenrt.RESULT_PASS:
            return

        if self.SUSPEND:
            # Resume VMs on the slave
            if self.runSubcase("resume", (1), "Step3", "Resume") != \
                xenrt.RESULT_PASS:
                return
        else:
            # Migrate some VMs back to the slave
            if self.runSubcase("migrate", (0, 1, False), "Step3", "XenMotion") != \
                    xenrt.RESULT_PASS:
                return

        # Perform testcase-specific host config checks
        if self.runSubcase("hostsCheck", (), "Step3", "HostsCheck") != \
                xenrt.RESULT_PASS:
            return

        # Very all VMs are operating normally
        if self.runSubcase("vmCheck1", (), "Step3", "Verify") != \
                xenrt.RESULT_PASS:
            return

        # Upgrade the drivers and tools in each VM
        if self.runSubcase("upgradeVMs", (), "Step4", "UpgradeVMs") != \
                xenrt.RESULT_PASS:
            return

        # Verify all VMs are operating normally
        if self.runSubcase("vmCheck2", (), "Step4", "Verify") != \
                xenrt.RESULT_PASS:
            return

        # Shutdown all the VMs
        if self.runSubcase("shutdown", (), "Step4", "Shutdown") != \
                xenrt.RESULT_PASS:
            return


class _NonRollingPoolUpgrade(_PoolUpgrade):

    NONROLLING = True

    def run(self, arglist):
        # Assume two hosts have been previously installed using the previous
        # GA versions and set up in a pool with the appropriate SR
        self.hosts = []
        self.hosts.append(self.getHost("RESOURCE_HOST_0"))
        self.hosts.append(self.getHost("RESOURCE_HOST_1"))
        xenrt.TEC().setInputDir(None)
        self.hostNames = self.hosts[0].minimalList("host-list", "name-label")
        self.hostNames.sort()
        self.vmbridge = None
        self.suspendedGuests = {}

        # Perform testcase-specific host setup
        if self.runSubcase("hostsSetup", (), "Prep", "HostSetup") != \
                xenrt.RESULT_PASS:
            return

        # Install a selection of VMs on the pool
        if self.runSubcase("installVMs", (), "PrevGA", "VMInstalls") != \
                xenrt.RESULT_PASS:
            return

        # Perform some random operations including the addition of virtual
        # devices
        if self.runSubcase("randomOps", (), "PrevGA", "VMOps") != \
                xenrt.RESULT_PASS:
            return

        # Eject CDs from VMs before starting pool upgrade (required by
        # installation guide).
        if self.runSubcase("ejectCDs", (), "PrevGA", "EjectCDs") != \
                xenrt.RESULT_PASS:
            return

        # Shut the VMs down
        if self.runSubcase("shutdown", (), "PrevGA", "ShutdownVMs") != \
               xenrt.RESULT_PASS:
            return

        # Update our internal pool object
        if self.runSubcase("upgradePool", (), "Pool", "UpgPoolObject") != \
                xenrt.RESULT_PASS:
            return

        # Upgrade the master
        if self.runSubcase("upgrade", (0), "Master", "Upgrade") != \
                xenrt.RESULT_PASS:
            return

        # Upgrade the slave
        if self.runSubcase("upgrade", (1), "Slave", "Upgrade") != \
                xenrt.RESULT_PASS:
            return

        # Verify the pool has returned to normal mode
        if self.runSubcase("poolCheck", (), "Pool", "Verify") != \
                xenrt.RESULT_PASS:
            return

        # Perform testcase-specific host config checks
        if self.runSubcase("hostsCheck", (), "Hosts", "Check") != \
                xenrt.RESULT_PASS:
            return

        # Start the VMs
        if self.runSubcase("start", (), "NewVer", "StartVMs") != \
                xenrt.RESULT_PASS:
            return

        # Very all VMs are operating normally
        if self.runSubcase("vmCheck1", (), "NewVer", "VerifyVMs") != \
                xenrt.RESULT_PASS:
            return

        # Upgrade the drivers and tools in each VM
        if self.runSubcase("upgradeVMs", (), "NewVer", "UpgradeVMs") != \
                xenrt.RESULT_PASS:
            return

        # Verify all VMs are operating normally
        if self.runSubcase("vmCheck2", (), "Final", "VerifyVMs") != \
                xenrt.RESULT_PASS:
            return

        # Shutdown all the VMs
        if self.runSubcase("shutdown", (), "Final", "ShutdownVMs") != \
                xenrt.RESULT_PASS:
            return

class TC6867(_RollingPoolUpgrade):
    """Pool rolling upgrade from previous GA version using NFS SR and static IP addressing."""

    pass

class TC8064(_RollingPoolUpgrade):
    """Pool rolling upgrade from n-2 GA version using NFS SR and static IP addressing."""
    pass

class TC8767(_RollingPoolUpgrade):
    """Pool rolling upgrade from previous GA version using iSCSI SR."""

    pass

class TC7984(_RollingPoolUpgrade):
    """Pool rolling upgrade from previous GA version using a bond and VLANs."""

    def findPIFToBondWithManagementNIC(self, host):
        """Returns a list of two PIF UUIDs. The first in the list is the
        management interface and the second is an interface suitable to
        join with the current management NIC in a bond.
        """
        # Assume that the current management NIC is on the default NIC.
        managementPIF = host.parseListForUUID("pif-list",
                                              "management",
                                              "true",
                                              "host-uuid=%s" %
                                              (host.getMyHostUUID()))
        managementNIC = host.genParamGet("pif", managementPIF, "device")
        if managementNIC != host.getDefaultInterface():
            raise xenrt.XRTError("Management interface not initially "
                                 "on default interface")

        # Find another interface on the NPRI network (same as the default NIC)
        assumedids = host.listSecondaryNICs("NPRI")
        if len(assumedids) == 0:
            raise xenrt.XRTError("Could not find a secondary NIC on NPRI")

        # Get the PIF for this interface
        secNIC = host.getSecondaryNIC(assumedids[0])
        secPIF = host.parseListForUUID("pif-list",
                                       "device",
                                       secNIC,
                                       "host-uuid=%s" % (host.getMyHostUUID()))

        return [managementPIF, secPIF]

    def xxxprepare(self, arglist):
        # Only used during testcase development
        old = xenrt.TEC().lookup("OLD_PRODUCT_VERSION")
        oldversion = xenrt.TEC().lookup("OLD_PRODUCT_INPUTDIR")
        h0 = xenrt.lib.xenserver.createHost(id=0,
                                            version=oldversion,
                                            productVersion=old,
                                            withisos=True)
        h1 = xenrt.lib.xenserver.createHost(id=1,
                                            version=oldversion,
                                            productVersion=old,
                                            withisos=False)

        # Now pool the hosts.
        pool = xenrt.lib.xenserver.poolFactory(h0.productVersion)(h0)
        pool.addHost(h1)
        xenrt.TEC().registry.poolPut("mypool", pool)

    def hostsSetup(self):

        h0 = self.hosts[0]
        h1 = self.hosts[1]

        vlans = h0.availableVLANs()
        if len(vlans) < 2:
            xenrt.TEC().skip("Not enough VLANs defined for host")
            return
        vlan, subnet, netmask = vlans[0]
        vlanvm, subnetvm, netmaskvm = vlans[1]

        # Set up a bonded interface on NPRI
        for host in self.hosts:
            newpifs = self.findPIFToBondWithManagementNIC(host)
            (bridge,device) = host.createBond(newpifs,
                                              dhcp=True,
                                              management=True)

            # Give it 20 seconds to do DHCP etc
            time.sleep(20)

            # Check the bond status
            (info,slaves) = host.getBondInfo(device)
            if len(info['slaves']) != 2:
                raise xenrt.XRTFailure("Bond has %u slave devices, expected 2" %
                                       (len(info['slaves'])))

            # Check we can still see the host etc...
            host.check(interfaces=[(bridge, "yes", "dhcp", None, None, None, None, None, None)])

        # Create VLANs
        vbridge = h0.createNetwork()
        vbridgevm = h0.createNetwork()
        self.vmbridge = h0.genParamGet("network", vbridgevm, "bridge")
        for host in self.hosts:
            pif = host.genParamGet("bond", host.getBonds()[0], "master")
            nic = host.genParamGet("pif", pif, "device")

            # VLAN for management
            host.createVLAN(vlan, vbridge, nic)
            host.checkVLAN(vlan, nic)

            # VLAN for VMs
            host.createVLAN(vlanvm, vbridgevm, nic)
            host.checkVLAN(vlanvm, nic)

        # Switch the management interfaces to the first VLAN. Do the slave
        # first.
        oldpif = h1.parseListForUUID("pif-list",
                                     "management",
                                     "true",
                                     "host-uuid=%s" % (h1.getMyHostUUID()))
        newpif = h1.parseListForUUID("pif-list",
                                     "VLAN",
                                     vlan,
                                     "host-uuid=%s" % (h1.getMyHostUUID()))
        cli = h1.getCLIInstance()
        cli.execute("pif-reconfigure-ip uuid=%s mode=dhcp" % (newpif))
        try:
            cli.execute("host-management-reconfigure pif-uuid=%s" % (newpif))
        except:
            pass
        newip = h1.execdom0("xe host-param-get uuid=%s param-name=address" %
                            (h1.getMyHostUUID())).strip()
        if newip == h1.getIP():
            raise xenrt.XRTError("Host address unchanged after reconfigure")
        h1.machine.ipaddr = newip
        cli.execute("pif-reconfigure-ip uuid=%s mode=None" % (oldpif))

        # Designate h1 as the master then perform the VLAN management switch
        # on h0 as the slave.
        h0.pool.designateNewMaster(h1)

        oldpif = h0.parseListForUUID("pif-list",
                                     "management",
                                     "true",
                                     "host-uuid=%s" % (h0.getMyHostUUID()))
        newpif = h0.parseListForUUID("pif-list",
                                     "VLAN",
                                     vlan,
                                     "host-uuid=%s" % (h0.getMyHostUUID()))
        cli = h0.getCLIInstance()
        cli.execute("pif-reconfigure-ip uuid=%s mode=dhcp" % (newpif))
        try:
            cli.execute("host-management-reconfigure pif-uuid=%s" % (newpif))
        except:
            pass
        newip = h0.execdom0("xe host-param-get uuid=%s param-name=address" %
                            (h0.getMyHostUUID())).strip()
        if newip == h0.getIP():
            raise xenrt.XRTError("Host address unchanged after reconfigure")
        h0.machine.ipaddr = newip
        cli.execute("pif-reconfigure-ip uuid=%s mode=None" % (oldpif))

        # Reboot h0 to clean up NFS mounts after the re-ip
        h0.reboot()
        time.sleep(120)

        # Switch back to h0 being master
        h1.pool.designateNewMaster(h0)

        # Reboot h1 to clean up NFS mounts after the re-ip
        h1.reboot()
        time.sleep(120)

    def hostsCheck(self):

        # TODO implement the check below correctly in the near future

        xenrt.TEC().warning("Host check not implemented")

        # Check the bond

        # Check the VLANs

        # Check the management in on the right VLAN

        # Check the VMs are on the right VLAN


class RpuAdvancedNetwork(_RollingPoolUpgrade):
    """Pool rolling upgrade from previous GA version using a bond and VLAN (VM on VLAN on bond, management on bond)."""

    NUMBER_OF_NICS = 2

    def findPIFToBondWithManagementNIC(self, host,numberOfNics=2):
        """Returns a list of two PIF UUIDs. The first in the list is the
        management interface and the second is an interface suitable to
        join with the current management NIC in a bond.
        """
        # Assume that the current management NIC is on the default NIC.
        managementPIF = host.parseListForUUID("pif-list",
                                              "management",
                                              "true",
                                              "host-uuid=%s" %
                                              (host.getMyHostUUID()))
        managementNIC = host.genParamGet("pif", managementPIF, "device")
        if managementNIC != host.getDefaultInterface():
            raise xenrt.XRTError("Management interface not initially "
                                 "on default interface")

        # Find another interface on the NPRI network (same as the default NIC)
        assumedids = host.listSecondaryNICs("NPRI")
        if len(assumedids) < (numberOfNics - 1):
            raise xenrt.XRTError("Could not find secondary NICs on NPRI")

        secPIFs = []
        numberOfNics = numberOfNics - 1
        assumedids = assumedids[0:numberOfNics]
        for id in assumedids:
            secNIC = host.getSecondaryNIC(id)
            secPIFs.append(host.parseListForUUID("pif-list","device",secNIC,"host-uuid=%s" % (host.getMyHostUUID())))

        return [managementPIF] +  secPIFs

    def hostsSetup(self):

        h0 = self.hosts[0]
        h1 = self.hosts[1]

        vlans = h0.availableVLANs()
        if len(vlans) < 1:
            xenrt.TEC().skip("Not enough VLANs defined for host")
            return
        vlanvm, subnetvm, netmaskvm = vlans[0]

        # Set up a bonded interface on NPRI
        bondnet = self.hosts[0].createNetwork()
        for host in self.hosts:
            newpifs = self.findPIFToBondWithManagementNIC(host,numberOfNics=self.NUMBER_OF_NICS)
            (bridge,device) = host.createBond(newpifs,
                                              dhcp=True,
                                              management=True,
                                              network=bondnet)

            # Give it 20 seconds to do DHCP etc
            time.sleep(20)

            # Check the bond status
            (info,slaves) = host.getBondInfo(device)
            if len(info['slaves']) != self.NUMBER_OF_NICS:
                raise xenrt.XRTFailure("Bond has %u slave devices, expected %u" %
                                       (len(info['slaves']),self.NUMBER_OF_NICS))

            # Check we can still see the host etc...
            host.check(interfaces=[(bridge, "yes", "dhcp", None, None, None, None, None, None)])
            # Update i_interfaces so a post upgrade check will work
            host.i_interfaces = [(bridge, "yes", "dhcp", None, None, None, None, None, None)]

        # Create VLAN
        vbridgevm = h0.createNetwork()
        self.vmbridge = h0.genParamGet("network", vbridgevm, "bridge")
        for host in self.hosts:
            pif = host.genParamGet("bond", host.getBonds()[0], "master")
            nic = host.genParamGet("pif", pif, "device")

            # VLAN for VMs
            host.createVLAN(vlanvm, vbridgevm, nic)
            host.checkVLAN(vlanvm, nic)

    def hostsCheck(self):
        pass # function still being implemented
        # Check the bond

        # Check the VLANs

        # Check the management in on the right VLAN

        # Check the VMs are on the right VLAN

class TC8146(RpuAdvancedNetwork):
    """Pool rolling upgrade from previous GA version using a bond and VLAN (VM on VLAN on bond, management on bond)."""


class TC15686(TC8146):
    """Pool rolling upgrade from previous GA version using a bond(3 Nics) and VLAN (VM on VLAN on bond, management on bond)."""

    NUMBER_OF_NICS = 3

class TC15687(TC8146):
    """Pool rolling upgrade from previous GA version using a bond(4 Nics) and VLAN (VM on VLAN on bond, management on bond)."""

    NUMBER_OF_NICS = 4

class TC8765(_RollingPoolUpgrade):
    """Pool rolling upgrade from previous GA version, suspending VMs."""
    SUSPEND = True

class TCRpuBlockedOperations(xenrt.TestCase):

    def prepare(self, arglist):
        # may need to add code here to create the pool
        self.pool = self.getDefaultPool()

        self.upgrader = BlockedOperationsPoolUpgrade(self.pool)

        # code here to create SRs of differnet types
        self.sharedSR = self.pool.getPoolParam("default-SR")

        for host in self.pool.getHosts():
            if isinstance(host, xenrt.lib.xenserver.MNRHost) and not isinstance(host, xenrt.lib.xenserver.TampaHost):
                host.addGuest(host.createBasicGuest(name='local',distro="debian50"))
            else:
                host.addGuest(host.createGenericLinuxGuest(name='local'))
            g = host.getGuest('local')
            g.suspend()

            guestName = 'startresume'+host.getName()
            if isinstance(host, xenrt.lib.xenserver.MNRHost) and not isinstance(host, xenrt.lib.xenserver.TampaHost):
                host.addGuest(host.createBasicGuest(\
                            distro="debian50", sr=self.sharedSR, name=guestName))
            else:
                host.addGuest(host.createGenericLinuxGuest(\
                            sr=self.sharedSR, name=guestName))

            guestName = 'migrate'+host.getName()
            if isinstance(host, xenrt.lib.xenserver.MNRHost) and not isinstance(host, xenrt.lib.xenserver.TampaHost):
                host.addGuest(host.createBasicGuest(\
                            distro="debian50", sr=self.sharedSR, name=guestName))
            else:
                host.addGuest(host.createGenericLinuxGuest(\
                            sr=self.sharedSR, name=guestName))

    def run(self, arglist):
        self.pool.upgrade(poolUpgrade=self.upgrader)




#############################################################################
class BlockedOperationsPoolUpgrade(xenrt.lib.xenserver.host.RollingPoolUpdate):

    def preSlaveUpdate(self, slave):
        # Check RPU mode
        self.newPool.verifyRollingPoolUpgradeInProgress(expected=True)

        # Attempt blocked operations
        upgradedHosts = []
        nonUpgradedHosts = []
        for s in self.newPool.getSlaves():
            if s.productRevision == self.newPool.master.productRevision:
                upgradedHosts.append(s)
            else:
                nonUpgradedHosts.append(s)
        upgradedHosts.append(self.newPool.master)

        xenrt.TEC().logverbose("Upgraded Hosts: %s"\
                             % (map(lambda(x):x.getName(), upgradedHosts)))
        xenrt.TEC().logverbose("Non-Upgraded Hosts: %s"\
                             % (map(lambda(x):x.getName(), nonUpgradedHosts)))

        #  Suspend / Resume, Shutdown / Start on local VM
        g = slave.getGuest('local')
        try:
            g.resume()
            raise xenrt.XRTFailure("VM.resume allowed during RPU.  Slave: %s"\
                                   ", VM : %s" % (slave.getName(), g.getName()))
        except Exception, e:
            xenrt.TEC().logverbose("VM.resume disallowed with reason: %s" %\
                                   (str(e)))

        g.shutdown(force=True)
        try:
            g.start()
            raise xenrt.XRTFailure("VM.start allowed during RPU.  Slave: %s"\
                                   ", VM : %s" % (slave.getName(), g.getName()))
        except Exception, e:
            xenrt.TEC().logverbose("VM.start disallowed with reason: %s" %\
                                   (str(e)))


        #  Suspend / Resume, Shutdown / Start on shared storage VM
        g = slave.getGuest('startresume'+slave.getName())
        if g.getState() != "UP":
            raise xenrt.XRTFailure("VM not in running state.  Slave: %s"\
                                   ", VM : %s" % (slave.getName(), g.getName()))

        g.suspend()
        for upgradedHost in upgradedHosts:
            try:
                xenrt.TEC().logverbose("VM.resume on Upgraded Host: %s"\
                                       % (upgradedHost.getName()))

                operation = "VM.resume"
                g.resume(on=upgradedHost)
                operation = "VM.start"
                g.shutdown()
                g.setHost(upgradedHost)
                g.start(specifyOn=True)
                g.suspend()
            except Exception, e:
                raise xenrt.XRTFailure("%s disallowed on upgraded host "\
                                       "%s with reason: %s" %\
                                 (operation, upgradedHost.getName(), str(e)))


        if g.getState() != "SUSPENDED":
            raise xenrt.XRTFailure("VM not in suspended state.  Slave: %s"\
                                   ", VM : %s" % (slave.getName(), g.getName()))
        for nonUpgradedHost in nonUpgradedHosts:
            try:
                xenrt.TEC().logverbose("VM.resume on non-Upgraded Host: %s"\
                                       % (nonUpgradedHost.getName()))

                g.resume(on=nonUpgradedHost)
                raise xenrt.XRTFailure("VM.resume on non-upgraded Host "\
                                       "allowed during RPU.  Host: %s, VM: %s"\
                                       % (slave.getName(), g.getName()))
            except Exception, e:
                xenrt.TEC().logverbose("VM.resume disallowed with reason: %s" %\
                                       (str(e)))

        g.shutdown(force=True)
        for nonUpgradedHost in nonUpgradedHosts:
            try:
                xenrt.TEC().logverbose("VM.start on non-Upgraded Host: %s"\
                                       % (nonUpgradedHost.getName()))

                g.setHost(nonUpgradedHost)
                g.start(specifyOn=True)
                raise xenrt.XRTFailure("VM.start on non-upgraded Host "\
                                       "allowed during RPU.  Host: %s, VM: %s"\
                                       % (slave.getName(), g.getName()))
            except Exception, e:
                xenrt.TEC().logverbose("VM.start disallowed with reason: %s" %\
                                       (str(e)))


        #  Migrate on shared storage VM
        g = slave.getGuest('migrate'+slave.getName())
        nonUpgradedHosts.remove(slave)
        #  Attempt to migrate to non-upgraded host
        if len(nonUpgradedHosts):
            xenrt.TEC().logverbose("VM.migrate %s to non-Upgraded Host: %s"\
                            % (g.getName(), nonUpgradedHosts[0].getName()))
            try:
                g.migrateVM(nonUpgradedHosts[0], live="true")
            except Exception, e:
                raise xenrt.XRTFailure("VM.migrate to non-upgraded host "\
                                       "failed with reason %s" % (str(e)))

            xenrt.TEC().logverbose("VM.migrate %s from non-Upgraded Host: %s"\
                                % (g.getName(), nonUpgradedHosts[0].getName()))
            try:
                g.migrateVM(slave, live="true")
            except Exception, e:
                raise xenrt.XRTFailure("VM.migrate from non-upgraded host "\
                                       "failed with reason %s" % (str(e)))

        #  Attempt to migrate to upgraded host
        xenrt.TEC().logverbose("VM.migrate %s to Upgraded Host: %s"\
                           % (g.getName(), upgradedHosts[0].getName()))
        try:
            g.migrateVM(upgradedHosts[0], live="true")
        except Exception, e:
            raise xenrt.XRTFailure("VM.migrate to upgraded host failed with"\
                                   "reason %s" % (str(e)))

        xenrt.TEC().logverbose("VM.migrate %s from Upgraded Host: %s"\
                           % (g.getName(), upgradedHosts[0].getName()))
        try:
            g.migrateVM(slave, live="true")
            raise xenrt.XRTFailure("VM.migrate from upgraded host not "\
                                   "disallowed during RPU.")
        except Exception, e:
            xenrt.TEC().logverbose("VM.migrate disallowed with reason: %s" %\
                                   (str(e)))
        # Attempt to create an SR
        try:
            tempSRUUID = slave.createFileSR(10)
            xenrt.TEC().logverbose("SR.create on non-upgraded Host "\
                                   "allowed during RPU.  Host: %s"\
                                   % (slave.getName()))
            slave.destroyFileSR(tempSRUUID)
            raise xenrt.XRTFailure("SR.create not disallowed during RPU.")
        except:
            xenrt.TEC().logverbose("SR Create disallowed with reason: %s" %\
                                   (str(e)))

class _RPUBasic(xenrt.TestCase):

    TEST_SRS = []

    def prepare(self, arglist):
        # may need to add code here to create the pool
        self.pool = self.getDefaultPool()

        # Create some VMs
        for testSR in self.TEST_SRS:
            srUUID = self.pool.master.parseListForUUID("sr-list", "name-label",
                                                       testSR)
            for host in self.pool.getHosts():
                guestName = testSR+host.getName()
                if isinstance(host, xenrt.lib.xenserver.MNRHost) and not isinstance(host, xenrt.lib.xenserver.TampaHost):
                    host.addGuest(host.createBasicGuest(\
                                distro="debian50", sr=srUUID, name=guestName))
                else:
                    host.addGuest(host.createGenericLinuxGuest(\
                                sr=srUUID, name=guestName))

        self.upgrader = xenrt.lib.xenserver.host.RollingPoolUpdate(self.pool)


    def run(self, arglist):
        # perform the upgrade
        self.newPool = self.pool.upgrade(poolUpgrade=self.upgrader)
        self.newPool.verifyRollingPoolUpgradeInProgress(expected=False)

        # Check all VMs are up and running
        for testSR in self.TEST_SRS:
            for host in self.newPool.getHosts():
                guestName = testSR+host.getName()
                vmUUID = self.newPool.master.parseListForUUID("vm-list",
                                                              "name-label",
                                                              guestName)
                state = self.pool.master.minimalList("vm-param-get uuid=%s "\
                        "param-name=power-state" % vmUUID)[0]
                xenrt.TEC().logverbose("VM [%s] in state: %s after RPU "\
                                        % (guestName, state))
                if state != 'running':
                    raise xenrt.XRTFailure("VM not running after RPU")

class TCRpuEql(_RPUBasic):
    TEST_SRS = ['pooliScsi', 'poolEql']

class TCRpuNetApp(_RPUBasic):
    TEST_SRS = ['pooliScsi', 'poolNetApp']

class TCAutoInstaller(xenrt.TestCase):

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        for f in string.split(xenrt.TEC().lookup(["INSTALLER_PATCH", "INSTALLER"]), ","):
            self.host.applyPatch(xenrt.TEC().getFile("xe-phase-1/" + f), returndata=True)

    def run(self, arglist):
        # Check that the image ISO exists
        imageName = xenrt.TEC().lookup("CARBON_CD_IMAGE_NAME", 'main.iso')
        xenrt.TEC().logverbose("Using XS install image name: %s" % (imageName))
        cd = xenrt.TEC().getFile("xe-phase-1/%s" % (imageName), imageName)
        xenrt.checkFileExists(cd)

        # Create a temp directory for the image
        protocol = xenrt.TEC().lookup(["INSTALLER_PATCH", "PROTOCOL"])
        xenrt.TEC().logverbose("Installer protocol: %s" % (protocol))
        if protocol == "NFS":
            imageDir = xenrt.NFSDirectory()
        elif protocol == "HTTP":
            imageDir = xenrt.WebDirectory()
        elif protocol == "FTP":
            imageDir = xenrt.FTPDirectory()
            imageDir.setUsernameAndPassword('xenrtd', 'xensource')
        else:
            raise xenrt.XRTFailure("Protocol not recognised: %s" %\
                                   (protocol))

        xenrt.TEC().logverbose("Using ISO %s" % (cd))
        mount = xenrt.MountISO(cd)
        mountpoint = mount.getMount()

        xenrt.TEC().logverbose("Verify that an attempt to install from an empty directory fails")
        self.callCheckAndInstall(imageLocation=imageDir.getURL(""),
                                 expectedToSucceed=False)

        xenrt.TEC().logverbose("Verify that an attempt to install from a directory that contain only a subset of the required files fails")
        imageDir.copyIn("%s/install.img" % (mountpoint))
        imageDir.copyIn("%s/packages.*" % (mountpoint))
        imageDir.copyIn("%s/XS-REPOSITORY-LIST" % (mountpoint))
        self.callCheckAndInstall(imageLocation=imageDir.getURL(""),
                                 expectedToSucceed=False)

        xenrt.TEC().logverbose("Verify that an attempt to install from a directory that contain all the required files is successful")
        imageDir.copyIn("%s/boot" % (mountpoint))
        mount.unmount()

        self.callCheckAndInstall(imageLocation=imageDir.getURL(""))
        # Verify the actual install
        self.host.reboot(timeout=1800)

        self.host.checkVersion()
        
        if self.host.productVersion == "Sanibel" and xenrt.TEC().lookup("PRODUCT_VERSION") == "Boston":
            # this is OK...if you put Boston in the sequence...you'll get Sanibel as the host product version
            return
        
        if self.host.productVersion != xenrt.TEC().lookup("PRODUCT_VERSION"):
            raise xenrt.XRTFailure("Host Product Version (%s) doesn't match test Product Version (%s)" % (self.host.productVersion, xenrt.TEC().lookup("PRODUCT_VERSION")))

    def callCheckAndInstall(self, imageLocation, expectedToSucceed=True):
        xenrt.TEC().logverbose("Image Location: %s" % (imageLocation))

        # Perform the testUrl function
        self.command = "host-call-plugin plugin=prepare_host_upgrade.py "\
                        "host-uuid=%s fn=%s args:url=%s" \
            % (self.host.getMyHostUUID(), "testUrl", imageLocation)
        cli = self.host.getCLIInstance()

        try:
            result = cli.execute(self.command, strip=True)
            succeeded = True
        except Exception, e:
            result = str(e)
            succeeded = False
        xenrt.TEC().logverbose("Response from installer plugin: %s" % (result))
        if succeeded != expectedToSucceed:
            raise xenrt.XRTFailure("Unexpected response from installer plugin")

        # Perform the install function
        self.command = "host-call-plugin plugin=prepare_host_upgrade.py "\
                        "host-uuid=%s fn=%s args:url=%s" \
            % (self.host.getMyHostUUID(), "main", imageLocation)
        try:
            result = cli.execute(self.command, strip=True)
            succeeded = True
        except Exception, e:
            result = str(e)
            succeeded = False
        xenrt.TEC().logverbose("Response from installer plugin: %s" % (result))
        if succeeded != expectedToSucceed:
            raise xenrt.XRTFailure("Unexpected response from installer plugin")

class TC8231(_NonRollingPoolUpgrade):
    """Pool non-rolling upgrade from previous GA version using Equallogic SR."""
    pass

class _SingleHostUpgrade(xenrt.TestCase):

    USE_EXISTING_HOST = False
    NO_VMS = False
    EXTRASUBCASES = []
    SAFE2UPGRAGE_CHECK = False

    def installVMs(self):
        if isinstance(self.host, xenrt.lib.xenserver.MNRHost) and not isinstance(self.host, xenrt.lib.xenserver.TampaHost):
            g = self.host.createBasicGuest(distro="debian50")
        else:
            g = self.host.createGenericLinuxGuest()
        g.shutdown()
        self.guests.append(g)

    def upgrade(self, newVersion):
        self.host.tailored = False
        xenrt.lib.xenserver.cli.clearCacheFor(self.host.machine)
        self.host = self.host.upgrade(newVersion)
        time.sleep(180)
        self.host.check()
        if len(self.host.listGuests()) == 0 and not self.NO_VMS:
            raise xenrt.XRTFailure("VMs missing after host upgrade")
    
    def installOld(self):
        old = xenrt.TEC().lookup("OLD_PRODUCT_VERSION")
        oldversion = xenrt.TEC().lookup("OLD_PRODUCT_INPUTDIR")
        self.host = xenrt.lib.xenserver.createHost(id=0,
                                                   version=oldversion,
                                                   productVersion=old)
    
    def upgradeVMs(self):
        for g in self.guests:
            xenrt.TEC().progress("Upgrading VM %s" % (g.getName()))
            g.start()
            if g.windows:
                g.installDrivers()
            else:
                # Workaround for CA-78632
                xenrt.TEC().logverbose("CA-78632 class %s template: %s" % (self.host.__class__, g.template))
                if re.search("Lenny", g.template) and isinstance(self.host, xenrt.lib.xenserver.TampaHost):
                    xenrt.TEC().logverbose("Skipping tools upgrade on %s" % (g.getName()))
                else:
                    g.installTools()
            g.check()

    def checkVMs(self):
        for g in self.guests:
            xenrt.TEC().progress("Checking VM %s" % (g.getName()))
            g.suspend()
            g.resume()
            g.check()
            g.suspend()
            g.resume()
            g.check()
            g.reboot()
            g.shutdown()
            g.start()
            g.check()

    def run(self, arglist):
        self.guests = []
        if not self.USE_EXISTING_HOST:
            # Install a host with the old product build
            if self.runSubcase("installOld", (), "PrevGA", "Install") != \
                   xenrt.RESULT_PASS:
                return
        else:
            self.host = self.getDefaultHost()
        self.hosts = [self.host]
        self.getLogsFrom(self.host)
        if not self.NO_VMS:
            if self.runSubcase("installVMs", (), "PrevGA", "InstallVMs") != \
                   xenrt.RESULT_PASS:
                return

        if self.SAFE2UPGRAGE_CHECK:
            self.NEW_PARTITIONS = self.host.checkSafe2Upgrade() or self.NEW_PARTITIONS

        # Upgrade the host and VMs
        upgsteps = []

        # Perform any intermediate upgrades. This happens if the
        # UPGRADE_TC_VIA contains a comma-separated list of versions.
        # All referenced versions should also have a PIDIR_<version>
        # variable for the input dir for that version (<version> in
        # upper case)
        vias = xenrt.TEC().lookup("UPGRADE_TC_VIA", None)
        if vias:
            viavers = vias.split(",")
            for v in viavers:
                inputdir = xenrt.TEC().lookup(\
                    "PRODUCT_INPUTDIR_%s" % (v.replace(" ", "").upper()), None)
                if not inputdir:
                    inputdir = xenrt.TEC().lookup(\
                        "PIDIR_%s" % (v.replace(" ", "").upper()), None)
                if not inputdir:
                    raise xenrt.XRTError("No product input directory set for "
                                         "%s" % (v))
                upgsteps.append((v, inputdir))

        # Finally upgrade to the current version under test
        upgsteps.append((xenrt.TEC().lookup("PRODUCT_VERSION"), None))
        for upgstep in upgsteps:
            toversion, inputs = upgstep
            xenrt.TEC().setInputDir(inputs)
            if self.runSubcase("upgrade",
                               (toversion),
                               toversion,
                               "HostUpg") != \
                   xenrt.RESULT_PASS:
                return
            if not self.NO_VMS:
                if self.runSubcase("upgradeVMs", (), toversion, "VMUpg") != \
                       xenrt.RESULT_PASS:
                    return
                if self.runSubcase("checkVMs", (), toversion, "VMCheck") != \
                       xenrt.RESULT_PASS:
                    return

        # Testcase specific post-upgrade tests (done after all upgrades
        # if a multi-step upgrade is being performed)
        for e in self.EXTRASUBCASES:
            if self.runSubcase(e[0], e[1], e[2], e[3]) != xenrt.RESULT_PASS:
                return


class TCUpgradeMultipathedRootDisk(_SingleHostUpgrade):

    """
    Upgrade a machine with a multipathed root disk after switching this feature off
    Apply a kernel hotfix and check what happens to the multipathing config
    See SCTX-1822
    """

    NO_VMS = True
    EXTRASUBCASES = [("fakeKernelHotfix", (), "Fake", "Kernel Hotfix"),
                     ("checkMPIsOn", (), "Check", "Multipath status")]

    def installOld(self):
        old = xenrt.TEC().lookup("OLD_PRODUCT_VERSION")
        oldversion = xenrt.TEC().lookup("OLD_PRODUCT_INPUTDIR")
        self.host = xenrt.lib.xenserver.createHost(id=0,
                                                   version=oldversion,
                                                   productVersion=old,
                                                   installSRType="lvm")
        self.checkMPIsOn()
        step("Disabling root disk multipathing...")
        self.host.disableMultipathingInKernel()

        #MP should be off here
        self.checkMPIsOn(False)

    def fakeKernelHotfix(self):
        step("Faking a kernel hotifx by rebuilding initrd...")
        self.getDefaultHost().rebuildInitrd()
        self.getDefaultHost().reboot()

    def checkMPIsOn(self, expectedOn=True):
        step("Checking the state of multipathing...")
        log(self.getDefaultHost().getMultipathInfo())
        mpOn = len(self.getDefaultHost().getMultipathInfo()) >= 1

        if mpOn != expectedOn:
            raise xenrt.XRTError(
                "Multipathing fail actual={0} and exepcted={1}".format(mpOn,expectedOn))


class TC6929(_SingleHostUpgrade):
    """Single host upgrade from previous release using static IP addressing and a local LVM SR"""

    def installOld(self):
        old = xenrt.TEC().lookup("OLD_PRODUCT_VERSION")
        oldversion = xenrt.TEC().lookup("OLD_PRODUCT_INPUTDIR")
        self.host = xenrt.lib.xenserver.createHost(id=0,
                                                   version=oldversion,
                                                   productVersion=old,
                                                   dhcp=False,
                                                   installSRType="lvm")

class TC6725(_SingleHostUpgrade):
    """Single host upgrade from previous release using dynamic IP addressing and a local VHD SR"""

    def installOld(self):
        old = xenrt.TEC().lookup("OLD_PRODUCT_VERSION")
        oldversion = xenrt.TEC().lookup("OLD_PRODUCT_INPUTDIR")
        self.host = xenrt.lib.xenserver.createHost(id=0,
                                                   version=oldversion,
                                                   productVersion=old,
                                                   installSRType="ext")

class TC14898(TC6725):
    """Single host upgrade from Cowley on HP G6 hardware"""
    pass

class _XenCert(object):
    """Uses the XenCert SR regression test in dom0 maintained by the storage team."""

    def runXenCertiCSLG(self,host,adapterid,comment="",sr=None):
        if xenrt.TEC().lookup("SKIP_XENCERT", False, boolean=True):
            xenrt.TEC().warning("Skipping XenCert due to SKIP_XENCERT flag")
            return
        CSLG_SRTYPE="cslg"
        if not sr:
            sr = host.lookupDefaultSR()
        xenrt.TEC().logverbose("default SR=%s" % sr)
        sr_type=host.genParamGet("sr",sr,"type")
        if sr_type != CSLG_SRTYPE:
            raise xenrt.XRTFailure("Expected cslg SR, obtained [%s]" % sr_type)
        sr_name=host.genParamGet("sr",sr,"name-label")
        pool = self.getDefaultPool()
        res = pool.master.srs[sr_name].resources["target"]

        pbds = host.minimalList("pbd-list",args="sr-uuid=%s" % (sr))
        if len(pbds) < 1:
            raise xenrt.XRTFailure("Expecting at least one PBD for SR %s: PBDs=[%s]" % (sr,pbds))
        pbd = pbds[0]
        pbd_dc = host.genParamsGet("pbd",pbd,"device-config")
        xenrt.TEC().logverbose("PBD=%s"%pbd_dc)
        pbd_ssid = pbd_dc['storageSystemId']
        pbd_spid = pbd_dc['storagePoolId']
        pbd_target = pbd_dc['target']
        pbd_protocol = pbd_dc['protocol']
        sr_username=res.getUsername()
        sr_password=res.getPassword()
        sr_name=res.getName()
        xccfg = "/tmp/xencert_isl.conf"
        if host.execdom0("test -e /opt/xensource/debug/XenCert/XenCert", retval="code") != 0:
            supp = xenrt.TEC().getFile("xe-phase-2/xencert-supp-pack.iso")
            sh = host.sftpClient()
            try:
                sh.copyTo(supp, "/tmp/xencert.iso")
            finally:
                sh.close()

            host.execdom0("xe-install-supplemental-pack /tmp/xencert.iso")

        xccmd = "/usr/bin/python -u /opt/xensource/debug/XenCert/XenCert -F '%s' -b isl -f -c -o" % xccfg
        isl_conf="""<?xml version="1.0" encoding="utf-8"?>
<configParamters>
    <comment>This array is %s</comment>
    <adapterid>%s</adapterid>
    <ssid>%s</ssid>
    <spid>%s</spid>
    <target>%s</target>
    <port>0</port>
    <username>%s</username>
    <password>%s</password>
    <protocol>%s</protocol>
    <chapuser></chapuser>
    <chappass></chappass>
    <lunsize>134217728</lunsize>
    <growsize>4194304</growsize>
</configParamters>
""" % (sr_name,adapterid,pbd_ssid,pbd_spid,pbd_target,sr_username,sr_password, pbd_protocol)
        xenrt.TEC().logverbose("Running XenCert SR Test Plan...%s" % comment)
        if host.execdom0("echo '%s'>%s" % (isl_conf,xccfg),retval="code") !=0:
            raise xenrt.XRTFailure("Could not copy XenCert config file to %s" % xccfg)
        if host.execdom0(xccmd,retval="code",timeout=3600) != 0:
            # obtain the resulting XenCert logs
            xclogs = host.execdom0("ls -t1 /tmp/XenCert-*").splitlines()
            if len(xclogs) > 0:
                host.addExtraLogFile(xclogs[0]) #grab the most recent log in dom0
            raise xenrt.XRTFailure("XenCert SR Test Suite FAILED -- see /var/log/SMlog")

class TCXenCert(_XenCert,xenrt.TestCase):
    """A TC for the XenCert SR regression test in dom0 maintained by the storage team."""

    def __init__(self, tcid="TC-13236", host=None, adapterid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.host = host
        self.adapterid = adapterid
        self.srtype = None
        self.createsr = False
        self.sr = None

        self.adapterid = "NETAPP"
        self.srtype = "icslg"
        self.createsr = True


    def createSR(self):
        if self.srtype == "icslg":
            if self.adapterid == "NETAPP":
                minsize = int(self.host.lookup("SR_NETAPP_MINSIZE", 40))
                maxsize = int(self.host.lookup("SR_NETAPP_MAXSIZE", 1000000))
                self.target = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
                self.sr = xenrt.lib.xenserver.IntegratedCVSMStorageRepository(self.host,"CVSMSR")
                self.sr.resources["target"] = self.target
                self.sr.create(self.target,
                               protocol="iscsi",
                               physical_size=None)
                self.host.addSR(self.sr, default=True)
            elif self.adapterid == "NETAPP_FC":
                self.adapterid = "NETAPP"
                self.target = xenrt.FCHBATarget()
                self.sr = xenrt.lib.xenserver.IntegratedCVSMStorageRepository(self.host,"CVSMSR")
                self.sr.resources["target"] = self.target
                self.sr.create(self.target,
                               protocol="fc",
                               physical_size=None)
                self.host.addSR(self.sr, default=True)
            elif self.adapterid == "DELL_EQUALLOGIC":
                minsize = int(self.host.lookup("SR_EQL_MINSIZE", 40))
                maxsize = int(self.host.lookup("SR_EQL_MAXSIZE", 1000000))
                self.target = xenrt.EQLTarget(minsize=minsize, maxsize=maxsize)
                self.sr = xenrt.lib.xenserver.IntegratedCVSMStorageRepository(self.host,"CVSMSR")
                self.sr.resources["target"] = self.target
                self.sr.create(self.target,
                               protocol="iscsi",
                               physical_size=None)
                self.host.addSR(self.sr, default=True)
            elif self.adapterid == "EMC_CLARIION_ISCSI":
                self.adapterid = "EMC_CLARIION"
                minsize = int(self.host.lookup("SR_SMIS_ISCSI_MINSIZE", 40))
                maxsize = int(self.host.lookup("SR_SMIS_ISCSI_MAXSIZE", 1000000))
                self.target = xenrt.SMISiSCSITarget()
                self.sr = xenrt.lib.xenserver.IntegratedCVSMStorageRepository(self.host,"CVSMSR")
                self.sr.resources["target"] = self.target
                self.sr.create(self.target,
                               protocol="iscsi",
                               physical_size=None)
                self.host.addSR(self.sr, default=True)
            elif self.adapterid == "EMC_CLARIION_FC":
                self.adapterid = "EMC_CLARIION"
                minsize = int(self.host.lookup("SR_SMIS_FC_MINSIZE", 40))
                maxsize = int(self.host.lookup("SR_SMIS_FC_MAXSIZE", 1000000))
                self.target = xenrt.SMISFCTarget()
                self.sr = xenrt.lib.xenserver.IntegratedCVSMStorageRepository(self.host,"CVSMSR")
                self.sr.resources["target"] = self.target
                self.sr.create(self.target,
                               protocol="fc",
                               physical_size=None)
                self.host.addSR(self.sr, default=True)
            else:
                raise xenrt.XRTError("unimplemented adapterid %s" % self.adapterid)
        else:
            raise xenrt.XRTError("unimplemented srtype %s" % self.srtype)

    def prepare(self, arglist=None):
        machine = "RESOURCE_HOST_0"
        for arg in arglist[1:]:
            l = string.split(arg, "=", 1)
            if l[0] == "srtype":
                self.srtype = l[1]
            if l[0] == "adapterid":
                self.adapterid = l[1]
            if l[0] == "createsr":
                self.createsr = (l[1]=="yes")
            if l[0] == "host":
                machine = l[1]
            if l[0] == "tcid":
                self._rename(l[1])
        host = self.getDefaultHost()
        if not host:
            host = xenrt.TEC().registry.hostGet(machine)
            if not host:
                raise xenrt.XRTError("Unable to find host %s in registry." % (machine))
        self.host = host
        if self.createsr:
            self.createSR()

    def run(self, arglist=None):
        self.getLogsFrom(self.host)
        if self.srtype == "icslg":
            self.runXenCertiCSLG(self.host, self.adapterid, sr=self.sr.uuid)
        else:
            xenrt.XRTError("unimplemented srtype %s" % self.srtype)

    def destroySR(self):
        self.sr.destroy()
        self.sr.check()
        self.sr = None

    def postRun(self):
        self.destroySR()
        try: self.target.release()
        except: pass
        try:
            if self.sr:
                self.sr.remove()
        except: pass

class _ICSLGNetAppHostUpgrade(_XenCert):
    """Host upgrade from previous release using CVSM NetApp to a release using integrated CVSM NetApp SR"""

    USE_EXISTING_HOST = True
    POSTUPG_CHECKS = [("checkSR", (), "Check", "SR")]
    SRTYPE = "cslg"
    CSLG_ADAPTERID = "NETAPP"
    #NO_VMS = True
    upghosts = 0

    def __init__(self):
        self.hosts = []

    def testprepare(self, arglist):
        if self.USE_EXISTING_HOST:
            self.host = self.getDefaultHost()
        minsize = int(self.host.lookup("SR_NETAPP_MINSIZE", 40))
        maxsize = int(self.host.lookup("SR_NETAPP_MAXSIZE", 1000000))
        netapp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
        sr = xenrt.lib.xenserver.IntegratedCVSMStorageRepository(self.host,"CVSMSR")
        sr.resources["target"] = netapp
        self.host.addSR(sr)
        self.runXenCertiCSLG(self.host,self.CSLG_ADAPTERID,"(DURING TESTPREPARE)")

    def checkSR(self):
        xenrt.TEC().logverbose("Just upgraded host %d of %d" % (self.upghosts,len(self.hosts)))
        if self.upghosts == len(self.hosts):
            #run a bunch of VDI(VM?)-level ops to make sure everything continues to work.
            #run XenCert SR Test Plan after the upgrade
            self.runXenCertiCSLG(self.host,self.CSLG_ADAPTERID,"(AFTER THE UPGRADE)")
        else:
            xenrt.TEC().logverbose("Skipping XenCert until after upgrade of the last host of the pool")

    def _upgrade(self, newVersion):
        raise xenrt.XRTFailure("not implemented")

    def upgrade(self, newVersion):
        #run a bunch of VDI(VM?)-level ops to make sure everything works.

        if len(self.hosts) > 1: # pool upgrade case
            hostid = newVersion
            self.host = self.hosts[hostid]

        self.upghosts+=1

        dsr0 = self.host.lookupDefaultSR()
        xenrt.TEC().logverbose("default SR=%s" % dsr0)
        dsr0_type=self.host.genParamGet("sr",dsr0,"type")
        if dsr0_type != self.SRTYPE: #'cslg'
            raise xenrt.XRTFailure("Expected cslg SR, obtained [%s]" % dsr0_type)
        dsr0_name=self.host.genParamGet("sr",dsr0,"name-label")
        pool = self.getDefaultPool()
        res0 = pool.master.srs[dsr0_name].resources["target"]
        dsr0_username=res0.getUsername()
        dsr0_password=res0.getPassword()
        dsr0_target=res0.getTarget()

        # upgrade the host
        self._upgrade(newVersion)

        # re-plug PBD of the cslg-netapp SR
        xenrt.TEC().logverbose("===RE-PLUGGING PBD OF THE CSLG-NETAPP SR FOR THIS HOST===")
        dsr = self.host.lookupDefaultSR()
        # check if it is a cslg sr with NETAPP subtype
        type=self.host.genParamGet("sr",dsr,"type")
        if type != self.SRTYPE: #'cslg'
            raise xenrt.XRTFailure("Expected cslg SR, obtained [%s]" % type)
        pbds = self.host.minimalList("pbd-list",args="sr-uuid=%s host-uuid=%s" % (dsr, self.host.getMyHostUUID()))
        if len(pbds) != 1:
            raise xenrt.XRTFailure("Expecting only one PBD for SR %s: PBDs=[%s]" % (dsr,pbds))
        old_pbd = pbds[0]
        old_pbd_dc = self.host.genParamsGet("pbd",old_pbd,"device-config")
        old_pbd_ssid = old_pbd_dc['storageSystemId']
        old_pbd_spid = old_pbd_dc['storagePoolId']
        old_pbd_protocol = old_pbd_dc['protocol']
        old_pbd_target = old_pbd_dc['target']

        old_pbd_adapterid = old_pbd_ssid
        if not re.search(self.CSLG_ADAPTERID, old_pbd_adapterid):
            raise xenrt.XRTFailure("Expecting [%s] in cslg adapterid=[%s]" % (self.CSLG_ADAPTERID,old_pbd_adapterid))

        cli = self.host.getCLIInstance()
        cli.execute("pbd-unplug","uuid=%s" % old_pbd)
        cli.execute("pbd-destroy","uuid=%s" % old_pbd)

        new_pbd_dconf={"username":dsr0_username,
            "password":dsr0_password,
            "target":dsr0_target,
            "adapterid":self.CSLG_ADAPTERID, #'NETAPP'
            "storageSystemId":old_pbd_ssid,
            "storagePoolId":old_pbd_spid,
            "protocol":old_pbd_protocol
            }
        args = []
        args.append("host-uuid=%s" % (self.host.getMyHostUUID()))
        args.append("sr-uuid=%s" % (dsr))
        args.extend(["device-config:%s=\"%s\"" % (x, y)
                         for x,y in new_pbd_dconf.items()])
        new_pbd = cli.execute("pbd-create", string.join(args)).strip()
        cli.execute("pbd-plug", "uuid=%s" % (new_pbd))

        # Testcase specific post-upgrade tests
        for e in self.POSTUPG_CHECKS:
            if self.runSubcase(e[0], e[1], e[2], e[3]) != xenrt.RESULT_PASS:
                return

class TC12698(_ICSLGNetAppHostUpgrade,_SingleHostUpgrade):
    """Single host upgrade from previous release using dynamic IP addressing and CVSM NetApp SR"""

    def __init__(self, tcid=None):
        _ICSLGNetAppHostUpgrade.__init__(self)
        _SingleHostUpgrade.__init__(self, tcid)

    def _upgrade(self, newVersion):
        _SingleHostUpgrade.upgrade(self, newVersion)

class TC12699(_ICSLGNetAppHostUpgrade,_RollingPoolUpgrade):
    """Pool rolling upgrade from previous GA version using CVSM NetApp SR."""

    def __init__(self, tcid=None):
        _ICSLGNetAppHostUpgrade.__init__(self)
        _SingleHostUpgrade.__init__(self, tcid)

    def _upgrade(self, newVersion):
        _RollingPoolUpgrade.upgrade(self, newVersion)

class TCCSLGNetAppNoUpgrade(_XenCert,_RollingPoolUpgrade):
    """Equivalent to TC-12699 without actually doing rolling upgrade"""

    CSLG_ADAPTERID = None

    def __init__(self, tcid=None):
        _RollingPoolUpgrade.__init__(self, tcid)
        self.host = None

    def run(self, arglist):
        self.hosts = []
        self.hosts.append(self.getHost("RESOURCE_HOST_0"))
        self.hosts.append(self.getHost("RESOURCE_HOST_1"))
        self.hostNames = self.hosts[0].minimalList("host-list", "name-label")
        self.hostNames.sort()
        self.vmbridge = None
        self.suspendedGuests = {}

        # Install a selection of VMs on the pool
        if self.runSubcase("installVMs", (), "PrevGA", "VMInstalls") != \
                xenrt.RESULT_PASS:
            return

        # Perform some random operations including the addition of virtual
        # devices
        if self.runSubcase("randomOps", (), "PrevGA", "VMOps") != \
                xenrt.RESULT_PASS:
            return

        # Eject CDs from VMs before starting pool upgrade (required by
        # installation guide).
        if self.runSubcase("ejectCDs", (), "PrevGA", "EjectCDs") != \
                xenrt.RESULT_PASS:
            return

        # Start workloads on the VMs
        if self.WORKLOADS:
            if self.runSubcase("startWorkloads", (), "PrevGA", "StartWork") != \
                   xenrt.RESULT_PASS:
                return

        if self.SUSPEND:
            # Suspend VMs on the master
            if self.runSubcase("suspend", (0), "Step1", "Suspend") != \
                    xenrt.RESULT_PASS:
                return
        else:
            # Migrate VMs from the master to the slave
            if self.runSubcase("migrate", (0, 1, True), "Step1", "XenMotion") != \
                    xenrt.RESULT_PASS:
                return

        # Verify the pool has returned to normal mode
        if self.runSubcase("poolCheck", (), "Step1", "Verify") != \
                xenrt.RESULT_PASS:
            return

        if self.SUSPEND:
            # Resume VMs on the master
            if self.runSubcase("resume", (0), "Step2", "Resume") != \
                xenrt.RESULT_PASS:
                return
            # Suspend VMs on the slave
            if self.runSubcase("suspend", (1), "Step2", "Suspend") != \
                xenrt.RESULT_PASS:
                return
        else:
            # Migrate VMs from the slave to the master
            if self.runSubcase("migrate", (1, 0, True), "Step2", "XenMotion") != \
                    xenrt.RESULT_PASS:
                return

        # This is where we would have upgraded the slave and hence executed:
        self.runXenCertiCSLG(self.host,self.CSLG_ADAPTERID,"(AFTER THE UPGRADE)")

        # Verify the pool has returned to normal mode
        if self.runSubcase("poolCheck", (), "Step2", "Verify") != \
                xenrt.RESULT_PASS:
            return

        if self.SUSPEND:
            # Resume VMs on the slave
            if self.runSubcase("resume", (1), "Step3", "Resume") != \
                xenrt.RESULT_PASS:
                return
        else:
            # Migrate some VMs back to the slave
            if self.runSubcase("migrate", (0, 1, False), "Step3", "XenMotion") != \
                    xenrt.RESULT_PASS:
                return

        # Perform testcase-specific host config checks
        if self.runSubcase("hostsCheck", (), "Step3", "HostsCheck") != \
                xenrt.RESULT_PASS:
            return

        # Very all VMs are operating normally
        if self.runSubcase("vmCheck1", (), "Step3", "Verify") != \
                xenrt.RESULT_PASS:
            return


class TC12700(_ICSLGNetAppHostUpgrade,_NonRollingPoolUpgrade):
    """Pool non-rolling upgrade from previous GA version, using CVSM NetApp SR."""

    def __init__(self, tcid=None):
        _ICSLGNetAppHostUpgrade.__init__(self)
        _NonRollingPoolUpgrade.__init__(self, tcid)

    def _upgrade(self, newVersion):
        _NonRollingPoolUpgrade.upgrade(self, newVersion)


class _ICSLGEqualLogicHostUpgrade(_ICSLGNetAppHostUpgrade):
    """Host upgrade from previous release using CVSM EqualLogic to a release using integrated CVSM EqualLogic SR"""
    CSLG_ADAPTERID = "DELL_EQUALLOGIC"

class TC13998(_ICSLGEqualLogicHostUpgrade,_SingleHostUpgrade):
    """Single host upgrade from previous release using dynamic IP addressing and CVSM EqualLogic SR"""
    def _upgrade(self, newVersion):
        _SingleHostUpgrade.upgrade(self, newVersion)

class TC13999(_ICSLGEqualLogicHostUpgrade,_RollingPoolUpgrade):
    """Pool rolling upgrade from previous GA version using CVSM EqualLogic SR."""
    def _upgrade(self, newVersion):
        _RollingPoolUpgrade.upgrade(self, newVersion)

class TC14000(_ICSLGEqualLogicHostUpgrade,_NonRollingPoolUpgrade):
    """Pool non-rolling upgrade from previous GA version, using CVSM EqualLogic SR."""
    def _upgrade(self, newVersion):
        _NonRollingPoolUpgrade.upgrade(self, newVersion)


class _ICSLGSMISHostUpgrade(_ICSLGNetAppHostUpgrade):
    """Host upgrade from previous release using CVSM SMI-S to a release using integrated CVSM SMI-S SR"""
    CSLG_ADAPTERID = "EMC_CLARIION"

class TC14925(_ICSLGSMISHostUpgrade,_SingleHostUpgrade):
    """Single host upgrade from previous release using dynamic IP addressing and CVSM SMI-S SR"""
    def _upgrade(self, newVersion):
        _SingleHostUpgrade.upgrade(self, newVersion)

class TC14928(_ICSLGSMISHostUpgrade,_RollingPoolUpgrade):
    """Pool rolling upgrade from previous GA version using CVSM SMI-S SR."""
    def _upgrade(self, newVersion):
        _RollingPoolUpgrade.upgrade(self, newVersion)

class TC14929(_ICSLGSMISHostUpgrade,_NonRollingPoolUpgrade):
    """Pool non-rolling upgrade from previous GA version, using CVSM SMI-S SR."""
    def _upgrade(self, newVersion):
        _NonRollingPoolUpgrade.upgrade(self, newVersion)


class TC8667(_SingleHostUpgrade):
    """A legacy mode SR on a host that is upgraded remains in legacy mode"""

    NO_VMS = True
    USE_EXISTING_HOST = True
    EXTRASUBCASES = [("checkSR", (), "Check", "SR")]
    SRTYPE = "lvm"

    def prepare(self, arglist):
        _SingleHostUpgrade.prepare(self, arglist)
        xenrt.TEC().setThreadLocalVariable("AUTO_UPGRADE_SRS",
                                           False,
                                           fallbackToGlobal=True)

    def checkSR(self):
        srs = self.host.getSRs(type=self.SRTYPE)
        if not srs:
            raise xenrt.XRTError("No %s SR found on host." % (self.SRTYPE))
        sr = srs[0]
        try:
            v = self.host.genParamGet("sr", sr, "sm-config", "use_vhd")
        except:
            pass
        else:
            raise xenrt.XRTFailure("sm-config:use_vhd set on non-upgraded "
                                   "legacy SR")

class TC9353(_SingleHostUpgrade):
    """Single host upgrade from previous release of a server with a boot disk on a SAN via an Emulex HBA"""

    USE_EXISTING_HOST = True

class TC12701(_SingleHostUpgrade):
    """Test to check RHEL3.8 guests from P2V George upgrade OK to MNR - SCTX-533, CA-48772"""

    EXTRASUBCASES = [("checkGuest", (), "Check", "Guest")]

    def installOld(self):
        old = xenrt.TEC().lookup("OLD_PRODUCT_VERSION")
        oldversion = xenrt.TEC().lookup("OLD_PRODUCT_INPUTDIR")
        self.host = xenrt.lib.xenserver.createHost(id=1, version=oldversion, productVersion=old)

        # Install native Linux on the P2V host
        mname = xenrt.TEC().lookup("RESOURCE_HOST_0")
        m = xenrt.PhysicalHost(mname)
        xenrt.GEC().startLogger(m)
        self.p2vhost = xenrt.lib.native.NativeLinuxHost(m)
        self.getLogsFrom(self.p2vhost)
        self.p2vhost.installLinuxVendor("rhel38")

        imageName = xenrt.TEC().lookup("CARBON_CD_IMAGE_NAME", 'main.iso')
        xenrt.TEC().logverbose("Using XS install image name: %s" % (imageName))
        cd = xenrt.TEC().getFile(oldversion + "/" + imageName, imageName)
        self.guest = self.host.p2v(xenrt.randomGuestName(), "rhel38", self.p2vhost, cd)

    def checkGuest(self):
        # need to check that the guest is responsive.
        self.guest.checkHealth()
        self.host.checkHealth()

        if self.guest.getState() != "UP":
            self.guest.start()

        # need to check that netback cpu usage is below 10%

        for i in range(100):
            time.sleep(1)
            top = self.host.execdom0("top -b -n 1|grep netback")

            procs = re.findall("(\d+.\d+)  \d+.\d+   \d+:\d+.\d+ netback", top)

            if not procs or len(procs) == 0:
                raise xenrt.XRTError("Could not find netback in top")

            for proc in procs:

                if float(proc) > 10:
                    raise xenrt.XRTError("netback using %s%% CPU" % proc)

class TC12058(_SingleHostUpgrade):
    """An upgrade of pre-Cowley to Cowley should retain its preference of multipath driver: MPP RDAC"""

    USE_EXISTING_HOST = True
    NO_VMS = True
    EXTRASUBCASES = [("checkSR", (), "Check", "SR")]
    MPP_RDAC = True

    def prepare(self, arglist):
        _SingleHostUpgrade.prepare(self, arglist)

        old = xenrt.TEC().lookup("OLD_PRODUCT_VERSION")
        oldversion = xenrt.TEC().lookup("OLD_PRODUCT_INPUTDIR")
        self.host = xenrt.lib.xenserver.createHost(id=0,
                                                   version=oldversion,
                                                   productVersion=old)
        self.initiator = xenrt.TEC().lookup(["ISCSI_LUNS", "MD3000i", "INITIATOR_NAME"]) % 1
        self.targetiqn = xenrt.TEC().lookup(["ISCSI_LUNS", "MD3000i", "TARGET_NAME"])
        self.targetip = xenrt.TEC().lookup(["ISCSI_LUNS", "MD3000i", "SERVER_ADDRESS"])

        # Set up secondary NIC
        h0nsecaids = self.host.listSecondaryNICs("NSEC")
        if len(h0nsecaids) == 0:
            raise xenrt.XRTError("Could not find a NSEC interface on host %s" %
                                 (self.host.getName()))
        self.host.setIPAddressOnSecondaryInterface(h0nsecaids[0])

        # Setup to use MPP RDAC or dm_multipath
        f = self.host.execdom0('cat /etc/mpp.conf')
        mppconf = dict(x.split('=') for x in f.strip().split('\n'))
        if self.MPP_RDAC:
            mppconf['EnableIscsi'] = '1'
        else:
            mppconf['EnableIscsi'] = '0'
        self.host.execdom0('echo "%s" > /etc/mpp.conf' % '\n'.join([a + '=' + b for (a, b) in mppconf.items()]))

        # Setup iSCSI SR
        self.sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host, "TCxxxx")
        lun = xenrt.ISCSILunSpecified("%s/%s/%s" %
                                      (self.initiator,
                                       self.targetiqn,
                                       self.targetip))
        self.sr.create(lun, subtype="lvm", findSCSIID=True, multipathing=True)

    def checkSR(self):
        # Confirm that the same driver is used as before
        try:
            res = self.host.execdom0('ls /dev/disk/by-mpp/*')
            if 'No such file or directory' in res or res.strip() == '':
                mpp = False
            else:
                mpp = True
        except:
            mpp = False

        if self.MPP_RDAC and not mpp:
            raise xenrt.XRTFailure('Incorrect multipath driver',
                                   'Expected MPP RDAC driver to be enabled after upgrade')
        elif not self.MPP_RDAC and mpp:
            raise xenrt.XRTFailure('Incorrect multipath driver',
                                   'Expected MPP RDAC driver to be disabled after upgrade')

class TC12063(TC12058):
    """An upgrade of pre-Cowley to Cowley should retain its preference of multipath driver: dm-multipath"""
    MPP_RDAC = False

class _TCCrossVersionImport(xenrt.TestCase):

    WORKAROUND_CA32958 = False
    WORKAROUND_CA87290 = False
    DISTROS = ["etch", "rhel51", "rhel44", "w2k3eesp2"]

    def prepare(self, arglist):

        # Install the two hosts. We do this sequentially because
        # the INPUTDIR is global.

        # Install the previous GA version on host 0
        old = xenrt.TEC().lookup("OLD_PRODUCT_VERSION")
        oldversion = xenrt.TEC().lookup("OLD_PRODUCT_INPUTDIR")

        self.host0 = xenrt.lib.xenserver.createHost(id=0,
                                                    version=oldversion,
                                                    productVersion=old,
                                                    withisos=True)
        self.getLogsFrom(self.host0)

        # Install the current version on host 1
        if xenrt.TEC().lookup("OPTION_CC", False, boolean=True):
            # Install this as a CC host
            self.host1 = xenrt.lib.xenserver.createHost(id=1, license="platinum")
            # Set up the network requirements
            self.host1.createNetworkTopology("""<NETWORK>
        <PHYSICAL network="NPRI">
          <NIC/>
          <MANAGEMENT/>
          <VMS/>
        </PHYSICAL>
        <PHYSICAL network="NSEC">
          <NIC/>
        </PHYSICAL>
        <PHYSICAL network="IPRI">
          <NIC/>
          <STORAGE/>
        </PHYSICAL>
      </NETWORK>""")
            # Rename the NPRI bridge to its default name
            nwUUID = self.host1.minimalList("network-list", "uuid", "bridge=xenbr0")[0]
            self.host1.genParamSet("network", nwUUID, "name-label", "Pool-wide network associated with eth0")
            # Set up an NFS SR
            nfsServer, nfsPath = xenrt.ExternalNFSShare().getMount().split(":")
            sr = xenrt.lib.xenserver.NFSStorageRepository(self.host1, "shared")
            sr.create(nfsServer, nfsPath)
            self.host1.addSR(sr, default=True)
            poolUUID = self.host1.minimalList("pool-list")[0]
            self.host1.genParamSet("pool", poolUUID, "default-SR", sr.uuid)
            self.host1.genParamSet("pool", poolUUID, "suspend-image-SR", sr.uuid)
        else:
            self.host1 = xenrt.lib.xenserver.createHost(id=1, withisos=True)
        self.getLogsFrom(self.host1)

        # this isn't great. So that we can do cross-version import testing
        # with tools ISO hotfixes, OPTION_NO_AUTO_PATCH is put in the sequence
        # and OLD_PRODUCT_VERSION is set to the same as the version under test.
        # This will result in self.host0 not having hotfixes applied, and
        # self.host1 will. That way we can test the hotfix(es).

        if xenrt.TEC().lookup("OPTION_NO_AUTO_PATCH", False, boolean=True):
            self.host1.applyRequiredPatches()

        # If the old host is Rio then rename the networks on the new host
        # to match the naming on the Rio host. This is so that
        # imports to later versions work correctly (CA-19382).
        if self.host0.productVersion == "Rio":
            # Network associated with bridge xenbr*
            # Pool-wide network associated with eth*
            networks = self.host1.minimalList("network-list")
            for network in networks:
                label = self.host1.genParamGet("network",
                                               network,
                                               "name-label")
                r = re.search("Pool-wide network associated with eth(\d+)",
                              label)
                if r:
                    newlabel = "Network associated with bridge xenbr%s" % \
                               (r.group(1))
                    self.host1.genParamSet("network",
                                           network,
                                           "name-label",
                                           newlabel)
        self.cliguest = self.host1.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.cliguest)
        # Need to add an extra disk, as root one is too small
        ud = None
        if xenrt.TEC().lookup("OPTION_CC", False, boolean=True):
            ud = self.cliguest.createDisk(sizebytes=32212254720, sruuid=sr.uuid)
        else:
            ud = self.cliguest.createDisk(sizebytes=32212254720) # 30GB
        d = self.host1.parseListForOtherParam("vbd-list",
                                              "vm-uuid",
                                              self.cliguest.getUUID(),
                                              "device",
                                              "userdevice=%s" % (ud))
        time.sleep(30)
        self.cliguest.execguest("mkdir -p /mnt/export")
        self.cliguest.execguest("mkfs.ext3 /dev/%s" % (d))
        self.cliguest.execguest("mount /dev/%s /mnt/export" % (d))
        self.exportLocation = "/mnt/export"
        self.cliguest.installCarbonLinuxCLI()

    def testOS(self, distro):

        filetoremove = None

        # Switch to using tools etc. from the old version
        xenrt.TEC().progress("Installing %s" % (distro))
        try:
            xenrt.TEC().setInputDir(xenrt.TEC().lookup("OLD_PRODUCT_INPUTDIR"))

            # Install the OS on the old version
            guest = xenrt.lib.xenserver.guest.createVM(\
                self.host0,
                xenrt.randomGuestName(),
                distro=distro,
                vifs=[("0",
                       self.host0.getPrimaryBridge(),
                       xenrt.util.randomMAC(),
                       None)])
            if guest.windows:
                guest.installDrivers()
            guest.reboot()
            guest.shutdown()
            self.getLogsFrom(guest)

            # Export the VM
            xenrt.TEC().progress("Exporting %s" % (distro))
            filename = "%s/export-%s.img" % (self.exportLocation,
                                             guest.getUUID())
            args = "uuid=%s filename=%s" % (guest.getUUID(), filename)
            c = xenrt.lib.xenserver.buildCommandLine(guest.host,
                                                     "vm-export",
                                                     args)
            filetoremove = filename
            self.cliguest.execcmd("xe %s" % (c), timeout=7200)
            filetoremove = None
        finally:
            # Switch back to using inputs from the current version
            xenrt.TEC().setInputDir(None)
            if filetoremove:
                try:
                    self.cliguest.execcmd("rm -f %s" % (filetoremove))
                except:
                    pass
                filetoremove = None

        # Import the VM to the current version host
        xenrt.TEC().progress("Importing %s" % (distro))
        try:
            filetoremove = filename
            newguest = self.host1.guestFactory()(guest.getName())
            guest.populateSubclass(newguest)
            newguest.vifs = []
            newguest.host = self.host1
            self.host1.guests[newguest.getName()] = newguest

            sruuid = self.cliguest.chooseSR()
            args = []
            args.append("sr-uuid=%s" % (sruuid))
            args.append("filename=%s" % (filename))
            args.append("preserve=true")
            c = xenrt.lib.xenserver.buildCommandLine(self.host1,
                                                     "vm-import",
                                                     string.join(args))
            newuuid = string.strip(self.cliguest.execcmd("xe %s" % (c),
                                                         timeout=7200))
            newguest.uuid = newuuid
            newguest.windows = guest.windows
            newguest.existing(self.host1)
            self.host1.addGuest(newguest)
            newguest.compareConfig(guest)
        finally:
            if filetoremove:
                self.cliguest.execcmd("rm -f %s" % (filetoremove))
                filetoremove = None

        if distro == "w2k3eesp2" and self.WORKAROUND_CA32958:
            # CA-32958 - we have to do a workaround here
            newguest.paramSet("xenstore-data:vm-data/disable_pf","1")

        # Perform a VM start before we upgrade the tools
        if self.WORKAROUND_CA87290:
            newguest.enlightenedDrivers = False
        newguest.start()
        newguest.check()
        newguest.shutdown()
        self.getLogsFrom(newguest)

        # Upgrade the PV tools and drivers
        xenrt.TEC().progress("Upgrading %s" % (distro))
        newguest.start()
        if distro == "w2k3eesp2" and self.WORKAROUND_CA32958:
            # CA-32958 Remove it so it vanishes on subsequent boot
            newguest.paramRemove("xenstore-data", "vm-data/disable_pf")
        if newguest.windows:
            newguest.installDrivers()
        else:
            newguest.installTools()

        # Smoketest the VM
        xenrt.TEC().progress("Smoketesting %s" % (distro))
        newguest.suspend()
        newguest.resume()
        newguest.check()
        newguest.suspend()
        newguest.resume()
        newguest.check()
        if not xenrt.TEC().lookup("OPTION_CC", False, boolean=True):
            newguest.migrateVM(newguest.host, live="true")
            time.sleep(10)
            newguest.check()
            newguest.migrateVM(newguest.host, live="true")
            time.sleep(10)
            newguest.check()
        newguest.reboot()
        newguest.waitForAgent(180)
        newguest.reboot()
        newguest.waitForAgent(180)
        newguest.shutdown()
        newguest.start()
        newguest.check()
        newguest.waitForAgent(180)
        newguest.shutdown()

        # Uninstall
        xenrt.TEC().progress("Uninstalling %s" % (distro))
        try:
            xenrt.TEC().setInputDir(xenrt.TEC().lookup("OLD_PRODUCT_INPUTDIR"))
            self.uninstallOnCleanup(guest)
        finally:
            xenrt.TEC().setInputDir(None)
        self.uninstallOnCleanup(newguest)

    def run(self, arglist):

        # For each OS version perform the subtest
        for distro in self.DISTROS:
            self.runSubcase("testOS", (distro), "ImpExp", distro)

class TC10536(_TCCrossVersionImport):
    """Import of VMs exported from XenServer 3.2 GA."""

    DISTROS = ["sarge", "rhel44", "w2k3eesp2"]

class TC7951(_TCCrossVersionImport):
    """Import of VMs exported from XenServer 4.1 GA."""

    DISTROS = ["rhel51", "rhel44", "w2k3eesp2"]

class TC7952(_TCCrossVersionImport):
    """Import of VMs exported from XenServer 4.0 GA."""
    WORKAROUND_CA32958 = True
    WORKAROUND_CA87290 = True

    DISTROS = ["rhel44", "w2k3eesp2"]

    def prepare(self, arglist):
        xenrt.TEC().config.setVariable("CARBON_EXTRA_CDS", "DEFAULT")
        _TCCrossVersionImport.prepare(self, arglist)


class TC9046(_TCCrossVersionImport):
    """Import of VMs exported from XenServer 5.0 GA."""

    DISTROS = ["rhel52", "rhel46", "ws08-x86"]

class TC12549(_TCCrossVersionImport):
    """Import of VMs exported from XenServer 5.0 Up3 GA."""

    DISTROS = ["rhel52", "rhel46", "ws08-x86"]

class TC9302(_TCCrossVersionImport):
    """Import of VMs exported from XenServer 5.5 GA."""

    DISTROS = ["rhel53", "rhel47", "ws08-x86"]

class TC12547(_TCCrossVersionImport):
    """Import of VMs exported from XenServer 5.5 Up1 GA."""

    DISTROS = ["rhel53", "rhel47", "ws08-x86"]

class TC12548(_TCCrossVersionImport):
    """Import of VMs exported from XenServer 5.5 Up2 GA."""

    DISTROS = ["rhel53", "rhel47"]

class TC12545(_TCCrossVersionImport):
    """Import of VMs exported from XenServer 5.6 GA (MNR)"""

    DISTROS = ["rhel53", "rhel47"]

class TC17440(_TCCrossVersionImport):
    """Import of VMs exported from XenServer 6.0 GA (Boston)"""

    DISTROS = ["debian60", "rhel56", "rhel6", "ws08sp2-x86"]

class TC17441(_TCCrossVersionImport):
    """Import of VMs exported from XenServer 6.0.2 GA (Sanibel)"""

    DISTROS = ["debian60", "rhel57", "rhel61", "ws08sp2-x86"]

class TC18551(_TCCrossVersionImport):
    """Import of VMs exported from XenServer 6.1 GA (Tampa)"""

    DISTROS = ["debian60", "rhel61","ws08sp2-x86", "win7sp1-x86"]


class TC8420(xenrt.TestCase):
    """Install the "Scunthorpe" Xen RPM upgrade"""

    def getXenVersion(self, host):
        dmesg = host.execdom0("xe host-dmesg uuid=%s" % (host.getMyHostUUID()))
        r = re.search(r"Latest ChangeSet:.*\((.*)\)", dmesg)
        if not r:
            raise xenrt.XRTError("Could not parse dmesg for Xen version")
        return r.group(1)

    def run(self, arglist):
        if not arglist or len(arglist) == 0:
            raise xenrt.XRTError("No hotfix specified")
        hotfix = arglist[0]

        host = self.getDefaultHost()

        # Get current Xen hypervisor version
        prevver = self.getXenVersion(host)

        # Install the RPM
        rpmfile = xenrt.TEC().getFile(hotfix)
        remotefn = "/tmp/%s" % os.path.basename(hotfix)
        sftp = host.sftpClient()
        try:
            sftp.copyTo(rpmfile, remotefn)
        finally:
            sftp.close()
        host.execdom0("rpm --upgrade -v %s" % (remotefn))

        # Reboot
        host.reboot()

        # Check the new Xen hypervisor version is different to the old
        newver = self.getXenVersion(host)
        if not newver > prevver:
            raise xenrt.XRTFailure("Host didn't boot into new Xen version",
                                   "%s to %s" % (prevver, newver))
        xenrt.TEC().comment("New Xen version: %s" % (newver))

class _VMToolsUpgrade(xenrt.TestCase):
    """Upgrade the kernel/drivers/tools in a VM installed on a previous XenServer version"""

    VMNAME = None

    def prepare(self, arglist):
        if not self.VMNAME:
            raise xenrt.XRTError("Subclass TC need to specify DISTRO")

        # The sequence must have prepared a VM named as specified. The
        # VM must be running out of date tools before we start. The host
        # should be at the current version under test.
        self.host = self.getDefaultHost()
        self.hostversion = self.host.productRevision.split("-")[0]
        self.guest = self.getGuest(self.VMNAME)
        self.guest.changeCD(None)
        self.guest.start()

        # DL: temporarily removing check for Gucci
        #existingversion = self.guest.getPVDriverVersion(micro=True)
        #if not existingversion:
        #    raise xenrt.XRTError("Could not find existing PV driver/tools version")
        #existingversion = existingversion.split("-")[0] # major.minor.micro
        #if self.hostversion == existingversion:
        #    raise xenrt.XRTError("VM already has the same tools version as the host (%s)" % (self.hostversion))

    def lifecycle(self, dosuspend):
        self.guest.shutdown()
        self.guest.start()
        self.guest.check()
        time.sleep(30)
        self.guest.reboot()
        if dosuspend:
            self.guest.suspend()
            self.guest.resume()
            self.guest.migrateVM(self.host, live="true")
        self.guest.check()

    def upgradeTools(self, guest=None):
        if not guest:
            guest = self.guest
        if guest.windows:

            if not isinstance(self.host, xenrt.lib.xenserver.DundeeHost):
                if guest.pvDriversUpToDate():
                    raise xenrt.XRTFailure("PV drivers should not be reported as up-to-date before driver upgrade")

            guest.installDrivers()

            if not guest.pvDriversUpToDate():
                raise xenrt.XRTFailure("PV drivers should be reported as up-to-date after driver upgrade")
        else:
            guest.installTools()
        guest.waitForAgent(60)
        guest.reboot()
        v = guest.getPVDriverVersion(micro=True)
        if not v:
            raise xenrt.XRTError("Could not find new PV driver/tools version")
        v = v.split("-")[0] # major.minor.micro
        if v != self.hostversion:
            raise xenrt.XRTFailure("Upgraded tools version %s does not match host version %s" % (v, self.hostversion))

    def uninstallTools(self):
        self.guest.uninstallDrivers()

    def run(self, arglist):
        # Test some lifecycle operations with the old tools
        if self.runSubcase("lifecycle", (False), "OldTools", "Lifecycle") != \
                xenrt.RESULT_PASS:
            return

        # Upgrade the tools/drivers/kernel
        if self.runSubcase("upgradeTools", (), "Tools", "Upgrade") != \
                xenrt.RESULT_PASS:
            return

        # Check lifecycle operations
        if self.runSubcase("lifecycle", (True), "NewTools", "Lifecycle") != \
                xenrt.RESULT_PASS:
            return
        self.guest.shutdown()


class UpgradeAllVMTools(_VMToolsUpgrade):
    def prepare(self,arglist=None):
        self.host = self.getDefaultHost()
        self.hostversion = self.host.productRevision.split("-")[0]
        self.guestNames = xenrt.TEC().registry.guestList()

    def run(self,arglist = None):

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guests":
                self.guestNames = l[1].split(',')

        self.guestsToUpgrade = [self.getGuest(g) for g in self.guestNames]
        xenrt.pfarm([xenrt.PTask(self.upgradeTools, guest=g) for g in self.guestsToUpgrade])

class TC9152(_VMToolsUpgrade):
    """Upgrade PV drivers and tools in a Windows 2003 EE SP2 VM installed on the previous GA version"""

    VMNAME = "w2k3eesp2"

class TC11413(_VMToolsUpgrade):
    """Upgrade PV drivers and tools in a Windows 2003 EE SP1 VM installed on the previous GA version"""

    VMNAME = "w2k3eesp1"

class TC11414(_VMToolsUpgrade):
    """Upgrade PV drivers and tools in a Windows 2003 EE VM installed on the previous GA version"""

    VMNAME = "w2k3ee"

class TC9153(_VMToolsUpgrade):
    """Upgrade PV drivers and tools in a Windows 2000 SP4 VM installed on the previous GA version"""

    VMNAME = "w2kassp4"

class TC9154(_VMToolsUpgrade):
    """Upgrade PV drivers and tools in a Windows 2003 EE SP2 x64 VM installed on the previous GA version"""

    VMNAME = "w2k3eesp2-x64"

class TC11415(_VMToolsUpgrade):
    """Upgrade PV drivers and tools in a Windows 2008 R2 x64 VM installed on the previous GA version"""

    VMNAME = "ws08r2-x64"

class TC11416(_VMToolsUpgrade):
    """Upgrade PV drivers and tools in a Windows 2008 SP2 VM installed on the previous GA version"""

    VMNAME = "ws08sp2-x86"

class TC9155(_VMToolsUpgrade):
    """Upgrade PV drivers and tools in a Windows 2008 VM installed on the previous GA version"""

    VMNAME = "ws08-x86"

class TC11417(_VMToolsUpgrade):
    """Upgrade PV drivers and tools in a Windows 2008 SP2 x64 VM installed on the previous GA version"""

    VMNAME = "ws08sp2-x64"

class TC9156(_VMToolsUpgrade):
    """Upgrade PV drivers and tools in a Windows 2008 x64 VM installed on the previous GA version"""

    VMNAME = "ws08-x64"

class TC11418(_VMToolsUpgrade):
    """Upgrade PV drivers and tools in a Windows 7 VM installed on the previous GA version"""

    VMNAME = "win7-x86"

class TC11419(_VMToolsUpgrade):
    """Upgrade PV drivers and tools in a Windows 7 x64 VM installed on the previous GA version"""

    VMNAME = "win7-x64"

class TC9157(_VMToolsUpgrade):
    """Upgrade PV drivers and tools in a Windows XP SP3 VM installed on the previous GA version"""

    VMNAME = "winxpsp3"

class TC11420(_VMToolsUpgrade):
    """Upgrade PV drivers and tools in a Windows XP SP2 VM installed on the previous GA version"""

    VMNAME = "winxpsp2"

class TC11421(_VMToolsUpgrade):
    """Upgrade PV drivers and tools in a Windows Vista EE SP2 VM installed on the previous GA version"""

    VMNAME = "vistaeesp2"

class TC9158(_VMToolsUpgrade):
    """Upgrade PV drivers and tools in a Windows Vista EE SP1 VM installed on the previous GA version"""

    VMNAME = "vistaeesp1"

class TC11422(_VMToolsUpgrade):
    """Upgrade PV drivers and tools in a Windows Vista EE SP2 x64 VM installed on the previous GA version"""

    VMNAME = "vistaeesp2-x64"

class TC9159(_VMToolsUpgrade):
    """Upgrade PV drivers and tools in a Windows Vista EE SP1 x64 VM installed on the previous GA version"""

    VMNAME = "vistaeesp1-x64"

class TC9160(_VMToolsUpgrade):
    """Upgrade kernel (if available) and tools in a RHEL 4.7 VM installed on the previous GA version"""

    VMNAME = "rhel47"

class TC9161(_VMToolsUpgrade):
    """Upgrade kernel (if available) and tools in a RHEL 5.2 VM installed on the previous GA version"""

    VMNAME = "rhel52"

class TC9162(_VMToolsUpgrade):
    """Upgrade kernel (if available) and tools in a RHEL 5.2 x64 VM installed on the previous GA version"""

    VMNAME = "rhel52x64"

class TC9163(_VMToolsUpgrade):
    """Upgrade kernel (if available) and tools in a SLES 9 SP4 VM installed on the previous GA version"""

    VMNAME = "sles94"

class TC9164(_VMToolsUpgrade):
    """Upgrade kernel (if available) and tools in a SLES 10 SP2 VM installed on the previous GA version"""

    VMNAME = "sles102"

class TC9165(_VMToolsUpgrade):
    """Upgrade kernel (if available) and tools in a SLES 10 SP2 x64 VM installed on the previous GA version"""

    VMNAME = "sles102x64"

class TC9166(_VMToolsUpgrade):
    """Upgrade kernel (if available) and tools in a Debian Etch VM installed on the previous GA version"""

    VMNAME = "etch"

class TC9167(_VMToolsUpgrade):
    """Upgrade kernel (if available) and tools in a Debian Sarge VM installed on the previous GA version"""

    VMNAME = "sarge"

class TC21204(_VMToolsUpgrade):
    """Upgrade kernel (if available) and tools in a Centos 5.4 VM installed on the previous GA version"""

    VMNAME = "centos54"

class TC21205(_VMToolsUpgrade):
    """Upgrade kernel (if available) and tools in a OEL 5.4 VM installed on the previous GA version"""

    VMNAME = "oel54"

class TC21206(_VMToolsUpgrade):
    """Upgrade kernel (if available) and tools in a SLES11 VM installed on the previous GA version"""

    VMNAME = "sles11"

class TC21207(_VMToolsUpgrade):
    """Upgrade kernel (if available) and tools in a Debian 5.0 VM installed on the previous GA version"""

    VMNAME = "debian50"

class _VMToolsUpgradeNotOutOfDate(_VMToolsUpgrade):
    """MNR non-Windows tools should be up-to-date on Cowley"""

    def run(self, arglist):
        uptodate = self.guest.paramGet("PV-drivers-up-to-date")
        if uptodate == 'false':
            raise xenrt.XRTFailure('Tools reported as out-of-date')

class TC12530(_VMToolsUpgradeNotOutOfDate):
    """MNR RHEL 5.4 tools should be up-to-date on Cowley"""

    VMNAME = "rhel5x"

class _FeatureOperationAfterUpgrade(xenrt.TestCase):
    """Template testcase for verifying that a feature set up before an update
    or upgrade still functions after the update/upgrade"""

    def __init__(self):
        xenrt.TestCase.__init__(self)
        self.host = None
        self.hostsToUpgrade = []
        self.poolsToUpgrade = []

    def prepare(self, arglist):
        # Assume that we've used <prepare> in combination with
        # INITIAL_VERSION_PATH to put the hosts into the pre-update/upgrade
        # state.
        #
        # This method should be overriden to set up the scenario. Any hosts
        # and pools involved should be added to self.hostsToUpgrade or
        # self.poolsToUpgrade
        #
        raise xenrt.XRTError("Unimplemented")

    def featureTest(self):
        # This method should be overriden by the testcase to verify the
        # feature is operating properly. This will be used both before
        # and after the update/upgrade
        raise xenrt.XRTError("Unimplemented")

    def preUpgradeHook(self):
        pass

    def postUpgradeHook(self):
        pass

    def checkHostIsAtVersion(self, host):
        versionPath = xenrt.TEC().lookup("INITIAL_VERSION_PATH", None)
        if not versionPath:
            # Can't check, not a problem...
            return
        versionPath = versionPath.replace(",", " ")
        versionPathList = versionPath.split()
        version = None
        haspatch = False
        versionPathList.reverse()
        for v in versionPathList:
            if v[0] == "+":
                haspatch = True
            else:
                vv = v.split("/")
                version = vv[0]
                if len(vv) > 1:
                    # May be a rollup so there *might* be patches
                    haspatch = None
                break
        if version:
            if host.productVersion != version:
                raise xenrt.XRTError("Host version %s != %s" %
                                     (host.productVersion, version),
                                     host.getName())
        patches = host.minimalList("patch-list")
        if xenrt.TEC().lookup("EXPECTED_PATCHES", False, boolean=True):
            haspatch = True
        if len(patches) > 0 and haspatch == False:
            raise xenrt.XRTError("Host has unexpected patches", host.getName())
        if len(patches) == 0 and haspatch == True:
            raise xenrt.XRTError("Host has no patches", host.getName())

    def featureOpUpgrade(self):
        # This is the update or upgrade as required. Note that upgrades
        # will sometimes replace the host/pool objects in self.hostsToUpgrade
        # and self.poolsToUpgrade so featureTest implementations should
        # always read fresh values back out from these arrays.
        u = xenrt.TEC().lookup("THIS_UPDATE", None)
        if not u:
            raise xenrt.XRTError("No THIS_UPDATE specified")
        # Check the hosts/pools have the expected version based on
        # INITIAL_VERSION_PATH. If INITIAL_VERSION_PATH specifies updates
        # to that version make sure the patch-list is not empty. (This is
        # not bullet proof but should protect against this test being
        # accidentally run on already upgraded (but not necessarilty updated)
        # hosts.)
        for h in self.hostsToUpgrade:
            self.checkHostIsAtVersion(h)
        for p in self.poolsToUpgrade:
            for h in p.getHosts():
                self.checkHostIsAtVersion(h)
        self.preUpgradeHook()
        if u == "UPGRADE":
            # Perform a full upgrade to the version in INPUTDIR
            xenrt.TEC().setInputDir(None)
            for i in range(len(self.hostsToUpgrade)):
                host = self.hostsToUpgrade[i]
                xenrt.TEC().logverbose("Upgrading host %s to version under "
                                       "test" % (host.getName()))
                newhost = host.upgrade()
                self.hostsToUpgrade[i] = newhost
            for i in range(len(self.poolsToUpgrade)):
                pool = self.poolsToUpgrade[i]
                xenrt.TEC().logverbose("Upgrading pool to version under test")
                newpool = pool.upgrade(rolling=True)
                self.poolsToUpgrade[i] = newpool
        else:
            # It's a hotfix
            updatefile = xenrt.TEC().getFile(u)
            if not updatefile:
                raise xenrt.XRTError("Could not retrieve update file %s" % (u))
            for h in self.hostsToUpgrade:
                xenrt.TEC().logverbose("Applying patch to %s: %s" %
                                       (h.getName(), u))
                patches = h.minimalList("patch-list")
                h.applyPatch(updatefile, applyGuidance=True)
                patches2 = h.minimalList("patch-list")
                h.execdom0("xe patch-list")
                if len(patches2) <= len(patches):
                    raise xenrt.XRTFailure("Patch list did not grow after "
                                           "patch application on %s" %
                                           (h.getName()))
            for p in self.poolsToUpgrade:
                xenrt.TEC().logverbose("Applying patch to pool: %s" % (u))
                patches = p.master.minimalList("patch-list")
                p.applyPatch(updatefile, applyGuidance=True)
                patches2 = p.master.minimalList("patch-list")
                p.master.execdom0("xe patch-list")
                if len(patches2) <= len(patches):
                    raise xenrt.XRTFailure("Patch list did not grow after "
                                           "patch application on pool")
        self.postUpgradeHook()

    def run(self, arglist):

        # Verify functionality before the upgrade/update
        if self.runSubcase("featureTest", (), "Check", "Before") != \
               xenrt.RESULT_PASS:
            return

        # Perform the upgrade/update
        if self.runSubcase("featureOpUpgrade", (), "Do", "Upgrade") != \
               xenrt.RESULT_PASS:
            return

        # Verify functionality after the upgrade/update
        if self.runSubcase("featureTest", (), "Check", "After") != \
               xenrt.RESULT_PASS:
            return

class _WindowsPVUpgradeWithStaticIP(_VMToolsUpgrade):
    def prepare(self,arglist):
        _VMToolsUpgrade.prepare(self,arglist)
        if not self.guest.windows:
            raise xenrt.XRTError("Guest is not windows")
        # Reconfigure the VIFs on the private networks
        self.staticIP = xenrt.StaticIP4Addr(network="NSEC")
        self.guest.configureNetwork("eth1", self.staticIP.getAddr(),xenrt.TEC().lookup(["NETWORK_CONFIG",
                                       "SECONDARY",
                                       "SUBNETMASK"]))

        # Stop the firewall blocking ICMP
        self.guest.xmlrpcExec("netsh firewall set icmpsetting 8")

        # Sanity check that it's currently working
        xenrt.command("ping -c 10 %s" % self.staticIP.getAddr())

    def run(self, arglist):

        self.guest.getWindowsIPConfigData()

        # Upgrade the tools
        if self.runSubcase("upgradeTools", (), "Tools", "Upgrade") != xenrt.RESULT_PASS:
            return

        if not "r2" in self.guest.distro and ("vista" in self.guest.distro or "ws08" in self.guest.distro):
            for i in range(2):
                self.guest.reboot()

        self.guest.getWindowsIPConfigData()

        # Check the VM kept it's static IP after the tools upgrade
        xenrt.command("ping -c 10 %s" % self.staticIP.getAddr())

        # Uninstall tools
        if self.runSubcase("uninstallTools", (), "Tools", "Uninstall") != xenrt.RESULT_PASS:
            return

        self.guest.getWindowsIPConfigData()

        # Check the VM kept it's static IP after the tools uninstallation
        if isinstance(self.guest, xenrt.lib.xenserver.guest.TampaGuest) and self.guest.host.productVersion != "Tampa" and not self.guest.usesLegacyDrivers():
            xenrt.command("ping -c 10 %s" % self.staticIP.getAddr())

        self.guest.shutdown()
  
    def postRun(self):
    
        self.guest.shutdown()
        self.staticIP.release()

class _WindowsPVUpgradeWithStaticIPv6(_VMToolsUpgrade):
    def prepare(self, arglist):
        _VMToolsUpgrade.prepare(self, arglist)

        staticIpObj = self.guest.specifyStaticIPv6()
        self.ipv6Add = staticIpObj.getAddr()
        self.guest.mainip =  self.ipv6Add
        self.guest.getWindowsIPConfigData()

    def run(self, arglist):

        # Upgrade the tools
        if self.runSubcase("upgradeTools", (), "Tools", "Upgrade") != xenrt.RESULT_PASS:
            return

        # just to be sure
        self.guest.mainip =  self.ipv6Add

        # test the connection
        self.guest.getWindowsIPConfigData()
        self.guest.shutdown()


# IPv4 Upgrade tests

class TC20716(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade Windows 8.1 x86 PV tools with static IP Address """

    VMNAME = "win81-x86"

class TC20717(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade Windows 8.1 x64 PV tools with static IP Address """

    VMNAME = "win81-x64"

class TC20718(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade WS2012R2 x64 PV tools with static IP Address """

    VMNAME = "ws12r2-x64"

class TC20719(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade WS2012R2 Core x64 PV tools with static IP Address """

    VMNAME = "ws12r2core-x64"

class TC19900(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade Windows 8 x86 PV tools with static IP Address """

    VMNAME = "win8-x86"

class TC19901(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade Windows 8 x64 PV tools with static IP Address """

    VMNAME = "win8-x64"

class TC19902(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade WS2012 x64 PV tools with static IP Address """

    VMNAME = "ws12-x64"

class TC19903(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade WS2012 Core x64 PV tools with static IP Address """

    VMNAME = "ws12core-x64"

class TC15220(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade WS08R2SP1 x64 PV tools with static IP Address """

    VMNAME = "ws08r2sp1-x64"


class TC15222(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade Win7 SP1 x64 PV tools with static IP Address """

    VMNAME = "win7sp1-x64"


class TC15223(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade Win7 SP1 x86 PV tools with static IP Address """

    VMNAME = "win7sp1-x86"


class TC15224(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade WS08SP2 x64 PV tools with static IP Address """

    VMNAME = "ws08sp2-x64"


class TC15225(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade WS08SP2 x86 PV tools with static IP Address """

    VMNAME = "ws08sp2-x86"

class TC15226(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade Vista SP2 x64 PV tools with static IP Address """

    VMNAME = "vistaeesp2-x64"

class TC15227(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade Vista SP2 x86 PV tools with static IP Address """

    VMNAME = "vistaeesp2"


class TC15228(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade W2k3 SP2 x64 PV tools with static IP Address """

    VMNAME = "w2k3eesp2-x64"


class TC15229(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade W2k3 SP2 x86 PV tools with static IP Address """

    VMNAME = "w2k3eesp2"


class TC15230(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade WinXP SP3 x86 PV tools with static IP Address """

    VMNAME = "winxpsp3"








# IPv6 Upgrade tests

class TC20720(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Win8.1 x86 PV tools with static IPv6 Address """

    VMNAME = "win81-x86"

class TC20721(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Win8.1 x64 PV tools with static IPv6 Address """

    VMNAME = "win81-x64"

class TC20722(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade WS2012R2 x64 PV tools with static IPv6 Address """

    VMNAME = "ws12r2-x64"

class TC20723(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade WS2012R2 x64 PV tools with static IPv6 Address """

    VMNAME = "ws12r2core-x64"


class TC19904(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Win8 x86 PV tools with static IPv6 Address """

    VMNAME = "win8-x86"

class TC19905(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Win8 x64 PV tools with static IPv6 Address """

    VMNAME = "win8-x64"

class TC19906(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade WS2012 x64 PV tools with static IPv6 Address """

    VMNAME = "ws12-x64"

class TC19907(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade WS2012 x64 PV tools with static IPv6 Address """

    VMNAME = "ws12core-x64"

class TC18826(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade WS08R2SP1 x64 PV tools with static IPv6 Address """

    VMNAME = "ws08r2sp1-x64"


class TC20628(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade WS12 x64 PV tools with static IPv6 Address """

    VMNAME = "ws12-x64"


class TC18827(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Win7 SP1 x64 PV tools with static IPv6 Address """

    VMNAME = "win7sp1-x64"


class TC20629(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Win8 x64 PV tools with static IPv6 Address """

    VMNAME = "win8-x64"


class TC18828(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Win7 SP1 x86 PV tools with static IPv6 Address """

    VMNAME = "win7sp1-x86"


class TC20630(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Win8 x86 PV tools with static IPv6 Address """

    VMNAME = "win8-x86"


class TC18829(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade WS08SP2 x64 PV tools with static IPv6 Address """

    VMNAME = "ws08sp2-x64"


class TC18830(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade WS08SP2 x86 PV tools with static IPv6 Address """

    VMNAME = "ws08sp2-x86"

class TC18831(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Vista SP2 x64 PV tools with static IPv6 Address """

    VMNAME = "vistaeesp2-x64"

class TC18832(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Vista SP2 x86 PV tools with static IPv6 Address """

    VMNAME = "vistaeesp2"


class TC18833(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade W2k3 SP2 x64 PV tools with static IPv6 Address """

    VMNAME = "w2k3eesp2-x64"


class TC18834(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade W2k3 SP2 x86 PV tools with static IPv6 Address """

    VMNAME = "w2k3eesp2"


class TC18835(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade WinXP SP3 x86 PV tools with static IPv6 Address """

    VMNAME = "winxpsp3"



# IPv4 Tools ISO Hotfix Upgrade tests

class TC18505(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade WS08R2SP1 x64 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "ws08r2sp1-x64"


class TC18506(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade Win7 SP1 x64 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "win7sp1-x64"


class TC18509(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade Win7 SP1 x86 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "win7sp1-x86"


class TC18507(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade WS08SP2 x64 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "ws08sp2-x64"


class TC18510(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade WS08SP2 x86 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "ws08sp2-x86"

class TC18511(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade Vista SP2 x86 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "vistaeesp2"


class TC18508(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade W2k3 SP2 x64 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "w2k3eesp2-x64"


class TC18512(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade W2k3 SP2 x86 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "w2k3eesp2"


class TC18513(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade WinXP SP3 x86 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "winxpsp3"

class TC20663(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade Windows 8 x86 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "win8-x86"

class TC20664(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade Windows 8.1 x86 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "win81-x86"

class TC20665(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade Windows 8 x64 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "win8-x64"

class TC20666(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade Windows 8.1 x64 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "win81-x64"

class TC20667(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade Windows Server 2012 x64 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "ws12-x64"

class TC20668(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade Windows Server 2012 core x64 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "ws12core-x64"

class TC20669(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade Windows Server 2012 R2 x64 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "ws12r2-x64"

class TC20670(_WindowsPVUpgradeWithStaticIP):
    """ Upgrade Windows Server 2012 R2 core x64 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "ws12r2core-x64"


# IPv4 Tools ISO Hotfix Install tests



class TC18542(_WindowsPVUpgradeWithStaticIP):
    """ Install WS08R2SP1 x64 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "ws08r2sp1-x64"


class TC18543(_WindowsPVUpgradeWithStaticIP):
    """ Install Win7 SP1 x64 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "win7sp1-x64"


class TC18544(_WindowsPVUpgradeWithStaticIP):
    """ Install Win7 SP1 x86 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "win7sp1-x86"


class TC18545(_WindowsPVUpgradeWithStaticIP):
    """ Install WS08SP2 x64 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "ws08sp2-x64"


class TC18546(_WindowsPVUpgradeWithStaticIP):
    """ Install WS08SP2 x86 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "ws08sp2-x86"

class TC18547(_WindowsPVUpgradeWithStaticIP):
    """ Install Vista SP2 x86 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "vistaeesp2"


class TC18548(_WindowsPVUpgradeWithStaticIP):
    """ Install W2k3 SP2 x64 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "w2k3eesp2-x64"


class TC18549(_WindowsPVUpgradeWithStaticIP):
    """ Install W2k3 SP2 x86 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "w2k3eesp2"


class TC18550(_WindowsPVUpgradeWithStaticIP):
    """ Install WinXP SP3 x86 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "winxpsp3"

class TC20655(_WindowsPVUpgradeWithStaticIP):
    """ Install Windows 8 x86 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "win8-x86"

class TC20656(_WindowsPVUpgradeWithStaticIP):
    """ Install Windows 8 x64 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "win8-x64"

class TC20657(_WindowsPVUpgradeWithStaticIP):
    """ Install Windows 8.1 x86 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "win81-x86"

class TC20658(_WindowsPVUpgradeWithStaticIP):
    """ Install Windows 8.1 x86 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "win81-x64"

class TC20659(_WindowsPVUpgradeWithStaticIP):
    """ Install Windows Server 2012 x64 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "ws12-x64"

class TC20660(_WindowsPVUpgradeWithStaticIP):
    """ Install Windows Server 2012 Core x64 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "ws12core-x64"

class TC20661(_WindowsPVUpgradeWithStaticIP):
    """ Install Windows Server 2012 R2 x64 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "ws12r2-x64"

class TC20662(_WindowsPVUpgradeWithStaticIP):
    """ Install Windows Server 2012 R2 core x64 PV tools with static IP Address from tools ISO hotfix"""

    VMNAME = "ws12r2core-x64"




# IPv6 Tools ISO Hotfix Upgrade tests

class TC18559 (_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade WS08R2SP1 x64 PV tools with static IPv6 Address from tools ISO hotfix"""

    VMNAME = "ws08r2sp1-x64"


class TC18560(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Win7 SP1 x64 PV tools with static IPv6 Address from tools ISO hotfix"""

    VMNAME = "win7sp1-x64"


class TC18561(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Win7 SP1 x86 PV tools with static IPv6 Address from tools ISO hotfix"""

    VMNAME = "win7sp1-x86"


class TC18562(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade WS08SP2 x64 PV tools with static IPv6 Address from tools ISO hotfix"""

    VMNAME = "ws08sp2-x64"


class TC18563(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade WS08SP2 x86 PV tools with static IPv6 Address from tools ISO hotfix"""

    VMNAME = "ws08sp2-x86"

class TC18564(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Vista SP2 x86 PV tools with static IPv6 Address from tools ISO hotfix"""

    VMNAME = "vistaeesp2"

class TC20647(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Windows 8 x86 PV tools with static IPv6 Address from tools ISO hotfix"""

    VMNAME = "win8-x86"

class TC20648(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Windows 8 x64 PV tools with static IPv6 Address from tools ISO hotfix"""

    VMNAME = "win8-x64"

class TC20649(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Windows 8.1 x86 PV tools with static IPv6 Address from tools ISO hotfix"""

    VMNAME = "win81-x86"

class TC20650(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Windows 8.1 x86 PV tools with static IPv6 Address from tools ISO hotfix"""

    VMNAME = "win81-x64"

class TC20651(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Windows Server 2012 x64 PV tools with static IPv6 Address from tools ISO hotfix"""

    VMNAME = "ws12-x64"

class TC20652(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Windows Server 2012 Core x64 PV tools with static IPv6 Address from tools ISO hotfix"""

    VMNAME = "ws12core-x64"

class TC20653(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Windows Server 2012R2 x64 PV tools with static IPv6 Address from tools ISO hotfix"""

    VMNAME = "ws12r2-x64"

class TC20654(_WindowsPVUpgradeWithStaticIPv6):
    """ Upgrade Windows Server 2012R2 x64 PV tools with static IPv6 Address from tools ISO hotfix"""

    VMNAME = "ws12r2core-x64"
  

class TC10718(_FeatureOperationAfterUpgrade):
    """Continued operation of AD authentication following host/pool update/upgrade"""

    AUTHSERVER = "AUTHSERVER"
    SUBJECTGRAPH = """
<subjects>
  <group name="TC10718group1">
    <user name="TC10718userA"/>
    <group name="TC10718group2">
      <user name="TC10718userB"/>
      <user name="TC10718userC"/>
    </group>
  </group>
  <user name="TC10718userD"/>
</subjects>
    """
    TESTUSERS = ["TC10718userA", "TC10718userB", "TC10718userC"]
    ADDREMOVEUSERS = ["TC10718userD"]

    def prepare(self, arglist):
        self.poolsToUpgrade.append(self.getDefaultPool())
        authguest = self.getGuest(self.AUTHSERVER)
        if not authguest:
            raise xenrt.XRTError("Could not find %s VM" % (self.AUTHSERVER))
        self.authserver = authguest.getActiveDirectoryServer()
        self.authserver.createSubjectGraph(self.SUBJECTGRAPH)

    def addExtraUsers(self):
        # Add extra user(s) to the subject-list
        for user in self.ADDREMOVEUSERS:
            self.poolsToUpgrade[0].allow(\
                self.authserver.getSubject(name=user), "pool-admin")
            xenrt.TEC().logverbose("Adding role ")
            uuid = self.poolsToUpgrade[0].master.getSubjectUUID(self.authserver.getSubject(name=user))
            cliRole = self.poolsToUpgrade[0].getCLIInstance()
            argsAddrole = []
            argsAddrole.append("role-name='pool-admin'")
            argsAddrole.append("uuid=%s" % (uuid))
            xenrt.TEC().logverbose("Executing CLI command to add role ")
            try:
                cliRole.execute("subject-role-add", string.join(argsAddrole),\
                    username="root",password=self.poolsToUpgrade[0].master.password)                                    
            except xenrt.XRTException, e:
                if "Role already exists" in e.reason:
                    xenrt.TEC().logverbose("Role seems to be added already")
                else:
                    raise
            xenrt.TEC().logverbose("adding role to the queue ")
            self.authserver.getSubject(name=user).roles.add("pool-admin")
            
    def cliAuthentication(self,auth=None):
        for user in self.TESTUSERS + self.ADDREMOVEUSERS:
            subject = self.authserver.getSubject(name=user)
            ok = True
            try:
                self.cli.execute("vm-list",
                                 username=subject.name,
                                 password=subject.password)
                ok = False
            except xenrt.XRTException, e:
                if auth:
                    raise            
            if not ok and not auth:
                raise xenrt.XRTFailure("Removed subject was able to "
                                       "authenticate using CLI")
    
    def sshAuthentication(self,auth=None):
        for user in self.TESTUSERS + self.ADDREMOVEUSERS:
            subject = self.authserver.getSubject(name=user)
            for host in self.poolsToUpgrade[0].getHosts():
                ok = True
                try:
                    if subject.server.domainname:
                        username = "%s\\%s" % (subject.server.domainname,
                                               subject.name)
                    else:
                        username = subject.name
                    host.execdom0("true",
                                  username=username,
                                  password=subject.password)
                    ok = False
                except xenrt.XRTException, e:
                    if auth:
                        if e.reason == "SSH authentication failed":
                            raise xenrt.XRTFailure(e.reason, e.data)
                        raise xenrt.XRTError(e.reason, e.data)
                    else:
                        if e.reason != "SSH authentication failed":
                            raise xenrt.XRTError(e.reason, e.data)
                if not ok and not auth:
                    raise xenrt.XRTFailure("Removed subject was able to "
                                           "authenticate using SSH")
    
    def featureTest(self):
        #Enable AD and add users
        self.poolsToUpgrade[0].enableAuthentication(self.authserver, setDNS=True)
        self.poolsToUpgrade[0].allow(self.authserver.getSubject(name="TC10718userA"), "pool-admin")
        self.poolsToUpgrade[0].allow(self.authserver.getSubject(name="TC10718group2"), "pool-admin")
        self.poolsToUpgrade[0].allow(self.authserver.getSubject(name="TC10718userD"), "pool-admin")
        #Test CLI authentication
        self.cli = self.poolsToUpgrade[0].getCLIInstance()
        self.cliAuthentication(auth=True)
        # Test SSH authentication
        self.sshAuthentication(auth=True)
        #Remove AD users and disable
        self.poolsToUpgrade[0].deny(self.authserver.getSubject(name="TC10718userA"))
        self.poolsToUpgrade[0].deny(self.authserver.getSubject(name="TC10718group2"))
        self.poolsToUpgrade[0].deny(self.authserver.getSubject(name="TC10718userD"))
        self.poolsToUpgrade[0].disableAuthentication(self.authserver, disable=True)
        # Test removed user(s) cannot authenticate
        self.cliAuthentication(auth=False)
        self.sshAuthentication(auth=False)

class ADUpgradeAuthentication(TC10718):

    def prepare(self, arglist):
        self.poolsToUpgrade.append(self.getDefaultPool())
        authguest = self.getGuest(self.AUTHSERVER)
        if not authguest:
            raise xenrt.XRTError("Could not find %s VM" % (self.AUTHSERVER))
        self.authserver = authguest.getActiveDirectoryServer()
        
                       
    def featureTest(self):
        for host in self.poolsToUpgrade[0].getHosts():
            host.setDNSServer(self.authserver.place.getIP())
            
        self.poolsToUpgrade[0].enableAuthentication(self.authserver, setDNS=False)
        self.authserver.createSubjectGraph(self.SUBJECTGRAPH)
        self.poolsToUpgrade[0].allow(\
            self.authserver.getSubject(name="TC10718userA"), "pool-admin")
        self.poolsToUpgrade[0].allow(\
            self.authserver.getSubject(name="TC10718group2"), "pool-admin")
        
        # Add extra user(s) to the subject-list
        self.addExtraUsers()
        
        #Test CLI authentication
        self.cli = self.poolsToUpgrade[0].getCLIInstance()
        self.cliAuthentication(auth=True)

        # Test SSH authentication
        self.sshAuthentication(auth=True)
        #Remove Users and disable
        self.poolsToUpgrade[0].deny(self.authserver.getSubject(name="TC10718userA"))
        self.poolsToUpgrade[0].deny(self.authserver.getSubject(name="TC10718group2"))
        self.poolsToUpgrade[0].deny(self.authserver.getSubject(name="TC10718userD"))
        self.poolsToUpgrade[0].disableAuthentication(self.authserver, disable=True)

        # Test removed user(s) cannot authenticate
        self.cliAuthentication(auth=False)
        self.sshAuthentication(auth=False)

    def run(self, arglist):
        # Perform the upgrade/update
        if self.runSubcase("featureOpUpgrade", (), "Do", "Upgrade") != \
               xenrt.RESULT_PASS:
            return

        # Verify functionality after the upgrade/update
        if self.runSubcase("featureTest", (), "Check", "After") != \
               xenrt.RESULT_PASS:
            return

class TC12611(TC10718):
    """Continued operation of RBAC following host/pool update/upgrade."""

    OPERATIONS = [xenrt.lib.xenserver.call.CLICall("vm-list"),
                  xenrt.lib.xenserver.call.CLICall("pool-emergency-transition-to-master")]

    VALID = ["vm-list"]
    def verifyOperation(self):
        for op in self.OPERATIONS:
            op.context = self.context
            for user in self.TESTUSERS:
                subject = self.authserver.getSubject(name=user)
                try:
                    op.call(self.poolsToUpgrade[0].master, subject)
                except:
                    if op.operation in self.VALID:
                        raise xenrt.XRTFailure("Valid operation failed.")
                else:
                    if not op.operation in self.VALID:
                        raise xenrt.XRTFailure("Invalid operation suceeded.")

    def prepare(self, arglist=[]):
        TC10718.prepare(self, arglist)
        self.context = xenrt.lib.xenserver.context.Context(self.poolsToUpgrade[0])

    def featureTest(self):
        self.poolsToUpgrade[0].enableAuthentication(self.authserver, setDNS=True)
        self.poolsToUpgrade[0].allow(self.authserver.getSubject(name="TC10718userA"), "vm-operator")
        self.poolsToUpgrade[0].allow(self.authserver.getSubject(name="TC10718group2"), "vm-operator")
        self.verifyOperation()
        self.poolsToUpgrade[0].deny(self.authserver.getSubject(name="TC10718userA"))
        self.poolsToUpgrade[0].deny(self.authserver.getSubject(name="TC10718group2"))
        self.poolsToUpgrade[0].disableAuthentication(self.authserver, disable=True)


class TC10721(_FeatureOperationAfterUpgrade):
    """Continued operation of a host with a boot disk on a FC SAN via Emulex HBA following host/pool update/upgrade"""

    def prepare(self, arglist):
        self.hostsToUpgrade.append(self.getDefaultHost())
        if isinstance(self.getDefaultHost(), xenrt.lib.xenserver.MNRHost) and not isinstance(self.getDefaultHost(), xenrt.lib.xenserver.TampaHost):
            self.guest = self.host.createBasicGuest(distro="debian50")
        else:
            self.guest = self.host.createGenericLinuxGuest()
        self.guest.shutdown()

    def postUpgradeHook(self):
        xenrt.TEC().logverbose("Upgrading VM kernel/tools")
        self.guest.start()
        self.guest.installTools()
        self.guest.shutdown()

    def featureTest(self):
        self.hostsToUpgrade[0].check()
        self.guest.start()
        self.guest.reboot()
        self.guest.suspend()
        self.guest.resume()
        self.guest.shutdown()

class TC10753(_FeatureOperationAfterUpgrade):
    """Continued operation of the Workload Balancing feature following host/pool update/upgrade"""

    def prepare(self, arglist):
        self.poolsToUpgrade.append(self.getDefaultPool())
        self.kirkwood = xenrt.lib.createFakeKirkwood(None)
        self.wlbUsername = "wlbuser"
        self.wlbPassword = "wlbpass"
        self.poolsToUpgrade[0].initialiseWLB("%s:%d" % (self.kirkwood.ip,self.kirkwood.port),
                                self.wlbUsername, self.wlbPassword,
                                self.wlbUsername, self.wlbPassword)
        self.nfs = xenrt.ExternalNFSShare()
        nfs = self.nfs.getMount()
        r = re.search(r"([0-9\.]+):(\S+)", nfs)
        if not r:
            raise xenrt.XRTError("Unable to parse NFS paths %s" % (nfs))
        sr = xenrt.lib.xenserver.NFSStorageRepository(self.poolsToUpgrade[0].master, "TC10753")
        sr.create(r.group(1), r.group(2))
        self.sr = sr
        self.poolsToUpgrade[0].addSRToPool(sr)
        if isinstance(self.poolsToUpgrade[0].master, xenrt.lib.xenserver.MNRHost) and not isinstance(self.poolsToUpgrade[0].master, xenrt.lib.xenserver.TampaHost):
            self.guest = self.poolsToUpgrade[0].master.createBasicGuest(distro="debian50", sr=sr.uuid)
        else:
            self.guest = self.poolsToUpgrade[0].master.createGenericLinuxGuest(sr=sr.uuid)
        self.guest.shutdown()

    def featureTest(self):
        recommendations = []
        r = {'CanBootVM':'true',
             'HostUuid':self.poolsToUpgrade[0].master.getMyHostUUID(),
             'RecommendationId':'1',
             'Stars':'5.0'}
        recommendations.append(r)
        i = 2
        for h in self.poolsToUpgrade[0].getSlaves():
            r = {'HostUuid':h.getMyHostUUID(),
                 'RecommendationId':str(i),
                 'ZeroScoreReason':'Other'}
            recommendations.append(r)
            i += 1
        self.kirkwood.recommendations[self.guest.getUUID()] = recommendations
        receivedRecs = self.guest.retrieveWLBRecommendations()
        if len(receivedRecs) != len(self.poolsToUpgrade[0].getHosts()):
            raise xenrt.XRTFailure("Incorrect number of WLB recommendations returned",
                                   data="Expecting %d, received %d" %
                                        (len(self.poolsToUpgrade[0].getHosts()), len(receivedRecs)))
        if not receivedRecs.has_key(self.poolsToUpgrade[0].master.getName()):
            raise xenrt.XRTFailure("Cannot find recommendation for master")
        if not re.search("WLB 5.0 1", receivedRecs[self.poolsToUpgrade[0].master.getName()]):
            raise xenrt.XRTFailure("Recommendation for master not as expected",
                                   data="Expecting 'WLB 5.0 1', found %s" %
                                   (receivedRecs[self.poolsToUpgrade[0].master.getName()]))
        i = 2
        for h in self.poolsToUpgrade[0].getSlaves():
            if not receivedRecs.has_key(h.getName()):
                raise xenrt.XRTFailure("Cannot find recommendation for slave %s" % (h.getName()))
            if not re.search("WLB 0.0 %s Other" % (str(i)), receivedRecs[h.getName()]):
                raise xenrt.XRTFailure("Recommendation for slave %s not as expected" % (h.getName()),
                                       data="Expecting 'WLB 0.0 %s Other', found '%s'" %
                                            (str(i), receivedRecs[h.getName()]))
            i += 1

    def postRun(self):
        try:
            self.guest.uninstall()
            self.sr.remove()
            self.nfs.release()
        except:
            pass

        _FeatureOperationAfterUpgrade.postRun(self)

class _MultipathSingleHostUpgrade(_SingleHostUpgrade):
    """Multipath upgrade tests base class"""

    EXTRASUBCASES = [("checkSR", (), "Check", "SR")]
    SR_MULTIPATHED = False
    ROOT_DISK_MULTIPATHED_NEW = True

    def installOld(self):

        old = xenrt.TEC().lookup("OLD_PRODUCT_VERSION")
        oldversion = xenrt.TEC().lookup("OLD_PRODUCT_INPUTDIR")
        self.host = xenrt.lib.xenserver.createHost(id=0,
                                                   version=oldversion,
                                                   productVersion=old)

        # Create an iSCSI SR
        self.iscsiSR = xenrt.lib.xenserver.ISCSIStorageRepository(self.host, "iscsi")
        self.iscsiSR.create(subtype="lvm", multipathing=self.SR_MULTIPATHED)
        self.host.addSR(self.iscsiSR)

        pbd = self.host.parseListForUUID("pbd-list",
                            "sr-uuid",
                            self.iscsiSR.uuid,
                            "host-uuid=%s" % (self.host.getMyHostUUID()))

        self.scsiid = string.split(self.host.lookup("OPTION_CARBON_DISKS", None), "scsi-")[1]
        self.iscsiSRScsiid = self.host.genParamGet("pbd", pbd, "device-config", "SCSIid")

        mp = self.host.getMultipathInfo(onlyActive=True, useLL=True)

        if not self.SR_MULTIPATHED and mp.has_key(self.iscsiSRScsiid) and len(mp[self.iscsiSRScsiid]) > 1:
            raise xenrt.XRTFailure("Expecting 1/4 paths active for ISCSI SR, found %u" % (len(mp[self.iscsiSRScsiid])))

        if self.SR_MULTIPATHED and ((not mp.has_key(self.iscsiSRScsiid)) or len(mp[self.iscsiSRScsiid]) < 2):
            raise xenrt.XRTFailure("Expecting 4/4 paths active for ISCSI SR, found %u" % (len(mp[self.iscsiSRScsiid])))

        # on cowley and later you need to explicitly enable multipath root disk
        if self.ROOT_DISK_MULTIPATHED_NEW:
            xenrt.TEC().config.setVariable("OPTION_ROOT_MPATH", "enabled")
        else:
            xenrt.TEC().config.setVariable("OPTION_ROOT_MPATH", "")

    def checkSR(self):

        mp = self.host.getMultipathInfo(onlyActive=True, useLL=True)

        if not self.ROOT_DISK_MULTIPATHED_NEW and mp.has_key(self.scsiid) and len(mp[self.scsiid]) > 1:
            raise xenrt.XRTFailure("Expecting 1/2 paths active for root disk, found %u" % (len(mp[self.scsiid])))

        if self.ROOT_DISK_MULTIPATHED_NEW and ((not mp.has_key(self.scsiid)) or len(mp[self.scsiid]) < 2):
            raise xenrt.XRTFailure("Expecting 2/2 paths active for root disk, found 1")

        if not self.SR_MULTIPATHED and mp.has_key(self.iscsiSRScsiid) and len(mp[self.iscsiSRScsiid]) > 1:
            raise xenrt.XRTFailure("Expecting 1/4 paths active for ISCSI SR, found %u" % (len(mp[self.iscsiSRScsiid])))

        if self.SR_MULTIPATHED and ((not mp.has_key(self.iscsiSRScsiid)) or len(mp[self.iscsiSRScsiid]) < 2):
            raise xenrt.XRTFailure("Expecting 4/4 paths active for ISCSI SR, found 1")

    def postRun(self):
        if self.iscsiSR:
            self.iscsiSR.release()

class TC12210(_MultipathSingleHostUpgrade):
    """Test upgrade from single path iSCSI SR to single path root disk"""
    SR_MULTIPATHED = False
    ROOT_DISK_MULTIPATHED_NEW = False

class TC12186(_MultipathSingleHostUpgrade):
    """Test upgrade from single path iSCSI SR to multipathed root disk"""
    SR_MULTIPATHED = False
    ROOT_DISK_MULTIPATHED_NEW = True

class TC12211(_MultipathSingleHostUpgrade):
    """Test upgrade from multipath path iSCSI SR to single path root disk"""
    SR_MULTIPATHED = True
    ROOT_DISK_MULTIPATHED_NEW = False

class TC12212(_MultipathSingleHostUpgrade):
    """Test upgrade from multipath path iSCSI SR to multipathed root disk"""
    SR_MULTIPATHED = True
    ROOT_DISK_MULTIPATHED_NEW = True

class _RpuNewPartitionsSingleHost(_SingleHostUpgrade):

    EXTRASUBCASES = [("checkPartitions", (), "Check", "Partitions"), ("checkSRs", (), "Check", "SRs")]
    SAFE2UPGRAGE_CHECK = True
    NEW_PARTITIONS = False

    def checkPartitions(self, arglist=[]):
        step("Check if dom0 partitions are as expected")
        if self.NEW_PARTITIONS:
            partitions = xenrt.TEC().lookup(["VERSION_CONFIG",xenrt.TEC().lookup("PRODUCT_VERSION"),"DOM0_PARTITIONS"])
        else:
            partitions = xenrt.TEC().lookup(["VERSION_CONFIG",xenrt.TEC().lookup("PRODUCT_VERSION"),"DOM0_PARTITIONS_OLD"])
        log("Expected partitions: %s" % partitions)

        if not self.host.compareDom0Partitions(partitions):
            raise xenrt.XRTFailure("Found unexpected partitions on XS clean install. Expected: %s Found: %s" % (partitions, self.host.getDom0Partitions()))
        log("Found expected Dom0 partitions on XS clean installation: %s" % partitions)

    def checkSRs(self):
        step("Check if SRs are working fine")
        self.host.checkSRs(type=["lvm","ext"])

class TCRpuNewPartSingle(_RpuNewPartitionsSingleHost):
    """TC-27063 - Dom0 disk partitioning on single host upgrade with no VMs on local storage"""

    NEW_PARTITIONS = True
    NO_VMS = True

class TCRpuOldPartSingle(_RpuNewPartitionsSingleHost):
    """TC-27064 - Dom0 disk partitioning on single host upgrade with VMs on local storage"""

    NEW_PARTITIONS = False
    NO_VMS = False
    
class TCRpuPrimaryDisk(_RpuNewPartitionsSingleHost):
    """TC-27064 - Dom0 disk partitioning on single host upgrade with VMs on local storage(additional Local SR)"""

    NEW_PARTITIONS = True
    NO_VMS = False

    def installVMs(self):
        #Create Local SR
        sr = self.createLocalSR()
        g = self.host.createBasicGuest("generic-linux", sr=sr.uuid)
        g.shutdown()
        self.guests.append(g)
    
    def createLocalSR(self):
        srType = xenrt.TEC().lookup("SECOND_SR_TYPE", "lvm")
        if srType == "lvm":
            sr = xenrt.lib.xenserver.LVMStorageRepository(self.host, "Second Local Storage")
        elif srType == "ext":
            sr = xenrt.lib.xenserver.EXTStorageRepository(self.host, "Second\ Local\ Storage")
        defaultlist = "sda sdb"
        guestdisks = string.split(self.host.lookup("OPTION_CARBON_DISKS", defaultlist))
        if len(guestdisks) < 2:
            raise xenrt.XRTError("Wanted 2 disks but we only have: %s" % (len(guestdisks)))
        sr.create("/dev/%s" % (guestdisks[1]))
        poolUUID = self.host.minimalList("pool-list")[0]
        self.host.genParamSet("pool", poolUUID, "default-SR", sr.uuid)
        return sr

class TC14930(_FeatureOperationAfterUpgrade):
    """Continued operation of VMPP feature"""

    def prepare(self, arglist=[]):

        self.pool = self.getDefaultPool()
        self.poolsToUpgrade.append(self.pool)
        self.pool.linux = None
        for h in self.pool.getHosts(): h.license(edition='platinum')

        self.vmpp = self.pool.createVMPP("assoc", "snapshot", "hourly")
        self.vm = self.getvm(self.pool,'DOWN')
        self.noVMPP(self.vm, "create")
        self.vm.paramSet("protection-policy", self.vmpp)

    def getvm(self,pool,state):

        name = "copiedVM"
        pool.linux = xenrt.TEC().gec.registry.guestGet('linux')
        pool.linux.goState('DOWN')
        vm = pool.linux.cloneVM(name=name) or pool.linux
        vm.tailored = True
        xenrt.TEC().registry.guestPut(vm.getName(), vm)
        self.uninstallOnCleanup(vm)
        vm.goState(state)
        return vm

    def cloneToNew(self, vm):
        return vm.cloneVM()

    def noVMPP(self, vm, op):

        time.sleep(10)
        pp = vm.paramGet('protection-policy')
        if pp != "<not in database>":
            raise xenrt.XRTFailure("We expect a VM created by %s with no "
                                   "VMPP assigned." % op)

    def newVMVerif(self, op, vm):

        newvm = eval("self." + op + "ToNew")(vm)
        newvm.tailored = True
        newvm.start()
        self.noVMPP(newvm, op)
        newvm.shutdown(again=True)
        newvm.uninstall()

    def featureTest(self):

        vm_uuid = self.vm.getUUID()
        expect = (vm_uuid in self.pool.getVMPPConf(vmpp=self.vmpp)['VMs']
                  and self.vm.paramGet("protection-policy") == self.vmpp)
        if not expect:
            raise xenrt.XRTFailure("VM %s and VMPP %s are not conencted as we "
                                   "expect." % (vm_uuid, self.vmpp))
        op = "clone"
        if self.runSubcase("newVMVerif", (op, self.vm), "VM-VMPP", op) != xenrt.RESULT_PASS:
            raise xenrt.XRTFailure("Error occured while checking vmpp on vm %s" % (self.vm))

class TC14931(_FeatureOperationAfterUpgrade):
    """Continued operation of SR-IOV"""

    MAX_VF_PER_VM = 16

    def prepare(self, arglist=None):

        self.host = self.getDefaultHost()
        self.hostsToUpgrade.append(self.host)

        # Let us install/use two guests for all tests

        self.guest_01 = self.host.installHVMLinux()
        self.uninstallOnCleanup(self.guest_01)

        self.io = xenrt.lib.xenserver.IOvirt(self.host)
        self.io.enableIOMMU()
        self.assignVFsToVM(self.guest_01, 1)

    def getSRIOVEthDevices(self):

        self.io.queryVFs()
        return self.io.getSRIOVEthDevices()

    def getFreeVFsPerEth(self, eths_to_use=None):

        eth_devs = self.getSRIOVEthDevices()

        if eths_to_use is not None:
            eths_to_use = set(eths_to_use)
            eth_devs = eth_devs.intersection(eths_to_use)

        free_vfs = {}
        for eth_dev in eth_devs:
            l = self.io.getFreeVFs(eth_dev)
            if len(l) > 0:
                free_vfs[eth_dev] = l

        return free_vfs

    def assignVFsToVM(self,
                           guest,
                           n,
                           strict=False,
                           eths_to_use=None,
                           mac=None,
                           vlan=None):

        vm_uuid = guest.getUUID()
        curr_pci_assignment = self.io.getVMInfo(vm_uuid)

        fn = lambda x: x[1] == 'vf'
        curr_vf_assignment = [x[0] for x in curr_pci_assignment if fn(x)]

        if n + len(curr_vf_assignment) > self.MAX_VF_PER_VM:
            raise xenrt.XRTError("Invalid test: max number of VF assignment (%s) > %s"
                                 % (n + len(curr_vf_assignment),
                                    self.MAX_VF_PER_VM))

        free_vfs_per_eth = self.getFreeVFsPerEth(eths_to_use)

        num_free_vfs = sum([len(vfs) for vfs in free_vfs_per_eth.values()])

        if n > num_free_vfs:
            if strict:
                return 0 #Our assignment failed
            else:
                n = num_free_vfs

        times = lambda x, n : [x for i in range(n)]

        vf_list = []
        for eth_dev, vfs in free_vfs_per_eth.items():
            vf_list.extend(zip(times(eth_dev, len(vfs)), vfs))

        for i in range(n):
            self.io.assignFreeVFToVM(vm_uuid,
                                         vf_list[i][0],
                                         vlan,
                                         mac)
        return n

    def getVFsAssignedToVM(self, guest):
        vm_uuid = guest.getUUID()
        pci_devs_assigned_to_vm = self.io.getVMInfo(vm_uuid)

        vfs_assigned = [pciid for pciid in pci_devs_assigned_to_vm.keys()
                        if pci_devs_assigned_to_vm[pciid]['pttype'] == 'vf']

        return set(vfs_assigned)

    def checkPCIDevicesInVM(self, guest):
        # make sure that vm is UP
        if guest.getState() == "UP":
            pass
        else:
            guest.start()
            guest.waitForSSH(300)

        self.io.checkPCIDevsAssignedToVM(guest)

    def featureTest(self):

        self.guest_01.start()

        vfs = self.getVFsAssignedToVM(self.guest_01)
        xenrt.TEC().logverbose("VFs assigned to VM (%s): %s"
                               % (self.guest_01.getUUID(), vfs))

        self.checkPCIDevicesInVM(self.guest_01)

        self.guest_01.shutdown()

class TC14932(_FeatureOperationAfterUpgrade):
    """Continued operation of active passive bonding"""

    BOND_MODE = "active-backup"

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.hostsToUpgrade.append(self.host)
        # Check we don't already have a bond...
        if len(self.host.getBonds()) > 0:
            raise xenrt.XRTError("Host already has a bond interface")

        # Create the bond
        newpifs = self.findPIFToBondWithManagementNIC(self.host)
        (self.bridge,self.device) = self.host.createBond(newpifs,dhcp=True,management=True,mode=self.BOND_MODE)

        # Give it 20 seconds to do DHCP etc
        time.sleep(20)

        # Check the bond status
        (info,slaves) = self.host.getBondInfo(self.device)
        if len(info['slaves']) != 2:
            raise xenrt.XRTFailure("Bond has %u slave devices, expected 2" %
                                   (len(info['slaves'])))

        # Check the bond mode if we specified one
        if self.BOND_MODE:
            if not re.search(self.BOND_MODE, info['mode']):
                raise xenrt.XRTFailure("We requested %s bonding, found %s" %
                                       (self.BOND_MODE, info['mode']))

    def featureTest(self):

        (info,slaves) = self.hostsToUpgrade[0].getBondInfo(self.device)
        if len(info['slaves']) != 2:
            raise xenrt.XRTFailure("Bond has %u slave devices, "
                                   "expected 2" % (len(info['slaves'])))
        if self.BOND_MODE:
            if not re.search(self.BOND_MODE, info['mode']):
                raise xenrt.XRTFailure("%s bond had become %s" %
                                       (self.BOND_MODE, info['mode']))
        self.hostsToUpgrade[0].check(interfaces=[(self.bridge, "yes", "dhcp", None, None, None, None, None, None)])

    def findPIFToBondWithManagementNIC(self, host):
        """Returns a list of two PIF UUIDs. The first in the list is the
        management interface and the second is an interface suitable to
        join with the current management NIC in a bond.
        """
        # Assume that the current management NIC is on the default NIC.
        managementPIF = host.parseListForUUID("pif-list","management","true")
        managementNIC = host.genParamGet("pif", managementPIF, "device")
        if managementNIC != host.getDefaultInterface():
            raise xenrt.XRTError("Management interface not initially "
                                 "on default interface")

        # Find another interface on the NPRI network (same as the default NIC)
        assumedids = host.listSecondaryNICs("NPRI")
        if len(assumedids) == 0:
            raise xenrt.XRTError("Could not find a secondary NIC on NPRI")

        # Get the PIF for this interface
        secNIC = host.getSecondaryNIC(assumedids[0])
        secPIF = host.parseListForUUID("pif-list","device",secNIC)

        return [managementPIF, secPIF]

class TC18591(_FeatureOperationAfterUpgrade):
    """Continued operation of NS VPXs 9.3 and 10.0"""

    allocatedIPAddrs = []

    def importNsXva(self, host, xva):
        distfiles = xenrt.TEC().lookup('EXPORT_DISTFILES_NFS', None)
        host.execdom0('mkdir -p /mnt/distfiles')
        host.execdom0('mount %s /mnt/distfiles' % distfiles)
        vm_uuid =  host.execdom0('xe vm-import filename=/mnt/distfiles/tallahassee/%s' % xva).strip()
        gName = xenrt.randomGuestName()
        host.genParamSet("vm", vm_uuid, "name-label", gName)
        host.execdom0('umount /mnt/distfiles')

        s_obj = xenrt.StaticIP4Addr()
        (_, netmask, gw) = host.getNICAllocatedIPAddress(0)
        self.allocatedIPAddrs.append(s_obj)
        ip = s_obj.getAddr()
        host.execdom0("xe vm-param-add uuid=%s param-name=xenstore-data vm-data/ip=%s" % (vm_uuid, ip))
        host.execdom0("xe vm-param-add uuid=%s param-name=xenstore-data vm-data/netmask=%s" % (vm_uuid, netmask))
        host.execdom0("xe vm-param-add uuid=%s param-name=xenstore-data vm-data/gateway=%s" % (vm_uuid, gw))
        vpx = host.guestFactory()(gName, host=host)
        vpx.uuid = vm_uuid
        vpx.mainip = ip
        vpx.password = 'nsroot'
        return vpx

    def getLicenseFile(self):
        lic = "CNS_V1000_SERVER_PLT_Retail.lic"
        working = xenrt.TEC().getWorkdir()
        out = os.path.join(working, lic)
        lic_url = "http://www.uk.xensource.com/~jobyp/CNS_V1000_SERVER_PLT_Retail.lic"
        xenrt.command('wget %s -O %s' % (lic_url, out))
        self.license_file = out
        return self.license_file

    def installLicense(self, vpx):
        if self.license_file is None:
            self.license_file = self.getLicenseFile()

        if vpx.getState() != "UP":
            vpx.start()
            time.sleep(180)
            vpx.waitForSSH(600, desc="Waiting for NS VPX to boot", username="nsroot", cmd="show ns ip")
        sftp = vpx.sftpClient(username='nsroot')
        sftp.copyTo(self.license_file, os.path.join("/nsconfig/license", os.path.basename(self.license_file)))
        sftp.close()
        vpx.reboot()
        vpx.waitForSSH(600, desc="Waiting for NS VPX to reboot", username="nsroot", cmd="show ns ip")
        return

    def installNSVPX(self, host, xva):
        vpx = self.importNsXva(host, xva)
        self.installLicense(vpx)
        return vpx

    def prepare(self, arglist):
        vpx_xvas = ["NSVPX-XEN-10.0-72.5_nc.xva", "NSVPX-XEN-9.3-60.3_nc.xva"]
        self.license_file = None
        self.host = self.getDefaultHost()
        self.hostsToUpgrade.append(self.host)
        self.VPXs = [self.installNSVPX(self.host, xva) for xva in vpx_xvas]
        return

    def featureTest(self):

        for vpx in self.VPXs:
            if vpx.getState() == "DOWN":
                vpx.start()
                vpx.waitForSSH(600, desc="Waiting for NS VPX to boot", username="nsroot", cmd="show ns ip")

        for vpx in self.VPXs:
            vpx.execguest('show ns ip', username='nsroot')
        return

    def postRun(self):

        for s_obj in self.allocatedIPAddrs:
            s_obj.release()

        _FeatureOperationAfterUpgrade.postRun(self)
        return


class TC15194(_FeatureOperationAfterUpgrade):
    """Continued operation of hidden Management interface"""

    def prepare(self, arglist=None):

        self.host = self.getDefaultHost()
        self.hostsToUpgrade.append(self.host)

        self.guest = self.host.installHVMLinux()
        self.uninstallOnCleanup(self.guest)
        mac = xenrt.randomMAC()
        xenapi_uuid = self.getHostInternalNetworkUuid()
        self.bridge = self.host.genParamGet("network", xenapi_uuid, "bridge")
        self.guest.createVIF(bridge=self.bridge, mac=mac)
        if self.guest.getState() == "DOWN":
            self.guest.start()
            self.guest.waitForSSH(900)
        self.guest_uuid = self.guest.getUUID()
        self.host_uuid = self.host.getMyHostUUID()
        self.mng_pif_uuid = self.host.parseListForUUID("pif-list",
                                                       "management",
                                                       "true",
                                                       "host-uuid=%s" %
                                                       self.host_uuid).strip()

    def getHostInternalNetworkUuid(self):

        xenapi_uuid = ""
        for uuid in self.hostsToUpgrade[0].minimalList("network-list", "uuid"):
            try:
                is_host_internal_management_network = self.hostsToUpgrade[0].genParamGet("network",
                                                                            uuid,
                                                                            "other-config",
                                                                            pkey="is_host_internal_management_network")
                if is_host_internal_management_network.strip() == "true":
                    xenapi_uuid = uuid.strip()
                    break
            except:
                pass

        if len(xenapi_uuid.strip()) == 0:
            raise xenrt.XRTFailure("No network found with 'is_host_internal_management_network' set to true")

        return xenapi_uuid

    def getXenapiNetworkID(self):

        xenapi_uuid = self.getHostInternalNetworkUuid()
        other_config = self.hostsToUpgrade[0].genParamGet("network", xenapi_uuid, "other-config")

        xenapi_other_config = dict([tuple(i.split(':'))
                                   for i in other_config.replace(' ', '').split(';')])

        xenapi_IP = IPy.IP("%s/%s" % (xenapi_other_config['ip_begin'],
                                     xenapi_other_config['netmask']),
                          make_net=True)
        return xenapi_IP

    def getVMIPAddress(self, guest):

        output_lines = guest.execcmd('ip -4 -o addr show').splitlines()
        return [line.split()[3] for line in output_lines]

    def heyXapiYouThere(self, guest, xenapi_ip):
        ret = self.guest.execcmd('wget -O /dev/null http://%s' % xenapi_ip, retval="code")
        if ret != 0:
            raise xenrt.XRTFailure("Xapi is not reachable from VM on %s" % xenapi_ip)


    def checkIfXapiIsReachable(self, guest, xenapi_ip):

        self.heyXapiYouThere(guest, xenapi_ip)
        self.guest.execcmd('nohup /sbin/shutdown -r now &> /dev/null < /dev/null & exit 0')
        time.sleep(180)
        guest.waitForSSH(900)
        self.heyXapiYouThere(guest, xenapi_ip)


    def waitForHostToBeEnabled(self, timeout=300):
        now = xenrt.util.timenow()
        deadline = now + timeout

        while True:
            ret = self.hostsToUpgrade[0].execdom0('xe host-param-get param-name=enabled uuid=%s ' %
                                     self.host_uuid).strip()

            if ret == 'true':
                return

            now = xenrt.util.timenow()
            if now > deadline:
                ret = self.hostsToUpgrade[0].execdom0('uptime')
                raise xenrt.XRTFailure('host is not enabled after the reboot')

            time.sleep(60)

    def checkIfXapiIsReachableFromExternalWorld(self):
        cli = self.hostsToUpgrade[0].getCLIInstance()
        try:
            cli.execute('vm-list')
        except:
            pass
        else:
            raise xenrt.XRTFailure('Xapi is reachable from external world with host management disabled')


    def featureTest(self):

        if self.guest.getState() == "DOWN":
            self.guest.start()
        xenapi_IP = self.getXenapiNetworkID()
        xenapi_ip = xenapi_IP[1]

        #1. Check if we can reach Xapi from VM
        self.checkIfXapiIsReachable(self.guest, xenapi_ip)

        #2. Disable management interface
        xenrt.TEC().logverbose("Disabling host management interface")
        self.hostsToUpgrade[0].execcmd("xe host-management-disable")

        #3. Check if we can reach Xapi from VM
        self.checkIfXapiIsReachable(self.guest, xenapi_ip)

        #4. Make sure that xapi is not reachable from outside.
        self.checkIfXapiIsReachableFromExternalWorld()

        self.guest.shutdown()

    def postRun(self):
        self.hostsToUpgrade[0].execcmd("xe host-management-reconfigure pif-uuid=%s" % self.mng_pif_uuid)


class TC15290(xenrt.TestCase):
    """Check that host evacuate is prevented when there are started HVM guests without PV drivers installed."""

    def run(self, arglist=None):
        h0 = self.getHost("RESOURCE_HOST_0")
        h1 = self.getHost("RESOURCE_HOST_1")

        # start an HVM guest on the master and don't install PV drivers
        guestUuid = h0.execdom0('xe vm-install new-name-label="winguest" template-name="Windows 7 (32-bit)"').strip()
        h0.execdom0('xe vm-cd-add uuid=%s cd-name="win7-x86.iso" device=hdd' % guestUuid)
        h0.execdom0('xe vm-start uuid=%s on=%s' % (guestUuid, h0.getName()))

        # check we can't evacuate
        if not guestUuid in h0.execdom0('xe host-get-vms-which-prevent-evacuation uuid=%s' % h0.uuid).strip():
            raise xenrt.XRTFailure("Shouldn't be allowed to evacuate with HVM guest and no PV drivers")


class TCUpgradeVMMigrate(xenrt.TestCase):

    def prepare(self, arglist):
        self.__balloonTo = None

        for arg in arglist:
            if arg.startswith("BalloonTo"):
                  self.__balloonTo = arg.split("=")[-1]

    def run(self, arglist=None):
        oldHost = self.getHost("RESOURCE_HOST_0")
        newHost = self.getHost("RESOURCE_HOST_1")

        items = self.tcsku.split("/")
        if len(items) == 3:
            distro = items[0]
            arch = items[1]
            memory = items[2]
        else:
            distro = items[0]
            arch = None
            memory = items[1]

        memory = self.__getMemorySize(memory)

        g = oldHost.createBasicGuest(distro=distro, arch=arch, memory=memory)

        if self.__balloonTo:
            xenrt.TEC().logverbose("Ballooning Memory to %s" % self.__balloonTo)
            balloonMemory = self.__getMemorySize(self.__balloonTo)
            g.setDynamicMemRange(balloonMemory, balloonMemory)

        g.migrateVM(remote_host=newHost, remote_user="root", remote_passwd=newHost.password)
        g.verifyGuestFunctional()
        g.uninstall()

    def __getMemorySize(self, memory):
        if memory[-1] == "M":
            memory = int(memory[:-1])
        elif memory[-1] == "G":
            memory = int(memory[:-1]) * 1024

        return memory

class TCRollingPoolUpdate(xenrt.TestCase, xenrt.lib.xenserver.host.RollingPoolUpdate):
    """
    Base class for Rolling Pool update/upgrade
    """

    UPGRADE = True

    def parseArgs(self, arglist):
        #Parse the arguments
        args = self.parseArgsKeyValue(arglist)
        if "INITIAL_VERSION" in args.keys():
            self.INITIAL_VERSION = args["INITIAL_VERSION"]
        if "FINAL_VERSION" in args.keys():
            self.FINAL_VERSION   = args["FINAL_VERSION"]
        if "vmActionIfHostRebootRequired" in args.keys():
            self.vmActionIfHostRebootRequired = args["vmActionIfHostRebootRequired"]
        if "applyAllHFXsBeforeApplyAction" in args.keys() and args["applyAllHFXsBeforeApplyAction"].lower() =="no":
            self.applyAllHFXsBeforeApplyAction = False
        if "skipApplyRequiredPatches" in args.keys() and args["skipApplyRequiredPatches"].lower() == "yes":
            self.skipApplyRequiredPatches = True

    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        self.newPool = None
        self.INITIAL_VERSION = self.pool.master.productVersion
        self.FINAL_VERSION = None
        self.vmActionIfHostRebootRequired = "SHUTDOWN"
        self.applyAllHFXsBeforeApplyAction = True
        self.preEvacuate = None
        self.preReboot = None
        self.skipApplyRequiredPatches = False
        
        #Parse arguments coming from sequence file
        self.parseArgs(arglist)

        # Eject CDs in all VMs
        for h in self.pool.getHosts():
            for guestName in h.listGuests():
                self.getGuest(guestName).changeCD(None)

        xenrt.lib.xenserver.host.RollingPoolUpdate.__init__(self, poolRef = self.pool, 
                                                            newVersion=self.FINAL_VERSION,
                                                            upgrade = self.UPGRADE,
                                                            applyAllHFXsBeforeApplyAction=self.applyAllHFXsBeforeApplyAction,
                                                            vmActionIfHostRebootRequired=self.vmActionIfHostRebootRequired,
                                                            preEvacuate=self.preEvacuate,
                                                            preReboot=self.preReboot,
                                                            skipApplyRequiredPatches=self.skipApplyRequiredPatches)

    def run(self, arglist=None):
        self.preCheckVMs(self.pool)
        self.doUpdate()
        self.postCheckVMs(self.newPool)

    def preCheckVMs(self,pool):
        self.expectedRunningVMs = 0
        for h in pool.getHosts():
            runningGuests = h.listGuests(running=True)
            xenrt.TEC().logverbose("Host: %s has %d running guests [%s]" % (h.getName(), len(runningGuests), runningGuests))
            self.expectedRunningVMs += len(runningGuests)
        xenrt.TEC().logverbose("Pre-upgrade running VMs: %d" % (self.expectedRunningVMs))

    def postCheckVMs(self,pool):
        postUpgradeRunningGuests = 0
        for h in pool.getHosts():
            h.verifyHostFunctional(migrateVMs=False)

            runningGuests = h.listGuests(running=True)
            xenrt.TEC().logverbose("Host: %s has %d running guests [%s]" % (h.getName(), len(runningGuests), runningGuests))
            postUpgradeRunningGuests += len(runningGuests)

        xenrt.TEC().logverbose("Post-upgrade running VMs: %d" % (postUpgradeRunningGuests))
        if self.expectedRunningVMs != postUpgradeRunningGuests:
            xenrt.TEC().logverbose("Expected VMs in running state: %d, Actual: %d" % (self.expectedRunningVMs, postUpgradeRunningGuests))
            raise xenrt.XRTFailure("Not all VMs in running state after upgrade complete") 

class TCRpuPartitions(TCRollingPoolUpdate):
    """
    Perform Rolling pool upgrade after calling testSafe
    """
    NEW_PARTITIONS = {}

    def preMasterUpdate(self):
        TCRollingPoolUpdate.preMasterUpdate(self)
        self.checkSafe2Upgrade(self.newPool.master)

    def preSlaveUpdate(self, slave):
        TCRollingPoolUpdate.preSlaveUpdate(self, slave)
        self.checkSafe2Upgrade(slave)

    def postMasterUpdate(self):
        TCRollingPoolUpdate.postMasterUpdate(self)
        self.checkPartitions(self.newPool.master)
        self.newPool.master.checkSRs(type=["lvm","ext"])

    def postSlaveUpdate(self, slave):
        TCRollingPoolUpdate.postSlaveUpdate(self, slave)
        self.checkPartitions(slave)
        slave.checkSRs(type=["lvm","ext"])

    def checkSafe2Upgrade(self, host):
        self.NEW_PARTITIONS[host.getName()] = host.checkSafe2Upgrade()

    def checkPartitions(self, host):
        """Function to check if DOM0 partitions are as expected"""
        step("Check if dom0 partitions are as expected")
        if self.NEW_PARTITIONS[host.getName()]:
            partitions = xenrt.TEC().lookup(["VERSION_CONFIG",xenrt.TEC().lookup("PRODUCT_VERSION"),"DOM0_PARTITIONS"])
        else:
            partitions = xenrt.TEC().lookup(["VERSION_CONFIG",xenrt.TEC().lookup("PRODUCT_VERSION"),"DOM0_PARTITIONS_OLD"])
        log("Expected partitions: %s" % partitions)

        if not host.compareDom0Partitions(partitions):
            raise xenrt.XRTFailure("Found unexpected partitions on XS clean install. Expected: %s Found: %s" % (partitions, host.getDom0Partitions()))
        log("Found expected Dom0 partitions on XS clean installation: %s" % partitions)

class TCUpgradeRestore(xenrt.TestCase):
    """This test upgrade the host, then restore the old version and upgrade it again and check dom0 partitions are as expected"""
    #TC-27086

    NEW_PARTITIONS = True

    def prepare(self, arglist=None):
        #Parse the arguments
        args = self.parseArgsKeyValue(arglist)
        self.NEW_PARTITIONS = args.get("NEW_PARTITIONS", "True") == "True" or isinstance(self.getDefaultHost(), xenrt.lib.xenserver.DundeeHost)

    def run(self, arglist=None):
        host = self.getDefaultHost()

        if self.NEW_PARTITIONS:
            step("Call safe to upgrade plugins")
            host.checkSafe2Upgrade()
        step("Current partitions of host")
        partitions1 = host.getDom0Partitions()

        step("Upgrade the host to %s" % xenrt.TEC().lookup("PRODUCT_VERSION", None))
        newhost = host.upgrade(xenrt.TEC().lookup("PRODUCT_VERSION", None))
        step("Check partitions of host after upgrade")
        partitions2 = newhost.getDom0Partitions()
        self.checkPartitions(newhost)

        step("Restore the host to %s" % xenrt.TEC().lookup("OLD_PRODUCT_VERSION", None))
        newhost.restoreOldInstallation()
        step("Partitions of host after restore")
        partitions3 = host.getDom0Partitions()
        expectedPartitions = host.lookup("DOM0_PARTITIONS")
        if not host.compareDom0Partitions(expectedPartitions):
            raise xenrt.XRTFailure("Found unexpected partitions on XS restore. Expected: %s Found: %s" % (expectedPartitions, partitions3()))

        step("Upgrade the host again to %s" % xenrt.TEC().lookup("PRODUCT_VERSION", None))
        newhost = host.upgrade(xenrt.TEC().lookup("PRODUCT_VERSION", None))
        step("Partitions of host after upgrade")
        partitions4 = newhost.getDom0Partitions()
        self.checkPartitions(newhost)
        if not newhost.compareDom0Partitions(partitions2):
            raise xenrt.XRTFailure("Partitions on XS upgrade is not same as previous upgrade. Expected: %s Found: %s" % (partitions2, partitions4()))

    def checkPartitions(self, host):
        """Function to check if DOM0 partitions are as expected"""
        step("Check if dom0 partitions are as expected")
        if self.NEW_PARTITIONS:
            partitions = host.lookup("DOM0_PARTITIONS")
        else:
            partitions = host.lookup("DOM0_PARTITIONS_OLD")
        log("Expected partitions: %s" % partitions)

        if not host.compareDom0Partitions(partitions):
            raise xenrt.XRTFailure("Found unexpected partitions. Expected: %s Found: %s" % (partitions, host.getDom0Partitions()))
        log("Found expected Dom0 partitions: %s" % partitions)
