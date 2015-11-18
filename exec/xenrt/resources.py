#
# XenRT: Test harness for Xen and the XenServer product family
#
# Resource management.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, tempfile, os, stat, traceback, os.path, glob, shutil,IPy
import threading, time, re, random, md5, urllib, xmlrpclib
import xenrt, xenrt.ssh

# Symbols we want to export from the package.
__all__ = ["WebDirectory",
           "NFSDirectory",
           "WorkingDirectory",
           "TempDirectory",
           "LogDirectory",
           "FTPDirectory",
           "ExternalNFSShare",
           "ExternalSMBShare",
           "NativeWindowsSMBShare",
           "NativeLinuxNFSShare",
           "VMSMBShare",
           "SpecifiedSMBShare",
           "ISCSIIndividualLun",
           "ISCSILun",
           "HBALun",
           "ISCSIVMLun",
           "ISCSINativeLinuxLun",
           "ISCSILunSpecified",
           "ISCSITemporaryLun",
           "FCHBATarget",
           "SMISiSCSITarget",
           "SMISFCTarget",
           "NetAppTarget",
           "NetAppTargetSpecified",
           "EQLTarget",
           "EQLTargetSpecified",
           "NetworkTestPeer",
           "PrivateSubnet",
           "VLANPeer",
           "BuildServer",
           "getBuildServer",
           "StaticIP4Addr",
           "StaticIP6Addr",
           "CentralResource",
           "CentralLock",
           "SharedHost",
           "PrivateVLAN",
           "PrivateRoutedVLAN",
           "ProductLicense",
           "GlobalResource",
           "getResourceInteractive"]

def getResourceInteractive(resType, argv):
    if resType == "NFS":
        res = ExternalNFSShare()
        return res.getMount()
    if resType == "SMB":
        res = ExternalSMBShare()
        return res.getMount()
    elif resType == "IP4ADDR":
        size = int(argv[0])
        addrs = StaticIP4Addr.getIPRange(size, wait=False)
        return {"start": addrs[0].getAddr(), "end": addrs[-1].getAddr()}
    elif resType == "VLAN":
        size = int(argv[0])
        vlans = PrivateVLAN.getVLANRange(size, wait=False)
        return {"start": vlans[0].getID(), "end": vlans[-1].getID()}
    elif resType == "ROUTEDVLAN":
        vlan = PrivateRoutedVLAN()
        return vlan.getNetworkConfig()

@xenrt.irregularName
def DhcpXmlRpc():
    return xmlrpclib.ServerProxy("http://localhost:1500", allow_none=True)

class DirectoryResource(object):

    def __init__(self, basedir, place=None, keep=0):
        if place:
            if place.windows:
                implementer = RemoteWindowsDirectoryResourceImplementer
                self._delegate = implementer(basedir, place, keep)
            else:
                raise xenrt.XRTError("Only Windows remote directories are currently supported.")
        else:
            implementer = LocalDirectoryResourceImplementer
            self._delegate = implementer(basedir, keep)

    def __getattr__(self, name):
        return getattr(self._delegate, name)

class WebDirectory(DirectoryResource):
    """A temporary directory exported by a web server."""
    def __init__(self, place=None):
        self.httpbasedir = xenrt.TEC().lookup("HTTP_BASE_PATH")
        self.httpbaseurl = xenrt.TEC().lookup("HTTP_BASE_URL")
        DirectoryResource.__init__(self, self.httpbasedir, place)

    def getURL(self, relpath):
        preflen = len(os.path.normpath(self.httpbasedir))
        subdir = self.dir[preflen+1:]
        if relpath == "/":
            relpath = "%s/" % (subdir)
        else:
            relpath = os.path.join(subdir, relpath)
        if self.httpbaseurl[-1] == '/':
            return self.httpbaseurl + urllib.pathname2url(relpath)
        return self.httpbaseurl + "/" + urllib.pathname2url(relpath)

    def getCIFSPath(self):
        preflen = len(os.path.normpath(self.httpbasedir))
        subdir = self.dir[preflen+1:]
        return "share\\export" + "\\" + subdir

class NFSDirectory(DirectoryResource):
    """A temporary directory exported by a NFS server."""
    def __init__(self, keep=0, place=None):
        self.nfsbasedir = xenrt.TEC().lookup("NFS_BASE_PATH")
        self.nfsbaseurl = xenrt.TEC().lookup("NFS_BASE_URL")
        DirectoryResource.__init__(self, self.nfsbasedir, keep=keep, place=place)

    def getURL(self, relpath):
        preflen = len(os.path.normpath(self.nfsbasedir))
        subdir = self.dir[preflen+1:]
        relpath = os.path.join(subdir, relpath)
        if self.nfsbaseurl[-1] == '/':
            return self.nfsbaseurl + relpath
        return self.nfsbaseurl + "/" + relpath

    def getMountURL(self, relpath):
        url = self.getURL(relpath)
        return string.replace(url, "nfs://", "")

    def getCIFSPath(self):
        return "\\\\%s\\scratch\\nfs\\%s" % (xenrt.TEC().lookup("XENRT_SERVER_ADDRESS"), os.path.basename(self.path()))

    def getHostAndPath(self, relpath):
        url = self.getURL(relpath)
        r = re.search(r"nfs://([^:]+):(/.+)", url)
        if not r:
            raise xenrt.XRTError("Unable to split NFS URL %s" % (url))
        return (r.group(1), r.group(2))

class WorkingDirectory(DirectoryResource):
    """A temporary working directory."""
    def __init__(self, place=None):
        self.basedir = xenrt.TEC().lookup("WORKING_DIR_BASE", "/tmp")
        k = xenrt.TEC().lookup("KEEP_WORKING_DIRS", False, boolean=True)
        DirectoryResource.__init__(self, self.basedir, keep=k, place=place)

class TempDirectory(DirectoryResource):
    """A temporary directory."""
    def __init__(self, place=None):
        self.basedir = xenrt.TEC().lookup("TEMP_DIR_BASE", "/tmp")
        DirectoryResource.__init__(self, self.basedir, place=place)

class FTPDirectory(TempDirectory):
    """A temporary directory exported by a FTP server."""
    USERNAME = None
    PASSWORD = None

    def getURL(self, relpath):
        ftpURL = xenrt.TEC().lookup("LOCALURL")
        if self.USERNAME and self.PASSWORD:
            ftpURL = ftpURL.replace("http://", "ftp://"+self.USERNAME+":"+self.PASSWORD+"@")
        else:
            ftpURL = ftpURL.replace("http://", "ftp://")

        # The '/' is inserted because this is the FTP delimiter
        if xenrt.TEC().lookup("WORKAROUND_CA59321", False, boolean=True):
            xenrt.TEC().warning("Using workaround for CA-59321")
            ftpPath = ftpURL + "/" + self.path() + relpath
        else:
            ftpPath = ftpURL + self.path() + relpath
        if not ftpPath.endswith('/'):
            ftpPath = ftpPath + '/'
        return ftpPath

    def setUsernameAndPassword(self, username, password):
        self.USERNAME = username
        self.PASSWORD = password

class LogDirectory(DirectoryResource):
    """A temporary directory for collating logs."""
    def __init__(self, place=None):
        self.basedir = xenrt.TEC().lookup("LOG_DIR_BASE", "/tmp/xenrtlogs")
        # Under job control we'll remove log dirs.
        if xenrt.GEC().jobid() == None:
            keep = True
        else:
            keep = False
        DirectoryResource.__init__(self, self.basedir, keep=keep, place=place)

class DirectoryResourceImplementer(object):
    """Superclass for allocating temporary directories."""
    def __init__(self, basedir, keep=0):
        try:
            if not self._exists(basedir):
                xenrt.TEC().logverbose("Creating directory %s" % (basedir))
                self._makedirs(basedir)
            self.dir = self._mkdtemp("", "xenrt", basedir)
            xenrt.TEC().logverbose("Created subdirectory %s" % (self.dir))
            self.keep = keep
            xenrt.TEC().gec.registerCallback(self)
        except Exception, e:
            self.dir = None
            traceback.print_exc(file=sys.stderr)
            raise xenrt.XRTError("Unable to create subdirectory in %s (%s)." %
                                 (basedir, str(e)))
    
    def path(self):
        return self.dir

    def copyIn(self, filespec, target=None):
        """Copy one or more files to this subdirectory."""
        files = self._glob(filespec)
        for f in files:
            if self._isfile(f):
                if target:
                    targetd = os.path.dirname(target)
                    if targetd:
                        targetd = "%s/%s" % (self.dir, targetd)
                        if not self._exists(targetd):
                            self._makedirs(targetd)
                    dest = "%s/%s" % (self.dir, target)
                else:
                    dest = self.dir
                self._copy(f, dest)
                xenrt.TEC().logverbose("Copied %s to %s" % (f, dest))
            elif self._isdir(f):
                self._copytree(f, "%s/%s" % (self.dir, os.path.basename(f)))
                xenrt.TEC().logverbose("Copied %s to %s" % (f, self.dir))

    def remove(self):
        if self.dir and self.keep == 0:
            try:
                if self._exists(self.dir):
                    xenrt.TEC().logverbose("Removing directory %s" %
                                           (self.dir))
                    self._rmtree(self.dir)
                    self.dir = None
                    xenrt.TEC().gec.unregisterCallback(self)
            except OSError:
                xenrt.TEC().logerror("Error removing directory %s" %
                                     (self.dir))
                
    def callback(self):
        self.remove()

    def _mkdtemp(self, suffix, prefix, path):
        raise xenrt.XRTError("Unimplemented.")

    def _exists(self, path):
        raise xenrt.XRTError("Unimplemented.")

    def _makedirs(self, path):
        raise xenrt.XRTError("Unimplemented.")

    def _glob(self, filespec):
        raise xenrt.XRTError("Unimplemented.")

    def _isfile(self, path):
        raise xenrt.XRTError("Unimplemented.")

    def _isdir(self, path):
        raise xenrt.XRTError("Unimplemented.")
   
    def _copy(self, path, destination):
        raise xenrt.XRTError("Unimplemented.")
        
    def _copytree(self, path, destination):
        raise xenrt.XRTError("Unimplemented.")
 
    def _rmtree(self, path):
        raise xenrt.XRTError("Unimplemented.")

class RemoteWindowsDirectoryResourceImplementer(DirectoryResourceImplementer):
    
    def __init__(self, basedir, place, keep=0):
        self.place = place
        DirectoryResourceImplementer.__init__(self, 
                                              self._convert(basedir), 
                                              keep)

    def _convert(self, path):
        return re.sub("/", "\\\\", path)

    def _exists(self, path):
        return self.place.xmlrpcFileExists(path)

    def _makedirs(self, path):
        return self.place.xmlrpcCreateDir(path)

    def _mkdtemp(self, suffix, prefix, path):
        return self.place.xmlrpcTempDir(suffix, prefix, path)

    def _glob(self, filespec):
        return glob.glob(filespec)

    def _isfile(self, path):
        return os.path.isfile(path)

    def _isdir(self, path):
        return os.path.isdir(path)

    def _copy(self, path, destination):
        if not os.path.dirname(destination):
            destination = destination + "\\" + os.path.basename(path)
        self.place.xmlrpcSendFile(path, destination, usehttp=True)
        
    def _copytree(self, path, destination):
        self.place.xmlrpcSendRecursive(path, destination)

    def _rmtree(self, path):
        self.place.xmlrpcDelTree(path)

class LocalDirectoryResourceImplementer(DirectoryResourceImplementer):

    def _exists(self, path):
        return os.path.exists(path)

    def _makedirs(self, path):
        os.makedirs(path)

    def _mkdtemp(self, suffix, prefix, path):
        prefix = "%s-%s" % (xenrt.TEC().lookup("JOBID", "nojob"), prefix)
        dir = tempfile.mkdtemp(suffix, prefix, path)
        os.chmod(dir, stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)
        return dir

    def _glob(self, filespec):
        return glob.glob(filespec)

    def _isfile(self, path):
        return os.path.isfile(path)

    def _isdir(self, path):
        return os.path.isdir(path)

    def _copy(self, path, destination):
        shutil.copy(path, destination)
        
    def _copytree(self, path, destination):
        shutil.copytree(path, destination)

    def _rmtree(self, path):
        xenrt.rootops.sudo("rm -rf %s" % path)

#############################################################################

