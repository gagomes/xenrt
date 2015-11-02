#
# XenRT: Test harness for Xen and the XenServer product family
#
# Security standalone testcases
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy, sets, xmlrpclib
import tempfile, inspect, ssl
import xenrt, xenrt.lib.xenserver, xenrt.networkutils
from xenrt.lazylog import step, comment, log, warning

from cc import _CCSetup
from xenrt.lib.xenserver.context import Context
from xenrt.lib.xenserver.call import *
import XenAPI
import ast
import os
import tarfile, lxml.html

class _HTTPHandlerTest(_CCSetup):
    """Verify that the XAPI HTTPS handlers check the username and password supplied."""
    LICENSE_SERVER_REQUIRED = False

    INVALID_PASSWORD = "invalidpassword"
    INVALID_PTOKEN = "97c238de-ada4-b3c5-2b04-185ad6e41f0c/" \
                         "2b01d385-f5a8-6141-c2ae-4d33340a6994/" \
                         "b5bec734-7f34-36df-7d94-2b99af8481fc"    
    INVALID_SESSION = "OpaqueRef:6043d52e-05b6-462b-c592-1d780017bfce"

    WGET = "wget --no-check-certificate -O /dev/null"
    PROTOCOL = "https"
    DENIED = "Authorization fail|Unauthorised"

    def getHandler(self):
        return "export?uuid=%s" % (self.guest.getUUID())

    def testHandler(self, username=None, password=None, ptoken=None, session=None, fail=False):
        if username and password:
            if self.WGET.startswith("curl"):
                result = xenrt.command("%s --user '%s':'%s' '%s://%s/%s'" % 
                                  (self.WGET, username, password,
                                   self.PROTOCOL, self.host.getIP(), self.getHandler()),
                                   ignoreerrors=True)
            else:
                result = xenrt.command("%s --user='%s' --password='%s' '%s://%s/%s'" % 
                                  (self.WGET, username, password,
                                   self.PROTOCOL, self.host.getIP(), self.getHandler()),
                                   ignoreerrors=True)
        if re.search("\?", self.getHandler()):
            delim = "&"
        else:
            delim = "?"
        if ptoken:
            result = xenrt.command("%s '%s://%s/%s%spool_secret=%s'" % 
                                  (self.WGET, self.PROTOCOL, self.host.getIP(),
                                   self.getHandler(), delim, ptoken),
                                   ignoreerrors=True)
        if session:
            result = xenrt.command("%s '%s://%s/%s%ssession_id=%s'" % 
                                  (self.WGET, self.PROTOCOL, self.host.getIP(),
                                   self.getHandler(), delim, session),
                                   ignoreerrors=True)
        if re.search(self.DENIED, result) and not "200 OK" in result:
            if fail:
                xenrt.TEC().logverbose("Operation failed as expected.")
            else: 
                raise xenrt.XRTFailure("Operation failed.")
        else:
            if fail:
                raise xenrt.XRTFailure("Operation succeeded.")
            else: 
                xenrt.TEC().logverbose("Operation succeeded as expected.")
            

    def prepare(self, arglist):
        _CCSetup.prepare(self, arglist)
        self.guest = self.host.createGenericEmptyGuest()
        self.uninstallOnCleanup(self.guest)
        self.ptoken = self.host.execdom0("cat /etc/xensource/ptoken").strip()

    def testUserPassword(self, valid):
        if valid:
            xenrt.TEC().logverbose("Attempt HTTPS operation over HTTPS using valid credentials. (%s, %s)" % 
                                  ("root", self.host.password))
            self.testHandler(username="root", password=self.host.password)
        else:
            xenrt.TEC().logverbose("Attempt HTTPS operation over HTTPS using invalid credentials. (%s, %s)" % 
                                  ("root", self.INVALID_PASSWORD))
            self.testHandler(username="root", password=self.INVALID_PASSWORD, fail=True)

    def testPoolToken(self, valid):
        if valid:
            xenrt.TEC().logverbose("Attempt HTTPS operation over HTTPS using a valid pool token. (%s)" % 
                                   (self.ptoken))
            self.testHandler(ptoken=self.ptoken)
        else:
            xenrt.TEC().logverbose("Attempt HTTPS operation over HTTPS using an invalid pool token. (%s)" % 
                                   (self.INVALID_PTOKEN))
            self.testHandler(ptoken=self.INVALID_PTOKEN, fail=True)

    def testSession(self, valid):
        if valid:
            v = sys.version_info
            if v.major == 2 and ((v.minor == 7 and v.micro >= 9) or v.minor > 7):
                xenrt.TEC().logverbose("Disabling certificate verification on >=Python 2.7.9")
                ssl._create_default_https_context = ssl._create_unverified_context
            session = xmlrpclib.Server("https://%s" % (self.host.getIP())).session.login_with_password("root",
                                        self.host.password)["Value"]
            xenrt.TEC().logverbose("Attempt HTTPS operation over HTTPS using a valid session. (%s)" % 
                                   (session))
            self.testHandler(session=session)
        else:
            xenrt.TEC().logverbose("Attempt HTTPS operation over HTTPS using an invalid session reference. (%s)" % 
                                   (self.INVALID_SESSION))
            self.testHandler(session=self.INVALID_SESSION, fail=True)

    def run(self, arglist):
        self.runSubcase("testUserPassword", (True), "UserPassword", "Valid")
        self.runSubcase("testUserPassword", (False), "UserPassword", "Invalid")
        self.runSubcase("testPoolToken", (True), "PoolToken", "Valid")
        self.runSubcase("testPoolToken", (False), "PoolToken", "Invalid")
        self.runSubcase("testSession", (True), "Session", "Valid")
        self.runSubcase("testSession", (False), "Session", "Invalid")
        
class TC7939(_HTTPHandlerTest):
    pass

class TC11260(_HTTPHandlerTest):
    """Test HTTPS GET handlers."""

    def test(self):
        self.runSubcase("testUserPassword", (True), self.getHandler(), "ValidUser")
        self.runSubcase("testPoolToken", (True), self.getHandler(), "ValidToken")
        self.runSubcase("testSession", (True), self.getHandler(), "ValidSession")
        if self.getHandler():
            self.runSubcase("testUserPassword", (False), self.getHandler(), "InvalidUser")
            self.runSubcase("testPoolToken", (False), self.getHandler(), "InvalidToken")
            self.runSubcase("testSession", (False), self.getHandler(), "InvalidSession")
        else:
            xenrt.TEC().logverbose("Expecting root handler to succeed for all credentials.")
            self.runSubcase("testUserPassword", (True), self.getHandler(), "InvalidUser")
            self.runSubcase("testPoolToken", (True), self.getHandler(), "InvalidToken")
            self.runSubcase("testSession", (True), self.getHandler(), "InvalidSession")

    def run(self, arglist):
        for handler in ["export",
                        "",
                        "audit_log",
                        "blob",
                        "export_metadata",
                        "host_backup",
                        "host_logs_download",
                        "host_rrd",
                        "pool/xmldbdump",
                        "pool_patch_download",
                        "rrd_updates",
                        # "rss", Disabled.
                        "sync_config_files",
                        "system-status",
                        "vm_rrd",
                        "vncsnapshot",
                        "wlb_diagnostics",
                        "wlb_report"
                        ]:
            self.getHandler = lambda : handler
            self.test()

class TC11261(TC11260):
    """Test HTTPS PUT handlers."""

    WGET = "curl --insecure --verbose --upload-file /dev/null --max-time 10"
    DENIED = "Unauthorised"

    def run(self, arglist):
        for handler in ["host_restore",
                        "import",
                        "import_metadata",
                        "import_raw_vdi",
                        "oem_patch_stream",
                        "pool_patch_upload",
                        "rrd",
                        ]:
            self.getHandler = lambda : handler
            self.test()

class TC8307(xenrt.TestCase):
    """Test case for CA-22616 (CVE-2007-5497)"""

    def run(self, arglist=None):
        host = self.getDefaultHost()

        # Get the required files
        host.execdom0("curl '%s/security/ext2fs_test' -o /tmp/ext2fs_test" % 
                      (xenrt.TEC().lookup("TEST_TARBALL_BASE")))
        host.execdom0("chmod +x /tmp/ext2fs_test")
        host.execdom0("curl '%s/security/instrumented.img' -o "
                      "/tmp/instrumented.img" % 
                      (xenrt.TEC().lookup("TEST_TARBALL_BASE")))

        # Run the test
        data = host.execdom0("/tmp/ext2fs_test /tmp/instrumented.img || true")

        # Parse the output
        m = re.match(".*Unknown code ext2 (\d+)$", data)
        if not m:
            raise xenrt.XRTError("Couldn't parse output of ext2fs_test")
        if int(m.group(1)) == 70 or int(m.group(1)) == 60:
            xenrt.TEC().logverbose("System appears to be patched against "
                                   "CVE-2007-5497")
        elif int(m.group(1)) == 36:
            raise xenrt.XRTFailure("CA-22616 System appears vulnerable to "
                                   "CVE-2007-5497")
        else:
            raise xenrt.XRTError("Unknown ext2 error code %s from ext2fs_test" % 
                                 (m.group(1)))

class TC7977(xenrt.TestCase):
    """Send a large number of HTTP headers to xapi"""

    def run(self, arglist=None):
        host = self.getDefaultHost()

        # Get curent agent start time
        agentStart = float(host.getHostParam("other-config", "agent_start_time"))

        # Send it stupid number of headers...
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host.getIP(), 80))
        s.send("GET / HTTP/1.0\r\n")
        sent = 0
        try:
            for i in range(2000000):
                s.send("content-length: 123\r\n")
                sent += 1
        except:
            # We expect this to fail...
            pass
        xenrt.TEC().logverbose("Sent %u headers" % (sent))

        # Get new agent start time (if it's up)
        newAgentStart = None
        try:
            newAgentStart = float(host.getHostParam("other-config",
                                                    "agent_start_time"))
        except:
            # Xapi probably dead...
            pass

        if newAgentStart != agentStart:
            raise xenrt.XRTFailure("CA-16594 Sending large number of HTTP "
                                   "headers caused xapi to crash")

class TC8368(_CCSetup):
    """Verify changing password on master changes the password on slaves"""
    LICENSE_SERVER_REQUIRED = False

    def prepare(self, arglist=None):
        self.originalPassword = None
        _CCSetup.prepare(self, arglist)

    def run(self, arglist=None):
        pool = self.getDefaultPool()
        self.pool = pool
        if len(pool.getHosts()) < 2:
            raise xenrt.XRTError("Need a pool of 2 hosts", data="Found %u" % 
                                 (len(pool.getHosts())))

        master = pool.master
        slave = pool.getSlaves()[0]

        # Run a command so we get the current password of each host displaed
        slave.execdom0("/bin/true")

        # Change the password on the master
        cli = master.getCLIInstance()
        master.findPassword()
        self.originalPassword = master.password
        cli.execute("user-password-change", "old=%s new=testpass" % 
                                            (master.password))

        for h in pool.getHosts():
            h.password = "testpass"
            xenrt.lib.xenserver.cli.clearCacheFor(h.machine)

        # Wait 2 minutes
        time.sleep(120)

        # Promote the slave to a new master
        pool.designateNewMaster(slave)
        pool.check()

        # Try and execute an SSH command on each host
        for h in pool.getHosts():
            h.execdom0("/bin/true")

    def postRun(self):
        # Attempt to set password back
        if self.originalPassword:
            cli = self.pool.getCLIInstance()
            cli.password = "testpass"
            try:
                cli.execute("user-password-change", "old=testpass new=%s" % 
                                                    (self.originalPassword))
            except:
                pass
            for h in self.pool.getHosts():
                xenrt.lib.xenserver.cli.clearCacheFor(h.machine)
                h.password = self.originalPassword
        _CCSetup.postRun(self)

class TC11213(xenrt.TestCase):
    """Regression test for CA-39378 (vm86 host crash)"""

    def run(self, arglist=None):
        host = self.getDefaultHost()
        distro = "debian50"
        if isinstance(host, xenrt.lib.xenserver.TampaHost):
            distro = "debian60"  # CA-86624
        guest = host.createBasicGuest(distro=distro, memory=8192)

        tf = xenrt.TEC().tempFile()
        f = file(tf, "w")
        f.write("""#include <sys/syscall.h>

int main(int argc, char *argv[])
{
    syscall(0x2d, 0x5c339892, 0x4db53c04, 0x73179324, 0x60496127,
        0x2946ccd2, 0x48977f14);
    syscall(0x71, 0x59786b8b, 0x6fca4e23, 0x2b43b07e, 0x03ad556a,
        0x58e66ca6, 0x7cdbd795);

    return 0;
}
""")
        f.close()

        sftp = guest.sftpClient()
        sftp.copyTo(tf, "/tmp/vm86.c")
        sftp.close()

        guest.execguest("cd /tmp; gcc -o vm86 vm86.c")

        # Start it 10s after we return to avoid losing our SSH connection
        guest.execguest("(sleep 10 && /tmp/vm86) > /dev/null 2>&1 < /dev/null &")

        # Wait 20s and then check the host
        time.sleep(20)

        try:
            host.checkReachable(15)
        except:
            raise xenrt.XRTFailure("Host appears vulnerable to CA-39378 (vm86old syscall)")
            
