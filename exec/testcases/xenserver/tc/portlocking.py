import math, threading, re, time, string, subprocess, os, random
import xenrt, xenrt.networkutils
from xenrt.lazylog import step, comment, log, warning

class InstallCSP(xenrt.TestCase):

    def run(self, arglist):
        tempDir = xenrt.TEC().tempDir()
        tgzFile = xenrt.TEC().getFile(xenrt.TEC().lookup("CSP_LOCATION"))
        xenrt.archive.TarGzArchiver().extractTo(tgzFile, tempDir)

        for h in self.getAllHosts():
            filename = "xenserver-cloud-supp.iso"
            local = "/root/%s" % filename
            
            sftp = h.sftpClient()
            try:
                sftp.copyTo("%s/%s" % (tempDir, filename), local)
            finally:
                sftp.close()
            
            h.execdom0("xe-install-supplemental-pack %s" % local)
            h.reboot()

class PortLock(xenrt.TestCase):
    
    def execMulti(self,  host,  multi,  targetFileName):
        """Run multiple commands from a shell script to ensure the firewall/routing is not temporarily in an inconsistent state"""
        
        xenrt.TEC().logverbose("Running commands:\n" + "\n".join(multi))

        dir = xenrt.TEC().tempDir()
        tempFile = dir+"/" + targetFileName
        f = open(tempFile,  "w")
        f.write("\n".join(multi))
        f.close()
        
        sftp = host.sftpClient()
        try:
            sftp.copyTo(tempFile,  "/root/%s"%targetFileName)
        finally:
            sftp.close()
        
        host.execdom0("chmod +x /root/%s"%targetFileName)
        
        return host.execdom0("/root/%s"%targetFileName)

    def prepare(self,  arglist):
        
        self.host = self.getHost("RESOURCE_HOST_0")
        self.host2 = self.getHost("RESOURCE_HOST_1")
        
        # First, look for our linux guests...
        self.linux_guest_1 = None
        self.linux_guest_2 = None
        guestList = self.host.listGuests(True)
        for guest in guestList:
            g = self.host.getGuest(guest)
            if (g.distro == "etch"):
                if (self.linux_guest_1 is None):
                    self.linux_guest_1 = g
                elif (self.linux_guest_2 is None):
                    self.linux_guest_2 = g
    
        # Install two guests (if we don't have them already)
        if (self.linux_guest_1 is None):
            self.linux_guest_1 = self.host.createGenericLinuxGuest()
            self.uninstallOnCleanup(self.linux_guest_1)
            self.getLogsFrom(self.linux_guest_1)
        
        if (self.linux_guest_2 is None):
            self.linux_guest_2 = self.host.createGenericLinuxGuest()
            self.uninstallOnCleanup(self.linux_guest_2)
            self.getLogsFrom(self.linux_guest_2)
        
    def checkKernLogForId(self, id, allowed):
        resp = self.host.execdom0('cat /var/log/kern.log | grep "%s" || true' % id)
        
        if allowed:
            xenrt.TEC().logverbose("Checking that %s is in /var/log/kern.log" % id)
            if not id in resp:
                raise xenrt.XRTFailure("Could not find %s in /var/log/kern.log" % id)
        else:
            xenrt.TEC().logverbose("Checking that %s can't be found in /var/log/kern.log" % id)
            if id in resp:
                raise xenrt.XRTFailure("Found %s in /var/log/kern.log" % id)
    
    def run(self,  arglist):
        raise xenrt.XRTError("Run must be over-ridden from %s"%self.__class__)

