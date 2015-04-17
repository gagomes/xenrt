import libperf
import xenrt
import random, string, time

# Expects the sequence file to set up two VMs, called 'endpoint0' and 'endpoint1'
class TCNetworkThroughputPointToPoint(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCNetworkThroughputPointToPoint")

    def findGuests(self):
        self.pool = self.getDefaultPool()
        if self.pool:
            self.host = self.pool.master
            self.hosts = self.pool.getHosts()
        else:
            #self.host already defined in libperf.initialiseHostList()
            self.hosts = [self.host]
        self.log(None, "hosts1=%s" % (self.hosts,))

        # any other remaining hosts not in any pools
        hostlist = xenrt.TEC().registry.hostList()
        self.log(None, "hostlist=%s" % (hostlist,))
        for h in hostlist:
            host = xenrt.TEC().registry.hostGet(h)
            if host not in self.hosts:
                self.hosts += [host]
        self.log(None, "hosts2=%s" % (self.hosts,))

        self.guests = []
        for host in self.hosts:
            self.guests = self.guests + host.guests.values()
        self.log(None, "guests=%s" % (self.guests,))

    def getGuestOrHostFromName(self, name):
        for guest in self.guests:
            if guest.getName() == name:
                self.log(None, "name=%s -> guest=%s" % (name, guest))
                return guest
        host = xenrt.TEC().registry.hostGet(name)
        self.log(None, "name=%s -> host=%s" % (name, host))
        if host:
            return host
        raise xenrt.XRTError("Failed to find guest or host with name %s" % (name,))

    def parseArgs(self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs(self, arglist)

        self.log(None, "parseArgs:arglist=%s" % (arglist,))
        self.interval = libperf.getArgument(arglist, "interval", int, 1)
        self.threads  = libperf.getArgument(arglist, "threads",  int, 1)
        self.duration = libperf.getArgument(arglist, "duration", int, 30)
        self.protocol = libperf.getArgument(arglist, "protocol", str, "tcp")
        self.gro      = libperf.getArgument(arglist, "gro", str, "default")
        self.dopause  = libperf.getArgument(arglist, "pause", str, "off")

        self.postinstall = libperf.getArgument(arglist, "postinstall", str, None) # comma-separated list of guest function names
        self.postinstall = [] if self.postinstall is None else self.postinstall.split(",")

        # Optionally, the sequence file can specify which eth device to use in each endpoint
        self.e0devstr = libperf.getArgument(arglist, "endpoint0dev", str, None)
        self.e1devstr = libperf.getArgument(arglist, "endpoint1dev", str, None)
        self.e0dev = None
        self.e1dev = None

        # Optionally, the sequence file can specify IP addresses to use in each endpoint
        self.e0ip = libperf.getArgument(arglist, "endpoint0ip", str, None)
        self.e1ip = libperf.getArgument(arglist, "endpoint1ip", str, None)

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)

        # Populate self.guests
        self.findGuests()

        self.log(None, "prepare:arglist=%s" % (arglist,))
        # Get the two communication endpoints
        e0 = libperf.getArgument(arglist, "endpoint0", str, None)
        e1 = libperf.getArgument(arglist, "endpoint1", str, None)
        self.log(None, "endpoints: e0=%s, e1=%s" % (e0,e1))
        if not e0 or not e1:
            raise xenrt.XRTError("Failed to find an endpoint")
        self.endpoint0 = self.getGuestOrHostFromName(e0)
        self.endpoint1 = self.getGuestOrHostFromName(e1)

        # Postinstall hook for guests
        for g in self.guests:
            xenrt.TEC().logverbose("executing post-install functions %s for guest %s" % (self.postinstall, g))
            for p in self.postinstall:
                eval("g.%s()" % (p))

    def before_prepare(self, arglist=None):
        pass
        ## tag the ipv6 network to be used by VMs
        #self.host.genParamSet("network", self.ipv6_net, "other-config", "true", "xenrtvms")

    def runIperf(self, origin, origindev, dest, destdev, interval=1, duration=30, threads=1, protocol="tcp"):
        xenrt.TEC().logverbose("Running iperf from origin %s (dev %s) to dest %s (dev %s)" % (origin, origindev, dest, destdev))

        prot_switch = None
        if protocol == "tcp":   prot_switch = ""
        elif protocol == "udp": prot_switch = "-u"
        else: raise xenrt.XRTError("unknown protocol %s" % (protocol,))

        destIP = self.getIP(dest, destdev)
        xenrt.TEC().logverbose("destIP = %s" % (destIP))
        if destIP is None:
            raise xenrt.XRTError("couldn't get the IP address of the destination %s (dev %s)" % (dest, destdev))

        if dest.windows:
            dest.startIperf()

            # Run the client
            output = origin.xmlrpcExec("c:\\iperf %s -c %s -i %d -t %d -f m -P %d" % (prot_switch, destIP, interval, duration, threads), returndata=True)

            # Kill server
            dest.xmlrpcKillAll("iperf.exe")

        else:
            # Start server
            dest.execcmd("nohup iperf %s -s 0<&- &>/dev/null &" % (prot_switch,)) # should be implemented in startIperf()

            # Run the client
            output = origin.execcmd("iperf %s -c %s -i %d -t %d -f m -P %d" % (prot_switch, destIP, interval, duration, threads))

            # Kill server
            dest.execcmd("killall iperf || true")
            dest.execcmd("killall -9 iperf || true")

        # Check for error on client
        if output.find("connect failed") >= 0:
            xenrt.TEC().logverbose("output was '%s'" % (output,))
            raise xenrt.XRTError("iperf client couldn't connect to server")

        return output

    def hostOfEndpoint(self, endpoint):
        # Get the host object for this endpoint
        if isinstance(endpoint, xenrt.GenericGuest):
            return endpoint.host
        elif isinstance(endpoint, xenrt.GenericHost):
            return endpoint
        else:
            raise xenrt.XRTError("unrecognised endpoint %s with type %s" % (endpoint, type(endpoint)))

    def setIPAddress(self, endpoint, endpointdev, ip):
        if isinstance(endpoint, xenrt.GenericGuest):
            xenrt.TEC().logverbose("setIPAddress: guest endpoint %s has vifs %s" % (endpoint, endpoint.vifs))
            idx = [i for i,(dev,_,_,_) in enumerate(endpoint.vifs) if dev==('eth%d' % endpointdev)][0]
            xenrt.TEC().logverbose("setIPAddress: dev %s is at index %d in vifs" % (endpointdev, idx))
            (eth, bridge, mac, _) = endpoint.vifs[idx]
            # TODO support configuring static IP in Windows guests
            endpoint.execguest("ifconfig %s %s netmask 255.255.255.0" % (eth, ip))
            endpoint.vifs[idx] = (eth, bridge, mac, ip)
        elif isinstance(endpoint, xenrt.lib.xenserver.Host):
            raise xenrt.XRTError("setting IP on XenServer PIF is not yet implemented")
        elif isinstance(endpoint, xenrt.GenericHost):
            endpoint.execcmd("ifconfig %s %s netmask 255.255.255.0" % (endpoint.getNIC(endpointdev), ip))

    def getIP(self, endpoint, endpointdev=None):
        # If the device is specified then get the IP for that device
        if endpointdev is not None:
            xenrt.TEC().logverbose("getIP(%s, %s): endpointdev %s is not None" % (endpoint, endpointdev, endpointdev))
            if isinstance(endpoint, xenrt.GenericGuest):
                xenrt.TEC().logverbose("getIP(%s, %s): endpoint %s is a GenericGuest, endpoint.vifs = %s" % (endpoint, endpointdev, endpoint, endpoint.vifs))
                ip = [ip for (dev,br,mac,ip) in endpoint.vifs if dev==('eth%d' % endpointdev)][0]
            elif isinstance(endpoint, xenrt.lib.xenserver.Host):
                xenrt.TEC().logverbose("getIP(%s, %s): endpoint %s is a xenserver.Host" % (endpoint, endpointdev, endpoint))
                ip = endpoint.getNICAllocatedIPAddress(endpointdev)
            elif isinstance(endpoint, xenrt.GenericHost):
                xenrt.TEC().logverbose("getIP(%s, %s): endpoint %s is a GenericHost" % (endpoint, endpointdev, endpoint))
                ip = endpoint.execdom0("ifconfig %s | fgrep 'inet addr:' | awk '{print $2}' | awk -F: '{print $2}'" % (endpoint.getNIC(endpointdev))).strip()
        else:
            xenrt.TEC().logverbose("getIP(%s, %s): endpointdev %s is None, so getting IP of endpoint %s" % (endpoint, endpointdev, endpointdev, endpoint))
            ip = endpoint.getIP()
        xenrt.TEC().logverbose("getIP(%s, %s) returning %s" % (endpoint, endpointdev, ip))
        return ip

    # endpointdev is the (integer) assumedid of the device. We return the device name, e.g. 'eth0' or 'vmnic0'
    def nicdevOfEndpointDev(self, endpoint, endpointdev):
        assert isinstance(endpoint, xenrt.GenericHost)
        return endpoint.getNIC(endpointdev)

    def nicdev(self, endpoint):
        ip = self.getIP(endpoint, None)
        return self.nicdevOfIP(endpoint, ip)

    def nicdevOfIP(self, endpoint, ip):
        endpointHost = self.hostOfEndpoint(endpoint)

        # Get the device name and MAC address for a given IP address
        if endpointHost.productType == "esx":
            cmds = [
                "vmk=$(esxcfg-vmknic -l | fgrep '%s' | awk '{print $1}')" % (ip,),
                "portgroup=$(esxcli network ip interface list | grep -A 10 \"^$vmk\\$\" | fgrep \"Portgroup:\" | sed 's/^.*: //')",
                "vswitch=$(esxcli network vswitch standard portgroup list | grep \"^$portgroup \" | sed \"s/^$portgroup *//\" | awk '{print $1}')",
                "nic=$(esxcfg-vswitch -l | fgrep $vswitch | awk '{print $6}')",
                "echo $nic",
            ]
            cmd = "; ".join(cmds)
            return endpoint.execcmd(cmd).strip()
        else:
            cmd = "ifconfig |grep -B 1 '%s'|grep HWaddr|awk '{print $1}'" % (ip,)
            _dev = endpoint.execcmd(cmd).strip()
            dev = _dev.replace("xenbr","eth")
            dev = dev.replace("virbr","eth")
            return dev

    # endpoint is always a xenrt.GenericHost
    # endpointdev is the (integer) assumedid of the device, or None to use the default device
    def nicinfo(self, endpoint, endpointdev=None, key_prefix=""):
        assert isinstance(endpoint, xenrt.GenericHost)
        def map2kvs(ls):return map(lambda l: l.split("="), ls)
        def kvs2dict(prefix,kvs):return dict(map(lambda (k,v): ("%s%s" % (prefix, k.strip()), v.strip()), filter(lambda kv: len(kv)==2, kvs)))
        if endpointdev is None:
            dev = self.nicdev(endpoint)
        else:
            dev = self.nicdevOfEndpointDev(endpoint, endpointdev)
        endpointHost = self.hostOfEndpoint(endpoint)
        ethtool   = kvs2dict("ethtool:",   map2kvs(endpoint.execcmd("ethtool %s || true"    % (dev,)).replace(": ","=").split("\n")))
        ethtool_i = kvs2dict("ethtool-i:", map2kvs(endpoint.execcmd("ethtool -i %s || true" % (dev,)).replace(": ","=").split("\n")))
        ethtool_k = kvs2dict("ethtool-k:", map2kvs(endpoint.execcmd("ethtool -k %s || true" % (dev,)).replace(": ","=").split("\n")))
        ethtool_P = kvs2dict("ethtool-P:", map2kvs(endpoint.execcmd("ethtool -P %s || true" % (dev,)).replace(": ","=").split("\n")))
        ethtool_g_unsupp = endpoint.execcmd("ethtool -g %s" % (dev,), retval="code")
        if not ethtool_g_unsupp:
            g = map2kvs(endpoint.execcmd("ethtool -g %s" % (dev,)).replace("\t","").replace(":","=").split("\n"))
            ethtool_g = {}
            ethtool_g["ethtool-g:ringmaxRX"]         = g[2][1]
            ethtool_g["ethtool-g:ringmaxRXMini"]     = g[3][1]
            ethtool_g["ethtool-g:ringmaxRXJumbo"]    = g[4][1]
            ethtool_g["ethtool-g:ringmaxTX"]         = g[5][1]
            ethtool_g["ethtool-g:ringcurRX"]     = g[7][1]
            ethtool_g["ethtool-g:ringcurRXMini"] = g[8][1]
            ethtool_g["ethtool-g:ringcurRXJumbo"]= g[9][1]
            ethtool_g["ethtool-g:ringcurTX"]     = g[10][1]
        if "ethtool-P:Permanent address" in ethtool_P:
            pa = ethtool_P["ethtool-P:Permanent address"].strip().upper()
            xenrt.TEC().logverbose("ethtool -i output is: %s" % (ethtool_i))
            if ethtool_i["ethtool-i:driver"] in ["mlx4_en", "enic"] and pa == "00:00:00:00:00:00":
                # This has been observed on CentOS 6.5, despite it working fine on XenServer with the same driver version and firmware version
                xenrt.TEC().logverbose("Permanent address of %s is zero. Not sure why, but it's not a problem." % (dev,))
        if "ethtool-i:bus-info" in ethtool_i:
            pci_id = ethtool_i["ethtool-i:bus-info"][5:]
            dev_desc = endpoint.execcmd("lspci |grep '%s'" % (pci_id,)).split("controller: ")[1]
        else:
            dev_desc = None
        proc_sys_net = kvs2dict("", map2kvs(endpoint.execcmd("find /proc/sys/net/ 2>/dev/null | while read p; do echo \"$p=`head --bytes=256 $p`\"; done", timeout=600).split("\n")))
        sys_class_net = kvs2dict("", map2kvs(endpoint.execcmd("find /sys/class/net/*/* 2>/dev/null | while read p; do echo \"$p=`head --bytes=256 $p`\"; done", timeout=600).split("\n")))
        sys_devices = kvs2dict("", map2kvs(endpoint.execcmd("find /sys/devices/system/cpu/ 2>/dev/null | while read p; do echo \"$p=`head --bytes=256 $p`\"; done", timeout=600).split("\n")))
        try:
            xlinfo = kvs2dict("xlinfo:", map2kvs(endpoint.execcmd("xl info").replace(": ","=").split("\n")))
        except Exception, e: #if xl not available, use lscpu for bare metal machines
            xlinfo = {}
            if endpointHost.productType == "esx":
                self.log(None, "using vim-cmd: %s" % (e,))
                cpuinfo = kvs2dict("cpuinfo:", map2kvs(map(lambda x: x.strip(","), endpoint.execcmd("vim-cmd hostsvc/hosthardware | grep -A 6 'cpuInfo = '").replace(" = ","=").split("\n"))))
                # Note: not a 1-to-1 mapping between ESXi's notions and xl info's notions of these things.
                xlinfo["cpuinfo:numCpuPackages"] = cpuinfo["cpuinfo:numCpuPackages"] # number of physical sockets
                xlinfo["cpuinfo:numCpuCores"]    = cpuinfo["cpuinfo:numCpuCores"]
                xlinfo["cpuinfo:numCpuThreads"]  = cpuinfo["cpuinfo:numCpuThreads"]
                xlinfo["cpuinfo:numNumaNodes"]   = "unknown" # I can't find a way of working this out
            else:
                self.log(None, "using lscpu: %s" % (e,))
                lscpu = kvs2dict("lscpu:", map2kvs(endpoint.execcmd("lscpu").replace(": ","=").split("\n")))
                xlinfo["xlinfo:nr_cpus"] = lscpu["lscpu:CPU(s)"]
                xlinfo["xlinfo:cores_per_socket"] = lscpu["lscpu:Core(s) per socket"]
                xlinfo["xlinfo:threads_per_core"] = lscpu["lscpu:Thread(s) per core"]
                xlinfo["xlinfo:nr_nodes"] = lscpu["lscpu:NUMA node(s)"]

        if endpointHost.productType == "esx":
            # We need to extract at least the equivalent info to the "model name" and "cpu MHz"
            cpuinfo = kvs2dict("cpuinfo:", map(lambda x: map(lambda x: x.strip("\", "), x), map2kvs(endpoint.execcmd("vim-cmd hostsvc/hosthardware | grep -A 8 'cpuPkg = '").replace(" = ","=").split("\n"))))
            cpuinfo["cpuinfo:model name"] = cpuinfo["cpuinfo:description"]
            cpuinfo["cpuinfo:cpu MHz"] = int(cpuinfo["cpuinfo:hz"])/1000000
        else:
            cpuinfo = kvs2dict("cpuinfo:", map2kvs(endpoint.execcmd("cat /proc/cpuinfo").replace(": ","=").split("\n")))

        info = {}
        info["nic_physdev"] = dev
        info["nic_desc"] = dev_desc
        info.update(ethtool)
        info.update(ethtool_i)
        info.update(ethtool_k)
        info.update(ethtool_P)
        if not ethtool_g_unsupp:
            info.update(ethtool_g)
        info.update(proc_sys_net)
        info.update(sys_class_net)
        info.update(sys_devices)
        info.update(xlinfo)
        info.update(cpuinfo)
        return dict( [ (("%s%s" % (key_prefix, k)), v) for k,v in info.iteritems() ] )

    def iperfinfo(self, endpoint, key_prefix=""):
        info = {}
        if endpoint.windows:
            output = endpoint.xmlrpcExec("c:\\iperf --version", returndata=True, returnerror=False)
        else:
            output = endpoint.execcmd("iperf --version 2>&1 || true")
        ivs = output.strip().split("\n")[-1].split(" ")
        info["iperf_version"] = "%s %s %s" % (ivs[0], ivs[2], ivs[6])
        return dict( [ (("%s%s" % (key_prefix, k)), v) for k,v in info.iteritems() ] )

    def getHostname(self, endpoint):
        return endpoint.execcmd("hostname").strip()

    # Return the assumedid of the NIC on which this VIF is bridged
    def physicalDeviceOf(self, guest, endpointdev):
        assert isinstance(guest, xenrt.GenericGuest)
        if endpointdev is None:
            return None
        else:
            # Get the bridge this VIF is on
            br = [b for (dev,b,_,_) in guest.vifs if dev==('eth%d' % endpointdev)][0]
            xenrt.TEC().logverbose("physicalDeviceOf(%s, %s): guest.vifs = %s, so device %d is bridged on %s" % (guest, endpointdev, guest.vifs, endpointdev, br))

            # Convert bridge into the assumed id of the PIF
            assumedid = self.convertNetworkToAssumedid(guest.host, br)
            xenrt.TEC().logverbose("physicalDeviceOf(%s, %s): bridge '%s' corresponds to assumedid %d" % (guest, endpointdev, br, assumedid))
            return assumedid

    def getIssue(self, endpoint):
        issue = endpoint.execcmd("head -n 1 /etc/issue || true").strip()
        if issue == "":
            issue = "no-issue"
        return issue

    def rageinfo(self, info = {}):
        if isinstance(self.endpoint0, xenrt.GenericHost):
            info.update(self.nicinfo(self.endpoint0,self.e0dev,"host0:"))
            info.update(self.iperfinfo(self.endpoint0,"host0:"))
            info["vm0type"]  = "host"
            info["vm0arch"]  = "NULL"
            info["vm0ram"]   = "NULL"
            info["vm0vcpus"] = "NULL"
            info["vm0domid"] = "NULL"
            info["host0product"] = self.endpoint0.productType
            info["host0branch"]  = self.endpoint0.productVersion
            info["host0build"]   = self.endpoint0.productRevision
            info["host0issue"]   = self.getIssue(self.endpoint0)
            info["host0hostname"]= self.getHostname(self.endpoint0)
        elif isinstance(self.endpoint0, xenrt.GenericGuest):
            info.update(self.nicinfo(self.endpoint0.host,self.physicalDeviceOf(self.endpoint0, self.e0dev),"host0:"))
            info.update(self.iperfinfo(self.endpoint0,"host0:"))
            info["vm0type"]  = self.endpoint0.distro
            info["vm0arch"]  = self.endpoint0.arch
            info["vm0ram"]   = self.endpoint0.memory
            info["vm0vcpus"] = self.endpoint0.vcpus
            info["vm0domid"] = self.endpoint0.getDomid()
            info["host0product"] = self.endpoint0.host.productType
            info["host0branch"]  = self.endpoint0.host.productVersion
            info["host0build"]   = self.endpoint0.host.productRevision
            info["host0issue"]   = self.getIssue(self.endpoint0.host)
            info["host0hostname"]= self.getHostname(self.endpoint0.host)
        if isinstance(self.endpoint1, xenrt.GenericHost):
            info.update(self.nicinfo(self.endpoint1,self.e1dev,"host1:"))
            info.update(self.iperfinfo(self.endpoint1,"host1:"))
            info["vm1type"]  = "host"
            info["vm1arch"]  = "NULL"
            info["vm1ram"]   = "NULL"
            info["vm1vcpus"] = "NULL"
            info["vm1domid"] = "NULL"
            info["host1product"] = self.endpoint1.productType
            info["host1branch"]  = self.endpoint1.productVersion
            info["host1build"]   = self.endpoint1.productRevision
            info["host1issue"]   = self.getIssue(self.endpoint1)
            info["host1hostname"]= self.getHostname(self.endpoint1)
        elif isinstance(self.endpoint1, xenrt.GenericGuest):
            info.update(self.nicinfo(self.endpoint1.host,self.physicalDeviceOf(self.endpoint1, self.e1dev),"host1:"))
            info.update(self.iperfinfo(self.endpoint1,"host1:"))
            info["vm1type"]  = self.endpoint1.distro
            info["vm1arch"]  = self.endpoint1.arch
            info["vm1ram"]   = self.endpoint1.memory
            info["vm1vcpus"] = self.endpoint1.vcpus
            info["vm1domid"] = self.endpoint1.getDomid()
            info["host1product"] = self.endpoint1.host.productType
            info["host1branch"]  = self.endpoint1.host.productVersion
            info["host1build"]   = self.endpoint1.host.productRevision
            info["host1issue"]   = self.getIssue(self.endpoint1.host)
            info["host1hostname"]= self.getHostname(self.endpoint1.host)
        kvs = "\n".join(["%s=%s" % (k,info[k]) for k in info.keys()])
        self.log("rageinfo", kvs)

    def setup_gro(self):
        def setgro(endpoint):
            dev = self.nicdev(endpoint)
            if self.gro in ["on", "off"]:
                endpoint.execcmd("ethtool -K %s gro %s" % (dev, self.gro))
            elif self.gro in ["default", ""]:
	        self.log(None, "not overriding gro option for %s" % (dev,))
            else:
                raise xenrt.XRTError("unknown gro option: %s" % (self.gro,))
        if isinstance(self.endpoint0, xenrt.GenericHost):
            setgro(self.endpoint0)
        elif isinstance(self.endpoint0, xenrt.GenericGuest):
            setgro(self.endpoint0.host)
        if isinstance(self.endpoint1, xenrt.GenericHost):
            setgro(self.endpoint1)
        elif isinstance(self.endpoint1, xenrt.GenericGuest):
            setgro(self.endpoint1.host)

    def vmunpause(self):
        if isinstance(self.endpoint0, xenrt.GenericGuest):
            if self.endpoint0.getState() == "PAUSED": self.endpoint0.unpause()
        if isinstance(self.endpoint1, xenrt.GenericGuest):
            if self.endpoint1.getState() == "PAUSED": self.endpoint1.unpause()
        time.sleep(20)

    def vmpause(self):
        if isinstance(self.endpoint0, xenrt.GenericGuest):
            self.endpoint0.pause()
        if isinstance(self.endpoint1, xenrt.GenericGuest):
            self.endpoint1.pause()

    def breathe(self):
        # try to work out all paused endpoints
        for g in self.guests:
            try:
                g.unpause()
                g.checkReachable()
                g.pause()
            except Exception, e:
                self.log(None, "error while breathing: %s" % (e,))

    # 'network' can be a network friendly name (e.g. "NET_A") or a name (e.g. "NPRI") or a bridge name (e.g. "xenbr3")
    # We assume there is only one NIC on the network.
    def convertNetworkToAssumedid(self, host, network):
        return host.getAssumedId(network)

    def run(self, arglist=None):
        # unpause endpoints if paused
        self.vmunpause()
        # set up gro if required
        self.setup_gro()

        # Install iperf in both places if necessary
        if 'iperf_installed' not in self.endpoint0.__dict__.keys():
            self.endpoint0.installIperf(version="2.0.5")
            self.endpoint0.iperf_installed = True
        if 'iperf_installed' not in self.endpoint1.__dict__.keys():
            self.endpoint1.installIperf(version="2.0.5")
            self.endpoint1.iperf_installed = True

        # Get the device position (assumedid) for the devices to use:
        #  - For hosts, endpointdev is a network name, so convert this.
        #  - For guests, endpointdev is a number. Just use this.
        if self.e0devstr is None:
            self.e0dev = None
        else:
            if isinstance(self.endpoint0, xenrt.GenericHost):
                self.e0dev = self.convertNetworkToAssumedid(self.endpoint0, self.e0devstr)
            else:
                self.e0dev = int(self.e0devstr)
                xenrt.TEC().logverbose("endpoint0 %s has vifs %s" % (self.endpoint0, self.endpoint0.vifs))
                self.endpoint0.reparseVIFs() # ensure IP address is recorded in self.endpoint0.vifs
                xenrt.TEC().logverbose("endpoint0 %s has vifs %s" % (self.endpoint0, self.endpoint0.vifs))
        xenrt.TEC().logverbose("endpoint0 device is %s %s" % (self.e0dev, type(self.e0dev)))
        if self.e1devstr is None:
            self.e1dev = None
        else:
            if isinstance(self.endpoint1, xenrt.GenericHost):
                self.e1dev = self.convertNetworkToAssumedid(self.endpoint1, self.e1devstr)
            else:
                self.e1dev = int(self.e1devstr)
                xenrt.TEC().logverbose("endpoint1 %s has vifs %s" % (self.endpoint1, self.endpoint1.vifs))
                self.endpoint1.reparseVIFs() # ensure IP address is recorded in self.endpoint1.vifs
                xenrt.TEC().logverbose("endpoint1 %s has vifs %s" % (self.endpoint1, self.endpoint1.vifs))
        xenrt.TEC().logverbose("endpoint1 device is %s %s" % (self.e1dev, type(self.e1dev)))

        # Give IP addresses to the endpoints if necessary
        if self.e0ip:
            xenrt.TEC().logverbose("Setting IP address of %s (dev %s) to %s" % (self.endpoint0, self.e0dev, self.e0ip))
            self.setIPAddress(self.endpoint0, self.e0dev, self.e0ip)
        if self.e1ip:
            xenrt.TEC().logverbose("Setting IP address of %s (dev %s) to %s" % (self.endpoint1, self.e1dev, self.e1ip))
            self.setIPAddress(self.endpoint1, self.e1dev, self.e1ip)

        # Collect as much information as necessary for the rage importer
        xenrt.TEC().logverbose("Collecting metadata...")
        self.rageinfo()

        # Run some traffic in one direction
        output = self.runIperf(self.endpoint1, self.e1dev, self.endpoint0, self.e0dev, interval=self.interval, duration=self.duration, threads=self.threads, protocol=self.protocol)
        self.log("iperf.1to0", output)

        # Now run traffic in the reverse direction
        output = self.runIperf(self.endpoint0, self.e0dev, self.endpoint1, self.e1dev, interval=self.interval, duration=self.duration, threads=self.threads, protocol=self.protocol)
        self.log("iperf.0to1", output)

        # pause endpoints again to avoid interfering with measurements on other vms
        self.vmpause()

        # don't let vms in the paused state for too long
        # without network activity: windows vms tend to forget their ips
        self.breathe()

    def postRun(self):
        self.finishUp()
