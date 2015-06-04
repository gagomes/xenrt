import socket, re, string, time, traceback, sys, random, copy, os.path
import xenrt, xenrt.lib.xenserver
from xenrt.lazylog import step, comment, log

class IPv6Address(object):
    # I am not proud of this class, but it seems to do the job...
    def __init__(self, addr, prefixlen):
        if type(addr) == str:
            if ':' in addr:
                addr = self.expand(addr)
            else:
                addr = int(addr, 16)
        if type(prefixlen) == str:
            prefixlen = int(prefixlen, 16)
        self.addr = addr
        self.prefixlen = prefixlen
    def __str__(self):
        h = '%032x' % self.addr
        l = [h[i:i+4] for i in range(0, 32, 4)]
        l = map(lambda x: hex(int(x, 16))[2:], l)
        mark, i, m = [], 0, 0
        for x in l:
            if x == '0':
                i += 1
            else:
                i = 0
            mark.append(i)
            m = max(m, i)
        n = mark.index(m)
        if m > 0:
            l[n-m+1:n+1] = ['']
            if l[0] == '': l[0] = ':'
            if l[-1] == '': l[-1] = ':'
        return ':'.join(l)
    def expand(self, addr):
        n = addr.index('::')
        if n > -1:
            m = addr.count(':')
            addr = addr.replace('::', ':0' * (1 + 7 - m) + ':')
        l = addr.split(':')
        return int(''.join([x.zfill(4) for x in l]), 16)
    def fullString(self):
        return '%s/%d' % (str(self), self.prefixlen)
    def matchPrefix(self, other):
        if self.prefixlen != other.prefixlen:
            return False
        elif self.addr >> (128 - self.prefixlen) != other.addr >> (128 - other.prefixlen):
            return False
        else:
            return True

