#
# XenRT: Test harness for Xen and the XenServer product family
#
# Test XenServer SDK operations
#
# Copyright (c) 2006-2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, re, string, os.path, urllib, traceback, time, xml.dom.minidom
import xenrt, xenrt.lib.xenserver

class TCSDKImport(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCSDKImport")

    def run(self, arglist=None):

        kit = "sdk"

        if arglist and len(arglist) > 0:
            machine = arglist[0]
        else:
            raise xenrt.XRTError("No machine specified for installation")

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)

        # Optional arguments
        vcpus = None
        memory = None
        uninstall = True
        guestname = xenrt.randomGuestName()
        for arg in arglist[1:]:
            l = string.split(arg, "=", 1)
            if l[0] == "vcpus":
                vcpus = int(l[1])
            elif l[0] == "memory":
                memory = int(l[1])
            elif l[0] == "nouninstall":
                uninstall = False
            elif l[0] == "kit":
                kit = l[1]
            elif l[0] == "guest":
                guestname = l[1]

        g = host.guestFactory()(\
            guestname, "NO_TEMPLATE",
            password=xenrt.TEC().lookup("ROOT_PASSWORD_SDK"))
        g.host = host
        self.guest = g
        if vcpus != None:
            g.setVCPUs(vcpus)
        if memory != None:
            g.setMemory(memory)

        # Perform the import
        sdkzip = None
        sdkiso = xenrt.TEC().lookup("SDK_CD_IMAGE", None)
        if not sdkiso:
            sdkzip = xenrt.TEC().getFile("xe-phase-2/%s.zip" % (kit), "%s.zip" % (kit))
        if not sdkiso and not sdkzip:
            sdkiso = xenrt.TEC().getFile("xe-phase-2/%s.iso" % (kit), "%s.iso" % (kit))
        if not sdkiso and not sdkzip:
            raise xenrt.XRTError("No SDK ISO/ZIP file given")
        try:
            if sdkiso:
                mount = xenrt.MountISO(sdkiso)
                mountpoint = mount.getMount()
            if sdkzip:
                # XXX Make this a tempDir once we've moved them out of /tmp
                tmp = xenrt.NFSDirectory()
                mountpoint = tmp.path()
                xenrt.command("unzip %s -d %s" % (sdkzip, mountpoint))
            g.importVM(host, "%s/%s" % (mountpoint, kit))
            br = host.getPrimaryBridge()
            if not br:
                raise xenrt.XRTError("Host has no bridge")
            g.vifs = [("eth0", br, xenrt.randomMAC(), None)]
            for v in g.vifs:
                eth, bridge, mac, ip = v
                g.createVIF(eth, bridge, mac)
        finally:
            try:
                if sdkiso:
                    mount.unmount()
                if sdkzip:
                    tmp.remove()
            except:
                pass
        g.memset(g.memory)
        g.cpuset(g.vcpus)

        xenrt.TEC().registry.guestPut(guestname, g)

        # Make sure we can boot it
        g.makeNonInteractive()
        g.tailored = True
        g.start()
        time.sleep(120)
        g.shutdown()

        # Uninstall
        if uninstall:
            g.uninstall()
        
    def postRun(self):
        r = self.getResult(code=True)
        if r == xenrt.RESULT_FAIL or r == xenrt.RESULT_ERROR:
            # Make sure the guest isn't running anymore
            if self.guest:
                self.tec.logverbose("Making sure %s is shut down" %
                                    (self.guest.name))
                try:
                    self.guest.shutdown(force=True)
                except:
                    pass

class TCSDKTest(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCSDKTest")

    def run(self, arglist=None):
        gname = None
        testname = "cli"

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            if l[0] == "test":
                testname = l[1]

        if not gname:
            raise xenrt.XRTError("No guest name specified")

        guest = self.getGuest(gname)
        if guest.getState() == "DOWN":
            guest.start()

        xenrt.TEC().comment("Running SDK test %s" % (testname))
        testscript = "/SDK/sdktests/test_%s_on_localhost" % (testname)
        rtxt = "/SDK/sdktests/output/testlog_%s.txt" % (testname)
        rxml = "/SDK/sdktests/output/testlog_%s.xml" % (testname)

        if guest.execguest("test -e %s" % (testscript), retval="code") != 0:
            xenrt.TEC().skip("No test %s found in SDK" % (testname))
            return

        self.runAsync(guest, testscript, timeout=5400)
        
        sftp = guest.sftpClient()
        try:
            ltxt = "%s/%s" % (self.tec.getLogdir(), os.path.basename(rtxt))
            lxml = "%s/%s" % (self.tec.getLogdir(), os.path.basename(rxml))
            sftp.copyFrom(rtxt, ltxt)
            sftp.copyFrom(rxml, lxml)
        finally:
            sftp.close()

        xenrt.TEC().logverbose("About to parse results file")
        if self.readResults(lxml) == 0:
            raise xenrt.XRTError("No results found in XML file")


