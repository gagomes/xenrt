# XenRT: Test harness for Xen and the XenServer product family
#
# Operations on XenServer guests.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, time, random, re, crypt, urllib, os, os.path, socket, copy, IPy
import shutil, traceback, fnmatch, xml.dom.minidom, pipes, uuid
import xenrt
from PIL import Image
from IPy import IP
from xenrt.lazylog import *
from xenrt.lib.scalextreme import SXAgent

# Symbols we want to export from the package.
__all__ = ["Guest",
           "MNRGuest",
           "BostonGuest",
           "TampaGuest",
           "ClearwaterGuest",
           "CreedenceGuest",
           "DundeeGuest",
           "startMulti",
           "shutdownMulti",
           "getTemplate"]

def getTemplate(host, distro, hvm=None, arch=None):
    return host.getTemplate(distro, hvm=hvm, arch=arch)


def isBSODBlue(img):
    pix = img.load()
    blue = 0
    for x in range (img.size[0]):
        for y in range(img.size[1]):
            if pix[x,y] == (0,0,128) or pix[x,y] == (32,104,180):
                            blue += 1
    pc = int((float(blue) / float(img.size[0] * img.size[1])) * 100)
    return pc > 50


class Guest(xenrt.GenericGuest):
    """Encapsulates a single guest VM."""

    VIFSTEM = "eth"
    VIFSTEMPV = "eth"
    VIFSTEMHVM = "eth"
    VIFSTEMSOLPV = "xnf"

    statustext = {'halted'   : 'DOWN',
                  'running'  : 'UP',
                  'suspended': 'SUSPENDED',
                  'paused'   : 'PAUSED'}

    def __init__(self, name, template=None, host=None, password=None, reservedIP=None):
        xenrt.GenericGuest.__init__(self, name, host=host, reservedIP=reservedIP)
        self.template = template
        if self.template and (re.search("[Ww]indows", self.template) or
                              re.search("XenApp", self.template) or
                              re.search("Presentation Server", self.template)):
            self.windows = True
            self.vifstem = self.VIFSTEMHVM
        elif self.template and (re.search("Solaris", self.template)):
            self.windows = False
            self.vifstem = self.VIFSTEMSOLPV
        else:
            self.windows = False
            self.vifstem = self.VIFSTEMPV
        if password:
            self.password = password
        if host and template:
            # Check the template exists
            tuuid = host.parseListForUUID("template-list",
                                                "name-label",
                                                template)
            if tuuid == "":
                xenrt.TEC().logverbose("Cannot find template %s on host" % 
                                       (template))
            else:

                # Set the default memory and CPUs to the template defaults
                v = int(host.parseListForOtherParam("template-list",
                                                    "name-label",
                                                    template,
                                                    "VCPUs-at-startup"))
                m = int(host.parseListForOtherParam("template-list",
                                                    "name-label",
                                                    template,
                                                    "memory-static-max"))
                m = m / xenrt.MEGA
                xenrt.TEC().logverbose("Using template defaults %uMB, "
                                       "%u CPU(s)" % (m, v))
                self.memory = m
                self.vcpus = v

        self.tailored = False
        self.uuid = None
        self.use_ipv6 = xenrt.TEC().lookup('USE_GUEST_IPV6', False, boolean=True)
        self.memory = None # Default to template memory.
        self.vcpus = None # Default to template vcpus.

    def _osParent_ejectIso(self):
        self.changeCD(None)

    def _osParent_setIso(self, isoName, isoRepo=None):
        self.changeCD(isoName)

    def rebootAsync(self):
        self.host.execdom0("xe vm-reboot uuid=%s >/dev/null 2>&1 </dev/null &" % (self.getUUID()))

    def _checkPVAddonsInstalled(self):
        """This is require by waitForAgent to check for host license from Dundee onwards """
        return False

    def populateSubclass(self, x):
        xenrt.GenericGuest.populateSubclass(self, x)
        x.template = self.template
        x.windows = self.windows
        # Always reset vifstem on upgraded VMs
        x.vifstem = x.VIFSTEM

    DEFAULT = -10

    def builtInGuestAgent(self):
        distro = getattr(self, 'distro', None)
        return distro and distro in string.split(self.getHost().lookup("BUILTIN_XS_GUEST_AGENT", ""), ",")

    def getCLIInstance(self):
        return self.getHost().getCLIInstance()

    @property
    def xapiObject(self):
        """Gets a XAPI VM object for this Guest
        @return: A xenrt.lib.xenserver.VM object for this Guest
        @rtype: xenrt.lib.xenserver.VM"""
        return xenrt.lib.xenserver.VM(self.getCLIInstance(), self.uuid)

    def getAllowedOperations(self):

        """
        Get a list of the allowed operations for a guest
        @rtype: list
        @return: strings denoting the allowed operations of a guest
        """
        return self.paramGet("allowed-operations").strip().split("; ")

    def determineDistro(self):
        """ Try find installed distro. """

        # use distro from other-config field if VM was created by XenRT
        if not self.distro:
            try:
                self.distro = self.paramGet("other-config", "xenrt-distro")
            except:
                pass

        # Have a go at working out the distro.
        if not self.distro:
            try:
                os = self.getHost().parseListForParam("vm-list",
                                                      self.getUUID(),
                                                      "os-version")
                d = {}
                for entry in [ re.split(":", i) for i in \
                               re.split(";", re.sub(" ", "", os)) ]:
                    d[entry[0]] = entry[1]
                if d["name"] == "rhel" or d["distro"] == "rhel":
                    if d["major"] == "4":
                        if d["minor"] == "1":
                            self.distro = "rhel41"
                        elif d["minor"] == "4":
                            self.distro = "rhel44"
                        elif d["minor"] == "5":
                            self.distro = "rhel45"
                    elif d["major"] == "5":
                        self.distro = "rhel5"
                elif d["name"] == "debian" or d["distro"] == "debian":
                    if d["major"] == "4":
                        self.distro = "etch"
                    elif re.search(r"^\d+$", d["major"]):
                        try:
                            major = int(d["major"])
                            if major >= 5:
                                minor = int(d["minor"])
                                self.distro = "debian%u%u" % (major, minor)
                            else:
                                self.distro = "debian"
                        except:
                            self.distro = "debian"
                    else:
                        self.distro = "debian"
                elif re.search(r"indows", d["name"]) or \
                        re.search(r"indows", d["distro"]):
                    self.windows = True
                    self.vifstem = self.VIFSTEMHVM
                    if re.search(r"2000", d["name"]):
                        self.distro = "w2k"
                    elif re.search(r"2003", d["name"]):
                        self.distro = "w2k3"
                    elif re.search(r"XP", d["name"]):
                        self.distro = "winxp"
                    elif re.search(r"2008 R2", d["name"]):
                        self.distro = "ws08r2"
            except:
                pass

        return self.distro

    def existing(self, host):
        self.setHost(host)
        host.addGuest(self)
        self.enlightenedDrivers = True 

        # Get basic guest details
        self.vcpus = self.cpuget()
        self.memory = self.memget()
        if self.windows or self.checkWindows():
            self.windows = True
            self.vifstem = self.VIFSTEMHVM

        if not self.distro:
            self.determineDistro()

        # If we've still not got it, try some heuristics
        if not self.distro and string.lower(self.getName()[0]) == "w":
            self.windows = True

        if not self.windows:
            if self.password is None or self.password.strip() == "":
                self.password = xenrt.TEC().lookup("ROOT_PASSWORD")

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

        if self.mainip and re.match("169\.254\..*", self.mainip):
            xenrt.TEC().warning("VM gave itself a link-local address.")

        # If the guest is up see if it has an XML-RPC daemon
        if self.getState() == "UP":
            try:
                xenrt.TEC().logverbose("Checking %s for daemon" % self.name)
                if self.xmlrpcIsAlive():
                    xenrt.TEC().logverbose("Guest %s daemon found" % self.name)
                    self.windows = True
            except socket.error:
                pass
        else:
            xenrt.TEC().logverbose("Guest %s not up to check for daemon" % self.name)
        
        if not self.arch:
            if self.getState() == "UP":
                if not self.windows:
                    try:
                        if self.execguest("uname -i").strip() == "x86_64":
                            self.arch = "x86-64"
                        else:
                            self.arch = "x86-32"
                    except Exception, e:
                        xenrt.TEC().logverbose("Could not determine architecture - %s" % str(e))
                else:
                    try:
                        if self.xmlrpcGetArch() == "amd64":
                            self.arch = "x86-64"
                        else:
                            self.arch = "x86-32"
                    except:
                        xenrt.TEC().logverbose("Could not determine architecture")


    def wouldBootHVM(self):
        return (self.paramGet("HVM-boot-policy") == "BIOS order")

    def isHVMLinux(self, distro=None):
        if not distro:
            distro=self.distro
        hvms = self.getHost().lookup("HVM_LINUX", None)
        if distro and hvms:
            for d in hvms.split(","):
                if re.match(d, distro):
                    return True
        return False

    def isNonBalloonablePVLinux(self):
        """Return True if pv-ops guest cannot balloon above initial dynamic-min.
        Checks if distro exists in nonBalloonablePvLinux list
        @return: boolean.
        """
        nonBalloonablePvLinux = ["rhel5","rhel6","centos5","centos6","sl5","sl6","oel5","oel6","debian60"]
        for d in nonBalloonablePvLinux:
            if re.match(d, self.distro):
                return True
        return False


    def isUncooperative(self):
        """Check if guest has been marked uncooperative.
        Reads xenstore entry memory/uncooperative for the given domain
        @return: boolean. True if uncooperative, else False
        """
        if self.windows:
            raise xenrt.XRTError("Unimplemented")
        else:
            if self.getHost().xenstoreExists("/local/domain/%s/memory/uncooperative" % self.getDomid()):
                return True
        return False


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
                pxe=False,
                sr=None,
                extrapackages=None,
                notools=False,
                extradisks=None,
                bridge=None,
                use_ipv6=False,
                rawHBAVDIs=None):
        self.setHost(host)

        #If guest is HVM Linux PXE has to be true
        if distro and (self.isHVMLinux(distro) or distro.startswith("solaris")):
            pxe = True
            xenrt.TEC().logverbose("distro is %s, hence setting pxe to %s"%(distro,pxe))


        # Workaround NOV-1 - SLES 11SP2 installer needs at least 2GB RAM
        if distro and distro=="sles112" and ((self.memory and self.memory<4096) or not self.memory):
            self.memory=4096

        # Workaround # RHEL/CentOS/OEL 6 or later requires at least 1G ram.
        if distro:
            m = re.match("(rhel|centos|oel|sl)[dw]?(\d)\d*", distro)
            if (m and int(m.group(2)) >= 6) or distro.startswith("fedora"):
                if (self.memory and self.memory<1024) or not self.memory:
                    self.memory = 1024
                                        
        # Hack to avoid using an ISO install for Debian VMs from TCMultipleVDI
        # etc.
        if distro and (distro in ["etch", "sarge"] or "debian5" in distro):
            isoname = None

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
            cds = host.minimalList("cd-list", "name-label")
            trylist = ["%s_xenrtinst.iso" % (isostem), "%s.iso" % (isostem)]

            if distro == "w2k3eesp2pae":
                trylist.append("w2k3eesp2.iso")

            if arch:
                trylist.append("%s_%s.iso" % (isostem, arch))
                trylist.append("%s_%s_xenrtinst.iso" % (isostem, arch))
            isoname = None
            for tryit in trylist:
                if tryit in cds:
                    isoname = tryit
                    break
            if not isoname:
                raise xenrt.XRTError("Could not find a suitable ISO for %s "
                                     "(arch %s)" % (distro, arch))

        self.isoname = isoname
        if self.isoname:
            minRootDisk = xenrt.TEC().lookup(["GUEST_LIMITATIONS", self.isoname, "MIN_ROOTDISK"], None)
            minRootDiskDiff = xenrt.TEC().lookup(["GUEST_LIMITATIONS",self.isoname,"MIN_ROOTDISK_MEMORY_DIFF"], 0)
            if self.memory and minRootDisk:
                if rootdisk == self.DEFAULT:
                    rootdisk = max(minRootDisk , minRootDiskDiff + self.memory)
                else:
                    rootdisk = max(minRootDisk , minRootDiskDiff + self.memory, rootdisk)
                xenrt.TEC().logverbose("Increasing root disk to %d" % rootdisk)

        if distro:
            self.distro = distro
        host.addGuest(self)
        cli = self.getCLIInstance()

        if use_ipv6: # if this was set to True, override the global flag.
            self.use_ipv6 = True

        # IPv6 support for w2k3 and winxp is flakey
        if distro and re.search("w2k|xp", distro) and use_ipv6:
            xenrt.TEC().logverbose("For windows guests, IPv6 is supported from Vista onwards.")
            raise  xenrt.XRTFailure("IPv6 is not supported for the distro %s" % distro)

        if vifs:
            self.vifs = vifs

        if pxe:
            self.vifstem = self.VIFSTEMHVM

        # Prepare VIFs
        if type(vifs) == type(self.DEFAULT):
            if bridge:
                br = bridge
            else:
                br = host.getPrimaryBridge()
                if not br:
                    raise xenrt.XRTError("Host has no bridge")
            self.vifs = [("%s0" % (self.vifstem), br, xenrt.randomMAC(), None)]
            if not vifs == self.DEFAULT:
                nwuuid = host.createNetwork()
                bridge = host.genParamGet("network", nwuuid, "bridge")
                for i in range(vifs - 1):
                    self.vifs.append(("%s%d" % (self.vifstem, i + 1), bridge, xenrt.randomMAC(), None))

        if self.windows:
            if len(self.vifs) == 0:
                raise xenrt.XRTError("Need at least one VIF to install Windows")
        if repository:
            if len(self.vifs) == 0:
                raise xenrt.XRTError("Need at least one VIF to install with "
                                     "vendor installer")

        # Choose a storage respository
        sruuid = self.chooseSR(sr)
        # Contruct the VM
        vifsdone = False
        # Install from a template
        if not self.windows and not repository:
            ni = True
        else:
            ni = False
        r = re.search(r"([\d\.]+)", self.template)
        if r:
            vers = float(r.group(1))
        else:
            vers = 0.0
        self.createGuestFromTemplate(self.template, 
                                     sruuid, 
                                     ni=ni,
                                     guestparams=guestparams, 
                                     rootdisk=rootdisk)

        if self.isHVMLinux() and self.template == "Other install media" and rootdisk == self.DEFAULT:
            rootdisk = 8096
        # Attaching root disk and extra disks for LUN Per VDI guests.
        if rawHBAVDIs:
            xenrt.TEC().logverbose("Attaching a list of VDIs %s to LUN Per VDI VM %s" % (rawHBAVDIs, self.getUUID()))
            for lunperVDI in rawHBAVDIs:
                args = []
                # Default to lowest available device number.
                allowed = self.getHost().genParamGet("vm", self.getUUID(), "allowed-VBD-devices")
                userdevice = str(min([int(x) for x in allowed.split("; ")]))
                args.append("device=%s" % (userdevice))
                args.append("vdi-uuid=%s" % (lunperVDI))
                args.append("vm-uuid=%s" % (self.getUUID()))
                args.append("mode=RW")
                args.append("type=Disk")
                if (userdevice == "0"):
                    args.append("bootable=true") # if root disk only.
                rawvbduuid = cli.execute("vbd-create", string.join(args), strip=True)

        # This is just in case it has autostarted
        xenrt.sleep(5)
        try:
            if self.getState() != "DOWN":
                cli.execute("vm-shutdown",
                            "--force vm-name=\"%s\"" % (self.name))
        except:
            pass

        # Add VIFs
        if not vifsdone:
            for v in self.vifs:
                eth, bridge, mac, ip = v
                self.createVIF(eth, bridge, mac)

        # Resize root disk if necessary
        if not rawHBAVDIs:
            if not xenrt.TEC().lookup("OPTION_CLONE_TEMPLATE", False, boolean=True):
                if rootdisk != self.DEFAULT:
                    # Handle the case where there is no existing rootdisk (CA-60974)
                    if not self.hasRootDisk():
                        self.createDisk(sizebytes=int(rootdisk)*xenrt.MEGA, bootable=True)
                    rootdiskid, size, min_size, function, qos = \
                                self.getRootDiskDetails()
                    if rootdisk < size:
                        xenrt.TEC().warning("Unable to shrink root disk from"
                                            " %uMB to %uMB" % (size, rootdisk))
                    else:
                        self.resizeDisk(rootdiskid, rootdisk)
                        xenrt.TEC().logverbose("Resized root disk to %uMB" %
                                               (rootdisk))

        # Add any extra disks.
        if not rawHBAVDIs:
            if extradisks:
                for size in extradisks:
                    self.createDisk(sizebytes=int(size)*xenrt.MEGA)

        # Windows needs to install from a CD
        if self.windows:
            if xenrt.TEC().lookup("WORKAROUND_CA28908", False, boolean=True) \
                   and ("win7" in distro or "ws08r2" in distro):
                xenrt.TEC().warning("Using CA-28908 workaround - "
                                    "disabling viridian flag")
                self.paramSet("platform:viridian", "false")
            if xenrt.TEC().lookup("FORCE_NX_DISABLE", False, boolean=True):
                self.paramSet("platform:nx", "false")
            self.installWindows(self.isoname)
        elif distro and "coreos-" in distro:
            self.enlightenedDrivers=True
            notools = True # CoreOS has tools installed already
            self.installCoreOS()
        elif repository and not isoname:
            dev = "%sa" % (self.vendorInstallDevicePrefix())
            options={"maindisk": dev}
            nfsdir = None
            nfssr = None
            if pxe:
                try:
                    self.insertToolsCD()
                except:
                    pass

            # Install using the vendor installer.
            self.installVendor(distro,
                               repository,
                               method,
                               kickstart,
                               pxe=pxe,
                               extrapackages=extrapackages,
                               options=options)
            if nfssr:
                nfssr.forget()
                nfsdir.remove()
        elif isoname:
            xenrt.TEC().logverbose("Installing Linux from ISO...")
            dev = "%sa" % (self.vendorInstallDevicePrefix())
            cli = self.getCLIInstance() 
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

        # store the distro so it can be used when using --existing or --pool
        if self.distro:
            self.paramSet("other-config:xenrt-distro", self.distro)

        # eject the CD, it's no longer needed
        self.changeCD(None)

        if start:
            self.start()

        xenrt.TEC().comment("Created %s guest named %s with %u vCPUS and "
                            "%uMB memory."
                            % (self.template, self.name, self.vcpus,
                               self.memory))
        ip = self.getIP()
        if ip:
            xenrt.TEC().logverbose("Guest address is %s" % (ip))

        if not notools and self.getState() == "UP":
            self.installTools()
        if self.special.get("XSKernel"):
            kernelUpdatesPrefix = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "") + "/kernelUpdates"
            if distro and distro == 'oel7':
                _new_kernel = kernelUpdatesPrefix + "/OEL7/"
                _new_kernel_path = ["kernel-uek-firmware-3.8.13-36.3.1.el7uek.xs.x86_64.rpm",
                                    "kernel-uek-3.8.13-36.3.1.el7uek.xs.x86_64.rpm",
                                    "kernel-uek-devel-3.8.13-36.3.1.el7uek.xs.x86_64.rpm"]
                for kernelFix in _new_kernel_path:
                    xenrt.TEC().logverbose("wget %s/%s"%(_new_kernel,kernelFix))
                    self.execcmd("wget %s/%s"%(_new_kernel,kernelFix))
                    self.execcmd("rpm -ivh --force %s"%(kernelFix))
                tempRoot = self.execcmd("grep -Eo 'root=UUID=[0-9a-f-]+' /boot/grub2/grub.cfg | head -n 1").split('\n')[0]
                self.execcmd("sed -i 's^root=/dev/mapper/VolGroup-lv_root^%s^' /boot/grub2/grub.cfg"%(tempRoot))
            elif distro and distro == 'oel71':
                _new_kernel = kernelUpdatesPrefix + "/OEL74/"
                _new_kernel_path = ["kernel-uek-firmware-3.8.13-55.1.5.el7uek.xs.x86_64.rpm",
                                    "kernel-uek-3.8.13-55.1.5.el7uek.xs.x86_64.rpm",
                                    "kernel-uek-devel-3.8.13-55.1.5.el7uek.xs.x86_64.rpm"]
                for kernelFix in _new_kernel_path:
                    xenrt.TEC().logverbose("wget %s/%s"%(_new_kernel,kernelFix))
                    self.execcmd("wget %s/%s"%(_new_kernel,kernelFix))
                    self.execcmd("rpm -ivh --force %s"%(kernelFix))
            elif distro and distro in ['rhel7','centos7']:
                _new_kernel = kernelUpdatesPrefix + "/RHEL7/"
                _new_kernel_path = ["kernel-devel-3.10.0-123.20.1.el7.xs.x86_64.rpm",
                                    "kernel-3.10.0-123.20.1.el7.xs.src.rpm",
                                    "kernel-3.10.0-123.20.1.el7.xs.x86_64.rpm",
                                    "kernel-headers-3.10.0-123.20.1.el7.xs.x86_64.rpm"]
                for kernelFix in _new_kernel_path:
                    xenrt.TEC().logverbose("wget %s/%s"%(_new_kernel,kernelFix))
                    self.execcmd("wget %s/%s"%(_new_kernel,kernelFix))
                    self.execcmd("rpm -ivh --force %s"%(kernelFix))
            elif distro and distro in ['rhel71','centos71']:
                _new_kernel = kernelUpdatesPrefix + "/RHEL71/"
                _new_kernel_path = ["kernel-devel-3.10.0-229.1.2.el7.xs.x86_64.rpm",
                                    "kernel-3.10.0-229.1.2.el7.xs.src.rpm",
                                    "kernel-3.10.0-229.1.2.el7.xs.x86_64.rpm",
                                    "kernel-headers-3.10.0-229.1.2.el7.xs.x86_64.rpm"]
                for kernelFix in _new_kernel_path:
                    xenrt.TEC().logverbose("wget %s/%s"%(_new_kernel,kernelFix))
                    self.execcmd("wget %s/%s"%(_new_kernel,kernelFix))
                    self.execcmd("rpm -ivh --force %s"%(kernelFix))
            else:
                raise xenrt.XRTError("XSKernel requested, but not available for this distro (%s)" % distro)
            del self.special['XSKernel']
            self.reboot()

    def installCoreOS(self):
        self.host.installContainerPack()
        self.changeCD("%s.iso" % self.distro)
        host = self.getHost()
        templateName = host.getTemplate(self.distro)
        templateUUID = host.minimalList("template-list", args="name-label='%s'" % templateName)[0]
        cli = self.getCLIInstance()
        config = cli.execute("host-call-plugin host-uuid=%s plugin=xscontainer fn=get_config_drive_default args:templateuuid=%s" % (host.uuid, templateUUID)).rstrip().lstrip("True")
        self.password = xenrt.TEC().lookup("ROOT_PASSWORD")
        passwd = crypt.crypt(self.password, '$6$SALT$')
        proxy = xenrt.TEC().lookup("HTTP_PROXY")
        
        config += """
  - path: /etc/systemd/system/docker.service.d/http-proxy.conf
    owner: core:core
    permissions: 0644
    content: |
      [Service]
      Environment="HTTP_PROXY=http://%s" """ % proxy
        
        config += """
users:
  - name: root
    passwd: %s
""" % (passwd)
        config = config.replace("\n", "%BR%")
        cli.execute("host-call-plugin host-uuid=%s plugin=xscontainer fn=create_config_drive args:vmuuid=%s args:sruuid=%s args:configuration=%s" % (host.uuid, self.uuid, self.chooseSR(), pipes.quote(config)))
        self.lifecycleOperation("vm-start")
        # Monitor ARP to see what IP address it gets assigned and try
        # to SSH to the guest on that address
        vifname, bridge, mac, c = self.vifs[0]

        if self.reservedIP:
            self.mainip = self.reservedIP
        elif self.use_ipv6:
            self.mainip = self.getIPv6AutoConfAddress(vifname)
        else:
            arptime = 10800
            self.mainip = self.getHost().arpwatch(bridge, mac, timeout=arptime)

        if not self.mainip:
            raise xenrt.XRTFailure("Did not find an IP address")

        self.waitForSSH(600, "CoreOS ISO boot")

        channel = self.distro.split("-")[-1]
        
        self.execguest("http_proxy=http://%s coreos-install -d /dev/xvda -V current -C %s -o xen" % (proxy, channel))

        self.shutdown()

    def installWindows(self, isoname):
        """Install Windows into a VM"""
        if xenrt.TEC().lookup("WINPE_GUEST_INSTALL", False, boolean=True):
            winpe = WinPE(self, "amd64" if isoname.endswith("-x64.iso") else "x86")
            winpe.boot()
            self.changeCD("xs-tools.iso")
            xenrt.TEC().logverbose("WinPE booted, mounting shares")
            customIso = xenrt.TEC().lookup("CUSTOM_WINDOWS_ISO", None)
            tailorMount = xenrt.mountStaticISO(isoname[:-4])
            if customIso:
                isoMount = xenrt.mountStaticISO(isoname[:-4], filename=customIso)
            else:
                isoMount = tailorMount
            nfsdir = xenrt.NFSDirectory()
            xenrt.command("ln -sfT %s %s/iso" % (isoMount, nfsdir.path()))

            os.makedirs("%s/custom" % nfsdir.path())
            customUnattend = xenrt.TEC().lookup("CUSTOM_UNATTEND_FILE", None)
            if customUnattend:
                xenrt.GEC().filemanager.getSingleFile(customUnattend, "%s/custom/Autounattend.xml" % nfsdir.path())
            else:
                shutil.copy("%s/Autounattend.xml" % tailorMount, "%s/custom/Autounattend.xml" % nfsdir.path())

                xenrt.command("""sed -i "s#<CommandLine>.*</CommandLine>#<CommandLine>c:\\\\\\\\install\\\\\\\\runonce.cmd</CommandLine>#" %s/custom/Autounattend.xml""" % nfsdir.path())
            
            shutil.copytree("%s/$OEM$" % tailorMount, "%s/custom/oem" % nfsdir.path())
            xenrt.command("chmod u+w %s/custom/oem/\\$1/install" % nfsdir.path())

            with open("%s/custom/oem/$1/install/runonce.cmd" % nfsdir.path(), "w") as f:
                f.write("%systemdrive%\install\python\python.cmd\r\n")
                f.write("EXIT\r\n")
            winpe.xmlrpc.exec_shell("net use y: %s\\iso" % nfsdir.getCIFSPath()) 
            winpe.xmlrpc.exec_shell("net use z: %s\\custom" % nfsdir.getCIFSPath()) 
            xenrt.TEC().logverbose("Starting installer")
            # Mount the install share and start the installer
            winpe.xmlrpc.start_shell("y:\\setup.exe /unattend:z:\\autounattend.xml /m:z:\\oem")
        else:
            self.changeCD(isoname)

            # Start the VM to install from CD
            xenrt.TEC().progress("Starting VM %s for unattended install" % self.name)

            self.lifecycleOperation("vm-start")

        # Monitor ARP to see what IP address it gets assigned and try
        # to SSH to the guest on that address
        vifname, bridge, mac, c = self.vifs[0]

        if self.reservedIP:
            self.mainip = self.reservedIP
        elif self.use_ipv6:
            self.mainip = self.getIPv6AutoConfAddress(vifname)
        else:
            arptime = 10800
            self.mainip = self.getHost().arpwatch(bridge, mac, timeout=arptime)

        if not self.mainip:
            raise xenrt.XRTFailure("Did not find an IP address")

        xenrt.TEC().progress("Found IP address %s" % (self.mainip))
        boottime = 14400
        autologonRetryCount = 5
        for i in range(autologonRetryCount): 
            try:
                self.waitForDaemon(boottime, desc="Windows final boot")
                break
            except Exception, ex:
                if "failed to autologon" in str(ex) and i < autologonRetryCount -1:
                    self.shutdown(force=True)
                    self.lifecycleOperation("vm-start")
                    xenrt.sleep(60)
                else:
                    raise
        # Remove any autologin failure screenshot that we may have saved - bootfail.jpg
        try:
            os.remove("%s/bootfail.jpg"%(xenrt.TEC().getLogdir()))
        except:
            pass

        xenrt.sleep(120)

        # Wait for c:\\alldone.txt to appear to indicate all post-install
        # actions have completed.
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
                xenrt.TEC().warning("Exception checking for alldone: %s" % str(e))
                xenrt.sleep(300)
                break
            if alldone:
                xenrt.TEC().logverbose(" ... found")
                break
            if xenrt.timenow() > deadline:
                raise xenrt.XRTFailure("Timed out waiting for Windows post-install alldone flag")
            xenrt.sleep(60)

        # If we need to install a service pack do it here.
        self.installWindowsServicePack(skipIfNotNeeded=True)

        # Shutdown the VM. This is to match Linux behaviour where
        # install does not necessarily mean start.
        xenrt.sleep(120)
        self.xmlrpcUpdate()
        self.xmlrpcShutdown()
        self.poll("DOWN", timeout=720)

    def insertToolsCD(self):
        isos = self.getHost().findISOs()
        if self.windows:
            pats = string.split(xenrt.TEC().lookup("TOOLS_CD_NAMES_WINDOWS"))
        else:
            pats = string.split(xenrt.TEC().lookup("TOOLS_CD_NAMES_LINUX"))
        for cdpattern in pats:
            cdnames = fnmatch.filter(isos, cdpattern)
            if cdnames and len(cdnames) > 0:
                if self.distro and \
                    (re.search("debian\d+", self.distro) or \
                    re.search("rhel[dw]?6", self.distro) or \
                    re.search("oel6", self.distro) or \
                    re.search("sl6", self.distro) or \
                    re.search("centos6", self.distro) or \
                    re.search("ubuntu", self.distro)):
                    self.changeCD(cdnames[0], device="3")
                else:
                    self.changeCD(cdnames[0])
                return cdnames[0]
        raise xenrt.XRTError("Could not find tools ISO to insert")

    def getPacketCount(self, vif):
        vif = self.host.execdom0("xenstore-read /xapi/%d/hotplug/vif/%d/vif" %
                                 (self.getDomid(), vif)).strip()
        data = self.host.execdom0("ifconfig %s" % (vif))
        transmit = int(re.search("TX packets:(?P<transmit>[0-9]+)", data).group("transmit"))
        receive = int(re.search("RX packets:(?P<receive>[0-9]+)", data).group("receive"))
        xenrt.TEC().logverbose("Packet counts for %s. RX: %d TX: %d" % (vif, receive, transmit))
        return (transmit, receive)

    def poll(self, state, timeout=600, level=xenrt.RC_FAIL, pollperiod=15):
        """Poll our VM for reaching the specified state"""
        deadline = xenrt.timenow() + timeout
        while 1:
            status = self.getState()
            if state == status:
                return
            if xenrt.timenow() > deadline:
                xenrt.XRT("Timed out waiting for VM %s to be %s" %
                          (self.name, state), level)
            xenrt.sleep(15, log=False)

    def start(self, reboot=False, skipsniff=False, specifyOn=True,\
              extratime=False, managenetwork=None, managebridge=None, 
              forcedReboot=False, timer=None):
        # Start the VM
        if reboot:
            xenrt.TEC().progress("Rebooting guest VM %s" % (self.name))
            if self.enlightenedDrivers or forcedReboot:
                self.lifecycleOperation("vm-reboot",specifyOn=specifyOn, force=forcedReboot)
            else:
                domid = self.getDomid()
                self.unenlightenedReboot()
                # Wait for the domid to change
                startTime = xenrt.util.timenow()
                while True:
                    try:
                        if self.getDomid() != domid:
                            break
                    except:
                        # There is a tiny window where the domid may not exist while the reboot occurs
                        pass
                    if (xenrt.util.timenow() - startTime) > 600:
                        raise xenrt.XRTError("domid failed to change 10 minutes after an unenlightenedReboot")
                    xenrt.sleep(10)
            xenrt.sleep(20)
        else:
            xenrt.TEC().progress("Starting guest VM %s" % (self.name))
            self.lifecycleOperation("vm-start",specifyOn=specifyOn,timer=timer)

        self.waitReadyAfterStart(skipsniff, extratime, managenetwork, managebridge)

    def waitReadyAfterStart(self, skipsniff=False, extratime=False,\
                            managenetwork=None, managebridge=None):

        # we should be able to wipe previous setting by giving
        # managenetwork/bridge = False arguments

        if managenetwork is not None:
            self.managenetwork = managenetwork
        if managebridge is not None:
            self.managebridge = managebridge

        # Wait for the VM to come up.
        xenrt.TEC().progress("Waiting for the VM to enter the UP state")
        self.poll("UP", pollperiod=1)

        # Workaround for PCI passthrough buggy option ROM to send a key
        if self.special.get("sendbioskey"):
            xenrt.sleep(10)
            self.sendVncKeys([0xff0d])

        vifs = ((self.managenetwork or self.managebridge)
                and self.getVIFs(network=self.managenetwork, bridge=self.managebridge).keys()
                or map(lambda v: v[0], self.vifs))
        xenrt.TEC().progress("Get all vifs %s" % vifs)

        # Look for an IP address on the first interface (if we have any)
        if len(vifs) > 0:
            if self.enlightenedDrivers or self.builtInGuestAgent():
                xenrt.sleep(30)
                xenrt.TEC().progress("Looking for VM IP address using CLI")
                tries = 0
                while 1:
                    tries = tries + 1

                    vifname = vifs[0]
                    try:
                        mac, ip, vbridge = self.getVIF(vifname)
                        if self.use_ipv6:
                            if not self.mainip or IPy.IP(self.mainip).version() != 6:
                                self.mainip = self.getIPv6AutoConfAddress(vifname)
                            break
                        elif ip:
                            if re.match("169\.254\..*", ip):
                                raise xenrt.XRTFailure("VM gave itself a link-local address.")
                            if ip == "0.0.0.0":
                                raise xenrt.XRTFailure("VM claims to have IP address 0.0.0.0")
                            if ip == "255.255.255.255":
                                raise xenrt.XRTFailure("VM claims to have IP address 255.255.255.255")
                            self.mainip = ip
                            break
                    except Exception, e:
                        xenrt.TEC().logException(e)
                    # Check the VM is still running
                    if self.getState() != "UP":
                        self.checkHealth(noreachcheck=True, desc="VM Start, waiting for IP address")
                        raise xenrt.XRTFailure("VM no longer running while  waiting for IP address")
                    if xenrt.TEC().lookup("EXTRA_TIME", False, boolean=True) or extratime:
                        max_tries = 200
                    else:
                        max_tries = 30
                    if tries == max_tries:
                        self.checkHealth(desc="VM Start, waiting for IP address")

                        try:
                            xenrt.command("sudo zgrep '%s' /var/log/syslog*" % mac)
                        except:
                            pass
                        raise xenrt.XRTFailure("No IP address found for %s" % (vifname))
                    xenrt.sleep(30, log=False)
            else:
                if self.managenetwork or self.managebridge:
                    mac, ip, bridge = self.getVIFs(network=self.managenetwork, bridge=self.managebridge).values()[0]
                elif xenrt.TEC().lookup("ARPWATCH_PRIMARY", False, boolean=True):
                    mac, ip, bridge =  self.getVIF(bridge = self.getHost().getPrimaryBridge())
                else:
                    vifname, bridge, mac, _ = (v for v in self.vifs if v[0] == vifs[0]).next()

                if self.use_ipv6:
                    if not self.mainip or IPy.IP(self.mainip).version() != 6:
                        self.mainip = self.getIPv6AutoConfAddress(vifname)
                    skipsniff = True
                else:
                    xenrt.TEC().progress("Looking for VM IP address using arpwatch.")
                if self.mainip and skipsniff:
                    # Don't tcpdump, assume the same address
                    pass
                else:
                    try:
                        if self.reservedIP:
                            self.mainip = self.reservedIP
                        else:
                            if not self.windows and \
                                   self.paramGet("HVM-boot-policy") == "BIOS order" and \
                                   'n' in self.paramGet("HVM-boot-params", "order") and \
                                   not xenrt.TEC().lookup("DHCP_IGNORE_UIDS", False, boolean=True):
                                # HVM Linux detected. ARP watch cannot be used as multiple IP addresses are present."
                                xenrt.TEC().logverbose("Waiting 20 mins, then checking DHCP leases to get IP address.")
                                xenrt.sleep(20 * 60)
                                ip = self.getHost().checkLeases(mac, checkWithPing=True)
                            else:
                                ip = self.getHost().arpwatch(bridge, mac, timeout=600)

                            self.mainip = ip
                    except Exception, e:
                        # If we previously knew an IP address for this VM then
                        # use it and warn that we did that.
                        if self.mainip:
                            xenrt.TEC().warning("Using cached IP address %s  for VM %s" % (self.mainip, self.getName()))
                        else:
                            self.checkHealth()
                            raise
                    if not self.mainip:
                        raise xenrt.XRTFailure("Did not find an IP address")

            if xenrt.TEC().lookup("EXTRA_TIME", False, boolean=True):
                boottime = 1440 
                agentTime = 600
            else:
                boottime = 900
                agentTime = 180
            if not self.windows:
                if self.hasSSH:
                    try:
                        self.waitForSSH(boottime, desc="Guest boot")

                        # sometimes SSH can be a little temperamental immediately after boot
                        # a small sleep should help this.
                        xenrt.sleep(10)

                    except Exception, e:
                        # Check the VM is still running
                        if self.getState() != "UP":
                            self.checkHealth(noreachcheck=True)
                            raise xenrt.XRTFailure("VM no longer running while waiting for boot")
                        raise
            else:
                autologonRetryCount = 5
                for i in range(autologonRetryCount):
                    try:
                        self.waitForDaemon(boottime, desc="Guest boot")
                        break
                    except Exception, e:
                        # Check the VM is still running
                        if self.getState() != "UP":
                            self.checkHealth(noreachcheck=True)
                            raise xenrt.XRTFailure("VM no longer running while waiting for boot")
                        elif "failed to autologon" in str(e) and i < autologonRetryCount - 1:
                            self.shutdown(force=True)
                            self.lifecycleOperation("vm-start")
                        else:
                            raise
            # Remove any autologin failure screenshot that we may have saved - bootfail.jpg
            try:
                os.remove("%s/bootfail.jpg"%(xenrt.TEC().getLogdir()))
            except:
                pass
            if self.enlightenedDrivers and self.windows:
                self.waitForAgent(agentTime)

            if not self.tailored:
                # Tailor the VM for future test use
                xenrt.TEC().progress("Tailoring the VM for test use")
                self.tailor()
                self.tailored = True

    def unenlightenedShutdown(self):
        if self.windows:
            self.xmlrpcShutdown()
        elif self.distro and re.search("solaris", self.distro):
            self.execguest("nohup /usr/sbin/poweroff >/tmp/poweroff.out 2>/tmp/poweroff.err </dev/null &")
        else:
            self.execguest("(sleep 5 && /sbin/poweroff) >/dev/null 2>&1 </dev/null &")
            xenrt.sleep(10)

    def unenlightenedReboot(self):
        if self.windows:
            self.xmlrpcReboot()
        elif self.distro and re.search("solaris", self.distro):
            self.execguest("nohup /usr/sbin/reboot >/tmp/reboot.out 2>/tmp/reboot.err </dev/null &")
        else:
            self.execguest("(sleep 5 && /sbin/reboot) >/dev/null 2>&1 </dev/null &")
            xenrt.sleep(10)

    def reboot(self, force=False, skipsniff=None, timer=None):
        if not force:
            self.waitForShutdownReady()
        # If this is a Linux guest without a guest agent we'll not sniff
        # if we already know the IP
        if skipsniff == None and self.builtInGuestAgent():
            skipsniff = True
        self.start(reboot=True, forcedReboot=force, skipsniff=skipsniff, timer=timer)

    def suspend(self, newstate="SUSPENDED", timer=None, extraTimeout=0):
        if timer:
            timer.startMeasurement()
        self.lifecycleOperation("vm-suspend", extraTimeout=extraTimeout)
        self.poll(newstate)
        if timer:
            timer.stopMeasurement()

    def resume(self, timer=None, on=None, check=True, checkclock=True):
        """Perform a resume of the VM and return the guest clock skew (from
        controller time) in seconds immediately after the resume. Positive
        means the guest clock is fast."""
        if timer:
            timer.startMeasurement()
        if on:
            self.lifecycleOperation("vm-resume on=%s" % (on.getMyHostName()))
            self.setHost(on)
        else:
            self.lifecycleOperation("vm-resume")
        self.poll("UP")
        if timer:
            timer.stopMeasurement()
        xenrt.sleep(2)
        if xenrt.TEC().lookup("EXTRA_TIME", False, boolean=True):
            boottime = 720
        else:
            boottime = 360
        if not checkclock:
            skew = 0 
        else:
            if not self.windows:
                self.waitForSSH(boottime, desc="Guest resume SSH check")
            else:
                self.waitForDaemon(boottime, desc="Guest resume XML-RPC check")
            skew = self.getClockSkew()
        xenrt.sleep(2)
        if check: self.check()
        return skew

    def getDomainVIFs(self):
        vifs = self.getVIFs()
        macs = []
        for vif in vifs.values():
            macs.append(vif[0])
        return macs 

    def getDomainMemory(self):
        return self.getHost().getGuestMemory(self)

    def getDomainVCPUs(self):
        return self.getHost().getGuestVCPUs(self)

    def cpucorespersocketset(self, corespersocket):
        cli = self.getCLIInstance()
        xenrt.TEC().logverbose("Setting cpu cores per socket: %s" % (corespersocket))
        args = []
        args.append("uuid=%s" % (self.getUUID()))
        args.append("platform:cores-per-socket=%s" % (corespersocket))
        cli.execute("vm-param-set", string.join(args))

    def getUUID(self):
        """Return this guest's UUID"""
        if self.uuid:
            return self.uuid
        self.uuid = self.getHost().getGuestUUID(self)
        return self.uuid

    def hasRootDisk(self):
        return (len(self.listVBDs()) > 0)            

    def getRootDiskDetails(self):
        vbds = self.listVBDs()
        for k in vbds.keys():
            size, min_size, function, qos = vbds[k]
            if function == "root":
                return k, size, min_size, function, qos
        raise xenrt.XRTError("Unable to find root disk")

    def getDomid(self):
        return self.getHost().getDomid(self)

    def getVdiMD5Sums(self):
        """Returns a dictionary of MD5 sums of all attached VDIs keyed by device ID"""

        output = {}
        host = self.getHost()

        for vbd in host.minimalList("vbd-list", args="vm-uuid=%s type=Disk" % self.getUUID()):
            if host.genParamGet("vbd", vbd, "currently-attached") == "true":
                dev = host.genParamGet("vbd", vbd, "device")
                vdi = host.genParamGet("vbd", vbd, "vdi-uuid")
                output[dev] = host.getVdiMD5Sum(vdi)

        return output

    def getVifOffloadSettings(self, device):
        """Returns a VifOffloadSettings object for the specified device

        @param device: integer such that 0 >= device < 99"""

        return xenrt.objects.VifOffloadSettings(self, device)

    def waitForShutdownReady(self):
        pass

    def crash(self):
        xenrt.TEC().logverbose("Sleeping for 180 seconds to let the VM run for atleast 2 minutes before crashing")
        time.sleep(180)
        if self.windows:
            self.host.execdom0("%s %d" % 
                               (self.host._findXenBinary("crash_guest"), self.getDomid()))
        else:
            panic = """
#include <linux/module.h>
#include <linux/init.h>
static int __init panic_init(void) { panic("XenRT Panic!"); }
module_init(panic_init);
"""        
            mkfile = """
obj-m  := panic.o
KDIR   := /lib/modules/$(shell uname -r)/build
PWD    := $(shell pwd)
default:
\t$(MAKE) -C $(KDIR) SUBDIRS=$(PWD) modules
"""
            m = xenrt.TEC().tempFile()
            p = xenrt.TEC().tempFile()
            file(m, "w").write(mkfile)
            file(p, "w").write(panic)
            sftp = self.sftpClient()
            sftp.copyTo(m, "Makefile")
            sftp.copyTo(p, "panic.c")
            self.execguest("make")
            self.execguest("(sleep 4 && insmod panic.ko) > /dev/null 2>&1 < /dev/null &")
            xenrt.sleep(5)

    def installCitrixCertificate(self):
        log("Installing citrix Certificate after checking the windows version")
        # Install the Citrix certificate to those VMs which require it (Vista and onwards)
        if self.windows and float(self.xmlrpcWindowsVersion()) > 5.99:
            xenrt.TEC().comment("Installing Citrix certificate")
            # Copy a version of certmgr.exe that takes command line arguments
            self.xmlrpcSendFile("%s/distutils/certmgr.exe" % xenrt.TEC().lookup("LOCAL_SCRIPTDIR"), "c:\\certmgr.exe")
            self.xmlrpcSendFile("%s/data/certs/CitrixTrust.cer" % (xenrt.TEC().lookup("XENRT_BASE")),"c:\\CitrixTrust.cer")
            self.xmlrpcExec("c:\\certmgr.exe /add c:\\CitrixTrust.cer /s /r localmachine trustedpublisher")

    def _generateRunOnceScript(self):
        u = []
        for p in string.split(xenrt.TEC().lookup("PV_DRIVERS_DIR"), ";"):
            u.append("""IF EXIST "%s\\xennet.inf" "c:\\devcon.exe" -r update "%s\\xennet.inf" XEN\\vif""" % (p, p))
            u.append("""IF EXIST "%s\\xeniface.inf" "c:\\devcon.exe" -r update "%s\\xeniface.inf" XEN\\iface""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon.exe" -r update "%s\\xenvif.inf" XENBUS\\CLASS^&VIF""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon.exe" -r update "%s\\xeniface.inf" XENBUS\\CLASS^&IFACE""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon.exe" -r update "%s\\xennet.inf" XENVIF\\DEVICE""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon.exe" -r update "%s\\xennet.inf" XEN\\vif""" % (p, p))
        for p in string.split(xenrt.TEC().lookup("PV_DRIVERS_DIR_64"), ";"):
            u.append("""IF EXIST "%s\\xennet.inf" "c:\\devcon64.exe" -r update "%s\\xennet.inf" XEN\\vif""" % (p, p))
            u.append("""IF EXIST "%s\\xeniface.inf" "c:\\devcon64.exe" -r update "%s\\xeniface.inf" XEN\\iface""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon64.exe" -r update "%s\\xenvif.inf" XENBUS\\CLASS^&VIF""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon64.exe" -r update "%s\\xeniface.inf" XENBUS\\CLASS^&IFACE""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon64.exe" -r update "%s\\xennet.inf" XENVIF\\DEVICE""" % (p, p))
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon64.exe" -r update "%s\\xennet.inf" XEN\\vif""" % (p, p))
        return string.join(u, "\n")


    def installRunOncePVDriversInstallScript(self):

        self.xmlrpcSendFile("%s/distutils/soon.exe" % (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")),"c:\\soon.exe")
        self.xmlrpcSendFile("%s/distutils/devcon.exe" % (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")), "c:\\devcon.exe")
        self.xmlrpcSendFile("%s/distutils/devcon64.exe" % (xenrt.TEC().lookup("LOCAL_SCRIPTDIR")), "c:\\devcon64.exe")
        runonce2 = xenrt.TEC().tempFile()

        updatecmd = self._generateRunOnceScript()
        f = file(runonce2, "w")
        f.write("""echo R1.1 > c:\\r1.txt
REM ping 127.0.0.1 -n 60 -w 1000
echo R1.2 > c:\\r2.txt
%s
echo R1.3 > c:\\r3.txt
""" % (updatecmd))
        f.close()
        self.xmlrpcSendFile(runonce2, "c:\\runoncepvdrivers2.bat")
        runonce = xenrt.TEC().tempFile()
        f = file(runonce, "w")
        f.write("""c:\\soon.exe 900 /INTERACTIVE c:\\runoncepvdrivers2.bat > c:\\xenrtlog.txt
at > c:\\xenrtatlog.txt
""")
        f.close()
        self.xmlrpcSendFile(runonce, "c:\\runoncepvdrivers.bat")

        # Set the run once script
        self.winRegAdd("HKLM",
                       "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\"
                       "RunOnce",
                       "XenRTPVDrivers",
                       "SZ",
                       "c:\\runoncepvdrivers.bat")

    def convertHVMtoPV(self):
        """Convert an HVM guest into a PV guest. Reboots guest if it is running."""

        # Handle guests that don't have a PV-compatible kernel installed by default
        if self.distro.startswith("sles12"):
            oldstate = self.getState()
            self.setState("UP")

            # Sorry, this is necessarily going to be ugly!
            # When we update the grub config, it sees that we're running in HVM mode and skips xenkernels.
            # So we need to hack grub to temporarily think that we're not in HVM mode.
            self.execguest("sed -i 's/CONFIG_XEN/xxx/' /etc/grub.d/10_linux")

            self.execguest("zypper -n install kernel-xen")

            # Now revert the grub hack
            self.execguest("sed -i 's/xxx/CONFIG_XEN/' /etc/grub.d/10_linux")

            self.setState(oldstate)

        self.paramSet("HVM-boot-policy", "")
        self.paramRemove("HVM-boot-params", "order")
        self.paramSet("PV-bootloader", "pygrub")

        # If VM is running, reboot it
        if self.getState() in ['UP', 'PAUSED']:
            self.reboot()

    def setDriversBootStart(self):
        self.winRegAdd("HKLM", "SYSTEM\\CurrentControlSet\\services\\xenvif", "Start", "DWORD", 0)
        self.winRegAdd("HKLM", "SYSTEM\\CurrentControlSet\\services\\xennet", "Start", "DWORD", 0)
        self.reboot()

    def installDrivers(self, source=None, extrareboot=False, expectUpToDate=True):
        """Install PV drivers into a guest"""

        if not self.windows:
            xenrt.TEC().skip("Non Windows guest, no drivers to install")
            return

        if float(self.xmlrpcWindowsVersion()) == 6.1 and xenrt.TEC().lookup("STRESS_TEST", False, boolean=True):
            # CA-35591 update the default SCM timeout
            try:
                self.winRegAdd("HKLM",
                               "System\\CurrentControlSet\\Control",
                               "ServicesPipeTimeout",
                               "DWORD",
                               120000)
            except Exception, e:
                pass

        # Locate the driver installer exe
        if not source:
            # This provides an external input fetched using standard
            # mechanisms
            sourcefile = xenrt.TEC().lookup("PV_TOOLS_INSTALLER", None)
            if sourcefile:
                source = xenrt.TEC().getFile(sourcefile)
                if not source:
                    raise xenrt.XRTError("Could not locate PV tools installer",
                                         sourcefile)
        if not source:
            source = xenrt.TEC().lookup("OPTION_DRIVER_ISO", None)
            if source:
                source = xenrt.TEC().getFile(source)
        if not source:
            try:
                remotefile = self.host.toolsISOPath()
                if not remotefile:
                    raise xenrt.XRTError("Could not find PV tools ISO in dom0")
                xenrt.TEC().logverbose("Using driver ISO: %s" % (remotefile))
                mp = self.host.hostTempDir()
                cdlock = xenrt.resources.CentralResource()
                attempts = 0
                while True:
                    try:
                        cdlock.acquire("PV_ISO_LOCK-%s" % (self.host.getName()))
                        break
                    except:
                        xenrt.sleep(30)
                        attempts = attempts + 1 
                        if attempts > 10:
                            raise xenrt.XRTError("Couldn't get ISO lock.")       
                try:
                    self.host.execdom0("mount -o loop %s %s" % 
                                       (remotefile, mp))
                    subdir = xenrt.TEC().tempDir()
                    sh = self.host.sftpClient()
                    sh.copyFrom("%s/xensetup.exe" % (mp),
                                "%s/xensetup.exe" % (subdir))
                    sh.close()
                    source = "%s/xensetup.exe" % (subdir)
                    xenrt.TEC().logverbose("Using Windows driver ISO from "
                                           "installed host.")
                except Exception, e:
                    xenrt.TEC().logverbose("Caught exception: %s" % (str(e)))
                self.host.execdom0("umount %s" % (mp))
                cdlock.release()
            except Exception, e:
                traceback.print_exc(file=sys.stderr)
                raise xenrt.XRTError("Exception fetching PV tools ISO: %s" %
                                     (str(e)))
        if not source:
            raise xenrt.XRTError("No Windows driver ISO/EXE path given.")
        xenrt.TEC().logverbose("Using drivers from %s" % (source))

        # If this is a file path, copy it locally, if it's a URL, fetch it
        tmp = xenrt.TEC().tempFile()
        tmpfile = "%s_%s" % (tmp, os.path.basename(source))
        if source[0] == "/":
            shutil.copyfile(source, tmpfile)
        else:
            xenrt.util.command("wget %s -O %s" % (source, tmpfile))

        ftype = xenrt.command("file -b %s" % (tmpfile))

        # If the file is tar.bz2 then it's probably a Carbon package
        # file containing an ISO. Unpack it
        decompress = None
        if tmpfile[-8:] == ".tar.bz2" or re.search(r"bzip2", ftype):
            decompress = "j"
        elif tmpfile[-4:] == ".tgz" or tmpfile[-7:] == ".tar.gz" or re.search(r"gzip", ftype):
            decompress = "z"
        if decompress:
            unpack = xenrt.TEC().tempDir()
            xenrt.util.command("tar -%sxf %s -C %s" % (decompress, tmpfile, unpack))
            tmpfile = string.strip(xenrt.util.command("find %s -type f -name \"xensetup.exe\" | "
                                                      "head -n 1" % (unpack)))
            if tmpfile == "":
                tmpfile = string.strip(xenrt.util.command("find %s -type f -name \"*.exe\" | "
                                                          "head -n 1" % (unpack)))
            if tmpfile == "":
                raise xenrt.XRTError("Could not find installer inside tarball")

        # If this is an ISO, mount it to pull out the installer exe
        if tmpfile[-4:] == ".iso" or re.search(r"ISO 9660", ftype):
            mount = xenrt.rootops.MountISO(tmpfile)
            mountpoint = mount.getMount()
            if not os.path.exists("%s/xensetup.exe" % (mountpoint)):
                mount.unmount()
                raise xenrt.XRTFailure("Could not find xensetup.exe on "
                                       "driver ISO")
            xensetup = xenrt.TEC().tempFile()
            shutil.copyfile("%s/xensetup.exe" % (mountpoint), xensetup)
            mount.unmount()
        else:
            # Otherwise assume it is the installer executable
            xensetup = tmpfile

        # Copy the setup binary to the guest
        self.xmlrpcSendFile(xensetup, "c:\\xensetup.exe")
        self.increaseServiceStartTimeOut()
        self.installRunOncePVDriversInstallScript()

        domid = self.host.getDomid(self)

        # Start the installer
        self.xmlrpcStart("c:\\xensetup.exe /S")

        # Monitor the guest for a domid change, this is the reboot
        deadline = xenrt.util.timenow() + 7200
        while True:
            try:
                if self.host.getDomid(self) != domid:
                    break
            except:
                pass
            now = xenrt.util.timenow()
            if now > deadline:
                self.checkHealth()
                raise xenrt.XRTFailure("Timed out waiting for installer initiated reboot")
            xenrt.sleep(30)
        try:
            bootTimeout=1200
            if xenrt.TEC().lookup("STRESS_TEST", False, boolean=True):
                bootTimeout=2400
            self.waitForDaemon(bootTimeout, desc="Daemon connect after driver install")
        except Exception, e:
            if not extrareboot: 
                raise
        else:
            # XRT-792 Cancel any left over AT jobs
            try:
                self.xmlrpcExec("at.exe /delete /yes")
            except:
                pass

        self.waitForAgent(300, checkPvDriversUpToDate=expectUpToDate)
        self.enlightenedDrivers = True

        if extrareboot:
            self.reboot()

        self.checkPVDevices()

        # CA-17052 - Mark extra disks as online.
        if float(self.xmlrpcWindowsVersion()) > 5.99:
            self.xmlrpcMarkDiskOnline()

        try:
            os.unlink(tmp)
        except:
            xenrt.TEC().warning("Failed to remove file %s" % tmp)

    def uninstallDrivers(self,waitForDaemon=True):
        # Write the uninstall script
        u = []
        for p in string.split(xenrt.TEC().lookup("PV_DRIVERS_DIR"), ";"):
            u.append("IF EXIST \"%s\\uninstaller.exe\" set PVPATH=%s" % (p,p))
        for p in string.split(xenrt.TEC().lookup("PV_DRIVERS_DIR_64"), ";"):
            u.append("IF EXIST \"%s\\uninstaller.exe\" set PVPATH=%s" % (p,p))

        uninstcmd = """@echo off
REM Uninstall PV Drivers
set PVPATH=
%s
IF "x%%PVPATH%%" == "x" GOTO NOTFOUND
"%%PVPATH%%\\uninstaller.exe" /S _?=%%PVPATH%%
exit /B 0
:NOTFOUND
echo Uninstaller Not Found!
exit /B 1
""" % (string.join(u, "\n")) 

        tf = xenrt.TEC().tempFile()
        f = file(tf, "w")
        f.write(uninstcmd)
        f.close()
        self.xmlrpcSendFile(tf, "c:\\uninstallpvdrivers.bat")

        domid = self.host.getDomid(self)
        self.xmlrpcStart("c:\\uninstallpvdrivers.bat")

        # Wait for a domid change        
        deadline = xenrt.util.timenow() + 300
        while True:
            try:
                d = self.host.getDomid(self)
                if d != domid:
                    break
            except:
                pass
            now = xenrt.util.timenow()
            if now > deadline:
                self.checkHealth()
                raise xenrt.XRTFailure("Timed out waiting for uninstaller "
                                       "initiated reboot")
            xenrt.sleep(30)

        if waitForDaemon:
            # Wait until we can connect
            self.waitForDaemon(1200, desc="Daemon connect after driver "
                                          "uninstall")

            # Verify PV devices have been removed
            try:
                self.checkPVDevices()
            except:
                pass
            else:
                raise xenrt.XRTFailure("PV devices still detected after "
                                       "uninstalling drivers")

        self.enlightenedDrivers = False

    def waitForAgent(self, timeout, checkPvDriversUpToDate=True):
        """Wait for guest agent to come up"""

        deadline = xenrt.util.timenow() + timeout

        while xenrt.util.timenow() < deadline:
            domid = self.getDomid()
            otherValue = None
            pvValue = None
            defaultValue = None

            try:
                defaultValue = self.host.xenstoreRead("/local/domain/%d/data/updated" % domid)
            except:
                pass

            try:
                otherValue = self.host.xenstoreRead("/local/domain/%d/data/update_cnt" % domid)
            except:
                pass

            if self._checkPVAddonsInstalled():
                pvValue = "1"
 
            else:
                try:
                    pvValue = self.host.xenstoreRead("/local/domain/%d/attr/PVAddons/Installed" % domid)     
                except:
                    pass

            if pvValue == "1" and (defaultValue or otherValue):
                xenrt.TEC().logverbose("Found PV driver evidence")
                xenrt.TEC().logverbose("Wait 5 seconds just in case XAPI is still settling.")
                xenrt.sleep(5)

                if not xenrt.TEC().lookup("NO_TOOLS_UP_TO_DATE_CHK", False, boolean=True) and checkPvDriversUpToDate:
                    for i in range(48):
                        if self.pvDriversUpToDate():
                            break
                        xenrt.sleep(10)
                return xenrt.RC_OK

            xenrt.sleep(5)

        raise xenrt.XRTFailure("Not found any PV driver evidence")

    def checkForWinGuestAgent(self):
        """Check if the VM up and the guest agent has reported."""
        return self.waitForAgent(0) == xenrt.RC_OK

    def checkPVDevicesState(self):
        # Check the guest is using the PV drivers
        pvcheck = []
        backend = "/local/domain/0/backend"
        domid = self.host.getDomid(self)
        # First we'll try blktap2, if that fails we'll do blktap3 instead
        try:
            self.host.execdom0("xenstore-ls %s/vbd/%u" % (backend, domid))
            vbdPath = "vbd"
        except:
            vbdPath = "vbd3"
        vbdids = self.host.execdom0("xenstore-ls %s/%s/%u | grep ^[0-9] | "
                                    "awk '{print $1}'" % (backend, vbdPath, domid))
        try:
            tapids = self.host.execdom0("xenstore-ls %s/tap/%u 2>/dev/null | "
                                        "grep ^[0-9] | awk '{print $1}'" %
                                        (backend, domid))
        except:
            tapids = ""
        vbdid = None
        for v in string.split(vbdids):
            idedev = self.host.xenstoreRead("%s/%s/%u/%s/dev" %
                                            (backend, vbdPath, domid, v))
            if idedev == "hda":
                vbdid = (vbdPath, v)
        for v in string.split(tapids):
            idedev = self.host.xenstoreRead("%s/tap/%u/%s/dev" %
                                            (backend, domid, v))
            if idedev == "hda":
                vbdid = ("tap", v)
        if not vbdid:
        #    pvcheck.append("Unable to lookup VBD/TAP backend ID")
            pass
        else:
            dx, vid = vbdid
            vbdstate = self.host.xenstoreRead("%s/%s/%u/%s/state" %
                                              (backend, dx, domid, vid))
            if vbdstate != "4":
                pvcheck.append("VBD/TAP backend not in connected state")
        vifstate = self.host.xenstoreRead("%s/vif/%u/0/state" %
                                          (backend, domid))
        if vifstate != "4":
            pvcheck.append("VIF backend not in connected state")
        
        return pvcheck
        
    def checkPVDevices(self):
        # Check the guest is using the PV drivers
        pvcheck = self.checkPVDevicesState()
        
        if pvcheck:
            if xenrt.TEC().lookup("PAUSE_ON_PV_CHECK_FAIL", False, boolean=True):
                xenrt.TEC().tc.pause("Paused on PV Check failure")

            raise xenrt.XRTFailure("VIF and/or VBD PV device not used. Possibilities: -" + " -".join(pvcheck))
        else:
            xenrt.TEC().logverbose("PV drivers are installed and ready") 

    def enableDriverVerifier(self, enable=True, drivers=["xennet.sys/xennet6.sys", "xenvbd.sys/xvbdstor.sys", "xevtchn.sys"]):

        if self.xmlrpcWindowsVersion() > "5.99":
            if xenrt.TEC().lookup("PRODUCT_VERSION", None) == "Orlando":
                drivers = ["xennet6.sys",
                           "xenvbd.sys/xvbdstor.sys",
                           "xevtchn.sys"]

            elif isinstance(self.host, xenrt.lib.xenserver.TampaHost):
                drivers = ["xenbus.sys", "xen.sys", "xenfilt.sys", "xenvbd.sys", "xencrsh.sys", "xeniface.sys", "xenvif.sys", "xennet.sys"]

        xenrt.TEC().logverbose("Using drivers: %s" % (drivers))

        if enable:
            command = "verifier.exe /standard /all"
            expfail = False
        else:
            command = "verifier.exe /reset"
            expfail = True
        rc = self.xmlrpcExec(command, level=xenrt.RC_OK)
        if rc != 0 and not expfail:
            raise xenrt.XRTFailure("Exception running verifier command")

        # Need to reboot to make the change
        self.reboot()

        data = self.xmlrpcExec("verifier.exe /query", returndata=True)
        v = 0
        notfound = []
        didfind = []
        for d in drivers:
            ds = d.split("/")
            found = False
            for dr in ds:
                if re.search("Name: %s" % (dr), data):
                    found = True
                    break
            if found:
                v = v + 1
                didfind.append(d)
            else:
                notfound.append(d)
        if enable:
            if v != len(drivers):
                if xenrt.TEC().lookup("VERIFIER_WARN_ONLY",
                                      False,
                                      boolean=True):
                    xenrt.TEC().warning("Problem enabling driver verifier for %s"
                                        % (string.join(notfound)))
                else:
                    raise xenrt.XRTError("Problem enabling driver verifier for %s"
                                         % (string.join(notfound)))
        else:
            if v != 0:
                if xenrt.TEC().lookup("VERIFIER_WARN_ONLY",
                                      False,
                                      boolean=True):
                    xenrt.TEC().warning("Problem disabling driver verifier "
                                        "for" % (string.join(didfind)))
                else:
                    raise xenrt.XRTError("Problem disabling driver verifier "
                                         "for" % (string.join(didfind)))

    def updateKernelFromWeb(self, webbase):
        """Update the VM's kernel from a XenSource updates website."""
        rewrites = ["http://updates.xensource.com",
                    "http://updates.vmd.citrix.com"]

        updateurltemplate = webbase + "/XenServer/${VERSION}"
        v = self.host.getInventoryItem("PRODUCT_VERSION")
        url = string.replace(updateurltemplate, "${VERSION}", v)

        # Debian
        if self.execguest("test -e /etc/debian_version", retval="code") == 0:
            # In VM install tailoring we rewrote the apt source.list file(s)
            # to prevent a fetch from updates.xensource.com etc.. Put this
            # back now so we can actually do the update. For general
            # updates we'll keep using the static mirrors.
            sourceslist = "/etc/apt/sources.list"
            sourceslistd = ["/etc/apt/sources.list.d/xensource.list",
                            "/etc/apt/sources.list.d/citrix.list"]
            v = self.execguest("cat /etc/debian_version").strip()
            if v == "3.1":
                # Sarge has the updates.xensource.com entry in the
                # main sources.list file
                if self.execguest("test -e %s" % (sourceslist),
                                  retval="code") == 0:
                    self.execguest(\
                        "sed -i '/updates.xensource.com/s/#deb/deb/g' %s" %
                        (sourceslist))

            # Put back the original sources.list.d files
            for file in sourceslistd:
                if self.execguest("test -e %s.orig" % (file),
                                  retval="code") == 0:
                    self.execguest("rm -f %s" % (file))
                    self.execguest("mv %s.orig %s" % (file, file))

            # Rewrite references to the update server
            for file in [sourceslist] + sourceslistd:
                if self.execguest("test -e %s" % (file), retval="code") == 0:
                    for rewrite in rewrites:
                        self.execguest("sed -i 's!%s!%s!g' %s" %
                                       (rewrite, webbase, file))

            # Make sure everything is upgraded
            if self.execguest("cat /etc/debian_version").strip() != "3.1":
                self.execguest("wget -O - %s/GPG-KEY | apt-key add -" %
                               (url))
            self.execguest("apt-get -y update")
            try:
                self.execguest("apt-get -y upgrade")
            except:
                pass

            # The upgrade may have put the source.list.d file back to
            # the published state so we may need to rewrite it again
            # Rewrite references to the update server
            for file in [sourceslist] + sourceslistd:
                if self.execguest("test -e %s" % (file), retval="code") == 0:
                    for rewrite in rewrites:
                        self.execguest("sed -i 's!%s!%s!g' %s" %
                                       (rewrite, webbase, file))
            self.execguest("apt-get -y update")

            # Perform the kernel upgrade
            self.execguest("apt-get -y install linux-image-2.6-xen")
            self.execguest("update-grub")
            if self.execguest("cat /etc/debian_version").strip() == "3.1":
                self.execguest("sed -i 's/^default[[:space:]]\+0/default 2/' "
                               "/boot/grub/menu.lst")
            self.reboot()

        # Centos 4 or 5 or RHEL 5
        elif self.execguest(\
            "grep -qi CentOS /etc/redhat-release", retval="code") == 0 or \
            self.execguest(\
            "grep -qi 'Red Hat.*release 5' /etc/redhat-release",
            retval="code") == 0:

            for repo in ["XenSource.repo", "Citrix.repo"]:
                if self.execguest("test -e /etc/yum.repos.d/%s" % (repo),
                                  retval="code") == 0:
                    for rewrite in rewrites:
                        self.execguest("sed -i 's!%s!%s!g' /etc/yum.repos.d/%s" %
                                       (rewrite, webbase, repo))
                    # Also comment out the mirrorlist and uncomment the
                    # baseurl to allow for the mirrorlist not being staging-
                    # safe
                    self.execguest("sed -e 's/^mirrorlist/#mirrorlist/' "
                                   "-e 's/^#baseurl/baseurl/' -i "
                                   "/etc/yum.repos.d/%s" % (repo))
            if self.execguest("grep -qi CentOS /etc/redhat-release",
                              retval="code") == 0:
                self.execguest("for i in /etc/yum.repos.d/CentOS-*.repo; "
                               "  do mv $i $i.orig; done")
            self.execguest("yum -y update", timeout=1200)
            self.reboot()

        # RHEL 4
        elif self.execguest("grep -qi 'Red Hat.*release 4' /etc/redhat-release",
                            retval="code") == 0:
            # No yum so just grab all the RPMs we can and filter out any
            # that we already have
            tmpdir = self.execguest("mktemp -d /tmp/updateXXXXXX").strip()
            self.execguest("cd %s && wget -r -np '%s/rhel4x/RPMS'" %
                           (tmpdir, url))
            rpmfiles = self.execguest(\
                "find %s -name \"*.rpm\" | grep -v x86_64 | grep -v src.rpm" %
                (tmpdir)).split()
            rpmskip = []
            for rpmfile in rpmfiles:
                rv = self.execguest("rpm -qp %s 2>/dev/null" % (rpmfile)).strip()
                rname = self.execguest("rpm -qp %s --qf %%{NAME} 2>/dev/null" %
                                       (rpmfile)).strip()
                try:
                    curv = self.execguest("rpm -q %s 2>/dev/null" % (rname)).strip()
                except:
                    # Probably don't have the RPM installed already
                    curv = None
                if not curv:
                    rpmskip.append(rpmfile)
                    xenrt.TEC().logverbose("Don't have %s" % (rname))
                elif curv == rv:
                    # We already have this version
                    rpmskip.append(rpmfile)
                    xenrt.TEC().logverbose("Already have %s" % (rv))
                elif rname == "mkinitrd":
                    # Assume we already have the necessary version
                    rpmskip.append(rpmfile)
                    xenrt.TEC().logverbose("Assuming we already have a "
                                           "suitable version of mkinitrd")
            for rpmfile in rpmskip:
                rpmfiles.remove(rpmfile)
            if len(rpmfiles) > 0:
                self.execguest("rpm -Uv --replacepkgs %s" %
                               (string.join(rpmfiles)))
                self.reboot()
            else:
                raise xenrt.XRTError("No RPMs to upgrade")

        else:
            raise xenrt.XRTError("No support for update of %s" %
                                 (self.getName()))

        # Re-tailor the VM
        self.tailor()

    def setName(self, name):
        self.paramSet("name-label", name)
        xenrt.GenericGuest.setName(self, name)

    def checkWindows(self):
        if re.search("Windows",
                     self.getHost().parseListForParam("vm-list",
                                                      self.getUUID(),
                                                      "os-version")):
            return True
        else:
            return False

    def createGuestFromTemplate(self, 
                                template, 
                                sruuid, 
                                ni=False, 
                                db=True, 
                                guestparams=[],
                                rootdisk=None):
        time = 3600
        cli = self.getCLIInstance()
        # We can't resize disks on VHD so we have to clone the
        # template and edit the config to make sure install
        # will work in all cases.
        if xenrt.TEC().lookup("OPTION_CLONE_TEMPLATE", False, boolean=True):
            if rootdisk and not rootdisk == self.DEFAULT:
                c = self.getHost().cloneTemplate(template)
                oc = self.getHost().genParamGet("template", c, "other-config")
                oc = re.sub('(device="0" size=")([0-9]+)',
                            '\g<1>%s' % (rootdisk*xenrt.MEGA), 
                             oc)
                oc = re.search("disks: (.*);", oc).group(1)
                self.getHost().genParamSet("template", 
                                           c, 
                                           "other-config:disks", 
                                           oc)
                template = self.getHost().parseListForParam("template-list",
                                                            c,
                                                            "name-label")
                if rootdisk > 100000:
                    time = 14400
        args = []
        args.append("new-name-label=\"%s\"" % (self.name))
        args.append("template-name=\"%s\"" % (template))
        if sruuid:
            args.append("sr-uuid=\"%s\"" % (sruuid))
        xenrt.TEC().progress("Installing guest VM %s" % (self.name))
        self.uuid = cli.execute("vm-install", string.join(args), timeout=time).strip()
        if self.getState() != "DOWN":
            raise xenrt.XRTFailure("Guest running after vm-install (CA-6160)")
        if ni:
            self.paramSet("PV-args", "noninteractive")

        if xenrt.TEC().lookup("DISABLE_USB", False, boolean=True):
            self.paramSet("platform:usb", "false")

        if xenrt.TEC().lookup("EXP_VIRIDIAN", False, boolean=True):
            self.paramSet("platform:exp-viridian-timers", "true")

        if xenrt.TEC().lookup("DISABLE_VIRIDIAN_COUNT", False, boolean=True):
            self.paramSet("platform:viridian_time_ref_count", "false")

        if db:
            try:
                self.paramSet("actions-after-crash", "preserve")
            except:
                pass
        if self.memory:
            self.memset(self.memory)
        else:
            self.memory = self.memget()
        if self.vcpus:
            self.cpuset(self.vcpus)
        else:
            self.vcpus = self.cpuget()            
        if self.corespersocket:
            self.cpucorespersocketset(self.corespersocket)
        self.setHostnameViaXenstore()
        for (gp_name,gp_value) in guestparams:
            self.paramSet(gp_name,gp_value)
        try:
            self.getHost().removeTemplate(c)
        except:
            pass

    def setHostnameViaXenstore(self):
        if xenrt.TEC().lookup("NO_XENSTORE_HOSTNAME", False, boolean=True):
            xenrt.TEC().logverbose('Not setting hostname via XenStore')
            return

        try:
            if xenrt.TEC().lookup("SET_VM_HOSTNAME", False, boolean=True):
                hn = re.sub(r"[^a-zA-Z0-9-]", "", self.getName())[0:15]
            else:
                hn = string.replace(self.getUUID(), "-", "")[0:15]
            self.paramSet("xenstore-data:vm-data/hostname", hn)
        except Exception, e:
            xenrt.TEC().logverbose("Exception setting VM hostname: %s" %
                                   (str(e)))

    def createHVMGuest(self, disks, pxe=False, db=True):
        """Create an HVM guest from scratch"""
        cli = self.getCLIInstance()
        vmuuid = cli.execute("vm-create",
                             "name-label=\"%s\"" % (self.name),
                             strip=True)
        for i in range(len(disks)):
            ds, sr = disks[i]
            if ds == self.DEFAULT:
                rootsize = 8589934592 # 8GB
            else:
                rootsize = ds * xenrt.MEGA
            if i == 0:
                bootable = True
            else:
                bootable = False
            device = "hd%s" % (chr(ord('a') + i))
            self.createDisk(sizebytes=rootsize, sruuid=sr, 
                            userdevice=device, bootable=bootable)
        self.paramSet("HVM-boot-policy", "BIOS order")
        if pxe:
            self.paramSet("HVM-boot-params-order", "dcn")
        else:
            self.paramSet("HVM-boot-params-order", "dc")
        if db:
            try:
                self.paramSet("actions-after-crash", "preserve")
            except:
                pass
        self.paramSet("platform-pae", "true")
        self.paramSet("platform-acpi", "true")
        self.paramSet("platform-apic", "true")
        self.paramSet("platform-nx", "true")

    def installHVMGuest(self, disks, pxe=False, db=True, biosHostUUID=None):
        """Install an HVM guest using Other install media template"""
        cli = self.getCLIInstance()
        args = []
        args.append("new-name-label=\"%s\"" % (self.name))
        args.append("template-name=\"Other install media\"")
        if biosHostUUID:
            args.append("copy-bios-strings-from=%s" % (biosHostUUID))
        vmuuid = cli.execute("vm-install",
                             string.join(args),
                             strip=True)
        if disks == None:
            disks = [(self.DEFAULT, self.chooseSR())]
        for i in range(len(disks)):
            ds, sr = disks[i]
            if ds == self.DEFAULT:
                rootsize = 8589934592 # 8GB
            else:
                rootsize = ds * xenrt.MEGA
            if i == 0:
                bootable = True
            else:
                bootable = False
            device = "hd%s" % (chr(ord('a') + i))
            self.createDisk(sizebytes=rootsize, sruuid=sr,
                            userdevice=device, bootable=bootable)
        self.paramSet("HVM-boot-policy", "BIOS order")
        if pxe:
            self.paramSet("HVM-boot-params-order", "dcn")
        else:
            self.paramSet("HVM-boot-params-order", "dc")
        if db:
            try:
                self.paramSet("actions-after-crash", "preserve")
            except:
                pass
        self.paramSet("platform-pae", "true")
        self.paramSet("platform-acpi", "true")
        self.paramSet("platform-apic", "true")
        self.paramSet("platform-nx", "true")

    def changeCD(self, isoname, device="3"):
        cli = self.getCLIInstance()
        add = False
        eject = True
        # See what we have already
        el = self.getHost().minimalList("vbd-list",
                                        "empty",
                                        "vm-uuid=%s type=CD" % (self.getUUID()))
        if el:
            # We already have a CD device
            if el[0] == "true":
                # The CD is empty so no need to eject
                eject = False
        else:
            # No CD device, go back to a legacy check
            try:
                # See if we already have a CD device (insert or <EMPTY>), don;t
                # care
                empty = self.getHost().parseListForOtherParam("vbd-list",
                                                              "device", 
                                                              device,
                                                              "empty",
                                                              "vm-uuid=%s" %
                                                              (self.getUUID()))
                if empty == "":
                    add = True
                elif empty == "true":
                    eject = False
            except:
                # No current CD
                add = True

        if add:
            if isoname:
                args = []
                args.append("uuid=%s" % (self.getUUID()))
                args.append("cd-name=\"%s\"" % (isoname))
                args.append("device=%s" % (device))
                cli.execute("vm-cd-add", string.join(args))
        else:
            if eject:
                args = []
                args.append("uuid=%s" % (self.getUUID()))
                cli.execute("vm-cd-eject", string.join(args))
            if isoname:
                args = []
                args.append("uuid=%s" % (self.getUUID()))
                args.append("cd-name=\"%s\"" % (isoname))
                cli.execute("vm-cd-insert", string.join(args))

    def removeCD(self, device=None):
        """Remove the CD device from the VM."""
        cli = self.getCLIInstance()
        if device:
            vbds = self.getHost().minimalList("vbd-list",
                                              "uuid",
                                              "vm-uuid=%s type=CD device=%s" %
                                              (self.getUUID(), device))
        else:
            vbds = self.getHost().minimalList("vbd-list",
                                              "uuid",
                                              "vm-uuid=%s type=CD" %
                                              (self.getUUID()))
        try:
            args = []
            args.append("uuid=%s" % (self.getUUID()))
            cli.execute("vm-cd-eject", string.join(args))
        except:
            pass
        for vbd in vbds:
            args = []
            args.append("uuid=%s" % (vbd))
            cli.execute("vbd-destroy", string.join(args))

    def createVIF(self, eth=None, bridge=None, mac=None, plug=False):
        if bridge:
            nwuuid = self.getHost().getNetworkUUID(bridge)
        else:
            nwuuid = self.getHost().createNetwork()

        bridge = self.getHost().genParamGet("network", nwuuid, "bridge") 

        if not mac:
            mac = xenrt.randomMAC()

        if eth:
            r = re.search(r"(\d+)", eth)
            device = r.group(1)
        else:
            device = \
                min(map(int, 
                self.getHost().genParamGet("vm", 
                                           self.getUUID(), 
                                           "allowed-VIF-devices").split("; ")))
        cli = self.getCLIInstance()
        args = []
        args.append("device=%s" % (device))
        args.append("mac=%s" % (mac))
        args.append("network-uuid=%s" % (nwuuid))
        args.append("vm-uuid=%s" % (self.getUUID()))
        uuid = cli.execute("vif-create", string.join(args), strip=True)

        # If we've used an alias, we need to convert it to the real bridge here
        if not eth in [x[0] for x in self.vifs]:
            self.vifs.append(("eth%s" % (device), bridge, mac, None))
        else:
            index = [i for i,x in enumerate(self.vifs) if x[0] == eth][0]
            oldeth, oldbridge, oldmac, oldip = self.vifs[index]
            if bridge != oldbridge:
                self.vifs[index] = (oldeth, bridge, oldmac, oldip)

        if plug:
            cli.execute("vif-plug","uuid=%s" % (uuid))

        if self.ips.get(int(device)):
            self.paramSet("other-config:xenrt-ip-%s%d" % (self.VIFSTEM, int(device)), self.ips.get(int(device)))

        return "%s%s" % (self.vifstem, device)

    def getIPSpec(self):
        ipSpec = []
        doSet = False
        for v in self.vifs:
            (eth, bridge, mac, currentIp) = v
            try:
                (newIP, mask) = self.paramGet("other-config", paramKey="xenrt-ip-%s" % eth).split("/")
                doSet = True
            except:
                newIP = None
                mask = None
            ipSpec.append((eth, newIP, mask))
        return ipSpec

    def setStaticIPs(self):
        ipSpec = self.getIPSpec()
        doSet = [x for x in ipSpec if x[1]]
        if doSet:
            self.getInstance().os.setIPs(ipSpec)

    def setupVCenter(self, vCenterVersion="5.5.0-update02"):
        vcenter = xenrt.lib.esx.getVCenter(guest=self, vCenterVersion=vCenterVersion)

    def setupUnsupGuest(self, getIP=None):
        self.tailored = True
        self.enlightenedDrivers = False
        self.noguestagent = True
        if self.getState() == "DOWN":
            self.lifecycleOperation('vm-start', specifyOn=False)
        if (getIP is None and not self.mainip) or getIP:
            vifname, bridge, mac, _ = self.vifs[0]
            self.mainip = self.getHost().arpwatch(bridge, mac, timeout=1800)
            self.vifs[0] = (vifname, bridge, mac, self.mainip)

    def setupDomainServer(self):
        self.installPowerShell()
        self.enablePowerShellUnrestricted()
        self.disableFirewall()
        domain = xenrt.TEC().lookup("DEFAULT_DOMAIN", None)
        xenrt.ActiveDirectoryServer(self, domainname=domain)

    def getVIFUUID(self, name):
        return self.getHost().parseListForUUID("vif-list",
                                               "device",
                                                name.strip(self.vifstem),
                                               "vm-uuid=%s" % (self.getUUID()))

    def plugVIF(self, eth):
        r = re.search(r"(\d+)", eth)
        vifuuid = self.getHost().parseListForUUID("vif-list",
                                                  "vm-uuid",
                                                  self.getUUID(),
                                                  "device=%s" % (r.group(1)))
        cli = self.getCLIInstance()
        cli.execute("vif-plug", "uuid=%s" % (vifuuid))

    def unplugVIF(self, eth):
        r = re.search(r"(\d+)", eth)
        vifuuid = self.getHost().parseListForUUID("vif-list",
                                                  "vm-uuid",
                                                  self.getUUID(),
                                                  "device=%s" % (r.group(1)))
        cli = self.getCLIInstance()
        cli.execute("vif-unplug", "uuid=%s" % (vifuuid))

    def setVIFRate(self, name, rate=None):
        device = re.sub(self.vifstem, "", name)
        vuuid = self.getHost().parseListForUUID("vif-list",
                                                "device",
                                                device,
                                                "vm-uuid=%s" %
                                                (self.getUUID()))
        cli = self.getCLIInstance()
        if rate:
            args = []
            args.append("uuid=%s" % (vuuid))
            args.append("qos_algorithm_type=ratelimit")
            cli.execute("vif-param-set", string.join(args))
            args = []
            args.append("uuid=%s" % (vuuid))
            args.append("qos_algorithm_params-kbps=%s" % (rate))
            cli.execute("vif-param-set", string.join(args))
        else:
            args = []
            args.append("uuid=%s" % (vuuid))
            args.append("qos_algorithm_type=\"\"")
            cli.execute("vif-param-set", string.join(args))
            args = []
            args.append("uuid=%s" % (vuuid))
            args.append("param-key=kbps")
            args.append("param-name=qos_algorithm_params")
            cli.execute("vif-param-remove", string.join(args))

    def removeAllVIFs(self):
        devs = self.getHost().minimalList("vif-list",
                                          "device",
                                          "vm-uuid=%s" % (self.getUUID()))
        vifs = list(self.vifs)
        for dev in devs:
            self.removeVIF(dev)

    def recreateVIFs(self, newMACs = False):
        """Recreate all VIFs we have in the guest's object config"""
        devs = self.getHost().minimalList("vif-list",
                                          "device",
                                          "vm-uuid=%s" % (self.getUUID()))
        vifs = list(self.vifs)
        for dev in devs:
            self.removeVIF(dev)
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

    def removeVIF(self, name):
        device = re.sub(self.vifstem, "", name)
        vuuid = self.getHost().parseListForUUID("vif-list",
                                                "vm-uuid",
                                                self.getUUID(),
                                                "device=%s" % (device))
        cli = self.getCLIInstance()
        cli.execute("vif-destroy", "uuid=%s" % (vuuid))
        if re.search(r"^\d+$", name):
            name = self.vifstem + name
        toremove = None
        for v in self.vifs:
            eth, bridge, mac, ip = v
            if eth == name:
                toremove = v
                break
        if toremove:
            self.vifs.remove(toremove)
        else:
            xenrt.TEC().warning(\
                "Could not find VIF '%s' in object metadata for VM '%s'" %
                (name, self.getName()))

    def getVIF(self, vifname=None, bridge=None, also_ipv6=False):
        """Return (mac, ip, vbridge) for the specified VIF"""
        vifs = self.getVIFs(also_ipv6=also_ipv6)
        if vifname:
            if vifs.has_key(vifname):
                return vifs[vifname]
        else:
            for v in vifs.keys():
                if also_ipv6:
                    mac, ip, br, ipv6_addrs = vifs[v]
                else:
                    mac, ip, br = vifs[v]
                if br == bridge:
                    return vifs[v]
        raise xenrt.XRTError("Could not find VIF %s for %s" %
                             (vifname, self.name))

    def getVIFs(self, network=None, bridge=None, also_ipv6=False):
        """Get details of the guest's VIFs, optionally filter by network or
        bridge name if specified. Returns a dictionary of (mac, ip, vbridge)
        keyed by vifname."""
        cli = self.getCLIInstance()
        reply = {}
        args = ("vm-uuid=%s" % self.getUUID()) \
               + (network and ' network-name-label="%s"' % network or "")
        vifs = self.getHost().minimalList("vif-list", args=args)
        for uuid in vifs:
            netuuid = self.getHost().genParamGet("vif", uuid, "network-uuid")
            mybridge = self.getHost().genParamGet("network", netuuid, "bridge")
            if bridge and bridge != mybridge: continue
            mac = self.getHost().genParamGet("vif", uuid, "MAC")
            device = self.getHost().genParamGet("vif", uuid, "device")            
            data = self.getHost().genParamGet("vm", self.getUUID(), "networks") 
            try:
                ip = re.search("%s/ip: (\d+\.\d+\.\d+\.\d+)" % (device), data).group(1)
            except:
                ip = None

            if also_ipv6:
                addrs = [addr.strip() for addr in data.split(';')]
                ipv6_addrs = []
                for addr in addrs:
                    if addr.startswith('%s/ipv6' % device):
                        ipv6_addrs.append(addr.split(':', 1)[1].strip())

                reply["%s%s" % (self.vifstem, device)] = (mac, ip, mybridge, ipv6_addrs)
            else:
                reply["%s%s" % (self.vifstem, device)] = (mac, ip, mybridge)

        return reply

    def changeVIF(self, name, bridge=None, mac=None):
        """Change the specified VIF to be on a different bridge or have a different MAC"""
        device = re.sub(self.vifstem, "", name)
        vuuid = self.getHost().parseListForUUID("vif-list",
                                                "vm-uuid",
                                                self.getUUID(),
                                                "device=%s" % (device))
        newmac, _, newbridge = self.getVIF(name)
        if bridge:
            newbridge = bridge
        if mac:
            newmac = mac
        cli = self.getCLIInstance()
        replug = False
        if self.getHost().genParamGet("vif", vuuid, "currently-attached") == "true":
            replug = True
            cli.execute("vif-unplug", "uuid=%s" % (vuuid))
        self.removeVIF(name)
        return self.createVIF(eth=name, bridge=newbridge, mac=newmac, plug=replug)

    def updateVIFDriver(self):
        if self.windows and self.getState() == "UP":
            if self.xmlrpcWindowsVersion() == "5.0":
                try:
                    tries = 2
                    while tries > 0:
                        tries = tries - 1
                        xenrt.sleep(60)
                        ref = None
                        for p in string.split(\
                                xenrt.TEC().lookup("PV_DRIVERS_DIR"), ";"):
                            pnet = "%s\\xennet.inf" % (p)
                            if self.xmlrpcFileExists(pnet):
                                ref = self.xmlrpcStart(\
                                    "\"c:\\devcon.exe\" -r update "
                                    "\"%s\" XEN\\vif" %(pnet))
                                break
                        if not ref:
                            raise xenrt.XRTError("Couldn't find xennet.inf.")
                        xenrt.sleep(30)
                        try:
                            self.xmlrpcWait(ref, timeout=600)
                            tries = 0
                        except Exception, e:
                            if tries > 0:
                                xenrt.TEC().warning("Retrying devcon.exe")
                            else:
                                raise e

                finally:
                    # Try to fetch setupapi.log from the VM
                    try:
                        xenrt.TEC().logverbose("Exception running devcon")
                        d = "%s/%s" % (xenrt.TEC().getLogdir(), self.getName())
                        if not os.path.exists(d):
                            os.makedirs(d)
                        self.xmlrpcGetFile("c:\\windows\\setupapi.log",
                                           "%s/setupapi.log" % (d))
                    except:
                        pass
            elif float(self.xmlrpcWindowsVersion()) >= 6.1:
                # Nothing needed, it should detect the hotplug I believe...
                pass
            else:
                self.xmlrpcExec("RunDll32.exe "
                                "Syssetup.dll,UpdatePnpDeviceDrivers", timeout=1800)

    def getState(self):
        status = self.getHost().parseListForParam("vm-list",
                                                  self.getUUID(),
                                                  "power-state")
        if self.statustext.has_key(status):
            status = self.statustext[status]
        return status

    def setState(self, state):
        action = {'UP'        :  { 'DOWN'      : self.shutdown,
                                   'SUSPENDED' : self.suspend,
                                   'PAUSED'    : self.pause},
                  'DOWN'      :  { 'UP'        : self.start,
                                   'SUSPENDED' : self.start,
                                   'PAUSED'    : self.start},
                  'SUSPENDED' :  { 'DOWN'      : self.resume,
                                   'UP'        : self.resume,
                                   'PAUSED'    : self.resume},
                  'PAUSED'    :  { 'DOWN'      : self.unpause,
                                   'UP'        : self.unpause,
                                   'SUSPENDED' : self.unpause}}
        while not self.getState() == state:
            action[self.getState()][state]()

    def pause(self):
        self.lifecycleOperation("vm-pause")

    def unpause(self):
        self.lifecycleOperation("vm-unpause")

    def lifecycleOperation(self,
                           command,
                           force=False,
                           specifyOn=True,
                           timer=None,
                           extraArgs=None,
                           extraTimeout=0,
                           timeout=None
                           ):
        """Perform a basic VM lifecycle operation"""
        cli = self.getCLIInstance()
        if force:
            flags = "--force"
        else:
            flags = ""
        defaultTimeout = 1800
        if command in ('vm-start', 'vm-resume'):
            defaultTimeout = 3600 + extraTimeout
            if self.getHost().pool and specifyOn:
                # With pooling we can make these happen on a specified host
                flags = flags + " on=\"%s\"" % (self.getHost().getMyHostName())
        elif command == 'vm-suspend':
            defaultTimeout = 3600 + extraTimeout
        if extraArgs: flags = flags + " " + extraArgs
        domid = None
        if command in ['vm-suspend', 'vm-reboot']:
            try:
                domid = self.getDomid()
            except:
                pass
        if timeout is None:
            timeout = defaultTimeout
        try:
            if timer:
                timer.startMeasurement()
            cli.execute(command,
                        "uuid=\"%s\" %s" % (self.getUUID(), flags),
                        timeout=timeout)
            if timer:
                timer.stopMeasurement()
        except xenrt.XRTFailure, e:
            if re.search(r"VM failed to shutdown before the timeout expired", e.reason) or \
                         re.search(r"Vmops.Domain_shutdown_for_wrong_reason", e.reason):
                # Might be a bluescreen etc.
                try:
                    self.checkHealth(noreachcheck=True, desc=command)
                except xenrt.XRTFailure, f:
                    if not re.search(r"Domain running but not reachable", f.reason):
                        raise
            raise
        if command in ('vm-start', 'vm-resume', 'vm-reboot'):
            try:
                # If we let VM randomly choose its host, we should find out
                # which host it's currently running on.
                pool = self.getHost().pool
                if pool and not specifyOn:
                    hostUUID = pool.master.genParamGet("vm",
                                                       self.getUUID(),
                                                       "resident-on")
                    self.setHost(pool.getHost(hostUUID))
                xenrt.TEC().logverbose("Guest %s domid is %u" %
                                       (self.getName(), self.getDomid()))
            except:
                pass
        if command in ['vm-suspend', 'vm-reboot']:
            # Check the old domain isn't still left behind (CA-32756)
            if domid:
                ld = self.host.listDomains()
                for domname in ld:
                    details = ld[domname]
                    if details[0] == domid:
                        if details[3] == self.host.STATE_DYING:
                            raise xenrt.XRTFailure("CA-32756 'Dying' domain left behind after suspend/reboot")
                        else:
                            raise xenrt.XRTFailure("Domain left behind after suspend/reboot")


    def shutdown(self, force=False, again=False, againOK=False):
        cli = self.getCLIInstance()
        try:
            domid = self.getDomid()
        except:
            domid = None
        args = ["uuid=\"%s\"" % (self.getUUID())]
        if force:
            print "with force"
            args.append("--force")
        try:
            if self.enlightenedDrivers or force:
                if not force:
                    self.waitForShutdownReady()
                try:
                    cli.execute("vm-shutdown", string.join(args))
                except xenrt.XRTFailure, e:
                    if re.search(r"VM failed to shutdown before the timeout expired", e.reason):
                        self.checkHealth(noreachcheck=True)
                    elif re.search(r"Vmops.Domain_shutdown_for_wrong_reason", e.reason):
                        self.checkHealth(noreachcheck=True)
                    raise e
            else:
                self.unenlightenedShutdown()
            self.poll("DOWN")
        except Exception, e:
            if again or againOK:
                # Murder the darn thing
                args = ["uuid=\"%s\"" % (self.getUUID())]
                args.append("--force")
                cli.execute("vm-shutdown", string.join(args))
                self.poll("DOWN")
                if againOK:
                    return
            raise

        # Check the old domain isn't still left behind (CA-32756)
        if domid:
            ld = self.host.listDomains()
            for domname in ld:
                details = ld[domname]
                if details[0] == domid:
                    if details[3] == self.host.STATE_DYING:
                        raise xenrt.XRTFailure("CA-32756 'Dying' domain left behind after shutdown")
                    else:
                        raise xenrt.XRTFailure("Domain left behind after shutdown")

    def destroyAdditionalDisks(self):
        """ destroys all additional disks other than disk 0."""
        cli = self.getHost().getCLIInstance()
        uuids = self.getHost().minimalList("vbd-list",
                                    args="vm-uuid=%s type=Disk" % (self.getUUID()))
        for uuid in uuids:
            if self.getHost().genParamGet("vbd", uuid, "userdevice") != "0":
                vdiuuid = self.host.genParamGet("vbd", uuid, "vdi-uuid")
                cli.execute("vbd-destroy", "uuid=%s" % (uuid))
                cli.execute("vdi-destroy", "uuid=%s" % (vdiuuid))

    def uninstall(self, destroyDisks = False):
        """ Uninstall a guest.

        @destroyDisks (boolean): if True, destroy all disks other than disk 0 before it runs vm-destroy.
        """
        before = self.getHost().minimalList("vbd-list", 
                                       "vdi-uuid",
                                       "vm-uuid=%s type=Disk" % 
                                       (self.getUUID()))

        self.setState("DOWN")
        if destroyDisks:
            self.destroyAdditionalDisks()
        self.lifecycleOperation("vm-uninstall", force=True)
        srs = self.getHost().getSRs()
        cli = self.getHost().getCLIInstance()
        for sr in srs:
            try:
                cli.execute("sr-scan", "uuid=%s" % (sr))
            except Exception, e:
                xenrt.TEC().warning("Exception on sr-scan of %s: %s" % 
                                    (sr, str(e)))
        self.getHost().removeGuest(self)
        after = self.getHost().minimalList("vdi-list")
        for vdi in before:
            if vdi in after:
                raise xenrt.XRTFailure("VDI still present after uninstall",
                                       "%s" % (vdi))

    def getMaxSupportedVCPUCount(self):
        """ Find maximum supported number of VCPU for this guest."""

        limits = []

        if not self.distro:
            self.determineDistro()

        # Guest has its own limitation
        if self.distro:
            if self.distro in xenrt.TEC().lookup(["GUEST_LIMITATIONS"]):
                itemname = "MAX_VM_VCPUS"
                if not self.windows and self.arch and "64" in self.arch:
                    xenrt.TEC().logverbose("x64 is detected.")
                    if "MAX_VM_VCPUS64" in xenrt.TEC().lookup(["GUEST_LIMITATIONS", self.distro]):
                        itemname = "MAX_VM_VCPUS64"
                    else:
                        xenrt.TEC().logverbose("No infor for 64 bit distro. Using 32 bit limit...")
                if itemname in xenrt.TEC().lookup(["GUEST_LIMITATIONS", self.distro]):
                    limits.append(int(xenrt.TEC().lookup(["GUEST_LIMITATIONS", self.distro, itemname])))
                    xenrt.TEC().logverbose("%s supports up to %d VCPUs." % (self.distro, limits[-1]))
                else:
                    xenrt.TEC().warning("Supported number of VCPU for %s is not declared." % self.distro)
            else:
                xenrt.TEC().warning("%s has no GUEST_LIMITATIONS config." % self.distro)
        else:
            xenrt.TEC().warning("Cannot detect distro.")

        # XS has limitation
        pver = xenrt.TEC().lookup("PRODUCT_VERSION", None)
        if pver:
            if "MAX_VM_VCPUS" in xenrt.TEC().lookup(["VERSION_CONFIG", pver]):
                limits.append(int(xenrt.TEC().lookup(["VERSION_CONFIG", pver, "MAX_VM_VCPUS"])))
                xenrt.TEC().logverbose("%d VCPUs per VM on %s host." % (limits[-1], pver))
            else:
                xenrt.TEC().warning("MAX_VM_VCPUS is not declared for %s host." % pver)
        else:
            xenrt.TEC().warning("Cannot determine PRODUCT VERSION")

        # HVM cannot have more vcpus than pcpus.
        pcpus = None
        for hostname in xenrt.TEC().registry.hostList():
            host = xenrt.TEC().registry.hostGet(hostname)
            if not pcpus or pcpus > host.getCPUCores():
                pcpus = host.getCPUCores()
        if pcpus:
            limits.append(pcpus)

        # Limit based on memory size
        guestmem = self.memory
        if not guestmem and self.distro:
            host = xenrt.TEC().registry.hostGet("RESOURCE_HOST_DEFAULT")
            guestmem = host.getTemplateParams(self.distro, self.arch).defaultMemory
        if guestmem:
            memlimit = guestmem / int(xenrt.TEC().lookup("RND_VCPUS_MB_PER_VCPU", "64"))
            limits.append(memlimit)
        else:
            xenrt.TEC().warning("Cannot determine guest memory")

        if limits:
            return min(limits)

        # Pick 4 if no limitation is declared.
        xenrt.TEC().warning("None of guest limit, host limit and XS limit is found.")
        return 4

    def setRandomVcpus(self):
        maxVcpusSupported = self.getMaxSupportedVCPUCount()
        maxRandom = min(maxVcpusSupported, 4)
        xenrt.TEC().logverbose("Setting random vcpus for VM between 1 and %d (max supported %d)" % (maxRandom, maxVcpusSupported))
        randomVcpus = random.randint(1, maxRandom)
        with xenrt.GEC().getLock("RND_VCPUS"):
            dbVal = int(xenrt.TEC().lookup("RND_VCPUS_VAL", "0"))
            if dbVal != 0:
                xenrt.TEC().logverbose("Using vcpus from DB: %d" % dbVal)
                if dbVal > maxVcpusSupported:
                    xenrt.TEC().warning("DB vcpus value is greater than maxVcpusSupported!")
                self.setVCPUs(dbVal)
            else:
                xenrt.TEC().logverbose("Randomly chosen vcpus is %d" % randomVcpus)
                self.setVCPUs(randomVcpus)
                xenrt.GEC().config.setVariable("RND_VCPUS_VAL",str(randomVcpus))
                xenrt.GEC().dbconnect.jobUpdate("RND_VCPUS_VAL",str(randomVcpus))

    def setRandomCoresPerSocket(self, host, vcpus):
        xenrt.TEC().logverbose("Setting random cores per socket....")

        if not isinstance(host, xenrt.lib.xenserver.ClearwaterHost) or not self.windows:
            xenrt.TEC().logverbose("Refusing to set cores-per-socket on anything prior \
                to Clearwater or non-windows guests")
            return

        # Max cores per socket makes sure we don't exceed the number of cores per socket on the host
        cpuCoresOnHost = host.getCPUCores()
        socketsOnHost  = host.getNoOfSockets()
        maxCoresPerSocket = cpuCoresOnHost / socketsOnHost
        maxDistroSockets = xenrt.TEC().lookup(["GUEST_LIMITATIONS", self.distro, "MAXSOCKETS"], None)

        xenrt.TEC().logverbose("cpuCoresonHost: %s, socketsonHost: %s, maxCoresPerSocket: %s, maxDistroSockets: %s" % (cpuCoresOnHost, socketsOnHost, maxCoresPerSocket, maxDistroSockets))

        if vcpus != None:
            # This gives us all the factors of the vcpus specified
            possibleCoresPerSocket = [x for x in range(1, vcpus+1) if vcpus % x == 0]
            xenrt.TEC().logverbose("possibleCoresPerSocket is %s" % possibleCoresPerSocket)

            # This eliminates the factors that would exceed the host's cores per socket
            validCoresPerSocket = [x for x in possibleCoresPerSocket if x <= maxCoresPerSocket]
            xenrt.TEC().logverbose("validCoresPerSocket is %s" % validCoresPerSocket)

            if maxDistroSockets:
                # This eliminates the factors that would exceed the distro's max sockets
                validCoresPerSocket = [x for x in validCoresPerSocket if vcpus / x <= int(maxDistroSockets)]
                xenrt.TEC().logverbose("validCoresPerSocket after distro MAXSOCKETS taken into account is %s" % validCoresPerSocket)

            # Then choose a value from here
            coresPerSocket = random.choice(validCoresPerSocket)

            with xenrt.GEC().getLock("RND_CORES_PER_SOCKET"):
                dbVal = int(xenrt.TEC().lookup("RND_CORES_PER_SOCKET_VAL", "0"))

                if dbVal in validCoresPerSocket:
                    xenrt.TEC().logverbose("Using Randomly chosen cores-per-socket from DB: %d" % dbVal)
                    self.setCoresPerSocket(dbVal)
                else:
                    xenrt.TEC().logverbose("Randomly choosen cores-per-socket is %s" % coresPerSocket)
                    self.setCoresPerSocket(coresPerSocket)
                    xenrt.GEC().config.setVariable("RND_CORES_PER_SOCKET_VAL", str(coresPerSocket))
                    xenrt.GEC().dbconnect.jobUpdate("RND_CORES_PER_SOCKET_VAL", str(coresPerSocket))

    def cpuget(self):
        """Return the initial number of vcpus this guest has"""
        return int(self.paramGet("VCPUs-at-startup"))

    def cpuset(self, cpus, live=False):
        self.vcpus = cpus

        if live:
            cli = self.getCLIInstance()
            cli.execute("vm-vcpu-hotplug", "new-vcpus=%s vm=%s" %
                       (cpus, self.name))
            if self.getState() == "UP":
                # See if the guest actually has what we asked for.
                self.check()
        else:
            xenrt.TEC().logverbose("Setting %s vCPUS to %u" % (self.name, cpus))
            # Are we increasing or decreasing from the current value
            if cpus > self.cpuget():
                self.paramSet("VCPUs-max", "%u" % (cpus))
                self.paramSet("VCPUs-at-startup", "%u" % (cpus))
            else:
                self.paramSet("VCPUs-at-startup", "%u" % (cpus))
                self.paramSet("VCPUs-max", "%u" % (cpus))
            c = self.paramGet("VCPUs-max")
            if int(c) != cpus:
                raise xenrt.XRTFailure("VM VCPUs-max %s does not match the "
                                       "requested %u" % (c, cpus))
            c = self.paramGet("VCPUs-at-startup")
            if int(c) != cpus:
                raise xenrt.XRTFailure("VM VCPUs-at-startup %s does not match the "
                                       "requested %u" % (c, cpus))

    def setCPUCredit(self, weight=None, cap=None):
        cli = self.getCLIInstance()

        xenrt.TEC().logverbose("Setting weight: %s, cap: %s." % (weight, cap))
        if weight and cap >= 0:
            args = []
            args.append("uuid=%s" % (self.getUUID()))
            args.append("VCPUs-params-weight=%s" % (weight))
            args.append("VCPUs-params-cap=%s" % (cap))
            cli.execute("vm-param-set", string.join(args))
        else:
            args = []
            args.append("uuid=%s" % (self.getUUID()))
            args.append("param-key=weight")
            args.append("param-name=VCPUs-params")
            cli.execute("vm-param-remove", string.join(args))
            args = []
            args.append("uuid=%s" % (self.getUUID()))
            args.append("param-key=cap")
            args.append("param-name=VCPUs-params")
            cli.execute("vm-param-remove", string.join(args))

    def getCPUCredit(self):
        cap = None
        weight = None
        d = self.getHost().genParamGet("vm", self.getUUID(), "VCPUs-params")
        for i in [ x.split(": ") for x in d.split("; ") ]:
            if i[0] == "cap":
                cap = int(i[1])
            elif i[0] == "weight":
                weight = int(i[1])
        return weight, cap

    def memget(self):
        """Return the static memory allocation in MB for this guest"""
        return int(self.paramGet("memory-dynamic-max"))/xenrt.MEGA

    def memset(self, memory):
        """Set the memory of the VM to memory MB"""
        self.memory = memory
        xenrt.TEC().logverbose("Setting %s memory to %uMB" % (self.name, memory))
        cli = self.getCLIInstance()
        # Set the required memory
        self.paramSet("memory-static-min", "%u" % (memory * xenrt.MEGA))
        self.paramSet("memory-dynamic-min", "%u" % (memory * xenrt.MEGA))
        self.paramSet("memory-dynamic-max", "%u" % (memory * xenrt.MEGA))
        self.paramSet("memory-static-max", "%u" % (memory * xenrt.MEGA))
        # Check we've set it
        for x in ("memory-dynamic-max",
                  "memory-dynamic-min",
                  "memory-static-max",
                  "memory-static-min"):
            m = (int(self.paramGet(x))/xenrt.MEGA)
            if m != memory:
                raise xenrt.XRTFailure("VM memory %uMB does not match the "
                                       "requested %uMB" % (m, memory))

    def getBootParams(self):
        return self.paramGet("PV-args")

    def setBootParams(self, p):
        self.paramSet("PV-args", p)

    def paramGet(self, paramName, paramKey=None):
        usecli = self.getCLIInstance()
        args = ["uuid=%s" % (self.getUUID())]
        args.append("param-name=%s" % (paramName))
        if paramKey:
            args.append("param-key=%s" % (paramKey))
        data = usecli.execute("vm-param-get", string.join(args),
                              strip=True)
        return data

    def paramSet(self, paramName, paramValue):
        usecli = self.getCLIInstance()
        data = usecli.execute("vm-param-set",
                              "uuid=%s %s=\"%s\"" %
                              (self.getUUID(),
                               paramName,
                               str(paramValue).replace('"', '\\"')))

    def paramRemove(self, name, key):
        cli = self.getCLIInstance()
        cli.execute("vm-param-remove",
                    "uuid=%s param-name=%s param-key=%s" %
                    (self.getUUID(), name, key))

    def paramClear(self, name):
        cli = self.getCLIInstance()
        cli.execute("vm-param-clear",
                    "uuid=%s param-name=%s" % (self.getUUID(), name))

    def listVBDs(self):
        """Return a dictionary of the guest's VBDs and their parameters.
        Parameter tuple is (size in MB, min_size in MB, function, qos)"""
        reply = {}
        cli = self.getCLIInstance()

        vbds = self.getHost().minimalList("vbd-list",
                                      args="vm-uuid=%s" % (self.getUUID()))
        for uuid in vbds:
            device = self.getHost().genParamGet("vbd", uuid, "userdevice")
            vdiuuid = self.getHost().genParamGet("vbd", uuid, "vdi-uuid")
            
            if xenrt.isUUID(vdiuuid):
                sizebytes = self.getHost().genParamGet("vdi", vdiuuid, "virtual-size")
                size = int(sizebytes) / xenrt.MEGA
            else:
                sizebytes = 0
                size = 0
            data = self.getHost().genParamGet("vbd", uuid, "qos_algorithm_params")
            try:
                qos = int(re.search("class: ([0-9]+)", data).group(1))
            except:
                qos = None
            if device in ('0', 'hda', 'sda', 'xvda'):
                reply[device] = (size, 0, "root", qos)
            else:
                reply[device] = (size, 0, None, qos)
        return reply

    def listVBDUUIDs(self, vbdtype=None):
        """Return a list of VBD UUIDs for this VM with optional type."""
        if vbdtype:
            args = "vm-uuid=%s type=%s" % (self.getUUID(), vbdtype)
        else:
            args = "vm-uuid=%s" % (self.getUUID())
        return self.getHost().minimalList("vbd-list", args=args)

    def countVBDs(self):
        return len(self.getHost().minimalList("vbd-list",
                                              args="vm-uuid=%s" % 
                                                   (self.getUUID())))

    def countVIFs(self):
        return len(self.getHost().minimalList("vif-list",
                                              args="vm-uuid=%s" % 
                                                   (self.getUUID())))

    def getAttachedVDIs(self):
        """Get all currently attached VDIs"""
        vbds = self.getHost().minimalList("vbd-list",args="vm-uuid=%s type=Disk" % 
                                                     (self.getUUID()))
        vdis = []
        for vbd in vbds:
            if self.getHost().genParamGet("vbd",vbd,"currently-attached") == "true":
                vdis.append(self.getHost().genParamGet("vbd", vbd, "vdi-uuid"))

        return vdis

    def listDiskDevices(self):
        """Return a list of VBD device names"""
        return self.getHost().minimalList("vbd-list",
                                          "userdevice",
                                          "vm-uuid=%s type=Disk" % 
                                          (self.getUUID()))

    def removeDisk(self, userdevice, keepvdi=False):
        cli = self.getCLIInstance()
        vbduuid = self.getDiskVBDUUID(userdevice)
        vdiuuid = self.getDiskVDIUUID(userdevice)
        args = []
        args.append("uuid=%s" % (vbduuid))
        cli.execute("vbd-destroy", string.join(args))
        if not keepvdi:
            args = []
            args.append("uuid=%s" % (vdiuuid))
            cli.execute("vdi-destroy", string.join(args))
        xenrt.TEC().logverbose("Removed %s." % (userdevice))

    def createDisk(self, 
                   sizebytes=None, 
                   sruuid=None, 
                   userdevice=None, 
                   bootable=False, 
                   plug=True, 
                   vdiuuid=None, 
                   returnVBD=False,
                   returnDevice=False,
                   smconfig=None,
                   mode="RW"):
        # Default to sequence specified default SR.
        sruuid = self.chooseSR(sruuid)

        # Default to lowest available device number.
        if not userdevice:
            allowed = self.getHost().genParamGet("vm", self.getUUID(),
                                                 "allowed-VBD-devices")
            userdevice = str(min([int(x) for x in allowed.split("; ")]))

        cli = self.getCLIInstance()
        existingVDI = vdiuuid
        if not vdiuuid:
            vdiuuid = self.getHost().createVDI(sizebytes, sruuid, smconfig)
        # Create the VBD.
        args = []
        args.append("device=%s" % (userdevice))
        args.append("vdi-uuid=%s" % (vdiuuid))
        args.append("vm-uuid=%s" % (self.getUUID()))
        args.append("mode=%s" % mode)
        args.append("type=Disk")
        if bootable:
            args.append("bootable=true")
        vbduuid = cli.execute("vbd-create", string.join(args), strip=True)
        # Set other-config-owner
        args = []
        args.append("other-config-owner=")
        args.append("uuid=%s" % (vbduuid))
        cli.execute("vbd-param-set", string.join(args))
        # Plug the disk.
        if plug and self.getState() == "UP":
            args = []
            args.append("uuid=%s" % (vbduuid))
            cli.execute("vbd-plug", string.join(args))
            xenrt.sleep(5)

        if existingVDI:
            xenrt.TEC().logverbose("Added existing VDI %s as %s." %
                                   (existingVDI, userdevice))
        else:
            xenrt.TEC().logverbose("Added %s of size %s using SR %s." % 
                                   (userdevice, sizebytes, sruuid))

        if returnVBD:
            return vbduuid
        elif returnDevice:
            return self.getHost().genParamGet("vbd", vbduuid, "device")
        else:
            return userdevice

    def getDiskSRType(self, device=0):
        vdiuuid = self.getDiskVDIUUID(device)
        sruuid = self.getHost().genParamGet("vdi",
                                            vdiuuid,
                                            "sr-uuid")
        return self.getHost().genParamGet("sr",
                                          sruuid,
                                          "type")

    def getDiskVBDUUID(self, device):
        return self.getHost().parseListForUUID("vbd-list",
                                               "userdevice",
                                               device,
                                               "vm-uuid=%s" % (self.getUUID()))

    def getDiskVDIUUID(self, device):
        uuid = self.getHost().parseListForOtherParam("vbd-list",
                                                     "userdevice",
                                                     device,
                                                     "vdi-uuid",
                                                     "vm-uuid=%s" %
                                                     (self.getUUID()))
        if uuid == "<not in database>":
            raise xenrt.XRTError("vdi-uuid for device %s for VM %s not found"
                                 % (device, self.getUUID()))
        return uuid

    def plugDisk(self, device):
        uuid = self.getDiskVBDUUID(device)
        cli = self.getCLIInstance()
        cli.execute("vbd-plug", "uuid=%s" % (uuid))

    def unplugDisk(self, device):
        uuid = self.getDiskVBDUUID(device)
        cli = self.getCLIInstance()
        cli.execute("vbd-unplug", "uuid=%s" % (uuid))

    def setDiskQoS(self, device, sched=None, value=None):
        vuuid = self.getDiskVBDUUID(device)
        cli = self.getCLIInstance()
        args = []
        args.append("uuid=%s" % (vuuid))
        args.append("qos_algorithm_type=\"\"")
        cli.execute("vbd-param-set", string.join(args))
        try:
            args = []
            args.append("uuid=%s" % (vuuid))
            args.append("param-key=sched")
            args.append("param-name=qos_algorithm_params")
            cli.execute("vbd-param-remove", string.join(args))
            args = []
            args.append("uuid=%s" % (vuuid))
            args.append("param-key=class")
            args.append("param-name=qos_algorithm_params")
            cli.execute("vbd-param-remove", string.join(args))
        except:
            pass
        if sched:
            args = []
            args.append("uuid=%s" % (vuuid))
            args.append("qos_algorithm_type=ionice")
            cli.execute("vbd-param-set", string.join(args))
            args = []
            args.append("uuid=%s" % (vuuid))
            args.append("param-name=qos_algorithm_params sched=%s class=%d" %
                        (sched, value))
            cli.execute("vbd-param-add", string.join(args))

    def resizeDisk(self, device, size):
        # device is the userdevice field from vm-disk-list
        vuuid = self.getDiskVDIUUID(device)
        cli = self.getCLIInstance()
        args = []
        args.append("uuid=\"%s\"" % (vuuid))
        args.append("disk-size=%u" % (size * xenrt.MEGA))
        cli.execute("vdi-resize", string.join(args))

    def getDomainType(self):
        """Get the domain type (hvm or linux) of a running VM"""
        uuid = self.getUUID()
        domains = self.getHost().listDomains()
        if domains.has_key(uuid):
            if domains[uuid][5]:
                return "hvm"
            return "linux"
        raise xenrt.XRTError("Cannot find domain type")        

    def getDomainFlags(self):
        """Get the domain flags (acpi, apic, ...) of a running VM"""
        data = self.paramGet("platform")
        x = data.findall("(\w+): true", data)
        x.sort()
        return x

    def makeNonInteractive(self):
        self.paramSet("PV-args", "noninteractive")

    def enablePXE(self, pxe=True, disableCD=False):
        try:
            self.paramRemove("HVM-boot-params", "order")
        except:
            pass
        if pxe:
            if disableCD:
                self.paramSet("HVM-boot-params-order", "cn")
            else:
                self.paramSet("HVM-boot-params-order", "dcn")
            self.paramSet("HVM-boot-policy", "BIOS order")
        else:
            if disableCD:
                self.paramSet("HVM-boot-params-order", "c")
            else:
                self.paramSet("HVM-boot-params-order", "dc")

    def chooseSR(self, sr=None):
        return self.getHost().chooseSR(sr=sr)

    def importVM(self, host, image, preserve=False, sr=None, metadata=False, imageIsOnHost=False, ispxeboot=False, vifs=[]):
        sruuid = self.chooseSR(sr)
        cli = host.getCLIInstance()
        args = []
        args.append("filename='%s'" % (image))
        args.append("sr-uuid=%s" % (sruuid))
        if preserve:
            args.append("preserve=true")
        if metadata:
            args.append("metadata=true")

        if imageIsOnHost:
            data = host.execdom0("xe vm-import " + string.join(args), timeout=3600)
        else:
            data = cli.execute("vm-import",string.join(args), timeout=3600)

        if re.search(r"Not implemented", data):
            raise xenrt.XRTError("Feature not implemented")
        r = re.search(r"New VM uuid: (\S+)", data)
        if not r:
            r = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}"
                          "-[0-9a-f]{12})", data)
        if not r:
            raise xenrt.XRTFailure("Unable to find UUID for imported VM")
        uuid = r.group(1)
        self.uuid = uuid
        cli.execute("vm-param-set",
                    "uuid=%s name-label=\"%s\"" % (uuid, self.name))
        if not ispxeboot:
            if not vifs:
                self.reparseVIFs()
                self.vifs.sort()
            else:
                self.vifs = vifs
            self.recreateVIFs(newMACs=True)
        self.existing(host)

    def migrateVM(self, host, live="false", fast=False, timer=None):

        # yuk. kill me now.
        if live == True:
            live = "true"
        elif live == False:
            live = "false"

        cli = self.getCLIInstance()
        if live == "true" and not self.windows:
            self.startLiveMigrateLogger()
        if timer:
            timer.startMeasurement()
        try:
            cli.execute("vm-migrate",
                        "uuid=%s host-uuid=%s live=%s" %
                        (self.getUUID(), host.getMyHostUUID(), live))
        except xenrt.XRTFailure, e:
            if re.search(r"VM failed to shutdown before the timeout expired",
                         e.reason) or \
                         re.search(r"Vmops.Domain_shutdown_for_wrong_reason",
                                   e.reason):
                # Might be a bluescreen etc.
                try:
                    self.checkHealth(noreachcheck=True)
                except xenrt.XRTFailure, f:
                    if re.search(r"Domain running but not reachable",
                                 f.reason):
                        # Report the original failure
                        raise e
                    raise f
            raise e
        if timer:
            timer.stopMeasurement()
        if live == "true" and not self.windows:
            self.stopLiveMigrateLogger()
        if xenrt.TEC().lookup("EXTRA_TIME", False, boolean=True):
            boottime = 720
        else:
            boottime = 360
        self.setHost(host)
        if not fast:
            if not self.windows:
                self.waitForSSH(boottime, desc="Guest migrate SSH check")
            else:
                self.waitForDaemon(boottime, desc="Guest migrate XML-RPC check")

    def copyVM(self, name=None, timer=None, sruuid=None, noIP=True):
        return self._cloneCopyVM("copy", name, timer, sruuid, noIP=noIP)

    def cloneVM(self, name=None, timer=None, sruuid=None, noIP=True):
        if sruuid:
            xenrt.TEC().warning("Deprecated use of sruuid in cloneVM. Should "
                                "use copyVM instead.")
        return self._cloneCopyVM("clone", name, timer, sruuid, noIP=noIP)

    def instantiateSnapshot(self, uuid, name=None, timer=None, sruuid=None, noIP=False):
        return self._cloneCopyVM("instance", name, timer, sruuid, uuid=uuid, noIP=noIP)

    def cloneTemplate(self, name=None, timer=None, sruuid=None, noIP=True):
        return self._cloneCopyVM("instance", name, timer, sruuid, noIP=noIP)

    def _cloneCopyVM(self, operation, name, timer, sruuid, uuid=None, noIP=True):
        cli = self.getCLIInstance()
        g_uuid = None

        if not name:
            stem = "%s-%s-" % (self.getName(), operation)            
            allnames = self.getHost().listGuests()
            existing = []
            for n in allnames:
                if n.startswith(stem):
                    rest = n[len(stem):]
                    if rest.isdigit():
                        existing.append(int(rest))
            name = "%s%s" % (stem, existing and max(existing)+1 or 0)
        if timer:
            timer.startMeasurement()

        args = []
        args.append("new-name-label=\"%s\"" % (name.replace('"', '\\"')))
        # Full VM copy.
        if operation == "copy" or sruuid:
            args.append("uuid=%s" % (self.getUUID()))
            if sruuid: 
                args.append("sr-uuid=%s" % (sruuid))
            g_uuid = cli.execute("vm-copy", string.join(args), timeout=5400).strip()
        # Try a fast clone.
        elif operation == "clone":
            args.append("uuid=%s" % (self.getUUID()))
            g_uuid = cli.execute("vm-clone", string.join(args)).strip()
        # Instantiate a snapshot.
        elif operation == "instance":
            if uuid is None:
                uuid = self.getUUID()
            template = self.getHost().genParamGet("template", 
                                                  uuid, 
                                                  "name-label")
            args.append("template=\"%s\"" % (template))
            g_uuid = cli.execute("vm-install", string.join(args)).strip()
        else:
            raise xenrt.XRTError("Invalid operation: %s" % (operation))    

        if timer:
            timer.stopMeasurement()

        g = copy.copy(self) 
        g.special = copy.copy(self.special)
        g.name = name
        g.uuid = g_uuid
        g.mainip = None
        g.vifs = []


        # Get the new VIFs:
        g.reparseVIFs()
        g.vifs.sort()
        xenrt.TEC().logverbose("Found VIFs: %s" % (g.vifs))
        g.recreateVIFs(newMACs=True)
        # Default IP to the first one we find unless g has managebridge or
        # managenetwork defined.
        vifs = ((g.managenetwork or g.managebridge)
                and g.getVIFs(network=g.managenetwork, \
                              bridge=g.managebridge).keys()
                or g.vifs)

        ips = filter(None, map(lambda (nic, vbridge, mac, ip):ip, vifs))
        if ips and not noIP:
            g.mainip = ips[0]
        vifs.sort()
        if g.use_ipv6 and vifs:
            g.mainip = g.getIPv6AutoConfAddress(device=vifs[0][0])
        elif g.mainip: 
            if re.match("169\.254\..*", g.mainip):
                raise xenrt.XRTFailure("VM gave itself a link-local address.")

        g.setHostnameViaXenstore()
        return g

    def snapshot(self, name=None, quiesced=False, quiesceretries=3):
        """Perform a snapshot of the VM. This returns a template UUID."""
        uuid = None
        cli = self.getCLIInstance()
        if not name:
            name = xenrt.randomGuestName()
        state = self.getState()

        command = "uuid=%s new-name-label=%s" % (self.getUUID(), name)
        if quiesced:
            lastexception = None
            xenrt.TEC().logverbose("Attempting quiesced snapshot of VM.")
            for attempt in range(quiesceretries):
                xenrt.TEC().logverbose("Attempt %s." % (attempt))
                try: 
                    uuid = cli.execute("vm-snapshot-with-quiesce", 
                                        command, strip=True)
                    break
                except Exception, e:
                    lastexception = e
                    xenrt.sleep(5)
                    if state == "UP":
                        # Make sure the VM is still healthy - this is to
                        # catch any BSOD that the VM may have had
                        self.checkHealth()
            if not uuid:
                if lastexception:
                    raise lastexception
                raise xenrt.XRTFailure("Snapshot with quiesce failed.")
        else:
            if self.windows and state == "UP":
                xenrt.TEC().warning("Snapshot of running Windows VM taken")
            xenrt.TEC().logverbose("Attempting snapshot of VM.")
            try:
                uuid = cli.execute("vm-snapshot", command, strip=True)
            except Exception, e:
                if state == "UP":
                    self.checkHealth()
                raise e
#        self.checkSnapshot(uuid)
#        snapvdis = self.host.minimalList("vbd-list", 
#                                         "vdi-uuid", 
#                                         "vm-uuid=%s type=Disk" % (uuid))
#        self.checkSnapshotVDIs(snapvdis)
        return uuid

    SNAPSHOT_CHECK_PARAMS = ['memory-dynamic-max',
                             'memory-dynamic-min',
                             'memory-static-max',
                             'memory-static-min',
                             'VCPUs-max',
                             'VCPUs-at-startup',
                             'actions-after-shutdown',
                             'actions-after-reboot',
                             'actions-after-crash',
                             'HVM-boot-policy',
                             'affinity',
                             'ha-restart-priority',
                             'ha-always-run']

    def checkSnapshot(self, uuid):
        """Check that the snapshot with UUID, uuid, matches
           this guest."""
        host = self.getHost()

        for param in self.SNAPSHOT_CHECK_PARAMS:

            templatevalue = host.genParamGet("template", uuid, param)
            vmvalue = self.paramGet(param)
            if templatevalue != vmvalue:
                raise xenrt.XRTFailure("Snapshot param %s does not match "
                                       "the VM param" % (param),
                                       "Template %s param %s '%s' does not "
                                       "match VM %s '%s'" %
                                       (uuid,
                                        param,
                                      templatevalue,
                                        self.getName(),
                                        vmvalue))
        if host.genParamGet("template", uuid, "is-a-template") != "true":
            raise xenrt.XRTFailure("Snapshot not is-a-template",
                                   "Snapshot UUID %s" % (uuid))
        if host.genParamGet("template", uuid, "is-a-snapshot") != "true":
            raise xenrt.XRTFailure("Snapshot not is-a-snapshot",
                                   "Snapshot UUID %s" % (uuid))
        if self.getState() == "SUSPENDED":
            if host.lookup("SNAPSHOT_OF_SUSPENDED_VM_IS_SUSPENDED",
                            False,
                            boolean=True):
                if host.genParamGet("template", uuid, "power-state") != \
                                    "suspended":
                    raise xenrt.XRTFailure("Snapshot not suspended",
                                           "Snapshot UUID %s" % (uuid))
            else:
                if host.genParamGet("template", uuid, "power-state") != \
                                    "halted":
                    raise xenrt.XRTFailure("Snapshot not halted",
                                           "Snapshot UUID %s" % (uuid))
        else:
            if host.genParamGet("template", uuid, "power-state") not in \
                                ["halted", "suspended"]:
                raise xenrt.XRTFailure("Snapshot not halted",
                                       "Snapshot UUID %s" % (uuid))

        # Make sure the snapshot linkage is correct.
        try:
            suuid = host.genParamGet("template", uuid, "snapshot-of")
        except xenrt.XRTFailure, e:
            xenrt.TEC().warning("Failed to get snapshot-of. (%s)" % (str(e)))
            suuid = host.genParamGet("template", uuid, "snapshot_of")

        if suuid != self.getUUID():
            raise xenrt.XRTFailure("Snapshot snapshot-of does not match "
                                   "original VM",
                                   "Template %s, VM %s" %
                                   (suuid, self.getUUID()))
        vmsnaps = self.paramGet("snapshots").split("; ")
        if not uuid in vmsnaps:
            raise xenrt.XRTFailure("Snapshot UUID not found in VM's "
                                   "snapshots list",
                                   "Template %s, VM snapshot list %s" %
                                   (uuid, string.join(vmsnaps)))

        # For each VIF belonging to the VM check a matching VIF was
        # created for the snapshot and that the MACs match.
        vmvifs = {}
        snapvifs = {}
        for vif in host.minimalList("vif-list",
                                              "uuid",
                                              "vm-uuid=%s" % (self.getUUID())):
            device = host.genParamGet("vif", vif, "device")
            mac = host.genParamGet("vif", vif, "MAC")
            network = host.genParamGet("vif", vif, "network-uuid")
            vmvifs[device] = (mac, network)
        for vif in host.minimalList("vif-list",
                                    "uuid",
                                    "vm-uuid=%s" % (uuid)):
            device = host.genParamGet("vif", vif, "device")
            mac = host.genParamGet("vif", vif, "MAC")
            network = host.genParamGet("vif", vif, "network-uuid")
            snapvifs[device] = (mac, network)
        for vmdevice in vmvifs.keys():
            if not snapvifs.has_key(vmdevice):
                raise xenrt.XRTFailure("A network device associated with "
                                       "the VM was not found in the snapshot",
                                       "Device %s missing from %s" %
                                       (vmdevice, uuid))
            vmmac, vmnetwork = vmvifs[vmdevice]
            snapmac, snapnetwork = snapvifs[vmdevice]
            if vmmac != snapmac:
                raise xenrt.XRTFailure("Snapshot MAC does not match the "
                                       "original VM MAC",
                                       "Device %s, VM MAC %s, snapshot MAC %s"
                                       % (vmdevice, vmmac, snapmac))
            if vmnetwork != snapnetwork:
                raise xenrt.XRTFailure("Snapshot network does not match the "
                                       "original VM network",
                                       "Device %s, VM n/w %s, snapshot n/w %s"
                                       % (vmdevice, vmnetwork, snapnetwork))
            del snapvifs[vmdevice]
        if len(snapvifs.keys()) > 0:
            raise xenrt.XRTFailure("Snapshot has more VIFs than the original "
                                   "VM",
                                   "Remaining devices: %s" %
                                   (string.join(snapvifs.keys())))

    def checkSnapshotVDIs(self, snapvdis):
        # For each VDI belonging to the VM check a snapshot VDI has been
        # created:
        found = []
        host = self.getHost()
        vmdisks = host.minimalList("vbd-list", 
                                   "vdi-uuid",
                                   "vm-uuid=%s type=Disk" % 
                                   (self.getUUID()))
        for disk in vmdisks:
            snapshots = host.genParamGet("vdi", disk, "snapshots").split("; ")
            if not snapshots or snapshots[0] == '':
                xenrt.TEC().warning("A VDI belonging to the VM has no snapshot. VDI %s." % (disk))
                continue
            found.extend(snapshots)
            for snapshot in snapshots:
                if not host.genParamGet("vdi", snapshot, "is-a-snapshot") == "true":
                    raise xenrt.XRTFailure("Snapshot VDI not marked as snapshot.",
                                           "VDI %s" % (snapshot)) 
                try:
                    snapshotof = host.genParamGet("vdi", snapshot, "snapshot-of")
                except xenrt.XRTFailure, e:
                    xenrt.TEC().warning("Failed to get snapshot-of. (%s)" % (str(e)))
                    snapshotof  = host.genParamGet("vdi", snapshot, "snapshot_of")
                if not snapshotof == disk:
                    raise xenrt.XRTFailure("Snapshot not marked as snapshot of "
                                           "what it should be.",
                                           "Expecting %s Saw %s VDI %s" % 
                                           (disk, snapshotof, snapshot))
        xenrt.TEC().logverbose("Found snapshot VDIs: %s" % (found))
        for vdi in snapvdis:
            # Check that we found all the snapvdis.
            if not vdi in found:
                raise xenrt.XRTFailure("Didn't find snapshot VDI (%s)" % (vdi))
            # Check that no snapshot VDIs have VBDs in the original VM.
            vms = host.minimalList("vbd-list",
                                   "vm-uuid",
                                   "vdi-uuid=%s" % (vdi))
            if self.getUUID() in vms:
                raise xenrt.XRTFailure("A snapshot VDI has a VBD in the "
                                       "original VM",
                                       "Snap VDI %s" % (vdi))

    def removeSnapshot(self, uuid, force=True):
        """Uninstall the snapshot (template) with UUID, uuid."""
        self.getHost().removeTemplate(uuid)

    def exportVM(self, image, metadata=False):
        if os.path.exists(image):
            os.unlink(image)
        cli = self.getCLIInstance()
        args = []
        args.append("filename=%s" % (image))
        args.append("uuid=%s" % (self.getUUID()))
        if metadata:
            args.append("--metadata")
        if self.special.has_key('export suspended VM uses '
                                '--preserve-power-state') \
                and self.getState() == "SUSPENDED":
            args.append("--preserve-power-state")

        cli.execute("vm-export",
                    string.join(args),
                    timeout=3600)
        if not xenrt.TEC().registry.read("/xenrt/cli/windows"):
            if not os.path.exists(image):
                raise xenrt.XRTError("%s does not exist after vm-export" %
                                     (image))

    def check(self):
        xenrt.GenericGuest.check(self)
        # Check we're running where we should be
        domains = self.getHost().listDomains(includeS=True)
        if not domains.has_key(self.getUUID()):
            raise xenrt.XRTFailure("Guest %s not found on host %s" %
                                   (self.getName(), self.getHost().getName()))

    def checkBSOD(self,img):
        if isBSODBlue(img):
                # This is almost certainly a BSOD (> 50% of the screen is the BSOD blue...)
                xenrt.TEC().tc._bluescreenGuests.append(self)
                img.save("%s/bsod.jpg" % (xenrt.TEC().getLogdir()))
                try:
                    domid = self.getDomid()
                except:
                    domid = None
                bsoddata = self.getHost().execdom0("tail -n 100 %s/console.%u.log" % (xenrt.TEC().lookup("GUEST_CONSOLE_LOGDIR"), domid))
                r = re.search("STOP.+", bsoddata, re.MULTILINE|re.DOTALL)
                reason = "Windows STOP error"
                if r:
                        stop = r.group(0)
                        if xenrt.TEC().lookup("PAUSE_ON_BSOD", False, boolean=True) and "crash dump" in stop:
                                xenrt.TEC().tc.pause("BSOD Detected - pausing")
                        r = re.search("(\w+\.sys)|Driver (\S+)", stop, re.MULTILINE)
                        driver = r and r.group(1) or r and r.group(2) or ""
                        r = re.search("0x\w+", stop, re.MULTILINE)
                        code = r and r.group(0) or ""
                        reason = "Windows STOP error [%s] in [%s]" % (code, driver)
                elif xenrt.TEC().lookup("PAUSE_ON_BSOD", False, boolean=True):
                        xenrt.TEC().tc.pause("BSOD Detected - pausing")
                xenrt.TEC().comment(reason + " on domid " + str(domid) + " on host " + self.getHost().getName())
                raise xenrt.XRTFailure(reason)

    def checkHealth(self, unreachable=False, noreachcheck=False, desc=""):
        """Check the guest is healthy (if it is running)"""

        # Make sure we're not already in a checkHealth call tree. This
        # is to avoid recursive checking when a command run as part of the
        # checkHealth method itself generates a checkHealth call
        stack = traceback.extract_stack()
        if "checkHealth" in map(lambda x:x[2], stack)[:-1]:
            xenrt.TEC().logverbose("Terminating recursive checkHealth call")
            return
        if len(stack) >= 2:
            parenttext = " (called from %s)" % (stack[-2][2])
        else:
            parenttext = ""

        if desc != "":
            desc = " (%s)" % desc
        else:
            desc = parenttext

        xenrt.TEC().logverbose("Checking guest %s health%s" %
                               (self.getName(), parenttext))
        if not self.getState() in ["UP", "PAUSED"]:
            return

        # Make sure we have a domain running
        domid = self.getDomid()

        # If this is a HVM VM, check qemu is running
        try:
            qpid = self.getHost().xenstoreRead("/local/domain/%u/qemu-pid" %
                                               (domid))
        except:
            # Not HVM
            qpid = None
        if qpid:
            if self.getHost().execdom0("test -d /proc/%s" % (qpid), retval="code") != 0:
                xenrt.TEC().logverbose("%s qemu process %s" %
                                       (self.getName(), qpid))
                xenrt.TEC().logverbose("%s domid %u" % (self.getName(), domid))
                if self.getHost().execdom0("test -e /var/xen/qemu/%s/core.%s" %
                                           (qpid, qpid), retval="code") == 0:
                    try:
                        sftp = self.getHost().sftpClient()
                        try:
                            sftp.copyFrom("/var/xen/qemu/%s/core.%s" %
                                          (qpid, qpid),
                                          "%s/core.%s" %
                                          (xenrt.TEC().getLogdir(), qpid))
                        finally:
                            sftp.close()
                    except:
                        pass
                    raise xenrt.XRTFailure("qemu process core dumped%s" % desc)
                else:
                    raise xenrt.XRTFailure("qemu process not running for domain%s" % desc)

        # if this is a Solaris guest, it must have PV drivers enabled
        if self.distro and re.search("solaris", self.distro):
            self.checkPVDevices()

        # Check the VM is reachable via the network
        try:
            if unreachable or noreachcheck:
                # This health check was called because the guest was
                # unreachable, don't call that check again
                raise xenrt.XRTFailure("Dummy exception%s" % desc)
            else:
                self.checkReachable()
        except:
            # Check for BSOD or other graphically visible failure mode
            filename = xenrt.TEC().tempFile()
            if self.getHost().getVncSnapshot(domid,filename):
                i = Image.open(filename)

                # Some tests (such as Mixops) need the screen capture
                # kept because it won't be available in the final log
                # collection phase.
                if xenrt.TEC().lookup("OPTION_KEEP_SCREENSHOTS",
                                      False,
                                      boolean=True):
                    try:
                        i.save("%s/vncgrab-domid%u-%s.jpg" %
                               (xenrt.TEC().getLogdir(),
                                domid,
                                self.getUUID()))
                    except:
                        pass
                self.checkBSOD(i)# Win 7 and Win 8
                if i.size == (720,400): # Might be a hung resume
                    pix = i.load()
                    black = 0
                    for x in range(i.size[0]):
                        for y in range(i.size[1]):
                            if pix[x,y] == (0,0,0):
                                black += 1
                    pc = int((float(black) / float(i.size[0]*i.size[1])) * 100)

                    if pc >= 85:
                        # Black enough, check for progress bar
                        grey = 0
                        total = 0
                        for x in range(i.size[0]):
                            for y in range(352,368):
                                total += 1
                                if pix[x,y] == (168,168,168):
                                    grey += 1

                        gpc = int((float(grey) / float(total)) * 100)
                        # Do we have at least 50% progress (this value may need
                        # tweaking)
                        if gpc >= 50:
                            raise xenrt.XRTFailure("Windows hung resume detected%s" % desc)
                        elif gpc == 0:
                            # This may be a failed boot (at which point progress
                            # bar won't be where we just looked for it)
                            # Check for info in log
                            failure = None
                            try:
                                # Only grab the last 100 lines of the console log
                                # in case this domid on a previous boot had an
                                # unrelated issue.
                                bootdata = self.getHost().execdom0(
                                    "tail -n 100 %s/console.%u.log" %
                                    (xenrt.TEC().lookup("GUEST_CONSOLE_LOGDIR"),
                                     domid))
                                nostart = re.search(r"Windows could not start",
                                                    bootdata,re.MULTILINE)
                                if nostart:
                                    # Definitely a failed boot, see if we can
                                    # get any details about it
                                    file = re.search(r"file is missing\s+or "
                                                      "corrupt:\s+([^\n]+)",
                                                      bootdata,re.MULTILINE)
                                    if file:
                                        # Copy the image to the logdir
                                        i.save("%s/bootfail.jpg" % 
                                               (xenrt.TEC().getLogdir()))

                                        fname = file.group(1).strip()
                                        failure = xenrt.XRTFailure(\
                                            "Windows corrupt boot file: %s%s" %
                                            (fname, desc))
                            except:
                                pass
                            if failure:
                                raise failure
                elif i.size == (1024,768): # Might be a hung hibernate
                    pix = i.load()
                    topstrip = 0
                    mainback = 0
                    total = 0
                    for x in range(i.size[0]):
                        for y in range(i.size[1]):
                            total += 1
                            if pix[x,y] == (0, 48, 156):
                                topstrip += 1
                            elif pix[x,y] == (88, 124, 220):
                                mainback += 1
                    tspc = int((float(topstrip) / float(total)) * 100)
                    backpc = int((float(mainback) / float(total)) * 100)
                    # We want to be fairly exact on this, as 1024x768 is the
                    # default resolution used by our guests - we don't want
                    # false positives
                    if tspc == 9 and backpc == 70:
                        raise xenrt.XRTFailure(\
                            "Windows hung hibernate/shutdown detected%s" % desc)

                    #Check for Win 8 Autologon Failure
                    #Screen is Deep Blue except for just two profile diplay buttons in middle which is White and Grey.
                    #Will check for top fifth being the exact blue and then verify for the blobs of white strip - that being the 
                    #profile picture - would capture thin long strips from the approx mid of these which is guaranteed more white.

                    pixr, pixg, pixb = xenrt.imageRectMeanColour(i,
                                                                 0,
                                                                 0,
                                                                 i.size[0],
                                                                 150)
                    pixr1, pixg1, pixb1 = xenrt.imageRectMeanColour(i,
                                                                    375,
                                                                    228,
                                                                    421,
                                                                    264)
                    pixr2, pixg2, pixb2 = xenrt.imageRectMeanColour(i,
                                                                    613,
                                                                    227,
                                                                    661,
                                                                    264)

                    if pixr < 30 and pixg < 5  and pixb < 88:
                        # Deep blue top fifth Ok
                        if pixr1 > 248 and pixg1 > 248 and pixg1 > 248 and \
                               pixr2 > 248 and pixg2 > 248 and pixb2 > 248:
                            #Two White strips ok
                            # Copy the image to the logdir                  
                            i.save("%s/bootfail.jpg" % 
                                   (xenrt.TEC().getLogdir()))
                            raise xenrt.XRTFailure(\
                                "Windows failed to autologon%s" % desc)

                    #checking autologon failure for WindowsServer2k3EESP2
                    #Checking Blue in top 1/3rd screen and middle grey color

                    pixr, pixg, pixb = xenrt.imageRectMeanColour(i,
                                                                 0,
                                                                 0,
                                                                 i.size[0],
                                                                 150)
                    pixr1, pixg1, pixb1 = xenrt.imageRectMeanColour(i,
                                                                    319,
                                                                    216,
                                                                    348,
                                                                    244)
                    pixr2, pixg2, pixb2 = xenrt.imageRectMeanColour(i,
                                                                    330,
                                                                    351,
                                                                    708,
                                                                    368)

                    if pixr >50 and pixr < 60 and pixg > 105 and pixg < 113 and pixb > 160 and pixb < 170:
                        if pixr1 >80 and pixr1 < 93 and pixg1 > 90 and pixg1 < 100 and pixb1 > 95 and pixb1 < 110:
                            if pixr2 >208 and pixr2 < 215 and pixg2 > 203 and pixg2 < 213 and pixb2 > 197 and pixb2 < 203:
                                i.save("%s/bootfail.jpg" % 
                                   (xenrt.TEC().getLogdir()))
                                raise xenrt.XRTFailure(\
                                    "Windows Server failed to autologon%s" % desc)  

                elif i.size == (800,600):
                    # Check for Windows 7 autologon failure (XRT-6080)
                    # Look for a bluish top third of the screen and two
                    # orange blobs for the login buttons
                    pixr, pixg, pixb = xenrt.imageRectMeanColour(i,
                                                                 0,
                                                                 0,
                                                                 i.size[0],
                                                                 300)
                    pixr1, pixg1, pixb1 = xenrt.imageRectMeanColour(i,
                                                                    296,
                                                                    352,
                                                                    330,
                                                                    388)
                    pixr2, pixg2, pixb2 = xenrt.imageRectMeanColour(i,
                                                                    472,
                                                                    352,
                                                                    508,
                                                                    388)
                    if pixr < 40 and pixg > 90 and pixg < 130 and pixb > 180:
                        # Bluish top third OK
                        if pixr1 > 220 and pixg1 > 90 and pixg1 < 130 and \
                               pixb1 < 30 and pixr2 > 220 and pixg2 > 90 and \
                               pixg2 < 130 and pixb2 < 30:
                            # Two orange blobs
                            # Copy the image to the logdir
                            i.save("%s/bootfail.jpg" % 
                                   (xenrt.TEC().getLogdir()))
                            raise xenrt.XRTFailure(\
                                "Windows failed to autologon%s" % desc)

                    # Check for Windows Server 2008 autologon failure
                    # Look for dull bluish colour on the first and second half of the image
                    pixr, pixg, pixb = xenrt.imageRectMeanColour(i,
                                                                 0,
                                                                 0,
                                                                 i.size[0],
                                                                 300)

                    pixr1, pixg1, pixb1 = xenrt.imageRectMeanColour(i,
                                                                    0,
                                                                    300,
                                                                    i.size[0],
                                                                    600)
                    if pixr < 40 and pixg > 90 and pixg < 130 and pixb > 110 and pixb < 135: 
                        xenrt.TEC().logverbose('Dull bluish top present')
                        if pixr1 < 40 and pixg1 > 90 and pixg1 < 130 and pixb1 > 110 and pixb1 < 135:
                            xenrt.TEC().logverbose('Dull bluish bottom half similar to the top half - Windows Server 2008 autologon failure')
                            # Copy the image to the logdir
                            i.save("%s/bootfail.jpg" % 
                                   (xenrt.TEC().getLogdir()))
                            raise xenrt.XRTFailure(\
                                "Windows failed to autologon%s" % desc)

            if not self.windows:
                # Check the guest console log for various failure signatures
                try:
                    data = self.getHost().guestConsoleLogTail(domid, lines=100)
                except:
                    data = ""

                try:
                    # Check for "XENBUS: Timeout connecting to device"
                    if re.search(r"XENBUS: Timeout connecting to device", data):
                        raise xenrt.XRTFailure("VM boot failed: XENBUS: "
                                               "Timeout connecting to device%s" % desc)

                    # See if it's a CA-13704 or CA-8914 hung RHEL start
                    if re.search(r"Bringing up interface eth0:\s*$", data):
                        raise xenrt.XRTFailure("VM boot hung at "
                                               "'Bringing up interface eth0'%s" % desc)
                    if re.search(r"Determining IP information for eth0\.\.\.\s*$",
                                 data):
                        raise xenrt.XRTFailure("VM boot hung at "
                                               "'Determining IP information "
                                               "for eth0...'%s" % desc)
                    if re.search(r"Enabling swap space:\s+\[\s+OKs\+\]\s*$", data):
                        raise xenrt.XRTFailure("VM boot hung after "
                                               "'Enabling swap space'%s" % desc)
                    if re.search(r"switchroot: mount failed: No such file "
                                 "or directory", data):
                        raise xenrt.XRTFailure(\
                            "initrd could not mount root filesystem%s" % desc)

                    # See if it's a CA-35026 Debian install failure
                    if "No kernel modules were found" in data:
                        raise xenrt.XRTFailure("Install failed: No kernel "
                                               "modules were found%s" % desc)

                    # Look for GPF or Oops
                    eip = None
                    r = re.search(r"(EIP is at \S+)", data)
                    if r:
                        eip = r.group(1)
                    r = re.search(r"RIP: .* (\S+\+0x[0-9a-f]+\/0x[0-9a-f]+)",
                                  data)
                    if r:
                        eip = "RIP is at %s" % (r.group(1))
                    if re.search(r"general protection fault", data):
                        if eip:
                            raise xenrt.XRTFailure("GPF. %s%s" % (eip, desc))
                        else:
                            raise xenrt.XRTFailure("general protection fault%s" % desc)
                    if re.search(r"Oops:", data):
                        if eip:
                            raise xenrt.XRTFailure("Oops. %s%s" % (eip,desc))
                        else:
                            raise xenrt.XRTFailure("Oops%s" % desc)
                    r = re.search(r"(kernel BUG at \S+:\d+)", data)
                    if r:
                        if eip:
                            raise xenrt.XRTFailure("%s (%s)%s" %
                                                   (r.group(1), eip, desc))
                        else:
                            raise xenrt.XRTFailure(r.group(1) + desc)
                    if eip:
                        raise xenrt.XRTFailure(eip + desc)
                finally:

                    # see if we can SSH to the guest from dom0.
                    try:
                        if self.getIP():
                            xenrt.TEC().logverbose("Attempting to SSH to guest from dom0")
                            self.host.execdom0("ssh -i /etc/ssh/ssh_host_dsa_key.pub -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no root@%s ls /" % self.getIP())
                    except Exception, ex:
                        xenrt.TEC().logverbose(str(ex))

                    # see if we can arping to the guest from dom0.
                    try:
                        if self.getIP():
                            xenrt.TEC().logverbose("Attempting to arping the guest from dom0")
                            bridge = self.getVIFs()['eth0'][2]
                            self.host.execdom0("arping -I %s -c 2 %s" % (bridge, self.getIP()))
                    except Exception, ex:
                        xenrt.TEC().logverbose(str(ex))

                    # capture the VIF ring and internal queue state
                    try:
                        xenrt.TEC().logverbose("Attempting to capture the VIF ring and internal queue state")
                        self.host.execdom0("mount -t debugfs none /sys/kernel/debug && (cat /sys/kernel/debug/xen-netback/vif%d.0/io_ring;umount /sys/kernel/debug)" % self.getDomid())
                    except Exception, ex:
                        xenrt.TEC().logverbose(str(ex))

                    if xenrt.TEC().lookup("PAUSE_CANT_CONTACT_VM", False, boolean=True):
                        xenrt.GEC().dbconnect.jobUpdate("CANT_CONTACT_VM_PAUSED", "yes")
                        xenrt.TEC().tc.pause("Paused - can't contact VM")
                        xenrt.GEC().dbconnect.jobUpdate("CANT_CONTACT_VM_PAUSED", "no")

                    try:
                        # use key presses to log /var/log/syslog to the console
                        xenrt.TEC().logverbose("Using keypresses to write syslog to console")

                        # press enter twice to clear any junk
                        self.sendVncKeys([0xff0d])
                        xenrt.sleep(10)
                        self.sendVncKeys([0xff0d])
                        xenrt.sleep(10)

                        self.sendVncKeys([0x72, 0x6f, 0x6f, 0x74, 0xff0d]) #root
                        xenrt.sleep(10)

                        self.sendVncKeys([0x78, 0x65, 0x6e, 0x72, 0x6f, 0x6f, 0x74, 0xff0d]) #xenroot
                        xenrt.sleep(10)

                        self.sendVncKeys([0x63, 0x61, 0x74, 0x20, 0x2f, 0x76, 0x61, 0x72, 0x2f, 0x6c, 0x6f, 0x67, 0x2f, 0x73, 0x79, 0x73, 0x6c, 0x6f, 0x67, 0xff0d]) #cat /var/log/syslog
                        xenrt.sleep(30)

                        self.sendVncKeys([0x63, 0x61, 0x74, 0x20, 0x2f, 0x76, 0x61, 0x72, 0x2f, 0x6c, 0x6f, 0x67, 0x2f, 0x6d, 0x65, 0x73, 0x73, 0x61, 0x67, 0x65, 0x73, 0xff0d]) #cat /var/log/messages
                        xenrt.sleep(30)
                    except Exception, ex:
                        xenrt.TEC().logverbose("Exception sending keys for guest syslog: " + str(ex))

                    # Send sysrq-t, -m, -p and -w to the VM if it's Linux
                    for key in ('9', 't', 'm', 'p', 'w'):
                        xenrt.TEC().logverbose("Sending sysrq-%s to %s" % 
                                               (key, self.getName()))
                        try:
                            self.sendSysRq(key)
                            xenrt.sleep(2)
                        except Exception, e:
                            xenrt.TEC().warning("Exception sending sysrq: %s" % 
                                                (str(e)))

            # Check if the domain is paused
            if self.getState() == "PAUSED":
                raise xenrt.XRTFailure("Domain is in the paused state%s" % desc)

            if self.windows:
                # If PV drivers are installed, see if they're connected
                if self.enlightenedDrivers:
                    self.checkPVDevices()

                if xenrt.TEC().lookup("DEBUG_VNCKEYS", False, boolean=True):
                    # Send some suitable keystrokes to product evidence on the
                    # VNC screen capture of the VM being alive
                    try:
                        # Send Windows-R to bring up a run dialog
                        self.sendVncKeys(["0x72/0xffeb"])
                        xenrt.sleep(8)
                        # sometimes you need to do this twice
                        self.sendVncKeys(["0x72/0xffeb"])
                        xenrt.sleep(8)
                        # Start a CMD prompt
                        self.sendVncKeys([0x63, 0x6d, 0x64, 0xff0d])
                        xenrt.sleep(5)
                        # Show the ipconfig output
                        self.sendVncKeys([0x69, 0x70, 0x63, 0x6f, 0x6e, 0x66, 0x69, 0x67, 0xff0d])
                    except Exception, ex:
                        xenrt.TEC().logverbose("Exception pressing keys: " + str(ex))

                ##Try to log the ipconfig data using a VB script writing it into the WMI
                try:
                    # Send Windows-R to bring up a run dialog
                    self.sendVncKeys(["0x72/0xffeb"])
                    xenrt.sleep(8)
                    # sometimes you need to do this twice
                    self.sendVncKeys(["0x72/0xffeb"])
                    xenrt.sleep(8)
                    # Start a CMD prompt
                    self.sendVncKeys([0x63, 0x6d, 0x64, 0xff0d])
                    xenrt.sleep(5)
                    # Send the keys to start the logger.vbs: wscript.exe logger.vbs
                    self.sendVncKeys([0x57, 0x73, 0x63, 0x72, 0x69, 0x70, 0x74, 0x2e, 0x65, 0x78, 0x65, 0x20, 0x2e, 0x2e, 0x5c, 0x2e, 0x2e, 0x5c, 0x6c, 0x6f, 0x67, 0x67, 0x65, 0x72, 0x2e, 0x76, 0x62, 0x73, 0xff0d])
                    xenrt.sleep(10)
                except Exception as e:
                    xenrt.TEC().logverbose("Windows ipconfig logger error: %s"%(e.message))

            if self.windows and self.getIP():
                # Check if RDP is accepting connections.
                s = socket.socket()
                s.settimeout(10)
                try: s.connect((self.getIP(), 3389))
                except socket.timeout:
                    xenrt.TEC().logverbose("RDP port 3389 appears to be closed.")
                except socket.error, e:
                    if 'Connection refused' in e:
                        xenrt.TEC().logverbose("RDP port 3389 is closed.")
                    else:
                        xenrt.TEC().logverbose("Socket error on RDP port 3389")
                else:
                    xenrt.TEC().logverbose("RDP port 3389 appears to be open.")
                s.close()

            # If we get here we didn't detect a BSOD or hung resume
            if not noreachcheck:
                if self.windows:
                    if self.enlightenedDrivers:
                        self.getHost().xenstoreWrite("/local/domain/%u/control/ping" %(domid),"1")
                        deadlineThreeMinute = xenrt.timenow() + 180
                        while xenrt.timenow() < deadlineThreeMinute:
                            try:
                                self.getHost().xenstoreRead("/local/domain/%u/control/ping" %(domid))
                            except:
                                raise xenrt.XRTFailure("Domain running but not reachable by XML-RPC%s but windows guest agent is responding" % desc)
                            xenrt.sleep(20)
                        raise xenrt.XRTFailure("Domain running but not reachable by XML-RPC%s and the windows guest agent isn't responding" % desc)
                    else:
                        raise xenrt.XRTFailure("Domain running but not reachable by XML-RPC%s" % desc)
                else:
                    raise xenrt.XRTFailure("Domain running but not reachable by SSH%s" % desc)

        xenrt.TEC().logverbose("Guest health check for %s couldn't find anything wrong" % (self.getName()))

    def installTools(self, reboot=False, updateKernel=True):
        """Install tools package into a guest"""

        if self.windows:
            return

        toolscdname = self.insertToolsCD()
        device="sr0"

        if not self.isHVMLinux():
            deviceList = self.getHost().minimalList("vbd-list", 
                                                "device", 
                                                "type=CD vdi-name-label=%s vm-uuid=%s" %
                                                (toolscdname, self.getUUID()))

            if deviceList:
                device = deviceList[0]
            else:
                raise xenrt.XRTFailure("VBD for tools ISO not found")

        for dev in [device, device, "cdrom"]:
            try:
                self.execguest("mount /dev/%s /mnt" % (dev))
                break
            except:
                xenrt.TEC().warning("Mounting xs-tools.iso failed on the first attempt.")
                xenrt.sleep(30)
        args = "-n"
        specialkey = "do not update kernel %s" % self.getHost().productVersion
        if self.special.has_key(specialkey) and self.special[specialkey]:
            updateKernel = False
        if not updateKernel:
            args += " -k"
        self.execguest("/mnt/Linux/install.sh %s" % (args))
        self.enlightenedDrivers=True
        self.execguest("umount /mnt")
        xenrt.sleep(10)
        try:
            self.removeCD(device=device)
        except xenrt.XRTFailure as e:
            # In case of Linux on HVM, vbd-destroy on CD may fail.
            if "vbd-destroy" in e.reason:
                pass
            else:
                raise
        if reboot or ((self.distro and (self.distro.startswith("centos4") or self.distro.startswith("rhel4"))) and updateKernel):
            # RHEL/CentOS 4.x update the kernel, so need to be rebooted
            self.reboot()

        # RHEL/CentOS 4.7/5.2 have a other-config key set in the
        # template to work around the >64GB bug (EXT-30). Once we have
        # upgraded to a Citrix kernel we can remove this restriction
        try:
            self.paramRemove("other-config", "machine-address-size")
        except:
            pass

        # RHEL/CentOS 4.6 have a other-config key set in the
        # template to work around the pgd_free bug (EXT-42). Once we have
        # upgraded to a Citrix kernel we can remove this restriction
        if self.distro and "rhel46" in self.distro:
            try:
                self.paramRemove("other-config", "suppress-spurious-page-faults")
            except:
                pass

    def getPVDriverVersion(self, micro=False):
        reply = None
        try:
            major = self.paramGet("PV-drivers-version", "major")
            minor = self.paramGet("PV-drivers-version", "minor")
            if micro:
                microv = self.paramGet("PV-drivers-version", "micro")
            build = self.paramGet("PV-drivers-version", "build")
            if micro:
                reply = "%s.%s.%s-%s" % (major, minor, microv, build)
            else:
                reply = "%s.%s-%s" % (major, minor, build)
        except:
            pass
        return reply

    def sendSysRq(self, key):
        if isinstance(self.getHost(), xenrt.lib.xenserver.DundeeHost):
            self.getHost().execdom0("xl sysrq %u %s" %(self.getDomid(),key))
        else:    
            self.getHost().execdom0("/opt/xensource/debug/xenops sysrq_domain "
                                "-domid %u -key %s" % (self.getDomid(), key))

    def pretendToHaveXenTools(self):
        """Write xenstore entries to trick xapi into thinking we have XenTools
        installed in the VM. This is only good for the current domain, i.e.
        will need to be rerun after any reboot, resume, migrate etc."""
        v = self.getHost().getHostParam("software-version",
                                        "product_version").split(".")
        domid = self.getDomid()
        self.getHost().xenstoreWrite(\
            "/local/domain/%u/attr/PVAddons/MajorVersion" % (domid), v[0])
        self.getHost().xenstoreWrite(\
            "/local/domain/%u/attr/PVAddons/MinorVersion" % (domid), v[1])
        self.getHost().xenstoreWrite(\
            "/local/domain/%u/attr/PVAddons/MicroVersion" % (domid), v[2])
        self.getHost().xenstoreWrite(\
            "/local/domain/%u/data/updated" % (domid), '1')

    def verifyGuestFunctional(self, migrate=False, attachedDisks=False):
        if self.getState() == "UP":
            if self.windows:
                # Write a file
                self.xmlrpcExec("echo 'Testing Storage Access' > \\teststorage") 
                # Read it
                self.xmlrpcExec("type \\teststorage") 

                if attachedDisks:
                    raise xenrt.XRTError("Unimplemented")

            else:
                # Write a file
                self.execguest("dd if=/dev/zero bs=1024 count=1000 of=teststorage")
                # Read it
                self.execguest("dd if=teststorage of=/dev/null")

                if attachedDisks:
                    devices = self.getHost().minimalList("vbd-list", "device",
                                    "vm-uuid=%s bootable=false type=Disk" % (self.getUUID()))
                    for d in devices:
                        # Write a file
                        self.execguest("dd if=/dev/zero bs=1024 count=1000 of=/dev/%s" % d)
                        # Read it
                        self.execguest("dd if=/dev/%s of=/dev/null" % d)

            if migrate:
               self.migrateVM(host=self.host, live="true")

    def pvDriversUpToDate(self):
        """Returns a Boolean indicating whether the guest's PV drivers are up-to-date"""

        self.paramGet("PV-drivers-version")
        return self.paramGet("PV-drivers-up-to-date") == 'true'

    def setHAPriority(self, order=0, protect=True):
        # The ordering of the below commands is different on purpose.
        if protect:
            self.paramSet("ha-restart-priority", order)
            self.paramSet("ha-always-run", "true")
        else:
            self.paramSet("ha-always-run", "false")
            self.paramSet("ha-restart-priority", "")

        try:
            cli = self.getHost().getCLIInstance()
            cli.execute("pool-sync-database")
        except:
            pass

    def setStartAndShutdownDelay(self, start_delay=0, shutdown_delay=0):

        self.getHost().genParamSet('vm', self.getUUID(), 'start-delay', start_delay)
        self.getHost().genParamSet('vm', self.getUUID(), 'shutdown-delay', shutdown_delay)

    def getHAPriority(self):
        return self.paramGet("ha-restart-priority")

    def findHost(self, timeout=300, reachableTimeout=600, checkReachable=True):
        """Find what host we are running on from a pool"""
        # Useful for HA testing - assume that we may no longer be on self.host,
        # but instead on another machine in the pool - search the pool (allowing
        # for the fact that hosts may be down)...

        if not self.getHost().pool:
            raise xenrt.XRTError("Original host is not in a pool")

        # We assume that the current master is available, so CLI should work
        st = xenrt.util.timenow()
        hostUUID = None
        while True:
            hostUUID = self.getHost().genParamGet("vm",
                                                  self.getUUID(),
                                                  "resident-on")

            if hostUUID and xenrt.isUUID(hostUUID):
                if self.getHost().pool.haEnabled:
                    # Check if host is expected to be live, as if not, then it
                    # might just be that xapi hasn't got round to trying to
                    # restart the VM yet
                    if hostUUID in self.getHost().pool.haLiveset:
                        break
                else:
                    break

            if (xenrt.util.timenow() - st) > timeout:
                return None

            xenrt.sleep(30)

        poolHosts = self.getHost().pool.getHosts()
        poolHostUUIDs = {}
        for h in poolHosts:
            poolHostUUIDs[h.getMyHostUUID()] = h

        if hostUUID in poolHostUUIDs.keys():
            self.setHost(poolHostUUIDs[hostUUID])
            if checkReachable:
                # Make sure the guest is actually reachable (allow a reasonably
                # long time as it may have to check disk etc)
                self.checkReachable(timeout=reachableTimeout)
            return self.getHost()
        else:
            raise xenrt.XRTError("Host found is not in the Pool object")

    def disableVSS(self):
        """Disable the XenServer VSS hardware provider."""
        ecmd = "uninstall-XenProvider.cmd"
        if self.xmlrpcGetArch() == "amd64":
            edir = "c:\\Program Files (x86)\\citrix\\xentools"
        else:
            edir = "c:\\Program Files\\citrix\\xentools"
        escript = "%s\\%s" % (edir, ecmd)
        self.xmlrpcExec("\"%s\"" % (escript))

    def enableVSS(self):
        """Enable the XenServer VSS hardware provider."""
        ecmd = "install-XenProvider.cmd"
        if self.xmlrpcGetArch() == "amd64":
            edir = "c:\\Program Files (x86)\\citrix\\xentools"
        else:
            edir = "c:\\Program Files\\citrix\\xentools"
        escript = "%s\\%s" % (edir, ecmd)
        self.xmlrpcExec("\"%s\"" % (escript))

    def leafCoalesce(self, hostuuid=None):
        if not hostuuid:
            hostuuid = self.host.getMyHostUUID()
        cli = self.getCLIInstance()
        args = []
        args.append("host-uuid=%s" % (hostuuid))
        args.append("plugin=coalesce-leaf")
        args.append("fn=leaf-coalesce")
        args.append("args:vm_uuid=%s" % (self.getUUID()))
        cli.execute("host-call-plugin", string.join(args))

    def messageCreate(self, name, body, priority=1):
        self.getHost().messageGeneralCreate("vm",
                                            self.getUUID(),
                                            name,
                                            body,
                                            priority)

    def setMemoryTarget(self, target):
        cli = self.getCLIInstance()
        args = []
        args.append("uuid=%s" % (self.getUUID()))
        args.append("target=%s" % (target))
        cli.execute("vm-memory-target-set", string.join(args))
        # Verify it was set correctly
        setTarget = self.getMemoryTarget() / xenrt.MEGA
        if str(setTarget) != str(target / xenrt.MEGA):
            raise xenrt.XRTFailure("Memory target does not match set value")

    def computeOverhead(self):
        cli = self.getHost().getCLIInstance()
        overhead = int(cli.execute("vm-compute-memory-overhead",
                                   "uuid=%s" % (self.getUUID()), strip=True))
        overhead = overhead / xenrt.MEGA
        return overhead

    def getMemoryTarget(self):
        return self.paramGet("memory-target")

    def getDataSourceValue(self, source):
        cli = self.getCLIInstance()
        mt = cli.execute("vm-data-source-query",
                         "uuid=%s data-source=%s" %
                         (self.getUUID(), source)).strip()
        return float(mt)

    #########################################################################
    # Kirkwood / WLB related methods
    def retrieveWLBRecommendations(self):
        cli = self.getCLIInstance()
        data = cli.execute("vm-retrieve-wlb-recommendations",
                           "uuid=%s" % (self.getUUID()))
        recs = xenrt.util.strlistToDict(data.splitlines()[1:], sep=":", keyonly=False)
        #CA-80791
        recs = dict(map(lambda x:(re.sub(r'\(.+\)$', '', x),recs[x]), recs))
        return recs

    def vendorInstallDevicePrefix(self):
        if self.distro.startswith("sles12") and self.wouldBootHVM():
            return "hd"
        else:
            return "xvd"

    def installXDVDABrokerLessConn(self):

        self.setState("UP")

        arch = self.xmlrpcGetArch()

        if arch == "amd64":
            arch = 'x64'

        self.snapshot("BeforeXD")

        nfs = xenrt.resources.NFSDirectory()
        nfsdir = xenrt.command("mktemp -d %s/isoXXXX" % (nfs.path()), strip = True)
        isosr = xenrt.lib.xenserver.ISOStorageRepository(self.host, "nfsisosr")
        server, path = nfs.getHostAndPath(os.path.basename(nfsdir))
        isosr.create(server, path)

        filename = "XendesktopBruin.iso"
        urlprefix = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "")
        url = "%s/XendesktopBruin/%s" % (urlprefix, filename)

        os.system("cd %s; wget %s" % (path,url)) 

        xenrt.sleep(60)
        self.changeCD(filename)

        xenrt.sleep(60)
        opSys = self.host.genParamGet("vm",self.getUUID(),"os-version")

        if "Server" in opSys:
            xdCommand = 'XenDesktopVdaSetup.exe /quiet /components vda,plugins /controllers "BOGUS.company.local" /enable_hdx_ports /enable_remote_assistance /noreboot'
        else:
            xdCommand = 'XenDesktopVdaSetup.exe /quiet /components vda,plugins /controllers "BOGUS.company.local" /enable_hdx_ports /optimize /masterimage /baseimage /enable_remote_assistance /noreboot'

        actualCommand = "cd d:\\%s\\XenDesktop Setup && d: && " % (arch)+ xdCommand
        self.xmlrpcExec(actualCommand, timeout=3600, returnerror=False)

        self.reboot()

        self.snapshot("AfterXD")

        regKey = u"""Windows Registry Editor Version 5.00\r\r\n[HKEY_LOCAL_MACHINE\SOFTWARE\Citrix\VirtualDesktopAgent]\r\n"ListOfDDCs"="BOGUS.company.local"\r\n"HighAvailability"=dword:00000001\r\n"HaRegistrarTimeout"=dword:00000001\r\n"ViaBoxMode"="E0950AF2-0D29-4BF4-A480-229C35366A13"\r\n\r\n[HKEY_LOCAL_MACHINE\SOFTWARE\Citrix\VirtualDesktopAgent\State]\r\n"ProductEdition"="ENT" """

        self.xmlrpcWriteFile("c:\\XD.reg",regKey)
        self.xmlrpcExec("regEdit.exe /s c:\\XD.reg")

        self.reboot()

    def getNetworkNameForVIF(self, vifname):
        mac, ip, bridge = self.getVIF(vifname=vifname)
        network = self.host.getNetworkUUID(bridge)
        try:
            return self.host.genParamGet("network", network, "other-config", "xenrtnetname")
        except:
            if bridge == self.host.getPrimaryBridge():
                return "NPRI"
            else:
                return self.host.genParamGet("network", network, "name-label")

    def installXenMobileAppliance(self):
        self.lifecycleOperation("vm-start", specifyOn=True)
        time.sleep(60)
        app = xenrt.XenMobileApplianceServer(self)
        app.doFirstbootUnattendedSetup() 

    def createScaleXtremeEnvironment(self):
        """Install agent on the guest and create ScaleXtreme
        Environment."""
        agent = SXAgent()
        agent.agentVM = self
        agent.installAgent()
        agent.setAsGateway()
        agent.createEnvironment()

    def prepareForTemplate(self):
        if self.getState() == "UP":
            self.preCloneTailor()
            if self.windows:
                self.sysPrepOOBE()
            self.shutdown()
        self.changeCD(None)

    def convertToTemplate(self):
        self.prepareForTemplate()
        self.paramSet("is-a-template", "true")
        self.host.removeGuest(self.name)
        self.isTemplate = True

    def getDeploymentRecord(self):
        ret = super(Guest, self).getDeploymentRecord()
        ret['networks'] = {}
        try:
            os = self.paramGet("os-version")
            if os and os != "<not in database>":
                ret['os']['reported'] = dict([x.split(": ") for x in self.paramGet("os-version").split("; ")])
        except:
            pass
        for v in self.vifs:
            (device, bridge, mac, ip) = v
            nwuuid = self.getHost().getNetworkUUID(bridge)
            nwname = self.getHost().genParamGet("network", nwuuid, "name-label")
            ret['networks'][device] = {"network": {"name": nwname, "uuid": nwuuid}}
            if not self.isTemplate:
                ret['networks'][device]['mac'] = mac
                if ip:
                    ret['networks'][device]['ip'] = ip
        
        ret['disks'] = {}
        for d in self.listDiskDevices():
            vdiuuid = self.getHost().minimalList("vbd-list", "vdi-uuid", "vm-uuid=%s userdevice=%s" % (self.uuid, d))[0]
            params = self.getHost().parameterList("vdi-list", ["virtual-size","sr-uuid", "sr-name-label"], "uuid=%s" % vdiuuid)[0]

            ret['disks'][d] = {
                "size": int(params['virtual-size'])/xenrt.GIGA,
                "sr": {"name": params['sr-name-label'], "uuid": params['sr-uuid']}
            }

        return ret

    def getAutoUpdateDriverState(self):
        """ Check whether the Windows Auto PV Driver updates is enabled on the VM"""
        
        if self.getHost().xenstoreExists("/local/domain/%u/control/auto-update-drivers" %(self.getDomid())):
            return self.getHost().xenstoreRead("/local/domain/%u/control/auto-update-drivers" %(self.getDomid()))
        else:
            raise xenrt.XRTFailure("cannot find auto-update-driver path in the xenstore")

    def xenDesktopTailor(self):

        xenrt.GenericGuest.xenDesktopTailor(self)

        self.shutdown()
        self.paramSet("platform:usb", "false")
        self.paramSet("platform:hvm_serial", "none")
        self.paramSet("platform:nousb", "true")
        self.paramSet("platform:monitor", "null")
        self.paramSet("platform:parallel", "none")
        self.start()

    def getLowMemory(self):
        """Returns low memory of the linux guest
        @return: low memory in MiBs
        """
        if self.windows:
            raise xenrt.XRTError("Unimplemented")
        else:
            return int(self.execguest("free -l | grep Low | awk '{print $2}'").strip()) / xenrt.KILO


#############################################################################

def parseSequenceVIFs(guest, host, vifs):
    update = []
    for v in vifs:
        device, bridge, mac, ip = v
        device = "%s%s" % (guest.vifstem, device)
        if not bridge:
            bridge = host.getPrimaryBridge()
        elif re.search(r"^[0-9]+$", bridge):
            bridge = host.getBridgeWithMapping(int(bridge))
        elif not host.getBridgeInterfaces(bridge):
            br = host.parseListForOtherParam("network-list",
                                                 "name-label",
                                                  bridge,
                                                 "bridge")
            if br:
                bridge = br
            elif not host.getNetworkUUID(bridge):
                bridge = None

        if not bridge:
            raise xenrt.XRTError("Failed to choose a bridge for createVM on "
                                 "host !%s" % (host.getName()))
        update.append([device, bridge, mac, ip])
    return update

def parseSequenceSRIOVVIFs(guest, host, vifs):
    update = []
    for v in vifs:
        netname, ip = v

        # Convert netname into a physical device name on the host (e.g. 'eth0')
        xenrt.TEC().logverbose("Converting netname='%s' into physical device name..." % (netname))
        if not netname:
            physdev = host.getPrimaryBridge()
            # we assume the host already has SRIOV enabled
            iovirt = xenrt.lib.xenserver.IOvirt(host)
            eth_devs = iovirt.getSRIOVEthDevices()
            if len(eth_devs) == 0:
                raise xenrt.XRTFailure("No SR-IOV devices on host %s" % (host))
            physdev = eth_devs[0]
            xenrt.TEC().logverbose("Available physical devices are %s; using %s" % (eth_devs, physdev))
        else:
            netuuid = host.getNetworkUUID(netname)
            if not netuuid:
                raise xenrt.XRTError("Could not find physical device on network '%s'" % (netname))
            # Convert network-uuid into physical device
            args = "host-uuid=%s" % (host.uuid)
            pifuuid = host.parseListForUUID("pif-list", "network-uuid", netuuid, args)
            xenrt.TEC().logverbose("PIF on network %s (for %s) is %s" % (netuuid, netname, pifuuid))
            if not pifuuid:
                raise xenrt.XRTError("couldn't get PIF uuid for network with uuid '%s'" % (netuuid))
            # Get the assumed enumeration ID for this PIF
            physdev = host.genParamGet("pif", pifuuid, "device")
            xenrt.TEC().logverbose("Physical device on network %s is %s" % (netname, physdev))

        update.append([physdev, netname, ip])
    return update

def setupSRIOVVIFs(guest, host, sriovvifs):
    if sriovvifs:
        xenrt.TEC().logverbose("Setting up SR-IOV VIFs %s for guest %s on host %s..." % (sriovvifs, guest, host))

        # We assume the host already has SR-IOV enabled
        iovirt = xenrt.lib.xenserver.IOvirt(host)
        eth_devs = iovirt.getSRIOVEthDevices()
        xenrt.TEC().logverbose("Available physical devices are %s" % (eth_devs))

        for (physdev, netname, ip) in sriovvifs:
            # Check whether it's in the list of devices
            if not (physdev in eth_devs):
                raise xenrt.XRTError("Physical device %s not in list of available SR-IOV devices %s" % (physdev, eth_devs))

            pcidev = iovirt.assignFreeVFToVM(guest.uuid, physdev)
            xenrt.TEC().logverbose("Assigned PCI device %s on %s to %s" % (pcidev, physdev, guest))

def createVMFromFile(host,
                     guestname,
                     filename,
                     userfile=False,
                     postinstall=[],
                     packages=[],
                     vcpus=None,
                     memory=None,
                     bootparams=None,
                     suffix=None,
                     vifs=[],
                     sriovvifs=[],
                     ips={},
                     sr=None,
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
    vifs = parseSequenceVIFs(guest, host, vifs)
    sriovvifs = parseSequenceSRIOVVIFs(guest, host, sriovvifs)
    
    if userfile:
        share = xenrt.ExternalNFSShare()
        m = xenrt.rootops.MountNFS(share.getMount())
        proxy = xenrt.TEC().lookup("HTTP_PROXY", None)
        if proxy:
            xenrt.command('wget -e http_proxy=%s "%s" -O %s/file.xva' % (proxy, filename, m.mountpoint))
        else:
            xenrt.command('wget "%s" -O %s/file.xva' % (filename, m.mountpoint))
        guest.importVM(host, "%s/file.xva" % m.mountpoint, vifs=vifs, sr=sr)
        share.release()
    else:
        if filename.startswith("nfs://"):
            filename = re.sub("\${(.*?)}", lambda x: xenrt.TEC().lookup(x.group(1), None), filename)
            filename = filename[6:]
            dirname = os.path.dirname(filename)
            d = host.execdom0("mktemp -d").strip()
            host.execdom0("mount -t nfs %s %s" % (dirname, d))
            guest.importVM(host, "%s/%s" % (d, os.path.basename(filename)), imageIsOnHost=True, sr=sr, vifs=vifs)
            host.execdom0("umount %s" % d)
        else:
            vmfile = xenrt.TEC().getFile(filename)
            if not vmfile:
                raise xenrt.XRTError("Cannot find %s to import" % filename)
            guest.importVM(host, vmfile, vifs=vifs, sr=sr)
    guest.paramSet("is-a-template", "false")
    guest.reparseVIFs()
    guest.vifs.sort()

    guest.sriovvifs = sriovvifs
    setupSRIOVVIFs(guest, host, sriovvifs)

    if bootparams:
        bp = guest.getBootParams()
        if len(bp) > 0: bp += " "
        bp += bootparams
        guest.setBootParams(bp)
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

def createVMFromPrebuiltTemplate(host,
             guestname,
             distro,
             vcpus=None,
             corespersocket=None,
             memory=None,
             vifs=[],
             bridge=None,
             sr=None,
             arch="x86-32",
             rootdisk=None,
             notools=False,
             suffix=None,
             ips={},
             special={}):
   
    if suffix:
        displayname = "%s-%s" % (guestname, suffix)
    else:
        displayname = guestname
    
    sruuid = host.chooseSR(sr)

    preinstalledTools = False

    # Lock around this section so only one template gets created for this distro
    with xenrt.GEC().getLock("TEMPLATE_SETUP_%s_%s_%s" % (distro, arch, sruuid)):
        preinstalledTemplates = host.minimalList("template-list", args="name-label=xenrt-template-%s-%s-%s" % (distro, arch, sruuid), params="name-label")
    
        if not preinstalledTemplates:
            preinstalledTemplates = host.minimalList("template-list", args="name-label=xenrt-template-%s-%s" % (distro, arch), params="name-label")
            # Templates in this format have the tools installed
            if preinstalledTemplates:
                preinstalledTools = True
  
        # Check whether the template SR is present
        templateSR = host.minimalList("sr-list", params="uuid", args="uuid=%s" % xenrt.lib.xenserver.host.TEMPLATE_SR_UUID)

        if not preinstalledTemplates and templateSR:
            host.getCLIInstance().execute("sr-scan", "uuid=%s" % xenrt.lib.xenserver.host.TEMPLATE_SR_UUID)
            # Mount the template SR locally to find out what the UUID of the VDI is
            m = xenrt.rootops.MountNFS(xenrt.TEC().lookup("SHARED_VHD_PATH_NFS"))
            vuuid = None
            if os.path.exists("%s/%s_%s.cfg" % (m.getMount(), distro, arch)):
                with open("%s/%s_%s.cfg" % (m.getMount(), distro, arch)) as f:
                    vuuid = f.read().strip()
            elif os.path.exists("%s/%s.cfg" % (m.getMount(), distro)):
                with open("%s/%s.cfg" % (m.getMount(), distro)) as f:
                    vuuid = f.read().strip()
            # Check the VDI exists
            if vuuid and os.path.exists("%s/%s.vhd" % (m.getMount(), vuuid)):
                if rootdisk and rootdisk != Guest.DEFAULT:
                    # Check that the disk is big enough
                    if rootdisk*xenrt.MEGA > int(host.genParamGet("vdi", vuuid, "virtual-size")):
                        return None
                template = host.getTemplate(distro, arch=arch)
                cli = host.getCLIInstance()
                # Copy the VDI to the target SR
                vdiuuid = cli.execute("vdi-copy sr-uuid=%s uuid=%s" % (sruuid, vuuid)).strip().strip(",")

                host.genParamSet("vdi", vdiuuid, "name-label", "%s_%s" % (distro, arch))

                # By default we'll put this VDI into a template, then install from the template
                if xenrt.TEC().lookup("CLONE_PREBUILT_TEMPLATES", True, boolean=True):
                    tname = "xenrt-template-%s-%s-%s" % (distro, arch, sruuid)
                else:
                    # The alternative is to clone a template, remove the option to create disks and just attach the copied VDI to the VM
                    tname = str(uuid.uuid4())
                tuuid = cli.execute("vm-clone", "name-label=\"%s\" new-name-label=%s" % (template, tname)).strip()
                host.genParamSet("template", tuuid, "PV-bootloader", "pygrub")
                host.genParamRemove("template", tuuid, "other-config", "disks")
                if xenrt.TEC().lookup("CLONE_PREBUILT_TEMPLATES", True, boolean=True):
                    # Add the VDI to the template
                    cli.execute("vbd-create", "vm-uuid=%s vdi-uuid=%s device=0 bootable=true" % (tuuid, vdiuuid))

                preinstalledTemplates = [tname]
            m.unmount()
        
    if not preinstalledTemplates:
        return None

    t = preinstalledTemplates[0]
    if rootdisk and rootdisk != Guest.DEFAULT:
        tuuid = host.minimalList("template-list", args="name-label=%s" % t, params="uuid")[0]
        if xenrt.TEC().lookup("CLONE_PREBUILT_TEMPLATES", True, boolean=True):
            vdiuuid=host.minimalList("vbd-list", args="vm-uuid=%s userdevice=0" % tuuid, params="vdi-uuid")[0]
        # Check that the disk is big enough
        if rootdisk*xenrt.MEGA > int(host.genParamGet("vdi", vdiuuid, "virtual-size")):
            return None
    g = host.guestFactory()(displayname, host=host)
    g.arch = arch
    g.distro=distro
    if vcpus:
        g.setVCPUs(vcpus)
    if corespersocket:
        g.setCoresPerSocket(corespersocket)
    if memory:
        g.setMemory(memory)
    g.createGuestFromTemplate(t, None)
    if not xenrt.TEC().lookup("CLONE_PREBUILT_TEMPLATES", True, boolean=True):
        # If we didn't attach the VDI to the template, we need to attach it to the VM here
        cli.execute("vbd-create", "vm-uuid=%s vdi-uuid=%s device=0 bootable=true" % (g.getUUID(), vdiuuid))
    g.ips = ips

    g.removeAllVIFs()
    if xenrt.isWindows(distro):
        g.windows = True
        g.vifstem = g.VIFSTEMHVM
        g.password = xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS", "ADMINISTRATOR_PASSWORD"])
    else:
        g.windows = False
        g.vifstem = g.VIFSTEMPV

    if vifs == xenrt.lib.xenserver.Guest.DEFAULT:
        vifs = [("0",
                 bridge or host.getPrimaryBridge(),
                 xenrt.randomMAC(),
                 None)]

    g.vifs = parseSequenceVIFs(g, host, vifs)
    for v in g.vifs:
        eth, bridge, mac, ip = v
        g.createVIF(eth, bridge, mac)

    g.existing(host)

    if "coreos-" in distro or preinstalledTools:
        g.enlightenedDrivers=True
        notools = True # CoreOS has tools installed already
    else:
        g.enlightenedDrivers = False

    g.changeCD("xs-tools.iso")
    g.special.update(special)
    g.start() 
    
    if not notools:
        g.installTools()
    
    return g

def createVM(host,
             guestname,
             distro,
             vcpus=None,
             corespersocket=None,
             memory=None,
             vifs=[],
             sriovvifs=[], # XXX currently unimplemented; see createVMFromFile
             bridge=None,
             sr=None,
             guestparams=[],
             arch="x86-32",
             disks=[],
             postinstall=[],
             packages=[],
             pxe=False,
             template=None,
             notools=False,
             bootparams=None,
             use_ipv6=False,
             suffix=None,
             ips={},
             **kwargs):


    canUsePrebuiltTemplate = not pxe and not guestparams and not template and not bootparams and not use_ipv6

    if not isinstance(host, xenrt.GenericHost):
        host = xenrt.TEC().registry.hostGet(host)

    (distro, special) = host.resolveDistroName(distro)
    rootdisk = xenrt.lib.xenserver.Guest.DEFAULT
    for disk in disks:
        device, size, format = disk
        if device == "0":
            rootdisk = int(size)*xenrt.KILO

    g = None

    if canUsePrebuiltTemplate:
        g = createVMFromPrebuiltTemplate(host,
                      guestname,
                      distro,
                      vcpus,
                      corespersocket,
                      memory,
                      vifs,
                      bridge,
                      sr,
                      arch,
                      rootdisk,
                      notools,
                      suffix,
                      ips,
                      special)
    if not g:
        if suffix:
            displayname = "%s-%s" % (guestname, suffix)
        else:
            displayname = guestname
        if distro.startswith("generic-"): 
            distro = distro[8:]
            if not vifs:
                # Some tests rely on getting a VIF by default for generic VMs.
                vifs = xenrt.lib.xenserver.Guest.DEFAULT
        if distro.lower() == "windows" or distro.lower() == "linux":
            distro = host.lookup("GENERIC_" + distro.upper() + "_OS"
                                 + (arch.endswith("64") and "_64" or ""),
                                 distro)
        # Create the guest object.
        if not template:
            template = host.getTemplate(distro, arch=arch)

        if re.search(r"etch", template or "", flags=re.IGNORECASE) or re.search(r"Demo Linux VM", template):
            password = xenrt.TEC().lookup("ROOT_PASSWORD_DEBIAN")
        else:
            password = xenrt.TEC().lookup("DEFAULT_PASSWORD")

        g = host.guestFactory()(displayname, 
                                template, 
                                password=password)
        g.distro = distro
        g.arch = arch
        if xenrt.isWindows(distro):
            g.windows = True
            g.vifstem = g.VIFSTEMHVM
            g.password = xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS", "ADMINISTRATOR_PASSWORD"])
        else:
            g.windows = False
            g.vifstem = g.VIFSTEMPV
        g.ips = ips
        if vifs == xenrt.lib.xenserver.Guest.DEFAULT:
            vifs = [("0",
                     host.getPrimaryBridge(),
                     xenrt.randomMAC(),
                     None)]

        vifs = parseSequenceVIFs(g, host, vifs)

        # The install method doesn't do this for us.
        if memory:
            g.setMemory(memory)
        if vcpus:
            if vcpus == "MAX":
                vcpus = g.getMaxSupportedVCPUCount()
                # Check if we need to do cores per socket (only if we have a MAXSOCKETS defined and are not using RND_CORES_PER_SOCKET
                # as that will take MAXSOCKETS into account anyway)
                if distro in xenrt.TEC().lookup(["GUEST_LIMITATIONS"]) and not xenrt.TEC().lookup("RND_CORES_PER_SOCKET", False, boolean=True):
                    maxsockets = xenrt.TEC().lookup(["GUEST_LIMITATIONS", distro, "MAXSOCKETS"], None)
                    if maxsockets and int(maxsockets) < vcpus:
                        if isinstance(host, xenrt.lib.xenserver.host.CreedenceHost):
                            g.setCoresPerSocket(vcpus / int(maxsockets))
                        else:
                            vcpus = maxsockets
            g.setVCPUs(vcpus)
        elif xenrt.TEC().lookup("RND_VCPUS", default=False, boolean=True):
            g.setRandomVcpus()
        if corespersocket:
            g.setCoresPerSocket(corespersocket)
        elif xenrt.TEC().lookup("RND_CORES_PER_SOCKET", default=False, boolean=True):
            g.setRandomCoresPerSocket(host, vcpus)

        if bootparams:
            bp = g.getBootParams()
            if len(bp) > 0: bp += " "
            bp += bootparams
            g.setBootParams(bp)

        # Try and determine the repository.
        repository = xenrt.getLinuxRepo(distro, arch, "HTTP", None)

        # Work out the ISO name.
        if not repository:
            isoname = xenrt.DEFAULT
        else:
            isoname = None

        g.special.update(special)
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

        g.reboot()
        g.check()

    if [x for x in disks if x[0] != "0"]:

        g.shutdown()

        diskstoformat = []
        for disk in disks:
            device, size, format = disk
            if not str(device) == "0":
                d = g.createDisk(sizebytes=int(size)*xenrt.GIGA,userdevice=device)
                if format:
                    diskstoformat.append(d)

        g.start()

        for d in diskstoformat:
            if g.windows:
                letter = g.xmlrpcPartition(d)
                g.xmlrpcFormat(letter, timeout=3600)
            else:
                letter = g.getHost().parseListForOtherParam("vbd-list",
                                                            "vm-uuid",
                                                            g.getUUID(),
                                                            "device",
                                                            "userdevice=%s" % (d))
                g.execguest("mkfs.ext2 /dev/%s" % (letter))
                g.execguest("mount /dev/%s /mnt" % (letter))

    # Store the object in the registry.
    xenrt.TEC().registry.guestPut(guestname, g)
    xenrt.TEC().registry.configPut(guestname, vcpus=vcpus,
                                   memory=memory,
                                   distro=distro)

    g.setStaticIPs()

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
            if "(" in p:
                eval("g.%s" % (p))
            else:
                eval("g.%s()" % (p))

    if packages:
        g.installPackages(packages)

    return g

#############################################################################


class MNRGuest(Guest):
    """Represents a MNR+ guest"""

    def __init__(self, name, template=None, host=None, password=None, reservedIP=None):
        Guest.__init__(self, name, template=template, host=host,
                              password=password, reservedIP=reservedIP)
        # dmcProperties contains static min, max then dynamic min,max
        self.dmcProperties = {}
        self.special['export suspended VM uses --preserve-power-state'] = True

    def populateSubclass(self, x):
        Guest.populateSubclass(self, x)
        x.dmcProperties = self.dmcProperties.copy()

    def __copy__(self):
        """Support for copy.copy()"""
        c = Guest.__copy__(self)
        # We have to copy the dmcProperties dictionary, otherwise we end up
        # with a reference to the current one in the copy
        c.dmcProperties = self.dmcProperties.copy()
        return c

    #########################################################################
    # Memory control methods
    def memset(self, memory):
        self.memory = memory
        xenrt.TEC().logverbose("Setting %s memory to %uMB" % (self.name, memory))
        cli = self.getCLIInstance()
        # Set the required memory (but NOT static-min)
        if self.host.getEdition() == "free":
            # We can't set it one parameter at a time any more...
            # Check if we're going below the template minimum
            oldsmin = int(self.paramGet("memory-static-min")) / xenrt.MEGA
            if oldsmin > memory:
                xenrt.TEC().warning("Setting %s static-min below what it was: "
                                    "was %uMB, setting to %uMB" %
                                    (self.getName(), oldsmin, memory))
                self.paramSet("memory-static-min", "%u" % (memory * xenrt.MEGA))
            self.setMemoryProperties(None, memory, memory, memory)
        else:
            # Is static-max going up or down?
            oldmax = int(self.paramGet("memory-static-max")) / xenrt.MEGA
            if memory > oldmax:
                # Going up, so set smax, then dmax, then dmin
                self.paramSet("memory-static-max", "%u" % (memory * xenrt.MEGA))
                self.paramSet("memory-dynamic-max", "%u" % (memory * xenrt.MEGA))
                self.paramSet("memory-dynamic-min", "%u" % (memory * xenrt.MEGA))
            else:
                # Going down, so set dmin, then dmax, then smax
                oldsmin = int(self.paramGet("memory-static-min")) / xenrt.MEGA
                if oldsmin > memory:
                    # We're probably dipping below the template minimum
                    xenrt.TEC().warning("Setting %s static-min below what it was: "
                                        "was %uMB, setting to %uMB" %
                                        (self.getName(), oldsmin, memory))
                    self.paramSet("memory-static-min", "%u" % (memory * xenrt.MEGA))
                self.paramSet("memory-dynamic-min", "%u" % (memory * xenrt.MEGA))
                self.paramSet("memory-dynamic-max", "%u" % (memory * xenrt.MEGA))
                self.paramSet("memory-static-max", "%u" % (memory * xenrt.MEGA))

        # Clear out any dmc properties
        for x in ["static-max", "dynamic-min", "dynamic-max"]:        
            if x in self.dmcProperties:
                del self.dmcProperties[x]

        # Check we've set it
        for x in ("memory-dynamic-max",
                  "memory-dynamic-min",
                  "memory-static-max"):
            m = (int(self.paramGet(x))/xenrt.MEGA)
            if m != memory:
                raise xenrt.XRTFailure("VM memory %uMB does not match the "
                                       "requested %uMB" % (m, memory))

    def check(self):
        Guest.check(self)
        # We set self.memory to 0 when we're using dmc values, to avoid existing
        # memory methods kicking in, so we need to check ourselves
        if self.memory == 0:
            self.checkMemory(inGuest=True)

    def setStaticMemRange(self, min, max):
        self.memory = 0
        if min and max:
            cli = self.getCLIInstance()
            args=[]
            args.append("uuid=%s" % (self.getUUID()))
            args.append("min=%dMiB" % (min))
            args.append("max=%dMiB" % (max))
            cli.execute("vm-memory-static-range-set", string.join(args))
            self.dmcProperties["static-min"] = min
            self.dmcProperties["static-max"] = max
        elif min:
            self.paramSet("memory-static-min", (min * xenrt.MEGA))
            self.dmcProperties["static-min"] = min
        elif max:
            self.paramSet("memory-static-max", (max * xenrt.MEGA))
            self.dmcProperties["static-max"] = max
        self.checkMemory()

    def setDynamicMemRange(self, min, max):
        self.memory = 0
        cli = self.getCLIInstance()
        args = []
        args.append("uuid=%s" % (self.getUUID()))
        args.append("min=%dMiB" % (min))
        args.append("max=%dMiB" % (max))
        cli.execute("vm-memory-dynamic-range-set", string.join(args))
        self.dmcProperties["dynamic-min"] = min
        self.dmcProperties["dynamic-max"] = max
        self.checkMemory()

    def setMemoryProperties(self, smin, dmin, dmax, smax):
        # Check for Nones (this means use the current value)
        if not smin:
            smin = int(self.paramGet("memory-static-min")) / xenrt.MEGA
        if not dmin:
            dmin = int(self.paramGet("memory-dynamic-min")) / xenrt.MEGA
        if not dmax:
            dmax = int(self.paramGet("memory-dynamic-max")) / xenrt.MEGA
        if not smax:
            smax = int(self.paramGet("memory-static-max")) / xenrt.MEGA
        cli = self.getCLIInstance()
        args = []
        args.append("uuid=%s" % (self.getUUID()))
        args.append("static-min=%dMiB" % (smin))
        args.append("dynamic-min=%dMiB" % (dmin))
        args.append("dynamic-max=%dMiB" % (dmax))
        args.append("static-max=%dMiB" % (smax))
        cli.execute("vm-memory-limits-set", string.join(args))
        self.dmcProperties["static-min"] = smin
        self.dmcProperties["dynamic-min"] = dmin
        self.dmcProperties["dynamic-max"] = dmax
        self.dmcProperties["static-max"] = smax
        self.checkMemory()

    def checkMemory(self, inGuest=False, allowTargetMismatch=False):
        # Check values match what we expect
        for x in ["static-min", "static-max", "dynamic-min", "dynamic-max"]:
            if x in self.dmcProperties:
                m = (int(self.paramGet("memory-%s" % (x)))/xenrt.MEGA)
                if m != self.dmcProperties[x]:
                    raise xenrt.XRTFailure("VM memory-%s %uMB does not match "
                                           "the expected %uMB" %
                                           (x, m, self.dmcProperties[x]))
            elif x != "static-min" and self.memory:
                m = (int(self.paramGet("memory-%s" % (x)))/xenrt.MEGA)
                if m != self.memory:
                    raise xenrt.XRTFailure("VM memory-%s %uMB does not match "
                                           "the expected %uMB" %
                                           (x, m, self.memory))

        # Check dynamic min+max are within static min+max etc
        dynamicMin = int(self.paramGet("memory-dynamic-min"))
        dynamicMax = int(self.paramGet("memory-dynamic-max"))
        staticMin = int(self.paramGet("memory-static-min"))
        staticMax = int(self.paramGet("memory-static-max"))
        if dynamicMin > dynamicMax:
            raise xenrt.XRTFailure("dynamic min is greater than dynamic max",
                                   "%u vs %u" % (dynamicMin, dynamicMax))
        if staticMin > staticMax:
            raise xenrt.XRTFailure("static min is greater than static max",
                                   "%u vs %u" % (staticMin, staticMax))
        if dynamicMin < staticMin or dynamicMax > staticMax:
            raise xenrt.XRTFailure("dynamic range is outside of static range",
                                   "%u-%u vs %u-%u" % (dynamicMin, dynamicMax,
                                                       staticMin, staticMax))


        target = self.getMemoryTarget()

        if inGuest:
            # Check the target is between dynamic min+max
            if target < dynamicMin or target > dynamicMax:
                raise xenrt.XRTFailure("memory-target is set outside of dynamic "
                                       "range", "%u outside of %u-%u" %
                                                (target, dynamicMin, dynamicMax))

        if inGuest:
            guest_reported = self.getGuestMemory()
            xenrt.TEC().logverbose("Guest reports %uM." % (guest_reported))
            # The amount the guest should report depends on the type of guest
            if self.windows:
                expected = staticMax / xenrt.MEGA
            else:
                expected = self.getMemoryActual() / xenrt.MEGA
            xenrt.TEC().logverbose("Expected %uM." % (expected))
            if guest_reported != expected:
                # Is it within 1%
                difference = abs(guest_reported - expected)
                percentage = float(difference) / float(expected)
                if percentage > 1:
                    xenrt.TEC().logverbose("Difference in expected memory "
                                           "value greater than 1%")
                    raise xenrt.XRTFailure("Guest saw an unxpected amount of "
                                           "memory", "Saw %u, expected %u" %
                                                     (guest_reported, expected))
                xenrt.TEC().logverbose("The difference of %.2f is allowed" %
                                       (percentage))

    def getMemoryTarget(self, fromRRD=False):
        if self.getState() != "UP":
            return int(self.paramGet("memory-target"))

        try:
            if fromRRD:
                # Get it from the RRD
                return int(self.getDataSourceValue("memory_target"))
            else:
                # Get it from Xenstore (this is the most accurate way)
                return int(self.host.xenstoreRead("/local/domain/%d/memory/target"
                                                  % (self.getDomid()))) * xenrt.KILO
        except:
            return int(self.paramGet("memory-target"))

    def getMemoryActual(self, fromRRD=True):
        if fromRRD:
            try:
                return int(self.getDataSourceValue("memory"))
            except:
                return int(self.paramGet("memory-actual"))
        else:
            return int(self.paramGet("memory-actual"))

    def waitForTarget(self, timeout, allowedTargetMismatch=0, desc="Target not reached within timeout"):
        """Waits for memory actual to reach memory target
        Raise failure if memory actual fails to reach memory target
        @param timeout: Maximum time for which function should wait for memory actual to reach target
        @param allowedTargetMismatch: Allowed difference in memory actual and target(beyond 1 percent) in MiBs
        @param desc: Message to be dislayed in case of failure.
        @return: None
        """

        startTime = xenrt.util.timenow()
        while (xenrt.util.timenow() - startTime) < timeout:
            target = self.getMemoryTarget()
            actual = self.getMemoryActual()
            if target != 0:
                difference = abs(target - actual)
                difference = min(abs(difference - allowedTargetMismatch ), difference)
                percentage = float(difference) / float(target)
                if percentage <= 1:
                    return
            xenrt.sleep(30)
        raise xenrt.XRTFailure("%s. Target=%u. Actual=%u." % (desc, target, actual))

    def makeCooperative(self, cooperative, xapiOnly=False):
        """Make a guest (un)cooperative to balloon requests"""

        if self.windows:
            # We need to set the FIST points in to xapi's xenstore-data key,
            # so they persist across migrate etc
            if cooperative: value = 0
            else: value = 1

            self.paramSet("xenstore-data:FIST/balloon/inflation", value)
            self.paramSet("xenstore-data:FIST/balloon/deflation", value)

        if not xapiOnly:
            xenrt.GenericGuest.makeCooperative(self, cooperative)

    ########################################################################
    # Checkpoint/revert methods
    def checkpoint(self, name=None):
        """Perform a checkpoint of the VM."""
        if not name:
            name = xenrt.randomGuestName()
        cli = self.getCLIInstance()
        command = ["vm-checkpoint"]
        command.append("uuid=%s" % (self.getUUID()))
        command.append("new-name-label=%s" % (name))
        return cli.execute(string.join(command), strip=True)

    def revert(self, uuid):
        """Revert to snapshot with UUID, uuid."""
        cli = self.getCLIInstance()
        command = ["snapshot-revert"]
        command.append("snapshot-uuid=%s" % (uuid))
        cli.execute(string.join(command), strip=True)

    def removeSnapshot(self, uuid, force=True):
        """Uninstall the snapshot with UUID, uuid."""
        cli = self.getCLIInstance()
        command = ["snapshot-uninstall"]
        command.append("snapshot-uuid=%s" % (uuid))
        if force: command.append("--force")
        cli.execute(string.join(command))

    def goState(self, state, on=None, choice=None, check=False):
        myhost = self.getHost()
        remote = on and myhost != on
        if remote and not (myhost.pool and on in myhost.pool.getHosts()):
            raise xenrt.XRTError("Couldn't move to a host not in current pool")
        # The most "direct" choice should be put in the first place
        # The most "safe" choice should be put in the last place (e.g. for HVM)
        choice = choice or 'direct'
        if choice == 'random':
            choice = random.choice
        elif choice == 'safe':
            choice = lambda l: l[-1]
        elif choice == 'direct':
            choice = lambda l: l[0]
        gomatrix =\
          {'UP':
             {'UP'       : remote
                           and choice([lambda :self.migrateVM(on,live="true",fast=not check),
                                       lambda :self.migrateVM(on,live="false",fast=not check),
                                       self.suspend,
                                       lambda :self.shutdown(againOK=True)])
                           or choice([None,
                                      lambda :self.migrateVM(myhost,live="true",fast=not check),
                                      lambda :self.migrateVM(myhost,live="false",fast=not check),
                                      None]),
              'PAUSED'   : remote
                           and (lambda :self.goState('UP', on, choice))
                           or self.pause,
              'SUSPENDED': self.suspend,
              'DOWN'     : lambda: self.shutdown(againOK=True)},
           'PAUSED':
             {'PAUSED'   : remote and self.unpause or None,
              'ANY'      : self.unpause},
           'SUSPENDED':
             {'UP'       : lambda :self.resume(on=remote and on or None,check=check,checkclock=check),
              'PAUSED'   : lambda :self.goState('UP', on, choice),
              'SUSPENDED': None,
              'DOWN'     : lambda :self.resume(check=check,checkclock=check) },
           'DOWN':
             {'UP'       : lambda : (remote
                                     and (self.setHost(on) or self.start())
                                     or self.start(specifyOn=False)),
              'PAUSED'   : lambda :self.goState('UP', on, choice),
              'SUSPENDED': lambda :self.start(specifyOn=False),
              'DOWN'     : None}
           }
        mystate = self.getState()
        xenrt.TEC().logverbose("Current state: %s, Object state: %s"
                               % (mystate,
                                  state + (remote and " at " + on.getName() or "")))
        action = gomatrix[mystate]
        if action.has_key(state):
            next = action[state]
        elif action.has_key('ANY'):
            next = action['ANY']
        else:
            raise xenrt.XRTError("No path to detined state %s" % state)
        if next:
            next()
            self.goState(state, on, choice)
        else:
            xenrt.TEC().logverbose("Arrive the destined status")

    def lifecycleSequence(self, pool=False, timeout=0, opcount=0,
                          norandom = False, check=False, back=True):
        initstate = self.getState()
        inithost = self.getHost()
        deadline = xenrt.timenow() + timeout
        restops = opcount
        states = [ 'UP', 'DOWN', 'PAUSED' ]
        if self.enlightenedDrivers:
            states.append('SUSPENDED')
        istate = 0
        places = pool and inithost.pool and inithost.pool.getHosts() or []
        places.append(None)
        iplace = 0
        choice = not self.enlightenedDrivers and 'safe' \
                 or (norandom and 'direct' or 'random')
        while xenrt.timenow() < deadline or restops > 0:
            if norandom:
                istate = istate + 1
                if istate >= len(states):
                    istate = 0
                    iplace = (iplace + 1) % len(places)
            else:
                istate = random.randint(0, len(states)-1)
                iplace = random.randint(0, len(places)-1)
            self.goState(states[istate], on=places[iplace],
                         choice=choice, check=check)
            if check and states[istate] == 'UP': check(self)
            restops = restops - 1
        if back: self.goState(initstate, on=inithost, choice=None)
        xenrt.TEC().logverbose("Lifecycle sequence finished successfully")

    def setNetworkViaXenstore(self, group, name, type, data, area=None, vif='eth0'):
        """ You'll need to restart the VM to make it effective."""
        if not (self.windows and self.enlightenedDrivers):
            raise xenrt.XRTError("setNetworkViaXenstore only works on "
                                     "Windows with PV drivers.")
        mac,ip,vb = self.getVIF(vif)
        macp = mac.replace(':', '_').upper()
        if not area:
            areaname = '_'.join([vif, group, name])
            area = ""
            for i in range(len(areaname)):
                if areaname[i].isalnum():
                    area += areaname[i]
                else:
                    area += '_'
        key = "vm-data/vif/%s/%s/%s" % (macp, group, area)
        try: self.paramRemove("xenstore-data", key)
        except: pass
        self.paramSet("xenstore-data:%s/name" % key, name)
        self.paramSet("xenstore-data:%s/type" % key, type)
        if type == 'remove':
            pass
        elif type == 'multi_sz':
            for i in range(len(data)):
                self.paramSet("xenstore-data:%s/data/%d" % (key,i), data[i])
        else:
            self.paramSet("xenstore-data:%s/data" % key, data)
        return key

class BostonGuest(MNRGuest):
    """Represents a Boston guest."""

    SNAPSHOT_CHECK_PARAMS = ['memory-dynamic-max',
                             'memory-dynamic-min',
                             'memory-static-max',
                             'memory-static-min',
                             'VCPUs-max',
                             'VCPUs-at-startup',
                             'actions-after-shutdown',
                             'actions-after-reboot',
                             'actions-after-crash',
                             'HVM-boot-policy',
                             'affinity',
                             'ha-restart-priority']

    def writeToConsole(self, str, retlines=0, cuthdlines=0):
        """Write str into this VM's main console stdin"""
        """and wait for retlines in stdout"""
        out = self.host.writeToConsole(self.getDomid(), str, tty=None, retlines=retlines,cuthdlines=cuthdlines)
        return out

    def setHAPriority(self, order=0, protect=True, restart=True):
        if protect:
            self.paramSet("order", order)
            if restart:
                self.paramSet("ha-restart-priority", "restart")
            else:
                self.paramSet("ha-restart-priority", "best-effort")
        else:
            self.paramSet("ha-restart-priority", "")
        # Synchronise changes across the pool.
        try:
            cli = self.getHost().getCLIInstance()
            cli.execute("pool-sync-database")
        except:
            pass

    def getHAPriority(self):
        return self.paramGet("order")

    def isProtected(self):
        if self.paramGet("ha-restart-priority") == "restart":
            return True
        else:
            return False

    def installWICIfRequired(self):
        """WIC is required to be installed on W2K3"""
        if float(self.xmlrpcWindowsVersion()) == 5.2:
            self.installWIC()

    def disableIPV4IfRequired(self):
        # CHECKME: Only after xmlrpcUnpackTarball is fixed, we can move disabling
        #          IPv4 into guest.install()
        assert (not self.ipv4_disabled)
        if self.use_ipv6 and xenrt.TEC().lookup("DISABLE_GUEST_IPV4", False, boolean=True):
            self.disableIPv4()
            self.ipv4_disabled = True

    def installDrivers(self, source=None, extrareboot=False, useLegacy=False, expectUpToDate=True):
        if not self.windows:
            xenrt.TEC().skip("Non Windows guest, no drivers to install")
            return
        self.installWICIfRequired()
        self.installDotNet4()
        self.disableIPV4IfRequired()
        MNRGuest.installDrivers(self, source, extrareboot, expectUpToDate)

    def setWindowsHostname(self, hostname):
        if self.windows:
            if len(hostname) > 15:
                xenrt.TEC().warning('Hostname too long for Windows: %s.  Using hostname: %s' % (hostname, hostname[0:15]))
                hostname = hostname[0:15]

            self.xmlrpcExec('wmic computersystem where name="%%COMPUTERNAME%%" call rename name="%s"' % (hostname))

    def _generateRunOnceScript(self):
        u = []
        for p in string.split(xenrt.TEC().lookup("PV_DRIVERS_DIR"), ";"):
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon.exe" -r update "%s\\xenvif.inf" XENBUS\\CLASS^&VIF""" % (p, p))
            u.append("ping 127.0.0.1 -n 20 -w 1000")
            u.append("""IF EXIST "%s\\xeniface.inf" "c:\\devcon.exe" -r update "%s\\xeniface.inf" XENBUS\\CLASS^&IFACE""" % (p, p))
            u.append("ping 127.0.0.1 -n 20 -w 1000")
            u.append("""IF EXIST "%s\\xennet.inf" "c:\\devcon.exe" -r update "%s\\xennet.inf" XEN\\vif""" % (p, p))
        for p in string.split(xenrt.TEC().lookup("PV_DRIVERS_DIR_64"), ";"):
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon64.exe" -r update "%s\\xenvif.inf" XENBUS\\CLASS^&VIF""" % (p, p))
            u.append("ping 127.0.0.1 -n 20 -w 1000")
            u.append("""IF EXIST "%s\\xeniface.inf" "c:\\devcon64.exe" -r update "%s\\xeniface.inf" XENBUS\\CLASS^&IFACE""" % (p, p))
            u.append("ping 127.0.0.1 -n 20 -w 1000")
            u.append("""IF EXIST "%s\\xenvif.inf" "c:\\devcon64.exe" -r update "%s\\xennet.inf" XEN\\vif""" % (p, p))
        return string.join(u, "\n")

##############################################################################

class TampaGuest(BostonGuest):

    VIFLOCK_NETWORK_DEFAULT = "network_default"
    VIFLOCK_LOCKED = "locked"
    VIFLOCK_UNLOCKED = "unlocked"
    VIFLOCK_DISABLED = "disabled"

    def getVifLockMode(self, vifUuid):
        return self.getCLIInstance().execute("vif-param-get param-name=locking-mode uuid=%s" % (vifUuid)).strip()

    def setVifLockMode(self, vifUuid, vifLockMode):
        """Sets the vif locking mode. Can take values: VIFLOCK_NETWORK_DEFAULT, VIFLOCK_LOCKED, VIFLOCK_UNLOCKED, VIFLOCK_DISABLED"""
        args = []
        args.append("uuid=%s" % (vifUuid))
        args.append("locking-mode=%s" % (vifLockMode))
        self.getCLIInstance().execute("vif-param-set", string.join(args))

    def clearVifAllowedAddresses(self, vifUuid):
        cli = self.getCLIInstance()
        cli.execute("vif-param-clear uuid=%s param-name=ipv4-allowed" % (vifUuid))
        cli.execute("vif-param-clear uuid=%s param-name=ipv6-allowed" % (vifUuid))

    def setVifAllowedIPv4Addresses(self, vifUuid, addresses):
        cli = self.getCLIInstance()
        for a in addresses:
            cli.execute("vif-param-add uuid=%s param-name=ipv4-allowed param-key=%s" % (vifUuid, a))

    def setVifAllowedIPv6Addresses(self, vifUuid, addresses):
        cli = self.getCLIInstance()
        for a in addresses:
            cli.execute("vif-param-add uuid=%s param-name=ipv6-allowed param-key=%s" % (vifUuid, a))

    def installDotNetRequiredForDrivers(self):
        """Tampa supports both .NET 3.5 and .NET 4, we set which version is required at the suite/sequence level"""

        dotnetversion = xenrt.TEC().lookup("DOTNETVERSION", None)
        if dotnetversion == "4":
            self.installDotNet4()
        elif dotnetversion == "3.5":
            self.installDotNet35()
        elif not dotnetversion:
            if not self.isDotNet35Installed():
                self.installDotNet4()
        else:
            raise xenrt.XRTError("Unsupported .NET version specified for PV driver install")

    def usesLegacyDrivers(self):
        """Returns True if the guest uses legacy drivers: This will use xenlegacy.exe from the tools iso.
        Otherwise, installwizard.msi from the tools iso will be used to install the new Tampa drivers"""

        if not self.distro:
            return False

        if not self.windows:
            raise xenrt.XRTError("usesLegacyDrivers() only applies to Windows guests")

        return "xp" in self.distro or "w2k3" in self.distro

    def installLegacyDrivers(self):
        self.installDrivers(useLegacy=True)

    def installDrivers(self, source=None, extrareboot=False, useLegacy=False, useHostTimeUTC=False, expectUpToDate=True, ejectISO=True):
        if not self.windows:
            xenrt.TEC().skip("Non Windows guest, no drivers to install")
            return

        # persist vif offload settings. If this is an upgrade we can compare these to the settings afterwards.
        offloadSettingsBefore = None
        try:
            offloadSettingsBefore = self.getVifOffloadSettings(0)
            xenrt.TEC().logverbose("xenvif settings before installing tools: %s" % str(offloadSettingsBefore))
        except:
            xenrt.TEC().logverbose("No xenvif settings found before installing tools. This must be a fresh install")

        # W2K3 and XP use the legacy drivers
        legacy = self.usesLegacyDrivers()

        # WIC is required to be installed for W2K3
        self.installWICIfRequired()

        # We support .NET 3.5 and .NET 4. This can be switched at the seq/suite level.
        self.installDotNetRequiredForDrivers()

        # Some filth
        self.disableIPV4IfRequired()

        # CA-56951 - [trunk stress failure] Windows guest agent did not report IP address
        self.increaseServiceStartTimeOut()

        # store domid before installation so can check for installer initiated reboot
        domid = self.host.getDomid(self)

        # Insert the tools ISO
        self.changeCD("xs-tools.iso")
        xenrt.sleep(30)

        if legacy or xenrt.TEC().lookup("USE_LEGACY_DRIVERS", False, boolean=True):

            self.installRunOncePVDriversInstallScript()

        if not legacy and (useLegacy or xenrt.TEC().lookup("USE_LEGACY_DRIVERS", False, boolean=True)):
            # We deliberately want to install the legacy drivers using xenlegacy.exe
            # This means if necessary resetting the platform flag

            try:
                newDriversDeviceId = self.paramGet("platform", "device_id") == "0002"
            except:
                newDriversDeviceId = False

            if newDriversDeviceId:
                self.shutdown()
                self.paramRemove("platform", "device_id")
                self.start()
            self.xmlrpcStart("D:\\xenlegacy.exe /AllowLegacyInstall /S")
        else:
            hostTimeString = ''
            if useHostTimeUTC:
                if not isinstance(self, xenrt.lib.xenserver.guest.ClearwaterGuest):
                    raise xenrt.XRTError('Windows guest agent HostTime=UTC functional only availalbe in Clearwater or later')
                hostTimeString = 'HOSTTIME=utc'

            # If source is specified, we should use it
            pvToolsTgz = source
            if not source:
                # See if we have an override at the job level
                pvToolsTgz = xenrt.TEC().lookup("PV_TOOLS_TGZ_" + self.host.productVersion.upper(), None)
            pvToolsDir = "D:"
            if pvToolsTgz:
                xenrt.TEC().logverbose("Using tools from: %s" % pvToolsTgz)
                if os.path.exists(pvToolsTgz):
                    toolsTgz = pvToolsTgz
                else:
                    toolsTgz = xenrt.TEC().getFile(pvToolsTgz)
                self.xmlrpcSendFile(toolsTgz, "c:\\tools.tgz")
                pvToolsDir = self.xmlrpcTempDir()
                self.xmlrpcExtractTarball("c:\\tools.tgz", pvToolsDir)

            self.xmlrpcStart("%s\\installwizard.msi /passive /liwearcmuopvx c:\\tools_msi_install.log %s" % (pvToolsDir, hostTimeString))

        # Monitor the guest for a domid change, this is the (first) reboot
        deadline = xenrt.util.timenow() + 3600
        while True:
            try:
                if self.host.getDomid(self) != domid:
                    break
            except:
                pass
            if xenrt.util.timenow() > deadline:
                self.checkHealth(desc="Waiting for installer reboot")
                raise xenrt.XRTFailure("Timed out waiting for installer initiated reboot")
            xenrt.sleep(30)

        if offloadSettingsBefore:
            # CA-87183: in the upgrade case, the Installed key gets set before installation is complete as the new drivers are forced
            # to install the old drivers first in order to set the hardware id. So the only safe way is just to wait for a set ammount of time.
            xenrt.sleep(20 * 60)
        else:
            while True:
                regValue = ""
                try:
                    regValue = self.winRegLookup('HKLM', "SOFTWARE\\Wow6432Node\\Citrix\\XenToolsInstaller", "InstallStatus", healthCheckOnFailure=False)
                except:
                    try:
                        regValue = self.winRegLookup('HKLM', "SOFTWARE\\Citrix\\XenToolsInstaller", "InstallStatus", healthCheckOnFailure=False)
                    except:
                        pass

                if xenrt.util.timenow() > deadline:
                    self.checkHealth(desc="Waiting for installer registry key to be written")

                    if regValue and len(regValue) > 0:
                        raise xenrt.XRTFailure("Timed out waiting for installer registry key to be written. Value=%s" % regValue)
                    else:
                        raise xenrt.XRTFailure("Timed out waiting for installer registry key to be written.")

                elif "Installed" == regValue:
                    break
                else:
                    xenrt.sleep(30)

        # now wait for PV devices to be connected
        count = 20
        for i in range(count):
            try:
                self.checkPVDevices()
                break
            except xenrt.XRTException:
                if i == count-1:
                    raise
                xenrt.sleep(120)

        # wait for guest agent
        self.waitForAgent(300, checkPvDriversUpToDate=expectUpToDate)

        self.enlightenedDrivers = True

        self.waitForDaemon(120, desc="Daemon connect after driver install")

        # wait for registry key to appear
        time.sleep(30)

        offloadSettingsAfter = self.getVifOffloadSettings(0)
        xenrt.TEC().logverbose("xenvif settings after installing tools: %s" % str(offloadSettingsAfter))

        # if the VM is moving from old PV drivers to new PV drivers
        # then we don't need to verify that offload settings are preserved
        if legacy and offloadSettingsBefore:
            offloadSettingsBefore.verifyEqualTo(offloadSettingsAfter)

        if extrareboot:
            self.reboot()
        
        if xenrt.TEC().lookup("DO_SYSPREP", False, boolean=True):
            self.xmlrpcDoSysprep()
            self.reboot()
            self.checkPVDevices()

        for i in range(12):
            if self.pvDriversUpToDate() or not expectUpToDate:
                break
            xenrt.sleep(10)

        # Eject tools ISO
        if ejectISO:
            self.changeCD(None)
            xenrt.sleep(5)

    def uninstallDrivers(self, waitForDaemon=True, source=None):

        # Insert the tools ISO
        self.changeCD("xs-tools.iso")
        xenrt.sleep(30)
        
        if source:
            if os.path.exists(source):
                toolsTgz = source
            else:
                toolsTgz = xenrt.TEC().getFile(source)
            self.xmlrpcSendFile(toolsTgz, "c:\\tools.tgz")
            pvToolsDir = self.xmlrpcTempDir()
            self.xmlrpcExtractTarball("c:\\tools.tgz", pvToolsDir)
        else:
            pvToolsDir = "D:"
            
        if self.usesLegacyDrivers() or xenrt.TEC().lookup("USE_LEGACY_DRIVERS", False, boolean=True):
            BostonGuest.uninstallDrivers(self, waitForDaemon)
        else:
            batch = ""

            if self.xmlrpcGetArch() == "amd64":
                batch = batch + "MsiExec.exe /X %s\\citrixxendriversx64.msi /passive /norestart\r\n" %(pvToolsDir)
                batch = batch + "ping 127.0.0.1 -n 10 -w 1000\r\n"
                batch = batch + "MsiExec.exe /X %s\\citrixguestagentx64.msi /passive /norestart\r\n" %(pvToolsDir)
                batch = batch + "ping 127.0.0.1 -n 10 -w 1000\r\n"
                batch = batch + "MsiExec.exe /X %s\\citrixvssx64.msi /passive /norestart\r\n" %(pvToolsDir)
            else:
                batch = batch + "MsiExec.exe /X %s\\citrixxendriversx86.msi /passive /norestart\r\n" %(pvToolsDir)
                batch = batch + "ping 127.0.0.1 -n 10 -w 1000\r\n"
                batch = batch + "MsiExec.exe /X %s\\citrixguestagentx86.msi /passive /norestart\r\n" %(pvToolsDir)
                batch = batch + "ping 127.0.0.1 -n 10 -w 1000\r\n"
                batch = batch + "MsiExec.exe /X %s\\citrixvssx86.msi /passive /norestart\r\n" %(pvToolsDir)

            batch = batch + "ping 127.0.0.1 -n 10 -w 1000\r\n"
            batch = batch + "MsiExec.exe /X %s\\installwizard.msi /passive /norestart\r\n" %(pvToolsDir)
            batch = batch + "ping 127.0.0.1 -n 10 -w 1000\r\n"
            batch = batch + "shutdown -r\r\n"

            self.xmlrpcWriteFile("c:\\uninst.bat", batch)
            self.xmlrpcStart("c:\\uninst.bat")

        # wait for reboot
        xenrt.sleep(6 * 60)

        if not self.xmlrpcIsAlive():
            raise xenrt.XRTFailure("XML-RPC not alive after tools uninstallation")

        installed = True
        i = 0
        while installed and i < 10:
            try:
                regValue = self.winRegLookup('HKLM', "SOFTWARE\\Wow6432Node\\Citrix\\XenToolsInstaller", "InstallStatus", healthCheckOnFailure=False)
            except:
                try:
                    regValue = self.winRegLookup('HKLM', "SOFTWARE\\Citrix\\XenToolsInstaller", "InstallStatus", healthCheckOnFailure=False)
                except:
                    installed = False

            if installed:
                xenrt.sleep(30)
            i = i + 1

        if installed:
            raise xenrt.XRTFailure("'Installed' reg key found after Tools uninstallation.")

        self.enlightenedDrivers = False

        if xenrt.TEC().lookup("USE_LEGACY_DRIVERS", False, boolean=True):
            self.xmlrpcShutdown()
            time.sleep(90)
            self.paramSet("platform:device_id", "0002")
            self.start()

        # Eject tools ISO
        self.changeCD(None)
        xenrt.sleep(5)

    def sxmVMMigrate(self,migrateParameters,pauseAfterMigrate=True,timeout = 3600,hostSessions=None):

        # This is the lib call for Storage Xen Motion Migrate
        #
        # Here is the list of all the parameters requied for this lib call
        #     1. migrateParameters: Its a dictionary of all the essential parameters
        #        required for migration, its like
        #        migrateParameters['VDI_SR_map': dict of source VDI to dest SR Map - Mandatory,
        #                          'VIF_NW_map': dict of source VIF to dest Network map - optional,
        #                          'dest_host': destination host uuid - Mandatory
        #                          'Migrate_Network': Network wich will be used for bulk transfer - optional]
        #     2. pauseAfterMigrate: This is a flag used to pause the VM after migration for verifying 
        #                           the integrity of vdi, its only for testing purpose
        #     3. timeout: Time required to wait for the migrate to happened
        #
        # Returns the object of observer

        eventClass = []
        xenrt.TEC().logverbose("Migrate Parameters: %s" % migrateParameters)

        if not migrateParameters.has_key("VDI_SR_map") or not migrateParameters.has_key("dest_host"):
            raise xenrt.XRTError("Essential parameters are not given")

        host = self.getHost()
        destHost = migrateParameters["dest_host"]

        if hostSessions:
            sourceSession=hostSessions[host.getName()]
            destSession=hostSessions[destHost.getName()]
        else:
            sourceSession = host.getAPISession(secure=False)
            destSession = destHost.getAPISession(secure=False)

        if not migrateParameters.has_key("Migrate_Network") or not migrateParameters["Migrate_Network"]:
            migrateParameters["Migrate_Network"] = destHost.getManagementNetworkUUID()

        xenrt.TEC().logverbose("Source Host uuid: %s,"
                                "Destination Host uuid: %s," % (host.getMyHostUUID(),destHost.getMyHostUUID()))

        eventClass.append("task")

        if host <> destHost:
            taskRef = self.vmLiveMigrate(migrateParameters,pauseAfterMigrate,sourceSession,destSession)
        else:
            #Might be different for VDI Migrate
            taskRef = self.vdiLiveMigrate(migrateParameters,sourceSession)           
        sxmObs = StorageMotionObserver(host, sourceSession,eventClass,taskRef,timeout)
        sxmObs.startObservingSXMMigrate(self,destHost,destSession)

        return sxmObs


    def vmLiveMigrate(self,migrateParameters,pauseAfterMigrate,session,destSession):

        vdiSRRefMap = {}
        vifNetworkRefMap = {}

        if not migrateParameters.has_key("VDI_SR_map") or not migrateParameters["VDI_SR_map"]:
            raise xenrt.XRTError("VDI SR Map not found")

        if not migrateParameters.has_key("dest_host") or not migrateParameters["dest_host"]:
            raise xenrt.XRTError("Destination host is not present")

        if not migrateParameters.has_key("Migrate_Network") or not migrateParameters["Migrate_Network"]:
            raise xenrt.XRTError("Network which will be used for bulk migration is not present")

        if not migrateParameters.has_key("VIF_NW_map"):
            migrateParameters["VIF_NW_map"] = {}

        vdiSRMap = migrateParameters["VDI_SR_map"]
        destHostuuid = migrateParameters["dest_host"].getMyHostUUID()
        networkUUID = migrateParameters["Migrate_Network"]
        optionsMap = {}
        if migrateParameters.has_key('copy'):
            optionsMap["copy"] = str(migrateParameters["copy"]).lower()

        xenrt.TEC().logverbose("VM Migrate Parameters: Source VM %s,"
                                                    "VDI to SR Map %s,"
                                                    "VIF to Network Map %s,"
                                                    "Source Host uuid %s,"
                                                    "Dest Host uuid %s,"
                                                    "Network uuid %s,"
                                                    "Options %s" % (self.getUUID(),vdiSRMap,migrateParameters["VIF_NW_map"],self.getHost().getMyHostUUID(),destHostuuid,networkUUID,optionsMap))

        for key in vdiSRMap.keys():
            vdiRef = session.xenapi.VDI.get_by_uuid(key)
            srRef = destSession.xenapi.SR.get_by_uuid(vdiSRMap[key])
            vdiSRRefMap[vdiRef] = srRef

        if migrateParameters["VIF_NW_map"]: 
            vifNetworkMap = migrateParameters["VIF_NW_map"]
            for key in vifNetworkMap.keys():
                vifRef = session.xenapi.VIF.get_by_uuid(key)
                networkRef = destSession.xenapi.network.get_by_uuid(vifNetworkMap[key])
                vifNetworkRefMap[vifRef] = networkRef 

        vmRef = session.xenapi.VM.get_by_uuid(self.getUUID())
        destHostRef = destSession.xenapi.host.get_by_uuid(destHostuuid)
        networkRef = destSession.xenapi.network.get_by_uuid(networkUUID)

        try:
            returnMap = destSession.xenapi.host.migrate_receive(destHostRef,networkRef,optionsMap)
            xenrt.TEC().logverbose("host.migrate_receive API being called on destination host : %s " %destHostuuid)
        except Exception, e:
            raise xenrt.XRTFailure("Exception occurred while calling migrate_receive on destination host: %s" %e)
        try:
            taskId = session.xenapi.Async.VM.migrate_send(vmRef,returnMap,pauseAfterMigrate,vdiSRRefMap,vifNetworkRefMap,optionsMap)
            xenrt.TEC().logverbose("Async.VM.migrate API being called on source host : %s " %self.getHost().getMyHostUUID())
        except Exception, e:
            raise xenrt.XRTFailure("Exception occurred while calling migrate send on source host: %s" %e)

        xenrt.TEC().logverbose("Migration started")
        return taskId

    def vdiLiveMigrate(self,migrateParameters,session):

        if not migrateParameters.has_key("VDI_SR_map") or not migrateParameters["VDI_SR_map"]:
            raise xenrt.XRTError("VDI SR Map not found")

        vdiSRMap = migrateParameters["VDI_SR_map"]

        if len(vdiSRMap.keys()) > 1:
            raise xenrt.XRTError("More then 1 VDI migration is not supported")
        else:
            vdiRef = session.xenapi.VDI.get_by_uuid(vdiSRMap.keys()[0])
            srRef = session.xenapi.SR.get_by_uuid(vdiSRMap[vdiSRMap.keys()[0]])

        try:
            strToStrMap = {}
            taskId = session.xenapi.Async.VDI.pool_migrate(vdiRef,srRef,strToStrMap)
        except Exception, e:
            raise xenrt.XRTFailure("Exception occurred while calling vdi pool migrate: %s" %e )

        return taskId

    def migrateVM(self, 
                  host=None, # For migration with shared storage, use host
                  live="false", 
                  fast=False, 
                  timer=None,
                  remote_host=None, # For storage xen motion, use remote_host
                  remote_user=None,
                  remote_passwd=None,
                  vdi_sr_list=None,
                  dest_sr=None,
                  vif_net_list=None,
                  encrypt=False,
                  remote_network=None,
                  copy=False):
        cli = self.getCLIInstance()
        if live == "true" and not self.windows:
            self.startLiveMigrateLogger()
        if timer:
            timer.startMeasurement()

        try:
            cmd = "vm-migrate uuid=%s" % self.getUUID()
            if remote_user is None:
                remote_user = "root"
            if remote_passwd is None and remote_host:
                remote_passwd = remote_host.password
            remote_master = None
            if remote_host and remote_host.pool and remote_host.pool.master:
                remote_master = remote_host.pool.master
            else:
                remote_master = remote_host
            if remote_master: # This cross-pool or intra-pool
                cmd = cmd + " remote-master=%s remote-username=%s remote-password=%s" % (
                    remote_master.getIP(), 
                    remote_user, 
                    remote_passwd)
            if vdi_sr_list:
                cmd = cmd + " " + " ".join(["vdi:%s=%s" % vdi_sr for vdi_sr in vdi_sr_list])
            elif dest_sr:
                cmd = cmd + " destination-sr-uuid=%s" % dest_sr
            if vif_net_list:
                cmd = cmd + " " + " ".join(["vif:%s=%s" % vif_net for vif_net in vif_net_list])
            if encrypt:
                cmd = cmd + " encrypt=true"
            if remote_network:
                cmd = cmd + " remote-network=%s" % remote_network
            if host:
                cmd = cmd + " host-uuid=%s" % host.getMyHostUUID()
            else:
                cmd = cmd + " host-uuid=%s" % remote_host.getMyHostUUID()
            if live == "true":
                cmd = cmd + " live=true"
            else:
                cmd = cmd + " live=false"
            if copy:
                cmd = cmd + " copy=true"

            cli.execute(cmd)

        except xenrt.XRTFailure, e:
            if re.search(r"VM failed to shutdown before the timeout expired",
                         e.reason) or \
                         re.search(r"Vmops.Domain_shutdown_for_wrong_reason",
                                   e.reason):
                # Might be a bluescreen etc.
                try:
                    self.checkHealth(noreachcheck=True)
                except xenrt.XRTFailure, f:
                    if re.search(r"Domain running but not reachable",
                                 f.reason):
                        # Report the original failure
                        raise e
                    raise f
            raise e

        if timer:
            timer.stopMeasurement()
        if live == "true" and not self.windows:
            self.stopLiveMigrateLogger()
        if xenrt.TEC().lookup("EXTRA_TIME", False, boolean=True):
            boottime = 720
        else:
            boottime = 360
        if host:
            self.setHost(host)
        elif remote_host:
            self.setHost(remote_host)
        if not fast:
            if not self.windows:
                self.waitForSSH(boottime, desc="Guest migrate SSH check")
            else:
                self.waitForDaemon(boottime, desc="Guest migrate XML-RPC check")

    def setHostnameViaXenstore(self):
        """
        ***** Method deprecated *****
        Setting hostname via XenStore was disabled in Tampa
        Use setHostname method for setting the hostname
        In Creedence a similar method has been added as a new implementation
        has been added
        """
        xenrt.TEC().logverbose("setHostnameViaXenstore not supported in this release")

    def waitForShutdownReady(self):
        # Best effort function to wait for feature-shutdown xenstore key to be set if VM is windows.
        try:
            if self.windows and self.enlightenedDrivers:
                # Try and wait for control/feature-shutdown to be 1. If it doesn't find it after 10 minutes, try and shutdown anyway
                domid = self.getDomid()
                startTime = xenrt.util.timenow() 
                while xenrt.util.timenow() < startTime + 600:
                    try:
                        if self.getHost().xenstoreRead("/local/domain/%u/control/feature-shutdown" % domid) == "1":
                            break
                    except:
                        pass
                    xenrt.sleep(30)
        except:
            pass

