# Test harness for Xen and the XenServer product family
#
# Thin provisioning performance tests 
#
# https://info.citrite.net/display/perf/Proposed+performance+requirements+for+thin+provisioning
#
# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt, string, threading, time
from xenrt.lib.xenserver import ISCSIStorageRepository, NFSStorageRepository
from testcases.xenserver.tc.scalability import _TimedTestCase
from xenrt.lazylog import step, log, warning

class ThinLVHDPerfBase(xenrt.TestCase):

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

    def setDefaultSR(self, sr):
        """Set given SR to default"""

        host = self.getDefaultHost()
        pool = host.minimalList("pool-list")[0]
        host.genParamSet("pool", pool, "default-SR", sr.uuid)
        host.genParamSet("pool", pool, "crash-dump-SR", sr.uuid)
        host.genParamSet("pool", pool, "suspend-image-SR", sr.uuid)


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
            raise xenrt.XRTError("SR Type: %s not defined" % self.srtype)

        if default:
            self.setDefaultSR(sr)

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

    def __init__(self):
        ThinLVHDPerfBase.__init__(self, "TCIOLatency")

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
                                                        (string.join(args)), timeout=7200)

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

        # Copy disk profiler tool to golden image 'vm00'
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
            xenrt.TEC().logverbose("Cloning one or many VMs failed with error messages %s" % errors)
            raise xenrt.XRTFailure("Cloning one or many VMs failed.")

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


