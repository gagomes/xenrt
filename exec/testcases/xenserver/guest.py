#
# XenRT: Test harness for Xen and the XenServer product family
#
# Test basic guest operations
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy, xml.dom.minidom
import os, os.path
import xenrt, xenrt.lib.xenserver
import testcases.benchmarks.workloads

class TCXGTInstall(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCXGTInstall")
        self.blocker = True
        self.guest = None

    def run(self, arglist=None):

        if arglist and len(arglist) > 0:
            machine = arglist[0]
        else:
            raise xenrt.XRTError("No machine specified for installation")
        if len(arglist) < 2:
            raise xenrt.XRTError("No guest name specified")
        guestname = arglist[1]

        # Optional arguments
        distro = "rhel41"
        vcpus = None
        memory = None
        sr = None

        for arg in arglist[2:]:
            l = string.split(arg, "=", 1)
            if l[0] == "distro":
                distro = l[1]
            elif l[0] == "version":
                distro = l[1]
            elif l[0] == "vcpus":
                vcpus = int(l[1])
            elif l[0] == "memory":
                memory = int(l[1])
            elif l[0] == "sr":
                sr = l[1]
            elif l[0] == "config":
                config = xenrt.util.parseXMLConfigString(l[1])
                if config.has_key("vcpus"):
                    vcpus = config["vcpus"]
                if config.has_key("memory"):
                    memory = config["memory"]
                if config.has_key("distro"):
                    distro = config["distro"]

        try:
            template = xenrt.TEC().lookup(["TEMPLATE_NAMES", distro])
        except:
            raise xenrt.XRTError("No template name configured for %s" %
                                 (distro))

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)

        g = host.guestFactory()(\
            guestname, template,
            password=xenrt.TEC().lookup("ROOT_PASSWORD_XGT"))
        self.guest = g

        if vcpus != None:
            g.setVCPUs(vcpus)
        if memory != None:
            g.setMemory(memory)

        if xenrt.TEC().lookup(["CLIOPTIONS", "NOINSTALL"],
                              False,
                              boolean=True):
            xenrt.TEC().skip("Skipping because of --noinstall option")
        else:
            g.install(host, distro=distro, sr=sr)
            g.check()
        xenrt.TEC().registry.guestPut(guestname, g)
        xenrt.TEC().registry.configPut(guestname, vcpus=vcpus,
                                                  memory=memory,
                                                  distro=distro)

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


class TCRebootLoopNoDrivers(xenrt.TestCase):

    def run(self, args):
        gname = ""
        for arg in args:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
                break

        if len(gname) == 0:
            raise xenrt.XRTFailure("No guest")

        g = self.getGuest(gname)

        for i in range(100):
            g.reboot()

class _TCGuestInstall(xenrt.TestCase):
    
    def __init__(self):
        xenrt.TestCase.__init__(self, self.__class__.__name__)
        self.blocker = True
        self.guest = None

    def run(self, arglist=None):

        if arglist and len(arglist) > 0:
            machine = arglist[0]
        else:
            raise xenrt.XRTError("No machine specified for installation")

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)
        # Optional arguments
        distro = self.defaultDistro(host)
        vcpus = None
        memory = None
        sr = None
        notools = False
        rootdisk = None
        guestname = None
        config = None
        insertTools = False
        preCloneTailor = False
        self.post_shutdown = False
        arch = None
        
        for arg in arglist[1:]:
            l = string.split(arg, "=", 1)
            if l[0] == "distro":
                distro = l[1]
            elif l[0] == "version":
                distro = l[1]
            elif l[0] == "vcpus":
                vcpus = int(l[1])
            elif l[0] == "memory":
                memory = int(l[1])
            elif l[0] == "arch":
                arch = l[1]
            elif l[0] == "guest":
                guestname = l[1]
            elif l[0] == "sr":
                sr = l[1]
            elif l[0] == "disksize":
                if l[1] != "DEFAULT":
                    rootdisk = int(l[1])
            elif l[0] == "notools":
                notools = True
            elif l[0] == "config":
                config = xenrt.util.parseXMLConfigString(l[1])
                if config.has_key("vcpus"):
                    vcpus = config["vcpus"]
                if config.has_key("memory"):
                    memory = config["memory"]
                if config.has_key("distro"):
                    distro = config["distro"]
                if config.has_key("arch"):
                    arch = config["arch"]
                if config.has_key("disksize"):
                    rootdisk = config["disksize"]
            elif l[0] == "inserttools":
                insertTools = True
            elif l[0] == "preCloneTailor":
                preCloneTailor = True
            elif l[0] == "shutdown":
                self.post_shutdown = True
        if not guestname:
            if not config:
                raise xenrt.XRTError("Must specify at least one of guest name and config string.")
            else:
                guestname = xenrt.util.randomGuestName()
        
        if not arch:
            (distro, arch) = xenrt.getDistroAndArch(distro)

        disks = []
        if rootdisk:
            disks.append(("0", rootdisk/xenrt.KILO, False)) # createVM takes gigabytes

        g = xenrt.lib.xenserver.guest.createVM(host,
                            guestname,
                            distro,
                            arch=arch,
                            memory=memory,
                            sr=sr,
                            vcpus=vcpus,
                            disks=disks,
                            vifs=xenrt.lib.xenserver.Guest.DEFAULT)



        self.guest = g

        self.getLogsFrom(g)

        if insertTools:
            # Insert the tools ISO again so we can test with a CD present
            g.changeCD("xs-tools.iso")

        if preCloneTailor:
            g.preCloneTailor()

    
    def postRun(self):
        r = self.getResult(code=True)
        if r == xenrt.RESULT_FAIL or r == xenrt.RESULT_ERROR:
            # Make sure the guest isn't running anymore
            if self.guest:
                self.tec.logverbose("Making sure %s is shut down" %
                                    (self.guest.name))
                try:
                    self.guest.shutdown(force=True)
                    self.post_shutdown = False
                except:
                    pass
        if self.post_shutdown:
            self.guest.shutdown()

    def defaultDistro(self, host):
        raise xenrt.XRTError("Unimplemented")

class TCXenServerVendorInstall(_TCGuestInstall):
    def defaultDistro(self, host):
        return "rhel41"

class TCXenServerWindowsInstall(_TCGuestInstall):
    def defaultDistro(self, host):
        return "w2k3eer2"

class TCXenServerDebianInstall(_TCGuestInstall):
    def defaultDistro(self, host):
        return "debian60" if isinstance(host, xenrt.lib.xenserver.TampaHost) else "etch"


