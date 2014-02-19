#!/usr/bin/python

import XenAPI
import xenrt
import testcases.xenserver.tc.perf.libperf as libperf
import time
import random
import sys

from testcases.xenserver.tc.perf.libperf import curry

class TCVlanScalability (libperf.PerfTestCase):
    def __init__ (self):
        libperf.PerfTestCase.__init__ (self, self.__class__.__name__)
        self.remoteRun = libperf.RemoteRunner().remoteRun
    def prepare (self, arglist):
        self.parseArgs (arglist)
        get = curry (libperf.getArgument, arglist)

        #lower = get ("lowest_number_of_vlans", int, 0)
        ## Pythonic intervals are right-open:
        #upper = get ("highest_number_of_vlans", int, 128)+1
        #samples = get ("vlans_samples", int, 32)
        #self.samplePoints = [random.randrange (lower, upper) for _ in range(samples)]

        num = get("numvlans", int, 64)
        self.samplePoints = [num]

        self.initialiseHostList()
        self.configureAllHosts()

        self.master = self.getMaster ()

    def restartXapi (self):
        # TODO: get rid of the need to ssh into the host to learn if
        # the poller's results.  Let the poller phone home on a
        # high-numbered port.  (Choose different ports, if we need to
        # distinguish different machines / uses.)
        #
        # Why?  Because we too often get problems with ssh.  Like
        # error: (113, 'No route to host')

        t = 10 #seconds
        poll_log = "/tmp/polling_log"
        # restart xapi in t seconds from now:
        when = time.time() + t
        # but first, start our script to time how long it takes xapi
        # to come back and the hosts to be enabled again.
        poller_pid = self.remoteRun(self.master,
                                    scripts['poller_xapi_restart'], output = poll_log,
                                    background=True).strip ()
        # now hurry up, and schedule the xap restarts:
        for host in map (self.tec.gec.registry.hostGet, self.normalHosts):
            self.remoteRun(host, scripts['at'],
                           when,
                           "service xapi restart", background=True)
        try:
            # loop until the poller has died:
            while True:
                # Meta-polling for the death of the poller.  This does
                # not impact the precision of the measurement.
                time.sleep (10)
                fuser = self.master.execdom0('fuser %s || true ' % poll_log).strip()
                xenrt.TEC().logverbose("vlan_scalability: fuser %s ? poller_pid %s"
                                       % (repr(fuser), repr(poller_pid)))
                if poller_pid not in fuser:
                    s = self.master.execdom0('cat %s' % poll_log).strip()
                    xenrt.TEC().logverbose("vlan_scalability: polling gave %s, id %s"
                                           % (repr(s), repr(fuser)))
                    try:
                        return float(s)
                    except ValueError:
                        c,e,s = sys.exc_info
                        if str(e) == "empty string for float()":
                            raise c, ValueError ("poller_xapi_restart wrote an empty string,"
                                                 "instead of a float."), s
                        else:
                            raise

        # `except' might be good enough here, but `finally' is easier
        # to maintain, if we should ever return for a different reason
        # than the death of the poller.
        finally:
            # kill poller in case we get killed
            self.master.execdom0("kill %s || true" % poller_pid)

    def run (self, arglist=[]):
        def timeIt(f):
            before = time.time()
            f ()
            return time.time() - before

        xenrt.TEC().logverbose("BEFORE")
        xenrt.TEC().logverbose(self.host.execdom0("xe vlan-list"))

        # destroy all vlans that might have been there from previous runs:
        self.remoteRun (self.master,
                        scripts['destroy_vlans'],
                        timeout=3600)

        xenrt.TEC().logverbose("AFTER FIRST DESTROY")
        xenrt.TEC().logverbose(self.host.execdom0("xe vlan-list"))

        def getData (samplePoints):
            xenrt.TEC().logverbose("In getData. samplePoints = %s" % samplePoints)
            # only for debugging
            from os import popen
            xenrt.TEC().logverbose("vlan_scalability: pwd %s"
                                   % popen("pwd").read().strip())
            for i in samplePoints:
                xenrt.TEC().logverbose("BEFORE CREATE VLANS")
                xenrt.TEC().logverbose(self.host.execdom0("xe vlan-list"))

                create_vlans_time = str(timeIt (curry (
                            self.remoteRun,
                            self.master,
                            scripts['create_vlans'], 1, i,
                            timeout=3600)))

                xenrt.TEC().logverbose("BEFORE RESTART XAPI")
                xenrt.TEC().logverbose(self.host.execdom0("xe vlan-list"))

                restart_xapi_time = self.restartXapi ()

                xenrt.TEC().logverbose("AFTER RESTART XAPI")
                xenrt.TEC().logverbose(self.host.execdom0("xe vlan-list"))

                destroy_vlans_time = str(timeIt (curry(
                            self.remoteRun,
                            self.master,
                            scripts['destroy_vlans'],
                            timeout=3600)))

                xenrt.TEC().logverbose("AFTER DESTROY VLANS")
                xenrt.TEC().logverbose(self.host.execdom0("xe vlan-list"))

                yield (i, restart_xapi_time, len(self.normalHosts), create_vlans_time, destroy_vlans_time)

        filename = "vlanScalability-xapi-restart"
        self.log (filename, "#vlans restart_time pool_size create_vlans_time destroy_vlans_time")

        # try..except here is only useful for debug-runs with xrt.
        try:
            for sample in getData (self.samplePoints):
                self.log (filename, " ".join(map(str, sample)))
        except KeyboardInterrupt, e:
            pass
