@echo off

SET KEY=HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce

IF EXIST %systemdrive%\install\broadcom.xrt (
    %systemdrive%\install\broadcom\setup.exe /s /v/qn
)

IF EXIST %systemdrive%\install\broadcom-xp.xrt (
    %systemdrive%\install\broadcom\winxp\setup.exe /s /v/qn
)

IF EXIST d:\$oem$\$1\install\vistafix.xrt (
    XCOPY d:\$oem$\$1\install c:\install\ /y /s
    %systemdrive%\install\python\python.cmd
    EXIT
)

IF EXIST %systemdrive%\install\w2kfix.xrt (
    COPY %systemdrive%\install\fixes\reg.exe %systemdrive%\WINDOWS\system32\reg.exe
    COPY %systemdrive%\install\fixes\diskpart.exe %systemdrive%\WINDOWS\system32\diskpart.exe
    COPY %systemdrive%\install\install.cmd "%allusersprofile%\start menu\programs\startup\install.cmd"
)

IF EXIST %systemdrive%\install\python.xrt (
    REG ADD %KEY% /V 1 /D "%systemdrive%\install\python\python.cmd" /f
)

EXIT
