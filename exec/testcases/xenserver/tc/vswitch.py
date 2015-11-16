import math, threading, re, time, string, subprocess, xml.dom.minidom, copy, os
import xenrt
from xenrt.lazylog import step, comment, log, warning
import socket,random,sys,time

class _VSwitch(xenrt.TestCase):
    """Base class for vswitch tests."""
    DURATION         = 5
    NETPERF_TESTS    = ["TCP_STREAM",
                        "TCP_MAERTS",
                        "UDP_STREAM"]
    PORT             = 32768
    sdkhosts         = []
    wdir             = None

    def pairs(self, list):
        return [ (list[x], list[y]) \
                    for x in xrange(len(list)) \
                        for y in xrange(len(list)) \
                            if not x == y ]

    def _internalNetperf(self, test, source, target, size=None):
        # netperf between two guest VMs (source and target)
         xenrt.TEC().logverbose("Running (internal): netperf %s -> %s (%s)" %
                                (source.getIP(), target, test))
         try:
             if size == None:
                 result = source.execguest("netperf -t %s -H %s -p %s -l %s -v 0 -P 0 -f k" %
                                           (test, target, self.PORT, self.DURATION),
                                           timeout=2*self.DURATION, useThread=True).strip()
             else:
                 result = source.execguest("netperf -t %s -H %s -p %s -l %s -v 0 -P 0 -f k -- -m %d" %
                                           (test, target, self.PORT, self.DURATION, size),
                                           timeout=2*self.DURATION, useThread=True).strip()

         except Exception, e:
             xenrt.TEC().warning("Internal netperf failed: %s" % e)
             result = 0
         return ("Internal:" + test, float(result))

    def _externalNetperf(self, test, source, size=None):
        # netperf between a guest VM and a test peer
        xenrt.TEC().logverbose("Running (external): netperf %s -> %s (%s)" %
                               (source.getIP(), self.peer.getAddress(), test))
        try:
            if size == None:
                result = source.execguest("netperf -t %s -H %s -p %s -l %s -v 0 -P 0 -f k" %
                                      (test, self.peer.getAddress(), self.PORT, self.DURATION),
                                       timeout=2*self.DURATION, useThread=True).strip()
            else:
                result = source.execguest("netperf -t %s -H %s -p %s -l %s -v 0 -P 0 -f k -- -m %d" %
                                      (test, self.peer.getAddress(), self.PORT, self.DURATION, size),
                                       timeout=2*self.DURATION, useThread=True).strip()
        except Exception, e:
            xenrt.TEC().logverbose("External netperf failed: %s" % e)
            result = 0
        return ("External:" + test, float(result))

    def _internalICMP(self, source, target):
        xenrt.TEC().logverbose("Running (internal): ping %s -> %s" % (source.getIP(), target))
        try:
            data = source.execguest("ping -w %s %s" % (self.DURATION, target),
                                                       timeout=2*self.DURATION, useThread=True)
            result = xenrt.mean(map(float, re.findall("time=([\d\.]+)", data)))
        except Exception, e:
            xenrt.TEC().logverbose("Internal ping failed: %s" % e)
            result = 0
        return ("Internal:ICMP", result)

    def _externalICMP(self, source):
        xenrt.TEC().logverbose("Running (external): ping %s -> %s" %
                               (source.getIP(), self.peer.getAddress()))
        try:
            data = source.execguest("ping -w %s %s" % (self.DURATION,
                                                       self.peer.getAddress()),
                                                       timeout=2*self.DURATION, useThread=True)
            result = xenrt.mean(map(float, re.findall("time=([\d\.]+)", data)))
        except Exception, e:
            xenrt.TEC().logverbose("External ping failed: %s" % e)
            result = 0
        return ("External:ICMP", result)

    def prepareGuests(self, guests, netperf_config = None):
        for g in guests:
            xenrt.TEC().logverbose("Initialising netperf on %s..." % (g.getName()))
            try: g.execguest("killall netserver")
            except: pass
            try: g.execguest("killall netperf")
            except: pass
            try: g.execguest("which netserver")
            except:
                if netperf_config != None:
                    g.installNetperf(config_params = netperf_config)
                else:
                    g.installNetperf()

            if not g.windows:
                g.execguest("netserver -p %s" % (self.PORT))
            else:
                g.xmlrpcExec("START C:\\netserver -p %s" % self.PORT)
            xenrt.TEC().logverbose("Initialised netperf on %s." % (g.getName()))

    def preparePeer(self):
        xenrt.TEC().logverbose("Initialising netperf on peer...")
        self.peer = xenrt.NetworkTestPeer(shared=True)
        try:
            pids = self.peer.runCommand("pgrep -f \"netserver -p %s\"" % (self.PORT)).split()
            for pid in pids:
                self.peer.runCommand("kill -9 %s" % (pid.strip()))
        except Exception, e:
            pass
        self.peer.runCommand("netserver -p %s" % (self.PORT))
        xenrt.TEC().logverbose("Initialised netperf on peer.")

    def enterMaintenanceMode(self):
        for host in self.pool.getHosts():
            self.pool_map.append(host)
            host.disable()
            # power off VMs
            host.running_vms = []
            for vm_name in host.listGuests(True):
                host.running_vms.append(vm_name)
                guest = self.getGuestFromName(vm_name)
                guest.shutdown()

    def exitMaintenanceMode(self):
        for host in self.pool_map:
            host.enable()
        # bring the vms back up
        for host in self.pool_map:
            for vm_name in host.running_vms:
                guest = self.getGuestFromName(vm_name)
                guest.start()
            host.running_vms = []
        self.pool_map = []

    def poolwideVswitchDisable(self):
        for host in self.pool_map:
            host.disablevswitch()
            
    def poolwideVswitchEnable(self):
        for host in self.pool_map:
            host.enablevswitch()
            
    def checkNetwork(self, guests, tag):
        try:
            self.prepareGuests(guests)
            self.preparePeer()
            guestPair = self.pairs(guests)
            log("Identified %d guest pair(s). \n%s" % (len(guestPair), 
                    "\n".join(["(%s,%s)"%(g1.getName(), g2.getName()) for (g1,g2) in guestPair]) ))
            
            taskArgs = [(g1, g2.getIP()) for (g1,g2) in guestPair]
            internalNetperfThreads =  [ xenrt.PTask(self._internalNetperf, test=test, source=source, target=target) 
                                        for test in self.NETPERF_TESTS 
                                        for (source, target) in taskArgs ]
            externalNetperfThreads =  [ xenrt.PTask(self._externalNetperf, test=test, source=source) 
                                        for test in self.NETPERF_TESTS 
                                        for source in guests ]
            internalICMPThreads =     [ xenrt.PTask(self._internalICMP, source=source, target=target) 
                                        for (source, target) in taskArgs ]
            externalICMPThreads =     [ xenrt.PTask(self._externalICMP, source=source) 
                                        for source in guests ]
            testThreads   =   internalNetperfThreads + externalNetperfThreads + internalICMPThreads + externalICMPThreads
            log("Number of Test threads  = %d. Threads: \n%s" % (len(testThreads),
                    "\n".join(["%s(%s,%s)" % (th.func, th.args, th.kwargs) for th in testThreads])))
            
            result = xenrt.pfarm(testThreads, interval=1, exception=False)
            xenrt.TEC().logverbose("Results: \n%s" % ("\n".join(["%s: %s" % (test,val) for (test,val) in result])))
            
            keys = set(map(lambda (x,y):x, result))
            values = [ xenrt.mean([ y for (x,y) in result if x == z]) for z in keys ]
            data = dict(zip(keys,values))
            for key in data:
                xenrt.TEC().value("%s:%s" % (tag, key), data[key])
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose("Failure data: %s" % (e.data))
            raise e

    def _hostOperation(self, host, operation, *args, **kwargs):
        resident = host.listGuests(running=True)
        xenrt.TEC().logverbose("Guests resident on %s: %s" % (host.getName(), resident))
        if len(self.hosts) > 1:
            xenrt.TEC().logverbose("Evacuating %s." % (host.getName()))
            host.evacuate()
        else:
            xenrt.TEC().logverbose("Shutting down guests.")
            for guest in self.guests:
                guest.shutdown()
        operation(*args, **kwargs)
        xenrt.TEC().logverbose("Enabling host after operation.")
        host.enable()
        self._restore(host, resident)

    def _restore(self, host, guests):
        for guest in self.guests:
            if guest.getName() in guests:
                if guest.getState() == "UP":
                    xenrt.TEC().logverbose("Moving %s back on to %s." % (guest.getName(), host.getName()))
                    guest.migrateVM(host, live="true")
                else:
                    xenrt.TEC().logverbose("Restarting guest %s." % (guest.getName()))
                    if guest.getState() == "DOWN":
                        guest.start()

    def reboot(self, host):
        xenrt.TEC().logverbose("Rebooting %s." % (host.getName()))
        self._hostOperation(host, host.reboot)

    def getGuestFromName(self, name):
        for guest in self.guests:
            if guest.getName() == name:
                return guest
        raise xenrt.XRTError("Failed to find guest with name %s" % (name))

    def setupGuestTcpDump(self, guest):
        guest.installPackages(["tcpdump"])

    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        self.host = self.pool.master
        self.hosts = self.pool.getHosts()
        self.guests = []
        self.pool_map=[]
        for host in self.hosts:
            self.guests = self.guests + host.guests.values()


class TC11398(_VSwitch):
    """
    vSwitch Enable/Disable

    1. Enable the vSwitch across a pool.
    2. Check ICMP, TCP and UDP traffic between all VMs is unaffected.
    3. Check external ICMP, TCP and UDP traffic is unaffected for all VMs.
    4. Disable the vSwitch across a pool.
    5. Check ICMP, TCP and UDP traffic between all VMs is unaffected.
    6. Check external ICMP, TCP and UDP traffic is unaffected for all VMs.

    """

    def run(self, arglist):
        self.checkNetwork(self.guests, "vswitch-before")
        self.poolwideVswitchDisable()
        self.checkNetwork(self.guests, "bridge")

    def postRun(self):
        self.poolwideVswitchEnable()

class TC11399(TC11398):
    """
    vSwitch xenbugtool

    1. Enable the vSwitch across a pool.
    2. Generate a xenbugtool and check it contains the vSwitch logs.
    3. Disable the vSwitch across a pool.
    4. Generate a xenbugtool.

    """

    VSWITCHLOGS = ["/etc/openvswitch/conf.db"]

    def checkBugtool(self, tag):
        xenrt.TEC().logverbose("Checking bugtool for vswitch logs. (%s)" % (tag))
        for host in self.hosts:
            bugtool = host.getBugTool()
            files = xenrt.command("tar -tf %s" % (bugtool)).split()
            for log in self.VSWITCHLOGS:
                entry = filter(re.compile(log).search, files)
                if not entry:
                    raise xenrt.XRTFailure("Log file %s not found in bugtool." % (log))

    def run(self, arglist):
        self.checkBugtool("before")
        TC11398.run(self, [])
        self.checkBugtool("after")

class TC11403(_VSwitch):
    """
    Promote Slave

    1. Promote a slave to master of a pool.
    2. Check ICMP, TCP and UDP traffic between all VMs is unaffected.
    3. Check external ICMP, TCP and UDP traffic is unaffected for all VMs.

    """

    def run(self, arglist):
        self.checkNetwork(self.guests, "before-promotion")
        self.pool.designateNewMaster(self.pool.getSlaves()[0])
        self.checkNetwork(self.guests, "after-promotion")

class TC11404(_VSwitch):
    """
    Restart master

    1. Restart the pool master.
    2. Check ICMP, TCP and UDP traffic between all VMs is unaffected.
    3. Check external ICMP, TCP and UDP traffic is unaffected for all VMs.

    """

    def run(self, arglist):
        self.checkNetwork(self.guests, "before-reboot")
        self.reboot(self.pool.master)
        self.checkNetwork(self.guests, "after-reboot")

class TC11405(_VSwitch):
    """
    Restart slave

    1. Restart a pool slave.
    2. Check ICMP, TCP and UDP traffic between all VMs is unaffected.
    3. Check external ICMP, TCP and UDP traffic is unaffected for all VMs.

    """

    def run(self, arglist):
        self.checkNetwork(self.guests, "before-slave-reboot")
        self.reboot(self.pool.getSlaves()[0])
        self.checkNetwork(self.guests, "after-slave-reboot")

class TC11406(_VSwitch):
    """
    Add/remove host

    1. Remove a slave from the pool.
    2. Check ICMP, TCP and UDP traffic between all VMs is unaffected.
    3. Check external ICMP, TCP and UDP traffic is unaffected for all VMs.
    4. Rejoin the slave to the pool.
    5. Check ICMP, TCP and UDP traffic between all VMs is unaffected.
    6. Check external ICMP, TCP and UDP traffic is unaffected for all VMs.

    """

    def run(self, arglist):
        slave = self.pool.getSlaves()[0]
        self.checkNetwork(self.guests, "before-eject")
        resident = slave.listGuests(running=True)
        slave.evacuate()
        self.pool.eject(slave)
        self.checkNetwork(self.guests, "after-eject")
        self.pool.addHost(slave)
        self._restore(slave, resident)
        self.checkNetwork(self.guests, "after-rejoin")

class TC11407(_VSwitch):
    """
    Logging

    1. Increase vSwitch log level and check that more information is logged.
    2. Decrease vSwitch log level and check that less information is logged.
    3. Direct vSwitch logs to console and check that they appear there. 
    4. Cause the conditions for logfile rotation and check that they occur.
    5. Check the same for vswitch logfile 

    """
    # 3-5 are still unimplemented

    def setvSwitchLogLevel(self, level):
        self.host.setvSwitchLogLevel(level)
        data = self.host.getvSwitchLogLevel()
        entries = re.findall("(\w+)\s+(\w+)\s+(\w+)\s+(\w+)", data)
        for component,console,syslog,logfile in entries:
            newcomponent, location, priority = level.split(":")
            if location == "CONSOLE":
                expected = console
            if location == "SYSLOG":
                expected = syslog
            if location == "FILE":
                expected = logfile
            if newcomponent == "ANY" or newcomponent == component:
                if not expected == priority:
                    raise xenrt.XRTFailure("Setting %s log level to %s failed." % (location, priority))

    def checkForCoverageLog(self, location):
        xenrt.TEC().logverbose("Checking for vSwitch logs in %s." % (location))
        start = time.gmtime(xenrt.timenow())
        xenrt.TEC().logverbose("Start time: %s" % (start))
        self.host.vSwitchCoverageLog()
        if location == "SYSLOG":
            data = self.host.execdom0("tail -n 500 /var/log/daemon.log")
        if location == "CONSOLE":
            data = string.join(self.host.machine.getConsoleLogHistory())
        times = re.findall("(\w+\s+\d+ [\d:]+).*coverage.*", data)
        times = [ "%s %s"  % (start[0], x) for x in times ]
        xenrt.TEC().logverbose("Found: %s" % (times))
        times = map(lambda x:time.strptime(x, "%Y %b %d %H:%M:%S"), times)
        if filter(lambda x:x[:-1] >= start[:-1], times):
            return True
        else:
            return False

    def run(self, arglist):
        self.setvSwitchLogLevel("ANY:SYSLOG:WARN")
        if not self.checkForCoverageLog("SYSLOG"):
            raise xenrt.XRTFailure("WARN messages not found in syslog.")
        self.setvSwitchLogLevel("ANY:SYSLOG:ERR")
        if self.checkForCoverageLog("SYSLOG"):
            raise xenrt.XRTFailure("WARN messages still found in syslog.")

    def postRun(self):
        _VSwitch.postRun(self)
        self.setvSwitchLogLevel("ANY:SYSLOG:ERR")

class TC11408(_VSwitch):
    """
    Core dump

    1. Configure vSwitch to core dump to a specific location.
    2. Cause vSwitch to core dump.
    3. Check that the core dump appeared in the expected location.

    """

    LOCATION = "/var/xen/openvswitch"

    def run(self, arglist):
        xenrt.TEC().logverbose("Removing any existing core dumps.")
        self.host.execdom0("rm -f %s/core.*" % (self.LOCATION))
        xenrt.TEC().logverbose("Triggering core dump.")
        self.host.execdom0("kill -SEGV $(cat /var/run/openvswitch/ovs-vswitchd.pid)")
        try:
            self.host.execdom0("ls %s/core.*" % (self.LOCATION))
        except Exception, e:
            xenrt.TEC().logverbose("Exception: %s" % e)
            raise xenrt.XRTFailure("No core dump found in %s." % (self.LOCATION))

    def postRun(self):
        _VSwitch.postRun(self)
        self.host.execdom0("rm -f %s/core.*" % (self.LOCATION))

class TC11409(_VSwitch):
    """
    Restart host.

    1. Restart a standalone host with vSwitch enabled.
    2. Check ICMP, TCP and UDP traffic between all VMs is unaffected.
    3. Check external ICMP, TCP and UDP traffic is unaffected for all VMs.

    """

    def run(self, arglist):
        self.checkNetwork(self.guests, "before-reboot")
        self.reboot(self.host)
        self.checkNetwork(self.guests, "after-reboot")

class TC11585(_VSwitch):

    """
    VM Off Host Performance

    Gain performance metrics for network throughput between VM and a remote endpoint
    on both vSwitch and Linux Bridge. There should be a degredation of less than 1%
    on the vSwitch

    It is questionable as to the use of testing Rx - This will be tested as part of
    VM-VM communication and is currently limtted by XenServer not the bridge or switch.

    Hence only Tx Is tested here
    """

    def prepare(self, arglist):
        _VSwitch.prepare(self, arglist)
        self.testVM = self.guests[0]
        self.prepareGuests([self.testVM])
        self.preparePeer()

    def run(self, arglist):
        percentage = 0
        self.DURATION=600
        result = self._externalNetperf("TCP_STREAM", self.testVM)
        xenrt.TEC().logverbose(result)
        vSwitchPerformance = result[1]

        self.host.disablevswitch()
        self.prepareGuests([self.testVM])

        result = self._externalNetperf("TCP_STREAM", self.testVM)
        xenrt.TEC().logverbose(result)
        bridgePerformance = result[1]

        percentage = vSwitchPerformance / bridgePerformance * 100
        if (percentage < 99):
            raise xenrt.XRTFailure("vSwitch external network performance is only %d%% of bridge performance" % percentage)
        xenrt.TEC().logverbose("PASS: vSwitch external network performance is %d%% of bridge performance" % percentage)

    def postRun(self):
        self.host.enablevswitch()

class TC11586(_VSwitch):

    """
    VM-VM Network Performance

    Gain performance metrics for network throughput between two VMs on the same host
    using both vSwitch and Linux Bridge. There should not be a reduction > 1% of
    throughput on the vSwitch.

    """

    def prepare(self, arglist):
        _VSwitch.prepare(self, arglist)
        self.prepareGuests(self.guests)

    def run(self, arglist):
        percentage = 0
        self.DURATION=600

        result = self.guests[0].execguest("netperf -t TCP_STREAM -H %s -p %s -l %s -i 10,3 -I 95,2 -v 0 -P 0 -f k" %
                                      (self.guests[1].getIP(), self.PORT, self.DURATION), timeout=10*self.DURATION).strip()
        xenrt.TEC().logverbose(result)
        vSwitchPerformance = result

        self.host.disablevswitch()
        self.prepareGuests(self.guests)

        result = self.guests[0].execguest("netperf -t TCP_STREAM -H %s -p %s -l %s -i 10,3 -I 95,2 -v 0 -P 0 -f k" %
                                      (self.guests[1].getIP(), self.PORT, self.DURATION), timeout=10*self.DURATION).strip()

        xenrt.TEC().logverbose(result)
        bridgePerformance = result

        percentage = float(vSwitchPerformance) / float(bridgePerformance) * 100
        if (percentage < 99):
            raise xenrt.XRTFailure("vSwitch internal network performance is only %d%% of bridge performance" % percentage)
        xenrt.TEC().logverbose("PASS: vSwitch internal network performance is %d%% of bridge performance" % percentage)

    def postRun(self):
        self.host.enablevswitch()

class TC11539(_VSwitch):
    """
    N Bridges on Host
    Create N Bridges on a vSwitch enabled host
    Generate Traffic
    """
    myguests = []
    new_nets = []
    new_name = []
    hangingGuest = [0, 0]
    def prepare(self, arglist):
        _VSwitch.prepare(self, arglist)
        self.prepareGuests(self.guests)
        self.myguests = self.host.listGuests()
        # create interface file backups
        for j in range(2):
            targetguest = self.host.guests[self.myguests[j]]
            targetguest.preCloneTailor()
            targetguest.execguest("cp /etc/network/interfaces /root/interfaces")

    def run(self, arglist):
        self.nbrOfBridges = 128
        if not isinstance(self.host, xenrt.lib.xenserver.CreedenceHost):
            self.nbrOfBridges = 100
        
        # remember we have one working bridge already
        for i in range(self.nbrOfBridges-1):
            name = "nw%d" % i
            xenrt.TEC().logverbose("Creating network %s" % name)
            uuid = self.host.createNetwork(name)
            self.new_nets.append(uuid)
            bridge = self.host.genParamGet("network", uuid, "bridge")
            self.new_name.append(bridge)

        # create VIF entries on each test vm
        for j in range(2):
            targetguest = self.host.guests[self.myguests[j]]

            targetguest.execguest("echo 'auto eth1' >> "
                                  "/etc/network/interfaces")
            targetguest.execguest("echo 'iface eth1 inet static' >> "
                                  "/etc/network/interfaces")
            targetguest.execguest("echo 'address 192.168.1.%u' >> "
                                  "/etc/network/interfaces" % (j + 1))
            targetguest.execguest("echo 'netmask 255.255.255.0' >> "
                                  "/etc/network/interfaces")

        # loop through bridges
        for i in range(self.nbrOfBridges - 1):
            # create and bring up VIFs for master's 1st 2 VMs
            for j in range(2):
                targetguest = self.host.guests[self.myguests[j]]
                targetguest.createVIF(eth="eth1", bridge=self.new_name[i], mac=None, plug=True)
                # this seems to take longer in the lab than its does at the local test machine
                time.sleep(10)
                targetguest.execguest("ifup eth1")
                # keep a reference in case we fail
                self.hangingGuest[j] = targetguest

            # Give poor old interfaces time to come up - they have prooved quite slow
            time.sleep(5)

            # test the bridge is working
            result = self._internalICMP(self.host.guests[self.myguests[0]], "192.168.1.2")
            if (result[1] == 0):
                raise xenrt.XRTFailure("Failed to ping across bridge %u" % i)

            # destroy the vms on this bridge
            for j in range(2):
                targetguest = self.host.guests[self.myguests[j]]
                targetguest.execguest("ifdown eth1")
                targetguest.unplugVIF("eth1")
                targetguest.removeVIF("eth1")
                self.hangingGuest[j] = 0

            # give time to delete too
            time.sleep(5)

        xenrt.TEC().logverbose("PASS: Pinged across %d bridges on a single host" % self.nbrOfBridges)

    def postRun(self):
        # restore interface file backups
        for j in range(2):
            targetguest = self.host.guests[self.myguests[j]]
            targetguest.execguest("cp /root/interfaces /etc/network/interfaces")
            targetguest.execguest("rm /root/interfaces")
            if self.hangingGuest[j] != 0:
                try: self.hangingGuest[j].execguest("ifdown eth1")
                except: pass
                try: self.hangingGuest[j].unplugVIF("eth1")
                except: pass
                try: self.hangingGuest[j].removeVIF("eth1")
                except: pass

        # destroy the bridges
        for uuid in self.new_nets:
            self.host.removeNetwork(None, uuid)

class TC11515(_VSwitch):
    """
    Rolling Downgrade

    On a pool of vSwitch Hosts
    Put the pool into maintenance mode and on each host:
        chkconfig openvswitch off
        echo bridge > /etc/xensource/network.conf
    Bring pool back out of maintenance mode
    Perform basic networking tests to ensure that the bridges are working
    """
    # storage for the state of the pool before entering maintenance mode

    def prepare(self, arglist):
        _VSwitch.prepare(self, arglist)

    def run(self, arglist):
        # sanity check the network
        self.checkNetwork(self.guests, "vswitch-before")
        self.poolwideVswitchDisable()
        # check the network is working again
        self.checkNetwork(self.guests, "bridge")

    def postRun(self):
        self.poolwideVswitchEnable()

class TC11512(TC11515):
    """
    Rolling Upgrade

    On a pool of non-vSwitch Hosts
    Put the pool into maintenance mode and on each host:
        chkconfig openvswitch on
        echo openvswitch > /etc/xensource/network.conf
    Bring pool back out of maintenance mode
    Perform basic networking tests to ensure that the vSwitches are working
    """

    vswitch_enabled_at_start = False

    def prepare(self, arglist):
        TC11515.prepare(self, arglist)
        # laurie runs with vswitch enabled by default
        if (self.host.special['Network subsystem type'] == "vswitch"):
            self.poolwideVswitchDisable()
            self.vswitch_enabled_at_start = True

    def run(self, arglist):
        # sanity check the network
        self.checkNetwork(self.guests, "vswitch-before")
        self.poolwideVswitchEnable()
        # check the network is working again
        self.checkNetwork(self.guests, "bridge")

    def postRun(self):
        if (self.vswitch_enabled_at_start != True):
            self.poolwideVswitchDisable()


class TC11561(_VSwitch):
    """
    VLAN Interfaces

    Ensure that an interface configured to a specific VLAN only forwards traffic for that VLAN
    """

    slave_ind = 0
    host_ind = 0
    slave = 0


    def startTcpdump(self, guest, ifname, targetIP):

        param = "tcpdump -i %s host %s -nqt &> mycap & echo $!" % (ifname, targetIP)

        return guest.execguest(param).strip() # return pid



    def collectTcpdumpResults(self, guest, pid):
        # kill the tcpdump process
        guest.execguest("kill %s" % (pid))
        # return number of ICMP requests
        return guest.execguest("grep 'ICMP echo request' mycap|awk 'END {print NR}'")

    def startHostTcpdump(self, host, ifname, targetIP):
        param = "tcpdump -i %s host %s -nqt &> mycap & echo $!" % (ifname, targetIP)
        return host.execdom0(param).strip() # return pid

    def collectHostTcpdumpResults(self, host, pid):
        # kill the tcpdump process
        host.execdom0("kill %s" % (pid))
        # return number of ICMP requests
        return host.execdom0("grep 'ICMP echo request' mycap|awk 'END {print NR}'")


    def _listen(self, guest, targetIP):
        result = guest.execguest("tcpdump host %s" % targetIP)
        return result

    def prepare(self, arglist):
        _VSwitch.prepare(self, arglist)
        self.prepareGuests(self.guests)

        # it has proved dangerous to identify the master as being host[0] and the slave as host[1]
        # the master is actually self.host and there are only two hosts in the pool

        i = 0
        for host in self.hosts:
            if host.getName() != self.host.getName():
                self.slave = host
                self.slave_ind = i
                xenrt.TEC().logverbose("Slave is %d" % (i))
            else:
                self.host_ind = i
                xenrt.TEC().logverbose("Master is %d" % (i))
            i += 1


    def run(self, arglist):
        self.vlansToRemove = []

        vlans = self.host.availableVLANs()
        xenrt.TEC().logverbose("Number of vlans = %d" % (len(vlans)))

        if len(vlans) == 0:
            xenrt.TEC().skip("No VLANs defined for host")
            return

        vlan, subnet, netmask = self.host.getVLAN('VR02')
        vlanpif = self.host.parseListForUUID("pif-list", "VLAN", vlan)
        vlan_nw_uuid = self.host.genParamGet("pif", vlanpif, "network-uuid")

        xenrt.TEC().logverbose("vlan %d, subnet %s, netmask %s" % (vlan, subnet, netmask))

        vlan_bridge = self.host.genParamGet("network", vlan_nw_uuid, "bridge")
        vlanguest = [self.host.createGenericLinuxGuest(bridge=vlan_bridge), self.host.createGenericLinuxGuest(bridge=vlan_bridge)]

        vlanguest.append( self.slave.createGenericLinuxGuest(bridge=vlan_bridge))

        vlanguestip = []
        self.uninstallOnCleanup(vlanguest[0])
        self.uninstallOnCleanup(vlanguest[1])
        self.uninstallOnCleanup(vlanguest[2])


        xenrt.TEC().logverbose("Number of vlanguests = %d" % (len(vlanguest)))

        # Check VLAN VM 1

        vlanguest[0].check()
        vlanguest[0].checkHealth()
        if subnet and netmask:
            vlanguestip.append(vlanguest[0].getIP())
            if xenrt.isAddressInSubnet(vlanguestip[0], subnet, netmask):
                xenrt.TEC().comment("%s is in %s/%s" % (vlanguestip[0], subnet, netmask))
            else:
                xenrt.TEC().comment("%s is not in %s/%s" %
                                    (vlanguestip[0], subnet, netmask))
                raise xenrt.XRTFailure("VM IP address not from VLAN subnet")
        else:
            xenrt.TEC().comment("Skipping guest IP check")

        # Check VLAN VM 2
        vlanguest[1].check()
        vlanguest[1].checkHealth()
        if subnet and netmask:
            vlanguestip.append(vlanguest[1].getIP())
            if xenrt.isAddressInSubnet(vlanguestip[1], subnet, netmask):
                xenrt.TEC().comment("%s is in %s/%s" % (vlanguestip[1], subnet, netmask))
            else:
                xenrt.TEC().comment("%s is not in %s/%s" %
                                    (vlanguestip[1], subnet, netmask))
                raise xenrt.XRTFailure("VM IP address not from VLAN subnet")
        else:
            xenrt.TEC().comment("Skipping guest IP check")

        # Check VLAN VM 3
        vlanguest[2].check()
        vlanguest[2].checkHealth()
        if subnet and netmask:
            vlanguestip.append(vlanguest[2].getIP())
            if xenrt.isAddressInSubnet(vlanguestip[2], subnet, netmask):
                xenrt.TEC().comment("%s is in %s/%s" % (vlanguestip[2], subnet, netmask))
            else:
                xenrt.TEC().comment("%s is not in %s/%s" %
                                    (vlanguestip[2], subnet, netmask))
                raise xenrt.XRTFailure("VM IP address not from VLAN subnet")
        else:
            xenrt.TEC().comment("Skipping guest IP check")


        # A Bit of translation to make everything nice and easy to read
        xenrt.TEC().logverbose("Test 2 languest strings = %S")
        languests = [ self.host.guests["linux_0"], self.host.guests["linux_1"] ]
        xenrt.TEC().logverbose("Test 3")
        languestips = [languests[0].getIP(), languests[1].getIP()]
        xenrt.TEC().logverbose("Test 4")

        xenrt.TEC().logverbose("Host name %s" % self.host.getName())
        xenrt.TEC().logverbose("Slave name %s" % self.slave.getName())
        xenrt.TEC().logverbose("Hosts[0] name %s" % self.hosts[0].getName())
        xenrt.TEC().logverbose("Hosts[1] name %s" % self.hosts[1].getName())

        # linux 2 and 3 are on the slave
        remotelanguests = [self.slave.guests["linux_2"], self.slave.guests["linux_3"] ]
        remotelanguestips = [remotelanguests[0].getIP(), remotelanguests[1].getIP()]

        # Test the internal lan
        xenrt.TEC().logverbose("Test 1 - Basic internal LAN VM to LAN VM")
        count = self._internalICMP(languests[0], languestips[1])
        if (count[0] == 0):
            raise xenrt.XRTFailure("No communication betwwen internal lan VMs")

        # Test the external lan
        xenrt.TEC().logverbose("Test 2 - Basic External LAN VM to LAN VM")
        count = self._internalICMP(languests[0], remotelanguestips[0])
        if count[0] == 0:
            raise xenrt.XRTFailure("No communication betwwen external lan VMs")


        # Test between the internal VLAN VMs
        xenrt.TEC().logverbose("Test 3 Basic internal VLAN VM to VLAN VM")
        count = self._internalICMP(vlanguest[0], vlanguestip[1])
        if count[0] == 0:
            raise xenrt.XRTFailure("No communication betwwen internal lan VLAN VMs")


        # Test between the external VLAN VMs
        xenrt.TEC().logverbose("Test 4 - Basic external VLAN VM to VLAN VM")
        count = self._internalICMP(vlanguest[0], vlanguestip[2])
        if count[0] == 0:
            raise xenrt.XRTFailure("No communication betwwen external VLAN VMs")

        # Test the internal lan to vlan
        xenrt.TEC().logverbose("Test 5 - Basic negative internal LAN VM to VLAN VM")
        # Because the GAP lab routes traffic between LAN and VLAN we need to check
        # the VLAN interface to see if traffic is getting routed via the external switch
        # in this case it is OK to pass the test
        vlan_nic_name = self.host.genParamGet("pif", vlanpif, "device")
        pid = self.startHostTcpdump(self.host, vlan_nic_name, languests[0].getIP())

        count = self._internalICMP(languests[0], vlanguestip[0])
        tcp_dump_result = self.collectHostTcpdumpResults(self.host, pid)

        # if we getr ping traffic, but it didn't come in on the host's vlan nic
        # them we route the traffic internally
        if count[0] != 0 and tcp_dump_result == 0:
            raise xenrt.XRTFailure("unwanted communication between internal LAN VM and VLAN VMs")

        # Test the external lan to vlan - because the GAP routers route between the lan and
        # VLAN this cannot be tested
        #xenrt.TEC().logverbose("Test 6 - Basic negative external LAN VM to VLAN VM")
        #pid = self.startHostTcpdump(self.slave, vlan_nic_name, languests[0].getIP())
        #count = self._internalICMP(languests[0], vlanguestip[2])
        #tcp_dump_result = self.collectHostTcpdumpResults(self.slave, pid)

        #if count[0] != 0 and tcp_dump_result == 0:
        #    raise xenrt.XRTFailure("unwanted communication between LAN and external VLAN VMs")


        # xenrt.TEC().logverbose("Test 7") - TURNED OFF as Infrastructure problems with apt-cache for tcpdump on
        # linux guests
    # Listen on both lan guests for trafic to/from vlan guest - This is not actually testing anything yet
        # look at later code
        # pids = []
        # pids.append(self.startHostTcpdump(languests[0], 'eth0', vlanguestip[0]))
        # pids.append(self.startTcpdump(languests[1], 'eth0', vlanguestip[0]))

        # Create ping traffic from vlan 1 to vlan 0
        # self._internalICMP(vlanguest[1], vlanguestip[0])

        # collect results of recieved ping requests
        # count = self.collectTcpdumpResults(languests[0], pids[0])

        # Check the number of packets received on the lan form the vlan
        # Note the first six lines always appear with tcpdump
        # if (count > 0 ):
        #     raise xenrt.XRTFailure("Lan guest 0 packets leaking from vlan to lan")

        # collect results of recieved ping requests
        # count = self.collectTcpdumpResults(languests[1], pids[1])

        # Check the number of packets received on the lan form the vlan
        # Note the first six lines always appear with tcpdump
        # if (count > 0 ):
        #     raise xenrt.XRTFailure("Lan guest 1 packets leaking from vlan to lan")


        # Uninstall the VM
        vlanguest[0].shutdown()
        vlanguest[0].uninstall()

        vlanguest[1].shutdown()
        vlanguest[1].uninstall()



