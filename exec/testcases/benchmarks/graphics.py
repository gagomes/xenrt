#
# XenRT: Test harness for Xen and the XenServer product family
#
# Graphics benchmarks
#
# Copyright (c) Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import sys, string, os, os.path, re, time, xml.dom.minidom, glob, json, numpy
from abc import ABCMeta
import xenrt
import testcases.benchmarks.workloads

class TCvideowin(xenrt.TestCaseWrapper):

    def __init__(self, tcid="TCvideowin"):
        xenrt.TestCaseWrapper.__init__(self,
                                       tcid=tcid,
                                       testname="videowin")

    def runViaDaemon(self, remote, arglist):

        # Extract onewin.exe and copy to the VM
        d = xenrt.TEC().tempDir()
        xenrt.getTestTarball("videowin", extract=True, copy=False, directory=d)
        xenrt.command("unzip %s/videowin/videowin.zip VideoWin/OneWin.exe "
                      "-d %s" % (d, d))
        workdir = remote.xmlrpcTempDir()
        remote.xmlrpcSendFile("%s/VideoWin/OneWin.exe" % (d),
                              "%s\\OneWin.exe" % (workdir))

        results = {}
        for iteration in range(9):
            xenrt.TEC().logdelimit("Iteration %u" % (iteration))

            # Run the test on the current video mode
            try:
                remote.xmlrpcRemoveFile("%s\\VideoLog.txt" % (workdir))
            except:
                pass
            try:
                remote.xmlrpcExec("cd %s\n%s\\OneWin.exe RUN" %
                                  (workdir, workdir),
                                  timeout=600)
            except xenrt.XRTFailure, e:
                # Returns non-zero for some reason
                xenrt.TEC().logverbose("OneWin.exe returned non-zero: %s" %
                                       (str(e)))

            # Process results.
            data = str(remote.xmlrpcReadFile("%s\\VideoLog.txt" % (workdir)))
            f = file("%s/VideoLog-%u.txt" %
                     (xenrt.TEC().getLogdir(), iteration), "w")
            f.write(data)
            f.close()

            # Find the header line
            lines = data.splitlines()
            headerindex = None
            headers = []
            for i in range(len(lines)):
                line = lines[i].strip()
                ll = line.split()
                if len(ll) > 0 and ll[0] == "Resolution":
                    headerindex = i
                    headers = ll[1:]
                    break
            if headerindex == None:
                raise xenrt.XRTError("Could not find result header line")

            # Walk through all lines after the header line looking for results
            for i in range(headerindex + 1, len(lines)):
                line = lines[i].strip()
                ll = line.split()
                if len(ll) == len(headers) + 3:
                    resolution = "%sx%sB%s" % (ll[0], ll[1], ll[2])
                    for j in range(len(headers)):
                        h = "%s_%s" % (resolution, headers[j])
                        v = float(ll[j+3])
                        if not results.has_key(h):
                            results[h] = []
                        results[h].append(v)

        # Record average results
        for h in results.keys():
            xenrt.TEC().logverbose("Results: %s %s" %
                                   (h, string.join(map(str, results[h]))))
            v = xenrt.util.mean(results[h])
            s = xenrt.util.stddev(results[h])
            self.tec.value(h, v)
            self.tec.value(h + "_stddev", s)

