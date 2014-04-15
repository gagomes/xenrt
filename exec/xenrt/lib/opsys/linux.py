import xenrt, string
from xenrt.lib.opsys import OS

class LinuxOS(OS):
    vifStem = "eth"

    def execSSH(self,
                command,
                username=None,
                retval="string",
                level=xenrt.RC_FAIL,
                timeout=300,
                idempotent=False,
                newlineok=False,
                nolog=False,
                outfile=None,
                useThread=False,
                getreply=True,
                password=None):
        """Execute a command on the instance.
    
        @param retval:  Whether to return the result code or stdout as a string
            "C{string}" (default), "C{code}"
            if "C{string}" is used then a failure results in an exception
        @param level:   Exception level to use if appropriate.
        @param nolog:   If C{True} then don't log the output of the command
        @param useThread: If C{True} then run the SSH command in a thread to
                        guard against hung SSH sessions
        """

        if not username:
            username = "root"
        if not password:
            if not self.password:
                self.password = self.findPassword()
            password = self.password

        return xenrt.ssh.SSH(self.parent.getIP(),
                             command,
                             level=level,
                             retval=retval,
                             password=password,
                             timeout=timeout,
                             username=username,
                             idempotent=idempotent,
                             newlineok=newlineok,
                             nolog=nolog,
                             outfile=outfile,
                             getreply=getreply,
                             useThread=useThread)

    def populateFromExisting(self):
        self.findPassword()

    def findPassword(self, ipList = []):
        """Try some passwords to determine which to use"""
        if not self.password or len(ipList) > 0:
            # Use a 30s timeout if we know the IP. If we don't try 10s first
            if len(ipList) == 0:
                timeouts = [30]
                ipList = [self.parent.getIP()]
            else:
                timeouts = [10, 30]
            passwords = string.split(xenrt.TEC().lookup("ROOT_PASSWORDS", ""))
            for t in timeouts:
                for p in passwords:
                    for i in ipList:
                        xenrt.TEC().logverbose("Trying %s on %s" % (p, i))
                        try:
                            xenrt.ssh.SSH(i, "true", username="root",
                                          password=p, level=xenrt.RC_FAIL, timeout=10)
                            xenrt.TEC().logverbose("Setting my password to %s" % (p))
                            self.password = p
                            if i != self.parent.getIP():
                                xenrt.TEC().logverbose("Setting my IP to %s" % (i))
                                self.parent.setIP(i)
                            return
                        except:
                            pass

    def waitForSSH(self, timeout, level=xenrt.RC_FAIL, desc="Operation",
                   username="root", cmd="true"):
        now = xenrt.util.timenow()
        deadline = now + timeout
        while 1:
            if not self.password:
                self.findPassword()
            if xenrt.ssh.SSH(self.parent.getIP(),
                             cmd,
                             password=self.password,
                             level=xenrt.RC_OK,
                             timeout=20,
                             username=username,
                             nowarn=True) == xenrt.RC_OK:
                xenrt.TEC().logverbose(" ... OK reply from %s" %
                                       (self.parent.getIP()))
                return xenrt.RC_OK
            now = xenrt.util.timenow()
            if now > deadline:
                # if level == xenrt.RC_FAIL:
                #     self.checkHealth(unreachable=True)
                return xenrt.XRT("%s timed out" % (desc), level)
            xenrt.sleep(15, log=False)

    def shutdown(self):
        self.execSSH("poweroff")

    def reboot(self):
        self.execSSH("reboot")

    @property
    def defaultRootdisk(self):
        return 8 * xenrt.GIGA

    @property
    def defaultVcpus(self):
        return 1

    @property
    def defaultMemory(self):
        return 256


