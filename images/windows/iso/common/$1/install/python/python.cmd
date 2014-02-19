REM
REM XenRT: Test harness for Xen and the XenServer product family.
REM
REM Windows post install script. 
REM
REM Copyright (c) 2007 XenSource, Inc. All use and distribution of this
REM copyrighted material is governed by and subject to terms and
REM conditions as licensed by XenSource, Inc. All other rights reserved.
REM

set PYTHONDIR=%~dp0

REM Installing ActivePython.
IF %PROCESSOR_ARCHITECTURE% == AMD64 (
    START /W msiexec.exe /I %PYTHONDIR%\ActivePython-2.7.2.5-win64-x64.msi /Q /L*v %systemdrive%\python-install.log
) ELSE (
    START /W msiexec.exe /I %PYTHONDIR%\ActivePython-2.7.2.5-win32-x86.msi /Q /L*v %systemdrive%\python-install.log
)
REM Run install script.
%systemdrive%\install\install.cmd
