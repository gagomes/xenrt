import xenrt, uuid, string

class XLToolstack(object):
    """An object to represent the xl toolstack and associated operations"""

    def __init__(self):
        self.hosts = [] # A list of known hosts
        self.residentOn = {} # A dictionary mapping running instances to their resident host
        self.instanceUUIDs = {} # A dictionary mapping running instances to their uuids

    def startInstance(self, instance, on):
        host = self.hosts[0] # TODO: use on to identify the right host
        host.create(self.generateXLConfig(instance), self.instanceUUIDs[instance])
        self.residentOn[instance] = host

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
        self.instanceUUIDs[instance] = str(uuid.uuid4())

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
        uuid = self.instanceUUIDs[instance]

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
        disks = "'/data/%s-root,raw,xvda,rw'" % (self.instanceUUIDs[instance])

        return """name = "%s"
uuid = "%s"
%s
extra = "%s"
memory = %d
vcpus = %d
vif = [ %s ]
disk = [ %s ]
""" % (instance.name, self.instanceUUIDs[instance], bootSpec, string.join(args), instance.memory, instance.vcpus, vifs, disks)
       
    def getHypervisor(self, instance):
        """Returns the Hypervisor object the given instance is running on, or None if the instance is shutdown"""
        if not instance in self.residentOn.keys():
            return None
        return self.residentOn[instance]

    def getState(self, instance):
        hv = self.getHypervisor(instance)
        if not hv:
            return xenrt.STATE_DOWN

        guests = hv.listGuestsData()
        if not self.instanceUUIDs[instance] in guests.keys():
            del self.residentOn[instance]
            return xenrt.STATE_DOWN

        gd = guests[self.instanceUUIDs[instance]]
        if gd[1] == "s":
            # Domain has actually shut down, so destroy it
            hv.destroy(gd[0])
            return xenrt.STATE_DOWN

        # TODO: handle paused / crashed etc
        return xenrt.STATE_UP

__all__ = ["XLToolstack"]
