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
        self.lun = None

    def setup(self):
        self.installMelio()
        self.setupISCSITarget()
        self.setupMelioDisk()

    def installMelio(self, reinstall=False):
        if self.host.execdom0("lsmod | grep warm_drive", retval="code") == 0 and not reinstall:
            return
        self.host.execdom0("yum install -y boost boost-atomic boost-thread boost-filesystem")
        f = xenrt.TEC().getFile(xenrt.TEC().lookup("MELIO_RPM"))
        d = xenrt.WebDirectory()
        d.copyIn(f)
        self.host.execdom0("wget -O /root/melio.rpm %s" % d.getURL(os.path.basename(f)))
        self.host.execdom0("rpm -U --replacepkgs /root/melio.rpm")

        # Workaround for now - load the melio stuff after boot

        self.host.execdom0("sed -i /warm_drive/d /etc/rc.d/rc.local")
        self.host.execdom0("sed -i /warm-drive/d /etc/rc.d/rc.local")
        self.host.execdom0("echo 'modprobe warm_drive' >> /etc/rc.d/rc.local")
        self.host.execdom0("chkconfig warm-drived off")
        self.host.execdom0("echo 'service warm-drived start' >> /etc/rc.d/rc.local")
        if self.host.execdom0("test -e /lib/systemd/system/warm-drive-webserverd.service", retval="code") == 0:
            self.host.execdom0("chkconfig warm-drive-webserverd off")
            self.host.execdom0("echo 'service warm-drive-webserverd start' >> /etc/rc.d/rc.local")
        self.host.reboot()

    def setupISCSITarget(self):
        self.lun = xenrt.ISCSIVMLun(targetType="LIO", sizeMB=100*xenrt.KILO)
        self.host.execdom0("iscsiadm -m discovery -t st -p %s" % self.lun.getServer())
        self.host.execdom0('iscsiadm -m node --targetname "%s" --portal "%s:3260" --login' % (self.lun.getTargetName(), self.lun.getServer()))

    @property
    def device(self):
        return "/dev/disk/by-id/scsi-%s" % self.lun.getID()

    def setupMelioDisk(self):
        self.host.execdom0("/usr/sbin/wd_format warm_fs mount_1234 %s" % self.device)

    def mount(self, mountpoint):
        self.host.execdom0("mount -t warm_fs %s %s" % (self.device, mountpoint))
    

