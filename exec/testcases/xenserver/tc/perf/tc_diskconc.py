import xenrt, libperf, string
import libsynexec

null_blk = "null_blk"

class TCDiskConcurrent(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCDiskConcurrent")

        self.vbds = 0       # Number of total VBDs plugged in the host
        self.rvms = 0       # Number of total number of VMs running

        # VM Data
        self.vm = [ ]
        self.host = self.getDefaultHost()
        self.userdevice = 1
        size = 1 # 1GB
        self.edisk = ( self.userdevice, size, False )  # definition of an extra disk

    def loadKernelModule(self):
        if not self.backend:
            return
        elif self.backend == null_blk:
            libperf.PerfTestCase.loadModule(self, self.host, "null_blk nr_devices=20")
        else:
            raise xenrt.XRTError("unknown module for backend: %s" % (self.backend,))

    def nullblkAttach(self, vm):
        #attach nulldev device to vm if not already attached
        vmname = vm.getName()
        vmidx = int(vmname.replace("vm",""))
        nullblkdev = "/dev/nullb%s" % (vmidx,)
        #eg. tap-ctl list => pid=32623 minor=2 state=0 args=aio:/dev/nullb1
        is_attached = int(self.host.execdom0("tap-ctl list |grep %s |wc -l" % (nullblkdev,)).strip()) > 0
        if not is_attached:
            #attach it
            spawn = self.host.execdom0("tap-ctl spawn").strip()
            target = self.host.execdom0("tap-ctl allocate").strip()
            m = target.split("/dev/xen/blktap-2/tapdev")[1]
            attach = self.host.execdom0("tap-ctl attach -p %s -m %s" % (spawn, m))
            tcopen = self.host.execdom0("tap-ctl open -p %s -m %s -a aio:%s" % (spawn, m, nullblkdev))
            vmdomid = vm.getDomid()
            dev = self.vmDiskDev(vm)
            xl = self.host.execdom0("xl block-attach %s backendtype=phy,vdev=%s,target=%s" % (vmdomid, dev, target))

    def nullblkDetach(self, vm):
        domid = None
        try:
            domid = vm.getDomid()
        except Exception, e:
            xenrt.TEC().logverbose("nullblkDetach: getDomid(): exception %s" % (e,))
        if not domid:
            #domid does not exist, no need to detach anything
            return
        xs0 = self.host.execdom0('xenstore-ls -f | egrep "/local/domain/0/backend/vbd/%s/.*\"xvdf\""' % (domid,)).strip()
        #xs0 eg.: /local/domain/0/backend/vbd/6/51792/dev = "xvdf"
        devid = xs0.split("/")[7] #eg. 51792
        xs1 = self.host.execdom0("xenstore-ls -f | grep /local/domain/0/backend/vbd/%s/%s/params" % (domid, devid)).strip()
        #xs1 eg.: /local/domain/0/backend/vbd/6/51792/params = "/dev/xen/blktap-2/tapdev11"
        m = xs1.split("=")[1].replace("\"","").strip().split("/dev/xen/blktap-2/tapdev")[1] #eg. 11
        tc0 = self.host.execdom0("tap-ctl list -m %s" % (m,)).strip()
        #tc0 eg.: pid=31719 minor=11 state=0 args=aio:/dev/nullb1
        tc0dic = dict(map(lambda e: tuple(e.split("=")), tc0.split(" ")))
        #tc0dic eg.: {'state': '0', 'args': 'aio:/dev/nullb1', 'pid': '31719', 'minor': '11'}
        pid = tc0dic["pid"]
        self.host.execdom0("xl block-detach %s %s" % (domid, devid))
        self.host.execdom0("tap-ctl close -p %s -m %s" % (pid, m))
        self.host.execdom0("tap-ctl detach -p %s -m %s" % (pid, m))
        self.host.execdom0("tap-ctl free -m %s" % (m,))

    def backendAttach(self, vm):
        if not self.backend:
            return
        elif self.backend == null_blk:
            self.nullblkAttach(vm)
        else:
            raise xenrt.XRTError("attach: unknown backend: %s" % (self.backend,))

    def backendDetach(self, vm):
        if not self.backend:
            return
        elif self.backend == null_blk:
            self.nullblkDetach(vm)
        else:
            raise xenrt.XRTError("detach: unknown backend: %s" % (self.backend,))

    def vmDiskDev(self, vm=None):
        if self.backend == null_blk:
            return "xvdf"
        else:
            return "xvdb"

    def parseArgs(self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs(self, arglist)

        # Parse other arguments
        self.vms        = libperf.getArgument(arglist, "numvms",     int, 20)
        self.writefirst = libperf.getArgument(arglist, "writefirst", str, "true")
        self.bufsize    = libperf.getArgument(arglist, "bufsize",    int, 32768)
        self.op         = libperf.getArgument(arglist, "op",         str, "read")
        self.distro     = libperf.getArgument(arglist, "distro",     str, "debian60")
        self.arch       = libperf.getArgument(arglist, "arch",       str, "x86-32")
        self.dom0vcpus  = libperf.getArgument(arglist, "dom0vcpus",  int, None)
        self.scheduler  = libperf.getArgument(arglist, "scheduler",  str, None)
        self.backend    = libperf.getArgument(arglist, "backend",    str, None)

        # Latency program command line
        self.latcmd = "/root/latency -s %s -b %d /dev/%s 60" % ("-w" if self.op=="write" else "", self.bufsize, self.vmDiskDev())

        # Fetch JobID
        self.jobid = xenrt.TEC().gec.config.lookup("JOBID", None)
        xenrt.TEC().progress("My JOBID is %s" % self.jobid)
        self.jobid = int(self.jobid)

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)

    def run(self, arglist=None):
        self.changeNrDom0vcpus(self.host, self.dom0vcpus)
        self.loadKernelModule()
        self.host.execdom0("iptables -F")

        guests = self.host.guests.values()

        if self.isNameinGuests(guests, "vm00"):
            # reuse any existing vms
            self.vm = guests
            self.rvms = len(self.vm)
            self.vbds = len(self.vm) * 2
        else:
            # Install 'vm00'
            xenrt.TEC().progress("Installing VM zero")
            self.vm.append(xenrt.lib.xenserver.guest.createVM(\
                    host=self.host,
                    guestname="vm00",
                    distro=self.distro,
                    arch=self.arch,
                    vifs=xenrt.lib.xenserver.Guest.DEFAULT,
                    disks=[ self.edisk ]))
            self.rvms += 1
            self.vbds += 2

            # Copy bins to 'vm00'
            sftp = self.vm[0].sftpClient()
            sftp.copyTo("/home/xenrtd/felipef/latency", "/root/latency")
            libsynexec.initialise_slave(self.vm[0])

            # Copy bins to dom0
            sftp = self.host.sftpClient()
            libsynexec.initialise_master_in_dom0(self.host)

            # Populate the extra disk
            if (self.writefirst == "true"):
                self.vm[0].execguest("dd if=/dev/zero of=/dev/xvdb bs=1M oflag=direct || true")

        if len(self.vm) > self.vms:
            # Shutdown unnecessary VMs
            for i in range(self.vms, len(self.vm)):
                self.backendDetach(self.vm[i]) #must detach any out-of-xapi devices before shutdown
                self.shutdown_vm(self.vm[i])

        if len(self.vm) < self.vms:
            # Shutdown VM for cloning
            self.backendDetach(self.vm[0]) #must detach any out-of-xapi devices before shutdown
            self.shutdown_vm(self.vm[0])

            # Install more VMs as appropriate
            for i in range(len(self.vm), self.vms):
                xenrt.TEC().progress("Installing VM %d" % i)

                # Copies original VM (much quicker than installing another one)
                cloned_vm = self.vm[0].copyVM(name="vm%02d" % i)
                self.vm.append(cloned_vm)
                self.host.addGuest(cloned_vm)
                self.vm[i].start()

                # Populate the extra disk
                if (self.writefirst == "true"):
                    self.vm[i].execguest("dd if=/dev/zero of=/dev/xvdb bs=1M oflag=direct || true")

                # At this point, we added one VM and plugged two more VBDs to the host
                self.rvms += 1
                self.vbds += 2

        # Make sure all VMs are running and have synexec on
        for i in range(0, self.vms):
            self.start_vm(self.vm[i])
            self.backendAttach(self.vm[i])
            libsynexec.start_slave(self.vm[i], self.jobid)

        # Change scheduler of the SRs where the VMs' VBDs are on
        for i in range(0, self.vms):
            sr_uuid = self.getSRofGuest(self.vm[i], self.userdevice)
            self.changeDiskScheduler(self.host, sr_uuid, self.scheduler)

        # Run synexec master
        libsynexec.start_master_in_dom0(self.host, self.latcmd, self.jobid, self.vms)

        # Fetch results from slaves
        for i in range (0, self.vms):
            results = libsynexec.get_slave_log(self.vm[i])
            for line in results.splitlines():
                self.log("concurrent", "%d %d" % (i, int(line)))

        # Fetch log from master
        results = libsynexec.get_master_log(self.host)
        self.log("synexec_master", "%s" % results)
