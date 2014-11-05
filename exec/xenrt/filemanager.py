
import sys, string, os.path, threading, os, shutil, tempfile, stat, hashlib
import time, httplib, urlparse, glob, re
import xenrt, xenrt.util

__all__ = ["getFileManager"]

fm = None

class FileNameResolver(object):
    def __init__(self, fn, multipleFiles=False):
        self.__url = fn
        self.__multiple = multipleFiles
        self.__singleWildcard = False
        self.__directory = False
        # This order is important. First we need to subst the variables, then add the input dir, then convert to HTTP.
        self.__resolveVariableSubstitutions()
        self.__resolveInputDir()
        self.__resolveHttpFetch()
        # Finally, we tidy up the path
        self.__removeMultipleSlashes()

        self.__localName = self.__url
        self.__resolveDirectory()
        self.__resolveWildCards()
        self.__resolveArchive()

    @property
    def url(self):
        return self.__url

    @property
    def localName(self):
        return self.__localName

    @property
    def directory(self):
        return self.__directory

    @property
    def multipleFiles(self):
        return self.__multiple

    @property
    def singleFileWithWildcard(self):
        return self.__singleWildcard
        
    def __resolveDirectory(self):
        if self.__localName.endswith("/"):
            self.__multiple = True
            self.__directory = True

    def __resolveWildCards(self):
        if "*" in self.localName and not self.__multiple:
            self.__singleWildcard = True
        self.__localName = self.__localName.replace("*", "WILDCARD")

    def __resolveArchive(self):
        if self.__directory:
            self.__localName = "%sxrtpackeddir" % self.__localName
        if self.__multiple:
            self.__localName = "%s.tar.gz" % self.__localName

    def __resolveVariableSubstitutions(self):
        """If the path contains ${VARIABLE}, subsitute with the xenrt variable ${VARIABLE}"""

        # First do a special case for INPUTDIR, as that may be overridden on a thread basis
        if re.search("\${INPUTDIR}", self.__url):
            self.__url = re.sub("\${INPUTDIR}", xenrt.TEC().getInputDir(), self.__url)

        # Now generic variables
        self.__url = re.sub("\${(.*?)}", lambda x: xenrt.TEC().lookup(x.group(1)), self.__url)

    def __resolveInputDir(self):
        """If the file doesn't begin with an HTTP path or a / indicating a root directory, it's relative to the input dir"""
        if    not self.__url.startswith("http://") \
          and not self.__url.startswith("https://") \
          and not self.__url.startswith("/"):
            self.__url = "%s/%s" % (xenrt.TEC().getInputDir(), self.__url)
        pass

    def __resolveHttpFetch(self):
        """If the file doesn't begin with an HTTP path, it needs the HTTP exporter prepending"""
        if    not self.__url.startswith("http://") \
          and not self.__url.startswith("https://"):
            self.__url = "%s/%s" % (xenrt.TEC().lookup("FORCE_HTTP_FETCH"), self.__url)

    def __removeMultipleSlashes(self):
        """Some of these substitutions tends to leave double or triple-slashes. Replace all of them that aren't protocol separators"""
        while re.search("[^:]//", self.__url):
            self.__url = re.sub("([^:])//", "\\1/", self.__url)

