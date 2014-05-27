from zope.interface import Interface, Attribute

__all__=["Toolstack", "OSParent", "OS", "InstallMethodPV", "InstallMethodIso", "InstallMethodIsoWithAnswerFile"]

class Toolstack(Interface):
    def instanceHypervisorType(instance):
        """Return the hypervisor type for the specified instance"""

    def instanceResidentOn(instance):
        """Return the place of residence of the current instance"""

    def instanceCanMigrateTo(instance):
        """Return a list of locations to which the instance can migrate"""

    def instanceSupportedLifecycleOperations(instance):
        """Return the lifecycle operations supported by the specified instance on this toolstack"""

    def createInstance(distro, name, vcpus,  memory, vifs, rootdisk, extraConfig, startOn, installTools, useTemplateIfAvailable, hypervisorType):
        """Create and install and instance on this toolstack"""

    def existingInstance(name):
        """Return an existing instance with the specified name"""

    def getAllExistingInstances():
        """Returns all existing instances"""

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

    def setInstanceIso(instance, isoName, isoRepo):
        """Set the ISO in the instance"""

    def ejectInstanceIso(instance):   
        """Eject the ISO from the specified instance"""

    def createInstanceSnapshot(instance, name, memory, quiesce):
        """Snapshot an instance"""

    def deleteInstanceSnapshot(instance, name):
        """Delete an Instance Snapshot"""
    
    def revertInstanceToSnapshot(instance, name):
        """Revert an Instance to a named snapshot"""

    def instanceScreenshot(instance, path):
        """Screenshot an instance"""

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

    def setIso(isoName, isoRepo):
        """Set the ISO to the specified iso"""

    def poll(state, timeout, level, pollperiod):
        """Poll for a change in power state"""

    def assertHealthy():
        """Quickly assert the health of the instance"""


class OS(Interface):

    installMethod = Attribute("Selected installation method")

    defaultRootdisk = Attribute("Default rootdisk size")

    defaultVcpus = Attribute("Default number of vCPUs")

    defaultRootdisk = Attribute("Default root disk size")

    defaultMemory = Attribute("Default memory size")

    canonicalDistroName = Attribute("Canonical distro name")

    def knownDistro(distro):
        """Determine if the given distro is known to this library"""

    def waitForBoot(timeout):
        """Wait for the OS to boot"""

    def testInit(parent):
        """Instantiate a dummy version for interface testing"""

    def reboot():
        """Perform an OS-initiated reboot"""

    def shutdown():
        """Perform an OS-initiated shutdown"""

    def populateFromExisting():
        """Populate class members from an existing OS installaion"""

    def assertHealthy():
        """Quickly verify that the OS is in a healthy state"""

class InstallMethodPV(Interface):
    installURL = Attribute("HTTP installation URL")
    installerKernelAndInitRD = Attribute("Installer PV kernel and initrd")

    def generateAnswerfile(webdir):
        """Generate an answerfile for the OS"""

    def waitForInstallCompleteAndFirstBoot():
        """Wait for installation completion and first boot"""

class InstallMethodIso(Interface):
    isoName = Attribute("ISO name")
    isoRepo = Attribute("ISO repository")

    def waitForInstallCompleteAndFirstBoot():
        """Wait for installation completion and first boot"""

class InstallMethodIsoWithAnswerFile(InstallMethodIso):

    def generateIsoAnswerfile():
        """Generate an answerfile for ISO installation"""


class StringGenerator(Interface):
    def generate(length):
        """Generate the string fitting the implementation"""
