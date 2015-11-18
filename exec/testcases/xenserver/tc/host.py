#
# XenRT: Test harness for Xen and the XenServer product family
#
# Host standalone testcases
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy, tarfile, os, os.path
import xenrt, xenrt.lib.xenserver
import datetime
import itertools, functools
from xenrt.lazylog import step, comment, log

class VersionChecks(xenrt.TestCase):
    # TC-27139
    '''early warning system that checks version details are correct for the preflight checks'''

    def __init__(self,tcid=None, anon=False):
        super(VersionChecks,self).__init__(tcid,anon)
        self.__pass = False
        self.__count = 0

    def compare(self, conRet, compareTo, file,host):
        if conRet == compareTo:
            log(file + " version: " + conRet + " is correct")
        else:
            log("version details wrong(%s) in %s" % (conRet, file))
            host.execdom0("cat %s" % file)
            self.__pass = False
            self.__count += 1

    def run(self, arglist):
        host = self.getDefaultHost()

        revision = host.productRevision
        version = revision.split("-")[0]
        build = revision.split("-")[1]

        redHatVer = host.execdom0("cat /etc/redhat-release").rstrip('\n')
        redHatVer = redHatVer[18:18+len(version)]
        self.compare(redHatVer, version,"/etc/redhat-release",host)

        consoleVer = host.execdom0("grep \"Citrix XenServer Host\" /etc/issue").rstrip('\n')
        consoleVer = consoleVer[22:]
        self.compare(consoleVer,revision, "/etc/issue and on console",host)

        readMeVer = host.execdom0("grep -o -P \"\d\.\d+\.\d+\" /Read_Me_First.html").rstrip('\n').split()
        for r in readMeVer:
            self.compare(r,version, "/Read_Me_First.html",host)

        citrixIndexVer = host.execdom0("grep -o -P \"\d\.\d+\.\d+\" /opt/xensource/www/Citrix-index.html").rstrip('\n').split()
        self.compare(citrixIndexVer[0],version, "/opt/xensource/www/Citrix-index.html",host)
        self.compare(citrixIndexVer[1],version, "/opt/xensource/www/Citrix-index.html",host)

        indexVer = host.execdom0("grep -o -P \"\d\.\d+\.\d+\" /opt/xensource/www/index.html").rstrip('\n').split()
        self.compare(indexVer[0],version, "/opt/xensource/www/index.html",host)
        self.compare(indexVer[1],version, "/opt/xensource/www/index.html",host)

        if not self.__pass:
            raise xenrt.XRTFailure("%i incorrect entries logged above" % self.__count)


class TC6858(xenrt.TestCase):
    """Veryify KERNEL_VERSION in /etc/xensource-inventory matches the
    running dom0 kernel"""

    def run(self, arglist):
        host = self.getDefaultHost()

        # CA-24161 Skip this test on hosts with patches
        patches = host.minimalList("patch-list")
        if len(patches) > 0:
            xenrt.TEC().skip("CA-24161 Do not check on patched host")
            return
        
        actual = host.execdom0("uname -r").strip()
        inv = host.getInventoryItem("KERNEL_VERSION")
        if inv != actual:
            inv = host.getInventoryItem("LINUX_KABI_VERSION")
            if inv != actual:
                raise xenrt.XRTFailure("Running dom0 kernel %s does not match %s "
                                       "in /etc/xensource-inventory" %
                                       (actual, inv))
        xenrt.TEC().comment("Domain-0 kernel %s" % (actual))

class TC5792(xenrt.TestCase):
    """Execute xen-bugtool in Domain-0"""
    def run(self, arglist):
        host = self.getDefaultHost()
        data = host.execdom0("/usr/sbin/xen-bugtool -y")
        r = re.search(r"Writing tarball (\S+)", data)
        if not r:
            raise xenrt.XRTFailure("xen-bugtool did not report the tarball "
                                   "path")
        tarball = r.group(1)
        if host.execdom0("test -e %s" % (tarball), retval="code") != 0:
            raise xenrt.XRTFailure("Output tarball %s does not exist" %
                                   (tarball))

        files = host.execdom0("tar -jtf %s" % (tarball))
        for path in ['/var/log/xensource.log', '/var/log/messages']:
            if not re.search("%s$" % (path), files, re.MULTILINE):
                raise xenrt.XRTFailure("xen-bugtool tarball does not contain "
                                       "%s" % (path))
class TC9988(xenrt.TestCase):
    """Verify that the csl_log.out file from a bug-tool is non-zero length"""
    def run(self, arglist):
        host = self.getDefaultHost()
        cslgsr = host.execdom0("xe sr-list type=cslg")
        if not cslgsr:
            raise xenrt.XRTFailure("Prerequisite Failure: there is no CSLG-SR...")
        data = host.execdom0("/usr/sbin/xen-bugtool -y")
        r = re.search(r"Writing tarball (\S+)", data)
        if not r:
            raise xenrt.XRTFailure("xen-bugtool did not report the tarball "
                                   "path")
        tarball = r.group(1)
        if host.execdom0("test -e %s" % (tarball), retval="code") != 0:
            raise xenrt.XRTFailure("Output tarball %s does not exist" %
                                   (tarball))
        cslLogTxt = host.execdom0("tar -jtvf %s | grep csl_log " % (tarball))
        r = re.search('([0-9]+)', cslLogTxt)
        if not r:
            raise xenrt.XRTFailure("Unable to get the size of the CSL_Log.out file from the BugTool")
        cslLogSize = int(r.group(1))
        if cslLogSize == 0:
            raise xenrt.XRTFailure("CSL Log file was of Zero Bites")
        
        
    

class TC6859(xenrt.TestCase):
    """Basic operation of host-get-system-status using the off-host CLI"""

    FORMATS = {"tar.bz2": ("bzip2 compressed data", False),
               "zip": ("Zip archive data", False),
               "tar": ("tar archive", True)}

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
    
    def run(self, arglist):
        cli = self.host.getCLIInstance()
        d = self.tec.tempDir()

        for format in self.FORMATS.keys():
            filename = "%s/system-status.%s" % (d, format)
            desc, oem = self.FORMATS[format]

            
            # Get the status report
            args = []
            args.append("output=%s" % (format))
            args.append("filename=%s" % (filename))
            args.append("uuid=%s" % (self.host.getMyHostUUID()))
            cli.execute("host-get-system-status", string.join(args))

            # Check the file is of the expected type
            data = xenrt.command("file %s" % (filename))
            if not re.search(desc, data):
                raise xenrt.XRTFailure("Status report file does not appear "
                                       "to be of type '%s'" % (format),
                                       data)

class TC8212(TC6859):
    """Operation of host-get-system-status of a slave using the off-host CLI"""

    def prepare(self, arglist):
        h = self.getDefaultHost()
        if not h.pool:
            raise xenrt.XRTError("Host in not in a pool")
        slaves = h.pool.getSlaves()
        if len(slaves) == 0:
            raise xenrt.XRTError("No slaves in pool")
        self.host = slaves[0]

class TC8810(xenrt.TestCase):
    """host-get-system-status for a slave should return a bugtool for the slave"""

    def prepare(self, arglist):
        h = self.getDefaultHost()
        if not h.pool:
            raise xenrt.XRTError("Host in not in a pool")
        slaves = h.pool.getSlaves()
        if len(slaves) == 0:
            raise xenrt.XRTError("No slaves in pool")
        self.host = slaves[0]

    def run(self, arglist):
        cli = self.host.getCLIInstance()
        d = self.tec.tempDir()
        filename = "%s/system-status.tar" % (d)
        
        # Get the status report
        args = []
        args.append("output=tar")
        args.append("filename=%s" % (filename))
        args.append("uuid=%s" % (self.host.getMyHostUUID()))
        cli.execute("host-get-system-status", string.join(args))

        # Extract the inventory file
        t = tarfile.open(filename, "r")
        try:
            n = t.next()
            stem = n.name.split("/")[0]
            f = t.extractfile("%s/etc/xensource-inventory" % (stem))
            try:
                data = f.read()
            finally:
                f.close()
            r = re.search(r"INSTALLATION_UUID='(\S+)'", data)
            u = r.group(1)
            if u != self.host.getMyHostUUID():
                raise xenrt.XRTFailure("bugtool returned by slave system "
                                       "status report is from a different "
                                       "host", u)
        finally:
            t.close()

class TC6641(xenrt.TestCase):
    """Tests very basic functionality of the xentrace debugging tool."""
    def run(self, arglist):
        host = self.getDefaultHost()
        duration = 30

        outfile = host.execdom0("mktemp /tmp/xentrace.XXX").strip()
        xenrt.TEC().logverbose("Starting %ss xentrace." % (duration))
        host.execdom0("xentrace -D -e all %s &> /dev/null < /dev/null &" % (outfile))
        g = host.createGenericEmptyGuest()
        g.start()
        g.shutdown(force=True)
        g.uninstall()
        time.sleep(duration)
        xenrt.TEC().logverbose("Attempting to kill xentrace.")
        host.execdom0("killall xentrace ; exit 0")
        time.sleep(5)
        if not host.execdom0("ps ax | grep xentrace | grep -v \"grep\"", retval="code"):
            raise xenrt.XRTFailure("xentrace still seems to be running.")
        if host.execdom0("ls %s" % (outfile), retval="code"):
            raise xenrt.XRTFailure("Trace doesn't seem to be there.")
        bytes = int(host.execdom0("du %s | cut -f 1" % (outfile)).strip())
        if bytes == 0:
            raise xenrt.XRTFailure("Trace is empty.")
        xenrt.TEC().comment("Generated a %skb trace." % (bytes))
        host.execdom0("rm -f %s" % (outfile))

class TC8101(xenrt.TestCase):
    """Check HAP is enabled on AMD processors with this feature."""
    
    MESSAGES = ["Hardware Assisted Paging \(HAP\) detected","Hardware Assisted Paging detected and enabled"]
    CPUTYPE = "svm"
    messageFound = False

    def run(self, arglist):
        host = self.getDefaultHost()
        host.reboot()
        cpuinfo = host.execdom0("cat /proc/cpuinfo")
        if not re.search(self.CPUTYPE, cpuinfo):
            raise xenrt.XRTError("Not running on %s hardware" % (self.CPUTYPE))

        dmesg = host.execdom0("xe host-dmesg uuid=%s" % (host.getMyHostUUID()))
        for m in self.MESSAGES:
            xenrt.TEC().logverbose("Searching for %s" %(m) )
            if re.search(m, dmesg, re.MULTILINE):
                xenrt.TEC().logverbose("HAP found : %s" %(m))
                messageFound = True
                break

        if not messageFound:
            raise xenrt.XRTFailure("Message not seen in Xen messages: %s" %(m))


class TC8446(TC8101):
    """Check EPT is enabled on Intel processors with this feature."""
    
    MESSAGES = ["Hardware Assisted Paging detected and enabled",
                "VMX: EPT is available"]
    CPUTYPE = "vmx"
    
class TC13818(TC8101):
    """Check EPT is enabled on Intel processors with this feature. (Boston message)"""
    
    MESSAGES = ["Hardware Assisted Paging detected and enabled",
                " - Extended Page Tables \(EPT\)"]
    CPUTYPE = "vmx"
    
class TC8340(TC8101):
    """Check HAP is disabled on AMD processors with this feature."""

    MESSAGES = ["Hardware Assisted Paging disabled"]

class TC8213(xenrt.TestCase):
    """An idle host should have a low dom0 load."""

    def checkLoad(self):
        data = self.host.execdom0("uptime")
        match = re.search(r"load average:\s+(?P<load>[0-9\.]+)", data)
        if not match:
            raise xenrt.XRTError("Could not parse uptime output", data)
        return float(match.group("load"))

    def getProcessUsage(self, pid):
        data = self.host.execdom0("cat /proc/%s/stat" % (pid)).strip()
        return tuple(map(int, data.split()[13:15]))

    def getUsage(self):
        pids = self.host.execdom0("ps ax -o pid=").split()
        for pid in pids:
            try: usage = self.getProcessUsage(pid)
            except: continue
            if self.processes.has_key(pid):
                oldutime, oldstime = self.processes[pid]
                newutime, newstime = usage
                self.processes[pid] = (newutime-oldutime, newstime-oldstime)            
            else:
                self.processes[pid] = usage

    def diagnoseUsage(self):
        xenrt.TEC().logverbose("Keep ps evidence as soon as we can")
        self.host.execdom0("ps -aux")
        xenrt.TEC().logverbose("Further triage single process")
        self.getUsage()
        for p in self.processes:
            utime, stime = self.processes[p]
            if utime > self.threshold or stime > self.threshold:
                command = self.host.execdom0("ps -p %s -o comm=" % (p)).strip()
                xenrt.TEC().warning("The %s process with PID %s used more than "
                                    "%ss of utime or stime during the test. "
                                    "(utime=%s, stime=%s)" % (command, 
                                                              p, 
                                                              self.threshold, 
                                                              utime, 
                                                              stime))
                
    def prepare(self, arglist):
        self.processes = {} 
        # How long, in seconds, to run the test for.
        self.duration = 600 
        # Waren about processes using more than this amount of time.
        self.threshold = self.duration/20
        self.host = self.getDefaultHost()

    def run(self, arglist):
        self.host.reboot()
        start = xenrt.timenow()
        self.getUsage()
        xenrt.TEC().logverbose("Sleeping for %ss." % (self.duration/2))
        time.sleep(self.duration/2)
        load = self.checkLoad()
        if load > 0.7:
            self.diagnoseUsage()
            xenrt.TEC().logverbose("Dom0 load on an idle system is too high %s minutes after boot." % (self.duration/120))
        xenrt.TEC().logverbose("Sleeping for %ss." % (self.duration/2))
        time.sleep(self.duration/2)
        load = self.checkLoad()
        if load > 0.5:
            self.diagnoseUsage()
            xenrt.TEC().logverbose("Dom0 load on an idle system is too high %s minutes after boot." % (self.duration/60))
        # Do a diagnose anyway
        self.diagnoseUsage()

class IdleVMsDom0CPUUtilize(xenrt.TestCase):
    """TC-20881 Hundred idle Windows VMs on a single host should not have a high dom0 CPU Usage"""
    
    DISTRO = "win7-x86"
    
    def __init__(self,tcid=None):
        
        self.host = None
        self.guests = []
        xenrt.TestCase.__init__(self, tcid)
        
    def prepare(self, arglist):
        
        self.host = self.getDefaultHost()
        # Create the Base Windows VM
        guest = self.host.createBasicGuest(distro=self.DISTRO, name="baseVM")
        # Deploy 100 VMs via VM Clone loop
        max = 100
        count = 0
        clones = []
        self.guests.append(guest)
        guest.preCloneTailor()
        guest.shutdown()
        
        while count < max:
            if count > 0 and count % 20 == 0:
                # CA-19617 Perform a vm-copy every 20 clones
                guest = guest.copyVM(name=str(count/20) + "copyOF-" + guest.getName())
                self.guests.append(guest)
            try:
                g = guest.cloneVM(name=str(len(clones)+1) + "-" + "cloneOF-" + guest.getName())
                self.guests.append(g)
                clones.append(g)
            except xenrt.XRTFailure, e:
                xenrt.TEC().warning("Failed to clone a VM %u: %s" % (len(clones)+1,e))
                break
            count += 1
        
        # Starting all the VMs
        attempts = 0 # One single VM failure shouldn't stop the VM start loop. Try a mximum of 10 failures, before quitting the loop..
        for g in clones:
            try:
                g.start()
            except xenrt.XRTFailure, e:
                xenrt.TEC().warning("Failure >> Couldn't start VM %s: %s" % (g.getName(),e))
                attempts += 1
            if attempts > 10:
                break
        
        # Check all the VMs are reachable
        aliveCount = 0
        for g in clones:
            try:
                g.checkReachable(30)
            except:
                xenrt.TEC().warning("Guest %s not reachable" % (g.getName()))
            else:
                aliveCount += 1
        xenrt.TEC().logverbose("%d/%d guests reachable" % (aliveCount, len(clones)))
        
    def run(self, arglist):
        
        # How long, in seconds, to run the test for
        duration = 600
        # CPU Utilization can vary for different XenServer Versions
        threshold = self.host.lookup("IDLE_VMs_DOM0_CPU_Utilize")
        deadline = xenrt.util.timenow() + duration
        # Check the dom0 cpu usage
        while xenrt.util.timenow() < deadline:
            usage = self.host.getXentopData()
            cpuUsage = usage["0"]["CPU(%)"]
            if float(cpuUsage) > float(threshold):
                raise xenrt.XRTFailure("CPU Usage of dom0 is high, Expected was %s and obtained is %s" % (threshold, cpuUsage))
                break
        xenrt.TEC().logverbose("CPU Usage of dom0 is under control")
        
    def postRun(self, arglist):
        
        for g in self.guests:
            try:
                try:
                    g.shutdown(force=True)
                except:
                    pass
                g.poll("DOWN", 120, level=xenrt.RC_ERROR)
                g.uninstall()
            except:
                xenrt.TEC().warning("Exception while uninstalling temp guest")
        

class _LicenseTest(xenrt.TestCase):

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.cli = self.host.getCLIInstance()
        
    def applyLicense(self, filename):
        # Parse useful stuff from the license
        f = file(filename, "r")
        data = f.read()
        f.close()
        r = re.search(r"sku_type=\"(.*?)\"", data)
        if not r:
            raise xenrt.XRTError("Could not parse sku_type", data)
        sku_type = r.group(1)
        r = re.search(r"version=\"(.*?)\"", data)
        if not r:
            raise xenrt.XRTError("Could not parse version", data)
        version = r.group(1)
        r = re.search(r"expiry=\"(.*?)\"", data)
        if not r:
            raise xenrt.XRTError("Could not parse expiry", data)
        expiry = r.group(1)
        r = re.search(r"serialnumber=\"(.*?)\"", data)
        if not r:
            raise xenrt.XRTError("Could not parse serialnumber", data)
        serialnumber = r.group(1)
        xenrt.TEC().logverbose("Checking license with SKU %s, version %s "
                               "and expiry %s" % (sku_type, version, expiry))
        
        # Apply the license file to the host
        try:
            self.cli.execute("host-license-add", "license-file=%s" % (filename))
            time.sleep(2)
        except xenrt.XRTFailure, e:
            r = re.search(r"Your license has expired", e.reason)
            if not r:
                raise e
            t = xenrt.timenow()
            if float(expiry) <= float(t):
                xenrt.TEC().logverbose("Valid expiry error")
                return
            raise xenrt.XRTFailure("License gave expiry error before expiry "
                                   "date", 
                                   "expiry=%s now=%u" % (expiry, t))

        # Check the license has been applied correctly
        ld = self.host.getLicenseDetails()

        if not ld.has_key("sku_type"):
            raise xenrt.XRTError("Could not parse sku_type from license")
        if ld["sku_type"] != sku_type:
            raise xenrt.XRTFailure("Licensed SKU '%s' is not what we "
                                   "asked for ('%s')" %
                                   (ld["sku_type"], sku_type))

        if not ld.has_key("serialnumber"):
            raise xenrt.XRTError("Could not parse serialnumber from license")
        if ld["serialnumber"] != serialnumber:
            raise xenrt.XRTFailure("License serial '%s' is not what we "
                                   "applied ('%s')" %
                                   (ld["serialnumber"], serialnumber))

        if not ld.has_key("version"):
            raise xenrt.XRTError("Could not parse version from license")
        if ld["version"] != version:
            raise xenrt.XRTFailure("License version '%s' is not what we "
                                   "applied ('%s')" % (ld["version"], version))

    def postRun(self):
        self.host.license()

class TC8225(_LicenseTest):
    """Verify a collection of example licenses can be applied"""

    TARGET_NUMBER = 800

    def prepare(self, arglist):
        # Fetch the exanmple licenses
        workdir = xenrt.TEC().getWorkdir()
        xenrt.getTestTarball("licenses",extract=True,directory=workdir)
        ldir = xenrt.TEC().tempDir()
        xenrt.command("unzip -P d439djYY %s/licenses/licenses.zip -d %s || true" %
                      (workdir, ldir))
        self.licensedir = "%s/licenses" % (ldir)
        licenseuuids = xenrt.command("ls %s" % (self.licensedir)).split()
        if len(licenseuuids) < self.TARGET_NUMBER:
            raise xenrt.XRTError("Only %u license files found" %
                                 (len(licenseuuids)))
        self.licenseuuids = random.sample(licenseuuids, self.TARGET_NUMBER)
        self.host = self.getDefaultHost()
        self.cli = self.host.getCLIInstance()

    def run(self, arglist):
        counter = 0
        for uuid in self.licenseuuids:
            counter = counter + 1
            xenrt.TEC().logverbose("Tested %u/%u licenses" %
                                   (counter, self.TARGET_NUMBER))
            filename = "%s/%s" % (self.licensedir, uuid)
            self.runSubcase("applyLicense", (filename), "License", uuid)

class TC8230(_LicenseTest):
    """Verify a license with lots of nasty characters can be applied"""

    def run(self, arglist):
        filename = ("%s/keys/xenserver/tests/TC-8230" % 
                    (xenrt.TEC().lookup("XENRT_CONF")))
        self.runSubcase("applyLicense", (filename), "License", "Nasty")

class _Dom0MemoryTest(xenrt.TestCase):

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.host = None


    def checkmem(self, targetb):
        memtarget = float(self.host.genParamGet("vm",
                                                self.host.getMyDomain0UUID(),
                                                "memory-target"))
        memactual = float(self.host.genParamGet("vm",
                                                self.host.getMyDomain0UUID(),
                                                "memory-actual"))
        data = self.host.execdom0("cat /proc/meminfo")
        r = re.search(r"MemTotal:\s+(\d+)\s+kB", data)
        if not r:
            raise xenrt.XRTError("Could not parse /proc/meminfo for MemTotal")
        memtotal = float(r.group(1)) * 1024
        for x in [("memory-target", memtarget),
                  ("memory-actual", memactual),
                  ("/proc/meminfo:MemTotal", memtotal)]:
            desc, m = x
            delta = abs(targetb - m)
            error = 100.0 * delta / targetb
            if error > 5.0:
                raise xenrt.XRTFailure("%s is not as expected" % (desc),
                                       "Target %f bytes, is %f bytes" %
                                       (targetb, m))

    def verifydom0mem(self,required=None):
        """Function to check whether the dom 0 memory maintains the relation with the 
           host memory in accordance with the ea-1041
           If a required dom0 memory is specified you check it against that value (for the upgrade scenarios)"""
        
        #get the actual dom 0 memory in MB
        memActual = self.host.genParamGet("vm",
                                          self.host.getMyDomain0UUID(),
                                          "memory-actual")
        memActual=int(memActual)/xenrt.MEGA 
        #logging the actual memory in MB  
        xenrt.TEC().logverbose("the dom0 memory in MB is %d" %memActual)
        
        #define the maximum allowed deviation from the expected dom0 memory value
        margin=24
        
        if required==None: 
          #testing for the clean install
          #create a dictionary to contain the memory range matrix
          hostMemRange={ (2,24):752,
                         (24,48):2048,
                         (48,64):3072,
                         (64,1024):4096
               }

          #below code gets u the rounded off value of memory-total of host (in GB)  
          hostMemActual=float(self.host.getHostParam("memory-total"))/xenrt.GIGA
          hostMemActual=round(hostMemActual)
          xenrt.TEC().logverbose("the host memory in GB is %d" %hostMemActual)
          #get the expected dom0 memory value according to the matrix
          for hostMem in hostMemRange:
            if hostMemActual in range(hostMem[0],hostMem[1]):
                required=hostMemRange[hostMem]
                
        xenrt.TEC().logverbose("the expected dom0 memory in MB is %d" %required)
        if abs(required-memActual)<=margin:
            xenrt.TEC().logverbose("The dom0 memory is close to the expected value")
        else:
            raise xenrt.XRTFailure("the dom0 memory deviates a lot from the expected value")
            
class Dom0MemOnCleanInstall(_Dom0MemoryTest):
    """Check whether the dom 0 memory is of the expected value for the clean installation"""
    
    def prepare(self, arglist):
        self.host=self.getDefaultHost()
        
    def run(self, arglist):        
        self.verifydom0mem()

class Dom0MemOnUpgrade(_Dom0MemoryTest):
    """Check whether the dom 0 memory is of the expected value for the default/custom upgrade"""
    
    def prepare(self, arglist):
    
        #self.host=self.getDefaultHost()
        
        if arglist and len(arglist)>0:
          for arg in arglist:
            l=arg.split("=",1)
            if len(l)==1: #host is specified ,eg. RESOURCE_HOST_1
              self.host=self.getHost(l[0]);
            elif l[0]=="dom0_mem":
              #editing the extlinux.conf file to change the dom0 mem values
              self.host.execdom0("sed -i 's/dom0_mem=[0-9]*M/dom0_mem=%sM/g' /boot/extlinux.conf" %l[1])
              self.host.execdom0("sed -i 's/dom0_mem=\([0-9]*\)M,max:[0-9]*M/dom0_mem=\\1M,max:%sM/g' /boot/extlinux.conf" %l[1])
        
              #rebooting the host
              self.host.reboot()
              
        else:
          raise xenrt.XRTError("Host not specified")
          
        self.required=self.host.genParamGet("vm",
                                          self.host.getMyDomain0UUID(),
                                          "memory-actual")
        self.required=int(self.required)/xenrt.MEGA  
        xenrt.TEC().logverbose("the dom0 memory before upgrade in MB is %d" %self.required)
        self.host=self.host.upgrade()
    
    def run(self,arglist):
        self.verifydom0mem(self.required)

class TC8298(_Dom0MemoryTest):
    """Check that domain zero's memory target persists across xapi restart"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.cli = self.host.getCLIInstance()
        self.uuid = self.host.getMyDomain0UUID()

        # Find the current dom0 memory target
        self.original = int(self.host.genParamGet("vm",
                                                  self.uuid,
                                                  "memory-target"))

        if self.original > (700 * 1024 * 1024):
            raise xenrt.XRTError("Dom0 memory is too high to test an increase",
                                 str(self.original))
        
        # Test by adding 50MB
        self.target = self.original + 50 * 1024 * 1024
    
    def run(self, arglist):

        # Set the dom0 memory to the new target
        self.cli.execute("vm-memory-target-set",
                         "target=%u uuid=%s" % (self.target, self.uuid))
        self.cli.execute("vm-memory-target-wait", "uuid=%s" % (self.uuid))
        time.sleep(60)

        targetb = float(self.target)

        # Check the new target is honoured
        if self.runSubcase("checkmem", (targetb), "Dom0Mem", "Initial") != \
               xenrt.RESULT_PASS:
            return

        # Check the target is honoured after a xapi restart
        self.host.restartToolstack()
        time.sleep(30)
        if self.runSubcase("checkmem", (targetb), "Dom0Mem", "Persist") != \
               xenrt.RESULT_PASS:
            return

        # Check the target is honoured after a reboot
        self.host.reboot()
        if self.runSubcase("checkmem", (targetb), "Dom0Mem", "Reboot") != \
               xenrt.RESULT_PASS:
            return

    def postRun(self):
        self.cli.execute("vm-memory-target-set",
                         "target=%u uuid=%s" % (self.original, self.uuid))
        self.cli.execute("vm-memory-target-wait", "uuid=%s" % (self.uuid))
    
class TC8299(_Dom0MemoryTest):
    """Dom0 memory should be set according to the gradient and intercept defined."""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()

        # The default parameters
        self.intercept = float(self.host.lookup("DOM0_MEM_INTERCEPT_MB",
                                                "226"))
        self.gradient = float(self.host.lookup("DOM0_MEM_GRADIENT",
                                               "0.0205078125"))
        self.minimum = float(self.host.lookup("DOM0_MEM_MIN_MB", "300"))
        self.maximum = float(self.host.lookup("DOM0_MEM_MAX_MB", "752"))

        # Look for any OEM overrides
        data = self.host.execdom0(\
            "if [ -e /etc/firstboot.d/data/memory.conf ]; then "
            "  cat /etc/firstboot.d/data/memory.conf; fi")
        r = re.search(r"MEMORY_INTERCEPT_MiB=(\S+)", data)
        if r:
            self.intercept = float(r.group(1).strip("'\""))
        r = re.search(r"MEMORY_GRADIENT=(\S+)", data)
        if r:
            self.gradient = float(r.group(1).strip("'\""))

        # Force the firstboot memory script to run again to simluate
        # a fresh reboot
        fbstate = "/etc/firstboot.d/state/23-set-dom0-memory"
        if self.host.execdom0("test -e %s" % (fbstate), retval="code") == 0:
            self.host.execdom0("rm -f %s" % (fbstate))
            self.host.reboot()
            if self.host.execdom0("test -e %s" % (fbstate),
                                  retval="code") != 0:
                raise xenrt.XRTError("Firstboot dom0 memory script appears "
                                     "not to have run")

    def run(self, arglist):

        xenrt.TEC().comment("Testing dom0 memory intercept %fMB, gradient %f, "
                            "in range [%f, %f]" % (self.intercept,
                                                   self.gradient,
                                                   self.minimum,
                                                   self.maximum))
        
        hostmem = self.host.getTotalMemory()
        targetb = float(hostmem * 1024 *1024) * self.gradient + \
                  float(self.intercept * 1024 * 1024)
        xenrt.TEC().logverbose("Initial target is %f bytes" % (targetb))
        minb = self.minimum * 1024 * 1024
        maxb = self.maximum * 1024 * 1024
        if targetb > maxb:
            targetb = maxb
            raise xenrt.XRTError("Required memory is capped, the test will "
                                 "not detect the failure")
        if targetb < minb:
            targetb = minb
            xenrt.TEC().logverbose("Raising target to %f bytes" % (targetb))
        
        if self.runSubcase("checkmem", (targetb), "Dom0Mem", "Initial") != \
                xenrt.RESULT_PASS:
            return
        self.host.reboot()
        if self.runSubcase("checkmem", (targetb), "Dom0Mem", "Reboot") != \
                xenrt.RESULT_PASS:
            return

class _HostReboot(xenrt.TestCase):

    PRODUCT_DOES_VM_SHUTDOWN = True

    def prepare(self, arglist):
        self.numberofguests = 2
        self.numbertostayup = 1
        self.host = self.getDefaultHost()
        self.pool = self.getDefaultPool()

        self.guests = []
        self.stayup = []
        self.shutdowntimes = []
        for i in range(self.numberofguests):
            g = self.host.createGenericLinuxGuest()
            self.getLogsFrom(g)
            self.guests.append(g)
            self._guestsToUninstall.append(g)

        if self.pool:        
            self.pool.setPoolParam("other-config:auto_poweron", "true")
        else:
            # Singleton host, lookup the pool UUID and issue the
            # param-set call via the host object
            hostuuid = self.host.getMyHostUUID()
            pooluuid = self.host.parseListForUUID("pool-list",
                                                  "master",
                                                  hostuuid)
            self.host.genParamSet("pool",
                                  pooluuid,
                                  "other-config",
                                  "true",
                                  "auto_poweron")

    def reboot(self):
        raise xenrt.XRTError("Unimplemented!")

    def run(self, arglist):
        for i in range(self.numbertostayup):
            self.guests[i].paramSet("other-config-auto_poweron", "true")
        for g in self.guests:
            g.shutdown()
            g.start()
            self.shutdowntimes.append(g.getLastShutdownTime())
        if not self.PRODUCT_DOES_VM_SHUTDOWN:
            for g in self.guests:
                g.shutdown()

        xenrt.TEC().logverbose("Rebooting host...")
        self.reboot()
        self.host.waitForSSH(300)
        time.sleep(30)

        for i in range(self.numbertostayup):
            if not self.guests[i].getState() == "UP":
                raise xenrt.XRTFailure("Guest failed to start after host reboot.",
                                       self.guests[i].getName())
            else:
                xenrt.TEC().logverbose("Found guest %s in the UP state." % 
                                       (self.guests[i].getName()))
        for i in range(self.numbertostayup, self.numberofguests):
            if not self.guests[i].getState() == "DOWN":
                raise xenrt.XRTFailure("Found guest in an incorrect state.",
                                       self.guests[i].getName())
            else:
                xenrt.TEC().logverbose("Found guest %s in the DOWN state." % 
                                       (self.guests[i].getName()))
                self.guests[i].start()

        for i in range(len(self.guests)):
            mostrecent = self.guests[i].getLastShutdownTime()
            if not mostrecent > self.shutdowntimes[i]:
                raise xenrt.XRTFailure("Guest doesn't appear to have been "
                                       "shut down cleanly.",
                                       "%s (%s <= %s)" %
                                       (self.guests[i].getName(),
                                        mostrecent,
                                        self.shutdowntimes[i]))

class TC8253(_HostReboot):
    """Single host reboot using CLI including auto started VM"""

    PRODUCT_DOES_VM_SHUTDOWN = False

    def reboot(self):
        self.host.cliReboot()

class TC8254(_HostReboot):
    """Single host reboot using /sbin/reboot including auto started VM"""

    def reboot(self):
        self.host.reboot()

class TC8453(xenrt.TestCase):
    """host-reboot should fail if any VMs are currently running on the host"""

    def prepare(self, arglist):
        # Install and start a VM
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericLinuxGuest()
        self.getLogsFrom(self.guest)
        self.uninstallOnCleanup(self.guest)
        
    def run(self, arglist):
        # Attempt a shutdown, we expect this to fail
        try:
            self.host.cliReboot()
        except xenrt.XRTFailure, e:
            if re.search("This operation cannot be completed as the host is in use", e.data):
                # This is good
                pass
            else:
                raise xenrt.XRTFailure("Unexpected failure on host-reboot: %s"
                                       % (str(e)))
        else:
            #raise xenrt.XRTFailure(\
            #    "host-reboot did not fail when a VM was running on the host")
            xenrt.TEC().logverbose("CA-61529: Weaken pre-condition for Host.shutdown and Host.reboot")
            xenrt.TEC().logverbose("Host-reboot does not fail when a VM was running on the host. Instead VM use the host.reboot/shutdown API even though it is still running itself.")

# Wait a bit then verify the VM is still OK
        time.sleep(120)
        self.guest.checkHealth()

    def postRun(self):
        self.host.enable()

class TC8255(xenrt.TestCase):
    """Single host reboot with a hung VM"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericWindowsGuest()
        self.getLogsFrom(self.guest)
        self._guestsToUninstall.append(self.guest)
       
    def run(self, arglist):
        self.host.execdom0("/usr/lib/xen/bin/crash_guest %s" % (self.guest.getDomid()))
        self.host.cliReboot()
        self.host.waitForSSH(600)

class TC8309(xenrt.TestCase):
    """Test for stale lockfiles"""

    def run(self, arglist=None):
        host = self.getDefaultHost()

        # Touch a test stamp
        host.execdom0("touch /var/lock/subsys/TEST.STAMP")

        # Hard power cycle
        host.execdom0("mount -o remount,barrier=1 /")
        host.execdom0("sync")
        host.machine.powerctl.cycle()
        xenrt.sleep(180)

        # Wait for it to boot
        host.waitForSSH(600, desc="Host boot after hard power cycle")

        xenrt.sleep(180)

        # Check if stamp still exists
        if host.execdom0("ls /var/lock/subsys/TEST.STAMP", retval="code") == 0:
            raise xenrt.XRTFailure("Test lockfile stamp remained after power "
                                   "cycle")

class TC8341(xenrt.TestCase):
    """Reboot a host until it has to fsck."""
   
    def getMountCount(self, max=False):
        if max: pattern = "Maximum mount count"
        else: pattern = "Mount count"
        cmd = "tune2fs -l %s | grep '%s' | cut -d ':' -f 2"
        count = int(self.host.execdom0(cmd % (self.rootdisk, pattern)).strip())
        if max and count <= 0:
            xenrt.TEC().logverbose("Maximum mount count was %d. Changing it to 30 for tests." % count)
            self.host.execdom0("tune2fs -c 30 %s" % self.rootdisk)
            count = int(self.host.execdom0(cmd % (self.rootdisk, pattern)).strip())
            if count != 30:
                raise xenrt.XRTError("Failed to change 'Maximum mount count' to 30.")

        return count

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        volume = "/"
        self.rootdisk = self.host.execdom0("df -h %s | "
                                           "tail -n 1 | "
                                           "cut -f 1 -d ' '" % (volume)).strip()

    def run(self, arglist): 
        mountcount = self.getMountCount()
        xenrt.TEC().logverbose("'Mount count' for %s is %s." % 
                               (self.rootdisk, mountcount))
        maxmountcount = self.getMountCount(max=True)
        xenrt.TEC().logverbose("'Maximum mount count' for %s is %s." % 
                               (self.rootdisk, maxmountcount))
        xenrt.TEC().logverbose("Setting mount count to 'Maximum mount count' - 1. (%s)" %
                               (maxmountcount - 1))
        self.host.execdom0("tune2fs -C %d %s" % (maxmountcount - 1, self.rootdisk))
        # Knock the mount count up to 'Maximum mount count'.
        self.host.reboot()
        # Try for a FSCK. If this passes we're good to go.
        self.host.reboot()
        # Check we actually had a FSCK.
        mountcount = self.getMountCount()
        if not mountcount == 1:
            raise xenrt.XRTFailure("'Mount count' after fsck isn't 1.")

class TC8450(xenrt.TestCase):
    """Verify crashdump (kdump) functionality on a box with up to 32GB RAM"""

    def prepare(self, arglist=None):

        self.host = self.getDefaultHost()

        # Check there aren't any existing crashdumps
        cds = self.host.listCrashDumps()
        if len(cds) > 0:
            raise xenrt.XRTError("%u existing crashdumps found on host" % 
                                 (len(cds)))

    def run(self, arglist=None):

        # Generate a crashdump
        try:
            self.host.execdom0("sleep 5 && echo c > /proc/sysrq-trigger &",
                               timeout=30)
        except:
            # We expect to lose SSH connection
            pass

        # Wait for the host to reboot
        self.host.waitForSSH(1200, desc="Post crash reboot on !" + self.host.getName())

        # Verify Xapi is running
        self.host.waitForXapi(600, desc="Xapi startup post reboot on !" + self.host.getName())

        # Confirm there is a crashdump
        cds = self.host.listCrashDumps()
        if len(cds) == 0:
            raise xenrt.XRTFailure("Crashdump not generated after crash on !" + self.host.getName())
        if len(cds) > 1:
            raise xenrt.XRTFailure("Multiple crashdumps generated after crash on !" + self.host.getName())

        xenrt.TEC().comment("crashdump UUID %s" % (cds[0]))

        # Check the crashdump files exist
        # XXX if CA-8453 ever gets resolved, it would be nicer to use it,
        #     rather than assuming the only file we get is the cdump
        logdir = "%s/bugtool" % (xenrt.TEC().getLogdir())
        os.makedirs(logdir)
        bugTool = self.host.getBugTool(bugdir=logdir,
                                       extras=["host-crashdump-logs"])
        # Extract it
        xenrt.command("tar -C %s -xzf %s" % (logdir, bugTool))
        # Now find the crashdump, and check the expected files are present
        # We want crash.log, debug.log, domain0.log and xen-memory-dump
        files = self.host.lookup("EXPECTED_CRASHDUMP_FILES",
                                 "crash.log,debug.log,domain0.log,"
                                 "xen-memory-dump").split(",")
        # Since the path might vary, just run find to get the files
        data = xenrt.command("find %s" % (logdir))
        missing = []
        for f in files:
            if not f in data:
                missing.append(f)
        if len(missing) > 0:
            raise xenrt.XRTFailure("One or more crashdump files missing from bugtool on !" + self.host.getName(),data=missing)

        nofiles = self.host.lookup("UNEXPECTED_CRASHDUMP_FILES",
                                   "core.kdump").split(",")
        unexpected = []
        for f in nofiles:
            if f in data:
                unexpected.append(f)
        if len(unexpected) > 0:
            raise xenrt.XRTFailure("One or more unexpected files found in crashdump on !" + self.host.getName(),data=unexpected)

    def preLogs(self):
        # If the host is unreachable, try powercycling it
        try:
            self.host.checkReachable(timeout=30)
        except:
            xenrt.TEC().logverbose("Host unreachable, attempting powercycle to collect bugtool")
            self.host.machine.powerctl.cycle()
            try:
                self.host.waitForSSH(1200, desc="Post power cycle reboot")
            except:
                pass

        # Attempt to wipe out any crashdumps so as not to cause alarm
        if self.host:
            try:
                for cd in self.host.listCrashDumps():
                    try:
                        self.host.destroyCrashDump(cd)
                    except:
                        pass
            except:
                pass

class TC8451(TC8450):
    """Verify crashdump (kdump) functionality on a box with the maximum
       supported amount of RAM"""
    pass 


class XenCrashDump(xenrt.TestCase):
    """Test xen-crashdump-analyser on a box with up to X GB RAM"""

    def createMoreVMs(self):
        mem = self.guest.memory
        
        while (int(self.host.getHostParam("memory-free")) / 1048576) > mem:
            g = self.guest.cloneVM(name=xenrt.randomGuestName())
            self.uninstallOnCleanup(g)
            g.start()
            g.waitForSSH(300)
            self.test_VMs.append((g.getDomid(), g.getUUID()))

        return
            
    def prepare(self, arglist=None):

        self.pool = self.getDefaultPool()
        if self.pool is None:
            self.host = self.getDefaultHost()
        else:
            self.host = self.pool.master
            
        self.guest = None
        self.crash_dom0 = True
        self.trigger_nmi = False
        self.crash_xen = False
        self.fill_rootfs = False
        self.num_VMs = 0
        self.test_VMs = []
        self.max_clones = False
        self.uptime = 0
        self.testEachCPU = False

        for arg in arglist:
            if arg.startswith('guest'):
                self.guest = self.getGuest(arg.split('=')[1].strip())
            if arg.startswith('crash_dom0'):
                self.crash_dom0 = True
                self.crash_xen = False
            if arg.startswith('crash_xen'):
                self.crash_dom0 = False
                self.crash_xen = True
            if arg.startswith('trigger_nmi'):
                self.trigger_nmi = True
                self.crash_dom0 = False
            if arg.startswith('fill_rootfs'):
                self.fill_rootfs = True
            if arg.startswith('clones'):
                self.num_VMs = int(arg.split('=')[1].strip())
            if arg.startswith('max_clones'):
                self.max_clones = True
            if arg.startswith('uptime'):
                self.uptime = int(arg.split('=')[1].strip())
            if arg.startswith('test_each_pcpu'):
                self.testEachCPU = True
       
        self.destroyAllCrashDumps() 

        if self.trigger_nmi:
            try:
                self.host.execdom0('/opt/xensource/libexec/xen-cmdline --set-xen nmi=fatal')
            except:
                pass
            else:
                self.host.reboot()

        if self.guest is None:
            return
        
        if self.guest.getState() <> 'UP':
            self.guest.start()
            self.guest.waitForSSH(300)
        
        self.guest.preCloneTailor()
        self.guest.shutdown()
        
        for i in range(self.num_VMs):
            if (int(self.host.getHostParam("memory-free")) / 1048576) <= self.guest.memory:
                break
            g = self.guest.cloneVM(name='test%03d' % i)
            self.uninstallOnCleanup(g)
            g.start()
            g.waitForSSH(300)
            self.test_VMs.append((g.getDomid(), g.getUUID()))
            
        if self.max_clones:
            self.createMoreVMs()

    def generateCrashdump(self):
        # Generate a crashdump
        if self.fill_rootfs:
            self.host.execdom0('dd if=/dev/zero of=/root/delete_me; exit 0', timeout=300)
        try:
            if self.crash_dom0:
                self.host.execdom0("sleep 5 && echo c > /proc/sysrq-trigger &", timeout=30)
            elif self.crash_xen:
                self.host.execdom0("sleep 5 && xl debug-keys C &", timeout=30)
            else: # must be self.trigger_nmi
                self.host.machine.powerctl.triggerNMI()
        except:
            # We expect to lose SSH connection
            pass

        time.sleep(120)
        return

    def waitForSpecifiedUptime(self):
        
        if self.uptime == 0:
            return
        
        uptime = float(self.host.execdom0("cat /proc/uptime").strip().split()[0])
        tm_required = datetime.timedelta(seconds=self.uptime)
        tm_current = datetime.timedelta(seconds=uptime)
        
        if tm_required > tm_current:
            time.sleep((tm_required - tm_current).seconds)

        self.host.execdom0('uptime') # For logging
        return

    def testCrashDump(self):

        # Pause if required (XOP-221)
        self.waitForSpecifiedUptime()

        # Generate a crashdump
        self.generateCrashdump()

        # Wait for the host to reboot
        self.host.waitForSSH(1200, desc="Post crash reboot on !" + self.host.getName())

        # Delete sparse file if necessary
        self.host.execdom0('rm -vf /root/delete_me ; exit 0')
        time.sleep(60)
        
        self.host.execdom0('xe-toolstack-restart')
        
        # Verify Xapi is running
        self.host.waitForXapi(600, desc="Xapi startup post reboot on !" + self.host.getName())

        # Confirm there is a crashdump
        cds = self.host.listCrashDumps()
        if len(cds) == 0:
            raise xenrt.XRTFailure("Crashdump not generated after crash on !" + self.host.getName())
        if len(cds) > 1:
            raise xenrt.XRTFailure("Multiple crashdumps generated after crash on !" + self.host.getName())

        xenrt.TEC().comment("crashdump UUID %s" % (cds[0]))
        
        # Check the crashdump files exist
        # XXX if CA-8453 ever gets resolved, it would be nicer to use it,
        #     rather than assuming the only file we get is the cdump
        logdir = "%s/bugtool" % (xenrt.TEC().getLogdir())
        xenrt.command('[ -d %s ] && rm -rf %s ; exit 0' % (logdir, logdir))
        os.makedirs(logdir)
        bugTool = self.host.getBugTool(bugdir=logdir,
                                       restrictTo=["host-crashdump-logs"])
        # Extract it
        xenrt.command("tar -C %s -xvzf %s" % (logdir, bugTool))
        # Now find the crashdump, and check the expected files are present
        # We want crash.log, debug.log, domain0.log and xen-memory-dump
        # files = self.host.lookup("EXPECTED_CRASHDUMP_FILES",
        #                          "xen-crashdump-analyser.log,xen.log,dom0.log").split(",")
        files = set(["xen-crashdump-analyser.log", "xen.log", "dom0.log"]) 
        # Since the path might vary, just run find to get the files
        data = xenrt.command("find %s" % (logdir))
        missing = []
        for f in files:
            if not f in data:
                missing.append(f)
        if len(missing) > 0:
            xenrt.TEC().logverbose("Following files are missing: %s" % missing)
            raise xenrt.XRTFailure("One or more crashdump files missing from bugtool on !" + self.host.getName(),data=missing)

        xen_crashdump_path = self.host.execdom0("find /var/crash -name xen-crashdump-analyser.log").strip()

        def checkFileSize(log):
            f = self.host.execdom0("find /var/crash -name " + log).strip()
            s = int(self.host.execdom0("ls -s " + f).strip().split()[0])
            if s == 0:
                return [log + " has size 0"]
            else:
                return []

        errMsgs = sum([checkFileSize(log) for log in files], [])

        if len(errMsgs) > 0:
            raise xenrt.XRTFailure("one or more log files have size 0 on !" + self.host.getName())
        
        ret = self.host.execdom0("grep '^ERROR' %s ; exit 0" % xen_crashdump_path).strip().splitlines()
        if len(ret) > 0:
            raise xenrt.XRTFailure("xen-crashdump-analyser.log has atleast one line beginning with 'ERROR' on !" + self.host.getName())

        ret = self.host.execdom0("tail -n1 %s | grep COMPLETE" % xen_crashdump_path, retval="code")
        if ret != 0:
            raise xenrt.XRTFailure("xen-crashdump-analyser.log doesn't have COMPLETE on its final line on !" + self.host.getName())
        
        def checkDomNLog(arg):
            dom_id, vm_uuid = arg
            path = self.host.execdom0("find /var/crash -name dom%s.log" % dom_id).strip()
            if path == "":
                return ["dom%s.log not found in %s" % (dom_id, os.path.dirname(xen_crashdump_path))]
            ret = self.host.execdom0("grep %s %s" % (vm_uuid, path), retval="code")
            if ret != 0:
                return ["VM UUID %s not found in %s" % (vm_uuid, path)]
            return []

        dom_N_err_msgs = sum(map(checkDomNLog, self.test_VMs),[])
        if dom_N_err_msgs:
            xenrt.TEC().logverbose("Following errors were found in domN logs on !" + self.host.getName())
            map(xenrt.TEC().logverbose, dom_N_err_msgs)
            raise xenrt.XRTFailure("domN log not found or missig VM UUID entry on !" + self.host.getName())

    def unplugAllButOneCPU(self):
        self.host.execdom0("""for cpu in `echo /sys/devices/system/cpu/cpu* | sed -e 's/\/.*cpu0//g'`; do echo 0 > $cpu/online ; done""")
        return
    
    def getNumCPUs(self):
        self.host.execdom0("xl info  | grep nr_cpus > /tmp/nr_cpus")
        return int(self.host.execdom0("sed -e 's/://' /tmp/nr_cpus | awk '{ print $NF }'").strip())
    
    def run(self, arglist=None):

        self.skipNextCrashdump = True
        self.host.skipNextCrashdump = True
        
        if not self.testEachCPU:
            self.testCrashDump()
            return

        # Alright, we have to test crash on each pcpus
        self.crash_dom0 = True
        self.crash_xen = False
        
        numCpus = self.getNumCPUs()
        indexes = [0, 1]
        
        if numCpus > 2:
            indexes.append(random.randint(2, numCpus - 1))
            indexes.append(numCpus - 1)
        
        for pcpu in indexes:
            self.unplugAllButOneCPU()
            self.host.execdom0('xl vcpu-pin 0 0 %d' % pcpu)
            self.destroyAllCrashDumps()
            time.sleep(60)
            self.testCrashDump()

    def destroyAllCrashDumps(self):
        for cd in self.host.listCrashDumps():
            try:
                self.host.destroyCrashDump(cd)
            except:
                pass

    def preLogs(self):
        # If the host is unreachable, try powercycling it
        try:
            self.host.checkReachable(timeout=30)
        except:
            xenrt.TEC().logverbose("Host unreachable, attempting powercycle to collect bugtool")
            self.host.machine.powerctl.cycle()
            try:
                self.host.waitForSSH(1200, desc="Post power cycle reboot")
            except:
                pass

    def postRun(self):
        try:
            self.destroyAllCrashDumps()
        except:
            pass


class _TCHideFromXenCenter(xenrt.TestCase):
    """Verify a SM.other_config key persists across some action"""

    def checkKey(self, xapi):
        smref = xapi.SM.get_by_name_label("ISO")[0]
        sm = xapi.SM.get_record(smref)
        if not sm['other_config'].has_key("HideFromXenCenter"):
            raise xenrt.XRTFailure("SM other_config:HideFromXenCenter does "
                                   "not exist")
        if sm['other_config']["HideFromXenCenter"] != "true":
            raise xenrt.XRTFailure("SM other_config:HideFromXenCenter is not "
                                   "true",
                                   sm['other_config']["HideFromXenCenter"])
        
    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        session = self.host.getAPISession()
        xapi = session.xenapi
        try:
            smref = xapi.SM.get_by_name_label("ISO")[0]
            try:
                xapi.SM.remove_from_other_config(smref, "HideFromXenCenter")
            except:
                pass
            xapi.SM.add_to_other_config(smref, "HideFromXenCenter", "true")
            self.checkKey(xapi)
        finally:
            self.host.logoutAPISession(session)

    def run(self, arglist):

        self.doAction()

        # Check the flag
        session = self.host.getAPISession()
        xapi = session.xenapi
        try:
            self.checkKey(xapi)
        finally:
            self.host.logoutAPISession(session)

    def postRun(self):
        session = self.host.getAPISession()
        xapi = session.xenapi
        try:
            smref = xapi.SM.get_by_name_label("ISO")[0]
            xapi.SM.remove_from_other_config(smref, "HideFromXenCenter")
        finally:
            self.host.logoutAPISession(session)

    def doAction(self):
        raise xenrt.XRTError("Not implemented") 


class TC8813(_TCHideFromXenCenter):
    """Verify a SM.other_config key persists across a xapi restart"""

    def doAction(self):
        # Restart xapi
        self.host.restartToolstack()
        time.sleep(60)

class TC8814(_TCHideFromXenCenter):
    """Verify a SM.other_config key persists across a host reboot"""

    def doAction(self):
        # Restart xapi
        self.host.reboot()
        time.sleep(60)

