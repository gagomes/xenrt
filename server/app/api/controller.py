from app.api import XenRTAPIPage
from server import PageFactory
import config

import time,string,os,re,traceback

class XenRTPower(XenRTAPIPage):
    def render(self):
        form = self.request.params
        machine = None
        powerop = None

        powerargs = { "off" : "--poweroff", "on": "--poweron", "reboot": "--powercycle" , "nmi": "--nmi"}

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
                xrtcmd = "--run-tool \"machineXML('%s')\"" % (machine)
                
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

PageFactory(XenRTPower, "power", "/api/controller/power", compatAction="power")
PageFactory(XenRTSNetwork, "snetwork", "/api/controller/network", compatAction="network")
PageFactory(XenRTMConfig, "mconfig", "/api/controller/machinecfg", compatAction="mconfig")
