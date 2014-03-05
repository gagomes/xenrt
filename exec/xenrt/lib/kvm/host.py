#
# XenRT: Test harness for Xen and the XenServer product family
#
# Encapsulate a kvm host.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import re, urllib

import xenrt

__all__ = ["createHost",
           "KVMHost"]

def createHost(id=0,
               version=None,
               pool=None,
               name=None,
               dhcp=True,
               license=True,
               diskid=0,
               diskCount=1,
               productType=None,
               productVersion=None,
               withisos=False,
               embedded=None,
               noisos=None,
               overlay=None,
               installSRType=None,
               suppackcds=None,
               addToLogCollectionList=False,
               noAutoPatch=False,
               disablefw=False,
               usev6testd=True,
               ipv6=None,
               noipv4=False):

    machine = str("RESOURCE_HOST_%s" % (id))

    m = xenrt.PhysicalHost(xenrt.TEC().lookup(machine, machine))
    xenrt.GEC().startLogger(m)

    if productVersion:
        distro = productVersion
        dd = distro.rsplit('-', 1)
        if len(dd) == 2 and dd[1] == "x64":
            distro = dd[0]
            arch = "x86-64"
        else:
            arch = "x86-32"
    else:
        distro = "centos64"
        arch = "x86-32"

    host = KVMHost(m)
    extrapackages = []
    extrapackages.append("libvirt")
    extrapackages.append("python-virtinst")
    extrapackages.append("kvm")
    extrapackages.append("bridge-utils")
    host.installLinuxVendor(distro, arch=arch, extrapackages=extrapackages, options={"ossvg":True})
    host.checkVersion()

    host.execdom0("sed -i 's/\\#listen_tcp = 1/listen_tcp = 1/' /etc/libvirt/libvirtd.conf")
    host.execdom0("sed -i 's/\\#listen_tls = 0/listen_tls = 0/' /etc/libvirt/libvirtd.conf")
    host.execdom0("sed -i 's/\\#auth_tcp = \"sasl\"/auth_tcp = \"none\"/' /etc/libvirt/libvirtd.conf")
    host.execdom0("sed -i 's/\\#LIBVIRTD_ARGS=\"--listen\"/LIBVIRTD_ARGS=\"--listen\"/' /etc/sysconfig/libvirtd")
    host.execdom0("service libvirtd restart")
    host.execdom0("service iptables stop")

    host.virConn = host._openVirConn()

    host.execvirt("virsh net-destroy default")
    host.execvirt("virsh net-undefine default")
    host.createNetwork("virbr0")

    networkConfig  = "<network>"
    networkConfig += "<name>virbr0</name>"
    networkConfig += "<forward mode='bridge'/>"
    networkConfig += "<bridge name='virbr0'/>"
    networkConfig += "</network>"
    host.execvirt("virsh net-define /dev/stdin <<< \"%s\"" % (networkConfig, ))

    # Create local storage with type EXT
    host.execdom0("lvcreate VGXenRT -l 100%FREE --name lv_storage")
    sr = xenrt.lib.kvm.EXTStorageRepository(host, "Local Storage")
    sr.createOn("/dev/VGXenRT/lv_storage")
    host.addSR(sr, default=True)

    xenrt.TEC().registry.hostPut(machine, host)
    xenrt.TEC().registry.hostPut(name, host)

    return host

class KVMHost(xenrt.lib.libvirt.Host):

    LIBVIRT_REMOTE_DAEMON = True

    def __init__(self, machine, productVersion="kvm", productType="kvm"):
        xenrt.lib.libvirt.Host.__init__(self, machine,
                             productType=productType,
                             productVersion=productVersion)

    def _getVirURL(self):
        return "qemu+tcp://%s/system" % (self.getIP(), )

    def guestFactory(self):
        return xenrt.lib.kvm.KVMGuest

    def lookupDefaultSR(self):
        # TODO
        return self.srs[self.defaultsr].uuid

    def getSRNameFromPath(self, srpath):
        """Returns the name of the SR in the path.
        srpath can be the SR mountpoint, or a volume within the mountpoint.
        Returns None if the path is not one of the above."""
        r = re.match(r"/var/run/sr-mount/([^/]*)", srpath)
        if r:
            return urllib.unquote(r.group(1))
        else:
            return None

    def getSRPathFromName(self, srname):
        return "/var/run/sr-mount/%s" % (urllib.quote(srname), )

    def getPrimaryBridge(self):
        # TODO
        return "virbr0"

    def createNetwork(self, name="bridge"):
        self.execvirt("virsh iface-bridge %s %s --no-stp 10" % (self.getDefaultInterface(), name))

    def removeNetwork(self, bridge=None, nwuuid=None):
        if bridge:
            self.execvirt("virsh iface-unbridge %s" % (bridge, ))

    def checkVersion(self):
        self.productVersion = "kvm"
        self.productRevision = self.execdom0("uname -r | cut -d'-' -f1")
