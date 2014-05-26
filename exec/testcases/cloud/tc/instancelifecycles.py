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
        ops = instance.supportedLifecycleOperations
        return self._type() in ops

    @abstractmethod
    def run(self, instance):
        pass

class StopInstance(LifecycleOperation):

    def _type(self):
        return xenrt.LifecycleOperation.stop

    def run(self, instance):
        instance.stop()

class ShutdownInstance(StopInstance):

    def run(self, instance):
        instance.stop(osInitiated=True)


class StartInstance(LifecycleOperation):

    def _type(self):
        return xenrt.LifecycleOperation.start

    def run(self, instance):
        instance.start()

class BootInstance(StartInstance):

    def run(self, instance):
        instance.start()


class RebootInstance(LifecycleOperation):

    def _type(self):
        return xenrt.LifecycleOperation.reboot

    def run(self, instance):
        instance.reboot(osInitiated=False)

class RebootInstanceOsInitiated(RebootInstance):

    def run(self, instance):
        instance.reboot(osInitiated=True)


class SuspendInstance(LifecycleOperation):

    def _type(self):
        return xenrt.LifecycleOperation.suspend

    def run(self, instance):
        instance.suspend()

class ResumeInstance(LifecycleOperation):

    def _type(self):
        return xenrt.LifecycleOperation.resume

    def run(self, instance):
        instance.resume()

class DestroyInstance(LifecycleOperation):
    def _type(self):
        return xenrt.LifecycleOperation.destroy

    def __instanceExists(self, instance):
        try:
            self._toolstack.existingInstance(instance.name)
            return True
        except:
            return False

    def run(self, instance):
        instance.destroy()

class MigrateInstance(LifecycleOperation):

    def _type(self):
        return xenrt.LifecycleOperation.livemigrate

    def run(self, instance):
        migrateToList = instance.canMigrateTo
        if not migrateToList:
            msg = "The toolstack cannot find a suitable location to migrate to"
            raise xenrt.XRTError(msg)
        migrateTo = instance.canMigrateTo[0]
        log("Instance migrating to %s" % migrateTo)
        instance.migrate(migrateTo)


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

        step("Execute operation")
        operation.run(instance)

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
