
#!/usr/bin/python
# XenRT: Test harness for Xen and the XenServer product family
#
# Am XML-RPC test execution daemon
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import os, traceback
    
if os.getenv("PROCESSOR_ARCHITECTURE") == "AMD64":
    arch = "amd64"
else:
    arch = "x86"

if arch == "x86":
    import win32api, win32security, win32com.client
    import win32process, pythoncom
    from win32con import *
    from ntsecuritycon import *

import sys, string, cgi, urlparse, tempfile, shutil, stat, time, trace
import subprocess, urllib, tarfile, glob, socket, re, zipfile, os.path, glob
import thread, sha, SocketServer, threading

# Hackish way to let SimpleXMLRPCServer of Python 2.4 support allow_none.
# This is not necessary for Python above 2.5 version.
import xmlrpclib
if sys.version_info < (2,5):
    class _xmldumps(object):
        def __init__(self, dumps):
            self.__dumps = (dumps,)
        def __call__(self, *args, **kwargs):
            kwargs.setdefault('allow_none', 1)
            return self.__dumps[0](*args, **kwargs)
    xmlrpclib.dumps = _xmldumps(xmlrpclib.dumps)

from SimpleXMLRPCServer import SimpleXMLRPCRequestHandler, SimpleXMLRPCDispatcher 
from SocketServer import TCPServer

import _winreg
import bz2
import platform

def is_ipv6_supported():
	pf = platform.release()
	if pf in set(['XP', '2003Server']):
		return False
	else:
		return True


class MyTCPServer(TCPServer):
    
    if is_ipv6_supported():		 
        address_family = socket.AF_INET6
    else:
        address_family = socket.AF_INET

    def __init__(self, server_address, RequestHandlerClass, bind_and_activate=True):
        """Constructor.  May be extended, do not override."""
        SocketServer.BaseServer.__init__(self, server_address, RequestHandlerClass)
        self.socket = socket.socket(self.address_family,
                                    self.socket_type)
        if bind_and_activate:
            self.server_bind()
            self.server_activate()

    def server_bind(self):
        
        if self.allow_reuse_address:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        if is_ipv6_supported():    
            try:
                self.socket.setsockopt(41, socket.IPV6_V6ONLY, 0)
            except Exception, e:
                loglocal("Caught Exception: %s" % (str(e)))
                loglocal(traceback.format_exc())
                
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()

    def server_activate(self):
        self.socket.listen(self.request_queue_size)

        
class SimpleXMLRPCServer(MyTCPServer,
                         SimpleXMLRPCDispatcher):
    """Simple XML-RPC server.

    Simple XML-RPC server that allows functions and a single instance
    to be installed to handle requests. The default implementation
    attempts to dispatch XML-RPC calls to the functions or instance
    installed in the server. Override the _dispatch method inhereted
    from SimpleXMLRPCDispatcher to change this behavior.
    """

    allow_reuse_address = True

    # Warning: this is for debugging purposes only! Never set this to True in
    # production code, as will be sending out sensitive information (exception
    # and stack trace details) when exceptions are raised inside
    # SimpleXMLRPCRequestHandler.do_POST
    _send_traceback_header = False

    def __init__(self, addr, requestHandler=SimpleXMLRPCRequestHandler,
                 logRequests=True, allow_none=False, encoding=None, bind_and_activate=True):
        self.logRequests = logRequests
        
        SimpleXMLRPCDispatcher.__init__(self, allow_none, encoding)
        MyTCPServer.__init__(self, addr, requestHandler, bind_and_activate)


# Workaround for http://bugs.python.org/issue1731717
# All it means is we need to be careful with polling. 
subprocess._cleanup = lambda : None

death = False
requests = 0

import httplib, socket

class MyHTTPConnection(httplib.HTTPConnection):

    def connect(self):
        """Connect to the host and port specified in __init__."""
        msg = "getaddrinfo returns an empty list"
        for res in socket.getaddrinfo(self.host, self.port, 0,
                                      socket.SOCK_STREAM):
            af, socktype, proto, canonname, sa = res
            try:
                self.sock = socket.socket(af, socktype, proto)
                self.sock.settimeout(7)
                if self.debuglevel > 0:
                    print "connect: (%s, %s)" % (self.host, self.port)
                self.sock.connect(sa)
            except socket.error, msg:
                if self.debuglevel > 0:
                    print 'connect fail:', (self.host, self.port)
                if self.sock:
                    self.sock.close()
                self.sock = None
                continue
            break
        if not self.sock:
            raise socket.error, msg

