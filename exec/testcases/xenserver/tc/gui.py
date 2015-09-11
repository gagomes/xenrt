#
# XenRT: Test harness for Xen and the XenServer product family
#
# XenCenter tests 
#
# Copyright (c) 2010 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import re, string, time, traceback, sys, os, os.path, xml.dom.minidom, socket, ConfigParser , tempfile , stat
import xenrt, xenrt.lib.xenserver
import appliance
import vswitch
import bonding

def addEntryDNS(ip, host):
    """ Set the IP in the hosts file"""
    host.execdom0("echo nameserver %s > /etc/resolv.conf" % ip)

class _TCXenCenterNUnit(xenrt.TestCase):
    """Execute the XenCenter NUnit tests"""

    NODOTNETAUTO = True
    MEMORY = None
    DISTRO = None
    
    def prepare(self, arglist):

        # Prepare a VM to run XenCenter
        self.host = self.getDefaultHost()
        self.guest = xenrt.GEC().registry.guestGet(self.DISTRO)
        
        if not self.guest:
            self.guest = xenrt.lib.xenserver.guest.createVM(\
                self.host,
                self.DISTRO,
                distro=self.DISTRO,
                memory=self.MEMORY,
                vifs=xenrt.lib.xenserver.Guest.DEFAULT)
            xenrt.GEC().registry.guestPut(self.DISTRO, self.guest)
            
            self.guest.installDrivers()
            self.getLogsFrom(self.guest)
            self.guest.installNUnit()

            # The tests need the Windows machine to be using British date format
            self.guest.winRegAdd("HKCU",
                                 "Control Panel\\International",
                                 "sShortDate",
                                 "SZ",
                                 "dd/MM/yyyy")
            self.guest.winRegAdd("HKCU",
                                 "Control Panel\\International",
                                 "sLongDate",
                                 "SZ",
                                 "dd MMMM yyyy")
            self.guest.winRegAdd("HKCU",
                                 "Control Panel\\International",
                                 "sTimeFormat",
                                 "SZ",
                                 "HH:mm:ss")

            # Install XenCenter
            self.guest.installCarbonWindowsGUI(noAutoDotNetInstall = self.NODOTNETAUTO)

        # Find where we installed the thing
        x = self.guest.findCarbonWindowsGUI()
        if not x:
            raise xenrt.XRTError("Could not find the installed GUI")
        self.xenadmindir, self.xenadminexe = x

        # Fetch and copy the tarball containing the tests
        testtar = xenrt.TEC().getFile("xe-phase-1/XenAdminTests.tgz",
                                      "XenAdminTests.tgz")
        if not testtar:
            raise xenrt.XRTError("Could not retrieve the test tarball")
        tdir = self.guest.tempDir()
        self.tdir = tdir
        self.guest.xmlrpcSendFile(testtar, "%s\\XenAdminTests.tgz" % (tdir))
        self.guest.xmlrpcExtractTarball("%s\\XenAdminTests.tgz" % (tdir), tdir)
        if not self.guest.xmlrpcFileExists("%s\\Release\\xenadmintests.sh" %
                                           (tdir)):
            raise xenrt.XRTError("Test tarball does not contain "
                                 "Release/xenadmintests.sh")

        # Determine the clock skew between the guest and the controller 
        # (if any) so we can correlate logs accurately
        xenrt.TEC().logverbose("Clock skew is %s seconds (positive value "
                               "means guest clock is fast)" %
                               (self.guest.getClockSkew()))

    def run(self, arglist):

        logdir = self.guest.tempDir()
        
        # Run NUnit tests
        self.guest.arch = self.guest.xmlrpcGetArch()
        g = self.guest.xmlrpcGlobPattern("c:\\Program Files%s\\NUnit*\\bin"
                                         "\\net-2.0\\nunit-console.exe"
                                         % (self.guest.arch == "amd64"
                                            and " (x86)" or ""))
        if len(g) < 1:
            raise xenrt.XRTError("Unable to locate nunit-console.exe")
        
        categories = ["SmokeTest"]
        for category in categories:
        
            xenrt.TEC().logverbose("Running category: " + category)
            
            cmd = []
            cmd.append('"%s"' % (g[0]))
            cmd.append("/process=separate")
            cmd.append("/noshadow")
            cmd.append("/err=\"%s\\%s.error.nunit.log\"" % (logdir, category))
            cmd.append("/timeout=120000")
            cmd.append("/output=\"%s\\%s.output.nunit.log\"" % (logdir, category))
            cmd.append("/xml=\"%s\\%s.XenAdminTests.xml\"" % (logdir, category))
            cmd.append('"%s\\Release\\XenAdminTests.dll"' % (self.tdir))
            cmd.append("/include=%s" % category)
            if isinstance(self.host, xenrt.lib.xenserver.DundeeHost):
                cmd.append("/framework=net-4.0")
            
            try:
                self.guest.xmlrpcExec(string.join(cmd), timeout=3600)
                self.testcaseResult("NUnit", category + "Run", xenrt.RESULT_PASS)
            except xenrt.XRTFailure, e:
                self.testcaseResult("NUnit", category + "Run", xenrt.RESULT_FAIL, e.reason)

            # Copy logs back
            for f in ["error.nunit.log", "output.nunit.log", "XenAdminTests.xml"]:
                rf = "%s\\%s.%s" % (logdir, category, f)
                lf = "%s/%s.%s" % (self.tec.getLogdir(), category, f)
                if self.guest.xmlrpcFileExists(rf):
                    self.guest.xmlrpcGetFile(rf, lf)

            # Parse results
            fn = "%s/%s.XenAdminTests.xml" % (self.tec.getLogdir(), category)
            serial = 0
            uniqlist = []
            if os.path.exists(fn):
                self.testcaseResult("NUnit", "XML", xenrt.RESULT_PASS)
                try:
                    xmltree = xml.dom.minidom.parse(fn)
                    testcases = xmltree.getElementsByTagName("test-case")
                    for testcase in testcases:
                        executed = testcase.getAttribute("executed")
                        if executed != "True":
                            continue
                        success = testcase.getAttribute("success")
                        name = testcase.getAttribute("name")
                        name = name.replace("'", "")
                        name = name.replace("\"", "")
                        name = name.replace("`", "")
                        name = name.replace(" ", "_")
                        name = name.replace("(", "")
                        name = name.replace(")", "")
                        n = name.split(".")
                        if len(n) >= 2:
                            split = int((len(n) + 1)/2)
                            group = string.join(n[0:split], ".")[-40:]
                            testcase = string.join(n[split:], ".")[-40:]
                        elif len(n) == 1:
                            group = "testcase"
                            testcase = n[0]
                        elif len(n) == 0:
                            group = "testcase"
                            testcase = "%04u" % (serial)
                            serial = serial + 1
                        if success == "True":
                            outcome = xenrt.RESULT_PASS
                            reason = None
                        else:
                            outcome = xenrt.RESULT_FAIL
                            reason = "test-case failed"
                        if (group, testcase) in uniqlist:
                            while True:
                                testcasex = testcase + "%04u" % (serial)
                                serial = serial + 1
                                if not (group, testcasex) in uniqlist:
                                    testcase = testcasex
                                    break
                        self.testcaseResult(group, testcase, outcome, reason)
                        uniqlist.append((group, testcase))
                        
                    self.testcaseResult("NUnit",
                                        category+"XMLParse",
                                        xenrt.RESULT_PASS)
                except Exception, e:
                    self.testcaseResult("NUnit",
                                        category+"XMLParse",
                                        xenrt.RESULT_ERROR,
                                        "Error parsing XenAdminTests.xml: %s" %
                                        (str(e)))
            else:
                self.testcaseResult("NUnit",
                                    category+"XML",
                                    xenrt.RESULT_ERROR,
                                    "Cannot find XenAdminTests.xml")
        

