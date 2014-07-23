Add-PSSnapIn vm*

$vcenter = $args[0]
$vuser = $args[1]
$vpassword = $args[2]
$hostname = $args[3]
$lic = $args[4]

Connect-ViServer -Server $vcenter -User $vuser -Password $vpassword

$LicMan = Get-View ((Get-View ServiceInstance).Content.LicenseManager)

$LicAssign = Get-View -Id $LicMan.LicenseAssignmentManager

$hostobj = Get-View -ViewType "HostSystem" -Filter @{Name=$hostname} -Property Config.Host

$LicAssign.UpdateAssignedLicense($hostObj.Config.Host.Value, $lic, $null)
