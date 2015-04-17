#
# XenRT: Test harness for Xen and the XenServer product family
#
# Testcase for vhostmd
#
# Copyright (c) 2012 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import xml.dom.minidom
import time, sys
import re
import xenrt, xenrt.lib.xenserver

UPDATE_PERIOD = 60 # seconds between updates of the vhostmd data.

def ensure(requirement, failString):
    if not requirement:
        raise xenrt.XRTFailure(failString)

# Pure functions (except for references to UPDATE_PERIOD)

def areTextNodesBlank(elem):
    """Returns whether an XML DOM element contains any non-blank text.
    Does not descend tree: just checks elem's immediate children."""
    return '' == ''.join([n.data for n in elem.childNodes
                          if n.nodeType == xml.dom.Node.TEXT_NODE]).strip()

def getText(elem):
    """Specifically for a DOM element that should contain some text and nothing else."""
    if [] == elem.childNodes:
        return ""
    childCount = len(elem.childNodes)
    ensure(1 == childCount, "Found %d DOM nodes where there should be one." % childCount)
    ensure(elem.childNodes[0].nodeType == xml.dom.Node.TEXT_NODE,
           "Expected DOM node of type text (%s) but got %s." %
           (xml.dom.Node.TEXT_NODE, elem.childNodes[0].nodeType))
    return elem.childNodes[0].data

def getNameAndValue(metricNode):
    return (getText(metricNode.getElementsByTagName("name")[0]),
            getText(metricNode.getElementsByTagName("value")[0]))

def handleHostMetric(metricNode, dataDate):
    """Examines the DOM node to check that it contains a metric with an
    expected name and type and a reasonable value. If the name is "Time", the
    value must be close to the dataDate parameter."""
    vtype = metricNode.getAttribute("type")
    (name, value) = getNameAndValue(metricNode)
    if "TotalCPUTime" == name:
        ensure("real64" == vtype, "Host metric TotalCPUTime should have type real64; got %s." % vtype)
        try:
            t = float(value)
        except:
            raise xenrt.XRTFailure("Could not parse host metric %s as float: %s" % (name, value))
        ensure(18.0 < t and t < 900.0, "Host metric TotalCPUTime has bad value %s" % t)
    elif "uint64" == vtype:
        try:
            lv = long(value)
        except:
            raise xenrt.XRTFailure("Could not parse host metric %s as long: %s" % (name, value))
        if name in ["PagedOutMemory", "PagedInMemory"]:
            ensure(0 <= lv and lv <= 1000, "Host metric %s has bad value %d" % (name, lv))
        elif name in ["UsedVirtualMemory", "MemoryAllocatedToVirtualServers"]:
            ensure(0 <= lv and lv <= 7000, "Host metric %s has bad value %d" % (name, lv))
        elif name in ["FreeVirtualMemory", "FreePhysicalMemory"]:
            # Up to two terabytes, since the units here are MB.
            ensure(2 <= lv and lv <= 2**21, "Host metric %s has bad value %d" % (name, lv))
        else:
            ensure("Time" == name, "Found uint64 host metric with unexpected name %s." % name)
            ensure(abs(dataDate - lv) <= (UPDATE_PERIOD/10),
                   "Host metric for Time is %d but metrics-file timestamp is %d." %(lv, dataDate))
    elif "NumberOfPhysicalCPUs" == name:
        ensure("uint32" == vtype, "Host metric %s should have type uint32." % name)
        try:
            n = int(value)
        except:
            raise xenrt.XRTFailure("Could not parse host metric %s as int: %s" % (name, value))
        ensure(n >= 4 and n <= 1024, "Host metric %s has bad value %d" % (name, n))
    else:
        ensure("string" == vtype, "Host metric %s should have type string, not %s" %(name, vtype))
        if name in ["HostSystemInfo", "HostName"]:
            ensure(len(value) > 1 and len(value) <= 500, "Host metric %s has bad length %d" % (name, len(value)))
        elif "VirtProductInfo" == name:
            # major.minor.micro
            ensure(re.match("\d+\.\d+\.\d+$", value),
                   "Host metric VirtProductInfo should be major.minor.micro but is %s" % value)
        elif "VirtualizationVendor" == name:
            ensure("Citrix Systems, Inc." == value, "Host metric VirtualizationVendor has bad value %s" % value)
        else:
            raise xenrt.XRTFailure("Unknown string-type host metric: %s" % name)