class TC11903(_VSwitch):
    """
    The DVSC must support 64 hosts, with a maximum of 16 host per pool.
    """

    CONTROLLER = "controller"
    # Maximum number of threads we want to use simultaneously.
    THREADS = 300

    def checkNetwork(self):
        pairs = self.pairs(self.guests) 
        intervals = range(0, len(pairs), 256) + [len(pairs)]
        indices = [ (intervals[x], intervals[x+1]) for x in range(len(intervals)-1) ]
        ping = lambda (x,y):x.execguest("ping -w 10 %s" % (y.getIP()), nolog=True)
        result = []
        for a,b in indices:
            result.extend(xenrt.pmap(ping, pairs[a:b], interval=1, exception=False))
        fail = False
        for (x,y),r in zip(pairs, result):
            if type(r) == type(""):
                xenrt.TEC().logverbose("Ping from %s to %s successful." % (x.getName(), y.getName()))
            else:
                xenrt.TEC().warning("Ping from %s to %s failed: %s" % (x.getName(), y.getName(), r.data))
                fail = True
        if fail:
            raise xenrt.XRTFailure("One or more pings failed.")

    def prepare (self, arglist=[]):
        # Give the DVSC sufficient RAM and vCPU to cope.
        self.controller = self.getGuest(self.CONTROLLER).getDVSCWebServices()
        self.controller.place.shutdown()
        self.controller.place.cpuset(4)
        self.controller.place.memset(4096)
        self.controller.place.start()
        # By convention RESOURCE_POOL_0 is the DVSC pool.
        self.pools = map(xenrt.TEC().registry.read,
                         filter(re.compile("/xenrt/specific/pool/RESOURCE_POOL_[1-9]").match,
                                xenrt.TEC().registry.data))
        self.guests = map(self.getGuest, 
                          filter(lambda x:not x == "controller",
                                 xenrt.TEC().registry.guestList()))

    def run(self, arglist=[]):
        # Check all guests are responsive.
        self.checkNetwork()
        for pool in self.pools:
            pool.associateDVS(self.controller)
        # Check all guests are responsive.
        self.checkNetwork()
        # TODO We may want to load the network with more traffic.

    def postRun(self):
        try:
            self.controller.place.shutdown()
        except:
            xenrt.TEC().warning("Failed to shutdown controller.")

class _TC11551(_VSwitch):

    """Base class for testcases that verify vdi-copy works between different SR
       types"""
    FROM_TYPE = None
    TO_TYPE = None
    pid=""
    REQ_PERCENT = 0
    MTU = None

    def prepare(self, arglist):
        _VSwitch.prepare(self, arglist)
        cli = self.host.getCLIInstance()
        self.cli = cli

        # Get the two SRs
        fromSRs = self.host.getSRs(type=self.FROM_TYPE)
        if len(fromSRs) == 0:
            raise xenrt.XRTError("Could not find %s SR on the host" %
                                 (self.FROM_TYPE))
        self.fromSR = fromSRs[0]
        toSRs = self.host.getSRs(type=self.TO_TYPE)
        if len(toSRs) == 0:
            raise xenrt.XRTError("Could not find %s SR on the host" %
                                 (self.TO_TYPE))
        self.toSR = toSRs[0]
        self.copies = {}
        self.vdisToDestroy = []

    def doCreate(self):
        # Create a VDI on the fromSR
        args = []
        args.append("sr-uuid=%s" % (self.fromSR))
        args.append("name-label=\"XenRT Test %s-%s\"" %
                    (self.FROM_TYPE, self.TO_TYPE))
        args.append("type=user")
        args.append("virtual-size=%d" % (100 * xenrt.MEGA)) # 100Mib

        self.vdi = self.cli.execute("vdi-create", string.join(args)).strip()
        self.vdisToDestroy.append(self.vdi)
        self.copies["original"] = self.vdi

        # Put a filesystem on it
        self.host.execdom0("echo '/sbin/mkfs.ext3 /dev/${DEVICE}' > "
                           "/tmp/mkfs.sh")
        self.host.execdom0("chmod u+x /tmp/mkfs.sh")
        self.host.execdom0("/opt/xensource/debug/with-vdi %s /tmp/mkfs.sh" %
                           (self.vdi))

        # Checksum the entire VDI
        self.host.execdom0("echo 'md5sum /dev/${DEVICE}' > /tmp/md5.sh")
        self.host.execdom0("chmod u+x /tmp/md5.sh")
        self.md5sum = self.host.execdom0(\
            "/opt/xensource/debug/with-vdi %s /tmp/md5.sh" %
            (self.vdi)).splitlines()[-1].split()[0]
        if "The device is not currently attached" in self.md5sum:
            raise xenrt.XRTError("Device not attached when trying to md5sum")

    def doCopy(self, sourcetag, targetsruuid, targettag):
        vdiuuid = self.copies[sourcetag]
        xenrt.TEC().logverbose("Attempting to copy to SR %s" % (targetsruuid))
        args = []
        args.append("uuid=%s" % (vdiuuid))
        args.append("sr-uuid=%s" % (targetsruuid))
        newVDI = self.cli.execute("vdi-copy", string.join(args)).strip()
        self.vdisToDestroy.append(newVDI)
        self.copies[targettag] = newVDI

    def doCheck(self, tag):
        vdiuuid = self.copies[tag]
        # Check the whole VDI checksum
        md5sum = self.host.execdom0(\
            "/opt/xensource/debug/with-vdi %s /tmp/md5.sh" %
            (vdiuuid)).splitlines()[-1].split()[0]
        if "The device is not currently attached" in md5sum:
            raise xenrt.XRTError("Device not attached when trying to md5sum")
        if md5sum != self.md5sum:
            raise xenrt.XRTFailure("Copy and original VDIs have different "
                                   "checksums")

        # Check the physical utilisation is appropriate taking into
        # account that LVM is fully provisioned for non-snapshot VDIs
        sruuid = self.host.genParamGet("vdi", vdiuuid, "sr-uuid")
        srtype = self.host.genParamGet("sr", sruuid, "type")

    def startTcpdump(self):
        # jumbo is always on IPRI
        nics = self.host.listSecondaryNICs("IPRI")
        if len(nics) == 0:
            raise xenrt.XRTFailure("No NICs on jumbo network")

        nic = self.host.getSecondaryNIC(nics[0])

        nicname = "eth%d" % nics[0]
        param = "tcpdump -i %s -nqt &> mycap & echo $!" % nicname

        self.pid = self.host.execdom0(param).strip()


    def collectTcpdumpResults(self, size):
        # kill the tcpdump process
        self.host.execdom0("kill %s" % (self.pid))
        # Provide some useful information as to the distribution of frames

        temp = self.host.execdom0("grep ': tcp' mycap|awk 'BEGIN {c=0} $NF <= 1500 {c++} END {print c, NR}'").split()
        xenrt.TEC().logverbose("%d%% frames between 0 and 1500" % float(float(temp[0]) / float(temp[1]) * 100))
        temp = self.host.execdom0("grep ': tcp' mycap|awk 'BEGIN {c=0} $NF > 1500 && $NF <=3000 {c++} END {print c, NR}'").split()
        xenrt.TEC().logverbose("%d%% frames between 1501 and 3000" % float(float(temp[0]) / float(temp[1]) * 100))
        temp = self.host.execdom0("grep ': tcp' mycap|awk 'BEGIN {c=0} $NF > 3000 && $NF <=4500 {c++} END {print c, NR}'").split()
        xenrt.TEC().logverbose("%d%% frames between 3001 and 4500" % float(float(temp[0]) / float(temp[1]) * 100))
        temp = self.host.execdom0("grep ': tcp' mycap|awk 'BEGIN {c=0} $NF > 4500 && $NF <=6000 {c++} END {print c, NR}'").split()
        xenrt.TEC().logverbose("%d%% frames between 4501 and 6000" % float(float(temp[0]) / float(temp[1]) * 100))
        temp = self.host.execdom0("grep ': tcp' mycap|awk 'BEGIN {c=0} $NF > 6000 && $NF <=7500 {c++} END {print c, NR}'").split()
        xenrt.TEC().logverbose("%d%% frames between 6001 and 7500" % float(float(temp[0]) / float(temp[1]) * 100))
        temp = self.host.execdom0("grep ': tcp' mycap|awk 'BEGIN {c=0} $NF > 7500 && $NF <=8999 {c++} END {print c, NR}'").split()
        xenrt.TEC().logverbose("%d%% frames between 7501 and 8999" % float(float(temp[0]) / float(temp[1]) * 100))
        temp = self.host.execdom0("grep ': tcp' mycap|awk 'BEGIN {c=0} $NF > 8999 {c++} END {print c, NR}'").split()
        xenrt.TEC().logverbose("%d%% above 8999" % float(float(temp[0]) / float(temp[1]) * 100))

        # Count the number of packets with mtu  > size
        result = self.host.execdom0("grep ': tcp' mycap|awk 'BEGIN {c=0} $NF >= %d {c++} END {print c, NR}'" % size).split()
        # result [packets > size, total tcp packets]

        return float(float(result[0]) / float(result[1]) * 100)

    def run(self, arglist):

        self.doCreate()
        # Attempt to copy the VDI onto the same SR type
        xenrt.TEC().logverbose("Attempting to copy within the %s SR" %
                               (self.FROM_TYPE))

        self.startTcpdump()
        if self.runSubcase("doCopy", ("original", self.fromSR, "intra"),
                           "Copy", "SameSR") == xenrt.RESULT_PASS:

            result = self.collectTcpdumpResults(self.MTU)
            if result < self.REQ_PERCENT:
                raise xenrt.XRTFailure("Only %d%% of frames are >%d MTU" % (result, self.MTU))


            self.runSubcase("doCheck", ("intra"), "Check", "SameSR")


        # Now onto the other
        xenrt.TEC().logverbose("Attempting to copy to the %s SR" %
                               (self.TO_TYPE))
        self.startTcpdump()
        if self.runSubcase("doCopy", ("original", self.toSR, "other"),
                           "Copy", "OtherSR") == xenrt.RESULT_PASS:
            result = self.collectTcpdumpResults(self.MTU)
            if result < self.REQ_PERCENT:
                raise xenrt.XRTFailure("Only %d%% of frames are >%d MTU" % (result, self.MTU))

            if self.runSubcase("doCheck", ("other"), "Check", "OtherSR") == \
                   xenrt.RESULT_PASS:

                # Now back again
                xenrt.TEC().logverbose("Attempting a final copy to the %s SR" %
                                       (self.FROM_TYPE))
                self.startTcpdump()
                if self.runSubcase("doCopy",
                                   ("other", self.fromSR, "back"),
                                   "Copy",
                                   "OriginalSR") == \
                                   xenrt.RESULT_PASS:

                    result = self.collectTcpdumpResults(self.MTU)
                    if result < self.REQ_PERCENT:
                        raise xenrt.XRTFailure("Only %d%% of frames are > 1500 MTU" % (result))

                    self.runSubcase("doCheck", ("back"), "Check", "OriginalSR")

    def postRun(self):
        for vdi in self.vdisToDestroy:
            try:
                self.cli.execute("vdi-destroy","uuid=%s" % (vdi))
            except:
                xenrt.TEC().warning("Exception attempting to destroy VDI %s" %
                                    (vdi))

class TC11553(_TC11551):
    """Verify vdi-copy between an lvmoiscsi SR and an ext SR"""
    FROM_TYPE = "lvmoiscsi"
    TO_TYPE = "nfs"
    MTU = 8000 # This is the value of the MTU we expect to see, actual MTu is set in the sequence file
               # For this test case the MTU is set to True, which should give us 9000 MTU
               # The tcpdump will check that for packets over 8000 MTU

    REQ_PERCENT = 1 # Any number of large packets will prove jumbo working

class JumboFrames(_TC11551):

    def nativehostMTUSet(self, host, jumboFrames=True, eth='eth0'):
        if jumboFrames:
            host.execcmd('ifconfig %s mtu 9000' % eth)
        else:
            host.execcmd('ifconfig %s mtu 1500' % eth)

    def xenserverMTUSet(self, host, jumboFrames=True, bridge='xenbr0'):
        cli=host.getCLIInstance()
        uuid=host.getNetworkUUID(bridge)
        if jumboFrames:
            mtu=9000
        else:
            mtu=1500
        host.execdom0("ifconfig %s mtu %s" % 
                        (host.getBridgeInterfaces(bridge)[0], mtu))
        host.execdom0("ifconfig %s mtu %i" % 
                    (bridge, mtu))
        cli.execute("network-param-set", 
                    "uuid=%s MTU=%i" %
                    (uuid, mtu) )

    def prepare(self, arglist=None):
        self.linHost=self.getHost("RESOURCE_HOST_0")
        self.xsHost = self.getHost("RESOURCE_HOST_1")
        
        # Install iperf on both hosts
        self.linHost.installIperf()
        self.linHost.execcmd("iperf -s > /root/iperf.log 2>&1 &")
        self.xsHost.installIperf()

    def _parseIperfData(self, data, jf=False):
        """ Extract throughputs and mss from raw iperf data """

        iperfData = {}
        dataFound = False
        mssFound = False
        for line in data.splitlines():
            if len(data.splitlines()) < 7:
                    raise xenrt.XRTError('Iperf still running so could not parse output')

            if re.search("0.0-", line, re.I):
                lineFields = line.split()
                if len(lineFields) != 8:
                    raise xenrt.XRTError('Failed to parse output from Iperf')

                iperfData['transfer'] = lineFields[4]
                iperfData['bandwidth'] = lineFields[6]
                dataFound = True
            
            # Parse MSS info to ensure desired packet sizes are transfered
            if re.search('MSS', line):
                lineFields = line.split()
                iperfData['mss'] = int(lineFields[4])
                mssFound = True

        if not dataFound and mssFound:
            raise xenrt.XRTError('Failed to parse general output from Iperf')
        if jf and not iperfData['mss'] > 1500 :

            raise xenrt.XRTFailure("MSS when jumboframes is enabled is expected to be greater than 1500" \
                                    "Current value %i" % iperfData['mss'])
        return iperfData

    def run(self, arglist):
        nonJFRes={}
        jfRes={}
        allowedVariance=30

        # Run the client to measure throughput
        rawData=self.xsHost.execdom0('iperf -m -c %s' % 
                                    self.linHost.getIP())

        nonJFRes=self._parseIperfData(rawData)
        xenrt.log("BEFORE JUMBOFRAMES SETTING: %s" % 
                    [(k,r) for k,r in nonJFRes.iteritems()])
        
        # Turn on jumbo frames and measure
        eth=self.linHost.execcmd("ifconfig | sed 's/[ \t].*//;/^$/d' | grep -v 'lo'").strip()
        self.nativehostMTUSet(host=self.linHost,
                                eth=eth)
        # Turn on jumbo frames on XS
        self.xenserverMTUSet(host=self.xsHost)
        rawData=self.xsHost.execdom0('iperf -m -c %s' % 
                                    self.linHost.getIP())
        jfRes=self._parseIperfData(rawData,
                                    jf=True)
        xenrt.log("AFTER JUMBOFRAMES SETTING: %s" % 
                    [(k,r) for k,r in jfRes.iteritems()])

        if not float(jfRes['bandwidth']) > (float(nonJFRes['bandwidth']) - allowedVariance):
            raise xenrt.XRTFailure("Value after jumboFrames - %s is expected to be greater/equal to before - %s" %
                                    (jfRes['bandwidth'], nonJFRes['bandwidth']))

class TC21019(JumboFrames):

    def startIperfServers(self, host, ipsToTest, baseport=5000):
        """ Start multiple iperf servers on different ports """
        list=" ".join(self.ipsToTest)

        try:
            host.execdom0("pkill iperf")
        except Exception, e:
            # Dont really need to do anything if the above fails
            xenrt.TEC().warning("Caught exception - %s, continuing.." % e)
        try:
            host.execdom0("service iptables stop")
        except Exception, e:
            # Dont really need to do anything if the above fails
            xenrt.TEC().warning("Caught exception - %s, continuing.." % e)

        scriptfile = xenrt.TEC().tempFile()

        script="""#!/bin/bash
base_port=%i
ips='%s'
mkdir -p "/tmp/iperfLogs"
for i in $ips; do
# Set server port
server_port=$((base_port++))
# Report file includes server port
report_file="/tmp/iperfLogs/iperfServer-${server_port}-$i.txt"
# Run iperf
iperf -s -p $server_port -B $i > $report_file 2>&1 &
done """ % (baseport, list)

        f = file(scriptfile, "w")
        f.write(script)
        f.close()
        sftp = host.sftpClient()
        try:
            sftp.copyTo(scriptfile, "/tmp/startiperf.sh")
        finally:
            sftp.close()
        host.execdom0("chmod +x /tmp/startiperf.sh")
        host.execdom0("/tmp/startiperf.sh &")


    def startIPerfClient(self, iperfClient, iperfServerIPs, srvBasePort=5000, timeSecs=10):
        # Convert the python list into a shell script list
        iplist=" ".join(iperfServerIPs)
        scriptfile = xenrt.TEC().tempFile()
        # Kill any iperf server that might be running
        try: 
            iperfClient.execcmd("pkill iperf")
        except Exception, e:
            xenrt.log("Caught exception - %s, continuing..." % e)

        script = """#!/bin/bash
test_duration=%i
ip='%s'
base_port=%i
mkdir -p "/tmp/iperfLogs"
for i in $ip; do
# Set server port
server_port=$((base_port++));
# Report file includes server ip, server port and test duration
report_file="/tmp/iperfLogs/iperfClient-${server_port}-${i}.txt"
# Run iperf
iperf -m -c $i -p $server_port -t $test_duration > $report_file 2>&1 &
done
# Add sleep to stall the script from exiting
sleep %i
""" % (timeSecs, iplist, srvBasePort, timeSecs)

        f = file(scriptfile, "w")
        f.write(script)
        f.close()
        sftp = iperfClient.sftpClient()
        try:
            sftp.copyTo(scriptfile, "/tmp/iperfclient.sh")
        finally:
            sftp.close()
        iperfClient.execcmd("chmod +x /tmp/iperfclient.sh")
        iperfClient.execcmd("/tmp/iperfclient.sh",
                            timeout=timeSecs+10)

    def _collectLogs(self):
        logDir="iperf"
        logsubdir = os.path.join(xenrt.TEC().getLogdir(), logDir)
        if not os.path.exists(logsubdir):
                os.makedirs(logsubdir)

        for h in self.linHost, self.xsHost:
            try:
                sftp = h.sftpClient()
                sftp.copyTreeFrom("/tmp/iperfLogs", logsubdir)
            finally:
                sftp.close()

    def prepare(self, arglist=None):
        self.ipsToTest=[]
        self.basePort=5000
        JumboFrames.prepare(self)
        assumedids = self.xsHost.listSecondaryNICs()
        cli=self.xsHost.getCLIInstance()

        # Turn on jumbo frames on native linux
        eth=self.linHost.execcmd("ifconfig | sed 's/[ \t].*//;/^$/d' | grep -v 'lo'").strip()
        self.nativehostMTUSet(host=self.linHost,
                                eth=eth)
        # Turn on Jumbo Frames on management interface
        self.xenserverMTUSet(host=self.xsHost)

        for id in assumedids:
            pif = self.xsHost.getNICPIF(id)
            cli.execute("pif-reconfigure-ip", "mode=dhcp uuid=%s" % pif)
            self.ipsToTest.append(self.xsHost.getIPAddressOfSecondaryInterface(id))
            self.xenserverMTUSet(host=self.xsHost,
                                bridge=self.xsHost.getBridgeWithMapping(id))

        # Dont forget to test the management interface
        self.ipsToTest.append(self.xsHost.getIP())
        xenrt.log("IPs to test - %s" % self.ipsToTest)

        if len(self.ipsToTest) <= 1:
            raise xenrt.XRTError("This test requires machines with more than one NIC")
        # Start iperf servers on XS - one for each pif
        self.startIperfServers(host=self.xsHost,
                                ipsToTest=self.ipsToTest,
                                baseport=self.basePort)

    def generateNetworkTraffictoXS(self, timeSecs, ips):
        result={}
        rxDict = {}
        self.startIPerfClient(iperfClient=self.linHost,
                        iperfServerIPs=ips,
                        timeSecs=int(timeSecs))

        counter=len(self.ipsToTest)+20 # Add another few iterations as buffer
        out=self.linHost.execcmd("ps -ef | pgrep iperf").strip()
        while out and counter:
            # This is to let iperf logs get generated (waiting for the exact timeSecs is not enough)
            xenrt.sleep(timeSecs)
            counter-=1
            try:
                out=self.linHost.execcmd("ps -ef | pgrep iperf").strip()
            except Exception, e:
                out=False

        # Process results
        for ip in ips:
            str=self.linHost.execcmd("cd /tmp/iperfLogs && ls | grep %s | xargs cat" % ip).strip()
            xenrt.log("Raw iperf data for ip - %s: %s" %
                        (ip, str) )
            # Check if any iperf client communication has bombed
            result=self._parseIperfData(data=str, 
                                        jf=True)
            result['ip']=ip
            xenrt.log("Iperf results - %s" % 
                        [(k,r) for k,r in result.iteritems()])

        for id in self.xsHost.listSecondaryNICs():
            # Look for overruns
            overruns=self.xsHost.execdom0("ifconfig %s | grep RX | grep overruns" %
                                            self.xsHost.getSecondaryNIC(id)).strip().split()[-2]
            rxDict[self.xsHost.getSecondaryNIC(id)] = overruns

            # Verify there are no overruns
            if int(overruns.split(":")[1]) <> 0:
                raise xenrt.XRTFailure("Found overruns for NIC %s - %s" %
                                        (self.xsHost.getSecondaryNIC(id), overruns))
        xenrt.log("OVERRUN DATA: %s" %
                        [(k,r) for k,r in rxDict.iteritems()])

    def run(self, arglist):
        self.runSubcase("generateNetworkTraffictoXS", (60, self.ipsToTest), "RX Overruns", "RX Overruns")
        self.runSubcase("generateNetworkTraffictoXS", (120, self.ipsToTest), "RX Overruns", "RX Overruns")

    def postRun(self):
        self._collectLogs()

