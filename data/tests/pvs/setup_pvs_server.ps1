#
# Created: 2012-DEC
# This script does the following:
#   install dot net4 (if already installed, then skips)
#   install sql2008x (if already installed, then skips)
#   install signing certificates
#   install citrix license server
#   setup license files (and restart license service)
#   install powershell snapins (several)
#   install PVS
#   install PVS console
#   create Database
#   configure PVS Server
#   Create-PVSVdisk
#   Create-PVSDevice
#   Assign-PVSDisk2Device
#   Set-PVSDeviceBootFrom
#   Set-WriteCacheType
#   Wait for client
#   Then process remaining clients

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
#Log script start
$message = "-----=====START SCRIPT=====-----"
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
$sectionName = "Server Status"


$message = "STEP: Getting Machine Information..."
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
Collect-MachineInfo -sectionName $sectionName


#*--- STEP: Installing .Net4
#Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
#$message = "STEP: Installing .Net4 ..."
#Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
#Install-DotNet4 -sectionName $sectionName


#*--- STEP: Installing SQL2008x...
#Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
#$message = "STEP: Installing SQL2008x..."
#Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
#Install-MSSQL2008express -sectionName $sectionName


#*--- STEP: Installing Signing Certificates...
Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
$message = "STEP: Installing Signing Certificates..."
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
Install-SigningCerts -sectionName $sectionName


#*--- STEP: Installing License Server...
#Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
#$message = "STEP: Installing License Server..."
#Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
#Install-CTXLicenseServer -sectionName $sectionName


#*--- STEP: Setup License Files...
#Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
#$message = "STEP: Setup License Files..."
#Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
#Setup-License -sectionName $sectionName


#*--- STEP: INSTALL XD Host PowerShell Snapin ---
Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
$message = "STEP: INSTALL XD Host PowerShell Snapin..."
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
Install-XDHostPSSnapin -sectionName $sectionName


#*--- STEP: Installing XD Broker PowerShell Snapin ---
Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
$message = "STEP: Installing XD Broker PowerShell Snapin ..."
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
Install-XDBrokerPSSnapin -sectionName $sectionName


#*--- STEP: Installing Configuration PowerShell Snapin ---
Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
$message = "STEP: Installing Configuration PowerShell Snapin ..."
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
Install-ConfigPSSnapin -sectionName $sectionName


#*--- STEP: Installing ConfigurationLogging PowerShell Snapin
Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
$message = "STEP: Installing ConfigurationLogging PowerShell Snapin ..."
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
Install-ConfigurationLoggingPSSnapin -sectionName $sectionName

	
#*--- STEP: Installing DelagatedAdmin PowerShell Snapin
Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
$message = "STEP: Installing DelagatedAdmin PowerShell Snapin ..."
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
Install-DelagatedAdminPSSnapin -sectionName $sectionName


#*--- STEP: Installing PVS Server
Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
$message = "STEP: Installing PVS Server..."
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
Install-PVSServer -sectionName $sectionName


#*--- STEP: Installing PVS Console
Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
$message = "STEP: Installing PVS Console..."
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
Install-PVSConsole -sectionName $sectionName


#*--- STEP: Disable firewall...
#Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
#$message = "STEP: Disable firewall..."
#Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
#Set-FirewallMode -mode "disable" -sectionName $sectionName


#*--- STEP: Creating PVS Database...
Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
$message = "STEP: Creating PVS Database..."
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
Create-PVSDatabase -sectionName $sectionName


#*--- STEP: Configure PVS Server...
Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
$message = "STEP: Configure PVS Server..."
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
Configure-PVSServer -sectionName $sectionName


#*--- STEP: Create-PVSVdisk...
Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
$message = "STEP: Create-PVSVdisk1..."
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
$vDiskName     = Get-Parameter -configFile $global:paramFile -section "PVS Device1" -key "devicevDiskName"
$vDiskSizeInMB = Get-Parameter -configFile $global:paramFile -section "PVS Device1" -key "devicevDiskSizeInMB"
$pvsStoreName  = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "storeName"
$pvsSiteName   = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "siteName"
Create-PVSVdisk -vDiskName $vDiskName -pvsStoreName $pvsStoreName -pvsSiteName $pvsSiteName -vDiskSizeInMB $vDiskSizeInMB -sectionName $sectionName


# This is vDiskMaster device
$sectionName = "PVS Device1"
#*--- STEP: Create-PVSDevice...
Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
$message = "STEP: Create-PVSDevice..."
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
$device1Name = Get-Parameter -configFile $global:paramFile -section $sectionName -key "deviceName"
$device1MAC  = Get-Parameter -configFile $global:paramFile -section $sectionName -key "deviceMAC"
Create-PVSDevice -deviceName $device1Name -MACaddress $device1MAC -sectionName $sectionName


#*--- STEP: Assign-PVSDisk2Device...
Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
$message = "STEP: Assign-PVSDisk2Device..."
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
Assign-PVSDisk2Device -deviceName $device1Name -vDiskName $vDiskName -sectionName $sectionName


#*--- STEP: Set-PVSDeviceBootFrom...
Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
$message = "STEP: Set-PVSDeviceBootFrom..."
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
$bootFrom = Get-Parameter -configFile $global:paramFile -section $sectionName -key "bootFrom"
Set-PVSDeviceBootFrom -deviceName $device1Name -bootFrom $bootFrom -sectionName $sectionName


#*--- STEP: Set-WriteCacheType to private mode...
Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
$message = "STEP: Set-WriteCacheType to private mode..."
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
$writeCacheType = Get-Parameter -configFile $global:paramFile -section $sectionName -key "writeCacheType"
$writeCacheSize = Get-Parameter -configFile $global:paramFile -section $sectionName -key "writeCacheSize"
Set-WriteCacheType -writeCacheType $writeCacheType -vDiskName $vDiskName -sectionName $sectionName -siteName $pvsSiteName -storeName $pvsStoreName -writecachesize $writeCacheSize


# Log script end
$message = "-----=====END SCRIPT=====-----"
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile

