#
# XenRT: Test harness for Xen and the XenServer product family
#
# Host internal management network testcases
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy, os, subprocess, urllib2
import xenrt, xenrt.lib.xenserver

class _TCHIMN(xenrt.TestCase):
    GUEST1NAME = "guest1"
    GUEST2NAME = "guest2"
    HIMN_IP = "169.254.0.1"
    
    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid=tcid)
        self.pool = None
        self.master = None
        self.slave = None
        
    def prepare(self, args):
        self.pool = self.getDefaultPool();
        self.master = self.pool.master;
        self.slave = self.getHost("RESOURCE_HOST_1")
        
    def _createGuest(self, host, name):
        himnNetwork = host.parseListForUUID("network-list", "name-label", "Host internal management network")
        himnBridge = host.genParamGet("network", himnNetwork, "bridge")
        g = host.createGenericLinuxGuest(name=name)
        g.createVIF(bridge=himnBridge, plug=True)
        g.execguest("ifconfig eth1 up")
        g.execguest("dhclient eth1")
        xenrt.GEC().registry.guestPut(name, g)
        return g
        
    def getGuests(self):
        g1 = xenrt.GEC().registry.guestGet(self.GUEST1NAME)
        if not g1:
            g1 = self._createGuest(self.master, self.GUEST1NAME)
            
        g2 = xenrt.GEC().registry.guestGet(self.GUEST2NAME)
        if not g2:
            g2 = self._createGuest(self.slave, self.GUEST2NAME)
            
        return [g1, g2]
        
    def writeGuestFile(self, guest, fullpath, data):
        # write script to temp file on controller
        dir = xenrt.TEC().tempDir()
        tempFile = dir + "/tmp"
        f = open(tempFile, "w")
        f.write(data)
        f.close()
        
        # copy script to guest
        sftp = guest.sftpClient()
        try:
            sftp.copyTo(tempFile, fullpath)
        finally:
            sftp.close()
    
class TCOtherConfig(_TCHIMN):
    """TC-16122 test the HIMN other-config key is in place"""
    
    def run(self, args):
        for h in [self.master, self.slave]:
            himnNetwork = h.parseListForUUID("network-list", "name-label", "Host internal management network")
            oc = h.execdom0("xe network-list uuid=%s params=other-config" % (himnNetwork))
            
            if not "is_host_internal_management_network: true;" in oc:
                raise xenrt.XRTFailure("HIMN other-config key not set")

class TCAccessXapiXmlRpc(_TCHIMN):
    """TC-16120 test can access XAPI from guest on HIMN using XML-RPC"""
    
    def run(self, args):
        for g in self.getGuests():
            
            # script to access host XAPI using XMLRPC from the guest using the HIMN
            scr = """#!/usr/bin/python
import xmlrpclib
s = xmlrpclib.Server('http://%s')
session = s.session.login_with_password('root','%s')
print s.VM.get_all_records(session['Value'])
""" % (self.HIMN_IP, self.master.lookup("ROOT_PASSWORD"))
            
            # write script to guest
            self.writeGuestFile(g, "/himn", scr)
            
            # execute script on guest
            ret = g.execguest("chmod +x /himn && /himn")
            
            # ensure script output is valid by checking for guest uuid
            if not ret or not g.uuid in ret:
                raise xenrt.XRTFailure("Could not access XAPI on guest using HIMN")
        
class TCAccessXapiSsh(_TCHIMN):
    """TC-16121 test can acces XAPI from guest on HIMN using SSH"""
    
    def run(self, args):
        for g in self.getGuests():
            if g.execguest("test -e /root/.ssh/id_rsa", retval="code") != 0:
                
                # generate new key pair on guest and use for SSH
                g.execguest("rm -f /root/.ssh/id_rsa")
                g.execguest("rm -f /root/.ssh/id_rsa.pub")
                g.execguest("ssh-keygen -q -t rsa -N '' -f /root/.ssh/id_rsa")
                
                # copy guest public key to tempdir on controller
                tmp = xenrt.TEC().tempDir()
                sftp = g.sftpClient()
                try:
                    sftp.copyFrom("/root/.ssh/id_rsa.pub", tmp + "/id_rsa.pub")
                finally:
                    sftp.close()
                
                # copy guest public key from tempdir on controller to host
                sftp = g.host.sftpClient()
                try:
                    sftp.copyTo(tmp + "/id_rsa.pub", "/root/id_rsa.pub")
                finally:
                    sftp.close()
                
                # add guest public key to host's autorized keys
                g.host.execdom0("cat /root/id_rsa.pub >> /root/.ssh/authorized_keys")
            
            # do simple SSH command to dom0 from guest using the HIMN
            ret = g.execguest("ssh -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null root@%s ls /" % (self.HIMN_IP))
            
            if not ret or not "root" in ret:
                raise xenrt.XRTFailure("Could not access dom0 via SSH using HIMN")

class TCVMExport(_TCHIMN):
    """TC-16123 test can do vm-export from guest on HIMN using XML-RPC"""
    
    def run(self, args):
        g = self.getGuests()[0]
        
        # create a guest to export
        toExport = g.host.createGenericLinuxGuest(name="toExport" + g.name, start=False)
        self.uninstallOnCleanup(toExport)
        
        # little script to export vm using xml-rpc
        scr = """#!/usr/bin/python
import xmlrpclib, os
s = xmlrpclib.Server('http://%s')
session = s.session.login_with_password('root','%s')
task = s.task.create(session['Value'], "exporttask", "exporttask")
url = "http://%s/export?session_id=%%s&uuid=%s&task_id=%%s" %% (session['Value'], task['Value'])
os.system('wget "%%s" -O /tmp/exported' %% (url))
""" % (self.HIMN_IP, self.master.lookup("ROOT_PASSWORD"), self.HIMN_IP, toExport.uuid)
            
        xenrt.TEC().logverbose('script used for vm-export:\n%s' % scr)
        
        # write script to guest
        self.writeGuestFile(g, "/vmexport", scr)
        
        # now execute script on guest
        xenrt.TEC().logverbose('Exporting VM "toExport%s" using HIMN' % (g.name)) 
        ret = g.execguest("chmod +x /vmexport && /vmexport")
        
        if "error" in ret.lower():
            raise xenrt.XRTFailure("Error when exporting VM using HIMN")
        
        # check exported VM exists
        if g.execguest("test -e /tmp/exported", retval="code") != 0:
            raise xenrt.XRTFailure("Could not export VM using HIMN")
        
        # stat should reveal file to be of decent size
        if int(g.execguest("stat -c %s /tmp/exported").strip()) < 1000000:
            raise xenrt.XRTFailure("Exported file is to small.")
            
class TCHttps(_TCHIMN):
    """TC-16124 test can access xapi using https from guest on HIMN"""

    def run(self, args):
        for g in self.getGuests():
            # script to check can access server with https
            scr = """#!/usr/bin/python
import xmlrpclib, os
s = xmlrpclib.Server('https://%s')
session = s.session.login_with_password('root','%s')
""" % (self.HIMN_IP, self.master.lookup("ROOT_PASSWORD"))

            # write script to guest
            self.writeGuestFile(g, "/httpscheck", scr)

            # now execute script on guest
            xenrt.TEC().logverbose('Checking https access to host') 
            
            g.execguest("chmod +x /httpscheck && /httpscheck")