class MyHTTP(httplib.HTTP):

    _connection_class = MyHTTPConnection

class MyTrans(xmlrpclib.Transport):

    def make_connection(self, host):
        # create a HTTP connection object from a host descriptor
        host, extra_headers, x509 = self.get_host_info(host)
        return MyHTTP(host)

class MySimpleXMLRPCRequestHandler(SimpleXMLRPCRequestHandler):

    def address_string(self):

        host, port = self.client_address[:2]
        return host

class MySimpleXMLRPCServer(SocketServer.ThreadingMixIn, SimpleXMLRPCServer):

    def __init__(self, addr, requestHandler=MySimpleXMLRPCRequestHandler,
                 logRequests=1):
        if sys.version_info < (2,5):
            SimpleXMLRPCServer.__init__(self, addr, requestHandler,
                                        logRequests)
        else:
            SimpleXMLRPCServer.__init__(self, addr, requestHandler,
                                        logRequests, allow_none=True)
   
    def _dispatch(self, method, params):
        try:
            return SimpleXMLRPCServer._dispatch(self, method, params)
        except Exception, e:
            loglocal("Caught Exception: %s" % (str(e)))
            loglocal(traceback.format_exc())
            raise e
 
    def serve_forever(self):
        global death, requests
        while 1:
            if death:
                sys.exit(0)
            self.handle_request()
            requests = requests + 1
            
this_host = '0.0.0.0' 
if is_ipv6_supported():
    this_host = '::'

# Create server
try:
    server = MySimpleXMLRPCServer((this_host, 8936))
except socket.error, e:
    # This is probably because we're trying to run this on a rdesktop
    # display and there is another daemon running on the glass, just
    # wait a while then exit. This is to stop a tight loop with the
    # wrapper batch file.
    print "Error '%s' starting RPC server, waiting 5 minutes" % (str(e))
    print "If this is a RDP session then this error is benign."
    time.sleep(300)
    sys.exit(0)
    
server.register_introspection_functions()
print "Starting XML-RPC server on port 8936..."

PASSWORD = "xensource"
daemonlog = "c:\\execdaemon.log"

def loglocal(data):
    f = file(daemonlog, "a")
    f.write("%s %s\n" % (time.strftime("%d/%b/%Y %H:%M:%S", time.localtime()), data))
    f.close()

loglocal("Server started")

def delayed(fn, args, delay):
    time.sleep(delay)
    if args == None:
        fn()
    else:
        fn(args)

def doLater(fn, args, delay):
    """Run fn(args) in delay seconds"""
    thread.start_new_thread(delayed, (fn, args, delay))

############################################################################
# Remote command execution                                                 #
############################################################################

commands = {}
index = 0
indexlock = threading.Lock()

class Command:
    """A command the remote host has asked us to run"""
    def __init__(self, command):
        global commands, index, indexlock
        self.command = command
        f, filename = tempfile.mkstemp()
        os.close(f)
        os.chmod(filename,
                 stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)
        self.logfile = filename

        indexlock.acquire()
        self.reference = "%08x" % (index)
        index = index + 1
        indexlock.release()

        commands[self.reference] = self
        self.returncode = 0
        self.finished = False
        self.process = None
        self.loghandle = None

    def run(self):
        self.loghandle = file(self.logfile, "w")
        print "Starting %s... " % (self.command)
        loglocal("Starting %s... " % (self.command))
        self.process = subprocess.Popen(string.split(self.command),
                                        stdin=None,
                                        stdout=self.loghandle,
                                        stderr=subprocess.STDOUT,
                                        shell=True)
        print "... started"

    def poll(self):
        if self.finished:
            return "DONE"
        if not self.process:
            raise "Command object %s has no process member" % (self.reference)
        r = self.process.poll()
        if r == None:
            return "RUNNING"
        self.finished = True
        self.returncode = r
        self.loghandle.close()
        return "DONE"

    def getPID(self):
        return self.process.pid

def getCommand(reference):
    global commands
    if commands.has_key(reference):
        return commands[reference]
    return None

def delCommand(reference):
    global commands
    if commands.has_key(reference):
        del commands[reference]