class GPUBenchmark(object):
    DEFAULT_RESOLUTION=None
    def __init__(self, guest):
        self.guest = guest
        self.workloadRef = None
        self.workloadProcessToKill = None
        self.logSuffix = None

    def _disablevsync(self):
        if not self.guest.xmlrpcFileExists("c:\\disablevsync\\disablevsync.exe"):
            self.guest.xmlrpcUnpackTarball("%s/disablevsync.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")
        self.guest.xmlrpcExec("c:\\disablevsync\\disablevsync.exe")

    def setLogSuffix(self, suffix):
        self.logSuffix = suffix

    def install(self):
        pass

    def prepare(self, params=None):
        self._processResolutions(params)
        try:
            self._disablevsync()
        except:
            xenrt.TEC().warning("Failed to disable vsync")

    def run(self, params=None):
        pass

    def getResults(self):
        pass

    def runAsWorkload(self, params=None):
        raise xenrt.XRTError("Not implemented")

    def getLogDir(self, dirName):
        if self.logSuffix:
            logpath = "%s/%s-%s" % (xenrt.TEC().getLogdir(), dirName, self.logSuffix)
        else:   
            logpath = "%s/%s" % (xenrt.TEC().getLogdir(), dirName)
        if not os.path.exists(logpath):
            os.makedirs(logpath)
        return logpath

    def checkWorkload(self):
        if not self.workloadRef:
            return
        if self.guest.xmlrpcPoll(self.workloadRef):
            try:
                raise xenrt.XRTFailure("Workload %s has died in %s" % (self.workloadProcessToKill, self.guest.name))
            finally:
                self.stopWorkload()

    def stopWorkload(self):
        if self.workloadProcessToKill:
            self.guest.xmlrpcKillAll(self.workloadProcessToKill)
        self.workloadProcessToKill = None
        self.workloadRef = None
            
    def _processResolutions(self, params):
        (x,y) = self.DEFAULT_RESOLUTION
        if params and params.has_key('screenres'):
            x = params['screenres']['x']
            y = params['screenres']['y']
        try:
            self.guest.setScreenResolution(x,y)
        except:
            xenrt.TEC().logverbose("qres failed try a reboot to fix the problem....")
            self.guest.reboot()
            self.guest.setScreenResolution(x,y)
            
        self.screenResolution = (x,y)
        if params and params.has_key('appres'):
            x = params['appres']['x']
            y = params['appres']['y']
        self.appResolution = (x,y)

    def _getScreenResolution(self):
        return self.screenResolution

    def _getAppResolution(self):
        return self.appResolution

