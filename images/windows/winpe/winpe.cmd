@echo off

REM Windows PE image creator.
REM Runs on a Longhorn/Vista machine with WAIK installed.
REM 
REM Usage: winpe.cmd <destination> <architecture>
REM
REM        <destination>        The directory to place the
REM                             output files in.
REM        <architecture>       The architecture to build
REM                             for, x86 or amd64.

set DEST=%1
set ARCH=%2
set AIK=%ProgramFiles%\windows aik\tools\petools
set WORKDIR=%~dp0\working
set DRIVERDIR=%~dp0\drivers
set TOOLDIR=%~dp0\tools

REM Make sure we're not inside a working directory.
pushd c:\

echo Creating WinPE boot files and placing them in %DEST%.

REM Make sure we can access PE tools.
call "%AIK%\pesetenv.cmd"

REM Create clean destination directory.
rmdir /s /q %DEST%
md %DEST%

REM Create clean working directory.
rmdir /s /q %WORKDIR%
md %WORKDIR%

REM ********* BEGIN BCD SECTION *********
echo Creating BCD store...
Bcdedit /createstore %WORKDIR%\BCD
Bcdedit /store %WORKDIR%\BCD /create {ramdiskoptions} /d "Ramdisk options"
Bcdedit /store %WORKDIR%\BCD /set {ramdiskoptions} ramdisksdidevice boot
Bcdedit /store %WORKDIR%\BCD /set {ramdiskoptions} ramdisksdipath \Boot\boot.sdi
Bcdedit /store %WORKDIR%\BCD /create /d "WinPE Boot Image" /application osloader
for /f "tokens=1-3" %%a in ('Bcdedit /store %WORKDIR%\BCD /create /d "WinPEBootImage" /application osloader') do set GUID=%%c
Bcdedit /store %WORKDIR%\BCD /set %GUID% systemroot \Windows
Bcdedit /store %WORKDIR%\BCD /set %GUID% detecthal Yes
Bcdedit /store %WORKDIR%\BCD /set %GUID% winpe Yes
Bcdedit /store %WORKDIR%\BCD /set %GUID% osdevice ramdisk=[boot]\Boot\winpe.wim,{ramdiskoptions}
Bcdedit /store %WORKDIR%\BCD /set %GUID% device ramdisk=[boot]\Boot\winpe.wim,{ramdiskoptions}
Bcdedit /store %WORKDIR%\BCD /create {bootmgr} /d "Windows BootManager"
Bcdedit /store %WORKDIR%\BCD /set {bootmgr} timeout 30
Bcdedit /store %WORKDIR%\BCD /displayorder %GUID%
copy %WORKDIR%\BCD %DEST%\BCD
REM ********* END BCD SECTION *********

REM ********* BEGIN WIM SECTION *********
echo Creating PE image...
REM Grab a copy of the WinPE files.
call copype %ARCH% %WORKDIR%\winpe
REM Extract the files.
imagex /apply %WORKDIR%\winpe\winpe.wim 1 %WORKDIR%\winpe\mount
REM Take the files we need.
copy %WORKDIR%\winpe\mount\Windows\Boot\PXE\abortpxe.com %DEST%\abortpxe.com
copy %WORKDIR%\winpe\mount\Windows\Boot\PXE\bootmgr.exe %DEST%\bootmgr.exe
copy %WORKDIR%\winpe\mount\Windows\Boot\PXE\pxeboot.n12 %DEST%\pxeboot.0
copy "%AIK%\%ARCH%\boot\boot.sdi" %DEST%\boot.sdi

REM Include the tools we need.
copy /Y %TOOLDIR%\*.* %WORKDIR%\winpe\mount\Windows\system32\
copy /Y %TOOLDIR%\startnet-%ARCH%.cmd %WORKDIR%\winpe\mount\windows\system32\startnet.cmd

REM Add some drivers.
for /f %%d in ('dir /s /b %DRIVERDIR%\*.inf') do peimg /inf=%%d %WORKDIR%\winpe\mount
peimg /f /prep %WORKDIR%\winpe\mount

REM Finalise and write image.
imagex /boot /compress max /capture %WORKDIR%\winpe\mount %WORKDIR%\boot.wim "WinPE"
copy %WORKDIR%\boot.wim %DEST%\winpe.wim
popd
rmdir /s /q %WORKDIR%
