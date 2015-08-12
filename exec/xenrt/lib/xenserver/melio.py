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
import requests

__all__ = [
    "MelioHelper"
]
           

class MelioHelper(object):
    def __init__(self, host):
        self.host = host
        self.lun = None

    def setup(self):
        self.installMelio()
        self.setupISCSITarget()
        self.setupMelioDisk()

    def getRpmToDom0(self, var, specVar, dest):
        rpm = xenrt.TEC().lookup(var, None)
        if not rpm:
            return False
        if rpm.endswith(".rpm"):
            f = xenrt.TEC().getFile(rpm)
        else:
            spec = requests.get(xenrt.filemanager.FileNameResolver(rpm).url).json()
            f = xenrt.TEC().getFile(spec[specVar])
        if not f:
            return False
        d = xenrt.WebDirectory()
        d.copyIn(f)
        self.host.execdom0("wget -O %s %s" % (dest, d.getURL(os.path.basename(f))))
        return True

    def installMelio(self, reinstall=False):
            
        if self.host.execdom0("lsmod | grep warm_drive", retval="code") == 0 and not reinstall:
            return
        d = xenrt.WebDirectory()
        if xenrt.TEC().lookup("PATCH_SMAPI_RPMS", False, boolean=True):
            self.host.execdom0("mkdir -p /root/smapi_rpms")
            rpms = ['xapi-core-*.rpm', 'xapi-storage-script-*.rpm', 'xenopsd-0*.rpm', 'xenopsd-xc-*.rpm', 'xenopsd-xenlight-*.rpm']
            for r in rpms:
                f = xenrt.TEC().getFile("/usr/groups/xen/carbon/trunk-btrfs-3/latest/binary-packages/RPMS/domain0/RPMS/x86_64/%s" % r)
                d.copyIn(f)
                self.host.execdom0("wget -O /root/smapi_rpms/%s %s" % (os.path.basename(f), d.getURL(os.path.basename(f))))
            self.host.execdom0("rpm -Uv --force /root/smapi_rpms/*.rpm")
            self.host.resetToFreshInstall(setupISOs=True)
        self.host.execdom0("yum install -y boost boost-atomic boost-thread boost-filesystem")
        if not self.getRpmToDom0("MELIO_RPM", "melio_rpm", "/root/melio.rpm"):
            raise xenrt.XRTError("MELIO_RPM not found")
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
        self.checkXapiResponsive()
        if self.getRpmToDom0("FFS_RPM", "ffs_rpm", "/root/ffs.rpm"):
            # RPM workaround for now
            self.host.execdom0("rm -rf /usr/libexec/xapi-storage-script/datapath/raw+file*")
            self.host.execdom0("rpm -U --replacepkgs /root/ffs.rpm")

    def checkXapiResponsive(self):
        for i in xrange(20):
            start = xenrt.timenow()
            self.host.getCLIInstance().execute("vm-list")
            if xenrt.timenow() - start > 10:
                raise xenrt.XRTError("vm-list took > 10 seconds after installing melio")

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
    

