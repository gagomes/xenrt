#
# XenRT: Test harness for Xen and the XenServer product family
#
# Testcases for logging features
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy
import xenrt, xenrt.lib.xenserver, math
from time import sleep
from xenrt.lazylog import log, step, comment

class TC6710(xenrt.TestCase):
    """Remote syslog operation"""

    def prepare(self, arglist):

        # Get a host to use
        self.host = self.getDefaultHost()

    def setupRsyslog(self, guest):
        guest.execguest("perl -p  -i -e 's/^#(\$ModLoad\s+imudp)/$1/' /etc/rsyslog.conf")
        guest.execguest("perl -p  -i -e 's/^#(\$UDPServerRun\s+514)/$1/' /etc/rsyslog.conf")
        guest.execguest("/etc/init.d/rsyslog restart")
        return
    
    def run(self, arglist):

        host = self.host
        
        useRsyslog = False

        step("Install a basic Linux VM")
        guest = host.createGenericLinuxGuest()
        self.uninstallOnCleanup(guest)
        self.getLogsFrom(guest)        
        guest.addExtraLogFile("/var/log/syslog")

        step("Configure the VM as a syslog server")
        # This might be Debian squeeze
        release = guest.execguest("which lsb_release > /dev/null && lsb_release -c || true").strip()
        if release.endswith("squeeze") or release.endswith("wheezy"):
            self.setupRsyslog(guest)
            useRsyslog = True
        else:
            # Configure the VM as a syslog server 
            guest.execguest("echo 'SYSLOGD=\"-r\"' > /etc/default/syslogd")
            guest.execguest("mv /etc/init.d/sysklogd /etc/init.d/sysklogd.orig")
            guest.execguest("sed -e's/^SYSLOGD.*/SYSLOGD=\"-r\"/' "
                            "< /etc/init.d/sysklogd.orig > /etc/init.d/sysklogd")
            guest.execguest("chmod 755 /etc/init.d/sysklogd")
            guest.execguest("/etc/init.d/sysklogd restart")
    
        if guest.execguest("netstat -lun | grep -q :514", retval="code") != 0:
            raise xenrt.XRTError("syslogd not listening")

        step("Enable syslog on the host")
        host.enableSyslog(guest.getIP())

        step("Create a manual log entry to check where it goes")
        msg = "TEST%s" % (xenrt.randomGuestName())
        host.execdom0("logger -t xenrt '%s'" % (msg))
        time.sleep(10)

        step("Check the message reached the syslogd")
        if guest.execguest("grep %s /var/log/syslog*" % (msg),retval="code") != 0:
            raise xenrt.XRTFailure("syslog message not found on syslog server")
        
        step("Check the message is populated in Host")
        if not isinstance(host, xenrt.lib.xenserver.DundeeHost):
            if host.execdom0("grep %s /var/log/messages" % (msg),retval="code") != 0:
                raise xenrt.XRTFailure("syslog message not found locally when remote is enabled")
        elif host.execdom0("grep %s /var/log/user.log" % (msg),retval="code") != 0:
            raise xenrt.XRTFailure("syslog message not found locally when remote is enabled")

        step("Spam the syslog to ensure the next check doesn't see old entries")
        host.execdom0('for (( i=0;i<6000;i++ )); do logger -t xenrt "logspam $i"; done')

        step("Cause some xapi activity")
        host.restartToolstack()
        time.sleep(20)

        step("Check the \"xapi (re)start message\" reached the syslogd")
        if guest.execguest("tail -n 6000 /var/log/syslog | grep '(Re)starting xapi'", retval="code") != 0:
            raise xenrt.XRTFailure("syslog message not found on syslog server (xapi)")
        
        step("Check the \"xapi (re)start message\" is populated in Host")
        if not isinstance(host, xenrt.lib.xenserver.DundeeHost):
            if host.execdom0("tail -n 6000 /var/log/messages | grep '(Re)starting xapi'", retval="code") != 0:
                raise xenrt.XRTFailure("syslog message not found locally when remote is enabled")
        elif host.execdom0("tail -n 6000 /var/log/xensource.log | grep '(Re)starting xapi'", retval="code") != 0:
            raise xenrt.XRTFailure("syslog message not found locally when remote is enabled")

        step("Stop the remote syslog server and verify the host still works")
        if useRsyslog:
            guest.execguest("/etc/init.d/rsyslog stop")
        else:
            guest.execguest("/etc/init.d/sysklogd stop")
        host.listGuests()
        time.sleep(5)
        host.listGuests()
        time.sleep(5)
        host.checkHealth()

        step("Re-enable the remote syslog server and check it")
        guest.execguest("rm -f /var/log/syslog")
        if useRsyslog:
            guest.execguest("/etc/init.d/rsyslog start")
        else:
            guest.execguest("/etc/init.d/sysklogd start")
        
        step("Create a manual log entry to check where it goes")
        msg = "TEST%s" % (xenrt.randomGuestName())
        host.execdom0("logger -t xenrt '%s'" % (msg))
        time.sleep(20)
        
        step("Check the message reached the syslogd")
        if guest.execguest("grep %s /var/log/syslog*" % (msg), retval="code") != 0:
            raise xenrt.XRTFailure("syslog message not found on syslog server after restart")

        step("Check the message is populated in Host")
        if not isinstance(host, xenrt.lib.xenserver.DundeeHost):
            if host.execdom0("grep %s /var/log/messages" % (msg),retval="code") != 0:
                raise xenrt.XRTFailure("syslog message not found locally when remote is enabled")
        elif host.execdom0("grep %s /var/log/user.log" % (msg),retval="code") != 0:
                raise xenrt.XRTFailure("syslog message not found locally when remote is enabled")
        
        step("Spam the syslog to ensure the next check doesn't see old entries")
        host.execdom0('for (( i=0;i<6000;i++ )); do logger -t xenrt "logspam $i"; done')

        step("Disable remote syslogging by the host")
        host.disableSyslog()

        step("Create a manual log entry to check where it goes")
        msg = "TEST%s" % (xenrt.randomGuestName())
        host.execdom0("logger -t xenrt '%s'" % (msg))
        time.sleep(60)

        step("Make sure the message is in the local log")
        if host.execdom0("grep %s /var/log/messages || grep %s /var/log/user.log" % (msg, msg), retval="code") != 0:
            raise xenrt.XRTFailure("syslog message not locally when remote was disabled")

        step("Check the message didn't reach syslogd")
        if guest.execguest("grep %s /var/log/syslog*" % (msg), retval="code") == 0:
            raise xenrt.XRTFailure("syslog message found on syslog server after remote syslogging disabled")

        step("Cause some xapi activity and verify logs go to the right place")
        host.restartToolstack()
        time.sleep(60)
        
        if not isinstance(host, xenrt.lib.xenserver.DundeeHost):
            if host.execdom0("tail -n 6000 /var/log/messages | grep '(Re)starting xapi'", retval="code") != 0:
                raise xenrt.XRTFailure("syslog message not found locally when remote was disabled (xapi)")
        elif host.execdom0("tail -n 6000 /var/log/xensource.log | grep '(Re)starting xapi'", retval="code") != 0:
            raise xenrt.XRTFailure("syslog message not found locally when remote was disabled (xapi)")

        step("Check the message didn't reach the syslogd")
        if guest.execguest("tail -n 6000 /var/log/syslog | grep '(Re)starting xapi'", retval="code") == 0:
            raise xenrt.XRTFailure("syslog message found on syslog server after remote syslogging disabled (xapi)")

    def postRun(self):
        if self.host:
            self.host.disableSyslog()

