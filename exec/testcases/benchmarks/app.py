#
# XenRT: Test harness for Xen and the XenServer product family
#
# Application benchmarks
#
# Copyright (c) Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import sys, string, shutil, re, glob, os.path, time
import xenrt
from random import choice

class TCkernbench(xenrt.TestCaseWrapper):

    needs = ["gcc", "make"]
    
    def __init__(self, tcid="TCkernbench"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="kernbench")

class TCosdlaim(xenrt.TestCaseWrapper):

    needs = ["gcc", "make"]

    def __init__(self, tcid="TCosdlaim"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="osdlaim")

class TCmemtest(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCmemtest", testname="memtest"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname=testname)
        
    def runViaDaemon(self, remote, arglist):
        workdir = remote.xmlrpcTempDir()
        remote.xmlrpcUnpackTarball("%s/%s.tgz" %
                          (xenrt.TEC().lookup("TEST_TARBALL_BASE"),
                           self.testname),
                           workdir)
         

class TCDDKbuild(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCDDKbuild", testname="ddkbuild"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname=testname)
        self.nolinux = True
        
    def runViaDaemon(self, remote, arglist):
        ddkLocation = "c:\\ddkinstall"
        vcpus = remote.xmlrpcGetCPUs()
        if not remote.xmlrpcDirExists(ddkLocation):
            remote.installWindowsDDK(ddkLocation)
        else:
            xenrt.TEC().logverbose("DDK appears to be installed.")
        remote.xmlrpcExec("echo build -cZPM %d >> %s\\bin\\setenv.bat" %
                          (vcpus + 1, ddkLocation))
        remote.xmlrpcExec("%s\\bin\\setenv.bat %s > %s\\out.log 2>&1" %
                          (ddkLocation, ddkLocation, ddkLocation), 
                           timeout=10800,
                           ignoredata=True,
                           returnerror=False)
        data = remote.xmlrpcExec("findstr \"Elapsed time\" %s\\out.log" % 
                                 (ddkLocation), returndata=True)
        self.parseResults(data)

    def parseResults(self, data):
        tstr = re.findall("Elapsed time \[([0-9:\.]+)\]", data).pop()
        hms = [ int(x) for x in re.sub("\..*", "", tstr).split(":") ]
        xenrt.TEC().value("ElapsedTime", hms[0]*60*60+hms[1]*60+hms[2], "s")

class TCspecint(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCspecint", testname="specint"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname=testname)
        self.remote = None
        self.nolinux = True
    
    def runViaDaemon(self, remote, arglist):
        remote.getCD("specint2000.iso", "c:\\specint")
        remote.xmlrpcDirRights("c:\\specint")
        remote.xmlrpcExec("cd c:\\specint \n"
                                 "call shrc.bat \n"
                                 "runspec.bat -c win32-x86-vc7.cfg --reportable int",
                                  timeout=7200, returndata=True)
        remote.xmlrpcGetFile("c:\\specint\\result\\CINT2000.001.asc", 
                             "%s/CINT2000.001.asc" % (xenrt.TEC().getLogdir()))
        remote.xmlrpcGetFile("c:\\specint\\result\\CINT2000.001.raw", 
                             "%s/CINT2000.001.raw" % (xenrt.TEC().getLogdir()))
        remote.xmlrpcGetFile("c:\\specint\\result\\log.001", 
                             "%s/log.001" % (xenrt.TEC().getLogdir()))
        self.parseResults(file("%s/CINT2000.001.asc" % (xenrt.TEC().getLogdir())).read())
        
    def parseResults(self, data):
        m = re.search("SPECint_base2000[ \t]+(?P<base>[0-9]+)", data)
        if m:
            xenrt.TEC().value("SPECint_base2000", "%s" % m.group("base"))
        else:
            xenrt.TEC().comment("Didn't find a SPECint base value.")
        m = re.search("SPECint_2000[ \t]+(?P<spec>[0-9]+)", data)
        if m:
            xenrt.TEC().value("SPECint_2000", "%s" % m.group("spec"))
        else:
            xenrt.TEC().comment("Didn't find a SPECint value.")

class TCspecjbb(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCspecjbb", testname="specjbb"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname=testname)
        self.remote = None

    def runViaDaemon(self, remote, arglist):
        try:
            remote.xmlrpcExec("java -version")
        except:
            remote.installJava()

        self.remote = remote

        # Get a working directory on the guest
        workdir = remote.xmlrpcTempDir()

        # Unpack the test binaries
        remote.xmlrpcUnpackTarball("%s/%s.tgz" %
                          (xenrt.TEC().lookup("TEST_TARBALL_BASE"),
                           self.testname),
                          workdir)
        jbb_base = "%s\\%s\\installed" % (workdir, self.testname)
        jobfile = "SPECjbb.props"
        if arglist and arglist[0] == "winperf":
            minheap = "300M"
            maxheap = "500M"
        else:
            minheap = "256M"
            maxheap = "256M"

        self.tec.comment("Heap window %s to %s" % (minheap, maxheap))
        data = remote.xmlrpcExec("java -version", returndata=True)
        r = re.search(r"java version \"([0-9\.-_]+)\"", data)
        if r:
            self.tec.comment("JRE %s" % (r.group(1)))

        remote.xmlrpcExec("cd %s\n"
                          "copy %s\\*.props .\n"
                          "xcopy %s\\xml xml /E /C /F /H /K /Y /I\n"
                          "set CLASSPATH=%s\\jbb.jar;"
                          "%s\\jbb_no_precompile.jar;"
                          "%s\\check.jar;%s\\reporter.jar;%%CLASSPATH%%\n"
                          "java -ms%s -mx%s spec.jbb.JBBmain -propfile %s"
                          % (workdir,
                             jbb_base,
                             jbb_base,
                             jbb_base,
                             jbb_base,
                             jbb_base,
                             jbb_base,
                             minheap,
                             maxheap,
                             jobfile),
                          timeout=7200)
        
        self.parseResults(remote, workdir)

    def parseResults(self, guest, workdir):
        data = guest.xmlrpcReadFile("%s\\results\\SPECjbb.001.raw" % (workdir))
        f = file("%s/SPECjbb.001.raw" % (self.tec.getLogdir()), "w")
        f.write(data)
        f.close()
        data = guest.xmlrpcReadFile("%s\\results\\SPECjbb.001.results" %
                                    (workdir))
        f = file("%s/SPECjbb.001.results" % (self.tec.getLogdir()), "w")
        f.write(data)
        f.close()
        try:
            data = guest.xmlrpcReadFile("%s\\results\\SPECjbb.001.asc" %
                                        (workdir))
            f = file("%s/SPECjbb.001.asc" % (self.tec.getLogdir()), "w")
            f.write(data)
            f.close()
        except:
            raise xenrt.XRTFailure("Unable to locate results file")

        r = re.search(r"^\s*Throughput\s+(\w+)", data, re.MULTILINE)
        if r:
            if r.group(1) == "Invalid":
                self.setResult(xenrt.RESULT_PARTIAL)
                r = re.search(r"but estimate is (\d+)", data)
                if r:
                    self.tec.comment("Estimated score %s" % (r.group(1)))
            else:
                self.tec.value("Score", int(r.group(1)), "units")
        else:
            raise xenrt.XRTError("Unable to parse result")

    def postRun(self):
        try:
            # Terminate any running java processes
            self.remote.xmlrpcKillAll("java.exe")
        except:
            pass

class TCspecjbb2005(TCspecjbb):

    def __init__(self, tcid="TCspecjbb2005"):
        TCspecjbb.__init__(self,
                           tcid=tcid,
                           testname="specjbb2005")

    def runViaDaemon(self, remote, arglist=None):
        TCspecjbb.runViaDaemon(self, remote, arglist)

    def parseResults(self, guest, workdir):
        data = guest.xmlrpcReadFile("%s\\results\\SPECjbbSingleJVM\\"
                                    "SPECjbb.001.raw" % (workdir))
        f = file("%s/SPECjbb.001.raw" % (self.tec.getLogdir()), "w")
        f.write(data)
        f.close()
        data = guest.xmlrpcReadFile("%s\\results\\SPECjbbSingleJVM\\"
                                    "SPECjbb.001.results" % (workdir))
        f = file("%s/SPECjbb.001.results" % (self.tec.getLogdir()), "w")
        f.write(data)
        f.close()

        r = re.search(r"Score is\s+(\d+)", data, re.MULTILINE)
        if r:
            score = int(r.group(1))
            if re.search(r"Invalid", data):
                self.setResult(xenrt.RESULT_PARTIAL)
                self.tec.comment("Estimated score %u" % (score))
                self.tec.value("Estimated", score)
            else:
                self.tec.value("Score", score)
        else:
            raise xenrt.XRTError("Unable to parse result")

class TCpostmark(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCpostmark"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="postmark")

class TCosdb(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCosdb"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="osdb")

class TCdbench(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCdbench"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="dbench")

class TCtbench(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCtbench"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="tbench")

class TCsandra(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCsandra"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="sandra")
        self.nolinux = True

class TCsciencemark2(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCsciencemark2"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="sciencemark2")

        self.workdir = None
        self.nolinux = True
        self.guest = None

    def startRun(self, guest):
        # Get a working directory on the guest.
        self.workdir = guest.xmlrpcTempDir()

        # Unpack the test binaries
        guest.xmlrpcUnpackTarball("%s/sciencemark2.tgz" %
                          (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                          self.workdir)

        ref = guest.xmlrpcStart("cd %s\\sciencemark2\n"
                                "ScienceMark2.exe -runallbench -automate\n" %
                                (self.workdir))
        time.sleep(10)       
        if not "ScienceMark2.exe" in guest.xmlrpcPS():
            raise xenrt.XRTError("ScienceMark2 failed to start.")
        return ref

    def stopRun(self, guest):
        if not "ScienceMark2.exe" in guest.xmlrpcPS():
            raise xenrt.XRTFailure("ScienceMark2 no longer running.")
        guest.xmlrpcKillAll("ScienceMark2.exe")
        if "ScienceMark2.exe" in guest.xmlrpcPS():
            raise xenrt.XRTFailure("ScienceMark2 failed to die.")

    def runViaDaemon(self, guest, arglist):

        self.guest = guest

        if guest.xmlrpcWindowsVersion() == "5.0":
            xenrt.TEC().skip("Skipping sciencemark2 on Windows 2000")
            return

        ref = self.startRun(guest)
        guest.xmlrpcWait(ref, timeout=7200)

        # Process the results
        logfiles = guest.xmlrpcGlobPattern("%s\\sciencemark2\\*.rst" % (self.workdir))
        logfiles.sort()
        if len(logfiles) == 0:
            raise xenrt.XRTFailure("No result file found")
        # Last log file will be the most recent
        data = guest.xmlrpcReadFile(logfiles[-1])

        # We want the 6th line, split by spaces
        lines = data.split("\n")

        # Now split by spaces
        values = lines[5].split(" ")

        # Now extract and report the values
        self.tec.value("membench",values[-7], "units")
        self.tec.value("STREAM",values[-6], "units")
        self.tec.value("cipherbench",values[-5], "units")
        self.tec.value("moldyn",values[-4], "units")
        self.tec.value("primordia",values[-3], "units")
        self.tec.value("BLAS/FLOPs",values[-2], "units")
        self.tec.value("Overall",values[-1], "units")

        # Deal with the console log files
        logfiles = guest.xmlrpcGlobPattern("%s\\sciencemark2\\Console-*.txt" 
                                   % (self.workdir))
        for lf in logfiles:
            data = guest.xmlrpcReadFile(lf)
            fn = os.path.basename(lf.replace("\\","/"))
            f = file("%s/%s" % (xenrt.TEC().getLogdir(), fn), "w")
            f.write(data)
            f.close()
            
    def postRun(self):
        try:
            self.guest.xmlrpcKillAll("ScienceMark2.exe")        
        except:
            pass

class TCsio(xenrt.TestCaseWrapper):

    # Based on the scripts/sio bash script written by Karl Spalding

    # Note that we must use password, not key, authentication to talk to
    # guests.

    NETCMD="C:\\WINDOWS\\system32\\net.exe"
    NETSH="C:\\WINDOWS\\system32\\netsh.exe"

    def __init__(self, tcid="TCsio"):
        xenrt.TestCaseWrapper.__init__(self, 
                                       tcid=tcid,
                                       testname="sio")
        self.nolinux = True
        self.client = None

    def runViaDaemon(self, remote, arglist=None):

        server = remote
        gname = None

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
                # If we're running in single testcase 
                # mode then client may be a name/address
                # of a VM. Build a guest object:
                stcm = xenrt.TEC().lookup("SINGLE_TESTCASE_MODE", False, boolean=True)
                if stcm:
                    client = xenrt.GenericGuest(gname)
                    client.mainip = gname
                    client.windows = True            
                else:
                    client = self.getGuest(gname)

        if not gname:
            client = server
    
        self.client = client

        if not server.password:
            server.password = xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS",
                                                  "ADMINISTRATOR_PASSWORD"])

        xenrt.TEC().comment("Server %s, client %s" %
                            (server.name, client.name))

        # Enable File and Printer Sharing in Firewall on Server and share a
        # folder
        log = server.xmlrpcExec("%s firewall set service type=fileandprint "
                                "mode=enable profile=all" % (self.NETSH),
                                returndata=True)
        server.xmlrpcExec("mkdir C:\\share")
        log += server.xmlrpcExec("%s share siotest=C:\\share "
                                 "/GRANT:Administrator,FULL" % (self.NETCMD),
                                 returndata=True)

        f = file("%s/sio.remote.log" % (xenrt.TEC().getLogdir()), "w")
        f.write(log)
        f.close()
        
        # See what the server calls itself in NBT land
        ncs = server.xmlrpcExec("%s config server" % (self.NETCMD),
                                returndata=True)
        ncsl = ncs.split("\n")
        for l in ncsl:
            if l.startswith("Server Name"):
                ls = l.split()
                server_nbt = ls[2].replace("\\","").strip()
                break

        # Use a file size of 3 x the server VM's RAM size
        fsize = server.memory * 3
        
        # Extract tarball on the client
        workdirc = client.xmlrpcTempDir()
        client.xmlrpcUnpackTarball("%s/sio.tgz" % 
                        (xenrt.TEC().lookup("TEST_TARBALL_BASE")), workdirc)

        # Run the test
        run_log = client.xmlrpcExec("%s use z: \\\\%s\\siotest %s" % 
                                    (self.NETCMD,server_nbt,server.password),
                                    returndata=True)
        run_log += client.xmlrpcExec("%s use" % (self.NETCMD), returndata=True)
        run_log += client.xmlrpcExec("echo 0 > z:\\test.file", returndata=True)
        run_log += client.xmlrpcExec("%s\\sio\\sio_win32.exe 70 100 16k 0 %um "
                                     "120 1 z:\\test.file -fillonce" % 
                                     (workdirc, fsize), returndata=True, timeout=7200)
        run_log += client.xmlrpcExec("%s\\sio\\sio_win32.exe 70 100 16k 0 %um "
                                     "120 1 z:\\test.file -niceoutput" %
                                     (workdirc, fsize), returndata=True, timeout=7200)
        run_log += client.xmlrpcExec("%s use z: /delete" % (self.NETCMD),
                                     returndata=True)

        f = file("%s/sio-run.log" % (xenrt.TEC().getLogdir()), "w")
        f.write(run_log)
        f.close()

        # Cleanup the server
        log = server.xmlrpcExec("%s share siotest /delete" % (self.NETCMD),
                                returndata=True)
        log += server.xmlrpcExec("del /Q C:\\share", returndata=True)
        log += server.xmlrpcExec("rmdir C:\\share", returndata=True)
        log += server.xmlrpcExec("%s firewall set service type=fileandprint "
                                 "mode=disable profile=all" % (self.NETSH),
                                 returndata=True)
        f = file("%s/sio.remote-post.log" % (xenrt.TEC().getLogdir()), "w")
        f.write(log)
        f.close()

        # Parse the output
        f = open("%s/sio-run.log" % (xenrt.TEC().getLogdir()), "r")
        passed = False
        while True:
            line = f.readline()
            if not line:
                break
            if re.search(r"z: was deleted successfully", line):
                passed = True
            r = re.search(r"^LAT\(ms\):\s+([0-9.]+)", line)
            if r:
                xenrt.TEC().value("Latency", r.group(1))
            r = re.search(r"^TPUT\(KB/s\):\s+([0-9.]+)", line)
            if r:
                xenrt.TEC().value("Throughput", r.group(1))
        if not passed:
            raise xenrt.XRTFailure("Did not complete successfully")

    def postRun(self):
        try:
            self.client.xmlrpcKillAll("sio_win32.exe")
        except:
            pass

class TCSQLIO(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCSQLIO"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="SQLIO")
        self.workdir = None
        self.length = 300
        self.sizes = ["8", "64", "128", "256"]
        self.rws = ["R", "W"]
        self.iotypes = ["random", "sequential"]
        self.drives = ["c"]
        self.remote = None
        self.nolinux = True

    def doTest(self, rw, iotype, size):

        cmd = []
        cmd.append('"c:\\Program Files\\SQLIO\\sqlio.exe"')
        cmd.append("-k%s" % (rw))
        cmd.append("-s%u" % (self.length))
        cmd.append("-f%s" % (iotype))
        cmd.append("-o8")
        cmd.append("-b%s" % (size))
        cmd.append("-LS")
        cmd.append("-Fparam.txt")

        params = reduce(lambda a,b:a + "%s:\\testfile.dat 2 0x0 100\r\n" % (b), self.drives, "") 
        self.remote.xmlrpcWriteFile("c:\\Program Files\\SQLIO\\param.txt", params)

        try:
            data = self.remote.xmlrpcExec("cd \"c:\\Program Files\\SQLIO\"\n%s" %
                                          (string.join(cmd)),
                                          returndata=True,
                                          timeout=self.length*3)
        finally:
            try: self.remote.xmlrpcKillAll("sqlio.exe")
            except: pass
            for drive in self.drives:
                try: self.remote.xmlrpcRemoveFile("%s:\\testfile.dat" % (drive))
                except: pass
            
        r = re.search(r"MBs/sec:\s+([0-9.]+)", data)
        if not r:
            raise xenrt.XRTError("Couldn't find rate in output")
        self.tec.value("%s:%s:%sk" % (iotype, rw, size),
                       float(r.group(1)),
                       "MB/s")
        r = re.search(r"Avg_Latency\(ms\):\s+([0-9.]+)", data)
        if r:
            self.tec.value("%s:%s:%sk:lat" % (iotype, rw, size),
                           float(r.group(1)),
                           "ms")

    def runViaDaemon(self, remote, arglist):
        self.remote = remote

        if arglist and len(arglist) > 0:
            for arg in arglist:
                l = string.split(arg, "=", 1)
                if l[0] == "sizes":
                    self.sizes = string.split(l[1], ",")
                elif l[0] == "rws":
                    self.rws = string.split(l[1], ",")
                elif l[0] == "iotypes":
                    self.iotypes = string.split(l[1], ",")
                elif l[0] == "length":
                    self.length = int(l[1])
                elif l[0] == "drives":
                    if l[1] == "all":
                        data = self.remote.xmlrpcDiskInfo()
                        self.drives = re.findall(" ([A-Z]{1}) .*Partition", data)
                    else:
                        self.drives = string.split(l[1], ",")
           
        if remote.xmlrpcGetArch() == "amd64":
            xenrt.TEC().skip("Skipping SQLIO on x64")
            return

        # Get a working directory on the guest
        workdir = remote.xmlrpcTempDir()

        # Unpack the test binaries and install SQLIO
        remote.xmlrpcUnpackTarball("%s/sqlio.tgz" %
                          (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                          workdir)
        remote.xmlrpcExec("msiexec.exe /I %s\\sqlio\\SQLIO.msi /Q /L*v "
                          "c:\\sqlio-install.log" % (workdir), timeout=3600)

        for rw in self.rws:
            for iotype in self.iotypes:
                for size in self.sizes:
                    self.runSubcase("doTest",
                                    (rw, iotype, size),
                                    "%s_%s" % (iotype, rw),
                                    "%sk" % (size))

class TCsm2004se(xenrt.TestCaseWrapper):
    def __init__(self, tcid="TCsm2004se"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="sm2004se")
        self.workdir = None
        self.remote = None

    def runViaDaemon(self, remote, arglist):
        self.remote = remote
        g = remote

        # Check we have enough disk space
        size = g.getRootDiskDetails()[1]
        if (size/1024) < 15:
            xenrt.TEC().skip("This test requires a disk of at least 15GB")
            return
        

        # Install
        try:
            self.install()
        except xenrt.XRTFailure, e:
            # This isn't a failure of the testcase
            raise xenrt.XRTError(e)

        # Start it up (10 ping delay to allow the xmlrpc transaction to
        # finish before it reboots the guest...)
        g.xmlrpcStart("ping -n 10 127.0.0.1\n"
                      "cd \"C:\\Program Files\\BAPCo\\SYSmark 2004 SE\\"
                      "Benchmgr\"\n"
                      "Sysmgr.exe STDSUITE=1 PROJNAME=XenRT")

        # Wait for the first reboot
        g.waitToReboot(timeout=180)
        g.waitForDaemon(180,desc="Guest boot before ICC run")

        xenrt.TEC().comment("ICC run started")

        # Wait for reboot to indicate end of ICC run
        g.waitToReboot(timeout=9000)
        g.waitForDaemon(180,desc="Guest boot before OP run")

        xenrt.TEC().comment("OP run started")

        # Wait for reboot to indicate end of OP run
        g.waitToReboot(timeout=9000)
        g.waitForDaemon(180,desc="Guest boot after OP run")

        xenrt.TEC().comment("Run complete")

        # Parse the results
        log = g.xmlrpcReadFile("C:\\Program Files\\BAPCo\\SYSmark 2004 SE\\"
                                "Reports\\XENRT.wmr")
        # Write it to the logdir
        f = file("%s/XENRT.wmr" % (xenrt.TEC().getLogdir()),"w")
        f.write(log)
        f.close()

        icc = self.runSubcase("parseResults",(log,True),"Std Suite","ICC")
        op = self.runSubcase("parseResults",(log,False),"Std Suite","OP")

        if icc == xenrt.RESULT_PASS or op == xenrt.RESULT_PASS:
            overall = self.extractScore(log,"SYSmark 2004 SE Overall Rating",sep="=")
            xenrt.TEC().value("Overall",overall)

    def extractScore(self,log,score,sep=","):
        loglines = log.split("\n")
        for line in loglines:
            if line.count(score) == 1:
                f = line.split(sep)
                return f[-1].strip()
        return None

    def parseResults(self,log,icc):
        # Parse results, if icc is true do it for ICC, otherwise for OP
        if icc:
            overall = self.extractScore(log,"Internet Content Creation Overall",sep="=")
        else:
            overall = self.extractScore(log,"Office Productivity Overall",sep="=")
        if not overall:
            raise xenrt.XRTFailure("Overall score not found in log")

        # Now get the individual results
        if icc:
            xenrt.TEC().value("ICC Overall",overall)
            xenrt.TEC().value("ICC 3D Creation",self.extractScore(log,
                                      "Internet Content Creation, 3D Creation"))
            xenrt.TEC().value("ICC 2D Creation",self.extractScore(log,
                                      "Internet Content Creation, 2D Creation"))
            xenrt.TEC().value("ICC Web Publication",self.extractScore(log,
                                  "Internet Content Creation, Web Publication"))
        else:
            xenrt.TEC().value("OP Overall",overall)
            xenrt.TEC().value("OP Communication",self.extractScore(log,
                                      "Office Productivity, Communication"))
            xenrt.TEC().value("OP Document Creation",self.extractScore(log,
                                      "Office Productivity, Document Creation"))
            xenrt.TEC().value("OP Data Analaysis",self.extractScore(log,
                                      "Office Productivity, Data Analysis"))

    def install(self):
        g = self.remote
        # Get a workdir
        workdir = g.xmlrpcTempDir()
        self.workdir = workdir

        # Extract the tarball
        g.xmlrpcUnpackTarball("%s/sm2004se.tgz" %
                                 (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                 workdir)

        # Install Virtual Audio Cable
        g.xmlrpcExec("c:\\devcon.exe install "
                     "%s\\sm2004se\\vaudio\\vrtaucbl.inf "
                     "EuMusDesign_VAC_WDM" % (workdir))

        # Make the execdaemon actually start up again (sm2004se disables all
        # entries in the Run part of the registry)
        sed = "c:\execdaemon.cmd"
        g.xmlrpcWriteFile("C:\\docume~1\\admini~1\\startm~1\\Programs\\Startup"
                          "\\execdaemon.bat",sed)

        # Load the cd
        g.changeCD("sysmark_2004_se.iso")
        time.sleep(30)

        # Kill setup.exe (it autoruns which we don't want)
        try:
            g.xmlrpcKillAll("SETUP.EXE")
        except:
            pass

        # Start the install
        g.xmlrpcStart("D:\\setup.exe -s -f1%s\\sm2004se\\xen.iss" % (workdir))

        # Wait for the guest to reboot
        g.waitToReboot(timeout=5400)
        g.waitForDaemon(180,desc="Guest boot after sm2004se install")

class TCvConsolidate(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCvConsolidate"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="vConsolidate")

        # Reference scores used to calculate ratios
        self.referenceScores = {'java':18.95, 'db':6.58, 'mail':2.41, 'web':105.24}

    def run(self,arglist):
        # Get all guest objects
        if len(arglist) < 8:
            raise xenrt.XRTError("Expecting 8 guests as arguments")

        MailServer1 = xenrt.TEC().registry.guestGet(arglist[0]) # Windows
        WebServer1 = xenrt.TEC().registry.guestGet(arglist[1])  # Linux
        JavaServer1 = xenrt.TEC().registry.guestGet(arglist[2]) # Linux
        DBServer1 = xenrt.TEC().registry.guestGet(arglist[3])   # Linux
        IdleServer1 = xenrt.TEC().registry.guestGet(arglist[4]) # Windows
        Client1 = xenrt.TEC().registry.guestGet(arglist[5])     # Windows
        Client2 = xenrt.TEC().registry.guestGet(arglist[6])     # Windows
        Controller = xenrt.TEC().registry.guestGet(arglist[7])  # Windows

        if not MailServer1:
            raise xenrt.XRTError("Cannot find guest %s" % (arglist[0]))
        if not WebServer1:
            raise xenrt.XRTError("Cannot find guest %s" % (arglist[1]))
        if not JavaServer1:
            raise xenrt.XRTError("Cannot find guest %s" % (arglist[2]))
        if not DBServer1:
            raise xenrt.XRTError("Cannot find guest %s" % (arglist[3]))
        if not IdleServer1:
            raise xenrt.XRTError("Cannot find guest %s" % (arglist[4]))
        if not Client1:
            raise xenrt.XRTError("Cannot find guest %s" % (arglist[5]))
        if not Client2:
            raise xenrt.XRTError("Cannot find guest %s" % (arglist[6]))
        if not Controller:
            raise xenrt.XRTError("Cannot find guest %s" % (arglist[7]))

        allGuests = [MailServer1,WebServer1,JavaServer1,DBServer1,IdleServer1,
                     Client1,Client2,Controller]
        winGuests = [MailServer1,IdleServer1,Client1,Client2,Controller]
        linuxGuests = [WebServer1,JavaServer1,DBServer1]

        try:
            # make sure guests are down
            for guest in allGuests:
                if guest.getState() == "UP": 
                    guest.shutdown()
                elif guest.getState() == "SUSPENDED":
                    guest.resume()
                    guest.shutdown()
                self.getLogsFrom(guest)
                if guest.host:
                    self.getLogsFrom(guest.host)

            # See how much RAM on the boxes, and divide up appropriately
            # Get total RAM for the host running the servers
            serverHost = MailServer1.host
            clientHost = Client1.host
            serverMem = serverHost.getTotalMemory() # in MB
            clientMem = clientHost.getTotalMemory() # in MB
            
            validConfig = False
            if serverMem > 7168: # 7GB, i.e. most likely an 8GB box
                validConfig = True
                WebServer1.memset(1.5 * 1024)
                MailServer1.memset(1.5 * 1024)
                DBServer1.memset(1.5 * 1024)
                JavaServer1.memset(2 * 1024)
                IdleServer1.memset(int(0.4 * 1024))
            elif serverMem > 3584: # 3.5GB, i.e. most likely a 4GB box
                WebServer1.memset(750)
                MailServer1.memset(750)
                DBServer1.memset(750)
                JavaServer1.memset(1024)
                IdleServer1.memset(200)
            elif serverMem > 1536: # 1.5GB, i.e. most likely a 2GB box
                WebServer1.memset(750)
                MailServer1.memset(750)
                DBServer1.memset(750)
                JavaServer1.memset(1024)
                IdleServer1.memset(200)
            else:
                raise xenrt.XRTError("Host needs at least 2GB of RAM, has %u MB" % (serverMem))

            if not validConfig:
                xenrt.TEC().warning("Not using a valid Intel run profile (due to memory restrictions)")

            if clientMem > 1536: # 1.5GB, i.e. most likely a 2GB box
                Client1.memset(512)
                Client2.memset(512)
                Controller.memset(512)
            else:
                # Allow a 300MB safeguard for Xen and qemu overheads etc
                clientsMem = (clientMem - 300) / 3
                Client1.memset(clientsMem)
                Client2.memset(clientsMem)
                Controller.memset(clientsMem)


            for guest in allGuests:
                guest.start()

            # Set up the same workdirs on all guests (makes life easier)
            self.winWorkdir = MailServer1.xmlrpcTempDir()
            for guest in winGuests:
                try:
                    guest.xmlrpcExec("mkdir %s" % (self.winWorkdir))
                except:
                    pass # We get an error on MailServer1 as it already exists

            self.linuxWorkdir = WebServer1.execguest("mktemp -d /tmp/workXXXXXX").strip()
            for guest in linuxGuests:
                guest.execguest("mkdir -p %s" % (self.linuxWorkdir))

            # Unpack tarballs
            for guest in winGuests:
                guest.xmlrpcUnpackTarball("%s/vconsolidate.tgz" %
                                      (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                      self.winWorkdir)
                guest.xmlrpcUnpackTarball("%s/loadsim.tgz" %
                                      (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                      self.winWorkdir)
            for guest in linuxGuests:
                guest.execguest("wget '%s/vconsolidate.tgz' -O - | tar -zx -C %s" %
                              (xenrt.TEC().lookup("TEST_TARBALL_BASE"),
                              self.linuxWorkdir))

            # Disable firewall on linux guests
            for guest in linuxGuests:
                guest.execguest("/etc/init.d/iptables stop || true")
                guest.execguest("chkconfig --del iptables || true")
        except xenrt.XRTFailure, e:
            # Any failure here is not a failure of the testcase
            raise xenrt.XRTError(e)

        # Configure MailServer1 and Client 1
        # Decide on a domain name
        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        self.domain = ""
        for i in range(8):
            self.domain += choice(chars)

        xenrt.TEC().comment("Random domain name: %s" % (self.domain))

        # Give MailServer1 an additional 90GB disk, format it and make it E
        MailServer1.shutdown()
        MailServer1.createDisk(sizebytes=96636764160)
        MailServer1.start()
        MailServer1.xmlrpcExec("diskpart /s %s\\vconsolidate\\mail\\partition.txt" % (self.winWorkdir), timeout=600)
        MailServer1.xmlrpcFormat("E")
        MailServer1.xmlrpcExec("mkdir E:\\backup")

        self.setupExchangeAndLoadsim(MailServer1,Client1)

        # LoadSim Initialize Test takes a long time...
        lsiRef = Client1.xmlrpcStart("%s\\vconsolidate\\mail\\loadsim_init.bat" % (self.winWorkdir))

        # Configure WebServer1
        WebServer1.execguest("%s/vconsolidate/web/setup.sh %s" % (self.linuxWorkdir,self.linuxWorkdir))

        # Configure JavaServer1
        # Get SpecJBB2005
        JavaServer1.execguest("wget '%s/specjbb2005.tgz' -O - | tar -zx -C %s" %
                              (xenrt.TEC().lookup("TEST_TARBALL_BASE"),
                              self.linuxWorkdir))
        # Modify it
        JavaServer1.execguest("%s/vconsolidate/java/setup.sh %s" % (self.linuxWorkdir,self.linuxWorkdir))

        # Configure DBServer1
        # Add extra disks
        mdd = DBServer1.createDisk(sizebytes=21474836480)
        mld = DBServer1.createDisk(sizebytes=5368709120)
        # Temporary bodge that makes it work with current product
        mdd = "xvdb"
        mld = "xvdc"
        time.sleep(10)
        DBServer1.execguest("%s/vconsolidate/db/disk.sh %s %s" % (self.linuxWorkdir,mdd,mld))

        # Set up MySQL etc
        DBServer1.execguest("%s/vconsolidate/db/setup.sh %s" % (self.linuxWorkdir,self.linuxWorkdir),timeout=600)

        # Configure Client2
        # Install Webbench client
        Client2.xmlrpcExec("%s\\vconsolidate\\web\\client\\setup.exe /s /f1%s\\vconsolidate\\web\\client.iss" % (self.winWorkdir,self.winWorkdir))
        # Configure hosts file
        hosts = Client2.xmlrpcReadFile("c:\\windows\\system32\\drivers\\etc\\hosts")
        hosts += "\n%s    controller\n" % (Controller.mainip)
        hosts += "%s    webserver\n" % (WebServer1.mainip)
        Client2.xmlrpcWriteFile("c:\\windows\\system32\\drivers\\etc\\hosts",hosts)

        # Configure Controller
        # Install Webbench controller
        Controller.xmlrpcExec("%s\\vconsolidate\\web\\controller\\setup.exe /s /f1%s\\vconsolidate\\web\\controller.iss" % (self.winWorkdir,self.winWorkdir))
        # Install vConsolidate
        Controller.xmlrpcExec("mkdir c:\\vCON")
        Controller.xmlrpcExec("xcopy %s\\vconsolidate\\controller\\* c:\\vCON /E /Q /H" % (self.winWorkdir))
        # Turn off firewall (gets annoyed with WebBench)
        Controller.xmlrpcExec("netsh firewall set opmode DISABLE")
        # Grab lslog.exe from Client1
        lslog = Client1.xmlrpcReadFile("C:\\Program Files\\LoadSim\\lslog.exe")
        Controller.xmlrpcWriteFile("C:\\vCON\\lslog.exe", lslog)
        # Set up configurations
        # vConsolidate profile
        vcp = Controller.xmlrpcReadFile("C:\\vCON\\Profiles\\xenrt.template")
        vcp = vcp.replace("%DB%",DBServer1.mainip)
        vcp = vcp.replace("%LS%",Client1.mainip)
        vcp = vcp.replace("%Java%",JavaServer1.mainip)
        vcp = vcp.replace("%WB%", Controller.mainip)
        Controller.xmlrpcWriteFile("C:\\vCON\\Profiles\\XenRT.profile", vcp)

        # Set up WebBench controller
        wbc = "%s             1" % (Client2.mainip)
        Controller.xmlrpcWriteFile("C:\\WebBench\\Controller\\Clientids\\client.cdb",wbc)

        # Start the various daemons
        Client1.xmlrpcExec("netsh firewall set opmode DISABLE")
        Client1.xmlrpcExec("copy %s\\vconsolidate\\mail\\daemon\\* C:\\" % (self.winWorkdir))
        wind = ("cd C:\\\n"
                "daemon.exe\n")
        Client1.xmlrpcWriteFile("C:\\docume~1\\alluse~1\\startm~1\\programs\\startup\\daemon.bat",wind)
        Controller.xmlrpcExec("copy %s\\vconsolidate\\web\\daemon\\* C:\\" % (self.winWorkdir))
        Controller.xmlrpcWriteFile("C:\\daemon.bat",wind)
        Controller.xmlrpcExec("c:\\soon.exe 90 /INTERACTIVE c:\\daemon.bat",level=xenrt.RC_OK)
        time.sleep(120)
        JavaServer1.execguest("cd %s/vconsolidate/java/daemon && ./daemon > /dev/null 2>&1 &" % (self.linuxWorkdir),getreply=False)
        DBServer1.execguest("cd %s/vconsolidate/db/daemon && ./daemon > /dev/null 2>&1 &" % (self.linuxWorkdir),getreply=False)

        # Get WebBench ready
        Controller.xmlrpcExec("copy %s\\vconsolidate\\web\\suite\\vConsolidate.tst C:\\WebBench\\controller\\suites\\WebBench" % (self.winWorkdir))
        Controller.xmlrpcExec("copy %s\\vconsolidate\\web\\suite\\ecommerce* C:\\WebBench\\controller\\suites\\WebBench\\Templates\\CGI" % (self.winWorkdir))

        self.startWebBench(Client2,Controller)

        # Wait for loadsim to be ready
        xenrt.TEC().logverbose("Waiting for Loadsim to finish prepration")
        Client1.xmlrpcWait(lsiRef,level=xenrt.RC_OK,timeout=10800)

        # Backup the mail database
        exchangeService = "\"Microsoft Exchange Information Store\""
        eb = MailServer1.xmlrpcStart("net stop %s\n"
                                     "copy /Y E:\\priv1.* E:\\backup\\\n"
                                     "net start %s" % (exchangeService,
                                                       exchangeService))

        # Reboot Client1 so it loads it's daemon
        Client1.reboot()

        xenrt.TEC().logverbose("Waiting for Exchange backup to complete...")
        MailServer1.xmlrpcWait(eb,timeout=3600,desc="Create Exchange backup")

        # MailServer1 runs really badly at this point, we need to reboot it...
        MailServer1.reboot()

        # Are we pausing (e.g. for starting a trace?)
        if xenrt.TEC().lookup("OPTION_PAUSE_VCONS", False, boolean=True):
            self.pause("vConsolidate pausing")

        # Do numRuns runs
        numRuns = 3
        for i in range(numRuns):
            xenrt.TEC().progress("Starting vConsolidate run %u" % (i))
            Controller.xmlrpcStart("cd c:\\vCon\n"
                                   "c:\\vCon\\vConsolidate.exe")
            time.sleep(5)
            Controller.xmlrpcAppActivate("vConsolidate")
            time.sleep(5)
            Controller.xmlrpcSendKeys(" ,s1,{TAB},s1, ")
            xenrt.TEC().progress("Run started, sleeping 40 minutes")
            time.sleep(2390)
            xenrt.TEC().progress("Stopping vConsolidate run %u" % (i))
            # Now send the stop command (need to tab away and back to vConsolidate)
            Controller.xmlrpcAppActivate("WebBench")
            time.sleep(5)
            Controller.xmlrpcAppActivate("vConsolidate")
            Controller.xmlrpcSendKeys("s5,{ENTER},s30,%{F4}")
            time.sleep(60)
            if (i + 1) == numRuns:
                # Don't bother with the cleanup
                break

            # Cleanup...
            # Copy the mail backup
            mbr = MailServer1.xmlrpcStart("net stop %s\n"
                                          "copy /Y E:\\backup\\priv1.* E:\\\n"
                                          "net start %s" % (exchangeService,exchangeService))
            # Reset WebBench
            xenrt.TEC().logverbose("Resetting WebBench...")
            Controller.xmlrpcAppActivate("WebBench")
            time.sleep(5)
            Controller.xmlrpcSendKeys("%{F4},s1, ")
            time.sleep(30)
            Controller.xmlrpcExec("del C:\\WebBench\\Controller\\Results\\vConsolidate.*")
            self.startWebBench(Client2,Controller)
            time.sleep(60)
            xenrt.TEC().logverbose("Waiting for Exchange backup to restore...")
            MailServer1.xmlrpcWait(mbr,timeout=7200,desc="Restore exchange backup")
            MailServer1.reboot()

        # Now process the results - we should have 3 dirs in c:\vCON of the form
        # vCon-M-DD-HH-MM, we want to grab from each dir result.txt

        dirs = Controller.xmlrpcGlobpath("c:\\vCon\\*-*-*-*")
        if len(dirs) <> 3:
            raise xenrt.XRTError("Found %u results dirs, expecting 3" % (len(dirs)))

        dirs.sort()
        i = 1
        for dir in dirs:
            Controller.xmlrpcGetFile("%s\\result.txt" % (dir),"%s/result%u.txt" % (xenrt.TEC().getLogdir(),i))
            i += 1

        # Process the actual files and get a score out...
        avg = []
        for i in range(1,len(dirs)+1):
            f = file("%s/result%u.txt" % (xenrt.TEC().getLogdir(),i),"r")
            data = f.read()
            f.close()
            datal = data.split("\n")
            java = None
            db = None
            mail = None
            web = []
            times = []
            for line in datal:
                l = line.strip()
                if l.startswith("JFT sum"):
                    java = l.split("=")[1]
                elif l.startswith("DB Trans Number"):
                    db = l.split("=")[1]
                elif l.startswith("Weighted Avg"):
                    mail = l.split()[3]
                elif l.startswith("A,4_client,2"):
                    web.append(l.split(",")[3])
                elif re.match("\d+:\d+:\d+\.\d+",l):
                    times.append(l)

            # Check we have all the scores
            if not java or not db or not mail or len(web) < 3 or len(times) < 2:
                raise xenrt.XRTError("Failed to parse vConsolidate results file",data=[java,db,mail,web,times])

            # Work out the run score
            start = self.processTime(times[0])
            stop = self.processTime(times[1])
            run = stop - start # FIXME - if the test spans midnight this will be wrong!
            
            webAvg = (float(web[0]) + float(web[1]) + float(web[2])) / 3

            rawscores = {}
            scores = {}
            rawscores['java'] = float(java) / run
            scores['java'] = rawscores['java'] / self.referenceScores['java']
            rawscores['db'] = float(db) / run
            scores['db'] = rawscores['db'] / self.referenceScores['db']
            rawscores['mail'] = float(mail) / run
            scores['mail'] = rawscores['mail'] / self.referenceScores['mail']
            rawscores['web'] = webAvg
            scores['web'] = rawscores['web'] / self.referenceScores['web']

            # Calculate geo-mean
            scores['avg'] = (scores['java'] * scores['db'] * scores['mail'] * scores['web']) ** (1/float(4))

            # Return all these
            xenrt.TEC().value("raw_java_%u" % (i),rawscores['java'])
            xenrt.TEC().value("java_%u" % (i),scores['java'])
            xenrt.TEC().value("raw_db_%u" % (i),rawscores['db'])
            xenrt.TEC().value("db_%u" % (i),scores['db'])
            xenrt.TEC().value("raw_mail_%u" % (i),rawscores['mail'])
            xenrt.TEC().value("mail_%u" % (i),scores['mail'])
            xenrt.TEC().value("raw_web_%u" % (i),rawscores['web'])
            xenrt.TEC().value("web_%u" % (i),scores['web'])
            xenrt.TEC().value("avg_%u" % (i),scores['avg'])

            avg.append(scores['avg'])

        # Return the median score as an overall score
        avg.sort()
        xenrt.TEC().value("Average",avg[1])
      
    def processTime(self,timeStr):
        timeSplit = timeStr.split(":")
        return (float(timeSplit[0])*3600 + float(timeSplit[1])*60 + 
                float(timeSplit[2]))

    def setupExchangeAndLoadsim(self,server,client):
        workdir = self.winWorkdir
        domain = self.domain

        # Most of this code is taken straight from TCloadsim (which may be rendered redundant by this TC anyway)

        # AD onto server
        server.winRegAdd("HKLM",
                            "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\"
                            "Winlogon",
                            "DefaultDomainName",
                            "SZ",
                            domain)
        # Make sure the windows CD is in
        server.changeCD("%s.iso" % (server.distro))

        # This gets slightly tricky, we need to give the guest a static IP
        # (as otherwise it complains during AD install), then change it back
        # to dynamic afterwards. For now, use the guest's dynamic IP, and hope
        # the lease is long enough that it won't get reassigned!

        # Get the current IP and subnetmask (this is a bit nasty...)
        # We could use getIP, but to make sure we get the IP that corresponds
        # to the subnet mask, use the same method for both
        ipc = server.xmlrpcExec("ipconfig",returndata=True)
        ipcs = ipc.split("\n")
        ip = ipcs[9][39:]
        snm = ipcs[10][39:]
        dg = ipcs[11][39:]

        # Get current DNS server
        data = server.xmlrpcExec("netsh interface ip show dns",
                                    returndata=True)
        datal = data.split("\n")
        dns = datal[4][42:]

        # Edit dcinstall-auto.txt to replace %DOMAIN%
        dca = server.xmlrpcReadFile("%s\\loadsim\\dcinstall-auto.txt" %
                                       (workdir))
        dca = dca.replace("%DOMAIN%",domain)
        dca = dca.replace("%PASSWORD%",
                          xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS",
                                              "ADMINISTRATOR_PASSWORD"]))
        server.xmlrpcWriteFile("%s\\loadsim\\dcinstall-auto.txt" %
                                  (workdir), dca)

        # Local Area Connection 2 as we assume PV drivers have been installed
        server.xmlrpcStart("ping -n 15 127.0.0.1\n"
                              "netsh interface ip set address \"Local Area "
                              "Connection 2\" static %s %s %s 1\n"
                              "netsh interface ip set dns \"Local Area Connection "
                              "2\" static %s\n"
                              "cd %s\\loadsim\n"
                              "dcpromo /answer:dcinstall-auto.txt" %
                              (ip,snm,dg,dns,workdir))

        # Loadsim onto client
        client.xmlrpcStart("cd %s\\loadsim\n"
                            "msiexec.exe /package loadsim.msi /passive" %
                            (workdir))

        # Now wait for server to reboot
        server.waitToReboot(timeout=3600)

        server.waitForDaemon(300,desc="Waiting for boot after AD install")

        # Return it to DHCP
        server.xmlrpcStart("ping -n 15 127.0.0.1\n"
                              "netsh interface ip set address \"Local Area "
                              "Connection 2\" dhcp")

        time.sleep(30)

        server.waitForDaemon(60,desc="Waiting for guest to return to DHCP")

        # Turn off firewall
        server.xmlrpcExec("netsh firewall set opmode DISABLE")

        # Install support tools
        server.xmlrpcExec("msiexec /package "
                             "d:\\support\\tools\\suptools.msi /passive", timeout=3600)

        # Specify DNS server to forward queries to
        dnscmd = "\"C:\\Program Files\\Support Tools\\dnscmd.exe\""
        server.xmlrpcExec("%s /ResetForwarders %s\n"
                             "%s /ClearCache" % (dnscmd,dns,dnscmd), timeout=3600)

        # Now point client at server's DNS server
        client.xmlrpcExec("netsh interface ip set dns \"Local Area Connection "
                           "2\" static %s" % (ip))
        # Join client to the domain (we hope this finishes before exchange
        # reboots the DC!)
        client.xmlrpcExec("Cscript.exe //Nologo "
                          "%s\\loadsim\\joindomain.vbs %s %s" % (workdir,
                           domain, 
                           xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS",
                                               "ADMINISTRATOR_PASSWORD"])),
                          timeout=3600)
        client.winRegAdd("HKLM",
                          "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\"
                          "Winlogon",
                          "DefaultDomainName",
                          "SZ",
                          domain)
        client.winRegAdd("HKLM",
                          "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\"
                          "Winlogon",
                          "DefaultPassword",
                          "SZ",
                          "%s" % (xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS",
                                                      "ADMINISTRATOR_PASSWORD"])))
        # Put in a registry key to disable the firewall
        client.winRegAdd("HKLM",
                          "SOFTWARE\\Policies\\Microsoft\\WindowsFirewall\\"
                          "DomainProfile",
                          "EnableFirewall",
                          "DWORD",
                          0)
        client.xmlrpcReboot()

        # Now install IIS
        server.xmlrpcExec("sysocmgr /i:%%windir%%\\inf\\sysoc.inf "
                             "/u:%s\\loadsim\\iisinstall.txt" %
                             (workdir), timeout=3600)

        # Now install Exchange
        # Change CD
        server.changeCD("exchange.iso")
        # Disable app compatibility checking
        server.winRegAdd("HKLM",
                            "SOFTWARE\\Policies\\Microsoft\\windows\\AppCompat",
                            "DisableEngine",
                            "DWORD",
                            1)
        # Wait 30 seconds for the CD to actually get through
        time.sleep(30)
        # Edit exchangeinstall.txt to replace %DOMAIN%
        exi = server.xmlrpcReadFile("%s\\loadsim\\exchangeinstall.txt" %
                                       (workdir))
        exi = exi.replace("%DOMAIN%",domain)
        server.xmlrpcWriteFile("%s\\loadsim\\exchangeinstall.txt" %
                                  (workdir), exi)

        server.xmlrpcStart("D:\\setup\\i386\\setup.exe /UnattendFile "
                              "%s\\loadsim\\exchangeinstall.txt" %
                              (workdir))
        # Start the watcher
        server.xmlrpcStart("c:\\soon.exe 120 "
                              "%s\\loadsim\\checkfinished.bat %s\\loadsim "
                              "SETUP.EXE %s %s" % (workdir,
                              workdir,domain,
                              xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS",
                                                  "ADMINISTRATOR_PASSWORD"])))

        # Check in case client hasn't finished rebooting
        client.waitForDaemon(600,
                              desc="Waiting for boot after joining domain")

        # Install outlook onto client
        client.changeCD("outlook.iso")
        # Wait 30 seconds for the CD to actually get through
        time.sleep(30)
        # Start the install
        client.xmlrpcStart("msiexec /package d:\\OUTLS11.msi /passive")

        # Now wait for server to reboot
        server.waitToReboot(timeout=3600)

        server.waitForDaemon(300,
                                desc="Waiting for boot after Exchange install")

        # Exchange updates
        server.changeCD("exchange_update.iso")
        time.sleep(30)
        # Edit exchangeupdate.txt to replace %DOMAIN%
        exu = server.xmlrpcReadFile("%s\\loadsim\\exchangeupdate.txt" %
                                       (workdir))
        exu = exu.replace("%DOMAIN%",domain)
        server.xmlrpcWriteFile("%s\\loadsim\\exchangeupdate.txt" %
                                  (workdir), exu)

        server.xmlrpcStart("D:\\i386\\update.exe /UnattendFile "
                             "%s\\loadsim\\exchangeupdate.txt" %
                             (workdir))
        # Start the watcher
        server.xmlrpcStart("c:\\soon.exe 120 "
                              "%s\\loadsim\\checkfinished.bat %s\\loadsim "
                              "UPDATE.EXE %s %s" % (workdir,
                              workdir,domain,
                              xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS",
                                                  "ADMINISTRATOR_PASSWORD"])))

        # Now wait for server to reboot

        server.waitToReboot(timeout=3600)

        server.waitForDaemon(300,
                                desc="Waiting for boot after Exchange update")
        # Move Exchange data to E
        server.xmlrpcStart("mmc c:\\progra~1\\Exchsrvr\\bin\\Exchan~1.msc")
        time.sleep(5)
        server.xmlrpcAppActivate("Exchange System Manager")
        time.sleep(5)
        keys = "{DOWN},{DOWN},{DOWN},{RIGHT},s1,{DOWN},{RIGHT},s1,{DOWN},{DOWN},{RIGHT},s1,{DOWN},s1,%a,s1,r,s1,{TAB},{TAB},{TAB},{TAB},{TAB},{TAB},{TAB},{TAB},{TAB},{TAB},{TAB},s1,{RIGHT},s1,{TAB},{TAB},{ENTER},s1,E,:,\\,p,r,i,v,1,.,e,d,b,{ENTER},s1,{TAB},{TAB},{ENTER},s1,E,:,\\,p,r,i,v,1,.,s,t,m,{ENTER},{TAB},{TAB},{TAB},{TAB}, ,{TAB},{TAB},{TAB},{ENTER},s1,{LEFT},{ENTER},s120,{ENTER},s20,%{F4},s10"
        server.xmlrpcSendKeys(keys)
        # Move Exchange logs to E
        server.xmlrpcStart("mmc c:\\progra~1\\Exchsrvr\\bin\\Exchan~1.msc")
        time.sleep(5)
        server.xmlrpcAppActivate("Exchange System Manager")
        time.sleep(5)
        keys = "{DOWN},{DOWN},{DOWN},{RIGHT},s1,{DOWN},{RIGHT},s1,{DOWN},{DOWN},s1,%a,s1,r,s1,{TAB},{ENTER},s1,{TAB},{TAB},{TAB},s1,E,:,\\,{ENTER},s1,{TAB},{TAB},{ENTER},s1,{TAB},{TAB},{TAB},s1,E,:,\\,{ENTER},s1,{TAB},{TAB},{TAB},{TAB},{ENTER},s1,{LEFT},{ENTER},s120,{ENTER},s5,%{F4}"
        server.xmlrpcSendKeys(keys)

        # Prepare c:\loadsim.sim
        adf = ("%s\\loadsim\\adfind.exe -gc -b \"CN=Servers,CN=First Administra"
               "tive Group,CN=Administrative Groups,CN=XenRT,CN=Microsoft Excha"
               "nge,CN=Services,CN=Configuration,DC=%s,DC=testdomain\"" %
              (workdir,domain))

        # Get the server's hostname
        sn = server.xmlrpcGetEnvVar("COMPUTERNAME")
        data = client.xmlrpcExec("%s -f \"adminDisplayName=%s\" "
                                 "adminDisplayName objectGUID" % (adf,sn),
                                 returndata=True, timeout=7200)

        datal = data.split("\n")
        for l in datal:
            if l.startswith(">objectGUID: "):
                machine_guid = self.fixGUID(l[13:])
            if l.startswith(">adminDisplayName: "):
                machine_name = l[19:]

        data = client.xmlrpcExec("%s -f \"adminDisplayName=First Storage "
                                 "Group\" objectGUID" % (adf),
                                 returndata=True, timeout=7200)

        datal = data.split("\n")
        for l in datal:
            if l.startswith(">objectGUID: "):
                storage_guid = self.fixGUID(l[13:])

        data = client.xmlrpcExec("%s -f \"adminDisplayName=Mailbox Store "
                                 "*\" objectGUID" % (adf),returndata=True, timeout=7200)

        datal = data.split("\n")
        for l in datal:
            if l.startswith(">objectGUID: "):
                mailbox_guid = self.fixGUID(l[13:])

        client_name = client.xmlrpcGetEnvVar("COMPUTERNAME")

        # Load in the template
        template = client.xmlrpcReadFile("%s\\vconsolidate\\mail\\loadsim.sim" %
                                         (workdir))
        # Do some replacement
        template = template.replace("%MACHINE_GUID%",machine_guid)
        template = template.replace("%MACHINE_NAME%",machine_name)
        template = template.replace("%STORAGE_GUID%",storage_guid)
        template = template.replace("%MAILBOX_GUID%",mailbox_guid)
        template = template.replace("%CLIENT_NAME%",client_name)       
        template = template.replace("%DOMAIN%",self.domain)

        # Now write the file back
        client.xmlrpcWriteFile("c:\\loadsim.sim",template)

    def fixGUID(self,orig):
        # Strip out -'s
        orig = orig.replace("-","")

        # Fix layout (believed to be due to endianness)
        fixed = orig[:9]
        fixed += orig[13:17]
        fixed += orig[9:13]
        fixed += orig[23:25]
        fixed += orig[21:23]
        fixed += orig[19:21]
        fixed += orig[17:19]
        fixed += orig[31:33]
        fixed += orig[29:31]
        fixed += orig[27:29]
        fixed += orig[25:27]
        fixed += "}"

        return fixed

    def startWebBench(self,client,server):
        client.xmlrpcStart("c:\\WebBench\\Client\\Client.exe")
        server.xmlrpcStart("cd c:\\WebBench\\Controller\n"
                           "c:\\WebBench\\Controller\\Controller.exe")
        time.sleep(5)
        server.xmlrpcAppActivate("WebBench")
        time.sleep(5)
        server.xmlrpcSendKeys("{PGDN},{TAB}, ,s1,{TAB},{TAB}, ,s1,%c,s,s30, ,s1, ,{TAB},{TAB},{TAB},{TAB},{RIGHT},s1,{UP},{UP},{UP},{UP},{UP},{UP},{UP},{DOWN},{DOWN},{DOWN},{DOWN},{DOWN},{DOWN},{ENTER},s1,{TAB},{TAB},{DOWN},{ENTER},s1,{DOWN},{DOWN},{DOWN},{DOWN},{ENTER},s1,{TAB},{TAB},{TAB},{TAB},{TAB},{TAB},{ENTER},s1,{RIGHT}")

