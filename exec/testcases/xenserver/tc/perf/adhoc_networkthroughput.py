import libperf, os, re, string, thread, threading, time, xenrt

class PoolMaster(object):
    def __init__(self, host, sender_host="tg02", vm_type="win", name_scheme=".*"):
        # declare variables
        self.hostRx = host
        self.hostTx = None
        self.vmTx = []
        self.vmRx = []
        self.vm_type = vm_type
        for name, g in self.hostRx.guests.iteritems():
            if re.match(name_scheme, name):
                self.vmRx.append(g)
        self.hostRxN = 8
        self.vm_ping_count = 20
        self.hostTx = self.existingHost(sender_host)

    def existingHost(self, hostname):
        machine = xenrt.PhysicalHost(hostname)
        place = xenrt.GenericHost(machine)
        place.findPassword()
        place.checkVersion()
        host = xenrt.lib.xenserver.hostFactory(place.productVersion)(machine, productVersion=place.productVersion)
        place.populateSubclass(host)
        host.findPassword()
        host.checkVersion()
        return host

    def createVMs(self, n=4, trans_bridge="xenbr11", ip_family=7, vm_type="win"):
        print "createVMs: start"
        ts = []
        for i in range(1, n+1):
            t = CreateVM(self.hostRx, "xenbr0", trans_bridge, "xenbr1", 1, vm_type, "10.0.%d.%d" % (ip_family, i))
            ts.append(t)
            t.start()
            time.sleep(60)
        for t in ts: t.join(); self.vmRx.append(t.guest)
        print "createVMs: done"

    def clone(self, vm, n=1):
        for i in range(n):
            self.vmRx.append(vm.cloneVM())

    def renameVMs(self, base):
        for i in range(len(self.vmRx)):
            self.vmRx[i].setName("%s-%02d" % (base, i))

    def doVmOps(self, op="start", num=None):
        vm_type = self.vm_type
        class StartVM(threading.Thread):
            def __init__(self, guest):
                threading.Thread.__init__(self)
                self.guest = guest
            def run(self):
                getattr(self.guest, op)()
                if vm_type == "demo":
                    self.guest.execguest("ethtool -K eth1 gso on")
        ts = []
        if not num: num = len(self.vmRx)
        for i in range(num):
            t = StartVM(self.vmRx[i])
            ts.append(t)
            t.start()
            if op is "start":
                time.sleep(2)
                if t.isAlive(): time.sleep(60)
        for t in ts: t.join()
        print "doVmOps '%s': DONE" % op

    def manyIperfAllContexts(self):
        nums = range(1, len(self.vmRx)+1)
        #for rsc in True, False:
        for backend in "openvswitch", "bridge":
            self.manyIperfSingleContext(False, backend, nums)
            #self.manyIperfSingleContext(rsc, backend, nums)

    def manyIperfSingleContext(self, rsc=False, backend="bridge", nums=None):
        if not nums: nums = [len(self.vmRx)]
        #print "Setting context to RSC=%s, backend=%s ..." % (rsc, backend)
        #print "Make sure that all VMs are up ..."
        #self.doVmOps("start")
        #print "Stop any receivers still running ..."
        #self.stopReceivers()
        #print "Set RSC to %s on all VMs ..." % rsc
        #self.setRSC(rsc)
        print "Set network backend to %s ..." % backend
        print self.hostRx.execdom0("xe-switch-network-backend %s" % backend)
        print "Shutdown VMs and host, then start host ..."
        self.hostRx.reboot()
        print "Wait a minute for the host to settle ..."
        time.sleep(60)
        print "Run tests ..."
        for num in nums: self.manyIperf(rsc, backend, num)

    def manyIperf(self, rsc, backend, num=None):
        if not num: num = len(self.vmRx)
        print "Starting test where RSC=%s, backend=%s, num=%d ..." % (rsc, backend, num)
        print "Make sure first %d VMs are up ..." % num
        self.doVmOps("start", num)
        print "Wait a few minutes for VMs to settle ..."
        time.sleep(180)
        print "Stop any receivers already running ..."
        self.stopReceivers(num)
        print "Configure IPs ..."
        self.configureIPs(num)
        print "Start fresh receivers ..."
        self.startReceivers(num)
        print "Wait half a minute for receiver starts to settle ..."
        time.sleep(30)
        print "Run the test ..."
        out = "rsc-%s-backend-%s-num-%d.out" % (rsc, backend, num)
        print self.hostTx.execdom0("/root/many-iperf %s %d" % (out, num), timeout=7200)


    ## timeslice:
    ##param = "sched_credit_tslice_ms"
    ##regexp = "s/%s=[0-9]*/%s=%d/" % (param, param, timeslice)
    ##cmd = "sed -i '%s' /boot/extlinux.conf" % regexp
    ##self.hostRx.execdom0(cmd)

    def getRSC(self, num=None):
        data = {}
        key = "HKEY_LOCAL_MACHINE\SYSTEM\\CurrentControlSet\\services\\xenvif\\Parameters"
        val = "ReceiverMaximumProtocol"
        cmd = "REG QUERY %s /v %s" % (key, val)
        class GetRSC(threading.Thread):
            def __init__(self, guest):
                threading.Thread.__init__(self)
                self.guest = guest
            def run(self):
                fs = self.guest.xmlrpcExec(cmd, returndata=True).split()
                data[self.guest.getUUID()] = fs[len(fs) - 1]
        ts = []
        if not num: num = len(self.vmRx)
        for i in range(num):
            t = GetRSC(self.vmRx[i])
            ts.append(t)
            t.start()
        for t in ts: t.join()
        for uuid, d in data.iteritems():
            print "%s ==> %s" % (uuid, d)

    def setRSC(self, enable=True, num=None):
        key = "HKEY_LOCAL_MACHINE\SYSTEM\\CurrentControlSet\\services\\xenvif\\Parameters"
        val = "ReceiverMaximumProtocol"
        if enable: data = 1
        else: data = 0
        cmd = "REG ADD %s /v %s /t REG_DWORD /d %d /f" % (key, val, data)
        class SetRSC(threading.Thread):
            def __init__(self, guest):
                threading.Thread.__init__(self)
                self.guest = guest
            def run(self): self.guest.xmlrpcExec(cmd)
        ts = []
        if not num: num = len(self.vmRx)
        for i in range(num):
            t = SetRSC(self.vmRx[i])
            ts.append(t)
            t.start()
        for t in ts: t.join()

    def startReceivers(self, num=None, udp=False, mss=-1, window_size=256, buffer_size=256):
        if not num: num = len(self.vmRx)
        for i in range(num):
            RxVMthread(self.vmRx[i], self.vm_type, mss, window_size, buffer_size).start()

    def stopReceivers(self, num=None):
        if not num: num = len(self.vmRx)
        class StopReceiver(threading.Thread):
            def __init__(self, guest, vm_type):
                threading.Thread.__init__(self)
                self.guest = guest
                self.vm_type = vm_type
            def run(self):
                if self.vm_type == "win":
                    self.guest.xmlrpcExec("taskkill /F /IM iperf.exe /T")
                else:
                    self.guest.execguest("killall iperf")
        ts = []
        for i in range(num):
            t = StopReceiver(self.vmRx[i], self.vm_type)
            ts.append(t)
            t.start()
        for t in ts: t.join()
        print "Receivers stopped."

    def startTest(self, num_vm_pairs=-1, num_vm_threads=1, vm_run_time=10, mss=-1, window_size=-1, buffer_size=-1):
        if num_vm_pairs is -1: num_vm_pairs = len(self.vmTx)
        # start sender threads
        TxVMts = []
        for i in range(num_vm_pairs):
            t = TxVMthread(self.vmTx[i], self.vm_type, "10.0.%d.%d" % (self.hostRxN, i), vm_run_time, num_vm_threads, self.vm_ping_count, mss, window_size, buffer_size)
            TxVMts.append(t)
            t.start()
        # wait for all sender threads, and compute total latency and throughput
        #latencySum = 0.0
        throughputTotal = 0
        for t in TxVMts:
            t.join()
            #latencySum += t.latency
            throughputTotal += t.throughput
        # output and save results
        xenrt.TEC().logverbose("========================================")
        #xenrt.TEC().logverbose("AVERAGE LATENCY: %f ms" % (latencySum / len(self.vmTx)))
        xenrt.TEC().logverbose("TOTAL VM-to-VM THROUGHPUT: %d Mbits/sec" % throughputTotal)
        xenrt.TEC().logverbose("========================================")
        return throughputTotal

    def startTests(self, num_tests=1, num_vm_pairs=-1, num_vm_threads=1, vm_run_time=10, mss=-1, window_size=-1, buffer_size=-1):
        sum = 0
        for i in range(num_tests):
            time.sleep(5)
            xenrt.TEC().logverbose("==> run: %d" % (i+1))
            sum += self.startTest(num_vm_pairs, num_vm_threads, vm_run_time, mss, window_size, buffer_size)
        return sum / num_tests

    def searchOptimal(self, vm_pairs=1, vm_threads=1):
        for mss_k in range(8, 15):
            mss = 2 << mss_k
            for ws_k in range(3, 11):
                ws = 2 << ws_k
                for bs_k in range(3, 11):
                    bs = 2 << bs_k
                    print "===> STARTING TEST WITH: mss: %d, ws: %dK, bs: %dK" % (mss, ws, bs)
                    self.stopReceivers(vm_pairs)
                    self.startReceivers(vm_pairs, False, mss, ws, bs)
                    t = self.startTests(1, vm_pairs, vm_threads, 20, mss, ws, bs)
                    self.log("results-%d-pairs" % vm_pairs, "%d %d %d %d" % (t, mss, ws, bs))
        print "Done."

    def searchOptimals(self):
        for vm_pairs in range(1, 9):
            print "===> SEARCH FOR OPTIMAL PARAMETERS FOR %d VM PAIRS" % vm_pairs
            self.searchOptimal(vm_pairs)

    def startBothSidedTest(self, num_vm_pairs=1, num_vm_threads=1, vm_run_time=10, mss=-1, ws=-1, bs=-1):
        self.stopReceivers(num_vm_pairs)
        self.startReceivers(num_vm_pairs, False, mss, ws, bs)
        time.sleep(5)
        self.startTest(num_vm_pairs, num_vm_threads, vm_run_time, mss, ws, bs)

    def startThreadSeries(self, num_tests=5, vm_run_time=20, max_vm_threads=4):
        result = ""
        for num_vm_threads in range(1, max_vm_threads+1):
            result += "THREADS-%d\n" % num_vm_threads;
            for num_vm_pairs in range(1, len(self.vmTx)+1):
                time.sleep(5)
                throughput = self.startTests(num_tests, num_vm_pairs, num_vm_threads, vm_run_time)
                xenrt.TEC().logverbose("==> num_vm_pairs: %d, num_vm_threads: %d, throughput: %d" % (num_vm_pairs, num_vm_threads, throughput))
                result += "%d %d\n" % (num_vm_pairs, throughput)
        print result

    def startSeries(self, num_tests=1, num_vm_pairs=-1, num_vm_threads=1, vm_run_time=10):
        if num_vm_pairs is -1: num_vm_pairs = len(self.vmTx)
        results = {}
        for i in range(10):
            mss = 2**i
            throughput = self.startTests(num_tests, num_vm_pairs, num_vm_threads, vm_run_time, mss)
            results[mss] = throughput
        results[1492] = self.startTests(num_tests, num_vm_pairs, num_vm_threads, vm_run_time, 1492)
        xenrt.TEC().logverbose("========================================")
        for mss, throughput in results.iteritems():
            xenrt.TEC().logverbose("Throughput (mss = %d): %d" % (mss, throughput))
        xenrt.TEC().logverbose("========================================")

    def show(self):
        print "Receiver: %s" % self.hostRx.getName()
        print "Receiver VMs:"
        for vm in self.vmRx:
            print vm.getName()
        print "Sender VMs:"
        for vm in self.vmTx:
            print vm.getName()

    def configureIPs(self, num=None, eth="eth1", ip_family=7):
        if not num: num = len(self.vmRx)
        for i in range(num):
            self.vmRx[i].execguest("ifconfig %s 10.0.%d.%d netmask 255.255.0.0" % (eth, ip_family, 10 + i))

    def installIperfs(self, num=None):
        class InstallIperf(threading.Thread):
            def __init__(self, guest):
                threading.Thread.__init__(self)
                self.guest = guest
            def run(self):
                self.guest.execguest("sed -i 's/http:\/\/.*\//http:\/\/archive.debian.org\//' /etc/apt/sources.list")
                self.guest.execguest("apt-get update")
                self.guest.execguest("apt-get install --force-yes -y iperf")
        if not num: num = len(self.vmRx)
        ts = []
        for i in range(num):
            t = InstallIperf(self.vmRx[i])
            ts.append(t)
            t.start()
        for t in ts: t.join()
        print "installIperfs: done."

    def enableJumboFrames(self):
        for i in range(len(self.vmRx)): self.vmRx[i].execguest("ifconfig eth1 mtu 9000 up")
        for i in range(len(self.vmTx)): self.vmTx[i].execguest("ifconfig eth1 mtu 9000 up")

