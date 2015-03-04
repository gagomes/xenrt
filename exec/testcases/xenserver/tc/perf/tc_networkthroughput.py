import hashlib, libperf, libthread, re, string, threading, time, traceback, xenrt

# Current invariants:
# - one VM only sends traffic to one other VM on the other host

# List of potential future improvements:
# - replace sender VMs with dom0 (on sender host)
# - replace sender host with bare metal
# - consider creating a single VM, and cloning it (instead of creating lots in parallel)
# - consider removing trySingle-s to simplify the test case
# - make sure latency tests are accurate

# friendly VM type names to VM image names
win_vms = {"winxp" : "winxpsp3", "win7" : "win7-x64", "win2008" : "ws08r2sp1-x64"}
linux_vms = {"demo" : "demo", "etch" : "etch"}
all_vms = dict(win_vms.items() + linux_vms.items())

# a class representing the NIC
# - version is the driver version
# - desc contains the corresponding lspci line
class NIC(object):
  def __init__(self, eth, carrier, speed, driver, version, desc):
    self.eth = eth
    self.carrier = int(carrier) == 1
    try: self.speed = int(speed[:-4])
    except: self.speed = 0
    self.driver = driver
    self.version = version
    self.desc = desc
    self.bridge = "xenbr" + self.eth[3:]

  def __repr__(self):
    return "<%s, %d, %d, %s (%s)>" % \
      (self.eth, self.carrier, self.speed, self.driver, self.version)

# NICs representing the NIC choices for a single host
# - comm = network management interface
# - trans = transport interface
# - dummy = extra interface that guarantees good allocation of VIFs to netback
#   threads when there are 4 netbacks
class NICs(object):
  def __init__(self, comm, trans, dummy):
    self.comm = comm
    self.trans = trans
    self.dummy = dummy

class NICFinder(object):
  def __init__(self, host1, host2):
    self.host1 = host1
    self.host2 = host2

  def readAllNics(self, host):
    pciidToDesc = {}
    for pci in host.execdom0("lspci").strip().split("\n"):
      space = pci.find(" ")
      pciidToDesc[pci[:space]] = pci[space+1:]
    cmd = """
      cd /sys/class/net;
      for eth in `ls -d eth*`; do
        echo $eth;
        cat $eth/carrier;
        ethtool $eth | awk '$1 ~ "Speed" {print $2}';
        ethtool -i $eth | awk 'NR < 3 || NR == 4 {print $2}';
      done
    """
    cmd = re.sub('[ \n]+', ' ', cmd)
    out = host.execdom0(cmd).strip().split()
    nics = []
    fields = 6
    for i in range(0, len(out), fields):
      pciid = out[i+5][5:]
      if not pciid or pciid not in pciidToDesc.keys() or out[i+2]=="Unknown!":
        continue
      desc = pciidToDesc[pciid]
      params = out[i:i+fields-1]
      params.append(desc)
      nics.append(NIC(*params))
    return nics

  def filterNics(self, host, minSpeed = 10000, filterDesc = ""):
    """This function splits NICs into two exclusive groups, both of which only
    contain online NICs. The second group contains NIC with the specified
    minimum speed (in Mb/s), and contains the specified filterDesc in its
    description (as shown by lspci). All NICs are assumed to be connected
    through a switch supporting at least minSpeed. Eth0 is assumed to be the
    management interface."""
    selected, other = [], []
    for nic in self.readAllNics(host):
      if not nic.carrier: continue
      if nic.eth == "eth0": comm = nic; continue
      if nic.speed < minSpeed or nic.desc.find(filterDesc) == -1:
        other.append(nic)
      else: selected.append(nic)
    return comm, selected, other

  def findNICs(self, minSpeed = 10000, filterDesc = ""):
    driverToNics1 = {}
    comm1, selected1, other1 = self.filterNics(self.host1, minSpeed, filterDesc)
    comm2, selected2, other2 = self.filterNics(self.host2, minSpeed, filterDesc)
    for nic in selected1:
      if nic.driver not in driverToNics1: driverToNics1[nic.driver] = []
      driverToNics1[nic.driver].append(nic)
    for nic in selected2:
      if nic.driver in driverToNics1:
        trans1, trans2 = driverToNics1[nic.driver][0], nic
        break
    # maybe throw exception here if nothing is found
    nics1 = NICs(comm1, trans1, (selected1 + other1)[0])
    nics2 = NICs(comm2, trans2, (selected2 + other2)[0])
    return nics1, nics2

