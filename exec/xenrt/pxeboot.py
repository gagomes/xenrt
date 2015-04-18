#
# XenRT: Test harness for Xen and the XenServer product family
#
# PXE boot support
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import string, os.path, os, pwd, shutil
import xenrt, xenrt.resources

# Symbols we want to export from the package.
__all__ = ["PXEBootEntry",
           "PXEBootEntryLocal",
           "PXEBootEntryLinux",
           "PXEBootEntryIPXE",
           "PXEBootEntryMboot",
           "PXEBootEntryMbootImg",
           "PXEBoot",
           "PXEGrubBoot",
           "pxeHexIP",
           "pxeMAC",
           "PXEBootUefi"]

class PXEBootEntry(object):
    """An individual boot entry in a PXE config."""
    def __init__(self, cfg, label):
        self.cfg = cfg
        self.label = label

    def generate(self):
        pass

class PXEBootEntryLocal(PXEBootEntry):
    """An individual boot entry in a PXE config for local booting."""
    def __init__(self, cfg, label):
        PXEBootEntry.__init__(self, cfg, label)

    def generate(self):
        return """
LABEL %s
    LOCALBOOT 0
""" % (self.label)

class PXEBootEntryChainLocal(PXEBootEntry):
    """An individual boot entry in a PXE config for local booting."""
    def __init__(self, cfg, label, options):
        PXEBootEntry.__init__(self, cfg, label)
        if options:
            self.device = options
        else:
            self.device = "hd0"

    def generate(self):
        return """
LABEL %s
    KERNEL chain.c32
    APPEND %s
""" % (self.label, self.device)

class PXEBootEntryIPXE(PXEBootEntry):
    """An individual boot entry in a PXE config to boot iPXE."""
    def __init__(self, cfg, label):
        PXEBootEntry.__init__(self, cfg, label)

    def generate(self):
        if xenrt.TEC().lookup("EXTERNAL_PXE", False, boolean=True):
            self.cfg.copyIn("/tftpboot/ipxe.embedded.0") 
            return """
LABEL %s
    KERNEL %s
""" % (self.label, self.cfg.makeBootPath("ipxe.embedded.0"))
        else:
            return """
LABEL %s
    KERNEL %s
""" % (self.label, xenrt.TEC().lookup("IPXE_KERNEL", "ipxe.0"))

class PXEBootEntryLinux(PXEBootEntry):
    """An individual boot entry in a PXE config for Linux kernel booting."""
    def __init__(self, cfg, label):
        PXEBootEntry.__init__(self, cfg, label)
        self.kernel = ""
        self.kernelArgs = []

    def linuxSetKernel(self, str, abspath=False):
        if abspath:
            self.kernel=str
        else:
            self.kernel = self.cfg.makeBootPath(str)

    def linuxArgsKernelAdd(self, str):
        self.kernelArgs.append(str)

    def linuxGetArgsKernelString(self):
        return string.join(self.kernelArgs)

    def generate(self):
        if len(self.kernelArgs) > 0:
            extra = "    APPEND %s" % (self.linuxGetArgsKernelString())
        else:
            extra = ""
        return """
LABEL %s
    KERNEL %s
%s
""" % (self.label, self.kernel, extra)

class PXEBootEntryMemdisk(PXEBootEntry):
    def __init__(self, cfg, label):
        PXEBootEntry.__init__(self, cfg, label)
        self.initrd = ""
        self.args = None

    def setInitrd(self, initrd):
        self.initrd = initrd

    def setArgs(self, args):
        self.args = args

    def generate(self):
        if self.args:
            extra = "    APPEND %s" % (self.args)
        else:
            extra = ""
        return """
LABEL %s
    LINUX memdisk
    INITRD %s
%s
""" % (self.label, self.initrd, extra)

class PXEBootEntryPxeGrub(PXEBootEntryLinux):
    """An individual boot entry in a PXE config for pxegrub chainloading."""
    def __init__(self, cfg, label="pxegrub.0"):
        PXEBootEntryLinux.__init__(self, cfg, label)
        self.kernel = "boot/grub/pxegrub.0"

