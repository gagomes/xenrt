#
# XenRT: Test harness for Xen and the XenServer product family
#
# General utility functions.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import time, fnmatch, sys, os.path, time, os, popen2, random, string, socket, threading
import signal, select, traceback, smtplib, math, re, urllib, urllib2, xml.dom.minidom
import calendar, types, fcntl, resource, requests
import xenrt, xenrt.ssh
import IPy
import xml.sax.saxutils
import logging
from collections import namedtuple

# Symbols we want to export from the package.
__all__ = ["timenow",
           "parseXapiTime",
           "makeXapiTime",
           "waitForFile",
           "localOrRemoteCommand",
           "command",
           "randomMAC",
           "randomMACXenSource",
           "randomMACViridian",
           "checkFileExists",
           "checkConfigDefined",
           "parseBasicConfigFileString",
           "getBasicConfigFileString",
           "formPartition",
           "extractDevice",
           "normaliseMAC",
           "getHostAddress",
           "isAddressInSubnet",
           "calculateSubnet",
           "sendmail",
           "prefLenToMask",
           "formSubnet",
           "median",
           "XenRTLogStream",
           "setupLogging",
           "Timer",
           "randomSuffix",
           "randomGuestName",
           "randomApplianceName",
           "isUUID",
           "fixUUID",
           "getHTTP",
           "count",
           "mean",
           "stddev",
           "parseXMLConfigString",
           "parseSectionedConfig",
           "parseLayeredConfig",
           "strlistToDict",
           "convertIpToLong",
           "convertLongToIp",
           "ipsInSameSubnet",
           "maskToPrefLen",
           "sanitiseForBash",
           "compareIPForSort",
           "SimpleSMTPServer",
           "PhysicalProcessorMonitor",
           "RunCommandPeriodically",
           "imageRectMeanColour",
           "PTask",
           "pfarm",
           "pmap",
           "rot13Encode",
           "roundUpMiB",
           "roundDownMiB",
           "getInterfaceIdentifier",
           "recursiveFileSearch",
           "getRandomULAPrefix",
           "sleep",
           "jobOnMachine",
           "canCleanJobResources",
           "staleMachines",
           "xrtAssert",
           "xrtCheck",
           "keepSetup",
           "getADConfig",
           "getDistroAndArch",
           "getMarvinFile",
           "dictToXML",
           "getNetworkParam",
           "getCCPInputs",
           "getCCPCommit",
           "isUrlFetchable",
           "isWindows",
           "isDevLinux",
           "is32BitPV",
           "checkXMLDomSubset",
           "getUpdateDistro",
           "getLinuxRepo",
           "getURLContent"
           ]

def sleep(secs, log=True):
    if log:
        xenrt.TEC().logverbose("Sleeping for %s seconds - called from %s" % (secs, traceback.extract_stack(limit=2)[0]))
    time.sleep(secs)

def parseXMLConfigString(configString):
    config = {}
    try:
        cfg = xml.dom.minidom.parseString(configString)
        for i in cfg.childNodes:
            if i.nodeType == i.ELEMENT_NODE:
                if i.localName == "CONFIG":
                    for n in i.childNodes:
                        if n.localName == "CPU":
                            for a in n.childNodes:
                                if a.nodeType == a.TEXT_NODE:
                                    config["vcpus"] = int(str(a.data))
                                else:
                                    raise Exception("Invalid CPU value.")
                        elif n.localName == "MEMORY":
                            for a in n.childNodes:
                                if a.nodeType == a.TEXT_NODE:
                                    config["memory"] = int(str(a.data))
                                else:
                                    raise Exception("Invalid MEMORY value.")
                        elif n.localName == "DISTRO":
                            for a in n.childNodes:
                                if a.nodeType == a.TEXT_NODE:
                                    config["distro"] = str(a.data)
                                else:
                                    raise Exception("Invalid DISTRO value.")
                        elif n.localName == "VERSION":
                            for a in n.childNodes:
                                if a.nodeType == a.TEXT_NODE:
                                    config["distro"] = str(a.data)
                                else:
                                    raise Exception()
                        elif n.localName == "DISKSIZE":
                            for a in n.childNodes:
                                if a.nodeType == a.TEXT_NODE:
                                    if str(a.data) != "DEFAULT":
                                        config["disksize"] = int(str(a.data))
                                else:
                                    raise Exception("Invalid DISKSIZE value.")
                        elif n.localName == "METHOD":
                            for a in n.childNodes:
                                if a.nodeType == a.TEXT_NODE:
                                    config["method"] = str(a.data)
                                else:
                                    raise Exception("Invalid METHOD value.")
                        elif n.localName == "ARCH":
                            for a in n.childNodes:
                                if a.nodeType == a.TEXT_NODE:
                                    config["arch"] = str(a.data)
                                else:
                                    raise Exception("Invalid ARCH value.")
                        elif n.localName == "VARCH":
                            for a in n.childNodes:
                                if a.nodeType == a.TEXT_NODE:
                                    config["varch"] = str(a.data)
                                else:
                                    raise Exception("Invalid VARCH value.")
                        else:
                            raise Exception("Invalid config key. (%s)" % 
                                            (n.localName))
                else:
                    raise Exception("Invalid top level key.")
            else:
                raise Exception("Invalid top level type.")
    except Exception, e:
        raise xenrt.XRTError("Error parsing config string. (%s)" % (str(e)))
    return config

def parseSectionedConfig(data, secpatt, fieldpatt):
    """ Generic function for getting sectioned configuration as two-layer's
    dictionary using regexp pattern """
    config = dict(re.findall(secpatt, data))
    
    converter = lambda(k,v): (k.strip(), " ".join(v.strip().split()))
    for sec in config:
        entries = re.findall(fieldpatt, config[sec])
        
        secDict = {}
        keyCount = 1;
        for entry in entries:
            (k,v) = converter(entry)
            
            # allows duplicated keys to be stored. Append a number to the key-name if it already exists.
            if secDict.has_key(k):
                keyCount = keyCount + 1
                secDict[k + str(keyCount)] = v
            else:
                secDict[k] = v
            
        config[sec] = secDict
        
    return config

def parseLayeredConfig(data, spec):
    """ Generic function for parsing layered config-like string into python
    data structure using specification argument. spec type is defined as:

    spec :=  | None                         # No further parsing
             | string                       # Single seperator
             | { sep : string               # The first segment's separator and
                 sub : spec                 # Optional:
                                            # The sub spec for that segment
                 next: (val list -> spec)   # Optional:
                                            # Seprator generator for the rest
                                            # segments (based on parsing result
                                            # of preceeding segments).If none,
                                            # the same config as the first
                                            # segment will be used.
                 post: (val list -> result) # Optional:
                                            # what to do with the parsing
                                            # result of all segments
               }
    """
    data = data.strip()
    if not spec: return data
    elif type(spec) == types.StringType:
        return parseLayeredConfig(data, {'sep': spec})
    else:
        sep = spec.get('sep')
        sub = spec.get('sub')
        next = spec.get('next')
        post = spec.get('post')
        if not sep:
            result = data
        elif not next:
            l = filter(None, data.split(sep))
            result = map(lambda seg: parseLayeredConfig(seg, sub), l)
        else:
            l = data.split(sep, 1)
            first = l[0]
            rest = len(l) > 1 and l[1] or ""
            result = []
            result.append(parseLayeredConfig(first, sub))
            rspec = next(result)
            result.append(parseLayeredConfig(rest, rspec))
        if post:
            result = post(result)
        return result    
    
