#
# XenRT: Test harness for Xen and the XenServer product family
#
# API testcases
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy
import xenrt, xenrt.lib.xenserver

class TC8236(xenrt.TestCase):
    """Miami-style metrics on a post-Miami host"""
    
    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        # Start a compute workload in dom0 so we have something to measure
        self.host.execdom0("dd if=/dev/zero count=1000000000 2>&1 < /dev/null "
                           "| md5sum > /dev/null 2>&1 &")
        #time.sleep(60)

    def checkCPUMetrics(self, zero):
        session = self.host.getAPISession()
        xapi = session.xenapi
        try:
            hostref = xapi.host.get_all()[0]
            host = xapi.host.get_record(hostref)
            cpus = host['host_CPUs']
            utilisation = 0.0
            for cpu in cpus:
                cpu_info = xapi.host_cpu.get_record(cpu)
                xenrt.TEC().logverbose("CPU %s utilisation %s" %
                                       (str(cpu_info['number']),
                                        str(cpu_info['utilisation'])))
                util = float(cpu_info['utilisation'])
                utilisation = utilisation + util
        finally:
            self.host.logoutAPISession(session)
        if zero:
            if utilisation > 0.0:
                raise xenrt.XRTFailure("CPU utilisation metrics non-zero")
        else:
            if utilisation == 0.0:
                raise xenrt.XRTFailure("CPU utilisation metrics zero")

    def run(self, arglist=None):
        # Check the existing configuration does not return valid metrics
        self.runSubcase("checkCPUMetrics", (True), "Disabled", "CPU")

        # Enable Miami-style metrics with a 60 second poll period
        self.host.setHostParam("other-config:rrd_update_interval", "2")
        self.host.restartToolstack()
        time.sleep(60)

        # Check the CPU metrics are now non-zero
        self.runSubcase("checkCPUMetrics", (False), "Enabled", "CPU")

    def postRun(self):
        # Stop the dom0 compute workload
        try:
            self.host.execdom0("killall -9 dd")
        except:
            pass
        self.host.removeHostParam("other-config", "rrd_update_interval")
        self.host.restartToolstack()
