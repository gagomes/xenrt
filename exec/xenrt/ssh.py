#
# XenRT: Test harness for Xen and the XenServer product family
#
# SSH interface
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, string, sys, os, os.path, traceback, time
import paramiko
import xenrt

# Symbols we want to export from the package.
__all__ = ["SSHSession",
           "SFTPSession",
           "SSHCommand",
           "SSH",
           "SSHread",
           "getPublicKey"]

def getPublicKey():
    filename = xenrt.TEC().lookup("SSH_PUBLIC_KEY_FILE")
    f = file(filename, "r")
    data = f.read()
    f.close()
    return string.strip(data)

class SSHSession(object):
    def __init__(self,
                 ip,
                 username="root",
                 timeout=300,
                 level=xenrt.RC_ERROR, 
                 password=None,
                 nowarn=False,
                 useThread=False,
                 port=22):
        self.level = level
        self.toreply = 0
        self.debug = False
        self.trans = None
        for tries in range(3):
            self.trans = None
            try:
                if useThread:
                    t = xenrt.util.ThreadWithException(target=self.connect,
                                                       args=(ip, port, username,
                                                             password, timeout))
                    # Make the thread daemonic (so python will exit if it ends
                    # up hung and still running)
                    t.setDaemon(True)
                    t.start()
                    t.join(timeout)
                    if t.isAlive():
                        raise xenrt.XRTFailure("Connection appears to have hung")
                    if t.exception:
                        raise t.exception
                else:
                    self.connect(ip, port, username, password, timeout)
            except Exception, e:
                traceback.print_exc(file=sys.stderr)
                desc = str(e)
                xenrt.TEC().logverbose("SSH exception %s" % (desc))
                if string.find(desc, "Signature verification") > -1 or \
                        string.find(desc,
                                    "Error reading SSH protocol banner") > -1:
                    # Have another go
                    if not nowarn:
                        xenrt.TEC().warning(\
                            "Retrying SSH connection after '%s'" % (desc))
                    try:
                        self.close()
                    except:
                        pass
                    xenrt.sleep(1)
                    continue
                elif string.find(desc, "Authentication failed") > -1:
                    self.reply = xenrt.XRT("SSH authentication failed",
                                           self.level)
                    self.toreply = 1
                    self.close()
                    break
                else:
                    # Probably a legitimate exception
                    pass
                self.reply = xenrt.XRT("SSH connection failed", self.level)
                self.toreply = 1
                self.close()
                break
            if self.debug:
                xenrt.TEC().logverbose("done")
            # If we get here we have successfully opened a connection
            return
        # Even after retry(s) we didn't get a connection
        self.reply = xenrt.XRT("SSH connection failed", self.level)
        self.toreply = 1
        self.close()

    def connect(self, ip, port, username, password, timeout):
        if self.debug:
            xenrt.TEC().logverbose("connect")
        sock = socket.create_connection((ip, port), timeout)
            
        # Create SSH transport.
        if self.debug:
            xenrt.TEC().logverbose("transport")
        self.trans = paramiko.Transport(sock)
        self.trans.set_log_channel("")
            
        # Negotiate SSH session synchronously.
        if xenrt.TEC().lookup("OPTION_RETRY_SSH2", False, boolean=True):
            goes = 3
        else:
            goes = 1
        while goes > 0:
            try:
                if self.debug:
                    xenrt.TEC().logverbose("start_client")
                self.trans.start_client()
                goes = 0
            except Exception, e:
                goes = goes - 1
                if goes > 0:
                    xenrt.TEC().warning("Retrying SSHSession connection")
                    xenrt.sleep(10)
                else:
                    raise e
            
        # Load DSS key.
        k = None
        try:
            dsskey = xenrt.TEC().lookup("SSH_PRIVATE_KEY_FILE")
            if self.debug:
                xenrt.TEC().logverbose("load key")
            k = paramiko.DSSKey.from_private_key_file(dsskey)
        except:
            pass
        
        # Authenticate session. No host key checking is performed.
        if self.debug:
            xenrt.TEC().logverbose("auth")
        if password:
            if password == "<NOPASSWORD>":
                password = ""
            xenrt.TEC().logverbose("Using SSH password %s" % (password))
            self.trans.auth_password(username, password)
        else:
            if not k:
                raise xenrt.XRTError("No password given and no key read")
            xenrt.TEC().logverbose("Using SSH public key %s" % (dsskey))
            self.trans.auth_publickey(username, k)
        if not self.trans.is_authenticated():
            raise xenrt.XRTError("Problem with SSH authentication")

    @xenrt.irregularName
    def open_session(self):
        if self.debug:
            xenrt.TEC().logverbose("open_session")
        return self.trans.open_session()

    def close(self):
        if self.trans:
            self.trans.close()
            self.trans = None

    def __del__(self):
        self.close()