class LocalXenRTInfiniteLoop(xenrt.TestCase):
    def run(self, arglist=None):
        self.var = 1
        while self.var > 0:
            self.var = self.var + 1
            if self.var == 10000:
                self.var = 1
            time.sleep(1500)
    

class TC11011(_TCXenCenterNUnit):
    """Execute the XenCenter NUnit tests on Windows 7 32 bit"""
    DISTRO = "win7-x86"
    MEMORY = 4096

class TC11012(_TCXenCenterNUnit):
    """Execute the XenCenter NUnit tests on Windows 7 64 bit"""
    DISTRO = "win7-x64"
    MEMORY = 4096

class TC11013(_TCXenCenterNUnit):
    """Execute the XenCenter NUnit tests on Windows Server 2008 R2"""
    DISTRO = "ws08r2-x64"
    MEMORY = 4096

class TC11014(_TCXenCenterNUnit):
    """Execute the XenCenter NUnit tests on Windows Server 2008 SP2 32 bit"""
    DISTRO = "ws08sp2-x86"
    MEMORY = 4096

class TC11015(_TCXenCenterNUnit):
    """Execute the XenCenter NUnit tests on Windows Server 2008 SP2 64 bit"""
    DISTRO = "ws08sp2-x64"
    MEMORY = 4096

