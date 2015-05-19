from app.api import XenRTAPIPage
from server import PageFactory
import config

import time,string,os,re,traceback

class XenRTPower(XenRTAPIPage):
    def render(self):
        form = self.request.params
        machine = None
        powerop = None

        powerargs = { "off" : "--poweroff", "on": "--poweron", "reboot": "--powercycle" , "nmi": "--nmi", "status": "--powerstatus"}

        try:
            if form.has_key("machine"):
                machine  = form["machine"]
            if form.has_key("powerop"):
                powerop = form["powerop"]
                if powerop not in powerargs.keys():
                    return "ERROR Invalid power operation"

            if not machine or not powerop:
                return "ERROR Missing machine and/or operation"

            # Form a command line to launch the suite
            cmd = ["%s/exec/main.py" % config.sharedir, powerargs[powerop], machine]
            if form.has_key("bootdev"):
                cmd.append("--bootdev %s" % form['bootdev'])
            self.request.response.body_file = os.popen("%s 2>&1" % string.join(cmd))
            self.request.response.content_type="text/plain"
            return self.request.response
        except Exception, e:
            traceback.print_exc()
            return "ERROR Exception occurred, see error_log for details"
        
class XenRTSNetwork(XenRTAPIPage):
    def render(self):
        form = self.request.params
        try:
            xrtcmd = "--show-network"
            if form.has_key("ipv6"):
                xrtcmd = "--show-network6"
            
            # Form a command line to launch the suite
            cmd = ["%s/exec/main.py" % config.sharedir, xrtcmd]
            self.request.response.body_file = os.popen("%s 2>&1" % string.join(cmd))
            self.request.response.content_type="text/plain"
            return self.request.response
        except Exception, e:
            traceback.print_exc()
            return "ERROR Exception occurred, see error_log for details"

class XenRTMConfig(XenRTAPIPage):
    def render(self):
        form = self.request.params
        machine = form['machine']
        if form.has_key("generated"):
            try:
                xrtcmd = "--mconfig %s" % (machine)
                
                # Form a command line to launch the suite
                cmd = ["%s/exec/main.py" % config.sharedir, xrtcmd]
                self.request.response.body_file = os.popen("%s 2>&1" % string.join(cmd))
                self.request.response.content_type="text/plain"
                return self.request.response
            except Exception, e:
                traceback.print_exc()
                return "ERROR Exception occurred, see error_log for details"
        else:
            try:
                self.request.response.body_file = open("/etc/xenrt/machines/%s.xml" % (machine))
                self.request.response.content_type="text/plain"
                return self.request.response
            except Exception, e:
                return "No config defined, machine config will be taken from racktables"

class XenRTGetResource(XenRTAPIPage):
    def render(self):
        form = self.request.params
        machine = form['machine']
        restype = form['type']
        

        if form.has_key('args'):
            args = " %s" % form['args']
        else:
            args = ""
        
        xrtcmd = "--get-resource \"%s %s%s\"" % (machine, restype, args)
        
        cmd = ["%s/exec/main.py" % config.sharedir, xrtcmd]
        self.request.response.body_file = os.popen("%s 2>&1" % string.join(cmd))
        self.request.response.content_type="application/json"
        return self.request.response

class XenRTListResources(XenRTAPIPage):
    def render(self):
        form = self.request.params
        machine = form['machine']

        xrtcmd = "--list-resources \"%s\"" % (machine)
        
        cmd = ["%s/exec/main.py" % config.sharedir, xrtcmd]
        self.request.response.body_file = os.popen("%s 2>/dev/null" % string.join(cmd))
        self.request.response.content_type="application/json"
        return self.request.response

class XenRTReleaseResources(XenRTAPIPage):
    def render(self):
        form = self.request.params
        for v in form.getall("resource"):
            if v.startswith("NFS-"):
                xrtcmd = "--cleanup-nfs-dir \"%s\"" % (v.split("-", 1)[1])
            else:
                xrtcmd = "--release-lock \"%s\"" % (v)
            cmd = ["%s/exec/main.py" % config.sharedir, xrtcmd]
            os.system(string.join(cmd))
        return "OK"

PageFactory(XenRTGetResource, "/api/controller/getresource")
PageFactory(XenRTListResources, "/api/controller/listresources")
PageFactory(XenRTReleaseResources, "/api/controller/releaseresources", contentType="text/plain")
PageFactory(XenRTPower, "/api/controller/power", compatAction="power")
PageFactory(XenRTSNetwork, "/api/controller/network", compatAction="network")
PageFactory(XenRTMConfig, "/api/controller/machinecfg", compatAction="mconfig")