class _IPv6(xenrt.TestCase):
    # Test guest options
    ARCH = "x86-64"
    DISTRO = "ubuntu1204"
    TEMPLATE_VM_NAME = "xenrt-ipv6-%u"
    VLAN = False
    BOND = False
    BOND_MODE = None
    TUNNEL = False

    # IPv6 network options
    ROUTER_IPV6 = IPv6Address('fd27:d4ac:d1d:c0d7::1', 64)
    ROUTER_DNS = 's0'
    DOMAIN = 'test6.uk.xensource.com'
    IPV6_VLAN = 'VR08'

    # Special TC options
    SINGLE_HOST = True

    IPV6_BRIDGE = "xenbr0"

    IPV6_NICS = []
    IPV6_VNIC = 'eth1'   # in guest

    def createGrePort(self, host, name, bridge, local_ip, remote_ip, key):
        # The DVSC normally creates these tunnel ports, but we do it manually to avoid having to install the DVSC
        host.execdom0("ovs-vsctl -- --may-exist add-port %s %s -- set interface %s type=gre options:key=%s options:remote_ip=%s options:local_ip=%s" % (bridge, name, name, key, remote_ip, local_ip))

    def getVlanID(self, host, vlan):
        vlan_id, subnet, netmask = host.getVLAN(vlan)
        return vlan_id

    def setupVlan(self):
        net = self.host.createNetwork()
        vlan_id = self.getVlanID(self.host, self.IPV6_VLAN)
        nsec_nics = map(int, self.host.listSecondaryNICs(network='NSEC'))
        nsec_nics.sort()
        if len(nsec_nics) == 0:
            raise xenrt.XRTError("Host doesn't have any NSEC NIC")
        self.host.createVLAN(vlan_id, net, "eth%d" % nsec_nics[0])
        if not self.SINGLE_HOST:
            nsec_nics = map(int, self.host2.listSecondaryNICs(network='NSEC'))
            nsec_nics.sort()
            if len(nsec_nics) == 0:
                raise xenrt.XRTError("Host doesn't have any NSEC NIC")
            self.host2.createVLAN(vlan_id, net, "eth%d" % nsec_nics[0])
        self.ipv6_net = net
        
    def destroyVlan(self):
        self.vlan_id = self.getVlanID(self.host, self.IPV6_VLAN)
        self.host.removeVLAN(self.vlan_id)
        if not self.SINGLE_HOST:
            self.host2.removeVLAN(self.vlan_id)
        self.host.removeNetwork(self.ipv6_net)

    def getNPRINICs(self,host):
        nics = ["eth%d" % i for i in host.listSecondaryNICs(network='NPRI')]
        if host.getNICNetworkName(0) == 'NPRI':
            nics = ['eth0'] + nics
        nics = list(set(nics))
        nics.sort()
        return nics
            
    def setupBond(self):
        net = self.host.createNetwork()
        ipv6_nics = self.getNPRINICs(self.host)
        if len(ipv6_nics) < 2:
            raise xenrt.XRTError("Insufficient NPRI NPRIs available for creating a BOND")
        ipv6_nics = ipv6_nics[:2]

        pifs = map(lambda nic: self.host.parseListForUUID("pif-list", "device", nic, "host-uuid=%s" %
            (self.host.getMyHostUUID())), ipv6_nics)
        self.host.createBond(pifs=pifs, network=net, mode=self.BOND_MODE)

        if not self.SINGLE_HOST:
            ipv6_nics = self.getNPRINICs(self.host2)
            if len(ipv6_nics) < 2:
                raise xenrt.XRTError("Insufficient NPRI NPRIs available for creating a BOND")
            ipv6_nics = ipv6_nics[:2]
            pifs = map(lambda nic: self.host2.parseListForUUID("pif-list", "device", nic, "host-uuid=%s" %
                (self.host2.getMyHostUUID())), ipv6_nics)
            self.host2.createBond(pifs=pifs, network=net, mode=self.BOND_MODE)
        self.ipv6_net = net

    def destroyBond(self):
        bonds = self.host.getBonds()
        for bond in bonds:
            self.host.execdom0('xe bond-destroy uuid=%s' % bond)
        self.host.removeNetwork(self.ipv6_net)

    def setupTunnel(self):
        # This does not make sense on a single host
        if self.SINGLE_HOST:
            raise xenrt.XRTError("Tunnels do not make sense on a single host")
        net = self.host.createNetwork()
        pifs = map(lambda nic: self.host.parseListForUUID("pif-list", "device", nic, "host-uuid=%s" %
            (self.host.getMyHostUUID())), self.IPV6_NICS)
        self.host.execdom0('xe pif-reconfigure-ip uuid=%s mode=static IP=192.168.6.1 netmask=255.255.255.0' % pifs[0])
        self.host.execdom0('xe tunnel-create network-uuid=%s pif-uuid=%s' % (net, pifs[0]))

        pifs = map(lambda nic: self.host2.parseListForUUID("pif-list", "device", nic, "host-uuid=%s" %
            (self.host2.getMyHostUUID())), self.IPV6_NICS)
        self.host2.execdom0('xe pif-reconfigure-ip uuid=%s mode=static IP=192.168.6.2 netmask=255.255.255.0' % pifs[0])
        self.host2.execdom0('xe tunnel-create network-uuid=%s pif-uuid=%s' % (net, pifs[0]))

        bridge = self.host.genParamGet("network", net, "bridge")
        self.createGrePort(self.host, "gre6", bridge, '192.168.6.1', '192.168.6.2', "6")
        self.createGrePort(self.host2, "gre6", bridge, '192.168.6.2', '192.168.6.1', "6")

        xenrt.TEC().logverbose('Setting up IPv6 router on private network')
        self.installIpv6Router(self.host)

        self.ipv6_net = net

    def destroyTunnel(self):
        tunnels = self.host.minimalList('tunnel-list')
        for tunnel in tunnels:
            self.host.execdom0('xe tunnel-destroy uuid=%s' % tunnel)
        self.host.removeNetwork(self.ipv6_net)

    def prepare(self, arglist):
        self.guests = []
        self.host = self.getDefaultHost()
        if not self.SINGLE_HOST:
            self.host2 = self.getHost("RESOURCE_HOST_1")

        if self.BOND:
            self.setupBond()
        elif self.VLAN:
            self.setupVlan()
        elif self.TUNNEL:
            self.setupTunnel()
        else:
            cli = self.host.getCLIInstance()
            self.ipv6_net = cli.execute('network-list', 'bridge=%s --minimal' % self.IPV6_BRIDGE).strip()

        self.host.templateVM = self.createTemplateVM(self.host, self.TEMPLATE_VM_NAME % 0)

        if not self.SINGLE_HOST:
            self.host2.templateVM = self.createTemplateVM(self.host2, self.TEMPLATE_VM_NAME % 1, self.host)
        else:
            self.host2 = self.host


    def postRun(self):
        for g in self.guests:
            try:
                if g.getState() != "DOWN":
                    try: g.shutdown(again=True)
                    except: pass
                g.uninstall()
            except:
                pass
        if self.BOND:
            self.destroyBond()
        if self.VLAN:
            self.destroyVlan()
        if self.TUNNEL:
            self.destroyTunnel()

    def createTemplateVM(self, host, name, host0=None):
        "Create IPv6 Template VM, or return existing one"

        # See if local template VM already exists
        guest = self.getGuest(name)
        if guest:
            return guest

        if host0 and host0.templateVM:
            sr = host.getLocalSR()
            guest = host0.templateVM.copyVM(name=name, sruuid=sr)
            guest.setHost(host)
            return guest

        guest = host.createBasicGuest(name=name, distro=self.DISTRO)
        self.uninstallOnCleanup(guest)
        self.getLogsFrom(guest)

        guest.waitForAgent(180)
        
        # Change to unstable and update DHCP client
        # (dhclient has worked well for DHCPv6 only since mid-2011)
        #guest.execguest("sed -i 's/squeeze/unstable/' /etc/apt/sources.list")
        guest.execguest("apt-get update")
        #guest.execguest("apt-get install -y --force-yes isc-dhcp-client")
        # Install IPv6 version of netcat (nc)
        #guest.execguest("wget %s/netcat6/netcat6_1.0-8_i386.deb" % xenrt.TEC().lookup("TEST_TARBALL_BASE"))
        #guest.execguest("dpkg -i netcat6_1.0-8_i386.deb")

        guest.reboot()
        guest.shutdown()

        return guest

    def installIpv6Router(self, host):
        pass

    def createTestGuest(self, host):
        guest = host.templateVM.cloneVM(name=xenrt.randomGuestName())
        guest.setHost(host)
        host.execdom0('xe vif-create vm-uuid=%s network-uuid=%s device=1 mac=%s' % (guest.getUUID(), self.ipv6_net, xenrt.randomMAC()))
        guest.start()
        self.getLogsFrom(guest)
        guest.NICs = guest.getVIFs()
        self.guests.append(guest)
        return guest

    def doDHCPv6(self, guest, nic):
        guest.execguest("echo 0 > /proc/sys/net/ipv6/conf/%s/autoconf" % nic)
        guest.execguest("ifconfig %s down; ifconfig %s up" % (nic, nic))
        guest.execguest("dhclient -6 %s" % nic)

    def doAutoConf(self, guest, nic):
        guest.execguest("echo 1 > /proc/sys/net/ipv6/conf/%s/autoconf" % nic)
        guest.execguest("ifconfig %s down; ifconfig %s up" % (nic, nic))

    def getIPv6Addresses(self, guest):
        raw = guest.execguest("cat /proc/net/if_inet6")
        info = {}
        for line in raw.split('\n'):
            r = re.search("(\S+) +(\S+) +(\S+) +(\S+) +(\S+) +(\S+)\s*", line)
            if r:
                if r.group(6) not in info:
                    info[r.group(6)] = []
                address = IPv6Address(r.group(1), r.group(3))
                xenrt.TEC().logverbose('%s has %s' % (r.group(6), address.fullString()))
                info[r.group(6)].append(address)
        return info

    def findAddress(self, guest, nic):
        addresses = self.getIPv6Addresses(guest)
        found = None
        host = guest.getHost()
        guest_network = self.IPV6_VLAN if self.VLAN else "NPRI"
        (router_prefix, dhcp6_begin, dhcp6_end) = host.getIPv6NetworkParams(nw=guest_network)
        prefix = IPv6Address(router_prefix, 64)
        
        for address in addresses[nic]:
            if address.matchPrefix(prefix):
                found = address
        if not found:
            xenrt.TEC().logverbose("Required prefix == %s  guest_network == %s" % (prefix, guest_network))
            raise xenrt.XRTFailure("No IPv6 address present with required prefix")
        return found

    def checkPing(self, guest1, nic1, guest2, nic2, oneway=False):
        addr1 = self.findAddress(guest1, nic1)
        addr2 = self.findAddress(guest2, nic2)
        
        rc = guest1.execguest("ping6 -c 3 %s" % str(addr2), retval="code")
        if rc != 0:
            raise xenrt.XRTFailure("Could not ping6 from guest 1 to guest 2")

        if not oneway:
            rc = guest2.execguest("ping6 -c 3 %s" % str(addr1), retval="code")
            if rc != 0:
                raise xenrt.XRTFailure("Could not ping6 from guest 2 to guest 1")

    def checkDNS(self, guest):
        if True:
            return
        guest.execguest("echo 'domain\t%s\nnameserver\t%s' > /etc/resolv.conf" % (self.DOMAIN, str(self.ROUTER_IPV6)))
        rc = guest.execguest("ping6 -c 3 %s" % self.ROUTER_DNS, retval="code")
        if rc != 0:
            raise xenrt.XRTFailure("Could not ping6 DNS name of router")

    def checkTCP(self, guest1, nic1, guest2, nic2, port):
        addr1 = self.findAddress(guest1, nic1)
        addr2 = self.findAddress(guest2, nic2)

        # Setup server
        s = "IPv6 is coming!"
        guest1.execguest("nohup echo '%s' | nc -6 -l %s > out &" % (s, port))

        # Setup receiver
        guest2.execguest("nohup nc -6 %s %s > x &" % (str(addr1), port))

        # Cleanup
        try:
            guest1.execguest("killall nc")
        except:
            pass

        try:
            guest2.execguest("killall nc")
        except:
            pass

        # Check string
        time.sleep(1)
        r = guest2.execguest("cat x").strip()
        if r != s:
            raise xenrt.XRTFailure("Could not transfer data from guest 2 to guest 1 via TCP port %s" % port)
        else:
            xenrt.TEC().logverbose("Successfully transfered string '%s'" % r)

    def run(self, arglist=None):
        pass

