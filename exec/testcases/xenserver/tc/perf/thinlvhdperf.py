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
from xenrt.lazylog import step, log

class ThinLVHDPerfBase(xenrt.TestCase):

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid=tcid)

        self.vms = 0
        self.srtype = None
        self.distro = None
        self.thinprov = None

    def parseArgs(self, arglist):
        """Parse the sequence arguments"""

        self.args = self.parseArgsKeyValue(arglist)

        self.vms = int(self.args.get("numvms", "20"))
        self.distro = str(self.args.get("distro", "debian60"))
        self.arch = str(self.args.get("arch", "x86-64"))

        self.srtype = str(self.args.get("srtype", "lvmoiscsi"))
        self.thinprov = str(self.args.get("thinprov", False))

        self.goldenVMName = str(self.args.get("goldvm", "vm00"))

    def parseEnvArgs(self):
        """Parse the enviroment variables"""

        # Environment arguments supplied from the CLI using -D option takes the preference.
        self.vms = int (xenrt.TEC().lookup("VMCOUNT", self.vms))
        self.srtype = xenrt.TEC().lookup("SRTYPE", self.srtype)
        self.distro = xenrt.TEC().lookup("DISTRO", self.distro)
        self.thinprov = xenrt.TEC().lookup("THINPROV", self.thinprov)

    def createSR(self):
        """Create a SR with given parameters"""

        if self.srtype=="lvmoiscsi":
            sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host, "lvmoiscsi", thin_prov=self.thinprov)
            sr.create(subtype="lvm")
        elif self.srtype=="lvmohba":
            fcLun = self.host.lookup("SR_FCHBA", "LUN0")
            fcSRScsiid = self.host.lookup(["FC", fcLun, "SCSIID"], None)
            sr = xenrt.lib.xenserver.FCStorageRepository(self.host,  "lvmohba", thin_prov=self.thinprov)
            sr.create(fcSRScsiid)
        elif self.srtype=="nfs":
            sr = xenrt.lib.xenserver.NFSStorageRepository(self.host, "nfssr")
            sr.create()
        else:
            raise xenrt.XRTError("SR Type: %s not defined" % self.srtype)
        return sr

    def prepare(self, arglist=None):

        # Parse the sequence arguments
        self.parseArgs(arglist)

        # Obtain the env arguments, if any to take precedence.
        self.parseEnvArgs()

        # Obtain the pool object to retrieve its hosts.
        self.pool = self.getDefaultPool()
        if self.pool is None:
            self.host = self.getDefaultHost()
        else:
            self.host = self.pool.master

class TCIOLatency(ThinLVHDPerfBase):
    """Test case to measure the IO latency on a storage repository"""

    def __init__(self):
        ThinLVHDPerfBase.__init__(self, "TCIOLatency")

        self.clones = []
        self.edisk = ( None, 2, False )  # definition of an extra disk of 2GiB.
        self.diskprefix = None  # can be "hd" for KVM or "xvd" for Xen

    def parseArgs(self, arglist):
        """Parse the sequence arguments"""

        # Parse generic arguments
        ThinLVHDPerfBase.parseArgs(self, arglist)

        self.edisks = int(self.args.get("edisks", "1"))

        self.bufsize = int(self.args.get("bufsize", "512"))
        self.groupsize = int(self.args.get("groupsize", "1"))

    def parseEnvArgs(self):
        """Parse the enviroment variables"""

        # Parse environment variables.
        ThinLVHDPerfBase.parseEnvArgs(self)

        # Add more env vars, if required.

    def prepare(self, arglist=None):

        # Call the base prepare.
        ThinLVHDPerfBase.prepare(self, arglist)

        # Create the SR.
        sr = self.createSR()

        # Set the SR as pool default SR.
        if self.pool:
            self.pool.setPoolParam("default-SR", sr.uuid)
        else:
            pooluuid = self.host.minimalList("pool-list")[0]
            self.host.genParamSet("pool", pooluuid, "default-SR", sr.uuid)

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
                            guestname=self.goldenVMName,
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
        args.append("> /root/output.log 2>&1") # display options.
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
        errors = []
        try:
            xenrt.pfarm([xenrt.PTask(self.collectMetrics, clone) for clone in self.clones])
        except Exception, e:
            errors.append(str(e))

        if len(errors) > 1:
            xenrt.TEC().logverbose("Parallel collection of iolatency metrics failed with error messages %s" % errors)
            raise xenrt.XRTFailure("Failed to collect iolatency metrics parallely.")

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


class TCThinVDIscalability(_TimedTestCase):
    """ Measure the sequential VM clone and destory time"""

    DEFAULTNUMVMS = 100
    DEFAULTSRTYPE = "lvmoiscsi"
    DEFAULTDISTRO = "debian70"
    DEFAULTSROPTIONS = "thin"
    DEFAULTOUTPUTFILE = "thinsrscaletiming.log"

    def __init__(self, tcid=None):
        super(TCThinVDIscalability,self).__init__(self, tcid)

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
            sr.create(fcSRScsiid, physical_size=size)
        elif self.srtype == "nfs":
            sr = NFSStorageRepository(self.host, "nfssr")
            sr.create()
        elif self.srtype == "lvm":
            sr = host.getSRs(type="lvm")[0]
        else:
            raise xenrt.XRTError("We do not have provision in the test to create %s  SR." % self.srtype)

        return sr

    def cloneVMSerial(self):
        count = 1
        while count <= self.numvms:
            try:
                log("Cloning the guest ...")
                self.addTiming("TIME_VM_CLONE_START_%s:%.6f" % (self.distro, xenrt.util.timenow(float=True)))
                guest = self.guest.cloneVM()
                self.addTiming("TIME_VM_CLONE_COMPLETE_%s:%.6f" % (self.distro, xenrt.util.timenow(float=True)))
                self.cloneGuests.append(guest)
            except Exception as e:
                xenrt.TEC().warning("Cloning the VM '%s' of uuid '%s' failed with exception '%s': " % (self.guest, self.guest.getUUID(), str(e)))
            count = count + 1

    def destoryVMSerial(self):
        try :
            for guest in self.cloneGuests:
                log("Destorying the guest ...")
                self.addTiming("TIME_VM_DESTROY_START_%s:%.3f" % (self.distro, xenrt.util.timenow(float=True)))
                guest.uninstall()
                self.addTiming("TIME_VM_DESTROY_COMPLETE_%s:%.3f" % (self.distro, xenrt.util.timenow(float=True)))
        except Exception as e:
            xenrt.TEC().warning("Destroying the VM '%s' of uuid '%s' failed with exception '%s': " % (self.guest, self.guest.getUUID(), str(e)))

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

