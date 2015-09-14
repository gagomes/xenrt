import xenrt, libperf
import os, time, json
from xenrt.lazylog import step, comment, log, warning

class BlackWidowPerformanceTestCase(libperf.PerfTestCase):

    TEST = None
    IS_VALID_CLIENTTHREADS = True
    IS_VALID_CLIENTPARALLELCONN = True
    WORKLOADS = {
        "100KB.wl" : r"""DEFINE_CLASSES
        BULK:   100
 
DEFINE_REQUESTS
 
        BULK:
                GET /wb30tree/100000_1.txt
 
""",
        "1only.wl": r"""DEFINE_CLASSES
        BULK:   100
 
DEFINE_REQUESTS
 
        BULK:
                GET /wb30tree/100_1.txt
 
"""
    }

#### functional methods ####
    def getVPX(self, guest, password='nsroot'):
        guest.password = password
        return xenrt.lib.netscaler.NetScaler(guest, None)

    def setupBlackWidow(self, vpx_ns):
        # Add HTTP client IPs
        for i in range(2, self.clients+1):
            vpx_ns.cli("add ns ip 43.54.181.%d 255.255.0.0 -vServer DISABLED" % (i))

        # Find the ID of the second VLAN
        vlan_ord = 2
        lines = vpx_ns.cli("show vlan")
        vlan_idx = next(line.split('\t')[1].split(' ')[2] for line in lines if line.startswith("%d)" % (vlan_ord)))

        # Make 43.* traffic go down the right interface
        vpx_ns.cli("bind vlan %s -IPAddress 43.54.181.2 255.255.0.0" % (vlan_idx))
        vpx_ns.cli('save ns config')

    def setupDUT(self, vpx_ns):
        # Add SNIPs (the origin IP for requests travelling from NS to webserver)
        for i in range(1, self.snips+1):
            vpx_ns.cli("add ns ip 43.54.30.%d 255.255.0.0 -vServer DISABLED -mgmtAccess ENABLED" % (i))

        # Add references to the HTTP server's IP addresses
        for i in range(2, self.servers+1):
            vpx_ns.cli("add server 43.54.31.%d 43.54.31.%d" % (i, i))

        # Configure the vServer on 43.54.30.247 and bind it to the true servers
        vpx_ns.cli("add serviceGroup s1 HTTP -maxClient 0 -maxReq 0 -cip DISABLED -usip NO -useproxyport YES -cltTimeout 180 -svrTimeout 360 -CKA NO -TCPB NO -CMP NO")
        vpx_ns.cli("enable ns feature LB")
        vpx_ns.cli("add lb vserver v1 %s 43.54.30.247 80 -persistenceType NONE -lbMethod ROUNDROBIN -cltTimeout 18" % self.dutProtocolVServer)
        vpx_ns.cli("bind lb vserver v1 s1")
        for i in range(2, self.servers+1):
            vpx_ns.cli("bind serviceGroup s1 43.54.31.%d 80" % (i))

        # Make 43.* traffic go down the second interface
        vpx_ns.cli("bind vlan 2 -IPAddress 43.54.30.1 255.255.0.0")
        vpx_ns.cli('save ns config')

    def setupSslFromTar(self, vpx_ns):
        sslTarFileUrl = xenrt.TEC().lookup('NS_BW_TEST_SSL_TAR',"http://files.uk.xensource.com/usr/groups/xenrt/ns_bw_testing/ssl.tar.gz")
        vpx_ns.extractTarToDir(sslTarFileUrl, "/nsconfig/ssl")

    def sampleCounters(self, vpx, ctrs, filename):
        stats = {ctr:xenrt.getURLContent("http://nsroot:nsroot@%s/nitro/v1/stat/%s" % (vpx.mainip, ctr)) for ctr in ctrs}
        self.log(filename, json.dumps(stats))

    def createWorkloadFile(self, vpx_ns):
        if self.workloadFileName not in self.WORKLOADS:
            raise xenrt.XRTError("Workload data not found for %s" % self.workloadFileName)

        tmpFile = xenrt.TEC().tempDir() + "/" + self.workloadFileName
        with open(tmpFile, 'w') as f:
            f.write(self.WORKLOADS[self.workloadFileName])

        wlFile = "%s/%s" % (self.remoteWLDir, self.workloadFileName)
        vpx_ns.cli("shell mkdir -p %s" % self.remoteWLDir)
        vpx_ns.getGuest().sftpClient(username='nsroot').copyTo(tmpFile, wlFile)
        self.workload = wlFile

    def createHttpServers(self, vpx_ns):
        vpx_ns.cli("shell /var/BW/nscsconfig -s server=%d -s serverip=43.54.31.2 -w %s -s ka=100 -s contentlen=100 -s chunked=0 -ye httpsvr" % (self.server_id, self.workload))

    def createHttpClients(self, vpx_ns):
        vpx_ns.cli("shell /var/BW/nscsconfig -s client=%d -s percentpers=100 -w %s -s cltserverip=43.54.30.247 -s threads=%d -s parallelconn=%d -ye start" % (self.client_id, self.workload, self.httpClientThreads, self.httpClientParallelconn))

    def showHttpServerClient(self, vpx_ns):
        vpx_ns.cli("shell /var/BW/nscsconfig -d allvcs")
        vpx_ns.cli("shell /var/BW/nscsconfig -d allurls")
        vpx_ns.cli("shell /var/BW/conntest -d validserver")

    def removeHttpServerClient(self, vpx_ns):
        vpx_ns.cli("shell /var/BW/nscsconfig -s client=%d -yE removeserver" % (self.client_id))
        vpx_ns.cli("shell /var/BW/nscsconfig -s server=%d -yE removeserver" % (self.server_id))
        vpx_ns.cli("shell /var/BW/conntest -s %d -yE stopall" % (self.server_id))

