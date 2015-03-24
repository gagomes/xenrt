#
# XenRT: Test harness for Xen and the XenServer product family
#
# Networking tests.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, os.path, xml.dom.minidom, os, time, re
import xenrt
from random import choice
from xenrt.lazylog import log, step, comment

class TCVIFStress(xenrt.TestCase):

    def __init__(self, tcid="TCVIFStress"):
        xenrt.TestCase.__init__(self, tcid)
        self.bridge = None
        self.viflist = []
        self.guest = None

    def run(self, arglist=None):
        guest = None
        loops = 50
        vifs = 1
        gname = None

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "loops":
                loops = int(l[1])
            elif l[0] == "vifs":
                vifs = int(l[1])
            elif l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("Need to specify a guest name")
        guest = self.getGuest(gname)
        if not guest:
            raise xenrt.XRTError("Could not find guest %s in registry" %
                                 (gname))
        self.guest = guest
        host = guest.host

        # Only run this test if the guest supports hot plug and unplug
        if guest.distro:
            x = string.split(host.lookup("GUEST_NO_HOTPLUG_VIF", ""), ",")
            y = string.split(host.lookup("GUEST_NO_HOTUNPLUG_VIF", ""), ",")
            if guest.distro in x or guest.distro in y:
                xenrt.TEC().skip("Not running VIF plug test on %s" %
                                 (guest.distro))
                return
        
        self.getLogsFrom(host)

        try:
            if guest.getState() == "DOWN":
                xenrt.TEC().logverbose("Starting guest before commencing test.")
                guest.start()
            guest.checkHealth()
        except xenrt.XRTFailure, e:
            # Convert to error
            raise xenrt.XRTError(e.reason, e.data)

        xenrt.TEC().logverbose("Creating temporary test network.")
        nwuuid = host.createNetwork()
        self.bridge = host.genParamGet("network", nwuuid, "bridge")

        basevifs = len(guest.getMyVIFs())
        xenrt.TEC().logverbose("Found %s VIF(s) initially." % (basevifs))

        xenrt.TEC().logverbose("Adding %s VIF(s)." % (vifs))
        for i in range(vifs):
            self.viflist.append(guest.createVIF(None, self.bridge, None))

        xenrt.TEC().progress("Running %s loops of plug/unplug using %s VIF(s)."
                             % (loops, vifs))
        success = 0
        try:
            for i in range(loops):
                xenrt.TEC().logverbose("Plugging VIF(s) iteration %u." % (i))
                for i in self.viflist:
                    guest.plugVIF(i)

                time.sleep(10)
                guest.checkReachable()
                guest.updateVIFDriver()
                data = guest.getMyVIFs()
                xenrt.TEC().logverbose("Plugged: %s" % data)
                if len(data) != basevifs + vifs:
                    xenrt.TEC().warning("Found wrong number of VIFs. Waiting "
                                        "a bit longer...")
                    time.sleep(30)
                    data = guest.getMyVIFs()
                    xenrt.TEC().logverbose("Plugged: %s" % data)
                    if len(data) != basevifs + vifs:
                        raise xenrt.XRTFailure("Found wrong number of VIFs "
                                               "after plugging.")
            
                xenrt.TEC().logverbose("Unplugging VIF(s).")
                for i in self.viflist:
                    guest.unplugVIF(i)
            
                time.sleep(10)
                guest.checkReachable()

                data = guest.getMyVIFs()
                xenrt.TEC().logverbose("Unplugged: %s" % data)
                if len(data) != basevifs:
                    xenrt.TEC().warning("Found wrong number of VIFs. Waiting "
                                        "a bit longer...")
                    time.sleep(30)
                    data = guest.getMyVIFs()
                    xenrt.TEC().logverbose("Unplugged: %s" % data)
                    if len(data) != basevifs + vifs:
                        raise xenrt.XRTFailure("Found wrong number of VIFs "
                                               "after unplugging.")
                success = success + 1
        finally:
            xenrt.TEC().comment("%u/%u iterations successful." %
                                (success, loops))

    def postRun(self):
        for v in self.viflist:
            try:
                self.guest.unplugVIF(v)
            except:
                pass
            try:
                self.guest.removeVIF(v)
            except:
                pass
        try:
            self.guest.host.removeNetwork(self.bridge)
        except:
            pass

class TCInterVMNetworking(xenrt.TestCase):

    def __init__(self, tcid="TCInterVMNetworking"):
        xenrt.TestCase.__init__(self, tcid)
        self.guestsToShutdown = []
        self.vifsToRemove = []
        self.bridge = None
        self.time = 30

    def run(self, arglist=None):
        machine = "RESOURCE_HOST_0"
        guests = None
        vmcount = 0;

        for arg in arglist:
            if arg.startswith('RESOURCE_HOST_0'):
                machine = arg
            if arg.startswith('guests'):
                guests = string.split(arg.split('=')[1],",") 
            if arg.startswith('vmcount'):
                vmcount = int(arg.split('=')[1])
            if arg.startswith('time'):
                self.time = int(arg.split('=')[1])

        if not guests or (len(guests) <= 1 and vmcount == 0):
            raise xenrt.XRTError("At least two guests must be specified.")

        if (len(guests) == 1 ) and (vmcount >1):
            tmpGuests = []
            masterG = self.getGuest(guests[0])
            tmpGuests = [masterG]
 
            masterG.setState("DOWN")

            for i in range(vmcount-1):
                g = masterG.cloneVM(name="%s-clone%d" %(guests[0],i))
                xenrt.TEC().registry.guestPut(g.name, g) 
                tmpGuests.append(g)

            guests = tmpGuests        
        else:
            xenrt.TEC().logverbose("Looking for existing guests: %s" % (guests))
            guests = [ self.getGuest(name) for name in guests ]

        self.guests = guests
        self.host = guests[0].host
        self.getLogsFrom(self.host)

        xenrt.TEC().logverbose("Making sure guests are down.")
        for g in guests: 
            if g.getState() == "UP":
                xenrt.TEC().logverbose("Stopping guest before commencing test")
                g.shutdown()

        xenrt.TEC().progress("Testing Inter-VM networking for guests: %s" %
                            ([ g.name for g in guests ]))

        # Create a network for the guests to communicate over.
        nwuuid = self.host.createNetwork()
        self.bridge = self.host.genParamGet("network", nwuuid, "bridge")

        # Give each guest a VIF on the shared network.    
        for i in range(len(guests)):        
            g = guests[i]
            xenrt.TEC().logverbose("Adding VIF on test network to %s." % (g.name))
            vif = g.createVIF(bridge=self.bridge)
            self.vifsToRemove.append([g, vif])
            g.start()
            self.guestsToShutdown.append(g)
            if g.windows:
                g.updateVIFDriver()
                if xenrt.TEC().lookup("INTERVM_FIX", False, boolean=True):
                    domid = g.host.getDomid(g)
                    dev = re.sub("[a-z]", "", vif)
                    self.host.execdom0("ethtool -K vif%s.%s sg off" % (domid, dev))
            g.configureNetwork(vif, 
                               ip="169.254.0.%d" % (i+1),
                               netmask="255.255.255.0",
                               gateway="169.254.0.1",   
                               metric="100")

        # Install NetPerf server and client on all guests.
        for g in guests:
            xenrt.TEC().logverbose("Installing Netperf on %s." % (g.name))
            g.installNetperf()

        if vmcount > 1:
            #this is only windows VM
            permutations = [[x]+[x+1] for x in range(0,len(guests),2)]
            for p in permutations:
                g = guests[p[1]]
                g.xmlrpcStart("c:\\netserver.exe")
                
            pStart = [xenrt.PTask(self.doPerm, p[0], p[1], "TCP") for p in permutations]
            xenrt.pfarm(pStart)
                
            for p in permutations:
                g = guests[p[1]]
                g.xmlrpcKillAll("netserver.exe")

        else:

            permutations = filter(lambda x:x[0] != x[1],
                             [ [x] + [y] for x in range(len(guests)) for y in range(len(guests)) ])
            for p in permutations:
                g1 = guests[p[0]]
                g2 = guests[p[1]]
                xenrt.TEC().progress("Testing connection from %s(%s) to %s(%s)." % (g1.name, p[0], g2.name, p[1]))

                if g2.windows:
                    g2.xmlrpcStart("c:\\netserver.exe")
                else:
                    self.runAsync(g2, "netserver")
                    try:
                        g2.execguest("/etc/init.d/iptables stop")
                    except:
                        pass

                pair = "%s_%s" % (g1.getName(), g2.getName())
                self.runSubcase("doPerm", (p[0], p[1], "TCP"), pair, "TCP")
                self.runSubcase("doPerm", (p[0], p[1], "UDP"), pair, "UDP")
            
                # Cleanup.
                if g2.windows:
                    g2.xmlrpcKillAll("netserver.exe")
                else:
                    g2.execguest("killall netserver")
                    try:
                        g2.execguest("rm -f /etc/udev/rules.d/z25_persistent-net.rules "
                                     "/etc/udev/persistent-net-generator.rules")
                    except:
                        pass
                    try:
                        g2.execguest("rm -f /etc/udev/rules.d/30-net_persistent_names.rules")
                    except:
                        pass
                    try:
                        g2.execguest("/etc/init.d/iptables start")
                    except:
                        pass            

    def doPerm(self, p0, p1, protocol):
        g1 = self.guests[p0]
        g2 = self.guests[p1]
        try:
            if g1.windows:
                data = g1.xmlrpcExec("c:\\netperf.exe -H 169.254.0.%d "
                                     "-t %s_STREAM -l %d -v 0 -P 0" % 
                                     (p1 + 1, protocol, self.time), returndata=True, timeout=90000, ignoreHealthCheck=True)
            else:
                data = g1.execguest("netperf -H 169.254.0.%d -t %s_STREAM -l 30 "
                                    "-v 0 -P 0" % (p1 + 1, protocol))
        except xenrt.XRTFailure, e:
            # Check VMs are healthy
            g1.checkHealth()
            g2.checkHealth()
            raise
            
        # Process results.
        xenrt.TEC().value("%s_%s_%s" % (protocol, g1.getName(), g2.getName()),
                          self.parseRate(data))

    def parseRate(self, data):
        for line in string.split(data, "\n"):
            if re.search(r"^\s*\d+", line):
                l = string.split(line)
                return float(l[0])
        raise xenrt.XRTError("Could not parse netperf output")

    def postRun(self):
        xenrt.TEC().logverbose("Shutting down %s." %
                              ([ x.name for x in self.guestsToShutdown ]))
        for g in self.guestsToShutdown:
            try:
                g.shutdown(again=True)
            except:
                pass
        for v in self.vifsToRemove:
            try:
                g, vif = v
                g.removeVIF(vif)
            except:
                pass
        try:
            self.host.removeNetwork(self.bridge)
        except:
            pass