def runbatch(commands):
    try: commands = commands.decode("uu").decode("utf-16").encode("utf-8")    
    except ValueError, v: pass
    cmd = tempFile(".cmd")
    f = file(cmd, "w")
    f.write(commands)
    f.close()
    loglocal("Built command file %s containing >>>%s<<<" % (cmd, commands))
    c = Command(cmd)
    c.run()
    return c.reference

def run(command, makebatch=False):
    c = Command(command)
    c.run()
    return c.reference

def runsync(command):
    return subprocess.check_output(command, stderr=subprocess.STDOUT, shell=True)

def runpshell(commands):
    commands = commands.decode("uu").decode("utf-16")
    pfile = tempFile(".ps1")
    file(pfile, "wb").write(commands.encode("utf-16"))
    return runbatch("c:\\windows\\system32\\WindowsPowerShell\\v1.0\\" \
                    "powershell.exe %s" % (pfile))

def poll(reference):
    global commands
    print "Poll '%s', %s" % (reference, `commands`)
    c = getCommand(reference)
    if not c:
        raise "Could not find command object %s" % (reference)
    return c.poll()

def getPID(reference):
    global commands
    print "getPID '%s', %s" % (reference, `commands`)
    c = getCommand(reference)
    if not c:
        raise "Could not find command object %s" % (reference)
    return c.getPID()

def returncode(reference):
    c = getCommand(reference)
    return c.returncode

def log(reference):
    c = getCommand(reference)
    f = file(c.logfile, "r+t")
    r = f.read()
    f.close()
    return r

def cleanup(reference):
    c = getCommand(reference)
    if c.finished:
        if c.logfile:
            os.unlink(c.logfile)
            c.logfile = None
    delCommand(c.reference)
    return True

server.register_function(runbatch)
server.register_function(runpshell)
server.register_function(run)
server.register_function(runsync)
server.register_function(poll)
server.register_function(getPID)
server.register_function(returncode)
server.register_function(log)
server.register_function(cleanup)

############################################################################
# Process library functions                                                #
############################################################################

def ps():
    if arch == "amd64":
        f = os.popen("tasklist /fo csv")
        data = f.read().strip()
        pids = [ re.sub("\"", "", k) for k in 
                [ j[0] for j in 
                    [ i.split(",") for i in 
                        data.split("\n") ] ] ]
    else:
        pythoncom.CoInitialize()
        WMI = win32com.client.GetObject("winmgmts:")
        ps = WMI.InstancesOf("Win32_Process")
        pids = []
        for p in ps:
            pids.append(p.Properties_('Name').Value)
        pythoncom.CoUninitialize()
    return pids

def kill(pid):
    if arch == "amd64":
        os.system("taskkill /pid %s /t /f" % (pid))
    else:
        handle = win32api.OpenProcess(1, False, pid)
        win32api.TerminateProcess(handle, -1)
        win32api.CloseHandle(handle)
    return True

def killall(pname):
    pids = []
    if arch == "amd64":
        f = os.popen("tasklist /fo csv")
        data = f.read().strip()
        tasks =  [ j[0:2] for j in 
                    [ i.split(",") for i in 
                        data.split("\n") ] ]
        for t in tasks:
            if re.sub("\"", "", t[0]).lower() == pname.lower():
                pids.append(re.sub("\"", "", t[1]))
    else:
        pythoncom.CoInitialize()
        WMI = win32com.client.GetObject("winmgmts:")   
        ps = WMI.InstancesOf("Win32_Process")
        for p in ps:
            if p.Properties_('Name').Value.lower() == pname.lower():
                pids.append(p.Properties_('ProcessID').Value)     
    for pid in pids:
        kill(pid)
    if arch == "x86":
        pythoncom.CoUninitialize()
    return True

def appActivate(app):
    pythoncom.CoInitialize()
    shell = win32com.client.Dispatch("WScript.Shell")
    pythoncom.CoUninitialize()
    return shell.AppActivate(app)

def sendKeys(keys):
    pythoncom.CoInitialize()
    shell = win32com.client.Dispatch("WScript.Shell")
    keysSplit = keys.split(",")
    for key in keysSplit:
        if len(key) == 1 or key.startswith("{") or key.startswith("%") or \
           key.startswith("^") or key.startswith("+"):
            shell.SendKeys(key)
        elif key.startswith("s"):
            time.sleep(int(key[1:]))
    pythoncom.CoUninitialize()
    return True

server.register_function(ps)
server.register_function(kill)
server.register_function(killall)
server.register_function(appActivate)
server.register_function(sendKeys)

############################################################################
# File and directory library functions                                     #
############################################################################

