Import-Module Hyper-V

$ethernet = Get-NetAdapter -Name Ethernet
New-VMSwitch -Name externalSwitch -NetAdapterName $ethernet.Name -AllowManagementOS $true -Notes 'Parent OS, VMs, LAN'
