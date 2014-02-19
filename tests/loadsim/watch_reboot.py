# XenRT: Watch for a Windows process to finish, then reboot the machine
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import os,sys,time,_winreg,subprocess

if os.getenv("PROCESSOR_ARCHITECTURE") == "AMD64":
    arch = "amd64"
else:
    arch = "x86"
    import win32api, win32security, win32com.client
    from win32con import *
    from ntsecuritycon import *


# Functions

def ps():
    if arch == "amd64":
        f = os.popen("tasklist /fo csv")
        data = f.read().strip()
        pids = [ re.sub("\"", "", k) for k in
                [ j[0] for j in
                    [ i.split(",") for i in
                        data.split("\n") ] ] ]
    else:
        WMI = win32com.client.GetObject("winmgmts:")
        ps = WMI.InstancesOf("Win32_Process")
        pids = []
        for p in ps:
            pids.append(p.Properties_('Name').Value)
    return pids

# Borrowed: http://mail.python.org/pipermail/python-list/2002-August/161778.html
def AdjustPrivilege(priv, enable = 1):
     # Get the process token.
     flags = TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY
     htoken = win32security.OpenProcessToken(win32api.GetCurrentProcess(), flags)
     # Get the ID for the system shutdown privilege.
     id = win32security.LookupPrivilegeValue(None, priv)
     # Now obtain the privilege for this process.
     # Create a list of the privileges to be added.
     if enable:
         newPrivileges = [(id, SE_PRIVILEGE_ENABLED)]
     else:
         newPrivileges = [(id, 0)]
     # and make the adjustment.
     win32security.AdjustTokenPrivileges(htoken, 0, newPrivileges)
# /Borrowed

############################################################################
# Registry functions                                                       #
############################################################################

def lookupHive(hive):
    if hive == "HKLM":
        key = _winreg.HKEY_LOCAL_MACHINE
    elif hive == "HKCU":
        key = _winreg.HKEY_CURRENT_USER
    else:
        raise "Unknown hive %s" % (hive)
    return key

def lookupType(vtype):
    if vtype == "DWORD":
        vtypee = _winreg.REG_DWORD
    elif vtype == "SZ":
        vtypee = _winreg.REG_SZ
    elif vtype == "EXPAND_SZ":
        vtypee = _winreg.REG_EXPAND_SZ
    elif vtype == "MULTI_SZ":
        vtypee = _winreg.REG_MULTI_SZ
    else:
        raise "Unknown type %s" % (vtype)
    return vtypee

def regSet(hive, subkey, name, vtype, value):
    key = lookupHive(hive)
    vtypee = lookupType(vtype)
    k = _winreg.CreateKey(key, subkey)
    _winreg.SetValueEx(k, name, 0, vtypee, value)
    k.Close()
    return True

def regDelete(hive, subkey, name):
    key = lookupHive(hive)
    k = _winreg.CreateKey(key, subkey)
    _winreg.DeleteValue(k, name)
    k.Close()
    return True

# The process to watch for is given as a our first argument
process = sys.argv[1]

pids = ps()
if process in pids:
    sys.exit(0)

# Stop this script from running again
subprocess.Popen(["at.exe","/delete","/yes"])

# Insert the registry entries that exchange will have removed (GRR)
regSet("HKLM","SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon",
       "DefaultUsername", "SZ", "Administrator")
if sys.argv[3]:
    password = sys.argv[3]
else:
    password = "xenroot"
regSet("HKLM","SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon",
       "DefaultPassword", "SZ", password)
if sys.argv[2]:
    domain = sys.argv[2]
else:
    domain = "XENTEST"
regSet("HKLM","SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon",
       "DefaultDomainName", "SZ", domain)

# Now reboot
if arch == "x86":
   AdjustPrivilege(SE_SHUTDOWN_NAME)
   try:
       win32api.InitiateSystemShutdown(None, "Rebooting", 10, True, True)
   finally:
       AdjustPrivilege(SE_SHUTDOWN_NAME, 0)
else:
    os.system("shutdown -r -f -t 10")