class BackendSwitcher(PortLock):

    def getNetworkBackend(self):
        return self.getDefaultHost().execdom0("cat /etc/xensource/network.conf").strip()
    
    def prepare(self, arglist):
        
        self.host = self.getHost("RESOURCE_HOST_0")
        self.host2 = self.getHost("RESOURCE_HOST_1")

        if (self.getNetworkBackend()  == "bridge"):
            xenrt.TEC().logverbose("Using bridge backend")
            self._use_bridge = True
        else:
            xenrt.TEC().logverbose("Using vSwitch backend")
            self._use_bridge = False

        # this needs to be done for Tampa and later
        if self._use_bridge and isinstance(self.host, xenrt.lib.xenserver.TampaHost):
            self.host.execdom0("sysctl -w net.bridge.bridge-nf-call-iptables=1")
            self.host.execdom0("sysctl -w net.bridge.bridge-nf-call-arptables=1")
        
        # must call this before creating VMs to unblock DHCP
        self.clearAllRules()
        
        PortLock.prepare(self, arglist)

    def resetHostRules(self, host):
        if (self._use_bridge):
            self.bridgeResetHostRules(host)
        else:
            self.vswitchResetHostRules(host)

    def clearAllRules(self):
        if (self._use_bridge):
            self.bridgeClearAllRules()
    
    def clearRules(self, bridge, vifName):
        if (self._use_bridge):
            self.bridgeClearRules(bridge, vifName)
        else:
            self.vswitchClearRules(bridge, vifName)

    def addIPv4LockRules(self, bridge, vifName, mac, ipv4):
        if (self._use_bridge):
            self.bridgeAddIPv4LockRules(bridge, vifName, mac, ipv4)
        else:
            self.vswitchAddIPv4LockRules(bridge, vifName, mac, ipv4)

    def vswitchResetHostRules(self,  host):
        # Reset each bridge
        brs = host.execdom0('ovs-vsctl list-br').split('\n')
        multi=['#!/bin/sh']
        multi.append('set -e')
        for bridge in brs[:-1]:
            multi.append('network_uuid=`xe network-list bridge=%s minimal=true`'%bridge)
            multi.append('pif=`xe pif-list network-uuid=$network_uuid params=device minimal=true`')
            multi.append('ofport=`ovs-vsctl get Interface $pif ofport`')
            multi.append('ovs-ofctl del-flows %s'%bridge)
            multi.append('ovs-ofctl add-flow %s priority=1,actions=normal'%bridge)
        self.execMulti(host,  multi,  "portlocking_reset_rules.sh")
    
    def vswitchClearRules(self, bridge, vifName):
        multi=['#!/bin/sh']
        multi.append('set -e')
        multi.append('ofport=`ovs-vsctl get Interface %s ofport`'%vifName)
        multi.append('ovs-ofctl del-flows %s in_port=$ofport'%bridge)
        multi.append('ovs-ofctl add-flow %s priority=10$ofport,in_port=$ofport,actions=normal'%bridge)
        self.execMulti(self.host,  multi,  "portlocking_unlock.sh")
        
    def vswitchAddIPv4LockRules(self, bridge, vifName, mac, ipv4):
        multi=['#!/bin/sh']
        multi.append('set -e')
        multi.append('ofport=`ovs-vsctl get Interface %s ofport`'%vifName)
        multi.append('ovs-ofctl del-flows %s in_port=$ofport'%bridge)
        
        # allow valid ARP outbound (both request / reply)
        multi.append('ovs-ofctl add-flow %s priority=10$ofport,in_port=$ofport,dl_src=%s,arp,arp_sha=%s,nw_src=%s,actions=normal'%(bridge, mac, mac, ipv4))
        multi.append('ovs-ofctl add-flow %s priority=10$ofport,in_port=$ofport,dl_src=%s,arp,arp_sha=%s,nw_src=0.0.0.0,actions=normal'%(bridge, mac, mac))
        # allow valid IPv4 outbound
        multi.append('ovs-ofctl add-flow %s priority=10$ofport,in_port=$ofport,dl_src=%s,ip,nw_src=%s,actions=normal'%(bridge, mac, ipv4))
        multi.append('ovs-ofctl add-flow %s priority=10$ofport,in_port=$ofport,dl_src=%s,arp,arp_sha=%s,nw_src=%s,actions=normal'%(bridge, mac, mac, ipv4))
        # Drop the rest coming from the VM
        multi.append('ovs-ofctl add-flow %s priority=1$ofport,in_port=$ofport,actions=drop'%bridge)

        self.execMulti(self.host,  multi,  "portlocking_lock_ipv4.sh")

    def bridgeResetHostRules(self,  host):
        # Reset each bridge
        pifs = host.execdom0('xe pif-list params=device minimal=true')[:-1].split(',')
        multi=['#!/bin/sh']
        multi.append('set -e')
        multi.append('iptables -F')
        multi.append('iptables -X')
        multi.append('iptables -P FORWARD ACCEPT')
        multi.append('arptables -F')
        multi.append('arptables -X')
        multi.append('arptables -P FORWARD ACCEPT')
        multi.append('ebtables -F')
        multi.append('ebtables -X')
        multi.append('ebtables -P FORWARD ACCEPT')
        for pif in pifs:
            multi.append('ebtables -I FORWARD -o %s -j ACCEPT'%pif)
            multi.append('iptables -I FORWARD -m physdev --physdev-in %s -j ACCEPT'%pif)
            
            multi.append('arptables -I FORWARD --opcode Request --in-interface %s -j ACCEPT'%pif)
            multi.append('arptables -I FORWARD --opcode Reply --in-interface %s -j ACCEPT'%pif)
        
        self.execMulti(host,  multi,  "portlocking_reset_rules.sh")
        
    def bridgeClearRules(self, bridge, vifName):
        multi=['#!/bin/sh']
        multi.append('set -e')
        ruleName = "forward_%s"%vifName
        multi.append("iptables_rule=`iptables -L FORWARD --line-numbers | grep %s | cut -d' ' -f 1`"%ruleName)
        multi.append('if [ -n "$iptables_rule" ]; then')
        multi.append('  iptables -D FORWARD $iptables_rule')
        multi.append('  iptables -F %s'%ruleName)
        multi.append('  iptables -X %s'%ruleName)
        multi.append('fi')
        
        multi.append("ebtables_rule=`ebtables -L FORWARD --Ln | grep %s | cut -d' ' -f 1 | tr -d '.'`"%ruleName)
        multi.append('if [ -n "$ebtables_rule" ]; then')
        multi.append('  ebtables -D FORWARD $ebtables_rule')
        multi.append('  ebtables -F %s'%ruleName)
        multi.append('  ebtables -X %s'%ruleName)
        multi.append("  ebtables_rule=`ebtables -L FORWARD --Ln | grep -- \"-i %s\" | cut -d' ' -f 1 | tr -d '.'`"%vifName)
        multi.append('  ebtables -D FORWARD $ebtables_rule')
        multi.append('fi')
        
        multi.append("arptables_rule=`arptables -L FORWARD --line-numbers | grep %s | cut -d' ' -f 1`"%ruleName)
        multi.append('if [ -n "$arptables_rule" ]; then')
        multi.append('  arptables -D FORWARD $arptables_rule')
        multi.append('  arptables -F %s'%ruleName)
        multi.append('  arptables -X %s'%ruleName)
        multi.append('fi')
        
        self.execMulti(self.host,  multi,  "portlocking_unlock.sh")
        
    def bridgeClearAllRules(self):
        multi=['#!/bin/sh']
        multi.append('set -e')
        multi.append('ipset -F')
        multi.append('ipset -X')
        multi.append('iptables -F')
        multi.append('iptables -X')
        multi.append('arptables -F')
        multi.append('arptables -X')
        multi.append('ebtables -F')
        multi.append('ebtables -X')
        
        # self.host might not have been set yet.
        host = getattr(self, 'host', self.getDefaultHost())
        
        self.execMulti(host, multi,  "portlocking_reset_rules.sh")
    
    def bridgeAddIPv4LockRules(self, bridge, vifName, mac, ipv4):
        self.clearRules(bridge, vifName)
        multi=['#!/bin/sh']
        multi.append('set -e')
        ruleName = "forward_%s"%vifName
        multi.append('iptables -N %s'%ruleName)
        multi.append('iptables -A FORWARD -m physdev --physdev-in %s -j %s'%(vifName, ruleName))
        multi.append('iptables -A %s -s %s -j ACCEPT'%(ruleName, ipv4))
        multi.append('iptables -A %s -j DROP'%ruleName)
        
        multi.append('arptables -N %s'%ruleName)
        multi.append('arptables -A FORWARD --in-interface %s -j %s'%(vifName, ruleName))
        
        multi.append('arptables -A %s --opcode Request --source-ip %s -j ACCEPT'%(ruleName, ipv4))
        multi.append('arptables -A %s --opcode Reply --source-ip %s --source-mac %s -j ACCEPT'%(ruleName, ipv4, mac))
        multi.append('arptables -A %s -j DROP'%ruleName)

        multi.append('ebtables -N %s'%ruleName)
        multi.append('ebtables -A FORWARD -j %s'%(ruleName))
        multi.append('ebtables -A %s -p ARP -o %s --arp-ip-dst %s -j ACCEPT'%(ruleName, vifName, ipv4))
        multi.append('ebtables -A %s -p IPv4 -o %s --ip-dst %s -j ACCEPT'%(ruleName, vifName, ipv4))
        multi.append('ebtables -A %s -p ARP -o %s -j DROP'%(ruleName, vifName))
        multi.append('ebtables -A %s -p IPv4 -o %s -j DROP'%(ruleName, vifName))
        
        multi.append('ebtables -I FORWARD 1 -s ! %s -i %s -j DROP'%(mac, vifName))
        self.execMulti(self.host,  multi,  "portlocking_lock_ipv4.sh")

class FalseMacIPTest(BackendSwitcher):
    def run(self,  arglist):
        vifDefn = self.linux_guest_1.vifs[0]
        pif, bridge, mac, ipv4 = vifDefn
        # Using only vif in this domain
        vifName='vif%s.%s'%(self.linux_guest_1.getDomid(), 0)
        ipv4 = self.linux_guest_1.getIP()
        xenrt.TEC().logverbose("vifName: %s / vifDef: %s --> IP: %s"%(vifName, vifDefn, ipv4))

        if (ipv4 is None or mac is None):
            raise xenrt.XRTFailure("Guest must have a MAC and IP address!")

        # Default is to not have any access at all; so must allow IPv4 
        self.clearRules(bridge, vifName)
        # Check that we have guest access
        xenrt.TEC().logverbose("Checking can access guest with no rules set")
        self.linux_guest_1.checkNetwork()
        
        # Check the wrong MAC - the VM should not be accessible
        self.addIPv4LockRules(bridge, vifName, 'AA:AA:AA:AA:AA:AA', ipv4)
        failed = False
        try:
            xenrt.TEC().logverbose("Checking cannot access guest with wrong MAC but right IP set")
            self.linux_guest_1.checkNetwork()
            failed = True
        except xenrt.XRTFailure, e:
            pass
        if (failed):
            raise xenrt.XRTFailure("Guest should not have been reachable with wrong MAC")

        # Lock with correct IPv4 rules - should be accessible
        self.addIPv4LockRules(bridge, vifName, mac, ipv4)
        xenrt.TEC().logverbose("Checking can access guest with right MAC and right IP")
        self.linux_guest_1.checkNetwork()
        
        # Check the wrong IP - the VM should not be accessible
        self.addIPv4LockRules(bridge, vifName, mac, "127.255.1.1")
        failed = False
        try:
            xenrt.TEC().logverbose("Checking cannot access guest with right MAC and wrong IP set")
            self.linux_guest_1.checkNetwork()
            failed = True
        except xenrt.XRTFailure, e:
            pass
        if (failed):
            raise xenrt.XRTFailure("Guest should not have been reachable with wrong IP")

class IPTablesInputTest(BackendSwitcher):

    def prepare(self, arglist):
        if self.getNetworkBackend() == "bridge":
            BackendSwitcher.prepare(self, arglist)
    
    def run(self, arglist):
        if self.getNetworkBackend() != "bridge":
            xenrt.TEC().skip("N/A for vswitch")
        else:
            (pif, bridge, mac, ipv4) = self.linux_guest_1.vifs[0]
            vifName='vif%s.%s'%(self.linux_guest_1.getDomid(), 0)
            
            id = "IPTablesInputTest"
            self.clearAllRules()
            
            # log packets coming into dom0 from VM1
            self.host.execdom0("iptables -A INPUT -m physdev --physdev-in %s -s %s -j LOG --log-prefix '%s'" % (vifName, self.linux_guest_1.getIP(), id))
            
            # check that pinging dom0 from the guest gets logged
            self.linux_guest_1.execguest("ping %s -c 5" % self.host.getIP())
            self.checkKernLogForId(id, True)
            
            # now clear the rules and check the logging stops
            self.host.execdom0("iptables -F")
            time.sleep(10)
            self.host.execdom0('echo "" > /var/log/kern.log')
            self.linux_guest_1.execguest("ping %s -c 5" % self.host.getIP())
            self.checkKernLogForId(id, False)

