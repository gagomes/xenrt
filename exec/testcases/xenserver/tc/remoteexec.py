from xenrt.lib.xenserver.call import APICall
from xenrt import step, log, warning
from random import sample, choice
import xenrt
import re

class TCRemoteCommandExecBase(xenrt.TestCase):
    """Base class of all Remote Command Execution API for CLM"""

    PLUGIN = "guest-agent-operation"
    PLUGIN_FUNC = "run-script"

    # on first (with xenstore) implementation, username and password are required but
    # not being used. Any valid string is okay.
    GUEST_USER = "xxx"
    GUEST_PWD = "xxx"

    TARGET = ["win7x86", "win7x64", "ws2008r2", "win8x86", "win8x64", "win81x86", "win81x64", "ws12x64", "ws12r2x64"]
    USE_TARGET = 0
    COMMAND_INTERVAL = 11

    LEAVE_DEFAULT = False
    POOL_OPTION = "allow_guest_agent_run_script"

    def _getSession(self, guest, username=None, password=None):
        """
        Create a session for APICall)
        """
        return guest.host.pool.master.getAPISession(secure=False, username=username,
            password=password, local=True)

    def _getGuestRef(self, session, guest):
        """
        Find Guest reference to run plugin call.

        @param session: Session to run API
        @param guest: Guest instance to find ref.

        @return: guest reference.
        """
        for gref in session.xenapi.VM.get_all():
            if session.xenapi.VM.get_uuid(gref) == guest.getUUID():
                return gref

        raise xenrt.XRTError("Cannot find the guest ref of guest %s(%s)" %
            (guest.getName(), guest.getUUID()))

    def _getHostRef(self, session, host):
        """
        Find host ref to run plugin call.

        @param session: Session to run API
        @param host: Host object to find ref.

        @return host ref for API call.
        """
        for hostref in session.xenapi.host.get_all():
            if session.xenapi.host.get_uuid(hostref) == host.getUUID():
                return hostref

        raise xenrt.XRTError("Cannot find host ref of host %s(%s)" % (host.getName(), host.getUUID()))

    def executeCommandCLI(self, guest, script, forcewrap=False, username=None, password=None):
        """Executing script(batch file) from guest using
        Remote command execution API for CLM

        @param guest: Guest object that to run command.
        @param script: Content of script to run.
        @param forcewrap: When true, script is saved in a text file and called via $(cat ~)
        @param username: RBAC username, root/admin by default.
        @param password: password for username

        @return: Dict of return value of exitcode, stdout and stderr.
        """

        host = guest.host
        if guest.host.pool:
            host = guest.host.pool.master

        # shell scripts parser needs to escaped.
        script = script.replace("\\", "\\\\")
        if forcewrap:
            # Get the host. Use master if VM is in the pool.
            path = host.execdom0("mktemp").strip()
            for line in script.split("\n"):
                host.execdom0("echo \"%s\" >> %s" % (line.strip(), path))
            script = "$(cat %s)" % (path)

        rbac = ""
        if username and password:
            rbac = "-u \"%s\" -pw \"%s\"" % (username, password)

        param = "args:username=\"%s\" args:password=\"%s\" args:script=\"%s\"" % \
            (self.GUEST_USER, self.GUEST_PWD, script)

        log("Executing script...")
        cmd = "xe vm-call-plugin %s vm-uuid=%s plugin=guest-agent-operation fn=run-script %s" % \
            (rbac, guest.getUUID(), param)
        ret = host.execdom0(cmd)
        log("Output: %s" % ret)
        status = eval(ret)

        if forcewrap:
            host.execdom0("rm -f %s" % (path))

        return status

    def executeCommandAPI(self, guest, script, username=None, password=None):
        """Executing script(batch file) from guest using
        Remote command execution API for CLM

        @param guest: Guest object that to run command.
        @param script: Content of script to run.
        @param username: RBAC username, root/admin by default.
        @param password: password for username

        @return: Dict of return value of exitcode, stdout and stderr.
        """

        log("Prepare APICall")
        session = self._getSession(guest, username, password)
        guestRef = self._getGuestRef(session, guest)
        param = {"script": script, "username": self.GUEST_USER, "password": self.GUEST_PWD}

        log("Executing script...")
        ret = session.xenapi.VM.call_plugin(guestRef, self.PLUGIN, self.PLUGIN_FUNC, param)
        log("Output: %s" % ret)
        status = eval(ret)

        return status

    def __parseAsyncOutput(self, output):
        """
        Asynchronous call have different format of return value.

        @param result: output from Asynchronous call.

        @return: parsed and modified result.
        """

        group = re.match("<value>(.*)</value>", output)
        if not group:
            return ""

        result = group.groups()[0]

        #HTML escaping handler.
        result = result.replace("&lt;", "<")
        result = result.replace("&gt;", ">")
        result = result.replace("&nbsp;", " ")
        result = result.replace("&brvbar;", "|")
        result = result.replace("&quot;", "\"")
        # This should be the last among HTML escape
        result = result.replace("&amp;", "&")

        # shell escaping handler.
        result = result.replace("\\/", "/")
        # This should be the last among shell escape
        result = result.replace("\\\\", "\\")

        return result

    def executeCommandAPIAsync(self, guest, script, timeout=60, username=None, password=None):
        """Executing script(batch file) from guest using
        Remote command execution API for CLM

        @param guest: Guest object that to run command.
        @param script: Content of script to run.
        @param timeout: Time out for checking status of execution.
        @param username: RBAC username, root/admin by default.
        @param password: password for username

        @return: Dict of return value of exitcode, stdout and stderr.
        """

        log("Prepare APICall")
        session = self._getSession(guest, username, password)
        guestRef = self._getGuestRef(session, guest)
        session = self._getSession(guest)
        param = {"script": script, "username": self.GUEST_USER, "password": self.GUEST_PWD}

        log("Executing script...")
        task = session.xenapi.Async.VM.call_plugin(guestRef, self.PLUGIN, self.PLUGIN_FUNC, param)

        if timeout == 0:
            return task

        start = xenrt.util.timenow()
        while xenrt.util.timenow() < start + timeout:
            status = session.xenapi.task.get_status(task)
            if status == "success":
                log("%s has finished" % task)
                result = session.xenapi.task.get_result(task)
                break
            elif status == "failure":
                #The task has failed, and the error should be propogated upwards.
                raise Exception("Async call failed with error: %s" % session.xenapi.task.get_error_info(task))
            else:
                log("Task Status: %s" % status)

            if start + timeout <= xenrt.util.timenow():
                raise xenrt.XRTError("task %d has failed to finish in %d time." % (task, timeout))

            xenrt.sleep(2)

        log("Output: %s" % result)
        result = self.__parseAsyncOutput(result)
        status = eval(result)

        return status

    def runCommand(self, guest, script, method="cli", timeout = 60):
        """ Run given commands

        @param guest: guest instance to run with.
        @param script: script to run
        @param timeout: timeout value for async call. Ignored in other calls.

        @return: dict from execution result.
        """

        log("Running command \"\"\"%s\"\"\" with %s" %
            (script, method))

        method = method.lower()
        if method == "cli":
            status = self.executeCommandCLI(guest, script)
        elif method == "api":
            status = self.executeCommandAPI(guest, script)
        elif method == "async":
            status = self.executeCommandAPIAsync(guest, script, timeout)
        else:
            raise xenrt.XRTError("Unknown running method: %s" % method)

        log("Result: %s" % status)

        return status

    def createGuest(self, distro):
        """Create a Guest with given distro and add it to self.guests"""

        guest = self.host.createBasicGuest(distro)
        guest.preCloneTailor()
        guest.xenDesktopTailor()
        guest.shutdown()
        guest.removeCD()
        self.guests.append(guest)

    def isRemoteExecEnabled(self):
        """Check Remote Command Execution API is enabled on pool."""

        host = self.getDefaultHost()
        pool = self.getDefaultPool()

        ret = False
        try:
            rest = host.genParamGet("pool", pool.getUUID(), "other-config", self.POOL_OPTION)
            if rest == "true":
                ret = True
        except:
            pass

        return ret

    def __setRemoteExecAPI(self, val):
        """Set Remote Command Execution API enable/disable """
        host = self.getDefaultHost()
        for pool in host.minimalList("pool-list"):
            host.genParamSet("pool", pool, "other-config", val, self.POOL_OPTION)

    def enableRemoteExecAPI(self):
        """Enable Remote Command Execution API on main (default) pool"""
        self.__setRemoteExecAPI("true")

    def disableRemoteExecAPI(self):
        """Enable Remote Command Execution API on main (default) pool"""
        self.__setRemoteExecAPI("false")

    def enableRemoteExecFromGuest(self, guest):
        """Enable calls by modifying Registry of given guest."""
        guest.winRegDel("HKLM", "Software\\Citrix\\Xentools", "NoRemoteExecution")

    def disableRemoteExecFromGuest(self, guest):
        """Disable calls by modifying Registry of given guest."""
        guest.winRegAdd("HKLM", "Software\\Citrix\\Xentools", "NoRemoteExecution", "DWORD", 1)

    def runCase(self, func):
        """
        Utility function to run jobs simutanously.

        @param func: a refrence to member function that accept a guest as a param
        """

        # Use sub case to run command on all guest simultanously.
        tasks = []
        for guest in self.guests:
            tasks.append(xenrt.PTask(func, guest))
        xenrt.pfarm(tasks)
        for task in tasks:
            if task.exception:
                log("Sub task (%s with %s) has exception: %s" % \
                    (task.func.__name__, task.args[0].getName(), task.exception))

    def prepare(self, arglist=[]):
        args = self.parseArgsKeyValue(arglist)
        self.host = self.getDefaultHost()

        self.guests = []
        if "masters" in args:
            log("%s guests are declared." % args["masters"])
            if self.USE_TARGET > 0:
                log("Using %d guests for this TC." % self.USE_TARGET)
                targets = sample(args["masters"].split(","), self.USE_TARGET)
            else:
                targets = args["masters"].split(",")
            self.guests = [self.host.getGuest(name).cloneVM() for name in targets]
            log("Seleted Guests: %s" % targets)
        else:
            num = len(self.TARGET)
            targets = self.TARGET
            if self.USE_TARGET > 0:
                log("Using %d guests for this TC." % num)
                num = self.USE_TARGET
                targets = sample(self.TARGET, num)
                log("Seleted Distros: %s" % targets)
            log("Creating %d guests of %s distros." % (num, targets))
            tasks = [xenrt.PTask(self.createGuest, distro) for distro in targets]
            xenrt.pfarm(tasks)
            log("Created %s guests." % ([g.name for g in self.guests],))

        for g in self.guests:
            self.uninstallOnCleanup(g)
            g.setState("DOWN")
            g.setHost(choice(self.getDefaultPool().getHosts()))
            g.start()

        if not self.LEAVE_DEFAULT:
            self.enableRemoteExecAPI()

    def run(self, arglist=None):
        raise xenrt.XRTError("Not implemented.")


class TCEnabilityCheck(TCRemoteCommandExecBase):
    """Verify function can be disabled."""

    LEAVE_DEFAULT = True
    USE_TARGET = 2

    def verifyWorks(self, guest):
        """Execute a simple command on given guest and return whether it worked or not."""

        script = "dir"

        try:
            self.runCommand(guest, script)
        except:
            return False
        return True

    def run(self, arglist=None):
        host = self.getDefaultHost()
        guest = self.guests[0]

        # This only pass on fresh install.
        step("Check default value is set off")
        if self.isRemoteExecEnabled():
            raise xenrt.XRTFailure("Feature is on by default.")

        step("Try run command while feature is disabled.")
        if self.verifyWorks(guest):
            raise xenrt.XRTFailure("Guest executed command while %s is disabled." % self.POOL_OPTION)
        xenrt.sleep(self.COMMAND_INTERVAL)

        step("Turn it on and check feature works.")
        self.enableRemoteExecAPI()
        if not self.verifyWorks(guest):
            raise xenrt.XRTFailure("Feature did not work after %s is enabled." % self.POOL_OPTION)
        xenrt.sleep(self.COMMAND_INTERVAL)

        step("Check guest level configuration.")
        self.disableRemoteExecFromGuest(guest)
        if self.verifyWorks(guest):
            raise xenrt.XRTFailure("Guest executed command while registry is set.")
        if not self.verifyWorks(self.guests[1]):
            raise xenrt.XRTFailure("Guest failed to execute command while registry is NOT set and %s is enabled." % \
                (self.POOL_OPTION))
        xenrt.sleep(self.COMMAND_INTERVAL)
        self.enableRemoteExecFromGuest(guest)
        if not self.verifyWorks(guest):
            raise xenrt.XRTFailure("Guest failed to execute command while after registry key is removed.")


class TCBasicFunc(TCRemoteCommandExecBase):
    """Verify basic functionality."""

    METHOD = "cli"

    def checkLoggedOnHost(self, guest, script):
        """Verify xensource log has information of calls."""

        args = {}
        host = guest.host.pool.master
        # Checking last command.
        if self.METHOD == "cli":
            log = host.execdom0("grep 'xe vm-call-plugin vm-uuid=%s plugin=guest-agent-operation " \
                "fn=run-script' /var/log/xensource.log" % guest.getUUID()).splitlines()[-1]
            for tkn in log.split("args:")[1:]:
                tkn = tkn.strip()
                key, val = tkn.split("=", 1)
                args[key] = val
        else:
            log = host.execdom0("grep \"VM.call_plugin: VM = '%s (%s)'; plugin = 'guest-agent-operation'; " \
                "fn = 'run-script'\" /var/log/xensource.log" % (guest.getUUID(), guest.getName())).splitlines()[-1]
            for tkn in log.split("args:")[1:]:
                tkn = tkn.strip()
                key, val = tkn.split("=", 1)
                args[key.strip()] = val.strip()

        if "username" not in args:
            raise xenrt.XRTFailure("username is not logged in host xensource.log.")
        if "password" not in args:
            raise xenrt.XRTFailure("password is not logged in host xensource.log.")
        if "omitted" not in args["password"]:
            raise xenrt.XRTFailure("password is not omitted in host xensource.log.")
        if "script" not in args:
            raise xenrt.XRTFailure("script is not logged in host xensource.log")
        if script not in args["script"]:
            raise xenrt.XRTFailure("script is not properly logged in host xensource.log")

    def checkLoggedOnGuest(self, guest, script):
        """Verify guest event viewer has the log."""

        # Todo: checking guest eventlog when it is alive.
        # Using eventquery.vbs or GenericPlace.getWindowsEventLogs
        pass

    def verifyBasicFuncPosCase(self, guest):

        script = """dir C:\\"""

        status = self.runCommand(guest, script, self.METHOD)

        if status["rc"] != 0:
            raise xenrt.XRTFailure("Simple command did not run properly.")
        if not "stdout" in status or not len(status["stdout"]):
            raise xenrt.XRTFailure("Valid command did not produce stdout.")

        self.checkLoggedOnHost(guest, script)
        self.checkLoggedOnGuest(guest, script)

    def verifyBasicFuncNegCase(self, guest):

        script = """wrong command"""

        status = self.runCommand(guest, script, self.METHOD)

        if status["rc"] == 0:
            raise xenrt.XRTFailure("Expected error but command ran successfully.")
        if not "stderr" in status or not len(status["stderr"]):
            raise xenrt.XRTFailure("Wrong command did not produce stderr.")

        self.checkLoggedOnHost(guest, script)
        self.checkLoggedOnGuest(guest, script)

    def verifyBasicFuncEmptyCommand(self, guest):

        script = ""

        status = self.runCommand(guest, script, self.METHOD)

        if status["rc"] != 0:
            raise xenrt.XRTFailure("Empty command returned error.")
        if not "stdout" in status or len(status["stdout"]):
            raise xenrt.XRTFailure("Empty command have stdout.")
        if not "stderr" in status or len(status["stderr"]):
            raise xenrt.XRTFailure("Empty command have stderr.")

        self.checkLoggedOnHost(guest, script)
        self.checkLoggedOnGuest(guest, script)

    def run(self, arglist=[]):
        log("Running Basic functionality with %s method." % self.METHOD)

        step("Running valid command.")
        self.runSubcase("runCase", (self.verifyBasicFuncPosCase,), "Positive case", self.METHOD)
        xenrt.sleep(self.COMMAND_INTERVAL)

        step("Running invlaid command.")
        self.runSubcase("runCase", (self.verifyBasicFuncNegCase,), "Negative case", self.METHOD)
        xenrt.sleep(self.COMMAND_INTERVAL)

        step("Running empty command.")
        self.runSubcase("runCase", (self.verifyBasicFuncEmptyCommand,), "Empty command", self.METHOD)
        xenrt.sleep(self.COMMAND_INTERVAL)


class TCBasicFuncAPI(TCBasicFunc):
    """Verify basic functionality with XAPI call."""
    METHOD = "api"


class TCBasicFuncAPIAsync(TCBasicFunc):
    """Verify basic functionality with XAPI asynchronous call."""
    METHOD = "async"


class TCCLMCommand(TCRemoteCommandExecBase):
    """ """

    USE_TARGET = 2
    SCRIPT = """cmd /c exit /b 34
set dp=%%=ExitCodeAscii%%
cd c:/
echo function O1^(DownloadDest, LocalFile^) > sx.vbs
echo set O0=createobject^(^%%dp%%MSXML2.ServerXMLHTTP.3.0^%%dp%%^):O0.setOption 2,13056:O0.Open ^%%dp%%GET^%%dp%%, DownloadDest, false:O0.Send:set O2 = CreateObject^(^%%dp%%ADODB.Stream^%%dp%%^):O2.Type = 1:O2.Open:O2.Write O0.responseBody:O2.SaveToFile LocalFile >> sx.vbs
echo O2.Close:set O2 = Nothing:set O0=Nothing >> sx.vbs
echo End function >> sx.vbs
echo O1 ^%%dp%%https://cloudstore.scalextreme.com/swinstall/getscript/0i0q2dee52al^%%dp%%,^%%dp%%sxdr.vbs^%%dp%%:Dim O10:Set O10 = Wscript.CreateObject^(^%%dp%%WScript.Shell^%%dp%%^):O10.Run ^%%dp%%sxdr.vbs^%%dp%%:Set O10 = Nothing >> sx.vbs
cscript sx.vbs
rename sx.vbs sx.vbs.bak
del /f /q sx.lock
exit
"""

    def verifyCLMCommand(self, guest):
        """Verify CLM('ish) command works. This is primary use case."""
        status = self.executeCommandAPIAsync(guest, self.SCRIPT, timeout=120)

        if status["rc"] != 0:
            raise xenrt.XRTFailure("Failed to execute CLM command.")

        xenrt.sleep(300) # give some time to get agent installed.

        if not guest.xmlrpcFileExists("C:\\Program Files\\Citrix\\LifecycleManagement\\agent.cert") and \
            not guest.xmlrpcFileExists("C:\\Program Files (x86)\\Citrix\\LifecycleManagement\\agent.cert"):
            raise xenrt.XRTFailure("Failed to install CLM agent.")

    def run(self, arglist=None):

        self.runCase(self.verifyCLMCommand)


