import xenrt, libperf, string, os, os.path
import libsynexec

def toBool(val):
    if val.lower() in ("false", "no"):
        return False
    return True

class TCDiskConcurrent2(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCDiskConcurrent2")

        # VM Data
        self.vm = []
        self.sr_to_diskname = {}
        self.host = self.getDefaultHost()

    def parseArgs(self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs(self, arglist)

        # Parse other arguments
        # Specify the disks to use as a list of partitions to use in the form:
        # /dev/disk/by-id/X,/dev/disk/by-id/Y,...
        # Use "default" to use the default SR (which will *not* be destroyed)
        self.devices = libperf.getArgument(arglist, "devices", str, "default").strip().split(",")
        self.blocksizes = libperf.getArgument(arglist, "blocksizes",  str,
                                              "512,1024,2048,4096,8192,16384,32768,65536,131072,262144,524288,1048576,2097152,4194304")
        self.blocksizes = map(int, self.blocksizes.strip().split(","))
        self.vms_per_sr = libperf.getArgument(arglist, "vms_per_sr", int, 1)
        self.vbds_per_vm = libperf.getArgument(arglist, "vbds_per_vm", int, 1)
        self.vcpus_per_vm = libperf.getArgument(arglist, "vcpus_per_vm", int, None)

        # A number in MB; e.g. 1024
        self.vm_ram = libperf.getArgument(arglist, "vm_ram", int, None)

        self.duration = libperf.getArgument(arglist, "duration", int, 60)
        self.vdi_size = libperf.getArgument(arglist, "vdi_size", str, "5GiB")
        self.distro = libperf.getArgument(arglist, "distro", str, "debian60")
        self.arch = libperf.getArgument(arglist, "arch", str, "x86-32")
        self.dom0vcpus  = libperf.getArgument(arglist, "dom0vcpus", int, None)
        self.write_iterations = libperf.getArgument(arglist, "write_iterations", int, 1)
        self.read_iterations = libperf.getArgument(arglist, "read_iterations", int, 1)
        self.zeros = libperf.getArgument(arglist, "zeros", bool, False)
        self.prepopulate = libperf.getArgument(arglist, "prepopulate", toBool, True)

        # Disk schedulers are specified in the form deviceA=X,deviceB=Y,...
        # To specify the scheduler for the default SR, use default=Z
        schedulers = libperf.getArgument(arglist, "disk_schedulers", str, "").strip()
        self.disk_schedulers = {}
        if schedulers != "":
            for pair in schedulers.split(","):
                pair = pair.split("=")
                self.disk_schedulers[pair[0]] = pair[1]

        # Choice of VDI; default, xen-vhd, xen-raw
        self.vdi_type = libperf.getArgument(arglist, "vdi_type", str, "default")

        # Choice of backend; default, xen-blkback, xen-tapdisk2 or xen-tapdisk3
        self.backend = libperf.getArgument(arglist, "backend", str, "default")
        if self.backend == "xen-blkback":
            vdi_type = libperf.getArgument(arglist, "vdi_type", str, None)
            if vdi_type and vdi_type != "xen-raw":
                raise ValueError("Cannot use blkback with VHD vdi_type")

        if self.vdi_type == "xen-raw" or self.vdi_type == "xen-blkback":
            self.sm_config = "type=raw"
        else:
            self.sm_config = None

        # Fetch JobID
        self.jobid = xenrt.TEC().gec.config.lookup("JOBID", None)
        xenrt.TEC().progress("My JOBID is %s" % self.jobid)
        self.jobid = int(self.jobid)

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)

    def createVMsForSR(self, sr):
        for i in range(self.vms_per_sr):
            xenrt.TEC().progress("Installing VM %d on disk %s" % (i, self.sr_to_diskname[sr]))

            # Clone original VM
            cloned_vm = self.template.cloneVM(name="%s-%d" % (self.sr_to_diskname[sr], i))
            self.vm.append(cloned_vm)
            self.host.addGuest(cloned_vm)

            for j in range(self.vbds_per_vm):
                vbd_uuid = cloned_vm.createDisk(sizebytes=self.vdi_size,
                                                sruuid=sr,
                                                smconfig=self.sm_config,
                                                returnVBD=True)

                if self.backend == "xen-tapdisk3":
                    self.host.genParamSet("vbd", vbd_uuid, "other-config:backend-kind", "vbd3")
                elif self.backend == "xen-tapdisk2" or self.backend == "xen-blkback":
                    self.host.genParamSet("vbd", vbd_uuid, "other-config:backend-kind", "vbd")

            cloned_vm.start()
            libsynexec.start_slave(cloned_vm, self.jobid)

    def runPrepopulate(self):
        for vm in self.vm:
            for i in range(self.vbds_per_vm):
                vm.execguest("dd if=/dev/zero of=/dev/xvd%s bs=1M oflag=direct || true" % chr(ord('b') + i))

    def runPhase(self, count, op):
        for blocksize in self.blocksizes:
            # Run synexec master
            libsynexec.start_master_in_dom0(self.host,
                    """/bin/bash :CONF:
#!/bin/bash

for i in {b..%s}; do
    pididx=0
    /root/latency -s -t%s%s -b %d /dev/xvd\\$i %d &> /root/out-\\$i &
    pid[\\$pididx]=\\$!
    ((pididx++))
done

for ((idx=0; idx<pididx; idx++)); do
  wait \\${pid[\\$idx]}
done
""" % (chr(ord('a') + self.vbds_per_vm), "" if op == "r" else " -w",
       " -z" if self.zeros else "", blocksize, self.duration),
                    self.jobid, len(self.vm))

            for vm in self.vm:
                libsynexec.start_slave(vm, self.jobid)

            # Fetch results from slaves
            for vm in self.vm:
                for j in range(self.vbds_per_vm):
                    results = vm.execguest("cat /root/out-%s" % chr(ord('b') + j))
                    for line in results.splitlines():
                        # Log format: Operation(r,w) iteration, blocksize, diskname, VM number on that SR, VBD number, number of bytes processed
                        self.log("slave", "%s %d %d %s %s %d %s" %
                                 (op, count + 1, blocksize, vm.getName().split("-")[0], vm.getName().split("-")[1], j, line))

            # Fetch log from master
            results = libsynexec.get_master_log(self.host)
            for line in results.splitlines():
                self.log("master", "%d %s" % (blocksize, line))

    def installTemplate(self, guests):
        # Install 'vm-template'
        if not self.isNameinGuests(guests, "vm-template"):
            xenrt.TEC().progress("Installing VM template")

            self.template = xenrt.productLib(host=self.host).guest.createVM(\
                    host=self.host,
                    guestname="vm-template",
                    vcpus=self.vcpus_per_vm,
                    memory=self.vm_ram,
                    distro=self.distro,
                    arch=self.arch,
                    vifs=xenrt.productLib(host=self.host).Guest.DEFAULT)

            self.template.installLatency()
            libsynexec.initialise_slave(self.template)

            # Shutdown VM for cloning
            self.shutdown_vm(self.template)
        else:
            for vm in guests:
                if vm.getName() == "vm-template":
                    self.template = vm

    def destroyVMs(self, guests):
        # Destroy all VMs other than vm-template
        for vm in guests:
            if vm.getName() != "vm-template":
                try:
                    vm.shutdown(force=True)
                except Exception as e:
                    # Ignore but log shutdown errors  
                    xenrt.TEC().logverbose("Shutting down VM: exception %s" % e)

                vm.uninstall(destroyDisks=True)

    def run(self, arglist=None):
        self.changeNrDom0vcpus(self.host, self.dom0vcpus)

        libsynexec.initialise_master_in_dom0(self.host)

        guests = self.host.guests.values()
        self.installTemplate(guests)
        self.destroyVMs(guests)

        # Save original SM backend type and set new one if necessary
        if self.backend == "xen-blkback":
            original_backend = self.host.execdom0('grep ^VDI_TYPE_RAW /opt/xensource/sm/vhdutil.py | sed "s/VDI_TYPE_RAW = \'\\(.\\+\\)\'/\\1/"').strip()
            self.host.execdom0('sed -i "s/^VDI_TYPE_RAW = \'\\(aio\|phy\\)\'$/VDI_TYPE_RAW = \'phy\'/" /opt/xensource/sm/vhdutil.py')

        # Create SRs on the given devices
        for device in self.devices:
            if device == "default":
                sr = self.host.lookupDefaultSR()
                self.sr_to_diskname[sr] = "default"
            elif device.startswith("xen-sr="):
                device = sr = device.split('=')[1]
                self.sr_to_diskname[sr] = sr.split("-")[0]
            elif device.startswith("xen-device="):
                device = device.split('=')[1]

                # Remove any existing SRs on the device
                uuids = self.host.minimalList("pbd-list",
                                              args="params=sr-uuid "
                                                   "device-config:device=%s" % device)
                for uuid in uuids:
                    self.host.forgetSR(uuids[0])

                diskname = self.host.execdom0("basename `readlink -f %s`" % device).strip()
                sr = xenrt.lib.xenserver.host.LVMStorageRepository(self.host, 'SR-%s' % diskname)
                sr.create(device)
                sr = sr.uuid
                self.sr_to_diskname[sr] = diskname

            # Set the SR scheduler
            if device in self.disk_schedulers:
                self.changeDiskScheduler(self.host, sr, self.disk_schedulers[device])

            self.createVMsForSR(sr)

        if self.prepopulate:
            self.runPrepopulate()

        for i in range(self.write_iterations):
            self.runPhase(i, 'w')

        for i in range(self.read_iterations):
            self.runPhase(i, 'r')

        self.destroyVMs(self.vm)

        # Restore original backend type if necessary
        if self.backend == "xen-blkback":
            self.host.execdom0('sed -i "s/^VDI_TYPE_RAW = \'\\(aio\|phy\\)\'$/VDI_TYPE_RAW = \'%s\'/" /opt/xensource/sm/vhdutil.py' % original_backend)