def tempFile(suffix=""):
    f, filename = tempfile.mkstemp(suffix)
    os.close(f)
    os.chmod(filename,
             stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)
    return filename

def tempDir(suffix="", prefix="", path=None):
    dir = tempfile.mkdtemp(suffix, prefix, path)
    os.chmod(dir, stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)
    loglocal("Created %s" % (dir))
    return dir

def globpath(p):
    return glob.glob(p)

def deltree(p):
    shutil.rmtree(p, ignore_errors=True)
    return True

def createEmptyFile(filename, size):
    """Create a file full of zeros of the size (MBytes) specified."""
    zeros = "\0" * 65536
    f = file(filename, "wb")
    for i in range(size * 16):
        f.write(zeros)
    f.close()
    return True

def removeFile(filename):
    os.unlink(filename)
    return True

def createDir(dirname):
    os.makedirs(dirname)
    return True

def createFile(filename, data):
    f = file(filename, "wb")
    if type(data) == type(""):
        f.write(data)
    else:
        f.write(data.data)
    f.close()
    return True

def readFile(filename):
    data = xmlrpclib.Binary()
    f = file(filename, "rb")
    data.data = f.read()
    f.close()
    return data

def readFileBZ2(filename):
    c = bz2.BZ2Compressor()
    f = file(filename, "rb")
    count = 0
    data = xmlrpclib.Binary()
    data.data = ""
    while True:
        d = f.read(4096)
        if len(d) == 0:
            break
        count = count + len(d)
        data.data = data.data + c.compress(d)
    f.close()
    data.data = data.data + c.flush()
    loglocal("Read %s (%u bytes) to bz2 compressed stream (%u bytes)" %
             (filename, count, len(data.data)))
    return data

def globPattern(pattern):
    return glob.glob(pattern)

def fileExists(filename):
    return os.path.exists(filename)

def dirExists(filename):
    return os.path.exists(filename) and os.path.isdir(filename)

def dirRights(dirname):
    for x in os.walk(dirname):
        dirpath, dirnames, filenames = x
        for fn in filenames:
            filename = "%s\\%s" % (dirpath, fn)
            os.chmod(filename,
                     stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)
    return True

def fileMTime(filename):
    return os.stat(filename).st_mtime

server.register_function(tempFile)
server.register_function(createDir)
server.register_function(tempDir)
server.register_function(globpath)
server.register_function(deltree)
server.register_function(createEmptyFile)
server.register_function(removeFile)
server.register_function(createFile)
server.register_function(readFile)
server.register_function(readFileBZ2)
server.register_function(globPattern)
server.register_function(fileExists)
server.register_function(dirExists)
server.register_function(dirRights)
server.register_function(fileMTime)

############################################################################
# Power control                                                            #
############################################################################

# Borrowed: http://mail.python.org/pipermail/python-list/2002-August/161778.html
def AdjustPrivilege(priv, enable = 1):
    # Get the process token.
    flags = TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY
    htoken = win32security.OpenProcessToken(win32api.GetCurrentProcess(), flags)
    # Get the ID for the system shutdown privilege.
    id = win32security.LookupPrivilegeValue(None, priv)
    # Now obtain the privilege for this process.
    # Create a list of the privileges to be added.
    if enable:
        newPrivileges = [(id, SE_PRIVILEGE_ENABLED)]
    else:
        newPrivileges = [(id, 0)]
    # and make the adjustment.
    win32security.AdjustTokenPrivileges(htoken, 0, newPrivileges)
# /Borrowed

def shutdown2000():
    reply = False
    AdjustPrivilege(SE_SHUTDOWN_NAME)
    try:
        win32api.ExitWindowsEx(EWX_POWEROFF)
        reply = True
    finally:
        AdjustPrivilege(SE_SHUTDOWN_NAME, 0)
    return reply

def shutdown():
    if windowsVersion() == "5.0":
        doLater(shutdown2000, None, 15)
        return True
    reply = False
    if arch == "x86":
        AdjustPrivilege(SE_SHUTDOWN_NAME)
        try:
            win32api.InitiateSystemShutdown(None,
                                            "Shutting down",
                                            15,
                                            True,
                                            False)
            reply = True
        finally:
            AdjustPrivilege(SE_SHUTDOWN_NAME, 0)
        return reply
    else:
        os.system("shutdown -s -f -t 15")
        return True

