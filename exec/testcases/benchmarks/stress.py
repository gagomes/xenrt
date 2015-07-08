#
# XenRT: Test harness for Xen and the XenServer product family
#
# Stress tests
#
# Copyright (c) Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import sys, string, time, xmlrpclib, os.path, re, socket, xml.dom.minidom
import xenrt

class TCburnintest(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCburnintest"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="burnintest")
        self.workdir = None
        self.bitcfg = None
        self.amd64 = False
        self.nolinux = True
        self.guest = None

    def startRun(self, guest):
        # Get a working directory on the guest.
        self.workdir = guest.xmlrpcTempDir()

        self.guest = guest

        # Unpack the test binaries.
        if self.amd64:
            testname = "burnintest64"
            eargs = "-p"
        else:
            testname = "burnintest"
            eargs = ""

        if not xenrt.checkTarball("%s.tgz" % (testname)):
            xenrt.TEC().skip("Test tarball not found")
            return None

        guest.xmlrpcUnpackTarball("%s/%s.tgz" %
                          (xenrt.TEC().lookup("TEST_TARBALL_BASE"), testname),
                          self.workdir)

        # Run the benchmark.
        ref = guest.xmlrpcStart("cd %s\\%s\n"
                                "bit.exe -C %s\\%s\\%s -R -x %s" %
                                (self.workdir,
                                 testname,
                                 self.workdir,
                                 testname,
                                 self.bitcfg,
                                 eargs))
        time.sleep(60)
        if not "bit.exe" in guest.xmlrpcPS():
            raise xenrt.XRTFailure("Burnintest failed to start.")
        return ref

    def stopRun(self, guest):
        if not "bit.exe" in guest.xmlrpcPS():
            raise xenrt.XRTFailure("Burnintest no longer running.")
        guest.xmlrpcKillAll("bit.exe")
        if "bit.exe" in guest.xmlrpcPS():
            raise xenrt.XRTFailure("Burnintest failed to die.")

    def runViaDaemon(self, remote, arglist):

        if remote.xmlrpcGetArch() == "amd64":
            self.amd64 = True
            testname = "burnintest64"
        else:
            testname = "burnintest"

        self.declareTestcase("CPU", "CPU")
        self.declareTestcase("Memory", "RAM")
        self.declareTestcase("Disk", "DriveC")
        self.declareTestcase("Network", "1")
       
        # Possible lengths
        lengths = {1:"1hour.bitcfg", 12:"12hours.bitcfg", 24:"24hours.bitcfg",
                  48:"48hours.bitcfg", 72:"72hours.bitcfg", 0:"15mins.bitcfg"}
 
        guest = remote
        
        # Get duration (argument 0 is a number of hours)
        if arglist and len(arglist) > 0:
            hours = int(arglist[0])
            if (lengths.has_key(hours)):
                self.bitcfg = lengths[hours]
            else:
                raise xenrt.XRTError("burnintest length parameter '%s' invalid"
                                     % (arglist[0]))
        else:
            vals = lengths.keys()
            vals.sort()
            hours = vals[0]
            self.bitcfg = lengths[hours]
        xenrt.TEC().comment("Duration will be %u hours" % (hours))

        ref = self.startRun(guest)
        if not ref:
            return
        t = hours * 3600 + 3600
        runok = False
        try:
            guest.xmlrpcWait(ref, timeout=t)
            runok = True
            # Give the VM 5 minutes to settle
            xenrt.TEC().logverbose("Allowing 5 minutes for the VM to settle...")
            time.sleep(300)
        finally:
            # Fetch (or try to) the log files even if the app errored
            try:
                logfiles = guest.xmlrpcGlobPattern("%s\\%s\\results_*.log" %
                                                   (self.workdir, testname))
                if len(logfiles) == 0:
                    raise xenrt.XRTError("No result files found")
                logfiles.sort()
                data = None
                for lf in logfiles:
                    data = guest.xmlrpcReadFile(lf)
                    f = file("%s/%s" %
                             (self.tec.getLogdir(),
                              os.path.basename(string.replace(lf, '\\', '/'))),
                             "w")
                    f.write(data)
                    f.close()
            except Exception, e:
                # Only worry about exceptions here if the bit.exe run
                # did not return error or raise some other exception.
                if runok:
                    raise e
            # See if there are any dump files
            try:
                if self.amd64:
                    dmpfiles = guest.xmlrpcGlobPattern("%s\\%s\\*.dmp" %
                                                       (self.workdir, testname))
                else:
                    dmpfiles = guest.xmlrpcGlobPattern("c:\\documents and settings\\administrator\\my documents\\passmark\\burnintest\\*.dmp")
                dmpfiles.sort()
                dmp = None
                for df in dmpfiles:
                    dmp = guest.xmlrpcReadFile(df)
                    f = file("%s/%s" %
                             (self.tec.getLogdir(),
                              os.path.basename(string.replace(df, '\\', '/'))),
                             "w")
                    f.write(dmp)
                    f.close()
            except Exception, e:
                xenrt.TEC().logverbose("Exception while fetching dump files: "
                                       "%s" % (str(e)))
                
        # Process the results
        # The most recent file content is in the data variable
        reason = None
        #if not re.search(r"^TEST RUN PASSED", data, re.MULTILINE):
        self.runSubcase("parseResults", (data, "CPU"), "CPU", "CPU")
        self.runSubcase("parseResults", (data, "Memory \\(RAM\\)"), "Memory",
                        "RAM")
        self.runSubcase("parseResults", (data, "Disk \\(C:\\)"), "Disk", "DriveC")
        self.runSubcase("parseResults", (data, "Network 1"), "Network", "1")

    def parseResults(self, data, tag):
        r = re.search("^\s+%s\s+(\d+)\s+([\d\.]+ \w+|[\d\.]+)\s+(PASS|FAIL)"
                      "\s+(\d+)\s+(.*)$" % (tag),
                      data,
                      re.MULTILINE)
        if not r:
            raise xenrt.XRTError("Could not find '%s' in results file" % (tag))
        err = r.group(5).strip()
        self.tec.comment("%s: cycles: %s  operations: %s  result: %s  "
                         "errors: %s" %
                         (tag, r.group(1), r.group(2), r.group(3), r.group(4)))
        if r.group(3) == "FAIL":
            msg = "%s (x %s)" % (err, r.group(4))
            if err == "Timeout waiting for packet" and \
                   int(r.group(4)) < 100:
                xenrt.TEC().warning(msg)
            else:
                raise xenrt.XRTFailure(msg)

    def postRun(self):
        try:
            self.guest.xmlrpcKillAll("bit.exe")
        except:
            pass

class TCstress(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCstress"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="stress")

class TCslurp(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCslurp"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="slurprun")

class TCMappedFile(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCMappedFile")

    def run(self, arglist):

        duration = 7200
        threads = 2

        guest = self.getLocation()
        self.storedguest = guest
        self.getLogsFrom(guest.host)
        
        if not guest.windows:
            xenrt.TEC().skip("Not running on windows.")
            return

        guest.xmlrpcCreateEmptyFile("c:\\mappedfile.dat", 1024)
        f = file("%s/progs/mappedfiletest.exe" %
                 (self.tec.lookup("LOCAL_SCRIPTDIR")), "rb")
        mfte = f.read()
        f.close()
        guest.xmlrpcCreateFile("c:\\mappedfiletest.exe", xmlrpclib.Binary(mfte))

        readers = []
        writers = []

        for i in range(threads):
            readers.append(None)
            writers.append(None)

        started = xenrt.timenow()
        w = 0
        r = 0
        f = 0
        stop = False
        xenrt.TEC().logverbose("Starting main loop")
        while True:
            time.sleep(15)
            now = xenrt.timenow()
            if now > (started + duration):
                stop = True
            
            # Check the status of the threads
            any = False
            for i in range(threads):
                if not readers[i] and not stop:
                    readers[i] = guest.xmlrpcStart("c:\\mappedfiletest.exe "
                                                   "READ c:\\mappedfile.dat")
                if not writers[i] and not stop:

                    writers[i] = guest.xmlrpcStart("c:\\mappedfiletest.exe "
                                                   "WRITE 1024")
                try:
                    if readers[i] and guest.xmlrpcPoll(readers[i], retries=3):
                        ref = readers[i]
                        self.tec.log(guest.xmlrpcLog(ref))
                        readers[i] = None
                        r = r + 1
                        if guest.xmlrpcReturnCode(ref) != 0:
                            f = f + 1   
                except socket.error:
                    pass
                try:                     
                    if writers[i] and guest.xmlrpcPoll(writers[i], retries=3):
                        ref = writers[i]
                        self.tec.log(guest.xmlrpcLog(ref))
                        writers[i] = None
                        w = w + 1
                        if guest.xmlrpcReturnCode(ref) != 0:
                            f = f + 1
                except socket.error:
                    pass
                if readers[i]:
                    any = True
                if writers[i]:
                    any = True
            if stop and not any:
                break
                    
        self.tec.comment("%u writers and %u readers completed" % (w, r))
        if f > 0:
            self.tec.warning("One or more operations returned an error")

    def postRun(self):
        guest = self.storedguest
        try:
            guest.xmlrpcKillAll("mappedfiletest.exe")
        except:
            pass
        guest.xmlrpcRemoveFile("c:\\mappedfile.dat")

class TCHCTStress(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCHCTStress")
        self.verifier = True

    def run(self, arglist):

        duration = 8 # hours
        tests = 7

        if arglist and len(arglist) > 0:
            duration = int(arglist[0])
            for arg in arglist[1:]:
                l = string.split(arg, "=", 1)
                if l[0] == "tests":
                    tests = int(l[1])
                if l[0] == "noverify":
                    self.verifier = False
        
        guest = self.getLocation()
        self.getLogsFrom(guest.host)
        self.storedguest = guest
        if not guest.windows:
            xenrt.TEC().skip("Not running on windows.")
            return

        # Make sure the guest is up
        if guest.getState() == "DOWN":
            xenrt.TEC().comment("Starting guest before commencing test")
            guest.start()

        # Enable driver verifier
        if self.verifier:
            guest.enableDriverVerifier()

        # fetch and unpack stress.tgz into  c:\stress
        guest.xmlrpcUnpackTarball("%s/hct/stress.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")

        # Get out domid before the test to check for reboots
        domid = guest.getDomid()

        # Logging
        data = guest.xmlrpcExec("verifier.exe /query", returndata=True)
        f = file("%s/verifier_before.txt" % (self.tec.getLogdir()), "w")
        f.write(data)
        f.close()
        
        # Change in to c:\stress and run runstrss.exe <duration> <tests>
        self.tec.comment("Duration will be %u hours" % (duration))
        self.tec.comment("Number of tests will be %u" % (tests))
        ref = guest.xmlrpcStart("cd \\stress\nrunstrss.exe %u %u" % (duration, tests))
        
        deadline = xenrt.timenow() + (3600 * duration) + 1800
        excount = 0
        while True:
            time.sleep(120)
            if xenrt.timenow() > deadline:
                raise xenrt.XRTFailure("HCT stress still running after timeout")
            try:
                if guest.xmlrpcPoll(ref):
                    break
                excount = 0
            except Exception, e:
                excount = excount + 1
                if excount > 5:
                    raise e

        # When complete grab c:\stress\stress.log
        data = guest.xmlrpcReadFile("c:\\stress\\stress.log")
        f = file("%s/stress.log" % (self.tec.getLogdir()), "w")
        f.write(data)
        f.close()

        # Verifier data
        data = guest.xmlrpcExec("verifier.exe /query", returndata=True)
        f = file("%s/verifier_after.txt" % (self.tec.getLogdir()), "w")
        f.write(data)
        f.close()
            
        # Try to find out whether there was a crash etc.
        time.sleep(120)
        if guest.getState() != "UP":
            raise xenrt.XRTFailure("Guest was not UP after tests exited")
        if guest.getDomid() != domid:
            raise xenrt.XRTFailure("Guest has rebooted during tests")
        if not guest.xmlrpcIsAlive():
            raise xenrt.XRTFailure("Could not reach guest after tests exited")

    def postRun(self):
        guest = self.storedguest
        try:
            guest.xmlrpcKillAll("runstrss.exe")
        except:
            pass
        if self.verifier:
            guest.enableDriverVerifier(False)

class TCamdsst(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCamdsst"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="amdsst")
        self.workdir = None
        self.length = 3600
        self.nolinux = True
        self.guest = None

    def startRun(self, guest):
        # Get a working directory on the guest.
        self.workdir = guest.xmlrpcTempDir()

        # Unpack the test binaries.
        guest.xmlrpcUnpackTarball("%s/amdsst.tgz" %
                          (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                          self.workdir)
        
        # Install AMD SST
        guest.xmlrpcExec("cd %s\\amdsst\n"
                         "setup.exe /quiet" % (self.workdir), timeout=3600)

        # Set registry settings
        # Autostart
        guest.winRegAdd("HKLM",
                                    "SOFTWARE\\AMD\\SST4",
                                    "Autostart",
                                    "SZ",
                                    "true")
        # Runtime
        guest.winRegAdd("HKLM",
                                    "SOFTWARE\\AMD\\SST4",
                                    "Runtime",
                                    "SZ",
                                    "%s" % (self.length))

        # Stop on error
        guest.winRegAdd("HKLM",
                                    "SOFTWARE\\AMD\\SST4",
                                    "StopOnError",
                                    "SZ",
                                    "true")                                   
              
        # Run the benchmark.
        time.sleep(900) # allow 15 minutes before starting to give it a chance to settle
        ref = guest.xmlrpcStart("cd %s\\amdsst\n"
                         "CScript.exe //Nologo amdsst.vbs" % (self.workdir))

        xenrt.TEC().logverbose("Waiting for AMDSST to start")
        for iteration in range(60):
            if "AMDSST.exe" in guest.xmlrpcPS():
                return ref
            time.sleep(1)
        
        raise xenrt.XRTFailure("AMDSST failed to start.")

    def stopRun(self, guest):
        if not "AMDSST.exe" in guest.xmlrpcPS():
            raise xenrt.XRTFailure("AMDSST no longer running.")
        guest.xmlrpcKillAll("AMDSST.exe")
        if "AMDSST.exe" in guest.xmlrpcPS():
            raise xenrt.XRTFailure("AMDSST failed to die.")

    def runViaDaemon(self, remote, arglist):
        
        guest = remote
        self.guest = guest
       
        try:
            if guest.host:
                v = guest.host.getCPUVendor()
                if v == "GenuineIntel":
                    xenrt.TEC().skip("Not running AMD SST on Intel")
                    return
        except:
            pass
 
        # Get duration (argument 0 is a number of hours)
        if arglist and len(arglist) > 0:
            hours = int(arglist[0])
            self.length = (hours * 3600)
        
        xenrt.TEC().comment("Duration will be %u hours" % (self.length / 3600))
        
        
        ref = self.startRun(guest)
        t = self.length + 3600
        guest.xmlrpcWait(ref, timeout=t, level=xenrt.RC_OK, cleanup=False)
        
        # See what the return code was
        rc = guest.xmlrpcReturnCode(ref)
        guest.xmlrpcCleanup(ref)
        if rc == 1:
            xenrt.TEC().comment("AMDSST reported a configuration error")
        elif rc == 2:
            raise xenrt.XRTFailure("AMDSST reported a test error!")
        elif rc > 2:
            raise xenrt.XRTError("Unknown return code received")
        
        # Grab any HTML log files
        logfiles = guest.xmlrpcGlobPattern(
                       "C:\\Program Files\\AMD\\System Stress Test 4\\*.html")
        
        for lf in logfiles:
            data = guest.xmlrpcReadFile(lf)
            fn = os.path.basename(lf.replace("\\","/"))
            f = file("%s/%s" % (xenrt.TEC().getLogdir(), fn), "w")
            f.write(data)
            f.close()

    def postRun(self):
        try:
            self.guest.xmlrpcKillAll("AMDSST.exe")
        except:
            pass

class TCSQLIOSim(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCSQLIOSim"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="SQLIOSim")
        self.workdir = None
        self.length = 300
        self.allowedErrs = ["Unable to get disk cache info for c:\\"]
        self.nolinux = True
        self.guest = None
        
    def startRun(self, guest):
        # Get a working directory on the guest.
        self.workdir = guest.xmlrpcTempDir()

        # Unpack the test binaries.
        guest.xmlrpcUnpackTarball("%s/sqliosim.tgz" %
                          (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                          self.workdir)


        # Start it up...
        ref = guest.xmlrpcStart("cd %s\\sqliosim\n"
                            "%%PROCESSOR_ARCHITECTURE%%\\sqliosim.com -d %s" %
                            (self.workdir,self.length))

        time.sleep(5)
        if not "sqliosim.com" in guest.xmlrpcPS():
            raise xenrt.XRTFailure("SQLIOSim failed to start.")
        return ref

    def stopRun(self, guest):
        if not "sqliosim.com" in guest.xmlrpcPS():
            raise xenrt.XRTFailure("SQLIOSim no longer running.")
        guest.xmlrpcKillAll("sqliosim.com")
        if "sqliosim.com" in guest.xmlrpcPS():
            raise xenrt.XRTFailure("SQLIOSim failed to die.")

    def runViaDaemon(self, remote, arglist):

        guest = remote
        self.guest = guest

        # Get duration (argument 0 is a number of minutes)
        if arglist and len(arglist) > 0:
            mins = int(arglist[0])
            self.length = (mins * 60)

        xenrt.TEC().comment("Duration will be %u minutes" % (self.length / 60))

        if guest.xmlrpcGetArch() == "amd64":
            xenrt.TEC().skip("Skipping SQLIO on x64")
            return

        ref = self.startRun(guest)
        t = self.length + 3600
        guest.xmlrpcWait(ref, timeout=t, level=xenrt.RC_OK)

        # Now grab the log file back
        logfile = "%s\\sqliosim\\sqliosim.log.xml" % (self.workdir)
        guest.xmlrpcGetFile2(logfile,
                             "%s/sqliosim.log.xml" % (xenrt.TEC().getLogdir()))
        
        # Also grab the xslt file to make it easy to view
        xslt = "%s\\sqliosim\\ErrorLog.xslt" % (self.workdir)
        guest.xmlrpcGetFile2(xslt,
                             "%s/ErrorLog.xslt" % (xenrt.TEC().getLogdir()))

        # Now parse it
        dom = xml.dom.minidom.parse("%s/sqliosim.log.xml" % 
                                    (xenrt.TEC().getLogdir()))

        extended_descs = dom.getElementsByTagName("EXTENDED_DESCRIPTION")

        for desc in extended_descs:
            if desc.childNodes[0].data.startswith("Target IO Duration"):
                # This is the line we want
                m = re.match("Target IO Duration \(ms\) = (\d+), Running " +
                             "Average IO Duration \(ms\) = (\d+), Number of " +
                             "times IO throttled = (\d+), IO request blocks " +
                             "= (\d+)",desc.childNodes[0].data)
                self.tec.value("Average_IO_Duration", m.group(2), "ms")
                self.tec.value("Num_Time_IO_Throttled", m.group(3))
                self.tec.value("IO_Request_Blocks", m.group(4))
                break

        entries = dom.getElementsByTagName("ENTRY")
        for entry in entries:
            if entry.attributes['TYPE'].value == "ERROR":
                for child in entry.childNodes:
                    if isinstance(child,xml.dom.minidom.Element):
                        if child.tagName == "EXTENDED_DESCRIPTION":
                            # Check for ignored ones
                            desc = child.firstChild.data
                            if desc in self.allowedErrs:
                                continue
                            raise xenrt.XRTFailure("Error in logfile: %s" %
                                                   (desc))

    def postRun(self):
        try:
            self.guest.xmlrpcKillAll("sqliosim.com")
        except:
            pass

class TCcorestress(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCcorestress"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="corestress")
        # Default duration 30 minutes
        self.duration = 30
        self.nolinux = True
        self.guest = None

    def runViaDaemon(self, remote, arglist):

        self.guest = remote

        if remote.xmlrpcWindowsVersion() == "5.0":
            xenrt.TEC().skip("Skipping TCcorestress on Windows 2000")
            return

        # See if we've been given a duration
        if arglist and len(arglist) > 0:
            for arg in arglist:
                l = arg.split("=")
                if l[0] == "duration":
                    self.duration = int(l[1])
        timeout = (self.duration + 60) * 60

        # Get a working directory on the guest
        workdir = remote.xmlrpcTempDir()
        # Unpack tarball
        remote.xmlrpcUnpackTarball("%s/corestress.tgz" %
                                     (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                     workdir)

        # Put the duration into the file
        xenrt.TEC().comment("Test duration will be %d minutes" % (self.duration))
        conf = remote.xmlrpcReadFile("%s\\corestress\\DRS_Stress.ini" % 
                                     (workdir))
        newconf = conf.replace("%DURATION%",str(self.duration))
        remote.xmlrpcWriteFile("%s\\corestress\\DRS_Stress.ini" % (workdir), 
                               newconf)

        # Now start it
        remote.xmlrpcExec("cd %s\\corestress\n"
                          "runstrss.exe" % (workdir),
                          timeout=timeout)

        # If we get here, then we've passed (a failure is if it brings down the
        # VM or Xen)

    def postRun(self):
        try:
            self.guest.xmlrpcKillAll("runstrss.exe")
        except:
            pass

class TCdvdstore(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCdvdstore"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="dvdstore")
        self.guestsToClean = []

    def run(self,arglist=None):
        machine = "RESOURCE_HOST_0"
        distro = "rhel5"
        arch = "x86-32"
        method = "HTTP"
        gname = None

        # First argument is the Windows guest to use to run the tests from
        # (ideally on a second host)
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("You must specify a Windows guest")

        winGuest = xenrt.TEC().registry.guestGet(gname)
        if not winGuest:
            raise xenrt.XRTError("Cannot find guest %s" % (gname))

        self.winGuest = winGuest

        # Unpack the tarball
        self.workdir = winGuest.xmlrpcTempDir()
        winGuest.xmlrpcUnpackTarball("%s/dvdstore.tgz" % 
                                     (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                     self.workdir)

        # Set up the template guest
        extrapackages = ["mysql","mysql-server","mysql-devel","php","php-mysql"]
        repository = xenrt.getLinuxRepo(distro, arch, method)

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)

        # Find out how much memory we have available
        memFree = host.getFreeMemory()
        # Get the number of 256M guests we can create
        maxGuests = memFree / 256
        # We need to create at least two
        if maxGuests < 2:
            raise xenrt.XRTError("Need at least 512MB free memory on host, "
                                 "got %u" % (memFree))

        template = xenrt.lib.xenserver.getTemplate(host,distro,arch=arch)

        guestToClone = host.guestFactory()("dvdstoreMaster", template)
        g = guestToClone
        self.guestsToClean.append(g)
        g.windows = False
        g.arch = arch
        g.install(host, repository=repository, distro=distro, method=method, 
                  extrapackages=extrapackages)
        g.check()

        workdir = g.execguest("mktemp -d /tmp/workXXXXXX").strip()

        # Unpack tarball
        g.execguest("wget '%s/dvdstore.tgz' -O - | tar -zx -C %s" %
                    (xenrt.TEC().lookup("TEST_TARBALL_BASE"),
                    workdir))

        # Set up MySQL etc on the guest

        # Disable SELinux
        g.execguest("grep -ve '^SELINUX=' /etc/selinux/config > "
                    "/etc/selinux/config2 && echo 'SELINUX=disabled' >> "
                    "/etc/selinux/config2 && mv /etc/selinux/config2 "
                    "/etc/selinux/config")
        g.execguest("echo 0 > /selinux/enforce")

        # Add a 20GB disk
        g.createDisk(sizebytes=21474836480)
        time.sleep(10)
        g.execguest("chown mysql:mysql /dev/xvdb")
        g.execguest("echo \"chown mysql:mysql /dev/xvdb\" >> /etc/rc.d/rc.local")
        
        # Copy in our my.cnf file
        g.execguest("cp -f %s/dvdstore/my.cnf /etc/my.cnf" % (workdir))
        # Start MySQL
        g.execguest("/usr/bin/mysql_install_db")
        g.execguest("/etc/init.d/mysqld start",retval="code")

        # Wait for the log to show it's created the raw file (with 30m timeout)
        st = xenrt.util.timenow()
        deadline = st + (30 * 60)
        while True:
            if g.execguest("grep \"InnoDB: Started\" /var/log/mysqld.log",
                           retval="code") == 0:
                break
            if xenrt.util.timenow() > deadline:
                raise xenrt.XRTError("InnoDB did not initialise within timeout "
                                     "period")
            time.sleep(20)

        # Stop MySQL
        g.execguest("/etc/init.d/mysqld stop")
        # Apply our my.cnf patch
        g.execguest("cd /etc && patch -p0 < %s/dvdstore/cnfpatch" % (workdir))
        # Start MySQL again
        g.execguest("/etc/init.d/mysqld start")
        # Set it to autostart (have to do it this way as otherwise our chown won't have
        # happened in time and it won't start...
        g.execguest("echo \"/etc/init.d/mysqld start\" >> /etc/rc.d/rc.local")

        # Set up dvdstore (this takes a while!)
        g.execguest("cd %s/dvdstore && ./setup.sh" % (workdir),timeout=7200)

        # Set up the web bits
        g.execguest("mkdir /var/www/html/ds2 && cp "
                    "%s/dvdstore/ds2/mysqlds2/web/php5/* /var/www/html/ds2/" % 
                    (workdir))
        g.execguest("/etc/init.d/httpd start")
        g.execguest("chkconfig --add httpd && chkconfig --level 345 httpd on")
        g.execguest("echo \"GRANT ALL ON DS2.* TO apache@localhost\" | mysql")

        # Disable iptables
        g.execguest("chkconfig --del iptables")

        # Prepare the VM for cloning, and shut it down
        g.preCloneTailor()
        g.shutdown()

        # Start with 2 clones, run the tests and get an OPM value
        guests = []
        guests.append(g.cloneVM())
        guests.append(g.cloneVM())

        for g in guests:
            self.guestsToClean.append(g)
            g.start()
        time.sleep(30)

        opm = self.runTest(guests)
        xenrt.TEC().comment("2 guests gives OPM value %u" % (opm))

        # Now keep adding clones until the OPM value is lower than previous one
        # Or we run out of resources
        guestCount = 2
        lastopm = opm
        while guestCount < maxGuests:
            numGuests = len(guests)
            g = guestToClone.cloneVM()
            g.start()
            self.guestsToClean.append(g)
            guests.append(g)
            time.sleep(30)
            opm = self.runTest(guests)
            xenrt.TEC().comment("%u guests gives OPM value %u" % (len(guests),
                                                                  opm))
            if opm < lastopm:
                break

            lastopm = opm
            guestCount += 1

        if guestCount == maxGuests and opm >= lastopm:
            xenrt.TEC().warning("Could not create more guests due to lack of "
                                "memory.")

        # Return as results the maximum OPM and the number of clones used for it
        xenrt.TEC().value("MaxOPM",lastopm)
        xenrt.TEC().value("GuestCount",numGuests)

    def runTest(self,guests):
        # Run the test against guests and return an OPM value
        wg = self.winGuest
        refs = {}
        for g in guests:
            refs[g] = wg.xmlrpcStart("%s\\dvdstore\\ds2webdriver.exe --target=%s "
                                     "--think_time=2 --db_size_str=M --run_time"
                                     "=15 --n_threads=30" % (self.workdir,
                                                             g.mainip))
        # Now wait for them to finish
        st = xenrt.util.timenow()
        deadline = st + (20 * 60)
        while True:
            running = False
            for g in guests:
                if not wg.xmlrpcPoll(refs[g]):
                    running = True
                    break
            if not running:
                break
            if xenrt.util.timenow() > deadline:
                raise xenrt.XRTError("Run did not complete after 20 minutes")
            time.sleep(60)
        # Get the results back and parse them
        logs = {}
        for g in guests:
            if wg.xmlrpcReturnCode(refs[g]) <> 0:
                raise xenrt.XRTError("ds2webdriver for guest %s returned an"
                                     "error code" % (g))
            logs[g] = wg.xmlrpcLog(refs[g])
        opm = 0
        for log in logs.values():
            lines = log.split("\n")
            for line in lines:
                m = re.match("^Final: .* opm=(\d+) .*",line)
                if m:
                    opm += int(m.group(1))
        return opm

    def postRun(self):
        for g in self.guestsToClean:
            try:
                g.shutdown(force=True)
            except:
                pass
            g.poll("DOWN", 120, level=xenrt.RC_ERROR)
            g.uninstall()
            time.sleep(15)