class CentralResource(object):
    """Defines a resource shared by multiple test job instances."""
    def __init__(self, held=True, timeout=None):
        self.timeout = timeout
        self.lockfile = None
        self.mylock = threading.Lock()
        self.resourceHeld = held
        self.id = None
        xenrt.TEC().gec.registerCallback(self, mark=True, order=1)

    @staticmethod
    def isLocked(id):
        d = xenrt.TEC().lookup("RESOURCE_LOCK_DIR")
        lockfile = "%s/%s" % (d, md5.new(id).hexdigest())
        if os.path.exists(lockfile):
            return True
        else:
            return False

    def createLockDir(self):
        d = xenrt.TEC().lookup("RESOURCE_LOCK_DIR")
        os.makedirs(d)
        os.chmod(d, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)

    def acquire(self, id, shared=False):
        if shared:
            self.lockid = id
            self._addToRegistry()
            return
        d = xenrt.TEC().lookup("RESOURCE_LOCK_DIR")
        if not os.path.exists(d):
            self.createLockDir()
        lockfile = "%s/%s" % (d, md5.new(id).hexdigest())
        try:
            os.mkdir(lockfile)
            self.lockfile = lockfile
        except:
            if self.timeout:
                id, held, d = self._listProcess(id)
                if (int(d["timestamp"]) + self.timeout) < int(time.time()):
                    shutil.rmtree(lockfile)
                    try:
                        os.mkdir(lockfile)
                        self.lockfile = lockfile
                    except:
                        raise xenrt.XRTError("Lock %s held by someone else" % (id))
                else:
                    raise xenrt.XRTError("Lock %s held by someone else" % (id))
            else:
                raise xenrt.XRTError("Lock %s held by someone else" % (id))
        try:
            f = file("%s/id" % (lockfile), "w")
            f.write(id)
            f.close()
        except:
            pass
        try:
            f = file("%s/timestamp" % (lockfile), "w")
            f.write(str(xenrt.util.timenow()))
            f.close()
        except:
            pass
        try:
            j = xenrt.GEC().jobid()
            if j:
                f = file("%s/jobid" % (lockfile), "w")
                f.write(str(j))
                f.close()
        except:
            pass
        self.lockid = id
        self._addToRegistry()

    def _addToRegistry(self):
        xenrt.GEC().registry.centralResourcePut(self.lockid, self)

    def _listProcess(self,id):
        d = xenrt.TEC().lookup("RESOURCE_LOCK_DIR")
        md5id = md5.new(id).hexdigest()
        path = "%s/%s" % (d, md5id)
        if os.path.exists(path):
            newid = None
            try:
                f = file("%s/id" % (path), "r")
                newid = f.read()
                f.close()
                if newid != id:
                    xenrt.TEC().warning("id inside lockdir (%s) does not equal"
                                        " id of resource %s" % (newid,id))
            except:
                pass
            timestamp = None
            try:
                f = file("%s/timestamp" % (path), "r")
                timestamp = f.read()
                f.close()
            except:
                pass
            jobid = None
            try:
                f = file("%s/jobid" % (path), "r")
                jobid = f.read()
                f.close()
            except:
                pass

            return (id,True,{'md5':md5id, 'timestamp':timestamp, 'jobid':jobid})
        else:
            return (id,False,None)

    def logList(self):
        locks = self.list()
        for l in locks:
            (name,locked,lockinfo) = l
            locktext = "%s: " % name
            if locked:
                locktext += "locked"
                if lockinfo:
                    lockinfotext = map(lambda x: "%s: %s" % (x, lockinfo[x]), lockinfo.keys())
                    locktext += " (%s)" % string.join(lockinfotext, ", ")
            else:
                locktext += "Not locked"
            xenrt.TEC().logverbose(locktext)

    def list(self):
        """List all shared resources and their locking status"""
        locks = []
        # Static locks
        locks.append(self._listProcess("PV_ISO_LOCK"))
        # NetworkTestPeer locks
        ntpl = xenrt.TEC().lookup("TTCP_PEERS",None)
        if ntpl:
            for k in ntpl:
                locks.append(self._listProcess("TTCP_PEER-%s" % (k)))
        # ISCSILun locks
        isll = xenrt.TEC().lookup("ISCSI_LUNS",None)
        if isll:
            for k in isll:
                locks.append(self._listProcess("ISCSI_LUN-%s" % (k)))
        # ISCSILunGroup locks
        isll = xenrt.TEC().lookup("ISCSI_LUN_GROUPS",None)
        if isll:
            for k in isll:
                locks.append(self._listProcess("ISCSI_LUN_GROUP-%s" % (k)))
        # NetAppTarget locks
        natl = xenrt.TEC().lookup("NETAPP_FILERS",None)
        if natl:
            for k in natl:
                locks.append(self._listProcess("NETAPP_TARGET-%s" % (k)))
        # EQLTarget locks
        eqltl = xenrt.TEC().lookup("EQUALLOGIC",None)
        if eqltl:
            for k in eqltl:
                locks.append(self._listProcess("EQUALLOGIC-%s" % (k)))
        # SMISiSCSITarget locks
        smisitl = xenrt.TEC().lookup("SMIS_ISCSI_TARGETS",None)
        if smisitl:
            for k in smisitl:
                locks.append(self._listProcess("SMIS_ISCSI_TARGETS-%s" % (k)))
        # SMISFCTarget locks
        smisftl = xenrt.TEC().lookup("SMIS_FC_TARGETS",None)
        if smisftl:
            for k in smisftl:
                locks.append(self._listProcess("SMIS_FC_TARGETS-%s" % (k)))
        # FCProvider locks
        fctl = xenrt.TEC().lookup("FC_PROVIDER",None)
        if fctl:
            for k in fctl:
                locks.append(self._listProcess("FC_PROVIDER-%s" % (k)))
        # IPRange locks
        iptl = xenrt.TEC().lookup("IPRANGES",None)
        if iptl:
            for k in iptl:
                locks.append(self._listProcess("IPRANGE-%s" % (k)))

        liclist = xenrt.TEC().lookup("LICENSES", None)
        if liclist:
            for p in liclist.keys():
                for l in liclist[p].keys():
                    locks.append(self._listProcess("LICENSE-%s-%s" % (p[8:], l)))

        
        if xenrt.TEC().lookup("XENRT_DHCPD", False, boolean=True):
            addrs = DhcpXmlRpc().listReservedAddresses()
            for a in addrs:
                if a[1] == "nojob":
                    a[1] = None
                locks.append(("EXT-IP4ADDR-%s" % a[0], True, {'jobid': a[1], 'timestamp': a[2]}))

        # Handle any left
        dealtwith = []
        for l in locks:
            dealtwith.append(l[0])

        d = xenrt.TEC().lookup("RESOURCE_LOCK_DIR")
        entries = os.listdir(d)
        for e in entries:
            lf = "%s/%s" % (d,e)
            id = None
            try:
                f = file("%s/id" % (lf))
                id = f.read()
                f.close()
            except:
                continue # If we can't read ID, ignore it
            if not id in dealtwith:
                timestamp = None
                try:
                    f = file("%s/timestamp" % (lf))
                    timestamp = f.read()
                    f.close()
                except:
                    pass
                jobid = None
                try:
                    f = file("%s/jobid" % (lf))
                    jobid = f.read()
                    f.close()
                except:
                    pass

                locks.append((id,True,{'md5':e,'timestamp':timestamp,
                                       'jobid':jobid}))

        return locks
        
    def release(self, atExit=False):
        """Release the resource after use."""
        if self.resourceHeld:
            if self.lockfile:
                try:
                    os.unlink("%s/jobid" % (self.lockfile))
                except:
                    pass
                try:
                    os.unlink("%s/id" % (self.lockfile))
                except:
                    pass
                try:
                    os.unlink("%s/timestamp" % (self.lockfile))
                except:
                    pass
                os.rmdir(self.lockfile)
                self.lockfile = None
            self.resourceHeld = False
            self.id = None
            xenrt.TEC().gec.unregisterCallback(self)

    def mark(self):
        """Update the timestamp on any held locks to show we're not dead"""
        if self.lockfile and self.resourceHeld:
            f = file("%s/timestamp" % (self.lockfile), "w")
            f.write(str(xenrt.util.timenow()))
            f.close()

    def callback(self):
        self.release(atExit=True)

class CentralLock(CentralResource):
    """Implementation of a central lock"""
    def __init__(self, id, timeout=3600, acquire=True):
        CentralResource.__init__(self, timeout=timeout)
        self.id = id
        if acquire:
            self.acquire()

    def acquire(self):
        startlooking = xenrt.util.timenow()
        while True:
            try:
                CentralResource.acquire(self, self.id, shared=False)
                break
            except xenrt.XRTError:
                pass 
            if xenrt.util.timenow() > (startlooking + self.timeout):
                xenrt.TEC().logverbose("Timed out waiting for lock after %d seconds" % self.timeout)
                self.logList()
                raise xenrt.XRTError("Timed out waiting for lock")
            xenrt.sleep(30)

class ManagedStorageResource(CentralResource):
    """Resources that can be used as CVSM targets should inherit this class."""

    def preAddStorageSystemHook(self, cvsmserver):
        """Called before trying to add the resource as a storage system to
        the CVSM service."""
        pass

    def getName(self):
        raise xenrt.XRTError("Unimplemented")

    def getTarget(self):
        raise xenrt.XRTError("Unimplemented")

    def getUsername(self):
        raise xenrt.XRTError("Unimplemented")

    def getPassword(self):
        raise xenrt.XRTError("Unimplemented")

    def getType(self):
        raise xenrt.XRTError("Unimplemented")
    
    def getDisplayName(self):
        raise xenrt.XRTError("Unimplemented")

    def getFriendlyName(self):
        raise xenrt.XRTError("Unimplemented")

    def getProtocolList(self):
        """Return a list of CVSM transport protocols supported by this target.
        """
        return ["iscsi", "fc"]
    
    def getNamespace(self):
        return None

class _ExternalFileShare(CentralResource):
    """An file share volume, or subdirectory thereof, on an external share server"""
    def __init__(self, jumbo=False, network="NPRI", version=None, cifsuser=None):
        self.subdir = None
        if not version:
            version = self.DEFAULT_VERSION
        version = str(version)
        self.version = version
        # Find a suitable server
        serverdict = xenrt.TEC().lookup(self.SHARE_TYPE, None)
        if not serverdict:
            raise xenrt.XRTError("No %s defined" % self.SHARE_TYPE)
        servers = serverdict.keys()
        if len(servers) == 0:
            raise xenrt.XRTError("No %s defined" % self.SHARE_TYPE)
        # Generate a list of suitable servers based on jumbo frame preference
        okservers = []
        preferredservers = []
        for s in servers:
            ok = True
            preferred = False
            xjumbo = xenrt.TEC().lookup([self.SHARE_TYPE,
                                         s, "JUMBO"], False, boolean=True)
            if jumbo and not xjumbo:
                ok = False
            if not jumbo and xjumbo:
                ok = False
            xversions = xenrt.TEC().lookup([self.SHARE_TYPE, s, "SUPPORTED_VERSIONS"], self.version).split(",")
            if version not in xversions:
                ok = False
            if network == "NPRI":
                address = xenrt.TEC().lookup([self.SHARE_TYPE,
                                                         s, "ADDRESS"], None)
            else:
                address = xenrt.TEC().lookup([self.SHARE_TYPE, s, "SECONDARY_ADDRESSES", network], None)
            if not address:
                ok = False
            reserved = xenrt.TEC().lookup([self.SHARE_TYPE, s, "RESERVED"], None)
            if reserved:
                allowedmachines = reserved.split(",")
                machines = []
                i = 0
                while True:
                    try:
                        machines.append(xenrt.TEC().lookup("RESOURCE_HOST_%d" % i))
                        i += 1
                    except:
                        break
                allowed = False
                for m in allowedmachines:
                    if m in machines:
                        allowed = True
                if not allowed:
                    ok = False
                else:
                    preferred = True
            if ok:
                okservers.append(s)
            if preferred:
                preferredservers.append(s)


        if len(okservers) == 0:
            raise xenrt.XRTError("No suitable %s defined "
                                 "(after jumbo frame validation, network validation and reserved server validation)" % self.SHARE_TYPE)
        if len(preferredservers) > 0:
            name = random.choice(preferredservers)
        else:
            name = random.choice(okservers)
        name = xenrt.TEC().lookup("USE_NFS_SERVER", name)
        name = xenrt.TEC().lookup("USE_FILE_SERVER", name)
        CentralResource.__init__(self)
        self.name = name
        # Get details of this resource from the config
        if network == "NPRI":
            self.address = xenrt.TEC().lookup([self.SHARE_TYPE,
                                           name,
                                           "ADDRESS"],
                                          None)
        else:
            self.address = xenrt.TEC().lookup([self.SHARE_TYPE,
                                           name,
                                           "SECONDARY_ADDRESSES",
                                           network],
                                           None)
        self.base = xenrt.TEC().lookup([self.SHARE_TYPE,
                                        name,
                                        "BASE"],
                                       None)

        sharepath = "%s:%s" % (self.address, self.base)
        m = self.mount(sharepath, cifsuser)
        mp = m.getMount()
        td = string.strip(xenrt.rootops.sudo("mktemp -d %s/%s-XXXXXX" % (mp, xenrt.TEC().lookup("JOBID", "nojob"))))
        self.setPermissions(td)
        self.subdir = "%s/%s" % (self.base, os.path.basename(td))
        m.unmount()

    def release(self, atExit=False):
        if self.subdir:
            if xenrt.util.keepSetup():
                xenrt.TEC().logverbose("Not deleting file export %s" %
                                       (self.getMount()))
            else:
                if atExit:
                    for host in xenrt.TEC().registry.hostList():
                        if host == "SHARED":
                            continue
                        h = xenrt.TEC().registry.hostGet(host)
                        h.machine.exitPowerOff()
                # Mount it here to remove the tree
                m = self.mount("%s:%s" % (self.address, self.base))
                mp = m.getMount()
                xenrt.rootops.sudo("rm -rf %s/%s" %
                                   (mp, os.path.basename(self.subdir)))
                m.unmount()
                self.subdir = None
        CentralResource.release(self, atExit)

    def getMount(self):
        if not self.subdir:
            raise xenrt.XRTError("No mount directory available")
        return "%s:%s" % (self.address, self.subdir)

class ExternalNFSShare(_ExternalFileShare):
    SHARE_TYPE="EXTERNAL_NFS_SERVERS"
    DEFAULT_VERSION = "3"

    def mount(self, path, cifsuser):
        return xenrt.rootops.MountNFS(path, version=self.version)

    def setPermissions(self, td):
        xenrt.rootops.sudo("chmod 777 %s" % (td))

class ExternalSMBShare(_ExternalFileShare):
    SHARE_TYPE="EXTERNAL_SMB_SERVERS"
    DEFAULT_VERSION = "2"

    def mount(self, path, cifsuser):
        ad = xenrt.getADConfig()
        self.user = ad.adminUser
        self.password = ad.adminPassword
        self.domain = ad.domainName

        if cifsuser:
            self.user = ad.allUsers['CIFS_USER'].split(":", 1)[0]
            self.password = ad.allUsers['CIFS_USER'].split(":", 1)[1]

        return xenrt.rootops.MountSMB(path, self.domain, self.user, self.password)

    def getUNCPath(self):
        return "\\\\%s%s" % (self.address, self.subdir.replace("/", "\\"))

    def getEscapedUNCPath(self):
        return self.getUNCPath().replace("\\", "\\\\")

    def getLinuxUNCPath(self):
        return self.getUNCPath().replace("\\", "/")

    def setPermissions(self, td):
        pass

class ISCSIIndividualLun(object):
    """An individual iSCSI LUN from a group of LUNs"""
    def __init__(self,
                 lungroup,
                 lunid,
                 size=0,
                 scsiid=None,
                 server=None,
                 targetname=None):
        self.lungroup = lungroup
        self.lunid = lunid
        self.size = size
        self.scsiid = scsiid
        self.server = server
        self.targetname = targetname
        self.sharedDB = None
        self.chap = None
        self.outgoingChap = None

    def getTargetName(self):
        if self.targetname:
            return self.targetname
        return self.lungroup.getTargetName()

    def getServer(self):
        if self.server:
            return self.server
        return self.lungroup.getServer()

    def getID(self):
        return self.scsiid

    def setID(self, scsiid):
        self.scsiid = scsiid

    def getSize(self):
        return self.size

    def getLunID(self):
        return self.lunid

    def getCHAP(self):
        if self.chap:
            return self.chap
        if not self.lungroup:
            return None
        return self.lungroup.getCHAP()
    
    def getOutgoingCHAP(self):
        return self.outgoingChap
    
    def getInitiatorName(self, allocate=False):
        return self.lungroup.getInitiatorName(allocate=allocate)
    
    def _release(self):
        if xenrt.util.keepSetup():
            xenrt.TEC().logverbose("Not disconnecting from iSCSI %s:%s %s (%u)"
                                   % (self.getServer(),
                                      self.getTargetName(),
                                      self.getID(),
                                      self.getLunID()))
        else:
            for host in xenrt.TEC().registry.hostList():
                for sr in xenrt.TEC().registry.hostGet(host).srs.values():
                    if sr.lun == self:
                        try:
                            sr.remove()
                        except Exception, e:
                            traceback.print_exc(file=sys.stderr)
        
            if self.sharedDB:
                # This is a host that is using this LUN for a shared DB
                # Stop xapi and unmount...
                try:
                    self.sharedDB.execdom0("/etc/init.d/xapi stop")
                    self.sharedDB.execdom0("umount -f /var/xapi/shared_db")
                    self.sharedDB.execdom0("rm -f "
                                           "/etc/xensource/remote.db.conf")
                    self.sharedDB.execdom0("/bin/cp -f "
                                           "/etc/xensource/local.db.conf "
                                           "/etc/xensource/db.conf")
                    self.sharedDB.execdom0("/etc/init.d/xapi start")
                    self.sharedDB = None
                except Exception, e:
                    traceback.print_exc(file=sys.stderr)

