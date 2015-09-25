#
# XenRT: Test harness for Xen and the XenServer product family
#
# Encapsulate a libvirt host.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import pexpect, re, thread, xml

import xenrt
import libvirt

LIBVIRT_CONTROLLER_MIN_VERSION = 9004
LIBVIRT_GUEST_MIN_VERSION = 9000

__all__ = ["Host", "hostFactory"]

def hostFactory(hosttype):
    if hosttype == "ESX" or hosttype == "ESXi":
        return xenrt.lib.esx.ESXHost
    elif hosttype == "KVM":
        return xenrt.lib.kvm.KVMHost
    else:
        return xenrt.lib.libvirt.Host

class Host(xenrt.GenericHost):

    eventThread = None
    
    def __init__(self, machine, productType="libvirt", productVersion="libvirt"):
        xenrt.GenericHost.__init__(self, machine,
                                   productType=productType,
                                   productVersion=productVersion)
        self.guestversion = None
        self.guests = {}
        self.pool = None
        self.srs = {}
        self.defaultsr = None

    @classmethod
    def virEventLoop(cls):
        while True:
            libvirt.virEventRunDefaultImpl()

    def _getVirURL(self):
        """Create a libvirt virConnect object."""
        raise xenrt.XRTError("_getVirURL unimplemented")

    def _openVirConn(self):
        """Open a libvirt connection, and return the virConnect object.
        This method also ensures that the libvirt event is running."""

        def requestCredentials(creds, unused):
            for cred in creds:
                if cred[0] == libvirt.VIR_CRED_AUTHNAME:
                    cred[4] = "root"
                elif cred[0] == libvirt.VIR_CRED_PASSPHRASE:
                    cred[4] = self.password
                else:
                    return -1
            return 0

        # ensure an event loop is running
        if Host.eventThread is None:
            xenrt.TEC().logverbose("Starting libvirt event loop")
            libvirt.virEventRegisterDefaultImpl()
            Host.eventThread = thread.start_new_thread(Host.virEventLoop, ())

        # make the connection to the libvirt daemon on the guest
        xenrt.TEC().logverbose("Connecting to libvirt daemon for %s" % self)
        uri = self._getVirURL()
        auth = [[libvirt.VIR_CRED_AUTHNAME, libvirt.VIR_CRED_PASSPHRASE], requestCredentials, None]
        virConn = libvirt.openAuth(uri, auth, 0)

        # if necessary, check that the version of libvirt that's on the guest is recent enough
        if self.LIBVIRT_REMOTE_DAEMON and virConn.getLibVersion() < LIBVIRT_GUEST_MIN_VERSION:
            raise xenrt.XRTError("libvirt version on the guest (%d) is not recent enough (need >= %d)" %
                                 (virConn.getLibVersion(), LIBVIRT_GUEST_MIN_VERSION))

        return virConn

    def execvirt(self, cmd, cmdPostConnect=""):
        """Execute a command on the machine running libvirt. (Not in xenrt.lib.xenserver)"""
        if self.LIBVIRT_REMOTE_DAEMON:
            return self.execdom0(cmd)
        else:
            cmd += " --connect \"%s\" " % self._getVirURL()
            cmd += cmdPostConnect
            child = pexpect.spawn(cmd)
            child.expect("Enter username for .*: ")
            child.sendline("root")
            child.expect("Enter root's password for .*: ")
            child.sendline(self.password)
            output = child.read()
            xenrt.TEC().logverbose(output)
            child.close()
            if child.exitstatus != 0:
                raise xenrt.XRTFailure("libvirt command exited with error (%s)" % (cmd))
            else:
                return output

    def existing(self):
        """Query an existing host"""
        self.virConn = self._openVirConn()
        for guestname in self.listGuests():
            guest = self.guestFactory()(guestname, None)
            guest.existing(self)
            xenrt.TEC().logverbose("Found existing guest: %s" % (guestname))
        for sruuid in self.getSRs():
            isESX = ("esx" in self.productVersion.lower() or "esx" in self.productType.lower())
            isKVM = ("kvm" in self.productVersion.lower() or "kvm" in self.productType.lower())
            srname = self.getSRName(sruuid)
            if isESX and srname == "datastore1":
                srclass = xenrt.lib.esx.EXTStorageRepository
            elif isESX and srname == "XenRT ISOs":
                srclass = xenrt.lib.esx.ISOStorageRepository
            elif isESX and srname == "XenRT static ISOs":
                srclass = xenrt.lib.esx.ISOStorageRepository
            elif isESX and srname.startswith("local"):
                srclass = xenrt.lib.esx.EXTStorageRepository
            elif isKVM and srname.startswith("LocalStorage"):
                srclass = xenrt.lib.kvm.EXTStorageRepository
            elif isKVM and srname.startswith("XenRT ISOs"):
                srclass = xenrt.lib.kvm.ISOStorageRepository
            elif isKVM and srname.startswith("XenRT static ISOs"):
                srclass = xenrt.lib.kvm.ISOStorageRepository
            elif isKVM and srname.startswith("SR-"):
                srclass = xenrt.lib.kvm.EXTStorageRepository
            else:
                xenrt.TEC().logverbose("Warning: No way of identifying type of SR %s" % (srname))
                srclass = xenrt.lib.libvirt.sr.StorageRepository
            sr = srclass(self, srname)
            sr.existing()
            self.addSR(sr)
            xenrt.TEC().logverbose("Found existing %s SR: %s" % (sr.getType(), sr.name))

    def addGuest(self, guest):
        self.guests[guest.name] = guest

    def listGuests(self):
        # XXX: there is a race condition in this code;
        # if a VM is transitioning between the two states it may not appear
        # in either of the two sets
        inactive = set(self.virConn.listDefinedDomains())
        active = set([self.virConn.lookupByID(id).name() for id in self.virConn.listDomainsID()])
        return list(active | inactive)

    def createGenericLinuxGuest(self,
                                name=None,
                                arch=None,
                                start=True,
                                sr=None,
                                bridge=None,
                                vcpus=None,
                                memory=512,
                                allowUpdateKernel=True,
                                disksize=None,
                                use_ipv6=False):
        """Installs a generic Linux VM for non-OS-specific tests."""

        if not name:
            name = xenrt.randomGuestName()

        t = xenrt.lib.libvirt.createVM(
            self,
            name,
            "rhel62",
            vifs=xenrt.lib.libvirt.Guest.DEFAULT,
            vcpus=vcpus,
            memory=memory)

        if start and t.getState() == "DOWN":
            t.start()
        return t

    def getMyHostUUID(self):
        caps = xml.dom.minidom.parseString(self.virConn.getCapabilities())
        uuid = caps.getElementsByTagName("host")[0].getElementsByTagName("uuid")[0].childNodes[0].data
        caps.unlink()
        return uuid

    def check(self):
        pass

    #########################################################################
    # Storage operations
    # These are operations which work with SR UUIDs or names.
    # Host.srs is a map from SR names to StorageRepository classes,
    # the latter of which which you should work with if possible.
    #########################################################################

    def getSRUUID(self, srname):
        """Find the UUID of an SR given its name. (Not in xenrt.lib.xenserver)"""
        virPool = self.virConn.storagePoolLookupByName(srname)
        return virPool.UUIDString()

    def getSRName(self, sruuid):
        """Find the name of an SR given its UUID. (Not in xenrt.lib.xenserver)"""
        virPool = self.virConn.storagePoolLookupByUUIDString(sruuid)
        return virPool.name()

    def getSRs(self, type=None, local=False):
        """List our SR UUIDs"""
        filtered_srs = []
        for srname in self.virConn.listStoragePools():
            sruuid = self.getSRUUID(srname)
            if type is None or (srname in self.srs and type == self.srs[srname].getType()):
               filtered_srs.append(sruuid)
        return filtered_srs

    def getSRNameFromPath(self, srpath):
        raise xenrt.XRTError("Unimplemented")

    def getLocalSR(self):
        """Return a local SR UUID"""
        srl = self.getSRs(type="ext", local=True)
        if len(srl) == 0:
            srl = self.getSRs("lvm", local=True)
        if len(srl) == 0:
            raise xenrt.XRTError("Could not find suitable local SR")
        return srl[0]

    def hasLocalSR(self):
        """Returns True if the host has a local SR"""
        return len(self.getLocalSR()) > 0

    def removeLocalSR(self):
        """Removes a local SR on the host"""
        self.srs[self.getLocalSR()].destroy()

    def addSR(self, sr, default=False):
        """Add an SR object to the list of SRs this host knows about."""
        self.srs[sr.name] = sr
        if default:
            self.defaultsr = sr.name

    def destroyVDI(self, vdipath):
        """Destroys a VDI at vdipath.
        Note that the xenserver implementation takes a VDI UUID, however
        VDIs do not have UUIDs in libvirt."""
        srname = self.getSRNameFromPath(vdipath)
        srobj = self.srs[srname]
        vdiname = srobj.getVDINameFromPath(vdipath)
        srobj.destroyVDI(vdiname)

    def createVDI(self, sizebytes, sruuid=None, smconfig=None, name=None, format="raw"):
        """Creates a VDI on sruuid, or the default SR if unspecified.

        Returns the VDI *name*. This deviates from xenserver behaviour, which
        returns the VDI UUID. VDIs do not have UUIDs in libvirt."""
        if not sruuid:
            sruuid = self.lookupDefaultSR()
        srobj = self.srs[self.getSRName(sruuid)]
        if name is None:
            name = srobj.randomVDIName(format)
        srobj.createVDI(name, sizebytes, format=format)
        return name

    def getCDPath(self, cdname):
        """Find the path of a CD in an SR, given its name. (Not in xenrt.lib.xenserver)"""
        for srname in self.srs:
            srobj = self.srs[srname]
            for volname in srobj.listVDIs():
                if cdname == volname:
                    return srobj.getVDIPath(volname)

    def getTemplate(self, distro, hvm=None, arch=None):
        template = None
        try:
            if distro.startswith("w2k3"):
                template = self.chooseTemplate("TEMPLATE_NAME_WINDOWS_2003")
            elif distro.startswith("w2k"):
                template = self.chooseTemplate("TEMPLATE_NAME_WINDOWS_2000")
            elif distro.startswith("xpsp3"):
                template = self.chooseTemplate("TEMPLATE_NAME_WINDOWS_XP_SP3")
            elif distro.startswith("xp"):
                template = self.chooseTemplate("TEMPLATE_NAME_WINDOWS_XP")
            elif distro.startswith("vista"):
                template = self.chooseTemplate("TEMPLATE_NAME_VISTA")
            elif distro.startswith("ws08"):
                template = self.chooseTemplate("TEMPLATE_NAME_WS08")
            elif distro.startswith("win7"):
                template = self.chooseTemplate("TEMPLATE_NAME_WIN7")
            elif distro.startswith("win8"):
                template = self.chooseTemplate("TEMPLATE_NAME_WIN8")
            elif distro.startswith("debian"):
                v = re.search("debian(\d*)", distro).group(1)
                if v != "": v = "_" + v
                template = self.chooseTemplate("TEMPLATE_NAME_DEBIAN%s" % (v))
            elif distro.startswith("sarge"):
                template = self.chooseTemplate("TEMPLATE_NAME_DEBIAN_SARGE")
            elif distro.startswith("etch"):
                template = self.chooseTemplate("TEMPLATE_NAME_DEBIAN_ETCH")
            elif distro.startswith("rhel"):
                v = re.search(r"rhel(\d+)", distro).group(1)
                template = self.chooseTemplate("TEMPLATE_NAME_RHEL_%s" % (v))
            elif distro.startswith("centos"):
                v = re.search(r"centos(\d+)", distro).group(1)
                template = self.chooseTemplate("TEMPLATE_NAME_CENTOS_%s" % (v))
            elif distro.startswith("sles"):
                v = re.search(r"sles(\d+)", distro).group(1)
                template = self.chooseTemplate("TEMPLATE_NAME_SLES_%s" % (v))
            elif distro.startswith("solaris10u9-32"):
                template = self.chooseTemplate("TEMPLATE_NAME_SOLARIS_10U9_32")
            elif distro.startswith("solaris10u9"):
                template = self.chooseTemplate("TEMPLATE_NAME_SOLARIS_10U9")
            elif distro.startswith("ubuntu"):
                v = re.search("ubuntu(\d+)", distro).group(1)
                template = self.chooseTemplate("TEMPLATE_NAME_UBUNTU_%s" % (v))
            elif distro.startswith("other"):
                template = self.chooseTemplate("TEMPLATE_OTHER_MEDIA")
            else:
                raise LookupError("No suitable template available for %s." % (distro,))
        except LookupError as e:
            if distro.startswith("fc") or distro.startswith("rhel") or distro.startswith("centos"):
                xenrt.TEC().warning(e.reason)
                template = self.chooseTemplate("TEMPLATE_NAME_RHEL_5")
                xenrt.TEC().warning("Using a generic RedHat template: %s." % (template, ))
            else:
                raise xenrt.XRTError(str(e))

        return template

    def chooseTemplate(self, guesttype):
        """Choose a template name for installing a guest of this type"""
        # Try a per-version template name first and fall back to a global
        template = self.lookup(guesttype, None)
        if not template:
            raise xenrt.XRTError("Could not identify a suitable template for "
                                 "%s" % (guesttype))

        # See if we have a choice
        choices = template.split(",")
        return choices[0]

    def isEnabled(self):
        return True

    def getDomid(self, guest):
        """Return the domid of the specified guest."""
        #TODO: use virsh list output
        return "unknown"

    def getBridgeByName(self, name):
        """Return the actual bridge based on the given friendly name. Currently
        KVM has no way to store the friendly name of a bridge in its data model,
        therefore should overwrite this function. """
        return name
