#
# XenRT: Test harness for Xen and the XenServer product family
#
# Host networking standalone testcases
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy, os, subprocess
import urllib2
import xenrt
import xenrt.lib.xenserver
from xenrt.lazylog import step, comment, log
import itertools
import xenrt.util, xenrt.rootops

class _TC7485(xenrt.TestCase):
    """Use a Windows VM as a PXE server."""
        
    def doit(self, pxebridge, clientmac):
        raise xenrt.XRTError("Method not implemented in parent class")
        
    def prepare(self, arglist):
        self.host = None
        self.pxeservername = "pxeserver"
        self.pxeroot = "c:\\tftproot"
        self.pxenetwork = "pxenetwork"
        self.linuxversion = "rhel54"
        self.guestsToClean = []

    def run(self, arglist=None):
        # This test requires ARPWATCH_PRIMARY and CONFOTHERNET to be true.
        self.host = self.getDefaultHost()

        for arg in arglist:
            l = string.split(arg, "=")
            if l[0] == "pxeserver":
                self.pxeservername = l[1]
            if l[0] == "pxeroot":
                self.pxeroot = l[1]
            if l[0] == "distro":
                self.linuxversion = l[1]
            if l[0] == "pxenetwork":
                self.pxenetwork = l[1]
            
        # Set PXE_SERVER.
        self.oldpxe = xenrt.TEC().lookup("PXE_SERVER", None)
        xenrt.TEC().config.setVariable("PXE_SERVER", self.pxeservername)
        self.pxeserver = xenrt.TEC().registry.guestGet(self.pxeservername)
        self.getLogsFrom(self.pxeserver)

        # Get the name of the VIF attached to self.pxenetwork.
        pxeservervifs = self.pxeserver.getVIFs()
        pxebridge = self.host.parseListForOtherParam("network-list",
                                                     "name-label",
                                                      self.pxenetwork,
                                                     "bridge")
        pxeinterface = [ x for x in pxeservervifs \
                            if pxebridge in pxeservervifs[x] ][0]
        publicinterface = [ x for x in pxeservervifs \
                            if self.host.getPrimaryBridge() in pxeservervifs[x] ][0]

        # Install PXE server.
        self.pxeserver.installWindowsDHCPServer(pxeinterface)
        self.pxeserver.installWindowsTFTPServer(tftproot=self.pxeroot)
        self.pxeserver.installWindowsNATServer(publicinterface, pxeinterface)

        clientmac = xenrt.randomMAC()

        # Workaround for CA-16162.
        self.host.execdom0("ethtool -K vif%s.%s tx off" % 
                           (self.pxeserver.getDomid(), 
                            pxeinterface.strip(self.pxeserver.vifstem)))

        # Install our VM
        self.doit(pxebridge, clientmac)

    def postRun(self):
        for g in self.guestsToClean:
            try:
                g.shutdown(force=True)
            except:
                pass
            try:
                g.uninstall()
            except:
                pass
        # Try and clean up the server.
        try:
            for f in self.pxeserver.xmlrpcGlobpath("c:\\windows\\system32\\dhcp\\dhcpsrvlog*"):
                self.pxeserver.xmlrpcGetFile(f, 
                                            "%s/%s" % 
                                            (xenrt.TEC().getLogdir(), re.sub(r".*\\", "", f)))
        except:
            pass
        try:
            self.pxeserver.xmlrpcExec("net stop tftpd")
            self.pxeserver.xmlrpcExec("sc delete tftpd")
            self.pxeserver.xmlrpcExec("net stop RemoteAccess")
            self.pxeserver.xmlrpcExec("netsh routing ip nat uninstall")
            self.pxeserver.xmlrpcDelTree("%s" % (self.pxeroot))
            self.pxeserver.winRegAdd("HKLM", 
                                     "system\\currentcontrolset\\services\\tcpip\\parameters",
                                     "IPEnableRouter",
                                     "DWORD",
                                      0)
            self.pxeserver.xmlrpcExec("sc config RemoteAccess start= disabled")
            self.pxeserver.uninstallWindowsDHCPServer()
            xenrt.TEC().config.setVariable("PXE_SERVER", self.oldpxe)
        except:
            pass

class TC8773(_TC7485):
    """Test Windows VMs Booting From A Windows PXE Server"""

    def doit(self, pxebridge, clientmac):
        # Windows test.
        xenrt.getTestTarball("native", extract=True)
        pxe = xenrt.PXEBoot(place=self.pxeserver)
        pxe.copyIn("%s/native/pxe/pxeboot.0" % (xenrt.TEC().getWorkdir()))
        self.pxeserver.xmlrpcCreateDir("%s\\Boot" % (self.pxeroot))
        self.pxeserver.xmlrpcSendFile("%s/native/pxe/32/BCD" % (xenrt.TEC().getWorkdir()), 
                                      "%s\\Boot\\BCD" % (self.pxeroot))
        self.pxeserver.xmlrpcSendFile("%s/native/pxe/boot.sdi" % (xenrt.TEC().getWorkdir()),
                                      "%s\\Boot\\boot.sdi" % (self.pxeroot))
        self.pxeserver.xmlrpcSendFile("%s/native/pxe/bootmgr.exe" % (xenrt.TEC().getWorkdir()), 
                                      "%s\\bootmgr.exe" % (self.pxeroot))
        self.pxeserver.xmlrpcSendFile("%s/winpe32.wim" % (xenrt.TEC().lookup("IMAGES_ROOT")),
                                 "%s\\Boot\\winpe.wim" % (self.pxeroot), usehttp=True)
        pxecfg = pxe.addEntry("winpe", default=1, boot="linux")
        pxecfg.linuxSetKernel("pxeboot.0")
        pxe.writeOut(None, forcemac=clientmac)
        
        winclient = self.host.guestFactory()(xenrt.randomGuestName(),
                                             host=self.host)
        self.guestsToClean.append(winclient)
        winclient.createGuestFromTemplate("Other install media",
                                          self.host.lookupDefaultSR())
        winclient.createVIF(bridge=pxebridge, mac=clientmac)
        winclient.enablePXE()

        w = xenrt.WebDirectory()
        t = xenrt.TempDirectory()

        data = self.host.execdom0("cat /etc/ssh/ssh_host_rsa_key.pub")
        data = self.host.getIP() + " " + data
        f = file("%s/known_hosts" % (t.path()), "w")
        f.write(data)
        f.close()    
        data = xenrt.command("%s/utils/kh2reg.py %s/known_hosts" %
                            (xenrt.TEC().lookup("LOCAL_SCRIPTDIR"), t.path()))
        f = file("%s/host.reg" % (t.path()), "w")
        f.write(data)
        f.close()
        w.copyIn("%s/host.reg" % (t.path()))        

        self.host.findPassword()
        ht = self.host.hostTempDir()
        perun = """
wget %s/host.reg
reg import host.reg
plink -l root -pw %s %s touch %s/booted
""" % (w.getURL("/"), self.host.password, self.host.getIP(), ht)
        f = file("%s/perun.cmd" % (t.path()), "w")
        f.write(perun)
        f.close()

        perun_dir = os.path.dirname(xenrt.TEC().lookup("WINPE_START_FILE"))
        if not os.path.exists(perun_dir):
            xenrt.sudo("mkdir -p %s" % (perun_dir))
        xenrt.sudo("cp %s/perun.cmd %s" %
                  (t.path(),
                   xenrt.TEC().lookup("WINPE_START_FILE")))

        winclient.lifecycleOperation("vm-start")
        winclient.poll("UP")
        t = 0
        found = False
        while t < 300:
            if self.host.execdom0("ls %s/booted" % (ht), retval="code"):
                time.sleep(5)
                t += 5       
            else:
                found = True
                break
 
        if not found:
            raise xenrt.XRTFailure("Timed out waiting for WinPE boot.")

class TC7485(_TC7485):
    """Test Linux VMs Booting From A Windows PXE Server"""

    def doit(self, pxebridge, clientmac):
        # Linux test.
        linuxclient = xenrt.lib.xenserver.guest.createVM(\
            self.host, 
            xenrt.randomGuestName(), 
            self.linuxversion, 
            vifs=[("0", pxebridge, clientmac, None), 
                  ("1", self.host.getPrimaryBridge(), xenrt.randomMAC(), None)],
            disks=[("0",1,False)],
            pxe=True, 
            bridge=pxebridge,
            template=self.host.chooseTemplate("TEMPLATE_NAME_UNSUPPORTED_HVM"),
            notools=True)

        self.guestsToClean.append(linuxclient)
        self.getLogsFrom(linuxclient)


class TC7371(xenrt.TestCase):
    """Reorder NICs on a single server."""

    def run(self, arglist=None):
        self.host = self.getDefaultHost()

        # Make sure there are no running guests.
        running = self.host.listGuests(running=True)
        if running:
            raise xenrt.XRTError("Found running guests: %s" % (running))

        # Get the primary NIC device.
        primary = self.host.minimalList("pif-list", "device", "management=true")[0]
        xenrt.TEC().logverbose("Found primary NIC: %s" % (primary))
        
        # Get any other NIC devices.
        devices = self.host.minimalList("pif-list", "device")
        devices.remove(primary)
        if not devices:
            raise xenrt.XRTError("Not enough NICs present for test.")
        xenrt.TEC().logverbose("Found NICs: %s" % (devices))

        # Choose an arbitrary NIC to swap device names with the primary.
        swap = devices[0]

        # Get the PIF data we'll need.
        primarymac = self.host.genParamGet("pif", self.host.getPIFUUID(primary), "MAC")
        swapmac = self.host.genParamGet("pif", self.host.getPIFUUID(swap), "MAC")
        
        # Perform the reordering.
        self.reorder(primary, primarymac, swap, swapmac)
        self.host.getCLIInstance().execute("pif-list params=uuid,device,MAC")
        self.reorder(swap, primarymac, primary, swapmac)
        self.host.getCLIInstance().execute("pif-list params=uuid,device,MAC")

    def reorder(self, a, primarymac, b, swapmac):
        """Swap the device names of two PIFs. The host
           management interface must be specified by primarymac."""
        # Get the PIF UUIDs.
        auuid = self.host.getPIFUUID(a)
        buuid = self.host.getPIFUUID(b)

        xenrt.TEC().logverbose("Swapping %s with %s." % (a, b))
        
        # Prepare a script to swap the names of the NICs.
        commands = []
        commands.append("xe host-management-disable")
        commands.append("xe pif-forget uuid=%s" % (auuid))
        commands.append("xe pif-forget uuid=%s" % (buuid))
        # Save the UUID of the new host management pif.
        commands.append("UUID=`xe pif-introduce device=%s host-uuid=%s mac=%s`" %
                        (b, self.host.getMyHostUUID(), primarymac))
        commands.append("xe pif-introduce device=%s host-uuid=%s mac=%s" %
                        (a, self.host.getMyHostUUID(), swapmac))
        commands.append("xe pif-reconfigure-ip uuid=${UUID} mode=dhcp")
        commands.append("xe host-management-reconfigure pif-uuid=${UUID}")

        xenrt.TEC().logverbose("Running PIF swap commands asynchronously on host.")
        self.runAsync(self.host, commands)
        
class MngReconfigure(xenrt.TestCase):
    """Change management interface with host-management-reconfigure."""
        
    def run(self, arglist=None):
        host = self.getDefaultHost()

        step("Check for default NIC")
        
        default = host.getDefaultInterface()
        xenrt.TEC().logverbose("Default NIC for host is %s." % (default))   
        defaultuuid = host.parseListForUUID("pif-list",
                                            "device",
                                            default).strip()
                                            
        step("Get list of secongary NICs")
        
        nics = host.listSecondaryNICs()
        if len(nics) == 0:
            raise xenrt.XRTError("Test must be run on a host with at "
                                 "least 2 NICs.")

        nmi = host.getSecondaryNIC(nics[0])
        xenrt.TEC().logverbose("Using new management interface %s." % (nmi)) 

        step("Setting secondary NIC's mode to DHCP")
        
        xenrt.TEC().logverbose("Setting %s mode to DHCP." % (nmi))
        nmiuuid = host.parseListForUUID("pif-list", "device", nmi).strip()
        cli = host.getCLIInstance()
        cli.execute("pif-reconfigure-ip uuid=%s mode=dhcp" % (nmiuuid))

        step("Changing management interface to secondary NIC")
        
        xenrt.TEC().logverbose("Changing management interface from %s to %s." %
                               (default, nmi))
        try:
            cli.execute("host-management-reconfigure pif-uuid=%s" % (nmiuuid))
        except:
            # This will always return an error.
            pass
        time.sleep(120)

        xenrt.TEC().logverbose("Finding IP address of new management "
                               "interface...")
        data = host.execdom0("ifconfig xenbr%s" % (nmi[-1]))
        nip = re.search(".*inet (addr:)?(?P<ip>[0-9\.]+)", data).group("ip")
        xenrt.TEC().logverbose("Interface %s appears to have IP %s." %
                               (nmi, nip))

        xenrt.TEC().logverbose("Start using new IP address.")
        oldip = host.machine.ipaddr
        host.machine.ipaddr = nip

        step(" Remove IP configuration from the previous management interface")
        
        cli.execute("pif-reconfigure-ip uuid=%s mode=None" % (defaultuuid))
        data = host.execdom0("ifconfig xenbr%s" % (default[-1]))
        r = re.search(".*inet (addr:)?(?P<ip>[0-9\.]+)", data)
        if r:
            raise xenrt.XRTFailure("Old management interface still has IP "
                                   "address")

        step("Check the agent responds to an off-host CLI command")
        
        try:
            cli.execute("vm-list")
        except:
            raise xenrt.XRTFailure("Failed to run CLI command over new "
                                   "management interface.")

        step("Change back to the old management interface")
        
        xenrt.TEC().logverbose("Changing management interface back from "
                               "%s to %s." % (nmi, default))
        cli.execute("pif-reconfigure-ip uuid=%s mode=dhcp" % (defaultuuid))
        try:
            cli.execute("host-management-reconfigure pif-uuid=%s" %
                        (defaultuuid))
        except:
            # This will always return an error.
            pass
        time.sleep(120)

        xenrt.TEC().logverbose("Return to using old IP.")
        host.machine.ipaddr = oldip

        step("Check the agent still responds to an off-host CLI command")
        
        try:
            cli.execute("vm-list")
        except:
            raise xenrt.XRTFailure("Failed to run CLI command over old "
                                   "management interface.")

        step("Remove IP configuration from the previous management interface")
        
        cli.execute("pif-reconfigure-ip uuid=%s mode=None" % (nmiuuid))
        data = host.execdom0("ifconfig xenbr%s" % (nmi[-1]))
        r = re.search(".*inet (addr:)?(?P<ip>[0-9\.]+)", data)
        if r:
            raise xenrt.XRTFailure("Previous management interface still has "
                                   "IP address")

        step("Check agent operation again")
        
        try:
            cli.execute("vm-list")
        except:
            raise xenrt.XRTFailure("Failed to run CLI command over old "
                                   "management interface (with IP removed) "
                                   "from the other interface.")