class TC11527(_VSwitch):
    """
    SPAN Mirror
    Ensure that is possible to select mirrored traffic by interface of any type 
    (physical, bond [see TC11565] or virtual), direction (ingress, egress or both) or by VLAN.
    
    """
    # at the start of this test we have the following setup

    # +----------------+         +----------------+
    # | H0             |         | H1             |
    # |  Linux_0       |         |        Linux_2 |
    # |    Eth0---+    |         |   +---Eth0     |
    # |           |    |         |   |            |
    # |         XenBr0-|---Eth0--|-xenbr0         |
    # |  Linux_1  |    |   NPRI  |   |    Linux_3 |
    # |    Eth0---+    |         |   +---Eth0     |
    # |                |         |                |
    # |         XenBr4-|---Eth4--|-xenbr4         |
    # |                |   NSEC  |                |
    # +----------------+ VLAN902 +----------------+
    #                    RSPAN (VLAN2)

    linux_0 = None
    linux_1 = None
    linux_1 = None
    mirrorUUID = None


    def startTcpdump(self, guest, nic_name):
        param = "tcpdump -i %s icmp &> mycap & echo $!" % nic_name
        return guest.execguest(param).strip() 

    def collectTcpdumpResults(self, guest, pid, search_ipaddr):
        # kill the tcpdump process
        guest.execguest("kill %s" % (pid))

        return int(guest.execguest("grep '%s' mycap|awk 'END {print NR}'" % search_ipaddr).strip())

    def prepare(self, arglist):
        _VSwitch.prepare(self, arglist)
        self.linux_0 = self.getGuestFromName('p0h0-0')
        self.linux_1 = self.getGuestFromName('p0h0-1')
        self.linux_2 = self.getGuestFromName('p0h1-0')
        self.setupGuestTcpDump(self.linux_1)
        self.vlanpif = self.pool.master.getNICPIF(4)
        self.network = self.pool.master.createNetwork(name="RSPAN")
        self.linux_2.getHost().createVLAN(2, self.network, pifuuid=self.vlanpif)
        self.network2 = self.pool.master.createNetwork(name="VLAN VR02 on NPRI 4")
        self.linux_2.getHost().createVLAN(902, self.network2, pifuuid=self.vlanpif)
      
    def setupSPAN(self, host, selectsrcport, selectdstport, outputport):
        srcPortUUID = self.host.execdom0("ovs-vsctl -- get Port %s _uuid" % selectsrcport).strip()
        dstPortUUID = self.host.execdom0("ovs-vsctl -- get Port %s _uuid" % selectdstport).strip()
        outPortUUID = self.host.execdom0("ovs-vsctl -- get Port %s _uuid" % outputport).strip()
        self.mirrorUUID = self.host.execdom0("ovs-vsctl -- set Bridge xenbr0 mirrors=@m -- --id=@m create Mirror name=mymirror "
                                             "select-src-port=%s select-dst-port=%s output-port=%s" %
                                            (srcPortUUID, dstPortUUID, outPortUUID)).strip()

    def getXenbrFromFakeXapibr(self, host, vlan_bridge):
        """ XAPI bridges are not real bridges as such, when the bridge provides connection to the pif they form part of an xenbr bridge. This function returns the xenbr bridge that the xapi bridge is associated with."""
        peids = host.execdom0("ovs-vsctl -- get port %s external_ids" % vlan_bridge).strip().replace("fake-bridge-", "" )
        bridges = host.execdom0("ovs-vsctl list-br").strip().split("\n")
        xen_bridge = None
        beids = None
        for bridge in bridges:
            if "xapi" not in bridge:
                beids = host.execdom0("ovs-vsctl -- get Bridge %s external_ids" % bridge).strip()
            if beids == peids:
                xen_bridge = bridge
                break
            else:
                xen_bridge = None
        return xen_bridge

    def removeSPAN(self, host): 
        host.execdom0("ovs-vsctl destroy Mirror mymirror -- clear Bridge xenbr0 mirrors")

    def setupVLANSPAN(self, host, selectvlan, selectsrcport, selectdstport, outputport, bridge):
        srcPortUUID = self.host.execdom0("ovs-vsctl -- get Port %s _uuid" % selectsrcport).strip()
        dstPortUUID = self.host.execdom0("ovs-vsctl -- get Port %s _uuid" % selectdstport).strip()
        outPortUUID = self.host.execdom0("ovs-vsctl -- get Port %s _uuid" % outputport).strip()
        self.mirrorUUID = self.host.execdom0("ovs-vsctl -- set Bridge %s mirrors=@m -- --id=@m create Mirror name=mymirror "
                                             "select-vlan=%d select-src-port=%s select-dst-port=%s output-port=%s" %
                                            (bridge, selectvlan, srcPortUUID, dstPortUUID, outPortUUID)).strip()
       

    def removeVLANSPAN(self, host, bridge): 
        host.execdom0("ovs-vsctl destroy Mirror mymirror -- clear Bridge %s mirrors" % bridge)


    def run(self, arglist):
        # Create a listen vif on linux_1 xenbr0 
        self.linux_1.execcmd("rm -f "
                             "/etc/udev/rules.d/z25_persistent-net.rules "
                             "/etc/udev/persistent-net-generator.rules")

        self.linux_1.execguest("cp /etc/network/interfaces /root/interfaces")
        self.linux_1.execguest("echo 'auto eth1 \niface eth1 inet static \n"
                                       "address 192.168.242.1 \nnetmask 255.255.240.0' "
                                       " >>/etc/network/interfaces")


        self.linux_1.createVIF(eth="eth1", bridge='xenbr0', mac=None, plug=True)
        self.linux_1.execguest("ifup eth1")
        # Linux_1 now has a VIFs 0 and 1 on xenbr0, vif 1 is the listen vif 



        self.linux_0.execguest("nohup ping %s >/dev/null 2>/dev/null &" % self.linux_2.getIP())
        # Linux_0 vif 0 is now pinging linux_2 vif 0

        # get the host linux_0 and 1 are on 
        host = self.linux_0.getHost()
        
        # Tests have shown that listen vif is not always created at 2.1 as expected
        # This nasty line calls ifconfig and extracts the only ?.1 vif
        listenvifname = "vif%d.1" % (self.linux_1.getDomid())

        xenrt.TEC().logverbose("Test 1 Mirror Host_0 eth0")
        # This will mirror the hosts eth0 onto vif?.1 (linux_1) - i.e. physical mirror
        # and should reflect all traffic on Host0 Eth0 to Linux1 vif?.1
        self.setupSPAN(host, "eth0", "eth0", listenvifname)

        # Start tcpdump on linux1 vif?.1
        pid = self.startTcpdump(self.linux_1, "eth1")

        # Local tests show that tcpdump is buffering 43-5 seconds of data
        time.sleep(50)

        # Ensure that linux1 vif?.1 has recived the pings between linux_0 and linux_2
        if self.collectTcpdumpResults(self.linux_1, pid, self.linux_2.getIP()) < 1:
            raise xenrt.XRTError("No Pings received at linux_1")

        # Clean up the mirror
        self.removeSPAN(host)

        # Let the information trickle through the interfaces 
        time.sleep(10)

        # Again start tcpdump on linux 1 vif?.1 to ensure mirror was removed
        pid = self.startTcpdump(self.linux_1, "eth1")

        # Local tests show that tcpdump is buffering 43-5 seconds of data
        time.sleep(50)
        
        # Check that we have not recieved any pings
        if self.collectTcpdumpResults(self.linux_1, pid, self.linux_2.getIP())	:
            raise xenrt.XRTError("Still receiving pings at linux_1 after mirror removed")


        # Now test the Mirroring of a VIF
        mirrorvifname = "vif%d.0" % (self.linux_0.getDomid())
        xenrt.TEC().logverbose("Test 2 Mirror linux0 eth0 (%s)" % mirrorvifname) 

        # This will mirror vif1.0 onto listenvif (linux_1) - i.e. virtual mirror
        self.setupSPAN(host, mirrorvifname, mirrorvifname, listenvifname)

        pid = self.startTcpdump(self.linux_1, "eth1")
        # Local tests show that tcpdump is buffering 43-5 seconds of data
        time.sleep(50)
        if self.collectTcpdumpResults(self.linux_1, pid, self.linux_2.getIP()) < 1:
            raise xenrt.XRTError("No Pings received at linux_1")

        self.removeSPAN(host)
        # let the information trickle through the interfaces 
        time.sleep(10)

        pid = self.startTcpdump(self.linux_1, "eth1")
        # Local tests show that tcpdump is buffering 43-5 seconds of data
        time.sleep(50)
        if self.collectTcpdumpResults(self.linux_1, pid, self.linux_2.getIP()) > 0:
            raise xenrt.XRTError("Still receiving pings at linux_1 after mirror removed")

        
        # kill the ping
        self.linux_0.execguest("killall ping")

        # Remove the vif created on linux_1
        self.linux_1.execguest("ifdown eth1")
        self.linux_1.unplugVIF("eth1")
        self.linux_1.removeVIF("eth1")
        self.linux_1.execguest("cp /root/interfaces /etc/network/interfaces")


        xenrt.TEC().logverbose("Test 3 Mirror VLAN") 


        # Create VIFs ?.1 on linux_0, linux_1 and linux_2 all VIFs are on xenbr4 which is 
        # connected to the VLAN network VR02
        for guest in [self.linux_0, self.linux_1, self.linux_2]:
            guest.execcmd("rm -f "
                             "/etc/udev/rules.d/z25_persistent-net.rules "
                             "/etc/udev/persistent-net-generator.rules")

            guest.execguest("cp /etc/network/interfaces /root/interfaces")
            guest.execguest("echo '\nauto eth1 \niface eth1 inet dhcp \n' >> /etc/network/interfaces")

            vlan_bridge = guest.getHost().minimalList("network-list", "bridge", "'name-label=VLAN VR02 on NPRI 4'")[0]
            
            guest.createVIF(eth="eth1", bridge=vlan_bridge, mac=None, plug=True)
            guest.execguest("ifup eth1")

        # Again use linux_1 vif ?.1 for listening to traffic
        vlanlistenvifname = "vif%d.1" % (self.linux_1.getDomid())

        # Wait for the dhcp addresses to propagate to all the vifs,
        # by waiting for the last vif that was created we should be sure that all
        # vifs now have an IP address
        while self.linux_2.getVIFs()['eth1'][1] == None:
            time.sleep(5)

        # Get the IP address for linux_2's VLAN vif - this will be pinged by linux 0
        linux_2_vlanip = self.linux_2.getVIFs()['eth1'][1]

        # cause linux 0 to ping linux 2 over vlan, as linux 2's IP address is on the 
        # vlan linux 0 will route it via its vlan vif
        self.linux_0.execguest("nohup ping %s >/dev/null 2>/dev/null &" % linux_2_vlanip)

        # get the name of the vlan bridge (should be xapi1)
        vlan_bridge = host.minimalList("network-list", "bridge", "'name-label=VLAN VR02 on NPRI 4'")[0]

        # XenServer associates a fake bridge with a real bridge, in this case xapi1 should be a part
        # of xenbr2.
        # However as xapi is not a real bridge we cannot mirror from it
        mirror_vlan_bridge = self.getXenbrFromFakeXapibr(host, vlan_bridge)

        # Set up a vlan mirror for VR02 (vlan id 902), note we listen between eth2 and xenbr2
        # directing the traffic to linux_1 vif ?.1
        self.setupVLANSPAN(host, 902, "eth4", "eth4", vlanlistenvifname, mirror_vlan_bridge)

        pid = self.startTcpdump(self.linux_1, "eth1")
        # Local tests show that tcpdump is buffering 43-5 seconds of data
        time.sleep(50)
        # need to get linux 2's vlan IP address
        linux_2_vlan_ip = self.linux_2.getVIFs()['eth1'][1]
        if self.collectTcpdumpResults(self.linux_1, pid, linux_2_vlan_ip) < 1:
            raise xenrt.XRTError("No Pings received at linux_1")

        self.removeVLANSPAN(host, mirror_vlan_bridge)

        # let the information trickle through the interfaces 
        time.sleep(10)

        # Ensure that the removal of the VLAN SPAN has worked
        pid = self.startTcpdump(self.linux_1, "eth1")

        # Local tests show that tcpdump is buffering 43-5 seconds of data
        time.sleep(50)
        if self.collectTcpdumpResults(self.linux_1, pid, linux_2_vlan_ip) > 0:
            raise xenrt.XRTError("Still receiving pings at linux_1 after mirror removed")

        # Remove the interfaces we created
        for guest in [self.linux_0, self.linux_1, self.linux_2]:
            guest.execguest("ifdown eth1")
            guest.unplugVIF("eth1")
            guest.removeVIF("eth1")
            guest.execguest("cp /root/interfaces /etc/network/interfaces")

        # kill the ping
        self.linux_0.execguest("killall ping")


    def postRun(self):
        # None of this should be required if the test passes, however if the fails
        # This 'should' leave the system in the state that we found it so the following
        # test is able to run. We could not run this sesction in the event of the above 
        # passing, but just in case lets run it anyway
        for guest in [self.linux_0, self.linux_1, self.linux_2]:
            try:
                guest.execguest("ifdown eth1")
                guest.unplugVIF("eth1")
                guest.removeVIF("eth1")
                guest.execguest("cp /root/interfaces /etc/network/interfaces")
            except:
                xenrt.TEC().logverbose("postRun failed to remove interface on %s - this is probably OK" % guest.getName())
        try:
            self.removeSPAN(self.host)
        except:
            xenrt.TEC().logverbose("postRun failed to remove SPAN - this is probably OK")
        try:
            vlan_bridge = self.host.minimalList("network-list", "bridge", "'name-label=VLAN VR02 on NPRI 4'")[0]
            mirror_vlan_bridge = self.getXenbrFromFakeXapibr(self.host, vlan_bridge)
            self.removeVLANSPAN(self.host, mirror_vlan_bridge)
        except:
            xenrt.TEC().logverbose("postRun failed to remove VLAN SPAN - this is probably OK")
        try:
            self.linux_0.execguest("killall ping")
        except:
            xenrt.TEC().logverbose("postRun failed to kill ping - this is probably OK")
           
            
class TC11565(_VSwitch):
    """
    Ensure that Broadcast and Multicast packets from a single host are sent on only one of the NICs in a bond
    """
    cap_count = 0
    mirrornum = 0
    vif_num = 1 
    guest = None
    mirrorbridge = None

    def startTcpdump(self, guest, nic_name):
        param = "tcpdump -i %s icmp &> mycap_%s & echo $!" % (nic_name, nic_name)
        return guest.execguest(param).strip() 

    def collectTcpdumpResults(self, guest, interface, pid, search_ipaddr):
        # kill the tcpdump process
        guest.execguest("kill %s" % (pid))

        return int(guest.execguest("grep '%s' mycap_%s|grep 'echo request'|awk 'END {print NR}'" % (search_ipaddr, interface)).strip())


    def startHostTcpdump(self, host, ifname):
        param = "tcpdump -i %s src %s and icmp -nqt &> mycap%d & echo $!" % (ifname, host.getIP(), self.cap_count)
        self.cap_count += 1
        return host.execdom0(param).strip() # return pid

    def collectHostTcpdumpResults(self, host, pid, cap_count):
        # kill the tcpdump process
        self.host.execdom0("kill %s" % (pid))
        # return number of ICMP requests
        return self.host.execdom0("grep 'echo request' mycap%d|awk 'END {print NR}'" % (cap_count))

    def createListenVIF(self, guest, vif):
        if self.vif_num  == 1:
            guest.execcmd("rm -f "
                             "/etc/udev/rules.d/z25_persistent-net.rules "
                             "/etc/udev/persistent-net-generator.rules")

            guest.execguest("cp /etc/network/interfaces /root/interfaces")

        guest.execguest("echo 'auto eth%d \niface eth%d inet dhcp\n' >>/etc/network/interfaces" 
                        % (self.vif_num, self.vif_num))

        interface = "eth%d" % (self.vif_num)
        xenrt.TEC().logverbose("interface = %s" % interface)
        guest.createVIF(eth=interface, bridge=self.mirrorbridge, mac=None, plug=True)
        guest.execguest("ifup %s" % (interface))
        self.vif_num += 1


    def setupSPAN(self, host, srcPortUUID, dstPortUUID, outputport):
        outPortUUID = self.host.execdom0("ovs-vsctl -- get Port %s _uuid" % outputport).strip()
        if dstPortUUID == None:
            mirrorUUID = self.host.execdom0("ovs-vsctl -- set Bridge %s mirrors=@m -- --id=@m create Mirror name=mymirror%d "
                                             "select-src-port=%s output-port=%s" %
                                            (self.mirrorbridge, self.mirrornum, srcPortUUID, outPortUUID)).strip()
        else:
            mirrorUUID = self.host.execdom0("ovs-vsctl -- set Bridge %s mirrors=@m -- --id=@m create Mirror name=mymirror%d "
                                             "select-src-port=%s select-dst-port=%s output-port=%s" %
                                            (self.mirrorbridge, self.mirrornum, srcPortUUID, dstPortUUID, outPortUUID)).strip()

        self.mirrornum += 1

        return self.mirrornum

    def removeSPAN(self, host, mirrornum): 
        host.execdom0("ovs-vsctl destroy Mirror mymirror%d -- clear Bridge %s mirrors" % (self.mirrorbridge))


    def prepare (self, arglist):
        _VSwitch.prepare(self, arglist)
        
        

    def run(self, arglist):
        # create a generic linux guest on the primary bridge
        # We expect the host to have a single bond
        bonds = self.host.getBonds()
        hosts = self.host.pool and self.host.pool.getHosts() or [self.host]
        if len(bonds) != len(hosts):
            raise xenrt.XRTError("Found %d bonds, expecting %d" % (len(bonds), len(hosts)))

        # Find the bond corresponding to this host
        bondPif = None
        for bond in bonds:
            pif = self.host.genParamGet("bond", bond, "master")
            if self.host.genParamGet("pif", pif, "host-uuid") == self.host.getMyHostUUID():
                bondPif = pif
                break
        if not bondPif:
            raise xenrt.XRTError("Couldn't find a bond for the test host")

        bondNet = self.host.genParamGet("pif", bondPif, "network-uuid")

        bond_bridge = self.host.genParamGet("network", bondNet, "bridge")
        xenrt.TEC().logverbose("Bond bridge = %s" %  (bond_bridge))
        self.mirrorbridge = bond_bridge

        self.guest = self.host.createGenericLinuxGuest(bridge=bond_bridge)
        # create 3 extra vifs on xenbr2
        # guest map xapi1[vif1.0 = eth0], xenbr2[vif1.1 = eth1, vif1.2=eth2, vif1.3=eth3]
        for i in range(3):
            self.createListenVIF(self.guest, i + 1)
        self.setupGuestTcpDump(self.guest)


        # get list of pif uuids on this host
        host_pifs = self.host.minimalList("pif-list", 
                                          "uuid",
                                          "host-uuid=%s" %(self.host.uuid))

        xenrt.TEC().logverbose("Host pifs = %s" % str(host_pifs))

        # for unknown reasons vswitch calls xapi0 bond0
        ovs_bridge_name = "bond0"
        # This list has the slave uuids in string pairs
        bond_ifUUIDs = re.findall('[\d\w-]+', self.host.execdom0("ovs-vsctl -- get Port %s interfaces" % ovs_bridge_name))
        bondUUID = self.host.execdom0("ovs-vsctl -- get Port %s _uuid" % ovs_bridge_name).strip()

        xenrt.TEC().logverbose("bond_slaves = %s" % str(bond_ifUUIDs))

        vifndot1 = "vif%s.1" % self.guest.getDomid()
        vifndot2 = "vif%s.2" % self.guest.getDomid()
        vifndot3 = "vif%s.3" % self.guest.getDomid()

        # setup some span for tracking the traffic
        self.setupSPAN(self.host, bond_ifUUIDs[0], None, vifndot1) # now we can see what is emitted on eth0
        self.setupSPAN(self.host, bond_ifUUIDs[1], None, vifndot2) # now we can see what is emitted on eth1
        self.setupSPAN(self.host, bondUUID, bondUUID, vifndot3) # now we can see what is received/emitted on the bond


        ###########################
        # Broadcast - to the world
        ###########################

        
        pri_nic_pid = self.startTcpdump(self.guest, 'eth1')
        sec_nic_pid = self.startTcpdump(self.guest, 'eth2')
        bond_pid = self.startTcpdump(self.guest, 'eth3')
 
        self.guest.execguest("ping -b -w %s 255.255.255.255" % (self.DURATION), timeout=2*self.DURATION)


        pri_count = self.collectTcpdumpResults(self.guest, 'eth1', pri_nic_pid, self.guest.getIP())
        sec_count = self.collectTcpdumpResults(self.guest, 'eth2', sec_nic_pid, self.guest.getIP())
        bond_count = self.collectTcpdumpResults(self.guest, 'eth3', bond_pid, self.guest.getIP())

        xenrt.TEC().logverbose("pri_count=%d, sec_count=%d, bond_count=%d" % (pri_count, sec_count, bond_count))
        
        # One bond nic show should send and one should reflect
        if pri_count == 0 and sec_count == 0: 
            raise xenrt.XRTError("No broadcast traffic found on bonded NICs")

        # If one bond nic sends and one receives relections the bond mirror will see 
        # 2 * sent packets, if both bonds send the same packet bond mirror will see
        # sent packets / 2
        if bond_count != (pri_count + sec_count):
            raise xenrt.XRTError("Broadcast traffic found on both bonded NICs")
        
        #################
        # Broadcast local
        #################
        netmask = self.host.lookup(["NETWORK_CONFIG", "DEFAULT", "SUBNETMASK"])
        subnet = self.host.lookup(["NETWORK_CONFIG", "DEFAULT", "SUBNET"])

        xenrt.TEC().logverbose("Netmask reported as %s" % 
                               (netmask))
        xenrt.TEC().logverbose("Subnet reported as %s" % 
                               (subnet))



        # now we will only see output ping requeats
        bcast = xenrt.util.calculateLANBroadcast(subnet, netmask)
        xenrt.TEC().logverbose("Multicast reported as %s" % 
                               (bcast))

        pri_nic_pid = self.startTcpdump(self.guest, 'eth1')
        sec_nic_pid = self.startTcpdump(self.guest, 'eth2')
        bond_pid = self.startTcpdump(self.guest, 'eth3')
 
        self.guest.execguest("ping -b -w %s 255.255.255.255" % (self.DURATION), timeout=2*self.DURATION)


        pri_count = self.collectTcpdumpResults(self.guest, 'eth1', pri_nic_pid, self.guest.getIP())
        sec_count = self.collectTcpdumpResults(self.guest, 'eth2', sec_nic_pid, self.guest.getIP())
        bond_count = self.collectTcpdumpResults(self.guest, 'eth3', bond_pid, self.guest.getIP())

        # One bond nic show should send and one should reflect
        if pri_count == 0 and sec_count == 0: 
            raise xenrt.XRTError("No broadcast traffic found on bonded NICs")

        # If one bond nic sends and one receives relections the bond mirror will see 
        # 2 * sent packets, if both bonds send the same packet bond mirror will see
        # sent packets / 2
        if bond_count != (pri_count + sec_count):
            raise xenrt.XRTError("Broadcast traffic found on both bonded NICs")


        ###########
        # Multicast
        ###########
        pri_nic_pid = self.startTcpdump(self.guest, 'eth1')
        sec_nic_pid = self.startTcpdump(self.guest, 'eth2')
        bond_pid = self.startTcpdump(self.guest, 'eth3')
 
        self.guest.execguest("ping -b -w %s 255.255.255.255" % (self.DURATION), timeout=2*self.DURATION)


        pri_count = self.collectTcpdumpResults(self.guest, 'eth1', pri_nic_pid, self.guest.getIP())
        sec_count = self.collectTcpdumpResults(self.guest, 'eth2', sec_nic_pid, self.guest.getIP())
        bond_count = self.collectTcpdumpResults(self.guest, 'eth3', bond_pid, self.guest.getIP())

        # One bond nic show should send and one should reflect
        if pri_count == 0 and sec_count == 0: 
            raise xenrt.XRTError("No broadcast traffic found on bonded NICs")

        # If one bond nic sends and one receives relections the bond mirror will see 
        # 2 * sent packets, if both bonds send the samee packet bond mirror will see
        # sent packets / 2
        if bond_count != (pri_count + sec_count):
            raise xenrt.XRTError("Broadcast traffic found on both bonded NICs")


    def postRun(self):
        for i in range(self.mirrornum):
            try:
                self.removeSPAN(self.host, i)            
            except:
                xenrt.TEC().logverbose("Failed to remove mirror %d" %  (i))
        try:
            self.guest.shutdown()
            self.guest.uninstall()
        except:
            xenrt.TEC().logverbose("Failed to remove guest")
        _VSwitch.postRun(self)

        

        pri_nic_pid = self.startTcpdump(self.guest, 'eth1')
        sec_nic_pid = self.startTcpdump(self.guest, 'eth2')
        bond_pid = self.startTcpdump(self.guest, 'eth3')
 
        self.guest.execguest("ping -b -w %s 255.255.255.255" % (self.DURATION), timeout=2*self.DURATION)


        pri_count = self.collectTcpdumpResults(self.guest, 'eth1', pri_nic_pid, self.guest.getIP())
        sec_count = self.collectTcpdumpResults(self.guest, 'eth2', sec_nic_pid, self.guest.getIP())
        bond_count = self.collectTcpdumpResults(self.guest, 'eth3', bond_pid, self.guest.getIP())


class TC11567(_VSwitch):
    """
    Bond carrier loss and carrier detection rates. Set the carrier loss and carrier detection delays and ensure that these are obeyed.
    """

    bond_pif_uuid = None
    orig_down_delay = None

    def moveInterfaceOnto(self, vm, new_bridge):

        # force a ping during this exercise to make the switch learn the new net loaction of the VM
        pid = vm.execguest("nohup ping google.com &>/dev/null 2>/dev/null & echo $!").strip('\n')

        vm.execcmd("rm -f "
                     "/etc/udev/rules.d/z25_persistent-net.rules "
                     "/etc/udev/persistent-net-generator.rules")
        mac_addr, ip_addr, old_bridge = vm.getVIFs()['eth0']
        vm.unplugVIF("eth0")
        vm.removeVIF("eth0")
        vm.createVIF(eth="eth0", bridge=new_bridge, mac=mac_addr, plug=True)
        vif = "vif%s.0" % vm.getDomid()
        new_ip = None
        while new_ip == None or new_ip == ip_addr :
            new_ip = vm.getVIFs()['eth0'][1]
        vm.mainip = new_ip

        # now the guest 'should' be contactable through the new interface - we hope
        vm.execguest("kill -9 %s" % pid)

    def prepare(self, arglist):
        _VSwitch.prepare(self, arglist)
        # The nasty lab setup can play tricks by sending managment out on NSEC
        # but receiving the response on NRPI
        # The follwing tears down the NPRI bond leaving only the NSEC NIC
        # It then causes the host to broadcast ping the NSEC subnet
        # This forces the switch to learn that the host management inetrface
        # is routable via NSEC
        mpif = self.host.parseListForUUID("pif-list",
                                     "management",
                                     "true",
                                     "host-uuid=%s" % (self.host.getMyHostUUID()))
        netmask = self.host.genParamGet("pif", mpif, "netmask")
        subnet = xenrt.util.calculateSubnet(self.host.getIP(), netmask)
        bcast = xenrt.util.calculateLANBroadcast(subnet, netmask)

        networks = self.host.minimalList("network-list")
        bondNetwork = None
        for n in networks:
            netName = self.host.genParamGet("network", n, "name-label")
            if netName.startswith("NPRI bond of"):
                bondNetwork = n
                self.bridge = self.host.genParamGet("network", n, "bridge")
                break
        if not bondNetwork:
            raise xenrt.XRTError("Cannot find bond network")

        bondPif = self.host.parseListForUUID("pif-list", "network-uuid", bondNetwork)
        bondUUID = self.host.genParamGet("pif", bondPif, "bond-master-of")
        slavePifs = self.host.minimalList("pif-list", args="bond-slave-of=%s" % (bondUUID))
        self.bondDevices = map(lambda p: self.host.genParamGet("pif", p, "device"), slavePifs)
        self.host.execdom0("/etc/init.d/ntpd restart") # Make sure time is in sync

        dev1 = self.bondDevices[0]
        dev2 = self.bondDevices[1]
        script="""#!/bin/bash
# Force phyiscal switch to send all man traffic through
# NSEC
ifconfig %s down
ifconfig %s down
ping -c 1 -b %s
ifconfig %s up
ifconfig %s up
""" % (dev1, dev2, bcast, dev1, dev2)

        self.host.execdom0("echo '%s' > script" % script)
        self.host.execdom0("chmod a+x script")
        self.host.execdom0("nohup ./script &")
        time.sleep(5) # give time for interfaces to ressurect
        self.orig_down_delay = self.host.execdom0("ovs-vsctl get port bond0 bond_downdelay")

    def run(self, arglist):
        # The contextt for this test is as follows:
        # R4.9 Link failure must be determined by carrier loss on the interface.
        # R4.10 The link failure detection mechanism must support a user-configurable delay before an 
        #       interface that has lost carrier is declared down and another user-configured delay before 
        #       an interface that has detected carrier is declared "up". Transitions between states 
        #       during this delay period must reset the timer.
        # R4.11 The delay on carrier detection must be ignored when all interfaces in a bond are out of 
        #       service to minimize the latency in re-establishing connectivity.
        # R4.12 In the event of an interface failure the MAC addresses on the failed interface must be 
        #       rebalanced onto the remaining interfaces and the switching fabric must be advised of the change
        # R4.12a When an interface resumes service traffic from existing interfaces must be rebalanced across 
        #       all the operational interfaces.

        # get the bond information
        bond_uuid = self.host.minimalList("bond-list")[0]
        self.bond_pif_uuid = self.host.genParamGet("bond", bond_uuid, "master")

        linux_0 = self.getGuestFromName('linux_0')
        # start pinging forever - this will provide some constant traffic to monitor
        linux_0.execguest("nohup ping %s >/dev/null 2>/dev/null &" % (xenrt.TEC().lookup("XENRT_SERVER_ADDRESS")))

        # Note that I am moving the interface whilst pinging, this should 
        # help the switch keep the new loaction
        vif = self.host.minimalList('vm-vif-list uuid=%s' % linux_0.getUUID())[0]
        vm_old_network = self.host.genParamGet("vif", vif, "network-uuid")
        self.vm_old_bridge = self.host.genParamGet("network", vm_old_network, "bridge")
        self.moveInterfaceOnto(linux_0, self.bridge)
        
        # First we need to find the pif the traffic is being tx'd on
        dev1 = self.bondDevices[0]
        dev2 = self.bondDevices[1]
        try:
            self.host.execdom0("tcpdump -c1 -i %s host %s and icmp" % (dev1, linux_0.getIP()), timeout=2)
        except:
            first_if = dev1
            sec_if = dev2
        else:
            first_if = dev2
            sec_if = dev1

        # tolerence for python/ssh command execution
        tolerence = 2
        for delay in [2, 3, 4, 5]:
            ##
            # Test down delay
            ##

            # set the bond down delay to 'delay' seconds - this delay is in miliseconds
            self.host.execdom0("ovs-vsctl set port bond0 bond_downdelay=%d" % (delay * 1000))

            # bring down the interface we know the traffic is on originally 'first if'            
            self.host.execdom0("ifconfig %s down" % first_if)

            # store time now
            before = time.time()

            # wait until traffic is seen on the second interface
            self.host.execdom0("tcpdump -c1 -i %s host %s and icmp" % (sec_if, linux_0.getIP()), timeout=(delay *2))
            # check time delta is not greater than that we are testing
            # Note we need to subtract one second to delay to account for the turnaround of python commands
            after= time.time()
            if ((after - before) - tolerence) > delay:
                raise xenrt.XRTFailure("down time was exceeded: %d (-%d) measured for down time of %d secs" % ((after - before) - tolerence, tolerence, delay))
            # However if it were instant that would be bad too
            if ((after - before) + tolerence) < delay:
                raise xenrt.XRTFailure("down time was less than set: %d (+%d) measured or down time of %d secs" % ((after - before) + tolerence, tolerence, delay))

            # Bring up the first interface 
            self.host.execdom0("ifconfig %s up" % first_if)
            
            # pings are still being received on sec interface now - so switch first and sec for next iteration
            temp = first_if
            first_if = sec_if
            sec_if = temp

        try: 
            linux_0.execguest("killall ping")
        except:
            pass

    def postRun(self):
        try:
            self.moveInterfaceOnto(self.getGuestFromName('linux_0'), self.vm_old_bridge)
        except:
            pass
        try: 
            self.host.execdom0("ifconfig %s up" % (self.bondDevices[0]))
        except:
            pass
        try:
            self.host.execdom0("ifconfig %s up" % (self.bondDevices[1]))
        except:
            pass
        try:
            self.host.genParamSet("pif", self.bond_pif_uuid, "other-config:bond-updelay", 200)
        except:
            pass
        try:
            self.host.execdom0("ovs-vsctl set port bond0 bond_downdelay=%s" % self.orig_down_delay)
        except:
            pass

