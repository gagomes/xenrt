import xenrt, libperf
import os, time, json
from xenrt.lazylog import step, comment, log, warning

class _BlackWidow(libperf.PerfTestCase):

    TEST = None
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

#### Black widow functional methods ####
    def configureVPX(self, vpx):
        vpx.password = 'nsroot'

    def nscli(self, vpx, cmd):
        return vpx.cli(cmd)

    def setupBlackWidow(self, vpx):
        xenrt.TEC().logverbose("setting up %s as blackwidow..." % (vpx))
        self.configureVPX(vpx)
        vpx_ns = xenrt.lib.netscaler.NetScaler(vpx, None)

        # Remove existing SNIP, if any
        snipLines = self.nscli(vpx_ns, "show ns ip | grep SNIP")
        for snipLine in snipLines:
            existingSNIP = snipLine.split('\t')[1].split(' ')[0]
            self.nscli(vpx_ns, "rm ns ip %s" % (existingSNIP))

        # Add HTTP client IPs
        for i in range(2, self.clients+1):
            self.nscli(vpx_ns, "add ns ip 43.54.181.%d 255.255.0.0 -vServer DISABLED" % (i))

        # Find the ID of the second VLAN
        vlan_ord = 2
        lines = self.nscli(vpx_ns, "show vlan")
        vlan_idx = next(line.split('\t')[1].split(' ')[2] for line in lines if line.startswith("%d)" % (vlan_ord)))

        # Make 43.* traffic go down the right interface
        self.nscli(vpx_ns, "bind vlan %s -IPAddress 43.54.181.2 255.255.0.0" % (vlan_idx))
        self.nscli(vpx_ns, 'save ns config')
        return vpx_ns

    def setupDUT(self, vpx):
        xenrt.TEC().logverbose("setting up %s as DUT..." % (vpx))
        self.configureVPX(vpx)
        vpx_ns = xenrt.lib.netscaler.NetScaler(vpx, None)

        # Remove existing SNIP, if any
        snipLines = self.nscli(vpx_ns, "show ns ip | grep SNIP")
        for snipLine in snipLines:
            existingSNIP = snipLine.split('\t')[1].split(' ')[0]
            self.nscli(vpx_ns, "rm ns ip %s" % (existingSNIP))

        # Add SNIPs (the origin IP for requests travelling from NS to webserver)
        for i in range(1, self.snips+1):
            self.nscli(vpx_ns, "add ns ip 43.54.30.%d 255.255.0.0 -vServer DISABLED -mgmtAccess ENABLED" % (i))

        # Add references to the HTTP server's IP addresses
        for i in range(2, self.servers+1):
            self.nscli(vpx_ns, "add server 43.54.31.%d 43.54.31.%d" % (i, i))

        # Configure the vServer on 43.54.30.247 and bind it to the true servers
        self.nscli(vpx_ns, "add serviceGroup s1 HTTP -maxClient 0 -maxReq 0 -cip DISABLED -usip NO -useproxyport YES -cltTimeout 180 -svrTimeout 360 -CKA NO -TCPB NO -CMP NO")
        self.nscli(vpx_ns, "enable ns feature LB")
        self.nscli(vpx_ns, "add lb vserver v1 HTTP 43.54.30.247 80 -persistenceType NONE -lbMethod ROUNDROBIN -cltTimeout 18")
        self.nscli(vpx_ns, "bind lb vserver v1 s1")
        for i in range(2, self.servers+1):
            self.nscli(vpx_ns, "bind serviceGroup s1 43.54.31.%d 80" % (i))

        # Make 43.* traffic go down the second interface
        self.nscli(vpx_ns, "bind vlan 2 -IPAddress 43.54.30.1 255.255.0.0")
        self.nscli(vpx_ns, 'save ns config')
        return vpx_ns

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
        self.nscli(vpx_ns, "shell mkdir -p %s" % self.remoteWLDir)
        vpx_ns.getGuest().sftpClient(username='nsroot').copyTo(tmpFile, wlFile)
        self.workload = wlFile

    def createHttpServers(self, vpx_ns):
        self.nscli(vpx_ns, "shell /var/BW/nscsconfig -s server=%d -s serverip=43.54.31.2 -w %s -s ka=100 -s contentlen=100 -s chunked=0 -ye httpsvr" % (self.server_id, self.workload))

    def createHttpClients(self, vpx_ns):
        self.nscli(vpx_ns, "shell /var/BW/nscsconfig -s client=%d -s percentpers=100 -w %s -s cltserverip=43.54.30.247 -s threads=%d -s parallelconn=%d -ye start" % (self.client_id, self.workload, self.httpClientThreads, self.httpClientParallelconn))

    def showHttpServerClient(self, vpx_ns):
        self.nscli(vpx_ns, "shell /var/BW/nscsconfig -d allvcs")
        self.nscli(vpx_ns, "shell /var/BW/nscsconfig -d allurls")

    def removeHttpServerClient(self, vpx_ns):
        self.nscli(vpx_ns, "shell /var/BW/nscsconfig -s client=%d -yE removeserver" % (self.client_id))
        self.nscli(vpx_ns, "shell /var/BW/nscsconfig -s server=%d -yE removeserver" % (self.server_id))