class TC6632(MngReconfigure):
    """Change management interface with host-management-reconfigure."""

class TC7337(xenrt.TestCase):
    """Simultaneous use of all physical network interfaces"""

    MININTERFACES = 6
    MAXINTERFACES = 6
    DURATION = 3600

    def run(self, arglist=None):

        forceintf = xenrt.TEC().lookup("TC7337_INTERFACES", None)
        if forceintf:
            xenrt.TEC().comment("Forcing interface count to %s" % (forceintf))
            self.MININTERFACES = int(forceintf)
            self.MAXINTERFACES = int(forceintf)

        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")

        # Get networks available on each host
        bridges0 = self.host0.getExternalBridges()
        bridges1 = self.host0.getExternalBridges()
        bridges0.sort()
        bridges1.sort()
        while len(bridges0) > self.MAXINTERFACES:
            bridges0.pop()
        while len(bridges1) > self.MAXINTERFACES:
            bridges1.pop()
        if len(bridges0) < self.MININTERFACES:
            raise xenrt.XRTError("Not enough interfaces for test. %u required,"
                                 " %s found" % (self.MININTERFACES, `bridges0`))
        if len(bridges1) < self.MININTERFACES:
            raise xenrt.XRTError("Not enough interfaces for test. %u required,"
                                 " %s found" % (self.MININTERFACES, `bridges1`))
        if bridges0 != bridges1:
            raise xenrt.XRTError("Dissimilar networking on hosts.")

        # Install a Linux VM on each bridge on each host
        guests0 = []
        guests1 = []
        for br in bridges0:
            g = self.host0.createGenericLinuxGuest(bridge=br)
            self.uninstallOnCleanup(g)
            g.installNetperf()
            g.execguest("netserver &")
            try:
                g.execguest("/etc/init.d/iptables stop")
            except:
                pass
            guests0.append(g)
        for br in bridges1:
            g = self.host1.createGenericLinuxGuest(bridge=br)
            self.uninstallOnCleanup(g)
            g.installNetperf()
            guests1.append(g)

        # Start netperf transfers
        handles0 = []
        handles1 = []
        for i in range(len(guests0)):
            cmd = "netperf -H %s -t TCP_STREAM -l %u -v 0 -P 0" % \
                (guests0[i].getIP(), self.DURATION)
            h = self.startAsync(guests1[i], cmd)
            handles0.append(h)
            cmd = "netperf -H %s -t TCP_MAERTS -l %u -v 0 -P 0" % \
                (guests0[i].getIP(), self.DURATION)
            h = self.startAsync(guests1[i], cmd)
            handles1.append(h)

        # Wait for the jobs to complete, check health while we go
        deadline = xenrt.util.timenow() + self.DURATION + 60
        while xenrt.util.timenow() < deadline:
            # Check VMs and the hosts
            for g in guests0:
                g.checkHealth()
            for g in guests1:
                g.checkHealth()
            self.host0.checkHealth()
            self.host1.checkHealth()
            time.sleep(30)

        # Check the jobs have completed and get the results
        for i in range(len(guests0)):
            if self.pollAsync(handles0[i]):
                rate = float(self.completeAsync(handles0[i]))
                if rate < 500.0:
                    xenrt.TEC().warning("Tranfer %s to %s rate %fMbps" %
                                        (guests1[i].getName(),
                                         guests0[i].getName(),
                                         rate))
            else:
                raise xenrt.XRTFailure("Tranfer %s to %s still running" %
                                       (guests1[i].getName(),
                                        guests0[i].getName()))
            if self.pollAsync(handles1[i]):
                rate = float(self.completeAsync(handles1[i]))
                if rate < 500.0:
                    xenrt.TEC().warning("Tranfer %s to %s rate %fMbps" %
                                        (guests0[i].getName(),
                                         guests1[i].getName(),
                                         rate))
            else:
                raise xenrt.XRTFailure("Tranfer %s to %s still running" %
                                       (guests0[i].getName(),
                                        guests1[i].getName()))

    
class VlanCreateDelete(xenrt.TestCase):
    """Creation and deletion of a VLAN network"""

    def run(self, arglist=None):

        host = self.getDefaultHost()
        self.host = host
        self.vlansToRemove = []

        vlan = 1234

        # Create a VLAN network on the primary interface
        nic = host.getDefaultInterface()
        vbridge = host.createNetwork()
        host.createVLAN(vlan, vbridge, nic) 
        self.vlansToRemove.append(vlan)
        host.checkVLAN(vlan, nic)

        # Remove the VLAN interface
        host.removeVLAN(vlan)
        self.vlansToRemove.remove(vlan)
        
    def postRun2(self):
        try:
            for vlan in self.vlansToRemove:
                try:
                    self.host.removeVLAN(vlan)
                except:
                    pass
        except:
            pass
        
class TC7339(VlanCreateDelete):
    """Creation and deletion of a VLAN network"""

        
class VmOnVlanOperations(xenrt.TestCase):
    """Operation of a VM on a VLAN interface"""

    def run(self, arglist=None):

        host = self.getDefaultHost()
        self.host = host
        self.vlansToRemove = []

        step("Get available VLANs")
        vlans = host.availableVLANs()
        if len(vlans) == 0:
            xenrt.TEC().skip("No VLANs defined for host")
            return
        vlan, subnet, netmask = vlans[0]

        step("Create a VLAN network on the primary interface")
        nic = host.getDefaultInterface()
        vbridge = host.createNetwork()
        host.createVLAN(vlan, vbridge, nic) 
        self.vlansToRemove.append(vlan)
        host.checkVLAN(vlan, nic)

        step("Install a VM using the VLAN network")
        bridgename = host.genParamGet("network", vbridge, "bridge")
        g = host.createGenericLinuxGuest(bridge=bridgename)
        self.uninstallOnCleanup(g)

        step("Check the VM")
        g.check()
        g.checkHealth()
        if subnet and netmask:
            ip = g.getIP()
            if xenrt.isAddressInSubnet(ip, subnet, netmask):
                xenrt.TEC().comment("%s is in %s/%s" % (ip, subnet, netmask))
            else:
                xenrt.TEC().comment("%s is not in %s/%s" %
                                    (ip, subnet, netmask))
                raise xenrt.XRTFailure("VM IP address not from VLAN subnet")
        else:
            xenrt.TEC().comment("Skipping guest IP check")

        if xenrt.TEC().lookup("OPTION_SKIP_VLAN_CLEANUP", False, boolean=True):
            return

        step("Uninstall the VM")
        g.shutdown()
        g.uninstall()

        step("Remove the VLAN interface")
        host.removeVLAN(vlan)
        self.vlansToRemove.remove(vlan)
        
    def postRun2(self):
        if xenrt.TEC().lookup("OPTION_SKIP_VLAN_CLEANUP", False, boolean=True):
            return
        try:
            for vlan in self.vlansToRemove:
                try:
                    self.host.removeVLAN(vlan)
                except:
                    pass
        except:
            pass
        
        
class TC7340(VmOnVlanOperations):
    """Operation of a VM on a VLAN interface"""
        
class TC7341(xenrt.TestCase):
    """Create a VLAN network for every possible VLAN ID"""

    def run(self, arglist=None):

        host = self.getDefaultHost()
        self.host = host
        self.vlansToRemove = []

        nic = host.getDefaultInterface()

        for vlan in range(1, 4096):
            # Create a VLAN network on the primary interface
            vbridge = host.createNetwork()
            host.createVLAN(vlan, vbridge, nic) 
            self.vlansToRemove.append(vlan)
            host.checkVLAN(vlan, nic)

        # Reboot the host and check the VLANs afterwards
        host.reboot()
        for vlan in range(1, 4096):
            host.checkVLAN(vlan, nic)

        # Remove the VLAN interfaces
        for vlan in range(1, 4096):
            host.removeVLAN(vlan)
            self.vlansToRemove.remove(vlan)
        
    def postRun2(self):
        try:
            for vlan in self.vlansToRemove:
                try:
                    self.host.removeVLAN(vlan)
                except:
                    pass
        except:
            pass

class TC7479(xenrt.TestCase):
    """PIF ethtool config for a running interface"""

    def run(self, arglist=None):

        host = self.getDefaultHost()

        # Find the management interface
        pif = host.parseListForUUID("pif-list",
                                    "management",
                                    "true",
                                    "host-uuid=%s" % 
                                    (host.getMyHostUUID())).strip()
        iface = host.genParamGet("pif", pif, "device")

        # Check ethtool TX offload isn't already disabled
        if host.getEthtoolOffloadInfo(iface)['tx-checksumming'] != 'on':
            raise xenrt.XRTError("TX offload already disabled")

        # Check if nics support TX offloading
        res = host.execdom0("ethtool -K %s tx off" % iface, retval="code")
        if res:
            raise xenrt.XRTError("TX offloading not supported on this machine")
        else:
            host.execdom0("ethtool -K %s tx on" % iface)

        # Set the other-config
        host.genParamSet("pif", pif, "other-config", "off", "ethtool-tx")

        # Reboot the host
        host.reboot()

        # Verify offload is disabled
        if host.getEthtoolOffloadInfo(iface)['tx-checksumming'] != 'off':
            raise xenrt.XRTFailure("TX offload not disabled")

        # Re-enable
        host.genParamRemove("pif", pif, "other-config", "ethtool-tx")
        host.reboot()

class TC7480(xenrt.TestCase):
    """PIF ethtool config for a non-running interface"""

    def run(self, arglist=None):

        host = self.getDefaultHost()
        cli = host.getCLIInstance()
        
        # Find a NIC on NSEC
        nsecaids = host.listSecondaryNICs("NSEC")
        if len(nsecaids) == 0:
            raise xenrt.XRTError("Host has no NSEC interface")

        bridge = host.getBridgeWithMapping(nsecaids[0])
        iface = host.getSecondaryNIC(nsecaids[0])
        pif = host.parseListForUUID("pif-list",
                                    "device",
                                    iface,
                                    "host-uuid=%s" %
                                    (host.getMyHostUUID())).strip()
                        
        # Reboot the host (to make sure the NIC isn't being used)
        host.reboot()

        # Check it isn't already disabled
        if host.getEthtoolOffloadInfo(iface)['tx-checksumming'] != 'on':
            raise xenrt.XRTError("TX offload already disabled")
        
        # Set the other-config
        host.genParamSet("pif", pif, "other-config", "off", "ethtool-tx")
        plugged = host.genParamGet("pif", pif, "currently-attached")
        if plugged == "true":
            cli.execute("pif-unplug", "uuid=%s" % (pif))
            cli.execute("pif-plug", "uuid=%s" % (pif))

        # Install and start a VM using the network attached to the interface
        guest = host.createGenericLinuxGuest(bridge=bridge)
        self.uninstallOnCleanup(guest)        

        # Verify it is now disabled
        if host.getEthtoolOffloadInfo(iface)['tx-checksumming'] != 'off':
            raise xenrt.XRTFailure("TX offload not disabled")

        # Re-enable
        guest.shutdown()
        host.genParamRemove("pif", pif, "other-config", "ethtool-tx")
        host.reboot()