class TCTapBridgeTest(xenrt.TestCase):

    def __init__(self, tcid="TCTapBridgeTest"):
        xenrt.TestCase.__init__(self, tcid)
        self.guestsToClean = []
        self.bridges = []

    def run(self, arglist=None):
        """This test check for a VM with VIFs on two bridges being unable to
        bridge packets between those bridges. A VM "nictest", specified by the
        distro argument, is created with one VIF on the main externally
        facing bridge and one on a dedicated internal bridge. A
        VM "nictarget" is set up on the isolated bridge. For the test to
        pass nictarget must not be able to DHCP itself an address. If
        it does then the DHCP request and reply must have been bridged to
        the external network via nictest."""

        machine = "RESOURCE_HOST_0"
        distro = "w2k3eesp2"
        vcpus = None
        memory = None
        arch = "x86-32"

        if arglist and len(arglist) > 0:
            machine = arglist[0]
        for arg in arglist[1:]:
            l = string.split(arg, "=", 1)
            if l[0] == "distro":
                distro = l[1]
            elif l[0] == "vcpus":
                vcpus = int(l[1])
            elif l[0] == "memory":
                memory = int(l[1])

        self.host = xenrt.TEC().registry.hostGet(machine)
        if not self.host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(self.host)

        template = xenrt.lib.xenserver.getTemplate(self.host, distro)
        g = self.host.guestFactory()(xenrt.randomGuestName(), template)       
        self.guestsToClean.append(g)

        if vcpus != None:
            g.setVCPUs(vcpus)
        if memory != None:
            g.setMemory(memory)

        if xenrt.TEC().lookup(["CLIOPTIONS", "NOINSTALL"],
                              False,
                              boolean=True):
            xenrt.TEC().skip("Skipping because of --noinstall option")
            g.existing(self.host)
        else: 
            g.install(self.host,
                      isoname=xenrt.DEFAULT,
                      distro=distro,
                      start=False)

            eth = "%s1" % (g.vifstem)
            g.createVIF( eth, None, xenrt.randomMAC())
            mac, ip, bridge = g.getVIF(eth)
            self.bridges.append(bridge)
            
            t = self.host.createGenericLinuxGuest(start=False)
            self.guestsToClean.append(t)

            vifs = t.getVIFs()
            for vif in vifs:
                t.removeVIF(vif)
            t.createVIF( eth, bridge, mac)

        g.start()
        try:
            # If we are able to get an IP address on nictarget then
            # it must have been able to successfully DHCP a request. The only
            # path the packets could have taken to the outside world (and
            # therefore the DHCP server) is via the multihomed nictest VM.
            t.start()
        except Exception, e:
            # If we didn't get an address then the test passed
            xenrt.TEC().logverbose("Failed to start Debian guest (%s) "
                                   "(this is generally a good thing)." %
                                   (str(e)))
            return
    
        raise xenrt.XRTFailure("Guest network available!") 

    def postRun(self):
        for g in self.guestsToClean:
            try:
                g.shutdown(force=True)
            except:
                pass
            try:
                g.poll("DOWN", 120, level=xenrt.RC_ERROR)
                g.uninstall()
                time.sleep(15)
            except:
                pass
        for b in self.bridges:
            try:
                self.host.removeNetwork(b)
            except:
                pass