class IPTablesForwardTest(BackendSwitcher):
    
    def prepare(self, arglist):
        if self.getNetworkBackend() == "bridge":
            BackendSwitcher.prepare(self, arglist)
    
    def run(self,  arglist):
        if self.getNetworkBackend() != "bridge":
            xenrt.TEC().skip("N/A for vswitch")
        else:
            (pif, bridge, mac, ipv4) = self.linux_guest_1.vifs[0]
            vifName='vif%s.%s'%(self.linux_guest_1.getDomid(), 0)
            
            id = "IPTablesForwardTest"
            self.clearAllRules()
            
            # log packets being forwarded on to VM1
            self.host.execdom0("iptables -A FORWARD -m physdev --physdev-in %s -j LOG --log-prefix '%s'" % (vifName, id))
            
            # check that SSHing to the VM from the controller gets logged
            self.linux_guest_1.execguest("ls")
            self.checkKernLogForId(id, True)
            
            # now clear the rules and check that the logging stops
            self.host.execdom0("iptables -F")
            time.sleep(10)
            self.host.execdom0('echo "" > /var/log/kern.log')
            self.linux_guest_1.execguest("ls")
            self.checkKernLogForId(id, False)

class IPTablesOutputTest(BackendSwitcher):
    
    def prepare(self, arglist):
        if self.getNetworkBackend() == "bridge":
            BackendSwitcher.prepare(self, arglist)
    
    def run(self,  arglist):
        if self.getNetworkBackend() != "bridge":
            xenrt.TEC().skip("N/A for vswitch")
        else:
            xrtcontroller = xenrt.TEC().lookup("XENRT_SERVER_ADDRESS")
            
            id = "IPTablesOutputTest"
            self.clearAllRules()
            
            # log packets coming out of dom0 to the controller
            self.host.execdom0("iptables -A OUTPUT -m physdev ! --physdev-is-bridged -d %s -j LOG --log-prefix '%s'" % (xrtcontroller, id))
            
            # chat that pinging the xrt controller from dom0 gets logged
            self.host.execdom0("ping %s -c 5" % xrtcontroller)
            self.checkKernLogForId(id, True)
            
            # now clear the rules and check nothing is logged
            self.host.execdom0("iptables -F")
            time.sleep(10)
            self.host.execdom0('echo "" > /var/log/kern.log')
            self.host.execdom0("ping %s -c 5" % xrtcontroller)
            self.checkKernLogForId(id, False)

class IPSetTest(BackendSwitcher):
    
    def prepare(self, arglist):
        if self.getNetworkBackend() == "bridge":
            BackendSwitcher.prepare(self, arglist)
    
    def run(self,  arglist):
        if self.getNetworkBackend() != "bridge":
            xenrt.TEC().skip("N/A for vswitch")
        else:
            (pif, bridge, mac, ipv4) = self.linux_guest_1.vifs[0]
            vifName='vif%s.%s'%(self.linux_guest_1.getDomid(), 0)
            
            self.clearAllRules()
            id = "IPSetTest"
            
            # create ip-set with VM's IP
            # log packets being forwarded to the VM
            multi=['#!/bin/sh']
            multi.append('set -e')
            multi.append("ipset -N test1 iphash")
            multi.append("ipset -A test1 %s" % self.linux_guest_1.getIP())
            multi.append("iptables -A FORWARD -m set --set test1 src -j LOG --log-prefix '%s'" % id)
            self.execMulti(self.host,  multi,  "portlocking_lock_ipv4.sh")
            
            # ping VM from controller and check it gets logged.
            self.linux_guest_1.execguest("ls")
            self.checkKernLogForId(id, True)
            
            # now clear the rules and check nothing is logged
            self.host.execdom0("iptables -F")
            time.sleep(10)
            self.host.execdom0('echo "" > /var/log/kern.log')
            self.linux_guest_1.execguest("ls")
            self.checkKernLogForId(id, False)

class IPSetNameLengthTest(BackendSwitcher):
    
    VALID_NAME =    "abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijk"   # this string is 63 chars (not too long)
    INVALID_NAME =  "abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijkl"  # this string is 64 chars (too long)
    ERROR_MESSAGE = "63 char"
    
    DUNDEE_VALID_NAME =    "abcdefghijklmnopqrstuvwxyzabcde"   # this string is 31 chars (not too long)
    DUNDEE_INVALID_NAME =  "abcdefghijklmnopqrstuvwxyzabcdef"  # this string is 32 chars (too long)
    DUNDEE_ERROR_MESSAGE = "31 char"
    
    # CP-7155 - on Dundee onwards, we only expect 31 character names to work (31 rather than 32 as the last byte is the null byte)
    def testForDundeeOrCreedence(self, host):     
        if isinstance(host, xenrt.lib.xenserver.DundeeHost) or isinstance(host, xenrt.lib.xenserver.CreedenceHost):
            step("Testing on an Dundee/post Dundee host with 32 and 31 character strings - CP-7155.")
            self.VALID_NAME = self.DUNDEE_VALID_NAME
            self.INVALID_NAME = self.DUNDEE_INVALID_NAME  
            self.ERROR_MESSAGE = self.DUNDEE_ERROR_MESSAGE            
        else:
            step("Testing on a pre Dundee host with 64 and 63 character strings. - CP-7155")            
    
    def prepare(self, arglist):
        if self.getNetworkBackend() == "bridge":
            BackendSwitcher.prepare(self, arglist)
    
    def run(self, arglist):        
        if self.getNetworkBackend() != "bridge":
            xenrt.TEC().skip("N/A for vswitch")
            return
            
        self.clearAllRules()
            
        # check if the test is being carried out on a Dundee/post Dundee host - CP-7155
        self.testForDundeeOrCreedence(self.host)   
            
        step("Testing with an invalid name \"%s\" of length %d." % (self.INVALID_NAME, len(self.INVALID_NAME)))     
        try:
            self.host.execdom0("ipset -N %s iphash" % self.INVALID_NAME)
        except xenrt.XRTFailure, e:
            if not self.ERROR_MESSAGE in e.data:
                raise xenrt.XRTFailure("ipset succedded with a %d-character argument. Exception message: %s" % (len(self.INVALID_NAME), e.data))       
            else:
                step("ipset failed with a %d-character argument. Exception message: %s" % (len(self.INVALID_NAME), e.data))                 
        if self.INVALID_NAME in self.host.execdom0("ipset -L"):
            raise xenrt.XRTFailure("ipset succedded with a %d-character argument." % len(self.INVALID_NAME))               
        step("Test with an invalid name of length %d succeeded." % len(self.INVALID_NAME))            
            
        step("Testing with a valid name \"%s\" of length %d." % (self.VALID_NAME, len(self.VALID_NAME)))                       
        try:
            self.host.execdom0("ipset -N %s iphash" % self.VALID_NAME)
            step("ipset succedded with a %d-character argument." % (len(self.VALID_NAME)))
        except xenrt.XRTFailure, e:
            raise xenrt.XRTFailure("Could not set a valid %d-character name. The following exception has been thrown: %s" % (len(self.VALID_NAME), e.data))        
        if not self.VALID_NAME in self.host.execdom0("ipset -L"):
            raise xenrt.XRTFailure("Could not set a valid %d-character name." % len(self.VALID_NAME))                        
        step("Test with a valid name of length %d succeeded." % len(self.VALID_NAME))

class IPSetNumTablesTest(BackendSwitcher):
    
    def prepare(self, arglist):
        if self.getNetworkBackend() == "bridge":
            BackendSwitcher.prepare(self, arglist)
    
    def run(self,  arglist):
        if self.getNetworkBackend() != "bridge":
            xenrt.TEC().skip("N/A for vswitch")
        else:
            self.clearAllRules()
            resp = self.host.execdom0("for i in {1..1024}; do ipset -N hash$i iphash; done")

