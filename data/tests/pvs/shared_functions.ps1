
<#
.SYNOPSIS
 	Logs message to console AND to logfile.
.PARAMETER message
	Actual message that gets written. 
.PARAMETER logFile
	Logfile where output gets written to.
.PARAMETER thisFile	
	Name of this script file that is currently executing.
#>
function Log-Message([Parameter(Position=0,Mandatory=$true)] [string]$message,
                     [Parameter(Position=1,Mandatory=$true)] [string]$logFile,
                     [Parameter(Position=2,Mandatory=$true)] [string]$thisFile)
{
    # create logfile if it does not exist.
    if (!(Test-Path $logFile))
    {
        $timestamp = Get-Date -Format s
        $msg =  $timestamp + " - File I/O Error with [$logFile]. Now attempting to create it..."
        Write-Output  $msg
        Write-Verbose $msg
        Write-Host    $msg
        
        New-Item $logFile -type file -force

        $timestamp = Get-Date -Format s
        if (!(Test-Path $logFile))
        {
            $msg = $timestamp + " - Unable to create file [$logFile]."
            Write-Output  $msg
            Write-Verbose $msg
            Write-Host    $msg
            throw $msg
        }
        else
        {
            $msg =  $timestamp + " - Successfully created file [$logFile]."
            Write-Output  $msg
            Write-Verbose $msg
            Write-Host    $msg
            Write-Output  $msg | Out-File -FilePath $logFile -Append
        }
    }
    
    $timestamp = Get-Date -Format s
    $line = $timestamp + " " + $thisFile + " - " + $message
    Write-Host $line
    Write-Output $line | Out-File -FilePath $logFile -Append
}


<#
.SYNOPSIS
 	If Verbose is enabled, logs message to console AND to logfile.
.PARAMETER message
	Actual message that gets written. 
.PARAMETER logFile
	Logfile where output gets written to.
.PARAMETER thisFile	
	Name of this script file that is currently executing.
#>
function Log-MessageVerbose([Parameter(Position=0,Mandatory=$true)] [string]$message,
                            [Parameter(Position=1,Mandatory=$true)] [string]$logFile,
                            [Parameter(Position=2,Mandatory=$true)] [string]$thisFile)
{
    if ("Continue" -eq $VerbosePreference)
    {
        Log-Message -message $message -logFile $logFile -thisFile $thisFile
    }
}


<#
.SYNOPSIS
    Returns true if 64bit Operating System
#>
function Is-64bit()
{
	if( Test-Path -Path "${env:ProgramFiles} (x86)" -ErrorAction SilentlyContinue)
    { return $true}
	else 
    { return $false}

	## Note: this WMI call returns null for the OS architecture on XP but
    ## we only test on 32-bit for XP.  So this works.
    #if ((Get-WmiObject win32_operatingsystem).OSArchitecture -eq "64-bit") 
    #{
    #    return $true
    #} 	
}


<#
.SYNOPSIS
    Starts a log file.
#>
function Start-Log()
{
    # Notes:
    # 1. Regarding $global:logDir directory: if it does not exist, this function will attempt create it.
    # 2. Regarding $global:messagesLog file: this function assumes the files directory path has already been created.    
    #    If the actual messageLog (file) does not exist, the file will get created (by LogMessage function).    
    
	if (! (Test-Path $global:logDir)) 
	{
        $timestamp = Get-Date -Format s
        $message =  $timestamp + " - Making dir [$global:logDir]"
        Write-Output  $message
        Write-Verbose $message
        Write-Host    $message 
		md $global:logDir        
        
        if (! (Test-Path $global:logDir))
        {
            $timestamp = Get-Date -Format s        
            $message =  $timestamp + " - Failed to create dir [$global:logDir]"
            Write-Output  $message
            Write-Verbose $message
            Write-Host    $message 
            throw $message
        }
        else
        {
            Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        }
	}

 	Log-Message -message "START LOG." -logFile $global:messagesLog -thisfile $global:thisFile 
 }


<#
.SYNOPSIS
 	Install SQL Server 2008. 
.PARAMETER SqlLocation
	Path to the root folder of SQL 2008x setup.exe file. 
.PARAMETER DBAdminUser
	User Name for SQL admin account
.PARAMETER DBAdminPassword	
	Password for SQL admin account
.PARAMETER sectionName
	Specifies to which Section status should get written to.
.PARAMETER configIniPath	
	Path to configuration ini file for SQL installation.
.PARAMETER DBInstance	
	DB Instance name.
.PARAMETER configIniDir	
	Directory where configuration ini file resides.
#>
function ExecuteInstall-SQL2008x(
			[Parameter(Mandatory=$true)] [string] $SqlLocation= "\\ftlengnas03.eng.citrite.net\Apps$\Microsoft\SQL\EN\2008_R2\Enterprise\Image",
			[Parameter(Mandatory=$true)] [string] $DBAdminUser,
			[Parameter(Mandatory=$true)] [string] $DBAdminPassword,
            [Parameter(Mandatory=$true)] [string] $sectionName,
			[Parameter(Mandatory=$false)] [string]$configIniPath=$null,
			[Parameter(Mandatory=$false)] [string]$DBInstance= "SQLEXPRESS",
			[Parameter(Mandatory=$false)] [string]$configIniDir="c:")
{
	$functionName = "ExecuteInstall-SQL2008x"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	#switch zone check off (don't prompt me to run when an msi is executed)
	$env:SEE_MASK_NOZONECHECKS = 1

	$drive = $SqlLocation		
	if ([string]::IsNullOrEmpty($configIniPath))
	{
		#default to using configuration file in same folder as this script
		# NamedInstance: SQLEXPRESS
		$configINI =
@"
;SQLSERVER2008 Configuration File
[SQLSERVER2008]

; Specify the Instance ID for the SQL Server features you have specified. SQL Server directory structure, registry structure, and service names will reflect the instance ID of the SQL Server instance. 

INSTANCEID= "$DBInstance"

; Specifies a Setup work flow, like INSTALL, UNINSTALL, or UPGRADE. This is a required parameter. 

ACTION= "Install"

; Specifies features to install, uninstall, or upgrade. The list of top-level features include SQL, AS, RS, IS, and Tools. The SQL feature will install the database engine, replication, and full-text. The Tools feature will install Management Tools, Books online, Business Intelligence Development Studio, and other shared components. 
; SQLENGINE - Installs only the Database Engine.
; FULLTEXT - Installs the FullText component along with Database Engine.
; SSMS - Management Tools – Basic
; ADV_SSMS - Management Tools – Complete

FEATURES=SQLENGINE,FULLTEXT,SSMS,ADV_SSMS
; FEATURES=SQLENGINE,RS,BIDS,CONN,BC,SDK,BOL,SSMS,ADV_SSMS,SNAC_SDK

; Displays the command line parameters usage 

HELP= "False"

; Specifies that the detailed Setup log should be piped to the console. 

INDICATEPROGRESS= "False"

; Setup will not display any user interface. 

QUIET= "False"

; Setup will display progress only without any user interaction. 

QUIETSIMPLE= "True"

; Specifies that Setup should install into WOW64. This command line argument is not supported on an IA64 or a 32-bit system. 

X86= "False"

; Detailed help for command line argument ENU has not been defined yet. 

ENU= "True"

; Parameter that controls the user interface behavior. Valid values are Normal for the full UI, and AutoAdvance for a simplied UI. 

; UIMODE= "Normal"

; Specify if errors can be reported to Microsoft to improve future SQL Server releases. Specify 1 or True to enable and 0 or False to disable this feature. 

ERRORREPORTING= "False"

; Specify the root installation directory for native shared components. 

INSTALLSHAREDDIR= "${env:ProgramFiles}\Microsoft SQL Server"

; Specify the installation directory. 

INSTANCEDIR= "${env:ProgramFiles}\Microsoft SQL Server"

; Specify that SQL Server feature usage data can be collected and sent to Microsoft. Specify 1 or True to enable and 0 or False to disable this feature. 

SQMREPORTING= "False"

; Specify a default or named instance. MSSQLSERVER is the default instance for non-Express editions and SQLExpress for Express editions. This parameter is required when installing the SQL Server Database Engine (SQL), Analysis Services (AS), or Reporting Services (RS). 

INSTANCENAME= "$DBInstance"

; Agent account name 

AGTSVCACCOUNT= "$DBAdminUser"
AGTSVCPASSWORD= "$DBAdminPassword"
;AGTSVCACCOUNT= "NT AUTHORITY\NetworkService"

; Auto-start service after installation.  

AGTSVCSTARTUPTYPE= "Manual"

; Startup type for Integration Services. 

ISSVCSTARTUPTYPE= "Automatic"

; Account for Integration Services: Domain\User or system account. 

ISSVCACCOUNT= "NT AUTHORITY\NetworkService"

; Controls the service startup type setting after the service has been created. 

ASSVCSTARTUPTYPE= "Automatic"

; The collation to be used by Analysis Services. 

ASCOLLATION= "Latin1_General_CI_AS"

; The location for the Analysis Services data files. 

ASDATADIR= "Data"

; The location for the Analysis Services log files. 

ASLOGDIR= "Log"

; The location for the Analysis Services backup files. 

ASBACKUPDIR= "Backup"

; The location for the Analysis Services temporary files. 

ASTEMPDIR= "Temp"

; The location for the Analysis Services configuration files. 

ASCONFIGDIR= "Config"

; Specifies whether or not the MSOLAP provider is allowed to run in process. 

ASPROVIDERMSOLAP= "1"

; A port number used to connect to the SharePoint Central Administration web application. 

FARMADMINPORT= "0"

; Startup type for the SQL Server service. 

SQLSVCSTARTUPTYPE= "Automatic"

; Level to enable FILESTREAM feature at (0, 1, 2 or 3). 

FILESTREAMLEVEL= "0"

; Set to "1" to enable RANU for SQL Server Express. 

ENABLERANU= "False"

; Specifies a Windows collation or an SQL collation to use for the Database Engine. 

SQLCOLLATION= "SQL_Latin1_General_CP1_CI_AS"
; SQLCOLLATION= "SQL_Latin1_General_CI_AS_KS"

; Account for SQL Server service: Domain\User or system account. 

SQLSVCACCOUNT= "$DBAdminUser"
SQLSVCPASSWORD= "$DBAdminPassword"
;SQLSVCACCOUNT= "NT AUTHORITY\NetworkService"

; Windows account(s) to provision as SQL Server system administrators. 

SQLSYSADMINACCOUNTS= "$DBAdminUser"

; Specify 0 to disable or 1 to enable the TCP/IP protocol. 

TCPENABLED= "1"

; Specify 0 to disable or 1 to enable the Named Pipes protocol. 

NPENABLED= "0"

; Startup type for Browser Service. 

BROWSERSVCSTARTUPTYPE= "Automatic"

; Specifies how the startup mode of the report server NT service.  When 
; Manual - Service startup is manual mode (default).
; Automatic - Service startup is automatic mode.
; Disabled - Service is disabled 

RSSVCSTARTUPTYPE= "Automatic"

; Specifies which mode report server is installed in.  
; Default value: “FilesOnly”  

RSINSTALLMODE= "FilesOnlyMode"

; Add description of input argument FTSVCACCOUNT 

FTSVCACCOUNT= "NT AUTHORITY\LOCAL SERVICE"

"@

        if(Is-64bit)
        { 
            $configINI = $configINI + 
@"

; Specify the root installation directory for the WOW64 shared components. 

INSTALLSHAREDWOWDIR= "${env:ProgramFiles(x86)}\Microsoft SQL Server"

"@
        }
        
		# Add above PS1 to temp directory
		#$configIniPath = "$($env:SystemDrive)\SQLConfigurationFile.ini"
		$configIniPath = "$configIniDir\SQLConfigurationFile.ini"
		Set-Content -Path $configIniPath -Value $configINI -Force
	
	}
	Log-MessageVerbose -message "SQL configuration file: $configIniPath" -logFile $global:messagesLog -thisfile $global:thisFile
	$filePath     = "$drive\setup.exe"
	$argumentList = "/IACCEPTSQLSERVERLICENSETERMS /ConfigurationFile=" + $configIniPath
	
	# TODO
	# Work-around - Prevent Install warning notification
	# This work-around may mask possible security issue. Need to find alternate solution
	$Lowriskregpath = "HKCU:\Software\Microsoft\Windows\Currentversion\Policies\Associations"
    $Lowriskregfile = "LowRiskFileTypes"
	
	$LowRiskFileTypes = ".exe"
    $res = New-Item -Path $Lowriskregpath -erroraction silentlycontinue |Out-Null
    $res = New-ItemProperty $Lowriskregpath -name $Lowriskregfile -value $LowRiskFileTypes -propertyType String -erroraction silentlycontinue |Out-Null
	
#	[Diagnostics.Process]::Start($command,$args).WaitForExit() | Out-Null
    Execute-Program -filePath $filePath -argumentList $argumentList
	
	$timeout = 120
	$processRunning = $false
	while($timeout -gt 0)
	{
		$processObj = Get-WmiObject win32_process -Filter "name='sqlservr.exe'"
		if($processObj -ne $null)
		{
			$processRunning = $true
			break;
		}
		sleep -Seconds 1
		$timeout--
	}
	if(!$processRunning)
	{
		$log = ""
		if(Test-Path "$($env:SystemDrive)\Program Files\Microsoft SQL Server\100\Setup Bootstrap\Log\Summary.txt")
		{
			$log = Get-Content -Path "$($env:SystemDrive)\Program Files\Microsoft SQL Server\100\Setup Bootstrap\Log\Summary.txt"
			
		}
		$message = "Failed to detect sqlservr.exe after SQl install: $log"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
		Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-MSSQL2008express" -newValue "0"
		throw $message
	}
	$message = "Install-MSSQL2008express completed successfully."
	Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
	Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-MSSQL2008express" -newValue "1"
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile	
}


