REM XenRT: Helper script to run via soon

REM Schedule ourselves to run again
c:\soon.exe 120 %1\checkfinished.bat %1 %2 %3 %4

REM Call the python prog
%1\watch_reboot.py %2 %3 %4