class _ISCSILunBase(CentralResource):
    def filterLuns(self,
                 keyname,
                 startlist,
                 minsize=10,
                 ttype=None,
                 hwtype=None,
                 maxsize=10000000,
                 jumbo=False,
                 mpprdac=None,
                 params={}):
        # Find a suitable LUN
        names = []
        for s in startlist:
            # Check if the jumbo frames option is suitable
            xjumbo = xenrt.TEC().lookup([keyname, s, "JUMBO"], False, boolean=True)
            if jumbo and not xjumbo: # Need jumbo but this isn't
                continue
            if not jumbo and xjumbo: # Don't want jumbo but this is
                continue

            xmpprdac = xenrt.TEC().lookup([keyname, s, "MPPRDAC"], False, boolean=True)
            if mpprdac and not xmpprdac: # Need MPP RDAC but this isn't
                continue
            if type(mpprdac) == type(False) and not mpprdac and xmpprdac: # Don't want MPP RDAC but this is
                continue

            # Check if the size is suitable
            xsize = int(xenrt.TEC().lookup([keyname, s, "SIZE"], 0))
            if xsize < minsize:
                continue
            if xsize > maxsize:
                continue

            # Check if the type (hardware/software) is suitable
            xtype = xenrt.TEC().lookup([keyname, s, "TYPE"], "unknown")
            if ttype and ttype != xtype:
                continue
            
            if not ttype and xtype.endswith("-reserved"):
                # Only use flash-reserved if we ask for it
                continue
            
            # Check the suitable hardware type
            htype = xenrt.TEC().lookup([keyname, s, "HWTYPE"], "unknown")
            if hwtype and hwtype != htype:
                continue
            # Check we have enough initiator names defined
            if params.has_key("INITIATORS"):
                want = int(params["INITIATORS"])
                have = int(xenrt.TEC().lookup([keyname,
                                               s,
                                               "INITIATOR_COUNT"], "1"))
                if want > have:
                    xenrt.TEC().logverbose("LUN has %u initiators defined "
                                           "but we want %u" % (have, want))
                    continue

            # Check if the network is suitable. Unless otherwise defined
            # the LUN and requested are assumed to be NPRI
            if params.has_key("NETWORK"):
                nw = params["NETWORK"]
                # The primary network for the LUN
                xnws = [xenrt.TEC().lookup([keyname, s, "NETWORK"],
                                           "NPRI")]
                # See if the LUN is available on other networks
                addict = xenrt.TEC().lookup([keyname,
                                             s,
                                             "ALTERNATE_ADDRESSES"], None)
                if addict:
                    xnws.extend(addict.keys())
                if not nw in xnws:
                    xenrt.TEC().logverbose("LUN %s has networks %s but we "
                                           "want %s" % (s, str(xnws), nw))
                    continue

            # All OK, we'll consider this LUN
            names.append(s)
        if len(names) == 0:
            raise xenrt.XRTError("Could not find a suitable LUN "
                                 "(size>%uG, type=%s, hardwaretype=%s)" % (minsize, ttype, hwtype))
        return names   

class ISCSILunGroup(_ISCSILunBase):

    def __init__(self,
                 luncount,
                 minsize=10,
                 ttype=None,
                 hwtype=None,
                 maxsize=10000000,
                 jumbo=False,
                 mpprdac=None,
                 params={}):
        """minsize is in GB
        ttype can be "hardware", "software" or None for any"""
        CentralResource.__init__(self)
        xenrt.TEC().logverbose("About to attempt to lock ISCSI LUN group with %d LUNs - current central resource status:" % luncount)
        self.logList()
        serverdict = xenrt.TEC().lookup("ISCSI_LUN_GROUPS", None)
        if not serverdict:
            raise xenrt.XRTError("No ISCSI_LUN_GROUPS defined")
        servers = sorted(serverdict.keys())
        if len(servers) == 0:
            raise xenrt.XRTError("No ISCSI_LUN_GROUPS defined")
        names = []
        for s in servers:
            lunnames = xenrt.TEC().lookup(["ISCSI_LUN_GROUPS",s,"LUNS"]).values()
            if len(lunnames) >= luncount:
                names.append(s)
        names = self.filterLuns("ISCSI_LUN_GROUPS",names,minsize, ttype, hwtype, maxsize, jumbo, mpprdac, params)
        CentralResource.__init__(self, held=False)
        name = None
        startlooking = xenrt.util.timenow()
        self.luns = []
        # Find one of the LUNs that is available
        while True:
            for n in names:
                xenrt.TEC().logverbose("Examining %s" % n)
                lunnames = xenrt.TEC().lookup(["ISCSI_LUN_GROUPS",n,"LUNS"]).values()
                print lunnames
                try:
                    id, held, d = self._listProcess("ISCSI_LUN_GROUP-%s" % n)
                    if held:
                        raise xenrt.XRTError("Resource already locked")
                    useluns = []
                    # Check whether all the luns are available
                    for l in lunnames:
                        id, held, d = self._listProcess("ISCSI_LUN-%s" % l)
                        if not held:
                            useluns.append(l)
                    if len(useluns) < luncount:
                        raise xenrt.XRTError("Insufficient free LUNs, need %d, found %d" % (luncount, len(useluns)))
                    # Then actually try to lock them all
                    self.acquire("ISCSI_LUN_GROUP-%s" % n)
                    self.resourceHeld = True
                    for l in useluns[0:luncount]:
                        xenrt.TEC().logverbose("Locking %s" % l) 
                        lun = ISCSILun(name=l)
                        self.luns.append(lun)
                    name = n
                    break
                except xenrt.XRTError, e:
                    xenrt.TEC().logverbose("Exception %s" % str(e))
                    self.release()
                    self.resourceHeld = False
                    self.luns = []
                    continue
            if name:
                xenrt.TEC().logverbose("Locked %s" % name)
                self.logList()
                break
            if xenrt.util.timenow() > (startlooking + 3600):
                xenrt.TEC().logverbose("Could not lock ISCSI LUN group, current central resource status:")
                self.logList()
                raise xenrt.XRTError("Timed out waiting for a LUN group to be "
                                     "available")
            xenrt.sleep(60)
            
        self.name = name
        
        # Get details of this resource from the config
        self.initiatornamebase = xenrt.TEC().lookup(["ISCSI_LUN_GROUPS",
                                                     name,
                                                     "INITIATOR_NAME"],
                                                    None)
        self.initiatorcount = int(xenrt.TEC().lookup(["ISCSI_LUN_GROUPS",
                                                      name,
                                                      "INITIATOR_COUNT"],
                                                     "1"))
        self.initiatorstart = int(xenrt.TEC().lookup(["ISCSI_LUN_GROUPS",
                                                      name,
                                                      "INITIATOR_START"],
                                                     "0"))
        r = re.search(r"(%\d*u)", self.initiatornamebase)
        if r:
            pattern = r.group(1)
            self.initiatornames = {}
            for i in range(self.initiatorstart,
                           self.initiatorstart + self.initiatorcount):
                iname = string.replace(self.initiatornamebase,
                                       pattern,
                                       pattern % (i))
                self.initiatornames[iname] = False
                if i == self.initiatorstart:
                    self.initiatorname = iname
        else:
            self.initiatorname = self.initiatornamebase
            self.initiatornames = {}
            self.initiatornames[self.initiatorname] = False
            self.initiatorcount = 0
        self.allocatedluncount = 0

    def getInitiatorName(self, allocate=False):
        if not allocate or self.initiatorcount == 0:
            return self.initiatorname
        for iqn in self.initiatornames.keys():
            if not self.initiatornames[iqn]:
                self.initiatornames[iqn] = True
                return iqn
        raise xenrt.XRTError("No unused IQNs left")

    def allocateLun(self):
        if len(self.luns) <= self.allocatedluncount:
            raise xenrt.XRTError("No unused LUNs left, %d available, %d allocated" % (len(self.luns), self.allocatedluncount))
        lun = self.luns[self.allocatedluncount]
        self.allocatedluncount += 1
        return lun

    def release(self, atExit=False):
        if xenrt.util.keepSetup():
            return
        for l in self.luns:
            l.release(atExit=atExit)
        CentralResource.release(self, atExit)


class ISCSILun(_ISCSILunBase):
    """An iSCSI LUN from a central shared pool."""
    def __init__(self,
                 minsize=10,
                 ttype=None,
                 hwtype=None,
                 maxsize=10000000,
                 jumbo=False,
                 mpprdac=None,
                 params={},
                 name=None,
                 usewildcard=False):
        """minsize is in GB
        ttype can be "hardware", "software" or None for any
        hwtype can be specific hardware or None for any"""
        if name:
            CentralResource.__init__(self, held=False)
            self.name = name
            self.acquire("ISCSI_LUN-%s" % (name))
            self.resourceHeld = True
        else:
            CentralResource.__init__(self)
            xenrt.TEC().logverbose("About to attempt to lock ISCSI LUN - current central resource status:")
            self.logList()
            serverdict = xenrt.TEC().lookup("ISCSI_LUNS", None)
            if not serverdict:
                raise xenrt.XRTError("No ISCSI_LUNS defined")
            servers = sorted(serverdict.keys())
            if len(servers) == 0:
                raise xenrt.XRTError("No ISCSI_LUNS defined")
            names = self.filterLuns("ISCSI_LUNS",servers,minsize, ttype, hwtype, maxsize, jumbo, mpprdac, params)
            # Sort the list of LUNs in order of size (so we find the smallest available)
            names.sort(key=lambda n: int(xenrt.TEC().lookup(["ISCSI_LUNS", n, "SIZE"], 0)))
            CentralResource.__init__(self, held=False)
            name = None
            startlooking = xenrt.util.timenow()
            # Find one of the LUNs that is available
            while True:
                for n in names:
                    try:
                        self.acquire("ISCSI_LUN-%s" % (n))
                        name = n
                        self.resourceHeld = True
                        break
                    except xenrt.XRTError:
                        continue
                if name:
                    break
                if xenrt.util.timenow() > (startlooking + 3600):
                    xenrt.TEC().logverbose("Could not lock ISCSI LUN, current central resource status:")
                    self.logList()
                    raise xenrt.XRTError("Timed out waiting for a LUN to be "
                                         "available")
                xenrt.sleep(60)
            self.name = name
        # Get details of this resource from the config
        self.initiatornamebase = xenrt.TEC().lookup(["ISCSI_LUNS",
                                                     name,
                                                     "INITIATOR_NAME"],
                                                    None)
        self.initiatorcount = int(xenrt.TEC().lookup(["ISCSI_LUNS",
                                                      name,
                                                      "INITIATOR_COUNT"],
                                                     "1"))
        self.initiatorstart = int(xenrt.TEC().lookup(["ISCSI_LUNS",
                                                      name,
                                                      "INITIATOR_START"],
                                                     "0"))
        if usewildcard:
            self.targetname = "*"
        else:
            self.targetname = xenrt.TEC().lookup(["ISCSI_LUNS",
                                                  name,
                                                  "TARGET_NAME"],
                                                None)
        self.lunid = int(xenrt.TEC().lookup(["ISCSI_LUNS",
                                              name,
                                              "LUN_ID"],
                                             "0"))
        
        # Get details of the iscsi filer for this resource if available
        self.filername = xenrt.TEC().lookup(["ISCSI_LUNS", name, "FILER"], None)
        if self.filername:
            self.primaryIPs = xenrt.TEC().lookup(["ISCSI_FILERS", self.filername, "PRIMARY"], None)
            self.primaryNetconfig = xenrt.TEC().lookup(["ISCSI_FILERS", self.filername, "PRIMARY_NETCONFIG"], None)
            self.secondaryIPs = xenrt.TEC().lookup(["ISCSI_FILERS", self.filername, "SECONDARY"], None)
            self.secondaryNetconfig = xenrt.TEC().lookup(["ISCSI_FILERS", self.filername, "SECONDARY_NETCONFIG"], None)
        
        if params.has_key("NETWORK"):
            # We specified a network, make sure we use the correct server
            # address for that
            nw = xenrt.TEC().lookup(["ISCSI_LUNS",
                                     name,
                                     "NETWORK"],
                                    "NPRI")
            if nw == params["NETWORK"]:
                # It's the main network for the LUN
                self.server = xenrt.TEC().lookup(["ISCSI_LUNS",
                                                  name,
                                                  "SERVER_ADDRESS"],
                                                 None)
            else:
                # Use an alternate address
                self.server = xenrt.TEC().lookup(["ISCSI_LUNS",
                                                  name,
                                                  "ALTERNATE_ADDRESSES",
                                                  params["NETWORK"]],
                                                 None)
        else:
            self.server = xenrt.TEC().lookup(["ISCSI_LUNS",
                                              name,
                                              "SERVER_ADDRESS"],
                                             None)
        self.scsiid = xenrt.TEC().lookup(["ISCSI_LUNS",
                                          name,
                                          "SCSIID"],
                                         None)

        r = re.search(r"(%\d*u)", self.initiatornamebase)
        if r:
            pattern = r.group(1)
            self.initiatornames = {}
            for i in range(self.initiatorstart,
                           self.initiatorstart + self.initiatorcount):
                iname = string.replace(self.initiatornamebase,
                                       pattern,
                                       pattern % (i))
                self.initiatornames[iname] = False
                if i == self.initiatorstart:
                    self.initiatorname = iname
        else:
            self.initiatorname = self.initiatornamebase
            self.initiatornames = {}
            self.initiatornames[self.initiatorname] = False
            self.initiatorcount = 0

        self.chap = None
        self.outgoingChap = None
        chap_init = xenrt.TEC().lookup(["ISCSI_LUNS",
                                        name,
                                        "CHAP",
                                        "INITIATOR_NAME"],
                                       None)
        chap_user = xenrt.TEC().lookup(["ISCSI_LUNS",
                                        name,
                                        "CHAP",
                                        "USERNAME"],
                                       None)
        chap_secret = xenrt.TEC().lookup(["ISCSI_LUNS",
                                          name,
                                          "CHAP",
                                          "SECRET"],
                                         None)
        if chap_user and chap_secret:
            if not chap_init:
                chap_init = self.initiatorname
            self.chap = (chap_init, chap_user, chap_secret)

        self.sharedDB = None
        self.secAddrs = {}

    def release(self, atExit=False):
        if xenrt.util.keepSetup() and atExit:
            xenrt.TEC().logverbose("Not disconnecting from iSCSI %s:%s" %
                                   (self.getServer(),
                                    self.getTargetName()))
            return
        xenrt.TEC().logverbose("Looking at hosts")
        for host in xenrt.TEC().registry.hostList():
            h = xenrt.TEC().registry.hostGet(host)
            xenrt.TEC().logverbose("Looking at %s" % (h.getName()))
            for sr in h.srs.values():
                xenrt.TEC().logverbose("Looking at SR %s" % (sr.name))
                if sr.lun == self:
                    xenrt.TEC().logverbose("Lun matched, trying to remove")
                    try:
                        sr.remove()
                        xenrt.TEC().logverbose("Remove successful")
                    except Exception, e:
                        traceback.print_exc(file=sys.stderr)
        
        if self.server:
            self.server = None
            self.targetname = None
            self.initiatorname = None

        if self.sharedDB:
            # This is a host that is using this LUN for a shared DB
            # Stop xapi and unmount...
            try:
                self.sharedDB.execdom0("/etc/init.d/xapi stop")
                self.sharedDB.execdom0("umount -f /var/xapi/shared_db")
            except Exception, e:
                traceback.print_exc(file=sys.stderr)

        if atExit:
            for host in xenrt.TEC().registry.hostList():
                if host == "SHARED":
                    continue
                h = xenrt.TEC().registry.hostGet(host)
                h.machine.exitPowerOff()
        CentralResource.release(self, atExit)

    def getInitiatorName(self, allocate=False):
        if not allocate or self.initiatorcount == 0:
            return self.initiatorname
        for iqn in self.initiatornames.keys():
            if not self.initiatornames[iqn]:
                self.initiatornames[iqn] = True
                return iqn
        raise xenrt.XRTError("No unused IQNs left")
    
    def getTargetName(self):
        return self.targetname

    def getSecondaryAddresses(self, network):
        if self.secAddrs.has_key(network):
            return self.secAddrs[network]
        else:
            return [self.server]

    def setNetwork(self, network):
        if not self.secAddrs.has_key("NPRI"):
            self.secAddrs["NPRI"] = [self.server]

        self.server = self.getSecondaryAddresses(network)[0]

    def getServer(self):
        return self.server

    def getID(self, lunid=0):
        return self.scsiid

    def setID(self, scsiid):
        self.scsiid = scsiid

    def setCHAP(self, user, secret):
        self.chap = (None, user, secret)
        
    def setOutgoingCHAP(self, user, secret):
        self.outgoingChap = (None, user, secret)
        
    def getOutgoingCHAP(self):
        if not self.outgoingChap:
            return None
        chap_init, chap_user, chap_secret = self.outgoingChap
        return (chap_user, chap_secret)

    def getCHAP(self):
        if not self.chap:
            return None
        chap_init, chap_user, chap_secret = self.chap
        return (chap_user, chap_secret)

    def getLunID(self):
        return self.lunid

class ISCSINativeLinuxLun(ISCSILun):
    def __init__(self, host, sizeMB=None):
        self.host = host
        host.setupDataDisk()
        try:
            self.host.execcmd("test -e /etc/ietd.conf")
            
            # Find the Target IQN name from ietd.conf
            self.targetname = self.host.execcmd("grep 'Target' /etc/ietd.conf | awk '{print $2}'").strip()

        except:
            self.targetname = "iqn.2009-01.xenrt.test:iscsi%08x" % \
                     (random.randint(0, 0x7fffffff))
            self.host.installLinuxISCSITarget(iqn = self.targetname)
        try:
            self.lunid = int(self.host.execcmd("grep '  Lun' /etc/ietd.conf | wc -l").strip())
        except:
            self.lunid = 0

        scsiid = self.host.createISCSITargetLun(self.lunid, sizeMB, "/data/", thickProvision=False)

        strscsi = string.join(["%02x" % ord(x) for x in "%08x" % scsiid], "")

        self.scsiid = "14945540000000000%s0000000000000000" % strscsi
        self.server = self.host.getIP()
        self.initiatorname = "iqn.2009-01.xenrt.test:iscsi%08x" % \
                 (random.randint(0, 0x7fffffff))
        nics = self.host.listSecondaryNICs()
        nics.append(0)

        self.secAddrs = {}
        for n in nics:
            try:
                eth = self.host.getNIC(n)
                net = self.host.getNICNetworkName(n)
                addr = self.host.getNetworkInterfaceIPAddress(eth)
                if not self.secAddrs.has_key(net):
                    self.secAddrs[net] = []
                self.secAddrs[net].append(addr)
            except Exception, e:
                xenrt.TEC().warning(str(e))

        # For creating iSCSI SRs via Native Linux Lun
        self.outgoingChap = None
        self.chap = None
        self.initiatornamebase = None
        self.initiatorcount = None
        self.initiatorstart = None
        self.initiatornames = {}

    def acquire(self):
        pass
    
    def release(self, atExit=False):
        CentralResource.release(self, atExit)

class HBALun(CentralResource):
    def __init__(self,
                 hosts,
                 luntype=None,
                 minsize=10,
                 maxsize=10000):
        CentralResource.__init__(self)
        self.scsiid = None
        self.luntype = None
        xenrt.TEC().logverbose("About to attempt to lock HBA LUN - current central resource status:")
        self.logList()
        luns = hosts[0].lookup("FC", {})
        luns = dict([(x, luns[x]) for x in luns.keys() if x.startswith("LUN")])
        for l in luns.keys():
            accept = True
            if minsize and int(luns[l].get('SIZE', "0")) < minsize:
                accept = False
            elif maxsize and int(luns[l].get('SIZE', "0")) > maxsize:
                accept = False
            elif luntype and luns[l].get("TYPE") != luntype:
                accept = False
            else:
                for h in hosts[1:]:
                    hluns = h.lookup("FC")
                    if not luns[l]['SCSIID'] in [hluns[x]['SCSIID'] for x in hluns.keys() if x.startswith("LUN")]:
                        accept = False
                        break
            
            if not accept:
                del luns[l]
        
        if not luns:
            raise xenrt.XRTError("Could not find a suitable LUN")
        else:
            CentralResource.__init__(self, held=False)
            startlooking = xenrt.util.timenow()
            mylun = None
            while True:
                for l in luns.keys():
                    try:
                        self.acquire("HBA_LUN-%s" % (luns[l]['SCSIID']))
                        mylun = luns[l]
                        self.resourceHeld = True
                        break
                    except xenrt.XRTError:
                        continue
                if mylun:
                    break
                if xenrt.util.timenow() > (startlooking + 3600):
                    xenrt.TEC().logverbose("Could not lock HBA LUN, current central resource status:")
                    self.logList()
                    raise xenrt.XRTError("Timed out waiting for a LUN to be "
                                         "available")
                xenrt.sleep(60)
   
        self.scsiid = luns[l]['SCSIID']
        self.luntype = luns[l].get('TYPE')
        self.lunid = int(luns[l]['LUNID']) if luns[l].has_key('LUNID') else None
        self.mpclaim = luns[l].get("MPCLAIM")

    def getID(self):
        return self.scsiid

    def getType(self):
        return self.luntype

    def getLunID(self):
        return self.lunid

    def getMPClaim(self):
        return self.mpclaim

    def release(self, atExit=False):
        if xenrt.util.keepSetup() and atExit:
            xenrt.TEC().logverbose("Not releasing LUN %s" % self.scsiid)
            return
        
        self.scsiid = None
        self.luntype = None
        if atExit:
            for host in xenrt.TEC().registry.hostList():
                if host == "SHARED":
                    continue
                h = xenrt.TEC().registry.hostGet(host)
                h.machine.exitPowerOff()
        CentralResource.release(self, atExit)

class NativeLinuxNFSShare(CentralResource):
    """NFS share on a native (bare metal) linux host."""
    def __init__(self, hostName="RESOURCE_HOST_0", device='sda'):
        self.place = xenrt.GEC().registry.hostGet(hostName)

        if device != 'sda':
            self.place.execcmd("mkfs.ext3 -F /dev/%s" % (device)) # "-F" to suppress prompt for use of whole device

        self.subdir = self.createShare(device)
        self.address = self.place.getIP()

    def createShare(self, device='sda'):
        # TODO this assumes the native linux host is CentOS 6.5
        sharepath = "/var/nfs"
        self.place.execcmd("yum -y install nfs-utils nfs-utils-lib")
        self.place.execcmd("chkconfig --levels 235 nfs on")
        self.place.execcmd("/etc/init.d/nfs start")
        self.place.execcmd("mkdir -p %s" % (sharepath))
        self.place.execcmd("mount /dev/%s %s" % (device, sharepath))
        self.place.execcmd("chown 65534:65534 %s" % (sharepath))
        self.place.execcmd("chmod 755 %s" % (sharepath))
        self.place.execcmd("echo '%s	*(rw,sync,no_subtree_check)' >> /etc/exports" % (sharepath))
        self.place.execcmd("exportfs -a")
        return sharepath

    def getMount(self):
        if not self.subdir:
            raise xenrt.XRTError("No mount directory available")
        return "%s:%s" % (self.address, self.subdir)

    def acquire(self):
        pass
    
    def release(self, atExit=False):
        CentralResource.release(self, atExit)

class _WindowsSMBShare(CentralResource):
    """Base class for Windows-based SMB shares"""
    def createShare(self, driveLetter=None):
        driveLetter = driveLetter or 'c'
        sharesPath = "%s:\\shares" % (driveLetter)
        if not self.place.xmlrpcDirExists(sharesPath):
            self.place.xmlrpcCreateDir(sharesPath)
        shareName = xenrt.randomGuestName()
        self.place.xmlrpcCreateDir("%s\\%s" % (sharesPath, shareName))
        self.place.xmlrpcExec("net share %s=%s\\%s /grant:Everyone,FULL" % (shareName, sharesPath, shareName))
        self.place.xmlrpcExec("icacls %s\\%s /grant Users:(OI)(CI)F" % (sharesPath, shareName))
        self.shareName = shareName
        self.domain = None
        self.user = "Administrator"
        self.password = "xensource"


    def acquire(self):
        pass
    
    def release(self, atExit=False):
        CentralResource.release(self, atExit)

    def getUNCPath(self):
        return "\\\\%s\\%s" % (self.place.getIP(), self.shareName)

    def getEscapedUNCPath(self):
        return self.getUNCPath().replace("\\", "\\\\")

    def getLinuxUNCPath(self):
        return self.getUNCPath().replace("\\", "/")


class NativeWindowsSMBShare(_WindowsSMBShare):
    """SMB share on a native (bare metal) windows host"""
    def __init__(self, hostName="RESOURCE_HOST_0", driveLetter=None):
        self.place = xenrt.GEC().registry.hostGet(hostName)

        driveLetter = driveLetter or 'c'

        if driveLetter != 'c':
            # Destroy anything existing on any drive that doesn't contain C: and reinitialise
            for diskid in self.place.xmlrpcDiskpartListDisks():
                driveletters = self.place.xmlrpcDriveLettersOfDisk(diskid)
                xenrt.TEC().logverbose("Disk with id %s contains drive letters %s" % (diskid, driveletters))

                nextDriveLetter = driveLetter
                if not 'C' in driveletters:
                    # destroy anything that might already exist on the disk
                    self.place.xmlrpcDeinitializeDisk(diskid)

                    # initialize the disk with a single partition and give it a letter
                    self.place.xmlrpcInitializeDisk(diskid, driveLetter=nextDriveLetter)
                    nextDriveLetter = chr(ord(nextDriveLetter)+1)

            # Format the disk we want to use
            self.place.xmlrpcFormat(driveLetter, quick=True)

        self.createShare(driveLetter)

class VMSMBShare(_WindowsSMBShare):
    """ A tempory SMB share in a VM """
    
    def __init__(self,hostIndex=None,sizeMB=None, guestName="xenrt-smb", distro="ws12r2-x64"):
        if not hostIndex:
            self.host = xenrt.TEC().registry.hostGet("RESOURCE_HOST_0")
        else:
            self.host = xenrt.TEC().registry.hostGet("RESOURCE_HOST_%s" % hostIndex)
        if not sizeMB:
            sizeMB = 50*xenrt.KILO
        self.guestName = guestName

        # Check if we already have the VM on this host, if we don't, then create it, otherwise attach to the existing one.
        if not self.host.guests.has_key(self.guestName):
            self.place = self.host.createBasicGuest(distro=distro, name=guestName, disksize = 20*xenrt.KILO + sizeMB)
        else:
            self.place = self.host.guests[self.guestName]
        self.createShare()
        
class SpecifiedSMBShare(object):
    """SMB share created elsewhere, suitable for passing to SMBStorageRepository"""
    def __init__(self,
                 addr,
                 shareName,
                 user,
                 password,
                 domain=None):
        self.addr = addr
        self.shareName = shareName
        self.domain = domain
        self.user = user
        self.password = password

    def getUNCPath(self):
        return "\\\\%s\\%s" % (self.addr, self.shareName)

    def getEscapedUNCPath(self):
        return self.getUNCPath().replace("\\", "\\\\")

    def getLinuxUNCPath(self):
        return self.getUNCPath().replace("\\", "/")

class ISCSIVMLun(ISCSILun):
    """ A tempory LUN in a VM """
    
    def __init__(self,hostIndex=None,sizeMB=None, totalSizeMB=None, guestName="xenrt-iscsi-target", bridges=None, targetType=None, host=None, sruuid=None):
        if host:
            self.host=host
        else:
            if not hostIndex:
                self.host = xenrt.TEC().registry.hostGet("RESOURCE_HOST_0")
            else:
                self.host = xenrt.TEC().registry.hostGet("RESOURCE_HOST_%s" % hostIndex)
        if not sizeMB:
            sizeMB = 50*xenrt.KILO
        self.guestName = guestName

        # Check if we already have the VM on this host, if we don't, then create it, otherwise attach to the existing one.
        if not self.host.guests.has_key(self.guestName):
            self._createISCSIVM(sizeMB, totalSizeMB, bridges=bridges, targetType=targetType, sruuid=sruuid)
        else:
            self.guest = self.host.guests[self.guestName]
            self._existingISCSIVM(sizeMB)
            

        self.outgoingChap = None
        self.chap = None
        self.initiatornamebase = None
        self.initiatorcount = None
        self.initiatorstart = None
        self.initiatornames = {}
        self.server = self.guest.mainip
        self.secAddrs = {}
        # Add a LUN to this VM
        self.scsiid = self.guest.createISCSITargetLun(self.lunid, int(sizeMB), dir="/iscsi/", thickProvision=False)

    def _existingISCSIVM(self, sizeMB):
        # Check whether we gave this VM space for all the LUNs upfront. If we didn't, we need to shut it down and resize the VDI
        iscsitype = self.guest.execguest("cat /root/iscsi_target_type").strip()
        if (self.guest.execguest("cat /etc/xenrtfullyprovisioned").strip() != "yes"):
            device = self.guest.execguest("cat /etc/xenrtiscsidev").strip()
            vdi = self.host.minimalList("vbd-list", "vdi-uuid", "device=%s" % device)[0]
            self.guest.shutdown()
            curSize = int(self.host.genParamGet("vdi", vdi, "virtual-size"))
            newSize = curSize + sizeMB * xenrt.MEGA
            self.host.getCLIInstance().execute("vdi-resize", "uuid=%s disk-size=%d" % (vdi, newSize)) # Resize the VDI to current + sizeMB
            self.guest.start()
            # Stop the daemon if it's running
            if iscsitype == "IET":
                try:
                    self.guest.execguest("/etc/init.d/iscsi-target stop")
                except:
                    pass
                try:
                    self.guest.execguest("killall ietd")
                except:
                    pass

                self.guest.execguest("umount /iscsi") # Now we can unmount the /iscsi volume and resize the filesystem
                self.guest.execguest("e2fsck -pf /dev/%s" % device)
                self.guest.execguest("resize2fs /dev/%s" % device)
                self.guest.execguest("mount /iscsi") # and now mount and start it again.
                if iscsitype == "IET":
                    self.guest.execguest("/etc/init.d/iscsi-target start")
            elif iscsitype == "LIO":
                # Using a modern kernel so online resize possible
                self.guest.execguest("resize2fs /dev/%s" % device)
        if iscsitype == "IET":
            self.targetname = self.guest.execguest("head -1 /etc/ietd.conf  | awk '{print $2}'").strip() # Find the Target IQN name from ietd.conf
            self.lunid = int(self.guest.execguest("tail -1 /etc/ietd.conf | awk '{print $2}'").strip()) + 1 # Find the next available LUN ID
        elif iscsitype == "LIO":
            self.targetname = self.guest.execguest("cat /root/iscsi_iqn").strip()
            self.lunid = int(self.guest.execguest("cat /root/iscsi_lun").strip()) + 1

    def _createISCSIVM(self, sizeMB, totalSizeMB, bridges=None, targetType=None, sruuid=None):
        if not bridges:
            networks = self.host.minimalList("pif-list", "network-uuid", "management=true host-uuid=%s" % self.host.getMyHostUUID()) # Find the management interface on this host
            networks.extend(self.host.minimalList("pif-list", "network-uuid", "IP-configuration-mode=DHCP host-uuid=%s management=false" % self.host.getMyHostUUID())) # And all of the non-management DHCP addresses
            networks.extend(self.host.minimalList("pif-list", "network-uuid", "IP-configuration-mode=static host-uuid=%s management=false" % self.host.getMyHostUUID())) # And all of the non-management static addresses
            bridges = [] # For XenRT we actually need the bridges, not the network UUIDs
            for n in networks:
                bridges.append(self.host.genParamGet("network", n, "bridge"))
        
        self.guest = self.host.createGenericLinuxGuest(name=self.guestName, bridge=bridges[0]) # Create the VM, putting the main VIF on the management network
        i = 1
        for b in bridges[1:]:
            self.guest.createVIF(eth = "eth%d" % i, bridge=b, plug=True) # Now create the VIFs on the other networks that the host has IPs on
            self.guest.execguest("echo 'auto eth%d' >> /etc/network/interfaces" % i)
            self.guest.execguest("echo 'iface eth%d inet dhcp' >> /etc/network/interfaces" % i)
            self.guest.execguest("ifup eth%d" % i) # And bring the link up
            i += 1
        
        self.targetname = "iqn.2009-01.xenrt.test:iscsi%08x" % \
                 (random.randint(0, 0x7fffffff))
        self.guest.installLinuxISCSITarget(iqn = self.targetname, targetType=targetType) # Install the linux ISCSI target
        self.lunid = 0
        if totalSizeMB: # We can tell this class how much space this will need in total, in which case we won't need to resize the VDI later. Store that in /etc/xenrtfullyprovisioned
            self.guest.execguest("echo yes > /etc/xenrtfullyprovisioned")
        else:
            self.guest.execguest("echo no > /etc/xenrtfullyprovisioned")
            totalSizeMB=sizeMB
        
        # Create a disk, 1GB larger than specified for FS overhead, then format and mount it.
        device = self.guest.createDisk(sizebytes=(int(totalSizeMB)*xenrt.MEGA + xenrt.GIGA), returnDevice=True, sruuid=sruuid)
        self.guest.execguest("echo %s > /etc/xenrtiscsidev" % device)
        self.guest.execguest("mkfs.ext3 /dev/%s" % device)
        self.guest.execguest("mkdir /iscsi")
        self.guest.execguest("echo /dev/%s /iscsi ext3 defaults 0 0 >> /etc/fstab" % device)
        self.guest.execguest("mount /iscsi")

    def acquire(self):
        pass
    
    def release(self, atExit=False):
        CentralResource.release(self, atExit)

