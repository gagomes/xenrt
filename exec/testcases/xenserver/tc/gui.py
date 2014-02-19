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
            if isinstance(self.host, xenrt.lib.xenserver.SarasotaHost):
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


class TestComplete(xenrt.TestCase):
    """The base class for TestComplete tests. TestComplete tests should inherit from this class"""
    
    SET_DNS_MASTER = False
    SET_DNS_SLAVE = False
    ENABLE_DVSC_MASTER = False
    ENABLE_DVSC_SLAVE = False
    SET_ISCSI_IQN = False
    
    def run(self, arglist):
        assert(len(arglist) >= 4)
        
        #Initialize common variables
        self.initialize()
        
        if self.SET_DNS_MASTER:
            self.setDNS(self.host1)
        if self.SET_DNS_SLAVE:
            self.setDNS(self.host2)
        if self.ENABLE_DVSC_MASTER:
            self.enableDVSC(self.host1)
        if self.ENABLE_DVSC_SLAVE:
            self.enableDVSC(self.host2)
        if self.SET_ISCSI_IQN:
            self.setISCSIIQN()
        
        # The following parameters need to be provided for running a TestComplete TC
        # tcUnit - Name of the TestComplete Unit containging the TC
        # tcRoutine - Name of the TestComplete Routine which specifies the TC steps 
        # tcID - Testcase ID 
        # postRun set it to true if cleanup is required
        self.guest = self.getGuest("TestComplete")
        self.repoUrl = "http://hg.uk.xensource.com/closed/guitest/%s" %(xenrt.TEC().lookup("TESTCOMPLETE_REPO"))
        self.repoName = re.sub(r"^.+/","", self.repoUrl)
        self.guestSourceCodeDir = "E:\\GUI Automation"
        self.clean = None
        
        try:
            # execute the command for triggering TestComplete test case in the following format :
            # batchFile <TC-unit-name> <TC-routine-name> <TCID>
            batchFile = "c:\\execGuiTC"
            batchCmd = "%s %s %s %s" % (batchFile, arglist[1], arglist[2], arglist[3])
            #check for postRun if any of arglist is defined as true
            for arg in arglist:
                if (re.search('postRun',arg)):
                    if (re.search('true',arg)):
                        self.clean = True
                        break
            xenrt.TEC().logverbose("batchCmd is " + batchCmd)
            result = self.guest.xmlrpcExec(batchCmd, timeout=18000, returndata=True)
            if re.search('Passed',result):
                xenrt.TEC().logverbose("TC-%s Passed" % arglist[3] )
            else:
                xenrt.TEC().logverbose("TC-%s Result is %s" % (arglist[3],result))
                raise xenrt.XRTError("TestComplete TC-%s has failed" % arglist[3])
                
        finally:
            # kill xencenter
            self.guest.xmlrpcKillAll("XenCenterMain.exe")
            
            #Runs Force CleanUp script if asked for it
            if self.clean:
                self.cleanup()
                
            # leave a bit of time for the logs to be generated
            time.sleep(20)
            batchCmd = "c:\\execGuiTC.bat ResultLogger ExportLog %s" % arglist[3]
            xenrt.TEC().logverbose("batchCmd is " + batchCmd)
            result = self.guest.xmlrpcExec("%s %s %s %s" % (batchFile, "ResultLogger", "ExportLog", arglist[3]), timeout=3600, returndata=True)
            if re.search('Passed',result):
                xenrt.TEC().logverbose("Result Logging of Test Passed" )
            else:
                xenrt.TEC().logverbose("Result Logging of Test %s" % result)
            logsDir = "%s\\%s\\XenAutomation\\Log" % (self.guestSourceCodeDir, self.repoName)
            
            if self.guest.xmlrpcDirExists(logsDir):
                self.guest.xmlrpcFetchRecursive(logsDir, xenrt.TEC().getLogdir())
                self.guest.xmlrpcDelTree(logsDir)
                
    def cleanup(self):
        batchCmd = 'c:\\execGuiTC.bat Search ClearSetup ClearSetup'
        result = self.guest.xmlrpcExec(batchCmd,timeout= 3600,returndata=True)
        if re.search('Passed',result):
            xenrt.TEC().logverbose("ClearSetup Passed" )
        else:
            xenrt.TEC().logverbose("ClearSetup Result is %s" % (result)) 
        
        #Setting the DNS entry in server if AD server exists
        if self.getGuest("AUTHSERVER"):
            self.setDNS(self.host1)
            self.setDNS(self.host2)
            
        self.setISCSIIQN()
                
    def getXMLEntry(self, name):
        """Retrieve value of an input from the global XML file"""
        if not self.guest.xmlrpcFileExists(self.globalXMLFile):
            xenrt.TEC().logverbose("%s not found"%self.globalXMLFile)
        tempFile = xenrt.TEC().tempFile()
        self.guest.xmlrpcGetFile(self.globalXMLFile,tempFile)
        doc=xml.dom.minidom.parse(tempFile)
        node = doc.getElementsByTagName(name)
        if (node):
            value = node.item(0).firstChild.data
            xenrt.TEC().logverbose("Value of "+name+" is "+value)
            return value
        else:
            xenrt.TEC().logverbose(name+" not found in global XML file")
            return None
    
    def setISCSIIQN(self):
        """set iscsiiqn settings for both master and slave"""
        self.iscsiInitiator = self.getXMLEntry("iscsiInitiator")
        if  self.iscsiInitiator is not None : 
            for h in [self.host1,self.host2]:
                h.setIQN(self.iscsiInitiator)
            
    def setDNS(self, server):
        # adding the AD server ip in DNS entry of server
        
        self.authserver = self.getGuest("AUTHSERVER")
        adIP = self.authserver.getIP()
        addEntryDNS(adIP, server)
    
    def enableDVSC(self, server):
        # enabling DVSC on the server
        self.dvscService = xenrt.TEC().registry.guestGet("DVSCController").getDVSCWebServices()
        self.dvscService.addHostToController(server)
        
 
    def initialize(self):
        """Initialixe all common variables required by TestComplete """
        
        #Get the hosts
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host2 = self.getHost("RESOURCE_HOST_2")
        self.guest = self.getGuest("TestComplete")
        self.globalXMLFile = "C:\\xenrtTestCompleteConfig.xml"
        