class PXEBootEntryMboot(PXEBootEntry):
    """An individual boot entry in a PXE config using multiboot."""
    def __init__(self, cfg, label):
        PXEBootEntry.__init__(self, cfg, label)
        self.kernel = ""
        self.module1 = ""
        self.module2 = ""
        self.kernelArgs = []
        self.module1Args = []
        self.module2Args = []

    def mbootSetKernel(self, str):
        self.kernel = self.cfg.makeBootPath(str)

    def mbootSetModule1(self, str):
        self.module1 = self.cfg.makeBootPath(str)

    def mbootSetModule2(self, str):
        self.module2 = self.cfg.makeBootPath(str)

    def mbootArgsKernelAdd(self, str):
        self.kernelArgs.append(str)

    def mbootArgsModule1Add(self, str):
        self.module1Args.append(str)

    def mbootArgsModule2Add(self, str):
        self.module2Args.append(str)

    def mbootGetArgsKernelString(self):
        return string.join(self.kernelArgs)

    def mbootGetArgsModule1String(self):
        return string.join(self.module1Args)

    def mbootGetArgsModule2String(self):
        return string.join(self.module2Args)

    def generate(self):
        return """
LABEL %s
    KERNEL mboot.c32
    APPEND %s %s --- %s %s --- %s %s
""" % (self.label, self.kernel, self.mbootGetArgsKernelString(),
       self.module1, self.mbootGetArgsModule1String(),
       self.module2, self.mbootGetArgsModule2String())

class PXEBootEntryMbootImg(PXEBootEntry):
    """An individual boot entry in a PXE config using multiboot."""
    def __init__(self, cfg, label):
        PXEBootEntry.__init__(self, cfg, label)
        self.mbootimg = self.cfg.makeBootPath("mboot.img")
        self.kernelArgs = []
        self.module1Args = []

    def mbootArgsKernelAdd(self, str):
        self.kernelArgs.append(str)

    def mbootArgsModule1Add(self, str):
        self.module1Args.append(str)

    def mbootGetArgsKernelString(self):
        return string.join(self.kernelArgs)

    def mbootGetArgsModule1String(self):
        return string.join(self.module1Args)

    def generate(self):
        return """
LABEL %s
    KERNEL %s
    APPEND %s -- %s
""" % (self.label, self.mbootimg, self.mbootGetArgsKernelString(),
       self.mbootGetArgsModule1String())

