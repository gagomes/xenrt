@echo off
REM SYNOPSIS:
REM    Startup script (V1.3) should be placed in the windows startup folder 
REM    Copyright (c) 2011 UK Test Automation, Citrix Systems UK Ltd.
REM DETAIL:
REM    * Executes post-login, only progresses if the remoting client is not installed.
REM    * Validates the network is up then copies and executes a automation bootstrap script

echo check if jonas is installed
IF EXIST "%PROGRAMFILES%\Jonas" goto end 2>nul

REM set the remote execution policy - this is essential for any powershell scripting
echo setting powershell execution policy
powershell set-executionpolicy remotesigned

echo waiting for valid network configuration...
REM Validates DNSDomain is set on at least one interface (DHCP should supply this).
powershell -command "while(-not ($t = gwmi Win32_NetworkAdapterConfiguration | where-object {!$_.DNSDomain -eq ''})){start-sleep 1; write-host 'waiting for valid nework configuration'};$t"

echo getting automatin boot strap script
set bootstrapfullpath=\\controller\public\bootstrap.ps1
powershell -command "copy-item %bootstrapfullpath% $env:temp -force" -verbose

echo executing automation boot strap script...
powershell -file "%temp%\bootstrap.ps1"