class TC1857(TestComplete):
    # Requires user xsag-pa as part of the additional AD setup
    def prepare(self, arglist):
        self.host2 = self.getHost("RESOURCE_HOST_2")
        self.authserver = self.getGuest("AUTHSERVER")
        adIP = self.authserver.getIP()
        addEntryDNS(adIP, self.host2)
        

class TC1866(TestComplete):
    """Class for creating setup for Extra AD Server"""
    def prepare(self, arglist=None):
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host2 = self.getHost("RESOURCE_HOST_2")
        self.authserver = self.getGuest("AUTHSERVER2")
        
        adIP = self.authserver.getIP()
        self.authserver = xenrt.ActiveDirectoryServer(self.authserver, domainname="xsagsec.com")
        addEntryDNS(adIP, self.host2)
        
class TC14073(TestComplete):
    SET_DNS_SLAVE = True
    
class TC10504(TestComplete):
    SET_DNS_SLAVE = True
    
class TC1138(TestComplete):
    SET_ISCSI_IQN = True  
    
class TC1139(TestComplete):
    SET_ISCSI_IQN = True 
    
class TC1141(TestComplete):
    SET_ISCSI_IQN = True     
 
class TC1142(TestComplete):
    SET_ISCSI_IQN = True 
    
class TC1144(TestComplete):
    SET_ISCSI_IQN = True 
    
class TC1145(TestComplete):
    SET_ISCSI_IQN = True 
    
class TC1149(TestComplete):
    SET_ISCSI_IQN = True 

class TC1143(TestComplete):
    SET_ISCSI_IQN = True 
    
class TC11444(TestComplete):
    SET_ISCSI_IQN = True 
    
class TC13990(TestComplete):
    ENABLE_DVSC_MASTER = True
    ENABLE_DVSC_SLAVE = True
    
class TC12191(TestComplete):
    ENABLE_DVSC_MASTER = True

