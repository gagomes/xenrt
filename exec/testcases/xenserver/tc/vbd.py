#
# XenRT: Test harness for Xen and the XenServer product family
#
# Testcases for import/export features
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and conditions
# as licensed by Citrix Systems, Inc. All other rights reserved.
#

import re, traceback, sys, string
import xenrt
from xenrt.lazylog import log

class _VBDPlug(xenrt.TestCase):
    DISTRO = None

    def __init__(self, tcid=None):
        self.guest = None
        self.host = None
        self.disksize = 100*1024*1024
        xenrt.TestCase.__init__(self, tcid)

    def run(self, arglist=None):
        self.host = self.getHost("RESOURCE_HOST_0")
        if not self.host:
            raise xenrt.XRTError("Couldn't find host object.")
        self.guest = self.installGuest()
        self.guest.shutdown()
        device = self.guest.createDisk(self.disksize)
        self.guest.start()
        guestdevice = self.makeFS(device)
        self.guest.unplugDisk(device)
        if self.checkDisk(guestdevice):
            raise xenrt.XRTFailure("Disk is still there after unplugging.")
        self.guest.reboot()
        if not self.checkDisk(guestdevice):
            raise xenrt.XRTFailure("Disk isn't there after plugging.")
        self.guest.reboot()
        self.guest.unplugDisk(device)
        if self.checkDisk(guestdevice):
            raise xenrt.XRTFailure("Disk is still there after unplugging.")

    def makeFS(self, disk):
        raise xenrt.XRTError("Unimplemented")

    def checkDisk(self, disk):
        raise xenrt.XRTError("Unimplemented")

    def installGuest(self):
        if self.DISTRO:
            vifs = [("0", 
                     self.host.getPrimaryBridge(), 
                     xenrt.randomMAC(), 
                     None)]
            g = xenrt.lib.xenserver.guest.createVM(self.host,
                                                   xenrt.randomGuestName(),
                                                   self.DISTRO,
                                                   vifs=vifs)
        else:
            g = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(g)
        if g.windows:
            g.installDrivers()
        return g

class _VBDPlugWindows(_VBDPlug):

    def makeFS(self, disk):
        disks = self.guest.xmlrpcListDisks()
        rootdisk = self.guest.xmlrpcGetRootDisk()
        xenrt.TEC().logverbose("VM disks: %s" % (string.join(disks)))
        xenrt.TEC().logverbose("VM root disk: %s" % (rootdisk))
        secdisks = [ x for x in disks if not x == rootdisk ][0]
        if len(secdisks) == 0:
            cli = self.guest.host.getCLIInstance()
            cli.execute("vm-disk-list", "uuid=%s" % (self.guest.getUUID()))
            raise xenrt.XRTError("No non-root disk found in VM")
        newdisk = secdisks[0]
        letter = self.guest.xmlrpcPartition(newdisk)
        self.guest.xmlrpcFormat(letter)
        return letter

    def checkDisk(self, disk):
        data = self.guest.xmlrpcExec("echo select volume %s | diskpart" % (disk),
                                      returndata=True)
        if re.search("The volume you selected is not valid or does not exist.", data):
            return False
        else:
            return True

class _VBDPlugLinux(_VBDPlug):

    def makeFS(self, disk):
        device = self.host.parseListForParam("vbd-list",
                                              self.guest.getDiskVBDUUID(disk),
                                             "device") 
        self.guest.execguest("mkfs.ext2 /dev/%s" % (device))
        return device

    def checkDisk(self, disk):
        try:
            self.guest.execguest("mount /dev/%s /mnt" % (disk))
            self.guest.execguest("umount /dev/%s" % (disk))
            return True
        except:
            return False

class TC6940(_VBDPlugWindows):
    """Hot unplug of a VBD that the Windows VM had attached when it was booted."""
    DISTRO="w2k3eesp2"

class TC6949(_VBDPlugLinux):
    """Hot unplug of a VBD that the Linux VM had attached when it was booted."""
    pass

class TC27127(xenrt.TestCase):

    def run(self,arglist):
        host = self.getDefaultHost()
        guest = host.getGuest("winguest2")
        try:
            guest.createDisk("1073741824", sruuid=host.getLocalSR(), plug=True, mode="RO")
        except Exception, ex:
            if "All VBDs of type 'disk' must be read/write for HVM guests" in str(ex):
                log("Read only disk failed to attach to the Windows machine")
            else:
                raise
        else:
            raise xenrt.XRTFailure("Read only disk attached to Windows successfully")
