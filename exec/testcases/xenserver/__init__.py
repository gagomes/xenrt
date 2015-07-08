#
# XenRT: Test harness for Xen and the XenServer product family
#
# Test XenServer operations
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, re, string, os.path, urllib, traceback, time, xml.dom.minidom
import xenrt, xenrt.lib.xenserver

class TCDDKImport(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCDDKImport")

    def run(self, arglist=None):

        kit = "ddk"

        if arglist and len(arglist) > 0:
            machine = arglist[0]
        else:
            raise xenrt.XRTError("No machine specified for installation")
        if len(arglist) < 2:
            raise xenrt.XRTError("No guest name specified")
        guestname = arglist[1]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)

        # Optional arguments
        vcpus = None
        memory = None
        uninstall = True

        for arg in arglist[2:]:
            l = string.split(arg, "=", 1)
            if l[0] == "vcpus":
                vcpus = int(l[1])
            elif l[0] == "memory":
                memory = int(l[1])
            elif l[0] == "uninstall":
                uninstall = True
            elif l[0] == "kit":
                kit = l[1]

        g = host.guestFactory()(\
            guestname, "NO_TEMPLATE",
            password=xenrt.TEC().lookup("ROOT_PASSWORD_DDK"))
        g.host = host
        self.guest = g
        if vcpus != None:
            g.setVCPUs(vcpus)
        if memory != None:
            g.setMemory(memory)

        # Perform the import
        ddkzip = None
        ddkiso = xenrt.TEC().lookup("DDK_CD_IMAGE", None)
        if not ddkiso:
            # Try the same directory as the ISO
            ddkiso = xenrt.TEC().getFile("%s.iso" % (kit), "xe-phase-2/%s.iso" % (kit))
        if not ddkiso:
            ddkzip = xenrt.TEC().getFile("%s.zip" % (kit), "xe-phase-2/%s.zip" % (kit))
        if not ddkiso and not ddkzip:
            raise xenrt.XRTError("No DDK ISO/ZIP file given")
        try:
            if ddkiso:
                mount = xenrt.MountISO(ddkiso)
                mountpoint = mount.getMount()
            if ddkzip:
                # XXX Make this a tempDir once we've moved them out of /tmp
                tmp = xenrt.NFSDirectory()
                mountpoint = tmp.path()
                xenrt.command("unzip %s -d %s" % (ddkzip, mountpoint))
            g.importVM(host, "%s/%s" % (mountpoint, kit))
        finally:
            try:
                if ddkiso:
                    mount.unmount()
                if ddkzip:
                    tmp.remove()
            except:
                pass
        g.memset(g.memory)
        g.cpuset(g.vcpus)

        xenrt.TEC().registry.guestPut(guestname, g)

        # Make sure we can boot it
        g.makeNonInteractive()
        g.tailored = True
        g.start()
        time.sleep(120)
        g.shutdown()

        # Uninstall
        if uninstall:
            g.uninstall()
        
    def postRun(self):
        r = self.getResult(code=True)
        if r == xenrt.RESULT_FAIL or r == xenrt.RESULT_ERROR:
            # Make sure the guest isn't running anymore
            if self.guest:
                self.tec.logverbose("Making sure %s is shut down" %
                                    (self.guest.name))
                try:
                    self.guest.shutdown(force=True)
                except:
                    pass

