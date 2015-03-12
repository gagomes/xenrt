#
# XenRT: Test harness for Xen and the XenServer product family
#
# Build a grub config file
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import string, sys, os, re
import xenrt

# Symbols we want to export from the package.
__all__ = ["GrubEntry",
           "GrubEntryXen",
           "GrubEntryLinux",
           "GrubConfig"]

class GrubEntry(object):
    """An individual entry in a GrUB config"""
    def __init__(self, cfg, label):
        self.cfg = cfg
        self.label = label
        self.root = "(hd0,0)"

    def setRoot(self, root):
        self.root = root

    def generate(self):
        pass

    def getInitrdPath(self):
        raise xenrt.XRTError("Unimplemented")

    def getKernelPath(self):
        raise xenrt.XRTError("Unimplemented")

    def getKernelArgs(self):
        raise xenrt.XRTError("Unimplemented")

    def populate(self, elements):
        raise xenrt.XRTError("Unimplemented")

class GrubEntryXen(GrubEntry):
    """An individual entry in a GrUB config for booting Xen"""
    def __init__(self, cfg, label):
        GrubEntry.__init__(self, cfg, label)
        self.kernel = ""
        self.module1 = ""
        self.module2 = ""
        self.kernelArgs = []
        self.module1Args = []
        self.module2Args = []

    def xenSetKernel(self, str):
        self.kernel = str

    def xenSetModule1(self, str):
        self.module1 = str

    def xenSetModule2(self, str):
        self.module2 = str

    def xenArgsKernelAdd(self, str):
        self.kernelArgs.append(str)

    def xenArgsModule1Add(self, str):
        self.module1Args.append(str)

    def xenArgsModule2Add(self, str):
        self.module2Args.append(str)

    def getKernelPath(self):
        return self.module1

    def getInitrdPath(self):
        return self.module2

    def getKernelArgs(self):
        return string.join(self.module1Args)

    def generate(self):
        return """title %s
        root %s
        kernel %s %s
        module %s %s
        module %s %s
""" % (self.label, self.root, self.kernel, string.join(self.kernelArgs),
       self.module1, string.join(self.module1Args),
       self.module2, string.join(self.module2Args))

    def populate(self, elements):
        if elements.has_key("root"):
            self.root = elements["root"][0]
        if elements.has_key("kernel"):
            x = string.split(elements["kernel"][0])
            self.kernel = x[0]
            self.kernelArgs = x[1:]
        if elements.has_key("module"):
            x = string.split(elements["module"][0])
            self.module1 = x[0]
            self.module1Args = x[1:]
            if len(elements["module"]) > 1:
                x = string.split(elements["module"][1])
                self.module2 = x[0]
                self.module2Args = x[1:]
        
class GrubEntryLinux(GrubEntry):
    """An individual entry in a GrUB config for booting Linux"""
    def __init__(self, cfg, label):
        GrubEntry.__init__(self, cfg, label)
        self.kernel = ""
        self.initrd = ""
        self.kernelArgs = []

    def linuxSetKernel(self, str):
        self.kernel = str

    def linuxSetInitrd(self, str):
        self.initrd = str

    def linuxArgsKernelAdd(self, str):
        self.kernelArgs.append(str)

    def getKernelPath(self):
        return self.kernel

    def getInitrdPath(self):
        return self.initrd

    def getKernelArgs(self):
        return string.join(self.kernelArgs)
    
    def generate(self):
        if self.initrd:
            return """title %s
        root %s
        kernel %s %s
        initrd %s
""" % (self.label, self.root, self.kernel, string.join(self.kernelArgs),
       self.initrd)
        return """title %s
        root %s
        kernel %s %s
""" % (self.label, self.root, self.kernel, string.join(self.kernelArgs))
    
    def populate(self, elements):
        if elements.has_key("root"):
            self.root = elements["root"][0]
        if elements.has_key("kernel"):
            x = string.split(elements["kernel"][0])
            self.kernel = x[0]
            self.kernelArgs.extend(x[1:])
        if elements.has_key("initrd"):
            x = string.split(elements["initrd"][0])
            self.initrd = x[0]

