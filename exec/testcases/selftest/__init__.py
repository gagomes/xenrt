#
# XenRT: Test harness for Xen and the XenServer product family
#
# Test the test harness and infrastructure
#
# Copyright (c) Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import sys, re, string, os.path, urllib, traceback, time, xml.dom.minidom
import xenrt, xenrt.lib.xenserver

class TCNICCheck(xenrt.TestCase):
    """Check each physical NIC received the expected DHCP address."""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.vlans = self.host.availableVLANs()

    def doNIC(self, id):
        # Get our local device name for this NIC
        device = self.host.getSecondaryNIC(id)
        mac = self.host.getNICMACAddress(id)
        ip = None
        netmask = None
        try:
            ip, netmask, gateway = self.host.getNICAllocatedIPAddress(id)
        except:
            # If it's not configured we'll not worry about it now
            pass
        pif = self.host.getNICPIF(id)
        
        # Make sure the NIC is not currently configured with IP
        mode = self.host.genParamGet("pif", pif, "IP-configuration-mode")
        if mode != "None":
            raise xenrt.XRTError("PIF already has configuration '%s'" % (mode))
        
        # Enable DHCP on this NIC
        try:
            newip = self.host.setIPAddressOnSecondaryInterface(id)

            if ip:
                # Check the IP address we got matches the static config
                if ip != newip:
                    raise xenrt.XRTFailure("DHCP IP does not match config",
                                           "got %s, expected %s" % (newip, ip))
            else:
                # Check the IP address we got is in the correct subnet for
                # the network this NIC is on
                subnet, netmask = self.host.getNICNetworkAndMask(id)
                if not xenrt.util.isAddressInSubnet(newip, subnet, netmask):
                    raise xenrt.XRTFailure("DHCP IP not in expected subnet",
                                           "%s not in %s/%s" %
                                           (newip, subnet, netmask))
            # Check the netmask
            newnetmask = self.host.genParamGet("pif", pif, "netmask")
            if newnetmask != netmask:
                raise xenrt.XRTFailure("DHCP netmask does not match config",
                                       "got %s, expected %s" %
                                       (newnetmask, netmask))
        finally:
            # Deconfigure IP on this NIC
            try:
                self.host.removeIPAddressFromSecondaryInterface(id)
            except:
                pass

    def doVLANonNIC(self, nicid, vlan, subnet, netmask):
        device = self.host.getSecondaryNIC(nicid)
        pif = self.host.getNICPIF(nicid)
        
        # Ensure this VLAN on this NIC does not already exist
        vlans = self.host.minimalList("vlan-list",
                                      "tag",
                                      "tagged-PIF=%s" % (pif))
        if str(vlan) in vlans:
            raise xenrt.XRTError("VLAN %u already exists on %s" %
                                 (vlan, device))

        nwuuid = None
        vlanpif = None
        ip = None

        try:
            # Create a VLAN on this physical interface
            nwuuid = self.host.createNetwork("%s.%u network" % (device, vlan))
            vlanpif = self.host.createVLAN(vlan, nwuuid, device, pif)

            # Enable DHCP on this NIC
            ip = self.host.enableIPOnPIF(vlanpif)
        
            # Check the IP address we got is in the correct subnet for the VLAN
            if not xenrt.util.isAddressInSubnet(ip, subnet, netmask):
                raise xenrt.XRTFailure("DHCP IP not in expected subnet",
                                       "%s not in %s/%s" % (ip, subnet, netmask))

            # Check the netmask
            newnetmask = self.host.genParamGet("pif", vlanpif, "netmask")
            if newnetmask != netmask:
                raise xenrt.XRTFailure("DHCP netmask does not match config",
                                       "got %s, expected %s" %
                                       (newnetmask, netmask))
        finally:
            # Deconfigure IP on the VLAN
            if ip:
                try:
                    self.host.removeIPFromPIF(vlanpif)
                except Exception, e:
                    xenrt.TEC().warning("Exception removing IP from PIF: %s" %
                                        (str(e)))
                    
            # Remove the VLAN
            if vlanpif:
                try:
                    self.host.removeVLAN(vlan)
                except Exception, e:
                    xenrt.TEC().warning("Exception removing VLAN: %s" %
                                        (str(e)))
            if nwuuid:
                try:
                    self.host.removeNetwork(nwuuid=nwuuid)
                except Exception, e:
                    xenrt.TEC().warning("Exception removing network: %s" %
                                        (str(e)))

    def run(self, arglist):
        ids = filter(lambda x:self.host.getNICNetworkName(x) != "none",
                     self.host.listSecondaryNICs())
        if len(ids) == 0:
            self.tec.skip("No secondary NICs to check")
            return

        xenrt.TEC().logverbose("Checking NICs: %s" % (str(ids)))
        for id in ids:
            self.runSubcase("doNIC", (id), "NIC", str(id))
            for vlanspec in self.vlans:
                vlan, subnet, netmask = vlanspec
                self.runSubcase("doVLANonNIC",
                                (id, vlan, subnet, netmask),
                                "NIC%u" % (id),
                                "VLAN%u" % (vlan))

