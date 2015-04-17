import xenrt
import libperf
import string
import time
from xenrt.lazylog import log, step, comment, warning

initscriptname = "wait-for-host-enable"
initscript = '''#!/bin/bash
# 
# wait-for-host-enable  Print a syslog message when this host is enabled
# 
# chkconfig: 345 99 99
# description: Wait for this host to become enabled

logger "waiting for this host to become enabled..."
while [ "$(xe host-list hostname=$(hostname) params=enabled --minimal)" != "true" ]; do sleep 1; done
logger "this host is now enabled"
'''

class TCVlanScalability(libperf.PerfTestCase):

    def __init__(self):
        libperf.PerfTestCase.__init__(self, "TCVlanScalability")

        self.testVM = None
        self.networks = {}    # index -> network uuid
        self.hosteth0pif = {} # hostname -> pif uuid
        self.hostvlans = {}   # hostname -> (index -> vlan uuid)

        self.createLog = "create"
        self.destroyLog = "destroy"
        self.rebootLog = "reboot"
        self.bootstartgrepkey = "klogd [0-9\.]*,"
        self.bootfinishgrepkey = "this host is now enabled"

    def parseArgs(self, arglist):
        # Parse generic arguments
        libperf.PerfTestCase.parseArgs(self, arglist)

        # Parse arguments relating to this test
        self.numvlans = libperf.getArgument(arglist, "numvlans", int, 500)

    def prepare(self, arglist=None):
        self.basicPrepare(arglist)

    # Append the duration of cmd to the array durs. Return the output from cmd.
    def execCommandMeasureTime(self, durs, cmd):
        output = self.host.execdom0("time %s" % cmd)
        val = "\n".join(output.split('\n')[0:-4])
        durs.append(libperf.parseTimeOutput(output))
        return val

    def createSingleVLAN(self, i):
        durs = []

        # Create a network
        self.networks[i] = self.execCommandMeasureTime(durs, "xe network-create name-label=vlan-net-%d" % i).strip()
        xenrt.TEC().logverbose("self.networks[%d] = %s" % (i, self.networks[i]))

        # On each host in the pool, create a VLAN and plug it
        for h in self.normalHosts:
            if not h in self.hostvlans:
                self.hostvlans[h] = {}

            self.hostvlans[h][i] = self.execCommandMeasureTime(durs, "xe vlan-create vlan=%d network-uuid=%s pif-uuid=%s" % (i, self.networks[i], self.hosteth0pif[h])).strip()
            xenrt.TEC().logverbose("self.hostvlans[%s][%d] = %s" % (h, i, self.hostvlans[h][i]))

            self.execCommandMeasureTime(durs, "xe pif-plug uuid=%s" % self.hostvlans[h][i])

        # Create a VIF on the test VM and plug it. (This checks that xapi isn't cheating in VLAN.create!)
        self.vif = self.execCommandMeasureTime(durs, "xe vif-create network-uuid=%s vm-uuid=%s device=%d mac=%s" % (self.networks[i], self.testVM.uuid, 2, xenrt.randomMAC())).strip()
        xenrt.TEC().logverbose("self.vif = %s" % (self.vif))

        self.execCommandMeasureTime(durs, "xe vif-plug uuid=%s" % self.vif)

        # Destroy the VIF (because the VM can only handle so many before crashing...)
        self.host.execdom0("xe vif-unplug uuid=%s" % self.vif)
        self.host.execdom0("xe vif-destroy uuid=%s" % self.vif)

        # Compute the total control-plane time for this operation
        s = sum(durs)

        self.log(self.createLog, "%d    %s  %f" % (i, ",".join(map(str, durs)), s))

        return s

    def destroySingleVLAN(self, i):
        durs = []

        # Destroy all VLAN PIFs
        for h in self.normalHosts:
            self.execCommandMeasureTime(durs, "xe pif-unplug uuid=%s" % self.hostvlans[h][i])
            self.execCommandMeasureTime(durs, "xe vlan-destroy uuid=%s" % self.hostvlans[h][i])

        # Destroy the network
        self.execCommandMeasureTime(durs, "xe network-destroy uuid=%s" % self.networks[i])

        # Compute the total control-plane time for this operation
        s = sum(durs)

        self.log(self.destroyLog, "%d    %s  %f" % (i, ",".join(map(str, durs)), s))

        return s

    def createVLANs(self):
        durkeys = ["network-create"]
        for h in self.normalHosts:
            durkeys.append("%s_vlan-create" % h)
            durkeys.append("%s_pif-plug" % h)
        durkeys.append("vif-create")
        durkeys.append("vif-plug")
        self.log(self.createLog, "# vlan %s  total" % (",".join(durkeys)))

        for i in range(1, self.numvlans+1):
            if i%200 == 0 and xenrt.TEC().lookup("WORKAROUND_CA95084", False, boolean=True):
                log("rebooting vm after creating %s vlans" % i)
                self.testVM.reboot()
            dur = self.createSingleVLAN(i)
            xenrt.TEC().logverbose("total duration for creating VLAN %d was %f" % (i, dur))

    def destroyVLANs(self):
        durkeys = []
        for h in self.normalHosts:
            durkeys.append("%s_pif-unplug" % h)
            durkeys.append("%s_vlan-destroy" % h)
        durkeys.append("network-destroy")
        self.log(self.destroyLog, "# vlan %s  total" % (",".join(durkeys)))

        for i in range(1, self.numvlans+1):
            dur = self.destroySingleVLAN(i)
            xenrt.TEC().logverbose("total duration for destroying VLAN %d was %f" % (i, dur))

    def rebootHosts(self, prewaitsleep=240, boottime=7200):
        # Install a pseudo init-script on each host that watches for the host to become enabled
        for h in self.normalHosts:
            host = self.tec.gec.registry.hostGet(h)

            libperf.RemoteRunner().transfer(host, initscriptname, initscript, "+x")
            host.execdom0("mv /root/%s /etc/init.d/%s" % (initscriptname, initscriptname))
            host.execdom0("chkconfig --add %s" % initscriptname)

        # Reboot the hosts
        xenrt.TEC().logverbose("Rebooting hosts...")
        for h in self.normalHosts:
            host = self.tec.gec.registry.hostGet(h)
            host.execdom0("/sbin/reboot &")

        # Wait for the hosts to come up
        time.sleep(prewaitsleep)
        for h in self.normalHosts:
            host = self.tec.gec.registry.hostGet(h)
            host.waitForSSH(boottime, desc="Host boot after forced reboot")

        xenrt.TEC().logverbose("All hosts are now contactable")

        # Now wait for them all to become enabled
        allenabled = False
        startTime = xenrt.util.timenow()
        deadline = startTime + 3600*4 # 4 hours
        while not allenabled:
            time.sleep(1)
            # Get a comma-separated list of booleans, one per host
            try:
                output = host.execdom0("xe host-list params=enabled --minimal").strip()
                xenrt.TEC().logverbose("output: %s" % output)
            except xenrt.XRTFailure:
                output = ""
                xenrt.TEC().logverbose("xapi still not contactable")
            
            # See if they are all true
            allenabled = reduce(lambda x,y: x and y, map(lambda x: x=="true", output.split(",")))
            if xenrt.util.timenow() > deadline:
                raise xenrt.XRTError("Timed out waiting for hosts to become enabled")

        xenrt.TEC().logverbose("All hosts are enabled")

        # When they are all up, see how long they took to become enabled
        self.log(self.rebootLog, "# host bootduration")
        for h in self.normalHosts:
            host = self.tec.gec.registry.hostGet(h)

            [bootstarttime, bootfinishtime] = map (lambda g: int(host.execdom0("date -d \"$(grep -h \"%s\" /var/log/{user.log,kern.log,messages} 2> /dev/null | tail -n 1 | awk '{print $1\" \"$2\" \"$3}')\" '+%%s'" % g).strip()), [self.bootstartgrepkey, self.bootfinishgrepkey])
            if bootstarttime == 0:
                xenrt.XRTError("on %s, could not find '%s' in /var/log/messages" % (host.getName(), self.bootstartgrepkey))
            if bootfinishtime == 0:
                xenrt.XRTError("on %s, could not find '%s' in /var/log/messages" % (host.getName(), self.bootfinishgrepkey))

            bootdur = bootfinishtime - bootstarttime

            if bootdur < 0:
                xenrt.XRTError("on %s, boot started at %d and finished at %d -- impossible!" % (host.getName(), bootstarttime, bootfinishtime))

            self.log(self.rebootLog, "%s %d" % (host.getName(), bootdur))

    def run(self, arglist=None):
        
        step("Installing Linux Guest")
        self.testVM = self.host.createGenericLinuxGuest()
        
        step("Find out the eth0 PIFs on each host")
        for h in self.normalHosts:
            host = self.tec.gec.registry.hostGet(h)
            self.hosteth0pif[h] = host.execdom0("xe pif-list device=eth0 host-uuid=%s params=uuid --minimal" % host.uuid).strip()

        step("Create VLANs")
        self.createVLANs()

        step("Reboot hosts")
        self.rebootHosts()
        
        step("Destroy VLANs")
        self.destroyVLANs()

    def postRun(self):
        self.finishUp()

