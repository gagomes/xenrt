#
# XenRT: Test harness for Xen and the XenServer product family
#
# Cimserver(WSMAN and CIMXML) standalone testcases
#
# Copyright (c) 2010 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

#import os.path
import socket, re, string, time, traceback, sys, random, copy, os, os.path, urllib, filecmp

import xenrt, xenrt.lib.xenserver, XenAPI
import xml.dom.minidom
from xml.dom.minidom import parseString
import urllib2
import datetime, random
from xenrt.lazylog import log, warning

class _CIMInterface(object): 

    PACK = "xenserver-integration-suite.iso"
#    RPMS = ["xs-cim-cmpi-5.6.199-39460c",
#            "openpegasus-2.10.0-xs1"]

    RPMS = ["openpegasus-2.10.0-xs1"]
  
    RPMCHECK = True

    def _startCimLogging(self):
        #start capturing cimserver logs
        script = self.cimLogScript()
        try:
            self.host.execdom0(command=script)
        except:
            xenrt.TEC().logverbose("Exception occurred while trying to start cimserver logging")

    def prepare(self,host):
        """Install a host with xenserver integration supplemental pack"""

        flag = False
        self.host = host

        xenrt.TEC().logverbose("Going to check whether Xenserver integration supplemental pack has been installed or not")
        for rpm in self.RPMS:
            self.RPMCHECK = self.checkRPMS(self.host,rpm)
            if not self.RPMCHECK:
                flag = True
                break

        if flag == False:
            self._startCimLogging()
            return

        suppPack = xenrt.TEC().getFile("xe-phase-2/%s" % self.PACK, self.PACK, "../xe-phase-2/%s" % self.PACK)
        try:
            xenrt.checkFileExists(suppPack)
        except Exception, ex:
            xenrt.TEC().logverbose("xenserver-integration-suite iso file not found in xe-phase-2")
            raise

        hostPath = "/tmp/%s" % (self.PACK)
        #Upload the contents of iso onto a http server 
        sh = self.host.sftpClient()
        try:
            sh.copyTo(suppPack,hostPath)
        finally:
            sh.close() 

        #Pass the exception for the time being as there is a bug in the supp pack, ssh timeout is happening after the installation
        try:
            self.host.execdom0("xe-install-supplemental-pack /tmp/%s" % (self.PACK))
        except:
            xenrt.TEC().logverbose("Exception occurred while installing xenserver integration suite")

#        packdir = xenrt.WebDirectory()

#        spcd =""

        # Try the local test inputs
#        spcd = "%s/suppacks/%s" % (\
#            xenrt.TEC().lookup("TEST_TARBALL_ROOT"),
#            os.path.basename(self.PACK))

#        if not os.path.exists(spcd):
#            raise xenrt.XRTError(\
#                "Supplemental pack CD not found %s" % (self.PACK))
#        xenrt.TEC().logverbose("Using Xenserver Integration supplemental pack CD %s" % (spcd))

#        spmount = xenrt.MountISO(spcd)
#        spmountpoint = spmount.getMount()
        #Upload the contents of iso onto a http server
#        packdir.copyIn("%s/*" %(spmountpoint),"/packages.%s/" % (os.path.basename(self.PACK)))
#        self.downloadPackISO(self.host)

        #install the downloaded supplemental pack
#        self.host.execdom0("xe-install-supplemental-pack /tmp/%s" % (self.PACK))
        rpmInstalled = True
        for rpm in self.RPMS:
            rpmInstalled = self.checkRPMS(self.host,rpm)
            if not rpmInstalled:
                raise xenrt.XRTFailure("RPM package %s is not installed" %
                                       (rpm))

        #Check if CIM server running on host
        if not self.checkCimServerRunning(self.host):
            raise xenrt.XRTFailure("Cim Server is not running")

        self._startCimLogging()

    def cimLogScript(self):
 
        script = u"""
        #!/bin/bash

        # reset the log files
        export SBLIM_TRACE=4
        export SBLIM_TRACE_FILE=/var/log/xencim.log
        echo "" > $SBLIM_TRACE_FILE


        pid=$(pidof cimserver)
        kill -9 $pid

        echo "Launching CIM with debug tracing turned on. "
        echo "Collect the following trace files:"
        echo "    "$SBLIM_TRACE_FILE
        echo "    "$PEGASUS_TRACE_FILE
        cd /opt/openpegasus
        bin/cimserver enableHttpConnection=true traceComponents=all traceLevel=4
        """

        return script

    def downloadPackISO(self, host):

        #Download xenserver integration suite iso from the http server
        host.execdom0("curl '%s/suppacks/%s' -o /tmp/%s" %
                     (xenrt.TEC().lookup("TEST_TARBALL_BASE"),
                      self.PACK,self.PACK))

    def checkRPMS(self,host,rpm):

        # Check if the pack's rpms are installed
        try:
            data = host.execdom0("rpm -qi %s" % rpm)
        except:
            return False
        if "is not installed" in data:
            return False
        else:
            return True

    def checkCimServerRunning(self,host):

        cimProcess = "bin/cimserver"
        #check whether cimserver is running or not
        try:
            data = host.execdom0("ps ux | awk '/cimserver/ && !/awk/ {print $2}'")
            processId = int(data)
        except:
            return False
        
        processId = int(data)
        data = None
        if processId > 0:
            data = host.execdom0("ps -eaf|grep -i cimserver")
            if "%s" % (cimProcess) in data:
                return True
            else:
                return False
        else:
            return False

    def createProtocolObject(self,protocol):
        if protocol == "WSMAN":
            return _WSMANProtocol() 
        if protocol == "CIMXML":
            return _CIMXMLProtocol()
        else:
            raise xenrt.XRTFailure("Invalid Protocol")

class _WSMANProtocol(_CIMInterface):

    VMNAME = "test"
    SHAREDIRECTORY = "SharedDirectory"

    def prepare(self,arglist,host):

        self.host = host
        self.guest = None
        self.guest = xenrt.TEC().registry.guestGet(self.VMNAME)
        #self.getLogsFrom(self.guest)
        if self.guest == None:
            raise xenrt.XRTFailure("No VM with name %s exists." % (self.VMNAME))

        self.hostIPAddr = self.host.getIP()
        self.hostPassword = self.host.password

        # Start the VM if it is not running
        if self.guest.getState() == "DOWN":
            self.guest.start()
        else:
            self.guest.reboot()

        #update xmlRPC on the guest
        self.guest.xmlrpcUpdate()

        #Set the execution policy of PS to RemoteSigned
        self.executionPolicy()

        #Enable PS remoting on guest  
