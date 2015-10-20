#
# XenRT: Test harness for Xen and the XenServer product family
#
# Workloads to be used to load VMs while running other tests.
#
# Copyright (c) Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import string, time, re, xml.dom.minidom, os, os.path, libxml2
import xenrt

__all__ = ["Burnintest",
           "Burnintest64",
           "Prime95",
           "Ping",
           "FastPing",
           "SQLIOSim",
           "NetperfTX",
           "NetperfRX",
           "LinuxNetperfTX",
           "LinuxNetperfRX",
           "LinuxSysbench",
           "DiskFind",
           "IOMeter",
           "WindowsExperienceIndex",
           "Dummy"]

class Workload(object):

    def __init__(self, guest):
        self.guest = guest
        self.name = None 
        self.process = None
        self.tarball = None
        self.cmdline = None
        self.skip = False
        self.stopped = False
        self.workdir = None
        self.rpcref = None
        self.startOnBoot = False

    def install(self, startOnBoot=False):
        if self.skip:
            xenrt.TEC().logverbose("Skipping workload %s." % (self.name))
            return
        xenrt.TEC().logverbose("Installing workload %s." % (self.name))
        self.workdir = self.guest.xmlrpcTempDir()
        if self.tarball:
            if not xenrt.checkTarball(self.tarball):
                self.skip = True
                xenrt.TEC().logverbose("Skipping workload %s due to missing "
                                       "tarball." % (self.name))
                return
            self.guest.xmlrpcUnpackTarball("%s/%s" %
                                        (xenrt.TEC().lookup("TEST_TARBALL_BASE"),
                                        (self.tarball)),
                                         self.workdir)
        if startOnBoot:
            self.startOnBoot = True
            # Write command line to startup folder
            data = "@echo off\n%s\n" % (string.replace(self.cmdline,
                                                     "%s",
                                                     self.workdir))
            startupPath = self.guest.xmlrpcGetEnvVar("ALLUSERSPROFILE") + "\\start menu\\programs\\startup"
            if not self.guest.xmlrpcFileExists(startupPath):
                raise xenrt.XRTFailure("Start up path for guest is invalid: %s" % startupPath)

            self.guest.xmlrpcWriteFile("%s\\XRT_%s_%s.bat" % (startupPath, 
                                           self.name, self.workdir.split("\\")[-1]), data)
            

    def start(self):
        if self.skip:
            xenrt.TEC().logverbose("Skipping workload %s." % (self.name))
            return
        if self.startOnBoot:
            raise xenrt.XRTError("Cannot start workload %s (set to start on "
                                 "boot)" % (self.name))
        xenrt.TEC().logverbose("Starting workload %s." % (self.name))
        self.install()
        self.rpcref = self.guest.xmlrpcStart(string.replace(self.cmdline,
                                                            "%s",
                                                            self.workdir))
        try:
            xenrt.TEC().logverbose("Memory details: %s" % 
                                   (self.guest.getMyMemory(complete=True)))
        except:
            pass
        time.sleep(5)
        if not self.process in map(string.lower, self.guest.xmlrpcPS()):
            message = "%s failed to start." % (self.name)
            if xenrt.TEC().lookup("SRM_STRICT", False, boolean=True):
                raise xenrt.XRTError(message)
            xenrt.TEC().warning(message)

    def stop(self):
        if self.skip:
            return
        if self.stopped:
            return
        if self.startOnBoot:
            raise xenrt.XRTError("Cannot stop workload %s (set to start on "
                                 "boot)" % (self.name))
        xenrt.TEC().logverbose("Stopping workload %s." % self.name)
        if self.rpcref:
            try:
                logdata = self.guest.xmlrpcLog(self.rpcref)
                f = file("%s/%s-cmd-output.txt" %
                         (xenrt.TEC().getLogdir(), self.name), 'w')
                f.write(logdata)
                f.close()
            except Exception, e:
                message = "Exception fetching %s log: %s" % (self.name, str(e))
                if xenrt.TEC().lookup("SRM_STRICT", False, boolean=True):
                    raise xenrt.XRTError(message)
                xenrt.TEC().warning(message)
        self.stopped = True
        if not self.process in map(string.lower, self.guest.xmlrpcPS()):
            if xenrt.TEC().tc.getResult(code=True) == xenrt.RESULT_UNKNOWN:
                xenrt.TEC().tc.setResult(xenrt.RESULT_PARTIAL)
            xenrt.TEC().reason("%s no longer running." % (self.name))
        try:
            self.guest.xmlrpcKillAll(self.process)
        except:
            message = "Error killing %s." % (self.name)
            if xenrt.TEC().lookup("SRM_STRICT", False, boolean=True):
                raise xenrt.XRTError(message)
            xenrt.TEC().warning(message)
        time.sleep(5)
        try:
            if self.process in map(string.lower, self.guest.xmlrpcPS()):
                message = "%s failed to die." % (self.name)
                if xenrt.TEC().lookup("SRM_STRICT", False, boolean=True):
                    raise xenrt.XRTError(message)
                xenrt.TEC().warning(message)
        except xenrt.XRTException, e:
            raise e
        except:
            xenrt.TEC().warning("Exception checking for %s death" %
                                (self.name))
        self.check()

    def check(self):
        pass

    def checkRunning(self):
        return (self.process in map(string.lower, self.guest.xmlrpcPS()))

    def __str__(self):
        return str(self.name)

