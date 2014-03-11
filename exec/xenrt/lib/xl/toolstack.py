import xenrt, uuid, string

class XLToolstack(object):
    """An object to represent the xl toolstack and associated operations"""

    def __init__(self):
        self.hosts = [] # A list of known hosts
        self.residentOn = {} # A dictionary mapping running instances to their resident host
        self.suspendedInstances = []

    def startInstance(self, instance, on):
        host = self.hosts[0] # TODO: use on to identify the right host
        host.create(self.generateXLConfig(instance), instance.toolstackId)
        self.residentOn[instance.toolstackId] = host

    # TODO: in guest shutdown?
    def stopInstance(self, instance, force=False):
        hv = self.getHypervisor(instance)
        if not hv:
            raise xenrt.XRTError("Instance is not running")

        if force:
            hv.destroy(instance.name)
        else:
            hv.shutdown(instance.name)

        instance.poll(xenrt.STATE_DOWN)

    def rebootInstance(self, instance):
        hv = self.getHypervisor(instance)
        if not hv:
            raise xenrt.XRTError("Instance is not running")

        hv.reboot(instance.name)

    def suspendInstance(self, instance):
        if not self.getState(instance) == xenrt.STATE_UP:
            raise xenrt.XRTError("Cannot suspend a non running VM")

        # TODO: Parameterise where to store the suspend image
        img = "/data/%s-suspend" % (instance.toolstackId)
        hv = self.getHypervisor(instance)
        hv.save(instance.name, img)
        self.suspendedInstances.append(instance.toolstackId)
        del self.residentOn[instance.toolstackId]
                

    def resumeInstance(self, instance, on):
        if not self.getState(instance) == xenrt.STATE_SUSPENDED:
            raise xenrt.XRTError("Cannot resume a non suspended VM")

        img = "/data/%s-suspend" % (instance.toolstackId)
        host = self.hosts[0] # TODO: use on!
        host.restore(img)
        self.residentOn[instance.toolstackId] = host
        self.suspendedInstances.remove(instance.toolstackId)

    def migrateInstance(self, instance, to, live=True):
        if not isinstance(to, xenrt.lib.oss.OSSHost):
            raise xenrt.XRTError("xl can only migrate to OSSHost objects")

        if not live:
            raise xenrt.XRTError("xl only supports live migration")

        if not self.getState(instance) == xenrt.STATE_UP:
            raise xenrt.XRTError("Cannot migrate a non running VM")

        src = self.getHypervisor(instance)
        src.migrate(instance.name, to)
        self.residentOn[instance.toolstackId] = to

    def createInstance(self,
                       distro,
                       name,
                       vcpus,
                       memory,
                       vifs=None,
                       rootdisk=None,
                       extraConfig={},
                       startOn=None):
        instance = xenrt.lib.Instance(self, name, distro, vcpus, memory, extraConfig=extraConfig, vifs=vifs, rootdisk=rootdisk)
        instance.toolstackId = str(uuid.uuid4())

        if "PV" in instance.os.supportedInstallMethods:
            self._createInstancePV(instance, startOn)
        else:
            raise xenrt.XRTError("Specified instance does not have a supported install method")

        # TODO: tools?
        return instance

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
        # TODO: handle different storage locations
        host.execSSH("dd if=/dev/zero of=/data/%s-root bs=1M seek=%d count=0" % (uuid, instance.rootdisk / xenrt.MEGA))

        # Build an XL configuration
        xlcfg = self.generateXLConfig(instance, "/tmp/installers/%s/kernel" % (uuid), "/tmp/installers/%s/initrd" % (uuid), bootArgs)
        domid = host.create(xlcfg, uuid)
        self.residentOn[instance] = host
        host.updateConfig(domid, self.generateXLConfig(instance)) # Reset the boot config to normal for the reboot

        instance.os.waitForInstallCompleteAndFirstBoot()

    def getIP(self, instance, timeout=600, level=xenrt.RC_ERROR):
        if self.getState(instance) != xenrt.STATE_UP:
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

    def generateXLConfig(self, instance, kernel=None, initrd=None, args=None):
        # TODO: HVM!

        bootSpec = "bootloader = \"pygrub\""
        if kernel:
            bootSpec = "kernel = \"%s\"" % (kernel)
            if initrd:
                bootSpec += "\nramdisk = \"%s\"" % (initrd)

        if args is None:
            args = instance.os.pvBootArgs

        vifList = []
        # TODO: Sort the vif list to ensure we create these in the right order if > 1!
        for v in instance.vifs:
            vifList.append("'mac=%s'" % v[2])
        vifs = string.join(vifList, ",")
        # TODO: Handle additional disks
        disks = "'/data/%s-root,raw,xvda,rw'" % (instance.toolstackId)

        return """name = "%s"
uuid = "%s"
%s
extra = "%s"
memory = %d
vcpus = %d
vif = [ %s ]
disk = [ %s ]
""" % (instance.name, instance.toolstackId, bootSpec, string.join(args), instance.memory, instance.vcpus, vifs, disks)
       
    def getHypervisor(self, instance):
        """Returns the Hypervisor object the given instance is running on, or None if the instance is shutdown"""
        if not instance.toolstackId in self.residentOn.keys():
            return None
        return self.residentOn[instance.toolstackId]

    def getState(self, instance):
        if instance.toolstackId in self.suspendedInstances:
            return xenrt.STATE_SUSPENDED

        hv = self.getHypervisor(instance)
        if not hv:
            return xenrt.STATE_DOWN

        guests = hv.listGuestsData()
        if not instance.toolstackId in guests.keys():
            del self.residentOn[instance.toolstackId]
            return xenrt.STATE_DOWN

        gd = guests[instance.toolstackId]
        if gd[1] == "s":
            # Domain has actually shut down, so destroy it
            hv.destroy(gd[0])
            return xenrt.STATE_DOWN

        # TODO: handle paused / crashed etc
        return xenrt.STATE_UP

__all__ = ["XLToolstack"]