class SFTPSession(SSHSession):
    """An SFTP session guarded for target lockups."""
    def __init__(self,
                 ip,
                 username="root",
                 timeout=1250,
                 level=xenrt.RC_ERROR,
                 password=None,
                 nowarn=False,
                 port=22):
        xenrt.TEC().logverbose("SFTP session to %s@%s" % (username, ip))
        self.ip = ip
        self.port = port
        self.username = username
        self.timeout = timeout
        self.level = level
        self.password = password
        self.nowarn = nowarn
        SSHSession.__init__(self,
                            ip,
                            username=username,
                            timeout=timeout,
                            level=level,
                            password=password,
                            nowarn=nowarn,
                            port=port)
        try:
            # We do this rather than the simple trans.open_sftp_client() because
            # if we don't then we don't get a timeout set so we can hang forever
            c = self.trans.open_channel("session")
            c.settimeout(timeout)
            c.invoke_subsystem("sftp")
            self.client = paramiko.SFTPClient(c)
        except:
            self.reply = xenrt.XRT("SFTP connection failed", self.level)
            self.toreply = 1
            self.close()

    def getClient(self):
        # This is UNSAFE - the client object may change if we auto reconnect!
        return self.client

    def check(self):
        # Check if the connection is still active, if not, try and re-open the
        # connection (this handles the case where the connection has dropped
        # due to a transient network error)...

        alive = True

        # First see if the transport is alive
        if not self.trans.is_active():
            alive = False
        else:
            try:
                d = self.client.listdir()
            except:
                alive = False

        if not alive:
            xenrt.TEC().logverbose("SFTP session appears to have gone away, "
                                   "attempting to reconnect...")
            self.__init__(self.ip,
                          username=self.username,
                          timeout=self.timeout,
                          level=self.level,
                          password=self.password,
                          nowarn=self.nowarn)

    def close(self):
        if self.client:
            try:
                self.client.close()
            except Exception, e:
                xenrt.TEC().logverbose("SFTP close exception %s" % (str(e)))
        if self.trans:
            try:
                self.trans.close()
            except Exception, e:
                xenrt.TEC().logverbose("SFTP trans close exception %s" %
                                       (str(e)))

    def copyTo(self, source, dest, preserve=True):
        xenrt.TEC().logverbose("SFTP local:%s to remote:%s" % (source, dest))
        self.client.put(source, dest)
        if preserve:
            st = os.lstat(source)
            if preserve == True:
                self.client.chmod(dest, st.st_mode)
            self.client.utime(dest, (st.st_atime, st.st_mtime))

    def copyFrom(self, source, dest, preserve=True, threshold=None,
                 sizethresh=None):
        xenrt.TEC().logverbose("SFTP remote:%s to local:%s" % (source, dest))
        self.check()
        st = self.client.stat(source)
        if threshold and st.st_mtime < threshold:
            xenrt.TEC().logverbose("Skipping %s, too old" % (source))
            return
        elif sizethresh and st.st_size > long(sizethresh):
            xenrt.TEC().logverbose("Skipping %s, too big (%u)" %
                                   (source, st.st_size))
            return
        self.client.get(source, dest)
        if preserve:
            if preserve == True:
                os.chmod(dest, st.st_mode)
            os.utime(dest, (st.st_atime, st.st_mtime))

    def copyTreeTo(self, source, dest, preserve=True):
        """Recursive copy to the remote host

        source: local directory being root of the tree
        dest:   remote directory to be the new root of the tree
        """
        xenrt.TEC().logverbose("SFTP recursive local:%s to remote:%s" %
                               (source, dest))
        self.check()
        source = os.path.normpath(source)
        dirs = os.walk(source)
        for dir in dirs:
            (dirname, dirnames, filenames) = dir
            # Create the remote directory
            dirname = os.path.normpath(dirname)
            relpath = dirname[len(source):]
            if len(relpath) > 0 and relpath[0] == "/":
                relpath = relpath[1:]
            targetpath = os.path.normpath(os.path.join(dest, relpath))
            try:
                self.client.lstat(targetpath)
                # Already exists
                if preserve == True:
                    self.client.chmod(targetpath, os.lstat(dirname).st_mode)
            except IOError, e:
                self.client.mkdir(targetpath, os.lstat(dirname).st_mode)
            # Copy all the files in
            for file in filenames:
                srcfile = os.path.join(dirname, file)
                dstfile = os.path.join(targetpath, file)
                st = os.lstat(srcfile)
                self.client.put(srcfile, dstfile)
                if preserve:
                    if preserve == True:
                        self.client.chmod(dstfile, st.st_mode)
                    self.client.utime(dstfile, (st.st_atime, st.st_mtime))

    def copyTreeFromRecurse(self, source, dest, preserve=True, threshold=None,
                            sizethresh=None):
        # make sure local destination exists
        if not os.path.exists(dest):
            os.makedirs(dest)
        if preserve:
            os.chmod(dest, self.client.lstat(source).st_mode)
        d = self.client.listdir(source)
        for i in d:
            try:
                dummy = self.client.listdir("%s/%s" % (source, i))
                isdir = True
            except:
                isdir = False                
            if isdir:
                self.copyTreeFromRecurse("%s/%s" % (source, i),
                                         "%s/%s" % (dest, i),
                                         preserve=preserve,
                                         threshold=threshold,
                                         sizethresh=sizethresh)
            else:
                xenrt.TEC().logverbose("About to copy %s/%s" % (source, i))
                st = self.client.stat("%s/%s" % (source, i))
                if threshold and st.st_mtime < threshold:
                    xenrt.TEC().logverbose("Skipping %s/%s, too old" %
                                           (source, i))
                elif sizethresh and st.st_size > long(sizethresh):
                    xenrt.TEC().logverbose("Skipping %s/%s, too big (%u)" %
                                           (source, i, st.st_size))
                else:
                    self.client.get("%s/%s" % (source, i),
                                    "%s/%s" % (dest, i))
                    if preserve:
                        if preserve == True:
                            os.chmod("%s/%s" % (dest, i), st.st_mode)
                        os.utime("%s/%s" % (dest, i),
                                 (st.st_atime, st.st_mtime))

    def copyTreeFrom(self, source, dest, preserve=True, threshold=None,
                     sizethresh=None):
        """Recursive copy from the remote host

        source: remote directory being root of the tree
        dest:   local directory to be the new root of the tree
        """
        xenrt.TEC().logverbose("SFTP recursive remote:%s to local:%s" %
                               (source, dest))
        self.check()
        self.copyTreeFromRecurse(source,
                                 dest,
                                 preserve=preserve,
                                 threshold=threshold,
                                 sizethresh=sizethresh)

    def copyLogsFrom(self, pathlist, dest, threshold=None, sizethresh=None):
        """Copy any files or directory trees from pathlist remotely to
        dest locally"""
        xenrt.TEC().logverbose("SFTP log fetch of %s to local:%s" %
                               (`pathlist`, dest))
        for p in pathlist:
            # Directory?
            xenrt.TEC().logverbose("Trying to fetch %s." % (p))
            try:
                d = self.client.listdir(p)
                self.copyTreeFrom(p, "%s/%s" % (dest, os.path.basename(p)),
                                  preserve="utime", threshold=threshold,
                                  sizethresh=sizethresh)
            except:
                # File?
                try:
                    s = self.client.lstat(p)
                    self.copyFrom(p, "%s/%s" % (dest, os.path.basename(p)),
                                  preserve="utime", threshold=threshold,
                                  sizethresh=sizethresh)
                except:
                    pass
    
    def __del__(self):
        SSHSession.__del__(self)                

