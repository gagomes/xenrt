#
# XenRT: Test harness for Xen and the XenServer product family
#
# Performance tests
#
# Copyright (c) 2009 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and conditions
# as licensed by Citrix Systems, Inc. All other rights reserved.
#

import string, time, re, copy, threading, sys, traceback
import xenrt

class _VMInstall(xenrt.XRTThread):

    def __init__(self, host, distro, vcpus, memory, index):
        self.host = host
        self.distro = distro
        self.vcpus = vcpus
        self.memory = memory
        self.guest = None
        self.exception = None
        self.starttime = None
        self.index = index
        xenrt.XRTThread.__init__(self)

    def run(self):
        try:
            self.starttime = xenrt.timenow()
            self.guest = xenrt.lib.xenserver.guest.createVM(\
                self.host,
                xenrt.randomGuestName(),
                self.distro,
                memory=self.memory,
                vcpus=self.vcpus,
                vifs=xenrt.lib.xenserver.Guest.DEFAULT)
            #self.guest.installDrivers()
        except Exception, e:
            xenrt.TEC().logverbose("Exception while performing a VM install")
            traceback.print_exc(file=sys.stderr)
            self.exception = e

class _TCParallelOSInstallPerf(xenrt.TestCase):
    """Compare the speed of VM OS install in parallel to alone"""

    # How much more time is acceptable for a VM installed in parallel with
    # another compared to installing alone. 100% implies double is OK
    ALLOWED_DURATION_INCREASE_PERCENT = 120
    DISTROS = []
    VCPUS = []
    MEMORY = []

    def prepare(self, arglist=[]):
        self.host = self.getDefaultHost()
        self.starttimes = {}
        self.endtimes = {}

    def installSerial(self, index):
        starttime = xenrt.timenow()
        guest = xenrt.lib.xenserver.guest.createVM(\
            self.host,
            xenrt.randomGuestName(),
            self.DISTROS[index],
            memory=self.MEMORY[index],
            vcpus=self.VCPUS[index],
            vifs=xenrt.lib.xenserver.Guest.DEFAULT)
        #guest.installDrivers()
        self.starttimes["SERIAL%u" % (index)] = starttime
        self.endtimes["SERIAL%u" % (index)] = \
            guest.xmlrpcFileMTime("c:\\alldone.txt")
        # Uninstall now to conserve disk space
        guest.shutdown()
        guest.uninstall()

    def installParallel(self):
        workers = []
        for i in range(len(self.DISTROS)):
            w = _VMInstall(self.host,
                           self.DISTROS[i],
                           self.VCPUS[i],
                           self.MEMORY[i],
                           i)
            workers.append(w)
        for w in workers:
            w.start()
        for w in workers:
            w.join()
            if w.exception:
                raise w.exception
            self.uninstallOnCleanup(w.guest)
            self.starttimes["PARALLEL%u" % (w.index)] = w.starttime
            self.endtimes["PARALLEL%u" % (w.index)] = \
                w.guest.xmlrpcFileMTime("c:\\alldone.txt")

    def compare(self):
        errors = 0
        for i in range(len(self.DISTROS)):
            sstarts = self.starttimes["SERIAL%u" % (i)]
            sends = self.endtimes["SERIAL%u" % (i)]
            sduration = sends - sstarts
            pstarts = self.starttimes["PARALLEL%u" % (i)]
            pends = self.endtimes["PARALLEL%u" % (i)]
            pduration = pends - pstarts

            xenrt.TEC().comment("OS %s %u VCPUS %uMB install time: "
                                "Alone: %umins, Parallel: %umins" %
                                (self.DISTROS[i],
                                 self.VCPUS[i],
                                 self.MEMORY[i],
                                 int(sduration/60),
                                 int(pduration/60)))

            pallowed = int(float(sduration) *
                           (100.0 + self.ALLOWED_DURATION_INCREASE_PERCENT)/
                           100.0)
            if pduration > pallowed:
                errors = errors + 1
        if errors:
            raise xenrt.XRTFailure("VM(s) install in parallel with another "
                                   "install took much longer than installing "
                                   "alone",
                                   "%u/%u VMs slow" %
                                   (errors/len(self.DISTROS)))

    def run(self, arglist=[]):

        # Install each VM on its own
        for i in range(len(self.DISTROS)):
            if self.runSubcase("installSerial",
                               (i),
                               "Install",
                               "Serial%u" % (i)) \
                    != xenrt.RESULT_PASS:
                return

        # Install both VMs together (approximately)
        if self.runSubcase("installParallel", (), "Install", "Parallel") \
                != xenrt.RESULT_PASS:
            return

        # Compare the times from starting the XenRT install process to
        # alldone.txt being written
        self.runSubcase("compare", (), "Install", "Perf")

class TCxxxx(_TCParallelOSInstallPerf):

    DISTROS = ["vistaeesp1", "vistaeesp1-x64"]
    VCPUS = [1, 1]
    MEMORY = [1024, 1024]