class _TC8095(xenrt.TestCase):
    """Parent testcase class for storage network configuration tests."""

    def __init__(self):
        xenrt.TestCase.__init__(self, "_TC8095")
        self.host = None
        
    def run(self, arglist=None):

        # Check the management and primary NIC configuration
        if self.runSubcase("checkPrimary", (), "Check", "Management") != \
                xenrt.RESULT_PASS:
            return
        # Set up the secondary NIC configuration
        if self.runSubcase("confSecondary", (), "Create", "Secondary") != \
                xenrt.RESULT_PASS:
            return
        # Check the secondary NIC configuration
        if self.runSubcase("checkSecondary", (), "Check", "Secondary") != \
                xenrt.RESULT_PASS:
            return
        # Check the management and primary NIC configuration
        if self.runSubcase("checkPrimary", (), "Check", "Management") != \
                xenrt.RESULT_PASS:
            return
        # Reboot the host
        if self.runSubcase("hostReboot", (), "Host", "Reboot") != \
                xenrt.RESULT_PASS:
            return
        # Check the secondary NIC configuration
        if self.runSubcase("checkSecondary", (), "PostReboot", "Secondary") != \
                xenrt.RESULT_PASS:
            return
        # Check the management and primary NIC configuration
        if self.runSubcase("checkPrimary", (), "PostReboot", "Management") != \
                xenrt.RESULT_PASS:
            return
        # Unconfigure the secondary NIC
        if self.runSubcase("unconfSecondary", (), "Remove", "Secondary") != \
                xenrt.RESULT_PASS:
            return
        # Check the secondary configuration has gone
        if self.runSubcase("checkNoSecondary", (), "Check", "Removed") != \
                xenrt.RESULT_PASS:
            return
        # Check the management and primary NIC configuration
        if self.runSubcase("checkPrimary", (), "Check", "ManagementOnly") != \
                xenrt.RESULT_PASS:
            return
        # Reboot the host
        if self.runSubcase("hostReboot", (), "Host", "RebootNoSecondary") != \
                xenrt.RESULT_PASS:
            return
        # Check the management and primary NIC configuration
        if self.runSubcase("checkPrimary", (), "PostReboot", "ManagementOnly") != \
                xenrt.RESULT_PASS:
            return

    def confSecondary(self):
        # Set up the secondary NIC configuration
        nsecaids = self.host.listSecondaryNICs("NSEC")
        if len(nsecaids) == 0:
            raise xenrt.XRTError("Could not find a NSEC interface")
        ip = self.host.setIPAddressOnSecondaryInterface(nsecaids[0])
        xenrt.TEC().comment("Secondary interface configured with IP %s" % (ip))
        self.secondaryInterfaces = [(nsecaids[0], ip)]

    def unconfSecondary(self):
        # Unconfigure the secondary NIC
        for aid, ip in self.secondaryInterfaces:
            self.host.removeIPAddressFromSecondaryInterface(aid)

    def checkSecondary(self):
        # Check the secondary NIC configuration
        for aid, ip in self.secondaryInterfaces:
            # Verify the secondary interface has an IP address
            if not ip:
                raise xenrt.XRTFailure("Secondary interface does not have "
                                       "an IP address")
            actualip = self.host.getIPAddressOfSecondaryInterface(aid)
            if not actualip:
                raise xenrt.XRTFailure("Secondary interface IP address is no "
                                       "longer present")
            if ip != actualip:
                raise xenrt.XRTFailure("Secondary interface IP address has "
                                       "changed",
                                       "Was %s, now %s" % (ip, actualip))
            
            # Verify a host or router on the secondary subnet is pingable
            # from dom0 (and that traffic goes via the secondary interface)
            secpeer = self.host.lookup(["NETWORK_CONFIG",
                                        "SECONDARY",
                                        "ADDRESS"])
            seceth = self.host.getSecondaryNIC(aid)
            secbr = string.replace(seceth, "eth", "xenbr")

            # Start a tcpdump on the secondary interface
            dumpfile = self.host.hostTempFile()
            tracepid = None
            try:                
                tracepid = self.host.execdom0(\
                    "/usr/sbin/tcpdump -i %s -w %s host %s and icmp "
                    ">/dev/null 2>&1 </dev/null & echo $!" %
                    (seceth, dumpfile, secpeer)).strip()
                time.sleep(2)
                rc = self.host.execdom0("ping -c 3 %s" % (secpeer),
                                        retval="code")
                if rc != 0:
                    raise xenrt.XRTFailure("Could not ping via secondary NIC")
            finally:
                if tracepid:
                    try:
                        # Wait for tcpdump to flush its output and stop
                        time.sleep(5)
                        self.host.execdom0("kill -TERM %s" % (tracepid))
                        time.sleep(2)
                    except:
                        pass
            # Check our pings and replies were in this trace
            data = self.host.execdom0("/usr/sbin/tcpdump -r %s -lne" %
                                      (dumpfile))
            if len(re.findall(r"ICMP echo request", data)) != 3:
                raise xenrt.XRTFailure("Did not find the expected number of "
                                       "ICMP request packets in the seocndary "
                                       "network trace")
            if len(re.findall(r"ICMP echo reply", data)) != 3:
                raise xenrt.XRTFailure("Did not find the expected number of "
                                       "ICMP reply packets in the seocndary "
                                       "network trace")

            # Verify the routing table contains an entry for the subnet
            # attached to the secondary NIC
            data = self.host.execdom0("/sbin/ip route list match %s" %
                                      (secpeer))
            subnet = self.host.lookup(["NETWORK_CONFIG",
                                       "SECONDARY",
                                       "SUBNET"])
            subnetmask = self.host.lookup(["NETWORK_CONFIG",
                                           "SECONDARY",
                                           "SUBNETMASK"])
            preflen = xenrt.maskToPrefLen(subnetmask)
            sn = "%s/%s dev %s" % (subnet, preflen, secbr)
            if not re.search(sn, data):
                raise xenrt.XRTFailure("Could not find route for local subnet")
                
            if isinstance(self.host, xenrt.lib.xenserver.TampaHost):
            # Verify that xapi can be reached via the secondary NIC's Ip address for Clearwater host onwards                 
                try:
                    u = urllib2.urlopen("http://%s/" % (ip))                    
                    xenrt.TEC().logverbose("Was able to reach port 80 on storage NIC's IP address ")
                except:                    
                    raise xenrt.XRTFailure("Was UNABLE to reach port 80 on storage NIC's IP address")
                    
                try:    
                    u = urllib2.urlopen("https://%s/" % (ip))
                    xenrt.TEC().logverbose("Was able to reach port 443 on storage NIC's IP address ")
                except:                    
                    raise xenrt.XRTFailure("Was UNABLE to reach port 443 on storage NIC's IP address")
            else:
            # Verify that xapi CANNOT be reached via the secondary NIC's IP address for pre-Clearwater host
                try:
                    u = urllib2.urlopen("http://%s/" % (ip))
                    raise xenrt.XRTFailure("Was able to reach port 80 on storage NIC's IP address")
                except urllib2.URLError, e:
                    xenrt.TEC().logverbose("Was unable to reach port 80 on storage NIC's IP address as EXPECTED")                    
                    pass
                except:
                    raise xenrt.XRTFailure("Was able to reach port 80 on storage NIC's IP address")
                
                try:
                    u = urllib2.urlopen("https://%s/" % (ip))
                    raise xenrt.XRTFailure("Was able to reach port 443 on storage NIC's IP address")
                except urllib2.URLError, e:
                    xenrt.TEC().logverbose("Was unable to reach port 443 on storage NIC's IP address as EXPECTED")                    
                    pass
                except:
                    raise xenrt.XRTFailure("Was able to reach port 443 on storage NIC's IP address")
                    
            secpif = self.host.getPIFUUID(seceth)
            mgmt = self.host.genParamGet("pif", secpif, "management")
            if mgmt != "false":
                raise xenrt.XRTFailure("Secondary PIF has unexpected "
                                       "management config '%s'" % (mgmt))

    def checkPrimary(self):
        # Check the management and primary NIC configuration
        prieth = self.host.getDefaultInterface()
        pribr = string.replace(prieth, "eth", "xenbr")
        pripif = self.host.getPIFUUID(prieth)
        pifip = self.host.genParamGet("pif", pripif, "IP")
        if pifip == "":
            raise xenrt.XRTFailure("Primary NIC has lost its IP address")
        try:
            data = self.host.execdom0("ifconfig %s" % (pribr))
        except:
            raise xenrt.XRTError("Primary interface not configured for IP")
        if not re.search(r"UP", data):
            raise xenrt.XRTFailure("Primary interface not UP")
        try:
            ip = re.search(".*inet (addr:)?(?P<ip>[0-9\.]+)", data).group("ip")
        except:
            raise xenrt.XRTFailure("No IP address found for primary interface")
        if ip != pifip:
            raise xenrt.XRTFailure("PIF and interface IP mismatch")
        mgmt = self.host.genParamGet("pif", pripif, "management")
        if mgmt != "true":
            raise xenrt.XRTFailure("Primary interface is not marked as "
                                   "management")

        # Check the default route if via the management interface
        data = self.host.execdom0("/sbin/ip route list match 0.0.0.0")
        defs = re.findall(r"default via (\S+) dev (\S+)", data)
        if len(defs) != 1:
            raise xenrt.XRTFailure("Found %u default routes, expected 1" %
                                   (len(defs)))
        gw = self.host.lookup(["NETWORK_CONFIG", "DEFAULT", "GATEWAY"])
        if defs[0][0] != gw:
            raise xenrt.XRTFailure("Incorrect default gateway found", 
                                   "Found %s, expecting %s" % (defs[0][0], gw))
        if defs[0][1] != pribr:
            raise xenrt.XRTFailure("Default route via wrong interface",
                                   "Found %s, expecting %s" % (defs[0][1], pribr))

    def hostReboot(self):
        self.host.reboot()

    def checkNoSecondary(self):
        # Check the secondary configuration has gone
        for aid, ip in self.secondaryInterfaces:
            hasip = False
            try:
                self.host.getIPAddressOfSecondaryInterface(aid)
                hasip = True
            except xenrt.XRTException, e:
                pass
            if hasip:
                raise xenrt.XRTFailure("Secondary interface still has an IP "
                                       "address after being unconfigured")

            secsubnet = self.host.lookup(["NETWORK_CONFIG",
                                          "SECONDARY",
                                          "SUBNET"])
            data = self.host.execdom0("/sbin/ip route list match %s" %
                                      (secsubnet))
            if re.search(secsubnet, data):
                raise xenrt.XRTFailure("Route still exists for storage subnet")

    def postRun(self):
        for aid, ip in self.secondaryInterfaces:
            try:
                self.host.removeIPAddressFromSecondaryInterface(aid)
            except:
                pass