class SSHCommand(SSHSession):
    """An SSH session guarded for target lockups."""
    def __init__(self,
                 ip,
                 command,
                 username="root",
                 timeout=1200,
                 level=xenrt.RC_ERROR,
                 password=None,
                 nowarn=False,
                 newlineok=False,
                 nolog=False,
                 useThread=False,
                 usePty=False,
                 port=22):
        SSHSession.__init__(self,
                            ip,
                            username=username,
                            timeout=timeout,
                            level=level,
                            password=password,
                            nowarn=nowarn,
                            useThread=useThread,
                            port=port)
        self.command = command
        self.nolog = nolog
        if string.find(command, "\n") > -1 and not newlineok:
            xenrt.TEC().warning("Command with newline: '%s'" % (command))
        try:
            self.client = self.open_session()
            if self.debug:
                xenrt.TEC().logverbose("settimeout")
            self.client.settimeout(timeout)
            if self.debug:
                xenrt.TEC().logverbose("set_combine_stderr")
            self.client.set_combine_stderr(True)
            if usePty:
                if self.debug:
                    xenrt.TEC().logverbose("get_pty")
                self.client.get_pty()
            if self.debug:
                xenrt.TEC().logverbose("exec_command")
            self.client.exec_command(command)
            if self.debug:
                xenrt.TEC().logverbose("shutdown(1)")
            self.client.shutdown(1)            
            if self.debug:
                xenrt.TEC().logverbose("makefile")
            self.fh = self.client.makefile()            
        except Exception, e:
            if self.debug:
                traceback.print_exc(file=sys.stderr)
            self.reply = xenrt.XRT("SSH connection failed", self.level)
            self.toreply = 1
            self.close()
        if self.debug:
            xenrt.TEC().logverbose("done (2)")

    def read(self, retval="code", fh=None):
        """Process the output and result of the command.

        @param retval: Whether to return the result code (default) or 
            stdout as a string.
    
            string  :   Return a stdout as a string.
            code    :   Return the result code. (Default). 
                  
            If "string" is used then a failure results in an exception.
 
        """

        if self.toreply:
            if retval == "string":
                raise self.reply
            return self.reply
        reply = ""

        while True:
            try:
                if fh:
                    output = self.fh.read(4096)
                else:
                    if self.debug:
                        xenrt.TEC().logverbose("readline")
                    output = self.fh.readline()
            except socket.timeout:
                if self.debug:
                    xenrt.TEC().logverbose("close")
                self.close()
                return xenrt.XRT("SSH timed out", self.level)
            if len(output) == 0:
                break
            if fh:
                fh.write(output)
            elif retval == "string":
                reply = reply + output
            if not self.nolog and not fh:
                xenrt.TEC().log(output)
        if self.debug:
            xenrt.TEC().logverbose("recv_exit_status")
        self.exit_status = self.client.recv_exit_status()
        
        # Local clean up.
        if self.debug:
            xenrt.TEC().logverbose("close (2)")
        self.close()
        
        if retval == "code":
            return self.exit_status
        if self.exit_status == -1:
            return xenrt.XRT("SSH channel closed unexpectedly",
                             self.level,
                             data=reply)
        elif not self.exit_status == 0:
            return xenrt.XRT("SSH command exited with error (%s)" %
                             (self.command), self.level, data=reply)

        if self.debug:
            xenrt.TEC().logverbose("done (3)")
        return reply
    
    def __del__(self):
        SSHSession.__del__(self)   
 