class IPv6TC1pt1(_IPv6):
    "Basic communication with a XenServer VM via IPv6"

    def prepare(self, arglist):
        _IPv6.prepare(self, arglist=arglist)
        self.vm1 = self.createTestGuest(self.host)
        self.vm2 = self.createTestGuest(self.host2)

    def run(self, arglist=None):
        xenrt.TEC().logverbose('Autoconfiguring IPv6 addresses and testing connection (ping)')
        self.doAutoConf(self.vm1, self.IPV6_VNIC)
        self.doAutoConf(self.vm2, self.IPV6_VNIC)
        time.sleep(5)
        self.checkPing(self.vm1, self.IPV6_VNIC, self.vm2, self.IPV6_VNIC)

        xenrt.TEC().logverbose('Using DHCPv6 to configure IPv6 addresses and testing connection (ping)')
        self.doDHCPv6(self.vm1, self.IPV6_VNIC)
        self.doDHCPv6(self.vm2, self.IPV6_VNIC)
        time.sleep(5)
        self.checkPing(self.vm1, self.IPV6_VNIC, self.vm2, self.IPV6_VNIC)

        xenrt.TEC().logverbose('Check whether router can be reached by its DNS name')
        self.checkDNS(self.vm1)
        self.checkDNS(self.vm2)

        xenrt.TEC().logverbose('Check whether we can transfer some data over TCP')
        self.checkTCP(self.vm1, self.IPV6_VNIC, self.vm2, self.IPV6_VNIC, '8080')