class EBTablesInputTest(BackendSwitcher):

    def prepare(self, arglist):
        if self.getNetworkBackend() == "bridge":
            BackendSwitcher.prepare(self, arglist)
    
    def run(self,  arglist):
        if self.getNetworkBackend() != "bridge":
            xenrt.TEC().skip("N/A for vswitch")
        else:
            (pif, bridge, mac, ipv4) = self.linux_guest_1.vifs[0]
            vifName='vif%s.%s'%(self.linux_guest_1.getDomid(), 0)
                        
            self.clearAllRules()
            id = "EBTablesInputTest"
            
            # log packets to dom0's mac address on eth0
            pif = self.host.parseListForUUID("pif-list", "device", "eth0")
            mac = self.host.genParamGet("pif", pif, "MAC")
            self.host.execdom0("ebtables -A INPUT -d %s --log --log-prefix '%s'" % (mac, id))
            
            # ssh dom0 from controller and check it's logged
            self.host.execdom0("ls")
            self.checkKernLogForId(id, True)
            
            # now clear the rules and check nothing is logged
            self.host.execdom0("ebtables -F")
            time.sleep(10)
            self.host.execdom0('echo "" > /var/log/kern.log')
            self.host.execdom0("ls")
            self.checkKernLogForId(id, False)
            
class EBTablesForwardTest(BackendSwitcher):

    def prepare(self, arglist):
        if self.getNetworkBackend() == "bridge":
            BackendSwitcher.prepare(self, arglist)
    
    def run(self,  arglist):
        if self.getNetworkBackend() != "bridge":
            xenrt.TEC().skip("N/A for vswitch")
        else:
            (pif, bridge, mac, ipv4) = self.linux_guest_1.vifs[0]
            vifName='vif%s.%s'%(self.linux_guest_1.getDomid(), 0)
                        
            self.clearAllRules()
            id = "EBTablesForwardTest"
            
            # log packets being forwarded to the VM's MAC address
            self.host.execdom0("ebtables -A FORWARD -i %s -s %s --log --log-prefix '%s'" % (vifName, mac, id))
            
            # ssh vm from controller and check it's logged
            self.linux_guest_1.execguest("ls")
            self.checkKernLogForId(id, True)
            
            # now clear the rules and check nothing is logged
            self.host.execdom0("ebtables -F")
            time.sleep(10)
            self.host.execdom0('echo "" > /var/log/kern.log')
            self.linux_guest_1.execguest("ls")
            self.checkKernLogForId(id, False)
            
class EBTablesOutputTest(BackendSwitcher):

    def prepare(self, arglist):
        if self.getNetworkBackend() == "bridge":
            BackendSwitcher.prepare(self, arglist)
    
    def run(self,  arglist):
        if self.getNetworkBackend() != "bridge":
            xenrt.TEC().skip("N/A for vswitch")
        else:
            (pif, bridge, mac, ipv4) = self.linux_guest_1.vifs[0]
            vifName='vif%s.%s'%(self.linux_guest_1.getDomid(), 0)
                        
            self.clearAllRules()
            id = "EBTablesOutputTest"
            
            # log packets coming out of dom0 with eth0 mac address
            pif = self.host.parseListForUUID("pif-list", "device", "eth0")
            mac = self.host.genParamGet("pif", pif, "MAC")
            
            self.host.execdom0("ebtables -A OUTPUT -s %s --log --log-prefix '%s'" % (mac, id))
            
            # ssh dom0 from controller
            self.host.execdom0("ls")
            self.checkKernLogForId(id, True)
            
            # now clear the rules and check nothing is logged
            self.host.execdom0("ebtables -F")
            time.sleep(10)
            self.host.execdom0('echo "" > /var/log/kern.log')
            self.checkKernLogForId(id, False)
            
class ArpTablesInputTest(BackendSwitcher):

    def prepare(self, arglist):
        if self.getNetworkBackend() == "bridge":
            BackendSwitcher.prepare(self, arglist)
    
    def run(self,  arglist):
        if self.getNetworkBackend() != "bridge":
            xenrt.TEC().skip("N/A for vswitch")
        else:
            host2IP = self.host2.getIP()
            
            self.clearAllRules()
            
            # apply the rules
            try:
                self.host.execdom0("arp -d %s" % host2IP)
            except xenrt.XRTFailure, e:
                pass
                
            self.host.execdom0("arptables -A INPUT -s %s -j DROP" % host2IP)
            
            # ping host2 from dom0
            failed = False
            try:
                self.host.execdom0("ping %s -c 5" % host2IP)
                failed = True
            except xenrt.XRTFailure, e:
                pass
            if (failed):
                raise xenrt.XRTFailure("Arptables didn't block")
            
            # now clear the rules and check ping succeeds
            self.host.execdom0("arptables -F")
            self.host.execdom0("ping %s -c 5" % host2IP)
            
class ArpTablesForwardTest(BackendSwitcher):

    def prepare(self, arglist):
        if self.getNetworkBackend() == "bridge":
            BackendSwitcher.prepare(self, arglist)
    
    def run(self,  arglist):
        if self.getNetworkBackend() != "bridge":
            xenrt.TEC().skip("N/A for vswitch")
        else:
            (pif, bridge, mac, ipv4) = self.linux_guest_1.vifs[0]
            vifName='vif%s.%s'%(self.linux_guest_1.getDomid(), 0)
                        
            self.clearAllRules()
            
            # remove VM1's ip address from VM2's arp table (if required)
            try:
                self.linux_guest_2.execguest("arp -d %s" % self.linux_guest_1.getIP())
            except xenrt.XRTFailure, e:
                pass
            
            # now block arps being forwarded to VM1
            self.host.execdom0("arptables -A FORWARD -d %s -j DROP" % self.linux_guest_1.getIP())
            
            # Now check that we can't ping vm1 from vm2
            failed = False
            try:
                self.linux_guest_2.execguest("ping %s -c 5" % self.linux_guest_1.getIP())
                failed = True
            except xenrt.XRTFailure, e:
                pass
            if (failed):
                raise xenrt.XRTFailure("Arptables didn't block")

            # now clear the rules
            self.host.execdom0("arptables -F")
            
            # ensure can ping VM1
            self.linux_guest_2.execguest("ping %s -c 5" % self.linux_guest_1.getIP())

class ArpTablesOutputTest(BackendSwitcher):
    
    def prepare(self, arglist):
        if self.getNetworkBackend() == "bridge":
            BackendSwitcher.prepare(self, arglist)
    
    def run(self,  arglist):
        if self.getNetworkBackend() != "bridge":
            xenrt.TEC().skip("N/A for vswitch")
        else:
            (pif, bridge, mac, ipv4) = self.linux_guest_1.vifs[0]
            vifName='vif%s.%s'%(self.linux_guest_1.getDomid(), 0)
                        
            host2IP = self.host2.getIP()
            
            self.clearAllRules()
            
            # remove host2 from dom0's arp table (if required)
            try:
                self.host.execdom0("arp -d %s" % host2IP)
            except xenrt.XRTFailure, e:
                pass
            
            # now block ARPs from going out of dom0 to host2
            self.host.execdom0("arptables -A OUTPUT -d %s -j DROP" % host2IP)
            
            # check can't ping host2
            failed = False
            try:
                self.host.execdom0("ping %s -c 5" % host2IP)
                failed = True
            except xenrt.XRTFailure, e:
                pass
            if (failed):
                raise xenrt.XRTFailure("Arptables didn't block ARPs from dom0 to host2")
            
            # now clear the rules
            self.host.execdom0("arptables -F")
            
            # ensure can ping host2 from dom0
            self.host.execdom0("ping %s -c 5" % host2IP)
            
