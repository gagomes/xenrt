' VBS script to launch AMDSST, then send an ENTER keypress to accept
' the license and start it.
Set ws = CreateObject("WScript.Shell")
Set sst = ws.Exec("C:\Program Files\AMD\System Stress Test 4\AMDSST.exe")
' Wait 5 seconds to ensure the program has launched
Wscript.Sleep 5000
ws.SendKeys "{ENTER}"
' Loop until it completes
Do While sst.Status = 0
    Wscript.Sleep 30000
Loop
' Now exit with the exit code that AMDSST returned
Wscript.Quit(sst.ExitCode)
