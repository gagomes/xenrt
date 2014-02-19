
$VerbosePreference = "Continue"
Write-Verbose "START"

Write-Verbose "Getting current CLR being used by PowerShell..."
$PSVersionTable

if (($($PSVersionTable).CLRVersion).Major -eq 4)
{
	Write-Verbose "CLR already set to 4.x, skipping..."
	exit
}

Write-Verbose "Setting CLR to 4.x..."
$config_text = @"
<?xml version="1.0"?> 
<configuration> 
    <startup useLegacyV2RuntimeActivationPolicy="true"> 
        <supportedRuntime version="v4.0.30319"/> 
        <supportedRuntime version="v2.0.50727"/> 
    </startup> 
</configuration>
"@

$config_text| Out-File $pshome\powershell.exe.config
$config_text| Out-File $pshome\powershell_ise.exe.config


Write-Verbose "END"