class TC7954(TC6710):
    """Remote syslog operation on a slave host."""
    
    def prepare(self, arglist):

        # Get a host to use
        h = self.getDefaultHost()
        if not h.pool:
            raise xenrt.XRTError("No pool found")
        slaves = h.pool.getSlaves()
        if len(slaves) == 0:
            raise xenrt.XRTError("No slaves in pool")
        self.host = slaves[0]

class _GenerateLogs(xenrt.XRTThread):
    """This thread runs in the background writing to files in /var/log through syslog"""
    
    def __init__(self, host):
    
        xenrt.XRTThread.__init__(self, name="GenerateLogs")
        self.host = host

    def createLogSpamFile(self):
    
        script="""
#!/usr/bin/env python
#!/usr/bin/env python

import syslog
import time

syslog.openlog('logspammer')

facilities = [
  syslog.LOG_KERN,
# syslog.LOG_USER, 
  syslog.LOG_MAIL,
  syslog.LOG_DAEMON,
  syslog.LOG_AUTH,
  syslog.LOG_LPR,
  syslog.LOG_NEWS,
  syslog.LOG_UUCP,
# syslog.LOG_CRON,
  syslog.LOG_SYSLOG,
  syslog.LOG_LOCAL0,
  syslog.LOG_LOCAL1,
  syslog.LOG_LOCAL2,
  syslog.LOG_LOCAL3,
  syslog.LOG_LOCAL4,
  syslog.LOG_LOCAL5,
  syslog.LOG_LOCAL6,
  syslog.LOG_LOCAL7
]

vol=2500*1024*1024
msgcount = vol/2000/len(facilities)


i = 0
t = time.time()
while (i < msgcount):
    i = i+1

    # (These numbers will need tweaking depending on speed of test-machine.)
    if i % 40 == 0:
        t = t + 5.91
        nap = t - time.time()
        if nap > 0:
            time.sleep(nap)

    # Facility local5 is used by xapi.
    for f in facilities:
        syslog.syslog(syslog.LOG_INFO | f, (
            "Nonsenseha %d facility %d ---- This is spam entry to increase log size iaseriaiseri iaserianer aw8i3rjiaw3jr w9arj4 aiw3rja9iw 3jra9w3j r9aw3 jria r439ai r9iae rj9iase r9iase jrfi9ase f9iase jf9iase jrfi9asj erfi9asj eij r9aw3 jria r439ai r9iae rj9iase r9iase jrfi9ase f9iase jf9iase jrfi9asj erfi9asj eirfasierfj r9aw3 jria r439ai r9iae rj9iase r9iase jrfi9ase f9iase jf9iase jrfi9asj erfi9asj ej r9aw3 jria r439ai r9ij r9aw3 jria r439ai r9iae rj9iase r9iase jrfi9ase f9iase jf9iase jrfi9asj erfi9asj eirfasierfj r9aw3 jria r439ai r9iae rj9iase r9iase jrfi9ase f9iase jf9iase jrfi9asj erfi9asj eirfasierfj r9aw3 jria r439ai r9iae rj9iase r9iase jrfi9ase f9iase jf9iase jrfi9asj erfi9asj eirfasierfj r9aw3 jria r439ai r9iae rj9iase r9iase jrfi9ase f9iase jf9iase jrfi9asj erfi9asj eirfasierfae rj9iase rj r9aw3 jria r439ai r9iae rj9iase r9iase jrfi9ase f9iase jf9iase jrfi9asj erfi9asj eirfasierfj r9aw3 jria r439ai r9iae rj9iase r9iase jrfi9ase f9iase jf9iase jrj r9aw3 jria r439ai r9iae rj9iase r9iase jrfi9ase f9iase jf9iase jrfi9asj erfi9asj eirfasierffi9asj erfi9asj eirfasierfj r9aw3 jria r439ai r9iae rj9iase r9iase j r9aw3 jria r439ai r9iae rj9iase r9iase jrfi9ase f9iase jf9iase jrfi9asj erfi9asj eirfasierfjrfi9ase f9iase jf9iase jrfi9asj erfi9asj eirfasierfj r9aw3 jria r439ai r9iae rj9iase r9iase jrfi9ase f9iase jf9iase jrfi9asj erfi9asj eirfasierf9iase jrfi9ase f9iase jf9iase jrfi9asj erfi9asj eirfasierfj r9aw3 jria r439ai r9iae rj9iase r9iase jrfi9ase f9iase jf9iase jrfi9asj erfi9asj eirfasierfj r9aw3 jria r439ai r9iae rj9iase r9iase jrfi9ase f9iase jf9iase jrfi9asj erfi9asj eirfasierfirfasierfj r9aw3 jria r439ai r9iae rj9iase r9iase jrfi9ase f9iase jf9iase jrfi9asj erfi9asj eirfasierfj r9aw3 jria r439ai r9iae rj9iase r9iase jrfi9ase f9iase jf9iase jrfi9asj erfi9asj eirfasierfrfasierfaise rfaisefaiisejfriasejfrisjefijseifjsiefjaiesfjaiesjfiasejfiasjefijaseifjaisejfiasejfiajefiajsefiaseirfja eirj aie jrfijawe XYZABC"
        % (i,f)))
        """
        logspammer = xenrt.TEC().tempFile()
        f = file(logspammer, "w")
        f.write(script)
        f.close()
        sftp = self.host.sftpClient()
        sftp.copyTo(logspammer, "/home/logspammer.py")
        sftp.close()
        
    def run(self):
        xenrt.TEC().logverbose("Generating logs using syslog by writing log messages to files in /var/log/")
        self.createLogSpamFile()
        self.host.execdom0("python /home/logspammer.py &")
        xenrt.TEC().logverbose("Done writing to logs")


