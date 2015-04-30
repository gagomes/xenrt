#
# XenRT: Test harness for Xen and the XenServer product family
#
# Classes for interacting with xapi
#
# Copyright (c) 2009 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import string, re, time
import xenrt

class _Call(object):
    """Class representing a call for later evaluation."""

    TYPE = ""

    def __init__(self, 
                 operation="", 
                 environment=[],
                 keep=[],
                 parameters=[],
                 context=None,
                 error=None): 
        self.operation = operation
        self.environment = environment
        self.keep = keep
        self.parameters = parameters
        self.context = context
        self.error = error 
        self.session = None
        self.saved_parameters = self.parameters            

    def getSession(self, host, username, password):
        pass
    
    def getName(self, subject, usedomainname=False):
        pass

    def execute(self, host, username, password):
        pass

    def call(self, host, subject, usedomainname=False):
        xenrt.TEC().comment("Testing %s (%s, %s)" % (self.operation, subject.name, subject.password))
        xenrt.TEC().logverbose("CALL: %s PARAM: %s ENV: %s KEE: %s CON: %s" %
                              (self.operation, self.parameters, self.environment, 
                               self.keep, self.context))
        try:
            # If possible, use a cached API session to save time.
            createsession = True
            username = self.getName(subject, usedomainname)
            password = subject.password
            hostname = host.getName()
            if "credentials" in self.context.cache:
                credentials = self.context.cache["credentials"]
                xenrt.TEC().logverbose("Found existing credentials: %s" % (list(credentials)))
                if hostname in credentials:
                    if subject.name in credentials[hostname]:
                        if subject.password == credentials[hostname][subject.name]["subject"].password:
                            if self.TYPE in credentials[hostname][subject.name]:
                                createsession = False
                                self.session = credentials[hostname][subject.name][self.TYPE]
                    else:
                        credentials[hostname][subject.name] = {}
                else:
                    credentials[hostname] = {}
                    credentials[hostname][subject.name] = {}
            else:
                self.context.cache["credentials"] = {}
                self.context.cache["credentials"][hostname] = {}
                self.context.cache["credentials"][hostname][subject.name] = {}
            if createsession:
                try:
                    xenrt.TEC().logverbose("Creating a session (%s, %s)." % (username, password))
                except:
                    pass # CA-66057 this can break with unicode
                self.session = self.getSession(host, username, password) 
                self.context.cache["credentials"][hostname][subject.name][self.TYPE] = self.session
                self.context.cache["credentials"][hostname][subject.name]["subject"] = subject
                xenrt.TEC().logverbose("Set credentials: %s" % 
                                       (list(self.context.cache["credentials"])))
            if not "current" in self.context.cache:
                if not username == "root":
                    self.context.cache["current"] = (hostname, subject)
            if self.environment:
                xenrt.TEC().logverbose("Preparing %s." % (self.environment))
                self.context.prepare(self.environment)
            self.parameters = map(self.context.evaluate, self.parameters)
            xenrt.TEC().logverbose("CALL: %s(%s)" % (self.operation, self.parameters))
            result = self.execute(host, username, password)
            xenrt.TEC().logverbose("RESULT: %s" % (result))
            return result
        finally: 
            self.parameters = self.saved_parameters
            self.context.cleanup(filter(lambda x:not x in self.keep, self.environment))
            if "current" in self.context.cache:
                del self.context.cache["current"]

    def __repr__(self):
        return self.operation

    def __str__(self):
        return self.operation

class APICall(_Call):

    TYPE = "API"

    def getName(self, subject, usedomainname=False):
        return subject.apiName(usedomainname)

    def getSession(self, host, username, password):
        return host.getAPISession(username=username, password=password)

    def execute(self, host, username, password):
        return reduce(getattr, self.operation.split("."), self.session)(*self.parameters)

class SlaveAPICall(APICall):

    TYPE = "SlaveAPI"

    def getSession(self, host, username, password):
        return host.getAPISession(username=username, password=password, slave=True, local=True)

class CLICall(_Call):

    TYPE = "CLI"

    def getName(self, subject, usedomainname=False):
        return subject.cliName(usedomainname)

    def getSession(self, host, username, password):
        return host.getCLIInstance()
        
    def execute(self, host, username, password):
        return self.session.execute(self.operation, string.join(self.parameters), 
                                    username=username, password=password, timeout=600)

class SSHCall(_Call):

    TYPE = "SSH"

    def getSession(self, host, username, password):
        return host

    def execute(self, host, username, password):
        self.session.execdom0(self.operation, username=username, password=password)

class _FatalCall(object):

    TIMEOUT = 360 

    def __init__(self):
        self.context = None
        self.error = None

    def wrap(self, method, host, username, password):
        s = """
#!/bin/bash
/etc/init.d/xapi stop
rm -rf /var/xapi/state.db*
rm -rf /etc/firstboot.d/state/*
rm -f /etc/firstboot.d/data/host.conf || true
rm -f /etc/firstboot.d/05-filesystem-summarise || true
echo master > /etc/xensource/pool.conf
/etc/init.d/xapi start
/etc/init.d/firstboot restart
xe host-apply-edition edition=platinum"""
        master = self.context.entities["Pool"].ref.master
        #from Clearwater onwards no platinum licensing present
        if isinstance(master, xenrt.lib.xenserver.ClearwaterHost):
           s=s.replace("edition=platinum", "edition=free")
           
        master.execdom0("echo '%s' > /root/reset" % (s), newlineok=True)
        master.execdom0("chmod +x /root/reset")
        master.execdom0("echo /root/reset | at now + %s minutes" % 
                        (self.TIMEOUT/60))
        result = None
        try:
            try:
                result = method(self, host, username, password)
            except Exception, e:
                xenrt.TEC().logverbose("Call failed with error: %s" % (e))
                if re.search("RBAC_PERMISSION_DENIED", str(e)):
                    raise e
                if re.search("Authentication failed", str(e)):
                    raise e
                xenrt.TEC().logverbose("Expected error to contain: %s" % (self.error))
                if not re.search(self.error, str(e)): 
                    raise e
            else:
                if self.error: 
                    raise xenrt.XRTFailure("Expected to fail with %s." % (self.error))
        finally:
            xenrt.sleep(self.TIMEOUT+150)
            # TODO This needs to check for agent.
            master.waitForSSH(self.TIMEOUT+150)
        return result

class FatalAPICall(APICall, _FatalCall):

    def execute(self, host, username, password):
        try: 
            _FatalCall.wrap(self, APICall.execute, host, username, password)
        finally:
            self.context.cleanup(["Pool"])    

class FatalCLICall(CLICall, _FatalCall):

    def execute(self, host, username, password):
        try:
            _FatalCall.wrap(self, CLICall.execute, host, username, password)
        finally:
            self.context.cleanup(["Pool"])
        
