from zope.interface import Interface, Attribute

__all__=["Toolstack", "OSParent"]

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
        """Reboot the specified instance"""

    def suspendInstance(instance):
        """Suspend the specified instance"""

    def resumeInstance(instance, on):
        """Resume the specified instance"""

    def migrateInstance(instance, to, live):
        """Resume the specified instance"""

    def destroyInstance(instance):
        """Destroy the specified instance"""

    def getInstancePowerState(instance):
        """Get the current power state for the specified instance"""

    def ejectInstanceIso(instance):   
        """Eject the ISO from the specified instance"""

class OSParent(Interface):
    name = Attribute("Name of the OS")
    hypervisorType = Attribute("Hypervisor (or native) on which the OS is running")

    def getIP(timeout, level):
        """Get the IP for the OS"""

    def setIP(ip):
        """Set the IP for the OS"""

    def start():
        """Start the OS container (VM/host)"""

    def ejectIso():
        """Eject the ISO from the OS container"""

    def poll(state, timeout, level, pollperiod):
        """Poll for a change in power state"""


