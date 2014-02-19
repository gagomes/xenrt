wpeinit
REM Make sure we have an IP address.
ipconfig /renew
REM Run the Windows installer.
c:\win\sources\setup.exe /unattend:c:\unattend.xml