class TC8095(_TC8095):
    """Create and remove secondary network interface IP configuration"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()

class TC8100(_TC8095):
    """Create and remove secondary network interface IP configuration on a slave host"""

    def prepare(self, arglist):
        self.host = self.getHost("RESOURCE_HOST_1")
        if self.host.pool.master == self.host:
            raise xenrt.XRTError("Attempting to run slave test on the master")

class _TC8342(xenrt.TestCase):
    """Base class for TC8342 style TCs"""
    NFS = False
    ISCSI = False

    def prepare(self, arglist=None):
        self.pool = self.getDefaultPool()

        # Set up an appropriate SR
        if self.NFS:
            # Create NFS SR
            nfsShare = xenrt.ExternalNFSShare()
            nfs = nfsShare.getMount()
            r = re.search(r"([0-9\.]+):(\S+)", nfs)
            if not r:
                raise xenrt.XRTError("Unable to parse NFS paths %s" % (nfs))
            sr = xenrt.lib.xenserver.NFSStorageRepository(self.pool.master,
                                                          "nfs")
            sr.create(r.group(1), r.group(2))
            self.sr = sr
            self.pool.addSRToPool(sr)
            self.target = nfsShare.address
        elif self.ISCSI:
            # Create iSCSI SR
            sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.pool.master,
                                                            "iscsi")
            sr.create(subtype="lvm")
            self.sr = sr
            self.pool.addSRToPool(sr)
            self.target = sr.lun.getServer()
            self.sr.prepareSlave(self.pool.master, self.pool.getSlaves()[0])
        else:
            raise xenrt.XRTError("Must specify a storage type")

    def run(self, arglist=None):
        # Reboot the slave
        slave = self.pool.getSlaves()[0]
        slave.reboot()
        
        # Check storage is plugged correctly etc...
        self.guest2 = slave.createGenericLinuxGuest(sr=self.sr.uuid, start=False)
        self.uninstallOnCleanup(self.guest2)
        self.guest2.start(specifyOn=True)
        self.checkHost(slave)

        # Now reboot the master
        master = self.pool.master
        master.reboot()
        self.guest = master.createGenericLinuxGuest(sr=self.sr.uuid, start=False)
        self.uninstallOnCleanup(self.guest)
        self.guest.start(specifyOn=True)
        
        # Check storage is plugged correctly etc...
        self.checkHost(master)

    def checkHost(self, host):
        # Make sure this host has the relevant storage PIF plugged,
        # and existing connections go to the right place

        # Storage PIF is the one on NPRI
        npIF = host.getDefaultInterface()
        nws = host.minimalList("network-list")
        network = None
        for nw in nws:
            if host.genParamGet("network", nw, "name-label").endswith(npIF):
                # This is the one we want
                network = nw
                break
        if not network:
            raise xenrt.XRTError("Cannot find NPRI network")
        # Now find the PIFs for that network
        pifs = host.minimalList("pif-list", args="host-uuid=%s network-uuid=%s" %
                                                 (host.getMyHostUUID(), network))
        if len(pifs) != 1:
            raise xenrt.XRTError("Found %u pifs on network/host, expecting 1" %
                                 (len(pifs)))

        # We have our pif, lets see if its plugged
        if host.genParamGet("pif", pifs[0], "currently-attached") != "true":
            raise xenrt.XRTFailure("Storage PIF not plugged after reboot",
                                   "Host %s, PIF uuid %s" % (host.getName(),
                                                             pifs[0]))        

        # Check existing connections
        nsdata = host.execdom0("netstat -na | grep %s | grep ESTABLISHED" %
                               (self.target))
        for ns in nsdata.splitlines():
            fields = ns.split()
            source = fields[3].split(":")[0]
            dest = fields[4].split(":")[0]
            # Check that dest is correct, and that source is in the same subnet
            if dest != self.target:
                raise xenrt.XRTError("Error parsing netstat data - found "
                                     "unexpected dest", dest)
            # Verify that source is in the NPRI subnet
            npsubnet = xenrt.TEC().lookup(["NETWORK_CONFIG", "DEFAULT", "SUBNET"])
            npsubnetMask = xenrt.TEC().lookup(["NETWORK_CONFIG", "DEFAULT", "SUBNETMASK"])
            prefixlen = xenrt.util.maskToPrefLen(npsubnetMask)
            sourceSubnet = xenrt.util.formSubnet(source, prefixlen)
            if sourceSubnet != npsubnet:
                raise xenrt.XRTFailure("Found storage connection from incorrect"
                                       " source subnet","%s not in %s/%s" % 
                                                        (source, npsubnet,
                                                         prefixlen))
            
    def postRun(self):
        self.guest.uninstall()
        self.guest2.uninstall()
        
        # Remove the SR
        self.sr.remove()

class TC8342(_TC8342):
    """Verify that storage PIFs are plugged before using to NFS storage"""
    NFS = True

class TC8343(_TC8342):
    """Verify that storage PIFs are plugged before using iSCSI storage"""
    ISCSI = True

class TC8350(xenrt.TestCase):
    """Regression test for CA-23042."""

    def prepare(self, arglist):
        self.pifs = []
        self.networks = []
        self.vlans = [1234, 1235]

        self.host = self.getDefaultHost()
        self.cli = self.host.getCLIInstance()
        self.usepif = self.host.getSecondaryNIC(1)
        self.usepifuuid = self.host.getPIFUUID(self.usepif)
        xenrt.TEC().logverbose("Creating VLANS...")
        for v in self.vlans:
            network = self.host.createNetwork()
            self.networks.append(network)
            self.pifs.append(self.host.createVLAN(v, 
                             network, 
                             self.usepif))
        self.vlans = [ self.host.parseListForUUID("vlan-list", "tag", v) \
                        for v in self.vlans ]
        for p in self.pifs:
            self.cli.execute("pif-plug", "uuid=%s" % (p))
        self.host.execdom0("touch /tmp/fist_allow_forget_of_vlan_pif")

    def run(self, arglist):
        xenrt.TEC().logverbose("Unplugging use PIF.")
        self.cli.execute("pif-unplug", 
                         "uuid=%s" % 
                         (self.usepifuuid))
        xenrt.TEC().logverbose("Forgetting one VLAN PIF.")
        self.cli.execute("pif-forget",
                         "uuid=%s" %
                         (self.pifs[0]))
        xenrt.TEC().logverbose("Trying to remove remaining VLAN.")
        self.host.removeVLAN(int(self.host.genParamGet("pif", self.pifs[1], "VLAN")))

    def postRun(self):
        for v in self.vlans:
            try: self.cli.execute("vlan-destroy", "uuid=%s" % (v)) 
            except: pass 
        for p in self.pifs:
            try: self.cli.execute("pif-forget", "uuid=%s" % (p))
            except: pass 
        for n in self.networks:
            try: self.cli.execute("network-destroy", "uuid=%s" % (n)) 
            except: pass 
        try: self.cli.execute("pif-plug", "uuid=%s" % 
                             (self.usepifuuid))
        except: pass 
        self.host.execdom0("rm -f /tmp/fist_allow_forget_of_vlan_pif")

class TC8609(xenrt.TestCase):
    """pif-forget of an untagged VLAN pif should be blocked"""

    def prepare(self, arglist):

        self.vlanuuid = None
        self.network = None
        
        self.host = self.getDefaultHost()
        self.cli = self.host.getCLIInstance()
        self.pif = self.host.minimalList("pif-list",
                                         args="host-uuid=%s management=true" %
                                         (self.host.getMyHostUUID()))[0]
        xenrt.TEC().logverbose("Creating VLAN...")
        self.network = self.host.createNetwork()
        pifdev = self.host.genParamGet("pif", self.pif, "device")
        self.vlanpif = self.host.createVLAN(1236, self.network, pifdev)
        self.vlanuuid = self.host.parseListForUUID("vlan-list", "tag", 1236)

    def run(self, arglist):

        try:
            self.cli.execute("pif-forget", "uuid=%s" % (self.vlanpif))
        except xenrt.XRTFailure, e:
            if not re.search(r"Operation cannot proceed while a VLAN "
                             "exists on this interface", e.data):
                raise e
        else:
            raise xenrt.XRTFailure("Was able to pif-forget an untagged VLAN PIF")

    def postRun(self):
        if self.vlanuuid:
            try: self.cli.execute("vlan-destroy", "uuid=%s" % (self.vlanuuid)) 
            except: pass 
        if self.network:
            try: self.cli.execute("network-destroy", "uuid=%s" % (self.network)) 
            except: pass 

class _CheckTopology(xenrt.TestCase):
    """Check network topologies persist across host reboots."""

    TOPOLOGY = ""
    
    def reconfigure(self, pifuuid):
        if self.host.genParamGet("pif", pifuuid, "currently-attached") == "false":
            self.runAsync(self.host, "xe pif-plug uuid=%s" % (pifuuid))
        elif self.host.genParamGet("pif", pifuuid, "management") == "true":
            # Midnight Ride blocks unplug of the management PIF so disable
            # management first. This should be safe on older versions as
            # well.
            self.runAsync(self.host, [\
                "xe host-management-disable",
                "xe pif-unplug uuid=%s" % (pifuuid), 
                "xe pif-plug uuid=%s" % (pifuuid),
                "xe host-management-reconfigure pif-uuid=%s" % (pifuuid)],
                          ignoreSSHErrors=True)
            time.sleep(600)
        else:
            self.runAsync(self.host, ["xe pif-unplug uuid=%s" % (pifuuid), 
                                      "xe pif-plug uuid=%s" % (pifuuid)],
                          ignoreSSHErrors=True)

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.savedmanagement = self.host.parseListForUUID("pif-list", "management", "true")
        self.host.createNetworkTopology(self.TOPOLOGY)
        self.host.checkNetworkTopology(self.TOPOLOGY)

    def run(self, arglist):
        self.host.reboot(timeout=3600)
        self.host.checkNetworkTopology(self.TOPOLOGY)

    def postRun(self):
        cli = self.host.getCLIInstance()
        vlans = self.host.minimalList("pif-list", "VLAN")
        for v in vlans:
            if v == "-1": continue
            pifuuid = self.host.parseListForUUID("pif-list", "VLAN", v)
            network = self.host.genParamGet("pif", pifuuid, "network-uuid")
            try: self.host.removeVLAN(int(v))
            except: pass 
            try: cli.execute("network-destroy uuid=%s" % (network))
            except: pass
        bonds = self.host.getBonds()
        for b in bonds:
            try: self.host.removeBond(b, management=True)
            except: pass 
        try:
            originalmif = self.host.genParamGet("pif", self.savedmanagement, "device")
            self.host.changeManagementInterface(originalmif)
        except:
            pass    
        pifs = self.host.minimalList("pif-list")
        for p in pifs:
            try: self.host.genParamRemove("pif", p, "other-config", "defaultroute")
            except: pass
            if not p == self.savedmanagement: 
                try: cli.execute("pif-reconfigure-ip uuid=%s mode=none" % (p))
                except: pass
            try: self.reconfigure(p)
            except: pass
   
class TC8351(_CheckTopology):

    TOPOLOGY = """
<NETWORK>
  <PHYSICAL>
    <MANAGEMENT/>
    <NIC/>
    <NIC/>
    <VLAN>
      <VMS/>
    </VLAN>
  </PHYSICAL>
</NETWORK>
"""

class _IndependentGateway(_CheckTopology):
    """Test other-config:defaultroute PIF setting."""

    ROUTEFORMAT = "(?P<destination>\S+)\s+" + \
                  "(?P<gateway>\S+)\s+" + \
                  "(?P<netmask>\S+)\s+" + \
                  "(?P<flags>\S+)\s+" + \
                  "(?P<metric>\S+)\s+" + \
                  "(?P<ref>\S+)\s+" + \
                  "(?P<use>\S+)\s+" + \
                  "(?P<iface>\S+)"

    def getTestPIF(self):
        raise xenrt.XRTError("Unimplemented.")

    def getGatewayPIF(self):
        #data = self.host.execdom0("/sbin/route")
        #data = re.search("default.*", data)
        data = self.host.execdom0("route -n | grep ^0.0.0.0")
        if not data:
            raise xenrt.XRTFailure("No default route found.")
        #data = data.group()
        #bridge = re.match(self.ROUTEFORMAT, data).group("iface")
        bridge = data.strip().split()[7]
        network = self.host.parseListForUUID("network-list", "bridge", bridge)
        pif = self.host.parseListForUUID("pif-list", "network-uuid", network)
        return pif

    def prepare(self, arglist):
        _CheckTopology.prepare(self, arglist)
        self.management = self.host.parseListForUUID("pif-list", "management", "true")
        xenrt.TEC().logverbose("Give the test PIF an IP address.")
        self.pifuuid = self.getTestPIF()
        self.host.getCLIInstance().execute("pif-reconfigure-ip uuid=%s mode=dhcp" % (self.pifuuid))

    def run(self, arglist):
        xenrt.TEC().logverbose("Current routing table:")
        self.host.execdom0("route -n")
        xenrt.TEC().logverbose("Move the default route.")
        self.host.genParamSet("pif", self.pifuuid, "other-config", "true", pkey="defaultroute") 
        self.reconfigure(self.pifuuid)
        if not self.getGatewayPIF() == self.pifuuid:
            raise xenrt.XRTFailure("Default route didn't change.")

        xenrt.TEC().logverbose("Check that the default route persists across a reboot.")
        self.host.reboot()
        if not self.getGatewayPIF() == self.pifuuid:
            raise xenrt.XRTFailure("Default route didn't persist.")

        xenrt.TEC().logverbose("Move the default route back.")
        self.host.genParamSet("pif", self.pifuuid, "other-config", "false", pkey="defaultroute") 
        self.reconfigure(self.management)
        if not self.getGatewayPIF() == self.management:
            raise xenrt.XRTFailure("Default route didn't revert.")

        xenrt.TEC().logverbose("Check that the default route persists across a reboot.")
        self.host.reboot()
        if not self.getGatewayPIF() == self.management:
            raise xenrt.XRTFailure("Default route didn't persist.")

        xenrt.TEC().logverbose("Move the default route again.")
        self.host.genParamSet("pif", self.pifuuid, "other-config", "true", pkey="defaultroute") 
        self.reconfigure(self.pifuuid)
        if not self.getGatewayPIF() == self.pifuuid:
            raise xenrt.XRTFailure("Default route didn't change.")

        xenrt.TEC().logverbose("Move the default route back a different way.")
        self.host.genParamRemove("pif", self.pifuuid, "other-config", pkey="defaultroute") 
        self.reconfigure(self.management)
        if not self.getGatewayPIF() == self.management:
            raise xenrt.XRTFailure("Default route didn't revert.")

        xenrt.TEC().logverbose("Check that the default route persists across a reboot.")
        self.host.reboot()
        if not self.getGatewayPIF() == self.management:
            raise xenrt.XRTFailure("Default route didn't persist.")

class TC8358(_IndependentGateway):
    """Default route on a non-management PIF."""
    
    TOPOLOGY = """
<NETWORK>
  <PHYSICAL>
    <MANAGEMENT/>
    <NIC/>
  </PHYSICAL>
  <PHYSICAL>
    <NIC/>
  </PHYSICAL>
</NETWORK>
"""
   
    def getTestPIF(self):
        # CA-56452 Plug all PIFs so carrier reports the correct status.        
        for pif in self.host.minimalList("pif-list"):
            try:
                self.host.getCLIInstance().execute("pif-plug", "uuid=%s" % (pif))
            except:
                xenrt.TEC().warning("Failed to plug PIF: %s" % (pif))        
        pifs = self.host.minimalList("pif-list", args="carrier=true")
        if self.management in pifs:
            pifs.remove(self.management)
        return pifs[0]
 
class TC8364(TC8358):
    """Test for correct failure when two default routes are specified."""

    def run(self, arglist):
        self.host.genParamSet("pif", self.pifuuid, "other-config", "true", pkey="defaultroute") 
        self.reconfigure(self.pifuuid)
        self.host.genParamSet("pif", self.management, "other-config", "true", pkey="defaultroute") 
        self.reconfigure(self.management)
        time.sleep(15) # Xapi seems to blip in this situation as it rebinds its interfaces CA-84410
        self.host.waitForXapi(60, desc="Xapi reachability after routing changes")
        xenrt.TEC().comment("Used PIF: %s" % (self.getGatewayPIF()))

class TC8359(_IndependentGateway):
    """Default route on a non-management bond."""
    
    TOPOLOGY = """
<NETWORK>
  <PHYSICAL network="NSEC">
    <MANAGEMENT/>
    <NIC/>
  </PHYSICAL>
  <PHYSICAL>
    <NIC/>
    <NIC/>
  </PHYSICAL>
</NETWORK>
"""

    def getTestPIF(self):
        bond = self.host.minimalList("bond-list")
        if not bond:
            raise xenrt.XRTError("No bonds found on host.")
        return self.host.genParamGet("bond", bond[0], "master")

class TC12453(TC8359):
    """Default route on a non-management active/passive bond."""
    
    TOPOLOGY = """
<NETWORK>
  <PHYSICAL network="NSEC">
    <MANAGEMENT/>
    <NIC/>
  </PHYSICAL>
  <PHYSICAL bond-mode="active-backup">
    <NIC/>
    <NIC/>
  </PHYSICAL>