class _XapiPortLock(xenrt.TestCase):
    """The base class for all PR-1219 tests.
    See http://confluence.uk.xensource.com/display/engp/PR-1219 for use-cases being tested for
    Add the ability to "lock" a switch port to a MAC and a list of IPv4 or IPv6 addresses"""
    
    DVSC = False
    
    def run(self, arglist):
       self.lock()
       self.sendTraffic()
       self.checkResults()
        
    def prepare(self, arglist):
        self.host = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        if self.DVSC:
            self.controller = self.getGuest("controller").getDVSCWebServices()
            self.host.associateDVS(self.controller)
        self.isBridge = xenrt.TEC().lookup("NETWORK_BACKEND", None) == "bridge"
        self.iface = "eth0" # we're using eth0 by default for tests
        self.bridge = "xenbr1"
        self.attackerVM = self.getGuest("attacker")
        self.victim1VM = self.getGuest("victim1")
        self.victim2VM = self.getGuest("victim2")
        self.attackerVMipv6 = self.getGuest("attackeripv6")
        self.victim1VMipv6 = self.getGuest("victim1ipv6")
        self.victim2VMipv6 = self.getGuest("victim2ipv6")
        self.guests = [self.attackerVM, self.victim1VM, self.victim2VM, self.attackerVMipv6, self.victim1VMipv6, self.victim2VMipv6]
        
        for g in self.guests:
            if "ipv6" in g.getName():
                g.setUseIPv6()
                
        # cache eth0 mac addresses for convenience
        self.attackerMacipv6 = self.getMac(self.attackerVMipv6)
        self.victim1Macipv6 = self.getMac(self.victim1VMipv6)
        self.victim2Macipv6 = self.getMac(self.victim2VMipv6)
        self.attackerMac = self.getMac(self.attackerVM)
        self.victim1Mac = self.getMac(self.victim1VM)
        self.victim2Mac = self.getMac(self.victim2VM)
        
        # reset everything
        self.unlockAll()
        self.clearArpCaches()

        # store an instance of TcpDump and Scapy for each guest for convenience
        self.tcpDumps = {}
        self.scapys = {}
        for g in self.guests:
            self.tcpDumps[g] = xenrt.networkutils.TcpDump(g)
            self.scapys[g] = xenrt.networkutils.Scapy(g)
            self.scapys[g].install()
        
    def getScapy(self, guest):
        return self.scapys[guest]
    
    def getTcpDump(self, guest):
        return self.tcpDumps[guest]
    
    def postRun(self):
        
        self.unlockAll()
        self.clearArpCaches()
        
        # remove any extra vifs that were created in the test
        for g in self.guests:
            for eth in ["eth1", "eth2"]:
                try:
                    g.execguest("ifconfig %s down" % eth)
                except:
                    pass
                    
                try:
                    g.unplugVIF(eth)
                except:
                    pass
                
                try:
                    g.removeVIF(eth)
                except:
                    pass
        
        if self.DVSC:
            self.host.disassociateDVS()
    
    def clearArpCaches(self):
        if self.victim2VM.getIP() in self.victim1VM.execguest("arp"):
            try:
                self.victim1VM.execguest("arp -d %s" % (self.victim2VM.getIP()))
            except:
                # for some reason this can fail
                pass
        
        if self.victim1VM.getIP() in self.victim2VM.execguest("arp"):
            try:
                self.victim2VM.execguest("arp -d %s" % (self.victim1VM.getIP()))
            except:
                # for some reason this can fail
                pass
            
        if self.victim2VMipv6.getIP() in self.victim1VMipv6.execguest("ip neighbor show"):
            self.victim1VMipv6.execguest("ip neighbor flush %s" % (self.victim2VMipv6.getIP()))
        
        if self.victim1VMipv6.getIP() in self.victim2VMipv6.execguest("ip neighbor show"):
            self.victim2VMipv6.execguest("ip neighbor flush %s" % (self.victim1VMipv6.getIP()))
        
    def getMac(self, guest, iface=None):
        if not iface:
            iface = self.iface
        return self.host.genParamGet("vif", guest.getVIFUUID(iface), "MAC")
        
    def unlockAll(self):
        for g in self.guests:
            self.setVifTo(g, xenrt.lib.xenserver.guest.TampaGuest.VIFLOCK_UNLOCKED, [])
    
    def setVifTo(self, guest, value, addresses, iface=None):
        if not iface:
            iface = self.iface
        
        vifUuid = guest.getVIFUUID(iface)
        guest.setVifLockMode(vifUuid, value)
        
        guest.clearVifAllowedAddresses(vifUuid)
        guest.setVifAllowedIPv4Addresses(vifUuid, filter(lambda x: not self.isIPV6Address(x), addresses))
        guest.setVifAllowedIPv6Addresses(vifUuid, filter(lambda x: self.isIPV6Address(x), addresses))
    
    def lockVif(self, guest):
        self.setVifTo(guest, xenrt.lib.xenserver.guest.TampaGuest.VIFLOCK_LOCKED, [guest.getIP()])
        
    def lockVifToIpAddresses(self, guest, addresses):
        self.setVifTo(guest, xenrt.lib.xenserver.guest.TampaGuest.VIFLOCK_LOCKED, addresses)
        
    def isIPV6Address(self, address):
        if ":" in address:
            return True
        return False
    
    def lock(self):
        """Derived classes should override this method to lock VIFs"""
        pass

    def sendTraffic(self):
        """Derived classes should override this method to send traffic"""
        pass
    
    def checkResults(self):
        """Derived class should override this method to check results"""
        pass
    
class TCIPBroadcast(_XapiPortLock):
    
    def lock(self):
        self.lockVif(self.attackerVM)
        self.lockVif(self.victim1VM)
        
    def sendTraffic(self):
        self.tcpDump = self.getTcpDump(self.attackerVM)
        self.tcpDump.start(self.iface)
        scapy = self.getScapy(self.victim1VM)
        try:
            self.getScapy(self.victim1VM).sendEmptyIPPacket(self.iface, self.victim1Mac, "ff:ff:ff:ff:ff:ff", self.victim1VM.getIP(), "255.255.255.255")
        finally:
            self.tcpDump.stop()
        
    def checkResults(self):
        self.tcpDump.verifyIPPacketReceived(self.victim1Mac, "IP broadcast packet should be received by locked VIF")

class _TCArpBroadcast(_XapiPortLock):
    """ARP spoofing prevention: Base class for testing the blocking of arp broadcasts"""
    
    def sendTraffic(self):
        self.tcpDump = self.getTcpDump(self.attackerVM)
        self.tcpDump.start(self.iface)
        try:
            self.victim1VM.execguest("ping %s -c 5" % (self.victim2VM.getIP()))
        finally:
            self.tcpDump.stop()
        
class TCArpBroadcastNoLocking(_TCArpBroadcast):
    """TC-16590: Verify that ARP request broadcasts are seen by unlocked VIFs with an ip different to the one in the arp request"""
    
    def checkResults(self):
        self.tcpDump.verifyArpRequestReceived(self.victim2VM.getIP(), self.victim1VM.getIP(), "ARP broadcast should be received by unlocked VIF")

class TCArpBroadcastVifLock(_TCArpBroadcast):
    """TC-16591: Verify that ARP broadcasts are not seen by locked VIFs with an ip different to the one in the arp request"""
    
    def lock(self):
        self.lockVif(self.attackerVM)
        
    def checkResults(self):
        self.tcpDump.verifyArpRequestReceived(self.victim2VM.getIP(), self.victim1VM.getIP(), "ARP broadcast should not be received by locked VIF")
        
class _TCBadArpResponse(_XapiPortLock):
    """ARP spoofing prevention base class"""
    
    def sendTraffic(self):
        self.tcpDump = self.getTcpDump(self.victim1VM)
        self.tcpDump.start(self.iface)
        
        try:
            scapy = self.getScapy(self.attackerVM)
            
            # notice we have used self.victim2VM.getIP() for the source ip address of the ARP
            # this should not be allowed if attacker's VIF is locked to its IP address
            
            scapy.sendArp(self.iface, "is-at", self.attackerMac, self.victim2VM.getIP(), self.attackerMac, 
                self.victim1Mac, self.victim1VM.getIP(), self.victim1Mac)
                
            scapy.sendArp(self.iface, "is-at", self.attackerMac, self.victim2VM.getIP(), self.victim2Mac, 
                self.victim1Mac, self.victim1VM.getIP(), self.victim1Mac)
        finally:
            self.tcpDump.stop()
        