class TCInPlaceP2V(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCInPlaceP2V")
        self.blocker = True
        self.guest = None

    def run(self, arglist=None):

        # Mandatory args
        if arglist and len(arglist) > 0:
            gname = arglist[0]
        else:
            raise xenrt.XRTError("No guest name specified")

        distro = "rhel41"
        arch = "x86-32"

        for arg in arglist[1:]:
            l = string.split(arg, "=", 1)
            if l[0] == "distro":
                distro = l[1]
            elif l[0] == "version":
                distro = l[1]

        repository = xenrt.getLinuxRepo( distro, arch, "NFS")
        
        guest = self.getGuest(gname)
        self.guest = guest
        self.getLogsFrom(guest.host)
        if guest.getState() == "UP":
            guest.execguest("/sbin/poweroff")
            guest.poll("DOWN")

        # Insert the PV tools CD
        cli = guest.getCLIInstance()
        isoname = xenrt.TEC().lookup("PVTOOLS_ISO_NAME", "pvtools-linux.iso")
        guest.changeCD(isoname)
        guest.start()
        guest.execguest("mkdir -p /mnt/cdrom")
        guest.execguest("if [ ! -e /dev/cdrom ]; then "
                        "  ln -s /dev/hdd /dev/cdrom; "
                        "fi")
        guest.execguest("mount -r -t iso9660 /dev/cdrom /mnt/cdrom")
        guest.execguest("cp -r /mnt/cdrom/xen-setup /tmp")
        guest.execguest("umount /mnt/cdrom")

        # Mount the vendor files
        guest.execguest("mount -t nfs %s /mnt/cdrom" % (repository))

        # Run the P2V tool
        guest.execguest("yes | "
                        "TERM=xterm /tmp/xen-setup/xen-setup -m /mnt/cdrom")

        # Cleanup and restart
        guest.execguest("umount /mnt/cdrom")
        guest.execguest("/sbin/poweroff")
        guest.poll("DOWN")
        guest.enlightenedDrivers = True
        guest.vifstem = "eth"
        vifs = []
        for v in guest.vifs:
            eth, bridge, mac, ip = v
            eth = string.replace(eth, "nic", "eth")
            vifs.append((eth, bridge, mac, ip))
        guest.vifs = vifs
        guest.start()

        # Make sure we are running the correct PV kernel
        kernel = string.strip(guest.execguest("uname -r"))
        if not re.search(r"xen", kernel):
            raise xenrt.XRTFailure("Guest was not running a Xen kernel after "
                                   "P2V")
        guest.check()

    def postRun(self):
        # Unmount anything left
        if self.guest:
            try:
                self.guest.execguest("umount /mnt/cdrom")
            except:
                pass
            


class TCStartStopMulti(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCStartStopMulti")
        self.blocker = True

    def run(self, arglist=None):

        loops = 50

        # Mandatory args
        if arglist and len(arglist) > 0:
            loops = int(arglist[0])
        else:
            raise xenrt.XRTError("No loop count specified")
        guestlist = []
        hosts = {}
        for gname in arglist[1:]:
            l = string.split(gname, "=")
            if len(l) == 1:
                guest = self.getGuest(gname)
                if not guest:
                    raise xenrt.XRTError("Guest %s not found in registry" %
                                         (gname))
                guestlist.append(guest)
                host = guest.host
                if not hosts.has_key(host):
                    hosts[host] = True                
                    self.getLogsFrom(host)
            else:
                # host=guest-regexp format
                h = xenrt.TEC().registry.hostGet(l[0])
                if not h:
                    raise xenrt.XRTError("Host %s not found in registry" %
                                         (l[0]))
                gs = h.listGuests()
                xenrt.TEC().logverbose("Regexp %s for host %s" % (l[1], l[0]))
                for gname in gs:
                    if re.search(l[1], gname):
                        xenrt.TEC().logverbose("Matched %s" % (gname))
                        guest = self.getGuest(gname)
                        if not guest:
                            raise xenrt.XRTError("Guest %s not found in "
                                                 "registry" % (gname))
                        guestlist.append(guest)
                        if not hosts.has_key(h):
                            hosts[h] = True                
                            self.getLogsFrom(h)
                    else:
                        xenrt.TEC().logverbose("Didn't match %s" % (gname))

        # Make sure the guests are down
        for g in guestlist:
            if g.getState() == "UP":
                xenrt.TEC().comment("Shutting down guest %s before commencing "
                                    "loop" % (g.name))
                g.shutdown()

        # Test start/shutdown in a loop
        success = 0
        fail = 0
        try:
            for i in range(loops):
                xenrt.TEC().logverbose("Starting loop iteration %u..." % (i))
                for host in hosts.keys():
                    host.listDomains()
                c = copy.copy(guestlist)
                xenrt.lib.xenserver.startMulti(guestlist)
                for g in c:
                    if not g in guestlist:
                        fail = fail + 1
                for host in hosts.keys():
                    host.checkHealth()
                    host.listDomains()
                c = copy.copy(guestlist)
                xenrt.lib.xenserver.shutdownMulti(guestlist)
                for g in c:
                    if not g in guestlist:
                        fail = fail + 1
                for host in hosts.keys():
                    host.checkHealth()
                if guestlist == []:
                    break
                success = success + 1
        finally:
            self.tec.comment("%u/%u iterations successful" % (success, loops))
        if fail > 0:
            raise xenrt.XRTFailure("%d guests failed." % (fail))

class TCRebootMulti(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCRebootMulti")
        self.blocker = True

    def run(self, arglist=None):

        loops = 50

        # Mandatory args
        if arglist and len(arglist) > 0:
            loops = int(arglist[0])
        else:
            raise xenrt.XRTError("No loop count specified")
        guestlist = []
        hosts = {}
        for gname in arglist[1:]:
            l = string.split(gname, "=")
            if len(l) == 1:
                guest = self.getGuest(gname)
                if not guest:
                    raise xenrt.XRTError("Guest %s not found in registry" %
                                         (gname))
                guestlist.append(guest)
                host = guest.host
                if not hosts.has_key(host):
                    hosts[host] = True                
                    self.getLogsFrom(host)
            else:
                # host=guest-regexp format
                h = xenrt.TEC().registry.hostGet(l[0])
                if not h:
                    raise xenrt.XRTError("Host %s not found in registry" %
                                         (l[0]))
                gs = h.listGuests()
                xenrt.TEC().logverbose("Regexp %s for host %s" % (l[1], l[0]))
                for gname in gs:
                    if re.search(l[1], gname):
                        xenrt.TEC().logverbose("Matched %s" % (gname))
                        guest = self.getGuest(gname)
                        if not guest:
                            raise xenrt.XRTError("Guest %s not found in "
                                                 "registry" % (gname))
                        guestlist.append(guest)
                        if not hosts.has_key(h):
                            hosts[h] = True                
                            self.getLogsFrom(h)
                    else:
                        xenrt.TEC().logverbose("Didn't match %s" % (gname))


        # Make sure the guests are up
        for g in guestlist:
            if g.getState() == "DOWN":
                xenrt.TEC().comment("Starting guest %s before commencing "
                                    "loop" % (g.name))
                g.start()

        # Test reboot in a loop
        success = 0
        try:
            for i in range(loops):
                xenrt.TEC().logverbose("Starting loop iteration %u..." % (i))
                for host in hosts.keys():
                    host.listDomains()
                xenrt.lib.xenserver.startMulti(guestlist, reboot=True)
                for host in hosts.keys():
                    host.checkHealth()
                success = success + 1
        finally:
            self.tec.comment("%u/%u iterations successful" % (success, loops))

class TCUnsupported(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCUnsupported")

    def attempt(self, template, vcpus, memory):
        name = "shouldfail"
        try:
            args = []
            args.append("create-vifs=false")
            args.append("name=\"%s\"" % (name))
            args.append("memory_set=%u" % (memory))
            args.append("vcpus=%u" % (vcpus))
            args.append("template-name=\"%s\"" % (template))
            args.append("auto_poweron=false")
            xenrt.TEC().progress("Attempting install of guest VM %s using %s" %
                                 (name, template))
            output = self.cli.execute("vm-install", string.join(args),
                                      ignoreerrors=True)
            r = re.search("Command failed:", output)
            if not r:
                raise xenrt.XRTFailure("Installation of '%s' vcpus=%u "
                                       "memory=%u did not fail" %
                                       (template, vcpus, memory))
            r = re.search("New VM uuid: (\S+)", output)
            if r:
                uuid = r.group(1)
                output = self.cli.execute("host-vm-list")
                if re.search("uuid: %s" % (uuid), output):
                    raise xenrt.XRTFailure("Installation of '%s' vcpus=%u "
                                           "memory=%u failed but left "
                                           "a guest behind" %
                                           (template, vcpus, memory))
        finally:
            try:
                self.cli.execute("vm-uninstall", "vm-name=\"%s\"" % (name))
            except:
                pass

    def run(self, arglist=None):
        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)
        self.cli = host.getCLIInstance()

        unsupported = string.split(host.lookup("UNSUPPORTED_GUESTS", ""))
        if len(unsupported) == 0:
            xenrt.TEC().skip("No unsupported guest configurations")
            return

        if "Windows2000/SMP" in unsupported:
            self.runSubcase("attempt",
                            (host.getTemplate("w2kassp4"),
                             2,
                             512),
                            "Windows2000", "SMP")

class TCCorruptExportImage(xenrt.TestCase):
    """Importing a corrupt export image using the CLI should give an error"""

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCCorruptExportImage")
        self.guest = None

    def run(self, arglist=None):

        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]
        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Could not find machine '%s'" % (machine))

        # Install a guest to export
        self.getLogsFrom(host)

        # Create a basic guest
        self.guest = host.createGenericLinuxGuest()
        gname = self.guest.getName()

        if self.guest.getState() == "UP":
            xenrt.TEC().comment("Shutting down guest %s before commencing "
                                "test." % (gname))
            self.guest.shutdown()

        tmp = xenrt.resources.TempDirectory()
        image = "%s/%s" % (tmp.path(), gname)

        self.guest.exportVM(image)

        # Flip a bit.
        byte = 150000000
        xenrt.TEC().logverbose("Flipping a bit in byte %s of image." % (byte))
        xenrt.command("ls -l %s" % (image))
        xenrt.command("sha1sum %s" % (image))
        xenrt.command("%s/progs/flipbit %s %s" % 
                      (xenrt.TEC().lookup("LOCAL_SCRIPTDIR"),
                       byte, image))
        xenrt.command("ls -l %s" % (image))
        xenrt.command("sha1sum %s" % (image))
        fail = False
        try:
            self.guest.importVM(host, image)
        except Exception, e:
            if re.search(r"checksum failed", e.data):
                fail = True
            else:
                raise xenrt.XRTFailure("Import failed but didn't mention "
                                       "checksum failure (%s)" % (e.data))

        if not fail:
            raise xenrt.XRTFailure("Import of corrupt image suceeded.")

    def postRun(self):
        if self.guest:
            try:
                self.guest.shutdown(force=True)
            except:
                pass
            try:
                self.guest.poll("DOWN", 120, level=xenrt.RC_ERROR)
                self.guest.uninstall()
            except:
                pass
        

class TCImportExport(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCImportExport")
        self.blocker = True
        self.vdi = None
        self.vbd = None
        self.tmpdev = None
        self.vg = None
        self.tmpmnt = None
        self.host = None
        self.cliguest = None
        self.image = None
        self.cliguesttidy = []

    def makeDom0Scratch(self, host):
        # Make a VDI for import/export
        try:
            cli = host.getCLIInstance()
            dom0 = host.getMyDomain0UUID()
            srl = host.getSRs(type="ext")
            lvm = False
            if len(srl) == 0:
                srl = host.getSRs("lvm")
                if len(srl) > 0:
                    lvm = True
            if len(srl) == 0:
                raise xenrt.XRTError("Could not find suitable SR for temp "
                                     "storage")
            sr = srl[0]
            if lvm:
                # Provision with LVM tools
                vg = string.strip(\
                    host.execRawStorageCommand(sr, "vgs --noheadings -o size,name,size "
                                  "--separator=, | cut -d, -f2"))
                host.execRawStorageCommand(sr, "lvcreate -n importexport -L 20G %s" % (vg))
                self.vg = vg
                dev = "%s/importexport" % (vg)
            else:
                # Provision via official channels
                vdi = string.strip(cli.execute("vdi-create",
                                               "name-label=importexport "
                                               "type=user sr-uuid=%s "
                                               "virtual-size=20000000000" %
                                               (sr),
                                               compat=False))
                self.vdi = vdi
                vbd = string.strip(cli.execute("vbd-create",
                                               "vdi-uuid=%s vm-uuid=%s "
                                               "device=autodetect" %
                                               (vdi, dom0),
                                               compat=False))
                self.vbd = vbd
                cli.execute("vbd-plug", "uuid=%s" % (vbd), compat=False)
                dev = string.strip(cli.execute("vbd-param-get",
                                               "uuid=%s param-name=device" %
                                               (vbd),
                                               compat=False))

            host.execdom0("mke2fs /dev/%s" % (dev), level=xenrt.RC_ERROR)
            self.tmpmnt = host.hostTempDir()
            host.execdom0("mount /dev/%s /%s" % (dev, self.tmpmnt),
                          level=xenrt.RC_ERROR)
            self.tmpdev = dev
        except xenrt.XRTFailure, e:
            # Anything that breaks here is not a failure of the testcase
            raise xenrt.XRTError(e.reason)

    def run(self, arglist=None):

        discard = False
        loops = 10
        dom0 = False
        checkpreserve = False
        useExtraVDIs = False
        gname = None

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("No guest name given.")

        g = self.getGuest(gname)
        if not g:
            raise xenrt.XRTError("Cannot find guest named %s" % (gname))

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "dom0":
                dom0 = True
            elif l[0] == "loops":
                loops = int(l[1])
            elif l[0] == "checkpreserve":
                checkpreserve = True
            elif l[0] == "discard":
                discard = True
            elif l[0] == "client":
                self.cliguest = self.getGuest(l[1])
                if not self.cliguest:
                    raise xenrt.XRTError("Could not find guest %s" % (l[1]))
            elif l[0] == "extravdis":
                useExtraVDIs = True

        # If we're exporting to another guest then make sure it has the
        # CLI installed
        if self.cliguest:
            if self.cliguest.getState() != "UP":
                self.cliguest.start()
            if self.cliguest.windows:
                self.cliguest.installCarbonWindowsCLI()
            else:
                self.cliguest.installCarbonLinuxCLI()

        if g.getState() == "UP":
            xenrt.TEC().comment("Shutting down guest %s before commencing "
                                "loop." % (g.name))
            g.shutdown()

        host = g.host
        cli = host.getCLIInstance()
        self.host = host
        self.getLogsFrom(host)

        if useExtraVDIs:
            # Add four 2GB disks with known patterns to the guest
            # create VDIs           
            extravdis = []
            for i in range(4):
                args = []
                args.append("sr-uuid=%s" % (g.chooseSR()))
                args.append("name-label=\"XenRT TCImportExport "
                            "Extra VDI %d\"" % (i))
                args.append("type=\"user\"")
                args.append("virtual-size=%d" % (2 * xenrt.GIGA))
                extravdis.append(cli.execute("vdi-create",string.join(args),
                                             strip=True))

            # Plug them into dom0 and note down the device
            dom0vbds = []
            dom0devs = []
            for i in range(4):
                args = []
                args.append("vm-uuid=%s" % (host.getMyDomain0UUID()))
                args.append("device=autodetect")
                args.append("vdi-uuid=%s" % (extravdis[i]))
                dom0vbds.append(cli.execute("vbd-create",string.join(args),
                                            strip=True))
                cli.execute("vbd-plug","uuid=%s" % (dom0vbds[i]))
                dom0devs.append(host.genParamGet("vbd",dom0vbds[i],"device"))

            # Put patterns onto the disks using scripts/remote/patterns.py
            for i in range(4):
                host.execdom0("%s/remote/patterns.py /dev/%s %d write %d" % 
                              (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"),
                              dom0devs[i],2 * xenrt.GIGA,i))

            # Unplug then destroy the VBDs for dom0
            for vbd in dom0vbds:
                cli.execute("vbd-unplug","uuid=%s" % (vbd))
                cli.execute("vbd-destroy","uuid=%s" % (vbd))

            # Decide on devices to use
            existingdevices = g.listDiskDevices()
            existingdevicesints = []
            for dev in existingdevices:
                existingdevicesints.append(int(dev))
            startdev = max(existingdevicesints) + 1
    

            # Create VBDs
            guestvbds = []
            for i in range(4):
                args = []
                args.append("vm-uuid=%s" % (g.getUUID()))
                args.append("device=%d" % (startdev + i))
                args.append("vdi-uuid=%s" % (extravdis[i]))
                guestvbds.append(cli.execute("vbd-create",string.join(args),
                                             strip=True))
                
        success = 0
        if dom0:
            self.makeDom0Scratch(host)
        else:
            if xenrt.TEC().registry.read("/xenrt/cli/windows"):
                self.cliguest = xenrt.TEC().registry.read("/xenrt/cli/windows_guest")            
                image = "c:\\\\%s" % (gname)
            else:
                tmp = xenrt.resources.TempDirectory()
                image = "%s/%s" % (tmp.path(), gname)
                self.image = image
        # Get our current SR - this is where we'll install back to
        myvbds = host.minimalList("vbd-list",
                                  "vdi-uuid",
                                  "vm-uuid=%s type=Disk" % g.getUUID())
        sruuid = cli.execute("vdi-param-get",
                             "uuid=%s param-name=sr-uuid" % (myvbds[0]),
                             strip=True)
        try:
            for i in range(loops):
                xenrt.TEC().logverbose("Starting loop iteration %u..." % (i))
                host.listDomains()
                if dom0:
                    if checkpreserve:
                        # Store macs
                        vifs = g.getVIFs()
                    filename = "%s/%s.xenrtimpexp" % (self.tmpmnt, g.getUUID())
                    host.execdom0("xe vm-export uuid=%s filename=%s" %
                                  (g.getUUID(), filename),
                                  timeout=1800)
                elif self.cliguest:
                    if self.cliguest.windows:
                        g.exportVM(image)
                    else:
                        filename = "/export-%s.img" % (g.getUUID())
                        self.cliguesttidy.append(filename)
                        args = "uuid=%s filename=%s" % (g.getUUID(), filename)
                        c = xenrt.lib.xenserver.buildCommandLine(host,
                                                                 "vm-export",
                                                                 args)
                        self.cliguest.execcmd("xe %s" % (c), timeout=3600)
                else:
                    g.exportVM(image)
                host.listDomains()
                if discard:
                    xenrt.TEC().logverbose("Discarding exported image.")
                    if self.cliguest:
                        if self.cliguest.windows:
                            self.cliguest.xmlrpcExec("del /F %s" %
                                                     (string.replace(image,
                                                                     "\\\\",
                                                                     "\\")))
                        else:
                            self.cliguest.execcmd("rm -f %s" % (filename))
                            self.cliguesttidy.remove(filename)
                    else:
                        host.execdom0("rm -f %s" % (image))
                    continue
                g.uninstall()
                host.listDomains()
                if dom0:
                    newuuid = string.strip(host.execdom0(\
                        "xe vm-import filename=%s sr-uuid=%s preserve=true" %
                        (filename, sruuid), timeout=1800))
                    g.uuid = newuuid
                    host.addGuest(g)
                elif self.cliguest:
                    if self.cliguest.windows:
                        g.importVM(host, image)
                    else:
                        args = "sr-uuid=%s filename=%s preserve=true" % \
                               (sruuid, filename)
                        c = xenrt.lib.xenserver.buildCommandLine(host,
                                                                 "vm-import",
                                                                 args)
                        newuuid = string.strip(self.cliguest.execcmd(\
                            "xe %s" % (c), timeout=3600))
                        g.uuid = newuuid
                        host.addGuest(g)
                        self.cliguest.execcmd("rm -f %s" % (filename))
                        self.cliguesttidy.remove(filename)
                else:
                    g.importVM(host, image)
                host.listDomains()
                if useExtraVDIs:
                    # Find the new VBDs, delete them
                    newvdis = []
                    for i in range(4):
                        newvdis.append(g.getDiskVDIUUID(startdev+i))
                        vbd = g.getDiskVBDUUID(startdev+i)
                        cli.execute("vbd-destroy","uuid=%s" % (vbd))
                    
                    # Create VBDs for dom0 on the new VDIs, and plug them
                    dom0vbds = []
                    dom0devs = []
                    for i in range(4):
                        args = []
                        args.append("vm-uuid=%s" % (host.getMyDomain0UUID()))
                        args.append("device=autodetect")
                        args.append("vdi-uuid=%s" % (extravdis[i]))
                        dom0vbds.append(cli.execute("vbd-create",
                                                  string.join(args),strip=True))
                        cli.execute("vbd-plug","uuid=%s" % (dom0vbds[i]))
                        dom0devs.append(host.genParamGet("vbd",dom0vbds[i],
                                                         "device"))

                    # Verify that the patterns are still there and correct
                    for i in range(4):
                        rc = host.execdom0("%s/remote/patterns.py /dev/%s %d read "
                                           "%d" % 
                                        (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"),
                                   dom0devs[i],2*xenrt.GIGA,i),retval="code")
                        if rc > 0:
                            raise xenrt.XRTFailure("Extra VDI patterns do not "
                                                   "match!")

                    # Cleanup
                    for vbd in dom0vbds:
                        cli.execute("vbd-unplug","uuid=%s" % (vbd))
                        cli.execute("vbd-destroy","uuid=%s" % (vbd))
                    for vdi in newvdis:
                        cli.execute("vdi-destroy","uuid=%s" % (vdi))

                g.start()
                if dom0:
                    if checkpreserve:
                        # Check the mac addresses are correct
                        newvifs = g.getVIFs()
                        for vif in vifs:
                            mac = vifs[vif][0]
                            if mac != newvifs[vif][0]:
                                raise xenrt.XRTFailure(
                                 "MAC address not preserved of imported "
                                 "preserve=true guest")
                        
                host.listDomains()
                g.shutdown()
                host.listDomains()
                host.checkHealth()
                success = success + 1
        finally:
            self.tec.comment("%u/%u iterations successful" % (success, loops))

    def postRun(self):
        # Clean up the temp space
        if self.image:
            try:
                os.unlink(self.image)
            except:
                pass
        if self.host:
            cli = self.host.getCLIInstance()

        # get sr uuid for cleanup.
        sr = None
        if self.vdi and self.vg:
            sr = self.host.genParamGet("vdi", self.vdi, "sr-uuid")

        try:
            if self.tmpmnt:
                self.host.execdom0("umount %s" % (self.tmpmnt))
        except Exception, e:
            toraise = e
        try:
            if self.vbd:
                cli.execute("vbd-unplug",
                            "uuid=%s" % (self.vbd),
                            compat=False)
        except Exception, e:
            toraise = e
        try:
            if self.vbd:
                cli.execute("vbd-destroy",
                            "uuid=%s" % (self.vbd),
                            compat=False)
        except Exception, e:
            toraise = e
        try:
            if self.vdi:
                cli.execute("vdi-destroy",
                            "uuid=%s" % (self.vdi),
                            compat=False)
        except Exception, e:
            toraise = e
            
        # Clean up mounts and LVs
        try:
            if self.vg:
                self.host.execRawStorageCommand(sr, "lvremove --force "
                                   "/dev/%s/importexport" % (self.vg))
        except Exception, e:
            toraise = e

        if toraise != None:
            raise toraise

        for f in self.cliguesttidy:
            if not self.cliguest.windows:
                self.cliguest.execcmd("rm -f %s" % (f))

class TCMakeTemplate(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCMakeTemplate")
        self.template = None
        self.newguest = None

    def run(self, arglist):
        guestname = None

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                guestname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not guestname:
            raise xenrt.XRTError("No guest specified.")

        g = self.getGuest(guestname)
        if not g:
            raise xenrt.XRTError("Could not find guest %s in  registry." % (guestname))
        self.getLogsFrom(g.host)
        g.preCloneTailor()
        if g.getState() == "UP":
            xenrt.TEC().comment("Shutting down guest %s before commencing "
                                "clone." % (g.name))
            g.shutdown()

        # Create template.
        self.template = g.cloneVM(xenrt.randomGuestName())
        self.template.paramSet("is-a-template", "true")

        name = xenrt.randomGuestName()
        self.newguest = g.host.guestFactory()(name,
                                              self.template.name)
        self.template.populateSubclass(self.newguest)
        self.newguest.name = name

        # Install a new guest.
        cli = self.template.getCLIInstance()
        args = []
        args.append("new-name-label=%s" % (self.newguest.name))
        args.append("sr-uuid=%s" % self.template.host.getLocalSR())
        args.append("template-name=%s" % (self.template.name))
        self.newguest.uuid = cli.execute("vm-install", 
                                          string.join(args), 
                                          timeout=3600).strip()

        # A new MAC will have been assigned.
        self.newguest.vifs = []
        for vif in self.newguest.getVIFs().keys():
            mac, ip, bridge = self.newguest.getVIF(vif)
            self.newguest.vifs.append((vif, bridge, mac, ip))
        self.newguest.start()
        self.newguest.check()

    def postRun(self):
        try:
            devices = self.template.host.minimalList("vbd-list",
                                                      params="userdevice",
                                                      args="type=Disk vm-uuid=%s" %
                                                     (self.template.getUUID()))
            for d in devices:
                try:
                    self.template.removeDisk(d)
                except:
                    pass
            self.template.lifecycleOperation("vm-destroy", force=True)
        except:
            pass
        try:
            self.newguest.shutdown()
        except:
            pass
        try:
            self.newguest.uninstall()
        except:
            pass

class TCDiskPattern(xenrt.TestCase):
    """Write or check a deterministic pattern to a named VDI"""
    def run(self, arglist=None):
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                guest = self.getGuest(l[1])
            if l[0] == "parameter":
                parameter = l[1]
            if l[0] == "vdiindex":
                uuid = guest.getAttachedVDIs()[int(l[1])]

        size = long(guest.host.genParamGet("vdi", uuid, "virtual-size"))
        cmd = "%s/remote/patterns.py /dev/$\{DEVICE\} %d %s" % (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), size, parameter)

        f = "/tmp/" + xenrt.randomGuestName()
        guest.host.execdom0('echo "%s" > %s' % (cmd, f))
        guest.host.execdom0('chmod +x %s' % f)
        guest.host.execdom0("/opt/xensource/debug/with-vdi %s %s || true" % (uuid, f))
        guest.host.execdom0("/opt/xensource/debug/with-vdi %s %s" % (uuid, f))

class TCClone(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCClone")
        self.blocker = True
        self.guestsToClean = []

    def run(self, arglist=None):

        clones = 1 
        remove = True
        gname = None
        newname = None
        distro = None
        chain = False
        leaveup = False
        suspended = False
        noPreCloneTailor = False
        host = None

        for arg in arglist[0:]:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "newname":
                newname = l[1]
            elif l[0] == "clones":
                clones = int(l[1])
            elif l[0] == "keep":
                remove = False  
            elif l[0] == "distro":
                distro = l[1]
            elif l[0] == "chain":
                chain = True       
            elif l[0] == "leaveup":
                leaveup = True       
            elif l[0] == "suspended":
                suspended = True
            elif l[0] == "host":
                host = xenrt.TEC().registry.hostGet(l[1])
            elif l[0] == "noPreCloneTailor":
                noPreCloneTailor = True
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
 
        if not gname:
            raise xenrt.XRTError("No guest name specified.")
        
        g = self.getGuest(gname)
        if not g:
            raise xenrt.XRTError("Could not find guest %s in registry" %
                                (gname))
        self.getLogsFrom(g.host)
        
        # Some guests need to be prepared before we clone
        if distro:
            g.distro = distro
        
        if not noPreCloneTailor:
            if g.getState() != "UP":
                xenrt.TEC().logverbose("Starting guest %s before commencing "
                                       "pre-clone tailor." % (g.name))
                g.start()
            g.preCloneTailor()

        if suspended:
            xenrt.TEC().comment("Suspending guest %s before commencing "
                                "clone" % (g.name))
            g.suspend()
        elif g.getState() == "UP":
            xenrt.TEC().comment("Shutting down guest %s before commencing "
                                "clone." % (g.name))
            g.shutdown()

        if suspended:
            cli = g.host.getCLIInstance()
            pooluuid = cli.execute("pool-list", 
                                   "master=%s --minimal" %
                                   (g.host.getMyHostUUID())).strip()
            cli.execute("pool-param-set", "uuid=%s other-config-allow_clone_suspended_vm=true" %
                        (pooluuid))

        # See if all VDIs are VHD
        disks = g.listDiskDevices()
        allvhd = True
        for disk in disks:
            vdi = g.getDiskVDIUUID(disk)
            sr = g.host.getVDISR(vdi)
            # Find the sr type
            srtype = g.host.genParamGet("sr",sr,"type")
            if srtype != "nfs" and srtype != "file":
                allvhd = False
                break

        count = 0
        ct = xenrt.util.Timer()
        try:
            previous = g
            for i in range(clones):
                if newname:
                    if clones == 1:
                        c = previous.cloneVM(newname,timer=ct)
                    else:
                        c = previous.cloneVM("%s%u" % (newname, i),timer=ct)
                else:
                    c = previous.cloneVM(timer=ct)
                
                if host:
                    c.setHost(host)
                if remove:
                    self.guestsToClean.append(c)
                if allvhd:
                    # See how long it took
                    timetaken = ct.measurements[-1]
                    if timetaken > (len(c.listDiskDevices()) * 60):
                        xenrt.TEC().warning("Clone of VM with entirely VHD "
                                            "disks took longer than expected")
                if suspended:
                    c.lifecycleOperation("vm-resume")
                    c.poll("UP")
                    c.reboot()
                else:
                    c.start()
                c.check()
                if not leaveup:
                    c.shutdown()
                if chain:
                    previous = c
                if not remove:
                    xenrt.TEC().registry.guestPut(c.getName(), c)
                count = count + 1
        finally:
            xenrt.TEC().comment("%u of %u iterations successful" %
                                (count, clones))

            if ct.count() > 0:
                xenrt.TEC().logverbose("Clone times: %s" % (ct.measurements))
                xenrt.TEC().value("CLONE_MAX", ct.max())
                xenrt.TEC().value("CLONE_MIN", ct.min())
                xenrt.TEC().value("CLONE_AVG", ct.mean())
                xenrt.TEC().value("CLONE_DEV", ct.stddev())

        if not noPreCloneTailor:
            if g.getState() == "SUSPENDED":
                g.resume()
            else:
                g.start()
            g.check()
            g.shutdown()

    def postRun(self):
        for g in self.guestsToClean:
            try:
                try:
                    g.shutdown(force=True)
                except:
                    pass
                g.poll("DOWN", 120, level=xenrt.RC_ERROR)
                g.uninstall()
            except:
                pass

class TCMoveToSR(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCMoveToSR")
        self.blocker = True

    def run(self, arglist=None):

        gname = None
        distro = None
        srtypes = None

        for arg in arglist[0:]:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "types":
                srtypes = string.split(l[1], ",")
            elif l[0] == "distro":
                distro = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]

        if not gname:
            raise xenrt.XRTError("No guest name specified.")

        g = self.getGuest(gname)
        if not g:
            raise xenrt.XRTError("Could not find guest %s in registry" %
                                (gname))
        self.getLogsFrom(g.host)

        # Look up the SR
        sruuids = []
        for srtype in srtypes:
            sruuids.extend(g.host.getSRs(srtype))
        if len(sruuids) == 0:
            raise xenrt.XRTError("No SRs found for '%s'" %
                                 (string.join(srtypes, ",")))
        newsruuid = sruuids[0]
        xenrt.TEC().comment("Using SR %s from choice of %s" %
                            (newsruuid, string.join(srtypes, ",")))

        # Some guests need to be prepared before we clone
        if distro:
            g.distro = distro
        if g.getState() != "UP":
            xenrt.TEC().logverbose("Starting guest %s before commencing "
                                   "pre-clone tailor." % (g.name))
            g.start()
        g.preCloneTailor()

        if g.getState() == "UP":
            xenrt.TEC().comment("Shutting down guest %s before commencing "
                                "clone." % (g.name))
            g.shutdown()

        # Copy the VM and uninstall the original
        newg = g.copyVM(sruuid=newsruuid)
        name = g.getName()
        g.uninstall()
        newg.paramSet("name-label", name)
        newg.name = name
        xenrt.TEC().registry.guestPut(newg.getName(), newg)

class TCMixops(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCMixops")
        self.guest = None
        self.guestclean = None
        self.hotplugvbd = True
        self.hotunplugvbd = True
        self.hotplugvif = True
        self.hotunplugvif = True
        self.allowedVBDs = []
        self.removeableVBDs = []
        self.sruuid = None
        self.basemem = None
        self.basevcpus = None
        self.sizebytes = 1000000000
        self.allowedVIFs = []
        self.removeableVIFs = []
        self.bridge = None
        self.ops = [ "startVM",
                     "stopVM",
                     "rebootVM",
                     "suspendResumeVM",
                     "migrateVM",
                     "liveMigrateVM",
                     "addVBD",
                     "removeVBD",
                     "addVIF",
                     "removeVIF",
                     "increaseMemory",
                     "resetMemory",
                     "increaseCPUs",
                     "resetCPUs" ]
        self.noclean = False
        self.clonesToClean = []
        self.memcap = None

    def setState(self, state):
        action = {'UP'        :  { 'DOWN'      : 'shutdown',
                                   'SUSPENDED' : 'suspend'},
                  'DOWN'      :  { 'UP'        : 'start',
                                   'SUSPENDED' : 'start'},
                  'SUSPENDED' :  { 'DOWN'      : 'resume',
                                   'UP'        : 'resume'}}
        while not self.guest.getState() == state:
            eval("self.guest.%s()" % 
                (action[self.guest.getState()][state]))
        
    def startVM(self):
        self.setState("DOWN")
        self.guest.start()
        self.guest.check()

    def stopVM(self):
        self.setState("UP")
        self.guest.shutdown()

    def rebootVM(self):
        self.setState("UP")
        self.guest.start(reboot=True)
        self.guest.check()

    def suspendResumeVM(self):
        self.setState("UP")
        self.guest.suspend()
        self.guest.resume()
        self.guest.check()

    def migrateVM(self):
        self.setState("UP")
        guestmem = self.guest.memory
        if self.memcap:
            if self.memcap < 2*guestmem:
                xenrt.TEC().logverbose("Not enough capped free memory to "
                                       "migrate at VM of %uMB" % (guestmem))
                return
        else:
            hostfree = self.guest.host.getFreeMemory()
            if hostfree < 2*guestmem:
                xenrt.TEC().comment("Not enough memory to migrate. (%s < 2*%s)"
                                    % (hostfree, guestmem))
                return
        self.guest.migrateVM(self.guest.host)
        self.guest.check()

    def liveMigrateVM(self):
        self.setState("UP")
        guestmem = self.guest.memory
        if self.memcap:
            if self.memcap < 2*guestmem:
                xenrt.TEC().logverbose("Not enough capped free memory to "
                                       "migrate at VM of %uMB" % (guestmem))
                return
        else:
            hostfree = self.guest.host.getFreeMemory()
            if hostfree < 2*guestmem:
                xenrt.TEC().comment("Not enough memory to migrate. (%s < 2*%s)"
                                    % (hostfree, guestmem))
                return
        self.guest.migrateVM(self.guest.host, live="true")
        self.guest.check()

    def addVBD(self):
        if self.allowedVBDs == []:
            return
        if self.hotplugvbd:
            self.setState("UP")
        else:
            self.setState("DOWN")
        device = self.allowedVBDs.pop()
        self.guest.createDisk(sizebytes=self.sizebytes,
                              sruuid=self.sruuid,
                              userdevice=device)
                              
        self.removeableVBDs.append(device)
        self.setState("UP")
        self.guest.check()

    def removeVBD(self):
        if self.removeableVBDs == []:
            return
        if self.hotunplugvbd:
            self.setState("UP")
        else:
            self.setState("DOWN")
        device = self.removeableVBDs.pop()
        if self.hotunplugvbd:
            self.guest.unplugDisk(device)
        self.guest.removeDisk(device)
        self.allowedVBDs.append(device)
        self.setState("UP")
        self.guest.check()
   
    def addVIF(self):
        if self.allowedVIFs == []:
            return
        if self.hotplugvif:
            self.setState("UP")
        else:
            self.setState("DOWN")
        device = "%s%d" % (self.guest.vifstem, 
                           int(self.allowedVIFs.pop()))
        mac = xenrt.randomMAC()
        self.guest.createVIF(device, 
                             self.bridge,
                             mac)
        self.guest.vifs.append((device, 
                                self.bridge, 
                                mac,
                                None))
        self.removeableVIFs.append(device)
        if self.hotplugvif:
            self.guest.plugVIF(device)
            time.sleep(10)
            self.guest.updateVIFDriver()
        else:
            self.setState("UP")
        self.guest.check()

    def removeVIF(self):
        if self.removeableVIFs == []:
            return
        if self.hotunplugvif:
            self.setState("UP")
        else:
            self.setState("DOWN")
        device = self.removeableVIFs.pop()
        if self.hotunplugvif:
            self.guest.unplugVIF(device)
        self.guest.removeVIF(device)
        self.allowedVIFs.append(device.strip(self.guest.vifstem))
        for v in self.guest.vifs:
            d, b, m, i = v
            if d == device:
                self.guest.vifs.remove(v)
        self.setState("UP")
        self.guest.check()

    def increaseMemory(self):
        self.setState("DOWN")
        if self.memcap:
            # Set to memory to a random value between basemem and the cap
            if self.memcap < self.basemem:
                raise xenrt.XRTError("Memory cao is less than base memory",
                                     "%u < %u" % (self.memcap, self.basemem))
            m = random.randint(self.basemem, self.memcap)
        else:
            free = self.guest.host.getFreeMemory()
            m = self.basemem + free/4
        self.guest.memset(m)
        self.setState("UP")
        self.guest.check()

    def resetMemory(self):
        self.setState("DOWN")
        self.guest.memset(self.basemem)
        self.setState("UP")
        self.guest.check()

    def increaseCPUs(self):
        if self.guest.cpuget() >= 4:
            return
        self.setState("DOWN")
        self.guest.cpuset(self.guest.cpuget() + 1)
        self.setState("UP")
        if self.guest.windows:
            self.setState("DOWN")
            self.setState("UP")
        self.guest.check()

    def resetCPUs(self):
        self.setState("DOWN")
        self.guest.cpuset(self.basevcpus)
        self.setState("UP")
        if self.guest.windows:
            self.setState("DOWN")
            self.setState("UP")
        self.guest.check()

    def run(self, arglist=None):

        duration = 3600
        ops = None  
        gname = None

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "duration":
                duration = int(l[1]) * 60 * 60
            if l[0] == "ops":
                ops = int(l[1])
            if l[0] == "noclean":
                self.noclean = True
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]

        if not gname: 
            raise xenrt.XRTError("No guest name specified.")
        g = self.getGuest(gname)
        self.guest = g
        self.getLogsFrom(g.host)
        g.preCloneTailor()

        if g.distro:
            x = string.split(g.host.lookup("GUEST_NO_HOTPLUG_VBD", ""), ",")
            if g.distro in x:
                self.hotplugvbd = False
            x = string.split(g.host.lookup("GUEST_NO_HOTUNPLUG_VBD", ""), ",")
            if g.distro in x:
                self.hotunplugvbd = False
            x = string.split(g.host.lookup("GUEST_NO_HOTPLUG_VIF", ""), ",")
            if g.distro in x:
                self.hotplugvif = False
            x = string.split(g.host.lookup("GUEST_NO_HOTUNPLUG_VIF", ""), ",")
            if g.distro in x:
                self.hotunplugvif = False
        
        if g.windows:
            # Enable PAE in case we should get above 4GB memory later
            g.forceWindowsPAE()

        # Cap to a fraction of host memory (that's allocatable to VMs) if
        # requested. It is assumed 85% of host memory is allocatable.
        memfraction = xenrt.TEC().lookup("MIXOPS_MEMORY_SHARE", None)
        if memfraction:
            self.memcap = g.host.getTotalMemory()*85/(int(memfraction)*100)
            xenrt.TEC().comment("Capping guest memory use to %uMB" %
                                (self.memcap))

        self.basemem = self.guest.memget()
        self.basevcpus = self.guest.cpuget()
        xenrt.TEC().logverbose("Guest currently has %s vcpu(s) and %sMb memory." %
                              (self.basevcpus, self.basemem)) 

        if g.distro:
            maxvifs = int(g.host.lookup("GUEST_VIFS_%s" % (g.distro), 7))
        else:
            maxvifs = 7
        for vifind in g.host.genParamGet("vm",
                                         g.getUUID(),
                                         "allowed-VIF-devices").split("; "):
            if int(vifind) < maxvifs:
                self.allowedVIFs.append(vifind)
        
        self.allowedVBDs = \
            g.host.genParamGet("vm",
                                g.getUUID(),
                               "allowed-VBD-devices").split("; ") 
        rstr = g.host.genParamGet("vm",
                                   g.getUUID(),
                                  "recommendations")
        
        rxml = xml.dom.minidom.parseString(rstr)
        for i in rxml.childNodes:
            if i.nodeType == i.ELEMENT_NODE:
                if i.localName == "restrictions":
                    xenrt.TEC().logverbose("BOO: %s" % (i.childNodes))
                    for j in i.childNodes:
                        xenrt.TEC().logverbose("MAA: %s" % (j))
                        if j.localName == "restriction":
                            if j.getAttribute("property") == "number-of-vbds":
                                if j.hasAttribute("max"):
                                    maxvbds = int(j.getAttribute("max")) - len(g.listVBDs())
                                    self.allowedVBDs = self.allowedVBDs[0:maxvbds]
                            elif j.getAttribute("property") == "number-of-vifs":
                                if j.hasAttribute("max"):
                                    xenrt.TEC().logverbose("WOO: %s %s %s" % (j.getAttribute("max"), g.getVIFs(), self.allowedVIFs))
                                    maxvifs = int(j.getAttribute("max")) - len(g.getVIFs())
                                    self.allowedVIFs = self.allowedVIFs[0:maxvifs]

        xenrt.TEC().logverbose("Allowed VBDs: %s" % 
                              (self.allowedVBDs))
        # Set the sruuid to match the SR one of the VM's disks is using
        vdi = g.getAttachedVDIs()[0]
        self.sruuid = g.host.genParamGet("vdi", vdi, "sr-uuid")

        xenrt.TEC().logverbose("Allowed VIFs: %s" % 
                              (self.allowedVIFs))
        self.bridge = g.host.getPrimaryBridge()
        
        deadline = xenrt.timenow() + duration
        xenrt.TEC().progress("Running mixed operations until %s." %
            (time.strftime("%H:%M:%S", time.gmtime(deadline))))
        i = 0
        clonei = 0
        while xenrt.timenow() < deadline:
            if ops != None and i > ops:
                break
            if xenrt.GEC().abort:
                xenrt.TEC().warning("Aborting on command")
                break

            # Every 10 operations we clone the guest so we have a stable
            # point to go back to if something breaks. Every 100 operations
            # perform a vm-copy of the original to break the VHD chains.
            if (i % 100) == 0 and i > 0:
                try:
                    xenrt.TEC().logdelimit("Performing vm-copy %u" % (i/100))
                    # Remove any existing clone
                    if self.guestclean:
                        gc, a, b, c, d = self.guestclean
                        try:
                            gc.uninstall()
                        except xenrt.XRTException, e:
                            xenrt.TEC().warning("Exception during old clone "
                                                "uninstall: %s" % (e.reason))
                        self.clonesToClean.remove(self.guestclean)
                        self.guestclean = None
                        
                    # Shut down the working VM
                    self.setState("DOWN")

                    # Copy the working VM to the same SR.
                    newvm = self.guest.copyVM(xenrt.randomGuestName(),
                                               sruuid=self.sruuid)

                    # Remove the old working VM and substitute the copy
                    oldvm = self.guest
                    self.guest = newvm
                    oldvm.uninstall()
                    
                except xenrt.XRTFailure, e:
                    # Anything that breaks here is not a failure of the
                    # testcase
                    raise xenrt.XRTError(e.reason)
            if (i % 10) == 0 and not g.host.lookup("OPTION_MIXOPS_NO_CLONE",
                                                   False,
                                                   boolean=True):
                try:
                    xenrt.TEC().logdelimit("Performing clone %u" % (i/10))
                    self.setState("DOWN")
                    gc = None
                    if self.guestclean:
                        gc, a, b, c, d = self.guestclean
                        try:
                            gc.uninstall()
                        except xenrt.XRTException, e:
                            xenrt.TEC().warning("Exception during old clone "
                                                "uninstall: %s" % (e.reason))
                        self.clonesToClean.remove(self.guestclean)
                    self.guestclean = self.makeClone()
                    self.clonesToClean.append(self.guestclean)
                    try:
                        if gc and xenrt.TEC().lookup("OPTION_MIXOPS_BUGTOOLS",
                                                     False,
                                                     boolean=True):
                            gc.host.getBugTool()
                    except Exception, e:
                        xenrt.TEC().logverbose("Exception fetching bugtool: %s"
                                               % (str(e)))
                        traceback.print_exc(file=sys.stderr)
                except xenrt.XRTFailure, e:
                    # Anything that breaks here is not a failure of the
                    # testcase
                    raise xenrt.XRTError(e.reason)

            # Run a random test
            xenrt.TEC().logdelimit("Iteration %u" % (i))
            op = self.ops[random.randint(0, len(self.ops) - 1)]
            cpus = self.guest.cpuget()
            mem = self.guest.memget()
            vifs = self.guest.countVIFs()
            vbds = self.guest.countVBDs()
            current = "CPUs:%u memory=%uMB VIFs:%u VBDs:%u" % \
                      (cpus, mem, vifs, vbds)
            currentshort = "c%u_m%u_i%u_b%u" % (cpus, mem, vifs, vbds)
            xenrt.TEC().progress("Running iter %u (clone %u) %s with %s" %
                                 (i, clonei, op, current))
            if self.runSubcase(op, (), op, "%u_%s" % (i, currentshort)) != \
               xenrt.RESULT_PASS:
                if xenrt.TEC().lookup("PAUSE_ON_MIXOPS_FAIL", False, boolean=True):
                    self.pause("Mixops %s failed" % (currentshort))
                if g.host.lookup("OPTION_MIXOPS_NO_CLONE", False, boolean=True):
                    xenrt.TEC().warning("No clone to revert to, aborting")
                    break
                if clonei >= 10:
                    xenrt.TEC().warning("Too many clones, aborting")
                    break
                try:
                    # Revert to the most recent clone
                    xenrt.TEC().logdelimit("Reverting to clone")
                    if self.guest != g:
                        try:
                            if self.guest.getState() != "DOWN":
                                self.guest.shutdown(force=True)
                            self.guest.uninstall()
                        except:
                            pass
                    self.guest, self.allowedVBDs, self.removeableVBDs, \
                                self.allowedVIFs, self.removeableVIFs = \
                                self.guestclean
                    self.guest.memset(self.basemem)
                    self.guestclean = self.makeClone()
                    self.clonesToClean.append(self.guestclean)
                except xenrt.XRTFailure, e:
                    # Anything that breaks here is not a failure of the
                    # testcase
                    raise xenrt.XRTError(e.reason)
                clonei = clonei + 1
            time.sleep(15)
            i = i + 1

    def makeClone(self):
        return (self.guest.cloneVM(xenrt.randomGuestName()),
                copy.copy(self.allowedVBDs),
                copy.copy(self.removeableVBDs),
                copy.copy(self.allowedVIFs),
                copy.copy(self.removeableVIFs))

    def postRun(self):
        if not self.noclean:
            for v in self.removeableVIFs:
                try:
                    self.removeVIF()
                except:
                    pass
            for d in self.removeableVBDs:
                try:
                    self.removeVBD()
                except:
                    pass
            try:
                self.resetCPUs()
            except:
                pass
            try:
                self.resetMemory()
            except:
                pass
        for t in self.clonesToClean:
            c, w, x, y, z = t
            try:
                try:
                    c.shutdown(force=True)
                except:
                    pass
                c.poll("DOWN", 120, level=xenrt.RC_ERROR)
                c.uninstall()
            except:
                pass

class TCP2V(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCP2V")
        self.blocker = True
        self.guest = None

    def run(self, arglist=None):
        
        if arglist and len(arglist) > 0:
            machine = arglist[0]
        else:
            raise xenrt.XRTError("No machine specified for installation")
        if len(arglist) < 2:
            raise xenrt.XRTError("No guest name specified")
        guestname = arglist[1]
        if len(arglist) < 3:
            raise xenrt.XRTError("No source machine name specified")
        sourcemachine = arglist[2]
        
        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        sourcehost = xenrt.TEC().registry.hostGet(sourcemachine)
        if not sourcehost:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (sourcemachine))
        self.getLogsFrom(host)

        # Optional arguments
        vcpus = None
        memory = None
        distro = None

        for arg in arglist[2:]:
            l = string.split(arg, "=", 1)
            if l[0] == "vcpus":
                vcpus = int(l[1])
            elif l[0] == "memory":
                memory = int(l[1])
            elif l[0] == "distro":
                distro = l[1]

        g = host.p2v(guestname, distro, sourcehost)
        self.guest = g
        if vcpus != None:
            g.setVCPUs(vcpus)
        if memory != None:
            g.setMemory(memory)

        g.shutdown()
        g.start()
            
        xenrt.TEC().registry.guestPut(guestname, g)

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

class TCSuspendResumeTimeSync(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCSuspendResumeTimeSync")

    def run(self, arglist=None):
        # Default to sleep for 10 minutes
        wait = 10

        for arg in arglist:
            l = arg.split("=")
            if l[0] == "wait":
                wait = int(l[1])
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        # First argument should be an existing VM
        if not gname:
            raise xenrt.XRTError("No guest specified")
        g = xenrt.TEC().registry.guestGet(gname)
        if not g:
            raise xenrt.XRTError("Unable to find guest %s" % (gname))

        # Make sure guest is running
        if g.getState() == "DOWN":
            g.start()
        elif g.getState() == "SUSPENDED":
            g.resume()

        # If linux, enable independent wallclock
        if not g.windows:
            g.execguest("echo 1 > /proc/sys/xen/independent_wallclock")
            g.reboot()
        # If windows, make sure the clock is out of sync (we assume dom0 is
        # roughly in sync with the controller) (this is to test for CA-8531)
        else:
            # Set clock 10 mins back
            newtime = time.strftime("%H:%M:%S",time.localtime(time.time()-600))
            g.xmlrpcExec("time %s" % (newtime))

        # Note down clock skew
        skew = self.getSkew(g)
        xenrt.TEC().comment("Clock skew between guest and controller %d "
                            "seconds" % (skew))

        # Suspend the guest
        g.lifecycleOperation("vm-suspend")

        # Wait...
        xenrt.TEC().progress("Sleeping for %d minutes" % (wait))
        time.sleep(wait * 60)

        # Resume the guest (and start a timer)
        # Timeout if it takes longer to catch up than it was suspended for
        g.lifecycleOperation("vm-resume")
        st = xenrt.util.timenow()
        deadline = st + (wait * 60)
        count = 0
        while True:
            newskew = self.getSkew(g)
            # We allow a 1 second variation
            if abs(newskew - skew) <= 1:
                break
            if xenrt.util.timenow() > deadline:
                raise xenrt.XRTFailure("Clock did not get back in sync within "
                                       "timeout period")
            count += 1

        timeTaken = xenrt.util.timenow() - st

        xenrt.TEC().value("syncTime",timeTaken)

    def getSkew(self,guest):
        if guest.windows:
            gt = guest.xmlrpcGetTime()
            mt = time.time()
            return (gt - mt)
        else:
            gdate = int(guest.execguest("date -u +%s"))
            mdate = int(xenrt.util.command("date -u +%s"))
            return (gdate - mdate)

class TCCrash(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self,"TCCrash")

    def run(self, arglist=None):

        # Defaults
        checkhealth = False
        gname = None

        # Mandatory args
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":    
                gname = l[1]
            if l[0] == "checkhealth":
                checkhealth = True
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("No guest name specified")

        guest = self.getGuest(gname)
        self.getLogsFrom(guest.host)

        # Crash the guest
        guest.host.execdom0("/usr/lib/xen/bin/crash_guest %u" % 
                            (guest.getDomid()))

        if checkhealth:
            time.sleep(20)
            guest.checkHealth()

class TCSafeBoot(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self,"TCSafeBoot")
        self.guests = []

    def run(self, arglist=None):
        gname = None

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":    
                gname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("No guest name specified.")

        g = self.getGuest(gname)
        self.getLogsFrom(g.host)

        # Use a clone for the actual test.
        if g.getState() != "UP":
            xenrt.TEC().logverbose("Starting guest %s before commencing "
                                   "pre-clone tailor." % (g.name))
            g.start()

        g.preCloneTailor()

        if g.getState() == "UP":
            xenrt.TEC().comment("Shutting down guest %s before commencing "
                                "clone." % (g.name))
            g.shutdown()

        c = g.cloneVM()
        self.guests.append(c)
        c.start()

        c.waitforxmlrpc(300)
        c.xmlrpcAddBootFlag("/SAFEBOOT:NETWORK")
        c.xmlrpcExec("netsh firewall set icmpsetting 8")

        c.lifecycleOperation("vm-reboot")
        mac, ip, bridge = c.getVIF("%s0" % (c.vifstem))
        c.mainip = c.host.arpwatch(bridge, mac, timeout=1200)
        xenrt.TEC().logverbose("Found IP: %s for %s" % (c.mainip, mac))
        time.sleep(30)
        if not xenrt.command("ping -c 3 -w 10 %s" % (c.getIP())):
            raise xenrt.XRTFailure("Cannot ping guest.")

        fail = True
        try:
            c.waitforxmlrpc(300)
        except:
            fail = False

        if fail:
            raise xenrt.XRTFailure("We don't seem to be running in safe mode.")
    
    def postRun(self):
        for g in self.guests:
            try:
                g.shutdown(force=True)
            except:
                pass
            try:
                g.uninstall()
            except:
                pass

class TCLifeCycleLoop(xenrt.TestCase):
    """Perform a series of lifecycle operations on one VM in a pool."""

    def getTimer(self, op):
        timer = xenrt.util.Timer(float=True)
        self.timers.append((timer, op))
        return timer
    
    def doReboot(self):
        self.guest.host.listDomains()
        self.guest.reboot(timer=self.getTimer("reboot"))
        self.guest.host.checkHealth()
        time.sleep(20)
        if not self.opcounts.has_key("reboot"):
            self.opcounts["reboot"] = 0
        self.opcounts["reboot"] = self.opcounts["reboot"] + 1

    def doStopStart(self):
        self.guest.host.listDomains()
        self.guest.shutdown()
        self.guest.host.checkHealth()
        self.guest.host.listDomains()
        self.guest.start(timer=self.getTimer("start"))
        self.guest.host.checkHealth()
        time.sleep(20)
        if not self.opcounts.has_key("stopstart"):
            self.opcounts["stopstart"] = 0
        self.opcounts["stopstart"] = self.opcounts["stopstart"] + 1
        
    def doSuspendResume(self):
        self.guest.host.listDomains()
        self.guest.suspend(timer=self.getTimer("suspend"))
        self.guest.host.checkHealth()
        self.guest.host.listDomains()
        self.guest.resume(timer=self.getTimer("resume"))
        self.guest.host.checkHealth()
        time.sleep(20)
        if not self.opcounts.has_key("suspendresume"):
            self.opcounts["suspendresume"] = 0
        self.opcounts["suspendresume"] = self.opcounts["suspendresume"] + 1

    def doMigrate(self):
        h = self.guest.host
        self.guest.host.listDomains()
        self.guest.migrateVM(self.peerhost, live="true", timer=self.getTimer("migrate"))
        self.peerhost.checkHealth()
        self.peerhost.listDomains()
        self.guest.migrateVM(h, live="true", timer=self.getTimer("migrate"))
        self.guest.host.checkHealth()
        time.sleep(20)
        if not self.opcounts.has_key("migrate"):
            self.opcounts["migrate"] = 0
        self.opcounts["migrate"] = self.opcounts["migrate"] + 1

    def prepare(self, arglist):
        self.blocker = True
        self.guest = None
        self.peerhost = None # For migrate tests
        self.iterations = 100
        self.duration = None
        self.dosnap = False
        self.opcounts = {}
        self.timers = []

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                self.guest = self.getGuest(l[1])
            elif l[0] == "iterations":
                if l[1] != "NA":
                    self.iterations = int(l[1])
            elif l[0] == "duration": # hours
                if l[1] != "NA":
                    self.duration = int(l[1]) * 3600
                    self.iterations = None
            elif l[0] == "peerhost":
                if l[1] != "localhost":
                    self.peerhost = xenrt.TEC().registry.hostGet(l[1])
            elif l[0] == "snap":
                if len(l) == 1:
                    self.dosnap = 10
                elif l[1] != "0":
                    self.dosnap = int(l[1])
            
        if not self.guest:
            raise xenrt.XRTError("No guest specified")

    def run(self, arglist):

        iteration = 0
        starttime = xenrt.timenow()

        oplist = ["Reboot", "StopStart", "SuspendResume"]
        if self.peerhost:
            oplist.append("Migrate")

        try:
            while True:
                if xenrt.GEC().abort:
                    xenrt.TEC().warning("Aborting on command")
                    break
                if self.iterations and iteration >= self.iterations:
                    break
                if self.duration and \
                       xenrt.timenow() > (starttime + self.duration):
                    break
                opchoice = oplist
                op = random.choice(opchoice)
                xenrt.TEC().logdelimit("loop iteration %u (%s)..." %
                                       (iteration, op))
                if self.dosnap and (iteration % self.dosnap) == 0:
                    snapuuid = self.guest.snapshot()
                eval("self.do%s()" % (op))
                if self.dosnap and (iteration % self.dosnap) == 0:
                    self.guest.host.removeTemplate(snapuuid)
                iteration = iteration + 1
        finally:
            for timer, op in self.timers:
                if not timer.starttime and timer.measurements:
                    self.rageTimings.append("TIME_VM_%s_DURATION_%s:%.3f" % (op.upper(), self.guest.getName(), timer.measurements[-1]))
            
            dur = xenrt.timenow() - starttime
            xenrt.TEC().comment("Total iterations: %u" % (iteration))
            xenrt.TEC().comment("Duration: %uh%02u" %
                                (dur/3600, (dur%3600)/60))
            for op in self.opcounts.keys():
                xenrt.TEC().comment("Operations '%s': %u" %
                                    (op, self.opcounts[op]))

class TCCheckToolsCD(xenrt.TestCase):
    """Check the VM still has a tools ISO attached and working"""

    def prepare(self, arglist):
        self.guest = None

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                self.guest = self.getGuest(l[1])

        if not self.guest:
            raise xenrt.XRTError("No guest specified")

        self.host = self.guest.host

    def run(self, arglist):
        # First verify there is a CD drive
        cds = self.host.minimalList("vbd-list", args="vm-uuid=%s type=CD" % (self.guest.getUUID()))
        if len(cds) == 0:
            raise xenrt.XRTFailure("No CD drive found")
        elif len(cds) > 1:
            raise xenrt.XRTError("Multiple CD drives found")
        vbd = cds[0]

        # Now check it is the tools ISO
        vdi = self.host.genParamGet("vbd", vbd, "vdi-uuid")
        if not xenrt.isUUID(vdi):
            raise xenrt.XRTFailure("Did not find VDI in CD drive")

        name = self.host.genParamGet("vdi", vdi, "name-label")
        if name != "xs-tools.iso":
            raise xenrt.XRTFailure("Non tools ISO in CD drive", data="Found %s" % (name))

        if self.guest.windows:
            # Check we see a CD with xensetup.exe on it
            if not self.guest.xmlrpcFileExists("D:\\xensetup.exe") and not self.guest.xmlrpcFileExists("D:\\installwizard.msi"):
                raise xenrt.XRTFailure("Couldn't find xensetup.exe or installwizard.msi on tools ISO")
            
        else:
            # If a linux VM, check the md5 matches
            device = self.host.genParamGet("vbd", vbd, "device")
            guestmd5 = self.guest.execguest("md5sum /dev/%s" % (device)).split()[0]          
            vdiuuid = self.host.minimalList("vdi-list",args="name-label=xs-tools.iso") 
            hostToolName = self.host.minimalList("vdi-param-get uuid=%s param-name=location" %(vdiuuid[0])) 
            hostmd5 = self.host.execdom0("md5sum /opt/xensource/packages/iso/%s" % (hostToolName[0])).split()[0] 
            if guestmd5 != hostmd5:
                raise xenrt.XRTFailure("In-guest md5sum of tools ISO does not match host md5sum",
                                       data="Guest: %s, host: %s" % (guestmd5, hostmd5))

class GraphicsEmulationCheck(xenrt.TestCase):
    """Base class for verifying the video controller property check."""

    GUEST_VIDEO_RAM = 0
    GUEST_DISPLAY_ADAPTER_NAME = ""

    def prepare(self, arglist=None):
        self.guest = None

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                self.guest = self.getGuest(l[1])

        if not self.guest:
            raise xenrt.XRTError("No guest specified")

        self.host = self.guest.host

    def videoControllerPropertyCheckUsingWMI(self):
        """Obtain the Guest Video Settings Properties using WMI instrumentation."""

        videoResults = self.guest.getVideoControllerInfo()

        if videoResults==None:
            raise xenrt.XRTFailure("Couldn't retrieve the video controller property from the HVM guest.")

        if videoResults.has_key("AdapterRAM"):
            adapterRAM = videoResults["AdapterRAM"]

            if len(adapterRAM) > 0:
                # convert string to int
                adapterRAM = int(adapterRAM) / xenrt.MEGA

                if adapterRAM == 0:
                    # ISSUE (1) - Adapter RAM reported 0.
                    #raise xenrt.XRTFailure("The HVM guest has reported 0 graphics memory using WMI instrumentation.")
                    xenrt.TEC().logverbose("The HVM guest has reported 0 graphics memory using WMI instrumentation.")
                else:
                    if adapterRAM != self.GUEST_VIDEO_RAM:
                        raise xenrt.XRTFailure("The HVM guest is configured with %uMB of graphics memory." % adapterRAM)
                    else:
                        xenrt.TEC().logverbose("The HVM guest is configured with %uMB of graphics memory as expected." % adapterRAM)
            else:
                # ISSUE (2) - Adapter RAM reported Empty.
                #raise xenrt.XRTFailure("The HVM guest has not detected (Empty) the available graphics memory using WMI instrumentation.")
                xenrt.TEC().logverbose("The HVM guest has not detected (Empty) the available graphics memory using WMI instrumentation.")

                # ISSUE (1) & ISSUE (2) needs to be addressed as to why Windows guest is not populating VM parameters using WMI Instrumentation.
        else:
            raise xenrt.XRTFailure("Couldn't find the video controller key property: AdapterRAM.")

        if not videoResults.has_key("Name"): # Name = Caption = Description
            raise xenrt.XRTFailure("Couldn't find the video controller key property: Name.")
        else:
            xenrt.TEC().logverbose("Found the video controller key property: Name.")

        if videoResults["Name"] != self.GUEST_DISPLAY_ADAPTER_NAME:
            raise xenrt.XRTFailure("The video controller key property: Name should have a value: Standard VGA Graphics Adapter.")
        else:
            xenrt.TEC().logverbose("Found the value (%s) for video controller key property: Name." % 
                                                                                self.GUEST_DISPLAY_ADAPTER_NAME)

class TCCheckCirrusLogic(GraphicsEmulationCheck):
    """Check whether non-Windows-8 Guests uses Cirrus Logic Device Emulation."""

    GUEST_VIDEO_RAM = 4 # 4MB used in non-Windows 8
    GUEST_DISPLAY_ADAPTER_NAME = "Standard VGA Graphics Adapter"

    def run(self, arglist=None):
        domid = self.guest.getDomid()
        data = self.host.execdom0("ps aux | grep  qemu-dm-%u" % (domid))

        # 1. Checks for guest video controller in dom0
        if re.search(r"-std-vga", data):
            raise xenrt.XRTFailure("The HVM guest [non-Windows-8] under test uses std-vga for graphics emulation.")

        if not re.search(r"-videoram 4", data):
            raise xenrt.XRTFailure("The HVM guest [non-Windows-8] under test does not use 4MB of graphics memory.")

        # Commenting (2) below due to CA-103816/CP-3848. Now the required log is in /var/log/daemon.log

        # 2. Another level of guest check using /var/log/messages.
        #try:
        #    # qemu-dm-15[32249]: pci_register_device: 00:02:00 (Cirrus VGA)
        #    cvgaData = self.host.execdom0('cat /var/log/messages | grep "Cirrus VGA" | grep qemu-dm-%u' % (domid))
        #except:
        #    raise xenrt.XRTFailure("Couldn't find the video controller property:Cirrus VGA for HVM guest [non-Windows-8] in host /var/log/messages.")

        #xenrt.TEC().logverbose("Found video controller property:Cirrus VGA for HVM guest [non-Windows-8] in host /var/log/messages.")

        # 3. Check using WMI instrumentation.
        self.videoControllerPropertyCheckUsingWMI()

class TCCheckStdVGA(GraphicsEmulationCheck):
    """Std VGA device emulation replaces cirrus logic device emulation for Windows 8."""

    GUEST_VIDEO_RAM = 8 # 8MB used in Windows 8
    GUEST_DISPLAY_ADAPTER_NAME = "Microsoft Basic Display Adapter"

    def run(self, arglist=None):
        domid = self.guest.getDomid()
        data = self.host.execdom0("ps aux | grep  qemu-dm-%u" % (domid))

        # 1. Checks for guest video controller in dom0
        if not re.search(r"-std-vga", data):
            raise xenrt.XRTFailure("The HVM guest [Windows-8] under test does not use std-vga for graphics emulation.")

        if not re.search(r"-videoram 8", data):
            raise xenrt.XRTFailure("The HVM guest [Windows-8] under test does not use 8MB of graphics memory.")

        # 2. Another level of guest check.
        if (int(self.guest.paramGet("platform", "videoram")) != self.GUEST_VIDEO_RAM):
            raise xenrt.XRTFailure("The HVM guest [Windows-8] under test does not use 8MB of graphics memory.")

        if (self.guest.paramGet("platform", "vga") != "std"):
            raise xenrt.XRTFailure("The HVM guest [Windows-8] under test does not use std-vga for graphics emulation.")

        # 3. Check using WMI instrumentation.
        self.videoControllerPropertyCheckUsingWMI()

class TCSysprep(xenrt.TestCase):
        
    goldenVM = None
    host = None
    vdi = None
    bridge = None
    nwuuid = None
    num_vms = 1
    
    def installGoldenVM(self, host, distro, vcpus, memory):
        
        guest = self.host.createGenericWindowsGuest(distro=distro,
                                                    vcpus=vcpus,
                                                    memory=memory,
                                                    name='win0')
        guest.xmlrpcDoSysprep()
        guest.reboot()
        guest.checkPVDevices()
        
        return guest
    
    def cloneVM(self, guest, spare_memory):
        
        g = None
        if (int(self.host.getHostParam("memory-free")) / xenrt.MEGA) > (guest.memory + spare_memory):
            g = guest.cloneVM()
            g.start()
            g.waitforxmlrpc(300)
            g.checkPVDevices()
            self.uninstallOnCleanup(g)
        return g

    def checkPVDevs(self, vms):
        for vm in vms:
            vm.checkPVDevices()
        return
        
    def doParallel(self, ops, desc):
        tasks = [xenrt.PTask(op) for op in ops]
        xenrt.pfarm(tasks)
        xenrt.TEC().logverbose(desc)
        return
    

    def testVBDPlugUnplug(self, guest, vdi):
 
        vbds = guest.listVBDs()
        ds = vbds.keys()
        userdevice = max(map(int, ds)) + 1

        args = ["device=%s" % userdevice, 
                "vdi-uuid=%s" % vdi,
                "vm-uuid=%s" % guest.getUUID(),
                "mode=RW",
                "type=Disk"]
        
        cli = self.host.getCLIInstance()
        vbd = cli.execute("vbd-create", string.join(args), strip=True)

        xenrt.TEC().logverbose("Plugging VBD on %s" % guest.getName())
        cli.execute("vbd-plug", "uuid=%s" % vbd)
        
        xenrt.TEC().logverbose("Unplugging VBD on %s" % guest.getName())
        cli.execute("vbd-unplug", "uuid=%s" % vbd)

        cli.execute("vbd-destroy", "uuid=%s" % vbd)

        return
    
    def testVIFPlugUnplug(self, guest, bridge):
        eth = guest.createVIF(bridge=bridge, plug=True)
        guest.unplugVIF(eth)
        guest.removeVIF(eth)
        return
    
    def testLiveMigrate(self, guest):
        free_mem = self.host.getFreeMemory()
        if free_mem < (2 * guest.memory):
            xenrt.TEC().logverbose("Not enough memory to migrate. (%s < 2*%s)"
                                   % (free_mem, guest.memory))
        else:
            guest.migrateVM(self.host, live="true")
            xenrt.TEC().logverbose("Migration of %s successful" % guest.getName())
        return

    def prepare(self, arglist=[]):
        
        distro = "ws08r2-x64"
        vcpus = 1
        memory = 1024
        gname = None
        
        # Get the host/master
        pool = self.getDefaultPool()
        if pool is None:
            self.host = self.getDefaultHost()
        else:
            self.host = pool.master

        for arg in arglist:
            if arg.startswith('distro'):
                distro = arg.split('=')[1].strip()
            elif arg.startswith('clones'):
                self.num_vms = int(arg.split('=')[1])
            elif arg.startswith('memory'):
                memory = int(arg.split('=')[1])
            elif arg.startswith('guest'):
                gname = arg.split('=')[1].strip()

        if gname is not None: # Let us reuse a SYSPREPed VM from the earlier test (possibly).
            self.goldenVM = self.getGuest(gname)
            self.goldenVM.setHost(self.host)
        else:
            self.goldenVM = self.installGoldenVM(self.host, distro, vcpus, memory)

        if self.goldenVM.getState <> 'DOWN': # We are going to clone.
            self.goldenVM.shutdown()

        self.vdi = self.host.createVDI(512 * xenrt.MEGA)
        self.nwuuid = self.host.createNetwork()
        self.bridge = self.host.genParamGet("network", self.nwuuid, "bridge")
        
        return

    def run(self, arglist=None):

        # Let us check clone operation.
        spare_memory = 3 * int(self.goldenVM.memory)  # Spare some memory for guest migrate
        clones = filter(bool, 
                        [self.cloneVM(self.goldenVM, spare_memory) for i in range(self.num_vms)])
        
        self.doParallel([g.shutdown for g in clones],
                        "All Guests  shutdown  succesfully")

        self.doParallel([g.start for g in clones],
                        "All Guests  started  succesfully")
        self.checkPVDevs(clones)        

        self.doParallel([g.reboot for g in clones],
                        "All guests  rebooted  succesfully")
        self.checkPVDevs(clones)

        self.doParallel([g.suspend for g in clones],
                        "All guests  suspended  succesfully")

        self.doParallel([g.resume for g in clones],
                        "All guests  resumed  succesfully")
        self.checkPVDevs(clones)        
        
        # Test VBD plug-unplug
        map(lambda g: self.testVBDPlugUnplug(g, self.vdi), clones)
        self.checkPVDevs(clones)        

        # Test VIF plug-unplug network 
        map(lambda g: self.testVIFPlugUnplug(g, self.bridge), clones)
        self.checkPVDevs(clones)        
        
        # Test live migrate (local host)
        map(lambda g: self.testLiveMigrate(g), clones)
        self.checkPVDevs(clones)        

        return

    def postRun(self):
        
        cli = self.host.getCLIInstance()
        if self.vdi:
            cli.execute("vdi-destroy", "uuid=%s" % self.vdi)
        
        if self.nwuuid:
            cli.execute("network-destroy", "uuid=%s" % self.nwuuid)

        return

class TCPVHVMIInstall(xenrt.TestCase):
    
    def __init__(self):
        xenrt.TestCase.__init__(self, "TCPVHVMIInstall")
        #self.blocker = True
        #self.guest = None
        #self.host = None

    def run(self, arglist=[]):

        args = xenrt.util.strlistToDict(arglist)

        # Optional arguments
        distro = args.get("distro") or "rhel65"
        vcpus = args.get("vcpus") or None
        memory = args.get("memory") or None
        if memory: memory = int(memory)
        arch = args.get("arch") or "x86-32"
        sr = args.get("sr") or None
        sruuid = None
        host = self.getDefaultHost()
        if sr:
            if xenrt.isUUID(sr):
                sruuid = sr
            else:
                sr_uuids = host.getSRs()
                sr_names = [host.getSRParam(uuid=sr_uuid, param='name-label') for sr_uuid in sr_uuids]
                sr_map = dict(zip(sr_names, sr_uuids))
                if sr_map.has_key(sr):
                    sruuid = sr_map[sr]
                else:
                    sruuid = sr #Default behaviour
        notools = args.get("notools") or False
        extrapackages = args.get("extrapackages") or None
        rootdisk = args.get("rootdisk") or None
        if rootdisk: rootdisk = int(rootdisk)
        vifs = args.get("vifs") or xenrt.lib.xenserver.Guest.DEFAULT
        extradisks = args.get("extradisks") or None
        guestname = args.get("guest") or None
        if not guestname:
            guestname = distro #+ "_" + xenrt.util.randomGuestName()
            if arch == "x86-64": guestname += arch
        #post_shutdown = False

        guest = self.getDefaultHost().createBasicGuest( 
                         distro = distro,
                         vcpus = vcpus,
                         memory = memory,
                         name = guestname,
                         arch = arch,
                         sr = sruuid,
                         #bridge=None,
                         #use_ipv6=False,
                         notools = notools,
                         disksize=rootdisk,
                         #rawHBAVDIs=None,
                         #primaryMAC=None,
                         #reservedIP=None,
                         forceHVM = True
                         )
        xenrt.TEC().registry.guestPut(guestname, guest)
        xenrt.TEC().registry.configPut(guestname, vcpus=vcpus,
                                                  memory=memory,
                                                  distro=distro,
                                                  arch=arch,
                                                  disksize=rootdisk)
        xenrt.sleep(30)
        guest.setState("DOWN")