def shutdown2000Geneva():
    reply = False
    AdjustPrivilege(SE_SHUTDOWN_NAME)
    try:
        win32api.InitiateSystemShutdown(None,
                                        "Shutting down",
                                        10,
                                        True,
                                        False)
        reply = True
    finally:
        AdjustPrivilege(SE_SHUTDOWN_NAME, 0)
    return reply

def reboot():
    reply = False
    if arch == "x86":
        AdjustPrivilege(SE_SHUTDOWN_NAME)
        try:
            win32api.InitiateSystemShutdown(None, "Rebooting", 10, True, True)
            reply = True
        finally:
            AdjustPrivilege(SE_SHUTDOWN_NAME, 0)
        return reply
    else:
        os.system("shutdown -r -f -t 10")
        return True

server.register_function(shutdown)
server.register_function(shutdown2000Geneva)
server.register_function(reboot)

############################################################################
# Miscellaneous library functions                                          #
############################################################################

def unpackTarball(url, directory):
    f = tempFile()
    loglocal("Created file: %s" % (f))
    urllib.urlretrieve(url, f)
    loglocal("Fetched tarfile: %s" % (url)) 
    tf = tarfile.open(f, "r")
    for m in tf.getmembers():
        tf.extract(m, directory)
        loglocal("Extracting %s to %s" % (m, directory))
    tf.close()
    try:
        os.unlink(f)
    except Exception, e:
        loglocal("Failed to delete temporary file: %s (%s)" % (f, str(e)))
        loglocal(traceback.format_exc())
    return True

def pushTarball(data, directory):
    f = tempFile()
    createFile(f, data)
    tf = tarfile.open(f, "r")
    for m in tf.getmembers():
        tf.extract(m, directory)
    tf.close()
    os.unlink(f)
    return True

def extractTarball(filename, directory):
    tf = tarfile.open(filename, "r")
    for m in tf.getmembers():
        m.name = string.replace(m.name, ":", "_")
        tf.extract(m, directory)
    tf.close()
    return True

def createTarball(filename, directory):
    tf = tarfile.open(filename, "w")
    tf.add(directory)
    tf.close()
    return True

def addBootFlag(flag):
    os.system("attrib -R -S -H c:\\boot.ini")
    data = ""
    insection = False
    f = file("c:\\boot.ini", "rt")
    for line in f.readlines():
        line = string.strip(line)
        if insection:
            if not string.find(line, flag) > -1:
                line = line + " " + flag
        elif re.search(r"^\[operating systems\]", line):
            insection = True
        elif re.search(r"^\[", line):
            insection = False
        data = data + line + "\n"
    f.close()
    f = file("c:\\boot.ini", "wt")
    f.write(data)
    f.close()
    os.system("attrib +R +S +H c:\\boot.ini")
    return True

def WMIQueryReturnAll(object, *values):
    """ Some WMI Queries have multiple instances """
    if windowsVersion() == "5.0":
        data = r"""
Set WMI = GetObject("winmgmts:{impersonationlevel=impersonate}!\\.\root\cimv2")
Set DATA = WMI.ExecQuery("Select * from %s")

WScript.Echo "%s"

For Each D in DATA
    WScript.Echo %s
Next
""" % (object,
       string.join(values),
       string.join([ "D." + x for x in values ], " & \" \" & "))
        tmp = tempFile(suffix=".vbs")
        createFile(tmp, data)
        t = os.popen("cscript /nologo %s" % (tmp)).read().strip()
        removeFile(tmp)
    else:
        t = os.popen("wmic path %s get %s" % 
                    ( object, string.join(values, ","))).read().strip()
        t = re.sub("Please wait while WMIC is being installed.", "", t)
    t = [ x.split() for x in t.split("\n") ]
    return dict(map(lambda x: (x[0], list(x[1:])), zip(*t)))

def WMIQuery(object, *values):
    r = WMIQueryReturnAll(object, *values)
    return dict([(k,v[0]) for k,v in r.iteritems()])

def singleWMIQuery(object, value):
    return WMIQuery(object, *[value])[value]

def getMemory(complete=False, unit=1048576):
    path = "Win32_PhysicalMemoryArray"
    key = "MaxCapacity"
    pathext = "Win32_OperatingSystem"
    keysext = ["TotalVisibleMemorySize",
               "TotalVirtualMemorySize",
               "FreePhysicalMemory",
               "FreeVirtualMemory"
               ]
    result = int(singleWMIQuery(path, key)) * 1024 /unit
    if complete:
        resultext = WMIQuery(pathext, *keysext)
        resultext = dict(map(lambda(x, y):(x, int(y) * 1024 / unit), resultext.iteritems()))
        resultext["TotalPhysicalMemorySize"] = result
        return resultext
    else:
        return result