class TCBadArpResponseNoLocking(_TCBadArpResponse):
    """TC-16592: ARP spoofing prevention: Verify that ARP responses are seen by unlocked VIFs with a different MAC to the one in the arp response"""
    
    def checkResults(self):
        self.tcpDump.verifyArpReplyReceived(self.attackerMac, self.victim2VM.getIP(), self.attackerMac, "Bad ARP response should be received by unlocked VIF")
        self.tcpDump.verifyArpReplyReceived(self.victim2Mac, self.victim2VM.getIP(), self.attackerMac, "Bad ARP response should be received by unlocked VIF")

class TCBadArpResponseVifLocked(_TCBadArpResponse):
    """TC-16593: ARP spoofing prevention: Verify that ARP responses are not seen by locked VIFs with a different MAC to the one in the arp response"""
    
    def lock(self):
        self.lockVif(self.attackerVM)
    
    def checkResults(self):
        self.tcpDump.verifyArpReplyNotReceived(self.attackerMac, self.victim2VM.getIP(), self.attackerMac, "Bad ARP response should not be received by locked VIF")
        self.tcpDump.verifyArpReplyNotReceived(self.victim2Mac, self.victim2VM.getIP(), self.victim2Mac, "Bad ARP response should not be received by locked VIF")

class TCGoodArpResponse(_XapiPortLock):
    """TC-16594: Verify that arp responses from a locked VIF with correct MAC and ip-address are received"""
    
    def lock(self):
        self.lockVif(self.victim1VM)
        self.lockVif(self.victim2VM)
    
    def sendTraffic(self):
        time.sleep(30)
        self.host.execdom0("ebtables -L")
        self.host1.execdom0("ebtables -L")
        self.victim1VM.execguest("ping %s -c 5" % (self.victim2VM.getIP()))
        self.clearArpCaches()
        self.victim2VM.execguest("ping %s -c 5" % (self.victim1VM.getIP()))
        
class _TCIPMacSpoof(_XapiPortLock):
    """IP/Mac spoofing base class"""
    
    def sendTraffic(self):
        self.tcpDump = self.getTcpDump(self.victim1VM)
        self.tcpDump.start(self.iface)
        
        try:
            self.getScapy(self.attackerVM).sendEmptyIPPacket(self.iface, self.victim2Mac, self.victim1Mac, self.victim2VM.getIP(), self.victim1VM.getIP())
        finally:
            self.tcpDump.stop()
        
class TCIPMacSpoofNoLocking(_TCIPMacSpoof):
    """TC-16595: IP/Mac spoofing prevention: Verify that ip traffic with an incorrect MAC and IP is received by an unlocked vif"""

    def checkResults(self):
        self.tcpDump.verifyIPPacketReceived(self.victim2Mac, "IP packet with bad MAC and IP should be received by unlocked VIF")

class TCIPMacSpoofVifLocked(_TCIPMacSpoof):
    """TC-16596: IP/Mac spoofing prevention: Verify that ip traffic with an incorrect MAC and IP is not received with a locked vif"""
    
    def lock(self):
        self.lockVif(self.attackerVM)
        
    def checkResults(self):
        self.tcpDump.verifyIPPacketNotReceived(self.victim2Mac, "IP packet with bad MAC and IP should not be received by locked VIF")
        self.tcpDump.verifyIPPacketNotReceived(self.attackerMac, "IP packet with bad MAC and IP should not be received by locked VIF")

class _TCIPSpoof(_XapiPortLock):
    """IP spoofing prevention base class"""

    def sendTraffic(self):
        self.tcpDump = self.getTcpDump(self.victim1VM)
        self.tcpDump.start(self.iface)
        scapy = self.getScapy(self.attackerVM)
        try:
            scapy.sendEmptyIPPacket(self.iface, self.attackerMac, self.victim1Mac, self.victim2VM.getIP(), self.victim1VM.getIP())
        finally:
            self.tcpDump.stop()
        
class TCIPSpoofNoLocking(_TCIPSpoof):
    """TC-16597: IP spoofing prevention: Verify that ip traffic with incorrect IP address is received by an unlocked vif"""
    
    def checkResults(self):
        self.tcpDump.verifyIPPacketReceived(self.attackerMac, "IP packet with bad IP should be received by unlocked VIF")

class TCIPSpoofVifLocked(_TCIPSpoof):
    """TC-16598: IP spoofing prevention: Verify that ip traffic with incorrect IP address is not received by a locked vif"""
    
    def lock(self):
        self.lockVif(self.attackerVM)
        
    def checkResults(self):
        self.tcpDump.verifyIPPacketNotReceived(self.attackerMac, "IP packet with bad IP should not be received by locked VIF")

class _TCMacSpoof(_XapiPortLock):
    """Mac spoofing prevention base class"""

    def sendTraffic(self):
        self.tcpDump = self.getTcpDump(self.victim1VM)
        self.tcpDump.start(self.iface)
        scapy = self.getScapy(self.attackerVM)
        try:
            scapy.sendEmptyIPPacket(self.iface, self.victim2Mac, self.victim1Mac, self.attackerVM.getIP(), self.victim1VM.getIP())
        finally:
            self.tcpDump.stop()
        
class TCMacSpoofNoLocking(_TCMacSpoof):
    """TC-16599: Mac spoofing prevention: Verify that ip traffic from an unlocked VIF with an incorrect MAC is received"""
    
    def checkResults(self):
        self.tcpDump.verifyIPPacketReceived(self.victim2Mac, "IP packet with bad MAC should be received by unlocked VIF")
    
class TCMacSpoofVifLocked(_TCMacSpoof):
    """TC-16600: Mac spoofing prevention: Verify that ip traffic from a locked VIF with an incorrect MAC is not received"""
    
    def lock(self):
        self.lockVif(self.attackerVM)
        
    def checkResults(self):
        self.tcpDump.verifyIPPacketNotReceived(self.attackerMac, "IP packet with bad MAC should not be received by locked VIF")
        self.tcpDump.verifyIPPacketNotReceived(self.victim2Mac, "IP packet with bad MAC should not be received by locked VIF")

class _TCSniffing(_XapiPortLock):
    """Traffic sniffing prevention base class"""
    
    def sendTraffic(self):
        unknownMac = "aa:aa:aa:aa:aa:aa"
        self.tcpDump = self.getTcpDump(self.attackerVM)
        self.tcpDump.start(self.iface)
        scapy = self.getScapy(self.victim1VM)
        try:
            scapy.sendEmptyIPPacket(self.iface, self.victim1Mac, unknownMac, self.victim1VM.getIP(), self.victim2VM.getIP())
        finally:
            self.tcpDump.stop()
        
class TCSniffingNoLocking(_TCSniffing):
    """TC-16601: Traffic sniffing prevention: Test that traffic directed to an unknown mac address can be sniffed from an unlocked vif"""    

    def checkResults(self):
        self.tcpDump.verifyIPPacketReceived(self.victim1Mac, "It should be possible to sniff traffic to an unknown mac on an unlocked VIF")

class TCSniffingVifLocked(_TCSniffing):
    """TC-16602: Traffic sniffing prevention: Test that traffic to an unknown mac address can't be sniffed from a locked vif"""    
    
    def lock(self):
        self.lockVif(self.attackerVM)
        
    def checkResults(self):
        self.tcpDump.verifyIPPacketReceived(self.victim1Mac, "It should be possible to sniff traffic to an unknown mac on a locked VIF")

class _TCNeighbourSoliciation(_XapiPortLock):
    """IPv6 NDP spoofing prevention base class"""
    
    def sendTraffic(self):
        self.tcpDump = self.getTcpDump(self.attackerVMipv6)
        self.tcpDump.start(self.iface)
        
        try:
            self.victim1VMipv6.execguest("ping6 %s -c 5" % (self.victim2VMipv6.getIP()))
        finally:
            self.tcpDump.stop()
        
