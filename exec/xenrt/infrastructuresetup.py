#
# XenRT: Code for generating config files for a XenRT site
#

import glob,sys,string,os,copy,re,socket

import xenrt

def setupNetPeer(netpeer, config):
    # Setup logdir
    xenrt.TEC().logdir = xenrt.resources.LogDirectory()

    # Get the info for this peer
    tp = config.lookup(["TTCP_PEERS",netpeer])
    mac = tp["MAC"]
    addr = tp["ADDRESS"]

    print "Configuring network test peer %s" % (netpeer)

    machine = xenrt.PhysicalHost(netpeer,ipaddr=addr)
    machine.macaddr = mac
    config.setVariable("MAC_ADDRESS", mac)

    h = xenrt.NetPeerHost(machine) 

    # Hacks to make install work
    h.memory = None
    h.vcpus = None
 
    h.installLinuxVendor("centos64",extrapackages=["xinetd"],kickstart="centos6")
    print "Centos Installed, tailoring..."
    h.tailor()
    print "Tailoring complete, installing netperf and iperf..."

    h.execdom0("chkconfig iptables off")
    h.execdom0("/etc/init.d/iptables stop")
    
    # Install netperf
    h.installNetperf()
    # Set up netserver
    h.execdom0("echo 'netperf 12865/tcp' >> /etc/services")
    h.execdom0("""echo 'service netperf
{
        disable                 = no
        socket_type             = stream
        protocol                = tcp
        wait                    = no
        user                    = root
        server                  = /usr/local/bin/netserver
}
' > /etc/xinetd.d/netperf""")
    h.execdom0("/etc/init.d/xinetd restart")

    # Install iperf
    h.installIperf()
    # Set up iperf server
    h.execdom0("echo '/usr/local/bin/iperf -s -D > /dev/null 2>&1 </dev/null' "
               ">> /etc/rc.d/rc.local")
    h.execdom0("echo '/usr/local/bin/iperf -s -D -u > /dev/null 2>&1 "
               "</dev/null' >> /etc/rc.d/rc.local")
    h.execdom0("iperf -s -D > /dev/null 2>&1 </dev/null")
    h.execdom0("iperf -s -D -u > /dev/null 2>&1 </dev/null")
    
    print "Netperf and iperf installed, configuring any vlans..."

    # Set up any necessary vlans
    sftp = h.sftpClient()
    h.execdom0("modprobe 8021q")

    if tp.has_key("VLANS"):
        vlans = tp["VLANS"]
        for vlan in vlans.split(","):
            (vid, net) = vlan.split(":",1)
            (ip, mask) = net.split("/",1)
            netConf = """DEVICE=eth0.%s
BOOTPROTO=static
IPADDR=%s
NETMASK=%s
ONBOOT=yes
TYPE=Ethernet
VLAN=yes
""" % (vid,ip,mask)
            ifcfg = xenrt.TEC().tempFile()
            f = file(ifcfg, "w")
            f.write(netConf)
            f.close()
            sftp.copyTo(ifcfg, 
                        "/etc/sysconfig/network-scripts/ifcfg-eth0.%s" % (vid))
            # And set it up for now
            h.execdom0("vconfig add eth0 %s" % (vid))
            h.execdom0("ifconfig eth0.%s %s netmask %s up" % (vid,ip,mask))
            print "Configured vlan %s" % (vid)

    # Set up the cleanup script (kills any netserver procs over 7 days old)
    h.execdom0("echo '30 2 * * * root %s/cleanupNetperf.py' >> /etc/crontab" %
               (xenrt.TEC().lookup("REMOTE_SCRIPTDIR")))
    h.execdom0("/etc/init.d/crond restart")

    print "%s has been successfully set up." % (netpeer)

def buildDHCPSubnet(config, configpath, netname, hostdict):
    configpath = copy.copy(configpath)
    configpath.append(None)
    configpath[-1] = "ADDRESS"
    myself = config.lookup(configpath, None)
    if myself:
        configpath[-1] = "SUBNET"
        subnet = config.lookup(configpath)
        configpath[-1] = "SUBNETMASK"
        netmask = config.lookup(configpath)
        configpath[-1] = "GATEWAY"
        gateway = config.lookup(configpath, None)
        if gateway:
            gatewaytext = "option routers                %s;" % gateway
        else:
            gatewaytext = ""
        configpath[-1] = "POOLSTART"
        poolstart = config.lookup(configpath)
        configpath[-1] = "POOLEND"
        poolend = config.lookup(configpath)
        if config.lookup("DHCP_IGNORE_UIDS", False, boolean=True):
            ignoreuids = "  ignore-client-uids true;\n"
        else:
            ignoreuids = ""
        text = """subnet %s netmask %s {
  option subnet-mask            %s;
  %s
  authoritative;
%s
  next-server %s;
%s

  pool {
    range %s %s;
    deny members of "cloudstack";
  }

""" % (subnet, netmask, netmask, gatewaytext, ignoreuids, myself, pxeFile(config), poolstart, poolend)

        if hostdict.has_key(netname):
            for x in hostdict[netname]:
                machine, nic, addr, mac = x
                text =  text + """  host %s-%s {
    fixed-address %s;
    hardware ethernet %s;
  }
""" % (machine.replace("_","-"), nic, addr, mac)
        text = text + "}\n"
        return text
    return ""

def buildDHCP6Subnet(config, configpath, netname, ifname, hostdict):
    configpath = copy.copy(configpath)
    configpath.append(None)
    configpath[-1] = "POOLSTART6"
    poolstart = config.lookup(configpath,None)
    configpath[-1] = "POOLEND6"
    poolend = config.lookup(configpath,None)
    configpath[-1] = "SUBNET6"
    subnet = config.lookup(configpath,None)
    configpath[-1] = "SUBNETMASK6"
    subnetmask = config.lookup(configpath,None)
    if poolstart and poolend:
        text = """iface %s {
    t1 1800-2000
    t2 2700-3000
    prefered-lifetime 3600
    valid-lifetime 7200
    class {
        pool %s-%s
    }
""" % (ifname, poolstart, poolend)
        if hostdict.has_key(netname):
            for x in hostdict[netname]:
                machine, nic, addr, mac = x
                if nic:
                    entryname = "%s-%s" % (machine, nic)
                else:
                    entryname = machine
                text =  text + """
    # %s
    client link-local fe80::%s {
        address %s
        prefix %s/%s
    }
""" % (entryname, xenrt.getInterfaceIdentifier(mac.lower()), addr, subnet, subnetmask)

        text += "}\n"

        return text
    return None

