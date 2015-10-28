#
# XenRT: Test harness for Xen and the XenServer product family
#
# Storage tests
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import string, os.path, re, glob, os, time, xml.dom.minidom
import xenrt
import xenrt.lib.xenserver.cli
import xenrt.lib.xenserver
from xenrt.lazylog import log, step
from abc import ABCMeta, abstractmethod, abstractproperty


class TCGUIJUnit(xenrt.TestCase):

    def __init__(self, tcid="TCGUIJUnit"):
        xenrt.TestCase.__init__(self, tcid)

    def run(self, arglist=None):
        cver = xenrt.TEC().lookup(["CLIOPTIONS", "VERSION"], "xenserver")

        # Get the test scripts
        testtar = xenrt.TEC().lookup("GUI_JUNIT_TESTS", None)
        if not testtar:
            # Try the same directory as the ISO
            testtar = xenrt.TEC().getFile("%s-client-tests.tar" % (cver))
        if not testtar:
            raise xenrt.XRTError("No GUI JUnit test tarball given")
        xenrt.command("tar -xf %s -C %s" % (testtar, self.tec.getWorkdir()))

        # Unpack the client
        client_install = xenrt.TEC().getDir("client_install")
        rpms = glob.glob("%s/*-client-*.rpm" % (client_install))
        for rpm in rpms:
            xenrt.command("cd %s; rpm2cpio \"%s\" | cpio -idv" %
                          (self.tec.getWorkdir(), rpm))

        # Run the tests
        client = "%s/opt/xensource/%s-client" % (self.tec.getWorkdir(), cver)
        ant_home = "%s/ext/ant" % (self.tec.getWorkdir())
        java_home = "%s/jre" % (client)
        os.mkdir("%s/results" % (self.tec.getLogdir()))
        os.mkdir("%s/runtime/log" % (client))

        xenrt.command("cd %s ; ANT_HOME=%s JAVA_HOME=%s %s/bin/ant -v "
                      "  -buildfile \"projects/gui.hg/build.xml\""
                      "  -DCLIENT_LOCATION=\"%s/runtime\""
                      "  -Dtests.builddir=\"%s/javatree/test\""
                      "  -Dtests.formatter=plain"
                      "  -Dtests.results.dir=\"%s/results\""
                      "  -DLOGDIR=\"%s\""
                      "  -DCLIENT_NAME=%s-client"
                      "  prebuilttests" %
                      (self.tec.getWorkdir(), ant_home, java_home, ant_home,
                       client,
                       self.tec.getWorkdir(), self.tec.getLogdir(),
                       self.tec.getLogdir(), cver))

        # Process results
        for fn in glob.glob("%s/results/TEST-*.txt" % self.tec.getLogdir()):
            suite = None
            testsrun = 0
            failures = 0
            errors = 0
            f = file(fn, "r")
            while True:
                line = f.readline()
                if not line:
                    break
                r = re.search(r"Testsuite: (\S+)", line)
                if r:
                    suite = r.group(1)
                r = re.search(r"Tests run: (\d+), Failures: (\d+), "
                              "Errors: (\d+)", line)
                if r:
                    testsrun = int(r.group(1))
                    failures = int(r.group(2))
                    errors = int(r.group(3))
            f.close()
            if suite:
                if failures > 0:
                    result = xenrt.RESULT_FAIL
                elif errors > 0 or testsrun == 0:
                    result = xenrt.RESULT_ERROR
                else:
                    result = xenrt.RESULT_PASS
                self.testcaseResult(None, suite, result)


class TCGUISelfTest(xenrt.TestCase):

    def __init__(self, tcid="TCGUISelfTest"):
        xenrt.TestCase.__init__(self, tcid)
        self.guestsToClean = []
        # Bad log entries from Ewan M
        self.badentries = ["AutomatedTests: Error writing screencap to file",
            "Bad VNC server message:",
            "Could not encrypt session",
            "Could not hash entered password",
            "Could not resolve the pool object for the current connection when asked to remove member",
            "Disconnected at the end of New Pool wizard",
            "Error drawing image from server",
            "Error from VIF table:",
            "Error parsing provision XML in New VM Wizard:",
            "Error updating host list drop down menu:",
            "Exception rebooting host:",
            "Exception shutting down VMs before shutting down host",
            "Exception shutting down host:",
            "Exception trying to re-enable host after error rebooting Host",
            "Exception trying to re-enable host after error shutting down Host",
            "Exception trying to re-enable host after error shutting down VMs",
            "Exception whilst handling clipboard changed event:",
            "FATAL",
            "No dom0 on host when connecting to host VNC console",
            "No local copy of host information when connecting to host VNC console",
            "PercentComplete is erroneously",
            "System.NullReferenceException: Object reference not set to an instance of an object",
            "There was an error calling assert_can_boot_here on host",
            "There was an error generating host drop down menu",
            "null source when attempting to connect to host VNC",
            "sr = null in FinishWizard",
            "srWrapper = null in FinishWizard",
            "vm = null in FinishWizard"]
        # Entries that are automatically fatal
        self.fatalentries = ["FATAL"]

    def run(self, arglist=None):

        machine = "RESOURCE_HOST_0"
        target = "RESOURCE_HOST_0"
        distro = "w2k3eesp2"
        inputdir = None
        rootdisk = xenrt.lib.xenserver.Guest.DEFAULT
        if arglist and len(arglist) > 0:
            machine = arglist[0]
        if arglist and len(arglist) > 1:
            for arg in arglist[1:]:
                l = string.split(arg, "=", 1)
                if l[0] == "distro":
                    distro = l[1]
                elif l[0] == "target":
                    target = l[1]
                elif l[0] == "input":
                    inputdir = l[1]
                elif l[0] == "disksize" or l[0] == "rootdisk":
                    if l[1] != "DEFAULT":
                        rootdisk = int(l[1])
        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)

        if inputdir:
            xenrt.TEC().logverbose("Changing inputdir to %s." % (inputdir))
            xenrt.TEC().setInputDir(inputdir)

        t = xenrt.TEC().registry.hostGet(target)
        if not t:
            raise xenrt.XRTError("Unable to find target host %s in registry" %
                                 (target))
        self.getLogsFrom(t)

        gip = xenrt.TEC().lookup("GUI_DEBUG_GUEST", None)
        if gip:
            # For debug purposes, use an existing VM
            guest = xenrt.GenericGuest(gip)
            guest.mainip = gip
            guest.windows = True
        else:
            # Install a VM to test
            template = xenrt.lib.xenserver.getTemplate(host, distro)
            guest = host.guestFactory()(xenrt.randomGuestName(), template)
            self.guestsToClean.append(guest)
            guest.setMemory(512)
            guest.install(host,
                          isoname=xenrt.DEFAULT,
                          distro=distro,
                          rootdisk=rootdisk)
            guest.installDrivers()

        self.getLogsFrom(guest)
        guest.installCarbonWindowsGUI()

        # Find where we installed the thing
        x = guest.findCarbonWindowsGUI()
        if not x:
            raise xenrt.XRTError("Could not find the installed GUI")
        xenadmindir, xenadminexe = x

        # Create a directory for the UI to write extra logs and screenshots to
        ld = self.remoteLoggingDirectory(guest)

        # Make sure c:\TEMP directory exists for the VM export test
        try:
            guest.xmlrpcExec("mkdir c:\\temp")
        except:
            pass

        # Determine the clock skew between the guest and the controller (if any)
        # so we can correlate logs accurately
        xenrt.TEC().logverbose("Clock skew is %s seconds (positive value means "
                               "guest clock is fast)" % (guest.getClockSkew()))

        # Run the tests
        outcome = None
        try:
            guest.xmlrpcExec("cd %s\n"
                             "%s runtests host=\"%s\" password=%s \"log_directory=%s\" --wait" %
                             (xenadmindir,
                              xenadminexe,
                              t.getIP(),
                              t.password,
                              ld),
                             timeout=7200)
        except Exception, e:
            outcome = e

        # Copy the logs back
        xmlfile = "%s/UITestResults.xml" % (xenrt.TEC().getLogdir())
        try:
            data = guest.xmlrpcReadFile("%s\\UITestResults.xml" %
                                        (xenadmindir))

            f = file(xmlfile, "w")
            f.write(data)
            f.close()
        except Exception, e:
            if not outcome:
                outcome = e

        try:
            data = guest.xmlrpcReadFile("%s\\crashdump.txt" % (xenadmindir))
            f = file("%s/crashdump.txt" % (xenrt.TEC().getLogdir()), "w")
            f.write(data)
            f.close()
            self.tec.warning("Crashdump file found")
        except:
            pass

        fatal = False
        try:
            for lf in string.split(xenrt.TEC().lookup("XENCENTER_LOG_FILE"),
                                   ";"):
                if guest.xmlrpcFileExists(lf):
                    guest.xmlrpcGetFile(lf,
                                        "%s/XenCenter.log" %
                                        (xenrt.TEC().getLogdir()))

            # Review XenCenter.log for bad entries
            f = file("%s/XenCenter.log" % (xenrt.TEC().getLogdir()), "r")
            data = f.read()
            f.close()

            lines = data.split("\n")
            lnum = 1
            for line in lines:
                for b in self.badentries:
                    if line.count(b) > 0:
                        if b in self.fatalentries:
                            fatal = True
                        if not line in guest.thingsWeHaveReported:
                            guest.thingsWeHaveReported.append(line)
                            xenrt.TEC().warning("\"%s\" found in XenCenter.log "
                                                "on line %u" % (b,lnum))
                lnum += 1

        except:
            pass

        # Parse the XML results file
        if not os.path.exists(xmlfile):
            if not outcome:
                outcome = xenrt.XRTFailure(
                    "No results file was returned (%s)" % (xmlfile))
        else:
            xenrt.TEC().logverbose("About to parse results file")
            try:
                self.readResults(xmlfile)
            except Exception, e:
                # We had a problem parsing the file, did we have a fatal error
                if fatal:
                    raise xenrt.XRTFailure("Fatal error in XenCenter.log")
                else:
                    raise e

        # Check the health of the dom0
        xenrt.TEC().logverbose("Checking dom0 health")
        host.checkHealth()
        xenrt.TEC().logverbose("Done")

        if outcome:
            raise outcome

    def postRun(self):
        for g in self.guestsToClean:
            try:
                g.shutdown(force=True)
            except:
                pass
            g.poll("DOWN", 120, level=xenrt.RC_ERROR)
            g.uninstall()
            time.sleep(15)


class _UnitTestMechanism(object):
    """
    Abstract base class for running a set of SDK unit tests in a VM
    """
    __metaclass__ = ABCMeta
    TARGET_ROOT = ""
    RESULT_FILE_NAME = "test_results.out"
    SDK_OVERRIDE = "SDK_BUILD_LOCATION"

    def __init__(self, host, targetGuest):
        self._host = host
        self._runner = targetGuest

    def __get_sdk_location(self):
        """
        Look for the SDK location in a named flag otherwise provide the default
        """
        log("Look for override in %s" % self.SDK_OVERRIDE)
        try:
            location = xenrt.TEC().lookup(self.SDK_OVERRIDE)
            log("Found override.....")
            return location
        except:
            return "xe-phase-2/%s" % self._packageName

    def _getSdk(self):
        self.removePackage()
        step("Getting SDK....")
        target = self.__get_sdk_location()
        sdkfile = xenrt.TEC().getFile(target)
        sftp = self._runner.sftpClient()
        targetLocation = os.path.join(self.TARGET_ROOT, self._packageName)
        sftp.copyTo(sdkfile, targetLocation)
        log("Target location: %s" % targetLocation)
        sftp.close()
        return targetLocation

    def removePackage(self):
        log("Removing SDK....")
        self._runner.execguest( "rm -rf %s*" % self._packageName.split('.')[0])

    def writeResultsFile(self):
        if not self.results:
            raise xenrt.XRTFailure("An omnishambles has occured - no results to report")
        file("%s/%s" % (xenrt.TEC().getLogdir(), self.RESULT_FILE_NAME), "w").write(self.results)
        log("Output file written: %s" % self.RESULT_FILE_NAME)

    @abstractproperty
    def _packageName(self):
        pass

    @abstractproperty
    def _srcPath(self):
        pass

    @abstractproperty
    def results(self):
        pass

    @abstractmethod
    def installDependencies(self):
        pass

    @abstractmethod
    def installSdk(self):
        pass

    @abstractmethod
    def buildTests(self):
        pass

    @abstractmethod
    def runTests(self):
        pass

    @abstractmethod
    def triageTestOutput(self):
        pass


class JavaUnitTestMechanism(_UnitTestMechanism):

    __ZIP_DEP_PATH = "XenServer-SDK/XenServerJava/bin"
    __TEST_CODE_PATH = "XenServer-SDK/XenServerJava/samples"
    __TEST_RUNNER = "RunTests"
    __ERRORS = ["Exception in", "<state>Fail"]
    __BUILD_LOG = "make.log"

    def __init__(self, host, runner):
        self.__results = None
        super(JavaUnitTestMechanism, self).__init__(host, runner)

    @property
    def _packageName(self):
        return "XenServer-SDK.zip"

    @property
    def _srcPath(self):
        return "XenServer-SDK/XenServerJava/src"

    @property
    def results(self):
        return self.__results

    def installDependencies(self):
        deps = ["unzip", "default-jdk"]
        [self._runner.execguest("sudo apt-get -y install %s" % p) for p in deps]

    def installSdk(self):
        sdkLocation = self._getSdk()
        self._runner.execguest("unzip %s" % sdkLocation)
        self._runner.execguest("cp %s/*.jar %s" %(self.__ZIP_DEP_PATH, self._srcPath))
        return os.path.join(self.TARGET_ROOT, sdkLocation)

    def __writeMakeLog(self, message):
        log("Make output in: %s" % self.__BUILD_LOG)
        file("%s/%s" % (xenrt.TEC().getLogdir(), self.__BUILD_LOG), "w").write(message)

    def buildTests(self):
        self._runner.execguest("cp %s/*.java %s" %(self.__TEST_CODE_PATH, self._srcPath))
        self._runner.execguest("cd %s && make clean" % self._srcPath)

        try:
            self.__writeMakeLog(self._runner.execguest("cd %s && make" % self._srcPath))
        except xenrt.XRTFailure, e:
            self.__writeMakeLog(e.data)
            raise

    def runTests(self):
        try:
            self.__results = self._runner.execguest("cd %s && java -cp .:*: %s %s root xenroot" % (self._srcPath, self.__TEST_RUNNER, str(self._host.getIP())))
        except xenrt.XRTFailure, e:
            log("Running the tests has failed - caputuring the errors for later triage")
            self.__results = str(e.data)

    def triageTestOutput(self):
        for e in self.__ERRORS:
            if re.search(e, self.__results):
                log("Found error indicator %s" % e)
                raise xenrt.XRTFailure("An error was found while triaging the output")


class _SDKUnitTestCase(xenrt.TestCase, object):
    __metaclass__ = ABCMeta
    __RUNNER_VM = "runner_vm"

    def __vmName(self, arglist):
        for (a, v) in [x.split('=') for x in arglist]:
            if a == self.__RUNNER_VM:
                return v
        raise xenrt.XRTFailure("Failure parsing args")

    @abstractmethod
    def _createMechanism(self, host, runner):
        pass

    def run(self, arglist):
        host = self.getDefaultHost()
        runner = self.getGuest(self.__vmName(arglist))
        log("Host %s and Runner %s" % (host, runner))

        installer = self._createMechanism(host, runner)
        step("Install dependencies....")
        installer.installDependencies()
        step("Install SDK....")
        installer.installSdk()
        step("Build tests....")
        installer.buildTests()
        step("Run tests....")
        installer.runTests()
        step("Write results file...")
        installer.writeResultsFile()
        step("Triage output....")
        installer.triageTestOutput()
        step("Tidy up ....")
        installer.removePackage()


class TCJavaSDKUnitTests(_SDKUnitTestCase):
    def _createMechanism(self, host, runner):
        return JavaUnitTestMechanism(host, runner)


