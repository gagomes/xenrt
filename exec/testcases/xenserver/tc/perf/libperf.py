import xenrt
import time, string, re
import sys
import traceback
import XenAPI
import os.path
import thread
import itertools

# Telti is a NetApp machine used as an NFS server in the performance dev vpn.
teltiIP = "192.168.0.100"

# When we move to Python2.6 (or newer), replace curry with functools.partial

def curry (func, *args, **kwds):
    """curry (fun, *args, **kwds)
    Creates a new function calling the old function fun
    with some of the arguments already supplied.
    """
    def callit(*moreargs, **morekwds):
        kw = kwds.copy()
        kw.update(morekwds)
        return func(*(args+moreargs), **kw)
    return callit

def createLogName(stem):
    """Returns the full path (doesn't actually create a file)"""
    filename = os.path.join (xenrt.TEC().getLogdir(), stem+".log")
    return filename

def outputToResultsFile(filename, line, addNewline=True):
    """filename is usually created via createLogName(stem)"""
    fd = open(filename, "a")
    fd.write(line)
    if addNewline:
        fd.write("\n")
    fd.close()

def boolOfStrDefault(default):
    """Returns a function that converts optional str to bool, e.g.
    boolOfStrDefault(True)() -> True
    boolOfStrDefault(True)("no") -> False
    The generated functions are ued as callbacks for getArgument."""
    def f(s = default):
        if isinstance(s, bool):
            return s
        else:
            b = s.lower().strip()
            if b in ["y", "yes", "t", "true", "1", "on"]:
                return True
            elif b in ["n", "no", "f", "false", "0", "off"]:
                return False
            else:
                raise ValueError("Cannot parse string as boolean: " + s)
    return f

def logArg(name, value):
    outputToResultsFile(createLogName("arguments"), "'%s'='%s'" % (name, value))

def getArgument (arglist, name, convert, defaultValue):
        """Reads and parses an argument from the command line or sequence file.

        Has no side-effects except logging.
        Can read a sequence file argument (either type)
        or a xrt-style command line argument, e.g. "[...] -D
        name=value". TODO find out which takes precedence."""


        # if this ever becomes a bottleneck, memoize argdict.
        def split(arg):
            if '=' not in arg:
                return (arg, [])
            else:
                (name,val) = arg.split('=',1)
                return (name, [val])

        argdict = dict (map (split, arglist))

        try: value = [xenrt.TEC().lookup(name)]
        except xenrt.XRTError:
            try: value = argdict[name]
            except KeyError:
                xenrt.TEC().logverbose("getArgument "+
                    "(arglist=%s, name=%s, convert=%s, defaultValue=%s) = defaultValue" %
                    (arglist, name, convert, defaultValue))
                logArg(name, defaultValue)
                return defaultValue
        cvalue = convert (*value)
        xenrt.TEC().logverbose("getArgument "+
                       "(arglist=%s, name=%s, convert=%s, defaultValue=%s) = %s" %
                       (arglist, name, convert, defaultValue, repr(cvalue)))
        logArg(name, cvalue)
        return cvalue

# Parse the output from the 'time' command, returning the number of seconds as a float
# e.g. '\nreal\t1m10.156s\nuser\t0m0.000s\nsys\t0m0.000s\n' -> 70.156
def parseTimeOutput(output):
    totaltimestr = output.split('\n')[-4].split('\t')[1]
    return parseMinutesSeconds(totaltimestr)

# e.g. '1m10.156s' -> 70.156
def parseMinutesSeconds(totaltimestr):
    totaltimerec = totaltimestr.strip('s').split('m')
    totaltimesecs = float(totaltimerec[1]) + 60*float(totaltimerec[0])
    return totaltimesecs

def timeCLICommand(host, cmd):
    output = host.execdom0(cmd)
    xenrt.TEC().logverbose(output)
    totaltimesecs = parseTimeOutput(output)
    return totaltimesecs

class PerfTestCase(xenrt.TestCase):

    def __init__(self, name):
        xenrt.TestCase.__init__(self, name)

        self.host = None
        self.pool = None
        # TODO: rename guest to something more meaningful: here in
        # PerfTestCase it is always a generic linux helper guest, but
        # in the child classes sometimes it is other things (so should
        # be called something different there).
        self.guest = None

        # TODO: move vmsbooted and lock into child class.
        self.vmsbooted = 0 # global variable counting total VMs booted by all Starter threads
        self.vmsbootedlock = thread.allocate_lock()

        self.perfloggingdir    = {}
        self.nfsServerHostObj  = None
        self.goldimagesruuid   = None

    def basicPrepare(self, arglist):
        self.arglist = arglist
        self.parseArgs(arglist)

        self.initialiseHostList()
        self.configureAllHosts()

    def readArg(self, name, convert, defaultValue, possible=None):
        value = getArgument(self.arglist, name, convert, defaultValue)
        if possible:
            possible.append(defaultValue)
            if value not in possible:
                err = "'%s' must be set to one of: %s." % (name, ", ".join(possible))
                raise NotImplementedError(err)
        setattr(self, name, value)

    def log(self, filename, msg):
        """Logs to a file and console"""
        xenrt.TEC().logverbose(msg)
        if filename is not None:
            outputToResultsFile(createLogName(filename), msg)

    def getAndSetArg(self, name, convert, defaultValue):
        """Before calling this function, make sure "self.arglist = arglist".
        Can read a sequence file argument or a xrt-style command line
        argument, e.g. "[...] -D name=value", where the command line argument
        takes precedence. This results in "self.name = value". This function
        has no return value."""
        setattr(self, name, getArgument(self.arglist, name, convert, defaultValue))

    def parseArgs(self, arglist=[]):
        # TODO move some of these args into the relevant child classes.
        get = curry (getArgument, arglist)

        # Very fast NFS server for SRs, probably a NetApp.
        self.fastStoreIP = get ("faststore", str, teltiIP)

        # A server holding misc. useful software, VM-images etc.
        self.refStoreIP = get ("refstore", str, teltiIP)

        # None to keep the normal xapi, or "xapi_george-update-1_mps"
        # or "xapi-george-mps" for a patched version. Can be
        # overridden in .seq files.
        self.xapiRequired = get ("xapi", str, None)

        self.useLocalSRs = get ("uselocalsrs", boolOfStrDefault(True), False)
        self.nfsserverhost = get ("nfsserverhost", str, None)
        self.crippleNfs = get ("cripplenfs", boolOfStrDefault(True), False)

        # XenServer configuration settings
        self.asyncLogging = get ("asynclogging", boolOfStrDefault(True), False)
        self.memoryTarget = get ("memorytarget", int, None)
        self.bufferCache = get ("buffercache", str, None)
        self.performanceLogging = get ("perflogging", boolOfStrDefault(True), False)
        self.localStorageCaching = get ("localstoragecaching", boolOfStrDefault(True), False)
        self.resetOnBoot = get ("resetonboot", boolOfStrDefault (True), False)
        self.tune2fsOption = get ("tune2fsoption", str, None)

        # Pausing the starter threads
        self.pauseat = get ("pauseat", int, None)
        self.pausefor = get ("pausefor", int, None)

        # Pause each VM until all have started, then set them all going again so their OSs boot concurrently.
        self.parallelBoot = get ("parallelboot", boolOfStrDefault(True), False)

        # Name of desktop image used in VM-start tests
        self.desktopimage = get("desktopimage", str, "desktop3.img")
        self.desktopvmname = get("desktopvmname", str, "desktop3")
        self.desktopvmnetwork = get("network", str, "NPRI bond of 0 1 2 3")

        self.hostrootpassword = xenrt.TEC().lookup("ROOT_PASSWORD")

        self.useMPS = get ("dontusemps", boolOfStrDefault(False), True)

        self.clockTime = get ("date", str, None)
        # by default, put the VMs on the bond network
        self.dontGiveVIFsToVMs = get ("novifs", boolOfStrDefault(True), False)

        logMsg = lambda params: ', '.join(["%s=%s" % (param, getattr(self, param))
                                           for param in params])

        xenrt.TEC().logverbose("Test configuration: " + logMsg (
                ["xapiRequired", "performanceLogging",
                 "localStorageCaching", "resetOnBoot", "clockTime",
                 "useLocalSRs", "nfsserverhost"]))

        xenrt.TEC().logverbose("XenServer configuration: " + logMsg (
                ["asyncLogging", "tune2fsOption", "memoryTarget", "bufferCache"]))
    
    # TODO: make helper functions to replace the larger blocks in this very long function.
    def configureAllHosts(self):
        """Configure XenServer according to arguments in the .seq file."""

        # Set self.goldimagesruuid to either use fastStore or create and use an NFS server VM
        xenrt.TEC().logverbose("XS configuration parameter 'nfsserverhost' is [%s]" % self.nfsserverhost)
        if self.nfsserverhost is None:
            try:
                xenrt.TEC().logverbose("Seeing if we have a fast store accessible...")
                self.goldimagesruuid = self.getFastStoreUUID()
            except Exception, e:
                xenrt.TEC().logverbose("Exception: %s" % str(e))
                xenrt.TEC().logverbose("No fast store accessible")
                # e.g. because there are no NFS SRs configured in the sequence file
                self.goldimagesruuid = None
        else:
            xenrt.TEC().logverbose("NFS server enabled for host %s" % self.nfsserverhost)
            if self.nfsserverhost not in self.everyHost:
                raise Exception("NFS server host %s should be in the list of hosts %s." % (self.nfsserverhost, ", ".join(self.everyHost)))

            self.nfsServerHostObj = self.tec.gec.registry.hostGet(self.nfsserverhost)
            
            # Create a debian VM in the local SR
            localSR = self.nfsServerHostObj.getLocalSR()
            xenrt.TEC().logverbose("creating debian VM in SR %s on bridge %s" % (localSR, "xenbr4"))
            nfsServerVM = self.nfsServerHostObj.createGenericLinuxGuest(name="Linux NFS server", start=False, sr=localSR, bridge="xenbr4")

            # Attach a big disk to it
            size = 200 * 1024 * 1024 * 1024 # 200 GiB
            xenrt.TEC().logverbose("creating disk of size %Ld in SR %s" % (size, localSR))
            userdev = nfsServerVM.createDisk(sizebytes=size, sruuid=localSR)

            xenrt.TEC().logverbose("the disk is at userdevice %s" % userdev)

            # Make it into an NFS server
            path = "/nfs"

            xenrt.TEC().logverbose("starting the VM...")
            nfsServerVM.start()

            diskDeviceName = self.nfsServerHostObj.parseListForOtherParam(
                "vbd-list",
                "vm-uuid",
                nfsServerVM.getUUID(),
                "device",
                "userdevice=%s" % (userdev))
            xenrt.TEC().logverbose("the disk has device name %s" % diskDeviceName)

            xenrt.TEC().logverbose("enabling NFS serving")
            cmds = [
                "apt-get install -y --force-yes nfs-kernel-server",
                "mkdir %s" % path,
                "mkfs.ext3 /dev/%s" % diskDeviceName,
                "mount /dev/%s %s" % (diskDeviceName, path),
                "chmod 777 %s" % path,
                "echo '%s   *(rw,%s,no_subtree_check)' >> /etc/exports" %
                    (path, {True:"sync", False:"async"} [self.crippleNfs]),
                "/etc/init.d/nfs-kernel-server restart",
                ]

            nfsServerVM.execguest (" && ".join(cmds))

            # Find out the IP address of the guest
            ip = nfsServerVM.getIP()
            xenrt.TEC().logverbose("IP address of NFS guest is %s" % ip)

            # Create an SR on the NFS share. Do this on a host that will see the SR, not the NFS server which just holds it.
            srhost = self.tec.gec.registry.hostGet(self.normalHosts[0])
            nfssr = xenrt.lib.xenserver.NFSStorageRepository(srhost, "SR on %s using NFS on %s" % (srhost.getName(), self.nfsserverhost))
            nfssr.create(ip, path)
            self.goldimagesruuid = nfssr.uuid
            srhost.addSR(nfssr, default=True)
            xenrt.TEC().logverbose("Created SR on %s using NFS on %s:%s with uuid %s" % (srhost.getName(),ip,path,self.goldimagesruuid))

        xenrt.TEC().logverbose("Gold image SR uuid is %s" % self.goldimagesruuid)

        xenrt.TEC().logverbose("XS configuration parameter 'localStorageCaching' is [%s]" % self.localStorageCaching)
        xenrt.TEC().logverbose("XS configuration parameter 'resetOnBoot' is [%s]" % self.resetOnBoot)
        if self.localStorageCaching or self.resetOnBoot:
            xenrt.TEC().logverbose("Enabling local storage caching on all hosts")
            for h in self.normalHosts:
                xenrt.TEC().logverbose("host is [%s]" % h)
                host = self.tec.gec.registry.hostGet(h)

                # Local storage is assumed to be ext already

                cmds = [
                    "xe host-disable host=%s" % host.getName(),
                    "localsr=`xe sr-list type=ext host=%s params=uuid --minimal`" % host.getName(),
                    "echo localsr=$localsr",
                    "xe host-enable-local-storage-caching host=%s sr-uuid=$localsr" % host.getName(),
                    "xe host-enable host=%s" % host.getName(),
                ]
                output = host.execdom0(" && ".join(cmds))
                xenrt.TEC().logverbose("output: %s" % output)

        xenrt.TEC().logverbose("XS configuration parameter 'performanceLogging' is [%s]" % self.performanceLogging)
        if self.performanceLogging:
            xenrt.TEC().logverbose("Enabling performance logging on all hosts")
            for h in self.normalHosts:
                xenrt.TEC().logverbose("host is [%s]" % h)
                host = self.tec.gec.registry.hostGet(h)
                refBaseDir = self.mountRefBase(host.execdom0)
                host.execdom0("cp %s/gather-test-status.sh /root" % refBaseDir)
                output = host.execdom0("/root/gather-test-status.sh %s" % self.hostrootpassword)
                xenrt.TEC().logverbose("OUTPUT: %s" % output)

                for line in output.split('\n'):
                    if line.startswith('output directory is'):
                        self.perfloggingdir[h] = line.split(' ')[3]
                        xenrt.TEC().logverbose("so performance logging dir on host %s is %s" % (h, self.perfloggingdir[h]))

        xenrt.TEC().logverbose("XS configuration parameter 'tune2fsoption' is [%s]" % self.tune2fsOption)
        if self.tune2fsOption:
            for h in self.normalHosts:
                xenrt.TEC().logverbose("host is [%s]" % h)
                host = self.tec.gec.registry.hostGet(h)
                cmd = "tune2fs -o %s /dev/sda1" % self.tune2fsOption
                xenrt.TEC().logverbose("executing %s on %s" % (cmd, h))
                output = host.execdom0(cmd)
                xenrt.TEC().logverbose("output: %s" % output)
                xenrt.TEC().logverbose("rebooting host to re-mount FS")
                host.reboot()

        xenrt.TEC().logverbose("XS configuration parameter 'asyncLogging' is [%s]" % self.asyncLogging)
        if self.asyncLogging:
            xenrt.TEC().logverbose("MAKING /var/log/secure ASYNCHRONOUS")
            for h in self.normalHosts:
                xenrt.TEC().logverbose("host is [%s]" % h)
                host = self.tec.gec.registry.hostGet(h)
                output = host.execdom0("mv /etc/syslog.conf /etc/syslog.conf_ORIG; cat /etc/syslog.conf_ORIG | sed 's/\/var\/log\/secure/-\/var\/log\/secure/' > /etc/syslog.conf; cat /etc/syslog.conf; /etc/init.d/syslog restart")
                xenrt.TEC().logverbose("OUTPUT: %s" % output)

        xenrt.TEC().logverbose("XS configuration parameter 'memoryTarget' is [%s]" % self.memoryTarget)
        # TODO: decide whether memoryTarget should apply to the nfs server if there is one.
        if self.memoryTarget is not None:
            xenrt.TEC().logverbose("setting memory target to %Ld" % self.memoryTarget)
            for h in self.normalHosts:
                xenrt.TEC().logverbose("host is [%s]" % h)
                host = self.tec.gec.registry.hostGet(h)

                conf = host.execdom0("cat /boot/extlinux.conf")
                xenrt.TEC().logverbose("/boot/extlinux.conf contains: %s" % conf)
                cli = host.getCLIInstance()

                # Find out the UUID of dom0
                dom0uuid = host.execdom0(". /etc/xensource-inventory; echo $CONTROL_DOMAIN_UUID").strip()
                xenrt.TEC().logverbose("dom0 uuid is %s" % dom0uuid)

                # Find out what static max is. (Usually it's a bit below what we set on the xen command-line.)
                staticmax = cli.execute("vm-param-get", "uuid=%s param-name=memory-static-max" % dom0uuid).strip()

                # Now set the memory target (and the dynamic range) to equal static-max
                # Note: only valid to do this on >= MNR
                cli.execute("vm-memory-target-set", "uuid=%s target=%s" % (dom0uuid, staticmax))
                balloon = host.execdom0("cat /proc/xen/balloon") # for debugging
                xenrt.TEC().logverbose("/proc/xen/balloon contains: %s" % balloon)

        xenrt.TEC().logverbose("XS configuration parameter 'bufferCache' is [%s]" % self.bufferCache)
        if self.bufferCache is not None:
            # We do not have buffercaching blktap that works with Boston, but it does with Cowley.
            xenrt.TEC().logverbose("installing buffer cache patches...")
            for h in self.normalHosts:
                xenrt.TEC().logverbose("enabling buffer cache type %s on host [%s]" % (self.bufferCache, h))
                host = self.tec.gec.registry.hostGet(h)

                refBaseDir = self.mountRefBase(host.execdom0)
                buffercachedir = "%s/buffer-cache" % refBaseDir

                blktapPath = "/opt/xensource/sm/blktap2.py"
                blktapRpmPath = "%s/blktap-5.6.199-567.i686.rpm" % (buffercachedir)
                cmds = [
                    # Note: 'rpm -e blktap' fails due to dependent packages: see jobs/173017/harness.err
                    "( rpm -U %s || rpm -U --oldpackage %s )" % (blktapRpmPath, blktapRpmPath),
                    "mv %s %s.orig" % (blktapPath, blktapPath),
                    "cp %s/blktap2.py.%s %s" % (buffercachedir, self.bufferCache, blktapPath)
                ]
                host.execdom0(" && ".join(cmds))

                # Check the RPMs were installed
                rpms = host.execdom0("rpm -qa | grep blktap")
                xenrt.TEC().logverbose("blktap RPMs are: %s" % rpms)

    def configureAllVMs(self):
        """Execute this after the VMs have been created to run build-specific reconfiguration as defined in .seq file."""
        if self.clockTime is not None:
            xenrt.TEC().logverbose("setting timeoffset on VMs. Note this will have no effect if the VMs have VIFs and use NTP.")
            cmds = [
                "then=`date -d '%s' '+%%s'`" % self.clockTime,
                "now=`date '+%s'`",
                "((diff=then-now))",
                "echo diff=$diff",
                "for vm in `xe vm-list is-control-domain=false power-state=halted params=uuid --minimal | sed 's/,/ /g'`; do echo vm=$vm; xe vm-param-set uuid=$vm platform:timeoffset=$diff; done",
            ]
            output = self.host.execdom0(" && ".join(cmds))
            xenrt.TEC().logverbose("output: %s" % output)

        xenrt.TEC().logverbose("XS configuration parameter 'bufferCache' is [%s]" % self.bufferCache)
        if self.bufferCache is not None:
            xenrt.TEC().logverbose("setting buffer cache options for VDIs to '%s'..." % self.bufferCache)

            # N.B. This string must match the sequence files.
            srname = "fastStoreSR"
            virtualsize = 8 * (2**30) # 8 GiBytes: size of the main VDI in the guest
            cmds = [
                "sr=`xe sr-list name-label=%s params=uuid --minimal`" % srname,
                "echo sr=$sr",
                "vdis=`xe vdi-list sr-uuid=$sr virtual-size=%Ld managed=true params=uuid --minimal | sed 's/,/ /g'`" % virtualsize,
                "echo vdis=$vdis",
                "for vdi in $vdis; do echo vdi=$vdi; xe vdi-param-set uuid=$vdi other-config:iomode=%s; done" % self.bufferCache,
            ]
            output = self.host.execdom0(" && ".join(cmds))
            xenrt.TEC().logverbose("output: %s" % output)

        xenrt.TEC().logverbose("XS configuration parameter 'localStorageCaching' is [%s]" % self.localStorageCaching)
        xenrt.TEC().logverbose("XS configuration parameter 'resetOnBoot' is [%s]" % self.resetOnBoot)
        if self.localStorageCaching or self.resetOnBoot:
            xenrt.TEC().logverbose("enabling PR-1053 on main VDIs in cloned VMs")

            params = [
                "allow-caching=%s" % ((self.localStorageCaching or self.resetOnBoot) and "true" or "false"),
                "on-boot=%s" % (self.resetOnBoot and "reset" or "persist"),
            ]

            cmds = [
                "vdis=`xe vdi-list sr-uuid=%s managed=true params=uuid --minimal | sed 's/,/ /g'`" % self.goldimagesruuid,
                "echo vdis=$vdis",
                "for vdi in $vdis; do echo vdi=$vdi; xe vdi-param-set uuid=$vdi %s; done" % (" ".join(params)),
            ]
            output = self.host.execdom0(" && ".join(cmds))
            xenrt.TEC().logverbose("output: %s" % output)

    def finishUp(self):
        if self.performanceLogging:
            xenrt.TEC().logverbose("Gathering performance logs from all hosts")
            for h in self.normalHosts:
                xenrt.TEC().logverbose("host is [%s]" % h)
                host = self.tec.gec.registry.hostGet(h)

                xenrt.TEC().logverbose("killing performance logger in %s on %s" % (self.perfloggingdir[h], h))
                host.execdom0("for pid in `cat %s/pids`; do kill $pid; done" % self.perfloggingdir[h])

                xenrt.TEC().logverbose("copying performance logging dir from %s %s to logs" % (h, self.perfloggingdir[h]))
                sftp = host.sftpClient()
                destpath = "%s/perflogs/%s" % (xenrt.TEC().getLogdir(), h)
                xenrt.TEC().logverbose("recursively stfping %s to %s" % (self.perfloggingdir[h], destpath))
                sftp.copyTreeFromRecurse(self.perfloggingdir[h], destpath)

    # TODO Document or remove the assumptions this function makes, including
    # the EXTERNAL_NFS_SERVERS section of /etc/xenrt/site.xml on the controller.
    def getFastStoreUUID(self):
        xenrt.TEC().logverbose("Looking for NFS SRs...")
        nfssrs = self.host.getSRs(type="nfs")
        if not nfssrs:
            raise xenrt.XRTError("Could not find any NFS SRs on host")
        xenrt.TEC().logverbose("Found NFS SR(s): %s" % nfssrs)
        return nfssrs[0]

    def mountRefDir(self, dirname, execfn):
        '''This function lazily mounts <EXPORT_DISTFILES_NFS>/performance,
        returning the relative path to the mounted directory with the specified
        dirname appended. The mount is read-only.'''
        def printExec(cmd):
            xenrt.TEC().logverbose("Executing: %s" % cmd)
            return execfn(cmd)
        mountDir = "/mnt/distfiles-perf"
        xenrt_distfiles = xenrt.TEC().lookup("EXPORT_DISTFILES_NFS", None)
        if xenrt_distfiles:
            refBase = "%s/performance" % xenrt_distfiles
        else:
            raise Exception("EXPORT_DISTFILES_NFS not found.")
        # Count the number of matching mounts (without throwing exception if there are zero)
        if len(printExec("mount | grep %s | grep %s; true" % (refBase, mountDir)).strip().splitlines()) < 1:
            try:
                printExec("mkdir -p %s" % mountDir)
                printExec("mount --read-only --types nfs %s %s" % (refBase, mountDir))
            except:
                xenrt.TEC().warning("Unable to mount %s at %s." % (refBase, mountDir))
                raise
        return "%s/%s" % (mountDir, dirname)

    def getPathToDistFile(self, subdir=""):
        '''This function mounts <EXPORT_DISTFILES_NFS>/performance on the
        XenRT controller.'''
        return self.mountRefDir(subdir, lambda cmd: os.popen("sudo %s" % cmd).read())

    def mountRefBase(self, execfn):
        return self.mountRefDir("base", execfn)

    def importVMFromRefBase(self, host, imagefilename, vmname, sruuid, template="NO_TEMPLATE"):
        dir = self.mountRefBase(host.execdom0)
        vmimagefile = "%s/%s" % (dir, imagefilename)

        # Note: we can't use guest.importVM because that relies on the image being visible from the TC environment.
        # timeout: 40 mins. Usually takes around 20 mins.
        vmuuid = host.execdom0("xe vm-import filename=%s sr-uuid=%s" % (vmimagefile, sruuid), timeout=2400).strip()

        xenrt.TEC().logverbose("imported %s into SR %s; uuid is %s" % (vmimagefile, sruuid, vmuuid))

        # Register the new VM as a guest
        newVM = host.guestFactory()(vmname, template, host)
        newVM.uuid = vmuuid
        newVM.existing(host)
        host.addGuest(newVM)

        return newVM


    def getVDIRef(self, vdiuuid):
        # Note: the blank file-name means dump to stdout.
        dbline = self.host.execdom0(
            "xe pool-dump-datebase file-name= | xmllint --format - | grep  '\"%s\"'" % (vdiuuid)
            ).strip()

        xenrt.TEC().logverbose("dbline was [%s]" % dbline)
        vdiref = re.search(r'ref="([^"]+)"', dbline).group(1)
        xenrt.TEC().logverbose("vdiref is [%s]" % vdiref)
        return vdiref

    # TODO explain: what is an identity disk?
    def makeIdentityDisk(self, desktopname, vdiuuid):
        # If useCLI then do 'xe vdi-import' on the host. Otherwise, do 'import_raw_vdi' from the guest.
        useCLI = True

        if useCLI:
            execfun = self.host.execdom0
        else:
            execfun = self.guest.execguest

        # Firstly, see if there's a cached identity disk on the reference store
        dir = self.mountRefDir("identity-disks", execfun)

        cachedidfilepath = "%s/%s.id" % (dir, desktopname)
        xenrt.TEC().logverbose("Checking for cached identity disk %s" % cachedidfilepath)
        cachedidfileexists = (execfun("[ -e %s ]" % cachedidfilepath, retval='code') == 0)
        xenrt.TEC().logverbose("Test for existence returned %s" % (cachedidfileexists))

        file = cachedidfilepath
        if not cachedidfileexists:
            # TODO: Fix or remove.
            # This code-path fails because mkfs.ntfs is not in Dom0.
            # The ntfs tools have been installed in a VM though.
            # Is execfun being set wrongly?

            # It doesn't exist, so make it!
            tmpFile = execfun("mktemp").strip()
            mnt = execfun("mktemp -d -p /mnt").strip();
            xenrt.TEC().logverbose("File is %s" % tmpFile)
            xenrt.TEC().logverbose("Mount point is %s" % mnt)
    
            loop = execfun("losetup -f").strip()
            xenrt.TEC().logverbose("Using loop device %s" % loop)
    
            stem = "CTXSOSID.INI"
            password = "password123"
    
            # Write the identity file to it
            idfile = "%s/%s" % (mnt, stem)
    
            commands = [
                # Create a 10 MB file
                "dd if=/dev/zero of=%s bs=1024 count=10240" % tmpFile,
                # Loop-back mount it
                "losetup %s %s" % (loop, tmpFile),
                # Create an NTFS filesystem on it
                "mkfs.ntfs %s" % loop,
                # Mount it (via the loop device)
                "mount -t ntfs-3g %s %s" % (loop, mnt),
                # Create the identity file
                "echo -e '" + (
"""[Identity]
HostName=%s
MachinePassword=%s
""" % (desktopname, password)).replace('\n', '\\r\\n') + "' > " + idfile,
                # Unmount it
                "umount %s" % mnt,
                "rmdir %s" % mnt,
                # Detach the loop device
                "losetup -d %s 2>&1" % loop,
                # Now save it in the cache
                "mv %s %s" % (tmpFile, cachedidfilepath),
            ]

            # Run all the commands in one go, to save on SSH round-trips
            #execfun(" && ".join(commands))

            # TODO change to the above once things work.
            for c in commands:
                execfun(c)

            xenrt.TEC().logverbose("Created NTFS on %s" % tmpFile)
            xenrt.TEC().logverbose("Loop-back mounted %s at %s (via %s)" % (tmpFile, mnt, loop))
            xenrt.TEC().logverbose("Written identity file for %s" % desktopname)
            xenrt.TEC().logverbose("Finished preparing identity disk in %s" % tmpFile)

        xenrt.TEC().logverbose("Using identity disk in %s" % cachedidfilepath)

        if useCLI:
            self.host.execdom0("xe vdi-import filename=%s uuid=%s" % (cachedidfilepath, vdiuuid))
        else:
            # Find out the ref of the VDI
            vdiref = self.getVDIRef(vdiuuid)
            
            # Now stream it straight from the guest into the VDI
            user = "root"
            host = self.host.getIP()
            pw = host.password
            xenrt.TEC().logverbose("hostname is [%s]" % host)
            
            url = "http://%s:%s@%s/import_raw_vdi?vdi=%s" % (user, pw, host, vdiref)
            xenrt.TEC().logverbose("url is [%s]" % url)
            
            # curl -T test.vdi http://root:xensource@localhost/import_raw_vdi?vdi=OpaqueRef:b1f167ec-d153-3b29-fd95-e82ba1807b49
            self.guest.execguest("curl -T %s %s" % (cachedidfilepath, url), timeout=300) # 5 mins
            xenrt.TEC().logverbose("uploaded image from %s to %s" % (cachedidfilepath, url))

        xenrt.TEC().logverbose("imported image from %s" % cachedidfilepath)

    def putVMonNetwork(self, vm, network="NPRI bond of 0 1 2 3"):
        # Remove the guest's VIF(s)
        vifs = vm.getVIFs()
        for v in vifs:
            xenrt.TEC().logverbose("removing VIF %s from VM %s" % (v, vm.name))
            vm.removeVIF(v)

        if not self.dontGiveVIFsToVMs:
            # Put the guest's VIF onto the true bond's network
            networkuuid = self.host.parseListForUUID("network-list", "name-label", network)
            xenrt.TEC().logverbose("true uuid for network '%s' is %s" % (network, networkuuid))
            bridge = self.host.genParamGet("network", networkuuid, "bridge")
            xenrt.TEC().logverbose("bridge is %s" % bridge)
            vm.createVIF(bridge=bridge)
            xenrt.TEC().logverbose("created a VIF on %s for VM %s" % (bridge, vm.name))

    def importGoldDesktopVM(self, sruuid, exportname, expectedvmname, network="NPRI bond of 0 1 2 3"):
        goldVM = self.importVMFromRefBase(self.host, exportname, expectedvmname, sruuid)
        self.putVMonNetwork(goldVM, network)
        return goldVM

    def installXapiForMPS(self):
        # NB: not required for trunk, so do nothing
        if self.xapiRequired is None:
            return

        for h in self.normalHosts:
            xenrt.TEC().logverbose("host is [%s]" % h)
            host = self.tec.gec.registry.hostGet(h)

            dir = self.mountRefBase(host.execdom0)
            host.execdom0("service xapi stop")
            host.execdom0("cp %s/%s /opt/xensource/bin/xapi" % (dir, self.xapiRequired))
            host.startXapi()

    def installStuffInGuest(self, guest):
        # sshpass for doing stuff on the NetApp
        guest.execguest("apt-get install -y --force-yes sshpass")

        # ntfsprogs
        guest.execguest("apt-get install -y --force-yes ntfsprogs")

        # Portmap is necessary in order to mount -t nfs without taking 1'45.
        guest.execguest("apt-get install -y --force-yes portmap")

        # From http://technowizah.com/2006/11/debian-how-to-writing-to-ntfs.html
        # Get ntfs-3g drivers to allow writing to NTFS
        # Firstly, fetch the ntfs .deb packages from ref-base
        dir = self.mountRefBase(guest.execguest)
        guest.execguest("apt-get install --force-yes -y fuse-utils libfuse2")
        guest.execguest("dpkg -i %s/libntfs-3g0_0.0.0+20061031-6_i386.deb" % dir)
        guest.execguest("dpkg -i %s/ntfs-3g_0.0.0+20061031-6_i386.deb" % dir)

        guest.execguest("apt-get update") # to get it to get libcurl3_7.15.5-1etch2_i386.deb rather than etch1
        guest.execguest("apt-get install -y --force-yes curl")

    def initialiseHostList(self):
        self.host = self.getMaster()
        xenrt.TEC().logverbose("self.host is %s" % self.host)
        self.pool = None
        if hasattr(self.host, 'pool'):
            self.pool = self.host.pool
        xenrt.TEC().logverbose("self.pool is %s" % self.pool)

        # Dirty hack so that the test case works when there are
        # single, unpooled hosts. If we want to do stuff with pools
        # containing anything other than all of the hosts, we'll need
        # to do something different.
        if self.pool is None:
            # TODO (I THINK THE FOLLOWING:) This is indicative that
            # the host is unpooled. In this case, only consider this
            # host.
            self.everyHost = [self._host]
        else:
            # Otherwise, consider all hosts that are defined in the
            # seq file, even if they belong to other pools. We do this
            # for now because I don't know of a way of getting all the
            # hosts in the pool that the host running this TC
            # (self._host) belongs to.
            self.everyHost = self.tec.gec.registry.hostList()

        self.normalHosts = [h for h in self.everyHost
                            if h != self.nfsserverhost]

        xenrt.TEC().logverbose("we've got %d hosts in the pool: %s" % (len(self.everyHost), self.everyHost))

    # TODO Make this idempotent.
    def getMaster(self):
        """Returns the master.
        
        Beware: Might be not idempotent."""
        xenrt.TEC().logverbose("self._host is '%s'" % self._host)
        return self.getDefaultHost()

    # TODO: What is MPS?
    def createVMforMPS(self, name, goldvm):
        xenrt.TEC().logverbose("cloning gold image")
        clone = goldvm.cloneVM(name=name)

        if self.useMPS:
            # Create an unplugged VDI with a VBD on the clone
            sruuid = self.goldimagesruuid
            xenrt.TEC().logverbose("creating disk on sr %s" % sruuid)
            vbduuid = clone.createDisk(sizebytes=(10 * 2**20), sruuid=sruuid, plug=False, returnVBD=True)
            xenrt.TEC().logverbose("VBD uuid is [%s]" % vbduuid)
    
            # Get the UUID of the VDI
            vdiuuid = self.host.genParamGet("vbd", vbduuid, "vdi-uuid")
            xenrt.TEC().logverbose("VDI uuid is [%s]" % vdiuuid)
    
            # Make an identity disk and upload it to the VDI
            xenrt.TEC().logverbose("populating disk as identity disk for host with name '%s'" % name)
            self.makeIdentityDisk(name, vdiuuid)

        return clone

    def timeStartVMs(self, numthreads, clones, starterLogfile, bootwatcherLogfile,
                     queueHosts=itertools.repeat(None), awaitParam="other",
                     awaitKey="feature-shutdown"):
        """timeStartVMs (...)
        @param queueHosts iterator of hostname of a host for each queue. If None, VMs queues are not associated with specific hosts. If not None, must be the same length as numthreads.
        if awaitParam is None, don't use a BootWatcher"""
        # Mimics parallel-start-xmlrpclib-threadperhost
        xenrt.TEC().logverbose("timeStartVMs")
        xenrt.TEC().logverbose("we have %d desktop VMs" % len(clones))
        xenrt.TEC().logverbose("we have %d hosts" % numthreads)

        from itertools import imap, count

        def createThread (i, queue, useHost):
            t = Starter(self, queue, starterLogfile, onHost=useHost,
                        pauseat=self.pauseat, pausefor=self.pausefor, parallelBoot=self.parallelBoot)
            xenrt.TEC().logverbose("created thread %d for host %s" % (i, useHost))
            return t
        queues = [clones[i::numthreads] for i in range(numthreads)]
        starterThreads = list (imap(createThread, count(), queues, queueHosts))

        xenrt.TEC().logverbose("created %d threads" % len(starterThreads))

        if awaitParam is not None:
            bw = BootWatcher(self, len(clones), bootwatcherLogfile, awaitParam, awaitKey)
            bw.start()
            xenrt.TEC().logverbose("started bootwatcher")

        self.vmsbooted = 0
        for t in starterThreads:
            t.start()
        xenrt.TEC().logverbose("started %d threads" % len(starterThreads))

        for t in starterThreads:
            t.join()
        xenrt.TEC().logverbose("finished joining %d threads" % len(starterThreads))

        if self.crippleNfs and (self.nfsServerHostObj is not None):
            xenrt.TEC().logverbose("About to cripple ethernet on nfsServerHostObj before unpausing VMs.")
            # This assumes all ports show up in ifconfig as ethN (where N is number).
            # NOTE: this is an appropriate amount of crippling on the
            # q machines but might not be on other hardware, depending on
            # number of ports and the speed of other potential bottlenecks.
            self.nfsServerHostObj.execdom0("""$(ifconfig | grep '^eth[[:digit:]]\+[[:space:]]' |  awk 'FNR > 1 {printf "%s"," && "}{printf "ethtool -s %s speed 100 duplex full advertise 0x008",$1}')""")

        # NOTE: this could be simpler.
        # In fact since the unpause command doesn't take a host param, there's no point
        # having multiple unpauser threads, therefore no point having a separate unpauser
        # thread at all. We could define an unpause method without needing a special class.
        if self.parallelBoot:
            unpauserThread = VMUnpauser(self, clones, starterLogfile)
            xenrt.TEC().logverbose("about to unpause the vms")
            unpauserThread.start()
            unpauserThread.join()
            xenrt.TEC().logverbose("unpaused all %s vms" % len(clones))

        if awaitParam is not None:
            xenrt.TEC().logverbose("waiting for bootwatcher to complete")
            bw.join()
            xenrt.TEC().logverbose("bootwatcher has completed")
            if bw.error:
                raise xenrt.XRTError("bootwatcher completed with error")

    def createMPSVMs(self, num, goldvm, registerForCleanup=False):
        if self.useLocalSRs:
            goldvmcopies = {}

            # TODO Copy the gold image into each SR
            for h in self.normalHosts:
                host = self.tec.gec.registry.hostGet(h)
                localsruuid = host.getLocalSR()
                xenrt.TEC().logverbose("Local SR on host %s is %s" % (host.getName(), localsruuid))

                name = "goldvm-on-host-%s" % host.getName()
                xenrt.TEC().logverbose("copying gold VM into SR %s with name %s" % (localsruuid, name))
                goldvmcopy = goldvm.copyVM(name=name, sruuid=localsruuid)
                goldvmcopies[host] = goldvmcopy

        def createClone(number):
            name = "scale%d" % number
        
            xenrt.TEC().logverbose("Doing VM %d (name '%s')" % (number, name))

            if self.useLocalSRs:
                # Clone the copy of the gold VMin the local SR on the nth host (modulo number of hosts)
                host = self.tec.gec.registry.hostGet(self.normalHosts[(number-1) % len(self.normalHosts)])
                xenrt.TEC().logverbose("corresponding host is %s" % host.getName())
                vmtoclone = goldvmcopies[host]
            else:
                vmtoclone = goldvm
            xenrt.TEC().logverbose("cloning VM %s" % vmtoclone)
                
            timer = Timer()
            timer.startMeasurement()

            clone = self.createVMforMPS(name, vmtoclone)

            timer.stopMeasurement()

            if registerForCleanup: self.uninstallOnCleanup(clone)
            xenrt.TEC().logverbose("finished preparing clone '%s'" % name)

            start = formattime(timer.starttime)
            end = formattime(timer.endtime)

            line = "%s %s %s" % (name, start, end)
            xenrt.TEC().logverbose("CLONED %s" % line)
            outputToResultsFile(createLogName("create"), line)
            return clone

        return map (createClone, range(1, num+1))

    def destroyVMs(self, clones):
        for clone in clones:
            xenrt.TEC().logverbose("Shutting down clone %s" % clone.getName())
            clone.shutdown(force=True)
            xenrt.TEC().logverbose("Destroying clone %s" % clone.getName())
            clone.lifecycleOperation("vm-destroy", force=True)

    def createHelperGuest(self, registerForCleanup=False):
        localSR = self.host.getLocalSR()
        guest = self.host.createGenericLinuxGuest(sr=localSR)
        self.installStuffInGuest(guest)
        if registerForCleanup: self.uninstallOnCleanup(guest)
        return guest

    def importGoldVM(self, sruuid, exportname, expectedvmname, network="NPRI bond of 0 1 2 3", registerForCleanup=False):
        self.installXapiForMPS()

        goldvm = self.importGoldDesktopVM(sruuid, exportname, expectedvmname, network)
        if registerForCleanup: self.uninstallOnCleanup(goldvm)

        return goldvm

    def measureSizeOfSR(self, sruuid):
        """Returns size in bytes as reported by du."""
        srpath = "/var/run/sr-mount/%s" % sruuid
        line = self.host.execdom0("du -b %s" % srpath).strip()
        xenrt.TEC().logverbose("line was [%s]" % line)
        return int(line.split('\t')[0])

    def executeNetAppCommand(self, cmd):
        password = "xenroot"
        addr = self.fastStoreIP
        user = "root"

        # Execute the command using sshpass to supply password to ssh. Turn off strict host-key checking otherwise sshpass hangs.
        xenrt.TEC().logverbose("Executing NetApp command '%s'" % cmd)
        return self.guest.execguest("sshpass -p%s ssh -o StrictHostKeyChecking=no %s@%s '%s'" % (password, user, addr, cmd)).strip()

    def startNetAppStatGather(self):
        cmds = """priv set -q diag
statit -b
nfsstat -z
nfs_hist -z
wafl_susp -z"""
        return self.executeNetAppCommand("; ".join(cmds.split("\n")))

    def finishNetAppStatGather(self):
        cmds = """priv set -q diag
echo "-----statit -e -r -n"
statit -e -r -n
echo "-----nfsstat -d"
nfsstat -d
echo "-----nfs_hist"
nfs_hist
echo "-----wafl_susp -w"
wafl_susp -w"""
        return self.executeNetAppCommand("; ".join(cmds.split("\n")))

    def getNrDom0vcpus(self, host):
        nr_dom0_vcpus = int(host.execcmd("cat /sys/devices/system/cpu/online").strip().split("-")[1])+1
        return nr_dom0_vcpus

    def changeNrDom0vcpus(self, host, nrdom0vcpus):
        if (not nrdom0vcpus) or (nrdom0vcpus == self.getNrDom0vcpus(host)):
            #nothing to do
            return
        out = host.execcmd("/opt/xensource/libexec/xen-cmdline --set-xen dom0_max_vcpus=%s" % (nrdom0vcpus,))
        self.log(None, "changeNrDom0vcpus: result=%s" % (out,))

        xenrt.TEC().logverbose("shutting down vms before reboot...")
        for vm in host.guests.values():
            if hasattr(self, "backendDetach"):
                self.backendDetach(vm)
            self.shutdown_vm(vm)

        host.reboot()
        if nrdom0vcpus != self.getNrDom0vcpus(host):
            raise Exception("nrdom0vcpus=%s != self.getNrDom0vcpus(%s)=%s" % (nrdom0vcpus, host, self.getNrDom0vcpus(host)))

    def isNameinGuests(self, guests, name):
        names = map(lambda g: g.getName(), guests)
        self.log(None, "name=%s, guests=%s, guest names=%s" % (name, guests, names))
        return name in names

    def start_vm(self, vm):
        self.log(None, "start_vm: vm %s state: %s" % (vm, vm.getState()))
        if vm.getState() == "DOWN": vm.start()

    def shutdown_vm(self, vm):
        self.log(None, "shutdown_vm: vm %s state: %s" % (vm, vm.getState()))
        if vm.getState() == "UP": vm.shutdown()

    def getSRofGuest(self, guest, userdevice):
        vbds = guest.host.minimalList("vbd-list", args="vm-uuid=%s userdevice=%s" % (guest.getUUID(), userdevice))
        self.log(None, "vbds=%s" % (vbds,))
        if len(vbds)<1:
            return None
        vdi_uuid = guest.host.genParamGet("vbd", vbds[0], "vdi-uuid")
        self.log(None, "vdi_uuid=%s" % (vdi_uuid,))
        sr_uuid  = guest.host.genParamGet("vdi", vdi_uuid, "sr-uuid")
        self.log(None, "sr_uuid=%s" % (sr_uuid,))
        return sr_uuid

    def changeDiskScheduler(self, host, sr_uuid, scheduler):
        if not scheduler:
            return
        self.log(None, "host=%s, sr_uuid=%s, scheduler=%s" % (host, sr_uuid, scheduler))
        sr_type = host.genParamGet("sr", sr_uuid, "type")
        self.log(None, "sr_type=%s" % (sr_type,))
        if sr_type not in ["nfs"]:
            #it's a block device
            devserial = host.genParamGet("sr", sr_uuid, "sm-config", "devserial")
            devpath = "/dev/disk/by-id/%s" % (devserial,)
            devpath_target = host.execdom0("readlink -f %s" % (devpath)).strip() #eg. <prefix>/sda
            device = devpath_target.split("/")[-1:][0] #eg. sda
            scheduler_path = "/sys/block/%s/queue/scheduler" % (device,)
            self.log(None, "devpath=%s, devpath_target=%s, device=%s, scheduler_path=%s" % (devpath, devpath_target, device, scheduler_path))
            current_scheduler = host.execdom0("cat %s" % (scheduler_path,)).strip()
            self.log(None, "current_scheduler at %s=%s" % (scheduler_path, current_scheduler))
            #update its scheduler
            host.execdom0("echo %s > %s" % (scheduler, scheduler_path))
            updated_scheduler = host.execdom0("cat %s" % (scheduler_path,)).strip()
            self.log(None, "updated_scheduler at %s=%s" % (scheduler_path, updated_scheduler))
            if ("[%s]" % (scheduler,)) not in updated_scheduler:
                raise Exception("scheduler=[%s] not in updated_scheduler=%s" % (scheduler, updated_scheduler))

    def loadModule(self, host, module):
        out = host.execdom0("modprobe %s" % (module,))
        self.log(None, "modprobe %s: %s" % (module, out))

class Cloner(xenrt.XRTThread):
    def __init__(self, tc, host, vm, numclones, logFile):
        xenrt.XRTThread.__init__(self)
        self.tc = tc
        self.host = host
        self.vm = vm
        self.numclones = numclones
        self.logFile = logFile
        xenrt.TEC().logverbose("Created cloner for %d VMs" % numclones)

    def run(self):
        cli = self.host.getCLIInstance()
        uuid = self.vm.getUUID()
        name = self.vm.getName()
        timeout=300 # seconds

        for i in range(1, self.numclones+1):
            xenrt.TEC().logverbose("about to do %dth vm-clone VM %s" % (i, name))
            timer = xenrt.util.Timer(float=True)

            newname = "clone%d" % i

            # Don't do the full XenRT clone because that adds extra overhead. It means that the VMs won't be accessible in the object model.
            args = []
            args.append("uuid=%s" % uuid)
            args.append("new-name-label=%s" % newname)
            timer.startMeasurement()
            cli.execute("vm-clone", string.join(args), timeout=timeout)
            timer.stopMeasurement()

            xenrt.TEC().logverbose("finished %dth vm-clone VM %s" % (i, name))

            line = "SUCCESS %s %s" % (newname, timer.measurements.pop())
            xenrt.TEC().logverbose(line)
            outputToResultsFile(self.logFile, line)