class _AuthenticationBase(xenrt.TestCase):
    """Base class for AD authentication tests."""

    AUTHSERVER = "AUTHSERVER"
    AUTHTYPE = "AD"
    DOMAINNAME = None  # the value None will have the domain name auto-generated

    OPERATIONS = {"cli" :   [CLICall("vm-list")],
                  "api" :   [],
                  "ssh" :   ["whoami"]}

    SUBJECTGRAPH = ""
    ENABLE = []
    # None == All
    TESTUSERS = None 
    LOCALUSERS = True
    
    NOREVERT = False
    NOMODIFY = False

    ALLOWED = {}
    FATAL = {}
    SLAVE = []
    LOCAL = []

    PRESERVE_AUTH = False

    CHECK_AUDIT = False

    USEAPI = False

    USEDOMAINNAME = False

    def userinstance(x): return str(x) == "user" 
    userinstance = staticmethod(userinstance)

    def groupinstance(x): return str(x) == "group"
    groupinstance = staticmethod(groupinstance)

    def allMembers(subject, result=sets.Set()):
        if hasattr(subject, "members"):
            users = sets.Set(filter(_AuthenticationBase.userinstance, subject.members))
            groups = sets.Set(filter(_AuthenticationBase.groupinstance, subject.members))
            for x in groups:
                if x in result: continue
                result = result.union(_AuthenticationBase.allMembers(x, result.union(sets.Set([x]))))
            return result.union(users)
        return result

    allMembers = staticmethod(allMembers)

    def allParents(subject, result=sets.Set()):
        for x in subject.memberof:
            if x in result: continue
            result = result.union(_AuthenticationBase.allParents(x, result.union(sets.Set([x]))))
        return result
    allParents = staticmethod(allParents)

    def closure(subjects):
        return reduce(sets.Set.union,
                      map(_AuthenticationBase.allMembers, subjects),
                      sets.Set(subjects))
    closure = staticmethod(closure)

    def buildSubjectGraph(self):
        """Return the subject graph for this test."""
        return self.SUBJECTGRAPH

    def buildEnableList(self):
        """Return the list of subjects to enable."""
        return self.ENABLE

    def buildTestUsersList(self):
        """Returns the list of users to test authenticate (None implies all)."""
        return self.TESTUSERS

    def getValid(self, operation):
        """Return the list of currently valid users for 'operation'."""
        return self.valid

    def getAuthServer(self, name):
        """Return the authentication server named 'name'."""
        # See if we have a cached version from an earlier test.
        authserver = xenrt.TEC().registry.read("/xenrt/specific/authserver/%s" % (name))
        if authserver:
            if not self.DOMAINNAME or self.DOMAINNAME == authserver.domainname:
                return authserver

        if self.AUTHTYPE == "AD":
            authserver = self.getGuest(name)
            if not authserver and xenrt.TEC().lookup("INSTALL_AUTHSERVER",
                                                     False,
                                                     boolean=True):
                authserver = xenrt.lib.xenserver.guest.createVM(\
                    self.getDefaultHost(),
                    name,
                    distro=xenrt.TEC().lookup("DEFAULT_AD_SERVER_DISTRO",
                                              "ws08sp2-x86"),
                    vifs=xenrt.lib.xenserver.Guest.DEFAULT)
                self.uninstallOnCleanup(authserver)
                self.getLogsFrom(authserver)
                authserver.installDrivers()
                authserver.installPowerShell()
                authserver.enablePowerShellUnrestricted()
            authserver = xenrt.ActiveDirectoryServer(authserver, domainname=self.DOMAINNAME)
        elif self.AUTHTYPE == "PAM":
            authserver = self.getHost(name)
            authserver = xenrt.PAMServer(authserver)
        xenrt.TEC().registry.write("/xenrt/specific/authserver/%s" % (name), authserver)
        return authserver

    def getHostTopology(self):
        host = self.getDefaultHost()
        version = host.productVersion
        self.pool = xenrt.lib.xenserver.host.poolFactory(version)(host)

    def cli(self, host, subject, operation):
        try:
            operation.call(host, subject, usedomainname=self.USEDOMAINNAME)
        except Exception, e:
            xenrt.TEC().logverbose("Caught exception: %s" % (str(e)))
            traceback.print_exc(sys.stderr)
            if re.search("RBAC permission denied", str(e)):
                raise xenrt.XRTFailure(str(e))
            if self.ALLOWED.has_key(operation.operation):
                if re.search(self.ALLOWED[operation.operation], str(e)):
                    xenrt.TEC().comment("Allowed failure '%s' for '%s'." % \
                                        (self.ALLOWED[operation.operation], operation.operation))
                    return
            raise xenrt.XRTError(e.reason, e.data)

    def api(self, host, subject, operation):
        try: 
            operation.call(host, subject, usedomainname=self.USEDOMAINNAME)
        except Exception, e:
            xenrt.TEC().logverbose("Caught exception: %s" % (str(e)))
            traceback.print_exc(sys.stderr)
            if re.search("SESSION_AUTHENTICATION_FAILED", str(e)):
                raise xenrt.XRTFailure(str(e))
            if re.search("RBAC_PERMISSION_DENIED", str(e)):
                raise xenrt.XRTFailure(str(e))
            if self.ALLOWED.has_key(operation.operation):
                if re.search(self.ALLOWED[operation.operation], str(e)):
                    xenrt.TEC().comment("Allowed failure '%s' for '%s'." % \
                                        (self.ALLOWED[operation.operation], operation.operation))
                    return
            raise xenrt.XRTError(str(e))
            
    def ssh(self, host, subject, operation):            
        try:
            if isinstance(subject, xenrt.ActiveDirectoryServer.Local):
                username = subject.name
            elif isinstance(subject, xenrt.PAMServer.User):
                username = subject.name
            else:
                if self.USEDOMAINNAME:
                    username = "%s\\%s" % (subject.server.netbiosname, subject.name)
                else:
                    username = "%s\\%s" % (subject.server.domainname, subject.name)
            user = host.execdom0(operation,
                                 username=username.encode("utf-8"),
                                 password=subject.password).strip()
        except xenrt.XRTException, e:
            if e.reason == "SSH authentication failed":
                raise xenrt.XRTFailure(e.reason, e.data)
            raise xenrt.XRTError(e.reason, e.data)

    def authenticate(self, host, subject, valid, mode, operation):
        valid = subject.name in valid
        local = isinstance(subject, xenrt.ActiveDirectoryServer.Local)
        if mode == "ssh": 
            method = self.ssh
        elif mode == "cli": 
            method = self.cli
        elif mode == "api": 
            method = self.api
        else:
            raise xenrt.XRTError("Unknown calling mechanism: %s" % (mode))
        try:
            xenrt.TEC().logverbose("Trying to connect to %s using %s "
                               "with %s credentials, believed %s. (%s, %s)" % 
                               (host.getName(),
                                string.upper(mode),
                                local and "local" or "external",
                                valid and "good" or "bad",
                                subject.name.encode("utf-8"),
                                subject.password.encode("utf-8")))
        except:
            # The above logverbose call can fail due to encoding issues
            # - don't block the test because of this...
            pass
        try: 
            method(host, subject, operation)
        except Exception, e:
            xenrt.TEC().logverbose("Exception: %s" % (e)) 
            if valid:
                self.authserver.place.checkHealth()
                stre = str(e)
                note = None
                for x in ["The call to Kerberos 5 failed",
                          "SESSION_AUTHENTICATION_FAILED"]:
                    if x in stre:
                        note = x
                        break
                msg = "Authentication failed with good credentials."
                if note:
                    msg = "%s '%s'" % (msg, note)
                    raise xenrt.XRTFailure(msg)
                raise
            else:
                xenrt.TEC().logverbose("Failed to authenticate with bad credentials.")
                if self.CHECK_AUDIT:
                    self.checkAudit(host, subject, valid, mode, operation)
        else:
            xenrt.TEC().logverbose("No exception raised.")
            if not valid: 
                self.authserver.place.checkHealth()
                raise xenrt.XRTFailure("Authenticated with bad credentials.")
            else:
                xenrt.TEC().logverbose("Authentication succeeded with good credentials.")
                if self.CHECK_AUDIT:
                    self.checkAudit(host, subject, valid, mode, operation)

    def checkAudit(self, host, subject, valid, mode, operation):
        username = host.genParamGet("subject", host.getSubjectUUID(subject), "other-config", "subject-name")
        username = re.sub(r"\\", r"\\\\", username)
        sid = host.getSubjectSID(subject)
        callname = re.sub("xenapi\.", "", operation.operation)
        if valid: 
            result = "ALLOWED"
        else:
            result = "DENIED"   
        timestamp = xenrt.timenow()
        xenrt.TEC().logverbose("Checking for audit entry. (U: %s S: %s R: %s C: %s" % 
                               (username, sid, result, callname))
        found = False
        host.execdom0("gzip -d /var/log/audit.log.*.gz", level=xenrt.RC_OK)  # We need to unzip any zipped logs
        data = host.execdom0("cat /var/log/audit.log*", nolog=True).strip()
        fieldvalues = ("timestamp", "logtype", "hostname", "thread", "task", "audit")
        sexpvalues = ("session", "sid", "username", "result", "error", "calltype", "callname", "parameters")
        for line in data.splitlines():
            current = re.search("\[(?P<field>.*)\]", line)
            if not current:
                raise xenrt.XRTFailure("Malformed audit.log entry: %s" % (line))
            field = dict(zip(fieldvalues,
                             map(string.strip,
                                 current.group("field").split("|"))))
            # ignoring entry if the logtype is not audit/ info(for older builds)
            if not field["logtype"] == "audit" and not field["logtype"] == "info":
                # xenrt.TEC().logverbose("Ignoring line: %s" % (line))
                continue

            current = re.search("\((?P<sexp>.*)\)", line)
            if not current:
                raise xenrt.XRTFailure("Malformed audit.log entry: %s" % (line))    
       
            sexp = re.findall("'([^']*)'", current.group("sexp"))
            sexp = dict(zip(sexpvalues, sexp[:len(sexpvalues) - 1] + [sexp[len(sexpvalues) - 1:]]))
            
            if username == sexp["username"]:
                if sid == sexp["sid"]:
                    if callname == sexp["callname"]:
                        if result == sexp["result"]:
                            found = True
                            xenrt.TEC().logverbose("Found audit entry: %s" % (line))
                            t = time.mktime(time.strptime(re.sub("\..*", "", field["timestamp"]),
                                                         "%Y%m%dT%H:%M:%S"))
                            xenrt.TEC().logverbose("Time difference: %s" % (timestamp - t))                            

        if not found:
            raise xenrt.XRTFailure("No audit entry found for operation.") 

    def testCredentials(self, mode, operation):
        for user in self.users:
            valid = self.getValid(operation)
            xenrt.TEC().logverbose("Subjects believed valid: %s" % (valid))
            self.authenticate(self.pool.master, user, valid, mode, operation)
            for slave in self.slaves:
                if mode == "ssh":
                    self.authenticate(slave, user, valid, mode, operation)
            for other in self.others:
                valid = filter(lambda x:x == "root" or not x == user.name, valid)
                self.authenticate(other, user, valid, mode, operation)

    def enableAuthentication(self):
        self.valid = []
        self.pool.enableAuthentication(self.authserver, useapi=self.USEAPI)
        for subjectname in self.buildEnableList(): 
            subject = self.authserver.getSubject(name=subjectname)
            self.pool.allow(subject, "pool-admin")
            self.valid.append(subject)
        self.valid = filter(self.userinstance, self.closure(self.valid))
        self.valid = [ x.name for x in self.valid ]

    def prepare(self, arglist):
        self.users = []
        self.groups = []
        self.valid = []

        self.pool = None
        self.slaves = []
        self.others = []
        self.getHostTopology()

        nfs = xenrt.NFSDirectory()
        self.isosr = self.pool.master.parseListForUUID("sr-list",
                                                       "name-label",
                                                       "Remote ISO Library on: %s" % \
                                                       xenrt.TEC().lookup("EXPORT_ISO_NFS_STATIC"))

        self.context = Context(self.pool)
        
        # we need to let the context know the NFS location of the ISO SR that contains
        # reader.iso. During the tests, the host gets set back to its original state
        # and it then can't get reader.iso. 
        self.context.isoSRNfsLocation = nfs

        if self.AUTHTYPE:
            self.authserver = self.getAuthServer(self.AUTHSERVER) 
            self.users, self.groups = self.authserver.createSubjectGraph(self.buildSubjectGraph())
            self.groups = map(lambda x:self.authserver.getSubject(name=x), self.groups)
            self.users = map(lambda x:self.authserver.getSubject(name=x), self.users)        
            
            self.enableAuthentication()
    
        # If we've overriden the default behaviour of testing all users
        # in the subject list then reset the self.users list
        u = self.buildTestUsersList()
        if u:
            self.users = map(lambda x:self.authserver.getSubject(name=x), u)

        # Add a couple of control subjects. 
        if self.LOCALUSERS:
            self.users.append(xenrt.ActiveDirectoryServer.Local("root", xenrt.TEC().lookup("ROOT_PASSWORD")))
            self.users.append(xenrt.ActiveDirectoryServer.Local("fail", xenrt.TEC().lookup("ROOT_PASSWORD")))
            self.valid.append("root")
        
        for mode in self.OPERATIONS:
            for operation in self.OPERATIONS[mode]:
                if not type("") == type(operation):
                    if not operation.context:
                        xenrt.TEC().logverbose("Setting context to: %s" % (self.context))
                        operation.context = self.context

    def modify(self):
        xenrt.TEC().logverbose("Not modifying any credentials.")

    def revert(self):
        xenrt.TEC().logverbose("Not modifying any credentials.")

    def doTest(self, label):
        result = None
        for mode in self.OPERATIONS:
            group = "Check%s" % (string.upper(mode))
            cases = {} 
            for operation in self.OPERATIONS[mode]:
                testcase = "%s-%s" % (label, operation)
                if testcase in cases:
                    cases[testcase] += 1
                    testcase = "%s-%s" % (testcase, cases[testcase])
                else:
                    cases[testcase] = 0
                result = self.runSubcase("testCredentials", (mode, operation), group, testcase)
                if self.PRESERVE_AUTH:
                    try:
                        if not self.pool.master.paramGet("external-auth-type") == self.AUTHTYPE: 
                            self.enableAuthentication()
                    except Exception, e: 
                        xenrt.TEC().logverbose("Reenabling authentication failed. (%s)" % (e))   

    def run(self, arglist):
        self.doTest("Initial")
        if not self.NOMODIFY:
            modify = self.runSubcase("modify", (), "Scenario", "Modify")
            if not modify == xenrt.RESULT_PASS: 
                raise xenrt.XRTFailure("Modify failed.") 
            self.doTest("Modified")
        if not self.NOREVERT:
            revert = self.runSubcase("revert", (), "Scenario", "Revert")
            if not revert == xenrt.RESULT_PASS: 
                raise xenrt.XRTFailure("Revert failed.")
            self.doTest("Reverted")
 
    def postRun(self):
        for user in self.users:
            xenrt.TEC().logverbose("Removing Users")
            if not isinstance(user, xenrt.ActiveDirectoryServer.Local):
                try: self.pool.deny(user)
                except: pass
                try: self.authserver.removeSubject(user.name)
                except: pass
        for group in self.groups:
            xenrt.TEC().logverbose("Removing pool")
            try: self.pool.deny(group)
            except: pass
            try: self.authserver.removeSubject(group.name)
            except: pass
        try:
            xenrt.TEC().logverbose("Disable pool authentication") 
            self.pool.disableAuthentication(self.authserver)
        except: pass
        for slave in self.slaves:
            xenrt.TEC().logverbose("Disable slve authentication")
            try: slave.disableAuthentication(self.authserver)
            except: pass
        for other in self.others:
            xenrt.TEC().logverbose("disbale others")
            try: other.disableAuthentication(self.authserver)
            except: pass
        try: self.pool.master.forgetSR(self.isosr)
        except: pass

class _PoolAuthentication(_AuthenticationBase):

    SUBJECTGRAPH = """
<subjects>
  <user name="user"/>
</subjects>
"""
    ENABLE = ["user"]

    def getHostTopology(self):
        self.pool = self.getDefaultPool()
        self.slaves = self.pool.slaves.values()