<#
.SYNOPSIS
    Internal function to start a process to solve the limitation that existing Start-Process cannot directly output standarderror and standardoutput. We set RedirectStandardError,RedirectStandardOutput set to true and UseShellEexecute set to $false, wait for process to exit
.PARAMETER filename
	The name of the program to run in the process
.PARAMETER Arguments
	The argument value(s) to use when starting the process		
.EXAMPLE
    Start-MyProcess -fileName "net.exe" -arguments "use \\eng.citrite.net\ftl /u:eng\svc_testdept"
.OUTPUTS
	System.Diagnostics.Process
#>
function Start-MyProcess
{
	param
	( 
    	[Parameter(Mandatory=$true)]
		[string]$fileName, 
		[Parameter(Mandatory=$true)]
		[string]$Arguments 
	)
	$functionName = "Start-MyProcess"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile

	$pinfo = New-Object System.Diagnostics.ProcessStartInfo
	$pinfo.FileName = $fileName
	$pinfo.RedirectStandardError = $true
	$pinfo.RedirectStandardOutput = $true
	$pinfo.UseShellExecute = $false
	$pinfo.Arguments = $Arguments
	$p = New-Object System.Diagnostics.Process
	$p.StartInfo = $pinfo
	$p.Start() | Out-Null
	$p.WaitForExit()
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	return $p
}


<#
.SYNOPSIS
    Connect to a network share
.PARAMETER drive
	name of the drive like "Z:" and not "Z:\" : While using positional arguments we should always pass both drive and share parameters.
.PARAMETER share
	the unc path to the share like "\\Server\Share" or "\\Server\<drive>$"
.PARAMETER username
	user name to be used to connect to the share. If domain has to be passed it should be passed with username (e.g. "domain\username")
.PARAMETER password
	password to be used to connect to the share
.PARAMETER persistent
	Whether drive mapping will be persistent or not
.EXAMPLE
    Connect-NetShare -drive "Z:" -share "\\server\share" -username "joe" -password "password"
.EXAMPLE
    Connect-NetShare -share "\\server\share" -username "joe" -password "password"
.EXAMPLE
    Connect-NetShare -drive "Z:" -share "\\server\C$" -username "joe" -password "password"
.OUTPUTS
	Returns the drive letter to which the share has been mapped.
