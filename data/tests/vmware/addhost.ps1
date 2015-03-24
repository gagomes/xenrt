Add-PSSnapIn vm*

$vcenter = $args[0]
$vuser = $args[1]
$vpassword = $args[2]
$datacenter = $args[3]
$cluster = $args[4]
$hostaddr = $args[5]
$huser = $args[6]
$hpassword = $args[7]
$dvs = $args[8]
$switchname = "DVS-1"

Write-Output Connecting to $vcenter

Connect-ViServer -Server $vcenter -User $vuser -Password $vpassword

Write-Output Checking whether Datacenter Exists

if (!(Get-DataCenter $datacenter)) {
    Write-Output Datacenter does not exist, creating
    New-DataCenter -Name $datacenter -Location (Get-Folder -NoRecursion)
}

Write-Output Checking whether Cluster Exists
if (!(Get-Cluster $cluster)) {
    Write-Output Cluster does not exist, creating
    New-Cluster -Name $cluster -Location (Get-DataCenter $datacenter)
}

if (Get-DataCenter -VMHost $hostaddr) {
    Get-DataCenter -VMHost $hostaddr | Remove-DataCenter -Confirm:$false
}

Write-Output Adding Host
Add-VMHost -Name $hostaddr -Location (Get-Cluster $cluster) -Force -User $huser -Password $hpassword

Get-VMHostNetworkAdapter -VMKernel | where { $_.IP -eq $hostaddr} | Set-VMHostNetworkAdapter -VMotionEnabled:$true -Confirm:$false

Get-VMHost -Location $datacenter | Export-CSV c:\vmware\$datacenter.csv -notype


if ($dvs -eq "yes") {
	New-VDSwitch -Name $switchname -Location $datacenter
	Get-VDSwitch -Name $switchname | Add-VDSwitchVMHost -VMHost $hostaddr
}