#### Testcase core methods ####
    def parseArgs(self, arglist):
        # Performance Test Metrics
        self.runtime = libperf.getArgument(arglist, "runtime", int, 120) # duration over which to run the throughput test
        self.snips   = libperf.getArgument(arglist, "snips",   int, 50)  # number of NetScaler clients on the DUT
        self.servers = libperf.getArgument(arglist, "servers", int, 251) # number of HTTP servers
        self.clients = libperf.getArgument(arglist, "clients", int, 100) # number of HTTP servers
        self.httpClientThreads = libperf.getArgument(arglist, "httpclientthread", int, 500) # number of HTTP client threads
        self.httpClientParallelconn = libperf.getArgument(arglist, "httpclientparallelconn", int, 500) # number of HTTP client parallel connections

        bw_name  = libperf.getArgument(arglist, "bw",  str, "blackwidow") # name of the VPX to use for BlackWidow
        dut_name = libperf.getArgument(arglist, "dut", str, "dut")        # name of the VPX to use as the device-under-test
        self.guest_bw  = xenrt.GEC().registry.guestGet(bw_name)
        self.guest_dut = xenrt.GEC().registry.guestGet(dut_name)

    def prepare(self, arglist):
        self.parseArgs(arglist)
        self.workloadFileName = None
        self.workload = None
        self.remoteWLDir = "/var/BW/WL"
        # Identifiers used by nscsconfig
        self.server_id = 0 # higher numbers don't seem to result in a running server
        self.client_id = 1

        self.ns_bw  = self.setupBlackWidow(self.guest_bw)
        self.ns_dut = self.setupDUT(self.guest_dut)

    def startWorkload(self):
        pass

    def runTest(self):
        raise xenrt.XRTError("Unimplemented")

    def stopWorkload(self):
        pass

    def run(self, arglist=[]):
        self.startWorkload()
        self.runTest()
        self.stopWorkload()

class TCHttp100KResp(_BlackWidow):
    TEST = "100K_resp"

    def __init__(self):
        _BlackWidow.__init__(self, self.TEST)

    def prepare(self, arglist=[]):
        _BlackWidow.prepare(self, arglist=[])

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
            self.sampleCounters(self.guest_dut, self.statsToCollect, "tcp.%d.ctr" % (i))
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
    TEST = "1B_Resp"

    def prepare(self, arglist=[]):
        _BlackWidow.prepare(self, arglist=[])

        # Overwritting defaults for threads and parallelconn
        self.httpClientThreads = libperf.getArgument(arglist, "httpclientthread", int, 200)
        self.httpClientParallelconn = libperf.getArgument(arglist, "httpclientparallelconn", int, 200)

        self.workloadFileName = "1only.wl"
        self.statsToCollect = ["protocolhttp"]

    def createHttpClients(self, vpx_ns):
        self.nscli(vpx_ns, "shell /var/BW/nscsconfig -s client=%d -s percentpers=0 -s finstop=0 -w %s -s reqperconn=1 -s cltserverip=43.54.30.247 -s threads=%d -s parallelconn=%d -ye start" % (self.client_id, self.workload, self.httpClientThreads, self.httpClientParallelconn))