#### Testcase core methods ####
    def __init__(self):
        super(BlackWidowPerformanceTestCase, self).__init__(self.TEST)
        self.httpClientThreads = 0
        self.httpClientParallelconn = 0

    def parseArgs(self, arglist):
        # Performance Test Metrics
        self.runtime = libperf.getArgument(arglist, "runtime", int, 120) # duration over which to run the throughput test
        self.snips   = libperf.getArgument(arglist, "snips",   int, 50)  # number of NetScaler clients on the DUT
        self.servers = libperf.getArgument(arglist, "servers", int, 251) # number of HTTP servers
        self.clients = libperf.getArgument(arglist, "clients", int, 100) # number of HTTP clients

        if self.IS_VALID_CLIENTTHREADS :
            clientThreads = libperf.getArgument(arglist, "clientthreads", str, "50,100,200,300,500").split(",") # various client threads value
        if self.IS_VALID_CLIENTPARALLELCONN:
            clientParallelconn = libperf.getArgument(arglist, "clientparallelconn", str, "50,100,200,300,500").split(",") # various client parallelconn value
            if self.IS_VALID_CLIENTTHREADS and len(clientThreads)!=len(clientParallelconn):
                raise xenrt.XRTError("We expect number of values in args 'clientthreads' and 'clientparallelconn' to be same.")
        if self.IS_VALID_CLIENTTHREADS or self.IS_VALID_CLIENTPARALLELCONN:
            self.clientTnP = zip(clientThreads if self.IS_VALID_CLIENTTHREADS else clientParallelconn, clientParallelconn if self.IS_VALID_CLIENTPARALLELCONN else clientThreads)

        bw_name  = libperf.getArgument(arglist, "bw",  str, "blackwidow") # name of the VPX to use for BlackWidow
        dut_name = libperf.getArgument(arglist, "dut", str, "dut")        # name of the VPX to use as the device-under-test
        self.guest_bw  = xenrt.GEC().registry.guestGet(bw_name)
        self.guest_dut = xenrt.GEC().registry.guestGet(dut_name)

    def prepare(self, arglist=[]):
        self.parseArgs(arglist)
        self.workloadFileName = None
        self.workload = None
        self.remoteWLDir = "/var/BW/WL"
        self.dutProtocolVServer = "HTTP"
        # Identifiers used by nscsconfig
        self.server_id = 0 # higher numbers don't seem to result in a running server
        self.client_id = 1

        xenrt.TEC().logverbose("setting up %s as blackwidow..." % (self.guest_bw))
        self.ns_bw = self.getVPX(self.guest_bw)
        self.ns_bw.removeExistingSNIP()
        self.setupBlackWidow(self.ns_bw)

        xenrt.TEC().logverbose("setting up %s as DUT..." % (self.guest_dut))
        self.ns_dut = self.getVPX(self.guest_dut)
        self.ns_dut.removeExistingSNIP()
        self.setupDUT(self.ns_dut)

    def startWorkload(self):
        pass

    def runTest(self):
        raise xenrt.XRTError("Unimplemented")

    def stopWorkload(self):
        pass

    def run(self, arglist=[]):
        if self.IS_VALID_CLIENTTHREADS or self.IS_VALID_CLIENTPARALLELCONN:
            for t,p in self.clientTnP:
                step("Test segment started")
                if self.IS_VALID_CLIENTTHREADS:
                    self.httpClientThreads=int(t)
                    log("Test Parameter: httpClientThreads = %d" % (self.httpClientThreads))
                if self.IS_VALID_CLIENTPARALLELCONN:
                    self.httpClientParallelconn=int(p)
                    log("Test Parameter: httpClientParallelconn = %d" % (self.httpClientParallelconn))

                self.startWorkload()
                self.runTest()
                self.stopWorkload()
                step("Test segment finished")
        else:
            self.startWorkload()
            self.runTest()
            self.stopWorkload()

