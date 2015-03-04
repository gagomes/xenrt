#
# XenRT: Test harness for Xen and the XenServer product family
#
# XenServer xsconsole interface
#

import string, re, time

import xenrt

__all__ = ["getInstance"]

boilerplate = r"""#!/usr/bin/env python
import time, xmlrpclib, XenAPI, os, signal
from pprint import pprint

if not os.path.exists("/etc/xsconsole/activatexmlrpc"):
    try: os.makedirs("/etc/xsconsole")
    except: pass
    file("/etc/xsconsole/activatexmlrpc", "w").write("")
    pid = os.popen("ps a | grep [x]sconsole | awk '{print $1}'").read().strip()
    os.kill(int(pid), signal.SIGKILL)
    time.sleep(10)

s = xmlrpclib.ServerProxy('http://_var_xapi_xmlrpcsocket.xsconsole',
                           transport=XenAPI.UDSTransport())

try:
    %s
except Exception, e:
    print str(e).replace("\\n", "\n")
"""

instances = {}
def getInstance(host):
    global instances
    if not instances.has_key(host.getName()):
        instances[host.getName()] = XSConsoleSession(host)
    i = instances[host.getName()]
    i.reset()
    return i

class XSConsoleSession(object):

    def __init__(self, host, name="XenRT"):
        self.host = host
        self.name = name

    def _command(self, cmdlist):
        sftp = self.host.sftpClient()
        t = xenrt.TEC().tempFile()
        script = boilerplate % (string.join(cmdlist, "\n"))
        file(t, "w").write(script)
        sftp.copyTo(t, "/tmp/xsconscmd.py")
        data = self.host.execdom0("/tmp/xsconscmd.py")
        if re.search("Fault.*Exception*", data):
            raise xenrt.XRTFailure(data)
        xenrt.TEC().logverbose(data)
        return data

    def reset(self):
        return self._command(["print s.new('%s')" % 
                              (self.name)])

    def authenticate(self, password=None):
        if not password: password = self.host.password
        return self._command(["print s.authenticate('%s')" % 
                              (password)])

    def activate(self, plugin):
        return self._command(["print s.activate('%s')" % 
                              (plugin)])

    def keypress(self, key):
        return self._command(["print s.keypress('%s')" %
                              (key)])
    
    def check(self, fail=False):
        if fail: return self._command(["print s.assertfailure()"])
        else: return self._command(["print s.assertsuccess()"])

    def screengrab(self):
        # Allow for slight delays in updting the menus.
        xenrt.sleep(5)
        return self._command(["pprint(s.snapshot())"])
