Import-Module Hyper-V

$ethernet = Get-NetAdapter | where {$_.MacAddress -eq $args[0]}
New-VMSwitch -Name externalSwitch -NetAdapterName $ethernet.Name -AllowManagementOS $true -Notes 'Parent OS, VMs, LAN'
