import xenrt
from zope.interface import implements

__all__=["GuestWrapper"]

class GuestWrapper(object):
    """An object to wrap a guest in order to be able to use an "Instance" object"""

    implements(xenrt.interfaces.Toolstack)

    def __init__(self, guest):
        self.guest = guest

    @property
    def name(self):
        return "wraper-%s" % self.guest.name
    
    def getAllExistingInstances(self):
        raise xenrt.XRTError("Not implemented")

    def instanceHypervisorType(self, instance):
        if isinstance(self.guest, xenrt.lib.xenserver.Guest):
            return xenrt.HypervisorType.xen
        if isinstance(self.guest, xenrt.lib.kvm.KVMGuest):
            return xenrt.HypervisorType.kvm
        if isinstance(self.guest, xenrt.lib.esx.Guest):
            return xenrt.HypervisorType.vmware
        if isinstance(self.guest, xenrt.lib.hyperv.Guest):
            return xenrt.HypervisorType.hyperv
        raise xenrt.XRTError("Could not determine hypervisor type")

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
        self.guest.start()

    def stopInstance(self, instance, force=False):
        self.guest.shutdown(force=force)

    def existingInstance(self, name):
        raise xenrt.XRTError("Not implemented")

    def rebootInstance(self, instance, force=False):
        self.guest.reboot(force=force) 
    
    def suspendInstance(self, instance):
        self.guest.suspend()
    
    def resumeInstance(self, instance, on):
        self.guest.resume()
    
    def createInstance(self, distro, name, vcpus,  memory, vifs, rootdisk, extraConfig, startOn, installTools, useTemplateIfAvailable, hypervisorType):
        """Create and install and instance on this toolstack"""

    def createOSTemplate(self, distro, rootdisk,installTools, useTemplateIfAvailable, hypervisorType=None):
        """Create a template for the specified OS, to be used later by createInstance"""
        raise xenrt.XRTError("Not implemented")

    def getInstanceIP(self, instance, timeout, level):
        """Get the IP for the specified instance, with timeout"""
        return self.guest.getIP()

    def migrateInstance(self, instance, to, live):
        """Resume the specified instance"""
        host = xenrt.GEC().registry.hostGet(to)
        self.guest.migrateVM(host, live=live)

    def destroyInstance(self, instance):
        """Destroy the specified instance"""
        self.guest.uninstall(destroyDisks=True)

    def getInstancePowerState(self, instance):
        """Get the current power state for the specified instance"""
        state = self.guest.getState()
        states = {"DOWN": xenrt.PowerState.down,
                  "UP": xenrt.PowerState.up,
                  "SUSPENDED": xenrt.PowerState.suspended,
                  "PAUSED": xenrt.PowerState.paused}
        return states[state]

    def setInstanceIso(self, instance, isoName, isoRepo):
        """Set the ISO in the instance"""
        raise xenrt.XRTError("Not implemented")

    def ejectInstanceIso(self, instance):   
        """Eject the ISO from the specified instance"""
        raise xenrt.XRTError("Not implemented")

    def createInstanceSnapshot(self, instance, name, memory, quiesce):
        """Snapshot an instance"""
        raise xenrt.XRTError("Not implemented")

    def deleteInstanceSnapshot(self, instance, name):
        """Delete an Instance Snapshot"""
        raise xenrt.XRTError("Not implemented")
    
    def revertInstanceToSnapshot(self, instance, name):
        """Revert an Instance to a named snapshot"""
        raise xenrt.XRTError("Not implemented")

    def instanceScreenshot(self, instance, path):
        """Screenshot an instance"""
        pass

    def getLogs(self, path):
        """Retrieve logs into path"""
        pass

    def discoverInstanceAdvancedNetworking(self, instance):
        pass
