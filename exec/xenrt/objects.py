
#
# XenRT: Test harness for Xen and the XenServer product family
#
# Abstract classes representing objects we can manipulate
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, time, socket, re, os.path, os, shutil, random, sets, math
import traceback, xmlrpclib, crypt, glob, copy, httplib, urllib, mimetools
import xml.dom.minidom, threading, fnmatch, urlparse, libxml2
import xenrt, xenrt.ssh, xenrt.util, xenrt.rootops, xenrt.resources
import testcases.benchmarks.workloads
import bz2, simplejson, json
import IPy
import XenAPI
import ssl
import xml.etree.ElementTree as ET
from xenrt.lazylog import log, warning, step
from xenrt.linuxanswerfiles import *

from zope.interface import implements

#Dummy import of _strptime module
#This is done to import this module before the threads do this - which causes CA-137801 - because _strptime is not threadsafe
time.strptime('2014-06-12','%Y-%m-%d')
#End dummy import

__all__ = ["GenericPlace", "GenericHost", "NetPeerHost", "GenericGuest", "productLib",
           "RunOnLocation", "ActiveDirectoryServer", "PAMServer", "CVSMServer", "WlbApplianceFactory",
           "WlbApplianceServer", "WlbApplianceServerHVM", "DLVMApplianceFactory", "DemoLinuxVM", 
           "DemoLinuxVMHVM", "ConversionManagerApplianceFactory",
           "ConversionApplianceServer", "ConversionApplianceServerHVM", "EventObserver",
           "XenMobileApplianceServer", "_WinPEBase"]

class MyHTTPConnection(httplib.HTTPConnection):
    XENRT_SOCKET_TIMEOUT = 600

    # Borrowed from python 2.6 library
    def connect(self):
        """Connect to the host and port specified in __init__."""
        self.timeout =  self.XENRT_SOCKET_TIMEOUT
        self.sock = socket.create_connection((self.host, self.port),
                                             self.timeout)
        if self._tunnel_host:
            self._tunnel()

class MyReallyImpatientHTTPConnection(MyHTTPConnection):
    XENRT_SOCKET_TIMEOUT = 5

class MyImpatientHTTPConnection(MyHTTPConnection):
    XENRT_SOCKET_TIMEOUT = 30

class MyPatientHTTPConnection(MyHTTPConnection):
    XENRT_SOCKET_TIMEOUT = 86400

class MyHTTP(httplib.HTTP):

    _connection_class = MyHTTPConnection

class MyReallyImpatientHTTP(httplib.HTTP):

    _connection_class = MyReallyImpatientHTTPConnection

class MyImpatientHTTP(httplib.HTTP):

    _connection_class = MyImpatientHTTPConnection

class MyPatientHTTP(httplib.HTTP):

    _connection_class = MyPatientHTTPConnection

def transportCompatMode():
    return sys.version_info[0] <=2 and sys.version_info[1] <=6

class MyTrans(xmlrpclib.Transport):

    # Borrowed from python 2.3 library
    @xenrt.irregularName
    def make_connection(self, host):
        # create a HTTP connection object from a host descriptor
        host, extra_headers, x509 = self.get_host_info(host)
        if transportCompatMode():
            return MyHTTP(host)
        else:
            return MyHTTPConnection(host)

class MyReallyImpatientTrans(xmlrpclib.Transport):

    # Borrowed from python 2.3 library
    @xenrt.irregularName
    def make_connection(self, host):
        # create a HTTP connection object from a host descriptor
        host, extra_headers, x509 = self.get_host_info(host)
        if transportCompatMode():
            return MyReallyImpatientHTTP(host)
        else:
            return MyReallyImpatientHTTPConnection(host)

class MyImpatientTrans(xmlrpclib.Transport):

    # Borrowed from python 2.3 library
    @xenrt.irregularName
    def make_connection(self, host):
        # create a HTTP connection object from a host descriptor
        host, extra_headers, x509 = self.get_host_info(host)
        if transportCompatMode():
            return MyImpatientHTTP(host)
        else:
            return MyImpatientHTTPConnection(host)

class MyPatientTrans(xmlrpclib.Transport):

    # Borrowed from python 2.3 library
    @xenrt.irregularName
    def make_connection(self, host):
        # create a HTTP connection object from a host descriptor
        host, extra_headers, x509 = self.get_host_info(host)
        if transportCompatMode():
            return MyPatientHTTP(host)
        else:
            return MyPatientHTTPConnection(host)

def productLib(productType=None, host=None, hostname=None):
    if hostname and not host and not productType:
        host = xenrt.TEC().registry.hostGet(hostname)
    if host and not productType:
        productType = host.productType

    if productType in ["unknown", "xenserver"]:
        return xenrt.lib.xenserver
    elif productType == "kvm":
        return xenrt.lib.kvm
    if productType in ["esx"]:
        return xenrt.lib.esx
    if productType == "hyperv":
        return xenrt.lib.hyperv
    else:
        raise xenrt.XRTError("Unknown productType %s" % (productType, ))

class GenericPlace(object):

    LINUX_INTERFACE_PREFIX = "eth"

    def __init__(self):
        self.password = None
        self.guestconsolelogs = None
        self.windows = False
        self.hasSSH = True
        self.distro = None
        self.arch = None
        self.thingsWeHaveReported = []
        self.uuid = None
        self.special = {}
        self.extraLogsToFetch = None
        self.logFetchExclude = None
        self.mylock = threading.Lock()
        self.skipNextCrashdump = False
        self.vifstem = "eth"
        self.host = None
        self.memory = None
        self.vcpus = None
        self._os = None

    def populateSubclass(self, x):
        x.password = self.password
        x.guestconsolelogs = self.guestconsolelogs
        x.windows = self.windows
        x.distro = self.distro
        x.arch = self.arch
        x.thingsWeHaveReported = self.thingsWeHaveReported
        x.special.update(self.special)
        x.extraLogsToFetch = self.extraLogsToFetch
        x.logFetchExclude = self.logFetchExclude
        x.vifstem = self.vifstem
        x._os = self._os

    def compareConfig(self, other):
        """Compare the configuration of this place to another place. This
        is limited to the major parameters modelled by this library. Any
        differences will cause a XRTFailure to be raised.
        """
        if self.windows != other.windows:
            raise xenrt.XRTFailure("Windows flag mismatch",
                                   "%s:%s %s:%s" % (self.getName(),
                                                    str(self.windows),
                                                    other.getName(),
                                                    str(other.windows)))

    @property
    def os(self):
        if not self._os:
            if self.distro:
                if self.windows or not self.arch:
                    osdistro = self.distro
                else:
                    osdistro = "%s_%s" % (self.distro, self.arch)

                self._os = xenrt.lib.opsys.osFactory(osdistro, self, self.password)
            else:
                self._os = xenrt.lib.opsys.osFromExisting(self, self.password)
                self.password = self._os.password
                self.distro = self._os.distro
        return self._os

    def _clearObjectCache(self):
        """Remove cached object data."""
        self.uuid = None

    def getIP(self):
        raise xenrt.XRTError("Unimplemented")

    def getName(self):
        raise xenrt.XRTError("Unimplemented")

    def paramGet(self, paramName, paramKey=None):
        raise xenrt.XRTError("Unimplemented")

    def tailor(self):
        raise xenrt.XRTError("Unimplemented")

    def createScaleXtremeEnvironment(self):
        raise xenrt.XRTError("Unimplemented")

    def execdom0(self,
                 command,
                 username=None,
                 retval="string",
                 level=xenrt.RC_FAIL,
                 timeout=300,
                 idempotent=False,
                 newlineok=False,
                 nolog=False,
                 outfile=None,
                 useThread=False,
                 password=None):
        raise xenrt.XRTError("Unimplemented")

    def execguest(self,
                  command,
                  username=None,
                  retval="string",
                  level=xenrt.RC_FAIL,
                  timeout=300,
                  idempotent=False,
                  newlineok=False,
                  getreply=True,
                  nolog=False,
                  outfile=None,
                  password=None):
        raise xenrt.XRTError("Unimplemented")

    def getBasicArch(self):
        if self.arch == "x86-64":
            barch = self.arch
        else:
            barch = "x86-32"
        return barch

    def getMyMemory(self):
        """ This is how an OS inside a guest VM thinks about its physical
        memory. The figure is quite likely to be the same as the one used for
        VM creation (an integral metabytes) despite the actual memory (as
        obtained via "memory-actual") can be smaller.
        """
        try:
            return self.os.visibleMemory
        except Exception, e:
            self.checkHealth()
            raise

    def getMyVCPUs(self):
        try:
            if self.windows:
                return self._xmlrpc().getCPUs()
            elif re.search("solaris", self.distro):
                return int(self.execcmd("prtconf|grep cpu|grep -cv cpus"))
            else:
                return int(self.execcmd("grep -c \"^processor[[:space:]]\" " +
                                        "/proc/cpuinfo"))
        except Exception, e:
            self.checkHealth()
            raise

    def deprecatedIfConfig(self):
        return self.distro.startswith("rhel7") or self.distro.startswith("oel7") or self.distro.startswith("centos7") or self.distro.startswith("sl7") or self.distro.startswith("fedora")

    def getMyVIFs(self):
        try:
            if self.windows:
                macs = []
                ipconfData = self.getWindowsIPConfigData()
                for entry in ipconfData.itervalues():
                    if entry.has_key('Physical Address'):
                        if re.match('^([0-9a-fA-F]{2}-){5}[0-9a-fA-F]{2}$', entry['Physical Address']):
                            # Check for Teredo tunneling
                            if not 'teredo' in entry['Description'].lower():
                                macs.append(re.sub('-', ':', entry['Physical Address']))
                return macs
            elif re.search("solaris", self.distro):
                macs = self.execcmd("ifconfig -a|grep \"ether [0-9a-fA-F:]\"|awk '{print $2}'").strip().upper().splitlines()
                return map(lambda mac:":".join([("%s" % oc).zfill(2) for oc in (string.split(mac,":"))]),macs)
            elif self.deprecatedIfConfig():
                return self.execcmd("ip link show | grep -o \"link/ether [0-9a-fA-F:]\+\" | sed -e 's#link/ether ##'").strip().upper().splitlines()
            else:
                return self.execcmd("ifconfig -a | grep -o \"HWaddr [0-9a-fA-F:]\+\" | sed -e 's/HWaddr //'").strip().upper().splitlines()
        except Exception, e:
            self.checkHealth()
            raise

    def getLastBootTime(self):
        try:
            if self.windows:
                return None
            else:
                return int(self.execcmd("date -d "
                                        "\"`last reboot -n 1 -R | "
                                        "head -n 1 | "
                                        "cut -d \" \" -f 7-10`\" +%s").strip())
        except Exception, e:
            self.checkHealth()
            raise


    def getLastShutdownTime(self):
        try:
            if self.windows:
                return None
            else:
                try:
                    # Assume year is the same locally as it is in
                    # the syslog entries.
                    year = time.localtime()[0]
                    data = self.execcmd("cat /var/log/messages")
                    sdlines = re.findall(".*shutting down.*", data)
                    # Parse out the timestamps.
                    mtime = re.compile("[A-Z][a-z]+[ \t]+[0-9]+[ \t]+[0-9:]+")
                    stimes = [ mtime.search(x).group() for x in sdlines ]
                    # Append the year.
                    withyear = [ x + " %s" % (year) for x in stimes ]
                    # Convert to times.
                    dformat = "%b %d %H:%M:%S %Y"
                    times = [ time.strptime(x, dformat) for x in withyear ]
                    times = [ time.mktime(x) for x in times ]
                    # Return most recent shutdown.
                    return max(times)
                except:
                    return None
        except Exception, e:
            self.checkHealth()
            raise

    def sshSession(self, username=None, password=None):
        if xenrt.TEC().lookup("OPTION_RETRY_SSH", False, boolean=True):
            goes = 3
        else:
            goes = 1
        toraise = None
        while goes > 0:
            try:
                kwargs = {}
                if username:
                    kwargs["username"] = username
                if password:
                    kwargs["password"] = password
                else:
                    kwargs["password"] = self.password
                return xenrt.ssh.SSHSession(self.getIP(), **kwargs)
            except Exception, e:
                toraise = e
            goes = goes - 1
            if goes > 0:
                xenrt.TEC().warning("Retrying SSHSession connection")
                xenrt.sleep(10)
        raise toraise

    def execcmd(self,
                command,
                username=None,
                retval="string",
                level=xenrt.RC_FAIL,
                timeout=300,
                idempotent=False,
                newlineok=False,
                nolog=False,
                outfile=None,
                password=None):
        """Execute a command on the guest using SSH"""
        if isinstance(self, GenericHost):
            return self.execdom0(command,
                                 username=username,
                                 retval=retval,
                                 level=level,
                                 timeout=timeout,
                                 idempotent=idempotent,
                                 newlineok=newlineok,
                                 nolog=nolog,
                                 outfile=outfile,
                                 password=password)
        elif isinstance(self, GenericGuest):
            return self.execguest(command,
                                  username=username,
                                  retval=retval,
                                  level=level,
                                  timeout=timeout,
                                  idempotent=idempotent,
                                  newlineok=newlineok,
                                  nolog=nolog,
                                  outfile=outfile,
                                  password=password)
        else:
            raise xenrt.XRTError("Unknown GenericPlace subclass")

    def sftpClient(self, username="root", level=xenrt.RC_FAIL):
        """Get a SFTP client object to the guest"""
        return xenrt.ssh.SFTPSession(self.getIP(),
                                     username=username,
                                     password=self.password,
                                     level=level)

    def findPassword(self, ipList = []):
        """Try some passwords to determine which to use"""
        if self.windows:
            return
        if not self.password or len(ipList) > 0:
            # Use a 30s timeout if we know the IP. If we don't try 10s first
            if len(ipList) == 0:
                timeouts = [30]
                ipList = [self.getIP()]
            else:
                timeouts = [10, 30]
            passwords = string.split(xenrt.TEC().lookup("ROOT_PASSWORDS", ""))
            for t in timeouts:
                for p in passwords:
                    for i in ipList:
                        xenrt.TEC().logverbose("Trying %s on %s" % (p, i))
                        try:
                            xenrt.ssh.SSH(i, "true", username="root",
                                          password=p, level=xenrt.RC_FAIL, timeout=t)
                            xenrt.TEC().logverbose("Setting my password to %s" % (p))
                            self.password = p
                            if i != self.getIP():
                                xenrt.TEC().logverbose("Setting my IP to %s" % (i))
                                self.setIP(i)
                            return
                        except:
                            pass

    def checkWindows(self, ipList = []):
        password = string.split(xenrt.TEC().lookup("ROOT_PASSWORDS", ""))[0]
        for i in ipList:
            try:
                xenrt.ssh.SSH(i, "true", username="root",
                              password=password, level=xenrt.RC_FAIL, timeout=2)
                return
            except:
                if self.xmlrpcIsAlive(i):
                    xenrt.TEC().logverbose("Detected Windows")
                    if i != self.getIP():
                        xenrt.TEC().logverbose("Setting my IP to %s" % (i))
                        self.setIP(i)
                    self.windows=True
                    return

    def waitForSSH(self, timeout, level=xenrt.RC_FAIL, desc="Operation", username="root", cmd="true"):

        if not self.getIP():
            if level == xenrt.RC_FAIL:
                self.checkHealth(unreachable=True)
            return xenrt.XRT("%s: No IP address found" % (desc), level)

        now = xenrt.util.timenow()
        deadline = now + timeout
        while 1:
            if not self.password:
                self.findPassword()
            if xenrt.ssh.SSH(self.getIP(),
                             cmd,
                             password=self.password,
                             level=xenrt.RC_OK,
                             timeout=20,
                             username=username,
                             nowarn=True) == xenrt.RC_OK:
                xenrt.TEC().logverbose(" ... OK reply from %s" %
                                       (self.getIP()))
                return xenrt.RC_OK
            now = xenrt.util.timenow()
            if now > deadline:
                if level == xenrt.RC_FAIL:
                    self.checkHealth(unreachable=True)
                return xenrt.XRT("%s timed out" % (desc), level)
            xenrt.sleep(15, log=False)

    def waitforxmlrpc(self, timeout, level=xenrt.RC_FAIL, desc="Daemon", sleeptime=15, reallyImpatient=False):
        now = xenrt.util.timenow()
        deadline = now + timeout
        perrors = 0
        while True:
            xenrt.TEC().logverbose("Checking for exec daemon on %s" %
                                   (self.getIP()))
            try:
                if self._xmlrpc(impatient=True, reallyImpatient=reallyImpatient).isAlive():
                    xenrt.TEC().logverbose(" ... OK reply from %s" %
                                           (self.getIP()))
                    return xenrt.RC_OK
            except socket.error, e:
                xenrt.TEC().logverbose(" ... %s" % (str(e)))
            except socket.timeout, e:
                xenrt.TEC().logverbose(" ... %s" % (str(e)))
            except xmlrpclib.ProtocolError, e:
                perrors = perrors + 1
                if perrors >= 3:
                    raise
                xenrt.TEC().warning("XML-RPC daemon ProtocolError during "
                                    "poll (%s)" % (str(e)))
            now = xenrt.util.timenow()
            if now > deadline:
                if level == xenrt.RC_FAIL:
                    self.checkHealth(unreachable=True)
                return xenrt.XRT("%s timed out" % (desc), level)
            xenrt.sleep(sleeptime, log=False)

    def waitForDaemon(self, timeout, level=xenrt.RC_FAIL, desc="Daemon"):
        return self.waitforxmlrpc(timeout, level=level, desc=desc)

    def xmlrpcIsAlive(self, ip=None):
        """Return True if this place has a reachable XML-RPC test daemon"""
        try:
            if self._xmlrpc(ipoverride=ip).isAlive():
                return True
        except:
            pass
        return False

    def checkHealth(self, unreachable=False, noreachcheck=False, desc=""):
        """Check the location is healthy."""
        pass

    def checkReachable(self, timeout=60, level=xenrt.RC_FAIL):
        if not self.windows:
            return self.waitForSSH(timeout,
                                   level=level,
                                   desc="Reachability check")
        else:
            return self.waitforxmlrpc(timeout,
                                      level=level,
                                      desc="Reachability check")

    def checkAlive(self):
        """Check the location is alive"""
        if not self.windows:
            if not self.password:
                self.findPassword()
            if xenrt.ssh.SSH(self.getIP(),
                             "true",
                             password=self.password,
                             level=xenrt.RC_OK,
                             timeout=20,
                             username="root",
                             nowarn=True) == xenrt.RC_OK:
                xenrt.TEC().logverbose(" ... OK reply from %s" %
                                       (self.getIP()))
                return True
            return False
        else:
            return self.xmlrpcIsAlive()

    def _xmlrpc(self, impatient=False, patient=False, reallyImpatient=False, ipoverride=None):
        try:
            if not isinstance(self.os, xenrt.xenrt.lib.opsys.WindowsOS):
                xenrt.TEC().warning("OS is not Windows - self.os is of type %s" % str(self.os.__class__))
                [xenrt.TEC().logverbose(x) for x in traceback.format_stack()]
        except Exception, e:
            xenrt.TEC().warning("Error creating OS: %s" % str(e))
            [xenrt.TEC().logverbose(x) for x in traceback.format_stack()]
        if reallyImpatient:
            trans = MyReallyImpatientTrans()
        elif impatient:
            trans = MyImpatientTrans()
        elif patient:
            trans = MyPatientTrans()
        else:
            trans = MyTrans()
        if ipoverride:
            ip = IPy.IP(ipoverride)
        else:
            ip = IPy.IP(self.getIP())
        url = ""
        if ip.version() == 6:
            url = 'http://[%s]:8936'
        else:
            url = 'http://%s:8936'
        return xmlrpclib.ServerProxy(url % (self.getIP()),
                                     transport=trans,
                                     allow_none=True)

    def xmlrpcUpdate(self):
        """Update the test execution daemon to the latest version"""
        xenrt.TEC().logverbose("Updating XML-RPC daemon on %s" % (self.getIP()))
        self.xmlrpcExec("attrib -r c:\\execdaemon.py")
        f = file("%s/utils/execdaemon.py" %
                 (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")), "r")
        data = f.read()
        f.close()
        try:
            self._xmlrpc().stopDaemon(data)
            try:
                self._xmlrpc().isAlive()
            except:
                pass
            if xenrt.TEC().lookup("EXTRA_TIME", False, boolean=True):
                xenrt.sleep(60)
            else:
                xenrt.sleep(30)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcShutdown(self):
        """Use the test execution daemon to shutdown the guest"""
        xenrt.TEC().logverbose("Shutting down %s" % (self.getIP()))
        self._xmlrpc().shutdown()

    def xmlrpcReboot(self):
        """Use the test execution daemon to reboot the guest"""
        xenrt.TEC().logverbose("Rebooting %s" % (self.getIP()))
        self._xmlrpc().reboot()

    def xmlrpcStart(self, command):
        """Asynchronously start a command"""
        xenrt.TEC().logverbose("Starting on %s via daemon: %s" %
                               (self.getName(), command.encode("utf-8")))
        trace = xenrt.TEC().lookup("TCPDUMP_XMLRPCSTART", False, boolean=True)
        tracefile = None
        tracepid = None
        try:
            try:
                if trace:
                    # Record a tcpdump trace of traffic between the controller
                    # and the remote location for the duration of the
                    # XML-RPC start command.
                    try:
                        logdir = xenrt.TEC().getLogdir()
                        if logdir:
                            tracefile = "%s/%s_%u.tcpdump" % (\
                                logdir,
                                self.getIP(),
                                xenrt.util.timenow())
                        if tracefile:
                            # Start the tcpdump
                            xenrt.TEC().logverbose(\
                                "tcpdump of xmlrpcStart"
                                "(\"%s\") on %s to file %s"
                                % (command.encode("utf-8"),
                                   self.getIP(),
                                   os.path.basename(tracefile)))
                            tracepid = xenrt.util.command(\
                                "sudo /usr/sbin/tcpdump -i eth0 -s0 -w %s "
                                "host %s >/dev/null 2>&1 </dev/null & echo $!"
                                % (tracefile, self.getIP())).strip()
                            xenrt.sleep(2)
                    except:
                        pass
                ref = self._xmlrpc().runbatch(command.encode("utf-16").encode("uu"))
                xenrt.TEC().logverbose(" ... started")
                return ref
            finally:
                if tracepid:
                    try:
                        # Stop the tcpdump
                        xenrt.util.command("sudo kill -TERM %s" % (tracepid))
                    except:
                        pass
        except Exception, e:
            self.checkHealth()
            raise


    def xmlrpcPoll(self, ref, retries=1):
        """Returns True if the command has completed."""
        try:
            while retries > 0:
                try:
                    retries = retries - 1
                    st = self._xmlrpc().poll(ref)
                    break
                except Exception, e:
                    if retries == 0:
                        raise
                    xenrt.sleep(15)
            if st == "DONE":
                return True
            return False
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcGetPID(self, ref):
        """Returns the PID of the command"""
        try:
            return self._xmlrpc().getPID(ref)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcCreateDir(self, pathname):
        xenrt.TEC().logverbose("CreateDir %s on %s" % (pathname, self.getIP()))
        try:
            self._xmlrpc().createDir(pathname)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcReturnCode(self, ref):
        """Returns the return code of the command."""
        try:
            return int(self._xmlrpc().returncode(ref))
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcCleanup(self, ref):
        """Clean up the state for a command"""
        try:
            self._xmlrpc().cleanup(ref)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcLog(self, ref):
        """Return the logfile text from a command."""
        try:
            return self._xmlrpc().log(ref).encode("utf-8")
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcExec(self, command, level=xenrt.RC_FAIL, desc="Remote command",
                   returndata=False, returnerror=True, returnrc=False,
                   timeout=300, ignoredata=False, powershell=False,ignoreHealthCheck=False):
        """Execute a command and wait for completion."""
        currentPollPeriod = 1
        maxPollPeriod = 16

        try:
            xenrt.TEC().logverbose("Running on %s via daemon: %s" %
                                   (self.getName(), command.encode("utf-8")))
            started = xenrt.util.timenow()
            s = self._xmlrpc()
            if powershell:
                ref = s.runpshell(command.encode("utf-16").encode("uu"))
            else:
                ref = s.runbatch(command.encode("utf-16").encode("uu"))
            xenrt.sleep(currentPollPeriod, log=False)
            errors = 0
            if xenrt.TEC().lookup("EXTRA_TIME", False, boolean=True):
                maxerrors = 6
            else:
                maxerrors = 2
            while True:
                try:
                    st = s.poll(ref)
                    errors = 0
                except socket.error, e:
                    errors = errors + 1
                    if errors > maxerrors:
                        raise
                    st = "ERROR"
                if st == "DONE":
                    break
                if timeout:
                    now = xenrt.util.timenow()
                    deadline = started + timeout
                    if now > deadline:
                        xenrt.TEC().logverbose("Timed out polling for %s on %s"
                                               % (ref, self.getIP()))
                        return xenrt.XRT("%s timed out" % (desc), level)

                if currentPollPeriod < maxPollPeriod:
                    currentPollPeriod *= 2
                    currentPollPeriod = min(currentPollPeriod, maxPollPeriod)

                xenrt.sleep(currentPollPeriod, log=False)
            if not ignoredata:
                data = s.log(ref)
                xenrt.TEC().log(data.encode("utf-8"))
            else:
                data = None
            rc = s.returncode(ref)
            try:
                s.cleanup(ref)
            except Exception, e:
                xenrt.TEC().warning("Got exception while cleaning up after "
                                    "xmlrpcExec: %s" % (str(e)))
            if rc != 0 and returnerror:
                return xenrt.XRT("%s returned error (%d)" % (desc, rc),
                                 level,
                                 data)
            if returndata:
                return data
            if returnrc:
                return rc
            return 0
        except xenrt.XRTException, e:
            if not ignoreHealthCheck:
                self.checkHealth()
            raise
        except Exception, e:
            sys.stderr.write(str(e))
            traceback.print_exc(file=sys.stderr)
            if not ignoreHealthCheck:
                self.checkHealth()
            raise

    def xmlrpcWait(self, ref, level=xenrt.RC_FAIL, desc="Remote command",
                   returndata=False, timeout=None, cleanup=True):
        """Wait for completion of a command started with xmlrpcStart."""
        try:
            started = xenrt.util.timenow()
            s = self._xmlrpc()
            while True:
                st = s.poll(ref)
                if st == "DONE":
                    break
                if timeout:
                    now = xenrt.util.timenow()
                    deadline = started + timeout
                    if now > deadline:
                        return xenrt.XRT("%s timed out" % (desc), level)
                xenrt.sleep(15)
            data = s.log(ref).encode("utf-8")
            xenrt.TEC().log(data)
            rc = s.returncode(ref)
            if cleanup:
                s.cleanup(ref)
            if rc != 0:
                return xenrt.XRT("%s returned error (%d)" % (desc, rc),
                                 level,
                                 data)
            if returndata:
                return data
            return 0
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcGetTime(self):
        xenrt.TEC().logverbose("GetTime on %s" % (self.getIP()))
        try:
            t = self._xmlrpc().getTime()
            xenrt.TEC().logverbose("GetTime on %s returned %s" %
                                   (self.getIP(), str(t)))
            return t
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcGetEnvVar(self, var):
        xenrt.TEC().logverbose("GetEnvVar %s on %s" % (var, self.getIP()))
        try:
            return self._xmlrpc().getEnvVar(var)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcUnpackTarball(self, tarball, dest, patient=False):
        xenrt.TEC().logverbose("UnpackTarball %s to %s on %s" %
                               (tarball, dest, self.getIP()))
        try:
            return self._xmlrpc(patient=patient).unpackTarball(tarball, dest)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcTempDir(self, suffix="", prefix="", path=None, patient=False):
        xenrt.TEC().logverbose("TempDir on %s" % (self.getIP()))
        try:
            if path:
                return self._xmlrpc(patient=patient).tempDir(suffix, prefix, path)
            else:
                return self._xmlrpc(patient=patient).tempDir(suffix, prefix)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcCheckOtherDaemon(self, ip):
        try:
            return self._xmlrpc().checkOtherDaemon(ip)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcKillAll(self, name):
        xenrt.TEC().logverbose("KillAll %s on %s" % (name, self.getIP()))
        try:
            return self._xmlrpc().killall(name)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcKill(self, pid):
        xenrt.TEC().logverbose("Kill %s on %s" % (pid, self.getIP()))
        try:
            return self._xmlrpc().kill(pid)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcPS(self):
        xenrt.TEC().logverbose("PS on %s" % (self.getIP()))
        numberOfTimes = 5
        while True:
            try:
                return self._xmlrpc().ps()
            except Exception, e:
                if numberOfTimes > 0:
                    xenrt.TEC().logverbose("ps() call to the guest failed. Trying again.")
                    numberOfTimes -= 1
                    xenrt.sleep(60)
                else:
                    self.checkHealth()
                    raise

    def xmlrpcBigdump(self, ignoreHealthCheck=False):
        xenrt.TEC().logverbose("Bugdump on %s" % (self.getIP()))
        try:
            s = self._xmlrpc()
            if s.globpath("%s\\MEMORY.DMP" % s.getEnvVar("SystemRoot")):
                return True
            else:
                return False
        except Exception, e:
            if not ignoreHealthCheck:
                self.checkHealth()
            raise

    def xmlrpcSha1Sum(self, filename, patient=False):
        xenrt.TEC().logverbose("Sha1Sum on %s" % (self.getIP()))
        try:
            return self._xmlrpc(patient=patient).sha1Sum(filename)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcSha1Sums(self, temp, list, patient=False):
        xenrt.TEC().logverbose("Sha1Sums on %s" % (self.getIP()))
        try:
            return self._xmlrpc(patient=patient).sha1Sums(temp, list)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcDirRights(self, dir, patient=False):
        xenrt.TEC().logverbose("DirRights %s on %s" % (dir, self.getIP()))
        try:
            return self._xmlrpc(patient=patient).dirRights(dir)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcDelTree(self, dir, patient=False):
        xenrt.TEC().logverbose("DelTree %s on %s" % (dir, self.getIP()))
        try:
            return self._xmlrpc(patient=patient).deltree(dir)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcMinidumps(self, ignoreHealthCheck=False):
        xenrt.TEC().logverbose("Minidumps on %s" % (self.getIP()))
        try:
            s = self._xmlrpc()
            return s.globpath("%s\\Minidump\\*" % s.getEnvVar("SystemRoot"))
        except Exception, e:
            if not ignoreHealthCheck:
                self.checkHealth()
            raise

    def xmlrpcReadFile(self, filename, patient=False, ignoreHealthCheck=False):
        try:
            xenrt.TEC().logverbose("Fetching file %s from %s via daemon" %
                                   (filename, self.getIP()))
            s = self._xmlrpc(patient=patient)
            return s.readFile(filename).data
        except Exception, e:
            if not ignoreHealthCheck:
                self.checkHealth()
            raise

    def xmlrpcGetFile(self, remotefn, localfn, patient=False, ignoreHealthCheck=False):
        xenrt.TEC().logverbose("GetFile %s to %s on %s" %
                               (remotefn, localfn, self.getIP()))
        try:
            data = self.xmlrpcReadFile(remotefn, patient=patient, ignoreHealthCheck=ignoreHealthCheck)
            f = file(localfn, "w")
            f.write(data)
            f.close()
        except Exception, e:
            if not ignoreHealthCheck:
                self.checkHealth()
            raise

    def xmlrpcGetFile2(self, remotefn, localfn, patient=False):
        xenrt.TEC().logverbose("GetFile2 %s to %s on %s" %
                               (remotefn, localfn, self.getIP()))
        try:
            s = self._xmlrpc(patient=patient)
            databz2 = s.readFileBZ2(remotefn).data
            c = bz2.BZ2Decompressor()
            f = file(localfn, "w")
            start = 0
            while True:
                data = c.decompress(databz2[start:start+4096])
                if len(data) > 0:
                    f.write(data)
                start = start + 4096
                if start >= len(databz2):
                    break
            f.close()
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcFetchFile(self, url, remotefn):
        try:
            xenrt.TEC().logverbose("Fetching %s to %s on %s via daemon" %
                                   (url,remotefn,self.getIP()))
            s = self._xmlrpc()
            return s.fetchFile(url, remotefn)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcVersion(self):
        s = self._xmlrpc()
        try:
            return s.version()
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcWindowsVersion(self):
        xenrt.TEC().logverbose("WindowsVersion on %s" % (self.getIP()))
        try:
            v = self._xmlrpc().windowsVersion()
            xenrt.TEC().logverbose("WindowsVersion returned %s" % str(v))
            return v
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcGetArch(self):
        xenrt.TEC().logverbose("GetArch on %s" % (self.getIP()))
        try:
            return self._xmlrpc().getArch()
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcGetCPUs(self):
        xenrt.TEC().logverbose("GetCPUs on %s" % (self.getIP()))
        patient = xenrt.TEC().lookup("EXTRA_TIME", False, boolean=True)
        try:
            return self._xmlrpc(patient=patient).getCPUs()
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcGetSockets(self):
        """ Get the number of CPU sockets (filled) on the remote system """
        if float(self.xmlrpcWindowsVersion()) < 6.0:
            raise xenrt.XRTError("N/A for NT kernel < 6.0")
        xenrt.TEC().logverbose("GetSockets on %s" % (self.getIP()))
        patient = xenrt.TEC().lookup("EXTRA_TIME", False, boolean=True)
        try:
            return self._xmlrpc(patient=patient).getSockets()
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcGetCPUCores(self):
        """ Get the number of cores on each physical CPU on the remote system """
        if float(self.xmlrpcWindowsVersion()) < 6.0:
            raise xenrt.XRTError("N/A for NT kernel < 6.0")
        xenrt.TEC().logverbose("GetCPUCores on %s" % (self.getIP()))
        patient = xenrt.TEC().lookup("EXTRA_TIME", False, boolean=True)
        try:
            return self._xmlrpc(patient=patient).getCPUCores()
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcGetCPUVCPUs(self):
        """ Get the number of logical CPUs on each physical CPU on the remote system """
        if float(self.xmlrpcWindowsVersion()) < 6.0:
            raise xenrt.XRTError("N/A for NT kernel < 6.0")
        xenrt.TEC().logverbose("GetCPUVCPUs on %s" % (self.getIP()))
        patient = xenrt.TEC().lookup("EXTRA_TIME", False, boolean=True)
        try:
            return self._xmlrpc(patient=patient).getCPUVCPUs()
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcPartition(self, disk):
        xenrt.TEC().logverbose("Partition %s on %s" % (disk, self.getIP()))
        try:
            return self._xmlrpc().partition(disk)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcDeletePartition(self, letter):
        xenrt.TEC().logverbose("DeletePartition %s on %s" %
                               (letter, self.getIP()))
        try:
            return self._xmlrpc().deletePartition(letter)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcMapDrive(self, networkLocation, driveLetter):
        self.xmlrpcExec(r"net use %s: /Delete /y" % driveLetter, level=xenrt.RC_OK)
        self.xmlrpcExec(r"net use %s: %s"% (driveLetter, networkLocation))

    def xmlrpcAssign(self, disk):
        xenrt.TEC().logverbose("Assign %s on %s" % (disk, self.getIP()))
        try:
            return self._xmlrpc().assign(disk)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcListDisks(self):
        xenrt.TEC().logverbose("ListDisks on %s" % (self.getIP()))
        try:
            return self._xmlrpc().listDisks()
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcDiskpartCommand(self, cmd):
        self.xmlrpcWriteFile("c:\\diskpartcmd.txt", cmd)
        return self.xmlrpcExec("diskpart /s c:\\diskpartcmd.txt", returndata=True)

    def xmlrpcDiskpartListDisks(self):
        disksstr = self.xmlrpcDiskpartCommand("list disk")
        return re.findall("Disk\s+([0-9]*)\s+", disksstr)

    def xmlrpcDriveLettersOfDisk(self, diskid):
        diskdetail = self.xmlrpcDiskpartCommand("select disk %s\ndetail disk" % (diskid))
        return re.findall("Volume [0-9]+\s+([A-Z])", diskdetail)

    def xmlrpcDeinitializeDisk(self, diskid):
        self.xmlrpcDiskpartCommand("select disk %s\nclean" % (diskid))

    def xmlrpcInitializeDisk(self, diskid, driveLetter='e'):
        """ Initialize disk, create a single partition on it, activate it and
        assign a drive letter.
        """
        xenrt.TEC().logverbose("Initialize disk %s (letter %s)" % (diskid, driveLetter))
        return self.xmlrpcDiskpartCommand("select disk %s\n"
                             "attributes disk clear readonly\n"
                             "convert mbr\n"              # initialize
                             "create partition primary\n" # create partition
                             "active\n"                   # activate partition
                             "assign letter=%s"           # assign drive letter
                             % (diskid, driveLetter))

    def xmlrpcMarkDiskOnline(self, diskid=None):
        """ mark disk online by diskid. The function will fail if the diskid is
        invalid or the disk is already online . When diskid == None (default),
        the function will mark any offline disk as online.
        """
        xenrt.TEC().logverbose("Mark disk %s online" % (diskid or "all"))
        data = self.xmlrpcExec("echo list disk | diskpart",
                               returndata=True)
        offline = re.findall("Disk\s+([0-9]+)\s+Offline", data)
        if diskid:
            if diskid in offline:
                offline = [ diskid ]
            else:
                raise xenrt.XRTError("disk %d is already online" % diskid)
        for o in offline:
            return self.xmlrpcDiskpartCommand("select disk %s\n"
                                 "attributes disk clear readonly\n"
                                 "online disk noerr" % (o))

    def xmlrpcFormat(self, letter, fstype="ntfs", timeout=1200, quick=False):
        cmd = self.xmlrpcWindowsVersion() == "5.0" \
              and "echo y | format %s: /fs:%s" \
              or "format %s: /fs:%s /y"
        cmd = quick and cmd + " /q" or cmd
        self.xmlrpcExec(cmd % (letter, fstype), timeout=timeout)

    def xmlrpcSendFile(self, localfilename, remotefilename, usehttp=None, ignoreHealthCheck=False):
        if usehttp == None:
            # If the file is larger than 4MB default to using HTTP fetch,
            # otherwise default to XML-RPC push
            if os.stat(localfilename).st_size > 4194304:
                usehttp = True
            else:
                usehttp = False
        try:
            s = self._xmlrpc()
            if usehttp:
                # Pull the file into the guest
                wdir = xenrt.resources.WebDirectory()
                try:
                    wdir.copyIn(localfilename)
                    xenrt.TEC().logverbose("Pulling %s into %s:%s" %
                                           (localfilename,
                                            self.getIP(),
                                            remotefilename))
                    s.fetchFile(wdir.getURL(os.path.basename(localfilename)),
                                remotefilename)
                finally:
                    wdir.remove()
            else:
                # Push the file to the guest
                f = file(localfilename, 'r')
                data = f.read()
                f.close()
                xenrt.TEC().logverbose("Pushing %s to %s:%s" %
                                       (localfilename,
                                        self.getIP(),
                                        remotefilename))
                s.createFile(remotefilename, xmlrpclib.Binary(data))
        except Exception, e:
            if not ignoreHealthCheck:
                self.checkHealth()
            raise

    def xmlrpcWriteFile(self, filename, data):
        try:
            xenrt.TEC().logverbose("Writing file %s to %s via daemon" %
                                   (filename, self.getIP()))
            s = self._xmlrpc()
            s.createFile(filename, xmlrpclib.Binary(data))
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcSendTarball(self, localfilename, remotedirectory):
        xenrt.TEC().logverbose("SendTarball %s to %s on %s" %
                               (localfilename, remotedirectory, self.getIP()))
        try:
            s = self._xmlrpc()
            f = file(localfilename, 'r')
            data = f.read()
            f.close()
            s.pushTarball(xmlrpclib.Binary(data), remotedirectory)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcPushTarball(self, data, directory):
        xenrt.TEC().logverbose("PushTarball to %s on %s" %
                               (directory, self.getIP()))
        try:
            return self._xmlrpc().pushTarball(data, directory)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcSendRecursive(self, localdirectory, remotedirectory):
        xenrt.TEC().logverbose("SendRecursive %s to %s on %s" %
                               (localdirectory, remotedirectory, self.getIP()))
        try:
            f = xenrt.TEC().tempFile()
            xenrt.util.command("tar -zcf %s -C %s ." % (f, localdirectory))
            self.xmlrpcSendTarball(f, remotedirectory)
            os.unlink(f)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcFetchRecursive(self, remotedirectory, localdirectory, ignoreHealthCheck=False):
        xenrt.TEC().logverbose("FetchRecursive %s to %s on %s" %
                               (remotedirectory, localdirectory, self.getIP()))
        try:
            f = xenrt.TEC().tempFile()
            rf = self._xmlrpc().tempFile()
            self._xmlrpc().createTarball(rf, remotedirectory)
            self.xmlrpcGetFile(rf, f, ignoreHealthCheck=ignoreHealthCheck)
            xenrt.util.command("tar -xf %s -C \"%s\"" % (f, localdirectory))
            self.xmlrpcRemoveFile(rf, ignoreHealthCheck=ignoreHealthCheck)
            os.unlink(f)
        except Exception, e:
            if not ignoreHealthCheck:
                self.checkHealth()
            raise

    def xmlrpcExtractTarball(self, filename, directory, patient=True):
        xenrt.TEC().logverbose("ExtractTarball %s to %s on %s" %
                               (filename, directory, self.getIP()))
        try:
            self._xmlrpc(patient=patient).extractTarball(filename, directory)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcGlobpath(self, p):
        xenrt.TEC().logverbose("GlobPath %s on %s" % (p, self.getIP()))
        try:
            return self._xmlrpc().globpath(p)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcGlobPattern(self, pattern):
        xenrt.TEC().logverbose("GlobPattern %s on %s" % (pattern, self.getIP()))
        try:
            return self._xmlrpc().globPattern(pattern)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcFileExists(self, filename, patient=False, ignoreHealthCheck=False):
        xenrt.TEC().logverbose("FileExists %s on %s" % (filename, self.getIP()))
        counter = 0
        while(counter<3):
            try:
                ret = self._xmlrpc(patient=patient).fileExists(filename)
                xenrt.TEC().logverbose("FileExists returned %s" % str(ret))
                return ret
            except Exception, e:
                if counter == 3:
                    ignoreHealthCheck
                    self.checkHealth()
                    raise
                else:
                    xenrt.sleep(30)
                    counter = counter + 1
 

    def xmlrpcDirExists(self, filename, patient=False):
        xenrt.TEC().logverbose("DirExists %s on %s" % (filename, self.getIP()))
        try:
            return self._xmlrpc(patient=patient).dirExists(filename)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcFileMTime(self, filename, patient=False):
        xenrt.TEC().logverbose("FileMTime %s on %s" % (filename, self.getIP()))
        try:
            return self._xmlrpc(patient=patient).fileMTime(filename)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcDiskInfo(self):
        xenrt.TEC().logverbose("DiskInfo on %s" % (self.getIP()))
        try:
            return self._xmlrpc().diskInfo()
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcDoSysprep(self):
        xenrt.TEC().logverbose("Sysprep on %s" % (self.getIP()))
        try:
            return self._xmlrpc().doSysprep()
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcGetRootDisk(self):
        xenrt.TEC().logverbose("GetRootDisk on %s" % (self.getIP()))
        try:
            return self._xmlrpc().getRootDisk()
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcCreateFile(self, filename, data):
        xenrt.TEC().logverbose("CreateFile %s on %s" % (filename, self.getIP()))
        try:
            return self._xmlrpc().createFile(filename, data)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcRemoveFile(self, filename, patient=False, ignoreHealthCheck=False):
        xenrt.TEC().logverbose("RemoveFile %s on %s" % (filename, self.getIP()))
        try:
            return self._xmlrpc(patient=patient).removeFile(filename)
        except Exception, e:
            if not ignoreHealthCheck:
                self.checkHealth()
            raise

    def xmlrpcCreateEmptyFile(self, filename, size):
        xenrt.TEC().logverbose("CreateEmptyFile %s on %s" %
                               (filename, self.getIP()))
        try:
            return self._xmlrpc().createEmptyFile(filename, size)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcAddBootFlag(self, flag):
        xenrt.TEC().logverbose("AddBootFlag %s on %s" % (flag, self.getIP()))
        try:
            return self._xmlrpc().addBootFlag(flag)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcAppActivate(self, app):
        xenrt.TEC().logverbose("AppActivate %s on %s" % (app, self.getIP()))
        try:
            return self._xmlrpc().appActivate(app)
        except Exception, e:
            self.checkHealth()
            raise

    def xmlrpcSendKeys(self, keys):
        xenrt.TEC().logverbose("SendKeys %s on %s" % (keys, self.getIP()))
        try:
            return self._xmlrpc().sendKeys(keys)
        except Exception, e:
            self.checkHealth()
            raise

    def getWindowsEventLog(self, log, clearlog=False, ignoreHealthCheck=False):
        """Return a string containing a CSV dump of the specified Windows
        event log."""
        if not self.xmlrpcFileExists("c:\\psloglist.exe", ignoreHealthCheck=ignoreHealthCheck):
            self.xmlrpcSendFile("%s/distutils/psloglist.exe" %
                                (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")),
                                "c:\\psloglist.exe", ignoreHealthCheck=ignoreHealthCheck)
        command = []
        command.append("c:\\psloglist.exe")
        command.append("/accepteula")
        command.append("-s")
        command.append("-x %s" % (log))
        if clearlog:
            command.append("-c")
        data = self.xmlrpcExec(string.join(command),
                               returndata=True,
                               timeout=3600, ignoreHealthCheck=ignoreHealthCheck)
        return data

    def getWindowsEventLogs(self, logdir, ignoreHealthCheck=False):
        """Fetch all useful Windows event logs to CSV files in the specified
        directory."""
        clearlog = xenrt.TEC().lookup("CLEAR_EVENT_LOGS_ON_FETCH",
                                      False,
                                      boolean=True)
        for log in ("system", "application", "security"):
            if self.logFetchExclude and log in self.logFetchExclude:
                continue
            data = self.getWindowsEventLog(log, clearlog=clearlog, ignoreHealthCheck=ignoreHealthCheck)
            f = file("%s/%s.csv" % (logdir, log), "w")
            f.write(data)
            f.close()

    def winRegPresent(self, hive, key, name):
        """ Check for the windows registry value"""
        
        try:
            s = self._xmlrpc()
            s.regLookup(hive, key, name)
            return True
        except Exception, e:
            return False
            
    def winRegLookup(self, hive, key, name, healthCheckOnFailure=True, suppressLogging=False):
        """Look up a Windows registry value."""

        if not suppressLogging:
            xenrt.TEC().logverbose("Registry lookup: %s %s %s" % (hive, key, name))
        try:
            s = self._xmlrpc()
            val = s.regLookup(hive, key, name)
            if not suppressLogging:
                xenrt.TEC().logverbose("Registry lookup returned: " + str(val))
            return val
        except Exception, e:
            if not suppressLogging:
                xenrt.TEC().logverbose("Registry key not found: " + str(e))
            if healthCheckOnFailure:
                self.checkHealth()
            raise

    def winRegAdd(self, hive, key, name, vtype, value):
        """Add a value to the Windows registry"""
        xenrt.TEC().logverbose("Registry add on %s %s:%s %s=%s (%s)" %
                               (self.getIP(), hive, key, name, value, vtype))
        try:
            s = self._xmlrpc()
            s.regSet(hive, key, name, vtype, value)
        except Exception, e:
            self.checkHealth()
            raise

    def winRegDel(self, hive, key, name, ignoreHealthCheck=False):
        """Remove a value from the Windows registry"""
        xenrt.TEC().logverbose("Registry delete on %s %s:%s %s" %
                               (self.getIP(), hive, key, name))
        try:
            s = self._xmlrpc()
            s.regDelete(hive, key, name)
        except Exception, e:
            if not ignoreHealthCheck:
                self.checkHealth()
            raise

    def disableReceiverMaxProto(self):

        try:
            self.winRegDel("HKLM", "SYSTEM\\CurrentControlSet\\services\\xenvif\\Parameters", "ReceiverMaximumProtocol")
        except:
            xenrt.TEC().logverbose("winRegDel fails post Clearwater")

        self.winRegAdd("HKLM", "SYSTEM\\CurrentControlSet\\services\\xenvif\\Parameters", "ReceiverMaximumProtocol", "DWORD", 0)

    def getReceiverMaxProtocol(self):

        return self.winRegLookup('HKLM', 'SYSTEM\\CurrentControlSet\\services\\xenvif\\Parameters', 'ReceiverMaximumProtocol')

    def joinDomain(self, adserver, computerName=None, adminUserName="Administrator", adminPassword=None):
        # works with ws2008 and ws2012
        if not computerName:
            computerName=self.getName()
        if not adminPassword:
            adminPassword = adserver.place.password

        primarynic = filter(lambda (a,(b,c,d)):d == self.host.getPrimaryBridge(),
                            self.getVIFs().items())[0]
        self.configureDNS(primarynic[0], adserver.place.getIP())
        self.reboot()
        self.xmlrpcExec("netsh advfirewall set domainprofile state off")
        self.rename(computerName)

        script = """$domain = "%s";
$password = "%s" | ConvertTo-SecureString -asPlainText -Force;
$username = "$domain\%s";
$credential = New-Object System.Management.Automation.PSCredential($username,$password);
Add-Computer -DomainName $domain -Credential $credential
""" % (adserver.domainname, adminPassword, adminUserName)

        self.xmlrpcExec(script, returndata=True, powershell=True ,ignoreHealthCheck=True)
        self.xmlrpcExec("net localgroup Administrators %s\\%s /add" % (adserver.domainname, adminUserName), level=xenrt.RC_OK)
        self.reboot()

    def leaveDomain(self):
        # works with ws2008 and ws2012
        try:
            self.xmlrpcExec("Add-Computer -WorkGroupName WORKGROUP -force", returndata=True, powershell=True ,ignoreHealthCheck=True)
        except:
            self.xmlrpcExec("Add-Computer -WorkGroupName WORKGROUP", returndata=True, powershell=True ,ignoreHealthCheck=True)
        self.reboot()

    def configureAutoLogon(self, user):
        if not user.password:
            user.password = xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS",
                                                "ADMINISTRATOR_PASSWORD"],
                                                "xensource")
        self.xmlrpcExec("cacls c:\\execdaemon.log /E /G %s:F" % (user.name))
        self.xmlrpcExec("cacls c:\\execdaemon.py /E /G %s:F" % (user.name))
        # Give everyone read-write permissions for the auto-logon keys.
        t = self.xmlrpcTempDir()
        self.xmlrpcWriteFile("%s\\regperm.txt" % (t),
                             "\\Registry\\Machine\\software\\microsoft\\windows nt\\"
                             "currentversion\\winlogon [1 5 9]")
        self.xmlrpcExec("regini %s\\regperm.txt" % (t))
        self.xmlrpcDelTree(t)
        self.winRegAdd("HKLM",
                       "software\\microsoft\\windows nt\\currentversion\\winlogon",
                       "DefaultUserName",
                       "SZ",
                        user.name)
        self.winRegAdd("HKLM",
                       "software\\microsoft\\windows nt\\currentversion\\winlogon",
                       "DefaultPassword",
                       "SZ",
                        user.password)
        self.winRegAdd("HKLM",
                       "software\\microsoft\\windows nt\\currentversion\\winlogon",
                       "AutoAdminLogon",
                       "SZ",
                       "1")
        self.winRegAdd("HKLM",
                       "software\\microsoft\\windows nt\\currentversion\\winlogon",
                       "DefaultDomainName",
                       "SZ",
                        user.server.domainname)

    def configureDNS(self, device, server):
        device = str(device).strip(self.vifstem)
        device = "%s%s" % (self.vifstem, device)
        if self.windows:
            device = self.getWindowsInterface(device)
            netshargs = []
            netshargs.append('"%s"' % (device))
            netshargs.append("static")
            netshargs.append("%s" % (server))
            self.xmlrpcExec("netsh interface ip set dns %s" %
                            (string.join(netshargs)))
            data = self.getWindowsIPConfigData()
            if not data[device]["DNS Servers"] == server:
                raise xenrt.XRTFailure("DNS server not set. (%s != %s)" %
                                       (server, data[device]["DNS Servers"]))

    def configureNetwork(self, device,
                         ip=None, netmask=None, gateway=None, metric=None):
        device = str(device).strip(self.vifstem)
        device = "%s%s" % (self.vifstem, device)
        if self.windows:
            device = self.getWindowsInterface(device)
            netshargs = []
            netshargs.append('name="%s"' % (device))
            if not ip:
                netshargs.append("source=dhcp")
            else:
                netshargs.append("source=static")
                netshargs.append("addr=%s" % (ip))
                netshargs.append("mask=%s" % (netmask))
            if gateway:
                netshargs.append("gateway=%s" % (gateway))
            if metric:
                netshargs.append("gwmetric=%s" % (metric))
            self.xmlrpcExec("netsh interface ip set address %s" %
                            (string.join(netshargs)))
            # Check changes.
            data = self.getWindowsIPConfigData()
            try:
                readip = data[device]["IP Address"]
            except:
                try:
                    readip = data[device]["IPv4 Address"]
                except:
                    readip = data[device]["Autoconfiguration IPv4 Address"]
            readip = re.search(r"(\d{1,3}|\.){7}", readip).group()
            try:
                dhcp = data[device]["DHCP Enabled"]
            except:
                dhcp = data[device]["Dhcp Enabled"]
            if not ip:
                if not dhcp == "Yes":
                    raise xenrt.XRTError("DHCP not enabled on %s." % (device))
                ip = readip
            else:
                if not dhcp == "No":
                    raise xenrt.XRTError("DHCP enabled on %s." % (device))
                if not readip == ip:
                    raise xenrt.XRTError("IP address not set correctly on %s. (%s, %s)" %
                                         (device, readip, ip))
                if not data[device]["Subnet Mask"] == netmask:
                    if not data[device].has_key("Subnet Mask2") or not data[device]["Subnet Mask2"] == netmask:
                        raise xenrt.XRTError("Subnet mask not set correctly on %s. (%s, %s)" %
                                             (device, data[device]["Subnet Mask"], netmask))
            if gateway:
                if not data[device]["Default Gateway"] == gateway:
                    raise xenrt.XRTError("Gateway not set correctly on %s. (%s, %s)" %
                                         (device, data[device]["Default Gateway"], gateway))
            default, routes = self.getWindowsRouteData()
            if gateway:
                gwroutes = filter(lambda x:x["destination"] == "0.0.0.0", routes)
                gwrecord = filter(lambda x:x["interface"] == ip, gwroutes)
                if not gwrecord:
                    xenrt.TEC().warning("Gateway route not present for %s." % (device))
                    return
                else:
                    if len(gwrecord) == 1: gwrecord = gwrecord[0]
                    else: xenrt.TEC().warning("Multiple gateway routes for %s. (%s)" %
                                              (device, gwrecord))
                if not gateway == gwrecord["gateway"]:
                    xenrt.TEC().warning("Gateway incorrect for gateway route on %s. (%s, %s)" %
                                        (device, gwrecord["gateway"], gateway))
                if metric:
                    if not metric == gwrecord["metric"]:
                        xenrt.TEC().warning("Metric not correct for gateway "
                                            "route on %s. (%s, %s)" %
                                            (device, gwrecord["metric"], metric))
        else:
            data = self.execguest("ifconfig %s %s netmask %s" % (device, ip, netmask))
            if re.search("No such device", data):
                raise xenrt.XRTError("Setting IP failed: No such device.")
            data = self.getLinuxIFConfigData()
            if not data[device]["IP"] == ip:
                raise xenrt.XRTError("Failed to set IP on %s. (%s, %s)" %
                                     (device, data[device]["IP"], ip))
            if not data[device]["netmask"] == netmask:
                raise xenrt.XRTError("Failed to set netmask on %s. (%s, %s)" %
                                     (device, data[device]["netmask"], netmask))

    def getSectionedConfig(self, cmd, secpatt, fieldpatt):
        """ Generic function for getting sectioned configuration output of commands"""
        result = self.xmlrpcExec(cmd, returndata=True)
        config = dict(re.findall(secpatt, result))
        for sec in config:
            entries = re.findall(fieldpatt, config[sec])
            config[sec] = dict(map(lambda(k,v): (k.strip(), " ".join(v.strip().split())), entries))
        xenrt.TEC().logverbose("""Get configuration by command "%s":
%s""" % (cmd, config))
        return config

    def getWindowsRouteData(self):
        ROUTE = r"\s+(?P<destination>[0-9\.]+)" + \
                 "\s+(?P<netmask>[0-9\.]+)" + \
                 "\s+(?P<gateway>[0-9\.]+)" + \
                 "\s+(?P<interface>[0-9\.]+)" + \
                 "\s+(?P<metric>[0-9\.]+)"
        DEFAULT = r"Default Gateway:\s+(?P<default>[0-9\.]+)"

        routes = []
        data = self.xmlrpcExec("route PRINT", returndata=True).strip()
        default = re.search(DEFAULT, data)
        if default: default = default.group("default")
        for m in re.finditer(ROUTE, data):
            groups = re.compile(ROUTE).groupindex.keys()
            routes.append(dict([ (x, m.group(x)) for x in groups ]))
        return (default, routes)

    def getInterfaceForDestination(self, address):
        if self.windows:
            raise xenrt.XRTError("Not implemented for Windows")
        table = {}
        for l in self.execcmd("route -n").strip().splitlines():
            ls = l.split()
            if not re.match("^\d+(\.\d+){3}$", ls[0]):
                continue
            table[(ls[0], ls[2])] = ls[7]

        # Find all routes that match
        matching = filter(lambda x: xenrt.util.isAddressInSubnet(address, x[0], x[1]), table.keys())
        if len(matching) == 0:
            # No route to this address - use the default route
            for t in table.keys():
                if t[0] == "0.0.0.0":
                    return table[t]
            raise xenrt.XRTError("No route to %s found" % (address))

        # Now identify the route with the longest match
        longest = matching[0]
        for m in matching:
            if xenrt.util.maskToPrefLen(m[1]) > xenrt.util.maskToPrefLen(longest[1]):
                longest = m

        return table[longest]

    def getLinuxIFConfigData(self):
        if self.deprecatedIfConfig():
           SECTION = r"(?m)(?P<key>^\S+)(?P<value>.*(?:\n^\s+\S+[^\n]+)+)"
           VALUES = {"MAC":r"ether (?P<MAC>[A-Fa-f0-9:]+)",
                      "IP":r"inet (?P<IP>[0-9\.]+)",
                      "netmask":r"netmask (?P<netmask>[0-9\.]+)"}
        else:
            SECTION = r"(?m)(?P<key>^\S+)(?P<value>.*(?:\n^\s+\S+[^\n]+)+)"
            VALUES = {"MAC":r"HWaddr (?P<MAC>[A-Fa-f0-9:]+)",
                      "IP":r"inet addr:(?P<IP>[0-9\.]+)",
                      "netmask":r"Mask:(?P<netmask>[0-9\.]+)"}

        data = self.execcmd("ifconfig -a").strip()
        # Remove empty lines.
        data = re.sub("\n\n", "\n", data)
        data = dict(re.findall(SECTION, data))
        for key in data:
            entry = {}
            for value in VALUES:
                match = re.search(VALUES[value], data[key])
                if match: entry[value] = match.group(value)
                else: entry[value] = None
            #key = key.split(':')[0]
            data[key] = entry
        for key in data:
            data[key.split(':')[0]] = data.pop(key)
        return data

    def getWindowsIPConfigData(self):
        SECPATT = '(?m)^(\S[^:]*):?\n\n((?:^[\ \t]+\S.*\n)+)'
        FIELDPATT = '\s+([^\.:]+)(?:\.\ )+:(.*\n(?:(?:[^:]+\n)*))'
        result = self.xmlrpcExec("ipconfig /all", returndata=True)
        config = xenrt.util.parseSectionedConfig(result, SECPATT, FIELDPATT)

        output = {}
        for net in config.keys():
            k = re.sub('.*adapter ', '', net)
            xenrt.TEC().logverbose("%s=%s" % (k, str(config[net])))
            output[k] = config[net]

        return output

    def getWindowsNetshConfig(self, cmd):
        SECPATT = '^Configuration for interface "(?m)([^"]+)"\n((?:^[\ \t]+\S.*\n)+)'
        FIELDPATT = '\s*([^:\n]+)(?:\n|:\s*(.*\n?(?:\s*\d[^:]+\n)*)?)'
        result = self.xmlrpcExec(cmd, returndata=True)
        return xenrt.util.parseSectionedConfig(result, SECPATT, FIELDPATT)

    def getWindowsInterface(self, device):
        device = str(device).strip(self.vifstem)
        vifs = self.getVIFs()
        mac, ip, bridge = vifs["%s%s" % (self.vifstem, device)]

        data = self.getWindowsIPConfigData()
        for key in data:
            if data[key].has_key("Physical Address"):
                physical = re.sub("-", ":", data[key]["Physical Address"])
                if xenrt.normaliseMAC(physical) == mac: return key
        raise xenrt.XRTError("Couldn't find %s%s in ipconfig output." %
                             (self.vifstem, device))

    def buildProgram(self, prog):
        """Build a program in the guest"""
        if self.windows:
            raise xenrt.XRTError("Cannot build programs in Windows guests")

        # Make sure we're running
        if self.getState() == "DOWN":
            self.start()

        # Build it
        self.execguest("cd %s/guestprogs/%s && make" %
                       (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), prog))

    def runOnStartup(self, command):
        """Run the specified command on startup"""
        if self.windows:
            # TODO: Implement adding to registry / startup folder
            raise xenrt.XRTError("Unimplemented")
        else:
            self.execcmd("grep -v '^exit 0$' /etc/rc.local > /tmp/rc.local || true")
            self.execcmd("echo '%s' >> /tmp/rc.local" % (command))
            self.execcmd("echo 'exit 0' >> /tmp/rc.local")
            self.execcmd("mv /tmp/rc.local /etc/rc.local")
            self.execcmd("chmod +x /etc/rc.local")
            try:
                self.execcmd("grep -v '^exit 0$' /etc/rc.d/rc.local > /tmp/rc.local || true")
                self.execcmd("echo '%s' >> /tmp/rc.local" % (command))
                self.execcmd("echo 'exit 0' >> /tmp/rc.local")
                self.execcmd("mv /tmp/rc.local /etc/rc.d/rc.local")
                self.execcmd("chmod +x /etc/rc.d/rc.local")
            except:
                xenrt.TEC().logverbose("Failed to install /etc/rc.d/rc.local")

    def getCD(self, cd, destination):
        """Extracts cd to destination on an XML-RPC guest."""
        nfsexp = xenrt.TEC().lookup("EXPORT_ISO_NFS")
        if not nfsexp:
            raise xenrt.XRTError("Couldn't find NFS ISO repository.")
        iso = None
        try:
            f = xenrt.TEC().tempFile()
            mount = xenrt.rootops.MountNFS(nfsexp)
            mountpoint = mount.getMount()
            xenrt.checkFileExists("%s/%s" % (mountpoint, cd))
            iso = xenrt.rootops.MountISO("%s/%s" % (mountpoint, cd))
            mountpoint = iso.getMount()
            xenrt.util.command("tar -zcf %s -C %s ." % (f, mountpoint))
            self.xmlrpcSendFile(f, "c:\\%s.tgz" % (cd), usehttp=True)
        finally:
            try:
                iso.unmount()
            except:
                pass
            try:
                mount.unmount()
            except:
                pass
        self.xmlrpcExtractTarball("c:\\%s.tgz" % (cd), destination)
        try:
            self.xmlrpcRemoveFile("c:\\%s.tgz" % (cd))
        except:
            pass

    def getCDLocal(self, testspath, destination):
        """Copies the contents of a ISO image found in the controller
        tests directory to the specified directory on the guest. If the
        testspath is to a tarball that will be unpacked and the first ISO
        file found within will be used.
        """
        fulltp = "%s/tests/%s" % (xenrt.TEC().lookup("XENRT_BASE"), testspath)
        xenrt.checkFileExists(fulltp)
        if testspath.endswith(".tgz"):
            d = xenrt.TEC().tempDir()
            files = xenrt.util.command("tar -zvxf %s -C %s" % (fulltp, d)).split()
            isopath = None
            for file in files:
                if file.endswith(".iso") or file.endswith(".ISO"):
                    isopath = "%s/%s" % (d, file)
                    break
            if not isopath:
                raise xenrt.XRTError("Could not find an ISO file in the tarball")
        else:
            isopath = fulltp
        remotetemp = "c:\\%u%s.tgz" % (xenrt.util.timenow(),
                                       os.path.basename(isopath))
        iso = xenrt.rootops.MountISO(isopath)
        try:
            mountpoint = iso.getMount()
            f = xenrt.TEC().tempFile()
            xenrt.util.command("tar -zcf %s -C %s ." % (f, mountpoint))
            self.xmlrpcSendFile(f, remotetemp, usehttp=True)
        finally:
            try:
                iso.unmount()
            except:
                pass
        try:
            self.xmlrpcExtractTarball(remotetemp, destination)
        finally:
            try:
                self.xmlrpcRemoveFile(remotetemp)
            except:
                pass
    def installCVSM2230Workaround(self):
        """Install the work-around for CVSM-2230: redist not installed via silent install"""
        vcredist_loc = xenrt.TEC().lookup("CVSM_INPUTDIR", None)
        if vcredist_loc:
            vcredist = xenrt.TEC().getFile("%s/vcredist_x86.exe" % (vcredist_loc))
            rempath = "c:\\%s" % (os.path.basename(vcredist))
            self.xmlrpcSendFile(vcredist, rempath)
            vcredistOptions = '/q:a /c:"VCREDI~3.EXE /q:a /c:""msiexec /i vcredist.msi /qn"" "'
            try:
                self.xmlrpcExec("%s %s" % (rempath, vcredistOptions))
            except Exception, e:
                raise xenrt.XRTError("VCREDIST.exe was unable to load prior to CSLG Install: %s" % str(e))

    def installCVSM(self, service=True, cli=False):
        """Install the CVSM service on a Windows VM."""
        cvsmiso = None
        cvsmver = xenrt.TEC().lookup("CVSM_VERSION", None)

        # Using Workaround CVSM2230
        self.installCVSM2230Workaround()

        if cvsmver:
            cvsmiso = xenrt.TEC().getFile("%s/storagelink-retail-%s.iso" %
                                          (xenrt.TEC().lookup("CVSM_INPUTDIR"),
                                           cvsmver))
            if not cvsmiso:
                cvsmiso = xenrt.TEC().getFile("%s/storagelink-%s.iso" %
                                              (xenrt.TEC().lookup("CVSM_INPUTDIR"),
                                               cvsmver))

        if not cvsmiso:
            cvsmiso = xenrt.TEC().getFile("%s/storagelink.iso" %
                                          (xenrt.TEC().lookup("CVSM_INPUTDIR")))
        if not cvsmiso:
            raise xenrt.XRTError("Unable to locate a StorageLink ISO")
        mount = xenrt.rootops.MountISO(cvsmiso)
        mountpoint = mount.getMount()
        try:
            relpaths = []
            if service:
                cslg_service_setup_relpath = None
                for possiblerelpath in \
                    ["StorageLink/cslg_service_setup_ent.exe",
                     "StorageLink/cslg_service_setup.exe"]:
                    if os.path.exists("%s/%s" % (mountpoint, possiblerelpath)):
                        cslg_service_setup_relpath = possiblerelpath
                        break
                if cslg_service_setup_relpath:
                    relpaths.append(cslg_service_setup_relpath)
                else:
                    raise xenrt.XRTError(\
                        "Cannot locate CSLG service setup EXE")
            if cli:
                relpaths.append("StorageLink/csl_admin_setup.exe")
            for relpath in relpaths:
                rempath = "c:\\%s" % (os.path.basename(relpath))
                if not os.path.exists("%s/%s" % (mountpoint, relpath)):
                    raise xenrt.XRTError(\
                        "File not found on StorageLink CD: %s" % (relpath))
                self.xmlrpcSendFile("%s/%s" % (mountpoint, relpath), rempath)

                try:
                    self.xmlrpcExec("%s /S" % (rempath))
                except Exception, e:
                    raise xenrt.XRTError("CVSM item %s failed to install: %s" %
                                         (relpath, str(e)))
            # If we installed the service install a license server as well
            if service:
                ls = self.getV6LicenseServer()
                ls.addLicense("CVSM2")
                xenrt.sleep(60)

            # need to install additional certs as of 19/01/2012
            # http://support.citrix.com/article/CTX131994

            if service:
                self.xmlrpcUnpackTarball("%s/cvsm.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")
                self.xmlrpcExec('copy /Y c:\\cvsm\\* "C:\\Program Files\\Citrix\\StorageLink\\Server\\"')
                self.xmlrpcExec('net stop "Citrix StorageLink Gateway Service"')
                self.xmlrpcExec('net start "Citrix StorageLink Gateway Service"')
            elif cli:
                self.xmlrpcUnpackTarball("%s/cvsm.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")
                self.xmlrpcExec('copy /Y c:\\cvsm\\* "C:\\Program Files\\Citrix\\StorageLink\\Client\\"')

        finally:
            mount.unmount()

    def installCVSMCLI(self):
        """Install the CVSM CLI on a Windows VM."""
        self.installCVSM(service=False, cli=True)

    def installKirkwood(self):
        """Install the WLB (Kirkwood or later) load balancing server."""
        xenrt.sleep(120)
        self.xmlrpcExec("net user kirkwood kirkwood /add")
        if self.xmlrpcGetArch() == "amd64":
            installer = "WorkloadBalancingx64.msi"
        else:
            installer = "WorkloadBalancing.msi"
        kirkwood = xenrt.TEC().getFile(\
            "%s/%s/%s" % (xenrt.TEC().lookup("WLB_INPUTDIR"),
                          xenrt.TEC().lookup("WLB_VERSION"),
                          installer))

        self.xmlrpcSendFile(kirkwood, "c:\\%s" % (installer))

        try:
            self.xmlrpcExec('msiexec /package c:\\%s '
                            '/quiet /l*v c:\\wlb.txt '
                            'PREREQUISITES_PASSED="1" '
                            'IAGREE="TRUE" '
                            'InstallMode="typical" '
                            'DBNAME="xenrtwlb" '
                            'SERVEREDIT="%s\\SQLExpress" '
                            'DATABASESERVER="%s\\SQLExpress" '
                            'ACCOUNTNAME="kirkwood" '
                            'ACCOUNTPASSWORD="kirkwood" '
                            'USERORGROUPACCOUNT="kirkwood" '
                            'HTTPS_CB="1" '
                            'HTTPS_PORT="8012" '
                            'WEBSERVICE_USER_CB="1" '
                            'CERT_CHOICE="0" '
                            'CERTNAMEPICKED="cn=wlb-cert1" '
                            'TARGETDIR="C:\\" '
                            'INSTALLDIR="C:\\Program Files\\Citrix\\WLB" '
                            'ADDLOCAL="All"' %
                            (installer,
                             self.xmlrpcGetEnvVar("COMPUTERNAME"),
                             self.xmlrpcGetEnvVar("COMPUTERNAME")))
        finally:
            self.xmlrpcGetFile2("c:\\wlb.txt", "%s/wlb-install.txt" % (xenrt.TEC().getLogdir()))
        self.xmlrpcExec("netsh firewall set portopening TCP 8012 WLB")

    def installSQLServer2005CompatibilityPack(self):
        """Install SQL Server 2005 compatibility pack."""
        self.xmlrpcUnpackTarball("%s/sqlcomp.tgz" %
                                 (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                 "c:\\")
        if self.xmlrpcGetArch() == "amd64":
            self.xmlrpcExec("c:\\sqlcomp\\SQLServer2005_BC_x64.msi /quiet /norestart",
                             timeout=3600)
        else:
            self.xmlrpcExec("c:\\sqlcomp\\SQLServer2005_BC.msi /quiet /norestart",
                             timeout=3600)
        self.reboot()

    def installSQLServer2005(self, extraArgs=""):
        """Install SQL Server 2005 Express."""
        self.installDotNet2()
        self.installWindowsInstaller()
        self.xmlrpcUnpackTarball("%s/sqlserver.tgz" %
                                 (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                 "c:\\")
        exe = self.xmlrpcGetArch() ==  "amd64" and "sqlexpr.exe" or "sqlexpr32.exe"
        self.xmlrpcExec(("c:\\sqlserver\\%s -q /norebootchk "
                         "/qn reboot=ReallySuppress addlocal=all "
                         "instancename=SQLEXPRESS SQLAUTOSTART=1 " % exe)
                        + extraArgs,
                        timeout=3600)
        self.reboot()

    def _installPVS(self, path, exe_name):
        arch = self.windows and self.xmlrpcGetArch() or self.getBasicArch()
        exe = exe_name +\
              (arch.endswith("64") and "_x64" or "") +\
              (self.windows and ".exe" or ".run")
        src = "%s/%s/%s/%s" % (xenrt.TEC().lookup("TEST_TARBALL_BASE"),
                               "pvs", path, exe)
        dst = self.tempDir()
        dst = dst + (self.windows and "\\" or "/") + exe
        if self.windows:
            self.xmlrpcFetchFile(src, dst)
            rc = self.xmlrpcExec(('%s /s /v"/qn /l*v c:\\%s.log /norestart"'
                                  % (dst, exe_name)),
                                 timeout=3600, returnerror=False, returnrc=True)
            self.xmlrpcGetFile("c:\\%s.log" % (exe_name),
                               "%s/%s.log" % (xenrt.TEC().getLogdir(), exe_name))
            if rc == 3010:
                self.reboot()
            elif rc != 0:
                raise xenrt.XRTFailure("PVS installation command %s failed with "
                                       "error code %d." % (exe_name, rc))
        else:
            self.execcmd("wget %s -O %s" % (src, dst))
            self.execcmd("chmod +x %s" % dst)
            self.execcmd(dst)

    def installWindowsNFSClient(self):
        """Installs a Windows NFS client. Requires Win2008R2 or Win7 Ultimate"""

        self.xmlrpcExec("start /w ocsetup ServicesForNFS-ClientOnly")
        self.xmlrpcExec("start /w ocsetup ClientForNFS-Infrastructure")

    def installPVSServer(self):
        """Install PVS server program."""
        self._installPVS("Server", "PVS_Server")

    def installPVSClient(self):
        """Install PVS client program."""
        if self.windows:
            self._installPVS("Device", "PVS_Device")
        else:
            self._installPVS("linux", "PVS_LinuxDevice")

    def installKB932532(self):
        """Install Windows update KB932532."""
        self.xmlrpcUnpackTarball("%s/kb932532.tgz" %
                                 (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                 "c:\\")
        if not self.xmlrpcWindowsVersion() == "5.2":
            xenrt.TEC().logverbose("This update only applies to Windows 2003.")
            return
        if self.xmlrpcGetArch() == "amd64":
            self.xmlrpcExec("c:\\kb932532\\WindowsServer2003.WindowsXP-KB932532-x64-ENU.exe "
                            "/quiet /norestart",
                             timeout=3600, returnerror=False)
        else:
            self.xmlrpcExec("c:\\kb932532\\WindowsServer2003-KB932532-x86-ENU.exe "
                            "/quiet /norestart",
                             timeout=3600, returnerror=False)
        self.reboot()

    def installWindowsInstaller(self):
        """Install Windows Installer 4.5."""
        self.xmlrpcUnpackTarball("%s/wininstaller.tgz" %
                                 (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                 "c:\\")
        if self.xmlrpcWindowsVersion() == "6.0":
            if self.xmlrpcGetArch() == "amd64":
                self.xmlrpcExec("c:\\wininstaller\\Windows6.0-KB942288-v2-x64.msu /quiet /norestart",
                                 timeout=3600, returnerror=False)
            else:
                self.xmlrpcExec("c:\\wininstaller\\Windows6.0-KB942288-v2-x86.msu /quiet /norestart",
                                 timeout=3600, returnerror=False)
        elif self.xmlrpcWindowsVersion() == "5.1":
            if self.xmlrpcGetArch() == "amd64":
                raise xenrt.XRTError("No 64-bit XP Windows Installer available")
            self.xmlrpcExec("c:\\wininstaller\\WindowsXP-KB942288-v3-x86.exe /quiet /norestart",
                            timeout=3600, returnerror=False)
        else:
            if self.xmlrpcGetArch() == "amd64":
                self.xmlrpcExec("c:\\wininstaller\\WindowsServer2003-KB942288-v4-x64.exe /quiet /norestart",
                                 timeout=3600, returnerror=False)
            else:
                self.xmlrpcExec("c:\\wininstaller\\WindowsServer2003-KB942288-v4-x86.exe /quiet /norestart",
                                 timeout=3600, returnerror=False)
        self.reboot()

    def installWindowsDDK(self, ddkLocation="c:\\ddkinstall"):
        if self.xmlrpcDirExists(ddkLocation):
            return
        self.getCD("w2k3eesp1_ddk.iso", "c:\\ddk")
        self.xmlrpcExec("c:\\ddk\\x86\\kitsetup.exe /d%s "
                        "/g\"Build Environment\" "
                        "/g\"Network Samples\"" % (ddkLocation),
                         timeout=7200)

    def compileWindowsProgram(self, source):
        ddkpath = "c:\\ddkinstall"
        self.installWindowsDDK(ddkLocation=ddkpath)
        build = self.xmlrpcTempDir(path='c:\\users\\admini~1\\appdata\\local\\')
        self.xmlrpcSendRecursive(source, build)
        script = """
call %s\\bin\\setenv.bat %s fre WNET
cd %s
build -nmake "/f %s\\bin\\makefile.new"
""" % (ddkpath, ddkpath, build, ddkpath)
        self.xmlrpcExec(script)
        return "%s\\i386" % (build)

    def installJava(self):
        """Install Java into a Windows XML-RPC guest"""
        d = xenrt.TEC().tempDir()
        xenrt.getTestTarball("windows-java",
                             extract=True,
                             copy=False,
                             directory=d)
        #if self.xmlrpcGetArch() == "x86":
        exe = glob.glob("%s/windows-java/jre-*i586*.exe" % (d))[0]
        #else:
        #    exe = glob.glob("%s/windows-java/jre-*amd64*.exe" % (d))[0]
        self.xmlrpcSendFile(exe,
                            "c:\\%s" % (os.path.basename(exe)),
                            usehttp=True)
        self.xmlrpcExec("c:\\%s /s /v\"/qn\"" % (os.path.basename(exe)), timeout=3600)

        if self.xmlrpcGetArch() == "amd64":
            jpath = self.xmlrpcGlobpath("c:\\program files*\\java\\*\\bin")[0]
            self.xmlrpcExec("dir \"%s\"" % (jpath))
            self.xmlrpcExec("setx /M PATH \"%%PATH%%;%s\"" % (jpath))
            self.xmlrpcReboot()
            xenrt.sleep(60)
            self.waitforxmlrpc(600)
            xenrt.TEC().logverbose("Path after reboot: %s" %
                                   (self.xmlrpcGetEnvVar("PATH")))

    def installVCRedist(self):
        """Install the VC++ redistributables"""
        if self.xmlrpcFileExists("c:\\windows\\system32\\msvcr100.dll"):
            return
        self.xmlrpcUnpackTarball("%s/vcredist.tgz" %
                                 (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                 "c:\\")
        exe = self.xmlrpcGetArch() == "amd64" and "vcredist_x64.exe" or "vcredist_x86.exe"
        self.xmlrpcExec("c:\\vcredist\\%s /q /norestart" % exe,
                        timeout=3600, returnerror=False)

    def installDirectX(self):
        if not self.xmlrpcFileExists("c:\\directx\\directx_Jun2010_redist.exe"):
            self.xmlrpcUnpackTarball("%s/directx.tgz" %
                                     (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                     "c:\\")
        if not self.xmlrpcFileExists("c:\\windows\\system32\\d3dx9_43.dll"):
            if not self.xmlrpcFileExists("c:\\directxtemp\\dxsetup.exe"):
                self.xmlrpcExec("c:\\directx\\directx_Jun2010_redist.exe /Q /T:c:\\directxtemp",
                                timeout=3600, returnerror=False)
            self.xmlrpcExec("c:\\directxtemp\\dxsetup.exe /silent",
                            timeout=3600, returnerror=False)

    def startGPUWorkloads(self):
        self.installDirectX()
        gpuWorkloads = []
        gpuWorkloads.append(("softparticles", self.xmlrpcStart("c:\\directx\\dxdemos\demos\\direct3d10\\bin\\x86\\softparticles.exe")))
        gpuWorkloads.append(("sparsemorphtargets", self.xmlrpcStart("c:\\directx\\dxdemos\demos\\direct3d10\\bin\\x86\\sparsemorphtargets.exe")))
        gpuWorkloads.append(("nbodygravity", self.xmlrpcStart("c:\\directx\\dxdemos\demos\\direct3d10\\bin\\x86\\nbodygravity.exe")))
        return gpuWorkloads

    def checkGPUWorkloads(self, workloads):
        for w in workloads:
            (name, pid) = w
            if self.xmlrpcPoll(pid):
                raise xenrt.XRTFailure("Workload %s (pid %d) has stopped running" % (name, pid))

    def installDotNet2(self):
        """Install .NET 2.0 into a Windows XML-RPC guest"""
        g = self.xmlrpcGlobPattern("c:\\windows\\Microsoft.NET\\Framework\\v2*\\mscorlib.dll")
        if len(g) > 0:
            xenrt.TEC().logverbose(".NET already installed")
            return
        if self.xmlrpcWindowsVersion() == "5.1":
            # CA-41364 need a newer version of windows installer
            self.installWindowsInstaller()
        self.xmlrpcUnpackTarball("%s/dotnet.tgz" %
                                 (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                 "c:\\")
        exe = self.xmlrpcGetArch() == "amd64" and "NetFx20SP2_x64.exe" or "NetFx20SP2_x86.exe"
        self.xmlrpcExec("c:\\dotnet\\%s /q /norestart" % exe,
                        timeout=3600, returnerror=False)
        self.reboot()

    def isDotNet35Installed(self):
        try:
            val = self.winRegLookup('HKLM', 'SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v3.5', 'Install', healthCheckOnFailure=False)
        except:
            val = 0

        if val == 1:
            xenrt.TEC().logverbose(".NET 3.5 already installed.")
        else:
            xenrt.TEC().logverbose(".NET 3.5 not installed.")

        return val == 1

    def installDotNet35(self):
        """Install .NET 3.5 into a Windows XML-RPC guest"""
        if self.isDotNet35Installed():
            return

        xenrt.TEC().logverbose("Installing .Net3.5 for: %s" % (self.distro))
        if self.distro.startswith('ws08r2'):
            filename = "c:\\xrtInstallNet35.ps1"
            fileData = """Import-Module ServerManager
Add-WindowsFeature as-net-framework"""
            self.xmlrpcWriteFile(filename=filename, data=fileData)
            self.enablePowerShellUnrestricted()

            rData = self.xmlrpcExec('%s' % (filename),
                                     desc='Install .Net 3.5',
                                     returndata=False, returnerror=True,
                                     timeout=1200, powershell=True)
        elif self.distro.startswith('win8') or self.distro.startswith('ws12'):
            self.changeCD('%s.iso'%(self.distro))
            xenrt.sleep(60)
            self.xmlrpcExec("dism.exe /online /enable-feature /featurename:NetFX3 /All /Source:D:\sources\sxs /LimitAccess",timeout=3600)
        else:
            self.xmlrpcUnpackTarball("%s/dotnet35.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\", patient=True)
            self.xmlrpcExec("c:\\dotnet35\\dotnetfx35.exe /q /norestart", timeout=3600, returnerror=False)
            self.reboot()

    def isDotNet4Installed(self):
        try:
            val = self.winRegLookup('HKLM', 'SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v4\\Client', 'Install', healthCheckOnFailure=False)
        except:
            val = 0

        if val ==  1:
            xenrt.TEC().logverbose(".NET 4 already installed.")
        else:
            xenrt.TEC().logverbose(".NET 4 not installed.")

        return val ==  1

    def installDotNet4(self):
        """Install .NET 4 into a Windows XML-RPC guest"""
        if self.isDotNet4Installed():
            return

        xenrt.TEC().logverbose("Installing .NET 4.0.")
        self.xmlrpcCreateDir("c:\\dotnet40logs")
        self.xmlrpcUnpackTarball("%s/dotnet40.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\", patient=True)
        self.xmlrpcExec("c:\\dotnet40\\dotnetfx40.exe /q /norestart /log c:\\dotnet40logs\\dotnet40log", timeout=3600, returnerror=False)
        self.reboot()

    def getDotNet45Version(self):
        version = None
        try:
            rawVersion = self.winRegLookup('HKLM', 'SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v4\\Full', 'Release', healthCheckOnFailure=False)
            if rawVersion == 378389:
                version = '4.5'
            elif rawVersion == 378675 or rawVersion == 378758:
                version = '4.5.1'
            elif rawVersion == 379893:
                version = '4.5.2'
            else:
                xenrt.TEC().logverbose('Unknown .Net 4.5 version found: %d' % (rawVersion))
        except:
            xenrt.TEC().logverbose('No .Net 4.5 version found')

        if version:
            xenrt.TEC().logverbose('Detected %s .Net version installed on guest %s' % (version, self.name))
        return version

    def installDotNet451(self):
        """Install .NET 4.5.1 into a Windows XML-RPC guest"""
        currentDotNet45Version = self.getDotNet45Version()
        if currentDotNet45Version == None or currentDotNet45Version == '4.5':
            xenrt.TEC().logverbose("Installing .NET 4.5.1.")
            self.xmlrpcCreateDir("c:\\dotnet451logs")
            self.xmlrpcUnpackTarball("%s/dotnet451.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\", patient=True)
            self.xmlrpcExec("c:\\dotnet451\\NDP451-KB2858728-x86-x64-AllOS-ENU.exe /q /norestart /log c:\\dotnet451logs\\dotnet451log", timeout=3600, returnerror=False)
            self.reboot()
        else:
            xenrt.TEC().logverbose('.NET %s version already installed' % (currentDotNet45Version))

    def installCloudManagementServer(self):
        manSvr = xenrt.lib.cloud.ManagementServer(self)
        manSvr.installCloudManagementServer()

    def installMarvin(self):
        import testcases.cloud.marvin
        testcases.cloud.marvin.RemoteNoseInstaller(self).install()

    def installTestComplete(self):
        """Install TestComplete into a Windows XML-RPM guest"""

        if self.xmlrpcGlobPattern("C:\\Program Files\\Automated QA\\TestComplete 7\\Bin\\TestComplete.exe"):
            xenrt.TEC().logverbose("TestComplete already installed")
            return

        xenrt.TEC().logverbose("Installing TestComplete")
        self.xmlrpcUnpackTarball("%s/testcomplete.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")
        self.xmlrpcStart("c:\\testcomplete\\NagKill.exe")
        self.xmlrpcExec("c:\\testcomplete\\setup.exe /s", timeout=3600, returnerror=False)

    def installWIC(self):
        self.xmlrpcUnpackTarball("%s/wic.tgz" %
                             (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                             "c:\\")
        exe = self.xmlrpcGetArch() == "amd64" and "wic_x64_enu.exe" or "wic_x86_enu.exe"
        self.xmlrpcExec("c:\\wic\\%s /quiet /norestart" % exe,
                        timeout=3600, returnerror=False)

        # CA-114127 - sleep to stop this interfering with .net installation later??
        xenrt.sleep(120)

    def installAutoIt(self, withAutoItX=False):
        """
        Install AutoIt3 interpreter and compiler into a Windows XML-RPC guest.
        The path to the autoit interpreter is returned.
        """
        is_x64 = self.xmlrpcGetArch() == "amd64"
        autoit = "c:\\Program Files" + (is_x64 and " (x86)" or "") + \
                 "\\AutoIt3\\AutoIt3" + (is_x64 and "_x64" or "") + ".exe"
        if self.xmlrpcGlobPattern(autoit):
            xenrt.TEC().logverbose("AutoIt already installed")
        else:
            tempdir = self.xmlrpcTempDir()
            self.xmlrpcUnpackTarball("%s/autoit.tgz" %
                                     (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                     tempdir)
            self.xmlrpcExec(tempdir + "\\autoit\\autoit-v3-setup.exe /S")
            assert self.xmlrpcGlobPattern(autoit)
        if withAutoItX:
            self._xmlrpc().installAutoItX()
        return autoit

    def getAutoItX(self):
        self.installAutoIt(withAutoItX=True)
        return self._xmlrpc().autoitx

    def getPowershellVersion(self):
        version = 0.0
        try:
            version = float(self.winRegLookup("HKLM", "SOFTWARE\\Microsoft\\PowerShell\\1\\PowerShellEngine", "PowerShellVersion", healthCheckOnFailure=False))
            version = float(self.winRegLookup("HKLM", "SOFTWARE\\Microsoft\\PowerShell\\3\\PowerShellEngine", "PowerShellVersion", healthCheckOnFailure=False))
        except:
            pass
        return version

    def installPowerShell(self):
        """Install PowerShell into a Windows XML-RPC guest."""
        if self.getPowershellVersion() >= 1.0:
            xenrt.TEC().logverbose("PowerShell 1.0 or above installed.")
            return
        self.installDotNet2()
        exe = ""
        if self.xmlrpcWindowsVersion() == "6.0":
            try:
                self.xmlrpcExec("servermanagercmd -install PowerShell")
                return
            except xenrt.XRTFailure, e:
                if re.search("not recognized", e.data):
                    xenrt.TEC().logverbose("Doesn't look like we have "
                                           "servermanagercmd. Guessing "
                                           "this is Vista. (%s)" % (e.data))
                    exe = "powershell.msu"
                else:
                    xenrt.TEC().logverbose("Exception: %s" % (e.data))
                    raise
        # XP needs a different installer
        elif self.xmlrpcWindowsVersion() == "5.1":
            exe = "powershell-xp.exe"
        else:
            exe = "powershell.exe"
        t = self.xmlrpcTempDir()
        self.xmlrpcUnpackTarball("%s/powershell.tgz" %
                                (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                 t)
        self.xmlrpcExec("%s\\powershell\\%s\\%s /quiet" %
                        (t, self.xmlrpcGetArch(), exe))

    def installPowerShell20(self, reboot=True):
        """Install PowerShell 2.0 into a Windows XML-RPC guest. Note this
        op requires a reboot to finish install using Win Update"""
        if self.getPowershellVersion() >= 2.0:
            xenrt.TEC().logverbose("PowerShell 2.0 or above installed.")
            return

        if self.xmlrpcWindowsVersion() == "6.0":
            if self.xmlrpcGetArch() == "amd64":
                exe = "Windows6.0-KB968930-x64.msu"
            else:
                exe = "Windows6.0-KB968930-x86.msu"
        elif self.xmlrpcWindowsVersion() == "5.2":
            self.installDotNet2()
            if self.xmlrpcGetArch() == "amd64":
                exe = "WindowsServer2003-KB968930-x64-ENG.exe"
            else:
                exe = "WindowsServer2003-KB968930-x86-ENG.exe"
        elif self.xmlrpcWindowsVersion() == "5.1":
            self.installDotNet2()
            exe = "WindowsXP-KB968930-x86-ENG.exe"
        else:
            raise xenrt.XRTError("PowerShell 2.0 installer is not \
            available for Windows version %s" % self.xmlrpcWindowsVersion())
        t = self.xmlrpcTempDir()
        self.xmlrpcUnpackTarball("%s/powershell20.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), t)
        self.xmlrpcExec("%s\\powershell20\\%s /quiet /norestart" % (t, exe), returnerror=False, timeout=600)
        if reboot:
            self.reboot()

    def installPowerShell30(self, reboot=True, verifyInstall=True):
        """Install PowerShell 3.0 into a Windows XML-RPC guest. Note this
        op requires a reboot to finish install using Win Update"""
        if self.getPowershellVersion() >= 3.0:
            xenrt.TEC().logverbose("PowerShell 3.0 or above installed.")
            return

        if self.xmlrpcWindowsVersion() == "6.1":
            self.installDotNet4()
            if self.xmlrpcGetArch() == "amd64":
                exe = "Windows6.1-KB2506143-x64.msu"
            else:
                exe = "Windows6.1-KB2506143-x86.msu"
        else:
            raise xenrt.XRTError("PowerShell 3.0 installer is not \
            available for Windows version %s" % self.xmlrpcWindowsVersion())
        t = self.xmlrpcTempDir()
        self.xmlrpcUnpackTarball("%s/powershell30.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), t)
        self.xmlrpcExec("%s\\powershell30\\%s /quiet /norestart" % (t, exe), returnerror=False, timeout=600)
        if reboot:
            self.reboot()
            if verifyInstall and self.getPowershellVersion() < 3.0:
                raise xenrt.XRTError('Failed to install PowerShell v3.0')

    def enablePowerShellUnrestricted(self):
        """Allow the running of unsigned PowerShell scripts."""
        self.winRegAdd("HKLM",
                       "SOFTWARE\\Microsoft\\PowerShell\\1\\ShellIds\\Microsoft.PowerShell",
                       "ExecutionPolicy",
                       "SZ",
                       "Unrestricted")

    def installPowerShellSnapIn(self, snapInDirName="XenServerPSSnapIn"):
        """Install the XenCenter PowerShell snap-in."""
        if isinstance(self, xenrt.lib.xenserver.guest.ClearwaterGuest):
            sdk = xenrt.TEC().getFile("xe-phase-2/XenServer-SDK.zip")
            tempDir = xenrt.TEC().tempDir()
            xenrt.command("cp %s %s" % (sdk, tempDir))
            xenrt.command("cd %s && unzip XenServer-SDK.zip" % tempDir)
            srcPath = os.path.join(tempDir, "XenServer-SDK/XenServerPowerShell/XenServerPSModule")
            xenrt.TEC().logverbose("Sending dir to %s" % srcPath)
            targetPath="C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\Modules\\XenServerPSModule"
            self.xmlrpcExec("mkdir %s" % targetPath)
            self.xmlrpcSendRecursive(srcPath, targetPath)
            testRunner = os.path.join(tempDir, "XenServer-SDK/XenServerPowerShell/samples/AutomatedTestCore.ps1")
            xenrt.TEC().logverbose("Sending test runner %s to %s" % (testRunner, targetPath))
            self.xmlrpcSendFile(testRunner, targetPath + "\\AutomatedTestCore.ps1", usehttp=True)

        elif isinstance(self, xenrt.lib.xenserver.guest.TampaGuest):
            sdk = xenrt.TEC().getFile("xe-phase-2/XenServer-SDK.zip")
            tempDir = xenrt.TEC().tempDir()
            xenrt.command("cp %s %s" % (sdk, tempDir))
            xenrt.command("cd %s && unzip XenServer-SDK.zip" % tempDir)
            msi = xenrt.command("(cd / && ls %s/XenServer-SDK/%s/*.msi)" % (tempDir, snapInDirName)).strip()
            self.xmlrpcSendFile(msi, "c:\\XenServerPSSnapIn.msi", usehttp=True)
            self.xmlrpcExec("msiexec /i c:\\XenServerPSSnapIn.msi /qn /lv* c:\\pssnapininstall.log")

        else:
            snapinstaller = xenrt.TEC().getFile("xe-phase-2/XenServerPSSnapIn.msi")
            self.xmlrpcSendFile(snapinstaller, "c:\\XenServerPSSnapIn.msi", usehttp=True)
            self.xmlrpcExec("msiexec /i c:\\XenServerPSSnapIn.msi /qn /lv* c:\\pssnapininstall.log")

    def getVideoControllerInfo(self):
        """Retrieves the HVM guest Video Settings with PowerShell using Windows Management Instrumentation (WMI)."""

        # Requires Powershell pre-installed to query the Video Settings through WMI.
        self.installPowerShell()

        # Obtain the HVM guest graphics settings with PowerShell using Windows Management Instrumentation (WMI).
        psScript = "powershell Get-WmiObject -Class Win32_VideoController"
        configString = self.xmlrpcExec(psScript, returndata = True, powershell=False)
        if configString:
            # Convert the contents of a video controller output file (passed as configString) into a dictionary of key value pairs.
            lines = configString.splitlines()
            # Remove all empty lines
            #lines = filter(lambda x:not x.startswith(' '), lines) # Not required as the following command does it.
            # Find out lines with key / value pairs
            lines = filter(lambda x:len(x.split(':')) == 2, lines)
            configDict = {}
            for line in lines:
                (key, value) = line.split(':')
                configDict[key.strip()] = value.strip()
            return configDict
        else:
            raise xenrt.XRTFailure("The requested Video Settings command returned an empty value !!!")

    def installNetperf(self, config_params = ""):
        """Install netperf client into the guest"""
        if self.windows:
            if not self.xmlrpcFileExists("c:\\netperf.exe"):
                d = xenrt.TEC().tempDir()
                xenrt.getTestTarball("netperf",
                                     extract=True,
                                     copy=False,
                                     directory=d)
                #if self.xmlrpcGetArch() == "amd64":
                #    path = "netperf/x64"
                #else:
                path = "netperf"

                for fn in ["netperf.exe", "netserver.exe"]:
                    exe = "%s/%s/%s" % (d, path, fn)
                    self.xmlrpcSendFile(exe,
                                        "c:\\%s" % (os.path.basename(exe)),
                                        usehttp=True)
                # Required by netserver.exe.
                try:
                    self.xmlrpcExec("mkdir c:\\temp")
                except:
                    pass
                try:
                    self.xmlrpcExec("netsh firewall set allowedprogram " + \
                                    "c:\\netserver.exe")
                except:
                    pass
        else:
            if self.execcmd("test -e /usr/local/bin/netperf -o "
                            "     -e /usr/bin/netperf",
                            retval="code") != 0:
                workdir = string.strip(self.execcmd("mktemp -d /tmp/XXXXXX"))
                self.execcmd("wget '%s/netperf.tgz' -O %s/netperf.tgz" %
                             (xenrt.TEC().lookup("TEST_TARBALL_BASE"),
                              workdir))
                self.execcmd("tar -zxf %s/netperf.tgz -C %s" % (workdir, workdir))
                self.execcmd("tar -zxf %s/netperf/netperf-2.4.3.tar.gz -C %s" %
                             (workdir, workdir))
                self.execcmd("cd %s/netperf-2.4.3 && patch -p1 < "
                             "%s/netperf/XRT-5722.patch" % (workdir, workdir))
                self.execcmd("cd %s/netperf-2.4.3 && ./configure %s" %
                               (workdir, config_params))
                self.execcmd("cd %s/netperf-2.4.3 && make" % (workdir))
                self.execcmd("cd %s/netperf-2.4.3 && make install" %
                             (workdir))
                self.execcmd("rm -rf %s" % (workdir))

    def installIperf(self, version=""):
        """Install iperf into the container (requires gcc/make already installed) """

        if version=="":
            sfx = "2.0.4"
        else:
            sfx = version

        if self.windows:
            self.xmlrpcUnpackTarball("%s/iperf-bin%s.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE"), version), "c:\\")
            self.xmlrpcExec("move c:\\iperf-bin%s\\* c:\\" % (version,))
        else:
            if self.execcmd("test -e /usr/local/bin/iperf -o "
                            "     -e /usr/bin/iperf",
                            retval="code") != 0:
                workdir = string.strip(self.execcmd("mktemp -d /tmp/XXXXXX"))
                self.execcmd("wget '%s/iperf%s.tgz' -O %s/iperf%s.tgz" %
                             (xenrt.TEC().lookup("TEST_TARBALL_BASE"), version,
                             workdir, version))
                self.execcmd("tar -zxf %s/iperf%s.tgz -C %s" % (workdir, version, workdir))
                self.execcmd("tar -zxf %s/iperf%s/iperf-%s.tar.gz -C %s" %
                             (workdir, version, sfx, workdir))
                self.execcmd("cd %s/iperf-%s && ./configure" %
                             (workdir, sfx))
                self.execcmd("cd %s/iperf-%s && make" % (workdir, sfx))
                self.execcmd("cd %s/iperf-%s && make install" %
                             (workdir, sfx))
                self.execcmd("rm -rf %s" % (workdir))
                self.execcmd("mkdir ./iperf && cp /usr/local/bin/iperf ./iperf/iperf")

    def startIperf(self):
        """Starts iperf as server in the Guest"""
        if self.windows:
            self.xmlrpcExec("start c:\\iperf -s", returnerror=False, ignoredata=True)
            time.sleep(10) # iperf -s takes some time to kick in
        else:
            raise xenrt.XRTError("Unimplemented")

    def installLatency(self):
        """Install Latency into the guest"""

        workdir = string.strip(self.execcmd("mktemp -d /tmp/XXXXXX"))
        self.execcmd("wget -O - '%s/latency.tgz' | tar -xz -C %s" %
                     (xenrt.TEC().lookup("TEST_TARBALL_BASE"), workdir))

        if self.getBasicArch() == "x86-64":
            self.execcmd("cp %s/latency/latency.x86_64 /root/latency" % workdir)
        else:
            self.execcmd("cp %s/latency/latency.x86_32 /root/latency" % workdir)
        self.execcmd("rm -rf %s" % workdir)

    def installUDPGen(self):
        """Install udpgen into a host"""

        workdir = string.strip(self.execcmd("mktemp -d /tmp/XXXXXX"))
        self.execcmd("wget -O - '%s/udpgen.tgz' | tar -xz -C %s" %
                     (xenrt.TEC().lookup("TEST_TARBALL_BASE"), workdir))

        if self.getBasicArch() == "x86-64":
            self.execcmd("cp %s/udpgen/udptx.x86_64 /root/udptx" % workdir)
            self.execcmd("cp %s/udpgen/udprx.x86_64 /root/udprx" % workdir)
        else:
            self.execcmd("cp %s/udpgen/udptx.x86_32 /root/udptx" % workdir)
            self.execcmd("cp %s/udpgen/udprx.x86_32 /root/udprx" % workdir)
        self.execcmd("rm -rf %s" % workdir)

    def installKernBench(self):
        """Install KernBench into the guest"""

        self.execcmd("rm -rf /root/kernbench3.10")
        self.execcmd("wget -O - '%s/kernbench3.10.tgz' | tar -xz -C /root" %
                     xenrt.TEC().lookup("TEST_TARBALL_BASE"))

    def installFioWin(self):
        """Install Fio into the Windows guest"""

        self.xmlrpcUnpackTarball("%s/fiowin.tgz" % xenrt.TEC().lookup("TEST_TARBALL_BASE"), "c:\\")

        if self.getBasicArch() == "x86-64":
            self.xmlrpcExec("move c:\\fiowin\\x64\\fio.exe c:\\")
        else:
            self.xmlrpcExec("move c:\\fiowin\\x86\\fio.exe c:\\")

    def installIOMeter(self):
        """Install IOMeter into the guest"""

        self.xmlrpcUnpackTarball("%s/iometer1.1.0.tgz" % xenrt.TEC().lookup("TEST_TARBALL_BASE"), "c:\\")
        self.xmlrpcExec("move c:\\iometer1.1.0\\* c:\\")

        # Prevent IOMeter license box from appearing
        self.winRegAdd("HKCU",
                       "Software\\iometer.org\\Iometer\\Recent File List",
                       "dummy",
                       "SZ",
                       "")
        self.winRegDel("HKCU",
                       "Software\\iometer.org\\Iometer\\Recent File List",
                       "dummy")
        self.winRegAdd("HKCU",
                       "Software\\iometer.org\\Iometer\\Settings",
                       "Version",
                       "SZ",
                       "1.1.0")

        # Allow through the firewall
        try:
            self.xmlrpcExec('NETSH firewall set allowedprogram '
                            'program="C:\\IOmeter.exe" '
                            'name="Iometer Control/GUI" mode=ENABLE')
        except:
            xenrt.TEC().comment("Error disabling firewall")
        try:
            self.xmlrpcExec('NETSH firewall set allowedprogram '
                            'program="C:\\Dynamo.exe" '
                            'name="Iometer Workload Generator" mode=ENABLE')
        except:
            xenrt.TEC().comment("Error disabling firewall")

    def installVSSTools(self):
        """Install Microsoft VSS tools into a Windows XML-RPC guest"""
        g = self.xmlrpcGlobPattern("c:\\vshadow.exe")
        if len(g) > 0:
            xenrt.TEC().logverbose("VSS tools already installed")
            return
        if self.xmlrpcGetArch() == "amd64":
            prog = "vshadow-x64.exe"
        else:
            prog = "vshadow.exe"
        d = xenrt.TEC().tempDir()
        xenrt.getTestTarball("vss",
                             extract=True,
                             copy=False,
                             directory=d)
        exe = "%s/vss/%s" % (d, prog)
        self.xmlrpcSendFile(exe, "c:\\vshadow.exe", usehttp=True)

    def installCarbonWindowsCLI(self):
        """Installs a Carbon product Windows CLI client."""
        if self.xmlrpcFileExists("c:\\windows\\xe.exe"):
            xenrt.TEC().logverbose("xe.exe already installed")
            return
        # Miami onwards packages xe.exe with the GUI
        if not ((isinstance(self, GenericGuest) and self.host and
                 self.host.productVersion == "Rio") or
                xenrt.TEC().lookup("PRODUCT_VERSION", "unknown") == "Rio"):
            self.installCarbonWindowsGUI()
            xeorigdir = None
            for d in string.split(xenrt.TEC().lookup("XENCENTER_DIRECTORY"),
                                  ";"):
                f = "%s\\xe.exe" % (d)
                if self.xmlrpcFileExists(f):
                    xeorigdir = d
                    xeorig = f
                    break
            if not xeorigdir:
                raise xenrt.XRTError("Cannot find xe.exe")
            self.xmlrpcExec("copy \"%s\" c:\\windows\\xe.exe" % (xeorig))
            self.xmlrpcExec("copy \"%s\\*.dll\" c:\\windows" % (xeorigdir))
            return
        # Rio, get xe.exe from wherever we can find it
        self.installDotNet2()
        # Get the CLI binary from the CD.
        mount = None
        winbin = None
        cds = []

        imageName = xenrt.TEC().lookup("CARBON_CD_IMAGE_NAME", 'main.iso')
        xenrt.TEC().logverbose("Using XS install image name: %s" % (imageName))
        try:
            cd = xenrt.TEC().getFile("xe-phase-1/%s" % (imageName), imageName)
            if cd:
                cds.append(cd)
        except:
            pass
        tmpdir = xenrt.resources.TempDirectory()
        for cd in cds:
            xenrt.util.checkFileExists(cd)
            try:
                mount = xenrt.rootops.MountISO(cd)
                mountpoint = mount.getMount()
                if os.path.exists("%s/client_install/xe.exe" % (mountpoint)):
                    xenrt.TEC().logverbose("Using Windows CLI binary from ISO %s"
                                           % (cd))
                    tmpdir.copyIn("%s/client_install/xe.exe" % (mountpoint))
                    winbin = "%s/xe.exe" % (tmpdir.path())
                    break
            finally:
                mount.unmount()
                mount = None
        if not winbin:
            raise xenrt.XRTError("Could not find xe.exe to install")
        self.xmlrpcSendFile(winbin, "c:\\windows\\xe.exe")

    def installCarbonLinuxCLI(self):
        """Installs a Carbon product Linux CLI client."""
        if self.execcmd("which xe", retval="code") == 0:
            xenrt.TEC().logverbose("xe already installed")
            return
        tmpdir = xenrt.resources.TempDirectory()
        # Get the CLI RPM from the CD.
        mount = None
        rpm = None
        hostarch = self.execcmd("uname -m").strip()
        # Try an explicit path first - this is used for OEM update tests
        # Use static linked version of xe on Dundee if the distro is not Centos 7
        if isinstance(self.host, xenrt.lib.xenserver.DundeeHost) and not self.distro == 'centos7':
            rpmpath = "xe-phase-1/client_install/xe-cli-6.2.0-70442c.i686.rpm"
        else:
            rpmpath = xenrt.TEC().lookup("XE_RPM", None)

        if rpmpath:
            rpm = xenrt.TEC().getFile(rpmpath)
        if not rpm:
            cds = []
            imageName = xenrt.TEC().lookup("CARBON_CD_IMAGE_NAME", 'main.iso')
            xenrt.TEC().logverbose("Using XS install image name: %s" % (imageName))
            try:
                cd = xenrt.TEC().getFile("xe-phase-1/%s" % (imageName), imageName)
                if cd:
                    cds.append(cd)
            except:
                pass
            try:
                cd = xenrt.TEC().getFile("xe-phase-1/linux.iso", "linux.iso")
                if cd:
                    cds.append(cd)
            except:
                pass
            for cd in cds:
                xenrt.util.checkFileExists(cd)
                try:
                    mount = xenrt.rootops.MountISO(cd)
                    mountpoint = mount.getMount()
                    if hostarch != "x86_64":
                        rpms = glob.glob("%s/client_install/xe-cli*86.rpm" %
                                      (mountpoint))
                        rpms.extend(glob.glob(\
                            "%s/client_install/xenenterprise-cli-[0-9]*86.rpm" %
                            (mountpoint)))
                    else:
                        rpms = glob.glob("%s/client_install/xe-cli*86_64.rpm" %
                                      (mountpoint))
                        rpms.extend(glob.glob(\
                            "%s/client_install/xenenterprise-cli-[0-9]*86_64.rpm" %
                            (mountpoint)))
                    if len(rpms) > 0:
                        xenrt.TEC().logverbose("Using CLI RPM %s from ISO %s" %
                                               (os.path.basename(rpms[-1]), cd))
                        tmpdir.copyIn(rpms[-1])
                        rpm = "%s/%s" % (tmpdir.path(), os.path.basename(rpms[-1]))
                        break
                finally:
                    mount.unmount()
                    mount = None
        if not rpm:
            raise xenrt.XRTError("Could not find xe RPM to install")
        if self.execcmd("test -e /etc/debian_version", retval="code") == 0:
            # Extract the RPM here and copy to the destination
            if xenrt.command("cd %s && rpm2cpio %s | cpio -idv" %
                             (tmpdir.path(), rpm), retval="code") != 0:
                raise xenrt.XRTError("Error extracting CLI binary from %s" %
                                     (rpm))
            if xenrt.command("mv %s/opt/xensource/bin/xe %s" %
                             (tmpdir.path(), tmpdir.path()),
                             retval="code") == 0:
                pass
            elif xenrt.command("mv %s/usr/bin/xe %s" %
                               (tmpdir.path(), tmpdir.path()),
                               retval="code") != 0:
                raise xenrt.XRTError("Couldn't find xe in RPM")
            sftp = self.sftpClient()
            sftp.copyTo("%s/xe" % (tmpdir.path()), "/usr/bin/xe")
            sftp.close()
        else:
            # Copy the RPM to the destination and install
            sftp = self.sftpClient()
            sftp.copyTo(rpm, "/tmp/%s" % (os.path.basename(rpm)))
            sftp.close()
            self.execcmd("rpm --install /tmp/%s" % (os.path.basename(rpm)))
            self.execcmd("if [ -e /opt/xensource/bin/xe -a ! -e /usr/bin/xe ];"
                         "  then ln -s /opt/xensource/bin/xe /usr/bin/xe; fi")

    def installCarbonWindowsGUI(self, noAutoDotNetInstall=False, forceFromCD=False):
        """Installs a Carbon product Windows GUI."""
        if self.findCarbonWindowsGUI():
            xenrt.TEC().logverbose("GUI already installed")
            return
        if not noAutoDotNetInstall:
            if isinstance(self.host, xenrt.lib.xenserver.DundeeHost):
                self.installDotNet451()
            elif isinstance(self.host, xenrt.lib.xenserver.CreedenceHost):
                self.installDotNet4()
            elif isinstance(self.host, xenrt.lib.xenserver.BostonHost):
                self.installDotNet35()
            else:
                self.installDotNet2()

        # Get the UI binaries to the VM
        msi = None
        if not forceFromCD:
            msifile = xenrt.TEC().lookup("XENADMIN_INSTALLER", None)
            if msifile:
                msi = xenrt.TEC().getFile(msifile)

            if not msi:
                # See if the host we're running on itself has a copy
                if self.host:
                    msifile = "/opt/xensource/www/XenCenter.msi"
                    tmpdir = xenrt.resources.TempDirectory()
                    sftp = self.host.sftpClient()

                    # If XenCenter.msi doesn't exists we need to extract it from XenCenterSetup.exe
                    if not self.host.execdom0("test -e %s" % (msifile),
                                              retval="code") == 0:
                        exefile = "/opt/xensource/www/XenCenterSetup.exe"
                        if self.host.execdom0("test -e %s" % (exefile),
                                              retval="code") == 0:
                            exe = "%s/XenCenterSetup.exe" % (tmpdir.path())
                            sftp.copyFrom(exefile, exe)
                            xenrt.util.command("cabextract %s -d %s/" % (exe, tmpdir.path()))
                            msi = "%s/XenCenter.msi" % tmpdir.path()
                            if not os.path.exists(msi):
                                raise xenrt.XRTFailure("XenCenter.msi not extracted")

                    elif self.host.execdom0("test -e %s" % (msifile),
                                            retval="code") == 0:
                        msi = "%s/XenCenter.msi" % tmpdir.path()
                        sftp.copyFrom(msifile, msi)

                    sftp.close()

        if not msi:
            # Get the installer from the CD.
            mount = None
            cds = []
            try:
                imageName = xenrt.TEC().lookup("CARBON_CD_IMAGE_NAME", 'main.iso')
                xenrt.TEC().logverbose("Using XS install image name: %s" % (imageName))
                cd = xenrt.TEC().getFile("xe-phase-1/%s" % (imageName), imageName)
                if cd:
                    cds.append(cd)
            except:
                pass
            tmpdir = xenrt.resources.TempDirectory()
            for cd in cds:
                xenrt.util.checkFileExists(cd)
                try:
                    mount = xenrt.rootops.MountISO(cd)
                    mountpoint = mount.getMount()
                    # If XenCenter.msi doesn't exists we need to extract it from XenCenterSetup.exe
                    exepath = "%s/client_install/XenCenterSetup.exe" % (mountpoint)
                    pospath = "%s/client_install/XenCenter.msi" % (mountpoint)
                    if os.path.exists(exepath):
                        xenrt.TEC().logverbose("Using XenCenterSetup.exe from ISO %s" %
                                               cd)
                        tmpdir.copyIn(exepath)
                        xenrt.util.command("cabextract %s/XenCenterSetup.exe -d %s/" % (tmpdir.path(), tmpdir.path()))
                        msi = "%s/XenCenter.msi" % tmpdir.path()
                        if not os.path.exists(msi):
                            raise xenrt.XRTFailure("XenCenter.msi not extracted")

                    elif os.path.exists(pospath):
                        xenrt.TEC().logverbose("Using XenCenter.msi from ISO %s" %
                                               cd)
                        tmpdir.copyIn(pospath)
                        msi = "%s/%s" % (tmpdir.path(),
                                         os.path.basename(pospath))

                finally:
                    mount.unmount()
                    mount = None

        if not msi:
            # Try the same directory as the ISO
            msi = xenrt.TEC().getFile("client_install/XenCenter.msi")
            if not msi:
                msi = xenrt.TEC().getFile("xe-phase-1/client_install/XenCenter.msi")
            if not msi:
               exe = xenrt.TEC().getFile("xe-phase-1/client_install/XenCenterSetup.exe")
               # If XenCenter.msi doesn't exists we need to extract it from XenCenterSetup.exe
               if exe:
                    msi = exe.strip('XenCenterSetup.exe')
                    xenrt.util.command("cabextract %s -d %s/" % (exe, msi))
                    msi = "%s/XenCenter.msi" % msi
        if msi:
            # Perform the install
            xenrt.TEC().logverbose("Installing GUI using MSI installer")

            # CA-120006....sometimes large files like this can fail to copy
            count=5
            for i in range(count):
                try:
                    self.xmlrpcSendFile(msi, "c:\\XenCenter.msi")
                    break
                except Exception, ex:
                    xenrt.TEC().logverbose("Exception: %s" % str(ex))

                    if i == count-1:
                        raise
                    else:
                        xenrt.TEC().logverbose("retrying...")

            try:
                self.xmlrpcExec("msiexec.exe /I c:\\XenCenter.msi /Q /L*v "
                                "c:\\xencenter-install.log", timeout=3600)
            finally:
                try:
                    self.xmlrpcGetFile("c:\\xencenter-install.log",
                                       "%s/xencenter-install.log" %
                                       (xenrt.TEC().getLogdir()))
                except:
                    pass
        else:
            # No MSI, use the zip instead
            xenrt.TEC().logverbose("Installing GUI from zip file")
            testtar = xenrt.TEC().lookup("XENADMIN_ZIPFILE", None)
            if not testtar:
                # Try the same directory as the ISO
                testtar = xenrt.TEC().getFile("xenadmin.zip")
            if not testtar:
                raise xenrt.XRTError("No XenAdmin zip file found")
            d = xenrt.TEC().tempDir()
            xenrt.util.command("unzip %s -d %s" % (testtar, d))

            self.xmlrpcSendRecursive(d, "c:\\")
            try:
                self.xmlrpcExec("COPY "
                                "c:\\XenAdmin\\bin\\Debug\\VNC\\scvncctrl.* "
                                "c:\\XenAdmin\\bin\\Debug")
            except:
                pass
        for lf in string.split(xenrt.TEC().lookup("XENCENTER_LOG_FILE"), ";"):
            self.addExtraLogFile(lf)

        if xenrt.TEC().lookup("XENCENTER_EXE", None):
            xcexe = xenrt.TEC().lookup("XENCENTER_EXE")
            exe = xenrt.TEC().getFile(xcexe)
            self.xmlrpcSendFile(exe, "C:\\Program Files\\Citrix\\XenCenter\\XenCenterMain.exe")
        if xenrt.TEC().lookup("XENMODEL_DLL", None):
            xcexe = xenrt.TEC().lookup("XENMODEL_DLL")
            exe = xenrt.TEC().getFile(xcexe)
            self.xmlrpcSendFile(exe, "C:\\Program Files\\Citrix\\XenCenter\\XenModel.dll")

        # If this build has it, unpack XenCenterTestResources.tar to
        # c:\XenCenterTestResources
        self.xmlrpcDelTree("c:\\XenCenterTestResources")

        xctrtar = None
        if xenrt.TEC().lookup("INPUTDIR", None):
            xctrtar = xenrt.TEC().getFile("XenCenterTestResources.tar",
                                          "xe-phase-1/XenCenterTestResources.tar")
        if xctrtar:
            xctrd = xenrt.TEC().tempDir()
            xenrt.util.command("tar -xf %s -C %s" % (xctrtar, xctrd))
            self.xmlrpcExec("mkdir c:\\XenCenterTestResources")
            self.xmlrpcSendRecursive(xctrd, "c:\\XenCenterTestResources")
            self.xmlrpcExec("dir c:\\XenCenterTestResources")

    def findCarbonWindowsGUI(self):
        exenames = string.split(xenrt.TEC().lookup("XENCENTER_EXE_NAME"), ";")
        for path in string.split(xenrt.TEC().lookup("XENCENTER_DIRECTORY"),
                                 ";"):
            for exe in exenames:
                if self.xmlrpcFileExists("%s\\%s" % (path, exe)):
                    return path, exe
        return None

    def attachXenCenterToHost(self, host=None):
        if not host:
            host = xenrt.TEC().registry.hostGet("RESOURCE_HOST_0")
        ip = host.getIP()
        password = host.password

        (path, exe) = self.findCarbonWindowsGUI()
        self.xmlrpcExec("\"%s\\%s\" connect %s root %s" % (path, exe, ip, password))
        # Send enter to get past the check for updates box
        xenrt.sleep(10)
        self.xmlrpcSendKeys("{ENTER}")

    def installNUnit(self):
        """Install the NUnit package."""
        g = self.xmlrpcGlobPattern("c:\\Program Files\\NUnit*\\bin\\net-2.0"
                                   "\\nunit.exe")
        if len(g) > 0:
            xenrt.TEC().logverbose("NUnit already installed")
            return
        if float(self.xmlrpcWindowsVersion()) <= 5.2:
            self.installDotNet2()

        self.installDotNet35()

        if isinstance(self.host, xenrt.lib.xenserver.DundeeHost):
            self.installDotNet4()

        self.xmlrpcUnpackTarball("%s/nunit.tgz" %
                                 (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                 "c:\\")
        g = self.xmlrpcGlobPattern("c:\\nunit\\NUnit*.msi")
        vers = {}
        for n in g:
            m = re.search("NUnit-(\d+\.\d+\.\d+\.\d+)\.msi", n)
            if m:
                vers[m.group(1)] = n

        verToUse = xenrt.TEC().lookup("NUNIT_VERSION", "2.5.10.11092")
        if not verToUse in vers.keys():
            raise xenrt.XRTError("Can't find NUnit version %s installer" % verToUse)

        self.xmlrpcExec("msiexec /i %s /qn /lv* c:\\nunitinstall.log" %
                        (vers[verToUse]))

    def disableWindowsPasswordComplexityCheck(self):
        self.xmlrpcExec("secedit /export /cfg c:\\password.inf /areas SECURITYPOLICY")
        data = self.xmlrpcReadFile("c:\\password.inf").decode("utf-16LE")
        data = re.sub("PasswordComplexity = 1", "PasswordComplexity = 0", data)
        tfile = xenrt.TEC().tempFile()
        file(tfile, "wb").write(data.encode("utf-16LE"))
        self.xmlrpcSendFile(tfile, "c:\\password.inf")
        self.xmlrpcExec("secedit /import /db c:\\password.sdb /cfg c:\\password.inf")
        self.xmlrpcExec("secedit /configure /db c:\\password.sdb")

    def synchroniseWindowsNTP(self, server):
        self.xmlrpcExec("net time /setsntp:%s" % (server))
        self.xmlrpcExec("net stop w32time")
        self.xmlrpcExec("net start w32time")

    def uninstallWindowsDHCPServer(self):
        # Uninstall the DHCP server component.
        if float(self.xmlrpcWindowsVersion()) < 6.0 :
            dhcpuninstall = """
[NetOptionalComponents]
DHCPServer = 0
"""
            self.xmlrpcCreateFile("c:\\dhcpuninstall.txt", dhcpuninstall)
            self.xmlrpcExec("sysocmgr /i:%%windir%%\\inf\\sysoc.inf "
                            "/u:c:\\dhcpuninstall.txt")
            self.xmlrpcRemoveFile("c:\\dhcpuninstall.txt")
        else:
            self.xmlrpcExec("start /w ocsetup DHCPServer /uninstall /passive /quiet /norestart")

    def installWindowsDHCPServer(self,
                                 interface,
                                 network="192.168.0.0",
                                 server="192.168.0.1",
                                 netmask="255.255.255.0",
                                 start="192.168.0.2",
                                 end="192.168.0.254"):
        # Get the Windows device number for iface and set its IP.
        self.configureNetwork(interface, ip=server, netmask=netmask)

        # Install the DHCP server component.
        if float(self.xmlrpcWindowsVersion()) < 6.0 :
            dhcpinstall = """
[NetOptionalComponents]
DHCPServer = 1
"""
            self.xmlrpcCreateFile("c:\\dhcpinstall.txt", dhcpinstall)
            self.xmlrpcExec("sysocmgr /i:%%windir%%\\inf\\sysoc.inf "
                            "/u:c:\\dhcpinstall.txt")
            self.xmlrpcRemoveFile("c:\\dhcpinstall.txt")
        else:
            self.xmlrpcExec("start /w ocsetup DHCPServer /passive /quiet /norestart")

        # Some OS won't set newly enabled DHCPServer to start automatically
        self.xmlrpcExec("sc config DHCPServer start= auto")
        if self.xmlrpcExec('net start | find "DHCP Server"',
                           returnerror=False, returnrc=True) != 0:
            self.xmlrpcExec("net start DHCPServer")

        # Add a DHCP scope and activate it.
        self.xmlrpcExec("netsh dhcp server "
                        "add scope %s %s scope" % (network, netmask))
        self.xmlrpcExec("netsh dhcp server scope %s "
                        "add iprange %s %s" % (network, start, end))
        self.xmlrpcExec("netsh dhcp server scope %s "
                        "set state 1" % (network))

        # Let DHCP through the firewall.
        try: self.xmlrpcExec('netsh firewall set portopening '
                             'UDP 67 "DHCP Server" ENABLE')
        except: pass
        # Log configuration.
        try: self.xmlrpcExec("netsh dhcp server show bindings")
        except: pass

    def installWindowsTFTPServer(self,
                                 network="192.168.0.0",
                                 server="192.168.0.1",
                                 tftproot="c:\\tftproot",
                                 filename="pxelinux.0"):
        # Install the TFTP Server.
        self.xmlrpcUnpackTarball("%s/pxeserver.tgz" %
                                (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                 tftproot)
        self.xmlrpcExec("move %s\\pxeserver\\*.* "
                        "%s\\" %
                        (tftproot, tftproot))
        self.xmlrpcExec("move %s\\tftpd.exe "
                        "%%systemroot%%\\system32\\tftpd.exe" %
                        (tftproot))
        self.xmlrpcExec("sc create tftpd "
                        "binPath= %%systemroot%%\\system32\\tftpd.exe")
        self.winRegAdd("HKLM",
                       "system\\currentcontrolset\\services\\tftpd",
                       "DisplayName",
                       "SZ",
                       "TFTP Server")
        self.winRegAdd("HKLM",
                       "system\\currentcontrolset\\services\\tftpd\\Parameters",
                       "Directory",
                       "SZ",
                        tftproot)
        self.xmlrpcExec("net start tftpd")
        try:
            self.xmlrpcExec("netsh firewall set portopening UDP 69 \"TFTP Server\" ENABLE")
        except:
            pass

        # Set TFTP DHCP options.
        try:
            self.xmlrpcExec("netsh dhcp server "
                            "add optiondef 066 tftpserver STRING")
        except:
            pass
        try:
            self.xmlrpcExec("netsh dhcp server "
                            "add optiondef 067 pxefile STRING")
        except:
            pass
        self.xmlrpcExec("netsh dhcp server scope %s "
                        "set optionvalue 066 STRING %s" % (network, server))
        self.xmlrpcExec("netsh dhcp server scope %s "
                        "set optionvalue 067 STRING %s" % (network, filename))
        self.tftproot = tftproot
        self.xmlrpcExec("sc config tftpd start= auto")

    def installWindowsNATServer(self, public, private,
                                network="192.168.0.0", server="192.168.0.1"):

        public = self.getWindowsInterface(public)
        private = self.getWindowsInterface(private)

        try:
            self.xmlrpcExec("net stop SharedAccess")
            self.xmlrpcExec("sc config SharedAccess start= disabled")
        except:
            pass

        # Enable routing.
        self.winRegAdd("HKLM",
                       "system\\currentcontrolset\\services\\tcpip\\parameters",
                       "IPEnableRouter",
                       "DWORD",
                        1)
        self.xmlrpcExec("netsh routing ip nat install")
        self.xmlrpcExec("netsh routing ip nat add interface "
                        "\"%s\" private" % (private))
        self.xmlrpcExec("netsh routing ip nat add interface "
                        "\"%s\" full" % (public))
        self.xmlrpcExec("netsh routing ip nat add interface Internal private")
        self.xmlrpcExec("sc config RemoteAccess start= auto")
        self.xmlrpcExec("net start RemoteAccess")

        try:
            self.xmlrpcExec("netsh dhcp server "
                            "add optiondef 003 router IPADDRESS")
        except:
            pass
        try:
            self.xmlrpcExec("netsh dhcp server "
                            "add optiondef 006 dnsserver IPADDRESS")
        except:
            pass
        self.xmlrpcExec("netsh dhcp server scope %s "
                        "set optionvalue 003 IPADDRESS %s" % (network, server))
        dnsdata = self.xmlrpcExec("netsh interface ip show dns", returndata=True)
        r = "%s.*?(?P<nameserver>[0-9\.]+)" % (public)
        nameserver = re.search(r, dnsdata, re.DOTALL).group("nameserver")
        self.xmlrpcExec("netsh dhcp server scope %s "
                        "set optionvalue 006 IPADDRESS %s" % (network, nameserver))
        # Need to reboot to make sure NAT will work. (CA-16162)
        self.xmlrpcReboot()
        xenrt.sleep(60)
        self.waitforxmlrpc(600)

    def disableFirewall(self):
        """Disable the firewall on this location."""
        try:
            if self.windows:
                self.xmlrpcExec("netsh firewall set opmode DISABLE")
            else:
                self.execcmd("service iptables stop")
        except Exception, e:
            xenrt.TEC().warning("Exception disabling firewall: %s" %
                                (str(e)))

    def installLinuxISCSITarget(self, iqn=None, user=None, password=None, outgoingUser=None, outgoingPassword=None, targetType=None):
        if not targetType:
            targetType = xenrt.TEC().lookup("LINUX_ISCSI_TARGET", "IET")

        self.execcmd("echo %s > /root/iscsi_target_type" % targetType) 

        if targetType == "IET":
            return self.installLinuxISCSITargetIET(iqn=iqn, user=user, password=password, outgoingUser=outgoingUser, outgoingPassword=outgoingPassword)
        elif targetType == "LIO":
            return self.installLinuxISCSITargetLIO(iqn=iqn, user=user, password=password, outgoingUser=outgoingUser, outgoingPassword=outgoingPassword)
        else:
            raise xenrt.XRTError("Unsupported ISCSI target type %s" % targetType)

    def targetcli(self, command):
        if int(self.execcmd("cat /root/targetcli_noninteractive").strip()):
            self.execcmd("targetcli %s" % command)
        else:
            if command == "/ saveconfig":
                self.execcmd("/bin/echo -e '/ saveconfig\\nyes' | targetcli")
            else:
                self.execcmd("echo '%s' | targetcli" % command)

    def targetcliGetTpg(self):
        if int(self.execcmd("cat /root/targetcli_noninteractive").strip()):
            return self.execcmd("targetcli ls /iscsi | grep -1 TPG | tail -1 | awk '{print $2}'").strip()
        else:
            return re.sub(r'\x1b[^m]*m', '', self.execcmd("echo 'ls /iscsi' | targetcli | grep -1 TPG | tail -1 | awk '{print $2}'").strip())
        

    def installLinuxISCSITargetLIO(self, iqn=None, user=None, password=None, outgoingUser=None, outgoingPassword=None):
        if not iqn:
            iqn = "iqn.2008-01.xenrt.test:iscsi%08x" % \
                  (random.randint(0, 0x7fffffff))
        self.execcmd("echo %s > /root/iscsi_iqn" % iqn)
        try:
            debversion = int(self.execcmd("cat /etc/debian_version").strip().split(".")[0])
        except:
            debversion = None

        try:
            redhat = self.execcmd("cat /etc/redhat-release")
        except:
            redhat = None

        if debversion:
            if debversion == 8:
                self.execcmd("wget -O - %s/jessie-targetcli.tgz | tar -xvz" % xenrt.TEC().lookup("TEST_TARBALL_BASE"))
                self.execcmd("dpkg -i jessie-targetcli/*.deb || apt-get -yf install")
            else:
                self.execcmd("apt-get install -y targetcli")
            if debversion >=8:
                self.execcmd("echo 1 > /root/targetcli_noninteractive")
            else:
                self.execcmd("echo 0 > /root/targetcli_noninteractive")
        elif redhat:
            self.execcmd("yum install -y targetcli")
            self.execcmd("chkconfig target on")
            self.execcmd("echo 1 > /root/targetcli_noninteractive")
        self.targetcli("/ set global auto_add_default_portal=false") 
        self.targetcli("/iscsi create %s" % iqn)
        tpg = self.targetcliGetTpg()
        ips = self.execcmd("ip addr show | grep 'inet ' | awk '{print $2}' | cut -d '/' -f 1 | grep -v 127.0.0.1").strip().splitlines()
        for i in ips:
            self.targetcli("/iscsi/%s/%s/portals create %s"  % (iqn, tpg, i))
        # Set up open access 
        self.targetcli("/iscsi/%s/%s set attribute authentication=0 demo_mode_write_protect=0 generate_node_acls=1 cache_dynamic_acls=1" % (iqn, tpg))

        # Not implementing CHAP yet
        if user or password or outgoingUser or outgoingPassword:
            raise xenrt.XRTError("XenRT support for CHAP is not implemented on LIO luns")
        
        self.targetcli("/ saveconfig")
        return iqn
        

    
    def installLinuxISCSITargetIET(self, iqn=None, user=None, password=None, outgoingUser=None, outgoingPassword=None):
        """Installs a Debian VM to be an iSCSI target"""
        if not iqn:
            iqn = "iqn.2008-01.xenrt.test:iscsi%08x" % \
                  (random.randint(0, 0x7fffffff))

        isLegacy = True
        try:
            debversion = int(self.execcmd("cat /etc/debian_version").strip().split(".")[0])
        except:
            debversion = None

        if debversion >= 6:
            isLegacy = False

        try:
            redhat = self.execcmd("cat /etc/redhat-release")
            isLegacy = False
        except:
            redhat = None

        if not isLegacy:
            # Prerequisites
            if debversion:
                self.execcmd("apt-get install libssl-dev --force-yes -y")
                self.execcmd("apt-get install linux-headers-`uname -r` --force-yes -y")
            elif redhat:
                try:
                    self.execcmd("yum --disablerepo=updates install -y openssl-devel kernel-headers")
                except:
                    self.execcmd("yum install -y openssl-devel kernel-headers")
                    

            # Get and install the iscsi target
            
            if debversion >= 7:
                self.execcmd("apt-get install -y --force-yes iscsitarget iscsitarget-dkms")
                self.execcmd('sed -i "s/false/true/" /etc/default/iscsitarget')
                self.execcmd('/etc/init.d/iscsitarget restart')
                self.execcmd('ln -s /etc/init.d/iscsitarget /etc/init.d/iscsi-target')
            else:
                self.execcmd("cd /root && wget '%s/iscsitarget-1.4.20.2.tgz'" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")))
                self.execcmd("cd /root && tar -xzf iscsitarget-1.4.20.2.tgz")
                self.execcmd("cd /root/iscsitarget-1.4.20.2 && make")
                self.execcmd("cd /root/iscsitarget-1.4.20.2 && make install")
            
            self.execcmd("rm /etc/iet/ietd.conf")
            self.execcmd("ln -s /etc/ietd.conf /etc/iet/ietd.conf")
        else: 
            # Legacy installation for etch
            # Prerequisites
            self.execcmd("apt-get install libssl-dev --force-yes -y")

            if debversion == 4 and self.execcmd("uname -r").strip() == "2.6.18.8.xs5.5.0.14.443":
                # On Etch on George we need to workaround the fact the updates repo no longer exists,
                # and thus we don't pick up kernel headers from it
                url = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP")
                self.execcmd("wget -O /root/linux-headers.tar.gz %s/etch/linux-headers.tar.gz" % url)
                self.execcmd("cd /root && tar -xzf linux-headers.tar.gz")
                self.execcmd("cd /root && dpkg -i linux-headers*.deb")

            # Workaround for incorrect symlink
            for path in self.execcmd("ls /lib/modules").split():
                self.execcmd("rm -f /lib/modules/%s/build" % (path.strip()))
                self.execcmd("ln -s /usr/src/linux-headers-%s /lib/modules/%s/build" % (path.strip(),path.strip()))

            # Setup iscsitarget
            self.execcmd("cd /root && wget '%s/iscsitarget.tgz'" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")))
            self.execcmd("cd /root && tar -xzf iscsitarget.tgz")
            self.execcmd("cd /root/iscsitarget && patch -p1 < multihomed.patch")
            self.execcmd("cd /root/iscsitarget && make")
            self.execcmd("cd /root/iscsitarget && make install")

        # Create initial config
        self.execcmd("echo 'Target %s' > /etc/ietd.conf" % (iqn))
        if user and password:
            self.execcmd("echo '        IncomingUser %s %s' >> /etc/ietd.conf" % (user, password))

        if outgoingUser and outgoingPassword:
            self.execcmd("echo '        OutgoingUser %s %s' >> /etc/ietd.conf" % (outgoingUser, outgoingPassword))

        # Don't start the server yet, we'll wait for a LUN to be
        # created first

        if debversion:
            try:
                self.execcmd("update-rc.d iscsi-target defaults")
            except:
                pass
        elif redhat:
            self.execcmd("chkconfig iscsi-target on")

        return iqn

    def createISCSITargetLun(self, lunid, sizemb, dir="/", thickProvision=True, timeout=1200, existingFile=None):
        targetType = self.execcmd("cat /root/iscsi_target_type").strip()

        if targetType == "IET":
            return self.createISCSITargetLunIET(lunid=lunid, sizemb=sizemb, dir=dir, thickProvision=thickProvision, timeout=timeout, existingFile=existingFile)
        elif targetType == "LIO":
            return self.createISCSITargetLunLIO(lunid=lunid, sizemb=sizemb, dir=dir, existingFile=existingFile)

    def createISCSITargetLunLIO(self, lunid, sizemb, dir="/", existingFile=None):
        name = "iscsi%08x" % random.randint(0, 0x7fffffff)
        if existingFile:
            url = xenrt.filemanager.FileNameResolver(existingFile).url
            self.execcmd("mkdir -p %s.tmp" % (os.path.join(dir, name)))
            if url.endswith(".gz") or url.endswith(".tgz"):
                options = "z"
            elif url.endswith(".bz2"):
                options = "j"
            else:
                options = ""
            proxy = xenrt.TEC().lookup("HTTP_PROXY", None)
            proxyflag = " -e http_proxy=%s" % proxy if proxy else ""
            self.execcmd("cd %s.tmp && wget %s -nv -O - %s | tar -xv%s" % (os.path.join(dir, name), proxyflag, url, options))
            fname = self.execcmd("find %s.tmp -type f" % os.path.join(dir, name)).splitlines()[0].strip()
            self.execcmd("mv %s %s" % (fname, os.path.join(dir, name)))
            self.execcmd("rm -rf %s.tmp" % (os.path.join(dir, name)))
        iqn = self.execcmd("cat /root/iscsi_iqn").strip()
        self.execcmd("echo %d > /root/iscsi_lun" % lunid)
        self.targetcli("/backstores/fileio create name=%s file_or_dev=%s size=%dM" % (name, os.path.join(dir, name), sizemb))
        tpg = self.targetcliGetTpg()
        self.targetcli("/iscsi/%s/%s/luns create /backstores/fileio/%s lun=%d" % (iqn, tpg, name, lunid))
        self.targetcli("/ saveconfig")

        serial = self.execcmd("cat /sys/kernel/config/target/core/*/%s/wwn/vpd_unit_serial" % name).strip().split()[-1]
        scsiid = "36001405" + serial.replace("-", "")[:-7]

        return scsiid

    def createISCSITargetLunIET(self, lunid, sizemb, dir="/", thickProvision=True, timeout=1200, existingFile=None):
        """Creates a LUN on the software iSCSI target installed in this VM."""

        if existingFile:
            xenrt.TEC().logverbose("Importing existing LUNs is not supported with IET")

        # Create a lun
        filename = string.strip(self.execcmd("mktemp %siSCSIXXXXXX" % (dir)))
        if thickProvision:
            self.execcmd("dd if=/dev/zero of=%s bs=1M count=%u" %
                         (filename, sizemb),timeout=1200)
        else:
            self.execcmd("dd if=/dev/zero of=%s bs=1M count=0 seek=%u" %
                         (filename, sizemb),timeout=timeout)

        scsiid = random.randint(0, 0x7fffffff)
        self.execcmd("echo '        Lun %u Path=%s,Type=fileio,ScsiId=%08x' >> "
                     "/etc/ietd.conf" % (lunid, filename, scsiid))

        # Stop the daemon if it's running
        try:
            self.execcmd("/etc/init.d/iscsi-target stop")
        except:
            pass

        try:
            self.execcmd("killall ietd")
        except:
            pass
        # Start iscsi-target
        self.execcmd("/etc/init.d/iscsi-target start")
        xenrt.sleep(5)

        return scsiid

    def createLinuxNfsShare(self, name, verifyShare=True):
        """Share a directory over NFS on this Linux VM.
           The NFS Server service will be installed / started if required"""
        if self.windows == True:
            raise xenrt.XRTError('createLinuxNfsShare called for Windows guest')

        exportPath = '/xenrtexport/%s' % (name)
        if self.execcmd('test -e %s' % (exportPath), retval='code') == 0:
            raise xenrt.XRTError('Export path: %s already exists on %s' % (exportPath, self.name))
        xenrt.TEC().logverbose('Creating export on %s at path: %s' % (self.name, exportPath))
        self.execcmd('mkdir -p %s' % (exportPath))
        self.execcmd('echo "%s *(rw,async,no_root_squash)" >> /etc/exports' % (exportPath))

        if self.distro.startswith('centos') or self.distro.startswith('rhel'):
            self.execcmd('service nfs start')
            self.execcmd('chkconfig nfs on')
            self.execcmd('exportfs -a')
        else:
            if self.execcmd('test -e /etc/init.d/nfs-kernel-server', retval='code') != 0:
                self.execcmd('apt-get install -y --force-yes nfs-kernel-server nfs-common portmap')
                self.execcmd('update-rc.d nfs-kernel-server defaults')
            self.execcmd('/etc/init.d/nfs-kernel-server reload')
        nfsPath = '%s:%s' % (self.getIP(), exportPath)
        xenrt.TEC().logverbose('Created NFS share: %s' % (nfsPath))

        if verifyShare:
            tempMnt = xenrt.TempDirectory().dir
            tempFile = 'verifyShare.txt'
            self.execcmd('touch %s' % (os.path.join(exportPath, tempFile)))
            try:
                xenrt.util.command('sudo mount %s %s && test -e %s' % (nfsPath, tempMnt, os.path.join(tempMnt, tempFile)))
            finally:
                xenrt.util.command('sudo umount %s' % (tempMnt))
                self.execcmd('rm %s' % (os.path.join(exportPath, tempFile)))

        return nfsPath

    def updateWindows(self):
        """Apply all relevant critical updates to a Windows guest"""
        if not self.windows:
            raise xenrt.XRTError("Asked to update Windows on non-Windows guest")

        # Unpack tarball
        workdir = self.xmlrpcTempDir()
        arch = self.xmlrpcGetArch()
        if arch == "amd64":
            arch = "x64"

        self.xmlrpcUnpackTarball("%s/winupdates.tgz" %
                                 (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                 workdir)

        # Grab the latest update catalog
        self.xmlrpcFetchFile("http://go.microsoft.com/fwlink/?LinkId=76054",
                               "%s\\winupdates\\wsusscn2.cab" % (workdir))

        # Install appropriate Windows Update Agent
        self.xmlrpcExec("%s\\winupdates\\WindowsUpdateAgent20-%s.exe /quiet "
                        "/norestart" % (workdir,arch))

        gotReport = False
        count = 1
        while not gotReport:
            if count > 2:
                # Avoid an infinite loop!
                raise xenrt.XRTError("Missing a required component for MBSA")

            # Run MBSA
            self.xmlrpcExec("%s\\winupdates\\mbsacli.exe /catalog "
                            "%s\\winupdates\\wsusscn2.cab /xmlout /nvc /nd > "
                            "%s\\winupdates\\report.xml" % (workdir,workdir,
                                                            workdir))

            # Grab back the report.xml
            data = self.xmlrpcReadFile("%s\\winupdates\\report.xml" % (workdir))

            # Parse it to see what updates we need
            dom = xml.dom.minidom.parseString(data)

            # Do we need Windows Installer?
            checks = dom.getElementsByTagName("Check")
            if checks[0].getAttribute("GroupID") == "MBSA:Required":
                r = checks[0].childNodes[1].childNodes[0].getAttribute("GUID")
                if r == "MBSA:Requirement:MSI":
                    # Install Windows Installer
                    self.xmlrpcExec("%s\\winupdates\\"
                                    "WindowsInstaller-KB893803-v2-%s.exe /quiet"
                                    " /norestart" % (workdir,arch),
                                    level=xenrt.RC_OK)
                    self.xmlrpcReboot()
                    xenrt.sleep(60)
                    self.waitForDaemon(300,desc="Guest reboot after installing "
                                           "Windows Update")
            else:
                gotReport = True
            count += 1

        nodes = dom.getElementsByTagName("UpdateData")
        updates = []
        for node in nodes:
            if node.getAttribute("Type") == "1" and \
               node.getAttribute("IsInstalled") == "false":
                childs = node.childNodes
                for c in childs:
                    if c.tagName == "References":
                        childs2 = c.childNodes
                        for c2 in childs2:
                            if c2.tagName == "DownloadURL":
                                updates.append(c2.childNodes[0].data.strip())

        # Install them...
        fc = xenrt.filecache.FileCache("winupdates")
        i = 1
        for u in updates:
            uf = os.path.basename(u)
            path = fc.getURL(u)
            self.xmlrpcSendFile(path,"%s\\winupdates\\%s" % (workdir,uf),
                                usehttp=True)
            xenrt.TEC().logverbose("Installing %s (%u/%u)" % (uf,i,len(updates)))
            i += 1
            # Check this isn't a special case
            if uf.find("kb923789") > 0:
                switches = "/Q"
            else:
                switches = "/quiet /norestart"
            self.xmlrpcExec("%s\\winupdates\\%s %s" %
                            (workdir,uf,switches),level=xenrt.RC_OK)

        # Reboot the guest after that lot
        self.xmlrpcReboot()
        xenrt.sleep(60)
        self.waitForDaemon(300,desc="Guest reboot after updating Windows")

    def updateYumConfig(self, distro=None, arch=None, allowKernel=False):
        """If we have a local HTTP mirror of a yum repo then create
        a yum repo config for it on this guest/host. This is only for
        for the base repo, all others get removed. This is a hack
        primarily intended for XenServer dom0."""
        if arch == "x86-32p":
            arch = "x86-32"
        if not distro:
            distro = self.distro
        if not arch:
            arch = self.arch

        url = xenrt.getLinuxRepo(distro, arch, "HTTP", None)
        if not url:
            return False
        try:
            # All versions of CentOS and RHEL7+ don't have Server in the repo path
            if distro.startswith("centos") or distro.startswith("rhel7") or distro.startswith("oel7") or distro.startswith("sl"):
                pass
            else:
                url = os.path.join(url, 'Server')
            try:
                # Try to rename the files to .orig. This could fail if they don't exist
                self.execcmd("for r in /etc/yum.repos.d/*.repo; "
                             "   do mv $r $r.orig; done")
            except:
                pass
            c = """[base]
name=CentOS-$releasever - Base
baseurl=%s
gpgcheck=0
""" % (url)
            # If we're upgrading then we can't exclude the kernel
            if not allowKernel:
                c += "exclude=kernel*, *xen*\n"
            sftp = self.sftpClient()
            fn = xenrt.TEC().tempFile()
            f = file(fn, "w")
            f.write(c)
            f.close()
            sftp.copyTo(fn, "/etc/yum.repos.d/xenrt.repo")
            sftp.close()
        except:
            return False
        return True

    def updateLinux(self, updateTo):
        # Currently only for RHEL derivatives
        if updateTo == "latest":
            timeout = 7200
            self.execguest("rm /etc/yum.repos.d/xenrt.repo")
            self.execguest("rename '.orig' '' /etc/yum.repos.d/*.orig")
            # Add a proxy if we know about one
            proxy = xenrt.TEC().lookup("HTTP_PROXY", None)
            if proxy:
                self.execguest("sed -i '/proxy/d' /etc/yum.conf")
                self.execguest("echo 'proxy=http://%s' >> /etc/yum.conf" % proxy)
            updateTo = xenrt.getUpdateDistro(self.distro)
        else:
            timeout = 3600
            self.updateYumConfig(updateTo, self.arch, allowKernel=True)
        
        # Do the upgrade
        self.execcmd("yum update -y", timeout=timeout)
        # Cleanup the repositories again
        self.distro=updateTo
        self.updateYumConfig(self.distro, self.arch, allowKernel=False)
        # And reboot to start the new system
        xenrt.TEC().comment("Updated from %s to %s" % (self.distro, updateTo))
        self.reboot()
        

    def getExtraLogs(self, directory):
        pass

    def workloadsAvailable(self):
        if self.windows:
            return ["Prime95",
                    "Ping",
                    "SQLIOSim",
                    "Burnintest",
                    "NetperfTX",
                    "NetperfRX",
                    "Memtest"]
        else:
            return ["LinuxNetperfRX",
                    "LinuxNetperfTX"]

    def installWorkloads(self, workloads=None):
        if workloads is None:
            workloads = self.workloadsAvailable()
        installedWorkloads = []
        for w in workloads:
            xenrt.TEC().progress("Installing workload %s..." % (w))
            try:
                workload = eval("testcases.benchmarks.workloads.%s(self)" % (w))
            except AttributeError, e:
                workload = None

            if workload:
                workload.install(startOnBoot=True)
                installedWorkloads.append(workload)
            else:
                raise xenrt.XRTError("%s is a legacy workload and cannot be "
                                     "installed" % (w))
        return installedWorkloads

    def startWorkloads(self, workloads=None):
        if not workloads:
            workloads = self.workloadsAvailable()
        runningWorkloads = []
        for w in workloads:
            xenrt.TEC().progress("Starting workload %s..." % (w))
            try:
                workload = eval("testcases.benchmarks.workloads.%s(self)" % (w))
            except AttributeError, e:
                workload = None

            if workload:
                workload.start()
                runningWorkloads.append(workload)
            else:
                try:
                    self.execcmd("%s/workloads/%s start" %
                                 (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), w))
                except Exception, e:
                    message = "%s failed to start: %s" % (w, str(e))
                    if xenrt.TEC().lookup("SRM_STRICT", False, boolean=True):
                        raise xenrt.XRTError(message)
                    xenrt.TEC().warning(message)
                runningWorkloads.append(w)
        return runningWorkloads

    def stopWorkloads(self, workloads):
        for w in workloads:
            if isinstance(w, testcases.benchmarks.workloads.Workload):
                w.stop()
            else:
                try:
                    self.execcmd("%s/workloads/%s stop" %
                                 (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), w))
                except Exception, e:
                    message = "%s failed to stop: %s" % (w, str(e))
                    if xenrt.TEC().lookup("SRM_STRICT", False, boolean=True):
                        raise xenrt.XRTError(message)
                    xenrt.TEC().warning(message)

    def stopWorkloadsManual(self, workloads=None):
        stoppedWorkloads = []
        if not workloads:
            workloads = self.workloadsAvailable()
        for w in workloads:
            xenrt.TEC().progress("Stopping workload %s..." % (w))
            try:
                workload = eval("testcases.benchmarks.workloads.%s(self)" % (w))
            except:
                workload = None

            if workload:
                workload.stop()
                stoppedWorkloads.append(workload)
            else:
                try:
                    self.execcmd("%s/workloads/%s stop" %
                                 (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), w))
                    stoppedWorkloads.append(w)
                except Exception, e:
                    message = "%s failed to stop: %s" % (w, str(e))
                    xenrt.TEC().warning(message)

        return stoppedWorkloads

    def configureIPv6Router(self):
        pass

    def preCloneTailor(self):
        # Tailor this guest to be clone-friendly - i.e. remove any MAC adddress
        # hardcodings
        if not self.windows:
            if self.execcmd("test -e /etc/redhat-release",
                            retval="code") == 0:
                # Tweak network scripts on RHEL.
                self.execcmd("for f in "
                             " /etc/sysconfig/network-scripts/ifcfg-eth?; "
                             "   do mv -f $f $f.bak; "
                             "      grep -v ^HWADDR $f.bak > $f; done")
            elif self.execcmd("test -e /etc/debian_version",
                              retval="code") == 0:
                self.execcmd("rm -f "
                             "/etc/udev/rules.d/z25_persistent-net.rules "
                             "/etc/udev/persistent-net-generator.rules")
            elif self.execcmd("test -e /etc/SuSE-release",
                              retval="code") == 0:
                try:
                    self.execcmd(\
                        "rm /etc/udev/rules.d/30-net_persistent_names.rules")
                except:
                    pass
                script = """
#!/usr/bin/env python

import os, re

data = os.popen("ifconfig -a") .read()
current = [ re.sub(".*HWaddr ", "", d).strip().lower() for d in
                re.findall("eth.*", data) ]

data = os.popen("ls /etc/sysconfig/network/ifcfg-eth-*").read().strip()
old = [ re.sub("/etc/sysconfig/network/ifcfg-eth-id-", "", d) for d in
                data.split("\\n") ]

for i in range(len(old)):
        os.system("mv /etc/sysconfig/network/ifcfg-eth-id-%s "
                  "/etc/sysconfig/network/ifcfg-eth-id-%s" %
                  (old[i], current[i]))
bootlocal = file("/etc/rc.d/boot.local", "rw")
data = bootlocal.read()
data = re.sub("python /etc/rc.d/netfix", "", data)
bootlocal.write(data)
bootlocal.close()
"""
                netfix = xenrt.TEC().tempFile()
                f = file(netfix, "w")
                f.write(script)
                f.close()
                sftp = self.sftpClient()
                sftp.copyTo(netfix, "/etc/rc.d/netfix")
                sftp.close()
                self.execcmd("echo python /etc/rc.d/netfix >> "
                             "/etc/rc.d/boot.local")

    def xmlrpcTailor(self):
        """Tailor a new xml-rpc Windows guest/host"""
        if not self.getIP():
            raise xenrt.XRTError("Unknown IP address")

        # Update the test execution daemon
        xenrt.TEC().logverbose("Updating RPC daemon")
        self.xmlrpcUpdate()

        # Disable the screensaver (XRT-214)
        self.winRegAdd("HKCU",
                       "Control Panel\\Desktop",
                       "ScreenSaveActive",
                       "SZ",
                       "0")
        try:
            self.winRegDel("HKCU",
                           "Control Panel\\Desktop",
                           "SCRNSAVE.EXE", ignoreHealthCheck=True)
        except Exception, e:
            pass

        # Disable the 'Manage Your Server' wizard
        self.winRegAdd("HKCU",
                       "Software\\Microsoft\\Windows NT\\CurrentVersion\\"
                       "srvWiz",
                       "",
                       "DWORD",
                       0)
        # Terminate it now
        self.xmlrpcKillAll("mshta.exe")

        # Don't prompt for a password on unhibernate
        self.winRegAdd("HKCU",
                       "Software\\Policies\\Microsoft\\Windows\\"
                       "System\\Power",
                       "PromptPasswordOnResume",
                       "DWORD",
                       0)

        # Disable the shutdown even tracker.
        self.winRegAdd("HKLM",
                       "Software\\Policies\\Microsoft\\"
                       "Windows NT\\Reliability",
                       "ShutdownReasonOn",
                       "DWORD",
                        0)

        # Disable autoplay.
        if float(self.xmlrpcWindowsVersion()) > 5.99:
            self.winRegAdd("HKLM",
                           "Software\\Microsoft\\"
                           "Windows\\CurrentVersion\\"
                           "Policies\\Explorer",
                           "NoDriveTypeAutoRun",
                           "DWORD",
                            0x9D)
            # Prevent reboot after BSOD. XRT-2860
            try:
                self.xmlrpcExec("bcdedit /set {default} nocrashautoreboot true", ignoreHealthCheck=True)
            except:
                pass

        if self.xmlrpcGetArch() == "amd64":
            try:
                self.xmlrpcExec("copy c:\\windows\\system32\\diskpart.exe c:\\windows\\SysWOW64\\diskpart.exe", ignoreHealthCheck=True)
            except:
                pass

        try:
            if self.xmlrpcWindowsVersion() == "5.0":
                self.xmlrpcSendFile("%s/distutils/devcon.exe" %
                                    (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")),
                                    "c:\\devcon.exe", ignoreHealthCheck=True)
                self.xmlrpcUnpackTarball("%s/powercfg.tgz" %
                                (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                 "c:\\")
                self.xmlrpcExec("copy c:\\powercfg\\powercfg.exe c:\\windows\\system32\\", ignoreHealthCheck=True)
        except:
            pass

        # Enable EMS on Windows (XRT-514)
        if xenrt.TEC().lookup("OPTION_USE_EMS", False, boolean=True):
            try:
                if float(self.xmlrpcWindowsVersion()) > 5.99:
                    self.xmlrpcExec("bcdedit /bootems {default} ON", ignoreHealthCheck=True)
                    self.xmlrpcExec("bcdedit /ems {default} ON", ignoreHealthCheck=True)
                    self.xmlrpcExec("bcdedit /emssettings EMSPORT:1 EMSBAUDRATE:115200", ignoreHealthCheck=True)
                else:
                    self.xmlrpcExec("bootcfg /ems ON /port COM1 /id 1", ignoreHealthCheck=True)
            except:
                # Always seems to exit non-zero
                pass

        # Add the /PAE flag to boot.ini if we're using more than
        # 4GB of memory
        if isinstance(self, GenericGuest) and not "pae" in self.distro and self.memory > 4096 and \
                not float(self.xmlrpcWindowsVersion()) > 5.99:
            xenrt.TEC().logverbose("Adding /PAE flag")
            self.xmlrpcAddBootFlag("/PAE")
            self.xmlrpcExec("type c:\\boot.ini")

        # Enable remote desktop.
        self.winRegAdd("HKLM",
                       "SYSTEM\\CurrentControlSet\\Control\\Terminal Server",
                       "fDenyTSConnections",
                       "DWORD",
                        0)

        # Optionally forcably disable NX (DEP) support
        if xenrt.TEC().lookup("FORCE_NX_DISABLE", False, boolean=True):
            self.setWindowsNX(False)

        # XRT-9905 Disable Windows content indexer in VMs
        try:
            self.xmlrpcExec("net stop WSearch", ignoreHealthCheck=True)
            self.xmlrpcExec("sc config WSearch start= disabled", ignoreHealthCheck=True)
        except:
            # Probably not running anyway, or a version of Windows without the
            # indexer
            pass
            
        applicationEventLogger = "wevtutil qe Application /c:50 /f:text"
        systemEventLogger = "wevtutil qe System /c:50 /f:text"
        setupEventLogger = "wevtutil qe Setup /c:50 /f:text"
        if 'xp' in self.distro or '2003' in self.distro:
            applicationEventLogger = "cscript C:\\Windows\\System32\\eventquery.vbs /L Application /R 50"
            systemEventLogger = "cscript C:\\Windows\\System32\\eventquery.vbs /L System /R 50"
            setupEventLogger = "cscript C:\\Windows\\System32\\eventquery.vbs /L Setup /R 50"
        windowsIPConfigLogger = """Set osh = WScript.CreateObject("WScript.Shell")
dim oex, oex1, oex2, oex3
set oex = osh.Exec("ipconfig /all")
set oex1 = osh.Exec("%s")
set oex2 = osh.Exec("%s")
set oex3 = osh.Exec("%s")

Set objWMIService = GetObject("winmgmts:\\\\.\\root\\wmi")
Set base = objWmiService.InstancesOf("CitrixXenStoreBase")

for each itementry in base
    set objitem = itementry
next

objitem.AddSession "NewSession", answer
query = "select * from CitrixXenStoreSession where SessionId = '" & answer & "'"
Set sessions = objWMIService.ExecQuery(query) 
for each itementry in sessions
   rem is there a more trivial way of getting the only item from a collection in vbscript?
   set session = itementry
next

Do
    str = oex.StdOut.ReadLine()
    session.log(str)
Loop While not oex.Stdout.atEndOfStream

Do
    str = oex1.StdOut.ReadLine()
    session.log(str)
Loop While not oex1.Stdout.atEndOfStream

Do
    str = oex2.StdOut.ReadLine()
    session.log(str)
Loop While not oex2.Stdout.atEndOfStream

Do
    str = oex3.StdOut.ReadLine()
    session.log(str)
Loop While not oex3.Stdout.atEndOfStream"""%(applicationEventLogger,systemEventLogger,setupEventLogger)

        try:
            self.xmlrpcWriteFile("C:\\logger.vbs", windowsIPConfigLogger)
            self.logger = True
        except Exception as e:
            xenrt.TEC().logverbose("Writing ipconfig logger to Windows VM failed: %s"%(e.message))


    def setWindowsNX(self, enable):
        """Enable or disable Windows NX (DEP) support."""
        if not self.windows:
            raise xenrt.XRTError(\
                "setWindowsNX not supported for non-Windows OS")
        if enable:
            xenrt.TEC().logverbose("Enabling NX for Windows VM %s" %
                                   (self.getName()))
        else:
            xenrt.TEC().logverbose("Disabling NX for Windows VM %s" %
                                   (self.getName()))
        if float(self.xmlrpcWindowsVersion()) > 5.99:
            if enable:
                self.xmlrpcExec("bcdedit /set nx AlwaysOn")
            else:
                self.xmlrpcExec("bcdedit /set nx AlwaysOff")
        else:
            if enable:
                self.xmlrpcExec("bootcfg /raw \"/noexecute=alwayson\" /A")
            else:
                self.xmlrpcExec("bootcfg /raw \"/noexecute=alwaysoff\" /A")
        self.reboot()

    def sendSysRq(self, key):
        raise xenrt.XRTError("Unimplemented")

    def addExtraLogFile(self, path):
        """Add a log file to the list of files we collect from this place."""
        if not self.extraLogsToFetch:
            self.extraLogsToFetch = []
        self.extraLogsToFetch.append(path)

    def tempDir(self):
        """Create a temporary directory on this place.
        This will not be automatically removed.
        """
        if self.windows:
            return self.xmlrpcTempDir()
        return string.strip(self.execcmd("mktemp -d /tmp/distXXXXXX"))

    def collectPerfdata(self, counters, interval=10):
        if self.windows:
            cname = xenrt.util.randomGuestName()
            self.xmlrpcExec("logman create counter %s -c %s -f csv -si %s" %
                            (cname, string.join([ "\"%s\"" % (x) for x in counters ]), interval))
            self.xmlrpcExec("logman start %s" % (cname))
            for log in self.xmlrpcGlobpath("c:\\perflogs\\%s*" % (cname)):
                self.addExtraLogFile(log)

    def getTime(self):
        """Return the guest OS clock time as seconds since the epoch."""
        stime = (self.windows and self.xmlrpcGetTime()
                 or self.execcmd("date -u +%s.%N", idempotent=True).strip())
        return float(stime)

    def getClockSkew(self):
        """Return the difference in seconds between the guest clock time
        and the local controller time. A positive value means the guest clock
        is fast."""
        t1 = time.time()
        tr = self.getTime()
        t2 = time.time()
        # If the remote getTime took too long record that
        if (t2 - t1) > 2.0:
            xenrt.TEC().logverbose("Remote getTime took %fs" % (t2 - t1))
        return tr - t2

    def setClockSync(self, enable):
        if self.windows:
            if enable:
                exists = self.xmlrpcExec('sc query w32time | find "SERVICE_NAME:"',
                                         returnerror=False, returnrc=True) == 0
                if not exists: self.xmlrpcExec('w32tm /register')
                running = self.xmlrpcExec('sc query w32time | find "RUNNING"',
                                          returnerror=False, returnrc=True) == 0
                if not running: self.xmlrpcExec('sc start w32time')
                self.xmlrpcExec('w32tm /resync /rediscover')
                if abs(xenrt.timenow() - self.xmlrpcGetTime()) > 30.0:
                    raise xenrt.XRTError("Clock difference is greater "
                                             "than 30 seconds after sync.")
            else:
                # This won't raise an error even if w32time doesn't exists
                self.xmlrpcExec('sc stop w32time')
                xenrt.sleep(3)
                self.xmlrpcExec('w32tm /unregister')
        else:
            ntpd = self.execcmd('stat /etc/init.d/ntpd', retval='code') == 0
            ntpwait = self.execcmd('which ntp-wait', retval='code') == 0
            ntp_run = ntpd \
                      and self.execcmd('ps aux | grep -v grep | grep ntpd',
                                       retval='code') == 0
            if enable:
                # Just to make life easier
                self.setTime(xenrt.timenow())
                if ntpd:
                    if not ntp_run:
                        self.execcmd("/etc/init.d/ntpd start")
                    # if ntpwait:
                    #     self.execcmd("ntp-wait")
                    # else:
                    #     self.execcmd("ntpd -q -gx")
                else:
                    raise xenrt.XRTError("No ntpd, clock can not be set "
                                         "to sync status")
                # if abs(xenrt.timenow() - self.getTime()) > 30.0:
                #     raise xenrt.XRTError("Clock difference is greater "
                #                          "than 30 seconds after sync.")
            else:
                if ntp_run:self.execcmd("/etc/init.d/ntpd stop")
        xenrt.TEC().logverbose("Clock is set to %s status"
                               % (enable and "sync" or "unsync"))


    def setTime(self, secondsSinceEpoch):
        """Set the time on this place."""
        t = time.gmtime(secondsSinceEpoch)
        if self.windows:
            # XXX assumes UTC and US locale date format
            dstring = time.strftime("%m-%d-%Y", t)
            tstring = time.strftime("%H:%M:%S", t)
            self.xmlrpcExec("time %s\ndate %s" % (tstring, dstring))
        else:
            dstring = time.strftime("%a %b %d %H:%M:%S UTC %Y", t)
            self.execcmd("date -s '%s'" % (dstring))
        actual = self.getTime()
        if abs(actual - secondsSinceEpoch) > 30.0:
            # The slack is to allow for time elapsed since we started
            # this method
            raise xenrt.XRTError("Unable to set the time",
                                 "On %s. Wanted %u, got %u" %
                                 (self.getName(),
                                  int(secondsSinceEpoch),
                                  int(actual)))

    def getActiveDirectoryServer(self):
        """Return an ActiveDirectoryServer for this place, creating
        a new object if we do not already have one cached."""
        if self.special.has_key("ActiveDirectoryServer"):
            xenrt.TEC().logverbose("Using cached AD server for %s" %
                                   (self.getName()))
            return self.special["ActiveDirectoryServer"]
        ad = ActiveDirectoryServer(self)
        self.special["ActiveDirectoryServer"] = ad
        return ad

    def getV6LicenseServer(self, useEarlyRelease=None, install=True, host = None):
        """Return a V6LicenseServer for this place, creating a new object if we
           do not already have one cached."""
        if self.special.has_key("V6LicenseServer"):
            xenrt.TEC().logverbose("Using cached V6 license server for %s" %
                                   (self.getName()))
            return self.special["V6LicenseServer"]
        v6 = V6LicenseServer(self, useEarlyRelease=useEarlyRelease, install=install, host=host)
        self.special["V6LicenseServer"] = v6
        return v6

    def getDVSCWebServices(self):
        """Return a DVSCWebServices for this place, creating a new object if we
           do not already have one cached."""
        if self.special.has_key("DVSCWebServices"):
            xenrt.TEC().logverbose("Using cached DVSC Web Services for %s" %
                                   (self.getName()))
            return self.special["DVSCWebServices"]

        dvsc = DVSCWebServices(self)
        self.special["DVSCWebServices"] = dvsc

        # Patches the DVSC if defined in SKU
        patchfile = xenrt.TEC().lookup("DVSC_PATCH", None)
        if patchfile != None:
            if xenrt.TEC().lookup("DEV_TEST", None) != None:
                filepath = xenrt.TEC().getFile(patchfile)
            else:
                filepath = patchfile

            xenrt.TEC().logverbose("Calling patch with %s" % filepath)
            dvsc.patchFromFile(filepath)

        # Disable the CSRF check CA-81692
        self.execguest("touch /opt/virtex/etc/disable_csrf_check")
        self.reboot()
        xenrt.sleep(120) # Allow time for the DVSC API to start

        return dvsc

    def installV6LicenseServer(self):
        # The act of getting a V6 license server is enough to install it
        self.getV6LicenseServer()

    def getNetworkInterfaceConfig(self, interface="eth0"):
        """Return a dictionary of ifcfg style network interface configuation
        details."""
        if self.windows:
            raise xenrt.XRTError("getNetworkInterfaceConfig not implemented "
                                 "for Windows")
        else:
            interface = str(interface)
            if re.search("^\d$", interface):
                interface = self.LINUX_INTERFACE_PREFIX + interface
            interface = interface.replace("eth", self.LINUX_INTERFACE_PREFIX)
            ifcfg = "/etc/sysconfig/network-scripts/ifcfg-%s" % (interface)
            if self.execcmd("test -e %s" % (ifcfg), retval="code") != 0:
                raise xenrt.XRTError("No configuration found for interface %s"
                                     % (interface))
            xenrt.TEC().logverbose("Have network config file for %s" %
                                   (interface))
            cfg = self.execcmd("cat %s" % (ifcfg))
            d = dict(re.findall("(\S+)=(.*)", cfg))#
            cfg = self.execcmd("cat /etc/sysconfig/network")
            r = re.search("GATEWAY=(.+)", cfg)
            if r:
                d["GATEWAY"] = r.group(1)
            return d

    def getNetworkInterfaceIPAddress(self, interface="eth0"):
        """Return the IP address of the specified network interface."""
        data = self.execdom0("ip address show dev %s" % (interface))
        r = re.search(r"inet\s+([0-9\.]+)", data)
        if r:
            return r.group(1)
        raise xenrt.XRTError("Could not find IP address for %s on %s" %
                             (interface, self.getName()))

    def reboot(self):
        raise xenrt.XRTError("Function 'reboot' not implemented for this class")

    def devcon(self, command):
        if self.xmlrpcGetArch() == "amd64":
            devconexe = "devcon64.exe"
        else:
            devconexe = "devcon.exe"
        if not self.xmlrpcFileExists("c:\\%s" % devconexe):
            self.xmlrpcSendFile("%s/distutils/%s" % (xenrt.TEC().lookup("LOCAL_SCRIPTDIR"), devconexe), "c:\\%s" % devconexe)
        return self.xmlrpcExec("c:\\%s %s" % (devconexe, command), returndata=True)

    def getWindowsHostName(self):
        return self.xmlrpcExec("hostname", returndata=True).strip().splitlines()[-1]

    def rename(self, name):
        if self.windows:
            curName = self.getWindowsHostName()
            self.xmlrpcExec("wmic ComputerSystem where Name=\"%s\" call Rename Name=\"%s\"" % (curName, name))
            self.winRegAdd("HKLM",
                           "software\\microsoft\\windows nt\\currentversion\\winlogon",
                           "DefaultDomainName",
                           "SZ",
                            name)
            self.reboot()
        else:
            self.execcmd("hostname %s" % name)
            if self.execcmd('test -e /etc/hostname', retval="code") == 0:
                self.execcmd("echo %s > /etc/hostname" % name)
            elif self.execcmd('test -e /etc/sysconfig/network', retval="code") == 0:
                self.execcmd("sed -i '/HOSTNAME/d' /etc/sysconfig/network")
                self.execcmd("echo 'HOSTNAME=%s' >> /etc/sysconfig/network" % name)
            self.execcmd("echo '%s    %s' >> /etc/hosts" % (self.getIP(), name))
                
            

    def sysPrepOOBE(self):
        if not self.windows:
            raise xenrt.XRTError("This can only be performed on Windows installations")

        with open("%s/data/sysprep/unattend.xml" % xenrt.TEC().lookup("XENRT_BASE")) as f:
            unattend = f.read()

        unattend = unattend.replace("%ARCH%", self.xmlrpcGetArch())
        unattend = unattend.replace("%PASSWORD%", xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS", "ADMINISTRATOR_PASSWORD"], "xensource"))
        pkey = xenrt.util.command("grep '%s ' %s/keys/windows | awk '{print $2}'" % (self.distro, xenrt.TEC().lookup("XENRT_CONF"))).strip()
        unattend = unattend.replace("%PRODUCTKEY%", pkey)

        self.xmlrpcWriteFile("c:\\unattend.xml", unattend)

        self.xmlrpcExec("c:\\windows\\system32\\sysprep\\sysprep.exe /unattend:c:\\unattend.xml /oobe /generalize /quiet /quit", returnerror=False)

    def _softReboot(self, timeout=300):
        try:
            self.execcmd("/sbin/reboot", timeout=timeout)
        except xenrt.XRTFailure, e:
            if e.reason != "SSH channel closed unexpectedly" and e.reason != "SSH timed out":
                raise
    
    def upgradeDebian(self, newVersion="testing"):
        codename = self.execguest("cat /etc/apt/sources.list | grep '^deb' | awk '{print $3}' | head -1").strip()
        self.execcmd("sed -i s/%s/%s/g /etc/apt/sources.list" % (codename, newVersion))
        if self.execcmd('test -e /etc/apt/sources.list.d/*', retval="code") == 0:
            self.execcmd("sed -i s/%s/%s/g /etc/apt/sources.list.d/*" % (codename, newVersion))
        try:
            self.execcmd("apt-get update")
        except:
            # We might be upgrading to a version that doesn't have update repos - if that's the case then remove them and try apt-get update again
            self.execcmd("rm -f /etc/apt/sources.list.d/updates.list")
            self.execcmd("apt-get update")
        self.execcmd('DEBIAN_FRONTEND=noninteractive apt-get -y --force-yes -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" upgrade')
        self.execcmd('DEBIAN_FRONTEND=noninteractive apt-get -y --force-yes -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" dist-upgrade')
        self.execcmd('DEBIAN_FRONTEND=noninteractive apt-get -y --force-yes autoremove')
        self._softReboot(timeout=60)
        xenrt.sleep(60)
        if isinstance(self, GenericHost):
            timeout = 600 + int(self.lookup("ALLOW_EXTRA_HOST_BOOT_SECONDS", "0"))
        else:
            timeout = 600
        self.waitForSSH(timeout)
        self.tailor()

    def installWindowsMelio(self, renameHost=False):
        if renameHost:
            self.rename("%s-%s" % (self.name, xenrt.GEC().jobid() or "nojob"))
        self.xmlrpcFetchFile("%s/melio/sanbolic.cer" % xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP"), "c:\\sanbolic.cer")
        self.xmlrpcSendFile("%s/distutils/certmgr.exe" % xenrt.TEC().lookup("LOCAL_SCRIPTDIR"), "c:\\certmgr.exe")
        self.xmlrpcExec("c:\\certmgr.exe /add c:\\sanbolic.cer /c /s /r localmachine trustedpublisher")
        self.xmlrpcFetchFile("%s/melio/%s" % (xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP"), xenrt.TEC().lookup("MELIO_PATH")), "c:\\warm-drive.exe")
        self.xmlrpcExec("c:\\warm-drive.exe /SILENT")
        self.disableFirewall()

    def getWindowsMelioConfig(self):
        return json.loads(unicode(self.xmlrpcReadFile("c:\\program files\\citrix\\warm-drive\\warm-drive.json"), "utf-16"))

    def writeWindowsMelioConfig(self, config):
        d = xenrt.TempDirectory()  
        with open("%s/warm-drive.json" % d.path(), "w") as f:
            f.write(json.dumps(config, indent=2).replace("\n", "\r\n").encode("utf-16"))
        self.xmlrpcSendFile("%s/warm-drive.json" % d.path(), "c:\\program files\\citrix\\warm-drive\\warm-drive.json")
        d.remove()
        self.reboot()

class RunOnLocation(GenericPlace):
    def __init__(self, address):
        GenericPlace.__init__(self)
        self.address = address

    def getIP(self):
        return self.address

class GenericHost(GenericPlace):
    implements(xenrt.interfaces.OSParent)

    # Domain states
    STATE_UNKNOWN  = 0
    STATE_RUNNING  = 1
    STATE_BLOCKED  = 2
    STATE_SAVING   = 3
    STATE_PAUSED   = 4
    STATE_CRASHED  = 5
    STATE_DYING    = 6
    STATE_SHUTDOWN = 7

    def __init__(self,
                 machine,
                 productType="unknown",
                 productVersion="unknown",
                 productRevision="unknown"):
        GenericPlace.__init__(self)
        self.machine = machine
        self.guests = {}
        self.tailored = False
        self.productType = productType
        self.productVersion = productVersion
        self.productRevision = productRevision
        if self.machine:
            self.machine.setHost(self)
        self.volumegroup = None
        self.pddomaintype = "Domain0"
        self.portsToEnableAtCleanup = []
        self.hbasToEnableAtCleanup = []
        self.callbackRegistered = False
        self.replaced = None
        self.use_ipv6 = xenrt.TEC().lookup('USE_HOST_IPV6', False, boolean=True)
        self.ipv6_mode = None
        self.controller = None
        self.containerHost = None
        self.jobTests = []

        xenrt.TEC().logverbose("Creating %s instance." % (self.__class__.__name__))


    def __str__(self):
        return self.getName()

    def __repr__(self):
        return self.__str__()

    def populateSubclass(self, x):
        GenericPlace.populateSubclass(self, x)
        x.machine = self.machine
        x.guests = self.guests
        x.tailored = self.tailored
        x.containerHost = self.containerHost
        if x.machine:
            x.machine.setHost(x)
  
    def getDeploymentRecord(self):
        ret = {"access": {"hostname": self.getName(),
                          "ipaddress": self.getIP()},
               "os": {"family": self.productType,
                      "version": self.productVersion}}
        if self.windows:
            ret['access']['username'] = "Administrator"
            ret['access']['password'] = xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS",
                                                                    "ADMINISTRATOR_PASSWORD"],
                                                                    "xensource")
        else: 
            ret['access']['username'] = "root"
            ret['access']['password'] = self.password
        return ret

    ##### Methods from OSParent #####

    @property
    @xenrt.irregularName
    def _osParent_name(self):
        return self.getName()

    @property
    @xenrt.irregularName
    def _osParent_hypervisorType(self):
        # This refers to the Hypervisor type of the control domain, which for most purposes can assumed to be Native
        return xenrt.HypervisorType.native

    @xenrt.irregularName
    def _osParent_getIP(self, trafficType=None, timeout=600, level=xenrt.RC_ERROR):
        if self.machine and self.use_ipv6:
            return self.machine.ipaddr6
        elif self.machine:
            return self.machine.ipaddr
        return None

    @xenrt.irregularName
    def _osParent_getPort(self, trafficType):
        return None

    @xenrt.irregularName
    def _osParent_setIP(self,ip):
        if self.machine:
            obj = IPy.IP(ip)
            if IPy.IP(ip).version() == 6:
                self.machine.ipaddr6 = ip
            else:
                self.machine.ipaddr = ip
        else:
            raise xenrt.XRTError("No host Object Found")

    @xenrt.irregularName
    def _osParent_start(self):
        self.machine.powerctl.on()

    @xenrt.irregularName
    def _osParent_stop(self):
        self.machine.powerctl.off()

    @xenrt.irregularName
    def _osParent_ejectIso(self):
        # TODO implement this with Virtual Media
        raise xenrt.XRTError("Not implemented")

    @xenrt.irregularName
    def _osParent_setIso(self, isoName, isoRepo=None):
        # TODO implement this with Virtual Media
        raise xenrt.XRTError("Not implemented")

    @xenrt.irregularName
    def _osParent_pollPowerState(self, state, timeout=600, level=xenrt.RC_FAIL, pollperiod=15):
        """Poll for reaching the specified state"""
        raise xenrt.XRTError("Not supported")

    @xenrt.irregularName
    def _osParent_getPowerState(self):
        """Get the current power state"""
        raise xenrt.XRTError("Not supported")

    def registerJobTest(self, jt):
        try:
            if xenrt.TEC().lookup("JTSKIP_%s" % jt.TCID, False, boolean=True):
                return
            self.jobTests.append(jt(self))
        except:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().logverbose("Exception instantiating job test %s" % str(jt))

    def disableMultipathingInKernel(self, reboot=True):
        """
        Disable multipathing if the root disk of Dom0 has it switched on already

        Add a line to the latches file and rebuild the initrd
        The host should then reboot in order that the changes
        are enacted.

        @param reboot: reboot the machine after kernel rebuild
        @type reboot: boolean
        @rtype: void
        """
        latchesFile = "/etc/sysconfig/mkinitrd.latches"
        option = "--without-multipath"

        if self._stringIsInFile(option, latchesFile):
            xenrt.TEC().logverbose("Option already found in file, skipping addition...")
            return

        self.execdom0("echo {0}>>{1}".format(option, latchesFile))
        self.rebuildInitrd()
        if reboot:
            self.reboot()

    def _stringIsInFile(self, stringToFind, fileName):
        """
        Look for a string in the given file in the dom0 file system

        @param stringToFind: pattern to look for in a file
        @type stringToFind: string
        @param fileName: file in the Dom0 filesysten
        @type fileName: string
        @return: the string is found in the file
        @rtype: boolean
        """
        res = self.execdom0("grep -e'{0}' {1} || true".format(stringToFind, fileName))
        return len(res) > 0

    def getIP(self):
        if self.machine and self.use_ipv6:
            return self.machine.ipaddr6
        elif self.machine:
            return self.machine.ipaddr
        return None

    def setIP(self,ip):
        if self.machine:
            obj = IPy.IP(ip)
            if IPy.IP(ip).version() == 6:
                self.machine.ipaddr6 = ip
            else:
                self.machine.ipaddr = ip
        else:
            raise xenrt.XRTError("No host Object Found")

    def getPXEIP(self):
        if self.machine:
            return self.machine.pxeipaddr
        return None

    def getIPv6AutoconfAddress(self, dev=0):
        network = self.getNICNetworkName(dev)
        mac = self.getNICMACAddress(dev)
        host_id = xenrt.getInterfaceIdentifier(mac.lower())
        router_prefix, _, _ = self.getIPv6NetworkParams(nw=network)
        router_prefix = router_prefix.replace('::',':')
        return (router_prefix  + host_id)

    def getName(self):
        if self.machine:
            return self.machine.name
        return None

    def getInfo(self):
        name = self.getName()
        if not name:
            name = "UNKNOWN"
        ip = self.getIP()
        if not ip:
            ip = "UNKNOWN"
        return [name, ip]

    def lookup(self, var, default=xenrt.XRTError, boolean=False):
        """Lookup a per-host variable"""
        if not self.productVersion:
            return xenrt.TEC().lookupHost(self.getName(),
                                          var,
                                          default=default,
                                          boolean=boolean)
        return xenrt.TEC().lookupHostAndVersion(self.getName(),
                                                self.productVersion,
                                                var,
                                                default=default,
                                                boolean=boolean)

    def waitForSSH(self, timeout, level=xenrt.RC_FAIL, desc="Operation",
                   username="root", cmd="true"):
        timeout = timeout + int(self.lookup("ALLOW_EXTRA_HOST_BOOT_SECONDS", "0"))
        GenericPlace.waitForSSH(self, timeout, level, desc, username, cmd)
        if self.lookup("SERIAL_DISABLE_ON_BOOT",False, boolean=True) and self.machine.consoleLogger:
            self.machine.consoleLogger.reload()


    def addGuest(self, guest):
        self.guests[guest.name] = guest

    def getGuest(self, name):
        if self.guests.has_key(name):
            return self.guests[name]
        return None

    def removeGuest(self, name):
        if self.guests.has_key(name):
            del self.guests[name]

    def uninstallAllGuests(self):
        """Uninstall all guests on this host."""
        while 1:
            guests = self.listGuests()
            if len(guests) == 0:
                break
            for gname in guests:
                g = self.getGuest(gname)
                if not g:
                    # Probably not from this test run
                    g = self.createGuestObject(gname)
                try:
                    g.shutdown(force=True)
                except:
                    pass
                g.poll("DOWN", 120, level=xenrt.RC_ERROR)
                g.uninstall()
                xenrt.sleep(15)

    def transformCommand(self, command):
        """
        Tranform commands if it is required on Host
        
        @param command: The command that can be transformed.
        @return: transformed command
        """

        return command

    def execdom0(self,
                 command,
                 username=None,
                 retval="string",
                 level=xenrt.RC_FAIL,
                 timeout=300,
                 idempotent=False,
                 newlineok=False,
                 nolog=False,
                 outfile=None,
                 useThread=False,
                 getreply=True,
                 password=None):
        """Execute a command on the dom0 of the specified machine.

        @param retval:  Whether to return the result code or stdout as a string
            "C{string}" (default), "C{code}"
            if "C{string}" is used then a failure results in an exception
        @param level:   Exception level to use if appropriate.
        @param nolog:   If C{True} then don't log the output of the command
        @param useThread: If C{True} then run the SSH command in a thread to
                        guard against hung SSH sessions
        """
        try:
            if not isinstance(self.os, xenrt.xenrt.lib.opsys.LinuxOS):
                xenrt.TEC().warning("OS is not Linux - self.os is of type %s" % str(self.os.__class__))
                [xenrt.TEC().logverbose(x) for x in traceback.format_stack()]
        except Exception, e:
            xenrt.TEC().warning("Error creating OS: %s" % str(e))
            [xenrt.TEC().logverbose(x) for x in traceback.format_stack()]
        if not username:
            if self.windows:
                username = "Administrator"
            else:
                username = "root"
        if not password:
            password = self.password
        return xenrt.ssh.SSH(self.getIP(),
                             self.transformCommand(command),
                             level=level,
                             retval=retval,
                             password=password,
                             timeout=timeout,
                             username=username,
                             idempotent=idempotent,
                             newlineok=newlineok,
                             nolog=nolog,
                             outfile=outfile,
                             getreply=getreply,
                             useThread=useThread)

    def postInstall(self):
        """Perform any product-specific post install actions."""
        pass

    def postUpgrade(self):
        """Perform any product-specific post upgrade actions."""
        pass

    def preJobTests(self):
        """Perform any pre-job phases of job tests"""
        for jt in self.jobTests:
            try:
                jt.preJob()
            except Exception, e:
                traceback.print_exc(file=sys.stderr)
                xenrt.TEC().warning("Exception running job test %s pre method: %s" % (str(jt), str(e)))

    def postJobTests(self):
        """Perform any post-job phases of job tests"""
        for jt in self.jobTests:
            try:
                result = jt.postJob()
                if result is not None:
                    tcid = jt.TCID
                    reason = jt.FAIL_MSG
                    data = result
                    xenrt.TEC().logverbose("Post job test %s failed" % str(jt))
                    xenrt.TEC().logverbose("Post job test fail reason: %s" % (str(result)))
                    if xenrt.TEC().lookup("AUTO_BUG_FILE", False, boolean=True) and tcid:
                        jl = xenrt.jiralink.getJiraLink()
                        jl.processJT(xenrt.TEC(), tcid, reason, data)
            except Exception, e:
                traceback.print_exc(file=sys.stderr)
                xenrt.TEC().warning("Exception running job test %s: %s" % (str(jt), str(e)))

    def xapiCPUUsage(self):
        # Check for xenstored using too much CPU, if a pid is not found, None is returned
        pid = None
        pidLocations = ["/var/run/xenstore.pid", "/var/run/xenstored.pid"]
        for p in pidLocations:
            try:
                pid = int(self.execdom0("cat %s" % (p)))
                break
            except:
                pass
        pcpu = None
        if pid:
            self.execdom0("[ -d /proc/%u ]" % (pid))
            pcpu = float(self.execdom0("ps -p %u -o pcpu --no-headers" % (pid)).strip())
        return pcpu
        
    def checkHealth(self, unreachable=False, noreachcheck=False, desc=""):
        """Make sure the dom0 is in good shape."""
        if unreachable:
            # This is to make this check compatible with waitForSSH failures
            return
        # Make sure we've not filled the disk
        space = string.strip(self.execdom0("df -P -m / | awk '{if "
                                           "($5 != \"Use%\") {print $5}}'",
                                           idempotent=True))
        if space == "100%":
            xenrt.TEC().warning("Domain-0 disk usage is 100%")
        pcpu = self.xapiCPUUsage()
        if pcpu and pcpu > 40.0:
            xenrt.TEC().warning("xenstore using %.2f%% CPU" % (pcpu))
            log("xenstore using %.2f%% CPU" % (pcpu))

    def checkLeasesXenRTDhcpd(self, mac, checkWithPing=False):
        valid = json.loads(xenrt.util.command("%s/xenrtdhcpd/leasesformac.py %s" % (xenrt.TEC().lookup("XENRT_BASE"), mac.lower())))
        if not valid:
            return None
        for a in valid:
            if checkWithPing and xenrt.command("ping -c 3 -w 10 %s" % a, retval="code", level=xenrt.RC_OK) == 0:
                return a

        return valid[0]

    def checkLeases(self, mac, checkWithPing=False):
        rem = self.lookup("REMOTE_DHCP", None)
        if rem:
            leasefile = xenrt.TEC().tempFile()
            xenrt.util.command("%s > %s" % (rem, leasefile))
        elif self.lookup("XENRT_DHCPD", False, boolean=True):
            return self.checkLeasesXenRTDhcpd(mac, checkWithPing)
        elif os.path.exists("/var/lib/dhcp/dhcpd.leases"):
            leasefile = "/var/lib/dhcp/dhcpd.leases"
        elif os.path.exists("/var/lib/dhcpd/dhcpd.leases"):
            leasefile = "/var/lib/dhcpd/dhcpd.leases"
        else:
            xenrt.TEC().logverbose("Couldn't find dhcpd.leases.")
            return None
        try:
            data = xenrt.util.command("grep -C 20 %s %s" % (mac, leasefile))
        except:
            xenrt.TEC().logverbose("Couldn't find %s in dhcpd.leases." % (mac))

            try:
                xenrt.command("sudo zgrep '%s' /var/log/syslog*" % mac)
            except:
                pass

            return None
        # matches is a list of tuples of (ip,start,end)
        matches = re.findall("lease (?P<ip>[0-9\.]+)[^}]+"
                          "starts [0-9] (?P<start>[0-9/: ]+)[^}]+"
                          "ends [0-9] (?P<end>[0-9/: ]+)[^}]+"
                          "hardware ethernet %s" % (mac),
                           data)
        if len(matches) > 0:
            now = time.time()
            valid = []
            for match in matches:
                start = time.mktime(time.strptime(match[1],
                                              "%Y/%m/%d %H:%M:%S"))
                end = time.mktime(time.strptime(match[2],
                                            "%Y/%m/%d %H:%M:%S"))
                if start < now and now < end:
                    xenrt.TEC().logverbose("Found IP %s for MAC %s in "
                                           "/var/lib/dhcp/dhcpd.leases. "
                                           "(%s < %s < %s)" %
                                           (match[0],
                                            mac,
                                            match[1],
                                            time.strftime("%Y/%m/%d %H:%M:%S",
                                                          time.gmtime(now)),
                                            match[2]))
                    valid.append(match)
                else:
                    xenrt.TEC().logverbose("Found IP %s but it was out of date. "
                                           "(%s %s %s)" % (match[0],match[1],
                                            time.strftime("%Y/%m/%d %H:%M:%S",
                                                          time.gmtime(now)),
                                            match[2]))
            if valid:
                # Return the most recent valid IP.
                valid.sort(lambda x,y:cmp(time.mktime(time.strptime(x[1],
                                              "%Y/%m/%d %H:%M:%S")),
                                          time.mktime(time.strptime(y[1],
                                              "%Y/%m/%d %H:%M:%S"))))
                valid.reverse()

                for a in valid:
                    if checkWithPing and xenrt.command("ping -c 3 -w 10 %s" % a[0], retval="code", level=xenrt.RC_OK) == 0:
                        return a[0]


                return valid[0][0]
        else:
            xenrt.TEC().logverbose("Couldn't find MAC %s in %s" %
                                   (mac, leasefile))
            return None

    TCPDUMP = "tcpdump"

    def getUptime(self):
        return 0

    def arpwatch(self, iface, mac, timeout=600, level=xenrt.RC_FAIL):
        """Monitor an interface (or bridge) for an ARP reply"""

        xenrt.TEC().logverbose("Sniffing ARPs on %s for %s" % (iface, mac))

        deadline = xenrt.util.timenow() + timeout

        if xenrt.TEC().lookup("XENRT_DHCPD", False, boolean=True):
            uptime = self.getUptime()
            while True:
                ip = self.checkLeases(mac)
                if ip:
                    return ip
                if self.getUptime() < uptime:
                    self.checkHealth()
                xenrt.sleep(20)
                if xenrt.util.timenow() > deadline:
                    xenrt.XRT("Timed out monitoring for guest DHCP lease", level, data=mac)

        myres = []
        myres.append(re.compile(r"(?P<ip>[0-9.]+) is-at (?P<mac>[0-9a-f:]+)"))
        myres.append(re.compile(r"> (?P<mac>[0-9a-f:]+).*> (?P<ip>[0-9.]+).bootpc: BOOTP/DHCP, Reply"))
        myres.append(re.compile(r"\s+(?P<mac>[0-9a-f:]+)\s+>\s+Broadcast.*ARP.*tell\s+(?P<ip>[0-9.]+)"))
        myres.append(re.compile(r"\s+(?P<mac>[0-9a-f:]+)\s+>\s+ff:ff:ff:ff:ff:ff.*ARP.*tell\s+(?P<ip>[0-9.]+)")) # tcpdump-uw formatting of 'broadcast' MAC
        myres.append(re.compile(r"> (?P<mac>[0-9a-f:]+),.* [0-9.]+ > (?P<ip>[0-9.]+)\.[0-9]+: BOOTP/DHCP"))
        ip = None
        lip = None
        while True:
            tcpdump_command = "%s -lne -i \"%s\" arp or udp port bootps" % \
                              (self.TCPDUMP, iface)
            # Start a tcpdump
            s = xenrt.ssh.SSHCommand(self.machine.ipaddr,
                                     tcpdump_command,
                                     username="root",
                                     timeout=3600,
                                     level=xenrt.RC_ERROR,
                                     password=self.password)
            xenrt.TEC().logverbose("Command: %s" % tcpdump_command)

            try:
                # Watch the output for our MAC
                while True:
                    now = xenrt.util.timenow()
                    if now > deadline:
                        ip = self.checkLeases(mac)
                        if not ip and lip:
                            ip = lip
                        if ip:
                            break
                        self.checkHealth(unreachable=True)
                        xenrt.XRT("Timed out monitoring for guest ARP/DHCP", level, data=mac)

                    output = s.fh.readline()
                    if len(output) == 0:
                        break
                    for myre in myres:
                        r = myre.search(output)
                        if r:
                            tip = r.group("ip")
                            tmac = r.group("mac")
                            if xenrt.util.normaliseMAC(tmac) == xenrt.util.normaliseMAC(mac) and not tip in ("255.255.255.255", "0.0.0.0"):
                                ip = tip
                                xenrt.TEC().logverbose("Matched: %s" % (output))
                                break
                    if ip:
                        if re.match("169\.254\..*", ip):
                            lip = ip
                            ip = None
                        else:
                            break

            finally:
                s.client.close()
                s.close()

            if ip:
                break
            xenrt.sleep(2)

        if re.match("169\.254\..*", ip):
            raise xenrt.XRTFailure("VM gave itself a link-local address.")

        return ip

    def checkVersion(self, versionNumber=False):
        # Figure out the product version and revision of the host
        if self.windows:
            self.productType = "nativewindows"
            self.productVersion = None
            try:
                if "[X]" in self.xmlrpcExec("Get-WindowsFeature -Name Hyper-V", powershell=True, returndata=True):
                    self.productType = "hyperv"
            except:
                pass
        else:
            data = ""
            if self.execdom0("test -e /etc/xensource-inventory", retval="code") == 0:
                data = self.execdom0("cat /etc/xensource-inventory")
                r = re.search("PRODUCT_VERSION='([\d+\.]+)'", data)
                if r:
                    version = r.group(1)
                    name = xenrt.TEC().lookup(["PRODUCT_CODENAMES", version], None)
                else:
                    r = re.search("PLATFORM_VERSION='([\d+\.]+)'", data)
                    if r:
                        version = r.group(1)
                        name = xenrt.TEC().lookup(["PLATFORM_CODENAMES", version], None)
                    else:
                        raise xenrt.XRTFailure("Failed to determine XenServer / XCP Version")
            elif self.execdom0("test -e /etc/xcp/inventory", retval="code") == 0:
                data = self.execdom0("cat /etc/xcp/inventory")
                r = re.search("PRODUCT_VERSION='([\d+\.]+)'", data)
                if r:
                    version = r.group(1)
                    name = xenrt.TEC().lookup(["KRONOS_CODENAMES", version], None)
                else:
                    raise xenrt.XRTFailure("Failed to determine KRONOS Version")
            elif self.execdom0("test -e /etc/vmware", retval="code") == 0:
                # e.g. "ESXi"
                name        = self.execdom0("grep ^product /etc/slp.reg").strip().split("\"")[1].split(" ")[1]
                # e.g. "5.0.0"
                version     = self.execdom0("grep ^product-version /etc/vmware/hostd/ft-hostd-version").strip().split(" ")[2]
                # e.g. "623860"
                buildNumber = self.execdom0("grep ^build /etc/vmware/hostd/ft-hostd-version").strip().split(" ")[2]
            elif self.execdom0("virsh list", retval="code") == 0:
                # It's probably KVM
                name = "KVM"
                version = "Linux"
                buildNumber = ""
            elif self.execdom0("test -e /etc/redhat-release", retval="code") == 0:
                name = "Linux"
                version = "RedHat"
                buildNumber = ""
            elif self.execdom0("test -e /etc/xen", retval="code") == 0:
                name = "OSS"
                version = ""
                buildNumber = ""
            elif self.execdom0("test -e /etc/debian_version", retval="code") == 0:
                name = "Linux"
                version = "Debian"
                buildNumber = ""
            else:
                raise xenrt.XRTFailure("Failed to identify host software")

            if not name:
                raise xenrt.XRTFailure("Failed to resolve host software version")

            if data:
                r = re.search(r"BUILD_NUMBER=.*?(\w+).*", data)
                if not r:
                    raise xenrt.XRTFailure("Failed to get build number")
    
                buildNumber = r.group(1)

            if "47101" in buildNumber:
                name = "Oxford"
            elif "58523" in buildNumber:
                name = "SanibelCC"
            if name == "Creedence" and self.execdom0("grep XS65ESP1 /var/patch/applied/*", retval="code") == 0:
                name = "Cream"
            elif name == "Creedence" and not "90233" in buildNumber:
                name = "Cream"

            xenrt.TEC().logverbose("Found: Version Name: %s, Version Number: %s" % (name, version))
            xenrt.TEC().logverbose("Found Build: %s" % (buildNumber))

            self.productVersion = name
            self.productRevision = "%s-%s" % (version, buildNumber)

        if versionNumber:
            return version

    def tailor(self):
        """Tailor to allow other tests to be run"""
        ip = self.getIP()
        if not ip:
            raise xenrt.XRTError("Unknown IP address to SSH to %s" %
                                 (self.machine.name))

        if not self.windows:
            self.findPassword()

            if self.special.get("debiantesting_upgrade"):
                self.special['debiantesting_upgrade'] = False
                self.upgradeDebian(newVersion="testing")
            
            if xenrt.TEC().lookup("TAILOR_CLEAR_IPTABLES", False, boolean=True):
                self.execdom0("iptables -P INPUT ACCEPT && iptables -P OUTPUT ACCEPT && iptables -P FORWARD ACCEPT && iptables -F && iptables -X")
                self.iptablesSave()

            # Copy the test scripts to the guest
            xrt = xenrt.TEC().lookup("XENRT_BASE", "/usr/share/xenrt")
            sdir = self.lookup("REMOTE_SCRIPTDIR")
            self.execdom0("rm -rf %s" % (sdir))
            self.execdom0("mkdir -p %s" % (os.path.dirname(sdir)))
            sftp = self.sftpClient()
            sftp.copyTreeTo("%s/scripts" % (xrt), sdir)
            sftp.close()

            # Save more log files.
            try:
                self.execdom0("cat /etc/logrotate.conf | "
                              "sed 's/rotate 4/rotate 50/' > "
                              "/etc/logrotate.new")
                self.execdom0("mv /etc/logrotate.new /etc/logrotate.conf")
            except:
                pass
        else:
            self.xmlrpcTailor()
        self.checkVersion()

    def getXMInfoItem(self, param):
        data = self.execdom0("xm info")
        r = re.search("^%s\s+:\s+(.*)$" % (param), data, re.MULTILINE)
        if not r:
            raise xenrt.XRTError("Could not find %s in xm info" % (param))
        return r.group(1)

    def getCPUCores(self):
        """Return the number of logical CPUs (including hyperthreads)"""
        return int(self.getXMInfoItem("nr_cpus"))

    def getFreeMemory(self):
        """Return the amount of free memory in MB"""
        return int(self.getXMInfoItem("free_memory"))

    def getDefaultInterface(self):
        """Return the enumeration ID for the configured default interface."""
        return self.lookup("OPTION_CARBON_NETS", "eth0").split()[0]

    def getPrimaryBridge(self):
        """Return the name of the first bridge."""
        brs = self.getBridges()
        if brs:
            return brs[0]

    def getBridges(self):
        """Return the list of bridges on the host."""
        brs = string.split(self.execdom0(\
            "brctl show | awk '{if(!/^[[:space:]]/ && FNR != 1){print $1}}' | "
            "grep ^[xeb]"))
        if len(brs) == 0:
            return None
        return brs

    def listSecondaryNICs(self, network=None, rspan=False, speed=None, macaddr=None):
        """Return a list of "assumed" IDs (integers) of secondary NICs for this
        host as defined in the per-machine config."""
        reply = []
        i = 1
        while True:
            mac = self.lookup(["NICS", "NIC%u" % (i), "MAC_ADDRESS"], None)
            nw = self.lookup(["NICS", "NIC%u" % (i), "NETWORK"], None)
            rs = self.lookup(["NICS", "NIC%u" % (i), "RSPAN"], False, boolean=True)
            sp = self.lookup(["NICS", "NIC%u" % (i), "SPEED"], None)
            if sp == "1G":
                sp = None
            if mac and nw:
                if network == None or network == nw or network == "ANY":
                    if (not rspan) or rs:
                        if speed == None or speed == sp or (speed == "1G" and not sp):
                            if macaddr == None or xenrt.util.normaliseMAC(macaddr) == xenrt.util.normaliseMAC(mac):
                                reply.append(i)
            else:
                break
            i = i + 1
        return reply

    def getSecondaryNIC(self, assumedid):
        """ Compatibility function - see getNIC """
        return self.getNIC(assumedid)


    def getNIC(self, assumedid):
        """ Return the product enumeration name (e.g. "eth2") for the
        assumed enumeration ID (integer)"""
        mac = self.getNICMACAddress(assumedid)
        mac = xenrt.util.normaliseMAC(mac)
        data = self.execdom0("ifconfig -a")
        intfs = re.findall(r"(eth\d+|p\d+p\d+).*?(HWaddr|\n\s+ether)\s+([A-Za-z0-9:]+)", data)
        for intf in intfs:
            ieth, _, imac = intf
            if xenrt.util.normaliseMAC(imac) == mac:
                return ieth
        raise xenrt.XRTError("Could not find interface with MAC %s" % (mac))

    def getNICMACAddress(self, assumedid):
        """Return the MAC address of the NIC specified by the integer
        assumed enumeration ID."""
        if assumedid == 0:
            return self.lookup("MAC_ADDRESS")
        return self.lookup(["NICS", "NIC%u" % (assumedid), "MAC_ADDRESS"])

    def getNICAllocatedIPAddress(self, assumedid, also_ipv6=False):
        """Return the allocated IP address, subnet mask and gateway of the NIC
        specified by the integer assumed enumeration ID."""
        gateway6 = None
        ip6 = None
        if assumedid == 0:
            ip = self.lookup("HOST_ADDRESS")
            netmask = self.lookup(["NETWORK_CONFIG", "DEFAULT", "SUBNETMASK"])
            gateway = self.lookup(["NETWORK_CONFIG", "DEFAULT", "GATEWAY"])
            if also_ipv6:
                ip6 = self.lookup("HOST_ADDRESS6")
                gateway6 = self.lookup(["NETWORK_CONFIG", "DEFAULT", "GATEWAY6"])
        else:
            ip = self.lookup(["NICS", "NIC%u" % (assumedid), "IP_ADDRESS"],
                             None)
            if also_ipv6:
                ip6 = self.lookup(["NICS", "NIC%u" % (assumedid), "IP_ADDRESS6"],
                                  None)
            if not ip:
                raise xenrt.XRTError(\
                    "No IP address specified for host %s NIC%u" %
                    (self.getName(), assumedid))
            nw = self.lookup(["NICS", "NIC%u" % (assumedid), "NETWORK"], None)
            if not nw:
                raise xenrt.XRTError(\
                    "No network specificed for host %s NIC%u" %
                    (self.getName(), assumedid))
            if nw == "NPRI":
                netmask = self.lookup(["NETWORK_CONFIG",
                                       "DEFAULT",
                                       "SUBNETMASK"])
                gateway = self.lookup(["NETWORK_CONFIG",
                                       "DEFAULT",
                                       "GATEWAY"])
                if also_ipv6:
                    gateway6 = self.lookup(["NETWORK_CONFIG", "DEFAULT", "GATEWAY6"])

            elif nw == "NSEC":
                netmask = self.lookup(["NETWORK_CONFIG",
                                       "SECONDARY",
                                       "SUBNETMASK"])
                gateway = self.lookup(["NETWORK_CONFIG",
                                       "SECONDARY",
                                       "GATEWAY"])
                if also_ipv6:
                    gateway6 = self.lookup(["NETWORK_CONFIG", "SECONDARY", "GATEWAY6"])

            elif nw == "IPRI":
                netmask = self.lookup(["NETWORK_CONFIG",
                                       "VLANS", "IPRI",
                                       "SUBNETMASK"])
                gateway = self.lookup(["NETWORK_CONFIG",
                                       "VLANS", "IPRI",
                                       "GATEWAY"])
                if also_ipv6:
                    gateway6 = self.lookup(["NETWORK_CONFIG",
                                            "VLANS",
                                            "IPRI",
                                            "GATEWAY6"])
            else:
                raise xenrt.XRTError(\
                    "Don't know how to determine subnet mask and "
                    "gateway for network '%s' on host %s NIC%u" %
                    (nw, self.getName(), assumedid))
        if not netmask:
            raise xenrt.XRTError(\
                "Could not determine subnet mask for host %s NIC%u" %
                (self.getName(), assumedid))
        if not gateway:
            raise xenrt.XRTError(\
                "Could not determine gateway for host %s NIC%u" %
                (self.getName(), assumedid))

        if also_ipv6:
            return ip, netmask, gateway, ip6, gateway6
        else:
            return ip, netmask, gateway

    def getNICNetworkAndMask(self, assumedid):
        """Return the network/mask of the NIC specified by the integer
        assumed enumeration ID."""
        if assumedid == 0:
            netmask = self.lookup(["NETWORK_CONFIG", "DEFAULT", "SUBNETMASK"])
            subnet = self.lookup(["NETWORK_CONFIG", "DEFAULT", "SUBNET"])
        else:
            nw = self.lookup(["NICS", "NIC%u" % (assumedid), "NETWORK"], None)
            if not nw:
                raise xenrt.XRTError(\
                    "No network specificed for host %s NIC%u" %
                    (self.getName(), assumedid))
            if nw == "NPRI":
                netmask = self.lookup(["NETWORK_CONFIG",
                                       "DEFAULT",
                                       "SUBNETMASK"])
                subnet = self.lookup(["NETWORK_CONFIG",
                                      "DEFAULT",
                                      "SUBNET"])
            elif nw == "NSEC":
                netmask = self.lookup(["NETWORK_CONFIG",
                                       "SECONDARY",
                                       "SUBNETMASK"])
                subnet = self.lookup(["NETWORK_CONFIG",
                                      "SECONDARY",
                                      "SUBNET"])
            elif nw == "IPRI" or nw == "ISEC":
                netmask = self.lookup(["NETWORK_CONFIG",
                                       "VLANS",
                                       nw,
                                       "SUBNETMASK"])
                subnet = self.lookup(["NETWORK_CONFIG",
                                      "VLANS",
                                      nw,
                                      "SUBNET"])
            else:
                raise xenrt.XRTError(\
                    "Don't know how to determine subnet and mask "
                    "for network '%s' on host %s NIC%u" %
                    (nw, self.getName(), assumedid))
        if not netmask:
            raise xenrt.XRTError(\
                "Could not determine subnet mask for host %s NIC%u" %
                (self.getName(), assumedid))
        if not subnet:
            raise xenrt.XRTError(\
                "Could not determine subnet for host %s NIC%u" %
                (self.getName(), assumedid))
        return subnet, netmask

    def getNICNetworkName(self, assumedid):
        """Return the symbolic network name of the NIC specified by the integer
        assumed enumeration ID."""
        if assumedid == 0:
            return "NPRI"
        nw = self.lookup(["NICS", "NIC%u" % (assumedid), "NETWORK"], None)
        if not nw:
            raise xenrt.XRTError(\
                "No network specificed for host %s NIC%u" %
                (self.getName(), assumedid))
        return nw

    def getCPUVendor(self):
        data = self.execdom0("cat /proc/cpuinfo")
        r = re.search(r"vendor_id\s+:\s+(\S+)", data)
        if r:
            return r.group(1)
        return None

    def getCPUSpeed(self):
        data = self.execdom0("cat /proc/cpuinfo")
        r = re.search(r"cpu MHz\s+:\s+(\S+)", data)
        if r:
            return float(r.group(1))
        return None

    def getMemorySpeed(self):
        data = self.execdom0("dmidecode")
        r = re.search(r"^\s+Speed: (\d+) MHz", data, re.MULTILINE)
        if r:
            return int(r.group(1))
        return None

    def listDomains(self, includeS=False):
        """Return a list of domains and their basic details."""
        reply = {}
        xmli = self.execdom0("xm list")
        for line in string.split(xmli, "\n"):
            fields = string.split(line)
            if len(fields) >= 6:
                if fields[1] == "ID":
                    continue
                domname = fields[0]
                domid = int(fields[1])
                memory = int(fields[2])
                vcpus = int(fields[3])
                cputime = float(fields[5])
                state = self.STATE_UNKNOWN
                if string.find(fields[4], "r") > -1:
                    state = self.STATE_RUNNING
                elif string.find(fields[4], "b") > -1:
                    state = self.STATE_BLOCKED
                elif string.find(fields[4], "s") > -1:
                    state = self.STATE_SAVING
                elif string.find(fields[4], "p") > -1:
                    state = self.STATE_PAUSED
                elif string.find(fields[4], "c") > -1:
                    state = self.STATE_CRASHED
                reply[domname] = [domid, memory, vcpus, state, cputime]
        return reply

    def getDomid(self, guest):
        """Return the domid of the specified guest."""
        domains = self.listDomains(includeS=True)
        if domains.has_key(guest.name):
            return domains[guest.name][0]
        raise xenrt.XRTError("Domain '%s' not found" % (guest.name))

    def enableGuestConsoleLogger(self, enable=True, persist=False):
        """Start and enable to guest console logging daemon"""
        # If the host console daemon has special powers (TM) then use them
        if self.execdom0("grep -q '/local/logconsole/@' /usr/sbin/xenconsoled",
                         retval="code") == 0:
            self.guestconsolelogs = xenrt.TEC().lookup(\
                "GUEST_CONSOLE_LOGDIR")
            if enable:
                self.execdom0("mkdir -p %s" % (self.guestconsolelogs))
                self.xenstoreWrite("/local/logconsole/@",
                                        "%s/console.%%d.log" %
                                        (self.guestconsolelogs))
            else:
                self.xenstoreWrite("/local/logconsole/@", "")
            if persist:
                self.execdom0("echo 'mkdir -p %s' >> /etc/rc.d/rc.local" % (self.guestconsolelogs))
                self.execdom0("echo 'xenstore-write /local/logconsole/@ "
                              "%s/console.%%d.log' >> /etc/rc.d/rc.local" %
                              (self.guestconsolelogs))
            return
        # Do not start a logger is we don't have xm
        if self.execdom0("test -e /usr/sbin/xm", retval="code") != 0:
            xenrt.TEC().logverbose("Not running the guest console logger")
            return
        self.guestconsolelogs = xenrt.TEC().lookup("GUEST_CONSOLE_LOGDIR")
        if enable:
            action = "start"
        else:
            action = "stop"
        cmd = "%s/lib/console %s %s" % \
              (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"),
               action,
               self.guestconsolelogs)
        self.execdom0(cmd)
        if persist:
            self.execdom0("echo 'rm -f %s/.run' >> /etc/rc.d/rc.local" %
                          (self.guestconsolelogs))
            self.execdom0("echo 'mkdir -p %s' >> /etc/rc.d/rc.local" % (self.guestconsolelogs))
            self.execdom0("echo '%s' >> /etc/rc.d/rc.local" % (cmd))

    def guestConsoleLogTail(self, domid, lines=20):
        """Return the last lines of the guest console log for the domid.
        This requires that the guest console logger is running. It makes
        no check that the log used is the correct one for this host boot,
        i.e. it might end up giving back output from the same domid on a
        previous boot.
        """
        if not self.guestconsolelogs:
            return ""
        filename = "%s/console.%u.log" % (self.guestconsolelogs, domid)
        try:
            return self.execdom0("tail -n %u %s" % (lines, filename))
        except:
            return ""

    def getBridgeInterfaces(self, bridge):
        """Return a list of interfaces on the bridge, or None if that bridge
        does not exist."""
        data = self.execdom0("brctl show")
        if not re.search("^%s\s" % (bridge), data, re.MULTILINE):
            return None
        ifs = string.split(self.execdom0(
            "brctl show | awk '{if(/^%s[[:space:]]/){x=1;"
            "  if (!/get port info/)print $4}else if(/^[[:alnum:]]/){x=0}"
            "else if(x){print $1}}'" % (bridge)))
        return ifs

    def hostTempDir(self, prefix=""):
        return string.strip(self.execdom0("mktemp -d %s/tmp/distXXXXXX" %
                                          (prefix)))

    def hostTempFile(self, prefix=""):
        return string.strip(self.execdom0("mktemp %s/tmp/distXXXXXX" %
                                          (prefix)))

    def getGuestUUID(self, guest):
        return None

    def reboot(self,forced=False,timeout=600):
        """Reboot the host and verify it boots"""
        # Some ILO controllers have broken serial on boot
        if self.lookup("SERIAL_DISABLE_ON_BOOT",False, boolean=True) and self.machine.consoleLogger:
            self.machine.consoleLogger.pauseLogging()

        if forced:
            self.execdom0("(sleep 5 && echo b > /proc/sysrq-trigger) "
                          "> /dev/null 2>&1 </dev/null &")
            xenrt.sleep(5)
        else:
            self._softReboot()
        rebootTime = xenrt.util.timenow()
        xenrt.sleep(180)
        for i in range(3):
            try:
                self.waitForSSH(timeout, desc="Host reboot of !" + self.getName())
            except xenrt.XRTException, e:
                if not re.search("timed out", e.reason):
                    raise
                # Try again if this is a known BIOS/hardware boot problem
                if not self.checkForHardwareBootProblem(True):
                    raise
                rebootTime = xenrt.util.timenow()
                self.waitForSSH(timeout, desc="Host reboot of !" + self.getName())
            # Check what we can SSH to is the rebooted host

            try:
                uptime = self.execdom0("uptime")
            except Exception, e:
                xenrt.TEC().logverbose(str(e))
                uptime = ""
            r = re.search(r"up (\d+) min", uptime)
            minsSinceReboot = int((xenrt.util.timenow() - rebootTime) / 60)
            if r and int(r.group(1)) <= minsSinceReboot:
                if xenrt.TEC().lookup("REMOTE_SCRIPTDIR")[0:5] == "/tmp/":
                    # Re-tailor because the scripts live in ramdisk
                    self.tailor()
                return
            # Give it a second chance before trying the reboot again
            # This is to try to avoid a race on slow shutdowns (XRT-3155)
            xenrt.sleep(60)
            self.waitForSSH(timeout, desc="Host reboot of !" + self.getName())
            try:
                uptime = self.execdom0("uptime")
            except Exception, e:
                xenrt.TEC().logverbose(str(e))
                uptime = ""
            r = re.search(r"up (\d+) min", uptime)
            minsSinceReboot = int((xenrt.util.timenow() - rebootTime) / 60)
            if r and int(r.group(1)) <= minsSinceReboot:
                if xenrt.TEC().lookup("REMOTE_SCRIPTDIR")[0:5] == "/tmp/":
                    # Re-tailor because the scripts live in ramdisk
                    self.tailor()
                return
            self._softReboot(timeout)
            rebootTime = xenrt.util.timenow()
            xenrt.sleep(180)
        raise xenrt.XRTFailure("Host !%s has not rebooted" % self.getName())

    def poweron(self, timeout=600):
        """Power on the host and verify it boots"""
        self.machine.powerctl.on()
        xenrt.sleep(180)
        self.waitForSSH(timeout, desc="Host boot on !" + self.getName())
        uptime = self.execdom0("uptime")
        r = re.search(r"up (\d+) min", uptime)
        if r and int(r.group(1)) <= 10:
            if xenrt.TEC().lookup("REMOTE_SCRIPTDIR")[0:5] == "/tmp/":
                # Re-tailor because the scripts live in ramdisk
                self.tailor()
        else:
            raise xenrt.XRTFailure("Host has not freshly booted")

    def poweroff(self):
        """Power off a host"""
        self.machine.powerctl.off()

    def installLinuxVendor(self,
                           distro,
                           kickstart=None,
                           arch="x86-32",
                           method="HTTP",
                           extrapackages=None,
                           options={}):
        if re.search("sles|suse|sled", distro):
            self.installLinuxVendorSLES(distro,
                                        kickstart=kickstart,
                                        arch=arch,
                                        method=method,
                                        extrapackages=extrapackages,
                                        options=options)
        elif re.search("debian|ubuntu", distro):
            self.installLinuxVendorDebian(distro,
                                          arch,
                                          method,
                                          extrapackages=extrapackages,
                                          options=options)
        else:
            self.installLinuxVendorRHEL(distro,
                                        kickstart=kickstart,
                                        arch=arch,
                                        method=method,
                                        extrapackages=extrapackages,
                                        options=options)

    def installLinuxVendorRHEL(self,
                               distro,
                               kickstart=None,
                               arch="x86-32",
                               method="HTTP",
                               extrapackages=None,
                               options={}):
        self.arch = arch
        self.distro = distro

        repository = xenrt.getLinuxRepo(distro, arch, method)

        if (re.search(r"rhel7", distro) or \
                re.search(r"centos7", distro) or \
                re.search(r"oel7", distro)):
            legacySATA = False
        else:
            legacySATA = True
        mainDisk=self.getInstallDisk(ccissIfAvailable=False, legacySATA=legacySATA)

        if re.search(r"oel5", distro) or re.search (r"rhel5", distro) or re.search(r"centos5", distro) or \
                re.search(r"oel4", distro) or re.search (r"rhel4", distro) or re.search(r"centos4", distro):
            ethDevice = self.getDefaultInterface()
        else:
            ethDevice = self.getNICMACAddress(0)

        bootDiskSize = self.lookup("BOOTDISKSIZE",250)
        bootDiskFS = self.lookup("BOOTDISKFS","ext4")
        ethdev = self.getDefaultInterface()
        ethmac = xenrt.normaliseMAC(self.getNICMACAddress(0)).upper()
        nfsdir = xenrt.NFSDirectory()

        ksf=RHELKickStartFile(distro,
                             mainDisk,
                             nfsdir.getMountURL(""),
                             bootDiskFS=bootDiskFS,
                             bootDiskSize=bootDiskSize,
                             password=self.password,
                             vcpus=self.vcpus,
                             memory=self.memory,
                             ethdev=ethdev,
                             ethmac=ethmac,
                             options=options,
                             installOn=xenrt.HypervisorType.native,
                             method=method,
                             repository=repository,
                             ethDevice=ethDevice,
                             extraPackages=extrapackages,
                             ossVG=False,
                            )
        ks=ksf.generate()

        filename = "%s/kickstart.cfg" % (xenrt.TEC().getLogdir())
        f = file(filename, "w")
        f.write(ks)
        f.close()
        nfsdir.copyIn(filename)
        h, p = nfsdir.getHostAndPath("kickstart.cfg")

        if method != "HTTP":
            raise xenrt.XRTError("%s PXE install not supported" % (method))

        # Pull boot files from HTTP repository
        fk = xenrt.TEC().tempFile()
        fr = xenrt.TEC().tempFile()
        xenrt.getHTTP("%s/isolinux/vmlinuz" % (repository),fk)
        xenrt.getHTTP("%s/isolinux/initrd.img" % (repository),fr)

        # Construct a PXE target
        pxe = xenrt.PXEBoot()
        serport = self.lookup("SERIAL_CONSOLE_PORT", "0")
        serbaud = self.lookup("SERIAL_CONSOLE_BAUD", "115200")
        pxe.setSerial(serport, serbaud)
        chain = self.lookup("PXE_CHAIN_LOCAL_BOOT", None)
        if chain:
            pxe.addEntry("local", boot="chainlocal", options=chain)
        else:
            pxe.addEntry("local", boot="local")
        pxe.copyIn(fk, target="vmlinuz")
        pxe.copyIn(fr, target="initrd.img")
        pxecfg = pxe.addEntry("install", default=1, boot="linux")
        pxecfg.linuxSetKernel("vmlinuz")
        pxecfg.linuxArgsKernelAdd("ks=nfs:%s:%s" % (h, p))
        pxecfg.linuxArgsKernelAdd("ksdevice=%s" % (ethDevice))
        pxecfg.linuxArgsKernelAdd("nousb")
        pxecfg.linuxArgsKernelAdd("console=tty0")
        pxecfg.linuxArgsKernelAdd("console=ttyS%s,%sn8" %
                                  (serport, serbaud))
        pxecfg.linuxArgsKernelAdd("initrd=%s" %
                                  (pxe.makeBootPath("initrd.img")))
        if distro.startswith("oel7") or distro.startswith("centos7") or distro.startswith("rhel7"):
            pxecfg.linuxArgsKernelAdd("inst.repo=%s" % repository)
            pxecfg.linuxArgsKernelAdd("biosdevname=0")
            pxecfg.linuxArgsKernelAdd("net.ifnames=0")
            pxecfg.linuxArgsKernelAdd("console=tty0")
            pxecfg.linuxArgsKernelAdd("console=hvc0")
        else:
            pxecfg.linuxArgsKernelAdd("root=/dev/ram0")
            if re.search(r"(rhel|oel|centos)[dw]?6", distro):
                pxecfg.linuxArgsKernelAdd("biosdevname=0")
        pxefile = pxe.writeOut(self.machine)
        pfname = os.path.basename(pxefile)
        xenrt.TEC().copyToLogDir(pxefile,target="%s.pxe.txt" % (pfname))

        # Reboot to start the install
        self.machine.powerctl.cycle()

        # Monitor for installation complete
        xenrt.waitForFile("%s/.xenrtsuccess" % (nfsdir.path()),
                          3600,
                          desc="Vendor install")
        pxe.setDefault("local")
        pxe.writeOut(self.machine)

        # Wait a bit out of politeness to the installer, then perform a
        # reboot
        xenrt.sleep(60)
        self.machine.powerctl.cycle()
        self.waitForSSH(1800, desc="Post installation reboot")

        if xenrt.TEC().lookup("WORKAROUND_NATIVEBNX2", False, boolean=True):
            self.execdom0("ethtool -K %s rx off" % (ethDevice))
            self.execdom0("ethtool -K %s tx off" % (ethDevice))
            self.execdom0("ethtool -K %s sg off" % (ethDevice))
            self.execdom0("ethtool -K %s tso off" % (ethDevice))

        if not self.updateYumConfig(distro, arch):
            xenrt.TEC().warning('Failed to specify XenRT yum repo for %s, %s' % (distro, arch))

        # Optionally install some RPMs
        rpms = xenrt.TEC().lookupLeaves("RHEL_RPM_UPDATES")
        if len(rpms) == 1:
            rpms = string.split(rpms[0], ",")
        remotenames = []
        for rpm in [x for x in rpms if x != "None"]:
            rpmfile = xenrt.TEC().getFile(rpm)
            remotefn = "/tmp/%s" % os.path.basename(rpm)
            sftp = self.sftpClient()
            try:
                sftp.copyTo(rpmfile, remotefn)
            finally:
                sftp.close()
            remotenames.append(remotefn)
        if len(remotenames) > 0:
            force = xenrt.TEC().lookup("FORCE_RHEL_RPM_UPDATES", False,boolean=True)
            if force:
                self.execdom0("rpm --upgrade -v --force --nodeps %s" % (string.join(remotenames)))
            else:
                self.execdom0("rpm --upgrade -v %s" % (string.join(remotenames)))
            self.reboot()

        self.tailor()

    def installLinuxVendorSLES(self,
                               distro,
                               kickstart=None,
                               arch="x86-32",
                               method="HTTP",
                               extrapackages=None,
                               options={}):
        """Network install of HVM SLES into this host."""
        self.arch = arch
        self.distro = distro
        repository = xenrt.getLinuxRepo(distro, arch, method)
        nfsdir = xenrt.NFSDirectory()
        mainDisk = self.getInstallDisk(ccissIfAvailable=False, legacySATA=True)
        ethDevice = self.getDefaultInterface()
        bootDiskSize = self.lookup("BOOTDISKSIZE", "100")
        ay=SLESAutoyastFile( distro,
                             nfsdir.getMountURL(""),
                             mainDisk,
                             installOn="native",
                             method=method,
                             ethDevice=ethDevice,
                             password=self.password,
                             extraPackages=extrapackages,
                             bootDiskSize=bootDiskSize,
                            )

        filename = "%s/autoyast.xml" % (xenrt.TEC().getLogdir())
        f = file(filename, "w")
        f.write(ay)
        f.close()

        # Make autoyast file available over HTTP.
        webdir = xenrt.WebDirectory()
        webdir.copyIn(filename)
        url = webdir.getURL(os.path.basename(filename))

        # Pull boot files from HTTP repository.
        fk = xenrt.TEC().tempFile()
        fr = xenrt.TEC().tempFile()
        if re.search(r"sles1[01]", distro):
            xenrt.getHTTP("%s/boot/i386/loader/linux" % (repository), fk)
            xenrt.getHTTP("%s/boot/i386/loader/initrd" % (repository), fr)
        else:
            xenrt.getHTTP("%s/boot/loader/linux" % (repository), fk)
            xenrt.getHTTP("%s/boot/loader/initrd" % (repository), fr)

        if method != "HTTP":
            raise xenrt.XRTError("%s PXE install not supported" % (method))

        # Construct a PXE target.
        pxe = xenrt.PXEBoot()
        serport = self.lookup("SERIAL_CONSOLE_PORT", "0")
        serbaud = self.lookup("SERIAL_CONSOLE_BAUD", "115200")
        pxe.setSerial(serport, serbaud)
        chain = self.lookup("PXE_CHAIN_LOCAL_BOOT", None)
        if chain:
            pxe.addEntry("local", boot="chainlocal", options=chain)
        else:
            pxe.addEntry("local", boot="local")
        pxe.copyIn(fk, target="vmlinuz")
        pxe.copyIn(fr, target="initrd.img")
        pxecfg = pxe.addEntry("install", default=1, boot="linux")
        pxecfg.linuxSetKernel("vmlinuz")
        pxecfg.linuxArgsKernelAdd("initrd=%s" %
                                  (pxe.makeBootPath("initrd.img")))
        pxecfg.linuxArgsKernelAdd("ramdisk_size=65536")
        pxecfg.linuxArgsKernelAdd("autoyast=%s" % (url))
        #pxecfg.linuxArgsKernelAdd("showopts")
        pxecfg.linuxArgsKernelAdd("netdevice=%s" % (ethDevice))
        pxecfg.linuxArgsKernelAdd("install=%s" % (repository))
        #pxecfg.linuxArgsKernelAdd("console=tty0")
        pxecfg.linuxArgsKernelAdd("console=ttyS%s,%sn8" % (serport, serbaud))
        pxefile = pxe.writeOut(self.machine)
        pfname = os.path.basename(pxefile)
        xenrt.TEC().copyToLogDir(pxefile,target="%s.pxe.txt" % (pfname))

        # Reboot to start the install
        self.machine.powerctl.cycle()

        # Next time we boot normally
        xenrt.sleep(300)
        xenrt.TEC().logverbose("Switching PXE config to local boot")
        pxe.setDefault("local")
        pxe.writeOut(self.machine)

        # Wait for notification that the install has finished
        # (This happens after the installer has booted into
        # the newly installed guest)
        xenrt.waitForFile("%s/.xenrtsuccess" % (nfsdir.path()),
                          3600,
                          desc="Vendor install and boot")

        self.waitForSSH(1800, desc="Post installation reboot")
        xenrt.sleep(30)
        self.tailor()

    def installLinuxVendorDebian(self,
                      distro,
                      arch,
                      method,
                      extrapackages=None,
                      options={}):
        """Network install of Debian into this host."""

        self.arch = arch
        self.distro = distro

        repository = xenrt.getLinuxRepo(distro, arch, method)

        mainDisk=self.getInstallDisk(ccissIfAvailable=False, legacySATA=True)

        ethdev = self.getDefaultInterface()
        ethmac = xenrt.normaliseMAC(self.getNICMACAddress(0))

        preseedfile = "preseed-%s.cfg" % (self.getName())
        filename = "%s/%s" % (xenrt.TEC().getLogdir(), preseedfile)

        tmpdir = xenrt.TempDirectory()
        webdir = xenrt.WebDirectory()

        sigkey = os.path.basename(tmpdir.path())

        # Make post install script
        serport = self.lookup("SERIAL_CONSOLE_PORT", "0")
        serbaud = self.lookup("SERIAL_CONSOLE_BAUD", "115200")
        extra = ""
        if distro.startswith("debian80") or distro.startswith("debiantesting"):
            extra += """sed -i 's/PermitRootLogin without-password/PermitRootLogin yes/g' /etc/ssh/sshd_config
/etc/init.d/ssh restart
"""

        piscript = """#!/bin/bash
# Ensure we get dom0 serial console (there should be a way to do this through preseed but I can't find an obvious way)
sed -i 's/GRUB_CMDLINE_LINUX=""/GRUB_CMDLINE_LINUX="console=tty0 console=ttyS%s,%sn8"/' /etc/default/grub
/usr/sbin/update-grub

%s

# Signal completion
wget -q -O - %s/share/control/signal?key=%s
exit 0
""" % (serport, serbaud, extra, xenrt.TEC().lookup("LOCALURL"),  sigkey)
        pifile = "post-install-%s.sh" % (self.getName())
        pifilename = "%s/%s" % (xenrt.TEC().getLogdir(), pifile)
        f = file(pifilename, "w")
        f.write(piscript)
        f.close()
        webdir.copyIn(pifilename)
        piurl = webdir.getURL(pifile)

        disk = self.lookup("OPTION_CARBON_DISKS", "sda")
        disk = "/dev/%s" % disk

        # Generate a config file
        ps=DebianPreseedFile(distro,
                             repository,
                             filename,
                             installOn=xenrt.HypervisorType.native,
                             method=method,
                             password=self.password,
                             ethDevice=ethdev,
                             extraPackages=extrapackages,
                             ossVG=False,
                             arch=arch,
                             postscript=piurl,
                             poweroff=False,
                             disk=disk)
        ps.generate()

        webdir.copyIn(filename)
        url = webdir.getURL(os.path.basename(filename))

        if method != "HTTP":
            raise xenrt.XRTError("%s PXE install not supported" %
                                 (method))

        arch = "amd64" if "64" in self.arch else "i386"
        if distro == "debian50":
            release = "lenny"
        elif distro == "debian60":
            release = "squeeze"
        elif distro == "debian70":
            release = "wheezy"
        elif distro == "debian80":
            release = "jessie"
        elif distro == "debiantesting":
            release = "jessie"
            self.special['debiantesting_upgrade'] = True
        _url = repository + "/dists/%s/" % (release.lower(), )
        boot_dir = "main/installer-%s/current/images/netboot/debian-installer/%s/" % (arch, arch)

        # Pull boot files from HTTP repository
        fk = xenrt.TEC().tempFile()
        fr = xenrt.TEC().tempFile()
        initrd = fr
        xenrt.getHTTP(_url + boot_dir + "linux", fk)
        xenrt.getHTTP(_url + boot_dir + "initrd.gz", fr)

        # Handle any firmware requirements
        firmware = xenrt.TEC().lookup(["DEBIAN_FIRMWARE", self.distro], None)
        if firmware:
            initrd = xenrt.TEC().tempFile()
            fw = xenrt.TEC().tempFile()
            xenrt.getHTTP(firmware, fw)
            xenrt.command("cat %s %s > %s" % (fr, fw, initrd))

        # Construct a PXE target
        pxe = xenrt.PXEBoot()
        pxe.setSerial(serport, serbaud)
        chain = self.lookup("PXE_CHAIN_LOCAL_BOOT", None)
        if chain:
            pxe.addEntry("local", boot="chainlocal", options=chain)
        else:
            pxe.addEntry("local", boot="local")
        pxe.copyIn(fk, target="linux")
        pxe.copyIn(initrd, target="initrd.gz")
        pxecfg = pxe.addEntry("install", default=1, boot="linux")
        pxecfg.linuxSetKernel("linux")
        pxecfg.linuxArgsKernelAdd("vga=normal")
        pxecfg.linuxArgsKernelAdd("auto=true priority=critical")
        pxecfg.linuxArgsKernelAdd("console=tty0")
        pxecfg.linuxArgsKernelAdd("console=ttyS%s,%sn8" %
                                  (serport, serbaud))
        pxecfg.linuxArgsKernelAdd("interface=%s" % (ethdev))
        pxecfg.linuxArgsKernelAdd("url=%s" % (webdir.getURL(preseedfile)))
        pxecfg.linuxArgsKernelAdd("initrd=%s" %
                                  (pxe.makeBootPath("initrd.gz")))
        pxefile = pxe.writeOut(self.machine)
        pfname = os.path.basename(pxefile)
        xenrt.TEC().copyToLogDir(pxefile,target="%s.pxe.txt" % (pfname))

        # Start the install
        self.machine.powerctl.cycle()

        installTimeout = 1800 + int(self.lookup("ALLOW_EXTRA_HOST_BOOT_SECONDS", "0"))
        xenrt.waitForFile("%s/.xenrtsuccess" % (tmpdir.path()),
                          installTimeout,
                          desc="Vendor install")
        pxe.setDefault("local")
        pxe.writeOut(self.machine)

        self.waitForSSH(1800, desc="Post installation reboot")

        self.tailor()


    def _lookupVncDisplay(self, domid):
        """Returns the VNC display number for a specified domain."""
        vp = self.xenstoreRead("/local/domain/%u/console/vnc-port" % (domid))
        if vp:
            return int(vp) - 5900
        raise xenrt.XRTError("Could not find VNC display for domain",
                             "Domain %u on %s" % (domid, self.getName()))

    def sendVncKeys(self, domid, keycodes):
        """Send the list of X11 keycodes to the VNC interface for the
        specified domain."""
        sendvnc = "%s/utils/sendvnc.py" % \
                  (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"))
        if self.execdom0("test -e %s" % (sendvnc), retval="code") != 0:
            raise xenrt.XRTError("sendvnc tool not found on host")
        if type(domid) == type(0):
            display = ":%u" % (self._lookupVncDisplay(domid))
        else:
            # Hack to allow a display to be passed instead of domid
            display = domid
        self.execdom0("%s %s %s" % (sendvnc,
                                    display,
                                    string.join(map(str, keycodes))))

    def getVncSnapshot(self,domid,filename):
        """Get a VNC snapshot of domain domid and write it to filename"""
        vncsnapshot = None
        if self.execdom0("test -e /usr/lib64/xen/bin/vncsnapshot",
                              retval="code") == 0:
            vncsnapshot = "/usr/lib64/xen/bin/vncsnapshot"
        if self.execdom0("test -e /usr/lib/xen/bin/vncsnapshot",
                              retval="code") == 0:
            vncsnapshot = "/usr/lib/xen/bin/vncsnapshot"
        if self.execdom0("test -e /usr/bin/vncsnapshot",
                              retval="code") == 0:
            vncsnapshot = "/usr/bin/vncsnapshot"
        if vncsnapshot:
            try:
                # Figure out which display to grab
                display = ":%u" % (self._lookupVncDisplay(domid))

                # Send a shift key to wake up any screensaver
                self.sendVncKeys(display, [0xffe1])
                xenrt.sleep(1)

                # Send WindowsKey+R to show desktop on Win8+
                self.sendVncKeys(display, ["0x72/0xffeb"])
                xenrt.sleep(8)

                # Perform the snapshot
                workdir = string.strip(\
                    self.execdom0("mktemp -d /tmp/XXXXXX"))
                self.execdom0("%s -compresslevel 9 -quality 25 %s "
                              "%s/vnc.jpg" % (vncsnapshot,display,workdir))
                # Grab the file
                sftp = self.sftpClient()
                sftp.copyFrom("%s/vnc.jpg" % (workdir), filename)
                sftp.close()
                self.execdom0("rm -fr %s" % (workdir))

                return True
            except:
                # Probably no display for the domid
                return False
        return False

    def writeToConsole(self, domid, str, tty=None, retlines=0, cuthdlines=0):
        """Write str into the domain's main console stdin"""
        """and wait for retlines in stdout"""
        if not tty:
            tty = self.xenstoreRead("/local/domain/%u/console/port" % (domid))
        if not tty:
            raise xenrt.XRTError("Could not find tty port for domain",
                                 "Domain %u on %s" % (domid, self.getName()))
        #TODO: escape the echo 's in str properly
        #TODO: return stdout synchronously instead of relying on a different program (head)
        if cuthdlines>0:
            sed="| sed '%ud'" % cuthdlines
        else:
            sed=""
        out = self.execdom0("echo -e -n '%s' > %s && head -n %u %s %s" % (str,tty,(retlines+cuthdlines),tty,sed))
        return out

    def bootRamdiskLinux(self):
        """Boot a Linux ramdisk image from the network"""

        
        # Construct a PXE target
        pxe1 = xenrt.PXEBoot()
        serport = self.lookup("SERIAL_CONSOLE_PORT", "0")
        serbaud = self.lookup("SERIAL_CONSOLE_BAUD", "115200")
        pxe1.setSerial(serport, serbaud)
        pxe2 = xenrt.PXEBoot()
        serport = self.lookup("SERIAL_CONSOLE_PORT", "0")
        serbaud = self.lookup("SERIAL_CONSOLE_BAUD", "115200")
        pxe2.setSerial(serport, serbaud)
    
        pxe1.addEntry("ipxe", boot="ipxe")
        pxe1.setDefault("ipxe")
        pxe1.writeOut(self.machine)

        webdir = xenrt.WebDirectory()
        with open(os.path.join(webdir.path(), "cloudconfig.yaml"), "w") as f:
            f.write("""#cloud-config

users:
  - name: root
    passwd: $1$IpG/0K10$FRR072xrFnouDDxWEG/Br1
write_files:
  - path: /xenrt
    permissions: 0644
    owner: root
    content: |
        xenrt
""")

        coreos = pxe2.addEntry("coreos", boot="linux")
        basepath = xenrt.getLinuxRepo("coreos-stable", "x86-64", "HTTP")
        coreos.linuxSetKernel("%s/amd64-usr/current/coreos_production_pxe.vmlinuz" % basepath, abspath=True)
        coreos.linuxArgsKernelAdd("initrd=%s/amd64-usr/current/coreos_production_pxe_image.cpio.gz cloud-config-url=%s" % (basepath, webdir.getURL("cloudconfig.yaml")))
    
        pxe2.setDefault("coreos")
        filename = pxe2.writeOut(self.machine, suffix="_ipxe")
        ipxescript = """set 209:string pxelinux.cfg/%s
chain tftp://${next-server}/%s
""" % (os.path.basename(filename), xenrt.TEC().lookup("PXELINUX_PATH", "pxelinux.0"))
        pxe2.writeIPXEConfig(self.machine, ipxescript)
        tries = 0
        while True:
            try:
                # Try to reboot the host by SSH to whatever is there. This may
                # fail if the previous installation is broken, not ours,
                # different password etc...
                xenrt.TEC().progress("Rebooting into ramdisk image (%u)" % \
                                     (tries))
                self.machine.powerctl.cycle()

                # Wait a bit so our post-boot check doesn't pick up the
                # existing installation
                xenrt.sleep(120)

                # Wait for the host to come up in the ramdisk image
                try:
                    self.waitForSSH(600 + int(self.lookup("ALLOW_EXTRA_HOST_BOOT_SECONDS", "0")))
                except:
                    # Try another hard reboot
                    xenrt.TEC().progress("Second reboot attempt")
                    self.machine.powerctl.cycle()
                    self.waitForSSH(600 + int(self.lookup("ALLOW_EXTRA_HOST_BOOT_SECONDS", "0")),
                                    "Second reboot attempt into ramdisk image")

                # Make sure we really have booted the ramdisk
                xenrt.TEC().progress("Checking we're in the ramdisk image")
                if self.execdom0("ls /xenrt", retval="code") \
                       != 0:
                    raise xenrt.XRTError("Did not reboot into ramdisk image")
                break
            except Exception, e:
                tries = tries + 1
                if tries == 3:
                    raise

    def createGenericLinuxGuest(self):
        raise xenrt.XRTError("Unimplemented")

    def createRamdiskLinuxGuest(self,
                                disks=[],
                                start=True,
                                memory=2048,
                                ramdisk_size=550000):
        """Installs a ramdisk PXE-booting Linux VM using vm-create."""
        g = self.guestFactory()(\
                xenrt.randomGuestName(),
                None,
                self,
                password=xenrt.TEC().lookup("ROOT_PASSWORD"))
        g.createHVMGuest(disks, pxe=True)
        g.memset(memory)
        mac = xenrt.randomMAC()
        g.createVIF(bridge=self.getPrimaryBridge(),mac=mac)
        pxe = xenrt.PXEBoot(abspath=True,removeOnExit=True)

        pxecfg = pxe.addEntry("cleanrd", default=1, boot="linux")
        barch = self.getBasicArch()
        pxecfg.linuxSetKernel("clean/vmlinuz-xenrt-%s" % (barch))
        pxecfg.linuxArgsKernelAdd("root=/dev/ram0")
        pxecfg.linuxArgsKernelAdd("console=tty0")
        pxecfg.linuxArgsKernelAdd("maxcpus=1")
        pxecfg.linuxArgsKernelAdd("console=ttyS0,115200n8")
        pxecfg.linuxArgsKernelAdd("ramdisk_size=%d" % (ramdisk_size))
        pxecfg.linuxArgsKernelAdd("ro")
        pxecfg.linuxArgsKernelAdd("initrd=clean/cleanroot-%s.img.gz" % (barch))

        pxefile = pxe.writeOut(None,forcemac=mac)

        g.password="xensource"

        if start:
            g.start()
            if not g.mainip:
                raise xenrt.XRTError("Could not find ramdisk guest IP address")

            g.waitForSSH(600)

        return g

    def installRamdiskLinuxGuest(self,
                                disks=[],
                                start=True,
                                memory=2048,
                                ramdisk_size=550000,
                                biosHostUUID=None):
        """Installs a ramdisk PXE-booting Linux VM using vm-install."""
        g = self.guestFactory()(\
                xenrt.randomGuestName(),
                None,
                self,
                password="xensource") # password is burnt into initrd
        g.installHVMGuest(disks, pxe=True, biosHostUUID=biosHostUUID)
        g.memset(memory)
        mac = xenrt.randomMAC()
        g.createVIF(bridge=self.getPrimaryBridge(),mac=mac)

        pxe = xenrt.PXEBoot(abspath=True,removeOnExit=True)

        pxecfg = pxe.addEntry("cleanrd", default=1, boot="linux")
        barch = self.getBasicArch()
        pxecfg.linuxSetKernel("clean/vmlinuz-xenrt-%s" % (barch))
        pxecfg.linuxArgsKernelAdd("root=/dev/ram0")
        pxecfg.linuxArgsKernelAdd("console=tty0")
        pxecfg.linuxArgsKernelAdd("maxcpus=1")
        pxecfg.linuxArgsKernelAdd("console=ttyS0,115200n8")
        pxecfg.linuxArgsKernelAdd("ramdisk_size=%d" % (ramdisk_size))
        pxecfg.linuxArgsKernelAdd("ro")
        pxecfg.linuxArgsKernelAdd("initrd=clean/cleanroot-%s.img.gz" % (barch))

        pxefile = pxe.writeOut(None,forcemac=mac)

        if start:
            g.start()
            if not g.mainip:
                raise xenrt.XRTError("Could not find ramdisk guest IP address")

            g.waitForSSH(600)

        return g


    def installHVMLinux(self,
                          disks=[],
                          start=False,
                          memory=2048,
                          biosHostUUID=None,
                          bridge=None,
                          create_vif_fn=None,
                          use_64_bit=False,
                          guest_name=None,
                          ramdisk_size=None):
        """Installs a live PXE-booting Linux (2.6.35) VM using vm-install."""
        if guest_name is None:
            guest_name = xenrt.randomGuestName()

        g = self.guestFactory()(\
            guest_name,
            None,
            self,
            password="xensource") # password is burnt into initrd
        g.installHVMGuest(disks, pxe=True, biosHostUUID=biosHostUUID)
        g.memset(memory)
        mac = xenrt.randomMAC()
        if bridge is None:
            bridge = self.getPrimaryBridge()
        if create_vif_fn is None:
            g.createVIF(bridge=bridge, mac=mac)
        else:
            create_vif_fn(g, primaryMAC=mac)

        pxe = xenrt.PXEBoot(removeOnExit=True)

        if use_64_bit:
            kernel = 'rescue64'
        else:
            kernel = 'rescuecd'

        pxe.copyIn("%s/sysrescue/%s" % (xenrt.TEC().lookup("TEST_TARBALL_ROOT"), kernel))
        pxe.copyIn("%s/sysrescue/%s" % (xenrt.TEC().lookup("TEST_TARBALL_ROOT"), 'initram.igz'))

        pxecfg = pxe.addEntry("sysrescue", default=1, boot="linux")
        barch = self.getBasicArch()
        pxecfg.linuxSetKernel(kernel)
        pxecfg.linuxArgsKernelAdd("dodhcp rootpass=%s setkmap=uk netboot=%s/sysrescue/sysrcd.dat" %
                                  (g.password, xenrt.TEC().lookup("TEST_TARBALL_BASE")))
        pxecfg.linuxArgsKernelAdd("initrd=%s" % pxe.makeBootPath("initram.igz"))
        if ramdisk_size:
            pxecfg.linuxArgsKernelAdd("ramdisk_size=%d" % (ramdisk_size))

        pxefile = pxe.writeOut(None,forcemac=mac)

        if start:
            g.start()
            if not g.mainip:
                raise xenrt.XRTError("Could not find linux HVM guest IP address")

            g.waitForSSH(600)

        return g


    def getBondInfo(self,bond):
        """Gets information about a network bond"""
        if self.execdom0("test -e /proc/net/bonding/%s" % (bond),
                         retval="code") != 0:
            raise xenrt.XRTFailure("No bond config found for %s" % (bond))
        data = self.execdom0("cat /proc/net/bonding/%s" % (bond))
        slaves = {}
        info = {}
        lines = data.split("\n")
        intf = None
        for line in lines:
            if line.startswith("Slave Interface:"):
                intf = line.split(":")[1].strip()
                slaves[intf] = {}
            elif intf:
                if line.startswith("MII Status:"):
                    slaves[intf]['status'] = line.split(":",1)[1].strip()
                elif line.startswith("Link Failure Count:"):
                    pass # unused
                    #slaves[intf]['failcount'] = line.split(":",1)[1].strip()
                elif line.startswith("Permanent HW addr:"):
                    slaves[intf]['hwaddr'] = line.split(":",1)[1].strip()
            else:
                if line.startswith("Bonding Mode:"):
                    info['mode'] = line.split(":",1)[1].strip()
                elif line.startswith("Primary Slave:"):
                    pass # unused
                    #info['primary_slave'] = line.split(":",1)[1].strip()
                elif line.startswith("Currently Active Slave:"):
                    info['active_slave'] = line.split(":",1)[1].strip()
                elif line.startswith("MII Status:"):
                    pass # unused
                    # info['status'] = line.split(":",1)[1].strip()
                elif line.startswith("Source load balancing info:"):
                    info['slb'] = {}
                elif re.match(" \[\d+\] = \S+", line):
                    m = re.match(" \[(\d+)\] = (\S+)", line)
                    info['slb'][int(m.group(1))] = m.group(2)

        info['slaves'] = slaves.keys()

        return (info,slaves)

    def binreplace(self,
                   smstring,
                   value,
                   file="/usr/lib/xen/boot/hvmloader"):
        """Run the binreplace tool in dom0 to update hvmloader."""
        self.mylock.acquire()
        try:
            self.execdom0("%s/binreplace %s %s write \"%s\"" %
                          (self.lookup("REMOTE_SCRIPTDIR"),
                           file,
                           smstring,
                           value))
        finally:
            self.mylock.release()

    def getGateway(self,nw=None):

        gateway = None

        if nw == "NPRI" or nw is None:
            gateway = self.lookup(["NETWORK_CONFIG",
                                         "DEFAULT",
                                         "GATEWAY"])
        elif nw == "NSEC":
            gateway = self.lookup(["NETWORK_CONFIG",
                                         "SECONDARY",
                                         "GATEWAY"])
        else:
            vlannames = self.lookup(["NETWORK_CONFIG", "VLANS"], None)
            if not vlannames:
                raise xenrt.XRTError("No VLANs defined for host %s" %
                                     (self.getName()))
            if not nw in vlannames.keys():
                xenrt.TEC().logverbose("Known VLANs %s" % (vlannames.keys()))
                raise xenrt.XRTError("VLAN %s not defined for host %s" %
                                     (nw, self.getName()))

            gateway = self.lookup(["NETWORK_CONFIG",
                                         "VLANS",
                                         nw,
                                         "GATEWAY"],
                                        None)

        return gateway

    def getIPv6NetworkParams(self, nw=None):
        """Returns a tuple of (router_prefix, dhcp_pool_begin, dhcp_pool_end).

        If nw is None, NPRI is assumed. Acceptable values of nw are NPRI, NSEC and
        VLAN names.
        """
        router_prefix = None
        dhcp6_begin = None
        dhcp6_end = None

        if nw == "NPRI" or nw is None:
            router_prefix = self.lookup(["NETWORK_CONFIG",
                                         "DEFAULT",
                                         "SUBNET6"])
            dhcp6_begin = self.lookup(["NETWORK_CONFIG",
                                       "DEFAULT",
                                       "POOLSTART6"])
            dhcp6_end = self.lookup(["NETWORK_CONFIG",
                                     "DEFAULT",
                                     "POOLEND6"])
        elif nw == "NSEC":
            router_prefix = self.lookup(["NETWORK_CONFIG",
                                         "SECONDARY",
                                         "SUBNET6"])
            dhcp6_begin = self.lookup(["NETWORK_CONFIG",
                                       "SECONDARY",
                                       "POOLSTART6"])
            dhcp6_end = self.lookup(["NETWORK_CONFIG",
                                     "SECONDARY",
                                     "POOLEND6"])
        else:
            vlannames = self.lookup(["NETWORK_CONFIG", "VLANS"], None)
            if not vlannames:
                raise xenrt.XRTError("No VLANs defined for host %s" %
                                     (self.getName()))
            if not nw in vlannames.keys():
                xenrt.TEC().logverbose("Known VLANs %s" % (vlannames.keys()))
                raise xenrt.XRTError("VLAN %s not defined for host %s" %
                                     (nw, self.getName()))

            router_prefix = self.lookup(["NETWORK_CONFIG",
                                         "VLANS",
                                         nw,
                                         "SUBNET6"],
                                        None)

            dhcp6_begin = self.lookup(["NETWORK_CONFIG",
                                       "VLANS",
                                       nw,
                                       "POOLSTART6"],
                                      None)

            dhcp6_end = self.lookup(["NETWORK_CONFIG",
                                     "VLANS",
                                     nw,
                                     "POOLEND6"],
                                    None)

        return (router_prefix, dhcp6_begin, dhcp6_end)


    def getVLAN(self, vlanname):
        """Return a tuple of (vlan, subnet, netmask), where vlan is an
        integer, for the VLAN defined by the symbolic name given."""
        vlannames = self.lookup(["NETWORK_CONFIG", "VLANS"], None)
        if not vlannames:
            raise xenrt.XRTError("No VLANs defined for host %s" %
                                 (self.getName()))
        if vlanname == "NSEC":
            vlanid = self.lookup(["NETWORK_CONFIG", "SECONDARY", "VLAN"], None)
            if not vlanid:
                raise xenrt.XRTError("Could not find ID for VLAN %s" % (vlanname))
            vlan = int(vlanid)
            subnet = self.lookup(["NETWORK_CONFIG",
                                  "SECONDARY",
                                  "SUBNET"],
                                  None)
            netmask = self.lookup(["NETWORK_CONFIG",
                                   "SECONDARY",
                                   "SUBNETMASK"],
                                   None)
        elif vlanname in vlannames.keys():
            vlanid = self.lookup(["NETWORK_CONFIG", "VLANS", vlanname, "ID"], None)
            if not vlanid:
                raise xenrt.XRTError("Could not find ID for VLAN %s" % (vlanname))
            vlan = int(vlanid)
            subnet = self.lookup(["NETWORK_CONFIG",
                                  "VLANS",
                                  vlanname,
                                  "SUBNET"],
                                  None)
            netmask = self.lookup(["NETWORK_CONFIG",
                                   "VLANS",
                                   vlanname,
                                   "SUBNETMASK"],
                                   None)
        else:
            vlanres = xenrt.GEC().registry.vlanGet(vlanname)
            if not vlanres:
                raise xenrt.XRTError("VLAN %s not found" % vlanname)
            vlan = vlanres.getID()
            subnet = None
            netmask = None

        return (vlan, subnet, netmask)

    def availableVLANs(self):
        """Return a list of available routed VLANs for the network(s) this host is connected to.
           The list is of tuples of (vlan, subnet, netmask) where vlan is an integer."""
        reply = []
        vlannames = self.lookup(["NETWORK_CONFIG", "VLANS"], None)
        if vlannames:
            # Remove:
            #   * Unrouted VLANs with a "VU" prefix.
            #   * Special VLANs for storage traffic (IPRI/ISEC).
            #   * RSPAN VLANs.
            #   * IPv6 VLANs
            valid = filter(lambda x:not re.match("ISEC|IPRI|RSPAN|VU|RA6|DH6|PRIV\d|PVS\d", x), vlannames)
            if valid:
                f = lambda x,y:self.lookup(["NETWORK_CONFIG", "VLANS", x, y])
                reply = map(lambda x:(int(f(x, "ID")), f(x, "SUBNET"), f(x, "SUBNETMASK")), valid)
        return reply

    def _controlNetPort(self, mac, action, startup=False):
        cmd = None
        netport = None
        mac = xenrt.normaliseMAC(mac)
        # Check the default interface
        mac0 = xenrt.normaliseMAC(self.lookup("MAC_ADDRESS", ""))
        if mac == mac0:
            # First check for a specific command
            cmd = self.lookup(action, None)
            if not cmd:
                # Look for a NETPORT config
                netport = self.lookup("NETPORT", None)
                if not netport:
                    raise xenrt.XRTError(\
                        "No %s or NETPORT specified for %s default interface"
                        % (action, self.getName()))
        else:
            # Check the secondary interfaces
            i = 1
            while True:
                macn = xenrt.normaliseMAC(self.lookup(["NICS",
                                                       "NIC%u" % (i),
                                                       "MAC_ADDRESS"], ""))
                if macn == "":
                    break
                if macn == mac:
                    cmd = self.lookup(["NICS", "NIC%u" % (i), action], None)
                    if not cmd:
                        # Look for a NETPORT config
                        netport = self.lookup(\
                            ["NICS", "NIC%u" % (i), "NETPORT"], None)
                        if not netport:
                            raise xenrt.XRTError(\
                                "No %s or NETPORT specified for %s NIC %s" %
                                (action, self.getName(), mac))
                    break
                i = i + 1
            if not cmd and not netport:
                raise xenrt.XRTError("Could not find %s interface with %s" %
                                     (self.getName(), mac))

        if netport:
            ll = netport.split("/")
            if len(ll) != 2:
                raise xenrt.XRTError("NETPORT syntax error: %s (%s)" %
                                     (netport, self.getName()) )
            xenrtSwitchName, portNumber = ll
            unitName = re.sub('^XenRT','', xenrtSwitchName)
            switchName, unit = unitName.rsplit('-', 1)
            if not unit.isdigit():
                raise xenrt.XRTError("Unexpected format in NETSWITCHES. "
                                    "Should be switchname-digit, found: '%s'"
                                    % (switchName))

            if startup and xenrt.TEC().lookup(["NETSWITCHES", switchName, 'STARTUP_ENABLE'], False, boolean=True):
                return

            addr = xenrt.TEC().lookup(["NETSWITCHES", switchName, 'ADDRESS'])
            if not addr:
                raise xenrt.XRTError("No ADDRESS for NETSWITCH %s" % (switchName))

            comm = xenrt.TEC().lookup(["NETSWITCHES", switchName, 'SNMPPRIVATE'])
            if not comm:
                raise xenrt.XRTError("No SNMPPRIVATE for NETSWITCH %s" %(switchName))

            portOffset = int(xenrt.TEC().lookup(["NETSWITCHES", switchName, "UNIT%s" % unit, "PORTOFFSET"], "0"))

            portInterval = int(xenrt.TEC().lookup(["NETSWITCHES", switchName, "PORTINTERVAL"], "1"))
            oidBase = xenrt.TEC().lookup(["NETSWITCHES", unit, "OID_BASE"],
                                    ".1.3.6.1.2.1.2.2.1.7")

            if action == "CMD_PORT_ENABLE":
                icmd = "1"
            elif action == "CMD_PORT_DISABLE":
                icmd = "2"
            else:
                raise xenrt.XRTError("Unknown port action: %s" % (action))
            cmd = "snmpset -c %s -v1 -t 10 -r 10 %s %s.%u i %s" % \
                  (comm, addr, oidBase, int(portNumber)*portInterval + portOffset, icmd)

        # Run the command
        if cmd:
            xenrt.TEC().logverbose("Controlling switch port for %s %s (%s)" %
                                   (self.getName(), mac, action))
            i = 0
            while True:
                i += 1
                try:
                    xenrt.command(cmd)
                    break
                except:
                    if i > 3:
                        raise
                    xenrt.sleep(30)

    def enableAllNetPorts(self):
        """Enable all switch ports connected to the host NICs"""
        nics = [0]
        nics.extend(self.listSecondaryNICs())
        for n in nics:
            mac = self.getNICMACAddress(n)
            try: self.enableNetPort(mac, startup=True)
            except: pass

    def enableNetPort(self, mac, startup=False):
        """Enable the switch port to which the NIC with the specified MAC
        is connected."""
        self._controlNetPort(mac, "CMD_PORT_ENABLE", startup=startup)

    def disableNetPort(self, mac):
        """Disable the switch port to which the NIC with the specified MAC
        is connected."""
        self._controlNetPort(mac, "CMD_PORT_DISABLE")
        if not mac in self.portsToEnableAtCleanup:
            self.portsToEnableAtCleanup.append(mac)
        self._registerCallback()

    def disableAllFCPorts(self):
        """Disable all the FC ports to which the HBAs are connected"""
        fckeys = self.lookup(["FC"], {}).keys()
        for k in fckeys:
            m = re.match("CMD_HBA(\d+)_DISABLE", k)
            if m:
                self.disableFCPort(int(m.group(1)))

    def enableAllFCPorts(self):
        """Enable all the FC ports to which the HBAs are connected"""
        fckeys = self.lookup(["FC"], {}).keys()
        for k in fckeys:
            m = re.match("CMD_HBA(\d+)_ENABLE", k)
            if m:
                self.enableFCPort(int(m.group(1)))

    def getNumOfFCPorts(self):
        """Obtain the number of FC ports to which the HBAs are connected"""
        portCount = 0
        fckeys = self.lookup(["FC"], {}).keys()
        for k in fckeys:
            m = re.match("CMD_HBA(\d+)_ENABLE", k)
            if m:
                portCount = portCount + 1
        return portCount

    def enableFCPort(self, hba):
        """Enable the FC port to which the specified HBA is connected."""
        cmd = self.lookup(["FC", "CMD_HBA%u_ENABLE" % (hba)], None)
        if not cmd:
            raise xenrt.XRTError("No CMD_HBA%u_ENABLE defined for %s" % (hba, self.getName()))
        xenrt.TEC().logverbose("Enabling FC port for HBA %u on %s" % (hba, self.getName()))
        tries = 0
        while True:
            try:
                xenrt.command(cmd)
                break
            except:
                tries += 1
                if tries > 3:
                    raise
                xenrt.sleep(60)

    def disableFCPort(self, hba):
        """Disable the FC port to which the specified HBA is connected."""
        cmd = self.lookup(["FC", "CMD_HBA%u_DISABLE" % (hba)], None)
        if not cmd:
            raise xenrt.XRTError("No CMD_HBA%u_DISABLE defined for %s" % (hba, self.getName()))
        xenrt.TEC().logverbose("Disabling FC port for HBA %u on %s" % (hba, self.getName()))
        tries = 0
        while True:
            try:
                xenrt.command(cmd)
                break
            except:
                tries += 1
                if tries > 3:
                    raise
                xenrt.sleep(60)
        if not hba in self.hbasToEnableAtCleanup:
            self.hbasToEnableAtCleanup.append(hba)
        self._registerCallback()

    # Boot failure patterns are tuples of regexps, the number of lines
    # of log history to be considered, a description of the failure and
    # a boolean denoting whether a powercycle might help
    BOOT_FAIL_PATTERNS = [\
        ("Controller.*not.*started", 12, "RAID controller did not start", True),
        ("IP address not configured", 30, "Dom0 did not get an IP address", True),
        ("rebooting machine", 3, "Machine didn't come back somehow", True)
        ]
    def checkForHardwareBootProblem(self, retry):
        """Check the host serial console log, if available, for known
        BIOS/hardware boot problems. If a known problem is found, known to
        be intermittent (i.e. a power cycle may clear the problem) and
        the retry argument is true the machine will be power cycled and
        the method will return True. If the problem is unknown the
        method returns False. In all other cases the method raises an
        exception with a description of the failure."""
        if not self.machine:
            return False
        serlog = self.machine.getConsoleLogHistory()
        for bfp in self.BOOT_FAIL_PATTERNS:
            regexp, nlines, desc, pcycle = bfp
            found = None
            for line in serlog[0-nlines:]:
                if re.search(regexp, line):
                    found = desc
                    if pcycle and retry and self.machine.powerctl:
                        xenrt.TEC().warning(\
                            "Found known boot problem '%s' for machine %s. "
                            "Power cycling." % (desc, self.getName()))
                        self.machine.powerctl.cycle(fallback = True)
                        return True
                    break
            if found:
                raise xenrt.XRTError("Boot failure '%s' for machine !%s" %
                                     (found, self.getName()))
        # For machines with known intermittent PXE/BIOS boot failures we
        # can retry the boot (the calling method will only call us once
        # for this)
        if self.lookup("PXE_BIOS_BOOT_RETRY", False, boolean=True):
            xenrt.TEC().warning("Machine %s is known to have unreliable "
                                "PXE/BIOS boot, power cycling." %
                                (self.getName()))
            self.machine.powerctl.cycle(fallback = True)
            return True
        if self.lookup("CONSOLE_TYPE", None) != "basic" and self.lookup("CONSOLE_TYPE", None) != "slave":
            xenrt.TEC().warning("Machine %s may have unreliable serial output, power cycling." % (self.getName()))
            self.machine.powerctl.cycle(fallback = True)
            return True
        return False

    def _registerCallback(self):
        if not self.callbackRegistered:
            xenrt.TEC().gec.registerCallback(self)
            self.callbackRegistered = True

    def callback(self):
        """Cleanup callback."""
        for mac in self.portsToEnableAtCleanup:
            try:
                self.enableNetPort(mac)
            except Exception, e:
                traceback.print_exc(file=sys.stderr)
        for hba in self.hbasToEnableAtCleanup:
            try:
                self.enableFCPort(hba)
            except Exception, e:
                traceback.print_exc(file=sys.stderr)

    def bridgeToNetworkName(self, bridge):

        pif_uuids = self.minimalList("network-list", "PIF-uuids", "bridge=%s" % bridge)
        if len(pif_uuids) == 0:
            return None

        network = None
        my_pifs = self.minimalList('pif-list', 'uuid', 'host-uuid=%s' % self.getMyHostUUID())
        try:
            pif_uuid = set(my_pifs).intersection(set(pif_uuids)).pop()
        except:
            return None
        vlan = self.genParamGet("pif", pif_uuid, "VLAN")

        if vlan == "-1":
            network = "NPRI" # If we can't find a NSEC nic with the same MAC, then network must be NPRI
            mac = xenrt.util.normaliseMAC(self.genParamGet("pif", pif_uuid, "MAC"))
            nics = self.listSecondaryNICs()
            for n in nics:
                if xenrt.util.normaliseMAC(self.getNICMACAddress(n)) == mac:
                    network = self.getNICNetworkName(n)
        else:
            vlannames = self.lookup(["NETWORK_CONFIG", "VLANS"], None)
            if not vlannames:
                raise xenrt.XRTError("No VLANs defined for host %s" %
                                     (self.getName()))
            for v in vlannames:
                vlanid = self.lookup(["NETWORK_CONFIG", "VLANS", v, "ID"], None)
                if vlanid == vlan:
                    network = v

        return network

    def getIPv6SubnetMaskGateway(self,network):

        if network == "NPRI":
            configpath = ["NETWORK_CONFIG", "DEFAULT"]
        elif network == "NSEC":
            configpath = ["NETWORK_CONFIG", "SECONDARY"]
        else:
            configpath = ["NETWORK_CONFIG", "VLANS", network]

        configpath.append("SUBNETMASK6")
        subnetMask = xenrt.TEC().lookup(configpath, None)

        configpath[-1] = "GATEWAY6"
        gateway = xenrt.TEC().lookup(configpath, None)

        return subnetMask,gateway

    def _getDisks(self, var, sdfallback, count, ccissIfAvailable, legacySATA):
        disks = None
        try:
            if ccissIfAvailable:
                disks = self.lookup([var, "CCISS"])
            else:
                disks = self.lookup([var, "SCSI"])
        except:
            pass
        try:
            if legacySATA:
                disks = self.lookup([var, "LEGACY_SATA"])
            else:
                disks = self.lookup([var, "SATA"])
        except:
            pass
        if not disks:
            disks = self.lookup(var, None)
            # REQ-35: (Better) temp fix until we fix all of the config files
            if not legacySATA and disks and "scsi-SATA" in "".join(disks):
                disks = None
        if not disks and sdfallback:
            disks = string.join(map(lambda x:"sd"+chr(97+x), range(count)))
        if not disks:
            return []
        else:
            return string.split(disks)[:count]

    def _getMainDisks(self, count, ccissIfAvailable, legacySATA):
        return self._getDisks("OPTION_CARBON_DISKS", True, count=count, ccissIfAvailable=ccissIfAvailable, legacySATA=legacySATA)

    def getInstallDisk(self, ccissIfAvailable=False, legacySATA=False):
        return self._getMainDisks(ccissIfAvailable=ccissIfAvailable, count=1, legacySATA=legacySATA)[0]

    def getGuestDisks(self, count=1, ccissIfAvailable=False, legacySATA=False):
        disks = self._getDisks("OPTION_GUEST_DISKS", False, count=count, ccissIfAvailable=ccissIfAvailable, legacySATA=legacySATA)
        if disks:
            return disks
        else:
            return self._getMainDisks(count=count, ccissIfAvailable=ccissIfAvailable, legacySATA=legacySATA)

    def getContainerHost(self):
        container = self.lookup("CONTAINER_HOST", None)
        if not container:
            return None
        if not self.containerHost:
            machine = xenrt.PhysicalHost(container)
            place = xenrt.GenericHost(machine)
            place.findPassword()
            place.checkVersion()
            self.containerHost = xenrt.lib.xenserver.hostFactory(place.productVersion)(machine, productVersion=place.productVersion)
            place.populateSubclass(self.containerHost)
            self.containerHost.existing(doguests=False)
            guest = self.containerHost.guestFactory()(self.machine.name)
            guest.existing(self.containerHost)
        return self.containerHost

    def _parseNetworkTopology(self, topology, useFriendlySuffix=False):
        """Parse a network topology specification. Takes either a string
        containing XML or a XML DOM node."""
        if type(topology) == type(""):
            # Parse the topology XML
            xmlm = xml.dom.minidom.parseString(topology)
        else:
            xmlm = topology
        netnode = xmlm.getElementsByTagName("NETWORK")[0]
        physnodes = netnode.getElementsByTagName("PHYSICAL")
        nicsUsed = []
        physList = []
        for phys in physnodes:
            # Which network to use
            network = phys.getAttribute("network")
            if not network:
                network = "NPRI"
            network = str(network)

            enable_jumbo = phys.getAttribute("jumbo")
            if enable_jumbo:
                if type(enable_jumbo) is str or type(enable_jumbo) is unicode:
                    if str(enable_jumbo) == "yes":
                        jumbo = True
                    else:
                        jumbo = False
                else:
                    jumbo = enable_jumbo
            else:
                jumbo = False

            speed = phys.getAttribute("speed")
            if not speed:
                speed = None # Needed as we'll get the empty string rather than
                             # None if the attribute isn't specified, and that
                             # confuses listSecondaryNICs

            bondMode = phys.getAttribute("bond-mode")
            if bondMode == "":
                bondMode = None

            # Find NICs by assumed ID on this network
            avail = self.listSecondaryNICs(network, speed=speed)
            primaryNICSpeed = self.lookup("NIC_SPEED", None)
            if primaryNICSpeed == "1G":
                primaryNICSpeed = None
            if (network == "NPRI" or network == "ANY") and (not speed or primaryNICSpeed == speed or (not primaryNICSpeed and speed == "1G")):
                # The primary NIC is also on this network
                avail = [0] + avail
            nicnodes = phys.getElementsByTagName("NIC")
            nicList = []
            for nic in nicnodes:
                enum = nic.getAttribute("enum")
                if not enum and str(enum) != "0":
                    # Find the first unused NIC
                    nicaid = None
                    for n in avail:
                        if n in nicsUsed:
                            continue
                        nicaid = n
                        break
                    if nicaid == None:
                        raise xenrt.XRTError("Run out of %s NICs" % (network))
                else:
                    if int(enum) >= len(avail):
                        raise xenrt.XRTError("NIC %u of %s not found" %
                                             (int(enum), network))
                    if avail[int(enum)] in nicsUsed:
                        raise xenrt.XRTError("NIC %u of %s already used" %
                                             (int(enum), network))
                    nicaid = avail[int(enum)]
                nicsUsed.append(nicaid)
                nicList.append(nicaid)
            # See if we've configured management, storage or VM access on
            # this physical device
            mgmt = False
            storage = False
            vms = False
            friendlynetname = phys.getAttribute("name")
            if not friendlynetname:
                if useFriendlySuffix:
                    friendlynetname = "%s-%s" % (network,xenrt.randomSuffix())
                else:
                    friendlynetname = network
            for n in phys.childNodes:
                if n.nodeType == n.ELEMENT_NODE:
                    if n.localName == "MANAGEMENT":
                        m = n.getAttribute("mode")
                        if m:
                            mgmt = str(m).lower()
                        else:
                            mgmt = "dhcp"
                    elif n.localName == "STORAGE":
                        m = n.getAttribute("mode")
                        if m:
                            storage = str(m).lower()
                        else:
                            storage = "dhcp"
                    elif n.localName == "VMS":
                        vms = True
            # Look for VLANs on this physical device
            vlannodes = phys.getElementsByTagName("VLAN")
            vlanList = []
            for vlan in vlannodes:
                vnetwork = vlan.getAttribute("network")
                if not vnetwork:
                    vnetwork = "VR01"
                vnetwork = str(vnetwork)
                vfriendlynetname = vlan.getAttribute("name")
                if not vfriendlynetname:
                    if useFriendlySuffix:
                        vfriendlynetname = "%s-%s" % (vnetwork,xenrt.randomSuffix())
                    else:
                        vfriendlynetname = vnetwork
                # Look for management, storage or VM use on this VLAN
                vmgmt = False
                vstorage = False
                vvms = False
                for n in vlan.childNodes:
                    if n.nodeType == n.ELEMENT_NODE:
                        if n.localName == "MANAGEMENT":
                            m = n.getAttribute("mode")
                            if m:
                                vmgmt = str(m).lower()
                            else:
                                vmgmt = "dhcp"
                        elif n.localName == "STORAGE":
                            m = n.getAttribute("mode")
                            if m:
                                vstorage = str(m).lower()
                            else:
                                vstorage = "dhcp"
                        elif n.localName == "VMS":
                            vvms = True
                vlanList.append((vnetwork, vmgmt, vstorage, vvms, vfriendlynetname))
            physList.append((network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode))
        xenrt.TEC().logverbose("Parsed topology: %s" % (str(physList)))

        return physList

    def logInstallResult(self, result, installProduct):
        try:
            xenrt.GEC().dbconnect.jobctrl("event", [result, self.getName(), "%s-%s" % (xenrt.GEC().jobid(), installProduct)])
        except:
            pass

    def createTemplateSR(self):
        raise xenrt.XRTError("Not implemented")

class NetPeerHost(GenericHost):
    """ Encapsulates a network test peer for installation"""

    def checkVersion(self):
        pass

class GenericGuest(GenericPlace):
    """Encapsulates a single guest VM."""
    implements(xenrt.interfaces.OSParent)

    STATE_MAPPING = {
        xenrt.PowerState.down: "DOWN",
        xenrt.PowerState.up: "UP",
        xenrt.PowerState.paused: "PAUSED",
        xenrt.PowerState.suspended: "SUSPENDED"
    }
    
    def __init__(self, name, host=None, reservedIP=None):
        GenericPlace.__init__(self)
        self.host = host
        self.name = name
        self.memory = 256
        self.vcpus = 1
        self.corespersocket = None
        self.vifs = []
        self.ips = {}
        self.mainip = None
        self.reservedIP = reservedIP
        self.tailored = False
        self.enlightenedDrivers = False
        self.distro = None
        self.managenetwork = False
        self.managebridge = False
        self.use_ipv6 = False
        self.ipv4_disabled = False
        self.instance = None
        self.isTemplate = False
        self.imported = False
        self.sriovvifs = []
        xenrt.TEC().logverbose("Creating %s instance." % (self.__class__.__name__))

    def populateSubclass(self, x):
        GenericPlace.populateSubclass(self, x)
        x.host = self.host
        x.name = self.name
        x.memory = self.memory
        x.vcpus = self.vcpus
        x.vifs = self.vifs
        x.mainip = self.mainip
        x.enlightenedDrivers = self.enlightenedDrivers
        x.distro = self.distro
        x.tailored = self.tailored
        x.reservedIP = self.reservedIP
        x.instance = self.instance
        x.isTemplate = self.isTemplate
        x.imported = self.imported
        x.sriovvifs = self.sriovvifs

    def getDeploymentRecord(self):
        if self.isTemplate:
            ret = {"access": {"templatename": self.getName()}, "os": {}}
        else:
            ret = {"access": {"vmname": self.getName(),
                              "ipaddress": self.getIP()}, "os": {}}
        if not self.imported:
            if self.windows:
                ret['access']['username'] = "Administrator"
                ret['access']['password'] = xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS",
                                                            "ADMINISTRATOR_PASSWORD"],
                                                            "xensource")
                ret['os']['family'] = "windows"
                ret['os']['version'] = self.distro
            else:
                ret['access']['username'] = "root"
                ret['access']['password'] = "xenroot"
                ret['os']['family'] = "linux"
                arch = self.arch or "x86-32"
                ret['os']['version'] = "%s_%s" % (self.distro, arch)
        if self.host:
            ret['host'] = self.host.getName()
        else:
            ret['host'] = None
        return ret

    ##### Methods from OSParent #####

    @property
    @xenrt.irregularName
    def _osParent_name(self):
        return self.name

    @property
    @xenrt.irregularName
    def _osParent_hypervisorType(self):
        return xenrt.HypervisorType.unknown

    @xenrt.irregularName
    def _osParent_getIP(self, trafficType=None, timeout=600, level=xenrt.RC_ERROR):
        # TODO add arp sniffing capabilities here
        return self.mainip

    @xenrt.irregularName
    def _osParent_getPort(self, trafficType):
        return None

    @xenrt.irregularName
    def _osParent_setIP(self,ip):
        self.mainip = ip

    @xenrt.irregularName
    def _osParent_start(self):
        self.lifecycleOperation("vm-start")

    @xenrt.irregularName
    def _osParent_stop(self):
        self.lifecycleOperation("vm-shutdown")

    @xenrt.irregularName
    def _osParent_ejectIso(self):
        # TODO implement this with ISO SRs
        raise xenrt.XRTError("Not implemented")

    @xenrt.irregularName
    def _osParent_setIso(self, isoName, isoRepo=None):
        # TODO implement this with ISO SRs
        raise xenrt.XRTError("Not implemented")

    @xenrt.irregularName
    def _osParent_pollPowerState(self, state, timeout=600, level=xenrt.RC_FAIL, pollperiod=15):
        """Poll for reaching the specified state"""
        self.poll(self.STATE_MAPPING[state], timeout, level, pollperiod)

    @xenrt.irregularName
    def _osParent_getPowerState(self):
        """Get the current power state"""
        return [x for x in self.STATE_MAPPING.keys() if self.STATE_MAPPING[x] == self.getState()][0]

    def setHost(self, host):
        if host and host.replaced:
            self.host = host.replaced
        else:
            self.host = host

    def getHost(self):
        if not self.host:
            raise xenrt.XRTError("Guest has no host member")
        if self.host.replaced:
            self.host = self.host.replaced
        return self.host

    def compareConfig(self, other):
        """Compare the configuration of this place to another place. This
        is limited to the major parameters modelled by this library. Any
        differences will cause a XRTFailure to be raised.
        """
        GenericPlace.compareConfig(self, other)
        if self.memory != other.memory:
            raise xenrt.XRTFailure("Memory size mismatch",
                                   "%s:%s %s:%s" % (self.getName(),
                                                    str(self.memory),
                                                    other.getName(),
                                                    str(other.memory)))
        if self.vcpus != other.vcpus:
            raise xenrt.XRTFailure("vCPUs mismatch",
                                   "%s:%s %s:%s" % (self.getName(),
                                                    str(self.vcpus),
                                                    other.getName(),
                                                    str(other.vcpus)))
        if (self.vifs and not other.vifs) or (other.vifs and not self.vifs):
            raise xenrt.XRTFailure("VIF count mismatch",
                                   "%s:%s %s:%s" % (self.getName(),
                                                    str(self.vifs),
                                                    other.getName(),
                                                    str(other.vifs)))
        elif self.vifs and other.vifs:
            if len(self.vifs) != len (other.vifs):
                raise xenrt.XRTFailure("VIF count mismatch",
                                       "%s:%s %s:%s" % (self.getName(),
                                                        str(self.vifs),
                                                        other.getName(),
                                                        str(other.vifs)))
            for i in range(len(self.vifs)):
                nic0, vbridge0, mac0, ip0 = self.vifs[i]
                nic1, vbridge1, mac1, ip1 = other.vifs[i]
                # Strip the nic prefix ("eth" or "nic") to compare only
                # on index
                nic0 = nic0.replace("eth", "")
                nic0 = nic0.replace("nic", "")
                nic1 = nic1.replace("eth", "")
                nic1 = nic1.replace("nic", "")
                if nic0 != nic1:
                    raise xenrt.XRTError("VIF device mismatch",
                                         "%s:%s %s:%s" % (self.getName(),
                                                          str(nic0),
                                                          other.getName(),
                                                          str(nic1)))
                if vbridge0 != vbridge1:
                    raise xenrt.XRTError("Bridge name mismatch",
                                         "%s:%s %s:%s" % (self.getName(),
                                                          str(vbridge0),
                                                          other.getName(),
                                                          str(vbridge1)))
                if mac0 != mac1:
                    raise xenrt.XRTError("MAC address mismatch",
                                         "%s:%s %s:%s" % (self.getName(),
                                                          str(mac0),
                                                          other.getName(),
                                                          str(mac1)))

    def checkFailuresinConsoleLogs(self,domid):
        """
        Checks console logs for known install failures and raise error if found
        if none of the errors matches, raise error with last log line
        """
        
        #error_list is a dictionary with key is regular expression for expected error
        #value is the error message that will be displayed
        #In case this error lists becomes too long, it will be good to move it to a file.
        error_lists={
        "EIP is at cpuid4_cache_lookup":"EIP is at cpuid4_cache_lookup",
        "The file (.*.rpm) cannot be opened.": '{0} is corrupted',
        "kernel BUG at (.*)" : "kernel BUG at {0}",
        "rcu_sched detected stalls on cpus/tasks": "rcu_sched detected stalls on cpus/tasks",
        "BUG: unable to handle kernel paging request at virtual address [\d]+":\
                                     "BUG: unable to handle kernel paging request at virtual address",
        "Failure trying to run: chroot /target dpkg.* (.*.deb)" : \
                                     "Failure trying to run: chroot /target dpkg for {0}",
        }
        log("looking in console logs for errors")
        data = self.host.guestConsoleLogTail(domid,lines=200)
        data = re.sub(r"\033\[[\d]*;?[\d]*[a-zA-Z]","",data)
        lines = re.findall(r"((?:[\w\d\./\(\)]+ ){3,20})", data)
        if lines:
            for error in error_lists:
                mo=re.search(error, data,re.DOTALL|re.MULTILINE)
                if mo:
                    inputs=mo.groups()
                    raise xenrt.XRTFailure("Install failed:%s" % error_lists[error].format(*inputs))

            lastline = lines[-1].strip()
            if lastline:
                raise xenrt.XRTFailure("Vendor install timed out. " 
                                           "Last log line was %s" % (lastline))

    def __copy__(self):
        cp = self.__class__(self.name)
        cp.__dict__.update(self.__dict__)
        cp.vifs = copy.copy(self.vifs)
        return cp

    def setVCPUs(self, vcpus):
        self.vcpus = vcpus

    def setCoresPerSocket(self, corespersocket):
        self.corespersocket = corespersocket

    def setMemory(self, memory):
        self.memory = memory

    def getIP(self):
        return self.mainip

    def getName(self):
        return self.name

    def __str__(self):
        return self.getName()

    def setName(self, name):
        self.name = name

    def getInfo(self):
        uuid = "UNKNOWN"
        if self.host:
            uuid = self.host.getGuestUUID(self)
            if not uuid:
                uuid = "UNKNOWN"
        name = self.getName()
        if not name:
            name = "UNKNOWN"
        ip = self.getIP()
        if not ip:
            ip = "UNKNOWN"
        distro = self.distro
        if not distro:
            distro = "UNKNOWN"
        vcpus = self.vcpus
        if vcpus == None:
            vcpus = 0
        memory = self.memory
        if memory == None:
            memory = 0
        return [name, ip, vcpus, memory, distro, uuid]

    def getGuestMemory(self):
        return self.getMyMemory()

    def getGuestVCPUs(self):
        return self.getMyVCPUs()

    def getGuestVIFs(self):
        return self.getMyVIFs()

    def findDistro(self):
        if self.distro and self.distro !="UNKNOWN":
            return
        # windows distro
        try:
            osname = self.xmlrpcExec('systeminfo | findstr /C:"OS Name"',returndata=True).splitlines()[2].split(":")[1].strip()
            osname = osname.strip("Microsoft ")
            self.windows = True

            matchedDistros = [(d,n) for (d,n) in xenrt.enum.windowsdistros if osname in n]
            while len(matchedDistros) == 0 and len(osname.split(" ")) > 3:
                osname = osname.rsplit(" ",1)[0]
                matchedDistros = [(d,n) for (d,n) in xenrt.enum.windowsdistros if osname in n]

            if len(matchedDistros) > 1:
                systype = self.xmlrpcExec('systeminfo | findstr /C:"System Type"',returndata=True).splitlines()[2].split(":")[1].strip()
                if "x64" not in systype:
                    matchedDistros = [(d,n) for (d,n) in matchedDistros if "x64" not in d]
                else:
                    matchedDistros = [(d,n) for (d,n) in matchedDistros if "x64" in d]
            if len(matchedDistros) > 1:
                osname = osname + " "
                matchedDistros = [(d,n) for (d,n) in matchedDistros if osname in n]

            # At this point if we have more than 1 distro matching, we can proceed with any of them.
            if len(matchedDistros) >= 1:
                self.distro = matchedDistros[0][0]
        except:
            # linux distros
            try:
                release = self.execguest("cat /etc/issue", nolog=True).strip().splitlines()[0].strip()
                # Debian derived - debian, ubuntu
                if "Ubuntu" in release:
                    release = release.split(" ")[1]
                    if len(release)>5:
                        release = release[:5]
                    self.distro = "ubuntu" + str(release.replace(".",""))
                elif "Debian" in release:
                    release = self.execguest("cat /etc/debian_version", nolog=True).splitlines()[0].strip()
                    self.distro = "debian" + str(release.split(".")[0]) + "0"
                elif  "SUSE" in release:
                    # sles
                    release = self.execguest("rpm -qf /etc/SuSE-release", nolog=True).strip()
                    relversion = release.split("-")[2].replace(".","")
                    self.distro ="sles" + relversion
                else:
                    # rhel derived - rhel, centos, oel
                    try:
                        release = self.execguest("cat /etc/oracle-release", nolog=True).splitlines()[0].strip()
                    except:
                        try:
                            release = self.execguest("cat /etc/redhat-release", nolog=True).splitlines()[0].strip()
                        except:
                            release = None
                    if release:
                        relversion = release.split("release ")[1].split(" ")[0].strip("0")
                        if "Oracle" in release:
                            self.distro = "oel" + str(relversion.replace(".",""))
                        elif "CentOS" in release:
                            self.distro = "centos" + str(relversion.replace(".",""))
                        elif "Red Hat" in release:
                            self.distro = "rhel" + str(relversion.replace(".",""))
            except:
                pass

        if self.distro:
            xenrt.TEC().logverbose("distro identified as %s " % self.distro)
        else:
            xenrt.TEC().warning("Failed to identify guest distro")

    def check(self):
        """Check the installed guest resources match the specification."""
        ok = 1
        reasons = []

        xenrt.TEC().logverbose("Checking guest: %s" % (self.name))

        # Memory
        if self.memory:
            try:
                guest_reported = self.getGuestMemory()
                dom0_reported = self.getDomainMemory()
                xenrt.TEC().logverbose("Guest reports %uM." % (guest_reported))
                xenrt.TEC().logverbose("Domain-0 reports %uM." % (dom0_reported))
                xenrt.TEC().logverbose("Config reports %uM." % (self.memory))

                memcap = None
                if self.distro:
                    if self.arch and "64" in self.arch:
                        memcap = xenrt.TEC().lookup(["GUEST_LIMITATIONS", self.distro, "MAXMEMORY64"], None)

                    if not memcap:
                        memcap = xenrt.TEC().lookup(["GUEST_LIMITATIONS", self.distro, "MAXMEMORY"], None)

                if xenrt.TEC().lookup("IGNORE_MEM_LIMITATIONS", False, boolean=True):
                    memcap = None

                if memcap and self.memory > int(memcap):
                    xenrt.TEC().logverbose("%s will not use more than %sMB memory." % (self.distro, memcap))
                    m = int(memcap)
                else:
                    m = self.memory

                if guest_reported != -1:
                    delta = abs(guest_reported - m)
                    if delta <= 16 or delta <= (m/20):
                        pass
                    elif delta <= (m/10):
                        xenrt.TEC().warning("Guest memory %uMB does not match config %uMB." %
                                            (guest_reported, m))
                    else:
                        ok = 0
                        reasons.append("Guest memory %uMB does not match config %uMB." %
                                       (guest_reported, m))

                delta = abs(dom0_reported - m)
                if delta <= 16 or delta <= (m/20):
                    pass
                elif delta <= (m/10):
                    xenrt.TEC().warning("Domain memory %uMB does not match config %uMB." %
                                       (dom0_reported, m))
                else:
                    ok = 0
                    reasons.append("Domain memory %uMB does not match config %uMB." %
                                  (dom0_reported, m))
            except Exception, e:
                sys.stderr.write(str(e))
                traceback.print_exc(file=sys.stderr)
                xenrt.TEC().warning("Unable to check guest memory.")

        # CPUs
        try:
            guest_reported = self.getGuestVCPUs()
            dom0_reported = self.getDomainVCPUs()

            if self.corespersocket:
                corespersocket = int(self.corespersocket)
            else:
                corespersocket = 1

            xenrt.TEC().logverbose("Guest reports %u CPUs." % (guest_reported))
            xenrt.TEC().logverbose("Domain-0 reports %u CPUs." % (dom0_reported))
            xenrt.TEC().logverbose("Config reports %u CPUs (with %u cores per CPU socket)." % (self.vcpus, corespersocket))

            if self.vcpus == 0:
                # vcpus=all
                configed = self.host.getCPUCores()
            else:
                configed = self.vcpus

            cpucap = None
            if self.distro:
                cpucap = xenrt.TEC().lookup(\
                    ["GUEST_LIMITATIONS", self.distro, "MAXCORES"], None)
            if cpucap and configed > int(cpucap):
                xenrt.TEC().logverbose("%s will not use more than %s CPU cores" %
                                       (self.distro, cpucap))
                c = int(cpucap)
            else:
                c = configed

            if guest_reported != c:
                ok = 0
                reasons.append("Guest CPUs %u does not match config vCPUs %u" %
                              (guest_reported, c))

            if dom0_reported != c:
                ok = 0
                reasons.append("Domain-0 vCPUs %u does not match config vCPUs %u" %
                              (dom0_reported, c))
        except Exception, e:
            xenrt.TEC().logverbose("Guest check CPUs exception: %s" % (str(e)))
            xenrt.TEC().warning("Unable to check guest cpus.")

        # Network
        try:
            guest_reported = [ xenrt.normaliseMAC(i) for i in self.getGuestVIFs() ]
            dom0_reported = [ xenrt.normaliseMAC(i) for i in self.getDomainVIFs() ]
            xenrt.TEC().logverbose("Guest found: %s" % (guest_reported))
            xenrt.TEC().logverbose("Domain-0 found: %s" % (dom0_reported))

            if not len(guest_reported) == len(self.vifs):
                msg = "Guest VIFs %u do not match config VIFs %u." % \
                          (len(guest_reported), len(self.vifs))
                if xenrt.TEC().lookup("GUEST_VIFS_WARN_ONLY",
                                      False,
                                      boolean=True):
                    xenrt.TEC().warning(msg)
                else:
                    ok = 0
                    reasons.append(msg)
            for vif in self.vifs:
                nic, vbridge, mac, ip = vif
                if not xenrt.normaliseMAC(mac) in guest_reported:
                    msg = "Couldn't find VIF with MAC %s in guest." % (mac)
                    if xenrt.TEC().lookup("GUEST_VIFS_WARN_ONLY",
                                          False,
                                          boolean=True):
                        xenrt.TEC().warning(msg)
                    else:
                        ok = 0
                        reasons.append(msg)

            if not len(dom0_reported) == len(self.vifs):
                msg = "Domain-0 VIFs %u do not match config VIFs %u." % \
                      (len(dom0_reported), len(self.vifs))
                if xenrt.TEC().lookup("GUEST_VIFS_WARN_ONLY",
                                      False,
                                      boolean=True):
                    xenrt.TEC().warning(msg)
                else:
                    ok = 0
                    reasons.append(msg)
            for vif in self.vifs:
                nic, vbridge, mac, ip = vif
                if not xenrt.normaliseMAC(mac) in dom0_reported:
                    msg = "Couldn't find VIF with MAC %s in domain-0." % (mac)
                    if xenrt.TEC().lookup("GUEST_VIFS_WARN_ONLY",
                                          False,
                                          boolean=True):
                        xenrt.TEC().warning(msg)
                    else:
                        ok = 0
                        reasons.append(msg)
        except Exception, e:
            xenrt.TEC().logverbose("Guest check VIFs exception: %s" % (str(e)))
            xenrt.TEC().warning("Unable to check guest vifs.")

        if ok == 0:
            if xenrt.TEC().lookup("GUEST_CONFIG_WARN_ONLY", True, boolean=True):
                for r in reasons:
                    xenrt.TEC().warning(r)
            else:
                for r in reasons:
                    xenrt.TEC().reason(r)
                    raise xenrt.XRTFailure("Installed guest resources did " +
                                           "not match VM configuration.")

    def checkNetworkSSH(self):
        """Check network connectivity to the guest"""
        # Try SSH up to three times
        try:
            self.execguest("true")
            return
        except:
            pass
        xenrt.sleep(2)
        try:
            self.execguest("true")
            xenrt.TEC().comment("Could not SSH to guest on first attempt")
            return
        except:
            pass
        xenrt.sleep(5)
        try:
            self.execguest("true")
            xenrt.TEC().comment("Could not SSH to guest on second attempt")
            return
        except:
            pass

        # Anything from here will be a failure
        if xenrt.command("ping -c 3 -w 10 %s" % (self.getIP()),
                         retval="code") == 0:
            raise xenrt.XRTFailure("Could not SSH to guest but is pingable")
        raise xenrt.XRTFailure("Could not SSH to guest and is not pingable")

    def checkNetworkNoSSH(self):
        """Check network connectivity to the guest"""
        # Try the daemon up to three times
        try:
            self.xmlrpcVersion()
            return
        except:
            pass
        xenrt.sleep(2)
        try:
            self.xmlrpcVersion()
            xenrt.TEC().comment("Could not connect to guest on first attempt")
            return
        except:
            pass
        xenrt.sleep(5)
        try:
            self.xmlrpcVersion()
            xenrt.TEC().comment("Could not connect to guest on second attempt")
            return
        except:
            pass

        # Anything from here will be a failure
        if xenrt.command("ping -c 3 -w 10 %s" % (self.getIP()),
                         retval="code") == 0:
            raise xenrt.XRTFailure("Could not connect to guest but is "
                                   "pingable")
        raise xenrt.XRTFailure("Could not connect to guest and is not "
                               "pingable")

    def checkNetwork(self):
        if not self.windows:
            self.checkNetworkSSH()
        else:
            self.checkNetworkNoSSH()

    def execguest(self,
                  command,
                  username=None,
                  retval="string",
                  level=xenrt.RC_FAIL,
                  timeout=1200,
                  idempotent=False,
                  newlineok=False,
                  getreply=True,
                  nolog=False,
                  useThread=False,
                  outfile=None,
                  password=None):
        """Execute a command on the guest.

        @param retval:  Whether to return the result code or stdout as a string
            "C{string}" (default), "C{code}"
            if "C{string}" is used then a failure results in an exception
        @param level:   Exception level to use if appropriate.
        @param nolog:   If C{True} then don't log the output of the command
        """
        try:
            if not isinstance(self.os, xenrt.xenrt.lib.opsys.LinuxOS):
                xenrt.TEC().warning("OS is not Linux - self.os is of type %s" % str(self.os.__class__))
                [xenrt.TEC().logverbose(x) for x in traceback.format_stack()]
        except Exception, e:
            xenrt.TEC().warning("Error creating OS: %s" % str(e))
            [xenrt.TEC().logverbose(x) for x in traceback.format_stack()]
        if not self.mainip:
            raise xenrt.XRTError("Unknown IP address to SSH to %s" %
                                 (self.name))
        if not username:
            if self.windows:
                username = "Administrator"
            else:
                username = "root"
        if not self.password and self.windows:
            password = xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS",
                                           "ADMINISTRATOR_PASSWORD"],
                                          "xensource")
        else:
            if password is None:
                password = self.password
        return xenrt.ssh.SSH(self.mainip,
                             command,
                             username=username,
                             password=password,
                             level=level,
                             retval=retval,
                             timeout=timeout,
                             idempotent=idempotent,
                             newlineok=newlineok,
                             getreply=getreply,
                             nolog=nolog,
                             useThread=useThread,
                             outfile=outfile)

    def reboot(self, force=False, skipsniff=False):
        # Per-product guest subclasses will override this. Define a fallback
        # method for guests used directly (e.g. with xrt --guest)

        # Initiate a reboot from within the VM
        if self.windows:
            self.xmlrpcReboot()
        else:
            self.execguest("/sbin/reboot")
        xenrt.sleep(180)

        # Wait for the guest to become reachable
        timeout = 600
        if self.windows:
            self.waitForDaemon(timeout)
        else:
            self.waitForSSH(timeout, desc="Guest reboot")
        # XXX: ought to check uptime to make sure the reboot happened

    def recoverGuest(self):
        xenrt.TEC().logverbose("Trying to recover %s..." % (self.getName()))
        try:
            if self.getState() == "UP":
                xenrt.TEC().logverbose("Guest seems to be up. Forcing shutdown.")
                self.shutdown(force=True)
            if self.getState() == "PAUSED":
                xenrt.TEC().logverbose("Guest seems to be paused. Forcing shutdown.")
                self.shutdown(force=True)
            self.start()
            if not self.windows:
                self.waitForSSH(300)
            else:
                self.waitForDaemon(300)
        except:
            xenrt.TEC().comment("Failed to recover %s." % (self.getName()))
            return False
        xenrt.TEC().comment("Recovered %s." % (self.getName()))
        return True

    def tailor(self):
        """Tailor a new guest to allow other tests to be run"""
        
        if "tailor" in map(lambda x:x[2], traceback.extract_stack())[:-1]:
            xenrt.TEC().logverbose("Terminating recursive tailor call")
            return
        
        if not self.mainip:
            raise xenrt.XRTError("Unknown IP address to SSH to %s" %
                                 (self.name))

        self.findPassword()

        if not self.windows:
            # Copy the test scripts to the guest
            xrt = xenrt.TEC().lookup("XENRT_BASE", "/usr/share/xenrt")
            sdir = xenrt.TEC().lookup("REMOTE_SCRIPTDIR")
            self.execguest("rm -rf %s" % sdir)
            self.execguest("mkdir -p %s" % (os.path.dirname(sdir)))
            sftp = self.sftpClient()

            # sometimes we get an error doing this recursive copy very soon after a vm-start (CA-172621)
            max = 3
            for i in range(max):
                try:
                    sftp.copyTreeTo("%s/scripts" % (xrt), sdir)
                except Exception, ex:
                    xenrt.TEC().logverbose(str(ex))
                    if i == max - 1:
                        raise
                else:
                    break

            # write out host key to guest to allow us to SSH to guest from dom0. This is a useful diagnostic tool.
            try:
                k = self.host.execdom0("cat /etc/ssh/ssh_host_dsa_key.pub")
                self.execguest("mkdir -p /root/.ssh")
                self.execguest("echo '%s' > /root/.ssh/authorized_keys" % k, newlineok=True)
                self.execguest("chmod 600 /root/.ssh/authorized_keys")
            except Exception, ex:
                xenrt.TEC().logverbose(str(ex))

        # Build a Windows preparation script.
        if self.windows:
            self.xmlrpcTailor()
        else:
            # Linux guest
            isDebian = self.execguest("test -e /etc/debian_version",
                                      retval="code") == 0

            isUbuntu = False
            if self.execguest("test -e /etc/lsb-release", retval="code") == 0:
                ubuntuVer = self.execguest("cat /etc/lsb-release")
                if re.match(r".*Ubuntu.*", ubuntuVer):
                    isUbuntu = True

            isDebian = isDebian and not isUbuntu

            if isUbuntu:
                # change the TMPTIME so /tmp doesn't get cleared away on
                # every reboot

                self.execguest("sed -i 's/TMPTIME=0/TMPTIME=-1/g' /etc/default/rcS")

                self.execguest("cat /etc/apt/sources.list")
                self.execguest("apt-get update")


            # If Debian then apt-get some stuff
            if isDebian:

                if self.special.get("debiantesting_upgrade"):
                    self.special['debiantesting_upgrade'] = False
                    self.upgradeDebian(newVersion="testing")


                apt_cacher = None
                debVer = self.execguest("cat /etc/debian_version")
                if "stretch" in debVer or "sid" in debVer:
                    debVer = 9.0
                else:
                    debVer = float(re.match(r"\d+(\.\d+)?", debVer).group(0))
                if debVer < 5.0:
                    # Pre-Lenny, may have to use a cacher
                    apt_cacher = "%s/debarchive" % xenrt.TEC().lookup("APT_SERVER")
                if apt_cacher:
                    filebase = "/etc/apt/sources.list"
                    if self.execguest("test -e %s.orig" % (filebase),
                                      retval="code") != 0:
                        apt_cacher_root = re.sub(r"/debian$","",apt_cacher)
                        fn = xenrt.TEC().tempFile()
                        sftp.copyFrom(filebase, fn)
                        f = file(fn, "r")
                        data = f.read()
                        f.close()
                        data = string.replace(data,
                                              "deb http://security.debian.org",
                                              "#deb http://security.debian.org")
                        data = re.sub(r"http\S+debian.org\S+",
                                      apt_cacher,
                                      data)
                        data = string.replace(data,
                                              "http://www.backports.org/debian",
                                              "%s-backports" % (apt_cacher))
                        #data = string.replace(data,
                        #                      "http://updates.xensource.com",
                        #                      apt_cacher_root)
                        lines = data.split("\n")
                        newlines = []
                        for line in lines:
                            if "updates.xensource.com" in line:
                                line = "#" + line
                            newlines.append(line)
                            data = string.join(newlines,"\n")

                        self.execguest("mv %s %s.orig" % (filebase, filebase))
                        f = file(fn, "w")
                        f.write(data)
                        f.close()
                        sftp.copyTo(fn, filebase)

                # Rewrite /etc/apt/sources.list.d/xensource.list
                # or similar (if present)
                for filebase, hname in \
                        [("/etc/apt/sources.list.d/xensource.list",
                          "updates.xensource.com"),
                         ("/etc/apt/sources.list.d/citrix.list",
                          "updates.vmd.citrix.com")]:
                    try:
                        if (self.execguest("test -e %s.orig" % (filebase),
                                           retval="code") != 0 and
                            self.execguest("test -e %s" % (filebase),
                                           retval="code") == 0):
                            fn = xenrt.TEC().tempFile()
                            sftp.copyFrom(filebase, fn)
                            f = file(fn, "r")
                            data = f.read()
                            f.close()
                            if apt_cacher:
                                apt_cacher_root = re.sub(r"/debian$","",apt_cacher)
                                data = string.replace(data,
                                                      hname,
                                                      apt_cacher_root)
                            lines = data.split("\n")
                            newdata = ""
                            for line in lines:
                                newdata += "#" + line + "\n"
                            self.execguest("mv %s %s.orig" %
                                           (filebase, filebase))
                            f = file(fn, "w")
                            f.write(newdata)
                            f.close()
                            sftp.copyTo(fn, filebase)
                    except:
                        pass

                # If running Debian Etch, we need to disable the updates.vmd.citrix.com repository,
                # as this no longer exists due to Etch going end of life
                if debVer <= 4.0:
                    for filename in ["/etc/apt/sources.list.d/xensource.list", "/etc/apt/sources.list.d/citrix.list"]:
                        if self.execguest("test -e %s" % (filename), retval="code") == 0:
                            self.execguest("rm -f %s" % (filename))

                if self.execguest("[ -e /etc/apt/sources.list.d/updates.list ]", retval="code") and int(debVer) in (6, 7, 8) and xenrt.TEC().lookup("APT_SERVER", None):
                    codename = self.execguest("cat /etc/apt/sources.list | grep '^deb' | awk '{print $3}' | head -1").strip()
                    self.execguest("echo deb %s/debsecurity %s/updates main >> /etc/apt/sources.list.d/updates.list" % (xenrt.TEC().lookup("APT_SERVER"), codename))
                    self.execguest("echo deb %s/debian %s-updates main >> /etc/apt/sources.list.d/updates.list" % (xenrt.TEC().lookup("APT_SERVER"), codename))
                    if int(debVer) in (6,):
                        self.execguest("echo deb %s/debian %s-lts main >> /etc/apt/sources.list.d/updates.list" % (xenrt.TEC().lookup("APT_SERVER"), codename))
                    if int(debVer) in (7,8):
                        self.execguest("echo deb %s/debian %s-backports main >> /etc/apt/sources.list.d/updates.list" % (xenrt.TEC().lookup("APT_SERVER"), codename))

                try:
                    data = self.execguest("apt-get update")
                except:
                    # If apt-get commands fail, wait a bit and retry.
                    xenrt.sleep(60)
                    data = self.execguest("apt-get update")

                # May need to update the keyring
                if "NO_PUBKEY" in data:
                    try:
                        self.execguest("apt-get install --force-yes -y "
                                       "debian-archive-keyring")
                    except Exception, e:
                        xenrt.TEC().logverbose("Exception: %s" % (str(e)))
                    self.execguest("apt-get update")

                preUpgBootDir = self.execguest("find /boot -type f | xargs md5sum")
                self.execguest("DEBIAN_FRONTEND=noninteractive apt-get -y --force-yes upgrade")
                postUpgBootDir = self.execguest("find /boot -type f | xargs md5sum")
                if preUpgBootDir != postUpgBootDir:
                    self.reboot(skipsniff=True)

                modules = ["DEBIAN_MODULES", "DEBIAN_MODULES2"]
                if debVer == 4.0:
                    modules.append("DEBIAN_ETCH_MODULES")
                for v in modules:
                    m = xenrt.TEC().lookup(v, None)
                    if m:
                        cmd = "apt-get install -y --force-yes %s" % (m)
                        try:
                            self.execguest(cmd)
                        except:
                            # If apt-get commands fail, wait a bit and retry.
                            xenrt.sleep(60)
                            self.execguest(cmd)

                # Disable the bootclean init script (XRT-4102)
                self.execguest("/usr/sbin/update-rc.d -f bootclean remove || true")
                self.execguest("/usr/sbin/update-rc.d -f mountall-bootclean.sh remove || true")
                self.execguest("/usr/sbin/update-rc.d -f mountnfs-bootclean.sh remove || true")

            # Optionally upgrade some RPMs
            if self.distro and self.arch:

                needreboot = False
                oldkernel = None

                # Check if XenRT yum repo needs to be added to guest
                if self.execcmd('test -e /etc/redhat-release', retval="code") == 0:
                    if not self.updateYumConfig(self.distro, self.arch):
                        xenrt.TEC().warning('Failed to specify XenRT yum repo for %s, %s' % (self.distro, self.arch))
                    updateTo = self.special.get("UpdateTo")
                    if updateTo:
                        del self.special['UpdateTo']
                        self.updateLinux(updateTo)

                # These are RPMs statically configured for this distro
                rpmdir = "%s/guestrpms/%s/%s" % \
                         (xenrt.TEC().lookup("TEST_TARBALL_ROOT"),
                          self.distro,
                          self.arch)
                if os.path.exists(rpmdir):

                    if self.execguest("test -e "
                                      "/etc/xenrt-static-rpms-installed",
                                      retval="code") == 0:
                        xenrt.TEC().logverbose("Static RPMs already installed "
                                               "on VM '%s'" % (self.getName()))
                    else:
                        xenrt.TEC().logverbose(\
                            "We have static RPM additions/upgrades for %s %s "
                            "VM '%s'" %
                            (self.distro, self.arch, self.getName()))
                        rpms = glob.glob("%s/*.rpm" % (rpmdir))
                        rdir = self.tempDir()
                        sftp = self.sftpClient()
                        haskernel = False
                        try:
                            for rpm in rpms:
                                sftp.copyTo(rpm, "%s/%s" %
                                            (rdir, os.path.basename(rpm)))
                                if os.path.basename(rpm).startswith("kernel-"):
                                    haskernel = True
                        finally:
                            sftp.close()

                        if haskernel and self.distro in ["rhel5","rhel51",
                                                         "rhel52","centos5",
                                                         "centos51","centos52"]:
                            # We need to remove the ecryptfs RPM
                            xenrt.TEC().logverbose("Removing ecryptfs RPM "
                                                   "which conflicts with newer "
                                                   "kernels")
                            self.execguest("rpm -e --allmatches ecryptfs-utils || true")

                        # Install/upgrade the RPMs
                        self.execguest("rpm -Uv %s/*" % (rdir))
                        self.execguest("touch "
                                       "/etc/xenrt-static-rpms-installed")

                        # If the RPMs included a kernel then record what
                        # we have now, reboot, and check we have a new one
                        # after reboot
                        if haskernel and not self.getDomainType() == "hvm":
                            needreboot = True
                            oldkernel = self.execguest("uname -r").strip()

                # These are RPMs given as inputs to the test
                rpmupg = xenrt.TEC().lookup("RPMUPG_%s-%s" %
                                            (self.distro, self.arch), None)
                if rpmupg:
                    xenrt.TEC().logverbose(\
                        "We have RPM upgrades for %s %s VM '%s'" %
                        (self.distro, self.arch, self.getName()))
                    fn = xenrt.TEC().getFile(rpmupg)
                    if not fn:
                        raise xenrt.XRTError("Failed to fetch file %s" %
                                             (rpmupg))
                    rpms = []
                    tarargs = None
                    if rpmupg.endswith(".rpm"):
                        rpms.append(fn)
                    elif rpmupg.endswith("tar"):
                        tarargs = "-xf"
                    elif rpmupg.endswith("tar.gz"):
                        tarargs = "-zxf"
                    elif rpmupg.endswith("tar.bz2"):
                        tarargs = "-jxf"
                    else:
                        raise xenrt.XRTError(\
                            "Don't know how to handle an RPM upgrade "
                            "file named %s" % (rpmupg))
                    if tarargs:
                        rpmdir = xenrt.TEC().tempDir()
                        xenrt.command("tar -C %s %s %s" %
                                      (rpmdir, tarargs, fn))
                        rpms.extend(xenrt.command(\
                            "find %s -name '*.rpm'" % (rpmdir)).split())
                    rdir = self.tempDir()
                    sftp = self.sftpClient()
                    try:
                        for rpm in rpms:
                            sftp.copyTo(rpm, "%s/%s" %
                                        (rdir, os.path.basename(rpm)))
                    finally:
                        sftp.close()
                    self.execguest("rpm -Uv %s/*" % (rdir))
                    xenrt.TEC().warning(\
                        "Upgrading one or more RPMs in VM %s" %
                        (self.getName()))
                    needreboot = True

                if needreboot:
                    # Mark that we're finished tailoring so reboot doesn't
                    # recursively call us
                    self.tailored = True
                    self.reboot()

                    # If required check the kernel has been upgraded
                    if oldkernel:
                        newkernel = self.execguest("uname -r").strip()
                        if oldkernel == newkernel:
                            raise xenrt.XRTError(\
                                "Was expecting kernel upgrade in VM "
                                "tailoring, did not happen", oldkernel)
                        xenrt.TEC().logverbose(\
                            "Upgraded VM kernel from %s to %s" %
                            (oldkernel, newkernel))

            # Enable sysrq if possible
            try:
                sysctlFileisPresent= (self.execguest("if [ -e /etc/sysctl.conf ]; then echo $?; fi;",retval="code") == 0)
                if sysctlFileisPresent:
                # Check if kernel.sysrq is present in sysctl.conf
                    kernelSysrqisPresent = (self.execguest("grep -q 'kernel.sysrq' '/etc/sysctl.conf' && echo $?",retval="code") == 0)
                    if kernelSysrqisPresent:
                        self.execguest("mv /etc/sysctl.conf /etc/sysctl.conf.orig;"
                                 "sed -re's/kernel.sysrq = 0/kernel.sysrq = 1/' "
                                 "< /etc/sysctl.conf.orig > /etc/sysctl.conf; "
                                 "echo 1 > /proc/sys/kernel/sysrq; ")
                    else:
                        self.execguest("echo 'kernel.sysrq = 1' >> /etc/sysctl.conf")
                        self.execguest("echo 1 > /proc/sys/kernel/sysrq")
            except:
                xenrt.TEC().warning("Error enabling syslog in %s" %
                                    (self.getName()))
            try:
                isSLES = (self.execguest("test -e /etc/SuSE-release", retval="code") == 0)
                if isSLES:
                    # SLES enables sysrq in a different way to other VMs
                    self.execguest("if [ -e /etc/sysconfig/sysctl ]; then "
                                   "  mv /etc/sysconfig/sysctl /etc/sysconfig/sysctl.orig; "
                                   "  sed -re's/ENABLE_SYSRQ=/#ENABLE_SYSRQ=/' "
                                   "     < /etc/sysconfig/sysctl.orig > /etc/sysconfig/sysctl; "
                                   "  echo 'ENABLE_SYSRQ=1' >> /etc/sysconfig/sysctl; "
                                   "fi")
            except:
                xenrt.TEC().warning("Error performing SLES specific syslog "
                                    "enable in %s" % (self.getName()))

            # Disable some stuff (XRT-759)
            for s in ["makewhatis", "locate"]:
                try:
                    self.execguest("( for i in /etc/cron.*; "
                                   "    do find $i -name '*%s*'; "
                                   "  done ) | xargs rm -f" % (s))
                except:
                    pass

        if not self.windows:
            xenrt.TEC().logverbose("Guest %s is running kernel %s" % (self.name, self.execguest("uname -a")))


        if not self.windows:
            sftp.close()

        self.tailored = True

    def getWindowsCertList(self):
        """Return a list of Windows certificates by subject CN from the
        Root and TrustedPublisher stores in the form (key, name, sha1)."""
        stores = ["Root", "TrustedPublisher"]
        # Copy a version of certmgr.exe that takes command line
        # arguments
        self.xmlrpcSendFile("%s/distutils/certmgr.exe" %
                            (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")),
                            "c:\\certmgr.exe")
        r_cno = re.compile("=+Certificate # (\d+) =+")
        r_sect = re.compile("^(.*)::\s*$")
        r_cn = re.compile("\(CN\) (.+)")
        r_sha1 = re.compile("^([A-F0-9]{8} [A-F0-9]{8} [A-F0-9]{8} [A-F0-9]{8} [A-F0-9]{8})$")
        certs = []
        for store in stores:
            data = self.xmlrpcExec("c:\\certmgr.exe /c /s /r localmachine %s" % (store),
                                   returndata=True)
            certno = None
            subject = None
            sha1 = None
            section = None
            for line in data.splitlines():
                r = r_cno.search(line)
                if r:
                    # This is a new certificate starting
                    if certno:
                        # We've already got some details about the last one, but not all...
                        subject = subject is None and "(unknown)" or subject
                        certs.append((certno, subject, sha1))
                        subject = None
                        sha1 = None
                    certno = r.group(1)
                if certno:
                    r = r_sect.search(line)
                    if r:
                        section = r.group(1).strip()
                        continue
                    if section == "Subject":
                        r = r_cn.search(line)
                        if r:
                            subject = r.group(1)
                    elif section == "SHA1 Thumbprint":
                        r = r_sha1.search(line.strip())
                        if r:
                            sha1 = r.group(1)
                    if subject and sha1:
                        certs.append((certno, subject, sha1))
                        certno = None
                        subject = None
                        sha1 = None
            if certno:
                subject = subject is None and "(unknown)" or subject
                certs.append((certno, subject, sha1))

        return certs

    def increaseServiceStartTimeOut(self):
        # CA-56951 - increase the windows timeout for starting a service

        self.winRegAdd("HKLM",
                       "SYSTEM\\CurrentControlSet\\Control",
                       "ServicesPipeTimeout",
                       "DWORD",
                       600000)

    def getDomid(self):
        return self.host.getDomid(self)

    def getDomainType(self):
        """Get the domain type (hvm or linux) of a running VM"""
        vm = self.host.xenstoreRead("/local/domain/%u/vm" %
                                    (self.getDomid()))
        ostype = self.host.xenstoreRead("%s/image/ostype" % (vm))
        return ostype

    def getDomainFlags(self):
        """Get the domain flags (acpi, apic, ...) of a running VM"""
        data = self.host.execdom0("xm list --long %u" % (self.getDomid()))
        reply = []
        if re.search("acpi\s+1", data):
            reply.append("acpi")
        if re.search("apic\s+1", data):
            reply.append("apic")
        if re.search("pae\s+1", data):
            reply.append("pae")
        return reply

    def installVendor(self,
                      distro,
                      repository,
                      method,
                      config,
                      pxe=True,
                      extrapackages=None,
                      options={},
                      start=True):
        if re.search("sles|suse|sled", distro):
            self.installSLES(distro,
                             repository,
                             method,
                             config,
                             pxe=pxe,
                             extrapackages=extrapackages,
                             options=options,
                             start=start)
        elif re.search("debian|ubuntu", distro):
            self.installDebian(distro,
                               repository,
                               method,
                               config,
                               pxe=pxe,
                               extrapackages=extrapackages,
                               options=options,
                               start=start)
        elif re.search("solaris", distro):
            self.installSolaris(distro,
                                repository,
                                method,
                                config,
                                pxe=pxe,
                                extrapackages=extrapackages,
                                options=options,
                                start=start)
        else:
            self.installRHEL(distro,
                             repository,
                             method,
                             config,
                             pxe=pxe,
                             extrapackages=extrapackages,
                             options=options,
                             start=start)

    def installSolaris(self,
                       distro,
                       repository,
                       method,
                       config,
                       pxe,
                       extrapackages=None,
                       options={},
                       start=True):
        """Network install of HVM Solaris into this guest."""

        #PR-1089: solaris must not use the viridian flag
        if re.search("viridian: true", self.paramGet("platform")):
            raise xenrt.XRTFailure("Solaris guest must not have "
                                   "viridian flag enabled")

        pxefile=None
        grubfile=None
        pxeb=None
        vifname, bridge, mac, c = self.vifs[0]

        if pxe:
            self.enablePXE(True)
            self.paramSet("HVM-boot-params-order", "ndc")

            #build new Solaris jumpstart files for unattended installation
            webdir = xenrt.WebDirectory()
            datadir = "%s/data/jumpstart" % (xenrt.TEC().lookup("XENRT_BASE"))
            nfsdir = xenrt.NFSDirectory()
            configdir = nfsdir.getMountURL("")

            amd64_infix = ""
            # TODO: there's a tftpd/grub error when transmitting the large >130MB miniroot
            # of solaris-64 during first boot over network. Disabling it for now until the
            # reason is completely understood. See also http://opensolaris.org/jive/thread.jspa?threadID=120197
            # This comment causes the installer to be 32-bits, but it will install a 64-bit solaris if requested
            #if (self.arch == "x86-64"): amd64_infix = "amd64/" # = "$ISADIR/"

            def publishToNfs(cfgfilename):
                filename_config_tar = "%s/%s" % (datadir, cfgfilename)
                nfsdir.copyIn(filename_config_tar)
                url_config_tar = nfsdir.getMountURL(os.path.basename(filename_config_tar))

            publishToNfs("rules.ok")
            publishToNfs("sysidcfg")
            publishToNfs("preinstall.sh")

            if method == "CDROM" or method == "NFS":
                # use installation from scratch
                publishToNfs("any_machine")
            else: # method == HTTP,FTP,etc
                # use flar archive method
                rpm_source=re.search(r'(.*://)?(.+)',repository).group(2)
                flar_url = "%s://anonymous:anonymous@%s/../flar/solaris10u9.flar" % (method, rpm_source)
                filename_profile = "any_machine"
                f_profile = file("%s/%s_flar" % (datadir, filename_profile), "r")
                pdat = f_profile.read()
                f_profile.close()
                pdat = string.replace(pdat, "%%ARCHIVE_LOCATION%%", "%s" % flar_url)
                filename_log_profile = "%s/%s" % (xenrt.TEC().getLogdir(),filename_profile)
                f_logdir_profile = file(filename_log_profile, "w")
                f_logdir_profile.write(pdat)
                f_logdir_profile.close()
                nfsdir.copyIn(filename_log_profile)
                url_profile = nfsdir.getMountURL(os.path.basename(filename_log_profile))

            filename_postinstall = "postinstall.sh"
            f_postinstall = file("%s/%s-%s" % (datadir, filename_postinstall, self.arch), "r")
            ay = f_postinstall.read()
            f_postinstall.close()
            vars = {}
            signaldir = nfsdir.getMountURL("")
            vars["SIGNALDIR"] = signaldir
            vars["EXTRAPOSTINSTALL"] = ""

            for v in vars.keys():
                ay = string.replace(ay, "%%%s%%" % (v), vars[v])
            filename_log_postinstall = "%s/%s" % (xenrt.TEC().getLogdir(),filename_postinstall)
            f_logdir_postinstall = file(filename_log_postinstall, "w")
            f_logdir_postinstall.write(ay)
            f_logdir_postinstall.close()
            nfsdir.copyIn(filename_log_postinstall)
            url_postinstall = nfsdir.getMountURL(os.path.basename(filename_log_postinstall))

            # build jumpstart config files
            self.password = xenrt.TEC().lookup("ROOT_PASSWORD")
            if method == "CDROM":
                # Solaris only installs via CDROM booting either with cdrom or pxelinux, not pxegrub
                pxeb = xenrt.PXEBoot(remoteNfs=self.getHost().lookup("REMOTE_PXE", None))
                pxebootdir = pxeb.makeBootPath("")
                pxecfg = pxeb.addEntry("install", default=1, boot="linux")
                pxecfg.linuxSetKernel("mboot.c32")
                pxecfg.linuxArgsKernelAdd("%sboot/multiboot" % pxebootdir)
                pxecfg.linuxArgsKernelAdd("kernel/%sunix" % amd64_infix)
                pxecfg.linuxArgsKernelAdd("- install nowin dhcp")
                pxecfg.linuxArgsKernelAdd("-B install_config=%s,sysid_config=%s,install_media=cdrom" % (configdir,configdir))
                pxecfg.linuxArgsKernelAdd("---")
                pxecfg.linuxArgsKernelAdd("%sboot/%sx86.miniroot" % (pxebootdir,amd64_infix))
                pxefile = pxeb.writeOut(None, forcemac=mac)
            else:

                def resolvNfs(nfsname):
                    # work around dhcp server not providing proper nfs server settings sometimes
                    srvname,srvpath = nfsname.split(":")
                    srvip=os.popen("ping '%s' -n -c 1|grep '64 bytes'|awk '{print $4}'|sed 's/://'"%srvname).readline().strip()
                    nfsip="%s:%s" % (srvip,srvpath)
                    xenrt.TEC().logverbose("Resolving %s->%s" % (nfsname,nfsip))
                    return nfsip

                # Solaris needs pxegrub to install over NFS/HTTP/FTP
                installdir = xenrt.getLinuxRepo(distro,self.arch,"NFS")
                installdir = resolvNfs(installdir)
                configdir = resolvNfs(configdir)
                repository_http = xenrt.getLinuxRepo(distro,self.arch,"HTTP")
                pxebootdir_template = "%s/boot.tar.bz2" % repository_http
                # installation from a repo only available in Solaris via NFS
                if method != "NFS": installdir = configdir

                # Construct a PXE target.
                pxeb = xenrt.PXEGrubBoot(boottar=pxebootdir_template)
                pxebootdir = pxeb.makeBootPath("")
                pxecfg = pxeb.addEntry("Unattended Installation of Solaris over %s (%s)" % (method,self.arch),default=0,boot="grub")
                pxecfg.grubSetKernel("%sboot/multiboot kernel/%sunix - install nowin dhcp -B install_config=%s,sysid_config=%s,install_media=%s" % (pxebootdir,amd64_infix,configdir,configdir,installdir))
                pxecfg.grubArgsKernelAdd("%sboot/%sx86.miniroot" % (pxebootdir,amd64_infix))
                (pxefile,grubfile) = pxeb.writeOut(None, mac)

        if not start:
            return

        self.lifecycleOperation("vm-start")

        # Next time we boot normally
        if pxe:
            self.enablePXE(False)
        self.paramSet("HVM-boot-params-order", "c")

        # Get the guest address during installation
        if self.reservedIP:
            self.mainip = self.reservedIP
        else:
            self.mainip = self.host.arpwatch(bridge, mac, timeout=1800)
        if not self.mainip:
            raise xenrt.XRTFailure("Did not find an IP address")

        if pxe:
            # When using pxe, we are able to send a signal to the VM indicating
            # where it should write back indicating a successful install.
            # Wait for notification that the install has finished
            # (This happens after the installer has booted into
            # the newly installed guest)
            if xenrt.TEC().lookup("EXTRA_TIME", False, boolean=True):
                installtime = 10800
            else:
                installtime = 7200
                xenrt.waitForFile("%s/.xenrtsuccess" % (nfsdir.path()),
                                  installtime,
                                  desc="Vendor install")
        else:
            # sleep a few minutes while the non-pxe installation runs
            xenrt.sleep(600)

        # we now can delete the pxe configs
        if pxefile is not None: os.unlink(pxefile)
        if grubfile is not None: os.unlink(grubfile)
        if pxeb is not None: pxeb.remove()

        # Solaris reboots after the first-boot, watch for the ARP of the
        # new address
        if self.reservedIP:
            self.mainip = self.reservedIP
        else:
            self.mainip = self.host.arpwatch(bridge, mac, timeout=1800)
        if not self.mainip:
            raise xenrt.XRTFailure("Did not find an IP address on "
                                   "second boot")

        self.waitForSSH(7200, desc="Post installation reboot")
        xenrt.sleep(60)

        # check if the installed Solaris guest is running with PV drivers
        # as expected
        self.checkPVDevices()

        try:
            self.execguest("/usr/sbin/poweroff",timeout=60)
        except:
            pass
        self.poll("DOWN", timeout=240)


    def installSLES(self,
                    distro,
                    repository,
                    method,
                    config,
                    pxe,
                    extrapackages=None,
                    options={},
                    start=True):
        """Network install of HVM SLES into this guest."""
        nfsdir = xenrt.NFSDirectory()
        vifname, bridge, mac, c = self.vifs[0]
        # Build an autoyast file.
        ks=SLESAutoyastFile(distro,
                            nfsdir.getMountURL(""),
                            maindisk="hda",
                            installOn=xenrt.HypervisorType.xen,
                            password=self.password,
                            pxe=pxe,
                            method=method,
                            ethDevice="eth0",
                            extraPackages=extrapackages,
                            kickStartExtra=None,
                            ossVG=False)
        ay=ks.generate()
        filename = "%s/autoyast.xml" % (xenrt.TEC().getLogdir())
        f=file(filename,"w")
        for line in ay.splitlines():
            f.write("%s\n" % (line))
        f.close()


        # Make autoyast file available over HTTP.
        webdir = xenrt.WebDirectory()
        webdir.copyIn(filename)
        url = webdir.getURL(os.path.basename(filename))

        if pxe:
            # Pull boot files from HTTP repository.
            fk = xenrt.TEC().tempFile()
            fr = xenrt.TEC().tempFile()
            if self.arch=="x86-64":
                xenrt.getHTTP("%s/boot/x86_64/loader/linux" % (repository), fk)
                xenrt.getHTTP("%s/boot/x86_64/loader/initrd" % (repository), fr)
            else:
                xenrt.getHTTP("%s/boot/i386/loader/linux" % (repository), fk)
                xenrt.getHTTP("%s/boot/i386/loader/initrd" % (repository), fr)

        if pxe:
            # HVM PXE install
            self.enablePXE()
            if method != "HTTP":
                raise xenrt.XRTError("%s PXE install not supported" %
                                     (method))

            # Construct a PXE target.
            pxe = xenrt.PXEBoot(remoteNfs=self.getHost().lookup("REMOTE_PXE", None))
            pxe.copyIn(fk, target="vmlinuz")
            pxe.copyIn(fr, target="initrd.img")
            pxecfg = pxe.addEntry("install", default=1, boot="linux")
            pxecfg.linuxSetKernel("vmlinuz")
            pxecfg.linuxArgsKernelAdd("initrd=%s" %
                                      (pxe.makeBootPath("initrd.img")))
            pxecfg.linuxArgsKernelAdd("ramdisk_size=65536")
            pxecfg.linuxArgsKernelAdd("autoyast=%s" % (url))
            lh = xenrt.TEC().lookup("SLES_LOGHOST", None)
            if lh:
                pxecfg.linuxArgsKernelAdd("loghost=%s" % (lh))
            pxecfg.linuxArgsKernelAdd("showopts")
            pxecfg.linuxArgsKernelAdd("netdevice=%s" % ("eth0"))
            pxecfg.linuxArgsKernelAdd("install=%s" % (repository))
            pxefile = pxe.writeOut(None, forcemac=mac)
            pfname = os.path.basename(pxefile)
            xenrt.TEC().copyToLogDir(pxefile,target="%s.pxe.txt" % (pfname))
            # XRT-2259 Check the kernel args will work
            kargs = pxecfg.linuxGetArgsKernelString()
            if len(kargs) > 255:
                raise xenrt.XRTError("SLES kernel args string is too long",
                                     "%u chars: %s" % (len(kargs), kargs))
        else:
            if method == "NFS" and repository[0:3] != 'nfs':
                self.paramSet("other-config-install-repository",
                              "nfs://%s" % (repository))
            else:
                self.paramSet("other-config-install-repository", repository)
            bootparams = "console=ttyS0 xencons=ttyS autoyast=%s showopts " \
                         "netdevice=%s" % (url, "eth0")
            bootparams = bootparams + " netsetup=dhcp"
            lh = xenrt.TEC().lookup("SLES_LOGHOST", None)
            if lh:
                bootparams += " loghost=%s" % (lh)
            self.setBootParams(bootparams)

        if not start:
            return

        self.lifecycleOperation("vm-start")

        # Get the guest address during installation
        if self.reservedIP:
            self.mainip = self.reservedIP
        else:
            self.mainip = self.host.arpwatch(bridge, mac, timeout=1800)
        if not self.mainip:
            raise xenrt.XRTFailure("Did not find an IP address")

        # Next time we boot normally
        if pxe:
            self.enablePXE(False)
            xenrt.sleep(120)
            os.unlink(pxefile)

        # Wait for notification that the install has finished
        # (This happens after the installer has booted into
        # the newly installed guest)
        if xenrt.TEC().lookup("EXTRA_TIME", False, boolean=True):
            installtime = 10800
        else:
            installtime = 7200
        xenrt.waitForFile("%s/.xenrtsuccess" % (nfsdir.path()),
                          installtime,
                          desc="Vendor install")

        # SLES reboots after the first-boot, watch for the ARP of the
        # new address
        if re.search(r"/sbin/reboot",ay):
            if self.reservedIP:
                self.mainip = self.reservedIP
            else:
                self.mainip = self.host.arpwatch(bridge, mac, timeout=1800)
            if not self.mainip:
                raise xenrt.XRTFailure("Did not find an IP address on "
                                       "second boot")

        self.waitForSSH(1800, desc="Post installation reboot")
        xenrt.sleep(30)
        try:
            self.execguest("/sbin/poweroff")
        except:
            pass
        self.poll("DOWN", timeout=240)

    def installRHEL(self,
                    distro,
                    repository,
                    method,
                    config,
                    pxe=True,
                    extrapackages=None,
                    options={},
                    start=True):
        """Network install of HVM RHEL into this guest."""
        # Create an NFS directory for the installer to signal completion
        nfsdir = xenrt.NFSDirectory()
        vifname, bridge, mac, c = self.vifs[0]

        if pxe:
            ethDevice = string.replace(vifname, "nic", "eth")
            if self.host.productType == "esx":
                maindisk="sda"
            else:
                maindisk="hda"
                if distro:
                    m = re.match("(rhel|centos|oel|sl)[dw]?(\d)\d*", distro)
                    if (m and int(m.group(2)) >= 6) or distro.startswith("fedora"):
                        maindisk="xvda"
        else:
            ethDevice = vifname
            maindisk = options["maindisk"]

        bootDiskFS = xenrt.TEC().lookup("BOOTDISKFS", "ext4")
                      
        # Build a kickstart file.
        ksf=RHELKickStartFile(distro,
                              maindisk,
                              nfsdir.getMountURL(""),
                              vifs=self.vifs,
                              password=self.password,
                              host=self.host,
                              installOn=xenrt.HypervisorType.xen,
                              method=method,
                              repository=repository,
                              arch=self.arch,
                              bootDiskSize=500,
                              bootDiskFS=bootDiskFS,
                              ethDevice=ethDevice,
                              pxe=pxe,
                              extraPackages=extrapackages,
                              ossVG=False)
        ks=ksf.generate()
        vifname, bridge, mac, c = self.vifs[0]
        filename = "%s/kickstart.cfg" % (xenrt.TEC().getLogdir())
        f = file(filename, "w")
        for line in ks.splitlines():
            if options.has_key("nolvm") and (line[0:8] == "volgroup" or
                                             line[0:6] == "logvol" or
                                             line[0:7] == "part pv"):
                continue
            f.write("%s\n" % (line))
            if options.has_key("nolvm") and line[0:10] == "part /boot":
                swapsize = int(xenrt.TEC().lookup("GUEST_SWAP_SIZE", 512))
                if options.has_key("vbdsize"):
                    vbdsize = options["vbdsize"]
                else:
                    vbdsize = 8192
                f.write("part swap --fstype swap --size=%u "
                        "--ondisk=%s\n" % (swapsize, maindisk))
                f.write("part / --fstype \"ext3\" --size=%u "
                        "--ondisk=%s\n" % (vbdsize - swapsize - 200,
                                           maindisk))
        f.close()
        nfsdir.copyIn(filename)
        h, p = nfsdir.getHostAndPath("kickstart.cfg")

        cleanupdir = None
        inosreboot = False

        if pxe and method == "CDROM":
            xenrt.TEC().logverbose("RHEL HVM CD installation")
            # We need to put the answerfile where the guest can reach it
            # The only thing we know is the MAC, so we have to use that
            path = "%s/%s" % (xenrt.TEC().lookup("GUESTFILE_BASE_PATH"), mac.lower().replace(":",""))
            cleanupdir = path
            try:
                os.makedirs(path)
            except:
                pass
            xenrt.rootops.sudo("chmod -R a+w %s" % path)
            xenrt.command("rm -f %s/kickstart.stamp" % path)
            shutil.copyfile(filename, "%s/kickstart" % path)
            pxe = False
            inosreboot = True
        elif pxe:
            # HVM PXE install
            self.enablePXE()
            if method != "HTTP":
                raise xenrt.XRTError("%s PXE install not supported" %
                                     (method))
            # Pull boot files from HTTP repository
            fk = xenrt.TEC().tempFile()
            fr = xenrt.TEC().tempFile()
            xenrt.getHTTP("%s/isolinux/vmlinuz" % (repository),fk)
            xenrt.getHTTP("%s/isolinux/initrd.img" % (repository),fr)

            # Construct a PXE target
            pxe = xenrt.PXEBoot(remoteNfs=self.getHost().lookup("REMOTE_PXE", None))
            pxe.copyIn(fk, target="vmlinuz")
            pxe.copyIn(fr, target="initrd.img")
            pxecfg = pxe.addEntry("install", default=1, boot="linux")
            pxecfg.linuxSetKernel("vmlinuz")
            pxecfg.linuxArgsKernelAdd("ks=nfs:%s:%s" % (h, p))
            pxecfg.linuxArgsKernelAdd("ksdevice=%s" % (ethDevice))
            pxecfg.linuxArgsKernelAdd("initrd=%s" %
                                      (pxe.makeBootPath("initrd.img")))

            if distro.startswith("oel7") or distro.startswith("centos7") or distro.startswith("rhel7") or distro.startswith("sl7") or distro.startswith("fedora"):
                pxecfg.linuxArgsKernelAdd("inst.repo=%s" % repository)
                pxecfg.linuxArgsKernelAdd("console=tty0")
                pxecfg.linuxArgsKernelAdd("console=hvc0")
            else:
                pxecfg.linuxArgsKernelAdd("console=tty0")
                pxecfg.linuxArgsKernelAdd("console=ttyS0,9600n8")
                pxecfg.linuxArgsKernelAdd("serial")
                pxecfg.linuxArgsKernelAdd("root=/dev/ram0")
            xeth, xbridge, mac, xip = self.vifs[0]
            pxefile = pxe.writeOut(None, forcemac=mac)
            pfname = os.path.basename(pxefile)
            xenrt.TEC().copyToLogDir(pxefile,target="%s.pxe.txt" % (pfname))
        elif options.has_key("OSS_PV_INSTALL"):
            if method != "HTTP":
                raise xenrt.XRTError("%s install not supported" %
                                     (method))
            # Pull boot files from HTTP repository and send to host
            fk = xenrt.TEC().tempFile()
            fr = xenrt.TEC().tempFile()
            if self.host.productType in ["xenserver", "unknown"]:
                xenrt.getHTTP("%s/images/xen/vmlinuz" % (repository),fk)
                xenrt.getHTTP("%s/images/xen/initrd.img" % (repository),fr)
            else:
                xenrt.getHTTP("%s/images/pxeboot/vmlinuz" % (repository),fk)
                xenrt.getHTTP("%s/images/pxeboot/initrd.img" % (repository),fr)

            hdir = self.host.hostTempDir()
            try:
                sftp = self.host.sftpClient()
                sftp.copyTo(fk, "%s/vmlinuz" % (hdir))
                sftp.copyTo(fr, "%s/initrd.img" % (hdir))
            finally:
                sftp.close()
            if self.host.productType == "kvm":
                self.host.execdom0("chmod 777 -R %s" % (hdir, ))
            self.kernel = "%s/vmlinuz" % (hdir)
            self.initrd = "%s/initrd.img" % (hdir)
            self.extra = "ks=nfs:%s:%s ksdevice=%s" % (h, p, vifname)
            if self.host.productType == "kvm":
                self._setPVBoot(self.kernel, self.initrd, self.extra)
        else:
            if not (re.search("rhel41", distro) or \
                    re.search("rhel44", distro)):
                if method == "NFS" and repository[0:3] != 'nfs':
                    self.paramSet("other-config-install-repository",
                                  "nfs:%s" % (repository))
                else:
                    self.paramSet("other-config-install-repository", repository)

            # Paravirtual vendor install
            self.setBootParams("ks=nfs:%s:%s ksdevice=%s" %
                               (h, p, vifname))

        if not start:
            return;

        # Start the VM to install from CD
        xenrt.TEC().progress("Starting VM %s for kickstart install" %
                             (self.name))
        self.lifecycleOperation("vm-start")

        #get current DomId
        domid = self.getDomid()

        # RHEL 6.3 derivatives are fussy about hardware, but don't support the kickstart unsupported_harware command
        # We'll see if the hardware unsupported error comes up, and send a CRLF if it does

        if distro in ["rhel63", "oel63", "centos63"]:
            xenrt.sleep(120)
            if re.search("is not supported", self.host.guestConsoleLogTail(self.getDomid())):
                self.writeToConsole("\r\n")

        # Monitor for installation complete
        if xenrt.TEC().lookup("EXTRA_TIME", False, boolean=True):
            installtime = 7200
        else:
            installtime = 3600
        try:
            xenrt.waitForFile("%s/.xenrtsuccess" % (nfsdir.path()),
                              installtime,
                              desc="Vendor install")
        except xenrt.XRTFailure, e:
            self.checkHealth(noreachcheck=True)
            # Check for CA-18131-like symptom
            self.checkFailuresinConsoleLogs(domid=domid)
            raise

        if os.path.exists("%s/rpmupgrade.log" % (nfsdir.path())):
            xenrt.TEC().copyToLogDir("%s/rpmupgrade.log" % (nfsdir.path()))
        if pxe:
            # Cancel PXE booting for the new guest
            self.enablePXE(False)
            pxe.remove()
        if options.has_key("OSS_PV_INSTALL"):
            # Revert to pygrub booting
            self.kernel = None
            self.initrd = None
            self.extra = None
            self.bootloader = "/usr/bin/pygrub"
            if self.host.productType == "kvm":
                self._setPVBoot(self.kernel, self.initrd, self.extra)
                self._setBoot("hd")
        if xenrt.TEC().lookup("DEBUGSTOP_CA6404", False, boolean=True):
            raise xenrt.XRTError("CA-6404 debug stop")

        if pxe or inosreboot:
            # Just wait for the reboot that kickstart performed
            pass
        elif options.has_key("OSS_PV_INSTALL"):
            # Do not reboot - we want to pick up config file changes
            xenrt.sleep(60)
            if self.host.productType == "kvm":
                force = True
            else:
                force = False
            self.lifecycleOperation("vm-shutdown", force=force)
            self.poll("DOWN")
            xenrt.sleep(10)
            self.lifecycleOperation("vm-start")
        else:
            xenrt.sleep(60)
            self.lifecycleOperation("vm-reboot")

        if xenrt.TEC().lookup("ARPWATCH_PRIMARY", False, boolean=True):
            mac, ip, bridge = self.getVIF(bridge=self.host.getPrimaryBridge())
        goes = 1
        while True:
            try:
                goes = goes - 1
                if self.reservedIP:
                    self.mainip = self.reservedIP
                else:
                    self.mainip = self.host.arpwatch(bridge, mac, timeout=600)
                if not self.mainip:
                    raise xenrt.XRTFailure("Did not find an IP address")
                break
            except xenrt.XRTException, e:
                if goes == 0:
                    raise
                xenrt.TEC().warning("Retrying boot after failed arpwatch")
                self.lifecycleOperation("vm-reboot", force=True)
        self.waitForSSH(1800, desc="Post installation reboot")

        # Shutdown the VM. This is to match Linux behaviour where
        # install does not necessarily mean start.
        if pxe:
            # No guest agent, so do a normal shutdown
            xenrt.sleep(30)
            try:
                self.execguest("/sbin/poweroff")
            except:
                pass
        else:
            self.lifecycleOperation("vm-shutdown")
        self.poll("DOWN", timeout=240)

        if cleanupdir:
            shutil.rmtree(cleanupdir)

    def installDebian(self,
                      distro,
                      repository,
                      method,
                      config,
                      pxe,
                      extrapackages=None,
                      options={},
                      start=True):
        """Network install of Debian into this guest."""
        if method != "HTTP" and method != "CDROM":
            raise xenrt.XRTError("%s install not supported" % (method))

        vifname, bridge, mac, c = self.vifs[0]
        preseedfile = "preseed-%s.cfg" % (self.getName())
        filename = "%s/%s" % (xenrt.TEC().getLogdir(), preseedfile)

        # Generate a config file
        arch=self.arch
        ps=DebianPreseedFile(distro,
                             repository,
                             filename,
                             installOn=xenrt.HypervisorType.xen,
                             method=method,
                             password=self.password,
                             ethDevice="eth0",
                             extraPackages=extrapackages,
                             ossVG=False,
                             arch=arch)


        ps.generate()
        # Make config file available over HTTP.
        webdir = xenrt.WebDirectory()
        webdir.copyIn(filename)
        url = webdir.getURL(os.path.basename(filename))

        cleanupdir = None

        if pxe and method == "CDROM":
            xenrt.TEC().logverbose("debian HVM CD installation")
            # We need to put the answerfile where the guest can reach it
            # The only thing we know is the MAC, so we have to use that
            path = "%s/%s" % (xenrt.TEC().lookup("GUESTFILE_BASE_PATH"), mac.lower().replace(":",""))
            cleanupdir = path
            try:
                os.makedirs(path)
            except:
                pass
            xenrt.rootops.sudo("chmod -R a+w %s" % path)
            xenrt.command("rm -f %s/preseed.stamp" % path)
            shutil.copyfile(filename, "%s/preseed" % path)
            pxe = False
        elif pxe:
            xenrt.TEC().logverbose("Experimental debian pxe installation support")
            # HVM PXE install
            self.enablePXE(disableCD=True)
            if method != "HTTP":
                raise xenrt.XRTError("%s PXE install not supported" %
                                     (method))

            arch = "amd64" if "64" in self.arch else "i386"
            xenrt.TEC().logverbose("distro: %s | repository: %s | filename: %s" % (distro, repository, filename))
            m = re.search("ubuntu(.+)", distro)
            if m:
                release = m.group(1)
                if release == "1004":
                    _url = repository + "/dists/lucid/"
                elif release == "1204":
                    _url = repository + "/dists/precise/"
                elif release == "1404":
                    _url = repository + "/dists/trusty/"
                elif release == "devel":
                    _url = repository + "/dists/devel/"
                boot_dir = "main/installer-%s/current/images/netboot/ubuntu-installer/%s/" % (arch, arch)
            else:
                if distro == "debian50":
                    release = "lenny"
                elif distro == "debian60":
                    release = "squeeze"
                elif distro == "debian70":
                    release = "wheezy"
                elif distro == "debian80":
                    release = "jessie"
                elif distro == "debiantesting":
                    release = "jessie"
                    self.special['debiantesting_upgrade'] = True
                _url = repository + "/dists/%s/" % (release)
                boot_dir = "main/installer-%s/current/images/netboot/debian-installer/%s/" % (arch, arch)
            
            # Pull boot files from HTTP repository
            fk = xenrt.TEC().tempFile()
            fr = xenrt.TEC().tempFile()
            xenrt.getHTTP(_url + boot_dir + "linux", fk)
            xenrt.getHTTP(_url + boot_dir + "initrd.gz", fr)

            # Construct a PXE target
            pxe = xenrt.PXEBoot(remoteNfs=self.getHost().lookup("REMOTE_PXE", None))
            pxe.copyIn(fk, target="linux")
            pxe.copyIn(fr, target="initrd.gz")
            pxecfg = pxe.addEntry("install", default=1, boot="linux")
            pxecfg.linuxSetKernel("linux")
            pxecfg.linuxArgsKernelAdd("vga=normal")
            pxecfg.linuxArgsKernelAdd("auto=true priority=critical")
            pxecfg.linuxArgsKernelAdd("interface=eth0")
            pxecfg.linuxArgsKernelAdd("url=%s" % (webdir.getURL(preseedfile)))
            pxecfg.linuxArgsKernelAdd("initrd=%s" %
                                      (pxe.makeBootPath("initrd.gz")))
            xeth, xbridge, mac, xip = self.vifs[0]
            pxefile = pxe.writeOut(None, forcemac=mac)
            pfname = os.path.basename(pxefile)
            xenrt.TEC().copyToLogDir(pxefile,target="%s.pxe.txt" % (pfname))
        else:
            if method == "CDROM":
                self.paramSet("other-config-install-repository", "cdrom")
            else:
                if self.host.productType == "kvm":
                    arch = "amd64" if "64" in self.arch else "i386"
                    release = re.search("Debian/(\w+)/", repository).group(1)
                    _url = repository + "/dists/%s/" % (release.lower(), )
                    boot_dir = "main/installer-%s/current/images/netboot/debian-installer/%s/" % (arch, arch)

                    fk = xenrt.TEC().tempFile()
                    fr = xenrt.TEC().tempFile()
                    xenrt.getHTTP(_url + boot_dir + "linux", fk)
                    xenrt.getHTTP(_url + boot_dir + "initrd.gz", fr)
                    hdir = self.host.hostTempDir()
                    try:
                        sftp = self.host.sftpClient()
                        sftp.copyTo(fk, "%s/linux" % (hdir, ))
                        sftp.copyTo(fr, "%s/initrd.gz" % (hdir, ))
                    finally:
                        sftp.close()
                    self.host.execdom0("chmod 777 -R %s" % (hdir, ))
                    self.kernel = "%s/linux" % (hdir, )
                    self.initrd = "%s/initrd.gz" % (hdir, )
                else:
                    self.paramSet("other-config-install-repository", repository)

        # A valid hostname may contain only the numbers 0-9, the lowercase
        # letters a-z, and the minus sign. It must be between 2 and 63
        # characters long, and may not begin or end with a minus sign.

        hostname = self.getName().lower()
        hostname = re.sub("[^a-z0-9\-]", "", hostname)
        hostname = re.sub("^-", "", hostname)
        hostname = re.sub("-$", "", hostname)

        if len(hostname) < 2:
            hostname = hostname + "xx"

        bootparams = "auto=true priority=critical " \
                     "console-keymaps-at/keymap=us preseed/locale=en_US " \
                     "auto-install/enable=true " \
                     "netcfg/choose_interface=eth0 " \
                     "hostname=%s domain=localdomain url=%s" % (hostname, url)

        if self.host.productType.lower() == "kvm" and method != "CDROM":
            self._setPVBoot(self.kernel, self.initrd, bootparams)
        elif self.host.productType.lower() in ("esx", "hyperv"):
            pass
        else:
            self.setBootParams(bootparams)

        if not start:
            return
        step("Starting the guest for automated install")
        # Start the install
        self.lifecycleOperation("vm-start")

        # Get the current domid
        domid = self.getDomid()
        # Get the guest address during installation
        if self.reservedIP:
            self.mainip = self.reservedIP
        else:
            self.mainip = self.host.arpwatch(bridge, mac, timeout=1800)
        if not self.mainip:
            raise xenrt.XRTFailure("Did not find an IP address")

        # Wait for the VM to power down - this means the install has finished
        if xenrt.TEC().lookup("DEBIAN_INSTALL_TIMEOUT", None):
            installtime = int(xenrt.TEC().lookup("DEBIAN_INSTALL_TIMEOUT"))
        elif xenrt.TEC().lookup("EXTRA_TIME", False, boolean=True):
            installtime = 10800
        else:
            installtime = 5400
        try:
            self.poll("DOWN", timeout=installtime)
        except xenrt.XRTFailure, e:
            if "Timed out" in e.reason:
                self.checkHealth(noreachcheck=True)
                self.checkFailuresinConsoleLogs(domid=domid)
            raise

        if self.host.productType == "kvm":
            self._setPVBoot(None, None, None)
            self._setBoot("hd")

        if pxe:
            # Cancel PXE booting for the new guest
            self.enablePXE(False, disableCD=True)
            pxe.remove()
    
        if cleanupdir:
            shutil.rmtree(cleanupdir)


    def waitToReboot(self,timeout=3600):
        deadline = xenrt.util.timenow() + timeout
        startDomid = self.host.getDomid(self)
        while True:
            try:
                d = self.host.getDomid(self)
                if d != startDomid:
                    break
            except:
                pass
            now = xenrt.util.timenow()
            if now > deadline:
                raise xenrt.XRTFailure("Timed out waiting for reboot")

            xenrt.sleep(30)

    def preCloneTailor(self):
        # Tailor this guest to be clone-friendly - i.e. remove any MAC adddress
        # hardcodings
        if self.getState() == "DOWN":
            xenrt.TEC().logverbose("Starting %s to prepare for clone " %
                                   (self.getName()))
            self.start()
        GenericPlace.preCloneTailor(self)

    def startLiveMigrateLogger(self):
        try:
            # Start a ping in dom0 to check for VM downtime
            ip = IPy.IP(self.mainip)
            if ip.version() == 6:
                self.host.execdom0("ping6 -q %s > /tmp/%s_ping.log 2>&1 & echo $! > /tmp/%s_ping.pid" %
                               (self.mainip,self.name,self.name))
            else:
                self.host.execdom0("ping -q %s > /tmp/%s_ping.log 2>&1 & echo $! > /tmp/%s_ping.pid" %
                               (self.mainip,self.name,self.name))
            # Start the live migrate logger process
            # (scripts/remote/migratecheck.py)
            if self.windows:
                # Use XML-RPC
                # First we need to copy the script to the machine
                lsd = xenrt.TEC().lookup("LOCAL_SCRIPTDIR")
                self.xmlrpcSendFile("%s/remote/migratecheck.py" % (lsd),
                                    "c:\\migratecheck.py")
                # Now execute it
                self.xmlrpcStart("c:\\migratecheck.py c:\\migrate.log "
                                       "c:\\migrate.pid")
            else:
                # Use SSH (we assume remote scriptdir exists)
                rsd = xenrt.TEC().lookup("REMOTE_SCRIPTDIR")
                self.execguest("%s/remote/migratecheck.py /migrate.log "
                               "/migrate.pid > /dev/null 2>&1 &" % (rsd))
        except Exception, e:
            xenrt.TEC().warning("Exception in startLiveMigrateLogger: " +
                                str(e))

    def stopLiveMigrateLogger(self, isReturn=None):
        try:
            # Stop the ping (Slightly nasty, as it may kill legitimate
            # ping processes, but there are unlikely to be any)
            self.host.execdom0("kill -s SIGINT `cat /tmp/%s_ping.pid` || true" % (self.name))
            # View the log file
            data = self.host.execdom0("cat /tmp/%s_ping.log" % (self.name))
            lines = data.split("\n")
            for line in lines:
                m = re.match("(\d+) packets transmitted, (\d+) received",line)
                if m:
                    txd = int(m.group(1))
                    rxd = int(m.group(2))
                    lost = txd-rxd
                    if lost > 2:
                        xenrt.TEC().warning("Lost %u pings during live migrate" % (lost))
                    else:
                        xenrt.TEC().logverbose("Lost %u pings during live migrate" % (lost))
                    break
            # Stop the live migrate logger process, and see if it was actually
            # live
            if self.windows:
                # Use XML-RPC
                # Kill the process
                pid = string.strip(self.xmlrpcReadFile("c:\\migrate.pid"))
                self.xmlrpcKill(int(pid))
                # Now read the logfile
                log = self.xmlrpcReadFile("c:\\migrate.log")
                # Cleanup
                self.xmlrpcExec("del c:\\migrate.log")
                self.xmlrpcExec("del c:\\migrate.pid")
                self.xmlrpcExec("del c:\\migrate.py")
            else:
                # Use SSH
                pid = string.strip(self.execguest("cat /migrate.pid"))
                self.execguest("kill %s" % (pid))
                # Read the log file
                log = self.execguest("cat /migrate.log")
                # Cleanup
                self.execguest("rm /migrate.log")
                self.execguest("rm /migrate.pid")

            # Look at each entry, if the entry after it is more than 200ms away,
            # then this is most probably our migrate gap
            lines = log.split("\n")
            count = 0
            found = False
            for line in lines:
                if (count+2) == len(lines):
                    break
                count += 1
                secs = float(line.strip())
                next_secs = float(lines[count].strip())
                if (next_secs - secs) > 0.2:
                    found = True
                    downtime = next_secs - secs
                    xenrt.TEC().logverbose("Live migrate downtime ~%dms" %
                                           (int(downtime*1000)))
                    if downtime > 1:
                        xenrt.TEC().warning("Live migrate downtime > 1s!")
                        xenrt.TEC().appresult("LiveMigrate,%d" % (int(downtime*1000)))
                    if isReturn:
                           return float(downtime) # downtime in seconds.
            if not found:
                xenrt.TEC().logverbose("Live migrate downtime not visible in log, presumably <100ms")
                if isReturn:
                    return float(0) # no visible downtime noticed in live/storage migration.
        except Exception, e:
            xenrt.TEC().warning("Exception in stopLiveMigrateLogger: " + str(e))
            if isReturn:
                return float(-1) # error occured while migration.

    def enableHibernation(self):
        """Perform configuration actions on the VM to enable hibernation"""
        try:
            self.winRegAdd("HKCU",
                           "Software\\Policies\\Microsoft\\Windows\\"
                           "System\\Power",
                           "PromptPasswordOnResume",
                           "DWORD",
                           0)
            try:
                self.xmlrpcExec("powercfg.exe /GLOBALPOWERFLAG off /OPTION RESUMEPASSWORD")
            except:
                pass
        except:
            pass
        try:
            data = self.xmlrpcExec("powercfg.exe /HIBERNATE ON", returndata=True)
        except:
            data = ""
        if re.search(r"There is not enough space on the disk", data):
            raise xenrt.XRTError("Cannot hibernate: There is not enough "
                                 "space on the disk")

    def hibernate(self):
        """Hibernate the VM using Windows' own hibernation mechanism."""
        attempt = 0
        while True:
            try:
                # Ignore errors since we may get the connection
                # severed on the down
                self.xmlrpcStart("ping 127.0.0.1 -n 3 -w 1000\n"
                                 "rundll32.exe "
                                 "powrprof.dll,SetSuspendState")
            except:
                pass
            try:
                self.poll("DOWN", timeout=1200)
                break
            except Exception, e:
                try:
                    # See if the hibernate started, i.e. we can't ping
                    # the execdaemon.
                    self.checkReachable()
                except:
                    self.checkHealth(unreachable=True)
                    raise xenrt.XRTFailure("Hibernate didn't complete")
                self.check()
                if attempt == 2:
                    raise xenrt.XRTFailure("Hibernate didn't happen after 3 attempts")
                else:
                    xenrt.TEC().warning("Hibernate didn't seem to happen.")
                    attempt = attempt + 1
                    continue

    def forceMultiprocessorHALonSingleVCPU(self):
        """Force a Windows VM to use the Multiprocessor HAL on a single VCPU
        domain."""
        self.shutdown()
        self.cpuset(2)
        self.start()
        self.shutdown()
        self.cpuset(1)
        self.start()
        if not re.search("Multiprocessor",
                          self.xmlrpcExec("systeminfo",
                          returndata=True)):
            raise xenrt.XRTError("We don't seem to be using the "
                                 "SMP HAL.")

    def forceWindowsPAE(self):
        """Enable Windows PAE mode even if we have less than 4GB memory"""
        if not float(self.xmlrpcWindowsVersion()) > 5.99:
            self.xmlrpcAddBootFlag("/PAE")
            self.xmlrpcExec("type c:\\boot.ini")
            self.reboot()
        paeval = self.winRegLookup("HKLM",
                                   "SYSTEM\\CurrentControlSet\\"
                                   "Control\\Session Manager\\"
                                   "Memory Management",
                                   "PhysicalAddressExtension")
        if not paeval == 1:
            raise xenrt.XRTError("Tried to enable PAE but registry flag "
                                 "does not show it as enabled.")

    def installWindowsServicePack(self, skipIfNotNeeded=False):
        """Install a Windows service pack to bring the VM to level
        specified by self.distro."""
        # This is currently only implemented for 2008/Vista SP2.
        # Generalisation may be required in the future. TODO
        spexe = self.host.lookup(["SERVICE_PACKS", self.distro], None)
        if not spexe:
            if skipIfNotNeeded:
                # No service pack needed to get here
                return
            raise xenrt.XRTError("No service pack configured for %s" %
                                 (self.distro))

        # We may not yet have tailored - do this now because we need
        # to use the exec daemon
        if not self.tailored:
            self.tailor()

        # Format is "CDname pathToExe SPn"
        cdname, path, splevel = spexe.split()
        self.changeCD(cdname)
        xenrt.sleep(30)

        # Start the install
        domid = self.host.getDomid(self)
        self.xmlrpcStart("d:\\%s /forcerestart /unattend" % (path))

        # Wait for the VM to reboot
        deadline = xenrt.util.timenow() + 7200
        while True:
            try:
                d = self.host.getDomid(self)
                if d != domid:
                    break
            except:
                pass
            now = xenrt.util.timenow()
            if now > deadline:
                self.checkHealth()
                raise xenrt.XRTFailure("Timed out waiting for installer "
                                       "initiated reboot")
            xenrt.sleep(30)

        # Wait for the exec daemon
        self.waitForDaemon(1200, desc="Daemon connect after service pack install")
        xenrt.sleep(120)

        # Check we're in the right SP
        data = self.xmlrpcExec("systeminfo", returndata=True)
        if not (re.search("OS Version:.*%s" %
                          (splevel.replace("SP", "Service Pack ")),
                          data) or
                re.search("OS Version:.*%s" % (splevel), data)):
            raise xenrt.XRTError("VM not reporting the expected SP level",
                                 "Wanted %s" % (splevel))

    def getVncSnapshot(self, filename):
        """Get a VNC display snapshot of this VM."""
        return self.host.getVncSnapshot(self.getDomid(), filename)

    def sendVncKeys(self, keycodes):
        """Send the list of X11 keycodes to the VNC interface for this VM"""
        self.host.sendVncKeys(self.getDomid(), keycodes)

    def writeToConsole(self, str, retlines=0, cuthdlines=0):
        """Write str into this VM's main console stdin"""
        """and wait for retlines in stdout"""
        tty = self.host.xenstoreRead("/local/domain/%u/console/tty" % (self.getDomid()))
        if not tty:
            raise xenrt.XRTError("Could not find tty for domain",
                                  "Domain %u on %s" % (self.getDomid(), self.getName()))
        out = self.host.writeToConsole(self.getDomid(), str, tty=tty, retlines=retlines,cuthdlines=cuthdlines)
        return out

    def makeCooperative(self, cooperative):
        """Make a guest (un)cooperative to balloon requests"""
        if self.windows:
            # Use the PV driver FIST points
            if cooperative: value = 0
            else: value = 1
            self.host.xenstoreWrite("/local/domain/%s/FIST/balloon/inflation" %
                                    (self.getDomid()), value)
            self.host.xenstoreWrite("/local/domain/%s/FIST/balloon/deflation" %
                                    (self.getDomid()), value)
        else:
            if cooperative:
                # Set permissions back sensibly
                self.host.execdom0("xenstore-chmod /local/domain/%s/memory/target n0 r%s" %
                                   (self.getDomid(),self.getDomid()))
            else:
                # Restrict the domain from reading its memory target
                self.host.execdom0("xenstore-chmod /local/domain/%s/memory/target n0 n%s" %
                                   (self.getDomid(),self.getDomid()))

    def reparseVIFs(self):
        self.vifs = [ (nic, vbridge, mac, ip) for \
                      (nic, (mac, ip, vbridge)) in self.getVIFs().items() ]

    def deviceToNetworkName(self,device):

        nics = self.getVIFs()
        bridge = nics[device][2]
        network = self.host.bridgeToNetworkName(bridge)

        return network

    def disableRandomizeIdentifiers(self):

        if self.windows:
            self.xmlrpcExec("netsh interface ipv6 set global randomizeidentifiers=disabled")
            self.reboot()

    def getIPv6AutoConfAddress(self,device='eth0', link_local=False, routerPrefix=None):

        NICs = self.getVIFs()
        mac = NICs[device][0]
        interfaceIdentifier = xenrt.getInterfaceIdentifier(mac)

        if link_local:
            routerPrefix = 'fe80:0000:0000:0000:'
        elif routerPrefix is None:
            network = self.deviceToNetworkName(device)
            (routerPrefix, dhcp6Begin, dhcp6End) = self.host.getIPv6NetworkParams(nw=network)
            routerPrefix = routerPrefix.replace('::',':')

        autoConfAddr = routerPrefix + interfaceIdentifier
        return autoConfAddr

    def checkIsIPv6AdrressInRange(self,ipv6Addr,device='eth0'):

        if ipv6Addr.rfind('%') > 0:
            ipv6Addr = ipv6Addr.split('%')[0]

        ipv6 = IPy.IP(ipv6Addr)

        network = self.deviceToNetworkName(device)
        (routerPrefix, dhcp6Begin, dhcp6End) = self.host.getIPv6NetworkParams(nw=network)

        return (ipv6 >= IPy.IP(dhcp6Begin) and ipv6 <= IPy.IP(dhcp6End))



    def disableIPv4(self, restart=True):

        if self.ipv4_disabled:
            return

        if self.windows:
            try:
                self.xmlrpcExec("netsh interface ipv4 uninstall",ignoreHealthCheck=True)
            except:
                #Expects exception and it has to be ignored
                pass
            self.ipv4_disabled = True
            if restart: # Only applicable to Windows
                self.shutdown()
                self.start()
        else:
            #CHECKME: Disabling IPv4 for linux is broken (not persisted over reboot)
            for device in self.getVIFs().keys():
                self.execguest("ip -4 addr delete dev %s" % device)
            self.ipv4_disabled = True
            try:
                self.execguest("killall -9 dhclient")
            except:
                pass
            try:
                self.execguest("killall -9 dhclient3")
            except:
                pass

    def enableIPv4(self,deviceList=None):

        if self.windows:
            try:
                self.xmlrpcExec("netsh interface ipv4 install")
            except:
                #Expects exception and it has to be ignored
                pass
            self.shutdown()
            self.start()
        else:
            if deviceList:
                for device in deviceList:
                    self.execguest("dhclient %s" % device)
            else:
                vifs = self.getVIFs()
                for device in vifs:
                    self.execguest("dhclient %s" % device)

    def disableIPv6(self, reboot=True, deleteInterfaces=True):
        if self.windows:
            self.winRegAdd('HKLM', 'SYSTEM\\currentcontrolset\\services\\tcpip6\\parameters', 'DisabledComponents', 'DWORD', -1)
            
            if deleteInterfaces:
                try:
                    self.xmlrpcExec("REG DELETE \"HKLM\\SYSTEM\\currentcontrolset\\services\\tcpip6\\parameters\\interfaces\" /f")
                except:
                    pass #doesn't always exist
            
            if reboot:
                # Reboot the VM to disable IPv6
                self.reboot()
        else:
            raise xenrt.XRTError('disableIPv6 not implemented for non-windows guests')

    def disableVbscriptEngine(self, restart=True):
        if self.windows:
            self.xmlrpcExec("cd C:\\Windows\\System32")
            self.xmlrpcExec("takeown /f C:\\Windows\\System32\\vbscript.dll")
            self.xmlrpcExec("echo y| cacls C:\\Windows\System32\\vbscript.dll /G administrator:F")
            self.xmlrpcExec("rename vbscript.dll vbscript1.dll")
        else:
            raise xenrt.XRTError('disableVbscriptEngine not implemented for non-windows guests')

    def specifyStaticIPv6(self,device="eth0"):

        network = self.deviceToNetworkName(device)
        staticIpObj = xenrt.StaticIP6Addr(network)
        ipv6Addr = staticIpObj.getAddr()
        netmask,gateway = self.host.getIPv6SubnetMaskGateway(network)

        if self.windows:
            interfaces = self.xmlrpcExec("netsh interface show interface", returndata=True)

            res = re.findall("((Local Area Connection|Ethernet) *\d*)", interfaces, re.MULTILINE|re.DOTALL)

            if len(res) > 0:
                self.xmlrpcExec('netsh interface ipv6 set address "%s" %s' % (res[0][0], ipv6Addr))
            else:
                raise xenrt.XRTFailure("No Local Area connection was found, check network settings on VM")

            xenrt.sleep(10)
            try:
                self.xmlrpcExec("ping %s" % ipv6Addr)
            except:
                raise xenrt.XRTFailure("IPV6 address %s is not pingable" % ipv6Addr)
        else:
            self.execguest("echo '\n'iface %s inet6 static >> /etc/network/interfaces" % device)
            self.execguest("echo '    'address %s >> /etc/network/interfaces" % ipv6Addr)
            self.execguest("echo '    'netmask %s >> /etc/network/interfaces" % netmask)
            self.execguest("echo '    'gateway %s >> /etc/network/interfaces" % gateway)
            # Note that we change the IP before the reboot. This is fine for toolstacks that have an out of band soft reboot
            # mechanism, but may fail if we need to SSH to the guest to perform the reboot
            self.mainip = ipv6Addr
            self.reboot()
            xenrt.sleep(10)
            try:
                self.execguest("ping6 -c 3 %s" % ipv6Addr)
            except:
                raise xenrt.XRTFailure("IPV6 address %s is not pingable" % ipv6Addr)

        return staticIpObj

    def enableIPv6Dhcp(self):

        if not self.windows:
            raise xenrt.XRTError("Funcion not implemented for non-Windows guests")

        try:
            self._xmlrpc().enableDHCP6()
        except:
            pass
        if self.enlightenedDrivers:
            ipv6_addrs = self.getVIFs(also_ipv6=True)['eth0'][3]
            lst = filter(lambda x: self.checkIsIPv6AdrressInRange(x), ipv6_addrs)
            if lst:
                self.mainip = lst[0]
                return

        # If needed, check for the new IP in the controller log file
        mac = self.getVIFs()['eth0'][0]
        dhcpLogData = xenrt.rootops.sudo('grep %s /var/lib/dibbler/server-cache.xml; exit 0' % mac)
        log('DHCP log data found: "%s"' % dhcpLogData)
        reg = re.compile('<entry duid="(?:[0-9A-Fa-f][0-9A-Fa-f]:){8}%s">([0-9A-Fa-f:]+)<' % mac)
        match = reg.search(dhcpLogData)
        if not match:
            raise xenrt.XRTError("IPv6 address not found for MAC %s" % mac)
        ip6 = match.group(1)
        log('DHCP IPv6 address found: "%s"' % ip6 )
        # set up the new IPv6 address, so xmlrpc can work again
        self.mainip = ip6

        return

    def getDhcpIP6(self):
        # find out the DHCP IPv6 address
        command = "netsh interface ipv6 show address"
        data = self.xmlrpcExec(command, returndata=True)
        # match line like "Dhcp  Preferred  1h46m6s   46m6s fd06:7768:b9e5:8b50::3442"
        reg = re.compile(r'^Dhcp\s+\S+\s+\S+\s\S+\s+(\S+)', re.MULTILINE)
        match = reg.search(data)
        if not match:
            xenrt.TEC().logverbose("Command '%s' returned following output: \n%s" % (command, data) )
            raise xenrt.XRTFailure("IPv6 address not found. Check command output and regular expression used.")
        else:
            ip6 = match.group(1)
            return ip6

    def setUseIPv6(self):
        if not self.use_ipv6:
            self.mainip = self.getIPv6AutoConfAddress()
            self.use_ipv6 = True

    def getUseIPv6(self):
        return self.use_ipv6

    def setUseIPv4(self, address):
        if self.use_ipv6:
            self.mainip = address
            self.use_ipv6 = False

    def findGPUMake(self):

        gpuMake = ""
        xenrt.TEC().logverbose("Obtaining graphics card maker/model")
        self.xmlrpcSendFile("%s/distutils/devcon.exe" % (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")), "c:\\devcon.exe")
        self.xmlrpcExec("c:\\devcon find * > c:\\windows\\temp\\devcon.log")
        d = "%s/%s" % (xenrt.TEC().getLogdir(), self.getName())
        if not os.path.exists(d):
            os.makedirs(d)
        self.xmlrpcGetFile("c:\\windows\\temp\\devcon.log", "%s/devcon.log" % (d))
        gpuDetected = 0
        gpuPatterns = ["PCI.VEN_10DE.*(NVIDIA|VGA).*"   #nvidia pci vendor id
                        ,"PCI.VEN_1002.*(ATI|VGA).*"    #ati/amd pci vendor id
                        ,"PCI.VEN_102B.*(Matrox|VGA).*" #matrox  pci vendor id
                        ,"PCI.VEN.*Intel.*Graphics.*"   #intel pci vendor id
                       ]
        f = open("%s/devcon.log"%d)
        for line in f:
            if line.startswith("PCI"):
                xenrt.TEC().logverbose("devcon: %s" % line)
                for gpuPattern in gpuPatterns:
                    if re.search(gpuPattern,line) and not re.search(".*(Audio).*",line):
                        xenrt.TEC().logverbose("Found GPU device: %s" % line)
                        gpuDetected += 1
                        gpuMake = line
                        break
        f.close()
        if gpuDetected < 1:
            raise xenrt.XRTFailure("GPU not detected for vm %s" % (self.getName()))
        if gpuDetected > 1:
            raise xenrt.XRTFailure("More than 1 GPU detected for vm %s" % (self.getName()))

        return gpuMake

    def installIntelGPUDriver(self):
        """This function installs the Intel Iris and HD Graphics Driver on Windows guest 7/8/8.1"""

        xenrt.TEC().logverbose("Installing Intel Iris and HD Graphics Driver on guest %s" %
                                                                                self.getName())

        if not self.windows:
            raise xenrt.XRTError("Intel Iris and HD Graphics Driver is only available for Windows guests.")

        currentVersion = xenrt.TEC().lookup("INTEL_GPU_DRIVER_VERSION", None)
        if not currentVersion:
            raise xenrt.XRTError("The current Intel Iris and HD Graphics Driver version is not described")

        # Workaround, VM unrespnsive for a short time after booting to getArch()
        xenrt.sleep(60)

        tarBall = "intelgpudriver.tgz"
        if self.xmlrpcGetArch() == "amd64":
            fileName = "win64_%s.exe" % currentVersion
        else:
            fileName = "win32_%s.exe" % currentVersion

        urlPrefix = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "")
        url = "%s/intelgpudriver/%s" % (urlPrefix, fileName)
        installFile = xenrt.TEC().getFile(url)
        if not installFile:
            raise xenrt.XRTError("Failed to fetch Intel Iris and HD Graphics Driver from distmaster.")

        tempDir = xenrt.TEC().tempDir()
        xenrt.command("cp %s %s" % (installFile, tempDir))
        xenrt.command("cd %s && tar -cvf %s %s" %
                      (tempDir, tarBall, fileName))
        self.xmlrpcSendFile("%s/%s" % (tempDir,tarBall),"c:\\%s" % tarBall)

        self.xmlrpcExtractTarball("c:\\%s" % tarBall,"c:\\")
        vbScript = """
Set WshShell = WScript.CreateObject("WScript.Shell")
WScript.sleep 60000
WshShell.Run "cmd", 9
WScript.sleep 1000
WshShell.SendKeys "c:\%s -s"
WshShell.SendKeys "{ENTER}"
WScript.sleep 180000

WshShell.SendKeys "{ENTER}"
WScript.sleep 1000
WshShell.SendKeys "{LEFT}"
WshShell.SendKeys "{ENTER}"
WScript.sleep 1000
WshShell.SendKeys "{ENTER}"

WScript.sleep 180000

WshShell.SendKeys "{ENTER}"
WScript.sleep 1000
WshShell.SendKeys "{ENTER}"
""" % (fileName)
        self.xmlrpcWriteFile("c:\\vb.vbs",vbScript)
        returncode = self.xmlrpcExec("c:\\vb.vbs",
                                      level=xenrt.RC_OK, returnerror=False, returnrc=True,
                                      timeout = 600)
        # Wait for some time to settle down with driver installer.
        xenrt.sleep(30)

        if returncode == 0:
            xenrt.TEC().logverbose("Intel Iris and HD Graphics Driver installation successful")
            # Because of /noreboot option, the setup may require guest reboot.
            self.reboot()
        else:
            raise xenrt.XRTError("Intel Iris and HD Graphics Driver installation failed! (return code = %d)" %
                                                                                                    (returncode,))

    def installGPUDriver(self):


        if not self.windows:
            raise xenrt.XRTError("GPU driver is only available on windows guests.")

        xenrt.TEC().logverbose("Installing GPU driver on vm %s" % self.getName())

        if self.xmlrpcGetArch().endswith("64"):
            filename = xenrt.TEC().lookup("GPU_GUEST_DRIVER_X64",None)
        else:
            filename = xenrt.TEC().lookup("GPU_GUEST_DRIVER_X86",None)

        urlprefix = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "")
        url = "%s/gpuDriver/%s" % (urlprefix, filename)

        self.installNvidiaVGPUSignedDriver(filename, url)

    def __nvidiaX64GuestDriverName(self, driverType):
        X64_SIGNED_FILENAME = "332.83_grid_win8_win7_64bit_english.exe"
        X64_UNSIGNED_FILENAME = "WDDM_x64_332.83.zip"

        defaultFilename = X64_UNSIGNED_FILENAME
        if driverType == 0:
            defaultFilename = X64_SIGNED_FILENAME

        return xenrt.TEC().lookup("VGPU_GUEST_DRIVER_X64",
                                  default=defaultFilename)

    def __nvidiaX86GuestDriverName(self, driverType):
        X86_SIGNED_FILENAME = "332.83_grid_win8_win7_english.exe"
        X86_UNSIGNED_FILENAME = "WDDM_x86_332.83.zip"

        defaultFilename = X86_UNSIGNED_FILENAME
        if driverType == 0:
            defaultFilename = X86_SIGNED_FILENAME

        return xenrt.TEC().lookup("VGPU_GUEST_DRIVER_X86",
                                  default=defaultFilename)

    def requiredVGPUDriverName(self, driverType):
        if self.xmlrpcGetArch().endswith("64"):
            return self.__nvidiaX64GuestDriverName(driverType)
        else:
            return self.__nvidiaX86GuestDriverName(driverType)

    def installNvidiaVGPUDriver(self, driverType):
        driverName = self.requiredVGPUDriverName(driverType)

        urlprefix = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "")
        url = "%s/vgpudriver/vmdriver/%s" % (urlprefix, driverName)        

        if driverType == 0:
            self.installNvidiaVGPUSignedDriver(driverName, url)
        else:
            self.installNvidiaVGPUUnsignedDriver(driverName)

    def installNvidiaVGPUSignedDriver(self, filename, url):

        tarball = "drivers.tgz"
        xenrt.TEC().logverbose("Installing vGPU driver on vm %s" % (self.getName(),))

        # This is for windows only.
        if not self.windows:
            raise xenrt.XRTError("vGPU driver is only available on windows guests.")

        try:
            installfile = xenrt.TEC().getFile(url)
            if not installfile:
                raise xenrt.XRTError("Failed to fetch NVidia driver.")
            tempdir = xenrt.TEC().tempDir()
            xenrt.command("cp %s %s" % (installfile, tempdir))
            xenrt.command("cd %s && tar -cvf %s %s" %
                          (tempdir, tarball, filename))
            self.xmlrpcSendFile("%s/%s" % (tempdir,tarball),"c:\\%s" % tarball)

            self.xmlrpcExtractTarball("c:\\%s" % tarball,"c:\\")

            returncode = self.xmlrpcExec("c:\\%s /s /noreboot" % (filename),
                                          returnerror=False, returnrc=True,
                                          timeout = 600)

            # Wait some time to settle down the driver installer.
            xenrt.sleep(30)

            # Because of /noreboot option, if setup requires reboot, it returns 1.
            if returncode != 0:
                if returncode == 1:
                    self.reboot()
                elif returncode == -522190831:
                    raise xenrt.XRTError("NVidia driver installer failed to detect compatible hardware. (return code = %d)" % (returncode,))
                else:
                    raise xenrt.XRTError("NVidia driver installer failed to install. (return code = %d)" % (returncode,))

        except xenrt.XRTError as e:
            raise e

    def installNvidiaVGPUUnsignedDriver(self, filename):

        """
        Installing NVidia Graphics drivers onto vGPU enabled guest.
        """

        xenrt.TEC().logverbose("Installing vGPU driver on vm %s" % (self.getName(),))

        # This is for windows only.
        if not self.windows:
            raise xenrt.XRTError("vGPU driver is only available on windows guests.")

        # Downloading driver files.
        targetPath = self.tempDir() + "\\vgpudrivers"
        try:
            urlprefix = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "")
            url = "%s/vgpudriver/vmdriver/%s" % (urlprefix, filename)
            installfile = xenrt.TEC().getFile(url)
            if not installfile:
                raise xenrt.XRTError("Failed to fetch NVidia driver.")
            tempdir = xenrt.TEC().tempDir()
            xenrt.command("cp %s %s" % (installfile, tempdir))
            execpath = xenrt.command("cd %s && unzip %s | grep 'setup.exe'" % (tempdir, installfile), strip = True)
            execpath = execpath.replace("inflating: ", "")
            execbase = execpath.split("/")[0]
            execpath = execpath.replace("/", "\\")

            # Sending files as tarball
            tarball = "drivers.tgz"
            xenrt.command("tar -zcf %s/%s -C %s/%s ." % (tempdir, tarball, tempdir, execbase))
            self.xmlrpcExec("mkdir %s" % (targetPath,))
            self.xmlrpcExec("mkdir %s\\%s" % (targetPath, execbase))
            self.xmlrpcSendFile("%s/%s" % (tempdir, tarball), "%s\\%s\\%s" % (targetPath, execbase, tarball))
            self.xmlrpcExtractTarball("%s\\%s\\%s" % (targetPath, execbase, tarball), "%s\\%s" % (targetPath, execbase))

            # Prepare AutoIt3 to approve unsigned driver installation.
            au3path = targetPath + "\\approve_driver.au3"
            au3scr = """If WinWait ("Windows Security", "") Then
sleep (10000)
SendKeepActive("Windows Security")
sleep (1000)
send ("{DOWN}")
sleep (1000)
send ("{ENTER}")
EndIf
"""
            au3desktopmode = """send ("#r")
sleep (5000)
send ("{ESC}")
sleep (3000)
"""
            xenrt.TEC().logverbose("Windows distro: " + self.distro)
            if self.distro.lower().startswith("win") and int(self.distro[3]) >= 8:
                au3scr = au3desktopmode + au3scr
            if self.distro.lower().startswith("ws") and int(self.distro[2:4]) >= 12:
                    au3scr = au3desktopmode + au3scr

            self.xmlrpcWriteFile(au3path, au3scr)
            autoit = self.installAutoIt()
            # Wait security warning and approved it.
            self.xmlrpcStart("\"%s\" %s" % (autoit, au3path))
            xenrt.sleep(30);

            # Execute installer
            returncode = self.xmlrpcExec("%s\\%s /s /noreboot" % (targetPath, execpath), returnerror=False, returnrc=True, timeout = 1800)

            # Wait some time to settle down the driver installer.
            xenrt.sleep(30)

            # Because of /noreboot option, if setup requires reboot, it returns 1.
            if returncode != 0:
                if returncode == 1:
                    self.reboot()
                elif returncode == -522190831:
                    raise xenrt.XRTError("NVidia driver installer failed to detect compatible hardware. (return code = %d)" % (returncode,))
                else:
                    raise xenrt.XRTError("NVidia driver installer failed to install. (return code = %d)" % (returncode,))

        except xenrt.XRTError as e:
            raise e

        finally:
            if self.xmlrpcDirExists(targetPath):
                self.xmlrpcDelTree(targetPath)

    def isGPUBeingUtilized(self, gpuType):
        """Find if a GPU is being utilized on a linux vm.
        Designed for use with Ubuntu1404, RHEL7, OEL7, CentOS7.
        Raises XRTError if used with a different distro, although older versions of above fail gracefully.
        @param gpuType: The brand of the GPU which should be checked against. eg. "NVIDIA"
        @rtype: boolean
        """

        def findPciID(componentList):
            """Find the pciid from the lspci output components list."""
            pciid = None
            for line in componentList.splitlines():
                if "VGA" in line:
                    pciid = componentList.split(" ")[0]
                    break
            return pciid

        def isKernelDriverInUse(lspciOut):
            """Parse the input to figure out if Kernel Driver in use from lspci output."""
            # Check if "Kernel driver in use: " is in second last line.
            loLastLine = [line for line in lspciOut.splitlines()][-2]
            xenrt.TEC().logverbose("Output last line: %s" % loLastLine)

            if "Kernel driver in use: " not in loLastLine:
                return False # No kernel driver in use, ie. GPU not utilized.
            return True

        def isGPUClaimed(xml):
            root = ET.fromstring(xml)
            desiredNode = None
            for child in root:
                if child.attrib["handle"].endswith(pciid):
                    desiredNode = child
                    break

            if "claimed" in desiredNode.attrib:
                if desiredNode.attrib["claimed"] != "true":
                    return False # GPU is unclaimed.
            else:
                return False
            return True

        if not gpuType:
            return False

        # List of compatible distros.
        workingDistros = ["rhel", "centos", "oel", "ubuntu"]

        self.findDistro()
        xenrt.TEC().logverbose("Current distro is: %s" % self.distro)

        if not any([self.distro.lower().startswith(d) for d in workingDistros]):
            raise xenrt.XRTError("Function can only be used with certain linux distros. Current distro: %s. Woring distros: %s" % (self.distro, workingDistros))

        # RHEL based systems need to install lspci/lshw
        if not self.distro.lower().startswith("ubuntu"):
            if not self.checkRPMInstalled("pciutils"):
                self.execguest("yum -y install pciutils")

            if not self.checkRPMInstalled("lshw"):
                urlprefix = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "")
                url = "%s/gpuDriver/PVHVM/gputools/lshw-2.17-1.el7.rf.x86_64_new.rpm" % (urlprefix)
                installfile = xenrt.TEC().getFile(url)
                if not installfile:
                    raise xenrt.XRTError("Failed to fetch lshw .rpm")
                sftp = self.sftpClient()
                sftp.copyTo(installfile, "/tmp/%s" % (os.path.basename(installfile)))
                sftp.close()

                self.execguest("yum -y install /tmp/lshw-2.17-1.el7.rf.x86_64_new.rpm")

        # Check if the GPU of given type is present.
        try:
            componentList = self.execguest("lspci | grep -i %s" % gpuType)
        except:
            xenrt.TEC().logverbose("Could not find any devices of the given name: %s" % gpuType)
            return False

        # Identify pciid of GPU.
        # Sample output to parse: "0:00.0 VGA|Audio ... NVIDIA|AMD|Intel"
        pciid = findPciID(componentList)
        if not pciid:
            xenrt.TEC().logverbose("Could not find any graphics devices of the given name: %s" % gpuType)
            return False

        lspciOut = self.execguest("lspci -v -s %s" % pciid)
        inUse = isKernelDriverInUse(lspciOut)
        if not inUse:
            return False
                
        xml = self.execguest("lshw -xml -c video")
        claimed = isGPUClaimed(xml)
        if not claimed:
            return False

        # Both tests for the GPU being utilized passed.
        return True

    def diskWriteWorkLoad(self,timeInsecs,FileNameForTimeDiff=None):

        def getScriptToBeExecuted(timeInsecs,FileNameToBeWritten,FileNameForTimeDiff,vmName):

            writeScriptOnVM = """
from datetime  import datetime
import time
import string
import random
MB=1024*1024
f=open('%s','w')
f1=open('%s','w')
deadline = time.time() + %d
while True:
    data=(random.choice(string.letters))*100*MB
    timeBefore=datetime.now()
    f.write(data)
    timeAfter = datetime.now()
    f.seek(0)
    diff = str(timeAfter - timeBefore)
    totalTime = '\\r\\n %s: WRITE_TIME: 100MB data: ' + diff
    f1.write(totalTime)
    if (time.time() > deadline):
        break
""" % (FileNameToBeWritten,FileNameForTimeDiff,int(timeInsecs),vmName)

            return writeScriptOnVM

        if self.windows:

            if not FileNameForTimeDiff:
                FileNameForTimeDiff = 'c:\\\\writetime.txt'
            FileNameToBeWritten = 'c:\\\\test'
            script = getScriptToBeExecuted(timeInsecs,FileNameToBeWritten,FileNameForTimeDiff,self.getName())
            try:
                self.xmlrpcWriteFile("c:\\writeScript.py",script)
                self.xmlrpcExec("python c:\\writeScript.py",ignoreHealthCheck=True)
            except xenrt.XRTFailure, e:
                xenrt.TEC().logverbose("Failed to execute read script on VM %s and failed with error : %s" % (self.getName(),e))

        else:

           if not FileNameForTimeDiff:
               FileNameForTimeDiff = 'writetime.txt'
           FileNameToBeWritten = 'test'
           script = getScriptToBeExecuted(timeInsecs,FileNameToBeWritten,FileNameForTimeDiff,self.getName())

    def installPVHVMNvidiaGpuDrivers(self):
        if not self.verifyGuestAsPVHVM():
            raise xenrt.XRTError("This GPU drivers are for PVHVM guests only")

        #guestArch=self.execguest("uname -p")
        xenrt.log("Guest distro is %s"%self.distro)
        xenrt.log("Guest arch is %s"%self.arch)

        if "64" in (self.arch or "") or "-64" in self.distro:
            drivername=xenrt.TEC().lookup("PVHVM_GPU_NVIDIA_X64")
        else :
            drivername=xenrt.TEC().lookup("PVHVM_GPU_NVIDIA_X86")

        #Get the file and put it into the VM
        urlprefix = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "")
        url = "%s/gpuDriver/PVHVM/%s" % (urlprefix, drivername)
        installfile = xenrt.TEC().getFile(url)
        installName = "nvidialinuxdriver.run"
        if not installfile:
            raise xenrt.XRTError("Failed to fetch PVHVM GPU NVidia driver.")
        sftp = self.sftpClient()
        sftp.copyTo(installfile, "/%s" % (os.path.basename(installName)))
        sftp.close()

        #Call guest methods to install drivers
        if self.distro.startswith("ubuntu"):
            self.installUbuntuGpuDrivers(installName)
        else :
            self.installRhelGpuDrivers(installName)

    def installUbuntuGpuDrivers(self ,drivername):
        self.execcmd("echo 'blacklist nouveau' >> /etc/modprobe.d/blacklist.conf ")
        self.execcmd("echo 'blacklist nvidiafb' >> /etc/modprobe.d/blacklist.conf ")
        self.execcmd("sudo apt-get remove --purge nvidia*")
        self.execcmd("sudo update-initramfs -u")
        self.reboot()
        self.execcmd("sh /./%s --silent" %(drivername))
        self.reboot()
        
    def installRhelGpuDrivers(self,drivername):
        self.execcmd("sed -i 's/GRUB_CMDLINE_LINUX.*\s[a-z,A_Z,0-9]*/& rdblacklist=nouveau/' /etc/default/grub")
        self.execcmd("grub2-mkconfig -o /boot/grub2/grub.cfg")
        self.execcmd("echo 'blacklist nouveau' >> /etc/modprobe.d/blacklist.conf ")
        self.execcmd("echo 'blacklist nvidiafb' >> /etc/modprobe.d/blacklist.conf ")
        self.execcmd("echo 'blacklist nouveau' >> /etc/modprobe.d/disable-nouveau.conf ")
        self.execcmd("echo 'options nouveau modeset=0' >> /etc/modprobe.d/disable-nouveau.conf ")
        self.reboot()
        self.execcmd("sh /./%s --silent" %(drivername))
        self.reboot()

    def verifyGuestAsPVHVM(self):

        return self.paramGet("HVM-boot-policy") == "BIOS order" and self.paramGet("PV-bootloader") == ""

    def diskReadWorkload(self,timeInsecs,fileNameForTimeDiff=None):

        def getScriptToBeExecuted(timeInsecs,fileNameToBeWritten,fileNameForTimeDiff,vmName):

            readScriptOnVM = """
from datetime import datetime
import string,time,random
MB=1024*1024
fw=open('%s','w')
fr=open('%s','r')
f1=open('%s','w')
deadline = time.time() + %d
while True:
    data=(random.choice(string.letters))*200*MB
    fw.write(data)
    timeBefore=datetime.now()
    fr.read(100*MB)
    timeAfter=datetime.now()
    diff = str(timeAfter - timeBefore)
    totalTime = '\\r\\n%s: READ_TIME: 100MB data: ' + diff
    f1.write(totalTime)
    fr.seek(0)
    fw.seek(0)
    if (time.time() > deadline):
        break
""" % (fileNameToBeWritten,fileNameToBeWritten,fileNameForTimeDiff,int(timeInsecs),vmName)

            return readScriptOnVM

        if self.windows:

            if not fileNameForTimeDiff:
                fileNameForTimeDiff = 'c:\\\\readtime.txt'
            fileNameToBeWritten = 'c:\\\\test'
            script = getScriptToBeExecuted(timeInsecs,fileNameToBeWritten,fileNameForTimeDiff,self.getName())
            try:
                self.xmlrpcWriteFile("c:\\readScript.py",script)
                self.xmlrpcExec("python c:\\readScript.py",ignoreHealthCheck=True)
            except xenrt.XRTFailure, e:
                xenrt.TEC().logverbose("Failed to execute read script on VM %s and failed with error : %s" % (self.getName(),e))

        else:

            if not fileNameForTimeDiff:
                fileNameForTimeDiff = 'writetime.txt'
            fileNameToBeWritten = 'test'
            script = getScriptToBeExecuted(timeInsecs,fileNameToBeWritten,fileNameForTimeDiff,self.getName())

    def installspecjbb(self,workdir=None):

        if not workdir:
            workdir = "c:\\"
        try:
            self.xmlrpcUnpackTarball("%s/specjbb.tgz" %
                              (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                              workdir)
        except Exception, e:
            xenrt.TEC().logverbose("installation of specjbb failed with error: %s" % (str(e)))
            raise xenrt.XRTFailure("Installation of specjbb failed with error: %s" % (str(e)))

    def specjbbCPUWorkload(self,workdir=None):

        if self.windows:
            if not workdir:
                workdir = "c:\\"
            cpuWorkload = "specjbb"
            jbbBase = "%s\\%s\\installed" % (workdir, cpuWorkload)
            jobFile = "SPECjbb.props"
            minheap = "300M"
            maxheap = "500M"

            try:
                self.xmlrpcExec("java -version")
            except:
                self.installJava()

            self.xmlrpcUnpackTarball("%s/%s.tgz" %
                              (xenrt.TEC().lookup("TEST_TARBALL_BASE"),
                               cpuWorkload),
                              workdir)

            self.xmlrpcExec("cd %s\n"
                              "copy %s\\*.props .\n"
                              "xcopy %s\\xml xml /E /C /F /H /K /Y /I\n"
                              "set CLASSPATH=%s\\jbb.jar;"
                              "%s\\jbb_no_precompile.jar;"
                              "%s\\check.jar;%s\\reporter.jar;%%CLASSPATH%%\n"
                              "java -ms%s -mx%s spec.jbb.JBBmain -propfile %s"
                              % (workdir,
                                 jbbBase,
                                 jbbBase,
                                 jbbBase,
                                 jbbBase,
                                 jbbBase,
                                 jbbBase,
                                 minheap,
                                 maxheap,
                                 jobFile),
                              timeout=7200)
        else:
            raise xenrt.XRTFailure("Not Implemented for Linux VMs")

    def prime95CPUMemoryWorkload(self,timeinsecs,testmemory=False,workdir=None):

        if self.windows:

            if not workdir:
                workdir = "c:\\"
            cpuWorkload = "prime95"

            # Unpack the test binaries
            try:
                self.xmlrpcUnpackTarball("%s/%s.tgz" %
                                  (xenrt.TEC().lookup("TEST_TARBALL_BASE"),
                                   cpuWorkload), workdir)
            except Exception, e:
                raise xenrt.XRTFailure("Failure occured while copying Prime95 on windows VM with error: %s" % (str(e)))

            if testmemory:
                self.xmlrpcExec("copy %s\\%s\\prime_mem.txt %s\\%s\\prime.txt /Y" %(workdir,cpuWorkload,workdir,cpuWorkload))
            else:
                self.xmlrpcExec("copy %s\\%s\\prime_cpu.txt %s\\%s\\prime.txt /Y" %(workdir,cpuWorkload,workdir,cpuWorkload))

            # Start the test
            id = self.xmlrpcStart("%s\\prime95\\prime95.exe -T" % (workdir))
            started = xenrt.timenow()
            finishat = started + timeinsecs
            time.sleep(30)
            if self.xmlrpcPoll(id):
                raise xenrt.XRTError("prime95 did not start properly")

            # Wait for the specified duration
            while finishat > xenrt.timenow():
                if self.xmlrpcPoll(id):
                    raise xenrt.XRTFailure("prime95 has stopped running")
                time.sleep(30)

            # Kill it
            self.xmlrpcKillAll("prime95.exe")
            time.sleep(30)
            if not self.xmlrpcPoll(id):
                raise xenrt.XRTError("prime95 did not terminate properly")
        else:
            raise xenrt.XRTFailure("Not Implemented for Linux VMs")

    def installVNCServer(self):
        if self.windows:
            self.xmlrpcUnpackTarball("%s/tightvnc.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")
            if self.arch == "x86-64":
                self.xmlrpcExec("msiexec /i c:\\tightvnc\\tightvnc-2.7.10-setup-64bit.msi /quiet /norestart SET_PASSWORD=1 VALUE_OF_PASSWORD=%s" % (xenrt.TEC().lookup("ROOT_PASSWORD")))
            else:
                self.xmlrpcExec("msiexec /i c:\\tightvnc\\tightvnc-2.7.10-setup-32bit.msi /quiet /norestart SET_PASSWORD=1 VALUE_OF_PASSWORD=%s" % (xenrt.TEC().lookup("ROOT_PASSWORD")))
        else:
            raise xenrt.XRTError("Not Implemented for Linux VMs")

    def setScreenResolution(self, x=None, y=None, colorDepth=None):
        if self.windows:
            if not self.xmlrpcFileExists("c:\\qres\\qres.exe"):
                self.xmlrpcUnpackTarball("%s/qres.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")
            cmd = "c:\\qres\\qres.exe "
            if x:
                cmd += "x=%d " % x
            if y:
                cmd += "y=%d " % y
            if colorDepth:
                cmd += "c=%d " % colorDepth
            self.xmlrpcExec(cmd)
        else:
            raise xenrt.XRTError("Not Implemented for Linux VMs")

    def enableFullCrashDump(self):

        regKey = u"""Windows Registry Editor Version 5.00\r\r\n[HKEY_LOCAL_MACHINE\SYSTEM\ControlSet001\Control\CrashControl]\r\n"CrashDumpEnabled"=dword:00000001"""

        self.xmlrpcWriteFile("c:\\crashDump.reg",regKey)
        self.xmlrpcExec("regEdit.exe /s c:\\crashDump.reg")

        self.reboot()

    def getInstance(self):
        if not self.instance:
            if self.windows or not self.arch:
                osdistro = self.distro
            else:
                osdistro = "%s_%s" % (self.distro, self.arch)
        
            wrapper = xenrt.lib.generic.GuestWrapper(self)
            self.instance = xenrt.lib.generic.Instance(wrapper, self.name, osdistro, self.vcpus, self.memory)
            self.instance.os.tailor()
            self.instance.os.populateFromExisting()
            xenrt.TEC().registry.instancePut(self.name, self)
        return self.instance

    def installPackages(self, packageList):
        packages = " ".join(packageList)
        try:
            if "deb" in self.distro or "ubuntu" in self.distro:
                self.execguest("apt-get update", level=xenrt.RC_OK)
                self.execguest("apt-get -y --force-yes install %s" % packages)
            elif "rhel" in self.distro or "centos" in self.distro or "oel" in self.distro or "fedora" in self.distro:
                self.execguest("yum install -y %s" % packages)
            elif re.search("sles|sled", self.distro):
                self.execguest("zypper -n --non-interactive install %s" % packages)
            else:
                raise xenrt.XRTError("Not Implemented")
        except Exception, e:
            raise xenrt.XRTError("Failed to install packages '%s' on guest %s : %s" % (packages, self, e))

    def xenDesktopTailor(self):
        # Optimizations from CTX125874, excluding Windows crash dump (because we want them) and IE (because we don't use it)
        self.winRegAdd("HKLM", "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update", "AUOptions", "DWORD", 1)
        self.winRegAdd("HKLM", "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update", "ScheduledInstallDay", "DWORD", 0)
        self.winRegAdd("HKLM", "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update", "ScheduledInstallTime", "DWORD", 3)
        self.winRegAdd("HKLM", "SYSTEM\\CurrentControlSet\\Services\\wuauserv", "Start", "DWORD", 4)
        self.winRegAdd("HKLM", "SOFTWARE\\Microsoft\\Dfrg\\BootOptimizeFunction", "Enable", "SZ", "N")
        self.winRegAdd("HKLM", "SOFTWARE\\Microsoft\Windows\\CurrentVersion\\OptimalLayout", "EnableAutoLayout", "DWORD", 0)
        self.winRegAdd("HKLM", "SYSTEM\\CurrentControlSet\\Services\\sr", "Start", "DWORD", 4)
        self.winRegAdd("HKLM", "SYSTEM\\CurrentControlSet\\Services\\srservice", "Start", "DWORD", 4)
        self.winRegAdd("HKLM", "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\SystemRestore", "DisableSR", "DWORD", 1)
        self.winRegAdd("HKLM", "SYSTEM\\CurrentControlSet\\Control\\FileSystem", "NtfsDisableLastAccessUpdate", "DWORD", 1)
        self.winRegAdd("HKLM", "SYSTEM\\CurrentControlSet\\Services\\cisvc", "Start", "DWORD", 4)
        self.winRegAdd("HKLM", "SYSTEM\\CurrentControlSet\\Services\\Eventlog\\Application", "MaxSize", "DWORD", 65536)
        self.winRegAdd("HKLM", "SYSTEM\\CurrentControlSet\\Services\\Eventlog\\Security", "MaxSize", "DWORD", 65536)
        self.winRegAdd("HKLM", "SYSTEM\\CurrentControlSet\\Services\\Eventlog\\System", "MaxSize", "DWORD", 65536)
        self.winRegAdd("HKLM", "SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Memory Management", "ClearPageFileAtShutdown", "DWORD", 0)
        self.winRegAdd("HKLM", "SYSTEM\\CurrentControlSet\\Services\\WSearch", "Start", "DWORD", 4)

        try:
            self.winRegDel("HKLM", "SOFTWARE\\Microsoft\Windows\\CurrentVersion\\Run", "Windows Defender")
        except:
            pass


        if self.xmlrpcFileExists("C:\\Windows\\Microsoft.NET\\Framework\\v2.0.50727\\ngen.exe"):
            try:
                self.xmlrpcExec("C:\\Windows\\Microsoft.NET\\Framework\\v2.0.50727\\ngen.exe executeQueuedItems")
            except:
                pass
        if self.xmlrpcFileExists("C:\\Windows\\Microsoft.NET\\Framework\\v4.0.30319\\ngen.exe"):
            try:
                self.xmlrpcExec("C:\\Windows\\Microsoft.NET\\Framework\\v2.0.50727\\ngen.exe executeQueuedItems")
            except:
                pass

    def checkRPMInstalled(self, rpm):
        """
        Check if a specific rpm is installed
        @param rpm: the rpm name including or excluding the extension '.rpm'
        @type rpm: string
        @return If the rpm provided is installed already
        @rtype boolean
        """
        if self.windows:
            raise xenrt.XRTError("Function can only be used to check for installed RPMs on linux.")

        #rpm should NOT contain file extn .rpm, so split off any file extension
        fileWithoutExt = os.path.splitext(rpm)[0]

        return not bool(self.execguest("rpm -qi %s" % fileWithoutExt, retval="code", level=xenrt.RC_OK))

    def installDrivers(self):
        pass

    def setupNetscalerVPX(self, installNSTools=False):
        netscaler = xenrt.lib.netscaler.NetScaler.setupNetScalerVpx(self, useExistingVIFs=True, license=xenrt.lib.netscaler.NetScaler.getLicenseFileFromXenRT())
        xenrt.GEC().registry.objPut("netscaler", self.name, netscaler)
        if installNSTools:
            netscaler.installNSTools()
        netscaler.checkFeatures("Test results after setting up:")

class EventObserver(xenrt.XRTThread):

    def __init__(self,host,session,eventClass,taskRef,timeout):

        self.session = session
        self.host = host
        self.threadSession = None
        self.eventClass = eventClass
        self.timeout = timeout
        self.taskId = taskRef
        self.totalTime = 0
        self.eventStatus = "NOT_RUNNING"
        xenrt.XRTThread.__init__(self)

    def run(self):
        self.threadSession = self.host.getAPISession(secure=False)

        if self.eventStatus == "NOT_RUNNING":
            self.eventStatus = "RUNNING"
            self.monitorEvent()
        else:
            raise xenrt.XRTError("Event Monitoring is being done or finished for the event")

    def monitorEvent(self):
        #This monitors one event at a time

        complete = False
        xapi = self.threadSession.xenapi
        xapi.event.register(self.eventClass)
        startTime = time.time()

        if xapi.task.get_status(self.taskId) == "pending":
            failCount = 0
            while 1:
                try:
                    events = xapi.event.next()
                    if xapi.task.get_status(self.taskId) <> "pending":
                        self.totalTime = time.time() - startTime
                        self.eventStatus = "COMPLETED"
                        break
                    elif (time.time() - startTime > self.timeout):
                        self.eventStatus = "TIMEOUT"
                        break
                    failCount = 0

                except Exception, e:

                    xenrt.TEC().logverbose("** Exception occurred: e = [%s]" % str(e))

                    failCount += 1
                    if failCount > 30:
                        self.eventStatus = "ERROR_MONITORING"
                        break

                    try:
                        xenrt.TEC().logverbose("** re-registering anyway")
                        self.threadSession.xenapi.event.unregister(self.eventClass)
                        self.threadSession.xenapi.event.register(self.eventClass)
                    except:
                        self.eventStatus = "ERROR_MONITORING"
                        xenrt.TEC().logverbose("Unable to re-register Event")
                        break

    def getSession(self):

        return self.session

    def getTaskID(self):

        return self.taskId

    def getResult(self):

        result  = {'eventStatus': 'ERROR_MONITORING',
                   'taskResult': 'error',
                   'totalTime': 0}

        if self.eventStatus <> "RUNNING" and self.session <> None:
            try:
                taskResult = self.session.xenapi.task.get_status(self.taskId)
                result = {'eventStatus': self.eventStatus,
                          'taskResult': taskResult,
                          'totalTime': self.totalTime}
                return result
            except Exception, e:
                xenrt.TEC().logverbose("Exception occurred while trying to get task status: e = %s" % str(e))
                return result
        else:
            if self.session.xenapi.task.get_status(self.taskId) <> "pending":
                try:
                    taskResult = self.session.xenapi.task.get_status(self.taskId)
                    self.eventStatus = "COMPLETED"
                    result = {'eventStatus': self.eventStatus,
                              'taskResult': taskResult,
                              'totalTime': self.totalTime}
                    return result
                except:
                    xenrt.TEC().logverbose("Exception occurred while trying to get task status: e= %s" % str(e))
                    return result
            else:
                raise xenrt.XRTError("Task is still running")

    def getEventMonitorStatus(self):

        return self.eventStatus

    def getTaskStatus(self):

        if self.session <> None:
            try:
                status = self.session.xenapi.task.get_status(self.taskId)
                return status
            except Exception, e:
                xenrt.TEC().logverbose("Exception occurred while trying to get task status: e = %s" % str(e))
                return 'error'
        else:
            raise xenrt.XRTError("Xapi session does not exists")

    def getErrorInfo(self):

        if self.eventStatus <> "NOT_RUNNING" and self.eventStatus <> "RUNNING" and self.session <> None:
            return self.session.xenapi.task.get_error_info(self.taskId)
        else:
            raise xenrt.XRTError("Event Monitoring is not completed or xapi session does not exists")

    def isCompleted(self):

        if self.eventStatus <> "NOT_RUNNING" and self.eventStatus <> "RUNNING":
            return True
        else:
            return False

    def closeXapiSession(self):

        if self.session <> None:
            self.session.xenapi.session.logout()
        else:
            raise xenrt.XRTError("Session is already closed")

    def cancelTask(self):

        if self.session <> None:
            self.session.xenapi.task.cancel(self.taskId)
        else:
            raise xenrt.XRTError("Session is already closed")

    def getTaskOtherConfig(self):

        if self.session <> None:
            otherConfig = self.session.xenapi.task.get_other_config(self.taskId)
            return otherConfig
        else:
            raise xenrt.XRTError("Session is already closed")

class PAMServer(object):

    def createSubjectGraph(self, subjects):
        def parseUser(x, group=None):
            name = x.getAttribute("name")
            subject = self.getSubject(name=name)
            if not subject:
                password = x.getAttribute("password")
                subject = self.addUser(name, password=password)
            if group: group.addSubject(subject)
        def parseGroup(x, group=None):
            name = x.getAttribute("name")
            subject = self.getSubject(name=name)
            if not subject:
                subject = self.addGroup(name)
            for y in x.childNodes:
                if y.localName == "user": parseUser(y, subject)
        try:
            xs = xml.dom.minidom.parseString(subjects)
            for x in xs.getElementsByTagName("subjects"):
                for y in x.childNodes:
                    if y.localName == "group": parseGroup(y)
                    if y.localName == "user": parseUser(y)
            users = [ x.getAttribute("name") for x in xs.getElementsByTagName("user") ]
            groups = [ x.getAttribute("name") for x in xs.getElementsByTagName("group") ]
            return users, groups
        except Exception, e:
            traceback.print_exc(sys.stdout)
            xenrt.TEC().logverbose("Caught exception %s trying to create "
                                   "the subject graph: %s" % (str(e), subjects))

    class Subject:

        def __repr__(self): return self.name

        def __hash__(self): return hash(str(self) + "_" + self.name)

        def __eq__(self, other):
            return str(self) == str(other) and self.name == other.name

        def __init__(self, server, name):
            self.groups = sets.Set()
            self.name = name
            self.server = server
            self.roles = sets.Set()
            self.domain = None

        def _getAllGroupMembers(self):
            data = self.server.place.execdom0("cat /etc/group").strip().split("\n")
            data = [ x.split(":") for x in data ]
            return dict(map(lambda (a,b,c,d):(a, d.split(",")), data))

        def getSID(self):
            pass

        def apiName(self, usedomainname=False):
            return self.name

        def cliName(self, usedomainname=False):
            return self.name

    class User(Subject):

        def __str__(self): return "user"

        def __init__(self, server, name):
            PAMServer.Subject.__init__(self, server, name)
            self.password = None

        def getSID(self):
            return "u%s" % (self.server.place.execdom0("id -u %s" % (self.name)).strip())

        def remove(self):
            self.server.place.execdom0("userdel -r %s" % (self.name))
            for group in self.groups: group.members.remove(self)
            self.server.users.remove(self)

        def setPassword(self, password):
            self.password = password
            self.server.place.execdom0("echo %s | passwd --stdin %s" %
                                       (self.password, self.name))

        def enable(self):
            self.server.place.execdom0("usermod -U %s" % (self.name))

        def disable(self):
            self.server.place.execdom0("usermod -L %s" % (self.name))

        def getGroups(self):
            data = self._getAllGroupMembers()
            if not data.has_key(self.name): return
            groups = data[self.name]
            for group in groups:
                subject = self.server.getGroup(group)
                if subject:
                    subject.members.add(self)
                    self.groups.add(subject)

    class Group(Subject):

        def __str__(self): return "group"

        def __init__(self, server, name):
            self.members = sets.Set()
            PAMServer.Subject.__init__(self, server, name)

        def getSID(self):
            return "g%s" % (self.server.place.execdom0("cat /etc/group | grep %s | cut -d ':' -f 3" % (self.name)).strip())

        def remove(self):
            self.server.place.execdom0("groupdel %s" % (self.name))
            for m in self.members: m.groups.remove(self)
            self.server.groups.remove(self)

        def addSubject(self, subject):
            self.server.place.execdom0("usermod -a -G %s,%s %s" %
                                       (self.name,
                                        string.join([x.name for x in subject.groups], ","),
                                        subject.name))
            self.members.add(subject)
            subject.groups.add(self)

        def delSubject(self, subject):
            subject.groups.remove(self)
            self.server.place.execdom0("usermod -G %s %s" %
                                       (string.join([x.name for x in subject.groups], ","),
                                        subject.name))
            self.members.remove(subject)

        def getMembers(self):
            data = self._getAllGroupMembers()
            members = [ x for x in data if self.name in data[x] ]
            for member in members:
                subject = self.server.getUser(member)
                if subject:
                    self.members.add(subject)
                    subject.groups.add(self)

    def getSubject(self, name=None):
        for subject in self.users + self.groups:
            if subject.name == name: return subject
        return None

    def getGroup(self, name):
        for subject in self.groups:
            if subject.name == name: return subject
        return None

    def getUser(self, name):
        for subject in self.users:
            if subject.name == name: return subject
        return None

    def addUser(self, name, password=None, group="users"):
        if not password: password = xenrt.randomGuestName()[-8:]
        user = self.User(self, name)
        group = self.getGroup(group)
        user.groups.add(group)
        group.members.add(user)
        self.place.execdom0("adduser -g %s %s" % (group.name, user.name))
        user.setPassword(password)
        self.users.append(user)
        return user

    def addGroup(self, name):
        group = self.Group(self, name)
        self.place.execdom0("groupadd %s" % (group.name))
        self.groups.append(group)
        return group

    def _getAllSubjects(self, type):
        return self.place.execdom0("cat /etc/%s | cut -d ':' -f 1" %
                                   (type)).strip().split("\n")

    def getAllUsers(self):
        return [ self.User(self, name) for name in self._getAllSubjects("passwd") ]

    def getAllGroups(self):
        return [ self.Group(self, name) for name in self._getAllSubjects("group") ]

    def __init__(self, place):
        self.users = []
        self.groups = []
        self.type = "PAM"
        self.place = place
        self.domainname = None
        if self.place.windows:
            raise xenrt.XRTError("XenRT only supports PAM on Linux.")

        self.groups = self.getAllGroups()
        self.users = self.getAllUsers()
        for subject in self.users:
            subject.getGroups()
        for subject in self.groups:
            subject.getMembers()

class ActiveDirectoryServer(object):

    def createSubjectGraph(self, subjects):
        def parseUser(x, group=None):
            name = x.getAttribute("name")
            subject = self.getSubject(name=name)
            dontPreauthenticate = x.getAttribute("dontPreauthenticate")
            if not subject:
                password = x.getAttribute("password")
                subject = self.addUser(name, password=password, dontPreauthenticate=dontPreauthenticate)
            if group: group.addSubject(subject)
        def parseGroup(x, group=None):
            name = x.getAttribute("name")
            subject = self.getSubject(name=name)
            if not subject:
                subject = self.addGroup(name)
            if group: group.addSubject(subject)
            for y in x.childNodes:
                if y.localName == "group": parseGroup(y, subject)
                if y.localName == "user": parseUser(y, subject)
        try:
            xs = xml.dom.minidom.parseString(subjects)
            for x in xs.getElementsByTagName("subjects"):
                for y in x.childNodes:
                    if y.localName == "group": parseGroup(y)
                    if y.localName == "user": parseUser(y)
            users = sets.Set([ x.getAttribute("name") for x in xs.getElementsByTagName("user") ])
            groups = sets.Set([ x.getAttribute("name") for x in xs.getElementsByTagName("group") ])
            return users, groups
        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().logverbose("Caught exception %s trying to create the AD graph: %s" %
                                   (str(e), subjects))
            raise

    class Local:

        def __repr__(self): return self.name

        def __hash__(self): return hash(self.name)

        def __eq__(self, other):
            return self.name == other.name

        def apiName(self, usedomainname=False):
            return self.name

        def cliName(self, usedomainname=False):
            return self.name

        def __init__(self, name, password):
            self.name = unicode(name)
            self.password = unicode(password)


    class Subject:

        def __repr__(self): return self.name.encode("utf-8")

        def __hash__(self): return hash(self.dn)

        def __eq__(self, other):
            return self.dn == other.dn

        def apiName(self, usedomainname=False):
            if usedomainname:
                return u"%s\\%s" % (self.server.netbiosname, self.name)
            else:
                return u"%s\\%s" % (self.server.domainname, self.name)

        def cliName(self, usedomainname=False):
            if usedomainname:
                return u"%s\\\\%s" % (self.server.netbiosname, self.name)
            else:
                return u"%s\\\\%s" % (self.server.domainname, self.name)

        def __init__(self, server, dn):
            self.server = server
            self.dn = unicode(dn)
            self.memberof = sets.Set()
            self.roles = sets.Set()
            self.name = re.match(r"^CN=(?P<name>[^,]+)", self.dn).group("name")

        def enable(self):
            script = u"""
$subject = [ADSI]"LDAP://%s"
$subject.psbase.InvokeSet("AccountDisabled", "False")
$subject.setInfo()
""" % (self.dn)
            self.server.place.xmlrpcExec(script, powershell=True)

        def disable(self):
            script = u"""
$subject = [ADSI]"LDAP://%s"
$subject.psbase.InvokeSet("AccountDisabled", "True")
$subject.setInfo()
""" % (self.dn)
            self.server.place.xmlrpcExec(script, powershell=True)

        def getSID(self):
            def wordtoint(word):
                result = [ "%02X" % (x) for x in reversed(word) ]
                result = string.join(result, "")
                return int(result, 16)
            script = u"""
$subject = [ADSI]"LDAP://%s"
$subject.objectSID
""" % (self.dn)
            data = self.server.place.xmlrpcExec(script, powershell=True, returndata=True)
            bytesid = map(int, data.strip().split()[2:])
            revision = bytesid[0]
            authority = wordtoint(bytesid[1:7])
            subcount = bytesid[7]
            subauths = []
            for i in range(subcount):
                subauths.append(wordtoint(bytesid[4*i+8:4*i+12]))
            return "S-%s-%s-%s" % (revision, authority, string.join(map(str, subauths), "-"))

    class User(Subject):

        def __str__(self): return "user"

        def __init__(self, server, dn):
            self.password = u""
            ActiveDirectoryServer.Subject.__init__(self, server, dn)

        def getUserAccountControl(self):
            #0x0002     ACCOUNTDISABLE
            #0x0008     HOMEDIR_REQUIRED
            #0x0010     LOCKOUT
            #0x0020     PASSWD_NOTREQD
            #0x0040     PASSWD_CANT_CHANGE
            #0x0080     ENCRYPTED_TEXT_PWD_ALLOWED
            #0x0100     TEMP_DUPLICATE_ACCOUNT
            #0x0200     NORMAL_ACCOUNT
            #0x0800     INTERDOMAIN_TRUST_ACCOUNT
            #0x1000     WORKSTATION_TRUST_ACCOUNT
            #0x2000     SERVER_TRUST_ACCOUNT
            #0x10000    DONT_EXPIRE_PASSWORD
            #0x20000    MNS_LOGON_ACCOUNT
            #0x40000    SMARTCARD_REQUIRED
            #0x80000    TRUSTED_FOR_DELEGATION
            #0x100000   NOT_DELEGATED
            #0x200000   USE_DES_KEY_ONLY
            #0x400000   DONT_REQ_PREAUTH
            #0x800000   PASSWORD_EXPIRED
            #0x1000000  TRUSTED_TO_AUTH_FOR_DELEGATION
            script = u"""
$user = [ADSI]"LDAP://%s"
$user.userAccountControl
""" % (self.dn)
            data = self.server.place.xmlrpcExec(script, powershell=True, returndata=True)
            data = re.match(".+?(\d+)\n$", data, re.M|re.S).group(1)
            return int(data)

        def setUserAccountControl(self, value):
            script = u"""
$user = [ADSI]"LDAP://%s"
$user.userAccountControl = "%s"
$user.SetInfo()
""" % (self.dn, value)
            self.server.place.xmlrpcExec(script, powershell=True)

        def setDontPreauthenticate(self, boolean):
            if boolean:
                self.setUserAccountControl(self.getUserAccountControl() | 0x400000)
            else:
                self.setUserAccountControl(self.getUserAccountControl() & ~0x400000)

        def setPassword(self, password):
            script = u"""
$subject = [ADSI]"LDAP://%s"
$subject.psbase.Invoke("setpassword", "%s")
$subject.setInfo()
""" % (self.dn, password)
            self.server.place.xmlrpcExec(script, powershell=True)
            self.password = password

    class Group(Subject):

        def __str__(self): return "group"

        def __init__(self, server, dn):
            self.members = sets.Set()
            ActiveDirectoryServer.Subject.__init__(self, server, dn)

        def addSubject(self, subject):
            script = u"""
$group = [ADSI]"LDAP://%s"
$subject = [ADSI]"LDAP://%s"
$group.member = $group.member + $subject.distinguishedName
$group.setInfo()
""" % (self.dn, subject.dn)
            self.server.place.xmlrpcExec(script, powershell=True)
            self.members.add(subject)
            subject.memberof.add(self)

        def removeSubject(self, subject):
            script = u"""
$group = [ADSI]"LDAP://%s"
$subject = [ADSI]"LDAP://%s"
foreach ($member in $group.member)
{
  if ($subject.distinguishedname -ne $member)
  {
    $new = $new + $member
  }
}
$group.member = $new
$group.setInfo()
""" % (self.dn, subject.dn)
            self.server.place.xmlrpcExec(script, powershell=True)
            self.members.remove(subject)
            subject.memberof.remove(self)

    def getSubject(self, name=u"", dn=u""):
        for subject in self.users + self.groups:
            if dn:
                if subject.dn == dn:
                    return subject
            if name:
                if subject.name == name:
                    return subject

    def _addSubject(self, entity, subjectname):
        if "." in self.domainname:
            container = u"CN=Users,DC=%s,DC=%s" % (tuple(self.domainname.split(".")))
        else:
            container = u"CN=Users,DC=%s" % (self.domainname)
        dn = u"CN=%s,%s" % (subjectname, container)
        subject = entity(self, dn)
        script = u"""
$parent = [ADSI]"LDAP://%s"
$subject = $parent.Create("%s", "CN=%s")
$subject.SetInfo()
""" % (container, str(subject), subjectname)
        self.place.xmlrpcExec(script, powershell=True)
        return subject

    def addUser(self, username, password=u"", parent=None, enable=True, dontPreauthenticate=False):
        if not password:
            password = unicode(xenrt.randomGuestName()[-8:])
        user = self._addSubject(self.User, username)
        script = u"""
$user = [ADSI]"LDAP://%s"
$user.sAMAccountName = "%s"
$user.userPrincipalName = "%s@%s"
$user.SetInfo()
""" % (user.dn, user.name, user.name, user.server.domainname)
        self.place.xmlrpcExec(script, powershell=True)
        parent = self.getSubject("Domain Users")
        user.memberof.add(parent)
        parent.members.add(user)
        self.users.append(user)
        user.setPassword(password)
        user.setDontPreauthenticate(dontPreauthenticate)
        if enable:
            user.enable()
        return user

    def addGroup(self, groupname, parent=None):
        group = self._addSubject(self.Group, groupname)
        script = u"""
$group = [ADSI]"LDAP://%s"
$group.sAMAccountName = "%s"
$group.SetInfo()
""" % (group.dn, group.name)
        self.place.xmlrpcExec(script, powershell=True)
        self.groups.append(group)
        return group

    def removeSubject(self, subjectname):
        subject = self.getSubject(name=subjectname)
        script = u"""
$subject = [ADSI]"LDAP://%s"
$subject.psbase.DeleteTree()
""" % (subject.dn)
        self.place.xmlrpcExec(script, powershell=True)
        if subject in self.users:
            self.users.remove(subject)
        if subject in self.groups:
            self.groups.remove(subject)
        for entity in self.users + self.groups:
            if subject in entity.memberof:
                entity.memberof.remove(subject)
        for entity in self.groups:
            if subject in entity.members:
                entity.members.remove(subject)

    def getSubjectGraph(self):
        try: self.place.xmlrpcRemoveFile("c:\\users.txt")
        except: pass
        try: self.place.xmlrpcRemoveFile("c:\\groups.txt")
        except: pass
        if "." in self.domainname:
            script = u"""
function children {
  param($entity)
  foreach ($child in $entity.psbase.get_children()) {
    if ($child.objectClass -eq "user") {
      write ">>" $child.distinguishedName $child.memberOf >> c:\\users.txt
    }
    if ($child.objectClass -eq "group") {
      write ">>" $child.distinguishedName $child.memberOf >> c:\\groups.txt
    }
    children($child)
  }
}
$domain = [ADSI]"LDAP://DC=%s,DC=%s"
children($domain)
""" % (tuple(self.domainname.split(".")))
        else:
            script = u"""
function children {
  param($entity)
  foreach ($child in $entity.psbase.get_children()) {
    if ($child.objectClass -eq "user") {
      write ">>" $child.distinguishedName $child.memberOf >> c:\\users.txt
    }
    if ($child.objectClass -eq "group") {
      write ">>" $child.distinguishedName $child.memberOf >> c:\\groups.txt
    }
    children($child)
  }
}
$domain = [ADSI]"LDAP://DC=%s"
children($domain)
""" % (self.domainname)
        self.place.xmlrpcExec(script, powershell=True)
        data = self.place.xmlrpcReadFile("c:\\users.txt").decode("utf-16")
        users = [ x.strip().splitlines() for x in re.findall(">>([^>]+)", data) ]
        users = [ (x[0], x[1:]) for x in users ]
        data = self.place.xmlrpcReadFile("c:\\groups.txt").decode("utf-16")
        groups = [ x.strip().splitlines() for x in re.findall(">>([^>]+)", data) ]
        groups = [ (x[0], x[1:]) for x in groups ]

        self.users = [ xenrt.ActiveDirectoryServer.User(self, user) for user,parents in users ]
        self.groups = [ xenrt.ActiveDirectoryServer.Group(self, group) for group,parents in groups ]

        for subject,parents in users + groups:
            for parent in parents:
                user = self.getSubject(dn=subject)
                group = self.getSubject(dn=parent)
                group.members.add(user)
                user.memberof.add(group)

    def getAllComputers(self):
        script = """
$computers = [ADSI]"LDAP://CN=Computers,DC=%s,DC=%s"
write $computers.psbase.get_Children()
""" % (tuple(self.domainname.split(".")))
        data = self.place.xmlrpcExec(script, powershell=True, returndata=True)
        return re.findall("{CN=([^,]+)", data)

    def __init__(self, place, username="Administrator", password=None, domainname=None, dontinstall=False):
        self.users = []
        self.groups = []
        self.type = "AD"
        self.place = place
        self.place.superuser = username
        self.place.password = password
        self.domainname = domainname
        self.netbiosname = None
        self.forestMode = None
        self.domainMode = None

        if not dontinstall:
            self.prepare()

    def prepare(self):
        if float(self.place.xmlrpcWindowsVersion()) < 6.0:
            raise xenrt.XRTError("XenRT only supports Active Directory on Windows Server 2008 and higher.")

        if not self.place.password:
            self.place.password = xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS",
                                                      "ADMINISTRATOR_PASSWORD"])

        if self.place.logFetchExclude:
            self.place.logFetchExclude.append("security")
        else:
            self.place.logFetchExclude = ["security"]

        activeDirectoryConfigured = False
        currentDomainName = None
        if float(self.place.xmlrpcWindowsVersion()) < 6.3:
            data = self.place.xmlrpcExec("servermanagercmd -q", returndata=True)
        else:
            data = self.place.xmlrpcExec("Get-WindowsFeature AD-Domain-Services",powershell=True, returndata=True)
        if re.search("\[X\].*Active Directory Domain Services", data):
            try:
                currentDomainName = unicode(string.lower(self.place.xmlrpcGetEnvVar("USERDNSDOMAIN")))
                activeDirectoryConfigured = True
            except:
                pass
            self.netbiosname = unicode(self.place.xmlrpcGetEnvVar("USERDOMAIN"))
            if self.domainname and not self.domainname == currentDomainName:
                # re-install to change the domain name
                self.uninstall()
                self.install()
            else:
                self.domainname = currentDomainName

        if activeDirectoryConfigured:
            xenrt.TEC().logverbose("Active Directory server already installed. "
                                   "(Domain: %s)" % (self.domainname))
        else:
            extension = str(random.randint(0, 0x7fff))
            if self.domainname == None:
                self.domainname = u"xenrt%s.local" % (extension)
            self.netbiosname = u"XENRTXENRT%s" % (string.upper(extension))
            self.install()

        self.getSubjectGraph()

        if not self.getSubject(name=self.place.superuser):
            admin = self.addUser(self.place.superuser, password=self.place.password)
            self.getSubject(name="Domain Admins").addSubject(admin)

        # Give AD sufficient time to start up.
        xenrt.sleep(60)

    def install(self):
        self.place.xmlrpcExec("netsh advfirewall set domainprofile state off")
        self.place.rename(self.place.getName())
        # Disable the password complexity requirement so we can continue using our default.
        self.place.disableWindowsPasswordComplexityCheck()

        # Set forest mode and domain mode
        self.forestMode = xenrt.TEC().lookup("ADSERVER_FORESTMODE", "Win2008")
        self.domainMode = xenrt.TEC().lookup("ADSERVER_DOMAINMODE", "Win2008")
        ## DCPromo setup requires numeric value rather than windows version string.
        if float(self.place.xmlrpcWindowsVersion()) < 6.3:
            modeLevels = {'0':"Win2000", '2':"Win2003", '3':"Win2008", '4':"Win2008R2"}

            forestLevelList = [key for key,value in modeLevels.iteritems() if value.lower() == self.forestMode.lower()]
            if len(forestLevelList) != 1:
                raise xenrt.XRTError("Unknown forest level : '%s' " % self.forestMode)
            self.forestMode = forestLevelList[0]

            domainLevelList = [key for key,value in modeLevels.iteritems() if value.lower() == self.domainMode.lower()]
            if len(domainLevelList) != 1:
                raise xenrt.XRTError("Unknown forest level : '%s' " % self.domainMode)
            self.domainMode = domainLevelList[0]

        # Set up a new AD domain.
        if float(self.place.xmlrpcWindowsVersion()) < 6.3:
            self.installOnWS2008()
        elif float(self.place.xmlrpcWindowsVersion()) == 6.3:
            self.installOnWS2012()
        else:
            raise xenrt.XRTError("Unimplemented")

        self.place.reboot()
        # This manages to get switched back on during the AD install.
        self.place.disableWindowsPasswordComplexityCheck()
        xenrt.TEC().logverbose("Installed Active Directory Server. (Domain: %s)" % (self.domainname))

    def installOnWS2008(self):
        dcpromo = """
[DCInstall]
ReplicaOrNewDomain=Domain
NewDomain=Forest
NewDomainDNSName=%s
ForestLevel=%s
DomainNetbiosName=%s
DomainLevel=%s
InstallDNS=Yes
ConfirmGc=Yes
CreateDNSDelegation=No
DatabasePath="C:\Windows\\NTDS"
LogPath="C:\Windows\\NTDS"
SYSVOLPath="C:\Windows\SYSVOL"
SafeModeAdminPassword=%s
RebootOnSuccess=No
""" % (self.domainname, self.forestMode, self.netbiosname, self.domainMode, self.place.password)
        self.place.xmlrpcCreateFile("c:\\ad.txt", dcpromo)
        self.place.xmlrpcExec("dcpromo.exe /unattend:c:\\ad.txt\n"
                              "netsh advfirewall set domainprofile "
                              "firewallpolicy allowinbound,allowoutbound",
                               timeout=1800, returnerror=False)
        self.place.xmlrpcRemoveFile("c:\\ad.txt")
        current = self.place.winRegLookup("HKLM",
                                          "SYSTEM\\CurrentControlSet\\Services\\Netlogon",
                                          "DependOnService")
        self.place.winRegAdd("HKLM",
                             "SYSTEM\\CurrentControlSet\\Services\\Netlogon",
                             "DependOnService",
                             "MULTI_SZ",
                              current + ["DNS"])

    def installOnWS2012(self):
        self.place.xmlrpcExec("install-WindowsFeature AD-Domain-Services",powershell=True)
        psscript = """Import-Module ADDSDeployment;
Install-ADDSForest `
-CreateDnsDelegation:$false `
-DatabasePath "C:\Windows\\NTDS" `
-DomainMode "%s" `
-DomainName "%s" `
-DomainNetbiosName "%s" `
-ForestMode "%s" `
-InstallDns:$true `
-LogPath "C:\Windows\\NTDS" `
-NoRebootOnCompletion:$true `
-SysvolPath "C:\Windows\SYSVOL" `
-Force:$true `
-Confirm:$false `
-SafeModeAdministratorPassword `
(ConvertTo-SecureString '%s' -AsPlainText -Force) """ % (self.domainMode, self.domainname, self.netbiosname, self.forestMode, self.place.password)
        self.place.xmlrpcExec(psscript,powershell=True,returndata=True)
        self.place.winRegAdd("HKLM",
                           "software\\microsoft\\windows nt\\currentversion\\winlogon",
                           "DefaultDomainName",
                           "SZ",
                            self.netbiosname)

    def uninstall(self):
        # "Demote" the AD controller.
        if float(self.place.xmlrpcWindowsVersion()) < 6.3:
            dcpromo = """
[DCInstall]
UserName=%s
Password=%s
UserDomain
AdministratorPassword=%s
IsLastDCInDomain=Yes
RebootOnSuccess=Yes
""" % (self.place.superuser, self.place.password, self.place.password)
            self.place.xmlrpcCreateFile("c:\\ad.txt", dcpromo)
            self.place.xmlrpcExec("dcpromo.exe /unattend:c:\\ad.txt",
                                   timeout=1800, returnerror=False)
            self.place.xmlrpcRemoveFile("c:\\ad.txt")
            self.place.reboot()
            xenrt.TEC().logverbose("Uninstalled Active Directory Server. (Domain: %s)" % (self.domainname))
        elif float(self.place.xmlrpcWindowsVersion()) == 6.3:
            script = """Uninstall-ADDSDomainController `
-NoRebootOnCompletion:$true `
-confirm:$false `
-LastDomainControllerInDomain:$true `
-IgnoreLastDnsServerForZone:$true `
-RemoveApplicationPartitions:$true `
-LocalAdministratorPassword: `
(ConvertTo-SecureString '%s' -AsPlainText -Force) """ % (self.place.password)
            self.place.disableWindowsPasswordComplexityCheck()
            self.place.xmlrpcExec(script,powershell=True,returndata=True)
            self.place.reboot()
            self.place.xmlrpcExec("uninstall-WindowsFeature AD-Domain-Services",powershell=True)
            self.place.reboot()

    def debugDump(self, fd=sys.stdout):
        fd.write("AD groups and users on %s\n" % (self.place.getName()))
        for group in self.groups:
            fd.write("\nGroup %s:\n" % (group.dn))
            for member in group.members:
                fd.write("  %s\n" % (member.dn))

class CVSMServer(object):

    CLIPATH = '"c:\\program files\\citrix\\storagelink\\client\\csl.exe"'

    def __init__(self, place):
        self.place = place
        try:
            self.place.xmlrpcExec("sc query StorageLink")
        except:
            self.place.installCVSM()
        if not self.place.xmlrpcFileExists(self.CLIPATH.replace('"', "")):
            self.place.installCVSMCLI()
        if xenrt.TEC().lookup("OPTION_DEBUG_CVSM", False, boolean=True):
            self.enableDebugTracing()

    def cli(self, command):
        commands = []
        commands.append(self.CLIPATH)
        commands.append(command)
        commands.append("xml")
        reply = self.place.xmlrpcExec(string.join(commands),
                                      returndata=True,
                                      returnerror=False)
        xmltext = re.search("<.*>", reply, re.DOTALL)
        if xmltext:
            return xmltext.group()
        else:
            return xmltext

    def xpath(self, expression, xmltext):
        xmltree = libxml2.parseDoc(xmltext)
        nodes = xmltree.xpathEval(expression)
        return map(lambda x:x.getContent(), nodes)

    def enableDebugTracing(self, enable=True):
        if enable:
            level = "debug"
        else:
            level = "info"
        self.cli("srv-trace-level-set trace-level=%s" % (level))

    def addStorageSystem(self, resource):
        resource.preAddStorageSystemHook(self)
        ipparts = resource.getTarget().split(":")
        if len(ipparts) > 1:
            target = "ipaddress=%s port=%s" % (ipparts[0], ipparts[1])
        else:
            target = "ipaddress=%s" % (ipparts[0])
        if resource.getNamespace():
            target += " namespace=%s" % resource.getNamespace()
        reply = self.cli('sc-add name="%s" '
                                'adapter-id=%s '
                                '%s '
                                'username=%s '
                                'password=%s' %
                                (resource.getName(),
                                 resource.getType(),
                                 target,
                                 resource.getUsername(),
                                 resource.getPassword()))
        try:
            return self.xpath("//ssid", reply).pop()
        except:
            return xenrt.XRTFailure("Invalid XML returned")


    def removeStorageSystem(self, resource):
        self.cli("sc-remove name=%s" % (resource.getName()))

    def getStorageSystemId(self, resource):
        return self.xpath("//ssid[../../friendlyName='%s']" %
                          (resource.getName()), self.cli("sc-list")).pop()

    def getStoragePoolId(self, resource, key, value):
        ssid = self.getStorageSystemId(resource)
        return self.xpath("//storagePoolId[preceding-sibling::%s='%s']" %
                          (key, value), self.cli("sp-list ssid=%s" % (ssid))).pop()

    def addXenServerHost(self, host, username=None, password=None):
        if not username:
            username = "root"
        if not password:
            password = host.password
        if not password:
            password = xenrt.TEC().lookup("ROOT_PASSWORD")
        attempts = 0
        while True:
            attempts = attempts + 1
            reply = self.cli('host-add hostname="%s" username="%s" '
                             'password="%s" hypervisor-type=xen' %
                             (host.getIP(), username, password))
            if "License not granted for host" in reply:
                if attempts >= 3:
                    raise xenrt.XRTError("Unable to license host through "
                                         "StorageLink",
                                         host.getName())
                xenrt.sleep(120)
                continue
            uuid = host.getMyHostUUID()
            if not uuid in reply:
                raise xenrt.XRTFailure("Host UUID not found in host-add output",
                                       uuid)
            break

    def isHostKnownToCVSM(self, host):
        uuid = host.getMyHostUUID()
        data = self.cli('host-list')
        return uuid in data

class DemoLinuxBase(object):
    """Base DLVM Appliance Class for PV DLVM Appliance and HVM DLVM Appliance"""

    def __init__(self, place, password):
        self.place = place
        self.password = password
        if self.place:
            self.place.password = self.password

    def doFirstbootUnattendedSetup(self):
        pass

    def doLogin(self):
        pass

    def installSSH(self):
        pass

class DemoLinuxVM(DemoLinuxBase):
    """An object to represent a Centos 5.7 based Citrix Demonstration Linux Virtual Machine"""

    def __init__(self, place):
        password = xenrt.TEC().lookup("DEFAULT_PASSWORD")
        super(DemoLinuxVM, self).__init__(place, password)

    def doFirstbootUnattendedSetup(self):
        # choose root passwd: 'xensource'
        self.place.writeToConsole("%s\\n" % self.password)
        xenrt.sleep(5)
        # retype root passwd: 'xensource'
        self.place.writeToConsole("%s\\n" % self.password)
        xenrt.sleep(5)

    def doLogin(self):
        self.place.writeToConsole("root\\n")
        xenrt.sleep(5)
        self.place.writeToConsole("%s\\n" % self.password)
        xenrt.sleep(5)

    def installSSH(self):
        self.place.writeToConsole("yum -y install openssh-server\\n")
        xenrt.sleep(360)

class DemoLinuxVMHVM(DemoLinuxBase):
    """An object to represent a Centos 7.* based Citrix Demonstration Linux Virtual Machine"""

    def __init__(self, place):
        password = xenrt.TEC().lookup("VPX_DEFAULT_PASSWORD", "citrix") # by default vpx root's password
        super(DemoLinuxVMHVM, self).__init__(place, password)

    def doFirstbootUnattendedSetup(self):
        command = "/sbin/chkconfig rootpassword off"
        self.place.execguest(command)
        xenrt.sleep(60)
        self.place.lifecycleOperation("vm-reboot", force=True)
        self.place.waitReadyAfterStart()

class ApplianceFactory(object):
    def create(self, guest, version="CentOS7"):
        if version == "CentOS7":
            return self._createHVM(guest)
        else:
            return self._createLegacy(guest)

    def _createHVM(self, guest):
        raise xenrt.XRTError("Not Implemented")

    def _createLegacy(self, guest):
        raise xenrt.XRTError("Not Implemented")

class WlbApplianceFactory(ApplianceFactory):
    def _createHVM(self, guest):
        return WlbApplianceServerHVM(guest)

    def _createLegacy(self, guest):
        return WlbApplianceServer(guest)

class ConversionManagerApplianceFactory(ApplianceFactory):
    def _createHVM(self, guest):
        return ConversionApplianceServerHVM(guest)

    def _createLegacy(self, guest):
        return ConversionApplianceServer(guest)

class DLVMApplianceFactory(ApplianceFactory):
    def _createHVM(self, guest):
        return DemoLinuxVMHVM(guest)

    def _createLegacy(self, guest):
        return DemoLinuxVM(guest)

class WlbApplianceBase(object):
    """Base WLB Appliance Class for PV WLB Appliance Server and HVM WLB Appliance Server"""

    def __init__(self, place, password):
        self.place = place
        self.password = password
        self.wlb_password = self.password
        if self.place:
            self.place.password = self.password
        self.wlb_username = "wlbuser"
        self.wlb_port = "8012" # default port

    def doFirstbootUnattendedSetup(self):
        pass
        
    def doLogin(self):
        pass

    def installSSH(self):
        pass

    def doVerboseLogs(self):
        pass

    def doSanityChecks(self):
        pass


class WlbApplianceServer(WlbApplianceBase):
    """An object to represent a WLB Appliance Server"""

    def __init__(self, place):
        password = xenrt.TEC().lookup("DEFAULT_PASSWORD")
        super(WlbApplianceServer, self).__init__(place, password)
        
    def doFirstbootUnattendedSetup(self):
        # Send some suitable keystrokes to go through the initial setup
        # configuration during the appliance firstboot
        # Accept EULA? (Tampa onwards)
        if isinstance(self.place.host, xenrt.lib.xenserver.TampaHost):
            #send "y"
            self.place.writeToConsole("y\\n")
            xenrt.sleep(5)
        # screen 1
        # choose root passwd: 'xensource'
        self.place.writeToConsole("%s\\n" % self.password)
        xenrt.sleep(5)
        # retype root passwd: 'xensource'
        self.place.writeToConsole("%s\\n" % self.password)
        xenrt.sleep(5)
        # screen 2
        # specify hostname: 'wlbvm<enter>'
        self.place.writeToConsole("wlbvm\\n")
        xenrt.sleep(5)
        # enter domain suffix: 'xenrt.local<enter'
        self.place.writeToConsole("xenrt.local\\n")
        xenrt.sleep(5)
        # would you like to use dhcp: 'y<enter>'
        self.place.writeToConsole("y\\n")
        xenrt.sleep(5)
        # screen 3
        # are these settings correct: 'y<enter>'
        self.place.writeToConsole("y\\n")
        xenrt.sleep(5)
        # wait for swap to be created
        xenrt.sleep(300)
        # screen 4
        # press any key to continue
        #self.place.writeToConsole("\\n")
        xenrt.sleep(30)
        # screen 5
        # postgres username, empty for default postgres username
        self.place.writeToConsole("\\n")
        xenrt.sleep(5)
        # password for postgres
        self.place.writeToConsole("%s\\n" % self.password)
        xenrt.sleep(5)
        # please confirm password
        self.place.writeToConsole("%s\\n" % self.password)
        # wait for postgres functions to be loaded and db to be restarted
        xenrt.sleep(45)
        # wlb service username
        self.place.writeToConsole("%s\\n" % self.wlb_username)
        xenrt.sleep(5)
        # wlb service password
        self.place.writeToConsole("%s\\n" % self.password)
        xenrt.sleep(5)
        # confirm wlb service password
        self.place.writeToConsole("%s\\n" % self.password)
        xenrt.sleep(5)
        # port for wlb service, empty for default 8012
        self.place.writeToConsole("\\n")
        xenrt.sleep(15)

    def doLogin(self):
        self.place.writeToConsole("root\\n")
        xenrt.sleep(5)
        self.place.writeToConsole("%s\\n" % self.password)
        xenrt.sleep(5)

    def installSSH(self):
        self.place.writeToConsole("yum -y install openssh-server\\n")
        xenrt.sleep(360)
        #self.place.writeToConsole("service sshd start\\n")
        #xenrt.sleep(10)

    def doVerboseLogs(self):
        if isinstance(self.place.host, xenrt.lib.xenserver.TampaHost):
            #conf file is different in wlb Tampa onwards
            self.place.writeToConsole("sed -i \"s/\(AnalEngTrace\).*/\\1 = 1/\" /opt/citrix/wlb/wlb.conf\\n")
            xenrt.sleep(2)
            self.place.writeToConsole("sed -i \"s/\(DataCompactionTrace\).*/\\1 = 1/\" /opt/citrix/wlb/wlb.conf\\n")
            xenrt.sleep(2)
            self.place.writeToConsole("sed -i \"s/\(DataGroomingTrace\).*/\\1 = 1/\" /opt/citrix/wlb/wlb.conf\\n")
            xenrt.sleep(2)
            self.place.writeToConsole("sed -i \"s/\(ScoreHostTrace\).*/\\1 = 1/\" /opt/citrix/wlb/wlb.conf\\n")
            xenrt.sleep(2)
            self.place.writeToConsole("sed -i \"s/\(WlbWebServiceTrace\).*/\\1 = 1/\" /opt/citrix/wlb/wlb.conf\\n")
            xenrt.sleep(2)
            self.place.writeToConsole("echo \"VerboseTraceEnabled = 1\" >> /opt/citrix/wlb/wlb.conf\\n")
            xenrt.sleep(2)
            if isinstance(self.place.host, xenrt.lib.xenserver.DundeeHost):
                self.place.writeToConsole("sed -i \"s/\(SoapDataTrace\).*/\\1 = 1/\" /opt/citrix/wlb/wlb.conf\\n")
                xenrt.sleep(2)
        else:
            self.place.writeToConsole("sed \"s/AnalEngTrace>0/AnalEngTrace>1/\" < /opt/citrix/wlb/wlb.conf > /opt/citrix/wlb/wlb.conf.tmp && rm /opt/citrix/wlb/wlb.conf && mv /opt/citrix/wlb/wlb.conf.tmp /opt/citrix/wlb/wlb.conf\\n")
            xenrt.sleep(5)
            self.place.writeToConsole("sed \"s/WlbWebServiceTrace>0/WlbWebServiceTrace>1/\" < /opt/citrix/wlb/wlb.conf > /opt/citrix/wlb/wlb.conf.tmp && rm /opt/citrix/wlb/wlb.conf && mv /opt/citrix/wlb/wlb.conf.tmp /opt/citrix/wlb/wlb.conf\\n")
            xenrt.sleep(5)

    def doSanityChecks(self):
        # sanity checks after automated setup
        # check if the wlb server is listening on the expected port
        out = self.place.writeToConsole("netstat -a | grep 8012 | wc -l\\n",1,cuthdlines=1).strip()
        if out != "1":
            raise xenrt.XRTFailure("WLB appliance not listening on expected port 8012")

class WlbApplianceServerHVM(WlbApplianceBase):
    """An object to represent a new WLB Appliance Server, which is a CentOS 7 HVM guest"""

    def __init__(self, place):
        password = xenrt.TEC().lookup("VPX_DEFAULT_PASSWORD", "citrix") # by default vpx root's password
        super(WlbApplianceServerHVM, self).__init__(place, password)
        
    def doFirstbootUnattendedSetup(self):
        # wlb_self_configure.sh [wlbusername] [wlbpassword] [pgsqluser] [pgsqlpassword] [hostname] [domainname]
        command = "/etc/init.d/wlb_self_configure.sh %s %s %s %s %s %s" % (self.wlb_username, self.wlb_password, "postgres", "postgres", "wlbvm", "xenrt.local")
        self.place.execguest(command)
        xenrt.sleep(60)
        self.place.lifecycleOperation("vm-reboot", force=True)
        self.place.waitReadyAfterStart()

    def doVerboseLogs(self):
        if isinstance(self.place.host, xenrt.lib.xenserver.TampaHost):
            #conf file is different in wlb Tampa onwards
            self.place.execguest("sed -i \"s/\(AnalEngTrace\).*/\\1 = 1/\" /opt/citrix/wlb/wlb.conf")
            xenrt.sleep(2)
            self.place.execguest("sed -i \"s/\(DataCompactionTrace\).*/\\1 = 1/\" /opt/citrix/wlb/wlb.conf")
            xenrt.sleep(2)
            self.place.execguest("sed -i \"s/\(DataGroomingTrace\).*/\\1 = 1/\" /opt/citrix/wlb/wlb.conf")
            xenrt.sleep(2)
            self.place.execguest("sed -i \"s/\(ScoreHostTrace\).*/\\1 = 1/\" /opt/citrix/wlb/wlb.conf")
            xenrt.sleep(2)
            self.place.execguest("sed -i \"s/\(WlbWebServiceTrace\).*/\\1 = 1/\" /opt/citrix/wlb/wlb.conf")
            xenrt.sleep(2)
            self.place.execguest("echo \"VerboseTraceEnabled = 1\" >> /opt/citrix/wlb/wlb.conf")
            xenrt.sleep(2)
            if isinstance(self.place.host, xenrt.lib.xenserver.DundeeHost):
                self.place.execguest("sed -i \"s/\(SoapDataTrace\).*/\\1 = 1/\" /opt/citrix/wlb/wlb.conf")
                xenrt.sleep(2)
        else:
            self.place.execguest("sed \"s/AnalEngTrace>0/AnalEngTrace>1/\" < /opt/citrix/wlb/wlb.conf > /opt/citrix/wlb/wlb.conf.tmp && rm /opt/citrix/wlb/wlb.conf && mv /opt/citrix/wlb/wlb.conf.tmp /opt/citrix/wlb/wlb.conf")
            xenrt.sleep(5)
            self.place.execguest("sed \"s/WlbWebServiceTrace>0/WlbWebServiceTrace>1/\" < /opt/citrix/wlb/wlb.conf > /opt/citrix/wlb/wlb.conf.tmp && rm /opt/citrix/wlb/wlb.conf && mv /opt/citrix/wlb/wlb.conf.tmp /opt/citrix/wlb/wlb.conf")
            xenrt.sleep(5)

    def doSanityChecks(self):
        # sanity checks after automated setup
        # check if the wlb server is listening on the expected port
        out = self.place.execguest("netstat -a | grep 8012 | wc -l").strip()
        try:
            # Occasionally, pid or inode number equals to 8012, the above out would be 2 or 3.
            # It has has been observed in test.
            count = int(out)
            if count < 1:
                raise xenrt.XRTFailure("WLB appliance not listening on expected port 8012")
        except:
            raise xenrt.XRTFailure("WLB appliance not listening on expected port 8012")

class V6LicenseServer(object):
    """An object to represent a V6 License Server"""

    def __init__(self, place, useEarlyRelease=None, install=True, host=None):
        self.licenses = []
        self.licensedir = None
        self.place = place
        self.workdir = None
        self.port = None

        p = None
        if self.place.windows:
            # Install a Windows V6 License Server
            rtmp = self.place.xmlrpcTempDir()
            self.place.xmlrpcUnpackTarball("%s/v6.tgz" %
                                      (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                           rtmp)
            if install:
                rempath = "%s\\v6\\windows\\CTX_Licensing.msi" % (rtmp)
                self.place.xmlrpcExec("msiexec /i %s /quiet /qn /lv* c:\\installCTXLicensing.log" % (rempath))
            p = self.place.xmlrpcReadFile("%s\\v6\\conf" % (rtmp)).strip()
            self.workdir = rtmp
        else:
            if not self.place.password:
                self.place.password = xenrt.TEC().lookup("DEFAULT_PASSWORD")
            if self.place.getState() != "UP":
                self.place.lifecycleOperation("vm-start",specifyOn=True)
                # Wait for the VM to come up.
                xenrt.TEC().progress("Waiting for the VM to enter the UP state")
                self.place.poll("UP", pollperiod=5)
                xenrt.sleep(120)
            # Install the License Server VPX
            # Press enter to start
            self.place.writeToConsole("\\n")
            xenrt.sleep(5)

            # Enter UNIX password for root
            self.place.writeToConsole("%s\\n" % self.place.password)
            xenrt.sleep(5)

            # Retype UNIX password for root
            self.place.writeToConsole("%s\\n" % self.place.password)
            xenrt.sleep(5)

            # Enter hostname
            self.place.writeToConsole("licenseServer\\n")
            xenrt.sleep(5)

            # Enter domain name
            self.place.writeToConsole("testdev.hq.xensource.com\\n")
            xenrt.sleep(5)

            # Use DHCP?
            self.place.writeToConsole("y\\n")
            xenrt.sleep(5)

            # Are these settings correct?
            self.place.writeToConsole("y\\n")
            # Wait for DHCP
            xenrt.sleep(60)

            # Username
            self.place.writeToConsole("root\\n")
            xenrt.sleep(5)

            # Enter web admin password
            self.place.writeToConsole("%s\\n" % self.place.password)
            xenrt.sleep(5)

            # Retype web admin password
            self.place.writeToConsole("%s\\n" % self.place.password)
            # Wait a bit longer for login prompt
            xenrt.sleep(60)

            self.place.mainip = self.place.getVIFs()['eth0'][1]
            v6dir = xenrt.TEC().tempDir()
            xenrt.util.command("tar -xvzf %s/v6.tgz -C %s v6/conf" % (xenrt.TEC().lookup("TEST_TARBALL_ROOT"), v6dir))
            f = open("%s/v6/conf" % v6dir)
            p = f.read()
            f.close()

             # Press enter to start
            self.place.writeToConsole("\\n")
            xenrt.sleep(5)

            # Now we login and install SSH

            # Username
            self.place.writeToConsole("root\\n")
            xenrt.sleep(5)
            # Password
            self.place.writeToConsole("%s\\n" % self.place.password)
            xenrt.sleep(5)

            # Sort out the mirrors in the yum config

            self.place.writeToConsole("sed -i \"/mirrorlist/d\" /etc/yum.repos.d/*\\n")
            xenrt.sleep(5)
            self.place.writeToConsole("sed -i \"s@#baseurl=http://mirror.centos.org/centos/\$releasever/os/\$basearch/@baseurl=%s@\" /etc/yum.repos.d/*\\n" % xenrt.getLinuxRepo("centos55", "x86-64", "HTTP"))
            xenrt.sleep(5)

            #Add the root to lmadmin group so the root has priviledges to lmreread                       
            self.place.writeToConsole("sed -i 's/lmadmin:x:500:ctxlsuser/lmadmin:x:500:ctxlsuser,root/g' /etc/group \\n")
            xenrt.sleep(5)
            self.place.writeToConsole("sed -i 's/lmadmin:x:500:/lmadmin:x:500:ctxlsuser,root/g' /etc/group \\n")
            xenrt.sleep(5)

            # Install SSH and SCP
            self.place.writeToConsole("yum clean all\\n")
            xenrt.sleep(5)

            self.place.writeToConsole("yum install -y --disablerepo=* --enablerepo=base openssh-server openssh openssh-clients\\n")
            # Wait for installation complete
            xenrt.sleep(60)

            # Allow SSH through the firewall
            self.place.writeToConsole("iptables -I INPUT -i eth0 -p tcp --dport 22 -j ACCEPT\\n")
            xenrt.sleep(5)
            # Save the iptables config
            self.place.writeToConsole("iptables-save > /etc/sysconfig/iptables\\n")
            xenrt.sleep(5)

            self.workdir = "/opt/citrix/licensing"

        # Get licenses
        self.p = p
        self.changeLicenseMode(useEarlyRelease, host)

    def changeLicenseMode(self, useEarlyRelease, host=None):
        """Change between retail and earlyrelease licensing"""

        self.licensedir = xenrt.TEC().tempDir()

        er = ""
        if not host:
            host = self.place.host
        if useEarlyRelease:
            er = "er"
        elif useEarlyRelease is None and (host.special.has_key('v6earlyrelease') and host.special['v6earlyrelease']):
            er = "er"
        zipfile = "%s/keys/citrix/v6%s.zip" % (xenrt.TEC().lookup("XENRT_CONF"), er)
        xenrt.TEC().logverbose("Looking for V6 zip file: %s" % (zipfile))
        if not os.path.exists(zipfile):
            raise xenrt.XRTError("Cannot find V6 license zip file")
        xenrt.util.command("unzip -P %s -d %s %s" % (self.p, self.licensedir, zipfile))

    def getAddress(self):
        return self.place.getIP()

    def getPort(self):
        if self.port:
            return self.port
        return 27000

    def addLicense(self, license, useEarlyRelease = None):
        """Add a license to the license server"""

        if license in self.licenses:
            raise xenrt.XRTError("License %s is already installed on the "
                                 "license server" % (license))
        if not os.path.isdir(self.licensedir):
            self.changeLicenseMode(useEarlyRelease)

        # Check the license exists
        l = "%s/%s.lic" % (self.licensedir, license)
        if not os.path.exists(l):
            raise xenrt.XRTError("License %s not found" % (license))


        if self.place.windows:
            # Put it in the relevant location
            self.place.xmlrpcSendFile(l, "c:\\Program Files\\Citrix\\"
                                         "Licensing\\MyFiles\\%s.lic" %
                                         (license))
            # Re-read license dir
            self.place.xmlrpcExec("\"c:\\Program Files\\Citrix\\Licensing\\LS\\"
                                  "lmreread.exe\" -c @localhost")
        else:
            sftp = self.place.sftpClient()
            sftp.copyTo(l, "%s/myfiles/%s.lic" % (self.workdir, license))
            sftp.close()
            self.place.execcmd("cd %s && LS/lmreread" % (self.workdir))

        xenrt.TEC().logverbose("Added license %s to license server" % (license))
        self.licenses.append(license)

    def removeLicense(self, license):
        """Remove a license from the license server"""

        if not license in self.licenses:
            raise xenrt.XRTError("License is not installed on the license server")

        if self.place.windows:
            l = "c:\\Program Files\\Citrix\\Licensing\\MyFiles\\%s.lic" % (license)
            # Stop the v6 daemon
            self.place.xmlrpcExec("net stop \"Citrix Licensing\"", returnerror=False)
            # Delete the license file
            self.place.xmlrpcExec("del \"%s\"" % (l))
            # Start the daemon
            self.place.xmlrpcExec("net start \"Citrix Licensing\"")
        else:

            self.place.writeToConsole("/etc/init.d/citrixlicensing stop\\n")
            xenrt.sleep(20)
            self.place.execcmd("rm -f %s/myfiles/%s.lic" % (self.workdir, license))
            self.place.writeToConsole("/etc/init.d/citrixlicensing start\\n")
            xenrt.sleep(20)
            #A bit of hack for a successful lmreread i.e stop and start again
            self.place.writeToConsole("/etc/init.d/citrixlicensing stop\\n")
            xenrt.sleep(30)
            self.place.writeToConsole("/etc/init.d/citrixlicensing start\\n")
            xenrt.sleep(30)

            #restarting license server to make sure that everything is working fine
            self.place.reboot()

            try:
                self.place.execcmd("cd %s && LS/lmreread" % (self.workdir))
            except:
                xenrt.sleep(300) # Allow a bit longer for the license server to start
                try:
                    self.place.execcmd("cd %s && LS/lmreread" % (self.workdir))
                except:
                    self.place.reboot()
                    xenrt.sleep(30)
                    self.place.execcmd("cd %s && LS/lmreread" % (self.workdir))
            self.port = None

        xenrt.TEC().logverbose("Removed license %s from license server" % (license))
        self.licenses.remove(license)

    def removeAllLicenses(self):
        """Remove all licenses from the license server"""

        xenrt.TEC().logverbose("Removing all licenses from license server")
        licensesToRemove = copy.copy(self.licenses)
        for l in licensesToRemove:
            self.removeLicense(l)

    def restart(self):
        """Restart the license server"""
        self.stop()
        self.start()

    def stop(self):
        """Stop the license server"""
        if self.place.windows:
            # Stop the v6 daemon
            self.place.xmlrpcExec("net stop \"Citrix Licensing\"", returnerror=False)
        else:
            self.place.execcmd("/etc/init.d/citrixlicensing stop")

    def start(self):
        """Start the license server"""
        if self.place.windows:
            # Start the daemon
            self.place.xmlrpcExec("net start \"Citrix Licensing\"")
        else:
            self.place.execcmd("/etc/init.d/citrixlicensing start > /dev/null 2>&1 < /dev/null")
            xenrt.sleep(5)
            self.port = None

    def getLogfile(self):
        """Get the V6 server log file(s)"""

        if self.place.windows:
            pass # TODO
        else:
            sftp = self.place.sftpClient()
            try:
                sftp.copyTreeFrom("%s/LS/logs" % (self.workdir),
                              "%s/ls" % (xenrt.TEC().getLogdir()))
            except:
                xenrt.TEC().logverbose("V6 server log not found")
            sftp.close()

    def getLicenseUsage(self, feature):
        """Get the usage information for a specific license feature"""

        if self.place.windows:
            data = self.place.xmlrpcExec("\"c:\\Program Files\\Citrix"
                                         "\\Licensing\\LS\\lmstat\" -f %s "
                                         "-c @localhost" % (feature),
                                         returndata=True)
        else:
            data = self.place.execcmd("cd %s && LS/lmutil lmstat -f %s "
                                      "-c @localhost" % (self.workdir, feature))

        # Now parse the data with a horrendous looking regexp...
        usages = {}
        for l in data.splitlines():
            m = re.search("CXS(?:TP)? ([\w-]+) CXS(?:TP)? ([\w-]+) \((v\d+\.\d+)\) \([^\)]+\), start (\w+ \d+/\d+ \d+:\d+)", l)
            if m:
                usages[m.group(1)] = (m.group(2),m.group(3),m.group(4))

        return usages

    def getLicenseInUse(self,licenseType):
        """Get the number of licenses in use """

        if self.place.windows:
            xenrt.TEC().logverbose("Not implemented")
        else:
            data = self.place.execcmd("cd %s && LS/lmutil lmstat -f" % self.workdir)

        totalLicenses = 0  #Total number of licenses present on license server
        licenseInuse = 0   # Total number of licenses inuse
        for l in data.splitlines():
            if licenseType in l:
                totalLicenses = int(l.split("  ")[1].split(" ")[2])
                licenseInuse = int(l.split("  ")[2].split(" ")[2])
                break

        return totalLicenses, licenseInuse

class DVSCWebServices(object):

    def __init__(self, place, auto = True):
        self.place = place

        self.headers = {"Content-type": "application/x-www-form-urlencoded", "Accept": "text/plain", "Connection": "close"}
        self.path = "/ws.v1/"
        self.cookie = ''
        self.port = 443
        self.h1 = 0
        self.rsp = ''
        self.root = ''
        password = xenrt.TEC().lookup("DEV_ADMIN", None)
        if password != None:
            self.admin_pw = password
        else:
            self.admin_pw = 'admin'
        self.auto = auto
        self.keepAlive = False
        self.lock = threading.Lock()
        self.read = ""
        # auto = False allows us to test requests without login
        #if self.auto == True:
        #    self.login("admin", "admin")


    def request (self, method, url, headers=None, params=""):
        v = sys.version_info
        if v.major == 2 and ((v.minor == 7 and v.micro >= 9) or v.minor > 7):
            xenrt.TEC().logverbose("Disabling certificate verification on >=Python 2.7.9")
            ssl._create_default_https_context = ssl._create_unverified_context
        xenrt.TEC().logverbose("request")
        if self.auto == True and self.keepAlive == False:
            self.login("admin", self.admin_pw)
        self.lock.acquire()
        try:

            if self.keepAlive == False or self.h1 == 0:
                self.h1 = httplib.HTTPSConnection(self.place.getIP(), self.port)
            if self.cookie != '':
                self.headers["Cookie"] = self.cookie
            xenrt.TEC().logverbose("IP: %s" % (self.place.getIP()))
            xenrt.TEC().logverbose("METHOD: %s" % (method))
            xenrt.TEC().logverbose("URL: %s" % (url))
            xenrt.TEC().logverbose("PARAMS: %s" % (params))
            xenrt.TEC().logverbose("HEADERS: %s" % (self.headers))
            #self.h1.set_debuglevel(1)
            start = time.time()
            if headers == None:
                self.h1.request(method, url, params, self.headers)
            else:
                self.h1.request(method, url, params, headers)
            if time.time() - start > 120:
                # protect our lab resource
                raise xenrt.XRTFailure("HTTP Request taking more than 2 minutes, bailing")
            slow_rsp = True
            slow_rsp_counter = 0
            while slow_rsp == True:
                try:
                    xenrt.TEC().logverbose("waiting for response")
                    #self.h1.set_debuglevel(1)
                    self.rsp = self.h1.getresponse()
                    xenrt.TEC().logverbose("read response: %d, %s" % (self.rsp.status, self.rsp.reason))
                    self.read= self.rsp.read()

                except:
                    xenrt.sleep(0.2)
                    slow_rsp_counter += 1
                    if slow_rsp_counter == 20:
                        raise xenrt.XRTFailure("Cannot connect to controller")
                else:
                    slow_rsp = False
            self.cookie = self.rsp.getheader("Set-Cookie", self.cookie)
            xenrt.TEC().logverbose("cookie: %s" % (self.cookie))
        finally:
            self.lock.release()
        xenrt.TEC().logverbose("read: %s" % (self.read))



    # The following sectiom is included to keep the https seesion alive
    # it is optional as some tests require that the connection is not kept
    # alive. The connection times out at 3 seconds, hence the 2 second time
    # out is optimal
    def keepAliveMethod(self):
        xenrt.TEC().logverbose("keepAliveMethod")


        while self.keepAlive == True:
            self.lock.acquire()
            try:
                if self.cookie != '':
                    self.headers["Cookie"] = self.cookie
                xenrt.TEC().logverbose("Keep alive request: GET /ws.v1/nox/up")
                self.h1.request("GET", "/ws.v1/nox/up", "", self.headers)
                slow_rsp = True
                slow_rsp_counter = 0
                while slow_rsp == True:
                    try:
                        xenrt.TEC().logverbose("Waiting for keep alive response")
                        self.rsp = self.h1.getresponse()
                        me = self.rsp.read()
                        #xenrt.TEC().logverbose("me = %s" % (me))

                    except:
                        xenrt.sleep(0.2)
                        slow_rsp_counter += 1
                        if slow_rsp_counter == 20:
                            raise xenrt.XRTFailure("Cannot connect to controller")
                    else:
                        slow_rsp = False
                self.cookie = self.rsp.getheader("Set-Cookie", self.cookie)
                xenrt.TEC().logverbose("cookie: %s" % (self.cookie))
            finally:
                self.lock.release()
            xenrt.sleep(2)


    def keepDVSAlive(self):
        xenrt.TEC().logverbose("keepDVSAlive")
        self.login("admin", self.admin_pw)
        xenrt.TEC().logverbose("Logged In")

        self.keepAlive = True

        xenrt.pfarm([xenrt.PTask(self.keepAliveMethod)], wait=False)

    def stopKeepAlive(self):
        self.keepAlive = False

    # Generic HTTP(S) Methods
    def post(self, command, params, headers=None):
        url = self.path + command
        self.request("POST", url, headers, params)

    def get(self, command, params=None, headers=None):
        url = self.path + command
        self.request("GET", url, headers, "")

    def put(self, command, params=None, headers=None):
        url = self.path + command
        self.request("PUT", url, headers, params)

    def loginRequest(self, method, url, params, headers):
        #xenrt.TEC().logverbose("Login")
        self.lock.acquire()
        try:
            if self.h1 == 0:
                self.h1 = httplib.HTTPSConnection(self.place.getIP(), self.port)
            #xenrt.TEC().logverbose("METHOD: %s" % (method))
            #xenrt.TEC().logverbose("URL: %s" % (url))
            #xenrt.TEC().logverbose("PARAMS: %s" % (params))
            #xenrt.TEC().logverbose("HEADERS: %s" % headers)
            try:
                self.h1.request(method, url, params, headers)
            except:
                # sometimes the h1 connection is dropped after a timeout
                self.h1 = httplib.HTTPSConnection(self.place.getIP(), self.port)
                self.h1.request(method, url, params, headers)
            slow_rsp = True
            slow_rsp_counter = 0
            while slow_rsp == True:
                try:
                    #xenrt.TEC().logverbose("waiting for response")
                    #xenrt.TEC().logverbose("rsp = %s" % self.rsp)
                    self.rsp = self.h1.getresponse()
                    self.rsp.read()
                    #xenrt.TEC().logverbose("rsp read")
                    #xenrt.TEC().logverbose("%s" % self.rsp.getheaders)
                    self.cookie = self.rsp.getheader("Set-Cookie")
                    xenrt.TEC().logverbose("cookie: %s" % (self.cookie))
                    #xenrt.TEC().logverbose("got cookie %s" % self.cookie)
                except:
                    #xenrt.TEC().logverbose("rsp %s" % (self.rsp))
                    xenrt.sleep(0.2)
                    slow_rsp_counter += 1
                    if slow_rsp_counter == 20:
                        raise xenrt.XRTFailure("Cannot connect to controller")
                else:
                    slow_rsp = False
        finally:
            self.lock.release()
        if url != "/logout" and self.rsp.reason != "OK":
            raise xenrt.XRTFailure("Failed to login to controller with admin, %s reason %s" % (self.admin_pw, self.rsp.reason))


    def login(self, user, passw):
        xenrt.TEC().logverbose("Logging in with %s/%s" % (user, passw))
        headers = {"Content-type": "application/x-www-form-urlencoded", "Accept": "text/plain"}
        params = urllib.urlencode({"username": user, "password": passw})
        res = self.loginRequest('POST', '/ws.v1/login', params, headers)
        return res

    def updateAdminPassw(self, user, passw):
        headers = {"Content-type": "application/x-www-form-urlencoded", "Accept": "text/plain"}
        params = urllib.urlencode({"username": user, "password": passw})
        res = self.loginRequest('POST', '/ws.v1/adminuser/admin/password', params, headers)
        return res

    def logout(self):
        headers = {"Content-type": "application/x-www-form-urlencoded", "Accept": "text/plain"}
        params = ""
        self.keepAlive = False
        res = self.loginRequest('POST', '/logout', params, headers)
        return res



    def listNtpServers(self):
        res = self.get('ntp_daemon')
        return res

    def addNtpServer(self, address):
        res = self.put('ntp_daemon/add_server', address)
        return res

    def delete(self, command, params, headers=None):
        url = self.path + command
        self.request("DELETE", url, headers, params)


    # Generic Json Methods
    def getJson (self, url, json, headers=None):
        self.headers["Content-type"] = "application/json"
        return self.get(url, json, headers)

    def getAsJson (self, url, object, headers=None):
        json = simplejson.dumps(object)
        return self.getJson(url, json, headers)

    def putJson (self, url, json, headers=None):
        self.headers["Content-type"] = "application/json"
        return self.put(url, json, headers)

    def putAsJson (self, url, object, headers=None):
        json = simplejson.dumps(object)
        return self.putJson(url, json, headers)

    def postJson (self, json, url, headers=None):
        self.headers["Content-type"] = "application/json"
        return self.post(url, json, headers)

    def postAsJson (self, url, params, headers=None):
        json = simplejson.dumps(params)
        return self.postJson(json, url, headers)

    def deleteJson (self, json, url, headers=None):
        self.headers["Content-type"] = "application/json"
        return self.delete(url, json, headers)


    def deleteAsJson (self, url, params, headers=None):
        json = simplejson.dumps(params)
        return self.deleteJson(json, url, headers)

    # Methods on the Controller

    # looks for search key and value and returns the value of item key
    # Works but not pretty pythonise and refactor
    def getFromTree(self, mypath, searchKey, searchValue, itemKey):
        if self.root == '':
            self.root = mypath
        self.get(mypath)
        node = simplejson.loads(self.read)
        # Nodes can be a dictionary or a list of dictionaries
        if type(node) != list:
            node = [node]
        mylist = node
        for item in mylist:
            if searchKey in item and item[searchKey] == searchValue:
                if itemKey in item:
                    return item[itemKey]
            if 'children' in item:
                branches = [i['$ref'] for i in item['children']]
                if len(branches) == 0:
                    return
                for child in branches:
                    thispath = self.root + child
                    result = self.getFromTree(thispath, searchKey, searchValue, itemKey)
                    if result != None:
                        return result

    def getTreeNode(self, node):
        mypath = 'tree/node/' + node
        self.get(mypath)
        return simplejson.loads(self.read)

    # Methods on the Controller
    def addHostToController(self, host):
        params = {"type":"Xen", "name":"", "search_order":0,
                                "properties":[["master_address_1", host.getIP()],
                                ["username", 'root'], ["password", host.password],
                                ["steal_pool", "true"]]}
        self.postAsJson('datasource', params)
        # This operation take a few seconds to receive all the pool information from the vSwicthes
        xenrt.sleep(30)

    def getResourcePoolList(self):
        root = self.getTreeNode("")
        pools = []
        for item in root[0]['children']:
            pools.append(self.getTreeNode(item["$ref"])['name'])
        return pools

    def getPool(self, pool_name_rq):
        root = self.getTreeNode("")
        # Find Pool
        for item in root[0]['children']:
            pool_node = self.getTreeNode(item["$ref"])
            if pool_node['name'] == pool_name_rq:
                return pool_node, item
        raise xenrt.XRTFailure("Failed to get pool node '%s' in DVSC response. Possibly host connectivity is lost temporarily and pool name is replaced by slave." % pool_name_rq)

    # Pool level requests
    def getSubBranchesFromPool(self, pool_name_rq, tree_name):
        root = self.getTreeNode("")
        # Find Pool
        for item in root[0]['children']:
            pool_node = self.getTreeNode(item["$ref"])
            pool_name = pool_node['name']
            if pool_name == pool_name_rq:
                break
        # find 'XenServers'
        for item in pool_node['children']:
            pool_node_child = self.getTreeNode(item["$ref"])
            xenrt.TEC().logverbose("pool_node_child: %s" % pool_node_child)
            if pool_node_child['name'] == tree_name:
                break
        names = []
        for item in pool_node_child['children']:
            name=self.getTreeNode(item["$ref"])['name']
            xenrt.TEC().logverbose("name: %s" % name)
            names.append(name)

        return names

    def getHostsInPool(self, pool_name):
        return self.getSubBranchesFromPool(pool_name,'Xen Servers')

    def getVMsInPool(self, pool_name):
        return self.getSubBranchesFromPool(pool_name,'All Vms')

    def getNetworksInPool(self, pool_name):
        return self.getSubBranchesFromPool(pool_name,'Pool-wide Networks')

    def getVifsOnVM(self, vm_name):
        vm_children = self.getFromTree("tree/node/", 'name', vm_name, 'children')
        xenrt.TEC().logverbose("vm_children: %s" % vm_children)
        vifs = []
        for item in vm_children:
            vif_node = self.getTreeNode(item["$ref"])
            vifs.append(vif_node['name'])
        return vifs

    def getProtocols(self):
        self.get('protocol')
        return simplejson.loads(self.read)


    def findProtocol(self, name):
        protocols = self.getProtocols()
        for item in protocols:
            if item['name'] == name:
                return item
        return None

    # addProtoForACL
    # name: must be unique - will raise exception if not
    # src/dest: For TCP/UDP 0-65536 or None,
    #           For ICMP src = ICMP TYPE and dest = ICMP CODE
    # iptype tcp (6), udp(17), icmp(1), any(None)
    def addProtoForACL(self, name, src, dest, iptype, check=True):
        # check name is unique
        if check == True and self.findProtocol(name) != None:
            raise xenrt.XRTFailure("Protocol exists for name: ", name)
        protocol = {"src_port": None, "ethertype": 2048, "name": "",
                    "unidirectional": True, "dst_port": None, "iptype": None}
        # replace protocol fields
        protocol['name'] = name
        iptypes = {'ANY' : None, 'ICMP': 1, 'TCP': 6, 'UDP': 17}
        protocol['iptype'] = iptypes[iptype]
        if iptype != 'ANY':
            protocol['src_port'] = src
            protocol['dst_port'] = dest
        self.postAsJson('protocol', protocol)
        # return the protocol uid
        xenrt.TEC().logverbose("read rsp %s" % (self.read))
        return simplejson.loads(self.read)['uid']

    def deleteProtocol(self, name):
        proto = self.findProtocol(name)
        if proto == None:
            raise xenrt.XRTFailure("Protocol does not exist for name: ", name)
        path = 'protocol/%d' % proto['uid']
        self.deleteAsJson(path, proto)

    def removeHostFromController(self, host):
        self.get('datasource')
        datasources = simplejson.loads(self.read)
        xenrt.TEC().logverbose("Datasources: %s" % (datasources))
        for item in datasources:
            if item['properties'] != [] and (item['properties'][0][1] == host.getIP() or item['properties'][1][1] == host.getIP()):
                uid = item['uid']
        if uid:
            params = {"uid": uid, "type":"Xen", "name":"", "search_order":0,
                                "properties":[["master_address_1", host.getIP()],
                                ["username", 'root'], ["password", host.password],
                                ["steal_pool", "false"]]}
            path = 'datasource/%d' % uid
            self.deleteAsJson(path, params)
        else:
            warning("Unable to find the host in the controller.")

    def addACLRuleToVM(self, guest_name, proto_name):

        vm_node_id = self.getFromTree("tree/node/", 'name', guest_name, 'tree_uid')

        # get the entire node
        vm_node = self.getTreeNode(vm_node_id)

        proto = self.findProtocol(proto_name)
        proto_uid = proto['uid']

        rules = ({"qos_limit_kbps": 0,
                   "acl_split_before": 1, "xen_type": "vm", "uid": "vm;14",
                   "qos_burst_kbps": 0,
                   "acl_rules": [{"direction": "out", "description": "",
                   "protocol_uid": 8, "remote_customs": [],
                   "remote_groups": [],
                   "invert_remote_addresses": False,
                   "action": "deny",
                   "uid": 17}], "qos":
                   "inherit", "rspan":
                   "inherit", "rspan_vlan": 0,
                   "qos_burst": "inherit",
                   "name": "xenrt097dcc274bb30393"})
        rules['uid'] = "vm;%d" % vm_node['uid']
        rules['acl_rules'][0]['direction'] = 'out'
        rules['acl_rules'][0]['protocol_uid'] = proto_uid
        rules['acl_rules'][0]['action'] = "deny"

        rules['acl_rules'][0]['uid'] = None
        rules['name'] = vm_node['name']

        path = 'role/' + rules['uid']

        xenrt.TEC().logverbose("Putting path: %s rules: %s" % (path, rules))
        self.putAsJson(path, rules)



    def addACLProtoToNode(self, vm_node, proto_uid, allowed="deny", split=1):

        rules = ({"qos_limit_kbps": 0,
                   "acl_split_before": split, "xen_type": "vm", "uid": "vm;14",
                   "qos_burst_kbps": 0,
                   "acl_rules": [{"direction": "out", "description": "",
                   "protocol_uid": 8, "remote_customs": [],
                   "remote_groups": [],
                   "invert_remote_addresses": False,
                   "action": "deny",
                   "uid": 17}], "qos":
                   "inherit", "rspan":
                   "inherit", "rspan_vlan": 0,
                   "qos_burst": "inherit",
                   "name": "xenrt097dcc274bb30393"})
        rules['uid'] = "vm;%d" % vm_node['uid']
        rules['acl_rules'][0]['direction'] = 'out'
        rules['acl_rules'][0]['protocol_uid'] = proto_uid
        rules['acl_rules'][0]['action'] = allowed

        rules['acl_rules'][0]['uid'] = None
        rules['name'] = vm_node['name']

        path = 'role/' + rules['uid']

        self.putAsJson(path, rules)

    def getGlobalRules(self):
        self.get("role/global;0")
        return simplejson.loads(self.read)

    def setGlobalRules(self, rules):
        self.putAsJson("role/global;0", rules)

    def getPoolRules(self, master_ip):
        rc = self.getFromTree("tree/node/", 'name', master_ip, "uid")
        if type(rc) == type(None):
            # XXX: Perhaps once we discover the nature of this issue, we can
            #      add a more descriptive message here
            raise xenrt.XRTFailure("getFromTree didn't return any branches")

        path = "role/pool;%d" % (rc)
        self.get(path)
        return simplejson.loads(self.read)

    def setPoolRules(self, master_ip, rules):
        path = "role/pool;%d" % self.getFromTree("tree/node/", 'name', master_ip, "uid")
        self.putAsJson(path, rules)

    def getNetworkRules(self, network_name):
        path = "role/network;%d" % self.getFromTree("tree/node/", 'name', network_name, "uid")
        self.get(path)
        return simplejson.loads(self.read)

    def setNetworkRules(self, network_name, rules):
        path = "role/network;%d" % self.getFromTree("tree/node/", 'name', network_name, "uid")
        self.putAsJson(path, rules)

    def getVMRules(self, vm_name):
        path = "role/vm;%d" % self.getFromTree("tree/node/", 'name', vm_name, "uid")
        self.get(path)
        return simplejson.loads(self.read)

    def setVMRules(self, vm_name, rules):
        path = "role/vm;%d" % self.getFromTree("tree/node/", 'name', vm_name, "uid")
        self.putAsJson(path, rules)

    def getVIFRules(self, vif_mac):
        vif_name = "VIF (%s)" % vif_mac
        path = "role/vif;%d" % self.getFromTree("tree/node/", 'name', vif_name, "uid")
        self.get(path)
        return simplejson.loads(self.read)

    def setVIFRules(self, vif_mac, rules):
        vif_name = "VIF (%s)" % vif_mac
        path = "role/vif;%d" % self.getFromTree("tree/node/", 'name', vif_name, "uid")
        self.putAsJson(path, rules)


    # direction - "in"/"out"/"both"
    # proto_uid - as retrieved from self.findProtocol(proto_name)['uid']
    # action    - "allow"/"deny"
    def createACL(self, direction, proto_uid, description="", action="deny"):
        return {"direction": direction, "description": description,
                   "protocol_uid": proto_uid, "remote_customs": [],
                   "remote_groups": [],
                   "invert_remote_addresses": False,
                   "action": action,
                   "uid": None}

    def removeAllACLRules(self, guest_name):
        vm_node_id = self.getFromTree("tree/node/", 'name', guest_name, 'tree_uid')

        # get the entire node
        vm_node = self.getTreeNode(vm_node_id)

        rules = ({"qos_limit_kbps": 0,
                   "acl_split_before": 1, "xen_type": "vm", "uid": "vm;14",
                   "qos_burst_kbps": 0,
                   "acl_rules": [], "qos":
                   "inherit", "rspan":
                   "inherit", "rspan_vlan": 0,
                   "qos_burst": "inherit",
                   "name": "xenrt097dcc274bb30393"})
        rules['uid'] = "vm;%d" % vm_node['uid']
        rules['name'] = vm_node['name']

        path = 'role/' + rules['uid']

        self.putAsJson(path, rules)

    def removeAllACLRulesFromNode(self, vm_node):

        rules = ({"qos_limit_kbps": 0,
                   "acl_split_before": 1, "xen_type": "vm", "uid": "vm;14",
                   "qos_burst_kbps": 0,
                   "acl_rules": [], "qos":
                   "inherit", "rspan":
                   "inherit", "rspan_vlan": 0,
                   "qos_burst": "inherit",
                   "name": "xenrt097dcc274bb30393"})
        rules['uid'] = "vm;%d" % vm_node['uid']
        rules['name'] = vm_node['name']

        path = 'role/' + rules['uid']

        self.putAsJson(path, rules)

    def setQoSRules(self, rules, rate, burst):

        rules["qos_limit_kbps"] = rate
        rules["qos_burst_kbps"] = burst

        if rate ==  0:
            rules["qos"] = "inherit"
        else:
            rules["qos"] = "set"

        if burst == 0:
            rules["qos_burst"] = "inherit"
        else:
            rules["qos_burst"] = "set"




    # note this is set in Kbps and Kb
    # to remove set both to 0
    def setGlobalQoSPolicy(self, rate, burst):
        rules = self.getGlobalRules()
        self.setQoSRules(rules, rate, burst)
        self.setGlobalRules(rules)

    def setPoolQoSPolicy(self, master_ip, rate, burst):
        rule = self.getPoolRules(master_ip)
        self.setQoSRules(rule, rate, burst)
        self.setPoolRules(master_ip, rule)

    def setNetworkQoSPolicy(self, network_name, rate, burst):
        rule = self.getNetworkRules(network_name)
        self.setQoSRules(rule, rate, burst)
        self.setNetworkRules(network_name, rule)

    def setVMQoSPolicy(self, vm_name, rate, burst):
        rule = self.getVMRules(vm_name)
        self.setQoSRules(rule, rate, burst)
        self.setVMRules(vm_name, rule)

    def setVIFQoSPolicy(self, vif_mac, rate, burst):
        rule = self.getVIFRules(vif_mac)
        self.setQoSRules(rule, rate, burst)
        self.setVIFRules(vif_mac, rule)

    # Infomrs the controller of vlan rspan can be sent to
    def addRSPANTargetVLAN(self, vlan):
        try: self.removeRSPANTargetVLAN(vlan)
        except: pass
        path = "xen_directory/vlan/%d" % vlan
        self.postAsJson(path, "")

    def removeRSPANTargetVLAN(self, vlan):
        path="xen_directory/vlan/%d" % vlan
        self.deleteAsJson(path, "")

    # Mode: 0 = Fail open, 1 = fail closed
    def setPoolFailMode(self, pool_name, mode):
        pool_node, pool_branch = self.getPool(pool_name)
        pool_node['fail_mode'] = mode
        path="xen_directory/%s" % pool_node['uid']
        xenrt.TEC().logverbose("path: %s" % path)
        xenrt.TEC().logverbose("pool_node to put: %s" % str(pool_node))
        self.putAsJson(path, pool_node)

    def getPoolFailMode(self, pool_name):
        pool_node, pool_branch = self.getPool(pool_name)
        xenrt.TEC().logverbose("pool_node" % str(pool_node))
        return pool_node['fail_mode']



    # Simplified code based upon function from
    # http://code.activestate.com/recipes/146306/
    def encodeMultipartFormdata(self, name, path):
        f = open(path, "rb")
        value = f.read()
        f.close()

        BOUNDARY = mimetools.choose_boundary()
        CRLF = '\r\n'
        content_type = 'application/octet-stream'
        data =\
            [
            '--%s' % BOUNDARY,
            'Content-Disposition: form-data; name="%s"; filename="%s"' % (name, path),
            'Content-Type: %s' % content_type,
            '%s%s' % (CRLF, value),
            '--%s--%s' % (BOUNDARY, CRLF)
            ]
        content_type = 'multipart/form-data; boundary=%s' % BOUNDARY
        content_length = len(CRLF.join(data))
        body = CRLF.join(data)
        return content_type, content_length, body

    def patchFromFile(self, path):

        self.login("admin", self.admin_pw)
        data_name="update_file"
        content_type, content_length, body = self.encodeMultipartFormdata(data_name, path)
        headers = {'Content-Type': content_type,
                   'Content-Length': content_length,
                   'Transfer-Encoding': 'chunked',
                   "Cookie": self.cookie}

        command = 'nox/update_from_file'
        self.post(command, body, headers)
        # Need to wait for reboot
        xenrt.sleep(60)

    def setStaticIP(self, ip, netmask, gateway):
        data = {"name"      : "eth0",
                "dhcp"      : False,
                "address"   : ip,
                "netmask"   : netmask,
                "gateway"   : gateway
                }
        self.putAsJson("nox/local_config/interface/configured/eth0", data)

    def setDynamicIP(self):
        data = {"name"      : "eth0",
                "dhcp"      : True}
        self.putAsJson("nox/local_config/interface/configured/eth0", data)

    def setNetflowCollector(self, pool_name, ipaddress, port, use_vmanager):
        # syntax put https://<server_ip>/ws.v1/netflow/<pool_node_uid>
        # params {'other_servers' : 'collector_ip:collector_port', 'use_vmanager': 'true|false'}

        pool_node, pool_branch = self.getPool(pool_name)
        body = { 'other_servers' : "%s:%s" % (ipaddress, port),
                 'use_vmanager' : use_vmanager}
        self.putAsJson("netflow/%s" % pool_node['uid'], body)

class XenMobileApplianceServer(object):
    """An object to represent a XenMobile Appliance Server"""

    def __init__(self, guest):
        self.guest = guest
        self.password = xenrt.TEC().lookup("XENMOBILE_PASSWORD", "adminadmin")
        self.host = self.guest.getHost()

    def doFirstbootUnattendedSetup(self):
        """ Answer the first boot questions"""
        mac, _, _ = self.guest.getVIF("eth0")
        ip = xenrt.StaticIP4Addr(mac=mac).getAddr()
        self.guest.mainip = ip
        _, netmask = self.host.getNICNetworkAndMask(0)
        gateway = self.host.getGateway()
        dns = xenrt.TEC().lookup(["NETWORK_CONFIG", "DEFAULT", "NAMESERVERS"], "").split(",")[0].strip()

        # choose root passwd
        self.guest.writeToConsole("%s\\n" % self.password)
        xenrt.sleep(2)
        # retype root passwd
        self.guest.writeToConsole("%s\\n" % self.password)
        xenrt.sleep(2)
        # type static-ip
        self.guest.writeToConsole("%s\\n" % ip)
        xenrt.sleep(2)
        # type netmask
        self.guest.writeToConsole("%s\\n" % netmask)
        xenrt.sleep(2)
        # type gateway
        self.guest.writeToConsole("%s\\n" % gateway)
        xenrt.sleep(2)
        # type dns
        self.guest.writeToConsole("%s\\n" % dns)
        xenrt.sleep(2)
        # no secondary dns
        self.guest.writeToConsole("%s\\n" % "")
        xenrt.sleep(2)
        # commit settings y
        self.guest.writeToConsole("%s\\n" % "y")
        xenrt.sleep(5)
        # generate random passphrase y
        self.guest.writeToConsole("%s\\n" % "y")
        xenrt.sleep(2)
        # Federal Information Processing Standard (FIPS) mode n
        self.guest.writeToConsole("%s\\n" % "n")
        xenrt.sleep(2)
        # Database connection l
        self.guest.writeToConsole("%s\\n" % "l")
        xenrt.sleep(2)
        # commit settings y
        self.guest.writeToConsole("%s\\n" % "y")
        xenrt.sleep(10)
        # XenMobile hostname:
        self.guest.writeToConsole("%s\\n" % ip)
        xenrt.sleep(2)
        # commit settings y
        self.guest.writeToConsole("%s\\n" % "y")
        xenrt.sleep(2)
        # HTTP port - default to 80
        self.guest.writeToConsole("%s\\n" % "")
        xenrt.sleep(2)
        # HTTPs port - default to 443
        self.guest.writeToConsole("%s\\n" % "")
        xenrt.sleep(2)
        # HTTPs port no cert - default to 8443
        self.guest.writeToConsole("%s\\n" % "")
        xenrt.sleep(2)
        # HTTPs management - default to 4443
        self.guest.writeToConsole("%s\\n" % "")
        xenrt.sleep(2)
        # commit settings y
        self.guest.writeToConsole("%s\\n" % "y")
        xenrt.sleep(2)
        # same password for all certs -default y
        self.guest.writeToConsole("%s\\n" % "")
        xenrt.sleep(2)
        # password
        self.guest.writeToConsole("%s\\n" % self.password)
        xenrt.sleep(2)
        # password
        self.guest.writeToConsole("%s\\n" % self.password)
        xenrt.sleep(2)
        # commit settings y
        self.guest.writeToConsole("%s\\n" % "y")
        xenrt.sleep(5)
        # username - default to administrator
        self.guest.writeToConsole("%s\\n" % "")
        xenrt.sleep(2)
        # password
        self.guest.writeToConsole("%s\\n" % self.password)
        xenrt.sleep(2)
        # password
        self.guest.writeToConsole("%s\\n" % self.password)
        xenrt.sleep(2)
        # commit settings y
        self.guest.writeToConsole("%s\\n" % "y")
        xenrt.sleep(2)
        # Upgrade from previous release - default n
        self.guest.writeToConsole("%s\\n" % "")

class ConversionApplianceBase(object):
    """Base Conversion Appliance Class for PV Conversion Appliance Server and HVM Conversion Appliance Server"""

    def __init__(self, place, password):
        self.place = place
        self.password = password
        if self.place:
            self.place.password = self.password
        self.conv_password = self.password
        self.conv_username = "convuser"
        self.conv_port = "8012" # default port

    def increaseConversionVMUptime(self, value):
        pass

    def doFirstbootUnattendedSetup(self):
        pass

    def doLogin(self):
        pass

    def getVpx(self, session):
        pass

    def createJob(self, session, vpx, xen_servicecred, vmware_serverinfo, vm, uuid, this_pif, host_ip):
        pass

    def getVMList(self, session, vpx, xen_servicecred, vmware_serverinfo):
        pass

    def unattendedSetup(self):
        pass

    def doSanityChecks(self):
        pass

    def installSSH(self):
        pass

    def updateXcmNetwork(self, session, vm_uuid, network_ref):
        pass

    def findHostMgmtPif(self, session):
        pass

class ConversionApplianceServer(ConversionApplianceBase):
    """An object to represent a Conversion Appliance Server"""

    def __init__(self, place):
        password = xenrt.TEC().lookup("DEFAULT_PASSWORD")
        super(ConversionApplianceServer, self).__init__(place, password)

    # To increase the Conversion VM uptime (in seconds) after being idle.
    # The conversion VM automatically shuts down after 300 seconds,
    #           if the conversion console is not connected to the VM.
    def increaseConversionVMUptime(self, value):
        xenrt.TEC().logverbose("ConversionVM::VPX Increase Uptime Started")
        xenrt.sleep(5)
        self.place.writeToConsole("cd /opt/citrix/conversion/\\n")
        xenrt.sleep(5)
        xenrt.TEC().logverbose("ConversionVM::VPX Increasing default uptime from 300 seconds to %s seconds" % value)
        #sed -i 's/\(AutoShutdownDelay" value="\)300/\13600/g' convsvc.exe.config
        self.place.writeToConsole("sed -i '\"'\"'s/\\(Delay\" value=\"\\)300/\\1%s/g'\"'\"' convsvc.exe.config\\n" % value)
        xenrt.sleep(5)
        xenrt.TEC().logverbose("ConversionVM::VPX Restarting the Service")
        self.place.writeToConsole("cd /etc/init.d/\\n")
        xenrt.sleep(5)
        self.place.writeToConsole("service convsvcd restart\\n")
        xenrt.sleep(5)
        xenrt.TEC().logverbose("ConversionVM::VPX Increase Uptime Completed")

    def doFirstbootUnattendedSetup(self):

        # Retry decorator with exponential backoff
        def retry(tries, delay=3, backoff=2):
            """Retries a function or method until it returns True.

            delay sets the initial delay in seconds, and backoff sets the factor by which
            the delay should lengthen after each failure. backoff must be greater than 1,
            or else it isn't really a backoff. tries must be at least 0, and delay
            greater than 0."""

            if backoff <= 1:
                raise ValueError("backoff must be greater than 1")

            tries = math.floor(tries)
            if tries < 0:
                raise ValueError("tries must be 0 or greater")

            if delay <= 0:
                raise ValueError("delay must be greater than 0")

            def decoRetry(f):
                def fRetry(*args, **kwargs):
                    mtries, mdelay = tries, delay # make mutable

                    xenrt.TEC().logverbose("ConversionVM::First try")
                    rv = f(*args, **kwargs) # first attempt
                    while mtries > 0:
                        if rv == True: # Done on success
                            xenrt.TEC().logverbose("ConversionVM::Try successful")
                            return True

                        xenrt.TEC().logerror("ConversionVM::Try failed")
                        mtries -= 1            # consume an attempt
                        xenrt.sleep(mdelay) # wait...
                        mdelay *= backoff    # make future wait longer

                        xenrt.TEC().logverbose("ConversionVM::Retry # %s" % mtries)
                        rv = f(*args, **kwargs) # Try again

                    xenrt.TEC().logverbose("ConversionVM::Ran out of tries")
                    return False # Ran out of tries :-(

                return fRetry # true decorator -> decorated function
            return decoRetry    # @retry(arg[, ...]) -> true decorator

        @retry(tries=10)
        def retryWriteToConsole(str):
            try:
                self.place.writeToConsole(str)
                return True
            except Exception, e:
                return False

        # Send some suitable keystrokes to go through the initial setup
        # configuration during the appliance firstboot
        # Accept EULA
        xenrt.TEC().logverbose("ConversionVM::Accept EULA")
        retryWriteToConsole("y\\n")
        xenrt.TEC().logverbose("ConversionVM::EULA accepted")
        # choose root passwd: 'xensource'
        xenrt.TEC().logverbose("ConversionVM::Enter root password")
        retryWriteToConsole("%s\\n" % self.password)
        xenrt.TEC().logverbose("ConversionVM::root password entered")
        # xenrt.sleep(5)
        # retype root passwd: 'xensource'
        xenrt.TEC().logverbose("ConversionVM::Confirm root password")
        retryWriteToConsole("%s\\n" % self.password)
        xenrt.TEC().logverbose("ConversionVM::root password confirmed")
        # xenrt.sleep(5)
        # specify hostname: 'conversionvm<enter>'
        xenrt.TEC().logverbose("ConversionVM::Set hostname")
        retryWriteToConsole("conversionvm\\n")
        xenrt.TEC().logverbose("ConversionVM::Set hostname Completed")
        # xenrt.sleep(5)
        # enter domain suffix: 'xenrt.local<enter'
        xenrt.TEC().logverbose("ConversionVM::Set domain suffix")
        retryWriteToConsole("xenrt.local\\n")
        xenrt.TEC().logverbose("ConversionVM::Set domain suffix Completed")
        # xenrt.sleep(5)
        # would you like to use dhcp: 'y<enter>'
        xenrt.TEC().logverbose("ConversionVM::Enable DHCP")
        retryWriteToConsole("y\\n")
        xenrt.TEC().logverbose("ConversionVM::Enable DHCP Completed")
        # xenrt.sleep(5)
        # are these settings correct: 'y<enter>'
        xenrt.TEC().logverbose("ConversionVM::Confirm settings")
        retryWriteToConsole("y\\n")
        xenrt.TEC().logverbose("ConversionVM::Confirm Settings Completed")
        # xenrt.sleep(5)
        # wait for swap to be created, 600 is too long
        # xenrt.sleep(600)
        # press any key to continue
        # self.place.writeToConsole("\\n")
        # Removed this sleep for testing retries
        xenrt.TEC().logverbose("ConversionVM::Sleep for 30 seconds")
        xenrt.sleep(30)
        # login using root
        xenrt.TEC().logverbose("ConversionVM::Enter username")
        retryWriteToConsole("root\\n")
        xenrt.TEC().logverbose("ConversionVM::Enter username Completed")
        # xenrt.sleep(5)
        # password for postgres
        xenrt.TEC().logverbose("ConversionVM::Enter password")
        retryWriteToConsole("%s\\n" % self.password)
        xenrt.TEC().logverbose("ConversionVM::Enter password Completed")
        xenrt.TEC().logverbose("ConversionVM::VPX Login Completed")
        xenrt.TEC().logverbose("ConversionVM::Unattended Setup Completed")

    def doLogin(self):
        self.place.writeToConsole("root\\n")
        xenrt.TEC().logverbose("ConversionVM::Enter username Completed")
        xenrt.sleep(5)
        self.place.writeToConsole("%s\\n" % self.password)
        xenrt.TEC().logverbose("ConversionVM::Enter password Completed")
        xenrt.sleep(5)
        xenrt.TEC().logverbose("ConversionVM::VPX Login Completed")
        self.place.writeToConsole("service sshd start\\n")
        xenrt.sleep(30)

    def getVpx(self, session):
        # call the XenServer host plugin to get the IP address of the conversion VPX,
        # and start it if necessary.
        host_ref = session.xenapi.session.get_this_host(session.handle)
        args = {}
        vpx_ip = session.xenapi.host.call_plugin(host_ref, 'conversion', 'main', args)
        xenrt.TEC().logverbose("ConversionVM::VPX IP = %s" % vpx_ip)
        vpx_url = "https://%s" % vpx_ip
        return XenAPI.xmlrpclib.ServerProxy(vpx_url)

    def createJob(self, session, vpx, xen_servicecred, vmware_serverinfo, vm, uuid, this_pif, host_ip):
        importInfo = {'SRuuid': ""}
        jobInfo = {'JobName': "test name", 'JobDesc': "test description", 'UserField1': ""}
        jobInfo['SourceVmUUID'] = uuid
        jobInfo['SourceVmName'] = vm
        jobInfo['Source'] = vmware_serverinfo
        jobInfo['ImportInfo'] = importInfo
        jobInfo['PreserveMAC'] = True
        xen_serverinfo = {'ServerType': 0}
        xen_serverinfo['Hostname'] = host_ip
        xenrt.TEC().logverbose("ConversionVM::xen_serverinfo['Hostname'] = %s" % xen_serverinfo['Hostname'])
        xen_serverinfo['Username'] = xen_servicecred['Username']
        xenrt.TEC().logverbose("ConversionVM::xen_serverinfo['Username'] = %s" % xen_serverinfo['Username'])
        xen_serverinfo['Password'] = xen_servicecred['Password']
        xenrt.TEC().logverbose("ConversionVM::xen_serverinfo['Password'] = %s" % xen_serverinfo['Password'])
        netList = vpx.svc.get_networks(xen_servicecred, vmware_serverinfo)
        netMap = {}
        xenrt.TEC().logverbose("ConversionVM::netList = %s" % netList)
        for x in netList:
            netMap[x['Name']] = this_pif
            xenrt.TEC().logverbose("ConversionVM::netMap = %s" % netMap)
        jobInfo['NetworkMappings'] = netMap
        xenrt.TEC().logverbose("ConversionVM::jobInfo['NetworkMappings'] = %s" % jobInfo['NetworkMappings'])
        xenrt.TEC().logverbose("ConversionVM::Creating Job")
        JobInstance = vpx.job.create(xen_servicecred, jobInfo)
        xenrt.TEC().logverbose("ConversionVM::Job created")
        xenrt.TEC().logverbose("Id = %s" % JobInstance['Id'])
        return JobInstance

    def getVMList(self, session, vpx, xen_servicecred, vmware_serverinfo):
        VmInstance = vpx.svc.getVMList(xen_servicecred, vmware_serverinfo)
        return VmInstance

    def unattendedSetup(self):
        # Send some suitable keystrokes to go through the initial setup
        # configuration during the appliance firstboot
        # screen 1
        # choose root passwd: 'xensource'
        self.place.writeToConsole("%s\\n" % self.password)
        xenrt.sleep(5)
        # retype root passwd: 'xensource'
        self.place.writeToConsole("%s\\n" % self.password)
        xenrt.sleep(5)
        # screen 2
        # specify hostname: 'conversionvm<enter>'
        self.place.writeToConsole("conversionvm\\n")
        xenrt.sleep(5)
        # enter domain suffix: 'xenrt.local<enter'
        self.place.writeToConsole("xenrt.local\\n")
        xenrt.sleep(5)
        # would you like to use dhcp: 'y<enter>'
        self.place.writeToConsole("y\\n")
        xenrt.sleep(5)
        # screen 3
        # are these settings correct: 'y<enter>'
        self.place.writeToConsole("y\\n")
        xenrt.sleep(5)
        # wait for swap to be created
        xenrt.sleep(300)
        # screen 4
        # press any key to continue
        #self.place.writeToConsole("\\n")
        xenrt.sleep(30)
        # screen 5
        # login using root
        self.place.writeToConsole("root\\n")
        xenrt.sleep(5)
        # password for postgres
        self.place.writeToConsole("%s\\n" % self.password)
        xenrt.sleep(5)

    def doSanityChecks(self):
        # sanity checks after automated setup
        # check if the Conversion VPX is listening on the expected port
        out = self.place.writeToConsole("netstat -a | grep 443 | wc -l\\n",1,cuthdlines=1).strip()
        if out != "1":
            raise xenrt.XRTFailure("Conversion appliance not listening on expected port 443")

    def installSSH(self):
        self.place.writeToConsole("yum -y install openssh-server\\n")
        xenrt.sleep(360)

    def updateXcmNetwork(self, session, vm_uuid, network_ref):
        vm_ref = session.xenapi.VM.get_by_uuid(vm_uuid)
        # Destroy the VIF for device '1'
        vifs = session.xenapi.VM.get_VIFs(vm_ref)
        for vif in vifs:
            device = session.xenapi.VIF.get_device(vif)
            if device == '1':
                print 'Destroying VIF', vif
                session.xenapi.VIF.destroy(vif)
        # Create a new VIF for device '1' using the management network-uuid
        session.xenapi.VIF.create({'device': '1',
                                   'network': network_ref,
                                   'VM': vm_ref,
                                   'MAC': '',
                                   'MTU': '1504',
                                   'other_config': {},
                                   'qos_algorithm_type': '',
                                   'qos_algorithm_params': {}})
        return

    def findHostMgmtPif(self, session):
        """Return the PIF object representing the management interface on a Host"""
        # First find the object representing the Host
        host_ref = session.xenapi.session.get_this_host(session.handle)
        # Second enumerate all the physical interfaces (PIFs) on that Host
        pifs = session.xenapi.host.get_PIFs(host_ref)
        # Find the PIF which has the management flag set: this is the interface we use to perform
        # API/management operations
        mgmt = None
        for pif in pifs:
            if session.xenapi.PIF.get_management(pif):
                mgmt = pif
                break
        if mgmt == None:
            raise xenrt.XRTError("Failed to find a management interface (PIF).")
        return mgmt

class ConversionApplianceServerHVM(ConversionApplianceBase):
    """An object to represent a new Conversion Appliance Server, which is a CentOS 7 HVM guest"""

    def __init__(self, place):
        password = xenrt.TEC().lookup("VPX_DEFAULT_PASSWORD", "citrix") # by default vpx root's password
        super(ConversionApplianceServerHVM, self).__init__(place, password)

    # To increase the Conversion VM uptime (in seconds) after being idle.
    # The conversion VM automatically shuts down after 300 seconds,
    #           if the conversion console is not connected to the VM.
    def increaseConversionVMUptime(self, value):
        xenrt.TEC().logverbose("ConversionVM::VPX Increasing default uptime from 300 seconds to %s seconds" % value)
        #sed -i 's/\(AutoShutdownDelay" value="\)300/\13600/g' convsvc.exe.config
        self.place.execguest("sed -i 's/\\(Delay\" value=\"\\)300/\\1%s/g' /opt/citrix/conversion/convsvc.exe.config" % value)
        xenrt.sleep(5)
        xenrt.TEC().logverbose("ConversionVM::VPX Restarting the Service")
        # the first restart command will fail, not sure why ???
        self.place.execguest("systemctl restart convsvcd.service; systemctl restart convsvcd.service")
        xenrt.sleep(5)
        xenrt.TEC().logverbose("ConversionVM::VPX Increase Uptime Completed")

    def doFirstbootUnattendedSetup(self):
        # xcm_self_configure.sh [hostname] [domainname]
        command = "/etc/init.d/xcm_self_configure.sh %s %s" % ("conversionvm", "xenrt.local")
        self.place.execguest(command)
        xenrt.sleep(60)
        self.place.lifecycleOperation("vm-reboot", force=True)
        self.place.waitReadyAfterStart(managenetwork='Pool-wide network associated with eth0') # XenRT eth name-label

    def doSanityChecks(self):
        # sanity checks after automated setup
        # check if the Conversion VPX is listening on the expected port
        out = self.place.execguest("netstat -a | grep 443 | wc -l",1,cuthdlines=1).strip()
        if out != "1":
            raise xenrt.XRTFailure("Conversion appliance not listening on expected port 443")

class VifOffloadSettings(object):

    # The {4D36E972-E325-11CE-BFC1-08002BE10318} subkey represents the class of network adapter devices that the system supports. This will never change.
    REG_KEY_STEM = 'SYSTEM\\CurrentControlSet\\Control\\Class\\{4D36E972-E325-11CE-BFC1-08002BE10318}\\'
    LSO1_KEY = '*LSOv1IPv4'
    LSO2_KEY = '*LSOv2IPv4'
    LRO_KEY = 'LROIPv4'
    IPCHECKSUM_KEY = '*IPChecksumOffloadIPv4'
    TCPCHECKSUM_KEY = '*TCPChecksumOffloadIPv4'
    UDPCHECKSUM_KEY = '*UDPChecksumOffloadIPv4'

    def __init__(self, guest, device):

        self.guest = guest
        self.device = device
        self.xenVifRegistryId = -1

        if not guest.windows:
            raise xenrt.XRTError("getWindowsVifSettings() only supports Windows guests")
        if not isinstance(device, int) or device < 0 or device > 99:
            raise xenrt.XRTError("device must be an integer: 0 >= device > 99")

        xenrt.TEC().logverbose("Looking for reg key for xenvif: %d" % device)

        i = 0
        regValue = None
        for registryIndex in range(100):
            try:
                regValue = self.guest.winRegLookup('HKLM', self.REG_KEY_STEM + ('%04d' % registryIndex), "ComponentId", healthCheckOnFailure=False, suppressLogging=True)
                if "xen" in regValue and "vif" in regValue:
                    if device == i:
                        xenrt.TEC().logverbose("Found reg key for xenvif: %d" % registryIndex)
                        xenrt.TEC().logverbose("reg value for xenvif: " + regValue)
                        self.xenVifRegistryId = registryIndex
                        break;
                    i = i + 1
            except Exception, e:
                # this isn't a xen\vif -> continue through the loop
                if registryIndex == 99:
                    xenrt.TEC().logverbose("Couldn't find xenvif in registry for device %d to collect settings" % device)
                    raise

    def getRegistryId(self):
        return self.xenVifRegistryId

    def __str__(self):
        """Returns a string representation of the offload settings"""

        return "device: %d, LRO: %d, LSO: %d, IPChecksumOffload: %d, TCPChecksumOffload: %d, UDPChecksumOffload: %d" % (
            self.device,
            self.getLargeReceiveOffload(),
            self.getLargeSendOffload(),
            self.getIPChecksumOffload(),
            self.getTcpChecksumOffload(),
            self.getUdpChecksumOffload())

    def verifyEqualTo(self, settings):
        """Raises an exception if the current Windows VIF settings are different from the specified settings"""

        lso = settings.getLargeSendOffload()
        lro = settings.getLargeReceiveOffload()
        ipc = settings.getIPChecksumOffload()
        tcp = settings.getTcpChecksumOffload()
        udp = settings.getUdpChecksumOffload()

        if lso != -1 and self.getLargeSendOffload() != settings.getLargeSendOffload():
            raise xenrt.XRTFailure("LSO value changed. Was: %d, Now: %d" % (settings.getLargeSendOffload(), self.getLargeSendOffload()))

        if lro != -1 and self.getLargeReceiveOffload() != settings.getLargeReceiveOffload():
            raise xenrt.XRTFailure("LRO value changed. Was: %d, Now: %d" % (settings.getLargeReceiveOffload(), self.getLargeReceiveOffload()))

        if ipc != -1 and self.getIPChecksumOffload() != settings.getIPChecksumOffload():
            raise xenrt.XRTFailure("IP Checksum value changed. Was: %d, Now: %d" % (settings.getIPChecksumOffload(), self.getIPChecksumOffload()))

        if tcp != -1 and self.getTcpChecksumOffload() != settings.getTcpChecksumOffload():
            raise xenrt.XRTFailure("TCP Checksum value changed. Was: %d, Now: %d" % (settings.getTcpChecksumOffload(), self.getTcpChecksumOffload()))

        if udp != -1 and self.getUdpChecksumOffload() != settings.getUdpChecksumOffload():
            raise xenrt.XRTFailure("UDP Checksum value changed. Was: %d, Now: %d" % (settings.getUdpChecksumOffload(), self.getUdpChecksumOffload()))

    def _setValue(self, key, value):

        # First try and get the value to check the key exists. We do not want to go adding keys (just setting them).
        try:
            self._getValue(key)
        except:
            raise xenrt.XRTFailure("Tried to set value for " + key + ". This key does not exist")

        self.guest.winRegAdd("HKLM", self.REG_KEY_STEM + ('%04d' % self.xenVifRegistryId), key, "SZ", str(value))

    def _getValue(self, key):
        return int(self.guest.winRegLookup('HKLM', self.REG_KEY_STEM + ('%04d' % self.xenVifRegistryId), key, healthCheckOnFailure=False))

    def _verifyEnabledDisabledParameterValue(self, value):
        if not isinstance(value, int) or value < 0 or value > 1:
            raise xenrt.XRTError("value must be 0 or 1 (0=disabled, 1=enabled)")

    def _verifyRxTxParameterValue(self, value):
        if not isinstance(value, int) or value < 0 or value > 3:
            raise xenrt.XRTError("value must be 0, 1, 2 or 3 (0=disabled, 1=Tx Enabled, 2=Rx Enabled, 3=Tx and Rx Enabled)")

    def setLargeSendOffload(self, value):
        """Sets the Large Send Offload (LSO) value (0=disabled, 1=enabled)"""

        self._verifyEnabledDisabledParameterValue(value)

        # There are two versions of LSO which vary across Windows Versions. Set the one which exists.
        try:
            self._setValue(self.LSO1_KEY, value)
        except:
            self._setValue(self.LSO2_KEY, value)

    def getLargeSendOffload(self):
        """Gets the Large Send Offload (LSO) value (0=disabled, 1=enabled)"""

        # There are two versions of LSO which vary across Windows Versions. Get the one which exists.
        try:
            return self._getValue(self.LSO1_KEY)
        except:
            try:
                return self._getValue(self.LSO2_KEY)
            except:
                # This isn't available for all Windows/XenServer versions.
                return -1

    def setLargeReceiveOffload(self, value):
        """Sets the Large Receive Offload (LRO) value (0=disabled, 1=enabled)"""

        self._verifyEnabledDisabledParameterValue(value)
        return self._setValue(self.LRO_KEY, value)

    def getLargeReceiveOffload(self):
        """Gets the Large Receive Offload (LRO) value (-1=notfound, 0=disabled, 1=enabled)"""

        try:
            return self._getValue(self.LRO_KEY)
        except:
            # This isn't available for all Windows/XenServer versions.
            return -1

    def setIPChecksumOffload(self, value):
        """Sets the IP Checksum Offload value (0=disabled, 1=Tx Enabled, 2=Rx Enabled, 3=Tx and Rx Enabled)"""

        self._verifyRxTxParameterValue(value)
        return self._setValue(self.IPCHECKSUM_KEY, value)

    def getIPChecksumOffload(self):
        """Gets the IP Checksum Offload value (0=disabled, 1=Tx Enabled, 2=Rx Enabled, 3=Tx and Rx Enabled)"""

        try:
            return self._getValue(self.IPCHECKSUM_KEY)
        except:
            # This isn't available for all Windows/XenServer versions.
            return -1

    def setTcpChecksumOffload(self, value):
        """Sets the TCP Checksum Offload value (0=disabled, 1=Tx Enabled, 2=Rx Enabled, 3=Tx and Rx Enabled)"""

        self._verifyRxTxParameterValue(value)
        return self._setValue(self.TCPCHECKSUM_KEY, value)

    def getTcpChecksumOffload(self):
        """Gets the TCP Checksum Offload value (0=disabled, 1=Tx Enabled, 2=Rx Enabled, 3=Tx and Rx Enabled)"""

        try:
            return self._getValue(self.TCPCHECKSUM_KEY)
        except:
            # This isn't available for all Windows/XenServer versions.
            return -1

    def setUdpChecksumOffload(self, value):
        """Sets the UDP Checksum Offload value (0=disabled, 1=Tx Enabled, 2=Rx Enabled, 3=Tx and Rx Enabled)"""

        self._verifyRxTxParameterValue(value)
        return self._setValue(self.UDPCHECKSUM_KEY, value)

    def getUdpChecksumOffload(self):
        """Gets the UDP Checksum Offload value (0=disabled, 1=Tx Enabled, 2=Rx Enabled, 3=Tx and Rx Enabled)"""

        try:
            return self._getValue(self.UDPCHECKSUM_KEY)
        except:
            # This isn't available for all Windows/XenServer versions.
            return -1

class _WinPEBase(object):
    def __init__(self):
        self._xmlrpc = None
        self._xmlrpcInit = False
        self.ip = None

    @property
    def xmlrpc(self):
        if not self._xmlrpcInit:
            if not self.ip:
                raise xenrt.XRTError("IP not known")
            self._xmlrpc = xmlrpclib.ServerProxy("http://%s:8080" % self.ip)
            self._xmlrpcInit = True
        return self._xmlrpc

    def boot(self):
        raise xenrt.XRTError("Not implemented")

    def waitForBoot(self):
        deadline = xenrt.util.timenow() + 1800
        while True:
            try:
                if self.xmlrpc.file_exists("x:\\execdaemonwinpe.py") and not self.xmlrpc.file_exists("x:\\waiting.stamp"):
                    break
            except Exception, e:
                xenrt.TEC().logverbose("Exception: %s" % str(e))
            if xenrt.util.timenow() > deadline:
                raise xenrt.XRTError("Timed out waiting for WinPE boot")
            xenrt.sleep(15)

    def reboot(self):
        self.xmlrpc.write_file("x:\\waiting.stamp", "")
        self.xmlrpc.start_shell("wpeutil reboot")
        self.waitForBoot()