class TCNICTest(xenrt.TestCase):

    def __init__(self, tcid="TCNICTest"):
        xenrt.TestCase.__init__(self, tcid)
        self.guestsToClean = []
        self.guestsToShutdown = []
        self.bridges = {}
        self.vifsToRemove = []

    def run(self, arglist=None):

        machine = "RESOURCE_HOST_0"
        distro = "w2k3eer2"
        vcpus = None
        memory = None
        method = "HTTP"
        initial = 1
        max = None
        pxe = False
        arch = "x86-32"
        repository = None
        shutdown = True    
        guestname = None

        if arglist and len(arglist) > 0:
            machine = arglist[0]
        for arg in arglist[1:]:
            l = string.split(arg, "=", 1)
            if l[0] == "distro":
                distro = l[1]
            elif l[0] == "vcpus":
                vcpus = int(l[1])
            elif l[0] == "memory":
                memory = int(l[1])
            elif l[0] == "initial":
                initial = int(l[1])
            elif l[0] == "max":
                max = int(l[1])
            elif l[0] == "pxe":
                pxe = True
            elif l[0] == "noshutdown":
                shutdown = False
            elif l[0] == "guest":
                guestname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        self.shutdown = shutdown
      
 
        if guestname:
            # Use an existing guest.
            g = self.getGuest(guestname)
            distro = g.distro
            if distro and re.search(r"w2kassp4", distro) and \
                   xenrt.TEC().lookup("WORKAROUND_XRT917", False, boolean=True):
                xenrt.TEC().skip("Skipping on Windows 2000")
                return
            self.host = g.host
            self.getLogsFrom(self.host)
            cli = self.host.getCLIInstance()
            xenrt.TEC().progress("Using existing guest %s. (%s)" % (g.getName(), g.getUUID()))

            # Make sure the guest is up.
            if g.getState() == "DOWN":
                xenrt.TEC().logverbose("Starting guest before commencing test.")
                g.start()
            self.guestsToShutdown.append(g)
            g.checkHealth()
        else:
            self.host = xenrt.TEC().registry.hostGet(machine)
            if not self.host:
                raise xenrt.XRTError("Unable to find host %s in registry." % (machine))
            self.getLogsFrom(self.host)
            xenrt.TEC().progress("Installing a new guest...")
            try:
                g = xenrt.lib.xenserver.guest.createVM(self.host,
                                                       xenrt.randomGuestName(),
                                                       distro=distro,
                                                       vcpus=vcpus,
                                                       memory=memory,
                                                       arch=arch,
                                                       pxe=pxe)
                self.guestsToClean.append(g)
                if g.windows:
                    xenrt.TEC().progress("Installing PV drivers on %s. (%s)" % (g.getName(), g.getUUID()))
                    g.installDrivers()
            except xenrt.XRTFailure, e:
                # Anything that breaks here is not a failure of the test.
                raise xenrt.XRTError(e.reason)

        if not g.windows:
            xenrt.TEC().logverbose("Removing troublesome udev rules.")
            g.execguest("rm -f /etc/udev/rules.d/z25_persistent-net.rules "
                        "/etc/udev/persistent-net-generator.rules")

        # Get the bridge the VM is using.
        xmac, xip, mybridge = g.getVIF("%s0" % (g.vifstem))
        xenrt.TEC().logverbose("Using primary bridge %s." % (mybridge))
        
        if shutdown:
            xenrt.TEC().logverbose("Shutting down guest before commencing test.")
            g.shutdown()

        # If we haven't specified a maximum VIF count then use the per-distro
        # product config.
        if not max and distro:
            max = int(g.host.lookup("GUEST_VIFS_%s" % (distro), 7))
            xenrt.TEC().comment("Using maximum VIF count of %u." % (max))

        # Create bridges.
        xenrt.TEC().progress("Creating %s bridges, one for each " \
                             "of the NICs we're testing." % (max))
        for i in range(1, max):
            nwuuid = self.host.createNetwork()
            br = self.host.genParamGet("network", nwuuid, "bridge")
            self.bridges[i] = br
            xenrt.TEC().progress("Created bridge %s." % (br))

        xenrt.TEC().progress("Installing target VM...")
        
        t = self.host.createGenericLinuxGuest(start=False)
        
        t.setMemory(128)
        self.guestsToClean.append(t)
        xenrt.TEC().logverbose("Creating %s NICs on the target VM." % (max))
        for i in range(1, max):
            t.createVIF("%s%d" % (t.vifstem, i), self.bridges[i], xenrt.randomMAC())
            xenrt.TEC().progress("Created %s%d on peer VM %s." % (t.vifstem, i, t.name))
        t.start()

        xenrt.TEC().progress("Adding initial NICs. (%s)" % (initial))
        nics = initial
        for i in range(1, nics):
            g.createVIF("%s%d" % (g.vifstem, i), self.bridges[i], xenrt.randomMAC())
            xenrt.TEC().progress("Created %s%d on test VM %s." %
                                 (g.vifstem, i, g.name))
            self.vifsToRemove.append("%s%d" % (g.vifstem, i))
            if not shutdown:
                g.plugVIF("%s%d" % (g.vifstem, i))
            mac, ip, bridge = g.getVIF("%s%d" % (g.vifstem, i))
            
        use_ipv6 = g.use_ipv6
        ula_prefix = xenrt.getRandomULAPrefix()

        # Loop over the possible NIC values.
        for i in range(0, max):
            xenrt.TEC().progress("Testing with %d NICs." % (nics))

            if shutdown: g.start()
            else: g.checkReachable()

            # Remove any link-local routes (XRT-944).
            if not g.windows:
                try:
                    data = g.execguest("ip route list to root 169.254/16").strip()
                    xenrt.TEC().logverbose("ip route: %s" % (data))
                    if re.search("/16.*dev", data):
                        g.execguest("ip route delete %s" % (data))
                except:
                    pass

            # Prod Windows to sort out any new NICs.
            if g.windows:
                time.sleep(60)
                g.updateVIFDriver()

            
            # Loop over currently installed NICs.
            for j in range(0, nics):

                transmitafter = 0
                transmitbefore = 0
                receiveafter = 0
                receivebefore = 0
                
                xenrt.TEC().logverbose("Testing %s%d." % (g.vifstem, j))
                mac, ip, bridge = g.getVIF("%s%d" % (g.vifstem, j))

                # Assume this one works because we have access to the VM.
                if bridge == mybridge:
                    continue
                
                # Connect up target VM.
                target_ipv6_addr = "%s:%04x::1" % (ula_prefix, (j + 1))
                guest_ipv6_address = "%s:%04x::2" % (ula_prefix, (j + 1))
                
                if use_ipv6:
                    t.execguest('ifconfig %s%d up; exit 0' % (t.vifstem, j))
                    t.execguest('ip -6 addr add %s/64 dev %s%d' % (target_ipv6_addr, t.vifstem, j))
                else:
                    t.configureNetwork(str(j), 
                                       ip="169.254.%d.1" % (j + 1),
                                       netmask="255.255.255.0")
                t.execguest("ifconfig -a")
                t.execguest("route -n")
                
                if "connected" != self.host.xenstoreRead("/local/domain/0/backend/vif/%u/%u/hotplug-status" % (self.host.getDomid(g), j)):
                    raise xenrt.XRTFailure("Xenstore reports VIF %u not connected" % j)
                
                if g.windows:
                    # Check we can't ping target before configuring the
                    # interface. This may help us find packet leaks.
                    xenrt.TEC().logverbose("Trying to ping target before "
                                           "configuring interface.")
                    # TODO
                    g.xmlrpcExec("ipconfig /all", returndata=True)
                    g.xmlrpcExec("route PRINT", returndata=True)
                    if use_ipv6:
                        data = g.xmlrpcExec("ping %s" % target_ipv6_addr,
                                            timeout=60,
                                            returndata=True,
                                            returnerror=False)
                    else:
                        data = g.xmlrpcExec("ping 169.254.%d.1" % (j + 1),
                                        timeout=60,
                                        returndata=True,
                                        returnerror=False)
                    # Windows Server 2008 has buggy reporting for
                    # host unreachable so we do some dodgy parsing instead.
                    if re.search("Reply from .* TTL=", data):
                        xenrt.TEC().warning("Could ping target without "
                                            "configuring interface.")
                    elif re.search("100% loss", data):
                        pass
                    elif re.search("Destination host unreachable", data):
                        pass
                    else:
                        xenrt.TEC().warning("Could not parse ping data for "
                                            "packet leak check.")
                    # TODO

                    # Get ipconfig data.
                    g.xmlrpcExec("ipconfig /all", returndata=True)
                    
                    interface = g.getWindowsInterface(str(j))
                    xenrt.TEC().progress("Testing %s." % (interface))
                    xenrt.TEC().logverbose("Configuring interface.")
                    
                    if use_ipv6:
                        g.xmlrpcExec('netsh int ipv6 set address interface="%s" address="%s" store=persistent' 
                                     % (interface, guest_ipv6_address))
                    else:
                        g.configureNetwork(str(j), ip="169.254.%s.2" % (j+1), 
                                           netmask="255.255.255.0",
                                           gateway="169.254.%s.1" % (j+1),
                                           metric="100")
                    time.sleep(60)

                    try:
                        xenrt.TEC().logverbose("Checking packet counts before ping.")
                        transmitbefore, receivebefore = g.getPacketCount(j)
                    except:
                        pass
                    
                    time.sleep(30)

                    # TODO
                    g.xmlrpcExec("ipconfig /all", returndata=True)
                    g.xmlrpcExec("route PRINT", returndata=True)
                    xenrt.TEC().logverbose("Pinging target.")
                    if use_ipv6:
                        data = g.xmlrpcExec("ping %s" % target_ipv6_addr,
                                            timeout=60,
                                            returndata=True,
                                            returnerror=False)
                    else:
                        data = g.xmlrpcExec("ping 169.254.%d.1" % (j + 1),
                                            timeout=60,
                                            returndata=True,
                                            returnerror=False)

                    if not re.search("\(0% loss\)", data):
                        raise xenrt.XRTFailure("Pinging target failed.")
                    if re.search("Destination host unreachable", data):
                        raise xenrt.XRTFailure("Pinging target failed.")
                    # TODO

                    try:
                        xenrt.TEC().logverbose("Checking packet counts after ping.")
                        transmitafter, receiveafter = g.getPacketCount(j)
                        if (transmitafter) <= (transmitbefore) or \
                           (receiveafter) <= (receivebefore):
                            xenrt.TEC().warning("Saw no traffic on interface.")
                    except:
                        pass

                    if use_ipv6:
                        xenrt.TEC().logverbose("Deleting the IPv6 address from the interface.")
                        g.xmlrpcExec('netsh int ipv6 delete address interface="%s" address="%s"' 
                                     % (interface, guest_ipv6_address))

                    else:
                        xenrt.TEC().logverbose("Reconfiguring interface to another network.")
                        g.configureNetwork(str(j), ip="192.168.%d.2" % (j+1), 
                                           netmask="255.255.255.0",
                                           gateway="192.168.%d.1" % (j+1),
                                           metric="100")
                else:

                    if use_ipv6:
                        g.execguest('ifconfig %s%d up; exit 0' % (g.vifstem, j))
                        g.execguest('ip -6 addr add %s/64 dev %s%d' % (guest_ipv6_address, g.vifstem, j))
                    else:
                        g.configureNetwork(j,
                                           ip="169.254.%d.2" % (j + 1),
                                           netmask="255.255.255.0")
                    g.execguest("ifconfig -a")
                    g.execguest("route -n")

                    try:
                        xenrt.TEC().logverbose("Checking packet counts before ping.")
                        transmitbefore, receivebefore = g.getPacketCount(j)
                    except:
                        pass

                    if use_ipv6:
                        g.execguest("ping6 -c 10 %s" % target_ipv6_addr)
                    else:
                        g.execguest("ping -c 10 169.254.%d.1" % (j + 1))

                    try:
                        xenrt.TEC().logverbose("Checking packet counts after ping.")
                        transmitafter, receiveafter = g.getPacketCount(j)
                    except:
                        pass

                    if (transmitafter) <= (transmitbefore) or \
                       (receiveafter) <= (receivebefore):
                        xenrt.TEC().warning("Saw no traffic on interface.")
                    
                    if use_ipv6:
                        xenrt.TEC().logverbose("Deleting the IPv6 address from the test VM.")
                        g.execguest('ip -6 addr del %s/64 dev %s%d' % (guest_ipv6_address, g.vifstem, j))

                if use_ipv6:
                    xenrt.TEC().logverbose("Deleting the IPv6 address from the %s%d on target VM" % (t.vifstem, j))
                    t.execguest('ip -6 addr del %s/64 dev %s%d' % (target_ipv6_addr, t.vifstem, j))
                    
            if shutdown:
                g.shutdown()
            
            # Move to the next number of NICs.
            nics = (nics + 1) % max
            if nics == 0: nics = max
            xenrt.TEC().logverbose("Moving to %s NIC(s)." % (nics))

            vifs = g.getVIFs()
            xenrt.TEC().logverbose("Found %s NIC(s)." % (len(vifs)))
            if len(vifs) == nics: return
            elif len(vifs) > nics:
                xenrt.TEC().logverbose("Removing %s NIC(s)." % (len(vifs) - nics))
                for i in range(len(vifs) - nics):
                    eth = "%s%d" % (g.vifstem, (len(vifs) - (i + 1)))
                    if not shutdown: g.unplugVIF(eth)
                    g.removeVIF(eth)
            elif len(vifs) < nics:
                xenrt.TEC().logverbose("Adding %s NIC(s)." % (nics - len(vifs)))
                for i in range(nics - len(vifs)):
                    eth = "%s%d" % (g.vifstem, len(vifs) + i)
                    g.createVIF(eth, self.bridges[len(vifs)], xenrt.randomMAC())
                    xenrt.TEC().logverbose("Created %s%d on %s." % (g.vifstem, len(vifs) + i, g.name))
                    self.vifsToRemove.append(eth)
                    if not shutdown: g.plugVIF(eth)
                    mac, ip, bridge = g.getVIF(eth)
 
    def postRun(self):
        for g in self.guestsToShutdown:
            try:
                if g.getState() == "UP":
                    g.shutdown()
            except:
                pass
            xenrt.TEC().logverbose("Removing VIFs: %s" % (self.vifsToRemove))
            for v in self.vifsToRemove:
                try:
                    xenrt.TEC().logverbose("Removing %s." % (v))
                    g.removeVIF(v)
                except:
                    pass
        xenrt.TEC().logverbose("Guests to be cleaned: %s" % ([ x.name for x in self.guestsToClean ]))
        for g in self.guestsToClean:
            try:
                g.shutdown(again=True)
            except:
                pass
            try:
                g.poll("DOWN", 120, level=xenrt.RC_ERROR)
                g.uninstall()
                time.sleep(15)
            except:
                pass
        for b in self.bridges.values():
            try:
                self.host.removeNetwork(b)
            except:
                pass