class Starter(xenrt.XRTThread):
    def __init__(self, tc, vms, logFile, onHost=None, pauseat=None, pausefor=1200, parallelBoot=False):
        xenrt.XRTThread.__init__(self)
        self.tc = tc
        self.vms = vms
        self.logFile = logFile
        self.onHost = onHost

        self.pauseat = pauseat # number of VMs booted before we pause (or None to never pause)
        self.pausefor = pausefor # seconds to pause thread for
        self.thisthreadhaspaused = False
        self.parallelBoot = parallelBoot

        xenrt.TEC().logverbose("Created starter for %d VMs (for host %s)" % (len(vms), onHost))

    def run(self):
        for vm in self.vms:
            name = vm.getName()
            cli = vm.getCLIInstance()

            # Pause if requested (Note: don't need to acquire lock to read vmsbooted)
            if (not self.pauseat is None) and self.tc.vmsbooted >= self.pauseat and not self.thisthreadhaspaused:
                xenrt.TEC().logverbose("thread for host %s is pausing for %d seconds..." % (self.onHost, self.pausefor))
                time.sleep(self.pausefor)
                xenrt.TEC().logverbose("thread for host %s has finished pausing" % self.onHost)
                self.thisthreadhaspaused = True

            xenrt.TEC().logverbose("about to vm-start VM %s%s on host %s" % (
                    name,
                    {True:" paused", False:""}[bool(self.parallelBoot)],
                    self.onHost))
            timer = Timer()

            #vm.lifecycleOperation("vm-start", timer=timer, specifyOn=False)

            timer.startMeasurement()
            if self.onHost is None:
                # Start it on any host
                cli.execute("vm-start", "vm=\"%s\" paused=%s" % (name, self.parallelBoot))
            else:
                # Start it on the specified host
                cli.execute("vm-start", "vm=\"%s\" on=\"%s\" paused=%s" % (name, self.onHost, self.parallelBoot))
            timer.stopMeasurement()

            self.tc.vmsbootedlock.acquire()
            self.tc.vmsbooted += 1
            self.tc.vmsbootedlock.release()

            xenrt.TEC().logverbose("finished vm-start VM %s on host %s" % (name, self.onHost))

            start = formattime(timer.starttime)
            end = formattime(timer.endtime)

            line = "SUCCESS %s %s %s" % (name, start, end)
            xenrt.TEC().logverbose(line)
            outputToResultsFile(self.logFile, line)