##############################################################################

class ClearwaterGuest(TampaGuest):

    def retreiveVmGenId(self):
    #Method to retreive VM Generation token id for Windows VM

        if float(self.xmlrpcWindowsVersion()) < 6.2:
            raise xenrt.XRTError("VM gen id is not supported in this windows version")

        if self.xmlrpcGetArch() == "x86": 
            vmgenexe = "vmgenid32.exe"
        elif self.xmlrpcGetArch() == "amd64":
            vmgenexe = "vmgenid64.exe"
        else :
            raise xenrt.XRTFailure("Cant find the appropriate vmgen.exe file for %s" % self.getName())

        #check if vmgen is already there else retreive from the build
        if not self.xmlrpcFileExists("c:\\%s" % (vmgenexe)):
            self.xmlrpcSendFile("%s/data/vmgenid/%s" % (xenrt.TEC().lookup("XENRT_BASE") ,vmgenexe ), "c:\\%s" % (vmgenexe))            

        #Run the vmgenid and return the value back to the function
        self.xmlrpcExec("c:\\%s > c://VmGen.log  " %(vmgenexe) , returndata = True )
        vmgenid = self.xmlrpcReadFile("c:\\VmGen.log").strip()
        xenrt.TEC().logverbose("VmgenID is %s" %(vmgenid))

        #Verify that ID genearated only consists of digits
        for i in vmgenid.split(':') :
            if not i.isdigit() :
                xenrt.TEC().warning("VM Generation Id contains characters other than digits")

        return vmgenid

    def createvGPU(self,groupUUID,vgpuConfigTypeUUID=None):

        args = []
        cli = self.getCLIInstance()

        args.append("vm-uuid=%s" % self.uuid)
        args.append("gpu-group-uuid=%s" % groupUUID)
        if vgpuConfigTypeUUID:
            args.append("vgpu-type-uuid=%s" % vgpuConfigTypeUUID)

        try:
            vgpuUUID = cli.execute("vgpu-create", " ".join(args), strip=True)
        except Exception, e:
            xenrt.TEC().logverbose("vGPU Creation failed with error %s" % str(e))
            raise xenrt.XRTFailure("vGPU Creation failed with error %s" % str(e))

        if vgpuConfigTypeUUID:
            vGPUType = self.host.genParamGet("vgpu-type",vgpuConfigTypeUUID,"model-name")        
            typeOfVGPU = self.host.genParamGet("vgpu",vgpuUUID,"type-model-name")

            if vGPUType != typeOfVGPU:
                raise xenrt.XRTFailure("vGPU type is not %s as intended but instead it is %s" % (vGPUType,typeOfVGPU))

    def destroyvGPU(self):

        args = []
        cli = self.getCLIInstance()

        vgpuuuid = self.host.minimalList("vgpu-list", args="vm-uuid=%s" % self.getUUID())[0]

        args.append("uuid=%s" % vgpuuuid)

        try:
            cli.execute("vgpu-destroy", " ".join(args), strip = True)
        except Exception, e:
            raise xenrt.XRTFailure("vGPU deletion failed with error %s" % str(e))

    def hasvGPU(self):
        """
        @rtype: bool
        @return: Guest has a vGPU assigned
        """
        return bool(self.host.parseListForUUID("vgpu-list", "vm-uuid", self.uuid))

    def setVGPUVNCActive(self, state):
        """
        Set VNC either enabled or disabled, depending on the provided state for a vgpu host 
        @type state: boolean
        @param state: if you should switch on or off vnc
        """
        option = "true"
        if not state:
            option = "false"

        if self.host.execdom0("xe vm-param-add uuid=%s param-name=platform vgpu_vnc_enabled=%s" % (self.uuid, option), retval="code") != 0:
            args = ["uuid=%s" % self.uuid, "platform:vgpu_vnc_enabled=%s" % option]
            self.getCLIInstance().execute("vm-param-set", string.join(args))