class TCVLANSetup(xenrt.TestCase):

    def __init__(self, tcid="TCVLANSetup"):
        xenrt.TestCase.__init__(self, tcid)
        self.vlans = []
        self.guestsToClean = []
        
    def createVBridgeVLAN(self, vlan):
        nic = self.host.getDefaultInterface()
        bridge = "vbridge%u" % (vlan)
        desc = "VLAN%u bridge" % (vlan)
        if not vlan in self.vlans:
            self.vlans.append(vlan)
        self.host.createVBridge(bridge, vlan=vlan, nic=nic, desc=desc)
        self.host.checkVBridge(bridge, vlan=vlan, nic=nic, desc=desc)

    def createVBridge(self, idx):
        nic = self.host.getDefaultInterface()
        bridge = "vbridge%u" % (idx)
        desc = "vbridge %u" % (idx)
        self.host.createVBridge(bridge, nic=nic, desc=desc)
        self.host.checkVBridge(bridge, nic=nic, desc=desc)        

    def removeVBridgeVLAN(self, vlan):
        nic = self.host.getDefaultInterface()
        bridge = "vbridge%u" % (vlan)
        self.host.removeVBridge(bridge)
        brs = self.host.getVBridges()
        if brs.has_key(bridge):
            raise xenrt.XRTFailure("Bridge %s exists after removal" % (bridge))
        ifs = self.host.getBridgeInterfaces(bridge)
        if ifs:
            raise xenrt.XRTFailure("Host bridge %s exists after removal" %
                                   (bridge))
        try:
            vlanif = "%s.%u" % (nic, vlan)
            self.host.execdom0("ifconfig %s" % (vlanif))
            raise xenrt.XRTFailure("Interface %s exists after bridge removal" %
                                   (vlanif))
        except:
            pass

    def removeVBridge(self, idx):
        nic = self.host.getDefaultInterface()
        bridge = "vbridge%u" % (idx)
        self.host.removeVBridge(bridge)
        brs = self.host.getVBridges()
        if brs.has_key(bridge):
            raise xenrt.XRTFailure("Bridge %s exists after removal" % (bridge))
        ifs = self.host.getBridgeInterfaces(bridge)
        if ifs:
            raise xenrt.XRTFailure("Host bridge %s exists after removal" %
                                   (bridge))
        
    def run(self, arglist=None):
        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]

        self.host = xenrt.TEC().registry.hostGet(machine)
        if not self.host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(self.host)

        self.runSubcase("createVBridgeVLAN", (5), "vbridge_create", "VLAN5")
        self.runSubcase("createVBridgeVLAN", (50), "vbridge_create", "VLAN50")
        v1024 = self.runSubcase("createVBridgeVLAN", (1024),
                                "vbridge_create", "VLAN1024")
        self.runSubcase("createVBridgeVLAN", (4011),
                        "vbridge_create", "VLAN4011")
        if v1024 == xenrt.RESULT_PASS:
            self.runSubcase("removeVBridgeVLAN", (1024),
                            "vbridge_remove", "VLAN1024")
        else:
            self.declareTestcase("vbridge_remove", "VLAN1024")

    def postRun(self):
        for g in self.guestsToClean:
            try:
                g.shutdown(force=True)
            except:
                pass
            try:
                g.poll("DOWN", 120, level=xenrt.RC_ERROR)
                g.uninstall()
                time.sleep(15)
            except:
                pass
        if self.host:
            for vlan in self.vlans:
                try:
                    self.removeVBridge(vlan)
                except:
                    pass

