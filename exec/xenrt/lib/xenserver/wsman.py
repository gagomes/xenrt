#
#
# XenRT: Test harness for Xen and the XenServer product family
#
# Encapsulate a XenServer host.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, os.path, glob, time, re, random, shutil, os, stat
import traceback, threading, types
import xml.dom.minidom
import tarfile
import xenrt
import xenrt.lib.xenserver.guest
import XenAPI
from xenrt.lazylog import log

# Symbols we want to export from the package.
__all__ = ["getCIMClasses",
           "wsmanEnumerate",
           "createWSMANVM",
           "changeWSMANVMState",
           "deleteWSMANVM",
           "convertNetwork",
           "exportWSMANVM",
           "jobCleanUp",
           "importWSMANVM",
           "createWSMANVMFromTemplate",
           "copyWSMANVM",
           "createWSMANCifsIsoSr",
           "detachWSMANISO",
           "deleteWSMANSR",
           "createWSMANNFSSR",
           "createWSMANNFSISOSR",
           "getWSMANHistoricalMetrics",
           "getWSMANInstMetric",
           "getWSMANInstHostCPUMetric",
           "getWSMANInstDiskMetric",
           "createWSMANISCSISR",
           "forgetWSMANSR",
           "createWSMANVdiForVM",
           "attachWSMANVdiToVM",
           "getWSMANVBDuuid",
           "dettachWSMANVBDFromVM",
           "deleteWSMANVDI",
           "modifyWSMANProcessor",
           "modifyWSMANMemory",
           "remWSMANcddvdDrive",
           "addWSMANcddvdDrive",
           "snapshotWSMANVM",
           "applyWSMANSnapshot",
           "destroyWSMANSnapshot",
           "createWSMANVMFromSnapshot",
           "getWSMANVMSnapshotList",
           "modifyWSMANVdiProperties",
           "modifyWSMANVMSettings",
           "convertWSMANVMToTemplate",
           "createWSMANInternalNetwork",
           "createWSMANExternalNetwork",
           "createWSMANBondedNetwork",
           "addWSMANNicToNetwork",
           "removeWSMANNicFromNetwork",
           "attachWSMANVMToNetwork",
           "dettachWSMANVMFromNetwork",
           "destroyWSMANetwork",
           "exportWSMANSnapshotTree",
           "importWSMANSnapshotTree",
           "addWSMANGuestKvp",
           "getAllWSMANGuestKvps",
           "getWSMANGuestKvpByDeviceID",
           "removeWSMANGuestKvpUsingDeviceID",
           "removeWSMANGuestKvpUsingKeyDevId",
           "setupKvpChannel"]

def convertNetwork():

    #This is to convert the network of guest from public to private
    psScript = u"""
    # Convert the network to Private

    $nlm = [Activator]::CreateInstance([Type]::GetTypeFromCLSID([Guid]"{DCB00C01-570F-4A9B-8D69-199FDBA5723B}"))
    $connections = $nlm.getnetworkconnections()
    $connections |foreach {
        if ($_.getnetwork().getcategory() -eq 0)
        {
            $_.getnetwork().setcategory(1)
        }
    }
    """
    return psScript

def wsmanConnection(password = None,
                    hostIPAddr = None):

    connStr = '"' + "http://%s:5988" %(hostIPAddr) + '"'
    username = "root"
    wsmanConn = u"""
    $obj = New-Object -ComObject wsman.automation
    $conn = $obj.CreateConnectionOptions()
    $conn.UserName = "%s"
    $conn.Password = "%s"
    $iFlags = ($obj.SessionFlagNoEncryption() -bor $obj.SessionFlagUTF8() -bor $obj.SessionFlagUseBasic() -bor $obj.SessionFlagCredUsernamePassword())
    $target = %s
    $objSession = $obj.CreateSession($target, $iflags, $conn)
    """ % (username,password,connStr)
    return wsmanConn


