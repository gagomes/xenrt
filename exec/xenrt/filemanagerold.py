#
# XenRT: Test harness for Xen and the XenServer product family
#
# Abstract mechanism to get input files such as product ISOs to test
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, os.path, threading, os, shutil, tempfile, stat, md5
import time, httplib, urlparse, glob
import xenrt, xenrt.util

__all__ = ["getFileManager"]

class FileManager(object):
    """Filemanager base class, used for controllers with access to the same
    file tree as the job scheduler"""

    def __init__(self, basevar="INPUTDIR"):
        self.basedirdefault = self._resolveLatestDir(xenrt.TEC().lookup(basevar, None))
        if not self.basedirdefault:
            xenrt.TEC().warning('FileManager object created without base dir')
        self.forceHTTPHack = False

    def setInputDir(self, dirname):
        if not dirname:
            dirname = "None"
        xenrt.TEC().setThreadLocalVariable("_THREAD_LOCAL_INPUTDIR",
                                           self._resolveLatestDir(dirname),
                                           fallbackToGlobal=True)

    def _resolveLatestDir(self, dirname):
        userServer = xenrt.TEC().lookup("SSH_SYMLINK_RESOLVER", None)
        if not userServer:
            return dirname
        if not dirname:
            return None
        sdirname = dirname
        httpBase = xenrt.TEC().lookup("FORCE_HTTP_FETCH", None)
        if httpBase and dirname.startswith(httpBase):
            sdirname = dirname[len(httpBase):]
        sdirname = sdirname.rstrip("/")
        if not sdirname.endswith("latest"):
            return dirname
        (user, server) = userServer.split("@", 2)
        try:
            realDir = xenrt.SSH(server, "readlink %s" % sdirname, username=user, retval="string").strip()
        except:
            return dirname
        if realDir == "":
            return dirname
        xenrt.TEC().logverbose("Resolved latest symlink to %s" % realDir)
        return "%s/%s" % (os.path.dirname(dirname.strip("/")), realDir)

    def isReleasedBuild(self):
        return "/release/" in self._getBaseDir()

    def _getBaseDir(self):
        """Internal method to get the currently in force base directory.
        This will take into account thread-local input dir overrides."""
        dirname = xenrt.TEC().lookup("_THREAD_LOCAL_INPUTDIR", None)
        if not dirname or dirname == "None":
            return self.basedirdefault
        if self.forceHTTPHack and dirname[0] == "/":
            urlpref = xenrt.TEC().lookup("FORCE_HTTP_FETCH", "")
            return "%s%s" % (urlpref, dirname)
        return dirname
    
    def getFiles(self, *filename): 
        raise xenrt.XRTError("%s: getFiles is not implemented" % self.__class__.__name__)
     
    def getFile(self, *filename):
        """Get an absolute path to the relative filename provided. Returns
        None if the file does not exist. If this is an absolute path then
        just return it unchanged."""
        for f in filename:
            xenrt.TEC().logverbose("Looking for %s." % (f))
            if f[0] == "/":
                if os.path.exists(f):
                    return f
                return None
            basedir = self._getBaseDir()
            if not basedir:
                raise xenrt.XRTError("No base directory.")
            path = "%s/%s" % (basedir, f)
            xenrt.TEC().logverbose("... %s" % (path))
            if os.path.exists(path):
                return path
        return None

    def fileExists(self, *filename):
        """Return True if one of the specified files exists"""
        for f in filename:
            xenrt.TEC().logverbose("Looking for %s." % (f))
            if f[0] == "/":
                if os.path.exists(f):
                    return True
                return False
            basedir = self._getBaseDir()
            if not basedir:
                xenrt.TEC().logverbose("No base directory.")
                return False
            path = "%s/%s" % (basedir, f)
            xenrt.TEC().logverbose("... %s" % (path))
            if os.path.exists(path):
                return True
        return False
    