class TCRioVLANSetup(TCVLANSetup):

    def __init__(self):
        TCVLANSetup.__init__(self, "TCRioVLANSetup")

    def createVBridgeVLAN(self, vlan):
        if not vlan in self.vlans:
            self.vlans.append(vlan)
        nic = self.host.getDefaultInterface()
        bridge = self.host.createNetwork()
        self.host.createVLAN(vlan, bridge, nic) 
        self.host.checkVLAN(vlan, nic)

    def removeVBridgeVLAN(self, vlan):
        self.host.removeVLAN(vlan)
    
    def postRun(self):
        for g in self.guestsToClean:
            try:
                g.shutdown(force=True)
            except:
                pass
            try:
                g.poll("DOWN", 120, level=xenrt.RC_ERROR)
                g.uninstall()
                time.sleep(15)
            except:
                pass
        if self.host:
            for vlan in self.vlans:
                try:
                    self.removeVBridgeVLAN(vlan)
                except:
                    pass

class TCRioVLANTraffic(TCRioVLANSetup):
    
    def __init__(self):
        TCVLANSetup.__init__(self, "TCRioVLANTraffic")
        self.peer = None
   
    def createGuest(self, vlan):
        g = self.host.createGenericLinuxGuest(name="vlanGuest%u" % (vlan))
        self.guestsToClean.append(g)

        # Disable a whole bunch of stuff on the guest so it doesn't get
        # too upset when we start it on a 169.254 address.
        g.execguest("rm -f /etc/init.d/exim4")
        g.execguest("echo 'UseDNS no' >> /etc/ssh/sshd_config")

        # Tweak the network config.
        subnet = xenrt.PrivateSubnet(2)
        cfg = """auto eth0 lo

iface lo inet loopback

iface eth0 inet static
    address %s
    network %s
    netmask %s
    broadcast %s
    gateway %s
""" % (subnet.getAddress(2),
       subnet.getSubnet(),
       subnet.getMask(),
       subnet.getBroadcast(),
       subnet.getAddress(1))
        fn = xenrt.TEC().tempFile()
        f = file(fn, "w")
        f.write(cfg)
        f.close()
        sftp = g.sftpClient()
        sftp.copyTo(fn, "/etc/network/interfaces")

        # Shut down and move to the VLAN bridge.
        g.shutdown()
        mac, ip, bridge = g.getVIF("eth0")
        
        nwuuid = self.host.minimalList("pif-list", 
                                       "network-uuid", 
                                       "VLAN=%s" % (vlan))[0]
        bridge = self.host.genParamGet("network",
                                        nwuuid,
                                       "bridge")
        g.removeVIF("eth0")
        g.createVIF("eth0", bridge, mac)

        # Create an interface on the peer and start our guest
        self.peer.createVLANInterface(vlan, subnet, 1)
        xenrt.TEC().progress("Starting guest VM %s" % (g.name))
        g.lifecycleOperation("vm-start")

        # Wait for the VM to come up.
        xenrt.TEC().progress("Waiting for the VM to enter the UP state")
        g.poll("UP", pollperiod=5)

        # On the peer check the guest is pingable.
        time.sleep(120)
        try:
            self.peer.runCommand("ping -c 3 -w 10 %s" %
                                (subnet.getAddress(2)))
        except:
            raise xenrt.XRTFailure("Guest not pingable across the VLAN")

        # Shut down the guest
        g.shutdown()
    
    def run(self, arglist=None):
        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]

        self.host = xenrt.TEC().registry.hostGet(machine)
        if not self.host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(self.host)

        vlans = xenrt.TEC().lookup("TEST_VLANS", None)
        if not vlans:
            xenrt.TEC().skip("No VLANs defined in config.")
            return

        vlans = map(int, vlans.split(","))
        self.peer = xenrt.VLANPeer()

        # Create some VLANs
        for v in vlans:
            self.createVBridgeVLAN(v)

        # For each VLAN create a guest to use that VLAN
        for v in vlans:
            self.runSubcase("createGuest", (v), "vlan_guest", "VLAN%u" % (v))

    def postRun(self):
        try:
            TCRioVLANSetup.postRun(self)
        finally:
            if self.peer:
                self.peer.cleanup()
                self.peer.release()

class TCVLANTraffic(TCVLANSetup):

    """Tests that VLANs work properly and traffic goes out on the correct
    VLAN.

    We must have a host that is on the network in such a way that all VLAN
    tagged packets between the test host and this peer will get through
    with the tags intact.

    On the peer we create/check an interface of eth0.<vlan>.

    We create guests on the default VLAN so they get DHCP addresses so we
    we can get in to them. We then log in and edit their network configs
    to give them static 169.254 addresses. The guest is then shut down,
    put on the VLAN bridge, then started.
    """

    def __init__(self):
        TCVLANSetup.__init__(self, "TCVLANTraffic")
        self.peer = None
        self.host = None

    def createGuest(self, vlan):
        # Install Debian
        g = self.host.createGenericLinuxGuest(name="vlanGuest%u" % (vlan))
        self.guestsToClean.append(g)

        # Disable a whole bunch of stuff on the guest so it doesn't get
        # too upset when we start it on a 169.254 address
        g.execguest("rm -f /etc/init.d/exim4")
        g.execguest("echo 'UseDNS no' >> /etc/ssh/sshd_config")

        # Tweak the network config
        subnet = xenrt.PrivateSubnet(2)
        cfg = """auto eth0 lo

iface lo inet loopback

iface eth0 inet static
    address %s
    network %s
    netmask %s
    broadcast %s
    gateway %s
""" % (subnet.getAddress(2),
       subnet.getSubnet(),
       subnet.getMask(),
       subnet.getBroadcast(),
       subnet.getAddress(1))
        fn = xenrt.TEC().tempFile()
        f = file(fn, "w")
        f.write(cfg)
        f.close()
        sftp = g.sftpClient()
        sftp.copyTo(fn, "/etc/network/interfaces")

        # Shut down and move to the VLAN bridge
        g.shutdown()
        cli = self.host.getCLIInstance()
        eth, bridge, mac, ip = g.vifs[0]
        cli.execute("vm-vif-remove", "vm-name=%s vif-name=%s" % (g.name, eth))
        vbridge = "vbridge%u" % (vlan)
        cli.execute("vm-vif-add",
                    "vm-name=%s vif-name=%s mac=%s bridge-name=%s" %
                    (g.name, eth, mac, vbridge))

        # Create an interface on the peer and start our guest
        self.peer.createVLANInterface(vlan, subnet, 1)
        cli.execute("vm-start", "vm-name=%s" % (g.name))
        g.poll("UP", 180)

        # On the peer check the guest is pingable
        time.sleep(120)
        try:
            self.peer.runCommand("ping -c 3 -w 10 %s" %
                                  (subnet.getAddress(2)))
        except:
            raise xenrt.XRTFailure("Guest not pingable across the VLAN")
        
        # Shut down the guest
        g.shutdown()

    def run(self, arglist=None):
        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]

        self.host = xenrt.TEC().registry.hostGet(machine)
        if not self.host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(self.host)

        # VLANs are based on offsets from a multiple of 256 to allow
        # our 169.254 address allocation plan to work
        vlans = [5, 50, 1024, 4011]
        self.peer = xenrt.VLANPeer()

        # Create some VLANs
        for v in vlans:
            self.createVBridgeVLAN(v)

        # For each VLAN create a guest to use that VLAN
        for v in vlans:
            self.runSubcase("createGuest", (v), "vlan_guest", "VLAN%u" % (v))

    def postRun(self):
        try:
            TCVLANSetup.postRun(self)
        finally:
            if self.peer:
                self.peer.cleanup()
                self.peer.release()