class TCGuestCompat(TCRemoteCommandExecBase):
    """Verify XAPI produces proper error message when the guest is not capable to run."""

    def prepare(self, arglist=[]):
        args = self.parseArgsKeyValue(arglist)
        self.host = self.getDefaultHost()

        self.guests = []
        if "guests" in args:
            log("%s guests are declared." % args["guests"])
            self.guests = [self.host.getGuest(name) for name in args["guests"].split(",")]
            log("Picked premade guests: %s" % ([g.getName() for g in self.guests],))
        else:
            log("Creating a Windows guest without PV driver and a Linux guest")
            self.guests.append(self.host.createGenericLinuxGuest("LinuxPV"))
            self.guests.append(self.host.createGenericWindowsGuest("WinNoPV", False))
            log("Created %s guests." % ([g.getName() for g in self.guests],))

        for g in self.guests:
            self.uninstallOnCleanup(g)
            g.setState("UP")

    def run(self, arglist=None):
        script = "dir"
        methods = ["cli", "async"]

        for guest in self.guests:
            for method in methods:
                try:
                    self.runCommand(guest, script, method)
                except:
                    pass
                else:
                    raise xenrt.XRTFailure("Succeeded to run a command using %s on %s." % (method, guest.getName()))


class TCCommandLength(TCRemoteCommandExecBase):
    """Verify command and output are truncated properly."""

    USE_TARGET = 1

    MAX_LEN_COMMAND = 1024
    MAX_LEN_STDOUT = 1024
    MAX_LEN_STDERR = 1024

    def verifyCommandLength(self, guest):
        cmd1024 = "echo 67890" + ("1234567890" * 101) + "1234" # 10 + (10 * 101) + 4
        cmd1025 = "echo 67890" + ("1234567890" * 101) + "12345" # # 10 + (10 * 101) + 5

        try:
            status = self.executeCommandCLI(guest, cmd1024, forcewrap=True)
        except:
            raise xenrt.XRTFailure("Failed to execute 1024 byte length command")

        xenrt.sleep(self.COMMAND_INTERVAL) 
        try:
            status = self.executeCommandCLI(guest, cmd1025, forcewrap=True)
        except:
            log("Failed to execute longer than 1024 bytes command as expected.")
        else:
            raise xenrt.XRTFailure("XAPI accepted to run longer than 1024 bytes command.")

    def verifyStdoutLength(self, guest):

        script = "dir /a C:\\WINDOWS"
        status = self.runCommand(guest, script)
        #if "(truncated)" not in status["stdout"]:
            #raise xenrt.XRTFailure("STDOUT is not truncated.")
        if len(status["stdout"].replace("\\\\", "\\").replace("\\/", "/")) > self.MAX_LEN_STDOUT + len(" (truncated)"):
            raise xenrt.XRTFailure("STDOUT is longer than %d." % self.MAX_LEN_STDOUT)

    def run(self, arglist=None):
        step("Check command length restricted to 1024 bytes")
        self.runCase(self.verifyCommandLength)

        xenrt.sleep(self.COMMAND_INTERVAL)

        step("Check stdout is truncated properly.")
        self.runCase(self.verifyStdoutLength)