class TCNSNoLocking(_TCNeighbourSoliciation):
    """TC-16603: IPv6 neighbour spoofing prevention: Verify that ICMPv6 NDP Neighbour solicitations aren't blocked by an unlocked vif"""
    
    def checkResults(self):
        self.tcpDump.verifyNdpReceived(self.victim1Macipv6, "IPv6 NS packet should be recieved by unlocked VIF")

class TCNSVifLocked(_TCNeighbourSoliciation):
    """TC-16604: IPv6 neighbour spoofing prevention: Verify that ICMPv6 NDP Neighbour solicitations are blocked by a locked vif"""
    
    def lock(self):
        self.lockVif(self.attackerVMipv6)
        
    def checkResults(self):
        self.tcpDump.verifyNdpReceived(self.victim1Macipv6, "IPv6 NS packet should be recieved by unlocked VIF")

class _TCBadNA(_XapiPortLock):
    """IPv6 neighbour spoofing prevention base class"""
    
    def sendTraffic(self):
        
        self.tcpDump = self.getTcpDump(self.victim1VMipv6)
        self.tcpDump.start(self.iface)
        scapy = self.getScapy(self.attackerVMipv6)
        
        try:
            scapy.sendNeighbourAdvertisement(self.iface, 
                self.attackerMacipv6, 
                self.attackerVMipv6.getIP(), 
                self.victim1Macipv6, 
                self.victim1VMipv6.getIP(), 
                self.victim2VMipv6.getIP(), 
                self.attackerMacipv6)
        finally:
            self.tcpDump.stop()
        
class TCBadNANoLocking(_TCBadNA):
    """TC-16605: IPv6 neighbour spoofing prevention: Verify that ICMPv6 NDP Neighbour advertisements aren't blocked by an unlocked vif"""
    
    def checkResults(self):
        self.tcpDump.verifyNdpReceived(self.attackerMacipv6, "Bad IPv6 NA packet should be recieved by unlocked VIF")
    
class TCBadNAVifLocked(_TCBadNA):
    """TC-16606: IPv6 neighbour spoofing prevention: Verify that ICMPv6 NDP Neighbour advertisements are blocked by a locked vif"""
    
    def lock(self):
        self.lockVif(self.attackerVMipv6)
    
    def checkResults(self):
        if self.isBridge:
            self.tcpDump.verifyNdpReceived(self.attackerMacipv6, "IPv6 NA packet should be received by locked VIFs when using linux bridge")
        else:
            self.tcpDump.verifyNdpNotReceived(self.attackerMacipv6, "IPv6 NA packet should not be received by locked VIF")

class _TCIPMacSpoofIPV6(_XapiPortLock):
    """IPv6 IP/Mac spoofing prevention base class"""
    
    def sendTraffic(self):
        self.tcpDump = self.getTcpDump(self.victim1VMipv6)
        self.tcpDump.start(self.iface)
        scapy = self.getScapy(self.attackerVMipv6)
        
        try:
            scapy.sendEmptyIPv6Packet(self.iface, self.victim2Macipv6, self.victim1Macipv6, self.victim2VMipv6.getIP(), self.victim1VMipv6.getIP())
        finally:
            self.tcpDump.stop()
        
class TCIPMacSpoofNoLockingIPV6(_TCIPMacSpoofIPV6):
    """TC-16607: IPv6 IP/Mac spoofing prevention: Verify that ipv6 traffic from an unlocked VIF with incorrect MAC and IP is not blocked"""
    
    def checkResults(self):
        self.tcpDump.verifyIPPacketReceived(self.victim2Macipv6, "IPv6 packet with bad IP and MAC should be received by unlocked VIF")
    
class TCIPMacSpoofVifLockedIPV6(_TCIPMacSpoofIPV6):
    """TC-16608: IPv6 IP/Mac spoofing prevention: Verify that ipv6 traffic from a locked VIF with incorrect MAC and IP is blocked"""
    
    def lock(self):
        self.lockVif(self.attackerVMipv6)
        
    def checkResults(self):
        self.tcpDump.verifyIPPacketNotReceived(self.victim2Macipv6, "IPv6 packet with bad IP and MAC should not be received")

class _TCIPV6Spoof(_XapiPortLock):
    """IPv6 IP spoofing prevention base class"""

    def sendTraffic(self):
        self.tcpDump = self.getTcpDump(self.victim1VMipv6)
        self.tcpDump.start(self.iface)
        scapy = self.getScapy(self.attackerVMipv6)
        try:
            scapy.sendEmptyIPv6Packet(self.iface, self.attackerMacipv6, self.victim1Macipv6, self.victim2VMipv6.getIP(), self.victim1VMipv6.getIP())
        finally:
            self.tcpDump.stop()
        
class TCIPV6SpoofNoLocking(_TCIPV6Spoof):
    """TC-16609: IPv6 IP spoofing prevention: Verify that ipv6 traffic from a unlocked VIF with incorrect IP is not blocked"""
    
    def checkResults(self):
        self.tcpDump.verifyIPPacketReceived(self.attackerMacipv6, "IPv6 packet with bad IP should be received by unlocked VIF")

class TCIPV6SpoofVifLocked(_TCIPV6Spoof):
    """TC-16610: IPv6 IP spoofing prevention: Verify that ipv6 traffic from a locked VIF with incorrect IP is blocked"""
    
    def lock(self):
        self.lockVif(self.attackerVMipv6)

    def checkResults(self):
        if self.isBridge:
            self.tcpDump.verifyIPPacketReceived(self.attackerMacipv6, "IPv6 packet with bad IP should be recieved when using linux bridge")
        else:
            self.tcpDump.verifyNothingReceivedFromMac(self.attackerMacipv6, "IPv6 packet with bad IP should not be received by locked VIF")

class _TCMacSpoofIPV6(_XapiPortLock):
    """IPv6 Mac spoofing prevention base class"""

    def sendTraffic(self):
        self.tcpDump = self.getTcpDump(self.victim1VMipv6)
        self.tcpDump.start(self.iface)
        scapy = self.getScapy(self.attackerVMipv6)
        try:
            scapy.sendEmptyIPv6Packet(self.iface, self.victim2Macipv6, self.victim1Macipv6, self.attackerVMipv6.getIP(), self.victim1VMipv6.getIP())
        finally:
            self.tcpDump.stop()
        
class TCMacSpoofIPV6NoLocking(_TCMacSpoofIPV6):
    """TC-16611: IPv6 Mac spoofing prevention: Verify that ipv6 traffic from a unlocked VIF with incorrect Mac is not blocked"""
    
    def checkResults(self):
        self.tcpDump.verifyIPPacketReceived(self.victim2Macipv6, "IPv6 packet with bad MAC should be received by unlocked VIF")
    
class TCMacSpoofIPV6VifLocked(_TCMacSpoofIPV6):
    """TC-16612: IPv6 Mac spoofing prevention: Verify that ipv6 traffic from a locked VIF with incorrect Mac is blocked"""
    
    def lock(self):
        self.lockVif(self.attackerVMipv6)
    
    def checkResults(self):
        self.tcpDump.verifyNothingReceivedFromMac(self.attackerMacipv6, "IPv6 packet with bad MAC should not be received by locked VIF")
        self.tcpDump.verifyIPPacketNotReceived(self.victim2Macipv6, "IPv6 packet with bad MAC should not be received by locked VIF")

class TCMultipleIPV4Send(_XapiPortLock):
    """TC-16613: Verify that a VIF can be locked to multiple IPv4 addresses: Send Test"""

    def lock(self):
        self.lockAddresses = [self.attackerVM.getIP(), self.victim1VM.getIP()]
        self.lockVifToIpAddresses(self.attackerVM, self.lockAddresses)
    
    def sendTraffic(self):
        self.tcpDump = self.getTcpDump(self.victim1VM)
        
        for a in [self.attackerVM.getIP(), self.victim1VM.getIP(), self.victim2VM.getIP()]:
            self.tcpDump.start(self.iface)
            try:
                self.getScapy(self.attackerVM).sendEmptyIPPacket(self.iface, self.attackerMac, self.victim1Mac, a, self.victim1VM.getIP())
            finally:
                self.tcpDump.stop()
                
            if not a in self.lockAddresses:
                self.tcpDump.verifyIPPacketNotReceived(self.attackerMac, "IP packet sent to address which isn't assigned to VIF should not be received")
            else:
                self.tcpDump.verifyIPPacketReceived(self.attackerMac, "IP packet sent to address which is assigned to VIF should be received")