class TCChangeNIC(xenrt.TestCase):

    def __init__(self, tcid="TCChangeNIC"):
        xenrt.TestCase.__init__(self, tcid)

    def changeVIF(self, live):
        raise xenrt.XRTError("Not implemented.")

    def run(self, arglist=None):
        
        shutdown = True
        guestname = None
        machine = "RESOURCE_HOST_0"

        if arglist and len(arglist) > 0:
            machine = arglist[0]
        for arg in arglist[1:]:
            l = string.split(arg, "=", 1)
            if l[0] == "noshutdown":
                shutdown = False
            elif l[0] == "guest":
                guestname = l[1] 
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]

        # Use an existing guest.
        g = self.getGuest(guestname)
        self.guest = g
        self.host = g.host
        self.getLogsFrom(self.host)
        cli = self.host.getCLIInstance()

        if shutdown:
            # Make sure the guest is down.
            if g.getState() == "UP":
                xenrt.TEC().logverbose("Shutting down guest before "
                                       "commencing test.")
                g.shutdown()
        else:
            # Make sure the guest is up.
            if g.getState() == "DOWN":
                xenrt.TEC().logverbose("Starting guest before commencing "
                                       "test.")
                g.start()

        self.changeVIF(not shutdown)

class TCAddNIC(TCChangeNIC):

    def __init__(self, tcid="TCAddNIC"):
        xenrt.TestCase.__init__(self, tcid)

    def changeVIF(self, live):
        data = self.host.minimalList("vif-list", 
                                     "device", 
                                     "vm-uuid=%s" % 
                                        (self.guest.getUUID()))
        if data == []:
            eth = '0'
        else:
            eth = str(max(map(int, data)) + 1)
        # Get the bridge the VM is using
        xmac, xip, mybridge = self.guest.getVIF("%s0" % (self.guest.vifstem))
        xenrt.TEC().logverbose("Using primary bridge %s" % (mybridge))
        self.guest.createVIF(eth, mybridge, xenrt.randomMAC())             
        if live:
            self.guest.plugVIF(eth)

class TCRemoveNIC(TCChangeNIC):

    def __init__(self, tcid="TCRemoveNIC"):
        xenrt.TestCase.__init__(self, tcid)

    def changeVIF(self, live):
        data = self.host.minimalList("vif-list", 
                                     "device", 
                                     "vm-uuid=%s" % 
                                        (self.guest.getUUID()))
        if data == []:
            raise xenrt.XRTFailure("No VIF to remove.")
        else:
            eth = str(max(map(int, data)))
        if live:
            self.guest.unplugVIF(eth)
        self.guest.removeVIF(eth)

class TCWinWinNetwork(xenrt.TestCase):
    """Interim basic Windows to Windows network connectivity check"""

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCWinWinNetwork")
        self.guestsToClean = []
        
    def run(self, arglist=None):

        gname = None
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]

        if not gname:
            raise xenrt.XRTError("No guest name specified.")
        g = self.getGuest(gname)
        if not g:
            raise xenrt.XRTError("Could not find guest %s in registry" %
                                (gname))
        self.getLogsFrom(g.host)

        try:
            if g.getState() == "UP":
                xenrt.TEC().comment("Shutting down guest %s before commencing "
                                    "clone." % (g.name))
                g.shutdown()

            c = g.cloneVM(xenrt.randomGuestName())
            self.guestsToClean.append(c)

            c.start()
            c.check()
            g.start()
        except xenrt.XRTFailure, e:
            # Anything that breaks here is not a failure of the testcase
            raise xenrt.XRTError(e.reason)

        if not c.xmlrpcCheckOtherDaemon(g.getIP()):
            raise xenrt.XRTFailure("Cannot talk to %s from %s" %
                                   (c.getName(), g.getName()))
        if not g.xmlrpcCheckOtherDaemon(c.getIP()):
            raise xenrt.XRTFailure("Cannot talk to %s from %s" %
                                   (g.getName(), c.getName()))        

    def postRun(self):
        for g in self.guestsToClean:
            try:
                try:
                    g.shutdown(force=True)
                except:
                    pass
                g.poll("DOWN", 120, level=xenrt.RC_ERROR)
                g.uninstall()
            except:
                pass

class TCMultiNIC(xenrt.TestCase):
    """Stress test of multiple physical NICs"""

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCMultiNIC")
        self.guestsToClean = []

    def run(self, arglist=None):
        machine = "RESOURCE_HOST_0"

        if arglist and len(arglist) > 0:
            machine = arglist[0]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry." % 
                                 (machine))
        self.getLogsFrom(host)

        # See how many NICs we have
        pifs = host.minimalList("pif-list")
        pif_count = len(pifs)
        if pif_count < 2:
            xenrt.TEC().skip("Host only has %u NICs, need at least 2" % (pif_count))
            return

        masters = pif_count / 2
        slaves = pif_count - masters

        # Create a VM to clone
        deb = host.createGenericLinuxGuest()
        self.guestsToClean.append(deb)

        # Install netperf
        deb.installNetperf()
        deb.execguest("echo 'netperf 12865/tcp' >> /etc/services")
        deb.preCloneTailor()
        deb.shutdown()
        deb.memset(128)

        # Now clone it pif_count-1 times
        for i in range(pif_count-1):
            self.guestsToClean.append(deb.cloneVM())

        current_nic = 0

        # Set up the masters
        masterGuests = []
        for i in range(masters):
            m = self.guestsToClean[i]
            masterGuests.append(m)
            # Add a VIF on the appropriate NIC
            m.createVIF("eth1","xenbr%u" % (current_nic),None)
            m.start()
            # Configure IP address
            m.configureNetwork("eth1", 
                                ip="169.254.%u.1" % (current_nic), 
                                netmask="255.255.255.0")
            m.MultiNIC = current_nic
            current_nic += 1
            # Set up netperf server
            m.execguest("echo 'netperf stream tcp nowait root "
                        "/usr/local/bin/netserver netserver' >> "
                        "/etc/inetd.conf")
            m.execguest("/etc/init.d/inetd reload")

        # Set up the slaves
        slaveGuests = []
        for i in range(masters,slaves+masters):
            s = self.guestsToClean[i]
            slaveGuests.append(s)
            # Add a VIF on the appropriate NIC
            s.createVIF("eth1","xenbr%u" % (current_nic),None)
            s.MultiNIC = current_nic
            current_nic += 1
            s.start()

        # Allocate slaves to masters round-robin
        currentMaster = 0
        i = 0
        h = 2
        sToM = {}
        while len(sToM) < len(slaveGuests):
            s = slaveGuests[i]
            m = masterGuests[currentMaster]
            sToM[s] = m
            s.configureNetwork("eth1",
                                ip="169.254.%u.%u" % (m.MultiNIC,i+2),
                                netmask="255.255.255.0")
            i += 1
            currentMaster += 1
            if currentMaster == masters:
                currentMaster = 0

        # Run the netperf tests (we start them all at once, and record results later)
        # TCP        
        for s in slaveGuests:
            s.execguest("netperf -H 169.254.%u.1 -t TCP_STREAM -l 300 "
                        "-v 0 -P 0 > /netperf.log 2>/netperf.err &" % (sToM[s].MultiNIC))

        # Wait for completion and parse
        completed = False
        while not completed:
            completed = True
            for s in slaveGuests:
                if re.search("netperf", s.execguest("ps -A")):
                    completed = False
                    break
            time.sleep(30)

        for s in slaveGuests:
            data = s.execguest("cat /netperf.log")
            self.parseResults(data,"TCP",s.MultiNIC,sToM[s].MultiNIC)

        # UDP
        for s in slaveGuests:
            s.execguest("netperf -H 169.254.%u.1 -t UDP_STREAM -l 300 "
                        "-v 0 -P 0 > /netperf.log 2>/netperf.err &" % (sToM[s].MultiNIC))

        # Wait for completion and parse
        completed = False
        while not completed:
            completed = True
            for s in slaveGuests:
                if re.search("netperf", s.execguest("ps -A")):
                    completed = False
                    break
            time.sleep(30)

        for s in slaveGuests:
            data = s.execguest("cat /netperf.log")
            self.parseResults(data,"UDP",s.MultiNIC,sToM[s].MultiNIC)

    def parseResults(self, data, protocol, g1, g2):
        xenrt.TEC().value("%s_%u_%u" % (protocol, g1, g2), self.parseRate(data))

    def parseRate(self, data):
        for line in string.split(data, "\n"):
            if re.search(r"^\s*\d+", line):
                l = string.split(line)
                return float(l[0])
        raise xenrt.XRTError("Could not parse netperf output")

    def postRun(self):
        for g in self.guestsToClean:
            try:
                try:
                    g.shutdown(force=True)
                except:
                    pass
                g.poll("DOWN", 120, level=xenrt.RC_ERROR)
                g.uninstall()
            except:
                pass