#        self.enablePsRemoting()

        #configure PS so that the scripts can be executed and can talk to cimserver running on host
        self.configurePS()

        #To verify whether CIMServer is bind to port 5988 by executing winrm identify command
        self.verifyHost()

        self.setMaxEnvelopeSize()
 
    def executionPolicy(self):
        self.guest.xmlrpcExec("powershell set-ExecutionPolicy RemoteSigned -f", timeout=30)

    def enablePsRemoting(self):
        self.guest.xmlrpcExec("powershell Enable-PSRemoting -force", timeout=30)
  
    def psExecution(self,psScript,timeout = 3600):
        #Function that executes PS script on guest
        rValue = self.guest.xmlrpcExec(psScript, returndata = True, timeout = timeout, powershell=True)
        if "Exception" in rValue or "Test Failed" in rValue or "Error number" in rValue:
            xenrt.TEC().logverbose("Error executing requested script - %s " % (rValue))
            raise xenrt.XRTFailure("Either exception caught while executing Powershell script or PS failed with following error")
        return rValue
    
    def verifyHost(self):

        # After installing xenserver integration suite iso on host check whether cimserver is responding to WSMAN request or not
        psScript = u"""
        winrm identify -remote:http://%s:5988 -authentication:basic -username:root -password:%s -encoding:utf-8
        """ % (self.hostIPAddr,self.hostPassword)
        ret = None
        for attempt in range(0,3):
            try:
                ret = self.psExecution(psScript,timeout = 300)
                if ret:
                    break
            except Exception, e:
                xenrt.sleep(10)
                xenrt.TEC().logverbose("Try again - Authentication of host failed with exception:%s" % str(e))
        if not ret:
            raise xenrt.XRTFailure("Authentication of host failed - After 4 attempts")
        xenrt.TEC().logverbose("The outcome of winrm identify command is %s" % (ret))

    def setMaxEnvelopeSize(self):

        psScript = u"""
        # Set network interfaces to private so we can change the envelope size
        $networkListManager = [Activator]::CreateInstance([Type]::GetTypeFromCLSID([Guid]"{DCB00C01-570F-4A9B-8D69-199FDBA5723B}"))
        $networkConnections= $networkListManager.getnetworkconnections()
        foreach($networkConnection in $networkConnections) {
            if ($networkConnection.getnetwork().getcategory() -eq 0)
            {
                $networkConnection.getnetwork().setcategory(1)
            } else {
            }
        }
        Set-Item WSMan:\localhost\MaxEnvelopeSizeKB 700

        #Set it back to public so that it can talk to external world
        $networkListManager = [Activator]::CreateInstance([Type]::GetTypeFromCLSID([Guid]"{DCB00C01-570F-4A9B-8D69-199FDBA5723B}"))
        $networkConnections= $networkListManager.getnetworkconnections()
        foreach($networkConnection in $networkConnections) {
            if ($networkConnection.getnetwork().getcategory() -eq 1)
            {
                $networkConnection.getnetwork().setcategory(0)
            } else {
            }
        }
 
        """
        try:
            ret = self.psExecution(psScript,timeout = 300)
        except Exception, e:
            xenrt.TEC().logverbose("Exception occurred while trying to set Max envelope size: %s" % (str(e)))
 
    def configurePS(self):
 
        #Configuring PS on guest so that PS scripts can be executed after that
        psScript = u"""
        set-item WSMan:\localhost\Client\AllowUnencrypted -value true -force
        set-item WSMan:\localhost\Client\TrustedHosts -value * -force
        """
        ret = self.psExecution(psScript,timeout = 300)
        xenrt.TEC().logverbose("%s" % (ret))
        
    def wsmanEnumerate(self):

        #Enumerate different CIM classes
        self.cimClasses = xenrt.lib.xenserver.getCIMClasses()
        for cimClass in self.cimClasses:
            psScript = xenrt.lib.xenserver.wsmanEnumerate(cimClass,self.hostIPAddr,self.hostPassword)
            ret = self.psExecution(psScript,timeout = 3600)
            xenrt.TEC().logverbose("%s" % (ret))

    def createVM(self,vmName):

        #Creates a VM using WSMAN protocol
        psScript = xenrt.lib.xenserver.createWSMANVM(self.hostPassword,self.hostIPAddr,vmName)
        ret = self.psExecution(psScript,timeout = 3600)
        try:
            vmuuid = ret.splitlines()[2]
        except:
            raise xenrt.XRTFailure("Error occured while trying to get VM uuid")
        xenrt.TEC().logverbose("VM Created with UUID: %s" % (vmuuid))
        return vmuuid

    def changeVMState(self,vmuuid,state):

        #Change the state of VM using WSMAN protocol
        psScript = xenrt.lib.xenserver.changeWSMANVMState(self.hostPassword,self.hostIPAddr,vmuuid,state)
        self.psExecution(psScript,timeout = 3600)

    def deleteVM(self,vmuuid):

        #Deletes VM using WSMAN protocol
        psScript = xenrt.lib.xenserver.deleteWSMANVM(self.hostPassword,self.hostIPAddr,vmuuid)
        self.psExecution(psScript,timeout = 300)
        xenrt.TEC().logverbose("VM Deleted with UUID: %s" % (vmuuid))

    def getVMUUID(self,vm):
     
        #returns the vmuuid
        return vm
   
    def jobCleanUp(self):

        xenrt.TEC().logverbose("Cleaning any remaining job on host") 
        psScript = xenrt.lib.xenserver.jobCleanUp(self.hostPassword,self.hostIPAddr)
        try:
            self.psExecution(psScript,timeout = 600)
        except:
            pass
        try:
            self.guest.xmlrpcExec("bitsadmin /reset /allusers",returndata = False)
        except:
            pass

    def deleteShareDirectory(self):

        try:
            self.guest.xmlrpcExec("bitsadmin /reset /allusers",returndata = False)
        except:
            pass

        try:
            self.guest.xmlrpcExec("net use Q: /DELETE",returndata = False)
        except:
            pass
        try: 
            self.guest.xmlrpcExec("net share %s /DELETE \q" % (self.shareDName), returndata = False)
        except:
            pass
        try:
            self.guest.xmlrpcExec("rmdir c:\%s /s /q" % (self.SHAREDIRECTORY), returndata = False)
        except:
            pass

    def createSharedDirectory(self):

        #Create and share a folder on the guest and map that to Q: drive
        guestIP = self.guest.getIP()
        try:
            self.guest.xmlrpcExec("mkdir c:\%s " % (self.SHAREDIRECTORY),returndata = False)
        except:
            pass
        try:
            self.shareDName = self.guest.xmlrpcExec("net share %s=c:\%s /GRANT:Everyone,FULL" % (self.SHAREDIRECTORY,self.SHAREDIRECTORY),returndata = True)
        except:
            pass
        targetShare = "\\" + "\\%s\%s" % (guestIP,self.SHAREDIRECTORY)
        try:
            self.guest.xmlrpcExec("net use Q: %s" % (targetShare),returndata = False,powershell=True)
           # self.guest.xmlrpcExec("net use Q: %s /user:%s %s" % (targetShare,user,self.hostPassword),returndata = False,powershell=True)
        except:
            pass

    def exportVM(self,vmuuid,transProtocol,ssl):

        self.createSharedDirectory()
        # Get the staticIP for connectToDiskImage
        s_obj = xenrt.StaticIP4Addr.getIPRange(3)
        static_ip = s_obj[1].getAddr()
        (_, mask, gateway) = self.host.getNICAllocatedIPAddress(0)
        # Export vm
        psScript = xenrt.lib.xenserver.exportWSMANVM(self.hostPassword,self.hostIPAddr,vmuuid,transProtocol,ssl,static_ip,mask,gateway)
        try:
            ret = self.psExecution(psScript,timeout = 40000)
            self.getTheWsmanScriptsLogs("exportWSMANVMScriptsOutput.txt")
        except Exception, e:
            self.getTheWsmanScriptsLogs("exportWSMANVMScriptsOutput.txt")
            raise xenrt.XRTFailure("Failure caught while executing wsman scripts")
        xenrt.TEC().logverbose("VM %s exported" % (vmuuid))

    def verifyExport(self,vdiuuid,vdiName):
        
        #check whether the exported vhd file exists or not
        filename = vdiName + "." + vdiuuid + "." + "vhd"
        try:
            fileExist = self.guest.xmlrpcExec("if exist c:\%s\%s echo True" % (self.SHAREDIRECTORY,filename), returndata = True)
        except:
            raise xenrt.XRTFailure("Exception caught while checking for VHD file")

        if fileExist == None:
            raise xenrt.XRTFailure("VDI with uuid %s has not been exported correctly" % (vdiuuid))        

        if fileExist.splitlines()[2] != "True":
            raise xenrt.XRTFailure("VDI with uuid %s has not been exported correctly" % (vdiuuid))

        #get the size of the file and verify the size of exported file
        psScript = u"""
        $Obj = New-Object System.IO.FileInfo("c:\%s\%s")
        $Obj.Length
        """ % (self.SHAREDIRECTORY,filename)

        ret = self.psExecution(psScript,timeout = 300)
        
        size = ret.splitlines()[2]
        rValue = self.host.execdom0("xe vdi-param-get uuid=%s param-name=virtual-size" % (vdiuuid))        
        vdiSize = rValue.splitlines()[0]

        if vdiSize != size:
            raise xenrt.XRTFailure("Size of the exported file is not same as that of VDI")     

        xenrt.TEC().logverbose("VDI with uuid %s exported,checking the integrity of the VDI" % (vdiuuid)) 
        try:
            self.guest.xmlrpcExec("bitsadmin /reset /allusers",returndata = False)
        except:
            pass
 
    def importVM(self,vmuuid,transProtocol,ssl,vmName,vmProc,vmRam):

        # Get the staticIP for connectToDiskImage
        s_obj = xenrt.StaticIP4Addr.getIPRange(3)
        static_ip = s_obj[1].getAddr()
        (_, mask, gateway) = self.host.getNICAllocatedIPAddress(0)
        # import VM
        psScript = xenrt.lib.xenserver.importWSMANVM(self.hostPassword,self.hostIPAddr,vmuuid,transProtocol,ssl,vmName,vmProc,vmRam,static_ip,mask,gateway)
        try:
            ret = self.psExecution(psScript,timeout = 40000)
            vm = ret.splitlines()[2]
            self.getTheWsmanScriptsLogs("importWSMANVMScriptsOutput.txt")
        except Exception, e:
            self.getTheWsmanScriptsLogs("importWSMANVMScriptsOutput.txt")
            raise xenrt.XRTFailure("Failure caught while executing wsman scripts")
        xenrt.TEC().logverbose("VM %s imported" % (vm))
        return vm
       
    def createVMFromTemplate(self,templateName,vmName):

        psScript =  xenrt.lib.xenserver.createWSMANVMFromTemplate(self.hostPassword,self.hostIPAddr,templateName,vmName)
        ret = self.psExecution(psScript,timeout = 3600)
        vm = ret.splitlines()[2]
        xenrt.TEC().logverbose("VM created from template '%s'" % (templateName)) 
        return vm

    def copyVM(self,origVMName,copyVMName):

        psScript =  xenrt.lib.xenserver.copyWSMANVM(self.hostPassword,self.hostIPAddr,origVMName,copyVMName)
        try:
            ret = self.psExecution(psScript,timeout = 3600)
            self.getTheWsmanScriptsLogs("copyVMWSMANScriptsOutput.txt")
            vm = ret.splitlines()[2]
            xenrt.TEC().logverbose("VM copied from '%s'" % (origVMName))
            return vm
        except Exception, e:
            self.getTheWsmanScriptsLogs("copyVMWSMANScriptsOutput.txt")
            raise xenrt.XRTFailure("Failure caught while executing wsman scripts")
 
    def createCIFSISO(self,targetHost,isoSRName,vdiName,vmuuid,sharename,cifsGuest,host):
      
        self.srs = []
        self.srsToRemove = []

        # Enable file and printer sharing on the guest.
        self.guest.xmlrpcExec("netsh firewall set service type=fileandprint "
                              "mode=enable profile=all")
        cifsGuest.xmlrpcExec("netsh firewall set service type=fileandprint "
                             "mode=enable profile=all")

        # Create a user account.
        user = "Administrator"
        password = self.guest.password
        # Share a directory.
        sharedir = self.guest.xmlrpcTempDir() 
        try: 
            self.guest.xmlrpcExec("net share %s=%s /GRANT:Everyone,FULL" %
                                  (sharename, sharedir))
        except:
            raise xenrt.XRTError("Exception caught while sharing directory on source guest")

        targetShareDir = cifsGuest.xmlrpcTempDir()
        try:
            cifsGuest.xmlrpcExec("net share %s=%s /GRANT:Everyone,FULL" %
                                  (sharename, targetShareDir))
        except:
            raise xenrt.XRTError("Exception caught while sharing directory on target guest")

        # Copy the PV tools ISO from the host to use as an example ISO
        # in our CIFS SR
        remotefile = host.toolsISOPath()
        if not remotefile:
            raise xenrt.XRTError("Could not find PV tools ISO in dom0")
        cd = "%s/xs-tools.iso" % (xenrt.TEC().getWorkdir())
        sh = host.sftpClient()
        try:
            sh.copyFrom(remotefile, cd)
        finally:
            sh.close()
        self.guest.xmlrpcSendFile(cd,
                                  "%s\\xs-tool.iso" % (sharedir),
                                  usehttp=True)
   
        location = "/" + "/%s/%s" % (cifsGuest.getIP(),sharename) 

        #map the network drive to Q
        guestIP = self.guest.getIP()
        targetShare = "\\" + "\\%s\%s" % (guestIP,sharename)
        try:
            self.guest.xmlrpcExec("net use Q: %s" % (targetShare),returndata = False,powershell=True)
        except:
            raise xenrt.XRTError("Exception caught while mapping the share directory")

        # Get the staticIP for connectToDiskImage
        s_obj = xenrt.StaticIP4Addr.getIPRange(3)
        static_ip = s_obj[1].getAddr()
        (_, mask, gateway) = self.host.getNICAllocatedIPAddress(0)
        psScript =  xenrt.lib.xenserver.createWSMANCifsIsoSr(self.hostPassword,self.hostIPAddr,location,user,password,isoSRName,vdiName,vmuuid,static_ip,mask,gateway)
        ret = self.psExecution(psScript,timeout = 3600)
        return ret

    def detachISO(self,vmuuid,hostPass=None,hostIPA=None):

        if hostPass:
            password = hostPass
        else:
            password = self.hostPassword
        if hostIPA:          
            ipAddress = hostIPA
        else:
            ipAddress = self.hostIPAddr
        psScript = xenrt.lib.xenserver.detachWSMANISO(password,ipAddress,vmuuid)
        self.psExecution(psScript,timeout = 3600)

    def deleteSR(self,sr,hostPass=None,hostIPA=None):

        if hostPass:
            password = hostPass
        else:
            password = self.hostPassword
        if hostIPA:
            ipAddress = hostIPA
        else:
            ipAddress = self.hostIPAddr

        psScript = xenrt.lib.xenserver.deleteWSMANSR(password,ipAddress,sr)
        self.psExecution(psScript,timeout = 300)

    def forgetSR(self,sr,hostPass=None,hostIPA=None):

        if hostPass:
            password = hostPass
        else:
            password = self.hostPassword
        if hostIPA:
            ipAddress = hostIPA
        else:
            ipAddress = self.hostIPAddr
 
        psScript = xenrt.lib.xenserver.forgetWSMANSR(password,ipAddress,sr)
        self.psExecution(psScript,timeout = 300)

    def deleteSRDirectories(self,shareName):
  
        try:
            self.guest.xmlrpcExec("bitsadmin /reset /allusers",returndata = False)
        except:
            pass

        try:
            self.guest.xmlrpcExec("net use Q: /DELETE",returndata = False)
        except:
            pass
        try:
            self.guest.xmlrpcExec("net share %s /DELETE -f" % (shareName), returndata = False)
        except:
            pass

    def createNFSSR(self,isoSRName,serverIP,path):

        psScript = xenrt.lib.xenserver.createWSMANNFSSR(self.hostPassword,self.hostIPAddr,isoSRName,serverIP,path)
        ret = self.psExecution(psScript,timeout = 3600)
        return ret

    def createNFSISOSR(self,isoSRName,location):

        psScript = xenrt.lib.xenserver.createWSMANNFSISOSR(self.hostPassword,self.hostIPAddr,isoSRName,location)
        ret = self.psExecution(psScript,timeout = 3600)
        return ret

    def createISCSISR(self,srName,target,iqn,scsiId,user,password):

        psScript = xenrt.lib.xenserver.createWSMANISCSISR(self.hostPassword,self.hostIPAddr,srName,target,iqn,scsiId,user,password)
        ret = self.psExecution(psScript,timeout = 3600)
        return ret

    def getHistoricalMetrics(self,uuid,system):
 
        psScript = xenrt.lib.xenserver.getWSMANHistoricalMetrics(self.hostPassword,self.hostIPAddr,uuid,system)
        ret = self.psExecution(psScript,timeout = 600)
        return ret

    def getFile(self):
      
        self.guest.xmlrpcGetFile("c:\\xmldata.xml", "%s/xmldata.xml" % (xenrt.TEC().getWorkdir()))

    def getInstantaneousMetric(self,cimClass,vmuuid,networkName):

        parameter = "MetricValue"
        psScript = xenrt.lib.xenserver.getWSMANInstMetric(self.hostPassword,self.hostIPAddr,cimClass,parameter,vmuuid,networkName)
        ret = self.psExecution(psScript,timeout = 300)
        return ret
    
    def getInstantaneousMemoryMetric(self,metricType,vmuuid):
 
        if metricType == "vmAllocatedMemory" or metricType == "hostAllocatedMemory":
            parameter = "NumberOfBlocks"
        elif metricType == "vmFreeMemory" or metricType == "hostFreeMemory":
            parameter = "ConsumableBlocks"

        if metricType == "vmAllocatedMemory" or metricType == "vmFreeMemory":
            cimClass = "Xen_Memory"
        elif metricType == "hostAllocatedMemory" or metricType == "hostFreeMemory":
            cimClass = "Xen_HostMemory"

        psScript = xenrt.lib.xenserver.getWSMANInstMetric(self.hostPassword,self.hostIPAddr,cimClass,parameter,vmuuid)
        ret = self.psExecution(psScript,timeout = 300)
        return ret   

    def getInstantaneousHostCpuMetric(self,cimClass):

        psScript = xenrt.lib.xenserver.getWSMANInstHostCPUMetric(self.hostPassword,self.hostIPAddr,cimClass)
        ret = self.psExecution(psScript,timeout = 300)
        return ret
 
    def getInstantaneousDiskMetrics(self,cimClass,vbdName):

        psScript = xenrt.lib.xenserver.getWSMANInstDiskMetric(self.hostPassword,self.hostIPAddr,cimClass,vbdName)
        ret = self.psExecution(psScript,timeout = 300)
        return ret

    def createVdi(self,vdiName,vdiSize):

        psScript = xenrt.lib.xenserver.createWSMANVdiForVM(self.hostPassword,self.hostIPAddr,vdiName,vdiSize)
        ret = self.psExecution(psScript,timeout = 3600)
        return ret
       
    def attachVdiToVM(self,vmuuid,vdiDeviceId,vdiuuid): 

        psScript = xenrt.lib.xenserver.attachWSMANVdiToVM(self.hostPassword,self.hostIPAddr,vmuuid,vdiDeviceId,vdiuuid)
        ret = self.psExecution(psScript,timeout = 3600)
        return ret
 
    def getVBDuuid(self,vdiuuid,vmuuid):
 
        psScript =  xenrt.lib.xenserver.getWSMANVBDuuid(self.hostPassword,self.hostIPAddr,vdiuuid,vmuuid)
        ret = self.psExecution(psScript,timeout = 3600)
        return ret     

    def dettachVBDFromVM(self,vbdInstanceID):

        psScript = xenrt.lib.xenserver.dettachWSMANVBDFromVM(self.hostPassword,self.hostIPAddr,vbdInstanceID)
        ret = self.psExecution(psScript,timeout = 3600)
        return ret

    def deleteVdi(self,vdiParams):

        psScript = xenrt.lib.xenserver.deleteWSMANVDI(self.hostPassword,self.hostIPAddr,vdiParams['DeviceId'],
                       vdiParams['CreationClassName'],vdiParams['SystemCreationClassName'],vdiParams['SystemName'])
        ret = self.psExecution(psScript,timeout = 300)
        return ret

    def modifyProcessor(self,vmName,procCount):

        psScript = xenrt.lib.xenserver.modifyWSMANProcessor(self.hostPassword,self.hostIPAddr,vmName,procCount)
        ret = self.psExecution(psScript,timeout = 600)
        return ret

    def modifyMemory(self,vmName,vmNewMemory):

        psScript = xenrt.lib.xenserver.modifyWSMANMemory(self.hostPassword,self.hostIPAddr,vmName,vmNewMemory)
        ret = self.psExecution(psScript,timeout = 600)
        return ret

    def remCDDVDDrive(self,vmuuid,driveType,vbduuid):
       
        psScript = xenrt.lib.xenserver.remWSMANcddvdDrive(self.hostPassword,self.hostIPAddr,vmuuid,driveType,vbduuid)
        ret = self.psExecution(psScript,timeout = 300)

    def addCDDVDDrive(self,vmuuid,driveType):

        psScript = xenrt.lib.xenserver.addWSMANcddvdDrive(self.hostPassword,self.hostIPAddr,vmuuid,driveType)
        ret = self.psExecution(psScript,timeout = 600)

    def takeSnapshot(self,vmName,snapshotName):

        psScript = xenrt.lib.xenserver.snapshotWSMANVM(self.hostPassword,self.hostIPAddr,vmName,snapshotName)
        ret = self.psExecution(psScript,timeout = 3600)
        return ret

    def applySnapshot(self,snapshotID):
 
        psScript = xenrt.lib.xenserver.applyWSMANSnapshot(self.hostPassword,self.hostIPAddr,snapshotID)
        ret = self.psExecution(psScript,timeout = 3600)
   
    def destroySnapshot(self,snapshotID):

        psScript = xenrt.lib.xenserver.destroyWSMANSnapshot(self.hostPassword,self.hostIPAddr,snapshotID)
        ret = self.psExecution(psScript,timeout = 300)

    def createVMFromSnapshot(self,vmNameForSnapshop,snapshotID):
 
        psScript = xenrt.lib.xenserver.createWSMANVMFromSnapshot(self.hostPassword,self.hostIPAddr,snapshotID,vmNameForSnapshop)
        ret = self.psExecution(psScript,timeout = 3600)
        return ret

    def getSnapshotList(self):
 
        psScript = xenrt.lib.xenserver.getWSMANVMSnapshotList(self.hostPassword,self.hostIPAddr)
        ret = self.psExecution(psScript,timeout = 300)
        return ret

    def modifyVdiProperties(self,vmuuid,vdiNewSize,vdiNewName,vdiName):

        psScript = xenrt.lib.xenserver.modifyWSMANVdiProperties(self.hostPassword,self.hostIPAddr,vmuuid,vdiNewSize,vdiNewName,vdiName)
        ret = self.psExecution(psScript,timeout = 300)

    def modifyVMSettings(self,instanceID,vmNewName,vmNewDescription):
 
        psScript = xenrt.lib.xenserver.modifyWSMANVMSettings(self.hostPassword,self.hostIPAddr,instanceID,vmNewName,vmNewDescription)
        ret = self.psExecution(psScript,timeout = 300)

    def convertVMToTemplate(self,vmuuid):
 
        psScript = xenrt.lib.xenserver.convertWSMANVMToTemplate(self.hostPassword,self.hostIPAddr,vmuuid)
        ret = self.psExecution(psScript,timeout = 3600)

    def getTheWsmanScriptsLogs(self, filename):
        
        base = xenrt.TEC().getLogdir()
        self.guest.xmlrpcGetFile("C:\\%s" % filename, "%s/%s" % (base,filename))
        self.guest.xmlrpcRemoveFile("C:\\%s" % filename)

    def getIPRange(self,staticIPs):

        s_obj = xenrt.StaticIP4Addr.getIPRange(staticIPs+1)
        start_ip = s_obj[1].getAddr()
        end_ip = s_obj[staticIPs].getAddr()
        return start_ip,end_ip

    def exportVMSnapshotTree(self,vmuuid,staticIPs):

        self.createSharedDirectory()
        driveName = "Q:\\"
        if staticIPs:
            start_ip,end_ip = self.getIPRange(staticIPs)
            s_ip = start_ip.split('.')
            if (int(s_ip[3]) == 0) or ((int(s_ip[3]) + staticIPs) >= 255):
                start_ip,end_ip = self.getIPRange(staticIPs)
            (_, mask, gateway) = self.host.getNICAllocatedIPAddress(0)
            psScript = xenrt.lib.xenserver.exportWSMANSnapshotTree(self.hostPassword,self.hostIPAddr,vmuuid,driveName,start_ip,end_ip,mask,gateway)
        else:
            psScript = xenrt.lib.xenserver.exportWSMANSnapshotTree(self.hostPassword,self.hostIPAddr,vmuuid,driveName)
        
        try:
            ret = self.psExecution(psScript,timeout = 30000)
            self.getTheWsmanScriptsLogs("exportWSMANScriptsOutput.txt")
        except Exception, e:
            self.getTheWsmanScriptsLogs("exportWSMANScriptsOutput.txt")
            raise xenrt.XRTFailure("Failure caught while executing wsman scripts")

    def importVMSnapshotTree(self,transProtocol,ssl):

        driveName = "Q:\\"
        # Get the staticIP for connectToDiskImage
        s_obj = xenrt.StaticIP4Addr.getIPRange(3)
        static_ip = s_obj[1].getAddr()
        (_, mask, gateway) = self.host.getNICAllocatedIPAddress(0)
        # Import VMSnapshotTree
        psScript = xenrt.lib.xenserver.importWSMANSnapshotTree(self.hostPassword,self.hostIPAddr,driveName,transProtocol,ssl,static_ip,mask,gateway)
        
        try:
            ret = self.psExecution(psScript,timeout = 30000)
            self.getTheWsmanScriptsLogs("importWSMANScriptsOutput.txt")
        except Exception, e:
            self.getTheWsmanScriptsLogs("importWSMANScriptsOutput.txt")
            raise xenrt.XRTFailure("Failure caught while executing wsman scripts")
        
        return ret
        

    def createInternalNetwork(self,networkName):

        psScript = xenrt.lib.xenserver.createWSMANInternalNetwork(self.hostPassword,self.hostIPAddr,networkName)
        ret = self.psExecution(psScript,timeout = 30000)
        return ret

    def createExternalNetwork(self,networkName):

        psScript = xenrt.lib.xenserver.createWSMANExternalNetwork(self.hostPassword,self.hostIPAddr,networkName,"eth0")
        ret = self.psExecution(psScript,timeout = 30000)
        return ret

    def addNicToNetwork(self,networkuuid):    

        psScript = xenrt.lib.xenserver.addWSMANNicToNetwork(self.hostPassword,self.hostIPAddr,networkuuid,"eth0")
        ret = self.psExecution(psScript,timeout = 30000)
        return ret

    def removeNicFromNetwork(self,networkuuid):

        psScript = xenrt.lib.xenserver.removeWSMANNicFromNetwork(self.hostPassword,self.hostIPAddr,networkuuid,"eth0")
        ret = self.psExecution(psScript,timeout = 30000)

    def addNetworkToVM(self,networkuuid,vmuuid):
 
        psScript = xenrt.lib.xenserver.attachWSMANVMToNetwork(self.hostPassword,self.hostIPAddr,vmuuid,networkuuid)
        ret = self.psExecution(psScript,timeout = 30000)

    def removeNetworkFromVM(self,vif):

        psScript = xenrt.lib.xenserver.dettachWSMANVMFromNetwork(self.hostPassword,self.hostIPAddr,vif)
        ret = self.psExecution(psScript,timeout = 30000)

    def destroyNetwork(self,networkuuid):

        psScript = xenrt.lib.xenserver.destroyWSMANetwork(self.hostPassword,self.hostIPAddr,networkuuid)
        ret = self.psExecution(psScript,timeout = 30000)

class _CIMXMLProtocol(_CIMInterface):

    def prepare(self,arglist,host):

        self.host =  host
        self.hostIPAddr = self.host.getIP()
        self.hostVerify(self.hostIPAddr)

    def hostVerify(self,hostIPAddr):

        # After installing xenserver integration suite iso on host check whether cimserver is responding to CIM-XML request or not
        self.hostPassword = self.host.password
        try:
            xenrt.lib.xenserver.verifyHost(hostIPAddr,self.hostPassword)
        except:
            raise xenrt.XRTFailure("Authentication of host failed")   

    def changeVMState(self,vmuuid,state):

        #Change the state of VM using CIM-XML protocol
        xenrt.lib.xenserver.changeCIMXMLState(self.hostPassword,self.hostIPAddr,vmuuid,state)

    def createVM(self,vmName):

        #Create VM using CIM-XML protocol
        vm = xenrt.lib.xenserver.createCIMXMLVM(self.hostPassword,self.hostIPAddr,vmName) 
        return vm

    def getVMUUID(self,vm):

        return vm["Name"]

    def deleteVM(self,vm):

        #Deletes VM using CIM-XML protocol
        xenrt.lib.xenserver.deleteCIMXMLVM(self.hostPassword,self.hostIPAddr,vm)
        xenrt.TEC().logverbose("VM Deleted with UUID: %s" % (vm["Name"]))

class _CimBase(xenrt.TestCase,_CIMInterface):

    PROTOCOL = "WSMAN"

    def prepare(self,arglist):

        self.host = self.getDefaultHost()
        _CIMInterface.prepare(self,self.host)
        self.protocolObj = _CIMInterface.createProtocolObject(self,self.PROTOCOL)
        xenrt.TEC().logverbose("Xenserver Integration suite installed successfully")
        self.protocolObj.prepare(self,self.host)
        if isinstance(self.protocolObj, _WSMANProtocol) and self.protocolObj.guest: 
            self.getLogsFrom(self.protocolObj.guest)

    def checkisVMCreated(self,vmuuid,vmNameToCompare,host):

        #Check if VM is created using CLI command

        data = host.execdom0("xe vm-param-get uuid=%s param-name=name-label" % (vmuuid))
        vmName = data.splitlines()[0]
        if vmName != vmNameToCompare:
            raise xenrt.XRTFailure("No VM with the name %s exists." % (vmNameToCompare))

    def checkVMState(self,vmuuid,vmState,timeout,host):
        """Poll out VM for reaching the specified state"""

        #Check the VM state using CLI command
        deadline = xenrt.timenow() + timeout
        pollPeriod = 5
        time.sleep(10)
        while 1:
            data = host.execdom0("xe vm-param-get uuid=%s param-name=power-state" % (vmuuid))
            state = data.splitlines()[0]
            if vmState == state:
                time.sleep(3)
                return
            if xenrt.timenow() > deadline:
                raise xenrt.XRTFailure("Timed out waiting for VM with uuid %s to change its state to %s" %
                   (vmuuid, vmState))
            time.sleep(pollPeriod)

    def destroyVM(self,vmuuid,host):

        #Delete VM using CLI command
        host.execdom0("xe vm-destroy uuid=%s" % (vmuuid))

    def verifyVM(self,vmuuid,vmName,origVMObj,host,createVif,changeVif=False):

        #Copy the original object for the new VM
        newVm =  copy.copy(origVMObj)
        newVm.name =  vmName
        newVm.uuid = vmuuid
        newVm.paramSet("platform:device_id", "0002")
        self.uninstallOnCleanup(newVm)

        #considering that there is only one vif with name eth0
        if (createVif or changeVif):
            mac = xenrt.randomMAC()
            bridge = newVm.host.getPrimaryBridge()
            device = 'eth0'
            if createVif:
                newVm.createVIF(device, bridge, mac)
            else:
                newVm.changeVIF(device, bridge, mac)
            
        
        #considering that there is only one vif with name eth0
        mac, ip, network = newVm.getVIFs()["eth0"]
        newVm.vifs = [('eth0',network,mac,None)]
 
        #start the newly created vm only if it is a copy of an existing VM
        if newVm.getState() == "DOWN":
            newVm.start()