class TC8904(xenrt.TestCase):
    """Verify that application of a patch that's already applied is rejected"""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.hf = self.host.getTestHotfix(1)
        
        patchesBefore = self.host.minimalList("patch-list")
        self.host.applyPatch(self.hf)
        patchesAfter = self.host.minimalList("patch-list")
        self.uuid = filter(lambda x:not x in patchesBefore, patchesAfter)[0]
        
        self.host.execdom0("rm -f /root/hotfix-test1")

    def run(self, arglist=None):

        try:
            self.host.getCLIInstance().execute("patch-apply", "uuid=%s host-uuid=%s" % (self.uuid, self.host.getMyHostUUID()))
        except xenrt.XRTFailure, e:
            # Check we get the expected error
            if not re.search("This patch has already been applied", e.data):
                raise xenrt.XRTError("Expected failure attempting to apply patch for a second time, but with unexpected message", data=e.data)
        else:
            raise xenrt.XRTFailure("Allowed to apply a patch that had already been applied")

        # Verify it hasn't actually applied
        if self.host.execdom0("ls /root/hotfix-test1", retval="code") == 0:
            raise xenrt.XRTFailure("Second application of patch failed as expected, however patch executed anyway")

class TC8912(xenrt.TestCase):
    """Verify snmpd can be started in dom0."""

    def prepare(self, arglist=None):
        self.wasrunning = False
        self.host = self.getDefaultHost()
        data = self.host.execdom0("service snmpd status | cat")
        if "running" in data:
            self.wasrunning = True
            self.host.execdom0("service snmpd stop")

    def run(self, arglist=None):
        # Start the snmpd service
        self.host.execdom0("service snmpd start")

        # Make sure the snmpd service is reported as running
        data = self.host.execdom0("service snmpd status | cat")
        if not "running" in data:
            raise xenrt.XRTFailure("snmpd service is not running")

        # Make sure the snmpd process is running
        data = self.host.execdom0("ps axw")
        if not "snmpd" in data:
            raise xenrt.XRTFailure("snmpd process is not running")

    def postRun(self):
        if self.host and not self.wasrunning:
            self.host.execdom0("service snmpd stop")

class TC8913(xenrt.TestCase):
    """Enabling snmpd in dom0 using chkconfig should cause the service to start after a reboot"""

    def prepare(self, arglist=None):
        self.wasrunning = False
        self.wasenabled = False
        self.host = self.getDefaultHost()
        data = self.host.execdom0("service snmpd status | cat")
        if "running" in data:
            self.wasrunning = True
        if self.host.snmpdIsEnabled():
            self.wasenabled = True

    def run(self, arglist=None):
        # Enable snmpd service
        self.host.enableSnmpd()

        # Reboot
        self.host.reboot()

        # Check the service is still enabled
        if not self.host.snmpdIsEnabled():
            raise xenrt.XRTFailure("snmpd service disabled after reboot")

        # Make sure the snmpd service is reported as running
        data = self.host.execdom0("service snmpd status | cat")
        if not "running" in data:
            raise xenrt.XRTFailure("snmpd service is not running")

        # Make sure the snmpd process is running
        data = self.host.execdom0("ps axw")
        if not "snmpd" in data:
            raise xenrt.XRTFailure("snmpd process is not running")

    def postRun(self):
        if self.host:
            if not self.wasrunning:
                self.host.execdom0("service snmpd stop")
            if not self.wasenabled:
                self.host.disableSnmpd()

class TC8914(xenrt.TestCase):
    """Dom0 SNMP (when enabled by hacking dom0) can be quiered for SNMPv2-MIB::sysContact and SNMPv2-MIB::sysLocation"""

    def prepare(self, arglist=None):
        self.oldconf = None
        self.wasrunning = True
        self.wasenabled = True
        self.host = self.getDefaultHost()
        data = self.host.execdom0("service snmpd status | cat")
        if not "running" in data:
            self.wasrunning = False
            self.host.execdom0("service snmpd start")
        if not self.host.snmpdIsEnabled():
            self.host.enableSnmpd()
            self.wasenabled = False

        # Back up the old config
        oldconf = self.host.hostTempFile() + ".bak"
        self.host.execdom0("mv %s %s" % (self.host.SNMPCONF, oldconf))
        self.oldconf = oldconf

        # Make sure the firewall allows SNMP through
        self.host.execdom0("service iptables restart || true")
        for port in [161, 162]:
            self.host.execdom0("iptables -D RH-Firewall-1-INPUT -m state "
                               "--state NEW -m udp -p udp --dport %u "
                               "-j ACCEPT || true" % (port))
            self.host.execdom0("iptables -I RH-Firewall-1-INPUT 1 -m state "
                               "--state NEW -m udp -p udp --dport %u "
                               "-j ACCEPT" % (port))
        self.host.iptablesSave()

    def checkSNMP(self):
        for com in ["xenrtsnmprw", "xenrtsnmpro"]:
            for x in [("sysContact", "XenRT syscontact"),
                      ("sysLocation", "XenRT syslocation")]:
                oidbit, expected = x
                data = xenrt.command(\
                    "snmpget -v1 -c %s -Ovq %s SNMPv2-MIB::%s.0" %
                    (com, self.host.getIP(), oidbit))
                if not expected in data:
                    raise xenrt.XRTFailure(\
                        "Expected value not found for %s using %s" %
                        (oidbit, com))

    def run(self, arglist=None):
        # Create a new config
        txt = """rwcommunity xenrtsnmprw 0.0.0.0/0
rocommunity xenrtsnmpro 0.0.0.0/0
trapcommunity xenrtsnmptrap
syscontact XenRT syscontact
syslocation XenRT syslocation
"""
        # trapsink %s xenrtsnmptrap % (target.getIP())
        fn = xenrt.TEC().tempFile()
        f = file(fn, "w")
        f.write(txt)
        f.write(self.host.execdom0(\
            "grep -v -e '^syscontact' -e '^syslocation' %s" % (self.oldconf)))
        f.close()
        xenrt.TEC().copyToLogDir(fn, "snmpd.conf")
        sftp = self.host.sftpClient()
        try:
            sftp.copyTo(fn, self.host.SNMPCONF)
        finally:
            sftp.close()

        # Restart with the new config
        self.host.execdom0("service snmpd restart")
        
        # Make sure the snmpd service is reported as running
        data = self.host.execdom0("service snmpd status | cat")
        if not "running" in data:
            raise xenrt.XRTFailure("snmpd service is not running")

        # Make sure the snmpd process is running
        data = self.host.execdom0("ps axw")
        if not "snmpd" in data:
            raise xenrt.XRTFailure("snmpd process is not running")

        # Check the SNMPd can be reached
        data = xenrt.command(\
            "snmpget -v1 -c xenrtsnmpro -Ovq %s SNMPv2-MIB::sysDescr.0" %
            (self.host.getIP())).strip()
        if not data:
            raise xenrt.XRTFailure("Could not snmpget from host")
        self.runSubcase("checkSNMP", (), "snmpget", "initial")
        self.host.reboot()
        self.runSubcase("checkSNMP", (), "snmpget", "postreboot")

    def postRun(self):
        if self.host:
            if self.oldconf:
                self.host.execdom0("rm -f %s" % (self.host.SNMPCONF))
                self.host.execdom0("cp %s %s" % (self.oldconf, self.host.SNMPCONF))
            if self.wasrunning:
                self.host.execdom0("service snmpd restart")
            else:
                self.host.execdom0("service snmpd stop")
            if not self.wasenabled:
                self.host.disableSnmpd()

class TC9989(xenrt.TestCase):
    """Verify SNMP is disabled by default in Dom0."""

    def run(self, arglist=None):
        self.host = self.getDefaultHost()

        # Make sure the snmpd service is reported as stopped
        data = self.host.execdom0("service snmpd status | cat")
        if not "inactive" in data and not "stopped" in data:
            raise xenrt.XRTFailure("snmpd service is not stopped")

        # Make sure the snmpd process is not running
        data = self.host.execdom0("ps axw")
        if "snmpd" in data:
            raise xenrt.XRTFailure("snmpd process is running")

        # Make sure the snmpd service is not enabled
        if self.host.snmpdIsEnabled():
            raise xenrt.XRTFailure("snmpd service is enabled")

class _SNMPConfigTest(xenrt.TestCase):
    MIB_II_SUBTREES = ["system",
                       "interfaces",
                       "at",
                       "ip",
                       "icmp",
                       "tcp",
                       "udp",
                       "snmp"]

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()

        # Get the contents of the SNMP configuration file
        self.snmp_config_data = self.host.execdom0("cat %s" % (self.host.SNMPCONF))
        self.snmp_config_lines = str(self.snmp_config_data).splitlines()

class TC9990(_SNMPConfigTest):
    """Verify the SNMP default configuration file contains the list of supported MIB-II sub-trees"""

    def run(self, arglist=None):
        # Check that all the subtrees are defined in the configuration file
        missing_subtrees = [] 
        for subtree in self.MIB_II_SUBTREES:
            subtreeInConfigFile = False
            for line in self.snmp_config_lines:
                r = re.match(r'view\s+\S+\s+included\s+%s' % subtree, line)
                if r:
                    subtreeInConfigFile = True
                    break
            if not subtreeInConfigFile:
                missing_subtrees.append(subtree)
 
        if missing_subtrees:
            raise xenrt.XRTFailure("MIB-II subtrees not defined in %s: %s" % 
                                   (self.host.SNMPCONF, ", ".join(missing_subtrees)))

class TC9991(_SNMPConfigTest):
    """Verify the SNMP default configuration file does not contain unsupported components"""

    def run(self, arglist=None):
        # Check that the default configuration file does not contain unsupported components
        unsupported_subtrees = []
        for line in self.snmp_config_lines:
            r = re.match(r'view\s+\S+\s+included\s+(\S+)', line)
            if r:
                subtree = r.group(1)
                if subtree not in self.MIB_II_SUBTREES and subtree != ".1":
                    unsupported_subtrees.append(subtree)

        if unsupported_subtrees:
            raise xenrt.XRTFailure("Unsupported SNMP components found in %s: %s" % 
                                   (self.host.SNMPCONF, ", ".join(unsupported_subtrees)))

class TC9992(_SNMPConfigTest):
    """Verify the SNMP default configuration file restricts write access to the views"""

    def run(self, arglist=None):
        # Check that the default configuration restricts write access to the set of MIB-II
        for line in self.snmp_config_lines:
            r = re.match(r'access\s+(\S+)\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+(\S+)\s+\S+', line)
            if r:
                group = r.group(1)
                write_view = r.group(2)
                if write_view != "none":
                    raise xenrt.XRTFailure("Group %s has write access to the %s view" % 
                                           (group, write_view))

class TC9993(_SNMPConfigTest):
    """Retrieve the management values of all the supported MIB-II subtrees using snmpwalk"""

    def prepare(self, arglist=None):
        _SNMPConfigTest.prepare(self, arglist)
        self.community = None
        self.wasrunning = True
        self.wasenabled = True
        data = self.host.execdom0("service snmpd status | cat")
        if not "running" in data:
            self.wasrunning = False
            self.host.execdom0("service snmpd start")
            xenrt.TEC().logverbose("Waiting 60s after starting snmpd (CA-70508)...")
            time.sleep(60)
        if not self.host.snmpdIsEnabled():
            self.host.enableSnmpd()
            self.wasenabled = False

        # Make sure the firewall allows SNMP through
        self.host.execdom0("service iptables restart || true")
        for port in [161, 162]:
            self.host.execdom0("iptables -D RH-Firewall-1-INPUT -m state "
                               "--state NEW -m udp -p udp --dport %u "
                               "-j ACCEPT || true" % (port))
            self.host.execdom0("iptables -I RH-Firewall-1-INPUT 1 -m state "
                               "--state NEW -m udp -p udp --dport %u "
                               "-j ACCEPT" % (port))
        self.host.iptablesSave()

        # Find the community name
        for line in self.snmp_config_lines:
            r = re.match(r'com2sec\s+\S+\s+\S+\s+(\S+)', line)
            if r:
                self.community = r.group(1)
                break

    def run(self, arglist=None):
        if not self.community:
            raise xenrt.XRTFailure("Community name not found in %s" % (self.host.SNMPCONF))

        # Make sure the snmpd service is reported as running
        data = self.host.execdom0("service snmpd status | cat")
        if not "running" in data:
            raise xenrt.XRTFailure("snmpd service is not running")

        # Make sure the snmpd process is running
        data = self.host.execdom0("ps axw")
        if not "snmpd" in data:
            raise xenrt.XRTFailure("snmpd process is not running")

        # Retrieve MIB-II subtrees values using snmpwalk
        subtrees_without_data = []
        for subtree in self.MIB_II_SUBTREES:
            data = xenrt.command(\
                "snmpwalk -v 2c -c %s %s %s" %
                (self.community, self.host.getIP(), subtree))
            if not data:
                raise xenrt.XRTFailure("Could not snmpwalk from host")
            if "%s = No Such Object available on this agent at this OID" % subtree in data:
                subtrees_without_data.append(subtree)

        if subtrees_without_data:
            raise xenrt.XRTFailure(\
                "SNMP agent returned no values, using the %s community, for: %s" %
                (self.community, ", ".join(subtrees_without_data)))

    def postRun(self):
        if self.host:
            if self.wasrunning:
                self.host.execdom0("service snmpd restart")
            else:
                self.host.execdom0("service snmpd stop")
            if not self.wasenabled:
                self.host.disableSnmpd()

class TC9995(TC9993):
    """Stress test system with large number of VIFs while SNMP daemon is processing queries"""

    NUMBER_VMS = 10
    MEMORY = 256
    ITERATIONS = 2 
    CLITIMEOUT = 1800
    ALLOWED_DIFF = 0.1 # 10%
    SNMP_QUERY_INTERVAL = 5 # seconds

    def prepare(self, arglist=None):
        TC9993.prepare(self, arglist)

        self.guests = []

        # Create a guest which we'll use to clone
        guest = self.host.createGenericLinuxGuest(memory=self.MEMORY)
        self.uninstallOnCleanup(guest)
        self.guests.append(guest)

        # Determine how many VIFs we can add to the guest
        vifdevices = self.host.genParamGet("vm",
                                           guest.getUUID(),
                                           "allowed-VIF-devices").split("; ")
        vifsToAdd = len(vifdevices)

        # Add VIFs to the guest
        bridge = self.host.getPrimaryBridge()
        for i in range(vifsToAdd):
            vif = guest.createVIF(None, bridge, None)
            guest.plugVIF(vif)

        guest.preCloneTailor()
        guest.shutdown()

        # Clone the guest
        for i in range(1, self.NUMBER_VMS):
            if i % 20 == 0:
                # CA-19617 Perform a vm-copy every 20 clones
                g = guest = guest.copyVM()
            else:
                g = guest.cloneVM()
            g.start()
            g.shutdown()
            self.uninstallOnCleanup(g)
            self.guests.append(g)

    def multipleStartShutdown(self, startTimer, shutdownTimer):
        # Test start/shutdown using --multiple.

        i = 0
        try:
            while i < self.ITERATIONS:
                xenrt.TEC().logverbose("start/stop loop iteration %u" % (i))
                self.host.listDomains()
                c = copy.copy(self.guests)
                xenrt.lib.xenserver.startMulti(c,
                                               no_on=True,  
                                               clitimeout=self.CLITIMEOUT,
                                               timer=startTimer)
                if len(c) != len(self.guests):
                    raise xenrt.XRTFailure("One or more VMs did not start",
                                           str(len(self.guests) - len(c)))
                self.host.listDomains()
                c = copy.copy(self.guests)
                xenrt.lib.xenserver.shutdownMulti(c,
                                                  clitimeout=self.CLITIMEOUT,
                                                  timer=shutdownTimer)
                if len(c) != len(self.guests):
                    raise xenrt.XRTFailure("One or more VMs did not shutdown",
                                           str(len(self.guests) - len(c)))
                i += 1
                if xenrt.GEC().abort:
                    xenrt.TEC().warning("Aborting on command")
                    break
        finally:
            xenrt.TEC().comment("%u/%u start/stop iterations successful" %
                                (i, self.ITERATIONS))
            xenrt.TEC().logverbose("Start times: %s" % (startTimer.measurements))
            xenrt.TEC().logverbose("Shutdown times: %s" % (shutdownTimer.measurements))

    def run(self, arglist=None):
        if not self.community:
            raise xenrt.XRTFailure("Community name not found in %s" % (self.host.SNMPCONF))

        # Make sure the snmpd service is reported as running
        data = self.host.execdom0("service snmpd status | cat")
        if not "running" in data:
            raise xenrt.XRTFailure("snmpd service is not running")

        # Make sure the snmpd process is running
        data = self.host.execdom0("ps axw")
        if not "snmpd" in data:
            raise xenrt.XRTFailure("snmpd process is not running")

        # Run multiple VM start/shutdown operations while running snmp queries
        snmpqueries = xenrt.RunCommandPeriodically("snmpwalk -v 2c -c %s %s" %
                                      (self.community, self.host.getIP()),
                                      self.SNMP_QUERY_INTERVAL)
        snmpqueries.start()
        snmpStartTimer = xenrt.Timer()
        snmpShutdownTimer = xenrt.Timer()
        self.multipleStartShutdown(snmpStartTimer, snmpShutdownTimer)
        snmpqueries.stop()

        if snmpqueries.exception:
            raise snmpqueries.exception

        # Run multiple VM start/shutdown operations with snmp daemon stopped
        self.host.execdom0("service snmpd stop")
        nonsnmpStartTimer = xenrt.Timer()
        nonsnmpShutdownTimer = xenrt.Timer()
        self.multipleStartShutdown(nonsnmpStartTimer, nonsnmpShutdownTimer)

        self.host.execdom0("service snmpd start")

        # Compare snmp and non-snmp start/shudown times
        snmpStartTime       = sum(snmpStartTimer.measurements)
        snmpShutdownTime    = sum(snmpShutdownTimer.measurements)
        nonsnmpStartTime    = sum(nonsnmpStartTimer.measurements)
        nonsnmpShutdownTime = sum(nonsnmpShutdownTimer.measurements)

        startDiff    = float(snmpStartTime-nonsnmpStartTime)/nonsnmpStartTime
        shutdownDiff = float(snmpShutdownTime-nonsnmpShutdownTime)/nonsnmpShutdownTime

        exceededDiff = []

        if startDiff > self.ALLOWED_DIFF:
            exceededDiff.append("%u iteration(s) of %u VM starts took %us "
               "on snmp-enabled system. With snmp stopped, it took %us." %
               (self.ITERATIONS, self.NUMBER_VMS, snmpStartTime, nonsnmpStartTime))

        if shutdownDiff > self.ALLOWED_DIFF:
            exceededDiff.append("%u iteration(s) of %u VM shutdowns took %us "
               "on snmp-enabled system. With snmp stopped, it took %us." %
               (self.ITERATIONS, self.NUMBER_VMS, snmpShutdownTime, nonsnmpShutdownTime))

        if exceededDiff:
            raise xenrt.XRTFailure("VM operations ran more than %.1f%% slower "
                 "when snmpd process is actively being queried (snmpwalk every "
                 "%u secs) than when snmpd is stopped" % 
                 (self.ALLOWED_DIFF*100, self.SNMP_QUERY_INTERVAL),
                 "\n".join(exceededDiff))

class _Dom0FileCheck(xenrt.TestCase):
    """Check one or more specified files exists in domain 0"""

    FILES = []

    def run(self, arglist):
        host = self.getDefaultHost()
        missing = []
        for f in self.FILES:
            if host.execdom0("test -e %s" % (f), retval="code") != 0:
                missing.append(f)
        if len(missing) > 0:
            raise xenrt.XRTFailure("File(s) missing from dom0: %s" %
                                   (string.join(missing)))

class TC9123(_Dom0FileCheck):
    """Check /usr/bin/expect exists in dom0"""

    FILES = ["/usr/bin/expect"]


class _HostMemoryVerif(xenrt.TestCase):
    """Verify XenServer's host memory limitation is valid and detect the hard
    memory limitation if possible.

    All the basic memory units used in this test and following code will be mega
    bytes, to allow inaccuracy to certain degree.

    """

    WINDOWSGUEST = True
    ARCH = "x86-32"

    WINPROPOVERHEAD =  1.01
    LINUXPROPOVERHEAD = 1.0

    # We'll use ext type storage, so we don't care about disk limitation for the moment.

    def prepare(self, arglist):

        args = xenrt.util.strlistToDict(arglist)
        self.host = self.getDefaultHost()
        
        if args.has_key('distro'):
            if self.WINDOWSGUEST and "wv".find(args['distro'][0]) < 0:
                raise xenrt.XRTError("The expected guest type of this testcase is Windows, "
                                     "only Windows distributions should be specified.")
            self.DISTRO = args['distro']
        else:
            distro_key = "GENERIC" + (self.WINDOWSGUEST and "_WINDOWS" or "_LINUX") + "_OS" \
                         + (self.ARCH.endswith("64") and "_64" or "")
            self.DISTRO = self.host.lookup(distro_key)

        self.host_max_vm = int(self.host.lookup("MAX_CONCURRENT_VMS", "50"))

        self.host_mem = self.host.getTotalMemory()
        self.host_mem_limit = int(self.host.lookup("MAX_HOST_MEMORY", "131072"))

        self.host_mem_free_actual = self.host.getFreeMemory()
        self.host_mem_free_computed = int(self.host.paramGet("memory-free-computed")) / xenrt.MEGA 

        self.base_mem_base_actual = self.host_mem - self.host_mem_free_actual
        self.base_mem_base_computed = self.host_mem - self.host_mem_free_computed

        self.vm_mem_all_spec = 0
        self.vm_mem_all_computed = 0
        self.vm_mem_overhead = self.WINDOWSGUEST and self.WINPROPOVERHEAD or self.LINUXPROPOVERHEAD


        self.vm_mem_min = max(int(self.host.lookup("MIN_VM_MEMORY", "128")),
                              int(xenrt.TEC().lookup(["GUEST_LIMITATIONS", self.DISTRO, "MINMEMORY"],
                                                     str(self.WINDOWSGUEST and "512" or "512"))),
                              int(self.host.lookup(["VM_MIN_MEMORY_LIMITS", self.DISTRO], "0")))

        # For quick test only
        # self.vm_mem_min = 8 * xenrt.GIGA / xenrt.MEGA
                                                     
        self.vm_mem_max = min(int(self.host.lookup("MAX_VM_MEMORY", "32768")),
                              int(xenrt.TEC().lookup(["GUEST_LIMITATIONS", self.DISTRO, "MAXMEMORY"],
                                                     str(self.WINDOWSGUEST and "4096" or "16384"))))

        self.verify_object = min(self.host_mem, self.host_mem_limit)

        self.guests = []

        self.guesttpl = self.host.createBasicGuest(name=self.DISTRO, 
                                                   distro=self.DISTRO,
                                                   arch=self.ARCH,
                                                   memory=self.vm_mem_min)
        self.uninstallOnCleanup(self.guesttpl)
        self.guesttpl.preCloneTailor()
        self.guesttpl.shutdown()

        # For quick test only
        # self.guesttpl = self.host.getGuest(self.DISTRO)

    def estimate(self, mem, safe_extra=0.0):
        return int(mem * (self.vm_mem_overhead + safe_extra))

    def deduce(self, mem, safe_extra=0.0):
        return int(mem / (self.vm_mem_overhead + safe_extra))

    def createVM(self, mem):

        mem_info = {}
        mem_info['vm_mem_spec'] = mem
        
        time.sleep(60)
        mem_info['host_mem_free_actual'] = self.host.getFreeMemory()
        mem_info['host_mem_free_computed'] = int(self.host.paramGet('memory-free-computed'))/xenrt.MEGA
        
        vm = self.guesttpl.cloneVM()
        self.uninstallOnCleanup(vm)
        vm.memset(mem_info['vm_mem_spec'])
        vm.start()
        
        time.sleep(60)
        mem_info['vm_mem_guest'] = vm.getGuestMemory()
        mem_info['vm_mem_domain'] = vm.getDomainMemory()
        mem_info['host_mem_later_actual'] = self.host.getFreeMemory()
        mem_info['host_mem_later_computed'] = int(self.host.paramGet('memory-free-computed'))/xenrt.MEGA
        mem_info['vm_mem_actual'] = mem_info['host_mem_free_actual'] - mem_info['host_mem_later_actual']
        mem_info['vm_mem_computed'] = mem_info['host_mem_free_computed'] - mem_info['host_mem_later_computed']
        mem_info['vm_mem_estimated'] = self.estimate(mem_info['vm_mem_spec'])

        self.guests.append(mem_info)
        self.vm_mem_all_spec += mem_info['vm_mem_spec']
        self.vm_mem_all_computed += mem_info['vm_mem_computed']
        self.vm_mem_overhead = float(self.vm_mem_all_computed) / self.vm_mem_all_spec
        
        self.host_mem_free_actual = mem_info['host_mem_later_actual']
        self.host_mem_free_computed = mem_info['host_mem_later_computed']

        xenrt.TEC().logverbose("The memory information of the newly created VM is: %s" % mem_info)
        return mem_info

    def checkVM(self, mem_info):

        reason = []

        # For the moment, only cases without balloning are considered

        # Current dual-compatible mode:
        if not (-1 <= abs(mem_info['vm_mem_spec'] - mem_info['vm_mem_guest'])<= 8 + 1):
        # When non-ballooning versions are dropped:
        # if abs(mem_info['mem_mem_guest'] + 4 - mem_info['vm_mem_spec']) > 1:
            reason.append(
                "VM's memory inspected inside VM is far different from its memory specification")
        # Current dual-compatible mode:
        if not(mem_info['vm_mem_spec'] - 1 <= mem_info['vm_mem_domain'] <= mem_info['vm_mem_spec'] + 4 + 1):
        # When non-ballooning versions are dropped:
        # if abs(mem_info['vm_mem_domain'] - mem_info['vm_mem_spec']) > 1:
            reason.append(
                "VM's memory inspected by dom0 is far different from its memory specification")
        if not (mem_info['vm_mem_spec'] -1 <= mem_info['vm_mem_actual'] <= mem_info['vm_mem_computed'] + 1):
            reason.append(
                "VM's actual memory occupation is not within a resonable range between its specification and XAPI's perservation")
        if abs(mem_info['vm_mem_estimated'] - mem_info['vm_mem_computed']) > 0.01 * mem_info['vm_mem_spec']:
            xenrt.TEC().warning(
                "VM's memory occupation estimation is far different from XAPI's computation")
        if reason:
            raise xenrt.XRTFailure("; ".join(reason), data = mem_info)


    def verify(self):

        mem_remain = self.verify_object - (self.host_mem - self.host_mem_free_computed)

        while mem_remain > self.estimate(self.vm_mem_min):   
            if mem_remain <= 2 * self.estimate(self.vm_mem_min):
                mem = self.deduce(mem_remain, safe_extra=0.01)
            else:
                mem = min(self.deduce(mem_remain /2), self.vm_mem_max)
            mem_info = self.createVM(mem)
            self.checkVM(mem_info)
            mem_remain = self.verify_object - (self.host_mem - self.host_mem_free_computed)

        if self.verify_object - self.host_mem_free_computed > 0.05 * self.vm_mem_min:
            xenrt.TEC().warning("The verifiy plan (esp. the overhead parameters) is not so accurate.")

        xenrt.TEC().logverbose("At the end of verification, the memory information of all guests are:\n"
                               "%s" % "\n".join(map(lambda g:str(g), self.guests)))

    def detect(self):

        reason = None
        while reason is None:
            if self.host_mem_free_computed < self.estimate(self.vm_mem_min):
                reason = "Can't detect the hard memory limitation within current machine's memory range"
            elif self.host_max_vm <= len(self.guests):
                reason = "Can't detect the hard memory limitation due to the limitation on the maxinum parallel VMs"
            else:
                mem = self.deduce(self.host_mem_free_computed / (self.host_max_vm - len(self.guests)), safe_extra=0.01)
                try:
                    mem_info = self.createVM(mem)
                except Exception,e:
                    reason = "The hard memory limit for %s (%s) running on %s is between %u Mb and %u Mb, an exception %s is raised" % (self.DISTRO, self.ARCH, self.host.productVersion, self.host_mem - self.host_mem_free_actual, self.host_mem - self.host_mem_free_actual + self.estimate(mem), e)
                else:
                    self.checkVM(mem_info)
        xenrt.TEC().comment(reason)

    def run(self, arglist):
        self.verify()
        self.detect()
    
    
