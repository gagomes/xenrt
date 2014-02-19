import xenrt
import libperf
import string
import XenAPI
import traceback
import time

# Very similar to TCTimeVMStarts
class TCTimeVMCycles(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCTimeVMCycles")
        #TODO: Use getArgument
        self.numdesktops = 1000 # 800 = 16 hosts x 50 VMs

    def prepare(self, arglist=None):
        # Parse generic arguments
        self.parseArgs(arglist)

        # Parse arguments relating to this test
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "numdesktops":
                self.numdesktops = int(l[1])

        self.initialiseHostList()
        self.configureAllHosts()

        self.guest = self.createHelperGuest()

        self.goldvm = self.importGoldVM(self.goldimagesruuid, self.desktopimage, self.desktopvmname, self.desktopvmnetwork)

    def run(self, arglist=None):
        # Create the clones, recording how long it takes to do so
        self.clones = self.createMPSVMs(self.numdesktops, self.goldvm)
        self.configureAllVMs()

        # Set up log files for REQ226
        bootwatcherLogfile = libperf.createLogName("bootwatcher")
        starterLogfile = libperf.createLogName("starter")
        shutdownwatcherLogfile = libperf.createLogName("shutdownwatcher")
        xenrt.TEC().comment("bootwatcher logfile: %s" % bootwatcherLogfile)
        xenrt.TEC().comment("starter logfile: %s" % starterLogfile)
        xenrt.TEC().comment("shutdownwatcher logfile: %s" % shutdownwatcherLogfile)

        # Begin to collect stats from NetApp, for REQ246,248
        self.startNetAppStatGather()
        
        # Start watching for shutdowns
        sdw = ShutdownWatcher(self, len(self.clones), shutdownwatcherLogfile)
        sdw.start()
        xenrt.TEC().logverbose("started shutdownwatcher")

        # Now start the VMs, for REQ226
        numthreads = len(self.normalHosts)
        self.timeStartVMs(numthreads, self.clones, starterLogfile, bootwatcherLogfile, awaitParam=None) # awaitParam=None -> don't use a BootWatcher

        # Wait for all the VMs to shut down
        # TODO this is broken
        sdw.join()
        xenrt.TEC().logverbose("shutdownwatcher has completed")
        if sdw.error:
            raise xenrt.XRTError("shutdownwatcher completed with error")

        # Now gather the final stats from the NetApp, for REQ246,248
        stats = self.finishNetAppStatGather()
        netappLogFile = libperf.createLogName("netapp")
        libperf.outputToResultsFile(netappLogFile, stats)

    def postRun(self):
        self.finishUp()

class ShutdownWatcher(xenrt.XRTThread):
    def __init__(self, tc, numvms, logFile):
        xenrt.XRTThread.__init__(self)
        xenrt.TEC().logverbose("constructing shutdownwatcher to await %d shutdowns" % numvms)

        self.host = tc.host
        self.tc = tc
        self.logFile = logFile

        self.num_seen_shutdowns = 0
        self.num_expected_shutdowns = numvms

        self.seenrunning = {}
        self.seenshutdown = {}
        
        self.complete = False
        self.error = False
        self.previousShutdownTime = None
        self.maxTimeToWait = 3600 # time to wait for a bit since seeing previous shutdown

    def processVm(self, session, vm, snapshot):
        xenrt.TEC().logverbose("shutdownwatcher processing VM %s" % vm)
        xenrt.TEC().logverbose("vm %s has power_state=%s and seenrunning=%s and seenshutdown=%s" % (vm, snapshot['power_state'], vm in self.seenrunning, vm in self.seenshutdown))

        if snapshot['power_state'] == "Running":
            self.seenrunning[vm] = True
            self.seenshutdown[vm] = False
            xenrt.TEC().logverbose("vm %s is running" % vm)
        elif snapshot['power_state'] == "Halted" and vm in self.seenrunning and not self.seenshutdown[vm]:
            xenrt.TEC().logverbose("vm %s is halted and was previously running and not previously shut down" % vm)
            t = libperf.formattime(libperf.timenow())
            name = snapshot['name_label']
            line = "%s %s" % (name, t)
            xenrt.TEC().logverbose("SHUTDOWN %s" % line)
            libperf.outputToResultsFile(self.logFile, line)
            self.previousShutdownTime = time.time()
            self.seenshutdown[vm] = True

            self.num_seen_shutdowns = self.num_seen_shutdowns + 1
            if self.num_seen_shutdowns == self.num_expected_shutdowns:
                self.complete = True
            xenrt.TEC().logverbose("seen %d shutdowns of %d expected, hence complete=%s" % (self.num_seen_shutdowns, self.num_expected_shutdowns, self.complete))
    
    def run(self):
        xenrt.TEC().logverbose("shutdownwatcher running")
        n = libperf.formattime(libperf.timenow())
        zero = "zero"
        line = "%s %s %s" % (zero, n, n)
        xenrt.TEC().logverbose("SHUTDOWN %s" % line)
        libperf.outputToResultsFile(self.logFile, line)

        session = self.host.getAPISession(secure=False)

        try:
            self.watchEventsOnVm(session)
        finally:
            self.host.logoutAPISession(session)

    def watchEventsOnVm(self, session):
        # Register for events on all classes:
        def register():
            xenrt.TEC().logverbose("shutdownwatcher registering for events")
            session.xenapi.event.register(["VM"])
            all_vms = session.xenapi.VM.get_all_records()
            for vm in all_vms.keys():
                self.processVm(session, vm, all_vms[vm])

        register()
        while not self.complete:
            # Event loop
            try:
                xenrt.TEC().logverbose("shutdownwatcher calling event.next()")
                events = session.xenapi.event.next()
                for event in events:
                    xenrt.TEC().logverbose("shutdownwatcher received event op='%s' class='%s' ref='%s'" % (event['operation'], event['class'], event['ref']))
                    if event['class'] == 'vm' and event['operation'] == 'mod':
                        self.processVm(session, event['ref'], event['snapshot'])
                        continue

            except XenAPI.Failure, e:
                xenrt.TEC().logverbose("** exception: e = [%s]" % e)
                xenrt.TEC().logverbose("** exception: e.details = [%s]" % e.details)
                if len(e.details) > 0 and e.details[0] == 'EVENTS_LOST':
                    xenrt.TEC().logverbose("** Caught EVENTS_LOST")
                    session.xenapi.event.unregister(["VM"])
                    register()
                else:
                    xenrt.TEC().logverbose("** Non-EVENTS_LOST 'failure' exception: %s" % traceback.format_exc())
                    xenrt.TEC().logverbose("** re-registering anyway")
                    session.xenapi.event.unregister(["VM"])
                    register()
            except:
                xenrt.TEC().logverbose("** fatal exception: %s" % traceback.format_exc())
                self.complete = True
                self.error = True

            # See how long we've waited for
            if (not self.previousShutdownTime is None) and (time.time() - self.previousShutdownTime > self.maxTimeToWait):
                xenrt.TEC().logverbose("** TIMEOUT waiting for next shutdown: only seen %d of %d shutdowns" % (self.num_seen_shutdowns, self.num_expected_shutdowns))
                self.complete = True
                self.error = True

