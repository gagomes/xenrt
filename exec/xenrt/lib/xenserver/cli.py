#
# XenRT: Test harness for Xen and the XenServer product family
#
# XenServer CLI interface
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, os, glob, os.path, string, re, time
import xenrt

# Symbols we want to export from the package.
__all__ = ["getSession",
           "clearCacheFor",
           "buildCommandLine"]

sessions = {}
def getSession(machine):
    global sessions
    if not sessions.has_key(machine):
        sessions[machine] = Session(machine, cached=True)
    return sessions[machine]

def clearCacheFor(machine):
    global sessions
    if sessions.has_key(machine):
        del sessions[machine]

class Session(object):
    """A CLI (multi)session to a host."""
    def __init__(self, machine, username="root", password=None, cd=None,
                 cached=False):
        self.username = username
        if password:
            self.password = password
        elif machine.host:
            self.password = machine.host.password
        else:
            self.password = None
        self.machine = machine
        self.cached = cached
        self.dir = None
        self.tempDir = None
        self.winguest = None
        self.debug_on_fail = False

        if not self.password:
            self.password = xenrt.TEC().lookup("ROOT_PASSWORD")
        
        if xenrt.TEC().registry.read("/xenrt/cli/windows"):
            self.winguest = xenrt.TEC().registry.read(\
                    "/xenrt/cli/windows_guest") 
            if not self.winguest:
                raise xenrt.XRTError("Could not find guest in registry.")
            # Install xe.exe
            self.winguest.installCarbonWindowsCLI()
        else:
            if xenrt.command("which xe", retval="code") == 0 and not xenrt.TEC().lookup("OPTION_USE_XE_FROM_XS", False, boolean=True):
                # Use the version in the distro
                self.dir = os.path.dirname(xenrt.command("which xe"))
            else:
                self.tempDir = xenrt.TempDirectory()
                self.dir = self.tempDir.path()
                mount = None
                # Places we'll look for the CLI binary.
                cds = []
                if cd:
                    cds.append(cd)
                else:
                    imageName = xenrt.TEC().lookup("CARBON_CD_IMAGE_NAME", 'main.iso')
                    xenrt.TEC().logverbose("Using XS install image name: %s" % (imageName))
                    try:
                        cd = xenrt.TEC().getFile("xe-phase-1/%s" % (imageName), imageName)
                        if cd:
                            cds.append(cd)
                    except:
                        pass
                    if machine.host:
                        ecds = machine.host.getDefaultAdditionalCDList()
                        if ecds:
                            for ecd in string.split(ecds, ","):
                                if os.path.exists(ecd):
                                    cds.append(ecd)
                                else:
                                    try:
                                        cd = xenrt.TEC().getFile("xe-phase-1/%s" % (os.path.basename(ecd)), os.path.basename(ecd))
                                        if cd:
                                            cds.append(cd)
                                    except:
                                        pass
                    else:
                        try:
                            cd = xenrt.TEC().getFile("xe-phase-1/linux.iso", "linux.iso")
                            if cd:
                                cds.append(cd)
                        except:
                            pass


                # Get a CLI binary from the CD.
                rpm = None
                localarch = xenrt.command("uname -m").strip()
                remotearch = machine.getHost().execdom0("uname -m").strip()
                if remotearch == "x86_64" and localarch != "x86_64":
                    xenrt.TEC().logverbose("Using local CLI binary")
                    rpm = "%s/tests/xe/xe-cli.i686.rpm" % xenrt.TEC().lookup("XENRT_BASE")
                else:
                    for cd in cds:
                        # TODO: look for x86_64 RPMs if localarch is 64-bit.
                        xenrt.checkFileExists(cd)
                        mount = xenrt.MountISO(cd)
                        mountpoint = mount.getMount()
                        fl = glob.glob("%s/xe-cli-[0-9]*i?86.rpm" % (mountpoint))
                        if len(fl) != 0:
                            xenrt.TEC().logverbose("Using CLI binary from ISO %s" %
                                                   (cd))
                            rpm = fl[-1]
                            break
                        fl = glob.glob("%s/client_install/xe-cli-[0-9]*i?86.rpm" %
                                       (mountpoint))
                        fl.extend(glob.glob(\
                            "%s/client_install/xenenterprise-cli-[0-9]*i?86.rpm" %
                            (mountpoint)))
                        if len(fl) != 0:
                            xenrt.TEC().logverbose("Using CLI binary from ISO %s" %
                                                   (cd))
                            rpm = fl[-1]
                            break
                        mount.unmount()
                        mount = None

                    # Try a client_install subdir next to the main ISO.
                    if not rpm:
                        if len(cds) > 0:
                            cd = cds[0]
                            p = "%s/client_install" % (os.path.dirname(cd))
                            if os.path.exists(p):
                                fl = glob.glob("%s/xe-cli-[0-9]*i?86.rpm" % (p))
                                if len(fl) != 0:
                                    xenrt.TEC().logverbose("Using CLI binary from "
                                                           "split directory")
                                    rpm = fl[-1]

                if not rpm:
                    # Fallback is to copy the binary from the dom0.
                    h = machine.getHost()
                    if not h:
                        raise xenrt.XRTError("No host associate with %s, "
                                             "cannot get CLI" % (machine.name))
                    xenrt.TEC().logverbose("Copying CLI binary from host")
                    sftp = h.sftpClient()
                    sftp.copyFrom("/opt/xensource/bin/xe",
                                  "%s/xe" % (self.tempDir.path()))
                    sftp.close()
                else:
                    xenrt.TEC().logverbose("Using CLI RPM %s" %
                                           (os.path.basename(rpm)))
                    if xenrt.command("cd %s && rpm2cpio %s | cpio -idv"
                                     % (self.tempDir.path(), rpm), retval="code") != 0:
                        raise xenrt.XRTError("Error extracting CLI binary from %s"
                                             % (rpm))
                    if xenrt.command("mv %s/opt/xensource/bin/xe %s" %
                                     (self.tempDir.path(), self.tempDir.path()),
                                     retval="code") == 0:
                        pass
                    elif xenrt.command("mv %s/usr/bin/xe %s" %
                                     (self.tempDir.path(), self.tempDir.path()),
                                     retval="code") != 0:
                        raise xenrt.XRTError("Couldn't find xe in RPM")
                xenrt.TEC().logverbose("Test whether xe supports --debug-on-fail")
                if mount:
                    mount.unmount()
        
            if xenrt.command("%s/xe --debug-on-fail" % self.dir,
                             retval="code", level=xenrt.RC_OK) == 0:
                self.debug_on_fail = True
                xenrt.TEC().logverbose("xe supports --debug-on-fail, now available "
                                       "for use in any cli calls.")
            else:
                xenrt.TEC().logverbose("xe doesn't support --debug-on-fail")
                
    def close(self):
        if self.tempDir and not self.cached:
            # Remove the CLI binary.
            self.tempDir.remove()
            self.tempDir = None
            self.dir = None

    def xePath(self):
        """Return the full path to the xe binary."""
        return "%s/xe" % (self.dir)

    def execute(self,
                command,
                args="",
                retval="string",
                level=xenrt.RC_FAIL,
                timeout=2700,
                ignoreerrors=False,
                compat=None,
                strip=False,
                minimal=False,
                username=None,
                password=None,
                useCredentials=True,
                debugOnFail=False,
                nolog=False):
        """Execute a CLI command"""
        argusername = self.username
        argpassword = self.password
        if username:
            argusername = username
        if password:
            argpassword = password
        c = buildCommandLine(self.machine.getHost(),
                             command,
                             args=args,
                             compat=compat,
                             minimal=minimal,
                             username=argusername,
                             password=argpassword,
                             useCredentials=useCredentials)

        if (self.debug_on_fail and 
            (debugOnFail or xenrt.TEC().lookup("XE_DEBUG_ON_FAIL", False, boolean=True))):
            c = c + " --debug-on-fail"

        if xenrt.TEC().lookup("NO_XE_SSL", False, boolean=True) or (xenrt.TEC().lookup("WORKAROUND_CA109448", False, boolean=True) and re.search(".*-(import|upload|restore(-database)?)$",command)):
            c = c + " --nossl"

        if minimal:
            strip = True

        if xenrt.TEC().lookup("EXTRA_TIME", False, boolean=True):
            timeout = timeout * 2

        ex = None
        for i in range(3):
            try:
                if xenrt.TEC().registry.read("/xenrt/cli/windows"):
                    c = re.sub("-pw '([^']+)'", "-pw \\1", c)
                    return re.sub("\n.*xe.exe.*\n", "", 
                        self.winguest.xmlrpcExec("c:\\windows\\xe.exe %s" %
                                                 (c),
                                                 level=level,
                                                 timeout=timeout,
                                                 returnerror=False,
                                                 returndata=True)).strip()
                else:
                    try:
                        xenrt.TEC().logverbose("DEBUG command: %r/xe %s" % (self.dir,c))
                        reply = xenrt.command("%s/xe %s" % (self.dir,c),
                                              retval=retval,
                                              level=level,
                                              timeout=timeout,
                                              ignoreerrors=ignoreerrors,
                                              strip=strip,
                                              nolog=nolog)
                        return reply
                    except xenrt.XRTException, e:
                        xenrt.TEC().logverbose("DEBUG e.data: %r" % e.data)
                        # Propogate connectivity problems to retry loop
                        if e.data and re.search(r"Connection reset by peer",
                                                e.data):
                            raise
                        # Clean up the exception from the local command
                        # execution function. Take the first line of
                        # any output and any uppercase strings that look
                        # like error messages
                        if not e.data:
                            raise
                        firstline = string.split(e.data, "\n")[0]
                        if not firstline:
                            e.changeReason("CLI command %s failed" % (command))
                        else:
                            r = re.search(r"^reason: (.*)",
                                          e.data,
                                          re.MULTILINE)
                            if r:
                                firstline = "%s (%s)" % (firstline, r.group(1))
                            if re.search(r"The server failed to handle your request, due to an internal error", e.data):
                                r = re.search(r"^message: (.*)",
                                              e.data,
                                              re.MULTILINE)
                                if r:
                                    firstline = r.group(1)
                            if firstline == "Unhandled exception":
                                try:
                                    secondline = string.split(e.data, "\n")[1]
                                    firstline = "%s: %s" % (firstline,
                                                            secondline)
                                except:
                                    pass
                            r = re.search(r"([A-Z][A-Z0-9_]{4,})", e.data)
                            rmsg = re.search(r"msg:.*?\[(.*)\]", e.data)
                            if r:
                                if r.group(1) == "SR_BACKEND_FAILURE_200" and \
                                       re.search(r"Snapshot XenStorage\S+ "
                                                 "already exists", e.data):
                                    
                                    e.changeReason("CLI command %s failed: "
                                                   "Snapshot already exists "
                                                   "(%s)" %
                                                   (command, r.group(1)))
                                elif (r.group(1).startswith("SR_BACKEND_FAILURE_") or r.group(1) == "INTERNAL_ERROR") and rmsg:
                                    rmsgtxt = rmsg.group(1).replace("\\", "")
                                    rmsgtxt = rmsgtxt.strip(" ;")
                                    e.changeReason("CLI command %s failed: %s (%s %s)"
                                                   % (command,
                                                      firstline,
                                                      r.group(1),
                                                      rmsgtxt))
                                else:
                                    e.changeReason("CLI command %s failed: %s (%s)"
                                                   % (command,
                                                      firstline,
                                                      r.group(1)))
                            else:
                                e.changeReason("CLI command %s failed: %s" %
                                               (command, firstline))
                        raise e
                        
            except xenrt.XRTException, e:
                if xenrt.TEC().lookup("WORKAROUND_CA59859", False, boolean=True):
                    if command == "pif-reconfigure-ip" and e.data and re.search("Failed to see host on network after timeout expired", e.data):
                        return
                if not e.data or not \
                       re.search(r"Connection reset by peer", e.data):
                    raise
                ex = e
            xenrt.TEC().warning("Retrying CLI command %s" % (c))
            xenrt.sleep(30)
        # If we get here then we've failed three times.
        raise ex

def buildCommandLine(host,
                     command,
                     args="",
                     compat=None,
                     minimal=False,
                     username=None,
                     password=None,
                     useCredentials=True):
    """Prepare the command line arguments for a CLI command"""
    extras = []
    if isinstance(host, xenrt.lib.xenserver.Host):
        serverflag = "-s"
    else:
        serverflag = "-h"
    serverflag = host.lookup("CLI_SERVER_FLAG", serverflag)
    
    # XE 3.1, 3.2 compatability mode.
    if compat == True:
        extras.append("compat=true")
    elif compat == None:
        if host.compatCLI() == xenrt.lib.xenserver.host.CLI_LEGACY_COMPAT:
            extras.append("compat=true")
            serverflag = "-h"
    if minimal:
        extras.append("--minimal")

    c = [command]
    c.append("%s %s" % (serverflag, host.getIP()))
    if useCredentials:
        if not username:
            username = "root"
        c.append("-u %s" % (username))
        if not password:
            if host.password:
                password = host.password
            else:
                password = host.lookup("ROOT_PASSWORD")
        c.append("-pw '%s'" % (password))
    if args:
        c.append(args)
    c.extend(extras)

    return string.join(c)