#    def configureVIF(self, vm, device, ip_part):
#        ipconfig_all = vm.xmlrpcExec("ipconfig /all", returndata=True)
#        vif_uuid = self.hostRx.execdom0("xe vif-list vm-uuid=%s device=%d params=uuid --minimal" % (vm.getUUID(), device)).strip()
#        trans_mac = self.hostRx.execdom0("xe vif-param-get param-name=MAC uuid=%s" % vif_uuid).strip().upper().replace(":", "-")
#        trans_lan = self.hostRx.execdom0("echo \"%s\" | grep -i -B 4 \"%s\" | grep -o \"Local Area Connection [0-9]*\"" % (ipconfig_all, trans_mac)).strip()
#        ip = "10.0.7.%d" % ip_part
#        vm.xmlrpcExec("netsh interface ip set address \"%s\" static %s" % (trans_lan, ip))

    def configureVIFs(self, device=2, num=None):
        class ConfigureVIF(threading.Thread):
            def __init__(self, guest, ip_part):
                threading.Thread.__init__(self)
                self.guest = guest
                self.ip_part = ip_part
            def run(self):
                host = self.guest.getHost()
                ipconfig_all = self.guest.xmlrpcExec("ipconfig /all", returndata=True)
                vif_uuid = host.execdom0("xe vif-list vm-uuid=%s device=%d params=uuid --minimal" % (self.guest.getUUID(), device)).strip()
                trans_mac = host.execdom0("xe vif-param-get param-name=MAC uuid=%s" % vif_uuid).strip().upper().replace(":", "-")
                trans_lan = host.execdom0("echo \"%s\" | grep -i -B 4 \"%s\" | grep -o \"Local Area Connection [0-9]*\"" % (ipconfig_all, trans_mac)).strip()
                ip = "10.0.7.%d" % self.ip_part
                self.guest.xmlrpcExec("netsh interface ip set address \"%s\" static %s" % (trans_lan, ip))
                self.guest.xmlrpcExec("netsh firewall set opmode disable")
        if not num: num = len(self.vmRx)
        ts = []
        for i in range(num):
            t = ConfigureVIF(self.vmRx[i], 10 + i)
            ts.append(t)
            t.start()
        for t in ts: t.join()
 
    def sendFilesToVM(self, vm):
        vm.xmlrpcSendFile("/home/xenrtd/xenrt/bin/iperf.exe", "c:\\iperf.exe")
        vm.xmlrpcSendFile("/home/xenrtd/xenrt/bin/fping.exe", "c:\\fping.exe")

    def sendFilesToVMs(self):
        for vm in self.vmRx: self.sendFilesToVM(vm)
        for vm in self.vmTx: self.sendFilesToVM(vm)

    def startBoundReceivers(self):
        xenrt.TEC().logverbose("Starting receivers..")
        RxVMts = []
        for i in [1,2,3,4]:
            t = BoundRxVMthread(self.vmRx[0], "10.0.5.%d" % i, i-1)
            RxVMts.append(t)
            t.start()

    def startBoundTest(self, num_vm_threads=1, vm_run_time=10, mss=40):
        xenrt.TEC().logverbose("Starting senders..")
        TxVMts = []
        for i in [1,2,3,4]:
            t = BoundTxVMthread(self.vmTx[0], "10.0.6.%d" % i, "10.0.5.%d" % i, vm_run_time, num_vm_threads, mss)
            TxVMts.append(t)
            t.start()
        xenrt.TEC().logverbose("Waiting for tests to complete..")
        for t in TxVMts:
            t.join()
        xenrt.TEC().logverbose("Computing total throughput..")
        throughputTotal = 0
        for t in TxVMts:
            throughputTotal += t.throughput
        xenrt.TEC().logverbose("========================================")
        xenrt.TEC().logverbose("TOTAL VM-to-VM THROUGHPUT: %d Mbits/sec" % throughputTotal)
        xenrt.TEC().logverbose("========================================")
        return throughputTotal

    def startBoundTests(self, num_tests=1, num_vm_threads=1, vm_run_time=10, mss=40):
        sum = 0
        for i in range(num_tests):
            sum += self.startBoundTest(num_vm_threads, vm_run_time, mss)
        return sum / num_tests

    def startBoundSeries(self, num_tests=1, num_vm_threads=1, vm_run_time=10):
        results = {}
        for i in range(10):
            mss = 2**i
            throughput = self.startBoundTests(num_tests, num_vm_threads, vm_run_time, mss)
            results[mss] = throughput
        results[1492] = self.startBoundTests(num_tests, num_vm_threads, vm_run_time, 1492)
        xenrt.TEC().logverbose("========================================")
        for mss, throughput in results.iteritems():
            xenrt.TEC().logverbose("Throughput (mss = %d): %d" % (mss, throughput))
        xenrt.TEC().logverbose("========================================")

    def log(self, filename, msg):
        """Logs to a file and console"""
        xenrt.TEC().logverbose(msg)
        if filename is not None:
            libperf.outputToResultsFile(libperf.createLogName(filename), msg)

