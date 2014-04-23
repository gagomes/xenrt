import xenrt
import xenrt.lib.xenserver
from abc import ABCMeta, abstractmethod
from xenrt.lazylog import log, step


class LifecycleOperation(object):
    """ Abstract lifecycle operation command base class """
    __metaclass__ = ABCMeta

    def __init__(self, toolstack):
        self._toolstack = toolstack

    @abstractmethod
    def _type(self):
        pass

    def supported(self, instance):
        ops = self._toolstack.instanceSupportedLifecycleOperations(instance)
        return self._type() in ops

    def precheck(self, instance):
        return True

    @abstractmethod
    def run(self, instance):
        pass

    @abstractmethod
    def verify(self, instance):
        pass


class StopInstance(LifecycleOperation):

    def _type(self):
        return xenrt.LifecycleOperation.stop

    def precheck(self, instance):
        state = self._toolstack.getInstancePowerState(instance)
        return state == xenrt.PowerState.up

    def run(self, instance):
        self._toolstack.stopInstance(instance)

    def verify(self, instance):
        state = self._toolstack.getInstancePowerState(instance)
        return state == xenrt.PowerState.down


class ShutdownInstance(StopInstance):

    def run(self, instance):
        instance.stop(osInitiated=True)


class StartInstance(LifecycleOperation):

    def _type(self):
        return xenrt.LifecycleOperation.start

    def precheck(self, instance):
        state = self._toolstack.getInstancePowerState(instance)
        return state == xenrt.PowerState.down

    def run(self, instance):
        self._toolstack.startInstance(instance)

    def verify(self, instance):
        state = self._toolstack.getInstancePowerState(instance)
        return state == xenrt.PowerState.up


class BootInstance(StartInstance):

    def run(self, instance):
        instance.start()


class RebootInstance(LifecycleOperation):

    def _type(self):
        return xenrt.LifecycleOperation.reboot

    def precheck(self, instance):
        state = self._toolstack.getInstancePowerState(instance)
        return state == xenrt.PowerState.up

    def run(self, instance):
        instance.reboot(osInitiated=False)

    def verify(self, instance):
        state = self._toolstack.getInstancePowerState(instance)
        return state == xenrt.PowerState.up


class RebootInstanceOsInitiated(RebootInstance):

    def run(self, instance):
        instance.reboot(osInitiated=True)


class SuspendInstance(LifecycleOperation):

    def _type(self):
        return xenrt.LifecycleOperation.suspend

    def precheck(self, instance):
        state = self._toolstack.getInstancePowerState(instance)
        return state == xenrt.PowerState.up

    def run(self, instance):
        self._toolstack.suspendInstance(instance)

    def verify(self, instance):
        state = self._toolstack.getInstancePowerState(instance)
        return state == xenrt.PowerState.up


class ResumeInstance(LifecycleOperation):

    def _type(self):
        return xenrt.LifecycleOperation.resume

    def precheck(self, instance):
        state = self._toolstack.getInstancePowerState(instance)
        return state == xenrt.PowerState.suspended

    def run(self, instance):
        self._toolstack.resumeInstance(instance)

    def verify(self, instance):
        state = self._toolstack.getInstancePowerState(instance)
        return state == xenrt.PowerState.up


class DestroyInstance(LifecycleOperation):
    def _type(self):
        return xenrt.LifecycleOperation.destroy

    def __instanceExists(self, instance):
        try:
            self._toolstack.existingInstance(instance.name)
            return True
        except:
            return False

    def precheck(self, instance):
        return self.__instanceExists(instance)

    def run(self, instance):
        self._toolstack.destroyInstance(instance)

    def verify(self, instance):
        return not self.__instanceExists(instance)


class MigrateInstance(LifecycleOperation):

    def _type(self):
        return xenrt.LifecycleOperation.livemigrate

    def precheck(self, instance):
        self.__startsOn = self._toolstack.instanceResidentOn(instance)
        log("Instance starting on %s" % self.__startsOn)
        return True

    def run(self, instance):
        migrateToList = self._toolstack.instanceCanMigrateTo(instance)
        if not migrateToList or len(migrateToList) < 1:
            msg = "The toolstack cannot find a suitable location to migrate to"
            raise xenrt.XRTError(msg)
        migrateTo = self._toolstack.instanceCanMigrateTo(instance)[0]
        log("Instance migrating to %s" % migrateTo)
        self._toolstack.migrateInstance(instance, migrateTo)

    def verify(self, instance):
        resident = self._toolstack.instanceResidentOn(instance)
        log("Instance started: %s ended: %s" % (self.__startsOn, resident))
        return resident != self.__startsOn


class LifecycleInvoker(object):
    """
    Invoker class for lifecycle operations command classes
    """

    def __init__(self, commandList):
        self.__commandList = commandList

    def runCommands(self, instance, distro):
        for op in self.__commandList:
            self.__runOperation(op, distro, instance)

    def __runOperation(self, operation, distro, instance):
        name = type(operation).__name__
        step("%s Running operation: %s" % (distro, name))

        if not operation.supported(instance):
            step("Skipping test %s as it is not supported" % name)
            return

        step("Precheck state")
        if not operation.precheck(instance):
            raise xenrt.XRTFailure("Precheck failed")

        step("Execute operation")
        operation.run(instance)

        step("Verify result")
        if not operation.verify(instance):
            raise xenrt.XRTFailure("Verification failed")

        #Let the toolstack settle before the next operation
        xenrt.sleep(120)


class TCCloudGuestLifeCycle(xenrt.TestCase):
    def __fetchOsFromArg(self, arglist):
        """Parse the args from the sequence file"""
        for arg in arglist:
            if arg.startswith("distro"):
                return arg.split('=')[-1]
        return None

    def prepare(self, arglist):
        self.__ts = xenrt.TEC().registry.toolstackGetDefault()
        step("Spin up a %s" % self.__fetchOsFromArg(arglist))
        self.__distro = self.__fetchOsFromArg(arglist)

        self.__instance = self.__ts.createInstance(self.__distro,
                                                  useTemplateIfAvailable=False)

    def run(self, arglist):
        operations = [StopInstance(self.__ts), StartInstance(self.__ts),
                      SuspendInstance(self.__ts), ResumeInstance(self.__ts),
                      ShutdownInstance(self.__ts), BootInstance(self.__ts),
                      RebootInstance(self.__ts), MigrateInstance(self.__ts),
                      RebootInstanceOsInitiated(self.__ts),
                      DestroyInstance(self.__ts)]

        invoker = LifecycleInvoker(operations)
        invoker.runCommands(self.__instance, self.__distro)