class TCNetworkThroughput(libperf.PerfTestCase):
  def __init__(self):
    libperf.PerfTestCase.__init__(self, "TCNetworkThroughput")
    # Hosts. (Initialisation here is not strictly required.)
    self.hostTx = None
    self.hostRx = None
    self.protocol = None
    self.host_iperf = None
    self.vm_iperf = None
    self.use_vlan = False
    self.vlan_name = None
    self.vlan_tag = None
    self.network_backend = None
    self.use_irqbalance = False
    self.use_jumbo_frames = False
    self.use_gro = False
    self.use_lro = False
    self.num_hosts = None
    self.hostTxIP = None
    self.hostRxIP = None
    self.num_vm_pairs = None
    self.num_vm_vcpus = None
    self.vm_type = None
    self.ip_v = None
    self.hostRxN = None
    self.hostTxN = None
    self.host_iperf_buffer = None
    self.num_host_runs = None
    self.num_host_threads = None
    self.trySingleDom0Thread = False
    self.host_run_time = None
    self.udp_target = None
    self.host_ping_count = None
    self.num_vm_runs = None
    self.num_vm_threads = None
    self.trySingleVMPair = False
    self.vm_iperf_buffer = None
    self.trySingleVMThread = None
    self.vm_run_time = None
    self.vm_ping_count = None
    self.prebuilt_vms = []
    self._threads_to_execPostRun = []
    # Arrays of VMs for sending and receiving.
    self.vmTx = []
    self.vmRx = []

  def prepare(self, arglist=None):
    self.basicPrepare(arglist)
    ra = self.readArg
    ra("num_hosts", int, 2, [1]) # not sure if 1 host is currently supported
    ra("network_backend", str, "", ["bridge", "openvswitch"])
    ra("protocol", str, "tcp", ["udp"])
    ra("udp_target", int, 10)          # in Gbps
    ra("use_jumbo_frames", bool, False) # only supported for dom0 and demo VM
    ra("use_vlan", bool, False)
    ra("vlan_name", int, "vlannetwork")
    ra("vlan_tag", int, 101)
    ra("use_irqbalance", bool, False)  # only applicable to pre-Cowley
    ra("use_gro", bool, False) # only supported for dom0
    ra("use_lro", bool, False) # only supported for dom0
    ra("num_host_runs", int, 10) # dom0 runs
    ra("host_run_time", int, 60) # in seconds
    ra("host_ping_count", int, 20)
    ra("num_host_threads", int, 4) # iPerf threads
    ra("trySingleDom0Thread", bool, False) # in addition, try with single iPerf thread
    ra("vm_type", str, "demo", all_vms.keys())
    ra("num_vm_vcpus", int, 1)
    ra("num_vm_runs", int, 10)
    ra("vm_run_time", int, 60)
    ra("num_vm_pairs", int, 4)         # 7 is max for q machines due to RAM limit
    ra("trySingleVMPair", bool, False) # in addition, try with single VM pair
    ra("num_vm_threads", int, 2) # iPerf threads per VM pair
    ra("trySingleVMThread", bool, False) # in addition, try with single iPerf thread
    ra("vm_ping_count", int, 20)
    ra("host_iperf_window", int, -1)
    ra("host_iperf_buffer", int, -1)
    ra("vm_iperf_window", int, -1)
    ra("vm_iperf_buffer", int, -1)
    ra("ip_v", int, 4, [6])

    for arg in arglist:
        l = string.split(arg, "=", 1)
        if l[0] == "prebuilt_vms":
            self.prebuilt_vms = l[1].split(',')
            xenrt.TEC().logverbose("Listing prebuilt VMs: %s" % self.prebuilt_vms)

    if self.protocol == "udp":
      self.host_iperf_window = 524288
      self.vm_iperf_window = 524288
      self.host_iperf.buffer = 63  # when UDP, use largest buffer supported by UDP
      self.vm_iperf.buffer = 63    # when UDP, use largest buffer supported by UDP
    self.ipv6_prefix = "fd65:0e5f:7c2d:5b70"
    self.support_files = self.getPathToDistFile(subdir="support-files")
    self.setupHosts1()
    self.setupVMpairs()
    self.setupHosts2()

  def setupHosts1(self):
    self.setupHostGeneric(0, "T", False)                               # configure basic hostTx vars; don't start thread
    self.setupHostGeneric(1, "R", False)                               # configure basic hostRx vars; don't start thread
    # find NICs and log receiving NIC's description
    self.nicsTx, self.nicsRx = NICFinder(self.hostTx, self.hostRx).findNICs()
    libperf.logArg("rx_nic_desc", self.nicsRx.trans.desc)
    # determine network UUID (and create VLANs, if required)
    self.transNetUuidTx = self.hostTx.execdom0("xe network-list bridge=%s params=uuid --minimal" % self.nicsTx.trans.bridge).strip()
    self.transNetUuidRx = self.hostRx.execdom0("xe network-list bridge=%s params=uuid --minimal" % self.nicsRx.trans.bridge).strip()
    if self.use_vlan:
      pifUuidTx = self.hostTx.execdom0("xe pif-list host-uuid=%s network-uuid=%s params=uuid --minimal" % (self.hostTx.uuid, self.transNetUuidTx)).strip()
      pifUuidRx = self.hostRx.execdom0("xe pif-list host-uuid=%s network-uuid=%s params=uuid --minimal" % (self.hostRx.uuid, self.transNetUuidRx)).strip()
      self.transNetUuidTx = self.hostTx.execdom0("xe network-create name-label=%s" % self.vlan_name).strip()
      self.transNetUuidRx = self.transNetUuidTx
      self.hostTx.execdom0("xe vlan-create network-uuid=%s pif-uuid=%s vlan=%d" % (self.transNetUuidTx, pifUuidTx, self.vlan_tag))
      self.hostRx.execdom0("xe vlan-create network-uuid=%s pif-uuid=%s vlan=%d" % (self.transNetUuidRx, pifUuidRx, self.vlan_tag))
    # configure host(s)
    threadTx = self.setupHostGeneric(0, "T", True)                     # start thread for sender
    if self.num_hosts > 1: self.setupHostGeneric(1, "R", True).join()  # if multiple hosts: start and join thread for receiver
    else: self.setupHostGeneric(0, "R", False)                         # otherwise: configure "receiver" as sender
    threadTx.join()                                                    # join thread for sender

  def getHostByIndex(self, i):
    return self.tec.gec.registry.hostGet("RESOURCE_HOST_%d" % i)

  def setupHostGeneric(self, i, ref, run_setup):
    host = self.getHostByIndex(i)
    hostID = self.getIdFromHostName(host)
    hostIP = "10.1.1.%d" % hostID
    setattr(self, "host%sx" % ref, host)
    setattr(self, "host%sxN" % ref, hostID)
    setattr(self, "host%sxIP" % ref, hostIP)
    if run_setup:
      transNetUuid = getattr(self, "transNetUuid%sx" % ref)
      t = SetupHostThread(self.support_files, ref, host, self.protocol, self.network_backend, self.use_irqbalance,
                          self.use_jumbo_frames, self.use_gro, self.use_lro, transNetUuid)
      t.start()
      return t

  def getIdFromHostName(self, host):
    '''Get an id of the host that is to be used as the last number in the
    host's IP, and the third number in the IP of the VMs of that host. The
    function generates a pseudo-random int from 3 to 252 (inclusive) based
    on the host's name.'''
    m = hashlib.md5()
    m.update(host.getName())
    return sum(map(ord, m.hexdigest())) % 250 + 3

  def setupHosts2(self):
    bridgeTx = self.hostTx.execdom0("xe network-list uuid=%s params=bridge --minimal" % self.transNetUuidTx).strip()
    self.hostTx.execdom0("ifconfig %s %s netmask 255.255.0.0" % (bridgeTx, self.hostTxIP))
    if self.num_hosts > 1:
      bridgeRx = self.hostRx.execdom0("xe network-list uuid=%s params=bridge --minimal" % self.transNetUuidRx).strip()
      self.hostRx.execdom0("ifconfig %s %s netmask 255.255.0.0" % (bridgeRx, self.hostRxIP))

  def setupVMpairs(self):
    RxCreateVMts = []
    TxCreateVMts = []
    # start create VM threads
    n = self.num_vm_pairs
    for i in range(n):
      prebuilt_vm1 = None
      prebuilt_vm2 = None
      if self.prebuilt_vms and len(self.prebuilt_vms)>(2*i)+1:
        prebuilt_vm1 = self.hostRx.createGuestObject(self.prebuilt_vms[(2*i)])
        prebuilt_vm1.existing(self.hostRx)
        prebuilt_vm2 = self.hostTx.createGuestObject(self.prebuilt_vms[(2*i)+1])
        prebuilt_vm2.existing(self.hostTx)
      RxCreateVMt = CreateVMthread(self.hostRx, self.nicsRx.comm.bridge,
                                 self.transNetUuidRx, self.nicsRx.dummy.bridge,
                                 self.num_vm_vcpus, self.vm_type,
                                 i + 1, self.ip_v, self.hostRxN, self.ipv6_prefix, guest = prebuilt_vm1)
      TxCreateVMt = CreateVMthread(self.hostTx, self.nicsTx.comm.bridge,
                                 self.transNetUuidTx, self.nicsTx.dummy.bridge,
                                 self.num_vm_vcpus, self.vm_type,
                                 n + i + 1, self.ip_v, self.hostTxN, self.ipv6_prefix, guest = prebuilt_vm2)
      if prebuilt_vm1 and prebuilt_vm2:
        self._threads_to_execPostRun.extend([RxCreateVMt,TxCreateVMt])
      RxCreateVMts.append(RxCreateVMt)
      TxCreateVMts.append(TxCreateVMt)
      RxCreateVMt.start()
      TxCreateVMt.start()
    # wait for all threads to complete, register created VMs
    for i in range(self.num_vm_pairs):
      RxCreateVMts[i].join()
      TxCreateVMts[i].join()
      self.vmRx.append(RxCreateVMts[i].guest)
      self.vmTx.append(TxCreateVMts[i].guest)
    # start VMs in order
    for i in range(self.num_vm_pairs):
      self.vmRx[i].start(specifyOn=False)
      self.vmTx[i].start(specifyOn=False)
      self.wait(15)
    # set IPs
    for i in range(self.num_vm_pairs):
      if self.vm_type in win_vms:
        self.configureWinIP(self.hostRx, self.vmRx[i], RxCreateVMts[i].trans_vif_uuid, RxCreateVMts[i].ip)
        self.configureWinIP(self.hostTx, self.vmTx[i], TxCreateVMts[i].trans_vif_uuid, TxCreateVMts[i].ip)
        if self.use_jumbo_frames: raise Exception("Jumbo frames not yet supported for Windows VMs.")
      else: # self.vm_type == demo
        if self.ip_v == 4:
          self.vmRx[i].execguest("ifconfig eth1 10.1.%d.%d netmask 255.255.0.0" % (self.hostRxN, i + 1))
          self.vmTx[i].execguest("ifconfig eth1 10.1.%d.%d netmask 255.255.0.0" % (self.hostTxN, n + i + 1))
        else: # self.ip_v == 6
          ipv6_common = "ifconfig eth1 up; ip addr add %s" % self.ipv6_prefix
          self.vmRx[i].execguest("%s::%d/64 dev eth1" % (ipv6_common, i + 1))
          self.vmTx[i].execguest("%s::%d/64 dev eth1" % (ipv6_common, n + i + 1))
        if self.use_jumbo_frames:
          self.vmRx[i].execguest("ifconfig eth1 mtu 9000 up")
          self.vmTx[i].execguest("ifconfig eth1 mtu 9000 up")

  def configureWinIP(self, host, vm, trans_vif_uuid, ip):
    vm.xmlrpcExec("netsh firewall set opmode disable")
    ipconfig_all = vm.xmlrpcExec("ipconfig /all", returndata=True)
    trans_mac = host.execdom0("xe vif-param-get param-name=MAC uuid=%s" % trans_vif_uuid).strip().upper().replace(":", "-")
    trans_lan = host.execdom0("echo \"%s\" | grep -i -B 4 \"%s\" | grep -o \"Local Area Connection [0-9]*\"" % (ipconfig_all, trans_mac)).strip()
    if self.ip_v == 4:
      vm.xmlrpcExec("netsh interface ip set address \"%s\" static %s %s" % (trans_lan, ip, "255.255.0.0"))
    else: # self.ip_v == 6
      vm.xmlrpcExec("netsh interface ipv6 set address \"%s\" %s" % (trans_lan, ip))
    # consider moving these two lines into CreateVMthread
    vm.xmlrpcSendFile("%s/iperf.exe" % self.support_files, "c:\\iperf.exe")
    vm.xmlrpcSendFile("%s/fping.exe" % self.support_files, "c:\\fping.exe")

  def run(self, arglist=None):
    self.runDom0toDom0test() # requires setupHosts1,2()
    self.runVMtoVMtest()     # requires setupHosts1,2() and setupVMpairs()

  def runDom0toDom0test(self):
    if self.num_hosts > 1:
      RxHostThread(self.hostRx, self.protocol, self.host_iperf_window, self.host_iperf_buffer).start()
      for run in range(self.num_host_runs):
        self.logDom0iPerfThroughput("networkThroughputDom0", self.num_host_threads)
        if self.trySingleDom0Thread:
          self.logDom0iPerfThroughput("networkThroughputDom0-1t", 1)
        self.logDom0iPerfLatency()
    else: xenrt.TEC().logverbose("Not running dom0 to dom0 tests, since num_hosts =< 1.")

  def logDom0iPerfThroughput(self, log_filename, num_host_threads):
    self.wait(20)
    args = "-c %s -P %d -t %d -f m" % (self.hostRxIP, num_host_threads, self.host_run_time)
    if self.host_iperf_window != -1: args += " -w %dK" % self.host_iperf_window
    if self.host_iperf_buffer != -1: args += " -l %dK" % self.host_iperf_buffer
    if self.protocol == "tcp":
      grep = "grep -v 'SUM'"
    else: # self.protocol == "udp"
      args += " -u -b %dG" % self.udp_target
      grep = "grep ' ms '"
    grep += " | grep -o '[0-9.]\\+ Mbits/sec' | awk '{sum += $1} END {print sum}'"
    cmd = "iperf %s | %s" % (args, grep)
    self.log(log_filename, "%d" % int(float(self.hostTx.execdom0(cmd))))

  def logDom0iPerfLatency(self):
    cmd = ("ping -c %d %s" % (self.host_ping_count, self.hostRxIP) +
           " | grep rtt | awk '{print $4}' | awk -F / '{print $2}'")
    self.log("networkLatencyDom0", "%f" % float(self.hostTx.execdom0(cmd)))

  def runVMtoVMtest(self):
    # start receiver threads
    RxVMts = []
    for i in range(self.num_vm_pairs):
      t = RxVMthread(self.vmRx[i], self.vm_type, self.vm_iperf_window, self.vm_iperf_buffer, self.ip_v)
      RxVMts.append(t)
      t.start()
    for run in range(self.num_vm_runs):
      self.logVMiPerf("networkThroughputVm", "networkLatencyVm", self.num_vm_pairs, self.num_vm_threads)
      if self.trySingleVMPair:
        self.logVMiPerf("networkThroughputVm-1p", "networkLatencyVm-1p", 1, self.num_vm_threads)
      if self.trySingleVMThread:
        self.logVMiPerf("networkThroughputVm-1t", "networkLatencyVm-1t", self.num_vm_pairs, 1)
      if self.trySingleVMPair and self.trySingleVMThread:
        self.logVMiPerf("networkThroughputVm-1p-1t", "networkLatencyVm-1p-1t", 1, 1)

  def logVMiPerf(self, throughput_log_filename, latency_log_filename, num_vm_pairs, num_vm_threads):
    # wait a bit for receivers to settle
    self.wait(20)
    # start sender threads
    TxVMts = []
    for i in range(num_vm_pairs):
      t = TxVMthread(self.vmTx[i], self.vm_type, self.vm_run_time, num_vm_threads,
                     self.vm_ping_count, self.vm_iperf_window, self.vm_iperf_buffer,
                     i + 1, self.ip_v, self.hostRxN, self.ipv6_prefix)
      TxVMts.append(t)
      t.start()
    # wait for all sender threads, and compute total latency and throughput
    for t in TxVMts:
      t.join()
    latencySum = sum ([t.latency for t in TxVMts])
    throughputTotal = sum ([t.throughput for t in TxVMts])

    # output and save results
    self.log(throughput_log_filename, "%d" % throughputTotal)
    self.log(latency_log_filename, "%f" % (latencySum / num_vm_pairs))

  def wait(self, period):
    xenrt.TEC().logverbose("Sleeping for %d seconds... " % period)
    time.sleep(period)

  def postRun(self):
    self.finishUp()
    # reset prebuilt VMs
    for VMt in self._threads_to_execPostRun:
      VMt.execPostRun()