class SPECViewPerf11(GPUBenchmark):

    SVP_PATH = "C:\\SPEC\\SPECgpc\\SPECviewperf\\viewperf\\viewperf11.0"
    DEFAULT_RESOLUTION=(1920,1080)


    # Command arguments are combined down the tree, working directories are overridden down the tree

    def _parseDoc(self, xmlStr):
        dom = xml.dom.minidom.parseString(xmlStr)
        for n in dom.childNodes:
            if n.nodeType == n.ELEMENT_NODE:
                if n.nodeName == "Benchmark":
                    return self._parseBenchmarkNode(n, "%SPECVIEWPERF%\\viewperf\\Viewperf.exe", "c:\\")
                    

    def _parseBenchmarkNode(self, node, curCommand, workingDir):
        cmds = []
        cmdroot = curCommand
        cmdroot += " %s" %  node.getAttribute("CommandArguments")
        newWorkingDir = node.getAttribute("WorkingDirectory")
        if newWorkingDir:
            workingDir = newWorkingDir
        for n in node.childNodes:
            if n.nodeType == n.ELEMENT_NODE:
                if n.nodeName == "Benchmark":
                    cmds.extend(self._parseBenchmarkNode(n, cmdroot, workingDir))
                elif n.nodeName == "Command":
                    cmds.append(self._parseCommandNode(n, cmdroot, workingDir))
        return cmds

    def _parseCommandNode(self, node, curCommand, workingDir):
        newWorkingDir = node.getAttribute("WorkingDirectory")
        if newWorkingDir:
            workingDir = newWorkingDir
        cmd = curCommand
        cmd += " %s" % node.getAttribute("Arguments")
        node.getAttribute("WorkingDirectory")
        workingDir = workingDir.replace("%SPECVIEWPERF%", self.SVP_PATH)
        workingDir = workingDir.replace("/","\\")
        cmd = cmd.replace("%SPECVIEWPERF%", self.SVP_PATH)
        cmd = cmd.replace("/","\\")
        return "cd %s\n%s" % (workingDir, cmd)


    def install(self):
        if not self.guest.xmlrpcDirExists(self.SVP_PATH):
            if self.guest.xmlrpcGetArch() == "x86":
                fname = "SPECviewperf11win32.exe"
            else:
                fname = "SPECviewperf11win64.exe"

            self.guest.xmlrpcFetchFile("%s/specviewperf/%s" % (xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP"), fname), "c:\\%s" % fname)
            self.guest.xmlrpcExec("c:\\%s /S /NCRC" % fname, timeout=1800)
            self.guest.xmlrpcExec("del c:\\%s" % fname)

    def prepare(self, params=None):
        xmlStr = self.guest.xmlrpcReadFile("%s\\viewperf\\SPECviewperf11.xml" % self.SVP_PATH)
        # Parse all of the commands out of the SPECviewperf11.xml file and run them
        self.cmds = self._parseDoc(xmlStr)
        super(SPECViewPerf11, self).prepare(params)

    def run(self, params=None):
        (x,y) = self._getAppResolution()
        for c in self.cmds:
            self.guest.xmlrpcExec("%s -xws %d -yws %d" % (c,x,y), timeout=7200)

    def getResults(self):
        logpath = self.getLogDir("specviewperf")
        logpathhtml = "%s/%s" % (logpath, self.guest.name)
        if not os.path.exists(logpathhtml):
            os.makedirs(logpathhtml)
        d = xenrt.TempDirectory()
        
        self.guest.xmlrpcFetchRecursive("%s\\results" % self.SVP_PATH, d.path())
        respath = "%s/%s/results" % (d.path(), self.SVP_PATH.replace("\\","/")[3:])

        # Save the results in a tar file, and also produce a JSON summary
        if not xenrt.TEC().lookup("OPTION_SAVE_SVP_GRABS", False, boolean=True):
            xenrt.util.command("rm -rf %s/*/grabs" % respath)
        xenrt.util.command("tar -cvzf %s/%s.tar.gz -C %s ./" % (logpath, self.guest.name, respath))
        xenrt.util.command("tar -xvzf %s/%s.tar.gz -C %s --exclude '*.txt' --exclude '*grabs*'" % (logpath, self.guest.name, logpathhtml))

        (x,y) = self._getAppResolution()
        gpu = self.guest.findGPUMake().split(None, 1)[1].strip()
        files = glob.glob("%s/*/viewperfresult.txt" % respath)
        results = {"resolution": {"x":x, "y":y}, "winversion": self.guest.distro, "gpu":gpu, "results": {}}
        for f in files:
            benchmark = f.split("/")[-2]
            results['results'][benchmark] = {"tests":{}}
            for l in file(f).xreadlines():
                if l[0] == "#":
                    continue
                if l[0] == "*": # Composite score lines begin with "*"
                    results['results'][benchmark]["score"] = l.split()[-1]
                else:
                    (test, weight, fps) = l.split()
                    results['results'][benchmark]["tests"][test] = {}
                    results['results'][benchmark]["tests"][test]["weight"]=weight
                    results['results'][benchmark]["tests"][test]["fps"]=fps
        
        f = open("%s/%s.json" % (logpath, self.guest.name), "w")
        f.write(json.dumps(results))
        f.close()
        return results

class _UnigineBenchmark(GPUBenchmark):
    __metaclass__ = ABCMeta
    
    DEFAULT_RESOLUTION=(1280,1024)

    PACKAGE=None
    BACKENDS=None
    BINARY=None

    def install(self):
        if not self.guest.xmlrpcDirExists("c:\\%s" % self.PACKAGE):
            self.guest.xmlrpcUnpackTarball("%s/%s.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE"), self.PACKAGE), "c:\\")

    def prepare(self, params=None):
        # Workaround: Unigine benchmarks produce very unreliable results if the
        # VM isn't rebooted before running them.
        # This change admittedly won't help assessing exhaustion effects for a
        # sequence of benchmarks, but it helps assessing a stable base line.
        self.guest.reboot()
        super(_UnigineBenchmark, self).prepare(params)

    def run(self, params=None):
        (x,y) = self._getAppResolution()
        for backend in self.BACKENDS.keys():
            b = self.BACKENDS[backend]
            self.guest.xmlrpcExec("cd c:\\%s\n%s.exe " \
                "-video_app %s -data_path ./ -sound_app null -engine_config " \
                "data/unigine.cfg -system_script %s/unigine.cpp " \
                "-video_mode -1 -video_fullscreen 0 -video_width %d " \
                "-video_height %d -extern_define PHORONIX > c:\\%s_%s.log" \
                    % (self.PACKAGE, self.BINARY, b, self.BINARY,
                       x, y, self.PACKAGE, b), timeout=3600)

    def getResults(self):
        logpath = self.getLogDir(self.PACKAGE)

        gpu = self.guest.findGPUMake().split(None, 1)[1].strip()
        (x,y) = self._getAppResolution()

        results = {"resolution": {"x":x, "y":y}, "winversion": self.guest.distro, "gpu":gpu, "results": {}}

        for backend in self.BACKENDS.keys():
            b = self.BACKENDS[backend]
            resultStr = self.guest.xmlrpcReadFile("c:\\%s_%s.log" % (self.PACKAGE, b))
            for l in resultStr.splitlines():
                m = re.match("^FPS:\t(.*)", l)
                if m:
                    results['results'][backend] = float(m.group(1))
                    
        f = open("%s/%s.json" % (logpath, self.guest.name), "w")
        f.write(json.dumps(results))
        f.close()
        return results

    def runAsWorkload(self, params=None):
        backend = "opengl"
        if params and params.has_key("backend"):
            backend = params['backend']
        self._processResolutions(params)

        (x,y) = self._getAppResolution()

        self.workloadRef = self.guest.xmlrpcStart("cd c:\\%s\n%s.exe " \
            "-video_app %s -data_path ./ -sound_app null -engine_config " \
            "data/unigine.cfg -system_script %s/unigine.cpp " \
            "-video_mode -1 -video_fullscreen 0 -video_width %d " \
            "-video_height %d -extern_define RELEASE" \
                % (self.PACKAGE, self.BINARY, backend, self.BINARY, x, y))

        self.workloadProcessToKill = "%s.exe" % self.BINARY