def pxeFile(config):
    if config.lookup("USE_IPXE", False, boolean=True):
        pxefile ="undionly.kpxe"
    else:
        pxefile = "pxelinux.0"
    
    return """  if exists user-class and option user-class = "iPXE" {
      filename "http://%s/tftp/default-ipxe.cgi";
  } else {
      filename "/%s";
  }
""" % (config.lookup("XENRT_SERVER_ADDRESS"), pxefile)

def buildDHCPFile(config,machines,testpeers,sharedhosts):
    # Produce dhcpd.conf
    sys.stdout.write("Creating config file: dhcpd.conf...\n")
    dns = config.lookup(["NETWORK_CONFIG", "DEFAULT", "NAMESERVERS"], None)
    if dns:
        dnsconfig = "option domain-name-servers %s;" % (dns)
    else:
        dnsconfig = ""
    domainname = config.lookup(["NETWORK_CONFIG", "DEFAULT", "DOMAIN"], "uk.xensource.com")
    if domainname:
        domainnameconfig = "option domain-name \"%s\";" % (domainname)
    else:
        domainnameconfig = ""
    ntp = ntpservers = xenrt.TEC().lookup("NTP_SERVERS", "") 
    if ntp:
        ntpservers = ntp.split()
        ntps = []
        for s in ntpservers:
            try:
                ntps.append(socket.gethostbyname(s))
            except:
                pass
        ntp = string.join(ntps,",")
        ntpconfig = "option ntp-servers %s;" % (ntp)
    else:
        ntpconfig = ""
    if config.lookup("DHCP_IGNORE_UIDS", False, boolean=True):
        ignoreuids = "  ignore-client-uids true;\n"
    else:
        ignoreuids = ""
    f = file("dhcpd.conf", "w")
    f.write("""# dhcpd.conf generated by XenRT

use-host-decl-names on;

allow booting;
allow bootp;

boot-unknown-clients on;
ddns-update-style none;

default-lease-time 3600;
max-lease-time 3600;

%s
%s
%s

class "cloudstack" {
  match if (
    (binary-to-ascii (16,8,":",substring(hardware, 0, 2)) = "1:2") or
    (binary-to-ascii (16,8,":",substring(hardware, 0, 2)) = "1:6")
  );
}

subnet %s netmask %s {
  option subnet-mask            %s;
  option routers                %s;
  authoritative;
%s
  next-server %s;
%s


""" % (domainnameconfig,
       dnsconfig,
       ntpconfig,
       config.lookup(["NETWORK_CONFIG", "DEFAULT", "SUBNET"]),
       config.lookup(["NETWORK_CONFIG", "DEFAULT", "SUBNETMASK"]),
       config.lookup(["NETWORK_CONFIG", "DEFAULT", "SUBNETMASK"]),
       config.lookup(["NETWORK_CONFIG", "DEFAULT", "GATEWAY"]),
       ignoreuids,
       config.lookup("XENRT_SERVER_ADDRESS"), pxeFile(config)))
    if config.lookup(["NETWORK_CONFIG", "DEFAULT", "POOLSTART"]) != "TODO":
        f.write("""  pool {
    range %s %s;
    deny members of "cloudstack";
  }
""" % (config.lookup(["NETWORK_CONFIG", "DEFAULT", "POOLSTART"]),
       config.lookup(["NETWORK_CONFIG", "DEFAULT", "POOLEND"])))
    f.write("""  # Test machines and network test peers
  group {
""")
    for machine in machines:
        addr = config.lookup(["HOST_CONFIGS", machine, "HOST_ADDRESS"], None)
        mac = config.lookup(["HOST_CONFIGS", machine, "MAC_ADDRESS"], None)
        if addr and mac:
            f.write("    host %s {\n"
                    "      fixed-address %s;\n"
                    "      hardware ethernet %s;\n"
                    "    }\n" % (machine.replace("_","-"), addr, mac))

    # Get entries for other interfaces with statically assigned addresses
    hostSecondaryEntries = {}
    for machine in machines:
        if sharedhosts and machine in sharedhosts:
            continue
        nicdict = config.lookup(["HOST_CONFIGS", machine, "NICS"], None)
        if nicdict:
            for nic in nicdict.keys():
                network = config.lookup(\
                    ["HOST_CONFIGS", machine, "NICS", nic, "NETWORK"], None)
                addr = config.lookup(\
                    ["HOST_CONFIGS", machine, "NICS", nic, "IP_ADDRESS"], None)
                mac = config.lookup(\
                    ["HOST_CONFIGS", machine, "NICS", nic, "MAC_ADDRESS"], None)
                if network and addr and mac:
                    if network == "NPRI":
                        f.write("    host %s-%s {\n"
                                "      fixed-address %s;\n"
                                "      hardware ethernet %s;\n"
                                "    }\n" % (machine.replace("_","-"), nic, addr, mac))
                    else:
                        if not hostSecondaryEntries.has_key(network):
                            hostSecondaryEntries[network] = []
                        hostSecondaryEntries[network].append(\
                            (machine, nic, addr, mac))
        bmcmac = config.lookup(["HOST_CONFIGS", machine, "BMC_MAC"], None)
        bmcaddr = config.lookup(["HOST_CONFIGS", machine, "BMC_ADDRESS"], None)
        if bmcmac and bmcaddr:
            f.write("    host %s-bmc {\n"
                    "      fixed-address %s;\n"
                    "      hardware ethernet %s;\n"
                    "    }\n" % (machine.replace("_","-"), bmcaddr, bmcmac))
    if testpeers:
        for tp in testpeers:
            if testpeers[tp].has_key("MAC"):
                mac = testpeers[tp]["MAC"]
                addr = testpeers[tp]["ADDRESS"]
                f.write("    host %s {\n"
                        "      fixed-address %s;\n"
                        "      hardware ethernet %s;\n"
                        "    }\n" % (tp, addr, mac))
            bmcmac = config.lookup(["HOST_CONFIGS", tp, "BMC_MAC"], None)
            bmcaddr = config.lookup(["HOST_CONFIGS", tp, "BMC_ADDRESS"], None)
            if bmcmac and bmcaddr:
                f.write("    host %s-bmc {\n"
                        "      fixed-address %s;\n"
                        "      hardware ethernet %s;\n"
                        "    }\n" % (tp.replace("_","-"), bmcaddr, bmcmac))

    if sharedhosts:
        for sh in sharedhosts:
            if sharedhosts[sh].has_key("MAC"):
                mac = sharedhosts[sh]["MAC"]
                addr = sharedhosts[sh]["ADDRESS"]
                f.write("    host %s {\n"
                        "      fixed-address %s;\n"
                        "      hardware ethernet %s;\n"
                        "    }\n" % (sh, addr, mac))
            bmcmac = config.lookup(["HOST_CONFIGS", sh, "BMC_MAC"], None)
            bmcaddr = config.lookup(["HOST_CONFIGS", sh, "BMC_ADDRESS"], None)
            if bmcmac and bmcaddr:
                f.write("    host %s-bmc {\n"
                        "      fixed-address %s;\n"
                        "      hardware ethernet %s;\n"
                        "    }\n" % (sh.replace("_","-"), bmcaddr, bmcmac))

    f.write("  }\n")
    if os.path.exists("/etc/dhcpd.conf.local"):
        f.write("  include \"/etc/dhcpd.conf.local\";\n")
    f.write("}\n")

    if config.lookup(["NETWORK_CONFIG", "SECONDARY", "SUBNET"], None):
        f.write(buildDHCPSubnet(config, ["NETWORK_CONFIG", "SECONDARY"],
                                "NSEC",
                                hostSecondaryEntries))
    vsubnets = config.lookup(["NETWORK_CONFIG", "VLANS"], None)
    if vsubnets:
        for v in vsubnets:
            if v == "RSPAN": continue
            f.write(buildDHCPSubnet(config, ["NETWORK_CONFIG", "VLANS", v],
                                    v,
                                    hostSecondaryEntries))

    extrasubnets = config.lookup(["NETWORK_CONFIG","EXTRA_DHCP_SUBNETS"],None)
    if extrasubnets:
        for subnet in extrasubnets.split(","):
            s = subnet.split("/",1)
            sn = s[0]
            mask = s[1]
            # Convert sn and mask to integers
            snint = xenrt.util.convertIpToLong(sn)
            maskint = xenrt.util.convertIpToLong(mask)
            # Find the router (add 1 to subnet)
            routerint = snint + 1
            router = xenrt.util.convertLongToIp(routerint)
            # Find start (add 10 to subnet)
            startint = snint + 10
            start = xenrt.util.convertLongToIp(startint)
            # Find end (subtract 1 from broadcast)
            bcastint = (2**32 + ~maskint) | snint
            endint = bcastint - 1
            end = xenrt.util.convertLongToIp(endint)

            pxe = config.lookup("XENRT_SERVER_ADDRESS")
            if config.lookup("DHCP_IGNORE_UIDS", False, boolean=True):
                ignoreuids = "  ignore-client-uids true;\n"
            else:
                ignoreuids = ""

            f.write("""subnet %s netmask %s {
  option subnet-mask            %s;
  option routers                %s;
  authoritative;
%s
  next-server %s;
%s

  pool {
    range %s %s;
    deny members of "cloudstack";
  }
}
""" % (sn,mask,mask,router,ignoreuids,pxe,pxeFile(config),start,end))

    f.close()

def buildDHCP6File(config,machines,testpeers,sharedhosts):
    sys.stdout.write("Creating config file: dibbler-server.conf...\n")
    f = file("dibbler-server.conf", "w")
    f.write("# server.conf generated by XenRT\n\n")
    f.write("inactive-mode\n\n")
    hostEntries = {}
    hostEntries["NPRI"] = []

    for machine in machines:
        addr = config.lookup(["HOST_CONFIGS", machine, "HOST_ADDRESS6"], None)
        mac = config.lookup(["HOST_CONFIGS", machine, "MAC_ADDRESS"], None)
        if addr and mac:
            hostEntries["NPRI"].append((machine, None, addr, mac))

    # Get entries for other interfaces with statically assigned addresses
    for machine in machines:
        nicdict = config.lookup(["HOST_CONFIGS", machine, "NICS"], None)
        if nicdict:
            for nic in nicdict.keys():
                network = config.lookup(\
                    ["HOST_CONFIGS", machine, "NICS", nic, "NETWORK"], None)
                addr = config.lookup(\
                    ["HOST_CONFIGS", machine, "NICS", nic, "IP_ADDRESS6"], None)
                mac = config.lookup(\
                    ["HOST_CONFIGS", machine, "NICS", nic, "MAC_ADDRESS"], None)
                if network and addr and mac:
                    if not hostEntries.has_key(network):
                        hostEntries[network] = []
                    hostEntries[network].append(\
                        (machine, nic, addr, mac))
        bmcmac = config.lookup(["HOST_CONFIGS", machine, "BMC_MAC"], None)
        bmcaddr = config.lookup(["HOST_CONFIGS", machine, "BMC_ADDRESS6"], None)
        if bmcmac and bmcaddr:
            hostEntries["NPRI"].append((machine, "bmc", bmcaddr, bmcmac))
    if testpeers:
        for tp in testpeers:
            mac = config.lookup(["HOST_CONFIGS", tp, "MAC"], None)
            addr = config.lookup(["HOST_CONFIGS", tp, "ADDRESS6"], None)
            if mac and addr:
                hostEntries["NPRI"].append((tp, None, addr, mac))
            bmcmac = config.lookup(["HOST_CONFIGS", tp, "BMC_MAC"], None)
            bmcaddr = config.lookup(["HOST_CONFIGS", tp, "BMC_ADDRESS6"], None)
            if bmcmac and bmcaddr:
                hostEntries["NPRI"].append((machine, "bmc", bmcaddr, bmcmac))

    if sharedhosts:
        for sh in sharedhosts:
            mac = config.lookup(["HOST_CONFIGS", sh, "MAC"], None)
            addr = config.lookup(["HOST_CONFIGS", sh, "ADDRESS6"], None)
            if mac and addr:
                hostEntries["NPRI"].append((sh, None, addr, mac))
            bmcmac = config.lookup(["HOST_CONFIGS", sh, "BMC_MAC"], None)
            bmcaddr = config.lookup(["HOST_CONFIGS", sh, "BMC_ADDRESS6"], None)
            if bmcmac and bmcaddr:
                hostEntries["NPRI"].append((sh, "bmc", bmcaddr, bmcmac))

    text = buildDHCP6Subnet(config, ["NETWORK_CONFIG", "DEFAULT"], "NPRI", "eth0", hostEntries)
    if text:
        f.write(text)

    text = buildDHCP6Subnet(config, ["NETWORK_CONFIG", "SECONDARY"], "NSEC", "eth0.%s" % config.lookup(["NETWORK_CONFIG", "SECONDARY", "VLAN"], None), hostEntries)
    if text:
        f.write(text)

    vsubnets = config.lookup(["NETWORK_CONFIG", "VLANS"], None)
    if vsubnets:
        for v in vsubnets:
            if v == "RSPAN": continue
            text = (buildDHCP6Subnet(config, ["NETWORK_CONFIG", "VLANS", v], v, "eth0.%s" % config.lookup(["NETWORK_CONFIG", "VLANS", v, "ID"]), hostEntries))
            if text:
                f.write(text)

    f.close()

