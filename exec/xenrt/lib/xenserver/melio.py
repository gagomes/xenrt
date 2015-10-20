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
import json
import threading

__all__ = [
    "MelioHelper"
]
           

class MelioHelper(object):
    def __init__(self, hosts, iscsiHost=None):
        self.hosts = hosts
        for host in self.hosts:
            host.melioHelper = self
        self.lun = None
        self._scsiid = None
        self.guid = None
        self._iscsiHost = iscsiHost
        self.logNames = []
        # Get a checkout of the Melio Python library
        if not xenrt.TEC().lookup("MELIO_PYTHON_LOCAL_PATH", None):
            d = xenrt.TempDirectory()
            xenrt.util.command("cd %s && git clone %s melio-python" % (d.path(), xenrt.TEC().lookup("MELIO_PYTHON_REPO", "https://gitlab.citrite.net/xs-melio/python-melio-linux.git")))
            xenrt.util.command("cd %s/melio-python && git checkout %s" % (d.path(), xenrt.TEC().lookup("MELIO_PYTHON_BRANCH", "master")))
            xenrt.GEC().config.setVariable("MELIO_PYTHON_LOCAL_PATH", "%s/melio-python" % d.path())
            sys.path.append("%s/melio-python/lib" % d.path())
        xenrt.setupLogging("sanbolic")

        import sanbolic
        self._MelioClient = sanbolic.Client
        
    @property
    def iscsiHost(self):
        return self._iscsiHost or self.hosts[0]

    def getMelioClient(self, host):
        # Get an instance of the websockets library to the Melio UI
        logName="sanbolic-%s" % threading.currentThread().getName()
        if not logName in self.logNames:
            xenrt.setupLogging(logName, forceThisTEC=True)
            self.logNames.append(logName)
        return self._MelioClient("%s:8080" % host.getIP(), request_timeout=300, log_name=logName)

    def setup(self, reinstall=False, formatDisk=True):
        # Do a full setup of the melio tools
        tasks = [xenrt.PTask(self.installMelio, reinstall=reinstall)]
        if self.iscsiHost not in self.hosts:
            tasks.append(xenrt.PTask(self.createLun))
        xenrt.pfarm(tasks)
        self.setupISCSITarget()
        if formatDisk:
            self.setupMelioDisk()

    def getRpmToDom0(self, host, var, specVar, dest):
        # Get an RPM to dom0 from a URL
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
        # Install melio on the cluster (do each host in parallel)
        self.configureClusterFirewall()
        tasks = [xenrt.PTask(self.installMelioOnHost, x, reinstall) for x in self.hosts]
        xenrt.pfarm(tasks)
        self.checkCluster()
   

    def installMelioOnHost(self, host, reinstall=False):
        # Install the Melio software on a single host
        if host.execdom0("lsmod | grep warm_drive", retval="code") == 0 and not reinstall:
            return
        host.execdom0("yum install -y boost boost-atomic boost-thread boost-filesystem")
        if not self.getRpmToDom0(host, "MELIO_RPM", "melio_rpm", "/root/melio.rpm"):
            raise xenrt.XRTError("MELIO_RPM not found")
        host.execdom0("rpm -U --replacepkgs /root/melio.rpm")

        # Workaround for now - load the melio stuff after boot

        host.execdom0("sed -i /warm_drive/d /etc/rc.d/rc.local")
        host.execdom0("sed -i /warm-drive/d /etc/rc.d/rc.local")
        host.execdom0("sed -i /ping/d /etc/rc.d/rc.local")
        host.execdom0("echo 'ping -c 30 -i 0.1 -W 2 %s' >> /etc/rc.d/rc.local" % xenrt.TEC().lookup("XENRT_SERVER_ADDRESS"))
        host.execdom0("echo 'modprobe warm_drive' >> /etc/rc.d/rc.local")
        host.execdom0("chkconfig warm-drived off")
        host.execdom0("echo 'service warm-drived start' >> /etc/rc.d/rc.local")
        if host.execdom0("test -e /lib/systemd/system/warm-drive-webserverd.service", retval="code") == 0:
            host.execdom0("chkconfig warm-drive-webserverd off")
            host.execdom0("echo 'service warm-drive-webserverd start' >> /etc/rc.d/rc.local")
        host.reboot()
        self.checkXapiResponsive(host)
        if self.getRpmToDom0(host, "FFS_RPM", "ffs_rpm", "/root/ffs.rpm"):
            host.execdom0("rpm -i /root/ffs.rpm")
            # Workaround CA-180826
            # host.execdom0("""sed -i 's#urlparse.urlparse(sr)#urlparse.urlparse(sr.replace("file:///dev", "file:///run/sr-mount/dev") if check else sr)#' /usr/libexec/xapi-storage-script/volume/org.xen.xapi.storage.melio/common.py""")
            host.execdom0("service xapi-storage-script restart")

    def checkXapiResponsive(self, host):
        # Check that xapi is responsive on the specified host
        for i in xrange(20):
            start = xenrt.timenow()
            host.getCLIInstance().execute("vm-list")
            if xenrt.timenow() - start > 10:
                raise xenrt.XRTError("vm-list took > 10 seconds after installing melio")

    def createLun(self):
        if not self.lun:
            self.lun = xenrt.ISCSIVMLun(targetType="LIO", sizeMB=100*xenrt.KILO, host=self.iscsiHost)

    def setupISCSITarget(self):
        # Setup an LIO iscsi target
        self.createLun()
        self._scsiid = self.lun.getID()
        for host in self.hosts:
            host.execdom0("iscsiadm -m discovery -t st -p %s" % self.lun.getServer())
            host.execdom0('iscsiadm -m node --targetname "%s" --portal "%s:3260" --login' % (self.lun.getTargetName(), self.lun.getServer()))

    @property
    def device(self):
        return "/dev/disk/by-id/scsi-%s" % self._scsiid

    def rebootAndWait(self, host):
        host.reboot()
        host.execdom0("service iscsi restart")
        self.getSanDeviceForHost(host)
    
    def getSanDeviceForHost(self, host):
        with self.getMelioClient(host) as melioClient:
            deadline = xenrt.timenow() + 600
            while True:
                exportedDevice = melioClient.get_all()['exported_device']
                if isinstance(exportedDevice, dict):
                    if self.guid in exportedDevice.keys():
                        sanDevice = exportedDevice[self.guid]['system_name']
                        break
                    elif "_%s" % self.guid in exportedDevice.keys():
                        sanDevice = exportedDevice["_%s" % self.guid]['system_name']
                        break
                if xenrt.timenow() > deadline:
                    raise xenrt.XRTError("Timed out waiting for device to appear")
                xenrt.sleep(10)
        return sanDevice

    def setupMelioDisk(self):
        # Setup a melio disk on the scsi device
        disk = self.hosts[0].execdom0("realpath %s" % self.device).strip()[5:]
        with self.getMelioClient(self.hosts[0]) as melioClient:
            deadline = xenrt.timenow() + 600
            while True:
                data = melioClient.get_all()
                unmanaged = data.get('unmanaged_disk')
                xenrt.TEC().logverbose("Unmanaged disks: %s" % json.dumps(unmanaged, indent=2))
                if unmanaged:
                    disksToManage = [x for x in unmanaged if x['system_name'] == disk]
                else:
                    disksToManage = []
                if disksToManage:
                    diskToManage = disksToManage[0]
                    break
                if xenrt.timenow() > deadline:
                    raise xenrt.XRTError("Timed out waiting for disk to appear")
                xenrt.sleep(10)
            melioClient.manage_disk(diskToManage['system_name'])
            deadline = xenrt.timenow() + 600
            while True:
                managedDisks = melioClient.get_all()['managed_disk']
                guid = [x for x in managedDisks.keys() if managedDisks[x]['system_name'] == disk][0]
                if int(managedDisks[guid]['state']) == 2:
                    break
                if xenrt.timenow() > deadline:
                    raise xenrt.XRTError("Timed out waiting for disk to get to state 2")
                xenrt.sleep(10)
            self.guid = melioClient.create_volume(guid.lstrip("_"), managedDisks[guid]['free_space'])
        self.getSanDeviceForHost(self.hosts[0])
        tasks = [xenrt.PTask(self.rebootAndWait, x) for x in self.hosts[1:]]
        xenrt.pfarm(tasks)

    def mount(self, mountpoint):
        # Mount the melio device on every host in the cluster at the specified mountpoint
        for host in self.hosts:
            host.execdom0("mount -t warm_fs /dev/%s %s" % (self.getSanDeviceForHost(host), mountpoint))
    
    def checkMount(self, mountpoint):
        # Check that melioFS is mounted at the specified mountpoint on every host in the cluster
        for host in self.hosts:
            if not "on %s type warm_fs" % mountpoint in host.execdom0("mount"):
                raise xenrt.XRTError("warm_fs not mounted on %s" % host.getName())

    def createSR(self, name="Melio"):
        # Create the melio SR
        master = self.hosts[0].pool.master if self.hosts[0].pool else self.hosts[0]
        sr = xenrt.lib.xenserver.MelioStorageRepository(master, name)
        sr.create(self)
        sr.check()
        return sr

    def configureClusterFirewall(self):
        # Configure every host to be able to see every other host
        for applyHost in self.hosts:
            for ruleHost in self.hosts:
                if applyHost == ruleHost:
                    continue
                applyHost.execdom0("iptables -I RH-Firewall-1-INPUT -s %s -p udp --dport 8777 -j ACCEPT" % ruleHost.getIP())
            applyHost.execdom0("service iptables save")

    def checkCluster(self):
        # Check every host can see every other host in the cluster
        if len(self.hosts) == 1:
            return
        deadline = xenrt.timenow() + 600
        while True:
            ready = True
            for checkHost in self.hosts:
                with self.getMelioClient(checkHost) as melioClient:
                    # See which other servers we're connected to
                    servers = melioClient.get_all()['network_session']
                # We don't always get a dictionary back if it's empty
                if not isinstance(servers, dict):
                    ready = False
                else:
                    # Check we're connected to every other host (except ourselves)
                    for expectedHost in self.hosts:
                        if expectedHost == checkHost:
                            continue
                        if not expectedHost.getName() in [x['computer_name'] for x in servers.values()]:
                            ready = False
                            # No point in continuing
                            break
                if not ready:
                    # No point in continuing
                    break
            if ready:
                # All done
                break
            if xenrt.timenow() > deadline:
                raise xenrt.XRTError("Timed out waiting for all of the cluster to appear")
            # Sleep for 20 seconds before trying again
            xenrt.sleep(20)