class LinuxWorkload(Workload):

    def kill(self):
        self.guest.execguest("killall %s" % (self.process))

    def install(self, startOnBoot=False):
        if self.skip:
            xenrt.TEC().logverbose("Skipping workload %s." % (self.name))
            return
        xenrt.TEC().logverbose("Installing workload %s." % (self.name))
        self.workdir = self.guest.execguest("mktemp -d /tmp/workXXXXXX").strip()
        if self.tarball:
            if not xenrt.checkTarball(self.tarball):
                self.skip = True
                xenrt.TEC().logverbose("Skipping workload %s due to missing "
                                       "tarball." % (self.name))
                return
            self.guest.execguest("wget '%s/%s' -O - | tar -zx -C %s" %
                                 (xenrt.TEC().lookup("TEST_TARBALL_BASE"),
                                  self.tarball,
                                  self.workdir))
            self.workdir = "%s/%s" % (self.workdir, self.tarball.split(".")[0])

        if startOnBoot:
            self.startOnBoot = True
            # Write command line into /etc/rc.local
            self.guest.runOnStartup(string.replace(self.cmdline,
                                                   "%s",
                                                   self.workdir))

    def start(self):
        if self.skip:
            xenrt.TEC().logverbose("Skipping workload %s." % (self.name))
            return
        if self.startOnBoot:
            raise xenrt.XRTError("Cannot start workload %s (set to start on "
                                 "boot)" % (self.name))
        xenrt.TEC().logverbose("Starting workload %s." % (self.name))
        self.install()
        self.guest.execguest(string.replace(self.cmdline,
                                           "%s",
                                            self.workdir))    
        time.sleep(5)
        if not re.search(self.process, self.guest.execguest("ps ax",timeout=600)):
            message = "%s failed to start." % (self.name)
            if xenrt.TEC().lookup("SRM_STRICT", False, boolean=True):
                raise xenrt.XRTError(message)
            xenrt.TEC().warning(message)

    def stop(self):
        if self.skip:
            return
        if self.stopped:
            return
        if self.startOnBoot:
            raise xenrt.XRTError("Cannot stop workload %s (set to start on "
                                 "boot)" % (self.name))
        self.stopped = True
        xenrt.TEC().logverbose("Stopping workload %s." % self.name)
        if not re.search(self.process, self.guest.execguest("ps ax")):
            if xenrt.TEC().tc.getResult(code=True) == xenrt.RESULT_UNKNOWN:
                xenrt.TEC().tc.setResult(xenrt.RESULT_PARTIAL)
            xenrt.TEC().reason("%s no longer running." % (self.name))
        try:
            self.kill()
        except:
            message = "Error killing %s." % (self.name)
            if xenrt.TEC().lookup("SRM_STRICT", False, boolean=True):
                raise xenrt.XRTError(message)
            xenrt.TEC().warning(message)
        try:
            if re.search(self.process, self.guest.execguest("ps ax")):
                message = "%s failed to die." % (self.name)
                if xenrt.TEC().lookup("SRM_STRICT", False, boolean=True):
                    raise xenrt.XRTError(message)
                xenrt.TEC().warning(message)
        except xenrt.XRTException, e:
            raise e
        except:
            xenrt.TEC().warning("Exception checking for %s death" %
                                (self.name))
        self.check()

    def checkRunning(self):
        return re.search(self.process, self.guest.execguest("ps ax"))

class LinuxTimeCheck(LinuxWorkload):

    def __init__(self, guest):
        LinuxWorkload.__init__(self, guest)
        self.name = "TimeCheck"
        self.process = "checktime.py"
        self.cmdline = "%s/checktime.py &> %s/times.log &"
        self.tarball = "checktime.tgz"

    def install(self, startOnBoot=False):
        if self.skip:
            xenrt.TEC().logverbose("Skipping workload %s." % (self.name))
            return
        xenrt.TEC().logverbose("Installing workload %s." % (self.name))
        self.workdir = self.guest.execguest("mktemp -d /tmp/workXXXXXX").strip()

        sftp = self.guest.sftpClient()
        t = xenrt.TempDirectory()

        script = """#!/usr/bin/env python

import time

interval = 0.1

while True:
    print time.time()
    time.sleep(interval)
"""
        file("%s/checktime.py" % (t.path()), "w").write(script)
        sftp.copyTo("%s/checktime.py" % (t.path()), 
                    "%s/checktime.py" % (self.workdir))              
        self.guest.execguest("chmod +x %s/checktime.py" % 
                             (self.workdir))

    def kill(self):
        data = self.guest.execguest("ps ax")
        pid = re.search("([0-9]+).*%s" % (self.process), data).group(1)
        self.guest.execguest("kill -9 %s" % (pid))
    
    def check(self):
        data = self.guest.execguest("cat %s/times.log" % (self.workdir))
        data = map(float, data.split()) 
        # Ignore the last entry because it might not be complete.
        for i in range(len(data) - 2):
            if not data[i+1] > data[i]:
                if xenrt.TEC().lookup("SRM_STRICT", False, boolean=True):
                    raise xenrt.XRTError("Time not increasing. (%s =< %s)" %
                                         (data[i+1], data[i]))
                xenrt.TEC().warning("Time not increasing. (%s =< %s)" %
                                    (data[i+1], data[i]))
                
class LinuxNetperfTX(LinuxWorkload):
    
    def __init__(self, guest):    
        LinuxWorkload.__init__(self, guest)
        self.name = "NetperfTX"
        self.process = "netperf"

        self.guest.installNetperf()
        try:
            peer = xenrt.NetworkTestPeer(shared=True, blocking=False)
        except:
            xenrt.TEC().warning("Not running NetperfTX workload")
            self.skip = True
            return
        # Find the netperf path
        if self.guest.execguest("test -e /usr/local/bin/netperf",
                              retval="code") == 0:
            path = "/usr/local/bin"
        elif self.guest.execguest("test -e /usr/bin/netperf",
                                retval="code") == 0:
            path = "/usr/bin"
        else:
            raise xenrt.XRTError("Cannot find netperf binary")
        self.cmdline = "%s/netperf -H %s -l 1000000 >/dev/null 2>&1 " \
                       "< /dev/null &" % (path,peer.getAddress(guest=self.guest))

class LinuxNetperfRX(LinuxWorkload):
    
    def __init__(self, guest):    
        Workload.__init__(self, guest)
        self.name = "NetperfRX"
        self.process = "netperf"

        self.guest.installNetperf()
        try:
            peer = xenrt.NetworkTestPeer(shared=True, blocking=False)
        except:
            xenrt.TEC().warning("Not running NetperfRX workload")
            self.skip = True
            return
        # Find the netperf path
        if self.guest.execguest("test -e /usr/local/bin/netperf",
                                retval="code") == 0:
            path = "/usr/local/bin"
        elif self.guest.execguest("test -e /usr/bin/netperf",
                                  retval="code") == 0:
            path = "/usr/bin"
        else:
            raise xenrt.XRTError("Cannot find netperf binary")
        self.cmdline = "%s/netperf -t TCP_MAERTS -H %s -l 1000000 >/dev/null " \
                       "2>&1 < /dev/null &" % (path,peer.getAddress(guest=self.guest))