class TCHttp100KResp(BlackWidowPerformanceTestCase):
    TEST = "100K_resp"

    def prepare(self, arglist=[]):
        super(TCHttp100KResp, self).prepare(arglist)

        self.workloadFileName = "100KB.wl"
        self.statsToCollect = ["protocoltcp"]

    def startWorkload(self):
        step("startWorkload: create workload file")
        self.createWorkloadFile(self.ns_bw)

        step("startWorkload: create HTTP server(s?)")
        self.createHttpServers(self.ns_bw)

        step("startWorkload: create HTTP clients")
        self.createHttpClients(self.ns_bw)

        # Wait for the workload to get going
        xenrt.sleep(60)

    def runTest(self):
        now = time.time()
        finish = now + self.runtime
        i = 0

        step("runTest: sample the TCP counters on the DUT every 5 seconds")
        while now < finish:
            filename = "stat%s%s.%d.ctr" %(("_thd%d" % self.httpClientThreads) if self.IS_VALID_CLIENTTHREADS else "", ("_pc%d" % self.httpClientParallelconn) if self.IS_VALID_CLIENTPARALLELCONN else "", i )
            self.sampleCounters(self.guest_dut, self.statsToCollect, filename)
            self.log("sampletimes", "%d %f" % (i, now))

            # The counters only seem to be updated every ~5 seconds, so don't sample more often than that
            time.sleep(5)
            i = i + 1
            now = time.time()

    def stopWorkload(self):
        step("stopWorkload: show all running clients and servers")
        self.showHttpServerClient(self.ns_bw)

        step("stopWorkload: Stop the client and the server")
        self.removeHttpServerClient(self.ns_bw)

class TCHttp1BResp(TCHttp100KResp):
    """HTTP End-to-end req/sec"""
    TEST = "1B_Resp"

    def prepare(self, arglist=[]):
        super(TCHttp1BResp, self).prepare(arglist)

        self.workloadFileName = "1only.wl"
        self.statsToCollect = ["protocolhttp"]

    def createHttpClients(self, vpx_ns):
        vpx_ns.cli("shell /var/BW/nscsconfig -s client=%d -s percentpers=0 -s finstop=0 -w %s -s reqperconn=1 -s cltserverip=43.54.30.247 -s threads=%d -s parallelconn=%d -ye start" % (self.client_id, self.workload, self.httpClientThreads, self.httpClientParallelconn))

class TCTcpVipCps(TCHttp100KResp):
    """TCP Conn/sec (TCP VIP)"""
    TEST = "TCP_VIP_CPS"
    IS_VALID_CLIENTTHREADS = False

    def prepare(self, arglist=[]):
        super(TCTcpVipCps, self).prepare(arglist)

        self.workloadFileName = "1only.wl" # Any workload file will do.
        self.dutProtocolVServer = "TCP"
        self.statsToCollect = ["protocoltcp"]

    def createHttpClients(self, vpx_ns):
        vpx_ns.cli("shell /var/BW/conntest -s %d -p serverip=43.54.30.247 -p parallelconn=%d  -p serverport=80 -p holdconn=0 -y -e conntest" % (self.client_id, self.httpClientParallelconn))