class CUnitTestMechanism(_UnitTestMechanism):
    __TEST_CODE_PATH = "XenServer-SDK/libxenserver/src/test"
    __TEST_RUNNER = "test_vm_ops"
    __TEST_RECORDS = "test_get_records"
    __BADNESS = ["Error", "Segmentation fault", "FAULT", "command not found", "No such file"]

    def __init__(self, host, runner):
        self.__results = {}
        self.__currentTest = ""
        self.__vmCount = len(host.listGuests())
        log("Initially there are %d VMs" % self.__vmCount)
        super(CUnitTestMechanism, self).__init__(host, runner)

    @property
    def _packageName(self):
        return "XenServer-SDK.zip"

    @property
    def _srcPath(self):
        return "XenServer-SDK/libxenserver/src"

    @property
    def results(self):
        return str(self.__results)

    def installSdk(self):
        sdkLocation = self._getSdk()
        log(self._runner.execguest("unzip %s" % sdkLocation))
        return os.path.join(self.TARGET_ROOT, sdkLocation)

    def installDependencies(self):
        deps = ["libxml2-dev", "libcurl3-dev", "unzip"]
        [self._runner.execguest("sudo apt-get -y install %s" % p) for p in deps]

    def buildTests(self):
        self._runner.execguest("cd %s && make clean" % self._srcPath)
        self._runner.execguest("cd %s && make" % self._srcPath)

    def __runVmOps(self, localSrName):
        self.__currentTest = self.__TEST_RUNNER
        return self._runner.execguest("cd %s && ./%s https://%s \'%s\' root xenroot" % (self.__TEST_CODE_PATH, self.__currentTest, self._host.getIP(), localSrName))

    def __runGetRecords(self):
        self.__currentTest = self.__TEST_RECORDS
        return self._runner.execguest("cd %s && ./%s https://%s root xenroot" % (self.__TEST_CODE_PATH, self.__currentTest, self._host.getIP()))

    def runTests(self):
        localSrName = next(sr for sr in self._host.xapiObject.localSRs if sr.isLocal).name
        try:
            self.__results[self.__currentTest] = self.__runVmOps(localSrName)
            self.__results[self.__currentTest] = self.__runGetRecords()
        except xenrt.XRTFailure, e:
            log("Test failed: %s" % e)
            self.__results[self.__currentTest]=(e.data)

    def triageTestOutput(self):
        for bad in self.__BADNESS:
            if bad in self.results:
                log("Found the horror: %s in the output" %bad)
                raise xenrt.XRTFailure("A failure message was found in the output")

        if self.__vmCount + 1 != len(self._host.listGuests()):
            raise xenrt.XRTFailure("Unexpected guest count: expecting 1 VM more than the test started with")


class TCCSDKUnitTests(_SDKUnitTestCase):
    def _createMechanism(self, host, runner):
        return CUnitTestMechanism(host, runner)


