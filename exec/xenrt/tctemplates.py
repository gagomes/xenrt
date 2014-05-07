#
# XenRT: Test harness for Xen and the XenServer product family
#
# Superclass for benchmarks and other on-guest tests
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

SSHPORT     =   22
LOG_SUFFIX  =   "logs.tar.bz2"

import re
import os
import socket 
import sys
import string
import paramiko
import time
import traceback

import xenrt, xenrt.util

#from common import * 

class TestCaseWrapper(xenrt.TestCase):

    def __init__(self, tcid="TestCaseWrapper", testname=None):
        xenrt.TestCase.__init__(self, tcid=tcid)
        self.testname = testname
        self.uniq = xenrt.util.timenow()
        self.bmversion = None
        self.bmspecial = None
        self.nolinux = False

    # Build the SSH command line for legacy SSH tests.
    def remoteCommandLine(self, action):
        cmdl = ["%s/dispatch.new" % (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"))]
        cmdl.append(xenrt.TEC().lookup("JOBID", "-"))
        cmdl.append(str(self.uniq))
        for parameter in [ "VERSION", 
                           "REVISION", 
                           "OPTIONS", 
                           "MACHINE" ]:
            cmdl.append(xenrt.TEC().lookup(parameter, "-"))
        cmdl.append(self.testname)
        cmdl.append("-")   # phase TODO
        cmdl.append(action)
        if self.testargs:
            cmdl = cmdl + self.testargs
        cmd = string.join(cmdl)
        xenrt.TEC().logverbose("Legacy exec %s" % (cmd))
        return cmd

    def run(self, arglist=None):

        if self.runon:
            remote = self.runon
            if remote:
                self.getLogsFrom(remote)
            c = "runon"
        elif self._guest:
            remote = xenrt.TEC().registry.guestGet(self._guest)
            if remote:
                self.getLogsFrom(remote)
                if remote.host:
                    self.getLogsFrom(remote.host)
            c = "guest:%s" % (self._guest)
        elif self._host:
            remote = xenrt.TEC().registry.hostGet(self._host)
            if remote:
                self.getLogsFrom(remote)
            c = "host:%s" % (self._host)
        else:
            raise xenrt.XRTError("No remote host specified")

        if not remote:
            raise xenrt.XRTError("Unable to find remote host in registry (%s)"
                                 % (c))

        try:
            # Start remote if it hasn't been already.
            xenrt.TEC().logverbose("Test target state: %s" % (remote.getState()))
            if not remote.getState() == "UP":
                xenrt.TEC().logverbose("Starting test target...")
                remote.start()
                self._guestsToShutdown.append(remote)
        except:
            pass

        if xenrt.TEC().lookup("OPTION_PERF_REBOOT", False, boolean=True):
            remote.reboot()
            try:
                if remote.windows:
                    # Clean out temporary files.
                    remote.xmlrpcDelTree(remote.xmlrpcGetEnvVar("TEMP"))
                    remote.xmlrpcCreateDir(remote.xmlrpcGetEnvVar("TEMP"))
                    # Check disk space. 
                    if float(remote.xmlrpcWindowsVersion()) > 5.99:
                        data = remote.xmlrpcExec("echo list disk | diskpart",
                                                  returndata=True)
                        data = re.search("Disk 0.*", data).group().split()
                        if data[-1] == "MB":
                            free = int(data[-2])
                        else:
                            free = int(data[-2])*1024
                    else:
                        data = remote.xmlrpcExec("freedisk", returndata=True)
                        free = int(re.sub(",", "", re.search("[0-9,]+", data).group())) / 2**20
                else:
                    # Clean out temporary files.
                    remote.execcmd("rm -rf /tmp/*")
                    # Resync scripts.
                    remote.tailor()
                    # Check disk space. 
                    data = remote.execcmd("df -l")
                    data = re.search("(?P<free>\d*)\s*(\d*%)\s*(/)", data).group("free")
                    free = int(data) / 2**10
                if free < 100:
                    xenrt.TEC().warning("Low disk space. (%sM)" % (free))
            except Exception, e:
                xenrt.TEC().warning("Failed to reset VM (%s)." % (str(e)))

        if remote.windows:
            self.runViaDaemon(remote, arglist)
        elif self.nolinux:
            xenrt.TEC().skip("No Linux implementation")
        elif self.testname:
            self.runLegacy(remote, arglist)
        else:
            xenrt.TEC().skip("No SSH implementation")

    def runViaDaemon(self, remote, arglist=None):
        xenrt.TEC().skip("No non-SSH implementation")

    def runLegacy(self, remote, arglist=None):
        """Use the legacy SSH interface to run the test"""

        self.testargs = []
        timeout = 300
        self.testargs = arglist
        config = xenrt.TEC().getAllConfig()
        if xenrt.TEC().lookup("EXTRA_TIME", False, boolean=True):
            config += "TIMEOUT=21600\n"

        ssh = remote.sshSession()
        xenrt.TEC().progress("Installing test '%s' on %s with args '%s'" %
                             (self.testname, remote.getIP(),
                              self.testargs))

        c = ssh.open_session()
        c.settimeout(timeout)
        c.set_combine_stderr(True)
        c.exec_command(self.remoteCommandLine("install"))
        c.sendall(config)
        c.shutdown(1)
        f = c.makefile()
        # A received string of length zero indicates the channel 
        # is closed.
        while True:
            try:
                output = f.readline()
            except socket.timeout:
                raise xenrt.XRTError("Install timed out")
            xenrt.TEC().log(output)
            if len(output) == 0:
                break
        exit_status = c.recv_exit_status()
        if exit_status == -1:
            raise xenrt.XRTError("Install connection error")
        elif not exit_status == 0:
            raise xenrt.XRTError("Install failed")
        c.close()

        # Start running the test.  
        xenrt.TEC().progress("Starting test")
        c = ssh.open_session()
        c.settimeout(timeout)
        c.set_combine_stderr(True)
        c.exec_command(self.remoteCommandLine("start"))
        c.sendall(config)
        c.shutdown(1)
        f = c.makefile() 
        while True:
            try:
                output = f.readline()
            except socket.timeout:
                raise xenrt.XRTError("Start timed out")
            xenrt.TEC().log(output)
            if len(output) == 0:
                break
        exit_status = c.recv_exit_status()
        if exit_status == -1:
            raise xenrt.XRTError("Start connection error")
        elif not exit_status == 0:
            raise xenrt.XRTError("Start failed")
        c.close()    

        # Wait for the test to complete. 
        xenrt.TEC().progress("Waiting for test to complete")
        retries = 0
        while True:
            retry = False
            c = None
            try:
                c = ssh.open_session()
                c.settimeout(timeout)
                c.set_combine_stderr(True)
                c.exec_command(self.remoteCommandLine("waitfor"))
                c.sendall(config)
                c.shutdown(1)
                f = c.makefile()
            except Exception, e:
                xenrt.TEC().logverbose("Exception %s" % (str(e)))
                retry = True
                c = None
            while not retry:
                try:
                    output = f.readline()
                # Test unresponsive.
                except socket.timeout:
                    xenrt.TEC().logverbose("Waitfor timed out")
                    retry = True
                    break
            
                # Test still running and responsive.
                if output == "Running\n": 
                    continue
                # Test complete.
                elif output == "Done\n": 
                    break    
                elif output == "Dead\n":
                    xenrt.TEC().reason("Remote test death detected")
                    break    
                # Test responsive but has been running for too long.
                elif output == "Timeout\n":
                    xenrt.TEC().reason("Test timed out")
                    break    
                elif len(output) == 0: 
                    xenrt.TEC().logverbose("Waitfor connection error")
                    retry = True
                    break
                else:
                    continue 
            if c:
                c.close()
            if not retry:
                break
            retries = retries + 1
            if retries >= 10:
                raise xenrt.XRTError("Reached maximum waitfor retry count")
            xenrt.sleep(30)
            try:
                ssh.close()
            except:
                pass
            ssh = remote.sshSession()

            # Process the test results.
            xenrt.TEC().progress("Processing test results")
            c = ssh.open_session()
            c.settimeout(300)
            c.exec_command(self.remoteCommandLine("process"))
            c.sendall(config)
            c.shutdown(1)
            f = c.makefile()
            result = ""
            while True:
                try:
                    output = f.readline()
                except socket.timeout:
                    raise xenrt.XRTError("Process timed out")
                # Either we have all the results or the channel closed
                # unexpectedly.
                if len(output) == 0:
                    break
                xenrt.TEC().log(output)
                result += output
            if exit_status == -1:
                raise xenrt.XRTError("Process connection error")
            elif not exit_status == 0:
                raise xenrt.XRTError("Process failed")
            c.close()
            result = re.findall(".*:.*\n", result)
            for res in result:#string.split(result, "\n"):
                r = re.search(r"^(\w+):\s*(.+)", res)
                if r:
                    t = r.group(1)
                    c = r.group(2)
                    if t == "Comment":
                        xenrt.TEC().comment(c)
                    elif t == "Reason":
                        xenrt.TEC().reason(c)
                    elif t == "Result":
                        xenrt.TEC().appresult(c)
                    elif t == "Warning":
                        xenrt.TEC().warning(c)
                    elif t == "Value":
                        r2 = re.search(r"(\S+)\s+(\S+)\s+(\S+)", c)
                        if r2:
                            xenrt.TEC().value(r2.group(1), r2.group(2), r2.group(3))
                        else:
                            r2 = re.search(r"(\S+)\s+(\S+)", c)
                            if r2:
                                xenrt.TEC().value(r2.group(1), r2.group(2))
                    elif t == "Test":
                        if c == "passed":
                            self.setResult(xenrt.RESULT_PASS)
                        elif c == "failed":
                            self.setResult(xenrt.RESULT_FAIL)
                        elif c == "skipped":
                            self.setResult(xenrt.RESULT_SKIPPED)
                        elif c == "partial":
                            self.setResult(xenrt.RESULT_PARTIAL)
                        elif c == "error":
                            self.setResult(xenrt.RESULT_ERROR)
                        else:
                            self.setResult(xenrt.RESULT_UNKNOWN)
                    elif t == "Variable":
                        pass # TODO


            # Retrieve the logs from the test machine.
            xenrt.TEC().progress("Fetching logs")
            c = ssh.open_session()
            c.settimeout(timeout)
            c.exec_command(self.remoteCommandLine("getlogs"))
            logs = xenrt.TEC().tempFile()
            c.sendall(config)
            c.shutdown(1)
            f = c.makefile()
            g = file(logs, "w")
            while True:
                try:
                    output = f.read(4096)
                except socket.timeout:
                    raise xenrt.XRTError("Reason: Getlogs timed out.")
                if len(output) == 0:
                    break
                g.write(output)
            g.close()
            c.close()
            # Unpack the logs
            ldir = "%s/logs" % (xenrt.TEC().getLogdir())
            os.mkdir(ldir)
            xenrt.util.command("tar -jxf %s -C %s" % (logs, ldir))
            
            # Clean up after the test on the test machine. 
            # This is currently a noop for most tests. Need to 
            # remember to read output for this.
            c = ssh.open_session()
            c.exec_command(self.remoteCommandLine("cleanup"))
            c.sendall(config)
            clean = xenrt.TEC().tempFile()
            c.shutdown(1)
            f = c.makefile()
            g = file(clean, "w")
            while True:
                try:
                    output = f.read(4096)
                except socket.timeout:
                    raise xenrt.XRTError("Reason: Cleanup timed out.")
                if len(output) == 0:
                    break
                g.write(output)
            g.close()
            c.close()
        
            ssh.close()

class LoopingTestCase(xenrt.TestCase):

    initialState = None

    def __init__(self,tcid):
        xenrt.TestCase.__init__(self,tcid)
        self.guest = None
        self.workloadsExecd = None
        self.usedclone = False

    def extraArgs(self, arg):
        pass

    def preRun(self, guest):
        pass

    def run(self, arglist=None):
        # Default args
        loops = 50
        gname = "RESOURCE_GUEST_0"
        reboot = False
        workloads = False
        clonevm = False

        if arglist and len(arglist) > 0:
            for arg in arglist:
                l = string.split(arg, "=", 1)
                if l[0] == "reboot":
                    reboot = True
                elif l[0] == "guest":
                    gname = l[1]
                elif l[0] == "loops":
                    loops = int(l[1])
                elif l[0] == "config":
                    matching = xenrt.TEC().registry.guestLookup(\
                                **xenrt.util.parseXMLConfigString(l[1]))
                    for n in matching:
                        xenrt.TEC().comment("Found matching guest(s): %s" % 
                                            (n))
                    if matching:
                        gname = matching[0]
                elif l[0] == "workloads":
                    if len(l) > 1:
                        workloads = l[1].split(",")
                    else:
                        workloads = None
                elif l[0] == "clone":
                    clonevm = True
                else:
                    self.extraArgs(arg)

        guest = self.getGuest(gname)
        self.guest = guest
        if not guest:
            raise xenrt.XRTError("Guest %s not found" % (gname))

        if xenrt.TEC().lookup("OPTION_USE_CLONE", False, boolean=True) or clonevm:
            xenrt.TEC().comment("Using clone to run test.")
            self.blocker = False
            if guest.getState() != "UP":
                guest.start()
            guest.preCloneTailor()
            guest.shutdown()
            clone = guest.cloneVM()
            self.guest = clone
            guest = clone
            self.usedclone = True
            self.getLogsFrom(guest)

        # Do any test specific preRun
        self.preRun(guest)

        # See if preRun has set us to skip
        if self.getResult(code=True) == xenrt.RESULT_SKIPPED:
            return

        # See what the initial state is (assumed to be up if not specified)
        if not self.initialState:
            self.initialState = "UP"

        try:
            gState = guest.getState()

            if self.initialState == "UP":
                if gState == "DOWN":
                    xenrt.TEC().comment("Starting guest before commencing loop")
                    guest.start()
                elif gState == "SUSPENDED":
                    xenrt.TEC().comment("Resuming guest before commencing loop")
                    guest.resume()
            elif self.initialState == "DOWN":
                if gState == "UP":
                    xenrt.TEC().comment("Stopping guest before commencing loop")
                    guest.shutdown()
                elif gState == "SUSPENDED":
                    xenrt.TEC().comment("Resuming then stopping guest before "
                                        "commencing loop")
                    guest.resume()
                    guest.shutdown()
            elif self.initialState == "SUSPENDED":
                if gState == "UP":
                    xenrt.TEC().comment("Suspending guest before commencing "
                                        "loop")
                    guest.suspend()
                elif gState == "DOWN":
                    xenrt.TEC().comment("Starting then suspending guest before "
                                        "commencing loop")
                    guest.start()
                    guest.suspend()
    
            # Do we have any workloads to start?
            if workloads != False:
                if self.initialState != "UP":
                    raise xenrt.XRTError("Workloads specified but initial "
                                         "state is %s" % (self.initialState))

                if guest.windows:
                    self.workloadsExecd = guest.startWorkloads(workloads)
                else:
                    self.workloadsExecd = guest.startWorkloads(workloads)
    
            # If initial state is UP, make sure the guest is healthy
            if self.initialState == "UP":
                if guest.windows:
                    guest.waitForDaemon(60, desc="Guest check")
                else:
                    guest.waitForSSH(60, desc="Guest check")
        except Exception, e:
            xenrt.TEC().logverbose("Guest broken before we started (%s)." % str(e))
            raise

        # Now start the loop
        success = 0
        try:
            for i in range(loops):
                xenrt.TEC().logdelimit("loop iteration %u..." % (i))
                self.loopBody(guest,i)
                success += 1
                if xenrt.GEC().abort:
                    xenrt.TEC().warning("Aborting on command")
                    break
        except:
            guest.checkHealth()
            raise
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" % (success,loops))
            self.finallyBody(guest)

        if workloads != False:
            guest.stopWorkloads(self.workloadsExecd)

        try:
            if reboot:
                guest.reboot()
        except xenrt.XRTFailure, e:
            raise xenrt.XRTError(e.reason)

    def loopBody(self, guest, iteration):
        pass

    def finallyBody(self, guest):
        pass

    def postRun(self):
        try:
            self.guest.stopWorkloads(self.workloadsExecd)
        except:
            pass
        if self.usedclone:
            try:
                self.guest.shutdown(again=True)
            except:
                pass
            try:
                self.guest.uninstall()
            except:
                pass