class SetupHostThread(libthread.ExcThread):
  def __init__(self, support_files, ref, host, protocol, network_backend,
               use_irqbalance, use_jumbo_frames, use_gro, use_lro,
               trans_net_uuid):
    libthread.ExcThread.__init__(self)
    self.ref = ref
    self.host = host
    self.protocol = protocol
    self.network_backend = network_backend
    self.use_irqbalance = use_irqbalance
    self.use_jumbo_frames = use_jumbo_frames
    self.use_gro = use_gro
    self.use_lro = use_lro
    self.trans_net_uuid = trans_net_uuid
    self.hostInstallCmd = "yum --disablerepo=citrix --enablerepo=base,updates install -y"
    rpmforgeFilename = "rpmforge-release-0.5.1-1.el5.rf.i386.rpm"
    self.rpmforgeSrc = "%s/%s" % (support_files, rpmforgeFilename)
    self.rpmforgeTarget = "/root/%s" % rpmforgeFilename

  def excRun(self):
    xenrt.TEC().logverbose("host%sx = %s" % (self.ref, self.host.getName()))
    if self.network_backend != "":
      self.host.execdom0("xe-switch-network-backend %s" % self.network_backend)
      self.host.reboot(timeout=1000)
    if self.protocol == "udp": # increase read/write network buffer for UDP
      self.host.execdom0("sysctl -w net.core.rmem_max=268435456")
      self.host.execdom0("sysctl -w net.core.wmem_max=268435456")
    if self.use_irqbalance:
      self.host.execdom0("%s irqbalance && service irqbalance start" % self.hostInstallCmd)
    if self.use_jumbo_frames:
      self.host.execdom0("xe network-param-set uuid=%s MTU=9000" % self.trans_net_uuid)
      self.host.execdom0("for uuid in $(xe pif-list network-uuid=%s --minimal | sed 's/,/ /g'); do xe pif-unplug uuid=$uuid; xe pif-plug uuid=$uuid; done" % self.trans_net_uuid)
    if self.use_gro or self.use_lro:
      time.sleep(30) # it is not clear whether this is neccessary
    device = self.host.execdom0("xe pif-list network-uuid=%s params=device --minimal" % self.trans_net_uuid).strip().split(',')[0]
    if self.use_gro:
      self.host.execdom0("ethtool -K %s gro on" % device)
    if self.use_lro:
      self.host.execdom0("ethtool -K %s lro on" % device)
    self.host.execdom0("service iptables stop || true")
    sftp = self.host.sftpClient()
    sftp.copyTo(self.rpmforgeSrc, self.rpmforgeTarget)
    self.host.execdom0("rpm -Uhv %s; rpm -q iperf || %s iperf" % (self.rpmforgeTarget, self.hostInstallCmd))

