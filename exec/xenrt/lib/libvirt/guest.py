#
# XenRT: Test harness for Xen and the XenServer product family
#
# Operations on libvirt guests.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import os, re, time, socket, string, xml.dom.minidom, IPy

import xenrt
import libvirt

__all__ = ["createVMFromFile",
           "createVM",
           "Guest",
           "tryupto"]

def createVMFromFile(host,
                     guestname,
                     filename,
                     postinstall=[],
                     packages=[],
                     vcpus=None,
                     memory=None,
                     suffix=None,
                     ips={},
                     sr=None,
                     vifs=[],
                     *args,
                     **kwargs):
    if not isinstance(host, xenrt.GenericHost):
        host = xenrt.TEC().registry.hostGet(host)
    if suffix:
        displayname = "%s-%s" % (guestname, suffix)
    else:
        displayname = guestname
    guest = host.guestFactory()(displayname, host=host)
    guest.imported = True
    guest.ips = ips

    vifs = [[device, host.getBridgeByName(bridge), mac, ip] for (device, bridge, mac, ip) in vifs]

    file=xenrt.TEC().getFile(filename)
    if file.endswith(".zip"):
        fileDir=xenrt.TEC().tempDir()
        xenrt.command("unzip -o %s -d %s" % (file,fileDir))
        for root, dirs, files in os.walk(fileDir):
            files = [fi for fi in files if fi.endswith((".ovf",".ova"))]
            if files:
                file=fileDir+"/"+files[0]
            else:
                raise xenrt.XRTError("Unknown VM container type inside zip")

    guest.importVM(host, file, sr=sr, vifs=vifs)

    guest.password = None
    guest.tailored = True
    if vcpus:
        guest.cpuset(vcpus)
    if memory:
        guest.memset(memory)
    xenrt.TEC().registry.guestPut(guestname, guest)
    for p in postinstall:
        if "(" in p:
            eval("guest.%s" % (p))
        else:
            eval("guest.%s()" % (p))
    if packages:
        guest.installPackages(packages)
    return guest

def createVM(host,
             guestname,
             distro,
             vcpus=None,
             corespersocket=None,
             memory=None,
             vifs=[],
             bridge=None,
             sr=None,
             guestparams=[],
             arch="x86-32",
             disks=[],
             postinstall=[],
             pxe=True,
             template=None,
             notools=False,
             bootparams=None,
             use_ipv6=False,
             suffix=None,
             ips={},
             **kwargs):

    if not isinstance(host, xenrt.GenericHost):
        host = xenrt.TEC().registry.hostGet(host)

    if distro.startswith("generic-"):
        distro = distro[8:]
        if not vifs:
            # Some tests rely on getting a VIF by default for generic VMs.
            vifs = xenrt.lib.libvirt.Guest.DEFAULT
    if distro.lower() == "windows" or distro.lower() == "linux":
        distro = host.lookup("GENERIC_" + distro.upper() + "_OS"
                             + (arch.endswith("64") and "_64" or ""),
                             distro)
    # Create the guest object.
    if not template:
        template = host.getTemplate(distro, arch=arch)
    g = host.guestFactory()(guestname,
                            template,
                            password=xenrt.TEC().lookup("DEFAULT_PASSWORD"))
    g.arch = arch
    if re.search("[vw]", distro):
        g.windows = True
        g.vifstem = g.VIFSTEMHVM
        g.hasSSH = False
    else:
        g.windows = False
        g.vifstem = g.VIFSTEMPV
        g.hasSSH = True

    if vifs == xenrt.lib.libvirt.Guest.DEFAULT:
        vifs = [("0",
                 host.getPrimaryBridge(),
                 xenrt.randomMAC(),
                 None)]

    update = []
    for v in vifs:
        device, bridge, mac, ip = v
        device = "%s%s" % (g.vifstem, device)
        if not bridge:
            bridge = host.getPrimaryBridge()

        if not bridge:
            raise xenrt.XRTError("Failed to choose a bridge for createVM on "
                                 "host !%s" % (host.getName()))
        bridge = host.getBridgeByName(bridge)
        update.append([device, bridge, mac, ip])
    vifs = update

    # The install method doesn't do this for us.
    if vcpus:
        g.setVCPUs(vcpus)
    if memory:
        g.setMemory(memory)

    # TODO: boot params

    # Try and determine the repository.
    repository = xenrt.getLinuxRepo(distro, arch, "HTTP", None)

    # Work out the ISO name.
    if not repository:
        isoname = xenrt.DEFAULT
    else:
        isoname = None

    rootdisk = xenrt.lib.libvirt.Guest.DEFAULT
    for disk in disks:
        device, size, format = disk
        if device == "0":
            rootdisk = int(size)*xenrt.GIGA

    # Install the guest.
    g.install(host,
              distro=distro,
              vifs=vifs,
              bridge=bridge,
              sr=sr,
              guestparams=guestparams,
              isoname=isoname,
              rootdisk=rootdisk,
              repository=repository,
              pxe=pxe,
              notools=notools,
              use_ipv6=use_ipv6)

    if g.windows:
        g.xmlrpcShutdown()
    else:
        g.execguest("/sbin/shutdown -h now")
    g.poll("DOWN")

    diskstoformat = []
    for disk in disks:
        device, size, format = disk
        if str(device) != "0":
            d = g.createDisk(sizebytes=int(size)*xenrt.GIGA,userdevice=device)
            if format:
                diskstoformat.append(d)

    g.start()

    for d in diskstoformat:
        if g.windows:
            letter = g.xmlrpcPartition(d)
            g.xmlrpcFormat(letter, timeout=3600)
        else:
            # FIXME: this is probably wrong
            letter = g.DEVICE_DISK_PREFIX + chr(int(d)+ord('a'))
            g.execguest("mkfs.ext2 /dev/%s" % (letter))
            g.execguest("mount /dev/%s /mnt" % (letter))

    # Store the object in the registry.
    xenrt.TEC().registry.guestPut(guestname, g)
    xenrt.TEC().registry.configPut(guestname, vcpus=vcpus,
                                   memory=memory,
                                   distro=distro)

    for p in postinstall:
        if type(p) == tuple:
            data, format = p
            if format == "cmd":
                g.xmlrpcWriteFile("c:\\postrun.cmd", data)
                g.xmlrpcExec("c:\\postrun.cmd")
                g.xmlrpcRemoveFile("c:\\postrun.cmd")
            elif format == "vbs":
                g.xmlrpcWriteFile("c:\\postrun.vbs", data)
                g.xmlrpcExec("cscript //b //NoLogo c:\\postrun.vbs")
                g.xmlrpcRemoveFile("c:\\postrun.vbs")
        else:
            eval("g.%s()" % (p))

    return g

