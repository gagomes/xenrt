# Test harness for Xen and the XenServer product family
#
# Thin provisioning performance tests 
#
# https://info.citrite.net/display/perf/Proposed+performance+requirements+for+thin+provisioning
#
# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt
from xenrt.lazylog import step, log, warning
from testcases.xenserver.tc.perf.libperf import PerfTestCase

class ThinLVHDPerfBase(PerfTestCase):

    # "var name" : [<default value>(mandatory), <name in arg list>, <name in TEC>]
    ENV_VARS = {"vms": [20, "numvms", "VMCOUNT"],
            "distro": ["debian60", "distro", "DISTRO"],
            "arch": ["x86-64", "arch", "ARCH"],
            "srtype": ["lvmoiscsi", "srtype", "SRTYPE"],
            "srsize": ["100", "srsize", "SRSIZE"],
            "thinprov": [False, "thinprov", "THINPROV"],
            "goldvm": ["vm00", "goldvm"],
    }

    def __setValue(self, varname, default, argname=None, tecname=None):
        """A utility function to initialise memeber variables."""

        # Setting with default value
        var = default

        # Reading from sequence arguments
        if argname:
            var = self.args.get(argname, var)

        # Reading from TEC (including command line arguments)
        if tecname:
            var = xenrt.TEC().lookup(tecname, var)

        # Check type and cast to right type
        if type(default) == bool:
            if type(var) != bool:
                if var.strip().lower() in ["yes", "true"]:
                    var = True
                else:
                    var = False
        elif type(default) == int:
            var = int(var)

        # Assign value to local attribute
        setattr(self, varname, var)
        
    def setTestEnv(self, printOut=True):
        """A utility function to read env data."""

        for var in self.ENV_VARS:
            self.__setValue(var, *self.ENV_VARS[var])

        if printOut:
            log("=======================")
            for var in self.ENV_VARS:
                log("%s: %s" % (var, getattr(self, var)))
            log("=======================")

    def createSR(self, srsize=100, default=False):
        """Create a SR with given parameters"""

        if self.srtype=="lvmoiscsi":
            size = srsize * xenrt.KILO # converting size to MiB
            lun = xenrt.ISCSITemporaryLun(size)
            sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host, "lvmoiscsi", thin_prov=self.thinprov)
            sr.create(lun, subtype="lvm", physical_size=size, findSCSIID=True, noiqnset=True)
        elif self.srtype=="lvmohba":
            fcLun = self.host.lookup("SR_FCHBA", "LUN0")
            fcSRScsiid = self.host.lookup(["FC", fcLun, "SCSIID"], None)
            sr = xenrt.lib.xenserver.FCStorageRepository(self.host,  "lvmohba", thin_prov=self.thinprov)
            sr.create(fcSRScsiid)
        elif self.srtype=="nfs":
            sr = xenrt.lib.xenserver.NFSStorageRepository(self.host, "nfssr")
            sr.create()
        elif self.srttype =="lvmofcoe":
            fcLun = self.host.lookup("SR_FCHBA", "LUN0")
            fcSRScsiid = self.host.lookup(["FC", fcLun, "SCSIID"], None)
            sr= xenrt.lib.xenserver.FCOEStorageRepository(self.host, "FCOESR")
            sr.create(fcSRScsiid)
        else:
            raise xenrt.XRTError("SR Type: %s not supported in the test" % self.srtype)

        if default:
            sr.setDefault()

        self.createdSRs = []

        return sr

    def prepare(self, arglist=None):

        self.args = self.parseArgsKeyValue(arglist)
        self.setTestEnv()

        # Obtain the pool object to retrieve its hosts.
        self.pool = self.getDefaultPool()
        if not self.pool:
            self.host = self.getDefaultHost()
        else:
            self.host = self.pool.master

    def postRun(self, arglist=None):
        if hasattr(self, "createdSRs"):
            for sr in self.createdSRs:
                sr.remove()