def deleteWSMANVM(password = None,
                  hostIPAddr = None,
                  vmuuid = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSystemManagementService")

    psScript = u"""
    %s
    $vmName = "%s"
    %s
    $actionUri = $xenEnum

    $parameters = @"
    <DestroySystem_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService">
        <AffectedSystem xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
          <wsa:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:Address>
          <wsa:ReferenceParameters>
          <wsman:ResourceURI>http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem</wsman:ResourceURI>
          <wsman:SelectorSet>
                <wsman:Selector Name="Name">$vmName</wsman:Selector>
                <wsman:Selector Name="CreationClassName">Xen_ComputerSystem</wsman:Selector>
          </wsman:SelectorSet>
          </wsa:ReferenceParameters>
        </AffectedSystem>
    </DestroySystem_INPUT>
"@

    $output = [xml]$objSession.Invoke("DestroySystem", $actionURI, $parameters)

    if ($output.DestroySystem_OUTPUT.ReturnValue -ne 0) {
        # check for a job status of finished
        $jobPercentComplete = 0
        while ($jobPercentComplete -ne 100) {
            $jobResult = [xml]$objSession.Get($destroyVm.DestroySystem_OUTPUT.Job.outerxml)
            $jobPercentComplete = $jobResult.Xen_VirtualSystemManagementServiceJob.PercentComplete
            $jobPercentComplete
            sleep 3
        }
    }
    """ % (wsmanConn,vmuuid,endPointRef)
    return psScript

def changeWSMANVMState(password = None,
                       hostIPAddr = None,
                       vmuuid = None,
                       vmState = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    psScript = u"""
    %s
    $vmuuid = "%s"
    $actionUri = "http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem?CreationClassName=Xen_ComputerSystem+Name=$vmuuid"
    $state = %s
    if ($vmUuid -ne $null)
    {
        $parameters = @"
        <RequestStateChange_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem">
                <RequestedState>$state</RequestedState>
        </RequestStateChange_INPUT>
"@
            $response = [xml]$objSession.Invoke("RequestStateChange", $actionUri, $parameters)
        }
    """ % (wsmanConn,vmuuid,vmState)
    return psScript

def createWSMANVM(password = None,
                  hostIPAddr = None,
                  vmName = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    createVM = createVMScript()
    psScript = u"""
    %s
    $vmName = "%s"

    %s

    """ % (wsmanConn,vmName,createVM)
    return psScript

def createVMScript():

    endPointRef = endPointReference("Xen_VirtualSystemManagementService") 
    drive = addDrive("CD")

    psScript = u""" 

    if ($vmName -eq $null) {$vmName = "TestVirtualMachine"}
    if ($vmRam -eq $null) {$vmRam = 256}
    if ($vmProc -eq $null) {$vmProc = 1}
    if ($vmType -eq $null) {$vmType = "HVM"}

    # Create the VM
    %s
    $actionUri = $xenEnum

    $parameters = @"
    <DefineSystem_INPUT
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xmlns:xsd="http://www.w3.org/2001/XMLSchema"
     xmlns:cssd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystemSettingData"
     xmlns:msd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_MemorySettingData"
     xmlns="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService">
     <SystemSettings>
         <cssd:Xen_ComputerSystemSettingData xsi:type="Xen_ComputerSystemSettingData_Type">
              <cssd:HVM_Boot_Policy>BIOS order</cssd:HVM_Boot_Policy>
              <cssd:HVM_Boot_Params>order=dc</cssd:HVM_Boot_Params>
              <cssd:Platform>nx=false</cssd:Platform>
              <cssd:Platform>acpi=true</cssd:Platform>
              <cssd:Platform>apic=true</cssd:Platform>
              <cssd:Platform>pae=true</cssd:Platform>
              <cssd:Platform>viridian=true</cssd:Platform>
              <cssd:AutomaticShutdownAction>0</cssd:AutomaticShutdownAction>
              <cssd:AutomaticStartupAction>1</cssd:AutomaticStartupAction>
              <cssd:AutomaticRecoveryAction>2</cssd:AutomaticRecoveryAction>
              <cssd:VirtualSystemType>DMTF:xen:$vmType</cssd:VirtualSystemType>
              <cssd:Caption>My test VM description goes here</cssd:Caption>
              <cssd:ElementName>$vmName</cssd:ElementName>
         </cssd:Xen_ComputerSystemSettingData>
     </SystemSettings>
     <ResourceSettings>
         <msd:Xen_MemorySettingData>
             <msd:ResourceType>4</msd:ResourceType>
             <msd:VirtualQuantity>$vmRam</msd:VirtualQuantity>
             <msd:AllocationUnits>MegaBytes</msd:AllocationUnits>
         </msd:Xen_MemorySettingData>
     </ResourceSettings>
    </DefineSystem_INPUT>
"@
    $vmOutput = [xml]$objSession.Invoke("DefineSystem", $actionUri, $parameters)

    sleep 20
    # Get the VM object to return to the calling method
    $newVm = [xml]$objSession.Get($vmOutput.DefineSystem_OUTPUT.ResultingSystem.outerxml)
    $vmUuid = $newvm.Xen_ComputerSystem.Name
    $vmUuid
    $vmInstanceId = $newVm.Xen_ComputerSystem.InstanceID
    %s

    """ % (endPointRef,drive)

    return psScript

def wsmanEnumerate(cimClass = None,
                   hostIPAddr = None,
                   hostPassword = None):

    psScript = u"""
    "########################################"
    "Start: %s"
    $cimUri = "http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/%s"
    $cimXmlObject  = [xml](winrm enum $cimUri -r:http://%s:5988 -encoding:utf-8 -a:basic -u:root -p:%s -format:pretty)
    $cimXmlObject.DocumentElement.%s
    $xml = [xml]$cimXmlObject
    if ($xml.Results.wsman -like "http://schemas.dmtf.org/wbem/wsman/1/wsman/results")
        {"Test Passed"}
    else
        {"Test Failed"}
    "End: %s"
    """ % (cimClass,cimClass,hostIPAddr,hostPassword,cimClass,cimClass)
    return psScript


def getCIMClasses():

    xenCimClasses = [
    "Xen_HostComputerSystem",
    "Xen_HostComputerSystemCapabilities",
    "Xen_HostPool",
    "Xen_VirtualizationCapabilities",
    "Xen_MemoryCapabilitiesSettingData",
    "Xen_ProcessorCapabilitiesSettingData",
    "Xen_StorageCapabilitiesSettingData",
    "Xen_NetworkConnectionCapabilitiesSettingData",
    "Xen_VirtualSystemManagementService",
    "Xen_VirtualSystemManagementCapabilities",
    "Xen_VirtualSystemMigrationService",
    "Xen_VirtualSystemMigrationCapabilities",
    "Xen_VirtualSystemSnapshotService",
    "Xen_VirtualSystemSnapshotCapabilities",
    "Xen_VirtualSystemSnapshotServiceCapabilities",
    "Xen_VirtualSwitchManagementService",
    "Xen_StoragePoolManagementService",
    "Xen_VirtualSystemManagementServiceJob",
    "Xen_VirtualSystemModifyResourcesJob",
    "Xen_VirtualSystemCreateJob",
    "Xen_ConnectToDiskImageJob",
    "Xen_VirtualSystemMigrationServiceJob",
    "Xen_ComputerSystem",
    "Xen_ComputerSystemCapabilities",
    "Xen_VirtualSwitch",
    "Xen_HostNetworkPort",
    "Xen_HostProcessor",
    "Xen_HostMemory",
    "Xen_DiskImage",
    "Xen_MemoryState",
    "Xen_ProcessorPool",
    "Xen_MemoryPool",
    "Xen_StoragePool",
    "Xen_NetworkConnectionPool",
    "Xen_Processor",
    "Xen_Memory",
    "Xen_Disk",
    "Xen_DiskDrive",
    "Xen_NetworkPort",
    "Xen_VirtualSwitchLANEndpoint",
    "Xen_ComputerSystemLANEndpoint",
    "Xen_VirtualSwitchPort",
    "Xen_Console",
    "Xen_ComputerSystemSettingData",
    "Xen_ComputerSystemTemplate",
    "Xen_ComputerSystemSnapshot",
    "Xen_VirtualSwitchSettingData",
    "Xen_ProcessorSettingData",
    "Xen_MemorySettingData",
    "Xen_DiskSettingData",
    "Xen_NetworkPortSettingData",
    "Xen_HostNetworkPortSettingData",
    "Xen_ConsoleSettingData",
    "Xen_MemoryAllocationCapabilities",
    "Xen_ProcessorAllocationCapabilities",
    "Xen_StorageAllocationCapabilities",
    "Xen_NetworkConnectionAllocationCapabilities",
    "Xen_MetricService",
    "Xen_HostProcessorUtilization",
    "Xen_HostNetworkPortReceiveThroughput",
    "Xen_HostNetworkPortTransmitThroughput",
    "Xen_ProcessorUtilization",
    "Xen_DiskReadThroughput",
    "Xen_DiskWriteThroughput",
    "Xen_DiskReadLatency",
    "Xen_DiskWriteLatency",
    "Xen_NetworkPortReceiveThroughput",
    "Xen_NetworkPortTransmitThroughput"]
    return xenCimClasses

def exportWSMANVM(password = None,
                  hostIPAddr = None,
                  vmuuid = None,
                  transProtocol = None,
                  ssl = None,
                  static_ip = None,
                  mask = None,
                  gateway = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    connToDiskImage = connectToDiskImageWithStaticIP(transProtocol,ssl,static_ip,mask,gateway,"c:\exportWSMANVMScriptsOutput.txt")
    disconFromDiskImage = disconnectFromDiskImage("$connectionHandle")
    writexmlToFile = writeXmlToFile()
    str = '"' + "Xen:%s" % (vmuuid) + "%"+ '"'
    psScript = u"""
    %s
    %s
    $dialect = "http://schemas.microsoft.com/wbem/wsman/1/WQL"
    $filter1 = "SELECT * FROM Xen_DiskSettingData where InstanceID like"
    $filter = $filter1 + '"' + %s + '"'
    $xenEnum = $objSession.Enumerate("http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_DiskSettingData", $filter, $dialect)
    $timstamp = Get-Date -Format o
    $vmVbd = @()
    # Log the jobResult for Element in the array into exportWSMANVMScriptsOutput.txt
    "jobResult for Element in the array" | Out-File "c:\exportWSMANVMScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\exportWSMANVMScriptsOutput.txt" -Append
    $xenEnum | Out-File "c:\exportWSMANVMScriptsOutput.txt" -Append

    while (!$xenEnum.AtEndOfStream) {
        $elementRec = $xenEnum.ReadItem()
        $vmVbd += [xml]$elementRec
    }
    Import-Module BitsTransfer
    foreach ($element in $vmVbd) {
        if ($element.Xen_DiskSettingData.ResourceType -eq 19){
            # Parse the VBD into the Xen_DiskImage information needed
            $dsdHostResource = $element.Xen_DiskSettingData.HostResource
            $vDisk = @()
            $vDiskHash = @{}
            $vDisk = $dsdHostResource.split(",")
            foreach ($i in $vDisk) {
                $tempArr = $i.Split("=")
                $vdiskHash.Add($tempArr[0], $tempArr[1])
            }

            $deviceID = $vDiskHash.DeviceID.Replace('"','')
            $systemName = $vDiskHash.SystemName.Replace('"','')
            $systemCreationClassName = $vDiskHash.SystemCreationClassName.Replace('"','')
            $creationClassName = $vDiskHash.'root/cimv2:Xen_DiskImage.CreationClassName'.Replace('"','')

            $vdi = @"
            <Xen_DiskImage>
                <DeviceID>$DeviceID</DeviceID>
                <CreationClassName>$CreationClassName</CreationClassName>
                <SystemCreationClassName>$SystemCreationClassName</SystemCreationClassName>
                <SystemName>$SystemName</SystemName>
            </Xen_DiskImage>
"@
            %s
            $transferVM = $jobResult 

            $destination = "Q:\" + $element.Xen_DiskSettingData.AddressOnParent + "." + $element.Xen_DiskSettingData.HostExtentName + ".vhd"
            $source = $transferVm.Xen_ConnectToDiskImageJob.TargetURI

            $transferJob = Start-BitsTransfer -Source $source -destination $destination -Asynchronous -DisplayName XenExportImport
            $timestamp = Get-Date -Format o
            "-Source $source -destination $destination"

            # Log the Cim call response on RAW file copy using BITS into exportWSMANVMScriptsOutput.txt
            "Cim call response on RAW file copy using BITS" | Out-File "c:\exportWSMANVMScriptsOutput.txt" -Append
            $timestamp | Out-File "c:\exportWSMANVMScriptsOutput.txt" -Append
            $transferJob | Out-File "c:\exportWSMANVMScriptsOutput.txt" -Append

            while ($jobStatus.JobState -ne "transferred"){
                $jobStatus = Get-BitsTransfer -JobId $transferJob.JobId
                $timestamp = Get-Date -Format o
                Write-Progress -activity "BITS Transfer Download" -status "copying.. " -PercentComplete ((($jobstatus.BytesTransferred / 1Mb) / ($jobStatus.BytesTotal / 1Mb)) * 100)
                if ($jobStatus.JobState -eq "TransientError") {
                    $jobstatus
                    "download is paused for 10 secs due to TransientError from BITS"
                    sleep 10
                $jobStatus | Out-File "c:\exportWSMANVMScriptsOutput.txt" -Append
                    Resume-BitsTransfer -BitsJob $transferJob
                }
                sleep 10
            }
            # Log the Transfer Job Status for RAW file into exportWSMANVMScriptsOutput.txt
            "Transfer Job Status for RAW file" | Out-File "c:\exportWSMANVMScriptsOutput.txt" -Append
            $timestamp | Out-File "c:\exportWSMANVMScriptsOutput.txt" -Append
            $jobStatus | Out-File "c:\exportWSMANVMScriptsOutput.txt" -Append
            $transferJob | Out-File "c:\exportWSMANVMScriptsOutput.txt" -Append

            Write-Progress -activity "BITS Transfer Download" -status "copying.. " -completed

            $bitsTime = $jobstatus.TransferCompletionTime - $jobstatus.CreationTime
            $bitsTime.TotalSeconds.ToString() + " Seconds"

            Complete-BitsTransfer $transferJob.JobId
            $connectionHandle = $transferVM.Xen_ConnectToDiskImageJob.ConnectionHandle
            %s
            $vdiDisconnect = $output
            $vdiDisconnect
            # check for a job status of finished
            $jobPercentComplete = 0
            "jobResult for Disconnect From Disk Image Job" | Out-File "c:\exportWSMANVMScriptsOutput.txt" -Append
            while ($jobPercentComplete -ne 100) {
                $jobResult = [xml]$objSession.Get($vdiDisconnect.DisconnectFromDiskImage_OUTPUT.Job.outerxml)
                $jobPercentComplete = $jobresult.Xen_DisconnectFromDiskImageJob.PercentComplete
                sleep 3
            $jobResult | Out-File "c:\exportWSMANVMScriptsOutput.txt" -Append
            }
            # Log the jobResult for Export Finished into exportWSMANVMScriptsOutput.txt
            "jobResult for Export Finished" | Out-File "c:\exportWSMANVMScriptsOutput.txt" -Append
            $timestamp | Out-File "c:\exportWSMANVMScriptsOutput.txt" -Append
            WriteXmlToFile $jobResult | Out-File "c:\exportWSMANVMScriptsOutput.txt" -Append
        }
    }

    
    """ % (writexmlToFile,wsmanConn,str,connToDiskImage,disconFromDiskImage)
    return psScript

def importWSMANVM(password = None,
                  hostIPAddr = None,
                  vmuuid = None,
                  transProtocol = None,
                  ssl = None,
                  vmName = None,
                  vmProc = None,
                  vmRam = None,
                  static_ip = None,
                  mask = None,
                  gateway = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    connToDiskImage = connectToDiskImageWithStaticIP(transProtocol,ssl,static_ip,mask,gateway,"c:\importWSMANVMScriptsOutput.txt")
    disconFromDiskImage = disconnectFromDiskImage("$connectionHandle")
    writexmlToFile = writeXmlToFile()
    vmData = '"' + "%" + "%s" % (vmuuid) + "%" + '"'
    createVM = createVMScript()
    vdiCreate = createVMVDI()
    storage = "%Local storage%"
    
 
    psScript = u"""
    %s
    %s
    
    $vmName = "%s"

    $filter1 = "SELECT * FROM Xen_ComputerSystemSettingData where InstanceID like "
    $filter = $filter1 + '"' + %s + '"'


    $cimUri = "http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/" + "Xen_ComputerSystemSettingData"

    # Perform the enumeration against the given CIM class

    $xenEnum = $objSession.Enumerate($cimUri, $filter, "http://schemas.microsoft.com/wbem/wsman/1/WQL")
    $timestamp = Get-Date -Format o

    # This returns an object that contains all elements in $cimUri

    # Declare an empty, generic array with no specific type
    $xenEnumXml = @()

    # Log the jobResult for Element in the array into importWSMANVMScriptsOutput.txt
    "jobResult for Element in the array" | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append
    $xenEnum | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append

    # Read out each returned element as a member of the array
    while (!$xenEnum.AtEndOfStream) {
        $elementRec = $xenEnum.ReadItem()
        $xenEnumXml += $elementRec
    }
    $xenEnumXml | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append


    $vmDataInfo = [xml]$xenEnumXml

    $vmRam = %s
    $vmProc = %s
    $vmType = $vmDataInfo.Xen_ComputerSystemSettingData.VirtualSystemType

    %s

    $vm = $newVm

    $vhdFiles = Get-ChildItem Q:
    Import-Module BitsTransfer


    $dialect = "http://schemas.microsoft.com/wbem/wsman/1/WQL"  # This is used for all WQL filters
    $filterTemp = "SELECT * FROM Xen_StoragePool where Name like "
    $filterStr = $filterTemp + '"' + "%s" + '"'
    $xenEnum = $objSession.Enumerate("http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePool", $filterStr, $dialect)

    $timestamp = Get-Date -Format o
    # Log the jobResult for WQL Filters into importWSMANVMScriptsOutput.txt
    "jobResult for WQL Filters" | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append
    $xenEnum | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append

    $localSr = [xml]$xenEnum.ReadItem()


    foreach ($element in $vhdFiles) {
        # Create a VDI
        $fileSplit = $element.Name.Split(".")

        $vdiName = $element.BaseName
        $addressOnParent = $fileSplit[0]
        $vdiMb = (($element.Length/1024)/1024) 
        $vmName =  $vm.Xen_ComputerSystem.Name
        $srPoolId = $localSr.Xen_StoragePool.PoolID
         
        $bootable = "false"
        if ($fileSplit[0] -eq 0){
            $bootable = "true"
        }
        %s
        $newVdi = $output
        $timestamp = Get-Date -Format o
        # Log the Vdi file details into importWSMANVMScriptsOutput.txt
        "Get the Vdi file details" | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append
        $timestamp | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append
        $vdiName | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append
        $vmName | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append
        if ($newVdi -ne $NULL)
        {
            if ($newVdi.AddResourceSetting_OUTPUT.ReturnValue -ne 0) {
                # check for a job status of finished
                $jobPercentComplete = 0
                while ($jobPercentComplete -ne 100) {
                    $jobResult = [xml]$objSession.Get($newVdi.AddResourceSetting_OUTPUT.Job.outerxml)
                    $jobPercentComplete = $jobresult.Xen_DisconnectFromDiskImageJob.PercentComplete
                    sleep 1
                    $jobResult | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append
                }
            }
        }
        $vm2Vdi = [xml]($objSession.Get($newvdi.AddResourceSetting_OUTPUT.ResultingResourceSetting.outerXML))
        # Log the Add Resource to Vdi into importWSMANVMScriptsOutput.txt
        "Get the Add Resource to Vdi" | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append
        $timestamp | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append
        $jobResult | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append

        # Parse the VBD into the Xen_DiskImage information needed
        $dsdHostResource = $vm2vdi.Xen_DiskSettingData.HostResource
        $vDisk = @()
        $vDiskHash = @{}
        $vDisk = $dsdHostResource.split(",")
        foreach ($i in $vDisk) {
            $tempArr = $i.Split("=")
            $vdiskHash.Add($tempArr[0], $tempArr[1])
        }
        $deviceID = $vDiskHash.DeviceID.Replace('"','')
        $systemName = $vDiskHash.SystemName.Replace('"','')
        $systemCreationClassName = $vDiskHash.SystemCreationClassName.Replace('"','')
        $creationClassName = $vDiskHash.'root/cimv2:Xen_DiskImage.CreationClassName'.Replace('"','')

        $vdi = @"
        <Xen_DiskImage>
            <DeviceID>$DeviceID</DeviceID>
            <CreationClassName>$CreationClassName</CreationClassName>
            <SystemCreationClassName>$SystemCreationClassName</SystemCreationClassName>
            <SystemName>$SystemName</SystemName>
        </Xen_DiskImage>
"@
        %s
        $transferVM = $jobResult        
        $source =  "Q:\" + $element.Name

        $transferJob = Start-BitsTransfer -Source $source -destination $transferVm.Xen_ConnectToDiskImageJob.TargetURI -Asynchronous -DisplayName XenVdiTransfer -TransferType Upload
        $timestamp = Get-Date -Format o
        "-Source " + $source + " -destination " + $transferVm.Xen_ConnectToDiskImageJob.TargetURI
        # Log the Cim call response on RAW file copy using BITS into importWSMANVMScriptsOutput.txt
        "Cim call response on RAW file copy using BITS" | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append
        $timestamp | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append
        $transferJob | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append

        while ($jobStatus.JobState -ne "transferred"){
                $jobStatus = Get-BitsTransfer -JobId $transferJob.JobId
                $timestamp = Get-Date -Format o
                Write-Progress -activity "BITS Transfer Upload" -status "copying.. " -PercentComplete ((($jobstatus.BytesTransferred / 1Mb) / ($jobStatus.BytesTotal / 1Mb)) * 100)
                if ($jobStatus.JobState -eq "TransientError") {
                    $jobstatus
                    "upload is paused for 10 secs due to TransientError from BITS"
                    sleep 10
                    $jobstatus | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append
                    Resume-BitsTransfer -BitsJob $transferJob
                }
                sleep 10
            }

            Write-Progress -activity "BITS Transfer Upload" -status "copying.. " -completed
        # Log the Transfer Job Status for RAW file into importWSMANVMScriptsOutput.txt
        "Transfer Job Status for RAW file" | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append
        $timestamp | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append
        $jobStatus | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append
        $transferJob | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append

        $bitsTime = $jobstatus.TransferCompletionTime - $jobstatus.CreationTime
        $bitsTime.TotalSeconds.ToString() + " Seconds"


        Complete-BitsTransfer $transferJob.JobId

        $connectionHandle = $transferVm.Xen_ConnectToDiskImageJob.ConnectionHandle
        %s
        $vdiDisconnect = $output
 
        # check for a job status of finished
        $jobPercentComplete = 0
        while ($jobPercentComplete -ne 100) {
            $jobResult = [xml]$objSession.Get($vdiDisconnect.DisconnectFromDiskImage_OUTPUT.Job.outerxml)
            $timestamp = Get-Date -Format o
            $jobPercentComplete = $jobresult.Xen_DisconnectFromDiskImageJob.PercentComplete
            $jobPercentComplete
            sleep 3
            $jobResult | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append
        }
        # Log the jobResult for VDIDisconnect into importWSMANVMScriptsOutput.txt
        "jobResult for VDIDisconnect" | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append
        $timestamp | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append
        WriteXmlToFile $jobResult | Out-File "c:\importWSMANVMScriptsOutput.txt" -Append

    }
    $vmUuid = $vm.Xen_ComputerSystem.Name
    $vmUuid
 
    """ % (writexmlToFile,wsmanConn,vmName,vmData,vmRam,vmProc,createVM,storage,vdiCreate,connToDiskImage,disconFromDiskImage)
    
    return psScript

def createVMVDI():

    endPointRef = endPointReference("Xen_VirtualSystemManagementService")

    psScript = u"""
    %s
    $actionUri = $xenEnum

    $parameters = @"
    <AddResourceSetting_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/root/cimv2/Xen_VirtualSystemManagementService">
    <ResourceSetting>
        <dsd:Xen_DiskSettingData
            xmlns:dsd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_DiskSettingData"
            xsi:type="Xen_DiskettingData_Type">
            <dsd:PoolID>$srPoolId</dsd:PoolID>
            <dsd:ElementName>$vdiName</dsd:ElementName>
            <dsd:ResourceType>19</dsd:ResourceType>
            <dsd:VirtualQuantity>$vdiMb</dsd:VirtualQuantity>
            <dsd:AllocationUnits>MegaBytes</dsd:AllocationUnits>
            <dsd:Bootable>$bootable</dsd:Bootable>
            <dsd:Access>3</dsd:Access>
            <dsd:AddressOnParent>$addressOnParent</dsd:AddressOnParent>
        </dsd:Xen_DiskSettingData>
    </ResourceSetting>
    <AffectedSystem>
        <a:Address xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address>
        <a:ReferenceParameters xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:w="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
            <w:ResourceURI>http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem</w:ResourceURI>
            <w:SelectorSet>
                <w:Selector Name="Name">$vmName</w:Selector>
                <w:Selector Name="CreationClassName">Xen_ComputerSystem</w:Selector>
            </w:SelectorSet>
        </a:ReferenceParameters>
    </AffectedSystem>
    </AddResourceSetting_INPUT>
"@

    # $objSession.Get($actionURI)

    $output = [xml]$objSession.Invoke("AddResourceSetting", $actionURI, $parameters)

    """ % (endPointRef)

    return psScript

def enumClassFilter(cimClass = None): 
    # This is the core to perform enumerations wit a filter
    # All that is required to pass in is the CIM Class and an array is returned.

    psScript = u"""
    # Form the URI String
    $cimUri = "http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/" + "%s"

    # Perform the enumeration against the given CIM class

    $xenEnum = $objSession.Enumerate($cimUri, $filter, "http://schemas.microsoft.com/wbem/wsman/1/WQL")

    # This returns an object that contains all elements in $cimUri

    # Declare an empty, generic array with no specific type
    $xenEnumXml = @()

    # Read out each returned element as a member of the array
    while (!$xenEnum.AtEndOfStream) {
        $elementRec = $xenEnum.ReadItem()
        $xenEnumXml += [xml]$elementRec
    }

    # Return the array
    """ % (cimClass)

    return psScript

def connectToDiskImage(transProtocol = None,
                       ssl = None):
    
    endPointRef = endPointReference("Xen_StoragePoolManagementService")
    psScript = u"""
    if ($vdi.GetType().Name -ne "XmlDocument") {
        $vdi = [xml]$vdi
    }
    $protocol = "%s"
    $ssl = "%s"
    $DeviceID = $vdi.Xen_DiskImage.DeviceID
    $CreationClassName = $vdi.Xen_DiskImage.CreationClassName
    $SystemCreationClassName = $vdi.Xen_DiskImage.SystemCreationClassName
    $SystemName = $vdi.Xen_DiskImage.SystemName

    %s
    $actionUri = $xenEnum
    
    $parameters = @"
    <ConnectToDiskImage_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePoolManagementService">
            <DiskImage xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
                <wsa:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:Address>
                <wsa:ReferenceParameters>
                <wsman:ResourceURI>http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_DiskImage</wsman:ResourceURI>
                <wsman:SelectorSet>
                        <wsman:Selector Name="DeviceID">$DeviceID</wsman:Selector>
                        <wsman:Selector Name="CreationClassName">$CreationClassName</wsman:Selector>
                        <wsman:Selector Name="SystemCreationClassName">$SystemCreationClassName</wsman:Selector>
                        <wsman:Selector Name="SystemName">$SystemName</wsman:Selector>
                </wsman:SelectorSet>
                </wsa:ReferenceParameters>
            </DiskImage>
            <Protocol>$protocol</Protocol>
            <UseSSL>$ssl</UseSSL>
    </ConnectToDiskImage_INPUT>
"@

    $startTransfer = [xml]$objSession.Invoke("ConnectToDiskImage", $actionURI, $parameters)
    
    if ($startTransfer -ne $NULL)
    {
        if ($startTransfer.RequestStateChange_OUTPUT.ReturnValue -ne 0) {
        $jobPercentComplete = 0
        while ($jobPercentComplete -ne 100) {
            $jobResult = [xml]$objSession.Get($startTransfer.ConnectToDiskImage_OUTPUT.job.outerxml)
            $jobPercentComplete = $jobResult.Xen_ConnectToDiskImageJob.PercentComplete
            sleep 3
            }
        }
    }
    """ % (transProtocol,ssl,endPointRef)
 
    return psScript

def connectToDiskImageWithStaticIP(transProtocol = None, 
                                   ssl = None,
                                   static_ip = None,
                                   mask = None,
                                   gateway = None,
                                   scriptlog = "c:\importWSMANScriptsOutput.txt"):

    endPointRef = endPointReference("Xen_StoragePoolManagementService")
    psScript = u"""
    if ($vdi.GetType().Name -ne "XmlDocument") {
        $vdi = [xml]$vdi
    }
    $protocol = "%s"
    $ssl = "%s"
    $scriptlog = "%s"
    $DeviceID = $vdi.Xen_DiskImage.DeviceID
    $CreationClassName = $vdi.Xen_DiskImage.CreationClassName
    $SystemCreationClassName = $vdi.Xen_DiskImage.SystemCreationClassName
    $SystemName = $vdi.Xen_DiskImage.SystemName

    %s
    $actionUri = $xenEnum
    $timestamp = Get-Date -Format o
    # Log the actionUri for connectToDiskImage endpoint reference into importWSMANScriptsOutput.txt
    "Get the actionUri for connectToDiskImage" | Out-File $scriptlog -Append
    $timestamp | Out-File $scriptlog -Append
    $actionUri | Out-File $scriptlog -Append

    $parameters = @"
    <ConnectToDiskImage_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePoolManagementService">
            <NetworkConfiguration>%s</NetworkConfiguration>
            <NetworkConfiguration>%s</NetworkConfiguration>
            <NetworkConfiguration>%s</NetworkConfiguration>
            <DiskImage xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
                <wsa:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:Address>
                <wsa:ReferenceParameters>
                <wsman:ResourceURI>http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_DiskImage</wsman:ResourceURI>
                <wsman:SelectorSet>
                        <wsman:Selector Name="DeviceID">$DeviceID</wsman:Selector>
                        <wsman:Selector Name="CreationClassName">$CreationClassName</wsman:Selector>
                        <wsman:Selector Name="SystemCreationClassName">$SystemCreationClassName</wsman:Selector>
                        <wsman:Selector Name="SystemName">$SystemName</wsman:Selector>
                </wsman:SelectorSet>
                </wsa:ReferenceParameters>
            </DiskImage>
            <Protocol>$protocol</Protocol>
            <UseSSL>$ssl</UseSSL>
    </ConnectToDiskImage_INPUT>
"@

    $startTransfer = [xml]$objSession.Invoke("ConnectToDiskImage", $actionURI, $parameters)
    $timestamp = Get-Date -Format o
    # Log the Cim call response for connectToDiskImage into importWSMANScriptsOutput.txt
    "Cim call response for connectToDiskImage" | Out-File $scriptlog -Append
    $timestamp | Out-File $scriptlog -Append
    WriteXmlToFile $startTransfer | Out-File $scriptlog -Append

    if ($startTransfer -ne $NULL)
    {
        if ($startTransfer.RequestStateChange_OUTPUT.ReturnValue -ne 0) {
        $jobPercentComplete = 0
        while ($jobPercentComplete -ne 100) {
            $jobResult = [xml]$objSession.Get($startTransfer.ConnectToDiskImage_OUTPUT.job.outerxml)
            $jobPercentComplete = $jobResult.Xen_ConnectToDiskImageJob.PercentComplete
            sleep 3
            }
        }
        $timestamp = Get-Date -Format o
        # Log the jobResult for connectToDiskImage into importWSMANScriptsOutput.txt
        "JobResult for connectToDiskImage" | Out-File $scriptlog -Append
        $timestamp | Out-File $scriptlog -Append
        WriteXmlToFile $jobResult | Out-File $scriptlog -Append
    }
    """ % (transProtocol,ssl,scriptlog,endPointRef,static_ip,mask,gateway)
 
    return psScript

def disconnectFromDiskImage(connHandle = None):

    endPointRef = endPointReference("Xen_StoragePoolManagementService")
    psScript = u"""

    %s
    $actionUri = $xenEnum
    $timestamp = Get-Date -Format o
    # Log the actionUri for DisconnectFromDiskImage Call into importWSMANScriptsOutput.txt
    "actionUri for DisconnectFromDiskImage Call" | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    $actionUri | Out-File "c:\importWSMANScriptsOutput.txt" -Append

    $parameters = @"
    <DisconnectFromDiskImage_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePoolManagementService">
                <ConnectionHandle>%s</ConnectionHandle>
    </DisconnectFromDiskImage_INPUT>
"@

    $output = [xml]$objSession.Invoke("DisconnectFromDiskImage", $actionURI, $parameters)
    $timestamp = Get-Date -Format o
    # Log the Cim call response for DisconnectFromDiskImageResponse into importWSMANScriptsOutput.txt
    "Cim call response for DisconnectFromDiskImageResponse" | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    WriteXmlToFile $output | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    """ % (endPointRef,connHandle)
     
    return psScript

def endPointReference(cimClass = None):
    psScript = u"""
    # Set the return flag to an End Point Reference
    $enumFlags = $obj.EnumerationFlagReturnEPR()

    # Form the URI String
    $cimResource = "http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/" + "%s"

    # Perform the enumeration against the given CIM class - the two $NULLs are necessary
    $xenEnum = $objSession.Enumerate($cimResource, $NULL, $NULL, $enumFlags)

    $xenEnum = $xenEnum.ReadItem()
    """ % (cimClass)
    
    return psScript

def jobCleanUp(password = None,
               hostIPAddr = None):
   
    wsmanConn = wsmanConnection(password,hostIPAddr) 
    psScript = u"""
    # This does not take input, it simply cleans jobs that do not have errors
    
    %s
    $enumFlags = $obj.EnumerationFlagReturnEPR()

    # Make sure this does not go into an infinite loop
    $30Minutes = New-TimeSpan -Minutes 30
    $startTime = Get-Date
    $ahead30 = ($startTime + $30Minutes)

    do {
        $xenEnum = $objSession.Enumerate("http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_Job", $NULL, $NULL, $enumFlags)

        $allJobs = @()
        while (!$xenEnum.AtEndOfStream) {
            $elementRec = $xenEnum.ReadItem()
            $allJobs += $elementRec
        }

        "Job Count: " + $allJobs.Count
        foreach ($jobEpr in $allJobs) {
            $job = $objsession.Get($jobEpr)
            $jobXml = [xml]$job
            # Check for the state of the Job "JobState"
            $jobState = $jobXml.GetElementsByTagName("p:JobState")
            # $errorCode is returned and treated as an Array.
            foreach ($element in $jobState){
                    $stateValue = $element."#Text"
            }
            # Get the InstanceID as well
            $jobInstance = $jobXml.GetElementsByTagName("p:InstanceID")
            foreach ($element in $jobInstance){
                    $instanceValue = $element."#Text"
            }

            switch ($stateValue) {
                3 {"Starting: " + $instanceValue}
                4 {"Running: " + $instanceValue}
                5 {"Suspended: " + $instanceValue}
                6 {"Shutting Down: " + $instanceValue}
                7 {$null = $objsession.Delete($jobEpr)}
                8 {"Terminated: " + $instanceValue}
                9 {"Killed: " + $instanceValue}
                10 {"Exception: " + $instanceValue}
                default {"Stuck?: " + $instanceValue + " The State: " + $stateValue}
            }
        }
        sleep 5

        # The break out if the clean up takes longer than 30 minutes
        # most likely something went wrong or the jobs are taking an incredibly long time
        $time = Get-Date
        if ($time -ge $ahead30)
        {
            break
        }

    } until ($allJobs.Count -eq 0)
    """ %(wsmanConn)

    return psScript

def createWSMANVMFromTemplate(password = None,
                              hostIPAddr = None,
                              templateName = None,
                              vmName = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSystemManagementService")
    storage = "%Local storage%"
    template = '"' + "%" + "%s" % (templateName)+ "%" + '"'
    vm = '"' + "%" + "%s" % (vmName)+ "%" + '"'
    jobName = '"' + "%" + "$jobVmName" + "%" + '"'
    psScript = u"""

    %s
    $dialect = "http://schemas.microsoft.com/wbem/wsman/1/WQL"  # This is used for all WQL filters
    $filter1 = "SELECT * FROM Xen_StoragePool where Name like "
    $filter = $filter1 + '"' + "%s" + '"'
    $xenEnum = $objSession.Enumerate("http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePool", $filter, $dialect)
    $localSr = [xml]$xenEnum.ReadItem()

    $filter1 = "SELECT * FROM Xen_ComputerSystemTemplate where ElementName like "
    $filter = $filter1 + '"' + %s + '"'
    $xenEnum = $objSession.Enumerate("http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystemTemplate", $filter, $dialect)
    $sourceTemplate = [xml]$xenEnum.ReadItem()

    $newVmName = "%s"
    $refVmInstanceId = $sourceTemplate.Xen_ComputerSystemTemplate.InstanceID
    $xenSrInstanceId = $localSr.Xen_StoragePool.InstanceID
 
    %s
    $actionUri = $xenEnum
    $parameters = @"
    <CopySystem_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService"
        xmlns:cssd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystemSettingData">
        <SystemSettings>
         <cssd:Xen_ComputerSystemSettingData
             xsi:type="Xen_ComputerSystemSettingData_Type">
              <cssd:Description>This is a script created system</cssd:Description>
              <cssd:ElementName>$newVmName</cssd:ElementName>
           </cssd:Xen_ComputerSystemSettingData>
        </SystemSettings>
        <ReferenceConfiguration xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
              <wsa:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:Address>
              <wsa:ReferenceParameters>
              <wsman:ResourceURI>http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystemTemplate</wsman:ResourceURI>
              <wsman:SelectorSet>
                    <wsman:Selector Name="InstanceID">$refVmInstanceId</wsman:Selector>
              </wsman:SelectorSet>
              </wsa:ReferenceParameters>
        </ReferenceConfiguration>
        <StoragePool xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
              <wsa:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:Address>
              <wsa:ReferenceParameters>
              <wsman:ResourceURI>http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePool</wsman:ResourceURI>
              <wsman:SelectorSet>
                    <wsman:Selector Name="InstanceID">$xenSrInstanceId</wsman:Selector>
              </wsman:SelectorSet>
              </wsa:ReferenceParameters>
        </StoragePool>
    </CopySystem_INPUT>
"@

    $output = [xml]$objSession.Invoke("CopySystem", $actionURI, $parameters)
 
    sleep 10
   
    $createVmResult = $output

    if ($createVmResult.CopySystem_OUTPUT.ReturnValue -ne 0) {
        # check for a job status of finished
        $jobPercentComplete = 0
        while ($jobPercentComplete -ne 100) {
            $jobResult = [xml]$objSession.Get($createVmResult.CopySystem_OUTPUT.Job.outerxml)
            $jobPercentComplete = $jobresult.Xen_VirtualSystemCreateJob.PercentComplete
            sleep 3
        }
        # query for the new VM
        $jobVmName = $jobresult.Xen_VirtualSystemCreateJob.ElementName
        $filter1 = "SELECT * FROM Xen_ComputerSystem where ElementName like "
        $filter = $filter1 + '"' + %s + '"'
        $xenEnum = $objSession.Enumerate("http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem", $filter, $dialect)
        $vm = [xml]$xenEnum.ReadItem()
        $vmUuid = $vm.Xen_ComputerSystem.Name
    } else {
        $filter1 = "SELECT * FROM Xen_ComputerSystem where ElementName like "
        $filter = $filter1 + '"' +%s + '"'
        $xenEnum = $objSession.Enumerate("http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem", $filter, $dialect)
        $vm = [xml]$xenEnum.ReadItem()
        $vmUuid = $vm.Xen_ComputerSystem.Name
    }
    $vmUuid    

    """ % (wsmanConn,storage,template,vmName,endPointRef,jobName,vm)
 
    return psScript

def copyWSMANVM(password = None,
                 hostIPAddr = None,
                 origVMName = None,
                 copiedVMName = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    storage = "%Local storage%"
    sourceVMName = '"' + "%" + "%s" % (origVMName)+ "%" + '"'
    endPointRef = endPointReference("Xen_VirtualSystemManagementService")
    writexmlToFile = writeXmlToFile()
    vm = '"' + "%" + "%s" % (copiedVMName)+ "%" + '"'
    jobName = '"' + "%" + "$jobVmName" + "%" + '"'

    psScript = u"""
    %s
    %s
    $newVmName = "%s"
    $dialect = "http://schemas.microsoft.com/wbem/wsman/1/WQL"  # This is used for all WQL filters
    $filter1 = "SELECT * FROM Xen_ComputerSystemSettingData where ElementName like "
    $filter = $filter1 + '"' +  %s + '"'
    $xenEnum = $objSession.Enumerate("http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystemSettingData", $filter, $dialect)
    # We are only expecting one item back.
    $sourceVm = [xml]$xenEnum.ReadItem()
    $refVmInstanceId = $sourceVm.Xen_ComputerSystemSettingData.InstanceID

    $filter1 = "SELECT * FROM Xen_StoragePool where Name like "
    $filter = $filter1 + '"' + "%s" + '"'
    $xenEnum = $objSession.Enumerate("http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePool", $filter, $dialect)
    $localSr = [xml]$xenEnum.ReadItem()
    $xenSrInstanceId = $localSr.Xen_StoragePool.InstanceID

    %s
    $actionUri = $xenEnum
    $timestamp = Get-Date -Format o
    "Action URI for copyvm CIM call" | Out-File "c:\copyVMWSMANScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\copyVMWSMANScriptsOutput.txt" -Append
    $scriptOutput = [xml]$actionUri
    WriteXmlToFile $scriptOutput | Out-File "c:\copyVMWSMANScriptsOutput.txt" -Append

    $parameters = @"
    <CopySystem_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService"
        xmlns:cssd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystemSettingData">
        <SystemSettings>
         <cssd:Xen_ComputerSystemSettingData
             xsi:type="Xen_ComputerSystemSettingData_Type">
              <cssd:Description>This is a script created system</cssd:Description>
              <cssd:ElementName>$newVmName</cssd:ElementName>
              <cssd:Other_Config>HideFromXenCenter=false</cssd:Other_Config>
              <cssd:Other_Config>transfervm=false</cssd:Other_Config>
           </cssd:Xen_ComputerSystemSettingData>
        </SystemSettings>
        <ReferenceConfiguration xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
              <wsa:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:Address>
              <wsa:ReferenceParameters>
              <wsman:ResourceURI>http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystemSettingData</wsman:ResourceURI>
              <wsman:SelectorSet>
                    <wsman:Selector Name="InstanceID">$refVmInstanceId</wsman:Selector>
              </wsman:SelectorSet>
              </wsa:ReferenceParameters>
        </ReferenceConfiguration>
        <StoragePool xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
              <wsa:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:Address>
              <wsa:ReferenceParameters>
              <wsman:ResourceURI>http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePool</wsman:ResourceURI>
              <wsman:SelectorSet>
                    <wsman:Selector Name="InstanceID">$xenSrInstanceId</wsman:Selector>
              </wsman:SelectorSet>
              </wsa:ReferenceParameters>
        </StoragePool>
    </CopySystem_INPUT>
"@

    $output = [xml]$objSession.Invoke("CopySystem", $actionURI, $parameters)
    $timestamp = Get-Date -Format o
    "CIM call response for CopySystem" | Out-File "c:\copyVMWSMANScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\copyVMWSMANScriptsOutput.txt" -Append
    WriteXmlToFile $output | Out-File "c:\copyVMWSMANScriptsOutput.txt" -Append
 
    sleep 10
    $createVmResult = $output

    if ($createVmResult.CopySystem_OUTPUT.ReturnValue -ne 0) {
        # check for a job status of finished
        $jobPercentComplete = 0
        while ($jobPercentComplete -ne 100) {
            $jobResult = [xml]$objSession.Get($createVmResult.CopySystem_OUTPUT.Job.outerxml)
            $jobPercentComplete = $jobresult.Xen_VirtualSystemCreateJob.PercentComplete
            sleep 3
        }
        $timestamp = Get-Date -Format o
        "jobResult for CopySystem" | Out-File "c:\copyVMWSMANScriptsOutput.txt" -Append
        $timestamp | Out-File "c:\copyVMWSMANScriptsOutput.txt" -Append
        WriteXmlToFile $jobResult | Out-File "c:\copyVMWSMANScriptsOutput.txt" -Append
        
        # query for the new VM
        $jobVmName = $jobresult.Xen_VirtualSystemCreateJob.ElementName
        $filter1 = "SELECT * FROM Xen_ComputerSystem where ElementName like "
        $filter = $filter1 + '"' + %s + '"'
        $xenEnum = $objSession.Enumerate("http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem", $filter, $dialect)
        $vm = [xml]$xenEnum.ReadItem()
        $vmUuid = $vm.Xen_ComputerSystem.Name
    } else {
        $filter1 = "SELECT * FROM Xen_ComputerSystem where ElementName like "
        $filter = $filter1 + '"' +%s + '"'
        $xenEnum = $objSession.Enumerate("http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem", $filter, $dialect)
        $vm = [xml]$xenEnum.ReadItem()
        $vmUuid = $vm.Xen_ComputerSystem.Name
    }
    $vmUuid

    """ % (writexmlToFile,wsmanConn,copiedVMName,sourceVMName,storage,endPointRef,jobName,vm)

    return psScript 

def createWSMANCifsIsoSr(password = None,
                    hostIPAddr = None,
                    location = None,
                    cifsuser = None,
                    cifspassword = None, 
                    isoSRName = None,
                    vdiName = None,
                    vmuuid = None,
                    static_ip = None,
                    mask = None,
                    gateway = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_StoragePoolManagementService")
    vdiCreate = createVDI()
    transProtocol = "bits"
    ssl = "0"
    connToDiskImage = connectToDiskImageWithStaticIP(transProtocol,ssl,static_ip,mask,gateway)
    disconFromDiskImage = disconnectFromDiskImage("$connectionHandle")
    writexmlToFile = writeXmlToFile()
    attachIso  = attachISO(vmuuid)
#    $isoFile = Get-ChildItem Q: | where {$_.Extension -eq ".iso"}
    psScript = u"""
    %s
    %s
    %s
    $actionUri = $xenEnum
    $newSrName = "%s" 
    $location = "%s"
    $type = "cifs"
    $isoPath = ""
    $cifsUser = "%s"
    $cifsPass = "%s"
    $parameters = @"
    <CreateStoragePool_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePoolManagementService"
    xmlns:rasd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData">
        <ElementName>$newSrName</ElementName>
        <ResourceType>16</ResourceType>
        <Settings>
            <rasd:CIM_ResourceAllocationSettingData xsi:type="CIM_ResourceAllocationSettingData_Type">
              <rasd:Connection>location=$location</rasd:Connection>
              <rasd:Connection>type=$type</rasd:Connection>
              <rasd:Connection>iso_path=$isoPath</rasd:Connection>
              <rasd:Connection>username=$cifsUser</rasd:Connection>
              <rasd:Connection>cifspassword=$cifsPass</rasd:Connection>
              <rasd:ResourceSubType>iso</rasd:ResourceSubType>
            </rasd:CIM_ResourceAllocationSettingData>
        </Settings>
    </CreateStoragePool_INPUT>
"@

    # $objSession.Get($actionURI)
    $output = [xml]$objSession.Invoke("CreateStoragePool", $actionURI, $parameters)

    $addIsoSrResult = $output
    if ($addIsoSrResult -ne $NULL)
    {
        if ($addIsoSrResult.CreateStoragePool_OUTPUT.ReturnValue -ne 0) {
            # check for a job status of finished
            $jobPercentComplete = 0
            while ($jobPercentComplete -ne 100) {
                $jobResult = [xml]$objSession.Get($addIsoSrResult.CreateStoragePool_OUTPUT.Job.outerxml)
                $jobPercentComplete = $jobresult.Xen_StoragePoolManagementServiceJob.PercentComplete
                $jobPercentComplete
                sleep 3
            }
        }
    }

    $isoSr = [xml]$objSession.Get($addIsoSrResult.CreateStoragePool_OUTPUT.Pool.outerxml)
    $isoSr.Xen_StoragePool.InstanceID
    $isoFile = Get-ChildItem Q:
    $isoSizeMb = $isoFile.Length / 1MB

    $vdiMb = [math]::round($isoSizeMb)
    $vdiMb = $vdiMb + 2
    $vdiName = "%s"
    $srPoolId = $isosr.Xen_StoragePool.PoolID
    %s
    $vdi = $objSession.Get($createvdiresult.CreateDiskImage_OUTPUT.ResultingDiskImage.outerxml)
    $vdi.Xen_StoragePoolManagementService.Name
    Import-Module BitsTransfer
    %s
    $vdi.Xen_DiskImage.DeviceID
    $transferVM = $jobResult
    $source =  $isofile.FullName
    $transferJob = Start-BitsTransfer -Source $source -destination $transferVm.Xen_ConnectToDiskImageJob.TargetURI -Asynchronous -DisplayName XenISOTransfer -TransferType Upload

    while ($jobStatus.JobState -ne "transferred"){
        $jobStatus = Get-BitsTransfer -JobId $transferJob.JobId

        Write-Progress -activity "BITS Transfer Upload" -status "copying.. " -PercentComplete ((($jobstatus.BytesTransferred / 1Mb) / ($jobStatus.BytesTotal / 1Mb)) * 100)
            if ($jobStatus.JobState -eq "TransientError") {
             $jobstatus
             "upload is paused for 10 secs due to TransientError from BITS"
             sleep 10
             Resume-BitsTransfer -BitsJob $transferJob
            }
    sleep 1
    }
    Write-Progress -activity "BITS Transfer Upload" -status "copying.. " -completed

    $bitsTime = $jobstatus.TransferCompletionTime - $jobstatus.CreationTime
    $bitsTime.TotalSeconds.ToString() + " Seconds"

    Complete-BitsTransfer $transferJob.JobID
    $connectionHandle = $transferVm.Xen_ConnectToDiskImageJob.ConnectionHandle
    %s
    $vdiDisconnect = $output
    $jobPercentComplete = 0
    while ($jobPercentComplete -ne 100) {
        $jobResult = [xml]$objSession.Get($vdiDisconnect.DisconnectFromDiskImage_OUTPUT.Job.outerxml)
        $jobPercentComplete = $jobresult.Xen_DisconnectFromDiskImageJob.PercentComplete
        sleep 3
    }

    %s
    """ % (writexmlToFile,wsmanConn,endPointRef,isoSRName,location,cifsuser,cifspassword,vdiName,vdiCreate,connToDiskImage,disconFromDiskImage,attachIso)

    return psScript

def attachISO(vmuuid = None):
   
    vmName = '"' + "%" + "%s" % (vmuuid)+ "%" + '"'
    endPointRef = endPointReference("Xen_VirtualSystemManagementService")
 
    psScript = u"""
    $dialect = "http://schemas.microsoft.com/wbem/wsman/1/WQL"
    if ($vdi.GetType().Name -ne "XmlDocument") {
        $vdi = [xml]$vdi
    }

    # find the (last if there are many, assume one) virtual CD device (VBD) of a VM
    $filter1 = "SELECT * FROM Xen_DiskSettingData WHERE InstanceID LIKE " 
    $filter  = $filter1 + '"' + %s + '"' + " AND ResourceType = 16"
    $xenEnum = $objSession.Enumerate("http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_DiskSettingData", $filter, $dialect)
    $xenEnumXml = [xml]$xenEnum.ReadItem()
    $vbdInstanceID = $xenEnumXml.Xen_DiskSettingData.InstanceID

    # Build the HostResource string
    $DeviceID = $vdi.Xen_DiskImage.DeviceID
    $hostResource = "root/cimv2:Xen_DiskImage.CreationClassName=`"Xen_DiskImage`",DeviceID=`"$DeviceID`",SystemCreationClassName=`"Xen_StoragePool`",SystemName=`"$vdi.Xen_DiskImage.SystemName`""

    %s
    $actionUri = $xenEnum 

    $parameters = @"
        <ModifyResourceSettings_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService">
            <ResourceSettings>
                <dsd:Xen_DiskSettingData
                    xmlns:dsd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_DiskSettingData"
                    xsi:type="Xen_DiskettingData_Type">
                    <dsd:InstanceID>$vbdInstanceID</dsd:InstanceID>
                    <dsd:HostResource>$hostResource</dsd:HostResource>
                    <dsd:ResourceType>16</dsd:ResourceType>
                </dsd:Xen_DiskSettingData>
            </ResourceSettings>
        </ModifyResourceSettings_INPUT>
"@

    $output = [xml]$objSession.Invoke("ModifyResourceSettings", $actionURI, $parameters)

    """ % (vmName,endPointRef)
  
    return psScript

def detachWSMANISO(password = None,
              hostIPAddr = None,
              vmuuid = None):
 
    wsmanConn = wsmanConnection(password,hostIPAddr) 
    vmName = '"' + "%" + "%s" % (vmuuid)+ "%" + '"'
    endPointRef = endPointReference("Xen_VirtualSystemManagementService")

    psScript = u"""
    %s
    $filter1 = "SELECT * FROM Xen_DiskSettingData WHERE InstanceID LIKE "
    $filter  = $filter1 + '"' + %s + '"' + " AND ResourceType = 16"

    # Form the URI String
    $cimUri = "http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/" + "Xen_DiskSettingData"

    # Perform the enumeration against the given CIM class

    $xenEnum = $objSession.Enumerate($cimUri, $filter, "http://schemas.microsoft.com/wbem/wsman/1/WQL")

    # This returns an object that contains all elements in $cimUri

    # Declare an empty, generic array with no specific type
    $xenEnumXml = @()

    # Read out each returned element as a member of the array
    while (!$xenEnum.AtEndOfStream) {
        $elementRec = $xenEnum.ReadItem()
        $xenEnumXml += $elementRec
    }

    $xenEnumXml = [xml]$xenEnumXml

    $vbdInstanceID = $xenEnumXml.Xen_DiskSettingData.InstanceID
    $device = '"' + "\" + '"'
    $hostResource = "Xen_DiskImage.DeviceID=$device"
    %s
    $actionUri = $xenEnum

    $parameters = @"
        <ModifyResourceSettings_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService">
            <ResourceSettings>
                <dsd:Xen_DiskSettingData
                    xmlns:dsd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_DiskSettingData"
                    xsi:type="Xen_DiskettingData_Type">
                    <dsd:InstanceID>$vbdInstanceID</dsd:InstanceID>
                    <dsd:HostResource>$hostResource</dsd:HostResource>
                    <dsd:ResourceType>16</dsd:ResourceType>
                </dsd:Xen_DiskSettingData>
            </ResourceSettings>
        </ModifyResourceSettings_INPUT>
"@

    $detachIsoResult = [xml]$objSession.Invoke("ModifyResourceSettings", $actionURI, $parameters)
    if ($detachIsoResult -ne $NULL)
    {
        if ($detachIsoResult.ModifyResourceSettings_OUTPUT.ReturnValue -ne 0) {
            # check for a job status of finished
            $jobPercentComplete = 0
            while ($jobPercentComplete -ne 100) {
                $jobResult = [xml]$objSession.Get($detachIsoResult.ModifyResourceSettings_OUTPUT.Job.outerxml)
                $jobPercentComplete = $jobresult.Xen_SystemModifyResourcesJob.PercentComplete
                # $jobPercentComplete
                sleep 3
            }
        }
    }
    """ %(wsmanConn,vmName,endPointRef)
 
    return psScript

def deleteWSMANSR(password = None,
             hostIPAddr = None,
             sr = None):

    endPointRef = endPointReference("Xen_StoragePoolManagementService")
    wsmanConn = wsmanConnection(password,hostIPAddr)

    psScript = u"""
    %s
    $InstanceID = "%s" 

    %s
    $actionUri = $xenEnum

    $parameters = @"
    <DeleteResourcePool_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePoolManagementService">
    <Pool>
        <a:Address xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address>
        <a:ReferenceParameters xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:w="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
            <w:ResourceURI>http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_StoragePool</w:ResourceURI>
            <w:SelectorSet>
                <w:Selector Name="InstanceID">$InstanceID</w:Selector>
            </w:SelectorSet>
        </a:ReferenceParameters>
    </Pool>
    </DeleteResourcePool_INPUT>
"@

    $removeIsoSrResult = [xml]$objSession.Invoke("DeleteResourcePool", $actionUri, $parameters)
    if ($removeIsoSrResult -ne $NULL)
    {
        if ($removeIsoSrResult.DeleteResourcePool_OUTPUT.ReturnValue -ne 0) {
            # check for a job status of finished
            $jobPercentComplete = 0
            $jobResult = 0
            while ($jobPercentComplete -ne 100) {
                $jobResult = [xml]$objSession.Get($removeIsoSrResult.DeleteResourcePool_OUTPUT.Job.outerxml)
                $jobPercentComplete = $jobresult.Xen_StoragePoolManagementServiceJob.PercentComplete
                # $jobPercentComplete
                sleep 3
            }
            $jobResult.Save("c:\jobresult.xml")
        }
    }

    """ % (wsmanConn,sr,endPointRef)

    return psScript

def forgetWSMANSR(password = None,
             hostIPAddr = None,
             sr = None):

    endPointRef = endPointReference("Xen_StoragePoolManagementService")
    wsmanConn = wsmanConnection(password,hostIPAddr)

    psScript = u"""
    %s
    $InstanceID = "%s"

    %s
    $actionUri = $xenEnum

    $parameters = @"
    <DetachStoragePool_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePoolManagementService">
    <Pool>
        <a:Address xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address>
        <a:ReferenceParameters xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:w="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
            <w:ResourceURI>http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_StoragePool</w:ResourceURI>
            <w:SelectorSet>
                <w:Selector Name="InstanceID">$InstanceID</w:Selector>
            </w:SelectorSet>
        </a:ReferenceParameters>
    </Pool>
    </DetachStoragePool_INPUT>
"@

    $removeIsoSrResult = [xml]$objSession.Invoke("DetachStoragePool", $actionUri, $parameters)
    if ($removeIsoSrResult -ne $NULL)
    {
        if ($removeIsoSrResult.DetachStoragePool_OUTPUT.ReturnValue -ne 0) {
            # check for a job status of finished
            $jobPercentComplete = 0
            while ($jobPercentComplete -ne 100) {
                $jobResult = [xml]$objSession.Get($removeIsoSrResult.DetachStoragePool_OUTPUT.Job.outerxml)
                $jobPercentComplete = $jobresult.Xen_StoragePoolManagementServiceJob.PercentComplete
                # $jobPercentComplete
                sleep 3
            }
        }
    }

    """ % (wsmanConn,sr,endPointRef)

    return psScript

def createVDI():

    endPointRef = endPointReference("Xen_StoragePoolManagementService")

    psScript = u"""
    %s
    $actionUri = $xenEnum
    $timestamp = Get-Date -Format o
    # Log the ActionUri for CreatingDiskImage via Xen_StoragePoolManagementService into importWSMANScriptsOutput.txt
    "ActionUri for CreatingDiskImage via Xen_StoragePoolManagementService" | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    $actionUri | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    $parameters = @"
        <CreateDiskImage_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePoolManagementService">
        <ResourceSetting>
            <dsd:Xen_DiskSettingData
            xmlns:dsd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_DiskSettingData"
            xsi:type="Xen_DiskSettingData_Type">
                <dsd:ElementName>$vdiName</dsd:ElementName>
                <dsd:ResourceType>19</dsd:ResourceType>
                <dsd:PoolID>$srPoolId</dsd:PoolID>
                <dsd:Bootable>false</dsd:Bootable>
                <dsd:VirtualQuantity>$vdiMb</dsd:VirtualQuantity>
                <dsd:AllocationUnits>MegaBytes</dsd:AllocationUnits>
                <dsd:Access>3</dsd:Access>
            </dsd:Xen_DiskSettingData>
        </ResourceSetting>
        </CreateDiskImage_INPUT>
"@

    # $objSession.Get($actionURI)
    $output = [xml]$objSession.Invoke("CreateDiskImage", $actionURI, $parameters)
    $timestamp = Get-Date -Format o
    # Log the cim call response for CreatingDiskImage into importWSMANScriptsOutput.txt
    "Cim call response for CreatingDiskImage" | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    $output | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    $createVdiResult = $output
    if ($createVdiResult -ne $NULL)
    {
        if ($createVdiResult.CreateDiskImage_OUTPUT.ReturnValue -ne 0) {
            # check for a job status of finished
            $jobPercentComplete = 0
            while ($jobPercentComplete -ne 100) {
                $jobResult = [xml]$objSession.Get($createVdiResult.CreateDiskImage_OUTPUT.Job.outerxml)
                $jobPercentComplete = $jobResult.Xen_StoragePoolManagementServiceJob.PercentComplete
                sleep 1
            }
        }
        $timestamp = Get-Date -Format o
        # Log the Job Result for CreatingDiskImage into importWSMANScriptsOutput.txt
        "Job Result of CreateDiskImage" | Out-File "c:\importWSMANScriptsOutput.txt" -Append
        $timestamp | Out-File "c:\importWSMANScriptsOutput.txt" -Append
        $jobResult | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    }

    """ % (endPointRef)
    return psScript 

def createWSMANVdiForVM(password = None,
                        hostIPAddr = None,
                        vdiName = None,
                        vdiSize = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    vdiCreate = createVDI()
    storage = "%Local storage%"

    psScript = u"""
    %s
    $vdiMb = "%s"
    $vdiName = "%s"

    $dialect = "http://schemas.microsoft.com/wbem/wsman/1/WQL"  # This is used for all WQL filters
    $filter1 = "SELECT * FROM Xen_StoragePool where Name like "
    $filter = $filter1 + '"' + "%s" + '"'
    $xenEnum = $objSession.Enumerate("http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePool", $filter, $dialect)
    $localSr = [xml]$xenEnum.ReadItem()

    $srPoolId = $localSr.Xen_StoragePool.PoolID
    %s
    $vdi = [xml]$objSession.Get($createvdiresult.CreateDiskImage_OUTPUT.ResultingDiskImage.outerxml)
    $vdi.Xen_DiskImage.Name
    $vdi.Xen_DiskImage.DeviceID
    $vdi.Xen_DiskImage.CreationClassName
    $vdi.Xen_DiskImage.SystemCreationClassName
    $vdi.Xen_DiskImage.SystemName

    """ % (wsmanConn,vdiSize,vdiName,storage,vdiCreate)
  
    return psScript 

def attachWSMANVdiToVM(password = None,
                       hostIPAddr = None,
                       vmuuid = None,
                       vdiDeviceId = None,
                       vdiuuid = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSystemManagementService")

    psScript = u"""
    %s
    %s
    $actionURI = $xenEnum
    $vmName = "%s"
    $vdiDeviceId = "%s"
    $vdiuuid = "%s"
    $HostResource = "root/cimv2:Xen_DiskImage.DeviceID=`"$vdiDeviceId`",Name=`"$vdiuuid`""
    $parameters = @"
        <AddResourceSetting_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService">
            <ResourceSetting>
                <dsd:Xen_DiskSettingData xmlns:dsd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_DiskSettingData" xsi:type="Xen_DiskSettingData_Type">
                    <dsd:HostResource>$HostResource</dsd:HostResource>
                    <dsd:ResourceType>19</dsd:ResourceType>
                </dsd:Xen_DiskSettingData>
            </ResourceSetting>
            <AffectedSystem xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
            <wsa:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:Address>
            <wsa:ReferenceParameters>
                <wsman:ResourceURI>http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem</wsman:ResourceURI>
                <wsman:SelectorSet>
                    <wsman:Selector Name="Name">$vmName</wsman:Selector>
                    <wsman:Selector Name="CreationClassName">Xen_ComputerSystem</wsman:Selector>
                </wsman:SelectorSet>
            </wsa:ReferenceParameters>
            </AffectedSystem>
        </AddResourceSetting_INPUT>
"@

    # $objSession.Get($actionURI)
    $output = [xml]$objSession.Invoke("AddResourceSetting", $actionURI, $parameters)


    """ % (wsmanConn,endPointRef,vmuuid,vdiDeviceId,vdiuuid)

    return psScript

def createWSMANNFSSR(password = None,
                     hostIPAddr = None,
                     isoSRName = None,
                     serverIP = None,
                     path = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_StoragePoolManagementService")

    psScript = u"""
    %s

    %s
    $actionUri = $xenEnum
    $newSrName = "%s"
    $server = "%s"
    $serverPath = "%s"
    $parameters = @"
    <CreateStoragePool_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePoolManagementService"
    xmlns:rasd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData">
        <ElementName>$newSrName</ElementName>
        <ResourceType>19</ResourceType>
        <Settings>
            <rasd:CIM_ResourceAllocationSettingData xsi:type="CIM_ResourceAllocationSettingData_Type">
              <rasd:Connection>server=$server</rasd:Connection>
              <rasd:Connection>serverpath=$serverPath</rasd:Connection>
              <rasd:ResourceSubType>nfs</rasd:ResourceSubType>
            </rasd:CIM_ResourceAllocationSettingData>
        </Settings>
    </CreateStoragePool_INPUT>

"@

    # $objSession.Get($actionURI)
    $addNfsSrResult = [xml]$objSession.Invoke("CreateStoragePool", $actionURI, $parameters)
    if ($addNfsSrResult -ne $NULL)
    {
        if ($addNfsSrResult.CreateStoragePool_OUTPUT.ReturnValue -ne 0) 
        {
            # check for a job status of finished
            $jobPercentComplete = 0
            while ($jobPercentComplete -ne 100) 
            {
                $jobResult = [xml]$objSession.Get($addNfsSrResult.CreateStoragePool_OUTPUT.Job.outerxml)
                $jobPercentComplete = $jobresult.Xen_StoragePoolManagementServiceJob.PercentComplete
                $jobPercentComplete
                sleep 3
            }
        }

        $nfsSr = [xml]$objSession.Get($addNfsSrResult.CreateStoragePool_OUTPUT.Pool.outerxml)
        $nfsSr.Xen_StoragePool.InstanceID
    }

    """ % (wsmanConn,endPointRef,isoSRName,serverIP,path)

    return psScript

def createWSMANNFSISOSR(password = None,
                        hostIPAddr = None,
                        isoSRName = None,
                        location = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_StoragePoolManagementService")

    psScript = u"""
    %s

    %s
    $actionUri = $xenEnum

    $newSrName = "%s"
    $location = "%s"

    $parameters = @"
    <CreateStoragePool_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePoolManagementService"
    xmlns:rasd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData">
        <ElementName>$newSrName</ElementName>
        <ResourceType>16</ResourceType>
        <Settings>
            <rasd:CIM_ResourceAllocationSettingData xsi:type="CIM_ResourceAllocationSettingData_Type">
              <rasd:Connection>location=$location</rasd:Connection>
              <rasd:ResourceSubType>iso</rasd:ResourceSubType>
            </rasd:CIM_ResourceAllocationSettingData>
        </Settings>
    </CreateStoragePool_INPUT>
"@

    $addNfsSrResult = [xml]$objSession.Invoke("CreateStoragePool", $actionURI, $parameters)

    if ($addNfsSrResult -ne $NULL)
    {
        if ($addNfsSrResult.CreateStoragePool_OUTPUT.ReturnValue -ne 0) 
        {
            # check for a job status of finished
            $jobPercentComplete = 0
            while ($jobPercentComplete -ne 100) 
            {
                $jobResult = [xml]$objSession.Get($addNfsSrResult.CreateStoragePool_OUTPUT.Job.outerxml)
                $jobPercentComplete = $jobresult.Xen_StoragePoolManagementServiceJob.PercentComplete
                $jobPercentComplete
                sleep 3
            }
        }

        $nfsIsoSr = [xml]$objSession.Get($addNfsSrResult.CreateStoragePool_OUTPUT.Pool.outerxml)
        $nfsIsoSr.Xen_StoragePool.InstanceID
    }
    """ % (wsmanConn,endPointRef,isoSRName,location)

    return psScript

def getWSMANHistoricalMetrics(password = None,
                              hostIPAddr = None,
                              uuid = None,
                              system = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_MetricService")
    output = "c:" + '\\' + "xmldata.xml"
    psScript = u"""
    %s
    $system = "%s"
    if ($system -eq "HOST")
    {   
        $timeDiff = New-TimeSpan -Minutes 30
        $creationClassName = "Xen_HostComputerSystem"
    }
    else
    {
        $timeDiff = New-TimeSpan -Minutes 2 
        $creationClassName = "Xen_ComputerSystem"
    }
    $startTime = ((Get-Date) - $timeDiff)
    if ($startTime.Second -ne 0)
    {
        $seconds = 60 -$startTime.Second
        $startTime = $startTime.AddSeconds($seconds)
    } 
    $objScriptTime = New-Object -ComObject WbemScripting.SWbemDateTime
    $objScriptTime.SetVarDate($startTime)
    $cimStartTime = $objScriptTime.Value

    $epochdiff = New-TimeSpan "01 January 1970 00:00:00" $startTime
    $secs = $epochdiff.TotalSeconds   
    $secs

    $vmPerformance = @()

    # Due to requirement for InstanceID Xen_ComputerSystem needs to e used as Xen_HostComputerSystem does not return the InstanceID
    $name = "%s"

    $parameters = @"
    <GetPerformanceMetricsForSystem_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_MetricService">
        <StartTime>$cimStartTime</StartTime>
        <System>
            <a:Address xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address>
            <a:ReferenceParameters
            xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:w="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
                <w:ResourceURI>http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem</w:ResourceURI>
                <w:SelectorSet>
                    <w:Selector Name="CreationClassName">$creationClassName</w:Selector>
                    <w:Selector Name="Name">$name</w:Selector>
                </w:SelectorSet>
            </a:ReferenceParameters>
        </System>
    </GetPerformanceMetricsForSystem_INPUT>
"@
    # Put this into an arry as if this was actually useful
    %s
    $metricService = $xenEnum
    $vmPerformance = [xml]$objSession.Invoke("GetPerformanceMetricsForSystem", $metricService, $parameters)
    $xmlData = $vmPerformance.GetPerformanceMetricsForSystem_OUTPUT.Metrics
    $xmlData | out-file "%s" -encoding:ascii 
    
    """ % (wsmanConn,system,uuid,endPointRef,output)

    return psScript

def getWSMANInstMetric(password = None,
                       hostIPAddr = None,
                       cimClass = None,
                       parameter = None,
                       vmuuid = None,
                       networkName = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    str = "$element." + cimClass + "." + parameter
    if networkName != None:
        str1 = "$element." + cimClass + "." + "Description"
    else:
        networkName ="$null"
    filter = "$null"

    if parameter == "MetricValue":
        key = "InstanceID"
    else:
        key  = "Name"

    if vmuuid != None:
        instanceID = '"' + '"' + "%" + "%s" % (vmuuid) + "%"+ '"' + '"' 
        filter = '"' + "SELECT * FROM %s where" % (cimClass) +  " %s " % (key) + "like %s" % (instanceID) + '"'
    
    psScript = u"""
    %s
    $cimUri = "http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/%s"
    $dialect = "http://schemas.microsoft.com/wbem/wsman/1/WQL"
    $filter = %s
    if ($filter -eq $null)
    { 
        $xenEnum = $objSession.Enumerate($cimUri)
    }
    else
    {
        $xenEnum = $objSession.Enumerate($cimUri,$filter,$dialect)
    }
    $xenEnumXml = @()
    while (!$xenEnum.AtEndOfStream) {
        $elementRec = $xenEnum.ReadItem()
        $xenEnumXml += [xml]$elementRec
    }
    $networkName = "%s"
    foreach ($element in $xenEnumXml){      
        if ($networkName -eq $null)
        {
            %s
        }
        else
        {
           if ($networkName -eq %s)
           {
               %s
           }
        }
        
    }

    """ % (wsmanConn,cimClass,filter,networkName,str,str1,str) 
   
    return psScript

def getWSMANInstHostCPUMetric(password = None,
                              hostIPAddr = None,
                              cimClass = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)

    psScript = u"""
    %s
    $cimUri = "http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/%s"
    $xenEnum = $objSession.Enumerate($cimUri)

    $xenEnumXml = @()
    while (!$xenEnum.AtEndOfStream) {
        $elementRec = $xenEnum.ReadItem()
        $xenEnumXml += [xml]$elementRec
    }

    foreach ($element in $xenEnumXml) {
        $element.%s.MetricValue
    }      

    """ % (wsmanConn,cimClass,cimClass)

    return psScript

def getWSMANInstDiskMetric(password = None,
                           hostIPAddr = None,
                           cimClass = None,
                           vbdName = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    str = "$element." + cimClass + "." + "MetricValue"
    str1 = "$element." + cimClass + "." + "ElementName"
    psScript = u"""
    %s
    $cimClass = "%s"
    $cimUri = "http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/$cimClass"
    $xenEnum = $objSession.Enumerate($cimUri)

    $xenEnumXml = @()
    while (!$xenEnum.AtEndOfStream) {
        $elementRec = $xenEnum.ReadItem()
        $xenEnumXml += [xml]$elementRec
    }
    $vbdName = "%s"
    foreach ($element in $xenEnumXml) {
        if (%s -eq $vbdName)
        {
            %s
        }
    }

    """ % (wsmanConn,cimClass,vbdName,str1,str)

    return psScript

def createWSMANISCSISR(password = None,
                       hostIPAddr = None,
                       srName = None,
                       target = None,
                       iqn = None,
                       scsiId = None,
                       chapUser = None,
                       chapPassword = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_StoragePoolManagementService")

    psScript = u"""
    %s
    %s
    $actionUri = $xenEnum
   
    $newSrName = "%s"
    $target = "%s"
    $targetIqn = "%s"
    $scsiId = "%s"
    $chapUser = "%s"
    $chapPassword = "%s"
    $Port = "3260"
 
    if ($chapUser -ne $Null)
    { 
        $parameters = @"
        <CreateStoragePool_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePoolManagementService"
        xmlns:rasd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData">
            <ElementName>$newSrName</ElementName>
            <ResourceType>19</ResourceType>
            <Settings>
                <rasd:CIM_ResourceAllocationSettingData xsi:type="CIM_ResourceAllocationSettingData_Type">
                <rasd:Connection>target=$target</rasd:Connection>
                <rasd:Connection>targetIQN=$targetIqn</rasd:Connection>
                <rasd:Connection>chapuser=$chapUser</rasd:Connection>
                <rasd:Connection>chappassword=$chapPassword</rasd:Connection>
                <rasd:Connection>Port=$Port</rasd:Connection>
                <rasd:Connection>SCSIid=$scsiId</rasd:Connection>
                <rasd:ResourceSubType>lvmoiscsi</rasd:ResourceSubType>
                </rasd:CIM_ResourceAllocationSettingData>
            </Settings>
        </CreateStoragePool_INPUT>
"@
    }
    Else
    {
        $parameters = @"
        <CreateStoragePool_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePoolManagementService"
        xmlns:rasd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData">
            <ElementName>$newSrName</ElementName>
            <ResourceType>19</ResourceType>
            <Settings>
                <rasd:CIM_ResourceAllocationSettingData xsi:type="CIM_ResourceAllocationSettingData_Type">
                <rasd:Connection>target=$target</rasd:Connection>
                <rasd:Connection>targetIQN=$targetIqn</rasd:Connection>
                <rasd:Connection>Port=$Port</rasd:Connection>
                <rasd:Connection>SCSIid=$scsiId</rasd:Connection>
                <rasd:ResourceSubType>lvmoiscsi</rasd:ResourceSubType>
                </rasd:CIM_ResourceAllocationSettingData>
            </Settings>
        </CreateStoragePool_INPUT>
"@
    }

    # $objSession.Get($actionURI)

    $addiscsiSrResult = [xml]$objSession.Invoke("CreateStoragePool", $actionURI, $parameters)
    if ($addiscsiSrResult -ne $NULL)
    {
        if ($addiscsiSrResult.CreateStoragePool_OUTPUT.ReturnValue -ne 0)
        {
        # check for a job status of finished
            $jobPercentComplete = 0
            while ($jobPercentComplete -ne 100) 
            {
                $jobResult = [xml]$objSession.Get($addiscsiSrResult.CreateStoragePool_OUTPUT.Job.outerxml)
                $jobPercentComplete = $jobresult.Xen_StoragePoolManagementServiceJob.PercentComplete
                $jobPercentComplete
                sleep 3
            }
        }

        $iscsiSr = [xml]$objSession.Get($addiscsiSrResult.CreateStoragePool_OUTPUT.Pool.outerxml)
        $iscsiSr.Xen_StoragePool.InstanceID
    }
    """ % (wsmanConn,endPointRef,srName,target,iqn,scsiId,chapUser,chapPassword)
  
    return psScript

def getWSMANVBDuuid(password = None,
                    hostIPAddr = None,
                    vdiuuid = None,
                    vmuuid = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    enumClass = enumClassFilter("Xen_DiskSettingData")
    str = '"' + "%" + "%s" % (vmuuid) + "%"+ '"'

    psScript = u"""
    %s
    $filter1 = "SELECT * FROM Xen_DiskSettingData where InstanceID like " 
    $filter = $filter1 + '"' + %s + '"'

    %s
    $vdiuuid = "%s"
    foreach ($element in $xenEnumXml) {
        if ($element.Xen_DiskSettingData.HostExtentName -eq $vdiuuid)
        {$element.Xen_DiskSettingData.InstanceID}
    }
    """ % (wsmanConn,str,enumClass,vdiuuid)

    return psScript

def dettachWSMANVBDFromVM(password = None,
                          hostIPAddr = None,
                          vbdInstanceID = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSystemManagementService")

    psScript = u"""
    %s
    %s
    $actionUri = $xenEnum
    $xenVbd = "%s"    
 
    $parameters = @"
        <RemoveResourceSettings_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns:dsd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_DiskSettingData"
        xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService">
        <ResourceSettings>
            <dsd:Xen_DiskSettingData xmlns:dsd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_DiskSettingData" xsi:type="Xen_DiskSettingData_Type">
                <dsd:InstanceID>$xenVbd</dsd:InstanceID>
                <dsd:ResourceType>16</dsd:ResourceType>
            </dsd:Xen_DiskSettingData>
        </ResourceSettings>
        </RemoveResourceSettings_INPUT>
"@

    # $objSession.Get($actionURI)
    $output = [xml]$objSession.Invoke("RemoveResourceSettings", $actionURI, $parameters)

    """ % (wsmanConn,endPointRef,vbdInstanceID)

    return psScript

def deleteWSMANVDI(password = None,
                   hostIPAddr = None,
                   deviceId = None,
                   creationClassName = None,
                   systemCreationClassName = None,
                   systemName = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_StoragePoolManagementService")

    psScript = u"""
    %s
    %s
    $actionUri = $xenEnum
    $DeviceID = "%s"
    $CreationClassName = "%s"
    $SystemCreationClassName = "%s"
    $SystemName = "%s"

    $parameters = @"
        <DeleteDiskImage_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePoolManagementService">
            <DiskImage>
                <a:Address xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address>
                <a:ReferenceParameters xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:w="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
                    <w:ResourceURI>http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_DiskImage</w:ResourceURI>
                    <w:SelectorSet>
                        <w:Selector Name="DeviceID">$DeviceID</w:Selector>
                        <w:Selector Name="CreationClassName">$CreationClassName</w:Selector>
                        <w:Selector Name="SystemCreationClassName">$SystemCreationClassName</w:Selector>
                        <w:Selector Name="SystemName">$SystemName</w:Selector>
                    </w:SelectorSet>
                </a:ReferenceParameters>
            </DiskImage>
        </DeleteDiskImage_INPUT>
"@

    # $objSession.Get($actionURI)
    $output = [xml]$objSession.Invoke("DeleteDiskImage", $actionURI, $parameters)

    """ % (wsmanConn,endPointRef,deviceId,creationClassName,systemCreationClassName,systemName)

    return psScript

def modifyWSMANProcessor(password = None,
                         hostIPAddr = None,
                         vmName = None,
                         procCount = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSystemManagementService")
    enumerateVM = enumVM(vmName)    

    psScript = u"""
    %s
    %s
    $actionUri = $xenEnum
    $vmProc = %s
    %s
    $vmInstanceId = $xenEnum.Xen_ComputerSystemSettingData.InstanceID  

    $parameters = @"
    <ModifyResourceSettings_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns:psd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ProcessorSettingData"
    xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService">
    <ResourceSettings>
        <psd:Xen_ProcessorSettingData >
            <psd:ResourceType>3</psd:ResourceType>
            <psd:VirtualQuantity>$vmProc</psd:VirtualQuantity>
            <psd:AllocationUnits>true</psd:AllocationUnits>
            <psd:InstanceID>$vmInstanceId</psd:InstanceID>
        </psd:Xen_ProcessorSettingData>
    </ResourceSettings>
    </ModifyResourceSettings_INPUT>
"@

    $output = [xml]$objSession.Invoke("ModifyResourceSettings", $actionURI, $parameters)
    """ % (wsmanConn,endPointRef,procCount,enumerateVM)

    return psScript

def enumVM(vmName):

    vmData = '"' + "%" + "%s" % (vmName) + "%" + '"'
  
    psScript = u"""
   
    $filter1 = "SELECT * FROM Xen_ComputerSystemSettingData where ElementName like "
    $filter = $filter1 + '"' + %s + '"'
    $cimClass = "Xen_ComputerSystemSettingData"
    $cimUri = "http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/" + $cimClass


    $xenEnum = $objSession.Enumerate($cimUri, $filter, "http://schemas.microsoft.com/wbem/wsman/1/WQL")

    $xenEnum = [xml]$xenEnum.ReadItem()

    """ % (vmData)

    return psScript

def modifyWSMANMemory(password = None,
                      hostIPAddr = None,
                      vmName = None,
                      newMemory = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSystemManagementService")
    enumerateVM = enumVM(vmName)

    psScript = u"""
    %s
    %s
    $actionUri = $xenEnum
    $vmRam = %s
    #$vmInstanceId = "Xen:ab744781-8449-f2c9-96e5-d85ac894f409"
    %s
    $vmInstanceId = $xenEnum.Xen_ComputerSystemSettingData.InstanceID

    $parameters = @"
    <ModifyResourceSettings_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns:msd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_MemorySettingData"
    xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService">
    <ResourceSettings>
        <msd:Xen_MemorySettingData>
            <msd:ResourceType>19</msd:ResourceType>
            <msd:VirtualQuantity>$vmRam</msd:VirtualQuantity>
            <msd:AllocationUnits>MegaBytes</msd:AllocationUnits>
            <msd:InstanceID>$vmInstanceId</msd:InstanceID>
        </msd:Xen_MemorySettingData>
    </ResourceSettings>
    </ModifyResourceSettings_INPUT>
"@

    $output = [xml]$objSession.Invoke("ModifyResourceSettings", $actionURI, $parameters)
    """ % (wsmanConn,endPointRef,newMemory,enumerateVM)

    return psScript

def remWSMANcddvdDrive(password = None,
                       hostIPAddr = None,
                       vmuuid = None,
                       driveType = None,
                       vbduuid = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSystemManagementService")

    if driveType == "DVD":
        resourceType = 16
    else:
        resourceType = 15
 
    psScript = u"""
    %s
    %s
    $actionURI = $xenEnum
    $resourceType = %s
  
    $vmInstanceId = "Xen:" + "%s" + "/" + "%s" 

    $parameters = @"
        <RemoveResourceSettings_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns:dsd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_DiskSettingData"
        xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService">
        <ResourceSettings>
            <dsd:Xen_DiskSettingData xmlns:dsd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_DiskSettingData" xsi:type="Xen_DiskSettingData_Type">
                <dsd:InstanceID>$vmInstanceId</dsd:InstanceID>
                <dsd:ResourceType>$resourceType</dsd:ResourceType>
            </dsd:Xen_DiskSettingData>
        </ResourceSettings>
        </RemoveResourceSettings_INPUT>
"@

    # $objSession.Get($actionURI)
    $output = [xml]$objSession.Invoke("RemoveResourceSettings", $actionURI, $parameters)

    """ % (wsmanConn,endPointRef,resourceType,vmuuid,vbduuid)
  
    return psScript

def addWSMANcddvdDrive(password = None,
                       hostIPAddr = None,
                       vmuuid = None,
                       driveType = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    drive = addDrive(driveType)
    endPointRef = endPointReference("Xen_VirtualSystemManagementService")

    psScript = u"""
    %s
    $vmInstanceId = "Xen:" + "%s"
    %s
    $actionUri = $xenEnum
    %s 

    """ % (wsmanConn,vmuuid,endPointRef,drive)

    return psScript

def addDrive(driveType):

    if driveType == "DVD":
        resourceType = 16
        resourceSubType = "DVD"
    else:
        resourceType = 15
        resourceSubType = "CD"
 
    psScript = u"""
    $resourceType = %s
    $resourceSubType = "%s"
    # Add a Virtual CD / DVD ROM device to the VM in the state of <Empty>
    $parameters = @"
        <AddResourceSettings_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns:dsd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_DiskSettingData"
        xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService">
        <ResourceSettings>
            <dsd:Xen_DiskSettingData
            xmlns:dsd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_DiskSettingData"
            xsi:type="Xen_DiskSettingData_Type">
                <dsd:ElementName>MyCDRom</dsd:ElementName>
                <dsd:ResourceType>$resourceType</dsd:ResourceType>
                <dsd:ResourceSubType>$resourceSubType</dsd:ResourceSubType>
                <dsd:Bootable>true</dsd:Bootable>
                <dsd:Access>1</dsd:Access>
                <dsd:AddressOnParent>3</dsd:AddressOnParent>
            </dsd:Xen_DiskSettingData>
        </ResourceSettings>
        <AffectedConfiguration>
            <a:Address xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address>
            <a:ReferenceParameters
              xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
              xmlns:w="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
                <w:ResourceURI>http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem</w:ResourceURI>
                <w:SelectorSet>
                    <w:Selector Name="InstanceID">$vmInstanceId</w:Selector>
                </w:SelectorSet>
            </a:ReferenceParameters>
        </AffectedConfiguration>
        </AddResourceSettings_INPUT>
"@

    # $objSession.Get($actionURI)
    $output = [xml]$objSession.Invoke("AddResourceSettings", $actionURI, $parameters)

    """ % (resourceType,resourceSubType)
    
    return psScript

def snapshotWSMANVM(password = None,
                    hostIPAddr = None,
                    vmuuid = None,
                    snapshotName = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSystemSnapshotService")

    psScript = u"""
    %s
    %s
    $actionURI = $xenEnum
    $vmName = "%s"
    $snapshotName = "%s"

    $parameters = @"
    <CreateSnapshot_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns:vssd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemSettingData"
    xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemSnapshotService">
        <AffectedSystem>
            <a:Address xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address>
            <a:ReferenceParameters
            xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:w="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
                <w:ResourceURI>http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem</w:ResourceURI>
                <w:SelectorSet>
                    <w:Selector Name="Name">$vmName</w:Selector>
                    <w:Selector Name="CreationClassName">Xen_ComputerSystem</w:Selector>
                </w:SelectorSet>
            </a:ReferenceParameters>
        </AffectedSystem>
        <SnapshotSettings>
            <vssd:Xen_VirtualSystemSettingData xsi:type="Xen_VirtualSystemSettingData_Type">
                <vssd:ElementName>$snapshotName</vssd:ElementName>
                <vssd:Description>This is the description for this test snapshot</vssd:Description>
            </vssd:Xen_VirtualSystemSettingData>
        </SnapshotSettings>
    </CreateSnapshot_INPUT>
"@

    $snapshotResult= [xml]$objSession.Invoke("CreateSnapshot", $actionURI, $parameters)
    if ($snapshotResult -ne $NULL)
    {
        if ($snapshotResult.CreateSnapshot_OUTPUT.ReturnValue -ne 0)
        {
            # check for a job status of finished
            $jobPercentComplete = 0
            while ($jobPercentComplete -ne 100)
            {
                $jobResult = [xml]$objSession.Get($snapshotResult.CreateSnapshot_OUTPUT.Job.outerxml)
                $jobPercentComplete = $jobresult.Xen_VirtualSystemSnapshotServiceJob.PercentComplete
                $jobPercentComplete
                sleep 3
            }
        }

        $snapshot = [xml]$objSession.Get($snapshotResult.CreateSnapshot_OUTPUT.ResultingSnapshot.outerxml )
        $snapshot.Xen_ComputerSystemSnapshot.InstanceID
    }

    """ % (wsmanConn,endPointRef,vmuuid,snapshotName)

    return psScript

def applyWSMANSnapshot(password = None,
                       hostIPAddr = None,
                       snapshotID = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSystemSnapshotService")

    psScript = u"""
    %s
    %s
    $actionURI = $xenEnum
    $snapshotInstanceId = "%s"

    $parameters = @"
    <ApplySnapshot_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemSnapshotService">
    <Snapshot>
        <a:Address xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address>
        <a:ReferenceParameters xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:w="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
            <w:ResourceURI>http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_ComputerSystemSnapshot</w:ResourceURI>
            <w:SelectorSet>
                <w:Selector Name="InstanceID">$snapshotInstanceId</w:Selector>
            </w:SelectorSet>
        </a:ReferenceParameters>
    </Snapshot>
    </ApplySnapshot_INPUT>
"@

    # $objSession.Get($actionURI)
    $output = [xml]$objSession.Invoke("ApplySnapshot", $actionURI, $parameters)


    """ % (wsmanConn,endPointRef,snapshotID)

    return psScript

def destroyWSMANSnapshot(password = None,
                         hostIPAddr = None,
                         snapshotID = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSystemSnapshotService")

    psScript = u"""
    %s
    %s
    $actionURI = $xenEnum
    $snapshotInstanceId = "%s"

    $parameters = @"
    <DestroySnapshot_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemSnapshotService">
    <AffectedSnapshot>
        <a:Address xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address>
        <a:ReferenceParameters xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:w="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
            <w:ResourceURI>http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_ComputerSystemSnapshot</w:ResourceURI>
            <w:SelectorSet>
                <w:Selector Name="InstanceID">$snapshotInstanceId</w:Selector>
            </w:SelectorSet>
        </a:ReferenceParameters>
    </AffectedSnapshot>
    </DestroySnapshot_INPUT>
"@

    # $objSession.Get($actionURI)
    $output = [xml]$objSession.Invoke("DestroySnapshot", $actionURI, $parameters)

    """ % (wsmanConn,endPointRef,snapshotID)

    return psScript

def createWSMANVMFromSnapshot(password = None,
                              hostIPAddr = None,
                              snapshotID = None,
                              vmName = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSystemManagementService")

    storage = "%Local storage%"
    vm = '"' + "%" + "%s" % (vmName)+ "%" + '"'
    jobName = '"' + "%" + "$jobVmName" + "%" + '"'
    psScript = u"""

    %s
    $dialect = "http://schemas.microsoft.com/wbem/wsman/1/WQL"  # This is used for all WQL filters
    $filter1 = "SELECT * FROM Xen_StoragePool where Name like "
    $filter = $filter1 + '"' + "%s" + '"'
    $xenEnum = $objSession.Enumerate("http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePool", $filter, $dialect)
    $localSr = [xml]$xenEnum.ReadItem()

    $newVmName = "%s"
    $refVmInstanceId = "%s"
    $xenSrInstanceId = $localSr.Xen_StoragePool.InstanceID

    %s
    $actionUri = $xenEnum
    $parameters = @"
    <CopySystem_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService"
        xmlns:cssd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystemSettingData">
        <SystemSettings>
         <cssd:Xen_ComputerSystemSettingData
             xsi:type="Xen_ComputerSystemSettingData_Type">
              <cssd:Description>This is a script created system</cssd:Description>
              <cssd:ElementName>$newVmName</cssd:ElementName>
           </cssd:Xen_ComputerSystemSettingData>
        </SystemSettings>
        <ReferenceConfiguration xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
              <wsa:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:Address>
              <wsa:ReferenceParameters>
              <wsman:ResourceURI>http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystemTemplate</wsman:ResourceURI>
              <wsman:SelectorSet>
                    <wsman:Selector Name="InstanceID">$refVmInstanceId</wsman:Selector>
              </wsman:SelectorSet>
              </wsa:ReferenceParameters>
        </ReferenceConfiguration>
        <StoragePool xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
              <wsa:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:Address>
              <wsa:ReferenceParameters>
              <wsman:ResourceURI>http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePool</wsman:ResourceURI>
              <wsman:SelectorSet>
                    <wsman:Selector Name="InstanceID">$xenSrInstanceId</wsman:Selector>
              </wsman:SelectorSet>
              </wsa:ReferenceParameters>
        </StoragePool>
    </CopySystem_INPUT>
"@
    $output = [xml]$objSession.Invoke("CopySystem", $actionURI, $parameters)

    sleep 10

    $createVmResult = $output

    if ($createVmResult.CopySystem_OUTPUT.ReturnValue -ne 0) {
        # check for a job status of finished
        $jobPercentComplete = 0
        while ($jobPercentComplete -ne 100) {
            $jobResult = [xml]$objSession.Get($createVmResult.CopySystem_OUTPUT.Job.outerxml)
            $jobPercentComplete = $jobresult.Xen_VirtualSystemCreateJob.PercentComplete
            sleep 3
        }
        # query for the new VM
        $jobVmName = $jobresult.Xen_VirtualSystemCreateJob.ElementName
        $filter1 = "SELECT * FROM Xen_ComputerSystem where ElementName like "
        $filter = $filter1 + '"' + %s + '"'
        $xenEnum = $objSession.Enumerate("http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem", $filter, $dialect)
        $vm = [xml]$xenEnum.ReadItem()
        $vmUuid = $vm.Xen_ComputerSystem.Name
    } else {
        $filter1 = "SELECT * FROM Xen_ComputerSystem where ElementName like "
        $filter = $filter1 + '"' +%s + '"'
        $xenEnum = $objSession.Enumerate("http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem", $filter, $dialect)
        $vm = [xml]$xenEnum.ReadItem()
        $vmUuid = $vm.Xen_ComputerSystem.Name
    }
    $vmUuid

    """ % (wsmanConn,storage,vmName,snapshotID,endPointRef,jobName,vm)

    return psScript

def getWSMANVMSnapshotList(password = None,
                           hostIPAddr = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    enumClass = enumClassFilter("Xen_ComputerSystemSnapshot")

    psScript = u"""
    %s
    $filter = "SELECT * FROM Xen_ComputerSystemSnapshot"

    %s
    foreach ($element in $xenEnumXml) {
        $element.Xen_ComputerSystemSnapshot.InstanceID
    }
    """ % (wsmanConn,enumClass)

    return psScript

def modifyWSMANVdiProperties(password = None,
                             hostIPAddr = None,
                             vmuuid = None,
                             vdiNewSize = None,
                             vdiNewName = None,
                             vdiOldName = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    enumClass = enumClassFilter("Xen_DiskSettingData")
    str = '"' + "%" + "%s" % (vmuuid) + "%"+ '"'
    endPointRef = endPointReference("Xen_VirtualSystemManagementService")

    psScript = u"""
    %s
    $filter1 = "SELECT * FROM Xen_DiskSettingData where InstanceID like "
    $filter = $filter1 + '"' + %s + '"'
 
    %s
    $vdiName = "%s" 
    foreach ($element in $xenEnumXml) {
        if ($element.Xen_DiskSettingData.ElementName -eq $vdiName){
            $InstanceID = $element.Xen_DiskSettingData.InstanceID
            $HostResource = $element.Xen_DiskSettingData.HostResource
        }
    }
    $vdiNewName = "%s"
    $vdiNewSize = %s

    %s
    $actionUri = $xenEnum

    $parameters = @"
    <ModifyResourceSettings_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService">
    <ResourceSettings>
            <dsd:Xen_DiskSettingData
            xmlns:dsd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_DiskSettingData"
            xsi:type="Xen_DiskSettingData_Type">
            <dsd:ElementName>$vdiNewName</dsd:ElementName>
            <dsd:HostResource>$HostResource</dsd:HostResource>
            <dsd:VirtualQuantity>$vdiNewSize</dsd:VirtualQuantity>
            <dsd:AllocationUnits>byte</dsd:AllocationUnits>
            <dsd:ResourceType>19</dsd:ResourceType>
            <dsd:InstanceID>$InstanceID</dsd:InstanceID>
        </dsd:Xen_DiskSettingData>
    </ResourceSettings>
    </ModifyResourceSettings_INPUT>
"@

    $output = [xml]$objSession.Invoke("ModifyResourceSettings", $actionURI, $parameters)

    """ % (wsmanConn,str,enumClass,vdiOldName,vdiNewName,vdiNewSize,endPointRef)

    return psScript

def modifyWSMANVMSettings(password = None,
                          hostIPAddr = None,
                          InstanceID = None,
                          vmNewName = None,
                          vmNewDescription = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSystemManagementService")

    psScript = u"""
    %s
    %s
    $actionUri = $xenEnum

    $vmName = "%s"
    $InstanceID = "%s"
    $description = "%s"  

    $parameters = @"
    <ModifySystemSettings_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService"
    xmlns:cssd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystemSettingData">
    <SystemSettings>
            <cssd:Xen_ComputerSystemSettingData xsi:type="Xen_ComputerSystemSettingData_Type">
            <cssd:ElementName>$vmName</cssd:ElementName>
            <cssd:InstanceID>$InstanceID</cssd:InstanceID>
            <cssd:Description>$description</cssd:Description>
        </cssd:Xen_ComputerSystemSettingData>
    </SystemSettings>
    </ModifySystemSettings_INPUT>
"@

    $output = [xml]$objSession.Invoke("ModifySystemSettings", $actionURI, $parameters)

    """ %(wsmanConn,endPointRef,vmNewName,InstanceID,vmNewDescription)

    return psScript

def convertWSMANVMToTemplate(password = None,
                             hostIPAddr = None,
                             vmuuid = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSystemManagementService")

    psScript = u"""
    %s
    %s
    $actionUri = $xenEnum
    $vmName = "%s"
 
    $parameters = @"
        <ConvertToXenTemplate_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService">
        <System>
            <a:Address xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address>
            <a:ReferenceParameters
              xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
              xmlns:w="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
                <w:ResourceURI>http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem</w:ResourceURI>
                <w:SelectorSet>
                    <w:Selector Name="Name">$vmName</w:Selector>
                </w:SelectorSet>
            </a:ReferenceParameters>
        </System>
        </ConvertToXenTemplate_INPUT>
"@

        $output = [xml]$objSession.Invoke("ConvertToXenTemplate", $actionURI, $parameters)

    """ %(wsmanConn,endPointRef,vmuuid)

    return psScript

def createWSMANInternalNetwork(password = None,
                               hostIPAddr = None,
                               netName = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSwitchManagementService")

    psScript = u"""
    %s
    %s
    $actionURI = $xenEnum
    $netName = "%s"

    $parameters = @"
    <DefineSystem_INPUT
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xmlns:xsd="http://www.w3.org/2001/XMLSchema"
     xmlns:vssd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemSettingData"
     xmlns="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_VirtualSwitchManagementService">
        <SystemSettings>
            <vssd:Xen_VirtualSystemSettingData xsi:type="Xen_VirtualSystemSettingData_Type">
                <vssd:ElementName>$netName</vssd:ElementName>
                <vssd:Description>Internal network created by Powershell script</vssd:Description>
            </vssd:Xen_VirtualSystemSettingData>
        </SystemSettings>
    </DefineSystem_INPUT>
"@

    $output = [xml]$objSession.Invoke("DefineSystem", $actionURI, $parameters)
    $network = [xml]$objSession.Get($Output.DefineSystem_OUTPUT.ResultingSystem.outerxml)
    $network.Xen_VirtualSwitch.Name 
    """ %(wsmanConn,endPointRef,netName)

    return psScript

def createWSMANExternalNetwork(password = None,
                               hostIPAddr = None,
                               netName = None,
                               ethAdapter = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSwitchManagementService")

    psScript = u"""
    %s
    %s
    $actionURI = $xenEnum
    $netName = "%s"
    $ethAdapter = "%s"

    $parameters = @"
    <DefineSystem_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns:vssd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemSettingData"
    xmlns:npsd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_NetworkPortSettingData"
    xmlns="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_VirtualSwitchManagementService">
        <SystemSettings>
            <vssd:Xen_VirtualSystemSettingData xsi:type="Xen_VirtualSystemSettingData_Type">
                <vssd:ElementName>$netName</vssd:ElementName>
                <vssd:Description>External network created by Powershell script</vssd:Description>
            </vssd:Xen_VirtualSystemSettingData>
        </SystemSettings>
        <ResourceSettings>
            <npsd:Xen_NetworkPortSettingData
            xmlns:npsd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_NetworkPortSettingData"
            xsi:type="Xen_HostNetworkPortSettingData_Type">
                <npsd:Connection>$ethAdapter</npsd:Connection>
                <npsd:ResourceType>33</npsd:ResourceType>
                <npsd:VlanTag>9</npsd:VlanTag>
            </npsd:Xen_NetworkPortSettingData>
        </ResourceSettings>
    </DefineSystem_INPUT>
"@
    # $ethAdapter is a simple string such as "eth0" or "eth1"
    # <npsd:VlanTag></npsd:VlanTag> - sending a VlanTag is recommended however not required.  The tag must not be blank.
    $output = [xml]$objSession.Invoke("DefineSystem", $actionURI, $parameters)
    $network = [xml]$objSession.Get($Output.DefineSystem_OUTPUT.ResultingSystem.outerxml)
    $network.Xen_VirtualSwitch.Name 
    """ %(wsmanConn,endPointRef,netName,ethAdapter)

    return psScript

def createWSMANBondedNetwork(password = None,
                             hostIPAddr = None,
                             netName = None,
                             ethAdapter = None,
                             ethAdapter2 = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSwitchManagementService")

    psScript = u"""
    %s
    %s
    $actionURI = $xenEnum
    $netName = "%s"
    $ethAdapter = "%s"
    $ethAdapter2 = "%s"

    $parameters = @"
    <DefineSystem_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns:vssd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemSettingData"
    xmlns:npsd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_NetworkPortSettingData"
    xmlns="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_VirtualSwitchManagementService">
        <SystemSettings>
            <vssd:Xen_VirtualSystemSettingData xsi:type="Xen_VirtualSystemSettingData_Type">
                <vssd:ElementName>$netName</vssd:ElementName>
                <vssd:Description>External network created by the test script</vssd:Description>
            </vssd:Xen_VirtualSystemSettingData>
        </SystemSettings>
        <ResourceSettings>
            <npsd:Xen_NetworkPortSettingData
            xmlns:npsd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_NetworkPortSettingData"
            xsi:type="Xen_HostNetworkPortSettingData_Type">
                <npsd:Connection>$ethAdapter</npsd:Connection>
                <npsd:Connection>$ethAdapter2</npsd:Connection>
            </npsd:Xen_NetworkPortSettingData>
        </ResourceSettings>
    </DefineSystem_INPUT>
"@

    # $ethAdapter is a simple string such as "eth0" or "eth1"
    # <npsd:VlanTag></npsd:VlanTag> - sending a VlanTag is recommended however not required.  The tag must not be blank.
    $output = [xml]$objSession.Invoke("DefineSystem", $actionURI, $parameters)

    """ %(wsmanConn,endPointRef,netName,ethAdapter,ethAdapter2)

    return psScript

def addWSMANNicToNetwork(password = None,
                         hostIPAddr = None,
                         vSwitchName = None,
                         ethAdapter = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSwitchManagementService")

    psScript = u"""
    %s
    %s
    $actionURI = $xenEnum
    $vSwitchName = "%s" 
    $ethAdapter = "%s"

    $parameters = @"
    <AddResourceSettings_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns:npsd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_NetworkPortSettingData"
    xmlns="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_VirtualSwitchManagementService">
        <AffectedConfiguration>
            <a:Address xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address>
            <a:ReferenceParameters
            xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:w="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
                <w:ResourceURI>http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_VirtualSwitchSettingData</w:ResourceURI>
                <w:SelectorSet>
                    <w:Selector Name="InstanceID">Xen:$vSwitchName</w:Selector>
                </w:SelectorSet>
            </a:ReferenceParameters>
        </AffectedConfiguration>
        <ResourceSettings>
            <npsd:Xen_NetworkPortSettingData
            xmlns:npsd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_NetworkPortSettingData"
            xsi:type="Xen_HostNetworkPortSettingData_Type">
                <npsd:Connection>$ethAdapter</npsd:Connection>
                <npsd:VlanTag>99</npsd:VlanTag>
            </npsd:Xen_NetworkPortSettingData>
        </ResourceSettings>
    </AddResourceSettings_INPUT>
"@

    # $objSession.Get($actionURI)
    $output = [xml]$objSession.Invoke("AddResourceSettings", $actionURI, $parameters)

    """ %(wsmanConn,endPointRef,vSwitchName,ethAdapter)

    return psScript

def removeWSMANNicFromNetwork(password = None,
                              hostIPAddr = None,
                              vSwitchName = None,
                              ethAdapter = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSwitchManagementService")
    str = '"' + "%" + "%s" % (vSwitchName) + "%"+ '"'
    enumVmData = enumClassFilter("Xen_HostNetworkPortSettingData")
 
    psScript = u"""
    %s
    %s
    $actionURI = $xenEnum
    $ethAdapter = "%s"

    $filter1 = "SELECT * FROM Xen_HostNetworkPortSettingData where VirtualSwitch like "
    $filter = $filter1 + '"' + %s + '"'
    %s
    $hostNetPortsd = $xenEnumXml

    foreach ($element in $hostNetPortsd) {
        $nic = $element
        if ($nic.Xen_HostNetworkPortSettingData.Connection -like "$ethAdapter") {
        $hostNetPort = $nic.Xen_HostNetworkPortSettingData.InstanceID
        }
    

    $parameters = @"
    <RemoveResourceSettings_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns:hnpsd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_HostNetworkPortSettingData"
    xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSwitchManagementService">
        <ResourceSettings>
            <hnpsd:Xen_HostNetworkPortSettingData
            xmlns:npsd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_HostNetworkPortSettingData"
            xsi:type="Xen_HostNetworkPortSettingData_Type">
                <hnpsd:InstanceID>$hostNetPort</hnpsd:InstanceID>
            </hnpsd:Xen_HostNetworkPortSettingData>
        </ResourceSettings>
    </RemoveResourceSettings_INPUT>
"@

    # $objSession.Get($actionURI)
    $output = [xml]$objSession.Invoke("RemoveResourceSettings", $actionURI, $parameters)
    }
    """ % (wsmanConn,endPointRef,ethAdapter,str,enumVmData)

    return psScript

def attachWSMANVMToNetwork(password = None,
                           hostIPAddr = None,
                           vmuuid = None,
                           vSwitchName = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSystemManagementService")

    psScript = u"""
    %s
    %s
    $actionURI = $xenEnum
    $vSwitchName = "%s"
    $vmName = "%s"

    $parameters = @"
    <AddResourceSetting_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns:npsd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_NetworkPortSettingData"
    xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService">
        <AffectedSystem>
            <a:Address xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address>
            <a:ReferenceParameters
            xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:w="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
                <w:ResourceURI>http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem</w:ResourceURI>
                <w:SelectorSet>
                    <w:Selector Name="Name">$vmName</w:Selector>
                    <w:Selector Name="CreationClassName">Xen_ComputerSystem</w:Selector>
                </w:SelectorSet>
            </a:ReferenceParameters>
        </AffectedSystem>
        <ResourceSetting>
            <npsd:Xen_NetworkPortSettingData
            xmlns:npsd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_NetworkPortSettingData"
            xsi:type="Xen_NetworkPortSettingData_Type">
                <npsd:PoolID>$vSwitchName</npsd:PoolID>
                <npsd:ResourceType>33</npsd:ResourceType>
            </npsd:Xen_NetworkPortSettingData>
        </ResourceSetting>
    </AddResourceSetting_INPUT>
"@

    # $objSession.Get($actionURI)
    $output = [xml]$objSession.Invoke("AddResourceSetting", $actionURI, $parameters)

    """ % (wsmanConn,endPointRef,vSwitchName,vmuuid)

    return psScript

def dettachWSMANVMFromNetwork(password = None,
                              hostIPAddr = None,
                              vifInstanceID = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSystemManagementService")

    psScript = u"""
    %s
    %s
    $actionURI = $xenEnum
    $vifInstanceId = "%s"

    $parameters = @"
    <RemoveResourceSettings_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns:npsd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_NetworkPortSettingData"
    xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService">
        <ResourceSettings>
            <npsd:Xen_NetworkPortSettingData
            xmlns:npsd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_NetworkPortSettingData"
            xsi:type="Xen_NetworkPortSettingData_Type">
                <npsd:InstanceID>$vifInstanceId</npsd:InstanceID>
                <npsd:ResourceType>33</npsd:ResourceType>
            </npsd:Xen_NetworkPortSettingData>
        </ResourceSettings>
    </RemoveResourceSettings_INPUT>
"@

    $output = [xml]$objSession.Invoke("RemoveResourceSettings", $actionURI, $parameters)
   
    """ % (wsmanConn,endPointRef,vifInstanceID)

    return psScript

def destroyWSMANetwork(password = None,
                       hostIPAddr = None,
                       netName = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSwitchManagementService")

    psScript = u"""
    %s
    %s
    $actionURI = $xenEnum
    $xenNetName = "%s"

    $parameters = @"
    <DestroySystem_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSwitchManagementService">
        <AffectedSystem xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
          <wsa:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:Address>
          <wsa:ReferenceParameters>
          <wsman:ResourceURI>http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSwitch</wsman:ResourceURI>
          <wsman:SelectorSet>
                <wsman:Selector Name="Name">$xenNetName</wsman:Selector>
                <wsman:Selector Name="CreationClassName">Xen_VirtualSwitch</wsman:Selector>
          </wsman:SelectorSet>
          </wsa:ReferenceParameters>
        </AffectedSystem>
    </DestroySystem_INPUT>
"@

    # $objSession.Get($actionURI)
    $output = [xml]$objSession.Invoke("DestroySystem", $actionURI, $parameters)

    """ % (wsmanConn,endPointRef,netName)

    return psScript

def writeXmlToFile():
    psScript = u"""
    function WriteXmlToFile($xml)
    {
        $StringWriter = New-Object System.IO.StringWriter
        $XmlWriter = New-Object System.XMl.XmlTextWriter $StringWriter
        $xmlWriter.Formatting = "indented"
        $xml.WriteTo($XmlWriter)
        Write-Output $StringWriter.ToString()
    }
    """
    return psScript

def startExportWithStaticIP(start_ip,end_ip,mask,gateway):
    psScript = u"""
    @"
    <StartSnapshotForestExport_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemSnapshotService">
        <NetworkConfiguration>%s</NetworkConfiguration>
        <NetworkConfiguration>%s</NetworkConfiguration>
        <NetworkConfiguration>%s</NetworkConfiguration>
        <NetworkConfiguration>%s</NetworkConfiguration>
        <System>
            <a:Address xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address>
            <a:ReferenceParameters
            xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:w="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
                <w:ResourceURI>http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem</w:ResourceURI>
                <w:SelectorSet>
                    <w:Selector Name="Name">$vmName</w:Selector>
                    <w:Selector Name="CreationClassName">Xen_ComputerSystem</w:Selector>
                </w:SelectorSet>
            </a:ReferenceParameters>
        </System>
    </StartSnapshotForestExport_INPUT>
"@
    """ % (start_ip,end_ip,mask,gateway)
    return psScript

def startExportWithoutStaticIP():
    psScript = u"""
    @"
    <StartSnapshotForestExport_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemSnapshotService">
        <System>
            <a:Address xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address>
            <a:ReferenceParameters
            xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:w="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
                <w:ResourceURI>http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem</w:ResourceURI>
                <w:SelectorSet>
                    <w:Selector Name="Name">$vmName</w:Selector>
                    <w:Selector Name="CreationClassName">Xen_ComputerSystem</w:Selector>
                </w:SelectorSet>
            </a:ReferenceParameters>
        </System>
    </StartSnapshotForestExport_INPUT>
"@
    """
    return psScript

def exportWSMANSnapshotTree(password = None,
                            hostIPAddr = None,
                            vmuuid = None,
                            driveName = None,
                            start_ip = None,
                            end_ip = None,
                            mask = None,
                            gateway = None,):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSystemSnapshotService")
    writexmlToFile = writeXmlToFile()
    if start_ip:
        log("Static IP configuration we got is %s %s %s %s" % (str(start_ip),str(end_ip),str(mask),str(gateway)))
        startSnapahotForestExport = startExportWithStaticIP(start_ip,end_ip,mask,gateway)
    else:
        startSnapahotForestExport = startExportWithoutStaticIP()
    
    psScript = u"""
    %s
    %s
    %s
    $actionURI = $xenEnum
    # Log the actionURI for Xen_VirtualSystemSnapshotService into file exportWSMANScriptsOutput.txt
    "actionURI for Xen_VirtualSystemSnapshotService :" | Out-File "c:\exportWSMANScriptsOutput.txt" -Append
    $timestamp = Get-Date -Format o
    $timestamp | Out-File "c:\exportWSMANScriptsOutput.txt" -Append
    $scriptOutput = [xml]$actionURI
    WriteXmlToFile $scriptOutput | Out-File "c:\exportWSMANScriptsOutput.txt" -Append

    $vmName = "%s"
    Import-Module BitsTransfer
    $downloadPath = "%s"
    $exportOutput = $downloadPath + "exportSnapshotTree.txt"

    # Start the Export
    $parameters = %s

    $startExport = $objSession.Invoke("StartSnapshotForestExport", $actionURI, $parameters)
    $timestamp = Get-Date -Format o
    "StartSnapshotForestExport" | Out-File $exportOutput
    $startExport | Out-File $exportOutput -Append
    $startExport = [xml]$startExport
    # Log the Cim call response for StartSnapshotForestExport into file exportWSMANScriptsOutput.txt
    "Cim call response for StartSnapshotForestExport :" | Out-File "c:\exportWSMANScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\exportWSMANScriptsOutput.txt" -Append
    WriteXmlToFile $startExport | Out-File "c:\exportWSMANScriptsOutput.txt" -Append

    # Check for Job Status
    if ($startExport.StartSnapshotForestExport_OUTPUT.ReturnValue -ne 0) {
        $jobResult = [xml]$objSession.Get($startExport.StartSnapshotForestExport_OUTPUT.job.outerxml)
        if ($jobresult.Xen_StartSnapshotForestExportJob.PercentComplete -ne 100) {
            $jobPercentComplete = $jobresult.Xen_StartSnapshotForestExportJob.PercentComplete
            while ($jobPercentComplete -ne 100) {
                $jobResult = [xml]$objSession.Get($startExport.StartSnapshotForestExport_OUTPUT.job.outerxml)
                $jobPercentComplete = $jobresult.Xen_StartSnapshotForestExportJob.PercentComplete
                sleep 3
            }
        }
    }
    else {
        $jobResult = $objSession.Get($startExport.StartSnapshotForestExport_OUTPUT.job.outerxml)
        "StartExport Job Result" | Out-File $exportOutput -Append
        $jobResult | Out-File $exportOutput -Append
        $jobResult = [xml]$jobResult
    }
    $timestamp = Get-Date -Format o
    # Log the Job Status for StartSnapshotForestExport into file exportWSMANScriptsOutput.txt
    "Job Status for StartSnapshotForestExport :" | Out-File "c:\exportWSMANScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\exportWSMANScriptsOutput.txt" -Append
    WriteXmlToFile $jobResult | Out-File "c:\exportWSMANScriptsOutput.txt" -Append

    $connectionHandle = $jobResult.Xen_StartSnapshotForestExportJob.ExportConnectionHandle
    $metadataUri = $jobResult.Xen_StartSnapshotForestExportJob.MetadataURI

    if ($jobResult.Xen_StartSnapshotForestExportJob.DiskImageURIs -eq $null) {
        "No URI's were returned, go look" | Out-File $exportOutput -Append
        sleep 10 
    }
    # Download the Metadata file (this is an HTTP file download)
    $downloadClient = New-Object System.Net.WebClient
    $result = $downloadClient.DownloadFile($metadataUri,($downloadPath + "export.xva"))
    $timestamp = Get-Date -Format o
    # Log the metadata file download result into file exportWSMANScriptsOutput.txt
    "Check the metadata file download is done" | Out-File "c:\exportWSMANScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\exportWSMANScriptsOutput.txt" -Append
    $result | Out-File "c:\exportWSMANScriptsOutput.txt" -Append

    # Capture the virtual disk image URIs to pass to BITS
    $vDisksToDownload = @()
    $vDisksToDownload = $jobResult.Xen_StartSnapshotForestExportJob.DiskImageURIs
    $timestamp = Get-Date -Format o
    "The URIs for the disks that will be downloaded" | Out-File $exportOutput -Append
    $vDisksToDownload | Out-File $exportOutput -Append
    # Log the URIs for the disks that will be downloaded into file exportWSMANScriptsOutput.txt
    "The URIs for the disks that will be downloaded" | Out-File "c:\exportWSMANScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\exportWSMANScriptsOutput.txt" -Append
    $vDisksToDownload | Out-File "c:\exportWSMANScriptsOutput.txt" -Append

    # download each disk one at a time
    foreach ($element in $vDisksToDownload) {
        $file = $element.Split('/')
        $file = $file[($file.length - 1)]
        $destination = $downloadPath + $file

        $transferJob = Start-BitsTransfer -Source $element -destination $destination -DisplayName SnapshotDiskExport -asynchronous
        $timestamp = Get-Date -Format o
        # Log the transferJob status for BitsTransfer into file exportWSMANScriptsOutput.txt
        "Transfer job status for BitsTransfer of disks" | Out-File "c:\exportWSMANScriptsOutput.txt" -Append
        $timestamp | Out-File "c:\exportWSMANScriptsOutput.txt" -Append
        $transferJob | Out-File "c:\exportWSMANScriptsOutput.txt" -Append
        "-Source $element -destination $destination" | Out-File $exportOutput -Append

        while (($transferJob.JobState -eq "Transferring") -or ($transferJob.JobState -eq "Connecting"))
            { sleep 5 }

            switch($transferJob.JobState)
            {
                "Connecting" { Write-Host " Connecting " }
                "Transferring" { Write-Host "$transferJob.JobId has progressed to " + ((($transferJob.BytesTransferred / 1Mb) / ($transferJob.BytesTotal / 1Mb)) * 100) + " Percent Complete"}
                "Transferred" {Complete-BitsTransfer -BitsJob $transferJob}
                "Error" {
                    $transferJob | Format-List | Out-File $exportOutput -Append
                    "BITS Error Condition: " + $transferJob.ErrorCondition | Out-File $exportOutput -Append
                    "BITS Error Description: " + $transferJob.ErrorDescription | Out-File $exportOutput -Append
                    "BITS Error Context: " + $transferJob.ErrorContext | Out-File $exportOutput -Append
                    "BITS Error Context Description: " + $transferJob.ErrorContextDescription | Out-File $exportOutput -Append
                    sleep 10
                    Remove-BitsTransfer $transferJob
                    }
                "TransientError" {
                    $transferJob | Format-List | Out-File $exportOutput -Append
                    sleep 10
                    # Resume-BitsTransfer $element # This should attempt a resume-bitstransfer but that is currently not supported with the TransferVM.
                    Remove-BitsTransfer $transferJob
                    }
            }
            $timestamp = Get-Date -Format o
            # Log the transferJob status for BitsTransfer after completion into file exportWSMANScriptsOutput.txt
            "Transfer job status for BitsTransfer of disks after completion" | Out-File "c:\exportWSMANScriptsOutput.txt" -Append
            $timestamp | Out-File "c:\exportWSMANScriptsOutput.txt" -Append
            $transferJob | Out-File "c:\exportWSMANScriptsOutput.txt" -Append
    }

    # End the entire process to tear down the Transfer VM
    $parameters = @"
    <EndSnapshotForestExport_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemSnapshotService">
                <ExportConnectionHandle>$connectionHandle</ExportConnectionHandle>
    </EndSnapshotForestExport_INPUT>
"@

    # $objSession.Get($actionURI)
    $endExport = $objSession.Invoke("EndSnapshotForestExport", $actionURI, $parameters)
    $timestamp = Get-Date -Format o
    $endExport | Out-File $exportOutput -Append
    $endExport = [xml]$endExport
    # Log the Cim call response for EndSnapshotForestExport into file exportWSMANScriptsOutput.txt
    "Cim call response for EndSnapshotForestExport :" | Out-File "c:\exportWSMANScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\exportWSMANScriptsOutput.txt" -Append
    WriteXmlToFile $endExport | Out-File "c:\exportWSMANScriptsOutput.txt" -Append

    # Check for Job Status
    if ($endExport.EndSnapshotForestExport_OUTPUT.ReturnValue -ne 0) {
    $jobPercentComplete = 0
    while ($jobPercentComplete -ne 100) {
        $jobResult = [xml]$objSession.Get($endExport.EndSnapshotForestExport_OUTPUT.job.outerxml)
        $jobPercentComplete = $jobresult.Xen_EndSnapshotForestExportJob.PercentComplete
        sleep 3
        }
    }
    $timestamp = Get-Date -Format o
    # Log the jobResult for EndSnapshotForestExport into file exportWSMANScriptsOutput.txt
    "jobResult for EndSnapshotForestExport" | Out-File "c:\exportWSMANScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\exportWSMANScriptsOutput.txt" -Append
    WriteXmlToFile $jobResult | Out-File "c:\exportWSMANScriptsOutput.txt" -Append

    """ % (writexmlToFile,wsmanConn,endPointRef,vmuuid,driveName,startSnapahotForestExport)

    return psScript

def importWSMANSnapshotTree(password = None,
                            hostIPAddr = None,
                            driveName = None,
                            transProtocol = None,
                            ssl = None,
                            static_ip = None,
                            mask = None,
                            gateway = None):

    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSystemSnapshotService")
    storage = "%Local storage%"
    connToDiskImage = connectToDiskImageWithStaticIP(transProtocol,ssl,static_ip,mask,gateway)
    disconFromDiskImage = disconnectFromDiskImage("$connectionHandle")
    vdiCreate = createVDI()
    writexmlToFile = writeXmlToFile()
    vdiName = "vdi_importSnapshotTree"

    psScript = u"""
    %s
    %s

    Import-Module BitsTransfer

    $downloadPath = "%s"
    $importOutput = $downloadPath + "importSnapshotTree.txt"

    $dialect = "http://schemas.microsoft.com/wbem/wsman/1/WQL"  # This is used for all WQL filters
    $filter1 = "SELECT * FROM Xen_StoragePool where Name like "
    $filter = $filter1 + '"' + "%s" + '"'
    $xenEnum = $objSession.Enumerate("http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_StoragePool", $filter, $dialect)
    $timestamp = Get-Date -Format o
    # Log the Response from WQL filters for storage into importWSMANScriptsOutput.txt
    "Response from WQL filters for storage" | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    $xenEnum | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    $localSr = [xml]$xenEnum.ReadItem()

    $vdiName = "%s"
    $srPoolId = $localSr.Xen_StoragePool.PoolID
    $vdiMb = 10







    $importFiles = Get-ChildItem $downloadPath
    $timestamp = Get-Date -Format o
    # Log the Files which are going to be downloaded into importWSMANScriptsOutput.txt
    "Files which are going to be downloaded" | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    $importFiles | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    "0 - The items found in the import folder" | Out-File $importOutput   # note -append nor -noclobber is used, thus the file is reset
    $importFiles | Out-File -append $importOutput

    foreach ($element in $importFiles) {
        if ($element.Extension -like ".xva") {
            # Create a VDI
            %s
            $createMetadataVdi = $createVdiResult 
            $metadataVdi = $objSession.Get($createMetadataVdi.CreateDiskImage_OUTPUT.ResultingDiskImage.outerxml)
            $timestamp = Get-Date -Format o
            $metadataVdi | Out-File -append $importOutput
            $metaDataVdi = [xml]$metaDataVdi
            # Log the metadataVdis details into importWSMANScriptsOutput.txt
            "Get the metadataVdi details" | Out-File "c:\importWSMANScriptsOutput.txt" -Append
            $timestamp | Out-File "c:\importWSMANScriptsOutput.txt" -Append
            WriteXmlToFile $metaDataVdi | Out-File "c:\importWSMANScriptsOutput.txt" -Append
            $vdi = $metaDataVdi
            # Copy the export.xva to the VDI endpoint
            %s
            $transferVm = $jobResult
#           $transferVm = ConnectToDiskImage $metadataVdi "bits" "0"
            $source =  $downloadPath + $element.Name
            # This is a RAW file copy using BITS as the transport
            $transferJob = Start-BitsTransfer -Source $source -destination $transferVm.Xen_ConnectToDiskImageJob.TargetURI -DisplayName ImportSnapshotTreeMetadataUpload -TransferType Upload -Asynchronous
            $timestamp = Get-Date -Format o
            "-Source " + $source + " -destination " + $transferVm.Xen_ConnectToDiskImageJob.TargetURI | Out-File -append $importOutput
            
            # Log the Cim call response on RAW file copy using BITS into importWSMANScriptsOutput.txt
            "Cim call response on RAW file copy using BITS" | Out-File "c:\importWSMANScriptsOutput.txt" -Append
            $timestamp | Out-File "c:\importWSMANScriptsOutput.txt" -Append
            $transferJob | Out-File "c:\importWSMANScriptsOutput.txt" -Append

            while (($transferJob.JobState -eq "Transferring") -or ($transferJob.JobState -eq "Connecting"))
                { sleep 5 }

            switch($transferJob.JobState)
            {
                "Connecting" { Write-Host " Connecting " }
                "Transferring" { Write-Host "$transferJob.JobId has progressed to " + ((($transferJob.BytesTransferred / 1Mb) / ($transferJob.BytesTotal / 1Mb)) * 100) + " Percent Complete" }
                "Transferred" {Complete-BitsTransfer -BitsJob $transferJob}
                "Error" {
                    $transferJob | Format-List | Out-File -append $importOutput
                    "BITS Error Condition: " + $transferJob.ErrorCondition | Out-File -append $importOutput
                    "BITS Error Description: " + $transferJob.ErrorDescription | Out-File -append $importOutput
                    "BITS Error Context: " + $transferJob.ErrorContext | Out-File -append $importOutput
                    "BITS Error Context Description: " + $transferJob.ErrorContextDescription | Out-File -append $importOutput
                    sleep 10
                    Remove-BitsTransfer $transferJob
                    }
                "TransientError" {
                    $transferJob | Format-List | Out-File -append $importOutput
                    sleep 10
                    # Resume-BitsTransfer $transferJob # This should attempt a resume-bitstransfer but that is currently not supported with the TransferVM.
                    Remove-BitsTransfer $transferJob
                    }
            }
            $timestamp = Get-Date -Format o
            # Log the Transfer Job Status for RAW file into importWSMANScriptsOutput.txt
            "Transfer Job Status for RAW file" | Out-File "c:\importWSMANScriptsOutput.txt" -Append
            $timestamp | Out-File "c:\importWSMANScriptsOutput.txt" -Append
            $transferJob | Out-File "c:\importWSMANScriptsOutput.txt" -Append
            
            $connectionHandle = $transferVm.Xen_ConnectToDiskImageJob.ConnectionHandle
            %s
            $metadataVdiDisconnect = $output
#            $metadataVdiDisconnect = DisconnectFromDiskImage $transferVm.Xen_ConnectToDiskImageJob.ConnectionHandle
            $jobPercentComplete = 0
            while ($jobPercentComplete -ne 100) {
                $jobResult = [xml]$objSession.Get($metadataVdiDisconnect.DisconnectFromDiskImage_OUTPUT.Job.outerxml)
                $jobPercentComplete = $jobresult.Xen_DisconnectFromDiskImageJob.PercentComplete
                sleep 10
            }
            $timestamp = Get-Date -Format o
            # Log the jobResult for DisconnectFromDiskImage into importWSMANScriptsOutput.txt
            "jobResult for DisconnectFromDiskImage" | Out-File "c:\importWSMANScriptsOutput.txt" -Append
            $timestamp | Out-File "c:\importWSMANScriptsOutput.txt" -Append
            WriteXmlToFile $jobResult | Out-File "c:\importWSMANScriptsOutput.txt" -Append
        }
    }

    # Parse out $metadataVdi
    $DeviceIDSnapshotTree = $metadataVdi.Xen_DiskImage.DeviceID
    $CreationClassNameSnapshotTree = $metadataVdi.Xen_DiskImage.CreationClassName
    $SystemCreationClassNameSnapshotTree = $metadataVdi.Xen_DiskImage.SystemCreationClassName
    $SystemNameSnapshotTree = $metadataVdi.Xen_DiskImage.SystemName

    %s
    $actURI = $xenEnum
    $timestamp = Get-Date -Format o
    # Log the actionURI for endpoint reference into importWSMANScriptsOutput.txt
    "actionURI for endpoint reference" | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    $actURI | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    

    $parameters = @"
    <PrepareSnapshotForestImport_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemSnapshotService">
        <MetadataDiskImage
        xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
        xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
            <wsa:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:Address>
            <wsa:ReferenceParameters>
            <wsman:ResourceURI>http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_DiskImage</wsman:ResourceURI>
            <wsman:SelectorSet>
                    <wsman:Selector Name="DeviceID">$DeviceIDSnapshotTree</wsman:Selector>
                    <wsman:Selector Name="CreationClassName">$CreationClassNameSnapshotTree</wsman:Selector>
                    <wsman:Selector Name="SystemCreationClassName">$SystemCreationClassNameSnapshotTree</wsman:Selector>
                    <wsman:Selector Name="SystemName">$SystemNameSnapshotTree</wsman:Selector>
            </wsman:SelectorSet>
            </wsa:ReferenceParameters>
        </MetadataDiskImage>
    </PrepareSnapshotForestImport_INPUT>
"@

    $prepareImport = $objSession.Invoke("PrepareSnapshotForestImport", $actURI, $parameters)
    $timestamp = Get-Date -Format o
    "PrepareImport" | Out-File -append $importOutput
    $prepareImport  | Out-File -append $importOutput
    $prepareImport = [xml]$prepareImport
    # Log the Cim call response for PrepareSnapshotForestImport into importWSMANScriptsOutput.txt
    "Cim call response for PrepareSnapshotForestImport" | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    WriteXmlToFile $prepareImport | Out-File "c:\importWSMANScriptsOutput.txt" -Append

    # Start the Import
    $importContext = $prepareImport.PrepareSnapshotForestImport_OUTPUT.ImportContext
    $InstanceID = $localSr.Xen_StoragePool.InstanceID

    # Set the namespace once before entering the loop
    $namespace = @{n1="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemSnapshotService"}

    # The big loop needs to begin here and needs to Loop Until ImportContext is missing
    do {
        # This parameter needs to be set each time because $diskImageMap and $importContext need to be fed back in for processing
        $parameters = @"
        <CreateNextDiskInImportSequence_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemSnapshotService">
            <StoragePool>
                <a:Address xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address>
                <a:ReferenceParameters xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:w="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
                    <w:ResourceURI>http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_StoragePool</w:ResourceURI>
                    <w:SelectorSet>
                        <w:Selector Name="InstanceID">$InstanceID</w:Selector>
                    </w:SelectorSet>
                </a:ReferenceParameters>
            </StoragePool>
            <ImportContext>
                $importContext
            </ImportContext>
            <DiskImageMap>
                $diskImageMap
            </DiskImageMap>
        </CreateNextDiskInImportSequence_INPUT>
"@

        $diskImport = $objSession.Invoke("CreateNextDiskInImportSequence", $actURI, $parameters)
        $timestamp = Get-Date -Format o
        "DiskImport" | Out-File -append $importOutput
        $diskImport  | Out-File -append $importOutput
        $diskImport = [xml]$diskImport
        # Log the Cim call response for CreateNextDiskInImportSequence into importWSMANScriptsOutput.txt
        "Cim call response for CreateNextDiskInImportSequence" | Out-File "c:\importWSMANScriptsOutput.txt" -Append
        $timestamp | Out-File "c:\importWSMANScriptsOutput.txt" -Append
        WriteXmlToFile $diskImport | Out-File "c:\importWSMANScriptsOutput.txt" -Append

    #    $diskImport.CreateNextDiskInImportSequence_OUTPUT

        $diskToImport = $diskImport.CreateNextDiskInImportSequence_OUTPUT.OldDiskID
        $importContext = $diskImport.CreateNextDiskInImportSequence_OUTPUT.ImportContext
        $diskImageMap = $diskImport.CreateNextDiskInImportSequence_OUTPUT.DiskImageMap

        # little loop above until the parameter OldDiskID is returned if OldDiskID is present then go below
        if ((Select-Xml -Xml $diskImport -Xpath "//n1:OldDiskID" -Namespace $namespace) -ne $null) {
            foreach ($element in $importFiles) {
                if ($element.Name -match $diskToImport) {

                    $newVdi = $objSession.Get($diskImport.CreateNextDiskInImportSequence_OUTPUT.NewDiskImage.outerxml)
                    $timestamp = Get-Date -Format o
                    "DiskImportNewVdi" | Out-File -append $importOutput
                    $newVdi  | Out-File -append $importOutput
                    $newVdi = [xml]$newVdi
                    $vdi = $newVdi
                    # Log the vdi information to be import into importWSMANScriptsOutput.txt
                    "vdi information to be import" | Out-File "c:\importWSMANScriptsOutput.txt" -Append
                    $timestamp | Out-File "c:\importWSMANScriptsOutput.txt" -Append
                    WriteXmlToFile $vdi | Out-File "c:\importWSMANScriptsOutput.txt" -Append
                    %s
                    $transferVM = $jobResult
#                    $transferVm = ConnectToDiskImage $newVdi "bits" "0"
                    "DiskImportTransferVm" | Out-File -append $importOutput
                    $transferVm  | Out-File -append $importOutput

                    $source =  $downloadPath + $element.Name
                    $destination = $transferVm.Xen_ConnectToDiskImageJob.TargetURI + ".vhd"
                    "-Source $source"  | Out-File -append $importOutput
                    "-Destination $destination"  | Out-File -append $importOutput


                    $transferJob = Start-BitsTransfer -Source $source -destination $destination -DisplayName ImportSnapshotVirtualDiskUpload -TransferType Upload -Asynchronous
                    $timestamp = Get-Date -Format o
                    "DiskImportTransferJob" | Out-File -append $importOutput
                    $transferJob  | Out-File -append $importOutput
                    # Log the transferJob for ImportSnapshotVirtualDiskUpload into importWSMANScriptsOutput.txt
                    "transferJob for ImportSnapshotVirtualDiskUpload" | Out-File "c:\importWSMANScriptsOutput.txt" -Append
                    $timestamp | Out-File "c:\importWSMANScriptsOutput.txt" -Append
                    $transferJob | Out-File "c:\importWSMANScriptsOutput.txt" -Append

                    while (($transferJob.JobState -eq "Transferring") -or ($transferJob.JobState -eq "Connecting"))
                        { sleep 5 }

                    switch($transferJob.JobState)
                    {
                        "Connecting" { Write-Host " Connecting " }
                        "Transferring" { Write-Host "$element.JobId has progressed to " + ((($transferJob.BytesTransferred / 1Mb) / ($transferJob.BytesTotal / 1Mb)) * 100) + " Percent Complete" }
                        "Transferred" {Complete-BitsTransfer -BitsJob $transferJob}
                        "Error" {
                            $transferJob | Format-List | Out-File -append $importOutput
                            "BITS Error Condition: " + $transferJob.ErrorCondition | Out-File -append $importOutput
                            "BITS Error Description: " + $transferJob.ErrorDescription | Out-File -append $importOutput
                            "BITS Error Context: " + $transferJob.ErrorContext | Out-File -append $importOutput
                            "BITS Error Context Description: " + $transferJob.ErrorContextDescription | Out-File -append $importOutput
                            sleep 10 
                            Remove-BitsTransfer $transferJob
                            }
                        "TransientError" {
                            $transferJob | Format-List | Out-File -append $importOutput
                            sleep 10
                            # Resume-BitsTransfer $transferJob # This should attempt a resume-bitstransfer but that is currently not supported with the TransferVM.
                            Remove-BitsTransfer $transferJob
                            }
                    }
                    $timestamp = Get-Date -Format o
                    # Log the transferJob status for ImportSnapshotVirtualDiskUpload into importWSMANScriptsOutput.txt
                    "transferJob status for ImportSnapshotVirtualDiskUpload" | Out-File "c:\importWSMANScriptsOutput.txt" -Append
                    $timestamp | Out-File "c:\importWSMANScriptsOutput.txt" -Append
                    $transferJob | Out-File "c:\importWSMANScriptsOutput.txt" -Append
                    $connectionHandle = $transferVm.Xen_ConnectToDiskImageJob.ConnectionHandle
                    %s
                    $uploadVdiDisconnect = $output 
#                    $uploadVdiDisconnect = DisconnectFromDiskImage $transferVm.Xen_ConnectToDiskImageJob.ConnectionHandle
                    $jobPercentComplete = 0
                    while ($jobPercentComplete -ne 100) {
                        $jobResult = [xml]$objSession.Get($uploadVdiDisconnect.DisconnectFromDiskImage_OUTPUT.Job.outerxml)
                        $jobPercentComplete = $jobresult.Xen_DisconnectFromDiskImageJob.PercentComplete
                        sleep 3
                    }
                    $timestamp = Get-Date -Format o
                    # Log the jobResult for DisconnectFromDiskImage into importWSMANScriptsOutput.txt
                    "jobResult for DisconnectFromDiskImage" | Out-File "c:\importWSMANScriptsOutput.txt" -Append
                    $timestamp | Out-File "c:\importWSMANScriptsOutput.txt" -Append
                    $jobResult | Out-File "c:\importWSMANScriptsOutput.txt" -Append
                }
            }
        }

    } until ((Select-Xml -Xml $diskImport -Xpath "//n1:ImportContext" -Namespace $namespace) -eq $null)

    # When the loop is complete, finalize the import here.
    $parameters = @"
    <FinalizeSnapshotForestImport_INPUT
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemSnapshotService">
        <StoragePool>
            <a:Address xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address>
            <a:ReferenceParameters xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:w="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
                <w:ResourceURI>http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_StoragePool</w:ResourceURI>
                <w:SelectorSet>
                    <w:Selector Name="InstanceID">$InstanceID</w:Selector>
                </w:SelectorSet>
            </a:ReferenceParameters>
        </StoragePool>
        <MetadataDiskImage
        xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
        xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
            <wsa:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:Address>
            <wsa:ReferenceParameters>
            <wsman:ResourceURI>http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_DiskImage</wsman:ResourceURI>
            <wsman:SelectorSet>
                    <wsman:Selector Name="DeviceID">$DeviceIDSnapshotTree</wsman:Selector>
                    <wsman:Selector Name="CreationClassName">$CreationClassNameSnapshotTree</wsman:Selector>
                    <wsman:Selector Name="SystemCreationClassName">$SystemCreationClassNameSnapshotTree</wsman:Selector>
                    <wsman:Selector Name="SystemName">$SystemNameSnapshotTree</wsman:Selector>
            </wsman:SelectorSet>
            </wsa:ReferenceParameters>
        </MetadataDiskImage>
        <DiskImageMap>
            $diskImageMap
        </DiskImageMap>
    </FinalizeSnapshotForestImport_INPUT>
"@

    $importFinalize = $objSession.Invoke("FinalizeSnapshotForestImport", $actURI, $parameters)
    $timestamp = Get-Date -Format o
    "ImportFinalize" | Out-File -append $importOutput
    $importFinalize  | Out-File -append $importOutput
    $importFinalize = [xml]$importFinalize
    # Log the Cim call response for FinalizeSnapshotForestImport into importWSMANScriptsOutput.txt
    "Cim call response for FinalizeSnapshotForestImport" | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    WriteXmlToFile $importFinalize | Out-File "c:\importWSMANScriptsOutput.txt" -Append

    # Get the imported VM back to pass back out
    $vmImportResult = [xml]$objSession.Get($importFinalize.FinalizeSnapshotForestImport_OUTPUT.VirtualSystem.outerxml)
    $timestamp = Get-Date -Format o
    "VmImportResult" | Out-File -append $importOutput
    $vmImportResult  | Out-File -append $importOutput
    # Log the ImportVM details into importWSMANScriptsOutput.txt
    "ImportVM details" | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    $timestamp | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    WriteXmlToFile $vmImportResult | Out-File "c:\importWSMANScriptsOutput.txt" -Append
    $vmImportResult.Xen_ComputerSystem.Name

    """ % (writexmlToFile,wsmanConn,driveName,storage,vdiName,vdiCreate,connToDiskImage,disconFromDiskImage,endPointRef,connToDiskImage,disconFromDiskImage)

    return psScript

def addWSMANGuestKvp(hostIPAddr, password, key, value, guestUUID):
    wsmanConn = wsmanConnection(password, hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSystemManagementService")

    psScript = u"""
    %s
    %s
    $actionURI = $xenEnum

    $parameters = @"
        <AddResourceSettings_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns:dsd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_KVP"
        xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService">
        <ResourceSettings>
            <dsd:Xen_KVP
            xmlns:dsd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_KVP"
            xsi:type="Xen_KVP_Type">
                <dsd:key>%s</dsd:key>
                <dsd:value>%s</dsd:value>                
            </dsd:Xen_KVP>
        </ResourceSettings>
        <AffectedConfiguration>
            <a:Address xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address>
            <a:ReferenceParameters
              xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
              xmlns:w="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
                <w:ResourceURI>http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem</w:ResourceURI>
                <w:SelectorSet>
                    <w:Selector Name="InstanceID">Xen:%s</w:Selector>
                </w:SelectorSet>
            </a:ReferenceParameters>
        </AffectedConfiguration>
        </AddResourceSettings_INPUT>
"@

    $startTime = get-date
    $output = [xml]$objSession.Invoke("AddResourceSettings", $actionURI, $parameters)
    $endTime = get-date
    $duration = $endTime.Subtract($startTime).seconds
    write "Duration:$duration"
    $returncode = $output.AddResourceSettings_OUTPUT.ReturnValue
    write "Return-Code:$returncode"
    """ % (wsmanConn, endPointRef, key, value, guestUUID)

    return psScript

def getAllWSMANGuestKvps(hostIPAddr, password, guestUUID):
    wsmanConn = wsmanConnection(password, hostIPAddr)
    psScript = u"""
    %s

    $cimUri = "http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/" + "Xen_KVP"

    $f1 = "SELECT * FROM Xen_KVP where Vm_uuid = "
    $filter = $f1 + '"' + "%s" + '"'
    # Perform the enumeration against the given CIM class
    $xenEnum = $objSession.Enumerate($cimUri, $filter, "http://schemas.microsoft.com/wbem/wsman/1/WQL")

    $kvps = "{"
    # Read out each returned element as a member of the array
    while (!$xenEnum.AtEndOfStream) {
        $element = [xml]$xenEnum.ReadItem()
        $kvps += "'" + $element.Xen_KVP.Key + "':('" + $element.Xen_KVP.DeviceID + "','" + $element.Xen_KVP.Value + "'),"
    }
    $kvps += "}"
    write $kvps
    """ % (wsmanConn, guestUUID)

    return psScript

def getWSMANGuestKvpByDeviceID(hostIPAddr, password, deviceId):
    wsmanConn = wsmanConnection(password, hostIPAddr)
    psScript = u"""
    %s

    $cimUri = "http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/" + "Xen_KVP"

    $f1 = "SELECT * FROM Xen_KVP where DeviceID = "
    $filter = $f1 + '"' + "%s" + '"'
    # Perform the enumeration against the given CIM class
    $xenEnum = $objSession.Enumerate($cimUri, $filter, "http://schemas.microsoft.com/wbem/wsman/1/WQL")

    $kvps = "{"
    # Read out each returned element as a member of the array
    while (!$xenEnum.AtEndOfStream) {
        $element = [xml]$xenEnum.ReadItem()
        $kvps += "'" + $element.Xen_KVP.Key + "':('" + $element.Xen_KVP.DeviceID + "','" + $element.Xen_KVP.Value + "'),"
    }
    $kvps += "}"
    write $kvps
    """ % (wsmanConn, deviceId)

    return psScript


def removeWSMANGuestKvpUsingDeviceID(hostIPAddr, password, deviceId):
    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSystemManagementService")

    psScript = u"""
    %s
    %s
    $actionURI = $xenEnum

    $parameters = @"
    <RemoveResourceSettings_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns:dsd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_KVP"
        xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService">
        <ResourceSettings>
            <dsd:Xen_KVP
            xmlns:dsd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_KVP"
            xsi:type="Xen_KVP_Type">
                <dsd:DeviceID>%s</dsd:DeviceID>
            </dsd:Xen_KVP>
        </ResourceSettings>
    </RemoveResourceSettings_INPUT>
"@

    $startTime = get-date
    $output = [xml]$objSession.Invoke("RemoveResourceSettings", $actionURI, $parameters)
    $endTime = get-date
    $duration = $endTime.Subtract($startTime).seconds
    write "Duration:$duration"
    $returncode = $output.RemoveResourceSettings_OUTPUT.ReturnValue
    write "Return-Code:$returncode"
    """ % (wsmanConn, endPointRef, deviceId)

    return psScript

def removeWSMANGuestKvpUsingKeyDevId(hostIPAddr, password, key, deviceId):
    wsmanConn = wsmanConnection(password,hostIPAddr)
    endPointRef = endPointReference("Xen_VirtualSystemManagementService")

    psScript = u"""
    %s
    %s
    $actionURI = $xenEnum

    $parameters = @"
    <RemoveResourceSettings_INPUT
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns:dsd="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_KVP"
        xmlns="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_VirtualSystemManagementService">
        <ResourceSettings>
            <dsd:Xen_KVP
            xmlns:dsd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/Xen_KVP"
            xsi:type="Xen_KVP_Type">
                <dsd:key>%s</dsd:key>
                <dsd:DeviceID>%s</dsd:DeviceID>
            </dsd:Xen_KVP>
        </ResourceSettings>
    </RemoveResourceSettings_INPUT>
"@

    $startTime = get-date
    $output = [xml]$objSession.Invoke("RemoveResourceSettings", $actionURI, $parameters)
    $endTime = get-date
    $duration = $endTime.Subtract($startTime).seconds
    write "Duration:$duration"
    $returncode = $output.RemoveResourceSettings_OUTPUT.ReturnValue
    write "Return-Code:$returncode"
    """ % (wsmanConn, endPointRef, key, deviceId)

    return psScript

def setupKvpChannel(hostIPAddr, password, guestUUID):
    wsmanConn = wsmanConnection(password,hostIPAddr)
    
    psScript = u"""
    %s
    $actionUri = "http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem?CreationClassName=Xen_ComputerSystem+Name=%s"

    $parameters = @"
        <SetupKVPCommunication_INPUT 
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" 
            xmlns:xsd="http://www.w3.org/2001/XMLSchema" 
            xmlns ="http://schemas.citrix.com/wbem/wscim/1/cim-schema/2/Xen_ComputerSystem">
        </SetupKVPCommunication_INPUT>
"@

    write $output.SetupKVPCommunication_OUTPUT.ReturnValue
    $startTime = get-date
    $output = [xml]$objSession.Invoke("SetupKVPCommunication", $actionURI, $parameters)
    $endTime = get-date
    $duration = $endTime.Subtract($startTime).seconds
    write "Duration:$duration"
    $returncode = $output.SetupKVPCommunication_OUTPUT.ReturnValue
    write "Return-Code:$returncode"
    """ % (wsmanConn, guestUUID)

    return psScript