##############################################################################

class CreedenceGuest(ClearwaterGuest):
    def crash(self):
        xenrt.TEC().logverbose("Sleeping for 180 seconds to let the VM run for atleast 2 minutes before crashing")
        time.sleep(180)
        if self.windows:
            self.host.execdom0("/usr/sbin/xen-hvmcrash %d" % 
                               (self.getDomid()))
        else:
            panic = """
#include <linux/module.h>
#include <linux/init.h>
static int __init panic_init(void) { panic("XenRT Panic!"); }
module_init(panic_init);
"""        
            mkfile = """
obj-m  := panic.o
KDIR   := /lib/modules/$(shell uname -r)/build
PWD    := $(shell pwd)
default:
\t$(MAKE) -C $(KDIR) SUBDIRS=$(PWD) modules
"""
            m = xenrt.TEC().tempFile()
            p = xenrt.TEC().tempFile()
            file(m, "w").write(mkfile)
            file(p, "w").write(panic)
            sftp = self.sftpClient()
            sftp.copyTo(m, "Makefile")
            sftp.copyTo(p, "panic.c")
            self.execguest("make")
            try: self.execguest("insmod panic.ko", timeout=1)
            except: pass

    def setNameViaXenstore(self, name, reboot=True):
        """
        This is a second version of the mechanism to set the guest name
        via. xenstore. It was added in Creedence and the original for deprecated
        in Tampa
        NETBIOS name should be up 15 chars, the rest will be trucated
        """
        domid = self.getDomid()
        host = self.getHost()
        featurePresent = host.xenstoreRead("/local/domain/%u/control/feature-setcomputername" % domid).strip()
        if not featurePresent == "1":
            raise xenrt.XRTFailure("Cannot set the host name via. xenstore as the feature is not present")
        host.xenstoreWrite("/local/domain/%u/control/setcomputername/name" % domid, name)
        host.xenstoreWrite("/local/domain/%u/control/setcomputername/action" % domid, "set")

        # A reboot is required to make these changes appear in the guest
        if reboot:
            self.reboot()

    def dockerInstall(self):
        """Installs docker into a guest"""

        self.getDocker().install()

    def getDocker(self, method="XAPI"):

        if method == "XAPI":
            controller = xenrt.lib.xenserver.docker.XapiPluginDockerController
        elif method == "LINUX":
            controller = xenrt.lib.xenserver.docker.LinuxDockerController
        else:
            raise xenrt.XRTError("Unknown docker controller %s" % method)

        # The method by default uses docker interactions through Xapi.
        if self.distro.startswith("coreos"):
            return xenrt.lib.xenserver.docker.CoreOSDocker(self.getHost(), self, controller)
        elif self.distro.startswith("centos"): # CentOS7
            return xenrt.lib.xenserver.docker.CentOSDocker(self.getHost(), self, controller)
        elif self.distro.startswith("ubuntu"): #  Ubuntu 14.04
            return xenrt.lib.xenserver.docker.DebianBasedDocker(self.getHost(), self, controller)
        elif self.distro.startswith("debian"): #  Debian Jessie 8.0
            return xenrt.lib.xenserver.docker.DebianBasedDocker(self.getHost(), self, controller)
        else:
            raise xenrt.XRTFailure("Docker installation unimplemented on distro %s" % self.distro)