class _RBAC(_PoolAuthentication):
    """Class adding role awareness to the base AD tests."""

    OPERATIONS = {"cli" :   [],
                  "ssh" :   [],
                  "api" :   []}
 
    PERMISSIONS = {}
    CLIMAPPINGS = {}

    ALLROLES = ["pool-admin",
                "pool-operator",
                "vm-power-admin",
                "vm-admin",
                "vm-operator",
                "read-only"]

    NOREVERT = True
    NOMODIFY = True
    PRESERVE_AUTH = True

    AUTHTYPE = "AD"
    # AUTHTYPE = ""
    LOCALUSERS = False

    # Mapping of users in SUBJECTGRAPH to roles.
    # "user"    :   [role1,role2,...,roleN]
    ROLES = {}

    SLAVE = ["xenapi.VM.atomic_set_resident_on",
             "xenapi.VM.hard_reboot_internal",
             "xenapi.host.ha_disable_failover_decisions",
             "xenapi.host.ha_disarm_fencing",
             "xenapi.host.ha_stop_daemon",
             "xenapi.host.ha_release_resources",
             "xenapi.host.local_assert_healthy",
             "xenapi.host.preconfigure_ha",
             "xenapi.host.ha_join_liveset",
             "xenapi.host.ha_wait_for_shutdown_via_statefile",
             "xenapi.host.request_backup",
             "xenapi.host.request_config_file_sync",
             "xenapi.host.propose_new_master",
             "xenapi.host.abort_new_master",
             "xenapi.host.commit_new_master",
             "xenapi.host.signal_networking_change",
             "xenapi.host.notify",
             "xenapi.host.get_uncooperative_domains",
             "xenapi.host.attach_static_vdis",
             "xenapi.host.detach_static_vdis",
             "xenapi.host.enable_binary_storage",
             "xenapi.host.disable_binary_storage",
             "xenapi.host.update_pool_secret",
             "xenapi.host.update_master",
             "xenapi.host.set_localdb_key",
             "xenapi.host.tickle_heartbeat",
             "xenapi.host.certificate_install",
             "xenapi.host.certificate_uninstall",
             "xenapi.host.certificate_list",
             "xenapi.host.crl_install",
             "xenapi.host.crl_uninstall",
             "xenapi.host.crl_list",
             "xenapi.host.certificate_sync",
             "xenapi.host.set_license_params",
             "xenapi.pool.ha_schedule_plan_recomputation"]

    def parsePermissions(self, csv):
        """Parse an API call permissions map as supplied by the agent team."""
        data = csv.strip().splitlines()
        data = [ x.split(",") for x in data ]
        data = [ x[1:8] for x in data ]
        permissions = {}
        for line in data:
            apicall = "xenapi." + line[0]
            rights = line[1:]
            permissions[apicall] = []
            for i in range(len(rights)):
                if rights[i] == "X":
                    permissions[apicall].append(self.ALLROLES[i])
        return permissions

    def parseCLItoAPI(self, csv):
        """Parse CLI to API call map as supplied by agent team."""
        mapping = {}
        data = csv.strip().splitlines()
        for line in data:
            entries = line.split()            
            mapping[entries[0]] = map(lambda x:re.sub("Client\.", "", x), entries[1:])
        return mapping

    def cliFactory(self, cliargs):
        if not cliargs.has_key("context"):
            cliargs["context"] = self.context
        if cliargs["operation"] in self.FATAL:
            cliargs["error"] = self.FATAL[cliargs["operation"]]
            return FatalCLICall(**cliargs)
        else:
            return CLICall(**cliargs)

    def apiFactory(self, apiargs):
        """Return an APICall object for the current context."""
        # TODO
        # There's some bug, which I need to track down, that
        # breaks stuff if the following initialisation isn't
        # done.
        if not apiargs.has_key("operation"):
            apiargs["operation"] = "" 
        if not apiargs.has_key("environment"):
            apiargs["environment"] = []
        if not apiargs.has_key("keep"):
            apiargs["keep"] = [] 
        if not apiargs.has_key("parameters"):
            apiargs["parameters"] = [] 
        if not apiargs.has_key("context"):
            apiargs["context"] = self.context
        if apiargs["operation"] in self.FATAL:
            apiargs["error"] = self.FATAL[apiargs["operation"]]
            return FatalAPICall(**apiargs)
        elif apiargs["operation"] in self.SLAVE:
            return SlaveAPICall(**apiargs)
        else:
            return APICall(**apiargs)

    def allRoles(subject):
        return reduce(sets.Set.union,
                      map(lambda x:x.roles,
                          _AuthenticationBase.allParents(subject).union(set([subject]))))
    allRoles = staticmethod(allRoles)

    def getValidAPI(self, operation):
        permutations = [str(operation)]        
        permutations.append(re.sub("Pool", "pool", str(operation)))
        permutations.append(re.sub("Host", "host", str(operation)))
        permutations.append(str(operation).lower())
        permutations.append(re.sub("vm", "VM", str(operation)))
        permutations.append(re.sub("sr", "SR", str(operation)))
        permutations.append(re.sub("vdi", "VDI", str(operation)))
        permutations.append(re.sub("vbd", "VBD", str(operation)))
        permutations.append(re.sub("PIF", "PIF_metrics", str(operation)))
        permutations.append(re.sub("VM", "VM_metrics", str(operation)))
        permutations.append(re.sub("VM", "VM_guest_metrics", str(operation)))
        permutations.append(re.sub("VIF", "VIF_metrics", str(operation)))
        permutations.append(re.sub("host", "host_metrics", str(operation)))
        permutations.append(re.sub("VBD", "VBD_metrics", str(operation)))
        permissions = [] 
        found = False
        for p in permutations:
            if self.PERMISSIONS.has_key(p):
                found = True
                xenrt.TEC().logverbose("Matching permutation: %s" % (p))
                permissions = self.PERMISSIONS[p]
                break
        if not found:
            xenrt.TEC().warning("Permissions not found for %s" % (operation)) 
            permissions = self.ALLROLES
        if str(operation) in self.SLAVE:
            xenrt.TEC().comment("Using slave login for %s" % (operation))
            permissions = self.ALLROLES
        xenrt.TEC().logverbose("API: %s PERM: %s" % (str(operation), permissions))
        isvalid = lambda y:bool(filter(lambda x:x in permissions, self.allRoles(y)))
        subjects = filter(lambda x:x, [self.authserver.getSubject(name=str(x)) for x in self.valid])
        xenrt.TEC().logverbose("Subjects: %s" % (self.valid))
        valid = [ x.name for x in filter(isvalid, subjects) ]
        xenrt.TEC().logverbose("Valid subjects for %s: %s" % (operation, valid + ["root"]))
        return valid + ["root"]

    def getValidCLI(self, operation):
        xenrt.TEC().logverbose("Finding valid subjects for '%s'." % (str(operation)))
        xenrt.TEC().logverbose("Environment: %s Parameters: %s" % (operation.environment, operation.parameters))
        if self.CLIMAPPINGS.has_key(str(operation)):
            apicalls = [ "xenapi.%s" % (x) for x in self.CLIMAPPINGS[str(operation)] ]
        elif re.search("param", str(operation)):
            entity = self.context.classes[operation.environment[0]].NAME
            if re.search("param-list", str(operation)):
                apicalls = ["xenapi.%s.get_all" % (entity)]
            else:
                parameter = operation.parameters[1]
                parameter = re.sub("-uuid", "", parameter)
                if re.search("param-get", str(operation)):
                    parameter = re.sub("param-name=", "", parameter)
                    parameter = re.sub("-", "_", parameter)
                    apicalls = ["xenapi.%s.get_%s" % (entity, parameter)]
                elif re.search("param-clear", str(operation)):
                    parameter = re.sub("param-name=", "", parameter)
                    parameter = re.sub("-", "_", parameter)
                    apicalls = ["xenapi.%s.set_%s" % (entity, parameter)]
                else:               
                    parameter = re.sub("-", "_", parameter)
                    if re.search("param-set", str(operation)):
                        parameter = re.sub("[:=].*", "", parameter)
                        apicalls = ["xenapi.%s.set_%s" % (entity, parameter)]
                    else:
                        parameter = re.sub(".*[:=]", "", parameter)
                        if re.search("param-add", str(operation)):
                            apicalls = ["xenapi.%s.add_to_%s" % (entity, parameter)]
                        elif re.search("param-remove", str(operation)):
                            apicalls = ["xenapi.%s.remove_from_%s" % (entity, parameter)]
        else:
            raise xenrt.XRTSkip("No permissions mapping for '%s'." % (str(operation)))
        xenrt.TEC().logverbose("API calls for '%s': %s" % (str(operation), apicalls))
        if str(operation) == "vm-start":
            xenrt.TEC().logverbose("P: %s" % (operation.parameters))
            if not filter(lambda x:re.search("on=", x), operation.parameters):
                if "xenapi.VM.start_on" in apicalls:
                    apicalls.remove("xenapi.VM.start_on")
        if str(operation) == "vm-resume":
            xenrt.TEC().logverbose("P: %s" % (operation.parameters))
            if not filter(lambda x:re.search("on=", x), operation.parameters):
                if "xenapi.VM.resume_on" in apicalls:
                    apicalls.remove("xenapi.VM.resume_on")
        if not apicalls:
            raise xenrt.XRTSkip("Empty permissions mapping for '%s'." % (str(operation)))
        if str(operation) in self.LOCAL:
            xenrt.TEC().comment("Expecting %s to fail remotely." % (operation))
            return []
        return reduce(lambda a, b:[x for x in a if x in b], map(self.getValidAPI, apicalls))
    
    def getValid(self, operation):
        if str(operation) in self.PERMISSIONS:
            return self.getValidAPI(operation)
        else:
            return self.getValidCLI(operation)

    def prepare(self, arglist):
        _AuthenticationBase.prepare(self, arglist)
        xenrt.getTestTarball("rbac", extract=True)
        xenrt.TEC().logverbose("Product revision is: %s" % (self.pool.master.productRevision))
        if isinstance(self.pool.master, xenrt.lib.xenserver.MNRHost) and not self.pool.master.productVersion == 'MNR': 
            xenrt.TEC().logverbose("Using current permission mappings.")
            c = "%s/rbac/current/cli2api" % (xenrt.TEC().getWorkdir())
        else:
            xenrt.TEC().logverbose("Using MNR permission mappings.")
            c = "%s/rbac/MNR/cli2api" % (xenrt.TEC().getWorkdir())
        self.CLIMAPPINGS.update(self.parseCLItoAPI(file(c).read()))
        if self.pool.master.execdom0("ls /opt/xensource/debug/rbac_static.csv", retval="code") != 0:
            xenrt.TEC().logverbose("Using MNR permission mappings.")
            p = "%s/rbac/MNR/permissions" % (xenrt.TEC().getWorkdir())
            self.PERMISSIONS.update(self.parsePermissions(file(p).read()))
        else:
            self.PERMISSIONS.update(self.parsePermissions(self.pool.master.execdom0("cat /opt/xensource/debug/rbac_static.csv")))

    def enableAuthentication(self):
        self.valid = []
        self.pool.enableAuthentication(\
            self.authserver)
        for subjectname in self.buildEnableList(): 
            subject = self.authserver.getSubject(name=subjectname)
            self.pool.allow(subject)
            self.valid.append(subject)
        self.valid = filter(self.userinstance, self.closure(self.valid))
        self.valid = [ x.name for x in self.valid ]
        for user in self.ROLES:
            subject = self.authserver.getSubject(name=user)
            for role in self.ROLES[user]:
                self.pool.addRole(subject, role)

    def clearwaterAPICallCheck(self, calls):
      # omit wlb and VMPP related calls from Clearwater onwards
      if isinstance(self.pool.master, xenrt.lib.xenserver.ClearwaterHost):
        return [call for call in calls if not re.search("wlb|VMPP|set_protection_policy", call)]
      else:
        return calls
  
    def postRun(self):
        _AuthenticationBase.postRun(self)
        self.context.cleanup(self.context.entities) 

class TC8399(_AuthenticationBase):
    """Check local authentication works."""

    AUTHTYPE = ""

    SUBJECTGRAPH = """
<subjects>
  <user name="user1"/>
  <group name="group2">
    <user name="user2"/>
  </group>
</subjects>
"""

    def prepare(self, arglist):
        _AuthenticationBase.prepare(self, arglist)
        self.authserver = xenrt.PAMServer(self.getHost("RESOURCE_HOST_0"))
        self.users, self.groups = self.authserver.createSubjectGraph(self.buildSubjectGraph())
        self.groups = map(lambda x:self.authserver.getSubject(name=x), self.groups)
        self.users = map(lambda x:self.authserver.getSubject(name=x), self.users)        
        self.users.append(xenrt.ActiveDirectoryServer.Local("root", xenrt.TEC().lookup("ROOT_PASSWORD")))
        self.users.append(xenrt.ActiveDirectoryServer.Local("fail", xenrt.TEC().lookup("ROOT_PASSWORD")))

        self.valid.append("user1")
        self.valid.append("user2")

    def modify(self):
        xenrt.TEC().logverbose("Testing with an invalid password.")
        self.users = filter(lambda x:not x.name == "root", self.users)
        self.users.append(xenrt.ActiveDirectoryServer.Local("root", "XXXinvalidXXX")) 
        self.valid.remove("root")

    def revert(self):
        self.users = filter(lambda x:not x.name == "root", self.users)
        self.users.append(xenrt.ActiveDirectoryServer.Local("root", xenrt.TEC().lookup("ROOT_PASSWORD")))
        self.valid.append("root")

class TC8400(_AuthenticationBase):
    """Test a stand-alone user."""

    USEAPI = True

    SUBJECTGRAPH = """
<subjects>
  <user name="user"/>
</subjects>
"""
    
    ENABLE = ["user"]

    def modify(self):
        user = self.authserver.getSubject(name="user")
        self.pool.deny(user)
        self.authserver.removeSubject(user.name)
        self.valid.remove("user")

    def revert(self):
        self.users = filter(lambda x:not x.name == "user", self.users)
        user = self.authserver.addUser("user")
        self.users.append(user)
        self.pool.allow(user, "pool-admin")
        self.valid.append("user")
        
class ADPBISDirectoryCheck(xenrt.TestCase):
    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        
    def run(self, arglist=None):
        pbisDirectories = ['/etc/pbis','/opt/pbis','/var/lib/pbis']
        missingDirectories =[]
        
        for directory in pbisDirectories:
            if self.host.execdom0("test -d %s" % directory, retval="code") !=0:
                missingDirectories.append(directory)
        
        if not missingDirectories:
            xenrt.TEC().logverbose("PBIS directories exist")
        else:            
            raise xenrt.XRTFailure("Following PBIS folders do not exist: %s" % ",".join(missingDirectories))
        
class TC10890(TC8400):

    USEDOMAINNAME = True

class TC10630(TC8400):
    """Check domain join using EXT characters"""

    USERNAME = u"user\u03b1"

    def getAuthServer(self, name):
        """Return the authentication server named 'name'."""
        if self.AUTHTYPE == "AD":
            authserver = self.getGuest(name)
            authserver = xenrt.ActiveDirectoryServer(authserver,
                                                     username=self.USERNAME)
            return authserver

    def postRun(self):
        TC8400.postRun(self)
        self.authserver.place.superuser = "Administrator"   
        self.authserver.place.password = xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS",
                                                             "ADMINISTRATOR_PASSWORD"]) 
        self.authserver.removeSubject(self.USERNAME)

class TC9223(TC8400):
    """Verify operation of Active Directory authentication using an AD server on a different subnet to the host"""

    def prepare(self, arglist):
        TC8400.prepare(self, arglist)
        # Check the host and AD server are actually on different subnets
        hostip = self.pool.master.getIP()
        l = self.pool.master.minimalList("pif-list",
                                         "netmask",
                                         "IP=%s" % (hostip))
        if len(l) != 1:
            raise xenrt.XRTError("Couldn't find pool master subnet mask")
        hostnetmask = l[0]
        hostsubnet = xenrt.calculateSubnet(hostip, hostnetmask)
        adip = self.authserver.place.getIP()
        if xenrt.isAddressInSubnet(adip, hostsubnet, hostnetmask):
            raise xenrt.XRTError("Active Directory server is in the same "
                                 "subnet as the pool master")

class TC12544(TC8400):
    """Verify operation of Active Directory authentication using a domain name not containing a dot"""

    DOMAINNAME = "xenrt"

class TC8526(_AuthenticationBase):
    """Test user names of varying lengths."""

    SUBJECTGRAPH = "<subjects/>"

    USEAPI = True

    OPERATIONS = {"cli" :   [],
                  "api" :   [APICall("xenapi.VM.get_all")],
                  "ssh" :   ["whoami"]}

    def allow(self, username): 
        try:
            subject = self.authserver.getSubject(username)
            self.pool.allow(subject, "pool-admin", useapi=self.USEAPI)  
        except Exception, e:
            xenrt.TEC().logverbose("E: %s" % (str(e)))
            raise xenrt.XRTFailure("Error allowing subject.")

    def subjects(self):
        names = [ string.join([ random.choice(string.letters) \
                    for x in xrange(i) ], "") \
                        for i in xrange(1, 104) ]
        passwords = [ string.join([ random.choice(string.letters) \
                        for x in xrange(8) ], "") \
                            for i in xrange(1, 104) ]
        return zip(names, passwords)

    def run(self, arglist):
        iteration = 0
        for username, password in self.subjects():
            xenrt.TEC().logverbose("Testing username of length %s. (%s)" % 
                                   (len(username), username.encode("utf-8")))

            user = self.authserver.addUser(username, password)
            self.users.append(user)
            try:
                ssh = api = cli = xenrt.RESULT_PASS
                allow = self.runSubcase("allow", (username), "Allow", iteration)
                self.valid.append(username)
                if self.OPERATIONS["cli"]:
                    cli = self.runSubcase("testCredentials", ("cli", self.OPERATIONS["cli"][0]), "CheckCLI", iteration)
                if self.OPERATIONS["api"]:
                    api = self.runSubcase("testCredentials", ("api", self.OPERATIONS["api"][0]), "CheckAPI", iteration)
                if self.OPERATIONS["cli"]:
                    ssh = self.runSubcase("testCredentials", ("ssh", self.OPERATIONS["ssh"][0]), "CheckSSH", iteration)
                if not allow == ssh == cli == api == xenrt.RESULT_PASS: return
            finally:
                try:
                    self.valid.remove(username)
                    self.pool.deny(user)
                    self.authserver.removeSubject(user.name)
                    self.users = filter(lambda x:not x.name == username, self.users)
                except Exception, e:
                    xenrt.TEC().logverbose("Ignoring exception: %s" % (str(e)))
            iteration = iteration + 1

class TC8637(TC8526):

    def subjects(self):
        return [(u"user\u03b1", "booo2342")]

class TC8638(TC8526):

    def subjects(self):
        return [("user", u"booo2342\u03b1"),
                ("user", u"\u20ac\u0152\xe4\xe1\xe0\u0153xenrooT"),
                ("user", u"\xe4\xf6\xfc\xdf\xc4\xd6\xdcxenrooT"),
                ("user", u"\u0441\u0448\u0435\u043a\u0448\u0447xenrooT")]

class TC9067(TC8526):
    
    def subjects(self):
        return [("user", "@**ds34")]

class TC9323(TC8526):
    
    def subjects(self):
        return [("user", "foo bar")]

class TC8640(TC8526):

    def subjects(self):
        return [(u"user\u03b1", u"booo2342\u03b1")]

class TC8470(_AuthenticationBase):
    """Test AD authenication still works after host reboot."""

    SUBJECTGRAPH = """
<subjects>
  <user name="user"/>
</subjects>
"""
    ENABLE = ["user"]
    NOREVERT = True

    def modify(self):
        self.pool.master.reboot()
        self.pool.master.setDNSServer(self.authserver.place.getIP())  # CA-76402 On reboot our DNS modification can get undone...

class TC9218(_AuthenticationBase):
    """Test a user belonging to a group with a large number of other users"""

    SUBJECTGRAPH = """
<subjects>
  <group name="biggroup">
%s
  </group>
</subjects>
"""
    ENABLE = ["user000487"]
    TESTUSERS = ["user000487", "user000300"]
    NOREVERT = True
    NOMODIFY = True

    USERS = 500 

    def buildSubjectGraph(self):
        """Return the subject graph for this test"""
        template = '    <user name="user%06u"/>'
        userxml = string.join(map(lambda x:template % (x),
                                  range(self.USERS)), "\n")
        return self.SUBJECTGRAPH % (userxml) 

class TC9219(TC9218):
    """Test a user belonging to a group with a large number of other users (group in subject list)"""

    ENABLE = ["biggroup"]
    TESTUSERS = ["user000123"]