class TCMachineCheck(xenrt.TestCase):
    """Verify machine connectivity - tests power, network, FC, serial"""

    def run(self, arglist):
        self.host = self.getDefaultHost()

        if arglist:
            tests = map(lambda t: t.split("/", 1), arglist)
        else:
            tests = [("Power", "IPMI"), ("Power", "PDU"), ("Network", "Ports"), ("Network", "DHCP")]

        for t in tests:
            self.runSubcase("test%s%s" % (t[0],t[1]), (), t[0], t[1])
            self.host.waitForEnabled(600, desc="Boot after %s/%s test" % (t[0],t[1]))

    def _testPowerctl(self, powerctl):
        lock = xenrt.resources.CentralResource(timeout=1200)
        lock.acquire("MC_POWER")
        try:
            if not self.host.checkAlive():
                raise xenrt.XRTError("Host not reachable prior to powering down via IPMI")
            powerctl.off()
            xenrt.sleep(10)
            if self.host.checkAlive():
                raise xenrt.XRTFailure("Host reachable after powering down via IPMI")
        finally:
            powerctl.on()
            lock.release()

    def testPowerIPMI(self):
        """Verify the host IPMI is functional"""
        powerctl = self.host.machine.powerctl
        if isinstance(powerctl, xenrt.powerctl.IPMIWithPDUFallback):
            powerctl = powerctl.ipmi
        
        if not isinstance(powerctl, xenrt.powerctl.IPMI):
            raise xenrt.XRTSkip("No IPMI support found")
            return

        self._testPowerctl(powerctl)

    def testPowerPDU(self):
        """Verify the host is on the correct PDU port (either as primary or fallback)"""
        powerctl = self.host.machine.powerctl
        if isinstance(powerctl, xenrt.powerctl.IPMIWithPDUFallback):
            powerctl = powerctl.pdu
        
        if not isinstance(powerctl, xenrt.powerctl.PDU):
            raise xenrt.XRTSkip("No PDU support found")
            return

        self._testPowerctl(powerctl)

    def _lookupMac(self, assumedId):
        mac = self.host.lookup(["NICS", "NIC%u" % (assumedId), "MAC_ADDRESS"], None)
        if not mac:
            raise xenrt.XRTError("MAC not specified for NIC%u" % (assumedId))
        return xenrt.util.normaliseMAC(mac)

    def _checkNIC(self, dev):
        return self.host.execdom0("cat /sys/class/net/%s/carrier" % (dev)).strip() == "1"

    def testNetworkPorts(self):
        """Verify each NIC is connected to the correct switch port"""
        nics = self.host.listSecondaryNICs()
        nicMacs = dict([(assumedId, self._lookupMac(assumedId)) for assumedId in nics])
        nicDevs = dict([(assumedId, self.host.getSecondaryNIC(assumedId)) for assumedId in nics]) # getSecondaryNIC checks the MAC is on the PIF implicitly

        lock = xenrt.resources.CentralResource(timeout=1200)
        powerLock = xenrt.resources.CentralResource(timeout=1200)
        lock.acquire("MC_NETWORK")
        try:
            self.host.enableAllNetPorts()
            xenrt.sleep(30)
            for assumedId in nics:
                mac = nicMacs[assumedId]
                dev = nicDevs[assumedId]
                # Check link state before
                if not self._checkNIC(dev):
                    raise xenrt.XRTFailure("Link for NIC %u (%s / %s) down before bringing port down" % (assumedId, mac, dev))
                self.host.disableNetPort(mac)
                xenrt.sleep(20)
                if self._checkNIC(dev):
                    raise xenrt.XRTFailure("Link for NIC %u (%s / %s) up after bringing port down" % (assumedId, mac, dev))

            # Now check the primary NIC
            powerLock.acquire("MC_POWER") # We have to take this one as well to avoid confusion with a power test
            try:
                if not self.host.checkAlive():
                    raise xenrt.XRTError("Host not reachable prior to disabling primary NIC")
                self.host.disableNetPort(xenrt.normaliseMAC(self.host.lookup("MAC_ADDRESS")))
                xenrt.sleep(20)
                if self.host.checkAlive():
                    raise xenrt.XRTFailure("Host reachable after disabling primary NIC")
            finally:
                powerLock.release()
        finally:
            self.host.enableAllNetPorts()
            lock.release()

    def testNetworkDHCP(self):
        """Verify the host gets the correct DHCP address on each NIC"""
        # Primary NIC is implicitly verified, so we only test secondary NICs here
        nics = self.host.listSecondaryNICs()
        cli = self.host.getCLIInstance()
        missingIPConfigs = []
        for assumedId in nics:
            pif = self.host.getNICPIF(assumedId)
            cli.execute("pif-reconfigure-ip", "uuid=%s mode=dhcp" % pif)

            # Validate it has the expected config
            try:
                expectedIp, expectedNetmask, expectedGateway = self.host.getNICAllocatedIPAddress(assumedId)
                xenrt.TEC().logverbose("For NIC %u expecting %s/%s (GW %s)" % (assumedId, expectedIp, expectedNetmask, expectedGateway))
            except xenrt.XRTError:
                xenrt.TEC().warning("NIC %u has no assigned IP" % assumedId)
                expectedIp = None
                missingIPConfigs.append(str(assumedId))
            actualIp = self.host.genParamGet("pif", pif, "IP")
            actualNetmask = self.host.genParamGet("pif", pif, "netmask")
            actualGateway = self.host.genParamGet("pif", pif, "gateway")
            xenrt.TEC().logverbose("Found %s/%s (GW %s)" % (actualIp, actualNetmask, actualGateway))
            failures = []
            if expectedIp is None:
                # Determine if IP is in the expected subnet
                nw = self.host.lookup(["NICS", "NIC%u" % (assumedId), "NETWORK"], None)
                if not nw:
                    raise xenrt.XRTError("NETWORK not specified for NIC %u" % assumedId)
                nwMaps = {"NPRI": "DEFAULT", "NSEC": "SECONDARY", "IPRI": "VLANS/IPRI"}
                if not nw in nwMaps.keys():
                    raise xenrt.XRTError("Unknown NETWORK %s" % nw)
                confKey = ["NETWORK_CONFIG"] + nwMaps[nw].split("/")
                expectedSubnet = self.host.lookup(confKey + ["SUBNET"])
                expectedNetmask = self.host.lookup(confKey + ["SUBNETMASK"])
                expectedGateway = self.host.lookup(confKey + ["GATEWAY"])
                if not isAddressInSubnet(actualIp, expectedSubnet, expectedNetmask):
                    failures.append("IP not in correct subnet")
            else:
                if actualIp != expectedIp:
                    failures.append("IP not as expected")

            if actualNetmask != expectedNetmask:
                failures.append("Netmask not as expected")
            if actualGateway != expectedGateway:
                failures.append("Gateway not as expected")
            if len(failures) > 0:
                raise xenrt.XRTFailure("Incorrect DHCP response for NIC %u: %s" % (assumedId, ", ".join(failures)))
            cli.execute("pif-reconfigure-ip", "uuid=%s mode=none" % pif)

        if len(missingIPConfigs) > 0:
            raise xenrt.XRTPartial("Missing IP configs for NICs %s" % (",".join(missingIPConfigs)))

