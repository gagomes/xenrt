#!/usr/bin/python
# XenRT: Test harness for Xen and the XenServer product family
#
# Windows post install script.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import os

LOCK_DIR = "C:\\LOCKDIR"

if os.getenv("PROCESSOR_ARCHITECTURE") == "AMD64":
    arch = "amd64"
else:
    arch = "x86"

if arch == "x86":
    import win32api, win32security
    from win32con import *
    from ntsecuritycon import *

import glob, shutil, time, sys, re, stat

debug = True
done = False
installers = {}
components = []
logfile = file("C:\\installer.log", "a")

def enableRDP():
    pdebug("Enabling RDP...")
    addRegKey("SYSTEM\\CurrentControlSet\\Control\\Terminal Server", "fDenyTSConnections", "0", type="REG_DWORD")
    os.system("NETSH FIREWALL SET PORTOPENING TCP 3389 \"RDP\" ENABLE")

def disableIPv6Privacy():
    pdebug("Disable IPv6 Privacy Extensions...")
    os.system("netsh interface ipv6 set global randomizeidentifiers=disabled")

def installXMLRPC():
    pdebug("Installing XML-RPC daemon...")
    shutil.copy("%s\\install\\python\\execdaemon.py" % (os.getenv("SystemDrive")), \
                "%s\\execdaemon.py" % (os.getenv("SystemDrive")))    
    shutil.copy("%s\\install\\python\\execdaemon.cmd" % (os.getenv("SystemDrive")), \
                "%s\\execdaemon.cmd" % (os.getenv("SystemDrive")))    
    try:
        os.system("NETSH FIREWALL SET ALLOWEDPROGRAM PROGRAM=%s\\Python27\\python.exe " % (os.getenv("SystemDrive")) +
                  "NAME=\"XMLRPCDaemon\" MODE=ENABLE PROFILE=ALL")
    except Exception, e:
        pdebug("Exception: %s" % (str(e)))
    addRun("%s\execdaemon.cmd" % (os.getenv("SystemDrive")))

def installSSH():
    pdebug("Installing SSH...")
    # Run this in the background since it leaves an annoying popup.
    os.spawnl(os.P_NOWAIT, "%s\\install\\ssh\\setupssh.exe" % 
             (os.getenv("SystemDrive")), "setupsssh.exe", "/S")
    os.system("NETSH FIREWALL SET PORTOPENING TCP 22 \"SSH\" ENABLE")
   
    # Install location depends on architecture.
    while True:
        if os.path.exists("%s\\OpenSSH" % ("C:\\PROGRA~2")):
            sshpath = "%s\\OpenSSH" % ("C:\\PROGRA~2")
            break
        elif os.path.exists("%s\\OpenSSH" % ("C:\PROGRA~1")):
            sshpath = "%s\\OpenSSH" % ("C:\\PROGRA~1")
            break
        else:
            time.sleep(5)
    pdebug("OpenSSH is installed in %s." % (sshpath))

    time.sleep(30)

    # Perform post-install actions.
    os.unlink("%s\\etc\\banner.txt" % (sshpath))
    os.system("%s\\bin\\mkgroup -l >> %s\\etc\\group" % (sshpath, sshpath))
    os.system("%s\\bin\\mkpasswd -l >> %s\\etc\\passwd" % (sshpath, sshpath))

    f = file("%s\\ssh.cmd" % (os.getenv("SystemDrive")), "w")
    f.write("net start opensshd\n")
    f.close()
    addRun("%s\ssh.cmd" % (os.getenv("SystemDrive")))

def sfuFix():
    os.spawnl(os.P_WAIT, "%s\\install\\fixes\\kb899522.cmd" % 
             (os.getenv("SystemDrive")), "%s\\install\\fixes\\kb899522.cmd" % 
             (os.getenv("SystemDrive")))
    
def postSFU():
    os.system("%s\\install\\SFU\\setup.cmd" % (os.getenv("SystemDrive")))

def installSFU():
    pdebug("Creating SFU signal files...")
    f = file("%s\\install\\postsfu.xrt" % (os.getenv("SystemDrive")), "w")
    f.write("yes")
    f.close()
    f = file("%s\\install\\reboot.xrt" % (os.getenv("SystemDrive")), "w")
    f.write("yes")
    f.close()
    pdebug("Installing SFU...")
    os.system("msiexec /i %s\\install\\SFU\\sfusetup.msi SFUDIR=\"%s\SFU\" /q" % 
             (os.getenv("SystemDrive"), os.getenv("SystemDrive"))) 

