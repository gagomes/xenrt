#
# XenRT: Test harness for Xen and the XenServer product family
#
# Encapsulate an ESX SR.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import re, xml.dom.minidom
import xenrt

class StorageRepository(xenrt.lib.libvirt.StorageRepository):

    def getVDINameFromPath(self, vdipath):
        """Gets a VDI name from its path. Returns None if vdipath is invalid"""
        try:
            r = re.match(r"(?:\[%s\] )?(.*)" % (re.escape(self.name)), vdipath)
            return r.group(1)
        except:
            return None

    def getVDIPath(self, vdiname):
        return "[%s] %s" % (self.name, vdiname)

    def introduce(self):
        """Re-introduce the SR - it must have been created with this object previously

        libvirt does not support modifying SRs on ESX. We have to do it ourselves"""
        if not self.srxml:
            raise xenrt.XRTError("Cannot introduce SR because we don't have the SR's xml")

        xmldom = xml.dom.minidom.parseString(self.srxml)
        srtype = xmldom.getElementsByTagName("pool")[0].getAttribute("type")
        if srtype == "netfs":
            sourcedom = xmldom.getElementsByTagName("source")[0]
            hostname = sourcedom.getElementsByTagName("host")[0].getAttribute("name")
            path = sourcedom.getElementsByTagName("dir")[0].getAttribute("path")
            self.host.execdom0("esxcli storage nfs add --host %s --share %s --volume-name \"%s\"" % (hostname, path, self.name))
        else:
            raise xenrt.XRTError("SRs of type '%s' are not yet supported by ESX" % srtype)

        xmldom.unlink()
        xenrt.sleep(5)
        self.virPool = self.host.virConn.storagePoolLookupByName(self.name)
        self.uuid = self.virPool.UUIDString()

    def forget(self):
        """Forget this SR (but keep the details in this object)"""
        raise xenrt.XRTError("Forget is not yet supported by ESX")
        self.virPool.destroy()
        self.virPool.undefine()

    def destroy(self):
        """Destroy this SR (but keep the details in this object)"""
        raise xenrt.XRTError("Destroy is not yet supported by ESX")
        self.virPool.destroy()
        self.virPool.delete(0)
        self.virPool.undefine()
        self.isDestroyed = True

    def getVDIFormat(self, vdiname):
        # TODO
        return "vmdk"

    def randomVDIName(self, format):
        """Generates a random VDI name."""
        randname = xenrt.randomGuestName()
        return "%s/%s.%s" % (randname, randname, format)

    # Implement linked-clones using thin provisioning
    # e.g. srcvdiname='vm-template/vm-template.vmdk', destvdiname='localb-0/localb-0.vmdk'
    def cloneVDI(self, srcvdiname, destvdiname=None):
        if destvdiname is None:
            destvdiname = self.generateCloneName(srcvdiname, forcebranch=True)

        xenrt.TEC().logverbose("Thin-cloning '%s' to '%s'" % (srcvdiname, destvdiname))

        # Extract VM names and VDI names
        try:
            [srcvmname, srcvdi] = srcvdiname.split('/')
            srcvdistem = srcvdi.split('.')[0]
        except ValueError:
            raise ValueError("source VDI doesn't have expected format '<directory>/<file>'")

        try:
            [destvmname, destvdi] = destvdiname.split('/')
            destvdistem = destvdi.split('.')[0]
        except ValueError:
            raise ValueError("destination VDI doesn't have expected format '<directory>/<file>'")

        srcsrpath = "/vmfs/volumes/%s" % (self.name)
        destsrpath = srcsrpath # we assume the clone is going into the same datastore

        # Find out the domid of the VM to which this VDI belongs
        domid = self.host.execcmd("vim-cmd vmsvc/getallvms | grep '^[0-9]*\s\s*%s\s\s*' | awk '{print $1}'" % (srcvmname)).strip()

        # 0. Temporarily detach all the VM's other disks, so they aren't snapshotted
        # TODO

        # 1. If the disk is already a snapshot, use that. Otherwise, take a new snapshot and use that.
        if self.host.execcmd("fgrep parentFileNameHint= %s/%s" % (srcsrpath, srcvdiname), retval="code") == 0:
            xenrt.TEC().logverbose("disk %s/%s is already a snapshot so use it directly" % (srcsrpath, srcvdiname))
            # (note: if the VM was booted since taking the first snapshot, it won't be empty, so this won't be a true thin-clone)
            srcvmdkname  = "%s.vmdk"       % (srcvdistem)
            srcdeltaname = "%s-delta.vmdk" % (srcvdistem)
        else:
            xenrt.TEC().logverbose("disk %s/%s is not a snapshot so we need to snapshot it" % (srcsrpath, srcvdiname))
            self.host.execcmd("vim-cmd vmsvc/snapshot.create %s %s-snap1" % (domid, srcvmname))
            # TODO I don't know a reliable way of getting the VMDK file of a given snapshot, so we guess the filename
            srcvmdkname  = "%s-000001.vmdk"       % (srcvdistem)
            srcdeltaname = "%s-000001-delta.vmdk" % (srcvdistem)

        # 2. Copy the snapshot and make the parent path fully-qualified
        srcvmdk       = "%s/%s/%s"                   % (srcsrpath,  srcvmname,  srcvmdkname)
        srcdeltavmdk  = "%s/%s/%s"                   % (srcsrpath,  srcvmname,  srcdeltaname)
        destdeltaname = "%s-delta.vmdk"              % (destvdistem)
        destdir       = "%s/%s"                      % (destsrpath, destvmname)
        destvmdk      = "%s/%s/%s"                   % (destsrpath, destvmname, destvdi)
        destdeltavmdk = "%s/%s/%s"                   % (destsrpath, destvmname, destdeltaname)
        self.host.execcmd("mkdir -p %s" % (destdir))
        self.host.execcmd("cp %s %s" % (srcvmdk, destvmdk))
        self.host.execcmd("cp %s %s" % (srcdeltavmdk, destdeltavmdk))
        self.host.execcmd("sed -i 's!parentFileNameHint=\"!parentFileNameHint=\"%s/%s/!' %s" % (srcsrpath, srcvmname, destvmdk))
        self.host.execcmd("sed -i 's/%s/%s/' %s" % (srcdeltaname, destdeltaname, destvmdk))

        # 5. Re-attach all the VM's other disks
        # TODO

        return self.getVDIPath("%s/%s" % (destvmname, destvdi))

class ISOStorageRepository(xenrt.lib.libvirt.ISOStorageRepository, StorageRepository):
    pass

class EXTStorageRepository(xenrt.lib.libvirt.EXTStorageRepository, StorageRepository):
    pass

class NFSStorageRepository(xenrt.lib.libvirt.NFSStorageRepository, StorageRepository):
    pass