class FileManager(object):
    def __init__(self):
        self.cachedir = xenrt.TempDirectory().path()
        self.lock = threading.Lock()

    def getFile(self, filename, multiple=False):
        try:
            xenrt.TEC().logverbose("getFile %s" % filename)
            self.lock.acquire()
            sharedLocation = None
            fnr = FileNameResolver(filename, multiple)
            url = fnr.url
            localName = fnr.localName
            cache = self._availableInCache(localName)
            if cache:
                return cache

            else:
                sharedLocation = self._sharedCacheLocation(localName)
                perJobLocation = self._perJobCacheLocation(localName)
                f = open("%s.fetching" % sharedLocation, "w")
                f.write(str(xenrt.GEC().jobid()) or "nojob")
                f.close()
                
                if multiple:
                    self.__getMultipleFiles(url, sharedLocation)
                elif fnr.directory:
                    self.__getDirectory(url, sharedLocation)
                elif fnr.singleFileWithWildcard:
                    self.__getSingleFileWithWildcard(url, sharedLocation)
                else:
                    self.__getSingleFile(url, sharedLocation)
                os.chmod(sharedLocation, stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)
                os.link(sharedLocation, perJobLocation) 

                return perJobLocation
        except Exception, e:
            xenrt.TEC().logverbose("Warning - could not fetch %s - %s" % (filename, e))
            return None
        finally:
            if sharedLocation:
                os.unlink("%s.fetching" % sharedLocation)
            self.lock.release()

    def __getSingleFile(self, url, sharedLocation):
        try:
            xenrt.util.command("wget%s -nv '%s' -O '%s.part'" % (self.__proxyflag, url, sharedLocation))
        except:
            os.unlink('%s.part' % sharedLocation)
            raise
        else:
            os.rename('%s.part' % sharedLocation, sharedLocation)

    def __getSingleFileWithWildcard(self, url, sharedLocation):
        try:
            t = xenrt.resources.TempDirectory()
            splitpoint = 0
            ss = url.split("/")
            for s in ss:
                if "*" in s:
                    break
                splitpoint += 1
                    
            xenrt.util.command("wget%s -nv '%s' -P '%s' --recursive --accept '%s' -nd -l 1" % (self.__proxyflag, "/".join(ss[0:splitpoint]), t.dir, "/".join(ss[splitpoint:])))
            fetched = glob.glob("%s/*" % t.dir)
            os.rename(fetched[0], sharedLocation)
        finally:
            t.remove()

    def __getDirectory(self, url, sharedLocation):
        try:
            t = xenrt.resources.TempDirectory()
            u = urlparse.urlparse(url)
            cutdirs = len(u.path.split("/")) - 2 # Remove beginning and end items
            xenrt.util.command("wget%s -nv '%s' -P '%s' --recursive -nH -np --cut-dirs %d" % (self.__proxyflag, url, t.dir, cutdirs), ignoreerrors=True)
            xenrt.util.command("cd %s && tar -cvzf %s *" % (t.dir, sharedLocation))
        finally:
            t.remove()

    def __getMultipleFiles(self, url, sharedLocation, maxDepth=2):
        """
        Fetch a collection of files from a URL using wget
        depthOfSearch is how far down the URL tree to look for files - default is 2
        """
        try:
            t = xenrt.resources.TempDirectory()
            fetchPatterns= [url.split("/")[-1], url.split("/")[-1] + ".[0-9]*"]
            xenrt.util.command("wget%s -nv '%s' -P '%s' --recursive --accept '%s' -nd -l %d" % (self.__proxyflag, "/".join(url.split("/")[0:-1]), t.dir, ",".join(fetchPatterns), maxDepth))
            fetched = glob.glob("%s/*" % t.dir)
            fileList = " ".join(fetched)
            xenrt.TEC().logverbose( "Fetched files: %s"  % fileList)
            xenrt.archive.TarGzArchiver().create(sharedLocation, fileList)
            t.remove()
        except Exception, e:
            xenrt.TEC().logverbose("HTTP multiple fetchFile exception: %s" % (str(e)))
            return None
        return True
    
    @property
    def __proxyflag(self):
        proxy = xenrt.TEC().lookup("HTTP_PROXY", None)
        if proxy:
            return " -e http_proxy=%s" % proxy
        else:
            return ""

    def _filename(self, filename):
        return filename.rstrip("/").split("/")[-1]

    def _sharedCacheLocation(self, filename):
        dirname = "%s/%s" % (xenrt.TEC().lookup("FILE_MANAGER_CACHE"), hashlib.sha256(filename).hexdigest())
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        return "%s/%s" % (dirname, self._filename(filename))

    def _perJobCacheLocation(self, filename):
        dirname = "%s/%s" % (self.cachedir, hashlib.sha256(filename).hexdigest())
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        return "%s/%s" % (dirname, self._filename(filename))

    def removeFromCache(self, filename):
        sharedLocation = self._sharedCacheLocation(filename)
        if os.path.exists(sharedLocation):
            xenrt.TEC().logverbose("Found %s in cache" % sharedLocation)
            shutil.rmtree(sharedLocation) 

    def _availableInCache(self, filename):
        # First try the per-job cache
        perJobLocation = self._perJobCacheLocation(filename)
        sharedLocation = self._sharedCacheLocation(filename)
        if os.path.exists(perJobLocation):
            xenrt.TEC().logverbose("Found file in per-job cache")
            return perJobLocation

        # If it's not in the per-job cache, try the global cache
        # First, if someone else is fetching, wait until fetching is complete
        if os.path.exists("%s.fetching" % sharedLocation):
            xenrt.TEC().logverbose("File is fetching - waiting")
            while True:
                if not os.path.exists("%s.fetching" % sharedLocation):
                    break
                xenrt.sleep(15)

        # Now check whether the file is available

        if os.path.exists(sharedLocation):
            # If it is, hardlink it to the per-job cache
            xenrt.TEC().logverbose("Found file in shared cache")
            os.link(sharedLocation, perJobLocation) 

            # Return the cache location in the per-job cache
            return perJobLocation
        else:
            return None

    def cleanup(self, days=None):
        if not days:
            days=7

        sharedDir = xenrt.TEC().lookup("FILE_MANAGER_CACHE")

        entries = os.listdir(sharedDir)

        toRemove = []
        for entry in entries:
            cachepath = "%s/%s" % (sharedDir, entry)
            mtime = os.path.getmtime(cachepath)
            if (time.time() - mtime) > (days*24*3600):
                xenrt.TEC().logverbose("Removing %s" % cachepath)
                shutil.rmtree(cachepath)

    def fileExists(self, filename):
        try:
            xenrt.TEC().logverbose("fileExists %s" % filename)
            self.lock.acquire()
            filename = FileNameResolver(filename).url
            if self._availableInCache(filename):
                return True
            return self._isFetchable(filename)
        finally:
            self.lock.release()
    
    def _isFetchable(self, filename):
        # Split remote in to host and path
        xenrt.TEC().logverbose("Attempting to check response for %s" % filename)
        u = urlparse.urlparse(filename)
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

def getFileManager():
    global fm
    if not fm:
        fm = FileManager()
    return fm
