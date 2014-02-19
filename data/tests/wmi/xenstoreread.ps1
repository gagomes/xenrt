$location=$args[0]

# Locate the base object
$base = gwmi -n root\wmi -cl CitrixXenStoreBase
# Create a session
$sid = $base.AddSession("MyNewSession")
$session = gwmi -n root\wmi -q "select * from CitrixXenStoreSession where SessionId=$($sid.SessionId)"
# Read a value
$session.GetValue($location).value