class ISCSITemporaryLun(ISCSILun):
    """A temporary LUN on the XenRT controller."""

    def __init__(self, sizemb):
        CentralResource.__init__(self)
        self.file = None
        self.iettid = None
        self.lunid = 0
        
        # Create a backing file on the controller for the LUN
        basedir = xenrt.TEC().lookup("ISCSI_BASE_PATH")
        if not os.path.exists(basedir):
            os.makedirs(basedir)
        f, self.file = tempfile.mkstemp(".lun", "%s-iSCSI" % (xenrt.TEC().lookup("JOBID", "nojob")), basedir)
        os.close(f)
        os.chmod(self.file,
                 stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)
        xenrt.util.command("dd if=/dev/zero of=%s bs=1M seek=%u count=1" %
                           (self.file, sizemb-1), timeout=600)

        # Create a new target name
        ietlock = xenrt.resources.CentralResource()
        attempts = 0
        while True:
            try:
                ietlock.acquire("IETCONFIG")
                break
            except:
                xenrt.sleep(10)
                attempts += 1
                if attempts > 6:
                    raise xenrt.XRTError("Couldn't get IET config lock.")
        try:
            f = file("/proc/net/iet/volume")
            data = f.read()
            f.close()
            tids = map(int, re.findall(r"tid:(\d+)", data))
            tid = 1
            while True:
                if not tid in tids:
                    break
                tid = tid + 1
            target = "iqn.2009-01.xenrt.test:iscsi%08x" % \
                     (random.randint(0, 0x7fffffff))
            xenrt.rootops.sudo("/usr/sbin/ietadm --op new --tid %u "
                               "--params Name=%s" % (tid, target))
        finally:
            ietlock.release()

        # Create a LUN
        xenrt.rootops.sudo("/usr/sbin/ietadm --op new --tid %u --lun %u "
                           "--params Path=%s,Type=fileio,ScsiId=%08x" %
                           (tid, self.lunid, self.file, random.randint(0, 0x7fffffff)))
        self.targetname = target
        self.iettid = tid
        self.server = xenrt.TEC().lookup("XENRT_SERVER_ADDRESS")
        self.scsiid = None
        self.outgoingChap = None
        self.chap = None
        self.initiatornamebase = None
        self.initiatorcount = None
        self.initiatorstart = None
        self.initiatornames = {}
        self.secAddrs = {}
        nsecaddr = xenrt.TEC().lookup(["NETWORK_CONFIG", "SECONDARY", "ADDRESS"], None)
        if nsecaddr:
            self.secAddrs['NSEC'] = [nsecaddr]
        vlans = xenrt.TEC().lookup(["NETWORK_CONFIG", "VLANS"], {}).keys()
        for v in vlans:
            vlanaddr = xenrt.TEC().lookup(["NETWORK_CONFIG", "VLANS", v, "ADDRESS"], None)
            if vlanaddr:
                self.secAddrs[v] = [vlanaddr]
        
    def acquire(self):
        pass

    def release(self, atExit=False):
        # Remove the LUN from IET
        if self.iettid:
            try:
                xenrt.rootops.sudo("/usr/sbin/ietadm --op delete --tid %u --lun %u"
                                   % (self.iettid, self.lunid))
            except:
                pass
            xenrt.sleep(5)

        # Remove the target from IET
        if self.iettid:
            xenrt.rootops.sudo("/usr/sbin/ietadm --op delete --tid %s" %
                               (self.iettid))
            xenrt.sleep(5)

        # Remove the file backing the LUN
        if self.file:
            os.unlink(self.file)

        CentralResource.release(self, atExit)
        
class ISCSILunSpecified(ISCSILun):
    """An iSCSI LUN we have explicitly provided to this test."""
    def __init__(self, confstring):
        """Create an ISCSILunSpecified object.

        @param confstring: a slash-separated string of:
            initiatorname/targetname/targetaddress
        """
        l = string.split(confstring, "/")
        if len(l) < 3 or len(l) > 4:
            raise xenrt.XRTError("Invalid LUN config string '%s'" %
                                 (confstring))
        self.initiatornamebase = l[0]
        self.targetname = l[1]
        self.server = l[2]
        self.initiatorcount = int(xenrt.TEC().lookup("IQN_COUNT", "16"))
        self.initiatorstart = int(xenrt.TEC().lookup("IQN_START", "0"))
        self.scsiid = None
        self.chap = None
        self.outgoingChap = None
        if len(l) == 4:
            self.lunid = int(l[3])
        else:
            self.lunid = 0

        r = re.search(r"(%\d*u)", self.initiatornamebase)
        if r:
            pattern = r.group(1)
            self.initiatornames = {}
            for i in range(self.initiatorstart,
                           self.initiatorstart + self.initiatorcount):
                iname = string.replace(self.initiatornamebase,
                                       pattern,
                                       pattern % (i))
                self.initiatornames[iname] = False
                if i == 0:
                    self.initiatorname = iname
        else:
            self.initiatorname = self.initiatornamebase
            self.initiatornames = {}
            self.initiatornames[self.initiatorname] = False
            self.initiatorcount = 0
        self.secAddrs = {}
        
    def acquire(self):
        pass

    def release(self, atExit=False):
        pass

class FCHBATarget(ManagedStorageResource):
    """A FC-HBA Target and Fabric Information for CSLG Server
       Example site Config Entry::
    <FC_PROVIDER>
            <FAS270>
                <DEVICE-ID>NETAPP</DEVICE-ID>
                <TARGET>fas270.eng.hq.xensource.com</TARGET>
                <USERNAME>root</USERNAME>
                <PASSWORD>mypasswd</PASSWORD>
                <AGGR>aggr1</AGGR>
                <SIZE>20</SIZE>
                <SWITCH_NAME>SilkWorm 200e</SWITCH_NAME>
                <IPADDRESS>10.219.0.210</IPADDRESS>
                <FC-USERID>root</FC-USERID>
                <FC-PASSWORD>xensource01T</FC-PASSWORD>
                <FRIENDLYNAME>fas3020</FRIENDLYNAME>
            </FAS270>
    </FC_PROVIDER>
    """

    def __init__(self, specify=None):
        if not specify:
            serverdict = xenrt.TEC().lookup("FC_PROVIDER", None)
            if not serverdict:
                raise xenrt.XRTError("No FC_PROVIDER defined")
            servers = serverdict.keys()
            names = []
            for s in servers:
                names.append(s)
            # Find one of the targets that is available
            name = random.choice(names)
        else:
            name = specify
        CentralResource.__init__(self, held=False)
        self.name = name
        # Get details of this resource from the config
        self.DeviceID = xenrt.TEC().lookup(["FC_PROVIDER",
                                            name,
                                            "DEVICE-ID"],
                                           None)
        self.target = xenrt.TEC().lookup(["FC_PROVIDER",
                                          name,
                                          "TARGET"],
                                         None)
        self.username = xenrt.TEC().lookup(["FC_PROVIDER",
                                            name,
                                            "USERNAME"],
                                           None)
        self.password = xenrt.TEC().lookup(["FC_PROVIDER",
                                            name,
                                            "PASSWORD"],
                                           None)
        self.aggr = xenrt.TEC().lookup(["FC_PROVIDER",
                                        name,
                                        "AGGR"],
                                       None)
        self.size = xenrt.TEC().lookup(["FC_PROVIDER",
                                        name,
                                        "SIZE"],
                                       None)
        self.switchName = xenrt.TEC().lookup(["FC_PROVIDER",
                                             name,
                                             "SWITCH_NAME"],
                                            None)
        self.switchIP = xenrt.TEC().lookup(["FC_PROVIDER",
                                            name,
                                            "IPADDRESS"],
                                           None)
        self.switchUserID = xenrt.TEC().lookup(["FC_PROVIDER",
                                                name,
                                                "FC-USERID"],
                                               None)
        self.switchPassword = xenrt.TEC().lookup(["FC_PROVIDER",
                                                  name,
                                                  "FC-PASSWORD"],
                                                  None)
        self.FCDeviceID = xenrt.TEC().lookup(["FC_PROVIDER",
                                               name,
                                               "FC-DEVICE-ID"],
                                                None)
        self.friendlyname = xenrt.TEC().lookup(["FC_PROVIDER",
                                               name,
                                               "FRIENDLYNAME"],
                                                None)




    def release(self, atExit=False):
        if not xenrt.util.keepSetup():
            for host in xenrt.TEC().registry.hostList():
                for sr in xenrt.TEC().registry.hostGet(host).srs.values():
                    if sr.resources.has_key("target") and \
                           sr.resources["target"] == self:
                        try:
                            sr.remove()
                        except Exception, e:
                            traceback.print_exc(file=sys.stderr)
            if self.target:
                self.target = None
                self.username = None
                self.password = None
                self.aggr = None
        CentralResource.release(self, atExit)

    def getSwitchName(self):
        return self.switchName

    def getSwitchIP(self):
        return self.switchIP

    def getSwitchUserID(self):
        return self.switchUserID

    def getSwitchPassword(self):
        return self.switchPassword

    def getName(self):
        return self.name

    def getTarget(self):
        return self.target

    def getUsername(self):
        return self.username

    def getPassword(self):
        return self.password

    def getAggr(self):
        return self.aggr

    def getSize(self):
        return self.size

    def getDeviceID(self):
        return self.DeviceID

    def getType(self):
        return self.DeviceID

    def getFCType(self):
        return self.FCDeviceID

    def getDisplayName(self):
        return self.aggr

    def getFriendlyName(self):
        return self.friendlyname

    def getProtocolList(self):
        """Return a list of CVSM transport protocols supported by this target.
        """
        return ["fc"]
    
class SMISiSCSITarget(ManagedStorageResource):
    """A SMIS-iSCSI Target for CSLG Server
       Example site Config Entry::
      <SMIS_ISCSI_TARGETS>
          <emccx4>
              <TARGET>10.220.64.51:5988</TARGET>
              <USERNAME>admin</USERNAME>
              <PASSWORD>xxxxxxxx</PASSWORD>
              <STORAGESYSTEM>EMCSANCX4</STORAGESYSTEM>
              <STORAGEPOOL>0000</STORAGEPOOL>
              <SIZE>500</SIZE>
          </emccx4>
      </SMIS_ISCSI_TARGETS>
                                                    """

    def __init__(self):
        """minsize is in GB"""
        xenrt.TEC().logverbose("About to attempt to lock SMI-S iSCSI Target - current central resource status:")
        self.logList()
        serverdict = xenrt.TEC().lookup("SMIS_ISCSI_TARGETS", None)
        if not serverdict:
            raise xenrt.XRTError("No SMIS_ISCSI_TARGETS defined")
        servers = serverdict.keys()
        names = []
        for s in servers:
            names.append(s)
        CentralResource.__init__(self, held=False)
        # Find one of the targets that is available
        name = random.choice(names)
        self.name = name
        # Get details of this resource from the config
        self.target = xenrt.TEC().lookup(["SMIS_ISCSI_TARGETS",
                                          name,
                                          "TARGET"],
                                         None)
        self.username = xenrt.TEC().lookup(["SMIS_ISCSI_TARGETS",
                                            name,
                                            "USERNAME"],
                                           None)
        self.password = xenrt.TEC().lookup(["SMIS_ISCSI_TARGETS",
                                            name,
                                            "PASSWORD"],
                                           None)
        self.storagesystem = xenrt.TEC().lookup(["SMIS_ISCSI_TARGETS",
                                               name,
                                               "STORAGESYSTEM"],
                                                None)
        self.storagepool = xenrt.TEC().lookup(["SMIS_ISCSI_TARGETS",
                                        name,
                                        "STORAGEPOOL"],
                                       None)
        self.size = xenrt.TEC().lookup(["SMIS_ISCSI_TARGETS",
                                        name,
                                        "SIZE"],
                                       None)
        self.namespace = xenrt.TEC().lookup(["SMIS_ISCSI_TARGETS",
                                        name,
                                        "NAMESPACE"],
                                       None)




    def release(self, atExit=False):
        if not xenrt.util.keepSetup():
            for host in xenrt.TEC().registry.hostList():
                for sr in xenrt.TEC().registry.hostGet(host).srs.values():
                    if sr.resources.has_key("target") and \
                           sr.resources["target"] == self:
                        try:
                            sr.remove()
                        except Exception, e:
                            traceback.print_exc(file=sys.stderr)
            if self.target:
                self.target = None
                self.username = None
                self.password = None
                self.aggr = None
        CentralResource.release(self, atExit)

    def getName(self):
        return self.name

    def getTarget(self):
        return self.target

    def getUsername(self):
        return self.username

    def getPassword(self):
        return self.password

    def getDisplayName(self):
        return self.storagepool

    def getSize(self):
        return self.size

    def getType(self):
        return "EMC_CLARIION"

    def getFriendlyName(self):
        return self.storagesystem

    def getProtocolList(self):
        """Return a list of CVSM transport protocols supported by this target.
        """
        return ["iscsi"]
    
    def getNamespace(self):
        return self.namespace