def buildHostsFile(config,machines,testpeers,sharedhosts):
    # Produce hosts
    sys.stdout.write("Creating config file: hosts...\n")
    f = file("hosts", "w")
    f.write("# hosts generated by XenRT\n"
            "127.0.0.1 localhost localhost.localdomain\n"
            "%s controller\n" % (config.lookup("XENRT_SERVER_ADDRESS"))
            "%s xenrt-controller\n" % (config.lookup("XENRT_SERVER_ADDRESS")))
    for machine in machines:
        addr = config.lookup(["HOST_CONFIGS", machine, "HOST_ADDRESS"], None)
        if addr:
            f.write("%s %s\n" % (addr,machine.replace("_","-")))
    if testpeers:
        for tp in testpeers:
            addr = testpeers[tp]["ADDRESS"]
            if addr:
                f.write("%s %s\n" % (addr,tp))

    f.close()

def buildConserverClientFile(config):
    # Create console.cf.
    sys.stdout.write("Creating config file: console.cf...\n")
    master = config.lookup("CONSERVER_ADDRESS")
    f = file("console.cf", "w")
    f.write("config * {\nmaster %s;\nport 3109;\n}" % (master))
    f.close()

def buildConserverServerFile(config,machines,testpeers,sharedhosts):
    sys.stdout.write("Creating config file: conserver.cf...\n")
    f = file("conserver.cf", "w")
    master = config.lookup("CONSERVER_ADDRESS")
    if config.lookup(["CONSERVER_LOCAL"],False,boolean=True):
        f.write("""# conserer.cf generated by XenRT
config * {
    defaultaccess trusted;
}

access * {
    trusted 0.0.0.0/0;
}

default consoleserver {
    type host;
    portbase 0;
    portinc 1;
    rw *;
    logfile /local/consoles/&;    
    logfilemax 10m;
    master %s;
    options reinitoncc;
}

default ipmi {
    type exec;
    logfile /local/consoles/&;
    logfilemax 10m;
    rw *;
    master %s;
    options ondemand,reinitoncc;
}

default slave {
    type exec;
}

""" % (master,master))
        entries = config.lookup(["CONSERVER_ENTRIES"], {}) 
        for machine in machines:
            entries[machine] = config.lookup(["HOST_CONFIGS", machine])
        if testpeers:
            for tp in testpeers:
                entries[tp] = config.lookup(["HOST_CONFIGS", tp])
        if sharedhosts:
            for sh in sharedhosts:
                shc = config.lookup(["HOST_CONFIGS", sh], None)
                if shc:
                    entries[sh] = shc
        for i in entries.keys():
            if entries[i].has_key("CONSOLE_TYPE"):
                consoletype = entries[i]["CONSOLE_TYPE"]
                consolename = string.split(i, ".")[0]
                if entries[i].has_key("CONSOLE_ALIASES"):
                    aliases = " aliases \"%s\" ; " % entries[i]["CONSOLE_ALIASES"]
                else:
                    aliases = ""
                if consoletype == "none":
                    pass
                elif consoletype == "basic":
                    f.write("console %s { include consoleserver; host %s; port %s ;%s}\n" % (consolename, entries[i]["CONSOLE_ADDRESS"],entries[i]["CONSOLE_PORT"], aliases))
                elif consoletype == "slave":
                    f.write("console %s { include slave; master %s;%s }\n" % (consolename, entries[i]["CONSERVER_ADDRESS"], aliases))
                elif consoletype == "ipmi":
                    if entries[i].has_key("IPMI_INTERFACE"):
                        intf = entries[i]["IPMI_INTERFACE"]
                    else:
                        intf = "lanplus"
                    f.write("console %s { include ipmi; exec \"ipmitool -H %s -I %s -U %s -P %s sol activate\"; %s }\n" % (consolename, entries[i]["BMC_ADDRESS"], intf, entries[i]["IPMI_USERNAME"], entries[i]["IPMI_PASSWORD"], aliases))
                elif consoletype == "ssh":
                    extra = ""
                    if not entries[i].has_key("CONSOLE_SSH_ADDRESS"):
                        entries[i]["CONSOLE_SSH_ADDRESS"] = entries[i]["BMC_ADDRESS"]
                    if not entries[i].has_key("CONSOLE_SSH_USERNAME"):
                        entries[i]["CONSOLE_SSH_USERNAME"] = entries[i]["IPMI_USERNAME"]
                    if not entries[i].has_key("CONSOLE_SSH_PASSWORD"):
                        entries[i]["CONSOLE_SSH_PASSWORD"] = entries[i]["IPMI_PASSWORD"]
                    if entries[i].has_key("CONSOLE_SSH_COMMAND"):
                        extra += " %s" % entries[i]["CONSOLE_SSH_COMMAND"]
                    if entries[i].has_key("CONSOLE_SSH_INIT"):
                        extra += "\"; initcmd \"/etc/conserver/initcmd \\\"%s\\\" \\\"%s\\\"" % (entries[i]["CONSOLE_SSH_INIT_PROMPT"], entries[i]["CONSOLE_SSH_INIT"])
                    f.write("console %s { include ipmi; exec \"sshpass -p %s ssh %s@%s -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null%s\"; %s }\n" % (consolename, entries[i]["CONSOLE_SSH_PASSWORD"], entries[i]["CONSOLE_SSH_USERNAME"], entries[i]["CONSOLE_SSH_ADDRESS"], extra, aliases))
    else:
        f.write("""# conserer.cf generated by XenRT
config * {
    defaultaccess trusted;
}

access * {
    trusted 0.0.0.0/0;
}

default slave {
    type exec;
    master %s;
}

""" % (master))
        for m in machines:
            f.write("console %s { include slave; }\n" % (m))

    f.close()

