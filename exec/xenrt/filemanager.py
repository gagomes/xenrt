
import sys, string, os.path, threading, os, shutil, tempfile, stat, hashlib
import time, urlparse, glob, re, requests
import xenrt, xenrt.util, xenrt.ssh

__all__ = ["getFileManager"]

fm = None

class FileNameResolver(object):
    def __init__(self, fn, multipleFiles=False):
        self.__fn = fn
        self.__url = fn
        self.__multiple = multipleFiles
        self.__singleWildcard = False
        self.__directory = False
        # This order is important. First we need to subst the variables, then add the input dir, then convert to HTTP.
        self.__resolveVariableSubstitutions()
        self.__resolveInputDir()
        self.__resolveHttpFetch()
        self.__resolveLatest()
        self.__useArchiveIfNeeded()
        # Finally, we tidy up the path
        self.__removeMultipleSlashes()

        self.__localName = self.__url
        self.__resolveDirectory()
        self.__resolveWildCards()
        self.__resolveArchive()

    @property
    def fn(self):
        return self.__fn

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

    @property
    def isSimpleFile(self):
        return not (self.multipleFiles or self.singleFileWithWildcard or self.directory)
        
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
        self.__url = re.sub("\${(.*?)}", lambda x: xenrt.TEC().lookup(x.group(1), None), self.__url)

    def __resolveInputDir(self):
        """If the file doesn't begin with an HTTP path or a / indicating a root directory, it's relative to the input dir"""
        if    not self.__url.startswith("http://") \
          and not self.__url.startswith("https://") \
          and not self.__url.startswith("/"):
            self.__url = "%s/%s" % (xenrt.TEC().getInputDir(), self.__url)
        pass

    def __resolveLatest(self):
        m = re.match("(.+?)/([^/]*latest)/(.+)", self.__url)
        if m:
            try:
                r = requests.get("%s/%s/manifest" % (m.group(1), m.group(2)))
                r.raise_for_status()
                buildnum = [x.strip().split()[-1] for x in r.content.splitlines() if x.startswith("@install-image")][0]
                self.__url = "%s/%s/%s" % (m.group(1), buildnum, m.group(3))
            except Exception, e:
                xenrt.TEC().logverbose("Warning, could not determine build number for /latest - error: %s" % str(e))

    def __resolveHttpFetch(self):
        """If the file doesn't begin with an HTTP path, it needs the HTTP exporter prepending"""
        if    not self.__url.startswith("http://") \
          and not self.__url.startswith("https://"):
            self.__url = "%s/%s" % (xenrt.TEC().lookup("FORCE_HTTP_FETCH"), self.__url)

    def __removeMultipleSlashes(self):
        """Some of these substitutions tends to leave double or triple-slashes. Replace all of them that aren't protocol separators"""
        while re.search("[^:]//", self.__url):
            self.__url = re.sub("([^:])//", "\\1/", self.__url)

    def __useArchiveIfNeeded(self):
        
        rootBuildPath = "/usr/groups/xen/carbon/"
        rootArchivePath = "/nfs/archive/builds/carbon/"

        m = re.match("(.*%s.+?/\d+)/.*" % rootBuildPath, self.__url)
        if not m:
            return
        buildDir = m.group(1)
        archiveDir = buildDir.replace(rootBuildPath, rootArchivePath)

        if not xenrt.isUrlFetchable(buildDir) and xenrt.isUrlFetchable(archiveDir):
            self.__url = self.__url.replace(rootBuildPath, rootArchivePath)

