#
# XenRT: Test harness for Xen and the XenServer product family
#
# Encapsulate a libvirt SR.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import re, os, urllib
import xenrt

class StorageRepository(xenrt.lib.libvirt.StorageRepository):

    def getVDINameFromPath(self, vdipath):
        """Gets a VDI name from its path. Returns None if vdipath is invalid"""
        try:
            r = re.match(r"%s/(.*)" % (re.escape(self.getPath())), vdipath)
            return urllib.unquote(r.group(1))
        except:
            return None

    def getVDIPath(self, vdiname):
        return os.path.join(self.getPath(), urllib.quote(vdiname))

    def getVDIFormat(self, vdiname):
        reply = self.host.execdom0("qemu-img info %s | grep 'file format'" % self.getVDIPath(vdiname))
        r = re.match(r"file format: (.*)", reply)
        if r:
            return r.group(1)
        return "raw"

class ISOStorageRepository(xenrt.lib.libvirt.ISOStorageRepository, StorageRepository):
    pass

class EXTStorageRepository(xenrt.lib.libvirt.EXTStorageRepository, StorageRepository):
    pass

class NFSStorageRepository(xenrt.lib.libvirt.NFSStorageRepository, StorageRepository):
    pass