class IPv6TC1pt2(IPv6TC1pt1):
    SINGLE_HOST = False

class IPv6TC3(IPv6TC1pt2):
    VLAN = True

class IPv6TC4pt1(IPv6TC1pt2):
    BOND = True
    BOND_MODE = "balance-slb"

class IPv6TC4pt2(IPv6TC1pt2):
    BOND = True
    BOND_MODE = "active-backup"

# Ensure the IPv6 router is also on the tunnel network before calling run()!
class IPv6TC5(IPv6TC1pt2):
    TUNNEL = True

class IPv6Portlock(object):
    "Port locking"
    
    host = None

    # Taken from BobB's portlocking.py
    def execMulti(self,  host,  multi,  targetFileName):
        """Run multiple commands from a shell script to ensure the firewall/routing is not temporarily in an inconsistent state"""
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

    # Taken from BobB's portlocking.py
    def resetHostRules(self,  host):
        # Reset each bridge
        brs = host.execdom0('ovs-vsctl list-br').split('\n')
        multi=['#!/bin/sh']
        for bridge in brs[:-1]:
            multi.append('network_uuid=`xe network-list bridge=%s minimal=true`'%bridge)
            multi.append('pif=`xe pif-list network-uuid=$network_uuid params=device minimal=true`')
            multi.append('ofport=`ovs-vsctl get Interface $pif ofport`')
            multi.append('ovs-ofctl del-flows %s'%bridge)
            multi.append('ovs-ofctl add-flow %s priority=1,actions=normal'%bridge)
        self.execMulti(host,  multi,  "portlocking_reset_rules.sh")

    # Taken from BobB's portlocking.py
    def clearRules(self, bridge, vifName):
        multi=['#!/bin/sh']
        multi.append('ofport=`ovs-vsctl get Interface %s ofport`'%vifName)
        multi.append('ovs-ofctl del-flows %s in_port=$ofport'%bridge)
        #multi.append('ovs-ofctl add-flow %s priority=10$ofport,in_port=$ofport,actions=normal'%bridge)
        self.execMulti(self.host,  multi,  "portlocking_unlock.sh")

    # Modified from BobB's portlocking.addIPv4LockRules
    def addIPv6LockRules(self, bridge, vifName, mac, ipv6):
        # Rules adapted from:
        # http://bazaar.launchpad.net/~corywright/nova/ovs-vif-rules/view/head:/plugins/xenserver/networking/etc/xensource/scripts/ovs_configure_vif_flows.py

        xenrt.TEC().logverbose('Locking IPv6 and MAC of %s' % vifName)

        params = {'BRIDGE': bridge,
                  'MAC': mac,
                  'IPV6': ipv6}

        multi=['#!/bin/sh']
        multi.append('ofport=`ovs-vsctl get Interface %s ofport`' % vifName)
        multi.append('ovs-ofctl del-flows %s in_port=$ofport' % bridge)

        # allow valid IPv6 ND outbound
        # Neighbor Solicitation
        multi.append("ovs-ofctl add-flow %(BRIDGE)s priority=6,in_port=$ofport,dl_src=%(MAC)s,icmp6,ipv6_src=%(IPV6)s,icmp_type=135,nd_sll=%(MAC)s,actions=normal" % params)
        multi.append("ovs-ofctl add-flow %(BRIDGE)s priority=6,in_port=$ofport,dl_src=%(MAC)s,icmp6,ipv6_src=%(IPV6)s,icmp_type=135,actions=normal" % params)

        # Neighbor Advertisement
        multi.append("ovs-ofctl add-flow %(BRIDGE)s priority=6,in_port=$ofport,dl_src=%(MAC)s,icmp6,ipv6_src=%(IPV6)s,icmp_type=136,nd_target=%(IPV6)s,actions=normal" % params)
        multi.append("ovs-ofctl add-flow %(BRIDGE)s priority=6,in_port=$ofport,dl_src=%(MAC)s,icmp6,ipv6_src=%(IPV6)s,icmp_type=136,actions=normal" % params)

        # drop all other neighbor discovery (req b/c we permit all icmp6 below
        multi.append("ovs-ofctl add-flow %(BRIDGE)s priority=5,in_port=$ofport,icmp6,icmp_type=135,actions=drop" % params)
        multi.append("ovs-ofctl add-flow %(BRIDGE)s priority=5,in_port=$ofport,icmp6,icmp_type=136,actions=drop" % params)

        # do not allow sending specifc ICMPv6 types
        # Router Advertisement
        multi.append("ovs-ofctl add-flow %(BRIDGE)s priority=5,in_port=$ofport,icmp6,icmp_type=134,actions=drop" % params)
        # Redirect Gateway
        multi.append("ovs-ofctl add-flow %(BRIDGE)s priority=5,in_port=$ofport,icmp6,icmp_type=137,actions=drop" % params)
        # Mobile Prefix Solicitation
        multi.append("ovs-ofctl add-flow %(BRIDGE)s priority=5,in_port=$ofport,icmp6,icmp_type=146,actions=drop" % params)
        # Mobile Prefix Advertisement
        multi.append("ovs-ofctl add-flow %(BRIDGE)s priority=5,in_port=$ofport,icmp6,icmp_type=147,actions=drop" % params)
        # Multicast Router Advertisement
        multi.append("ovs-ofctl add-flow %(BRIDGE)s priority=5,in_port=$ofport,icmp6,icmp_type=151,actions=drop" % params)
        # Multicast Router Solicitation
        multi.append("ovs-ofctl add-flow %(BRIDGE)s priority=5,in_port=$ofport,icmp6,icmp_type=152,actions=drop" % params)
        # Multicast Router Termination
        multi.append("ovs-ofctl add-flow %(BRIDGE)s priority=5,in_port=$ofport,icmp6,icmp_type=153,actions=drop" % params)

        # allow valid IPv6 outbound, by type
        multi.append("ovs-ofctl add-flow %(BRIDGE)s priority=4,in_port=$ofport,dl_src=%(MAC)s,ipv6_src=%(IPV6)s,icmp6,actions=normal" % params)
        multi.append("ovs-ofctl add-flow %(BRIDGE)s priority=4,in_port=$ofport,dl_src=%(MAC)s,ipv6_src=%(IPV6)s,tcp6,actions=normal" % params)
        multi.append("ovs-ofctl add-flow %(BRIDGE)s priority=4,in_port=$ofport,dl_src=%(MAC)s,ipv6_src=%(IPV6)s,udp6,actions=normal" % params)
        # all else will be dropped ...
        multi.append('ovs-ofctl add-flow %(BRIDGE)s priority=3,in_port=$ofport,actions=drop' % params)

        self.execMulti(self.host, multi, "portlocking_lock_ipv6.sh")