#            try:
#                newVm.start()
#            except:
#                raise xenrt.XRTFailure("Caught Exception while starting the copied/Imported VM")

        self.checkVMState(vmuuid,"running",30,host)

        #check the metadata of newly created vm
        newVm.check()

        if newVm.getState() == "UP":
            newVm.shutdown()

        return newVm

    def getOfflineDisks(self,guest):
        data = guest.xmlrpcExec("echo list disk | diskpart",
                                 returndata=True)
        status = re.findall("Disk ([0-9])\W+(\w+)", data)
        return filter(lambda (a,b):b == 'Offline', status)
 
        #this function was written for creating a large but later an extra disk parameter has been introduced in createGenericWindowsGuest
           #so its not in use anymore
    def createLargeVM(self,host,vmName):

        distro = "ws08sp2-x86"
        memory = (xenrt.KILO)*4
        # Default to a 100Gb disk.
        disksize = 100

        vmInfo = {}
        vmInfo["host"] = host
        vmInfo["guestname"] = vmName
        vmInfo["distro"] = distro
        vmInfo["disks"] = [(1, disksize, True)]
        vmInfo["vifs"] = [(0, None, xenrt.randomMAC(), None)]
        vmInfo["memory"] = memory
        guest = xenrt.lib.xenserver.guest.createVM(**vmInfo)
        # Check disk is there and accessible.
        offline = self.getOfflineDisks(guest)
        if offline:
            raise xenrt.XRTFailure("Found offline disk before installing "
                                   "PV drivers. (%s)" % (offline))
        # Install PV drivers.
        guest.installDrivers()

        #check again after installing the drivers
        offline = self.getOfflineDisks(guest)
        if offline:
            raise xenrt.XRTFailure("Found offline disk after installing "
                                   "PV drivers. (%s)" % (offline))
        return guest

    def verifySRCreation(self,vmuuid,host,isoSRName,sruuid,vdiName,vdiuuid,srType): 

        ret = self.verifySR(host,sruuid,isoSRName)
        if not ret:
            raise xenrt.XRTFailure("sr with uuid=%s and name %s is not found" % (sruuid,isoSRName))

        data = host.execdom0("xe sr-param-get uuid=%s param-name=type" % (sruuid))
        type = data.splitlines()[0]
        if srType != type:
            raise xenrt.XRTFailure("sr with uuid=%s has not the correct type" % (sruuid))

        xenrt.TEC().logverbose("CIFS ISO SR created successfully")

        data = host.execdom0("xe vdi-param-get uuid=%s param-name=name-label" % (vdiuuid))
        name = data.splitlines()[0]
        if vdiName != name:
            raise xenrt.XRTFailure("vdi with uuid=%s and name %s is not found" % (vdiuuid,vdiName))

        ret = self.verifyIso(host,vmuuid,vdiName)
        if not ret:
            raise xenrt.XRTFailure("iso with the name %s not found in CD Drive" % (vdiName)) 

        xenrt.TEC().logverbose("iso inserted to CD drive successfully")

    def verifyIso(self,host,vmuuid,vdiName):

        data = host.execdom0("xe vm-cd-list uuid=%s vdi-params=name-label" % (vmuuid))
        if "%s" % (vdiName) in data:
            return True
        return False

    def verifySR(self,host,sruuid,isoSRName):

        try:
            data = host.execdom0("xe sr-param-get uuid=%s param-name=name-label" % (sruuid))
        except:
            return False
        name = data.splitlines()[0]
        if isoSRName != name:
            return False
        return True

    def deleteVdi(self,host,vdiuuid):
 
        try:
            host.execdom0("xe vdi-destroy uuid=%s" % (vdiuuid))
        except:
            pass

    def stateTable(self,guest,host,protocolObj):

        self.checkStateTransition(guest,host,protocolObj,"halted","start","running")
        self.checkStateTransition(guest,host,protocolObj,"paused","start","running")
        self.checkStateTransition(guest,host,protocolObj,"suspended","start","running")
        self.checkStateTransition(guest,host,protocolObj,"running","start","running")
        self.checkStateTransition(guest,host,protocolObj,"halted","shutdown","halted")
        self.checkStateTransition(guest,host,protocolObj,"paused","shutdown","halted")
        self.checkStateTransition(guest,host,protocolObj,"suspended","shutdown","halted")
        self.checkStateTransition(guest,host,protocolObj,"running","shutdown","halted")
        self.checkStateTransition(guest,host,protocolObj,"halted","disable","halted")
        self.checkStateTransition(guest,host,protocolObj,"paused","disable","halted")
        self.checkStateTransition(guest,host,protocolObj,"suspended","disable","halted")
        self.checkStateTransition(guest,host,protocolObj,"running","disable","halted")
        self.checkStateTransition(guest,host,protocolObj,"halted","reboot","halted")
        self.checkStateTransition(guest,host,protocolObj,"paused","reboot","paused")
        self.checkStateTransition(guest,host,protocolObj,"suspended","reboot","suspended")
        self.checkStateTransition(guest,host,protocolObj,"running","reboot","running")
        self.checkStateTransition(guest,host,protocolObj,"halted","hardshutdown","halted")
        self.checkStateTransition(guest,host,protocolObj,"paused","hardshutdown","halted")
        self.checkStateTransition(guest,host,protocolObj,"suspended","hardshutdown","halted")
        self.checkStateTransition(guest,host,protocolObj,"running","hardshutdown","halted")
        self.checkStateTransition(guest,host,protocolObj,"halted","hardreboot","halted")
        self.checkStateTransition(guest,host,protocolObj,"paused","hardreboot","running")
        self.checkStateTransition(guest,host,protocolObj,"suspended","hardreboot","suspended")
        self.checkStateTransition(guest,host,protocolObj,"running","hardreboot","running")
        self.checkStateTransition(guest,host,protocolObj,"halted","reset","halted")
        self.checkStateTransition(guest,host,protocolObj,"paused","reset","running")
        self.checkStateTransition(guest,host,protocolObj,"suspended","reset","suspended")
        self.checkStateTransition(guest,host,protocolObj,"running","reset","running")
        self.checkStateTransition(guest,host,protocolObj,"halted","pause","halted")
        self.checkStateTransition(guest,host,protocolObj,"paused","pause","paused")
        self.checkStateTransition(guest,host,protocolObj,"suspended","pause","suspended")
        self.checkStateTransition(guest,host,protocolObj,"running","pause","paused")
        self.checkStateTransition(guest,host,protocolObj,"halted","suspend","halted")
        self.checkStateTransition(guest,host,protocolObj,"paused","suspend","paused")
        self.checkStateTransition(guest,host,protocolObj,"suspended","suspend","suspended")
        self.checkStateTransition(guest,host,protocolObj,"running","suspend","suspended")

    def setState(self,currentState,guest):

        timeout = 300
        deadline = xenrt.timenow() + timeout
        pollPeriod = 10
        while 1:
            try:
                guest.setState(currentState)
                return
            except:
                pass
            time.sleep(pollPeriod)
            if xenrt.timenow() > deadline:
                raise xenrt.XRTFailure("Unable to move VM to requested Current State (%s)" % (currentState))

    def checkStateTransition(self,guest,host,protocolObj,requestedCurrentState,action,expectedState):

        vmuuid = guest.getUUID()

        xenrt.TEC().logverbose("RequestedCurrentState of VM is (%s), Action to be performed on VM is (%s),"
                               " Expected State after performing action is (%s)" % (requestedCurrentState,action,expectedState))
  
        #assign the value of state (as per CIM standard) according to action
        if action == "start":
            state = 2
        elif action == "shutdown":
            state = 4 
        elif action == "disable": 
            state = 3
        elif action == "reboot":
            state = 10
        elif action == "hardshutdown":
            state = 32768
        elif action == "hardreboot":
            state = 32769
        elif action == "reset":
            state = 11
        elif action == "pause":
            state = 9
        elif action == "suspend":
            state = 6
        
        if requestedCurrentState == "halted":
            currentState = "DOWN"
        elif requestedCurrentState == "running":
            currentState = "UP"
        elif requestedCurrentState == "suspended":
            currentState = "SUSPENDED"        
        elif requestedCurrentState == "paused":
            currentState = "PAUSED"

        #move the guest into the requested current state
        self.setState(currentState,guest) 

        #Perform the action on VM
        protocolObj.changeVMState(vmuuid,state) 
 
        #check whether the state of vm changed or not
        self.checkVMState(vmuuid,expectedState,300,host) 
        xenrt.TEC().logverbose("VM state changed(or remained same) to %s" % (expectedState))

    def probeSR(self,srType,sruuid,params,host):
        xenrt.TEC().logverbose("Probing SR uuid=%s type=%s host=%s params=%s" % (sruuid, srType, host, params))
        ret = None
        if srType == "CIFSISOSR":
            try:
                ret = ""
            except Exception, e:
                ret = str(e.data)

        elif srType == "NFSSR":
            try:
                ret = host.execdom0("xe sr-probe type=%s device-config:server=%s device-config:serverpath=%s" % (params['type'],params['server'],params['serverpath']))
            except Exception, e:
                ret = str(e.data)
            
        elif srType =="ISCSISR": 
            try:
                if params['user']: 
                    ret = host.execdom0("xe sr-probe type=%s device-config:target=%s device-config:targetIQN=%s device-config:chapuser=%s device-config:chappassword=%s device-config:SCSIid=%s" % (params['type'],params['target'],params['iqn'],params['user'],params['password'],params['scsiid']))
                else:
                    ret = host.execdom0("xe sr-probe type=%s device-config:target=%s device-config:targetIQN=%s device-config:SCSIid=%s" % (params['type'],params['target'],params['iqn'],params['scsiid']))
            except Exception, e:
                ret = str(e.data)

        if sruuid in ret:
            return True
        else:
            return False

    def verifyVDIExist(self,vdiuuid,virtualSize,vdiName,host):

        ret = False
        try:
            data = host.execdom0("xe vdi-param-get uuid=%s param-name=name-label" % (vdiuuid))
            name = data.splitlines()[0]
        except:
            xenrt.TEC().logverbose("Exeception Caught while fetching VDI Name")
            return ret

        if vdiName != name:
            xenrt.TEC().logverbose("vdi with uuid=%s and name %s is not found" % (vdiuuid,vdiName))
            return ret
 
        try:
            data = host.execdom0("xe vdi-param-get uuid=%s param-name=virtual-size" % (vdiuuid))
            size = data.splitlines()[0]
            size = int(size)
        except:
            xenrt.TEC().logverbose("Exeception Caught while fetching VDI size")
            return ret   
 
        if virtualSize != size:
            xenrt.TEC().logverbose("vdi with uuid=%s has incorrect virtual size" % (vdiuuid))
            return ret

        ret = True 
        return ret

    def verifyIsVDIAttached(self,vmuuid,vdiuuid,host):

        ret = False

        try:
            data = host.execdom0("xe vm-disk-list uuid=%s" % (vmuuid))
        except:
            xenrt.TEC().logverbose("exception caught while getting VM disk list")
            return ret

        if not vdiuuid in data:
            xenrt.TEC().logverbose("VDI is not attached to VM with uuid %s" % (vmuuid))
            return ret
   
        ret = True
        return ret

    def verifyIsVBDAttached(self,vmuuid,vbduuid,host):

        ret = False
 
        try:
            data = host.execdom0("xe vm-disk-list uuid=%s" % (vmuuid))
        except:
            xenrt.TEC().logverbose("exception caught while getting VM disk list")
 
        if not vbduuid in data:
            xenrt.TEC().logverbose("VBD is not attached to VM with uuid %s" % (vmuuid))
            return ret

        ret = True
        return ret

    def verifyCDDVDDrive(self,vmuuid,vmName,host):
 
        try:
            data = host.execdom0("xe vm-cd-list uuid=%s" % vmuuid)
            if not vmName in data:
                return False
        except:
            return False
        return True

    def getVbduuid(self,vmuuid,host):
    
        try:
            data = host.execdom0("xe vm-cd-list uuid=%s" % (vmuuid))
            vbduuidData = data.splitlines()[1]
            vbduuid = vbduuidData.split(":")[1]
            vbduuid = vbduuid.strip() 
        except:
            raise xenrt.XRTFailure("Exception occured while getting VBD uuid")           
 
        return vbduuid 

    def isSnapshotExist(self,snapshotuuid,snapshotName,host):
 
        try:
            data = host.execdom0("xe snapshot-list uuid=%s" % (snapshotuuid))          
            if snapshotName in data:
                return True 
        except:
            return False

        return False

    def isTemplateExist(self,templateuuid,templateName,host):

        try:
            data = host.execdom0("xe template-list uuid=%s" % (templateuuid))
            if templateName in data:
                return True
        except:
            return False

        return False

    def metricComparison(self,data,metricValue):

        if data == metricValue:
            return True
        else:
            try:
                diff = 1000
                if (float(data) > float(metricValue)) :
                    diff = float(data) - float(metricValue)
                elif (float(metricValue) > float(data)) :
                    diff = float(metricValue) - float(data)
                if diff < 100:
                    return True
                else:
                    xenrt.TEC().logverbose("Failed attempt as two metric values are different")
            except:
                raise xenrt.XRTFailure("Exception occurred while trying to compare two values")
                
        return False 

    def installSuppPack(self,host):

        pack = "xenserver-integration-suite.iso"
        rpms = ["openpegasus-2.10.0-xs1"]
 
        flag = False
        rpmCheck = True
        xenrt.TEC().logverbose("Going to check whether Xenserver integration supplemental pack has been installed or not")
        for rpm in rpms:
            rpmCheck = self.checkRPMS(host,rpm)
            if not rpmCheck:
                flag = True
                break

        if flag == False:
            return

        suppPack = xenrt.TEC().getFile("xe-phase-2/%s" % pack,pack, "../xe-phase-2/%s" % pack)
        try:
            xenrt.checkFileExists(suppPack)
        except Exception, ex:
            xenrt.TEC().logverbose("xenserver-integration-suite iso file not found in xe-phase-2")
            raise

        hostPath = "/tmp/%s" % (pack)
        #Upload the contents of iso onto a http server
        sh = host.sftpClient()
        try:
            sh.copyTo(suppPack,hostPath)
        finally:
            sh.close()

        #Pass the exception for the time being as there is a bug in the supp pack, ssh timeout is happening after the installation
        try:
            host.execdom0("xe-install-supplemental-pack /tmp/%s" % (pack))
        except:
            xenrt.TEC().logverbose("Exception occurred while installing xenserver integration suite")

        rpmInstalled = True
        for rpm in rpms:
            rpmInstalled = self.checkRPMS(host,rpm)
            if not rpmInstalled:
                raise xenrt.XRTFailure("RPM package %s is not installed" %
                                       (rpm))

        #Check if CIM server running on host
        if not self.checkCimServerRunning(host):
            raise xenrt.XRTFailure("Cim Server is not running")

    def checkRPMS(self,host,rpm):

        # Check if the pack's rpms are installed
        try:
            data = host.execdom0("rpm -qi %s" % rpm)
        except:
            return False
        if "is not installed" in data:
            return False
        else:
            return True

    def checkCimServerRunning(self,host):

        cimProcess = "bin/cimserver"
        #check whether cimserver is running or not
        try:
            data = host.execdom0("ps ux | awk '/cimserver/ && !/awk/ {print $2}'")
            processId = int(data)
        except:
            return False

        processId = int(data)
        data = None
        if processId > 0:
            data = host.execdom0("ps -eaf|grep -i cimserver")
            if "%s" % (cimProcess) in data:
                return True
            else:
                return False
        else:
            return False

class TC12539(_CimBase):
    """To verify the installation of supplement pack and to check CIMServer is bind to port 5988"""

    def run(self,arglist):
        xenrt.TEC().logverbose("CIMSERVER is bind to port 5988 and is responding to WSMAN requests")

class TC12540(_CimBase):
    """To verify various WSMAN schemas"""

    def run(self,arglist):
        xenrt.TEC().logverbose("PowerShell is configured on guest to execute PS scripts")
        self.protocolObj.wsmanEnumerate()
        xenrt.TEC().logverbose("All the CIM classes have been verified")

class VMFunctions(_CimBase):
    """To perform various actions related to VM like creating,deleting,starting VM etc using either WSMAN protocol or CIM-XML protocol""" 
   
    TESTVMNAME = "TestVM_WSMAN_CIMXML"

    def run(self,arglist):
        #Create a VM
        vm = self.protocolObj.createVM(self.TESTVMNAME)
   
        #Check whether VM is created or not
        vmuuid = self.protocolObj.getVMUUID(vm)
        self.checkisVMCreated(vmuuid,self.TESTVMNAME,self.host)
        xenrt.TEC().logverbose("VM created using %s protocol " % (self.PROTOCOL))

        #Create an object for the new VM
        newVm = self.host.createGuestObject(self.TESTVMNAME)
        newVm.uuid = vmuuid
        newVm.memory = 256
        newVm.vcpus = 1
        self.uninstallOnCleanup(newVm)

        # Start the VM
        state = 2
        self.protocolObj.changeVMState(vmuuid,state)
 
        # Verify whether the VM is running or not
        self.checkVMState(vmuuid,"running",30,self.host)
        xenrt.TEC().logverbose("VM Started using %s protocol" % (self.PROTOCOL))

        #Shutdown the VM
        state = 32768
        self.protocolObj.changeVMState(vmuuid,state)
 
        #Verify whether the VM is stopped or not
        self.checkVMState(vmuuid,"halted",30,self.host)
        xenrt.TEC().logverbose("VM shutdown using %s protocol" % (self.PROTOCOL))      
 
        #self.destroyVM(vmuuid,self.host)

        #Destroy the VM
        self.protocolObj.deleteVM(vm)

        #Verify whether the VM is deleted or not
        data = None
        try:
            data = self.host.execdom0("xe vm-param-get uuid=%s param-name=name-label" % (vmuuid))
            vmName = data.splitlines()[0]
            if vmName == self.TESTVMNAME:
                raise xenrt.XRTFailure("VM with the name %s still exists." % (self.TESTVMNAME))
        except Exception, e:
            exception = str(e.data)
            if not "The uuid you supplied was invalid" in exception: 
                raise xenrt.XRTFailure("VM with the name %s still exists." % (self.TESTVMNAME))
 
        #Create linux VM for checking other state transitions
        self.guest = self.host.createGenericLinuxGuest(name=self.TESTVMNAME)
        self.uninstallOnCleanup(self.guest)

        if self.guest.getState() == "DOWN":
            self.guest.start()

        self.stateTable(self.guest,self.host,self.protocolObj)

        #move the guest into halt state
        self.setState("DOWN",self.guest)

    def postRun(self):

        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()      
 
class TC12541(VMFunctions):
    """To Create a VM sing WSMAN protocol and check various state changes of VM"""
    
    PROTOCOL = "WSMAN"

class TC12542(VMFunctions):
    """To Create a VM using CIM-XML protocol and check various state changes of VM"""

    PROTOCOL = "CIMXML"