def getVIFs():
    data = os.popen("ipconfig /all").read()
    vifs = [ l[1] for l in \
             re.findall(r"(Ethernet.*\n.*Physical Address[\. :]+)([0-9A-Z-]+)", data) ] 
    if not vifs:
        loglocal(data)
        raise Exception("Unable to parse ipconfig output.")
    return [ re.sub("-", ":", mac) for mac in vifs ]

def getCPUs():
    try:
        return int(singleWMIQuery("Win32_ComputerSystem",
                                  "NumberOfLogicalProcessors"))
    except:
        return int(singleWMIQuery("Win32_ComputerSystem",
                                  "NumberOfProcessors"))

def getSockets():
    return int(singleWMIQuery("Win32_ComputerSystem", "NumberOfProcessors"))

def getCPUCores():
    return map(int, WMIQueryReturnAll("Win32_Processor", *["NumberOfCores"])["NumberOfCores"])

def getCPUVCPUs():
    return map(int, WMIQueryReturnAll("Win32_Processor",
                                      *["NumberOfLogicalProcessors"])["NumberOfLogicalProcessors"])
    
def fetchFile(url, localfile):
    urllib.urlretrieve(url, localfile)
    return True

def getVersion():
    if arch == "x86":
        return win32api.GetVersion()
    # Try parsing systeminfo
    data = os.popen("C:\\Windows\\System32\\systeminfo.exe").read()
    r = re.search(r"OS Version:\s+(\d+)\.(\d)", data)
    if r:
        return int(r.group(1)) | (int(r.group(2)) << 8)
    # XXX In the x64 case we need to find another way to get the version
    return 5 | (2 << 8)

def getArch():
    return arch

def windowsVersion():
    v = getVersion()
    major = v & 0xff
    minor = (v >> 8) & 0xff
    return "%s.%s" % (major, minor)

def sleep(duration):
    time.sleep(duration)
    return True

def checkOtherDaemon(address):     
    s = xmlrpclib.Server('http://%s:8936' % (address), MyTrans())
    try:
        return s.isAlive()
    except:
        pass
    return False

def getEnvVar(varname):
    return os.getenv(varname)

def getTime():
    return time.time()

def sha1Sum(filename):
    if os.path.exists("c:\\sha1sum.exe"):
        data = os.popen("c:\\sha1sum.exe \"%s\"" % (filename)).read()
        return string.split(data)[0]
    f = file(filename, "rb")
    data = f.read()
    f.close()
    s = sha.new(data)
    x = s.hexdigest()
    return x

def sha1Sums(path, filelist):
    reply = {}
    for file in filelist:
        reply[file] = sha1Sum("%s\\%s" % (path, file))
    return reply

def listDisks():
    disks = os.popen("echo list disk | diskpart").read() 
    disks = re.findall("Disk [0-9]+", disks)
    disks = [ disk.strip("Disk ") for disk in disks ]
    time.sleep(5)
    return disks

def getRootDisk():
    f = file("c:\\getrootdisk.txt", "w")
    f.write("""
select volume C
detail volume    
""") 
    f.close()
    data = os.popen("diskpart /s c:\\getrootdisk.txt").read()
    os.unlink("c:\\getrootdisk.txt")
    r = re.search("Disk (?P<disk>[0-9]+)", data)
    if not r:
        raise Exception(data)
    time.sleep(5)
    return r.group("disk")

def assign(disk):
    loglocal("Assigning a letter to disk %s..." % (disk))
    f = file("c:\\assign.txt", "w")
    f.write("""
select volume %s
assign
list volume
""" % (disk))
    f.close()
    data = os.popen("diskpart /s c:\\assign.txt").read()
    os.unlink("c:\\assign.txt")
    return re.search("Volume\s+%s\s+(\w{1})\s+" % (disk), data).group(1)

