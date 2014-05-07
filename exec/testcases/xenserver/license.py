#
# XenRT: Test harness for Xen and the XenServer product family
#
# XenServer licensing test cases
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import string, re, time
import xenrt, xenrt.lib.xenserver, xenrt.lib.xenserver.cli

class TCLicense(xenrt.TestCase):
    """Apply a license to a host"""
    
    def __init__(self):
        xenrt.TestCase.__init__(self, "TCLicense")

    def run(self, arglist=None):

        machine = "RESOURCE_HOST_0"
        sku = None
        if arglist:
            for arg in arglist:
                l = string.split(arg, "=")
                if l[0] == "machine":
                    machine = l[1]
                elif l[0] == "sku":
                    sku = l[1]
                else:
                    raise xenrt.XRTError("Invalid argument to testcase")

        host = xenrt.TEC().registry.hostGet(machine)

        if sku:
            host.license(sku=sku)
        else:
            host.license()

class TCLicenseExpiry(xenrt.TestCase):
    """Check that the product acts as expected at license expiry"""

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCLicenseExpiry")
        self.guestsToClean = []
        self.host = None

    def run(self, arglist=None):

        machine = None
        if not arglist or len(arglist) == 0:
            machine = "RESOURCE_HOST_0"
        else:
            l = string.split(arglist[0], "=")
            if len(l) == 1:
                machine = l[0]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)
        self.host = host

        try:            
            # Set up three guests
            guest = self.host.createGenericLinuxGuest()
            self.guestsToClean.append(guest)
            guest.preCloneTailor()
            guest.shutdown()
            guest.memset(128)

            self.guestsToClean.append(guest.cloneVM())
            self.guestsToClean.append(guest.cloneVM())

            # Start two of them
            self.guestsToClean[0].start()
            self.guestsToClean[1].start()

            # Generate a license that expires in 2 days time
            host.license(expirein=2)

            # Manipulate dom0 clock such that it's 3 days later
            host.execdom0("/etc/init.d/ntpd stop")
            gmtime = time.gmtime(time.time() + (3600*24*3))
            host.execdom0("date -u %s" % (time.strftime("%m%d%H%M%Y",gmtime)))
        except xenrt.XRTFailure, e:
            # This isn't a failure of the testcase
            raise xenrt.XRTError(e)

        # Attempt to clone a new guest
        allowed = True
        try:
            newguest = guest.cloneVM()
            self.guestsToClean.append(newguest)
        except xenrt.XRTFailure, e:
            allowed = False
            xenrt.TEC().comment("Expected XRTFailure while attempting to clone new VM")
        if allowed:
            raise xenrt.XRTFailure("Allowed to clone a guest with expired license!")

        # Attempt to start the third guest
        allowed = True
        try:
            self.guestsToClean[2].start()
        except xenrt.XRTFailure, e:
            allowed = False
            xenrt.TEC().comment("Expected XRTFailure while attempting to start VM")
        if allowed:
            raise xenrt.XRTFailure("Allowed to start a guest with expired license!")

        # Stop the second guest, and attempt to start it again
        self.guestsToClean[1].shutdown()
        allowed = True
        try:
            self.guestsToClean[1].start()
        except xenrt.XRTFailure, e:
            allowed = False
            xenrt.TEC().comment("Expected XRTFailure while attempting to start VM")
        if allowed:
            raise xenrt.XRTFailure("Allowed to start a guest with expired license!")

        # Attempt to reboot the first guest
        allowed = True
        try:
            self.guestsToClean[1].reboot()
        except xenrt.XRTFailure, e:
            allowed = False
            xenrt.TEC().comment("Expected XRTFailure while attempting to reboot VM")
        if allowed:
            raise xenrt.XRTFailure("Allowed to reboot a guest with expired license!")

    def postRun(self):
        try:
            # Fix dom0 clock (starting ntpd runs ntpdate first, so works for us)
            self.host.execdom0("/etc/init.d/ntpd start")
        except:
            xenrt.TEC().warning("Exception while fixing dom0 clock!")

        try:
            # Apply a normal license again
            self.host.license()
        except:
            xenrt.TEC().warning("Exception while applying normal license!")

        # Cleanup guests
        for g in self.guestsToClean:
            try:
                g.shutdown(force=True)
            except:
                pass
            try:
                g.poll("DOWN", 120, level=xenrt.RC_ERROR)
                g.uninstall()
                time.sleep(15)
            except:
                pass