def tryupto(func, tries=3, delay=0):
    def _tryupto(*args, **kwargs):
        i = 1
        while True:
            try:
                return func(*args, **kwargs)
            except Exception, e:
                xenrt.TEC().logverbose("tryupto: exception %s" % e)
                i += 1
                if i > tries:
                    xenrt.TEC().logverbose("tryupto: giving up")
                    raise
                time.sleep(delay)
                xenrt.TEC().logverbose("tryupto: Trying again (try %s out of %s)" % (i, tries))
    return _tryupto

class Guest(xenrt.GenericGuest):
    """Encapsulates a single guest VM."""

    VIFSTEM = "eth"
    VIFSTEMPV = "eth"
    VIFSTEMHVM = "eth"

    DEFAULT = -10

    def __init__(self, name, template=None, host=None, password=None):
        xenrt.GenericGuest.__init__(self, name, host=host)
        self.virConn = None
        self.virDomain = None

        self.template = template
        if self.template and (re.search("[Ww]in", self.template)):
            self.windows = True
            self.vifstem = self.VIFSTEMHVM
            self.hasSSH = False
        elif self.template and (re.search("Solaris", self.template)):
            self.windows = False
            self.vifstem = self.VIFSTEMSOLPV
            self.hasSSH = True
        else:
            self.windows = False
            self.vifstem = self.VIFSTEMPV
            self.hasSSH = True

        if host:
            self.virConn = host.virConn
        if password:
            self.password = password

        self.tailored = False
        self.uuid = None
        self.use_ipv6 = xenrt.TEC().lookup('USE_GUEST_IPV6', False, boolean=True)

        # No support for SR-IOV for libvirt hosts
        self.sriovvifs = []

    # override these functions to work around libvirt driver limitations.

    def _isSuspended(self):
        """Check if the domain is suspended."""
        return self.virDomain.hasManagedSaveImage(0)

    def _attachDevice(self, devicexmlstr, hotplug=False):
        """Attach a new device to the domain."""
        xenrt.TEC().logverbose("Attaching device to %s: devicexml=%s" % (self.name, devicexmlstr))
        if hotplug:
            if self.getState() == "UP" and self.enlightenedDrivers:
                try:
                    self.virDomain.attachDeviceFlags(devicexmlstr, libvirt.VIR_DOMAIN_AFFECT_LIVE | libvirt.VIR_DOMAIN_AFFECT_CONFIG)
                    return
                except:
                    xenrt.TEC().warning("Could not hotplug attach device")
            else:
                xenrt.TEC().logverbose("Ignoring request to hotplug attach device")
        self.virDomain.attachDeviceFlags(devicexmlstr, libvirt.VIR_DOMAIN_AFFECT_CONFIG)

    def _updateDevice(self, devicexmlstr, hotplug=False):
        """Update an existing device in the domain."""
        xenrt.TEC().logverbose("Updating device in %s" % self.name)
        if hotplug:
            if self.getState() == "UP" and self.enlightenedDrivers:
                try:
                    self.virDomain.updateDeviceFlags(devicexmlstr, libvirt.VIR_DOMAIN_AFFECT_LIVE | libvirt.VIR_DOMAIN_AFFECT_CONFIG)
                    return
                except:
                    xenrt.TEC().warning("Could not hotplug update device")
            else:
                xenrt.TEC().logverbose("Ignoring request to hotplug update device")
        self.virDomain.updateDeviceFlags(devicexmlstr, libvirt.VIR_DOMAIN_AFFECT_CONFIG)

    def _removeDevice(self, devicexmlstr, hotplug=False):
        """Remove an existing device in the domain."""
        xenrt.TEC().logverbose("Destroying device in %s" % self.name)
        if hotplug:
            if self.getState() == "UP" and self.enlightenedDrivers:
                try:
                    self.virDomain.detachDeviceFlags(devicexmlstr, libvirt.VIR_DOMAIN_AFFECT_LIVE | libvirt.VIR_DOMAIN_AFFECT_CONFIG)
                    return
                except:
                    xenrt.TEC().warning("Could not hotplug destroy device")
            else:
                xenrt.TEC().logverbose("Ignoring request to hotplug destroy device")
        self.virDomain.updateDeviceFlags(devicexmlstr, libvirt.VIR_DOMAIN_AFFECT_CONFIG)

    def _getXML(self):
        """Get the XML description of the domain."""
        return tryupto(self.virDomain.XMLDesc)(libvirt.VIR_DOMAIN_XML_INACTIVE)

    def _defineXML(self, newxmlstr):
        """Create a domain from an XML description"""
        self.virConn.defineXML(newxmlstr)

    def _redefineXML(self, newxmlstr):
        """Update the domain definition from an XML description"""
        self.virConn.defineXML(newxmlstr)


    # override these functions to provide hypervisor-specific stuff

    def _getDiskDevicePrefix(self):
        """Get the disk device name prefix.

        This function can not return None."""

        return "hd"

    def _getDiskDeviceBus(self):
        """Get the disk device bus.

        This function can not return None."""

        return "ide"

    def _getNetworkDeviceModel(self):
        """Get the network device model.

        See http://libvirt.org/formatdomain.html#elementsNICSModel.
        This function can return None, to use the default device model."""

        return None # use default

    def _detectDistro(self):
        """Try to detect the distro."""
        # try some heuristics
        if re.search("win", self.getName()) is not None:
            self.windows = True
            self.hasSSH = False

    def _preInstall(self):
        """Do stuff before a guest is about to be installed."""
        pass


    def _postInstall(self):
        """Do stuff after a guest has installed.

        Note that at this point the guest is *not* running! If you need
        to install tools inside the guest whilst it is running, override
        the "tailor" method instead."""
        pass



    def getState(self):
        state = self.virDomain.info()[0]
        if state == libvirt.VIR_DOMAIN_SHUTOFF:
            if self._isSuspended():
                return "SUSPENDED"
            return "DOWN"
        if state == libvirt.VIR_DOMAIN_CRASHED:
            return "DOWN"
        if state == libvirt.VIR_DOMAIN_RUNNING:
            return "UP"
        if state == libvirt.VIR_DOMAIN_PAUSED:
            return "PAUSED"
        if state == libvirt.VIR_DOMAIN_SHUTDOWN:
            return "SHUTTING_DOWN"
        return "UNKNOWN"

    def install(self,
                host,
                start=True,
                isoname=None,
                vifs=DEFAULT,
                repository=None,
                kickstart="standard",
                distro=None,
                guestparams=[],
                method="HTTP",
                rootdisk=DEFAULT,
                pxe=True,
                sr=None,
                extrapackages=None,
                notools=False,
                extradisks=None,
                bridge=None,
                use_ipv6=False):

        self.setHost(host)
        if not self.virConn:
            self.virConn = host.virConn

        # Hack to use correct kickstart for rhel6
        if distro and kickstart == "standard":
            if distro.startswith("rhel6") or distro.startswith("rhelw6"):
                kickstart = "rhel6"
            if distro.startswith("oel6"):
                kickstart = "oel6"
            if distro.startswith("centos6"):
                kickstart = "centos6"
            if distro.startswith("sl6"):
                kickstart = "sl6"

        # Have we been asked to choose an ISO automatically?
        if isoname == xenrt.DEFAULT:
            if not distro:
                raise xenrt.XRTError("Cannot choose ISO automatically without "
                                     "specifying a distro")
            if self.arch:
                arch = self.arch
            else:
                arch = "x86-32"
            isostem = host.lookup(["OS_INSTALL_ISO", distro], distro)
            trylist = ["%s_xenrtinst.iso" % (isostem), "%s.iso" % (isostem)]

            if distro == "w2k3eesp2pae":
                trylist.append("w2k3eesp2.iso")

            if arch:
                trylist.append("%s_%s.iso" % (isostem, arch))
            if distro.startswith("win") or distro.startswith("ws"):
                if arch in ["x86-64", "x64", "64"]:
                    winarch = "x64"
                else:
                    winarch = "x86"
                trylist.append("%s-%s.iso" % (distro, winarch))

            isoname = None
            for tryit in trylist:
                if self.host.getCDPath(tryit):
                    isoname = tryit
                    break
            if not isoname:
                raise xenrt.XRTError("Could not find a suitable ISO for %s "
                                     "(arch %s)" % (distro, arch))

        self.isoname = isoname
        if distro:
            self.distro = distro
        host.addGuest(self)

        if use_ipv6: # if this was set to True, override the global flag.
            self.use_ipv6 = True

        # IPv6 support for w2k3 and winxp is flakey
        if distro and re.search("w2k|xp", distro) and use_ipv6:
            xenrt.TEC().logverbose("For windows guests, IPv6 is supported from Vista onwards.")
            raise xenrt.XRTFailure("IPv6 is not supported for the distro %s" % distro)

        if vifs:
            self.vifs = vifs

        if pxe:
            self.vifstem = self.VIFSTEMHVM
            self.enlightenedDrivers = False

        # Prepare VIFs
        if type(vifs) == type(self.DEFAULT):
            if bridge:
                br = bridge
            else:
                br = host.getPrimaryBridge()
                if not br:
                    raise xenrt.XRTError("Host has no bridge")
            self.vifs = [("%s0" % (self.vifstem), br, xenrt.randomMAC(), None)]
            # if not vifs == self.DEFAULT:
            #     nwuuid = host.createNetwork()
            #     bridge = host.genParamGet("network", nwuuid, "bridge")
            #     for i in range(vifs - 1):
            #         self.vifs.append(("%s%d" % (self.vifstem, i + 1), bridge, xenrt.randomMAC(), None))


        if self.windows:
            if len(self.vifs) == 0:
                raise xenrt.XRTError("Need at least one VIF to install Windows")
        if repository:
            if len(self.vifs) == 0:
                raise xenrt.XRTError("Need at least one VIF to install with "
                                     "vendor installer")

        # Choose a storage respository
        if not sr:
            sruuid = self.chooseSR()
        else:
            if xenrt.isUUID(sr):
                sruuid = sr
            else:
                sruuid = self.getHost().virConn.poolLookupByName(sr).UUIDString()

        memory_min_limit = xenrt.TEC().lookup(["GUEST_LIMITATIONS", distro, "MINMEMORY"], None)
        memory_max_limit = xenrt.TEC().lookup(["GUEST_LIMITATIONS", distro, "MAXMEMORY"], None)

        if memory_min_limit:
            memory_min_limit = int(memory_min_limit)
            if self.memory < memory_min_limit:
                self.memory = memory_min_limit
        if memory_max_limit:
            memory_max_limit = int(memory_max_limit)
            if self.memory > memory_max_limit:
                self.memory = memory_max_limit

        self._preInstall()

        # Contruct the VM
        if False:
            # Construct a VM step by step
            self.createHVMGuest([(rootdisk, sruuid)], pxe=pxe)
            if self.memory:
                self.memset(self.memory)
            if self.vcpus:
                self.cpuset(self.vcpus)
        else:
            # Create from a template
            if not self.windows and not repository:
                ni = True
            else:
                ni = False
            self.createGuestFromTemplate(self.template,
                                         sruuid,
                                         ni=ni,
                                         guestparams=guestparams,
                                         rootdisk=rootdisk)

        # This is just in case it has autostarted
        time.sleep(5)
        try:
            if self.getState() != "DOWN":
                self.lifecycleOperation("vm-shutdown", force=True)
        except:
            pass

        # Add VIFs
        for eth, bridge, mac, ip in self.vifs:
            self.createVIF(eth, bridge, mac)

        # # Resize root disk if necessary
        # if not xenrt.TEC().lookup("OPTION_CLONE_TEMPLATE", False, boolean=True):
        #     if rootdisk != self.DEFAULT:
        #         # Handle the case where there is no existing rootdisk (CA-60974)
        #         if not self.hasRootDisk():
        #             self.createDisk(sizebytes=int(rootdisk)*xenrt.MEGA, bootable=True)
        #         rootdiskid, size, min_size, function, qos = \
        #                     self.getRootDiskDetails()
        #         if rootdisk < size:
        #             xenrt.TEC().warning("Unable to shrink root disk from"
        #                                 " %uMB to %uMB" % (size, rootdisk))
        #         else:
        #             self.resizeDisk(rootdiskid, rootdisk)
        #             xenrt.TEC().logverbose("Resized root disk to %uMB" %
        #                                    (rootdisk))

        # Add any extra disks.
        if extradisks:
            for size in extradisks:
                self.createDisk(sizebytes=int(size)*xenrt.MEGA)

        # Windows needs to install from a CD
        if self.windows:
            self.installWindows(self.isoname)
        elif repository and not isoname:
            if host.productType == "esx":
                pxe = True
            elif host.productType == "kvm":
                pxe = False

            dev = "%sa" % (self.vendorInstallDevicePrefix())
            options = {"maindisk" : dev}
            if not pxe:
                options["OSS_PV_INSTALL"] = True
            # Install using the vendor installer.
            self.installVendor(distro,
                               repository,
                               method="HTTP",
                               config=kickstart,
                               pxe=pxe,
                               extrapackages=extrapackages,
                               options=options)
        elif isoname:
            xenrt.TEC().logverbose("Installing Linux from ISO...")
            dev = "%sa" % (self.vendorInstallDevicePrefix())
            # Unset bootable flag on VBD.
            vbduuid = self.getHost().parseListForUUID("vbd-list",
                                                 "vm-uuid",
                                                  self.getUUID())
            xenrt.TEC().logverbose("Unsetting disk bootable flag.")
            self.getHost().genParamSet("vbd", vbduuid, "bootable", "false")
            xenrt.TEC().logverbose("Disk readback bootable=%s" %
                                   (self.getHost().genParamGet("vbd",
                                                               vbduuid,
                                                               "bootable")))
            if distro and distro.startswith("solaris"):
                self.changeCD(isoname,device="hdd")
            else:
                self.changeCD(isoname,device="xvdd")
            # Set the bootable flag on CD.
            cdvbduuid = self.getHost().parseListForUUID("vbd-list",
                                                        "vm-uuid",
                                                        self.getUUID(),
                                                        "type=CD")
            xenrt.TEC().logverbose("Setting CD bootable flag.")
            self._setBoot("cdrom")
            self.getHost().genParamSet("vbd", cdvbduuid, "bootable", "true")
            xenrt.TEC().logverbose("CD readback bootable=%s" %
                                   (self.getHost().genParamGet("vbd",
                                                               cdvbduuid,
                                                               "bootable")))
            xenrt.TEC().logverbose("Disk readback bootable=%s" %
                                   (self.getHost().genParamGet("vbd",
                                                               vbduuid,
                                                               "bootable")))
            self.installVendor(distro,
                               repository,
                               method,
                               kickstart,
                               pxe=pxe,
                               extrapackages=extrapackages,
                               options={"maindisk": dev})

        self._postInstall()

        if start:
            self.start()

        xenrt.TEC().comment("Created %s guest named %s with %u vCPUS and "
                            "%uMB memory."
                            % (self.template, self.name, self.vcpus,
                               self.memory))

        ip = self.getIP()
        if ip:
            xenrt.TEC().logverbose("Guest address is %s" % (ip))

    def installWindows(self, isoname):
        """Install Windows into a VM"""
        self.changeCD(isoname)

        self.hasSSH = not xenrt.TEC().lookup("NOSFU", True, boolean=True)

        # Start the VM to install from CD
        xenrt.TEC().progress("Starting VM %s for unattended install" %
                             (self.name))
        self.lifecycleOperation("vm-start")

        # Monitor ARP to see what IP address it gets assigned and try
        # to SSH to the guest on that address
        vifname, bridge, mac, c = self.vifs[0]
        if self.use_ipv6:
            self.mainip = self.getIPv6AutoConfAddress(vifname)
        else:
            if xenrt.TEC().lookup("EXTRA_ARP_TIME", False, boolean=True):
                arptime = 10800
            else:
                arptime = 7200

            xenrt.sleep(5)

            # get the mac address
            r = re.search(r"<mac address='([^']*)'/>", self._getXML())
            if r:
                mac = r.group(1)
                r2 = re.search(r"<source bridge='([^']*)'/>", self._getXML())
                if r2:
                    bridge = r2.group(1)
                    xenrt.TEC().logverbose("Guest's VIF is on '%s'" % bridge)
                else:
                    bridge = self.host.getDefaultInterface()
                    xenrt.TEC().logverbose("Could not find bridge name in XML; arpwatching on host's default interface")
                xenrt.TEC().progress("Looking for VM IP address on %s using arpwatch." % (bridge))
                self.mainip = self.host.arpwatch(bridge, mac, timeout=arptime)
        if not self.mainip:
            raise xenrt.XRTFailure("Did not find an IP address")
        xenrt.TEC().progress("Found IP address %s" % (self.mainip))
        # In case of IPv6, we need extra time
        if xenrt.TEC().lookup("EXTRA_TIME", self.use_ipv6, boolean=True):
            boottime = 14400
        else:
            boottime = 5400
        if self.hasSSH:
            self.waitForSSH(boottime, desc="Windows final boot")
        else:
            self.waitForDaemon(boottime, desc="Windows final boot")
        time.sleep(120)

        # Wait for c:\\alldone.txt to appear to indicate all post-install
        # actions have completed.
        if not self.hasSSH:
            xenrt.TEC().logverbose("Waiting for c:\\alldone.txt...")
            deadline = xenrt.timenow() + 1200
            while True:
                # Note that we haven't updated the execdaemon yet so
                # there is a risk that the fileExists method isn't available
                # because the baked-in starting daemon is too old. In this
                # case catch the exception and sleep for a bit
                try:
                    alldone = self.xmlrpcFileExists("c:\\alldone.txt")
                except Exception, e:
                    xenrt.TEC().warning("Exception checking for alldone: %s" %
                                        (str(e)))
                    time.sleep(300)
                    break
                if alldone:
                    xenrt.TEC().logverbose(" ... found")
                    break
                if xenrt.timenow() > deadline:
                    raise xenrt.XRTFailure("Timed out waiting for Windows "
                                           "post-install alldone flag")
                time.sleep(60)

        # If we need to install a service pack do it here.
        self.installWindowsServicePack(skipIfNotNeeded=True)

        # Shutdown the VM. This is to match Linux behaviour where
        # install does not necessarily mean start.
        if self.hasSSH:
            try:
                self.execguest("ls %s" % (xenrt.CMD_WIN_SHUTDOWN_EXE),
                               username="Administrator")
                use_shutdown = True
            except:
                use_shutdown = False
        else:
            use_shutdown = False
        if use_shutdown:
            self.execguest(xenrt.CMD_WIN_SHUTDOWN,
                           username="Administrator")
        else:
            time.sleep(120)
            self.xmlrpcUpdate()
            self.xmlrpcShutdown()
        self.poll("DOWN", timeout=360)

    # The normal interface for removeDisk only provides userdevice (0), but we
    # allow the optional use of userdevicename ('sda') here for convenience.
    def removeDisk(self, userdevice=None, keepvdi=False, userdevicename=None):
        if not userdevicename:
            assert type(userdevice) == int
            userdevicename = self._getDiskDevicePrefix() + chr(int(userdevice)+ord('a'))

        oldxmlstr = self._getXML()
        oldxmldom = xml.dom.minidom.parseString(oldxmlstr)
        vdipath = None
        for node in oldxmldom.getElementsByTagName("devices")[0].getElementsByTagName("disk"):
            if node.getAttribute("device") == "disk" and \
               node.getElementsByTagName("target")[0].getAttribute("dev") == userdevicename:
                vdipath = node.getElementsByTagName("source")[0].getAttribute("file")
                node.parentNode.removeChild(node)
                node.unlink()
                break
        else:
            raise xenrt.XRTFailure("Could not unplug disk %s; not already plugged into %s" % (userdevicename, self.name))

        newxmlstr = oldxmldom.toxml()
        self._redefineXML(newxmlstr)

        oldxmldom.unlink()

        if not keepvdi:
            self.host.destroyVDI(vdipath)
        xenrt.TEC().logverbose("Removed %s." % (userdevicename))

    def createDisk(self, sizebytes=None, sruuid=None,
                   userdevice=None, bootable=False,
                   plug=True, vdiuuid=None, returnVBD=False,
                   returnDevice=False,
                   smconfig=None, name=None, format=None,
                   controllerType=None, controllerModel=None):
        """Creates a disk and attaches it to the guest.
        This method should be called when the guest is shut down.

        sizebytes - size in bytes or a string such as 5000MiB or 5GiB
        sruuid - UUID of SR to create disk on
        userdevice - user-specified device number (e.g. 0 maps to "sda", 3 to "sdd" etc, or 0 maps
                     to "sdp" if controller==1)
        bootable - currently unused. To ensure that this disk will be booted from,
                   plug the VDI as userdevice 0 and call self._setBoot(self._getDiskDevicePrefix())
        plug - whether to attach to the guest
        vdiuuid - optionally specify an existing VDI to plug
        returnVBD - unused
        returnDevice - unused
        smconfig - unused
        name - name of the disk, defaults to a random name
        format - disk format, defaults to self.DEFAULT_DISK_FORMAT
        controllerType - the bus on which to put the disk (e.g. scsi), defaults to type of bus 0
        controllerModel - model of the controller (e.g. lsilogic)
        Returns the device number (e.g. a return value of 3 specifies the VDI was attached to hdd)
        """
        # there is no such thing as a VDI uuid in libvirt.
        # use "vdiuuid" as a name instead
        vdiname = vdiuuid

        # Default to local SR.