class TCVDIscalability(_TimedTestCase):
    """ Measure the sequential VM clone and destory time"""

    DEFAULTNUMVMS = 100
    DEFAULTSRTYPE = "lvmoiscsi"
    DEFAULTDISTRO = "debian70"
    DEFAULTSROPTIONS = "thin"
    DEFAULTOUTPUTFILE = "thinsrscaletiming.log"

    def createSR(self, host=None, sroptions="thin"):
        if not host:
            host = self.getDefaultHost()
        thinProv = True if sroptions is "thin" else False
        if self.srtype=="lvmoiscsi":
            sr = ISCSIStorageRepository(self.host, name="lvoiscsi", thin_prov=thinProv)
            sr.create(subtype="lvm", findSCSIID=True, noiqnset=True)
        elif self.srtype=="lvmohba":
            fcLun = self.host.lookup("SR_FCHBA", "LUN0")
            fcSRScsiid = self.host.lookup(["FC", fcLun, "SCSIID"], None)
            sr = xenrt.lib.xenserver.FCStorageRepository(self.host, "lvmohba", thin_prov=thinProv) 
            sr.create(fcSRScsiid)
        elif self.srtype == "nfs":
            sr = NFSStorageRepository(self.host, "nfssr")
            sr.create()
        elif self.srtype == "lvm":
            sr = host.getSRs(type="lvm")[0]
        elif self.srtype=="lvmofcoe":
           fcLun = self.host.lookup("SR_FCHBA", "LUN0")
           fcSRScsiid = self.host.lookup(["FC", fcLun, "SCSIID"], None)
           sr= xenrt.lib.xenserver.FCOEStorageRepository(self.host, "FCOESR")
           sr.create(fcSRScsiid)
        else:
            raise xenrt.XRTError("We do not have provision in the test to create %s  SR." % self.srtype)

        return sr

    def cloneVMSerial(self):
        count = 0
        while count < self.numvms:
            try:
                log("Cloning the guest ...")
                self.addTiming("TIME_VM_CLONE_START_%s:%.6f" % (self.distro, xenrt.util.timenow(float=True)))
                guest = self.cloneVM(self.guest)
                self.addTiming("TIME_VM_CLONE_COMPLETE_%s:%.6f" % (self.distro, xenrt.util.timenow(float=True)))
                self.cloneGuests.append(guest)
            except Exception as e:
                xenrt.TEC().warning("Cloning the VM '%s' of uuid '%s' failed with exception '%s': " % (self.guest, self.guest.getUUID(), str(e)))
                self.addTiming("TIME_VM_CLONE_COMPLETE_%s:%.6f (FAILED)" % (self.distro, xenrt.util.timenow(float=True)))
            count = count + 1

    def destoryVMSerial(self):
        xenrt.TEC().logverbose("Uninstalling %d VMs." % len(self.cloneGuests))
        try :
            for guest in self.cloneGuests:
                log("Destorying the guest ...")
                self.addTiming("TIME_VM_DESTROY_START_%s:%.3f" % (self.distro, xenrt.util.timenow(float=True)))
                self.uninstallVM(guest)
                self.addTiming("TIME_VM_DESTROY_COMPLETE_%s:%.3f" % (self.distro, xenrt.util.timenow(float=True)))
        except Exception as e:
            xenrt.TEC().warning("Destroying the VM '%s' of uuid '%s' failed with exception '%s': " % (self.guest, self.guest.getUUID(), str(e)))

    def __rawXSCloneVM(self, guest):
        """Clone VM with raw commands.

        @param guest: guest object to clone.

        @return: output from cli execution. "" if it succeeds.
        """
        # minimize xenrt lib call to avoid impact from xenrt/python delay
        return self.cli.execute("vm-clone", args="uuid=%s new-name-label=clone" % self.guest.getUUID())

    def __rawXSUninstallVM(self, guest):
        """Destroy VM with raw commands.
        
        @param guest: string of guest uuid to uninstall

        @return: output from cli execution. "" if it succeeds.
        """
        # minimize xenrt lib call to avoid impact from xenrt/python delay
        return self.cli.execute("vm-destroy", args="uuid=%s" % guest)

    def __noneXSCloneVM(self, guest):
        return guest.cloneVM()

    def __noneXSIninstallVM(self, guest):
        return guest.uninstall()

    def configParams(self):
        self.numvms = int (xenrt.TEC().lookup("NUMVMS", self.numvms))
        self.srtype = xenrt.TEC().lookup("SRTYPE", self.srtype)
        self.distro = xenrt.TEC().lookup("DISTRO", self.distro)
        self.sroptions = bool(xenrt.TEC().lookup("SROPTIONS", self.sroptions))
        self.outputfile = xenrt.TEC().lookup("OUTPUTFILE", self.outputfile)
        self.cloneGuests = []

    def prepare(self, arglist=None):
        args  = self.parseArgsKeyValue(arglist)
        self.host = self.getDefaultHost()
        self.numvms = int(args.get("numvms", self.DEFAULTNUMVMS))
        self.srtype = args.get("srtype", self.DEFAULTSRTYPE)
        self.distro = args.get("distro", self.DEFAULTDISTRO)
        self.sroptions = args.get("sroptions", self.DEFAULTSROPTIONS)
        self.outputfile =  args.get("outputfile", self.DEFAULTOUTPUTFILE)
        self.configParams()
        if isinstance(self.host, xenrt.lib.xenserver.Host):
            self.cloneVM = self.__rawXSCloneVM
            self.uninstallVM = self.__rawXSUninstallVM
            self.cli = self.host.getCLIInstance()
        else:
            self.cloneVM = self.__noneXSCloneVM
            self.uninstallVM = self.__noneUninstallVM

    def run(self, arglist=None):
        step("Trying to create SR of type %s" % (self.srtype))
        sr = self.createSR()
        step("Installing the guest %s on the SR %s" % (self.distro, self.srtype))
        self.guest = self.host.createBasicGuest(distro=self.distro, sr=sr.uuid)
        self.uninstallOnCleanup(self.guest)
        self.guest.preCloneTailor()
        self.guest.setState("DOWN")
        step("Start cloning the guests sequentially...")
        self.cloneVMSerial()
        step("Start Destroying the guests sequentially...")
        self.destoryVMSerial()
        self.preLogs(self.outputfile)