class TC10206(TC9219):

    HUGE = 2000

    SUBJECTGRAPH = """
<subjects>
  <group name="biggroup">
%s
  </group>
  <group name="hugegroup">
%s
  </group>
</subjects>
"""

    def buildSubjectGraph(self):
        """Return the subject graph for this test"""
        template = '    <user name="user%06u"/>'
        userxml = string.join(map(lambda x:template % (x),
                                  range(self.USERS)), "\n")
        hugexml = string.join(map(lambda x:template % (x),
                                  range(self.HUGE)), "\n")
        return self.SUBJECTGRAPH % (userxml, hugexml)
 
class TC8401(_AuthenticationBase):
    """Test a user which belongs to a single group."""

    SUBJECTGRAPH = """
<subjects>
  <group name="group">
    <user name="user"/>
  </group>
</subjects>
"""
    ENABLE = ["group"]
    
    def modify(self):
        user = self.authserver.getSubject(name="user")
        group = self.authserver.getSubject(name="group")
        group.removeSubject(user)
        self.valid.remove("user")

    def revert(self):
        user = self.authserver.getSubject(name="user")
        group = self.authserver.getSubject(name="group")
        group.addSubject(user) 
        self.valid.append("user")

class _MultipleGroups(_AuthenticationBase):
    """Base class for multiple direct group membership."""

    GROUPS = 2

    SUBJECTGRAPH = """
<subjects>
  %s
</subjects>
"""

    def multiGraph(self, groups):
        if not groups: return ""
        return """
<group name="group-%s">
<user name="user"/>
</group>%s""" % (groups, self.multiGraph(groups - 1))

    def buildSubjectGraph(self):
        """Return the subject graph for this test"""
        return self.SUBJECTGRAPH % (self.multiGraph(self.GROUPS))

    def run(self, arglist):
        for i in map(lambda x:x + 1, range(self.GROUPS)):
            xenrt.TEC().logverbose("Testing group-%s." % (i))
            cli = self.runSubcase("testCredentials", ("cli", self.OPERATIONS["cli"][0]),
                                  "CheckCLI",
                                  "Initial" + str(i))
            ssh = self.runSubcase("testCredentials", ("ssh", self.OPERATIONS["ssh"][0]),
                                  "CheckSSH",
                                  "Initial" + str(i))
            if cli != xenrt.RESULT_PASS or ssh != xenrt.RESULT_PASS:
                return
            active = self.authserver.getSubject(name="group-%s" % (i))
            self.pool.allow(active, "pool-admin")
            self.valid.append("user")
            cli = self.runSubcase("testCredentials", ("cli", self.OPERATIONS["cli"][0]),
                                  "CheckCLI",
                                  "Modified" + str(i))
            ssh = self.runSubcase("testCredentials", ("ssh", self.OPERATIONS["ssh"][0]),
                                  "CheckSSH",
                                  "Modified" + str(i))
            if cli != xenrt.RESULT_PASS or ssh != xenrt.RESULT_PASS:
                return
            self.pool.deny(active)
            self.valid.remove("user")

class TC8402(_MultipleGroups):
    """Test a user which belongs to two separate groups."""

    GROUPS = 2

class TC8417(_MultipleGroups):
    """Stress. Test a user which belongs to a large number of seperate groups."""

    def prepare(self, arglist):
        _MultipleGroups.prepare(self, arglist)

    GROUPS = 500

class _NestedGroups(_AuthenticationBase):
    """Base class for nested group membership."""

    LEVELS = 2

    SUBJECTGRAPH = """
<subjects>
  %s
</subjects>
"""

    ENABLE = ["group-%s" % (LEVELS)]

    def nestedGraph(self, levels):
        if not levels: return '<user name="user"/>'
        return """<group name="group-%s">
%s
</group>""" % (levels, self.nestedGraph(levels - 1))

    def buildSubjectGraph(self):
        """Return the subject graph for this test"""
        return self.SUBJECTGRAPH % (self.nestedGraph(self.LEVELS))

    def modify(self):
        parentgroup = "group-%s" % (self.LEVELS)
        childgroup = "group-%s" % (self.LEVELS - 1)
        parentgroup = self.authserver.getSubject(name=parentgroup)
        childgroup = self.authserver.getSubject(name=childgroup)
        parentgroup.removeSubject(childgroup)
        self.valid.remove("user")

    def revert(self):
        parentgroup = "group-%s" % (self.LEVELS)
        childgroup = "group-%s" % (self.LEVELS - 1)
        parentgroup = self.authserver.getSubject(name=parentgroup)
        childgroup = self.authserver.getSubject(name=childgroup)
        parentgroup.addSubject(childgroup)
        self.valid.append("user")

class TC8403(_NestedGroups):
    """Test an allowed user belonging to a group belonging to a group."""

    LEVELS = 2
    ENABLE = ["group-%s" % (LEVELS)]

class TC8418(_NestedGroups):
    """Stress. Test a deeply nested user."""

    LEVELS = 50 
    ENABLE = ["group-%s" % (LEVELS)]

class TC8404(_AuthenticationBase):
    """Test a circular group membership dependency."""

    SUBJECTGRAPH = """
<subjects>
  <group name="group1">
    <group name="group2">
      <group name="group3">
        <user name="user"/>
        <group name="group1"/>
      </group>
    </group>
  </group>
</subjects>
"""

    ENABLE = ["group1"]

class TC8405(_AuthenticationBase):
    """Test adding and removing subjects."""

    SUBJECTGRAPH = """
<subjects>
  <user name="user1"/>
  <user name="user2"/>
</subjects>
"""
    ENABLE = ["user1"]

    def modify(self):
        user1 = self.authserver.getSubject(name="user1")
        user2 = self.authserver.getSubject(name="user2")
        self.pool.deny(user1)
        self.valid.remove("user1")
        self.pool.allow(user2, "pool-admin")
        self.valid.append("user2")

    def revert(self):
        user1 = self.authserver.getSubject(name="user1")
        user2 = self.authserver.getSubject(name="user2")
        self.pool.deny(user2)
        self.valid.remove("user2")
        self.pool.allow(user1, "pool-admin")
        self.valid.append("user1")

class _ManySubjects(_AuthenticationBase):
    """Authentication performance with large subject lists."""

    SUBJECTS = 0 
    COUNT = 0

    SUBJECTGRAPH = """
<subjects>
%s
</subjects>
"""

    ENABLE = []

    def subjectGraph(self, subjects):
        if subjects <= 1: return '  <user name="user1"/>'
        return '  <user name="user%s"/>\n' % (subjects) + self.subjectGraph(subjects - 1)

    def buildSubjectGraph(self):
        """Return the subject graph for this test"""
        return self.SUBJECTGRAPH % (self.subjectGraph(self.SUBJECTS))

    def buildEnableList(self):
        """Return the list of subjects to enable"""
        return [ "user%s" % (x) for x in range(1, self.SUBJECTS + 1) ]

    def measure(self, ssh=False):
        user = self.authserver.getSubject(name="user1")
        start = time.time()
        for i in range(self.COUNT):
            if ssh: self.ssh(self.pool.master, user, self.OPERATIONS["ssh"][0])
            else: self.cli(self.pool.master, user, self.OPERATIONS["cli"][0])
        end = time.time()
        if ssh: tag = "SSH"
        else: tag = "CLI"
        value = "%.3fms" % ((end - start) * 1000 / self.COUNT)
        xenrt.TEC().logverbose("%s authentication took %s." % (tag, value))
        xenrt.TEC().value(tag, value, "ms")
 
    def run(self, arglist):
        xenrt.TEC().logverbose("Testing authentication performance with "
                               "%s users in the subject list." % (self.SUBJECTS))
        self.runSubcase("measure", (False), "Measure", "CLI")
        self.runSubcase("measure", (True), "Measure", "SSH")
        
class TC8511(_ManySubjects):

    SUBJECTS = 100 
    COUNT = 100

class TC8406(_PoolAuthentication):
    """Test AD authentication works on a pool. (Enable/Disable)"""

    def modify(self):
        self.pool.disableAuthentication(self.authserver)
        self.valid.remove("user")

    def revert(self):
        self.pool.enableAuthentication(self.authserver)
        self.valid.append("user")

class TC8531(TC8406):
    """Test enabling and disabling AD on a large pool"""
    pass

class TC8480(_PoolAuthentication):
    """Test enabling AD using different admin credentials."""

    SUBJECTGRAPH = """
<subjects>
  <user name="user"/>
  <group name="Administrators">
    <user name="xenuser"/>
  </group>
  <group name="Domain Admins">
    <user name="xenuser"/>
  </group>
</subjects>
"""
    ENABLE = ["user"]

    def modify(self):
        self.pool.disableAuthentication(self.authserver)
        self.valid.remove("user")

    def revert(self):
        admin = self.authserver.getSubject(name="xenuser")
        self.superuser = self.authserver.place.superuser 
        self.password = self.authserver.place.password
        self.authserver.place.superuser = admin.name
        self.authserver.place.password = admin.password 
        self.pool.enableAuthentication(self.authserver)
        self.valid.append("user")

    def postRun(self):
        try: 
            self.authserver.place.superuser = self.superuser
            self.authserver.place.password = self.password
        except: pass
        _PoolAuthentication.postRun(self)

class TC8407(_PoolAuthentication):
    """Test host join and leave under AD authentication."""

    def modify(self):
        self.expelled = self.slaves[0]
        self.pool.eject(self.expelled)
        self.slaves.remove(self.expelled)
        self.others.append(self.expelled)
        self.expelled.disableAuthentication(self.authserver)

    def revert(self):
        self.expelled.enableAuthentication(self.authserver)
        self.pool.addHost(self.expelled, force=True)
        self.expelled.setDNSServer(self.authserver.place.getIP())  # CA-76402
        self.others.remove(self.expelled)
        self.slaves.append(self.expelled)

    def postRun(self):
        _PoolAuthentication.postRun(self)
        try: self.pool.addHost(self.expelled, force=True)
        except: pass

class TC8532(TC8407):
    """Test host pool join and leave under AD with a large pool"""
    pass

class TC8510(TC8407):
    """Test host join and leave under AD authentication
       using AD credentials for the join."""
    
    def revert(self):
        user = self.authserver.getSubject(name="user")
        self.expelled.enableAuthentication(self.authserver)
        self.pool.addHost(self.expelled,
                          user=user.name,
                          pw=user.password,
                          force=True)
        self.others.remove(self.expelled)
        self.slaves.append(self.expelled)

class TC8528(TC8510):
    """Test host pool join and leave under AD using AD authentication in a large pool"""
    pass

class TC8408(_PoolAuthentication):
    """Test host join with different AD configurations."""

    ALTAUTHSERVER = "ALTAUTHSERVER"

    def getHostTopology(self):
        _PoolAuthentication.getHostTopology(self)
        self.altauthserver = self.getAuthServer(self.ALTAUTHSERVER)

    def modify(self):
        self.expelled = self.slaves[0]
        self.pool.eject(self.expelled)
        self.slaves.remove(self.expelled)
        self.others.append(self.expelled)
        self.expelled.disableAuthentication(self.authserver)
        self.expelled.enableAuthentication(self.altauthserver)

    def revert(self):
        try:
            self.pool.addHost(self.expelled, force=True)
        except:
            pass
        else:
            raise xenrt.XRTFailure("Added slave with incongruent AD configuration.")
        self.expelled.disableAuthentication(self.altauthserver)
        self.expelled.enableAuthentication(self.authserver)
        self.pool.addHost(self.expelled, force=True)
        self.expelled.setDNSServer(self.authserver.place.getIP())  # CA-76402
        self.others.remove(self.expelled)
        self.slaves.append(self.expelled)

    def postRun(self):
        _PoolAuthentication.postRun(self)
        try: self.pool.addHost(self.expelled, force=True)
        except: pass

class TC8409(_PoolAuthentication):
    """Change pool master."""

    def modify(self):
        self.oldmaster = self.pool.master
        self.slaves.append(self.pool.master)
        self.pool.designateNewMaster(self.slaves[0])
        self.slaves.remove(self.pool.master)

    def revert(self):
        self.slaves.append(self.pool.master)
        self.pool.designateNewMaster(self.oldmaster)
        self.slaves.remove(self.pool.master)

class TC8534(TC8409):
    """Test changing the pool master under AD in a large pool"""
    pass

class TC8410(_PoolAuthentication):
    """Fail pool master."""  
    
    def modify(self):
        self.oldmaster = self.pool.master
        self.pool.syncDatabase()
        self.oldmaster.poweroff()
        self.pool.setMaster(self.slaves[0])
        self.slaves.remove(self.pool.master)
        
    def revert(self):
        self.oldmaster.poweron()
        self.oldmaster.setDNSServer(self.authserver.place.getIP())  # CA-76402
        self.slaves.append(self.oldmaster)

    def postRun(self):
        _PoolAuthentication.postRun(self)
        try: self.oldmaster.poweron()
        except: pass

class TC8535(TC8410):
    """Test pool failover under AD in a large pool"""
    pass

class TC8472(_PoolAuthentication):
    """AD authentication should still work after a slave reboot"""  
    
    NOREVERT = True

    def modify(self):
        self.slaves[0].reboot()
        self.slaves[0].setDNSServer(self.authserver.place.getIP())  # CA-76402

class TC8411(_PoolAuthentication):
    """Test host in a stuck state."""

    def modify(self):
        slave = self.slaves[0]
        slave.execdom0("/etc/init.d/xapi stop")
        try:
            self.pool.disableAuthentication(self.authserver)
        except xenrt.XRTFailure, e:
            if not ("The pool failed to disable the external authentication of at least one host" in e.data):
                raise
        else:
            raise xenrt.XRTFailure("Disabling authentication of missing host succeeded.")
        slave.startXapi()
        try:
            self.pool.enableAuthentication(self.authserver)
        except xenrt.XRTFailure, e:
            if not re.search("External authentication in this pool is already enabled", e.data):
                raise
            else:
                raise xenrt.XRTFailure("Heterogenous authentication config wasn't detected.")
        slave.disableAuthentication(self.authserver) 
        self.pool.enableAuthentication(self.authserver)

    def revert(self): pass

class TC10756(_AuthenticationBase):

    HOSTNAME = "abcdefghijklmnopqrstuvxyzabcdefghijklmnopqrstuvxyzabcdefghijk"

    SUBJECTGRAPH = """
<subjects>
  <user name="user"/>
</subjects>
"""
    ENABLE = ["user"]

    def modify(self):
        self.pool.disableAuthentication(self.authserver)
        self.hostname = self.pool.master.getMyHostName()
        self.pool.master.execdom0("hostname %s" % (self.HOSTNAME))
        self.pool.enableAuthentication(self.authserver)

    def revert(self):
        self.pool.disableAuthentication(self.authserver)
        self.pool.master.execdom0("hostname %s" % (self.hostname))
        self.pool.enableAuthentication(self.authserver)

class TC8473(_AuthenticationBase):
    """Make sure only root can log in through XSConsole."""   
 
    SUBJECTGRAPH = """
<subjects>
  <user name="user"/>
</subjects>
"""
    ENABLE = ["user"]

    def authenticated(self):
        self.xsc.activate("CHANGE_PASSWORD")
        data = self.xsc.screengrab()
        self.xsc.reset()
        if re.search("Please log in", data): return False
        else: return True

    def prepare(self, arglist):
        _AuthenticationBase.prepare(self, arglist)
        self.xsc = self.pool.master.getXSConsoleInstance()
        if self.authenticated():
            self.xsc.activate("LOGINOUT")
            self.xsc.reset()

    def run(self, arglist):
        self.xsc.activate("LOGINOUT")
        for x in ["u", "s", "e", "r"]: self.xsc.keypress(x)
        self.xsc.keypress("KEY_ENTER")
        for x in self.pool.master.password: self.xsc.keypress(x)
        self.xsc.keypress("KEY_ENTER")
        data = self.xsc.screengrab()
        self.xsc.check(fail=True)
        self.xsc.keypress("KEY_ENTER")
        if not re.search("Only root can log in here", data):
            raise xenrt.XRTFailure("Got an unexpected login response.")
        if self.authenticated():
            raise xenrt.XRTFailure("Login suceeded.")