class TC12550(_VSwitch):
    """
    Ensure vSwitch supports configuring an interface as a VLAN trunk interface.
   (An interface configured as a VLAN trunk may receive and transmit packets containing any VLAN ID)
    """


    def createVLANLink(self, guest, base_if, vlan, dhcp=True):
        guest.execguest("ip link add link %s name %s.%d type vlan id %d" % (base_if, base_if, vlan, vlan))
        if dhcp == True:
            guest.execguest("dhclient %s.%s" % (base_if, vlan))

    def removeVLANLink(self, guest, base_if, vlan):
        guest.execguest("ip link del %s.%s" % (base_if, vlan))

    def prepare(self, arglist):
        _VSwitch.prepare(self, arglist)
        if isinstance(self.host, xenrt.lib.xenserver.TampaHost):
            self.myguest = self.host.createBasicGuest("generic-linux")
        else:
            self.myguest = self.host.createBasicGuest("debian50")
        # myguest eth0 is now sitting on xenbr0 - but we want it on xenbr1 
        self.myguest.execcmd("rm -f "
                             "/etc/udev/rules.d/z25_persistent-net.rules "
                             "/etc/udev/persistent-net-generator.rules")

        self.myguest.shutdown()        
        self.myguest.removeVIF('eth0')

        # We need to identify an NSEC NIC
        nsecs = self.host.listSecondaryNICs(network="NSEC")
        if len(nsecs) == 0:
            raise xenrt.XRTError("Couldn't find NSEC NIC")

        nsecPif = self.host.getNICPIF(nsecs[0])
        nsecNet = self.host.genParamGet("pif", nsecPif, "network-uuid")
        nsecBridge = self.host.genParamGet("network", nsecNet, "bridge")
        self.myguest.createVIF(bridge=nsecBridge)
        if self.myguest.getState() == "DOWN":
            self.myguest.start()

        self.myguest.execguest("echo 'auto eth1\niface eth1 inet dhcp' >> "
                               "/etc/network/interfaces")
        self.myguest.createVIF(bridge="xenbr0", plug=True)
        self.myguest.execguest("ifup eth1")

    def run(self, arglist):
        vlan_names = ["VR01", "VR02", "VR03", "VR04", "VR05", "VR06", "VR07", "VR08", "VU01", "VU02"]

        for vlan_name in vlan_names:
            vlan_id, vlan_subnet, vlan_netmask = self.host.getVLAN(vlan_name)
            
            self.createVLANLink(self.myguest, "eth1", vlan_id)
            # get the xenrt controller ip addr for this vlan/interface
            interface = "eth0.%d" % vlan_id
            if_info = subprocess.Popen(["/sbin/ifconfig", interface], stdout=subprocess.PIPE).communicate()[0]
            xenrt_if_address = re.findall("[0-9]+.[0-9]+.[0-9]+.[0-9]+", if_info)[0]
            result = self._internalICMP(self.myguest, xenrt_if_address)
            if result[1] == 0:
                raise xenrt.XRTFailure("Failed to ping target")

        # destroy the VLAN interfaces 
        for vlan_name in vlan_names:
            vlan_id, vlan_subnet, vlan_netmask = self.host.getVLAN(vlan_name)
            self.removeVLANLink(self.myguest, "eth1", vlan_id)    

        # Q1: what happens if we ping myguest from controller first ?
        # well the route will be known by the vswitch because of the dhcp request of myguest
        # but if my guest's ip were static would the vswitch correctly route then

        for vlan_name in vlan_names:
            vlan_id, vlan_subnet, vlan_netmask = self.host.getVLAN(vlan_name)
            self.createVLANLink(self.myguest, "eth1", vlan_id, dhcp=False)
            
            # vlan addresses x.y.z.1-5 are assigned and x.y.z.10-254 are dhcp
            # machines have been found pinging 6..8 so using 9
            # hence 9 is assured to be unassigned (until someone changes the assignments)
            vlan_if_address = re.findall("[0-9]+\.[0-9]+\.[0-9]+\.", vlan_subnet)[0] + "9"

            # now statically configure the interface
            interface = "eth1.%d" % vlan_id

            self.myguest.execguest("echo 'auto %s \niface %s inet static \n"
                                       "address %s \nnetmask 255.255.255.0' "
                                       " >>/etc/network/interfaces" %
                                       (interface, interface, vlan_if_address))

            self.myguest.execguest("ifup %s" % interface)
            # Now this interface exists on the VM but no one knows that it is there

            # Now get the xenrt controller to ping the unknown address
            ping_responses = subprocess.Popen(["ping", "-w", "60", vlan_if_address], stdout=subprocess.PIPE).communicate()[0]
            xenrt.TEC().logverbose("%s" % ping_responses)
            pings = ping_responses.split("\n")
            pings.pop()
            pings.pop()
            result = pings.pop()
            data = dict([(v.strip(),int(k)) for k, v in re.findall("(\d+)([\w\s%]+)", result)])
            if 'received' in data and data['received']==0:
                raise xenrt.XRTFailure("could not reach address %s on vlan %d" % (vlan_if_address, vlan_id))

        # destroy the VLAN interfaces 
        for vlan_name in vlan_names:
            vlan_id, vlan_subnet, vlan_netmask = self.host.getVLAN(vlan_name)
            interface = "eth1.%d" % vlan_id
            self.myguest.execguest("ip link set %s down" % interface)
            self.removeVLANLink(self.myguest, "eth1", vlan_id)    


    def postRun(self):
        self.myguest.shutdown()
        self.myguest.uninstall()
        _VSwitch.postRun(self)     


class TC20958(_VSwitch):
    """ Ensure vSwitch supports configuring an interface as a VLAN trunk interface.
    An interface configured as a VLAN trunk may receive and transmit packets containing any VLAN ID)
    for diferent bond modes on the host i.e {'balance-slb }
    """
    def createVLANLink(self, guest, base_if, vlan, dhcp=True):
        guest.execguest("ip link add link %s name %s.%d type vlan id %d" % (base_if, base_if, vlan, vlan))
        if dhcp == True:
            guest.execguest("dhclient %s.%s" % (base_if, vlan))

    def removeVLANLink(self, guest, base_if, vlan):
        guest.execguest("ip link del %s.%s" % (base_if, vlan))

    def prepare(self, arglist):
        _VSwitch.prepare(self, arglist)
        if isinstance(self.host, xenrt.lib.xenserver.TampaHost):
            self.myguest = self.host.createBasicGuest("debian60")
        else:
            self.myguest = self.host.createBasicGuest("debian50")
        # myguest eth0 is now sitting on xenbr0 - but we want it on xenbr1 
        self.myguest.execcmd("rm -f "
                             "/etc/udev/rules.d/z25_persistent-net.rules "
                             "/etc/udev/persistent-net-generator.rules")

        self.myguest.shutdown()        
        self.myguest.removeVIF('eth0')

        # We need to identify  NSEC NIC for bonding
        # NSEC nics are trunked switch port which will get all VLAN packets
        nsecs = self.host.listSecondaryNICs(network="NSEC")
        if len(nsecs) < 2:
            raise xenrt.XRTError("Couldn't find 2 NSEC NIC for bonding")
        
        nsecs = nsecs[0:2]
        pifs = map(lambda n: self.host.getNICPIF(n), nsecs)
        bondbridge, bondDevice = self.host.createBond(pifs, mode='balance-slb')
        self.myguest.createVIF(bridge=bondbridge)
        if self.myguest.getState() == "DOWN":
            self.myguest.start()

        self.myguest.execguest("echo 'auto eth1\niface eth1 inet dhcp' >> "
                               "/etc/network/interfaces")
        self.myguest.createVIF(bridge="xenbr0", plug=True)
        self.myguest.execguest("ifup eth1")

    def run(self, arglist):
        vlan_names = ["VR01", "VR02", "VR03", "VR04", "VR05", "VR06", "VR07", "VR08", "VU01", "VU02"]

        for vlan_name in vlan_names:
            vlan_id, vlan_subnet, vlan_netmask = self.host.getVLAN(vlan_name)
            
            self.createVLANLink(self.myguest, "eth1", vlan_id)
            # get the xenrt controller ip addr for this vlan/interface
            interface = "eth0.%d" % vlan_id
            if_info = subprocess.Popen(["/sbin/ifconfig", interface], stdout=subprocess.PIPE).communicate()[0]
            xenrt_if_address = re.findall("[0-9]+.[0-9]+.[0-9]+.[0-9]+", if_info)[0]
            result = self._internalICMP(self.myguest, xenrt_if_address)
            if result[1] == 0:
                raise xenrt.XRTFailure("Failed to ping target")

        # destroy the VLAN interfaces 
        for vlan_name in vlan_names:
            vlan_id, vlan_subnet, vlan_netmask = self.host.getVLAN(vlan_name)
            self.removeVLANLink(self.myguest, "eth1", vlan_id)    

        # Q1: what happens if we ping myguest from controller first ?
        # well the route will be known by the vswitch because of the dhcp request of myguest
        # but if my guest's ip were static would the vswitch correctly route then

        for vlan_name in vlan_names:
            vlan_id, vlan_subnet, vlan_netmask = self.host.getVLAN(vlan_name)
            self.createVLANLink(self.myguest, "eth1", vlan_id, dhcp=False)
            
            # vlan addresses x.y.z.1-5 are assigned and x.y.z.10-254 are dhcp
            # machines have been found pinging 6..8 so using 9
            # hence 9 is assured to be unassigned (until someone changes the assignments)
            vlan_if_address = re.findall("[0-9]+\.[0-9]+\.[0-9]+\.", vlan_subnet)[0] + "9"

            # now statically configure the interface
            interface = "eth1.%d" % vlan_id

            self.myguest.execguest("echo 'auto %s \niface %s inet static \n"
                                       "address %s \nnetmask 255.255.255.0' "
                                       " >>/etc/network/interfaces" %
                                       (interface, interface, vlan_if_address))

            self.myguest.execguest("ifup %s" % interface)
            # Now this interface exists on the VM but no one knows that it is there

            # Now get the xenrt controller to ping the unknown address
            ping_responses = subprocess.Popen(["ping", "-w", "60", vlan_if_address], stdout=subprocess.PIPE).communicate()[0]
            xenrt.TEC().logverbose("%s" % ping_responses)
            pings = ping_responses.split("\n")
            pings.pop()
            pings.pop()
            result = pings.pop()
            data = dict([(v.strip(),int(k)) for k, v in re.findall("(\d+)([\w\s%]+)", result)])
            if 'received' in data and data['received']==0:
                raise xenrt.XRTFailure("could not reach address %s on vlan %d" % (vlan_if_address, vlan_id))

        # destroy the VLAN interfaces 
        for vlan_name in vlan_names:
            vlan_id, vlan_subnet, vlan_netmask = self.host.getVLAN(vlan_name)
            interface = "eth1.%d" % vlan_id
            self.myguest.execguest("ifdown %s" % interface)
            self.removeVLANLink(self.myguest, "eth1", vlan_id)    
       

    def postRun(self):
        bonds = self.host.getBonds()
        for bond in bonds:
            self.host.removeBond(bond)
        self.myguest.shutdown()
        self.myguest.uninstall()
        _VSwitch.postRun(self)     

class TC20996(_VSwitch):
    """ Ensure vSwitch supports configuring an interface as a VLAN trunk interface.
    An interface configured as a VLAN trunk may receive and transmit packets containing any VLAN ID)
    """
    def createVLANLink(self, guest, base_if, vlan, dhcp=True):
        guest.execguest("ip link add link %s name %s.%d type vlan id %d" % (base_if, base_if, vlan, vlan))
        if dhcp == True:
            guest.execguest("dhclient %s.%s" % (base_if, vlan))

    def removeVLANLink(self, guest, base_if, vlan):
        guest.execguest("ip link del %s.%s" % (base_if, vlan))

    def prepare(self, arglist):
        _VSwitch.prepare(self, arglist)
        if isinstance(self.host, xenrt.lib.xenserver.TampaHost):
            self.myguest = self.host.createBasicGuest("debian60")
        else:
            self.myguest = self.host.createBasicGuest("debian50")
        # myguest eth0 is now sitting on xenbr0 - but we want it on xenbr1 
        self.myguest.execcmd("rm -f "
                             "/etc/udev/rules.d/z25_persistent-net.rules "
                             "/etc/udev/persistent-net-generator.rules")

        self.myguest.shutdown()        
        self.myguest.removeVIF('eth0')

        # We need to identify  NSEC NIC for bonding
        # NSEC nics are trunked switch port which will get all VLAN packets
        nsecs = self.host.listSecondaryNICs(network="NSEC")
        if len(nsecs) < 2:
            raise xenrt.XRTError("Couldn't find 2 NSEC NIC for bonding")
        
        nsecs = nsecs[0:2]
        pifs = map(lambda n: self.host.getNICPIF(n), nsecs)
        bondbridge, bondDevice = self.host.createBond(pifs, mode='active-backup')
        self.myguest.createVIF(bridge=bondbridge)
        if self.myguest.getState() == "DOWN":
            self.myguest.start()

        self.myguest.execguest("echo 'auto eth1\niface eth1 inet dhcp' >> "
                               "/etc/network/interfaces")
        self.myguest.createVIF(bridge="xenbr0", plug=True)
        self.myguest.execguest("ifup eth1")

    def run(self, arglist):
        vlan_names = ["VR01", "VR02", "VR03", "VR04", "VR05", "VR06", "VR07", "VR08", "VU01", "VU02"]

        for vlan_name in vlan_names:
            vlan_id, vlan_subnet, vlan_netmask = self.host.getVLAN(vlan_name)
            
            self.createVLANLink(self.myguest, "eth1", vlan_id)
            # get the xenrt controller ip addr for this vlan/interface
            interface = "eth0.%d" % vlan_id
            if_info = subprocess.Popen(["/sbin/ifconfig", interface], stdout=subprocess.PIPE).communicate()[0]
            xenrt_if_address = re.findall("[0-9]+.[0-9]+.[0-9]+.[0-9]+", if_info)[0]
            result = self._internalICMP(self.myguest, xenrt_if_address)
            if result[1] == 0:
                raise xenrt.XRTFailure("Failed to ping target")

        # destroy the VLAN interfaces 
        for vlan_name in vlan_names:
            vlan_id, vlan_subnet, vlan_netmask = self.host.getVLAN(vlan_name)
            self.removeVLANLink(self.myguest, "eth1", vlan_id)    

        # Q1: what happens if we ping myguest from controller first ?
        # well the route will be known by the vswitch because of the dhcp request of myguest
        # but if my guest's ip were static would the vswitch correctly route then

        for vlan_name in vlan_names:
            vlan_id, vlan_subnet, vlan_netmask = self.host.getVLAN(vlan_name)
            self.createVLANLink(self.myguest, "eth1", vlan_id, dhcp=False)
            
            # vlan addresses x.y.z.1-5 are assigned and x.y.z.10-254 are dhcp
            # machines have been found pinging 6..8 so using 9
            # hence 9 is assured to be unassigned (until someone changes the assignments)
            vlan_if_address = re.findall("[0-9]+\.[0-9]+\.[0-9]+\.", vlan_subnet)[0] + "9"

            # now statically configure the interface
            interface = "eth1.%d" % vlan_id

            self.myguest.execguest("echo 'auto %s \niface %s inet static \n"
                                       "address %s \nnetmask 255.255.255.0' "
                                       " >>/etc/network/interfaces" %
                                       (interface, interface, vlan_if_address))

            self.myguest.execguest("ifup %s" % interface)
            # Now this interface exists on the VM but no one knows that it is there

            # Now get the xenrt controller to ping the unknown address
            ping_responses = subprocess.Popen(["ping", "-w", "60", vlan_if_address], stdout=subprocess.PIPE).communicate()[0]
            xenrt.TEC().logverbose("%s" % ping_responses)
            pings = ping_responses.split("\n")
            pings.pop()
            pings.pop()
            result = pings.pop()
            data = dict([(v.strip(),int(k)) for k, v in re.findall("(\d+)([\w\s%]+)", result)])
            if 'received' in data and data['received']==0:
                raise xenrt.XRTFailure("could not reach address %s on vlan %d" % (vlan_if_address, vlan_id))

        # destroy the VLAN interfaces 
        for vlan_name in vlan_names:
            vlan_id, vlan_subnet, vlan_netmask = self.host.getVLAN(vlan_name)
            interface = "eth1.%d" % vlan_id
            self.myguest.execguest("ifdown %s" % interface)
            self.removeVLANLink(self.myguest, "eth1", vlan_id)    
        
    def postRun(self):
        bonds = self.host.getBonds()
        for bond in bonds:
            self.host.removeBond(bond)
        self.myguest.shutdown()
        self.myguest.uninstall()
        _VSwitch.postRun(self)     


class TC20997(_VSwitch):
    """ Ensure vSwitch supports configuring an interface as a VLAN trunk interface.
    An interface configured as a VLAN trunk may receive and transmit packets containing any VLAN ID)
    """
    def createVLANLink(self, guest, base_if, vlan, dhcp=True):
        guest.execguest("ip link add link %s name %s.%d type vlan id %d" % (base_if, base_if, vlan, vlan))
        if dhcp == True:
            guest.execguest("dhclient %s.%s" % (base_if, vlan))

    def removeVLANLink(self, guest, base_if, vlan):
        guest.execguest("ip link del %s.%s" % (base_if, vlan))

    def prepare(self, arglist):
        _VSwitch.prepare(self, arglist)
        if isinstance(self.host, xenrt.lib.xenserver.TampaHost):
            self.myguest = self.host.createBasicGuest("debian60")
        else:
            self.myguest = self.host.createBasicGuest("debian50")
        # myguest eth0 is now sitting on xenbr0 - but we want it on xenbr1 
        self.myguest.execcmd("rm -f "
                             "/etc/udev/rules.d/z25_persistent-net.rules "
                             "/etc/udev/persistent-net-generator.rules")

        self.myguest.shutdown()        
        self.myguest.removeVIF('eth0')

        # We need to identify  NSEC NIC for bonding
        # NSEC nics are trunked switch port which will get all VLAN packets
        nsecs = self.host.listSecondaryNICs(network="NSEC")
        if len(nsecs) < 2:
            raise xenrt.XRTError("Couldn't find 2 NSEC NIC for bonding")
        
        nsecs = nsecs[0:2]
        pifs = map(lambda n: self.host.getNICPIF(n), nsecs)
        bondbridge, bondDevice = self.host.createBond(pifs, mode='lacp')
        self.myguest.createVIF(bridge=bondbridge)
        if self.myguest.getState() == "DOWN":
            self.myguest.start()

        self.myguest.execguest("echo 'auto eth1\niface eth1 inet dhcp' >> "
                               "/etc/network/interfaces")
        self.myguest.createVIF(bridge="xenbr0", plug=True)
        self.myguest.execguest("ifup eth1")

    def run(self, arglist):
        vlan_names = ["VR01", "VR02", "VR03", "VR04", "VR05", "VR06", "VR07", "VR08", "VU01", "VU02"]

        for vlan_name in vlan_names:
            vlan_id, vlan_subnet, vlan_netmask = self.host.getVLAN(vlan_name)
            
            self.createVLANLink(self.myguest, "eth1", vlan_id)
            # get the xenrt controller ip addr for this vlan/interface
            interface = "eth0.%d" % vlan_id
            if_info = subprocess.Popen(["/sbin/ifconfig", interface], stdout=subprocess.PIPE).communicate()[0]
            xenrt_if_address = re.findall("[0-9]+.[0-9]+.[0-9]+.[0-9]+", if_info)[0]
            result = self._internalICMP(self.myguest, xenrt_if_address)
            if result[1] == 0:
                raise xenrt.XRTFailure("Failed to ping target")

        # destroy the VLAN interfaces 
        for vlan_name in vlan_names:
            vlan_id, vlan_subnet, vlan_netmask = self.host.getVLAN(vlan_name)
            self.removeVLANLink(self.myguest, "eth1", vlan_id)    

        # Q1: what happens if we ping myguest from controller first ?
        # well the route will be known by the vswitch because of the dhcp request of myguest
        # but if my guest's ip were static would the vswitch correctly route then

        for vlan_name in vlan_names:
            vlan_id, vlan_subnet, vlan_netmask = self.host.getVLAN(vlan_name)
            self.createVLANLink(self.myguest, "eth1", vlan_id, dhcp=False)
            
            # vlan addresses x.y.z.1-5 are assigned and x.y.z.10-254 are dhcp
            # machines have been found pinging 6..8 so using 9
            # hence 9 is assured to be unassigned (until someone changes the assignments)
            vlan_if_address = re.findall("[0-9]+\.[0-9]+\.[0-9]+\.", vlan_subnet)[0] + "9"

            # now statically configure the interface
            interface = "eth1.%d" % vlan_id

            self.myguest.execguest("echo 'auto %s \niface %s inet static \n"
                                       "address %s \nnetmask 255.255.255.0' "
                                       " >>/etc/network/interfaces" %
                                       (interface, interface, vlan_if_address))

            self.myguest.execguest("ifup %s" % interface)
            # Now this interface exists on the VM but no one knows that it is there

            # Now get the xenrt controller to ping the unknown address
            ping_responses = subprocess.Popen(["ping", "-w", "60", vlan_if_address], stdout=subprocess.PIPE).communicate()[0]
            xenrt.TEC().logverbose("%s" % ping_responses)
            pings = ping_responses.split("\n")
            pings.pop()
            pings.pop()
            result = pings.pop()
            data = dict([(v.strip(),int(k)) for k, v in re.findall("(\d+)([\w\s%]+)", result)])
            if 'received' in data and data['received']==0:
                raise xenrt.XRTFailure("could not reach address %s on vlan %d" % (vlan_if_address, vlan_id))

        # destroy the VLAN interfaces 
        for vlan_name in vlan_names:
            vlan_id, vlan_subnet, vlan_netmask = self.host.getVLAN(vlan_name)
            interface = "eth1.%d" % vlan_id
            self.myguest.execguest("ifdown %s" % interface)
            self.removeVLANLink(self.myguest, "eth1", vlan_id)    

    def postRun(self):
        bonds = self.host.getBonds()
        for bond in bonds:
            self.host.removeBond(bond)
        self.myguest.shutdown()
        self.myguest.uninstall()
        _VSwitch.postRun(self)     

class TCFlowEvictionThreshold(xenrt.TestCase):
    """Apply non-default flow-eviction threshold. 
       By default, OVS will keep only up to 1000 flows in the kernel. 
       This number can be changed by altering flow-eviction-threshold. """
       
        #Kernel space doesn't have the control over the flows cached.Its the user space which dictates the deletion of flows.
        #It might take a while for the user space to delete flows above the flow-eviction-threshold.
        #So waiting for 2 seconds. If flow-eviction-threshold is 1000, then dump-flows is expected to be around ~1400
    
    def prepare(self,arglist):
        self.nbrOfIterations = 10
        self.flowEvictionThresholdDefault = 1000
        self.flowEvictionThresholdDefaultTampa = 2500
        self.flowEvictionThresholdCustom = 2000

        self.host = self.getDefaultHost()
        self.targetVM = self.getGuest('linux_1')
        self.sourceVM = self.getGuest('linux_0')
        self.targetIP = self.targetVM.getIP()
        self.scriptFile = "/tmp/flood.py"
        self.flowLogFile = "/tmp/flows.log"
        
        #prepare script on guest to generate flows
        self.prepareFlowGenerator(self.sourceVM)
        
        #add flows script and data file to logs.
        self.getLogsFrom(self.sourceVM, [self.scriptFile])
        self.getLogsFrom(self.host, [self.flowLogFile])

    def prepareFlowGenerator(self, guest):
        """copy python script on sourceVM which can be used to generate flows by sending IP packets to targetVM."""
        script = """#!/usr/bin/python
import socket,random,sys,time
duration = 5
targetIP = sys.argv[1]
qClock = (lambda:0, time.clock)[duration > 0]
duration = (1, (qClock() + duration))[duration > 0]
qSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
while (qClock() < duration):
    pktSize = random._urandom(1024)
    pport =  random.randint(1,65500)
    for i in range(5):
        qSocket.sendto(pktSize, (targetIP, pport))
"""
        #Create file on guest and copy python script
        xenrt.ssh.createFile(guest, script, self.scriptFile)

    def run(self,arglist):
        """Generate flows and check if the number of flows in the kernel corresponds to the value of flow-eviction-threshold"""
        
        if isinstance(self.host, xenrt.lib.xenserver.TampaHost): 
            flowEvictionThreshold = self.flowEvictionThresholdDefaultTampa
        else:
            flowEvictionThreshold = self.flowEvictionThresholdDefault

        step("Check flow count to ensure default flow-eviction-threshold is working.")
        self.checkFlowCount(self.host, flowEvictionThreshold , (flowEvictionThreshold+400))

        step("change flows eviction threshold to %d" % self.flowEvictionThresholdCustom)
        flowEvictionThreshold = self.flowEvictionThresholdCustom
        self.host.execdom0("ovs-vsctl set bridge xenbr0 other-config:flow-eviction-threshold=%d" % flowEvictionThreshold)
        xenrt.sleep(5)

        step("Check flow count to ensure changed flow-eviction-threshold is working.")
        self.checkFlowCount(self.host, flowEvictionThreshold , (flowEvictionThreshold+400))

    def checkFlowCount(self, host, min, max):
        """This function verifies if flows of ovs is within range(min, max)"""

        inRangeSuccess = 0
        flowData = []

        # Fetch flow count
        for i in range(self.nbrOfIterations):
            self.sourceVM.execcmd("python %s %s" % (self.scriptFile,self.targetIP))
            host.execdom0('echo "[`date -u`] ovs-dpctl dump-flows xenbr0" >> %s' % self.flowLogFile)
            host.execdom0('ovs-dpctl dump-flows xenbr0 >>  %s' % self.flowLogFile)
            for j in range(3):
                flows = int(host.execdom0("ovs-dpctl dump-flows xenbr0 | wc -l"))
                if (flows > min and flows < max):
                    inRangeSuccess = inRangeSuccess +1
                    break
            flowData.append(flows)

        inRangeSuccess = inRangeSuccess * 100 / len(flowData)
        avg = sum(flowData)/len(flowData)

        log("STATS: list containing flows count : %s" % (flowData))
        log("STATS: Percentage of flows in range [%d - %d]: %d, avg = %d " % (min, max,inRangeSuccess,avg) )

        if inRangeSuccess < 50:
            raise xenrt.XRTFailure("Unexpected average flows: %d, expected in range %d to %d. Percentage of flows in range: %d" % (avg, min, max,inRangeSuccess))

class NetworkThroughputwithGRO(_VSwitch):
    SOURCE = "centos57"
    TARGET = "centos64"
    DURATION = 10 # Stick to the defaults
    TXHASNONSEC=True # Assume that rx does not have any NSECs
    NICSNOTTESTED=[]

    def setGRO(self, host, nic="eth0", state="on"):
        cli = host.getCLIInstance()
        pifuuid = cli.execute("pif-list", "host-uuid=%s device=%s --minimal" %
                            (host.uuid, nic)).strip()
        cli.execute("pif-param-set", "uuid=%s properties:gro='%s'" %
                    (pifuuid, state))

        # Verify GRO is set to the desired state
        currstate = host.execdom0("ethtool -k %s | grep 'generic-receive-offload' | cut -d ':' -f 2" %nic).strip()
        return currstate == state
    
    def addVIF(self, guest, id):
        """Adds a VIF to the guest on a particular bridge and assigns it an IP.
           For different distros, we need different measure to ensure the VIF gets an IP"""

        #Check if it's possible to add any more VIFs to the VM   
        if guest.getHost().genParamGet("vm", guest.getUUID(), "allowed-VIF-devices"):
            device = guest.createVIF(bridge="xenbr%d" %id, plug=True)
            if guest.windows: return #No complications for windows

            #Different ways of handling different Linux VMs
            if re.search("centos", guest.distro):
                guest.execguest("echo 'DEVICE=%s' > /etc/sysconfig/network-scripts/ifcfg-%s" %(device,device))
                guest.execguest("echo 'BOOTPROTO=dhcp' >> /etc/sysconfig/network-scripts/ifcfg-%s" %device)
                guest.execguest("echo 'ONBOOT=yes' >> /etc/sysconfig/network-scripts/ifcfg-%s" %device) 
                guest.execguest("echo 'TYPE=ethernet' >> /etc/sysconfig/network-scripts/ifcfg-%s" %device)

            elif re.search("sles", guest.distro):
                guest.execguest("echo 'DEVICE=%s' > /etc/sysconfig/network/ifcfg-%s" %(device,device))
                guest.execguest("echo 'BOOTPROTO=dhcp4' >> /etc/sysconfig/network/ifcfg-%s" %device)
                guest.execguest("echo 'STARTMODE=onboot' >> /etc/sysconfig/network/ifcfg-%s" %device)

            elif re.search("ubuntu", guest.distro):
                guest.execguest("echo 'auto %s' >> /etc/network/interfaces" %device)
                guest.execguest("echo 'iface %s inet dhcp' >> /etc/network/interfaces" %device)
            guest.execguest("ifconfig %s up" %device)
           
    def runThroughput(self, nic1, nic2, rx_nic):
        """Measures network throughput (with GRO enabled) for rx_nic (on rx) with nic1 enabled and nic2 disabled on tx"""

        #Set the main ip to the ip on nic1 vif
        self.tx.mainip = self.tx.execguest("ifconfig %s | grep 'inet addr' | awk -F: '{print $2}' | awk '{print $1}'" % nic1).strip()
        if not self.tx.mainip:
            raise xenrt.XRTFailure("No IP found for tx %s vif" %nic1)
        if nic2 <> None:
            self.tx.execguest("ifconfig %s down" % nic2)
        vif = self.rx.getVIF(bridge="xenbr%d" % rx_nic)

        #Run the throughput tests (with GRO off and on) for rx_nic
        step("Testing GRO disabled throughput for nic %d (on rx)" %rx_nic)
        self.setGRO(self.host2, "eth%d" %rx_nic, state='off')

        res = self._internalNetperf(test="TCP_STREAM", 
                                    source=self.tx, target=vif[1])
        log("Results with GRO disabled for nic %d (on rx): %s" % 
            (rx_nic,str(res)))

        #Enable GRO on rx_nic
        if not self.setGRO(self.host2, "eth%d" %rx_nic, state='on'):
            raise xenrt.XRTFailure("Failure while enabling gro on host 2 - %s, NIC %d" % 
                                    (self.host2,rx_nic))

        step("Testing GRO enabled throughput for nic %d (on rx)" % rx_nic)
        res = self._internalNetperf(test="TCP_STREAM", 
                                    source=self.tx, target=vif[1])
        log("Results with GRO enabled for nic %d (on rx): %s" % 
            (rx_nic,str(res)))

        if nic2 <> None :
            self.tx.execguest("ifconfig %s up" %nic2)
        if res[1] == 0.0:
            xenrt.TEC().warning("Netperf test (with GRO enabled) between %s and %s on nic %d (on rx) returned 0" %
                                    (self.SOURCE, self.TARGET, rx_nic))
            self.NICSNOTTESTED.append(rx_nic)
        
    def prepare(self, arglist=None):
        self.host1 = self.getHost("RESOURCE_HOST_0")
        self.host2 = self.getHost("RESOURCE_HOST_1")
        self.tx = self.host1.createBasicGuest(distro=self.SOURCE)
        self.rx = self.host2.createBasicGuest(distro=self.TARGET)
        
        #Add one NSEC vif to tx
        nics = self.host1.listSecondaryNICs(network='NSEC')
        if nics:
            self.addVIF(self.tx, nics[0])
            self.tx.reboot()
            self.TXHASNONSEC=False
        #Add vifs (on all on nics) to rx
        nics = self.host2.listSecondaryNICs()
        map(lambda x: self.addVIF(self.rx, x), nics)
        if self.TARGET == "w2k3eesp2": #Need to update the drivers for a Legacy Win VM
            time.sleep(60)
            self.rx.updateVIFDriver()
        self.rx.reboot()
      
        # Turn off the GRO on all the NICS on rx host
        if False in map(lambda x: self.setGRO(self.host2, "eth%d" %x, state='off'), [0]+self.host2.listSecondaryNICs()):
            raise xenrt.XRTFailure("Failure while disabling gro on host 2 - %s" % self.host2)
    
        # Install netperf
        time.sleep(60)
        guests = self.tx, self.rx
        self.prepareGuests(guests=guests)

    def run(self, arglist=None):

        # Let the netserver run on the rx and measure throughput from tx
        self.tx.execguest("killall netserver")
        # Stop iptables
        try:
            self.rx.execguest("service iptables stop")
        except Exception,e:
            log("No service in the name of iptables")
        
        #Throughtput for all NICs on NPRI/NSEC
        for (mac, ip, bridge) in self.rx.getVIFs().values():
            #Extract the NIC id for the VIFs on rx
            nic = int(re.search(r"(\d+)", bridge).group(1))
            #If it's NIC0 or on the NPRI network, then disable the eth1 interface on tx
            if not nic or self.host2.lookup(["NICS", "NIC%d" %nic, "NETWORK"], None)=="NPRI":
                if not self.TXHASNONSEC:
                    self.runThroughput("eth0", "eth1", nic)
                else:
                    self.runThroughput("eth0", None, nic)
            #If it's on the NSEC network, then disable the eth0 interface on tx
            elif self.host2.lookup(["NICS", "NIC%d" %nic, "NETWORK"], None)=="NSEC":
                if not self.TXHASNONSEC:
                    self.runThroughput("eth1", "eth0", nic)
                else:
                    xenrt.TEC().warning("Unable to test NSEC on RX since the TX has no nsec networks")

        if self.NICSNOTTESTED:
            raise xenrt.XRTFailure("The following nics on host %s were not tested - %s" %
                                    (self.host2, self.NICSNOTTESTED))

    def postRun(self):
        self.host1.uninstallAllGuests()
        self.host2.uninstallAllGuests()

