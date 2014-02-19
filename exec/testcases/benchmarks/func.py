#
# XenRT: Test harness for Xen and the XenServer product family
#
# Functional tests
#
# Copyright (c) Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import sys, string, re, time, xml.dom.minidom, os, os.path
from xml.parsers.expat import ExpatError
import xenrt

class TCltp(xenrt.TestCaseWrapper):

    needs = ["gcc", "make", "flex"]
    
    def __init__(self, tcid="TCltp"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="ltp")

class TCvm86(xenrt.TestCaseWrapper):

    needs = ["gcc", "make"]

    def __init__(self, tcid="TCvm86"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="vm86")

class TCwinetest(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCwinetest"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="winetest")
        self.nolinux = True
        self.storedguest = None

    def runViaDaemon(self, remote, arglist):

        guest = remote
        self.storedguest = guest

        self.getLogsFrom(guest)

        # Get a working directory on the guest
        workdir = guest.xmlrpcTempDir()

        # Unpack the test binaries
        guest.xmlrpcUnpackTarball("%s/%s.tgz" %
                                  (xenrt.TEC().lookup("TEST_TARBALL_BASE"),
                                   self.testname),
                                   workdir)

        # Run the benchmark
        guest.xmlrpcExec("cd %s\\winetest\n"
                         "winetest.exe -c -o results.txt -t XenRT" %
                         (workdir),
                         timeout=3600)

        # Process the results
        data = guest.xmlrpcReadFile("%s\\winetest\\results.txt" % (workdir), patient=True)
        f = file("%s/results.txt" % (self.tec.getLogdir()), "w")
        f.write(data)
        f.close()

        testcases = {}
        testcase = None
        testsrun = 0
        failures = 0
        count = 0
        for line in string.split(data, "\n"):
            r = re.search(r"^(\S+) start \S+ ([0-9\.]+)", line)
            if r:
                testcase = r.group(1)
                testcases[testcase] = {}
                testcases[testcase]["version"] = r.group(2)
                count = count + 1
                continue
            r = re.search(r"^(\S+) done \(\d+\)", line)
            if r:
                testcase = None
                continue
            if not testcase:
                continue
            r = re.search(r"^\S+: (\d+) tests executed, \d+ marked as todo,"
                          " (\d+) failures", line)
            if r:
                testcases[testcase]["tests"] = int(r.group(1))
                testcases[testcase]["failures"] = int(r.group(2))
                testsrun = testsrun + int(r.group(1))
                failures = failures + int(r.group(2))

        self.tec.comment("%u/%u tests failed" % (failures, testsrun))
        if float(guest.xmlrpcWindowsVersion()) > 5.99:
            allowed = 9000
        else:
            allowed = 2000
        if failures > allowed:
            raise xenrt.XRTFailure("%u tests failed" % (failures))
        if failures > 0:
            self.setResult(xenrt.RESULT_PARTIAL)

    def postRun(self):
        try:
            self.storedguest.xmlrpcKillAll("winetest.exe")
        except:
            pass

class TCTimeCheck(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCTimeCheck")

    def pingCheck(self, host):
        """Check we don't see negative ping times"""
        n = 100
        data = self.place.xmlrpcExec("ping -n %u %s" % (n, host),
                                     returndata=True)
        good = 0
        bad = 0
        warn = 0
        for line in string.split(data, "\n"):
            r = re.search(r"Reply from.*time(\S+)", line)
            if r:
                t = r.group(1)
                if t == "<1ms" or t == "<10ms":
                    good = good + 1
                elif t[0:2] == "=-":
                    bad = bad + 1
                else:
                    warn = warn + 1
        total =  good + bad + warn
        if bad > 0:
            raise xenrt.XRTFailure("%u negative ping times seen" % (bad))
        if total < (n - (n/10)):
            raise xenrt.XRTError("only %u of %u replies seen" % (total, n))
        if warn > 0:
            xenrt.TEC().warning("pingCheck %s: %u packets more than 1ms" %
                                (host, warn))

    def hwClock(self):
        """XRT-75: Check hwclock and date both advance at the same rate
        (Bugzilla 630)"""
        hwclock1 = self.place.execcmd("/sbin/hwclock | "
                                      "sed -re's/ *[-0-9\.]+ seconds$//'")
        # SLES10 hwclock doesn't return anything
        if string.strip(hwclock1) == "":
            return
        if string.find(hwclock1, "Cannot access the Hardware Clock") > -1:
            return
        date1 = self.place.execcmd("date")
        time.sleep(60)
        hwclock2 = self.place.execcmd("/sbin/hwclock | "
                                      "sed -re's/ *[-0-9\.]+ seconds$//'")
        date2 = self.place.execcmd("date")

        # Parse
        hwclock1p = int(xenrt.command("date +%%s -d '%s'" % (hwclock1)))
        hwclock2p = int(xenrt.command("date +%%s -d '%s'" % (hwclock2)))
        date1p = int(xenrt.command("date +%%s -d '%s'" % (date1)))
        date2p = int(xenrt.command("date +%%s -d '%s'" % (date2)))

        elapsedhw = hwclock2p - hwclock1p
        elapseddate = date2p - date1p
        diff = elapsedhw - elapseddate
        if abs(diff) > 2:
            raise xenrt.XRTFailure("Elapsed hwclock (%u) and date (%u) differ"
                                   % (elapsedhw, elapseddate))

    def run(self, arglist):
        self.place = self.getLocation()
        if self.place.windows:
            self.runSubcase("pingCheck", ("127.0.0.1"), "no_neg_ping",
                            "loopback")
        else:
            self.runSubcase("hwClock", (), "hwclock", "basic")

class TCsmbioshct(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCsmbioshct"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="smbioshct")
        self.nolinux = True
        self.remote = None

    def runViaDaemon(self, remote, arglist):

        self.remote = remote

        if remote.xmlrpcWindowsVersion() == "5.1":
            xenrt.TEC().skip("Skipping smbioshct on Windows XP.")
            return

        workdir = remote.xmlrpcTempDir()
        logdir = xenrt.TEC().getLogdir()
        remote.xmlrpcUnpackTarball("%s/smbioshct.tgz" %
                                   (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                    workdir)

        if remote.xmlrpcGetArch() == "amd64":
            path = "smbioshct64"
        else:
            path = "smbioshct32"

        remote.xmlrpcExec("cd %s\\smbioshct\\%s\\\n"
                          "smbioshct.exe -v -logo" % (workdir, path))
        try:
            remote.xmlrpcGetFile("%s\\smbioshct\\%s\\smbios.xml" % (workdir, path), 
                                 "%s/smbios.xml" % (logdir))
        except xenrt.XRTFailure, e:
            raise xenrt.XRTError("Results file not found!")
        
        try:
            dom = xml.dom.minidom.parse("%s/smbios.xml" % (logdir))
            errors = [ summary.getAttribute("Title")
                       for summary in dom.getElementsByTagName("EndTest")
                       if summary.getAttribute("Result") != "Pass" ]
        except Exception, e:
            raise xenrt.XRTError("Exception while handling results: " + str(e))
        if errors:
            raise xenrt.XRTFailure("failed on " + string.join(errors, " and "))

class TCnettest(xenrt.TestCase):
    """Network ping-pong validation tests."""

    BUFFERSIZE = 58400

    def installNettestOnGuest(self, guest):
        if guest.xmlrpcFileExists("c:\\netsend.exe"):
            # Assume we've already installed
            return
        d = xenrt.TEC().tempDir()
        xenrt.getTestTarball("nettest",
                             extract=True,
                             copy=False,
                             directory=d)
        path = "nettest"

        for fn in ["netecho.exe", "netsend.exe"]:
            exe = "%s/%s/%s" % (d, path, fn)
            guest.xmlrpcSendFile(exe,
                                 "c:\\%s" % (os.path.basename(exe)),
                                 usehttp=True)
        try:
            guest.xmlrpcExec("netsh firewall set opmode " + \
                             "DISABLE")
        except:
            pass

    def run(self, arglist):
        g0 = self.getGuest(arglist[0])
        g1 = self.getGuest(arglist[1])
        duration = int(arglist[2])

        # Install nettest tools on each server
        self.installNettestOnGuest(g0)
        self.installNettestOnGuest(g1)

        g0.xmlrpcExec("netstat -n")
        g1.xmlrpcExec("netstat -n")

        # Start 5 echoers on each VM
        e0 = []
        e1 = []
        for port in [9000, 9001, 9002, 9003, 9004]:
            cmd = "c:\\netecho.exe %u %u" % \
                    (port, self.BUFFERSIZE)
            ref = g0.xmlrpcStart(cmd)
            e0.append((g0, ref, cmd))
        for port in [9010, 9011, 9012, 9013, 9014]:
            cmd = "c:\\netecho.exe %u %u" % \
                    (port, self.BUFFERSIZE)
            ref = g1.xmlrpcStart(cmd)
            e1.append((g1, ref, cmd))

        g0.xmlrpcExec("netstat -n")
        g1.xmlrpcExec("netstat -n")

        # Start 5 senders on each VM
        s0 = []
        s1 = []
        for port in [9010, 9011, 9012, 9013, 9014]:
            cmd = "c:\\netsend.exe %s %u %u %u" % \
                    (g1.getIP(), port, self.BUFFERSIZE, duration)
            ref = g0.xmlrpcStart(cmd)
            s0.append((g0, ref, cmd))
        for port in [9000, 9001, 9002, 9003, 9004]:
            cmd = "c:\\netsend.exe %s %u %u %u" % \
                    (g0.getIP(), port, self.BUFFERSIZE, duration)
            ref = g1.xmlrpcStart(cmd)
            s1.append((g1, ref, cmd))

        g0.xmlrpcExec("netstat -n")
        g1.xmlrpcExec("netstat -n")

        # Monitor for termination
        deadline = xenrt.timenow() + duration + 300
        errors = 0 
        done = []
        errorlist = []
        while True:
            # Poll for the processes still running
            for x in e0 + e1 + s0 + s1:
                g, ref, cmd = x
                doneref = g.getName() + ref
                if doneref in done:
                    continue
                if g.xmlrpcPoll(ref):
                    done.append(doneref)
                    rc = g.xmlrpcReturnCode(ref)
                    xenrt.TEC().logverbose("Command on %s terminated (%d): %s"
                                           % (g.getName(), rc, cmd))
                    if rc != 0:
                        errors = errors + 1
                    data = g.xmlrpcLog(ref)
                    xenrt.TEC().logverbose(data)
                    reasons = re.findall("\[ERROR\]:\s+(.+)",
                                         data,
                                         re.MULTILINE)
                    for reason in reasons:
                        xenrt.TEC().reason(reason)
                        errorlist.append(reason)
            if len(done) == len(e0 + e1 + s0 + s1):
                break
            if xenrt.timenow() > deadline:
                xenrt.TEC().logverbose(g.xmlrpcPS())
                xenrt.TEC().logverbose("DONE: %s ALL: %s" % (done, [ (x.getName(), y, z) for (x, y, z) in e0 + e1 + s0 + s1 ]))
                raise xenrt.XRTError("Processes still running after deadline.")
            time.sleep(60)

        g0.xmlrpcExec("netstat -n")
        g1.xmlrpcExec("netstat -n")

        if len(errorlist) > 0:
            raise xenrt.XRTFailure(string.join(errorlist))
        if errors > 0:
            raise xenrt.XRTFailure("One or more commands returned error")

class TCnetsc(xenrt.TestCase):
    """A network stress test suite"""

    VCPUS = 1

    def run(self, arglist):

        if xenrt.TEC().lookup("OPTION_PAUSE_NETSC", False, boolean=True):
            self.pause("NetSC pausing")
        
        gserv = self.getGuest(arglist[0])
        gecho = self.getGuest(arglist[1])
        duration = int(arglist[2])
        full = False
        vcpus = self.VCPUS
        if len(arglist) > 3:
            for arg in arglist[3:]:
                if arg == "full":
                    full = True
                elif arg == "smp":
                    vcpus = 2

        d = xenrt.TEC().tempDir()
        xenrt.util.command("tar -zvxf %s/tests/netsc.tgz -C %s" %
                           (xenrt.TEC().lookup("XENRT_BASE"), d))        

        f = file("%s/netsc/binreplace" % (d), "r")
        reps = f.read().split("\n")
        f.close()
        for rep in reps:
            ll = rep.split("=", 1)
            if len(ll) == 2:
                gserv.host.binreplace(ll[0], ll[1])
                if gecho.host != gserv.host:
                    gecho.host.binreplace(ll[0], ll[1])

        if gserv.cpuget() != vcpus:
            gserv.cpuset(vcpus)
        if gecho.cpuget() != vcpus:
            gecho.cpuset(vcpus)

        gserv.reboot()
        gecho.reboot()

        gserv.disableFirewall()
        gecho.disableFirewall()

        # Mount the ISO and copy the installer files to the VM
        gserv.xmlrpcDelTree("c:\\netscinstall")
        gserv.xmlrpcDelTree("c:\\NOVI")
        gserv.getCDLocal("netsc.tgz", "c:\\netscinstall")

        # Perform a modified setup
        gserv.xmlrpcExec("xcopy \\netscinstall\\NOVI\\*.* "
                         "c:\\NOVI\\*.* /s /v /y")
        try:
            gserv.xmlrpcExec("net start w32time")
        except Exception, e:
            xenrt.TEC().warning("Exception starting w32time service: %s" %
                                (str(e)))
        try:
            gecho.xmlrpcDelTree("c:\\NOVI")
            gecho.xmlrpcExec("mkdir c:\\NOVI")
            gecho.xmlrpcExec("mkdir c:\\NOVI\\CLIENT")
        except:
            pass
        data = gserv.xmlrpcReadFile("c:\\NOVI\\SERVER\\CinstallPgm.exe")
        fn = xenrt.TEC().tempFile()
        f = file(fn, "w")
        f.write(data)
        f.close()
        gecho.xmlrpcSendFile(fn, "c:\\NOVI\\CLIENT\\CinstallPgm.exe")
        data = gserv.xmlrpcReadFile("c:\\NOVI\\SERVER\\Receiver.exe")
        f = file(fn, "w")
        f.write(data)
        f.close()
        gecho.xmlrpcSendFile(fn, "c:\\NOVI\\CLIENT\\Receiver.exe")

        # Add in the disk workload parts
        gserv.xmlrpcSendFile("%s/netsc/full.tgz" % (d), "c:\\full.tgz")
        gserv.xmlrpcExtractTarball("c:\\full.tgz", "c:\\NOVI\\SERVER")

        # Edit a file to remove references to non-existent files
        data = gserv.xmlrpcReadFile("c:\\NOVI\\SERVER\\local.bat")
        data = re.sub("if not exist MAX", "REM if not exist MAX", data)
        data = re.sub("if not exist shortcut", "REM if not exist shortcut",
                      data)
        f = file(fn, "w")
        f.write(data)
        f.close()
        gserv.xmlrpcSendFile(fn, "c:\\NOVI\\SERVER\\local.bat")

        # Edit another file to avoid problems caused by the CD being
        # mapped to D:
        data = gserv.xmlrpcReadFile("c:\\NOVI\\SERVER\\local2.bat")
        data = re.sub("[dD]:", "z:", data)
        f = file(fn, "w")
        f.write(data)
        f.close()
        gserv.xmlrpcSendFile(fn, "c:\\NOVI\\SERVER\\local2.bat")

        # Create a run batch file
        f = file("%s/netsc/runstress.bat" % (d), 'r')
        bat = f.read()
        f.close()
        password = gecho.password = "xenroot"
        if not password:
            password = xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS",
                                           "ADMINISTRATOR_PASSWORD"])
        bat = string.replace(bat, "%LOCALIP%", gserv.getIP())
        bat = string.replace(bat, "%PEERIP%", gecho.getIP())
        bat = string.replace(bat, "%PASSWORD%", password)
        bat = string.replace(bat, "%MINUTES%", "%u" % (duration/60))
        batfile = "%s/runstress.bat" % (xenrt.TEC().getLogdir())
        f = file(batfile, "w")
        f.write(bat)
        f.close()
        gserv.xmlrpcSendFile(batfile, "c:\\NOVI\\SERVER\\runstress.bat")
        
        # Start the tests
        if full:
            ref = gserv.xmlrpcStart("cd \\NOVI\\SERVER\nlocal.bat")
            time.sleep(300)
        else:
            ref = None
            data = gserv.xmlrpcExec("cd \\NOVI\\SERVER\nrunstress.bat",
                                    returndata=True)
            f = file("%s/serverout.txt" % (xenrt.TEC().getLogdir()), "w")
            f.write(data)
            f.close()

        started = xenrt.timenow()
        deadline = started + duration + 600
        errors = []
        try:
            # Poll for the sender processes terminating
            while True:
                processes = gserv.xmlrpcPS()
                if not "Sender.exe" in processes:
                    break
                if xenrt.timenow() > deadline:
                    raise xenrt.XRTError("Test still running after deadline.")
                time.sleep(300)
            if xenrt.timenow() < (deadline - 60):
                errors.append("Test only ran for %u minutes of the expected %u"
                              % ((xenrt.timenow() - started)/60,
                                 duration/60))
        finally:
            time.sleep(120)
            try:
                if full:
                    gserv.xmlrpcExec("cd \\NOVI\\SERVER\nstop.bat")
            except:
                pass
            time.sleep(120)
            slogdir = "%s/server" % (xenrt.TEC().getLogdir())
            elogdir = "%s/echoer" % (xenrt.TEC().getLogdir())
            if not os.path.exists(slogdir):
                os.mkdir(slogdir)
            if not os.path.exists(elogdir):
                os.mkdir(elogdir)
            for log in ["server.log", "logs.txt", "msinfo.txt", "netstuff.txt"]:
                try:
                    data = gserv.xmlrpcReadFile("c:\\NOVI\\SERVER\\%s" % (log))
                    f = file("%s/%s" % (slogdir, log), 'w')
                    f.write(data)
                    f.close()
                    if log == "server.log":
                        for line in string.split(data, "\n"):
                            if re.search(r"ERROR Compare Error", line):
                                errors.append("Compare Error")
                            else:
                                r = re.search(r"(ERROR.*)", line)
                                if r:
                                    xenrt.TEC().warning(r.group(1))
                except:
                    pass
            try:
                logs = []
                for suf in ["log", "dat", "pat", "S80", "W80", "txt"]:
                    logs.extend(gecho.xmlrpcGlobpath("c:\\novi\\client\\*.%s" %
                                                     (suf)))
                for log in logs:
                    base = string.split(log, "\\")[-1]
                    data = gecho.xmlrpcReadFile(log)
                    f = file("%s/%s" % (elogdir, base), 'w')
                    f.write(data)
                    f.close()
            except:
                pass
        if len(errors) > 0:
            if "Compare Error" in errors:
                raise xenrt.XRTFailure("One or more compare errors")
            else:
                raise xenrt.XRTFailure("Errors encountered")

class TCndistest(xenrt.TestCaseWrapper):

    SUBDIR = "WLK1.4\\"

    def __init__(self, tcid="TCndistest"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="ndistest")

    def runViaDaemon(self, remote, arglist):
        self.remote = remote
        
        if self.remote.xmlrpcWindowsVersion() < "6.0":
            xenrt.TEC().logverbose("Installing .Net 2.")
            self.remote.installDotNet2()

        self.workdir = self.remote.xmlrpcTempDir()
        self.remote.xmlrpcUnpackTarball(\
            "%s/ndistest.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
            self.workdir)
        if self.remote.xmlrpcGetArch() == "amd64":
            xenrt.TEC().comment("Running 64-bit test.")
            execdir = "%s\\ndistest\\%sndistest64\\ndistest.net" % \
                      (self.workdir, self.SUBDIR)
        else:
            execdir = "%s\\ndistest\\%sndistest32\\ndistest.net" % \
                      (self.workdir, self.SUBDIR)
        ref = self.remote.xmlrpcStart("cd %s\ncscript runmpe.vbs" % (execdir))
        time.sleep(300)

        # Keep checking we're OK.
        try:
            finishtime = xenrt.timenow() + 14400 # 4 hours.
            while True:
                if xenrt.timenow() > finishtime:
                    raise xenrt.XRTFailure("NDIS test hasn't finished in a "
                                           "long time.")
                time.sleep(30)
                remote.waitForDaemon(1800, level=xenrt.RC_OK)
                try:
                    pslist = remote._xmlrpc().ps()
                except:
                    xenrt.TEC().logverbose("PS failed. Probably hibernating "
                                           "again.")
                else:
                    if not "ndistest.exe" in pslist:
                        xenrt.TEC().logverbose("Appear to have successfully "
                                               "completed.")
                        break
                    else:
                        xenrt.TEC().logverbose("NDIS test still seems to be "
                                               "running.")

            # Check return code and fetch any results
            rc = self.remote.xmlrpcReturnCode(ref)
            log = self.remote.xmlrpcLog(ref)
            xenrt.TEC().logverbose(log)

        finally:
            try:
                # Grab the log file tree
                logsubdir = "%s/ndistestlogs" % (xenrt.TEC().getLogdir())
                os.makedirs(logsubdir)
                self.remote.xmlrpcFetchRecursive("%s\\logs" % (execdir),
                                                 logsubdir)
            except Exception, e:
                xenrt.TEC().warning("Exception fetching ndis logs: %s" %
                                    (str(e)))
            
        if rc != 0:
            raise xenrt.XRTFailure("Non-zero return code from ndistest MPE: %u"
                                   % (rc))

class TCdevpath(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCdevpath"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="devpath")
        self.nolinux = True
        self.remote = None

    def runViaDaemon(self, remote, arglist):

        self.remote = remote

        if self.remote.xmlrpcWindowsVersion() == "5.0":
            xenrt.TEC().skip("Skipping devpath on Windows 2000.")
            return

        if self.remote.xmlrpcGetArch() == "amd64":
            self.testdir = "devpathexer64"
        else:
            self.testdir = "devpathexer32"
        
        # Get a working directory on the guest.
        self.workdir = self.remote.xmlrpcTempDir()
        
        # Unpack tarball.
        self.remote.xmlrpcUnpackTarball("%s/devpath.tgz" %
                                        (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                        self.workdir,
                                        patient=True)

        self.remote.xmlrpcExec("netsh firewall set service "
                               "type=fileandprint mode=enable profile=all")
        self.remote.winRegAdd("HKLM",
                              "system\\currentcontrolset\\control\\lsa",
                              "forceguest",
                              "DWORD",
                               0)
        # Use correct net share syntax on XP.
        if self.remote.xmlrpcWindowsVersion() == "5.1":
            self.remote.xmlrpcExec("net share XENRTSHARE=%s\\devpath\\%s" % 
                                   (self.workdir, self.testdir))
        else:
            self.remote.xmlrpcExec("net share XENRTSHARE=%s\\devpath\\%s "
                                   "/GRANT:Administrator,FULL" % (self.workdir, self.testdir))

        xenrt.TEC().progress("Testing without verifier...")
        self.doTest()
        xenrt.TEC().logverbose("Enabling driver verifier.")
        self.remote.enableDriverVerifier()
        self.doTest()
        xenrt.TEC().progress("Testing with verifier...")

    def doTest(self):
        logdir = xenrt.TEC().getLogdir()
        sftp = self.remote.host.sftpClient()
        
        if self.remote.xmlrpcWindowsVersion() > "5.99" and isinstance(self.remote, xenrt.lib.xenserver.guest.TampaGuest):
            drivers = ["xenvbd", "xennet", "xenbus", "xeniface", "xenvif"]
        elif self.remote.xmlrpcWindowsVersion() > "5.99":
            drivers = ["xenvbd", "xennet6", "xenevtchn"]
        else:
            drivers = ["xenvbd", "xennet", "xenevtchn"]
        
        
        failures = {}
        for d in drivers:
            try:
                self.remote.xmlrpcExec("cd %s\\devpath\\%s\n"
                                       "devpathexer.exe /lwa /HCT /dr %s" % 
                                       (self.workdir, self.testdir, d),
                                        timeout=28800,
                                        ignoredata=True)
            except Exception, e:
                xenrt.TEC().logverbose("Exception: " + str(e))
                failures[d] = str(e)
            
            self.remote.host.execdom0(r"smbclient -U Administrator \\\\%s\\XENRTSHARE %s -c 'get DevPathExer.xml /tmp/devpath.xml'" % (self.remote.getIP(), xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS", "ADMINISTRATOR_PASSWORD"])))
            sftp.copyFrom("/tmp/devpath.xml", "%s/devpathexer-%s.xml" % (logdir, d))

            try:
                data = open("%s/devpathexer-%s.xml" % (logdir, d), "rb").read()
                newdata = re.sub("\r\n", "\n", data)
                f = open("%s/devpathexer-%s-unix.xml" % (logdir, d), "wb")
                f.write(newdata)
                f.close()
                dom = xml.dom.minidom.parse("%s/devpathexer-%s-unix.xml" % (logdir, d))
                errors = dom.getElementsByTagName("Error")
                xenrt.TEC().logverbose("Errors testing '%s': %s" % (d, len(errors)))
            except Exception, e:
                # in some rare cases, invalid XML can be output...just ignore if this is the case.
                xenrt.TEC().logverbose(str(e))
                
        if len(failures) > 0:
            raise xenrt.XRTFailure(str(failures.keys()) + " tests failed. " + failures.values()[0])
                
    def postRun(self):
        try:
            self.remote.xmlrpcExec("net share XENRTSHARE /delete")
        except:
            pass
        try:
            self.remote.enableDriverVerifier(enable=False)
        except:
            pass

class TCmemcheck(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCmemcheck"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="memcheck")
        self.remote = None

    def runViaDaemon(self, remote, arglist):
        self.remote = remote
        
        # Get a working directory on the guest.
        self.workdir = self.remote.xmlrpcTempDir()
        
        # Unpack tarball.
        self.remote.xmlrpcUnpackTarball("%s/memcheck.tgz" %
                                        (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                         self.workdir)

        data = self.remote.xmlrpcExec("%s/memcheck/memcheck.exe 600" % (self.workdir), 
                                       returndata=True, timeout=1200)

        xenrt.TEC().logverbose(data)
        if re.search("Invalid", data):
            raise xenrt.XRTFailure("Corruption detected!")