class LinuxSysbench(LinuxWorkload):

    def __init__(self, guest):
        LinuxWorkload.__init__(self, guest)
        self.name = "LinuxSysbench"
        self.tarball = "sysbench.tgz"
        self.process = "sysbench"

        # For now just use the memory test
        self.cmdline = "/usr/local/bin/sysbench --test=memory " \
                       "--memory-total-size=100T run >/dev/null " \
                       "2>&1 < /dev/null &"

    def install(self, startOnBoot=False):
        LinuxWorkload.install(self, startOnBoot)

        # Install sysbench
        self.guest.execguest("cd %s && ./configure --without-mysql" %
                             (self.workdir))
        self.guest.execguest("cd %s && make" % (self.workdir))
        self.guest.execguest("cd %s && make install" % (self.workdir))

class FIOLinux(LinuxWorkload):
    def __init__(self, guest):
        LinuxWorkload.__init__(self, guest)
        self.name = "FIOLinux"
        self.tarball = "fiowin.tgz"
        self.process = "fio"
        self.cmdline = "at now -f /root/startfio.sh" 

    def install(self, startOnBoot=False):
        LinuxWorkload.install(self, startOnBoot)
        if self.guest.execguest("test -e /etc/debian_version", retval="code") == 0:
            self.guest.execguest("apt-get install -y --force-yes zlib1g-dev")
        elif self.guest.execguest("test -e /etc/redhat-release", retval="code") == 0:
            self.guest.execguest("yum install -y zlib-devel")
        else:
            raise xenrt.XRTError("Guest is not supported")
        self.guest.execguest("cd %s/src && ./configure" % self.workdir)
        self.guest.execguest("cd %s/src && make" % self.workdir)
        self.guest.execguest("cd %s/src && make install" % self.workdir)
        inifile = """[workload]
rw=randrw
size=512m
runtime=1382400
time_based
numjobs=4
"""
        t = xenrt.TempDirectory()
        sftp = self.guest.sftpClient()
        file("%s/workload.fio" % (t.path()), "w").write(inifile)
        sftp.copyTo("%s/workload.fio" % (t.path()), "/root/workload.fio")
        self.guest.execguest("echo 'fio /root/workload.fio' > /root/startfio.sh")
        self.guest.execguest("chmod a+x /root/startfio.sh")
        

class Burnintest(Workload):
    
    def __init__(self, guest):
        Workload.__init__(self, guest)
        if guest.xmlrpcGetArch() == "amd64":
            self.name = "burnintest64"
            self.tarball = "burnintest64.tgz"
            self.process = "bit.exe"
            self.cmdline = "cd %s\\burnintest64\n" + \
                           "bit.exe -p -C %s\\burnintest64\\"+ self._configFileName() + " -R -X"
        else:
            self.name = "burnintest"
            self.tarball = "burnintest.tgz"
            self.process = "bit.exe"
            self.cmdline = "cd %s\\burnintest\n" + \
                           "bit.exe -C %s\\burnintest\\" + self._configFileName() + " -R -x"
    
    def _configFileName(self):
        return "72hours.bitcfg"

class BurnintestGraphics(Burnintest):
    def __init__(self, guest):
        Burnintest.__init__(self, guest)
        
    def _configFileName(self):
        return "3DaysIncGraphics.bitcfg"