class RxHostThread(libthread.ExcThread):
  def __init__(self, host, protocol, host_iperf_window, host_iperf_buffer):
    libthread.ExcThread.__init__(self)
    self.host = host
    self.protocol = protocol
    self.host_iperf_window = host_iperf_window
    self.host_iperf_buffer = host_iperf_buffer
    self.daemon = True

  def excRun(self):
    args = "-s"
    if self.protocol == "udp": args += " -u"
    if self.host_iperf_window != -1: args += " -w %dK" % self.host_iperf_window
    if self.host_iperf_buffer != -1: args += " -l %dK" % self.host_iperf_buffer
    try: self.host.execdom0("iperf %s > /dev/null" % args, timeout=3600, useThread=True)
    except: xenrt.TEC().logverbose("iperf server on host %s has been terminated." % self.host.getName())

class CreateVMthread(libthread.ExcThread):
  def __init__(self, host, comm_bridge, trans_net_uuid, dummy_bridge,
               num_vm_vcpus, vm_type, vm_index, ip_v, ipv4_family,
               ipv6_prefix, guest = None):
    libthread.ExcThread.__init__(self)
    self.host = host
    self.comm_bridge = comm_bridge
    self.trans_net_uuid = trans_net_uuid
    self.dummy_bridge = dummy_bridge
    self.num_vm_vcpus = num_vm_vcpus
    self.vm_type = vm_type
    self.ip_v = ip_v
    self.guest = guest
    self._vif_uuid_to_remove = []
    if ip_v == 4:
      self.ip = "10.1.%d.%d" % (ipv4_family, vm_index)
      self.netmask = "255.255.0.0"
    else: # ip_v == 6
      self.ip = "%s::%d/64" % (ipv6_prefix, vm_index)

  def excRun(self):
    if not self.guest:
      # create guest
      if self.vm_type in win_vms:
        iso = win_vms[self.vm_type]
        xenrt.TEC().logverbose("Creating a Windows 7 guest on host %s" % self.host.getName())
        self.guest = self.host.createGenericWindowsGuest(distro=iso, vcpus=self.num_vm_vcpus)
        # added for Boston MS3
        self.guest.unenlightenedShutdown()
        self.guest.poll('DOWN')
      else: # self.vm_type == demo
        xenrt.TEC().logverbose("Creating a generic Linux guest %s on bridge %s on host %s" % (self.vm_type,self.comm_bridge, self.host.getName()))
        self.guest = self.host.createGenericLinuxGuest(start=False, bridge=self.comm_bridge, vcpus=self.num_vm_vcpus, generic_distro=self.vm_type)
    # shutdown prebuilt VM
    if self.guest.getState() == "UP":
      self.guest.shutdown()
    # setup networking
    self.trans_vif_uuid = self.createVif(self.trans_net_uuid, "1")
    dummy_net_uuid = self.host.execdom0("xe network-list bridge=%s params=uuid --minimal" % self.dummy_bridge).strip()
    dummy_vif_uuid = self.createVif(dummy_net_uuid, "2")
    self.guest.start(specifyOn=False)
    if self.vm_type not in win_vms: # self.vm_type == demo
      if self.vm_type == "etch":
        self.guest.execguest("sed -i 's/http:\/\/.*\//http:\/\/archive.debian.org\//' /etc/apt/sources.list")
      self.guest.execguest("apt-get update")
      self.guest.execguest("apt-get install --force-yes -y iperf")
    self.guest.shutdown()

  def createVif(self, network_uuid, device):
    guest_uuid = self.guest.getUUID()
    vif_uuid = self.host.execdom0("xe vif-create network-uuid=%s vm-uuid=%s device=%s mac=%s" % (network_uuid, guest_uuid, device, xenrt.randomMAC())).strip()
    self._vif_uuid_to_remove.append(vif_uuid)
    return vif_uuid

  def execPostRun(self):
    if self.guest.getState() == "UP":
      self.guest.shutdown()
    for vif_uuid in self._vif_uuid_to_remove:
      self.host.execdom0("xe vif-destroy uuid=%s" % vif_uuid)
    self._vif_uuid_to_remove = []
    self.guest.start(specifyOn=False)
    xenrt.sleep(120)