class RxHostThread(threading.Thread):
    def __init__(self, host):
        threading.Thread.__init__(self)
        self.host = host
    def run(self):
        self.daemon = True
        try: self.host.execdom0("iperf -s > /dev/null")
        except: xenrt.TEC().logverbose("iperf server on host %s has been terminated." % self.host.getName())

class BoundRxVMthread(threading.Thread):
    def __init__(self, guest, bind_addr, cpu):
        threading.Thread.__init__(self)
        self.guest = guest
        self.bind_addr = bind_addr
        self.cpu = cpu

    def run(self):
        self.daemon = True
        self.guest.xmlrpcExec("c:\\iperf.exe -s -D -B %s" % self.bind_addr, timeout=3600)

class BoundTxVMthread(threading.Thread):
    def __init__(self, guest, source_ip, target_ip, vm_run_time, num_vm_threads, mss):
        threading.Thread.__init__(self)
        self.guest = guest
        self.source_ip = source_ip
        self.target_ip = target_ip
        self.vm_run_time = vm_run_time
        self.num_vm_threads = num_vm_threads
        self.mss = mss

    def run(self):
        host = self.guest.getHost()
        self.output = self.guest.xmlrpcExec("c:\\iperf -B %s -c %s -P %d -t %d -f m -M %d" % (self.source_ip, self.target_ip, self.num_vm_threads, self.vm_run_time, self.mss), timeout=None, returndata=True)
        self.throughput = int(float(host.execdom0("echo \"%s\" | grep -v 'SUM' | grep -o '[0-9.]* Mbits/sec' | awk '{sum += $1} END {print sum}'" % self.output).strip()))
        xenrt.TEC().logverbose("Throughput from %s to %s was %d Mbits/sec." % (self.source_ip, self.target_ip, self.throughput))