class TimeCheck(Workload):

    def __init__(self, guest):
        Workload.__init__(self, guest)
        self.name = "TimeCheck"
        self.process = "cscript.exe"
        self.cmdline = "cscript /nologo %s\\checktime.vbs > %s\\times.log"

    def install(self, startOnBoot=False):
        if self.skip:
            xenrt.TEC().logverbose("Skipping workload %s." % (self.name))
            return
        xenrt.TEC().logverbose("Installing workload %s." % (self.name))
        self.workdir = self.guest.xmlrpcTempDir()
        script = r"""Set WMI = GetObject("winmgmts:{impersonationlevel=impersonate}!\\.\root\cimv2")
While True
    Set DATA = WMI.ExecQuery("Select * from Win32_OperatingSystem")
    For Each D in DATA
        WScript.Echo D.LocalDateTime
    Next
    WScript.Sleep(100)
Wend
"""
        self.guest.xmlrpcWriteFile("%s/checktime.vbs" % (self.workdir), script)
    
    def check(self):
        data = self.guest.xmlrpcReadFile("%s/times.log" % (self.workdir))
        data = map(float, [ re.sub("\+.*", "", x) for x in data.split() ]) 
        # Ignore the last entry because it might not be complete.
        for i in range(len(data) - 2):
            if not data[i+1] > data[i]:
                if xenrt.TEC().lookup("SRM_STRICT", False, boolean=True):
                    raise xenrt.XRTError("Time not increasing. (%s =< %s)" %
                                         (data[i+1], data[i]))
                xenrt.TEC().warning("Time not increasing. (%s =< %s)" %
                                    (data[i+1], data[i]))

class Prime95(Workload):

    def __init__(self, guest):
        Workload.__init__(self, guest)
        self.name = "Prime95"
        self.tarball = "prime95.tgz"
        self.process = "prime95.exe"
        self.cmdline = "cd %s\\prime95\n" + \
                       "copy fft.ini prime.ini\n" + \
                       "prime95.exe -t"

    def check(self):
        if self.workdir:
            try:
                data = self.guest.xmlrpcReadFile("%s\\prime95\\results.txt" %
                                                 (self.workdir))
                f = file("%s/workload_Prime95_results.txt" %
                         (xenrt.TEC().getLogdir()), 'w')
                f.write(data)
                f.close()
                for line in string.split(data, "\n"):
                    r = re.search(r"^FATAL ERROR:\s*(.+)$", line)
                    if r:
                        xenrt.TEC().warning("Prime95 error '%s'" %
                                            (r.group(1)))
            except Exception, e:
                xenrt.TEC().logverbose("Exception checking Prime95: %s" % (str(e)))
    
class Ping(Workload):

    def __init__(self, guest):    
        Workload.__init__(self, guest)
        self.name = "Ping"
        self.tarball = None
        self.process = "ping.exe"

        # Try and get the gateway address of the VM
        gatewayAddr = None
        if guest.usesLegacyDrivers():
            data = self.guest.xmlrpcExec("ipconfig", returndata=True)
            gatewayAddr = re.search("Default Gateway[ :\.]+([0-9\.]+)", data).group(1)
            xenrt.TEC().logverbose('Found gateway address using ipconfig: %s' % (gatewayAddr))
            if not re.match('\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', gatewayAddr):
                raise xenrt.XRTError('Failed to get valid gateway address for guest: %s' % (self.guest.getName()))
        else:
            data = self.guest.getWindowsNetshConfig('netsh interface ipv4 show address')
            interfacesWithGateways = filter(lambda x:data[x].has_key('Default Gateway'), data.keys())
            if len(interfacesWithGateways) > 0:
                xenrt.TEC().logverbose('Using Gateway Address %s from interface: %s' % (data[interfacesWithGateways[0]]['Default Gateway'], interfacesWithGateways[0]))
                gatewayAddr = data[interfacesWithGateways[0]]['Default Gateway']
            else:
                raise xenrt.XRTError('Failed to get valid gateway address for guest: %s' % (self.guest.getName()))

        self.cmdline = "ping -t %s" % (gatewayAddr)