class VMUnpauser(xenrt.XRTThread):
    def __init__(self, tc, vms, logFile):
        xenrt.XRTThread.__init__(self)
        self.tc = tc
        self.vms = vms
        self.logFile = logFile

        xenrt.TEC().logverbose("Created unpauser for %d VMs" % (len(vms)))

    def run(self):
        cmd = " ".join(
            [("xe vm-unpause uuid=" + vm.getUUID() + " &") for vm in self.vms]
            ) + ' until [ -z "`jobs | head -c 1`" ] ; do  sleep 0.2; done'

        # CAUTION: getMaster has side-effects and is not idempotent.
        host = self.tc.getMaster() # Note: remove the "tc" if/when moving this to a function in the testcase.
        timer = Timer()
        timer.startMeasurement()
        output = host.execdom0(cmd)
        timer.stopMeasurement()
        xenrt.TEC().logverbose("Finished vm-unpause attempt.")
        xenrt.TEC().logverbose("vm-unpause output: %s" % output)

        start = formattime(timer.starttime)
        end = formattime(timer.endtime)
        xenrt.TEC().logverbose(
            "SUCCESS %s %s %s" % ("vm-unpause sequence", start, end))

class Timer(object):
    def __init__(self):
        self.starttime = None
        self.endtime = None

    def startMeasurement(self):
        xenrt.TEC().logverbose("Stopwatch started")
        self.starttime = timenow()

    def stopMeasurement(self):
        self.endtime = timenow()
        xenrt.TEC().logverbose("Stopwatch stopped")