#        if not sruuid:
#            sruuid = self.getHost().getLocalSR()
#        elif sruuid == "DEFAULT":
#            sruuid = self.getHost().lookupDefaultSR()
        if not sruuid:
            sruuid = self.getHost().lookupDefaultSR()

        if not format:
            format = self.DEFAULT_DISK_FORMAT

        if isinstance(sizebytes, str):
            if sizebytes.endswith("GiB"):
                sizebytes = int(sizebytes[:-3]) * 1024**3
            elif sizebytes.endswith("MiB"):
                sizebytes = int(sizebytes[:-3]) * 1024**2
            else:
                sizebytes = int(sizebytes)

        existingVDI = vdiname
        if not vdiname:
            vdiname = self.getHost().createVDI(sizebytes, sruuid, smconfig, name=name, format=format)

        if plug:
            # Create the VBD.
            userdevicename = self._createVBD(sruuid, vdiname, format, userdevice, controllerType, controllerModel)

        if existingVDI:
            xenrt.TEC().logverbose("Added existing VDI %s as %s." %
                                   (existingVDI, userdevicename))
        else:
            xenrt.TEC().logverbose("Added %s of size %s using SR %s." %
                                   (userdevicename, sizebytes, sruuid))

        return userdevicename

    def createController(self, typ='scsi', model='lsilogic'):
        # Find an unused index for controllers of this type
        oldxmlstr = self._getXML()
        xmldom = xml.dom.minidom.parseString(oldxmlstr)

        highestindex = 0
        for node in xmldom.getElementsByTagName("devices")[0].getElementsByTagName("controller"):
            if node.getAttribute('type') == typ:
                index = int(node.getAttribute('index'))
                if index > highestindex:
                    highestindex = index

        newindex = highestindex + 1

        # Create the new controller
        contxmlstr = "<controller type='%s' index='%s' model='%s'/>" % (typ, newindex, model)
        self._attachDevice(contxmlstr, hotplug=True)

        # Return the index
        return newindex

    def removeController(self, typ='scsi', index=0):
        oldxmlstr = self._getXML()
        xmldom = xml.dom.minidom.parseString(oldxmlstr)

        # iterate over all existing controllers
        for node in xmldom.getElementsByTagName("devices")[0].getElementsByTagName("controller"):
            if node.getAttribute('index') == index:
                node.parentNode.removeChild(node)
                node.unlink()

        self._redefineXML(xmldom.toxml())

    def changeControllerDriver(self, newDriver, typ='scsi', index=None):
        oldxmlstr = self._getXML()
        xmldom = xml.dom.minidom.parseString(oldxmlstr)

        # iterate over all existing controllers to find the one(s) we want
        found = False
        for node in xmldom.getElementsByTagName("devices")[0].getElementsByTagName("controller"):
            if node.getAttribute('type') == typ:
                if index is None or int(node.getAttribute('index')) == index:
                    node.setAttribute('model', newDriver)
                    found = True

        if not found:
            xenrt.TEC().warning("changeControllerDriver couldn't find a controller of type '%s' with index '%s'" % (typ, index))

        self._redefineXML(xmldom.toxml())

    def createVIF(self, eth=None, bridge="NPRI", mac=None):
        if not mac:
            mac = xenrt.randomMAC()
        if not bridge or bridge=="NPRI":
            bridge=self.host.getPrimaryBridge()
        elif bridge == "NSEC":
            raise xenrt.XRTError("Unimplemented")

        model = self._getNetworkDeviceModel()
        vifxmlstr = """
        <interface type='bridge'>
            <mac address='%s'/>
            <source bridge='%s'/>
            %s
        </interface>""" % (mac, bridge, "<model type='%s'/>" % model if model else "")
        self._attachDevice(vifxmlstr)

        if not eth or not eth in [x[0] for x in self.vifs]:
            self.vifs.append((eth, bridge, mac, None))
        else:
            index = [i for i,x in enumerate(self.vifs) if x[0] == eth][0]
            oldeth, oldbridge, oldmac, oldip = self.vifs[index]
            if bridge != oldbridge:
                self.vifs[index] = (oldeth, bridge, oldmac, oldip)

    def removeVIF(self, mac):
        vifxmlstr = """
        <interface type='bridge'>
            <mac address='%s'/>
        </interface>""" % mac
        self._removeDevice(vifxmlstr)
        self.vifs = [vif for vif in self.vifs if vif[2]!=mac]

    def removeVIFs(self, name=None, mac=None, eth=None, ip=None, multiple=False):
        self.vifs=self.getVIFs()
        self.reparseVIFs()
        vifsToRemove= [ vif for vif in self.vifs
                        if (vif[0]==eth or eth==None) and
                        (vif[1]==name or name==None) and
                        (vif[2]==mac or mac==None) and
                        (vif[3]==ip or ip==None) ]
        if len(vifsToRemove)>1 and not multiple:
            raise xenrt.XRTError("More than 1 vif exist matching condition: %s" % vifsToRemove)
        elif len(vifsToRemove)==0:
            xenrt.TEC().warning("No vif exists matching condition")

        for vif in vifsToRemove:
            self.removeVIF(mac=vif[2])

    def removeAllVIFs(self):
        self.removeVIFs(multiple=True)

    def recreateVIFs(self, newMACs = False):
        """Recreate all VIFs we have in the guest's object config"""
        vifs = list(self.vifs)
        self.removeVIFs(multiple=True)
        self.mainip = None
        self.vifs = vifs
        if newMACs:
            for v in self.vifs:
                eth, bridge, mac, ip = v
                self.createVIF(eth, bridge)
            self.reparseVIFs()
            self.vifs.sort()
        else:
            for v in self.vifs:
                eth, bridge, mac, ip = v
                self.createVIF(eth, bridge, mac)

    def getVIFs(self):
        xmlstr = self._getXML()
        xmldom = xml.dom.minidom.parseString(xmlstr)
        reply = {}
        id = 0
        for node in xmldom.getElementsByTagName("devices")[0].getElementsByTagName("interface"):
            if node.getAttribute("type") == "bridge":
                bridge = node.getElementsByTagName("source")[0].getAttribute("bridge")
                nic = self.VIFSTEM + str(id)
                mac = node.getElementsByTagName("mac")[0].getAttribute("address")
                ip = None
                reply[nic] = (mac, ip, bridge)
                id += 1
        xmldom.unlink()
        return reply

    def _baseDeviceForBus(self, busid=0):
        return (ord('p')-ord('a'))*busid + ord('a')

    def _getNextBlockDevice(self, prefix=None, controllerType='scsi', controllerIndex=0):
        if prefix is None:
            prefix = self._getDiskDevicePrefix()

        # TODO we should go to double letters for controllerIndex > 1
        base = self._baseDeviceForBus(busid=controllerIndex)
        maxchar = base-1

        xmlstr = self._getXML()
        xmldom = xml.dom.minidom.parseString(xmlstr)
        # Find all disks on this controller
        for node in xmldom.getElementsByTagName("devices")[0].getElementsByTagName("disk"):
            bus = node.getElementsByTagName("target")[0].getAttribute("bus")
            controller = node.getElementsByTagName("address")[0].getAttribute("controller")
            if controller == '':
                c = 0
            else:
                c = int(controller)
            if controllerType == bus and controllerIndex == c:
                dev = node.getElementsByTagName("target")[0].getAttribute("dev")
                hdchar = dev.strip(prefix)
                if ord(hdchar) > maxchar:
                    maxchar = ord(hdchar)
        userdevice = maxchar+1-base
        return prefix + chr(userdevice+base)

    def _setBoot(self, devicetype):
        """See http://libvirt.org/formatdomain.html#elementsOSBIOS.
        Valid devicetype values are "fd", "hd", "cdrom" or "network"."""

        oldxmlstr = self._getXML()
        oldxmldom = xml.dom.minidom.parseString(oldxmlstr)
        # remove all existing boot elements
        osnode = oldxmldom.getElementsByTagName("os")[0]
        for node in osnode.getElementsByTagName("boot"):
            node.parentNode.removeChild(node)
            node.unlink()
        newnode = oldxmldom.createElement("boot")
        newnode.setAttribute("dev", devicetype)
        osnode.appendChild(newnode)

        newxmlstr = oldxmldom.toxml()
        self._redefineXML(newxmlstr)

        oldxmldom.unlink()

    def _setPVBoot(self, kernel, initrd, cmdline):
        oldxmlstr = self._getXML()
        oldxmldom = xml.dom.minidom.parseString(oldxmlstr)
        # remove all existing boot elements
        osnode = oldxmldom.getElementsByTagName("os")[0]

        # Nodes to delete
        nodes = osnode.getElementsByTagName("boot")
        nodes += osnode.getElementsByTagName("kernel")
        nodes += osnode.getElementsByTagName("initrd")
        nodes += osnode.getElementsByTagName("cmdline")
        for node in nodes:
            node.parentNode.removeChild(node)
            node.unlink()
        if kernel:
            newnode = oldxmldom.createElement("kernel")
            txt = oldxmldom.createTextNode(kernel)
            newnode.appendChild(txt)
            osnode.appendChild(newnode)
        if initrd:
            newnode = oldxmldom.createElement("initrd")
            txt = oldxmldom.createTextNode(initrd)
            newnode.appendChild(txt)
            osnode.appendChild(newnode)
        if cmdline:
            newnode = oldxmldom.createElement("cmdline")
            txt = oldxmldom.createTextNode(cmdline)
            newnode.appendChild(txt)
            osnode.appendChild(newnode)

        newxmlstr = oldxmldom.toxml()
        self._redefineXML(newxmlstr)
        oldxmldom.unlink()

    def changeVIFDriver(self, newDriver):
        oldxmlstr = self._getXML()
        xmldom = xml.dom.minidom.parseString(oldxmlstr)

        # iterate over all existing VIFs
        for node in xmldom.getElementsByTagName("devices")[0].getElementsByTagName("interface"):
            # make the adjustments on the node
            oldmodelnode = node.getElementsByTagName("model")[0]
            node.removeChild(oldmodelnode)
            newmodelstr = "<model type='%s'/>" % (newDriver)
            newmodelxml = xml.dom.minidom.parseString(newmodelstr).documentElement
            node.appendChild(newmodelxml)

        self._redefineXML(xmldom.toxml())

    def changeCD(self, isoname, device=None, absolutePath=False):
        oldxmlstr = self._getXML()
        oldxmldom = xml.dom.minidom.parseString(oldxmlstr)

        includeReadOnly = True

        # find an existing cdrom drive
        for node in oldxmldom.getElementsByTagName("devices")[0].getElementsByTagName("disk"):
            if node.getAttribute("device") == "cdrom":
                targetxml = node.getElementsByTagName("target")[0].toxml()
                changeCDFunction = self._updateDevice
                includeReadOnly = False # sometimes this gets dropped from the device XML, so don't expect it to still be present
                xenrt.TEC().logverbose("not including <readonly/> in xmlstr")
                break
        else:
            # no existing cdrom drive; create a block device name
            device = self._getNextBlockDevice("hd", controllerType="ide")
            targetxml = "<target dev=\"%s\"/>" % device
            changeCDFunction = self._attachDevice
        oldxmldom.unlink()

        if not absolutePath:
            isopath = self.host.getCDPath(isoname) if isoname else ""
        else:
            isopath = isoname

        cdxmlstr  = "<disk type='file' device='cdrom'>"
        cdxmlstr += "<source file='%s'/>" % (isopath, )
        cdxmlstr += targetxml
        if includeReadOnly:
            cdxmlstr += "<readonly/>"
        cdxmlstr += "</disk>"
        xenrt.TEC().logverbose("cdxmlstr = %s" % (cdxmlstr))

        changeCDFunction(cdxmlstr, hotplug=True)

    def removeCD(self, device=None):
        self.changeCD(self, None, device=None)

    def existing(self, host=None):
        """Query an existing guest"""
        if host:
            self.setHost(host)
        host.addGuest(self)

        self.virConn = self.host.virConn
        self.virDomain = self.virConn.lookupByName(self.name)
        self.vcpus = self.cpuget()
        self.memory = self.memget()
        if self.getState() == 'UP':
            if self.mainip:
                self.findPassword()

        if not self.distro:
            self._detectDistro()

        # Get VIF details
        vifs = self.getVIFs()
        devs = vifs.keys()
        devs.sort()
        for nic in devs:
            mac, ip, vbridge = vifs[nic]
            xenrt.TEC().logverbose("Adding VIF %s (%s,%s)" %
                                   (nic, vbridge, mac))
            self.vifs.append((nic, vbridge, mac, ip))
            if self.use_ipv6:
                if not self.mainip or IPy.IP(self.mainip).version() != 6:
                    self.mainip = self.getIPv6AutoConfAddress(device=nic)
            else:
                if not self.mainip or (re.match("169\.254\..*", self.mainip)
                                       and ip and not re.match("169\.254\..*", ip)):
                    self.mainip = ip

        # If the guest is up see if it has an XML-RPC daemon
        if self.getState() == "UP":
            xmlrpcguest = False
            try:
                xenrt.TEC().logverbose("Checking %s for daemon" % (self.name))
                if self.xmlrpcIsAlive():
                    xenrt.TEC().logverbose("Guest %s daemon found" %
                                           (self.name))
                    xmlrpcguest = True
            except socket.error:
                pass
            if xmlrpcguest:
                self.windows = True
                self.hasSSH = False
            else:
                self.windows = False
                self.hasSSH = True
        else:
            xenrt.TEC().logverbose("Guest %s not up to check for daemon" %
                                   (self.name))

    def poll(self, state, timeout=600, level=xenrt.RC_FAIL, pollperiod=5):
        """Poll our VM for reaching the specified state"""
        deadline = xenrt.timenow() + timeout
        while True:
            status = self.getState()
            if state == status:
                return
            if xenrt.timenow() > deadline:
                xenrt.XRT("Timed out waiting for VM %s to be %s" %
                          (self.name, state), level)
            time.sleep(pollperiod)

    def memget(self):
        return self.virDomain.maxMemory() // 1024
    def cpuget(self):
        #return self.virDomain.vcpusFlags(0)
        return self.virDomain.info()[3]

    def memset(self, memory):
        xenrt.TEC().logverbose("Setting %s memory to %uMB" % (self.name, memory))
        self.memory = memory
        # self.virDomain.setMemoryFlags(memory*1024,
        #                               libvirt.VIR_DOMAIN_AFFECT_CONFIG |
        #                               #libvirt.VIR_DOMAIN_AFFECT_LIVE |
        #                               libvirt.VIR_DOMAIN_MEM_MAXIMUM)
        # self.virDomain.setMemoryFlags(memory*1024,
        #                               libvirt.VIR_DOMAIN_AFFECT_CONFIG |
        #                               #libvirt.VIR_DOMAIN_AFFECT_LIVE |
        #                               libvirt.VIR_DOMAIN_MEM_CURRENT)
        xml = self._getXML()
        xml = re.sub(r"<memory.*>.*</memory>", "<memory unit='MiB'>%d</memory>" % memory, xml)
        xml = re.sub(r"<currentMemory.*>.*</currentMemory>", "<currentMemory unit='MiB'>%d</currentMemory>" % memory, xml)
        self._redefineXML(xml)
    def cpuset(self, cpus):
        xenrt.TEC().logverbose("Setting %s vCPUS to %u" % (self.name, cpus))
        self.vcpus = cpus
        # self.virDomain.setVcpusFlags(cpus,
        #                              libvirt.VIR_DOMAIN_AFFECT_CONFIG |
        #                              #libvirt.VIR_DOMAIN_AFFECT_LIVE |
        #                              libvirt.VIR_DOMAIN_VCPU_MAXIMUM)
        # self.virDomain.setVcpusFlags(cpus,
        #                              libvirt.VIR_DOMAIN_AFFECT_CONFIG |
        #                              #libvirt.VIR_DOMAIN_AFFECT_LIVE |
        #                              libvirt.VIR_DOMAIN_VCPU_CURRENT)
        xml = self._getXML()
        xml = re.sub(r"<vcpu.*>.*</vcpu>", "<vcpu>%d</vcpu>" % cpus, xml)
        self._redefineXML(xml)

    def getUUID(self):
        if not self.uuid:
            self.uuid = self.virDomain.UUIDString()
        return self.uuid

    def lifecycleOperation(self,
                           command,
                           force=False,
                           timer=None,
                           remote=None,
                           extraflags=None,
                           timeout=None):
        """Perform a basic VM lifecycle operation"""

        xenrt.TEC().progress("Performing %s on %s" % (command, self.name))

        if timer:
            timer.startMeasurement()

        if command == "vm-start":
            if self._isSuspended():
                raise xenrt.XRTFailure("Cannot start a domain that has been suspended")
            self.virDomain.create()
        elif command == "vm-shutdown":
            if force:
                self.virDomain.destroy()
            else:
                try:
                    self.virDomain.shutdown()
                except libvirt.libvirtError:
                    # probably running on a hypervisor that can't soft-shutdown
                    # without tools, e.g. ESX
                    if self.xmlrpcIsAlive():
                        self.xmlrpcShutdown()
                    else:
                        xenrt.TEC().logverbose("soft shutdown requested but not possible; calling 'sync' before destroying domain")
                        self.execcmd("sync")
                        self.virDomain.destroy()
        elif command == "vm-reboot":
            try:
                self.virDomain.reboot(0)
            except libvirt.libvirtError:
                # probably running on a hypervisor that can't soft-reboot
                # without tools, e.g. ESX
                if self.xmlrpcIsAlive():
                    self.xmlrpcReboot()
                else:
                    self.virDomain.destroy()
                    self.virDomain.create()
        elif command == "vm-suspend":
            self.virDomain.managedSave(0)
        elif command == "vm-resume":
            if not self._isSuspended():
                raise xenrt.XRTFailure("Cannot resume a domain that has not been suspended")
            self.virDomain.create()
        elif command == "vm-pause":
            self.virDomain.suspend()
        elif command == "vm-unpause":
            self.virDomain.resume()
        elif command == "vm-uninstall":
            if self._isSuspended():
                self.virDomain.managedSaveRemove(0)
            xmlstr = self._getXML()
            self.virDomain.undefine()
            xmldom = xml.dom.minidom.parseString(xmlstr)
            for node in xmldom.getElementsByTagName("disk"):
                if node.getAttribute("device") == "disk":
                    vdipath = node.getElementsByTagName("source")[0].getAttribute("file")
                    self.host.destroyVDI(vdipath)
            xmldom.unlink()

        if timer:
            timer.stopMeasurement()


    def start(self, reboot=False):
        if reboot:
            self.lifecycleOperation("vm-reboot")
            time.sleep(20)
        else:
            self.lifecycleOperation("vm-start")

        xenrt.TEC().progress("Waiting for the VM to enter the UP state")
        self.poll("UP")

        xenrt.sleep(5)

        # get the mac address
        r = re.search(r"<mac address='([^']*)'/>", self._getXML())
        if r:
            mac = r.group(1)
            r2 = re.search(r"<source bridge='([^']*)'/>", self._getXML())
            if r2:
                bridge = r2.group(1)
                xenrt.TEC().logverbose("Guest's VIF is on '%s'" % bridge)
            else:
                bridge = self.host.getDefaultInterface()
                xenrt.TEC().logverbose("Could not find bridge name in XML; arpwatching on host's default interface")
            xenrt.TEC().progress("Looking for VM IP address on %s using arpwatch." % (bridge))
            self.mainip = self.getHost().arpwatch(bridge, mac, timeout=300)
            if not self.mainip:
                raise xenrt.XRTFailure("Did not find an IP address.")

        if self.hasSSH:
            self.waitForSSH(600, desc="Guest boot")
        else:
            self.waitForDaemon(600, desc="Guest boot")

        if not self.tailored:
            # Tailor the VM for future test use.
            xenrt.TEC().progress("Tailoring the VM for test use.")
            self.tailor()
            self.tailored = True

    def shutdown(self, force=False, again=False):
        try:
            self.lifecycleOperation("vm-shutdown", force=force)
            self.poll("DOWN")
        except Exception:
            if again:
                self.lifecycleOperation("vm-shutdown", force=True)
            raise

    def reboot(self, force=False, skipsniff=None):
        self.start(reboot=True)

    def suspend(self):
        self.lifecycleOperation("vm-suspend")
        self.poll("SUSPENDED")

    def resume(self, check=True):
        self.lifecycleOperation("vm-resume")
        # TODO: guest clock skew?
        self.poll("UP")
        if check:
            self.check()

    def pause(self):
        self.lifecycleOperation("vm-pause")
        # We use a hack to achieved pausedness in ESX, which isn't reflected in the libvirt domain info used by poll().
        if self.host.productType != "esx":
            self.poll("PAUSED")

    def unpause(self, check=True):
        self.lifecycleOperation("vm-unpause")
        self.poll("UP")

    def uninstall(self):
        if self.getState() == "UP":
            self.lifecycleOperation("vm-shutdown", force=True)
        self.lifecycleOperation("vm-uninstall")
        self.getHost().removeGuest(self)

    def chooseSR(self):
        return self.getHost().lookupDefaultSR()


    ########################################################################
    # Checkpoint/revert methods

    def importVM(self, host, image):
        # TODO This is not right
        dest = "/local/home/test/%s.img" % self.name
        host.execdom0("cp %s %s" % (image, dest))
        host.execvirt("virt-install --name %s --ram %d --disk %s --import --force --noreboot" %
                                (self.name,
                                 self.memory,
                                 dest))
        self.existing(host)
        if self.getState() != "DOWN":
            self.shutdown(force=True)

    #def migrateVM(self, host, live="false", fast=False, timer=None):

    def copyVM(self, name=None, timer=None, sruuid=None):
        return self._cloneCopyVM("copy", name, timer, sruuid)

    def cloneVM(self, name=None, timer=None, sruuid=None):
        if sruuid:
            xenrt.TEC().warning("Deprecated use of sruuid in cloneVM. Should "
                                "use copyVM instead.")
        return self._cloneCopyVM("clone", name, timer, sruuid)

    def _cloneCopyVM(self, operation, name, timer, sruuid):
        if self.getState() == "UP":
            raise xenrt.XRTFailure("Cannot clone a running VM")

        xenrt.TEC().progress("Cloning guest VM %s." % (self.name))

        # get the name
        if name:
            newname = name
        else:
            clonenum = 0
            for name in self.host.listGuests():
                r = re.match(r"%s-clone(\d+).*" % re.escape(self.name), name)
                if r:
                    clonenum = max(clonenum, int(r.group(1)))
            newname = "%s-clone%d" % (self.name, clonenum+1)

        clone = self.host.guestFactory()(newname, template=self.template, host=self.host)

        # clone disks
        xmlstr = self._getXML()
        xenrt.TEC().logverbose("xmlstr=%s" % (xmlstr,))
        xmldom = xml.dom.minidom.parseString(xmlstr)
        for node in xmldom.getElementsByTagName("devices")[0].getElementsByTagName("disk"):
            source = node.getElementsByTagName("source")[0]
            sourcefile = source.getAttribute("file")
            xenrt.TEC().logverbose("sourcefile=%s" % (sourcefile,))
            try:
                #sr can be none if it doesn't have []s (eg. if a cdrom is present)
                #if this is the case, currently we don't clone
                #TODO: what is the proper action if there are no []s in sourcefile?
                sr = self.host.srs[self.host.getSRNameFromPath(sourcefile)]
                xenrt.TEC().logverbose("sr=%s" % (sr,))
                vdiname = sr.getVDINameFromPath(sourcefile)
                xenrt.TEC().logverbose("vdiname=%s" % (vdiname,))

                newdiskname = vdiname.replace(self.name, newname)
                if newdiskname == vdiname:
                    newdiskname = sr.generateCloneName(vdiname)
                if operation == "copy":
                    newdisk = sr.copyVDI(vdiname, newdiskname)
                else:
                    newdisk = sr.cloneVDI(vdiname, newdiskname)
            except Exception, e:
                xenrt.TEC().logverbose("Not cloning disk image %s due to exception %s" % (sourcefile, e))
                newdisk = sourcefile
            source.setAttribute("file", newdisk)

        # create new mac addresses
        for node in xmldom.getElementsByTagName("devices")[0].getElementsByTagName("mac"):
            node.setAttribute("address", xenrt.randomMAC())

        # clone the domain
        xmldom.getElementsByTagName("name")[0].childNodes[0].data = newname
        uuiddom = xmldom.getElementsByTagName("uuid")[0]
        uuiddom.parentNode.removeChild(uuiddom)
        newxmlstr = xmldom.toxml()

        clone._defineXML(newxmlstr)
        clone.existing(self.host)

        xenrt.TEC().progress("Clone %s successful." % (newname))

        return clone

    def snapshot(self, name=None):
        """Perform a snapshot of the VM. This returns the snapshot name."""
        snapshot = self.virDomain.snapshotCreateXML("<domainsnapshot>%s</domainsnapshot>" %
                                                    ("<name>%s</name>" % name if name else ""),
                                                    libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY)
        return snapshot.getName()

    def checkpoint(self, name=None):
        """Perform a checkpoint of the VM. This returns the checkpoint name."""
        snapshot = self.virDomain.snapshotCreateXML("<domainsnapshot>%s</domainsnapshot>" %
                                                    ("<name>%s</name>" % name if name else ""),
                                                    0)
        return snapshot.getName()

    def revert(self, name):
        """Revert to snapshot with name, name."""
        snapshot = self.virDomain.snapshotLookupByName(name, 0)
        self.virDomain.revertToSnapshot(snapshot, 0)

    def removeSnapshot(self, name, force=True):
        """Uninstall the snapshot with name, name."""
        snapshot = self.virDomain.snapshotLookupByName(name, 0)
        snapshot.delete(0)

    #def tailor(self):
    #    pass

    def vendorInstallDevicePrefix(self):
        return self._getDiskDevicePrefix()

    def getIPSpec(self):
        ipSpec = []
        for v in self.vifs:
            (eth, bridge, mac, currentIp) = v
            ipData = self.paramGet("xenrt-ip-%s" % eth)
            (newIP, mask) = ipData.split("/") if ipData else [None, None]
            ipSpec.append((eth, newIP, mask))
        return ipSpec

    def paramSet(self, paramName, paramValue):
        xenrt.TEC().logverbose("WARNING: paramSet called! paramName=%s, paramValue=%s" % (paramName, paramValue))

