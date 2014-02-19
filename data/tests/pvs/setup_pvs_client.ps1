#
# Created: 2012-DEC
# This script does the following:
#   - on the first run of script; it will install pvs device software
#   - on the second run of script; it will execute p2pvs.exe

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

# verify number of script parameters passed in
$argCount = $args.Count
if(1 -ne $argCount)
{
    $message = "Expecting deviceID as a single parameter. Actual number of parameters passed in was [$argCount]."
    Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    Log-Message -message "Exiting script..." -logFile $global:messagesLog -thisfile $global:thisFile
    exit
}

$deviceID = $args[0]
Log-Message -message "deviceID passed in = [$deviceID]." -logFile $global:messagesLog -thisfile $global:thisFile

# build sectionName string using deviceID passed in
$sectionName = "PVS Device$deviceID" 

# check if PVS Device software has been installed
$installPVSDevice = Get-Parameter -configFile $global:paramFile -section $sectionName -key "Install-PVSDevice"
if ("-1" -eq $installPVSDevice)
{
    # do this only if pvs device software is Not already installed
    Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
    $message = "STEP: Getting Machine Information..."
    Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    Collect-MachineInfo -sectionName $sectionName


    #*--- STEP: Disable firewall...
    #Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
    #$message = "STEP: Disable firewall..."
    #Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    #Set-FirewallMode -mode "disable" -sectionName $sectionName


    #*--- STEP: Installing Signing Certificates...
    Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
    $message = "STEP: Installing Signing Certificates..."
    Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    Install-SigningCerts -sectionName $sectionName


    #*--- STEP: Install-PVSDevice...
    Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
    $message = "STEP: Install-PVSDevice..."
    Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    Install-PVSDevice -sectionName $sectionName
    
    # At this point in time this script will write (via Install-PVSDevice function) to parameters file 
    # status that it has completed installing pvs device software
    # at that point in time xenrt will know to reboot this VM
    # then restart this script so that it can complete the second part (run p2pvs.exe)
    # Log script end
    $message = "-----=====END SCRIPT=====-----"
    Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    exit
}
else
{
    $message = "PVS device software may already be installed; skipping installation."
    Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
}

# xenrt will eventually reboot this VM and automatically
# restart this script.
# this script will pick up where it left off
# lets make sure p2pvs.exe has not already been called previously
$buildPVSVdiskP2PVS = Get-Parameter -configFile $global:paramFile -section $sectionName -key "Build-PVSVdiskP2PVS"
if("-1" -eq $buildPVSVdiskP2PVS)
{
    # CALL P2PVS.EXE now
    Log-Message -message "`n`n" -logFile $global:messagesLog -thisfile $global:thisFile
    $message = "STEP: Build-PVSVdiskP2PVS (p2pvs.exe)..."
    Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    Build-PVSVdiskP2PVS -sectionName $sectionName
}
else
{
    $message = "Build-PVSVdiskP2PVS (p2pvs.exe) may have already been executed; skipping execution."
    Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
}

# Log script end
$message = "-----=====END SCRIPT=====-----"
Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile

