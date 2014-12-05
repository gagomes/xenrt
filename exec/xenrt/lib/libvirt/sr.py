#
# XenRT: Test harness for Xen and the XenServer product family
#
# Encapsulate a libvirt SR.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import re, string

import xenrt
import libvirt

class StorageRepository(object):
    """Models a storage repository."""

    CLEANUP = "forget"
    SHARED = False

    TYPE = None

    def __init__(self, host, name):
        self.host = host
        self.name = name
        self.uuid = None
        self.lun = None
        self.resources = {}
        self.isDestroyed = False

        self.virPool = None

        # Recorded by _create for possible future use by introduce
        self.srxml = ""

    def create(self, physical_size=0, content_type=""):
        raise xenrt.XRTError("Unimplemented")

    def existing(self):
        self.virPool = self.host.virConn.storagePoolLookupByName(self.name)
        self.uuid = self.virPool.UUIDString()

    def introduce(self):
        """Re-introduce the SR - it must have been created with this object previously"""
        if not self.srxml:
            raise xenrt.XRTError("Cannot introduce SR because we don't have the SR's xml")
        self.host.execdom0("mkdir -p %s" % self.getPath())
        self.virPool = self.host.virConn.storagePoolDefineXML(self.srxml, 0)
        self.virPool.create(0)
        self.virPool.setAutostart(1)
        self.uuid = self.virPool.UUIDString()

    def forget(self):
        """Forget this SR (but keep the details in this object)"""
        self.virPool.destroy()
        self.virPool.undefine()

    def destroy(self):
        """Destroy this SR (but keep the details in this object)"""
        self.virPool.destroy()
        self.virPool.delete(0)
        self.virPool.undefine()
        self.isDestroyed = True

    def getType(self):
        return self.TYPE

    def getPath(self):
        return self.host.getSRPathFromName(self.name)

    def _create(self, type, sourceconf=None, targetconf=None):
        xenrt.TEC().logverbose("Creating %s sr named \"%s\"" % (type, self.name))
        sourcexml = ""
        if sourceconf:
            sourcexml = "<source>%s</source>" % sourceconf
        targetxml = "<target>%s %s</target>" % ("<path>%s</path>" % self.getPath(),
                                                targetconf)
        self.srxml = """<pool type="%s">
  <name>%s</name>
  %s
  %s
</pool>""" % (type, self.name, sourcexml, targetxml)
        self.introduce()


    def check(self):
        self.checkCommon(self.srtype)
        return True

    def checkCommon(self, srtype):
        #TODO
        pass

    def _createVDI(self, vdiname, format="raw", extra=""):
        virVol = self.virPool.createXML("""
            <volume>
                <name>%s</name>
                <target>
                    <path>%s</path>
                    <format type='%s'/>
                </target>
                %s
            </volume>""" % (vdiname, self.getVDIPath(vdiname), format, extra), 0)
        return virVol.path()

    def createVDI(self, vdiname, sizebytes, format="raw", sparse=False):
        """Creates a VDI. Returns the VDI's *path*. Note that this is different behaviour to Host.createVDI."""
        if sparse:
            allocation = 0
        else:
            allocation = sizebytes

        xenrt.TEC().progress("Creating %s VDI '%s' of size %d" % (format, vdiname, sizebytes))

        return self._createVDI(vdiname, format=format, extra="""
            <capacity unit='bytes'>%d</capacity>
            <allocation unit='bytes'>%d</allocation>""" % (sizebytes, allocation))

    def destroyVDI(self, vdiname):
        self.virVol = self.virPool.storageVolLookupByName(vdiname)
        self.virVol.delete(0)

    def copyVDI(self, srcvdiname, destvdiname=None):
        if destvdiname is None:
            destvdiname = self.generateCloneName(srcvdiname, forcebranch=True)

        xenrt.TEC().progress("Copying VDI '%s' to '%s'" % (srcvdiname, destvdiname))

        virSrcVol = self.virPool.storageVolLookupByName(srcvdiname)
        srccapacity = re.search(r"<capacity.*</capacity>", virSrcVol.XMLDesc(0)).group(0)
        srcallocation = re.search(r"<allocation.*</allocation>", virSrcVol.XMLDesc(0)).group(0)
        virVol = self.virPool.createXMLFrom("""
            <volume>
                <name>%s</name>
                <target>
                    <path>%s</path>
                    <format type='%s'/>
                </target>
                %s
                %s
            </volume>""" % (destvdiname, self.getVDIPath(destvdiname), self.getVDIFormat(srcvdiname), srccapacity, srcallocation),
            virSrcVol, 0)
        return virVol.path()

    def cloneVDI(self, srcvdiname, destvdiname=None):
        # we don't have a fast cloning routine
        # fall back to a full copy
        return self.copyVDI(srcvdiname, destvdiname)

    def listVDIs(self):
        """Return a list of VDIs in this SR."""
        try:
            # for some stupid reason libvirt lists lost+found as a volume
            return filter(lambda v: v != "lost+found", self.virPool.listVolumes())
        except libvirt.libvirtError:
            # perhaps the SR was not accessible
            return []

    def remove(self):
        # TODO
        # Shutdown and remove all VMs on the SR.
        # Try to remove any left over VDIs
        pass

    def prepareSlave(self, master, slave, special=None):
        """Perform any actions on a slave before joining a pool that are
        needed to work with this SR type. Override if needed.
        """
        pass

    def release(self):
        self.remove()

    def generateCloneName(self, oldnameorpath, forcebranch=False, filesuffix=None):
        """Generates a clone name or path given an existing VDI name or path"""
        prefix, oldclonesuffix, oldfilesuffix = re.match(r"^(.*?)(clone\d+)?\.([^\.]*)$", oldnameorpath).groups()
        oldname = self.getVDINameFromPath(prefix) or prefix
        if forcebranch and oldclonesuffix:
            oldname = oldname + str(oldclonesuffix)
        if filesuffix is None:
            filesuffix = oldfilesuffix
        clonenum = 0
        for vdiname in self.virPool.listVolumes():
            r = re.match(r"%s-clone(\d+).*" % re.escape(oldname), vdiname)
            if r:
                clonenum = max(clonenum, int(r.group(1)))
        return "%s-clone%d.%s" % (prefix, clonenum+1, filesuffix)

    def randomVDIName(self, format):
        """Generates a random VDI name."""
        return "%s.%s" % (xenrt.randomGuestName(), format)

    def scan(self):
        """Not applicable to libvirt SRs."""
        pass

class ISOStorageRepository(StorageRepository):
    """Models an ISO SR"""

    TYPE = "iso"

    def create(self, server, path):
       self._create("netfs", "<host name='%s'/><dir path='%s'/>" % (server, path), "")

class EXTStorageRepository(StorageRepository):
    """Models an EXT storage repository."""

    SHARED = False
    CLEANUP = "destroy"

    TYPE = "ext"

    def create(self, device, physical_size=0, content_type=""):
        """Creates an EXT SR on a device."""
        self.host.execdom0("pvcreate %s" % device)
        self.host.execdom0("vgcreate vg1 %s" % device)
        self.host.execdom0("lvcreate vg1 -l 100%FREE --name lvextsr")
        self.createOn("/dev/vg1/lvextsr")

    def createOn(self, lvdevice):
        """Creates an EXT SR on a logical volume."""
        self.host.execdom0("mkfs -t ext3 %s" % lvdevice)
        path = self.getPath()
        self.host.execdom0("mkdir -p %s" % path)
        self.host.execdom0("mount %s %s" % (lvdevice, path))
        self.host.execdom0("echo '%s %s ext3 defaults 1 1' >> /etc/fstab" % (lvdevice, path))
        self._create("dir", "", "<path>%s</path>" % path)

class NFSStorageRepository(StorageRepository):
    """Models an NFS SR"""

    SHARED = True

    TYPE = "nfs"

    def create(self, server=None, path=None, physical_size=0, content_type="", nosubdir=False):
        if not (server or path):
            if xenrt.TEC().lookup("FORCE_NFSSR_ON_CTRL", False, boolean=True):
                # Create an SR using an NFS export from the XenRT controller.
                # This should only be used for small and low I/O throughput
                # activities - VMs should never be installed on this.
                nfsexport = xenrt.NFSDirectory()
                server, path = nfsexport.getHostAndPath("")
            else:
                # Create an SR on an external NFS file server
                share = xenrt.ExternalNFSShare()
                nfs = share.getMount()
                r = re.search(r"([0-9\.]+):(\S+)", nfs)
                server = r.group(1)
                path = r.group(2)

        self.server = server
        self.path = path
        self._create("netfs",
                     "<host name='%s'/><dir path='%s'/>" % (server, path),
                     "")

    def check(self):
        _StorageRepository.checkCommon(self, "nfs")
        #cli = self.host.getCLIInstance()
        if self.host.pool:
            self.checkOnHost(self.host.pool.master)
            for slave in self.host.pool.slaves.values():
                self.checkOnHost(slave)
        else:
            self.checkOnHost(self.host)

    def checkOnHost(self, host):
        try:
            host.execdom0("test -d %s" % (self.getPath()))
        except:
            raise xenrt.XRTFailure("SR mountpoint %s "
                                   "does not exist" % (self.getPath()))

        nfs = string.split(host.execdom0("mount | grep \" %s \"" %
                                          (self.getPath())))[0]
        shouldbe = "%s:%s/%s" % (self.server, self.path, self.name)
        if nfs != shouldbe:
            raise xenrt.XRTFailure("Mounted path '%s' is not '%s'" %
                                   (nfs, shouldbe))