class _PowerShellSnapTest(xenrt.TestCase):
    """Run the XenServer PowerShell Snap-In Tests."""

    DISTRO = None
    SNAPIN_DIR_NAME = "XenServerPSSnapIn"
    __MODULE_PATH = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\Modules\\XenServerPSModule"
    __DUNDEE_CORE_TEST = "AutomatedTestCore.ps1"
    __POWERSHELL_EXE = "C:\\Windows\\system32\\WindowsPowerShell\\v1.0\\powershell.exe"
    __MSI_PATH_64 = "c:\\progra~2\\citrix\\xenserverpssnapin"
    __MSI_PATH_32 = "c:\\progra~1\\citrix\\xenserverpssnapin"
    
    
            
    def prepare(self, arglist):
        self.nfs = None
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericWindowsGuest(distro=self.DISTRO)
        self.uninstallOnCleanup(self.guest)
        self.getLogsFrom(self.guest)
        
        packageName = xenrt.TEC().lookup("POWERSHELL_VERSION") 
        self.guest.getInstance().os.ensurePackageInstalled(packageName)
        
        
        self.guest.waitforxmlrpc(600)
        self.guest.installPowerShellSnapIn(snapInDirName=self.SNAPIN_DIR_NAME)
        self.guest.enablePowerShellUnrestricted()

        # Install the host's certificate on the Windows client VM to
        # avoid the interactive prompt for a self-signed cert.
        der_file = self.host.hostTempFile()
        self.host.execdom0("openssl x509 -outform DER -in /etc/xensource/xapi-ssl.pem > %s" % (der_file))
        der_file_tmp = xenrt.TEC().tempFile()
        sftp = self.host.sftpClient()
        try:
            sftp.copyFrom(der_file, der_file_tmp)
        finally:
            sftp.close()
        der_file_win = "%s\\hostcert.der" % (self.guest.xmlrpcTempDir())
        self.guest.xmlrpcSendFile(\
                    "%s/distutils/certmgr.exe" %
                    (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")),
                    "c:\\certmgr.exe")
        self.guest.xmlrpcSendFile(der_file_tmp, der_file_win)
        self.guest.xmlrpcExec("c:\\certmgr.exe /add %s "
                              "/s /r localmachine root" % (der_file_win))
        self.host.execdom0("rm -f %s" % (der_file))

    def __selectPath(self):
        if isinstance(self.guest, xenrt.lib.xenserver.guest.ClearwaterGuest):
            return self.__MODULE_PATH
        if self.guest.xmlrpcGetArch() == "amd64":
            return self.__MSI_PATH_64
        else:
            return self.__MSI_PATH_32

    def __runTestScript(self):
        nfshost, nfspath = self.nfs.getMount().split(":")
        pathpref = self.__selectPath()

        if isinstance(self.guest, xenrt.lib.xenserver.guest.ClearwaterGuest):
            testScript = self.__DUNDEE_CORE_TEST
            testScriptIncPath = self.__MODULE_PATH + "\\" + testScript
            resultFileName = "C:\\" + testScript.split('.')[0] + "_results.xml"
            self.guest.xmlrpcExec("cd %s" % pathpref)
            test = "%s %s %s %s %s %s %s" % (testScriptIncPath,
                                              resultFileName,
                                              self.host.getIP(), "root",
                                              self.host.password, nfshost,
                                              nfspath)
            self.guest.xmlrpcExec("%s -command \"Import-Module XenServerPSModule; %s\"" %(self.__POWERSHELL_EXE, test),
                                  timeout=900)
            return resultFileName
        else:
            # xenserverpssnapin.bat uses the -Noexit so it hangs around
            # after the tests complete (CA-27268 related). Remove this.
            batfile = "%s\\xenserverpssnapin.bat" % (self.__selectPath())
            data = self.guest.xmlrpcReadFile(batfile)
            pat = re.compile(r'(^.*?)(?=C:.*$)', flags=re.IGNORECASE|re.MULTILINE)
            data = pat.sub("", data, count=1)
            if "-Noexit" in data:
                xenrt.TEC().logverbose("Removing -Noexit from XSPS batch script")
                data = data.replace("-Noexit", "")
            self.guest.xmlrpcWriteFile(batfile, data)
            self.guest.xmlrpcExec("cd %s\n"
                          ".\\xenserverpssnapin.bat "
                          "\"%s\\automatedtestcore.ps1\" "
                          "c:\\result.xml %s %s %s %s %s" %
                          (pathpref, pathpref, self.host.getIP(), "root",
                           self.host.password, nfshost, nfspath), timeout=1800)
            return "c:\\result.xml"

    def run(self, arglist):
        self.nfs = xenrt.ExternalNFSShare()
        resultName = None

        try:
            resultName = self.__runTestScript()
        finally:
            if not resultName:
                raise xenrt.XRTFailure("Could not get the result files from the powershell tests")

            xenrt.TEC().logverbose("Reading file %s...." % resultName)
            result = self.guest.xmlrpcReadFile(resultName)
            resultFile = resultName.split('\\')[-1]
            file("%s/%s" % (xenrt.TEC().getLogdir(), resultFile), "w").write(result)
            try:
                self.parseResults(result)
            except:
                raise xenrt.XRTError("Error parsing XML results file.")
            for x in self.myresults:
                if x["state"] == "Fail":
                    raise xenrt.XRTFailure("One or more subcases failed.")

    def postRun(self):
        try: self.guest.shutdown()
        except: pass
        try: self.guest.uninstall()
        except: pass
        if self.nfs:
            try:
                self.nfs.release()
            except:
                pass

    def handleTestNode(self, test):
        outcome = {}
        for x in test.childNodes:
            if x.nodeName == "name":
                for y in x.childNodes:
                    if y.nodeName == "#text":
                        outcome["name"] = y.data
            elif x.nodeName == "state":
                for y in x.childNodes:
                    if y.nodeName == "#text":
                        outcome["state"] = y.data
            elif x.nodeName == "log":
                for y in x.childNodes:
                    if y.nodeName == "#text":
                        outcome["log"] = y.data
        if outcome["state"] == "Fail":
            xenrt.TEC().reason("Subcase failed: %s %s" %
                               (outcome["name"], outcome["log"]))
        self.myresults.append(outcome)

    def parseResults(self, xmldata):
        self.myresults = []
        xmltree = xml.dom.minidom.parseString(xmldata)
        for x in xmltree.childNodes:
            if x.nodeName == "results":
                for y in x.childNodes:
                    if y.nodeName == "group":
                        for z in y.childNodes:
                            if z.nodeName == "test":
                                self.handleTestNode(z)


class TC8300(_PowerShellSnapTest):
    """PowerShell Snap-In test on Windows Server 2003 EE SP2"""

    DISTRO = "w2k3eesp2"


class TC8301(_PowerShellSnapTest):
    """PowerShell Snap-In test on Windows Server 2003 EE SP2 x64"""

    DISTRO = "w2k3eesp2-x64"


class TC8302(_PowerShellSnapTest):
    """PowerShell Snap-In test on Windows XP SP3"""

    DISTRO = "winxpsp3"


class TC8303(_PowerShellSnapTest):
    """PowerShell Snap-In test on Windows Vista EE SP1"""

    DISTRO = "vistaeesp1"


class TC17780(_PowerShellSnapTest):
    """PowerShell Snap-In test on Windows Vista EE SP2"""

    DISTRO = "vistaeesp2"


class TC8304(_PowerShellSnapTest):
    """PowerShell Snap-In test on Windows Server 2008 32 bit"""

    DISTRO = "ws08sp2-x86"


class TC8305(_PowerShellSnapTest):
    """PowerShell Snap-In test on Windows Server 2008 64 bit"""

    DISTRO = "ws08sp2-x64"


class TC19252(_PowerShellSnapTest):
    """PowerShell Snap-In test on Windows Server 2012 64 bit"""

    DISTRO = "ws12-x64"
        
    
class TC19253(_PowerShellSnapTest):
    """PowerShell Snap-In test on Windows 7 32 bit"""

    DISTRO = "win7sp1-x86"
        
    
class TC19254(_PowerShellSnapTest):
    """PowerShell Snap-In test on Windows 7 64 bit"""

    DISTRO = "win7sp1-x64"
        
    
class TC19255(_PowerShellSnapTest):
    """PowerShell Snap-In test on Windows 8 32 bit"""

    DISTRO = "win81-x86"
    

class TC19256(_PowerShellSnapTest):
    """PowerShell Snap-In test on Windows 8 64 bit"""

    DISTRO = "win81-x64"
    

class TC19261(_PowerShellSnapTest):
    """Old PowerShell Snap-In test on Windows Server 2003 EE SP2"""

    DISTRO = "w2k3eesp2"
    SNAPIN_DIR_NAME = "XenServerPSSnapIn_old"


class TC19266(_PowerShellSnapTest):
    """Old PowerShell Snap-In test on Windows Server 2003 EE SP2 x64"""

    DISTRO = "w2k3eesp2-x64"
    SNAPIN_DIR_NAME = "XenServerPSSnapIn_old"


class TC19257(_PowerShellSnapTest):
    """Old PowerShell Snap-In test on Windows XP SP3"""

    DISTRO = "winxpsp3"
    SNAPIN_DIR_NAME = "XenServerPSSnapIn_old"


class TC19260(_PowerShellSnapTest):
    """Old PowerShell Snap-In test on Windows Vista EE SP2"""

    DISTRO = "vistaeesp2"
    SNAPIN_DIR_NAME = "XenServerPSSnapIn_old"


class TC19265(_PowerShellSnapTest):
    """Old PowerShell Snap-In test on Windows Server 2008 32 bit"""

    DISTRO = "ws08sp2-x86"
    SNAPIN_DIR_NAME = "XenServerPSSnapIn_old"


class TC19267(_PowerShellSnapTest):
    """Old PowerShell Snap-In test on Windows Server 2008 64 bit"""

    DISTRO = "ws08sp2-x64"
    SNAPIN_DIR_NAME = "XenServerPSSnapIn_old"


class TC19262(_PowerShellSnapTest):
    """Old PowerShell Snap-In test on Windows Server 2012 64 bit"""

    DISTRO = "ws12-x64"
    SNAPIN_DIR_NAME = "XenServerPSSnapIn_old"


class TC19258(_PowerShellSnapTest):
    """Old PowerShell Snap-In test on Windows 7 32 bit"""

    DISTRO = "win7sp1-x86"
    SNAPIN_DIR_NAME = "XenServerPSSnapIn_old"


class TC19263(_PowerShellSnapTest):
    """Old PowerShell Snap-In test on Windows 7 64 bit"""

    DISTRO = "win7sp1-x64"
    SNAPIN_DIR_NAME = "XenServerPSSnapIn_old"


class TC19259(_PowerShellSnapTest):
    """Old PowerShell Snap-In test on Windows 8 32 bit"""

    DISTRO = "win8-x86"
    SNAPIN_DIR_NAME = "XenServerPSSnapIn_old"


class TC19264(_PowerShellSnapTest):
    """Old PowerShell Snap-In test on Windows 8 64 bit"""

    DISTRO = "win8-x64"
    SNAPIN_DIR_NAME = "XenServerPSSnapIn_old"