class DundeeGuest(CreedenceGuest):

    def setRandomPvDriverSource(self):
        #Randomly select PV Drivers Installation source
        
        with xenrt.GEC().getLock("RND_PV_DRIVER_INSTALL_SOURCE"):
            dbVal = xenrt.TEC().lookup("RND_PV_DRIVER_INSTALL_SOURCE_VALUE", None)
            if dbVal != None:
                return dbVal
            else:
                randomPvDriverInstallSource = random.choice(xenrt.TEC().lookup("PV_DRIVER_INSTALLATION_SOURCE"))
                xenrt.GEC().config.setVariable("RND_PV_DRIVER_INSTALL_SOURCE_VALUE",str(randomPvDriverInstallSource))
                xenrt.GEC().dbconnect.jobUpdate("RND_PV_DRIVER_INSTALL_SOURCE_VALUE",str(randomPvDriverInstallSource))
                return randomPvDriverInstallSource

    def setRandomPvDriverList(self):
        #Randomise the order of PV packages 

        with xenrt.GEC().getLock("RND_PV_DRIVERS_LIST"):
            dbVal = xenrt.TEC().lookup("RND_PV_DRIVERS_LIST_VALUE", None)
            if dbVal != None:
                return dbVal
            else:
                pvDriversList =xenrt.TEC().lookup("PV_DRIVERS_LIST")
                pvDriversList = pvDriversList.split(';')
                random.shuffle(pvDriversList)
                randomPvDriversList = ';'.join(pvDriversList)
                xenrt.GEC().config.setVariable("RND_PV_DRIVERS_LIST_VALUE",randomPvDriversList)
                xenrt.GEC().dbconnect.jobUpdate("RND_PV_DRIVERS_LIST_VALUE",randomPvDriversList)
                return randomPvDriversList

    def installTestCerts(self):

        if self.usesLegacyDrivers():
            xenrt.TEC().warning("Skipping the installation of TestCertificates")
            return

        xenrt.TEC().logverbose("installing TestCertificates")
        testCertsDir = xenrt.TEC().tempDir()
        path = self.xmlrpcTempDir()
        zipfile = "%s/keys/citrix/testsign.zip" % (xenrt.TEC().lookup("XENRT_CONF"))
        if not os.path.exists(zipfile):
            raise xenrt.XRTError("Cannot find testsign zip file")
 
        xenrt.util.command("unzip -d %s %s" % (testCertsDir, zipfile))
        files = xenrt.util.command("ls %s" % (testCertsDir), retval="string").strip()
        files = files.split("\n")
        for f in files:
            self.xmlrpcSendFile("%s/%s" % (testCertsDir,f),"%s\%s" % (path,f))
       
        self.xmlrpcExec("bcdedit.exe -set TESTSIGNING ON")
        for f in files:
           self.xmlrpcExec("certutil.exe -addstore -f 'Root' %s\%s" % (path,f))
           self.xmlrpcExec("certutil.exe -addstore -f 'TrustedPublisher' %s\%s" % (path,f))  

        self.reboot()
        xenrt.TEC().logverbose("Testcertificates installed")

    def installDrivers(self, source=None, extrareboot=False, useLegacy=False, useHostTimeUTC=False, expectUpToDate=True, ejectISO=True, installFullWindowsGuestAgent=True, useDotNet=True, pvPkgSrc = None):
        """
        Install PV Tools on Windows Guest
        """

        #Check if it a windows guest , progress only if it is windows
        if not self.windows:
            xenrt.TEC().skip("Non Windows guest, no drivers to install")
            return

        """Check the PV Driver source from where the tools to be installed 
        Random : Randomly choose either ToolsISO or Packages
        ToolsISO : Install PV Drivers through ToolsISO
        Packages : Install PV Drivers from individual PV packages
        """
        if pvPkgSrc:
            pvDriverSource =pvPkgSrc
        else:
            pvDriverSource = xenrt.TEC().lookup("PV_DRIVER_SOURCE", None)

        if pvDriverSource == "Random":
            pvDriverSource = self.setRandomPvDriverSource()

        if not xenrt.TEC().lookup("DONT_INSTALL_TEST_CERTS", False, boolean=True):
            self.installTestCerts()

        # If source is "ToolsISO" then install from xs tools
        if pvDriverSource == "ToolsISO" or pvDriverSource == None or useLegacy == True or xenrt.TEC().lookup("USE_LEGACY_DRIVERS", False, boolean=True) or self.usesLegacyDrivers():
            TampaGuest.installDrivers(self, source, extrareboot, useLegacy, useHostTimeUTC, expectUpToDate, ejectISO)

        #If source is "Packages" then install from PV Packages
        if pvDriverSource == "Packages":

            if useDotNet:
                # We support .NET 3.5 and .NET 4. This can be switched at the seq/suite level.
                self.installDotNetRequiredForDrivers()
            
            self.installCitrixCertificate()
                
            if installFullWindowsGuestAgent:
                self.installFullWindowsGuestAgent()
            
            if source:
                if os.path.exists(source):
                    toolsTgz = source
                else:
                    toolsTgz = xenrt.TEC().getFile(source)

                if not toolsTgz:
                    raise xenrt.XRTError("Failed to get Windows PV tools location")

                self.xmlrpcSendFile(toolsTgz, "c:\\tools.tgz")
            else:
            # Download the Individual PV packages
                self.xmlrpcSendFile(xenrt.TEC().getFile("xe-phase-1/%s" %(xenrt.TEC().lookup("PV_DRIVERS_LOCATION"))), "c:\\tools.tgz")
            pvToolsDir = self.xmlrpcTempDir()
            self.xmlrpcExtractTarball("c:\\tools.tgz", pvToolsDir)
            
            #Get the list of the Packages to be installed in random order
            packages = self.setRandomPvDriverList()
            packages = packages.split(';')
            
            #Install the PV Packages
            for pkg in packages:
                self.installPVPackage(pkg, pvToolsDir)
           
            xenrt.sleep(30)
            self.reboot()
                
            # now wait for PV devices to be connected
            count = 20
            for i in range(count):
                try:
                    self.checkPVDevices()
                    break
                except xenrt.XRTException:
                    if i == count-1:
                        raise
                    xenrt.sleep(120)

            # wait for guest agent
            self.waitForAgent(300, checkPvDriversUpToDate=expectUpToDate)

            self.enlightenedDrivers = True

            self.waitForDaemon(120, desc="Daemon connect after driver install")
            
            if extrareboot:
                self.reboot()
            
            #Check whether tools are up to date
            for i in range(12):
                if self.pvDriversUpToDate() or not expectUpToDate:
                    break
                xenrt.sleep(10)

    def installPVPackage(self, packageName = None, toolsDirectory = None):
        """ Installing Individual PV package """
        
        #If packageName is none then raise error
        if packageName is None:
            raise xenrt.XRTError("PV package to install not specified")
        
        #Download the tools if not present already
        if toolsDirectory is None:
            self.xmlrpcSendFile(xenrt.TEC().getFile("xe-phase-1/%s" %(xenrt.TEC().lookup("PV_DRIVERS_LOCATION"))), "c:\\tools.tgz")
            toolsDirectory = self.xmlrpcTempDir()
            self.xmlrpcExtractTarball("c:\\tools.tgz", toolsDirectory)
        
        #Get the Arch and install the appropriate Drivers 
        if self.xmlrpcGetArch().endswith('64'):
            arch = "x64"
        else:
            arch = "x86"
        self.xmlrpcStart("%s\\%s\\%s\\dpinst.exe /sw" % (toolsDirectory, packageName, arch))
        xenrt.sleep(30)

    def installFullWindowsGuestAgent(self):
        """ Install Windows Guest Agent from xs tools """
        
        #Mount the tools CD 
        self.changeCD("xs-tools.iso")
        xenrt.sleep(30)
        pvToolsDir = "D:"
        
        #Get the Arch and install the appropriate guest agent  
        if self.xmlrpcGetArch().endswith('64'):
            self.xmlrpcStart("%s\\citrixguestagentx64.msi  /passive /norestart" %(pvToolsDir))
        else:
            self.xmlrpcStart("%s\\citrixguestagentx86.msi  /passive /norestart" %(pvToolsDir))
        
        xenrt.sleep(30)
        
        #Eject the tools CD from the VM.
        self.changeCD(None)

    def sc(self, command ):
        """SC is a command line program used for communicating with the Service control manager and services"""
        
        return self.xmlrpcExec("sc %s" % (command), returnerror=False, returnrc=True) == 0
        
    def checkPVDriversStatus(self, ignoreException = False):
        """ Verify the Drivers are running by using 'SC' Command line program"""
        
        drivers = ['XENBUS','XENIFACE','XENVIF','XENVBD','XENNET']
        notRunning = []
        
        for driver in drivers:
            status = self.sc('query %s | find "RUNNING"' %(driver))
            if not status:
                notRunning.append(driver)
                
        if notRunning:
            if ignoreException:
                return False
            else:
                raise xenrt.XRTFailure(" %s services not running on %s" %(','.join(notRunning), self.getName()))
        else:
            return True
            
        xenrt.TEC().logverbose("PV Devices are installed and Running on %s " %(self.getName()))

    def uninstallDrivers(self, waitForDaemon=True, source=None):
        
        installed = False
        driversToUninstall = ['*XENVIF*', '*XENBUS*', '*VEN_5853*']
        
        var1 = self.winRegPresent('HKLM', "SOFTWARE\\Wow6432Node\\Citrix\\XenToolsInstaller", "InstallStatus")
        var2 = self.winRegPresent('HKLM', "SOFTWARE\\Citrix\\XenToolsInstaller", "InstallStatus")
        if var1 or var2:
            super(DundeeGuest , self).uninstallDrivers(waitForDaemon, source)
            
        else:
            #Drivers are installed using PV Packages uninstall them separately
            
            if self.xmlrpcGetArch().endswith('64'):
                devconexe = "devcon64.exe"
            else:
                devconexe = "devcon.exe"
                
            if not self.xmlrpcFileExists("c:\\%s" % devconexe):
                self.xmlrpcSendFile("%s/distutils/%s" % (xenrt.TEC().lookup("LOCAL_SCRIPTDIR"), devconexe), "c:\\%s" % devconexe)
                
            self.enablePowerShellUnrestricted()
            
            #Get the OEM files to be deleted after uninstalling drivers
            oemFileList = self.xmlrpcExec("pnputil.exe -e | select-string 'Citrix' -Context 1,0 | findstr 'oem'" , returndata = True, powershell=True).split()
            oemFileList = [item for item in oemFileList if item.startswith('oem')]
            
            batch = []
            
            for driver in driversToUninstall:
            
                batch.append("C:\\%s remove %s\r\n" %(devconexe, driver))
                batch.append("ping 127.0.0.1 -n 10 -w 1000\r\n")

            for file in oemFileList:
                batch.append("pnputil.exe -f -d %s\r\n" %(file)) 
                batch.append("ping 127.0.0.1 -n 10 -w 1000\r\n")
            batch.append("shutdown -r\r\n")
            
            self.xmlrpcWriteFile("c:\\uninst.bat", string.join(batch))
            self.xmlrpcStart("c:\\uninst.bat")

        if not self.xmlrpcIsAlive():
            raise xenrt.XRTFailure("XML-RPC not alive after tools uninstallation")
        
        # Verify PV devices have been removed after tools uninstallation
        if self.checkPVDevicesState():
            xenrt.TEC().logverbose("PV Packages are uninstalled Successfully")
        else:
            raise xenrt.XRTFailure("PV Packages are not uninstalled")
            
        self.enlightenedDrivers = False

    def enableWindowsPVUpdates(self):
        """ Enable the windows updates by setting 'auto-update-drivers' flag to true on the host"""

        if self.getState() != "DOWN":
            self.shutdown()

        if self.pvDriversUpToDate():
            raise xenrt.XRTFailure("Windows PV updates cannot be enabled on VM with PV Drivers Installed")

        self.paramSet("auto-update-drivers", "true")
        
        if not self.checkWindowsPVUpdates():
            raise xenrt.XRTFailure("Windows PV updates Failed to be enabled on VM")

    def disableWindowsPVUpdates(self):
        """ Disable the windows updates by setting 'auto-update-drivers' flag to false on the host"""
        
        if self.getState() != "DOWN":
            self.shutdown()

        if self.pvDriversUpToDate():
            raise xenrt.XRTFailure("Windows PV updates cannot be disabled on VM with PV Drivers Installed")

        self.paramSet("auto-update-drivers", "false")
        
        if self.checkWindowsPVUpdates():
            raise xenrt.XRTFailure("Windows PV updates Failed to be disabled on VM")

    def checkWindowsPVUpdates(self):
        """ Check whether the windows pv updates is enabled on the host"""
        
        return self.paramGet("auto-update-drivers")


    def _checkPVAddonsInstalled(self):
        """This is require by waitForAgent to check for host license from Dundee onwards """
        return True
 