class TCXenOps(xenrt.TestCase):

    outcomes = {"SUCCEED" : xenrt.RESULT_PASS,
                "FAILURE" : xenrt.RESULT_FAIL,
                "SKIPPED" : xenrt.RESULT_SKIPPED}

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCXenOps")
        self.hostToClean = None

    def run(self, arglist=None):

        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)

        # Get the test scripts
        testtar = xenrt.TEC().lookup("XENOPS_REGRESSION_TESTS", None)
        if not testtar:
            # Try the same directory as the ISO
            testtar = xenrt.TEC().getFile("xenops-regress.tar.gz", 
                                          "xe-phase-1/xenops-regress.tar.gz")
        if not testtar:
            raise xenrt.XRTError("No CLI regression test tarball given")
        xenrt.command("tar -zxf %s -C %s" % (testtar, self.tec.getWorkdir()))
        if os.path.exists("%s/runtest" % (self.tec.getWorkdir())):
            testbin = "runtest"
        else:
            raise xenrt.XRTError("runtest not found in test tarball")

        # Copy test files to the host
        ramdisk = "initrd-1.1-i386.img"
        xenrt.getTestTarball("xm", extract=True)
        sftp = host.sftpClient()
        rdir = host.hostTempDir()
        sftp.copyTreeTo(self.tec.getWorkdir(), rdir)

        # Get dom0 kernel filename
        kver = string.strip(host.execdom0("uname -r"))
        kfile = "/boot/vmlinuz-%s" % (kver)
        if host.execdom0("ls %s" % (kfile), retval="code") != 0:
            raise xenrt.XRTError("Kernel not where expected (%s)" % (kfile))

        # Build a command line to run the regression test on dom0
        cmd = []
        cmd.append("%s/%s" % (rdir, testbin))
        cmd.append(kfile)
        cmd.append("%s/xm/%s" % (rdir, ramdisk))
        cmd.append("%s/log.txt" % (rdir))
        
        # Run the test
        self.hostToClean = host
        passed = True
        try:
            commands = []
            commands.append("cd %s" % (rdir))
            commands.append("PATH=.:${PATH} %s > output.txt 2> stderr.log" %
                            (string.join(cmd)))
            self.runAsync(host, commands, timeout=3600)
        except:
            traceback.print_exc(file=sys.stderr)
            self.tec.reason("Test exited with error or timed out")
            passed = False
        for f in ('log.txt', 'output.txt', 'stderr.log'):
            try:
                sftp.copyFrom("%s/%s" % (rdir, f),
                              "%s/%s" % (self.tec.getLogdir(), f))
            except:
                pass

        # Check for failures
        resfile = "%s/output.txt" % (self.tec.getLogdir())
        if os.path.exists(resfile):
            f = file(resfile, "r")
            while True:
                line = f.readline()
                if not line:
                    break
                r = re.search(r"^test\s+\d+\[\s*(\d+)\]\s+\(\s*(.+)\):"
                              "\s+([A-Z]+)", line)
                if r:
                    tc = r.group(1)
                    group = string.replace(r.group(2), " ", "_")
                    outcome = r.group(3)
                    if self.outcomes.has_key(outcome):
                        self.testcaseResult(group, tc, self.outcomes[outcome])
                        if self.outcomes[outcome] == xenrt.RESULT_FAIL or \
                               self.outcomes[outcome] == xenrt.RESULT_ERROR:
                            passed = False
                    else:
                        self.tec.warning("Unknown outcome '%s'" % (outcome))
            f.close()
        else:
            passed = False
            self.tec.reason("No output file found")

        if not passed:
            raise xenrt.XRTFailure()

    def postRun(self):
        if self.hostToClean:
            self.hostToClean.reboot()

class TCHostReboot(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCHostReboot")
        self.blocker = True

    def run(self, arglist=None):

        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)

        # Reboot the host
        if xenrt.TEC().lookup("PERFRUN", False, boolean=True):
            start = xenrt.timenow()
        host.reboot()
        if xenrt.TEC().lookup("PERFRUN", False, boolean=True):
            finish = xenrt.timenow()
            xenrt.TEC().value("Reboot", finish-start, "s")
    