class SRFunctions(_CimBase):
    """To Create, attach and destroy SR using either WSMAN or CIM-XML protocol"""

    SRTYPE = None
    isoSRName = None 
    vdiName = "xs-tools-cifs.iso"
    vmName = "SRVM"
    shareName = "XENRTSHARE"
    isChapUser = None
    isForgetSR = False

    def run(self,arglist):

        params = dict()

        if self.SRTYPE == "CIFSISOSR":
            pool = self.getDefaultPool()
            self.targetHost = pool.getSlaves()[0]
            self.installSuppPack(self.targetHost) 
            self.cifsGuest = self.targetHost.createGenericWindowsGuest(name=self.vmName)
            self.targetGuest = self.host.createGenericWindowsGuest("ISOVM") 
            self.uninstallOnCleanup(self.cifsGuest)
            self.uninstallOnCleanup(self.targetGuest)

            if self.targetGuest.getState() == "UP":
                self.targetGuest.shutdown()
            vmuuid = self.targetGuest.getUUID()
            
            #eject any iso present in cd drive
            try:
                self.host.getCLIInstance().execute("vm-cd-eject uuid=%s" % (vmuuid))
            except:
                pass
            if self.cifsGuest.getState() == "DOWN":
                self.cifsGuest.start()
 
            ret = self.protocolObj.createCIFSISO(self.targetHost,self.isoSRName,self.vdiName,vmuuid,self.shareName,self.cifsGuest,self.host)
            try:
                sr  = ret.splitlines()[2]
                vdi = ret.splitlines()[3]
            except :
                raise xenrt.XRTFailure("Invalid value was returned from Powershell script %s" % (ret))
            
            if self.targetGuest.getState() == "DOWN":
                self.targetGuest.start()

            sruuid = sr.split("/")[1]
            self.vdiuuid = vdi.split("/")[1]
            self.verifySRCreation(vmuuid,self.host,self.isoSRName,sruuid,self.vdiName,self.vdiuuid,"iso")
            if self.targetGuest.getState() == "UP":
                self.targetGuest.shutdown()
            self.protocolObj.detachISO(vmuuid,self.host.password,self.host.getIP())

            ret = self.verifyIso(self.host,vmuuid,self.vdiName)
            if ret:
                raise xenrt.XRTFailure("iso with the name %s found in CD Drive" % (self.vdiName))

            self.deleteVdi(self.host,self.vdiuuid)

            if self.isForgetSR == True:
                self.protocolObj.forgetSR(sr,self.host.password,self.host.getIP())
            else:
                self.protocolObj.deleteSR(sr,self.host.password,self.host.getIP())
    
            #cant Probe as this is not supported for iso SR

            ret = self.verifySR(self.host,sruuid,self.isoSRName)
            if ret: 
                raise xenrt.XRTFailure("sr with uuid=%s and name %s is found" % (sruuid,self.isoSRName))

        if self.SRTYPE == "NFSSR" or self.SRTYPE == "NFSISOSR":
            nfs = xenrt.resources.NFSDirectory()
            nfsdir = xenrt.command("mktemp -d %s/nfsXXXX" % (nfs.path()), strip = True)

            # Introduce the ISO SR.
            server, path = nfs.getHostAndPath(os.path.basename(nfsdir))

            if self.SRTYPE == "NFSSR":
                params['type'] = "nfs"
                params['server']  = server
                params['serverpath'] = path
                ret = self.protocolObj.createNFSSR(self.isoSRName,server,path)
            if self.SRTYPE == "NFSISOSR":
                location = server + ':' + "/" + path
                ret = self.protocolObj.createNFSISOSR(self.isoSRName,location)

            try:
                sr  = ret.splitlines()[2]
                sruuid = sr.split("/")[1]
            except :
                raise xenrt.XRTFailure("Invalid value was returned from Powershell script %s" % (ret))

            ret = self.verifySR(self.host,sruuid,self.isoSRName)
            if not ret:
                raise xenrt.XRTFailure("sr with uuid=%s and name %s is not found" % (sruuid,self.isoSRName))

            xenrt.TEC().logverbose("NFS SR created successfully")

            if self.isForgetSR == True:
                self.protocolObj.forgetSR(sr)
            else:
                self.protocolObj.deleteSR(sr)

            #probe for the SR, and it is not supported by NFSISOSR
            if self.SRTYPE == "NFSSR":
                ret = self.probeSR(self.SRTYPE,sruuid,params,self.host)
                if self.isForgetSR == True and ret == True:
                    pass
                elif self.isForgetSR == False and ret == False:
                    pass
                else:
                    raise xenrt.XRTFailure("Error occurred while deleting/Forgetting SR with uuid=%s" % (sruuid))

            ret = self.verifySR(self.host,sruuid,self.isoSRName)
            if ret:
                raise xenrt.XRTFailure("sr with uuid=%s and name %s is found" % (sruuid,self.isoSRName))
 
        if self.SRTYPE == "ISCSISR":
            self.guest = self.host.createGenericLinuxGuest(name=self.vmName)
            self.uninstallOnCleanup(self.guest)

            if self.guest.getState() == "DOWN":
                self.guest.start()
            vmuuid = self.guest.getUUID()
          
            try:               
                if self.isChapUser:
                    user = "root"
                    password = self.host.password
                    iqn = self.guest.installLinuxISCSITarget(user=user, password=password)                   
                else:
                    user = None
                    password = None
                    iqn = self.guest.installLinuxISCSITarget()
                self.guest.createISCSITargetLun(0, 128)
            except:
                raise xenrt.XRTFailure("Exception occurred while creating target for iscsi SR")
             
            srSubtype = "lvmoiscsi"
            targetIp =  self.guest.getIP()

            try:
                self.host.execdom0("iptables -D OUTPUT 1")
            except:
                pass

            #probe an SR in order to get the scsi ID and it always returns with Error
            try:
                if self.isChapUser:
                    tempStr = self.host.execdom0("xe sr-probe type=%s device-config:target=%s device-config:targetIQN=%s device-config:chapuser=%s device-config:chappassword=%s" % (srSubtype,targetIp,iqn,user,password))
                else:
                    tempStr = self.host.execdom0("xe sr-probe type=%s device-config:target=%s device-config:targetIQN=%s" % (srSubtype,targetIp,iqn))
            except Exception, e:
                tempStr = str(e.data)

            if not "The SCSIid parameter is missing or incorrect" in tempStr:
                raise xenrt.XRTFailure("Exception occurred while probing SR")

            time.sleep(300)
 
            tempStr = '\n'.join(tempStr.split('\n')[2:])
            temp = parseString(tempStr)
            ids = temp.getElementsByTagName('SCSIid')
            for id in ids:
                for node in id.childNodes:
                    scsiId = (node.nodeValue).strip()

            ret = self.protocolObj.createISCSISR(self.isoSRName,targetIp,iqn,scsiId,user,password)

            try:            
                sr  = ret.splitlines()[2]
                sruuid = sr.split("/")[1]
            except :
                raise xenrt.XRTFailure("Invalid value was returned from Powershell script %s" % (ret))

            ret = self.verifySR(self.host,sruuid,self.isoSRName)
            if not ret:
                raise xenrt.XRTFailure("sr with uuid=%s and name %s is not found" % (sruuid,self.isoSRName))

            xenrt.TEC().logverbose("ISCSI SR created successfully")

            params['type'] = "lvmoiscsi"
            params['target'] = targetIp
            params['iqn'] = iqn
            params['scsiid'] = scsiId
            params['user'] = user
            params['password'] = password
 
            if self.isForgetSR == True:
                self.protocolObj.forgetSR(sr)
            else:
                self.protocolObj.deleteSR(sr)

            #probe SR
            ret = self.probeSR(self.SRTYPE,sruuid,params,self.host)

            if self.isForgetSR == True and ret == True:
                pass
            elif self.isForgetSR == False and ret == False:
                pass
            else:
                raise xenrt.XRTFailure("Error occurred while deleting/Forgetting SR with uuid=%s" % (sruuid))

            try:
                ret = self.verifySR(self.host,sruuid,self.isoSRName)
                if ret:
                    raise xenrt.XRTFailure("sr with uuid=%s and name %s is found" % (sruuid,self.isoSRName))
            except:
                pass

    def postRun(self,arglist):

        if self.SRTYPE == "CIFSISOSR":
            self.protocolObj.deleteSRDirectories(self.shareName)
    
        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()
        if self.guest != None:
            if self.guest.getState() == "UP":
                self.guest.shutdown()

class TC12639(SRFunctions):
    """To Create CIFS ISO SR,attach ISO to VM,dettach ISO and finally delete SR using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    SRTYPE = "CIFSISOSR"
    isoSRName = "cifsISOSR"

class TC12640(SRFunctions):
    """To Create and delete NFS SR using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    SRTYPE = "NFSSR"
    isoSRName = "nfsSR"

class TC12641(SRFunctions):
    """To Create and delete NFS ISOSR using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    SRTYPE = "NFSISOSR"
    isoSRName = "nfsIsoSR"

class TC12702(SRFunctions):
    """To Create and delete ISCSI SR without Chap User and Password using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    SRTYPE = "ISCSISR"
    isoSRName = "iscsiSR"
    isChapUser = False

class TC12703(SRFunctions):
    """To Create and delete ISCSI SR with Chap User and Password using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    SRTYPE = "ISCSISR"
    isoSRName = "iscsiSR"
    isChapUser = True

class TC12705(SRFunctions):
    """To Create and forget NFS SR using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    SRTYPE = "NFSSR"
    isoSRName = "nfsSR"
    isForgetSR = True

class TC12706(SRFunctions):
    """To Create and forget NFS ISOSR using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    SRTYPE = "NFSISOSR"
    isoSRName = "nfsIsoSR"
    isForgetSR = True

class TC12707(SRFunctions):
    """To Create and forget ISCSI SR without Chap User and Password using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    SRTYPE = "ISCSISR"
    isoSRName = "iscsiSR"
    isChapUser = False
    isForgetSR = True

class TC12708(SRFunctions):
    """To Create and forget ISCSI SR with Chap User and Password using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    SRTYPE = "ISCSISR"
    isoSRName = "iscsiSR"
    isChapUser = True
    isForgetSR = True

class TC12709(SRFunctions):
    """To Create CIFS ISO SR,attach ISO to VM,dettach ISO and finally forgeet SR using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    SRTYPE = "CIFSISOSR"
    isoSRName = "cifsISOSR"
    isForgetSR = True

class ExportImportVM(_CimBase):
    """To export and Import a VM using WSMAN and CIM-XML protocol"""

    VMTYPE = None
    EXPORTVMNAME = "Test_Export_VM"
    IMPORTVMNAME = "Test_Import_VM"
    TRANSFERPROTOCOL = None
    SSL = None  
    windows = False
 
    def run(self,arglist):

        if self.VMTYPE == "SMALLVM":
            vmProc = "1"
            vmRam = "256"
            self.guest = self.host.createGenericLinuxGuest(name=self.EXPORTVMNAME)
            self.windows = False
            self.uninstallOnCleanup(self.guest)

        if self.VMTYPE == "MEDIUMVM":
            vmProc = "1"
            vmRam = "1024"
            self.guest = self.host.createGenericWindowsGuest(name=self.EXPORTVMNAME)
            self.windows = True
            self.uninstallOnCleanup(self.guest)

        if self.VMTYPE == "LARGEVM":
            vmProc = "1"
            vmRam = "1024"
            self.guest = self.host.createGenericWindowsGuest(name=self.EXPORTVMNAME,disksize=102400)
            self.windows = True
            self.uninstallOnCleanup(self.guest)

        #shutdown the VM if it is running
        if self.guest.getState() == "UP":
            self.guest.shutdown()

        self.guest.preCloneTailor()
        #shutdown the VM if it is running
        if self.guest.getState() == "UP":
            self.guest.shutdown()

        vmuuid = self.guest.getUUID()
        #Export the VM
        self.protocolObj.exportVM(vmuuid,self.TRANSFERPROTOCOL,self.SSL)

        #Verify whether VM has been exported or not
        vbdcount = self.guest.countVBDs()
        if self.windows:
            vbdcount = vbdcount - 1

        for i in range(vbdcount):
            vdiuuid = self.guest.getDiskVDIUUID(str(i))
            self.protocolObj.verifyExport(vdiuuid,str(i))

        #Import the VM
        vm = self.protocolObj.importVM(vmuuid,self.TRANSFERPROTOCOL,self.SSL,self.IMPORTVMNAME,vmProc,vmRam)        

        #get the vmuuid of the newly created vm
        vmuuid = self.protocolObj.getVMUUID(vm)

        createVif = True

        #verify the newly created vm
        self.verifyVM(vmuuid,self.IMPORTVMNAME,self.guest,self.host,createVif)

    def postRun(self):
   
        self.protocolObj.deleteShareDirectory() 
        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()
        if self.guest != None:
            if self.guest.getState() == "UP":
                self.guest.shutdown()

class TC12642(ExportImportVM):
    """To export and Import a small VM (4 GB) using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    VMTYPE = "SMALLVM"
    TRANSFERPROTOCOL = "bits"
    SSL = "0"

class TC12643(ExportImportVM):
    """To export and Import a medium VM(24 GB) using WSMAN protocol and transferVM using bits protocol"""

    PROTOCOL = "WSMAN"
    VMTYPE = "MEDIUMVM"
    TRANSFERPROTOCOL = "bits"
    SSL = "0"

class TC12644(ExportImportVM):
    """To export and Import a Large VM(100 GB) using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    VMTYPE = "LARGEVM"
    TRANSFERPROTOCOL = "bits"
    SSL = "0"

class CreateVMFromTemplate(_CimBase):
    """To Create a VM from an existing template"""

    VMTYPE = None
    TEMPLATENAME = "Sample"
    CREATEVMNAMEFROMTEMPLATE = "Test_CREATE_VM_TEMPLATE"
    windows = False

    def run(self,arglist):

        if self.VMTYPE == "SMALLVM":
            self.guest = self.host.createGenericLinuxGuest(name=self.TEMPLATENAME)
            self.windows = False
            self.uninstallOnCleanup(self.guest)

        if self.VMTYPE == "MEDIUMVM":
            self.guest = self.host.createGenericWindowsGuest(name=self.TEMPLATENAME)
            self.windows = True
            self.uninstallOnCleanup(self.guest)

        if self.VMTYPE == "LARGEVM":
            self.guest = self.host.createGenericWindowsGuest(name=self.TEMPLATENAME,disksize=102400)
            self.windows = True
            self.uninstallOnCleanup(self.guest)

        if self.guest.getState() == "UP":
            self.guest.shutdown()
   
        self.guest.preCloneTailor() 
        #shutdown the VM if it is running
        if self.guest.getState() == "UP":
            self.guest.shutdown()

        #convert the VM into template
        self.guest.paramSet("is-a-template", "true")

        templateuuid = self.guest.getUUID() 
        self.removeTemplateOnCleanup(self.host, templateuuid) 
        #create vm from the template through  cimserver call
        vm = self.protocolObj.createVMFromTemplate(self.TEMPLATENAME,self.CREATEVMNAMEFROMTEMPLATE)
      
        #get the vmuuid of the newly created vm 
        vmuuid = self.protocolObj.getVMUUID(vm)
 
        createVif = False
        changeVif = True

        #verify the newly created vm
        self.verifyVM(vmuuid,self.CREATEVMNAMEFROMTEMPLATE,self.guest,self.host,createVif,changeVif)

    def postRun(self):

        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()

        if self.guest != None:
            if self.guest.getState() == "UP":
                self.guest.shutdown()

class TC12645(CreateVMFromTemplate):
    """To Create a small VM(4 GB) from an existing template using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    VMTYPE = "SMALLVM"

class TC12646(CreateVMFromTemplate):
    """To Create a medium VM(24 GB) from an existing template using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    VMTYPE = "MEDIUMVM"

class TC12647(CreateVMFromTemplate):
    """To Create a Large VM(100 GB) from an existing template using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    VMTYPE = "LARGEVM"
 
class CopyVM(_CimBase):
    """To Copy a VM"""

    VMTYPE = None
    ORIGVMNAME = "Orig_VM"
    COPYVMNAME = "Copied_VM"
    windows = False

    def run(self,arglist):

        if self.VMTYPE == "SMALLVM":
            self.guest = self.host.createGenericLinuxGuest(name=self.ORIGVMNAME)
            self.windows = False
            self.uninstallOnCleanup(self.guest)

        if self.VMTYPE == "MEDIUMVM":
            self.guest = self.host.createGenericWindowsGuest(name=self.ORIGVMNAME)
            self.windows = True
            self.uninstallOnCleanup(self.guest)

        if self.VMTYPE == "LARGEVM":
            self.guest = self.host.createGenericWindowsGuest(name=self.ORIGVMNAME,disksize=102400)
            self.windows = True
            self.uninstallOnCleanup(self.guest)

        if self.guest.getState() == "UP":
            self.guest.shutdown()
     
        self.guest.preCloneTailor()

        #shutdown the VM if it is running
        if self.guest.getState() == "UP":
            self.guest.shutdown()

        #copy vm from already existing vm
        vm = self.protocolObj.copyVM(self.ORIGVMNAME,self.COPYVMNAME)

        #get the vmuuid of the newly created vm
        vmuuid = self.protocolObj.getVMUUID(vm)

        createVif = False
        changeVif = True

        #verify the newly created vm
        self.verifyVM(vmuuid,self.COPYVMNAME,self.guest,self.host,createVif,changeVif)

    def postRun(self):

        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()

        if self.guest != None:
            if self.guest.getState() == "UP":
                self.guest.shutdown()
 
class TC12648(CopyVM):
    """To Copy a small VM(4 GB) using WSMAN protocol"""
   
    PROTOCOL = "WSMAN"
    VMTYPE = "SMALLVM"

class TC12649(CopyVM):
    """To Copy a medium VM(24 GB) using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    VMTYPE = "MEDIUMVM"

class TC12650(CopyVM):
    """To Copy a Large VM(100 GB) using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    VMTYPE = "LARGEVM"

class HistoricMetricsAll(_CimBase):
    """To fetch the last 5 mins historical metric of host or VM using WSMAN or CIM-XML protocol"""

    SYSTEM = None

    def run(self,arglist):
        
        startTime = None
        params = dict()
        count = 0
        self.guest = None
 
        while 1:        
            if self.SYSTEM == "HOST":

                uuid = self.host.getMyHostUUID()
                params['host'] = 'true'
                params['vm_uuid'] = None
                params['interval'] = '30'

            elif self.SYSTEM == "VM":

                vmName = "VM_Historic_Metric"
                if self.guest == None:
                    self.guest = self.host.createGenericLinuxGuest(name=vmName)
                    self.uninstallOnCleanup(self.guest)

                if self.guest.getState() == "DOWN":
                    self.guest.start()

                if count == 0:
                    #wait for atleast 2 minutes as last 2 minutes VM historical metrics will be captured
                    time.sleep(120)

                uuid = self.guest.getUUID()
                params['vm_uuid'] = uuid
                params['interval'] = '5'
   
            else:
                raise xenrt.XRTFailure("Unknown System type, it should be either HOST or VM")

            ret = self.protocolObj.getHistoricalMetrics(uuid,self.SYSTEM)

            #get the start time and end time of metrics (difference should be of 1 hr)
            try:
                startTimeFloat = ret.splitlines()[2]
                startTime = int(time.mktime(time.gmtime(float(startTimeFloat))))
            except:
                raise xenrt.XRTFailure("Invalid Start time was returned by cimserver")  
 
            if startTime  != "":
             
                #get the historical metrics directly from xenserver
                hostIp = self.host.getIP()
                session = XenAPI.Session('http://%s' % (hostIp))
                session.login_with_password('root',self.host.password)

                params['start'] = startTime
                params['session_id'] = session.handle
                paramstr = "&".join(["%s=%s"  % (k,params[k]) for k in params])
                try:
                    sock = urllib.URLopener().open("http://%s/rrd_updates?%s" % (hostIp,paramstr))
                    xmlsource = sock.read()
                    sock.close()
                    if xmlsource != "":
                        fh = open('%s/httpxmldata.xml' % (xenrt.TEC().getWorkdir()),'w')
                        fh.write(xmlsource)
                        fh.close()
                except:
                    session.close()
                    raise xenrt.XRTFailure("Exception occured while getting historical metrics directly from Xenserver")
                session.close()

                #get the historical metrics xml file created after cim call
                self.protocolObj.getFile()

                #remove \n and \r from the xmlfile generated by powershell script (cimcall)
                os.system("cat %s/xmldata.xml | tr -d '\n' | tr -d '\r' > %s/xml_file.xml" % (xenrt.TEC().getWorkdir(),xenrt.TEC().getWorkdir()))

                try:
                    ret = filecmp.cmp('%s/httpxmldata.xml' % (xenrt.TEC().getWorkdir()),'%s/xml_file.xml' % (xenrt.TEC().getWorkdir()))
                    if ret:
                        xenrt.TEC().logverbose("Two metrics are same, Test case passed")
                        break
                    else:
                        xenrt.TEC().logverbose("Failed attempt as two metrics are different")
                except:
                    raise xenrt.XRTFailure("Exception occured while comparing two metrics")            
            else:
                raise xenrt.XRTFailure("StartTime is zero")
          
            count = count + 1
            if count == 10:

                #Compare the row count fetched from the two xmls 
                try:
                    file1 = "%s/httpxmldata.xml" % (xenrt.TEC().getWorkdir())
                    xmltree = xml.dom.minidom.parse(file1)
                    row = xmltree.getElementsByTagName("rows")          
                    xenserverRowCount = row[0].childNodes[0].data
  
                    file2 = "%s/xml_file.xml" % (xenrt.TEC().getWorkdir())
                    xmltree = xml.dom.minidom.parse(file2)
                    row = xmltree.getElementsByTagName("rows")
                    cimserverRowCount = row[0].childNodes[0].data
                    diff = int(cimserverRowCount) - int(xenserverRowCount)
                except:
                    raise xenrt.XRTFailure("Exception occurred while trying to compare two rows count")

                if diff >5:
                    raise xenrt.XRTFailure("Row count difference is more then 5 and the two metrics are not same(tried 10 attempts)")

                xenrt.TEC().warning("Historic data retrieved using CIM call is not same as fetched directly from xenserver (tried 10 attempts)")
                break
 
    def postRun(self):

        if self.guest != None:
            if self.guest.getState() == "UP":
                self.guest.shutdown()
  
        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()


class TC12659(HistoricMetricsAll):
    """To fetch the last 60 mins historical metric of host using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    SYSTEM = "HOST"

