#
# XenRT: Test harness for Xen and the XenServer product family
#
# Operations on KVM guests.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import xenrt
import libvirt
import thread

createVM = xenrt.lib.libvirt.createVM

virt_install_lock = thread.allocate_lock()

class KVMGuest(xenrt.lib.libvirt.Guest):
    DEFAULT = -10
    DEFAULT_DISK_FORMAT = "raw"

    def __init__(self, *args, **kwargs):
        xenrt.lib.libvirt.Guest.__init__(self, *args, **kwargs)

    def _getDiskDevicePrefix(self):
        if self.enlightenedDrivers:
            return "vd"
        return "hd"
    def _getDiskDeviceBus(self):
        if self.enlightenedDrivers:
            return "virtio"
        return "ide"
    def _getNetworkDeviceModel(self):
        if self.enlightenedDrivers:
            return "virtio"
        return None # use default

    def _detectDistro(self):
        xenrt.lib.libvirt.Guest._detectDistro(self)
        if not self.windows:
            # assume Linux OS with kernel >= 2.6.25, which has virtio PV drivers
            self.enlightenedDrivers = True

    def _preInstall(self):
        if not self.windows:
            # assume Linux OS with kernel >= 2.6.25, which has virtio PV drivers
            self.enlightenedDrivers = True

    def _createVBD(self, sruuid, vdiname, format, userdevice, controllerType='ide', controllerModel=None):
        if not controllerType:
            controllerType = self._getDiskDeviceBus()

        if userdevice is None:
            userdevicename = self._getNextBlockDevice(controllerType=controllerType)
        else:
            userdevicename = self._getDiskDevicePrefix() +chr(int(userdevice)+self._baseDeviceForBus())

        # Currently, address is ignored
        srobj = self.host.srs[self.host.getSRName(sruuid)]
        vbdxmlstr = """
        <disk type='file' device='disk'>
            <driver name='qemu' type='%s' cache='none'/>
            <source file='%s'/>
            <target dev='%s' bus='%s'/>
        </disk>""" % (format, srobj.getVDIPath(vdiname), userdevicename, controllerType)
        self._attachDevice(vbdxmlstr, hotplug=True)

    def createGuestFromTemplate(self,
                                template,
                                sruuid,
                                ni=False,
                                db=True,
                                guestparams=[],
                                rootdisk=None):
        if self.memory is None:
            self.memory = 512
        if self.vcpus is None:
            self.vcpus = 1
        if rootdisk in [None, xenrt.lib.libvirt.Guest.DEFAULT]:
            rootdisk = 16*xenrt.GIGA

        # create VM definition from template
        # virt-install has some in-built "templates" -- as close as we can get with libvirt
        args = []
        args.append("--os-variant %s" % template)
        args.append("--name %s" % self.name)
        args.append("--vcpus %d" % self.vcpus)
        args.append("--ram %d" % self.memory)
        args.append("--nodisks")
        args.append("--nonetworks")
        args.append("--graphics vnc,listen=0.0.0.0")
        args.append("--force --boot hd --noreboot")

        virt_install_lock.acquire()

        #critical section: virt-install uses ~/.virtinst exclusively, which creates problems if vms are installed concurrently
        self.host.execvirt("virt-install %s" % (' '.join(args)))

        self.virDomain = self.virConn.lookupByName(self.name)

        # create disks
        # FIXME: hard-coded
        vdiname = "%s.%s" % (self.name, self.DEFAULT_DISK_FORMAT)
        self.createDisk(rootdisk, sruuid, name=vdiname, format=self.DEFAULT_DISK_FORMAT)

        virt_install_lock.release()