class TCRateLimit(TCRemoteCommandExecBase):
    """Verify XAPI blocks according to RATE LIMIT"""

    USE_TARGET = 2

    def verifyRateLimited(self, guest):
        """Verify XAPI blocks guest running command in short time."""
        script = "dir"
        self.runCommand(guest, script)

        try:
            self.runCommand(guest, script)
        except:
            log("Execution failed as expected.")
        else:
            raise xenrt.XRTFailure("XAPI accept a call during rate limit cool-down.")

        # Just to verify.
        xenrt.sleep(self.COMMAND_INTERVAL)

        try:
            self.runCommand(guest, script)
        except:
            raise xenrt.XRTFailure("XAPI blocked a call after rate limit cool-down.")

    def run(self, arglist=None):
        self.runCase(self.verifyRateLimited)


class TCStressCommandBase(TCRemoteCommandExecBase):
    """A base class that is capable of running long/infinite command"""

    def runLongRunningCommand(self, guest, time=0, script=None):
        """ Running a time consuming task on guest.

        @param guest: Guest instance to run command.
        @param time: running time in second. 0 indicate indefinite.

        @return: task id of XAPI async call.
        """

        if not script:
            script = "ping citrite.net -t"
            if time > 0:
                script = "ping citrite.net -n %d" % ((time + 1),)

        log("Running command %s on %s." % ("indefinite time" if time == 0 else "for %d seconds" % (time,), guest.getName()))
        task = self.executeCommandAPIAsync(guest, script, timeout=0)

        return task

    def postRun(self):
        for guest in self.guests:
            guest.shutdown(force=True)
        xenrt.sleep(30)
        super(TCStressCommandBase, self).postRun()