class FastPing(Workload):

    def __init__(self, guest):
        Workload.__init__(self, guest)
        self.name = "Fping"
        self.tarball = "fping.tgz"
        self.process = "fping.exe"

        # Try and get the gateway address of the VM
        gatewayAddr = None
        if guest.usesLegacyDrivers():
            data = self.guest.xmlrpcExec("ipconfig", returndata=True)
            gatewayAddr = re.search("Default Gateway[ :\.]+([0-9\.]+)", data).group(1)
            xenrt.TEC().logverbose('Found gateway address using ipconfig: %s' % (gatewayAddr))
            if not re.match('\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', gatewayAddr):
                raise xenrt.XRTError('Failed to get valid gateway address for guest: %s' % (self.guest.getName()))
        else:
            data = self.guest.getWindowsNetshConfig('netsh interface ipv4 show address')
            interfacesWithGateways = filter(lambda x:data[x].has_key('Default Gateway'), data.keys())
            if len(interfacesWithGateways) > 0:
                xenrt.TEC().logverbose('Using Gateway Address %s from interface: %s' % (data[interfacesWithGateways[0]]['Default Gateway'], interfacesWithGateways[0]))
                gatewayAddr = data[interfacesWithGateways[0]]['Default Gateway']
            else:
                raise xenrt.XRTError('Failed to get valid gateway address for guest: %s' % (self.guest.getName()))

        self.cmdline = "%%s\\fping\\Fping.exe %s -c -t 100" % (gatewayAddr)


class SQLIOSim(Workload):

    def __init__(self, guest):    
        Workload.__init__(self, guest)
        self.name = "SQLIOSim"
        self.tarball = "sqliosim.tgz"
        self.process = "sqliosim.com"
        self.cmdline = "cd %s\\sqliosim\n" \
                       "%PROCESSOR_ARCHITECTURE%\\sqliosim.com -d 1000000"
        self.allowedErrs = ["Unable to get disk cache info for c:\\"]
        if guest.xmlrpcGetArch() == "amd64":
            self.skip = True

    def check(self):
        time.sleep(5)
        if self.workdir:
            try:
                data = self.guest.xmlrpcReadFile("%s\\sqliosim\\sqliosim.log.xml" %
                                                 (self.workdir))
                f = file("%s/workload_sqliosim.log.xml" %
                         (xenrt.TEC().getLogdir()), 'w')
                f.write(data)
                f.close()

                # Parse for errors
                dom = xml.dom.minidom.parse("%s/workload_sqliosim.log.xml" %
                                            (xenrt.TEC().getLogdir()))
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

            except xenrt.XRTException, e:
                if xenrt.TEC().lookup("SRM_STRICT", False, boolean=True):
                    raise xenrt.XRTError(e.reason)                
                else:
                    xenrt.TEC().warning(e.reason)

class NetperfTX(Workload):

    def __init__(self, guest):    
        Workload.__init__(self, guest)
        self.name = "NetperfTX"
        self.process = "netperf.exe"

        if guest.xmlrpcGetArch() == "amd64":
            self.skip = True
            return
        if guest.xmlrpcWindowsVersion() == "5.0":
            self.skip = True
            return

        self.guest.installNetperf()
        try:
            peer = xenrt.NetworkTestPeer(shared=True, blocking=False)
        except:
            xenrt.TEC().warning("Not running NetperfTX workload")
            self.skip = True
            return
        self.cmdline = "c:\\netperf.exe -H %s -l 1000000" % \
                       (peer.getAddress(guest=self.guest))

class NetperfRX(Workload):

    def __init__(self, guest):    
        Workload.__init__(self, guest)
        self.name = "NetperfRX"
        self.process = "netperfrx.exe"

        if guest.xmlrpcGetArch() == "amd64":
            self.skip = True
            return
        if guest.xmlrpcWindowsVersion() == "5.0":
            self.skip = True
            return
            
        self.guest.installNetperf()
        try:
            self.guest.xmlrpcExec("copy c:\\netperf.exe c:\\netperfrx.exe")
        except:
            pass
        try:
            peer = xenrt.NetworkTestPeer(shared=True, blocking=False)
        except:
            xenrt.TEC().warning("Not running NetperfRX workload")
            self.skip = True
            return
        self.cmdline = "c:\\netperfrx.exe -t TCP_MAERTS -H %s -l 1000000" % \
                       (peer.getAddress(guest=self.guest))
        