def allDone():
    global done
    pdebug("Writing %systemdrive%\\alldone.txt")
    f = file("%s\\alldone.txt" % (os.getenv("SystemDrive")), "w")
    f.write("yes")
    f.close()
    done = True

installers["kb899522"] = sfuFix
installers["postsfu"] = postSFU
installers["sfu"] = installSFU
installers["xmlrpc"] = installXMLRPC
installers["ssh"] = installSSH
installers["rdp"] = enableRDP
installers["ipv6"] = disableIPv6Privacy
installers["alldone"] = allDone

def pdebug(s):
    global logfile 
    if debug:
        logfile.write("DEBUG [%s]: %s\n" %
                      (time.strftime("%Y-%m-%d %H:%M:%S %Z"), s))

def addRun(command):
    addRegKey(r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
              os.path.basename(command), command)

# Use this with care as it may cause things to run at unexpected times.
def addRunOnce(command):
    addRegKey(r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce",
              os.path.basename(command), command)
        
def addRegKey(key, name, value, type="REG_SZ"):
    pdebug("Adding value %s to key %s with value %s." % (name, key, value))
    if arch == "x86":
        key = win32api.RegOpenKeyEx(HKEY_LOCAL_MACHINE, key, 0, KEY_SET_VALUE)
        if type == "REG_SZ":
            win32api.RegSetValueEx(key, name, 0, REG_SZ, value)
        win32api.RegCloseKey(key)
    else:
        os.system("REG ADD \"HKLM\\%s\" /v %s /t %s /d %s /f" % (key, name, type, value)) 

def install():
    try:
        os.makedirs(LOCK_DIR)     
    except:
        return
    try:
        components = [ re.sub("\.xrt", "", os.path.basename(f)) for f in \
                       glob.glob("%s\\install\\*.xrt" % (os.getenv("SystemDrive"))) ]
        components.sort()
        pdebug("Found signal files: %s" % (components))
        addRun("C:\\install\\install.cmd")
        if len(components) == 0:
            return
        while components:
            if "reboot" in components:
                os.chmod("%s\\install\\reboot.xrt" % (os.getenv("SystemDrive")), stat.S_IWRITE)
                os.unlink("%s\\install\\reboot.xrt" % (os.getenv("SystemDrive")))
                os.rmdir(LOCK_DIR)
                reboot()
                return
            else:
                c = components[0]
            try:
                pdebug("Removing signal file %s." % ("%s\\install\\%s.xrt" % (os.getenv("SystemDrive"), c)))
                os.chmod("%s\\install\\%s.xrt" % (os.getenv("SystemDrive"), c), stat.S_IWRITE)
                os.unlink("%s\\install\\%s.xrt" % (os.getenv("SystemDrive"), c))
                pdebug("Running function (%s) for signal file %s." % (installers[c], c))
                installers[c]()
            except:
                pass
            components = [ re.sub("\.xrt", "", os.path.basename(f)) for f in \
                           glob.glob("%s\\install\\*.xrt" % (os.getenv("SystemDrive"))) ]
            components.sort()
            pdebug("Found signal files: %s" % (components))
    
        if not done:
            pdebug("Writing end of script signal file.")
            f = file("%s\\install\\alldone.xrt" % (os.getenv("SystemDrive")), "w")
            f.write("yes")
            f.close()
            pdebug("Rebooting...")
            os.rmdir(LOCK_DIR)
            reboot() 
    finally:
        try:
            os.rmdir(LOCK_DIR)
        except:
            pass

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

def reboot():
    time.sleep(180)
    reply = False
    if arch == "x86":
        AdjustPrivilege(SE_SHUTDOWN_NAME)
        try:
            win32api.InitiateSystemShutdown(None, "Rebooting", 10, True, True)
            reply = True
        finally:
            AdjustPrivilege(SE_SHUTDOWN_NAME, 0)
    else:
        while True:
            os.system("shutdown -r -t 10 -f")
            time.sleep(600)
            os.system("shutdown -a")
            time.sleep(5)
    #time.sleep(20)
    return reply


install()
