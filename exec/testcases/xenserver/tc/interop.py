import xenrt, xenrt.util, xenrt.lib.xenserver, xenrt.rootops
import time, random, json, urllib
import os, re
import pprint
from xml.dom.minidom import Document
from xenrt.lazylog import step, comment, log

class TCPVSBVT(xenrt.TestCase):
    """ Base class for PVS BVT """

    """
    Test vars read in to the testConfig dictionary from sequence file:
    
    PXE_NETWORK: string, name of network created in prepare for PVS pxe/tftp
    SRV_DISTRO: var that is both distro indicator and vm name
    DEV_DISTRO: var that is both distro indicator and vm name
    
    PVS_BUILD_LOCATION: full path to PVS build location
    
    Test vars overloaded by the TC function:
    
    DEV_COUNT: int count of PVS client devices
    IMG_MODE: string that defines the PVS vDisk mode
    """
    
    DEV_COUNT = 1
    IMG_MODE = "private"

    def prepare(self, arglist):
        """Prepare function retrieves VMs built in the sequence 
        file, clones and configures a PVS server, a PVS master client, 
        and DEV_COUNT diskless PVS client devices"""
        
        # Read in test vars from the sequence file
        if not arglist:
            raise xenrt.XRTError("Test parameters not provided by sequence file")
        testConfig = dict(arglist[i].split("=") for i in range(len(arglist)))
        testConfig["PVS_BUILD_LOCATION"] = xenrt.TEC().lookup("PVS_BUILD_LOCATION")
        xenrt.TEC().logverbose("Test vars %s" % testConfig)
        
        # Set Win username and lookup password
        self.username = "Administrator"
        self.password = xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS", "ADMINISTRATOR_PASSWORD"])
        
        # Get ref to XS host
        self.host = self.getDefaultHost()
        xenrt.TEC().logverbose("Using host %s" % self.host)
        
        # Retreive all existing guests
        existingGuests = self.host.listGuests()
        xenrt.TEC().logverbose("Found guests %s" % existingGuests)
        
        # Check for an existing server VM and set the object if found
        if "PVSServer" in existingGuests:
            xenrt.TEC().logverbose("Found existing PVSServer VM")
            self.srv = self.host.getGuest("PVSServer")
            if not self.srv:
                self.srv = self.host.createGuestObject("PVSServer")
                self.srv.existing(self.host)
             
        else:
            # Get info on the server template VM
            xenrt.TEC().logverbose("Existing PVSServer VM not found")
            self.srvtpl = self.host.getGuest(testConfig["SRV_DISTRO"])
            if not self.srvtpl:
                raise xenrt.XRTError("Server template VM not found")
            
            # Create and start PVSServer from template
            if self.srvtpl.getState() != 'DOWN': self.srvtpl.shutdown()
            xenrt.TEC().logverbose("Creating PVSServer from template")
            self.srv = self.srvtpl.cloneVM(name="PVSServer")
            self.getLogsFrom(self.srv)
            self.configureServer(self.srv, testConfig)
            self.transferTestFiles(self.srv)
            self.setPSExecPolicy(self.srv)
            self.setPSCLR(self.srv, testConfig)
            
        # Check for an existing master client device VM and set the object if found
        if "vDiskMaster" in existingGuests:
            xenrt.TEC().logverbose("Found existing vDiskMaster VM")
            self.dev0 = self.host.getGuest("vDiskMaster")
            if not self.dev0:
                self.dev0 = self.host.createGuestObject("vDiskMaster")
                self.dev0.existing(self.host)
            
        else:
            # Get info on client device template VM
            xenrt.TEC().logverbose("Existing vDiskMaster VM not found")
            self.devtpl = self.host.getGuest(testConfig["DEV_DISTRO"])
            if not self.devtpl:
                raise xenrt.XRTError("Client device template VM not found")
            
            # Create and start vDiskMaster from template
            if self.devtpl.getState() != 'DOWN': self.devtpl.shutdown()
            xenrt.TEC().logverbose("Creating vDiskMaster from template")
            self.dev0 = self.devtpl.cloneVM(name="vDiskMaster")
            self.getLogsFrom(self.dev0)
            self.configureMasterClient(self.dev0, testConfig)
            self.transferTestFiles(self.dev0)
            self.setPSExecPolicy(self.dev0)
            self.setPSCLR(self.dev0, testConfig)
             
        # Delete stale client device clones
        for vm in [x for x in existingGuests if "PVSDevice" in x]:
            xenrt.TEC().logverbose("Deleting VM %s" % vm)
            vm = self.host.getGuest(vm)
            if vm.getState() != "DOWN": vm.shutdown()
            vm.uninstall()
        
        # Shutdown vDiskMaster for clone
        if self.dev0.getState() != "DOWN": self.dev0.shutdown()
        
        # Create diskless client device VMs
        self.clientDevices = self.createClientDeviceClones(self.dev0, self.DEV_COUNT)
        xenrt.TEC().logverbose("Created client devices %s" % self.clientDevices)
        
        # Verify key VMs are up and we have the correct IPs for xmlrpc
        pribridge = self.host.getPrimaryBridge()
        for vm in [self.srv, self.dev0]:
            if vm.getState() != 'UP': 
                vm.start(managebridge=pribridge)
            else:
                vm.start(reboot=True, managebridge=pribridge)
            
        # Modify the test case parameters file on PVSServer
        self.srv.hostname = self.srv.xmlrpcGetEnvVar('COMPUTERNAME')
        
        pxenet = self.host.parseListForOtherParam("network-list",
                                                  "name-label",
                                                  testConfig["PXE_NETWORK"],
                                                  "bridge")
        srvvifs = self.srv.getVIFs()    
        srvpxevif = [srvvifs[x][1] for x in srvvifs if pxenet in srvvifs[x]][0]
        
        filechanges = {}
        filechanges["deviceCount"] = self.DEV_COUNT
        filechanges["LicenseServer"] = self.srv.hostname
        filechanges["fqdn"] = self.srv.hostname
        filechanges["dbServer"] = self.srv.hostname
        filechanges["dbAdminUser"] = self.srv.hostname + "\\Administrator"
        filechanges["useADGroups"] = "false"
        filechanges["defaultAuthGroup"] = self.srv.hostname + "\\Administrators"
        filechanges["PVSStreamingIP"] = srvpxevif
        basedir = testConfig["PVS_BUILD_LOCATION"]
        prereqsdir = basedir + "\\Console\\ISSetupPrerequisites"
        
        filechanges["CTXLicLocation"] = basedir + "\\Licensing"
        filechanges["XDHostLocation"] = prereqsdir
        filechanges["XDBrokerLocation"] = prereqsdir
        filechanges["ConfigLocation"] = prereqsdir
        filechanges["ConfigLogLocation"] = prereqsdir
        filechanges["DelagatedAdminLocation"] = prereqsdir
        filechanges["DotNet4Location"] = prereqsdir
        filechanges["PVSCslLocation"] = basedir + "\\Console"
        filechanges["PVSSrvLocation"] = basedir + "\\Server"
        filechanges["pvsDeviceRoot"]  = basedir + "\\Device"
        
        
        xenrt.TEC().logverbose("Setting server parameters: %s" % filechanges)
        
        # Write changes to parameters file via PS
        for k,v in filechanges.iteritems():
            script = '''(Get-Content "c:\\pvs\\parameters.txt") | Foreach-Object\
            {$_ -replace "^%s=.+$", "%s=%s"} | Set-Content "c:\\pvs\\parameters.txt"''' % (k, k, v)
            self.srv.xmlrpcExec(script, powershell=True)
            self.dev0.xmlrpcExec(script, powershell=True)
        
        # PVS device cache type lookup table
        cachetable = {"private": 0, "standard": 3, "difference": 7}
        for id in [v for k,v in cachetable.iteritems() if self.IMG_MODE in k]:
            cachemode = id
         
        # Iterate through updating the parameters file for each client 
        # device via PS and a function in shared_functions.ps1
        n = 1
        for vm in [self.dev0] + self.clientDevices:
            vmvifs = vm.getVIFs()    
            pvsmac = [vmvifs[x][0] for x in vmvifs if pxenet in vmvifs[x]][0]
        
            filechanges = {}
            filechanges["deviceName"] = re.sub('[:]', '', pvsmac)
            filechanges["deviceMAC"] = pvsmac
            filechanges["devicevDiskName"] = "vdisk1"
            
            if vm == self.dev0:
                filechanges["bootFrom"] = "2"
                filechanges["writeCacheType"] = cachetable["private"]
            else:
                filechanges["bootFrom"] = "1"
                filechanges["writeCacheType"] = cachemode
                filechanges["Set-WriteCacheType"] = "-1"
                filechanges["Create-PVSDevice"] = "-1"
                filechanges["Assign-PVSDisk2Device"] = "-1"
                filechanges["Set-PVSDeviceBootFrom"] = "-1"
                
            section = "PVS Device%s" % n
            n = n+1
            
            xenrt.TEC().logverbose("Setting %s parameters: %s" % (section,filechanges))
            
            for k,v in filechanges.iteritems():
                script = '''. c:\\pvs\\shared_functions; Set-Parameter -configFile\
                c:\\pvs\\parameters.txt -section "%s" -key "%s" -newValue "%s"''' % (section, k, v)
                self.srv.xmlrpcExec(script, powershell=True)
                self.dev0.xmlrpcExec(script, powershell=True)
        
    def configureServer(self, vm, testConfig):
        """Main function to configure a PVS server"""
        
        # Shutdown VM if needed
        if vm.getState() != "DOWN": vm.shutdown()
        
        # Create a disk on server VM for vDisk storage, cache
        xenrt.TEC().logverbose("Creating a disk on PVSServer for vDisk storage")
        rawdisk = vm.createDisk(sizebytes=self.DEV_COUNT * 30 * xenrt.GIGA)
        
        # Reconfigure VIFs
        self.reconfigureVIFs(vm, testConfig)
        
        # Disable the firewall on PVSServer
        xenrt.TEC().logverbose("Disable firewall on PVSServer")
        vm.disableFirewall()
        
        # Format the raw disk for vDisk storage
        xenrt.TEC().logverbose("Formatting disk for vDisk storage")
        storedisk = vm.xmlrpcPartition(rawdisk)
        vm.xmlrpcFormat(storedisk, quick=True, timeout=1200)
        
        # Retrieve VIF information for DHCP server install
        pxenet = self.host.parseListForOtherParam("network-list",
                                                  "name-label",
                                                  testConfig["PXE_NETWORK"],
                                                  "bridge")
        vmvifs = vm.getVIFs()
        pvsvif = [x for x in vmvifs if pxenet in vmvifs[x]][0]
        
        # Install DHCP server, configure for PVS VIF
        xenrt.TEC().logverbose("Installing DHCP server on PVSServer pxe network VIF")
        vm.installWindowsDHCPServer(pvsvif)

        # Get PVSServer hostname via xmlrpc
        self.hostname = vm.xmlrpcGetEnvVar('COMPUTERNAME')

        # Install SQLExpress
        xenrt.TEC().logverbose("Installing SQLExpress on PVSServer")
        if float(vm.xmlrpcWindowsVersion().strip()) >= 6.0:
            xenrt.TEC().logverbose("Installing .NET and disabling Windows password complexity check")
            vm.xmlrpcExec("ServerManagerCmd.exe -install NET-Framework")
            vm.disableWindowsPasswordComplexityCheck()
        self.sqlinstance = 'SQLEXPRESS'
        xenrt.TEC().logverbose("Installing SQLExpress instance %s" % self.sqlinstance)
        vm.installSQLServer2005(extraArgs = \
                                    "DISABLENETWORKPROTOCOLS=0 "
                                    "ADDLOCAL=SQL_Engine SAPWD=%s "
                                    "SQLACCOUNT=%s SQLPASSWORD=%s "
                                    "SECURITYMODE=SQL SAPWD=%s" %
                                    (self.password, self.hostname + "\\" + self.username,
                                    self.password, self.password))
        xenrt.TEC().logverbose("SQLExpress installed, accounts added, TCP/IP and named pipes enabled")
        
        # Install dotNet 3.5 and 4.0 on PVSServer
        xenrt.TEC().logverbose("Installing dotNet 3.5 on PVSServer")
        vm.installDotNet35()
        xenrt.TEC().logverbose("Installing dotNet 4.0 on PVSServer")
        vm.installDotNet4()

        # Install PowerShell 2.0 on PVSServer
        xenrt.TEC().logverbose("Installing PowerShell 2.0 on PVSServer")
        vm.installPowerShell20()
        vm.enablePowerShellUnrestricted()
    
    def configureMasterClient(self, vm, testConfig):
        """Main function to configure a PVS master client device"""
        
        # Shutdown VM if needed
        if vm.getState() != "DOWN": vm.shutdown()
        
        # Reconfigure VIFs
        self.reconfigureVIFs(vm, testConfig)
        
        # Disable the firewall on vDiskMaster
        xenrt.TEC().logverbose("Disable firewall on %s" % vm)
        vm.disableFirewall()
        
        # Install dotNet 4.0 on vDiskMaster
        xenrt.TEC().logverbose("Installing dotNet 4.0 on %s" % vm)
        vm.installDotNet4()
        
    def reconfigureVIFs(self, vm, testConfig):
        """Remove all VIFs and reconfigure as:
           eth0 - PVS PXE network
           eth1 - Primary XenRT bridge for xmlrpc
           
           Then update the XenRT management bridge"""
                
        # Shutdown VM if needed
        if vm.getState() != 'DOWN': vm.shutdown()
        
        # Remove all VIFs
        for vif in vm.getVIFs():
            xenrt.TEC().logverbose("Removing VIF %s from %s" % (vif,vm))
            vm.removeVIF(vif)
            
        # Find the PXE network bridge and add as "eth0" 
        pxebridge = self.host.parseListForOtherParam("network-list",
                                                      "name-label",
                                                      testConfig["PXE_NETWORK"],
                                                      "bridge")
        vm.createVIF("eth0", bridge=pxebridge)
        
        # Find the primary bridge and add as "eth1"
        pribridge = self.host.getPrimaryBridge()
        vm.createVIF("eth1", bridge=pribridge)
        time.sleep(30)
        
        # Start the VM
        vm.lifecycleOperation("vm-start")
        vm.poll("UP")
        
        # Wait for the VM to settle
        time.sleep(120)
        
        # Reboot the VM and update the management bridge
        xenrt.TEC().logverbose("Updating the management bridge")
        vm.start(reboot=True, managebridge=pribridge)
        xenrt.TEC().logverbose("Completed VIF config")
    
    def createClientDeviceClones(self, vm, count):
        """Create count PVSDeviceX's; diskless, set to PXE"""
        xenrt.TEC().logverbose("Creating %s client device clones" % count)
        devn = []
        for i in range(count):
            devx = vm.cloneVM(name="PVSDevice" + str(i+1))
            self.uninstallOnCleanup(devx)
            devx.paramSet("HVM-boot-params-order", "ncd")
            for d in devx.listDiskDevices(): devx.removeDisk(d)
            devn.append(devx)
        return devn
    
    def transferTestFiles(self, vm, dst="c:\\pvs"):
        """Recursively transfer the PVS test directory via xmlrpc"""
        xenrt.TEC().logverbose("Starting file transfer")
        src = "%s/data/tests/pvs" % (xenrt.TEC().lookup("XENRT_BASE"))
        vm.xmlrpcSendRecursive(src, dst)
        xenrt.TEC().logverbose("File transfer complete")
        
    def setPSCLR(self, vm, testConfig):    
        """Set the PS CLR based on the PVS build number"""
        xenrt.TEC().logverbose("Setting PS CLR on %s" % vm)
        script = "powershell.exe c:\\pvs\\set_clr_4.ps1 -ExecutionPolicy ByPass"
        data = vm.xmlrpcExec(script, returndata=True, timeout=3600)
        if "Exception" in data:
            raise xenrt.XRTError("Failed to run %s %s" % (script, data))
        xenrt.TEC().logverbose("PS CLR set %s" % (data))
        
    def setPSExecPolicy(self, vm):
        """Set the PS execution policy as unrestricted via xmlrpc"""
        xenrt.TEC().logverbose("Setting PS execution policy as unrestricted on %s" % vm)
        vm.xmlrpcExec('powershell.exe -Command "Set-ExecutionPolicy Unrestricted"')
        
    def run(self, arglist):
        """Main run function, controls the three test scripts:
           setup_pvs_server.ps1
           setup_pvs_client.ps1
           setup_pvs_server2.ps1
           
           Vars are read from parameters.txt, which is modified in the prepare
           
           All test files can be found in xenrt.hg/data/tests/pvs"""
        
        # Run the first server test script
        step("Run PVS server test script 1 (1 of 5)")
        
        script = "powershell.exe -ExecutionPolicy ByPass -File c:\\pvs\\setup_pvs_server.ps1"
        data = self.srv.xmlrpcExec(script, returndata=True, timeout=3600)
        if "Exception" in data:
            raise xenrt.XRTFailure("Failure: failed to run %s %s" % (script, data))
        xenrt.TEC().logverbose("Results: %s" % data)
        
        # Once the server scripts is done, run the client script
        step("Run PVS client test script part 1 (2 of 5)")
        
        script = "powershell.exe -ExecutionPolicy ByPass -File c:\\pvs\\setup_pvs_client.ps1 1"
        data = self.dev0.xmlrpcExec(script, returndata=True, timeout=3600)
        if "Exception" in data:
            raise xenrt.XRTFailure("Failure: failed to run %s %s" % (script, data))
        xenrt.TEC().logverbose("Results: %s" % data)
        
        xenrt.TEC().logverbose("Changing the boot order on client 1, rebooting")
            
        # Set client device boot order
        self.dev0.paramSet("HVM-boot-params-order", "ncd")
        
        # Once client script part 1 installs the device software, run part 2 to image
        step("Run PVS client test script part 2 (3 of 5)")
        
        # Reboot the client twice to finalize driver installs, etc.
        for i in range(2):
            self.dev0.start(reboot=True, extratime=True)
            if self.dev0.getState() != "UP": 
                raise xenrt.XRTFailure("The VM did not boot properly (reboot #%s)" % (i+1))
                
        script = "powershell.exe -ExecutionPolicy ByPass -File c:\\pvs\\setup_pvs_client.ps1 1"
        data = self.dev0.xmlrpcExec(script, returndata=True, timeout=3600)
        if "Exception" in data:
            raise xenrt.XRTFailure("Failure: failed to run %s %s" % (script, data))
        xenrt.TEC().logverbose("Results: %s" % data)
            
        # Shutdown the client and prepare for the next step
        self.dev0.shutdown()
        
        # Once client script is finished, run the second server script
        step("Run PVS server test script 2 (4 of 5)")
        
        script = "powershell.exe -ExecutionPolicy ByPass -File c:\\pvs\\setup_pvs_server2.ps1"
        data = self.srv.xmlrpcExec(script, returndata=True, timeout=3600)
        if "Exception" in data:
            raise xenrt.XRTFailure("Failure: failed to run %s %s" % (script, data))
        xenrt.TEC().logverbose("Results: %s" % data)
        
        # Once second server script is finished, boot VMs via XRT and verify no BSOD
        step("Verify results (5 of 5)")
        
        pribridge = self.host.getPrimaryBridge()
        for vm in self.clientDevices:
            vm.start(extratime=True, managebridge=pribridge)
            if not vm.xmlrpcIsAlive():
                raise xenrt.XRTFailure("Client device %s boot to vDisk failed" % vm)
            xenrt.TEC().logverbose("%s boot to vDisk successful" % vm)
        
        for vm in self.clientDevices:
            vm.shutdown()
        
        # Retrieve the server and client log dirs
        self.dev0.paramSet("HVM-boot-params-order", "c")
        self.dev0.start()
        for vm in [self.srv, self.dev0]:
            ldir = "%s/%s/%s" % (xenrt.TEC().getLogdir(),self.IMG_MODE,vm)
            if not os.path.exists(ldir): os.makedirs(ldir)
            xenrt.TEC().logverbose("Retrieving %s logs" % vm)
            vm.xmlrpcFetchRecursive("c:\\pvs\\logs", ldir)
        