class TC11016(_TCXenCenterNUnit):
    """Execute the XenCenter NUnit tests on Windows Vista EE SP2 32 bit"""
    DISTRO = "vistaeesp2"
    MEMORY = 4096

class TC11017(_TCXenCenterNUnit):
    """Execute the XenCenter NUnit tests on Windows Vista EE SP2 64 bit"""
    DISTRO = "vistaeesp2-x64"
    MEMORY = 4096

class TC11018(_TCXenCenterNUnit):
    """Execute the XenCenter NUnit tests on Windows XP SP3"""
    DISTRO = "winxpsp3"
    NODOTNETAUTO = False
    MEMORY = 4096

class TC11019(_TCXenCenterNUnit):
    """Execute the XenCenter NUnit tests on Windows Server 2003 EE SP2"""
    DISTRO = "w2k3eesp2"
    NODOTNETAUTO = False
    MEMORY = 4096

class TC11020(_TCXenCenterNUnit):
    """Execute the XenCenter NUnit tests on Windows Server 2003 EE SP2 x64"""
    DISTRO = "w2k3eesp2-x64"
    NODOTNETAUTO = False
    MEMORY = 4096
    
class TC19929(_TCXenCenterNUnit):
    """Execute the XenCenter NUnit tests on Windows 8 32bit guest"""
    DISTRO = "win8-x86"
    NODOTNETAUTO = False
    MEMORY = 4096
    
class TC19930(_TCXenCenterNUnit):
    """Execute the XenCenter NUnit tests on Windows Server 2012 64bit guest"""
    """32bit guest support has been stopped by Microsoft"""
    DISTRO = "ws12-x64"
    NODOTNETAUTO = False
    MEMORY = 4096

class TC19931(_TCXenCenterNUnit):
    """Execute the XenCenter NUnit tests on Windows 8 64bit guest"""
    DISTRO = "win8-x64"
    NODOTNETAUTO = False
    MEMORY = 4096