</NETWORK>
"""

class TC8360(_IndependentGateway):
    """Default route on a non-management vlan."""
    
    TOPOLOGY = """
<NETWORK>
  <PHYSICAL network="NSEC">
    <MANAGEMENT/>
    <NIC/>
  </PHYSICAL>
  <PHYSICAL>
    <NIC/>
    <VLAN/>
  </PHYSICAL>
</NETWORK>
"""

    def getTestPIF(self):
        return self.host.minimalList("vlan-list", params="untagged-PIF")[0]

class TC8464(xenrt.TestCase):
    """VLANs cannot be created on top of other VLANs"""

    def prepare(self, arglist):

        self.topnetwork = None
        self.topvlanpif = None
        self.network = None
        self.vlanpif = None
        
        self.host = self.getDefaultHost()
        self.host.execdom0("rm -f /tmp/fist_allow_vlan_on_vlan")

        # Create a VLAN on the primary PIF
        nic = self.host.getDefaultInterface()
        self.topnetwork = self.host.createNetwork("TC-8464 first VLAN")
        self.topvlanpif = self.host.createVLAN(999, self.topnetwork, nic)

    def run(self, arglist):

        # Try to create a VLAN on the other VLAN
        self.network = self.host.createNetwork("TC-8464 second VLAN")
        try:
            self.vlanpif = self.host.createVLAN(998,
                                                self.network,
                                                None,
                                                pifuuid=self.topvlanpif)
        except xenrt.XRTFailure, e:
            if re.search("You tried to create a VLAN on top of another VLAN",
                         e.data):
                # This is what we want
                pass
            else:
                raise e
        else:
            raise xenrt.XRTFailure("Was allowed to create a VLAN on a VLAN")
        
    def postRun(self):
        cli = self.host.getCLIInstance()

        # Remove anything we made during the test
        if self.vlanpif:
            try:
                vlanuuid = self.host.parseListForUUID("vlan-list",
                                                      "untagged-PIF",
                                                      self.vlanpif)
                cli.execute("vlan-destroy", "uuid=%s" % (vlanuuid))
            except:
                pass
        if self.network:
            try:
                cli.execute("network-destroy", "uuid=%s" % (self.network))
            except:
                pass
            
        # Remove the top level network/VLAN
        if self.topvlanpif:
            try:
                vlanuuid = self.host.parseListForUUID("vlan-list",
                                                      "untagged-PIF",
                                                      self.topvlanpif)
                cli.execute("vlan-destroy", "uuid=%s" % (vlanuuid))
            except:
                pass
        if self.topnetwork:
            try:
                cli.execute("network-destroy", "uuid=%s" % (self.topnetwork))
            except:
                pass
            
class TC8465(xenrt.TestCase):
    """De-chaining of chained VLANs"""

    def prepare(self, arglist):

        self.topnetwork = None
        self.topvlanpif = None
        self.network = None
        self.vlanpif = None
        self.vlanuuid = None
        
        self.host = self.getDefaultHost()
        self.host.execdom0("touch /tmp/fist_allow_vlan_on_vlan")

        # Create a VLAN on the primary PIF
        nic = self.host.getDefaultInterface()
        self.topnetwork = self.host.createNetwork("TC-8464 first VLAN")
        self.topvlanpif = self.host.createVLAN(997, self.topnetwork, nic)
        self.topvlanuuid = self.host.parseListForUUID("vlan-list",
                                                      "untagged-PIF",
                                                      self.topvlanpif)

        # Create a VLAN on top of this
        self.network = self.host.createNetwork("TC-8464 second VLAN")
        self.vlanpif = self.host.createVLAN(996,
                                            self.network,
                                            None,
                                            pifuuid=self.topvlanpif)

        # Make sure the topology is correct
        self.vlanuuid = self.host.parseListForUUID("vlan-list",
                                                   "untagged-PIF",
                                                   self.vlanpif)
        p = self.host.genParamGet("vlan", self.vlanuuid, "tagged-PIF")
        if p != self.topvlanpif:
            raise xenrt.XRTError("Child VLAN did not get created with "
                                 "correct parent PIF",
                                 p)

    def run(self, arglist):

        # Restart xapi
        self.host.execdom0("service xapi restart")
        time.sleep(60)

        # Check the VLANs have been fixed up
        p1 = self.host.genParamGet("vlan", self.vlanuuid, "tagged-PIF")
        p2 = self.host.genParamGet("vlan", self.topvlanuuid, "tagged-PIF")
        if p1 != p2:
            raise xenrt.XRTFailure("Child VLAN did not get the tagged PIF "
                                   "updated")
        if p1 == self.topvlanpif:
            raise  xenrt.XRTFailure("Child VLAN did not get the tagged PIF "
                                    "updated")
        
    def postRun(self):
        cli = self.host.getCLIInstance()

        # Remove anything we made during the test
        if self.vlanpif:
            try:
                vlanuuid = self.host.parseListForUUID("vlan-list",
                                                      "untagged-PIF",
                                                      self.vlanpif)
                cli.execute("vlan-destroy", "uuid=%s" % (vlanuuid))
            except:
                pass
        if self.network:
            try:
                cli.execute("network-destroy", "uuid=%s" % (self.network))
            except:
                pass
            
        # Remove the top level network/VLAN
        if self.topvlanpif:
            try:
                vlanuuid = self.host.parseListForUUID("vlan-list",
                                                      "untagged-PIF",
                                                      self.topvlanpif)
                cli.execute("vlan-destroy", "uuid=%s" % (vlanuuid))
            except:
                pass
        if self.topnetwork:
            try:
                cli.execute("network-destroy", "uuid=%s" % (self.topnetwork))
            except:
                pass
            
        self.host.execdom0("rm -f /tmp/fist_allow_vlan_on_vlan")

class TC12419(xenrt.TestCase):
    """Regression test for CA-39056."""

    LIMIT = 5
 
    def prepare(self, arglist=[]):
        self.master = self.getHost("RESOURCE_HOST_0")
        self.slave = self.getHost("RESOURCE_HOST_1")
        try:
            self.master.execdom0("ovs-appctl vlog/set bridge:FILE:DBG")
            self.slave.execdom0("ovs-appctl vlog/set bridge:FILE:DBG")
        except:
            pass
        self.guest = self.master.createGenericWindowsGuest()
        self.mac, self.ip, network = self.guest.getVIFs()["eth0"]
        self.bridge = self.slave.getPrimaryBridge()
        self.packit = "/root/packit"
        xenrt.getTestTarball("packit", extract=True)
        sftp = self.master.sftpClient()
        sftp.copyTo("%s/packit/packit" % (xenrt.TEC().getWorkdir()), self.packit)
        sftp.close()

    def isVMIsolated(self, delay):
        self.guest.waitForDaemon(30)
        
        step("Capturing broadcast ARP packets on bridge")
        handle = self.startAsync(self.master,
                                "tcpdump -i %s -c 1 arp and broadcast and ether host %s; " \
                                "sleep %s; " \
                                "date; " \
                                "%s -t arp -A 1 -i eth1 -X %s -e %s -y %s" % \
                                (self.bridge, self.mac, delay, self.packit, self.mac, self.mac, self.ip))
        # Following two lines added for tracking of CA-53619.
        try:
            self.master.execdom0("ovs-appctl vlog/set bridge:syslog:DBG")
            self.slave.execdom0("ovs-appctl vlog/set bridge:syslog:DBG")
        except Exception, e:
            pass
        
        step("Live migrating the VM")
        self.guest.migrateVM(self.slave, live="true", fast=True)
        time.sleep(delay+5)
        
        try:
            try:
                if 'Network subsystem type' in self.slave.special and not self.slave.special['Network subsystem type'] == "linux":
                    data = self.slave.showPortMappings(self.bridge)
                    match = re.search("\s+(?P<port>\d+)\s+\d+\s+%s" % (self.mac), data)
                    if match:
                        log("MAC %s is on port %s on bridge %s." % (self.mac, match.group("port"), self.bridge))
                        data = self.slave.execdom0("ovs-dpctl show %s" % (self.bridge))
                        vifmatch = re.search("port\s+(?P<port>\d+):\s+vif%s.0" % (self.guest.getDomid()), data)
                        if vifmatch:
                            if not vifmatch.group("port") == match.group("port"):
                                raise xenrt.XRTFailure("%s was observed on port %s but it should be on port %s." % 
                                                       (self.mac, match.group("port"), vifmatch.group("port")))
                        else:
                            log("Couldn't find vif%s.0 on bridge %s." % (self.guest.getDomid(), self.bridge))
                    else:
                        log("Couldn't find MAC %s on bridge %s." % (self.mac, self.bridge))
                else:
                    data = self.slave.execdom0("brctl showmacs %s" % (self.bridge))
                    match = re.search("\s+(?P<port>\d+)\s+%s" % (self.mac), data)
                    if match:
                        log("MAC %s is on port %s on bridge %s." % (self.mac, match.group("port"), self.bridge))
                        data = self.slave.execdom0("brctl showstp %s" % (self.bridge)) 
                        vifmatch = re.search("vif%s.0\s+\((?P<port>\d+)\)" % (self.guest.getDomid()), data)
                        if vifmatch:
                            if not vifmatch.group("port") == match.group("port"):
                                raise xenrt.XRTFailure("%s was observed on port %s but it should be on port %s." % 
                                                       (self.mac, match.group("port"), vifmatch.group("port")))
                        else:
                            log("Couldn't find vif%s.0 on bridge %s." % (self.guest.getDomid(), self.bridge))
                    else:
                        log("Couldn't find MAC %s on bridge %s." % (self.mac, self.bridge))
                self.guest.waitForDaemon(120, level=xenrt.RC_ERROR)
            except xenrt.XRTFailure, e:
                log("Exception: %s" % (str(e)))
                return True 
            else:
                return False
        finally:
            try:
                self.master.execdom0("killall tcpdump")
            except:
                pass
            try:
                log(self.completeAsync(handle))
            except:
                pass
            step("Live migrating the VM back to master")
            self.guest.migrateVM(self.master, live="true", fast=True)

    def run(self, arglist=[]):
        for i in map(lambda x:float(x)/2.0, range(4*self.LIMIT)):
            step("Testing with an ARP %ss after the first." % (i))
            if self.isVMIsolated(i):
                if i >= self.LIMIT:
                    log("VM became isolated by an ARP sent %ss after the first." % (i))
                else:
                    raise xenrt.XRTFailure("VM became isolated by an ARP sent %ss after the first." % (i))
            else:
                log("VM is not isolated by and ARP sent %ss after the first." % (i))
            # Allow a minute for everything to settle down.
            time.sleep(60)

class TC12520(xenrt.TestCase):
    """Test host join doesn't create extra networks"""
    def run(self, arglist=None):
        pool = self.getPool("RESOURCE_POOL_0")
        h0 = self.getHost("RESOURCE_HOST_0")
        h1 = self.getHost("RESOURCE_HOST_1")
        
        # get network called Pool-wide network associated with eth0
        network = h0.parseListForUUID("network-list", "name-label", "Pool-wide network associated with eth0")
        
        # rename this network to something other than the default
        h0.execdom0("xe network-param-set uuid=%s name-label=bla" % network)
        
        # now join h1 to h0
        pool.addHost(h1)
        
        time.sleep(180)
        
        # now check that there isn't a new network with the name "Pool-wide network associated with eth0"
        ret = h0.execdom0("xe network-list name-label=Pool-wide\ network\ associated\ with\ eth0")
        
        if "uuid" in ret:
            raise xenrt.XRTFailure("New invalid network created on pool-join.")

class TC12527(xenrt.TestCase):
    """Test host gets enabled after pool join if it has a VLAN that the pool does not have"""
    
    def run(self, arglist=None):
        pool = self.getPool("RESOURCE_POOL_0")
        h0 = self.getHost("RESOURCE_HOST_0")
        h1 = self.getHost("RESOURCE_HOST_1")
        
        # create VLAN
        vlan=1
        nic = h1.getDefaultInterface()
        bridge = h1.createNetwork()
        h1.createVLAN(vlan, bridge, nic) 
        h1.checkVLAN(vlan, nic)
        
        # now join h1 to h0
        pool.addHost(h1)
        
        time.sleep(180)
        
        # now check h1 is enabled
        ret = h0.execdom0("xe host-param-get param-key=enabled uuid=%s param-name=enabled" % h1.uuid)
        
        if not "true" in ret:
            raise xenrt.XRTFailure("Host not enabled after added host with VLANs to pool.")

class TC12521(xenrt.TestCase):

    def prepare(self, arglist=[]):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericWindowsGuest(drivers=False)
        self.uninstallOnCleanup(self.guest)

    def run(self, arglist=[]):
        ifdata = self.host.getLinuxIFConfigData()
        tapmac = ifdata["tap%s.0" % (self.guest.getDomid())]["MAC"] 
        for bridge in self.host.getBridges():
            if bridge in ifdata:
                if ifdata[bridge]["MAC"] == tapmac:
                    raise xenrt.XRTFailure("Bridge %s has MAC of TAP." % (bridge))
        if not tapmac == "FE:FF:FF:FF:FF:FF":
            raise xenrt.XRTFailure("TAP MAC is %s rather than FE:FF:FF:FF:FF:FF." % (tapmac))