class TCMisc(xenrt.TestCase):
    
    def __init__(self, tcid="TCMisc"):
        xenrt.TestCase.__init__(self, tcid)
        self.guestsToClean = []
        self.guests = {}
        self.host = None

    def run(self, arglist=None):
        
        machine = None
        if not arglist or len(arglist) == 0:
            machine = "RESOURCE_HOST_0"
        else:
            l = string.split(arglist[0], "=")
            if len(l) == 1:
                machine = l[0]

        try:
            host = xenrt.TEC().registry.hostGet(machine)
            if not host:
                raise xenrt.XRTError("Unable to find host %s in registry" %
                                     (machine))
            self.getLogsFrom(host)

            self.host = host

            # Create a basic guest
            deb = host.createGenericLinuxGuest()
            self.guestsToClean.append(deb)
            deb.preCloneTailor()
            self.guests["debian"] = deb
        except xenrt.XRTFailure, e:
            # Anything that breaks here is not a failure of the testcase
            raise xenrt.XRTError(e.reason)

        self.runSubcase("ca7709", (), "CA-7709", "NotCrash")
        self.runSubcase("ca8095", (), "CA-8095", "WillStart")
        self.runSubcase("ca8294", (), "CA-8294", "WillShutdown")
        self.runSubcase("ca8358", (), "CA-8358", "WillStart")
        self.runSubcase("ca6753", (), "CA-6753", "WillShutdown")
        #self.runSubcase("ca8240", (), "CA-8240", "WillValidate")

    def clone(self,gname):
        try:
            g = self.guests[gname]
            if g.getState() == "UP":
                g.shutdown()
            c = g.cloneVM()
            self.guestsToClean.append(c)
            return c
        except xenrt.XRTFailure, e:
            # Anything that breaks here is not a failure of the testcase
            raise xenrt.XRTError("Failure while cloning guest: %s" % (gname))

    def ca7709(self):
        g = self.guests["debian"]
        if g.getState() == "UP":
            g.shutdown()
        for i in range(20):
            g.start(skipsniff=True)
            g.shutdown(force=True)
            g.host.execdom0("true")

    def ca8095(self):
        try:
            try:
                c = self.clone("debian")
                for dev in c.listDiskDevices():
                    c.removeDisk(dev)
                devs = c.listDiskDevices()
                if len(devs) != 0:
                    raise xenrt.XRTError("Did not remove all disks: %s" %
                                         (string.join(devs, ", ")))
            except xenrt.XRTFailure, e:
                # Anything that breaks here is not a failure of the testcase
                raise xenrt.XRTError(e.reason)
            try:
                c.lifecycleOperation("vm-start")
            except xenrt.XRTException, e:
                if not e.data:
                    raise xenrt.XRTError("Did not get any text back from the "
                                         "CLI command")
                if re.search(r"no bootable disk", e.data):
                    # This is the desired result
                    return
                raise xenrt.XRTFailure("Error message was: %s" %
                                       (string.strip(e.data)))
        finally:
            try:
                if c.getState() != "DOWN":
                    c.shutdown(force=True)
                c.uninstall()
                self.guestsToClean.remove(c)
            except:
                pass
            
    def ca8294(self):
        try:
            c = self.clone("debian")
            # Start
            c.start()
            # Suspend
            c.suspend()
        except xenrt.XRTFailure, e:
            # Anything that breaks here is not a failure of the testcase
            raise xenrt.XRTError(e.reason)
        try:
            c.shutdown(force=True)
        except xenrt.XRTException, e:
            raise xenrt.XRTFailure("Error message was: %s" %
                                   (string.strip(e.data)))
        if c.getState() != "DOWN":
            raise xenrt.XRTFailure("Guest did not shutdown")
        try:
            c.uninstall()
            self.guestsToClean.remove(c)
        except xenrt.XRTFailure, e:
            raise xenrt.XRTError(e.reason)

    def ca8358(self):
        try:
            c = self.clone("debian")
            c.memset(c.host.getFreeMemory())
        except xenrt.XRTFailure, e:
            # Anything that breaks here is not a failure of the testcase
            raise xenrt.XRTError(e.reason)
        try:
            c.start()
        except xenrt.XRTFailure, e:
            raise xenrt.XRTFailure("Guest did not start")
        try:
            c.shutdown()
            c.uninstall()
            self.guestsToClean.remove(c)
        except xenrt.XRTFailure, e:
            raise xenrt.XRTError(e.reason)

    def ca6753(self):
        host = self.host
        g = None
        try:
            # Create an HVM guest
            repository = xenrt.getLinuxRepo("rhel5", "x86-32", "HTTP")
            template = host.chooseTemplate("TEMPLATE_NAME_UNSUPPORTED_HVM")
            g = host.guestFactory()(xenrt.randomGuestName(), template)
            self.guestsToClean.append(g)
            g.windows = False
            g.setVCPUs(1)
            g.setMemory(256)
            g.arch = "x86-32"
            g.install(host, repository=repository, distro="rhel5", 
                      method="HTTP", pxe=True)		
            if g.getState() == "DOWN":
                g.start()
        except xenrt.XRTFailure, e:
            # This is not a failure of the testcase
            raise xenrt.XRTError(e.reason)

        g.execguest("dd if=/dev/zero of=foo bs=4K count=250K "
                    "> /dev/null 2>&1 &")
        g.lifecycleOperation("vm-shutdown", force=True)
        time.sleep(60)

        # See if the host is there
        try:
            upt = host.execdom0("cat /proc/uptime",timeout=30)
            # Parse this uptime data
            uptv = upt.split()
            seconds = int(round(float(uptv[0])))
            xenrt.TEC().comment("Host uptime: %d seconds" % (seconds))
            # If it's less than 120 then we assume it crashed (will have taken
            # more than a minute to install the guest!)            
            if seconds < 120:
                raise xenrt.XRTFailure("Uptime too low")
        except xenrt.XRTFailure, e:
            raise xenrt.XRTFailure("Host died after vm-shutdown!")
        
    def ca8240(self):
        """no validation while setting the userdevice parameter"""
        maxAllowed = None
        vbduuid = None
        try:
            c = self.clone("debian")
            # Find out the maximum allowed vbd device
            maxAllowed = max(map(int,
                         self.host.genParamGet("vm",c.getUUID(),
                                           "allowed-VBD-devices").split("; ")))
            vbds = self.host.minimalList("vbd-list","uuid","vm-uuid=%s" % 
                                         (c.getUUID()))
            vbduuid = vbds[0]
        except xenrt.XRTFailure, e:
            # Anything that breaks here is not a failure of the testcase
            raise xenrt.XRTError(e.reason)
    
        allowed = True
        try:
            cli = self.host.getCLIInstance()
            cli.execute("vbd-param-set", "userdevice=%d uuid=%s" % 
                                         (maxAllowed+1,vbduuid))
        except xenrt.XRTFailure, e:
            allowed = False

        if allowed:
            raise xenrt.XRTFailure("Allowed to set userdevice to a value "
                                   "not in allowed-VBD-devices")
        
    def postRun(self):
        for g in self.guestsToClean:
            try:
                g.shutdown(force=True)
            except:
                pass
            try:
                g.poll("DOWN", 120, level=xenrt.RC_ERROR)
                g.uninstall()
                time.sleep(15)
            except:
                pass