class RxVMthread(libthread.ExcThread):
  def __init__(self, guest, vm_type, vm_iperf_window, vm_iperf_buffer, ip_v):
    libthread.ExcThread.__init__(self)
    self.guest = guest
    self.vm_type = vm_type
    self.vm_iperf_window = vm_iperf_window
    self.vm_iperf_buffer = vm_iperf_buffer
    self.ip_v = ip_v
    self.daemon = True

  def excRun(self):
    xenrt.TEC().logverbose("Starting the iperf daemon on %s ..." % self.guest.getName())
    args = "-s"
    if self.vm_iperf_window != -1: args += " -w %dK" % self.vm_iperf_window
    if self.vm_iperf_buffer != -1: args += " -l %dK" % self.vm_iperf_buffer
    if self.ip_v == 6: args += " -V"
    try:
      if self.vm_type in win_vms:
        self.guest.xmlrpcExec("c:\\iperf %s" % args, timeout=3600)
      else: # self.vm_type == demo
        self.guest.execguest("iperf %s > /dev/null" % args, timeout=3600)
    except Exception, e:
      traceback.print_exc()
    xenrt.TEC().logverbose("Starting of iperf daemon on %s complete." % self.guest.getName())

class TxVMthread(libthread.ExcThread):
  def __init__(self, guest, vm_type, vm_run_time, num_vm_threads,
               vm_ping_count, vm_iperf_window, vm_iperf_buffer,
               vm_index, ip_v, ipv4_family, ipv6_prefix):
    libthread.ExcThread.__init__(self)
    self.guest = guest
    self.vm_type = vm_type
    self.vm_run_time = vm_run_time
    self.num_vm_threads = num_vm_threads
    self.vm_ping_count = vm_ping_count
    self.vm_iperf_window = vm_iperf_window
    self.vm_iperf_buffer = vm_iperf_buffer
    self.ip_v = ip_v
    if ip_v == 4:
      self.target_ip = "10.1.%d.%d" % (ipv4_family, vm_index)
      self.ping_cmd = "ping"
    else: # ip_v == 6
      self.target_ip = "%s::%d" % (ipv6_prefix, vm_index)
      self.ping_cmd = "ping6"

  def excRun(self):
    host = self.guest.getHost()
    args = "-c %s -P %d -t %d -f m" % (self.target_ip, self.num_vm_threads, self.vm_run_time)
    if self.vm_iperf_window != -1: args += " -w %dK" % self.vm_iperf_window
    if self.vm_iperf_buffer != -1: args += " -l %dK" % self.vm_iperf_buffer
    if self.ip_v == 6: args += " -V"
    if self.vm_type in win_vms:
      self.output = self.guest.xmlrpcExec("c:\\iperf %s" % args, timeout=3600, returndata=True)
      latency_output = self.guest.xmlrpcExec("c:\\fping %s -n %d -o" % (self.target_ip, self.vm_ping_count), returndata=True)
      self.latency = float(host.execdom0("echo \"%s\" | grep Average | awk '{print $11}'" % latency_output).strip())
    else: # self.vm_type == "demo"
      self.output = self.guest.execguest("iperf %s" % args)
      latency_output = self.guest.execguest("%s -c %d %s" % (self.ping_cmd, self.vm_ping_count, self.target_ip))
      self.latency = float(host.execdom0("echo \"%s\" | grep rtt | awk '{print $4}' | awk -F / '{print $2}'" % latency_output))
    self.throughput = int(float(host.execdom0("echo \"%s\" | grep -v 'SUM' | grep -o '[0-9.]* Mbits/sec' | awk '{sum += $1} END {print sum}'" % self.output).strip()))
    xenrt.TEC().logverbose("Throughput of guest %s was %d Mbits/sec." % (self.guest.getName(), self.throughput))
    xenrt.TEC().logverbose("Latency of guest %s was %f ms." % (self.guest.getName(), self.latency))