class SMISFCTarget(ManagedStorageResource):
    """A SMIS-FC Target for CSLG Server
       Example site Config Entry::
      <SMIS_FC_TARGETS>
          <emccx4>
              <TARGET>10.220.64.51:5988</TARGET>
              <USERNAME>admin</USERNAME>
              <PASSWORD>xxxxxxxx</PASSWORD>
              <STORAGESYSTEM>EMCSANCX4</STORAGESYSTEM>
              <STORAGEPOOL>0000</STORAGEPOOL>
              <SIZE>500</SIZE>
          </emccx4>
      </SMIS_FC_TARGETS>
                                                    """

    def __init__(self):
        """minsize is in GB"""
        xenrt.TEC().logverbose("About to attempt to lock SMI-S FC Target - current central resource status:")
        self.logList()
        serverdict = xenrt.TEC().lookup("SMIS_FC_TARGETS", None)
        if not serverdict:
            raise xenrt.XRTError("No SMIS_FC_TARGETS defined")
        servers = serverdict.keys()
        names = []
        for s in servers:
            names.append(s)
        CentralResource.__init__(self, held=False)
        name = random.choice(names)
        self.name = name
        # Get details of this resource from the config
        self.target = xenrt.TEC().lookup(["SMIS_FC_TARGETS",
                                          name,
                                          "TARGET"],
                                         None)
        self.username = xenrt.TEC().lookup(["SMIS_FC_TARGETS",
                                            name,
                                            "USERNAME"],
                                           None)
        self.password = xenrt.TEC().lookup(["SMIS_FC_TARGETS",
                                            name,
                                            "PASSWORD"],
                                           None)
        self.storagesystem = xenrt.TEC().lookup(["SMIS_FC_TARGETS",
                                               name,
                                               "STORAGESYSTEM"],
                                                None)
        self.storagepool = xenrt.TEC().lookup(["SMIS_FC_TARGETS",
                                        name,
                                        "STORAGEPOOL"],
                                       None)
        self.size = xenrt.TEC().lookup(["SMIS_FC_TARGETS",
                                        name,
                                        "SIZE"],
                                       None)
        self.namespace = xenrt.TEC().lookup(["SMIS_FC_TARGETS",
                                        name,
                                        "NAMESPACE"],
                                       None)




    def release(self, atExit=False):
        if not xenrt.util.keepSetup():
            for host in xenrt.TEC().registry.hostList():
                for sr in xenrt.TEC().registry.hostGet(host).srs.values():
                    if sr.resources.has_key("target") and \
                           sr.resources["target"] == self:
                        try:
                            sr.remove()
                        except Exception, e:
                            traceback.print_exc(file=sys.stderr)
            if self.target:
                self.target = None
                self.username = None
                self.password = None
                self.aggr = None
        CentralResource.release(self, atExit)

    def getName(self):
        return self.name

    def getTarget(self):
        return self.target

    def getUsername(self):
        return self.username

    def getPassword(self):
        return self.password

    def getDisplayName(self):
        return self.storagepool

    def getSize(self):
        return self.size

    def getType(self):
        return "EMC_CLARIION"

    def getFriendlyName(self):
        return self.storagesystem

    def getNamespace(self):
        return self.namespace

    def getProtocolList(self):
        """Return a list of CVSM transport protocols supported by this target.
        """
        return ["fc"]

class NetAppTarget(ManagedStorageResource):
    """A NetApp target from a central shared pool.

      Example site config entry::
    
        <NETAPP_FILERS>
          <fas270>
            <TARGET>fas270.eng.hq.xensource.com</TARGET>
            <USERNAME>root</USERNAME>
            <PASSWORD>mypasswd</PASSWORD>
            <AGGR>aggr1</AGGR>
            <SIZE>50</SIZE>
            <FRIENDLYNAME>fas3020</FRIENDLYNAME>
          </fas270>
        </NETAPP_FILERS>
    """

    def __init__(self, minsize=100, maxsize=1000000, specify=None):
        """minsize is in GB"""
        if not specify:
            # Find a suitable target
            serverdict = xenrt.TEC().lookup("NETAPP_FILERS", None)
            if not serverdict:
                raise xenrt.XRTError("No NETAPP_FILERS defined")
            servers = serverdict.keys()
            if len(servers) == 0:
                raise xenrt.XRTError("No NETAPP_FILERS defined")
            names = []
            for s in servers:
                xsize = int(xenrt.TEC().lookup(["NETAPP_FILERS", s, "SIZE"], 0))
                if xsize < minsize:
                    continue
                if xsize > maxsize:
                    continue
                names.append(s)
            if len(names) == 0:
                raise xenrt.XRTError("Could not find a suitable target "
                                     "(size>%uG)" % (minsize))
            # Find one of the targets that is available
            name = random.choice(names)
        else:
            name = specify
        CentralResource.__init__(self, held=False)
        
        self.name = name
        # Get details of this resource from the config
        self.target = xenrt.TEC().lookup(["NETAPP_FILERS",
                                          name,
                                          "TARGET"],
                                         None)
        self.username = xenrt.TEC().lookup(["NETAPP_FILERS",
                                            name,
                                            "USERNAME"],
                                           None)
        self.password = xenrt.TEC().lookup(["NETAPP_FILERS",
                                            name,
                                            "PASSWORD"],
                                           None)
        self.aggr = xenrt.TEC().lookup(["NETAPP_FILERS",
                                        name,
                                        "AGGR"],
                                       None)
        self.size = xenrt.TEC().lookup(["NETAPP_FILERS",
                                        name,
                                        "SIZE"],
                                       None)
        self.friendlyname = xenrt.TEC().lookup(["NETAPP_FILERS",
                                               name,
                                               "FRIENDLYNAME"],
                                                None)

    def release(self, atExit=False):
        if not xenrt.util.keepSetup():
            for host in xenrt.TEC().registry.hostList():
                for sr in xenrt.TEC().registry.hostGet(host).srs.values():
                    if sr.resources.has_key("target") and \
                           sr.resources["target"] == self:
                        try:
                            sr.remove()
                        except Exception, e:
                            traceback.print_exc(file=sys.stderr)
            if self.target:
                self.target = None
                self.username = None
                self.password = None
                self.aggr = None
        CentralResource.release(self, atExit)

    def getName(self):
        return self.name

    def getTarget(self):
        return self.target
    
    def getUsername(self):
        return self.username

    def getPassword(self):
        return self.password

    def getAggr(self):
        return self.aggr

    def getSize(self):
        return self.size

    def getType(self):
        """Return the 'storage adapter ID' for use with CVSM."""
        return "NETAPP"

    def getDisplayName(self):
        return self.aggr

    def getFriendlyName(self):
        return self.friendlyname

    def getProtocolList(self):
        """Return a list of CVSM transport protocols supported by this target.
        """
        return ["iscsi"]

class NetAppTargetSpecified(NetAppTarget):
    """A NetApp target we have explicitly provided to this test."""
    def __init__(self, confstring):
        """Create an NetAppTargetSpecified object.

        @param confstring: a slash-separated string of:
            targetaddress/aggregate/username/password/sizeGB
        """
        l = string.split(confstring, "/")
        if len(l) != 5:
            raise xenrt.XRTError("Invalid NetApp config string '%s'" %
                                 (confstring))
        self.target = l[0]
        self.aggr = l[1]
        self.username = l[2]
        self.password = l[3]
        self.size = l[4]

    def acquire(self):
        pass

    def release(self, atExit=False):
        pass

class EQLTarget(ManagedStorageResource):
    """An EqualLogic target from a central shared pool.

      Example site config entry::
    
        <EQUALLOGIC>
          <ps5000e>
            <TARGET>10.220.32.42</TARGET>
            <USERNAME>root</USERNAME>
            <PASSWORD>mypasswd</PASSWORD>
            <STORAGEPOOL>default</STORAGEPOOL>
            <SIZE>50</SIZE>
            <FRIENDLYNAME>fas3020</FRIENDLYNAME>
          </ps5000e>
        </EQUALLOGIC>
    """
    def __init__(self,
                 minsize=100,
                 maxsize=1000000,
                 specificNamedResource=None,
                 timeout=3600):
        """minsize is in GB"""
        # specificNamedResource is only to be used for internal maintenance
        # operations
        xenrt.TEC().logverbose("About to attempt to lock EQL Target - current central resource status:")
        self.logList()
        if not specificNamedResource:
            # Find a suitable target
            serverdict = xenrt.TEC().lookup("EQUALLOGIC", None)
            if not serverdict:
                raise xenrt.XRTError("No EQUALLOGIC arrays defined")
            servers = serverdict.keys()
            if len(servers) == 0:
                raise xenrt.XRTError("No EQUALLOGIC arrays defined")
            names = []
            for s in servers:
                xsize = int(xenrt.TEC().lookup(["EQUALLOGIC", s, "SIZE"], 0))
                if xsize < minsize:
                    continue
                if xsize > maxsize:
                    continue
                names.append(s)
            if len(names) == 0:
                raise xenrt.XRTError("Could not find a suitable target "
                                     "(size>%uG)" % (minsize))
        else:
            names = [specificNamedResource]
        CentralResource.__init__(self, held=False)
        # Find one of the targets that is available
        name = random.choice(names)
        self.name = name
        # Get details of this resource from the config
        self.target = xenrt.TEC().lookup(["EQUALLOGIC",
                                          name,
                                          "TARGET"],
                                         None)
        self.username = xenrt.TEC().lookup(["EQUALLOGIC",
                                            name,
                                            "USERNAME"],
                                           None)
        self.password = xenrt.TEC().lookup(["EQUALLOGIC",
                                            name,
                                            "PASSWORD"],
                                           None)
        self.aggr = xenrt.TEC().lookup(["EQUALLOGIC",
                                        name,
                                        "STORAGEPOOL"],
                                       None)
        self.size = xenrt.TEC().lookup(["EQUALLOGIC",
                                        name,
                                        "SIZE"],
                                       None)
        self.friendlyname = xenrt.TEC().lookup(["EQUALLOGIC",
                                               name,
                                               "FRIENDLYNAME"],
                                                None)

    def release(self, atExit=False):
        if not xenrt.util.keepSetup():
            for host in xenrt.TEC().registry.hostList():
                for sr in xenrt.TEC().registry.hostGet(host).srs.values():
                    if sr.resources.has_key("target") and \
                           sr.resources["target"] == self:
                        try:
                            sr.remove()
                        except Exception, e:
                            traceback.print_exc(file=sys.stderr)
            if self.target:
                self.target = None
                self.username = None
                self.password = None
                self.aggr = None
        CentralResource.release(self, atExit)

    def runSSHCommands(self, cmdlist):
        xenrt.TEC().logverbose("Executing command(s) on Equallogic target %s: "
                               "%s" % (self.name, str(cmdlist)))
        p = xenrt.GenericGuest(self.name)
        p.mainip = self.target
        c = None
        data = ""
        ssh = p.sshSession(username=self.username, password=self.password)
        try:
            c = ssh.open_session()
            c.settimeout(60)
            c.setblocking(0)
            c.invoke_shell()
            c.sendall("cli-settings events off\r\n")
            c.sendall("grpparams info-messages disable\r\n")
            c.sendall("cli-settings paging off\r\n")
            c.sendall("cli-settings formatoutput off\r\n")
            c.sendall("cli-settings confirmation off\r\n")
            c.sendall("stty hardwrap off\r\n")
            for cmd in cmdlist:
                c.sendall("%s\r\n" % (cmd))
            # Wait for start of returned output
            n = 0            
            while not c.recv_ready():
                xenrt.sleep(1)
                n = n + 1
                if n >= 30:
                    raise xenrt.TEC().logverbose("SSH read timeout")
            # Loop reading output until no more. This is a bit gross. Ideally
            # we would read until we get a prompt string.
            while True:
                if not c.recv_ready():
                    xenrt.sleep(1)
                    if not c.recv_ready():
                        break
                data = data + c.recv(1024)
            xenrt.TEC().logverbose("Read from SSH: %s" % (data))
            c.sendall("logout\r\n")
        finally:
            if c:
                c.close()
            ssh.close()
        return data

    def getTarget(self):
        return self.target
    
    def getUsername(self):
        return self.username

    def getPassword(self):
        return self.password

    def getAggr(self):
        return self.aggr

    def getSize(self):
        return self.size

    def getName(self):
        return self.name

    def getType(self):
        """Return the 'storage adapter ID' for use with CVSM."""
        return "DELL_EQUALLOGIC"

    def getDisplayName(self):
        return self.aggr

    def getFriendlyName(self):
        return self.friendlyname

    def getProtocolList(self):
        """Return a list of CVSM transport protocols supported by this target.
        """
        return ["iscsi"]


def eqlTargetCleanAll():
    """Attempt to remove all test LUNs from all Equallogic targets. This
    is fairly dangerous and should generally only be done when no jobs are
    running or using the Equallogic resources. ***This will remove all
    XenServer SRs on the arrays known about.*** Manually created LUNs such
    as those used for LUN-per-SR tests are not affected."""

    # We enumerate all declared Equallogic resources and group by the
    # target.
    resources = {}    
    serverdict = xenrt.TEC().lookup("EQUALLOGIC", None)
    if not serverdict:
        xenrt.TEC().logverbose("No EQUALLOGIC arrays defined")
        return
    servers = serverdict.keys()
    for s in servers:
        target = xenrt.TEC().lookup(["EQUALLOGIC", s, "TARGET"])
        if not resources.has_key(target):
            resources[target] = []
        resources[target].append(s)

    # For each target we try to acquire the locks on all resources
    # using the target. We have to do this because the cleanup process
    # cannot distinguish between LUNs owned by one resource or another
    for target in resources.keys():
        xenrt.TEC().progress("Processing target '%s' used by: %s" %
                             (target, string.join(resources[target])))

        try:
            # Try to acquire the locks
            robjects = []
            try:
                for r in resources[target]:
                    robject = EQLTarget(specificNamedResource=r, timeout=0)
                    robjects.append(robject)

                # Clean up the target        
                try:
                    # Get the list of volumes
                    vollist = robjects[0].runSSHCommands(["show volume"])
                    volumes = []
                    volume = ""
                    for line in vollist.splitlines():
                        if line.startswith("XenStorage"):
                            # New volume
                            if volume:
                                volumes.append(volume)
                            volume = line.split()[0]
                        else:
                            r = re.search("^  (\S+)", line)
                            if r and volume:
                                volume = volume + r.group(1)
                    if volume:
                        volumes.append(volume)
                    xenrt.TEC().logverbose("Volumes: %s" %
                                           (string.join(volumes)))

                    # Offlines and delete each volume, be pedantic about the
                    # volume name prefix being XenStorage
                    # Process in batches of 8 volumes to avoid stiffing
                    # the targets
                    commandgroups = []
                    for volume in volumes:
                        if not volume.startswith("XenStorage"):
                            continue
                        if len(commandgroups) == 0 or \
                               len(commandgroups[-1]) >= 32:
                            commandgroups.append([])
                        commandgroups[-1].append("volume select %s" % (volume))
                        commandgroups[-1].append("offline")
                        commandgroups[-1].append("exit")
                        commandgroups[-1].append("volume delete %s" % (volume))
                    
                    for commands in commandgroups:
                        vollist = robjects[0].runSSHCommands(commands)

                except Exception, e:
                    xenrt.TEC().warning("Exception cleaning target '%s': %s" %
                                        (target, str(e)))
                xenrt.sleep(10)

            finally:
                # Release the locks
                for robject in robjects:
                    robject.release()
        except Exception, e:
            xenrt.TEC().warning("%s (%s)" % (str(e), target))

