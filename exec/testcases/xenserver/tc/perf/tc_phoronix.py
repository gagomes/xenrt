import xenrt, libperf, string, os, os.path, math

class TCPhoronix(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCPhoronix")

        self.host = self.getDefaultHost()

    def parseArgs(self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs(self, arglist)

        self.device = libperf.getArgument(arglist, "device", str, "default")
        self.vm_ram = libperf.getArgument(arglist, "vm_ram", int, 4096) # note: we need > 1GB to compile some test suites
        self.distro = libperf.getArgument(arglist, "distro", str, "debian70")
        self.arch = libperf.getArgument(arglist, "arch", str, "x86-64")
        self.vcpus = libperf.getArgument(arglist, "vcpus", int, 2)
        self.rootDiskSizeGB = libperf.getArgument(arglist, "disksize", int, 24) # GB
        self.postinstall = libperf.getArgument(arglist, "postinstall", str, None) # comma-separated list of guest function names

        self.dom0vcpus  = libperf.getArgument(arglist, "dom0vcpus", int, None)

        self.multipage = libperf.getArgument(arglist, "multipage", int, None)

        if self.multipage:
            is_power2 = self.multipage != 0 and ((self.multipage & (self.multipage - 1)) == 0)

            if not is_power2:
                raise ValueError("Multipage %s is not a power of 2" % (self.multipage))

        # Optional VM image to use as a template
        self.vm_image = libperf.getArgument(arglist, "vm_image", str, None)

        # If vm_image is set, treat it as a distro name
        if self.vm_image:
            self.distro  = self.vm_image

    def createSR(self):
        device = self.device
        if device == "default":
            sr = self.host.lookupDefaultSR()
        elif device.startswith("xen-device="):
            device = device.split('=')[1]

            # Remove any existing SRs on the device
            uuids = self.host.minimalList("pbd-list",
                                          args="params=sr-uuid "
                                               "device-config:device=%s" % device)
            for uuid in uuids:
                self.host.forgetSR(uuids[0])

            diskname = self.host.execdom0("basename `readlink -f %s`" % device).strip()
            sr = xenrt.lib.xenserver.LVMStorageRepository(self.host, 'SR-%s' % diskname)
            sr.create(device)
            sr = sr.uuid

        return sr

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)

    def startGuest(self, guest):
        if self.multipage is None:
            guest.start()
        else:
            vm_uuid = guest.getUUID()

            self.host.execdom0("xe vm-start uuid=%s paused=true" % (vm_uuid))

            vmid = self.host.execdom0("list_domains | grep %s" % (vm_uuid)).strip().split(" ")[0].strip()

            vbd_uuid = self.host.execdom0("xe vbd-list params=uuid --minimal").strip()
            vdi_uuid = self.host.execdom0("xe vbd-list uuid=%s params=vdi-uuid --minimal" % (vbd_uuid)).strip()
            vbdid = self.host.execdom0("xenstore-ls -f /xapi/%s | grep vdi-id | grep %s" % (vm_uuid, vdi_uuid)).split("/")[5].strip()

            backend_xs_name = "vbd3"

            order = int(math.log(self.multipage, 2))
            self.host.execdom0("xenstore-write /local/domain/0/backend/%s/%s/%s/max-ring-page-order '%s'" %
                               (backend_xs_name, vmid, vbdid, order))

            guest.unpause()
            guest.waitReadyAfterStart()

    def resizeRootPartition(self, guest, newSizeGB):
        guest.execcmd("swapoff -a")
    
        # Remove swap partition
        guest.execcmd('echo "d\n2\nw" | fdisk /dev/xvda || true')
    
        # Remove root partition
        guest.execcmd('echo "d\nw" | fdisk /dev/xvda || true')
    
        # Create new root partition
        guest.execcmd('echo "n\np\n\n\n\nw" | fdisk /dev/xvda || true')
        guest.execcmd('partprobe || true')
    
        # Resize to desired size
        guest.execcmd('resize2fs /dev/xvda1 %dG || true' % (newSizeGB))

    def installGuest(self, guests):
        # Install 'vm-worker'
        if not self.isNameinGuests(guests, "vm-worker"):
            xenrt.TEC().progress("Installing VM worker")

            postinstall = [] if self.postinstall is None else self.postinstall.split(",")

            sr = self.createSR()

            if self.vm_image is None:
                self.guest = xenrt.productLib(host=self.host).guest.createVM(\
                    host=self.host,
                    guestname="vm-worker",
                    vcpus=self.vcpus,
                    memory=self.vm_ram,
                    distro=self.distro,
                    arch=self.arch,
                    sr=sr,
                    disks=[("0", self.rootDiskSizeGB, False)],
                    postinstall=postinstall,
                    vifs=self.host.guestFactory().DEFAULT)
            else:
                disturl = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "")
                vmurl = "%s/performance/base/%s" % (disturl, self.vm_image)
                xenrt.TEC().logverbose("Getting vm from %s" % (vmurl))
                self.guest = xenrt.productLib(host=self.host).guest.createVMFromFile(
                        host=self.host,
                        guestname=self.vm_image,
                        filename=vmurl,
                        sr=sr)

                if self.vcpus:
                    self.guest.cpuset(self.vcpus)

                if self.vm_ram:
                    self.guest.memset(self.vm_ram)

                self.guest.removeCD()
                self.startGuest(self.guest)

                if self.rootDiskSizeGB > 15:
                    self.resizeRootPartition(self.guest, self.rootDiskSizeGB)
        else:
            for vm in guests:
                if vm.getName() == "vm-worker":
                    self.guest = vm

        self.installPhoronix(self.guest)

    def installPhoronixDebian(self, guest):
        if guest.distro.startswith("debian60"):
            codename = "squeeze"
        else:
            codename = "wheezy"

        # The .tgz contains the .deb and the user-config.xml file, which should appear in the right place in /root/.phoronix-test-suite
        guest.execcmd("wget -O - '%s/phoronix-5.0.0.tgz' | tar -xz -C /root" % xenrt.TEC().lookup("TEST_TARBALL_BASE"))

        # Install some dependencies of the .deb
        guest.execcmd("echo 'deb http://http.debian.net/debian %s main' >> /etc/apt/sources.list" % (codename))
        guest.execcmd("apt-get update")
        guest.execcmd("apt-get -y --force-yes install php5-gd php5-cli")
        guest.execcmd("dpkg -i /root/phoronix-5.0.0/phoronix-test-suite_5.0.0_all.deb")

        # Install the pre-configured configuration file
        guest.execcmd("phoronix-test-suite user-config-set IndexCacheTTL=0 DefaultDisplayMode=BATCH LoadModules= SaveInstallationLogs=TRUE SaveTestLogs=TRUE")
        guest.execcmd("cp /root/phoronix-5.0.0/user-config.xml /root/.phoronix-test-suite/")

        # Hack Phoronix's use of aptitude/apt-get so it doesn't prompt for human input
        filename = "/usr/share/phoronix-test-suite/pts-core/external-test-dependencies/scripts/install-debian-packages.sh"
        guest.execcmd("sed -i 's/aptitude /aptitude -o Aptitude::Cmdline::ignore-trust-violations=true /' %s" % (filename))
        guest.execcmd("sed -i 's/apt-get -y /apt-get -y --force-yes /' %s" % (filename))

        # Install some dependencies that for some reason aren't resolved automatically
        guest.execcmd("apt-get -y --force-yes install libogg-dev libvorbis-dev yasm autoconf automake")
        
    def installPhoronixUbuntu(self, guest):
        guest.execcmd("echo 'deb http://gb.archive.ubuntu.com/ubuntu/ vivid main restricted' > /etc/apt/sources.list")
        guest.execcmd("echo 'deb http://gb.archive.ubuntu.com/ubuntu/ vivid universe' >> /etc/apt/sources.list")
        guest.execcmd("apt-get update")
        guest.execcmd("apt-get -y --force-yes install phoronix-test-suite")

        # Disable User Agreement check on first run.
        guest.execcmd("sed -i 's/pts_client::user_agreement_check($sent_command);/#pts_client::user_agreement_check($sent_command);/' /usr/share/phoronix-test-suite/pts-core/phoronix-test-suite.php")
        guest.execcmd("phoronix-test-suite user-config-set IndexCacheTTL=0 DefaultDisplayMode=BATCH LoadModules= SaveInstallationLogs=TRUE SaveTestLogs=TRUE")
        
        # Hack Phoronix's use of aptitude/apt-get so it doesn't prompt for human input
        filename = "/usr/share/phoronix-test-suite/pts-core/external-test-dependencies/scripts/install-ubuntu-packages.sh"
        guest.execcmd("sed -i 's/aptitude /aptitude -o Aptitude::Cmdline::ignore-trust-violations=true /' %s" % (filename))
        guest.execcmd("sed -i 's/apt-get -y /apt-get -y --force-yes /' %s" % (filename))
        
        # Install some dependencies that for some reason aren't resolved automatically
        guest.execcmd("apt-get -y --force-yes install libogg-dev libvorbis-dev yasm autoconf automake perl perl-base perl-modules libsdl-perl libperl-dev libtiff-dev")

    def installPhoronix(self, guest):
        # Obtain the test suite
        if self.vm_image:
            # We assume imported image is Ubuntu with multipage enabled..
            self.installPhoronixUbuntu(guest)
        elif guest.distro.startswith("debian60") or guest.distro.startswith("debian70"):
            self.installPhoronixDebian(guest)
        else:
            raise xenrt.XRTFailure("unsupported distro %s" % (guest.distro))

        # Set up Phoronix tests
        env = {"DEBIAN_FRONTEND": "noninteractive"} # otherwise installation of libssl will ask a question in ncurses
        envstr = string.join(map(lambda k: k+"="+env[k], env.keys()), " ")
        guest.execcmd("%s phoronix-test-suite install universe-cli" % (envstr), timeout=7200) # takes ages!

        # Note: some tests won't necessarily compile, e.g.
        #   x264-1.8.1                requires yasm >= 1.2.0 (installed 1.1.0)
        #   build-imagemagick-1.6.1   404 for tar file
        # Build failures will result in files /root/.phoronix-test-suite/installed-tests/pts/*/install-failed.log

    def run(self, arglist=None):
        self.changeNrDom0vcpus(self.host, self.dom0vcpus)

        guests = self.host.guests.values()
        self.installGuest(guests)

        # Run the tests
        if self.vm_image:
            # Configure Phoronix batch benchmark before the first run
            self.guest.execguest("echo y >> batch_answers") # Save test results when in batch mode (Y/n):
            self.guest.execguest("echo n >> batch_answers") # Open the web browser automatically when in batch mode (y/N):
            self.guest.execguest("echo n >> batch_answers") # Auto upload the results to OpenBenchmarking.org (Y/n):
            self.guest.execguest("echo n >> batch_answers") # Prompt for test identifier (Y/n):
            self.guest.execguest("echo n >> batch_answers") # Prompt for test description (Y/n):
            self.guest.execguest("echo n >> batch_answers") # Prompt for saved results file-name (Y/n):
            self.guest.execguest("echo y >> batch_answers") # Run all test options (Y/n):
            self.guest.execguest("cat batch_answers | phoronix-test-suite batch-setup")

        self.guest.execguest("phoronix-test-suite batch-benchmark universe-cli", timeout=3*3600)

        # Get the results for the tests that ran successfully
        resultsdir = self.guest.execguest("ls -1 .phoronix-test-suite/test-results | head -n 1").strip()
        resultsfile = "/root/.phoronix-test-suite/test-results/%s/test-1.xml" % (resultsdir)
        sftp = self.guest.sftpClient()
        sftp.copyFrom(resultsfile, '%s/test-1.xml' % (xenrt.TEC().getLogdir()))