class TC9347(_HostMemoryVerif):
    WINDOWSGUEST = True
    ARCH = "x86-32"

class TC9348(_HostMemoryVerif):
    WINDOWSGUEST = True
    ARCH = "x86-64"

class TC9349(_HostMemoryVerif):
    WINDOWSGUEST = False
    ARCH = "x86-32"

class TC9350(_HostMemoryVerif):
    WINDOWSGUEST = False
    ARCH = "x86-64"

class TC10171(xenrt.TestCase):
    """Dom0 should contain no symlinks to /obj/... paths"""

    def run(self, arglist):
        host = self.getDefaultHost()
        data = host.execdom0("find / -xdev -type l 2> /dev/null | "
                             "xargs -n1 readlink | grep '^/obj/' | cat")
        if data.strip():
            raise xenrt.XRTFailure("Found one or more dom0 symlinks to "
                                   "/obj/...")

class _TCHostShutdown(xenrt.TestCase):
    SHUTDOWN_CMDS = ["xe host-disable", "xe host-shutdown"]

    def run(self,arglist):
        host = self.getDefaultHost()
        for c in self.SHUTDOWN_CMDS:
            host.execdom0(c)
        time.sleep(300)
        try:
            host.waitForSSH(300)
        except:
            pass
        else:
            raise xenrt.XRTFailure("Host rebooted rather than shut down")

class TC14903(_TCHostShutdown):
    SHUTDOWN_CMDS = ["xe host-disable", "xe host-shutdown"]

class TC14904(_TCHostShutdown):
    SHUTDOWN_CMDS = ["shutdown -h +0"]

class _TCHostPowerON(xenrt.TestCase):
    """Test the Host Power On API calls.  Testcases for using the default Wake On Lan and for HP's iLo
    Also available are Dell's DRAC and a Custom call for later implimentation if needed"""
    
    POWERONMETHOD = ''
    RUNAGAIN = False
    DISABLED = False
    CUSTOM = False
    
    def poweron(self,name,slaves,timeout):
        now = xenrt.util.timenow()
        deadline = now + timeout
        self.cli.execute("host-power-on","host=%s" % (name))

        checking = True
        while checking is True:
            try:
                slaves.waitForSSH(1)
            except:
                if xenrt.util.timenow() > deadline:
                    raise xenrt.XRTFailure("Unable to power-on host %s.  The "
                                           "timeout had been reached" % (name))
                else: checking = True
            else:
                checking = False

    def poweroff(self,name,slaves,timeout):
        try:
            self.cli.execute("host-disable","host=%s" % (name))
            self.cli.execute("host-shutdown","host=%s" % (name))
        except Exception,e:
            raise xenrt.XRTFailure("Unable to shutdown host %s because: %s" %
                                   (name,str(e)))
        now = xenrt.util.timenow()
        deadline = now + timeout
        while True: 
            try:
                slaves.checkReachable()
                if xenrt.util.timenow() > deadline:
                    raise xenrt.XRTFailure("Host: %s was unable to shutdown" %
                                           (name))
            except:
                break
    
    def cleanup(self):
        xenrt.TEC().logverbose("Cleaning up all Slaves in the pool")
        for name, slave in self.pool.slaves.iteritems():
            slave.poweroff()
            slave.poweron()
            
    def isAlive(self):
        xenrt.TEC().logverbose("Verifying all Slaves in the Pool are Alive "
                               "and Well")
        for name, slaves in self.pool.slaves.iteritems():
            try:
                slaves.checkReachable()
            except:
                self.cleanup()
    
    def run(self, arglist):
        self.pool = self.getDefaultPool()
        self.cli = self.pool.master.getCLIInstance()
        self.isAlive()
        for name, slaves in self.pool.slaves.iteritems():
            self.poweroff(name,slaves,timeout=240)            
            time.sleep(60)
            counter = 0
            if self.RUNAGAIN:
                self.poweron(name,slaves,timeout=240)
                try:
                    self.poweron(name,slaves,timeout=240)
                    raise xenrt.XRTFailure(\
                        "No failure observed while attempting to power on a "
                        "host that is already powered on")

                except xenrt.XRTFailure, e:
                    if e.data and "This operation cannot be completed as " \
                                  "the host is still live" in str(e.data):
                        xenrt.TEC().comment("Expected XRTFailure Exception "
                                            "received: %s" % (str(e.data)))
                    else:
                        # Propogate this exception.
                        xenrt.TEC().comment(\
                            "Trying to power on a host that is powered on "
                            "resulted in unexpected exception: "
                            "%s" % (str(e.data)))
                        raise e
            
            elif self.CUSTOM:
                try: 
                    self.cli.execute("host-power-on","host=%s" % (name))
                    raise xenrt.XRTFailure(\
                        "Host power on using a 3rd party plug-in "
                        "unexpectedly succeeded")

                except xenrt.XRTFailure,e:
                    if e.data and "Failure(\"The host failed to power on.\")" \
                       in str(e.data):
                        xenrt.TEC().comment("Expected XRTFailure Exception "
                                            "received: %s" % (str(e.data)))
                    else: 
                        # Propogate this exception.
                        xenrt.TEC().comment(\
                            "Unexpected XRTFailure Exception when attempting "
                            "to power on a host using a 3rd party plug-in "
                            "%s" % (str(e.data)))
                        raise e  

            elif self.DISABLED:
                try: 
                    self.poweron(name,slaves,timeout=240)
                    raise xenrt.XRTFailure(\
                        "Host power on when power on is disabled unexpectedly "
                        "succeeded")
                except xenrt.XRTFailure, e:
                    if e.data and ("HOST_POWER_ON_NOT_CONFIGURED" \
                       in str(e.data) or "host power on mode is disabled" in str(e.data)):
                        xenrt.TEC().comment("Expected XRTFailure Exception "
                                            "received: %s" % (str(e.data)))
                    else:
                        # Propogate this exception.
                        xenrt.TEC().comment(\
                            "Unexpected XRTFailure Exception when attempting "
                            "to power on a host when power on is disabled "
                            "%s" % (str(e.data)))
                        raise e  
            else:
                self.poweron(name,slaves,timeout=240)
    
    def postRun(self):
        self.cleanup() 

class TC10181(_TCHostPowerON):
    """Testcase for Host Power On over wake-on-lan"""
    
    POWERONMETHOD = 'wake-on-lan'
    
    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        cli = self.pool.getCLIInstance()
        if self.POWERONMETHOD == 'wake-on-lan':
            for name, host in self.pool.slaves.iteritems():
                cli.execute("host-set-power-on-mode",
                            "power-on-mode='wake-on-lan' host='%s'" % (name))
    
class TC10182(_TCHostPowerON):
    """Testcase for Host Power On over HP's iLo"""
    
    POWERONMETHOD = 'iLO'
    
    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        cli = self.pool.getCLIInstance()
        if self.POWERONMETHOD == 'iLO':
            for name, host in self.pool.slaves.iteritems ():
                powerOnUser = host.lookup("ILO_USERNAME",None)
                powerOnPassword = host.lookup("ILO_PASSWORD",None)
                powerOnIP = host.lookup("ILO_ADDRESS",None)
                if powerOnIP is None:
                    raise xenrt.XRTError(\
                        "The iLo is not configured for this Host")
                # Need to define a secret for the password
                secret = cli.execute("secret-create",
                                     "value='%s'" % (powerOnPassword)).strip()
                args = []
                args.append("power-on-mode=%s" % (self.POWERONMETHOD))
                args.append("host=%s" % (name))
                args.append("power-on-config:power_on_user=%s" % (powerOnUser))
                args.append("power-on-config:power_on_password_secret=%s" %
                            (secret))
                args.append("power-on-config:power_on_ip=%s" % (powerOnIP))
                cli.execute("host-set-power-on-mode", string.join(args))
        else:
            raise xenrt.XRTError("Do not know how to enable power on method %s"
                                                            % (self.POWERONMETHOD))

class TC21632(_TCHostPowerON):
    """Test Case for Host Power On over Dell's DRAC."""

    POWERONMETHOD = 'DRAC'
    UNSATISFIED_DEPENDENCY = False
    
    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        cli = self.pool.getCLIInstance()

        for arg in arglist:
            if arg.startswith('unsatisfieddependency'):
                self.UNSATISFIED_DEPENDENCY = True

        if self.POWERONMETHOD == 'DRAC':
            for name, host in self.pool.slaves.iteritems():
                powerOnUser = host.lookup("IPMI_USERNAME",None)
                powerOnPassword = host.lookup("IPMI_PASSWORD",None)
                powerOnIP = host.lookup("BMC_ADDRESS",None)

                secret = cli.execute("secret-create",
                                     "value=%s" % (powerOnPassword).strip())
                args = []
                args.append("power-on-mode=%s" % (self.POWERONMETHOD))
                args.append("host=%s" % (name))
                args.append("power-on-config:power_on_user=%s" % (powerOnUser))
                args.append("power-on-config:power_on_ip=%s" % (powerOnIP))
                args.append("power-on-config:power_on_password_secret=%s" % (secret))
                
                cli.execute("host-set-power-on-mode", string.join(args))
        else:
            raise xenrt.XRTError("Do not know how to enable power on method %s"
                                                            % (self.POWERONMETHOD))

        # Install Dell OpenManage (OM) Supplemental Pack on pool master.
        self.installDellOpenManage()

    def installDellOpenManage(self):
        """Installs Dell OpenManage Supplemental Pack"""

        # Get the OpenManage Supplemental Pack from distmaster and install.
        self.pool.master.execdom0("wget -nv '%sdellomsupppack.tgz' -O - | tar -zx -C /tmp" %
                                                (xenrt.TEC().lookup("TEST_TARBALL_BASE")))
        productVersion = self.pool.master.productVersion.lower().strip()
        if productVersion == 'cream':    # Cream is Service Pack 1 for Creedence.
            productVersion = 'creedence' # Hence no change in Dell OpenManage Supppack.

        dellomSupppack = "dellomsupppack-%s.iso" % productVersion
        self.pool.master.execdom0("mv /tmp/dellomsupppack/%s /root" % dellomSupppack)

        if self.UNSATISFIED_DEPENDENCY:
            # A timeout of 3 minutes in expect script to allow the OM to install.
            script = """#!/usr/bin/expect
    set timeout 180
    set cmd [lindex $argv 0]
    set iso [lindex $argv 1]
    spawn $cmd $iso
    expect -exact "(Y/N)"
    sleep 5
    send -- "Y\r"
    expect -exact "Pack installation successful"
    expect eof
    """
            self.pool.master.execdom0("echo '%s' > script.sh; exit 0" % script)
            self.pool.master.execdom0("chmod a+x script.sh; exit 0")
            commandOutput = self.pool.master.execdom0("/root/script.sh xe-install-supplemental-pack %s" % dellomSupppack)
        else:
            commandOutput = self.pool.master.execdom0("xe-install-supplemental-pack %s" % dellomSupppack)

        xenrt.sleep(30) # Allowing OM to settle before Xapi restart.
        
        if re.search("Pack installation successful", commandOutput):
                xenrt.TEC().logverbose("Dell OpenManage Supplemental Pack is successfully installed on master %s" % self.pool.master)
        else:
            raise xenrt.XRTFailure("Failed to install Dell OpenManage Supplemental Pack on master")

        # Retart toolstack
        self.pool.master.restartToolstack()

class TC10811(_TCHostPowerON):
    """Testcase Exsures power control is disabled for a host"""
    
    DISABLED = True
    
    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        cli = self.pool.getCLIInstance()
        for name, host in self.pool.slaves.iteritems():
            cli.execute("host-set-power-on-mode",
                        "power-on-mode='' host=%s" % (name))
            
class TC10812(TC10181):
    """PowerOn Machine that is already powered on"""
    
    RUNAGAIN = True

class TC10813(_TCHostPowerON):
    """Power On Machine using 3rd Party Script"""
    
    CUSTOM = True
    
    def prepare(self, arglist):
        """instlal 3rd party scripts"""
        self.pool = self.getDefaultPool()
        cli = self.pool.getCLIInstance()
        plugin = """
import XenAPI 
def custom(session,remote_host, power_on_config): 
    result = True 
    for key in power_on_config.keys(): 
        result=result+'' 
        key=''+key+'' 
        value=''+power_on_config[key] 
    return str(result)
"""
        sftp = self.pool.master.sftpClient()
        try:
            t = xenrt.TEC().tempFile()
            f = file(t, "w")
            f.write(plugin)
            f.close()
            sftp.copyTo(t, "/etc/xapi.d/plugins/hpocustom.py")
        finally:
            sftp.close()
        self.pool.master.execdom0("chmod +x /etc/xapi.d/plugins/hpocustom.py")
        self.pool.master.restartToolstack()
        time.sleep(60)
        self.pool.master.checkReachable()
        self.isAlive()
        for name, host in self.pool.slaves.iteritems():
            cli.execute("host-set-power-on-mode",
                        "power-on-mode='hpocustom' host=%s" % (name))
    
 
class TC10814(TC10181):
    """Check allowed_operations for correct values"""
    def run(self, arglist):
        cli = self.pool.getCLIInstance()
        for name, host in self.pool.slaves.iteritems():
            params = cli.execute("host-list",
                                 "name-label='%s' params=all" % (name))
            r = re.search("power-on-mode \( RO\): (\S+)", params)
            if not r:
                raise xenrt.XRTFailure("power-on-mode not shown correctly in "
                                       "host params")

class TC26941(xenrt.TestCase):
    """Test that the list of templates matches the expected list"""

    def run(self, arglist=None):
        host = self.getDefaultHost()
        version = host.productVersion

        hostTemplates = host.minimalList("template-list", params="name-label", args="other-config:default_template=true")
        # The expected templates are the first entry in the list of templates for the host's XenServer version
        expectedTemplates = [xenrt.TEC().lookup(["VERSION_CONFIG", version, x]).split(",")[0] for x in xenrt.TEC().lookup(["VERSION_CONFIG", version]).keys() if x.startswith("TEMPLATE_") and xenrt.TEC().lookup(["VERSION_CONFIG", version, x])]

        missing = []
        unexpected = []

        for t in expectedTemplates:
            if t not in hostTemplates:
                missing.append(t)
        
        for t in hostTemplates:
            if t not in expectedTemplates:
                unexpected.append(t)

        failure = []
        if missing:
            failure.append("Template(s) %s missing from host" % ", ".join(missing))
        if unexpected:
            failure.append("Template(s) %s on host are unexpected" % ", ".join(unexpected))

        if failure:
            raise xenrt.XRTFailure(" and ".join(failure))



class _TemplateExists(xenrt.TestCase):
    """Check a specific template exists or doesn't exist."""

    TEMPLATE_NAME = None
    TEMPLATE_NAME_MNR = None
    SHOULD_EXIST = True
    CHECK_FIELDS = []
    
    def run(self, arglist):

        host = self.getDefaultHost()
        if isinstance(host, xenrt.lib.xenserver.MNRHost) and self.TEMPLATE_NAME_MNR:
            expected = self.TEMPLATE_NAME_MNR
        else:
            expected = self.TEMPLATE_NAME
        templates = host.minimalList("template-list", "name-label")
        if expected in templates:
            if not self.SHOULD_EXIST:
                raise xenrt.XRTFailure("Template named '%s' exists" %
                                       (expected))
        else:
            if self.SHOULD_EXIST:
                raise xenrt.XRTFailure("No template named '%s'" %
                                       (expected))

        if self.SHOULD_EXIST:
            uuid = host.parseListForUUID("template-list",
                                         "name-label",
                                         expected)
            if not uuid:
                raise xenrt.XRTError("Unable to lookup UUID for template '%s'"
                                     % (expected))
            for cf in self.CHECK_FIELDS:
                field, key, value = cf
                actual = host.genParamGet("vm", uuid, field, key)
                if actual != value:
                    if key:
                        fdisp = "%s:%s" % (field, key)
                    else:
                        fdisp = field
                    raise xenrt.XRTFailure(\
                        "Unexpected value '%s' for %s (expected '%s')" %
                        (actual, fdisp, value))

class TC10619(_TemplateExists):
    """A template named "Windows 7" exists"""
    TEMPLATE_NAME = "Windows 7"
    TEMPLATE_NAME_MNR = "Windows 7 (32-bit)"

class TC10620(_TemplateExists):
    """A template named "Windows 7 x64" exists"""
    TEMPLATE_NAME = "Windows 7 x64"
    TEMPLATE_NAME_MNR = "Windows 7 (64-bit)"
    
class TC10621(_TemplateExists):
    """A template named "Windows Server 2008 R2" doesn't exist"""
    TEMPLATE_NAME = "Windows Server 2008 R2"
    TEMPLATE_NAME_MNR = "Windows Server 2008 R2 (32-bit)"
    SHOULD_EXIST = False

class TC10622(_TemplateExists):
    """A template named "Windows Server 2008 R2 x64" exists"""
    TEMPLATE_NAME = "Windows Server 2008 R2 x64"
    TEMPLATE_NAME_MNR = "Windows Server 2008 R2 (64-bit)" 

class TC11783(_TemplateExists):
    """A template named "Red Hat Enterprise Linux 5 (32-bit)" exists"""
    TEMPLATE_NAME = "Red Hat Enterprise Linux 5"
    TEMPLATE_NAME_MNR = "Red Hat Enterprise Linux 5 (32-bit)"

class TC11784(_TemplateExists):
    """A template named "Red Hat Enterprise Linux 5 (64-bit)" exists"""
    TEMPLATE_NAME = "Red Hat Enterprise Linux 5 x64"
    TEMPLATE_NAME_MNR = "Red Hat Enterprise Linux 5 (64-bit)"

class TC10986(_TemplateExists):
    """A template named "Red Hat Enterprise Linux 5.4" exists"""
    TEMPLATE_NAME = "Red Hat Enterprise Linux 5.4"
    TEMPLATE_NAME_MNR = "Red Hat Enterprise Linux 5.4 (32-bit)"

class TC10987(_TemplateExists):
    """A template named "Red Hat Enterprise Linux 5.4 x64" exists"""
    TEMPLATE_NAME = "Red Hat Enterprise Linux 5.4 x64"
    TEMPLATE_NAME_MNR = "Red Hat Enterprise Linux 5.4 (64-bit)"

class TC11842(_TemplateExists):
    """A template named "Red Hat Enterprise Linux 6 (32-bit)" exists"""
    TEMPLATE_NAME = "Red Hat Enterprise Linux 6"
    TEMPLATE_NAME_MNR = "Red Hat Enterprise Linux 6 (32-bit)"

class TC11843(_TemplateExists):
    """A template named "Red Hat Enterprise Linux 6 (64-bit)" exists"""
    TEMPLATE_NAME = "Red Hat Enterprise Linux 6 x64"
    TEMPLATE_NAME_MNR = "Red Hat Enterprise Linux 6 (64-bit)"

class TC11785(_TemplateExists):
    """A template named "Oracle Enterprise Linux 5 (32-bit)" exists"""
    TEMPLATE_NAME = "Oracle Enterprise Linux 5 (32-bit)"

class TC11786(_TemplateExists):
    """A template named "Oracle Enterprise Linux 5 (64-bit)" exists"""
    TEMPLATE_NAME = "Oracle Enterprise Linux 5 (64-bit)"

class TC10988(_TemplateExists):
    """A template named "Oracle Enterprise Linux 5.3" exists"""
    TEMPLATE_NAME = "Oracle Enterprise Linux 5.3"
    TEMPLATE_NAME_MNR = "Oracle Enterprise Linux 5.3 (32-bit)"

class TC10989(_TemplateExists):
    """A template named "Oracle Enterprise Linux 5.3 x64" exists"""
    TEMPLATE_NAME = "Oracle Enterprise Linux 5.3 x64"
    TEMPLATE_NAME_MNR = "Oracle Enterprise Linux 5.3 (64-bit)"
    
class TC10990(_TemplateExists):
    """A template named "Oracle Enterprise Linux 5.4" exists"""
    TEMPLATE_NAME = "Oracle Enterprise Linux 5.4"
    TEMPLATE_NAME_MNR = "Oracle Enterprise Linux 5.4 (32-bit)"

class TC10991(_TemplateExists):
    """A template named "Oracle Enterprise Linux 5.4 x64" exists"""
    TEMPLATE_NAME = "Oracle Enterprise Linux 5.4 x64"
    TEMPLATE_NAME_MNR = "Oracle Enterprise Linux 5.4 (64-bit)"
    
class TC11787(_TemplateExists):
    """A template named "CentOS 5 (32-bit)" exists"""
    TEMPLATE_NAME = "CentOS 5 (32-bit)"

class TC11788(_TemplateExists): 
    """A template named "CentOS 5 (64-bit)" exists"""
    TEMPLATE_NAME = "CentOS 5 (64-bit)"
    
class TC10992(_TemplateExists):
    """A template named "CentOS 5.4" exists"""
    TEMPLATE_NAME = "CentOS 5.4"
    TEMPLATE_NAME_MNR = "CentOS 5.4 (32-bit)"

class TC10993(_TemplateExists):
    """A template named "CentOS 5.4 x64" exists"""
    TEMPLATE_NAME = "CentOS 5.4 x64"
    TEMPLATE_NAME_MNR = "CentOS 5.4 (64-bit)"

class TC10994(_TemplateExists):
    """A template named "Red Hat Enterprise Linux 4.8" exists"""
    TEMPLATE_NAME = "Red Hat Enterprise Linux 4.8"
    TEMPLATE_NAME_MNR = "Red Hat Enterprise Linux 4.8 (32-bit)"

class TC10995(_TemplateExists):
    """A template named "CentOS 4.8" exists"""
    TEMPLATE_NAME = "CentOS 4.8"
    TEMPLATE_NAME_MNR = "CentOS 4.8 (32-bit)"

class TC11025(_TemplateExists):
    """A template named "Citrix XenApp on Windows Server 2003" exists"""
    TEMPLATE_NAME = "Citrix XenApp on Windows Server 2003"
    TEMPLATE_NAME_MNR = "Citrix XenApp on Windows Server 2003 (32-bit)"
    CHECK_FIELDS = [("HVM-shadow-multiplier", None, "4.000")]

class TC11026(_TemplateExists):
    """A template named "Citrix XenApp x64 on Windows Server 2003 x64" exists"""
    TEMPLATE_NAME = "Citrix XenApp x64 on Windows Server 2003 x64"
    TEMPLATE_NAME_MNR = "Citrix XenApp on Windows Server 2003 (64-bit)"
    CHECK_FIELDS = [("HVM-shadow-multiplier", None, "4.000")]

class TC11028(_TemplateExists):
    """A template named "Citrix XenApp on Windows Server 2008" exists"""
    TEMPLATE_NAME = "Citrix XenApp on Windows Server 2008"
    TEMPLATE_NAME_MNR = "Citrix XenApp on Windows Server 2008 (32-bit)"
    CHECK_FIELDS = [("HVM-shadow-multiplier", None, "4.000")]

class TC11027(_TemplateExists):
    """A template named "Citrix XenApp x64 on Windows Server 2008 x64" exists"""
    TEMPLATE_NAME = "Citrix XenApp x64 on Windows Server 2008 x64"
    TEMPLATE_NAME_MNR = "Citrix XenApp on Windows Server 2008 (64-bit)"
    CHECK_FIELDS = [("HVM-shadow-multiplier", None, "4.000")]

class TC11029(_TemplateExists):
    """A template named "Citrix XenApp x64 on Windows Server 2008 R2 x64" exists"""
    TEMPLATE_NAME = "Citrix XenApp x64 on Windows Server 2008 R2 x64"
    TEMPLATE_NAME_MNR = "Citrix XenApp on Windows Server 2008 R2 (64-bit)"
    CHECK_FIELDS = [("HVM-shadow-multiplier", None, "4.000")]

class TC12528(_TemplateExists):
    """A template named "Solaris 10 (32-bit)" exists"""
    TEMPLATE_NAME = "Solaris 10 (experimental)"
    
class TC12529(_TemplateExists):
    """A template named "Solaris 10 (64-bit)" exists"""
    TEMPLATE_NAME = "Solaris 10 (experimental)"
    
