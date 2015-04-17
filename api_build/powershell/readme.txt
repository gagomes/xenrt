XenRT PowerShell Module
=======================

This module requires at least PowerShell 3.0

Unzip the archive into %USERPROFILE%\Documents\WindowsPowerShell\Modules

e.g. you should end up with the files

c:\Users\MyUser\Documents\WindowsPowerShell\Modules\XenRT\XenRT.psm1 and c:\Users\MyUser\Documents\WindowsPowerShell\Modules\XenRT\XenRT.psd1

Then run Get-Help XenRT to see the list of functions. You need to start by running

Connect-XenRT -ApiKey <XenRT_API_Key>