class NetworkThroughputwithGroOn(NetworkThroughputwithGRO):

    def prepare(self, arglist=None):
        self.host1 = self.getHost("RESOURCE_HOST_0")
        self.host2 = self.getHost("RESOURCE_HOST_1")        
        self.tx = self.host1.createBasicGuest(distro=self.SOURCE)
        self.rx = self.host2.createBasicGuest(distro=self.TARGET)
        
        #Retreive MAC for the eth0 of both the vms         
        vuuid = self.host1.parseListForUUID("vif-list","vm-uuid",self.tx.getUUID(),"device=0" )        
        self.tx_mac  = self.host1.genParamGet("vif", vuuid, "MAC")
        vuuid = self.host2.parseListForUUID("vif-list","vm-uuid",self.rx.getUUID(),"device=0" )        
        self.rx_mac  = self.host2.genParamGet("vif", vuuid, "MAC")
        
        # Turn off the GRO on all the NICS on rx host
        if False in map(lambda x: self.setGRO(self.host2, "eth%d" %x, state='off'), [0]+self.host2.listSecondaryNICs()):
            raise xenrt.XRTFailure("Failure while disabling gro on host 2 - %s" % self.host2)
        
        # Install netperf
        time.sleep(60)
        guests = self.tx, self.rx
        self.prepareGuests(guests=guests)
        
    def run(self, arglist=None):
        
        # Let the netserver run on the rx and measure throughput from tx
        self.tx.execguest("killall netserver")
        # Stop iptables
        try:
            self.rx.execguest("service iptables stop")
        except Exception,e:
            log("No service in the name of iptables")            
        
        xenrt.log("Measure throughput for nic 0")
        self.runThroughput(0)
        
        rx_nics = self.host2.listSecondaryNICs()
        tx_nics = self.host1.listSecondaryNICs()
        
        #If tx host has lesser number of secondary NICS in connected state than rx host then test only for the lesser number of NICS.
        if len(tx_nics) < len(rx_nics):
            rx_nics = tx_nics
            
        #Measure throughput for all the secondary NICS available on receiving host
        for nic in rx_nics :
            #Ensure that we have only those vifs attached to BOTH the vms that we want to test
            self.tx.unplugVIF("eth0")
            self.tx.removeVIF("eth0")
            self.rx.unplugVIF("eth0")
            self.rx.removeVIF("eth0")
            #Create the vif associated with the nic to be tested on both the vms 
            self.tx.createVIF(bridge="xenbr%d"%nic,plug=True, mac=self.tx_mac)
            #Unset mainip and reboot the guest so it the new ip gets populated to mainip
            self.tx.mainip = None
            self.tx.reboot()
            self.rx.createVIF(bridge="xenbr%d"%nic,plug=True, mac=self.rx_mac)
            self.rx.mainip = None
            self.rx.reboot()
            if self.TARGET == "w2k3eesp2": #Need to update the drivers for a Legacy Win VM                
                self.rx.updateVIFDriver()
                self.rx.reboot()            
            if not self.rx.windows:
                self.rx.execguest("netserver -p %s" % (self.PORT))
            else:
                self.rx.xmlrpcExec("START C:\\netserver -p %s" % self.PORT)
            
            #Measure throughput for the current nic 
            self.runThroughput(nic)
            
        if self.NICSNOTTESTED:
            raise xenrt.XRTFailure("The following nics on host %s were not tested - %s" %
                                    (self.host2, self.NICSNOTTESTED))
    
    def runThroughput(self, rx_nic):
        """Measures network throughput for rx_nic with only rx_nic connected to both the vms"""
        #Set the main ip to the ip on nic0 vif
        self.tx.mainip = self.tx.execguest("ifconfig eth0 | grep 'inet addr' | awk -F: '{print $2}' | awk '{print $1}'" ).strip()
        if not self.tx.mainip:
            raise xenrt.XRTFailure("No IP found for tx eth0 vif" )
        
        vif = self.rx.getVIF(bridge="xenbr%d"%rx_nic)

        #Run the throughput tests (with GRO off and on) for rx_nic
        step("Testing GRO disabled throughput for nic %d (on rx)" %rx_nic)
        self.setGRO(self.host2, "eth%d" %rx_nic, state='off')

        res = self._internalNetperf(test="TCP_STREAM", 
                                    source=self.tx, target=vif[1])
        log("Results with GRO disabled for nic %d (on rx): %s" % 
            (rx_nic,str(res)))

        #Enable GRO on rx_nic
        if not self.setGRO(self.host2, "eth%d" %rx_nic, state='on'):
            raise xenrt.XRTFailure("Failure while enabling gro on host 2 - %s, NIC %d" % 
                                    (self.host2,rx_nic))

        step("Testing GRO enabled throughput for nic %d (on rx)" %rx_nic)
        res = self._internalNetperf(test="TCP_STREAM", 
                                    source=self.tx, target=vif[1])
        log("Results with GRO enabled for nic %d (on rx): %s" % 
            (rx_nic,str(res)))
            
        if res[1] == 0.0:
            xenrt.TEC().warning("Netperf test (with GRO enabled) between %s and %s on nic %d (on rx) returned 0" %
                                    (self.SOURCE, self.TARGET, rx_nic))
            self.NICSNOTTESTED.append(rx_nic)
            

class TC19993(NetworkThroughputwithGroOn):
    SOURCE="centos57"
    TARGET="sles111"

class TC19994(NetworkThroughputwithGroOn):
    SOURCE="centos64"
    TARGET="ubuntu1204"

class TC20874(NetworkThroughputwithGroOn):
    SOURCE="centos64"
    TARGET="win7sp1-x86"
    
class TC20877(NetworkThroughputwithGroOn):
    SOURCE="centos64"
    TARGET="win8-x64"

class TC20875(NetworkThroughputwithGroOn):
    SOURCE="centos64"
    TARGET="w2k3eesp2"

class SRTrafficwithGRO(NetworkThroughputwithGRO):
    """ Create an SR VM on host1 with the requested SR type - iscsi or nfs
        Add the relevant additional vifs to the SR VM, make sure they are up
        Attach the SR created, to host2 and verify that a VM can be installed 
        successfully on the shared SR.
        Repeat attach and create VM for all the vifs present"""
        
    TYPE="iscsi"
    def prepare(self, arglist=None):
        self.host = self.getHost("RESOURCE_HOST_0")
        self.srhost = self.getHost("RESOURCE_HOST_1")
        self.pifs={}

        # Create a VM with all the 'connected' Nic cards on the host
        # This VM will act as the shared storage
        self.srvm = self.vmAddAditionalNics(iethost=self.srhost)

    def vmAddAditionalNics(self, iethost, distro='debian60'):
        srvm=iethost.createBasicGuest(name="SRVM", 
                                        distro=distro, 
                                        disksize=60 * 1024)

        # Construct a dict with the type of network the pif belongs to
        if len(iethost.listSecondaryNICs("NPRI")):
            self.pifs["NPRI"] = iethost.genParamGet("network", 
                                                iethost.getManagementNetworkUUID(), 
                                                "PIF-uuids")
        if len(iethost.listSecondaryNICs("NSEC")):
            self.pifs["NSEC"] = iethost.getNICPIF(iethost.listSecondaryNICs("NSEC")[0])

        # Create the SR VM with 1 NRPI and 1 NSEC
        if self.pifs.has_key('NSEC'):
            # Create the 2nd NSEC vif as eth1
            eth="eth1"
            network=iethost.genParamGet("pif",
                                    self.pifs['NSEC'],
                                    "network-uuid").strip()
            # Create and add vifs for NSEC only, the default is already there
            if not re.search(eth, iethost.getDefaultInterface(), re.I):
                srvm.createVIF(eth=eth, 
                                bridge=iethost.genParamGet("network", network,"bridge").strip(), 
                                plug=True)
                srvm.execguest("echo 'auto %s' >> /etc/network/interfaces" % 
                                eth)
                srvm.execguest("echo 'iface %s inet dhcp' >> /etc/network/interfaces" % 
                                eth)
                srvm.execguest("ifup %s" % eth)
                # Add some sleep to slow down
                time.sleep (60)
        srvm.reboot()
        return srvm

    def ietGuestSetup(self, iHost, ietvm):
        """Setup an iet target""" 
        iqn=ietvm.installLinuxISCSITarget()
        ietvm.createISCSITargetLun(0, 30 * 1024, thickProvision=False, timeout=2700)
        cli=iHost.getCLIInstance()
        # Probe to get the scsi id
        try:
            cli.execute("sr-probe", "type=lvmoiscsi device-config:target=%s device-config:targetIQN=%s" % 
                        (ietvm.getIP(), iqn))
        except Exception, e:
            xml_response=e.data

        xenrt.log(xml_response.split('<?')[1])
        dom = xml.dom.minidom.parseString('<?' + xml_response.split('<?')[1])
        luns = dom.getElementsByTagName("LUN")
        id=luns[0].getElementsByTagName("SCSIid")
        return iqn, id[0].childNodes[0].data.strip()

    def nfsDirSetup(self, nfsvm):
        """Setup an nfs share on the VM"""
        dir="/nfssr"
        nfsvm.installPackages(["nfs-kernel-server","nfs-common","portmap"])

        # Create a dir and export it
        nfsvm.execguest("mkdir %s" % dir)
        nfsvm.execguest("echo '%s *(sync,rw,no_root_squash,no_subtree_check)'"
                        " > /etc/exports" % dir)
        nfsvm.execguest("/etc/init.d/portmap start || /etc/init.d/rpcbind start")
        nfsvm.execguest("/etc/init.d/nfs-common start || true")
        nfsvm.execguest("/etc/init.d/nfs-kernel-server start || true")
        
        return dir

    def run(self, arglist=None):
        ips={}
        nicNotTested=[]

        # Get the list of IPs for all the vifs attached to the SR VM
        vif=self.srvm.getVIFs()
        xenrt.log("Our SR guest has been setup with the following vifs - %s " % vif)
        assumedids=self.host.listSecondaryNICs()
        # Dont forget to test the default interface
        assumedids.append(0)

        # Setup requested storage type - nfs or iscsi on the SRVM
        if re.search(self.TYPE,"nfs", re.I):
            nfsDir=self.nfsDirSetup(nfsvm=self.srvm)
        else:
            self.iqn, scsiId=self.ietGuestSetup(iHost=self.host, 
                                                ietvm=self.srvm)

        for id in assumedids:
            installFlag=1

            xenrt.log("Running test for interface %s in network %s" %
                        (self.host.getNIC(id), self.host.getNICNetworkName(id)))
            # Get ready to test traffic through the NICs on host2
            managementPIF = self.host.parseListForUUID("pif-list",
                                                        "management",
                                                        "true",
                                                        "host-uuid=%s" %
                                                        (self.host.getMyHostUUID()))
            managementNIC = self.host.genParamGet("pif", 
                                                    managementPIF, 
                                                    "device")

            if managementNIC !=  self.host.getNIC(id):
                xenrt.log("Current management NIC is %s\n"
                            "Need to change the management interface to %s" % 
                            (managementNIC, self.host.getNIC(id)))
                self.host.changeManagementInterface(self.host.getNIC(id))

            # Check if the Nic being tested is NPRI to avoid cross-network tests
            # It is okay to assume eth1 is NSEC since the NSEC vif is created as eth1 in prepare
            if self.host.getNICNetworkName(id) == "NSEC":
                if self.pifs.has_key('NSEC'):
                    ip = [j[1] for i,j in vif.iteritems() if i == "eth1"][0]
                else:
                    ip=None
            else:
                ip = [j[1] for i,j in vif.iteritems() if i == self.srhost.genParamGet("pif",self.pifs['NPRI'],"device")][0]

            if re.search(self.TYPE,"iscsi", re.I):
                # Set up the SR on the host, plug the pbd etc
                sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host,
                                                                    "test-iscsi")
                lun = xenrt.ISCSILunSpecified("xenrt-test/%s/%s" %
                                            (self.iqn, ip))
                # Create SR
                lun.setID(scsiId)
                try:
                    sr.create(lun,subtype="lvm")
                except Exception,e:
                    nic=self.host.getNIC(id)
                    xenrt.log("SR create for NIC - %s and Storage VM ip - %s failed with exception - %s" %
                                (nic, ip, e.data))
                    nicNotTested.append(nic)
                    installFlag=0
            else:
                sr = xenrt.lib.xenserver.NFSStorageRepository(self.host,
                                                                    "test-nfs")
                try:
                    sr.create(self.srvm.getIP(), nfsDir)
                except Exception, e:
                    nic=self.host.getNIC(id)
                    xenrt.log("SR create for NIC - %s and ip - %s failed with exception - %s" %
                                (nic, ip, e.data))
                    nicNotTested.append(nic)
                    installFlag=0

            # Install VM only if the SR is available
            if installFlag:
                g=self.host.createGenericLinuxGuest(sr=sr.uuid)
                # Uninstall the guest installed during the test
                g.uninstall()
            try:
                sr.forget()
            except Exception,e:
                xenrt.log("Exception when forgeting sr")

        # If the list is empty its a pass
        if nicNotTested:
            raise xenrt.XRTError("The following NICS in the system were not tested - %s" %
                                (nicNotTested))

    def postRun(self):
        # Clean state for the next test to start
        self.host.uninstallAllGuests()
        self.srhost.uninstallAllGuests()

class TC20672(SRTrafficwithGRO):
    TYPE="nfs"

#### Distributed Virtual Switch Controller (DVSC) Tests ####

class _Controller(_VSwitch):
    """Base class for vSwitch tests with controller."""

    CONTROLLER = "controller"

    def prepare(self, arglist):
        _VSwitch.prepare(self, arglist)
        self.controller = xenrt.TEC().registry.guestGet(self.CONTROLLER).getDVSCWebServices()

    def postRun(self):
        try:
            log("disassociating controller")
            self.pool.disassociateDVS()
        except Exception, e:
            xenrt.TEC().logverbose("_Controller.postRun Exception: %s" % e)
        try:
            if self.controller.place.getState() == "DOWN":
                self.controller.place.start()
        except Exception, e:
            xenrt.TEC().logverbose("_Controller.postRun Exception: %s" % e)

class TC11395(_Controller):

    """Run emergency reset command on a controller-managed host"""
    # R4.4 The vSwitch must support an "emergency reset" function that can be run
    # on a host. (ie via console access) and that removes all configuration
    # supplied by the controller.

    def prepare(self, arglist=[]):
        _Controller.prepare(self, arglist)
        self.pool.associateDVS(self.controller)
        # find first vm that is not controller
        self.targetVM = self.getGuestFromName('linux_1')
        self.sourceVM = self.getGuestFromName('linux_0')

    def run(self, arglist):
        # Prove ssh is working
        self._internalICMP(self.sourceVM, self.targetVM.getIP())

        # Set up an ACL rule on host via the controller
        self.controller.addACLRuleToVM(self.targetVM.getName(), "ICMP")

        # make sure that the rule was effective

        result = self._internalICMP(self.sourceVM, self.targetVM.getIP())
        if result[1] == 0:
            xenrt.TEC().logverbose("ACL Rule is working")
        else:
            raise xenrt.XRTFailure("ACL Rule for ICMP is not working")

        self.host.execdom0("ovs-vsctl emer-reset")

        time.sleep(120)

        # The vSwitch should now be acting as a standalone vSwitch with
        # the ACL rules removed, test that we can reach it guest again

        result = self._internalICMP(self.sourceVM, self.targetVM.getIP())
        xenrt.TEC().logverbose("result = %s %d" % (result[0], result[1]))
        if result[1] == 0:
            raise xenrt.XRTFailure("Emergency Reset left ACL rules behind")
        else:
            xenrt.TEC().logverbose("Emergency Reset is working")

    def postRun(self):
        self.controller.removeAllACLRules(self.targetVM.getName())
        _Controller.postRun(self)

class TC11400(_Controller):
    """
    Manage Pool with DVS

    1. Enable the vSwitch across a pool.
    2. Install the controller VM.
    3. Manage the pool with the controller.
    4. Check ICMP, TCP and UDP traffic between all VMs is unaffected.
    5. Check external ICMP, TCP and UDP traffic is unaffected for all VMs.

    """

    def run(self, arglist):
        self.checkNetwork(self.guests, "without-controller")
        self.pool.associateDVS(self.controller)
        self.checkNetwork(self.guests, "with-controller")

class TC11401(_Controller):
    """
    vSwitch is operational after controller shutdown

    1. Enable the vSwitch across a pool.
    2. Install the controller VM.
    3. Manage the pool with the controller.
    4. Shutdown the controller VM.
    5. Check ICMP, TCP and UDP traffic between all VMs is unaffected.
    6. Check external ICMP, TCP and UDP traffic is unaffected for all VMs.

    """

    def run(self, arglist):
        self.checkNetwork(self.guests, "without-controller")
        self.pool.associateDVS(self.controller)
        self.checkNetwork(self.guests, "with-controller")
        self.controller.place.shutdown()
        self.controller.h1 = 0 # resets the http connection
        self.checkNetwork(self.guests, "shutdown-controller")

class TC11402(_Controller):
    """
    Restart controller VM

    1. Enable the vSwitch across a pool.
    2. Install the controller VM.
    3. Manage the pool with the controller.
    4. Restart the controller VM.
    5. Check the pool is still associated with the controller.
    6. Check ICMP, TCP and UDP traffic between all VMs is unaffected.
    7. Check external ICMP, TCP and UDP traffic is unaffected for all VMs.

    """

    def run(self, arglist):
        self.checkNetwork(self.guests, "without-controller")
        self.pool.associateDVS(self.controller)
        self.checkNetwork(self.guests, "with-controller")
        self.controller.place.reboot()
        self.controller.h1 = 0 # resets the http connection
        self.checkNetwork(self.guests, "restarted-controller")

class TC11410(_Controller):
    """
    Add 2nd pool to controller

    1. Enable the vSwitch across a pool.
    2. Install the controller VM.
    3. Manage the pool with the controller.
    4. Manage the second pool with the controller.
    5. Check ICMP, TCP and UDP traffic between all VMs is unaffected.
    6. Check external ICMP, TCP and UDP traffic is unaffected for all VMs.

    """

    def prepare(self, arglist):
        _Controller.prepare(self, arglist)
        self.poolB = self.getPool("RESOURCE_POOL_1")

    def run(self, arglist):
        self.checkNetwork(self.guests, "without-controller")
        self.pool.associateDVS(self.controller)
        self.poolB.associateDVS(self.controller)
        self.checkNetwork(self.guests, "with-controller")

    def postRun(self):
        _Controller.postRun(self)
        try:
            self.poolB.disassociateDVS()
        except Exception, e:
            xenrt.TEC().logverbose("postRun Exception: %s" % (str(e)))

class TC11411(_Controller):
    """HA protect controller
     1. Enable the vSwitch across a pool.
     2. Install the controller VM on another pool of at least two hosts.
     3. Enable HA on the controller VM pool and protect the controller VM.
     4. Manage the pool with the controller.
     5. Check ICMP, TCP and UDP traffic between all VMs is unaffected.
     6. Check external ICMP, TCP and UDP traffic is unaffected for all VMs.
     7. Shutdown the host the controller VM is resident on.
     8. Check that the controller VM comes back on the other host in its pool.
     9. Check ICMP, TCP and UDP traffic between all VMs is unaffected.
    10. Check external ICMP, TCP and UDP traffic is unaffected for all VMs."""

    def prepare(self, arglist):
        _Controller.prepare(self, arglist)
        self.controllerpool = self.getPool("RESOURCE_POOL_1")
        self.controllerpool.enableHA()
        self.controller.place.setHAPriority("2")
        self.pool.associateDVS(self.controller)

    def run(self, arglist):
        self.checkNetwork(self.guests, "before-loss")
        xenrt.TEC().logverbose("Shutting down host with controller VM.")
        self.controllerpool.master.machine.powerctl.off()
        xenrt.TEC().logverbose("Checking controller VM is back.")
        try:
            self.controller.place.waitForSSH(600)
        except:
            self.controllerpool.findMaster(notCurrent=True)
            raise xenrt.XRTFailure("HA Failure")

        self.checkNetwork(self.guests, "after-loss")

    def postRun(self):
        _Controller.postRun(self)
        try:
            self.controllerpool.master.machine.powerctl.on()
            self.controllerpool.master.waitForSSH(600)
        except Exception, e:
            xenrt.TEC().logverbose("postRun Exception: %s" % (str(e)))
        try:
            self.controllerpool.disableHA()
        except Exception, e:
            xenrt.TEC().logverbose("postRun Exception: %s" % (str(e)))

class TC11685(_Controller):
    """
    vSwitch Stress

    Ensure that the addition and deletion of flow tables entries do not
    greatly impact the throughput of the vSwitch

    With a maximum throughput transfer between two VMs on the same host,
    create VIFs and have them ping one and other such that Flow Table
    Entries are created, then remove the VIFs, causing the entries to be
    removed from the flow table. Ensure that this does not greatly affect
    the throughput.
    """

    count = 0
    subnet = ""
    ipbase = 0
    new_net_uuid = ""
    new_net_name = ""
    throughput = 0
    pingcount = 0
    stop = False
    myguests = []
    subnetuint = 0

    def getGuestObjects(self):
        gueststrings = self.host.listGuests()
        xenrt.TEC().logverbose("%s" % gueststrings)
        for i in range(2):
            xenrt.TEC().logverbose("%s" % self.host.guests[gueststrings[i]])
            self.myguests.append(self.host.guests[gueststrings[i]])


    def cleanUp(self):

        for i in range(2):
            self.myguests[i].execguest("cp /root/interfaces /etc/network/interfaces")
            self.myguests[i].execguest("rm /root/interfaces")
            try:
                self.myguests[i].execguest("ifdown eth1")
                self.myguests[i].unplugVIF("eth1")
                self.myguests[i].removeVIF("eth1")
            except:
                dumbvar = 0
        try:
            self.host.removeNetwork(None, self.new_net_uuid)
        except:
            dumbvar=0


    def backupGuestNetworkInterfaceFiles(self):
        for i in range(2):
            self.myguests[i].execguest("cp /etc/network/interfaces /root/interfaces")

    def restoreGuestNetworkInterfaceFiles(self):
        for i in range(2):
            self.myguests[i].execguest("cp /root/interfaces /etc/network/interfaces")

    def createVIFs(self, guest, subnet, base, subnetuint):
        # create VIF entries on each test vm

        self.myguests[guest].execguest("echo 'auto eth1 \niface eth1 inet static \n"
                                       "address %s.%u \nnetmask 255.255.255.0' "
                                       " >>/etc/network/interfaces" %
                                       (subnet, base))


        self.myguests[guest].execguest("ifup eth1")

        # This is here because it takes the kernel time to remove vifs
        while re.search("inet addr:192.168", self.myguests[guest].execguest("ifconfig eth1")) == None:
            time.sleep(1)
            self.myguests[guest].execguest("ifdown eth1")
            self.myguests[guest].execguest("ifup eth1")

    def destroyIFs(self):
        for i in range(2):
            self.myguests[i].execguest("ifdown eth1")
        self.restoreGuestNetworkInterfaceFiles()

    def ifFarm(self):

        xenrt.TEC().logverbose("!!!SETTING FLAG TO ALLOW THREADS TO RUN!!!")
        self.stop = False
        # Pre-create VIFs on bridge 1
        for i in range(2):
            self.myguests[i].createVIF(eth="eth1", bridge=self.new_net_name, mac=None, plug=True)

        # Exercise Flow table by creating setting eth1 on two VMs to have a
        # new MAC and IP address on each iteration and ping between them
        while self.stop == False:
            # Each IF pair must be have new MAC/IP to exercise flow table
            self.subnetuint = (self.count / 125) + 241
            self.ipbase = (self.count % 125) * 2 + 1
            self.subnet = "192.168.%u" % (self.subnetuint)
            xenrt.pfarm ([xenrt.PTask(self.createVIFs, 0, self.subnet, self.ipbase, self.subnetuint),
                          xenrt.PTask(self.createVIFs, 1, self.subnet, self.ipbase + 1, self.subnetuint)])
            result = self.myguests[0].execguest("ping -c 1 %s.%u" % (self.subnet, self.ipbase + 1), timeout=5)
            self.destroyIFs()
            self.count += 1
            self.pingcount += 1

        # Tidy up the VIFs
        for i in range(2):
            self.myguests[i].unplugVIF("eth1")
            self.myguests[i].removeVIF("eth1")



    # Messure Throughput on VIF 0
    def messureThroughput(self):
        result=self._internalNetperf("TCP_STREAM", self.myguests[0], self.myguests[1].getIP())
        self.throughput = result[1]
        xenrt.TEC().logverbose("!!!STOPPING THREAD!!!")
        self.stop = True

    def prepare(self, arglist):
        _Controller.prepare(self, arglist)
        self.pool.associateDVS(self.controller)
        self.prepareGuests(self.guests)
        self.getGuestObjects()

    def run(self, arglist):
        self.DURATION = 600
        self.backupGuestNetworkInterfaceFiles()
        self.new_net_uuid = self.host.createNetwork("nw1")
        self.new_net_name = self.host.genParamGet("network", self.new_net_uuid, "bridge")

        # Gather a baseline for test
        self.messureThroughput()

        throughputbaseline = self.throughput
        if self.throughput == 0:
            raise xenrt.XRTFailure("Measure baseline throughput of 0 between %s and %s, cannot complete test" %
                                  (self.myguests[0].getName(), self.myguests[1].getName()))

        xenrt.TEC().logverbose("Baseline Throughput = %d" % throughputbaseline)

        # Start a process to create and destroy kernel flow table enrtrie
        result = xenrt.pfarm ([xenrt.PTask(self.ifFarm), xenrt.PTask(self.messureThroughput)],
                               exception=False)

        # Measure throughput whilst the above is going on
        testthroughput = self.throughput
        if self.throughput == 0:
            raise xenrt.XRTFailure("Measure test throughput of 0 between %s and %s, cannot complete test" %
                                  (self.myguests[0].getName(), self.myguests[1].getName()))


        # "Entries are cleared from the flow table every five seconds", Nicira.
        time.sleep(5)

        # Test the through put differences
        percentage = testthroughput / throughputbaseline * 100

        xenrt.TEC().logverbose("VIF Farm Throughput = %d" % testthroughput)
        xenrt.TEC().logverbose("Throughput whilst creating/destroying VIFs is %d%% of standing throughput" % percentage)
        xenrt.TEC().logverbose("Created %u VIF pairs and pinged between them" % self.pingcount)

        # Bridge implementation and vSwitch both show a maximum 10% reduction in throughput
        if percentage < 90:
            raise xenrt.XRTFailure("Flow table creation of %d flows drives average throughput below 90%%." % (self.count * 2))

        # Now check that the flow table does not contain eroneous VIFs
        # Note the following dumps the flow table grepping for the 192.168 subnet
        # If any 192.168.* subnets are found we raise an exception
        flowTable = self.host.execdom0("ovs-dpctl dump-flows system@dp0")
        if re.search("192.168.241", flowTable):
            raise xenrt.XRTFailure("Found 192.168.241 entries in the flow table which should have been automatically removed:\n%s" % (flowTable))

    def postRun(self):
        # destroy the bridges
        self.host.removeNetwork(None, self.new_net_uuid)
        self.cleanUp()
        _Controller.postRun(self)