class TC13140(_TemplateExists):
    """A template named "Ubuntu Lucid Lynx 10.04 (32-bit)" exists"""
    TEMPLATE_NAME = "Ubuntu Lucid Lynx 10.04 (32-bit)"

class TC13141(_TemplateExists):
    """A template named "Ubuntu Lucid Lynx 10.04 (64-bit)" exists"""
    TEMPLATE_NAME = "Ubuntu Lucid Lynx 10.04 (64-bit)"
    
class TC13142(_TemplateExists):
    """A template named "SUSE Linux Enterprise Server 9 SP4 (32-bit)" exists"""
    TEMPLATE_NAME = "SUSE Linux Enterprise Server 9 SP4 (32-bit)"

class TC15956(_TemplateExists):
    """A template named "SUSE Linux Enterprise Server 9 SP4 (32-bit)" doesn't exist"""
    TEMPLATE_NAME = "SUSE Linux Enterprise Server 9 SP4 (32-bit)"
    SHOULD_EXIST = False

class TC13143(_TemplateExists):
    """A template named "SUSE Linux Enterprise Server 10 SP1 (32-bit)" exists"""
    TEMPLATE_NAME = "SUSE Linux Enterprise Server 10 SP1 (32-bit)"

class TC13144(_TemplateExists):
    """A template named "SUSE Linux Enterprise Server 10 SP1 (64-bit)" exists"""
    TEMPLATE_NAME = "SUSE Linux Enterprise Server 10 SP1 (64-bit)"

class TC13145(_TemplateExists):
    """A template named "SUSE Linux Enterprise Server 10 SP2 (32-bit)" exists"""
    TEMPLATE_NAME = "SUSE Linux Enterprise Server 10 SP2 (32-bit)"

class TC13146(_TemplateExists):
    """A template named "SUSE Linux Enterprise Server 10 SP2 (64-bit)" exists"""
    TEMPLATE_NAME = "SUSE Linux Enterprise Server 10 SP2 (64-bit)"

class TC13147(_TemplateExists):
    """A template named "SUSE Linux Enterprise Server 10 SP3 (32-bit)" exists"""
    TEMPLATE_NAME = "SUSE Linux Enterprise Server 10 SP3 (32-bit)"

class TC13148(_TemplateExists):
    """A template named "SUSE Linux Enterprise Server 10 SP3 (64-bit)" exists"""
    TEMPLATE_NAME = "SUSE Linux Enterprise Server 10 SP3 (64-bit)"

class TC13149(_TemplateExists):
    """A template named "SUSE Linux Enterprise Server 10 SP4 (32-bit)" exists"""
    TEMPLATE_NAME = "SUSE Linux Enterprise Server 10 SP4 (32-bit)"

class TC13150(_TemplateExists):
    """A template named "SUSE Linux Enterprise Server 10 SP4 (64-bit)" exists"""
    TEMPLATE_NAME = "SUSE Linux Enterprise Server 10 SP4 (64-bit)"

class TC13151(_TemplateExists):
    """A template named "SUSE Linux Enterprise Server 11 (32-bit)" exists"""
    TEMPLATE_NAME = "SUSE Linux Enterprise Server 11 (32-bit)"

class TC13152(_TemplateExists):
    """A template named "SUSE Linux Enterprise Server 11 (64-bit)" exists"""
    TEMPLATE_NAME = "SUSE Linux Enterprise Server 11 (64-bit)"
    
class TC13153(_TemplateExists):
    """A template named "SUSE Linux Enterprise Server 11 SP1 (32-bit)" exists"""
    TEMPLATE_NAME = "SUSE Linux Enterprise Server 11 (32-bit)"

class TC13154(_TemplateExists):
    """A template named "SUSE Linux Enterprise Server 11 SP1 (64-bit)" exists"""
    TEMPLATE_NAME = "SUSE Linux Enterprise Server 11 (64-bit)"
    
class TC13209(_TemplateExists):
    """A template named "Debian Squeeze 6.0 (64-bit)" exists"""
    TEMPLATE_NAME = "Debian Squeeze 6.0 (64-bit)"
    
class TC13210(_TemplateExists):
    """A template named "Debian Squeeze 6.0 (32-bit)" exists"""
    TEMPLATE_NAME = "Debian Squeeze 6.0 (32-bit)"
    
class TC13211(_TemplateExists):
    """A template named "Debian Lenny 5.0 (32-bit)" exists"""
    TEMPLATE_NAME = "Debian Lenny 5.0 (32-bit)"

class TC15957(_TemplateExists):
    """A template named "Oracle Enterprise Linux 6 (32-bit)" exists"""
    TEMPLATE_NAME = "Oracle Enterprise Linux 6 (32-bit)"

class TC15958(_TemplateExists):
    """A template named "Oracle Enterprise Linux 6 (64-bit)" exists"""
    TEMPLATE_NAME = "Oracle Enterprise Linux 6 (64-bit)"

class TC15959(_TemplateExists):
    """A template named "CentOS 6 (32-bit)" exists"""
    TEMPLATE_NAME = "CentOS 6 (32-bit)"

class TC15960(_TemplateExists):
    """A template named "CentOS 6 (64-bit)" exists"""
    TEMPLATE_NAME = "CentOS 6 (64-bit)"

class TC17741(_TemplateExists):
    """A template named "Ubuntu Precise Pangolin 12.04 (32-bit)" exists"""
    TEMPLATE_NAME = "Ubuntu Precise Pangolin 12.04 (32-bit)"

class TC17742(_TemplateExists):
    """A template named "Ubuntu Precise Pangolin 12.04 (64-bit)" exists"""
    TEMPLATE_NAME = "Ubuntu Precise Pangolin 12.04 (64-bit)"

class TC10623(xenrt.TestCase):
    """Multipath configuration should exist for Pillar Axiom 300, 500 and 600 arrays"""

    MULTIPATH_KEYWORDS = ["Pillar", "Axiom 300", "Axiom 500", "Axiom 600"]
    FILES = ["/sbin/mpath_prio_alua_pillar",
             "/sbin/mpath_prio_alua_pillar.static"]

    def run(self, arglist):
        
        host = self.getDefaultHost()

        try:
            data = host.execdom0("cat /etc/multipath-enabled.conf")
        except:
            data = host.execdom0("cat /etc/multipath.conf")
        for s in self.MULTIPATH_KEYWORDS:
            if not s in data:
                raise xenrt.XRTFailure("Could not find '%s' in multipathd "
                                       "config" % (s))
        
        missing = []
        for f in self.FILES:
            if host.execdom0("test -e %s" % (f), retval="code") != 0:
                missing.append(f)
        if len(missing) > 0:
            raise xenrt.XRTFailure("File(s) missing from dom0: %s" %
                                   (string.join(missing)))

class _SYMCSFXREDO(xenrt.TestCase):
    """Base class for SYMC SFX Re-Do Logs on SR"""

    enableHABefore = False
    enableHAAfter = False
    ReDoLogDisableHA = False

    def srTypeLookup(self,srType):
        srdict = {}
        for sr in self.pool.master.getSRs():
            srdict[self.pool.master.getSRParam(sr, "type")] = sr
        return (srType in srdict.keys())
    
    def sharedSRs(self):
        self.SharedUUID = []
        for uuids in self.poolsrUUIDs:
            shared = self.pool.master.getSRParam(uuids,"shared") 
            srType = self.pool.master.getSRParam(uuids,"type")
            srName = self.pool.master.getSRParam(uuids, "name-label")
            if shared == "true":
                if srType != "iso":
                    self.SharedUUID.append(uuids)
        return self.SharedUUID
    
    def checkEnableHA(self):
        if self.srTypeLookup("iscsi") or self.srTypeLookup("hba"):
            self.pool.enableHA()
        else:
            raise xenrt.XRTError("No iscsi or fc-hba sr available for HA")
    
    def run(self, arglist):
        self.pool = xenrt.TestCase().getDefaultPool()
        self.host = self.getDefaultHost()
        self.slave = self.pool.getSlaves()[0]
        self.sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host, "iscsisr")
        self.sr.create()
        self.hba = xenrt.lib.xenserver.HBAStorageRepository(self.host, "hbasr")
        self.hba.create()
        self.poolsrUUIDs = self.pool.master.getSRs()       
        masterUUID = self.pool.master.getMyHostUUID()
        for uuid in self.sharedSRs():
            value = "true-%s" % (uuid)
            if self.enableHABefore:
                self.checkEnableHA()
            xenrt.TEC().logverbose("Enabling Re-Do Logs on the Pool...")
            self.pool.master.execdom0("xe pool-enable-redo-log sr-uuid=%s" % (uuid))
            if self.enableHAAfter:
                self.checkEnableHA()
            if self.ReDoLogDisableHA:
                self.pool.disableHA()   
            # change something    
            xenrt.TEC().logverbose("Changing an 'other-config' parameter")
            self.pool.master.execdom0("xe host-param-set uuid='%s' other-config:test_param='%s'" % (masterUUID,value))

            # Kill Xapi on the master
            xenrt.TEC().logverbose("killing xapi on the master...")
            ps = self.pool.master.execdom0("sevice xapi status")
            r = re.search("pid ([0-9]+)", ps)
            if r:
                self.pool.master.execdom0("kill -9 %s" % (r.group(1)))
            else:
                raise xenrt.XRTError("Could not find the xapi pid")

            # Emergency promote slave to master
            xenrt.TEC().logverbose("promoting slave to new master")
            self.slave.execdom0("xe pool-emergency-transition-to-master")

            # Verify the change persisted
            xenrt.TEC().logverbose("verifying that the other-config change persisted")
            otherConfig = self.slave.execcmd("xe host-param-list uuid=%s | grep 'other-config'" % (masterUUID))
            r = re.search("test_param: ([a-z]+)", otherConfig)
            if not r:
                raise xenrt.XRTError("param setting did not get written to the re-do log")
            # bring XAPI back up on the old master
            self.pool.master.restartToolstack()
            


class TC10550(_SYMCSFXREDO):
    """Testcase for SYMC SFX - Enable re-do logs on disk"""

    def prepare(self, arglist):
        pass


class TC10616(_SYMCSFXREDO):
    """Test Case for SYMC SFX - Enable re-do logs on a pool with HA enabled"""

    def prepare(self, arglist):
        self.enableHABefore = True

class TC10624(_SYMCSFXREDO):
    """Test Case for SYMC SFX - Enable Re-Do Logs on a Pool, Then enable HA.  Then test"""

    def prepare(self, arglist):
        self.enableHAAfter = True

class TC10625(_SYMCSFXREDO):
    """SYMC SFX - Enable re-do logs on pool with HA then Disable HA"""

    def prepare(self, arglist):
        self.enableHABefore = True
        self.ReDoLogDisableHA = True

class TC10551(xenrt.TestCase):
    """Testcase for SYMC SFC - Indestructable SR"""
    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        self.localSR = self.pool.master.getLocalSR()
        self.localPBD = self.pool.master.getSRParam(self.localSR,"PBDs")
        xenrt.TEC().logverbose("setting the indestructable flag for the local SR")
        try:
            self.pool.master.execdom0("xe sr-param-set uuid=%s other-config:indestructible=true" % (self.localSR))
        except:
            raise xenrt.XRTError("Unable to set SR as indestructible")

    def run(self, arglist):           
        xenrt.TEC().logverbose("unplugging the PBD")
        try:
            self.pool.master.execdom0("xe pbd-unplug uuid=%s" % (self.localPBD))
        except:
            raise xenrt.XRTError("Unable to unplug the PBD")

        xenrt.TEC().logverbose("Attempting to Destroy the SR")

        try:
            self.pool.master.execdom0("xe sr-destroy uuid=%s" % (self.localSR))
        except:
            xenrt.TEC().logverbose("Unable to destroy SR...")
        else:
            raise xenrt.XRTError("Was able to destroy the SR when the indestructible flag was set!")

class TC11023(xenrt.TestCase):
    """The maximum number of logical processors should be detected and reported by xapi"""

    def run(self, arglist):

        host = self.getDefaultHost()
        cpus = host.minimalList("host-cpu-list",
                                params="number",
                                args="host-uuid=%s" % (host.getMyHostUUID()))
        supported = int(host.lookup("MAX_HOST_LOG_CPUS", "32"))
        if len(cpus) == supported:
            xenrt.TEC().logverbose("Counted the expected %u logical CPUs" %
                                   (supported))
        elif len(cpus) > supported:
            raise xenrt.XRTError("Expected to find %u logical CPUs but "
                                 "found more (%u)" % (supported, len(cpus)))
        else:
            raise xenrt.XRTFailure("Expected to find %u logical CPUs but only "
                                   "found %u" % (supported, len(cpus)))
                                   
        cpus.sort()
        for i in range(1, len(cpus)):
            if cpus[i] == cpus[i-1]:
                raise xenrt.XRTFailure("Duplicate numbered logical CPU(s)")
            
class TC11024(xenrt.TestCase):
    """Run one VM per host logical CPU for maximum supported CPUs"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        supported = int(self.host.lookup("MAX_HOST_LOG_CPUS", "32"))
        self.cpus = self.host.minimalList("host-cpu-list",
                                          params="number",
                                          args="host-uuid=%s" %
                                          (self.host.getMyHostUUID()))
        if len(self.cpus) != supported:
            raise xenrt.XRTError("Host reports different number of logical "
                                 "CPUs than the supported number",
                                 "Supported %u, host reports %u" %
                                 (supported, len(self.cpus)))

        self.guest = self.host.createGenericLinuxGuest(vcpus=1)
        self.getLogsFrom(self.guest)
        self.uninstallOnCleanup(self.guest)
        self.guest.preCloneTailor()

        # I was getting FP errors with the version of slurp compiled on
        # the controller - build a fresh one:
        c = """/******************************************************************************
 * slurp.c
 * 
 * Slurps spare CPU cycles and prints a percentage estimate every second.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define US_INTERVAL 1000000ULL /* time between estimates, in microseconds. */

/* rpcc: get full 64-bit Pentium TSC value */
static __inline__ unsigned long long int rpcc(void) 
{
    unsigned int __h, __l;
    __asm__ __volatile__ ("rdtsc" :"=a" (__l), "=d" (__h));
    return (((unsigned long long)__h) << 32) + __l;
}


/*
 * find_cpu_speed:
 *   Interrogates /proc/cpuinfo for the processor clock speed.
 * 
 *   Returns: speed of processor in MHz, rounded down to nearest whole MHz.
 */
#define MAX_LINE_LEN 50
int find_cpu_speed(void)
{
    FILE *f;
    char s[MAX_LINE_LEN], *a, *b;

    if ( (f = fopen("/proc/cpuinfo", "r")) == NULL ) goto out;

    while ( fgets(s, MAX_LINE_LEN, f) )
    {
        if ( strstr(s, "cpu MHz") )
        {
            /* Find the start of the speed value, and stop at the dec point. */
            if ( !(a=strpbrk(s,"0123456789")) || !(b=strpbrk(a,".")) ) break;
            *b = '\0';
            fclose(f);
            return(atoi(a));
        }
    }

 out:
    fprintf(stderr, "find_cpu_speed: error parsing /proc/cpuinfo for cpu MHz");
    exit(1);
}