def parseBasicConfigFileString(configString):
    """
    Convert the contents of a config file (passed as configString) into a
    dictionary of key value pairs.
    """
    lines = configString.splitlines()
    # Remove commented out lines
    lines = filter(lambda x:not x.startswith('#'), lines)
    # Find lines with key / value pairs
    lines = filter(lambda x:len(x.split('=')) == 2, lines)

    configDict = {}
    for line in lines:
        (key, value) = line.split('=')
        configDict[key] = value

    return configDict

def getBasicConfigFileString(configDict):
    """
    From a dictionary of key / value pairs [similar to that created by
    parseBasicConfigFileString] create a string that can be written 
    as a config file.
    """
    configString = ''
    for (key, value) in configDict.iteritems():
        configString += '%s=%s\n' % (key, value)
    return configString

# Finding files recurssively
def recursiveFileSearch(rootdir='.', pattern='*'):
    #return [os.path.join(rootdir, filename)
    return [filename
        for rootdir, dirnames, filenames in os.walk(rootdir)
            for filename in filenames
                if fnmatch.fnmatch(filename, pattern)]

def strlistToDict(strlist, sep="=", keyonly=True):
    """
    Convert a list of strings into a dict. 
        
    Arguments:
    - `strlist`: list of string, each in the form like "key = value" or "key only"
    - `sep`: the seperator
    - `keyonly`: whether to keep strings without the sepeartor as key-only
    entries in the form of {key : None}. Note that a string with the seperator
    but empty value string is never considered as key-only but a {key : ""}
    entry.
    """
    d = {}
    for l in strlist:
        l = l.split(sep, 1)
        k = l[0].strip()
        if len(l) == 2:
            d[k] = l[1].strip()
        elif keyonly:
            d[k] = None
    return d

def count(list):
    return len(list)

def mean(list):
    return float(sum(list)) / len(list)

def stddev(list):
    n = float(len(list))
    s = sum(list)
    ssq = sum(map(lambda x:x*x, list))
    return math.sqrt(ssq / n - (s / n) ** 2)

def setupLogging(name, level=logging.DEBUG, forceThisTEC=False):
    logger = logging.getLogger(name)
    for i in logger.handlers:
        logger.removeHandler(i)
    logger.setLevel(level)
    if forceThisTEC:
        threadName = threading.currentThread().getName()
    else:
        threadName = None
    stream = logging.StreamHandler(stream = XenRTLogStream(threadName=threadName))
    stream.setLevel(level)
    logFormat = logging.Formatter("%(name)s: %(levelname)s - %(message)s")
    stream.setFormatter(logFormat)
    logger.addHandler(stream)
    

class XenRTLogStream(object):
    def __init__(self, threadName=None):
        self.threadName = threadName

    def write(self, data):
        xenrt.TEC(threadName=self.threadName).logverbose(data.rstrip())

    def flush(self):
        pass


class Timer(object):

    def __init__(self, float=False):
        self.measurements = []
        self.starttime = None
        self.float = float
        self.timing = False

    def startMeasurement(self):
        if self.timing:
            raise xenrt.XRTError("Timer double start.")
        self.starttime = timenow(float=self.float)
        self.timing = True

    def stopMeasurement(self):
        if not self.timing:
            raise xenrt.XRTError("Timer stop without start.")
        self.measurements.append(timenow(float=self.float) - self.starttime)
        self.timing = False

    def count(self):
        return count(self.measurements)

    def max(self):
        return max(self.measurements)

    def min(self):
        return min(self.measurements)

    def mean(self):
        return mean(self.measurements)

    def stddev(self):
        return stddev(self.measurements)

def timenow(float=False):
    if float:
        return time.time()
    else:
        return int(time.mktime(time.localtime()))

def parseXapiTime(timestamp):
    """Parse a timestamp of the form used by xapi to return seconds since
    the epoch."""
    timestamp = timestamp.replace("Z","UTC")
    return int(calendar.timegm(time.strptime(timestamp, "%Y%m%dT%H:%M:%S%Z")))

def makeXapiTime(timestamp):
    """Parse a number of seconds since the epoch into a xapi timestamp"""
    return time.strftime("%Y%m%dT%H:%M:%SZ", time.gmtime(timestamp))

def waitForFile(file, timeout, level=xenrt.RC_FAIL, desc="Operation"):
    now = timenow()
    deadline = now + timeout
    xenrt.TEC().logverbose("Looking for %s" % (file))
    while True:
        if os.path.exists(file):
            return xenrt.RC_OK
        now = timenow()
        if now > deadline:
            return xenrt.XRT("%s timed out." % (desc), level)
        time.sleep(15)

def logFileDescriptors():
    try:
        xenrt.TEC().logverbose("Open file descriptors:")
        for fd in range(3,resource.getrlimit(resource.RLIMIT_NOFILE)[0]):
            try:
                flags = fcntl.fcntl(fd, fcntl.F_GETFD)
            except IOError:
                continue
            try:
                xenrt.TEC().logverbose(os.readlink('/proc/self/fd/%d' % fd))
            except:
                xenrt.TEC().logverbose("FD %d appears to be open, but couldn't read link" % fd)

    except:
        pass
    

def localOrRemoteCommand(command, retval="string", level=xenrt.RC_FAIL, timeout=3600):
    if command.startswith("ssh://"):
        m = re.match("ssh://(.+?):(.+?)@(.+?):(.+)", command)
        username = m.group(1)
        password = m.group(2)
        host = m.group(3)
        sshcommand = m.group(4)

        return xenrt.ssh.SSH(host,
                             sshcommand,
                             username=username, 
                             password=password,
                             retval=retval,
                             level=level,
                             timeout=timeout)
    else:
        return xenrt.command(command, retval, level, timeout)