class UnigineTropics(_UnigineBenchmark):
    BACKENDS = {'opengl': 'opengl', 'directx10':'direct3d10', 'directx101':'direct3d11'}
    #BACKENDS = {'opengl': 'opengl', 'directx9': 'direct3d9', 'directx10':'direct3d10', 'directx101':'direct3d11'}
    PACKAGE = "uniginetropics"
    BINARY = "tropics"

class UnigineSanctuary(_UnigineBenchmark):
    BACKENDS = {'opengl': 'opengl', 'directx9': 'direct3d9', 'directx10':'direct3d10'}
    PACKAGE = "uniginesanctuary"
    BINARY = "sanctuary"
    
class WindowsExperienceIndex(GPUBenchmark):
    DEFAULT_RESOLUTION=(1280,1024)

    def install(self):
        self.wei = testcases.benchmarks.workloads.WindowsExperienceIndex(self.guest)
        self.wei.install()

    def run(self, params=None):
        self.wei.start()

        deadline = xenrt.util.timenow() + 1800

        while xenrt.util.timenow() < deadline:
            if not self.wei.checkRunning():
                break
            xenrt.sleep(30)

    def getResults(self):
        logpath = self.getLogDir("wei")

        self.wei.obtainResult()
        results = self.wei.analyseResult()

        gpu = self.guest.findGPUMake().split(None, 1)[1].strip()
        (x,y) = self._getAppResolution()

        resultsJSON = {"resolution": {"x":x, "y":y}, "winversion": self.guest.distro, "gpu":gpu, "results": {}}
        for r in results:
            (key, value) = r
            resultsJSON['results'][key] = float(value)

        f = open("%s/%s.json" % (logpath, self.guest.name), "w")
        f.write(json.dumps(resultsJSON))
        f.close()
        return resultsJSON

