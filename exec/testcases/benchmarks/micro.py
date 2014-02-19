#
# XenRT: Test harness for Xen and the XenServer product family
#
# Microbenchmarks
#
# Copyright (c) Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import sys, string, os.path, re, time
import xenrt

class TClmbench(xenrt.TestCaseWrapper):

    needs = ["gcc", "make"]
    
    def __init__(self, tcid="TClmbench"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="lmbench")

class TCpassmark(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCpassmark"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="passmark")

    def runViaDaemon(self, remote, arglist):
        if not xenrt.checkTarball("perftest.tgz"):
            xenrt.TEC().skip("Test tarball not found")
            return

        workdir = remote.xmlrpcTempDir()
        xenrt.TEC().logverbose("Using temporary directory: %s" % (workdir))
        remote.xmlrpcUnpackTarball("%s/perftest.tgz" %
                          (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                           workdir)
        try:
            remote.xmlrpcRemoveFile("c:\\results.csv")
        except:
            pass
        remote.xmlrpcExec("%s\\perftest\\pt.exe /s %s\\perftest\\script.txt /i" %
                          (workdir, workdir), timeout=600)

        # Process results.
        data = str(remote.xmlrpcReadFile("c:\\results.csv")).strip()
        headers = data.split("\r\n")[0].split(",")[1:]
        values = data.split("\r\n")[1].split(",")[1:]
        headers.remove('')
        values.remove('')
        for i in range(len(headers)):
            self.tec.value(headers[i], values[i])

class TCiometer(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCiometer"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="iometer")
        self.storedguest = None

    def runViaDaemon(self, remote, arglist):

        testtype = "default"
        if arglist and len(arglist) > 0:
            testtype = arglist[0]

        guest = remote
        self.storedguest = guest

        # Get a working directory on the guest
        workdir = guest.xmlrpcTempDir()

        # Unpack the test binaries
        guest.xmlrpcUnpackTarball("%s/iometer.tgz" %
                          (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                          workdir)

        # IOmeter registry settings - this prevents the license agreement
	# dialog from causing the test to hang.
        guest.winRegAdd("HKCU",
                        "Software\\iometer.org\\Iometer\\Recent File List",
                        "dummy",
                        "SZ",
                        "")
        guest.winRegDel("HKCU",
                        "Software\\iometer.org\\Iometer\\Recent File List",
                        "dummy")
        guest.winRegAdd("HKCU",
                        "Software\\iometer.org\\Iometer\\Settings",
                        "Version",
                        "SZ",
                        "2004.07.30")
        
        # Let iometer through the firewall.
        try:
            guest.xmlrpcExec('NETSH firewall set allowedprogram '
                             'program="%s\\iometer\\iometer.exe" '
                             'name="Iometer Control/GUI" mode=ENABLE' %
                             (workdir))
        except:
            xenrt.TEC().comment("Error disabling firewall")
        try:
            guest.xmlrpcExec('NETSH firewall set allowedprogram '
                             'program="%s\\iometer\\dynamo.exe" '
                             'name="Iometer Workload Generator" mode=ENABLE' %
                             (workdir))
        except:
            xenrt.TEC().comment("Error disabling firewall")

        # Run the benchmark
        stems = []
        for icf in guest.xmlrpcGlobPattern("%s\\iometer\\%s\\*.icf" %
                                   (workdir, testtype)):
            stem = os.path.basename(string.replace(icf, '\\', '/'))[:-4]
            guest.xmlrpcExec("cd %s\\iometer\n"
                             "%s\\iometer\\iometer.exe /c %s\\%s.icf /r "
                             "..\\%s.csv" %
                             (workdir, workdir, testtype, stem, stem),
                             timeout=7200)
            stems.append(stem)

        # Gather the results
        fields = []
        try:
            data = guest.xmlrpcReadFile("%s\\iometer\\%s\\fields.cfg" %
                                        (workdir, testtype))
            for f in string.split(data, "\n"):
                ll = string.split(f)
                if len(ll) >= 3:
                    fields.append((ll[0], ll[1], ll[2]))
        except:
            pass
        if len(stems) == 0:
            raise xenrt.XRTError("No result files generated")
        data = None
        results = []
        for stem in stems:
            try:
                data = guest.xmlrpcReadFile("%s\\%s.csv" % (workdir, stem))
            except:
                raise xenrt.XRTFailure("Result file for %s not found" % (stem))
            f = file("%s/%s.csv" % (self.tec.getLogdir(), stem), "w")
            f.write(data)
            f.close()
            results.extend(self.parseResults(data, stem))

        # Output the results
        if len(fields) == 0:
            # Just output the raw data
            mbps = ["MBps",
                    "Read_MBps",
                    "Write_MBps"]
            ms = ["Average_Response_Time",
                  "Average_Read_Response_Time",
                  "Average_Write_Response_Time",
                  "Average_Transaction_Time",
                  "Average_Connection_Time",
                  "Maximum_Response_Time",
                  "Maximum_Read_Response_Time",
                  "Maximum_Write_Response_Time",
                  "Maximum_Transaction_Time",
                  "Maximum_Connection_Time"]
            ps = ["Connections_per_Second",
                  "Interrupts_per_Second"
                  "Packets/Second",
                  "Transactions_per_Second"]
            units = ["IOps",
                     "Read_I/Os",
                     "Read_IOps",
                     "Write_I/Os",
                     "Write_IOps"]
            for result in results:
                stem, var, value = result
                if var in mbps:
                    self.tec.value(var, value, "Mb/s")
                elif var in ms:
                    self.tec.value(var, value, "ms")
                elif var in ps:
                    self.tec.value(var, value, "/s")
                elif var in units:
                    self.tec.value(var, value, "units")
                else:
                    self.tec.value(var, value)
        else:
            # check fields.cfg
            r = {}
            for result in results:
                stem, var, value = result
                r[(stem, var)] = value
            for field in fields:
                stem, var, tag = field
                if r.has_key((stem, var)):
                    self.tec.value(tag, r[(stem, var)])

    def parseResults(self, data, stem):
        reply = []
        tsc = 0
        lines = string.split(data, "\n")
        for i in range(len(lines)):
            if lines[i][0:8] == "'Results":
                labels = string.split(lines[i+1][1:], ",")
                values = string.split(lines[i+2][1:], ",")
                for j in range(min(len(labels), len(values))):
                    try:
                        v = float(values[j])
                        l = string.replace(labels[j], " ", "_")
                        reply.append((stem, l, v))
                    except:
                        pass
            elif lines[i][0:8] == "'Time Stamp":
                tsc = tsc + 1
        if tsc != 0:
            # Apparently the appearance of two time stamps indicates a pass.
            raise xenrt.XRTFailure("No completion timestamp found for %s" %
                                   (stem))
        return reply
                

    def postRun(self):
        if self.storedguest:
            try:
                self.storedguest.xmlrpcExec("del c:\\iobw.tst")            
            except:
                pass
            try:
                self.storedguest.xmlrpcKillAll("iometer.exe")
            except:
                pass

class TCttcpbw2(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCttcpbw2"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="ttcpbw")
        
class TCttcpbw(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCttcpbw"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="ttcpbw")
        self.ssh = False
        self.ttcp = None
        self.ttcptype = "ttcp"
        self.peer = None

    def install(self, remote):

        if self.ssh:
            workdir = string.strip(remote.execcmd("mktemp -d /tmp/XXXXXX"))
        else:
            workdir = remote.xmlrpcTempDir()

        self.getLogsFrom(remote)

        # Unpack the test binaries
        if self.ssh:
            remote.execcmd("wget '%s/ttcpbw.tgz' -O - | tar -zx -C %s" %
                           (xenrt.TEC().lookup("TEST_TARBALL_BASE"), workdir))
        else:
            remote.xmlrpcUnpackTarball(\
                "%s/ttcpbw.tgz" %
                (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                workdir)

        if remote.windows:
            if self.ssh:
                self.ttcp = "%s/ttcpbw/PCATTCP.exe" % (workdir)
            else:
                self.ttcp = "%s\\ttcpbw\\PCATTCP.exe" % (workdir)
            self.ttcptype = "pca"
        else:
            remote.execcmd("make -C %s/ttcpbw" % (workdir))
            self.ttcp = "%s/ttcpbw/ttcp" % (workdir)
        
    def runViaDaemon(self, remote, arglist):
        return self.runTTCP(remote, arglist, False)
    
    def runLegacy(self, remote, arglist):
        return self.runTTCP(remote, arglist, True)

    def runTTCP(self, remote, arglist, ssh):
        self.ssh = ssh
        self.firewall = False
        self.remote = remote

        mtus = "1496,552"
        buffers = 50000
        size = 8192
        socks = "131072"
        reps = 9
        nomtu = False

        if arglist:
            for arg in arglist:
                l = string.split(arg, "=", 1)
                if l[0] == "mtu":
                    mtus = l[1]
                elif l[0] == "buffers":
                    buffers = int(l[1])
                elif l[0] == "size":
                    size = int(l[1])
                elif l[0] == "reps":
                    reps = int(l[1])
                elif l[0] == "nomtu":
                    nomtu = True

        # Get a TTCP peer
        peer = xenrt.NetworkTestPeer()
        self.peer = peer
        try:
            peer.runCommand("killall ttcp")
        except:
            pass

        self.tec.comment("%u buffers of %u bytes" % (buffers, size))
        self.tec.comment("MTUs %s" % (mtus))
        self.tec.comment("Peer %s" % (peer.getAddress()))

        # Install TTCP on the remote
        self.install(remote)

        # Disable firewalls etc.
        if remote.windows:
            try:
                remote.xmlrpcExec('NETSH firewall set allowedprogram '
                                  'program="%s" name="TTCP" mode=ENABLE' %
                                  (self.ttcp))
            except:
                xenrt.TEC().comment("Error disabling firewall")
        else:
            try:
                if not remote.execcmd("/etc/init.d/iptables status", retval="code"):
                    self.firewall = True
                    remote.execcmd("/etc/init.d/iptables stop")
            except:
                pass

        # Run the tests
        try:
            for mtustr in string.split(mtus, ","):
                if mtustr == "default":
                    mtu = 0
                else:
                    mtu = int(mtustr)
                if not nomtu:
                    if mtu:
                        peer.runCommand("/sbin/ifconfig eth0 mtu %u" % (mtu))
                    else:
                        peer.runCommand("/sbin/ifconfig eth0 mtu 1500")
                for sockstr in string.split(socks, ","):
                    sock = int(sockstr)
                    tx = []
                    rx = []
                    for i in range(reps):
                        v = self.doTX(peer, remote, mtu, sock, buffers, size)
                        tx.append(v)
                        self.tec.appresult("TX:%u:%u (%u) %f" %
                                           (sock, mtu, i, v))
                        v = self.doRX(peer, remote, mtu, sock, buffers, size)
                        rx.append(v)
                        self.tec.appresult("RX:%u:%u (%u) %f" %
                                           (sock, mtu, i, v))
                    v = xenrt.median(tx)
                    self.tec.value("TX:%u:%u" % (sock, mtu), v, "MB/s")
                    v = xenrt.median(rx)
                    self.tec.value("RX:%u:%u" % (sock, mtu), v, "MB/s")
        finally:
            if not nomtu:
                peer.runCommand("/sbin/ifconfig eth0 mtu 1500")

    def doTX(self, peer, remote, mtu, sock, buffers, size):
        """Transmit from <remote> to the peer"""
        # Start a listener on the peer
        s = peer.startCommand("ttcp -r -fm -s -n %u -b %u -l %u" %
                              (buffers, sock, size))
        time.sleep(15)

        # Run a transmitter on remote
        c = [self.ttcp]
        if self.ttcptype == "ttcp":
            c.extend(["-t", peer.getAddress()])
            c.extend(["-fm", "-s", "-n %u" % (buffers), "-b %u" % (sock)])
            c.extend(["-l %u" % (size)])
        else:
            c.extend(["-t", "-n%u" % (buffers), "-l %u" % (size)])
            c.extend(["-b %u" % (sock), peer.getAddress()])
        c = [ x.strip() for x in c ]
        if self.ssh:
            tx = remote.execcmd(string.join(c))
        else:
            tx = remote.xmlrpcExec(string.join(c), timeout=7200)

        # Get data back from the peer
        rx = peer.readCommand(s)
        print tx, rx
        return self.parseRate(rx)

    def doRX(self, peer, remote, mtu, sock, buffers, size):
        """Transmit from the peer to <remote>"""
        # Start a listener on remote
        c = [self.ttcp]
        if self.ttcptype == "ttcp":
            c.extend(["-r", "-fm", "-s"])
            c.extend(["-n %u" % (buffers), "-b %u" % (sock), "-l %u" % (size)])
        else:
            c.extend(["-r", "-n%u" % (buffers), "-l %u" % (size)])
            c.extend(["-b %u" % (sock)])
        if self.ssh:
            outfile = string.strip(remote.execcmd("mktemp /tmp/XXXXXX"))
            remote.execcmd("%s > %s 2>&1 < /dev/null &" %
                           (string.join(c), outfile))
        else:
            s = remote.xmlrpcStart(string.join(c))
        time.sleep(15)

        # Run a transmitter on the peer
        tx = peer.runCommand("ttcp -t %s -fm -s -n %u -b %u -l %u" %
                             (remote.getIP(), buffers, sock, size))

        # Get data back from the remote
        if self.ssh:
            rx = remote.execcmd("cat %s" % (outfile))
        else:
            rx = remote.xmlrpcWait(s, returndata=True, timeout=60)
        print tx, rx
        return self.parseRate(tx)

    def parseRate(self, data):
        r = re.search(r"([0-9\.]+) Mbit/sec \+\+\+", data)
        if r:
            return float(r.group(1))
        r = re.search(r"([0-9\.]+) KB/sec \+\+\+", data)
        if r:
            return float(r.group(1))/128.0
        return 0.0

    def postRun(self):
        if self.peer:
            self.peer.release()
            self.peer = None
        if self.firewall:
            if self.remote.windows:
                pass
            else:
                self.remote.execcmd("/etc/init.d/iptables start")
        try:
            if self.remote.windows and not self.ssh:
                self.remote.xmlrpcKillAll("PCATTCP.exe")
        except:
            pass
                

class TCbonnie(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCbonnie"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="bonnie++")

class TCiozone(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCiozone"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="iozone")

    def parseThroughputResults(self, log):
        tags = {"initial"           : "Initial_writer_throughput",
                "rewriters"         : "Rewriter_throughput",
                "[0-9]+ readers"    : "Reader_throughput", 
                "re-readers"        : "Rereader_throughput",
                "reverse"           : "Reverse_reader_throughput",
                "random readers"    : "Random_reader_throughput",
                "stride readers"    : "Stride_reader_throughput",
                "mixed"             : "Mixed_throughput",
                "random writers"    : "Random_writer_throughput",
                "pwrite"            : "Pwrite_throughput",
                "pread"             : "Pread_throughput"}

        x = False
        for key in tags.keys():
            value = None
            for line in log.split("\n"):
                if re.search("Children", line):
                    if re.search(key, line):
                        x = True
                    else:
                        x = False
                elif re.search("Avg", line):
                    if x:
                        value = re.search("[0-9\.]+", line).group()
            if value:            
                xenrt.TEC().value(tags[key], value, "kb/s")
            else:
                xenrt.TEC().comment("No value found for %s - %s" %
                                   (tags[key], key))
  
    def parseAutoResults(self, log):
        # The numbers are the columns corresponding to the
        # labels.
        tags = {3   :   "WRT_NEW",
                4   :   "WRT_EXT",
                5   :   "RD_EXT",
                6   :   "RD_REC",
                7   :   "RD_RAND",
                8   :   "WRT_RAND",
                9   :   "RD_BACK",
                10  :   "RE_WRT",
                11  :   "RD_STRD",
                12  :   "FWR_NEW",
                13  :   "RE_FWR",
                14  :   "FREAD",
                15  :   "RE_FREAD"}
    
        data = ""
        for line in log.split("\n"):
            if not re.search("[A-Za-z]", line):
                if re.search("[0-9]", line):
                    data = data + line + "\n"
        values = [ re.split("[ ]+", l) for l in data.split("\n") ]
        # Get rid of empty list at the end.
        values.pop()
        for key in tags.keys():
            value = "%.2f" % (sum(\
                    [ float(v[key]) for v in values]) / 1024 / len(values))
            xenrt.TEC().value(tags[key], value, "kb/s") 
 
    def auto(self):
        timeout = 7200
        if xenrt.TEC().lookup("EXTRA_TIME", False, boolean=True):
            timeout = timeout * 4
        if self.benchmark:
            autolog = \
                self.guest.xmlrpcExec(\
                    "%s\\iozone\\iozone.exe %s -a" % (self.workdir, 
                                                      self.verify),
                     returndata=True, timeout=timeout)
        else: 
            autolog = \
                self.guest.xmlrpcExec(\
                    "%s\\iozone\\iozone.exe %s -i 0 -a" % (self.workdir,
                                                           self.verify),
                     returndata=True, timeout=timeout)
        
        if not re.search("iozone test complete", autolog):
            raise xenrt.XRTFailure("Auto test failed.")

        if not self.verify:
            self.parseAutoResults(autolog)

    def throughput(self):
        timeout = 14400
        if xenrt.TEC().lookup("EXTRA_TIME", False, boolean=True):
            timeout = timeout * 2
        if self.benchmark:
            tputlog = \
                self.guest.xmlrpcExec(\
                    "%s\\iozone\\iozone.exe %s -t %s" % (self.workdir, 
                                                         self.verify,
                                                         self.threads),
                     returndata=True, timeout=timeout)
        else: 
            tputlog = \
                self.guest.xmlrpcExec(\
                    "%s\\iozone\\iozone.exe %s -t %s -i 0" % (self.workdir, 
                                                              self.verify,
                                                              self.threads),
                     returndata=True, timeout=timeout)

        if not re.search("iozone test complete", tputlog):
            raise xenrt.XRTFailure("Throughput test failed.")

        if not self.verify:
            self.parseThroughputResults(tputlog)

    def runViaDaemon(self, remote, arglist):
        
        self.benchmark = True
        self.verify = "" 
        self.threads = 4

        if arglist and len(arglist) > 0:
            for arg in arglist:
                l = string.split(arg, "=", 1)
                if l[0] == "benchmark":
                    self.benchmark = True
                elif l[0] == "quick":
                    self.benchmark = False  
                elif l[0] == "verify":
                    self.verify = "-V 1234"

        self.guest = remote

        self.workdir = self.guest.xmlrpcTempDir()
        self.guest.xmlrpcUnpackTarball("%s/%s.tgz" %
                          (xenrt.TEC().lookup("TEST_TARBALL_BASE"),
                           self.testname),
                           self.workdir) 

        self.guest.xmlrpcExec("copy %s\\iozone\\cygwin1.dll " % (self.workdir) + \
                              "C:\\Windows\\System32\\cygwin1.dll")
        self.guest.xmlrpcExec("copy %s\\iozone\\sh.exe " % (self.workdir) + \
                              "C:\\Windows\\sh.exe")
        try:
            self.guest.xmlrpcExec("net stop opensshd")
        except:
            pass

        self.declareTestcase("WindowsGuest", "auto")
        self.declareTestcase("WindowsGuest", "throughput")

        self.runSubcase("auto", (), "WindowsGuest", "auto")
        try:
            self.guest.xmlrpcKillAll("iozone.exe")
        except:
            pass
        self.runSubcase("throughput", (), "WindowsGuest", "throughput")

    def postRun(self):
        try:
            self.guest.xmlrpcKillAll("iozone.exe")
        except:
            pass
        self.guest.xmlrpcExec("del c:\\windows\\system32\\cygwin1.dll")
        try:
            self.guest.xmlrpcExec("net start opensshd")
        except:
            try:
                self.guest.xmlrpcExec("net start opensshd")
            except:
                pass

class TCprime95(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCprime95"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="prime95")
        self.storedguest = None

    def runViaDaemon(self, remote, arglist):

        duration = 3600
        if arglist and len(arglist) > 0:
            duration = int(arglist[0])

        guest = remote
        self.storedguest = guest

        # Get a working directory on the guest
        workdir = guest.xmlrpcTempDir()

        # Unpack the test binaries
        guest.xmlrpcUnpackTarball("%s/%s.tgz" %
                          (xenrt.TEC().lookup("TEST_TARBALL_BASE"),
                           self.testname),
                          workdir)

        # Start the test
        id = guest.xmlrpcStart("cd %s\\prime95\nprime95.exe -t" % (workdir))
        started = xenrt.timenow()
        finishat = started + duration
        time.sleep(30)
        if guest.xmlrpcPoll(id):
            raise xenrt.XRTError("prime95 did not start properly")

        # Wait for the specified duration
        while finishat > xenrt.timenow():
            if guest.xmlrpcPoll(id):
                raise xenrt.XRTFailure("prime95 has stopped running")
            time.sleep(30)

        # Kill it
        guest.xmlrpcKillAll("prime95.exe")
        time.sleep(10)
        if not guest.xmlrpcPoll(id):
            raise xenrt.XRTError("prime95 did not terminate properly")

    def postRun(self):
        if self.storedguest:
            self.storedguest.xmlrpcKillAll("prime95.exe")

class TCnetperf(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCnetperf"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="netperf")
        self.ssh = False
        self.peer = None

    def runViaDaemon(self, remote, arglist):
        return self.runNetperf(remote, arglist, False)
    
    def runLegacy(self, remote, arglist):
        return self.runNetperf(remote, arglist, True)

    def runNetperf(self, remote, arglist, ssh):
        self.ssh = ssh
        self.firewall = False
        self.remote = remote

        mtus = "1496,552"
        socks = "131072"
        duration = 20
        reps = 3
        protocols = ["TCP"]
        nomtu = False
        tcprr = False        

        if arglist:
            for arg in arglist:
                l = string.split(arg, "=", 1)
                if l[0] == "mtu":
                    mtus = l[1]
                elif l[0] == "reps":
                    reps = int(l[1])
                elif l[0] == "protocols":
                    protocols = string.split(l[1], ",")
                elif l[0] == "nomtu":
                    nomtu = True
                    mtus = "1496"
                elif l[0] == "rr":
                    tcprr = True

        # Get a peer
        shared = xenrt.TEC().lookup("NETWORK_PEER_SHARED", False, boolean=True)
        try:
            peer = xenrt.NetworkTestPeer(shared=shared)
        except xenrt.XRTError, e:
            if re.search("Timed out", e.reason):
                xenrt.TEC().skip("Timed out waiting for peer.")
                return
            elif re.search("No TTCP_PEERS defined", e.reason):
                xenrt.TEC().skip(e.reason)
                return
            else:
                raise e
            
        self.peer = peer

        self.tec.comment("MTUs %s" % (mtus))
        self.tec.comment("Peer %s" % (peer.getAddress()))

        # Install (if not already) netperf on the remote
        remote.installNetperf()

        # Disable firewalls etc.
        if remote.windows:
            if remote.xmlrpcWindowsVersion() == "5.0":
                xenrt.TEC().skip("Skipping Netperf on Windows 2000")
                return
            try:
                remote.xmlrpcExec('NETSH firewall set allowedprogram '
                                  'program="C:\\netperf.exe" name="netperf"'
                                  ' mode=ENABLE')
            except:
                xenrt.TEC().comment("Error disabling firewall")
        else:
            try:
                if not remote.execcmd("/etc/init.d/iptables status", retval="code"):
                    self.firewall = True
                    remote.execcmd("/etc/init.d/iptables stop")
            except:
                pass

        # Run the tests
        failures = []
        try:
            for mtustr in string.split(mtus, ","):
                if mtustr == "default":
                    mtu = 0
                else:
                    mtu = int(mtustr)
                if not nomtu:
                    if mtu:
                        peer.runCommand("/sbin/ifconfig eth0 mtu %u" % (mtu))
                    else:
                        peer.runCommand("/sbin/ifconfig eth0 mtu 1500")
                for sockstr in string.split(socks, ","):
                    sock = int(sockstr)
                    tx = []
                    rx = []
                    rr = []
                    txudp = []
                    for i in range(reps):
                        if "TCP" in protocols:
                            try:
                                v, c = self.doTest(peer,
                                                   remote,
                                                   sock,
                                                   duration,
                                                   "TCP_STREAM")
                                tx.append(v)
                                self.tec.appresult("TX:TCP:%u:%u (%u) %f" %
                                                   (sock, mtu, i, v))
                            except xenrt.XRTException, e:
                                failures.append(e)
                            try:
                                v, c = self.doTest(peer,
                                                   remote,
                                                   sock,
                                                   duration,
                                                   "TCP_MAERTS")
                                rx.append(v)
                                self.tec.appresult("RX:TCP:%u:%u (%u) %f" %
                                                   (sock, mtu, i, v))
                            except xenrt.XRTException, e:
                                failures.append(e)
                            if tcprr:
                                try:
                                    v, c = self.doTest(peer,
                                                       remote,
                                                       sock,
                                                       duration,
                                                       "TCP_RR")
                                    rr.append(v)
                                    self.tec.appresult("RR:TCP:%u:%u (%u) %f" %
                                                       (sock, mtu, i, v))
                                except xenrt.XRTException, e:
                                    failures.append(e)
                        if "UDP" in protocols:
                            try:
                                v, c = self.doTest(peer,
                                                   remote,
                                                   sock,
                                                   duration,
                                                   "UDP_STREAM")
                                txudp.append(v)
                                self.tec.appresult("TX:UDP:%u:%u (%u) %f" %
                                                   (sock, mtu, i, v))
                            except xenrt.XRTException, e:
                                failures.append(e)
                    if "TCP" in protocols:
                        v = xenrt.median(tx)
                        self.tec.value("TX:TCP:%u:%u" % (sock, mtu), v, "MB/s")
                        v = xenrt.median(rx)
                        self.tec.value("RX:TCP:%u:%u" % (sock, mtu), v, "MB/s")
                        if tcprr:
                            v = xenrt.median(rr)
                            self.tec.value("RR:TCP:%u:%u" % (sock, mtu), v, "t/s")
                    if "UDP" in protocols:
                        v = xenrt.median(txudp)
                        self.tec.value("TX:UDP:%u:%u" % (sock, mtu), v, "MB/s")
        finally:
            if not nomtu:
                peer.runCommand("/sbin/ifconfig eth0 mtu 1500")
        if len(failures) == 1:
            raise failures[0]
        elif len(failures) > 1:
            for f in failures:
                xenrt.TEC().reason(f.reason)
            raise xenrt.XRTFailure("%u failures encountered" % (len(failures)))
        
    def doTest(self, peer, remote, sock, duration, test="TCP_STREAM"):
        args = []
        args.append("-f m")
        # netperf tool has timing issues affecting using confidence intervals.
        # http://www.netperf.org/pipermail/netperf-talk/2011-July/thread.html
        # args.append("-i 9,3")
        args.append("-t %s" % (test))
        args.append("-H %s" % (peer.getAddress()))
        args.append("-l %u" % (duration))
        args.append("-c")
        args.append("--")
        args.append("-s %u" % (sock))
        args.append("-S %u" % (sock))
        
        if self.ssh:
            tx = remote.execcmd("netperf %s" % (string.join(args)))
        else:
            tx = remote.xmlrpcExec("c:\\netperf.exe %s" % (string.join(args)),
                                   returndata=True,
                                   timeout=2800)
        return self.parseRate(tx)

    def parseRate(self, data):
        for line in string.split(data, "\n"):
            if re.search(r"^\s*\d+", line):
                l = string.split(line)
                if len(l) == 9:
                    return (float(l[4]), float(l[5]))
                if len(l) == 10:
                    return (float(l[5]), float(l[6]))
        raise xenrt.XRTError("Could not parse netperf output")

    def postRun(self):
        if self.peer:
            self.peer.release()
            self.peer = None
        if self.firewall:
            if self.remote.windows:
                pass
            else:
                self.remote.execcmd("/etc/init.d/iptables start")

        try:
            if self.remote.windows and not self.ssh:
                self.remote.xmlrpcKillAll("netperf.exe")
        except:
            pass

