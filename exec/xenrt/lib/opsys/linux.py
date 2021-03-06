import xenrt
import string
import socket
import re
from xenrt.lib.opsys import OS,OSNotDetected


class LinuxOS(OS):
    vifStem = "eth"

    tcpCommunicationPorts={"SSH": 22}

    def __init__(self, distro, parent, password=None):
        super(LinuxOS, self).__init__(distro, parent, password)

    @staticmethod
    def testInit(cls, parent): raise NotImplementedError()

    @property
    def canonicalDistroName(self): raise NotImplementedError()

    @property
    def waitForBoot(self): raise NotImplementedError()

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
                self.findPassword()
            password = self.password

        return xenrt.ssh.SSH(self.getIP(trafficType="SSH"),
                             command,
                             port=self.getPort(trafficType="SSH"),
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

    def getArch(self):
        arch = self.execSSH("uname -m").strip()
        if arch == "x86_64":
            return "x86-64"
        else:
            return "x86-32"

    def getLogs(self, path):
        sftp = self.sftpClient()
        sftp.copyLogsFrom(["/var/log/messages",
                           "/var/log/syslog",
                           "/var/log/daemon.log",
                           "/var/log/kern.log"], path)


    def sftpClient(self):
        """Get a SFTP client object to the guest"""
        return xenrt.ssh.SFTPSession(self.getIP(trafficType="SSH"),
                                     username="root",
                                     password=self.password,
                                     level=xenrt.RC_FAIL,
                                     port=self.getPort(trafficType="SSH"))

    def populateFromExisting(self):
        if self.parent._osParent_getPowerState() != xenrt.PowerState.up:
            self.password = xenrt.TEC().lookup("ROOT_PASSWORD")
        else:
            self.findPassword()

    def findPassword(self, ipList=[]):
        """Try some passwords to determine which to use"""
        if not self.password or len(ipList) > 0:
            # Use a 30s timeout if we know the IP. If we don't try 10s first
            if len(ipList) == 0:
                timeouts = [30]
                ipList = [(self.getIP(trafficType="SSH"), self.getPort(trafficType="SSH"))]
            else:
                timeouts = [10, 30]
                ipList = [(x,22) for x in ipList]
            passwords = string.split(xenrt.TEC().lookup("ROOT_PASSWORDS", ""))
            for t in timeouts:
                for p in passwords:
                    for i in ipList:
                        xenrt.TEC().logverbose("Trying %s on %s" % (p, i))
                        try:
                            xenrt.ssh.SSH(i[0], "true", username="root",
                                          password=p, level=xenrt.RC_FAIL,
                                          timeout=10, port=i[1])
                            xenrt.TEC().logverbose("Setting my password to %s"
                                                    % (p))
                            self.password = p
                            if i[0] != self.getIP(trafficType="SSH"):
                                xenrt.TEC().logverbose("Setting my IP to %s"
                                                        % (i))
                                self.parent._osParent_setIP(i)
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
            if xenrt.ssh.SSH(self.getIP(trafficType="SSH"),
                             cmd,
                             port=self.getPort(trafficType="SSH"),
                             password=self.password,
                             level=xenrt.RC_OK,
                             timeout=20,
                             username=username,
                             nowarn=True) == xenrt.RC_OK:
                xenrt.TEC().logverbose(" ... OK reply from %s:%s" %
                                       (self.getIP(trafficType="SSH"), self.getPort(trafficType="SSH")))
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

    @property
    def visibleMemory(self):
        """Memory visible on the guest in MB, including any used by a crash kernel"""
        assert self.parent._osParent_getPowerState() == xenrt.PowerState.up, "OS not running"
        data = self.execSSH("cat /proc/meminfo")
        rc = re.search(r"MemTotal:\s+(\d+)\s+kB", data)
        return (int(rc.group(1)) - self._getKdumpSize()) / xenrt.KILO

    def assertHealthy(self, quick=False):
        if self.parent._osParent_getPowerState() == xenrt.PowerState.up:
            # Wait for basic SSH access
            self.waitForSSH(timeout=180)
            if quick:
                return
            stampFile = "/tmp/healthy"
            self.execSSH("dd if=/dev/urandom oflag=direct of=%s count=1024"
                          % stampFile)
            self.execSSH("dd if=%s iflag=direct of=/dev/null" % stampFile)
    
    @classmethod
    def detect(cls, parent, detectionState):
        obj = cls("testlin", parent, detectionState.password)
        try:
            sock = socket.socket()
            sock.settimeout(10)
            sock.connect((obj.getIP(), obj.getPort("SSH")))
            sock.close()
            obj.execSSH("true")
        except Exception, e:
            raise OSNotDetected("OS appears not to have SSH: %s" % str(e))
        else:
            detectionState.password = obj.password

    def _getKdumpSize(self):
        """Returns the size (in kB) of any crashdump kernel present on the OS"""
        size = int(self.execSSH("[ -e /sys/kernel/kexec_crash_size ] && cat /sys/kernel/kexec_crash_size || echo 0").strip())
        return size / xenrt.KILO