int main(void)
{
    int mhz, i;

    /*
     * no_preempt_estimate is our estimate, in clock cycles, of how long it
     * takes to execute one iteration of the main loop when we aren't
     * preempted. 50000 cycles is an overestimate, which we want because:
     *  (a) On the first pass through the loop, diff will be almost 0,
     *      which will knock the estimate down to <40000 immediately.
     *  (b) It's safer to approach real value from above than from below --
     *      note that this algorithm is unstable if n_p_e gets too small!
     */
    unsigned int no_preempt_estimate = 50000;

    /*
     * prev     = timestamp on previous iteration;
     * this     = timestamp on this iteration;
     * diff     = difference between the above two stamps;
     * start    = timestamp when we last printed CPU % estimate;
     * next_est = next time at which we print estimate
     */
    unsigned long long int prev, this, diff, start, next_est;

    /*
     * preempt_time = approx. cycles we've been preempted for since last stats
     *                display.
     */
    unsigned long long int preempt_time = 0;

    /*
     * preempt_count = approximate number of times we were preempted.
     */
    unsigned long preempt_count = 0;

    /* Required in order to print intermediate results at fixed period. */
    mhz = find_cpu_speed();
    printf("CPU speed = %d MHz\\n", mhz);

    start = prev = rpcc();
    next_est = start + US_INTERVAL * mhz;

    for ( ; ; )
    {
        /*
         * By looping for a while here we hope to reduce affect of getting
         * preempted in critical "timestamp swapping" section of the loop.
         * In addition, it should ensure that 'no_preempt_estimate' stays
         * reasonably large which helps keep this algorithm stable.
         */
        for ( i = 0; i < 100; i++ ) __asm__ __volatile__ ( "rep; nop;" : : );

        /*
         * The critical bit! Getting preempted here will shaft us a bit,
         * but the loop above should make this a rare occurrence.
         */
        this = rpcc();
        diff = this - prev;
        prev = this;

        /* if ( diff > (2 * preempt_estimate) */
        if ( diff > (no_preempt_estimate<<1) )
        {
            /* We were probably preempted for a while. */
            preempt_time += diff - no_preempt_estimate;
            preempt_count++;
        }
        else
        {
            /*
             * Looks like we weren't preempted -- update our time estimate:
             * New estimate = 0.75*old_est + 0.25*curr_diff
             */
            no_preempt_estimate =
                (no_preempt_estimate >> 1) + 
                (no_preempt_estimate >> 2) +
                (diff >> 2);
        }
            
        /* Dump CPU time every second. */
        if ( this > next_est ) 
        { 
            printf("Slurped %.2f%% CPU, preempted %lu times\\n", 
                   100.0 * (((double)this - start - preempt_time) / 
                            ((double)this - start)), 
                   preempt_count);
            start         = this;
            next_est     += US_INTERVAL * mhz;
            preempt_time  = 0;
            preempt_count = 0;
        }
    }

    return(0);
}
"""
        fn = self.tec.tempFile()
        f = file(fn, "w")
        f.write(c)
        f.close()
        sftp = self.guest.sftpClient()
        try:
            sftp.copyTo(fn, "/root/slurp.c")
        finally:
            sftp.close()
        self.guest.execguest("cd /root ; gcc -O2 -o slurp slurp.c")
        self.guest.shutdown()

        # Clone the guest for each logical CPU
        self.guests = []
        for i in range(0, supported):
            g = self.guest.cloneVM()
            g.start()
            g.shutdown()
            self.uninstallOnCleanup(g)
            self.guests.append(g)

    def run(self, arglist):

        # Record current values for CPU data sources
        initvalues = {}
        for cpu in self.cpus:
            datasource = "cpu%s" % (cpu)
            initvalues[datasource] = self.host.dataSourceQuery(datasource)

        # Start all guests
        xenrt.TEC().logverbose("Starting VMs...")
        i = 0
        for g in self.guests:
            g.start()
            i += 1
            if i % 5 == 0:
                xenrt.TEC().logverbose("Logging memory usage after %u VM starts" % (i))
                self.host.execdom0("top -b -n 1")

        # Start slurp in each guest
        xenrt.TEC().logverbose("Starting slurp in VMs...")
        for g in self.guests:
            g.execguest("nohup /root/slurp > /tmp/slurp.out 2>&1 "
                        "< /dev/null &")
            #g.execguest("nohup %s/progs/slurp > /tmp/slurp.out 2>&1 "
            #            "< /dev/null &" %
            #            (xenrt.TEC().lookup("REMOTE_SCRIPTDIR")))

        # Wait five minutes
        time.sleep(300)

        # Check CPUs are all busy:
        quietcpus = []
        busyvalues = {}
        for cpu in self.cpus:
            datasource = "cpu%s" % (cpu)
            utilisation = self.host.dataSourceQuery(datasource)
            busyvalues[datasource] = utilisation
            if utilisation < 0.9:
                quietcpus.append(datasource)

        # Stop slurp workloads
        for g in self.guests:
            g.execguest("killall slurp")

        # Read in tail of slurp logs. Not doing anything with it just yet
        for g in self.guests:
            data = g.execguest("tail /tmp/slurp.out")

        if len(quietcpus) > 0:
            raise xenrt.XRTFailure("One or more CPUs not very busy",
                                   string.join(quietcpus))

class _CPUID(xenrt.TestCase):

    def hex2bits(self, h):
        d = long(h, 16)
        l = len(h) * 4
        bits = [0 for _ in range(l)]
        while d > 0:
            l -= 1
            bits[l] = int(d%2)
            d = d / 2
        return bits
    
    def bits2hex(self, b):
        l = len(b) / 4
        bs = ''.join([str(i) for i in b])
        d = long(bs, 2)
        return ("%0" + str(l) + "x") % d

    def bitsand(self, b1, b2, *bn):
        bs = list(bn)
        bs.insert(0, b2)
        bs.insert(0, b1)
        return reduce(lambda x,y: map(int.__mul__, x, y), bs)

    def cpuFeaturesToBits(self, features):
        sep = features.find('-') and '-' or ' '
        return self.hex2bits(''.join(features.split(sep)))

    def bitsToCPUFeatures(self, bits):
        sep = '-'
        hs = self.bits2hex(bits)
        return sep.join([hs[i*8:i*8+8] for i in range(len(hs)/8)])

    def getDomCPUFlags(self, dom):
        if dom.windows:
            raise xenrt.XRTError("Not implemented")
        domcpuinfo = xenrt.parseLayeredConfig(
            dom.execcmd("cat /proc/cpuinfo").split('\n\n', 1)[0],
            { 'sep':'\n', 'sub': {'sep': ':', 'next': lambda _: None}, 'post':dict }
            )
        domcpuflags = domcpuinfo['flags'].split()
        return domcpuflags

    def checkCPUFlags(self, host, guest):
        # Dom0, DomU should see the same flags as features
        hostflags = host.getCPUInfo()['flags'].split()
        hostflags.sort()
        dom0flags = filter(lambda f: f != 'up', self.getDomCPUFlags(host))
        dom0flags.sort()
        domuflags = filter(lambda f: f != 'up', self.getDomCPUFlags(guest))
        domuflags.sort()
        if not (hostflags == dom0flags): # == domuflags
            raise xenrt.XRTFailure("Host, dom0, domu see different cpu flags",
                                   data = (hostflags, dom0flags, domuflags))
        else:
            xenrt.TEC().logverbose("Host, dom0, domu see same cpu flags: %s"
                                   % hostflags)
        host.execdom0("sync")

    def checkVMHealth(self, vm, grace=True):
        if grace:
            time.sleep(10)
        vm.check()
        vm.checkHealth()
        # for w in vm.workloads:
        #     if not w.checkRunning():
        #         raise xenrt.XRTFailure("Some workload %s isn't running" % w)


class _TCCPUMask(_CPUID):

    VENDOR = "Intel"
    LEVEL = "high"
    TECH = "FlexMigrate"

    def prepare(self, arglist=[]):
        self.host = self.getDefaultHost()

        # Even a free version host should query the cpu info
        cpuinfo = self.host.getCPUInfo()

        # Ensure the cpuinfo and test condition agree (not effective for now
        # due to the lack of hardware)
        # if cpuinfo['maskable'].lower() == str(self.LEVEL == "legacy").lower():
        #     raise xenrt.XRTError("Testcase and cpu doesn't agree on maskable "
        #                          "or not", data= (cpuinfo, self.LEVEL))
        
        guest = self.host.getGuest("linux")
        if guest.getDiskSRType() == "nfs":
            guest.shutdown()
            self.guest = guest.cloneVM()
            self.guest.start()
        else:
            self.guest = guest
        self.uninstallOnCleanup(self.guest)            
        self.guest.workloads = self.guest.installWorkloads(["LinuxSysbench"])
        self.guest.reboot()
        self.checkVMHealth(self.guest)

    def run(self, arglist=[]):
        cli = self.host.getCLIInstance()

        cpuinfo = self.host.getCPUInfo()
        
        # fresh host, all three features set should identical
        if not (cpuinfo['physical_features']
                == cpuinfo['features']
                == cpuinfo['features_after_reboot']):
            raise xenrt.XRTFailure("Unexpected features relation on a fresh "
                                   "installed host.", data = cpuinfo)
        self.checkCPUFlags(self.host, self.guest)

        # Generate a problematic features set
        bits = self.cpuFeaturesToBits(cpuinfo['physical_features'])
        firstzero = bits.index(0)
        bits[firstzero] = 1
        nfeatures = self.bitsToCPUFeatures(bits)
        assert nfeatures != cpuinfo['physical_features']

        try:
            self.host.setCPUFeatures(nfeatures)
        except xenrt.XRTException, e:
            if self.LEVEL=="legacy" and e.data.find("not support") >= 0:
                xenrt.TEC().logverbose("Legacy hardware doesn't support CPU "
                                       "masking as expected")
                return
            elif e.reason.find("not valid") >= 0:
                xenrt.TEC().logverbose("Invalid CPU features, as expected")
            else:
                raise e
        else:
            raise xenrt.XRTFailure("Given features beyond physical features, "
                                   "but masking succeeded.")

        assert self.host.getCPUInfo() == cpuinfo

        # Generate a features set with extension bits modified
        bits = self.cpuFeaturesToBits(cpuinfo['physical_features'])
        firstone64 = bits.index(1, 64)
        bits[firstone64] = 0
        nfeatures = self.bitsToCPUFeatures(bits)
        assert nfeatures != cpuinfo['physical_features']
        try:
            self.host.setCPUFeatures(nfeatures)
        except xenrt.XRTException, e:
            if cpuinfo['maskable'].lower() != "full" \
               and e.data.find("not valid") >= 0:
                xenrt.TEC().logverbose("Intel CPU refused to mask extension "
                                       "bits, as expected")
            else:
                raise e
        else:
            if cpuinfo['maskable'].lower() != "full":
                xenrt.TEC().warning("XenServer should refuse to mask "
                                    "extension bits of Intel CPU")

        # Generate a safe features set
        bits = self.cpuFeaturesToBits(cpuinfo['physical_features'])
        firstone = bits.index(1)
        assert firstone < 64
        bits[firstone] = 0
        nfeatures = self.bitsToCPUFeatures(bits)
        assert nfeatures != cpuinfo['physical_features']
        self.host.setCPUFeatures(nfeatures)
        self.checkCPUFlags(self.host, self.guest)

        # Reboot and verify effectiveness
        self.host.reboot()
        self.guest.start()
        self.checkVMHealth(self.guest)

        ncpuinfo = self.host.getCPUInfo()
        if (nfeatures
            == ncpuinfo['features']
            == ncpuinfo['features_after_reboot']
            and 
            ncpuinfo['physical_features']
            == cpuinfo['physical_features']):
            xenrt.TEC().logverbose("The new features has been set by Xen")
        else:
            raise xenrt.XRTFailure("Unexpected features setting after reboot",
                                   data = ("previous: %s\n set: %s\n now: %s"
                                           % (cpuinfo, nfeatures, ncpuinfo)))
        
        self.checkCPUFlags(self.host, self.guest)

        # Check the VM running well
        self.guest.lifecycleSequence(opcount=10, norandom=True,
                                     check=self.checkVMHealth, back=True)
        
        # Test reset
        self.host.resetCPUFeatures()
        self.host.reboot()
        self.guest.start()
        self.checkCPUFlags(self.host, self.guest)
        self.checkVMHealth(self.guest)
            
class _TCHeterogeneousPool(_CPUID):

    VENDOR = "Intel"
    TECH = "FlexMigrate"

    def prepare(self, arglist=[]):

        self.master = self.getHost("RESOURCE_HOST_0")
        self.hosts = [ xenrt.TEC().registry.hostGet(hn)
                       for hn in xenrt.TEC().registry.hostList() ]
        self.hosts = list(set(self.hosts))
        for h in self.hosts:
            self.getLogsFrom(h)
            h.license()
        
        # Continue the CPUMask testcase, the hosts should now have the proper
        # license and should have the original CPU setting but with VM running
        # on it. We should stop any running VMs on the slaves and detach their
        # shared storages.

        for h in self.hosts:
            for gn in h.listGuests():
                g = h.getGuest(gn)
                if g.getState() != 'DOWN':
                    g.shutdown()
            if h != self.master:
                for sruuid in h.minimalList("sr-list", "uuid", "shared=true"):
                    h.forgetSR(sruuid)

        guest_l = self.master.getGuest("linux")
        guest_l.start()
        guest_l.workloads = guest_l.installWorkloads(["LinuxSysbench"])
        guest_l.reboot()
        self.checkVMHealth(guest_l)
        guest_l.shutdown()

        guest_w = self.master.getGuest("windows")
        guest_w.start()
        guest_w.workloads = guest_w.installWorkloads(["Prime95"])
        guest_w.reboot()
        self.checkVMHealth(guest_w)
        guest_w.shutdown()

        self.guests_lin = [ guest_l.cloneVM() for h in self.hosts ]
        self.guests_win = [ guest_w.cloneVM() for h in self.hosts ]
        for g in (self.guests_lin + self.guests_win):
            self.uninstallOnCleanup(g)
        
    def run(self, arglist=[]):
        self.poolCreation()
        self.poolOperation()

    def poolCreation(self):

        for master in self.hosts:
            master.resetCPUFeatures()
            pool = xenrt.lib.xenserver.poolFactory(master.productVersion)(master)
            for slave in self.hosts:
                if slave != master and slave != self.master:
                    self.tryJoin(pool, slave, setfeature=True)
            xenrt.TEC().logverbose("%s joined pool mastered by %s"
                                   % (pool.listSlaves(), master.getName()))
            pool.check()
            for slave in pool.getSlaves():
                # For debugging
                slave.special['v6licensing'] = True
                pool.eject(slave)

    def tryJoin(self, pool, slave, setfeature=False):

        """ If pool joining suceeds, return True; if fails with reasonable
        cause, return False; otherwise raise exception """

        master_ft = pool.master.getCPUFeatures()
        master_bits = self.cpuFeaturesToBits(master_ft)
        slave_ft = slave.getCPUFeatures()
        slave_cap = self.cpuFeaturesToBits(slave.getCPUInfo()
                                           ['physical_features'])
        if master_ft == slave_ft:
            pool.addHost(slave)
            xenrt.TEC().logverbose("Successfully join homogeneous pool")
            return True
        else:
            xenrt.TEC().logverbose("Host has hetrogeneous CPU")
            try:
                pool.addHost(slave)
            except xenrt.XRTException, e:
                if not re.search("homogeneous", e.reason): raise e
                if not setfeature: return False
                try:
                    forceMask = xenrt.TEC().lookup("FORCE_CPU_MASK", None)
                    if forceMask:
                        slave.setCPUFeatures(forceMask)
                    else:
                        slave.setCPUFeatures(master_ft)
                except xenrt.XRTException, e:
                    if (slave == self.master and re.search("not support", e.reason)):
                        xenrt.TEC().logverbose("Legacy machine doesn't "
                                               "support %s, as expected"
                                               % self.TECH)
                        return False
                    elif (self.bitsand(master_bits, slave_cap) != master_bits
                          and re.search("not valid", e.reason)):
                        xenrt.TEC().logverbose("Low-level machine couldn't "
                                               "be masked up beyond its "
                                               "physical capability")
                        return False
                    else:
                        raise e
                else:
                    xenrt.TEC().logverbose("Features set, will restart to make "
                                          "CPU masking effective")
                    slave.reboot()
                    return self.tryJoin(pool, slave, setfeature=False)
            else:
                raise xenrt.XRTFailure("Hetrogeneous hosts can pool join")

    def pairInterOp(self, left, right):
        
        hostl = self.hosts[left]
        hostr = self.hosts[right]
        guestsl = [ self.guests_lin[left], self.guests_win[left] ]
        guestsr = [ self.guests_lin[right], self.guests_win[right] ]

        for g in guestsl:
            g.host = hostr
            g.start()
            self.checkVMHealth(g)
        for g in guestsr:
            g.host = hostl
            g.start()
            self.checkVMHealth(g)

        for g in guestsl:
            g.suspend()
            g.resume(on=hostl)
            self.checkVMHealth(g)
        for g in guestsr:
            g.suspend()
            g.resume(on=hostr)
            self.checkVMHealth(g)

        # for g in (guestsl + guestsr):
        #     if not g.windows:
        #         continue
        #     else:
        #         g.enableHibernation()
        #         g.hibernate()
        #         g.start(skipsniff=True)
        #         time.sleep(10)
        #         g.hibernate()
        #         g.start(skipsniff=True)
        #         self.checkVMHealth(g)

        for g in guestsl:
            g.migrateVM(hostr)
            self.checkVMHealth(g)
        for g in guestsr:
            g.migrateVM(hostl)
            self.checkVMHealth(g)

        for g in guestsl:
            g.migrateVM(hostl, live="true")
            self.checkVMHealth(g)
        for g in guestsr:
            g.migrateVM(hostr, live="true")
            self.checkVMHealth(g)

        for g in (guestsl + guestsr):
            g.shutdown()
            
    def poolOperation(self):

        pool = xenrt.lib.xenserver.poolFactory(self.master.productVersion)(self.master)

        forceMask = xenrt.TEC().lookup("FORCE_CPU_MASK", None)
        if forceMask:
            self.master.setCPUFeatures(forceMask)
            self.master.reboot()

        joined = [ h for h in self.hosts 
                   if h != self.master and self.tryJoin(pool, h, setfeature=True) ]
      
        xenrt.TEC().logverbose("%s joined the pool created by %s" % (joined, self.master))

        num = len(self.hosts)

        if num != len(joined) + 1:
            raise xenrt.XRTFailure("Total hosts number: %d, hosts in the pool: %d"
                                % (num, len(joined)))

        for shift in range(0, num):
            left = shift
            right = (shift + 1) % num
            if left == right:
                continue
            else:
                self.pairInterOp(left, right)
        
class TC11183(_TCCPUMask):
    pass

class TC11184(_TCCPUMask):
    LEVEL = "middle"

class TC11185(_TCCPUMask):
    LEVEL = "low"

class TC11186(_TCCPUMask):
    LEVEL = "legacy"

class TC11187(_TCCPUMask):
    VENDOR = "AMD"
    TECH = "EMT"

class TC11188(_TCCPUMask):
    VENDOR = "AMD"
    LEVEL = "middle"
    TECH = "EMT"

class TC11189(_TCCPUMask):
    VENDOR = "AMD"
    LEVEL = "low"
    TECH = "EMT"

class TC11190(_TCCPUMask):
    VENDOR = "AMD"
    LEVEL = "legacy"
    TECH = "EMT"

class TCFlexMigrate(_TCHeterogeneousPool):
    pass

class TCEMT(_TCHeterogeneousPool):
    VENDOR = "AMD"
    TECH = "EMT"



class _Dom0Tuning(xenrt.TestCase):
    GUEST_VCPUS = 2
    CLONES_PER_BASE_VM = 10
    LIFECYCLE_LOOPS = 2
    RANDOM_CYCLES = 0

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.guests = []
        self.baseVMs = []

        existingGuests = self.host.listGuests()
        if existingGuests:
            self.baseVMs = map(lambda x:self.host.getGuest(x), existingGuests)
        else:
            self.baseVMs.append(self._createBaseVM(distro="debian60", vcpus=self.GUEST_VCPUS))
            self.baseVMs.append(self._createBaseVM(distro="win7sp1-x64", vcpus=self.GUEST_VCPUS))

        for baseVM in self.baseVMs:
            self.guests += self._createClonedVMs(numberOfVms=self.CLONES_PER_BASE_VM, baseVM=baseVM)

        self.timers = { 'start': [], 'reboot': [], 'suspend': [], 'resume': [], 'shutdown': [] }

    def run(self, arglist=None):
        pinningOptions = [self.host.DOM0_VCPU_PINNED, self.host.DOM0_VCPU_NOT_PINNED , self.host.DOM0_VCPU_DYNAMIC_PINNING]
        vCPUOptions = [self.host.DOM0_MIN_VCPUS, self.host.DOM0_MAX_VCPUS, self.host.DOM0_DYNAMIC_VCPUS]
        workerThreadOptions = [4, 9, 16]

#        matrix = [(self.host.DOM0_VCPU_DYNAMIC_PINNING, self.host.DOM0_MIN_VCPUS,     4),
#                  (self.host.DOM0_VCPU_DYNAMIC_PINNING, self.host.DOM0_MAX_VCPUS,     16),
#                  (self.host.DOM0_VCPU_DYNAMIC_PINNING, self.host.DOM0_DYNAMIC_VCPUS, 9),
#                  (self.host.DOM0_VCPU_PINNED,          self.host.DOM0_MAX_VCPUS,     16),
#                  (self.host.DOM0_VCPU_NOT_PINNED,      self.host.DOM0_MAX_VCPUS,     16),
#                  (self.host.DOM0_VCPU_DYNAMIC_PINNING, self.host.DOM0_MIN_VCPUS,     1)]

        matrix = [(self.host.DOM0_VCPU_NOT_PINNED,      self.host.DOM0_MAX_VCPUS,     8),
                  (self.host.DOM0_VCPU_NOT_PINNED,      self.host.DOM0_DYNAMIC_VCPUS, 8),
                  (self.host.DOM0_VCPU_NOT_PINNED,      self.host.DOM0_MIN_VCPUS,     4),
                  (self.host.DOM0_VCPU_NOT_PINNED,      self.host.DOM0_MAX_VCPUS,     4),
                  (self.host.DOM0_VCPU_NOT_PINNED,      self.host.DOM0_DYNAMIC_VCPUS, 4),
                  (self.host.DOM0_VCPU_NOT_PINNED,      self.host.DOM0_DYNAMIC_VCPUS, 1),
                  (self.host.DOM0_VCPU_DYNAMIC_PINNING, self.host.DOM0_DYNAMIC_VCPUS, 4)]

        randomCycles = self.RANDOM_CYCLES
        if randomCycles:
            for i in range(randomCycles):
                self.runSubcase('_configureAndRun', (random.choice(workerThreadOptions),
                                                     random.choice(pinningOptions),
                                                     random.choice(vCPUOptions)),
                                'Random Cycle', '%d' % (i))
                self._shutdownAllVms()
        else:
            for pin, vcpu, workTh in matrix:
                self.runSubcase('_configureAndRun', (workTh, pin, vcpu, self.LIFECYCLE_LOOPS),
                                'Matrix Cycle', '%d, %s, %s' % (workTh, pin, vcpu))
                self._shutdownAllVms()

    def _shutdownAllVms(self):
        # Attempt to force shutdown all VMs
        guestsToShutdown = filter(lambda x:x.getState() != 'DOWN', self.guests)
        map(lambda x:x.shutdown(force=True), guestsToShutdown)

    def _configureAndRun(self, workerThreads, pinning, vCPU, lifecycleLoops=1):
        xenrt.TEC().logverbose("workerThreads = %d" % (workerThreads))
        xenrt.TEC().logverbose("pinning = %s" % (pinning))
        xenrt.TEC().logverbose("vCPU = %s" % (vCPU))

        self.host.setXapiWorkerThreadPolicy(workerPoolSize=workerThreads)
        self.host.setDom0vCPUPolicy(pinning=pinning, numberOfvCPUs=vCPU)

        for i in range(lifecycleLoops):
            before = datetime.datetime.now()
            pt = map(lambda x:xenrt.PTask(x.start), self.guests)
            xenrt.pfarm(pt)
            duration = datetime.datetime.now() - before
            xenrt.TEC().logverbose("Duration for VM Start: %d sec" % (duration.seconds))
            self.timers['start'].append(duration.seconds)
            self._checkVcpuInfo('start', pinning, vCPU)

            before = datetime.datetime.now()
            pt = map(lambda x:xenrt.PTask(x.reboot), self.guests)
            xenrt.pfarm(pt)
            duration = datetime.datetime.now() - before
            xenrt.TEC().logverbose("Duration for VM Reboot: %d sec" % (duration.seconds))
            self.timers['reboot'].append(duration.seconds)
            self._checkVcpuInfo('reboot', pinning, vCPU)

            before = datetime.datetime.now()
            pt = map(lambda x:xenrt.PTask(x.suspend), self.guests)
            xenrt.pfarm(pt)
            duration = datetime.datetime.now() - before
            xenrt.TEC().logverbose("Duration for VM Suspend: %d sec" % (duration.seconds))
            self.timers['suspend'].append(duration.seconds)
            self._checkVcpuInfo('suspend', pinning, vCPU)

            before = datetime.datetime.now()
            pt = map(lambda x:xenrt.PTask(x.resume), self.guests)
            xenrt.pfarm(pt)
            duration = datetime.datetime.now() - before
            xenrt.TEC().logverbose("Duration for VM Resume: %d sec" % (duration.seconds))
            self.timers['resume'].append(duration.seconds)
            self._checkVcpuInfo('resume', pinning, vCPU)

            map(lambda x:x.checkReachable(), self.guests)

            before = datetime.datetime.now()
            pt = map(lambda x:xenrt.PTask(x.shutdown), self.guests)
            xenrt.pfarm(pt)
            duration = datetime.datetime.now() - before
            xenrt.TEC().logverbose("Duration for VM Shutdown: %d sec" % (duration.seconds))
            self.timers['shutdown'].append(duration.seconds)
            self._checkVcpuInfo('shutdown', pinning, vCPU)

    def _checkVcpuInfo(self, operation, pinning, vCPU):
        try:
            self._checkVcpuInfoE(operation, pinning, vCPU)
        except Exception, e:
            xenrt.TEC().comment("%s" % (str(e)))

    def _checkVcpuInfoE(self, operation, pinning, vCPU):
        xenrt.TEC().logverbose("Host CPU Usage: %s" % (self.host.getCpuUsage()))

        (tuneVCPUsConfig, policyParams) = self.host.getDom0vCPUPolicy()
        if tuneVCPUsConfig['POLICY_DYN'] != vCPU:
            raise xenrt.XRTFailure("Unexpected vCPU configuration: Expected: %s, Actual: %s" % (vCPU, tuneVCPUsConfig['POLICY_DYN']))
        if tuneVCPUsConfig['POLICY_PIN'] != pinning:
            raise xenrt.XRTFailure("Unexpected Pinning configuration: Expected: %s, Actual: %s" % (pinning, tuneVCPUsConfig['POLICY_PIN']))
        vmActiveThreshold = policyParams['VM_START_NR_THRESHOLD']

        # check if there are enough guests to exceed the active threshold
        checkForActiveVmTransitions = len(self.guests) > vmActiveThreshold

        vcpuInfo = self.host.getVcpuInfoByDomId()
        dom0vcpuInfo = vcpuInfo[0]
        if pinning == self.host.DOM0_VCPU_NOT_PINNED:
            if dom0vcpuInfo['vcpuspinned'] != 0:
                xenrt.TEC().logverbose("Dom0 vcpu info: %s" % (dom0vcpuInfo))
                raise xenrt.XRTFailure("Dom0 VCPUs pinned when policy is set to nopin")

        elif pinning == self.host.DOM0_VCPU_PINNED:
            # All online vCPUs should be pinned
            if dom0vcpuInfo['vcpuspinned'] < dom0vcpuInfo['vcpusonline']:
                raise xenrt.XRTFailure("Online Dom0 VCPUs are not pinned when policy is set to pin")

        elif pinning == self.host.DOM0_VCPU_DYNAMIC_PINNING:
            # todo
            pass
        else:
            raise xenrt.XRTError("Invalid Dom0 VCPUs pin policy: %s" % (pinning))

        if vCPU == self.host.DOM0_MIN_VCPUS:
            if dom0vcpuInfo['vcpusonline'] != 4:
                raise xenrt.XRTFailure("Incorrect number of online Dom0 VCPUs when policy is set to min. Expected: 4, Actual: %d" % (dom0vcpuInfo['vcpusonline']))

        elif vCPU == self.host.DOM0_MAX_VCPUS:
            if dom0vcpuInfo['vcpusonline'] != dom0vcpuInfo['vcpus']:
                raise xenrt.XRTFailure("Some Dom0 VCPUs are offline when policy is set to max. Total vCPUs: %d, Online vCPUs: %d" % (dom0vcpuInfo['vcpus'], dom0vcpuInfo['vcpusonline']))

        elif vCPU == self.host.DOM0_DYNAMIC_VCPUS:
            # todo
            pass
        else:
            raise xenrt.XRTError("Invalid Dom0 vCPU policy: %s" % (vCPU))

    def _createBaseVM(self, distro, vcpus):
        baseVM = self.host.createBasicGuest(distro=distro, vcpus=vcpus, name='%s-Base' % (distro))
        baseVM.preCloneTailor()
        baseVM.shutdown()
        return baseVM

    def _createClonedVMs(self, numberOfVms, baseVM):
        pClones = map(lambda x:xenrt.PTask(baseVM.cloneVM, name='%s-%d' % (baseVM.name, x)), range(numberOfVms))
        clones = xenrt.pfarm(pClones)
        for clone in clones:
            clone.tailored = True
        return clones

class TC18005(_Dom0Tuning):
    pass

class PCIPassThrough(xenrt.TestCase):

    def getEthDevs(self, host):
        
        return [host.getNIC(x) for x in [0] + host.listSecondaryNICs(network="NPRI")]
    
    def getEthPCIs(self, host, ethDevs):
        def getPCIId(eth):
            return host.execdom0('basename `readlink /sys/class/net/%s/device`' % eth).strip()
        
        return map(getPCIId, ethDevs)
    
    def getMgmtEth(self, host):
        pif_uuid = host.minimalList("pif-list",
                                    args="management=true host-uuid=%s" % host.getMyHostUUID())[0]
        return host.genParamGet('pif', pif_uuid, "device")

    def getPCIsAssigned(self, g):
        
        h = self.g2hMap[g.getName()]
        try:
            devString = h.genParamGet('vm', g.getUUID(), 'other-config', pkey='pci').strip()
        except:
            return set()
        
        pat = re.compile(r'\d+\/(\S+)')
        
        return set(map(lambda m: m.group(1),
                       filter(bool, map(pat.match, devString.split(',')))))
    
    def getAssignedPCIsPerHost(self, h):
        
        gs = [self.getGuest(gn) for (gn, hn) in self.g2hMap.items() 
              if hn.getName() == h.getName()]
        
        return functools.reduce(lambda x, y: x.union(y), 
                                [self.getPCIsAssigned(g) for g in gs], 
                                set())
    
    def copyDevcon(self):
        
        winVMs = [g for g in self.guests if g.windows]
        x86VMs = set([g for g in winVMs if g.xmlrpcGetArch() == "x86"])
        x64VMs = set(winVMs) - x86VMs
        devconx86 = "%s/utils/devcon.exe" % (xenrt.TEC().lookup("LOCAL_SCRIPTDIR"))
        devconx64 = "%s/utils/devcon64.exe" % (xenrt.TEC().lookup("LOCAL_SCRIPTDIR"))
        
        def checkDevCon(g):
            return g.xmlrpcFileExists("C:\\devcon.exe")
        
        def cp(g, devcon):
            g.xmlrpcSendFile(devcon, "C:\\devcon.exe")
            return
        
        map(lambda g: cp(g, devconx86), [g for g in x86VMs if not checkDevCon(g)])
        map(lambda g: cp(g, devconx64), [g for g in x64VMs if not checkDevCon(g)])
        
        return
    
    def prepare(self, arglist=None):
        
        self.pool = self.getDefaultPool()
        if self.pool is None:
            self.host = self.getDefaultHost()
        else:
            self.host = self.pool.master
        
        if self.pool is None:
            self.hosts = [self.host] #In case of a pool, we'll have (>1) host
        else:
            self.hosts = self.pool.getHosts()

        self.guests = []
        self.basicTest = False # For Boston, Sanibel
        self.upgradeTest = False
        self.PCIsAssigned = False # Used for upgrade tests
        self.g2PCINos = None # guest to number of PCI dev assignment
        
        pat = re.compile('\((\w+):(\d+)\)')  # guests=(guest_name,no_of_PCI_devs_passed),...

        for arg in arglist:

            if arg.startswith('guests'): # guests="(win1:2),(lin1:1),(lin2:1)"
                pciConfs = arg.split('=')[1].strip().split(',')
                regExps = [p for p in map(pat.match, pciConfs) if p is not None]
                self.g2PCINos = dict([(p.group(1), int(p.group(2))) for p in regExps])

            elif arg.startswith('basic_test'): # Basic test should be used for Boston/Sanibel Host(or Pool)
                self.basicTest = True
            elif arg.startswith('upgrade_test'):
                self.upgradeTest = True
            elif arg.startswith('pcis_assigned'):
                self.PCIsAssigned = True

        # If this is a basic test (host is pre-Tampa) no PCIs would have been assigned.
        if self.basicTest:
            self.PCIsAssigned = False
        
        self.guests = filter(bool, map(lambda g: self.getGuest(g), self.g2PCINos.keys()))
        if not self.guests:
            raise xenrt.XRTError("Need atleast 1 guest for testing PCI pass-through!")
        
        # Start VMs
        self.startVMs()
        
        self.g2hMap = dict([(g.getName(), g.findHost()) for g in self.guests])
        mgmt_eths = map(set, [[self.getMgmtEth(h)] for h in self.hosts])
        eths_per_host = map(set, [self.getEthDevs(h) for h in self.hosts])
        
        def getFreeEths(eths, mg_eth):
            return (eths - mg_eth)

        usable_eths_per_host = itertools.starmap(getFreeEths, 
                                                 zip(eths_per_host, mgmt_eths)) #set of eths
        def getPCIs(h, eths):
            return self.getEthPCIs(h, eths)

        usable_pcis_per_host = map(set, 
                                   itertools.starmap(getPCIs, zip(self.hosts, usable_eths_per_host)))
        hostNames = map(lambda h: h.getName(), self.hosts)
        
        # Some VMs might have PCIs assigned (in the case of upgrade tests)
        # so we have to update h2PCIMap
        additionalPCIs = map(lambda h: self.getAssignedPCIsPerHost(h), self.hosts)
        self.h2PCIMap = dict(zip(hostNames, 
                                 itertools.starmap(lambda x, y: x.union(y),
                                                   zip(usable_pcis_per_host, additionalPCIs))))
        self.h2PCIsAssigned = dict([(h.getName(), self.getAssignedPCIsPerHost(h)) 
                                    for h in self.hosts])
        self.copyDevcon()
        self.shutVMs()
        return
    
    def getAssignablePCIs(self, h):
        return (self.h2PCIMap[h.getName()] - self.h2PCIsAssigned[h.getName()])
        
    def assignPCIdevs(self, g, n):

        h = self.g2hMap[g.getName()]

        freePCIs = self.getAssignablePCIs(h)
        if n > len(freePCIs):
            raise xenrt.XRTError("Insufficient assignable PCIs on %s" % h.getName())
        
        candidatePCIs = [p[1] for p in  zip(range(n), freePCIs)]
        random.shuffle(candidatePCIs)
        
        devString = ",".join(["%d/%s" % i for i in enumerate(candidatePCIs)])
        h.genParamSet('vm', g.getUUID(), 'other-config', devString, pkey='pci')
        self.h2PCIsAssigned[h.getName()] = self.h2PCIsAssigned[h.getName()].union(set(candidatePCIs))
        
        return

    def unassignPCIdevs(self, g):
        pcis = self.getPCIsAssigned(g)
        if not pcis:
            return
        
        h = self.g2hMap[g.getName()]
        assert self.h2PCIsAssigned[h.getName()].issuperset(pcis)
        
        h.genParamRemove('vm', g.getUUID(), 'other-config', 'pci')
        self.h2PCIsAssigned[h.getName()] -= set(pcis)
        
        return

    def unassignPCIdevsFromVMs(self):
        for g in self.guests:
            self.unassignPCIdevs(g)
        return
        
    def assignPCIdevsToVMs(self):
        for g in self.guests:
            self.assignPCIdevs(g, self.g2PCINos[g.getName()])
        return
        
    def startVMs(self):
        for g in self.guests:
            if g.getState() == "DOWN":
                g.start(specifyOn=True)
        self.waitForVMsToBeUp()
        return
    
    def getWinPCIlisting(self, g):
        g.xmlrpcExec("c:\\devcon find * > c:\\windows\\temp\\devcon.log")
        d = "%s/%s" % (xenrt.TEC().getLogdir(), g.getName())
        if not os.path.exists(d):
            os.makedirs(d)
        path = "%s/devcon.log" % d
        g.xmlrpcGetFile("c:\\windows\\temp\\devcon.log", path)
        pciListing = xenrt.command("grep PCI %s | grep -i ethernet | grep -v -i realtek" % path).strip()
        if pciListing:
            pciListing = filter(bool, map(lambda s: s.strip(), pciListing.splitlines()))
        else:
            pciListing = []
        return pciListing

    def getLinPCIlisting(self, g):
        pciListing = g.execcmd("lspci -D | grep -i ethernet ; exit 0").strip()
        if pciListing:
            pciListing = filter(bool, map(lambda s: s.strip(), pciListing.splitlines()))
        else:
            pciListing = []
        return pciListing
        
    def checkPCIs(self):
        def check(g):
            n = 0
            if g.windows:
                n = len(self.getWinPCIlisting(g))
            else:
                n = len(self.getLinPCIlisting(g))
            m = self.g2PCINos[g.getName()]
            if n != m:
                return ["For %s PCIs found %d ; however we were expecting %d" % (g.getName(), n, m)]
            return []
        
        msgs = sum(map(check, self.guests), [])
        
        if msgs:
            for msg in msgs:
                xenrt.TEC().logverbose(msg)
            raise xenrt.XRTFailure("Unexpected PCI assignment to VM(s)")
        return

    def waitForVMsToBeUp(self):
        for g in self.guests:
            if g.windows:
                g.waitforxmlrpc(300)
            else:
                g.waitForSSH(300, desc='waiting for %s to be up' % g.getName()) 
        return
    
    def shutVMsfromInside(self):
        for g in self.guests:
            if g.windows:
                g.xmlrpcShutdown()
            else:
                g.execcmd('shutdown -h now; exit 0')
        time.sleep(120)
        return
        
    def rebootVMsfromInside(self):
        for g in self.guests:
            if g.windows:
                g.xmlrpcReboot()
            else:
                g.execcmd('shutdown -r now; exit 0')
            try:
                g.waitToReboot()
            except:
                pass
        self.waitForVMsToBeUp()
        return
    
    def rebootVMs(self):
        for g in self.guests:
            g.reboot()
        self.waitForVMsToBeUp()    
        return

    def shutVMs(self):
        for g in self.guests:
            if g.getState() == "UP":
                g.shutdown()
        time.sleep(120)
        return

    def testLifeCycleOopsAndPCI(self):
        self.shutVMs()
        self.startVMs()
        self.checkPCIs()
        self.rebootVMs()
        self.checkPCIs()
        self.rebootVMsfromInside()
        self.checkPCIs()
        self.shutVMsfromInside()
        self.unassignPCIdevsFromVMs()
        self.assignPCIdevsToVMs()
        self.startVMs()
        self.checkPCIs()
        return

    def restartHosts(self):
        for h in self.hosts:
            h.reboot()
            h.waitForSSH(600, desc="Waiting for host....")
            h.waitForXapi(300, desc="Waiting for Xapi....")
        return
        
    def upgradePool(self):
        upgrader = xenrt.lib.xenserver.host.RollingPoolUpdate(self.pool)
        newPool = self.pool.upgrade(poolUpgrade=upgrader) 
        newPool.verifyRollingPoolUpgradeInProgress(expected=False)
        self.pool = newPool
        self.host = self.pool.master
        return
    
    def upgradeHost(self):
        return

    def upgradeVMs(self):
        return
    
    def upgrade(self):
        self.shutVMs()
        if self.pool:
            self.upgradePool()
        else:
            self.upgradeHost()
        self.upgradeVMs()
        return
        
    def run(self, arglist=None):
        
        # Assign the PCI devices if required
        if not self.PCIsAssigned:
            self.assignPCIdevsToVMs()
        
        self.startVMs()
        self.checkPCIs()
        
        if self.basicTest:  # In case of pre-Tampa XenServer
            return
        
        if self.upgradeTest:
            self.upgrade()
            self.checkPCIs()

        self.testLifeCycleOopsAndPCI()
        self.shutVMsfromInside()
        self.restartHosts()
        self.startVMs()
        self.checkPCIs()
        self.testLifeCycleOopsAndPCI()
        
        return

class _Dom0Xpinning(xenrt.TestCase):
    SINGLE_HOST = True
    DOM0_VCPU_COUNT = 4
    DOM0_PINNING = False

    def prepare(self, arglist=None):
        self.host = self.getHost("RESOURCE_HOST_0")
        if not self.SINGLE_HOST:
            self.host2 = self.getHost("RESOURCE_HOST_1")
        self.guestInfo = {}
        self.guests = map(lambda x:self.host.getGuest(x), self.host.listGuests())
        for guest in self.guests:
            self.guestInfo[guest] = {'vcpus':0,'vcpumask':[]}

    def adviseDom0vCPUPinningStatus(self, host):
        # Matrix of (Host CPUs, Dom0 vCPUs, Pinning Status) as given in EA-1205
        
        dom0vCPUMatrix = [([1],1,False),
                  ([2],2,False),
                  ([3],3,False),
                  (range(4,24),4,False),
                  (range(24,32),6,False),
                  (range(32,48),8,False),
                  (range(48,1000),8,True)]

        if isinstance(host, xenrt.lib.xenserver.DundeeHost):
            # CAR-2003
            dom0vCPUMatrix = [([1],1,False),
                              ([2],2,False),
                              ([3],3,False),
                              ([4],4,False),
                              ([5],5,False),
                              ([6],6,False),
                              ([7],7,False),
                              ([8],8,False),
                              ([9],9,False),
                              ([10],10,False),
                              ([11],11,False),
                              ([12],12,False),
                              ([13],13,False),
                              ([14],14,False),
                              ([15],15,False),
                              (range(16,1000),16,False)]

        hostCPUCount = host.getCPUCores()
        #Default setting on most XenRT host configurations
        vcpuSetting = {'vcpus':4,'pinning':False}
        for hostCPUs, dom0vCPUs, pinningStatus in dom0vCPUMatrix:
            if hostCPUCount in hostCPUs:
                vcpuSetting['vcpus'] = dom0vCPUs
                vcpuSetting['pinning'] = pinningStatus
        xenrt.TEC().logverbose("Recommended Dom0 vCPU setting %s" %vcpuSetting)
        return vcpuSetting
        
    def checkDefaultDom0vCPUPinning(self, host):
        dom0vCPUPinningData = host.getDom0PinningPolicy()
        xenrt.TEC().logverbose("Dom0 vCPU count: %s" % dom0vCPUPinningData['dom0vCPUs'])
        xenrt.TEC().logverbose("Dom0 Pinning status: %s" % dom0vCPUPinningData['pinning'])
        advisedSetting = self.adviseDom0vCPUPinningStatus(host)
        if dom0vCPUPinningData['dom0vCPUs'] != str(advisedSetting['vcpus']):
            raise xenrt.XRTFailure("Default Dom0 vCPU count not set according to host pCPU configuration")

    def checkCurrentDom0vCPUPinning(self, host, pinning, vcpus):
        vcpuInfo = host.getVcpuInfoByDomId()
        dom0vcpuInfo = vcpuInfo[0]
        xenrt.TEC().logverbose("Dom0 vcpu info: %s" % (dom0vcpuInfo))
        if not pinning:
            if dom0vcpuInfo['vcpuspinned'] != 0:
                raise xenrt.XRTFailure("Dom0 VCPUs pinned when policy is set to nopin")
        elif pinning:
            # All online vCPUs should be pinned
            if dom0vcpuInfo['vcpuspinned'] < dom0vcpuInfo['vcpusonline']:
                raise xenrt.XRTFailure("Online Dom0 VCPUs are not pinned when policy is set to pin")
        else:
            raise xenrt.XRTError("Invalid Dom0 VCPUs pin policy: %s" % (pinning))

        if vcpus:
            if vcpus != dom0vcpuInfo['vcpus'] and dom0vcpuInfo['vcpusonline'] != dom0vcpuInfo['vcpus']:
                raise xenrt.XRTFailure("Invalid Dom0 vCPU configuration. Expected vCPUs: %s Actual vCPUs: %d, Online vCPUs: %d" % (vcpus,dom0vcpuInfo['vcpus'], dom0vcpuInfo['vcpusonline']))

    def checkGuestvCPUMask(self, host, guest, vcpuMask=[]):
        vcpuInfo = host.getVcpuInfoByDomId()
        dom0vcpuData = vcpuInfo[0]
        domId = host.getDomid(guest)
        if vcpuInfo.has_key(domId):
            vcpuData = vcpuInfo[domId]
            xenrt.TEC().logverbose("Guest vcpu data: %s" % vcpuData)
        else:
            raise xenrt.XRTFailure("Specified domain %s not available in the vcpu-list" % domId)
        dom0Affinity = dom0vcpuData['cpuaffinity']
        cpuAffinity = vcpuData['cpuaffinity']
        if dom0Affinity:
            if dom0Affinity != cpuAffinity:
                xenrt.TEC().logverbose("Guest cpu affinity mutually exclusive with Dom0 affinity")
            else:
                raise xenrt.XRTFailure("Guest cpu affinity %s not mutually exclusive with Dom0 affinity %s" % (cpuAffinity,dom0Affinity))
        if vcpuMask:
            if set(cpuAffinity) != set(vcpuMask):
                raise xenrt.XRTFailure("Guest cpu affinity not set according to its VCPU mask")
        
class TC19361(_Dom0Xpinning):
    SINGLE_HOST=True
    DOM0_PINNING = True

    def run(self, arglist=None):
        self.checkDefaultDom0vCPUPinning(self.host)
        self.DOM0_VCPU_COUNT = self.adviseDom0vCPUPinningStatus(self.host)['vcpus']
        self.host.setDom0PinningPolicy(self.DOM0_VCPU_COUNT,self.DOM0_PINNING)
        hostCPUCount = self.host.getCPUCores()
        hostCPUs = range(hostCPUCount)
        dom0CPUs = range(self.DOM0_VCPU_COUNT)
        guestCPUs = [cpu for cpu in hostCPUs if cpu not in dom0CPUs]
        cpuIter = 0
        vcpuCount = 2
        for guest in self.guests:
            guest.paramSet("VCPUs-max",vcpuCount)
            guest.paramSet("VCPUs-at-startup",vcpuCount)
            self.guestInfo[guest]['vcpus'] = vcpuCount
            if cpuIter < len(guestCPUs):
                self.guestInfo[guest]['vcpumask'] = guestCPUs[cpuIter:cpuIter+2]
                guest.paramSet("VCPUs-params:mask", ','.join(str(cpu) for cpu in self.guestInfo[guest]['vcpumask']))
                
            vcpuCount += 2
            cpuIter += 2
            try:
               guest.start()
            except:
               continue
        self.checkCurrentDom0vCPUPinning(self.host,self.DOM0_PINNING,self.DOM0_VCPU_COUNT)
        for guest in self.guests:
            self.checkGuestvCPUMask(self.host,guest,self.guestInfo[guest]['vcpumask'])

class TC19362(_Dom0Xpinning):
    SINGLE_HOST=True
    DOM0_PINNING = True

    def run(self, arglist=None):
        self.DOM0_VCPU_COUNT = self.adviseDom0vCPUPinningStatus(self.host)['vcpus']
        self.host.setDom0PinningPolicy(self.DOM0_VCPU_COUNT,self.DOM0_PINNING)
        hostCPUCount = self.host.getCPUCores()
        hostCPUs = range(hostCPUCount)
        dom0CPUs = range(self.DOM0_VCPU_COUNT)
        guestCPUs = [cpu for cpu in hostCPUs if cpu not in dom0CPUs]
        vcpuCount = 2
        for guest in self.guests:
            guest.paramSet("VCPUs-max",vcpuCount)
            guest.paramSet("VCPUs-at-startup",vcpuCount)
            self.guestInfo[guest]['vcpus'] = vcpuCount
            vcpuCount += 2
            try:
               guest.start()
            except:
               continue
        self.checkCurrentDom0vCPUPinning(self.host,self.DOM0_PINNING,self.DOM0_VCPU_COUNT)
        for guest in self.guests:
            self.checkGuestvCPUMask(self.host,guest)
     
class TC19363(_Dom0Xpinning):
    SINGLE_HOST=False
    DOM0_PINNING = True

    def run(self, arglist=None):
       step("Enable Pinning on Master")
       self.DOM0_VCPU_COUNT = self.adviseDom0vCPUPinningStatus(self.host)['vcpus']
       self.host.setDom0PinningPolicy(self.DOM0_VCPU_COUNT,self.DOM0_PINNING)
       step("Check pinning on master")
       self.checkCurrentDom0vCPUPinning(self.host,self.DOM0_PINNING,self.DOM0_VCPU_COUNT)
       
       step("Enable Pinning on slave")
       self.DOM0_VCPU_COUNT = self.adviseDom0vCPUPinningStatus(self.host2)['vcpus']
       self.host2.setDom0PinningPolicy(self.DOM0_VCPU_COUNT,self.DOM0_PINNING)
       step("Check pinning on slave")
       self.checkCurrentDom0vCPUPinning(self.host2,self.DOM0_PINNING,self.DOM0_VCPU_COUNT)
       
       for guest in self.guests:
            if guest.paramGet("resident-on") == self.host.getMyHostUUID():
                step("Check guest on master vcpu mask")
                self.checkGuestvCPUMask(self.host,guest)
            elif guest.paramGet("resident-on") == self.host2.getMyHostUUID():
                step("Check guest on slave vcpu mask")
                self.checkGuestvCPUMask(self.host2,guest)
       
       guest = self.guests[len(self.guests)/2]
       step("Migrate VM from master to slave")
       guest.migrateVM(self.host2, live="true")
       
       for guest in self.guests:
            if guest.paramGet("resident-on") == self.host.getMyHostUUID():
                step("Check guest on master vcpu mask")
                self.checkGuestvCPUMask(self.host,guest)
            elif guest.paramGet("resident-on") == self.host2.getMyHostUUID():
                step("Check guest on slave vcpu mask")
                self.checkGuestvCPUMask(self.host2,guest)

class TC19364(_Dom0Xpinning):
    SINGLE_HOST=False
    DOM0_PINNING = True

    def run(self, arglist=None):
       step("Enable Pinning on Master")
       self.DOM0_VCPU_COUNT = self.adviseDom0vCPUPinningStatus(self.host)['vcpus']
       self.host.setDom0PinningPolicy(self.DOM0_VCPU_COUNT,self.DOM0_PINNING)
       step("Check pinning on master")
       self.checkCurrentDom0vCPUPinning(self.host,self.DOM0_PINNING,self.DOM0_VCPU_COUNT)
       
       step("Disable Pinning on slave")
       self.DOM0_VCPU_COUNT = self.adviseDom0vCPUPinningStatus(self.host2)['vcpus']
       self.DOM0_PINNING = False
       self.host2.setDom0PinningPolicy(self.DOM0_VCPU_COUNT,self.DOM0_PINNING)
       step("Check pinning on slave")
       self.checkCurrentDom0vCPUPinning(self.host2,self.DOM0_PINNING,self.DOM0_VCPU_COUNT)
       
       for guest in self.guests:
            if guest.paramGet("resident-on") == self.host.getMyHostUUID():
                step("Check guest on master vcpu mask")
                self.checkGuestvCPUMask(self.host,guest)
            elif guest.paramGet("resident-on") == self.host2.getMyHostUUID():
                step("Check guest on slave vcpu mask")
                self.checkGuestvCPUMask(self.host2,guest)
       
       guest = self.guests[len(self.guests)/2]
       step("Migrate VM from master to slave")
       guest.migrateVM(self.host2, live="true")
       
       for guest in self.guests:
            if guest.paramGet("resident-on") == self.host.getMyHostUUID():
                step("Check guest on master vcpu mask")
                self.checkGuestvCPUMask(self.host,guest)
            elif guest.paramGet("resident-on") == self.host2.getMyHostUUID():
                step("Check guest on slave vcpu mask")
                self.checkGuestvCPUMask(self.host2,guest)

class TC19365(_Dom0Xpinning):
    SINGLE_HOST=False
    DOM0_PINNING = True

    def run(self, arglist=None):
       step("Disable Pinning on Master")
       self.DOM0_VCPU_COUNT = self.adviseDom0vCPUPinningStatus(self.host)['vcpus']
       self.DOM0_PINNING = False
       self.host.setDom0PinningPolicy(self.DOM0_VCPU_COUNT,self.DOM0_PINNING)
       step("Check pinning on master")
       self.checkCurrentDom0vCPUPinning(self.host,self.DOM0_PINNING,self.DOM0_VCPU_COUNT)
       
       step("Enable Pinning on Slave")
       self.DOM0_VCPU_COUNT = self.adviseDom0vCPUPinningStatus(self.host2)['vcpus']
       self.DOM0_PINNING = True
       self.host2.setDom0PinningPolicy(self.DOM0_VCPU_COUNT,self.DOM0_PINNING)
       step("Check pinning on slave")
       self.checkCurrentDom0vCPUPinning(self.host2,self.DOM0_PINNING,self.DOM0_VCPU_COUNT)
       
       for guest in self.guests:
            if guest.paramGet("resident-on") == self.host.getMyHostUUID():
                step("Check guest on master vcpu mask")
                self.checkGuestvCPUMask(self.host,guest)
            elif guest.paramGet("resident-on") == self.host2.getMyHostUUID():
                step("Check guest on slave vcpu mask")
                self.checkGuestvCPUMask(self.host2,guest)
       
       guest = self.guests[len(self.guests)/2]
       step("Migrate VM from master to slave")
       guest.migrateVM(self.host2, live="true")
       
       for guest in self.guests:
            if guest.paramGet("resident-on") == self.host.getMyHostUUID():
                step("Check guest on master vcpu mask")
                self.checkGuestvCPUMask(self.host,guest)
            elif guest.paramGet("resident-on") == self.host2.getMyHostUUID():
                step("Check guest on slave vcpu mask")
                self.checkGuestvCPUMask(self.host2,guest)

class TC18347(xenrt.TestCase):
    """HFX-485, HFX-486: Verify that host doesn't lose xapi db objects after xapi-db restore""" 

    def prepare(self, arglist=None):
        
        self.pool = self.getDefaultPool()
        if self.pool is None:
            self.host = self.getDefaultHost()
        else:
            self.host = self.pool.master

        if self.host.execdom0('xe pool-dump-database file-name=/root/xapi-db', retval="code") != 0:
            raise xenrt.XRTError("Could not dump database")

        if self.host.execdom0('xe pool-restore-database file-name=/root/xapi-db --force', retval="code") != 0:
            raise xenrt.XRTError("Could not restore database from /root/xapi-db")
        
        time.sleep(60)
        
        self.host.waitForSSH(600, desc="Waiting for host to boot after Xapi DB restore")
        self.host.waitForXapi(300, desc="Xapi startup post DB restore")
        

    def run(self, arglist=None):
        
        cli = self.host.getCLIInstance()
        dummy_uuid = cli.execute('vm-create', 'name-label=xenrt_dummy', strip=True)
        
        self.host.reboot(timeout=900)
        time.sleep(30)
        
        self.host.waitForSSH(600, desc="Waiting for host to boot")
        self.host.waitForXapi(300, desc="Xapi startup post reboot")

        if dummy_uuid not in self.host.minimalList("vm-list", "uuid", "name-label=xenrt_dummy"):
            raise xenrt.XRTFailure("VM object is missing after host reboot")