class PXEBoot(xenrt.resources.DirectoryResource):
    """A directory on a PXE server."""
    def __init__(self, place=None, abspath=False, removeOnExit=False, iSCSILUN=None, remoteNfs=None):
        self.abspath = abspath
        self.mount = None
        # Allow us to specify a guest to use as a PXE server.
        if not place:
            place = xenrt.TEC().registry.guestGet(xenrt.TEC().lookup("PXE_SERVER", None))
        if place:
            self.tftpbasedir = place.tftproot
        elif remoteNfs:
            self.mount = xenrt.MountNFS(remoteNfs)
            self.tftpbasedir = self.mount.getMount()
        else:
            self.tftpbasedir = xenrt.TEC().lookup("TFTP_BASE")
        self.iSCSILUN = iSCSILUN
        if self.iSCSILUN and not xenrt.TEC().lookup("USE_IPXE", False, boolean=True):
            raise xenrt.XRTError("Must use iPXE to use do iSCSI boot")
        self.pxebasedir = os.path.normpath(
            self.tftpbasedir + "/" + \
            xenrt.TEC().lookup("TFTP_SUBDIR", default="xenrt"))
        xenrt.resources.DirectoryResource.__init__(\
            self, self.pxebasedir, place=place)
        self.serport = "0"
        self.serbaud = "9600"
        self.entries = []
        self.default = "unknown"
        self.prompt  = "1"
        self.timeout = "20"
        self.filename = None
        self.iSCSINICs = []
        self.removeOnExit = removeOnExit
        self.iPXE = False
        if self.iSCSILUN:
            self.iPXE = True
        xenrt.TEC().gec.registerCallback(self)

    def setSerial(self, serport, serbaud):
        """Set the PXE serial settings."""
        self.serport = serport
        self.serbaud = serbaud

    def setPrompt(self, prompt):
        self.prompt = prompt

    def addEntry(self, label, default=0, boot="unknown", options=None):
        """Add a new boot entry."""
        if boot == "mboot":
            e = PXEBootEntryMboot(self, label)
        elif boot == "mbootimg":
            e = PXEBootEntryMbootImg(self, label)
        elif boot == "linux":
            e = PXEBootEntryLinux(self, label)
        elif boot == "ipxe":
            e = PXEBootEntryIPXE(self, label)
        elif boot == "local":
            e = PXEBootEntryLocal(self, label)
        elif boot == "chainlocal":
            e = PXEBootEntryChainLocal(self, label, options)
        elif boot == "pxegrub":
            e = PXEBootEntryPxeGrub(self, label)
        elif boot == "grub":
            e = PXEGrubBootEntry(self, label)
        elif boot == "memdisk":
            e = PXEBootEntryMemdisk(self, label)
        else:
            raise xenrt.XRTError("Unknown PXE boot type %s" % (boot))
        if default:
            self.default = label
        self.entries.append(e)
        return e

    def setDefault(self, label):
        """Set the default boot entry."""
        self.default = label

    def makeBootPath(self, str):
        """Turn a tempdir-relative file path and turn in into a TFTP_BASE
        relative path.
        """
        if self.abspath:
            return str
        
        # Get the absolute path
        abs = os.path.join(self.dir, str)
        
        # Now remove the basedir prefix
        preflen = len(os.path.normpath(self.tftpbasedir))
        return abs[preflen+1:]
    
    def generate(self):
        """Generate the PXE config as a multiline string."""
        if self.serport:
            reply = """# Generated by XenRT
SERIAL %s %s
PROMPT %s
TIMEOUT %s
DEFAULT %s

""" % (self.serport, self.serbaud, self.prompt, self.timeout,
               self.default)
        else:
            reply = """# Generated by XenRT
PROMPT %s
TIMEOUT %s
DEFAULT %s

""" % (self.prompt, self.timeout, self.default)
        for e in self.entries:
            reply = reply + e.generate() + "\n"
        return reply

    def _getIPXEDir(self):
        return xenrt.TEC().lookup("IPXE_CONF_DIR", self.tftpbasedir+"/ipxe.cfg")

    def _getUefiDir(self):
        return xenrt.TEC().lookup("EFI_DIR", self.tftpbasedir+"/EFI")

    def clearISCSINICs(self):
        self.iSCSINICs = []

    def addISCSINIC(self, index, pci):
        self.iSCSINICs.append((index, pci))

    def getIPXEFile(self, machine, forceip=None):
        if forceip:
            filename = "%s/%s" % (self._getIPXEDir(), forceip)
        else:
            filename = "%s/%s" % (self._getIPXEDir(), machine.pxeipaddr)
        return filename

    def waitForIPXEStamp(self, machine, forceip=None):
        if forceip:
            filename = "%s/%s.stamp" % (self._getIPXEDir(), forceip)
        else:
            filename = "%s/%s.stamp" % (self._getIPXEDir(), machine.pxeipaddr)
        self._rmtree(filename)
        xenrt.waitForFile(filename, 1800, desc="Waiting for iPXE config to be accessed on !%s" % (machine.name))

    def clearIPXEConfig(self, machine, forceip=None):
        xenrt.TEC().logverbose("Clearing iPXE config")
        self.iPXE = False
        if machine and self._exists("%s/%s" % (self._getIPXEDir(), machine.pxeipaddr)):
            self._rmtree("%s/%s" % (self._getIPXEDir(), machine.pxeipaddr))
        if forceip and self._exists("%s/%s" % (self._getIPXEDir(), forceip)):
            self._rmtree("%s/%s" % (self._getIPXEDir(), forceip))
    
    def clearUefi(self, machine, forceip=None):
        xenrt.TEC().logverbose("Clearing UEFI grub config")
        if machine and self._exists("%s/%s" % (self._getUefiDir(), machine.pxeipaddr)):
            self._rmtree("%s/%s" % (self._getUefiDir(), machine.pxeipaddr))
        if forceip and self._exists("%s/%s" % (self._getUefiDir(), forceip)):
            self._rmtree("%s/%s" % (self._getUefiDir(), forceip))

    def writeIPXEExit(self, machine, forceip=None):
        filename = self.getIPXEFile(machine, forceip)
        
        out = "goto end\n"

        t = xenrt.TEC().tempFile()
        f = file(t, "w")
        f.write(out)
        f.close()
        
        self._copy(t, filename)
        xenrt.TEC().logverbose("Wrote iPXE config file %s" % (filename))
        return filename

    def writeIPXEConfig(self, machine, script, forceip=None):
        self.iPXE = True
        filename = self.getIPXEFile(machine, forceip)
        
        if script:
            out = script
            out += "\ngoto end\n"
        else:
            out = ""

        t = xenrt.TEC().tempFile()
        f = file(t, "w")
        f.write(out)
        f.close()
        
        self._copy(t, filename)
        xenrt.TEC().logverbose("Wrote iPXE config file %s" % (filename))
        return filename

    def writeISCSIConfig(self, machine, forceip=None, boot=False):
        if not self.iSCSILUN:
            return

        filename = self.getIPXEFile(machine, forceip)


        out = "set initiator-iqn %s\n" % (self.iSCSILUN.getInitiatorName())

        for i in reversed(self.iSCSINICs):
            (nicid, pci) = i
            mac = machine.host.getNICMACAddress(nicid)
            (ip, netmask, gateway) = machine.host.getNICAllocatedIPAddress(nicid)
            net = machine.host.getNICNetworkName(nicid)

            out += """ifclose net0
set net0/mac %s
ifopen net0
set net0/ip %s
set net0/netmask %s
set net0/gateway %s
set override-pcibusdev 0x%x
sandescribe iscsi:%s:::%s:%s
""" % (mac, ip, netmask, gateway, pci, self.iSCSILUN.getSecondaryAddresses(net)[0], self.iSCSILUN.getLunID(), self.iSCSILUN.getTargetName())

        out += """ifclose net0
clear net0/mac
ifopen net0
clear net0/ip
clear net0/netmask
clear net0/gateway
dhcp
"""
  
        if boot:
            out += "sanboot --no-describe iscsi:%s:::%s:%s\n" % (self.iSCSILUN.getServer(), self.iSCSILUN.getLunID(), self.iSCSILUN.getTargetName())
        
        t = xenrt.TEC().tempFile()
        f = file(t, "w")
        f.write(out)
        f.close()
        
        self._copy(t, filename)
        xenrt.TEC().logverbose("Wrote iPXE config file %s" % (filename))
        return filename

    def writeOut(self, machine, forcemac=None, forceip=None, suffix=None, clearIPXE=True, clearUefi=True):
        """Write this config for the specified machine."""
        if clearIPXE:
            self.clearIPXEConfig(machine, forceip=forceip)
        if clearUefi:
            self.clearUefi(machine, forceip=forceip)
        pxedir = xenrt.TEC().lookup("PXE_CONF_DIR",
                                    self.tftpbasedir+"/pxelinux.cfg")


        if not self.iPXE:
            if machine and self._exists("%s/%s" % (self._getIPXEDir(), machine.pxeipaddr)):
                self._rmtree("%s/%s" % (self._getIPXEDir(), machine.pxeipaddr))
            if forceip and self._exists("%s/%s" % (self._getIPXEDir(), forceip)):
                self._rmtree("%s/%s" % (self._getIPXEDir(), forceip))

        if xenrt.TEC().lookup("USE_IPXE", False, boolean=True) and \
          self.default == "local" and \
          xenrt.TEC().lookupHost(machine.name,"IPXE_EXIT", False, boolean=True):
            self.writeIPXEExit(machine, forceip) 
        
        if not forcemac:
            forcemac = xenrt.TEC().lookupHost(machine.name,"PXE_MAC_ADDRESS", None)
        if forcemac:
            pxefile = pxeMAC(forcemac)
        elif forceip:
            pxefile = pxeHexIP(forceip)
        else:
            pxefile = xenrt.TEC().lookup("PXE_NAME_STYLE", "@IP@")
            pxefile = string.replace(pxefile, "@IP@", pxeHexIP(machine.pxeipaddr))
            pxefile = string.replace(pxefile, "@MAC@", pxeMAC(xenrt.TEC().lookupHost(machine.name,"MAC_ADDRESS")))
            pxefile = string.replace(pxefile, "@MACHINENAME@", machine.name)
            pxefile = string.replace(pxefile, "@MACHINESNAME@",
                                     string.split(machine.name, ".")[0])
            pxefile = string.replace(pxefile, "@LOGNAME@",
                                     pwd.getpwuid(os.getuid())[0])
        if suffix:
            pxefile += suffix
        filename = os.path.join(pxedir, pxefile)
        self.filename = filename
        if not self._exists(os.path.dirname(filename)):
            xenrt.TEC().logverbose("Making directory %s" %
                                   (os.path.dirname(filename)))
            self._makedirs(os.path.dirname(filename))
        t = xenrt.TEC().tempFile()
        f = file(t, "w")
        f.write(self.generate())
        f.close()
        # If this machine is configured to clean up (e.g. for dev machines), then remove on exit regardless of setting from caller
        if machine and xenrt.TEC().lookupHost(machine.name,"TFTP_CLEANUP", False, boolean=True):
            xenrt.TEC().logverbose("Marking PXE config file for removal on exit")
            self.removeOnExit = True
            xenrt.TEC().logverbose("Backing up existing PXE config file")
            if self._exists(self.filename):
                try:
                    xenrt.util.command("grep '# Generated by XenRT' %s || mv %s %s.xenrt.bak" % (self.filename, self.filename, self.filename))
                except:
                    xenrt.rootops.sudo("grep '# Generated by XenRT' %s || mv %s %s.xenrt.bak" % (self.filename, self.filename, self.filename))

        self._copy(t, filename)
        xenrt.TEC().logverbose("Wrote PXE config file %s" % (filename))
        return filename

    def callback(self):
        self.remove()

    def remove(self):
        if self.removeOnExit and self.filename:
            if self._exists(self.filename):
                self._rmtree(self.filename)
            if self._exists("%s.xenrt.bak" % self.filename):
                try:
                    xenrt.util.command("mv %s.xenrt.bak %s" % (self.filename, self.filename))
                except:
                    xenrt.rootops.sudo("mv %s.xenrt.bak %s" % (self.filename, self.filename))
        self._delegate.remove() 
        xenrt.TEC().gec.unregisterCallback(self)
        if self.mount:
            self.mount.unmount()