class TC12660(HistoricMetricsAll):
    """To fetch the last 2 mins historical metric of VM using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    SYSTEM = "VM"

class InstantaneousMetric(_CimBase):
    """To fetch various instantaneous metrics of host and VM by using either WSMAN or CIM-XML protocol"""

    METRICTYPE = None

    def prepare(self,arglist):

        _CimBase.prepare(self,[])
        self.cimClass = dict()
        self.cimClass['vmNICSend'] = "Xen_NetworkPortTransmitThroughput"
        self.cimClass['vmNICRecv'] = "Xen_NetworkPortReceiveThroughput"    
        self.cimClass['hostNICSend'] = "Xen_HostNetworkPortTransmitThroughput"
        self.cimClass['hostNICRecv'] = "Xen_HostNetworkPortReceiveThroughput"

    def run(self,arglist):

        count = 0
        vmuuid = None
        pifsvifsName = []

        if self.METRICTYPE.startswith("vm"):
            vmName = "VM_Instantaneous_Metric"
            self.guest = self.host.createGenericLinuxGuest(name=vmName)
            self.uninstallOnCleanup(self.guest)
            vmuuid = self.guest.getUUID()
            if self.guest.getState() == "DOWN":
                self.guest.start()
            dataQuery = "xe vm-data-source-query uuid=%s data-source=" % (vmuuid)
            vifs = self.host.minimalList("vif-list","device",args="vm-uuid=%s" % (vmuuid))

            if self.METRICTYPE == "vmNICSend":
                for vif in vifs:
                    pifsvifsName.append("vif_%s_tx" % (vif))                
                #ping host so that vm should start sending some packets
                hostIPAddr = self.host.getIP()    
                self.guest.execguest("ping -c 20 %s" % (hostIPAddr))

            if self.METRICTYPE == "vmNICRecv":
                for vif in vifs:
                    pifsvifsName.append("vif_%s_rx" % (vif))

        elif self.METRICTYPE.startswith("host"):
            dataQuery = "xe host-data-source-query data-source="
            pifs = self.host.minimalList("pif-list","device")
            if self.METRICTYPE == "hostNICSend":
                for pif in pifs: 
                    pifsvifsName.append("pif_%s_tx" % (pif)) 

            if self.METRICTYPE == "hostNICRecv":
                for pif in pifs:
                    pifsvifsName.append("pif_%s_rx" % (pif))

        for pifvifName in pifsvifsName:
            dataSourceQuery = dataQuery + pifvifName

            metricResult = False
            while 1:

                ret = self.protocolObj.getInstantaneousMetric(self.cimClass[self.METRICTYPE],vmuuid,pifvifName)
                try:
                    metricValue = ret.splitlines()[2]
                except:
                    raise xenrt.XRTFailure("Unable to fetch value for %s thorugh cim call" % pifvifName)

                xenrt.TEC().logverbose("Metric Value for %s fetched from cim server is %s" % (pifvifName,metricValue)) 

                if not metricValue:
                    raise xenrt.XRTFailure("Unable to fetch value for %s through cim call" % pifvifName)

                try:
                    tempStr = self.host.execdom0(dataSourceQuery)         
                    data1 = tempStr.splitlines()
                    data = data1[0]
                    xenrt.TEC().logverbose("Metric Value for %s fetched from xenserver is %s" % (pifvifName,data))
                except:
                    raise xenrt.XRTFailure("Exception occurred while getting Metric value for %s from Xenserver" % pifvifName)
                count = count + 1

                metricResult = self.metricComparison(data,metricValue)

                if metricResult:
                    break

                if count == 10:
                    raise xenrt.XRTFailure("Instantaneous value retrieved using CIM call is not same as fetched directly"
                                           " from xenserver (tried 10 attempts)")

    def postRun(self):

        if self.guest != None:
            if self.guest.getState() == "UP":
                self.guest.shutdown()

        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()

class HostNetworkTransmitThroughput(InstantaneousMetric):
    """To fetch the instantaneous host Network Transmit throughput by using either WSMAN or CIM-XML protocol"""

    METRICTYPE = "hostNICSend"

class TC12661(HostNetworkTransmitThroughput):
    """To fetch the instantaneous host Network Transmit throughput by using WSMAN"""

    PROTOCOL = "WSMAN"

class HostNetworkReceiveThroughput(InstantaneousMetric):
    """To fetch the instantaneous host Network Receive throughput by using either WSMAN or CIM-XML protocol"""

    METRICTYPE = "hostNICRecv"

class TC12662(HostNetworkReceiveThroughput):
    """"To fetch the instantaneous host Network Receive throughput by using either WSMAN protocol"""

    PROTOCOL = "WSMAN"

class VMNetworkTransmitThroughput(InstantaneousMetric):
    """To fetch the instantaneous VM Network Transmit throughput by using either WSMAN or CIM-XML protocol"""

    METRICTYPE = "vmNICSend"

class TC12663(VMNetworkTransmitThroughput):
    """To fetch the instantaneous VM Network Transmit throughput by using WSMAN"""

    PROTOCOL = "WSMAN"

class VMNetworkReceiveThroughput(InstantaneousMetric):
    """To fetch the instantaneous VM Network Receive throughput by using either WSMAN or CIM-XML protocol"""

    METRICTYPE = "vmNICRecv"

class TC12664(VMNetworkReceiveThroughput):
    """"To fetch the instantaneous VM Network Receive throughput by using WSMAN protocol"""

    PROTOCOL = "WSMAN"

class InstantaneousHostCPUMetric(_CimBase):
    """To fetch instantaneous host cpu usage by using either WSMAN or CIM-XML protocol"""

    def run(self,arglist):

        vmuuid = None

        count = 0

        cpuCount = 0
        session = self.host.getAPISession()
        xapi = session.xenapi
        try:
            hostref = xapi.host.get_all()[0]
            host = xapi.host.get_record(hostref)
            cpus = host['host_CPUs']
            for cpu in cpus:
                cpuCount = cpuCount + 1 
        finally:
            self.host.logoutAPISession(session)

        while 1:

            #The reason why data source query is used is because host_CPU returns 0 as CPU usage even though it is very small.
            for i in range(cpuCount):
                dataSourceQuery = "xe host-data-source-query data-source=cpu%s" % (i)
                try:
                    tempStr = self.host.execdom0(dataSourceQuery)
                    data1 = tempStr.splitlines()
                    data = data1[0]
                    xenrt.TEC().logverbose("Host CPU usage for CPU%s fetched from xenserver is %s" % (i,data))
                except:
                    raise xenrt.XRTFailure("Exception occurred while getting Metric value for VM CPU usage from Xenserver")

            ret = self.protocolObj.getInstantaneousHostCpuMetric("Xen_HostProcessorUtilization")
            
            if ret == None or ret == "":
                raise xenrt.XRTFailure("Unable to fetch value for host CPU usage through cim call") 
            for i in range(cpuCount):
                try:
                    metricValue = ret.splitlines()[i + 2]
                except:
                    raise xenrt.XRTFailure("Unable to fetch value for host CPU usage through cim call")
                xenrt.TEC().logverbose("Host CPU usage for CPU%s fetched from cim server is %s" % (i,metricValue))
                if not metricValue:
                    raise xenrt.XRTFailure("Unable to fetch value for host CPU usage through cim call")

            count = count +1
            if count == 5:
                xenrt.TEC().logverbose("5 iterations were done to get the CPU usage, at the moment no procedure is there to compare the two values")
                break

    def postRun(self):

        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()

class InstantaneousvmCPUMetric(_CimBase):
    """To fetch instantaneous vm cpu usage by using either WSMAN or CIM-XML protocol"""

    def run(self,arglist):

        vmuuid = None
        vmName = "VM_CPU_Instantaneous_Metric"
        self.guest = self.host.createGenericLinuxGuest(name=vmName)
        self.uninstallOnCleanup(self.guest)
        vmuuid = self.guest.getUUID()
        if self.guest.getState() == "DOWN":
            self.guest.start()

        count = 0

        dataSourceQuery = "xe vm-data-source-query uuid=%s data-source=cpu0" % (vmuuid)
 
        while 1:
            ret = self.protocolObj.getInstantaneousMetric("Xen_ProcessorUtilization",vmuuid,None)
            try:
                metricValue = ret.splitlines()[2]
            except:
                raise xenrt.XRTFailure("Unable to fetch value for VM CPU usage through cim call")

            xenrt.TEC().logverbose("VM CPU usage fetched from cim server is %s" % (metricValue))

            if not metricValue:
                raise xenrt.XRTFailure("Unable to fetch value for VM CPU usage through cim call")

            try:
                tempStr = self.host.execdom0(dataSourceQuery)
                data1 = tempStr.splitlines()
                data = data1[0]
                xenrt.TEC().logverbose("VM CPU usage fetched from xenserver is %s" % (data))
            except:
                raise xenrt.XRTFailure("Exception occurred while getting Metric value for VM CPU usage from Xenserver")

            count = count +1
            if count == 5:
                xenrt.TEC().logverbose("5 iterations were done to get the CPU usage, at the moment no procedure is there to compare the two values")
                break
 
    def postRun(self):

        if self.guest != None:
            if self.guest.getState() == "UP":
                self.guest.shutdown()

        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()

class TC12667(InstantaneousHostCPUMetric):
    """"To fetch the instantaneous host CPU usage by using WSMAN protocol"""

    PROTOCOL = "WSMAN"

class TC12668(InstantaneousvmCPUMetric):
    """To fetch the instantaneous VM CPU usage by using WSMAN protocol"""

    PROTOCOL = "WSMAN"

class InstantaneousMemoryMetric(_CimBase):
    """To fetch instantaneous allocated and free memory of VM and host using either WSMAN or CIM-XML protocol"""

    METRICTYPE = None

    def run(self,arglist):

        vmuuid = None
        normalisingFactor = 1

        if self.METRICTYPE.startswith("vm"):
            vmName = "VM_MEM_Instantaneous_Metric"
            self.guest = self.host.createGenericLinuxGuest(name=vmName)
            self.uninstallOnCleanup(self.guest)
            vmuuid = self.guest.getUUID()
            if self.guest.getState() == "DOWN":
                self.guest.start()

            tempStr = "xe vm-data-source-query uuid=%s data-source=" % (vmuuid)
            if self.METRICTYPE == "vmAllocatedMemory":
                dataSourceQuery = tempStr + "memory_target"
                normalisingFactor = 1 

            if self.METRICTYPE == "vmFreeMemory":
                normalisingFactor = 1024
                dataSourceQuery = tempStr + "memory_internal_free"

        elif self.METRICTYPE.startswith("host"):
            normalisingFactor = 1024
            tempStr = "xe host-data-source-query data-source="
            if self.METRICTYPE == "hostAllocatedMemory":
                dataSourceQuery = tempStr + "memory_total_kib"

            if self.METRICTYPE == "hostFreeMemory":
                dataSourceQuery = tempStr + "memory_free_kib"

        ret = self.protocolObj.getInstantaneousMemoryMetric(self.METRICTYPE,vmuuid)
        try:
            metricValue = ret.splitlines()[2]
        except:
            raise xenrt.XRTFailure("Unable to fetch value for %s through cim call" % self.METRICTYPE)

        xenrt.TEC().logverbose("Metric Value for %s fetched from cim server is %s" % (self.METRICTYPE,metricValue))

        if not metricValue:
            raise xenrt.XRTFailure("Unable to fetch value for %s through cim call" % self.METRICTYPE)

        try:
            tempStr = self.host.execdom0(dataSourceQuery)
            data1 = tempStr.splitlines()
            data = data1[0]
            actualValue = float(data) * normalisingFactor
            xenrt.TEC().logverbose("Metric Value for %s fetched from xenserver is %s" % (self.METRICTYPE,actualValue))
        except:
            raise xenrt.XRTFailure("Exception occurred while getting Metric value for %s from Xenserver" % self.METRICTYPE)

        if actualValue != float(metricValue):
            raise xenrt.XRTFailure("Instantaneous value retrieved using CIM call is not same as fetched directly"
                                   " from xenserver")


    def postRun(self):

        if self.guest != None:
            if self.guest.getState() == "UP":
                self.guest.shutdown()

        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()

class HostInstantaneousAllocMemory(InstantaneousMemoryMetric):
    """To fetch the instantaneous host total memory by using WSMAN or CIM-XML protocol"""

    METRICTYPE = "hostAllocatedMemory" 

class TC12669(HostInstantaneousAllocMemory):
    """To fetch the instantaneous host total memory by using WSMAN protocol"""

    PROTOCOL = "WSMAN"

class HostInstantaneousFreeMemory(InstantaneousMemoryMetric):
    """To fetch the instantaneous host free memory by using WSMAN or CIM-XML protocol"""

    METRICTYPE = "hostFreeMemory"

class TC12670(HostInstantaneousFreeMemory):
    """To fetch the instantaneous host free memory by using WSMAN protocol"""

    PROTOCOL = "WSMAN"

class VMInstantaneousAllocMemory(InstantaneousMemoryMetric):
    """To fetch the instantaneous vm total memory by using WSMAN or CIM-XML protocol"""

    METRICTYPE = "vmAllocatedMemory"

class TC12671(VMInstantaneousAllocMemory):
    """To fetch the instantaneous vm total memory by using WSMAN protocol"""

    PROTOCOL = "WSMAN"

class VMInstantaneousFreeMemory(InstantaneousMemoryMetric):
    """To fetch the instantaneous vm free memory by using WSMAN or CIM-XML protocol"""

    METRICTYPE = "vmFreeMemory"

class TC12672(VMInstantaneousFreeMemory):
    """To fetch the instantaneous vm free memory by using WSMAN protocol"""

    PROTOCOL = "WSMAN"

class InstDiskMetric(_CimBase):
    """To fetch instantaneous various disk metrics of VM using either WSMAN or CIM-XML protocol"""

    METRICTYPE = None
    VMTYPE = None

    def prepare(self,arglist):

        _CimBase.prepare(self,[])
        self.cimClass = dict()
        self.cimClass['vmDiskRead'] = "Xen_DiskReadThroughput"
        self.cimClass['vmDiskWrite'] = "Xen_DiskWriteThroughput"
        self.cimClass['vmDiskReadLatency'] = "Xen_DiskReadLatency"
        self.cimClass['vmDiskWriteLatency'] = "Xen_DiskWriteLatency"

    def run(self,arglist):
 
        vmName = "VM_DISK_METRIC"
        vbdsName = []
        count = 0 
        enableRecording = None
        dataSourceQuery  = None
        enable = False
        vbd = None
        if self.VMTYPE == "LINUX":
            self.guest = self.host.createGenericLinuxGuest(name=vmName)
        elif self.VMTYPE == "WINDOWS":
            self.guest = self.host.createGenericWindowsGuest(name=vmName)
         
        if self.guest != None:
            self.uninstallOnCleanup(self.guest)
            vmuuid = self.guest.getUUID()
            if self.guest.getState() == "DOWN":
                self.guest.start()
        else:
            raise xenrt.XRTFailure("Error occurred while creating VM")
 
        tempStr = "xe vm-data-source-query uuid=%s data-source=" % (vmuuid)
        enableStr = "xe vm-data-source-record vm=%s data-source=" % (vmName)

        vbds = self.host.minimalList("vbd-list","device",args="vm-uuid=%s" % (vmuuid))

        if self.METRICTYPE == "vmDiskRead":
            for vbd in vbds:
                if vbd != "" and vbd != "hdd":
                    vbdsName.append("vbd_%s_read" % (vbd))
        elif self.METRICTYPE == "vmDiskWrite":
            for vbd in vbds:
                if vbd != "" and vbd != "hdd":
                    vbdsName.append("vbd_%s_write" % (vbd))
        elif self.METRICTYPE == "vmDiskReadLatency":
            for vbd in vbds:
                if vbd != "" and vbd != "hdd":
                    vbdsName.append("vbd_%s_read_latency" % (vbd))
            enable = True
        elif self.METRICTYPE == "vmDiskWriteLatency":
            for vbd in vbds:
                if vbd != "" and vbd != "hdd":
                    vbdsName.append("vbd_%s_write_latency" % (vbd))
            enable = True

        #By default recording of read and write latency metric is not enabled,so it needs to be enabled
        for vbdName in vbdsName:
            dataSourceQuery = tempStr + vbdName
            if enable:
                enableRecording = enableStr + vbdName
                self.host.execdom0(enableRecording)

            metricResult = False
            count = 0
            while 1:
                ret = self.protocolObj.getInstantaneousDiskMetrics(self.cimClass[self.METRICTYPE],vbdName)
                try:
                    metricValue = ret.splitlines()[2]
                except:
                    raise xenrt.XRTFailure("Unable to fetch value for %s through cim call" % self.METRICTYPE)

                xenrt.TEC().logverbose("Metric Value for %s fetched from cim server is %s" % (self.METRICTYPE,metricValue))

                if not metricValue:
                    raise xenrt.XRTFailure("Unable to fetch value for %s through cim call" % self.METRICTYPE)

                try:
                    tempStr = self.host.execdom0(dataSourceQuery)
                    data1 = tempStr.splitlines()
                    data = data1[0]
                    xenrt.TEC().logverbose("Metric Value for %s fetched from xenserver is %s" % (self.METRICTYPE,data))
                except:
                    raise xenrt.XRTFailure("Exception occurred while getting Metric value for %s from Xenserver" % self.METRICTYPE)
                count = count + 1
        
                metricResult = self.metricComparison(data,metricValue)

                if metricResult:
                    break

                if count == 10:
                    raise xenrt.XRTFailure("Instantaneous value retrieved using CIM call is not same as fetched directly"
                                           " from xenserver (tried 10 attempts)")

class DiskReadMetric(InstDiskMetric):
    """To fetch the instantaneous disk read metric using either WSMAN and CIM-XML protocol for LINUX VM"""

    METRICTYPE = "vmDiskRead"

class TC12679(DiskReadMetric):
    """To fetch the instantaneous disk read metric for LINUX VM using WSMAN protocol"""

    PROTOCOL = "WSMAN" 
    VMTYPE = "LINUX"

class TC12680(DiskReadMetric):
    """To fetch the instantaneous disk read metric for WINDOWS VM using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    VMTYPE = "WINDOWS"

class DiskWriteMetric(InstDiskMetric):
    """To fetch the instantaneous disk write metric using either WSMAN and CIM-XML protocol"""

    METRICTYPE = "vmDiskWrite"

class TC12681(DiskWriteMetric):
    """To fetch the instantaneous disk write metric for LINUX VM using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    VMTYPE = "LINUX"

class TC12682(DiskWriteMetric):
    """To fetch the instantaneous disk write metric for WINDOWS VM using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    VMTYPE = "WINDOWS"

class DiskReadLatency(InstDiskMetric):
    """To fetch the instantaneous disk read latency metric using either WSMAN and CIM-XML protocol"""

    METRICTYPE = "vmDiskReadLatency"

class TC12683(DiskReadLatency):
    """To fetch the instantaneous disk read latency metric for LINUX VM using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    VMTYPE = "LINUX"

class TC12684(DiskReadLatency):
    """To fetch the instantaneous disk read latency metric for WINDOWS VM using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    VMTYPE = "WINDOWS"

class DiskWriteLatency(InstDiskMetric):
    """To fetch the instantaneous disk write latency metric using either WSMAN and CIM-XML protocol"""

    METRICTYPE = "vmDiskWriteLatency"

class TC12685(DiskWriteLatency):
    """To fetch the instantaneous disk write latency metric for LINUX VM using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    VMTYPE = "LINUX"