def command(command, retval="string", level=xenrt.RC_FAIL, timeout=3600,
            ignoreerrors=False, strip=False, newlineok=False, nolog=False):
    """Execute a command locally

    @param retval: Whether to return the result code or stdout as a string
        "string" (default), "code"
        if "string" is used then a failure results in an exception
    @param level: Exception level to use if appropriate.
    @param timeout: How long to wait for the command to complete
    @param ignoreerrors: If C{True} then ignore the return code
    @param strip: If C{True} then C{string.strip()} the return data
    @param newlineok: If C{True} then allow newlines in the command line
    @param nolog: If C{True} then don't log the command (for sensitive
        command lines containing passwords)
    """
    if string.find(command, "\n") > -1 and not newlineok:
        if nolog:
            xenrt.TEC().warning("Command with newline")
        else:
            xenrt.TEC().warning("Command with newline: '%s'" % (command))
    deadline = timenow() + timeout
    try:
        p = popen2.Popen4(command)
    except OSError, e:
        if e.strerror != "Too many open files":
            raise
        # Probably other threads opening lots of processes. Sleep for a random amount of time to let them finish
        logFileDescriptors()
        xenrt.TEC().logverbose("Too many open files, sleeping then retrying")
        xenrt.sleep(random.randint(10, 30))
        logFileDescriptors()
        p = popen2.Popen4(command)
    if nolog:
        xenrt.TEC().logverbose("Local command: (PID %u)" % (p.pid))
    else:
        xenrt.TEC().logverbose("Local command: %s (PID %u)" % (command, p.pid))
    p.tochild.close()
    reply = ""
    while 1:
        now = timenow()
        if now > deadline:
            # Command timed out, kill it
            try:
                p.fromchild.close()
                os.kill(p.pid, signal.SIGTERM)
            except Exception, e:
                sys.stderr.write(str(e))
                traceback.print_exc(file=sys.stderr)
            args = command.split()
            cmd = os.path.basename(args[0])
            if cmd == 'xe' and len(args) > 1:
                cmd = args[1]
            return xenrt.XRT("%s timed out" % cmd, level)
        remaining = deadline - now
        s, x, y = select.select([p.fromchild], [], [], remaining)
        if len(s) == 0:
            continue
        line = p.fromchild.readline()
        if line:
            xenrt.TEC().log(line)
            if retval == "string":
                reply = reply + line
        rc = p.poll()
        if rc != -1:
            while True:
                line = p.fromchild.readline()
                if not line:
                    break
                xenrt.TEC().log(line)
                if retval == "string":
                    reply = reply + line
            break
    try:
        p.fromchild.close()
    except:
        pass

    if rc > 0:
        if os.WIFEXITED(rc):
            # Get the actual exit code
            rc = os.WEXITSTATUS(rc)

    if retval == "code":
        return rc
    if rc == 0 or ignoreerrors:
        if strip:
            return string.strip(reply)
        else:
            return reply
    if nolog:
        return xenrt.XRT("Command exited with error (%u)" % (rc),
                         level,
                         data=reply)
    else:
        return xenrt.XRT("Command (%s) exited with error (%u)" % (command, rc),
                         level,
                         data=reply)

def randomMAC():
    """Return a random MAC in the locally administered range, avoiding Cloudstack MACs (starting with 02, 06)"""
    # Start at 2, to avoid cloudstack IPs 
    o1 = (random.randint(2, 63) << 2) | 2
    # Avoid tap device MAC range setup by libvirt i.e. 0xFE
    if o1 == 0xFE: return randomMAC()
    o2 = random.randint(0, 255)
    o3 = random.randint(0, 255)
    o4 = random.randint(0, 255)
    o5 = random.randint(0, 255)
    o6 = random.randint(0, 255)
    return "%02x:%02x:%02x:%02x:%02x:%02x" % (o1, o2, o3, o4, o5, o6)

def randomMACXenSource(pref="00:16:3e"):
    """Return a random MAC address in the XenSource range."""
    o4 = random.randint(0, 127)
    o5 = random.randint(0, 255)
    o6 = random.randint(0, 255)
    return "%s:%02x:%02x:%02x" % (pref, o4, o5, o6)

def randomMACViridian(pref="00:15:5D"):
    """Return a random MAC address in the Viridian range."""
    o4 = random.randint(0, 127)
    o5 = random.randint(0, 255)
    o6 = random.randint(0, 255)
    return "%s:%02x:%02x:%02x" % (pref, o4, o5, o6)
    
def checkFileExists(filename, level=xenrt.RC_ERROR):
    """Check for the existence of the specified file.

     @param filename: filename to check
     @param level: how to deal with a nonexistent file:
         1. L{xenrt.RC_ERROR} to raise a harness error
         2. L{xenrt.RC_FAIL} to raise a test failure
         3. L{xenrt.RC_OK} to raise no exception but return non-zero
    """
    if os.path.exists(filename):
        return xenrt.RC_OK
    if level == xenrt.RC_OK:
        return xenrt.RC_ERROR
    if level == xenrt.RC_FAIL:
        raise xenrt.XRTFailure("%s does not exist" % filename)
    raise xenrt.XRTError("%s does not exist" % filename)

def checkConfigDefined(var, level=xenrt.RC_ERROR):
    """Check for the existence of the specified configuration variable.

    @param var: variable name to check
    @param level: how to deal with a nonexistent variable:
        1. L{xenrt.RC_ERROR} to raise a harness error
        2. L{xenrt.RC_FAIL} to raise a test failure
        3. L{xenrt.RC_OK} to raise no exception but return non-zero
    """
    if xenrt.TEC().defined(var):
        return xenrt.RC_OK
    if level == xenrt.RC_OK:
        return xenrt.RC_ERROR
    if level == xenrt.RC_FAIL:
        raise xenrt.XRTFailure("%s is not defined" % var)
    raise xenrt.XRTError("%s is not defined" % var)

def formPartition(device, part):
    """Build a partition node name from a device and partition number"""
    if device[-1] in string.digits:
        return "%sp%u" % (device, int(part))
    return "%s%u" % (device, int(part))

def extractDevice(part, sysblock=False):
    """Remove the device part of the supplied partition node"""
    device = part[:-1]
    if device[-1] == 'p' and device[-2] in string.digits:
        # Probably a cciss/cod0p1 style
        device = device[:-1]
        if sysblock:
            device = device.replace("/", "!")
    return device

def normaliseMAC(mac):
    # TODO - leading zeros
    mac = string.strip(string.lower(mac))
    if not re.match("([a-f0-9]{2}:){5}([a-f0-9]{2})", mac):
        sl = [ string.join(list(mac)[i:i+2], "") for i in range(0, len(mac), 2) ]
        mac = string.join(sl, ":")
    return mac

def getHostAddress(hostname):
    """Returns the IP address of a host"""
    addr = xenrt.TEC().lookup(["HOST_CONFIGS", hostname, "HOST_ADDRESS"], None)
    if addr:
        return socket.gethostbyname(addr)
    if xenrt.TEC().lookup("NO_DNS", False, boolean=True):
        # We must use xenuse to get the address
        xenuse = xenrt.TEC().lookup("XENUSE", default="xenuse")
        return string.strip(command("%s --ip %s" % (xenuse, hostname)))
    else:
        return socket.gethostbyname(hostname)

def isAddressInSubnet(address, subnet, netmask):
    """Returns true if the specified address is in the specified subnet. All
    arguments are dotted quad strings."""
    
    
    a = socket.inet_aton(address)
    s = socket.inet_aton(subnet)
    m = socket.inet_aton(netmask)
    for i in range(4):
        if not ord(a[i]) & ord(m[i]) == ord(s[i]):
            xenrt.TEC().logverbose("Checking if %s is in subnet %s: False" % (address, subnet))
            return False
    
    xenrt.TEC().logverbose("Checking if %s is in subnet %s: True" % (address, subnet))
    return True