class StorageMotionObserver(xenrt.EventObserver):

    def startObservingSXMMigrate(self,vm,destHost,destSession):

        self.destHost = destHost
        self.destSession = destSession
        self.srcHost = vm.getHost()
        self.vm = vm
        self.vmDownTime = 0

        if self.getTaskStatus() <> "pending":
            xenrt.TEC().logverbose("Migration has been completed/failed already")
            return

        if not self.isAlive():
            self.start()
        else:
            raise xenrt.XRTError("Storage Motion observer is already running")

        self.vm.startLiveMigrateLogger()

    def waitToFinish(self):

        if self.getTaskStatus() <> "pending":
            xenrt.TEC().logverbose("Migration has been completed/failed already")
            self.updateHost() 
            return

        self.join()
        self.updateHost()

    def updateHost(self):

        if self.vm:
            self.vmDownTime = self.vm.stopLiveMigrateLogger(isReturn=True)
        if self.taskId:
            if self.session <> None:
                if self.getTaskStatus() == 'success':
                    self.vm.setHost(self.destHost)
            else:
                raise xenrt.XRTError("Session is already closed")
        else:
            raise xenrt.XRTError("There is no task running/executed")

    def closeDestHostSession(self):

        self.destHost.logoutAPISession(self.destSession) 

    def getSXMResult(self):

        result = {}
        result = self.getResult()
        result["vmDownTime"] = self.vmDownTime

        return result