def partition(disk):
    loglocal("Partitioning disk %s..." % (disk))
    letter = None
    for c in range(ord('C'), ord('Z')+1):
        loglocal("Checking drive letter %s." % (chr(c)))
        data = os.popen("echo select volume %s | diskpart" % 
                        (chr(c))).read()
        loglocal("Diskpart response: %s" % (data))
        if re.search("The volume you selected is not valid or does not exist.", data) or re.search("There is no volume selected", data):
            letter = chr(c)
            break
        elif re.search("Volume [0-9]+ is the selected volume.", data):
            time.sleep(5)
            continue
        else:
            raise Exception(data)
    loglocal("Using drive letter %s." % (letter))
    f = file("c:\\partition.txt", "w")
    # Don't run 'clean' on W2K. It hangs.
    if windowsVersion() == "5.0":
        f.write("""
rescan
list disk
select disk %s
create partition primary
assign letter=%s
detail partition 
        """ % (disk, letter))
    elif float(windowsVersion()) >= 6.0:
        p = os.popen("echo list disk | diskpart")
        data = p.read()
        if p.close():
            raise Exception(data)
        r = re.search("(Disk %s\s+)(?P<status>\w+)" % (disk), data)
        if r.group("status") == "Online":
            status = ""
        else:
            status = "online disk"
        f.write("""
rescan
list disk
select disk %s
attributes disk clear readonly
%s
clean
create partition primary
assign letter=%s
detail partition 
        """ % (disk, status, letter))
    else: 
        f.write("""
rescan
list disk
select disk %s
clean
create partition primary
assign letter=%s
detail partition 
        """ % (disk, letter))
    
    f.close()
    time.sleep(10)
    f = file("c:\\partition.txt", "r")
    script = f.read()
    f.close()
    loglocal("Partitioning disk using script \"%s\"..." % (script))
    p = os.popen("diskpart /s c:\\partition.txt")
    data = p.read()
    if p.close():
        raise Exception(data)
    loglocal("Diskpart response: %s" % (data))
    os.unlink("c:\\partition.txt")
    time.sleep(10)
    return letter

def diskInfo():
    data = os.popen("echo list disk | diskpart").read()
    time.sleep(5)
    data += os.popen("echo list volume | diskpart").read()
    time.sleep(5)
    return data

def doSysprep():
    cmd = "c:\\Windows\\system32\\sysprep\\sysprep.exe /generalize /audit /quiet /quit"
    loglocal("Executing '%s'" % cmd)
    data = os.popen(cmd).read()
    loglocal("Executed sysprep successfully")
    time.sleep(5)
    return data

def deletePartition(letter):
    loglocal("Deleting partition %s..." % (letter))
    f = file("c:\\deletepartition.txt", "w")
    f.write("""
select volume %s
delete volume    
""" % (letter)) 
    f.close()
    data = os.popen("diskpart /s c:\\deletepartition.txt").read()
    loglocal("Diskpart response: %s" % (data))
    os.unlink("c:\\deletepartition.txt")
    time.sleep(5)
    return True

def enableDHCP6():
    data = os.popen("netsh interface ipv6 show interface").read()
    loglocal('network setting on the guest before enabling DHCP: \n%s' % data)
    
    network_adapters = {}
    for line in data.splitlines():
        line = line.strip()
        m = re.search('Local Area Connection\s+(\d+)', line)
        if not m:
            continue
        network_adapters[m.group(0)] = (line.split()[0], m.group(1))

    for (adapter, nic_info) in network_adapters.items():
            os.system('netsh int ipv6 int %s ManagedAddress=Enable' %
                      nic_info[0])
            os.system('ipconfig /renew6 "%s"' % adapter)
            
    return

server.register_function(doSysprep)
server.register_function(diskInfo)
server.register_function(assign)
server.register_function(deletePartition)
server.register_function(getRootDisk)
server.register_function(partition)
server.register_function(listDisks)
server.register_function(unpackTarball)
server.register_function(pushTarball)
server.register_function(extractTarball)
server.register_function(createTarball)
server.register_function(addBootFlag)
server.register_function(getMemory)
server.register_function(getCPUs)
server.register_function(getSockets)
server.register_function(getCPUCores)
server.register_function(getCPUVCPUs)
server.register_function(getVIFs)
server.register_function(fetchFile)
server.register_function(getVersion)
server.register_function(getArch)
server.register_function(windowsVersion)
server.register_function(sleep)
server.register_function(checkOtherDaemon)
server.register_function(getEnvVar)
server.register_function(getTime)
server.register_function(sha1Sum)
server.register_function(sha1Sums)
server.register_function(singleWMIQuery)
server.register_function(enableDHCP6)

############################################################################
# Registry functions                                                       #
############################################################################