class TC11692(TC11685):
    """
    Controller/vSwitch Stress

    Ensure that the addition and deletion of flow table entries by the controller do not
    greatly impact the throughput of the vSwitch

    """
    def __init__(self, tcid=None, anon=False):
        TC11685.__init__(self, tcid=tcid, anon=anon)
        self.vif_node = {}
        self.proto_uid = None
        self.vm_node = {}

    def prepare(self, arglist):
        TC11685.prepare(self, arglist)
        self.targetVM = self.guests[0]
        self.sourceVM = self.guests[1]
        self.count = 0
        self.controller.keepDVSAlive()


    def controllerCreateFlowTableEntries(self):
        while self.stop == False:
            # Set up an ACL rule on host via the controller
            self.controller.addACLProtoToNode(self.vif_node, self.proto_uid)

            # make sure that the rule was effective
            try:
                self.sourceVM.execguest("ping -c 1 -w 0.5 %s" % (self.targetVM.getIP()), timeout=2)
            except Exception, e:
                xenrt.TEC().logverbose("ACL Rule is working")
            else:
                raise xenrt.XRTFailure("ACL Rule for ICMP is not working")

            self.controller.removeAllACLRulesFromNode(self.vm_node)

            self.sourceVM.execguest("ping -c 1 -w 0.5 %s" % (self.targetVM.getIP()), timeout=2)

            self.count += 1

    def prepareController(self):
        # Create a default rule at the VIF level
        # to deny ICMP
        icmp_uid = self.controller.findProtocol("ICMP")['uid']
        icmp_deny_rule = self.controller.createACL("out", icmp_uid, "", "deny")

        sourceVM_vif_mac = self.sourceVM.getVIFs()['eth0'][0]

        vif_rules = self.controller.getVIFRules(sourceVM_vif_mac)

        vif_rules["acl_rules"].append(icmp_deny_rule)
        # Note the VIF level does not provide default and mandatory rules

        self.controller.setVIFRules(sourceVM_vif_mac, vif_rules)


    def run(self, arglist):
        # This greatly reduces the ammount of traffic to the controller during the throughput test
        self.prepareController()

        self.DURATION = 600

        # Baseline Throughput
        self.messureThroughput()
        throughputbaseline = self.throughput

        if self.throughput == 0:
            raise xenrt.XRTFailure("Measure baseline throughput of 0 between %s and %s, cannot complete test" %
                                  (self.myguests[0].getName(), self.myguests[1].getName()))

        xenrt.TEC().logverbose("Baseline Throughput = %d" % throughputbaseline)

        self.stop = False
        xenrt.pfarm ([xenrt.PTask(self.controllerCreateFlowTableEntries), xenrt.PTask(self.messureThroughput)],
                               exception=False)

        if self.throughput == 0:
            raise xenrt.XRTFailure("Measure test throughput of 0 between %s and %s, cannot complete test" %
                                  (self.myguests[0].getName(), self.myguests[1].getName()))

        # Measured throughput whilst the above is going on
        testthroughput = self.throughput

        # "Entries are cleared from the flow table every five seconds", Nicira.
        time.sleep(5)

        # Test the through put differences
        percentage = testthroughput / throughputbaseline * 100

        xenrt.TEC().logverbose("Throughput whilst creating/destroying flows is %d%% of standing throughput" % percentage)
        xenrt.TEC().logverbose("Created %u ACL rules, including checks of pings between them" % self.count)

        # Bridge implementation and vSwitch both show a maximum 10% reduction in throughput
        if percentage < 90:
            raise xenrt.XRTFailure("Flow table creation of %d flows over %d"
                                    " seconds drives average throughput below 90%%."
                                    % (self.count * 2, self.DURATION))

        # Now check that the flow table does not contain eroneous entries from the
        # Note the following dumps the flow table grepping for the 192.168.241 subnet
        # If any 192.168.241* subnets are found we raise an exception
        flowTable = self.host.execdom0("ovs-dpctl dump-flows system@dp0")
        if re.search("192.168.241", flowTable):
            raise xenrt.XRTFailure("Found 192.168.241 entries in the flow table which should have been automatically removed:\n%s" % (flowTable))


    def postRun(self):
        self.controller.stopKeepAlive()
        TC11685.postRun(self)

class TC12011(TC11692):

    # Messure Throughput on VIF 0
    def messureExternalThroughput(self):
        result=self._externalNetperf("TCP_STREAM", self.myguests[0])
        self.throughput = result[1]
        xenrt.TEC().logverbose("!!!SETTING FLAG TO ALLOW THREADS TO RUN!!!")
        self.stop = True


    def run(self, arglist):
        # This greatly reduces the ammount of traffic to the controller during the throughput test
        self.prepareController()

        self.backupGuestNetworkInterfaceFiles()
        self.new_net_uuid = self.host.createNetwork("nw1")
        self.new_net_name = self.host.genParamGet("network", self.new_net_uuid, "bridge")

        # Gather a baseline for test
        self.messureThroughput()

        throughputbaseline = self.throughput
        xenrt.TEC().logverbose("Baseline Throughput = %d" % throughputbaseline)

        ###
        # Internal Performance
        ###
        result = xenrt.pfarm ([xenrt.PTask(self.controllerCreateFlowTableEntries), xenrt.PTask(self.ifFarm), xenrt.PTask(self.messureThroughput)],
                               exception=False)


        # Measure throughput whilst the above is going on
        testthroughput = self.throughput

        # "Entries are cleared from the flow table every five seconds", Nicira.
        time.sleep(5)

        # Test the through put differences
        percentage = testthroughput / throughputbaseline * 100

        xenrt.TEC().logverbose("VIF Farm Throughput = %d" % testthroughput)
        xenrt.TEC().logverbose("Internalhroughput whilst creating/destroying VIFs and flows is %d%% of standing throughput" % percentage)
        xenrt.TEC().logverbose("Created %u VIF pairs and pinged between them" % self.pingcount)

        # Bridge implementation and vSwitch both show a maximum 10% reduction in throughput
        if percentage < 90:
            raise xenrt.XRTFailure("Flow table creation of %d flows drives average throughput below 90%%." % (self.count * 2))


        # Now check that the flow table does not contain eroneous VIFs
        # Note the following dumps the flow table grepping for the 192.168 subnet
        # If any 192.168.* subnets are found we raise an exception
        flowTable = self.host.execdom0("ovs-dpctl dump-flows system@dp0")
        if re.search("192.168.1", flowTable):
            raise xenrt.XRTFailure("Found 192.168 entries in the flow table which should have been automatically removed:\n%s" % (flowTable))
    # No postRun required as this will call TC11692 and hence TC11685s post runs - the run being the culminatiion of the two

class TC11546(_Controller):
    """
    Verify the Browser GUI requires a login

    1. Perform some action without a cookie
    2. Perform some action with the login supplied cookie

    """
    def prepare(self, arglist):
        # This will log us in
        _Controller.prepare(self, arglist)
        self.pool.associateDVS(self.controller)
        self.targetVM = self.guests[0]

    def run(self, arglist):
        self.controller.logout()

        # prevent auto login for each request
        self.controller.auto = False

        try:
            self.controller.addACLRuleToVM(self.targetVM.getName(), "ICMP")
        except Exception, e:
            xenrt.TEC().logverbose("Log out has worked and we are unable to use the controller: " )
        else:
            raise xenrt.XRTFailure("Able to use the controller after logout")

        self.controller.login("admin", self.controller.admin_pw)
        self.controller.auto = True

        # chck that we are able to contact the controller again
        self.controller.addACLRuleToVM(self.targetVM.getName(), "ICMP")

    def postRun(self):
        self.controller.removeAllACLRules(self.targetVM.getName())
        _Controller.postRun(self)


class TC11548(_Controller):
    """
    ACL Hierachy

    Create Mandatory and Default ACL rules at Global, Pool, Network and VM Levels.
    Make sure that higher priority levels override lower priority levels

    """
    backup_rules = {}
    backup_rules['global', 'pool', 'network', 'vm', 'vif'] = [{}, {}, {}, {}, {}]
    network_name = ''
    vm_names = []
    def prepare(self, arglist):
        _Controller.prepare(self, arglist)
        self.prepareGuests(self.guests)
        # todo remove this
        self.pool.associateDVS(self.controller)
        self.targetVM = self.guests[0]
        self.sourceVM = self.guests[1]

    def run(self, arglist):

        # get the global rules
        global_rules = self.controller.getGlobalRules()
        self.backup_rules['global'] = self.controller.getGlobalRules()

        # we know that we have ARP, DHCP and DNS at the global mandatory level
        # and allow any to and from any ad the global default level
        # now if we insert deny ICMP at global default level
        # first create an ACL rule to do this
        icmp_uid = self.controller.findProtocol("ICMP")['uid']
        icmp_deny_rule = self.controller.createACL("both", icmp_uid, "", "deny")

        global_rules["acl_rules"].insert(3, icmp_deny_rule)
        self.controller.setGlobalRules(global_rules)

        # The http request returns before the ACL rule is set on the vswitch
        # Nicira have advised a 5 second turnaround
        time.sleep(10)

        # make sure that the rule was effective
        result = self._internalICMP(self.sourceVM, self.targetVM.getIP())
        if result[1] == 0:
            xenrt.TEC().logverbose("Default Global ACL Rule is working")
        else:
            raise xenrt.XRTFailure("Default Global ACL Rule for ICMP is not working result = %d" % result[1])

        # make sure that other sockets are not affected
        result = self._internalNetperf("TCP_STREAM", self.sourceVM, self.targetVM.getIP())
        if result[1] == 0:
            raise xenrt.XRTFailure("Default Global ACL Rule for ICMP interferes with port %d = %d" % (self.PORT, result[1]))

        # Next create a default rule at the Pool level to allow ICMP
        # This should override the global default rule.
        pool_rules = self.controller.getPoolRules(self.host.getIP())
        self.backup_rules['pool'] = self.controller.getPoolRules(self.host.getIP())

        icmp_allow_rule = self.controller.createACL("both", icmp_uid, "", "allow")
        # pool_rules["acl_rules"] is an empty list at this point
        pool_rules['acl_rules'].append(icmp_allow_rule)
        pool_rules['acl_split_before'] = 0

        self.controller.setPoolRules(self.host.getIP(), pool_rules)
        time.sleep(5)

        # Check that this overrides as expected
        result = self._internalICMP(self.sourceVM, self.targetVM.getIP())
        if result[1] != 0:
            xenrt.TEC().logverbose("Default Pool Rule is working")
        else:
            raise xenrt.XRTFailure("Default Pool ACL Rule for ICMP is not working result = %d" % result[1])

        # Next create a default rule at the network level
        # to deny ICMP
        # Nicira rename the network for some reason
        self.network_name = self.controller.getNetworksInPool(self.host.getIP())[0]
        network_rules = self.controller.getNetworkRules(self.network_name)
        self.backup_rules['network'] = self.controller.getNetworkRules(self.network_name)

        network_rules["acl_rules"].append(icmp_deny_rule)
        network_rules['acl_split_before'] = 0

        self.controller.setNetworkRules(self.network_name, network_rules)
        time.sleep(5)

        # make sure that the rule was effective
        result = self._internalICMP(self.sourceVM, self.targetVM.getIP())
        if result[1] == 0:
            xenrt.TEC().logverbose("Default Network ACL Rule is working")
        else:
            raise xenrt.XRTFailure("Default Network ACL Rule for ICMP is not working result = %d" % result[1])

        # make sure that other sockets are not affected
        result = self._internalNetperf("TCP_STREAM", self.sourceVM, self.targetVM.getIP())
        if result[1] == 0:
            raise xenrt.XRTFailure("Default Network ACL Rule for ICMP interferes with port %d = %d" % (self.PORT, result[1]))

        # Next create a default rule at the VM level
        # to allow ICMP to each VM
        self.backup_rules['vm'] = self.controller.getVMRules(self.targetVM.getName())
        self.vm_names.append(self.sourceVM.getName())
        self.vm_names.append(self.targetVM.getName())
        for name in self.vm_names:
            vm_rules = self.controller.getVMRules(name)

            vm_rules["acl_rules"].append(icmp_allow_rule)
            vm_rules['acl_split_before'] = 0

            self.controller.setVMRules(name, vm_rules)
            time.sleep(5)

        # make sure that the rule was effective
        result = self._internalICMP(self.sourceVM, self.targetVM.getIP())
        if result[1] != 0:
            xenrt.TEC().logverbose("Default VM ACL Rule is working")
        else:
            raise xenrt.XRTFailure("Default VM ACL Rule for ICMP is not working result = %d" % result[1])

        # Next create a default rule at the VIF level
        # to deny ICMP
        sourceVM_vif_mac = self.sourceVM.getVIFs()['eth0'][0]
        self.backup_rules['vif'] = self.controller.getVIFRules(sourceVM_vif_mac)
        vif_rules = self.controller.getVIFRules(sourceVM_vif_mac)

        vif_rules["acl_rules"].append(icmp_deny_rule)
        # Note the VIF level does not provide default and mandatory rules

        self.controller.setVIFRules(sourceVM_vif_mac, vif_rules)

        time.sleep(5)

        # make sure that the rule was effective
        result = self._internalICMP(self.sourceVM, self.targetVM.getIP())
        if result[1] == 0:
            xenrt.TEC().logverbose("VIF deny ACL Rule is working")
        else:
            raise xenrt.XRTFailure("VIF deny ACL Rule for ICMP is not working result = %d" % result[1])

        # make sure that other sockets are not affected
        result = self._internalNetperf("TCP_STREAM", self.sourceVM, self.targetVM.getIP())
        if result[1] == 0:
            raise xenrt.XRTFailure("Default VIF ACL Rule for ICMP interferes with port %d = %d" % (self.PORT, result[1]))


        # NOW CHECK MANADATORY OVERIDES

        # First we must remove the VIF rule as it overides the VM rule
        # and would leave us testing that the mandatory allow
        # overieds the default allow
        self.controller.setVIFRules(sourceVM_vif_mac, self.backup_rules['vif'])

        # make sure that the rule was effective
        result = self._internalICMP(self.sourceVM, self.targetVM.getIP())
        if result[1] != 0:
            xenrt.TEC().logverbose("Removal of VIF deny ACL Rule is working")
        else:
            raise xenrt.XRTFailure("Removal of VIF deny ACL Rule for ICMP is not working result = %d" % result[1])

        # Create a mandatory rule at the VM level
        # to deny ICMP to each VM - this overides the defaut VM allow rule
        for name in self.vm_names:
            vm_rules = self.controller.getVMRules(name)

            vm_rules["acl_rules"].insert(0, icmp_deny_rule)
            vm_rules['acl_split_before'] = 1

            self.controller.setVMRules(name, vm_rules)
            time.sleep(5)

        # make sure that the rule was effective
        result = self._internalICMP(self.sourceVM, self.targetVM.getIP())
        if result[1] == 0:
            xenrt.TEC().logverbose("Mandatory VM ACL Rule overrides the Default Rule as expected")
        else:
            raise xenrt.XRTFailure("Mandatory VM ACL Rule is not overriding the Default Rule result = %d" % result[1])

        # make sure that other sockets are not affected
        result = self._internalNetperf("TCP_STREAM", self.sourceVM, self.targetVM.getIP())
        if result[1] == 0:
            raise xenrt.XRTFailure("Mandatory VM ACL Rule for ICMP interferes with port %d = %d" % (self.PORT, result[1]))


        # Create a madatory rule at the network level
        # to allow ICMP
        network_rules["acl_rules"].insert(0, icmp_allow_rule)
        network_rules['acl_split_before'] = 1

        self.controller.setNetworkRules(self.network_name, network_rules)
        time.sleep(5)

        # make sure that the rule was effective
        result = self._internalICMP(self.sourceVM, self.targetVM.getIP())
        if result[1] != 0:
            xenrt.TEC().logverbose("Mandatory Network ACL Rule overrides the Default Rule as expected")
        else:
            raise xenrt.XRTFailure("Mandatory Network ACL Rule is not overriding the Default Rule result = %d" % result[1])

        # Create a mandatory rule at the Pool level to deny ICMP
        # This should override the default rule.
        pool_rules['acl_rules'].insert(0, icmp_deny_rule)
        pool_rules['acl_split_before'] = 1

        self.controller.setPoolRules(self.host.getIP(), pool_rules)
        time.sleep(5)

        # Check that this overrides as expected
        result = self._internalICMP(self.sourceVM, self.targetVM.getIP())
        if result[1] == 0:
            xenrt.TEC().logverbose("Mandatory Pool ACL Rule overrides the Default Rule as expected")
        else:
            raise xenrt.XRTFailure("Mandatory Pool ACL Rule is not overriding the Default Rule result = %d" % result[1])

        # make sure that other sockets are not affected
        result = self._internalNetperf("TCP_STREAM", self.sourceVM, self.targetVM.getIP())
        if result[1] == 0:
            raise xenrt.XRTFailure("Mandatory Pool ACL Rule for ICMP interferes with port %d = %d" % (self.PORT, result[1]))

        # Create a mandatory rule at the Global level to deny ICMP
        # This should override the default rule.
        global_rules["acl_rules"].insert(3, icmp_allow_rule)
        global_rules['acl_split_before'] = 4
        self.controller.setGlobalRules(global_rules)

        # The http request returns before the ACL rule is set on the vswitch
        # Nicira have advised a 5 second turnaround
        time.sleep(5)

        # make sure that the rule was effective
        result = self._internalICMP(self.sourceVM, self.targetVM.getIP())
        if result[1] != 0:
            xenrt.TEC().logverbose("Mandatory Global ACL Rule overrides the Default Rule as expected")
        else:
            raise xenrt.XRTFailure("Mandatory Global ACL Rule is not overriding the Default Rule result = %d" % result[1])

        # Remove all rules
        self.controller.setGlobalRules(self.backup_rules['global'])
        self.controller.setPoolRules(self.host.getIP(), self.backup_rules['pool'])
        self.controller.setPoolRules(self.network_name, self.backup_rules['network'])
        for name in self.vm_names:
            self.controller.setVMRules(self.network_name, self.backup_rules['vm'])

        # make sure that other sockets are not affected
        result = self._internalNetperf("TCP_STREAM", self.sourceVM, self.targetVM.getIP())
        if result[1] == 0:
            raise xenrt.XRTFailure("Mandatory Pool ACL Rule for ICMP interferes with port %d = %d" % (self.PORT, result[1]))

    def postRun(self):
        _Controller.postRun(self)

class TC11549(_Controller):
    """
    Common Protocols

    Ensure that a default set of the most commonly used protocols is provided

    """

    common_protos = ["ARP", "IP", "IPv6", "ICMP", "TCP", "UDP", "FTP", "SSH",
                     "Telnet", "SMTP", "HTTP", "Kerberos", "POP", "IMAP",
                     "HTTPS", "SOCKS", "SIP", "DNS", "DHCP", "BOOTP", "NTP",
                     "Syslog", "NFS"]
    def prepare(self, arglist):
        _Controller.prepare(self, arglist)
        # todo remove this
        self.pool.associateDVS(self.controller)
        self.targetVM = self.guests[0]
        self.sourceVM = self.guests[1]

    def getname(self, x): return x['name']

    def run(self, arglist):
        missing_protos = []
        protocols = self.controller.getProtocols()
        protocol_list  = map(self.getname, protocols)
        for item in self.common_protos:
            if item in protocol_list == False:
                missing_protos.append(item)

        if len(missing_protos) != 0:
            raise xenrt.XRTFailure(("The following protocols are missing from the default set: " + " ".join(missing_protos)))

    def postRun(self):
        _Controller.postRun(self)

class TC11535(_Controller):
    """
    Controller Daemons restart automatically

    Kill the controller software daemons, ensure they retart automatically
    """
    dead_controller = False
    def prepare(self, arglist):
        _Controller.prepare(self, arglist)
        self.pool.associateDVS(self.controller)

    def run(self, arglist):
        try :
            result = self.controller.place.execguest("killall nox_core nwflowpack")
        except :
            xenrt.XRTFailure("Not all processes killed")

        time.sleep(60)

        try :
            self.controller.login("admin", self.controller.admin_pw)
        except:
            self.dead_controller = True
            raise xenrt.XRTFailure("Controller processes failed to restart after 60 seconds")

    def postRun(self):
        # if the controller is dead reboot it (saves a few error reports
        if self.dead_controller == True:
            self.controller.place.execguest("reboot")
            time.sleep(180)

        _Controller.postRun(self)

class TC11579(_Controller):
    """
    Fail Open

    Check that the vSwitch reverts to "failing open" if it declares the controller failed

    This test also covers TC11581 'fail open' means 'ignore acl rules' as per meeting with nicira
    13/9/10
    """

    myguests = []
    def prepare(self, arglist):
        _Controller.prepare(self, arglist)
        self.pool.associateDVS(self.controller)
        # find first vm that is not controller
        for guest in self.guests:
            if guest.getName() != self.controller.place.getName():
                self.myguests.append(guest)

    def run(self, arglist):
        # Set the controller in fail open mode
        self.controller.setPoolFailMode(self.host.getIP(), 0)

        # First we need to setup some ACL rules
        xenrt.TEC().logverbose("Number of myguests = %d" % len(self.myguests) )

        # Set up an ACL rule on host via the controller
        self.controller.addACLRuleToVM(self.myguests[1].getName(), "ICMP")

        time.sleep(30)

        # test ACL rules now have effect
        success = 0
        iterations = 60
        while iterations:
            iterations -= 1
            try:
                self.myguests[1].getHost().execdom0("ovs-ofctl dump-flows xenbr0 | grep drop")
            except:
                pass
            try:
                self.myguests[0].execguest("ping -c1 -w 2 %s" % self.myguests[1].getIP())
                success += 1
            except:
                pass        
        if success == 0:
            xenrt.TEC().logverbose("ACL Rule is working")
        else:
            raise xenrt.XRTFailure("ACL Rule for ICMP is not working")

        # unlug the controllers vif - this'll freak a failed controller situation
        self.controller.place.unplugVIF("eth0")

        # allow time from the vswitch to realise that the controller has failed
        time.sleep(180)

        # test ACL rules now have no effect
        success = 0
        iterations = 60
        while iterations:
            iterations -= 1
            try:
                self.myguests[1].getHost().execdom0("ovs-ofctl dump-flows xenbr0 | grep drop")
            except:
                pass
            try:
                
                self.myguests[0].execguest("ping -c1 -w 2 %s" % self.myguests[1].getIP())
                success += 1
            except:
                pass
        if success == 0:
            raise xenrt.XRTFailure("ACL rules are still active after controller failed")
        else:
            xenrt.TEC().logverbose("ACL Pass, the rules are inactive after the controller has failed")

        # re-plug the controller's VIF
        self.controller.place.plugVIF("eth0")
        # give time for it to reconnect to the servers and apply the flow tables
        time.sleep(180)

        # make sure that the rules are effective again
        result = self._internalICMP(self.myguests[0], self.myguests[1].getIP())
        if result[1] == 0:
            xenrt.TEC().logverbose("ACL Rule is working")
        else:
            raise xenrt.XRTFailure("ACL Rule for ICMP is not working")

        self.controller.removeAllACLRules(self.myguests[1].getName())

        # test ACL rules now have been removed
        result = self._internalICMP(self.myguests[0], self.myguests[1].getIP())
        if result[1] == 0:
            raise xenrt.XRTFailure("ACL rules are still active after removal")
        else:
            xenrt.TEC().logverbose("ACL Pass, the rules are have been removed and the test completed")


    def postRun(self):
        try:
            # re-plug the controller's VIF
            self.controller.place.plugVIF("eth0")
            # give time for it to reconnect to the servers and apply the flow tables
            time.sleep(180)
        except:
            pass
        try:
            self.controller.removeAllACLRules(self.myguests[1].getName())
        except:
            pass
        
        _Controller.postRun(self)

class TC12657(_Controller):
    """
    Fail Closed

    Test the controller/vswitch fail closed functionality.

    1. Select Fail closed in the controller via the web services API and disconnect the controller
    2. Ensure that all existing ACLs are honored
    3. Add a new VM, ensure that it is not contactable
    4. Migrate an existing VM, ensure that it is no longer contactable
    5. Add a host with existing VMs to the pool, ensure its VMs are no longer contactable

    """
    pool1 = None
    myguests = []
    def prepare(self, arglist):
        _Controller.prepare(self, arglist)
        self.pool.associateDVS(self.controller)
        self.pool1 = self.getPool("RESOURCE_POOL_1")
        ifdata = self.controller.place.getLinuxIFConfigData()
        # Required for fail-close.
        self.controller.setStaticIP(ifdata["eth0"]["IP"], ifdata["eth0"]["netmask"], 
                                    self.controller.place.execguest("route | grep default | awk '{print $2}'").strip())

    def run(self, arglist):

        # need to set and check some ACL rules here - the obvioud choice is to use the fail open test
        for guest in self.guests:
            if guest.getName() != self.controller.place.getName():
                self.myguests.append(guest)
                self.controller.addACLRuleToVM(guest.getName(), "ICMP")


        # Set the pool fail mode to closed
        self.controller.setPoolFailMode(self.host.getIP(), 1)


        for i in range(10):
            # Get the result of the set pool fail mode 
            self.pool.getPoolParam("other-config")

            
        self.controller.place.unplugVIF("eth0")
        self.pool.getPoolParam("other-config")

        # Get useful info from about the fail mode
        bridges = self.host.execdom0("ovs-vsctl list-br").strip().split("\n")
        for bridge in bridges:
            if re.search("xenbr", bridge):
                self.host.execdom0("ovs-vsctl get-fail-mode %s" % bridge)

        # Ensure that the existing ACL rules are still working
        for guest in self.myguests:
            try:
                self._externalICMP(guest)
            except:
                xenrt.TEC().logverbose("ACL rule for %s still working fail closed is working" % guest.getName()) 
            else:
                raise xenrt.XRTFailure("ACL rule is not working hence we have failed open")

        # New guests should not be contactable
        try:
            myguest = self.host.createBasicGuest("debian50")
        except:
            xenrt.TEC().logverbose("Newly created guest is not contactable we have failed closed") 
        else:
            raise xenrt.XRTFailure("Guest install completed which means that the guest is contactable and we have failed open")

        # Migrated guests should not be contactable
        linux_0 = self.getGuestFromName("linux_0")
        linux_0_host = linux_0.getHost()

        host2 = None
        for host in self.hosts:
            if host != linux_0_host:
                host2 = host
                break

        
        try:
            linux_0.migrateVM(host2, live="true")
            linux_0.execguest("ls")
        except:
            xenrt.TEC().logverbose("Migrated guest is not contactable we have failed closed") 
        else:
            raise xenrt.XRTFailure("Guest contactable after migrate, we have failed open")

                
        # Add host with guests to pool
        linux_3 = xenrt.TEC().registry.guestGet('linux_3')
        linux_3.shutdown()
        self.pool.addHost(self.pool1.master)

        # linux 3 should not now be contactable
        try:
            linux_3.start()
        except:
            xenrt.TEC().logverbose("Guests added to pool are not contactable, we have failed closed") 
        else:
            raise xenrt.XRTFailure("Guest contactable after migrate, we have failed open")

    def postRun(self):
        # Set the pool fail mode to closed
        self.controller.setPoolFailMode(self.host.getIP(), 0)
        self.controller.setDynamicIP()
        _Controller.postRun()
        

class TC11583(_Controller):
    """ 
    Obey backoff
    
    Ensure that the vswitch attempts to connect to the controller do not exceed the maximum back off period
    """
    
    def prepare(self, arglist):
        _Controller.prepare(self, arglist)
        self.pool.associateDVS(self.controller)
        
    def debugNic(self):
        log( "(debug-NIC-457) \n%s" % 
                self.host.execdom0("ovs-vsctl get bridge xenbr0 controller").strip() )
        log( "(debug-NIC-457) \n%s" % self.host.listDomains() )

    def getControllerUUID(self):
        try:
            step("Getting uuid of the controller")
            dvscuuid = self.host.execdom0("ovs-vsctl get bridge xenbr0 controller").strip().strip("[]")
        except:
            raise xenrt.XRTError("Failed to retrieve Controller UUID.")

        if not dvscuuid:
            raise xenrt.XRTError("Controller UUID does not appear to be set")

        return dvscuuid

    def run(self, arglist):
        step("Setting rconn:FILE:DBG in vswitch")
        self.host.execdom0("ovs-appctl vlog/set rconn:FILE:DBG")
        self.debugNic()
        # Attempt backoff of 10 and 5 second(s).
        for backoffms in [10000, 5000]:
            step("Changing backoff to %s" % backoffms)
            dvscuuid = self.getControllerUUID()
            self.debugNic()
            self.host.execdom0("ovs-vsctl set controller %s max_backoff=%d" % (dvscuuid, backoffms))
            # Disconnect the controller.
            try:
                step("Unplugging eth0 VIF")
                self.debugNic()
                self.controller.place.unplugVIF("eth0")
                self.debugNic()
                step("Getting tcpdump data")
                data = self.host.execdom0("tcpdump -tt -c 10 -i %s host %s and port 6633" % \
                                          (self.host.getPrimaryBridge(), self.host.getIP()))
                step("Processing tcpdump data")
                for line in data.splitlines():
                    xenrt.TEC().logverbose("Captured data: %s" % (line))
                times = map(float, re.findall("(\d+\.\d+) IP", data))
                xenrt.TEC().logverbose("Parsed times: %s" % (times))
                self.debugNic()
                for i in range(len(times)-1):
                    delta = (times[i+1] - times[i])*1000
                    xenrt.TEC().logverbose("Delta between packet %s and %s is %sms." % (i+1, i, delta))
                    # Allow 1000ms margin for error. (For e.g. SSH propagation.)
                    if delta > 2*backoffms + 1700:          
                        raise xenrt.XRTFailure("Max back off of %sms exceeded. (%sms)" % (backoffms, delta))
            finally:
                step("Replugging eth0 VIF")
                self.debugNic()
                self.controller.place.plugVIF("eth0")
                self.debugNic()
                time.sleep(120)