def calculateSubnet(address, netmask):
    """Returns the subnet for the specified address. All arguments and return
    are dotted quad strings."""
    a = socket.inet_aton(address)
    m = socket.inet_aton(netmask)
    s = ""
    for i in range(4):
        s = s + chr(ord(a[i]) & ord(m[i]))
    return socket.inet_ntoa(s)

def calculateLANBroadcast(subnet, netmask):
    """ Returns the Broadcast address for the specified netmask and subnet 
    i.e. ~(netmask) | subnet """
    sn = socket.inet_aton(subnet)
    nm = socket.inet_aton(netmask)
    mc = ""
    for i in range(4):
        mc = mc + chr((~ord(nm[i]) & 0x00ff)| ord(sn[i]))
    return socket.inet_ntoa(mc)


class XentopLogger(threading.Thread):

    def __init__(self, host, logfile, period=30):
        self.host = host
        self.logfile = logfile
        self.logging = False
        self.period = period
        self.handle = None
        threading.Thread.__init__(self)

    def run(self):
        self.logging = True
        self.handle = file(self.logfile, "w")
        while self.logging:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S %Z")
            data = self.host.getXentopData()
            data = [ "[%s] %s" % (timestamp, string.join(x.values())) for x in data.values() ]
            data = string.join(data, "\n")
            self.handle.write(data + "\n")
            time.sleep(self.period)
            
    def stopLogging(self):
        self.logging = False
        self.join()
        self.handle.close()

def startXentopLogger(host, logfile):
    period = xenrt.TEC().lookup("OPTION_XENTOP_PERIOD", 30)
    xt = XentopLogger(host, logfile, period=period) 
    xt.start()
    return xt

def sendmail(toaddrs, subject, message, reply=None):
    """Send an email message, toaddrs = is a list of email addresses"""
    smtp_server = xenrt.TEC().lookup("SMTP_SERVER",
                                     "smtp01.ad.xensource.com")
    fromaddr = xenrt.TEC().lookup("SMTP_SENDER", "patchman@xensource.com")
    now = time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())
    msg = ("Date: %s\r\nFrom: %s\r\nTo: %s\r\nSubject: %s\r\n"
           % (now, fromaddr, ", ".join(toaddrs), subject))
    if reply:
        msg = msg + "Reply-To: %s\r\n" % (reply)
    msg = msg + "\r\n" + message

    server = smtplib.SMTP(smtp_server)
    #server.set_debuglevel(1)
    server.sendmail(fromaddr, toaddrs, msg)
    server.quit()

def prefLenToMaskInts(preflen):
    """Convert an IP prefix length to a subnet mask, returns a list of
    octets"""
    reply = []
    for o in range(4):
        if preflen > 0:
            if preflen > 8:
                p = 8
            else:
                p = preflen
            reply.append([0, 128, 192, 224, 240, 248, 252, 254, 255][p])
        else:
            reply.append(0)
        preflen = preflen - 8
    return reply

def prefLenToMask(preflen):
    """Convert an IP prefix length to a subnet mask"""
    mask = prefLenToMaskInts(preflen)
    return string.join(map(lambda x:str(x), mask), ".")

def formSubnet(address, preflen):
    """Return the subnet address for the specified address and prefix length"""
    reply = []
    mask = prefLenToMaskInts(preflen)
    addr = map(lambda x:int(x), string.split(address, "."))
    for i in range(4):
        reply.append(mask[i] & addr[i])
    return string.join(map(lambda x:str(x), reply), ".")

def median(values):
    v = []
    v.extend(values)
    l = len(v)
    if l == 0:
        return 0
    if l & 1:
        return v[l/2]
    return (v[(l/2)-1] + v[l/2])/2
   
def randomSuffix():
    return "%08x" % random.randint(0, 0x7fffffff)

def randomGuestName(distro=None, arch=None):
    if distro:
        if not arch:
            arch = ""
        else:
            arch = arch[-2:]
        return "xenrt%s%s%08x" % (distro, arch, random.randint(0, 0x7fffffff))
    else:
        return "xenrt%08x%08x" % (random.randint(0, 0x7fffffff),
                                  random.randint(0, 0x7fffffff))

def randomApplianceName():
    return "appl%08x%08x" % (random.randint(0, 0x7fffffff),
                             random.randint(0, 0x7fffffff))

def isUUID(x):
    if re.search(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-"
                 "[0-9a-f]{12}$", x):
        return True
    return False

def fixUUID(u):
    # Add the required -s to a UUID without them
    nu = "%s-%s-%s-%s-%s" % (u[:8],u[8:12],u[12:16],u[16:20],u[20:])
    return nu

def getHTTP(url,fname=None):
    xenrt.TEC().logverbose("Fetching %s to %s" % (url, fname))
    try:
        u = urllib2.urlopen(url)
        d = u.read()
        if fname:
            f = file(fname,"w")
            f.write(d)
            f.close()
        else:
            return d
    except urllib2.HTTPError, e:
        raise xenrt.XRTError(str(e))

def convertIpToLong(ip):
    i = ip.split(".")
    if len(i) != 4:
        raise xenrt.XRTError("Asked to convert invalid IP address %s to integer" % (ip))

    longValue = long(i[0]) * 256**3 + long(i[1]) * 256**2 + long(i[2]) * 256 + long(i[3])

    return longValue    

def convertLongToIp(longValue):
    d = 256**3
    ip = []
    while d > 0:
        m,longValue = divmod(longValue,d)
        ip.append(str(m))
        d = d/256

    return string.join(ip,'.')

def ipsInSameSubnet(ip1,ip2,subnetmask):
    ip1l = convertIpToLong(ip1)
    ip2l = convertIpToLong(ip2)
    subml = convertIpToLong(subnetmask)
    return (ip1l & subml) == (ip2l & subml)

def maskToPrefLen(mask):
    """Convert a string subnet mask (e.g. 255.255.240.0) to an integer prefix
       length (e.g. 20)"""
    m = mask.split(".")
    if len(m) != 4:
        raise xenrt.XRTError("Asked to convert invalid subnet mask %s to "
                             "prefix length" % (mask))

    length = 0
    for o in m:
        n = int(o)
        while n > 0:
            length += (n % 2)
            n = n >> 1

    return length

def sanitiseForBash(data):
    """Sanitise the provided data so it can be contained within speech marks (")
       in a bash command line"""

    # Turn any backslashes (\) in the string into double backslashes (\\)
    data = data.replace("\\", "\\\\")
    # Prefix speech marks (") with a backslash (\")
    data = data.replace("\"", "\\\"")
    # Prefix any backticks (`) with a backslash (\`)
    data = data.replace("`", "\\`")
    # Prefix any dollar signs ($) with a backslash (\$)
    data = data.replace("$", "\\$")

    return data

def compareIPForSort(a, b):
    """A compare function to use when sorting IPs for pretty display."""
    ia = IPy.IP(a)
    ib = IPy.IP(b)
    if ia > ib:
        return 1
    if ia < ib:
        return -1
    return 0

class ThreadWithException(threading.Thread):

    def __init__(self, group=None, target=None, getData=False, name=None, args=(), kwargs={}):
        # Initialise an empty exception object
        self.exception = None
        self.target = target
        self.getData = getData
        self.data = None
        self.args = args
        self.kwargs = kwargs
        threading.Thread.__init__(self, group=group, name=name)

    def run(self):
        try:
            if self.getData:
                self.data = self.target(*self.args, **self.kwargs)
            else:
                self.target(*self.args, **self.kwargs)
        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            self.exception = e

class SimpleSMTPServer(threading.Thread):
    """A very simple (not standards compliant) SMTP server"""

    def __init__(self, port=0, debug=False):
        self.mail = []
        self.port = port
        self.debug = debug
        self._shutdown = False
        threading.Thread.__init__(self)

    def _parseLine(self, line, conn, context):
        if context.has_key("data") and not context.has_key("dataComplete"):
            # In a DATA section
            if line.strip() == ".":
                if self.debug: sys.stderr.write("Finished DATA\n")
                conn.send("250 2.0.0 Ok: queued as 12345\r\n")
                context['dataComplete'] = True
                return True
            context['data'] += "%s\r\n" % (line)
        elif line.startswith("HELO"):
            conn.send("250 mail.xenrt\n")
        elif line.startswith("MAIL FROM:"):
            m = re.match("MAIL FROM:<(\S+)>", line)
            context['sender'] = m.group(1)
            if self.debug: sys.stderr.write("Sender: %s\n" % (context['sender']))
            conn.send("250 2.1.0 Ok\r\n")
        elif line.startswith("RCPT TO:"):
            m = re.match("RCPT TO:<(\S+)>", line)
            context['recipient'] = m.group(1)
            if self.debug: sys.stderr.write("Recipient: %s" % (context['recipient']))
            conn.send("250 2.1.5 Ok\r\n")
        elif line.startswith("DATA"):
            context['data'] = ""
            if self.debug: sys.stderr.write("Starting DATA\n")
            conn.send("354 End data with <CR><LF>.<CR>\r\n")
        elif line.strip() == "QUIT":
            if self.debug: sys.stderr.write("QUIT received\n")
            conn.send("221 2.0.0 Bye\r\n")
            return False
        else:
            conn.send("502 5.5.2 Error: command not recognized\r\n")

        return True

    def getMail(self):
        """Get any recevied messages"""
        return self.mail

    def clearMail(self):
        """Clear any received messages"""
        self.mail = []

    def run(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket = s
        try:
            s.bind(('', self.port))
            if self.port == 0:
                self.port = s.getsockname()[1]
            s.listen(1)
            while True:
                conn, addr = s.accept()
                if self._shutdown:
                    conn.close()
                    break
                try:
                    if self.debug: sys.stderr.write("Connection from: %s\n" % (addr[0]))
                    context = {}
                    prevData = ""
                    quit = False
                    conn.send("220 mail.xenrt SMTP XenRT\r\n")
                    context['RX timestamp'] = timenow()
                    while True:
                        data = prevData + conn.recv(4096)
                        if not data: break
                        if "\r\n" in data:
                            lines = data.split("\r\n")
                            for l in lines[:-1]:
                                try:
                                    if not self._parseLine(l, conn, context):
                                        quit = True
                                        break
                                except:
                                    conn.send("501 5.5.4 Syntax error\r\n")
                            if quit:
                                break
                            prevData = lines[-1]
                        else:
                            prevData = data
                    self.mail.append(context)
                finally:
                    if self.debug: sys.stderr.write("Connection closed\n")
                    try:
                        conn.close()
                    except:
                        pass
        finally:
            try:
                s.close()
            except:
                pass

    def stop(self):
        self._shutdown = True
        try:
            # Open a connection to trigger the shutdown...
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(("127.0.0.1", self.port))
            s.close()
        except:
            pass
        self.join(30)
        if self.isAlive():
            raise xenrt.XRTError("SimpleSMTPServer failed to shutdown")

class PhysicalProcessorMonitor(object):
    """
    Monitors the physical processors on a host.
    @author Jonathan Knowles
    """

    def __init__(self, host):
        self.host = host

    def calculateInstantaneousUsages (self, time_period_seconds = 1):
        """
        Returns instantaneous measurements of percentage CPU usages
        for all CPUs, measured over the specified short time period,
        returning results in the form:

        [usage_0, usage_1, usage_2, ..., usage_n] for n CPUs.
        """
        def calculate ():
            idle_tick_list_1 = self._readAccumulatedIdleTicks ()
            time.sleep (time_period_seconds)
            idle_tick_list_2 = self._readAccumulatedIdleTicks ()
            idle_tick_pairs = zip (idle_tick_list_1, idle_tick_list_2)
            for acc_idle_ticks_1, acc_idle_ticks_2 in idle_tick_pairs:
                yield self._calculateAmortizedUsageForSingleCPU (
                    time_period_seconds,
                    acc_idle_ticks_1,
                    acc_idle_ticks_2
                )
        return [x for x in calculate ()]

    _old_timestamp      = None
    _old_idle_tick_list = None

    def calculateAmortizedUsages (self):
        """
        Returns amortized measurements of percentage CPU usages for
        all CPUs, measured over the period of time elapsed since the
        last call to this function, returning results in the form:

        [usage_0, usage_1, usage_2, ..., usage_n] for n CPUs.
        """
        # Grab the old values.
        old_timestamp      = self._old_timestamp
        old_idle_tick_list = self._old_idle_tick_list

        # Grab the new values.
        new_timestamp      = time.time ()
        new_idle_tick_list = self._readAccumulatedIdleTicks ()

        # Overwrite the old values.
        self._old_timestamp      = new_timestamp
        self._old_idle_tick_list = new_idle_tick_list

        if old_timestamp is None:
            # We've not been called before, so fall back
            # to returning instantaneous measurements.
            return self.calculateInstantaneousUsages ()

        time_period_seconds = new_timestamp - old_timestamp
        idle_tick_pairs = zip (old_idle_tick_list, new_idle_tick_list)

        def calculate ():
            for acc_idle_ticks_1, acc_idle_ticks_2 in idle_tick_pairs:
                yield self._calculateAmortizedUsageForSingleCPU (
                    time_period_seconds,
                    acc_idle_ticks_1,
                    acc_idle_ticks_2
                )
        return [x for x in calculate ()]

    def conciseStringOfUsages (self, usages):
        """
        Returns a concise string representation of the given
        list of percentage CPU usages (as returned by any of
        the calculate_*_usages functions), of the form:

        "000.0 000.0 000.0 ... 000.0" for all CPUs
        """
        def generate_parts ():
            for usage in usages:
                yield "%05.1f" % usage
        return " ".join ([part for part in generate_parts ()])

    def _constrain (self, minimum, maximum, value):
        """
        Constrains a value within a range.
        """
        assert (minimum < maximum)

        if   value < minimum : return minimum
        elif value > maximum : return maximum
        else                 : return value

    def _calculateAmortizedUsageForSingleCPU (
            self, time_period_seconds, acc_idle_ticks_1, acc_idle_ticks_2):
        """
        Returns an amortized measurement of percentage CPU usage
        for a single CPU over the given time period, deriving the
        the measurement from the given accumulated idle tick counts.
        """
        idle_ticks = acc_idle_ticks_2 - acc_idle_ticks_1
        idle_ticks_per_second = idle_ticks / time_period_seconds
        idle_percentage = idle_ticks_per_second / 1.0e7
        busy_percentage = 100.0 - idle_percentage
        return self._constrain (0, 100, busy_percentage)

    _command = "/opt/xensource/debug/xenops pcpuinfo"
    _expression = re.compile ("cpu: ([0-9]+)  usage: ([0-9]+)")

    def _readAccumulatedIdleTicks (self):
        """
        Returns [ticks_1, ticks_2, ..., ticks_n] for n CPUs.
        """
        def read ():
            for line in self.host.execdom0(self._command).splitlines():
                matched = self._expression.match (line)
                cpu_id = int (matched.group (1))
                cpu_usage = int (matched.group (2))
                yield cpu_usage
        return [x for x in read ()]

class RunCommandPeriodically(xenrt.XRTThread):
    """A thread object that runs a local command periodically."""

    def __init__(self, cmd, period=5):
        self.cmd = cmd
        self.period = period
        self.exception = None
        xenrt.XRTThread.__init__(self)

    def run(self):
        self.running = True
        try:
            while self.running:
                data = xenrt.command(self.cmd)
                time.sleep(self.period)
        except Exception, e:
            xenrt.TEC().logverbose("Exception while running command %s", self.cmd)
            traceback.print_exc(file=sys.stderr)
            self.exception = e

    def stop(self):
        self.running = False
        self.join()

def imageRectMeanColour(image, x1, y1, x2, y2):
    """Return the mean RGB colour (as a 3-tuple) of a rectangle within the
    Image object."""
    pix = image.load()
    pixr = 0L
    pixg = 0L
    pixb = 0L
    for x in range(x1, x2):
        for y in range(y1, y2):
            pixr += pix[x, y][0]
            pixg += pix[x, y][1]
            pixb += pix[x, y][2]
    numpix = (x2 - x1) * (y2 - y1)
    return (int(pixr/numpix), int(pixg/numpix), int(pixb/numpix))


class PTask(xenrt.XRTThread):

    def __init__(self, func, *args, **kwargs):
        if type(func) not in ([ types.FunctionType,
                                types.MethodType,
                                types.ClassType ]):
            raise xenrt.XRTError("%s can not apply" % func.__name__)
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.result = None
        self.exception = None
        xenrt.XRTThread.__init__(self)

    def run(self):
        try:
            self.result = self.func(*self.args, **self.kwargs)
        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().logverbose("Exception while applying %s to (%s, %s)"
                                   % (self.func.__name__, self.args, self.kwargs))
            self.exception = e


def pfarm(tasks, start=True, interval=0, wait=True, value=True, exception=True):
    """
    Run a set of tasks in parallel

    @param tasks:     a sequence of elements from any of the 3 kinds:
                      - a sequence of (func/method/class, arg1, arg2, ...)
                      - a single func/method/class value that takes void args
                      - an instance of PTask class
    @param start:     if False, return a list of xenrt.XRTThread to run
                      func(arg1, arg2, ...) but yet to start
    @param interval:  the delay (in seconds) before launching the next task
    @param wait:      if False, return a list of xenrt.XRTThread already
                      started (but not necessarily ended)
    @param value:     if False, return a list of xenrt.XRTThread ended (joined)

    if all params above are True, pmap return a list of values got by parallel
    application of func(arg1, arg2, ...).

    @param exception: if True, the first exception (in list order) of the tasks
                      will be raised; if False, no exceptions will be raised,
                      they'll be exception values returned in the list.
    """
    
    jobs = [ isinstance(t, PTask) and t
             or hasattr(t, '__iter__') and PTask(*t)
             or PTask(t)
             for t in tasks ]

    if not start:
        return jobs
    else:
        for j in jobs:
            j.start()
            time.sleep(interval)
        if not wait:
            return jobs
        else:
            for j in jobs:
                j.join()
            if not value:
                return jobs
            else:
                result = []
                for j in jobs:
                    if j.exception and exception:
                        raise j.exception
                    else:
                        result.append(j.exception or j.result)
                return result

def pmap(func, *args, **kwargs):

    """
    A particular instance of pfarm, where the same operation will be applied to
    differen data set (given in format of map's parameters) to construct the
    parallel tasks.
    """
    ts = map(lambda *seq: PTask(func, *seq), *args)
    return pfarm(ts, **kwargs)


def rot13Encode(msg):
    """
    Encode a string into ROT13 format. 
    """
    encode_char = lambda c, base : chr(((ord(c) + 13 - base) % 26) + base)

    def encode(c):
        if c.isalpha():
            if c.isupper(): return encode_char(c, ord('A'))
            else: return encode_char(c, ord('a'))
        else:
            return c

    return string.join(map(encode, msg), '')

def roundUpMiB(num):
    """Round up the given value of bytes to the next biggest MiB value"""
    numMiB = num / float(xenrt.MEGA)
    if (numMiB - int(numMiB)) > 0:
        numMiB += 1
    return int(numMiB) * xenrt.MEGA

def roundDownMiB(num):
    """Round down the given value of bytes to the next lowest MiB value"""
    numMiB = round(num / xenrt.MEGA)
    return int(numMiB) * xenrt.MEGA


def _toggleBit(num, offset):
    """toggleBit() returns an integer with the bit at 'offset' inverted, 
       0 -> 1 and 1 -> 0."""
    
    mask = 1 << offset
    return (num ^ mask)


def getInterfaceIdentifier(macAddr):

    mac = macAddr.split(':')
    #Add ff and fe after 24 bits
    eui64Format = mac[0:3] + ['ff','fe'] + mac[3:6]

    #Flip the seventh bit
    firstOctetInDec = int(mac[0],16)
    firstOctetAfterFlip = hex(firstOctetInDec ^ (1<<1))[2:]
    eui64Format[0] = firstOctetAfterFlip
    interfaceIdentifier = []
    for i in range(0,len(eui64Format)-1,2): interfaceIdentifier.append(eui64Format[i]+ eui64Format[i+1])

    finalString = ':'.join(interfaceIdentifier)
    return finalString

def getTextFromXmlNode(node):
    for n in node.childNodes:
        if n.nodeType == n.TEXT_NODE:
            return n.data

def getRandomULAPrefix():
    first_part = xenrt.command(r"ntpq -c rv | grep clock= | sed -e 's/clock=//' -e 's/ .*//' -e 's/\.//'", strip=True)
    second_part = xenrt.command(r"/sbin/ip -6 addr show eth0 scope link | grep inet6 | sed -n 's|^.*fe80::\([^/]*\).*|\1|p' | tr -d ':'", strip=True)
    third_part = xenrt.command("echo %s%s | sha1sum | cut -c31-40" % (first_part, second_part), strip=True)
    global_id = xenrt.command("echo fd%s " % third_part + r"| sed -e 's|\(....\)\(....\)\(....\)|\1:\2:\3|'", strip=True)
    return global_id

def jobOnMachine(machine, jobid):
    try:
        job = xenrt.APIFactory().get_job(int(jobid))
    except:
        return False
    else:
        return machine in job['machines']

def canCleanJobResources(jobid):
    try:
        jobid = int(jobid)
        api = xenrt.APIFactory()
        xenrt.TEC().logverbose("Checking job %d" % jobid)
        job = api.get_job(jobid)
        # See if the job is completed
        if job['rawstatus'] != "done":
            xenrt.TEC().logverbose("Job is still running")
            return False
        # It's completed, now see whether any of the machines are borrowed, and haven't had a new job that cleans the resources
        ret = True
        for m in job['machines']:
            xenrt.TEC().logverbose("Checking whether machine %s is borrowed" % m)
            machine = api.get_machine(m)
            if machine['leaseuser']:
                xenrt.TEC().logverbose("Machine %s is borrowed, checking job number" % m)
                mjob = machine['jobid']
                if mjob != jobid:
                    xenrt.TEC().logverbose("A new job has run on this machine, checking whether it uses --existing")
                    mjobdict = api.get_job(mjob)
                    if not mjobdict['params'].has_key("CLI_ARGS_PASSTHROUGH"):
                        # This is a new job that will clean the hardware, so don't prevent resources being cleaned
                        xenrt.TEC().logverbose("Allowing the resources to be cleaned, as the new job will have cleaned the machine")
                        continue
                ret = False 
                xenrt.TEC().logverbose("Machine %s is still borrowed, so not cleaning resources" % m)
                break
    except Exception, e:
        xenrt.TEC().logverbose("Warning - could not determine whether job resources for job %s could be cleaned: %s" % (jobid, str(e)))
        ret = False
    return ret

def staleMachines(jobid):
    try:
        jobid = int(jobid)
        api = xenrt.APIFactory()
        job = api.get_job(jobid)
        ret = []
        for m in job['machines']:
            xenrt.TEC().logverbose("Checking whether machine %s is running a new job" % m)
            machine = api.get_machine(m)
            mjob = machine['jobid']
            if mjob == jobid:
                ret.append(m)
            else:
                xenrt.TEC().logverbose("A new job has run on this machine, checking whether it uses --existing")
                mjobdict = api.get_job(mjob)
                if mjobdict['params'].has_key("CLI_ARGS_PASSTHROUGH"):
                    # This is a new job that will clean the hardware, so don't prevent resources being cleaned
                    xenrt.TEC().logverbose("Marking machine as stale, as last job used --existing")
                    ret.append(m)
    except Exception, e:
        xenrt.TEC().logverbose("Warning: could not determine stale machines for job %s: %s" % (jobid, str(e)))
        ret = []
    return ret

def xrtAssert(condition, text):
    if not condition:
        raise xenrt.XRTError("Assertion %s failed" % text)

def xrtCheck(condition, text):
    if not condition:
        raise xenrt.XRTFailure("Check %s failed" % text)

def mostCommonInList(items):
    counts = {}
    for i in set(items):
        counts[i] = len([x for x in items if x==i])
    return sorted(counts, key=lambda x: counts[x], reverse=True)[0]

def keepSetup():
    keepOptions = ["OPTION_KEEP_SETUP",
                   "OPTION_KEEP_ISCSI",
                   "OPTION_KEEP_NFS",
                   "OPTION_KEEP_CVSM",
                   "OPTION_KEEP_VLANS",
                   "OPTION_KEEP_STATIC_IPS",
                   "OPTION_KEEP_UTILITY_VMS",
                   "OPTION_KEEP_GLOBAL_LOCKS"]

    for o in keepOptions:
        if xenrt.TEC().lookup(o, False, boolean=True):
            return True

    if xenrt.TEC().lookup("MACHINE_HOLD_FOR", None):
        return True

    # if machines are borrowed then keep resources
    try:
        api = xenrt.APIFactory()
        job = api.get_job(xenrt.GEC().jobid())
        for m in job['machines']:
            if api.get_machine(m)['leaseuser']:
                return True
    except Exception, ex:
        xenrt.TEC().logverbose("Exception checking if machines are borrowed: " + str(ex))

    return False

def getADConfig():

    ad = xenrt.TEC().lookup("AD_CONFIG")
    domain=ad['DOMAIN']
    dns=ad['DNS']
    domainName = ad['DOMAIN_NAME']
    adminUser = ad['ADMIN_USER']
    adminPassword = ad['ADMIN_PASSWORD']
    allUsers = ad['USERS']
    dcAddress = ad['DC_ADDRESS']
    dcDistro = ad['DC_DISTRO']

    allUsers = xenrt.TEC().lookup(["AD_CONFIG", "USERS"])

    ADConfig = namedtuple('ADConfig', ['domain', 'domainName', 'adminUser', 'allUsers','adminPassword', 'dns', 'dcAddress', 'dcDistro'])

    return ADConfig(domain=domain, domainName=domainName, adminUser=adminUser, allUsers=allUsers, adminPassword=adminPassword, dns=dns, dcAddress=dcAddress, dcDistro=dcDistro)

def getDistroAndArch(distrotext):
    if isWindows(distrotext):
        arch = "x86-32"
        if distrotext.endswith("64"):
            arch = "x86-64"
        return (distrotext, arch)
    if distrotext.endswith("-x64"):
        distro = distrotext[:-4]
        arch = "x86-64"
    elif distrotext.endswith("-x86"):
        distro = distrotext[:-4]
        arch = "x86-32"
    elif distrotext.endswith("-x32"):
        distro = distrotext[:-4]
        arch = "x86-32"
    elif distrotext.endswith("_x86-64"):
        distro = distrotext[:-7]
        arch = "x86-64"
    elif distrotext.endswith("_x86-32"):
        distro = distrotext[:-7]
        arch = "x86-32"
    else:
        distro = distrotext
        arch = "x86-32"
    return (distro, arch)

def isWindows(distro):
    return distro[0] in ("v", "w")

def isDevLinux(distro):
    if isWindows(distro):
        return False
    if "fedora" in distro:
        return True
    if "testing" in distro:
        return True
    if "devel" in distro:
        return True
    return False

def getMarvinFile():
    marvinversion = xenrt.TEC().lookup("MARVIN_VERSION", None)
    if not marvinversion:
        # The user has not specified the Marvin version to use
        if re.search('[/-]3\.0\.[1-7]', xenrt.TEC().lookup("CLOUDINPUTDIR", '')) != None or \
           re.search('[/-]3\.0\.[1-7]', xenrt.TEC().lookup("CLOUDINPUTDIR_RHEL6", '')) != None:
            marvinversion = "3.0."

    marvinFile = None
    if marvinversion:
        if marvinversion.startswith("3."):
            marvinFile = xenrt.TEC().getFile(xenrt.TEC().lookup(["MARVIN_FILE", "3.x"]), replaceExistingIfDiffers=True)
        elif marvinversion.startswith("4."):
            marvinFile = xenrt.TEC().getFile(xenrt.TEC().lookup(["MARVIN_FILE", "4.x"]), replaceExistingIfDiffers=True)
        elif marvinversion.startswith("http://") or marvinversion.startswith("https://"):
            marvinFile = xenrt.TEC().getFile(marvinversion, replaceExistingIfDiffers=True)

    if not marvinFile:
        xenrt.TEC().comment('Failed to determine marvin version, Looking for default.')
        marvinFile = xenrt.TEC().getFile(xenrt.TEC().lookup(["MARVIN_FILE", "DEFAULT"]), replaceExistingIfDiffers=True)

    xenrt.TEC().comment('Using Marvin Version: %s' % (marvinFile))
    return marvinFile

def dictToXML(d, indent):
    out = ""
    for k in sorted(d.keys()):
        if isinstance(d[k], dict):
            out += "%s<%s>\n%s%s</%s>\n" % (indent, k, dictToXML(d[k], indent + "  "),indent, k)
        elif isinstance(d[k], bool):
            out += "%s<%s>%s</%s>\n" % (indent, k, "yes" if d[k] else "no", k)
        else:
            out += "%s<%s>%s</%s>\n" % (indent, k, xml.sax.saxutils.escape(str(d[k])), k)
    return out

def getNetworkParam(network, param):
    path = ["NETWORK_CONFIG"]
    if network == "NPRI":
        path.append("DEFAULT")
    elif network == "NSEC":
        path.append("SECONDARY")
    else:
        path.append("VLANS")
        path.append(network)
    if param == "VLAN" and network not in ["NPRI", "NSEC"]:
        param = "ID"
    elif param == "ID" and network in ["NPRI", "NSEC"]:
        param = "VLAN"
    path.append(param)
    return xenrt.TEC().lookup(path)

def getCCPInputs(distro):
    defaultInputs = xenrt.TEC().lookup("CLOUDINPUTDIR", None)
    rh6Inputs = xenrt.TEC().lookup("CLOUDINPUTDIR_RHEL6", None)
    rh7Inputs = xenrt.TEC().lookup("CLOUDINPUTDIR_RHEL7", None)
    if distro and rh6Inputs and (distro.startswith("rhel6") or distro.startswith("centos6")):
        return rh6Inputs
    elif distro and rh7Inputs and (distro.startswith("rhel7") or distro.startswith("centos7")):
        return rh7Inputs
    else:
        return defaultInputs

def getCCPCommit(distro):
    defaultCommit = xenrt.TEC().lookup("CCP_EXPECTED_COMMIT", None)
    rh6Commit = xenrt.TEC().lookup("CCP_EXPECT_COMMIT_RHEL6", None)
    rh7Commit = xenrt.TEC().lookup("CCP_EXPECT_COMMIT_RHEL7", None)
    if distro and rh6Commit and (distro.startswith("rhel6") or distro.startswith("centos6")):
        return rh6Commit
    elif distro and rh7Commit and (distro.startswith("rhel7") or distro.startswith("centos7")):
        return rh7Commit
    else:
        return defaultCommit

def isUrlFetchable(filename):
    xenrt.TEC().logverbose("Attempting to check response for %s" % filename)
    try:
        proxy = xenrt.TEC().lookup("HTTP_PROXY", None)
        kwargs = {}
        if proxy:
            kwargs['proxies'] = {"http": proxy, "https": proxy}
        r = requests.head(filename, allow_redirects=True, **kwargs)
        return (r.status_code == 200)
    except:
        return False

def is32BitPV(distro, arch=None, release=None, config=None):
    if not arch:
        (distro, arch) = getDistroAndArch(distro)

    # Windows isn't PV
    if isWindows(distro):
        return False

    # 64 bit isn't 32 bit PV
    if arch != "x86-32":
        return False

    # HVM Linux isn't PV

    if not config:
        config = xenrt.TEC()

    if release and distro in config.lookup(["VERSION_CONFIG", release, "HVM_LINUX"], "").split(","):
        return False

    # We've got this far, so it must be 32 bitPV
    return True

def checkXMLDomSubset(superset, subset):
    if subset.localName != superset.localName:
        return False
    for index in range(subset.attributes.length):
        if superset.getAttribute(subset.attributes.item(index).name) != subset.attributes.item(index).value:
            return False
    for n in subset.childNodes:
        if n.nodeType == n.ELEMENT_NODE:
            sn=superset.getElementsByTagName(n.localName)
            if len(sn)==0:
                return False
            elif len(sn)>1:
                xenrt.TEC().comment("Multiple node found for '%s' in '%s'" % (n.localName, superset.toxml()))
            if not checkXMLDomSubset(sn[0],n):
                return False
    return True

def getUpdateDistro(distro):
    updateMap = xenrt.TEC().lookup("LINUX_UPDATE")
    match = ""
    newdistro = None
    # Look for the longest match
    for i in updateMap.keys():
        if distro.startswith(i) and len(i) > len(match):
            match = i
    # if we find one, we need to upgrade
    if match:
        newdistro = updateMap[match]
    if not newdistro:
        raise xenrt.XRTError("No update distro found for %s" % distro)
    return newdistro

def getLinuxRepo(distro, arch, method, default=xenrt.XRTError):
    if not arch:
        arch = "x86-32"
    if isWindows(distro):
        if default == xenrt.XRTError:
            raise xenrt.XRTError("No repo for windows")
        else:
            return default
    if distro.startswith("debian") or distro.startswith("ubuntu") or distro.startswith("fedora") or distro.startswith("coreos"):
        if method != "HTTP":
            raise xenrt.XRTError("Only HTTP install is supported")
        if distro == "debian50":
            return xenrt.TEC().lookup("DEBIAN_ARCHIVE_REPO", default=default)
        elif distro.startswith("debian"):
            return xenrt.TEC().lookup("DEBIAN_REPO", default=default)
        elif distro.startswith("ubuntu"):
            return xenrt.TEC().lookup("UBUNTU_REPO", default=default)
        elif distro.startswith("fedora"):
            if arch == "x86-32":
                farch = "i386"
            else:
                farch = "x86_64"
            return "%s/%s/os" % (xenrt.TEC().lookup(["FEDORA_REPO", distro], default=default), farch)
        elif distro.startswith("coreos"):
            channel = distro.split("-")[1]
            return xenrt.TEC().lookup(["COREOS_REPO", channel], default=default)
    else:
        try:
            path = xenrt.mountStaticISO(distro, arch)
            return "%s%s" % (xenrt.TEC().lookup(["RPM_SOURCE_%s_BASE" % method]), path)
        except:
            if default == xenrt.XRTError:
                raise
            else:
                return default

def getURLContent(url):
    sock = urllib.URLopener().open(url)
    resp = sock.read()
    sock.close()
    return resp