class _InstallXenCenter(xenrt.TestCase):
    """Base class to install the xencenter on predefined distro"""
    DISTRO = None
    NAME = None
    
    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        
    def run(self, arglist):
        
        # Install Guest
        self.guest = self.host.createGenericWindowsGuest(distro=self.DISTRO, name=self.NAME)
        
        # Install XenCenter
        self.guest.installCarbonWindowsGUI()

        # Check path to XenCenter
        guipath, guiexe = self.guest.findCarbonWindowsGUI()
        if not guipath or not guiexe:
            raise xenrt.XRTFailure("No guipath or guiexe file found")
        
        # Try To Run Xencenter
        command = "%s\\%s" % (guipath, guiexe)
        if not self.guest.xmlrpcExec(command = '"%s"' % command, returndata=True):
            raise xenrt.XRTFailure("Unable To Run Xencenter")
        
        # Get The Xencenter logs
        try:
            for lf in string.split(xenrt.TEC().lookup("XENCENTER_LOG_FILE"),";"):
                if self.guest.xmlrpcFileExists(lf):
                    self.guest.xmlrpcGetFile(lf, "%s/XenCenter.log" % (xenrt.TEC().getLogdir()))
        except:
            pass
        
    

class TC19053(_InstallXenCenter):
    """XenCenter install verification on Windows Server 2003 32bit guest"""
    DISTRO = "w2k3eesp2"
    NAME = "Windows Server 2003 32bit"

class TC19054(_InstallXenCenter):
    """XenCenter install verification on Windows Server 2003 64bit guest"""
    DISTRO = "w2k3eesp2-x64"
    NAME = "Windows Server 2003 64bit"

class TC19055(_InstallXenCenter):
    """XenCenter install verification on Windows Server 2008 32bit guest"""
    DISTRO = "ws08sp2-x86"
    NAME = "Windows Server 2008 32bit"

class TC19056(_InstallXenCenter):
    """XenCenter install verification on Windows Server 2008 64bit guest"""
    DISTRO = "ws08sp2-x64"
    NAME = "Windows Server 2008 64bit"

class TC19057(_InstallXenCenter):
    """XenCenter install verification on Windows Server 2008R2 64bit guest"""
    """32bit guest support has been stopped by Microsoft"""
    DISTRO = "ws08r2sp1-x64"
    NAME = "Windows Server 2008R2 64bit"

class TC19058(_InstallXenCenter):
    """XenCenter install verification on Windows Server 2012 64bit guest"""
    """32bit guest support has been stopped by Microsoft"""
    DISTRO = "ws12-x64"
    NAME = "Windows Server 2012 64bit"

class TC19059(_InstallXenCenter):
    """XenCenter install verification on Windows XP 32bit guest"""
    DISTRO = "winxpsp3"
    NAME = "Windows XP 32bit"

class TC19060(_InstallXenCenter):
    """XenCenter install verification on Windows XP 64bit guest"""
    DISTRO = "winxp-x64"
    NAME = "Windows XP 64bit"

class TC19061(_InstallXenCenter):
    """XenCenter install verification on Windows Vista 32bit guest"""
    DISTRO = "vistaeesp2"
    NAME = "Windows Vista 32bit"

class TC19062(_InstallXenCenter):
    """XenCenter install verification on Windows Vista 64bit guest"""
    DISTRO = "vistaeesp2-x64"
    NAME = "Windows Vista 64bit"

class TC19063(_InstallXenCenter):
    """XenCenter install verification on Windows 7 32bit guest"""
    DISTRO = "win7sp1-x86"
    NAME = "Windows 7 32bit"

class TC19064(_InstallXenCenter):
    """XenCenter install verification on Windows 7 64bit guest"""
    DISTRO = "win7sp1-x64"
    NAME = "Windows 7 64bit"

class TC19065(_InstallXenCenter):
    """XenCenter install verification on Windows 8 32bit guest"""
    DISTRO = "win8-x86"
    NAME = "Windows 8 32bit"

class TC19066(_InstallXenCenter):
    """XenCenter install verification on Windows 8 64bit guest"""
    DISTRO = "win8-x64"
    NAME = "Windows 8 64bit"
    
class TC27321(_InstallXenCenter):
    """XenCenter install verification on Windows 10 32bit guest"""
    DISTRO = "win10-x86"
    NAME = "Windows 10 32bit"

class TC27322(_InstallXenCenter):
    """XenCenter install verification on Windows 10 64bit guest"""
    DISTRO = "win10-x64"
    NAME = "Windows 10 64bit"