class TCBackupRestore(xenrt.TestCase):
    """Test the host-backup and host-restore CLI operations"""

    def __init__(self, tcid="TCBackupRestore"):
        xenrt.TestCase.__init__(self, tcid)

    def run(self, arglist=None):
        # TODO: Use a better method of checking for a correct restore
        #       Test the version compatibility sanity check if it exists?

        machine = None
        if not arglist or len(arglist) == 0:
            machine = "RESOURCE_HOST_0"
        else:
            l = string.split(arglist[0], "=")
            if len(l) == 1:
                machine = l[0]

        try:
            host = xenrt.TEC().registry.hostGet(machine)
            if not host:
                raise xenrt.XRTError("Unable to find host %s in registry" %
                                    (machine))

            self.getLogsFrom(host)

        except xenrt.XRTFailure, e:
            # Anything that happens here is not a failure of the testcase
            raise xenrt.XRTError(e.reason)

        # Currently use workdir on controller for storing backup - hopefully
        # it won't be too big!
        workdir = xenrt.TEC().getWorkdir()

        # Write a file onto the host (we can then check for it later)
        host.execdom0("touch /TCBackupRestore.xrt")        

        # Back it up
        host.backup("%s/backup" % (workdir))

        # Print the size (hopefully this will help with debugging CA-9225)
        xenrt.TEC().comment("Backup file size: %u bytes" % 
                            (os.path.getsize("%s/backup" % (workdir))))

        # Re-install the host
        try:
            host.uuid = None
            host.dom0uuid = None
            host.reinstall()
            time.sleep(180)
        except xenrt.XRTFailure, e:
            raise xenrt.XRTError("Failure during reinstall: %s" % (e.reason))

        # Restore the backup
        host.restore("%s/backup" % (workdir),bringlive=True)      

        # At present, we don't have support for actually bringing the backup
        # partition live, so for now just check the file is there on it
        bp = host.execdom0("grep BACKUP_PARTITION /etc/xensource-inventory | "
                           "awk -F= '{ print $2 }' | sed -e \"s/'//g\"").strip()

        host.execdom0("mkdir -p /mnt/xrt")

        try:
            host.execdom0("mount %s /mnt/xrt" % (bp))
        except xenrt.XRTFailure, e:
            raise xenrt.XRTFailure("Unable to mount backup partition!")


        # See if the file exists
        try:
            host.execdom0("cat /mnt/xrt/TCBackupRestore.xrt")
        except xenrt.XRTFailure, e:
            raise xenrt.XRTFailure("Host did not restore correctly!")

        host.execdom0("umount /mnt/xrt")