class IPv6TC9(IPv6Portlock, IPv6TC1pt2):
    def run(self, arglist=None):
        self.resetHostRules(self.host)

        xenrt.TEC().logverbose('Autoconfiguring IPv6 addresses and testing connection (ping)')
        self.doAutoConf(self.vm1, self.IPV6_VNIC)
        self.doAutoConf(self.vm2, self.IPV6_VNIC)
        time.sleep(2)
        self.checkPing(self.vm1, self.IPV6_VNIC, self.vm2, self.IPV6_VNIC)

        ipv6 = str(self.findAddress(self.vm1, self.IPV6_VNIC))
        mac = self.vm1.NICs[self.IPV6_VNIC][0]
        vifName = 'vif%s.%s' % (self.vm1.getDomid(), self.IPV6_VNIC[3])

        xenrt.TEC().logverbose('Locking to real IPv6 and MAC -- Ping should still work')
        self.addIPv6LockRules(self.IPV6_BRIDGE, vifName, mac, ipv6)
        self.checkPing(self.vm1, self.IPV6_VNIC, self.vm2, self.IPV6_VNIC)
        self.clearRules(self.IPV6_BRIDGE, vifName)

        xenrt.TEC().logverbose('Locking to false IPv6 and real MAC -- Ping should fail')
        self.addIPv6LockRules(self.IPV6_BRIDGE, vifName, mac, 'fe00::1')
        time.sleep(2)
        failed = False
        try:
            self.checkPing(self.vm1, self.IPV6_VNIC, self.vm2, self.IPV6_VNIC, oneway=True)
            failed = True
        except:
            pass
        if failed:
            raise xenrt.XRTFailure("Guest should not have been reachable with wrong IPv6")
        self.clearRules(self.IPV6_BRIDGE, vifName)

        xenrt.TEC().logverbose('Locking to real IPv6 and MAC -- Ping should work again')
        self.addIPv6LockRules(self.IPV6_BRIDGE, vifName, mac, ipv6)
        self.checkPing(self.vm1, self.IPV6_VNIC, self.vm2, self.IPV6_VNIC)
        self.clearRules(self.IPV6_BRIDGE, vifName)

        xenrt.TEC().logverbose('Locking to real IPv6 and false MAC -- Ping should fail')
        self.addIPv6LockRules(self.IPV6_BRIDGE, vifName, 'ff:ff:ff:ff:ff:ff', ipv6)
        time.sleep(2)
        failed = False
        try:
            self.checkPing(self.vm1, self.IPV6_VNIC, self.vm2, self.IPV6_VNIC, oneway=True)
            failed = True
        except:
            pass
        if failed:
            raise xenrt.XRTFailure("Guest should not have been reachable with wrong MAC")
        self.clearRules(self.IPV6_BRIDGE, vifName)