class TCLicenseRestrictions(xenrt.TestCase):
    """Check that a license has the correct restrictions"""

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCLicenseRestrictions")
        # Not currently testing sharedSRs or pooling
        self.tests = ["concurrentVMs","maxMemGiB","vlans","qos"]
        self.guestsToShutdown = []
        self.bridge = None
        self.skutype = ""

    def run(self, arglist=None):

        machine = None
        if not arglist or len(arglist) == 0:
            machine = "RESOURCE_HOST_0"
        else:
            l = string.split(arglist[0], "=")
            if len(l) == 1:
                machine = l[0]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)
        self.host = host

        # Set up the template VM that we will clone (saves time by not having
        # to install for each test!)
        self.guestToClone = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guestToClone)
        self.guestToClone.preCloneTailor()
        self.guestToClone.shutdown()

        # Run a test against a sku by specifying a set of restrictions as a
        # dictionary, and then calling runTests with the SKU and the dictionary

        express = {'concurrentVMs': 0, 'maxMemGiB': 0, 'vlans': False,
                   'qos': False, 'sharedSRs': False, 'pooling': False}
        self.runTests("XE Express", express)

        server = {'concurrentVMs': 0, 'maxMemGiB': 0, 'vlans': True,
                  'qos': False, 'sharedSRs': True, 'pooling': False}
        self.runTests("XE Server", server)

        # Note: Number of concurrentVMs to test at for the unlimited case is 
        # defined in the concurrentVMs subcase.
        enterprise = {'concurrentVMs': 0, 'maxMemGiB': 0, 'vlans': True, 
                      'qos': True, 'sharedSRs': True, 'pooling': True}
        self.runTests("XE Enterprise", enterprise)


    def runTests(self, sku, restrictions):
        self.skutype = sku.replace("XE ","")
        self.host.license(sku=sku)
        for test in self.tests:
            if restrictions.has_key(test):
                result = self.runSubcase(test, (restrictions[test]), sku, test)
                if result == xenrt.RESULT_SKIPPED:
                    # If we skip any subcases, we can't call it a complete pass
                    self.setResult(xenrt.RESULT_PARTIAL)
                self.scCleanup()
            else:
                xenrt.TEC().comment("Not running %s test for %s, as no "
                                    "restriction defined" % (test,sku))

    def scCleanup(self):
        # Shutdown and uninstall any VMs
        for g in self.guestsToShutdown:
            try:
                g.shutdown(force=True)
            except:
                pass

        self.guestsToShutdown = []

    def concurrentVMs(self, restriction):
        if restriction == 0:
            # Unlimited, test at 9
            unlimited = True
            restriction = 9
        else:
            unlimited = False

        # Find out how many VMs are running already (listDomains returns dom0
        # as well so subtract 1)
        current = len(self.host.listDomains()) - 1
        if current > restriction:
            raise xenrt.XRTError("Host already has %d VMs running, restriction "
                                 "is %d VMs!" % (current,restriction))

        # tocreate is the number of guests we should be allowed to launch
        tocreate = restriction - current

        # Check we have enough memory on the host
        if (self.host.getFreeMemory()/128 < tocreate):
            raise xenrt.XRTSkip("Not enough memory on host to test %d VMs" % 
                                 (restriction))

        guests = []

        # First guest
        try:
            guests.append(self.guestToClone.cloneVM(name="concurrentVMs"))
            self.guestsToShutdown.append(guests[0])
            self.uninstallOnCleanup(guests[0])
            guests[0].memset(128)
        except xenrt.XRTException, e:
            # Failures here are not a failure of the testcase
            raise xenrt.XRTError("Exception while installing VM: %s" % (str(e)))

        # Clone it tocreate number of times (i.e. we end up with an extra guest)
        try:
            for i in range(tocreate):
                g = guests[0].cloneVM()
                guests.append(g)
                self.guestsToShutdown.append(g)
                self.uninstallOnCleanup(g)
        except xenrt.XRTException, e:
            # Failures here are not a failure of the testcase
            raise xenrt.XRTError("Exception while cloning VM: %s" % (str(e)))

        # Start tocreate of the guests (this should work)
        try:
            for i in range(tocreate):
                guests[i].lifecycleOperation("vm-start")
        except xenrt.XRTException, e:
            raise xenrt.XRTFailure("Exception while starting VM: %s" % (str(e)))

        if not unlimited:
            # Now try and start the final one (this should error)
            allowed = True
            try:
                guests[tocreate].lifecycleOperation("vm-start")
            except xenrt.XRTException, e:
                allowed = False
            
            if allowed:
                raise xenrt.XRTFailure("vm-start succeeded for guest %d with "
                                       "restriction of %d" % 
                                       (tocreate+current+1,restriction))

        # In this test, uninstall all guests
        for g in self.guestsToShutdown:
            try:
                g.shutdown(force=True)
            except:
                pass
            g.uninstall()
        self.guestsToShutdown = []
            
    def maxMemGiB(self, restriction):
        # Convert to MB
        restMB = restriction * 1024

        # Check we have enough memory to check this restriction (+32MB as we
        # need to test above it as well)
        if self.host.getFreeMemory() < (restMB+32):
            raise xenrt.XRTSkip("Host does not have enough memory to test a "
                                 "restriction of %d GiB" % (restriction))

        # Create a guest that uses the exact limit of memory (if there is one)
        guest = self.guestToClone.cloneVM(name="maxMemGiB")
        self.guestsToShutdown.append(guest)
        self.uninstallOnCleanup(guest)
        if restriction > 0:
            guest.memset(restMB)

            try:
                guest.start()
            except xenrt.XRTException, e:
                raise xenrt.XRTFailure("Exception while starting VM using %d "
                                       "MB: %s" % (restMB,str(e)))

            guest.shutdown()

        # Now try using all the memory the host has (this is useful for testing
        # XE Enterprise)
        # Wait just over a minute to let the free memory recalculate
        time.sleep(75)
        mem = self.host.getFreeMemory()
        self.host.execdom0("/opt/xensource/debug/xenops physinfo") # CA-26342
        guest.memset(mem)

        if restriction > 0:
            allowed = True
            try:
                guest.start()
            except xenrt.XRTException, e:
                allowed = False
    
            if allowed:
                raise xenrt.XRTFailure("Allowed to start VM using %d MB of "
                                       "memory with a restriction of %d GB" %
                                       (mem,restriction))
        else:
            try:
                guest.start()
            except xenrt.XRTException, e:
                raise xenrt.XRTFailure("Exception while starting VM using %d "
                                       "MB of memory with no restriction" %
                                       (mem))

    def vlans(self, allowed):
        # Create the network if it doesn't exist
        if not self.bridge:
            self.bridge = self.host.createNetwork()
        
        # Now attempt to create the vlan
        vlan = None
        try:
            vlan = self.host.createVLAN(100,self.bridge,"eth0")
        except xenrt.XRTException, e:
            pass

        if vlan:
            try:
                self.host.removeVLAN(100)
            except:
                pass
            if not allowed:
                raise xenrt.XRTFailure("Allowed to create a VLAN when license "
                                       "does not allow creation")
        elif allowed:
            raise xenrt.XRTFailure("Not allowed to create a VLAN when license "
                                   "allows creation!")

    def qos(self, allowed):
        # We can't run this on OEM flash versions, as there's no xensource.log
        try:
            guest = self.guestToClone.cloneVM(name="qos%s" % (self.skutype))
            self.guestsToShutdown.append(guest)
            self.uninstallOnCleanup(guest)
    
            # These should work, regardless...
            guest.setCPUCredit(weight=128,cap=0)
            guest.setVIFRate("eth0",100)
            guest.setDiskQoS("0","rt",5)

            # This should succeed
            guest.start()
        except xenrt.XRTFailure, e:
            raise xenrt.XRTError("Failure while cloning VM and setting credit "
                                 "parameters: " + e.reason)

        # Now look in the log to see if we can find the warnings...
        foundcpu = self.findGuest(["Ignoring CPU QoS params due to license "
                                  "restrictions"],guest)
        foundvif = self.findGuest(["Ignoring QoS on VIFs due to licensing "
                                  "restrictions", "vif QoS failed: Ignoring "
                                  "QoS due to licensing restrictions"],guest)
        foundvbd = self.findGuestVBD(guest)

        if allowed:
            if foundcpu or foundvif or foundvbd:
                raise xenrt.XRTFailure("QoS ignored when license allows it "
                                       "(1=ignored): CPU %u, VIF %u, VBD %u" %
                                       (foundcpu,foundvif,foundvbd))
        else:
            if not (foundcpu and foundvif and foundvbd):
                raise xenrt.XRTFailure("QoS used when license disallows it "
                                       "(0=used): CPU %u, VIF %u, VBD %u" % 
                                       (foundcpu,foundvif,foundvbd))

    def grepLogFiles(self, pattern):
        reply1 = self.host.execdom0("grep '%s' /var/log/xensource.log | cat" %
                                    (pattern))
        reply2 = self.host.execdom0("grep '%s' /var/log/xensource.log.1 | cat" %
                                    (pattern))
        return reply1 + reply2

    # Not a subcase...
    def findGuestVBD(self, guest):
        try:
            data = self.grepLogFiles("vbd qos failed:")
            datal = data.split("\n")
            for l in datal:
                m = re.search("vbd qos failed: license restrictions "
                             "\(vm=(\S+),vbd=(\S+)\)",l)
                if m and m.group(1) == guest.getUUID():
                    return True
            return False
        except xenrt.XRTFailure, e:
            return False

    # Not a subcase...
    def findGuest(self, texts, guest):
        for text in texts:
            try:
                data = self.grepLogFiles(text)
                datal = data.split("\n")
                for l in datal:
                    # Try even newer style
                    m = re.search("\|VM\.start(?:_on)? (\S:\S+)\|",l)
                    if m:
                        tid = m.group(1)
                    else:
                        # Try new style
                        m = re.search("\[task: VM\.start \((\S+)\)",l)
                        if m:
                            tid = m.group(1)
                        else:                    
                            # This line has a task ID, which we need to extract
                            tids = l.split()
                            if len(tids) < 5:
                                continue
                            tid = tids[4]
                            tid = tid[1:]

                    # Now grep for this task ID
                    runon = self.grepLogFiles(tid)
                    # Now extract the domID
                    m = re.search("Adding vif(\d+)\.0 to bridge", runon)
                    if not m:
                        m = re.search("Device.Vif.add domid=(\d+)", runon)
                        if not m:
                            continue
                    domid = m.group(1)
                    if domid == str(guest.getDomid()):
                        return True
            except xenrt.XRTFailure, e:
                # An error in these commands probably means the entry didn't exist
                pass

        return False

    def sharedSRs(self, allowed):
        raise xenrt.XRTError("Not implemented.")

    def pooling(self, allowed):
        raise xenrt.XRTError("Not implemented.")