class Memtest(Workload):

    def __init__(self, guest):    
        Workload.__init__(self, guest)
        self.name = "Memtest"
        self.tarball = "memtest.tgz"
        self.process = "memtest.exe"
        self.cmdline = "%s\\memtest\\memtest.exe 200"

class DiskFind(Workload):

    def __init__(self,guest):
        Workload.__init__(self, guest)
        self.name = "DiskFind"
        self.tarball = "diskfind.tgz"
        self.process = "diskfind.bat"
        self.cmdline = "%s\\diskfind\\diskfind.bat"

class IOMeter(Workload):

    def __init__(self, guest):
        Workload.__init__(self, guest)
        self.name = "iometer"
        self.tarball = "iometer.tgz"
        self.process = "iometer.exe"
        self.cmdline = "cd %s\\iometer\n" + \
                       "%s\\iometer\\iometer.exe /c workload\\workload.icf " + \
                       "/r ..\\workload.csv\n"

    def install(self, startOnBoot=False):
        Workload.install(self, startOnBoot)
        guest = self.guest
        # registry settings
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
        # firewall
        try:
            guest.xmlrpcExec('NETSH firewall set allowedprogram '
                             'program="%s\\iometer\\iometer.exe" '
                             'name="Iometer Control/GUI" mode=ENABLE' %
                             (self.workdir))
        except:
            xenrt.TEC().comment("Error disabling firewall")
        try:
            guest.xmlrpcExec('NETSH firewall set allowedprogram '
                             'program="%s\\iometer\\dynamo.exe" '
                             'name="Iometer Workload Generator" mode=ENABLE' %
                             (self.workdir))
        except:
            xenrt.TEC().comment("Error disabling firewall")

class FIOWindows(Workload):
    def __init__(self, guest, drive=None):
        Workload.__init__(self, guest)
        self.name = "fio"
        self.process = "fio.exe"
        if self.guest.distro.endswith("x64"):
            arch = "x64"
        else:
            arch = "x86"
        self.drive = drive
        self.cmdline = "c:\\fiowin\\%s\\fio.exe c:\\workload.fio" % arch

    def install(self, startOnBoot=False):
        Workload.install(self, startOnBoot)
        inifile = """[workload]
rw=randrw
size=512m
runtime=1382400
time_based
numjobs=4
"""
        if self.drive:
            inifile += "directory=%s\\:\\\n" % self.drive
        self.guest.xmlrpcWriteFile("c:\\workload.fio", inifile) 
        self.guest.xmlrpcUnpackTarball("%s/fiowin.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")

    def runCheck(self):
        inifile = """[check]
rw=rw
size=512m
numjobs=4
"""
        if self.drive:
            inifile += "directory=%s\\:\\\n" % self.drive
        self.guest.xmlrpcWriteFile("c:\\check.fio", inifile) 
        self.guest.xmlrpcExec(self.cmdline.replace("workload", "check"), timeout=3600)