def SSH(ip,
        command,
        username="root",
        timeout=1200,
        level=xenrt.RC_ERROR,
        retval="code",
        password=None,
        idempotent=False,
        nowarn=False,
        newlineok=False,
        getreply=True,
        nolog=False,
        outfile=None,
        useThread=False,
        usePty=False,
        port=22):
    tries = 0
    while True:
        tries = tries + 1
        
        if tries > 1:
            xenrt.TEC().logverbose("SSH %s@%s %s (attempt %u)" % (username, ip, command, tries))
        else:
            xenrt.TEC().logverbose("SSH %s@%s %s" % (username, ip, command))
        
        try:
            s = SSHCommand(ip,
                           command,
                           username=username,
                           timeout=timeout,
                           level=level,
                           password=password,
                           nowarn=nowarn,
                           newlineok=newlineok,
                           nolog=nolog,
                           useThread=useThread,
                           usePty=usePty,
                           port=port)
            if outfile:
                try:
                    f = file(outfile, 'w')
                    reply = s.read(retval="code", fh=f)
                finally:
                    f.close()
                return reply
            elif getreply:
                reply = s.read(retval=retval)
                return reply
            else:
                return None
        except Exception, e:
            if tries >= 3 or not idempotent:
                raise
            if string.find(str(e), "SSH command exited with error") > -1:
                raise
            if not nowarn:
                xenrt.TEC().warning("Retrying ssh connection %s@%s %s after %s"
                                    % (username, ip, command, str(e)))
            xenrt.sleep(5)

@xenrt.irregularName
def SSHread(ip,
            command,
            username="root",
            timeout=300,
            level=xenrt.RC_ERROR, 
            password=None,
            idempotent=False,
            nowarn=False,
            newlineok=False,
            port=22):
    tries = 0
    while True:
        tries = tries + 1
        
        if tries > 1:
            xenrt.TEC().logverbose("SSH %s@%s %s (attempt %u)" % (username, ip, command, tries))
        else:
            xenrt.TEC().logverbose("SSH %s@%s %s" % (username, ip, command))
        
        try:
            s = SSHCommand(ip,
                           command,
                           username=username,
                           timeout=timeout,
                           level=level,
                           password=password,
                           nowarn=nowarn,
                           newlineok=newlineok,
                           port=port)
            reply = s.read(retval="string")
            return reply
        except Exception, e:
            if tries >= 3 or not idempotent:
                raise e
            if string.find(str(e), "SSH command exited with error") > -1:
                raise e
            if not nowarn:
                xenrt.TEC().warning("Retrying ssh connection %s@%s %s after %s"
                                    % (username, ip, command, str(e)))
            xenrt.sleep(5)

def createFile(guest, 
        data="",
        path="/tmp/temp.txt"):
        """Create a file on guest VM and write data to it"""
        t = xenrt.TEC().tempFile()
        f = file(t, "w")
        f.write(data)
        f.close()
        sftp = guest.sftpClient()
        try:
            sftp.copyTo(t, path)
        finally:
            sftp.close()
        guest.execcmd("chmod +x %s" % path)