class TCSslEncThroughput(TCHttp100KResp):
    TEST = "SSL Encrypted Throughput"

    def setupBlackWidow(self, vpx_ns):
        vpx_ns.multiCli(""" add servicegroup Loopback TCP
                            bind servicegroup Loopback 43.54.35.2 80
                            enable feature lb
                            add lb vserver v1 SSL_TCP 43.54.31.1 443
                            bind lb vserver v1 Loopback
                        """)
        vpx_ns.cli("add ip 43.54.180.10 255.255.0.0")
        vpx_ns.cli('save ns config')

    def setupDUT(self, vpx_ns):
        self.setupSslFromTar(vpx_ns)

        vpx_ns.multiCli(""" enable feature LB SSL ipv6pt
                            DISABLE FEATURE WL SP
                            DISABLE MODE EDGE L3 PMTU
                            enable ns mode MBF USNIP FR
                            set audit syslogparam -loglevel NONE
                            set dns parameter -nameLookupPriority DNS -cacheRecords NO
                            add ssl certkey c1 -cert server_cert.pem -key server_key.pem
                            add ssl certKey c2 -cert Cert2048 -key Key2048bit
                            set tcpparam -SACK DISABLED -WS DISABLED -ackOnPush DISABLED
                        """)
        vpx_ns.cli('add ssl certKey c3 -cert cert_4096.pem -key key_4096.key', level=xenrt.RC_OK)

        # Add SNIPs (the origin IP for requests travelling from NS to webserver)
        vpx_ns.multiCli("\n".join(["add ip 43.54.30.%d 255.255.0.0 -ty SNIP -mg en"%i for i in range(1,self.snips+1)]))

        # Make 43.* traffic go down the second interface
        vpx_ns.multiCli(""" bind vlan 2 -IPAddress 43.54.30.1 255.255.0.0
                            enable feat SSL LB
                        """)

        # Configure the vServers and bind it to the true servers
        for i in range(1,9):
            vpx_ns.cli("add lb vserver v%d SSL 43.54.30.%d 443 -lbmethod ROUNDROBIN"%(i,246+i) )
            vpx_ns.multiCli(""" bind ssl vserver v%d -certkey c2
                                set ssl vserver v%d -sessReuse ENABLED
                                add service s%d 43.54.3%d.254 HTTP 80
                                bind lb vser v%d s%d
                            """ % tuple([i]*6) )

        vpx_ns.cli('save ns config')

    def createHttpServers(self, vpx_ns):
        vpx_ns.cli("shell /var/BW/nscsconfig -s server=%d -s serverip=43.54.35.2 -s serverip_range=253 -s ka=100 -s contentlen=70 -s chunked=30 -w %s -ye httpsvr" % (self.server_id, self.workload))

    def createHttpClients(self, vpx_ns):
        vpx_ns.cli("shell /var/BW/nscsconfig -s client=%d -s cltserverport=443 -s ssl=1 -s ssl_sess_reuse_disable=0 -s ssl_dont_parse_server_cert=1 -s ssl_client_hello_version=2  -s percentpers=100 -w %s -s cltserverip=43.54.30.251 -s threads=%d -s parallelconn=%d -ye start" % (self.client_id, self.workload, self.httpClientThreads, self.httpClientParallelconn))

class TCSslTps1024(TCSslEncThroughput):
    TEST = "SSL TPS 1024bit Key"
    CERT = "c1"

    def setupBlackWidow(self, vpx_ns):
        super(TCSslTps1024, self).setupBlackWidow(vpx_ns)

        vpx_ns.multiCli(""" set ssl vserver v1 -sessReuse DISABLED
                            save ns config
                        """)

    def setupDUT(self, vpx_ns):
        vpx_ns.getGuest().shutdown()
        vpx_ns.getGuest().cpuset(4)
        vpx_ns.getGuest().memset(8192)
        vpx_ns.getGuest().lifecycleOperation('vm-start')
        vpx_ns.getGuest().waitForSSH(timeout=300, username='nsroot', cmd='shell')

        super(TCSslTps1024, self).setupDUT(vpx_ns)

        vpx_ns.cli("set ssl vserver v[1-8] -sessReuse DISABLED")
        vpx_ns.cli("bind ssl vserver v[1-8] -certkey %s"% self.CERT, level=xenrt.RC_OK)
        vpx_ns.cli("bind ssl cipher v[1-8] ORD SSL3-RC4-MD5", level=xenrt.RC_OK)
        vpx_ns.cli('save ns config')

    def prepare(self, arglist=[]):
        super(TCSslTps1024, self).prepare(arglist)

        self.workloadFileName = "1only.wl"
        self.statsToCollect = ["ssl"]

    def createHttpClients(self, vpx_ns):
        vpx_ns.cli("shell /var/BW/nscsconfig -s client=%d -s cltserverport=443 -s ssl=1 -s ssl_sess_reuse_disable=1 -s ssl_dont_parse_server_cert=1 -s ssl_client_hello_version=1 -s reqperconn=1 -s percentpers=0 -w %s -s cltserverip=43.54.30.251 -s threads=%d -s parallelconn=%d -s finstop=0 -ye start" % (self.client_id, self.workload, self.httpClientThreads, self.httpClientParallelconn))

class TCSslTps2K(TCSslTps1024):
    TEST = "SSL TPS 2048bit Key"
    CERT = "c2"

class TCSslTps4K(TCSslTps1024):
    TEST = "SSL TPS 4096bit Key"
    CERT = "c3"