def buildDebianNetworkConfigFile(config):
    vsubnets = config.lookup(["NETWORK_CONFIG", "VLANS"], None)
    data = []
    data6 = []
    if config.lookup(["NETWORK_CONFIG", "DEFAULT", "ADDRESS6"], None):
        npri = config.lookup(["NETWORK_CONFIG", "DEFAULT"], None)
        data6.append(("eth0", npri['ADDRESS6'], npri['SUBNETMASK6'], npri['GATEWAY6']))
    if config.lookup(["NETWORK_CONFIG", "SECONDARY", "VLAN"], None):
        nsec = config.lookup(["NETWORK_CONFIG", "SECONDARY"], None)
        data.append(("eth0." + str(nsec['VLAN']), nsec['ADDRESS'], nsec['SUBNETMASK']))
        if nsec.has_key("ADDRESS6"):
            data6.append(("eth0." + str(nsec['VLAN']), nsec['ADDRESS6'], nsec['SUBNETMASK6'], None))
    if vsubnets:
        for v in vsubnets:
            if v == "RSPAN": continue
            vid = config.lookup(["NETWORK_CONFIG", "VLANS", v, "ID"])
            ipaddr = config.lookup(["NETWORK_CONFIG", "VLANS", v, "ADDRESS"], None)
            if ipaddr:
                netmask = config.lookup(["NETWORK_CONFIG", "VLANS", v, "SUBNETMASK"])
                data.append(("eth0." + str(vid), ipaddr, netmask))
            ipaddr6 = config.lookup(["NETWORK_CONFIG", "VLANS", v, "ADDRESS6"], None)
            if ipaddr6:
                netmask6 = config.lookup(["NETWORK_CONFIG", "VLANS", v, "SUBNETMASK6"])
                data6.append(("eth0." + str(vid), ipaddr6, netmask6,None))
                
    d = os.popen("ip route show dev eth0").read()
    netmask = re.search("/(\d+)", d).group(1)
    netmask = ".".join([ str(int((int(netmask)*"1" + (32-int(netmask))*"0")[x:x+8],2)) for x in range(0, 32, 8) ])
    address = re.search("src ([\d+\.]+)", d).group(1)
    try:
        gateway = re.search("default via ([\d+\.]+)", d).group(1)
    except:
        gateway = None
    origfile = open("/etc/network/interfaces").readlines()

    origlines = []
    origautoifs = []
    keep = False
    for l in origfile:
        m = re.match("auto (.*)", l)
        if m:
            origautoifs.extend(m.group(1).strip().split(" "))
        if re.search("iface eth[1-9]", l):
            keep = True
        elif re.search("iface eth0", l):
            keep = False
        if keep:
            origlines.append(l)

    f = file("interfaces", "w")
    f.write("auto lo eth0 ")
    autoifs = map(lambda (x,y,z):x, data)
    autoifs.extend(filter(lambda x: x not in autoifs and x != "eth0", map(lambda(x,y,z,g):x, data6)))
    for i in origautoifs:
        if i not in autoifs and i not in ["lo", "eth0"]:
            autoifs.append(i)
    f.write(" ".join(autoifs))
    f.write("\n")
    f.write("\n")
    f.write("iface lo inet loopback\n")
    f.write("\n")
    f.write("iface eth0 inet static\n")
    f.write("    address %s\n" % (address))
    f.write("    netmask %s\n" % (netmask))
    if gateway:
        f.write("    gateway %s\n" % (gateway))
    for x,y,z in data:
        f.write("\n")
        f.write("iface %s inet static\n" % (x))
        f.write("    address %s\n" % y)
        f.write("    netmask %s\n" % z)
    for x,y,z,g in data6:
        f.write("\n")
        f.write("iface %s inet6 static\n" % (x))
        f.write("    address %s\n" % y)
        f.write("    netmask %s\n" % z)
        if g:
            f.write("    gateway %s\n" % g)
    f.write("\n")
    f.write("".join(origlines))
    f.close()

def buildCentOSNetworkConfigFiles(config):
    vsubnets = config.lookup(["NETWORK_CONFIG", "VLANS"], None)
    if vsubnets:
        for v in vsubnets:
            if v == "RSPAN": continue
            vid = config.lookup(["NETWORK_CONFIG", "VLANS", v, "ID"])
            ipaddr = config.lookup(["NETWORK_CONFIG", "VLANS", v, "ADDRESS"], None)
            if ipaddr:
                netmask = config.lookup(["NETWORK_CONFIG", "VLANS", v, "SUBNETMASK"])
                filename = "ifcfg-eth0.%s" % (vid)
                sys.stdout.write("Creating config file: %s...\n" % (filename))
                f = file(filename, "w")
                f.write("DEVICE=eth0.%s\n" % (vid))
                f.write("BOOTPROTO=static\n")
                f.write("IPADDR=%s\n" % (ipaddr))
                f.write("NETMASK=%s\n" % (netmask))
                f.write("ONBOOT=yes\n")
                f.write("TYPE=Ethernet\n")
                f.write("VLAN=yes\n")
                f.close()

def makeConfigFiles(config, debian):
    # Read in all machine config files
    hcfbase = config.lookup("MACHINE_CONFIGS", None)
    machines = config.lookup("HOST_CONFIGS").keys()

    testpeers = config.lookup("TTCP_PEERS", None)
    sharedhosts = config.lookup("SHARED_HOSTS", None)
    buildDHCPFile(config,machines,testpeers,sharedhosts)
    buildDHCP6File(config,machines,testpeers,sharedhosts)
    buildHostsFile(config,machines,testpeers,sharedhosts)
    buildConserverClientFile(config)
    buildConserverServerFile(config,machines,testpeers,sharedhosts)

    if not debian:
        buildCentOSNetworkConfigFiles(config)
    else:
        buildDebianNetworkConfigFile(config)

    sys.stdout.write("Done.\n")
    return 0

def makeSwitchConfig(config, machine):
    switches = config.lookup("NETSWITCHES").keys()
    if machine in switches:
        makeSwitchConfigForSwitch(config, machine)
    else:
        makeSwitchConfigForMachine(config, machine)

def makeSwitchConfigForSwitch(config, switch):
    for m in sorted(config.lookup("HOST_CONFIGS").keys()):
        makeSwitchConfigForMachine(config, m, filterSwitch=switch)

def makeSwitchConfigForMachine(config, machine, filterSwitch=None):
    primaryPort = config.lookupHost(machine, "NETPORT", None)
    if not primaryPort:
        return
    ports = {primaryPort: "NPRI"}
    nics = config.lookupHost(machine, "NICS", {})
    for n in nics.keys():
        net = config.lookupHost(machine, ["NICS", n, "NETWORK"], None)
        port = config.lookupHost(machine, ["NICS", n, "NETPORT"], None)
        if port and net in ["NPRI", "NSEC", "IPRI", "ISEC"]:
            ports[port] = net
    switches = {}
    for p in ports.keys():
        m = re.match("^(.*)-(\d+)/(\d+)$", p)
        if m:
            switch = m.group(1)
            unit = m.group(2)
            port = m.group(3)
            if not switches.has_key(switch):
                switches[switch] = {}
            pn = portName(config, switch, unit, port)
            if pn:
                switches[switch][pn] = ports[p]
    if not filterSwitch:
        for s in sorted(switches.keys()):
            print "\n### %s (%s) ###\n" % (s, config.lookup(["NETSWITCHES", s, "ADDRESS"], ""))
            for p in sorted(switches[s].keys()):
                portConfig(config,s,p,switches[s][p])
    elif switches.has_key(filterSwitch):
        print "\n### %s (%s) ###\n" % (filterSwitch, config.lookup(["NETSWITCHES", filterSwitch, "ADDRESS"], ""))
        for p in sorted(switches[filterSwitch].keys()):
            portConfig(config,filterSwitch,p,switches[filterSwitch][p])

