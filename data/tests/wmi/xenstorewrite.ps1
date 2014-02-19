$location=$args[0]
$value=$args[1]

# Locate the base object
$base = gwmi -n root\wmi -cl CitrixXenStoreBase
# Create a session
$sid = $base.AddSession("MyNewSession")
$session = gwmi -n root\wmi -q "select * from CitrixXenStoreSession where SessionId=$($sid.SessionId)"
# Write a value
$session.SetValue($location,$value)