#>
function Connect-NetShare
{
	param
	( 
    	[Parameter(Mandatory=$false)]
		[string]$drive, 
		[Parameter(Mandatory=$true)]
		[string]$share, 
        [Parameter(Mandatory=$false)]
		[string]$username, 
		[Parameter(Mandatory=$false)]
		[string]$password,
				[Parameter(Mandatory=$false)]
		[switch]$persistent
	)
	$functionName = "Connect-NetShare"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile

	# Logging information about the function
	Log-MessageVerbose -message "Connect-NetShare: Connecting to network share $share" -logFile $global:messagesLog -thisfile $global:thisFile
    	$lastexitcode = 0;
	if($persistent) {$pes= "Yes"} else {$pes= "No"}
	If($drive)
	{
		if(-not $drive.EndsWith(":")) {$drive+= ":"}
		$found = net use | Where {$_.contains($drive.ToUpper())}

	    If ($found)
	    {
	        Log-MessageVerbose -message "Connect-NetShare: Drive already mapped." -logFile $global:messagesLog -thisfile $global:thisFile
			Disconnect-NetShare $drive
	    }
		
		$retryAttempts = 0;
		do
		{
			$retry = $false;
			$retryAttempts++;
			If ($username.length -eq 0 -or $password.length -eq 0)
			{
				$res = Start-MyProcess -fileName "net.exe" -arguments "use $drive ""$share"" /persistent:$pes"
			}
			Else
			{
				$res = Start-MyProcess -fileName "net.exe" -arguments "use $drive ""$share"" /user:$userName $password /persistent:$pes"
	
			}
			$exitcode = $res.ExitCode
			$StandardError = $res.StandardError.ReadToEnd()
			$StandardOutput = $res.StandardOutput.ReadToEnd()
			if ($exitcode -ne 0)
			{
					Log-Message -message $StandardError -logFile $global:messagesLog -thisfile $global:thisFile 
					[int] $errorCode = [int] ([regex] "[0-9]+").Match($StandardError).Groups[0].Value
					Log-Message -message "Error code: $errorCode" -logFile $global:messagesLog -thisfile $global:thisFile
					
					switch ($errorCode)
					{
						1909 { if ($retryAttempts -le 3) { $retry = $true; Write-Warning "Account is locked out, sleep 10 minutes and try again"; Start-Sleep -seconds 600;}else 
                        {
                            $message = "Could not connect network share $share, error code = $errorCode"
                            Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
                            throw $message 
                        } }
						1219 { if ($retryAttempts -le 5) { $retry = $true; Write-Warning "Muliple connections using same user, sleep 1 minutes and try again"; Start-Sleep -seconds 60;}else 
                        {
                            $message = "Could not connect network share $share, error code = $errorCode"
                            Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
                            throw $message 
                        }  }
						1920 { if ($retryAttempts -le 5) { $retry = $true; Write-Warning "The file cannot be accessed by the system"; Start-Sleep -seconds 120;}else 
                        {
                            $message =  "Could not connect network share $share, error code = $errorCode"
                            Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
                            throw $message
                        }  }
						default 
						{ 	
							$message = "Could not connect network share $share,  error code = $errorCode"
							Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
							throw $message
						}
					}
			}
		} while ($retry)


		# Check for mapped drive before exiting

		$defaultTimeout = 45
		While($defaultTimeout -gt 0)
		{
			$driveInfo = New-Object System.IO.DriveInfo("$drive\")
			
			If($driveInfo.IsReady -eq $true)
			{
				Break
			}

			$defaultTimeout--
			sleep -Seconds 1
		}
		Log-Message -message "Connect-NetShare: Successfully mapped to the share $share" -logFile $global:messagesLog -thisfile $global:thisFile
		return $drive	
	}
	Else
	{

		$retryAttempts = 0;
		do
		{
			$retry = $false;
			$retryAttempts++;
			If ($username.length -eq 0 -or $password.length -eq 0)
			{
				$res = Start-MyProcess -fileName "net.exe" -arguments "use ""$share"" /persistent:$pes"
			}
			Else
			{
				$res = Start-MyProcess -fileName "net.exe" -arguments "use ""$share"" /user:$userName $password /persistent:$pes"
	
			}
			$exitcode = $res.ExitCode
			$StandardError = $res.StandardError.ReadToEnd()
			$StandardOutput = $res.StandardOutput.ReadToEnd()
			if ($exitcode -ne 0)
			{
					Log-Message -message $StandardError -logFile $global:messagesLog -thisfile $global:thisFile
					[int] $errorCode = [int] ([regex] "[0-9]+").Match($StandardError).Groups[0].Value
					Log-Message -message "Error code: $errorCode" -logFile $global:messagesLog -thisfile $global:thisFile
					
					switch ($errorCode)
					{
						1909 { if ($retryAttempts -le 3) { $retry = $true; Write-Warning "Account is locked out, sleep 10 minutes and try again"; Start-Sleep -seconds 600;}else 
                        {
                            $message = "Could not connect network share $share, error code = $errorCode"
                            Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
                            throw $message 
                        } }
						1219 { if ($retryAttempts -le 5) { $retry = $true; Write-Warning "Muliple connections using same user, sleep 1 minutes and try again"; Start-Sleep -seconds 60;}else 
                        {
                            $message = "Could not connect network share $share, error code = $errorCode" 
                            Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
                            throw $message
                        }  }
						1920 { if ($retryAttempts -le 5) { $retry = $true; Write-Warning "The file cannot be accessed by the system"; Start-Sleep -seconds 120;}else 
                        {
                            $message = "Could not connect network share $share, error code = $errorCode" 
                            Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
                            throw $message
                        }  }
						default 
						{ 
							$message = "Could not connect network share $share,  error code = $errorCode"
							Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
							throw $message
						}
					}
			}
		} while ($retry)
	}
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
    Disconnect a network drive
.PARAMETER drive
	name of the drive like "Z:" and not "Z:\"
.EXAMPLE
    Disconnect-NetShare -drive "Z:"
#>
function Disconnect-NetShare
{
	param
	(	
		[Parameter(Mandatory=$true)]
		[string]$drive
	)
	$functionName = "Disconnect-NetShare"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile

	# Logging information about the function
	Log-MessageVerbose -message "Disconnecting $drive from network share" -logFile $global:messagesLog -thisfile $global:thisFile
	# Change: Added by bassam since the delete of a network drive requires confirmation
	net use $drive /d /y | Out-Null
	if ($lastexitcode -ne 0)
	{
		$message = "Could not disconnect drive $drive, error is $lastexitcode"
        Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        throw $message
	}
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Creates a new PVS farm (i.e. a PVS database)
.PARAMETER sectionName
	Specifies to which Section status should get written to.
#>
function Create-PVSDatabase([Parameter(Mandatory=$true)] [string] $sectionName)
{
	$functionName = "Create-PVSDatabase"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	
    # If operation has already been completed; then just skip it and exit function
    $installed = Get-Parameter -configFile $global:paramFile -section "Server Status" -key "Create-PVSDatabase"
    if("1" -eq $installed)
    {
        $message = "Creation of PVS Database has already been previously completed; skipping operation."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        return
    }
    
	# Populate all variables from parameters file
	$databaseServer    = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "dbServer"
	$databaseName      = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "dbName"
	$dbInstanceName    = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "dbInstanceName"

	$farmName     	     = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "farmName"
	$siteName            = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "siteName"
	$collectionName      = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "collectionName"
	$domainWorkgroupName = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "fqdn"
	
	$defaultAuthGroup  = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "defaultAuthGroup"
	$useADGroups 	   = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "useADGroups"

    # fixups
    $account  = "$defaultAuthGroup"
    if($useADGroups.Contains("true") -or $useADGroups.Contains("1"))
    {
        $useADGroups = $true
        $account  = "$domainWorkgroupName/$defaultAuthGroup"
    }
    else
    {
        $useADGroups = $false
    }

    $sqlScript= "$global:logDir\CreateDB.sql"
    $mapiDLL  = "$env:SystemDrive\Program Files\Citrix\Provisioning Services\Mapi.dll"
	Log-MessageVerbose -message "Loading [$mapiDLL] to generate sql db creation script" -logFile $global:messagesLog -thisfile $global:thisFile
	[System.Reflection.Assembly]::loadfrom($mapiDLL) | Out-Null
    
    $message = "EXECUTE: [Mapi.CommandProcessor]::GenerateScript($databaseName, $farmName, $siteName, $collectionName, $account, $useADGroups, $sqlScript, $false) | Out-Null"
    Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
	[Mapi.CommandProcessor]::GenerateScript($databaseName, $farmName, $siteName, $collectionName, $account, $useADGroups, $sqlScript, $false) | Out-Null
    
    $seconds = 15
	Log-Message -message "Sleeping for [$seconds] seconds..." -logFile $global:messagesLog -thisfile $global:thisFile
    Start-Sleep -Seconds $seconds
    
	if (Test-Path $sqlScript) 
    {
        $message = "Successfully generated db script."
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    }
	else 
	{	$message = "Failed to create db script."
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Create-PVSDatabase" -newValue "0"
		throw $message
	}

	Log-MessageVerbose -message "Executing PVS create db script" -logFile $global:messagesLog -thisfile $global:thisFile
	#$p = [diagnostics.process]::start("sqlcmd", "-S $databaseServer\$dbInstanceName -o $global:logdir\PVSdbCreate.log -i $sqlScript")
	#$p.waitforexit()
	#if (($? -ne $true) -or ($p.exitcode -ne 0)) { throw  "ERROR PVS create dB script failed to execute" }	
    #$global:LastExitcode = 1
    $createLog = "$global:logDir\PVSdbCreate.log"
    $filePath = GetPath-SQLCMD
    
    if($false -eq $filePath)
	{
        $message = "ERROR Unable to find path to sqlcmd.exe."
        Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Create-PVSDatabase" -newValue "0"
        throw $message
	}
    
    $filePath = $filePath + "\sqlcmd.exe"
    if (!(Test-Path -Path $filePath))
	{
        $message = "ERROR Unable to find sqlcmd.exe at [$filePath]."
        Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Create-PVSDatabase" -newValue "0"
        throw $message
	}

    $argumentList = "-S $databaseServer\$dbInstanceName -o $createLog -i $sqlScript"
    Execute-Program -filePath $filePath -argumentList $argumentList
    
	#sqlcmd.exe -S $databaseServer\$dbInstanceName -o $createLog -i $sqlScript
	#if ($LastExitcode -ne 0) 
	#{ 
	#	$message = "ERROR PVS create dB script failed to execute"
	#	Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    #    Set-Parameter -configFile $global:paramFile -section "Server Status" -key "Create-PVSDatabase" -newValue "0"
	#	throw $message
	#}
    
    if (Get-Content $createLog | Select-String -quiet "Database create finished")
    { 
        $message = "PVS create db script executed succesfully."
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Create-PVSDatabase" -newValue "1"
    }
	else 
	{
		$message = "ERROR PVS create dB script failed to execute."
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Create-PVSDatabase" -newValue "0"
		throw $message
	}	
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Enabled/Disable Firewall
.PARAMETER mode
	enable/disable
.PARAMETER sectionName
	Specifies to which Section status should get written to.
#>
function Set-FirewallMode( [Parameter(Position=0,Mandatory=$true)] [string] $mode,
                           [Parameter(Position=1,Mandatory=$true)] [string] $sectionName)
{
	$functionName = "Set-FirewallMode"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
    
    # If operation has already been completed; then just skip it and exit function
    $installed = Get-Parameter -configFile $global:paramFile -section "Server Status" -key "Set-FirewallMode"
    if("1" -eq $installed)
    {
        $message = "Set Firewall mode has already been previously completed; skipping operation."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        return
    }
    
	netsh firewall set opmode $mode
    Set-Parameter -configFile $global:paramFile -section $sectionName -key "Set-FirewallMode" -newValue "1"
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Configure PVS Server - Silently run the PVS configuration wizard. 
.PARAMETER sectionName
	Specifies to which Section status should get written to.
#>
function Configure-PVSServer([Parameter(Mandatory=$true)] [string] $sectionName)
{
	$functionName = "Configure-PVSServer"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile

    # If operation has already been completed; then just skip it and exit function
    $installed = Get-Parameter -configFile $global:paramFile -section "Server Status" -key "Configure-PVSServer"
    if("1" -eq $installed)
    {
        $message = "Configure PVS Server has already been previously completed; skipping operation."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        return
    }
    
	# Populate all variables from parameters file
	$PVSServiceAccountName     = Get-Parameter -configFile $global:paramFile -section "PVS Console Wizard" -key "PVSServiceAccountName"
	$fqdn   = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "fqdn"
	$PVSServiceAccountPassword = Get-Parameter -configFile $global:paramFile -section "PVS Console Wizard" -key "PVSServiceAccountPassword"

	$databaseServer    = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "dbServer"
	$databaseName      = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "dbName"
	$dbInstanceName    = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "dbInstanceName"

	$siteName          = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "siteName"
	$storeName         = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "storeName"
	$storePath         = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "storePath"

	$PVSStreamingIP    = Get-Parameter -configFile $global:paramFile -section "PVS Console Wizard" -key "PVSStreamingIP"
    $PXEServiceType    = Get-Parameter -configFile $global:paramFile -section "PVS Console Wizard" -key "PXEServiceType"
    $IPServiceType     = Get-Parameter -configFile $global:paramFile -section "PVS Console Wizard" -key "IPServiceType"
	$LicenseServer     = Get-Parameter -configFile $global:paramFile -section "General" -key "LicenseServer"
	
	# fixups
	if ($PVSStreamingIP.Contains("local"))
	{
		$PVSStreamingIP = (Test-Connection $env:computername -Count 1).IPV4Address.IPAddressToString
	}
	
	Log-MessageVerbose -message "Verifying store path $storePath" -logFile $global:messagesLog -thisfile $global:thisFile
	if (Test-Path $storePath) 
	{ Log-MessageVerbose -message "$storePath Exists" -logFile $global:messagesLog -thisfile $global:thisFile }
	else 
	{ 
		Log-MessageVerbose -message "$storePath doesn't exist, creating ..." -logFile $global:messagesLog -thisfile $global:thisFile
		New-Item $storePath -type directory 
	}
	if (!(Test-Path $storePath)) 
	{
		$message = "$StorePath doesn't exist and fails to be created"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Configure-PVSServer" -newValue "0"
		throw $message
	}
    
	$filePath = "$env:SystemDrive\Program Files\Citrix\Provisioning Services\ConfigWizard.exe"
    
    $copyfix = $false
    if($copyfix)
    {
        $message = "2012-12-18: THIS IS TEMPORARY. PLEASE REMOVE WHEN TESTING OF CONFIGWIZARD TEMP FIX IS COMPLETED!!!!!!!!!!`n!!!!!!!!!!`n!!!!!!!!!!`n!!!!!!!!!!`n!!!!!!!!!!`n!!!!!!!!!!`n!!!!!!!!!!`n!!!!!!!!!!`n!!!!!!!!!!`n!!!!!!!!!!`n!!!!!!!!!!`n!!!!!!!!!!"
        Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        $source = "\\10.204.154.9\victorr\ConfigWizardFix\ConfigWizard.32"
        if (Is-64bit) 
        {
            $source = "\\10.204.154.9\victorr\ConfigWizardFix\ConfigWizard.64"
        }
        
        $result = dir "$env:SystemDrive\Program Files\Citrix\Provisioning Services\" | Out-String
        $message = "Directory listing BEFORE copying new configwizard.exe fix:  $result "
        Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile

        $message = "EXECUTE: Copy $source  $filePath"
        Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Copy $source  $filePath

        $result = dir "$env:SystemDrive\Program Files\Citrix\Provisioning Services\" | Out-String
        $message = "Directory listing AFTER copying new configwizard.exe fix:  $result "
        Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    }

	if ((Test-Path $filePath))
	{
		Log-MessageVerbose -message "ConfigWizard.exe exists, creating answer file & configuring..." -logFile $global:messagesLog -thisfile $global:thisFile
		
		$AnswerFileTemplate =
@"
IPServiceType=$IPServiceType
PXEServiceType=$PXEServiceType
FarmConfiguration=2
DatabaseServer=$databaseServer
DatabaseInstance=$dbInstanceName
FarmExisting=$databaseName
ExistingSite=$siteName
Store=$storeName
DefaultPath=$storePath
UserName=$fqdn\$PVSServiceAccountName
UserPass=$PVSServiceAccountPassword
PasswordManagementInterval=7
StreamNetworkAdapterIP=$PVSStreamingIP
ManagementNetworkAdapterIP=$PVSStreamingIP
IpcPortBase=6890
IpcPortCount=20
SoapPort=54321
BootstrapFile=$env:ProgramData\Citrix\Provisioning Services\Tftpboot\ARDBP32.BIN
LS1=$PVSStreamingIP,0.0.0.0,0.0.0.0,6910
AdvancedVerbose=1
AdvancedInterrultSafeMode=0
AdvancedMemorySupport=1
AdvancedRebootFromHD=0
AdvancedRecoverSeconds=10
AdvancedLoginPolling=5000
AdvancedLoginGeneral=30000
"@
		$answerFile = "$global:logDir\ConfigWizard.txt"
		Set-Content -Path $answerFile -Value $AnswerFileTemplate -Force -Encoding Unicode
       
        # first, print out the current status of Citrix services
        Get-StatusCitrixServices
        
        $logFile      = "$global:logDir\ConfigWizard.log"
        $argumentList = "/a:$answerFile /o:$logFile"
        Execute-Program -filePath $filePath -argumentList $argumentList
		
		if (Get-Content $logFile | Select-String -quiet "Configuration complete")
		{ 
			Log-Message -message "Configuration Wizard completed successfully" -logFile $global:messagesLog -thisfile $global:thisFile
            Set-Parameter -configFile $global:paramFile -section $sectionName -key "Configure-PVSServer" -newValue "1"
		}
		else 
		{ 
			$message = "Running PVS Server Configuration Wizard Failed"
			Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
            Set-Parameter -configFile $global:paramFile -section $sectionName -key "Configure-PVSServer" -newValue "0"
			throw $message
		}
	}
	else 
	{ 
		$message = "ERROR: ConfigWizard is missing. Unable to find [$filePath]."
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Configure-PVSServer" -newValue "0"
		throw $message
	}

    Log-MessageVerbose -message "Fixing bootstrap..." -logFile $global:messagesLog -thisfile $global:thisFile
    Fix-BootStrap

    # print out the current status of Citrix services
    Get-StatusCitrixServices
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
	Registers PVS Powershell Snapin(MCLIPsSnapin) and adds it to PoSH session
#>
function Register-PVSMcliPSSnapin
{
	$functionName = "Register-PVSMcliPSSnapin"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile

    $logFile      = $global:logDir + "\InstallUtil.log"
    $argumentList = "`"$env:ProgramFiles\Citrix\Provisioning Services Console\McliPSSnapin.dll`" /LogFile=$logFile"
    if (Is-64bit)
    {
		$message = "Registering PVS PSSnapin x64..."
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    	$installDir = "$env:SystemRoot\Microsoft.Net\Framework64\v2.0.50727"
    }
    else
    {
		$message = "Registering PVS PSSnapin x86..."
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
	    $installDir = "$env:SystemRoot\Microsoft.Net\Framework\v2.0.50727"
    }
    
    $filePath = "$installDir\installutil.exe"
    Execute-Program -filePath $filePath -argumentList $argumentList
    
    $message = "Assuming registering of PVS PSSnapin completed successfully."
    Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile

	Load-PVSMcliPSSnapin
	
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}



<#
.SYNOPSIS
 	Load PVS Powershell Snapin(MCLIPsSnapin). Note: snapin needs to already have been registered, prior to calling this fucntion.
#>
function Load-PVSMcliPSSnapin
{
	$functionName = "Load-PVSMcliPSSnapin"
	Log-MessageVerbose -message "Entering function Load-PVSSnapins"	-logFile $global:messagesLog -thisfile $global:thisFile  
    
    # Note: ASSUMPTION is that "Register-PVSMcliPSSnapin" has already been called by this point in time.
    
    $message = "Adding PVS mclipssnapin to PS Session"
	Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
	try
    {
        $message = "EXECUTE: Add-PSSnapin mclipssnapin -ErrorAction SilentlyContinue |Out-Null"
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Add-PSSnapin mclipssnapin -ErrorAction SilentlyContinue |Out-Null 
    }
	catch [Exception] 
	{
		$message = "$($_.Exception.Message)"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        throw $message
	}	
	Log-MessageVerbose -message "Leaving function Load-PVSSnapins" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Restart several PVS services.
#>
function Restart-PVSServices
{
	$functionName = "Restart-PVSServices"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
    
	try 
    {
        # stop services
        Log-MessageVerbose -message "EXECUTE: Stop-Service -displayname Citrix PVS PXE Service" -logFile $global:messagesLog -thisfile $global:thisFile
    	Stop-Service -displayname "Citrix PVS PXE Service"
        
        Log-MessageVerbose -message "EXECUTE: Stop-Service -displayname Citrix PVS Two-Stage Boot Service" -logFile $global:messagesLog -thisfile $global:thisFile
    	Stop-Service -displayname "Citrix PVS Two-Stage Boot Service"
        
        Log-MessageVerbose -message "EXECUTE: Stop-Service -displayname Citrix PVS Soap Server" -logFile $global:messagesLog -thisfile $global:thisFile
    	Stop-Service -displayname "Citrix PVS Soap Server"
        
        Log-MessageVerbose -message "EXECUTE: Stop-Service -displayname Citrix PVS TFTP Service" -logFile $global:messagesLog -thisfile $global:thisFile
    	Stop-Service -displayname "Citrix PVS TFTP Service"
        
        Log-MessageVerbose -message "EXECUTE: Stop-Service -displayname Citrix PVS Stream Service" -logFile $global:messagesLog -thisfile $global:thisFile
    	Stop-Service -displayname "Citrix PVS Stream Service"        

        Log-MessageVerbose -message "EXECUTE: Stop-Service -displayname Citrix PVS Ramdisk Server" -logFile $global:messagesLog -thisfile $global:thisFile
    	Stop-Service -displayname "Citrix PVS Ramdisk Server"        
	}
    catch
    {
        $message = "Error while attempting to stop services."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        throw $message
    }
    
	try 
    {
        # start services
        $seconds = 5
        Log-Message -message "Sleeping for [$seconds] seconds..." -logFile $global:messagesLog -thisfile $global:thisFile
        Start-Sleep -Seconds $seconds        
        
        Log-MessageVerbose -message "EXECUTE: Start-Service -displayname Citrix PVS Stream Service" -logFile $global:messagesLog -thisfile $global:thisFile
    	Start-Service -displayname "Citrix PVS Stream Service"
        Log-Message -message "Sleeping for [$seconds] seconds..." -logFile $global:messagesLog -thisfile $global:thisFile
        Start-Sleep -Seconds $seconds        

        Log-MessageVerbose -message "EXECUTE: Start-Service -displayname Citrix PVS PXE Service" -logFile $global:messagesLog -thisfile $global:thisFile
    	Start-Service -displayname "Citrix PVS PXE Service"
        Log-Message -message "Sleeping for [$seconds] seconds..." -logFile $global:messagesLog -thisfile $global:thisFile
        Start-Sleep -Seconds $seconds
        
        Log-MessageVerbose -message "EXECUTE: Start-Service -displayname Citrix PVS Two-Stage Boot Service" -logFile $global:messagesLog -thisfile $global:thisFile
    	Start-Service -displayname "Citrix PVS Two-Stage Boot Service"
        Log-Message -message "Sleeping for [$seconds] seconds..." -logFile $global:messagesLog -thisfile $global:thisFile
        Start-Sleep -Seconds $seconds
        
        Log-MessageVerbose -message "EXECUTE: Start-Service -displayname Citrix PVS Soap Server" -logFile $global:messagesLog -thisfile $global:thisFile
    	Start-Service -displayname "Citrix PVS Soap Server"
        Log-Message -message "Sleeping for [$seconds] seconds..." -logFile $global:messagesLog -thisfile $global:thisFile
        Start-Sleep -Seconds $seconds

        Log-MessageVerbose -message "EXECUTE: Start-Service -displayname Citrix PVS TFTP Service" -logFile $global:messagesLog -thisfile $global:thisFile
    	Start-Service -displayname "Citrix PVS TFTP Service"
        Log-Message -message "Sleeping for [$seconds] seconds..." -logFile $global:messagesLog -thisfile $global:thisFile
        Start-Sleep -Seconds $seconds
        
        Log-MessageVerbose -message "EXECUTE: Start-Service -displayname Citrix PVS Ramdisk Server" -logFile $global:messagesLog -thisfile $global:thisFile
    	Start-Service -displayname "Citrix PVS Ramdisk Server"        
        Log-Message -message "Sleeping for [$seconds] seconds..." -logFile $global:messagesLog -thisfile $global:thisFile
        Start-Sleep -Seconds $seconds
	}
    catch
    {
        $message = "Error while attempting to start services."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        throw $message
    }
    
    Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Evaluate MAPI Return codes
#>
function Return-MAPIError
{
	$functionName = "Return-MAPIError"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile

	if ($Error.Count -gt 0)
	{
		foreach ($err in $Error)
		{
			if ($err.FullyQualifiedErrorId -ne $NULL)
			{
				$slec = $err.FullyQualifiedErrorId.Split(',')[0].Trim()
				$Error.Clear()
				break;
			}
		}
	}
	else { $slec = "Success"; $Error.Clear() }
	$slec

	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Creates a PVS vDisk
.PARAMETER vDiskName
	Name of vDisk to create
.PARAMETER pvsStoreName
	Name of PVS store to create vDisk in
.PARAMETER pvsSiteName
	Name of PVS site the specified store resides in
.PARAMETER sectionName
	Specifies to which Section status should get written to.
.PARAMETER vDiskSizeInMB
	Size of vDisk to create in Mb, default=20GB
.PARAMETER vDiskType
	Type of vDisk to create, fixed or dynamic, default=dynamic
#>
function Create-PVSVdisk(
			[Parameter(Position=0,Mandatory=$true)] [string]$vDiskName,
			[Parameter(Position=1,Mandatory=$true)] [string]$pvsStoreName,
			[Parameter(Position=2,Mandatory=$true)] [string]$pvsSiteName,
            [Parameter(Position=3,Mandatory=$true)] [string]$sectionName,
			[Parameter(Position=4,Mandatory=$false)] [string]$vDiskSizeInMB = "20000",
			[Parameter(Position=5,Mandatory=$false)] [string]$vDiskType = "1")
{
	$functionName = "Create-PVSVdisk"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile

    # If operation has already been completed; then just skip it and exit function
    $installed = Get-Parameter -configFile $global:paramFile -section "Server Status" -key "Create-PVSVdisk"
    if("1" -eq $installed)
    {
        $message = "Creation of PVS VDisk has already been previously completed; skipping operation."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        return
    }
    
	# Note: ASSUMPTION is that "Register-PVSMcliPSSnapin" has already been called by this point in time.	
	$doNotCare = Restart-PVSServices	
	$message = "Creating vDisk"
	Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
	$error.Clear()
	try
    {
        $message = "EXECUTE: mcli-runwithreturn createdisk -p name=$vDiskName,size=$vDiskSizeInMB,storename=$pvsStoreName,sitename=$pvsSiteName,type=$vDiskType"
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        mcli-runwithreturn createdisk -p name=$vDiskName,size=$vDiskSizeInMB,storename=$pvsStoreName,sitename=$pvsSiteName,type=$vDiskType
    }
	catch [Exception] 
	{
		$message = "$($_.Exception.Message)"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        throw $message
	}
	$result = Return-MAPIError
	if ($result -ne "Success") 
	{ 
		$message =  "Creating disk Failed: $result"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Create-PVSVdisk" -newValue "0"
		throw $message
	}  
	else 
	{ 
		$message = "Create disk Succeeded"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Create-PVSVdisk" -newValue "1"
	}

	$message = "Checking vDisk creation status"
	Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
	$error.Clear()
	try
    {
        $message = "EXECUTE: mcli-runwithreturn creatediskstatus -p name=$vDiskName,storename=$pvsStoreName"
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        mcli-runwithreturn creatediskstatus -p name=$vDiskName,storename=$pvsStoreName 
    }
	catch [Exception] 
	{
		$message = "$($_.Exception.Message)"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Create-PVSVdisk" -newValue "0"
		throw $message
	}	
	$result = Return-MAPIError
	if ($result -ne "Success") 
	{ 
		$message = "vDisk creation status Failed: $result"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Create-PVSVdisk" -newValue "0"
		throw $message
	}  
	else 
	{ 
		$message = "vDisk creation status exists, Succeeded"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Create-PVSVdisk" -newValue "1"
	}

	$message = "Enable AD password changes on disk" #This is enabled by default on PVS 6.0 and above but will not hurt to run
	Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
	$error.Clear()
	try
    {
        $message = "EXECUTE: mcli-set disk -p disklocatorname=$vDiskName,sitename=$pvsSiteName,storeName=$pvsStoreName -r adPasswordEnabled=1"
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        mcli-set disk -p disklocatorname=$vDiskName,sitename=$pvsSiteName,storeName=$pvsStoreName -r adPasswordEnabled=1
    }
	catch [Exception] 
	{
		$message = "$($_.Exception.Message)"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Create-PVSVdisk" -newValue "0"
		throw $message
	}
    
	$result = Return-MAPIError
	if ($result -ne "Success") 
	{ 
		$message = "Enabling AD password changes on disk Failed: $result"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Create-PVSVdisk" -newValue "0"
		throw $message
	}
	else 
	{ 
		$message = "Enable AD password changes on disk Succeeded"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Create-PVSVdisk" -newValue "1"
	}

	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Creates PVS device records for given device
.PARAMETER deviceName
	Name of device to add
.PARAMETER MACaddress
	Specifies MAC
.PARAMETER sectionName
	Specifies to which Section status should get written to.
.PARAMETER collectionName
	Name of collection to add device to
.PARAMETER siteName
	Name of site specified collection resides in
.PARAMETER deviceType
	Type of PVS device to create, default=0 (production)
.PARAMETER bootFrom
	Device to set record to boot from, default = 1
#>
function Create-PVSDevice(
			[Parameter(Position=0,Mandatory=$true)] [string]$deviceName,
			[Parameter(Position=1,Mandatory=$true)] [string]$MACaddress,
            [Parameter(Position=2,Mandatory=$true)] [string]$sectionName,
			[Parameter(Position=3,Mandatory=$false)] [string]$collectionName="ST_Collection",
			[Parameter(Position=4,Mandatory=$false)] [string]$siteName="ST_Site",
			[Parameter(Position=5,Mandatory=$false)] [string]$deviceType="0",
			[Parameter(Position=6,Mandatory=$false)] [string]$bootFrom="1")
{
	$functionName = "Create-PVSDevice"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	
    # If operation has already been completed; then just skip it and exit function
    $installed = Get-Parameter -configFile $global:paramFile -section $sectionName -key "Create-PVSDevice"
    if("1" -eq $installed)
    {
        $message = "Creation of PVS Device has already been previously completed; skipping operation."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        return
    }
    
	# Note: ASSUMPTION is that "Register-PVSMcliPSSnapin" has already been called by this point in time.
	$error.Clear()	
	try
    { 
        $message = "EXECUTE: mcli-add device -r deviceName=$deviceName,collectionName=$collectionName,siteName=$siteName,deviceMac=$MACaddress,bootFrom=$bootFrom"
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        $res = mcli-add device -r deviceName=$deviceName,collectionName=$collectionName,siteName=$siteName,deviceMac=$MACaddress,bootFrom=$bootFrom
    }
	catch [Exception] 
	{
		$message = "$($_.Exception.Message)"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Create-PVSDevice" -newValue "0"
		throw $message
	}
	
	$result = Return-MAPIError
	if ($result -ne "Success") 
	{
		$message = "Adding Device Failed: $result"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Create-PVSDevice" -newValue "0"
		throw $message
	}  
	else 
	{ 
		$message = "Add Device Succeeded"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Create-PVSDevice" -newValue "1"
	}
	
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Assigns PVS device to a vDisk (disk locator record)
.PARAMETER deviceName
	Name of device to assign disk
.PARAMETER vDiskName
	Name of disk to to assign to device
.PARAMETER sectionName
	Specifies to which Section status should get written to.
.PARAMETER collectionName
	Name of collection the device resides in
.PARAMETER siteName
	Name of site specified collection resides in
.PARAMETER StoreName
	Name of store the specified vDisk resides in
#>
function Assign-PVSDisk2Device(
			[Parameter(Position=0,Mandatory=$true)] [string]$deviceName,
			[Parameter(Position=1,Mandatory=$true)] [string]$vDiskName,
            [Parameter(Position=2,Mandatory=$true)] [string]$sectionName,
			[Parameter(Position=3,Mandatory=$false)] [string]$collectionName="ST_Collection",
			[Parameter(Position=4,Mandatory=$false)] [string]$siteName="ST_Site",
			[Parameter(Position=5,Mandatory=$false)] [string]$storeName="ST_Store")
{
	$functionName = "Assign-PVSDisk2Device"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	
    # If operation has already been completed; then just skip it and exit function
    $installed = Get-Parameter -configFile $global:paramFile -section $sectionName -key "Assign-PVSDisk2Device"
    if("1" -eq $installed)
    {
        $message = "Assign PVSDisk to Device has already been previously completed; skipping operation."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        return
    }
    
	# Note: ASSUMPTION is that "Register-PVSMcliPSSnapin" has already been called by this point in time.	
	$error.Clear()
	try
    {
        $message = "EXECUTE: mcli-run assignDiskLocator -p diskLocatorName=$vDiskName,deviceName=$deviceName,collectionName=$collectionName,siteName=$siteName,storeName=$storeName"
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        mcli-run assignDiskLocator -p diskLocatorName=$vDiskName,deviceName=$deviceName,collectionName=$collectionName,siteName=$siteName,storeName=$storeName
    }
	catch [Exception] 
	{
		$message = "$($_.Exception.Message)"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Assign-PVSDisk2Device" -newValue "0"
		throw $message
	}
	
	$result = Return-MAPIError
	if ($result -ne "Success") 
	{ 
		$message = "Assigning Disk Locator to Devices Failed: $result"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Assign-PVSDisk2Device" -newValue "0"
		throw $message
	}
	else 
	{ 
		$message = "Assigning Disk Locator to Devices Succeeded"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
	}
	
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
    Set-Parameter -configFile $global:paramFile -section $sectionName -key "Assign-PVSDisk2Device" -newValue "1"
    
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Sets a PVS device's boot device
.PARAMETER deviceName
	Name of device to modify
.PARAMETER bootFrom
	Device to set record to boot from. Choices are 1 for vDisk, 2 for Hard Disk
	and 3 for Floppy. This cannot be Set for a Device with Personal vDisk. Min=1, Max=3
.PARAMETER sectionName
	Specifies to which Section status should get written to.
#>
function Set-PVSDeviceBootFrom(
			[Parameter(Position=0,Mandatory=$true)] [string]$deviceName,
			[Parameter(Position=1,Mandatory=$true)] [string]$bootFrom,
            [Parameter(Position=2,Mandatory=$true)] [string]$sectionName)
{
	$functionName = "Set-PVSDeviceBootFrom"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	
    # If operation has already been completed; then just skip it and exit function
    $installed = Get-Parameter -configFile $global:paramFile -section $sectionName -key "Set-PVSDeviceBootFrom"
    if("1" -eq $installed)
    {
        $message = "Set PVSDeviceBootFrom has already been previously completed; skipping operation."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        return
    }
    
	# Note: ASSUMPTION is that "Register-PVSMcliPSSnapin" has already been called by this point in time.	
	$error.Clear()	
	try
    { 
        $message = "EXECUTE: mcli-set device -p deviceName=$deviceName -r bootFrom=$bootFrom"
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        $res = mcli-set device -p deviceName=$deviceName -r bootFrom=$bootFrom
    }
	catch [Exception] 
	{
		$message = "$($_.Exception.Message)"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Set-PVSDeviceBootFrom" -newValue "1"
		throw $message
	}
	
	$result = Return-MAPIError
	if ($result -ne "Success") 
	{
		$message = "Setting $deviceName to boot from $bootFrom, Failed: $result"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Set-PVSDeviceBootFrom" -newValue "1"
		throw $message
	}  
	else 
	{ 
		$message = "Setting $deviceName to boot from $bootFrom, Succeeded"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Set-PVSDeviceBootFrom" -newValue "1"
	}
	
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Get parameter from configuration parameters file
.PARAMETER configFile
	Full path to parameters configuration file.
.PARAMETER section
	Name of the desired section from which to retrieve value. 
.PARAMETER key
	Name of the desired key from which to retrieve value. 
#>
function Get-Parameter([Parameter(Position=0,Mandatory=$true)] [string]$configFile,
                       [Parameter(Position=1,Mandatory=$true)] [string]$section,
					   [Parameter(Position=2,Mandatory=$true)] [string]$key)
{
    # confirm file exists
    if (!(Test-Path $configFile))
    {
        $message = "File I/O Error with [$configFile]."
		Write-Host    $message
        Write-Verbose $message
        Write-Output  $message
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
		throw $message
        return "-9zq" # technically, should never reach this line of code
    }
    
	$lines = Get-Content $configFile
    $insideSection = $false
	for ($i=0; $i -le ($lines.Length-1); $i=$i+1)
	{
        $currentLine = $lines[$i]
        # ignore comments
		if ($currentLine.StartsWith("#"))
		{
			continue
		}
        
        # check if this is the section of interest
		if ($currentLine.StartsWith("[$section]"))
		{
            $insideSection = $true
            continue
		}

        if ($insideSection)
        {
            # extract value of interest
    		if ($currentLine.StartsWith("$key="))
    		{
    			$len   = "$key=".Length
    			$value = $lines[$i].Substring($len)
    			return $value
    		}
            
            # we hit another section and still have not found
            # the actual var of interest
            if($currentLine.StartsWith("["))
            {
                return "-9zq"
            }
            
            continue
        }
	}
	return "-9zq"
}


<#
.SYNOPSIS
 	Set parameter from configuration parameters file
.PARAMETER configFile
	Full path to parameters configuration file.
.PARAMETER section
	Name of the desired section from which to retrieve value. 
.PARAMETER key
	Name of the desired key from which to retrieve value. 
.PARAMETER newValue
	New value to be written to the desired key
#>
function Set-Parameter([Parameter(Position=0,Mandatory=$true)] [string]$configFile,
                       [Parameter(Position=1,Mandatory=$true)] [string]$section,
                       [Parameter(Position=2,Mandatory=$true)] [string]$key,
					   [Parameter(Position=3,Mandatory=$true)] [string]$newValue)
{
    # confirm file exists
    if (!(Test-Path $configFile))
    {
        $message = "File I/O Error with [$configFile]."
		Write-Host    $message
        Write-Verbose $message
        Write-Output  $message
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
		throw $message
        return "-9zq" # technically, should never reach this line of code
    }
    $dirty = $false
	$lines = Get-Content $configFile
    $insideSection = $false
    $newFile = ""
	for ($i=0; $i -le ($lines.Length-1); $i=$i+1)
	{
        $currentLine = $lines[$i]
        
        if ($dirty)
        {
            # if all done setting the single variable then just do nothing
            # but copy rest of file as is.
            $newFile = $newFile + $currentLine + "`r`n"
            continue
        }
        
        # ignore comments
		if ($currentLine.StartsWith("#"))
		{
            $newFile = $newFile + $currentLine + "`r`n"
            Write-Debug "START WITH: $currentLine"
			continue
		}
        
        # check if this is the section of interest
		if ($currentLine.StartsWith("[$section]"))
		{
            $insideSection = $true
            $newFile = $newFile + $currentLine + "`r`n"
            Write-Debug "SECTION: $currentLine"
            continue
		}

        if ($insideSection)
        {
            # change value of interest
    		if ($currentLine.StartsWith("$key="))
    		{
                $newLine = "$key=" + $newValue + "`r`n"
                $newFile = $newFile + $newLine
                $dirty   = $true
                Write-Debug "UPDATED: newLine=$newLine"
    			continue
    		}
            $newFile = $newFile + $currentLine + "`r`n"
            Write-Debug "INSIDE NOT UPDATED: $currentLine"
            continue
        }
        
        $newFile = $newFile + $currentLine + "`r`n"
        Write-Debug "DEFAULT: $currentLine"
	}
    
    if ($dirty)
    {
        Write-Debug "returning newfile."
        # re-write file with new key value
        Set-Content -Path $configFile -Value $newFile -Force
        return $true
    }
    
    Write-Debug "returning key not found."
	return $false
}


<#
.SYNOPSIS
 	Install PVS Console
.PARAMETER sectionName
	Specifies to which Section status should get written to.
#>
function Install-PVSConsole([Parameter(Mandatory=$true)] [string] $sectionName)
{
	$functionName = "Install-PVSConsole"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	
    # If operation has already been completed; then just skip it and exit function
    $installed = Get-Parameter -configFile $global:paramFile -section "Server Status" -key "Install-PVSConsole"
    if("1" -eq $installed)
    {
        $message = "Installation of PVS Console has already been previously completed; skipping operation."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        return
    }
    
	$DriveLetter  = "R:"
	$BaseLocation = Get-Parameter -configFile $paramFile -section "PVS Console Installer" -key "PVSCslLocation"
	$network = $BaseLocation.StartsWith("\\")
	if($network)
	{
		$user     = Get-Parameter -configFile $global:paramFile -section "PVS Console Installer" -key "PVSCslLocationNetUser"
		$password = Get-Parameter -configFile $global:paramFile -section "PVS Console Installer" -key "PVSCslLocationNetPassword"
		Connect-NetShare -drive $DriveLetter -share $BaseLocation -username $user -password $password | Out-Null
		$BaseLocation = $DriveLetter
	}
	
	$Installer = Get-Parameter -configFile $paramFile -section "PVS Console Installer" -key "PVSCslInstallerX86"
	if (Is-64bit) 
	{
		$Installer = Get-Parameter -configFile $paramFile -section "PVS Console Installer" -key "PVSCslInstallerX64"
	}
	
	$filePath     = "`"$BaseLocation\$Installer`""
    $logFile      = "$global:logDir\PVSConsole.log"
    $argumentList = " /V`"/q/l*v $logFile`""
    Execute-Program -filePath $filePath -argumentList $argumentList

    if (Get-Content $logFile | Select-String -quiet "completed successfully")
    {
		$message = "Installation of PVS Console successfully Completed."
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
		Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-PVSConsole" -newValue "1" 
    }
    else
    {
		$message = "ERROR: Installing PVS Console Failed"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
		Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-PVSConsole" -newValue "0" 
        throw $message
    }


	if($network)
	{
		Disconnect-NetShare -drive $DriveLetter
	}
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Install PVS Server
.PARAMETER sectionName
	Specifies to which Section status should get written to.
#>
function Install-PVSServer([Parameter(Mandatory=$true)] [string] $sectionName)
{
	$functionName = "Install-PVSServer"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	
    # If operation has already been completed; then just skip it and exit function
    $installed = Get-Parameter -configFile $global:paramFile -section "Server Status" -key "Install-PVSServer"
    if("1" -eq $installed)
    {
        $message = "Installation of PVS Server has already been previously completed; skipping operation."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        return
    }
    
	$DriveLetter  = "R:"
	$BaseLocation = Get-Parameter -configFile $paramFile -section "PVS Server Installer" -key "PVSSrvLocation"
	$network = $BaseLocation.StartsWith("\\")
	if($network)
	{
		$user     = Get-Parameter -configFile $global:paramFile -section "PVS Server Installer" -key "PVSSrvLocationNetUser"
		$password = Get-Parameter -configFile $global:paramFile -section "PVS Server Installer" -key "PVSSrvLocationNetPassword"
		Connect-NetShare -drive $DriveLetter -share $BaseLocation -username $user -password $password | Out-Null
		$BaseLocation = $DriveLetter
	}
	
	$Installer = Get-Parameter -configFile $paramFile -section "PVS Server Installer" -key "PVSSrvInstallerX86"
	if (Is-64bit) 
	{
		$Installer = Get-Parameter -configFile $paramFile -section "PVS Server Installer" -key "PVSSrvInstallerX64"
	}
	
	$filePath     = "`"$BaseLocation\$Installer`""
    $logFile      = "$global:logDir\PVSSRV.log"
    $argumentList = " /V`"/q/l*v $logFile`""
    Execute-Program -filePath $filePath -argumentList $argumentList

    if (Get-Content $logFile | Select-String -quiet "completed successfully")
    {
        $message = "Installation of PVS Server successfully Completed."
        Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-PVSServer" -newValue "1"
        }
    else
    {
        $message = "ERROR: Installing PVS Server Failed"
        Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-PVSServer" -newValue "0"
        throw $message
    }


	if($network)
	{
		Disconnect-NetShare -drive $DriveLetter
	}
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Install Dot Net 4
.PARAMETER sectionName
	Specifies to which Section status should get written to.
#>
function Install-DotNet4([Parameter(Position=0,Mandatory=$true)] [string]$sectionName)
{
	$functionName = "Install-DotNet4"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	
	# check if Net4 already installed
	$path  = Test-Path "HKLM:\Software\Microsoft\NET Framework Setup\NDP\v4\full"
	$value = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\full").Version
	if ($path -and $value)
	{
		$message = "NetFramework [$value] is already installed. Skipping installation!"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
		Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-DotNet4" -newValue "1"
	}
	else
	{
		$DriveLetter  = "R:"
		$BaseLocation = Get-Parameter -configFile $paramFile -section "Dot Net 4 Installer" -key "DotNet4Location"
		$network = $BaseLocation.StartsWith("\\")
		if($network)
		{
			$user     = Get-Parameter -configFile $global:paramFile -section "Dot Net 4 Installer" -key "DotNet4NetUser"
			$password = Get-Parameter -configFile $global:paramFile -section "Dot Net 4 Installer" -key "DotNet4NetPassword"
			Connect-NetShare -drive $DriveLetter -share $BaseLocation -username $user -password $password | Out-Null
			$BaseLocation = $DriveLetter
		}
		
		$Installer = Get-Parameter -configFile $paramFile -section "Dot Net 4 Installer" -key "DotNet4InstallerX86"
		if (Is-64bit) 
		{
			$Installer = Get-Parameter -configFile $paramFile -section "Dot Net 4 Installer" -key "DotNet4InstallerX64"
		}
		
        $filePath     = "`"$BaseLocation\$Installer`""
        $logFile      = "$global:logDir\DotNet4.log"
        $argumentList = " /V`"/q/l*v $logFile`""
        Execute-Program -filePath $filePath -argumentList $argumentList

		$message = "Assuming installation of Dot Net4 successfully Completed."
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
		Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-DotNet4" -newValue "1"

		if($network)
		{
			Disconnect-NetShare -drive $DriveLetter
		}
	}
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Install DelagatedAdminPSSnapin
.PARAMETER sectionName
	Specifies to which Section status should get written to.
#>
function Install-DelagatedAdminPSSnapin([Parameter(Mandatory=$true)] [string] $sectionName)
{
	$functionName = "Install-DelagatedAdminPSSnapin"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	
    # If operation has already been completed; then just skip it and exit function
    $installed = Get-Parameter -configFile $global:paramFile -section "Server Status" -key "Install-DelagatedAdminPSSnapin"
    if("1" -eq $installed)
    {
        $message = "Installation of DelegatedAdminPSSnapin has already been previously completed; skipping operation."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        return
    }
    
	$DriveLetter  = "R:"
	$BaseLocation = Get-Parameter -configFile $paramFile -section "DelagatedAdminPSSnapin Installer" -key "DelagatedAdminLocation"
	$network = $BaseLocation.StartsWith("\\")
	if($network)
	{
		$user     = Get-Parameter -configFile $global:paramFile -section "DelagatedAdminPSSnapin Installer" -key "DelagatedAdminNetUser"
		$password = Get-Parameter -configFile $global:paramFile -section "DelagatedAdminPSSnapin Installer" -key "DelagatedAdminNetPassword"
		Connect-NetShare -drive $DriveLetter -share $BaseLocation -username $user -password $password | Out-Null
		$BaseLocation = $DriveLetter
	}
	
	$Installer = Get-Parameter -configFile $paramFile -section "DelagatedAdminPSSnapin Installer" -key "DelagatedAdminInstallerX86"
	if (Is-64bit) 
	{
		$Installer = Get-Parameter -configFile $paramFile -section "DelagatedAdminPSSnapin Installer" -key "DelagatedAdminInstallerX64"
	}
	
	$filePath     = "`"$BaseLocation\$Installer`""
    $logFile      = "$global:logDir\DelagatedAdminSnapin.log"
    $argumentList = "/qn /l*v $logFile"
    Execute-Program -filePath $filePath -argumentList $argumentList

    if (Get-Content $logFile | Select-String -quiet "completed successfully")
    {
        $message = "DelagatedAdmin PowerShell Snapin Installation successfully Completed."
        Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-DelagatedAdminPSSnapin" -newValue "1"
    }
    else
    {
        $message = "ERROR: Installing DelagatedAdmin PowerShell Snapin Failed."
        Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-DelagatedAdminPSSnapin" -newValue "0"
        throw $message
    }

	if($network)
	{
		Disconnect-NetShare -drive $DriveLetter
	}
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Install ConfigurationLoggingPSSnapin
.PARAMETER sectionName
	Specifies to which Section status should get written to.
#>
function Install-ConfigurationLoggingPSSnapin([Parameter(Mandatory=$true)] [string] $sectionName)
{
	$functionName = "Install-ConfigurationLoggingPSSnapin"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	
    # If operation has already been completed; then just skip it and exit function
    $installed = Get-Parameter -configFile $global:paramFile -section "Server Status" -key "Install-ConfigurationLoggingPSSnapin"
    if("1" -eq $installed)
    {
        $message = "Installation of ConfigurationLoggingPSSnapin has already been previously completed; skipping operation."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        return
    }
    
	$DriveLetter  = "R:"
	$BaseLocation = Get-Parameter -configFile $paramFile -section "ConfigurationLoggingPSSnapin Installer" -key "ConfigLogLocation"
	$network = $BaseLocation.StartsWith("\\")
	if($network)
	{
		$user     = Get-Parameter -configFile $global:paramFile -section "ConfigurationLoggingPSSnapin Installer" -key "ConfigLogNetUser"
		$password = Get-Parameter -configFile $global:paramFile -section "ConfigurationLoggingPSSnapin Installer" -key "ConfigLogNetPassword"
		Connect-NetShare -drive $DriveLetter -share $BaseLocation -username $user -password $password | Out-Null
		$BaseLocation = $DriveLetter
	}
	
	$Installer = Get-Parameter -configFile $paramFile -section "ConfigurationLoggingPSSnapin Installer" -key "ConfigLogInstallerX86"
	if (Is-64bit) 
	{
		$Installer = Get-Parameter -configFile $paramFile -section "ConfigurationLoggingPSSnapin Installer" -key "ConfigLogInstallerX64"
	}
	
	$filePath     = "`"$BaseLocation\$Installer`""
    $logFile      = "$global:logDir\ConfigLoggingSnapin.log"
    $argumentList = "/qn /l*v $logFile"
    Execute-Program -filePath $filePath -argumentList $argumentList

    if (Get-Content $logFile | Select-String -quiet "completed successfully")
    {
		$message = "ConfigurationLogging PowerShell Snapin Installation successfully Completed."
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
		Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-ConfigurationLoggingPSSnapin" -newValue "1"
    }
    else
    {
		$message = "ERROR: Installing ConfigurationLogging PowerShell Snapin Failed."
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
		Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-ConfigurationLoggingPSSnapin" -newValue "0"
        throw $message
    }

	if($network)
	{
		Disconnect-NetShare -drive $DriveLetter
	}
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Install ConfigPSSnapin
.PARAMETER sectionName
	Specifies to which Section status should get written to.
#>
function Install-ConfigPSSnapin([Parameter(Mandatory=$true)] [string] $sectionName)
{
	$functionName = "Install-ConfigPSSnapin"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	
    # If operation has already been completed; then just skip it and exit function
    $installed = Get-Parameter -configFile $global:paramFile -section "Server Status" -key "Install-ConfigPSSnapin"
    if("1" -eq $installed)
    {
        $message = "Installation of ConfigPSSnapin has already been previously completed; skipping operation."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        return
    }
    
	$DriveLetter  = "R:"
	$BaseLocation = Get-Parameter -configFile $paramFile -section "ConfigurationPSSnapin Installer" -key "ConfigLocation"
	$network = $BaseLocation.StartsWith("\\")
	if($network)
	{
		$user     = Get-Parameter -configFile $global:paramFile -section "ConfigurationPSSnapin Installer" -key "ConfigNetUser"
		$password = Get-Parameter -configFile $global:paramFile -section "ConfigurationPSSnapin Installer" -key "ConfigNetPassword"
		Connect-NetShare -drive $DriveLetter -share $BaseLocation -username $user -password $password | Out-Null
		$BaseLocation = $DriveLetter
	}
	
	$Installer = Get-Parameter -configFile $paramFile -section "ConfigurationPSSnapin Installer" -key "ConfigInstallerX86"
	if (Is-64bit) 
	{
		$Installer = Get-Parameter -configFile $paramFile -section "ConfigurationPSSnapin Installer" -key "ConfigInstallerX64"
	}
	
	$filePath     = "`"$BaseLocation\$Installer`""
    $logFile      = "$global:logDir\ConfigSnapin.log"
    $argumentList = "/qn /l*v $logFile"
    Execute-Program -filePath $filePath -argumentList $argumentList

    if (Get-Content $logFile | Select-String -quiet "completed successfully")
    {
        $message = "Configuration PowerShell Snapin Installation successfully Completed." 
        Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-ConfigPSSnapin" -newValue "1"
    }
    else
    {
        $message = "ERROR: Installing Configuration PowerShell Snapin Failed."
        Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-ConfigPSSnapin" -newValue "0"
        throw $message
    }

	if($network)
	{
		Disconnect-NetShare -drive $DriveLetter
	}
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Install XDBrokerPSSnapin
.PARAMETER sectionName
	Specifies to which Section status should get written to.
#>
function Install-XDBrokerPSSnapin([Parameter(Mandatory=$true)] [string] $sectionName)
{
	$functionName = "Install-XDBrokerPSSnapin"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	
    # If operation has already been completed; then just skip it and exit function
    $installed = Get-Parameter -configFile $global:paramFile -section "Server Status" -key "Install-XDBrokerPSSnapin"
    if("1" -eq $installed)
    {
        $message = "Installation of XDBrokerPSSnapin has already been previously completed; skipping operation."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        return
    }
    
	$DriveLetter  = "R:"
	$BaseLocation = Get-Parameter -configFile $paramFile -section "XDBrokerPSSnapin" -key "XDBrokerLocation"
	$network = $BaseLocation.StartsWith("\\")
	if($network)
	{
		$user     = Get-Parameter -configFile $global:paramFile -section "XDBrokerPSSnapin" -key "XDBrokerNetUser"
		$password = Get-Parameter -configFile $global:paramFile -section "XDBrokerPSSnapin" -key "XDBrokerNetPassword"
		Connect-NetShare -drive $DriveLetter -share $BaseLocation -username $user -password $password | Out-Null
		$BaseLocation = $DriveLetter
	}
	
	$Installer = Get-Parameter -configFile $paramFile -section "XDBrokerPSSnapin" -key "XDBrokerInstallerX86"
	if (Is-64bit) 
	{
		$Installer = Get-Parameter -configFile $paramFile -section "XDBrokerPSSnapin" -key "XDBrokerInstallerX64"
	}
	
	$filePath     = "`"$BaseLocation\$Installer`""
    $logFile      = "$global:logDir\BrokerSnapin.log"
    $argumentList = "/qn /l*v $logFile"
    Execute-Program -filePath $filePath -argumentList $argumentList

    if (Get-Content $logFile | Select-String -quiet "completed successfully")
    {
		$message = "XD Broker PowerShell Snapin Installation successfully Completed." 
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
		Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-XDBrokerPSSnapin" -newValue "1"
    }
    else
    {
		$message = "ERROR: Installing XD Broker PowerShell Snapin Failed."
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
		Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-XDBrokerPSSnapin" -newValue "0"
        throw $message
    }

	if($network)
	{
		Disconnect-NetShare -drive $DriveLetter
	}
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Install XDHostPSSnapin
.PARAMETER sectionName
	Specifies to which Section status should get written to.
#>
function Install-XDHostPSSnapin([Parameter(Mandatory=$true)] [string] $sectionName)
{
	$functionName = "Install-XDHostPSSnapin"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	
    # If operation has already been completed; then just skip it and exit function
    $installed = Get-Parameter -configFile $global:paramFile -section "Server Status" -key "Install-XDHostPSSnapin"
    if("1" -eq $installed)
    {
        $message = "Installation of XDHostPSSnapin has already been previously completed; skipping operation."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        return
    }
    
	$DriveLetter  = "R:"
	$BaseLocation = Get-Parameter -configFile $paramFile -section "XDHostPSSnapin" -key "XDHostLocation"
	$network = $BaseLocation.StartsWith("\\")
	if($network)
	{
		$user     = Get-Parameter -configFile $global:paramFile -section "XDHostPSSnapin" -key "XDHostNetUser"
		$password = Get-Parameter -configFile $global:paramFile -section "XDHostPSSnapin" -key "XDHostNetPassword"
		Connect-NetShare -drive $DriveLetter -share $BaseLocation -username $user -password $password | Out-Null
		$BaseLocation = $DriveLetter
	}
	
	$Installer = Get-Parameter -configFile $paramFile -section "XDHostPSSnapin" -key "XDHostInstallerX86"
	if (Is-64bit) 
	{
		$Installer = Get-Parameter -configFile $paramFile -section "XDHostPSSnapin" -key "XDHostInstallerX64"
	}
	
	$filePath     = "`"$BaseLocation\$Installer`""
    $logFile      = "$global:logDir\HostSnapin.log"
    $argumentList = "/qn /l*v $logFile"
    Execute-Program -filePath $filePath -argumentList $argumentList

    if (Get-Content $logFile | Select-String -quiet "completed successfully")
    {
		$message = "XD Host PowerShell Snapin Installation successfully Completed." 
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
		Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-XDHostPSSnapin" -newValue "1"
    }
    else
    {
		$message = "ERROR: Installing XD Host PowerShell Snapin Failed."; 
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
		Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-XDHostPSSnapin" -newValue "0"
        throw $message
    }

	if($network)
	{
		Disconnect-NetShare -drive $DriveLetter
	}
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Setup License; copy to the appropriate directory.
.PARAMETER sectionName
	Specifies to which Section status should get written to.
#>
function Setup-License([Parameter(Mandatory=$true)] [string] $sectionName)
{
	$functionName = "Setup-License"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	
    # If operation has already been completed; then just skip it and exit function
    $installed = Get-Parameter -configFile $global:paramFile -section "Server Status" -key "Setup-License"
    if("1" -eq $installed)
    {
        $message = "Setup license has already been previously completed; skipping operation."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        return
    }
    
	$PFDir = "${env:ProgramFiles}"
	if (Is-64bit) 
	{ 
		$PFDir = "${env:ProgramFiles(x86)}" 
	} 
	
    $DriveLetter = "R:"
	$BaseLocation= Get-Parameter -configFile $paramFile -section "License files" -key "CTXLicFileLocation"
	$CTXLicFile  = Get-Parameter -configFile $paramFile -section "License files" -key "CTXLicFile"
	$CTXLicFileD = Get-Parameter -configFile $paramFile -section "License files" -key "CTXLicFileD"
    
    $network = $BaseLocation.StartsWith("\\")
    if ($network)
    {
    	$user        = Get-Parameter -configFile $paramFile -section "License files" -key "CTXLicFileNetUser"
    	$password    = Get-Parameter -configFile $paramFile -section "License files" -key "CTXLicFileNetPassword"
        if ( ("donotmap" -eq $password) -or ("donotmap" -eq $user) )
        {
            # do not map network drive
            $network = $false
        }
        else
        {
       		Connect-NetShare -drive $DriveLetter -share $BaseLocation -username $user -password $password | Out-Null
    		$BaseLocation = $DriveLetter
        }
    }    

	$message =  "EXECUTE: Copy $BaseLocation\$CTXLicFile $PFDir\Citrix\Licensing\MyFiles"
	Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
	Copy $BaseLocation\$CTXLicFile $PFDir\Citrix\Licensing\MyFiles
	
	$message = "EXECUTE: Copy $BaseLocation\$CTXLicFileD $PFDir\Citrix\Licensing\MyFiles"
	Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
	Copy $BaseLocation\$CTXLicFileD $PFDir\Citrix\Licensing\MyFiles
	
	if($network)
	{
		Disconnect-NetShare -drive $DriveLetter
	}

	$message = "EXECUTE: Set-Service `"Citrix Licensing`" -startuptype manual"
	Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
	Set-Service "Citrix Licensing" -startuptype manual
	
	$message = "EXECUTE: Stop-Service `"Citrix Licensing`""
	Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
	Stop-Service "Citrix Licensing"
	
	$message = "EXECUTE: sleep -Seconds 5"
	Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
	sleep -Seconds 5
	
	$message = "EXECUTE: Start-Service `"Citrix Licensing`""
	Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
	Start-Service "Citrix Licensing"
	
	$message = "EXECUTE: `Get-Service `"Citrix Licensing`""
	Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
	$status = Get-Service "Citrix Licensing"# | Format-Table -Property Status
	
	if($status.Status -ne “Running”)
	{
		$message = "ERROR: Failed to start `"Citrix Licensing`""
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
		Set-Parameter -configFile $global:paramFile -section $sectionName -key "Setup-License" -newValue "0"
        throw $message
	}
	$message = "Successfully started `"Citrix Licensing`""
	Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
	Set-Parameter -configFile $global:paramFile -section $sectionName -key "Setup-License" -newValue "1"
	
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Install CTX License Server.
.PARAMETER sectionName
	Specifies to which Section status should get written to.
#>
function Install-CTXLicenseServer([Parameter(Mandatory=$true)] [string] $sectionName)
{
	$functionName = "Install-CTXLicenseServer"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	
    # If operation has already been completed; then just skip it and exit function
    $installed = Get-Parameter -configFile $global:paramFile -section "Server Status" -key "Install-CTXLicenseServer"
    if("1" -eq $installed)
    {
        $message = "Installation of CTX License Server has already been previously completed; skipping operation."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        return
    }
    
	$DriveLetter  = "R:"
	$BaseLocation = Get-Parameter -configFile $paramFile -section "CTX License Installer" -key "CTXLicLocation"
	$network = $BaseLocation.StartsWith("\\")
	if($network)
	{
		$user     = Get-Parameter -configFile $global:paramFile -section "CTX License Installer" -key "CTXLicNetUser"
		$password = Get-Parameter -configFile $global:paramFile -section "CTX License Installer" -key "CTXLicNetPassword"
		Connect-NetShare -drive $DriveLetter -share $BaseLocation -username $user -password $password | Out-Null
		$BaseLocation = $DriveLetter
	}
	
	$Installer = Get-Parameter -configFile $paramFile -section "CTX License Installer" -key "CTXLicInstaller"
	
	# execute installation
	$filePath     = "msiexec.exe"
    $logFile      = "$global:logDir\CTXlic.log"
    $argumentList = "/I `"$BaseLocation\$Installer`" ctx_web_server=`"IIS`" /l*v $logFile /q"
    Execute-Program -filePath $filePath -argumentList $argumentList

    if (Get-Content $logFile | Select-String -quiet "completed successfully")
    {
        $message = "Citrix License Server Installation completed successfully."
        Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
		Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-CTXLicenseServer" -newValue "1"
    }
    else
    {
        $message = "Citrix License Server Installation FAILED."
        Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
		Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-CTXLicenseServer" -newValue "0"
        throw $message
    }
	
	if($network)
	{
		Disconnect-NetShare -drive $DriveLetter
	}

	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Install Signing Certificates.
.PARAMETER sectionName
	Specifies to which Section status should get written to.
#>
function Install-SigningCerts([Parameter(Position=0,Mandatory=$true)] [string]$sectionName)
{
	$functionName = "Install-SigningCerts"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	
    # If operation has already been completed; then just skip it and exit function
    $installed = Get-Parameter -configFile $global:paramFile -section "Server Status" -key "Install-SigningCerts"
    if("1" -eq $installed)
    {
        $message = "Installation of signing certs has already been previously completed; skipping operation."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        return
    }
    
	$DriveLetter  = "R:"
	$BaseLocation = Get-Parameter -configFile $paramFile -section "Signing Certificates" -key "SignCertsLocation"
	$network = $BaseLocation.StartsWith("\\")
	if($network)
	{
		$user     = Get-Parameter -configFile $global:paramFile -section "Signing Certificates" -key "SignCertsNetUser"
		$password = Get-Parameter -configFile $global:paramFile -section "Signing Certificates" -key "SignCertsNetPassword"
		Connect-NetShare -drive $DriveLetter -share $BaseLocation -username $user -password $password | Out-Null
		$BaseLocation = $DriveLetter
	}

	#switch zone check off (don't prompt me to run when an msi is executed)
	$env:SEE_MASK_NOZONECHECKS = 1

	# todo: parameterize the use of $BaseLocation below
	# otherwise this function will crash when using non-network location (no such drive as "R:")
	# install certificates to local machine	
	R:\certmgr.exe -add R:\signing330.cer -s -r localMachine trustedpublisher|Out-Null
	R:\certmgr.exe -add R:\signing827.cer -s -r localMachine trustedpublisher|Out-Null
	R:\certmgr.exe -add R:\PVS-Cert.cer -s -r localMachine trustedpublisher|Out-Null
	R:\certmgr.exe -add R:\Solera3312014.cer -s -r localMachine trustedpublisher|Out-Null
    R:\certmgr.exe -add R:\signing8242014.cer -s -r localMachine trustedpublisher|Out-Null	
	
	# we are assuming this always succeeds
	Log-MessageVerbose -message "Assuming that Install-SigningCerts succeeded." -logFile $global:messagesLog -thisfile $global:thisFile
	Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-SigningCerts" -newValue "1"
	
	if($network)
	{
		Disconnect-NetShare -drive $DriveLetter
	}

	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Return version, if SQL2005 is installed
#>
function Is-SQL2005Installed
{
	$path1 = Test-Path "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\90\Tools\ClientSetup\CurrentVersion"
	$value1 = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\90\Tools\ClientSetup\CurrentVersion").CurrentVersion
	if ($path1 -and $value1)
    {
        return $value1
    }
    return $false
}


<#
.SYNOPSIS
 	Return version, if SQL2008 is installed
#>
function Is-SQL2008Installed
{
	$path2 = Test-Path "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\100\Tools\ClientSetup\CurrentVersion"
	$value2 = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\100\Tools\ClientSetup\CurrentVersion").CurrentVersion
	if ($path2 -and $value2)
    {
        return $value2
    }
    return $false
}


<#
.SYNOPSIS
 	Return base path to SQLCMD.EXE
#>
function GetPath-SQLCMD
{
    if(Is-SQL2005Installed)
    {
        $path = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\90\Tools\ClientSetup").Path
        $path = $path -replace “.$” # remove the last backslash character
        return $path
    }
    
    if(Is-SQL2008Installed)
    {
        $path = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\100\Tools\ClientSetup").Path
        $path = $path -replace “.$” # remove the last backslash character
        return $path
    }
    
    return $false
}


<#
.SYNOPSIS
 	Install PVS Device Software
.PARAMETER sectionName
	Specifies to which Section status should get written to.
#>
function Install-MSSQL2008express([Parameter(Position=0,Mandatory=$true)] [string]$sectionName)
{
	$functionName = "Install-MSSQL2008express"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	
	$value1 = Is-SQL2005Installed
	$value2 = Is-SQL2008Installed
	$DriveLetter = "R:"	
	
	if (($value1) -or ($value2))
	{
		if($value1)
		{
			$message = "Microsoft SQL [$value1] is already installed. Skipping installation!"
			Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
		}
		else
		{
			$message = "Microsoft SQL [$value2] is already installed. Skipping installation!"
			Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
		}
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-MSSQL2008express" -newValue "1"
	}
	else
	{
		$DriveLetter = "R:"
		$BaseLocation = Get-Parameter -configFile $paramFile -section "MSSQL2008xpress Installer" -key "MSSQLLocation"
		$network = $BaseLocation.StartsWith("\\")
		if($network)
		{
			$user     = Get-Parameter -configFile $global:paramFile -section "MSSQL2008xpress Installer" -key "MSSQLNetUser"
			$password = Get-Parameter -configFile $global:paramFile -section "MSSQL2008xpress Installer" -key "MSSQLNetPassword"
            if ( ("donotmap" -eq $password) -or ("donotmap" -eq $user) )
            {
                # do not map network drive
                $network = $false
            }
            else
            {
    			Connect-NetShare -drive $DriveLetter -share $BaseLocation -username $user -password $password | Out-Null
    			$BaseLocation = $DriveLetter
            }
		}
		
		$DBAdminUser     = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "dbAdminUser" #"$env:USERDOMAIN\$env:USERNAME"
		$DBAdminPassword = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "dbAdminPassword" 
		$message = "EXECUTE: ExecuteInstall-SQL2008x -SqlLocation $BaseLocation -DBAdminUser $DBAdminUser -DBAdminPassword $DBAdminPassword -configIniDir $global:logDir -sectionName $sectionName"
		Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
		ExecuteInstall-SQL2008x -SqlLocation $BaseLocation -DBAdminUser $DBAdminUser -DBAdminPassword $DBAdminPassword -configIniDir $global:logDir -sectionName $sectionName

		if($network)
		{
			Disconnect-NetShare -drive $DriveLetter
		}
	}

	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Sets the writeCache type on a specified vDisk
.PARAMETER writeCacheType
	writeCacheType mode to use:  0 (Private), (other values are standard image) 1 (Cache on Server), 3 (Cache in Device RAM), 
	4 (Cache on Device Hard Drive), 6 (Device RAM Disk) or 7 (Cache on Server Persistent). Min=0, Max=8,
.PARAMETER vDiskName
	Name of disk to to modify writeCacheType on
.PARAMETER sectionName
	Specifies to which Section status should get written to.
.PARAMETER siteName
	Name of site specified collection resides in
.PARAMETER storeName
	Name of store the specified vDisk resides in
.PARAMETER writecachesize
	writecachesize in MB - Only used when writeCache is 3 (Cache in Device RAM)
#>
function Set-WriteCacheType(
			[Parameter(Position=0,Mandatory=$true)] [string]$writeCacheType,
			[Parameter(Position=1,Mandatory=$true)] [string]$vDiskName,
			[Parameter(Position=2,Mandatory=$true)] [string]$sectionName,
            [Parameter(Position=3,Mandatory=$false)] [string]$siteName="ST_Site",
			[Parameter(Position=4,Mandatory=$false)] [string]$storeName="ST_Store",
			[Parameter(Position=5,Mandatory=$false)] [string]$writecachesize="512")
{
	$functionName = "Set-WriteCacheType"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	
    # If operation has already been completed; then just skip it and exit function
    $installed = Get-Parameter -configFile $global:paramFile -section $sectionName -key "Set-WriteCacheType"
    if("1" -eq $installed)
    {
        $message = "Set WriteCacheType has already been previously completed; skipping operation."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        return
    }
    
	# Note: ASSUMPTION is that "Register-PVSMcliPSSnapin" has already been called by this point in time.	
	$message = "Setting $vDiskName to $writeCacheType"
	Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
	if ($writeCacheType -eq "3")
	{   
		$error.Clear()
		try
        {
            $message = "EXECUTE: mcli-set disk -p disklocatorname=$vDiskName,sitename=$siteName,storename=$storeName -r writecachesize=$writecachesize,writecacheType=$writeCacheType"
            Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
            mcli-set disk -p disklocatorname=$vDiskName,sitename=$siteName,storename=$storeName -r writecachesize=$writecachesize,writecacheType=$writeCacheType
        }
		catch [Exception] 
		{
			$message = "$($_.Exception.Message)"
			Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
            Set-Parameter -configFile $global:paramFile -section $sectionName -key "Set-WriteCacheType" -newValue "0"
			throw $message
		}
	
		$result = Return-MAPIError
		if ($result -ne "Success") 
		{ 
			$message = "Setting $vDiskName to $mode Failed: $result"
			Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
            Set-Parameter -configFile $global:paramFile -section $sectionName -key "Set-WriteCacheType" -newValue "0"
			throw $message
		}
		else 
		{ 
			$message = "Setting $vDiskName to $mode Succeeded"
			Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
            Set-Parameter -configFile $global:paramFile -section $sectionName -key "Set-WriteCacheType" -newValue "1"
		}
	}
	else 
	{   
		$error.Clear()
		try
        {        
            $message = "EXECUTE: mcli-set disk -p disklocatorname=$vDiskName,sitename=$siteName,storename=$storeName -r writecacheType=$writeCacheType"
            Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
            mcli-set disk -p disklocatorname=$vDiskName,sitename=$siteName,storename=$storeName -r writecacheType=$writeCacheType
        }
		catch [Exception] 
		{
			$message = "$($_.Exception.Message)"
			Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
            Set-Parameter -configFile $global:paramFile -section $sectionName -key "Set-WriteCacheType" -newValue "0"
			throw $message
		}
	
		$result = Return-MAPIError
		if ($result -ne "Success") 
		{ 
			$message = "Setting $vDiskName to $mode Failed: $result"
			Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
            Set-Parameter -configFile $global:paramFile -section $sectionName -key "Set-WriteCacheType" -newValue "0"
			throw $message
		}
		else 
		{ 
			$message = "Setting $vDiskName to $mode Succeeded"
			Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
            Set-Parameter -configFile $global:paramFile -section $sectionName -key "Set-WriteCacheType" -newValue "1"
		}
	}
	
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Collect and log some machine information
.PARAMETER sectionName
	Specifies to which Section the OS info should get written to.
#>
function Collect-MachineInfo([Parameter(Position=0,Mandatory=$true)] [string]$sectionName)
{
    $osCaption = (Get-WmiObject -class Win32_OperatingSystem).Caption
    $osArch    = (Get-WmiObject -class Win32_OperatingSystem).OSArchitecture
    $osCaption = $osCaption + " " + $osArch
    $csName    = (Get-WmiObject -class Win32_OperatingSystem).CSName
    $domain    = (Get-WmiObject Win32_ComputerSystem).Domain
    $username  = (Get-WmiObject Win32_ComputerSystem).UserName

    Log-Message -message "OS Caption is [$osCaption]" -logFile $global:messagesLog -thisfile $global:thisFile
    Log-Message -message "Hostname is   [$csName]" -logFile $global:messagesLog -thisfile $global:thisFile
    Log-Message -message "Domain is     [$domain]" -logFile $global:messagesLog -thisfile $global:thisFile
    Log-Message -message "Username is   [$username]" -logFile $global:messagesLog -thisfile $global:thisFile
    
    Set-Parameter -configFile $global:paramFile -section $sectionName -key "OperatingSystemCaption" -newValue $osCaption
    Set-Parameter -configFile $global:paramFile -section $sectionName -key "hostname" -newValue $csName
    Set-Parameter -configFile $global:paramFile -section $sectionName -key "domain" -newValue $domain
    Set-Parameter -configFile $global:paramFile -section $sectionName -key "username" -newValue $username
}


<#
.SYNOPSIS
 	Executes a program
.PARAMETER filePath
	Full Path to installer 
.PARAMETER argumentList
	Arguments for installer 
#>
function Execute-Program( [Parameter(Position=0,Mandatory=$true)] [string]$filePath,
                          [Parameter(Position=1,Mandatory=$true)] [string]$argumentList)
{
	$functionName = "Execute-Program"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
    $message      = "EXECUTE: Execute-Program -filePath $filePath -argumentList $argumentList"
	Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    
	try
	{
		Start-Process -FilePath $filePath -ArgumentList $argumentList  -Wait
	}
	catch [Exception]
	{
		$message = "$($_.Exception.Message)"
		Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        throw $message
	}

	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Install PVS Device Software
.PARAMETER sectionName
	Specifies to which Section status should get written to.
#>
function Install-PVSDevice([Parameter(Position=0,Mandatory=$true)] [string]$sectionName)
{
	$functionName = "Install-PVSDevice"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	$DriveLetter = "R:"
	$BaseLocation = Get-Parameter -configFile $paramFile -section "PVS Device Installer" -key "pvsDeviceRoot"
	$network = $BaseLocation.StartsWith("\\")
	if($network)
	{
		$user     = Get-Parameter -configFile $global:paramFile -section "PVS Device Installer" -key "pvsDeviceNetUser"
		$password = Get-Parameter -configFile $global:paramFile -section "PVS Device Installer" -key "pvsDeviceNetPassword"
		Connect-NetShare -drive $DriveLetter -share $BaseLocation -username $user -password $password | Out-Null
		$BaseLocation = $DriveLetter
	}
    
    $installer = Get-Parameter -configFile $global:paramFile -section "PVS Device Installer" -key "pvsDeviceX86"
	if (Is-64Bit)
	{ 
        $installer = Get-Parameter -configFile $global:paramFile -section "PVS Device Installer" -key "pvsDeviceX64" 
    }
    
    $filePath     = "`"$BaseLocation\$installer`""
    $logFile      = "$global:logDir\PVSDevice.log"
    $argumentList = "/s /v`"/qn /l*v $logFile /norestart`""
    Execute-Program -filePath $filePath -argumentList $argumentList
    
    if (Get-Content $logFile | Select-String -quiet "completed successfully")
    {
        $message = "PVS Device software installed successfully."
        Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-PVSDevice" -newValue "1"
    }
    else
    {
        $message = "PVS Device software install FAILED."
        Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Install-PVSDevice" -newValue "0"
        throw $message
    }
    
	if($network)
	{
		Disconnect-NetShare -drive $DriveLetter
	}
    
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
    Fix boot strap.
#>
function Fix-BootStrap
{	
	$functionName = "Fix-BootStrap"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
    
    Register-PVSMcliPSSnapin

    $dbServer       = Get-Parameter -configFile $global:paramFile -section "PVS Database" -key "dbServer"
    $PVSStreamingIP = Get-Parameter -configFile $global:paramFile -section "PVS Console Wizard" -key "PVSStreamingIP"

    $message = "EXECUTE: mcli-set ServerBootstrap -p serverName=$dbServer,name=ardbp32.bin -r bootserver1_Ip=$PVSStreamingIP"
    Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
	mcli-set ServerBootstrap -p serverName=$dbServer,name=ardbp32.bin -r bootserver1_Ip=$PVSStreamingIP
    
    $message = "EXECUTE: mcli-set ServerBootstrap -p serverName=$dbServer,name=ardbp32.bin -r verboseMode=1"
    Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    mcli-set ServerBootstrap -p serverName=$dbServer,name=ardbp32.bin -r verboseMode=1

    $message = "EXECUTE: mcli-set farm -r licenseServer=$dbServer,licenseServerPort=27000"
    Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
	mcli-set farm -r licenseServer=$dbServer,licenseServerPort=27000

    $message = "EXECUTE: mcli-set server -p serverName=$dbServer -r eventLoggingEnabled=1,loglevel=5"
    Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
	mcli-set server -p serverName=$dbServer -r eventLoggingEnabled=1,loglevel=5 
    
	#should probably restart streamService
    Restart-PVSServices    
      
	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
    Test registry key.
#>
function Test-Key([string]$path, [string]$key)
{
    if(!(Test-Path $path)) { return $false }
    if ((Get-ItemProperty $path).$key -eq $null) { return $false }
    return $true
}


<#
.SYNOPSIS
    Get installed versions of NET Framework
#>
function Get-Framework-Versions
{
    $installedFrameworks = @()
    if(Test-Key "HKLM:\Software\Microsoft\.NETFramework\Policy\v1.0" "3705") { $installedFrameworks += "1.0" }
    if(Test-Key "HKLM:\Software\Microsoft\NET Framework Setup\NDP\v1.1.4322" "Install") { $installedFrameworks += "1.1" }
    if(Test-Key "HKLM:\Software\Microsoft\NET Framework Setup\NDP\v2.0.50727" "Install") { $installedFrameworks += "2.0" }
    if(Test-Key "HKLM:\Software\Microsoft\NET Framework Setup\NDP\v3.0\Setup" "InstallSuccess") { $installedFrameworks += "3.0" }
    if(Test-Key "HKLM:\Software\Microsoft\NET Framework Setup\NDP\v3.5" "Install") { $installedFrameworks += "3.5" }
    if(Test-Key "HKLM:\Software\Microsoft\NET Framework Setup\NDP\v4\Client" "Install") { $installedFrameworks += "4.0c" }
    if(Test-Key "HKLM:\Software\Microsoft\NET Framework Setup\NDP\v4\Full" "Install") { $installedFrameworks += "4.0" }   
     
    return $installedFrameworks
}


<#
.SYNOPSIS
 	Builds a vDisk image (assumes disk is in R/W mode)
.PARAMETER sectionName
	Specifies to which Section status should get written to.
.PARAMETER partitionsToImage
	A string containing the list of partitions to image in the form of "c: d: e:"
#>
function Build-PVSVdiskP2PVS([Parameter(Position=0,Mandatory=$true)]  [string]$sectionName,
                             [Parameter(Position=1,Mandatory=$false)] [string]$partitionsToImage="c:")
{   
	$functionName = "Build-PVSVdiskP2PVS"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile

	$message = "Converting local disk to vDisk: Building vdisk (p2pvs.exe)"
	Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    
    $Path2ProgData = "$env:SystemDrive\Documents and Settings\All Users\Application Data"
	if ($env:ProgramData -ne $null) 
    {
        $Path2ProgData=$env:ProgramData 
    } 

	$filePath     = "$env:SystemDrive\Program Files\Citrix\Provisioning Services\P2PVS.exe"
    $logFile      = "$Path2ProgData\citrix\P2PVS\P2PVS.txt"
    $argumentList = "P2Pvs $partitionsToImage /e /AutoFit"
    Execute-Program -filePath $filePath -argumentList $argumentList
	
	if (Get-Content $logFile | Select-String -quiet "Conversion was successful!")
	{ 
        $message =  "Converting local disk to vDisk: Conversion successfully Completed."         
        Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Build-PVSVdiskP2PVS" -newValue "1"
    }
	else
    {
        $message = "Converting local disk to vDisk: Conversion Failed" 
        Log-Message -message $message -logFile $global:messagesLog -thisfile $global:thisFile
        Set-Parameter -configFile $global:paramFile -section $sectionName -key "Build-PVSVdiskP2PVS" -newValue "0"
        throw $message
    }

    Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}


<#
.SYNOPSIS
 	Prints out the status of Citrix Services.
#>
function Get-StatusCitrixServices
{
	$functionName = "Get-StatusCitrixServices"
	Log-MessageVerbose -message "Entering function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
	try 
    {
        $message = "EXECUTE: Get-Service -DisplayName Citrix*"
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
		$output = Get-Service -DisplayName Citrix* | Out-String
	}
	catch 
    { 
        $message = "Failed to get status of Citrix services."
        Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile
    	Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
        return
    }
	
    $message = "Printing status of Citrix services..."
    Log-MessageVerbose -message $message -logFile $global:messagesLog -thisfile $global:thisFile    
    Log-MessageVerbose -message $output -logFile $global:messagesLog -thisfile $global:thisFile
    Log-MessageVerbose -message "Leaving function $functionName" -logFile $global:messagesLog -thisfile $global:thisFile
}