def portConfig(config,switch,port,network):
    swtype = config.lookup(["NETSWITCHES", switch, "TYPE"], None)
    if not swtype:
        return
    allvlannames = sorted(config.lookup(["NETWORK_CONFIG","VLANS"], {}).keys())
    allvlans = [config.lookup(["NETWORK_CONFIG","VLANS", x, "ID"]) for x in config.lookup(["NETWORK_CONFIG","VLANS"], {}).keys()]
    allvlans.append(config.lookup(["NETWORK_CONFIG","DEFAULT", "VLAN"]))
    allvlans.append(config.lookup(["NETWORK_CONFIG","SECONDARY", "VLAN"]))
    allvlans.append("1")
    if network == "NPRI":
        nativevlan = config.lookup(["NETWORK_CONFIG","DEFAULT", "VLAN"])
    elif network == "NSEC":
        nativevlan = config.lookup(["NETWORK_CONFIG","SECONDARY", "VLAN"])
    else:
        nativevlan = config.lookup(["NETWORK_CONFIG","VLANS", network, "ID"])
    vlanstoadd = [config.lookup(["NETWORK_CONFIG","VLANS", x, "ID"]) for x in
        allvlannames if x not in ("NPRI", "NSEC", "IPRI", "ISEC") and x in config.lookup(["NETWORK_CONFIG","VLANS"], {}).keys()
        ]
    vlanstoremove = [x for x in allvlans if x != nativevlan and x not in vlanstoadd]
    if swtype == "HP6120XG":
        print "vlan %s untagged %s" % (nativevlan, port)
        for v in vlanstoadd:
            print "vlan %s tagged %s" % (v, port)
        for v in vlanstoremove:
            print "no vlan %s untagged %s" % (v, port)
    elif swtype in ("DellM6348", "DellPC8024", "DellPC62xx", "DellM6348v5"):
        print "interface %s" % port
        print "switchport mode general"
        print "switchport general pvid %s" % nativevlan
        print "switchport general allowed vlan add %s untagged" % nativevlan
        print "switchport general allowed vlan add %s tagged" % ",".join(vlanstoadd)
        print "switchport general allowed vlan remove %s" % ",".join(vlanstoremove)
        print "spanning-tree portfast"
        print "mtu 9216"
        print "exit"
    elif swtype in ("CiscoC3750G", "CiscoC2960X"):
        print "interface %s" % port
        if swtype in ("CiscoC3750G"):
            print "switchport trunk encapsulation dot1q"
        print "switchport mode trunk"
        print "switchport trunk native vlan %s" % nativevlan
        print "switchport trunk allowed vlan add %s" % nativevlan
        print "switchport trunk allowed vlan add %s" % ",".join(vlanstoadd)
        print "switchport trunk allowed vlan remove %s" % ",".join(vlanstoremove)
        print "spanning-tree portfast trunk"
        print "exit"
    if swtype == "FujitsuBX600":
        print "interface %s" % port
        print "mtu 9216"
        print "switchport allowed vlan add %s" % nativevlan
        print "no switchport tagging %s" % nativevlan
        print "switchport native vlan %s" % nativevlan
        for v in vlanstoadd:
            print "switchport allowed vlan add tagged %s" % v
            print "switchport tagging %s" % v
        for v in vlanstoremove:
            print "switchport allowed vlan remove %s" % v
        print "exit"
    if swtype == "FujitsuBX900":
        print "interface %s" % port
        print "mtu 9216"
        print "switchport allowed vlan add %s" % nativevlan
        print "switchport native vlan %s" % nativevlan
        for v in vlanstoadd:
            print "switchport allowed vlan add tagged %s" % v
        for v in vlanstoremove:
            print "switchport allowed vlan remove %s" % v
        print "exit"
    
    

def portName(config, switch, unit, port):
    swtype = config.lookup(["NETSWITCHES", switch, "TYPE"], None)
    if not swtype:
        return None
    if swtype == "HP6120XG":
        return port
    elif swtype == "DellM6348":
        return "GigabitEthernet %s/0/%s" % (unit, port)
    elif swtype == "DellPC62xx":
        return "ethernet %s/g%s" % (unit, port)
    elif swtype == "DellPC8024":
        return "TenGigabitEthernet %s/0/%s" % (unit, port)
    elif swtype in ("CiscoC3750G", "CiscoC2960X"):
        return "GigabitEthernet %s/0/%s" % (unit, port)
    elif swtype == "FujitsuBX600":
        return "0/%s" % (port)
    elif swtype == "FujitsuBX900":
        return "%s/0/%s" % (config.lookup(["NETSWITCHES", switch, "PORTPREFIX"]), port)

def routerInterfaceConfig(config):
    ifs = []
    ifs6 = []

    natVLANs = config.lookup(["ROUTER","NAT"],"").split(",")

    iftext = """
iface lo inet loopback

iface eth0 inet static
    address %s
    netmask %s
    gateway %s
    
""" % (config.lookup(["ROUTER", "VM_ADDRESS"]), config.lookup(["NETWORK_CONFIG", "DEFAULT", "SUBNETMASK"]), config.lookup(["NETWORK_CONFIG", "DEFAULT", "GATEWAY"]))

    ifs6.append(("eth0", config.lookup(["NETWORK_CONFIG", "DEFAULT", "GATEWAY6"]), config.lookup(["NETWORK_CONFIG", "DEFAULT", "SUBNETMASK6"])))
    ifs6.append(("eth0.%s" % config.lookup(["NETWORK_CONFIG", "SECONDARY", "VLAN"]), config.lookup(["NETWORK_CONFIG", "SECONDARY", "GATEWAY6"]), config.lookup(["NETWORK_CONFIG", "SECONDARY", "SUBNETMASK6"])))

    if "NSEC" in natVLANs:
        ifs.append(("eth0.%s" % config.lookup(["NETWORK_CONFIG", "SECONDARY", "VLAN"]), config.lookup(["NETWORK_CONFIG", "SECONDARY", "GATEWAY"]), config.lookup(["NETWORK_CONFIG", "SECONDARY", "SUBNETMASK"])))

    for v in config.lookup(["NETWORK_CONFIG", "VLANS"]).keys():
        if v in natVLANs:
            ifs.append(("eth0.%s" % config.lookup(["NETWORK_CONFIG", "VLANS", v, "ID"]), config.lookup(["NETWORK_CONFIG", "VLANS", v, "GATEWAY"]), config.lookup(["NETWORK_CONFIG", "VLANS", v,  "SUBNETMASK"])))

    for v in config.lookup(["NETWORK_CONFIG", "VLANS"]).keys():
        if config.lookup(["NETWORK_CONFIG", "VLANS", v, "GATEWAY6"], None):
            ifs6.append(("eth0.%s" % config.lookup(["NETWORK_CONFIG", "VLANS", v, "ID"]), config.lookup(["NETWORK_CONFIG", "VLANS", v, "GATEWAY6"]), config.lookup(["NETWORK_CONFIG", "VLANS", v,  "SUBNETMASK6"])))

    autoifs = ["lo", "eth0"]

    for (intf, addr, subnetmask) in ifs:
        if intf not in autoifs:
            autoifs.append(intf)
        iftext += """iface %s inet static
    address %s
    netmask %s

""" % (intf, addr, subnetmask)

    for (intf, addr, subnetmask) in ifs6:
        if intf not in autoifs:
            autoifs.append(intf)

        iftext += """iface %s inet6 static
    address %s
    netmask %s

""" % (intf, addr, subnetmask)

    iftext = "auto %s\n\n%s" % (" ".join(autoifs), iftext)

    return iftext

def routerAdvertisementConfig(config):
    ifs6 = []
    
    radvdtext = ""

    ifs6.append(("eth0", config.lookup(["NETWORK_CONFIG", "DEFAULT", "SUBNET6"]), config.lookup(["NETWORK_CONFIG", "DEFAULT", "SUBNETMASK6"]), False))
    ifs6.append(("eth0.%s" % config.lookup(["NETWORK_CONFIG", "SECONDARY", "VLAN"]), config.lookup(["NETWORK_CONFIG", "SECONDARY", "SUBNET6"]), config.lookup(["NETWORK_CONFIG", "SECONDARY", "SUBNETMASK6"]),False))

    for v in config.lookup(["NETWORK_CONFIG", "VLANS"]).keys():
        if config.lookup(["NETWORK_CONFIG", "VLANS", v, "GATEWAY6"], None):
            ifs6.append(("eth0.%s" % config.lookup(["NETWORK_CONFIG", "VLANS", v, "ID"]), config.lookup(["NETWORK_CONFIG", "VLANS", v, "SUBNET6"]), config.lookup(["NETWORK_CONFIG", "VLANS", v,  "SUBNETMASK6"]),v=="DH6"))

    for (intf, net, subnetmask, managed) in ifs6:
        if managed:
            managedText = "on"
        else:
            managedText = "off"
        radvdtext += """interface %s {
    IgnoreIfMissing on;
    AdvSendAdvert on;
    AdvOtherConfigFlag on;
    AdvDefaultLifetime 1800;
    AdvLinkMTU 0;
    AdvCurHopLimit 64;
    AdvReachableTime 0;
    MaxRtrAdvInterval 600;
    MinRtrAdvInterval 198;
    AdvDefaultPreference medium;
    AdvRetransTimer 0;
    AdvManagedFlag %s;
    prefix %s/%s {
        AdvPreferredLifetime 604800;
        AdvAutonomous on;
        AdvOnLink on;
        AdvValidLifetime 2592000;
    };
};

""" % (intf, managedText, net, subnetmask)

    return radvdtext

def setupRouter(config):
    xenrt.TEC().logdir = xenrt.resources.LogDirectory()
    hostAddr = config.lookup(["ROUTER", "HOST_ADDRESS"])
    password = config.lookup(["ROUTER", "HOST_PASSWORD"])
    site = config.lookup("XENRT_SITE")

    machine = xenrt.PhysicalHost("RouterHost", ipaddr = hostAddr)
    place = xenrt.GenericHost(machine)
    place.password = password
    place.checkVersion()
    host = xenrt.lib.xenserver.hostFactory(place.productVersion)(machine, productVersion=place.productVersion)
    place.populateSubclass(host)
    host.existing()
    distro = "debian60"
    if isinstance(host, xenrt.lib.xenserver.ClearwaterHost):
        distro = "debian70"
    g = host.createBasicGuest(distro, arch="x86-64", name="Router (%s)" % site)
    g.execguest("apt-get install -y --force-yes radvd vlan")

    ifFile = xenrt.TEC().tempFile()
    f = file(ifFile, "w")
    f.write(routerInterfaceConfig(config))
    f.close()
    g.sftpClient().copyTo(ifFile, "/etc/network/interfaces")
    
    radvdFile = xenrt.TEC().tempFile()
    f = file(radvdFile, "w")
    f.write(routerAdvertisementConfig(config))
    f.close()
    g.sftpClient().copyTo(radvdFile, "/etc/radvd.conf")

    if config.lookup(["ROUTER","NAT"],None):
        g.execguest("echo iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE >> /etc/rc.local")
        g.execguest("sed -i '/^exit 0$/d' /etc/rc.local")

    g.execguest("echo net.ipv4.ip_forward=1 >> /etc/sysctl.conf")
    g.execguest("echo net.ipv6.conf.all.forwarding=1 >> /etc/sysctl.conf")
    g.execguest("echo 8021q >> /etc/modules")
    g.mainip = config.lookup(["ROUTER", "VM_ADDRESS"])
    g.noguestagent = True
    g.reboot(skipsniff= True)

def setupStaticHost():
    # Setup logdir
    xenrt.TEC().logdir = xenrt.resources.LogDirectory()
    hostname = xenrt.TEC().lookup("RESOURCE_HOST_0")
    
    hc = xenrt.TEC().lookup("HOST_CONFIGS")
    allguests = [x for x in hc.keys() if hc[x].has_key("CONTAINER_HOST") and hc[x]["CONTAINER_HOST"] == hostname]
    vxshosts = [x for x in hc.keys() if hc[x].has_key("CONTAINER_HOST") and hc[x]["CONTAINER_HOST"] == hostname and hc[x]["GUEST_TYPE"] == "vxs"]
    guests = [x for x in hc.keys() if hc[x].has_key("CONTAINER_HOST") and hc[x]["CONTAINER_HOST"] == hostname and hc[x]["GUEST_TYPE"] != "vxs"]


    for g in allguests:
        xenrt.GEC().dbconnect.jobctrl("borrow", [g, "-f"])
    

    # Install the host

    host = xenrt.lib.xenserver.createHost(productVersion=xenrt.TEC().lookup(['HOST_CONFIGS', hostname, "PRODUCT_VERSION"]), version=xenrt.TEC().lookup(['HOST_CONFIGS', hostname, "INPUTDIR"]))

    for i in ["EXPORT_ISO_NFS", "EXPORT_ISO_NFS_STATIC"]: 
        sr = xenrt.lib.xenserver.ISOStorageRepository(host, "XenRT ISOs")
        server, path = xenrt.TEC().lookup(i).split(":")
        sr.create(server, path)
        sr.scan()

    # Set up a separate VDI to hold the console logs

    if host.lookup("CONSOLE_VDI_SIZE", None):
        vdiuuid = host.createVDI(int(host.lookup("CONSOLE_VDI_SIZE")) * xenrt.GIGA, name="consoles")
        dom0uuid = host.getMyDomain0UUID()
        cli = host.getCLIInstance()
        vbduuid = cli.execute("vbd-create", "vdi-uuid=%s vm-uuid=%s device=0" % (vdiuuid, dom0uuid)).strip()
        cli.execute("vbd-plug", "uuid=%s" % vbduuid)
        device=host.genParamGet("vbd", vbduuid, "device")
        host.execdom0("sed -i /logconsole/d /etc/rc.local")
        host.execdom0("mkdir /consoles")
        host.execdom0("mkfs.ext3 /dev/%s" % device)

        host.execdom0("echo sleep 60 >> /etc/rc.local")
        host.execdom0("echo \"xe vbd-unplug uuid=%s; xe vbd-plug uuid=%s\" >> /etc/rc.local" % (vbduuid, vbduuid))
        host.execdom0("echo mount /dev/%s /consoles >> /etc/rc.local" % device)
        host.execdom0("echo rm -f /consoles/console.*.log >> /etc/rc.local")
        host.execdom0("echo xenstore-write /local/logconsole/@ /consoles/console.%d.log >> /etc/rc.local")

        # And reboot for the rc.local changes to take effect

        host.reboot()
    else:
        # Disable console logging
        host.execdom0("sed -i /logconsole/d /etc/rc.local")
        host.reboot()

    # Configure the networking

    host.createNetworkTopology(host.lookup("NETCFG"))

    # Configure the storage

    storage = host.lookup("STORAGE")
    if storage.startswith("nfs://"):
        (server, path) = storage[6:].split(":")
        mount = xenrt.rootops.MountNFSv3(storage[6:])
        xenrt.rootops.sudo("rm -rfv %s/*" % mount.getMount())
        mount.unmount()
        sr = xenrt.lib.xenserver.NFSStorageRepository(host, "Default Storage")
        sr.create(server, path)
        p = host.minimalList("pool-list")[0]
        host.genParamSet("pool", p, "default-SR", sr.uuid)

    # Configre the VMs


    for v in vxshosts:
        cpus = int(xenrt.TEC().lookupHost(v, "CPUS", "2"))
        memory = int(xenrt.TEC().lookupHost(v, "RAM", "4096"))
        g = host.createGenericEmptyGuest(memory=memory, vcpus=cpus, name=v)
        g.createVIF(bridge="NPRI", mac=xenrt.TEC().lookupHost(v, "MAC_ADDRESS"))
        i = 1
        while xenrt.TEC().lookup(["HOST_CONFIGS", v, "NICS", "NIC%d" % i], None):
            g.createVIF(bridge=xenrt.TEC().lookup(["HOST_CONFIGS", v, "NICS", "NIC%d" % i, "NETWORK"]), mac=xenrt.TEC().lookup(["HOST_CONFIGS", v, "NICS", "NIC%d" % i, "MAC_ADDRESS"]))
            i += 1
        disksize = int(xenrt.TEC().lookup(["HOST_CONFIGS", v, "DISK_SIZE"], "50")) * xenrt.GIGA
        g.createDisk(sizebytes=disksize, sruuid="DEFAULT", bootable=True)
        g.paramSet("HVM-boot-params-order", "nc")
        xenrt.GEC().dbconnect.jobctrl("return", [v])

    for g in guests:
        try:
            setupGuest(host, g)
            xenrt.GEC().dbconnect.jobctrl("return", [g])
        except:
            xenrt.GEC().dbconnect.jobctrl("mstatus", [g, "offline"])
    
def setupStaticGuest(guestname):
    details = xenrt.GEC().dbconnect.jobctrl("machine", [guestname])
    maxage = xenrt.TEC().lookup("MAX_GUEST_AGE", None)
    for x in details.keys():
        if maxage and x == "INSTALL_TIME" and (int(details[x]) + int(maxage)) >= xenrt.timenow():
            raise xenrt.XRTError("Not installing as machine has been recently installed")
        if x == "STATUS" and details[x] != "idle":
            raise xenrt.XRTError("Could not provision machine %s because it is not idle" % guestname)
        if x == "LEASEUSER" and details[x] != os.environ['USER']:
            raise xenrt.XRTError("Could not provision machine %s becuase it is borrowed by %s" % (guestname, details[x]))
    xenrt.GEC().dbconnect.jobctrl("borrow", [guestname, "-f"])
    try:
        container = xenrt.TEC().lookupHost(guestname, "CONTAINER_HOST")
        machine = xenrt.PhysicalHost(container)
        place = xenrt.GenericHost(machine)
        place.findPassword()
        place.checkVersion()
        host = xenrt.lib.xenserver.hostFactory(place.productVersion)(machine, productVersion=place.productVersion)
        place.populateSubclass(host)
        host.existing(doguests=False)
        setupGuest(host, guestname)
    except:
        xenrt.GEC().dbconnect.jobctrl("mstatus", [guestname, "offline"])
        raise
    finally:
        xenrt.GEC().dbconnect.jobctrl("return", [guestname])

def setupGuest(host, guestname):
    cpus = None
    if guestname in host.listGuests():
        guest = host.guestFactory()(guestname)
        guest.existing(host)
        guest.uninstall()
    if xenrt.TEC().lookupHost(guestname, "CPUS", None):
        cpus = int(xenrt.TEC().lookupHost(guestname, "CPUS"))
    memory = None
    if xenrt.TEC().lookupHost(guestname, "RAM", None):
        memory = int(xenrt.TEC().lookupHost(guestname, "RAM"))
    disksize = None
    if xenrt.TEC().lookupHost(guestname, "DISK_SIZE", None):
        disksize = int(xenrt.TEC().lookupHost(guestname, "DISK_SIZE")) * xenrt.GIGA
    arch = xenrt.TEC().lookupHost(guestname, "ARCH", "x86-32")
    guest = host.createBasicGuest(xenrt.TEC().lookupHost(guestname, "GUEST_TYPE"),
                                  vcpus=cpus,
                                  memory=memory,
                                  name=guestname,
                                  arch=arch,
                                  primaryMAC=xenrt.TEC().lookupHost(guestname, "MAC_ADDRESS"),
                                  reservedIP=xenrt.TEC().lookupHost(guestname, "HOST_ADDRESS"),
                                  sr="Default Storage")
    guest.disableFirewall()
    guest.disableIPv6(reboot=False)
    if guest.windows:
        guest.xmlrpcUnpackTarball("%s/sigcheck.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")
        guest.xmlrpcExec("echo %s > c:\\winversion.txt" % guest.distro)
    guest.shutdown()
    guest.snapshot("clean")
    guest.start()
    xenrt.GEC().dbconnect.jobctrl("mupdate", [guestname, "INSTALL_TIME", str(xenrt.timenow())])