#############################################################################

def startMulti(guestlist,
               reboot=False,
               resume=False,
               timeout=None,
               no_on=False,
               clitimeout=7200,
               timer=None):
    """Start, reboot or resume multiple guests. This assumes the guests are
    enlightened (i.e. no arpwatch needed)."""

    if len(guestlist) == 0:
        if timer:
            timer.startMeasurement()
            timer.stopMeasurement()
        return

    status = []
    healthCheck = []

    if not timeout:
        timeout = 300 + 120 * len(guestlist)

    if reboot:
        desc = "Rebooting"
        op = "vm-reboot"
    elif resume:
        desc = "Resuming"
        op = "vm-resume"
    else:
        desc = "Starting"
        op = "vm-start"

    # Start the VMs
    try:
        host = guestlist[0].getHost()
        xenrt.TEC().progress("%s guests %s" %
                             (desc,
                              string.join([g.getName() for g in guestlist],
                                          ",")))
        host.lifecycleOperationMultiple(guestlist,
                                        op,
                                        no_on=no_on,
                                        timeout=clitimeout,
                                        timer=timer)
        for g in guestlist:
            status.append(0)
    except xenrt.XRTError, e:
        if e.reason == "Unimplemented":
            # Just do them individually
            for g in guestlist:
                xenrt.TEC().progress("%s guest VM %s" % (desc, g.name))
                g.lifecycleOperation(op)
                status.append(0)
        else:
            raise e
    xenrt.sleep(20)

    # Wait for each VM to enter the UP state then get an IP address
    deadline = xenrt.timenow() + timeout
    lastchance = True
    while True:
        waiting = False
        for i in range(len(guestlist)):
            g = guestlist[i]
            if status[i] == 0:
                # Waiting for this VM to be UP
                if g.getState() == "UP":
                    status[i] = 1
            if status[i] == 1:
                # Waiting to get an IP address for this guest
                vifname, a, b, c = g.vifs[0]
                mac, ip, vbridge = g.getVIF(vifname)
                if ip:
                    status[i] = 2
            if status[i] == 2:
                if not g.windows:
                    if xenrt.ssh.SSH(g.getIP(), "true",
                                     password=g.password,
                                     level=xenrt.RC_OK,
                                     timeout=20) == xenrt.RC_OK:
                        status[i] = 3
                else:
                    try:
                        xenrt.TEC().logverbose("Trying to contact XML-RPC daemon on %s." %
                                              (g.name))
                        g.xmlrpcVersion()
                        status[i] = 3
                    except:
                        pass
            if status[i] != 3:
                waiting = True
        if not waiting:
            # All started
            break
        if xenrt.timenow() > deadline:
            if lastchance:
                # Have one more go around the loop
                lastchance = False
            else:
                gueststoremove = []
                for i in range(len(guestlist)):
                    g = guestlist[i]
                    if status[i] == 0:
                        xenrt.TEC().logverbose("Guest %s is not yet UP" % (g.name))
                        gueststoremove.append(g)
                        healthCheck.append(g)
                    elif status[i] == 1:
                        xenrt.TEC().logverbose("Guest %s is waiting for IP" %
                                               (g.name))
                        gueststoremove.append(g)
                        healthCheck.append(g)
                    elif status[i] == 2:
                        xenrt.TEC().logverbose("Guest %s is waiting for SSH" %
                                               (g.name))
                        gueststoremove.append(g)
                        healthCheck.append(g)
                    elif status[i] == 3:
                        xenrt.TEC().logverbose("Guest %s is UP" % (g.name))
                for g in gueststoremove:
                    guestlist.remove(g)
        xenrt.sleep(15)

    if reboot:
        xenrt.TEC().logverbose("Rebooted %u guests" % (len(guestlist)))
    else:
        xenrt.TEC().logverbose("Started %u guests" % (len(guestlist)))

    xenrt.TEC().logverbose("Checking health of %u guests that failed to start"
                           % (len(healthCheck)))
    for g in healthCheck:
        try:
            g.checkHealth(desc=desc)
            xenrt.TEC().logverbose("Health check of %s OK" % (g.name))
        except xenrt.XRTFailure, e:
            xenrt.TEC().comment("Health check of %s: %s" % (g.name, str(e)))
            if e.data:
                xenrt.TEC().logverbose(str(e.data))