def timenow():
    return time.gmtime(time.time ())

def formattime(t):
    iso8601 = "%Y%m%dT%H:%M:%SZ"
    return time.strftime(iso8601, t)

class BootWatcher(xenrt.XRTThread):
    def __init__(self, tc, numvms, logFile, awaitParam="other", awaitKey="feature-shutdown"):
        xenrt.XRTThread.__init__(self)
        xenrt.TEC().logverbose("constructing bootwatcher to await %d boots" % numvms)

        self.host = tc.host
        self.tc = tc
        self.logFile = logFile

        self.awaitParam = awaitParam
        self.awaitKey = awaitKey

        self.num_seen_boots = 0
        self.num_expected_boots = numvms

        self.interesting_vms = []
        self.vm_boot_times = {}
        self.vm_start_times = {}
        self.gm_seen_times = {}
        
        self.vm_cache = {}
        self.vgm_cache = {}
        self.vm_to_name = {}
        self.vgm_to_vm = {}

        self.complete = False
        self.error = False
        self.previousBootTime = None
        self.maxTimeToWait = 3600 # time to wait for a bit since seeing previous boot

    def vmOfMetrics(self, session, ref):
        if not(ref in self.vgm_to_vm.keys()):
            return None
        return self.vgm_to_vm[ref]

    def seenPossiblBboot(self, session, gm):
        if gm not in self.vgm_cache:
            return
        vgm = self.vgm_cache[gm]
    
        if self.awaitParam in vgm.keys():
            other = vgm[self.awaitParam]
            if self.awaitKey in other.keys():
                vm = self.vmOfMetrics(session, gm)
                if vm == None:
                    return
                vm_rec = self.vm_cache[vm]
    
                if vm_rec["power_state"] == "Running" and not(vm in self.vm_boot_times.keys()) and vm in self.vm_start_times.keys():
                    t = formattime(timenow())
                    self.vm_boot_times[vm] = t
                    name = vm_rec["name_label"]

                    line = "%s %s %s" % (name, self.vm_start_times[vm], t)
                    xenrt.TEC().logverbose("BOOTWATCHER %s" % line)
                    outputToResultsFile(self.logFile, line)

                    self.num_seen_boots = self.num_seen_boots + 1
                    if self.num_seen_boots == self.num_expected_boots:
                        self.complete = True
                    xenrt.TEC().logverbose("seen %d boots out of %d, hence complete=%s" % (self.num_seen_boots, self.num_expected_boots, self.complete))
                    self.previousBootTime = time.time()

    def processVm(self, session, vm, snapshot):
        xenrt.TEC().logverbose("bootwatcher processing VM %s" % vm)
        self.vm_cache[vm] = snapshot
        vgm = snapshot['guest_metrics']
        self.vgm_to_vm[vgm] = vm
    
        if vm not in self.vm_start_times.keys() and snapshot['power_state'] == "Running":
            self.vm_start_times[vm] = formattime(timenow())
            xenrt.TEC().logverbose("bootwatcher recording starttime of VM %s at %s" % (vm,self.vm_start_times[vm]))
    
        # Might have seen a boot now
        self.seenPossibleBoot(session, vgm)

    def seenPossibleBoot(self, session, vgm):
        raise xenrt.XRTError("Unimplemented")

    def processGuestMetrics(self, session, ref, snapshot):
        self.vgm_cache[ref] = snapshot
    
        # Might have seen a boot now
        self.seenPossibleBoot(session, ref)
    
    def processHostMetrics(self, session, ref, snapshot):
        if snapshot['live'] == False:
            raise xenrt.XRTError("Host with host_metrics ref %s has gone offline. This invalidates the entire test." % ref)

    def run(self):
        xenrt.TEC().logverbose("bootwatcher running")
        n = formattime(timenow())
        zero = "zero"
        self.vm_start_times[zero] = n
        self.vm_boot_times[zero] = n

        line = "%s %s %s" % (zero, n, n)
        xenrt.TEC().logverbose("BOOTWATCHER %s" % line)
        outputToResultsFile(self.logFile, line)

        session = self.host.getAPISession()

        try:
            self.watchEventsOnVm(session)
        finally:
            self.host.logoutAPISession(session)

    def watchEventsOnVm(self, session):
        # Register for events on all classes:
        def register():
            xenrt.TEC().logverbose("bootwatcher registering for events")
            session.xenapi.event.register(["VM","VM_guest_metrics","host_metrics"])
            all_vms = session.xenapi.VM.get_all_records()
            for vm in all_vms.keys():
                self.processVm(session, vm, all_vms[vm])
            all_gms = session.xenapi.VM_guest_metrics.get_all_records()
            for gm in all_gms.keys():
                self.processGuestMetrics(session, gm, all_gms[gm])

        register()
        while not self.complete:
            # Event loop
            try:
                xenrt.TEC().logverbose("bootwatcher calling event.next()")
                events = session.xenapi.event.next()
                for event in events:
                    xenrt.TEC().logverbose("bootwatcher received event op='%s' class='%s' ref='%s'" % (event['operation'], event['class'], event['ref']))
                    if event['operation'] == 'del':
                        continue
                    if event['class'] == 'vm' and event['operation'] == 'mod':
                        self.processVm(session, event['ref'], event['snapshot'])
                        continue
                    if event['class'] == 'vm_guest_metrics':
                        self.processGuestMetrics(session, event['ref'], event['snapshot'])
                        continue
                    if event['class'] == 'host_metrics':
                        self.processHostMetrics(session, event['ref'], event['snapshot'])
                        continue

            except XenAPI.Failure, e:
                xenrt.TEC().logverbose("** exception: e = [%s]" % e)
                xenrt.TEC().logverbose("** exception: e.details = [%s]" % e.details)
                if len(e.details) > 0 and e.details[0] == 'EVENTS_LOST':
                    xenrt.TEC().logverbose("** Caught EVENTS_LOST")
                    session.xenapi.event.unregister(["VM", "VM_guest_metrics"])
                    register()
                else:
                    xenrt.TEC().logverbose("** Non-EVENTS_LOST 'failure' exception: %s" % traceback.format_exc())
                    xenrt.TEC().logverbose("** re-registering anyway")
                    session.xenapi.event.unregister(["VM", "VM_guest_metrics"])
                    register()
            except:
                xenrt.TEC().logverbose("** fatal exception: %s" % traceback.format_exc())
                self.complete = True
                self.error = True

            # See how long we've waited for
            if (not self.previousBootTime is None) and (time.time() - self.previousBootTime > self.maxTimeToWait):
                xenrt.TEC().logverbose("** TIMEOUT waiting for next boot: only seen %d of %d boots" % (self.num_seen_boots, self.num_expected_boots))
                self.complete = True
                self.error = True
