' VB Script to launch the application specified as our first argument, and then
' send it the keypresses specified in our second argument

WScript.Echo "Executing " + WScript.Arguments.Item(0) + " and sending key sequence " + WScript.Arguments.Item(1)

Set ws = CreateObject("WScript.Shell")
Set app = ws.Exec(WScript.Arguments.Item(0))

' Parse the keys
keys = Split(WScript.Arguments.Item(1),",")
For Each key In keys
    If Left(key,1) = "{" Or Len(key) = 1 Then
        ' Just a normal key
        WScript.Echo "Sending key " + key
        Ws.SendKeys key
    Else
        ' A command
        If Left(key,1) = "s" Then 
            WScript.Echo "Sleeping for " + Mid(key,2)
            WScript.Sleep CLng(Mid(key,2)) ' Sleep
        End If
    End If
Next

' Loop until it completes
Do While app.Status = 0
    Wscript.Sleep 5000
Loop
' Now exit with the exit code that it returned
Wscript.Quit(app.ExitCode)