class IPv6WinGuest(xenrt.TestCase):
    """Test IPv6 guest with Windows"""
    # Jira TC-16130
    DISTRO = "win7-x86"
    def __init__(self):
        xenrt.TestCase.__init__(self)
        self.host = None
        self.guestBridge = None
        
    def installIpv6WinGuest(self, host):
        guest = host.createBasicGuest(distro=self.DISTRO, use_ipv6=True )
        self._guestsToUninstall.append(guest)
        # check IPv4 address - assume that we'll just have "eth0 VIF on the guest
        mac, ip, network = guest.getVIFs()["eth0"]
        if ip is None:
            raise xenrt.XRTFailure("IPv4 not found on freshly installed guest")
        else:
            if re.match('\d+\.\d+.\d+\.\d+', ip):
                log("IPv4 address of the guest: %s" % ip)
            else:
                raise xenrt.XRTFailure("Unexpected IP format: '%s'" % ip)
            
        # disable IPv4
        guest.disableIPv4()
        mac, ip, network = guest.getVIFs()["eth0"]
        if ip:
            raise xenrt.XRTFailure("IPv4 address still seems to exist on the guest: %s" % ip)
        return guest

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guest = self.installIpv6WinGuest(self.host)

    def run(self, arglist=None):
        commandOutput = self.guest.xmlrpcExec("ipconfig /all", returndata=True)
        if not len(commandOutput) > 0:
            raise xenrt.XRTFailure("Failed to contact the guest through xmlrcp")

class IPv6Win64Guest(IPv6WinGuest):
    """Test IPv6 guest with 64-bit Windows"""
    # Jira TC-16134
    
    DISTRO = "win7-x64"
    
    
class IPv6WinGuestOnBond(IPv6WinGuest):
    """Test a Windows guest with IPv6, installed on bonded network"""
    # Jira TC-16135

    TOPOLOGY = """
<NETWORK>
  <PHYSICAL>
    <MANAGEMENT/>
    <NIC/>
    <NIC/>
      <VMS/>
  </PHYSICAL>
</NETWORK>
"""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.host.createNetworkTopology(self.TOPOLOGY)
        self.guest = self.installIpv6WinGuest(self.host)
        
    def postRun(self):
        bond = self.host.getBonds()[0]
        (bridge,device) = self.host.removeBond(bond, dhcp=True, management=True)

        
class IPv6InterWinGuest(IPv6WinGuest):
    """Test IPv6 communication between two Windows guests""" 
    # Jira TC-16281
 
    def prepare(self, arglist=None):
    
        # install a guest on first host and get its IPv6 address
        self.host = self.getDefaultHost()
        self.guest = self.installIpv6WinGuest(self.host)
        self.guestAddr = self.guest.getIPv6AutoConfAddress()
        
        # install a guest on second host and get its IPv6 address
        self.host2 = self.getHost("RESOURCE_HOST_1")
        self.guest2 = self.installIpv6WinGuest(self.host2)
        self.guest2Addr = self.guest2.getIPv6AutoConfAddress()
        
        # allow ICMPv6 on both guests
        command = ('netsh advfirewall firewall add rule name="ICMPv6" '
                    'protocol=icmpv6:any,any dir=in action=allow')
        self.guest.xmlrpcExec(command)
        self.guest2.xmlrpcExec(command)
        
    def run(self, arglist=None):
        step('Sending ping from controller to guest')
        self.pingGuest(self.guestAddr)
        
        step('Sending ping from controller to guest1')
        self.pingGuest(self.guest2Addr)            

        step('Sending ping from guest to guest1')
        self.guest2guestPing(self.guest, self.guest2Addr)
        
        step('Sending ping from guest1 to guest')
        self.guest2guestPing(self.guest, self.guest2Addr)
            
    def pingGuest(self, ip6):
        # ping a guest on its IPv6 address from the controller 
        retCode = xenrt.command(("ping6 -c 3 -w 10 %s" % ip6), retval="code")
        if retCode != 0:
            raise xenrt.XRTFailure("Failed to ping the guest on %s" % ip6)

    def guest2guestPing(self, srcGuest, destIP):
        # ping a guest from another guest
        data = srcGuest.xmlrpcExec("ping -6 -n 3 %s" % destIP, returndata=True)
        if (not re.search("\(0% loss\)", data) or
                re.search("Destination host unreachable", data)) :
            raise xenrt.XRTFailure("Pinging target failed.")
            