class EQLTargetSpecified(EQLTarget):
    """An EqualLogic target we have explicitly provided to this test."""
    def __init__(self, confstring):
        """Create an EQLSpecified object.

        @param confstring: a slash-separated string of:
            targetaddress/storagepool/username/password/sizeGB
        """
        l = string.split(confstring, "/")
        if len(l) != 5:
            raise xenrt.XRTError("Invalid EqualLogic config string '%s'" %
                                 (confstring))
        self.target = l[0]
        self.aggr = l[1]
        self.username = l[2]
        self.password = l[3]
        self.size = l[4]

    def acquire(self):
        pass

    def release(self, atExit=False):
        pass

class NetworkTestPeer(CentralResource):
    """A peer for network tests that we have temporary exclusive access to."""
    def __init__(self, shared=False, blocking=True):
        CentralResource.__init__(self)
        xenrt.TEC().logverbose("About to attempt to lock Netperf test peer - current central resource status:")
        self.logList()
        # Find a suitable LUN
        serverdict = xenrt.TEC().lookup("TTCP_PEERS", None)
        if not serverdict:
            raise xenrt.XRTError("No TTCP_PEERS defined")
        servers = serverdict.keys()
        if len(servers) == 0:
            raise xenrt.XRTError("No TTCP_PEERS defined")
        names = []
        for s in servers:
            isshared = xenrt.TEC().lookup(["TTCP_PEERS", s, "SHARED"],
                                          False,
                                          boolean=True)
            if isshared != shared:
                continue
            names.append(s)
        if len(names) == 0:
            raise xenrt.XRTError("Could not find a suitable peer")
        CentralResource.__init__(self, held=False)
        name = None
        startlooking = xenrt.util.timenow()
        # Find one of the peers that is available
        while True:
            for n in names:
                try:
                    self.acquire("TTCP_PEER-%s" % (n), shared=shared)
                    name = n
                    if not shared:
                        self.resourceHeld = True
                    break
                except xenrt.XRTError:
                    continue
            if name:
                break
            if not blocking:
                raise xenrt.XRTError("No peer available now")
            if xenrt.util.timenow() > (startlooking + 3600):
                xenrt.TEC().logverbose("Could not lock Netperf peer, current central resource status:")
                self.logList()
                raise xenrt.XRTError("Timed out waiting for a peer to be "
                                     "available")
            xenrt.sleep(60)
            
        self.name = name
        # Get details of this resource from the config
        self.peerip = xenrt.TEC().lookup(["TTCP_PEERS",
                                          name,
                                          "ADDRESS"],
                                         None)
        # If this isn't root things will break.
        self.username = "root"
        self.password = None
        passwords = string.split(xenrt.TEC().lookup("ROOT_PASSWORDS", ""))
        for p in passwords:
            try:
                xenrt.ssh.SSH(self.peerip, "true", username="root",
                              password=p, level=xenrt.RC_FAIL, timeout=30)
                xenrt.TEC().logverbose("Setting my password to %s" % (p))
                self.password = p
                break
            except:
                pass
        if not self.password:
            raise xenrt.XRTError("Could not determine password for network peer")
        # Get details of any VLANs we have
        self.vlanips = {}
        self.vlannets = {}
        vlans = xenrt.TEC().lookup(["TTCP_PEERS",
                                    name,
                                    "VLANS"],
                                   None)
        if vlans:
            for vlan in vlans.split(","):
                (vid, net) = vlan.split(":",1)
                (ip, mask) = net.split("/",1)
                self.vlanips[vid] = ip
                self.vlannets[vid] = (ip, mask)

    def getAddress(self, vid=None, guest=None):
        if vid:
            vid = str(vid) # In case we get an int
            if self.vlanips.has_key(vid):
                return self.vlanips[vid]
            else:
                raise xenrt.XRTError("Peer %s does not have an IP on VLAN %s" %
                                     (self.name, vid))
        elif guest:
            # Figure out which IP to return based on which VLAN the guest is on
            # (CA-63585)
            # Get the guest IP address
            gip = guest.getIP()
            # See if it's in any of the VLANs we are on
            for vid in self.vlannets:
                pip = self.vlannets[vid][0]
                mask = self.vlannets[vid][1]
                if xenrt.util.ipsInSameSubnet(gip,pip,mask):
                    return pip
            # If we get here then we're not on the same vlan, so return default
            return self.peerip
            
        else:
            return self.peerip

    def startCommand(self, command, username=None, password=None):
        ip = self.getAddress()
        if not username:
            username = self.username
        if not password:
            password = self.password
        xenrt.TEC().logverbose("SSH %s@%s %s" % (username, ip, command))
        outfile = string.strip(xenrt.SSH(ip,
                                         "mktemp /tmp/XXXXXX",
                                         username=username,
                                         password=password,
                                         retval="string"))
        pid = xenrt.SSH(ip,
                        "%s > %s 2>&1 < /dev/null & echo $!" %
                        (command, outfile),
                        username=username,
                        password=password,
                        retval="string")
        return int(pid), outfile, username, password

    def runCommand(self, command, username=None, password=None):
        ip = self.getAddress()
        if not username:
            username = self.username
        if not password:
            password = self.password
        xenrt.TEC().logverbose("SSH %s@%s %s" % (username, ip, command))
        return xenrt.SSH(ip,
                         command,
                         username=username,
                         password=password,
                         retval="string")
 
    def readCommand(self, handle):
        pid, filename, username, password = handle
        ip = self.getAddress()
        return xenrt.SSH(ip,
                         "cat %s" % (filename),
                         username=username,
                         password=password,
                         retval="string")

_privateSubnetCounter = 1
class PrivateSubnet(CentralResource):
    def __init__(self, maxhosts=2):
        CentralResource.__init__(self)
        global _privateSubnetCounter
        self.octet = _privateSubnetCounter
        _privateSubnetCounter = _privateSubnetCounter + 1

    def getSubnet(self):
        return "10.10.%u.0" % (self.octet)

    def getMask(self):
        return "255.255.255.0"

    def getBroadcast(self):
        return "10.10.%u.255" % (self.octet)

    def getAddress(self, offset):
        return "10.10.%u.%u" % (self.octet, offset)

#############################################################################

class VLANPeer(NetworkTestPeer):
    """A peer we can test VLANs against"""
    def __init__(self):
        self.interface = "eth0"
        self.vlans = []
        NetworkTestPeer.__init__(self)
        
    def createVLANInterface(self, vlan, subnet, offset):
        """Create a VLAN interface on the peer"""
        self.vlans.append(vlan)
        self.runCommand("/sbin/modprobe 8021q")
        self.runCommand("/sbin/vconfig add %s %u" %
                       (self.interface, vlan))
        self.runCommand("/sbin/ifconfig %s.%u %s netmask %s up" %
                       (self.interface,
                        vlan,
                        subnet.getAddress(offset),
                        subnet.getMask()))

    def cleanup(self):
        for vlan in self.vlans:
            try:
                self.runCommand("/sbin/ifconfig %s.%u down" %
                               (self.interface, vlan))
                self.runCommand("/sbin/vconfig rem %s.%u" %
                               (self.interface, vlan))
            except:
                pass

    def callback(self):
        self.cleanup()
        NetworkTestPeer.callback(self)

#############################################################################
    
class BuildServer(object):
    """A build server"""
    def __init__(self, arch, hostname):
        self.arch = arch
        self.scratch = "/local/scratch/xenrt"
        self.hostname = hostname
        self.username = "xenrtd"
        self.password = "X3nR0cks"
        self.builddir = None
        self.tailor()
        self.builddir = self.newdir()

    def tailor(self):
        # Ensure this build server has everything it needs to perform
        # the builds. It is safe to call this method multiple times.
        # This assumes the xenrtd user has passwordless sudo rights.

        # Create necessary directories
        if self._exec("test -d %s" % (self.scratch), retval="code") != 0:
            xenrt.TEC().logverbose("Creating scratch directory on build "
                                   "server %s" % (self.hostname))
            self._exec("sudo mkdir -p %s" % (self.scratch))
            self._exec("sudo chown xenrtd %s" % (self.scratch))
            self._exec("mkdir -p %s/repos/git-cache" % (self.scratch))

        # Copy our files over
        xenrt.TEC().logverbose("Checking file overlay is up to date on "
                               "build server %s" % (self.hostname))
        overlay = ("%s/data/ossbuild" % (xenrt.TEC().lookup("XENRT_BASE")))
        filelist = xenrt.command("find %s -type f" % (overlay)).split()
        filelist = map(lambda x:x.replace(overlay, "", 1), filelist)
        tdir = None
        try:
            for filepath in filelist:
                remotemd5 = "unknown"
                if self._exec("test -e %s" % (filepath), retval="code") == 0:
                    remotemd5 = self._exec("md5sum %s" % (filepath)).split()[0]
                localmd5 = xenrt.command("md5sum %s%s" %
                                         (overlay, filepath)).split()[0]
                if localmd5 != remotemd5:
                    xenrt.TEC().logverbose("Updating %s on build server %s" %
                                           (filepath, self.hostname))
                    if not tdir:
                        tdir = self.newdir()
                    self._exec("sudo mkdir -p %s" %
                               (os.path.dirname(filepath)))
                    self._exec("mkdir -p %s%s" %
                               (tdir, os.path.dirname(filepath)))
                    sftp = self.sftpClient()
                    try:
                        sftp.copyTo(overlay + filepath, tdir + filepath)
                        self._exec("sudo cp -p %s%s %s" %
                                   (tdir, filepath, filepath))
                    finally:
                        sftp.close()
        finally:
            if tdir:
                self._exec("rm -rf %s" % (tdir))
        
    def newdir(self):
        """Create a new directory for building"""        
        builddir = string.strip(
            self.execCommand("mktemp -d %s/xenrtbuildXXXXXX" %
                             (self.scratch)))
        self.execCommand("chmod 775 %s" % (builddir))
        xenrt.TEC().logverbose("Created build dir %s on %s" %
                               (builddir, self.hostname))
        xenrt.TEC().gec.registerCallback(self)
        return builddir

    def cleanup(self):
        if self.builddir:
            if int(xenrt.TEC().lookup("KEEP_BUILD_DIRS", "0")):
                xenrt.TEC().logverbose("Preserving build directory %s:%s" %
                                       (self.hostname, self.builddir))
            else:
                builddir = self.builddir
                self.builddir = None
                xenrt.TEC().logverbose("Removing build dir %s on %s" %
                                       (builddir, self.hostname))
                self.execCommand("rm -rf %s" % (builddir))
            xenrt.TEC().gec.unregisterCallback(self)

    def callback(self):
        self.cleanup()

    def tempFile(self):
        return string.strip(self.execCommand("mktemp /tmp/xenrtbuildXXXXXX"))

    def tempFileDelete(self, filename):
        self.execCommand("rm -f %s" % (filename))

    def _exec(self, command, timeout=300, retval="string"):
        data = xenrt.ssh.SSH(self.hostname,
                             command,
                             username=self.username,
                             password=self.password,
                             retval=retval,
                             timeout=timeout)
        return data

    def execCommand(self, command, timeout=3600,
                    level=xenrt.RC_FAIL, retval="string"):
        """Execute a command in the build directory"""
        xenrt.TEC().logverbose("Build command '%s'" % (command))
        if self.builddir:
            c = "cd %s; %s" % (self.builddir, command)
        else:
            c = command
        env = xenrt.TEC().lookup("ENV", None)
        if env:
            e = ["export"]
            for var in env.keys():
                e.append("%s='%s'" % (var, env[var]))
            c = string.join(e) + " && " + c
        try:
            data = xenrt.ssh.SSH(self.hostname, c,
                                 username=self.username,
                                 password=self.password,
                                 level=level,
                                 retval=retval,
                                 timeout=timeout)
        finally:
            try:
                xenrt.ssh.SSH(self.hostname,
                              "df ; df -i",
                              username=self.username,
                              password=self.password)
            except:
                pass
        return data

    def sftpClient(self, level=xenrt.RC_FAIL):
        """Get a SFTP client object to the guest"""
        return xenrt.ssh.SFTPSession(self.hostname,
                                     username=self.username,
                                     password=self.password,
                                     level=level)

    def getFileAge(self, file):
        """Return the time in seconds since file was last modified"""
        return int(self.execCommand("echo $[`date +%%s` - `stat -c %%Y %s`]" %
                                    (file)))

    def lockGet(self, lock, timeout=600, level=xenrt.RC_FAIL):
        now = xenrt.timenow()
        deadline = now + timeout
        while True:
            try:
                self.execCommand("mkdir %s" % (lock))
                return
            except:
                pass
            now = xenrt.timenow()
            if now > deadline:
                return xenrt.XRT("Timed out waiting for %s" % (lock), level)
            xenrt.sleep(60)
        
    def lockRelease(self, lock):
        self.execCommand("rmdir %s" % (lock))

    def webDownload(self, url, file):
        self.execCommand("wget '%s' -O '%s/%s'" % (url, self.builddir, file))

def getBuildServer(arch):
    if arch == "x86-32" or arch == "x86-32p":
        bs = BuildServer(arch, xenrt.TEC().lookup("BUILD_HOST_32",
                                                  "localhost"))
    elif arch == "x86-64":
        bs = BuildServer(arch, xenrt.TEC().lookup("BUILD_HOST_64"))
    elif arch == "ia64-cross":
        bs = BuildServer(arch, xenrt.TEC().lookup("BUILD_HOST_IA64_CROSS"))
    else:
        raise xenrt.XRTError("Unknown architecture for build: %s" % (arch))
    xenrt.TEC().registry.buildServerPut(bs.hostname, bs)
    return bs