class TC10842(TCPVSBVT):
    DEV_COUNT = 1
    IMG_MODE = "private"
    
class TC10843(TCPVSBVT):
    DEV_COUNT = 2
    IMG_MODE = "standard"
    
class TC10844(TCPVSBVT):
    DEV_COUNT = 2
    IMG_MODE = "difference"
    
# class TC10845(TCPVSBVT):

# class TC10846(TCPVSBVT):
    
# class TC10847(TCPVSBVT):

class TCXdAsfSetup(xenrt.TestCase):

    XD_SVC_ACCOUNT_USERNAME = 'ENG\\svc_testautomation'
    XD_SVC_ACCOUNT_PASSWORD = 't41ly.h13Q1'
    XD_DOWNLOADS_PATH = '\\\\eng.citrite.net\\global\\layouts\\cds'

    ASF_NETWORK_NAME = 'AutoBVT2'
    ASF_WORKING_DIR = 'c:\\asf'

    def importXVAs(self, host, version, templates=False):
        # Import XVAs
        xvaMount = '/tmp/xd_xvas'
        nfsXdXvas = xenrt.TEC().lookup("XD_XVA_SOURCE_NFS", None)
        if not nfsXdXvas:
            raise xenrt.XRTError("XD_XVA_SOURCE_NFS not defined")

        host.execdom0("mkdir -p %s" % (xvaMount))
        host.execdom0("mount %s %s" % (nfsXdXvas, xvaMount))
        
        pathToXvas = os.path.join(xvaMount, version)
        if templates:
            pathToXvas = os.path.join(pathToXvas, 'templates')

        xvas = host.execdom0("ls %s" % (os.path.join(pathToXvas, '*.xva'))).split()
        xenrt.TEC().logverbose("Found xvas: %s in %s" % (",".join(xvas), pathToXvas))
        xvaUUIDList = []
        for xva in xvas:
            xenrt.TEC().logverbose("Importing file %s..." % (os.path.basename(xva)))
            uuid = host.execdom0("xe vm-import filename=%s" % (xva), timeout=3600).strip()

            xvaUUIDList.append(uuid)

        host.execdom0("umount %s" % (xvaMount))
        templateInfo = host.parameterList(command='template-list', params=['uuid', 'name-label'])
        return filter(lambda x:x['uuid'] in xvaUUIDList, templateInfo)

    def createInfrastructureVMs(self, host, templateList):
        cli = host.getCLIInstance()
        guestDict = {}
        for template in templateList:
            vmName = template['name-label'].lstrip('_')
            xenrt.TEC().logverbose('Create new guest %s from template %s' % (vmName, template['uuid']))
            guest = host.guestFactory()(name=vmName, host=host)
            guest.uuid = cli.execute('vm-install', 'template-uuid=%s new-name-label=%s' % (template['uuid'], vmName), strip=True)
            guest.start()
            guestDict[guest.name] = guest

        return guestDict

    def executeASFShellCommand(self, asfCont, command, csvFormat=False, timeout=300, netUse=False):
        csvFormatStr = csvFormat and '| convertto-csv' or ''
        netUseCommand = netUse and 'net use %s /user:%s %s /persistent:yes; ' % (self.XD_DOWNLOADS_PATH, self.XD_SVC_ACCOUNT_USERNAME, self.XD_SVC_ACCOUNT_PASSWORD) or ''
        commandStr = '%scd %s; Import-Module asf; echo "xrtretdatastart"; %s %s; echo "xrtretdataend"' % (netUseCommand,self.ASF_WORKING_DIR, command, csvFormatStr)
        rValue = asfCont.xmlrpcExec(commandStr, powershell=True, returndata=True, timeout=timeout).splitlines()
        rData = []
        storeLines = False
        finished = False 
        for line in rValue:
            if line == 'xrtretdataend':
                if not storeLines: raise xenrt.XRTError('ASF Test controller response invalid: End tag before start tag')
                finished = True
                break

            if storeLines: rData.append(line)
            if line == 'xrtretdatastart':
                if storeLines: raise xenrt.XRTError('ASF Test controller response invalid: Multiple start tags')
                storeLines = True

        if not finished: raise xenrt.XRTError('ASF Test controller response invalid: End tag not found')
        return rData            

    def executePowershellASFCommand(self, asfCont, command, netUse=False, returndata=False, timeout=60):
        commandfilename = "%s\\xenrtasfps.cmd" % (self.ASF_WORKING_DIR)
        netUseCommand = netUse and 'net use %s /user:%s %s /persistent:yes;' % (self.XD_DOWNLOADS_PATH, self.XD_SVC_ACCOUNT_USERNAME, self.XD_SVC_ACCOUNT_PASSWORD) or ''
        fileData = """cd %s
%s
powershell %s""" % (self.ASF_WORKING_DIR, netUseCommand, command)
        asfCont.xmlrpcWriteFile(filename=commandfilename, data=fileData)

        returnerror = True
        returnrc = False
        if not returndata:
            returnerror=False
            returnrc = True

        rData = asfCont.xmlrpcExec(commandfilename, desc='XenRT ASF Command',
                                   returndata=returndata, returnerror=returnerror, returnrc=returnrc,
                                   timeout=timeout)

        return rData


    def configureAsfController(self, asfCont, xdVersion, host):
        asfRepository = xdVersion
        asfRepositoryPath = "\\\\eng.citrite.net\\global\\Builds\\Automation\\Tests\\XD"
        testSuites = ['Common', 'TestApi', 'LayoutBvts']

        # Install tests
        # Temporary workaround for a false positive from the GSO virus scanner
        data = asfCont.xmlrpcReadFile("C:\\ASF\\environment\\SAL\\TestManager\\TestManager.psm1")
        asfCont.xmlrpcExec("attrib -r C:\\ASF\\environment\\SAL\\TestManager\\TestManager.psm1")
        asfCont.xmlrpcRemoveFile("C:\\ASF\\environment\\SAL\\TestManager\\TestManager.psm1")
        asfCont.xmlrpcWriteFile("C:\\ASF\\environment\\SAL\\TestManager\\TestManager.psm1", data.replace("\"release.txt\"", "\"release.txt\",\"Install-Tools.ps1\""))

        rData = self.executeASFShellCommand(asfCont, 'Install-Tests -Repository %s -TestRepositoryPath %s -TestSuites %s -UserName %s -Password %s' % (asfRepository, asfRepositoryPath, ','.join(testSuites), self.XD_SVC_ACCOUNT_USERNAME, self.XD_SVC_ACCOUNT_PASSWORD), timeout=600)

        map(lambda x:xenrt.TEC().logverbose(x), rData)

        self.executeASFShellCommand(asfCont, 'New-AsfHypervisor -HypName %s -Url http://%s -Username root -Password %s -Network %s' % (host.getName(), host.getIP(), host.password, self.ASF_NETWORK_NAME))
        self.executeASFShellCommand(asfCont, 'Import-AsfTemplateFromHypervisor -HypName %s | Add-AsfHypervisorTemplate -HypName %s' % (host.getName(), host.getName()))

        # Get Client, DDC and VDA templates
        val = self.executeASFShellCommand(asfCont, 'Get-AsfHypervisorTemplate -HypName %s' % (host.getName()), csvFormat=True)
        templateData = map(lambda x:x.replace('"', '').split(','), val)
        templateList = map(lambda x:dict(zip(templateData[1], x)), templateData[2:])
        xenrt.TEC().logverbose('ASF Hypervisor Template list:\n' + pprint.pformat(templateList))

        clientTemplates = filter(lambda x:x['HypName'] == host.getName() and not x['TemplateName'].startswith('__') and x['ClientOs'] == 'True', templateList)
        xenrt.TEC().logverbose('Using Client Templates: %s' % (map(lambda x:x['OSName'].strip(), clientTemplates)))
        serverTemplates = filter(lambda x:x['HypName'] == host.getName() and not x['TemplateName'].startswith('__') and not x['TemplateName'].startswith('ASF') and x['ServerOs'] == 'True', templateList)
        xenrt.TEC().logverbose('Using Server Templates: %s' % (map(lambda x:x['OSName'].strip(), serverTemplates)))

        # Temporary workaround for ENG DFS issues
        data = asfCont.xmlrpcReadFile("C:\\asf\\tests\\layoutbvts\\xenserver\\setup.ps1")
        asfCont.xmlrpcExec("attrib -r C:\\asf\\tests\\layoutbvts\\xenserver\\setup.ps1")
        asfCont.xmlrpcRemoveFile("C:\\asf\\tests\\layoutbvts\\xenserver\\setup.ps1")
        asfCont.xmlrpcWriteFile("C:\\asf\\tests\\layoutbvts\\xenserver\\setup.ps1", data.replace("Install-SAL", "Install-SAL -RepositoryPath \"\\\\eng.citrite.net\\global\\Builds\\automation\\SAL\" -UserName %s -Password %s" % (self.XD_SVC_ACCOUNT_USERNAME, self.XD_SVC_ACCOUNT_PASSWORD)))

        self.executeASFShellCommand(asfCont, 'c:\\asf\\tests\\layoutbvts\\xenserver\\setup.ps1 -ClientTemplate %s -DdcTemplate %s -VdaTemplates %s' % (clientTemplates[0]['TemplateName'], serverTemplates[0]['TemplateName'], clientTemplates[0]['TemplateName']))

        # Temp - workaround
        asfCont.xmlrpcExec('copy c:\\asf\\bin\\JonasCntrl.dll c:\\asf')

        patchStr = ''
        patchList = host.parameterList('patch-list', params=['name-label'])
        if len(patchList) > 0:
            patchList.sort()
            try:
                latestPatchNumber = int(re.search('XS\d+E(\d+)$', patchList[-1]['name-label']).group(1))
                patchStr = '+HFX%d' % (latestPatchNumber)
            except Exception, e:
                xenrt.TEC().logverbose('Unrecognised patch format: %s' % (patchList[-1]['name-label']))
                patchStr = '+HFX%s' % (patchList[-1]['name-label'])
                
        versionStr = host.productRevision + patchStr
        self.executeASFShellCommand(asfCont, 'Set-AsfBuildConfig -BuildId XenServer -BuildNumber %s' % (versionStr))

        if xenrt.TEC().lookup("DOUBLE_ASF_TIMEOUTS", False, boolean=True):        
            filename = "%s\\bin\\RegressionSuite.exe.config" % (self.ASF_WORKING_DIR)
            fileData = asfCont.xmlrpcReadFile(filename=filename)
            newFileData = re.sub('<add key="TIMEOUT_SCALE_FACTOR" value=".*"',
                                 '<add key="TIMEOUT_SCALE_FACTOR" value="%d"' % (2), fileData)
            asfCont.xmlrpcWriteFile(filename=filename, data=newFileData)

        map(lambda x:xenrt.TEC().logverbose(x), self.executeASFShellCommand(asfCont, 'Show-AsfConfig'))

    def configureInfrastructureVMs(self, host, infraGuests):
        infraGuests['ASFDC1'].waitForAgent(300)
        infraGuests['ASFDC1'].enlightenedDrivers = True
        infraGuests['ASFDC1'].shutdown()

        infraGuests['ASFController'].waitForAgent(300)
        infraGuests['ASFController'].tailored = True
        infraGuests['ASFController'].existing(host)
        xenrt.TEC().logverbose('ASFController: IP=%s, windows=%s, enlightenedDrivers=%s' % (infraGuests['ASFController'].mainip, infraGuests['ASFController'].windows, infraGuests['ASFController'].enlightenedDrivers))

        self.getLogsFrom(infraGuests['ASFController'])

        if xenrt.TEC().lookup("DISABLE_IPV6_XOP440", False, boolean=True):
            infraGuests['ASFController'].disableIPv6(reboot=False)

        # Install latest drivers
        if not infraGuests['ASFController'].pvDriversUpToDate():
            xenrt.TEC().comment('Upgrading out-of-date drivers')
            infraGuests['ASFController'].installDrivers()
        infraGuests['ASFController'].reboot()

        # Start the DC after PV driver upgrade on the Controller to work around problems seen in CA-122684
        infraGuests['ASFDC1'].start() 

    def executeAsfTests(self, asfCont):
        try:
            command = """$rc = @(Invoke-AsfWorkflow -NewWindow)
$rc = $rc[$rc.Length-1]
Write-Host "Invoke-AsfWorkflow exited: $rc"

if ($rc -ne 0){
    try {
        $errorReason = Get-AsfFailureMessage $rc
    } catch {}
    Throw "Invoke-AsfWorkflow : $rc - $errorReason"
}
return $rc
"""
            result = self.executeASFShellCommand(asfCont, command.replace("\n","; "), timeout=60*60*3, netUse=True)
            xenrt.TEC().comment('ASF Test Returned Result: %s' % (result))
        except Exception, e:
            xenrt.TEC().comment('ASF Test Returned Exception: %s' % (e))
        
        globalLogPath = self.getBasicAsfLogs(asfCont)
        self.checkAsfTestVerdict(globalLogPath)


    def createVDATemplatesFromGuests(self, host, bvtNetworkUUID):
        cli = host.getCLIInstance()
        uuidList = []
        for guestName in host.listGuests():
            xenrt.TEC().logverbose('Converting guest: %s to VDA template' % (guestName))
            guest = host.getGuest(guestName)

            # Add the XD startup script to the guest
            guest.xmlrpcCreateDir("c:\\bootstrap")
            if xenrt.TEC().lookup("DISABLE_NEW_ASF_DISCOVERY", False, boolean=True):
                guest.xmlrpcSendFile("%s/utils/xd_iop_startup.cmd" %
                                     (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")),
                                     "c:\\bootstrap\\StartupTasks.cmd") 
            else:
                guest.xmlrpcSendFile("%s/xdasf/Start-AsyncAsfDiscovery.ps1" %
                                     (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")),
                                     "c:\\bootstrap\\Start-AsyncAsfDiscovery.ps1")
                guest.xmlrpcSendFile("%s/xdasf/StartupTasks.cmd" %
                                     (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")),
                                     "c:\\bootstrap\\StartupTasks.cmd")

            guest.winRegAdd("HKLM",
                            "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\"
                            "Run",
                            "bvtbootstrap",
                            "SZ",
                            "c:\\bootstrap\\StartupTasks.cmd")

            guest.xmlrpcExec("net user Administrator tally.h0")
            guest.winRegAdd("HKLM",
                            "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\"
                            "Winlogon",
                            "DefaultUserName",
                            "SZ",
                            "Administrator")
            guest.winRegAdd("HKLM",
                            "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\"
                            "Winlogon",
                            "DefaultPassword",
                            "SZ",
                            "tally.h0")

            guest.disableFirewall()
            guest.xmlrpcExec('powershell.exe Set-ExecutionPolicy Unrestricted')

            if xenrt.TEC().lookup("DISABLE_IPV6_XOP440", False, boolean=True):
                guest.disableIPv6(reboot=False)

            guest.shutdown()
            guest.poll("DOWN")
            guest.paramSet("is-a-template", "true")

            # Destroy all existing VIFs
            vuuids = host.minimalList("vif-list", "uuid", "vm-uuid=%s" % (guest.uuid))
            for vuuid in vuuids:
                cli.execute("vif-destroy", "uuid=%s" % (vuuid))

            # Create a VIF on the AutoBVT network
            cli.execute("vif-create", "vm-uuid=%s network-uuid=%s device=0 mac=%s" % (guest.uuid, bvtNetworkUUID, xenrt.randomMAC()))

            bvtVIFs = guest.getVIFs(network=self.ASF_NETWORK_NAME)
            if bvtVIFs.keys():
                xenrt.TEC().logverbose("Found %d BVT VIFs" % (len(bvtVIFs.keys())))
                for key in bvtVIFs.keys():
                    xenrt.TEC().logverbose("BVT VIF: %s" % (",".join(bvtVIFs[key])))
            else:
                raise xenrt.XRTFailure("BVT network (%s) not found" % (self.BVT_NETWORK))

            uuidList.append(guest.getUUID())

        templateInfo = host.parameterList(command='template-list', params=['uuid', 'name-label'])
        return filter(lambda x:x['uuid'] in uuidList, templateInfo)

    def getBasicAsfLogs(self, asfCont):
        logsubdir = "%s/xdasf" % (xenrt.TEC().getLogdir())
        if not os.path.exists(logsubdir):
            os.makedirs(logsubdir)

        asfLogSrcDir = "%s\\Reports" % (self.ASF_WORKING_DIR)
        logDirList = asfCont.xmlrpcGlobpath("%s\\*\\*" % (asfLogSrcDir))
        # Remove self test dir
        logDirList = filter(lambda x:'SelfTest' not in x, logDirList)
        if not len(logDirList) == 1:
            xenrt.TEC().warning('Could not find unique ASF results directory')
        asfResultsDir = logDirList[0]
        xenrt.TEC().logverbose('Using ASF Results Path: %s' % (asfResultsDir))
        asfLogFilePath = '%s\\GlobalLog.txt' % (asfResultsDir)
        asfCont.xmlrpcGetFile2(asfLogFilePath, os.path.join(logsubdir, 'GlobalLog.txt'))

        return os.path.join(logsubdir, 'GlobalLog.txt')

    def checkAsfTestVerdict(self, globalLogPath):
        try:
            fh = open(globalLogPath)
        except Exception, e:
            raise xenrt.XRTError('XD Layout BVT not executed - see starttestenv.log for details')

        asfGlobalLogData = fh.readlines()
        fh.close()
        resultData = filter(None, map(lambda x:re.search('FINAL TEST RESULT - (.*):', x), asfGlobalLogData))
        if len(resultData) == 0:
            raise xenrt.XRTError('No ASF test verdicts found')
        if len(resultData) > 1:
            raise xenrt.XRTError('Multiple ASF test verdicts found')

        if resultData[0].group(1) == 'PASS':
            return
        elif resultData[0].group(1) == 'FAIL':
            raise xenrt.XRTFailure('XD Layout BVT failed')
        else:
            raise xenrt.XRTError('Unknown ASF test verdict: %s' % (resultData[0].group(1)))


    def run(self, arglist):
        host = self.getDefaultHost()

        networkInfo = host.parameterList('network-list', ['name-label', 'uuid'])
        bvtNetwork = filter(lambda x:x['name-label'] == self.ASF_NETWORK_NAME, networkInfo)
        if len(bvtNetwork) == 0:
            self.bvtNetworkUUID = host.createNetwork(name=self.ASF_NETWORK_NAME)
        else:
            self.bvtNetworkUUID = bvtNetwork[0]['uuid'] 

        self.createVDATemplatesFromGuests(host, self.bvtNetworkUUID)

        version = host.checkVersion(versionNumber=True)
        # Run trunk against Clearwater templates
        if host.productVersion == 'Creedence' or host.productVersion == 'Dundee' or host.productVersion == 'Cream':
            xenrt.TEC().warning('Using Clearwater Templates for trunk, Creedence and Cream')
            version = '6.2.0'

        if not xenrt.TEC().lookup("EXISTING_TEMPLATES", False, boolean=True):
            infraTemplateList = self.importXVAs(host, version)

class TCXsXdBvt(TCXdAsfSetup):

    def prepare(self, arglist):
        args = self.parseArgsKeyValue(arglist)
        xdVersion = 'MerlinCloud'
        if args.has_key('xdVersion'):
            xdVersion = args['xdVersion']
            xenrt.TEC().logverbose('Using XenDesktop version: %s' % (xdVersion))

        self.host = self.getDefaultHost()

        templateInfo = self.host.parameterList(command='template-list', params=['uuid', 'name-label'])
        infraTemplateList = filter(lambda x:x['name-label'].startswith('__'), templateInfo)
        self.infraGuests = self.createInfrastructureVMs(self.host, infraTemplateList)
        self.configureInfrastructureVMs(self.host, self.infraGuests)
        self.configureAsfController(self.infraGuests['ASFController'], xdVersion, self.host)

    def run(self, arglist):
        self.executeAsfTests(self.infraGuests['ASFController'])

    def postRun(self):
        # Clean-up any leftover VMs - not all VMs are XenRT controlled so not able to use standard XenRT guest methods
        vmStateData = self.host.parameterList(command='vm-list', params=['uuid', 'name-label', 'power-state'], argsString='is-control-domain=false')
        xenrt.TEC().logverbose("VMs to clean up:\n" + pprint.pformat(vmStateData))
        cli = self.host.getCLIInstance()
        for vmData in vmStateData:
            if vmData['power-state'] != 'halted':
                cli.execute('vm-shutdown uuid=%s --force' % (vmData['uuid']))
            cli.execute('vm-uninstall uuid=%s --force' % (vmData['uuid']))

class TCXenConvert(xenrt.TestCase):
    DISTRO = "w2k3eesp2-x64"
    VCPUS = 2
    MEMORY = 2048
    ROOTDISK = 34816
    LOGSDIR = "C:\\ProgramData\\Citrix\\XenConvert"
    VERSION = 25
    
    def installXenConvert(self, guest):
        
        if float(guest.xmlrpcWindowsVersion()) > 5.99:
            # Copy PVS test certificate and install
            
            guest.xmlrpcSendFile("%s/data/certs/ctxpvsdrv.cer" % (xenrt.TEC().lookup("XENRT_BASE")), "c:\\ctxpvsdrv.cer")
            
            # Get non expired cert
            #guest.xmlrpcFetchFile("http://rdm-inf-web1.rdm.xensource.com/misc/software/xenconvert/ctxpvsdrv.cer", "c:\\ctxpvsdrv.cer")
            
            # Install cert
            guest.xmlrpcExec("c:\\certmgr.exe /add c:\\ctxpvsdrv.cer /s /r localmachine trustedpublisher")

        # Now install XenConvert
        
        # Current installer in distmaster is outdated
        #guest.xmlrpcUnpackTarball("%s/xenconvert.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")
        
        guest.xmlrpcExec("mkdir C:\\xenconvert\\%s" % self.VERSION)
        if guest.xmlrpcGetArch() == "amd64":  
            if self.VERSION == 25:
                # Get updated installer
                guest.xmlrpcFetchFile("http://rdm-inf-web1.rdm.xensource.com/misc/software/xenconvert/2.5/XenConvert_Install_x64.exe", "c:\\xenconvert\\%s\\XenConvert_Install_x64.exe" % self.VERSION)
            if self.VERSION == 24:
                guest.xmlrpcUnpackTarball("%s/xenconvert.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")
            installer = "xenconvert\\%s\\XenConvert_Install_x64.exe" % (self.VERSION)
        else:
            if self.VERSION == 25:
                # Get updated installer
                guest.xmlrpcFetchFile("http://rdm-inf-web1.rdm.xensource.com/misc/software/xenconvert/2.5/XenConvert_Install.exe", "c:\\xenconvert\\%s\\XenConvert_Install.exe" % self.VERSION)
            if self.VERSION == 24:
                guest.xmlrpcUnpackTarball("%s/xenconvert.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")
            installer = "xenconvert\\%s\\XenConvert_Install.exe" % (self.VERSION)

        guest.xmlrpcExec("c:\\%s /S /v/qn" % installer)
    
    def run(self, arglist):
        guestName = self.DISTRO
        xcImportName = "XenConvertImport" + guestName
        host = self.getDefaultHost()
        template = xenrt.lib.xenserver.getTemplate(host, self.DISTRO)
        
        guest = host.guestFactory()(guestName, template, host)
        guest.setVCPUs(self.VCPUS)
        guest.setMemory(self.MEMORY)
        self.uninstallOnCleanup(guest)
        
        # Install guest OS
        guest.install(host,
                      distro=self.DISTRO,
                      isoname=xenrt.DEFAULT,
                      notools=False,
                      rootdisk=self.ROOTDISK,
                      sr=host.lookupDefaultSR())
        
        
        guest.installDotNet4()
        guest.installCitrixCertificate()
        guest.installDrivers()
        
        try:
            
            self.installXenConvert(guest)
            xenrt.TEC().logverbose("XenConvert installed")
            
            # Run XenConvert P2V
            guest.xmlrpcExec("\"c:\\Program Files\\Citrix\\XenConvert\\XenConvert.exe\" "
                               "P2XenServer "
                               + xcImportName +
                               " C:\\ "
                               + (host.getIP()) +
                               " root "
                               "xensource "
                               "C:\\",
                               timeout=28800)
            xenrt.TEC().logverbose("XenConvert import completed")
        
        finally:
            
            guest.xmlrpcExec("dir /S C:\\ > C:\\Files.txt", timeout=1200)
            guest.xmlrpcGetFile("C:\\Files.txt", xenrt.TEC().getLogdir() + "/Files.txt")
            
            if guest.xmlrpcDirExists(self.LOGSDIR):
                guest.xmlrpcFetchRecursive(self.LOGSDIR, xenrt.TEC().getLogdir())

        # Shutdown source VM
        # For XP, force shutdown required
        if self.DISTRO == "winxpsp3":
            guest.shutdown(force=True)
        else:
            guest.shutdown()
        
        xcimport = host.guestFactory()(xcImportName, template, host)
        self.uninstallOnCleanup(xcimport)
        xcimport.start()
        time.sleep(300)
        xcimport.reboot()
        time.sleep(300)
        xcimport.existing(host)
        xcimport.check()
        

class TC15472(TCXenConvert):
    """XenConvert 2.5 P2V Interop Test using w2k3eesp2-x64"""
    DISTRO = "w2k3eesp2-x64"
    LOGSDIR = "C:\\Documents and Settings\\All Users\\Application Data\\Citrix\\XenConvert"
    VERSION = 25

class TC17648(TCXenConvert):
    """XenConvert 2.5 P2V Interop Test using w2k3eesp2"""
    DISTRO = "w2k3eesp2"
    LOGSDIR = "C:\\Documents and Settings\\All Users\\Application Data\\Citrix\\XenConvert"
    VERSION = 25

class TC15474(TCXenConvert):
    """XenConvert 2.5 P2V Interop Test using ws08r2-x64"""
    DISTRO = "ws08r2-x64"
    VERSION = 25

class TC17646(TCXenConvert):
    """XenConvert 2.5 P2V Interop Test using win7sp1-x64"""
    DISTRO = "win7sp1-x64"
    VERSION = 25

class TC17645(TCXenConvert):
    """XenConvert 2.5 P2V Interop Test using ws08r2-x64"""
    DISTRO = "win7sp1-x86"
    VERSION = 25

class TC15475(TCXenConvert):
    """XenConvert 2.5 P2V Interop Test using winxpsp3"""
    DISTRO = "winxpsp3"
    LOGSDIR = "C:\\Documents and Settings\\All Users\\Application Data\\Citrix\\XenConvert"
    VERSION = 25

class TC15476(TCXenConvert):
    """XenConvert 2.5 P2V Interop Test using ws08sp2-x64"""
    DISTRO = "ws08sp2-x64"
    VERSION = 25

class TC17647(TCXenConvert):
    """XenConvert 2.5 P2V Interop Test using ws08sp2-x86"""
    DISTRO = "ws08sp2-x86"
    VERSION = 25

class TC15477(TCXenConvert):
    """XenConvert 2.5 P2V Interop Test using vistaeesp2"""
    DISTRO = "vistaeesp2"
    VERSION = 25

class TC15722(TCXenConvert):
    """XenConvert 2.4 P2V Interop Test using w2k3eesp2-x64"""
    DISTRO = "w2k3eesp2-x64"
    LOGSDIR = "C:\\Documents and Settings\\All Users\\Application Data\\Citrix\\XenConvert"
    VERSION = 24

class TC15723(TCXenConvert):
    """XenConvert 2.4 P2V Interop Test using ws08r2-x64"""
    DISTRO = "ws08r2-x64"
    VERSION = 24

class TC15724(TCXenConvert):
    """XenConvert 2.4 P2V Interop Test using winxpsp3"""
    DISTRO = "winxpsp3"
    LOGSDIR = "C:\\Documents and Settings\\All Users\\Application Data\\Citrix\\XenConvert"
    VERSION = 24

class TC15725(TCXenConvert):
    """XenConvert 2.4 P2V Interop Test using ws08sp2-x64"""
    DISTRO = "ws08sp2-x64"
    VERSION = 24

class TC15726(TCXenConvert):
    """XenConvert P2V 2.4 Interop Test using vistaeesp2"""
    DISTRO = "vistaeesp2"
    VERSION = 24


class TCInstallOpenStack(xenrt.TestCase):

    def prepare(self, arglist):

        listing = [x.strip() for x in xenrt.util.command(
            "wget --spider "
            "--recursive http://downloads.vmd.citrix.com/OpenStack/ "
            "--no-verbose -l 1 2>&1 "
            "| grep '200 OK' "
            "| awk '{ print $4}'").splitlines()]

        xvaURL = None
        xvaDate = None
        suppPackURL = None
        suppPackDate = None

        for l in listing:
            m = re.match(".*/devstack-(\d+_\d+_\d+)\.xva", l)
            if m:
                newDate = time.strptime(m.group(1), "%Y_%m_%d")
                if not xvaDate or newDate > xvaDate:
                    xvaDate = newDate
                    xvaURL = l
            m = re.match(".*/novaplugins-(\d+_\d+_\d+)\.iso", l)
            if m:
                newDate = time.strptime(m.group(1), "%Y_%m_%d")
                if not suppPackDate or newDate > suppPackDate:
                    suppPackDate = newDate
                    suppPackURL = l

        xenrt.TEC().logverbose("Using XVA %s" % xvaURL)
        xenrt.TEC().logverbose("Using Supp Pack %s" % suppPackURL)

        self.xva = xenrt.TEC().getFile(xvaURL)
        self.sp = xenrt.TEC().getFile(suppPackURL)

    def installSuppPack(self):
        installedRepos = self.host.execdom0(
            "ls /etc/xensource/installed-repos")

        if not "novaplugin:novaplugins" in installedRepos:
            self.host.sftpClient().copyTo(self.sp, "/root/novaplugins.iso")
            self.host.execdom0(
                "xe-install-supplemental-pack /root/novaplugins.iso")

    def getSlave(self):
        slave = self.getGuest("slave")
        if not slave:
            slave = self.host.createGenericLinuxGuest(name="slave")
        slave.setState("UP")
        return slave

    def injectPassword(self):
        slave = self.getSlave()
        rootVDIUUID = self.host.minimalList(
            "vbd-list",
            "vdi-uuid",
            "userdevice=0 vm-uuid=%s" % self.devstack.getUUID())[0]
        vbdUUID = self.cli.execute(
            "vbd-create",
            "vdi-uuid=%s vm-uuid=%s device=1" % (
                rootVDIUUID, slave.getUUID())).strip()
        self.cli.execute("vbd-plug", "uuid=%s" % vbdUUID)

        device = self.host.genParamGet("vbd", vbdUUID, "device")

        slave.execguest("fdisk -l /dev/%s" % device)
        slave.execguest("mount /dev/%s1 /mnt" % device)

        slave.execguest(
            "sed -i /XENAPI_PASSWORD/d /mnt/opt/stack/devstack/localrc")
        slave.execguest(
            "echo 'XENAPI_PASSWORD=%s' "
            ">> /mnt/opt/stack/devstack/localrc" % self.host.password)

        slave.execguest("umount /dev/%s1" % device)

        self.cli.execute("vbd-unplug", "uuid=%s" % vbdUUID)
        self.cli.execute("vbd-destroy", "uuid=%s" % vbdUUID)

    def importXVA(self):
        self.devstack = self.host.guestFactory()(
            "DevStackOSDomU", "NO_TEMPLATE",
            password=xenrt.TEC().lookup("DEFAULT_PASSWORD"))
        self.devstack.host = self.host
        xenrt.TEC().registry.guestPut("DevStackOSDomU", self.devstack)
        self.devstack.importVM(self.host, self.xva)
        self.devstack.password="citrix"

    def fixDevstackNetwork(self):
        vifUUID = self.host.minimalList(
            "vif-list",
            args="device=0 vm-uuid=%s" % self.devstack.getUUID())[0]
        self.cli.execute("vif-destroy", "uuid=%s" % vifUUID)
        self.devstack.createVIF(
            "eth0",
            self.host.getPrimaryBridge(),
            xenrt.randomMAC())

    def run(self, arglist):
        self.host = self.getDefaultHost()
        self.cli = self.host.getCLIInstance()

        self.installSuppPack()
        self.importXVA()
        self.injectPassword()
        self.fixDevstackNetwork()

        self.devstack.setState("UP")
        deadline = xenrt.util.timenow() + 1800
        while xenrt.util.timenow() < deadline:
            time.sleep(15)
            try:
                self.devstack.execguest(
                    "grep -q 'stack.sh completed in' "
                    "/opt/stack/devstack_logs/stack.log.summary", username="stack")
            except:
                continue
            break
        self.devstack.execguest(
            "test -e /opt/stack/runsh.succeeded", username="stack")


class TCOpenStackExercise(xenrt.TestCase):
    def run(self, arglist):
        devstack = self.getGuest("DevStackOSDomU")
        devstack.execguest(
            "cd /opt/stack/tempest "
            "&& sudo -H pip install tox==1.6.1 "
            "&& tox -eall tempest.scenario.test_minimum_basic </dev/null",
            username="stack",
            timeout=14400
        )


class TCOpenStackSmokeTest(xenrt.TestCase):
    def run(self, arglist):
        devstack = self.getGuest("DevStackOSDomU")
        devstack.execguest(
            "cd /opt/stack/tempest "
            "&& tox -esmoke </dev/null",
            username="stack",
            timeout=14400
        )
