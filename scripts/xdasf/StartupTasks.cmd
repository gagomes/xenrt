@echo off
REM SYNOPSIS:
REM    Startup script (V1.3) should be placed in the windows startup folder 
REM    Copyright (c) 2011 UK Test Automation, Citrix Systems UK Ltd.
REM DETAIL:
REM    * Executes post-login, only progresses if the remoting client is not installed.
REM    * Validates the network is up then copies and executes a automation bootstrap script

set BOOTDIR="C:\bootstrap"

echo.

echo Forcing a w32time sync

w32tm /resync /rediscover /nowait


@REM echo check if Remoting Agent is installed
IF EXIST "%PROGRAMFILES%\Jonas" goto END 2>nul

REM set the remote execution policy - this is essential for any powershell scripting
echo.
echo setting powershell execution policy 
powershell set-executionpolicy remotesigned 

echo.
echo Starting controller discovery 
powershell -file "%BOOTDIR%\Start-AsyncAsfDiscovery.ps1" 

echo.
echo "bootstrap script finished" 

:END