class TC12686(DiskWriteLatency):
    """To fetch the instantaneous disk write latency metric for WINDOWS VM using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    VMTYPE = "WINDOWS"

class VdiFunctions(_CimBase):
    """To verify the create, Attach, dettach and delete of VDI to/from VM using either WSMAN or CIM-XML protocol"""

    def run(self,arglist):

        vdiParams = dict()
        vmuuid = None
        vmName = "VM_VDI"
        vdiName = "VM_VDI"
        vdiSize = 100
        self.guest = self.host.createGenericLinuxGuest(name=vmName)
        self.uninstallOnCleanup(self.guest)
        vmuuid = self.guest.getUUID()
        if self.guest.getState() == "UP":
            self.guest.shutdown()

        ret = self.protocolObj.createVdi(vdiName,vdiSize)
        try:
            vdiuuid = ret.splitlines()[2]
            vdiParams['DeviceId'] = ret.splitlines()[3]
            vdiParams['CreationClassName'] = ret.splitlines()[4]
            vdiParams['SystemCreationClassName'] = ret.splitlines()[5]
            vdiParams['SystemName'] = ret.splitlines()[6]
        except:
            raise xenrt.XRTFailure("Error occured while getting the vdi uuid/vdi DeviceId")        

        virtualSize = vdiSize * 1024 * 1024

        #verify the creation of VDI
        ret = self.verifyVDIExist(vdiuuid,virtualSize,vdiName,self.host)

        if ret == False:
            raise xenrt.XRTFailure("VDI creation Failed")

        xenrt.TEC().logverbose("VDI created successfully")

        #attach VDI to VM 
        self.protocolObj.attachVdiToVM(vmuuid,vdiParams['DeviceId'],vdiuuid)
 
        #verify whether VDI has been attached to VM or not
        ret = self.verifyIsVDIAttached(vmuuid,vdiuuid,self.host)
        if ret == False:
            raise xenrt.XRTFailure("VDI is not attached to VM with uuid %s" % (vmuuid))

        xenrt.TEC().logverbose("VDI attached to VM with uuid %s successfully" % (vmuuid))
 
        #get VBD uuid usirng VDI uuid
        ret = self.protocolObj.getVBDuuid(vdiuuid,vmuuid)

        try:
            vbdInstanceID  = ret.splitlines()[2]
            vbduuid = vbdInstanceID.split("/")[1]
        except :
            raise xenrt.XRTFailure("Invalid value(InstanceID) was returned from Powershell script %s" % (ret))

        #verify correct VBD is attached to correct VM
        ret = self.verifyIsVBDAttached(vmuuid,vbduuid,self.host)
        if ret == False:
            raise xenrt.XRTFailure("VBD is not attached to VM with uuid %s" % (vmuuid)) 

        #start VM to check whether VM can boots up or not
        if self.guest.getState() == "DOWN":
            self.guest.start()

        #shutdown the VM 
        if self.guest.getState() == "UP":
            self.guest.shutdown()

        #detach VDI from VM 
        self.protocolObj.dettachVBDFromVM(vbdInstanceID)

        #verify whether VDI has been detached form VM or not
        ret = self.verifyIsVDIAttached(vmuuid,vdiuuid,self.host)
        if ret == True:
            raise xenrt.XRTFailure("VDI is still attached to VM with uuid %s" % (vmuuid))

        #Verify whether VBD has been detached from VM or not
        ret = self.verifyIsVBDAttached(vmuuid,vbduuid,self.host)
        if ret == True:
            raise xenrt.XRTFailure("VBD is still attached to VM with uuid %s" % (vmuuid))

        #delete VDI 
        self.protocolObj.deleteVdi(vdiParams)  

        #Verify Whether VDI has been deleted or not
        ret = self.verifyVDIExist(vdiuuid,virtualSize,vdiName,self.host)

        if ret == True:
            raise xenrt.XRTFailure("VDI with vdi Name %s still exist" % (vdiName))

        xenrt.TEC().logverbose("VDI Deleted successfully")

    def postRun(self):

        if self.guest != None:
            if self.guest.getState() == "UP":
                self.guest.shutdown()

        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()

class TC12718(VdiFunctions):
    """To verify the create, Attach, dettach and delete of VDI to/from VM using WSMAN protocol"""

    PROTOCOL = "WSMAN"

class TC12719(_CimBase):
    """To verify that if cimserver dies due to any reason then it should come up on its own within 2 minutes"""

    def run(self,arglist):

        command = "ps ux | awk '/cimserver/ && !/awk/ {print $2}'"

        #Get the process id of cimserver
        try:
            data = self.host.execdom0("%s" % (command))
            pid = data.splitlines()[0]
            processId = int(data)
        except:
            raise xenrt.XRTFailure("CimServer is not running")

        if processId  > 0:
            try:
                #kill Cimserver
                self.host.execdom0("nohup kill -9 %s &>/dev/null 2>/dev/null" % pid)
            except:
                raise xenrt.XRTFailure("Exception occured while killing CimServer")
        else:
            raise xenrt.XRTFailure("Invalid process ID")

        timeout = 120
        deadline = xenrt.timenow() + timeout
        pollPeriod = 5
        time.sleep(5)
        while 1:
            ret = _CIMInterface.checkCimServerRunning(self,self.host)
            if ret:
                #give some time to cimserver to come up
                time.sleep(5)
                break
            if xenrt.timenow() > deadline:
                raise xenrt.XRTFailure("Timed out waiting for CimServer to come up")
            time.sleep(pollPeriod)

        protocolObj = _CIMInterface.createProtocolObject(self,"WSMAN")
        protocolObj.prepare(self,self.host)
        xenrt.TEC().logverbose("CIMSERVER is bind to port 5988 and is responding to WSMAN requests")

        protocolObj = _CIMInterface.createProtocolObject(self,"CIMXML")
        protocolObj.prepare(self,self.host)
        xenrt.TEC().logverbose("CIMSERVER is responding to CIMXML requests")

class ModifyProcessor(_CimBase):
    """To increase or decrease the number of processors on VM using either WSMAN or CIM-XML protocol"""

    def run(self,arglist):

        vmName = "Modify_Processor_Count_VM"

        self.guest = self.host.createGenericLinuxGuest(name=vmName)
        self.uninstallOnCleanup(self.guest)
        if self.guest.getState() == "UP":
            self.guest.shutdown()

        #Add one more processor to VM
        procCount = 2
        self.protocolObj.modifyProcessor(vmName,procCount)

        #verify processor count of VM
        if procCount != self.guest.cpuget():  
            raise xenrt.XRTFailure("CPU count reported by Dom0 which is %s is not matching with the set value which is %s" % (str(self.guest.cpuget()),str(procCount))) 

        #Start VM to check wether VM is coming up after adding one more processor
        self.guest.start()  
 
        #shutdown VM
        self.guest.shutdown()

        #Add one more processor to VM
        procCount = 3
        self.protocolObj.modifyProcessor(vmName,procCount)

        #verify processor count of VM
        if procCount != self.guest.cpuget():
            raise xenrt.XRTFailure("CPU count reported by Dom0 which is %s is not matching with the set value which is %s" % (str(self.guest.cpuget()),str(procCount)))

        #Start VM to check wether VM is coming up after adding one more processor
        self.guest.start()

        #shutdown VM
        self.guest.shutdown()

        #Remove 2 processora from VM
        procCount = 1
        self.protocolObj.modifyProcessor(vmName,procCount)

        #verify processor count of VM
        if procCount != self.guest.cpuget():
            raise xenrt.XRTFailure("CPU count reported by Dom0 which is %s is not matching with the set value which is %s" % (str(self.guest.cpuget()),str(procCount)))

        #Start VM to check wether VM is coming up after adding one more processor
        self.guest.start()

        self.guest.shutdown()

    def postRun(self):

        if self.guest != None:
            if self.guest.getState() == "UP":
                self.guest.shutdown()

        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()

class TC12762(ModifyProcessor): 
    """To increase or decrease the number of processors on VM using WSMAN protocol"""

    PROTOCOL = "WSMAN"

class ModifyMemory(_CimBase):
    """To increase or decrease VM Memory using either WSMAN or CIM-XML protocol"""

    def run(self,arglist):

        vmName = "Modify_Memory_Count_VM"

        self.guest = self.host.createGenericLinuxGuest(name=vmName)
        self.uninstallOnCleanup(self.guest)
        if self.guest.getState() == "UP":
            self.guest.shutdown()

        #Increase memory of VM from 256 to 512
        vmMemory = 512
        self.protocolObj.modifyMemory(vmName,vmMemory)

        #verify VM memory
        if vmMemory != self.guest.memget():
            raise xenrt.XRTFailure("Memory reported by Dom0 which is %s is not matching with the set value which is %s" % (str(self.guest.memget()),str(vmMemory)))

        #Start VM to check wether VM is coming up after increasing memory
        self.guest.start()

        #shutdown VM
        self.guest.shutdown()

        #Increase memory of VM from 512 to 1024
        vmMemory = 1024
        self.protocolObj.modifyMemory(vmName,vmMemory)

        #verify VM memory
        if vmMemory != self.guest.memget():
            raise xenrt.XRTFailure("Memory reported by Dom0 which is %s is not matching with the set value which is %s" % (str(self.guest.memget()),str(vmMemory)))

        #Start VM to check wether VM is coming up after increasing memory
        self.guest.start()

        #shutdown VM
        self.guest.shutdown()

        #Decrease memory from 1024 to 256
        vmMemory = 256
        self.protocolObj.modifyMemory(vmName,vmMemory)

        #verify processor count of VM
        if vmMemory != self.guest.memget():
            raise xenrt.XRTFailure("Memory reported by Dom0 which is %s is not matching with the set value which is %s" % (str(self.guest.memget()),str(vmMemory)))

        #Start VM to check wether VM is coming up after adding one more processor
        self.guest.start()

        self.guest.shutdown()

    def postRun(self):

        if self.guest != None:
            if self.guest.getState() == "UP":
                self.guest.shutdown()

        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()

class TC12763(ModifyMemory):
    """To increase or decrease the VM Memory using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    
class CDDvdFunctions(_CimBase): 
    """To verify the creation and deletion of CD/DVD drive to/from VM using either CIM-XML or WSMAN protocol""" 

    def run(self,arglist):

        vmName = "VM_CD_DVD"
       
        self.guest = self.host.createGenericWindowsGuest(name=vmName)
        self.uninstallOnCleanup(self.guest)

        vmuuid = self.guest.getUUID()
        if self.guest.getState() == "UP":
            self.guest.shutdown()

        #get vbd uuid
        vbduuid = self.getVbduuid(vmuuid,self.host) 
 
        #remove cd/dvd drive from VM using WSMAN protocol
        self.protocolObj.remCDDVDDrive(vmuuid,"DVD",vbduuid)

        time.sleep(5) 

        #Verify whether DVD drive has been removed from VM or not
        ret = self.verifyCDDVDDrive(vmuuid,vmName,self.host)
        if ret:
            raise xenrt.XRTFailure("DVD drive has not been removed")

        #Add CD drive to VM
        self.protocolObj.addCDDVDDrive(vmuuid,"CD")

        time.sleep(5)

        #Verify whether CD drive has been created and attached to VM or not
        ret = self.verifyCDDVDDrive(vmuuid,vmName,self.host)
        if not ret:
            raise xenrt.XRTFailure("CD drive has not been created")

        self.guest.start()
        self.guest.shutdown()

        #get vbd uuid
        vbduuid = self.getVbduuid(vmuuid,self.host)

        #Remove CD drive from VM
        self.protocolObj.remCDDVDDrive(vmuuid,"CD",vbduuid)

        time.sleep(5)

        #Verify whether CD drive has been removed from VM or not
        ret = self.verifyCDDVDDrive(vmuuid,vmName,self.host)
        if ret:
            raise xenrt.XRTFailure("CD drive has not been removed")

        #Add DVD drive to VM
        self.protocolObj.addCDDVDDrive(vmuuid,"DVD")

        time.sleep(5)

        #Verify whether DVD drive has been created and attached to VM or not
        ret = self.verifyCDDVDDrive(vmuuid,vmName,self.host)
        if not ret:
            raise xenrt.XRTFailure("DVD drive has not been created")

        self.guest.start()
        self.guest.shutdown()

    def postRun(self):

        if self.guest != None:
            if self.guest.getState() == "UP":
                self.guest.shutdown()

        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()

class TC12764(CDDvdFunctions):
    """To verify the creation and deletion of CD/DVD drive to/from VM using WSMAN protocol"""

    PROTOCOL = "WSMAN"

class SnapShotFunctions(_CimBase):
    """To verify the create,delete, apply of snapshot of VM and creation of VM from snapshot using either CIM-XML or WSMAN protocol"""

    def run(self,arglist):

        vmName = "Snapshot_VM"
        snapshotName = "Snaphsot_1"
        vmNameForSnapshop = "VM_CREATED_FROM_SNAPSHOT"
        directoryName = "SNAPSHOT_DIRECTORY"

        self.guest = self.host.createGenericWindowsGuest(name=vmName)
        self.uninstallOnCleanup(self.guest)

        #shutdown the VM if it is running
        if self.guest.getState() == "UP":
            self.guest.shutdown()

        self.guest.preCloneTailor()

        if self.guest.getState() == "DOWN":
            self.guest.start()
        vmuuid = self.guest.getUUID()

        #update xmlRPC on the guest
        self.guest.xmlrpcUpdate()

        #take snapshot
        ret = self.protocolObj.takeSnapshot(vmuuid,snapshotName)
        try:
            snapshotID = ret.splitlines()[2]
            snapshotuuid = snapshotID.split(":")[1]
        except:
            raise xenrt.XRTFailure("Unable to fetch SnapshotUUID,Problem occurred while taking snapshot of VM")
       
        #verify whether the snapshot has been taken correctly or not
        ret = self.isSnapshotExist(snapshotuuid,snapshotName,self.host)

        if not ret:
            raise xenrt.XRTFailure("Snapshot %s does not exist" % (snapshotName))

        self.guest.checkSnapshot(snapshotuuid)

        xenrt.TEC().logverbose("Snapshot of VM %s created with name %s" % (vmName,snapshotName))

        #Create a directory on guest
        try:
            self.guest.xmlrpcExec("mkdir c:\%s" % (directoryName))
        except:
            raise xenrt.XRTFailure("Error occurred while created directory on guest") 

        #Apply snapshot
        self.protocolObj.applySnapshot(snapshotID)
 
        #verify whether snapshot has been applied or not by verifying whether the directory still exists or not
        try:
            ret = self.guest.xmlrpcExec("dir c:\%s" % (directoryName),returndata = True)
            if not "File Not Found" in ret:
                raise xenrt.XRTFailure("%s Directory still exists, Snapshot was not applied properly" % (directoryName))
        except:
            pass 

        if self.guest.getState() == "UP":
            self.guest.shutdown()

        xenrt.TEC().logverbose("Snapshot %s applied on VM %s" % (snapshotName,vmuuid))

        #Create VM from Snapshot
        ret = self.protocolObj.createVMFromSnapshot(vmNameForSnapshop,snapshotID)
        try:
            vm = ret.splitlines()[2]
        except:
            raise xenrt.XRTFailure("Error occured while trying to get VM details")       
     
        #get the vmuuid of the newly created vm
        newvmuuid = self.protocolObj.getVMUUID(vm)

        createVif = False
        changeVif = True

        #verify the newly created vm
        self.verifyVM(newvmuuid,vmNameForSnapshop,self.guest,self.host,createVif,changeVif)

        xenrt.TEC().logverbose("VM with uuid %s created from snapshot %s " % (newvmuuid,snapshotName))

        #Destroy snapshot
        self.protocolObj.destroySnapshot(snapshotID)

        #verify whether Snapshot has been destroyed or not
        ret = self.isSnapshotExist(snapshotID,snapshotName,self.host)
      
        if ret:
            raise xenrt.XRTFailure("Snapshot %s still exist" % (snapshotName))
     
        xenrt.TEC().logverbose("Snapshot with name %s destroyed" % (snapshotName))

    def postRun(self):

        if self.guest != None:
            if self.guest.getState() == "UP":
                self.guest.shutdown()

        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()
  
class TC13156(SnapShotFunctions): 
    """To verify the create,delete, apply of snapshot of VM and creation of VM from snapshot using WSMAN protocol"""

    PROTOCOL = "WSMAN"

class GetSnapshotList(_CimBase):
    """To verify the snapshot list on host through cimserver using either WSMAN or CIM-XML protocol """

    TOTALSNAPSHOTS = 3
  
    def run(self,arglist):

        self.snapshots = {}
        vmName = "Snapshot_VM"
        snapshotName = "Snaphsot_"
        cimserverSnapshots = []

        self.guest = self.host.createGenericLinuxGuest(name=vmName)
        self.uninstallOnCleanup(self.guest)

        if self.guest.getState() == "DOWN":
            self.guest.start()
        vmuuid = self.guest.getUUID()

        #create 3 snapshots
        for i in range(self.TOTALSNAPSHOTS):
            name = snapshotName + str(i)
            self.snapshots[i] = self.guest.snapshot(name=name)

        #get the snapshot uuid list through cimserver
        ret = self.protocolObj.getSnapshotList()
        i = 0
        try:
            for i in range(self.TOTALSNAPSHOTS):
                snapshotID = ret.splitlines()[2+i]
                cimserverSnapshots.append(snapshotID.split(":")[1])
        except:
            raise xenrt.XRTFailure("Error occured while fetching snapshot list through cimserver")        

        i = 0
        for i in range(self.TOTALSNAPSHOTS):
            if not self.snapshots[i] in cimserverSnapshots:
                raise xenrt.XRTFailure("Snapshot with uuid %s is not found in the list fetched through cimserver" %(self.snapshots[i]))
            
        xenrt.TEC().logverbose("The number of snapshots fetched through cimserver matches with the number created directly on xenserver")        

    def postRun(self):

        for i in range(self.TOTALSNAPSHOTS):
            self.guest.removeSnapshot(self.snapshots[i])

        if self.guest != None:
            if self.guest.getState() == "UP":
                self.guest.shutdown()

        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()

class TC13157(GetSnapshotList):
    """To verify the snapshot list on host through cimserver using WSMAN protocol"""

    PROTOCOL = "WSMAN"

class VdiPropertiesModification(_CimBase):
    """To modify the vdi size and name through cimserver using either CIM-XML or WSMAN protocol """

    TOTALSNAPSHOTS = 3

    def run(self,arglist):

        vdiNewName = "New_VDI"
        vmName = "VDI_MOD_PROPERTIES_VM"
        #set new size of VDI to be 50 GB
        vdiNewSize = 53687091200  
   
        self.guest = self.host.createGenericWindowsGuest(name=vmName)
        self.uninstallOnCleanup(self.guest)
        vmuuid = self.guest.getUUID()
      
        device = 0
        vdiuuid = self.guest.getDiskVDIUUID(str(device))

        if self.guest.getState() == "UP":
            self.guest.shutdown()

        data = self.host.execdom0("xe vdi-param-get uuid=%s param-name=name-label" % (vdiuuid))
        try:
            vdiName = data.splitlines()[0]
        except:
            raise xenrt.XRTFailure("Unable to fetch VDI Name")

        #modify VDI size and VDI name
        self.protocolObj.modifyVdiProperties(vmuuid,vdiNewSize,vdiNewName,vdiName)

        #verify VDI name
        data = self.host.execdom0("xe vdi-param-get uuid=%s param-name=name-label" % (vdiuuid))
        if not vdiNewName == data.splitlines()[0]:
            raise xenrt.XRTFailure("VDI Name is still the same and it has not been changed to %s" % (vdiNewName))

        xenrt.TEC().logverbose("VDI Name changed to %s from %s" %(vdiNewName,vdiName))

        #verify VDI size
        data = self.host.execdom0("xe vdi-param-get uuid=%s param-name=virtual-size" % (vdiuuid))
        if str(vdiNewSize) <> data.splitlines()[0]:
            raise xenrt.XRTFailure("VDI size is still the same and it has not been changed")

        xenrt.TEC().logverbose("VDI size changed to %s" %(vdiNewSize))
        
    def postRun(self):

        if self.guest != None:
            if self.guest.getState() == "UP":
                self.guest.shutdown()

        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()

class TC13158(VdiPropertiesModification):
    """To modify the vdi size and name through cimserver using WSMAN protocol """

    PROTOCOL = "WSMAN"

class VMSettingsModification(_CimBase):
    """To modify the VM name and description through cimserver using either CIM-XML or WSMAN protocol"""

    def run(self,arglist):

        vmName = "VM_SETTINGS_MOD"
        vmNewName = "VM_MODIFIED_NAME"
        vmDescription = "This has been modified through cimserver"

        self.guest = self.host.createGenericLinuxGuest(name=vmName)
        self.uninstallOnCleanup(self.guest)
        vmuuid = self.guest.getUUID()

        instanceID = "Xen:" + vmuuid 

        #Modify VM Name and VM description through Cimserver
        self.protocolObj.modifyVMSettings(instanceID,vmNewName,vmDescription) 

        #Verify new VM Name
        rValue = self.host.execdom0("xe vm-param-get uuid=%s param-name=name-label" % (vmuuid))
        data = rValue.splitlines()[0]

        if not data == vmNewName:
            raise xenrt.XRTFailure("VM Name does not changed to %s" % (vmNewName))
      
        xenrt.TEC().logverbose("VM Name changed to %s" %(vmNewName))

        #Verify new VM Description
        rValue = self.host.execdom0("xe vm-param-get uuid=%s param-name=name-description" % (vmuuid))
        data = rValue.splitlines()[0]

        if not data == vmDescription:
            raise xenrt.XRTFailure("VM Description does not changed to %s" % (vmDescription))

        xenrt.TEC().logverbose("VM Description changed to %s" %(vmDescription))

    def postRun(self):

        if self.guest != None:
            if self.guest.getState() == "UP":
                self.guest.shutdown()

        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()

class TC13159(VMSettingsModification):
    """To modify the VM name and description through cimserver using WSMAN protocol"""

    PROTOCOL = "WSMAN"

class TemplateOperations(_CimBase):
    """To verify the creation and deletion of template from VM using either CIM-XML or WSMAN protocol"""

    def run(self,arglist):

        vmName = "VM_TEMPLATE_OPERATION"

        self.guest = self.host.createGenericWindowsGuest(name=vmName)
        self.uninstallOnCleanup(self.guest)
        if self.guest.getState() == "UP":
            self.guest.shutdown()

        self.guest.preCloneTailor()
        #shutdown the VM if it is running
        if self.guest.getState() == "UP":
            self.guest.shutdown()

        vmuuid = self.guest.getUUID()
      
        #Convert VM to Template through cimserver
        self.protocolObj.convertVMToTemplate(vmuuid)

        #vm is now template
        templateuuid = vmuuid

        #Verify whether template has been created or not
        ret = self.isTemplateExist(templateuuid,vmName,self.host)

        if not ret:
            raise xenrt.XRTFailure("Template %s does not exists" % (vmName))

        xenrt.TEC().logverbose("Template created with name %s" %  (vmName))

        #create vm from the template through cimserver call
        vm = self.protocolObj.createVMFromTemplate(vmName,vmName)

        #get the vmuuid of the newly created vm
        vmuuid = self.protocolObj.getVMUUID(vm)
        createVif = False
        changeVif = True

        #verify the newly created vm
        self.verifyVM(vmuuid,vmName,self.guest,self.host,createVif,changeVif)

        xenrt.TEC().logverbose("VM created from template %s" % (vmName))

        #Delete the template 
        self.protocolObj.deleteVM(templateuuid)

        ret = self.isTemplateExist(templateuuid,vmName,self.host)

        if ret:
            raise xenrt.XRTFailure("Template %s still exists" % (vmName))

        xenrt.TEC().logverbose("Template Deleted with name %s" %  (vmName))

    def postRun(self):

        if self.guest != None:
            if self.guest.getState() == "UP":
                self.guest.shutdown()

        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()