class WindowsExperienceIndex(Workload):

    """ Run WinSAT/WEI and obtain result in xml format. """    

    availDistros = [
                "win7-x86", "win7-x64", "win7sp1-x86", "win7sp1-x64", # Windows 7
                "win8-x86", "win8-x64", "win81-x86", "win81-x64", # Windows 8.x
                "ws08r2-x64", "ws08r2dc-x64", "ws08r2sp1-x64", "ws08r2dcsp1-x64", # Windows Server 2008 R2
                "ws12-x64", "ws12dc-x64", "ws12r2-x64" #Windows Server 2012. Note core is not supported.
                ]

    def __init__(self, guest, distro = None):
        Workload.__init__(self, guest)
        if distro:
            self.distro = distro
        elif guest.distro:
            self.distro = guest.distro
        else:
            self.distro = "unknown"
        self.pid = None
        self.logfiles = None

    def install(self, startOnBoot = False):
        if not self.distro in self.availDistros:
            raise xenrt.XRTError("Windows Experience Index requires Windows 7 or later and Windows Server 2008 R2 or later.\n'%s' distro found." % (self.distro))

        # Servers do not have WEI software and are not running 'formal' option.
        if self.isWindowsServer():
            wsprefix = ""
            if self.distro.startswith("ws08"):
                wsprefix = "win7"
            else:
                wsprefix = "win8"
            if self.distro.endswith("x64"):
                wsprefix += "-x64-"
            elif self.distro.endswith("x86"):
                wsprefix += "-x86-"
            self.guest.xmlrpcUnpackTarball("%s/winsat.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")
            self.guest.xmlrpcExec("copy /V /Y C:\\winsat\\%sWinSAT.exe C:\\Windows\\System32\\WinSAT.exe" % (wsprefix))
            self.guest.xmlrpcExec("copy /V /Y C:\\winsat\\%sWinSATAPI.dll C:\\Windows\\System32\\WinSATAPI.dll" % (wsprefix))

    def isWindowsServer(self):
        if self.distro.startswith("ws"):
            return True
        return False

    def availableDistros(self):
        return self.availDistros

    def start(self):
        if self.isWindowsServer():
            self.guest.xmlrpcWriteFile("C:\\runwei.bat", """
call WinSAT.exe d3d -xml C:\winsat_d3d.xml
call WinSAT.exe dwm -xml C:\winsat_dwm.xml
exit /b %%errorlevel%%
""")
            self.pid = self.guest.xmlrpcStart("C:\\runwei.bat")
        else:
            self.pid = self.guest.xmlrpcStart("WinSAT.exe formal -xml C:\\winsat_formal.xml")

    def stop(self):
        if self.pid and self.guest:
            self.guest.xmlrpcKill(self.pid)

    def check(self):
        if self.checkRunning() or not self.guest:
            return None

        #returnCode = self.guest.xmlrpcReturnCode(self.pid)
        #if returnCode != 0:
            #if self.isWindowsServer():
                #raise xenrt.XRTError("WinSAT with dwm option returned %d. (distro: %s)" % (returnCode, self.distro))
            #else:
                #raise xenrt.XRTError("WinSAT with formal option returned %d. (distro: %s)" % (returnCode, self.distro))

        xenrt.TEC().logverbose("Obtained %d results files" % self.obtainResult())
        return self.analyseResult()

    def checkRunning(self):
        if self.pid and self.guest:
            return not self.guest.xmlrpcPoll(self.pid)
        else:
            return False

    def obtainResult(self):
        # Obtaining result files.
        weixmlfiles = ["winsat_formal.xml", "winsat_d3d.xml", "winsat_dwm.xml"]
        self.logfiles = []
        vmprefix = "C:\\"
        logdir = "%s/%s" % (xenrt.TEC().getLogdir(), self.guest.getName())
        if not os.path.exists(logdir):
            os.makedirs(logdir)
        for basename in weixmlfiles:
            filename = vmprefix + basename
            if self.guest.xmlrpcFileExists(filename):
                logpath = "%s/%s" % (logdir, basename)
                self.guest.xmlrpcGetFile(filename, logpath)
                self.logfiles.append(logpath)

        return len(self.logfiles)

    def analyseResult(self):
        # Analyse and return result.
        result = []
        xenrt.TEC().logverbose("Analysing %d results" % len(self.logfiles))
        for log in self.logfiles:
            xenrt.TEC().logverbose("Analysing log file: %s" % log)
            fp = file(log, "r")
            xmldata = fp.read().decode("utf-16").encode("utf-8")
            fp.close()
            
            xmldata = xmldata.replace("UTF-16", "UTF-8")
            xmltree = libxml2.parseDoc(xmldata)
            graphicsscores = [x.getContent() for x in xmltree.xpathEval("WinSAT/WinSPR/GraphicsScore")]
            for score in graphicsscores:
                result.append(("GraphicsScore", score))
            gamingscores = [x.getContent() for x in xmltree.xpathEval("WinSAT/WinSPR/GamingScore")]
            for score in gamingscores:
                result.append(("GamingScore", score))

        return result

    def __str__(self):
        return "WindowsExperienceIndex workload."

class Dummy(Workload):

    def __init__(self,guest):
        Workload.__init__(self, guest)
        self.skip = True

