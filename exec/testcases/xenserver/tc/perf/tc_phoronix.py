import xenrt, libperf, string, os, os.path

class TCPhoronix(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCPhoronix")

        self.host = self.getDefaultHost()

    def parseArgs(self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs(self, arglist)

        self.vm_ram = libperf.getArgument(arglist, "vm_ram", int, 4096) # note: we need > 1GB to compile some test suites
        self.distro = libperf.getArgument(arglist, "distro", str, "debian70")
        self.arch = libperf.getArgument(arglist, "arch", str, "x86-64")
        self.vcpus = libperf.getArgument(arglist, "vcpus", int, 2)
        self.rootDiskSizeGB = libperf.getArgument(arglist, "disksize", int, 24) # GB
        self.postinstall = libperf.getArgument(arglist, "postinstall", str, None) # comma-separated list of guest function names

        self.dom0vcpus  = libperf.getArgument(arglist, "dom0vcpus", int, None)

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)

    def installGuest(self, guests):
        # Install 'vm-worker'
        if not self.isNameinGuests(guests, "vm-worker"):
            xenrt.TEC().progress("Installing VM worker")

            postinstall = [] if self.postinstall is None else self.postinstall.split(",")

            self.guest = xenrt.productLib(host=self.host).guest.createVM(\
                    host=self.host,
                    guestname="vm-worker",
                    vcpus=self.vcpus,
                    memory=self.vm_ram,
                    distro=self.distro,
                    arch=self.arch,
                    disks=[("0", self.rootDiskSizeGB, False)],
                    postinstall=postinstall,
                    vifs=self.host.guestFactory().DEFAULT)
        else:
            for vm in guests:
                if vm.getName() == "vm-worker":
                    self.guest = vm

        self.installPhoronix(self.guest)

    def installPhoronix(self, guest):
        # Obtain the test suite
        if guest.distro.startswith("debian60") or guest.distro.startswith("debian70"):
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
        self.guest.execguest("phoronix-test-suite batch-benchmark universe-cli", timeout=3*3600)

        # Get the results for the tests that ran successfully
        resultsdir = self.guest.execguest("ls -1 .phoronix-test-suite/test-results | head -n 1").strip()
        resultsfile = "/root/.phoronix-test-suite/test-results/%s/test-1.xml" % (resultsdir)
        sftp = self.guest.sftpClient()
        sftp.copyFrom(resultsfile, '%s/test-1.xml' % (xenrt.TEC().getLogdir()))