class _Expel(_AuthenticationBase):
    """Base class for expulsion tests."""

    SESSIONSPERUSER = 2

    SUBJECTGRAPH = """
<subjects>
  <group name="groupone">
    <user name="userone"/>
    <user name="usertwo"/>
  </group>
</subjects>
"""
    
    ENABLE = ["groupone"]

    def prepare(self, arglist):
        _AuthenticationBase.prepare(self, arglist)
        self.sessions = {}        
        for user in filter(lambda x:not isinstance(x, xenrt.ActiveDirectoryServer.Local), self.users):
            self.sessions[user.name] = []
            for i in range(self.SESSIONSPERUSER):
                s = self.getSession(user)
                self.sessions[user.name].append(s)
        for user in self.sessions:
            xenrt.TEC().logverbose("Checking if %s is logged in." % (user))
            for session in self.sessions[user]:
                xenrt.TEC().logverbose("Checking session: %s" % (session._session))
                self.checkSession(session, loggedin=True)
    
    def getSession(self, subject):
        fullname = u"%s\\%s" % (subject.server.domainname, subject.name)
        session = self.pool.master.getAPISession(fullname, subject.password)
        xenrt.TEC().logverbose("Created session for user %s: %s" % 
                               (fullname.encode("utf-8"), session._session))
        return session

    def checkSession(self, session, loggedin=True):
        reply = session.VM.get_all_records(session.handle)
        if loggedin:
            if not reply["Status"] == "Success":
                raise xenrt.XRTError("Call using logged in session failed.")
        else:
            if not reply["Status"] == "Failure":
                raise xenrt.XRTFailure("Call using logged out session succeeded.")
            else:
                if not reply["ErrorDescription"][0] == "SESSION_INVALID":
                    raise xenrt.XRTFailure("Call failed but with odd error (%s)." % (reply))

class TC8717(_Expel):
    """Test expelling all users."""
    
    def run(self, arglist):
        xenrt.TEC().logverbose("Expelling all users.")
        self.pool.master.logoutAll()

        for user in self.sessions:
            xenrt.TEC().logverbose("Checking if %s is logged out." % (user))
            for session in self.sessions[user]:
                xenrt.TEC().logverbose("Checking session: %s" % (session._session))
                self.checkSession(session, loggedin=False)

class TC8718(_Expel):
    """Test expelling a particular user."""

    def run(self, arglist):
        expeluser, expelsessions = self.sessions.popitem()
        xenrt.TEC().logverbose("Trying to log out user %s." % (expeluser))
        self.pool.master.logout(self.authserver.getSubject(name=expeluser))

        for user in self.sessions:
            xenrt.TEC().logverbose("Checking if %s is logged in." % (user))
            for session in self.sessions[user]:
                xenrt.TEC().logverbose("Checking session: %s" % (session._session))
                self.checkSession(session, loggedin=True)
        xenrt.TEC().logverbose("Checking if %s is logged out." % (expeluser))
        for session in expelsessions:
            xenrt.TEC().logverbose("Checking session: %s" % (session._session))
            self.checkSession(session, loggedin=False)
        
class TC8719(_Expel):
    """Test a user expelling themselves."""

    def run(self, arglist):
        expeluser, expelsessions = self.sessions.popitem()
        expeluser = self.authserver.getSubject(name=expeluser)
        expelsid = self.pool.master.getSubjectSID(expeluser)
        s = self.getSession(expeluser)
        xenrt.TEC().logverbose("Using user %s with session %s to log out %s." % 
                               (expeluser.name, s._session, expeluser.name))
        reply = s.session.logout_subject_identifier(s.handle, expelsid)
        if reply["Status"] == "Failure":
            raise xenrt.XRTError(reply)

        for user in self.sessions:
            xenrt.TEC().logverbose("Checking if %s is logged in." % (user))
            for session in self.sessions[user]:
                xenrt.TEC().logverbose("Checking session: %s" % (session._session))
                self.checkSession(session, loggedin=True)

        xenrt.TEC().logverbose("Checking if %s is logged out." % (expeluser.name))
        for session in expelsessions:
            xenrt.TEC().logverbose("Checking session: %s" % (session._session))
            self.checkSession(session, loggedin=False)
        xenrt.TEC().logverbose("Checking session used to log out. (%s)" % (s._session))
        self.checkSession(s, loggedin=True)
        self.pool.master.logoutAPISession(s)
 
class TC8415(xenrt.TestCase):
    """Test session timeouts work."""

    # The absolute upper bound on timeouts is 45 minutes.
    TIMEOUT = 2700

    # Allow some slop time beyond the end of this.
    SLOPTIME = 180

    # Check session every INTERVAL seconds.
    INTERVAL = 10

    AUTHTYPE = "AD"
    AUTHSERVER = "AUTHSERVER"

    SUBJECTGRAPH = """
<subjects>
  <group name="groupone">
    <group name="grouptwo">
      <user name="userone"/>
    </group>
  </group>
</subjects>
"""

    def getAuthServer(self, name):
        if self.AUTHTYPE == "AD":
            authserver = self.getGuest(name)
            if not authserver and xenrt.TEC().lookup("INSTALL_AUTHSERVER",
                                                     False,
                                                     boolean=True):
                authserver = xenrt.lib.xenserver.guest.createVM(\
                    self.getDefaultHost(),
                    name,
                    distro=xenrt.TEC().lookup("DEFAULT_AD_SERVER_DISTRO",
                                              "ws08sp2-x86"),
                    vifs=xenrt.lib.xenserver.Guest.DEFAULT)
                self.uninstallOnCleanup(authserver)
                self.getLogsFrom(authserver)
                authserver.installDrivers()
                authserver.installPowerShell()
                authserver.enablePowerShellUnrestricted()
            return authserver.getActiveDirectoryServer()
        elif self.AUTHTYPE == "PAM":
            authserver = self.getHost(name)
            return xenrt.PAMServer(authserver)

    def checkSession(self, session):
        result = self.rpc.VM.get_all_records(session)
        if result["Status"] == "Success": 
            return True
        if "SESSION_INVALID" in result["ErrorDescription"]: 
            return False
        raise xenrt.XRTError("Unexpected error during API call. (%s)" % 
                             (result["ErrorDescription"]))

    def prepare(self, arglist):
        host = self.getDefaultHost()
        self.host = host
        self.pool = xenrt.lib.xenserver.host.poolFactory(host.productVersion)(host) 
        
        self.authserver = self.getAuthServer(self.AUTHSERVER)
        self.authserver.createSubjectGraph(self.SUBJECTGRAPH)

        self.pool.enableAuthentication(self.authserver)
        self.user = self.authserver.getSubject(name="userone")
        self.parentgroup = self.authserver.getSubject(name="groupone")
        self.childgroup = self.authserver.getSubject(name="grouptwo")
        self.pool.allow(self.parentgroup, "pool-admin")
        try: 
            self.rpc = xmlrpclib.ServerProxy("https://%s" % (self.pool.master.getIP()))
        except Exception, e:
            raise xenrt.XRTError("Couldn't connect to host using XML-RPC. (%s)" % (str(e)))

    def getSession(self, user):
        try:
            session = self.rpc.session.login_with_password("%s\\%s" % 
                                                           (user.server.domainname, user.name),
                                                            user.password)["Value"] 
        except Exception, e:
            raise xenrt.XRTError("Couldn't login to host. (%s)" % (str(e)))
        return session

    def run(self, arglist):
        session = self.getSession(self.user)
        if not self.checkSession(session):
            raise xenrt.XRTError("Session not authenticated before starting test.")

        self.parentgroup.removeSubject(self.childgroup)
        start = xenrt.timenow()
        xenrt.TEC().logverbose("Removed user %s from allowed group at %s." % 
                               (self.user.name, time.strftime("%H:%M:%S", time.gmtime(start))))
        xenrt.TEC().logverbose("Checking session's access permissions at %ss intervals." % 
                               (self.INTERVAL))
        xenrt.TEC().logverbose("Expecting timeout to expire at %s." % 
                               (time.strftime("%H:%M:%S", time.gmtime(start + self.TIMEOUT))))

        while xenrt.timenow() < start + self.TIMEOUT + self.SLOPTIME:
            # Check if authentication has failed before the timeout. This is a good thing.
            if not self.checkSession(session): return
            else: xenrt.TEC().logverbose("Session still authenticated at %s." % 
                                         (time.strftime("%H:%M:%S",
                                          time.gmtime(xenrt.timenow()))))
            time.sleep(self.INTERVAL)
        
        if self.checkSession(session):
            raise xenrt.XRTFailure(\
                "Session still authenticated after revocation timeout",
                "Session still authenticated at %s even though timeout "
                "was at %s." % 
                (time.strftime("%H:%M:%S", time.gmtime(xenrt.timenow())),
                 time.strftime("%H:%M:%S", time.gmtime(start + self.TIMEOUT))))

    def postRun(self):
        try: self.host.deny(self.parentgroup) 
        except: pass
        try: self.pool.disableAuthentication(self.authserver)
        except: pass
        try: self.authserver.removeSubject(self.user.name)
        except: pass
        try: self.authserver.removeSubject(self.parentgroup.name)
        except: pass
        try: self.authserver.removeSubject(self.childgroup.name)
        except: pass

class TC8414(xenrt.TestCase):
    """Test single sign-on."""

    ADSERVER = "ADSERVER"
    CLIENT = "CLIENT"
    AUTHTYPE = None
    AUTHSERVER = None

    SUBJECTGRAPH = """
<subjects>
  <user name="user1"/>
  <user name="user2"/>
</subjects>
"""

    def getAuthServer(self, name):
        if self.AUTHTYPE == "AD":
            authserver = self.getGuest(name)
            return authserver.getActiveDirectoryServer()
        elif self.AUTHTYPE == "PAM":
            authserver = self.getHost(name)
            return xenrt.PAMServer(authserver)

    def runGUITest(self):
        logdir = self.remoteLoggingDirectory(self.client)
        path, exe = self.client.findCarbonWindowsGUI()
        if not (path and exe): raise xenrt.XRTError("GUI not found on client.")
        command = []
        command.append('cd %s' % (path))
        command.append('%s runtests host=\"%s\" "log_directory=%s" --wait' % 
                       (exe, self.host.getIP(), logdir))
        self.client.xmlrpcExec(string.join(command, "\n"), timeout=7200)

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.pool = xenrt.lib.xenserver.host.poolFactory(self.host)

        self.authserver = self.getAuthServer(self.AUTHSERVER)
        self.authserver.createSubjectGraph(self.SUBJECTGRAPH)

        self.user1 = self.authserver.getSubject(name="user1")
        self.user2 = self.authserver.getSubject(name="user2")

        self.client = xenrt.TEC().registry.guestGet(self.CLIENT)
        self.client.joinDomain(self.authserver)

        self.pool.enableAuthentication(self.authserver)
        self.pool.allow(self.user1, "pool-admin")

    def run(self, arglist):
        self.client.configureAutoLogon(self.user1)
        self.client.reboot()
        self.runGUITest()        
        self.client.configureAutoLogon(self.user2)
        self.client.reboot()
        try:
            self.runGUITest()
        except: 
            xenrt.TEC().logverbose("GUI test with invalid credentials failed.") 
        else:
            raise xenrt.XRTFailure("GUI test with invalid credentials succeeded.")

    def postRun(self):
        try: 
            self.client.configureAutoLogon()
            self.client.reboot()
        except: pass
        try: self.client.leaveDomain(self.authserver)
        except: pass
        try: self.pool.deny(self.user2)
        except: pass
        try: self.authserver.removeSubject(self.user1.name)
        except: pass
        try: self.authserver.removeSubject(self.user2.name)
        except: pass
        try: self.pool.disableAuthentication(self.authserver)
        except: pass

class TC8416(_AuthenticationBase):
    """Test changing local password."""

    SUBJECTGRAPH = """
<subjects>
  <user name="user"/>
</subjects>
"""

    ENABLE = ["user"]   

    def changePassword(self, password):
        self.OPERATIONS["cli"] = [CLICall("user-password-change",
                                           parameters=["old=%s" % (self.pool.master.password), \
                                                       "new=%s" % (password)], context=self.context)]
        try: 
            self.cli(self.pool.master, self.authserver.getSubject(name="user"), self.OPERATIONS["cli"][0])
        except: 
            xenrt.TEC().logverbose("Failed to set password as expected.")
        else: 
            raise xenrt.XRTFailure("Set password with AD credentials.")
        try: 
            self.cli(self.pool.master, xenrt.ActiveDirectoryServer.Local("root", self.pool.master.password), self.OPERATIONS["cli"][0])
        except: 
            raise xenrt.XRTFailure("Failed to set password with local credentials.") 
        for user in self.users:
            if user.name == "root": user.password = password 
        self.pool.master.password = password
        self.OPERATIONS["cli"] = [CLICall("vm-list", context=self.context)]

    def modify(self):
        self.changePassword("newpassword")

    def revert(self):
        self.changePassword(xenrt.TEC().lookup("ROOT_PASSWORD"))

class TC8352(_CCSetup):
    """Change local root password with user-password-change"""
    LICENSE_SERVER_REQUIRED = False

    def prepare(self, arglist):
        _CCSetup.prepare(self, arglist)
        self.cli = self.host.getCLIInstance()

    def run(self, arglist): 
        self.cli.execute("user-password-change old=%s new=pw8352" % (self.host.password))
        self.cli.execute("vm-list", password="pw8352")
        try: self.cli.execute("vm-list", password=self.host.password)
        except: xenrt.TEC().logverbose("Operation using old password failed as expected.")
        else: raise xenrt.XRTFailure("Could still use the old password to authenticate.")
        try: self.cli.execute("user-password-change old=pw8352 new=%s" % (self.host.password), password="pw8352")
        except: pass

    def postRun(self):
        try: self.cli.execute("user-password-change old=pw8352 new=%s" % (self.host.password), password="pw8352")
        except: pass
        _CCSetup.postRun(self)

class TC8353(xenrt.TestCase):
    """Local root password change with user-password-change should be rejected if the old password is incorrect"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.cli = self.host.getCLIInstance()

    def changePassword(self, oldpassword):
        try: self.cli.execute("user-password-change %s new=%s" % 
                              (oldpassword, "pw8353"))
        except xenrt.XRTFailure, e: xenrt.TEC().logverbose("Password change failed as expected.")
        else: raise xenrt.XRTFailure("Password change successful with invalid old password.")

        try: self.cli.execute("vm-list", username="root", password="pw8353")  
        except xenrt.XRTFailure, e: xenrt.TEC().logverbose("Operation failed as expected.")
        else: raise xenrt.XRTFailure("Operation successful with invalid password.")

    def run(self, arglist):
        self.runSubcase("changePassword", ("old=XXXinvalidXXX"), "changePassword", "Invalid")
        try: self.cli.execute("user-password-change old=pw8353 new=xensource",
                               username="root", password="pw8353")
        except: pass
        self.runSubcase("changePassword", (""), "changePassword", "Empty")
        try: self.cli.execute("user-password-change old=pw8353 new=xensource",
                               username="root", password="pw8353")
        except: pass

class TC8396(xenrt.TestCase):
    """Verify that root password is not present in install-log"""

    def run(self, arglist=None):
        host = self.getDefaultHost()
        host.findPassword()

        # After build 12455 install-log is dropped in /var/log/installer rather
        # than /root
        if isinstance(host, xenrt.lib.xenserver.Host) and not host.productVersion == 'Orlando':
            lf = "/var/log/installer/install-log"
        else:
            lf = "/root/install-log"

        # The grep -v is because the normal root password also ends up in the
        # ssh key...
        data = host.execdom0("grep %s %s | "
                             "grep -v xensource\.com | grep -v opt/xensource | "                
                             "grep -v etc/xensource || true" % (host.password, lf))
        if len(data.strip()) > 0:
            raise xenrt.XRTFailure("root password found in install-log",
                                    data=data)

class TC9073(xenrt.TestCase):
    """Verify that leaving a domain removes the host from the AD server."""

    ADSERVER = "AUTHSERVER"
    AUTHTYPE = "AD"

    def getAuthServer(self, name):
        if self.AUTHTYPE == "AD":
            authserver = self.getGuest(name)
            return authserver.getActiveDirectoryServer()
        elif self.AUTHTYPE == "PAM":
            authserver = self.getHost(name)
            return xenrt.PAMServer(authserver)

    def run(self, arglist):
        host = self.getDefaultHost()
        version = host.productVersion
        self.pool = xenrt.lib.xenserver.host.poolFactory(version)(host) 
        self.authserver = self.getAuthServer(self.ADSERVER)
        
        self.hostname = string.upper(self.pool.master.getMyHostName())

        self.pool.enableAuthentication(self.authserver)
        
        if not self.hostname in self.authserver.getAllComputers():    
            raise xenrt.XRTFailure("Host not present on AD server after "
                                   "enabling authentication.")

        self.pool.disableAuthentication(self.authserver, disable=True)
        
        disabled = self.authserver.place.xmlrpcExec("dsquery computer -disabled",
                                                     returndata=True)
        if not re.search(self.hostname, disabled):
            raise xenrt.XRTError("Host doesn't appear to be disabled")

    def postRun(self):
        try: self.pool.disableAuthentication(self.authserver)
        except: pass
        try: 
            self.authserver.place.xmlrpcExec("dsmod computer CN=%s,CN=Computers,DC=%s,DC=%s -disabled no" % 
                                            ((self.hostname,) + tuple(self.authserver.domainname.split("."))))
        except: pass

class TC10179(_CCSetup):
    """Regression test for CA-33730"""
    LICENSE_SERVER_REQUIRED = False

    def run(self, arglist=None):
        host = self.getDefaultHost()
        cli = host.getCLIInstance()

        # Try and perform host-get-system-status-capabilities without authentication
        # It should return an error
        try:
            cli.execute("host-get-system-status-capabilities", useCredentials=False)
        except xenrt.XRTFailure, e:
            if not re.search("Authentication failed", e.reason):
                raise xenrt.XRTError("Command failed as expected but with unexpected error",
                                     data="Expecting 'Authentication failed', found %s" % (e.reason))
        else:
            raise xenrt.XRTFailure("CA-33730 Able to execute remote "
                                   "local_session CLI command without authentication")

class TC10324(_AuthenticationBase):
    """Smoke test the PAM external authentication plug-in."""

    AUTHTYPE = "PAM"
    AUTHSERVER = "RESOURCE_HOST_0"

    SUBJECTGRAPH = """