def handleVmMetric(metricNode, dom0cpuCount):
    """Examines the DOM node to check that it contains a metric with an
    expected name and type and a reasonable vmid and value."""
    ensure(metricNode.hasAttribute("uuid"), "Found a VM metric element with no uuid attribute.")
    try:
        vmid = metricNode.getAttribute("id")
        vtype = metricNode.getAttribute("type")
    except Exception, e:
        raise xenrt.XRTFailure, e, sys.exc_info()[2]
    (name, value) = getNameAndValue(metricNode)
    # Two vm ids: 0 for dom0, 1 for the guest.
    ensure(vmid in ["0", "1"], "VM id should be 0 or 1 but got %s." % vmid)
    isGuest = ("1" == vmid)
    if "PhysicalMemoryAllocatedToVirtualSystem" == name:
        ensure("uint64" == vtype, "VM metric %s should have type uint64; got %s." % (name, vtype))
        try:
            intV = int(value)
        except:
            raise xenrt.XRTFailure("Could not parse VM metric %s as int: %s" % (name, value))
        # Insisting on exact values for memory is brittle, but fail-fast.
        if isGuest:
            ensure(256 == intV, "VM metric %s for vm %s should be 256 not %s." % (name, vmid, intV))
        else:
            ensure(280 < intV and intV <= 4500, "VM metric %s for dom0 should be 281-4500 not %s." % (name, intV))
    elif "ResourceMemoryLimit" == name:
        ensure("uint64" == vtype, "VM metric %s should have type uint64; got %s." % (name, vtype))
        if isGuest:
            try:
                intV = int(value)
            except:
                raise xenrt.XRTFailure("Could not parse guest-VM metric %s as int: %s" % (name, value))
            ensure(256 == intV, "VM metric %s for vm %s should be 256 not %s." % (name, vmid, intV))
        else:
            ensure("" == value, "VM metric %s for dom0 should be the empty string; got %s." % (name, value))
    elif "ResourceProcessorLimit" == name:
        ensure("uint32" == vtype, "VM metric %s should have type uint32; got %s." % (name, vtype))
        try:
            intV = int(value)
        except:
            raise xenrt.XRTFailure("Could not parse VM metric %s as int: %s" % (name, value))
        if isGuest:
            ensure(1 == intV, "VM metric %s for guest should be 1; got %s." % (name, intV))
        else:
            ensure(dom0cpuCount == intV, "VM metric %s for dom0 should be %s; got %s." % (name, dom0cpuCount, intV))
    elif "TotalCPUTime" == name:
        ensure("real64" == vtype, "VM metric %s should have type real64; got %s." % (name, vtype))
        try:
            t = float(value)
        except:
            raise xenrt.XRTFailure("Could not parse VM metric %s as float: %s" % (name, value))
        if isGuest:
            ensure(0.4 < t and t < 40.0, "VM metric %s for vm %s has implausible value %s." % (name, vmid, t))
        else:
            ensure(16.0 < t and t < 850.0, "VM metric %s for vm %s has implausible value %s." % (name, vmid, t))
    else:
        raise xenrt.XRTFailure("Metric has unrecognised name %s." % name)

