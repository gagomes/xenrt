#
# callirrhoe - multiple-simultaneous-vifs network throughput tests
#

import libperf
import xenrt
import random, string
import tc_networkthroughput2
from random import randrange
import libsynexec

# Expects the sequence file to set up two VMs, called 'endpoint0' and 'endpoint1'
#
class TCNetworkThroughputMultipleVifs(tc_networkthroughput2.TCNetworkThroughputPointToPoint):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCNetworkThroughputMultipleVifs")
        self.endpoint0s = {}
        self.endpoint1s = {}

    def parseArgs(self, arglist):
        # Parse generic arguments
        tc_networkthroughput2.TCNetworkThroughputPointToPoint.parseArgs(self, arglist)

        self.log(None, "parseArgs:arglist=%s" % (arglist,))
        self.dom0vcpus   = libperf.getArgument(arglist, "dom0vcpus", int, 0)
        self.nr_vm_pairs = libperf.getArgument(arglist, "vmpairs", int, 1)

        self.log(None, "nr_vm_pairs=%s" % (self.nr_vm_pairs,))
        # - a vm has only one vif (to maximize n.of vifs)
        # - a vm_i_endpoint0 talks only to its partner vm_i_endpoint1 in the pair i
        # - there must be as many netback threads as dom0 vcpus

    def get_nr_dom0_vcpus(self, host_endpoint):
        nr_dom0_vcpus = int(host_endpoint.execcmd("cat /sys/devices/system/cpu/online").strip().split("-")[1])+1
        return nr_dom0_vcpus

    def get_vcpus_and_netback_threads(self, host_endpoint, vifs_in_the_host=None):
        nr_dom0_vcpus = self.get_nr_dom0_vcpus(host_endpoint)
        #netback_per_cpu (tampa, clearwater) uses a "[netback" thread per cpu
        #netback_per_vif (sarasota onwards) uses a "[vif" thread per vif
        nr_netback_threads_per_cpu = int(host_endpoint.execcmd('ps aux| grep "\[netback/*." |grep -v grep | wc -l').strip())
        nr_netback_threads_per_vif = int(host_endpoint.execcmd('ps aux| grep "\[vif*." |grep -v -- -dea |grep -v grep | wc -l').strip())

        # basic sanity checks
        if nr_netback_threads_per_cpu > 0 and nr_netback_threads_per_vif > 0:
            raise Exception("both nr_netback_threads_per_cpu=%s >0 and nr_netback_threads_per_vif=%s >0" % (nr_netback_threads_per_cpu, nr_netback_threads_per_vif))
        if nr_netback_threads_per_vif > 0:
            nr_dom0_netback_threads = nr_netback_threads_per_vif
            is_netback_thread_per_vif = True
        elif nr_netback_threads_per_cpu > 0:
            nr_dom0_netback_threads = nr_netback_threads_per_cpu
            is_netback_thread_per_vif = False
        else:
            if vifs_in_the_host:
                raise Exception("both nr_netback_threads_per_cpu=0 and nr_netback_threads_per_vif=0")
            else:
                is_netback_thread_per_vif = True
                nr_dom0_netback_threads = 0

        if not is_netback_thread_per_vif:
            #we have the same number of netback threads as dom0vcpus in netback_per_cpu mode
            if nr_dom0_vcpus != nr_dom0_netback_threads:
                raise Exception("nr_dom0_vcpus=%s != nr_dom0_netback_threads=%s" % (nr_dom0_vcpus, nr_dom0_netback_threads))
        else:
            if vifs_in_the_host:
                if vifs_in_the_host != nr_dom0_netback_threads:
                    raise Exception("vifs_in_the_host=%s != nr_dom0_netback_threads=%s" % (vifs_in_the_host, nr_dom0_netback_threads))

        self.log(None, "nr_dom0_vcpus=%s, nr_dom0_netback_threads=%s, self.dom0vcpus=%s, is_netback_thread_per_vif=%s" % (nr_dom0_vcpus, nr_dom0_netback_threads, self.dom0vcpus, is_netback_thread_per_vif))
        return (nr_dom0_vcpus, nr_dom0_netback_threads, is_netback_thread_per_vif)

    def check_nr_netback_threads(self, host_endpoint, nr_vifs):
        if host_endpoint.productType=="kvm":
            #no dom0vcpus or netback threads to check for
            return
        elif host_endpoint.productType=="esx":
            #no dom0vcpus or netback threads to check for
            return
        else:
            self.get_vcpus_and_netback_threads(host_endpoint, vifs_in_the_host=nr_vifs)

    def changeNetbackThreads(self, host_endpoint):
        if host_endpoint.productType=="kvm":
            #use whatever number of cpus is available in the kvm host
            self.dom0vcpus = self.get_nr_dom0_vcpus(host_endpoint)
            self.log(None, "kvm host %s: detected %s cpus" % (host_endpoint, self.dom0vcpus))
            return False
        elif host_endpoint.productType=="esx":
            self.dom0vcpus = 4
            self.log(None, "esx host %s: detected %s cpus" % (host_endpoint, self.dom0vcpus))
            return False
        else:
            if self.dom0vcpus == 0:
                # don't change anything -- use the default number of dom0 vCPUs and netback threads
                self.dom0vcpus = self.get_nr_dom0_vcpus(host_endpoint)
		self.log(None, "xenserver host %s: detected %s cpus" % (host_endpoint, self.dom0vcpus))
                return False

            nr_dom0_vcpus, nr_dom0_netback_threads, is_netback_thread_per_vif = self.get_vcpus_and_netback_threads(host_endpoint)
            self.log(None, "nr_dom0_vcpus=%s, nr_dom0_netback_threads=%s, self.dom0vcpus=%s, is_netback_thread_per_vif=%s" % (nr_dom0_vcpus, nr_dom0_netback_threads, self.dom0vcpus, is_netback_thread_per_vif))
            if not is_netback_thread_per_vif:
                if nr_dom0_netback_threads == self.dom0vcpus:
                    # nothing to do
                    return False
            else:
                if nr_dom0_vcpus == self.dom0vcpus:
                    # nothing to do
                    return False

            out1 = host_endpoint.execcmd("/opt/xensource/libexec/xen-cmdline --set-xen dom0_max_vcpus=%s" % (self.dom0vcpus,))
            self.log(None, "set dom0_max_vcpus: result=%s" % (out1,))
            out2 = host_endpoint.execcmd("/opt/xensource/libexec/xen-cmdline --set-dom0 xen-netback.netback_max_groups=%s" % (self.dom0vcpus,))
            self.log(None, "set netback_max_groups: result=%s" % (out2,))
            host_endpoint.reboot()
            nr_dom0_vcpus, nr_dom0_netback_threads, is_netback_thread_per_vif = self.get_vcpus_and_netback_threads(host_endpoint)
            self.log(None, "nr_dom0_vcpus=%s, nr_dom0_netback_threads=%s, self.dom0vcpus=%s, is_netback_thread_per_vif=%s" % (nr_dom0_vcpus, nr_dom0_netback_threads, self.dom0vcpus, is_netback_thread_per_vif))
            if not is_netback_thread_per_vif:
                if nr_dom0_netback_threads != self.dom0vcpus:
                    raise Exception("nr_dom0_netback_threads=%s != self.dom0vcpus=%s" % (nr_dom0_netback_threads, self.dom0vcpus))
            else:
                if nr_dom0_vcpus != self.dom0vcpus:
                    raise Exception("nr_dom0_vcpus=%s != self.dom0vcpus=%s" % (nr_dom0_vcpus, self.dom0vcpus))

            return True

    def host_of(self, endpoint):
        if isinstance(endpoint, xenrt.GenericGuest):
            endpoint = endpoint.host
        return endpoint

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)

        # Populate self.guests
        self.findGuests()

        self.log(None, "prepare:arglist=%s" % (arglist,))
        # Get the two vm endpoints to clone
        e0 = libperf.getArgument(arglist, "endpoint0", str, None)
        e1 = libperf.getArgument(arglist, "endpoint1", str, None)
        self.log(None, "endpoints to clone: e0=%s, e1=%s" % (e0,e1))
        if not e0 or not e1:
            raise xenrt.XRTError("Failed to find an endpoint")
        self.endpoint0 = self.getGuestOrHostFromName(e0)
        self.endpoint1 = self.getGuestOrHostFromName(e1)

        # change number of netback threads if required
        rebooted_e0 = self.changeNetbackThreads(self.host_of(self.endpoint0)) #may reboot
        rebooted_e1 = self.changeNetbackThreads(self.host_of(self.endpoint1)) #may reboot
        if rebooted_e0 or rebooted_e1:
            self.findGuests()    #repopulate guest/host info
            self.endpoint0 = self.getGuestOrHostFromName(e0)
            self.endpoint1 = self.getGuestOrHostFromName(e1)

        #cloning phase
        # - vms are cloned from the one in the sequence file to fit many vms in the same local sr of a host
        self.clone(self.endpoint0, self.endpoint0s)
        self.clone(self.endpoint1, self.endpoint1s)

    def clone(self, endpoint, endpoints):
        if endpoint not in endpoints:
            endpoints[endpoint] = [] # list of vms cloned from endpoint
            self.start_endpoint(endpoint) #required state to install iperf
            endpoint.installIperf(version="2.0.5")
            libsynexec.initialise_slave(endpoint)

        # reuse any existing clone
        for g in self.guests:
            g_name = g.getName()
            endpoint_name = endpoint.getName()
            is_clone = g_name.startswith("%s-" % (endpoint_name,))
            self.log(None, "endpoints=%s, endpoint=%s, g=%s, g_name=%s, endpoint_name=%s, is_clone=%s" % (endpoints, endpoint, g, g_name, endpoint_name, is_clone))
            if is_clone and g not in endpoints[endpoint]:
                endpoints[endpoint].append(g)

        self.log(None, "self.nr_vm_pairs=%s, endpoint=%s, endpoints=%s, self.endpoints_of(endpoint)=%s" % (self.nr_vm_pairs, endpoint, endpoints, self.endpoints_of(endpoint)))

        if endpoint.distro.startswith("rhel") or endpoint.distro.startswith("centos") or endpoint.distro.startswith("oel"):
            # When we clone this guest, we don't want it to remember its MAC address
            endpoint.execguest("sed -i /HWADDR/d /etc/sysconfig/network-scripts/ifcfg-eth0")

        # clone as needed
        if self.nr_vm_pairs > len(self.endpoints_of(endpoint)):
            self.shutdown_endpoint(endpoint) #required state for cloning
        for i in range(len(self.endpoints_of(endpoint)), self.nr_vm_pairs):
            new_name = "%s-%d" % (endpoint.getName(), i)
            cloned_endpoint = endpoint.cloneVM(new_name)
            endpoints[endpoint].append(cloned_endpoint)
            endpoint.host.addGuest(cloned_endpoint)

    def before_prepare(self, arglist=None):
        pass

    def endpoints_of(self, endpoint, n=None):
        if n==None: n=self.nr_vm_pairs
        #returns all endpoints cloned from endpoint, including endpoint
        all_endpoints = [endpoint] + (dict(self.endpoint1s.items() + self.endpoint0s.items())[endpoint])
        return all_endpoints[:n]

    def install_git(self, endpoint):
        if endpoint.execcmd("git --version", retval="code"):
            if endpoint.distro.startswith('centos') or endpoint.distro.startswith('rhel'):
                endpoint.execcmd("yum install git")
            elif endpoint.distro.startswith('sles'):
                endpoint.execcmd("zypper -n install git-core")
            else:
                endpoint.execcmd("apt-get install --force-yes -y git")

    def runIperf(self, origin, origindev, dest, destdev, interval=1, duration=30, threads=1, protocol="tcp"):

        prot_switch = None
        if protocol == "tcp":   prot_switch = ""
        elif protocol == "udp": prot_switch = "-u"
        else: raise xenrt.XRTError("unknown protocol %s" % (protocol,))

        dest_endpoints   = self.endpoints_of(dest)
        origin_endpoints = self.endpoints_of(origin)
        synexec_session  = randrange(1000000000)
        iperf_in_file  = "/tmp/iperf.in.%s" % (synexec_session,)
        iperf_out_file = "/tmp/iperf.out.%s" % (synexec_session,)

        if dest.windows:
            raise Exception("Windows endpoint not supported yet")
        else:

            # 1. start iperf servers in each vm in endpoint1s + endpoint1
            for d in dest_endpoints:
                # Start server
                d.execcmd("nohup iperf %s -s 0<&- &>/dev/null &" % (prot_switch,)) # should be implemented in startIperf()

            # 1.5. initialise synexec master in endpoint0
            libsynexec.initialise_master_in_guest(origin)

            # 2. start synexec slave in each vm in endpoint0s + endpoint0
            for i in range(len(origin_endpoints)):
                o = origin_endpoints[i]
                d   = dest_endpoints[i]
                destIP = self.getIP(d, destdev)
                libsynexec.start_slave(o, synexec_session)
                o.execcmd("echo %s > %s" % (destIP, iperf_in_file))

            # 3. create synexec master script in endpoint 0 to run iperf -c in each slave
            master_script = """/bin/sh :CONF:
#!/bin/sh
DEST_IP=$(cat "%s")
iperf %s -c ${DEST_IP} -i %d -t %d -f m -P %d >%s 2>&1
""" % (iperf_in_file, prot_switch, interval, duration, threads, iperf_out_file)
            self.log(None, "synexec_master_script=%s" % (master_script,))

            if self.dopause.lower() == "on" or (xenrt.TEC().lookup("PAUSE_AT_MASTER_ON_PHASE", "None") in self.getPhase()):
                self.pause('paused before running synexec_master')  # pause the tc and wait for user assistance

            # 4. start synexec master in endpoint0
            # 5. wait for synexec master to finish (=all synexec slaves finished iperf -c)
            master_out = libsynexec.start_master_in_guest(origin, master_script, synexec_session, len(origin_endpoints))
            self.log(None, master_out)

            # 6. kill iperf servers in each vm in endpoints1s + endpoint1
            for d in dest_endpoints:
                # Kill server
                d.execcmd("killall iperf || true")
                d.execcmd("killall -9 iperf || true")
            for o in origin_endpoints:
                libsynexec.kill_slave(o)

            # 7. collect the iperf -c output in each endpoint0s + endpoint0
            output = []
            for o in origin_endpoints:
                iperf_out = o.execcmd("cat %s" % (iperf_out_file,))
                self.log(None, "collect results: endpoint %s: %s=%s" % (o, iperf_out_file, iperf_out))
                output.append(iperf_out)

        return output

    def start_endpoint(self, endpoint):
        self.log(None, "start_endpoint: endpoint %s state: %s" % (endpoint, endpoint.getState()))
        if endpoint.getState() == "DOWN": endpoint.start()

    def shutdown_endpoint(self, endpoint):
        self.log(None, "shutdown_endpoint: endpoint %s state: %s" % (endpoint, endpoint.getState()))
        if endpoint.getState() == "UP": endpoint.shutdown()

    def provide_endpoints(self, endpoint, fn=None):
        if fn==None: fn=self.start_endpoint
        endpoints = self.endpoints_of(endpoint)
        #shutdown the endpoints that are not going to be required
        for i in range(self.nr_vm_pairs, len(endpoints)):
            self.shutdown_endpoint(endpoints[i])
        #start the required endpoints
        for i in range(0, self.nr_vm_pairs):
            fn(endpoints[i])

    def setIPFromPattern(self, endpoint, endpointdev, ippattern, offset=0):
        i = offset
        for ep in self.endpoints_of(endpoint):
            # Replace the "%" in the pattern with the index of the endpoint
            ip = ippattern.replace("%", str(i))
            self.setIPAddress(ep, endpointdev, ip)
            i = i+1

    def run(self, arglist=None):

        # set up gro if required
        self.setup_gro()

        # start the endpoints that will participate in the run
        self.provide_endpoints(self.endpoint0)
        self.provide_endpoints(self.endpoint1)

        #shutdown any vms not in any endpoints that are going to participate in the run
        for g in self.guests:
            self.log(None, "g=%s, self.endpoint0=%s, self.endpoint1=%s, self.endpoints_of(self.endpoint0)=%s, self.endpoints_of(self.endpoint1)=%s" % (g, self.endpoint0, self.endpoint1, self.endpoints_of(self.endpoint0), self.endpoints_of(self.endpoint1)))
            if g not in self.endpoints_of(self.endpoint0) and g not in self.endpoints_of(self.endpoint1):
                self.shutdown_endpoint(g)

        self.e0dev = None if self.e0devstr is None else int(self.e0devstr)
        self.e1dev = None if self.e1devstr is None else int(self.e1devstr)

        # Give IP addresses to the endpoints if necessary
        if self.e0ip:
            self.setIPFromPattern(self.endpoint0, self.e0dev, self.e0ip, offset=0)
        if self.e1ip:
            self.setIPFromPattern(self.endpoint1, self.e1dev, self.e1ip, offset=128)

        # Collect as much information as necessary for the rage importer
        info = {}
        if self.host_of(self.endpoint0) == self.host_of(self.endpoint1):
            total_nr_hosts = 1
        else:
            total_nr_hosts = 2
        vifs_per_vm = len(self.endpoint0.vifs) # assume same number of vifs on each endpoint
        info["vifs_per_vm"] = vifs_per_vm
        info["total_nr_hosts"] = total_nr_hosts
        total_nr_vifs_per_host  = vifs_per_vm * (self.nr_vm_pairs * 2) / total_nr_hosts
        info["total_nr_vifs_per_host"]  = total_nr_vifs_per_host
        info["vifs_per_dom0vcpu"] = total_nr_vifs_per_host / self.dom0vcpus
        info["dom0vcpus"] = self.dom0vcpus
        vif_pairs = vifs_per_vm * self.nr_vm_pairs
        info["vif_pairs"] = vif_pairs
        # sanity checks
        self.check_nr_netback_threads(self.host_of(self.endpoint0), total_nr_vifs_per_host)
        self.check_nr_netback_threads(self.host_of(self.endpoint1), total_nr_vifs_per_host)
        # collect rage data
        self.rageinfo(info = info)

        # Run some traffic in one direction between all pairs simultaneously
        output = self.runIperf(self.endpoint1, self.e1dev, self.endpoint0, self.e0dev, interval=self.interval, duration=self.duration, threads=self.threads, protocol=self.protocol)
        for i in range(0, len(output)):
            self.log("iperf.1to0.%d" % (i,), output[i])

        # Now run traffic in the reverse direction between all pairs simultaneously
        output = self.runIperf(self.endpoint0, self.e0dev, self.endpoint1, self.e1dev, interval=self.interval, duration=self.duration, threads=self.threads, protocol=self.protocol)
        for i in range(0, len(output)):
            self.log("iperf.0to1.%d" % (i,), output[i])

    def postRun(self):
        # make sure we don't have any vms running to interfere with potential future runs in the same sequence and different endpoints
        #self.provide_endpoints(self.endpoint0, fn=self.shutdown_endpoint)
        #self.provide_endpoints(self.endpoint1, fn=self.shutdown_endpoint)

        self.finishUp()