<subjects>
  <user name="user1"/>
  <group name="group2">
    <user name="user2"/>
  </group>
</subjects>
"""

    ENABLE = ["user1", "group2"]

    NOMODIFY = True
    NOREVERT = True 

class TC10557(xenrt.TestCase):
    """Likewise lsassd should not leak memory with repeated authentications."""

    SUBJECTGRAPH = """
<subjects>
  <group name="TC10557group1">
    <user name="TC10557user"/>
    <group name="TC10557group2">
      <user name="TC10557user"/>
    </group>
  </group>
</subjects>
    """

    ROUNDS = 5000
    FAILLIMIT = 2
    WARNLIMIT = 1

    def prepare(self, arglist):
        self.pool = None
        self.host = self.getDefaultHost()
        
        # Create an AD server
        self.authguest = xenrt.lib.xenserver.guest.createVM(\
            self.host,
            xenrt.randomGuestName(),
            distro=xenrt.TEC().lookup("DEFAULT_AD_SERVER_DISTRO", "ws08sp2-x86"),
            vifs=xenrt.lib.xenserver.Guest.DEFAULT)
        self.getLogsFrom(self.authguest)
        self.uninstallOnCleanup(self.authguest)
        self.authguest.installDrivers()
        self.authguest.installPowerShell()
        self.authguest.enablePowerShellUnrestricted()
        self.authserver = self.authguest.getActiveDirectoryServer()

        # Make a pool of one host using AD auth
        self.pool = xenrt.lib.xenserver.host.poolFactory(\
            self.host.productVersion)(self.host) 
        self.pool.enableAuthentication(self.authserver)

        # Create an account for authentication
        self.authserver.createSubjectGraph(self.SUBJECTGRAPH)
        self.subject = self.authserver.getSubject(name="TC10557user")
        self.pool.allow(self.subject, "pool-admin")

        # Run an authentication loop for one hour to stabilise lsassd
        # memory usage
        xenrt.TEC().logverbose("Stabilising lsassd by authenticating for "
                               "one hour")
        cli = self.host.getCLIInstance()
        endat = xenrt.timenow() + 3600
        i = 0
        while True:
            if xenrt.timenow() > endat:
                break
            xenrt.TEC().logverbose("Stabilisation loop iteration %u" % (i))
            cli.execute("vm-list",
                        username=self.subject.name,
                        password=self.subject.password)
            if i % 100 == 99:
                vsizei, rssi = self.getDaemonSize()
                xenrt.TEC().logverbose("lsassd size after stabilisation "
                                       "iteration %u is %ukB virtual, %ukB RSS"
                                       % (i, vsizei, rssi))
            i = i + 1
        xenrt.TEC().logverbose("Completed stabilisation loop")

    def getDaemonSize(self):
        """Return a pair (virtsize, rss) of the lsassd size in kB"""
        vsize = 0
        rss = 0
        x = self.host.execdom0("ps -C lsassd -o vsize,rss --no-headers").split()
        for i in range(len(x)):
            if i % 2 == 0:
                vsize = vsize + int(x[i])
            else:
                rss = rss + int(x[i])
        return vsize, rss


    def run(self, arglist):

        history = []

        # Record the memory usage of lsassd
        vsize, rss = self.getDaemonSize()
        xenrt.TEC().comment("lsassd size before test is %ukB virtual, %ukB RSS"
                            % (vsize, rss))

        # Authenticate $ROUNDS times
        cli = self.host.getCLIInstance()
        for i in range(self.ROUNDS):
            xenrt.TEC().logverbose("Loop iteration %u" % (i))
            cli.execute("vm-list",
                        username=self.subject.name,
                        password=self.subject.password)
            if i % 100 == 99:
                vsizei, rssi = self.getDaemonSize()
                xenrt.TEC().logverbose("lsassd size after iteration %u is "
                                       "%ukB virtual, %ukB RSS"
                                       % (i, vsizei, rssi))
                history.append({'round': i, 'vsize': vsizei, 'rss': rssi})
                time.sleep(random.randint(1, 5))

        # Check the memory usage of lsassd is around what it was before
        vsize2, rss2 = self.getDaemonSize()
        xenrt.TEC().comment("lsassd size after test is %ukB virtual, %ukB RSS"
                            % (vsize2, rss2))
        
        if rss2 - rss >= self.FAILLIMIT * xenrt.KILO:
            raise xenrt.XRTFailure("lsassd RSS grown by more than %dMB" % self.FAILLIMIT)
        elif rss2 - rss >= self.WARNLIMIT * xenrt.KILO:
            step = self.ROUNDS / 3
            phase3 = history[-1]['rss'] - history[-1 - step]['rss']            
            phase2 = history[-1 - step]['rss'] - history[-1 - 2 * step]['rss']
            phase1 = history[-1 - 2 * step]['rss'] - history[-1 - 3 * step]['rss']
            if phase3 <= 0 or phase3 <= phase2 <= phase1:
                xenrt.TEC().warning("lsassd RSS grown by more than %dMB" % self.WARNLIMIT)
            else:
                xenrt.XRTFailure("lsassd RSS grown between %dMB and %dMb with an increasing trend" % 
                                 (self.WARNLIMIT, self.FAILLIMIT))
        else:
            xenrt.TEC().logverbose("lsassd RSS grown by less than %dMB" % self.WARNLIMIT)

        xenrt.TEC().logverbose(history)
            

    def postRun(self):
        if self.pool:
            try:
                self.pool.disableAuthentication(self.authserver)
            except:
                pass
            self.host.pool = None

class TC10666(xenrt.TestCase):
    """A host should be able to leave one AD domain, join another and use it for authentication"""

    ADSERVERS = ["AUTHSERVER", "ALTAUTHSERVER"]
    AUTHTYPE = "AD"

    def getAuthServer(self, name):
        if self.AUTHTYPE == "AD":
            authserver = self.getGuest(name)
            return authserver.getActiveDirectoryServer()
        elif self.AUTHTYPE == "PAM":
            authserver = self.getHost(name)
            return xenrt.PAMServer(authserver)

    def prepare(self, arglist):
        if xenrt.TEC().lookup("TC10666_INSTALL_AD_VMS", False, boolean=True):
            for name in self.ADSERVERS:
                authguest = xenrt.lib.xenserver.guest.createVM(\
                    self.getDefaultHost(),
                    name,
                    distro=xenrt.TEC().lookup("DEFAULT_AD_SERVER_DISTRO",
                                              "ws08sp2-x86"),
                    vifs=xenrt.lib.xenserver.Guest.DEFAULT)
                self.uninstallOnCleanup(authguest)
                self.getLogsFrom(authguest)
                authguest.installDrivers()
                authguest.installPowerShell()
                authguest.enablePowerShellUnrestricted()
                xenrt.GEC().registry.guestPut(name, authguest)

        # Join the host to the first domain, add a user, check auth and
        # leave the domain
        host = self.getDefaultHost()
        if host.pool:
            self.pool = host.pool
        else:
            # Standalone host, create a dummy pool object
            version = host.productVersion        
            self.pool = xenrt.lib.xenserver.host.poolFactory(version)(host) 
        self.authserver0 = self.getAuthServer(self.ADSERVERS[0])
        self.hostname = string.upper(self.pool.master.getMyHostName())
        self.pool.enableAuthentication(self.authserver0)

        if not self.hostname in self.authserver0.getAllComputers():    
            raise xenrt.XRTFailure("Host not present on AD server after "
                                   "enabling authentication.")

        # Create an account for authentication
        self.subject0 = self.authserver0.addUser("TC10666user0")
        self.pool.allow(self.subject0, "pool-admin")
        self.sid0 = self.pool.master.getSubjectSID(self.subject0)

        # Check auth
        self.pool.getCLIInstance().execute("vm-list",
                                           username=self.subject0.name,
                                           password=self.subject0.password)

        # Leave the domain
        self.pool.disableAuthentication(self.authserver0, disable=True)

        # Second AD server
        self.authserver1 = self.getAuthServer(self.ADSERVERS[1])

    def run(self, arglist):

        # Join the second domain
        self.pool.enableAuthentication(self.authserver1)

        if not self.hostname in self.authserver1.getAllComputers():    
            raise xenrt.XRTFailure("Host not present on AD server after "
                                   "enabling authentication.")
        
        # Create an account for authentication
        self.subject1 = self.authserver1.addUser("TC10666user1")
        self.pool.allow(self.subject1, "pool-admin")

        # Check auth
        self.pool.getCLIInstance().execute("vm-list",
                                           username=self.subject1.name,
                                           password=self.subject1.password)

        # Check a likewise lookup for the old SID fails in a suitable way
        ok = True
        try:
            if self.pool.master.execdom0("test -e /opt/pbis", retval="code") == 0:
                self.pool.master.execdom0("/opt/pbis/bin/find-by-sid %s" % 
                                      (self.sid0))
            else:
                self.pool.master.execdom0("/opt/likewise/bin/lw-find-by-sid %s" % 
                                      (self.sid0))
            ok = False
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose("Caught exception: %s" % (str(e)))
            if not "Failed to locate SID." in e.data:
                raise xenrt.XRTFailure("Unexpected error from lw-find-by-sid "
                                       "on a SID from the old domain: %s" % 
                                       (e.data))
        if not ok:
            raise xenrt.XRTFailure("lw-find-by-sid did not fail on a SID "
                                   "from the old domain")

        # Check auth
        self.pool.getCLIInstance().execute("vm-list",
                                           username=self.subject1.name,
                                           password=self.subject1.password)

    def postRun(self):
        try: self.pool.master.clearSubjectList()
        except: pass
        try: self.pool.disableAuthentication(self.authserver1)
        except: pass
        try: self.pool.disableAuthentication(self.authserver0)
        except: pass
        try: 
            self.authserver0.place.xmlrpcExec("dsmod computer CN=%s,CN=Computers,DC=%s,DC=%s -disabled no" % 
                                            ((self.hostname,) + tuple(self.authserver0.domainname.split("."))))
        except: pass
        try: 
            self.authserver1.place.xmlrpcExec("dsmod computer CN=%s,CN=Computers,DC=%s,DC=%s -disabled no" % 
                                            ((self.hostname,) + tuple(self.authserver1.domainname.split("."))))
        except: pass

class TC11217(xenrt.TestCase):
    """Regression test for CA-37980: Check Async API calls get recorded in the audit log."""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()

    def run(self, arglist):
        xmlrpc = xmlrpclib.ServerProxy("http://%s" % (self.host.getIP()))
        session = xmlrpc.session.login_with_password("root", self.host.password)["Value"]
        
        task = xmlrpc.Async.VM.clean_shutdown(session, "00000000-0000-0000-0000-000000000000")["Value"]
        while xmlrpc.task.get_all_records(session)["Value"][task]["progress"] < 1.0:
            time.sleep(10)
        
        self.host.execdom0("gzip -d /var/log/audit.log.*.gz", level=xenrt.RC_OK)  # We need to unzip any zipped logs
        data = self.host.execdom0("grep Async.VM.clean_shutdown /var/log/audit.log*")
        t = re.findall("\d{8}T\d{2}:\d{2}:\d{2}", data)
        t = map(lambda x:time.mktime(time.strptime(x, "%Y%m%dT%H:%M:%S")), t)
        if xenrt.timenow() - max(t) > 300:
            raise xenrt.XRTFailure("Saw an audit message but it was a while ago. (%ss)" % (xenrt.timenow() - max(t)))

class TC11497(TC8400):
    """check if users with the flag 'Do not require Kerberos preauthentication' can log in twice in a sequence"""

    SUBJECTGRAPH = """
<subjects>
  <user name="user" dontPreauthenticate="True"/>
</subjects>
"""

class TC11499(xenrt.TestCase):
    """Regression test for CVE-2009-3555"""

    def prepare(self, arglist):
        self.hostA = self.getHost("RESOURCE_HOST_0")
        self.hostB = self.getHost("RESOURCE_HOST_1")

        # Stop the firewall on hostA
        self.hostA.execdom0("service iptables stop")

    def run(self, arglist):
        workdirA = self.hostA.hostTempDir()
        if self.hostA.execdom0("cat /proc/sys/net/ipv6/conf/all/disable_ipv6 || true").strip() == "1":
            xenrt.TEC().logverbose("Working around ipv6 being disabled, which breaks openssl s_server...")
            self.hostA.execdom0("echo 0 > /proc/sys/net/ipv6/conf/all/disable_ipv6")
            self.hostA.execdom0("/sbin/ip addr add ::2/128 scope global dev lo")

        try:
            self.hostA.execdom0("(sleep 60 && echo 'Q') 2>&1 < /dev/null | openssl s_server -cert /etc/xensource/xapi-ssl.pem -debug > %s/opensslA.log 2>&1 &" % (workdirA))
            self.hostB.execdom0("(sleep 5; echo 'R'; sleep 5; echo 'Q'; sleep 5) | openssl s_client -connect %s:4433" % (self.hostA.getIP()))

            time.sleep(15)
            if self.hostA.execdom0("grep 'Secure Renegotiation IS supported' %s/opensslA.log" % (workdirA), retval="code") != 0:
                raise xenrt.XRTFailure("Host appears vulnerable to CVE-2009-3555")
        finally:
            # Try and get logs
            try:
                self.hostA.execdom0("cat %s/opensslA.log || true" % (workdirA))
            except:
                pass

    def postRun(self):
        self.hostB.execdom0("killall openssl || true")
        self.hostA.execdom0("killall openssl || true")

        # Reboot hostA to ensure iptables is restored and any ipv6 config is lost
        self.hostA.reboot()

class TC11689(TC8400):
    """check the username is present in the audit.log even when user is logged in via group in subject-list"""

    SUBJECTGRAPH = """
<subjects>
  <group name="group">
    <user name="user"/>
  </group>