class TC15961(xenrt.TestCase):
    """Tests that vhostmd can be made to work the way SAP requires."""

    def prepare(self, arglist=[]):
        # Get a host to install on
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericLinuxGuest(vcpus=1)

    def run(self, arglist):
        # vhostmd and the SHM SR type should be disabled in a newly installed
        # XenServer host
        if self.runSubcase("checkNewInstallation", (), "vhostmd", "DisabledByDefault") != \
                xenrt.RESULT_PASS:
            return
        # Set it up for use and connect it to a guest VM
        if self.runSubcase("configureAndEnableVhostmd", (), "vhostmd",
                           "ConfigureAndEnable") != xenrt.RESULT_PASS:
            return
        # Ensure that the service does restart after reboot:
        self.host.reboot()
        self.guest.setState("UP")
        # Check that vhostmd does update its metrics file regularly.
        if self.runSubcase("watchForRefreshing", (3), "vhostmd",
                           "watchForRefreshing") != xenrt.RESULT_PASS:
            return
        # Check that the metrics available in the guest seem plausible.
        if self.runSubcase("gatherAndVerify", (), "vhostmd",
                           "GatherAndVerifyVhostmdData") != xenrt.RESULT_PASS:
            return
        # Even if the performance impact is too much, we can continue.
        self.runSubcase("performanceImpact", (), "vhostmd", "CheckPerformanceImpact")
        # Make sure we can turn it off again.
        if self.runSubcase("disableService", (), "vhostmd",
                           "Disable") != xenrt.RESULT_PASS:
            return
        # Having been disabled, it should not restart after reboot.
        self.host.reboot()
        self.guest.setState("UP")
        # Now check that we are back to the fresh state.
        self.runSubcase("checkNewInstallation", (), "vhostmd", "DisabledAgain")
        # And a last little extra bit, regardless of whether that passed:
        if 0 == self.guest.execguest("/root/vmDumpMetrics.sh", retval="code"):
            raise xenrt.XRTFailure("Tried to disable metrics but can still read them in guest.")

    def performanceImpact(self):

        # String is formatted like hours:minutes:seconds but might lack parts.
        def strToSeconds(hmsStr):
            hmsList = hmsStr.split(":")
            secs = int(hmsList[-1])
            if len(hmsList) > 1:
                secs += 60 * int(hmsList[-2])
                if len(hmsList) > 2:
                    secs += 3600 * int(hmsList[-3])
            return float(secs)

        rawStr = self.host.execdom0("ps --no-headers S -C vhostmd -o etime,time,pcpu,rss,vsz")
        strList = rawStr.split()
        # Use etime and time to calculate %cpu with better precision than the
        # pcpu from the ps command.
        percentCpu = 100.0 * strToSeconds(strList[1]) / strToSeconds(strList[0])
        rss = int(strList[3])
        vsz = int(strList[4])
        err = ""
        if percentCpu >= 0.1:
            err += " cpu"
        if rss >= 2000:
            err += " rss"
        #commenting check for VSZ as it doesn't give measure of memory demand made by process
        #if vsz >= 5000:
        #    err += " vsz"
        if "" != err:
            outList = [strList[0], strList[1], percentCpu, rss, vsz]
            raise xenrt.XRTFailure("Excessive performance impact on" + err,
                                   data = "[Elapsed-time, cpu-time, %%cpu, rss, vsz] are %s." % outList)

    def disableService(self):
        self.host.execdom0("xe-vhostmd disable")
        # Quick check that the metrics vbd is longer available in the guest...
        if 0 == self.guest.execguest("/root/vmDumpMetrics.sh", retval="code"):
            raise xenrt.XRTFailure("Tried to disable metrics but can still read them in guest.")
    

    def watchForRefreshing(self, count):
        for n in range(count):
            # Find the age in seconds of the metrics file.
            [metricsTime, hostNow] = self.host.execdom0(
                "date +%s -r /dev/shm/vhostmd0 && date +%s").split()
            age = int(hostNow) - int(metricsTime)
            timeUntilScheduledRefresh = (UPDATE_PERIOD - age)
            sleepDuration = (UPDATE_PERIOD/2 + timeUntilScheduledRefresh)
            time.sleep(sleepDuration)
            [metricsTime, hostNow] = self.host.execdom0(
                "date +%s -r /dev/shm/vhostmd0 && date +%s").split()
            age2 = int(hostNow) - int(metricsTime)
            # Allow an error-margin.
            if abs(UPDATE_PERIOD/2 - age2) > (UPDATE_PERIOD/10):
                raise xenrt.XRTFailure(
                    "Vhostmd data not updating correctly. Should update every "
                    "%d s. It was %d s old, then after %d s it was %d s old." %
                    (UPDATE_PERIOD, age, sleepDuration, age2))

    # Important to run watchForRefreshing immediately before this.
    def gatherAndVerify(self):
        xmlStr = self.guest.execguest("/root/vmDumpMetrics.sh")
        dataDate = int(self.host.execdom0("date +%s -r /dev/shm/vhostmd0"))
        xenrt.TEC().logverbose(
            "Metrics read from guest (host timestamp %d):\n%s" %
            (dataDate, xmlStr))
        
        # It is practical to handle dataDate and dom0cpuCount explicitly this
        # way, but if we were to end up needing more then we should fetch
        # /etc/vhostmd.conf from dom0 and parse it in much the same way as we
        # handle the xml metrics, then run its <action>s in parallel using a
        # load of threads each running self.host.execdom0(action) and adding
        # the results into the conf document object model data-structure. That
        # DOM can then be passed to handleVmMetric and handleHostMetric so that
        # they can make comparisons where appropriate, but still doing the
        # sanity-checks rather than just checking potentially bad data from the
        # metrics xml against the same data obtained by running the same
        # commands via execdom0.
        dom0cpuCount = int(self.host.execdom0("list_domains -all -domid 0 | tail -1 | cut -d'|' -f10 | tr -c -d '[:digit:]'"))
        d = xml.dom.minidom.parseString(xmlStr)
        if not areTextNodesBlank(d.documentElement):
            raise xenrt.XRTFailure("Expected metric-elements and whitespace; found non-blank text.")

        if not ([] == [n for n in d.documentElement.childNodes
                       if not (n.nodeType == xml.dom.Node.TEXT_NODE or
                               (n.nodeType == xml.dom.Node.ELEMENT_NODE
                                and n.tagName == "metric"))]):
            raise xenrt.XRTFailure("Expected metric elements; found something else.")

        if not ([n for n in d.documentElement.childNodes
                 if n.nodeType != xml.dom.Node.TEXT_NODE] ==
                d.documentElement.getElementsByTagName("metric")):
            raise xenrt.XRTFailure('XML contains a "metric" element at unexpected depth.')

        metricNodes = d.documentElement.getElementsByTagName("metric")
        if not metricNodes.length == 21:
            raise xenrt.XRTFailure('XML should contain exactly 21 metric elements; got %d' % metricNodes.length)

        for metricNode in metricNodes:
            if not areTextNodesBlank(metricNode):
                raise xenrt.XRTFailure("Found a metric element with non-blank text.")
            childCount = len([n for n in metricNode.childNodes if n.nodeType != xml.dom.Node.TEXT_NODE])
            if 2 != childCount:
                raise xenrt.XRTFailure("Found metric element with %d non-text children: should be 2." % childCount)
            context = metricNode.getAttribute("context")
            attributeCount = len(metricNode.attributes.items())
            if "host" == context:
                if 2 != attributeCount:
                    raise xenrt.XRTFailure("Found host metric with %d attributes: should be 2." % attributeCount)
                handleHostMetric(metricNode, dataDate)
            elif "vm" == context:
                if 4 != attributeCount:
                    raise xenrt.XRTFailure("Found VM metric with %d attributes: should be 4." % attributeCount)
                handleVmMetric(metricNode, dom0cpuCount)
            else:
                raise xenrt.XRTFailure("Metric context should be host or vm; found %s." % context)

    def configureAndEnableVhostmd(self):
        startText = self.host.execdom0("xe-vhostmd enable", timeout=123)
        # Now check it worked as expected: this file should exist.
        self.host.execdom0("[ -e /dev/shm/vhostmd0 ]")
        # Now pick the UUIDs out of the text we got.
        self.srUuid = re.findall('Created metrics SR.*', startText)[0].split()[-1]
        self.vdiUuid = re.findall('associated VDI.*', startText)[0].split()[-1]
        self.vbdUuid = self.host.execdom0(
            "xe vbd-create vm-uuid=%s vdi-uuid=%s device=12 mode=RO" %
            (self.host.getGuestUUID(self.guest), self.vdiUuid)).strip()
        self.host.execdom0("xe vbd-plug uuid=%s" % self.vbdUuid)
        # Also install a testing-tool into the guest:
        self.guest.execguest("echo '%s' > /root/vmDumpMetrics.sh" %
                             re.sub("'", "'\\''", VM_DUMP_METRICS_SCRIPT),
                             newlineok=True)
        self.guest.execguest("chmod 777 /root/vmDumpMetrics.sh")
        # And check that metrics (however bad) are available:
        self.guest.execguest("/root/vmDumpMetrics.sh")

    def checkNewInstallation(self):
        status = self.host.execdom0("service vhostmd status || true")
        if not re.search("stopped$", status.strip()) and not "inactive" in status:
            raise xenrt.XRTFailure(
                "vhostmd should be stopped in new installation, but was: %s" % status)
        if 0 == self.host.execdom0("[ -e /dev/shm/vhostmd0 ]", retval="code"):
            raise xenrt.XRTFailure("/dev/shm/vhostmd0 should not exist but does.")
        if 0 == self.host.execdom0("[ -e /opt/xensource/sm/SHMSR ]", retval="code"):
            raise xenrt.XRTFailure("/opt/xensource/sm/SHMSR should not exist but does.")