class TestCompleteSetup(xenrt.TestCase):

    def initialize(self, arglist):
        """Initialixe all common variables required by TestComplete setup"""
        assert(len(arglist) >= 1)        
        # args must be of this format in the sequence file:
        # <arg>http://hg.uk.xensource.com/closed/guitest/tampa.hg</arg>
        
        #TestcompleteRepository to be used for Testing will be come from suite file
        self.repoUrl = "http://hg.uk.xensource.com/closed/guitest/%s" %(xenrt.TEC().lookup("TESTCOMPLETE_REPO"))
        self.repoName = re.sub(r"^.+/","", self.repoUrl)
        
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host2 = self.getHost("RESOURCE_HOST_2")
        
        # this host will always be used for the TestComplete VM.
        # TestCompelte and the XenCenter to be tested are on this VM.
        self.host = self.getHost("RESOURCE_HOST_0")
        self.guestSourceCodeDir = "E:\\GUI Automation"
        self.guest = self.getGuest("TestComplete")
        self.testExePath = "C:\\Program Files\\Automated QA\\TestExecute 8\\Bin\\TestExecute.exe"
        self.projPath = "%s\\%s\\XenAutomation\\XenAutomation.pjs" % (self.guestSourceCodeDir, self.repoName)

        # Global data XML file
        self.globalXMLFile = "C:\\xenrtTestCompleteConfig.xml"

    def addChild(self, doc, parent, name, value):
        n = doc.createElement(name)
        n.appendChild(doc.createTextNode(value))
        parent.appendChild(n)
        
    def addCustomXMLEntry(self, name, value):
        """Adds custom database entry into the global XML file in TestComplete VM"""
        if not self.guest.xmlrpcFileExists(self.globalXMLFile):
            xenrt.TEC().logverbose("%s not found"%self.globalXMLFile)
        tempFile = xenrt.TEC().tempFile()
        self.guest.xmlrpcGetFile(self.globalXMLFile,tempFile)
        xmldoc=xml.dom.minidom.parse(tempFile)
        child = xmldoc.createElement(name)
        child.appendChild(xmldoc.createTextNode(value))
        for node in xmldoc.getElementsByTagName("tc"):
            node.appendChild(child)
        fp = open(tempFile,'w')
        fp.write(xmldoc.toxml())
        fp.close()
        # copy the edited XML file to the guest for use by testcomplete
        self.guest.xmlrpcSendFile(tempFile, self.globalXMLFile) 
        
    def getXMLEntry(self, name):
        """Retrieve value of an input from the global XML file"""
        if not self.guest.xmlrpcFileExists(self.globalXMLFile):
            xenrt.TEC().logverbose("%s not found"%self.globalXMLFile)
        tempFile = xenrt.TEC().tempFile()
        self.guest.xmlrpcGetFile(self.globalXMLFile,tempFile)
        doc=xml.dom.minidom.parse(tempFile)
        node = doc.getElementsByTagName(name)
        if (node):
            value = node.item(0).firstChild.data
            xenrt.TEC().logverbose("Value of "+name+" is "+value)
            return value
        else:
            xenrt.TEC().logverbose(name+" not found in global XML file")
            return None
        
    def getCustomXmlEntries(self, allConfig):
        """Allows any derived classes to add extra config"""
        
        output = {}
        output["slaveServerName"] = allConfig["RESOURCE_HOST_2"]
        output["slaveServerIP"] = allConfig["HOST_CONFIGS_" + allConfig["RESOURCE_HOST_2"] + "_HOST_ADDRESS"]
        output["slaveUsrName"] = "root"
        output["slaveUsrPwd"] = xenrt.TEC().lookup("ROOT_PASSWORD")
        output["srCIFSName"] = "CIFS SR"
        output["srNFSISOName"] = "NFS ISO SR"
        output["srNFSVHDName"] = "NFS SR"
        output["sriSCSIName"] = "iSCSI Storage"
        output["poolName"] = "Pool1"
        output["poolDesc"] = "2 host pool"
        #output["licenseServerIP "] = self.getGuest("LicenseServer").getIP()
        # Using the Citrix wide license server until the license server is updated with valid licenses
        output["licenseServerIP "] = "FTLENGMFLIC.eng.citrite.net"
        output["licenseServerPort "] = "27000"
        output["srNFSISOPath"] = allConfig["EXPORT_ISO_NFS"]
        
        if hasattr(self, 'nfs'):
            output["srNFSVHDPath"] = self.nfs.getMount()
        if hasattr(self, 'cifsShareName'):
            output["srCIFSUserName"] = "Administrator"
            output["srCIFSPassword"] = xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS", "ADMINISTRATOR_PASSWORD"])
            output["srCIFSISOPath"] = "\\\\" + self.guest.getIP() + "\\" + self.cifsShareName
        if hasattr(self, 'iscsilun'):
            output["sriSCSITargetIqns"] = self.iscsilun.getTargetName() + " (" +self.iscsilun.getServer() + ":3260)"
            output["sriSCSIPath"] = self.iscsilun.getServer()
            output["sriSCSITargetLun"] = "*"+self.lunName+"*"
            output["iscsiInitiator"] = self.iscsiInitiator
        if hasattr(self, 'netapp'):
            output["NetAppFilerAddress"] = self.netapp.getTarget()
            output["NetAppUsrName"] = self.netapp.getUsername()
            output["NetAppPasswd"] = self.netapp.getPassword()
            output["NetAppAggrName"] = self.netapp.getAggr()
            output["NetAppSystmStorageFullName"] = self.netapp.getFriendlyName()

        return output
    
    def getXml(self):
        """Get all XenRT config and put it in an xml file for TestComplete"""
        
        # create new xml doc
        impl = xml.dom.minidom.getDOMImplementation()
        newdoc = impl.createDocument(None, "guitest", None)
        
        # create tc node with id=1
        n = newdoc.createElement("tc")
        n.setAttribute("id", "1")
        newdoc.documentElement.appendChild(n)
        
        # add all config to xml doc
        allConfig = {}
        for c in re.findall(r"(.+?)='(.*)'\n", xenrt.GEC().config.getAll(deep=True)):
            allConfig[c[0]] = c[1]
            self.addChild(newdoc, n, c[0], c[1])
            
        xenrt.TEC().logverbose("All config: " + xenrt.GEC().config.getAll(deep=True))
        
        # add custom test complete entries
        masterServerName = allConfig["RESOURCE_HOST_1"]
        
        # Load XenServer data
        self.addChild(newdoc, n, "masterServerName", masterServerName)
        self.addChild(newdoc, n, "masterServerIP", allConfig["HOST_CONFIGS_" + masterServerName + "_HOST_ADDRESS"])
        self.addChild(newdoc, n, "masterUsrName", "root")
        self.addChild(newdoc, n, "masterUsrPwd", xenrt.TEC().lookup("ROOT_PASSWORD"))
        
        custom = self.getCustomXmlEntries(allConfig)
        for k in custom.keys():
            self.addChild(newdoc, n, k, custom[k])
        
        return newdoc.toxml()
        
    # Apply license by editing the HASP License configuration file
    # with the hostname and license manager information
    def applyLicense(self):
        licServer = xenrt.TEC().lookup("TESTCOMPLETE_LIC_SERVER")
        
        if not licServer:
            raise xenrt.XRTError("No TestComplete license server specified")
        
        tempFile = xenrt.TEC().tempFile()
        
        cp = ConfigParser.ConfigParser()
        cp.add_section("SERVER")
        cp.add_section("REMOTE")
        cp.add_section("ACCESS")
        cp.add_section("USERS")
        cp.add_section("LOGPARAMETERS")
        cp.add_section("UPDATE")
        cp.set('SERVER', 'name', self.getHost("RESOURCE_HOST_0").getIP())
        cp.set('SERVER', 'pagerefresh', '3')
        cp.set('SERVER', 'linesperpage', '20')
        cp.set('SERVER', 'accremote', '1')
        cp.set('SERVER', 'enabledetach', '0')
        cp.set('SERVER', 'reservedseats', '0')
        cp.set('SERVER', 'reservedpercent', '0')
        cp.set('SERVER', 'detachmaxdays', '14')
        cp.set('SERVER', 'requestlog', '0')
        cp.set('SERVER', 'loglocal', '0')
        cp.set('SERVER', 'logremote', '0')
        cp.set('SERVER', 'logadmin', '0')
        cp.set('SERVER', 'errorlog', '0')
        cp.set('SERVER', 'rotatelogs', '0')
        cp.set('SERVER', 'pidfile', '0')
        cp.set('SERVER', 'passacc', '0')
        cp.set('SERVER', 'accessfromremote', '1')
        cp.set('SERVER', 'accesstoremote', '1')
        cp.set('UPDATE', 'update_host', 'www.aladdin.com')
        cp.set('UPDATE', 'language_url', '/hasp/language_packs/end-user/')
        cp.set('REMOTE', 'broadcastsearch', '1')
        cp.set('REMOTE', 'aggressive', '30')
        cp.set('REMOTE', 'serveraddr', licServer)
        cp.set('REMOTE', 'serversearchinterval', '30')
        cp.set('LOGPARAMETERS', 'text', '{timestamp} {clientaddr}:{clientport} {clientid} {method} {url} {function}({functionparams}) result({statuscode}){newline}')
        fp = open(tempFile,'w')
        cp.write(fp)
        fp.close()
        
        self.guest.xmlrpcSendFile(tempFile, "C:\\Program Files\\Common Files\\Aladdin Shared\\HASP\\hasplm.ini")
    
    
    def prepare(self, arglist):
        self.initialize(arglist)
                     
        self.template = xenrt.lib.xenserver.guest.createVMFromFile(self.host1, "Demo Linux VM", "xe-phase-1/dlvm.xva")
        self.template.paramSet("is-a-template", "true")
        xenrt.TEC().logverbose("Created Demo Linux VM template on master server host")
        
        # map the testcomplete distfiles location to f:
        if not self.guest.xmlrpcDirExists("f:\\"):
            self.guest.installWindowsNFSClient()
            df = xenrt.TEC().lookup("EXPORT_DISTFILES_NFS")
            self.guest.xmlrpcExec("mount %s/testcomplete f:" % (df))
        
        # create storage setup required by TestComplete
        for arg in arglist:
            if re.search("storageType", arg, re.I):
                self.storageList = arg.split('=')[1]
                if re.search("nfs", self.storageList, re.I):
                    self.nfs = xenrt.ExternalNFSShare()
                if re.search("cifs", self.storageList, re.I):
                    # Enable file and printer sharing on the guest for CIFS share
                    self.guest.xmlrpcExec("netsh firewall set service type=fileandprint mode=enable profile=all")
                    # Share a directory for CIFS share
                    self.cifsShareDir = "c:\\users\\administrator\\appdata\\local\\temp\\cifsshare"
                    self.cifsShareName = "XENRTSHARE"
                    if not self.guest.xmlrpcFileExists(self.cifsShareDir):
                        self.guest.xmlrpcCreateDir(self.cifsShareDir)
                        self.guest.xmlrpcExec("net share %s=%s /GRANT:Administrator,FULL" % (self.cifsShareName, self.cifsShareDir))
                if re.search("iscsi", self.storageList, re.I):
                    self.iscsilun = xenrt.ISCSILun()
                    self.iscsiInitiator = self.iscsilun.getInitiatorName(allocate=True)
                    for h in [self.host1,self.host2]:
                        h.setIQN(self.iscsiInitiator)
                    try:
                        xml = self.host1.execdom0('xe sr-probe type=lvmoiscsi device-config:target="%s" device-config:targetIQN="%s"' % (self.iscsilun.getServer(), self.iscsilun.getTargetName()))
                    except Exception, e:
                        xml = str(e.data)
                    xenrt.TEC().logverbose("sr-probe data is: " + xml)
                    xenrt.TEC().logverbose("iSCSI LUN id is: " + self.iscsilun.getID())
                    self.lunName = re.search(r"<serial>\s*?([^\s]+?)\s*?</serial>.+?<SCSIid>\s*?" + self.iscsilun.getID() + "\s*?</SCSIid>", xml, re.MULTILINE|re.DOTALL).group(1)
                    xenrt.TEC().logverbose("iSCSI LUN name is: " + self.lunName)
                if re.search("netapp", self.storageList, re.I):
                    minsize = int(self.host.lookup("SR_NETAPP_MINSIZE", 40))
                    maxsize = int(self.host.lookup("SR_NETAPP_MAXSIZE", 10000000))
                    self.netapp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
                    xenrt.TEC().logverbose("Netapp target is : " + self.netapp.getTarget())
                    xenrt.TEC().logverbose("Netapp Username is : " + self.netapp.getUsername())
                    xenrt.TEC().logverbose("Netapp Password is : " + self.netapp.getPassword())
                    xenrt.TEC().logverbose("Netapp getAggr is : " + self.netapp.getAggr())
                    xenrt.TEC().logverbose("Netapp FriendlyName is : " + self.netapp.getFriendlyName())
        
        xenrt.TEC().logverbose("*****Starting ToolsInstaller thread*****")
        toolsInstaller = _ToolsInstaller([self.host1, self.host2])
        toolsInstaller.start()
              
        
        # format extra disk for the TestComplete source
        if not self.guest.xmlrpcDirExists("e:\\"):
            disks = self.guest.xmlrpcListDisks()
            rootdisk = self.guest.xmlrpcGetRootDisk()
            secdisks = [ x for x in disks if not x == rootdisk ][0]
            newdisk = secdisks[0]
            letter = self.guest.xmlrpcPartition(newdisk)
            self.guest.xmlrpcFormat(letter, timeout=7200, quick=True)
        
        if not self.guest.xmlrpcFileExists("c:\\testexecute\\setup.exe"):
            self.guest.xmlrpcUnpackTarball("%s/testexecute.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")
            self.guest.xmlrpcExec("c:\\testexecute\\setup.exe /s")
        
        # testcomplete licensing
        self.guest.disableFirewall()
        self.applyLicense()

        self.additionalGuestSetup()
        
        if not self.guest.xmlrpcDirExists("C:\\exports"):
            # the testcomplete tests expect this directory.
            self.guest.xmlrpcCreateDir("C:\\exports")
        
        # copy job config to the guest for use by testcomplete
        self.guest.xmlrpcCreateFile(self.globalXMLFile, self.getXml())
        
        # install XC if required
        self.guest.installCarbonWindowsGUI(noAutoDotNetInstall=True)

        # clear testcomplete source-code if required.
        if self.guest.xmlrpcDirExists(self.guestSourceCodeDir):
            self.guest.xmlrpcDelTree(self.guestSourceCodeDir)
        else:
            # create dir for testcomplete-source code
            self.guest.xmlrpcCreateDir(self.guestSourceCodeDir)

        temp = xenrt.TEC().tempDir()
        
        # get TestComplete source code
        xenrt.util.command("cd %s && hg clone %s" % (temp, self.repoUrl))
        
        # tar-gzip the XenAutomation dir from the source code repo
        xenrt.util.command("cd %s/%s && tar -zcvf ../source.tar.gz ./" % (temp, self.repoName))
        
        # send the compressed source to the guest
        self.guest.xmlrpcSendFile("%s/source.tar.gz" % temp, "c:\\source.tar.gz")
        
        # extract the source code onto the guest
        self.guest.xmlrpcExtractTarball("c:\\source.tar.gz", "%s\\%s" % (self.guestSourceCodeDir, self.repoName))

        # create bat file for executing TestComplete test
        xenrt.TEC().logverbose("Creating Test BAT file")
        tempFile = xenrt.TEC().tempFile()
        t = []
        t.append("""@ECHO OFF""")
        t.append("""set tcExePath="%s" """ %self.testExePath)
        t.append("""set pjsFilePath="%s" """%self.projPath)
        t.append("""%tcExePath% %pjsFilePath% /r /p:XenAutomation /u:%1 /rt:%2 "tcID="%3 /silentMode /ns /exit""")
        t.append("""IF ERRORLEVEL 3 GOTO CannotRun""")
        t.append("""IF ERRORLEVEL 2 GOTO Errors""")
        t.append("""IF ERRORLEVEL 1 GOTO Warnings""")
        t.append("""IF ERRORLEVEL 0 GOTO Success""")
        t.append(""":CannotRun""")
        t.append("""ECHO The script cannot be run""")
        t.append("""GOTO End""")
        t.append(""":Errors""")
        t.append("""ECHO Failed""")
        t.append("""GOTO End""")
        t.append(""":Warnings""")
        t.append("""ECHO Passed with warnings""")
        t.append("""GOTO End""")
        t.append(""":Success""")
        t.append("""ECHO Passed""")
        t.append("""GOTO End""")
        t.append(""":End""")
        tcCmd = string.join(t, "\n")
        xenrt.TEC().logverbose("tcCmd is " + tcCmd)
        f = file(tempFile, "w")
        f.write("""%s""" %tcCmd)
        f.close()
        self.guest.xmlrpcSendFile(tempFile, "c:\\execGuiTC.bat")
        #sets display of teh VM so objects are within the window frame
        xenrt.TEC().logverbose("Setting the display of the TestComplete VM to a recommended value")
        self.guest.xmlrpcExec('"%s" "%s" /r /p:XenAutomation /u:CommonFunctions /rt:SetsDisplay /silentMode /ns /exit' %(self.testExePath, self.projPath ))

    def additionalGuestSetup(self):
        pass

    def run(self, arglist):
        pass

class TestCompleteADSetup(TestCompleteSetup):
    """Class for creating setup for AD Server"""
    def prepare(self, arglist):   
        self.initialize(arglist)
        # Setting up the AD server - basic domain creation only, using xsag which is a global var in the testcomplete env
        self.authserver = self.getGuest("AUTHSERVER")
        adIP = self.authserver.getIP()
        self.authserver = xenrt.ActiveDirectoryServer(self.authserver, domainname="xsag.com")
        addEntryDNS(adIP, self.host1)
        addEntryDNS(adIP, self.host2)
        
        self.createADUser("xsqa-pa", "admin12!@")
        self.createADUser("xsqa-po", "operator12!@")
        self.createADUser("xsqa-va", "vmadmin12!@")
        self.createADUser("xsqa-vpa", "poweradmin12!@")
        self.createADUser("xsqa-vo", "vmoperator12!@")
        self.createADUser("xsqa-ro", "readonly12!@")
    
    def createADUser(self, user, password):
        # Additional setup for the AD server, create users on a need basis depending on the testcase
        self.authguest = self.getGuest("AUTHSERVER")
        adIP = self.authguest.getIP()
        self.authserver = self.authguest.getActiveDirectoryServer()

        xenrt.TEC().logverbose("Creating user %s with password %s" % (user, password))
        user = self.authserver.addUser(user, password)
        xenrt.TEC().logverbose("User %s created succesfully" % (user))

class TestCompleteDistroSetup(TestCompleteSetup):
    """Class for creating setup for guest distros"""
    def prepare(self, arglist):
        assert(len(arglist) >= 2)
        # args must be of this format in the sequence file:
        # <arg>http://hg.uk.xensource.com/closed/guitest/tampa.hg</arg>
        # <arg>rhel57,centos6</arg>
        # <arg installType=nfs/>

        self.distroList = {}
        
        from collections import defaultdict
        self.distroList = defaultdict(list)
        self.initialize(arglist)
        distroNames=arglist[1].split(',')

        # Determine the architechture, and extract the distro value and construct a dict
        for arg in distroNames:
            xenrt.TEC().logverbose("Setup for distro name %s" % (arg))
            if re.search('x86-64',arg):
                distro = arg.split('_')[0]
                arch="x86-64"
            else:
                distro = arg
                arch = "x86-32"
            self.distroList[distro].append(arch)

        # Look for the installType arg in the seq file
        for arg in arglist:
            installType = re.search('installType',arg)
            if installType:
                # Get the install type, nfs or ftp
                repoType = installType.string.split("=")[1]
                break
        
        if not installType:
            # Default to http if nothing is specified
            repoType = "http"
            
        xenrt.TEC().logverbose("Creating repository of type %s " % (repoType))
        # Raise exception if the installType param has no values
        if not repoType:
            raise xenrt.XRTError("Install type requires a parameter, NFS of FTP")
        elif repoType.lower() == "http":
            self.installHTTP(self.distroList)
        elif repoType.lower() == "nfs":
            self.installNFS(self.distroList)
        else:
            raise xenrt.XRTError("Please specify the right format of arguments for Distro Setups")

    def installNFS(self, distroList):
            method = "NFS"

            for distro, a in self.distroList.iteritems():
                xenrt.TEC().logverbose("Setup for %s-%s" % (distro, a))
                
                # Handle situations when a distro requires both 32 and 64 bit
                for arch in a:
                    # Choose a template and the guest name
                    template = xenrt.lib.xenserver.getTemplate(self.host, distro=distro, arch=arch)
                    xenrt.TEC().logverbose("Guest template is %s" % (template))
                    guest = self.host.guestFactory()(xenrt.randomGuestName(), template, self.host)

                    # Get the repository location
                    r = xenrt.TEC().lookup(["RPM_SOURCE", distro, arch, method], None)
                    if not r:
                        raise xenrt.XRTError("No %s repository for %s %s" % (method, arch, distro))
                    repository = string.split(r)[0]
                    xenrt.TEC().logverbose("Repository is %s"% (repository))

                    # Install from network repository into the VM
                    guest.arch = arch
                    guest.install(self.host, pxe=False, repository=repository, distro=distro, notools=False, method="NFS", dontstartinstall=True, installXenToolsInPostInstall=True)
                    
                    # Testcomplete expects the whole distro name in the global xml unlike in xenrt
                    if arch == "x86-32":
                        newdistro = distro
                    else:
                        newdistro = distro + "_" + arch
                    
                    xenrt.TEC().logverbose("Adding entries in global DB for %s - %s"% (newdistro, arch))

                    # Add entries into the global XML
                    self.addCustomXMLEntry(newdistro + "_PV-args", guest.getBootParams())

                    # guest.paramGet("", "").split(":",1)[1] is required to split the string since its in the format nfs:10.220* only for non sles guests
                    tmp = guest.paramGet("other-config", "install-repository").split(":",1)[1]
                    if not re.search('//', tmp):
                        tmp = "nfs://" + tmp
                    else:
                        tmp = "nfs:" + tmp

                    self.addCustomXMLEntry(newdistro + "_nfs_repo", tmp)
                    guest.uninstall()

    def installHTTP(self, distroList):
        # Install and create http repos for the required distros
        for distro, a in self.distroList.iteritems():
            xenrt.TEC().logverbose("Setup for %s-%s" % (distro, a))
            
            # Install both 32 and 64 bit
            for arch in a:
                guest = xenrt.lib.xenserver.guest.createVM(self.host, distro, distro=distro, arch=arch, memory=1024, vifs=xenrt.lib.xenserver.Guest.DEFAULT, dontstartinstall=True,installXenToolsInPostInstall=True)
                
                # Testcomplete expects the whole distro name in the global xml unlike in xenrt
                if arch == "x86-32":
                    newdistro = distro
                else:
                    newdistro = distro + "_" + arch
                
                xenrt.TEC().logverbose("Adding entries in global DB for %s - %s"% (newdistro, arch))

                self.addCustomXMLEntry(newdistro + "_PV-args", guest.getBootParams())
                self.addCustomXMLEntry(newdistro + "_http_repo", guest.paramGet("other-config", "install-repository"))
                guest.uninstall()

