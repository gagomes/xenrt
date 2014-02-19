import xenrt
import libperf
import string

class TCPoolOverhead(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCPoolOverhead")
        self.cleanupafter = False

    def disableASlave(self):
        host = None
        # Pick a host at random
        for h in self.normalHosts:
            host = self.tec.gec.registry.hostGet(h)

            if host.isEnabled() and host != self.pool.master:
                break

        if host:
            xenrt.TEC().comment("Disabling host %s" % host.getName())
            host.disable()

    def enableAllHosts(self):
        for h in self.normalHosts:
            host = self.tec.gec.registry.hostGet(h)

            if not host.isEnabled():
                xenrt.TEC().comment("Enabling host %s" % host.getName())
                host.enable()

    def prepare(self, arglist=None):
        self.parseArgs(arglist)

        self.initialiseHostList()
        self.configureAllHosts()

        self.guest = self.createHelperGuest()

        self.goldvm = self.importGoldVM(self.goldimagesruuid, self.desktopimage, self.desktopvmname, self.desktopvmnetwork, registerForCleanup=self.cleanupafter)
        self.hostname = self.host.getIP()

    def run(self, arglist=None):
        # Parse arguments
        vmsperhost = 10
        minnumhostsstr = "all" # e.g. "1"
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "vmsperhost":
                vmsperhost = int(l[1])
            elif l[0] == "minnumhosts":
                minnumhostsstr = l[1]

        numhosts = len(self.normalHosts)
        if minnumhostsstr == "all":
            minnumhosts = numhosts
        else:
            minnumhosts = int(minnumhostsstr)

        # Repeat until you've just got the master
        while numhosts >= minnumhosts:
            xenrt.TEC().comment("Starting test run with numhosts=%d" % numhosts)

            # Create numhosts * 10 MPS VMs
            numvms = numhosts * vmsperhost
            xenrt.TEC().logverbose("vmsperhost=%s so numvms=%d" % (vmsperhost, numvms))
            clones = self.createMPSVMs(numvms, self.goldvm)
            self.configureAllVMs()
            
            stem = "%d-perhost-%d-hosts" % (vmsperhost, numhosts)
            bootwatcherLogfile = libperf.createLogName("bootwatcher-%s" % stem)
            starterLogfile = libperf.createLogName("starter-%s" % stem)
            xenrt.TEC().comment("bootwatcher logfile for %d hosts (running on %s), %d VMs per host: %s" % (numhosts, self.hostname, vmsperhost, bootwatcherLogfile))
            xenrt.TEC().comment("starter logfile for %d hosts (running on %s), %d VMs per host: %s" % (numhosts, self.hostname, vmsperhost, starterLogfile))
        
            # Time starting them
            self.timeStartVMs(numhosts, clones, starterLogfile, bootwatcherLogfile)

            if numhosts > minnumhosts:
                # Destroy them
                self.destroyVMs(clones)

                # Disable a host
                self.disableASlave()
                xenrt.TEC().comment("Number of hosts is now %d and minimum is %d" % (numhosts, minnumhosts))

            numhosts = numhosts - 1

    def postRun(self):
        xenrt.TEC().logverbose("Enabling all hosts")
        self.enableAllHosts()
        self.finishUp()


