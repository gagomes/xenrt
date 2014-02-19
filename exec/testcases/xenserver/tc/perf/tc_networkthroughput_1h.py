import xenrt, libperf, string, threading, time, traceback

class TCNetworkThroughputOneHost(libperf.PerfTestCase):
    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCNetworkThroughputOneHost")
        # Hosts.
        self.hostTx = None
        # Arrays of VMs for sending and receiving.
        self.vmTx = []
        self.hostTx = None
        self.network_backend = None
        self.use_irqbalance = None
        self.use_jumbo_frames = None
        self.use_gro = None
        self.use_lro = None
        self.trans_bridge = None
        self.num_vm_pairs = None
        self.comm_bridge = None
        self.dummy_bridge = None
        self.num_vm_vcpus = None
        self.vm_type = None

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)

        def readArg(name, convert, defaultValue):
            setattr(self, name, libperf.getArgument(arglist, name, convert, defaultValue))


        readArg("network_backend", str, "")     # bridge or openvswitch
        readArg("use_jumbo_frames", bool, False)
        readArg("comm_bridge", str, "xenbr5")
        readArg("trans_bridge", str, "xenbr6")
        readArg("dummy_bridge", str, "xenbr7")
        readArg("use_irqbalance", bool, False)  # only applicable to pre-Cowley
        readArg("use_gro", bool, False)
        readArg("use_lro", bool, False)
        readArg("num_host_runs", int, 10)
        readArg("host_run_time", int, 60)
        readArg("host_ping_count", int, 20)
        readArg("num_host_threads", int, 4)
        readArg("trySingleDom0Thread", bool, False)
        readArg("vm_type", str, "demo")         # other: "win7"
        readArg("num_vm_vcpus", int, 1)
        readArg("num_vm_runs", int, 10)
        readArg("vm_run_time", int, 60)
        readArg("num_vm_pairs", int, 4)         # 7 is max for q machines due to RAM limit
        readArg("trySingleVMPair", bool, False)
        readArg("num_vm_threads", int, 2)
        readArg("trySingleVMThread", bool, False)
        readArg("vm_ping_count", int, 20)
        # TODO: Find better name parameter and values, or get over this completely.
        self.where = libperf.getArgument (arglist, "run_on", str, "q") # Can also be "perf"
        self.setupHosts1()
        self.setupVMpairs()
        self.setupHosts2()

    def setupHosts1(self):
        self.hostTx = self.tec.gec.registry.hostGet(self.normalHosts[0])
        if self.where != "q":
            raise NotImplementedError("We can only run on q-machines at the moment.")
        else:
            self.hostTxN = int(self.hostTx.getName().replace('q',''))
            self.hostTxIP = "10.0.0.%d" % self.hostTxN
        TxSetupHostThread = SetupHostThread("T", self.hostTx, self.network_backend, self.use_irqbalance, self.use_jumbo_frames, self.use_gro, self.use_lro, self.trans_bridge)
        TxSetupHostThread.start()
        TxSetupHostThread.join()

    def setupHosts2(self):
        self.hostTx.execdom0("ifconfig %s %s" % (self.trans_bridge, self.hostTxIP))

    def setupVMpairs(self):
        # start create VM threads
        TxCreateVMts = []
        for i in range(self.num_vm_pairs):
            TxCreateVMt = CreateVMthread(self.hostTx, self.comm_bridge, self.trans_bridge, self.dummy_bridge, self.num_vm_vcpus, self.vm_type, "10.0.%d.%d" % (self.hostTxN, i))
            TxCreateVMts.append(TxCreateVMt)
            TxCreateVMt.start()
        # wait for all threads to complete, register created VMs
        for i in range(self.num_vm_pairs):
            TxCreateVMts[i].join()
            self.vmTx.append(TxCreateVMts[i].guest)
        # start VMs in order
        for i in range(self.num_vm_pairs):
            self.vmTx[i].start()
        # set IPs in case of demo VMs
        if self.vm_type == "demo":
            for i in range(self.num_vm_pairs):
                if self.where != "q":
                    raise NotImplementedError("We can only run on q-machines at the moment.")
                else:
                    self.vmTx[i].execguest("ifconfig eth1 10.0.%d.%d" % (self.hostTxN, i))
                if self.use_jumbo_frames:
                    self.vmTx[i].execguest("ifconfig eth1 mtu 9000 up")

    def run(self, arglist=None):
        xenrt.TEC().logverbose("Nothing to do here.")

    def postRun(self):
        self.finishUp()

