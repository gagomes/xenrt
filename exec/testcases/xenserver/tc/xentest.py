#
# XenRT: Test harness for Xen and the XenServer product family
#
# XenTest Unit Tests 
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import re, string, time, traceback, sys 
import xenrt, xenrt.lib.xenserver

class _XenTest(xenrt.TestCase):
    """Test case for Xen unit tests."""

    TEST = ""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.testmac = xenrt.randomMAC()
        self.testguest = self.host.guestFactory()(xenrt.randomGuestName())
        self.testguest.host = self.host
        self.testguest.createGuestFromTemplate("Other install media",
                                                self.host.getLocalSR())
        self.testguest.enablePXE()
        self.testguest.createVIF(mac=self.testmac,
                                 bridge=self.host.getPrimaryBridge())
        sftp = self.host.sftpClient()
        sftp.copyFrom("/usr/lib/syslinux/xentest/%s.c32" % (self.TEST),
                      "%s/%s.c32" % (xenrt.TEC().getWorkdir(), self.TEST))

    def run(self, arglist):
        pxe = xenrt.PXEBoot()
        pxe.copyIn("%s/%s.c32" % (xenrt.TEC().getWorkdir(), self.TEST))
        entry = pxe.addEntry(self.TEST, boot="linux")
        entry.linuxSetKernel("%s.c32" % (self.TEST))
        pxe.setDefault(self.TEST)
        pxe.writeOut(None, forcemac=self.testmac)

        self.testguest.lifecycleOperation("vm-start")
        self.testguest.poll("UP", pollperiod=5)
        domainid = self.testguest.getDomid()
        xenrt.TEC().logverbose("Waiting for test to complete...")
        time.sleep(30) 
        self.testguest.shutdown(force=True)

        results = {}
        data = self.host.execdom0("cat %s/console.%s.log" % 
                                  (xenrt.TEC().lookup("GUEST_CONSOLE_LOGDIR"),
                                   domainid))
        file("%s/%s.out" % (xenrt.TEC().getLogdir(), self.TEST), "w").write(data)
        data = filter(re.compile("XenTest").search, data.split("boot:"))
        for item in data:
            testname = re.search("XenTest: (?P<test>.*)", item).group("test").strip()
            results[testname] = item.strip()
        for key in results:
            failure = re.search("FAIL .*", results[key])
            if failure:
                raise xenrt.XRTFailure("XenTest subcase %s failed: %s" % 
                                       (key, failure.group()))
 
    def postRun(self):
        try: self.testguest.shutdown(force=True)
        except: pass  
        try: self.testguest.uninstall()
        except: pass          

class TC8429(_XenTest):

    TEST = "pagefault"

class TC8430(_XenTest):

    TEST = "CA15723"

class TC8431(_XenTest):

    TEST = "CA24330"

class TC8706(_XenTest):

    TEST = "CA25834"