def shutdownMulti(guestlist, timeout=None, clitimeout=7200, timer=None):
    """Shutdown multiple guests."""

    if len(guestlist) == 0:
        if timer:
            timer.startMeasurement()
            timer.stopMeasurement()
        return

    xenrt.pmap(lambda g: g.waitForShutdownReady(), guestlist, interval = 1)

    status = []

    if not timeout:
        timeout = 300 + 60 * len(guestlist)

    # Shut the VMs down
    try:
        host = guestlist[0].getHost()
        xenrt.TEC().progress("Shutting down guests %s" %
                             (string.join([g.getName() for g in guestlist],
                                          ",")))
        host.lifecycleOperationMultiple(guestlist,
                                        "vm-shutdown",
                                        timeout=clitimeout,
                                        timer=timer)
        for g in guestlist:
            status.append(0)
    except xenrt.XRTError, e:
        if e.reason == "Unimplemented":
            # Just do them individually
            for g in guestlist:
                xenrt.TEC().progress("Shutting down guest VM %s" % (g.name))
                g.lifecycleOperation("vm-shutdown")
                status.append(0)
        else:
            raise e
    xenrt.sleep(20)

    # Poll for the guests going away
    deadline = xenrt.timenow() + timeout
    while True:
        waiting = False
        for i in range(len(guestlist)):
            g = guestlist[i]
            if status[i] == 0:
                # Waiting for this VM to be DOWN
                if g.getState() == "DOWN":
                    status[i] = 1
            if status[i] != 1:
                waiting = True
        if not waiting:
            # All shutdown
            break
        if xenrt.timenow() > deadline:
            gueststoremove = []
            for i in range(len(guestlist)):
                g = guestlist[i]
                if status[i] == 0:
                    xenrt.TEC().logverbose("Guest %s is not yet DOWN" %
                                           (g.name))
                    gueststoremove.append(g)
                elif status[i] == 1:
                    xenrt.TEC().logverbose("Guest %s is DOWN" % (g.name))
            for g in gueststoremove:
                guestlist.remove(g)
        xenrt.sleep(15)

    xenrt.TEC().logverbose("Shutdown %u guests" % (len(guestlist)))

class WinPE(xenrt._WinPEBase):
    def __init__(self, guest, arch):
        super(WinPE, self).__init__()
        self.guest = guest
        self.arch = arch

    def boot(self):
        self.guest.changeCD("winpe-%s.iso" % self.arch)
        # Start the VM to install from CD
        xenrt.TEC().progress("Starting VM %s for WinPE" % self.guest.name)

        self.guest.lifecycleOperation("vm-start")

        # Monitor ARP to see what IP address it gets assigned and try
        # to SSH to the guest on that address
        vifname, bridge, mac, c = self.guest.vifs[0]

        if self.guest.reservedIP:
            self.ip = self.guest.reservedIP
        else:
            arptime = 10800
            self.ip = self.guest.getHost().arpwatch(bridge, mac, timeout=arptime)

        if not self.ip:
            raise xenrt.XRTFailure("Did not find an IP address")

        xenrt.TEC().progress("Found WinPE IP address %s" % (self.ip))
        self.waitForBoot()