class TCloadsim(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCloadsim"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="loadsim")

        self.exchguest = None
        self.lsguest = None
        self.workdirexch = None
        self.workdirls = None
        self.domain = None

    def runViaDaemon(self, remote, arglist):

        # We should be given a guest as an argument in addition to remote
        # remote is the guest we install AD and exchange onto
        # The first argument is the guest we run loadsim on

        # The second (optional) argument is the number of hours to run for
        
        if not arglist or len(arglist) == 0:
            raise xenrt.XRTError("Second guest name not specified.")
        self.lsguest = self.getGuest(arglist[0])
        if not self.lsguest:
            raise xenrt.XRTError("Could not find guest %s in registry" %
                                (arglist[0]))

        if len(arglist) > 1:
            duration = arglist[1]
        else:
            duration = 1

        xenrt.TEC().comment("Run duration %d hour(s)" % (duration))

        self.exchguest = remote
        self.workdirexch = self.exchguest.xmlrpcTempDir()

        # Check lsguest is up (we can assume exchguest is)
        if self.lsguest.getState() != "UP":
            self.lsguest.start()

        # Update lsguest
        self.lsguest.xmlrpcUpdate()
        self.workdirls = self.lsguest.xmlrpcTempDir()

        # Decide on a domain name
        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        self.domain = ""
        for i in range(8):
            self.domain += choice(chars)

        xenrt.TEC().comment("Random domain name: %s" % (self.domain))
               
        # Unpack the tarballs
        self.exchguest.xmlrpcUnpackTarball("%s/loadsim.tgz" %
                                (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                self.workdirexch)
        self.lsguest.xmlrpcUnpackTarball("%s/loadsim.tgz" %
                                (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                self.workdirls)

        # Install exchguest and lsguest
        self.install()

        # Now start the tests!
        # Get the various bits we need...
        adf = ("%s\\loadsim\\adfind.exe -gc -b \"CN=Servers,CN=First Administra"
               "tive Group,CN=Administrative Groups,CN=XenRT,CN=Microsoft Excha"
               "nge,CN=Services,CN=Configuration,DC=%s,DC=testdomain\"" %
              (self.workdirls,self.domain))
        
        client_name = self.lsguest.xmlrpcGetEnvVar("COMPUTERNAME")
        server_name = self.exchguest.xmlrpcGetEnvVar("COMPUTERNAME")
 
        data = self.lsguest.xmlrpcExec("%s -f \"adminDisplayName=%s\" "
                                       "adminDisplayName objectGUID" % (adf, server_name),
                                       returndata=True, timeout=7200)

        datal = data.split("\n")
        for l in datal:
            if l.startswith(">objectGUID: "):
                machine_guid = self.fixGUID(l[13:])
            if l.startswith(">adminDisplayName: "):
                machine_name = l[19:]

        data = self.lsguest.xmlrpcExec("%s -f \"adminDisplayName=First Storage "
                                       "Group\" objectGUID" % (adf), 
                                       returndata=True, timeout=7200)

        datal = data.split("\n")
        for l in datal:
            if l.startswith(">objectGUID: "):
                storage_guid = self.fixGUID(l[13:])

        data = self.lsguest.xmlrpcExec("%s -f \"adminDisplayName=Mailbox Store "
                                       "*\" objectGUID" % (adf),returndata=True, timeout=7200)

        datal = data.split("\n")
        for l in datal:
            if l.startswith(">objectGUID: "):
                mailbox_guid = self.fixGUID(l[13:])

    
        # Load in the template
        template = self.lsguest.xmlrpcReadFile("%s\\loadsim\\template.sim" %
                                               (self.workdirls))
        # Do some replacement
        template = template.replace("%MACHINE_GUID%",machine_guid)
        template = template.replace("%MACHINE_NAME%",machine_name)
        template = template.replace("%STORAGE_GUID%",storage_guid)
        template = template.replace("%MAILBOX_GUID%",mailbox_guid)
        template = template.replace("%CLIENT_NAME%",client_name)
        template = template.replace("%DURATION%",str((duration*3600*1000)))
        template = template.replace("%DOMAIN%",self.domain)

        # Now write the file back
        self.lsguest.xmlrpcWriteFile("%s\\loadsim\\run.sim" %
                                     (self.workdirls),template)

        # Now start the run
        self.lsguest.xmlrpcExec("\"C:\\Program Files\\LoadSim\\loadsim.exe\" "
                                "/f %s\\loadsim\\run.sim /t /x\n"
                                "ping -n 120 127.0.0.1\n"
                                "\"C:\\Program Files\\LoadSim\\loadsim.exe\" "
                                "/f %s\\loadsim\\run.sim /ip /x\n"
                                "\"C:\\Program Files\\LoadSim\\loadsim.exe\" "
                                "/f %s\\loadsim\\run.sim /r /x" %
                                (self.workdirls,self.workdirls,self.workdirls),
                                timeout=(duration*3600)+3600,level=xenrt.RC_OK)

        xenrt.TEC().progress("Completed LoadSim Run")

        # Try and get lsperf.log
        try:
            self.lsguest.xmlrpcGetFile("c:\\docume~1\\admini~1.%s\\"
                                "lsperf.log" % (self.domain[:3]),
                                "%s/lsperf.log" % (xenrt.TEC().getLogdir()))
        except:
            raise xenrt.XRTFailure("lsperf.log not found!")

        # Produce the summary
        summary = self.lsguest.xmlrpcExec("\"C:\\Program Files\\LoadSim\\"
                  "lslog.exe\" answer C:\\docume~1\\admini~1.%s\\lsperf.log" % 
                  (self.domain[:3]),returndata=True,returnerror=False, timeout=3600)

        if not isinstance(summary,str):
            raise xenrt.XRTFailure("Unable to generate summary!")

        # We have a summary - write it out
        f = file("%s/lssummary.log" % (xenrt.TEC().getLogdir()), "w")
        f.write(summary)
        f.close()

        # Now get the mean from it
        summarys = summary.split("\n")
        mean = None
        for l in summarys:
            if l.startswith("Weighted Avg"):
                vals = l.split()
                mean = vals[6]
                xenrt.TEC().value("mean",mean)
                break

        if not mean:
            raise xenrt.XRTFailure("Unable to extract mean from summary!")

    def fixGUID(self,orig):
        # Strip out -'s
        orig = orig.replace("-","")

        # Fix layout (believed to be due to endianness)
        fixed = orig[:9]
        fixed += orig[13:17]
        fixed += orig[9:13]
        fixed += orig[23:25]
        fixed += orig[21:23]
        fixed += orig[19:21]
        fixed += orig[17:19]
        fixed += orig[31:33]
        fixed += orig[29:31]
        fixed += orig[27:29]
        fixed += orig[25:27]
        fixed += "}"

        return fixed
               
    def install(self):

        exchguest = self.exchguest
        lsguest = self.lsguest

        # AD onto exchguest
        exchguest.winRegAdd("HKLM",
                            "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\"
                            "Winlogon",
                            "DefaultDomainName",
                            "SZ",
                            self.domain)
        # Make sure the windows CD is in
        exchguest.changeCD("%s.iso" % (exchguest.distro))

        # This gets slightly tricky, we need to give the guest a static IP
        # (as otherwise it complains during AD install), then change it back
        # to dynamic afterwards. For now, use the guest's dynamic IP, and hope
        # the lease is long enough that it won't get reassigned!
    
        # Get the current IP and subnetmask (this is a bit nasty...)
        # We could use getIP, but to make sure we get the IP that corresponds
        # to the subnet mask, use the same method for both
        ipc = exchguest.xmlrpcExec("ipconfig",returndata=True)    
        ipcs = ipc.split("\n")
        ip = ipcs[9][39:]
        snm = ipcs[10][39:]
        dg = ipcs[11][39:]

        # Get current DNS server
        data = exchguest.xmlrpcExec("netsh interface ip show dns",
                                    returndata=True)
        datal = data.split("\n")
        dns = datal[4][42:]

        # Edit dcinstall-auto.txt to replace %DOMAIN%
        dca = exchguest.xmlrpcReadFile("%s\\loadsim\\dcinstall-auto.txt" %
                                       (self.workdirexch))
        dca = dca.replace("%DOMAIN%",self.domain)
        dca = dca.replace("%PASSWORD%",
                          xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS",
                                              "ADMINISTRATOR_PASSWORD"]))
        exchguest.xmlrpcWriteFile("%s\\loadsim\\dcinstall-auto.txt" %
                                  (self.workdirexch), dca)
       
        # Local Area Connection 2 as we assume PV drivers have been installed
        exchguest.xmlrpcStart("ping -n 15 127.0.0.1\n"
                              "netsh interface ip set address \"Local Area "
                              "Connection 2\" static %s %s %s 1\n"
                              "netsh interface ip set dns \"Local Area Connection "
                              "2\" static %s\n"
                              "cd %s\\loadsim\n"
                              "dcpromo /answer:dcinstall-auto.txt" % 
                              (ip,snm,dg,dns,self.workdirexch))

        # Loadsim onto lsguest
        lsguest.xmlrpcStart("cd %s\\loadsim\n"
                            "msiexec.exe /package loadsim.msi /passive" % 
                            (self.workdirls))

        # Now wait for exchguest to reboot
        exchguest.waitToReboot(timeout=3600)

        exchguest.waitForDaemon(300,desc="Waiting for boot after AD install")

        # Return it to DHCP
        exchguest.xmlrpcStart("ping -n 15 127.0.0.1\n"
                              "netsh interface ip set address \"Local Area "
                              "Connection 2\" dhcp")

        time.sleep(30)

        exchguest.waitForDaemon(60,desc="Waiting for guest to return to DHCP")

        # Turn off firewall
        exchguest.xmlrpcExec("netsh firewall set opmode DISABLE")

        # Install support tools
        exchguest.xmlrpcExec("msiexec /package "
                             "d:\\support\\tools\\suptools.msi /passive", timeout=3600)

        # Specify DNS server to forward queries to
        dnscmd = "\"C:\\Program Files\\Support Tools\\dnscmd.exe\""
        exchguest.xmlrpcExec("%s /ResetForwarders %s\n"
                             "%s /ClearCache" % (dnscmd,dns,dnscmd), timeout=3600)

        # Now point lsguest at exchguest's DNS server
        lsguest.xmlrpcExec("netsh interface ip set dns \"Local Area Connection "
                           "2\" static %s" % (ip))
        # Join lsguest to the domain (we hope this finishes before exchange
        # reboots the DC!)
        lsguest.xmlrpcExec("Cscript.exe //Nologo "
                           "%s\\loadsim\\joindomain.vbs %s %s" % 
                           (self.workdirls,
                            self.domain,
                            xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS",
                                                "ADMINISTRATOR_PASSWORD"])),
                           timeout=3600)
        lsguest.winRegAdd("HKLM",
                          "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\"
                          "Winlogon",
                          "DefaultDomainName",
                          "SZ",
                          self.domain)
        lsguest.winRegAdd("HKLM",
                          "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\"
                          "Winlogon",
                          "DefaultPassword",
                          "SZ",
                          "%s" % (xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS",
                                                      "ADMINISTRATOR_PASSWORD"])))
        # Put in a registry key to disable the firewall
        lsguest.winRegAdd("HKLM",
                          "SOFTWARE\\Policies\\Microsoft\\WindowsFirewall\\"
                          "DomainProfile",
                          "EnableFirewall",
                          "DWORD",
                          0)
        lsguest.xmlrpcReboot()

        # Now install IIS
        exchguest.xmlrpcExec("sysocmgr /i:%%windir%%\\inf\\sysoc.inf "
                             "/u:%s\\loadsim\\iisinstall.txt" % 
                             (self.workdirexch), timeout=3600)

        # Now install Exchange
        # Change CD
        exchguest.changeCD("exchange.iso")
        # Disable app compatibility checking
        exchguest.winRegAdd("HKLM",
                            "SOFTWARE\\Policies\\Microsoft\\windows\\AppCompat",
                            "DisableEngine",
                            "DWORD",
                            1)
        # Wait 30 seconds for the CD to actually get through
        time.sleep(30)
        # Edit exchangeinstall.txt to replace %DOMAIN%
        exi = exchguest.xmlrpcReadFile("%s\\loadsim\\exchangeinstall.txt" %
                                       (self.workdirexch))
        exi = exi.replace("%DOMAIN%",self.domain)
        exchguest.xmlrpcWriteFile("%s\\loadsim\\exchangeinstall.txt" %
                                  (self.workdirexch), exi)

        exchguest.xmlrpcStart("D:\\setup\\i386\\setup.exe /UnattendFile "
                              "%s\\loadsim\\exchangeinstall.txt" % 
                              (self.workdirexch))
        # Start the watcher
        exchguest.xmlrpcStart("c:\\soon.exe 120 "
                              "%s\\loadsim\\checkfinished.bat %s\\loadsim "
                              "SETUP.EXE %s %s" %
                              (self.workdirexch,
                               self.workdirexch,
                               self.domain,
                               xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS",
                                                   "ADMINISTRATOR_PASSWORD"])))

        # Check in case lsguest hasn't finished rebooting
        lsguest.waitForDaemon(300,
                              desc="Waiting for boot after joining domain")

        # Install outlook onto lsguest
        lsguest.changeCD("outlook.iso")
        # Wait 30 seconds for the CD to actually get through
        time.sleep(30)
        # Start the install
        lsguest.xmlrpcStart("msiexec /package d:\\OUTLS11.msi /passive")

        # Now wait for exchguest to reboot
        exchguest.waitToReboot(timeout=3600)

        exchguest.waitForDaemon(300,
                                desc="Waiting for boot after Exchange install")

        # Exchange updates
        exchguest.changeCD("exchange_update.iso")
        time.sleep(30)
        # Edit exchangeupdate.txt to replace %DOMAIN%
        exu = exchguest.xmlrpcReadFile("%s\\loadsim\\exchangeupdate.txt" %
                                       (self.workdirexch))
        exu = exu.replace("%DOMAIN%",self.domain)
        exchguest.xmlrpcWriteFile("%s\\loadsim\\exchangeupdate.txt" %
                                  (self.workdirexch), exu)

        exchguest.xmlrpcStart("D:\\i386\\update.exe /UnattendFile "
                             "%s\\loadsim\\exchangeupdate.txt" % 
                             (self.workdirexch))
        # Start the watcher
        exchguest.xmlrpcStart("c:\\soon.exe 120 "
                              "%s\\loadsim\\checkfinished.bat %s\\loadsim "
                              "UPDATE.EXE %s %s" %
                              (self.workdirexch,
                               self.workdirexch,
                               self.domain,
                               xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS",
                                                   "ADMINISTRATOR_PASSWORD"])))

        # Now wait for exchguest to reboot

        exchguest.waitToReboot(timeout=3600)

        exchguest.waitForDaemon(300,
                                desc="Waiting for boot after Exchange update")

        xenrt.TEC().progress("Completed Installation Phase")
 