class TC19175(xenrt.TestCase):
    """testcase to verify improved dom0 log rotation and deletion"""
    
    MAXVARLOGSIZE = 500
    MAXLIVELOGSSIZE = 36
    MINLIVELOGSSIZE = 12
    MAXTIMEPERIOD = 60
    TIMEOUT = 1500
    

    def prepare(self, arglist):
        self.host = self.getDefaultHost()


    def verifyDeleteGzFile(self, arglist):
        #Verify gzipped files are deleted and in proper order when /var/log size goes beyond 500MB before next minute.
        
        deadline = xenrt.timenow() + self.TIMEOUT
        while True:
        
            varLogSize = int(int(self.host.execdom0("du /var/log/ | tail -1").split()[0])/1024)
            
            if varLogSize < self.MAXVARLOGSIZE:
                xenrt.TEC().logverbose("Creating gzipped files to increase the size of /var/log/ %sMB beyond %sMB " %(varLogSize ,self.MAXVARLOGSIZE ))
                for i in range(8):
                    self.host.execdom0(" cd /var/log/ && dd if=/dev/zero of=%s.gz bs=1M count=20" % (xenrt.randomGuestName())) 
                    xenrt.sleep(1)
            varLogSize = int(int(self.host.execdom0("du /var/log/ | tail -1").split()[0])/1024)
            xenrt.TEC().logverbose("Size of '/var/log' is %sMB after creating gzipped files to increase size beyond %sMB " %(varLogSize ,self.MAXVARLOGSIZE ))
            
            if varLogSize > self.MAXVARLOGSIZE:
                cmd = "cd /var/log/ && ls -t -1 *.gz"
                gzFilesOld = self.host.execdom0(cmd).split("\n")[:-1]
                xenrt.TEC().logverbose("gz files ordered by time of creation before deletion by log handler %s" %(gzFilesOld))
                xenrt.sleep(self.MAXTIMEPERIOD)
                varLogSize = int(int(self.host.execdom0("du /var/log/ | tail -1").split()[0])/1024)
                xenrt.TEC().logverbose(varLogSize)
                
                if varLogSize > self.MAXVARLOGSIZE:
                    raise xenrt.XRTError("Failed to delete to compressed gz when /var/log/ size %sMB which is more than %sMB" %(varLogSize ,self.MAXVARLOGSIZE ))
                else:
                    xenrt.TEC().logverbose("gz files are deleted to bring down the size of /var/log size %sMB below %sMB" %(varLogSize ,self.MAXVARLOGSIZE ))
                    gzFilesNew = self.host.execdom0(cmd).split("\n")[:-1]
                    xenrt.TEC().logverbose("gz files ordered by time of creation after deletion by log handler %s" %(gzFilesNew))

                    for i in range(len(gzFilesOld)-len(gzFilesNew)):
                        gzFilesOld.pop()

                    if (gzFilesOld == gzFilesNew):
                        xenrt.TEC().logverbose("gz files are deleted in proper order by log handler %s" %(gzFilesOld))
                        break
                    else:
                        raise xenrt.XRTError("Log handler Failed to delete gz files in the proper order")
                    
            if xenrt.timenow() > deadline:
                raise xenrt.XRTFailure("Timed out while verifying the order of deletion of gz files ")
                
    def verifyRotateLiveLog(self, arglist):
    
        self.host.execdom0("cd /var/log/ && rm *.gz -f")
        
        #start thread to generate logs using syslog by writing log messages to files in /var/log/
        t = _GenerateLogs(self.host)
        t.start()
        ExpDirectories = ['/var/log/blktap/', '/var/log/installer/', '/var/log/sa/', '/var/log/samba/', '/var/log/xen/', '/var/log/openvswitch/']
        OptDirectories = ['/var/log/ntpstats/', '/var/log/audit/', '/var/log/pm/', '/var/log/cups/', '/var/log/ppp/', '/var/log/tuned/']
        DirectoriesToCheck = '/var/log /var/log/blktap /var/log/xen /var/log/openvswitch'

        ActDirectories = self.host.execdom0("ls -d /var/log/*/").split("\n")[:-1]
        xenrt.TEC().logverbose("Expected Directories in /var/log %s" %(ExpDirectories))
        xenrt.TEC().logverbose("Optional Directories in /var/log %s" %(OptDirectories))
        xenrt.TEC().logverbose("Actual Directories in /var/log %s" %(ActDirectories))
        for item in ExpDirectories:
            if item not in ActDirectories:
                raise xenrt.XRTFailure("%s expected but not present" %(item))

        for item in ActDirectories:
            if item not in ExpDirectories and item not in OptDirectories:
                raise xenrt.XRTFailure("%s not expected/optional but present" %(item))

        cmdLivelogSize = "find %s -maxdepth 1 -type f ! -name '*.tmp' ! -name '*.gz' ! -name lastlog ! -name faillog ! -name '*dmesg' ! -regex '.*\.[0-9]+'| xargs --delimiter='\n' du -m --total | tail -1 | cut -f 1" %(DirectoriesToCheck)
        #Verify if the total set of live log files(files still growing) is at least 36MB then the biggest ones will be rotated to bring the total down to 12MB or less. 
        deadline = xenrt.timenow() + self.TIMEOUT
        while True:
            liveLogSize = float(self.host.execdom0(cmdLivelogSize).split()[0])
            
            if liveLogSize >= self.MAXLIVELOGSSIZE:
                xenrt.TEC().logverbose("Size of live log files %sMB has grown above maximum limit %sMB " %(liveLogSize ,self.MAXLIVELOGSSIZE))
                
                sleep(2)
                pid = self.host.execdom0("ps aux | grep 'python /home/logspammer.py'| grep -v grep").split()[1]
                self.host.execdom0("kill -9 %s" %(pid))
                
                xenrt.TEC().logverbose("Wait for Maximum period of one minute for the live log files to get rotated")
                flag = 0
                deadlineOneMinute = xenrt.timenow() + self.MAXTIMEPERIOD
                while True:
                    liveLogSize = float(self.host.execdom0(cmdLivelogSize).split()[0])
                
                    if liveLogSize > self.MINLIVELOGSSIZE:
                        xenrt.TEC().logverbose("Size of live log files %sMB is still above expected size %sMB " %(liveLogSize ,self.MINLIVELOGSSIZE))
                        sleep(0.1)
                    else:
                        xenrt.TEC().logverbose("Size of live log files %sMB is rotated to size as expected below %sMB " %(liveLogSize ,self.MINLIVELOGSSIZE))
                        flag = 1
                        break
                    if xenrt.timenow() > deadlineOneMinute:
                        raise xenrt.XRTFailure("Total size of live log files %sMB are not rotated to bring the total down to 12MB or less beyond minute" %(liveLogSize))
                if flag:
                    break
            xenrt.TEC().logverbose("Size of live log files %sMB is still below maximum limit %sMB " %(liveLogSize ,self.MAXLIVELOGSSIZE))
            if xenrt.timenow() > deadline:
                raise xenrt.XRTFailure("Timed out while verifying live set of log files doesn't grow more than 36MB ")
            xenrt.sleep(2)

    def verifyPostRotate(self, arglist):
            """ After Rotation by rsyslog  """
            """1. Verify that new files are created after zipping the olds ones"""
            """2. Write some log lines check whether it is going to appropriate log files"""
            
            xenrt.TEC().logverbose("Verify that new files after rotating(zipping) the old ones")
            gzfilesPostRotation = self.host.execdom0("cd /var/log/ && ls -t -1 *.gz").split("\n")[:-1]
            xenrt.TEC().logverbose("gz files created post rotation %s" % gzfilesPostRotation)
            
            temp=[]
            gzfilesPostRotationNoExt=[]
            for i in range(len(gzfilesPostRotation)):
                for j in range(len(gzfilesPostRotation[i])):
                    if gzfilesPostRotation[i][j] == "." and gzfilesPostRotation[i][j+1].isdigit():
                        break
                    temp.append(gzfilesPostRotation[i][j])
                gzfilesPostRotationNoExt.append(''.join(temp))
                temp = []
            
            logFilesInVarLog = self.host.execdom0("cd /var/log/ && ls").split("\n")[:-1]
            xenrt.TEC().logverbose("gz files created post rotation without extension %s" % gzfilesPostRotationNoExt)
            xenrt.TEC().logverbose("Log files present in the /var/log  %s" % logFilesInVarLog)
            
            for item in gzfilesPostRotationNoExt:
                if item not in logFilesInVarLog:
                    raise xenrt.XRTFailure("File corresponding to %s gz file is not created after rotation " %(item))
                    
            xenrt.TEC().logverbose("write some data to logs and check it is going to appropriate files")
            t = _GenerateLogs(self.host)
            t.start()
            sleep(5)
            pid = self.host.execdom0("ps aux | grep 'python /home/logspammer.py'| grep -v grep").split()[1]
            self.host.execdom0("kill -9 %s" %(pid))
            
            expFileswithLogEntry = ['/var/log/audit.log', '/var/log/boot.log', '/var/log/daemon.log', '/var/log/maillog', '/var/log/SMlog', '/var/log/user.log', '/var/log/v6d.log', '/var/log/xcp-rrdd-plugins.log', '/var/log/xensource.log', '/var/log/xenstored-access.log']
            actFileswithLogEntry = self.host.execdom0('grep  -r "This is spam entry to increase log size" /var/log/ | cut -d: -f1 | uniq |sort').split("\n")[:-1]
            
            xenrt.TEC().logverbose("Files expected to contain the string %s" % expFileswithLogEntry)
            xenrt.TEC().logverbose("Actual Files which contain the string %s" % actFileswithLogEntry)
            
            for item in expFileswithLogEntry:
                if item not in actFileswithLogEntry:
                    raise xenrt.XRTFailure("Log Message not present in %s file when it is expected " % item)
                    
    def run(self, arglist):
        xenrt.TEC().logverbose("Verify gzipped files are deleted and in proper order when /var/log size goes beyond 500MB before next minute.")
        self.runSubcase("verifyDeleteGzFile", (arglist), "Step1", "verifyDeleteGzFile")
        
        xenrt.TEC().logverbose("Verify if the total set of live log files(files still growing) is at least 36MB then the biggest ones will be rotated to bring the total down to 12MB or less.")
        self.runSubcase("verifyRotateLiveLog", (arglist), "Step2", "verifyRotateLiveLog")
        
        xenrt.TEC().logverbose("Verify rsyslog is writing to new log files once old files are rotated.")
        self.runSubcase("verifyPostRotate", (arglist), "Step3", "verifyPostRotate")

class TC19177(TC19175):
    """Upgrade testcase to verify improved dom0 log rotation and deletion after upgrading from tampa to clearwater"""
    
    def prepare(self, arglist=None):
        old = xenrt.TEC().lookup("OLD_PRODUCT_VERSION")
        oldversion = xenrt.TEC().lookup("OLD_PRODUCT_INPUTDIR")
        
        self.host = xenrt.lib.xenserver.createHost(id=0,
                                                   version=oldversion,
                                                   productVersion=old,
                                                   withisos=True)
        # Upgrade the host
        self.host.upgrade()
    
    def run(self,arglist):
        TC19175.run(self, arglist)