class TC13170(TemplateOperations):
    """To verify the creation and deletion of template from VM using WSMAN protocol"""

    PROTOCOL = "WSMAN" 

class ExportImportSnapshotTree(_CimBase):
    """To verify the export and import of VM snapshot tree using either CIM-XML or WSMAN protocol"""

    SNAPSHOTPATTERN = None
    ISWINDOWS = False
    LARGEVM = False
    SIZE = None 
    COPY = False
    STATICIP = None

    def run(self,arglist):

        vmName = "VM_Export_Snapshot_Tree"
        vmImportName = "VM_Import_Snapshot_Tree"
        transProtocol = "bits"
        ssl = "0"

        if self.ISWINDOWS:
            if self.LARGEVM:        
                self.guest = self.host.createGenericWindowsGuest(name=vmName,disksize=self.SIZE)
            else:
                self.guest = self.host.createGenericWindowsGuest(name=vmName)
        else:
            self.guest = self.host.createGenericLinuxGuest(name=vmName)
        self.uninstallOnCleanup(self.guest)

        if self.guest.getState() == "UP":
            self.guest.shutdown()
        self.guest.preCloneTailor()

        if self.COPY:
            if self.guest.getState() == "UP":
                self.guest.shutdown()
            temp = self.guest.copyVM("VM_Copy_Export_Snapshot_Tree")
            self.guest = temp
            self.uninstallOnCleanup(self.guest)
            if self.guest.getState() == "UP":
                self.guest.shutdown()
            #Preclone tailor is again requuired for the copied VM
            self.guest.preCloneTailor()

        #start the VM if it is halted
        if self.guest.getState() == "DOWN":
            self.guest.start()

        if self.LARGEVM:
            self.guest.snapshot(name="Large")
        else:
            snapshotList = self.createSnapshotTree(self.SNAPSHOTPATTERN,self.guest,self.ISWINDOWS)
        if self.guest.getState() == "UP":
            self.guest.shutdown()

        vmuuid = self.guest.getUUID()
        self.protocolObj.exportVMSnapshotTree(vmuuid,self.STATICIP)

        ret = self.protocolObj.importVMSnapshotTree(transProtocol,ssl)
 
        if ret == None:
            raise xenrt.XRTFailure("VM uuid of imported VM is not returned")

        try:
            importedGuestuuid = ret.splitlines()[2]
        except: 
            raise xenrt.XRTFailure("Exception caught while trying to get uuid of Imported VM") 

        createVif = False
        changeVif = True
    
        #Change the name of newly created VM
        self.host.execdom0("xe vm-param-set uuid=%s name-label=%s" % (importedGuestuuid,vmImportName)) 
 
        #verify the newly created vm
        importedVM = self.verifyVM(importedGuestuuid,vmImportName,self.guest,self.host,createVif,changeVif)

        if self.LARGEVM:
            self.verifySingleSnapshot(importedVM,self.host,importedGuestuuid)
        else:
            self.verifySnapshotTree(self.SNAPSHOTPATTERN,self.host,importedGuestuuid,importedVM)

        xenrt.TEC().logverbose("VM imported with uuid %s from VM %s" % (importedGuestuuid,vmName))

    def postRun(self):

        self.protocolObj.deleteShareDirectory()
        if self.guest != None:
            if self.guest.getState() == "UP":
                self.guest.shutdown()

        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()

    def verifySingleSnapshot(self,importedVM,host,vmuuid):

        snapshots = []
        data = host.execdom0("xe vm-param-get uuid=%s param-name=snapshots"  % (vmuuid))
        tempSnapshotList = data.splitlines()[0]
        for i in xrange(0,1):
            temp = tempSnapshotList.split(";")[i]
            temp.replace(" ","")
            snapshots.append(temp)

        for snapshot in snapshots:
            name = host.minimalList("snapshot-param-get",args="uuid=%s param-name=name-label" % (snapshot))
            snap = snapshot
            if name[0] <> "Large":
                raise xenrt.XRTFailure("Invalid snapshot in the imported snapshot tree found")
        try:
            host.execdom0("xe snapshot-revert snapshot-uuid=%s" %(snap))
        except:
            raise xenrt.XRTFailure("Exception occurred while reverting to snapshot")
        if importedVM.getState() == "UP":
            importedVM.shutdown()
            self.changeVif(importedVM)
            importedVM.start()

        if importedVM.getState() == "DOWN":
            self.changeVif(importedVM)
            importedVM.start()

    def verifySnapshotTree(self,snapshotPattern,host,vmuuid,guest):

        snapshotList = []
        for i in xrange(1,16):
            snapshotList.append([])

        snapshots = []
        data = host.execdom0("xe vm-param-get uuid=%s param-name=snapshots"  % (vmuuid))
        tempSnapshotList = data.splitlines()[0]
        for i in xrange(0,14):
            temp = tempSnapshotList.split(";")[i]
            temp = temp.replace(" ","")
            snapshots.append(temp)

        for snapshot in snapshots:
            name = host.minimalList("snapshot-param-get",args="uuid=%s param-name=name-label" % (snapshot))
            try:
                snapshotList[int(name[0])] = snapshot
            except:
                raise xenrt.XRTFailure("Invalid Snapshot Name in the imported VM")

        if snapshotPattern == 1:
            for i in xrange(1,pow(2,3)-1):
                data = host.minimalList("snapshot-param-get",args="uuid=%s param-name=children" % (snapshotList[i]))
          
                if ((not snapshotList[2*i] in data) or (not snapshotList[2*i +1] in data)):
                    raise xenrt.XRTFailure("Wrong snapshot Tree has been imported")
                self.checkSnapshot(guest,snapshotList[i])
                for j in xrange(0,2):
                    self.checkSnapshot(guest,snapshotList[2*i + j])

            children = host.minimalList("snapshot-param-get",args="uuid=%s param-name=children" % (snapshotList[7]))
            if not snapshotList[2*7] in children:
                raise xenrt.XRTFailure("Wrong snapshot tree has been imported")
            self.checkSnapshot(guest,snapshotList[7])
            self.checkSnapshot(guest,snapshotList[2*7])

        elif snapshotPattern == 2:     
            for i in xrange(1,14):
                children = host.minimalList("snapshot-param-get",args="uuid=%s param-name=children" % (snapshotList[i]))
                if children[0] <> snapshotList[i+1]:
                    raise xenrt.XRTFailure("Wrong snapshot tree has been imported")
                self.checkSnapshot(guest,snapshotList[i])

            self.checkSnapshot(guest,snapshotList[14])

        elif snapshotPattern == 3:
             data = host.minimalList("snapshot-param-get",args="uuid=%s param-name=children" % (snapshotList[1]))
             self.checkSnapshot(guest,snapshotList[1])
             children = []
             for i in xrange(0,13):
                 temp = data[i]
                 temp = temp.replace(" ","")
                 children.append(temp)
             for i in xrange(2,15):
                 if not snapshotList[i] in children:
                     raise xenrt.XRTFailure("Wrong snapshot tree has been imported")
                 self.checkSnapshot(guest,snapshotList[i])
                 time.sleep(20)

    def checkSnapshot(self,guest,snapshot):
 
        guest.revert(snapshot)
        if guest.getState() == "DOWN":
            try:
                self.changeVif(guest)
                guest.start()
            except:
                raise xenrt.XRTFailure("After reverting VM to snapshot %s, VM is not coming up" % snapshot)

    def createSnapshotTree(self,snapshotPattern,guest,isWindows):

        if snapshotPattern == 1:
            snapshotList = self.fullTree(guest,isWindows)
        elif snapshotPattern == 2:
            snapshotList = self.longestTree(guest,isWindows)
        elif snapshotPattern == 3:
            snapshotList = self.widestTree(guest,isWindows)
        time.sleep(20)
        return snapshotList

    def longestTree(self,guest,isWindows):
 
        node = []
        snapshotList = []
        snapshotList.append([])

        for i in xrange(1,15):
 
            node = []
            self.createDir(guest,isWindows,i)
            snapuuid = guest.snapshot(name=str(i))
            if i == 1:
                node.append("0")
            else:
                node.append((snapshotList[i-1])[1])
            node.append(snapuuid)
            snapshotList.append(node) 
           
        return snapshotList 

    def widestTree(self,guest,isWindows):

        node = []
        snapshotList = []

        self.createDir(guest,isWindows,1) 
        snapuuid = guest.snapshot(name="1")
        node.append("0")
        node.append(snapuuid)
        snapshotList.append([])
        snapshotList.append(node)
 
        for i in xrange(2,15):

            node = []
            snapshot = (snapshotList[1])[1]
            guest.revert(snapshot)
            if guest.getState() == "DOWN":
                self.guest.start()
            self.createDir(guest,isWindows,i)
            snapuuid = guest.snapshot(name=str(i))
            node.append(snapshot)
            node.append(snapuuid)
            snapshotList.append(node)
 
        return snapshotList

    def createDir(self,guest,isWindows,name):
 
        if isWindows:
            guest.xmlrpcExec("mkdir c:\%s" % (str(name)))
        else:
            guest.execguest("mkdir /tmp/%s" % (str(name)))
        time.sleep(15)
    
    def changeVif(self, guest):
        # Change the vif of newly created guest to XenRT random mac before guest start
        mac = xenrt.randomMAC()
        bridge = guest.host.getPrimaryBridge()
        device = 'eth0'
        guest.changeVIF(device, bridge, mac)
    
    def fullTree(self,guest,isWindows):

        snapshotList = []
        for i in xrange(1,16):
            snapshotList.append([])

        self.createDir(guest,isWindows,1)
        snapshotList[1] = guest.snapshot(name=str(1))
        time.sleep(15)
        for i in xrange(1,7):
            guest.revert(snapshotList[i])
            if guest.getState() == "DOWN":
                self.guest.start()
            self.createDir(guest,isWindows,2*i)
            snapshotList[2*i] = guest.snapshot(name=str(2*i))
            guest.revert(snapshotList[i])
            if guest.getState() == "DOWN":
                self.guest.start()
            self.createDir(guest,isWindows,2*i +1)
            snapshotList[2*i + 1] = guest.snapshot(name=str(2*i +1))

        guest.revert(snapshotList[7])
        if guest.getState() == "DOWN":
            self.guest.start()
        self.createDir(guest,isWindows,2*7)
        snapshotList[2*7] = guest.snapshot(name=str(2*7))
        return snapshotList

class TC14445(ExportImportSnapshotTree):
    """To verify the export and import of Linux VM snapshot tree of 14 snapshot (pattern 1) using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    SNAPSHOTPATTERN = 1
    ISWINDOWS = False
    STATICIP = 7

class TC14446(ExportImportSnapshotTree):
    """To verify the export and import of Linux VM snapshot tree of 14 snapshot (pattern 2) using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    SNAPSHOTPATTERN = 2 
    ISWINDOWS = False
    STATICIP = 1

class TC14447(ExportImportSnapshotTree):
    """To verify the export and import of Linux VM snapshot tree of 14 snapshot (pattern 3) using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    SNAPSHOTPATTERN = 3
    ISWINDOWS = False
    STATICIP = 13

class TC14448(ExportImportSnapshotTree):
    """To verify the export and import of Windows VM snapshot tree of 14 snapshot (pattern 1) using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    SNAPSHOTPATTERN = 1
    ISWINDOWS = True
    STATICIP = 7

class TC14449(ExportImportSnapshotTree):
    """To verify the export and import of Windows VM snapshot tree of 14 snapshot (pattern 2) using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    SNAPSHOTPATTERN = 2
    ISWINDOWS = True
    STATICIP = 1

class TC14450(ExportImportSnapshotTree):
    """To verify the export and import of Windows VM snapshot tree of 14 snapshot (pattern 3) using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    SNAPSHOTPATTERN = 3
    ISWINDOWS = True
    STATICIP = 13

