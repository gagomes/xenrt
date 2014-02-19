REM
REM XenRT: Test harness for Xen and the XenServer product family
REM
REM XML-RPC test execution daemon installer
REM
REM Copyright (c) 2007 XenSource, Inc. All use and distribution of this
REM copyrighted material is governed by and subject to terms and
REM conditions as licensed by XenSource, Inc. All other rights reserved.
REM

REM Copy the scripts to c:\
copy %systemdrive%\Install\execdaemon.py %systemdrive%\
copy %systemdrive%\Install\execdaemon.cmd %systemdrive%\

REM Enable python to open listener sockets
NETSH firewall set allowedprogram program=c:\Python24\python.exe mode=enable profile=all

REM Start the daemon on boot
REG ADD "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run" /v XenRTExecDaemon /t REG_SZ /d "c:\execdaemon.cmd" /f

REM And start it now as well
START c:\execdaemon.cmd