class _NetworkResourceFromRange(CentralResource):
    LOCKID = None

    @classmethod
    def _getRange(cls, size, available, wait=True, **kwargs):
        cr = xenrt.resources.CentralResource()
        attempts = 0
        while True:
            ret = []
            try:
                xenrt.TEC().logverbose("About to lock range of network resources - current locking status")
                cr.logList()
                # Iterate through every possible starting point for a range
                for i in xrange(len(available)):
                    rangeToTry = available[i:i+size]
                    # Exit the loop if we've got beyond the point where there are enough addresses beyond it
                    if len(rangeToTry) < size:
                        break
                    rangeOK = True
                    # Check each address in this range to see if it's locked
                    for a in rangeToTry:
                        if cls.isLocked("%s-%s" % (cls.LOCKID, a)):
                            rangeOK = False
                            break
                    # If none of them are locked, then attempt to lock them all. This could fail, in which case we'll sleep for a minute and try again
                    if rangeOK:
                        for a in rangeToTry:
                            try:
                                ret.append(cls._rangeFactory(a, **kwargs))
                            except Exception, e:
                                for r in ret:
                                    r.release()
                                raise xenrt.XRTError("Could not lock all network resources")
                        break
                if len(ret) == 0:
                    raise xenrt.XRTError("Could not find a suitable range to lock")
            except Exception, e:
                if attempts > 30 or not wait:
                    raise
                attempts += 1
                xenrt.TEC().logverbose("Could not lock - %s, sleeping before retry" % str(e))
                # Sleep for a random time to avoid conflicts with another process
                xenrt.sleep(60 + random.randint(0,10))
            else:
                break
        return ret
    
    def _lockResourceFromRange(self, available, specified=False):
        CentralResource.__init__(self, held=False)
        name = None
        startlooking = xenrt.util.timenow()
        # Find one of the targets that is available
        while True:
            for a in available:
                try:
                    self.acquire("%s-%s" % (self.LOCKID, a))
                    name = a
                    self.resourceHeld = True
                    break
                except xenrt.XRTError:
                    continue
            if name:
                break
            # If an IP has been specified, we'll fail fast
            if specified or xenrt.util.timenow() > (startlooking + 3600):
                xenrt.TEC().logverbose("Could not lock IP Address, current central resource status:")
                self.logList()
                raise xenrt.XRTError("Timed out waiting for an IP Range to be "
                                     "available")
            xenrt.sleep(60)
        return name
        
    def release(self, atExit=False):
        if not xenrt.util.keepSetup():
            if atExit:
                for host in xenrt.TEC().registry.hostList():
                    if host == "SHARED":
                        continue
                    h = xenrt.TEC().registry.hostGet(host)
                    h.machine.exitPowerOff()
            CentralResource.release(self, atExit)

    @classmethod
    def _rangeFactory(cls, **kwargs):
        raise xenrt.XRTError("Not implemented")

class PrivateVLAN(_NetworkResourceFromRange):
    LOCKID = "VLAN"

    @classmethod
    def _rangeFactory(cls, vlan):
        return cls(vlan=vlan)

    @classmethod
    def getVLANRange(cls, size, wait=True):
        vlans = cls._getAllVLANsInRange()
        return cls._getRange(size, vlans, wait=wait)

    @classmethod
    def _getAllVLANsInRange(cls):
        vrange = xenrt.TEC().lookup(["NETWORK_CONFIG", "PRIVATEVLANS"])
        (start, end) = [int(x) for x in vrange.split("-")]
        return range(start, end+1)

    def __init__(self, vlan=None):
        CentralResource.__init__(self)
        if not vlan:
            xenrt.TEC().logverbose("About to attempt to lock VLAN - current central resource status:")
            self.logList()
        vlans = self._getAllVLANsInRange()
       
        # Filter out based on IP. This is safer than just populating addrs with the specified IP, as it ensures it is a valid IP
        if vlan:
            vlans = [x for x in vlans if x==vlan]

        self.id = self._lockResourceFromRange(vlans, vlan)

    def getName(self):
        return "VLAN%d" % self.id

    def getID(self):
        return self.id

class PrivateRoutedVLAN(PrivateVLAN):
    LOCKID = "ROUTEDVLAN"

    @classmethod
    def _getAllVLANsInRange(cls):
        vrange = xenrt.TEC().lookup(["NETWORK_CONFIG", "PRIVATE_ROUTED_VLANS"])
        return [int(re.match("[A-Za-z]*(\d+)$", x).group(1)) for x in vrange.keys()]

    @classmethod
    def getNetworkConfigForVLAN(cls, vlan):
        cfg = xenrt.TEC().lookup(["NETWORK_CONFIG", "PRIVATE_ROUTED_VLANS"])
        key = [x for x in cfg.keys() if re.match("[A-Za-z]*%d$" % int(vlan), x)][0]
        (net, gateway) = cfg[key].split(",")
        i = IPy.IP(net) 
        return {"id": int(vlan), "subnet": i.net().strNormal(), "netmask": i.netmask().strNormal(), "gateway": gateway}

    def getNetworkConfig(self):
        return self.__class__.getNetworkConfigForVLAN(self.id)

class _StaticIPAddr(_NetworkResourceFromRange):

    POOLSTART = None
    POOLEND = None

    @classmethod
    def _rangeFactory(cls, ip, network):
        return cls(network=network, ip=ip)

    @classmethod
    def getIPRange(cls, size, network="NPRI", wait=True):
        addrs = [x.strCompressed() for x in cls._getAllAddressesInRange(network)]
        return cls._getRange(size, addrs, wait=wait, network=network)

    @classmethod
    def _getAllAddressesInRange(cls, network):
        if network == "NPRI":
            configpath = ["NETWORK_CONFIG", "DEFAULT"]
        elif network == "NSEC":
            configpath = ["NETWORK_CONFIG", "SECONDARY"]
        else:
            configpath = ["NETWORK_CONFIG", "VLANS", network]
        
        configpath.append(cls.POOLSTART)
        rangestart = xenrt.TEC().lookup(configpath, None)
        configpath[-1] = cls.POOLEND
        rangeend = xenrt.TEC().lookup(configpath, None)
        if not rangestart or not rangeend:
            raise xenrt.XRTError("No valid static IP range specified")
        
        rangestartip = IPy.IP(rangestart)
        rangeendip = IPy.IP(rangeend)

        addrs = [rangestartip]
        while addrs[-1] < rangeendip:
            addrs.append(IPy.IP(addrs[-1].int() + 1))
        return addrs


    def __init__(self,  network="NPRI", ip=None):
        CentralResource.__init__(self)
        if not ip:
            xenrt.TEC().logverbose("About to attempt to lock IP address - current central resource status:")
            self.logList()
        addrs = self._getAllAddressesInRange(network)
       
        # Filter out based on IP. This is safer than just populating addrs with the specified IP, as it ensures it is a valid IP
        if ip:
            addrs = [x for x in addrs if x==IPy.IP(ip)]

        self.addr = self._lockResourceFromRange([x.strCompressed() for x in addrs], ip)
    
    def getAddr(self):
        return self.addr

class StaticIP4Addr(object):
    def __init__(self, network="NPRI", mac=None, name=None):
        if xenrt.TEC().lookup("XENRT_DHCPD", False, boolean=True):
            self._delegate = StaticIP4AddrDHCP(network=network, mac=mac, name=name)
        else:
            if mac:
                raise xenrt.XRTError("MAC-based reservations not supported")
            self._delegate = StaticIP4AddrFileBased(network)

    @classmethod
    def getIPRange(cls, size, network="NPRI", wait=True):
        if xenrt.TEC().lookup("XENRT_DHCPD", False, boolean=True):
            return StaticIP4AddrDHCP.getIPRange(size, network, wait)
        else:
            return StaticIP4AddrFileBased.getIPRange(size, network, wait)

    def __getattr__(self, name):
        return getattr(self._delegate, name)

class StaticIP4AddrFileBased(_StaticIPAddr):
    LOCKID = "IP4ADDR"
    POOLSTART = "STATICPOOLSTART"
    POOLEND = "STATICPOOLEND"

class StaticIP4AddrDHCPRangeMarker(object):
    def __init__(self, addrs):
        self.addrs = addrs
        xenrt.TEC().gec.registerCallback(self, mark=True, order=1)

    def mark(self):
        try:
            DhcpXmlRpc().updateReservations(self.addrs)
        except Exception, ex:
            xenrt.TEC().logverbose("Error updating DHCP reservation: " + str(ex))
            xenrt.TEC().warning("Error updating DHCP reservation: " + str(ex))

    def callback(self):
        self.release(atExit=True)

    def release(self, atExit=False):
        if not xenrt.util.keepSetup():
            if atExit:
                for host in xenrt.TEC().registry.hostList():
                    if host == "SHARED":
                        continue
                    h = xenrt.TEC().registry.hostGet(host)
                    h.machine.exitPowerOff()
            DhcpXmlRpc().releaseAddresses(self.addrs)
            xenrt.TEC().gec.unregisterCallback(self)

class StaticIP4AddrDHCP(object):
    def __init__(self, network, mac=None, ip=None, name=None, rangeObj=None):
        if ip:
            self.addr = ip
        else:
            self.addr = DhcpXmlRpc().reserveSingleAddress(self.networkToInterface(network), self.lockData(), mac, name)
        self.rangeObj = rangeObj
        if not self.rangeObj:
            xenrt.TEC().gec.registerCallback(self, mark=True, order=1)
        self.lockid = "IP4ADDR-%s" % self.addr
        xenrt.GEC().registry.centralResourcePut(self.lockid, self)

    def getAddr(self):
        return self.addr

    def release(self, atExit=False):
        if not xenrt.util.keepSetup():
            if atExit:
                for host in xenrt.TEC().registry.hostList():
                    if host == "SHARED":
                        continue
                    h = xenrt.TEC().registry.hostGet(host)
                    h.machine.exitPowerOff()
            DhcpXmlRpc().releaseAddress(self.addr)
            if self.rangeObj:
                try:
                    self.rangeObj.addrs.remove(self.addr)
                except:
                    xenrt.TEC().logverbose("Could not remove address from range")
            else:
                xenrt.TEC().gec.unregisterCallback(self)

    @classmethod
    def getIPRange(cls, size, network, wait):
        deadline = xenrt.timenow() + 3600
        while True:
            try:
                addrs = DhcpXmlRpc().reserveAddressRange(cls.networkToInterface(network), size, cls.lockData())
            except:
                if not wait or xenrt.timenow() > deadline:
                    raise
                xenrt.sleep(60)
            else:
                break

        r = StaticIP4AddrDHCPRangeMarker(addrs)
        return [StaticIP4AddrDHCP(network, ip=x, rangeObj=r) for x in addrs]
     

    @classmethod
    def lockData(cls):
        return xenrt.GEC().dbconnect.jobid() or "nojob"

    @classmethod
    def networkToInterface(cls, network):
        if network == "NPRI":
            return "eth0"
        elif network == "NSEC":
            return "eth0.%s" % (xenrt.TEC().lookup(["NETWORK_CONFIG","SECONDARY","VLAN"]))
        else:
            return "eth0.%s" % (xenrt.TEC().lookup(["NETWORK_CONFIG","VLANS",network,"ID"]))

    def mark(self):
        try:
            DhcpXmlRpc().updateReservation(self.addr)
        except Exception, ex:
            xenrt.TEC().logverbose("Error updating DHCP reservation: " + str(ex))
            xenrt.TEC().warning("Error updating DHCP reservation: " + str(ex))

    def callback(self):
        self.release(atExit=True)

class StaticIP6Addr(_StaticIPAddr):
    LOCKID = "IP6ADDR"
    POOLSTART = "STATICPOOLSTART6"
    POOLEND = "STATICPOOLEND6"

class SharedHost(object):
    def __init__(self, hostname=None, doguests=False):
        hosts = xenrt.TEC().lookup("SHARED_HOSTS")

        if hostname:
            h = hosts[hostname]
            machine = xenrt.PhysicalHost(hostname, ipaddr = h["ADDRESS"])
            useHost = xenrt.GenericHost(machine)
            useHost.findPassword()
        else:
            maxmem = 0
            useHost = None
            for host in hosts.keys():
                try:
                    h = hosts[host]
                    machine = xenrt.PhysicalHost(host, ipaddr = h["ADDRESS"])
                    place = xenrt.GenericHost(machine)
                    place.findPassword()
                    mem = int(place.execdom0("xe host-list params=memory-free --minimal").strip())
                    if (mem > maxmem):
                        useHost = place
                        maxmem = mem
                except Exception, e:
                    xenrt.TEC().logverbose("Warning - could not get free memopry from %s: %s" % (h, str(e)))
                    continue

        if not useHost:
            raise xenrt.XRTError("Could not find shared host")
        useHost.checkVersion()
        host = xenrt.lib.xenserver.hostFactory(useHost.productVersion)(useHost.machine, productVersion=useHost.productVersion)
        useHost.populateSubclass(host)
        host.existing(doguests=doguests, guestsInRegistry=False)
        self.host = host
        xenrt.TEC().gec.registerCallback(self)
    
    def getHost(self):
        return self.host

    def createTemplate(self, distro, arch, disksize):
        g = self.getHost().createBasicGuest(name="%s-%s" % (distro, arch), distro=distro, arch=arch, disksize=disksize)
        if distro.startswith("rhel") or distro.startswith("centos") or distro.startswith("oel") or (distro.startswith("sl") and not distro.startswith("sles")):
            g.execguest("sed -i /HWADDR/d /etc/sysconfig/network-scripts/ifcfg-eth0")
        g.shutdown()
        g.paramSet("name-label", "xenrt-template-%s-%s" % (distro, arch))
        g.paramSet("is-a-template", "true")

    def callback(self):
        if xenrt.util.keepSetup():
            return
        jobid = xenrt.GEC().dbconnect.jobid()
        if jobid:
            vms = self.getHost().execdom0("xe vm-list --minimal").strip().split(",")
            for vm in vms:
                vmname = self.getHost().execdom0("xe vm-param-get uuid=%s param-name=name-label" % vm).strip()
                if re.match(".+-%s$" % jobid, vmname):
                    try:
                        self.getHost().execdom0("xe vm-shutdown uuid=%s --force" % (vm))
                    except:
                        pass
                    self.getHost().execdom0("xe vm-uninstall uuid=%s --force" % (vm))
            
class ProductLicense(CentralResource):
    def __init__(self, product):
        CentralResource.__init__(self)
        xenrt.TEC().logverbose("About to attempt to lock %s license - current central resource status:" % product)
        self.logList()

        self.product = product
        licenses = xenrt.TEC().lookup(["LICENSES", "PRODUCT_%s" % product]).keys()

        startlooking = xenrt.util.timenow()
        license = None
        while True:
            for l in licenses:
                try:
                    self.acquire("LICENSE-%s-%s" % (product, l), shared=False)
                    license = l
                    self.resourceHeld = True
                    break
                except xenrt.XRTError:
                    continue
            if license:
                break
            if xenrt.util.timenow() > (startlooking + 3600):
                xenrt.TEC().logverbose("Could not lock license, current central resource status:")
                self.logList()
                raise xenrt.XRTError("Timed out waiting for a license to be available")
            xenrt.sleep(60)

        self.license = license

    def getKey(self):
        return xenrt.TEC().lookup(["LICENSES", "PRODUCT_%s" % self.product, self.license])


class GlobalResource(CentralResource):
    def __init__(self, restype):
        CentralResource.__init__(self)

        startlooking = xenrt.timenow()

        while True:
            try:
                res = xenrt.GEC().dbconnect.api.lock_global_resource(restype, xenrt.TEC().lookup("XENRT_SITE"), xenrt.GEC().dbconnect.jobid() or 0)
            except Exception, e:
                xenrt.TEC().logverbose("Warning: exception %s while trying to acquire lock" % str(e))
            else:
                if 'name' in res:
                    self.name = res['name']
                    self.data = res['data']
                    break
                if xenrt.util.timenow() > (startlooking + 3600):
                    xenrt.TEC().logverbose("Could not lock global resource of type %s" % restype)
                    raise xenrt.XRTError("Timed out waiting for %s to be available" % restype)
            xenrt.sleep(60)
        self.acquire("GLOBAL-%s" % (self.name))
        self.resourceHeld = True

    def release(self, atExit=False):
        if not atExit or not xenrt.util.keepSetup():
            xenrt.GEC().dbconnect.api.release_global_resource(self.getName())
            CentralResource.release(self, atExit)
        
    def getName(self):
        return self.name

    def getData(self):
        return self.data
