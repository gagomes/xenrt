import xenrt, uuid, string
from zope.interface import implements

class XLToolstack(object):
    """An object to represent the xl toolstack and associated operations"""
    implements(xenrt.interfaces.Toolstack)

    def __init__(self):
        self.hosts = [] # A list of known hosts
        self.residentOn = {} # A dictionary mapping running instances to their resident host
        self.suspendedInstances = []

    @property
    def name(self):
        return "XL"

    def getAllExistingInstances(self):
        raise xenrt.XRTError("Not implemented")

    def instanceHypervisorType(self, instance):
        # XL only works with Xen, so we will always be returning Xen
        return xenrt.HypervisorType.xen

    def instanceCanMigrateTo(self, instance):
        raise xenrt.XRTError("Not implemented")

    def instanceResidentOn(self, instance):
        raise xenrt.XRTError("Not implemented")

    def instanceSupportedLifecycleOperations(self, instance):
        ops = [xenrt.LifecycleOperation.start,
               xenrt.LifecycleOperation.stop,
               xenrt.LifecycleOperation.reboot,
               xenrt.LifecycleOperation.livemigrate,
               xenrt.LifecycleOperation.suspend,
               xenrt.LifecycleOperation.resume]

    def startInstance(self, instance, on):
        host = self.hosts[0] # TODO: use on to identify the right host
        host.createInstance(self.generateXLConfig(instance), instance.toolstackId)
        self.residentOn[instance.toolstackId] = host

    # TODO: in guest shutdown?
    def stopInstance(self, instance, force=False):
        hv = self.getHypervisor(instance)
        if not hv:
            raise xenrt.XRTError("Instance is not running")

        if force:
            hv.destroyInstance(instance.name)
        else:
            hv.shutdownInstance(instance.name)

        instance._osParent_pollPowerState(xenrt.PowerState.down)

    def existingInstance(self, name):
        raise xenrt.XRTError("Not implemented")

    def rebootInstance(self, instance, force=False):
        hv = self.getHypervisor(instance)
        if not hv:
            raise xenrt.XRTError("Instance is not running")

        hv.rebootInstance(instance.name)

    def suspendInstance(self, instance):
        if not self.getInstancePowerState(instance) == xenrt.PowerState.up:
            raise xenrt.XRTError("Cannot suspend a non running VM")

        # TODO: Parameterise where to store the suspend image
        img = "/data/%s-suspend" % (instance.toolstackId)
        hv = self.getHypervisor(instance)
        hv.saveInstance(instance.name, img)
        self.suspendedInstances.append(instance.toolstackId)
        del self.residentOn[instance.toolstackId]
                

    def resumeInstance(self, instance, on):
        if not self.getInstancePowerState(instance) == xenrt.PowerState.suspended:
            raise xenrt.XRTError("Cannot resume a non suspended VM")

        img = "/data/%s-suspend" % (instance.toolstackId)
        host = self.hosts[0] # TODO: use on!
        host.restoreInstance(img)
        self.residentOn[instance.toolstackId] = host
        self.suspendedInstances.remove(instance.toolstackId)

    def migrateInstance(self, instance, to, live=True):
        if not isinstance(to, xenrt.lib.oss.OSSHost):
            raise xenrt.XRTError("xl can only migrate to OSSHost objects")

        if not live:
            raise xenrt.XRTError("xl only supports live migration")

        if not self.getInstancePowerState(instance) == xenrt.PowerState.up:
            raise xenrt.XRTError("Cannot migrate a non running VM")

        src = self.getHypervisor(instance)
        src.migrateInstance(instance.name, to)
        self.residentOn[instance.toolstackId] = to

    def destroyInstance(self, instance):
        raise xenrt.XRTError("Not implemented")

    def createOSTemplate(self,
                         distro,
                         rootdisk=None,
                         installTools=True,
                         useTemplateIfAvailable=True,
                         hypervisorType=None):
        raise xenrt.XRTError("Not implemented")

    def createInstance(self,
                       distro,
                       name,
                       vcpus,
                       memory,
                       vifs=None,
                       rootdisk=None,
                       extraConfig={},
                       startOn=None,
                       installTools=True,
                       useTemplateIfAvailable=True,
                       hypervisorType=xenrt.HypervisorType.xen,
                       start=True):

        if hypervisorType != xenrt.HypervisorType.xen:
            raise xenrt.XRTError("XL only supports the Xen hypervisor")

        instance = xenrt.lib.Instance(self, name, distro, vcpus, memory, extraConfig=extraConfig, vifs=vifs, rootdisk=rootdisk)
        instance.toolstackId = str(uuid.uuid4())

        if xenrt.InstallMethod.PV in instance.os.supportedInstallMethods:
            self._createInstancePV(instance, startOn)
        elif xenrt.InstallMethod.Iso in instance.os.supportedInstallMethods:
            self._createInstanceISO(instance, startOn)
        else:
            raise xenrt.XRTError("Specified instance does not have a supported install method")

        if not start:
            instance.stop()

        # TODO: tools?
        return instance

    def _createDisk(self,
                    instance,
                    name,
                    size,
                    host):
        # TODO: handle different storage locations
        host.execSSH("dd if=/dev/zero of=/data/%s-%s bs=1M seek=%d count=0" % (instance.toolstackId, name, size / xenrt.MEGA))

    def _createInstancePV(self,
                          instance,
                          startOn):

        kernel, initrd = instance.os.installerKernelAndInitRD
        webdir = xenrt.WebDirectory()
        bootArgs = instance.os.generateAnswerfile(webdir)
        host = self.hosts[0] # TODO: Use startOn
        uuid = instance.toolstackId

        # Copy the kernel and initrd to the host
        host.execSSH("mkdir -p /tmp/installers/%s" % (uuid))
        host.execSSH("wget -O /tmp/installers/%s/kernel %s" % (uuid, kernel))
        host.execSSH("wget -O /tmp/installers/%s/initrd %s" % (uuid, initrd))

        # Create rootdisk
        self._createDisk(instance, "root", instance.rootdisk, host)

        # Build an XL configuration
        xlcfg = self.generateXLConfig(instance, kernel="/tmp/installers/%s/kernel" % (uuid), initrd="/tmp/installers/%s/initrd" % (uuid), args=bootArgs)
        domid = host.createInstance(xlcfg, uuid)
        self.residentOn[instance.toolstackId] = host
        host.updateConfig(domid, self.generateXLConfig(instance)) # Reset the boot config to normal for the reboot

        instance.os.waitForInstallCompleteAndFirstBoot()

    def _createInstanceISO(self,
                           instance,
                           startOn):
        """Perform an HVM ISO installation"""

        # We assume all ISOs used for HVM installation are in the primary ISO repository
        iso = "/mnt/isos/%s" % instance.os.isoName
        host = self.hosts[0] # TODO: Use startOn
        uuid = instance.toolstackId

        # Check the ISO exists
        if host.execSSH("ls %s" % (iso), retval="code") != 0:
            raise xenrt.XRTError("Cannot find %s to create instance" % (instance.os.isoName))

        # Create rootdisk
        self._createDisk(instance, "root", instance.rootdisk, host)

        # Build an XL configuration
        xlcfg = self.generateXLConfig(instance, hvm=True, iso=iso)
        domid = host.createInstance(xlcfg, uuid)
        self.residentOn[instance.toolstackId] = host

        instance.os.waitForInstallCompleteAndFirstBoot()

    def getInstanceIP(self, instance, timeout=600, level=xenrt.RC_ERROR):
        if self.getInstancePowerState(instance) != xenrt.PowerState.up:
            raise xenrt.XRTError("Instance not running")

        if instance.mainip is not None:
            return instance.mainip

        # If we haven't got an IP, use arpwatch to try and find one
        # TODO: Find the mac in a 'cleaner' way
        mac = instance.vifs[0][2]
        ip = self.getHypervisor(instance).arpwatch("xenbr0", mac, timeout)
        if not ip:
            raise xenrt.XRT("Timed out monitoring for guest ARP/DHCP", level, data=mac)
        instance.mainip = ip
        return ip

    def generateXLConfig(self, instance, hvm=False, kernel=None, initrd=None, args=None, iso=None):
        bootSpec = ""
        if hvm:
            bootSpec = "builder = \"hvm\""
        else:
            bootSpec = "bootloader = \"pygrub\""
            if kernel:
                bootSpec = "kernel = \"%s\"" % (kernel)
                if initrd:
                    bootSpec += "\nramdisk = \"%s\"" % (initrd)
            if args is None:
                args = instance.os.pvBootArgs

        if args is None:
            args = []

        vifList = []
        # TODO: Sort the vif list to ensure we create these in the right order if > 1!
        for v in instance.vifs:
            vifList.append("'mac=%s'" % v[2])
        vifs = string.join(vifList, ",")
        # TODO: Handle additional disks
        disks = "'/data/%s-root,raw,xvda,rw'" % (instance.toolstackId)
        if iso:
            disks += ",'%s,,hdd,cdrom'" % (iso)

        hvmData = ""
        if hvm:
            hvmData = "boot = \"dc\"\nvnc = 1\nusb = 1\nusbdevice = ['tablet']"
            if instance.os.viridian:
                hvmData += "\nviridian = 1"

        return """name = "%s"
uuid = "%s"
%s
extra = "%s"
memory = %d
vcpus = %d
vif = [ %s ]
disk = [ %s ]
%s
""" % (instance.name, instance.toolstackId, bootSpec, string.join(args), instance.memory, instance.vcpus, vifs, disks, hvmData)
       
    def getHypervisor(self, instance):
        """Returns the Hypervisor object the given instance is running on, or None if the instance is shutdown"""
        if not instance.toolstackId in self.residentOn.keys():
            return None
        return self.residentOn[instance.toolstackId]

    def getInstancePowerState(self, instance):
        if instance.toolstackId in self.suspendedInstances:
            return xenrt.PowerState.suspended

        hv = self.getHypervisor(instance)
        if not hv:
            return xenrt.PowerState.down

        guests = hv.listGuests()
        if not instance.toolstackId in guests:
            del self.residentOn[instance.toolstackId]
            return xenrt.PowerState.down

        # TODO: handle paused / crashed etc
        return xenrt.PowerState.up

    def setInstanceIso(self, instance, isoName, isoRepo):
        raise xenrt.XRTError("Not implemented")
    
    def ejectInstanceIso(self, instance):
        raise xenrt.XRTError("Not implemented")

    def createInstanceSnapshot(self, instance, name, memory=False, quiesce=False):
        raise xenrt.XRTError("Not implemented")

    def deleteInstanceSnapshot(self, instance, name):
        raise xenrt.XRTError("Not implemented")

    def revertInstanceToSnapshot(self, instance, name):
        raise xenrt.XRTError("Not implemented")

    def instanceScreenshot(self, instance, path):
        raise xenrt.XRTError("Not implemented")

    def getLogs(self, path):
        return

    def discoverInstanceAdvancedNetworking(self, instance):
        # We don't do any advanced networking, so just return
        return

__all__ = ["XLToolstack"]
