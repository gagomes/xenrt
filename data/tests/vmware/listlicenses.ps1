Add-PSSnapIn vm*

$vcenter = $args[0]
$vuser = $args[1]
$vpassword = $args[2]
$datacenter = $args[3]

Connect-ViServer -Server $vcenter -User $vuser -Password $vpassword

$LicMan = Get-View ((Get-View ServiceInstance).Content.LicenseManager)

$LicMan.Licenses | Select-Object LicenseKey,EditionKey,Total,Used | Export-CSV "c:\vmware\licenses.csv" -notype