VM_DUMP_METRICS_SCRIPT = r"""#!/bin/bash

# This script does essentially the same as the vm-dump-metrics binary,
# except it looks for metrics in the devices at /dev/xvd? rather than
# trying all items in /dev that have matching names in /sys/block.
# Also it has a time-out rather than retrying for ever.
# 
# Usually it runs in about a tenth of a second of elapsed time.
# 
# Like the binary version, it reads the metrics in O_DIRECT mode
# and ensures it gets a clean set of metrics, not part-updated.


tmpd=`mktemp -d`
thd="${tmpd}"/vdhumpheader
fourZero="${tmpd}"/fourZero
echo -en '\0\0\0\0' > "${fourZero}"

function attemptVmDump {
    # metrics disc
	local md="${1}"
	# Check the header busy-marker (second four bytes) is all zero:
	# return failure if not.
	head -c8 "${thd}" | tail -c4 | diff -q "${fourZero}" - > /dev/null \
		|| return 1
	# The 13th to 16th bytes of the header tell the length of the body,
	# with most significant byte first.
	dumpLength=$(tail -c+13 "${thd}" | od -t u1 | head -1 | \
		awk '{print (16777216 * $2) + (65536 * $3) + (256 * $4) + $5}'
	)
	# Check we have a somewhat plausible value for the size of the metrics xml
	[[ dumpLength -gt 18 ]] || return 2
	# Read the fake disc, using O_DIRECT to ignore the operating sytem cache.
	local ham="${tmpd}/headerAndMetrics"
	rm -f "${ham}"
	dd if="${md}" iflag=direct 2>/dev/null | \
		head -c$((16+dumpLength)) > "${ham}"
	# Check the header (including checksum in third four bytes) has not
	# changed since last we looked...
	head -c16 "${ham}" | diff -q "${thd}" - > /dev/null || return 3
	# Check there was as much data as expected.
	[[ $((16+dumpLength)) == `wc -c < "${ham}"` ]] || return 4
	# At last, dump the metrics xml (without the header) to stdout.
	tail -c+17 "${ham}"
}

# Initially set the return/exit value to a failure code.
retVal=10

for d in /dev/xvd? ; do
	rm -f "${thd}"
	# Attempt to read a header-sized chunk, using O_DIRECT to ignore the cache.
	dd if="${d}" iflag=direct count=1 2>/dev/null | head -c16 > "${thd}"
	# Did we manage to read sixteen bytes?
	[[ '16' == `wc -c < "${thd}"` ]] || continue
	# Does it start with the marker that indicates vhostmd metrics?
	[[ 'mvbd' == `head -c4 "${thd}"` ]] || continue

	# If we get to here, we assume we have found the right device.
	for (( triesLeft=15; triesLeft--; )); do
		attemptVmDump "${d}"
		retVal=$?
		if [[ '0' == $retVal ]]; then
			# Break out of both loops.
			break 2
		elif [[ $triesLeft -gt 0 ]]; then
			sleep 1
		fi
	done
	# Ran out of tries: failed to dump the metrics from the chosen file.
done

rm -rf "${tmpd}"
[[ $retVal == 0 ]] || echo 1>&2 'Failed to read the metrics.'
exit $retVal
"""