class TC15523(xenrt.TestCase):
    """Test that sync_vlans=false other-config key correctly suppresses VLAN replication from master to slave"""
    
    def run(self, arglist):
        pool = self.getDefaultPool()
        host1 = self.getHost("RESOURCE_HOST_1")
        
        host1.setHostParam("other-config:sync_vlans", "nosync")
        
        vlans = pool.master.minimalList("vlan-list")
        
        if len(vlans) != 1:
            raise xenrt.XRTFailure("Expecting only 1 VLAN expected before pool join. Found: " + str(len(vlans)))

        # now add host1 to pool and check vlans not synced
        pool.addHost(host1)
        
        vlans = pool.master.minimalList("vlan-list")
        
        if len(vlans) != 1:
            raise xenrt.XRTFailure("Expecting only 1 VLAN expected after pool join with sync_vlans=nosync. Found: " + str(len(vlans)))
    
   
class TCWith16Nics(xenrt.TestCase):
    """Test a host with 16 NICS"""
    # Jira TC15864    

    def prepare(self, arglist=None):
        
        self.pool = self.getDefaultPool()
        if self.pool is None:
            self.host = self.getDefaultHost()
        else:
            self.host = self.pool.master

        self.guest = self.getGuest("lin0")
        if self.guest.getState() == 'UP':
            self.guest.shutdown()
        self.test_guests = []
        
        self.all_pifs = set([self.host.parseListForUUID("pif-list", "MAC", self.host.getNICMACAddress(x))
                            for x in ([0] + self.host.listSecondaryNICs(network="NPRI"))])
        
        #Check if the pifs are valid
        for pif in self.all_pifs:
            if not pif or (',' in pif):
                raise xenrt.XRTError("Pifs are not ready to bond. There are existing bonds present probably")
        
        self.management_pif = self.host.parseListForUUID("pif-list", "management", "true")


    def cloneVM(self, host, guest, pif_uuid=None, bridge=None):

        new_guest = guest.cloneVM()
        old_vifs = new_guest.getVIFs()

        cli = host.getCLIInstance()
        for eth_dev in old_vifs.keys():
            vif_uuid = new_guest.getVIFUUID(eth_dev)
            cli.execute('vif-destroy', 'uuid=%s' % vif_uuid)
        
        if bridge is None:
            network_uuid = host.genParamGet("pif", pif_uuid, "network-uuid")
            bridge = host.genParamGet("network", network_uuid, "bridge")
        mac = xenrt.randomMAC()
        new_guest.createVIF(bridge=bridge, mac=mac)
        new_guest.tailored = True
        new_guest.start(managebridge=bridge)

        return new_guest


    def run(self, arglist=None):

        #. Assign IP address to each interface.
        pifs_without_ip = self.all_pifs - set([self.management_pif])
        
        # We are interested in only 16 NICs (including the management PIF)
        self.interesting_pifs = list(pifs_without_ip)[0:15]

        for pif in self.interesting_pifs:
            self.host.enableIPOnPIF(pif)
        
        #. Bring up a VM on each NIC
        for pif in self.interesting_pifs:
            self.test_guests.append(self.cloneVM(self.host, self.guest, pif_uuid=pif))
            
        self.guest.start()

    def postRun(self):
        for g in self.test_guests:
            g.uninstall()
            
        cli = self.host.getCLIInstance()
        for pif in self.interesting_pifs:
            self.host.removeIPFromPIF(pif)
            cli.execute("pif-plug", "uuid=%s" % (pif))
        self.guest.shutdown()

class _TCIperfDom0toWinGuest(xenrt.TestCase):
    """Iperf packets from Dom0 to Windows guest
    (regression test for CA-89061 - XENNET does not handle some GSO packets from netback)"""
    
    DISTRO = None
    
    def prepare(self, arglist=None):
    
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericWindowsGuest(distro=self.DISTRO, memory=1024)
        
    def run(self, arglist=None):
        
        step('Installing iperf in Dom0')
        self.host.installIperf()
        
        step('Disabling windows Firewall')
        self.guest.disableFirewall()
        try:
            val = self.guest.getReceiverMaxProtocol()
            log("ReceiverMaximumProtocol = %s" %(val))
        except:
            xenrt.TEC().logverbose("getReceiverMaxProtocol fails post Clearwater")
            
        
        step('Disabling ReceiverMaximumProtocol in windows registry editor')
        self.guest.disableReceiverMaxProto()
        
        val = self.guest.getReceiverMaxProtocol()
        log("ReceiverMaximumProtocol = %s" %(val))
        
        step('Rebooting the guest')
        self.guest.reboot()
        
        step('Installing iperf in Windows guest')
        self.guest.installIperf()
        
        step('Starting iperf server on Windows VM')
        self.guest.startIperf()
        
        step('iperf client at Dom0 started')
        self.host.execdom0("./iperf/iperf -c %s" %(self.guest.getIP()))
        
        step('Checking Guest health')
        self.guest.checkHealth()
        
        
class TCIperfDom0toWin2k8R2SP1x64(_TCIperfDom0toWinGuest):
    """Iperf packets from Dom0 to Windows 2008 R2 Service Pack 1 64 bit"""
    # jira TC-18498
    DISTRO = "ws08r2sp1-x64"
    
class TCIperfDom0toWin7x64(_TCIperfDom0toWinGuest):
    """Iperf packets from Dom0 to Windows 7 SP1 64 bit"""
    # jira TC-18503
    DISTRO = "win7sp1-x64"
    
class TCIperfDom0toWin7x32(_TCIperfDom0toWinGuest):
    """Iperf packets from Dom0 to Windows 7 SP1 32 bit"""
    # jira TC-18504
    DISTRO = "win7sp1-x86"

class _TCWinGuestMTU(xenrt.TestCase):
    """ Base class for MTU check for windows guests
    (regression test for SCTX-1156 - MTU set to 1496 for Windows 2003 VM running 6.0.2 XenTools)"""
    DISTRO = None
    
    def prepare(self, arglist=None):
        
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericWindowsGuest(distro=self.DISTRO)
        self.xrtcontrollerIP = xenrt.TEC().lookup("XENRT_SERVER_ADDRESS")
        
        step('pinging the controller with 1300 bytes packet')
        d = self.guest.xmlrpcExec(("ping -f -l 1300 %s" %(self.xrtcontrollerIP)), returndata=True, returnerror=False)
        xenrt.sleep(30)
        log(d)
        
        step('Verifying the ping output')
        if re.search("Reply from .* TTL=", d):
            log("%s able to ping controller %s" %(self.guest.getName(),self.xrtcontrollerIP))
        else:
            raise xenrt.XRTError("%s not able to ping controller %s" %(self.guest.getName(), self.xrtcontrollerIP))
            
    def run(self, arglist=None):
    
        step('pinging the controller with 1472 bytes packet')
        d = self.guest.xmlrpcExec(("ping -f -l 1472 %s" %(self.xrtcontrollerIP)), returndata=True, returnerror=False)
        xenrt.sleep(30)
        log(d)
        
        step('Verifying the ping output')
        if re.search("Packet needs to be fragmented but DF set", d):
            raise xenrt.XRTFailure("Packet needs to be fragmented but DF set:MTU size is not 1500")
        elif re.search("Reply from .* TTL=", d):
            log("MTU size is 1500")
            pass
        elif re.search("Destination host unreachable", d):
            raise xenrt.XRTError("Destination host unreachable")
        else:
            raise xenrt.XRTError("Could not parse ping data")

class TCWinGuestMTUW2k3x64(_TCWinGuestMTU):
    """ MTU check for Windows 2003 Enterprise Edition ServicePack 2 64 bit"""
    # jira TC-18495
    DISTRO = "w2k3eesp2-x64"
    
class TCWinGuestMTUW2k3(_TCWinGuestMTU):
    """ MTU check for Windows 2003 Enterprise Edition ServicePack 2 32 bit"""
    # jira TC-18501
    DISTRO = "w2k3eesp2"

class TCWinGuestMTUWin7x86(_TCWinGuestMTU):
    """ MTU check for Windows 2003 Enterprise Edition ServicePack 2 32 bit"""
    # jira TC-18501
    DISTRO = "win7-x86"
    
class TCWinGuestMTUWin8x86(_TCWinGuestMTU):
    """ MTU check for Windows 2003 Enterprise Edition ServicePack 2 32 bit"""
    # jira TC-18501
    DISTRO = "win8-x86"
    
class TCWinGuestMTUW2k8R2Sp1(_TCWinGuestMTU):
    """ MTU check for Windows 2003 Enterprise Edition ServicePack 2 32 bit"""
    # jira TC-18501
    DISTRO = "ws08r2sp1-x64"


class _TCDom0GuestPerf(xenrt.TestCase):
    # Traffic Direction
    DOM0_TO_GUEST = 1
    GUEST_TO_DOM0 = 2

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.guests = []
        guestNames = self.host.listGuests()
        xenrt.TEC().logverbose("Guests: %s found on %s" % (guestNames, self.host.getName()))
        if len(guestNames):
            for guestName in guestNames:
                guest = self.host.getGuest(guestName)
                self.guests.append(guest)
                xenrt.TEC().logverbose("Using guest: %s" % (guest.getName()))

                if guest.getState() != 'UP':
                    guest.start()
                guest.installIperf()
        else:
            raise xenrt.XRTError("No guest available on host")
        
        self.host.execdom0("yum --disablerepo=citrix --enablerepo=base install make gcc-c++ -y")
        self.host.installIperf()

    def _stopFirewallServiceForLegacyWindowsVMs(self):
        """This works around a problem with XP and WS2003 (see XOP-911).  The correct solutiuon would be to
           install the latest updates onto these distros"""
        WINDOWS_FIREWALL_SERVICE_NAME = 'Windows Firewall/Internet Connection Sharing (ICS)'
        for guest in self.guests:
            if guest.windows and guest.usesLegacyDrivers():
                # Stop the firewall service.
                xenrt.TEC().logverbose('Stopping Firewall Service for guest: %s' % (guest.name))
                try:
                    guest.xmlrpcExec('net stop "%s"' % (WINDOWS_FIREWALL_SERVICE_NAME))
                except Exception, e:
                    xenrt.TEC().warning('Stopping firewall service failed for Guest: %s.  Exception: %s' % (guest.name, str(e)))

    def _parseIperfData(self, data):
        iperfData = {}
        dataFound = False
        for line in data.splitlines():
            xenrt.TEC().logverbose(line)
  
            if line.startswith('[SUM]'):
                lineFields = line.split()
                if len(lineFields) != 7:
                    raise xenrt.XRTError('Failed to parse SUM output from Iperf')
                iperfData['transfer'] = int(lineFields[3])
                iperfData['bandwidth'] = int(lineFields[5])
                dataFound = True

        if not dataFound:
            raise xenrt.XRTError('Failed to parse general output from Iperf')
        return iperfData

    def _getHostIperfStats(self, host, guest, trafficDirection):
        host.execdom0("service iptables stop")

        if trafficDirection == self.DOM0_TO_GUEST:
            xenrt.sleep(10)
            rawData = host.execdom0("iperf/iperf -c %s -f m -P 4 -w 256K -l 256K -t 60" % (guest.getIP()))
        elif trafficDirection == self.GUEST_TO_DOM0:
            rawData = host.execdom0("iperf/iperf -s -f m -P 4 -w 256K -l 256K")
        else:
            raise xenrt.XRTError('Unknown trafficDirection: %s' % (trafficDirection))

        host.execdom0("service iptables start")
        data = self._parseIperfData(rawData)
        return data

    def _getGuestIperfStats(self, host, guest, trafficDirection):
        # Start iperf in guest
        if guest.windows:
            # Stop the firewall
            guest.disableFirewall()

            if trafficDirection == self.DOM0_TO_GUEST:
                rawData = guest.xmlrpcExec('c:\\iperf.exe -s -f m -P 4 -w 256K -l 256K', returndata=True)
            elif trafficDirection == self.GUEST_TO_DOM0:
                xenrt.sleep(5)
                rawData = guest.xmlrpcExec('c:\\iperf.exe -c %s -f m -P 4 -w 256K -l 256K -t 60' % (host.getIP()), returndata=True)
            else:
                raise xenrt.XRTError('Unknown trafficDirection: %s' % (trafficDirection))

            #guest.enableFirewall()
        else:
            raise xenrt.XRTError("Test doesn't support Linux guests")

        data = self._parseIperfData(rawData)
        return data

    def getBandwidth(self, host, guest, trafficDirection):
        (hostStats, guestStats) = xenrt.pfarm([xenrt.PTask(self._getHostIperfStats, host, guest, trafficDirection),
                                               xenrt.PTask(self._getGuestIperfStats, host, guest, trafficDirection)])

#        if float(abs(hostStats['bandwidth'] - guestStats['bandwidth'])) / min(hostStats['bandwidth'], guestStats['bandwidth']) > 0.05:
#            raise xenrt.XRTError('Inconsistent Iperf bandwidth data from guest and host')
        if float(abs(hostStats['transfer'] - guestStats['transfer'])) / min(hostStats['transfer'], guestStats['transfer']) > 0.05:
            raise xenrt.XRTError('Inconsistent Iperf transfer data from guest and host')

        actualBandwidth = 0
        if trafficDirection == self.DOM0_TO_GUEST:
            actualBandwidth = hostStats['bandwidth']
            xenrt.TEC().comment('Bandwidth from Dom0 to guest [%s] (MBits/sec): %d' % (guest.name, actualBandwidth))
        elif trafficDirection == self.GUEST_TO_DOM0:
            actualBandwidth = guestStats['bandwidth']
            xenrt.TEC().comment('Bandwidth from guest [%s] to Dom0 (MBits/sec): %d' % (guest.name, actualBandwidth))
        else:
            raise xenrt.XRTError('Unknown trafficDirection: %s' % (trafficDirection))

        return actualBandwidth

    def run(self, arglist=[]):
        raise xenrt.XRTError('Base class not executable as a test')