class RemoteRunner(object):
    """transfers and remoteRuns programs on a remote host.
    Use the mesh script and e.g. a Makefile to include your programs."""
    def __init__ (self):
        # Only piece of state.
        self.programsOnHosts = {}

    def remoteRun (self, host, (name,source), *arguments, **options):
        # Idea: Use the options of execdom0 instead.
        # Actually, they don't have `background'.  At least they don't
        # mean the same thing by it.
        bg = options.pop ("background", False)
        output = options.pop ("output", "/dev/null")

        self.transfer (host, name, source, "+x")
        cmd = "./" + " ".join([name] + map(str,arguments))
        if bg:
            cmd = "nohup %s > %s 2> /tmp/%s-log & echo $!" % (cmd, output, name)
        else:
            cmd = "%s 2> /tmp/%s-fg-log" % (cmd, name)
        return host.execdom0 (cmd, **options).strip()

    def transfer (self, host, name, source, permissions=None):
        self.programsOnHosts.setdefault (host, set())
        if name in self.programsOnHosts[host]:
            xenrt.TEC().logverbose("vlan_scalability: transfer: %s already on host %s" % (name, host))
            # Nothing to do.
            return

        import tempfile
        # using a tempfile is a bit silly,
        # but that's how the sftpClient interface works.
        f = tempfile.NamedTemporaryFile (suffix = "-"+name)
        client = host.sftpClient ()
        try:
            f.write (source)
            f.flush ()
            xenrt.TEC().logverbose("vlan_scalability: %s .sftpClient" % host)
            client.copyTo (f.name, name)
        finally:
            client.close ()
            f.close ()
        if permissions:
            host.execdom0 ("chmod %s %s" % (permissions, name))

        self.programsOnHosts [host].add(name)