class TC13207(ExportImportSnapshotTree):
    """To verify the export and import of Large Windows VM (100GB) with 1 snapshot using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    ISWINDOWS = True
    LARGEVM = True
    SIZE = 102400 
    STATICIP = 1

class TC14452(ExportImportSnapshotTree):
    """To verify the export and import of Copied vm with 1 snapshot using WSMAN protocol"""

    PROTOCOL = "WSMAN"
    ISWINDOWS = True
    LARGEVM = True
    SIZE = 24576
    COPY = True

class NetworkTest(_CimBase):
    """To verify the creation and deletion of various networks using either cim-xml or wsman protocol"""

    def run(self,arglist):
   
        internalNetworkName = "internalNetwork"
        externalNetworkName = "externalNetwork"
        ret = self.protocolObj.createInternalNetwork(internalNetworkName)       
        if ret == None:
            raise xenrt.XRTFailure("Network uuid of internal network is not returned")

        try:
            intNetuuid = ret.splitlines()[2]
        except:
            raise xenrt.XRTFailure("Exception caught while trying to get the internal network uuid")

        netList = self.host.minimalList("network-list")

        if not intNetuuid in netList:
            raise xenrt.XRTFailure("Internal network is not created")     
            

        ret = self.protocolObj.createExternalNetwork(externalNetworkName)
        if ret == None:
            raise xenrt.XRTFailure("Network uuid of external network is not returned")

        try:
            extNetuuid = ret.splitlines()[2]
        except:
            raise xenrt.XRTFailure("Exception caught while trying to get the external network uuid")
 
        netList = self.host.minimalList("network-list")
      
        if not extNetuuid in netList:
            raise xenrt.XRTFailure("External network is not created")

        self.protocolObj.addNicToNetwork(intNetuuid)
        time.sleep(10)
        pifs1 = []
        pifs2 = []
        ret = self.host.execdom0("xe network-param-get uuid=%s param-name=PIF-uuids" % (intNetuuid))
        data = ret.splitlines()[0] 
        data = data.replace(" ","") 
        i = 0
        while 1:
            try:
                pifs1.append(data.split(";")[i])
            except:
                break
            i = i + 1
        ret = self.host.execdom0("xe pif-list VLAN=99 minimal=true")
        data = ret.splitlines()[0]
        data = data.replace(" ","")
        i = 0
        while 1:
            try:
                pifs2.append(data.split(",")[i])
            except:
                break
            i = i + 1
        for pif in pifs1:
            if not pif in pifs2:       
                raise xenrt.XRTFailure("Error occurred while attaching NIC to network")

        self.protocolObj.removeNicFromNetwork(intNetuuid)
        ret = self.host.execdom0("xe network-param-get uuid=%s param-name=PIF-uuids" % (intNetuuid))
        pif1 = ((str(ret)).splitlines()[0]).strip()
        ret = self.host.execdom0("xe pif-list VLAN=99 minimal=true")
        pif2 = ((str(ret)).splitlines()[0]).strip()
        if pif1:
            raise xenrt.XRTFailure("Error occurred while trying to remove NIC from network")
        if pif2:
            raise xenrt.XRTFailure("Error oocuured while trying to remove NIC from network")
    
        self.guest = self.host.createGenericLinuxGuest(name="NetworkVM")
        self.uninstallOnCleanup(self.guest)
 
        if self.guest.getState() == "UP":
            self.guest.shutdown()

        vmuuid = self.guest.getUUID()

        self.protocolObj.addNetworkToVM(intNetuuid,vmuuid)
        ret = self.host.execdom0("xe network-param-get uuid=%s param-name=VIF-uuids" % (intNetuuid))
        vif1 = ret.splitlines()[0]
        
        vifs = self.host.minimalList("vm-vif-list",args="uuid=%s" % (vmuuid)) 
        if not vif1 in vifs:
            raise xenrt.XRTFailure("Error occurred while trying to attach Internal network to VM") 

        self.protocolObj.addNetworkToVM(extNetuuid,vmuuid)
        ret = self.host.execdom0("xe network-param-get uuid=%s param-name=VIF-uuids" % (extNetuuid))
        vif2 = ret.splitlines()[0]

        vifs = self.host.minimalList("vm-vif-list",args="uuid=%s" % (vmuuid))
        if not vif2 in vifs:
            raise xenrt.XRTFailure("Error occurred while trying to attach External network to VM")
        
        vifInstanceId = "Xen:%s/%s" %(vmuuid,vif1)
        self.protocolObj.removeNetworkFromVM(vifInstanceId)

        vifs = self.host.minimalList("vm-vif-list",args="uuid=%s" % (vmuuid))
        if vif1 in vifs:
            raise xenrt.XRTFailure("Error occurred while trying to dettach Internal network to VM")

        vifInstanceId = "Xen:%s/%s" %(vmuuid,vif2)
        self.protocolObj.removeNetworkFromVM(vifInstanceId)

        vifs = self.host.minimalList("vm-vif-list",args="uuid=%s" % (vmuuid))
        if vif2 in vifs:
            raise xenrt.XRTFailure("Error occurred while trying to dettach Internal network to VM")

        self.protocolObj.destroyNetwork(intNetuuid)
        netList = self.host.minimalList("network-list")

        if intNetuuid in netList:
            raise xenrt.XRTFailure("Internal network is not destroyed")

        self.protocolObj.destroyNetwork(extNetuuid)
        netList = self.host.minimalList("network-list")

        if extNetuuid in netList:
            raise xenrt.XRTFailure("External network is not destroyed")

    def postRun(self):

        #clean any unwanted jobs running on host and shutdown the guest used for executing PS
        self.protocolObj.jobCleanUp()

class TC14435(NetworkTest):
    """To verify the creation and deletion of various networks using wsman protocol"""

    PROTOCOL = "WSMAN"



class Kvp(object):
    HASH_THRESHOLD = 512

    def __init__(self, key, value, deviceId=None):
        self.key = key
        self.deviceId = deviceId
        if len(value) > self.HASH_THRESHOLD:
            self.value = hash(value)
            self.valueIsHash = True
        else:
            self.value = value
            self.valueIsHash = False

    def compare(self, kvp, compareDeviceId=True):
        if compareDeviceId and not self.deviceId == kvp.deviceId:
            return False
        return self.key == kvp.key and self.value == kvp.value

class _KvpBase(xenrt.TestCase):
    SUPP_PACK_NAME = 'xenserver-integration-suite.iso'
    """ TODO """

    def prepare(self,arglist):
        self.scvmmHost = self.getHost("RESOURCE_HOST_0")
        self.managedHost = self.getHost("RESOURCE_HOST_1")
      
        try: 
            self._installSuppPack(self.managedHost)
        except Exception, e:
            xenrt.TEC().logverbose("Work-around for supp pack install: Exception: %s" % (str(e)))

        self.protocolObj = _WSMANProtocol()
        xenrt.TEC().registry.guestGet(self.protocolObj.VMNAME).tailored = True
        self.protocolObj.prepare([], host=self.managedHost)

        timings = { 'number': 0, 'totalTime': 0, 'min': sys.maxint, 'max': 0, 'threshold': 20 } 
        self.wsmanTimings = { 
                'write': timings.copy(),
                'setup': timings.copy(),
                'remove': timings.copy() }

        self.wsmanTimings['setup']['threshold'] = 120

    def _installSuppPack(self, host):
        suppPack = xenrt.TEC().getFile("xe-phase-2/%s" % (self.SUPP_PACK_NAME), "../xe-phase-2/%s" % (self.SUPP_PACK_NAME))
        if not suppPack:
            raise xenrt.XRTError("xenserver-integration-suite iso file not found in xe-phase-2")

        hostPath = "/tmp/%s" % (self.SUPP_PACK_NAME)
        #Upload the contents of iso onto a http server 
        sh = host.sftpClient()
        try:
            sh.copyTo(suppPack,hostPath)
        finally:
            sh.close()

        host.execdom0('xe-install-supplemental-pack %s' % (hostPath), timeout=60, retval='code')
        host.execdom0('cimserver-debug-mode start', timeout=60)

    def _createManagedGuest(self, host, distro='ws08r2-x64'):
        existingGuests = host.listGuests()
        guest = None
        if distro in existingGuests:
            guest = host.getGuest(distro)
        else:
            guest = host.createGenericWindowsGuest(distro=distro, name=distro)

        guest.disableFirewall()
        self._installKVPAgent(guest)
        self._cimSetupKvpChannel(guest, host)

        return guest

    def _guestWriteKvp(self, guest, key, value):
        xenrt.TEC().logverbose("Write KVP [%s/%s] to KVP daemon in guest %s" % (key, value, guest.name))
        pass

    def _guestRemoveKvp(self, guest, key):
        xenrt.TEC().logverbose("Remove KVP [%s] from KVP daemon in guest %s" % (key, guest.name))
        pass

    def _guestReadKvp(self, guest, key):
        xenrt.TEC().logverbose("Read KVP [%s] from KVP daemon in guest %s" % (key, guest.name))
        pass

    def _cimSetupKvpChannel(self, guest, host):
        psScript = xenrt.lib.xenserver.setupKvpChannel(host.getIP(), 
                                                       host.password, guest.getUUID())
        xenrt.TEC().logverbose("Setup KVP channel on guest %s using WSMAN" % (guest.name))
        ret = self.protocolObj.psExecution(psScript)

        rCode = int(re.search('Return-Code:(\d+)', ret).group(1))
        if rCode != 0:
            raise xenrt.XRTFailure("WSMAN Setup KVP channel returned value: %d" % (rCode))
        duration = int(re.search('Duration:(\d+)', ret).group(1))
        self._updateTimings(duration, 'setup')


    def _cimWriteKvp(self, guest, host, key, value):
        psScript = xenrt.lib.xenserver.addWSMANGuestKvp(host.getIP(), host.password, key, value, guest.getUUID())
        xenrt.TEC().logverbose("Write KVP [%s/%s] to guest %s using WSMAN" % (key, value, guest.name))

        ret = self.protocolObj.psExecution(psScript)
        rCode = int(re.search('Return-Code:(\d+)', ret).group(1))
        if rCode != 0:
            raise xenrt.XRTFailure("WSMAN Write KVP returned value: %d" % (rCode))
        duration = int(re.search('Duration:(\d+)', ret).group(1))
        self._updateTimings(duration, 'write')

    def _cimRemoveKvp(self, host, deviceId, key=None):
        if key:
            psScript = xenrt.lib.xenserver.removeWSMANGuestKvpUsingKeyDevId(host.getIP(), host.password, key, deviceId)
        else:
            psScript = xenrt.lib.xenserver.removeWSMANGuestKvpUsingDeviceID(host.getIP(), host.password, deviceId)
        xenrt.TEC().logverbose("Remove KVP [Device ID:%s] using WSMAN" % (deviceId))

        ret = self.protocolObj.psExecution(psScript)
        rCode = int(re.search('Return-Code:(\d+)', ret).group(1))
        if rCode != 0:
            raise xenrt.XRTFailure("WSMAN Remove KVP returned value: %d" % (rCode))
        duration = int(re.search('Duration:(\d+)', ret).group(1))
        self._updateTimings(duration, 'remove')

    def _cimReadKvp(self, guest, host, deviceId):
        psScript = xenrt.lib.xenserver.getWSMANGuestKvpByDeviceID(host.getIP(), host.password, deviceId)
        xenrt.TEC().logverbose("Read KVP [Device ID:%s] from guest %s using WSMAN" % (deviceId, guest.name))

        ret = self.protocolObj.psExecution(psScript)
        kvps = eval(''.join(ret.splitlines()[2:]))

        if len(kvps) == 0:
            return None
        elif len(kvps) == 1:
            key = kvps.keys()[0]
            return Kvp(key, kvps[key][1], kvps[key][0])
        else:
            raise xenrt.XRTFailure("%d KVPs detected with identical device IDs" % (len(kvps)))

    def _cimReadAllKvps(self, guest, host):
        psScript = xenrt.lib.xenserver.getAllWSMANGuestKvps(host.getIP(), host.password, guest.getUUID())
        xenrt.TEC().logverbose("Read All KVP from guest %s using WSMAN" % (guest.name))

        ret = self.protocolObj.psExecution(psScript)
        kvps = eval(''.join(ret.splitlines()[2:]))

        kvpList = []
        for key, data in kvps.iteritems():
            kvpList.append(Kvp(key, data[1], data[0]))

        return kvpList

    def _cimRemoveAllKvps(self, guest, host):
        kvps = self._cimReadAllKvps(guest, host)
        map(lambda x:self._cimRemoveKvp(host, x.deviceId, x.key), kvps)

    def _updateTimings(self, durationSeconds, operation):
        xenrt.TEC().logverbose("WSMAN Operation %s took %d seconds" % (operation, durationSeconds))

        if durationSeconds > self.wsmanTimings[operation]['threshold']:
            raise xenrt.XRTFailure("WSMAN %s KVP exceeded time threshold: %d sec" % (operation, durationSeconds))
        self.wsmanTimings[operation]['number'] += 1
        self.wsmanTimings[operation]['totalTime'] += durationSeconds
        
        if durationSeconds < self.wsmanTimings[operation]['min']:
            self.wsmanTimings[operation]['min'] = durationSeconds
        if durationSeconds > self.wsmanTimings[operation]['max']:
            self.wsmanTimings[operation]['max'] = durationSeconds

    def _sanityCheck(self, guest, host):
        self._cimRemoveAllKvps(guest, host)
        sanityKvp = Kvp(key='SanityKey', value='SanityValue')

        self._cimWriteKvp(guest, host, key=sanityKvp.key, value=sanityKvp.value)
        kvps = self._cimReadAllKvps(guest=guest, host=host)
        if len(kvps) != 1:
            raise xenrt.XRTFailure("Sanity Test: Found %d KVPs expected 1" % (len(kvps)))
        if not kvps[0].compare(sanityKvp, compareDeviceId=False):
            raise xenrt.XRTFailure("Sanity Test: Read KVP doesn't match written KVP")
        self._cimRemoveKvp(host, kvps[0].deviceId)
        kvps = self._cimReadAllKvps(guest=guest, host=host)
        if len(kvps) != 0:
            raise xenrt.XRTFailure("Sanity Test: Found %d KVPs expected 0" % (len(kvps)))

    def _installKVPAgent(self, guest):
        # TODO - Correct location
#        msifilelocation = "http://wlbbuild01.citrite.net/output/CitrixXenServerIntegrationService/latest/release/CitrixXenServerIntegrationService.msi"
        msifilelocation = "http://%s/winkvp/CitrixXenServerIntegrationService-debug.msi" % (guest.getHost().getIP())
        xenrt.TEC().logverbose("Getting Integration Service MSI from %s" % (msifilelocation))

        msiFilename = os.path.basename(msifilelocation)
        installLocation = 'c:\\%s' % (msiFilename)
        # Copy MSI to guest
        if not guest.xmlrpcFetchFile(msifilelocation, installLocation):
            raise xenrt.XRTError("Failed to copy msi from %s to %s on guest %s" % (msifilelocation, installLocation, guest.name))
        # Install the MSI
        installCommand = "msiexec /i %s /qn /lv* c:\\integservinstall.log" % (installLocation)
        guest.xmlrpcWriteFile("c:\\commandToExecute.cmd",installCommand)
        guest.xmlrpcExec("c:\\commandToExecute.cmd >output")
        # Store the install log
        guest.xmlrpcGetFile2('c:\\integservinstall.log', os.path.join(xenrt.TEC().getLogdir(), 'integservinstall.log'))


    def _tempSetup(self, hostAddress, guestUUID):
        url = "http://%s:8080/vm/%s/cmd/setup" % (hostAddress, guestUUID)
        opener = urllib2.build_opener(urllib2.HTTPHandler)
        request = urllib2.Request(url)
        request.get_method = lambda: 'POST'
        response = urllib2.urlopen(request)
        data = response.read()
        response.close()
        xenrt.TEC().logverbose("Output from tempSetup: %s" % (data))

class TC17902(_KvpBase):
    """Basic KVP write / read / remove"""
    PARALLEL_KVP_OPS = 5
    PARALLEL_KVP_SETS = 200
    DISTRO = 'ws08r2-x64'
 
    def run(self,arglist):
        self.managedGuest = self._createManagedGuest(self.managedHost, self.DISTRO)

        baseKey = 'xenrtTestKey:'
        baseValue = 'xenrtTestValue:'

        # Write 1000 KVPs
        for i in range(self.PARALLEL_KVP_SETS):
            pWrites = map(lambda x:xenrt.PTask(self._cimWriteKvp, guest=self.managedGuest, host=self.managedHost, key=baseKey+str(x), value=baseValue+str(x)), range(i*self.PARALLEL_KVP_OPS, (i*self.PARALLEL_KVP_OPS)+self.PARALLEL_KVP_OPS))
            try:
                xenrt.pfarm(pWrites)
            except xenrt.XRTException, e:
                xenrt.TEC().logverbose("Write failed with Exception: Data: %s" % (e.data))

        # Check the writes
        kvps = self._cimReadAllKvps(guest=self.managedGuest, host=self.managedHost)
        for i in range(self.PARALLEL_KVP_SETS*self.PARALLEL_KVP_OPS):
            res = filter(lambda x:Kvp(key=baseKey+str(i), value=baseValue+str(i)).compare(x, compareDeviceId=False), kvps)
            if len(res) != 1:
                raise xenrt.XRTFailure("Found %d instances of KVP with Key: %s, Value: %s" % (len(res), baseKey+str(i), baseValue+str(i)))
                        
        # Remove all the KVPs
        for i in range(self.PARALLEL_KVP_SETS):
            pRemove = map(lambda x:xenrt.PTask(self._cimRemoveKvp, host=self.managedHost, deviceId=x.deviceId), kvps[i*self.PARALLEL_KVP_OPS:(i*self.PARALLEL_KVP_OPS)+self.PARALLEL_KVP_OPS])
            xenrt.pfarm(pRemove)
 
        # Check they have all been removed
        kvps = self._cimReadAllKvps(guest=self.managedGuest, host=self.managedHost)
        if len(kvps) != 0:
            raise xenrt.XRTFailure("Found %d KVPs after attempt to remove all" % (len(kvps)))

    def postRun(self):
        self._cimRemoveAllKvps(guest=self.managedGuest, host=self.managedHost)

class TC17904(_KvpBase):
    """KVP test with large keys and values"""

    def run(self,arglist):
        self.managedGuest = self._createManagedGuest(self.managedHost)

        numberOfLargeKvps = 50
        keyLength = 256
        valueLength = 40000
        writeKvps = []

        # Write 50 large KVPs
        for i in range(numberOfLargeKvps):
            randValue = ''.join(random.choice(string.ascii_letters+string.digits) for i in range(valueLength)) 
            randKey = ''.join(random.choice(string.ascii_letters+string.digits) for i in range(keyLength)) 
            self._cimWriteKvp(guest=self.managedGuest, host=self.managedHost, key=randKey, value=randValue)
            writeKvps.append(Kvp(randKey, randValue))

        # Check the values
        kvps = self._cimReadAllKvps(guest=self.managedGuest, host=self.managedHost)
        for writeKvp in writeKvps:
            res = filter(lambda x:writeKvp.compare(x, compareDeviceId=False), kvps)
            if len(res) != 1:
                raise xenrt.XRTFailure("Found %d instances of KVP with Key: %s, Value: %s" % (len(res), writeKvp.key, writeKvp.value))

        # Remove all KVPs
        map(lambda x:self._cimRemoveKvp(host=self.managedHost, deviceId=x.deviceId, key=x.key), kvps)

        # Check they have all been removed
        kvps = self._cimReadAllKvps(guest=self.managedGuest, host=self.managedHost)
        if len(kvps) != 0:
            raise xenrt.XRTFailure("Found %d KVPs after attempt to remove all" % (len(kvps)))

    def postRun(self):
        self._cimRemoveAllKvps(guest=self.managedGuest, host=self.managedHost)

class TC17905(_KvpBase):
    """Misc KVP test"""

    def run(self,arglist):
        self.managedGuest = self._createManagedGuest(self.managedHost)

        self.runSubcase('_invalidKey', (257), 'invalidKey', '257 bytes')
        self._sanityCheck(self.managedGuest, self.managedHost)

        self.runSubcase('_invalidKey', (40000), 'invalidKey', '40kbytes')
        self._sanityCheck(self.managedGuest, self.managedHost)

        self.runSubcase('_invalidKey', (0), 'invalidKey', '0 bytes')
        self._sanityCheck(self.managedGuest, self.managedHost)

        self.runSubcase('_existingKey', (), 'existingKey', 'write')
        self._sanityCheck(self.managedGuest, self.managedHost)

        guestUuid = self.managedGuest.getUUID()
        invalidDeviceId = 'Xen:%s/' % (guestUuid)
        self.runSubcase('_removeInvalidDeviceId', (invalidDeviceId), 'invalidDeviceId', 'noKey')
        self._sanityCheck(self.managedGuest, self.managedHost)

        invalidDeviceId = '%s/invalidKey' % (guestUuid)
        self.runSubcase('_removeInvalidDeviceId', (invalidDeviceId), 'invalidDeviceId', 'noXen')
        self._sanityCheck(self.managedGuest, self.managedHost)

        invalidDeviceId = 'Xen:/invalidKey'
        self.runSubcase('_removeInvalidDeviceId', (invalidDeviceId), 'invalidDeviceId', 'noUUID')
        self._sanityCheck(self.managedGuest, self.managedHost)

        invalidDeviceId = ''
        self.runSubcase('_removeInvalidDeviceId', (invalidDeviceId), 'invalidDeviceId', 'noDeviceId')
        self._sanityCheck(self.managedGuest, self.managedHost)

        self.runSubcase('_invalidVmPowerState', (), 'invalidVmPowerState', 'all')
        self._sanityCheck(self.managedGuest, self.managedHost)

    def _existingKey(self):
        # Write existing key
        self._cimWriteKvp(guest=self.managedGuest, host=self.managedHost, key='DuplicateKey', value='DuplicateKey-Value1')
        self._cimWriteKvp(guest=self.managedGuest, host=self.managedHost, key='DuplicateKey', value='DuplicateKey-Value2')
        kvps = self._cimReadAllKvps(guest=self.managedGuest, host=self.managedHost)
        dupKvps = filter(lambda x:x.key == 'DuplicateKey', kvps)
        if len(dupKvps) == 1:
            if dupKvps[0].value != 'DuplicateKey-Value2':
                raise xenrt.XRTFailure("Key value not updated: Value: %s" % (dupKvps[0].value))
        else:
            raise xenrt.XRTFailure("%d keys matching DuplicateKey" % (len(dupKvps)))

    def _removeInvalidDeviceId(self, deviceId):
        failureString = None
        try:
            self._cimRemoveKvp(host=self.managedHost, deviceId=deviceId) 
            failureString = "Attempt to remove invalid / non-existent deviceId [%s] did not fail" % (deviceId)
        except Exception, e:
            xenrt.TEC().logverbose("Attempt to remove invalid / non-existent deviceId failed with exception: %s" % (str(e)))

    def _invalidVmPowerState(self):
        failureString = None
        self.managedGuest.shutdown()
        try:
            self._cimWriteKvp(guest=self.managedGuest, host=self.managedHost, key='InvalidPowerState-Key', value='InvalidPowerState-Value1')
            failureString = "Attempt to write KVP when VM is shutdown did not fail"
        except Exception, e:
            xenrt.TEC().logverbose("Attempt to write KVP when VM is shutdown failed with exception: %s" % (str(e)))

        self.managedGuest.start()
        self.managedGuest.suspend()
        try:
            self._cimWriteKvp(guest=self.managedGuest, host=self.managedHost, key='InvalidPowerState-Key', value='InvalidPowerState-Value1')
            failureString = "Attempt to write KVP when VM is suspended did not fail" 
        except Exception, e:
            xenrt.TEC().logverbose("Attempt to write KVP when VM is suspended failed with exception: %s" % (str(e)))

        self.managedGuest.resume()
        

    def _invalidKey(self, keyLength):
        randKey = ''.join(random.choice(string.ascii_letters+string.digits) for i in range(keyLength))
        failureString = None
        try:
            self._cimWriteKvp(guest=self.managedGuest, host=self.managedHost, key=randKey, value='Invalid Key')
            failureString = "Attempt to write key with length %d did not fail" % (keyLength)
        except Exception, e:
            xenrt.TEC().logverbose("Attempt to write a zero length key failed with exception: %s" % (str(e)))

        kvps = self._cimReadAllKvps(guest=self.managedGuest, host=self.managedHost)
        if len(kvps) > 0:
            failureString = "KVP written with invalid key length of %d. Key: %s, Value: %s" % (keyLength, kvps[0].key, kvps[0].value)
        
        if failureString:
            raise xenrt.XRTFailure(failureString)



    def postRun(self):
        self._cimRemoveAllKvps(guest=self.managedGuest, host=self.managedHost)

class TCKvp11114(TC17902):
    """Go behond the max supported KVPs"""
    PARALLEL_KVP_SETS = 500

    def run(self,arglist):
        try:
            TC17902.run(self, arglist)
        except Exception, e:
            xenrt.TEC().logverbose("Failed with Exception: %s" % (str(e)))

        # Check that the system is still stable
        kvps = self._cimReadAllKvps(guest=self.managedGuest, host=self.managedHost)
        xenrt.TEC().logverbose("%d KVPs were written" % (len(kvps)))

class TC17903(TC17902):
    DISTRO = 'w2k3eesp2-x64'

class TC18037(_KvpBase):
    NUMBER_OF_VMS = 80
    PARALLEL_KVP_OPS = 20
    NUMBER_OF_KVPS = 10

    def run(self,arglist):
        self.managedPool = self.getPool('RESOURCE_POOL_0')
        self.managedMaster = self.managedPool.master
        self.managedGuests = []

        # Install supp pack onto all slaves
        map(lambda x:self._installSuppPack(x), self.managedPool.getSlaves())

        # Create a base VM
        self.managedGuestBase = self.managedMaster.createGenericWindowsGuest(distro='ws08r2sp1-x64', name='ws08r2sp1-x64')
#        self.managedGuestBase = self.managedMaster.createGenericWindowsGuest(distro='w2k3eesp2-x64', name='w2k3eesp2-x64')
        self.managedGuestBase.shutdown()

        # Create clones
        pClones = map(lambda x:xenrt.PTask(self.managedGuestBase.cloneVM, name='%s-%d' % (self.managedGuestBase.name, x)), range(self.NUMBER_OF_VMS))
        self.managedGuests = xenrt.pfarm(pClones)

        # Start clones
        for guest in self.managedGuests:
            guest.tailored = True
            guest.start(specifyOn=False)

            guest.disableFirewall()
            self._installKVPAgent(guest)
            self._cimSetupKvpChannel(guest, guest.getHost())

        # Write KVPs
        for i in range(self.NUMBER_OF_KVPS):
            for stIx in range(0, len(self.managedGuests), self.PARALLEL_KVP_OPS):
                pWrites = map(lambda x:xenrt.PTask(self._cimWriteKvp, guest=x, host=self.managedMaster, key=x.name+'KEY:'+str(i), value=x.name+'VALUE'+str(i)), self.managedGuests[stIx:stIx+self.PARALLEL_KVP_OPS])
                try:
                    xenrt.pfarm(pWrites)
                except xenrt.XRTException, e:
                    xenrt.TEC().logverbose("Write failed with Exception: Data: %s" % (e.data))

        # Check the writes
        kvps = {}
        for g in self.managedGuests:
            kvps[g.name] = self._cimReadAllKvps(guest=g, host=self.managedMaster)
            for i in range(self.NUMBER_OF_KVPS):
                res = filter(lambda x:Kvp(key=g.name+'KEY:'+str(i), value=g.name+'VALUE'+str(i)).compare(x, compareDeviceId=False), kvps[g.name])
                if len(res) != 1:
                    raise xenrt.XRTFailure("Found %d instances of KVP with Key: %s, Value: %s" % (len(res), g.name+'KEY:'+str(i), g.name+'VALUE'+str(i)))

        # Remove all the KVPs
        for i in range(self.NUMBER_OF_KVPS):
            for stIx in range(0, len(self.managedGuests), self.PARALLEL_KVP_OPS):
                pRemove = map(lambda x:xenrt.PTask(self._cimRemoveKvp, host=self.managedHost, deviceId=kvps[x.name][i].deviceId), self.managedGuests[stIx:stIx+self.PARALLEL_KVP_OPS])
                xenrt.pfarm(pRemove)

        # Check they have all been removed
        for g in self.managedGuests:
            kvps = self._cimReadAllKvps(guest=g, host=self.managedMaster)
            if len(kvps) != 0:
                raise xenrt.XRTFailure("Found %d KVPs after attempt to remove all" % (len(kvps)))