class TC18383(xenrt.TestCase):
    """HFX-473: Verify that dom0 doesn't crash if ftrace is used."""

    def prepare(self, arglist=None):
        
        self.pool = self.getDefaultPool()
        if self.pool is None:
            self.host = self.getDefaultHost()
        else:
            self.host = self.pool.master
        return
            
    def run(self, arglist=None):

        self.host.execdom0("mount -t debugfs 0 /sys/kernel/debug/")
        self.host.execdom0("echo function > /sys/kernel/debug/tracing/current_tracer")
        time.sleep(10)

        numLines = int(self.host.execdom0("cat /sys/kernel/debug/tracing/trace | wc -l").strip())
        if numLines < 100:
            raise xenrt.XRTFailure("No trace on the /sys/kernel/debug/tracing/trace ???")
        return

    def postRun(self):
        self.host.execdom0("echo nop > /sys/kernel/debug/tracing/current_tracer")
        return

class TC18613(xenrt.TestCase):

    NON_DEFAULT_FEATURE_VERSIONS = {
        'VDI_RESET_ON_BOOT': 2,
        }

    def prepare(self, arglist=None):
        self.hosts = []
        pool = self.getDefaultPool()
        if pool:
            self.hosts = pool.getHosts()
        else:
            self.hosts.append(self.getDefaultHost())

        if len(self.hosts) == 0:
            raise xenrt.XRTError('Failed to find any hosts')
 
        xenrt.TEC().logverbose('Executing tests on host(s): %s' % (self.hosts))

    def run(self, arglist=None):
        for host in self.hosts:
            smUUIDs = host.minimalList('sm-list')
            for smUUID in smUUIDs:
                smType = host.genParamGet('sm', smUUID, 'type')
                capabilities = map(lambda x:x.strip(), host.genParamGet('sm', smUUID, 'capabilities').split(';'))
                featuresData = host.genParamGet('sm', smUUID, 'features').split(';')
                featuresAndVersions = map(lambda x:(x.split(':')[0].strip(), int(x.split(':')[1])), featuresData)
                features = map(lambda x:x.split(':')[0].strip(), featuresData)

                # Check that all capabilities are in the features list
                capsNotInFeaturesList = filter(lambda x:x not in features, capabilities)
                xenrt.TEC().logverbose('Host %s, Type %s: Capabilities not in Features List: %s' % (host, smType, capsNotInFeaturesList))
                featuresNotInCapsList = filter(lambda x:x not in capabilities, features)
                xenrt.TEC().logverbose('Host %s, Type %s: Features not in Capabilities List: %s' % (host, smType, featuresNotInCapsList))

                if len(capsNotInFeaturesList) != 0 or len(featuresNotInCapsList) != 0:
                    raise xenrt.XRTFailure('SM Features and Capability lists do not match for SM-Type: %s' % (smType))
                
                # Check for feature version correctness
                for feature, version in featuresAndVersions:
                    xenrt.TEC().logverbose('Host %s, Type %s, Feature %s: Version = %d' % (host, smType, feature, version))
                    expectedVersion = 1
                    if self.NON_DEFAULT_FEATURE_VERSIONS.has_key(feature):
                        expectedVersion = self.NON_DEFAULT_FEATURE_VERSIONS[feature]
                    
                    if expectedVersion != version:
                        raise xenrt.XRTFailure('SM Feature Version for SM-Type: %s is incorrect: Expected: %d, Actual: %d' % (smType, expectedVersion, version))
        

class TC18850(xenrt.TestCase):
    """HFX-725:CA-98936 Ensure that Xapi does not create debug files every time when it gets an update from xenopsd different from the cached VM record 
    (regression test for HFX-725/CA-98936)"""

    def prepare(self, arglist=[]):
        pool = self.getDefaultPool()
        if pool is None:
            self.host = self.getDefaultHost()
        else:
            self.host = pool.master
        self.host.execdom0('rm -vf /tmp/metadata*')
        self.guest = self.host.createGenericEmptyGuest()
        self.guest.start()
        return
    
    def run(self, arglist=[]):
       
        self.guest.lifecycleOperation("vm-reboot",force=True)
        
        try:
            self.host.execdom0('ls -l /tmp/metadata.*')
        except:
            pass
        else:
            raise xenrt.XRTFailure('XAPI created /tmp/metadata.* on VM reboot')
        return

    def postRun(self):
        
        self.guest.shutdown(force=True)
        self.guest.uninstall()
        return

class NoLocalSR(xenrt.TestCase):
    
    def prepare(self, arglist=[]):
        self.host = self.getDefaultHost()
        return
    
    def run(self, arglist=[]):
        self.host.execdom0("sgdisk -p /dev/sda")
        partitions = self.host.execdom0("sgdisk -p /dev/sda | awk '$1 ~ /[0-9]+/ {print $1}'").splitlines()
        
        # Do we have LVM partitions?
        def checkPartitionForLVM(p):
            return self.host.execdom0("sgdisk -i %s /dev/sda | awk -F: '/Partition *name/ {print $2}' | grep LVM" % p,
                                      retval="code") != 0  

        if all([checkPartitionForLVM(p) for p in partitions]):
            pass
        else:
            for p in partitions:
                self.host.execdom0('sgdisk -i %s /dev/sda' % p)
            raise xenrt.XRTFailure("LVM partition found on /dev/sda")
        
        return


class TCPowerFailureRecovery(xenrt.TestCase):
    """A simple test checking the time of recovery from power failure (required for performance analysis)."""
    # This class switches off random delays in power control and hence should not have it done in threads
    # jira TC-19084
    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.hosts = None
        self.timings = []

    def prepare(self, arglist=None):
        self.hosts = self.getDefaultHost().pool.getHosts()
        # unset the random delay between powering on a host:
        for host in self.hosts:
            host.machine.powerctl.setAntiSurge(False)
        
    def addTiming(self, timing):
        line = "%.3f : %s" % (xenrt.util.timenow(float=True), timing)
        self.timings.append(line)
    
    def preLogs(self):
        filename = "%s/xenrt-timings.log" % (xenrt.TEC().getLogdir())
        f = file(filename, "w")
        for line in self.timings:
            f.write(line+"\n")
        f.close()
        
    def run(self, arglist):

        step("Sleep for 10 minutes, to make sure the pool is stable")
        xenrt.sleep(10*60)
 
        step("Prepare a list of hosts to reboot, starting with the pool master")
        slaves = self.hosts[:-1]
        master = self.hosts[-1]
        hostsToReboot = [master] + slaves
        log('Hosts to power cycle: %s' % hostsToReboot)
        
        step("Power off all hosts")
        for host in hostsToReboot:
            self.addTiming("Powering off host %s" % host.getName() )
            host.machine.powerctl.off()
        
        step("Power on all hosts in 10-s interval, starting with master")
        for host in hostsToReboot:
            xenrt.sleep(10)
            self.addTiming("Powering on host %s" % host.getName())
            host.machine.powerctl.on()
            
        step("Wait for xapi") # don't bother checking while xapi is not running
        master.waitForXapi(600, desc="Xapi response after powering on the master")
        
        step("Wait for all the hosts to become enabled")
        timeMax = 20 * 60
        timeStart = time.time()
        hostsNotEnabled = hostsToReboot[:]
        hostsToCheck = hostsNotEnabled[:]
        while hostsNotEnabled:
            for host in hostsToCheck:
                if host.getHostParam("enabled") == "true":
                    self.addTiming("Host %s enabled" % host.getName())
                    hostsNotEnabled.remove(host)
            hostsToCheck = hostsNotEnabled
            if time.time() - timeStart > timeMax:
                raise xenrt.XRTFailure("Timeout while waiting for all the hosts to get enabled")
            xenrt.sleep(5)
            
    def postRun(self):
        # set back on the random delay before powering on a host
        for host in self.hosts:
            host.machine.powerctl.setAntiSurge(True)



