wpeinit
REM Make sure we have an IP address.
ipconfig /renew
REM Retrieve the install script file.
wget %WINPE_START_URL% 
REM Run the install script file.
%WINPE_START_FILE_BASENAME%
