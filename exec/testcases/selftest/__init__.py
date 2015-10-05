#
# XenRT: Test harness for Xen and the XenServer product family
#
# Test the test harness and infrastructure
#
# Copyright (c) Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import sys, re, string, os.path, urllib, traceback, time, xml.dom.minidom, uuid
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
        if not self.host:
            m = xenrt.PhysicalHost(xenrt.TEC().lookup("RESOURCE_HOST_0"))
            self.host = xenrt.lib.xenserver.host.DundeeHost(m)
            self.host.findPassword()

        if arglist:
            tests = map(lambda t: t.split("/", 1), arglist)
        else:
            tests = [("Console", "Serial"), ("Power", "IPMI"), ("Power", "PDU"), ("Network", "Ports"), ("Network", "DHCP"), ("FC", "HBA")]

        for t in tests:
            self.runSubcase("test%s%s" % (t[0],t[1]), (), t[0], t[1])
            self.host.waitForEnabled(1800, desc="Boot after %s/%s test" % (t[0],t[1]))

    def _testPowerctl(self, powerctl):
        lock = xenrt.resources.CentralLock("MC_POWER", timeout=3600)
        try:
            if not self.host.checkAlive():
                raise xenrt.XRTError("Host not reachable prior to powering down")
            powerctl.off()
            xenrt.sleep(20)
            if self.host.checkAlive():
                raise xenrt.XRTFailure("Host reachable after powering down")
        finally:
            powerctl.on()
            xenrt.sleep(60)
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
            powerctl = powerctl.PDU
        
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

    def _checkNICLink(self, dev):
        speed = int(self.host.execdom0("cat /sys/class/net/%s/speed" % (dev)).strip())
        duplex = self.host.execdom0("cat /sys/class/net/%s/duplex" % (dev)).strip()
        xenrt.TEC().logverbose("%s is %s/%s" % (dev, speed, duplex))
        if speed < 1000 or duplex != "full":
            return "%s reports %s/%s, expecting at least 1000/full" % (dev, speed, duplex)

    def testNetworkPorts(self):
        """Verify each NIC is connected to the correct switch port"""
        nics = self.host.listSecondaryNICs()
        nicMacs = dict([(assumedId, self._lookupMac(assumedId)) for assumedId in nics])
        nicDevs = dict([(assumedId, self.host.getSecondaryNIC(assumedId)) for assumedId in nics]) # getSecondaryNIC checks the MAC is on the PIF implicitly

        failures = []

        lock = xenrt.resources.CentralLock("MC_NETWORK", timeout=3600)
        powerLock = xenrt.resources.CentralLock("MC_POWER", timeout=3600, acquire=False)
        try:
            self.host.enableAllNetPorts()
            xenrt.sleep(30)
            for assumedId in nics:
                mac = nicMacs[assumedId]
                dev = nicDevs[assumedId]
                # Check link state before
                if not self._checkNIC(dev):
                    failures.append("Link for NIC %u (%s / %s) down before bringing port down" % (assumedId, mac, dev))
                    continue
                # Check link speed / duplex
                link = self._checkNICLink(dev)
                if link:
                    failures.append(link)
                    
                self.host.disableNetPort(mac)
                xenrt.sleep(20)
                if self._checkNIC(dev):
                    failures.append("Link for NIC %u (%s / %s) up after bringing port down" % (assumedId, mac, dev))
                    self.host.enableNetPort(mac) # Re-enable it in case it's a different port on this host
                    xenrt.sleep(20)

            # Now check the primary NIC
            powerLock.acquire() # We have to take this one as well to avoid confusion with a power test
            try:
                if not self.host.checkAlive():
                    raise xenrt.XRTError("Host not reachable prior to disabling primary NIC")
                self.host.disableNetPort(xenrt.normaliseMAC(self.host.lookup("MAC_ADDRESS")))
                xenrt.sleep(20)
                if self.host.checkAlive():
                    failures.append("Host reachable after disabling primary NIC")
            finally:
                powerLock.release()
        finally:
            self.host.enableAllNetPorts()
            lock.release()

        if len(failures) > 0:
            for f in failures:
                xenrt.TEC().logverbose(f)
            raise xenrt.XRTFailure("Network port failures detected")

    def testNetworkDHCP(self):
        """Verify the host gets the correct DHCP address on each NIC"""
        # Primary NIC is implicitly verified, so we only test secondary NICs here
        nics = self.host.listSecondaryNICs()
        cli = self.host.getCLIInstance()
        missingIPConfigs = []
        overallFailures = []
        for assumedId in nics:
            pif = self.host.getNICPIF(assumedId)
            cli.execute("pif-reconfigure-ip", "uuid=%s mode=dhcp" % pif)

            # Validate it has the expected config
            try:
                expectedIp, expectedNetmask, _ = self.host.getNICAllocatedIPAddress(assumedId)
                xenrt.TEC().logverbose("For NIC %u expecting %s/%s" % (assumedId, expectedIp, expectedNetmask))
            except xenrt.XRTError:
                xenrt.TEC().warning("NIC %u has no assigned IP" % assumedId)
                expectedIp = None
                missingIPConfigs.append(str(assumedId))
            actualIp = self.host.genParamGet("pif", pif, "IP")
            actualNetmask = self.host.genParamGet("pif", pif, "netmask")
            if actualIp == "" or actualNetmask == "":
                overallFailures.append("No IP received on NIC %u" % assumedId)
                continue
            xenrt.TEC().logverbose("Found %s/%s" % (actualIp, actualNetmask))
            failures = []
            if expectedIp is None:
                # Determine if IP is in the expected subnet
                nw = self.host.lookup(["NICS", "NIC%u" % (assumedId), "NETWORK"], None)
                if not nw:
                    raise xenrt.XRTError("NETWORK not specified for NIC %u" % assumedId)
                nwMaps = {"NPRI": "DEFAULT", "NSEC": "SECONDARY", "IPRI": "VLANS/IPRI", "ISEC": "VLANS/ISEC"}
                if not nw in nwMaps.keys():
                    raise xenrt.XRTError("Unknown NETWORK %s" % nw)
                confKey = ["NETWORK_CONFIG"] + nwMaps[nw].split("/")
                expectedSubnet = self.host.lookup(confKey + ["SUBNET"])
                expectedNetmask = self.host.lookup(confKey + ["SUBNETMASK"])
                if not xenrt.util.isAddressInSubnet(actualIp, expectedSubnet, expectedNetmask):
                    failures.append("IP not in correct subnet")
            else:
                if actualIp != expectedIp:
                    failures.append("IP not as expected")

            if actualNetmask != expectedNetmask:
                failures.append("Netmask not as expected")
            if len(failures) > 0:
                overallFailures.append("Incorrect DHCP response for NIC %u: %s" % (assumedId, ", ".join(failures)))
            cli.execute("pif-reconfigure-ip", "uuid=%s mode=none" % pif)

        if len(overallFailures) > 0:
            for f in overallFailures:
                xenrt.TEC().logverbose(f)
            raise xenrt.XRTFailure("Network DHCP failures detected")

        if len(missingIPConfigs) > 0:
            raise xenrt.XRTPartial("Missing IP configs for NICs %s" % (",".join(missingIPConfigs)))

    def testConsoleSerial(self):
        """Verify we have serial console"""
        randomString = str(uuid.uuid4())
        self.host.execdom0("echo %s > /dev/console" % randomString)
        xenrt.sleep(10)

        serlog = string.join(self.host.machine.getConsoleLogHistory()[-20:], "\n")
        if randomString in serlog:
            xenrt.TEC().logverbose("Found string in console log - serial console functional")
        else:
            xenrt.TEC().logverbose("Serial log output...")
            xenrt.TEC().logverbose(serlog)
            xenrt.TEC().logverbose("...done")
            raise xenrt.XRTFailure("Cannot find string in console log - serial console non functional")

    def _getHBACounts(self):
        devices = self.host.execdom0("ls /sys/class/fc_host").splitlines()
        onlineDevices = 0
        for d in devices:
            if self.host.execdom0("cat /sys/class/fc_host/%s/port_state" % d).strip() == "Online":
                onlineDevices += 1
        return (onlineDevices, len(devices))

    def testFCHBA(self):
        """Verify FC HBAs are connected correctly"""

        # Do we have any HBAs we can control?
        fc = self.host.lookup("FC", {})
        hbas = []
        for k in fc:
            m = re.match("CMD_HBA(\d)_ENABLE", k)
            if m:
                hbas.append(int(m.group(1)))

        if len(hbas) == 0:
            raise xenrt.XRTSkip("No HBAs found with port control commands")

        # Check we've got the expected number of online devices at this point
        online, total = self._getHBACounts()

        if total < len(hbas):
            raise xenrt.XRTError("Found insufficient sysfs devices", data="%d HBAs, %d sysfs devices" % (len(hbas), total))

        total = len(hbas) # Ignore extra HBAs that may not be connected etc

        if online != total:
            raise xenrt.XRTFailure("Only found %d/%d HBAs online prior to test" % (online, total))

        lock = xenrt.resources.CentralLock("MC_FC", timeout=1200)
        try:
            for i in range(len(hbas)):
                hba = hbas[i]

                # Drop it
                self.host.disableFCPort(hba)
                xenrt.sleep(20)
                online, _ = self._getHBACounts()
                if online != (total - 1):
                    raise xenrt.XRTFailure("No change in online HBA count after bringing path down")
                # Re-enable so if we're booted from multipath SAN we don't end up dropping both paths
                self.host.enableFCPort(hba)
                xenrt.sleep(20)
                online, _ = self._getHBACounts()
                if online != total:
                    raise xenrt.XRTFailure("Link not recovered after bringing path back up")
        finally:
            self.host.enableAllFCPorts()
            lock.release()