class TCIOLatency(ThinLVHDPerfBase):
    """Test case to measure the IO latency on a storage repository"""

    ENV_VARS = {"vms": [20, "numvms", "VMCOUNT"],
            "distro": ["debian60", "distro", "DISTRO"],
            "arch": ["x86-64", "arch", "ARCH"],
            "srsize": ["100", "srsize", "SRSIZE"],
            "srtype": ["lvmoiscsi", "srtype", "SRTYPE"],
            "thinprov": [False, "thinprov", "THINPROV"],
            "goldvm": ["vm00", "goldvm"],
            "edisks": [1, "edisks"],
            "bufsize": [512, "bufsize"],
            "groupsize": [1, "groupsize"],
    }

    def __init__(self, tcid=None):
        super(TCIOLatency, self).__init__("TCIOLatency")

        self.clones = []
        self.edisk = ( None, 2, False )  # definition of an extra disk of 2GiB.
        self.diskprefix = None  # can be "hd" for KVM or "xvd" for Xen

    def prepare(self, arglist=[]):

        # Call the base prepare.
        super(TCIOLatency, self).prepare(arglist)

        # Create the SR.
        sr = self.createSR(default=True)

        # Populate the number of extra disks.
        extraDisks = []
        for i in range(1, self.edisks+1):
            extraDisks.append(self.edisk)

        # Check if there any golden image.
        existingGuests = self.host.listGuests()
        if existingGuests:
            vm = map(lambda x:self.host.getGuest(x), existingGuests)
            self.goldenVM = vm[0] # if so, pick the first one available.
        else: # Install a one with name 'vm00' with the specified extra disks.
            xenrt.TEC().progress("Installing VM zero")
            self.goldenVM = xenrt.productLib(host=self.host).guest.createVM(\
                            host=self.host,
                            guestname=self.goldvm,
                            distro=self.distro,
                            arch=self.arch,
                            vifs=xenrt.productLib(host=self.host).Guest.DEFAULT,
                            disks=extraDisks)

        self.diskprefix = self.goldenVM.vendorInstallDevicePrefix()

    def collectMetrics(self, guest):
        """Collect iolatency metrics for a given guest"""

        # This test makes use of the disk profiler tool from performance team
        # to gather the read/write latency of the given block device.
        # The tool opens the block device in O_DIRECT mode.

        args = []
        args.append("-w") # read(-r)/write(-w) the entire disk.
        args.append("-d /dev/%sb" % (self.diskprefix)) # block device to read/write.
        args.append("-m") # print in milliseconds.
        args.append("-vv") # print verbos.
        args.append("-b %d" % (self.bufsize)) # read/write every buffer of size.
        args.append("-g %d" % (self.groupsize)) # group the number of read/write operations.
        args.append("-o %s.log" % (guest.getName())) # place the perf metrics on the guest.
        #args.append("> /root/output.log 2>&1") # display options.
        results = guest.execguest("/root/perf-latency/diskprofiler/dprofiler %s" %
                                                        (" ".join(args)), timeout=7200)

        # write the metrics to a data file.
        f = open("%s/iolatency-%s.log" % (xenrt.TEC().getLogdir(), guest.getName()), "w")
        f.write("------------------------------------------\n")
        f.write("   Buffer write      Time(in millisecs)   \n")
        f.write("------------------------------------------\n")
        for line in results.splitlines():
            f.write(line + "\n")
        f.write("------------------------------------------\n")
        f.close()

    def cloneStart(self, clone):
        """Start the cloned guest"""

        clone.tailored = True
        clone.start()

    def run(self, arglist=None):

        # Install disk profiler tool to golden image 'vm00'
        if self.goldenVM.execcmd('test -e /root/perf-latency/diskprofiler/dprofiler', retval='code') != 0:
            self.goldenVM.execguest("cd /root && wget '%s/perf-latency.tgz'" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")))
            self.goldenVM.execguest("cd /root && tar -xzf perf-latency.tgz")
            self.goldenVM.execguest("cd /root/perf-latency/diskprofiler && gcc dprofiler.c -o dprofiler && chmod +x dprofiler")

        # Check, if installed correctly.
        if self.goldenVM.execcmd('test -e /root/perf-latency/diskprofiler/dprofiler', retval='code') != 0:
            raise xenrt.XRTError("Disk profiler tool is not installed correctly.")

        # Shutdown the golden image before proceeding to generate multiple copies.
        self.goldenVM.shutdown()

        # Install more VMs so that we can measure more metrics on different guests.
        errors = []
        for i in range(1, self.vms+1):
            xenrt.TEC().progress("Installing VM %d" % i)
            try:
                # Copies original VM (much quicker than installing another one)
                vmName = "vm%02d" % i
                self.clones.append(self.goldenVM.copyVM(vmName))
            except Exception, e:
                errors.append(vmName + ":" + str(e))

        if len(errors) > 1:
            raise xenrt.XRTFailure("Cloning one or many VMs failed with error messages %s" % errors)

        errors = []
        for clone in self.clones:
            xenrt.TEC().progress("Starting VM %s" % clone.getName())
            try:
                clone.start()
            except Exception, e:
                errors.append(clone.getName() + ":" + str(e))

        if len(errors) > 1:
            xenrt.TEC().logverbose("One or many guests failed to start with error messages %s" % errors)
            raise xenrt.XRTFailure("One or many guests failed to start.")

        # Now collect iolatency metrics for every cloned guests parallely.
        results = xenrt.pfarm([xenrt.PTask(self.collectMetrics, clone) for clone in self.clones], exception=False)
        log("Threads returned: %s" % results)

        exceptions = 0
        for result in results:
            if result:
                exceptions += 1
                warning("Found exception: %s" % result)

        if exceptions:
            raise xenrt.XRTFailure("Failed to run %d / %d io latency tests." % (exceptions, len(results)))

    def postRun(self, arglist=None):
        # Removing all cloned VMs after the test run.
        errors = []
        for clone in self.clones:
            xenrt.TEC().progress("Uninstalling VM %s" % clone.getName())
            try:
                clone.uninstall()
            except Exception, e:
                errors.append(clone.getName() + ":" + str(e))

        if len(errors) > 1:
            xenrt.TEC().logverbose("One or many guests failed to uninstall with error messages %s" % errors)
            raise xenrt.XRTFailure("One or many guests failed to unisntall.")

        super(TCIOLatency, self).postRun(arglist)


class TCVDIScalability(ThinLVHDPerfBase):
    """ Measure the sequential VM clone and destroy time"""

    DEFAULTOUTPUTFILE = "thinsrscaletiming.log"
    SCRIPT_CLONE_PATH = "/tmp/vmclone.sh"
    SCRIPT_UNINSTALL_PATH = "/tmp/vmuninstall.sh"
    OUTPUT_PATH = "/tmp/result.txt"

    ENV_VARS = {"numvms": [100, "numvms", "VMCOUNT"],
            "distro": ["debian70", "distro", "DISTRO"],
            "srtype": ["lvmoiscsi", "srtype", "SRTYPE"],
            "srsize": ["100", "srsize", "SRSIZE"],
            "thinprov": [False, "thinprov", "THINPROV"],
            "outputfile": ["result_vdiscalability.txt", "outputfile", "OUTPUTFILE"],
    }

    def __init__(self):
        super(TCVDIScalability, self).__init__("TCVDIScalability")
        self.logs = []

    def createLogFile(self):
        filename = "%s/%s" % (xenrt.TEC().getLogdir(), self.outputfile)
        f = file(filename, "w")
        f.write("\n".join(self.logs))
        f.close()

    def __noneXSCloneVMSerial(self):
        log("Cloning the %d guests" % self.numvms)
        for i in xrange(self.numvms):
            try:
                before = xenrt.util.timenow(float=True)
                guest = self.guest.cloneVM()
                after = xenrt.util.timenow(float=True)
                self.cloneGuests.append(guest)
                message = "Cloned %s" % guest.getUUID()
            except Exception as e:
                after = xenrt.util.timenow(float=True)
                message = "Cloning the VM '%s' of uuid '%s' failed with exception '%s': " % (self.guest, self.guest.getUUID(), str(e))
            finally:
                logline = "%.6f %s" % ((after - before), message) 
                self.logs.append(logline)

    def __noneXSUninstallVMSerial(self):
        log("Uninstalling %d VMs." % len(self.cloneGuests))
        for guest in self.cloneGuests:
            try:
                before = xenrt.util.timenow(float=True)
                guest = self.guest.uninstall()
                after = xenrt.util.timenow(float=True)
                message = "Uninstalled %s" % guest.getUUID()
            except Exception as e:
                after = xenrt.util.timenow(float=True)
                message = "Uninstalling '%s' of uuid '%s' failed with exception '%s': " % (guest, guest.getUUID(), str(e))
            finally:
                logline = "%.6f %s" % ((after - before), message) 
                self.logs.append(logline)

    def __rawXSCloneVMSerial(self):
        # Avoiding using lib code to overhead of xenrt/python
        log("Cloning the %d guests" % self.numvms)
        self.logs.append("Start cloning %d VMs" % self.numvms)
        for i in xrange(self.numvms):
            result = self.host.execdom0(self.SCRIPT_CLONE_PATH, retval="code")
            output = self.host.execdom0("cat %s" % self.OUTPUT_PATH).splitlines()
            if result:
                logline = "%s Failed cloning with error: %s" % (output[-1], " ".join(output[:-1]))
            else:
                logline = "%s Cloned: %s" % (output[-1], output[0])
                self.cloneGuests.append(output[0])
            self.logs.append(logline)

    def __rawXSUninstallVMSerial(self):
        log("Uninstalling %d VMs." % len(self.cloneGuests))
        self.logs.append("Uninstalling %d VMs" % len(self.cloneGuests))
        for guest in self.cloneGuests:
            result = self.host.execdom0("%s %s" % (self.SCRIPT_UNINSTALL_PATH, guest), retval="code")
            output = self.host.execdom0("cat %s" % self.OUTPUT_PATH).splitlines()
            if result:
                logline = "%s Failed uninstalling %s with error: %s" % (output[-1], guest, " ".join(output[:-1]))
            else:
                logline = "%s Cloned: %s" % (output[-1], output[0])
            self.logs.append(logline)

    def prepare(self, arglist=None):
        super(TCVDIScalability, self).prepare(arglist)
        self.host = self.getDefaultHost()
        if isinstance(self.host, xenrt.lib.xenserver.Host):
            self.cloneVMSerial = self.__rawXSCloneVMSerial
            self.destroyVMSerial = self.__rawXSUninstallVMSerial
        else:
            self.cloneVMSerial = self.__noneXSCloneVMSerial
            self.destroyVMSerial = self.__noneXSUninstallSerial
        self.cloneGuests = []

    def run(self, arglist=None):
        step("Trying to create SR of type %s" % (self.srtype))
        sr = self.createSR()

        step("Installing the guest %s on the SR %s" % (self.distro, self.srtype))
        self.guest = self.host.createBasicGuest(distro=self.distro, sr=sr.uuid)
        self.uninstallOnCleanup(self.guest)
        self.guest.preCloneTailor()
        self.guest.setState("DOWN")

        step("Preparing scripts and output")
        self.output = []
        if isinstance(self.host, xenrt.lib.xenserver.Host):
            self.host.execdom0("echo 'TIMEFORMAT=%%6R; (time xe vm-clone uuid=%s new-name-label=clone) > %s 2>&1' > %s" %
                    (self.guest.getUUID(), self.OUTPUT_PATH, self.SCRIPT_CLONE_PATH))
            self.host.execdom0("chmod +x %s" % self.SCRIPT_CLONE_PATH)
            self.host.execdom0("echo 'TIMEFORMAT=%%6R; (time xe vm-uninstall uuid=$1 --force) > %s 2>&1' > %s" %
                    (self.OUTPUT_PATH, self.SCRIPT_UNINSTALL_PATH))
            self.host.execdom0("chmod +x %s" % self.SCRIPT_UNINSTALL_PATH)

        step("Start cloning the guests sequentially...")
        self.cloneVMSerial()

        step("Start Uninstalling the guests sequentially...")
        self.destroyVMSerial()

        self.createLogFile()

