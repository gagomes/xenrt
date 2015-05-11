import xenrt, libperf
import os
import time
import urllib

# Install BlackWidow in a running NetScaler VPX VM
class TCBlackWidow(libperf.PerfTestCase):
    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCBlackWidow")

    def parseArgs(self, arglist):
        libperf.PerfTestCase.parseArgs(self, arglist)

        bw_name  = libperf.getArgument(arglist, "bw",  str, "blackwidow") # name of the VPX to use for BlackWidow
        dut_name = libperf.getArgument(arglist, "dut", str, "dut")        # name of the VPX to use as the device-under-test

        self.runtime = libperf.getArgument(arglist, "runtime", int, 120) # duration over which to run the throughput test
        self.snips   = libperf.getArgument(arglist, "snips",   int, 50)  # number of NetScaler clients on the DUT
        self.servers = libperf.getArgument(arglist, "servers", int, 251) # number of HTTP servers
        self.clients = libperf.getArgument(arglist, "clients", int, 100) # number of HTTP servers

        self.vpx_bw  = xenrt.GEC().registry.guestGet(bw_name)
        self.vpx_dut = xenrt.GEC().registry.guestGet(dut_name)

        self.configureVPX(self.vpx_bw)
        self.configureVPX(self.vpx_dut)

        # Identifiers used by nscsconfig
        self.server_id = 0 # higher numbers don't seem to result in a running server
        self.client_id = 1

    def configureVPX(self, vpx):
        vpx.password = 'nsroot'

    def setupBlackWidow(self, vpx):
        xenrt.TEC().logverbose("setting up %s as blackwidow..." % (vpx))
        vpx_ns = xenrt.lib.netscaler.NetScaler(vpx, None)

        # Remove existing SNIP
        existingSNIP = self.nscli(vpx_ns, "show ns ip | grep SNIP")[0].split('\t')[1].split(' ')[0]
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

    def setupDUT(self, vpx):
        xenrt.TEC().logverbose("setting up %s as DUT..." % (vpx))
        vpx_ns = xenrt.lib.netscaler.NetScaler(vpx, None)

        # Remove existing SNIP
        existingSNIP = self.nscli(vpx_ns, "show ns ip | grep SNIP")[0].split('\t')[1].split(' ')[0]
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

    def nscli(self, vpx, cmd):
        return vpx._NetScaler__netScalerCliCommand(cmd)

    def workloadFile(self):
        return """DEFINE_CLASSES
        BULK:   100
 
DEFINE_REQUESTS
 
        BULK:
                GET /wb30tree/100000_1.txt
 
"""

    def startBlackWidow(self, vpx):
        xenrt.TEC().logverbose("running blackwidow in %s..." % (vpx))
        vpx_ns = xenrt.lib.netscaler.NetScaler(vpx, None)

        workloadFilename = "100KB.wl"

        # Create workload file
        dir = xenrt.TEC().tempDir()
        wlFile = dir + "/" + workloadFilename
        f = open(wlFile, "w")
        f.write(self.workloadFile())
        f.close()

        remoteWLDir = "/var/BW/WL"
        fullpath = "%s/%s" % (remoteWLDir, workloadFilename)
        self.nscli(vpx_ns, "shell mkdir -p %s" % remoteWLDir)
        vpx.sftpClient(username='nsroot').copyTo(wlFile, fullpath)

        # Create the HTTP server(s?)
        self.nscli(vpx_ns, "shell /var/BW/nscsconfig -s server=%d -s serverip=43.54.31.2 -w %s -s ka=100 -s contentlen=100 -s chunked=0 -ye httpsvr" % (self.server_id, fullpath))

        # Create the HTTP clients
        self.nscli(vpx_ns, "shell /var/BW/nscsconfig -s client=%d -s percentpers=100 -w %s -s cltserverip=43.54.30.247 -s threads=500 -s parallelconn=500 -ye start" % (self.client_id, fullpath))

    def stopBlackWidow(self, vpx):
        xenrt.TEC().logverbose("stopping blackwidow in %s..." % (vpx))
        vpx_ns = xenrt.lib.netscaler.NetScaler(vpx, None)

        # Show all running clients and servers
        self.nscli(vpx_ns, "shell /var/BW/nscsconfig -d allvcs")
        self.nscli(vpx_ns, "shell /var/BW/nscsconfig -d allurls")

        # Stop the client and the server
        self.nscli(vpx_ns, "shell /var/BW/nscsconfig -s client=%d -yE removeserver" % (self.client_id))
        self.nscli(vpx_ns, "shell /var/BW/nscsconfig -s server=%d -yE removeserver" % (self.server_id))

    def prepare(self, arglist=[]):
        self.basicPrepare(arglist)

        self.setupBlackWidow(self.vpx_bw)
        self.setupDUT(self.vpx_dut)

    def getURL(self, url):
        sock = urllib.URLopener().open(url)
        resp = sock.read()
        sock.close()
        return resp

    def sampleCounters(self, vpx, ctr, filename):
        stats = self.getURL("http://nsroot:nsroot@%s/nitro/v1/stat/%s" % (vpx.mainip, ctr))
        self.log(filename, stats)

    def run(self, arglist=[]):
        self.startBlackWidow(self.vpx_bw)

        # Wait for the workload to get going
        xenrt.sleep(60)

        now = time.time()
        finish = now + self.runtime
        i = 0

        # While BW is running, sample the TCP counters on the DUT regularly
        while now < finish:
            self.sampleCounters(self.vpx_dut, "protocoltcp", "tcp.%d.ctr" % (i))
            self.log("sampletimes", "%d %f" % (i, now))

            # The counters only seem to be updated every ~5 seconds, so don't sample more often than that
            time.sleep(5)
            i = i + 1
            now = time.time()

        self.stopBlackWidow(self.vpx_bw)