class PXEGrubBootEntry(PXEBootEntry):
    """An individual boot entry in a PXE Grub config for kernel booting."""
    def __init__(self, cfg, label):
        PXEBootEntry.__init__(self, cfg, label)
        self.kernel = ""
        self.kernelArgs = []

    def grubSetKernel(self, str):
        self.kernel = str #self.cfg.makeBootPath(str)

    def grubArgsKernelAdd(self, str):
        self.kernelArgs.append(str)

    def grubGetArgsKernelString(self):
        return string.join(self.kernelArgs)

    def generate(self):
        if len(self.kernelArgs) > 0:
            extra = "    module$ %s" % (self.grubGetArgsKernelString())
        else:
            extra = ""
        return """
title %s
    kernel$ %s
%s
""" % (self.label, self.kernel, extra)

class PXEGrubBoot(PXEBoot):
    """A PXEGrub chainloader on a PXE server."""
    def __init__(self, boottar=None, place=None, abspath=False, removeOnExit=False):
        PXEBoot.__init__(self, place, abspath, removeOnExit)
        self.serport = "0"
        self.serbaud = "115200"
        self.entries = []
        self.default = "pxegrub"
        self.prompt  = "1"
        self.timeout = "10"
        self.filename = None
        xenrt.TEC().logverbose("PXEGrubBoot boottar=%s" % (boottar))
        if boottar:
            # Pull pxegrub boot files from repository
            fboottar = xenrt.TEC().tempFile()
            wget = "wget '%s' -O '%s'" % (boottar, fboottar)
            xenrt.TEC().logverbose("PXEGrubBoot: %s" % wget)
            os.system("bash -c '%s'" % wget)
            xenrt.TEC().logverbose("PXEGrubBoot: tar xzjf -C \"%s\" \"%s\"" % (self.dir,fboottar))
            os.system("tar xjC '%s' -f '%s'" % (self.dir,fboottar))
            os.system("chmod -R a+w '%s'" % self.dir)
        self.pxeboot = PXEBoot()
        e = self.pxeboot.addEntry(self.default,default=1,boot="pxegrub")
        pxegrub0 = self.makeBootPath("boot/grub/pxegrub.0")
        xenrt.TEC().logverbose("PXEGrubBoot pxegrub0=%s" % (pxegrub0))
        e.kernel = pxegrub0

    #def __del__(self):
    #    # delete self.pxegrubdir

    def generate(self):
        """Generate the PXE config as a multiline string."""
        reply = """serial --unit=%s --speed=%s --word=8 --parity=no --stop=1
timeout=%s
default=0
min_mem64 1024
""" % (self.serport, self.serbaud, self.timeout)
        for e in self.entries:
            reply = reply + e.generate() + "\n"
        return reply

    def writeOut(self, machine, mac):
        """Write this config for the specified machine."""

        # write pxelinux's initial pxegrub.0 link
        grubfilename = self.pxeboot.writeOut(machine, forcemac=mac)

        # write pxegrub's second link in the boot chain
        pxedir = self.tftpbasedir
        # Construct a related menu.lst.01<mac> to pxegrub-boot from
        pxefile = "menu.lst." + pxeGrubMAC(mac)
        filename = os.path.join(pxedir, pxefile)
        t = xenrt.TEC().tempFile()
        f = file(t, "w")
        f.write(self.generate())
        f.close()
        self._copy(t, filename)
        xenrt.TEC().logverbose("Wrote PXEGRUB config file %s" % (filename))
        return (filename,grubfilename)

    def remove(self):
        self.pxeboot.remove()
        PXEBoot.remove(self)