class TC18882(_TCDom0GuestPerf):
    EXPECTED_GUEST_TO_DOM0_BANDWIDTH = 5000

    def run(self, arglist=[]):
        self._stopFirewallServiceForLegacyWindowsVMs()
        allPassed = True
        bwList = map(lambda x:self.getBandwidth(self.host, x, self.GUEST_TO_DOM0), self.guests)
        for bw, guest in zip(bwList, self.guests):
            xenrt.TEC().logverbose('  Guest: %s, Bandwidth: %d' % (guest.name, bw))
            if bw < self.EXPECTED_GUEST_TO_DOM0_BANDWIDTH:
                xenrt.TEC().comment('Insufficient bandwidth between guest [%s] and Dom0: Expected (MBits/sec): %d, Actual (MBits/sec): %d' % (guest.name, self.EXPECTED_GUEST_TO_DOM0_BANDWIDTH, bw))
                allPassed = False

        if not allPassed:
            raise xenrt.XRTFailure('Insufficient bandwidth between guest and Dom0')

class TC18883(_TCDom0GuestPerf):
    EXPECTED_DOM0_TO_GUEST_BANDWIDTH = 2000

    def run(self, arglist=[]):
        self._stopFirewallServiceForLegacyWindowsVMs()
        allPassed = True
        bwList = map(lambda x:self.getBandwidth(self.host, x, self.DOM0_TO_GUEST), self.guests)
        for bw, guest in zip(bwList, self.guests):
            xenrt.TEC().logverbose('  Guest: %s, Bandwidth: %d' % (guest.name, bw))
            if bw < self.EXPECTED_DOM0_TO_GUEST_BANDWIDTH:
                xenrt.TEC().comment('Insufficient bandwidth between Dom0 and guest [%s]: Expected (MBits/sec): %d, Actual (MBits/sec): %d' % (guest.name, self.EXPECTED_DOM0_TO_GUEST_BANDWIDTH, bw))
                allPassed = False

        if not allPassed:
            raise xenrt.XRTFailure('Insufficient bandwidth between Dom0 and guest')
        
class TCGuestNetworkConfig(_TCDom0GuestPerf):

    def _getOffloadValue(self, offloadSettings):
        raise xenrt.XRTError('Base class not executable as a test')

    def _setOffloadValue(self, offloadSettings, value):
        raise xenrt.XRTError('Base class not executable as a test')

    def runPerfTest(self, guest, trafficDirection, newOffloadValue):
        offloadSettings = guest.getVifOffloadSettings(0)
        previousValue = self._getOffloadValue(offloadSettings)
        if previousValue < 0:
            xenrt.TEC().logverbose('Failed to read offload value')
            return -1
        xenrt.TEC().logverbose('Previous value: %d, New value: %d' % (previousValue, newOffloadValue))
        self._setOffloadValue(offloadSettings, newOffloadValue)
        if previousValue != newOffloadValue:
            guest.reboot()
        bandwidth = self.getBandwidth(self.host, guest, trafficDirection)
        return bandwidth


class TC18884(TCGuestNetworkConfig):

    def _getOffloadValue(self, offloadSettings):
        return offloadSettings.getLargeReceiveOffload()

    def _setOffloadValue(self, offloadSettings, value):
        offloadSettings.setLargeReceiveOffload(value)

    def run(self, arglist=[]):
        lroEnable1 = map(lambda x:self.runPerfTest(x, self.DOM0_TO_GUEST, 1), self.guests)
        lroDisable = map(lambda x:self.runPerfTest(x, self.DOM0_TO_GUEST, 0), self.guests)
        lroEnable2 = map(lambda x:self.runPerfTest(x, self.DOM0_TO_GUEST, 1), self.guests)

        for guest in self.guests:
            xenrt.TEC().logverbose('Bandwidth for Guest: %s' % (guest.name))
            ix = self.guests.index(guest)
            xenrt.TEC().logverbose('  LRO enabled (first run): Bandwidth (MBits/sec):   %d' % (lroEnable1[ix])) 
            xenrt.TEC().logverbose('  LRO disabled (first run): Bandwidth (MBits/sec):  %d' % (lroDisable[ix])) 
            xenrt.TEC().logverbose('  LRO enabled (second run): Bandwidth (MBits/sec):  %d' % (lroEnable2[ix])) 

class TC19275(xenrt.TestCase):
    """ HFX-723 testing. 
    Verify force reboot/shutdown does not timeout while guest sends large broadcast packets to host"""
   
    def prepare(self, arglist):
        self.host=self.getDefaultHost()
        self.guest=self.host.createBasicGuest(distro="centos56")
        hostScript="""
import socket
import signal
import sys

PORT = 9930

def sig_handler(signal, frame):
    print "you have interrupted"
    sock.close()
    sys.exit(0)

if __name__ == "__main__":
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("",PORT))
    signal.signal(signal.SIGINT,sig_handler)

    while True:
       #print "not receiving"
       pass
"""  
        #writing the recv.py script to /tmp directory on host side
        sftp = self.host.sftpClient()
        t = xenrt.TEC().tempFile()
        f = file(t, "w")
        f.write(hostScript)
        f.close()
        sftp.copyTo(t, "/tmp/recv.py")

        #getting the bcast address
        mpif = self.host.parseListForUUID("pif-list",
                                          "management",
                                          "true",
                                          "host-uuid=%s" % (self.host.getMyHostUUID()))
        netmask = self.host.genParamGet("pif", mpif, "netmask")
        subnet = xenrt.util.calculateSubnet(self.host.getIP(), netmask)
        bcast = xenrt.util.calculateLANBroadcast(subnet, netmask)
        xenrt.TEC().logverbose("The broadcast address is %s" %bcast)

        #writing script on guest side

        guestScript="""
import socket

DST = "%s"
PORT = 9930
MSG = "a"*999+"b"

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

#for i in range(5):
sock.sendto(MSG, (DST,PORT))
sock.close()
""" %bcast


        #writing the recv.py script to /tmp directory
        sftp = self.guest.sftpClient()
        t = xenrt.TEC().tempFile()
        f = file(t, "w")
        f.write(guestScript)
        f.close()
        sftp.copyTo(t, "/tmp/send.py")
        
    def run(self,arglist):
    
        #xe-switch-network-backend bridge on host side
        self.host.execdom0("xe-switch-network-backend bridge")

        #host reboot
        self.host.reboot()

        #start the guest
        if not self.guest.getState()=="UP":
            self.guest.start()

        #stop iptables on host
        self.host.execdom0("service iptables stop")

        #start recv.py on host, try-except block needed because this will throw ssh timed out exception
        try:
            self.host.execdom0("python /tmp/recv.py")
        except: pass

        #start send.py multiple times on guest
        for i in range(5):
            self.guest.execguest("python /tmp/send.py")

        #try a guest force-reboot
        cli=self.host.getCLIInstance()
        cli.execute("vm-reboot","uuid=%s --force" %(self.guest.getUUID()))
        
        #try a guest force-shutdown
        cli.execute("vm-shutdown","uuid=%s --force" %(self.guest.getUUID()))

    def postRun(self):
    
        #killing the recv.py process on host
        pid=self.host.execdom0("pgrep -f 'python /tmp/recv.py'").strip()
        self.host.execdom0("kill %s" %pid)
        
        #removing the guest
        try: self.guest.shutdown(force=True)
        except: pass
        
        try: self.guest.uninstall()
        except: pass
        
        
class TCHfx745(xenrt.TestCase):
    """ Test to check that packets larger than 64 KiB sent from a guest to Dom0 are dropped at netback and 
        the guest does not loose connectivity"""
    
    DISTRO = "centos57"
    
    def prepare(self, arglist=None):
        
        self.host = self.getDefaultHost()
        self.guest = self.host.createBasicGuest(self.DISTRO)
        
        self.host.installIperf()
        self.guest.installIperf()
        
        self.guest.checkReachable()
        
    def run(self, arglist=None):
        
        step("Set the Guest MTU to 100")
        self.guest.execguest("ifconfig eth0 mtu 100 up", nolog=True)
        
        step("Start iperf server on host")
        self.host.execdom0("service iptables stop")
        self.host.execdom0("./iperf/iperf -s -w 256K > /dev/null 2>&1 < /dev/null &")
        
        step("Send iperf packets of size 65 KiB from guest to host")
        self.guest.execguest("iperf -c %s -w 256K" % self.host.getIP())
        
        step("Verify if guest is reachable")
        self.guest.checkReachable()
        log("The guest did not lose connectivity")
        
class TCHfx799(TCHfx745):
    DISTRO = "debian60"

class TC20918(xenrt.TestCase):
    """Verify that DNS servers gets cleared when reconfiguring to static IP without DNS (HFX-959)"""
    def run(self, arglist):
        h = self.getDefaultHost()
        self.pif = h.getNICPIF(0)
        ip = h.genParamGet("pif", self.pif, "IP")
        netmask = h.genParamGet("pif", self.pif, "netmask")
        dns = h.execdom0("cat /etc/resolv.conf | grep nameserver | head -1 | awk '{print $2}'").strip()
        gateway = h.execdom0("""route -n | awk '{if ($1=="0.0.0.0") print $2}'""").strip()
        h.getCLIInstance().execute("""pif-reconfigure-ip mode=static uuid=%s DNS=%s IP=%s gateway=%s netmask=%s""" % (self.pif,dns,ip,gateway,netmask))
        h.getCLIInstance().execute("""pif-reconfigure-ip mode=static uuid=%s DNS="" IP=%s gateway=%s netmask=%s""" % (self.pif,ip,gateway,netmask))
        if h.genParamGet("pif", self.pif, "DNS") != "":
            raise xenrt.XRTFailure("DNS servers not cleared after reconfiguring to static IP without DNS")

    def postRun(self):
        h = self.getDefaultHost()
        h.getCLIInstance().execute("""pif-reconfigure-ip mode=dhcp uuid=%s""" % (self.pif))

class TC20921(xenrt.TestCase):
    """Verify VLAN 0 Behavior"""  

    VLANNAME = "VR01"
    
    def prepare(self, arglist=None):
        """Create a Linux guest"""
        
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
       
    def configureVlan(self , vlanid):
        """Configure a VLAN and see if it can DHCP """
        
        self.guest.execguest("modprobe 8021q")
        self.guest.execguest("vconfig add eth0 %s" % (vlanid))
        self.guest.execguest("dhclient eth0.%s" % (vlanid))
        data = self.guest.execguest("ifconfig eth0.%s" % (vlanid))
        ip = re.search(".*inet (addr:)?(?P<ip>[0-9\.]+)", data)
        return ip
        
    def run(self, arglist=None):

        vlanid, subnet, netmask = self.host.getVLAN(self.VLANNAME)
        self.guest.execguest("apt-get install -y vlan --force-yes")
        
        ip = self.configureVlan(vlanid)
        if ip:
            ip = ip.group("ip")
            xenrt.TEC().logverbose("eth0.%s got address %s as expected." % (vlanid,ip))
        else:
            raise xenrt.XRTFailure("eth0.%s failed to get address when expected." % (vlanid))
        
        self.guest.shutdown()
        
        """Create a network and VLAN using vlan ID 0 and move VM to use this network"""
        
        self.networkuuid = self.host.createNetwork("NewNetwork1")
        nic = self.host.getDefaultInterface()
        vlanpif = self.host.createVLAN(0, self.networkuuid, nic)
        self.vlanuuid = self.host.parseListForUUID("vlan-list", "tag", 0)
        vifs = self.guest.getVIFs()
        for vif in vifs:
            self.guest.removeVIF(vif)
        
        vif = self.guest.createVIF(bridge=self.networkuuid)
        self.guest.start()
        
        ip = self.configureVlan(vlanid)
        if ip:
            ip = ip.group("ip")
            raise xenrt.XRTFailure("eth0.%s got address %s while it is not expected" % (vlanid , ip))
        else:
            xenrt.TEC().logverbose("eth0.%s didn't get address as expected." % (vlanid))
        
    def postRun(self):
    
        self.cli = self.host.getCLIInstance()
        self.guest.shutdown()
        
        vifs = self.guest.getVIFs()
        for vif in vifs:
            self.guest.removeVIF(vif)
            
        if self.vlanuuid:
            try: self.cli.execute("vlan-destroy", "uuid=%s" % (self.vlanuuid)) 
            except: pass 
        if self.networkuuid:
            try: self.cli.execute("network-destroy", "uuid=%s" % (self.networkuuid)) 
            except: pass 

