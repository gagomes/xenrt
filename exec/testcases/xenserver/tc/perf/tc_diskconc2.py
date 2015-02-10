import xenrt, libperf, string, os, os.path, threading, time, re
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

        # blocksizes is a list of either bytes or names of pre-defined access patterns, e.g. "tesco"
        self.blocksizes = libperf.getArgument(arglist, "blocksizes",  str,
                                              "512,1024,2048,4096,8192,16384,32768,65536,131072,262144,524288,1048576,2097152,4194304")
        self.blocksizes = self.blocksizes.strip().split(",")
        self.vms_per_sr = libperf.getArgument(arglist, "vms_per_sr", int, 1)
        self.vbds_per_vm = libperf.getArgument(arglist, "vbds_per_vm", int, 1)
        self.vcpus_per_vm = libperf.getArgument(arglist, "vcpus_per_vm", int, None)

        # A number in MB; e.g. 1024
        self.vm_ram = libperf.getArgument(arglist, "vm_ram", int, None)

        self.duration = libperf.getArgument(arglist, "duration", int, 60)
        self.vdi_size = libperf.getArgument(arglist, "vdi_size", str, "5GiB")
        self.distro = libperf.getArgument(arglist, "distro", str, "debian60")
        self.postinstall = libperf.getArgument(arglist, "postinstall", str, None) # comma-separated list of guest function names
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

    def runPrepopulate(self):
        for vm in self.vm:
            for i in range(self.vbds_per_vm):
                vm.execguest("dd if=/dev/zero of=$(echo /dev/*d%s) bs=1M oflag=direct || true" % chr(ord('b') + i))

    def runPrepopulateWindows(self):
        for vm in self.vm:
            for i in range(self.vbds_per_vm):
                script = """select disk %d
clean all
""" % (i + 1)
                vm.xmlrpcWriteFile("C:\\erase.script", script)
                vm.xmlrpcExec("diskpart /s C:\\erase.script")

    def runPhase(self, count, op):
        for blocksize in self.blocksizes:
            # TODO we don't support pre-defined access patterns with 'latency', only integer block sizes
            blocksize = int(blocksize)
            # Run synexec master
            proc, port = libsynexec.start_master_on_controller(
                    """/bin/bash :CONF:
#!/bin/bash

for i in {b..%s}; do
    pididx=0
    /root/latency -s -t%s%s -b %d /dev/*d$i %d &> /root/out-$i &
    pid[$pididx]=$!
    ((pididx++))
done

for ((idx=0; idx<pididx; idx++)); do
  wait ${pid[$idx]}
done
""" % (chr(ord('a') + self.vbds_per_vm), "" if op == "r" else " -w",
       " -z" if self.zeros else "", blocksize, self.duration),
                    self.jobid, len(self.vm))

            for vm in self.vm:
                libsynexec.start_slave(vm, self.jobid, port)

            proc.wait()

            # Fetch results from slaves
            for vm in self.vm:
                for j in range(self.vbds_per_vm):
                    results = vm.execguest("cat /root/out-%s" % chr(ord('b') + j))
                    for line in results.splitlines():
                        # Log format: Operation(r,w) iteration, blocksize, diskname, VM number on that SR, VBD number, number of bytes processed
                        self.log("slave", "%s %d %d %s %s %d %s" %
                                 (op, count + 1, blocksize, vm.getName().split("-")[0], vm.getName().split("-")[1], j, line))

            # Fetch log from master
            results = libsynexec.get_master_log_on_controller(self.jobid)
            for line in results.splitlines():
                self.log("master", "%d %s" % (blocksize, line))

    def get_nbname(self, vm):
        vm.xmlrpcExec("nbtstat -n > C:\\out.txt")
        data = vm.xmlrpcReadFile("C:\\out.txt")
        return re.search("----+\r\n(.*)<", data, re.MULTILINE).group(1).strip()

    def runPhaseWindows(self, count, op):
        def dynamo_thread(vm):
            master_ip = self.vm[0].mainip

            # the master's dynamo is started automatically
            if master_ip != vm.mainip:
                time.sleep(10)
                vm.xmlrpcExec("C:\\dynamo.exe -i %s -m %s" % (master_ip, vm.mainip))

        # Get the netbios name of the master
        nbname = self.get_nbname(self.vm[0])

        queueDepth = 1

        for blocksize in self.blocksizes:
            if blocksize == 'tesco':
                accessSpecs = [
                    ("Email Server - R60 W40- RND- 4K",    "NONE", ["4096,100,60,100,0,1,0,0"]),
                    ("Database Server - R70 W30- RND- 8K", "NONE", ["8192,100,70,100,0,1,0,0"]),
                    ("Web Server - R95 W5- RND- Var",      "NONE", [
                        "2048,20,95,100,0,1,0,0",
                        "4096,19,95,100,0,1,0,0",
                        "8192,18,95,100,0,1,0,0",
                        "16384,17,95,100,0,1,0,0",
                        "32768,16,95,100,0,1,0,0",
                        "65536,10,95,100,0,1,0,0"]),
                    ("Online Tranaction Processing (OLTP)  Server - R80 W20- RND- Var", "NONE", [
                        "2048,33,80,100,0,1,0,0",
                        "4096,33,95,100,0,1,0,0",
                        "8192,34,80,100,0,1,0,0"]),
                    ("Archical File Server - R90 W10- SEQ- Var", "NONE", [
                        "65536,13,90,0,0,1,0,0",
                        "262144,34,95,100,0,1,0,0",
                        "524288,23,80,100,0,1,0,0",
                        "1048576,20,80,100,0,1,0,0",
                        "5242880,10,80,100,0,1,0,0"]),
                    ("User Store File Server - R80 W20- SEQ- Var", "NONE", [
                        "65536,13,80,0,0,1,0,0",
                        "262144,34,95,100,0,1,0,0",
                        "524288,23,80,100,0,1,0,0",
                        "1048576,20,80,100,0,1,0,0",
                        "5242880,10,80,100,0,1,0,0"]),
                    ("Streaming Media Server - R98 W2- SEQ- Var", "NONE", [
                        "65536,2,98,0,0,1,0,0",
                        "262144,5,95,100,0,1,0,0",
                        "524288,10,80,100,0,1,0,0",
                        "1048576,17,80,100,0,1,0,0",
                        "5242880,66,80,100,0,1,0,0"]),
                    ("Burst Read- 2M",  "NONE", ["2097152,100,100,0,0,16,0,0"]),
                    ("Burst Write- 2M", "NONE", ["2097152,100,0,0,0,16,0,0"]),
                    ("Std Read- 2M",    "NONE", ["2097152,100,100,0,0,1,0,0"]),
                    ("Std Write- 2M",   "NONE", ["2097152,100,0,0,0,1,0,0"])
                ]
            else:
                # treat the block size as a number of bytes
                accessSpecs = [
                    ("custom", "ALL", ["%d,100,%d,0,0,1,%d,0" % (int(blocksize), 100 if op == "r" else 0, int(blocksize))])
                ]

            config = """Version 1.1.0 
'TEST SETUP ====================================================================
'Test Description
	
'Run Time
'	hours      minutes    seconds
	0          0          %d
'Ramp Up Time (s)
	0
'Default Disk Workers to Spawn
	0
'Default Network Workers to Spawn
	0
'Record Results
	ALL
'Worker Cycling
'	start      step       step type
	1          1          LINEAR
'Disk Cycling
'	start      step       step type
	1          1          LINEAR
'Queue Depth Cycling
'	start      end        step       step type
	1          32         2          EXPONENTIAL
'Test Type
	NORMAL
'END test setup
'RESULTS DISPLAY ===============================================================
'Record Last Update Results,Update Frequency,Update Type
	DISABLED,0,WHOLE_TEST
'Bar chart 1 statistic
	Total I/Os per Second
'Bar chart 2 statistic
	Total MBs per Second (Decimal)
'Bar chart 3 statistic
	Average I/O Response Time (ms)
'Bar chart 4 statistic
	Maximum I/O Response Time (ms)
'Bar chart 5 statistic
	%% CPU Utilization (total)
'Bar chart 6 statistic
	Total Error Count
'END results display
'ACCESS SPECIFICATIONS =========================================================
""" % (self.duration)

            for (name, defaultAssign, specs) in accessSpecs:
                config += """'Access specification name,default assignment
	%s,%s
'size,%% of size,%% reads,%% random,delay,burst,align,reply
""" % (name, defaultAssign)

                for spec in specs:
                    config += """	%s
""" % (spec)

            config += """'END access specifications
'MANAGER LIST ==================================================================
"""
            for i, vm in enumerate(self.vm):
                config += """'Manager ID, manager name
	%d,%s
'Manager network address
	%s
""" % (i + 1, nbname, "" if i == 0 else vm.mainip)

                for i in range(self.vbds_per_vm):
                    config += """'Worker
	Worker %d
'Worker type
	DISK
'Default target settings for worker
'Number of outstanding IOs,test connection rate,transactions per connection,use fixed seed,fixed seed value
	%d,DISABLED,1,DISABLED,0
'Disk maximum size,starting sector,Data pattern
	0,0,0
'End default target settings for worker
'Assigned access specs
""" % (i+1, queueDepth)

                    for (name, _, _) in accessSpecs:
                        config += """	%s
""" % (name)

                    config += """'End assigned access specs
'Target assignments
'Target
	%d: "XENSRC PVDISK 2.0"
'Target type
	DISK
'End target
'End target assignments
'End worker
""" % (i+1)

                config += "'End manager\n"

            config += """'END manager list
Version 1.1.0 
"""
            self.vm[0].xmlrpcWriteFile("C:\\workload.icf", config)

            # Run a worker thread for each dynamo process
            threads = []
            for vm in self.vm:
                thread = threading.Thread(target=dynamo_thread, args=(vm,))
                thread.start()
                threads.append(thread)

            # Start the master
            filename = "results-%s-%d-%s.csv" % (op, count, blocksize)
            self.vm[0].xmlrpcExec("C:\\iometer.exe /c C:\\workload.icf /r C:\\%s /t 100" % filename)

            # Wait for the dynamo processes to finish
            for thread in threads:
                thread.join()

            # Store the results
            data = self.vm[0].xmlrpcReadFile("C:\\" + filename)
            data = data.replace("\r", "").strip()
            self.log("results", data)

            # Process the results into the same format as synexec+latency uses
            i = 0
            for line in data.split("\n"):
                if line.startswith("'Results"):
                    i = 0
                if line.startswith("MANAGER"):
                    vm = self.vm[i]
                    j = 0
                    i += 1
                if line.startswith("WORKER"):
                    line = line.split(",")
                    if blocksize == 'tesco':
                        result = float(line[13]) + float(line[14]) # sum read + write
                        # delete whitespace from the name of the workload
                        op = "tesco-%s" % (line[2])
                        op = op.replace(' ', '')
                        dispblocksize = 0
                    else:
                        result = float(line[13 if op == "r" else 14])
                        dispblocksize = blocksize
                    result = result * 1000000 * self.duration
                    result = long(result)
                    self.log("slave", "%s %d %s %s %s %d %s" %
                             (op, count + 1, dispblocksize, vm.getName().split("-")[0], vm.getName().split("-")[1], j, result))
                    j += 1

    def installTemplate(self, guests):
        # Install 'vm-template'
        if not self.isNameinGuests(guests, "vm-template"):
            xenrt.TEC().progress("Installing VM template")

            postinstall = [] if self.postinstall is None else self.postinstall.split(",")

            self.template = xenrt.productLib(host=self.host).guest.createVM(\
                    host=self.host,
                    guestname="vm-template",
                    vcpus=self.vcpus_per_vm,
                    memory=self.vm_ram,
                    distro=self.distro,
                    arch=self.arch,
                    postinstall=postinstall,
                    vifs=self.host.guestFactory().DEFAULT)

            if self.template.windows:
                if not isinstance(self.template, xenrt.lib.esx.Guest):
                    self.template.installDrivers(extrareboot=True)

                # Use pvsoptimize to reduce background tasks and IO
                urlperf = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "")
                pvsexe = "TargetOSOptimizer.exe"
                pvsurl = "%s/performance/support-files/%s" % (urlperf, pvsexe)
                pvsfile = xenrt.TEC().getFile(pvsurl,pvsurl)
                cpath = "c:\\%s" % pvsexe
                self.template.xmlrpcSendFile(pvsfile, cpath)
                self.template.xmlrpcExec("%s /s" % cpath)

                self.template.installIOMeter()

                # Reboot once more to ensure everything is quiescent
                self.template.reboot()
            else:
                if isinstance(self.template, xenrt.lib.esx.Guest):
                    self.template.installTools()
                self.template.installLatency()
                libsynexec.initialise_slave(self.template)

            if self.distro.startswith("rhel") or self.distro.startswith("centos") or self.distro.startswith("oel"):
                # When we clone this guest, we don't want it to remember its MAC address
                self.template.execguest("sed -i /HWADDR/d /etc/sysconfig/network-scripts/ifcfg-eth0")

            # Shutdown VM for cloning
            self.shutdown_vm(self.template)
        else:
            for vm in guests:
                if vm.getName() == "vm-template":
                    self.template = vm

        self.windows = self.template.windows

    def run(self, arglist=None):
        self.changeNrDom0vcpus(self.host, self.dom0vcpus)

        libsynexec.initialise_master_on_controller(self.jobid)

        guests = self.host.guests.values()
        self.installTemplate(guests)

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
            elif device.startswith("xen-srname="):
                srname = device.split('=')[1]
                sr = self.host.minimalList("sr-list", args="name-label=%s" % (srname))[0]
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
            elif device.startswith("esx-device="):
                device = sr = device.split('=')[1]

                diskname = 'local' + device[-1]
                disknum = ord(device[-1]) - ord('b')
                devices = self.host.execdom0("ls -1F /vmfs/devices/disks | grep -v '@' | grep -v ':' | sort").strip().split("\n")

                volumeinfo = self.host.execdom0("esxcli storage vmfs extent list").strip().split("\n")
                volumeinfo = volumeinfo[2:]
                rootdevice = ""
                for line in volumeinfo:
                    line = line.split()
                    if line[0] == "datastore1":
                        rootdevice = line[3]
                devices = sorted(filter(lambda dev: dev != rootdevice, devices))
                esxdev = devices[disknum]

                # Create the partition and format it
                size = self.host.execdom0('partedUtil get "/vmfs/devices/disks/%s" | head -n 1' % esxdev).strip().split(' ')[3]
                size = int(size) - 10240 # It doesn't seem to like using all the way up to the last sector
                self.host.execdom0('partedUtil setptbl "/vmfs/devices/disks/%s" gpt "1 2048 %d AA31E02A400F11DB9590000C2911D1B8 0"' % (esxdev, size))
                self.host.execdom0('vmkfstools -C vmfs5 -b 1m -S %s "/vmfs/devices/disks/%s:1"' % (diskname, esxdev))

                # Reload the host information until the new SR appears
                while diskname not in self.host.srs:
                    time.sleep(1)
                    self.host.existing()

                sr = self.host.getSRUUID(diskname)
                self.sr_to_diskname[sr] = diskname
            elif device.startswith("kvm-device="):
                device = device.split('=')[1]

                diskname = self.host.execdom0("basename `readlink -f %s`" % device).strip()
                srname = "SR-%s" % (diskname)
                sr = xenrt.lib.kvm.EXTStorageRepository(self.host, srname)
                sr.create(device)

                # Reload the host information until the new SR appears
                while srname not in self.host.srs:
                    time.sleep(1)
                    self.host.existing()
                    xenrt.TEC().logverbose("host has SRs %s" % (self.host.srs))

                sr = self.host.getSRUUID(srname)
                self.sr_to_diskname[sr] = diskname

            # Set the SR scheduler
            if device in self.disk_schedulers:
                self.changeDiskScheduler(self.host, sr, self.disk_schedulers[device])

            self.createVMsForSR(sr)

        # Log the IO engine used, for RAGE
        if self.windows:
            libperf.logArg("ioengine", "iometer")
        else:
            libperf.logArg("ioengine", "latency")

        if self.prepopulate:
            if self.windows:
                self.runPrepopulateWindows()
            else:
                self.runPrepopulate()

        for i in range(self.write_iterations):
            if self.windows:
                self.runPhaseWindows(i, 'w')
            else:
                self.runPhase(i, 'w')

        for i in range(self.read_iterations):
            if self.windows:
                self.runPhaseWindows(i, 'r')
            else:
                self.runPhase(i, 'r')

        # Restore original backend type if necessary
        if self.backend == "xen-blkback":
            self.host.execdom0('sed -i "s/^VDI_TYPE_RAW = \'\\(aio\|phy\\)\'$/VDI_TYPE_RAW = \'%s\'/" /opt/xensource/sm/vhdutil.py' % original_backend)