</subjects>
"""

    def run(self, arglist):
        TC8400.run(self, arglist)
        
        # session.login_with_password D:3f81e4fa7aca|audit] ('trackid=be13e3d81005f54516084c8a8ae57912' 'S-1-5-21-643717832-1169962007-1248025249-1127' 'XENRTXENRT30997\\user' 'ALLOWED' 'OK' 'API' 'session.create' (('uname' 'xenrt30997.local\\user' '' '')))
        host = self.getDefaultHost()        
        host.execdom0("gzip -d /var/log/audit.log.*.gz", level=xenrt.RC_OK)  # We need to unzip any zipped logs
        data = host.execdom0("grep login_with_password /var/log/audit.log*")
        m = re.match(".+'(XENRTXENRT[^']+\\\\user)'.+", data, re.S | re.M)
        
        if not m:
            raise xenrt.XRTFailure("User not written to audit log.")
        else:
            xenrt.TEC().logverbose("User %s written to audit log." % m.group(1))

class TCRetinaScan(xenrt.TestCase):

    RETINA_SCAN_TIMEOUT = 43200
    RETINA_SCAN_START = 'https://onescan.eng.citrite.net/scan/start?profile=%s&targetip=%s&component=%s&token=7a55f828959b4dbf8441d94b87b03ac5'
    RETINA_SCAN_STATUS = 'https://onescan.eng.citrite.net/scan/status?scan=%s'

    def prepare(self, arglist):
        self.host = self.getDefaultHost()

        self.scanType = '3'
        self.component = 'XenServer%%20%s%%20build%%20%s' % (self.host.productVersion, self.host.productRevision.split('-')[1])

    def run(self, arglist):
        # Issue the GET request to initiate the scan
        xenrt.TEC().comment("Initiating scan: Type = %s, Host IP = %s, Component = %s" % (self.scanType, self.host.getIP(), self.component))

        rValue = xenrt.util.getHTTP(self.RETINA_SCAN_START % (self.scanType, self.host.getIP(), self.component))
        
        result = ast.literal_eval(rValue)
        if result.has_key('error'):
            raise xenrt.XRTError('Failed to initiate Retina Scan: Code: %s, Msg: %s' % (result['error']['code'], result['error']['msg']))
        elif result.has_key('scan'):
            scanId = result['scan']
            xenrt.TEC().comment('Retina Scan initiated.  Scan ID: %s' % (scanId))
        else:
            raise xenrt.XRTError('Invalid response from Retina Scan initiation') 
        # Wait for the scan to complete
        deadline = xenrt.util.timenow() + self.RETINA_SCAN_TIMEOUT

        while xenrt.util.timenow() < deadline:
            time.sleep(60)

            rValue = xenrt.util.getHTTP(self.RETINA_SCAN_STATUS % (scanId))
            # Convert output to correct format
            rValue = re.sub('false', 'False', rValue)
            rValue = re.sub('true', 'True', rValue)

            result = ast.literal_eval(rValue)
            xenrt.TEC().comment('Retina Scan status: %s' % (result))
            if result.has_key('error'):
                raise xenrt.XRTError('Retina Scan failed: Code: %s, Msg: %s' % (result['error']['code'], result['error']['msg']))
            elif result.has_key('status'):
                if result['status']['complete']:
                    xenrt.TEC().comment('Retina Scan Completed')
                    return
            else:
                raise xenrt.XRTError('Invalid response from Retina Scan status')

class TC17802(xenrt.TestCase):
    """Regression test for CA-83267 (vncterm vt100 escape handling)"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)

    def run(self, arglist):

        # Find the vncterm PID
        domid = self.guest.getDomid()
        vncterms = self.host.execdom0("ps -C vncterm -o pid,args")
        m = re.search("(\d+) \S+vncterm.+/local/domain/%d" % domid, vncterms)
        if not m:
            raise xenrt.XRTError("Unable to identify vncterm PID")
        pid = int(m.group(1))

        # Send the bad escape sequence
        self.guest.execguest("""#!/bin/bash

csi0() {
	local final
	final=$1
	echo -n $'\x1b''[' > /dev/console
	for ((n=0; n < 512000; n=n+1)); do
		echo -n "1;" > /dev/console
	done
	echo $final
}

# csi overflow
csi(){
	csi0 1m
	csi0 1l
	csi0 1h
}

gen_csi0() {
	echo -n $'\x1b''['  > /dev/console
	echo -n $1 > /dev/console # number
	echo -n $2 > /dev/console # operation
	# some output to try writing characters in strange locations
	echo test > /dev/console
}

gen_csi() {
	local op
	local i
	op=$1
	# last number cause number overflow
	for i in 0 1 2 100 1000 10000 100000 1000000 10000000 123456789 345678901 3456789012; do
		gen_csi0 $i $op
	done
}


ESC=$'\x1b'
CSI="${ESC}["
for ((n=0; n < 0; n=n+1 )); do
	echo -n "${ESC}Z" > /dev/console
	echo -n "${CSI}c" > /dev/console
	echo -n "${CSI}5n" > /dev/console
	echo -n "${CSI}6n" > /dev/console
	echo -n "${CSI}x" > /dev/console
done

# CSI with many parameters, core
csi
# scroll down, cause core
gen_csi L
# scroll up, cause DoS (100% CPU)
gen_csi M
# delete character, just waste CPU, core <0
gen_csi P
# erase character, just waste CPU
gen_csi X
# set cursor y, no problem ??, no display
gen_csi d
# set cursor x, core
gen_csi e

# insert del characters, core
gen_csi '@'
# cursor up, no problem
gen_csi A
# cursor down, no display any more..
gen_csi B
# cursor rigth, core
gen_csi C
# cursor left, core
gen_csi D
# cursor down to first column, no display anymore...
gen_csi E
# cursor up and first column, no problem
gen_csi F
# set cursor x, no problem
gen_csi G
# cursor position, no problem
gen_csi H

echo -e "\e[f\e[4284967296Ca" > /dev/console

""")

        time.sleep(60)
        
        # Check vncterm is still running
        if self.host.execdom0("ps -p %d" % (pid), retval="code") != 0:
            raise xenrt.XRTFailure("CA-83267 vncterm process vanished after sending bad escape sequence")
            
class TC17803(xenrt.TestCase):
    """Regression test for CA-86932 (QEMU vt100 on parallel port)"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericWindowsGuest()
        self.uninstallOnCleanup(self.guest)

    def run(self, arglist):
        # Find the qemu PID
        domid = self.guest.getDomid()
        qpid = self.host.xenstoreRead("/local/domain/%u/qemu-pid" % (domid))

        # Verify its running before we start the test
        if self.host.execdom0("test -d /proc/%s" % (qpid), retval="code") != 0:
            raise xenrt.XRTError("QEMU not running before starting test")

        # Run the python script on the guest
        crashScript = """import sys
def get_value(x):
    if x >= 0:
        return str(x)
    else:
        return str(4294967296+x)
def do_esc(f, s):
    f.write("\033[")
    f.write(s)