class Redway3DTurbine(GPUBenchmark):
    DEFAULT_RESOLUTION=(1280,1024)


    def __location(self):
        if self.guest.xmlrpcGetArch() == "x86":
            return "C:\\Program Files\\Redway3d - Turbine Demo"
        else:
            return "C:\\Program Files (x86)\\Redway3d - Turbine Demo"

    def install(self):
        if not self.guest.xmlrpcDirExists(self.__location()):
            self.guest.xmlrpcUnpackTarball("%s/redway3dturbine.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")
            ref = self.guest.xmlrpcStart("c:\\redway3dturbine\\turbineDemo.exe /S")
            deadline = xenrt.util.timenow() + 600

            while xenrt.util.timenow() < deadline:
                self.guest.xmlrpcKillAll("REDSystemCheckUtility.exe")
                if self.guest.xmlrpcPoll(ref):
                    break
                xenrt.sleep(10)

    def run(self, params=None):
        self.guest.xmlrpcExec("cd \"%s\\Win32\"\n\"%s\\Win32\\REDTurbineDemo.exe\" -bench" % (self.__location(), self.__location()), timeout=7200)

    def getResults(self, params=None):
        logpath = "%s/redway3dturbine" % (xenrt.TEC().getLogdir())
        if not os.path.exists(logpath):
            os.makedirs(logpath)
       
        
        resultsFile = self.guest.xmlrpcReadFile("%s\\Win32\\Redway3d_turbine_benchmark.txt" % self.__location())

        gpu = self.guest.findGPUMake().split(None, 1)[1].strip()
        results = {"winversion": self.guest.distro, "gpu": gpu, "results": {}}

        for l in [x.strip() for x in resultsFile.splitlines()]:
            if l.startswith("Replay"):
                continue
            if l == "":
                continue
            if l.startswith("Resolution"):
                m = re.match("Resolution = (\d+) x (\d+)", l)
                self.appResolution = (int(m.group(1)), int(m.group(2)))
            else:
                (test, result) = l.split(" = ", 1)
                results['results'][test] = float(result)

        (x,y) = self._getAppResolution()
        results['resolution'] = {"x": x, "y": y}
        
        f = open("%s/%s.json" % (logpath, self.guest.name), "w")
        f.write(json.dumps(results))
        f.close()
        return results

class WebGL(GPUBenchmark):
    DEFAULT_RESOLUTION=(1280,1024)

    def __init__(self, guest):
        super(WebGL, self).__init__(guest)
        self.chromeLocation = None

    def __chromeLocation(self):
        if not self.chromeLocation:
            self.chromeLocation = "%s\\Google\\Chrome" % self.guest.xmlrpcGetEnvVar("LOCALAPPDATA")
        return self.chromeLocation

    def install(self):
        if not self.guest.xmlrpcFileExists("%s\\Application\\chrome.exe" % (self.__chromeLocation())):
            self.guest.xmlrpcUnpackTarball("%s/googlechrome.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")
            self.guest.xmlrpcExec("c:\\googlechrome\\ChromeStandaloneSetup.exe")
            self.guest.xmlrpcKillAll("chrome.exe")
            self.guest.winRegAdd("HKLM", "SOFTWARE\\Policies\\Google\\Update", "AutoUpdateCheckPeriodMinutes", "DWORD", 0)
        if not self.guest.xmlrpcFileExists("c:\\webglaquarium\\aquarium\\aquarium.html"):
            self.guest.xmlrpcUnpackTarball("%s/webglaquarium.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")

    def prepare(self, params=None):
        super(WebGL, self).prepare(params)
        self.guest.xmlrpcStart("cd c:\\webglaquarium\npython -m SimpleHTTPServer")
        self.guest.xmlrpcExec("del \"%s\\User Data\\chrome_debug.log\"" % self.__chromeLocation())

    def run(self, params=None):
        (x,y) = self._getAppResolution()
        self.guest.xmlrpcStart("%s\\Application\\chrome.exe --enable-logging --ignore-gpu-blacklist --disable-gpu-vsync --window-size=%d,%d --app=\"http://localhost:8000/aquarium/aquarium.html\"" % (self.__chromeLocation(), x, y))
        xenrt.sleep(300)
        self.guest.xmlrpcKillAll("chrome.exe")

    def getResults(self):
        logpath = self.getLogDir("webglaquarium")
        
        resultStr = self.guest.xmlrpcReadFile("%s\\User Data\\chrome_debug.log" % (self.__chromeLocation()))

        readings = []

        for l in resultStr.splitlines():
            m = re.search("FPS Info:(\d+)", l)
            if m:
                readings.append(float(m.group(1)))

        fps = numpy.mean(readings)
                
        gpu = self.guest.findGPUMake().split(None, 1)[1].strip()
        (x,y) = self._getAppResolution()

        results = {"resolution": {"x":x, "y":y}, "winversion": self.guest.distro, "gpu":gpu, "results": {"fps": fps}}

        f = open("%s/%s.json" % (logpath, self.guest.name), "w")
        f.write(json.dumps(results))
        f.close()
        return results