class GrubConfig(object):
    """Create a grub configuration."""
    def __init__(self):
        self.serport = "0"
        self.serbaud = "9600"
        self.entries = []
        self.default = "unknown"
        self.prompt  = "1"
        self.timeout = "5"

    def setSerial(self, serport, serbaud):
        """Set the serial settings."""
        self.serport = serport
        self.serbaud = serbaud

    def addEntry(self, label, default=0, boot="unknown"):
        """Add a new boot entry."""
        if boot == "xen":
            e = GrubEntryXen(self, label)
        elif boot == "linux":
            e = GrubEntryLinux(self, label)
        else:
            raise xenrt.XRTError("Unknown GrUB boot type %s" % (boot))
        if default:
            self.default = label
        self.entries.append(e)
        return e

    def setDefault(self, label):
        """Set the default boot entry. Supply a label, this will be
        matched with the entries to generate the index."""
        self.default = label

    def getDefault(self):
        """Look up the default entry index number"""
        counter = 0
        for i in self.entries:
            if i.label == self.default:
                return counter
            counter = counter + 1
        return 0 # XXX

    def getDefaultKernelPath(self):
        default = self.entries[self.getDefault()]
        return default.getKernelPath()

    def getDefaultInitrdPath(self):
        default = self.entries[self.getDefault()]
        return default.getInitrdPath()

    def getDefaultKernelArgs(self):
        default = self.entries[self.getDefault()]
        return default.getKernelArgs()

    def generate(self, common=True):
        """Generate the GrUB config as a multiline string."""
        reply = ""
        if common:
            if self.serport != None:
                reply = reply + ("serial --unit=%s --speed=%s\n" %
                                 (self.serport, self.serbaud))
                reply = reply + "terminal --timeout=2 serial console\n"
            reply = reply + "default=%u\n" % (self.getDefault())
            reply = reply + "timeout=%s\n" % (self.timeout)
            reply = reply + "\n"
                    
        for e in self.entries:
            reply = reply + e.generate() + "\n"
        return reply

    def existing(self, place):
        """Parse and existing grub config."""
        done = False
        for filename in ["/boot/grub/menu.lst", "/boot/grub/grub.conf"]:
            if place.execcmd("test -e %s" % (filename), retval="code") != 0:
                continue
            done = True
            defindex = 0
            data = place.execcmd("cat %s" % (filename))
            r = re.search(r"^timeout\s*=\s*(\d+)", data, re.MULTILINE)
            if r:
                self.timeout = r.group(1)
            r = re.search(r"^default\s*=\s*(\d+)", data, re.MULTILINE)
            if r:
                defindex = int(r.group(1))
            r = re.search(r"^serial\s+--unit=(\d+)\s+--speed=(\d+)",
                          data,
                          re.MULTILINE)
            if r:
                self.serport = r.group(1)
                self.serbaud = r.group(2)
            r = re.search(r"^timeout\s*=\s*(\d+)", data, re.MULTILINE)
            index = 0
            entlist = re.split(r"\n(title)", data)
            i = 0
            while i < len(entlist):
                if entlist[i] != "title":
                    i = i + 1
                    continue
                i = i + 1
                if i < len(entlist):
                    ll = entlist[i].split("\n")
                    title = string.strip(ll[0])
                    elements = {}
                    for e in ll[1:]:
                        r = re.search(r"^\s*(\S+)\s+(.*)", e)
                        if r:
                            if not elements.has_key(r.group(1)):
                                elements[r.group(1)] = []
                            elements[r.group(1)].append(r.group(2))
                    if elements.has_key("initrd"):
                        g = GrubEntryLinux(self, title)
                    elif elements.has_key("initrd"):
                        g = GrubEntryXen(self, title)
                    else:
                        g = GrubEntryLinux(self, title)
                    g.populate(elements)
                    self.entries.append(g)
                    if index == defindex:
                        self.default = title
                    index = index + 1
                i = i + 1
            if done:
                break
        if not done:
            raise xenrt.XRTError("Could not find a GrUB config to parse")
        
