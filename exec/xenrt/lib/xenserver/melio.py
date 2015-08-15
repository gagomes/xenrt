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
import sys

__all__ = [
    "MelioHelper"
]
           

class MelioHelper(object):
    def __init__(self, hosts, iscsiHost=None):
        self.hosts = hosts
        for host in self.hosts:
            host.melioHelper = self
        self.lun = None
        self._iscsiHost = iscsiHost
        if not xenrt.TEC().lookup("MELIO_PYTHON_LOCAL_PATH", None):
            d = xenrt.TempDirectory()
            xenrt.util.command("cd %s && git clone %s melio-python" % (d.path(), xenrt.TEC().lookup("MELIO_PYTHON_REPO", "https://gitlab.citrite.net/xs-melio/python-melio-linux.git")))
            xenrt.util.command("cd %s/melio-python && git checkout %s" % (d.path(), xenrt.TEC().lookup("MELIO_PYTHON_BRANCH", "master")))
            xenrt.GEC().config.setVariable("MELIO_PYTHON_LOCAL_PATH", "%s/melio-python" % d.path())
            sys.path.append("%s/melio-python/lib" % d.path())
        import sanbolic
        self.MelioClient = sanbolic.Client
        
    @property
    def iscsiHost(self):
        return self._iscsiHost or self.hosts[0]

    def setup(self, reinstall=False):
        tasks = [xenrt.PTask(self.installMelio, reinstall=reinstall)]
        if self.iscsiHost not in self.hosts:
            tasks.append(xenrt.PTask(self.createLun))
        xenrt.pfarm(tasks)
        self.setupISCSITarget()
        self.setupMelioDisk()

    def getRpmToDom0(self, host, var, specVar, dest):
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
        host.execdom0("wget -O %s %s" % (dest, d.getURL(os.path.basename(f))))
        return True

    def installMelio(self, reinstall=False):
        tasks = [xenrt.PTask(self.installMelioOnHost, x, reinstall) for x in self.hosts]
        xenrt.pfarm(tasks)
    
    def installMelioOnHost(self, host, reinstall=False):
        if host.execdom0("lsmod | grep warm_drive", retval="code") == 0 and not reinstall:
            return
        d = xenrt.WebDirectory()
        if xenrt.TEC().lookup("PATCH_SMAPI_RPMS", False, boolean=True):
            host.execdom0("mkdir -p /root/smapi_rpms")
            rpms = ['xapi-core-*.rpm', 'xapi-storage-script-*.rpm', 'xenopsd-0*.rpm', 'xenopsd-xc-*.rpm', 'xenopsd-xenlight-*.rpm', 'xapi-storage-0*.rpm']
            for r in rpms:
                f = xenrt.TEC().getFile("/usr/groups/xen/carbon/trunk-btrfs-3/latest/binary-packages/RPMS/domain0/RPMS/x86_64/%s" % r)
                d.copyIn(f)
                host.execdom0("wget -O /root/smapi_rpms/%s %s" % (os.path.basename(f), d.getURL(os.path.basename(f))))
            host.execdom0("rpm -Uv --force /root/smapi_rpms/*.rpm")
            host.resetToFreshInstall(setupISOs=True)
        host.execdom0("yum install -y boost boost-atomic boost-thread boost-filesystem")
        if not self.getRpmToDom0(host, "MELIO_RPM", "melio_rpm", "/root/melio.rpm"):
            raise xenrt.XRTError("MELIO_RPM not found")
        host.execdom0("rpm -U --replacepkgs /root/melio.rpm")

        # Workaround for now - load the melio stuff after boot

        host.execdom0("sed -i /warm_drive/d /etc/rc.d/rc.local")
        host.execdom0("sed -i /warm-drive/d /etc/rc.d/rc.local")
        host.execdom0("echo 'modprobe warm_drive' >> /etc/rc.d/rc.local")
        host.execdom0("chkconfig warm-drived off")
        host.execdom0("echo 'service warm-drived start' >> /etc/rc.d/rc.local")
        if host.execdom0("test -e /lib/systemd/system/warm-drive-webserverd.service", retval="code") == 0:
            host.execdom0("chkconfig warm-drive-webserverd off")
            host.execdom0("echo 'service warm-drive-webserverd start' >> /etc/rc.d/rc.local")
        host.reboot()
        self.checkXapiResponsive(host)
        if self.getRpmToDom0(host, "FFS_RPM", "ffs_rpm", "/root/ffs.rpm"):
            # RPM workaround for now
            host.execdom0("rm -rf /usr/libexec/xapi-storage-script/datapath/raw+file*")
            host.execdom0("rpm -U --replacepkgs /root/ffs.rpm")

    def checkXapiResponsive(self, host):
        for i in xrange(20):
            start = xenrt.timenow()
            host.getCLIInstance().execute("vm-list")
            if xenrt.timenow() - start > 10:
                raise xenrt.XRTError("vm-list took > 10 seconds after installing melio")

    def createLun(self):
        if not self.lun:
            self.lun = xenrt.ISCSIVMLun(targetType="LIO", sizeMB=100*xenrt.KILO, host=self.iscsiHost)

    def setupISCSITarget(self):
        self.createLun()
        for host in self.hosts:
            host.execdom0("iscsiadm -m discovery -t st -p %s" % self.lun.getServer())
            host.execdom0('iscsiadm -m node --targetname "%s" --portal "%s:3260" --login' % (self.lun.getTargetName(), self.lun.getServer()))

    @property
    def device(self):
        return "/dev/disk/by-id/scsi-%s" % self.lun.getID()

    def setupMelioDisk(self):
        self.hosts[0].execdom0("/usr/sbin/wd_format warm_fs mount_1234 %s" % self.device)

    def mount(self, mountpoint):
        for host in self.hosts:
            host.execdom0("mount -t warm_fs %s %s" % (self.device, mountpoint))
    
    def checkMount(self, mountpoint):
        for host in self.hosts:
            if not "on %s type warm_fs" % mountpoint in host.execdom0("mount"):
                raise xenrt.XRTError("warm_fs not mounted on %s" % host.getName())

    def createSR(self, name="Melio"):
        master = self.hosts[0].pool.master if self.hosts[0].pool else self.hosts[0]
        sr = xenrt.lib.xenserver.MelioStorageRepository(master, name)
        sr.create(self)
        return sr