f = open('LPT1', 'wb')
# Set cursor to (1,1)
do_esc(f, 'f')
# Move cursor -100000000 to the right (which actually means left)
do_esc(f, get_value(-10000000)+'C')
# Write a character to cause memory overwrite (should actually SIGSEGV)
f.write('a')
"""
        self.guest.xmlrpcWriteFile("c:\\crash_qemu.py", crashScript)
        try:
            self.guest.xmlrpcExec("python c:\\crash_qemu.py", ignoreHealthCheck=True)
        except:
            # This may fail if the parallel port is not behaving
            pass

        # Check qemu has not crashed
        if self.host.execdom0("test -d /proc/%s" % (qpid), retval="code") != 0:
            raise xenrt.XRTFailure("CA-86932 qemu process vanished after sending bad escape sequence to parallel port")

class Tahi(xenrt.TestCase):

    TAHI_INTERNAL_NETWORK = 'PrivNet'
    TAHI_NUT_CONFIG_FILE = '/usr/local/v6eval/etc/nut.def'
    TAHI_TN_CONFIG_FILE = '/usr/local/v6eval/etc/tn.def'

    def importTahiXva(self, host):
        dfMount = '/tmp/tahiXVA'
        distFiles = xenrt.TEC().lookup('EXPORT_DISTFILES_NFS', None)
        if not distFiles:
            raise xenrt.XRTError("EXPORT_DISTFILES_NFS not defined")

        host.execdom0("mkdir -p %s" % (dfMount))
        host.execdom0("mount %s %s" % (distFiles, dfMount))

        tahiDir = os.path.join(dfMount, 'tahi')
        xvas = self.host.execdom0("ls %s" % (os.path.join(tahiDir, '*.xva'))).split()
        xenrt.TEC().logverbose("Found xvas: %s in %s" % (",".join(xvas), tahiDir))

        # TODO - Handle >1 XVA
        tahiXVA = xvas[0]
        xenrt.TEC().logverbose("Importing file %s..." % (os.path.basename(tahiXVA)))
        uuid = self.host.execdom0("xe vm-import filename=%s" % (tahiXVA), timeout=1200).strip()
        xvaName = os.path.basename(tahiXVA).rstrip('.xva')
        g = host.guestFactory()(name=xvaName, host=host)
        g.uuid = uuid
        g.existing(host)
        g.name = g.paramGet('name-label')
        g.enlightenedDrivers = True

        host.execdom0("umount %s" % (dfMount))
        return g

    def configureNut(self, nodeUnderTest, tahiNetworkUUID):
        # Shutdown the VM
        if nodeUnderTest.getState() == 'UP':
            nodeUnderTest.shutdown()

        cli = self.nodeUnderTest.host.getCLIInstance()
        # TODO - fix hard-coded device#
        cli.execute("vif-create", "vm-uuid=%s network-uuid=%s device=1 mac=%s" % 
                        (nodeUnderTest.uuid, tahiNetworkUUID, xenrt.randomMAC()))

        nodeUnderTest.start()
        nodeUnderTest.reboot()

        if nodeUnderTest.windows:
            nodeUnderTest.xmlrpcExec("netsh interface ipv6 set global randomizeidentifiers=disabled")
            nodeUnderTest.xmlrpcExec("netsh firewall set opmode disable")
#            nodeUnderTest.xmlrpcExec("netsh interface ipv4 uninstall")

        nodeUnderTest.reboot()

    def configureTahiAutomation(self, tahiVM, nodeUnderTest):
        if nodeUnderTest.windows:
            tahiScriptDir = os.path.join(xenrt.TEC().lookup("LOCAL_SCRIPTDIR"), 'tahi')
            sftp = tahiVM.sftpClient()
            sftp.copyTo(os.path.join(tahiScriptDir, 'xmlrpc.py'), '/usr/local/v6eval/bin/xmlrpc.py')

            fn = xenrt.TEC().tempFile()
            fh = open(fn, 'w')
            fh.write('#!/usr/bin/perl\n')
            fh.write('use V6evalRemote;\n')
            fh.write("local $SIG{CHLD} = 'IGNORE';\n")
            fh.write('system("python /usr/local/v6eval/bin/xmlrpc.py --op=reboot-wait --host=%s");\n' % (nodeUnderTest.getIP()))
            fh.write('exit($V6evalRemote::exitPass);\n')
            fh.close()
            sftp.copyTo(fn, '/usr/local/v6eval/bin/manual/reboot.rmt')

            fn = xenrt.TEC().tempFile()
            fh = open(fn, 'w')
            fh.write('#!/usr/bin/perl\n')
            fh.write('use V6evalRemote;\n')
            fh.write("local $SIG{CHLD} = 'IGNORE';\n")
            fh.write('system("python /usr/local/v6eval/bin/xmlrpc.py --op=reboot --host=%s");\n' % (nodeUnderTest.getIP()))
            fh.write('exit($V6evalRemote::exitPass);\n')
            fh.close()
            sftp.copyTo(fn, '/usr/local/v6eval/bin/manual/reboot_async.rmt')
            sftp.close()

        else:
            raise xenrt.XRTError('XENRT TAHI does not support Linux NUT')

    def configureTahiVM(self, tahiVM, nodeUnderTest):
        if tahiVM.getState() != 'UP':
            tahiVM.start()

        vifs = nodeUnderTest.getVIFs(network=self.TAHI_INTERNAL_NETWORK)
        if len(vifs.keys()) != 1:
            raise xenrt.XRTError('NUT has %d VIF(s) on the TAHI network. Expected 1' % (len(vifs.keys())))
        interface = vifs.keys()[0]
        mac, ip, bridge = vifs[interface]
        xenrt.TEC().logverbose('NUT has interface %s with MAC %s on TAHI network' % (interface, mac))

        sftp = tahiVM.sftpClient()
        fn = xenrt.TEC().tempFile()
        sftp.copyFrom(self.TAHI_NUT_CONFIG_FILE, fn)
        fh = open(fn, 'r')
        data = fh.read()
        fh.close()
        # TODO - remove hardcoding
        data = re.sub('\nLink0.*\n', '\nLink0 %s %s\n' % ('re1', mac), data)
        fh = open(fn, 'w')
        fh.write(data)
        fh.close()
        sftp.copyTo(fn, self.TAHI_NUT_CONFIG_FILE)
        xenrt.TEC().copyToLogDir(fn, target='nut.def')

        fn = xenrt.TEC().tempFile()
        sftp.copyFrom(self.TAHI_TN_CONFIG_FILE, fn)
        fh = open(fn, 'r')
        data = fh.read()
        fh.close()
        # TODO - remove hard-coded value
        data = re.sub('\nLink0.*\n', '\nLink0 %s 00:00:00:00:01:00\n' % ('re1'), data)
        fh = open(fn, 'w')
        fh.write(data)
        fh.close()
        sftp.copyTo(fn, self.TAHI_TN_CONFIG_FILE)
        xenrt.TEC().copyToLogDir(fn, target='tn.def')

        sftp.close()

    def getResultsFromHtml(self, htmlFile):
        # TODO - This could be improved
        fh = open(htmlFile)
        lines = fh.readlines()
        fh.close()

        resultDict = {}

        match = filter(lambda x:re.search('<TITLE>(.*)</TITLE>', x), lines)
        if len(match) != 1:
            raise xenrt.XRTError('Failed to parse TITLE from TAHI result file: %s' % (htmlFile))
        resultDict['title'] = re.search('<TITLE>(.*)</TITLE>', match[0]).group(1)

        match = filter(lambda x:re.search('>TOTAL<.*>(\d+)<', x), lines)
        if len(match) != 1:
            raise xenrt.XRTError('Failed to parse TOTAL from TAHI result file: %s' % (htmlFile))
        resultDict['total'] = int(re.search('>TOTAL<.*>(\d+)<', match[0]).group(1))

        match = filter(lambda x:re.search('>PASS<.*>(\d+)<', x), lines)
        if len(match) != 1:
            raise xenrt.XRTError('Failed to parse PASS from TAHI result file: %s' % (htmlFile))
        resultDict['pass'] = int(re.search('>PASS<.*>(\d+)<', match[0]).group(1))

        match = filter(lambda x:re.search('>FAIL<.*>(\d+)<', x), lines)
        if len(match) != 1:
            raise xenrt.XRTError('Failed to parse FAIL from TAHI result file: %s' % (htmlFile))
        resultDict['fail'] = int(re.search('>FAIL<.*>(\d+)<', match[0]).group(1))

        match = filter(lambda x:re.search('>WARN<.*>(\d+)<', x), lines)
        if len(match) != 1:
            raise xenrt.XRTError('Failed to parse WARN from TAHI result file: %s' % (htmlFile))
        resultDict['warn'] = int(re.search('>WARN<.*>(\d+)<', match[0]).group(1))

        match = filter(lambda x:re.search('>SKIP<.*>(\d+)<', x), lines)
        if len(match) != 1:
            raise xenrt.XRTError('Failed to parse SKIP from TAHI result file: %s' % (htmlFile))
        resultDict['skip'] = int(re.search('>SKIP<.*>(\d+)<', match[0]).group(1))

        match = filter(lambda x:re.search('>N/A<.*>(\d+)<', x), lines)
        if len(match) != 1:
            raise xenrt.XRTError('Failed to parse N/A from TAHI result file: %s' % (htmlFile))
        resultDict['na'] = int(re.search('>N/A<.*>(\d+)<', match[0]).group(1))

        return resultDict

    """def parseResults(self, tahiResultFile, logsubdir):
        tf = tarfile.TarFile(tahiResultFile)
        summaryFiles = filter(lambda x:os.path.basename(x) == 'summary.html', tf.getnames())
        xenrt.TEC().logverbose('TAHI summary files found: %s' % (summaryFiles))

        # Extract summary files
        map(lambda x:tf.extract(x, path=logsubdir), summaryFiles)

        failedTests = False
        for htmlFile in map(lambda x:os.path.join(logsubdir, x), summaryFiles):
            result = self.getResultsFromHtml(htmlFile)
            xenrt.TEC().logverbose('TAHI Result: %s' % (result))
            if result['fail'] != 0:
                xenrt.TEC().logverbose('TAHI: %s FAILED' % (result['title']))
                failedTests = True

        if failedTests:
            raise xenrt.XRTFailure('TAHI Failed - see logs for details')"""
            
    def parseResults(self, tahiResultFile, logsubdir):
        tf = tarfile.TarFile(tahiResultFile)  # opening the tar file that was created before "tahi_results.tar"
        reportFiles = filter(lambda x:os.path.basename(x) == 'report.html', tf.getnames())  # filtering out report.html which holds information for every tests' index, PASS or FAIL, Test Name etc. 
        xenrt.TEC().logverbose('TAHI report files found: %s' % (reportFiles))

        # Extract report files
        map(lambda x:tf.extract(x, path=logsubdir), reportFiles)  # extracting the report.html files in particular
        
        reportFiles = filter(lambda x:os.path.basename(x) == 'report.html', tf.getnames())  # report.html contains each testcase wise result: PASS or FAIL. 
        titleDict = {}  # Will hold tests' sectional results in dict format as per each sections' title {'Sectional Title' :['Test Case title','FAIL or PASS']}
        failDict = {}  # Will hold failed tests' sectional results in dict for each 'key' as a 'Sectional Title' hold 'value' as a List of Index of the failures]}
        for htmlFile in reportFiles:
            tempList = []
            resultDict = {}
            page = lxml.html.parse(os.path.join(logsubdir, htmlFile))
            trList = page.xpath("//tr") 
            for tr in trList:
                if (re.search('FAIL', tr.text_content()) or re.search('PASS', tr.text_content())) and tr.getchildren()[0].text != None:
                    tempList = [node.text for node in tr.iter() if len(node) == 0][:3]
                    resultDict[tempList[0]] = tempList[1:3]
            titleDict[page.xpath('//title')[0].text] = resultDict
            tempList = []
            for key in resultDict.keys():
                if resultDict[key][1] == 'FAIL':
                    tempList.append(key)
                failDict[page.xpath('//title')[0].text] = tempList
                
        # Permitted list of failures: expFailDict will hold an expected list of failures
        expFailDict = {'Section 3: RFC 4862 - IPv6 Stateless Address Autoconfiguration': ['23', '40', '3', '5', '12', '19', '30'], 'Section 4: RFC 1981 - Path MTU Discovery for IPv6': ['11', '13', '15', '14', '16', '5', '7', '8'], 'Section 1: RFC 2460 - IPv6 Specification': ['38'], 'Section 5: RFC 4443 - ICMPv6': ['2', '5', '14'], 'Section 2: RFC 4861 - Neighbor Discovery for IPv6': ['218', '219', '133', '138', '8', '128', '225', '13', '15', '204']}
        
        
        if failDict != expFailDict:
            # To find actual Failures (remove expected failures from failDict list)
            actualFailDict = {}
            for key in failDict.keys():
                actualFailDict[key] = set(failDict[key]) - set(expFailDict[key])
            
            # Print actual Fail list names
            for key in titleDict:
                actualFailDict[key] = [(index, titleDict[key][index][0]) for index in actualFailDict[key]]
                xenrt.TEC().logverbose("The failure list for section under %s are %s" % (key, actualFailDict[key]))
            raise xenrt.XRTFailure('TAHI Failed - see logs for details - %s' % actualFailDict)
        else: xenrt.TEC().logverbose("********TAHI PASSED*****")

    def prepare(self, arglist):
        self.host = self.getDefaultHost()

        # Create internal network
        self.tahiNetworkUUID = self.host.createNetwork(name=self.TAHI_INTERNAL_NETWORK)

        existingGuests = self.host.listGuests()
        if 'tahi' in existingGuests:
            existingGuests.remove('tahi')
            self.tahi = self.host.getGuest('tahi')
        else:
            self.tahi = self.importTahiXva(self.host)

        if existingGuests:
            # Handle >1 NUT
            self.nodeUnderTest = self.host.getGuest(existingGuests[0])

        # Configure the Node Under Test
        self.configureNut(self.nodeUnderTest, self.tahiNetworkUUID)

        self.configureTahiVM(self.tahi, self.nodeUnderTest)
        self.configureTahiAutomation(self.tahi, self.nodeUnderTest)


    def run(self, arglist=None):
        res = self.tahi.execguest('cd ~/tahi/Self_Test_5-0-0 && make clean')
        try:
            res = self.tahi.execguest('cd ~/tahi/Self_Test_5-0-0 && make ipv6ready_p2_host', timeout=(5 * 60 * 60))
        except xenrt.XRTException, e:
            xenrt.TEC().logverbose('TAHI Execution FAILED: message: %s' % (str(e.message)))
            xenrt.TEC().logverbose('TAHI Execution FAILED: data: %s' % (str(e.data)))
            raise e

        xenrt.TEC().logverbose('TAHI Execution Complete: %s' % (res))

        # Save the results
        logsubdir = "%s/tahi_logs" % (xenrt.TEC().getLogdir())
        if not os.path.exists(logsubdir):
            os.makedirs(logsubdir)

        sftp = self.tahi.sftpClient()
        res = self.tahi.execguest('cd ~/tahi/Self_Test_5-0-0 && find . | grep .\html$ | xargs tar -cvf /root/tahi_result.tar')
        sftp.copyFrom('/root/tahi_result.tar', os.path.join(logsubdir, 'tahi_result.tar'))
        sftp.close()

        # Parse result
        self.parseResults(os.path.join(logsubdir, 'tahi_result.tar'), logsubdir)
        
class TCDisableHostnameAD(xenrt.TestCase):
    """Verify hostname from the AD server when config:disable_modules="hostname" is used."""

    ADSERVER = "AUTHSERVER"

    def run(self, arglist):
        host = self.getDefaultHost()
        # Standalone host, create a dummy pool object
        version = host.productVersion
        pool = xenrt.lib.xenserver.host.poolFactory(version)(host)  
        authserver = self.getGuest(self.ADSERVER).getActiveDirectoryServer()
        
        hostname = pool.master.getMyHostName()
        dnsHostname = hostname + ".testdev.hq.xensource.com"
        # add hostname with DNS domain in /etc/hosts
        host.execdom0("echo '127.0.0.1 %s %s localhost localhost.localdomain' > /etc/hosts" % (dnsHostname, hostname))
        
        # enable AD authentication
        pool.enableAuthentication(authserver, disable_modules="hostname")
        if not string.upper(hostname) in authserver.getAllComputers():    
            raise xenrt.XRTFailure("Host not present on AD server after "
                                   "enabling authentication.")        
        
        # check if dnsHostName is saved with domain name in AD server
        r = authserver.place.xmlrpcExec("dsquery * -filter samaccountname=%s$ -attr dnshostname" % (hostname), returndata=True)
        if string.lower(dnsHostname) not in r:
            raise xenrt.XRTFailure("Hostname present on AD server not as expected")
        xenrt.TEC().logverbose("Hostname present on AD server as expected: %s" % r)

class TC1660(xenrt.TestCase):
    """Verify there are no clear-text passwords in xen-bugtool output"""

    def run(self, arglist):
        host = self.getDefaultHost()

        # Create a secret that we can look for
        secretText = "tc1660test"
        secret = host.createSecret(secretText)
        
        # Ensure the xapi database is synced to disk
        host.getCLIInstance().execute("pool-sync-database")

        # Capture and extract a bugtool
        bt = host.getBugTool()

        workdir = xenrt.resources.TempDirectory().path()
        t = tarfile.open(bt, "r")
        t.extractall(workdir)

        # Look for our secretText, and (if not too common a string) our root password
        strings = [secretText]
        if host.password not in ["xensource", "admin", "administrator", "password"]:
            strings.append(host.password)
        grepstr = string.join([re.escape(s) for s in strings], "|")
        lines = xenrt.command("find %s -exec zgrep -H -E \"%s\" {} \\;" % (workdir, grepstr))
        if len(lines.strip()) > 0:
            raise xenrt.XRTFailure("Found plaintext password in bugtool output")

class NetworkConfigurator(object):
    PRIVATE_NETWORK = "eth1"

    def configureWindowsPrivateNet(self,attacker):
        attacker.configureNetwork(self.PRIVATE_NETWORK, "192.168.1.1", "255.255.255.0")
        i = 2
        for v in attacker.identifyWinVictims():
            v.configureNetwork(self.PRIVATE_NETWORK, "192.168.1." + str(i), "255.255.255.0")
            i = i + 1


class VMSecurityFacade(object):

    def __init__(self, guest):
       self._VM = guest

    def healthStatus(self):
        self._VM.checkHealth()

    def ipv6NetworkAddress(self, deviceNo = 0, ipNo = 0):
        return self._VM.xapiObject.ipv6NetworkAddress(deviceNo, ipNo)

    def configureNetwork(self, device,ip=None, netmask=None, gateway=None, metric=None):
        self._VM.configureNetwork(device, ip, netmask, gateway, metric)

    def getVMCPUUsage(self):
        return float(self._VM.xapiObject.cpuUsage['0'])*100

    def getHostCPUUsage(self):
        return self._VM.host.dom0CPUUsageOverTime(60)

    def shutdown(self):
        self._VM.shutdown()

    def forceReboot(self):
        self._VM.reboot(force=True)

    def getName(self):
        return self._VM.name


class Victim(VMSecurityFacade):
    __MAXED_OUT_THRESHOLD = 50.0

    def __init__(self,guest):
        super(Victim,self).__init__(guest)

    def victimIsMaxedOut(self,raiseExceptionOnFailure = False):
        return self.__isMaxedOut(self.getVMCPUUsage(),self.getName(),raiseExceptionOnFailure)

    def hostIsMaxedOut(self, raiseExceptionOnFailure = False):
        return self.__isMaxedOut(self.getHostCPUUsage(),"Host",raiseExceptionOnFailure)

    def __isMaxedOut(self, usage, name, raiseExceptionOnFailure = False):
        if usage > self.__MAXED_OUT_THRESHOLD:
            if raiseExceptionOnFailure:
                raise xenrt.XRTFailure("%s CPU is maxed out at %.2f%%" % (name, usage))
            else:
                return True
        else:
                log("%s CPU is %.2f%%, which is under threshold" % (name, usage))

    def healthStatusOverTime(self):
        verifyEnd = time.time() + (60 * 5) # 5 mins
        while time.time() < verifyEnd:
            try:
                self.healthStatus()
            except:
                log("Couldn't check victims health, ignore and allow to recover")
            log("zzzzz.....")
            time.sleep(10)


class Attacker(VMSecurityFacade):

    def __init__(self,guest):
        super(Attacker,self).__init__(guest)

    def installScapy(self):
        self.scapy = xenrt.networkutils.Scapy(self._VM)
        self.scapy.install()

    def installHCFloodRouterUbuntu(self, privateNetwork):
        hCFloodRouterPackage = xenrt.networkutils.HackersChoiceFloodRouter26Ubuntu(privateNetwork)
        hCFloodRouterPackage.install(self._VM)
        return hCFloodRouterPackage

    def installHCFirewall6Ubuntu(self, privateNetwork):
        hCFirewall6Package = xenrt.networkutils.HackersChoiceFirewall6Ubuntu(privateNetwork,self._VM)
        hCFirewall6Package.install(self._VM)
        return hCFirewall6Package

    def runHCUbuntuPackage(self,package):
        package.run(self._VM)

    def identifyWinVictims(self):
        return [Victim(xenrt.TEC().registry.guestGet(x)) for x in self._VM.host.listGuests() if xenrt.TEC().registry.guestGet(x).windows]

    def hCMaxOutVictim(self, victim,package,count=0):
        gameOver = time.time() + (60 * 30) # Timeout 30 mins
        log("Game over at: %s" % str(gameOver))
        
        log("Package started to run at %s " + str(time.time()))
        self.runHCUbuntuPackage(package)
        while not victim.victimIsMaxedOut:
            if not time.time() < gameOver:
                log("Timed out while trying to max out the guest")
                victim.HostIsMaxedOut(True)
                if count <= 5:
                    log("Retrying attack %s of 5" % str(count+1))
                    self.hCMaxOutVictim(victim,package,count+1)
                else:
                    raise xenrt.XRTFailure("All attempted attacks failed to max out the guest")
            if count > 0:
                return
            log("zzzzzz.....")
            time.sleep(10)
        log("Give it a couple of secs to be sure.....")
        time.sleep(10 * 3)
        log("%s CPU usage is maxed out: %s" % (victim.getName(), str(victim.victimIsMaxedOut())))

    def sendScapyPacket(self, net, packet):
        self.scapy.sendPacket(net, packet)

class TCHackersChoiceIPv6FloodRouter(xenrt.TestCase):

    def run(self, arglist):
        attacker = Attacker(self.getDefaultHost().getGuest("attacker"))
        #-------------------------
        step("Configure Private Network")
        #-------------------------
        net = NetworkConfigurator()
        net.configureWindowsPrivateNet(attacker)
        #-------------------------
        step("Install package")
        #-------------------------
        package = attacker.installHCFloodRouterUbuntu(net.PRIVATE_NETWORK)
        victims = attacker.identifyWinVictims()
        targetVM = next(v for v in victims if v.getName() == "victim1")
         #----------------------------------------------------------
        step("Run the package and check for the guest maxing out") 
        #----------------------------------------------------------
        attacker.hCMaxOutVictim(targetVM, package)
        #-------------------------------
        step("Shutdown the attacker")
        #-------------------------------
        attacker.shutdown()
        #------------------------------------
        step("Wait for victim to recover")
        #------------------------------------
        targetVM.healthStatusOverTime()
        #--------------------------
        step("Check all victims CPU usage")
        #--------------------------
        for victim in victims:
            if victim.victimIsMaxedOut():
                log("Waited %d secs for CPU to recover from attack and usage is %.2f"
                                       % (60 * 5, victim.getVMCPUUsage()))
                log("%s failed to recover from attack" % victim.getName())
            else:
                log("%s appears to have recovered from the attack usage =%.2f"
                    % (victim.getName(),victim.getVMCPUUsage()))
        #--------------------------
        step("Check host CPU usage")
        #--------------------------
        targetVM.hostIsMaxedOut(True)
        #--------------------------
        step("Check Health of all victim vms")
        #--------------------------
        deadVictims = 0
        for victim in victims:
            try:
                victim.healthStatus()
            except:
                log("problem checking %s healthStatus" % victim.getName())
                deadVictims += 1

        if deadVictims > 1:
            raise xenrt.XRTFailure("%d victims failed to recover from attack" % deadVictims)


class TCBadPackets(xenrt.TestCase):

    def run(self, arglist):
        attacker = Attacker(self.getDefaultHost().getGuest("attacker"))
        #-------------------------
        step("Configure Private Network")
        #-------------------------
        net = NetworkConfigurator()
        net.configureWindowsPrivateNet(attacker)
        # this is a base64 encoded pcap of a single broadcast packet with multiple VLAN tags (SCTX-1529)
        badPackets = ["1MOyoQIABAAAAAAAAAAAAACQAQABAAAAAAAAAAAAAAAgAAAAIAAAAP///////wAB/uHerYEAAEqBAABKgQDerd6t3q3erd6t"]
        attacker.installScapy()
        for p in badPackets:
            attacker.sendScapyPacket(net.PRIVATE_NETWORK, p)
        xenrt.sleep(30)
        victims = attacker.identifyWinVictims()
        if victims:
            for victim in victims:
                victim.healthStatus()


class TCHackersChoiceIPv6Firewall6(xenrt.TestCase):
    __package = None

    def _runPackageTestCase(self, victim, hackNumber):
        #----------------------------------------
        step("Run attack %d...." % hackNumber)
        #----------------------------------------
        self.__package.runtestcase(hackNumber)
        time.sleep(10)
        log("Results of attack: %s" % str(self.__package.results()))
        try:
            #----------------------------------------
            step("Check the victims health")
            #----------------------------------------
            victim.healthStatus()
        except xenrt.XRTFailure as e:
            #---------------------------------------------------------------------------------------
            step("Error caught, attempt to force-reboot host for next subcase and fail this one")
            #---------------------------------------------------------------------------------------
            victim.forceReboot()
            raise xenrt.XRTFailure(e)

    def __runAllPackageTests(self, attacker, victim, ipv6Address):
        self.__package.setIPv6Address(ipv6Address)
        #------------------------------------------------------------
        step("Running attacks from %s on vm %s" % (attacker.getName(), victim.getName()))
        #------------------------------------------------------------
        for tc in self.__package.testCasesIds():
            self.runSubcase("_runPackageTestCase", (victim, tc), "HackersChoice Firewall6 on %s" % victim.getName(), "test %d" % tc)

    def run(self,arglist):

        attacker = Attacker(self.getDefaultHost().getGuest("attacker"))
        #-------------------------
        step("Configure Private Network")
        #-------------------------
        net = NetworkConfigurator()
        net.configureWindowsPrivateNet(attacker)

        #-------------------------
        step("Install package")
        #-------------------------
        self.__package = attacker.installHCFirewall6Ubuntu(net.PRIVATE_NETWORK)
        victims = attacker.identifyWinVictims()
        for victim in victims:
            ipv6Address = victim.ipv6NetworkAddress(1)
            if ipv6Address:
                self.__runAllPackageTests(attacker,victim,ipv6Address)
            else:
                log("skipping %s tests...." % victim.getName())
                continue


class TCIPv6FloodRouterStress(xenrt.TestCase):
    __STRESS_DURATION = 60 * 60 * 24
    __STRESS_SLEEP = 60 * 5

    def __wait(self, victims):
        step("Start the waiting period")
        gameOver = time.time() + self.__STRESS_DURATION
        log("Game over in %s" % str(gameOver))
        log("Start the wait...")
        while time.time() < gameOver:
            for victim in victims:
                log("%s CPU usage is %.2f" % (victim.getName(), victim.getVMCPUUsage()))
            log("zzzzz.....")
            time.sleep(self.__STRESS_SLEEP)
        log("Wait over")

    def run(self,arglist):
        attacker = Attacker(self.getDefaultHost().getGuest("attacker"))
        #-------------------------
        step("Configure Private Network")
        #-------------------------
        net = NetworkConfigurator()
        net.configureWindowsPrivateNet(attacker)
        #-------------------------
        step("Install package")
        #-------------------------
        package = attacker.installHCFloodRouterUbuntu(net.PRIVATE_NETWORK)
        victims = attacker.identifyWinVictims()
        if not victims:
            raise xenrt.XRTFailure("Couldn't find a windows host")
        #----------------------------------------------------------
        step("Run the package and check for the guest maxing out")
        #----------------------------------------------------------
        attacker.hCMaxOutVictim(victims[0],package)
        self.__wait(victims)
        victims[0].hostIsMaxedOut(True)