class FileManager(object):
    def __init__(self):
        self.cachedir = xenrt.TempDirectory().path()
        self.lock = threading.Lock()
        self.defaultFetchTimeout = 3600
        self.externalFetchTimeout = 6 * 3600

    def getFile(self, filename, multiple=False, replaceExistingIfDiffers=False):
        try:
            xenrt.TEC().logverbose("getFile %s" % filename)
            self.lock.acquire()
            sharedLocation = None
            isUsingExternalCache = False
            fnr = FileNameResolver(filename, multiple)
            url = fnr.url
            localName = fnr.localName
            cache = self.__availableInCache(fnr, replaceExistingIfDiffers=replaceExistingIfDiffers)
            if cache:
                return cache

            else:
                sharedLocation = self._sharedCacheLocation(localName)
                # Check file size and decide which global cache to use. If file size is greater than
                # FILE_SIZE_CACHE_LIMIT, we cache file on external storage.
                try:
                    fileSizeThreshold = float(xenrt.TEC().lookup("FILE_SIZE_CACHE_LIMIT", str(1 * xenrt.GIGA)))
                    if fnr.isSimpleFile:
                        r = requests.head(fnr.url, allow_redirects=True)
                        if r.status_code == 200 and 'content-length' in r.headers and \
                            float(r.headers['content-length']) > fileSizeThreshold:
                            xenrt.TEC().logverbose("Using external cache")
                            sharedLocation = self._externalCacheLocation(localName)
                            isUsingExternalCache = True
                except Exception, e:
                    xenrt.TEC().warning('Reverting:Using internal shared cache. File Manager failed: %s' % e)

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
                elif filename.startswith("sftp://"):
                    self.__getSingleFileViaSftp(filename, sharedLocation)
                else:
                    self.__getSingleFile(url, sharedLocation, isUsingExternalCache)
                os.chmod(sharedLocation, stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)

                if isUsingExternalCache:
                    os.symlink(sharedLocation, perJobLocation)
                else:
                    os.link(sharedLocation, perJobLocation)
                return perJobLocation
        except Exception, e:
            xenrt.TEC().logverbose("Warning - could not fetch %s - %s" % (filename, e))
            return None
        finally:
            if sharedLocation:
                os.unlink("%s.fetching" % sharedLocation)
            self.lock.release()

    def __getSingleFile(self, url, sharedLocation, isUsingExternalCache=False):
        try:
            # Increase timeout if using external nfs.
            timeout = self.externalFetchTimeout if isUsingExternalCache else self.defaultFetchTimeout
            xenrt.util.command("wget%s -nv '%s' -O '%s.part'" % (self.__proxyflag, url, sharedLocation), timeout=timeout)
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
                    
            xenrt.util.command("wget%s -nv '%s' -P '%s' --recursive --accept '%s' -nd -l 1 -H" % (self.__proxyflag, "/".join(ss[0:splitpoint]), t.dir, "/".join(ss[splitpoint:])))
            fetched = glob.glob("%s/*" % t.dir)
            os.rename(fetched[0], sharedLocation)
        finally:
            t.remove()

    def __getDirectory(self, url, sharedLocation):
        try:
            t = xenrt.resources.TempDirectory()
            u = urlparse.urlparse(url)
            cutdirs = len(u.path.split("/")) - 2 # Remove beginning and end items
            xenrt.util.command("wget%s -H -nv '%s' -P '%s' --recursive -nH -np --cut-dirs %d" % (self.__proxyflag, url, t.dir, cutdirs), ignoreerrors=True)
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
            xenrt.util.command("wget%s -H -nv '%s' -P '%s' --recursive --accept '%s' -nd -l %d" % (self.__proxyflag, "/".join(url.split("/")[0:-1]), t.dir, ",".join(fetchPatterns), maxDepth))
            fetched = glob.glob("%s/*" % t.dir)
            fileList = " ".join(fetched)
            xenrt.TEC().logverbose( "Fetched files: %s"  % fileList)
            xenrt.archive.TarGzArchiver().create(sharedLocation, fileList)
            t.remove()
        except Exception, e:
            xenrt.TEC().logverbose("HTTP multiple fetchFile exception: %s" % (str(e)))
            return None
        return True

    def __getSingleFileViaSftp(self, file, sharedLocation):
        """
        Fetch a file which is accessible using ssh rather than web url
        """
        parsed = urlparse.urlparse(file)
        try:
            sftp = xenrt.ssh.SFTPSession(ip=parsed.hostname, username=parsed.username, password=parsed.password, level=xenrt.RC_FAIL,port=(parsed.port or 22))
            sftp.copyFrom(parsed.path, '%s.part' % sharedLocation)
            sftp.close()
        except:
            os.unlink('%s.part' % sharedLocation)
            raise
        else:
            os.rename('%s.part' % sharedLocation, sharedLocation)

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

    def _externalCacheLocation(self, filename, ignoreError=False):
        try:
            cachedir=xenrt.TEC().lookup("FILE_MANAGER_CACHE_NFS")
            if os.path.exists(cachedir) and xenrt.command("stat -f -c %%T %s" % cachedir, nolog=True).strip() == "nfs":
                dirname = "%s/%s" % (cachedir, hashlib.sha256(filename).hexdigest())
                if not os.path.exists(dirname):
                    os.makedirs(dirname)
                return "%s/%s" % (dirname, self._filename(filename))
            elif os.path.exists(cachedir):
                raise xenrt.XRTError("External cache directory exists but is not external storage.")
        except Exception, e:
            if not ignoreError:
                raise xenrt.XRTError("_externalCacheLocation: %s" % str(e))
        return None

    def removeFromCache(self, filename):
        fnr = FileNameResolver(filename, False)
        url = fnr.url
        globalCaches = []
        # try for both, filename and resolved filename
        for f in [filename, url]:
            globalCaches.append(self._sharedCacheLocation(f))
            externalLocation = self._externalCacheLocation(f, ignoreError=True)
            if externalLocation: 
                globalCaches.append(externalLocation)

        for cache in globalCaches:
            if os.path.exists(cache):
                xenrt.TEC().logverbose("Found %s in cache" % cache)
                os.unlink(cache)
                return

    def __availableInCache(self, fnr, replaceExistingIfDiffers=False):

        filename = fnr.localName
        perJobLocation = self._perJobCacheLocation(filename)
        globalCaches = [self._sharedCacheLocation(filename)]
        externalLocation = self._externalCacheLocation(filename, ignoreError=True)
        if externalLocation: 
            globalCaches.append(externalLocation)

        # First try the per-job cache
        if os.path.exists(perJobLocation):
            xenrt.TEC().logverbose("Found file in per-job cache")
            return perJobLocation

        # If it's not in the per-job cache, try the global cache(s)
        ## First, if someone else is fetching, wait until fetching is complete
        for cache in globalCaches:
            if os.path.exists("%s.fetching" % cache):
                xenrt.TEC().logverbose("File is fetching - waiting")
                if cache == externalLocation:
                    deadline = xenrt.util.timenow() + self.externalFetchTimeout
                else:
                    deadline = xenrt.util.timenow() + self.defaultFetchTimeout
                while xenrt.util.timenow() < deadline:
                    try:
                        with open("%s.fetching" % cache) as f:
                            job = f.read().strip()
                            if job != "nojob":
                                # Check if the job is still running
                                j = xenrt.GEC().dbconnect.api.get_job(int(job))
                                if j['rawstatus'] == "done" or j['params'].get('DEAD_JOB') == "yes":
                                    os.unlink("%s.fetching" % cache)
                                    break
                    except Exception, e:
                        xenrt.TEC().logverbose("Warning: exception %s raised when checking fetching file" % str(e))
                        if not os.path.exists("%s.fetching" % cache):
                            break
                        raise 
                    xenrt.sleep(15)

                # we need to raise an alarm if any fetching file is not deleted.
                if xenrt.util.timenow() > deadline:
                    raise xenrt.XRTError("found %s.fetching, file exceeds its max possible download duration." % cache)

            # Now check whether the file is available
            if os.path.exists(cache):
                # If it is, hardlink it to the per-job cache
                xenrt.TEC().logverbose("Found file in cache : %s" % cache)

                if fnr.isSimpleFile:
                    # Check the content length matches (i.e. the file hasn't been updated underneath us)
                    expectedLength = None
                    try:
                        r = requests.head(fnr.url, allow_redirects=True)
                        # We only trust the content-length if we got a 200 code, and the length is
                        # >10M, this is to avoid situations where we have a script providing the
                        # file where a HEAD request will give the size of the script not the file
                        # it provides
                        if r.status_code == 200 and 'content-length' in r.headers and \
                           r.headers['content-length'] > (10 * xenrt.MEGA):
                            expectedLength = int(r.headers['content-length'])
                    except:
                        # File is currently not available for some reason, still valid to use it from the cache
                        pass

                    if expectedLength:
                        s = os.stat(cache)
                        if s.st_size != expectedLength:
                            if replaceExistingIfDiffers:
                                self.removeFromCache(filename)
                                return None
                            raise xenrt.XRTError("found in global cache, but content-length (%d) differs from original (%d)" % (s.st_size, expectedLength))

                if cache == externalLocation:
                    os.symlink(cache, perJobLocation)
                else:
                    os.link(cache, perJobLocation)
                # Return the cache location in the per-job cache
                return perJobLocation

        # we reached till here, means file is not in cache.
        return None

    def cleanup(self, days=None):
        if not days:
            days=7

        for sharedDir in [xenrt.TEC().lookup("FILE_MANAGER_CACHE"), xenrt.TEC().lookup("FILE_MANAGER_CACHE_NFS")]:
            if os.path.exists(sharedDir):
                entries = os.listdir(sharedDir)
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
            fnr = FileNameResolver(filename)
            if self.__availableInCache(fnr):
                return True
            return xenrt.isUrlFetchable(fnr.url)
        finally:
            self.lock.release()

def getFileManager():
    global fm
    if not fm:
        fm = FileManager()
    return fm