class TC2VlansPerBridge(xenrt.TestCase):
    """ 2 VLANs should not be created on 1 bridge (Linux bridge only) """
    # jira TC-20912 

    def run(self, arglist=None):
        self.host = self.getDefaultHost()
        self.cli = self.host.getCLIInstance()
        # Find out the eth0 PIFs on each host
        hostEth0Pif = self.cli.execute("pif-list", "device=eth0 host-uuid=%s params=uuid --minimal" % self.host.uuid)
        self.network = self.cli.execute("network-create", "name-label=vlan-net1")
        
        step("Copy state.db file")
        self.host.execdom0("service xapi stop")
        self.host.execdom0("cp /var/xapi/state.db /tmp/state.db")
        self.host.execdom0("service xapi start")
        xenrt.sleep(60)
        
        step("Create vlan 1")
        hostVlan1 = self.cli.execute("vlan-create", "vlan=1 network-uuid=%s pif-uuid=%s" % (self.network.strip(), hostEth0Pif.strip()))
        
        step("Replace xapi using old state file")
        self.host.execdom0("service xapi stop")
        self.host.execdom0("yes | cp /tmp/state.db /var/xapi/state.db")
        self.host.execdom0("service xapi start")
        xenrt.sleep(60)
        
        step("Create vlan 2")
        self.hostVlan2 = self.cli.execute("vlan-create", "vlan=2 network-uuid=%s pif-uuid=%s" % (self.network.strip(), hostEth0Pif.strip()))
        
        step("Count interfaces on bridge")
        count = int(self.host.execdom0('brctl show | grep "eth0." | wc -l'))
        log("Number of interfaces on bridge = %d" % count)
        if count == 2:
            raise xenrt.XRTFailure("Found 2 interfaces for a bridge - not expected")
            
    def postRun(self):
        self.cli.execute("vlan-destroy", "uuid=%s" % self.hostVlan2)
        self.cli.execute("network-destroy", "uuid=%s" % self.network)
        self.host.reboot()


class TCQoSNetwork(xenrt.TestCase):

    def __init__(self, tcid="TCQoSNetwork"):
        xenrt.TestCase.__init__(self, tcid)
        self.timeout = 300
        self.guestsToClean = []

    def run(self, arglist=None):
        """Argument is either a machine name or "guest=<guestname>" to
        use an existing guest."""

        guestname = xenrt.TEC().lookup("guest", None, boolean=False)
        for arg in arglist:
            l = string.split(arg, "=")
            if l[0] == "guest":
                if not guestname:
                    guestname = l[1]
                    xenrt.TEC().logverbose("found guest name: %s" % guestname)
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    guestname = matching[0]
            elif l[0] == "timeout":
                self.timeout = int(l[1])
            else:
                raise xenrt.XRTError("Unknown argument %s" % (arglist[0]))

        self.declareTestcase("LinuxGuest", "rate100")
        self.declareTestcase("LinuxGuest", "rate1000")
        self.declareTestcase("LinuxGuest", "rate5000")

        if guestname:
            # Use existing guest
            g = self.getGuest(guestname)
            if not g:
                raise xenrt.XRTError("Unable to find guest %s in registry" %
                                     (guestname))
            self.getLogsFrom(g.host)
            if g.getState() == "DOWN":
                g.start()
        else:
            self.host = self.getDefaultHost()
            self.getLogsFrom(self.host)

            # Create a basic guest
            g = self.host.createGenericLinuxGuest()
            self.guestsToClean.append(g)

        g.installIperf()

        # Get a peer.
        self.peer = xenrt.NetworkTestPeer()

        # Check we can get network transfers with an acceptable rate
        measured = self.testRate(g)
        self.tec.comment("Unlimited guest rate %u KBytes/sec" % (measured))
        g.shutdown()
        self.qosguest = g

        self.runSubcase("rate", (100, measured), "LinuxGuest", "rate100")
        self.runSubcase("rate", (1000, measured), "LinuxGuest", "rate1000")
        self.runSubcase("rate", (5000, measured), "LinuxGuest", "rate5000")

    def testRate(self, guest):
        """Perform a transfer from the VM and measure the rate (KBytes/sec)"""
        data = guest.execcmd("iperf -c %s -t %d -f K -i 60" % 
                             (self.peer.getAddress(), self.timeout), timeout=self.timeout + 30)
        readings = map(float, re.findall("([0-9\.]+) KBytes/sec", data))
        return sum(readings)/len(readings)

    def rate(self, target=100, unlimited_measured = None):

        g = self.qosguest
        g.setState("DOWN")
        vifs = g.getVIFs() 
        try:
            for v in vifs.keys():
                g.setVIFRate(v, target)

            g.start()
            measuredlim = self.testRate(g)
            self.tec.comment("%u limited guest rate %u KBytes/sec" % (target, measuredlim))

            # Put the rate back to zero and check again
            if unlimited_measured:
                measured = unlimited_measured
                self.tec.comment("Given unlimited guest rate %u KBytes/sec" % (measured))
            else:
                g.shutdown()
                for v in vifs.keys():
                    g.setVIFRate(v)

                g.start()
                measured = self.testRate(g)
                self.tec.comment("Unlimited guest rate %u KBytes/sec" % (measured))
        except Exception, e:
            raise e
        finally:
            g.setState("DOWN")
            for v in vifs.keys():
                g.setVIFRate(v)

        # Check the unlimited rate is somewhat more than the target restriction
        # so there is actually something to test.
        wl = target * 2
        if measured < wl:
            self.tec.warning("Unlimited rate %u KBytes/sec is not a lot higher than the target limit of %u KBytes/sec" % (measured, target))

        # Check measured limited rate is within 50% and 120% of the target
        wh = target * 120 / 100
        wl = target / 2
        if measuredlim > wh:
            raise xenrt.XRTFailure("Measured rate %u KBytes/sec is more than 20%% higher than the target %u KBytes/sec" % (measuredlim, target))
        if measuredlim < wl:
            raise xenrt.XRTFailure("Measured rate %u KBytes/sec is more than 50%% lower than the target %u KBytes/sec" % (measuredlim, target))

    def postRun(self):
        if self.peer:
            try:
                self.peer.release()
            except:
                pass
        for g in self.guestsToClean:
            try:
                g.shutdown(force=True)
            except:
                pass
            g.poll("DOWN", 120, level=xenrt.RC_ERROR)
            g.uninstall()

class TCFCOEVmVlan(xenrt.TestCase):
    """VLAN operations on FCoE SR."""
    
    SRTYPE = "lvmofcoe"
    
    def prepare(self, arglist):

        self.host = self.getDefaultHost() 
        self.vlansToRemove = []
        self.sruuid = self.host.minimalList("sr-list", args="type=%s" %(self.SRTYPE))[0]
        
    def run(self, arglist):

        step("Get available VLANs")
        vlans = self.host.availableVLANs()
        if len(vlans) == 0:
            xenrt.TEC().skip("No VLANs defined for host")
            return
        vlan, subnet, netmask = vlans[0]

        step("Create a VLAN network on the primary interface")
        nic = self.host.getDefaultInterface()
        vbridge = self.host.createNetwork()
        self.host.createVLAN(vlan, vbridge, nic) 
        self.vlansToRemove.append(vlan)
        self.host.checkVLAN(vlan, nic)

        step("Install a VM using the VLAN network")
        bridgename = self.host.genParamGet("network", vbridge, "bridge")
        g = self.host.createGenericLinuxGuest(bridge=bridgename, sr=self.sruuid)

        step("Check the VM")
        g.check()
        g.checkHealth()
        
        if subnet and netmask:
            ip = g.getIP()
            if xenrt.isAddressInSubnet(ip, subnet, netmask):
                xenrt.TEC().comment("%s is in %s/%s" % (ip, subnet, netmask))
            else:
                xenrt.TEC().comment("%s is not in %s/%s" %
                                    (ip, subnet, netmask))
                raise xenrt.XRTFailure("VM IP address not from VLAN subnet")
        else:
            xenrt.TEC().comment("Skipping guest IP check")

        if xenrt.TEC().lookup("OPTION_SKIP_VLAN_CLEANUP", False, boolean=True):
            return
        
        step("Write some random data to disk and check md5sum of the file")
        g.execguest("dd if=/dev/urandom of=/file1 count=1000000 conv=notrunc oflag=direct",timeout=3600)
        md5checksumbefore = g.execguest("md5sum /file1").split()[0]
        xenrt.log("md5sum of original file is %s" % md5checksumbefore)

        step("Shutdown VM ")
        g.shutdown()
        
        step("Remove the VLAN interface")
        self.host.removeVLAN(vlan)
        self.vlansToRemove.remove(vlan)
        
        vifs = g.getVIFs()
        for vif in vifs:
            g.removeVIF(vif)
        
        g.createVIF(bridge=self.host.getPrimaryBridge())
        
        step("Start VM and copy the file over new interface and verify the md5sum")
        g.start()
        g.execguest("dd if=/file1 of=/file1copy conv=notrunc oflag=direct",timeout=7200)
        md5checksumafter = g.execguest("md5sum /file1copy").split()[0]
        xenrt.log("md5sum of copied file is %s" % md5checksumafter)
        
        if md5checksumbefore == md5checksumafter:
            xenrt.log(" md5sum matched ")
        else:
            raise xenrt.XRTFailure("md5sum match failed")
            
        g.uninstall()
        
class TCFCOEMngR(xenrt.TestCase):
    """Change management interface with host-management-reconfigure."""
    
    SRTYPE = "lvmofcoe"
    
    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.sruuid = self.host.minimalList("sr-list", args="type=%s" %(self.SRTYPE))[0]
        
    def run(self, arglist):

        step("Check for default NIC")
        default = self.host.getDefaultInterface()
        xenrt.TEC().logverbose("Default NIC for host is %s." % (default))   
        defaultuuid = self.host.parseListForUUID("pif-list",
                                            "device",
                                            default).strip()
                                            
        step("Get list of secongary NICs")
        
        nics = self.host.listSecondaryNICs()
        if len(nics) == 0:
            raise xenrt.XRTError("Test must be run on a host with at "
                                 "least 2 NICs.")

        nmi = self.host.getSecondaryNIC(nics[0])
        xenrt.TEC().logverbose("Using new management interface %s." % (nmi)) 

        step("Setting secondary NIC's mode to DHCP")
        
        xenrt.TEC().logverbose("Setting %s mode to DHCP." % (nmi))
        nmiuuid = self.host.parseListForUUID("pif-list", "device", nmi).strip()
        cli = self.host.getCLIInstance()
        cli.execute("pif-reconfigure-ip uuid=%s mode=dhcp" % (nmiuuid))

        step("Changing management interface to secondary NIC")
        
        xenrt.TEC().logverbose("Changing management interface from %s to %s." %
                               (default, nmi))
        try:
            cli.execute("host-management-reconfigure pif-uuid=%s" % (nmiuuid))
        except:
            # This will always return an error.
            pass
        time.sleep(120)

        xenrt.TEC().logverbose("Finding IP address of new management "
                               "interface...")
        data = self.host.execdom0("ifconfig xenbr%s" % (nmi[-1]))
        nip = re.search(".*inet (addr:)?(?P<ip>[0-9\.]+)", data).group("ip")
        xenrt.TEC().logverbose("Interface %s appears to have IP %s." %
                               (nmi, nip))

        xenrt.TEC().logverbose("Start using new IP address.")
        oldip = self.host.machine.ipaddr
        self.host.machine.ipaddr = nip

        step(" Remove IP configuration from the previous management interface")
        
        cli.execute("pif-reconfigure-ip uuid=%s mode=None" % (defaultuuid))
        data = self.host.execdom0("ifconfig xenbr%s" % (default[-1]))
        r = re.search(".*inet (addr:)?(?P<ip>[0-9\.]+)", data)
        if r:
            raise xenrt.XRTFailure("Old management interface still has IP "
                                   "address")

        step("Check the agent responds to an off-host CLI command")
        
        try:
            cli.execute("vm-list")
        except:
            raise xenrt.XRTFailure("Failed to run CLI command over new "
                                   "management interface.")

        g = self.host.createGenericLinuxGuest(sr=self.sruuid)

        step("Check the VM")
        g.check()
        g.checkHealth()
        
        step("")
        g.execguest("dd if=/dev/urandom of=/file1 count=1000000 conv=notrunc oflag=direct",timeout=3600)
        md5checksumbefore = g.execguest("md5sum /file1").split()[0]
        xenrt.log("md5sum of original file is %s" % md5checksumbefore)

        step("Change back to the old management interface")
        
        xenrt.TEC().logverbose("Changing management interface back from "
                               "%s to %s." % (nmi, default))
        cli.execute("pif-reconfigure-ip uuid=%s mode=dhcp" % (defaultuuid))
        try:
            cli.execute("host-management-reconfigure pif-uuid=%s" %
                        (defaultuuid))
        except:
            # This will always return an error.
            pass
        time.sleep(120)

        xenrt.TEC().logverbose("Return to using old IP.")
        self.host.machine.ipaddr = oldip

        step("Check the agent still responds to an off-host CLI command")
        
        try:
            cli.execute("vm-list")
        except:
            raise xenrt.XRTFailure("Failed to run CLI command over old "
                                   "management interface.")

        step("Remove IP configuration from the previous management interface")
        
        cli.execute("pif-reconfigure-ip uuid=%s mode=None" % (nmiuuid))
        data = self.host.execdom0("ifconfig xenbr%s" % (nmi[-1]))
        r = re.search(".*inet (addr:)?(?P<ip>[0-9\.]+)", data)
        if r:
            raise xenrt.XRTFailure("Previous management interface still has "
                                   "IP address")

        step("Check agent operation again")
        try:
            cli.execute("vm-list")
        except:
            raise xenrt.XRTFailure("Failed to run CLI command over old "
                                   "management interface (with IP removed) "
                                   "from the other interface.")

        g.execguest("dd if=/file1 of=/file1copy conv=notrunc oflag=direct",timeout=7200)
        md5checksumafter = g.execguest("md5sum /file1copy").split()[0]
        xenrt.log("md5sum of copied file is %s" % md5checksumafter)

        if md5checksumbefore == md5checksumafter:
            xenrt.log(" md5sum matched ")
        else:
            raise xenrt.XRTFailure("md5sum match failed")
            
        step("Uninstall the VM")
        g.shutdown()
        g.uninstall()
