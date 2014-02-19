# Locate the base object
$base = gwmi -n root\wmi -cl CitrixXenStoreBase
# Create a session
$sid = $base.AddSession("MyNewSession")
$session = gwmi -n root\wmi -q "select * from CitrixXenStoreSession where SessionId=$($sid.SessionId)"
# Write a value
$session.SetValue("data/TempValue","This is a string")
# Read a value
$session.GetValue("data/TempValue").value
# Read the current VM's name
$session.GetValue("name").value
# Remove a value
$session.RemoveValue("data/TempValue")
#Examine Children
$session.GetChildren("data").children
# Set Watch
$watch = Register-WMiEvent -n root\wmi -q "select * from CitrixXenStoreWatchEvent where EventId='data/TempValue'" -action {write $session.getvalue("data/TempValue") }
$session.setvalue("data/TempValue","HELLO")
$session.setvalue("data/TempValue","WORLD")
$watch.action.output 