class TCSingleCommand(TCStressCommandBase):
    """Verify only 1 command can be executed at a time."""

    USE_TARGET = 2

    def executeLongRunningCommand(self, guest):
        self.runLongRunningCommand(guest)
        xenrt.sleep(self.COMMAND_INTERVAL + 1)

    def verifyDualCommandProhibited(self, guest):
        """Check second command is not accepted when first one is running."""

        try:
            self.runCommand(guest, "dir")
        except:
            log("Second command is blocked while first command is running.")
        else:
            raise xenrt.XRTFailure("Succeeded to run a command while another is running.")

    def verifyVMOPsProhibited(self, guest):
        """Check VM power operations are blocked by XAPI during command is running."""

        try:
            guest.suspend()
        except:
            log("Suspend is blocked as expected.")
        else:
            raise xenrt.XRTFailure("Guest rebooted while a command is running.")

        try:
            guest.shutdown()
        except:
            log("Shutdown is blocked as expected.")
        else:
            raise xenrt.XRTFailure("Guest rebooted while a command is running.")

        pool = guest.host.pool
        if not pool:
            pool = self.getDefaultPool()
        if not pool:
            raise xenrt.XRTError("VM OPs test requires a pool.")
        target = None
        for host in pool.getHosts():
            if host != guest.host:
                target = host
                break
        try:
            guest.migrateVM(target, live="true")
        except:
            log("VM migration is blocked as expected.")
        else:
            raise xenrt.XRTFailure("VM migration is allowed while a command is running.")

    def verifyCommandCancelled(self, guest):
        """Check VM force reboot kills current task."""

        guest.shutdown(force=True)
        xenrt.sleep(10)
        guest.start()

        self.runCommand(guest, "dir")
        xenrt.sleep(self.COMMAND_INTERVAL)

    def run(self, arglist=None):
        step("Start all longRunning jobs.")
        self.runCase(self.executeLongRunningCommand)

        step("Verify next command is blocked by XAPI.")
        self.runCase(self.verifyDualCommandProhibited)

        step("Verify VM power ops are blocked by XAPI.")
        self.runCase(self.verifyVMOPsProhibited)

        step("Verify force reboot VM cancels existing job.")
        self.runCase(self.verifyCommandCancelled)