class RemoteFileManager(FileManager):
    """A filemanager for remote sites that get files from the job scheduler."""

    MAX_ATTEMPTS = 1

    def __init__(self, basevar="INPUTDIR"):
        FileManager.__init__(self, basevar=basevar)
        self.mylock = threading.Lock()
        self.shared = xenrt.TEC().lookup("FILE_MANAGER_CACHE", None)
        if self.shared and not os.path.exists(self.shared):
            try:
                os.makedirs(self.shared)
            except:
                self.shared = None
        if self.shared:
            # Use a subdir for the per-job cache so we can hardlink
            try:
                d = tempfile.mkdtemp("", "HL", self.shared)
                os.chmod(d,
                         stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH |
                         stat.S_IXOTH)
                self.cachedir = d
            except:
                # No write permission, use a non-shared cache only
                self.shared = None
        if not self.shared:
            # Create a local cache for non-shared use
            self.cachedir = xenrt.GEC().anontec.tempDir()
        xenrt.GEC().registerCallback(self)

    def callback(self):
        shutil.rmtree(self.cachedir,1)

    def cleanup(self,days=14):
        """Cleanup the shared cache"""
        if not self.shared:
            return

        # Get directory entries
        entries = os.listdir(self.shared)
        
        # Process the list to find any that are older than 2 weeks
        toRemove = []
        for entry in entries:
            cachepath = "%s/%s" % (self.shared,entry)
            if os.path.isfile(cachepath):
                mtime = os.path.getmtime(cachepath)
                if (time.time() - mtime) > (days*24*3600):
                    toRemove.append(entry)
        
        # Now remove the entries
        for entry in toRemove:
            os.unlink("%s/%s" % (self.shared,entry))

    def removeFromSharedCache(self, filename):
        cachepath, remote = self.getRemotePaths(filename)
        s = self.cacheLookup(remote)
        if s and os.path.exists(s):
            xenrt.TEC().logverbose("Removing %s" % s)
            os.unlink(s)

    def addToSharedCache(self, remote, filename):
        """Add to shared cache. This is based on centralised path, not
        content"""
        if not self.shared:
            return
        md5sum = md5.new(remote).hexdigest()
        cachepath = "%s/%s" % (self.shared, md5sum)
        if not os.path.exists(cachepath):
            xenrt.TEC().logverbose("Adding %s to shared cache as %s" %
                                   (remote, cachepath))
            os.link(filename, cachepath)
        if os.path.exists("%s.fetching" % (cachepath)):
            try:
                os.unlink("%s.fetching" % (cachepath))
            except:
                pass

    def notifyCacheFetch(self, remote, cancel=False):
        """Inform the shared cache we are commencing a fetch of a remote
        file."""
        if not self.shared:
            return
        md5sum = md5.new(remote).hexdigest()
        flagpath = "%s/%s.fetching" % (self.shared, md5sum)
        if cancel:
            try:
                os.unlink(flagpath)
            except:
                pass
            return
        if not os.path.exists(flagpath):
            f = file(flagpath, "w")
            f.write("%u" % (xenrt.util.timenow()))
            f.close()
            os.chmod(flagpath,
                     stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)

    def cacheLookup(self, remote):
        if not self.shared:
            return None
        md5sum = md5.new(remote).hexdigest()
        cachepath = "%s/%s" % (self.shared, md5sum)
        if os.path.exists(cachepath):
            return cachepath
        if os.path.exists("%s.fetching" % (cachepath)):
            # Wait a limited duration for this fetch to complete. If we
            # don't get it in time then return None and refetch ourselves
            xenrt.TEC().logverbose("Waiting for another process to fetch %s"
                                   % (cachepath))
            deadline = xenrt.util.timenow() + 1800
            while True:
                if os.path.exists(cachepath):
                    return cachepath
                if not os.path.exists("%s.fetching" % (cachepath)):
                    return None
                if xenrt.util.timenow() > deadline:
                    return None
                xenrt.sleep(60)
        return None

    def getFile(self, *filename):
        return self._getFile(False, *filename)
    
    def getFiles(self, *filename):
        return self._getFile(True, *filename)
    
    def _getFile(self, getMultipleFiles, *filename):
        for file in filename:
            
            if file[0] != "/" and not self._getBaseDir():
                continue
            
            xenrt.TEC().logverbose("Looking for %s." % (file))
            tries = 0
            while tries < self.MAX_ATTEMPTS:
                try:
                    f = self.getFileAttempt(file, getMultipleFiles)
                    if f:
                        return f
                except Exception, e:
                    xenrt.TEC().warning("Exception on getFileAttempt(%s): %s" %
                                        (file, str(e)))
                xenrt.sleep(5)
                tries = tries + 1
        return None
    
    def fileExists(self, *filename):
        for file in filename:
            xenrt.TEC().logverbose("Looking for %s." % (file))
            if self.isFileAvailable(file):
                return True
        return False

    def getRemotePaths(self, filename):
        if filename[0] == "/":                
            cachepath = "%s%s" % (self.cachedir, filename)
            urlpref = xenrt.TEC().lookup("FORCE_HTTP_FETCH", "")
            if urlpref:
                remote = urlpref + filename
            else:
                remote = filename
        elif filename[0:7] == "http://":
            cachepath = "%s/%s" % (self.cachedir, filename[7:])
            if "*" in cachepath:
                cachepath = cachepath + ".tar.gz"
            remote = filename
        else:
            basedir = self._getBaseDir()
            dmd5 = md5.new(basedir).hexdigest()
            cachepath = "%s/%s/%s" % (self.cachedir, dmd5, filename)
            remote = "%s/%s" % (basedir, filename)
        cachepath = cachepath.replace("*", "WILDCARD")
        if cachepath[-1] == "/":
            cachepath = "%s.dir.tar.gz" % cachepath[0:-1]
        return (cachepath, remote)

    def getFileAttempt(self, filename, getMultipleFiles):
        try:
            xenrt.TEC().logverbose("Remote getFile: %s" % (filename))
            self.mylock.acquire()

            cachepath, remote = self.getRemotePaths(filename)
            # If we have it already, return it
            if os.path.exists(cachepath):
                xenrt.TEC().logverbose("Found %s in cache (%s)." % (filename, cachepath))
                return cachepath
            if not os.path.exists(os.path.dirname(cachepath)):
                os.makedirs(os.path.dirname(cachepath))
            # See if it's in the shared cache
            s = self.cacheLookup(remote)
            if s:
                xenrt.TEC().logverbose("Found %s in shared cache." % (filename))
                os.link(s, cachepath)
            else:
                # Fetch it
                xenrt.TEC().logverbose("Fetching %s." % (filename))
                self.notifyCacheFetch(remote)
                try:
                    if getMultipleFiles:
                        r = self._fetchFiles(remote, cachepath)
                    else:
                        r = self._fetchFile(remote, cachepath)
                    if r == None:
                        xenrt.TEC().logverbose("Failed to retrieve %s." % (filename))
                        try:
                            os.unlink(cachepath)
                        except:
                            pass
                        self.notifyCacheFetch(remote, cancel=True)
                        return None
                    os.chmod(cachepath,
                             stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH |
                             stat.S_IXOTH)
                    self.addToSharedCache(remote, cachepath)
                except Exception, e:
                    self.notifyCacheFetch(remote, cancel=True)
                    raise e
            xenrt.TEC().logverbose("Retrieved %s." % (filename))
            return cachepath
        finally:
            self.mylock.release()

    def isFileAvailable(self, filename):
        try:
            xenrt.TEC().logverbose("Remote isFileAvailable: %s" % (filename))
            self.mylock.acquire()

            cachepath, remote = self.getRemotePaths(filename)

            # Is it in the cache, or the shared cache already
            if os.path.exists(cachepath):
                return True
            s = self.cacheLookup(remote)
            if s:
                return True

            # See if it is fetchable
            return self._isFetchable(remote)            
        finally:
            self.mylock.release()

    def _fetchFile(self, remote, cachepath):
        try:
            proxy = xenrt.TEC().lookup("HTTP_PROXY", None)
            if proxy:
                proxyflag = " -e http_proxy=%s" % proxy
            else:
                proxyflag = ""
            if remote[-1] == "/":
                t = xenrt.resources.TempDirectory()
                u = urlparse.urlparse(remote)
                cutdirs = len(u.path.split("/")) - 2 # Remove beginning and end items
                xenrt.util.command("wget%s -nv '%s' -P '%s' --recursive -nH -np --cut-dirs %d" % (proxyflag, remote, t.dir, cutdirs))
                xenrt.util.command("cd %s && tar -cvzf %s *" % (t.dir, cachepath))
                t.remove()
            elif "*" in remote:
                t = xenrt.resources.TempDirectory()
                xenrt.util.command("wget%s -nv '%s' -P '%s' --recursive --accept '%s' -nd -l 1" % (proxyflag, "/".join(remote.split("/")[0:-1]), t.dir, remote.split("/")[-1]))
                fetched = glob.glob("%s/*" % t.dir)
                os.rename(fetched[0], cachepath)
                t.remove()
            else:
                xenrt.util.command("wget%s -nv '%s' -O '%s'" % (proxyflag, remote, cachepath))
                
        except Exception, e:
            xenrt.TEC().logverbose("HTTP fetchFile exception: %s" % (str(e)))
            return None
        return True
    
    def _fetchFiles(self, remote, cachepath, depthOfSearch = 2):
        """
        Fetch a collection of files from a URL using wget
        depthOfSearch is how far down the URL tree to look for files - default is 2
        """
        try:
            proxyflag = self._getProxyFlag()
            t = xenrt.resources.TempDirectory()
            fetchPatterns= [remote.split("/")[-1], remote.split("/")[-1] + ".[0-9]*"]
            xenrt.util.command("wget%s -nv '%s' -P '%s' --recursive --accept '%s' -nd -l %d" % (proxyflag, "/".join(remote.split("/")[0:-1]), t.dir, ",".join(fetchPatterns), depthOfSearch))
            fetched = glob.glob("%s/*" % t.dir)
            fileList = " ".join(fetched)
            xenrt.TEC().logverbose( "Fetched files: %s"  % fileList)
            xenrt.archive.TarGzArchiver().create(cachepath, fileList)
            t.remove()
        except Exception, e:
            xenrt.TEC().logverbose("HTTP multiple fetchFile exception: %s" % (str(e)))
            return None
        return True
    
    def _getProxyFlag(self):
        proxy = xenrt.TEC().lookup("HTTP_PROXY", None)
        if proxy:
            return " -e http_proxy=%s" % proxy
        else:
            return ""   

    def _isFetchable(self, remote):
        # Split remote in to host and path
        u = urlparse.urlparse(remote)
        host = u[1]
        path = u[2]
        try:
            conn = httplib.HTTPConnection(host)
            conn.request("HEAD", path)
            res = conn.getresponse()
            conn.close()
            return (res.status == 200)
        except:
            return False

def getFileManager(basevar="INPUTDIR", remote=False):
    """Return a file manager object suitable for the local site."""
    id = xenrt.TEC().lookup(basevar, "")
    if id[0:7] == "http://":
        return RemoteFileManager(basevar=basevar)
    elif remote:
        urlpref = xenrt.TEC().lookup("FORCE_HTTP_FETCH", "")
        forceremotehttp = xenrt.TEC().lookup("FORCE_REMOTE_HTTP", False, boolean=True)
        if urlpref and len(id) > 0 and id[0] == "/":
            xenrt.GEC().config.setVariable(basevar, "%s%s" % (urlpref, id))
            r = RemoteFileManager(basevar=basevar)
            r.forceHTTPHack = True
            return r
        elif urlpref and forceremotehttp:
            xenrt.GEC().config.setVariable(basevar, urlpref)
            r = RemoteFileManager(basevar=basevar)
            r.forceHTTPHack = True
            return r
        elif xenrt.TEC().lookup("FORCE_LOCAL_FETCH", False, boolean=True):
            return FileManager(basevar=basevar)
        else:
            return RemoteFileManager(basevar=basevar)
    else:
        return FileManager(basevar=basevar)
