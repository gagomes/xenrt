#
# XenRT: Test harness for Xen and the XenServer product family
#
# Run a legacy test script on a remote host
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

import xenrt, xenrt.util

#from common import * 

class TestCaseLegacy(xenrt.TestCase):

    def __init__(self, tcid="TestCaseLegacy", testname=None):
        xenrt.TestCase.__init__(self, tcid=tcid)
        self.testname = testname
        self.uniq = xenrt.util.timenow()
        self.host = None
        self.guest = None
    
    # Build the SSH command line.
    def remoteCommandLine(self, action):
        cmdl = ["%s/dispatch.new" % (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"))]
        cmdl.append(xenrt.TEC().lookup("JOBID", "-"))
        cmdl.append(str(self.uniq))
        for parameter in [ "VERSION", 
                           "REVISION", 
                           "OPTIONS", 
                           "MACHINE" ]:
            cmdl.append(xenrt.TEC().lookup(parameter, "-") or "-")
        cmdl.append(self.testname)
        cmdl.append("-")   # phase TODO
        cmdl.append(action)
        if self.testargs:
            cmdl = cmdl + self.testargs
        cmd = string.join(cmdl)
        xenrt.TEC().logverbose("Legacy exec %s" % (cmd))
        return cmd

    def run(self, arglist=None):

        self.testargs = []
        timeout = 300

        if self.runon:
            remote = self.runon
        elif self.guest:
            remote = xenrt.TEC().registry.guestGet(self._guest)
        elif self.host:
            remote = xenrt.TEC().registry.hostGet(self._host)
        else:
            raise xenrt.XRTError("No remote host specified")
        self.testargs = arglist

        if not remote:
            raise xenrt.XRTError("Unable to find remote host in registry")

        config = xenrt.TEC().getAllConfig()
 
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
        c = ssh.open_session()
        c.settimeout(timeout)
        c.set_combine_stderr(True)
        c.exec_command(self.remoteCommandLine("waitfor"))
        c.sendall(config)
        c.shutdown(1)
        f = c.makefile()
        while True:
            try:
                output = f.readline()
            # Test unresponsive.
            except socket.timeout:
                raise xenrt.XRTError("Waitfor timed out")
            
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
                raise xenrt.XRTError("Waitfor connection error")
            else:
                continue 
        c.close()

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
        #c = ssh.open_session()
        #c.exec_command(self.remoteCommandLine("cleanup"))
        #c.sendall(config)
        #c.close()

        ssh.close()

