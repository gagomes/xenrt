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

        for t in [("Power", "IPMI"), ("Power", "PDU")]:
            self.runSubcase("test_%s_%s" % (t[0],t[1]), (), t[0], t[1])
            self.host.waitForSSH(600, desc="Boot after %s/%s test" % (t[0],t[1]))

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

    def test_Power_IPMI(self):
        powerctl = self.host.machine.powerctl
        if isinstance(powerctl, xenrt.powerctl.IPMIWithPDUFallback):
            powerctl = powerctl.ipmi
        
        if not isinstance(powerctl, xenrt.powerctl.IPMI):
            raise xenrt.XRTSkip("No IPMI support found")
            return

        self._testPowerctl(powerctl)

    def test_Power_PDU(self):
        lock = xenrt.resources.CentralResource(timeout=1200)
        powerctl = self.host.machine.powerctl
        if isinstance(powerctl, xenrt.powerctl.IPMIWithPDUFallback):
            powerctl = powerctl.pdu
        
        if not isinstance(powerctl, xenrt.powerctl.PDU):
            raise xenrt.XRTSkip("No PDU support found")
            return

        self._testPowerctl(powerctl)