def lookupHive(hive):
    if hive == "HKLM":
        key = _winreg.HKEY_LOCAL_MACHINE
    elif hive == "HKCU":
        key = _winreg.HKEY_CURRENT_USER
    else:
        raise "Unknown hive %s" % (hive)
    return key

def lookupType(vtype):
    if vtype == "DWORD":
        vtypee = _winreg.REG_DWORD
    elif vtype == "SZ":
        vtypee = _winreg.REG_SZ
    elif vtype == "EXPAND_SZ":
        vtypee = _winreg.REG_EXPAND_SZ
    elif vtype == "MULTI_SZ":
        vtypee = _winreg.REG_MULTI_SZ
    else:
        raise "Unknown type %s" % (vtype)
    return vtypee

def regLookup(hive, subkey, name):
    key = lookupHive(hive)
    k = _winreg.OpenKey(key, subkey)
    value, type = _winreg.QueryValueEx(k, name)
    return value

def regSet(hive, subkey, name, vtype, value):
    key = lookupHive(hive)
    vtypee = lookupType(vtype)
    k = _winreg.CreateKey(key, subkey)
    _winreg.SetValueEx(k, name, 0, vtypee, value)
    k.Close()
    return True

def regDelete(hive, subkey, name):
    key = lookupHive(hive)
    k = _winreg.CreateKey(key, subkey)
    _winreg.DeleteValue(k, name)
    k.Close()
    return True

server.register_function(regSet)
server.register_function(regDelete)
server.register_function(regLookup)

############################################################################
# Active directory                                                         #
############################################################################

def adGetAllSubjects(stype):
    data = os.popen("dsquery %s -limit 1000000" % (stype)).read()
    return re.findall(r'(?m)(^".*")', data.strip())

def adGetGroups(stype, subjects):
    subjects = [ x.decode("uu").decode("utf-16").encode("utf-8") for x in subjects ]
    """Takes a list of subjects and returns a list of lists
    of groups those subjects are in as (dn, grouplist)."""
    reply = []
    for dn in subjects:
        data = os.popen("dsget %s -memberof -expand %s" % (stype, dn)).read()
        groups = re.findall(r'(?m)(^".*")', data.strip())
        reply.append((dn, groups))
    return reply

def adGetMembers(groups):
    groups = [ x.decode("uu").decode("utf-16").encode("utf-8") for x in groups ]
    """Takes a list of groups and returns a list of lists of members of those
    groups as (dn, memberlist)"""
    reply = []
    for dn in groups:
        data = os.popen("dsget group -members -expand %s" % (dn)).read()
        members = re.findall(r'(?m)(^".*")', data.strip())
        reply.append((dn, members))
    return reply
    
server.register_function(adGetAllSubjects)
server.register_function(adGetGroups)
server.register_function(adGetMembers)

############################################################################
# Install AutoIt Service                                                   #
############################################################################

class Stub: pass
stub = Stub()
server.register_instance(stub, True)
def installAutoItX():
    if not hasattr(stub, "autoitx"):
        pythoncom.CoInitialize()
        autoitx = win32com.client.Dispatch("AutoItX3.Control")
        stub.autoitx = autoitx
        pythoncom.CoUninitialize()
server.register_function(installAutoItX)


############################################################################
# Daemon management                                                        #
############################################################################

def isAlive():
    return True

def stopDaemon(data):
    f = file(sys.argv[0], "w")
    f.write(data)
    f.close()
    global death
    death = True
    return death

def version():
    return "Execution daemon v0.9.3.\n"

server.register_function(stopDaemon)
server.register_function(version)
server.register_function(isAlive)

def checkLiveness():
    # This function is run 10 minutes after daemon start to check for
    # the daemon having been used. If no request has been made in those
    # ten minutes then restart the daemon. This is to workaround XRT-3993.
    global requests, death
    print "Checking liveness after 10 minutes: %u requests so far" % (requests)
    if requests == 0:
        loglocal("XRT-3993 restarting the daemon")
        death = True
        s = xmlrpclib.Server('http://localhost:8936')
        s.isAlive()

# Up our priority.
if arch == "x86":
    win32process.SetPriorityClass(win32process.GetCurrentProcess(),
                                  win32process.HIGH_PRIORITY_CLASS)

# Schedule a liveness check for 10 minutes from now
doLater(checkLiveness, None, 600)

# Run the server's main loop
server.serve_forever()