class RxVMthread(threading.Thread):
    def __init__(self, guest, vm_type, mss, window_size, buffer_size):
        threading.Thread.__init__(self)
        self.guest = guest
        self.vm_type = vm_type
        self.mss = mss
        self.window_size = window_size
        self.buffer_size = buffer_size

    def run(self):
        self.daemon = True
        if self.mss == -1: mssSetting = ""
        else: mssSetting = " -M %d" % self.mss
        if self.window_size == -1: windowSetting = ""
        else: windowSetting = " -w %dK" % self.window_size 
        if self.buffer_size == -1: bufferSetting = ""
        else: bufferSetting = " -l %dK" % self.buffer_size
        cmd = "iperf -s -m%s%s%s" % (mssSetting, windowSetting, bufferSetting)
        if self.vm_type == "win":
            self.guest.xmlrpcExec("c:\\%s" % cmd, timeout=3600)
        else:
            self.guest.execguest("%s > /dev/null" % cmd, timeout=3600)

class TxVMthread(threading.Thread):
    def __init__(self, guest, vm_type, target_ip, vm_run_time, num_vm_threads, vm_ping_count, mss, window_size, buffer_size):
        threading.Thread.__init__(self)
        self.guest = guest
        self.vm_type = vm_type
        self.target_ip = target_ip
        self.vm_run_time = vm_run_time
        self.num_vm_threads = num_vm_threads
        self.vm_ping_count = vm_ping_count
        self.mss = mss
        self.window_size = window_size
        self.buffer_size = buffer_size

    def run(self):
        host = self.guest.getHost()
        if self.mss == -1: mssSetting = ""
        else: mssSetting = " -M %d" % self.mss
        if self.window_size == -1: windowSetting = ""
        else: windowSetting = " -w %dK" % self.window_size 
        if self.buffer_size == -1: bufferSetting = ""
        else: bufferSetting = " -l %dK" % self.buffer_size
        cmd = "iperf -c %s -P %d -t %d -f m%s%s%s" % (self.target_ip, self.num_vm_threads, self.vm_run_time, mssSetting, windowSetting, bufferSetting)
        if self.vm_type == "win":
            self.output = self.guest.xmlrpcExec("c:\\%s" % cmd, timeout=None, returndata=True)
        else:
            self.output = self.guest.execguest(cmd)
        self.throughput = int(float(host.execdom0("echo \"%s\" | grep -v 'SUM' | grep -o '[0-9.]* Mbits/sec' | awk '{sum += $1} END {print sum}'" % self.output).strip()))
        xenrt.TEC().logverbose("Throughput of guest %s was %d Mbits/sec." % (self.guest.getName(), self.throughput))

