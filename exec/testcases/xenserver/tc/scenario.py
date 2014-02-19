#
# XenRT: Test harness for Xen and the XenServer product family
#
# Tests of potential customer scenarios
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, shutil, os.path, stat, re, os, time, urllib, glob
import traceback, random, copy
import xenrt, xenrt.lib.xenserver

class TC7330(xenrt.TestCase):
    """Small cluster, moderate VM count, low load"""

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        # Default duration in minutes
        self.duration = 10080 # = 7 days
        # Default health check frequency in minutes
        self.frequency = 60 # = 1 hour
        # Workload(s) to run on the guests (only one will be run per guest)
        self.workloads = ["FastPing","Dummy","Dummy","DiskFind","Dummy"]

        self.pool = None
        self.hosts = []
        self.guests = {}
        self.guestWorkloads = {}
        self.templateGuest = None

    def prepare(self, arglist):
        # Get the pool object
        self.pool = self.getDefaultPool()
        self.hosts.append(self.pool.master)
        for slave in self.pool.slaves.values():
            self.hosts.append(slave)

        # Create a Windows VM to clone
        # 384MB means we should *just* fit on an 8GB host
        self.templateGuest = self.hosts[0].createGenericWindowsGuest(memory=384)
        self.uninstallOnCleanup(self.templateGuest)
        self.templateGuest.preCloneTailor()
        self.templateGuest.shutdown()

    def run(self, arglist):
        # Check if we've got an argument with a new length or check frequency
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "duration":
                self.duration = int(l[1])
            elif l[0] == "frequency":
                self.frequency = int(l[1])

        self.declareTestcase("Preparation","CloneVMs")
        self.declareTestcase("Preparation","StartVMs")
        self.declareTestcase("Preparation","StartWorkloads")
        self.declareTestcase("Run","MonitorHealth")
        self.declareTestcase("Cleanup","StopWorkloads")

        self.runSubcase("cloneVMs",(),"Preparation","CloneVMs")

        self.runSubcase("startVMs",(),"Preparation","StartVMs")

        self.runSubcase("startWorkloads",(self.workloads),"Preparation","StartWorkloads")

        self.runSubcase("monitorHealth",(self.frequency,self.duration),"Run",
                        "MonitorHealth") 

        self.runSubcase("stopWorkloads",(),"Cleanup","StopWorkloads")

    def cloneVMs(self):
        # Clone 20 VMs per host
        for host in self.hosts:
            guests = []
            for i in range(20):
                g = self.templateGuest.cloneVM()
                self.uninstallOnCleanup(g)
                guests.append(g)
            self.guests[host.getName()] = guests

    def startVMs(self):
        # Start the VMs per host
        for host in self.hosts:
            guests = self.guests[host.getName()]
            for g in guests:
                g.start()

    def startWorkloads(self, workloads):
        # Start one workload per VM (iterate round which ones to start)
        wl = 0
        for host in self.hosts:
            guests = self.guests[host.getName()]
            for g in guests:
                self.guestWorkloads[g.getUUID()] = g.startWorkloads(workloads=[workloads[wl]])
                wl += 1
                if wl == len(workloads):
                    wl = 0

    def monitorHealth(self,frequency,duration):
        # Monitor all VMs and hosts for health for the specified duration (in
        # minutes), checking at the specified frequency (in minutes)
        started = xenrt.timenow()
        while True:
            if xenrt.timenow() > (started + (duration * 60)):
                break
            for host in self.hosts:
                host.checkHealth()
                for guest in self.guests[host.getName()]:
                    guest.checkHealth()
            time.sleep(frequency*60)

    def stopWorkloads(self):
        for guests in self.guests.values():
            for g in guests:
                if g.getUUID() in self.guestWorkloads.keys():
                    g.stopWorkloads(workloads=self.guestWorkloads[g.getUUID()])
                else:
                    xenrt.TEC().warning("Couldn't find workloads for guest %s" %
                                        (g.getName()))

