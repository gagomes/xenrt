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

class ISOStorageRepository(xenrt.lib.libvirt.ISOStorageRepository, StorageRepository):
    pass

class EXTStorageRepository(xenrt.lib.libvirt.EXTStorageRepository, StorageRepository):
    pass

class NFSStorageRepository(xenrt.lib.libvirt.NFSStorageRepository, StorageRepository):
    pass