class IPv6InterWinPingXL(IPv6InterWinGuest):
    "Ping a Windows WM from another Windows VM using a large IPv6 packet"
    # Jira TC-16626
 
    def pingGuest(self, ip6):
        try:
            # ping a guest on its IPv6 address from the controller 
            command = "ping6 -c 3 -w 10 -s 2000 %s"
            retCode = xenrt.command((command % ip6), retval="code")
            if retCode != 0:
                raise xenrt.XRTFailure('Command "%s" returned code %s' % (command, retCode) )
        except Exception, e:
            log('Exception encountered: \n%s\n' % e)
            raise xenrt.XRTFailure('Sending a large ping packet to %s failed' % ip6)
         
    def guest2guestPing(self, srcGuest, destIP):
        # ping a guest from another guest
        try: 
            data = srcGuest.xmlrpcExec("ping -6 -n 3 -l 2000 %s" % destIP, returndata=True)
            if (not re.search("\(0% loss\)", data) or
                    re.search("Destination host unreachable", data)) :
                raise xenrt.XRTFailure("Pinging target failed.")
        except Exception, e:
            log('Exception encountered: \n%s\n' % e)
            raise xenrt.XRTFailure('Sending a large ping packet to %s failed' % destIP)
                
class IPv6WinGuestOnVlan(_IPv6):
    """Test a Windows guest with IPv6, installed on a VLAN"""
    # Jira TC-16135
        
    DISTRO = "win7-x86"
    VLAN = True
    SINGLE_HOST = True
    
    def prepare(self, arglist=None):
    
        self.host = self.getDefaultHost()
        self.setupVlan()
        self.host2 = self.host
        self.guests = []

        # tag the ipv6 network to be used by VMs
        self.host.genParamSet("network", self.ipv6_net, "other-config", "true", "xenrtvms")
        
        # install the guest with IPv6 support
        self.guest = self.host.createBasicGuest(distro=self.DISTRO, use_ipv6=True)
        self.guests.append(self.guest)
        self.guest.disableIPv4()
        
    def run(self, arglist=None):
        commandOutput = self.guest.xmlrpcExec("ipconfig /all", returndata=True)
        if not len(commandOutput) > 0:
            raise xenrt.XRTFailure("Failed to contact the guest through xmlrcp")
            
    def postRun(self):
        # untag the ipv6 network used by VMs
        self.host.genParamSet("network", self.ipv6_net, "other-config", "false", "xenrtvms")
        _IPv6.postRun(self)
        
        
class IPv6WinGuestDhcp(IPv6WinGuestOnVlan):
    """Windows guest with IPv6, using DHCP"""
    # Jira TC-16354
    
    IPV6_VLAN = 'DH6'

    def run(self, arglist=None):
        self.guest.enableIPv6Dhcp()
        if not self.guest.checkIsIPv6AdrressInRange(self.guest.mainip):
            raise xenrt.XRTFailure("Guest does not have a valid DHCP6 IPv6 address")
        IPv6WinGuestOnVlan.run(self, arglist)


class IPv6StaticAddrLinux(_IPv6):

    def prepare(self, arglist):

        self.host = self.getDefaultHost()
        self.vm1 = self.host.createGenericLinuxGuest(name=xenrt.randomGuestName())
        self.uninstallOnCleanup(self.vm1)
        self.vm2 = self.host.createGenericLinuxGuest(name=xenrt.randomGuestName())
        self.uninstallOnCleanup(self.vm2)

    def run(self, arglist=None):

        staticIpObj = self.vm1.specifyStaticIPv6()
        ipv6Add = staticIpObj.getAddr()
        try:
            self.vm2.execguest("ping6 -c 3 %s" % ipv6Add)
        except:
            raise xenrt.XRTFailure("IPV6 address %s is not pingable" % ipv6Add)

        self.vm1.reboot()
        try:
            self.vm2.execguest("ping6 -c 3 %s" % ipv6Add)
        except:
            raise xenrt.XRTFailure("IPV6 address %s is not pingable" % ipv6Add)

        staticIpObj.release()

class IPv6StaticAddrWin(_IPv6):

    PVDRIVER = True

    def prepare(self, arglist):
  
        postInstall = []
        self.host = self.getDefaultHost()
        if self.PVDRIVER:
            postInstall = ["installDrivers"]
        
        self.vm = xenrt.lib.xenserver.guest.createVM(self.host,
                                                    xenrt.randomGuestName(),
                                                    "win7-x86",
                                                    arch="x86-32",
                                                    memory=2048,
                                                    vifs=[("0",
                                                        self.host.getPrimaryBridge(),
                                                        xenrt.randomMAC(),
                                                        None)],
                                                    disks=[("0",1,False)],
                                                    postinstall=postInstall,
                                                    use_ipv6=True)
        self.getLogsFrom(self.vm)
        self.uninstallOnCleanup(self.vm)

    def run(self, arglist=None): 

        staticIpObj = self.vm.specifyStaticIPv6()
        ipv6Add = staticIpObj.getAddr()
        self.vm.mainip =  ipv6Add
        self.vm.getWindowsIPConfigData()

        if not self.PVDRIVER:
            self.vm.installDrivers()
            
        self.vm.getWindowsIPConfigData()
        
        # just to be sure
        self.vm.mainip = ipv6Add
        self.vm.getWindowsIPConfigData()

        staticIpObj.release()