class SetupHostThread(threading.Thread):
    def __init__(self, ref, host, network_backend, use_irqbalance, use_jumbo_frames, use_gro, use_lro, trans_bridge):
        threading.Thread.__init__(self)
        self.ref = ref
        self.host = host
        self.use_irqbalance = use_irqbalance
        self.use_jumbo_frames = use_jumbo_frames
        self.use_gro = use_gro
        self.use_lro = use_lro
        self.trans_bridge = trans_bridge
        self.network_backend = network_backend
        self.hostInstallCmd = "yum --disablerepo=citrix --enablerepo=base,updates install -y"
        rpmforgeFilename = "rpmforge-release-0.5.1-1.el5.rf.i386.rpm"
        self.rpmforgeSrc = "/home/xenrtd/xenrt/bin/%s" % rpmforgeFilename
        self.rpmforgeTarget = "/root/%s" % rpmforgeFilename

    def run(self):
        xenrt.TEC().logverbose("host%sx = %s" % (self.ref, self.host.getName()))
        if self.network_backend != "":
            self.host.execdom0("xe-switch-network-backend %s" % self.network_backend)
            self.host.reboot(timeout=1000)
        if self.use_irqbalance:
            self.host.execdom0("%s irqbalance && service irqbalance start" % self.hostInstallCmd)
        if self.use_jumbo_frames:
            net_uuid = self.host.execdom0("xe network-list bridge=%s params=uuid --minimal" % self.trans_bridge).strip()
            self.host.execdom0("xe network-param-set uuid=%s MTU=9000" % net_uuid)
            self.host.execdom0("for uuid in $(xe pif-list network-uuid=%s --minimal | sed 's/,/ /g'); do xe pif-unplug uuid=$uuid; xe pif-plug uuid=$uuid; done" % net_uuid)
        if self.use_gro or self.use_lro:
            time.sleep(30) # it is not clear whether this is neccessary
        if self.use_gro:
            self.host.execdom0("ethtool -K eth%d gro on" % int(self.trans_bridge[5:]))
        if self.use_lro:
            self.host.execdom0("ethtool -K eth%d lro on" % int(self.trans_bridge[5:]))
        self.host.execdom0("service iptables stop || true")
        sftp = self.host.sftpClient()
        sftp.copyTo(self.rpmforgeSrc, self.rpmforgeTarget)
        self.host.execdom0("rpm -Uhv %s; %s iperf" % (self.rpmforgeTarget, self.hostInstallCmd))

class CreateVMthread(threading.Thread):
    def __init__(self, host, comm_bridge, trans_bridge, dummy_bridge, num_vm_vcpus, vm_type, ip):
        threading.Thread.__init__(self)
        self.host = host
        self.comm_bridge = comm_bridge
        self.trans_bridge = trans_bridge
        self.dummy_bridge = dummy_bridge
        self.ip = ip
        self.num_vm_vcpus = num_vm_vcpus
        self.vm_type = vm_type
        self.winIperfFile = "/home/xenrtd/xenrt/bin/iperf.exe"
        self.winFpingFile = "/home/xenrtd/xenrt/bin/fping.exe"

    def run(self):
        # create guest
        if self.vm_type == "win7":
            xenrt.TEC().logverbose("Creating a Windows 7 guest on host %s" % self.host.getName())
            self.guest = self.host.createGenericWindowsGuest(distro="win7-x64", vcpus=self.num_vm_vcpus)
            # added for Boston MS3
            self.guest.unenlightenedShutdown()
            self.guest.poll('DOWN')
        else:
            xenrt.TEC().logverbose("Creating a generic Linux guest on bridge %s on host %s" % (self.comm_bridge, self.host.getName()))
            self.guest = self.host.createGenericLinuxGuest(start=False, bridge=self.comm_bridge, vcpus=self.num_vm_vcpus)
        # setup networking
        trans_vif_uuid = self.createVif(self.trans_bridge, "1")
        dummy_vif_uuid = self.createVif(self.dummy_bridge, "2")
        self.guest.start()
        if self.vm_type == "win7":
            self.guest.xmlrpcExec("netsh firewall set opmode disable")
            ipconfig_all = self.guest.xmlrpcExec("ipconfig /all", returndata=True)
            trans_mac = self.host.execdom0("xe vif-param-get param-name=MAC uuid=%s" % trans_vif_uuid).strip().upper().replace(":", "-")
            trans_lan = self.host.execdom0("echo \"%s\" | grep -i -B 4 \"%s\" | grep -o \"Local Area Connection [0-9]*\"" % (ipconfig_all, trans_mac)).strip()
            self.guest.xmlrpcExec("netsh interface ip set address \"%s\" static %s" % (trans_lan, self.ip))
            self.guest.xmlrpcSendFile(self.winIperfFile, "c:\\iperf.exe")
            self.guest.xmlrpcSendFile(self.winFpingFile, "c:\\fping.exe")
        else:
            self.guest.execguest("sed -i 's/http:\/\/.*\//http:\/\/archive.debian.org\//' /etc/apt/sources.list")
            self.guest.execguest("apt-get update")
            self.guest.execguest("apt-get install --force-yes -y iperf")
        self.guest.shutdown()

    def createVif(self, bridge, device):
        network_uuid = self.host.execdom0("xe network-list bridge=%s params=uuid --minimal" % bridge).strip()
        guest_uuid = self.guest.getUUID()
        vif_uuid = self.host.execdom0("xe vif-create network-uuid=%s vm-uuid=%s device=%s mac=%s" % (network_uuid, guest_uuid, device, xenrt.randomMAC())).strip()
        return vif_uuid