def pxeHexIP(ip):
    octets = string.split(ip, ".")
    return "%02X%02X%02X%02X" % (int(octets[0]), int(octets[1]),
                                 int(octets[2]), int(octets[3]))

def pxeMAC(mac):
    octets = string.split(mac, ":")
    reply = ["01"]
    for i in octets:
        if len(i) == 1:
            reply.append("0%s" % (i))
        else:
            reply.append(i)
    return string.lower(string.join(reply, "-"))

def pxeGrubMAC(mac):
    ocs = string.split(mac, ":")
    return "01"+string.upper("".join(["%s" % oc for oc in ocs]))

class PXEBootUefi(xenrt.resources.DirectoryResource):
    def __init__(self):
        self.tftpbasedir = xenrt.TEC().lookup("TFTP_BASE")
        self.pxebasedir = os.path.normpath(
            self.tftpbasedir + "/" + \
            xenrt.TEC().lookup("TFTP_SUBDIR", default="xenrt"))
        xenrt.resources.DirectoryResource.__init__(\
            self, self.pxebasedir)
        xenrt.TEC().gec.registerCallback(self)
        self.bootdir = None
        self.entries = {}
        self.defaultEntry = None

    def setDefault(self, label):
        self.defaultEntry = label

    def addGrubEntry(self, label, text, default=False):
        self.entries[label] = text
        if default:
            self.defaultEntry = label

    def installBootloader(self, location, machine, forceip=None):
        ip = forceip or machine.pxeipaddr
        xenrt.TEC().logverbose("Installing UEFI PXE bootloader for %s" % ip)
        path = "%s/EFI/%s" % (self.tftpbasedir, ip)
        if not self._exists(path):
            os.makedirs(path)
        shutil.copyfile(location, "%s/boot.efi" % path)

    def uninstallBootloader(self, machine, forceip=None):
        ip = forceip or machine.pxeipaddr
        xenrt.TEC().logverbose("Removing UEFI PXE bootloader for %s" % ip)
        path = "%s/EFI/%s" % (self.tftpbasedir, ip)
        if self._exists(path):
            shutil.rmtree(path)

    def writeOut(self, machine, forceip=None):
        ip = forceip or machine.pxeipaddr
        path = "%s/EFI/xenserver" % self.tftpbasedir
        if not self._exists(path):
            os.makedirs(path)
        with open("%s/grub.cfg" % path, "w") as f:
            f.write("configfile /EFI/xenserver/$net_default_ip.cfg\n")
        with open("%s/%s.cfg" % (path, ip), "w") as f:
            f.write("set timeout=5\n\n")
            f.write("menuentry '%s' {\n" % self.defaultEntry)
            f.write(self.entries[self.defaultEntry])
            f.write("}\n")
        return "%s/%s.cfg" % (path, ip)

    def tftpPath(self):
        preflen = len(os.path.normpath(self.tftpbasedir))
        return self.path()[preflen:]

    def callback(self):
        self.remove()

    def remove(self):
        if self.removeOnExit and self.bootdir:
            if self._exists(self.bootdir):
                self._rmtree(self.bootdir)
            if self._exists("%s.xenrt.bak" % self.bootdir):
                try:
                    xenrt.util.command("mv %s.xenrt.bak %s" % (self.bootdir, self.bootdir))
                except:
                    xenrt.rootops.sudo("mv %s.xenrt.bak %s" % (self.bootdir, self.bootdir))
        self._delegate.remove() 
        xenrt.TEC().gec.unregisterCallback(self)

