cd c:\progra~1\loadsim
"C:\Program Files\LoadSim\loadsim.exe" /f c:\loadsim.sim /t /x
REM Give a bit of time for the new users to get sorted out before running 
REM the initialize test
ping -n 120 127.0.0.1
"C:\Program Files\LoadSim\loadsim.exe" /f c:\loadsim.sim /ip /x
