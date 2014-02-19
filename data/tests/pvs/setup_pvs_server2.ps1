#
# Created: 2012-DEC
# This script processes the remaining clients

# Variables
#switch zone check off (don't prompt me to run when an msi is executed)
$env:SEE_MASK_NOZONECHECKS = 1
$global:autoDir     = $env:SystemDrive + "\pvs"
$global:logDir      = $global:autoDir + "\logs"
$global:paramFile   = $global:autoDir + "\parameters.txt"
$base               = [system.io.path]::GetFilenameWithoutExtension($MyInvocation.InvocationName)
$global:messagesLog = $global:logDir + "\" + $base + ".log"
$global:thisFile    = $MyInvocation.MyCommand.Name
$global:sharedFunc  = $global:autoDir + "\shared_functions.ps1"
$VerbosePreference  = "Continue" # set this to get all "Write-Verbose" and all "Log-MessageVerbose" calls to execute.
#$ErrorActionPreference="Stop"    # set this to "Stop" script on errors, such as those generated from cmdlets
#$DebugPreference = "Continue"

# Import the modules your environment needs 
. $global:sharedFunc


#--------------------------------------------------------------------------------------------------------------------
#--------------------------------------------------------------------------------------------------------------------
#--------------------------------------------------------------------------------------------------------------------
Start-Log
$message = "-----=====START SCRIPT=====-----"
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
 
# By now, the First device client (vDiskMaster) should have been completed doing all its stuff.
Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
$message = "STEP: First device client (vDiskMaster) should have been completed doing all its stuff. Now, setting the remaining clients..."
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile

# go get the number of total 'additional' devices from parameters files
$additionalDevices = Get-Parameter -configFile $global:paramFile -section "General" -key "deviceCount"

# confirm number of additional devices is 1 or greater
if( !($additionalDevices -ge 1) )
{
    $message = "Error. Device count expected to be greater than or equal to 1."
    Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    throw $message
}

# re-use vDiskName
$vDiskName      = Get-Parameter -configFile $global:paramFile -section "PVS Device1" -key "devicevDiskName"
$writeCacheSize = Get-Parameter -configFile $global:paramFile -section "PVS Device1" -key "writeCacheSize"
$siteName  = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "siteName"
$storeName = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "storeName"
$deviceNumber = 2 # Must start at 2, since vDiskMaster is considered to be device1.

Log-MessageVerbose -message "EXECUTE: Load-PVSMcliPSSnapin" -logFile $global:messagesLog -thisfile $global:thisFile
Load-PVSMcliPSSnapin

for ($loop = 1; $loop -le $additionalDevices; $loop++)
{
    # get several parameters for the current device in this iteration
    $sectionName   = "PVS Device$deviceNumber"
    $deviceName    = Get-Parameter -configFile $global:paramFile -section $sectionName -key "deviceName"
    $deviceMAC     = Get-Parameter -configFile $global:paramFile -section $sectionName -key "deviceMAC"
    $writeCacheType= Get-Parameter -configFile $global:paramFile -section $sectionName -key "writeCacheType"
    $bootFrom      = Get-Parameter -configFile $global:paramFile -section $sectionName -key "bootFrom"

    # set write cache type
    Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
    $message = "STEP: Set-WriteCacheType for [$sectionName]..."
    Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    $message = "EXECUTE: Set-WriteCacheType -writeCacheType $writeCacheType -vDiskName $vDiskName -sectionName $sectionName -siteName $siteName -storeName $storeName -writecachesize $writecachesize"
    Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    Set-WriteCacheType -writeCacheType $writeCacheType -vDiskName $vDiskName -sectionName $sectionName -siteName $siteName -storeName $storeName -writecachesize $writecachesize

    # create pvs device
    Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
    $message = "STEP: Create-PVSDevice for [$sectionName]..."
    Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    $message = "EXECUTE: Create-PVSDevice -deviceName $deviceName -MACaddress $deviceMAC -sectionName $sectionName"
    Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    Create-PVSDevice -deviceName $deviceName -MACaddress $deviceMAC -sectionName $sectionName

    # assign disk to device
    Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
    $message = "STEP: Assign-PVSDisk2Device for [$sectionName]..."
    Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    $message = "EXECUTE: Assign-PVSDisk2Device -deviceName $deviceName -vDiskName $vDiskName -sectionName $sectionName"
    Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    Assign-PVSDisk2Device -deviceName $deviceName -vDiskName $vDiskName -sectionName $sectionName
    
    # set device boot from
    Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
    $message = "STEP: Set-PVSDeviceBootFrom for [$sectionName]..."
    Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    $message = "EXECUTE: Set-PVSDeviceBootFrom -deviceName $deviceName -bootFrom $bootFrom -sectionName $sectionName"
    Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    Set-PVSDeviceBootFrom -deviceName $deviceName -bootFrom $bootFrom -sectionName $sectionName
    $deviceNumber++
}

$message = "Setting remaining clients completed...."
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
Set-Parameter -configFile $global:paramFile -section "Server Status" -key "SetRemainingDevices" -newValue "1"


# Log script end
$message = "-----=====END SCRIPT=====-----"
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile

