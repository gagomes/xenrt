import xenrt, libperf, string
import libsynexec


class TCApacheBench(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCApacheBench")

        self.clientvms = [ ]
        self.servervms = [ ]
        self.serverHost = self.getHost("RESOURCE_HOST_0")
        self.clientHost = self.getHost("RESOURCE_HOST_1")

    def parseArgs(self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs(self, arglist)

        # Parse other arguments
        self.distro     = libperf.getArgument(arglist, "distro", str, "debian60")
        self.arch       = libperf.getArgument(arglist, "arch",   str, "x86-32")
        self.vmram      = libperf.getArgument(arglist, "memory", int, 256)
        self.vcpus      = libperf.getArgument(arglist, "vcpus",  int, 1)
        self.numclients = libperf.getArgument(arglist, "numvms", int, 20)
        self.numservers = self.numclients  # we use the same number of clients as servers

        self.postinstall = libperf.getArgument(arglist, "postinstall", str, None) # comma-separated list of guest function names
        self.postinstall = [] if (self.postinstall is None or self.postinstall == "") else self.postinstall.split(",")

        # Apachebench client command-line
        self.abCmd = "/usr/bin/ab -n 1000 -c 100 -g /root/ab.log http://%s/" # expects IP address of server

        # Fetch JobID
        self.jobid = xenrt.TEC().gec.config.lookup("JOBID", None)
        xenrt.TEC().progress("My JOBID is %s" % self.jobid)
        self.jobid = int(self.jobid)

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)

    def run(self, arglist=None):
        # Install the VMs on the two hosts in parallel
        xenrt.pfarm ([
            xenrt.PTask(self.createServers, self.serverHost),
            xenrt.PTask(self.createClients, self.clientHost)
        ])
        self.invokeClients(self.clientHost)

    def createVM(self, host, name):
        return xenrt.productLib(host=host).guest.createVM(\
            host=host,
            guestname=name,
            distro=self.distro,
            arch=self.arch,
            memory=self.vmram,
            vcpus=self.vcpus,
            vifs=self.host.guestFactory().DEFAULT,
            disks=[],
            postinstall=self.postinstall)

    def createServers(self, host):
        xenrt.TEC().progress("Installing server zero")
        self.servervms.append(self.createVM(host, "server00"))

        # Install apache
        self.servervms[0].execguest("apt-get -y --force-yes install apache2")

        # Shutdown VM for cloning
        self.servervms[0].shutdown()

        for i in range(1, self.numservers):
            xenrt.TEC().progress("Installing server VM %d" % i)

            # Clone original VM
            self.servervms.append(self.servervms[0].cloneVM(name="server%02d" % i))
            self.servervms[i].start()

        # Restart server00
        self.servervms[0].start()

    def createClients(self, host):
        # Run synexec on the controller to allow this to work on any hypervisor
        libsynexec.initialise_master_on_controller(self.jobid)

        # Install 'client00'
        xenrt.TEC().progress("Installing client zero")
        self.clientvms.append(self.createVM(host, "client00"))

        # Copy synexec slave binary to 'client00'
        libsynexec.initialise_slave(self.clientvms[0])

        # Install apache tools on client00
        self.clientvms[0].execguest("apt-get -y --force-yes install apache2-utils")

        # Shutdown client00 for cloning
        self.clientvms[0].shutdown()

        # Install more VMs as appropriate
        for i in range(1, self.numclients):
            xenrt.TEC().progress("Installing client VM %d" % i)

            # Clone original VM
            self.clientvms.append(self.clientvms[0].cloneVM(name="client%02d" % i))
            self.clientvms[i].start()

        # Restart client00
        self.clientvms[0].start()

    def invokeClients(self, host):
        # Run synexec master
        proc, port = libsynexec.start_master_on_controller("/bin/sh /root/synexec_cmd", self.jobid, self.numclients)

        # After all the servers have booted, set up synexec slave in each of the client VMs
        for i in range(0, self.numclients):
            # Write a file containing the apachebench command, pointing it at the relevant server VM
            target = self.servervms[i].getIP()
            self.clientvms[i].execguest("echo '%s' > /root/synexec_cmd" % (self.abCmd % target))

            # Wait for the synexec master to tell this VM to run the apachebench command
            libsynexec.start_slave(self.clientvms[i], self.jobid, port)

        # Wait for jobs to complete
        proc.wait()

        # Fetch results from slaves
        for i in range (0, self.numclients):
            logFileRemote = "/root/ab.log"
            logFileLocal = "%s/ab-%d.log" % (xenrt.TEC().getLogdir(), i)
            sftp = self.clientvms[i].sftpClient()
            sftp.copyFrom(logFileRemote, logFileLocal)

        # Fetch log from master
        results = libsynexec.get_master_log_on_controller(self.jobid)
        self.log("synexec_master", "%s" % results)
