#
# XenRT: Test harness for Xen and the XenServer product family
#
# Encapsulate a XenServer melio setup.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import xenrt
import os.path

__all__ = [
    "MelioHost"
]
           

class MelioHost(object):
    def __init__(self, host):
        self.host = host

    def installMelio(self):
        self.host.execdom0("yum install -y boost")
        f = xenrt.TEC().getFile(xenrt.TEC().lookup("MELIO_RPM"))
        d = xenrt.WebDirectory()
        d.copyIn(f)
        self.host.execdom0("wget -O /root/melio.rpm %s" % d.getURL(os.path.basename(f)))
        self.host.execdom0("rpm -U /root/melio.rpm")
        self.host.execdom0("modprobe warm_drive")

    def setupMelioDisk(self):
        lun = xenrt.ISCSIVMLun(targetType="LIO", sizeMB=100*xenrt.KILO)
        self.host.execdom0("iscsiadm -m discovery -t st -p %s" % lun.getServer())
        self.host.execdom0('iscsiadm -m node --targetname "%s" --portal "%s:3260" --login' % (lun.getTargetName(), lun.getServer()))
        disk = "/dev/disk/by-id/scsi-%s" % lun.getID()

        self.host.execdom0("/usr/sbin/wd_format warm_fs mount_1234 %s" % disk)
        self.host.execdom0("mount -t warm_fs %s /mnt" % disk)