class TC11509(_Controller):
    """
    Test the default QoS policy hierarchy.
    Verify global policy specifies "No QoS Policy" by default
    and all other levels of the hierarchy specify ?Inherit QoS policy from parent" by default.
    Check (with netperf) if indeed there's no policy, i.e. the throughput is maximal
    """
    # by Kasia Boronska

    myguests = []

    def prepare(self, arglist):
        _Controller.prepare(self, arglist)
        self.pool.associateDVS(self.controller)
        # This seems necessary - controller needs about 2 min. after associating again.
        time.sleep(120)

    def run(self, arglist):
        # remove Controller from the guest list
        self.myguests = self.hosts[1].guests.values()
        count = 0
        for guest in self.myguests:
            xenrt.TEC().logverbose("myguest[%d] %s" % (count, guest.getName))
            count += 1
            if guest.getName() == self.CONTROLLER:
                self.myguests.remove(guest)
        # define remote guest
        self.myremoteguest = self.hosts[0].guests.values()[0]
        xenrt.TEC().logverbose("myremoteguest %s" % (self.myremoteguest.getName))
        # prepare netperf/guests
        xenrt.TEC().logverbose("Preparing Host[0] guests")
        self.prepareGuests(self.myguests, netperf_config="--enable-intervals --enable-burst")
        xenrt.TEC().logverbose("Preparing Host[1] guests")
        self.prepareGuests([self.myremoteguest], netperf_config="--enable-intervals --enable-burst")
        # check global QoS policy:
        policy = (
            'global', self.controller.getGlobalRules(),
            'pool', self.controller.getPoolRules(self.host.getIP()),
            'network', self.controller.getNetworkRules("Network 0"),
            'guest', self.controller.getVMRules(self.myguests[0].getName()),
            'remote guest', self.controller.getVMRules(self.myremoteguest.getName()),
            'guest VIF', self.controller.getVIFRules(self.myguests[0].getVIFs()['eth0'][0]),
            'guest 2 VIF', self.controller.getVIFRules(self.myguests[1].getVIFs()['eth0'][0]),
            'remote guest VIF', self.controller.getVIFRules(self.myremoteguest.getVIFs()['eth0'][0]),
            )
        # Log all policy settings:
        for level, pol in zip(policy[0::2], policy[1::2]):
            xenrt.TEC().logverbose("Settings for %s policy: %s" % (level, pol ) )
        for level, pol in zip(policy[0::2], policy[1::2]):
            quos = pol['qos']
            if quos != 'inherit' :
                raise xenrt.XRTFailure("Default %s policy should be 'inherit' and is '%s'." % (level, quos))
        # Define expected throughput for external and internal transfer.
        # We expect internal between 2.8 and 4Gb and external between 0.9 and 1.2 Gb.
        # If the set-up is significantly changed, this test case should fail
        # and the values below should be changed to the new expected parameters.
        # WE GET REGUCED THROUGHPUT AFTER ASSOCIATING THE CONTROLLER -- SEE BUG CA-48175,
        # LOWER INTERNAL THROUGHPUT BELOW HAD TO BE REDUCED TO FROM 2.8  TO 2.5GB
        internal = ('internal', 1000000, 4000000,
            self._internalNetperf("TCP_STREAM", self.myguests[0],   self.myguests[1].getIP())[1] )
        external = ('external', 750000, 1200000,
            self._internalNetperf("TCP_STREAM", self.myremoteguest, self.myguests[1].getIP())[1] )
        for name, lower, upper, measured in (internal, external):
            xenrt.TEC().logverbose("Measured %s throughput: %s." % (name,measured) )
        # compare expected and measured throughputs :
        for name, lower, upper, measured in (internal, external):
            xenrt.TEC().logverbose("Measured %s throughput: %s." % (name,measured) )
            if measured < lower or ( name=='external' and measured > upper ):
                raise xenrt.XRTFailure("Expected %s throughput was between %s and %skb and measured throughput was %s."
                    % (name, lower, upper, measured) )

    def postRun(self):
        self.controller.setGlobalQoSPolicy(0, 0)
        self.controller.setPoolQoSPolicy(self.host.getIP(),0, 0)
        self.controller.setNetworkQoSPolicy("Network 0", 0, 0)
        for guest in self.myguests:
            # set Guest policy to 5MBps with 5Mb Burst
            self.controller.setVMQoSPolicy(guest.getName(), 0, 0)
        _Controller.postRun(self)

class TC11514(_Controller):
    """
    Policy priority

    Test lower level policies override higher-level policies

    Note Nicra's implementation implements the token bucket protocol with
    burst = bucket size
    rate = leak rate

    The bucket starts full with enough tokens to represent burst size packets

    As each packet arrives at the bucket, enough tokens are removed from the
    bucket to represent the bytes to be transmitted

    If there are not enough tokens in the bucket the packet is dropped.

    A token is added to the bucket every 1/rate seconds



    """
    DURATION         = 60
    SIZE = 1472 # Note size must be MTU less IP and ethernet headers
                # otherwise this will result in fragmentation skewing results
                # considerably

    myguests = []

    def checkResult(self, level, rate, burst, measured_internal, measured_external):
        expected_throughput = ((rate * self.DURATION) + burst) / self.DURATION

        internal_difference = (measured_internal / expected_throughput) * 100
        if internal_difference < 90 or internal_difference > 110:
            raise xenrt.XRTFailure("%s internal QoS produces %d%% of expected throughput this should be between 90 and 110%%" % (level, internal_difference))


        external_difference = (measured_external / expected_throughput) * 100
        if external_difference < 90 or external_difference > 110:
            raise xenrt.XRTFailure("%s external QoS produces %d%% of expected throughput this should be between 90 and 110%%"% (level, external_difference))


    def prepare(self, arglist):
        _Controller.prepare(self, arglist)
        self.pool.associateDVS(self.controller)
        
        step("Checking if Management NIC is on eth0")
        for host in self.hosts:
            br = host.getPrimaryBridge()
            pifs = host.parseListForOtherParam("network-list", "bridge", br, "PIF-uuids")
            device = host.genParamGet("pif", pifs.split(';')[0] ,"device")
            if device != 'eth0':
                raise xenrt.XRTError("Management NIC of host %s is not eth0" % (host.getIP()))

    def run(self, arglist):
        self.myguests = self.hosts[1].guests.values()
        count = 0
        for guest in self.myguests:
            xenrt.TEC().logverbose("myguest[%d] %s" % (count, guest.getName))
            count += 1
            if guest.getName() == self.CONTROLLER:
                self.myguests.remove(guest)

        self.myremoteguest = self.hosts[0].guests.values()[0]
        xenrt.TEC().logverbose("myremoteguest %s" % (self.myremoteguest.getName))


        xenrt.TEC().logverbose("Prepareing Host[0] guests")
        self.prepareGuests(self.myguests, netperf_config="--enable-intervals --enable-burst")
        xenrt.TEC().logverbose("Prepareing Host[1] guests")
        self.prepareGuests([self.myremoteguest], netperf_config="--enable-intervals --enable-burst")


        # We start with a external Phy of 1Gb/s and and an internal Phy of circa 3Gb/s
        xenrt.TEC().logverbose("Testing Phy Throughput guests")
        baseline_internal = self._internalNetperf("TCP_STREAM", self.myguests[0], self.myguests[1].getIP())
        baseline_external = self._internalNetperf("TCP_STREAM", self.myremoteguest, self.myguests[1].getIP())
        xenrt.TEC().logverbose("baseline_internal = %d, baseline_external = %d" % (baseline_internal[1], baseline_external[1]))

        ###########
        # Global
        ###########

        # set global policy to 100MBps with 50Mb Burst
        global_rate = 100000
        global_burst = 50000
        self.controller.setGlobalQoSPolicy(global_rate, global_burst)
        self.host.execdom0("tc -d qdisc")

        # gain performance metrics with 50 Mb burst
        global_internal = self._internalNetperf("TCP_STREAM", self.myguests[0], self.myguests[1].getIP(), size=self.SIZE)
        global_external = self._internalNetperf("TCP_STREAM", self.myremoteguest, self.myguests[1].getIP(), size=self.SIZE)

        xenrt.TEC().logverbose("Global 100MBps with 50Mb Burst: global_internal[1] = %d, global_external[1] = %d" % (global_internal[1], global_external[1]))

        self.checkResult("Global", global_rate, global_burst, global_internal[1], global_external[1])

        ###########
        # Pool
        ###########

        # set pool policy to 50MBps with 100Mb Burst
        pool_rate = 50000
        pool_burst = 25000

        self.controller.setPoolQoSPolicy(self.host.getIP(), pool_rate, pool_burst)
        self.host.execdom0("tc -d qdisc")

        # gain performance metrics
        pool_internal = self._internalNetperf("TCP_STREAM", self.myguests[0], self.myguests[1].getIP(), size=self.SIZE)
        pool_external = self._internalNetperf("TCP_STREAM", self.myremoteguest, self.myguests[1].getIP(), size=self.SIZE)

        xenrt.TEC().logverbose("Pool 50MBps with 25Mb Burst: pool_internal = %d, pool_external = %d" % (pool_internal[1], pool_external[1]))

        self.checkResult("Pool", pool_rate, pool_burst, pool_internal[1], pool_external[1])


        ###########
        # Network
        ###########

        # set network policy to 20MBps with 10Mb Burst
        network_rate = 20000
        network_burst = 10000
        self.controller.setNetworkQoSPolicy("Network 0", network_rate, network_burst)
        self.host.execdom0("tc -d qdisc")

        # gain performance metrics
        network_internal = self._internalNetperf("TCP_STREAM", self.myguests[0], self.myguests[1].getIP(), size=self.SIZE)
        network_external = self._internalNetperf("TCP_STREAM", self.myremoteguest, self.myguests[1].getIP(), size=self.SIZE)

        xenrt.TEC().logverbose("Network 20MBps with 10Mb Burst: network_internal = %d, network_external = %d" % (network_internal[1], network_external[1]))

        self.checkResult("Network", network_rate, network_burst, network_internal[1], network_external[1])


        ###########
        # Guest
        ###########
        guest_rate = 10000
        guest_burst = 5000

        self.controller.setVMQoSPolicy(self.myguests[0].getName(), guest_rate, guest_burst)
        self.controller.setVMQoSPolicy(self.myremoteguest.getName(), guest_rate, guest_burst)
        self.host.execdom0("tc -d qdisc")

        # gain performance metrics
        guest_internal = self._internalNetperf("TCP_STREAM", self.myguests[0], self.myguests[1].getIP(), size=self.SIZE)
        guest_external = self._internalNetperf("TCP_STREAM", self.myremoteguest, self.myguests[1].getIP(), size=self.SIZE)

        #  print the result
        xenrt.TEC().logverbose("Guest 10MBps with 5Mb Burst: guest_internal = %d, guest_external = %d" % (guest_internal[1], guest_external[1]))

        self.checkResult("Guest", guest_rate, guest_burst, guest_internal[1], guest_external[1])

    def postRun(self):
        self.controller.setGlobalQoSPolicy(0, 0)
        self.controller.setPoolQoSPolicy(self.host.getIP(),0, 0)
        self.controller.setNetworkQoSPolicy("Network 0", 0, 0)
        for guest in self.myguests:
            # set Guest policy to 5MBps with 5Mb Burst
            self.controller.setVMQoSPolicy(guest.getName(), 0, 0)
        self.controller.setVMQoSPolicy(self.myremoteguest.getName(), 0, 0)
        _Controller.postRun(self)

class TC11543(_Controller):
    """
    65536 Wildcard Flows

    A wildcard flow is one where the one of the flow parameters is "dont care"
    Thus we can create 65536 wildcard flows by blocking 65536 ports.
    This is simplest if we take the upper 32768 ports and block the on two hosts with direction any
    Hence top port (65535) - 32768  = 32767

    TODO
    This test needs a rethink - the requirements state that each VIF only supports 128 rules.

    Therefore we will need to generate 512 VIFs (broken at time of writing see NIC-248) and apply
    128 rules to each

    """


    created_protos = []
    def prepare(self, arglist):
        _Controller.prepare(self, arglist)
        self.controller.place.shutdown()
        self.controller.place.cpuset(4)
        self.controller.place.memset(4096) # MB
        self.controller.place.start()
        time.sleep(60)
        # todo remove this
        self.pool.associateDVS(self.controller)

        self.controller.auto = False # will stop login for each request
                                     # as add proto is serial, this will
                                     # greatly reeduce overall test time
        self.VM1 = self.guests[0]
        self.VM2 = self.guests[1]


    def run(self, arglist):
        rules = []
        for i in range (32767, 65536):
            port_name = "port_%d" % i

            proto_uid = self.controller.addProtoForACL(port_name, i, 0, 'TCP', check=False)
            self.created_protos.append(proto_uid)
            rules.append(self.controller.createACL("out", proto_uid, ""))

        xenrt.TEC().logverbose("rules set = %s" % (rules))

        self.controller.auto = True # if the controller is not contacted for 30 seconds
                                    # our cookie will no longer work, this will cause login
                                    # for each new request

        vm_rules = self.controller.getVMRules(self.VM1.getName())
        vm_rules['acl_rules'].extend(rules)

        xenrt.TEC().logverbose("rules we are trying to apply = %s" % (vm_rules))


        self.controller.setVMRules(self.VM1.getName(), vm_rules)
        self.controller.setVMRules(self.VM2.getName(), vm_rules)



    def postRun(self):
        self.controller.removeAllACLRules(self.VM1.getName())
        self.controller.removeAllACLRules(self.VM2.getName())
        # delete all newly created protocols
        # disable auto login for each new request again
        # to save the 32K logins
        self.controller.auto = False
        for proto in self.created_protos:
            path = 'protocol/%d' % proto
            self.controller.delete(path, None)
        _Controller.postRun(self)

class TC11522(_Controller): 
    """
    Verify global policy specifies "No traffic mirroring policy" by default
    and all other levels of the hierarchy specify "Inherit traffic mirroring
    policy from parent" by default.
    """

    def prepare(self, arglist):
        _Controller.prepare(self, arglist)
        self.pool.associateDVS(self.controller)

    def run(self, arglist):
        global_rules = self.controller.getGlobalRules()
        if global_rules["rspan"] != "inherit":
            raise xenrt.XRTFailure("'rspan' rule must be 'inherit' for global 'No traffic mirroring policy' default.")
        if global_rules["rspan_vlan"] != 0:
            raise xenrt.XRTFailure("'rspan_vlan' rule must be '0' for global 'No traffic mirroring policy' default.")

#### CHIN tests ####

class _CHIN(_Controller):
    """Base class for CHIN tests."""

    CHINMAP = ""  
    PAIRS = True 

    class CHIN:

        def pairs(self, list):
            return [ (list[x], list[y]) \
                        for x in xrange(len(list)) \
                            for y in xrange(len(list)) \
                                if not x == y ]

        def attachVIF(self, guest):
            """
            Give a VM an interface on a CHIN.
    
            Given:

            The CHIN index, N.
            The number of VIFs this VM currently has attached to the CHIN, C.
            The total number of VIFs currently attached to the CHIN, M.        

            Then:

            The static IP address of the new interface will be 192.168.N.(M+1).
            """
            xenrt.TEC().logverbose("Attaching VM %s to CHIN %s." % (guest.getName(), self.index))
            if not guest.getHost() in self.hosts:
                self.createTunnel(guest.getHost())
            mac = xenrt.randomMAC()
            vif = guest.createVIF(bridge=self.network, mac=mac, plug=True)
            # CA-75592 suggests that we may be connecting too quickly, so 
            # letting the vif creation settle down.
            time.sleep(5)
            data = guest.getLinuxIFConfigData()
            for device in data:
                if data[device]["MAC"]:
                    if xenrt.normaliseMAC(data[device]["MAC"]) == mac:
                        break
            interfaces = []
            interfaces.append("iface %s inet static" % (device))
            interfaces.append("address 192.168.%s.%s" % (self.index, sum(map(len, self.guests.values())) + 1))
            interfaces.append("netmask 255.255.255.0")
            interfaces.append("hwaddress ether %s" % (mac))
            interfaces.append("allow-hotplug %s" % (device))
            guest.execguest("echo -e '%s' >> /etc/network/interfaces" % (string.join(interfaces, r"\n")))
            guest.execguest("ifup %s" % (device))
            if not guest in self.guests:
                self.guests[guest] = []
            self.guests[guest].append((device, mac, guest.getVIFUUID(vif)))
            return device

        def detachVIF(self, guest, device):
            """
            Remove a guest from a CHIN.
            """
            xenrt.TEC().logverbose("Removing VIF %s on VM %s from CHIN %s." % (device, guest.getName(), self.index))
            if guest in self.guests:
                for guestdevice,mac,vifuuid in self.guests[guest]:
                    if guestdevice == device:
                        cli = self.pool.getCLIInstance()
                        args = []
                        args.append("uuid=%s" % (vifuuid))
                        cli.execute("vif-unplug", string.join(args))
                        cli.execute("vif-destroy", string.join(args))
                        data = guest.execguest("cat /etc/network/interfaces")
                        data = re.sub(re.search("iface %s.*allow-hotplug %s" % (device, device), data, re.DOTALL).group(), "", data)
                        guest.execcmd("echo -e '%s' > /etc/network/interfaces" % (string.join(data.splitlines(), r"\n")))
                        self.guests[guest].remove((device, mac, vifuuid))
                        if not len(self.guests[guest]):
                            del self.guests[guest]

        def createTunnel(self, host):
            """
            Create a CHIN tunnel on a host.
            """
            if not host in self.hosts:
                cli = self.pool.getCLIInstance()
                nics = host.listSecondaryNICs(network=self.subnet)
                if not nics:
                    raise xenrt.XRTError("Host %s has no NICs on %s." % (host.getName(), self.subnet))
                # Use the first available NIC on the subnet.
                device = host.getSecondaryNIC(nics[0])
                xenrt.TEC().logverbose("Using %s (%s) on host %s as a transport PIF." % (device, self.subnet, host.getName()))
                # The transport PIFs must have an IP address configured. We use DHCP.
                pifuuid = host.getPIFUUID(device)
                if not host.genParamGet("pif", pifuuid, "IP"):
                    args = []
                    args.append("uuid=%s" % (pifuuid))
                    args.append("mode=dhcp")
                    cli.execute("pif-reconfigure-ip", string.join(args))
                    # We do NOT plug the PIF at this point. The susequent tunnel-create should take care of this.
                args = []
                args.append("network-uuid=%s" % (self.network))
                args.append("pif-uuid=%s" % (pifuuid))
                tunnel = cli.execute("tunnel-create", string.join(args)).strip()
                self.hosts.append((host, pifuuid, tunnel))

        def destroyTunnel(self, host, pifuuid, tunnel):
            """
            Destroy a CHIN tunnel on a host.
            """
            cli = self.pool.getCLIInstance()
            tunneluuid = host.parseListForUUID("tunnel-list", "access-PIF", tunnel)
            args = []
            args.append("uuid=%s" % (tunneluuid))
            cli.execute("tunnel-destroy", string.join(args))
            self.hosts.remove((host, pifuuid, tunnel))
            if len(self.hosts) == 0:
                self.pool.master.removeNetwork(self.network)

        def destroy(self):
            xenrt.TEC().logverbose("Trying to Remove CHIN %s." % (self.index))
            for guest in copy.copy(self.guests):
                for device,mac,vifuuid in self.guests[guest]:
                    try: 
                        self.detachVIF(guest, device)
                    except Exception, e:
                        xenrt.TEC().logverbose("Exception detaching VIF: %s" % (str(e)))
            while self.hosts:
                try: self.destroyTunnel(*self.hosts[0])
                except Exception, e:
                    xenrt.TEC().logverbose("Exception destroying tunnel: %s" % (str(e)))

        def __init__(self, pool, index, subnet=None):
            self.pool = pool
            self.index = int(index)
            self.subnet = subnet
            self.network = None
            self.guests = {}
            self.hosts = [] 
            if not self.subnet:
                self.subnet = "NPRI"
            self.network = self.pool.master.createNetwork(name="CHIN-%s" % (self.index))

        def check(self):
            """Check if the CHIN is up."""
            for guest in self.guests:
                for device,mac,vifuuid in self.guests[guest]:
                    data = guest.getLinuxIFConfigData()
                    if device in data and data[device]["IP"]:
                        xenrt.TEC().logverbose("Interface %s on VM %s on CHIN %s has IP address %s." % \
                                               (device, guest.getName(), self.index, data[device]["IP"]))
                    else:
                        xenrt.TEC().logverbose("Interface %s on VM %s on CHIN %s has no IP address." % \
                                               (device, guest.getName(), self.index))
                        return False 
            return True

        def test(self, pairs=True):
            xenrt.TEC().logverbose("Testing CHIN %s." % (self.index))
            failures = []
            testmatrix = []
            if pairs:
                for x in self.guests:
                    for y,_,_ in self.guests[x]:
                        testmatrix.append((x,y))
                testmatrix = self.pairs(testmatrix)
            else:
                rootguest = self.guests.keys()[0]
                rootdevice, _, _ = self.guests[rootguest]
                for x in self.guests:
                    for y,_,_ in self.guests[x]:
                        testmatrix.append(((x,y), (rootguest, rootdevice)))
            for x,y in testmatrix:
                a, _ = x
                b, device = y
                xenrt.TEC().logverbose("Testing connection between %s and %s." % (a.getName(), b.getName()))
                ip = b.getLinuxIFConfigData()[device]["IP"]
                try: 
                    a.execguest("ping -w 8 %s" % (ip))
                except: 
                    failures.append((a, b))
            for a,b in failures:
                xenrt.TEC().logverbose("Connection from %s to %s failed." % (a.getName(), b.getName()))
            if failures:
                raise xenrt.XRTFailure("CHIN not fully functional.")

        def wait(self):
            if not self.check():
                if not self.check():
                    for guest in self.guests:
                        for device,mac,vifuuid in self.guests[guest]:
                            guest.execcmd("ifdown %s" % (device))
                            guest.execcmd("ifup %s" % (device))
                    if not self.check():
                        raise xenrt.XRTError("CHIN %s is not up even after we really tried." % (self.index))

        def generate(pool, xmltext):
            chins = []
            value = {} 
            def handleVM(node, id, guests):
                name = node.getAttribute("name")
                if not name:
                    raise xenrt.XRTError("Found VM tag with no name attribute.")
                guest = xenrt.TEC().registry.guestGet(name)
                if not guest:
                    raise xenrt.XRTError("Found VM that is not present in the registry.")
                guests.append(guest)
            def handleNetwork(node):
                id = node.getAttribute("id")
                subnet = node.getAttribute("network")
                guests = []
                for child in node.childNodes:
                    if child.localName == "vm":
                        handleVM(child, id, guests)
                chins.append((id, subnet, guests))
            def handleCHINNode(node):
                for child in node.childNodes:
                    if child.localName == "network":
                        handleNetwork(child)

            xmltree = xml.dom.minidom.parseString(xmltext)
            for child in xmltree.childNodes:
                if child.localName == "CHIN":
                    handleCHINNode(child)
            for chin in chins:
                id, subnet, guests = chin
                c = _CHIN.CHIN(pool, id, subnet)
                for g in guests:
                    c.attachVIF(g)
                value[int(id)] = c
            return value
        generate = staticmethod(generate)    

    def prepare(self, arglist=[]):
        self.chins = []
        _Controller.prepare(self, arglist)
        self.pool.associateDVS(self.controller)
        xenrt.TEC().logverbose("CHINMAP: %s" % (self.CHINMAP))
        self.chins = self.CHIN.generate(self.pool, self.CHINMAP)
        self.guests = [self.getGuest(gn) for gn in self.pool.master.listGuests()]
        for guest in self.guests:
            self.setupGuestTcpDump(guest)
        for chin in self.chins.values():
            chin.wait()
            try: chin.test(self.PAIRS) 
            except Exception, e:
                xenrt.TEC().logverbose("First test of CHIN %s failed. Retrying in 30s..." % (chin.index))
                time.sleep(30)
                chin.test(self.PAIRS)

    def run(self, arglist=()):
        pass

    def postRun(self):
        for chin in self.chins.values():
            chin.destroy()
        for guest in self.guests:
            try: guest.execcmd("killall ping")
            except: pass

class TC11939(_CHIN):
    """ 
    Enable CHIN

    On a pool of two or more hosts, each with one or more VMs, create a CHIN network
    Give each VM an interface on the CHIN network. 
    Each CHIN network should share a distinct statically allocated subnet.
    Ensure that the VMs can communicate over the CHIN subnet.
    """

    CHINMAP = """
    <CHIN>
      <network id="1" network="NSEC">
        <vm name="p0h0-0"/>
        <vm name="p0h1-0"/>
      </network>
    </CHIN>
    """

class TC14456(_CHIN):
    """
    Reconfigure the IP address of the underlying transport PIFs.
    """

    CHINMAP = """
    <CHIN>
      <network id="1" network="NSEC">
        <vm name="p0h0-0"/>
        <vm name="p0h1-0"/>
      </network>
    </CHIN>
    """

    def run(self, arglist=[]):
        for host,pifuuid,tunnel in self.chins[1].hosts:
            cli = host.getCLIInstance()
            args = []
            args.append("uuid=%s" % (pifuuid))
            args.append("mode=dhcp")
            cli.execute("pif-reconfigure-ip", string.join(args))
            self.chins[1].test()

class TC11941(_CHIN):
    """
    CHIN No Leak

    Ensure that chin traffic does not leak.
    """

    CHINMAP = """
    <CHIN>
      <network id="1" network="NSEC">
        <vm name="p0h0-0"/>
        <vm name="p0h1-0"/>
      </network>
      <network id="2" network="NSEC">
        <vm name="p0h0-0"/>
        <vm name="p0h1-0"/>
      </network>
    </CHIN>
    """

    def run(self, arglist=[]):
        src = self.getGuest("p0h0-0")
        dst = self.getGuest("p0h1-0")
        testchin = self.chins[1]
        controlchin = self.chins[2]
        source = src.getLinuxIFConfigData()[testchin.guests[src][0][0]]["IP"]
        destination = dst.getLinuxIFConfigData()[testchin.guests[dst][0][0]]["IP"]
        # Start a continous ping on the test CHIN.
        src.execcmd("nohup ping %s &>/dev/null &" % (destination))
        # Check traffic is seen on the test CHIN VIFs.
        try:
            src.execcmd("tcpdump -i %s -c 1 icmp and src %s and dst %s" % \
                        (testchin.guests[src][0][0], source, destination), timeout=30)
        except xenrt.XRTFailure:
            raise xenrt.XRTFailure("ICMP packet not seen on source VMs test CHIN VIF.")
        try:
            dst.execcmd("tcpdump -i %s -c 1 icmp and src %s and dst %s" % \
                        (testchin.guests[dst][0][0], source, destination), timeout=30)
        except xenrt.XRTFailure:
            raise xenrt.XRTFailure("ICMP packet not seen on destination VMs test CHIN VIF.")
        # Check traffic is NOT seen on the control CHIN VIFs.
        try:
            src.execcmd("tcpdump -i %s -c 1 icmp and src %s and dst %s" % \
                        (controlchin.guests[src][0][0], source, destination), timeout=30)
        except: pass
        else:
            raise xenrt.XRTFailure("ICMP packet seen on source VMs control CHIN VIF.")
        try:
            dst.execcmd("tcpdump -i %s -c 1 icmp and src %s and dst %s" % \
                        (controlchin.guests[dst][0][0], source, destination), timeout=30)
        except: pass
        else:
            raise xenrt.XRTFailure("ICMP packet seen on destination VMs control CHIN VIF.")
        for host,pifuuid,tunnel in testchin.hosts:
            bridge = host.genParamGet("network", host.genParamGet("pif", pifuuid, "network-uuid"), "bridge")
            # Check traffic is not seen in hosts' domain 0.
            try:
                host.execdom0("tcpdump -i %s -c 1 icmp and src %s and dst %s" % \
                             (bridge, source, destination), timeout=30)
            except: pass
            else:
                raise xenrt.XRTFailure("ICMP packet seen on %s's transport bridge." % (host.getName()))
            # Check GRE traffic between the guests IS seen in hosts' domain 0.
            try:
                host.execdom0("tcpdump -i %s -c 1 proto gre" % (bridge), timeout=30)
            except xenrt.XRTFailure:
                raise xenrt.XRTFailure("GRE packet not seen on %s's transport bridge." % (host.getName()))
    
class TC12418(_CHIN):
    """
    16 CHINs per pool 

    Ensure that 16 CHINs can be created and that each pair of endpoints on the CHIN can communicate.
    """

    CHINS = 16

    def prepare(self, arglist=[]):
        chins = []
        for i in range(self.CHINS):
            chins.append('<network id="%s" network="NSEC">' % (i+1))
            chins.append('<vm name="p0h0-%s"/>' % (i/6))
            chins.append('<vm name="p0h1-%s"/>' % (i/6))
            chins.append('</network>')
        self.CHINMAP = "<CHIN>%s</CHIN>" % (string.join(chins))
        _CHIN.prepare(self, arglist)

class TC12543(_CHIN):
    """ 
    16 Hosts per CHIN 

    Across a pool of 16 hosts create 1 chin with a VM on each host connected to that CHIN.

    Check traffic passes across the CHIN. 
    """
    
  
    CHINMAP = """
    <CHIN>
      <network id="1" network="NSEC">
        <vm name="p0h0-0"/>
        <vm name="p0h1-0"/>
        <vm name="p0h2-0"/>
        <vm name="p0h3-0"/>
        <vm name="p0h4-0"/>
        <vm name="p0h5-0"/>
        <vm name="p0h6-0"/>
        <vm name="p0h7-0"/>
        <vm name="p0h8-0"/>
        <vm name="p0h9-0"/>
        <vm name="p0h10-0"/>
        <vm name="p0h11-0"/>
        <vm name="p0h12-0"/>
        <vm name="p0h13-0"/>
        <vm name="p0h14-0"/>
        <vm name="p0h15-0"/>
      </network>
    </CHIN>
    """

class TC12551(_CHIN): 
    """
    256 VIFs per CHIN 
    """
       
    CHINS = 16

    CHINMAP = """
    <CHIN>
      <network id="1" network="NSEC">
        %s
      </network>
    </CHIN>
    """

    def prepare(self, arglist=[]):
        chins = []
        vmstring = '<vm name="p%sh%s-%s"/>'
        #16 CHINs with 16 vifs each.
        for i in range(self.CHINS):
            s = string.join(sorted(map(lambda x:vmstring % (x), 
                                   [ (j/17,j,i/6) for j in range(16) ])))
            chins.append('<network id="%s" network="NSEC">' % (i+1))
            chins.append(s)
            chins.append('</network>')
        self.CHINMAP = "<CHIN>%s</CHIN>" % (string.join(chins))
        _CHIN.prepare(self, arglist)

#### RSPAN Tests ####

class _RSPAN(_Controller):

    def __init__(self, tcid=None, anon=False):
        _Controller.__init__(self, tcid=tcid, anon=anon)
        self.vlanid = None
        self.sourcevif = None

    def getGuestFromUUID(self, uuid):
        guest = None
        for guest in map(self.getGuest, xenrt.TEC().registry.guestList()):
            if guest.getUUID() == uuid:
                break
        if not guest or not guest.getUUID() == uuid:
            raise xenrt.XRTError("Cannot find guest object for uuid %s." % (uuid))
        return guest

    def getGuestInterface(self, mac):
        for p in map(lambda x:xenrt.TEC().registry.data[x], 
                     filter(lambda x:re.search("POOL", x), 
                            xenrt.TEC().registry.data.keys())):
            vifuuid = p.master.parseListForUUID("vif-list", "MAC", mac)
            if vifuuid:
                vmuuid = p.master.parseListForOtherParam("vif-list", "MAC", mac, "vm-uuid")
                break
        guest = self.getGuestFromUUID(vmuuid)
        data = guest.getLinuxIFConfigData()
        device = None
        for device in data:
            if data[device]["MAC"]:
                if xenrt.normaliseMAC(data[device]["MAC"]) == mac:
                    break
        if not device or not xenrt.normaliseMAC(data[device]["MAC"]) == mac:
            raise xenrt.XRTError("Cannot find guest interface for MAC %s." % (mac))
        return device

    def createVIF(self, guest, network, ip=None):
        mac = xenrt.randomMAC()
        guest.createVIF(bridge=network, mac=mac, plug=True)
        device = self.getGuestInterface(mac)
        interfaces = []
        if ip:
            interfaces.append("iface %s inet static" % (device))
            interfaces.append("address %s" % (ip)) 
            interfaces.append("netmask 255.255.255.0")
        else:
            interfaces.append("iface %s inet dhcp" % (device))
        interfaces.append("hwaddress ether %s" % (mac))
        interfaces.append("allow-hotplug %s" % (device))
        guest.execguest("echo -e '%s' >> /etc/network/interfaces" % (string.join(interfaces, r"\n")))
        guest.execguest("ifup %s" % (device))
        return mac

    def removeVIF(self, mac):
        for p in map(lambda x:xenrt.TEC().registry.data[x], 
                     filter(lambda x:re.search("POOL", x), 
                            xenrt.TEC().registry.data.keys())):
            vifuuid = p.master.parseListForUUID("vif-list", "MAC", mac)
            if vifuuid:
                vmuuid = p.master.parseListForOtherParam("vif-list", "MAC", mac, "vm-uuid")
                break
        guest = self.getGuestFromUUID(vmuuid)
        device = self.getGuestInterface(mac)
        cli = guest.getHost().getCLIInstance()
        args = []
        args.append("uuid=%s" % (vifuuid))
        cli.execute("vif-unplug", string.join(args))
        cli.execute("vif-destroy", string.join(args))
        data = guest.execguest("cat /etc/network/interfaces")
        data = re.sub(re.search("iface %s.*allow-hotplug %s" % (device, device), data, re.DOTALL).group(), "", data)
        guest.execcmd("echo -e '%s' > /etc/network/interfaces" % (string.join(data.splitlines(), r"\n")))

    def getRSPANVLAN(self):
        rspan = xenrt.TEC().lookup(["NETWORK_CONFIG", "VLANS", "RSPAN", "ID"], None)
        if not rspan:
            raise xenrt.XRTError("This test must be run on a site with a configured RSPAN VLAN.")
        return int(rspan)

    def getRSPANPIF(self, host):
        rspannics = host.listSecondaryNICs(rspan=True)
        if not rspannics:
            raise xenrt.XRTError("to RSPAN NICs found on host %s." % (host.getName()))
        return host.getNICPIF(rspannics[0])

    def mirrorVIF(self, mac):
        rules = self.controller.getVIFRules(mac)
        rules["rspan"] = "set"
        rules["rspan_vlan"] = self.rspanVLAN
        self.controller.setVIFRules(mac, rules)
 
    def unmirrorVIF(self, mac):
        rules = self.controller.getVIFRules(mac)
        rules["rspan"] = "inherit"
        rules["rspan_vlan"] = 0
        self.controller.setVIFRules(mac, rules)
 
    def prepare(self, arglist=[]):
        _Controller.prepare(self, arglist)
        self.sourceNetwork = None
        self.pool.associateDVS(self.controller)
        self.source = self.getGuest("p0h0-0")
        self.target = self.getGuest("p0h1-0")
        self.source.execcmd("rm -f "
                            "/etc/udev/rules.d/z25_persistent-net.rules "
                            "/etc/udev/rules.d/z45_persistent-net-generator.rules")
        self.target.execcmd("rm -f "
                            "/etc/udev/rules.d/z25_persistent-net.rules "
                            "/etc/udev/rules.d/z45_persistent-net-generator.rules")
        self.rspanVLAN = self.getRSPANVLAN()
        self.targetPIF = self.getRSPANPIF(self.target.getHost())
        self.sourcePIF = self.getRSPANPIF(self.source.getHost())
        self.network = self.source.getHost().genParamGet("pif", self.sourcePIF, "network-uuid")
        self.rspanNetwork = self.pool.master.createNetwork(name="RSPAN")
        self.target.getHost().createVLAN(self.rspanVLAN, self.rspanNetwork, pifuuid=self.targetPIF)
        self.targetvif = self.createVIF(self.target, self.rspanNetwork, ip="192.168.0.1")
        self.controller.addRSPANTargetVLAN(self.rspanVLAN)
        self.setupGuestTcpDump(self.target)
 
    def run(self, arglist=[]):
        sourcedevice = self.getGuestInterface(self.sourcevif)
        sourceip = self.source.getLinuxIFConfigData()[sourcedevice]["IP"]
        xrtcontroller = xenrt.TEC().lookup("XENRT_SERVER_ADDRESS")
        self.source.execguest("nohup ping -i 5 -I %s %s &> /dev/null &" % (sourcedevice, xrtcontroller))
        vifdevice = "vif%s.%s" % (self.source.getDomid(), 
                                  self.source.getHost().parseListForOtherParam("vif-list", 
                                                                               "MAC", 
                                                                                self.sourcevif, 
                                                                               "device"))
        # Check for ICMP request and reply on VM VIF.
        try: self.source.getHost().execdom0("tcpdump -i %s -c 1 icmp and src %s and dst %s" % \
                                           (vifdevice, sourceip, xrtcontroller), timeout=30)
        except: raise xenrt.XRTFailure("ICMP request packet not seen on VIF. (%s)" % (vifdevice))
        try: self.source.getHost().execdom0("tcpdump -i %s -c 1 icmp and src %s and dst %s" % \
                                           (vifdevice, xrtcontroller, sourceip), timeout=30)
        except: raise xenrt.XRTFailure("ICMP reply packet not seen on VIF. (%s)" % (vifdevice))

        # Check ICMP request and reply aren't seen on the monitoring interface.
        targetdevice = self.getGuestInterface(self.targetvif)
        try: self.target.execguest("tcpdump -i %s -c 1 icmp and src %s and dst %s" % \
                                  (targetdevice, sourceip, xrtcontroller), timeout=30)
        except: pass
        else: raise xenrt.XRTFailure("ICMP request packet seen on target interface.")
        try: self.target.execguest("tcpdump -i %s -c 1 icmp and src %s and dst %s" % \
                                  (targetdevice, xrtcontroller, sourceip), timeout=30)
        except: pass
        else: raise xenrt.XRTFailure("ICMP reply packet seen on target interface.")

        # Mirror the source interface to the target interface.
        self.mirrorVIF(self.sourcevif)

        # Check ICMP request and reply can be seen on the monitoring interface.
        try: self.target.execguest("tcpdump -i %s -c 1 icmp and src %s and dst %s" % \
                                  (targetdevice, sourceip, xrtcontroller), timeout=30)
        except: raise xenrt.XRTFailure("ICMP request packet not seen on target interface.")
        try: self.target.execguest("tcpdump -i %s -c 1 icmp and src %s and dst %s" % \
                                  (targetdevice, xrtcontroller, sourceip), timeout=30)
        except: raise xenrt.XRTFailure("ICMP reply packet not seen on target interface.")
       
        # Stop mirroring traffic.
        self.unmirrorVIF(self.sourcevif)
 
        # Check ICMP request and reply aren't seen on the monitoring interface.
        try: self.target.execguest("tcpdump -i %s -c 1 icmp and src %s and dst %s" % \
                                  (targetdevice, sourceip, xrtcontroller), timeout=30)
        except: pass
        else: raise xenrt.XRTFailure("ICMP request packet seen on target interface.")
        try: self.target.execguest("tcpdump -i %s -c 1 icmp and src %s and dst %s" % \
                                  (targetdevice, xrtcontroller, sourceip), timeout=30)
        except: pass
        else: raise xenrt.XRTFailure("ICMP reply packet seen on target interface.")

        # Check both guests we used are still reachable.
        self.source.checkHealth()
        self.target.checkHealth()

    def postRun(self):
        try: self.source.execguest("killall ping")
        except: pass
        try: self.unmirrorVIF(self.sourcevif)
        except: pass
        self.removeVIF(self.targetvif)
        self.target.getHost().removeVLAN(self.rspanVLAN)
        self.pool.master.removeNetwork(nwuuid=self.rspanNetwork)
        self.source.shutdown()
        for vif in self.source.getVIFs():
            self.source.removeVIF(vif)
        self.sourcevif = xenrt.randomMAC()
        bridge = self.source.getHost().getPrimaryBridge()
        self.source.createVIF(bridge=bridge, mac=self.sourcevif)
        if self.source.getState() == "DOWN":
            self.source.start() 
        try: self.source.getHost().removeVLAN(self.vlanid)
        except: pass
        try: self.source.getHost().removeNetwork(self.sourceNetwork)
        except: pass
        self.controller.removeRSPANTargetVLAN(self.rspanVLAN)
        _Controller.postRun(self)

class TC11526(_RSPAN):
    """
    Mirroring
     
    At a policy level other than global, specify a VLAN on which the traffic should be mirrored.
    Sniff the VLAN to ensure traffic is being mirrored.

    """

    def prepare(self, arglist=[]):
        _RSPAN.prepare(self, arglist)
        # Make sure p0h0-0 has its only VIF on an RSPAN enabled bridge. 
        self.source.shutdown()
        for vif in self.source.getVIFs():
            self.source.removeVIF(vif)
        self.sourcevif = xenrt.randomMAC()
        bridge = self.source.getHost().getBridgeWithMapping(\
                    self.source.getHost().listSecondaryNICs(rspan=True)[0])
        self.source.createVIF(bridge=bridge, mac=self.sourcevif)
        if self.source.getState() == "DOWN":
           self.source.start() 

class TC11531(_RSPAN):
    """
    VLAN mangling
     
    Check that VLAN traffic mirrored to a VLAN has the original VLAN ID in the tag overwritten.

    This test requires 2 VLANs one for VRnn and one for RSPAN.

    The VRnn traffic should be mirrored to the RSPAN VLAN and the VRnn VLAN Tag should be overwritten
    by the RSPAN VLAN tag.
    """

    VLAN = "VR01" 

    def prepare(self, arglist=[]):
        _RSPAN.prepare(self, arglist)
        # Make sure p0h0-0 has its only VIF on VR01.
        self.vlanid = int(xenrt.TEC().config.lookup(["NETWORK_CONFIG", "VLANS", self.VLAN, "ID"]))
        self.sourceNetwork = self.pool.master.createNetwork(name="VLAN %s" % (self.vlanid))
        self.source.getHost().createVLAN(self.vlanid, self.sourceNetwork, pifuuid=self.sourcePIF)
        self.source.shutdown()
        for vif in self.source.getVIFs():
            self.source.removeVIF(vif)
        self.sourcevif = xenrt.randomMAC()
        self.source.createVIF(bridge=self.sourceNetwork, mac=self.sourcevif)
        if self.source.getState() == "DOWN":
            self.source.start() 

class TC11532(TC11531):
    """
    Ensure that traffic mirrored to the RSPAN VLAN can be seen:

        * On a VIF on the same host as the mirrored VIF.
        * On a VIF on a different host in the same pool as the VIF.
        * On a VIF on a different host outside the pool.
    """
   
    def prepare(self, arglist=[]):
        TC11531.prepare(self, arglist)
        self.targets = []
        self.targets.append((self.target, self.targetvif))
        xenrt.TEC().registry.poolGet("RESOURCE_POOL_1").associateDVS(self.controller)
        self.controller.removeRSPANTargetVLAN(self.rspanVLAN)
        self.controller.addRSPANTargetVLAN(self.rspanVLAN)
        for extra in ["p0h0-1", "p1h0-0"]:
            extra = self.getGuest(extra)
            extra.execguest("rm -f "
                            "/etc/udev/rules.d/z25_persistent-net.rules "
                            "/etc/udev/rules.d/z45_persistent-net-generator.rules")
            network = extra.getHost().parseListForUUID("network-list", "name-label", "RSPAN")
            if not network:
                network = extra.getHost().createNetwork(name="RSPAN")
            try:
                extra.getHost().createVLAN(self.rspanVLAN, network, pifuuid=self.getRSPANPIF(extra.getHost()))
            except: pass
            targetvif = self.createVIF(extra, network, ip="192.168.0.1")
            self.setupGuestTcpDump(extra)
            self.targets.append((extra, targetvif)) 

    def run(self, arglist=[]):
        self.mirrorVIF(self.sourcevif)
        sourcedevice = self.getGuestInterface(self.sourcevif)
        sourceip = self.source.getLinuxIFConfigData()[sourcedevice]["IP"]
        xrtcontroller = xenrt.TEC().lookup("XENRT_SERVER_ADDRESS")
        self.source.execguest("nohup ping -i 5 -I %s %s &> /dev/null &" % (sourcedevice, xrtcontroller))
        for guest,mac in self.targets:
            interface = self.getGuestInterface(mac)
            xenrt.TEC().logverbose("Looking for RSPAN traffic on %s %s (%s)." % \
                                   (guest.getName(), interface, mac))
            # Check ICMP request and reply can be seen on the monitoring interface.
            try: guest.execguest("tcpdump -i %s -c 1 icmp and src %s and dst %s" % \
                                 (interface, sourceip, xrtcontroller), timeout=30)
            except: raise xenrt.XRTFailure("ICMP request packet not seen on target interface.")
            try: guest.execguest("tcpdump -i %s -c 1 icmp and src %s and dst %s" % \
                                 (interface, xrtcontroller, sourceip), timeout=30)
            except: raise xenrt.XRTFailure("ICMP reply packet not seen on target interface.")

    def postRun(self):
        try: self.source.execguest("killall ping")
        except: pass
        try: self.unmirrorVIF(self.sourcevif)
        except: pass
        for guest,mac in self.targets:
            nwuuid = guest.getHost().parseListForOtherParam("vif-list", "MAC", mac, "network-uuid")
            self.removeVIF(mac)
            try: guest.getHost().removeVLAN(self.rspanVLAN)
            except: pass
            try: guest.getHost().removeNetwork(nwuuid=nwuuid)
            except: pass
        self.source.shutdown()
        for vif in self.source.getVIFs():
            self.source.removeVIF(vif)
        self.sourcevif = xenrt.randomMAC()
        bridge = self.source.getHost().getPrimaryBridge()
        self.source.createVIF(bridge=bridge, mac=self.sourcevif)
        if self.source.getState() == "DOWN":
            self.source.start() 
        try: self.source.getHost().removeVLAN(self.vlanid)
        except: pass
        try: self.source.getHost().removeNetwork(self.sourceNetwork)
        except: pass
        self.controller.removeRSPANTargetVLAN(self.rspanVLAN)
        xenrt.TEC().registry.poolGet("RESOURCE_POOL_1").disassociateDVS()
        _Controller.postRun(self)

class TC11582(TC11531): 
    """
    Obey RSPAN and Netflow

    A collector must continue to receive all netflow data whenever the controller dies.
    In fail safe mode some VMS may be lost but all exisiting VMs and their VIFs will 
    continue to generate traffic and hence their netflow data should be visible.

    Similarly any RSPAN mirror that has been configured should continue to operate, but if 
    the VM becomes uncontactable due to the fail safe mechanism, it will not generate traffic 
    and hence RSPAN cannot work.

    Therefore it is only worth testing obeying netflow and RSPAN with a failed controller
    in fail open mode.

    """

    def prepare(self, arglist=[]):
        TC11531.prepare(self, arglist)
        # Enable fail-open mode.
        self.controller.setPoolFailMode(self.host.getIP(), 0)
        self.receiver = self.getGuest("p1h0-0")
        self.setupGuestTcpDump(self.receiver)

    def run(self, arglist=[]):
        self.controller.setNetflowCollector(self.pool.master.getIP(), self.receiver.getIP(), 9996, False)
        self.receiver.execguest("tcpdump -c 1 port 9996") 
        # Mirror the source interface to the target interface.
        self.mirrorVIF(self.sourcevif)
        sourcedevice = self.getGuestInterface(self.sourcevif)
        sourceip = self.source.getLinuxIFConfigData()[sourcedevice]["IP"]
        xrtcontroller = xenrt.TEC().lookup("XENRT_SERVER_ADDRESS")
        targetdevice = self.getGuestInterface(self.targetvif)
        self.source.execguest("nohup ping -i 5 -I %s %s &> /dev/null &" % (sourcedevice, xrtcontroller))
        # Check ICMP request and reply can be seen on the monitoring interface.
        try: self.target.execguest("tcpdump -i %s -c 1 icmp and src %s and dst %s" % \
                                  (targetdevice, sourceip, xrtcontroller), timeout=30)
        except: raise xenrt.XRTFailure("ICMP request packet not seen on target interface.")
        try: self.target.execguest("tcpdump -i %s -c 1 icmp and src %s and dst %s" % \
                                  (targetdevice, xrtcontroller, sourceip), timeout=30)
        except: raise xenrt.XRTFailure("ICMP reply packet not seen on target interface.")

        # Disconnect the controller from the network.
        self.controller.place.unplugVIF('eth0')

        self.receiver.execguest("tcpdump -c 1 port 9996") 

        # Check ICMP request and reply can be seen on the monitoring interface.
        try: self.target.execguest("tcpdump -i %s -c 1 icmp and src %s and dst %s" % \
                                  (targetdevice, sourceip, xrtcontroller), timeout=30)
        except: raise xenrt.XRTFailure("ICMP request packet not seen on target interface.")
        try: self.target.execguest("tcpdump -i %s -c 1 icmp and src %s and dst %s" % \
                                  (targetdevice, xrtcontroller, sourceip), timeout=30)
        except: raise xenrt.XRTFailure("ICMP reply packet not seen on target interface.")

        self.controller.place.plugVIF("eth0")

#### vSwitch Scalability Tests ####

class _TC11537(object):
    """
    Base class providing Create VIFs/VMs for TC11537 sequences
    """

    machnum = -1 # simplifies thread synchronisation
    myguests = []
    lock = threading.Lock()
    ip_counter = 0
    mac_counter = 0
    seed_guests = []
    vifs_to_remove = []
    test_dead = False
    hosts = []

    def createNVifsOnGuest (self, n, guest):
        guest.execguest("cp /etc/network/interfaces /root/interfaces")
        for i in range(1, n + 1):
            eth = "eth%d" % i
            self.lock.acquire()
            ip_counter = self.ip_counter
            mac_counter = self.mac_counter
            self.ip_counter += 1
            self.mac_counter += 1
            self.lock.release()

            mac = "1a:37:36:11:%02x:%02x" % (mac_counter / 255, mac_counter % 255)

            # each machine will have n subnets with its machine number
            # identifing itself on each
            ip = "192.168.%d.%d" % (ip_counter / 253, (ip_counter % 253) + 1)

            # note subnet will require max 512 interfaces
            guest.execguest("echo 'iface %s inet static \n"
                            "address %s\nnetmask 255.255.240.0\n"
                            "hwaddress ether %s' >> "
                            "/etc/network/interfaces" %  (eth, ip, mac))
            bridge="xenbr0"
            guest.createVIF(eth, bridge, mac, plug=True)
            guest.execguest("ifup %s" % eth)

    def copyThisVMOnItsHost(self, vm_to_clone, num_guests, num_vifs):
        try:
            # store some values from the clean-up operation
            # do this in thread safe manner as this is likely to be called across
            # many hosts
            self.lock.acquire()
            self.seed_guests.append(vm_to_clone)
            self.vifs_to_remove.append(num_vifs)
            self.lock.release()

            vm_to_clone.execcmd("rm -f "
                                 "/etc/udev/rules.d/z25_persistent-net.rules "
                                 "/etc/udev/persistent-net-generator.rules")
            vm_to_clone.shutdown()
            first = True
            # self.machnum is shared across threads
            # slight danger that two vms get the same name here
            # but this is preventend once we enter the loop

            for i in range(num_guests):
                self.lock.acquire()
                self.machnum += 1
                machid = self.machnum
                vmname="clone%d" % (machid)
                self.lock.release()

                # - there is a cloning limitation
                if i > 0 and i % 20 == 0:
                    g = vm_to_clone.copyVM(name=vmname)
                    vm_to_clone.start() # start the previous vm_to_clone
                    if num_vifs > 0:
                        self.createNVifsOnGuest(num_vifs, vm_to_clone)
                    vm_to_clone = g
                    g.tailored=True
                else:
                    g = vm_to_clone.cloneVM(name=vmname)
                    g.tailored=True
                    g.start()
                    self.createNVifsOnGuest(num_vifs, g)

                # dont forget we need to copy every 30th clone

                # piece of code to protect shared variables in threaded execution
                self.lock.acquire()
                self.myguests.append(g)
                self.lock.release()
                # Kill this thread if another has died
                if self.test_dead == True:
                    break

            # all vms have been created start the last vm to clone
            vm_to_clone.start()
            if num_vifs > 0:
                self.createNVifsOnGuest(num_vifs, vm_to_clone)
        except Exception, e:
            warning("VM clone operation failed : %s" % e)
            self.test_dead=True
             

    def createVMsOnHost(self, host, num_guests, num_vifs):
        vm_to_clone = host.guests.values()[0]
        self.copyThisVMOnItsHost(vm_to_clone, num_guests, num_vifs)

    def createManyGuestsInPool(self,nbrOfGuests, extra_vifs=0):
        nbrOfHosts = len(self.hosts)
        (guestsPerHost, nbrOfGuestsOnLastHost) = self.proposeGuestDistribution(nbrOfGuests)
        
        comment("Number of guests on each host = %d." % guestsPerHost)
        comment("Number of guests on last host = %d." % nbrOfGuestsOnLastHost)
        
        # use parallel threads to create guest clones on each slave host in the pool 
        for host in self.hosts[:-1]: 
            xenrt.pfarm ([xenrt.PTask(self.createVMsOnHost, host, (guestsPerHost-1), extra_vifs)], wait = False)

        # use main thread to create clones on master host in the pool
        self.createVMsOnHost(self.hosts[(nbrOfHosts - 1)], (nbrOfGuestsOnLastHost-1), extra_vifs)

        singleGuestCreationTimeout = 20 * 60
        counterStep  = 5*60
        timeSinceLastGuestCreated  = 0
        previousNbrOfGuests = 0
        
        # we already have one guest on each host.
        nbrOfVmsToCreate = ((nbrOfHosts - 1) * (guestsPerHost-1)) + (nbrOfGuestsOnLastHost-1)
        
        while self.test_dead == False and len(self.myguests) < nbrOfVmsToCreate :
            currentNbrOfGuests = len(self.myguests)
            
            # additional guest VM is created in 1 counterStep
            if currentNbrOfGuests != previousNbrOfGuests: 
                timeSinceLastGuestCreated  = 0
            
            if timeSinceLastGuestCreated >= singleGuestCreationTimeout:
                raise xenrt.XRTFailure("No new guests created in last %d minutes. Test created only (%d/%d) guests." % ((timeSinceLastGuestCreated/60),currentNbrOfGuests, nbrOfVmsToCreate))
            
            xenrt.sleep(counterStep)
            timeSinceLastGuestCreated += counterStep
            previousNbrOfGuests = currentNbrOfGuests

    def proposeGuestDistribution(self, nbrOfGuests):
        """Propose a distribution of guests among hosts such that we have roughly x guests on each host and 0.5x guests on last host (master)"""

        nbrOfHosts = len(self.hosts)
        # nbrOfGuests < nbrOfHosts or one host in the pool
        if nbrOfGuests < nbrOfHosts or nbrOfHosts == 1:
            return (0, nbrOfGuests)

        # guestsPerHost is the solution to equation: N_guests = (N_hosts-1) * x + 0.5x
        guestsPerHost = int(round( ( nbrOfGuests /(nbrOfHosts - 0.5) ) ))
        nbrOfGuestsOnLastHost = int(nbrOfGuests - guestsPerHost*(nbrOfHosts - 1))

        return (guestsPerHost, nbrOfGuestsOnLastHost)

    def deleteGuestsFromPool(self):
        """ keep deleting guests until number of guests become zero """

        while len(self.myguests)>0: 
            try:
                self.lock.acquire()
                guest = self.myguests.pop()
                self.lock.release()
                guest.uninstall()
            except:
                pass

    def postRun(self):
        self.maxNbrOfThreads = 200
        
        try:
            log("Uninstall guest clones")
            xenrt.pfarm ([xenrt.PTask(self.deleteGuestsFromPool) for thread in range(self.maxNbrOfThreads)])
        except Exception, e:
            warning("_TC11537.postRun Exception: %s" % e)

        log("Clean extra vifs")
        for guest_num in range(len(self.seed_guests)):
            
            # remember that eth0 already exists we want to remove eth1 ... for this guest
            for i in range(self.vifs_to_remove[guest_num]):
                vif_to_remove = "eth%d" % (i + 1) 
                self.seed_guests[guest_num].execguest("ifdown %s" % (vif_to_remove))
                self.seed_guests[guest_num].unplugVIF(vif_to_remove)
                self.seed_guests[guest_num].removeVIF(vif_to_remove)
            
            #restore guest network interface file, if exists.
            if(self.vifs_to_remove[guest_num] >0):
                self.seed_guests[guest_num].execguest("cp /root/interfaces /etc/network/interfaces")

class TC11541(_VSwitch, _TC11537):

    """
        Add 7 VIFs to a VM
        Create 6 more VIFs to a host and check the network between them
        and an external host
    """
    def prepare(self, arglist):
        _VSwitch.prepare(self, arglist)

    def run(self, arglist):
        # this will enable _TC11537 to clean up
        self.seed_guests.append(self.guests[0])
        self.vifs_to_remove.append(6)

        # now create the VIFs
        self.createNVifsOnGuest(6, self.guests[0])
        self.checkNetwork(self.guests, "7 VIFs")

    def postRun(self):
        _TC11537.postRun(self)
        _VSwitch.postRun(self)

class TC11540(_VSwitch, _TC11537):
    """
        512 Interfaces on a Host
        The Sequence file provides 2 VMs and the host is assumed to have one physical interface
        We need 72 new VMs and 7 VIFs on all but one guest which has 1 VIF
    """

    def prepare(self, arglist):
        _VSwitch.prepare(self, arglist)

    def run(self, arglist):
        self.createVMsOnHost(self.hosts[0], 72, 6)
        # As linux_1 has 1 VIF and the above creates 6 additional
        # vifs on every VM, including the seed (linux_0) we now
        # have (72 * 7) = 511, + 1 = 512 VIFs on a single host

    def postRun(self):
        _TC11537.postRun(self)

class TC11544bridge (_VSwitch, _TC11537):
    """
    1024 Guests per controller
    """
    def prepare(self, arglist):
        _VSwitch.prepare(self, arglist)

    def run(self, arglist):
        self.createManyGuestsInPool(nbrOfGuests=1024, extra_vifs=0)

    def postRun(self):
        _TC11537.postRun(self)
        _VSwitch.postRun(self)

class TC11542(_VSwitch, _TC11537):
    """
    2048 learned MACs per bridge
    """
    guest0vifs = []
    def prepare(self, arglist):
        _VSwitch.prepare(self, arglist)
        # back up interfaces file on vm0
        xenrt.TEC().logverbose("self.guests[0].name = %s" % (self.guests[0].getName()))
        self.guests[0].execguest("cp /etc/network/interfaces /root/interfaces")

    def run(self, arglist):
        self.createManyGuestsInPool(nbrOfGuests=1024, extra_vifs=1)

        self.guest0vifs = self.guests[0].getVIFs()
        ## all newly created guests ping the existing guest
        for guest in self.myguests:
            # as the 2 vifs are created on seperate networks this generates pairs
            guest.execguest("echo '#!/bin/bash\nping -i 2 %s &\nping -i 2 %s&\n' > /root/script && chmod a+x /root/script && nohup /root/script > /root/script.out 2> /dev/null&" % (self.guest0vifs['eth0'][1], self.guest0vifs['eth1'][1]))

        # 2046 VIFs will now ping the guest0's 2 vifs giving 2048
        # note that 2046 * 56 bytes is only 114576 bytes and each VIF only pings every 2 seconds
        # hence network load will be 57288 bytes per second
        time.sleep(60)

        # to do this will remain incomplete until we are told how to query the 2048 learn MAC addresses
        vswitchd_pid = self.host.execdom0("cat /var/run/openvswitch/ovs-vswitchd.pid")
        learned_macs = self.host.execdom0("ovs-appctl -t /var/run/openvswitch/ovs-vswitchd\.%s\.ctl -e fdb/show xenbr0" % (vswitchd_pid.strip()))

        learned_macs_list = learned_macs.split("\n")
        # print the learned max list
        for item in learned_macs_list:
            xenrt.TEC().logverbose("%s" % (item))

        learned_mac_count = len(learned_macs.split("\n")) - 1
        # print the count of items in the list
        xenrt.TEC().logverbose("Learned MAC count = %d" % (learned_mac_count))
        if (learned_mac_count < 2048):
            raise xenrt.XRTFailure("Less that 2048 learned MAC addresses %d" % (learned_mac_count))

    def postRun(self):
        _TC11537.postRun(self)
        # all guests now removed
        self.guests[0].unplugVIF("eth1")
        self.guests[0].removeVIF("eth1")
        self.guests[0].execguest("cp /root/interfaces /etc/network/interfaces")

#### Controller Scalability Tests ####

class TCManyGuestsInPool(_Controller, _TC11537):
    """
    Many Guests per controller

    """
    def prepare(self, arglist):
        _Controller.prepare(self, arglist)
        self.pool.associateDVS(self.controller)
        self.controller.place.shutdown()
        self.controller.place.cpuset(4)
        self.controller.place.memset(4096) # MB
        self.controller.place.start()
        self.extra_vifs = 0

    def run(self, arglist=None):
        
        step("Fetching arguments")
        try:
            l = string.split(arglist[0], "=", 1)
            if l[0].strip() == "guests":
                nbrOfGuests = int(l[1].strip())
                log("Argument: '%s' = '%s'" % (l[0].strip(),l[1].strip()))
            else:
                raise Exception("Number of guests not specified.")
        except:
            raise xenrt.XRTError("Number of guests must be specified within the <testcase> block in the the sequence file, e.g. '<arg>guests=1024</arg>'")

        step("Creating a large number of guests in the pool")
        self.createManyGuestsInPool(nbrOfGuests, self.extra_vifs)

        step("Checking created guests in controller.")
        all_vms = self.controller.getVMsInPool(self.host.getName())
        if len(all_vms) != nbrOfGuests:
            raise xenrt.XRTFailure("Failed to see %d VMs at controller. VMs shown by controller = %d, VMs created successfully = %d."
                                   % ( (nbrOfGuests) , len(all_vms), len(self.myguests)))
        
    def postRun(self):
        _TC11537.postRun(self)
        _Controller.postRun(self)