class _ToolsInstaller(xenrt.XRTThread):
    """This thread sits in the background and listens for Windows VMs to install xen-tools on to.
    TestComplete can't do this itself as it doesn't have arpwatch or an xml-rpc client"""
    
    def __init__(self, hosts):
        
        xenrt.XRTThread.__init__(self, name="XenToolsInstaller")
        
        self.hosts = hosts
        self.daemon = True
        self.cliSessions = {}
        
        # store CLI sessions as this thread will stay alive for the entire duration of the test.
        for h in hosts:
            self.cliSessions[h] = h.getCLIInstance()
        
        # guests which don't need to have xen-tools installed
        self.done = []

    def _guestNeedsTools(self, guest, host):
        """Returns True if the specified guest requires xen-tools"""
        
        # ignore if already done
        if guest in self.done:
            return False
            
        # must be windows
        if not "BIOS order" in self.cliSessions[host].execute("vm-param-get uuid=%s param-name=HVM-boot-policy" % guest):
            self.done.append(guest)
            return False
        
        allowedOps = self.cliSessions[host].execute("vm-param-get uuid=%s param-name=allowed-operations" % guest)
        
        # must be started
        if not "hard_shutdown" in allowedOps:
            return False
            
        # must not have tools
        if "clean_shutdown" in allowedOps:
            self.done.append(guest)
            return False
            
        return True
    
    # This function is to install tools on Windows VMs installed via XC wizard. This is a simpler version of the xenrt guest.installDrivers()
    def _tcInstallDrivers(self, guest):
             
        tmp = guest.winRegLookup("HKLM", "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", "ProductName")
        xenrt.TEC().logverbose("Windows Version is "+tmp)
        
        # Install WIC if the iso is a 2k3
        if "2003" in tmp:
            xenrt.TEC().logverbose("Windows 2k3 iso detected, installing Windows Imaging Component")
            guest.xmlrpcUnpackTarball("%s/wic.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")
            exe = guest.xmlrpcGetArch() == "amd64" and "wic_x64_enu.exe" or "wic_x86_enu.exe"
            guest.xmlrpcExec("c:\\wic\\%s /quiet /norestart" % exe, timeout=3600, returnerror=False)
            
        # Insert the tools ISO
        guest.changeCD("xs-tools.iso")
        time.sleep(30)
        
        #Copy the contents of the cd drive to a Temporary Folder in C Drive, this is done for longhorn ISOs
        guest.xmlrpcExec("mkdir C:\\WinTools", timeout=100 ,returndata=True ,ignoreHealthCheck=True)
        guest.xmlrpcExec("copy d:\\* C:\\WinTools", timeout=200 ,returndata=True ,ignoreHealthCheck=True)
        
        if "2008" in tmp:
            xenrt.TEC().logverbose("Windows 2008 iso detected hence adding registry settings disable User Access Control")
            guest.xmlrpcExec("reg add HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Policies\\System /v EnableLUA /t Reg_DWORD /d 0 /f",
                            timeout=3600 , returnerror=False , ignoreHealthCheck = True)
            guest.reboot( force = True )
            time.sleep(300)
         # Check for DOT NET already installed
        if guest.xmlrpcGlobPattern("c:\\windows\\microsoft.net\\framework\\v4.0*\\mscorlib.dll"):
            xenrt.TEC().logverbose(".NET 4.0 already installed.")
        else:
            xenrt.TEC().logverbose("Installing .NET 4.0.")
            guest.xmlrpcExec("C:\\WinTools\\dotNetFx40_Full_x86_x64.exe /q /norestart",
                            timeout=3600, returnerror=False , ignoreHealthCheck = True)
                            
        if "2003" in tmp or "XP" in tmp :
                 xenrt.TEC().logverbose("Windows %s detected.Hence calling private method to skip the Found New Hardware Wizard " %(tmp) )
                 self._tcInstallRunOncePVDriversInstallScript(guest)
        xenrt.TEC().logverbose("Installing Tools ..... ")
        #Sanibel uses xensetup.exe for installing tools
        if not guest.xmlrpcFileExists("C:\\WinTools\installwizard.msi"):
            guest.xmlrpcStart("C:\\WinTools\\xensetup.exe /S /liwearcmuopvx c:\\tools_msi_install.log")
        else:
            guest.xmlrpcStart("C:\\WinTools\installwizard.msi /passive /liwearcmuopvx c:\\tools_msi_install.log")
        xenrt.TEC().logverbose("Installing Tools .....Completed")
        
    def _tcInstallRunOncePVDriversInstallScript(self , guest):
        
        self.workdir = xenrt.resources.WorkingDirectory()

        guest.xmlrpcSendFile("%s/utils/soon.exe" % (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")),"c:\\soon.exe")
        guest.xmlrpcSendFile("%s/utils/devcon.exe" % (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")), "c:\\devcon.exe")
        guest.xmlrpcSendFile("%s/utils/devcon64.exe" % (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")), "c:\\devcon64.exe")
        
        u = []
        for p in string.split(xenrt.TEC().lookup("PV_DRIVERS_DIR"), ";"):
            u.append("""IF EXIST "%s\\xennet.inf" "c:\\devcon.exe" -r update "%s\\xennet.inf" XEN\\vif""" % (p, p))
            u.append("""IF EXIST "%s\\xeniface.inf" "c:\\devcon.exe" -r update "%s\\xeniface.inf" XEN\\iface""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon.exe" -r update "%s\\xenvif.inf" XENBUS\\CLASS^&VIF""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon.exe" -r update "%s\\xeniface.inf" XENBUS\\CLASS^&IFACE""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon.exe" -r update "%s\\xennet.inf" XENVIF\\DEVICE""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon.exe" -r update "%s\\xennet.inf" XEN\\vif""" % (p, p))
        for p in string.split(xenrt.TEC().lookup("PV_DRIVERS_DIR_64"), ";"):
            u.append("""IF EXIST "%s\\xennet.inf" "c:\\devcon64.exe" -r update "%s\\xennet.inf" XEN\\vif""" % (p, p))
            u.append("""IF EXIST "%s\\xeniface.inf" "c:\\devcon64.exe" -r update "%s\\xeniface.inf" XEN\\iface""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon64.exe" -r update "%s\\xenvif.inf" XENBUS\\CLASS^&VIF""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon64.exe" -r update "%s\\xeniface.inf" XENBUS\\CLASS^&IFACE""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon64.exe" -r update "%s\\xennet.inf" XENVIF\\DEVICE""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon64.exe" -r update "%s\\xennet.inf" XEN\\vif""" % (p, p))
        updatecmd = string.join(u, "\n")
        
        t, runonce2 = tempfile.mkstemp("", "xenrt", self.workdir.dir)
        f = file(runonce2, "w")
        f.write("""echo R1.1 > c:\\r1.txt REM ping 127.0.0.1 -n 60 -w 1000 echo R1.2 > c:\\r2.txt %s echo R1.3 > c:\\r3.txt""" % (updatecmd))
        f.close()
        guest.xmlrpcSendFile(runonce2, "c:\\runoncepvdrivers2.bat")

        t, runonce = tempfile.mkstemp("", "xenrt", self.workdir.dir)
        f = file(runonce, "w")
        f.write("""c:\\soon.exe 900 /INTERACTIVE c:\\runoncepvdrivers2.bat > c:\\xenrtlog.txt
at > c:\\xenrtatlog.txt""")
        f.close()
        guest.xmlrpcSendFile(runonce, "c:\\runoncepvdrivers.bat")

        # Set the run once script
        guest.winRegAdd("HKLM",
                       "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\"
                       "RunOnce",
                       "XenRTPVDrivers",
                       "SZ",
                       "c:\\runoncepvdrivers.bat")
                       
    def run(self):
        while True:
            for h in self.hosts:
                try:
                    for g in h.minimalList("vm-list", "uuid"):
                        if self._guestNeedsTools(g, h):
                            name = self.cliSessions[h].execute("vm-param-get uuid=%s param-name=name-label" % g).strip()
                            xenrt.TEC().logverbose("Trying to install XenTools on: " + name)
                            
                            vif = h.parseListForUUID("vif-list", "vm-uuid", g, "device=0")
                            mac = h.genParamGet("vif", vif, "MAC")
                            ip = h.arpwatch("xenbr0", mac, timeout=120)
                            
                            guest = h.guestFactory()(name, host=h)
                            guest.uuid = g
                            guest.windows = True
                            guest.mainip = ip
                            guest.enlightenedDrivers = False
                            guest.waitForDaemon(3600, desc="Windows final boot")
                            time.sleep(120)
                            xenrt.TEC().logverbose("Waiting for c:\\alldone.txt...")
                            deadline = xenrt.timenow() + 3600
                            
                            while True:
                                try:
                                    if guest.xmlrpcFileExists("c:\\alldone.txt"):
                                        break
                                except Exception, e:
                                    pass
                                if xenrt.timenow() > deadline:
                                    raise xenrt.XRTFailure("Timed out waiting for Windows post-install alldone flag")
                                time.sleep(60)
                            
                            xenrt.TEC().logverbose("Calling Customized Windows Tools Drivers Installation Method")
                            self._tcInstallDrivers(guest)
                            #guest.installDrivers()
                            self.done.append(g)
                except Exception, e:
                    xenrt.TEC().logverbose("Caught exception in tools installer: " + str(e))
            
            xenrt.TEC().logverbose("Waiting 3 mins before checking again.")
            time.sleep(180)

class TestCompleteWLBSetup(TestCompleteSetup):
        #Inheriting TestCompleteSetup
        def prepare(self, arglist=None): 
        
            #Initialize global variables
            self.initialize(arglist)
            
            #Creating an Instance of _WLBApplianceVM class and calling its prepare method to do the WLB setup
            self.wlbinst = appliance._WlbApplianceVM()
            self.wlbinst.prepare(arglist)
           
            #Retrieving WLB VM's IP and credentials
            self.wlbguest = self.getGuest("VPXWLB")
            wlb_ip = self.wlbguest.getIP()           
            wlbUsername = self.wlbinst.wlbserver.wlb_username
            wlbPassword = self.wlbinst.wlbserver.wlb_password           
            
            xenrt.TEC().logverbose( "The WLB Appliance VM ip is %s" % (wlb_ip) )            
            xenrt.TEC().logverbose( "The WLB Appliance VM Username is %s" % (wlbUsername) )
            xenrt.TEC().logverbose( "The WLB Appliance VM Password is %s" % (wlbPassword) ) 
            
            #Add the WLB VM's ip and credentials to the globalxml file in the TestCompleteVM
            self.addCustomXMLEntry("wlbUserName" , wlbUsername)
            self.addCustomXMLEntry("wlbPasswd" , wlbPassword)
            self.addCustomXMLEntry("wlbIP",wlb_ip)

class TestCompleteDVSCSetup(TestCompleteSetup):
    """Class for creating setup for DVSC Controller"""
    
    def prepare(self, arglist):
        #Initialize the common variable
        self.initialize(arglist)
        
        #Adding the xml entry in global xml file for DVSC
        self.dvscVM = xenrt.TEC().registry.guestGet("DVSCController")
        self.dvscService = self.dvscVM.getDVSCWebServices()
        dvscIP = self.dvscVM.getIP()
        self.addCustomXMLEntry("DVSCIP", dvscIP)
        self.addCustomXMLEntry("DVSCVMName", "DVSCController")
        self.addCustomXMLEntry("DVSLoginName", "admin")
        self.addCustomXMLEntry("DVSDefaultPassword", "admin")
        self.addCustomXMLEntry("DVSNewPassword", "x$@gpw")


class TCLimitedLicense(TestCompleteSetup):
    # adding the third host
    def run(self, arglist):
        self.host3 = self.getHost("RESOURCE_HOST_3")
        self.addCustomXMLEntry("slave1ServerName", self.host3.getName())
        self.addCustomXMLEntry("slave1ServerIP", self.host3.getIP())
        
class TCMultipleHostSetup(TestCompleteSetup):
    # adding 3 more hosts
    def run(self, arglist):
        self.host3 = self.getHost("RESOURCE_HOST_3")
        self.addCustomXMLEntry("slave1ServerName", self.host3.getName())
        self.addCustomXMLEntry("slave1ServerIP", self.host3.getIP())
        self.host4 = self.getHost("RESOURCE_HOST_4")
        self.addCustomXMLEntry("slave2ServerName", self.host4.getName())
        self.addCustomXMLEntry("slave2ServerIP", self.host4.getIP()) 
        self.host5 = self.getHost("RESOURCE_HOST_5")
        self.addCustomXMLEntry("slave3ServerName", self.host5.getName())
        self.addCustomXMLEntry("slave3ServerIP", self.host5.getIP())        

class TestCompleteRPUPrepare(TestCompleteSetup):
    def prepare(self, arglist):
    # parse arg list to determine what builds need to be installed on respective hosts
        for arg in arglist:
            if re.search("host1", arg, re.I):
                self.productversion = arg.split('=')[1]
                self.host1 = self._install(self.productversion,1)
            if re.search("host2", arg, re.I):
                self.productversion = arg.split('=')[1]
                self.host2 = self._install(self.productversion,2)
            if re.search("storageType", arg, re.I):
                self.storageList = arg.split('=')[1]
                if re.search("iscsi", self.storageList, re.I):
                    self.initialize(arglist)
                    self.iscsiInitiator =self.getXMLEntry("iscsiInitiator")
                    for h in [self.host1,self.host2]:
                        h.setIQN(self.iscsiInitiator)
    
    def _install(self, version ,id):
        oldproductVersion = xenrt.TEC().lookup("%s_PRODUCT_VERSION" % (version))
        oldversion = xenrt.TEC().lookup("%s_PRODUCT_INPUTDIR" % (version))
        host = xenrt.lib.xenserver.createHost(id=id,
                       version=oldversion,
                       productVersion=oldproductVersion)
        return host

class SetLACPSwitchSetup(xenrt.TestCase):

    def run(self, arglist):
        if len(arglist) < 2:
            raise xenrt.XRTError("Invalid number of arguments")
        # args must be of this format in the sequence file:
        # <arg>host=master</arg> 
        # <arg>2</arg> 
        xenrt.TEC().logverbose("LACP configuration on switch started")
        #The first argument contains the host reference ex: host=master or host=slave
        #Assumption: RESOURCE_HOST_0 will always be used for Test Complete setup.
        self.HOST_REF=arglist[0].split("=", 1)
        if self.HOST_REF[1] == "master":
            self.HOST_REF = "RESOURCE_HOST_1"
        elif self.HOST_REF[1] == "slave":
            self.HOST_REF = "RESOURCE_HOST_2"
        else:
            #The first argument contains the host reference ex: RESOURCE_HOST_0 OR RESOURCE_HOST_1 OR RESOURCE_HOST_2
            self.HOST_REF=arglist[0]
        #The second argument contains the number of NICs to be bonded
        self.NUMBER_NICS=int(arglist[1])
        #self.TYPE_OF_NETWORK = "NPRI"
        self.host = self.getHost(self.HOST_REF)
        
        #Remove existing bonds present on the network
        try:
            if len(self.host.getBonds()) > 0:
                for bond in self.host.getBonds():
                    self.host.removeBond(bond)
        except Exception, e:
            xenrt.TEC().warning("Caught exception in removing exising bond during SetLACPSwitchSetup operation: " + str(e))

        #Steps to configure LACP on switch
        self.bondInst=bonding._BondTestCase()
        self.pifs =self.bondInst.findPIFToBondWithManagementNIC(self.host,numberOfNics=self.NUMBER_NICS)
        self.switch = xenrt.lib.switch.createSwitchForPifs(self.host, self.pifs) 
        self.switch.setLACP()
        xenrt.TEC().logverbose("LACP configuration on switch completed")

class UnSetLACPSwitchSetup(xenrt.TestCase):

    def run(self, arglist):
        if len(arglist) < 1:
            raise xenrt.XRTError("Invalid number of arguments")
        # args must be of this format in the sequence file:
        # <arg>host=master</arg>  
        xenrt.TEC().logverbose("LACP deconfiguration on switch started")
        #The first argument contains the host reference ex: host=master or host=slave
        #Assumption: RESOURCE_HOST_0 will always be used for Test Complete setup.
        self.HOST_REF=arglist[0].split("=", 1)
        if self.HOST_REF[1] == "master":
            self.HOST_REF = "RESOURCE_HOST_1"
        elif self.HOST_REF[1] == "slave":
            self.HOST_REF = "RESOURCE_HOST_2"
        else:
            #The first argument contains the host reference ex: RESOURCE_HOST_0 OR RESOURCE_HOST_1 OR RESOURCE_HOST_2
            self.HOST_REF=arglist[0]

        self.PyMacRef = xenrt.PhysicalHost(xenrt.TEC().lookup(self.HOST_REF, self.HOST_REF))
        #Removing existing LACP settings from host
        xenrt.lib.switch.lacpCleanUp(self.PyMacRef.name)
        xenrt.TEC().logverbose("LACP deconfigured on switch")

class _InstallPreviousVersion(xenrt.TestCase):
    """Base class to install a build on the host to defined version"""
    BUILD = None
    VERSION = None
    
    def prepare(self, arglist):
        
        hosts = []
        if self.VERSION == "N-1":
            self.VERSION = xenrt.TEC().lookup("OLD_PRODUCT_VERSION1")
            self.BUILD = xenrt.TEC().lookup("OLD_PRODUCT_INPUTDIR1")
        else:
            self.VERSION = xenrt.TEC().lookup("OLD_PRODUCT_VERSION2")
            self.BUILD = xenrt.TEC().lookup("OLD_PRODUCT_INPUTDIR2")
        
        xenrt.TEC().logverbose("Installing host with the version %s" % self.VERSION)
        for i in range(1,3):
            host = xenrt.lib.xenserver.createHost(id="%d" % i, version=self.BUILD, productVersion=self.VERSION, withisos=True)
            hosts.append(host)
            host.checkVersion()
            self.getLogsFrom(host)
        
        #Create Demo Linux VM for GUI Tests
        xenrt.TEC().logverbose("Creating Demo Linux VM template on master server host for GUI Tests")
        template = xenrt.lib.xenserver.guest.createVMFromFile(hosts[0], "Demo Linux VM", "xe-phase-1/dlvm.xva")
        template.paramSet("is-a-template", "true")
    
    def run(self, arglist):
        pass
        
    
class TC19067(_InstallPreviousVersion):
    """ Installing Host N-1 version from current version via sequence file"""
    VERSION = "N-1"

class TC19068(_InstallPreviousVersion):
    """ Installing Host N-2 version from current version via sequence file"""
    VERSION = "N-2"

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
        
        # Check .NET3.5 framework is installed
        if self.guest.winRegLookup('HKLM', 'SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v3.5', 'Install', healthCheckOnFailure=False) != 1:
            raise xenrt.XRTFailure(".NET framework is not installed")
        
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