class TCGoodNdpResponse(_XapiPortLock):
    """TC-16616: NDP spoofing prevention: Verify that NDP responses from a locked VM with correct MAC and ip-address are received"""
    
    def lock(self):
        self.lockVif(self.victim1VMipv6)
        self.lockVif(self.victim2VMipv6)
    
    def sendTraffic(self):
        self.victim1VMipv6.execguest("ping6 %s -c 5" % (self.victim2VMipv6.getIP()))
        self.clearArpCaches()
        self.victim2VMipv6.execguest("ping6 %s -c 5" % (self.victim1VMipv6.getIP()))

class _TCDisabled(_XapiPortLock):
    """Base class for VIF enablement tests"""

    def sendTraffic(self):
        self.tcpDump = self.getTcpDump(self.attackerVM)
        self.tcpDump.start("eth1")
        
        try:
            self.getScapy(self.victim1VM).sendEmptyIPPacket(self.iface, self.victim1Mac, self.getMac(self.attackerVM, "eth1"), self.victim1VM.getIP(), self.attackerVM.getIP())
        finally:
            self.tcpDump.stop()
        
    def checkResults(self):
        self.tcpDump.verifyIPPacketNotReceived(self.victim1Mac, "No IP traffic should be received on disabled VIF")
        
class TCDisabledNetwork(_TCDisabled):
    """TC-16617: Verify that a default VIF on a disabled network gets no traffic"""
    
    def lock(self):
        self.host.setNetworkLockingMode(self.host.getNetworkUUID("xenbr0"), xenrt.lib.xenserver.host.TampaHost.NETWORKLOCK_UNLOCKED)
        self.attackerVM.createVIF(eth="eth1", bridge="xenbr0", plug=True)
        self.attackerVM.execguest("ifconfig eth1 up")
        self.attackerVM.execguest("dhclient eth1")
        
        # need to unplug vif as you can't set the default-locking-mode on the network if there are plugged vifs
        self.attackerVM.execguest("ifconfig eth1 down")
        self.attackerVM.unplugVIF("eth1")

        # lock down xenbr0
        self.host.setNetworkLockingMode(self.host.getNetworkUUID("xenbr0"), xenrt.lib.xenserver.host.TampaHost.NETWORKLOCK_DISABLED)
        
        # replug vif
        self.attackerVM.plugVIF("eth1")
        self.attackerVM.execguest("ifconfig eth1 up")
        
    def postRun(self):
        _TCDisabled.postRun(self)
        self.host.setNetworkLockingMode(self.host.getNetworkUUID("xenbr0"), xenrt.lib.xenserver.host.TampaHost.NETWORKLOCK_UNLOCKED)

class TCDisabledNetworkDVSC(TCDisabledNetwork):
    """TC-20623: Verify that a default VIF on a disabled network gets no traffic when pool is associated to DVSC"""

    DVSC = True

class TCDisabledVif(_TCDisabled):
    """TC-16618: Verify that a disabled VIF gets no traffic"""

    def lock(self):
        self.attackerVM.createVIF(eth="eth1", bridge="xenbr0", plug=True)
        self.attackerVM.execguest("ifconfig eth1 up")
        self.attackerVM.execguest("dhclient eth1")
        self.setVifTo(self.attackerVM, xenrt.lib.xenserver.guest.TampaGuest.VIFLOCK_DISABLED, [], iface="eth1")

class TCDisabledVifDVSC(TCDisabledVif):
    """TC-20624: Verify that a disabled VIF gets no traffic when pool is associated to DVSC"""

    DVSC = True

class TCDisabledVif2(_TCDisabled):
    """TC-16619: Verify that a disabled VIF with ip addresses assigned gets no traffic"""

    def lock(self):
        self.attackerVM.createVIF(eth="eth1", bridge="xenbr0", plug=True)
        self.attackerVM.execguest("ifconfig eth1 up")
        self.attackerVM.execguest("dhclient eth1")
        ip = self.attackerVM.execguest("ifconfig eth1 | grep 'inet addr:' | cut -d: -f2 | awk '{ print $1}'").strip()
        self.setVifTo(self.attackerVM, xenrt.lib.xenserver.guest.TampaGuest.VIFLOCK_DISABLED, [ip], iface="eth1")

class TCDisabledVif2DVSC(TCDisabledVif2):
    """TC-20625: Verify that a disabled VIF with ip addresses assigned gets no traffic when pool is associated to DVSC"""

    DVSC = True

class TCNetworkLockApiVerify(_XapiPortLock):
    """TC-16621: Smoke test of the network locking API"""

    def setNetworkLockingModeUsingApi(self, uuid, value):
        s = self.host.getAPISession()
        try:
            networks = s.xenapi.network.get_all_records()
            for networkRef in networks.keys():
                if networks[networkRef]['uuid'] == uuid:
                    xenrt.TEC().logverbose("Setting locking mode of '%s' to '%s'" % (networks[networkRef]['bridge'], value))
                    s.xenapi.network.set_default_locking_mode(networkRef, value)
                    break
                
        finally:
            self.host.logoutAPISession(s)
    
    def run(self, arglist):
        networkUuid = self.host.getNetworkUUID("xenbr0")
        for v in [xenrt.lib.xenserver.TampaHost.NETWORKLOCK_UNLOCKED, xenrt.lib.xenserver.TampaHost.NETWORKLOCK_DISABLED]:
            self.setNetworkLockingModeUsingApi(networkUuid, v)
            lockMode = self.host.getNetworkLockingMode(networkUuid)
            if lockMode != v:
                raise xenrt.XRTFailure("Did not set Network locking mode using API, value should be '%s', actually '%s'" % (v, lockMode))
    
    def postRun(self):
        _XapiPortLock.postRun(self)
        self.host.setNetworkLockingMode(self.host.getNetworkUUID("xenbr0"), xenrt.lib.xenserver.host.TampaHost.NETWORKLOCK_UNLOCKED)


class TCVifLockApiVerify(_XapiPortLock):
    """TC-16622: Smoke test of the VIF locking API"""

    def setVifLockingModeUsingApi(self, uuid, value):
        s = self.host.getAPISession()
        try:
            vifs = s.xenapi.VIF.get_all_records()
            for vifRef in vifs.keys():
                if vifs[vifRef]['uuid'] == uuid:
                    xenrt.TEC().logverbose("Setting locking mode of '%s' to '%s'" % (vifs[vifRef]['device'], value))
                    s.xenapi.VIF.set_locking_mode(vifRef, value)
                    break
                
        finally:
            self.host.logoutAPISession(s)
    
    def run(self, arglist):
        self.attackerVM.createVIF(eth="eth1", bridge="xenbr0", plug=True)
        vifUuid = self.attackerVM.getVIFUUID("eth1")
        
        vals = [xenrt.lib.xenserver.guest.TampaGuest.VIFLOCK_NETWORK_DEFAULT,
                xenrt.lib.xenserver.guest.TampaGuest.VIFLOCK_LOCKED,
                xenrt.lib.xenserver.guest.TampaGuest.VIFLOCK_UNLOCKED,
                xenrt.lib.xenserver.guest.TampaGuest.VIFLOCK_DISABLED]
            
        for v in vals:
            self.setVifLockingModeUsingApi(vifUuid, v)
            lockMode = self.attackerVM.getVifLockMode(vifUuid)
            if lockMode != v:
                raise xenrt.XRTFailure("Did not set VIF locking mode using API, value should be '%s', actually '%s'" % (v, lockMode))

class TCVifIPAddressInvalidIPAddress(_XapiPortLock):
    """TC-16623: Smoke test for checking a VIF can't be locked to an invalid ip address"""

    def run(self, arglist):
        for a in ["10.10.10.300", "blurg", "300.10.10.10"]:
            try:
                self.lockVifToIpAddresses(self.attackerVM, [a])
            except:
                pass
            else:
                raise xenrt.XRTFailure("Locking to invalid IP address '%s' didn't throw exception." % a)


