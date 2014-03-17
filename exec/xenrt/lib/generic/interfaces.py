from zope.interface import Interface

__all__=["Toolstack"]

class Toolstack(Interface):
    def instanceHypervisorType(instance):
        """Return the hypervisor type for the specified instance"""

    def createInstance(distro, name, vcpus,  memory, vifs, rootdisk, extraConfig, startOn, installTools):
        """Create and install and instance on this toolstack"""

    def existingInstance(name):
        """Return an existing instance with the specified name"""

    def getInstanceIP(instance, timeout, level):
        """Get the IP for the specified instance, with timeout"""

    def startInstance(instance, on):
        """Start the specified instnace"""

    def stopInstance(instance, force):
        """Stop the specified instnace"""

    def rebootInstance(instance, force):
        """Reboot the specified instnace"""

    def getInstancePowerState(instance):
        """Get the current power state for the specified instance"""

    def ejectInstanceIso(instance):   
        """Eject the ISO from the specified instance"""