class IPv6StaticNoPVdriv(IPv6StaticAddrWin):

    PVDRIVER = False
    
class TCIPv6IPv4AllowedClear(xenrt.TestCase):
    """ Test case to check that ipv6-allowed and ipv4-allowed gets cleared properly (regression test for CA-110801)"""
    #Jira TC-20790
    
    def run(self, arglist = None):
        
        host = self.getDefaultHost()
        guest = host.createGenericLinuxGuest()
        vif = guest.getVIFUUID("eth0")
        self.uninstallOnCleanup(guest)
        
        #Create arbitrary param-keys for ipv4-allowed and ipv6-allowed
        ipv4address = ["127.0.0.2"]
        ipv6address = ["0::0:1:1"]
         
        #CLI testing 
        step("Add ivp4-allowed and ipv6-allowed param for the vif via CLI")
        guest.setVifAllowedIPv4Addresses(vif, ipv4address)
        guest.setVifAllowedIPv6Addresses(vif, ipv6address)
        
        step("Clear ipv4-allowed and ipv6-allowed for the vif via CLI")
        guest.clearVifAllowedAddresses(vif)
        step("Verify whether the params get cleared")
        ipv4allowed = host.genParamGet("vif", vif, "ipv4-allowed")
        ipv6allowed = host.genParamGet("vif", vif, "ipv6-allowed")
        if ipv4allowed:
            raise xenrt.XRTFailure("ipv4-allowed didn't get cleared via vif-param-clear. ipv4-allowed=%s" %ipv4allowed)
        if ipv6allowed:
            raise xenrt.XRTFailure("ipv6-allowed didn't get cleared via vif-param-clear. ipv6-allowed=%s" %ipv6allowed)
        log("Both ipv4-allowed and ipv6-allowed got cleared via vif-param-clear")
            
        step("Add ipv4-allowed and ipv6-allowed again to test vif-param-remove")
        guest.setVifAllowedIPv4Addresses(vif, ipv4address)
        guest.setVifAllowedIPv6Addresses(vif, ipv6address)
        
        step("Remove ipv4-allowed and ipv6-allowed for the vif via CLI")
        cli = host.getCLIInstance()
        cli.execute("vif-param-remove", "uuid=%s param-name=ipv4-allowed param-key=%s" %(vif, ipv4address[0]))
        cli.execute("vif-param-remove", "uuid=%s param-name=ipv6-allowed param-key=%s" %(vif, ipv6address[0]))
        step("Verify whether the params get removed")
        ipv4allowed = host.genParamGet("vif", vif, "ipv4-allowed")
        ipv6allowed = host.genParamGet("vif", vif, "ipv6-allowed")
        if ipv4allowed:
            raise xenrt.XRTFailure("ipv4-allowed didn't get removed via vif-param-remove. ipv4-allowed=%s" %ipv4allowed)
        if ipv6allowed:
            raise xenrt.XRTFailure("ipv6-allowed didn't get removed via vif-param-remove. ipv6-allowed=%s" %ipv6allowed)
        log("Both ipv4-allowed and ipv6-allowed got removed via vif-param-remove")
        
        #API testing
        step("Add ipv4-allowed and ipv6-allowed again for the vif via CLI")
        guest.setVifAllowedIPv4Addresses(vif, ipv4address)
        guest.setVifAllowedIPv6Addresses(vif, ipv6address)
        
        step("Create an API session to the host")
        session = host.getAPISession()
        xapi = session.xenapi
        log("CALL: xenapi.VIF.get_all()")
        vif_opaqueref = xapi.VIF.get_all()[0] #Opaque ref for the VIF
        log("RESULT: %s" % vif_opaqueref)
        
        step("Attempt to remove the ipv6_allowed with the key for ipv4_allowed, using API call")
        log("CALL: xenapi.VIF.remove_ivp6_allowed('%s','%s')" %(vif_opaqueref, ipv4address[0]))
        xapi.VIF.remove_ipv6_allowed(vif_opaqueref, ipv4address[0])
        
        #Close the API Session
        host.logoutAPISession(session)
        
        #Previously the remove_ipv6_allowed function was incorrect. 
        #In that case, the above call will result in ipv4_allowed getting cleared.
        #If fixed, ipv4_allowed should remain 
        ipv4allowed = host.genParamGet("vif", vif, "ipv4-allowed")
        if not ipv4allowed: #if ipv4_allowed gets removed
            raise xenrt.XRTFailure("ipv4_allowed parameter got removed while calling remove_ipv6_allowed() with incorrect param-key")