class CreateVM(threading.Thread):
    def __init__(self, host, comm_bridge, trans_bridge, dummy_bridge, num_vm_vcpus, vm_type, ip, guest=None):
        threading.Thread.__init__(self)
        self.host = host
        self.comm_bridge = comm_bridge
        self.trans_bridge = trans_bridge
        self.dummy_bridge = dummy_bridge
        self.vm_type = vm_type
        self.num_vm_vcpus = num_vm_vcpus
        self.ip = ip
        self.guest = guest
        self.winIperfFile = "/home/xenrtd/xenrt/bin/iperf.exe"
        self.winFpingFile = "/home/xenrtd/xenrt/bin/fping.exe"

    def run(self):
        if not self.guest:
            if not self.createVM():
                return
        if self.guest.getState() == "UP":
            self.guest.shutdown()
        self.setupNetworking()

    def createVM(self):
        if self.vm_type == "win":
            xenrt.TEC().logverbose("Creating a Windows Server 2008 R2 SP1 guest on host %s" % self.host.getName())
            self.guest = self.host.createGenericWindowsGuest(distro="ws08r2sp1-x64", vcpus=self.num_vm_vcpus)
            self.guest.unenlightenedShutdown()
            self.guest.poll('DOWN')
        elif self.vm_type == "demo":
            xenrt.TEC().logverbose("Creating a Demo Linux guest on bridge %s on host %s" % (self.comm_bridge, self.host.getName()))
            self.guest = self.host.createGenericLinuxGuest(start=False, bridge=self.comm_bridge, vcpus=self.num_vm_vcpus)
        else:
            xenrt.TEC().logverbose("Unrecognised value for 'vm_type': %s. Please choose one of: demo, win." % self.vm_type)
            return False
        return True

    def setupNetworking(self):
        trans_vif_uuid = self.createVif(self.trans_bridge, "1")
        dummy_vif_uuid = self.createVif(self.dummy_bridge, "2")
        self.guest.start()
        if self.vm_type == "win":
            self.guest.xmlrpcExec("netsh firewall set opmode disable")
            ipconfig_all = self.guest.xmlrpcExec("ipconfig /all", returndata=True)
            trans_mac = self.host.execdom0("xe vif-param-get param-name=MAC uuid=%s" % trans_vif_uuid).strip().upper().replace(":", "-")
            trans_lan = self.host.execdom0("echo \"%s\" | grep -i -B 4 \"%s\" | grep -o \"Local Area Connection [0-9]*\"" % (ipconfig_all, trans_mac)).strip()
            self.guest.xmlrpcExec("netsh interface ip set address \"%s\" static %s" % (trans_lan, self.ip))
            self.guest.xmlrpcSendFile(self.winIperfFile, "c:\\iperf.exe")
            self.guest.xmlrpcSendFile(self.winFpingFile, "c:\\fping.exe")
        elif self.vm_type == "demo":
            self.guest.execguest("sed -i 's/http:\/\/.*\//http:\/\/archive.debian.org\//' /etc/apt/sources.list")
            self.guest.execguest("apt-get update")
            self.guest.execguest("apt-get install --force-yes -y iperf")
        else:
            xenrt.TEC().logverbose("Unrecognised value for 'vm_type': %s. Please choose one of: demo, win." % self.vm_type)
            return
        self.guest.reboot()

    def createVif(self, bridge, device):
        network_uuid = self.host.execdom0("xe network-list bridge=%s params=uuid --minimal" % bridge).strip()
        guest_uuid = self.guest.getUUID()
        vif_uuid = self.host.execdom0("xe vif-create network-uuid=%s vm-uuid=%s device=%s mac=%s" % (network_uuid, guest_uuid, device, xenrt.randomMAC())).strip()
        return vif_uuid