class TCDriverDisk(xenrt.TestCase):
    """
    Testcase for verifying a driver disk is packaged correctly.
    This includes:
        * Installing appropriate hotfixes
        * Installing the driver disk
        * Loading the driver module
    """

    def installHotfixes(self, hotfixPaths):
        """
        Install a list of hotfixes in the list order as passed in
        to the function (i.e. pre-sorted).
        """

        for hf in hotfixPaths:
            self.host.applyPatch(xenrt.TEC().getFile(hf))

        # Reboot host to make sure the latest kernel is in use.
        xenrt.TEC().logverbose("Hotfixes applied. Rebooting host.")
        self.host.execdom0("xe patch-list")
        self.host.reboot()

    def buildHotfixList(self, targetHotfix):
        """
        Build a list of hotfixes that need to be installed ino order 
        to patch the host upto the targetHotfix.
        """
        if not targetHotfix:
            return []

        # Look up available hotfixes from XenRT's hotfix dictionary.
        hfxDict = xenrt.TEC().lookup(["HOTFIXES", self.host.productVersion])
        xenrt.TEC().logverbose("HFX dictionary for %s: %s" % (self.host.productVersion, hfxDict))

        branch = None
        for b in hfxDict.keys():
            if targetHotfix in hfxDict[b].keys():
                branch = b

        if not branch:
            raise xenrt.XRTFailure("Could not find hotfix '%s' in hotfix dict: '%s'" % (targetHotfix, hfxDict))

        paths = []

        for hotfixKey, hotfixPath in sorted(hfxDict[branch].iteritems()):
            # Textual comparison based on key naming scheme
            if hotfixKey <= targetHotfix:
                # Append paths in order.
                paths.append(hotfixPath)

        return paths

    def prepare(self, arglist=None):
        self.host = self.getHost("RESOURCE_HOST_0")
        hotfix = xenrt.TEC().lookup("HOTFIX", None)

        step("Install hotfixes on host if required. Otherwise test with GA")
        if hotfix:
            productVersion = xenrt.TEC().lookup("PRODUCT_VERSION")
            hotfixes = self.buildHotfixList(hotfix)
            xenrt.TEC().comment("Hotfixes to install: '%s'" % hotfixes)
            self.installHotfixes(hotfixes)

        return

    def fetchDriverDisk(self):
        remoteDir = "/tmp/"
        driverDiskPath = xenrt.TEC().lookup("DRIVER_PATH")
        # Get ISO name from path
        ddFile = os.path.basename(driverDiskPath)
        ddFilePath = "%s/%s" % (remoteDir, ddFile)

        sftp = self.host.sftpClient()
        try:
            xenrt.TEC().logverbose('About to copy "%s to "%s" on host.' \
                                        % (driverDiskPath, ddFilePath))
            sftp.copyTo(xenrt.TEC().getFile(driverDiskPath), ddFilePath)
        finally:
            sftp.close()

        res = self.host.execdom0('if [ -e %s ]; then echo "found"; fi' % ddFilePath)
        xenrt.TEC().logverbose('Result: "%s"' % res)
        if res.strip() != "found":
            raise xenrt.XRTError("Failed to copy '%s' to '%s' on host." % (driverDiskPath, ddFilePath))

        if ".zip" in driverDiskPath:
            mountpoint = "/tmp/dd_directory"
            self.host.execdom0("unzip %s -d %s" % (ddFilePath, mountpoint))
            self.isoPath = self.host.execdom0("find %s -name *iso" % (mountpoint)).strip()
            self.iso = os.path.basename(self.isoPath)
        else:
            self.isoPath = ddFilePath
            self.iso = os.path.basename(driverDiskPath)


    def testDriverInstallation(self):
        """
        * Install the driver disk using
          'install.sh' scripts if variable INSTALL_SUPP_PACK=False (default)
           xe-install-supplemental-pack if variable INSTALL_SUPP_PACK=True.
        * Check RPM list updates.
        * Check module dependency table has been updated.
        * Attempt a load of the driver.
        """

        step("Fetch driver disk iso")
        self.fetchDriverDisk()

        step("mount driver disk")
        mntDir = "/mnt/%s" % (self.iso.replace('.',''))
        tmpDir = "/tmp/%s" % (self.iso.replace('.',''))

        self.host.execdom0("mkdir %s" % mntDir)
        self.host.execdom0("mount -o loop %s %s" % (self.isoPath, mntDir))
            
        step("Create a location to copy contents of driver disk to")
        # we do this as we need read-write access to hack the install.sh script
        self.host.execdom0("mkdir %s" % tmpDir)
            
        # copy driver disk contents to /tmp/{i}
        self.host.execdom0("cp -R %s/* %s/" % (mntDir, tmpDir))

        step("Unmount driver disk")
        self.host.execdom0("cd / && umount %s && rmdir %s" % (mntDir, mntDir))
            
        step("Hack driver disk scripts so doesn't ask to confirm")
        self.host.execdom0("sed -i 's/if \[ -d \$installed_repos_dir\/$identifier \]/if \[ 0 -eq 1 \]/' %s/install.sh" % tmpDir)
        self.host.execdom0('sed -i "s/print msg/return/" %s/install.sh || true' % tmpDir)
            
        # list rpms in driver disk
        step("Listing RPMs in driver disk")
        driverDiskRpms = self.host.execdom0('cd / && find %s | grep ".rpm$"' % tmpDir).strip().splitlines()
            
        # dictionary of kernel objects for cross referencing against installed ones after driver disk has been installed
        kos = {}
        kokdump = []
            
        # manually unpack all rpms to get driver names and versions
        step("Unpacking all RPMs in driver disk to get version numbers")
        for j in range(len(driverDiskRpms)):
            self.host.execdom0("mkdir %s/%d" % (tmpDir, j))
            self.host.execdom0("cd %s/%d && rpm2cpio %s | cpio -idmv" % (tmpDir, j, driverDiskRpms[j]))
                
            for ko in self.host.execdom0('cd / && find %s/%d | grep ".ko$" || true' % (tmpDir, j)).strip().splitlines():
                koShort = re.match(".*/(.*?)\.ko$", ko).group(1)
                kos[koShort] = self.host.execdom0('modinfo %s | grep "^srcversion:"' % ko)
                if 'kdump' in ko:
                    kokdump.append(ko[ko.find("/lib"):]) 
                

        # list all rpms before installing driver disk
        rpmsBefore = self.host.execdom0("rpm -qa|sort").splitlines()
        
        step("Install driver disk")
        if xenrt.TEC().lookup("INSTALL_SUPP_PACK", False, boolean=True):
            self.host.execdom0("xe-install-supplemental-pack %s" % self.isoPath)
        else:
            self.host.execdom0("cd %s && ./install.sh" % tmpDir)
            
        step("Ensure the module dependency table has been updated correctly")
        for ko in kos:
            if len(self.host.execdom0("modinfo %s | grep `uname -r`" % ko).strip().splitlines()) == 0:
                raise xenrt.XRTFailure("Could not find kernel version in driver modinfo for %s" % ko)
                    
            if kos[ko] != self.host.execdom0('modinfo %s | grep "^srcversion:"' % ko):
                raise xenrt.XRTFailure("driver modinfo shows incorrect version. It should be \"%s\"." % kos[ko])

            version = self.host.execdom0("modinfo %s | grep -e '^version:' | awk '{print $2}'" % ko).strip()
            log("Driver version: %s" % (version))

            log("Use modprobe to force the driver to load. Check for warnings/errors")
            stdout = self.host.execdom0('modprobe %s' % ko)
            xenrt.TEC().logverbose("modprobe output: '%s'" % stdout)
            if stdout.strip() != "":
                raise xenrt.XRTFailure("Loading kernel module %s may have failed, see stout: '%s'" % (ko, stdout))

        step("Check if kdump  is built")
        for ko in kokdump:
            if "kdump" not in self.host.execdom0("modinfo %s | grep vermagic" % (ko)):
                raise xenrt.XRTFailure("Module was not built against the kdump kernel for %s" % ko)

    def run(self, arglist):
        driverDisk = xenrt.TEC().lookup("DRIVER_PATH")
        xenrt.TEC().comment("Driver Disk supplied for testing: %s" % driverDisk)

        if self.runSubcase("testDriverInstallation", (), "DriverDisk", "Installation"):
            return 


class TCDom0Checksums(xenrt.TestCase):
    def run(self, arglist):
        host = self.getDefaultHost()
        out = ""
        out += host.execdom0("""find /bin -type f| sort | xargs md5sum""", timeout=1800)
        out += host.execdom0("""find /boot  -type f | sort | xargs md5sum""", timeout=1800)
        out += host.execdom0("""find /etc -type f | egrep -v "pyc$" | egrep -v "bak$" | egrep -v "log$" | egrep -v "~$" | sort | xargs md5sum""", timeout=1800)
        out += host.execdom0("""find /usr -type f | egrep -v "pyc$" | egrep -v "pyo$" | egrep -v "bak$" | sort | xargs md5sum""", timeout=1800)
        out += host.execdom0("""find /opt -type f | egrep -v "pyc$" | egrep -v "bak$" | egrep -v "cpio$" | grep -v "patch-backup" | sort | xargs md5sum""", timeout=1800)
        out += host.execdom0("""find /sbin -type f | sort | xargs md5sum""", timeout=1800)
        out += host.execdom0("""find /var -type f | grep -v "/var/lock" | grep -v "/var/log" | egrep -v "pid$" | egrep -v "log$" | grep -v "/var/swap"| grep -v "/var/xapi/blobs" | grep -v "/var/run/sr-mount" | sort | xargs md5sum""", timeout=1800)
        

        f = open("%s/md5sums.txt" % (xenrt.TEC().getLogdir()), "w")
        f.write(out)
        f.close()

class TCDiffChecksums(xenrt.TestCase):
    def run(self, arglist):
        logdir = xenrt.TEC().getLogdir()
        logServer = xenrt.TEC().lookup("LOG_SERVER")
        jobid = xenrt.GEC().jobid()

        # Retrieve the checksum files
        xenrt.command("wget -O %s/original.txt http://%s/xenrt/logs/job/%d/IsoRepack/TCOriginalChecksums/binary/md5sums.txt" % (logdir, logServer, jobid))
        xenrt.command("wget -O %s/repacked.txt http://%s/xenrt/logs/job/%d/IsoRepack/TCRepackedChecksums/binary/md5sums.txt" % (logdir, logServer, jobid))
        xenrt.command("wget -O %s/hotfixed.txt http://%s/xenrt/logs/job/%d/IsoRepack/TCHotfixedChecksums/binary/md5sums.txt" % (logdir, logServer, jobid))

        # Filter each file to remove known volatile entries
        self.filterChecksums("%s/original.txt" % logdir)
        self.filterChecksums("%s/repacked.txt" % logdir)
        self.filterChecksums("%s/hotfixed.txt" % logdir)

        # Output the diffs
        self.diff("original", "repacked", "originalVsRepacked.txt")
        self.diff("original", "hotfixed", "originalVsHotfixed.txt")
        self.diff("repacked", "hotfixed", "repackedVsHotfixed.txt")

    def filterChecksums(self, checksumFile):
        f = open(checksumFile, "r")
        entries = f.read().splitlines()
        f.close()
        filteredEntries = []
        for e in entries:
            es = e.split()
            path = es[1]
            if path in ["/boot/ldlinux.sys", "/etc/adjtime", "/etc/fstab",
                        "/etc/issue", "/etc/mtab", "/etc/ntp.conf.predhclient",
                        "/etc/openvswitch/conf.db", "/etc/xensource/boot_time_cpus",
                        "/etc/xensource-inventory", "/etc/xensource/ptoken",
                        "/etc/xensource/xapi-ssl.pem", "/var/lib/likewise/db/registry.db",
                        "/var/lib/nfs/statd/state", "/var/lib/ntp/drift",
                        "/var/lib/random-seed", "/var/lib/pbis/db/registry.db"]:
                continue

            if any([path.startswith(sw) for sw in ["/boot/initrd", "/etc/blkid/blkid",
                                                   "/etc/firstboot.d/data/", "/etc/firstboot.d/state/",
                                                   "/etc/lvm/backup/", "/etc/lvm/cache/", "/etc/ssh/ssh_host_",
                                                   "/etc/sysconfig/network-scripts/interface-rename-data/",
                                                   "/var/run/", "/var/xapi/"]]):
                continue
            filteredEntries.append(e)
        f = open(checksumFile, "w")
        f.write("\n".join(filteredEntries))
        f.close()

    def diff(self, a, b, output):
        logdir = xenrt.TEC().getLogdir()
        diff = xenrt.command("diff -u %s/%s.txt %s/%s.txt" % (logdir, a, logdir, b), ignoreerrors=True)
        f = open("%s/%s" % (logdir, output), "w")
        f.write(diff)
        f.close()
        xenrt.TEC().logverbose("%s vs %s host diff at %s" % (a, b, output))

class TCIsoChecksums(xenrt.TestCase):
    """Testcase to compare checksums on a XenServer ISO with a reference ISO"""

    def run(self, arglist):
        # We expect the input dir will be the directory with the repacked ISO
        # We can find the old directory by looking up PIDIR_<PRODUCT_VERSION>

        productVersion = xenrt.TEC().lookup("PRODUCT_VERSION").upper()
        imagePath = xenrt.TEC().lookup("CD_PATH_%s" % productVersion,
                                       xenrt.TEC().lookup('CD_PATH', 'xe-phase-1'))
        originalIso = xenrt.TEC().getFile(os.path.join(xenrt.TEC().lookup("PIDIR_%s" % productVersion), imagePath, "main.iso"))
        repackedIso = xenrt.TEC().getFile(os.path.join(imagePath, "main.iso"))

        logdir = xenrt.TEC().getLogdir()

        # Checksum all files on the ISOs
        xenrt.TEC().logdelimit("Comparing ISO contents")
        originalMount = xenrt.MountISO(originalIso)
        originalSums = xenrt.command("cd %s; find . -type f | sort | xargs md5sum" % originalMount.getMount(), timeout=1800)
        originalMount.unmount()
        f = open("%s/original_md5s.txt" % logdir, "w")
        f.write(originalSums)
        f.close()
        repackMount = xenrt.MountISO(repackedIso)
        repackSums = xenrt.command("cd %s; find . -type f | sort | xargs md5sum" % repackMount.getMount(), timeout=1800)
        repackMount.unmount()
        f = open("%s/repack_md5s.txt" % logdir, "w")
        f.write(repackSums)
        f.close()

        diff = xenrt.command("diff -u %s/original_md5s.txt %s/repack_md5s.txt" % (logdir, logdir), ignoreerrors=True)
        f = open("%s/md5_diff.txt" % logdir, "w")
        f.write(diff)
        f.close()

        xenrt.TEC().logverbose("ISO contents diff written to md5_diff.txt")

        # Compare the boot sectors
        xenrt.TEC().logdelimit("Comparing ISO boot images")
        origBoot = xenrt.command("%s/geteltorito %s | md5sum | awk '{print $1}'" % (xenrt.TEC().lookup("LOCAL_SCRIPTDIR"), originalIso), strip=True)
        repackBoot = xenrt.command("%s/geteltorito %s | md5sum | awk '{print $1}'" % (xenrt.TEC().lookup("LOCAL_SCRIPTDIR"), repackedIso), strip=True)
        if origBoot != repackBoot:
            raise xenrt.XRTFailure("Boot image checksums differ", data="Original %s, Repack %s" % (origBoot, repackBoot))

        # Compare the volume label
        xenrt.TEC().logdelimit("Comparing ISO volume labels")
        origLabel = xenrt.command("file -b %s" % originalIso, strip=True)
        repackLabel = xenrt.command("file -b %s" % repackedIso, strip=True)
        if origLabel == repackLabel:
            raise xenrt.XRTFailure("ISO volume labels are identical")

        # Output isoinfo for reference
        xenrt.TEC().logdelimit("Getting isoinfo")
        xenrt.TEC().logverbose("Original ISO:")
        xenrt.command("isoinfo -d -i %s" % originalIso)
        xenrt.TEC().logverbose("Repacked ISO:")
        xenrt.command("isoinfo -d -i %s" % repackedIso)
        
class TC21452(xenrt.TestCase):
    """Testcase to verify whether logrotate -v -f works(CA-108965)"""
    def prepare(self, arglist=None): 
        self.host = self.getDefaultHost()
        self.host.execdom0("echo test > /root/logfile.db")
        self.host.execdom0("echo -e '/root/logfile.db {\n\trotate 5\n\tmissingok\n}' > /root/log.conf")
        self.sruuid=self.host.getLocalSR()
        
        #Running xe-backup-metadata
        self.host.execdom0("xe-backup-metadata -c -u %s" % (self.sruuid))
        
    def run(self, arglist=None):
        
        #Checking working of logrotate -v -f
        self.host.execdom0("logrotate -v -f /root/log.conf")
        flist = self.host.execdom0("ls logfile* ", retval="string")
        if not "logfile.db.1" in flist:
            raise xenrt.XRTFailure("logrotate -v -f not working")
        #Running second time xe-backup-metadata
        res=self.host.execdom0("xe-backup-metadata -c -u %s" % (self.sruuid),retval="string")        
        r=re.search(r"\n.*/var/run/pool-backup.*\n",res)
        if r :
            raise xenrt.XRTFailure(r.group(0))

class TC20917(xenrt.TestCase):
    """Test VM-lifecycle/device unplug after guest xenstore quota reached (HFX-952) """
    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericLinuxGuest()

    def fillXenStoreQuota(self):
        i = 0
        while True:
            try:
                self.guest.execguest("for i in {%u..%u}; do xenstore-write data/quota$i test; done" % (i, i+100))
            except:
                break
            i += 100

    def run(self, arglist):
        vbd = self.guest.createDisk(sizebytes=xenrt.MEGA, returnVBD=True)
        self.fillXenStoreQuota()
        self.host.getCLIInstance().execute("vbd-unplug uuid=%s" % vbd)
        
        self.guest.reboot()
        self.fillXenStoreQuota()
        self.guest.shutdown()
        
class TC20920(xenrt.TestCase):
    #This testcase is derived from HFX-890 in Hotfix TipEx
    def run(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guest = self.getGuest("lin01")
        self.host.execdom0("xl cpupool-numa-split")        
        try :
            self.host.execdom0("while true; do xl cpupool-migrate %s Pool-node1 ;"
                "xl cpupool-migrate %s Pool-node0 ; done;"
                %(self.guest.getDomid(),self.guest.getDomid()) ,getreply=False )       
        except Exception, e:
            raise xenrt.XRTFailure("Exception occurred while migrating the VM across cpu pools : %s"%(e))
            
        deadline = xenrt.timenow() + 300
        try :
            while xenrt.timenow() < deadline:
                self.host.checkReachable(timeout=10)
                xenrt.sleep(5)
        except Exception, e:
            raise xenrt.XRTFailure("Exception occurred while checking host reachability : %s"%(e))
        xenrt.TEC().logverbose("XEN doesn't hang after applying update")

class TCHostRebootLoop(xenrt.TestCase):
    def run(self, arglist):
        h = self.getDefaultHost()
        for i in range(1000):
            h.reboot()

class TCCheckLocalDVD(xenrt.TestCase):
    """Verify that a local DVD drive can be accessed by guests"""
    HVMDISTRO = "rhel7"
    HVMARCH = "x86-64"

    def prepare(self, arglist):
        self.host = self.getDefaultHost()

        # Ensure we don't have anything in the virtual media
        self.virtualmedia = self.host.machine.getVirtualMedia()
        self.virtualmedia.unmountCD()

        # TODO: Parallelise these
        self.device = {}
        self.guests = []

        xenrt.pfarm([(self.createGuest, False), (self.createGuest, True)])

        # Ensure the guests have CD devices and they're empty
        for g in self.guests:
            cd = self.host.minimalList("vbd-list", "empty", args="vm-uuid=%s type=CD" % g.getUUID())
            if len(cd) == 0:
                cli = self.host.getCLIInstance()
                cli.execute("vbd-create", "vm-uuid=%s device=3 type=CD mode=RO" % g.getUUID())
                break
            if len(cd) > 1:
                raise xenrt.XRTError("Installed guest had more than one CD drive!")
            if cd[0] == "false":
                g.changeCD(None)

        # Identify the DVD SR etc
        self.dvdSR = self.host.minimalList("sr-list", args="type=udev content-type=iso")[0]

    def createGuest(self, pv):
        if pv:
            g = self.host.createGenericLinuxGuest()
            self.device[g] = "xvdd"
            self.guests.append(g)
        else:
            g = self.host.createBasicGuest(distro=self.HVMDISTRO, arch=self.HVMARCH)
            self.device[g] = "cdrom"
            self.guests.append(g)

    def run(self, arglist):

        # Verify the devices show as empty
        self.checkDVDPresence(False)

        # Plug an ISO to the virtual media
        iso = "%s/isos/reader.iso" % xenrt.TEC().lookup("TEST_TARBALL_ROOT")
        self.virtualmedia.mountCD(iso)

        xenrt.sleep(20)

        vdiName = self.host.minimalList("vdi-list", "name-label", args="sr-uuid=%s" % self.dvdSR)[0]

        # Plug it through to the guests
        for g in self.guests:
            g.changeCD(vdiName)

        xenrt.sleep(60)

        # Verify the guests see the DVD
        self.checkDVDPresence(True)

        # Verify the DVD checksum
        self.checkDVDChecksum(iso)

        # Unplug it from the guests
        for g in self.guests:
            g.changeCD(None)

        xenrt.sleep(60)

        # Now eject the CD from the host
        self.virtualmedia.unmountCD()

        # Verify the guests doesn't see the DVD
        self.checkDVDPresence(False)

    def checkDVDPresence(self, expectedPresent):
        expectedCode = 0 if expectedPresent else 2
        for g in self.guests:
            if g.execguest("blkid /dev/%s" % self.device[g], retval="code") != expectedCode:
                if expectedPresent:
                    raise xenrt.XRTFailure("DVD not found in guest when expected")
                else:
                    raise xenrt.XRTFailure("DVD found in guest when not expected")

    def checkDVDChecksum(self, iso):
        realChecksum = xenrt.command("md5sum %s" % iso)
        for g in self.guests:
            checksum = g.execguest("md5sum /dev/%s" % self.device[g])
            if checksum != realChecksum:
                raise xenrt.XRTError("In-guest checksum of physical DVD drive didn't match DVD")

    def postRun(self):
        try:
            self.virtualmedia.unmountCD()
        except:
            pass

class TCSlaveConnectivity(xenrt.TestCase):
    #TC-23773
    """Test case for SCTX-1562- slave servers lost connection to master server 
    on receiving error for writing a packet that exceeds the 300k limit"""
    def prepare(self, arglist):
        step("Create plugin on the slave host")
        self.pool = self.getDefaultPool()
        plugin="""#!/usr/bin/python
import XenAPIPlugin
BRAIN_STR = "brain!"

def main(session, args):
    try:
        size = int(args["brain-size"])
        return (BRAIN_STR * (size / len(BRAIN_STR) + 1))[:size]
    except KeyError:
        raise RuntimeError("No argument found with key 'brain-size'.")

if __name__ == "__main__":
    XenAPIPlugin.dispatch({"main": main})
"""

        self.slave = self.pool.slaves.values()[0]
        sftp = self.slave.sftpClient()
        t = xenrt.TEC().tempFile()
        with open(t, 'w') as f:
            f.write(plugin)
        sftp.copyTo(t, "/etc/xapi.d/plugins/braindump")
        self.slave.execdom0("chmod +x /etc/xapi.d/plugins/braindump")
        sftp.close()
        
    def run(self, arglist=None):
        step("Call plugin from the master host")
        cli = self.pool.master.getCLIInstance()
        args = []
        args.append("host-uuid=%s" % (self.slave.getMyHostUUID()))
        args.append("plugin=braindump")
        args.append("fn=main")
        args.append("args:brain-size=$(( 310*1024 ))")
        try:
            output = cli.execute("host-call-plugin", string.join(args), timeout=600)
            if "brain" in output:
                xenrt.TEC().logverbose("Expected output: %s" % (output))
            else:
                raise xenrt.XRTFailure("Unexpected output: %s" % (output))
        except Exception, e:
            if "Client_requested_size_over_limit" not in str(e):
                raise

class TCDom0PartitionClean(xenrt.TestCase):
    #TC-27020
    """Test case for checking Dom0 disk partitioning on clean installation: Dundee onwards(REQ-176)"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
    
    def run(self, arglist):
        step("Compare Dom0 partitions")
        partitions = self.host.lookup("DOM0_PARTITIONS")
        if self.host.compareDom0Partitions(partitions):
            log("Found expected Dom0 partitions on XS clean installation: %s" % partitions)
        else:
            raise xenrt.XRTFailure("Found unexpected partitions on XS clean install. Expected: %s Found: %s" % (partitions, self.host.getDom0Partitions()))

class TCSwapPartition(xenrt.TestCase):
    #TC-27021
    """Test case for checking if SWAP partition is in use when running out of memory"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
    
    def run(self, arglist):
        step("Fetch Size of Swap Partition")
        swapUsed= float(self.host.execdom0("free -m | grep Swap | awk '{print $3}'"))
        
        step("Eat up memory by running a script")
        self.host.execdom0("cp -f %s/utils/memEater_x64 /root/; chmod +x /root/memEater_x64" % xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), level=xenrt.RC_OK)
        self.host.execdom0("/root/memEater_x64", getreply = False)
        step("Check if swap is in use")
        startTime = xenrt.util.timenow()
        while xenrt.util.timenow() - startTime < 900:
            newSwapUsed= float(self.host.execdom0("free -m | grep Swap | awk '{print $3}'"))
            if newSwapUsed > swapUsed:
                break
        try: self.host.execdom0("pkill memEater_x64")
        except: pass

        if newSwapUsed > swapUsed:
            log("SWAP is in use as expected. SWAP memory in use = %s" % (newSwapUsed))
        else:
            raise xenrt.XRTFailure("SWAP partition is not in use. SWAP memory in use = %s" % (newSwapUsed))