class TCGuestAgentMemory(TCStressCommandBase):
    """Verify Guest Agent memory are not over filled."""

    USE_TARGET = 2
    MARGIN = 30 * 1024
    PERIOD = 300 # in second to run.
    STEP = 10    # in seconds to sleep between iteration.

    def runHeavyOutputCommand(self, guest):
        """Running a heavy STDOUT command.

        @param guest: Guest instance to run command.

        @return: task id of XAPI async call.
        """
        script = """:start
dir /s /a c:\\
ping citrite.net -n 2
goto start
"""
        return self.runLongRunningCommand(guest, 0, script)

    def getGuestAgentRamUsage(self, guest):
        """Return size of RAM that guest agent is using."""

        ps = guest.xmlrpcExec("tasklist /FI \"IMAGENAME eq xenguestagent.exe\"", returndata = True)
        log("Found process info: %s" % ps)
        if ps:
            for line in reversed(ps.splitlines()):
                line = line.strip()
                if len(line):
                    try:
                        return int(line.split()[4].replace(",", ""))
                    except:
                        pass
        raise xenrt.XRTError("Cannot find guest agent process from guest %s" % guest.getName())

    def verifyGuestAgentMemory(self, guest):
        """Verify long running with large amount of output does not fill up
        memory of guest."""
        initram = self.getGuestAgentRamUsage(guest)
        log("Initial ram usage: %d" % initram)

        self.runHeavyOutputCommand(guest)

        xenrt.sleep(self.STEP)
        startram = self.getGuestAgentRamUsage(guest)
        log("After workload start ram usage: %d" % startram)

        for i in xrange(1, self.PERIOD / self.STEP + 1):
            curram = self.getGuestAgentRamUsage(guest)
            log("After %d sec ram usage: %d" % ((i * 10), curram))
            if curram > startram + self.MARGIN:
                raise xenrt.XRTFailure("Ram usage increased significantly.")
            xenrt.sleep(self.STEP)

    def run(self, arglist=None):
        self.runCase(self.verifyGuestAgentMemory)


class TCTempFileClear(TCStressCommandBase):
    """Verify temp directory in guest cleared properly."""

    TEMP_PATH = "%%TEMP%%"
    USE_TARGET = 1

    def getTempFileCount(self):
        """Return file count of temp"""
        guest = self.guests[0]
        output = guest.xmlrpcExec("dir %s /A /S /W | find \"File(s)\"" % self.TEMP_PATH, returndata = True).splitlines()[-1].strip()
        return int(output.split()[0])

    def run(self, arglist=None):
        guest = self.guests[0]

        initialCnt = self.getTempFileCount()
        log("Initial file count of temp dir is %d" % initialCnt)

        self.runLongRunningCommand(guest, time=60)
        xenrt.sleep(10)
        runningCnt = self.getTempFileCount()
        log("File count while command is running is %d" % runningCnt)

        xenrt.sleep(60)
        finalCnt = self.getTempFileCount()
        log("File coutn after command is executed is %d" % finalCnt)

        if runningCnt <= initialCnt:
            warning("Temp file count has decreased while command is running.")
        if finalCnt >= runningCnt:
            raise xenrt.XRTFailure("Temp file count has not decreased after command is done.")
        if finalCnt != initialCnt:
            warning("Temp file count has been changed after command is executed.")


class TCRBAC(TCRemoteCommandExecBase):
    """Verify API only available on vm-power-admin and above."""

    USE_TARGET = 1

    ALLOWED_ROLES = {"pooladmin": "xenroot01T", "pooloperator": "xenroot01T", "vmpoweradmin": "xenroot01T"}
    PROHIBITED_ROLES = {"vmadmin": "xenroot01T", "vmoperator": "xenroot01T", "readonly": "xenroot01T"}

    def runRBACTest(self, allowed, username, password):
        log("Testing with %s role" % username)
        try:
            self.executeCommandAPI(self.guests[0], "dir", username=username, password=password)
        except Exception as e:
            log("EXCEPTION: %s" % e)
            if allowed:
                raise xenrt.XRTFailure("Failed to execute with %s role." % username)
            else:
                log("%s roles failed to run as expected." % username)
        else:
            if allowed:
                log("Succeeded to run with %s the command." % username)
            else:
                raise xenrt.XRTFailure("Succeded to execute with %s role." % username)
        finally:
            xenrt.sleep(self.COMMAND_INTERVAL)

    def run(self, arglist=None):
        step("Testing ALLOWED RBAC accounts.")
        for key in self.ALLOWED_ROLES:
            self.runSubcase("runRBACTest", (True, key, self.ALLOWED_ROLES[key]), "allowed", key)

        step("Testing PROHIBITED RBAC accounts.")
        for key in self.PROHIBITED_ROLES:
            self.runSubcase("runRBACTest", (False, key, self.PROHIBITED_ROLES[key]), "prohibited", key)