class TCWindowsExport(xenrt.TestCase):

    def __init__(self, tcid="TCWindowsExport"):
        xenrt.TestCase.__init__(self, tcid=tcid)
        self.client = None
        self.target = None
        self.loops = 1
        self.usecli = True

    def prepare(self, arglist):
        gname = None

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            if l[0] == "loops":
                self.loops = int(l[1])
            elif l[0] == "export":
                self.target = self.getGuest(l[1])
                if not self.target:
                    raise xenrt.XRTError("Could not find guest %s" % (l[1]))
            elif l[0] == "gui":
                self.usecli = False
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("No client guest specified")
        self.client = self.getGuest(gname)
        if not self.client:
            raise xenrt.XRTError("Could not find guest %s" % (gname))

        if not self.target:
            raise xenrt.XRTError("No guest-to-be-exported specified.")

        if self.usecli:
            # Install xe.exe on the client
            self.client.installCarbonWindowsCLI()
        else:
            # Install GUI on the client
            self.client.installCarbonWindowsGUI()
            if True:
                # Dodgy hack for now
                self.client.installCarbonWindowsCLI()
                path, exe = self.client.findCarbonWindowsGUI()
                self.client.xmlrpcExec("COPY c:\\windows\\xe.exe \"%s\"" %
                                       (path))

        if not self.client.xmlrpcFileExists("c:\\sha1sum.exe"):
            self.client.xmlrpcSendFile("%s/utils/sha1sum.exe" %
                                       (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")),
                                       "c:\\sha1sum.exe")
        
        # Make sure the target is down
        if self.target.getState() == "UP":
            self.target.shutdown()

    def run(self, arglist):

        password = self.target.host.password
        if not password:
            password = xenrt.TEC().lookup("ROOT_PASSWORD")
        username = "root"
        if not self.usecli:
            path, exe = self.client.findCarbonWindowsGUI()

        success = 0
        try:
            for i in range(self.loops):
                xenrt.TEC().progress("Starting loop iteration %u..." % (i))

                # Remove any old export file
                try:
                    self.client.xmlrpcRemoveFile("c:\\export.img", patient=True)
                except:
                    pass

                # Perform the export
                args = []
                if self.usecli:
                    args.append("xe.exe -s %s -u %s -pw %s" %
                                (self.target.host.getIP(), username, password))
                    args.append("vm-export")
                    args.append("vm=\"%s\"" % (self.target.getName()))
                    args.append("filename=\"c:\\\\export.img\"")
                else:
                    # Create a directory for the UI to write extra logs and
                    # screenshots to
                    ld = self.remoteLoggingDirectory(self.client)

                    args.append("cd %s\n" % (path))
                    args.append(exe)
                    if self.client.xmlrpcFileExists(\
                        "c:\\XenCenterTestResources\\export.testrun"):
                        args.append("runtests testrun=\"export.testrun\"")
                    else:
                        args.append("runtests export=true")
                    args.append("host=\"%s\"" % (self.target.host.getIP()))
                    args.append("username=%s" % (username))
                    args.append("password=%s" % (password))
                    args.append("vm=\"%s\"" % (self.target.getName()))
                    args.append("filename=\"c:\\\\export.img\"")
                    args.append("disable_help_tests=true ")
                    args.append("disable_depenency_resolution=true ")
                    args.append("log_directory=\"%s\"" % (ld))
                data = self.client.xmlrpcExec(string.join(args),
                                              timeout=7200,
                                              returndata=True)

                if not self.client.xmlrpcFileExists("c:\\export.img", patient=True):
                    raise xenrt.XRTFailure("Export image file does not exist")

                # Unpack the export file. Note that we change colons in
                # filenames to underscores
                try:
                    rtmp = self.client.xmlrpcTempDir(patient=True)
                    xenrt.TEC().logverbose("Unpacking into %s" % (rtmp))
                    self.client.xmlrpcExtractTarball("c:\\export.img", rtmp, patient=True)

                    # Compare the SHA1 sums of the files with the manifest
                    if not self.client.xmlrpcFileExists("%s\\checksum.xml" % (rtmp), patient=True):
                        raise xenrt.XRTFailure("Checksum file does not exist")
                    csums = self.client.xmlrpcReadFile("%s\\checksum.xml" %
                                                       (rtmp), patient=True)
                    files = self.parseChecksums(csums)
                    filelist = []
                    for file in files:
                        name, csum = file
                        name = string.replace(name, ":", "_")
                        name = string.replace(name, "/", "\\")
                        filelist.append(name)
                    xenrt.TEC().logverbose("Summing file chunks...")
                    actuals = self.client.xmlrpcSha1Sums(rtmp, filelist, patient=True)

                    for file in files:
                        name, csum = file
                        name = string.replace(name, ":", "_")
                        name = string.replace(name, "/", "\\")
                        xenrt.TEC().logverbose("Checking file %s..." % (name))
                        #fullpath = "%s\\%s" % (rtmp, name)
                        #if not rpc.fileExists(fullpath):
                        #    raise xenrt.XRTFailure("%s does not exist" %
                        #                           (name))
                        #sha1 = rpc.sha1Sum(fullpath)
                        sha1 = actuals[name]
                        if sha1 != csum:
                            raise xenrt.XRTFailure("Checksum mismatch for %s: "
                                                   "was %s, should be %s" %
                                                   (name, sha1, csum))
                        xenrt.TEC().logverbose("SHA1 %s OK" % (sha1))
                finally:
                    self.client.xmlrpcDirRights(rtmp, patient=True)
                    self.client.xmlrpcDelTree(rtmp, patient=True)

                success = success + 1
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" %
                                (success, self.loops))

    def parseChecksums(self, data):
        reply = []
        xmld = xml.dom.minidom.parseString(data)
        for a in xmld.childNodes:
            if a.nodeType == a.ELEMENT_NODE and \
                   a.localName == "value":
                for b in a.childNodes:
                    if b.nodeType == b.ELEMENT_NODE and \
                           b.localName == "struct":
                        for c in b.childNodes:
                            if c.nodeType == c.ELEMENT_NODE and \
                                   c.localName == "member":
                                
                                name, value = \
                                      self.parseMemberStruct(c)
                                if not name or not value:
                                    raise xenrt.XRTError("Error parsing "
                                    "checksum.xml")
                                reply.append((name, value))
        return reply
                                                         
    def parseMemberStruct(self, xmld):
        name = None
        value = None
        for a in xmld.childNodes:
            if a.nodeType == a.ELEMENT_NODE and a.localName == "name":
                for b in a.childNodes:
                    if b.nodeType == b.TEXT_NODE and b.data:
                        name = string.strip(str(b.data))
            if a.nodeType == a.ELEMENT_NODE and a.localName == "value":
                for b in a.childNodes:
                    if b.nodeType == b.TEXT_NODE and b.data:
                        value = string.strip(str(b.data))
        return name, value

