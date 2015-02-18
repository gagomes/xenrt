# XenRT: Test harness for Xen and the XenServer product family
#
# Docker and docker container library classes.
#
# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt, string, random
import xmltodict

__all__ = ["ContainerCreateMethod",
            "ContainerState", "ContainerOperations", "ContainerNames",
            "UsingXapi", "UsingLinux",
            "CoreOSDocker", "RHELDocker", "UbuntuDocker"]

"""
Factory class for docker container.
"""

class ContainerCreateMethod:
    coreOS="CoreOS"
    viaXapi="ViaXapi"

class ContainerState:
    RUNNING  = "RUNNING"
    STOPPED  = "STOPPED"
    PAUSED   = "PAUSED"
    UNPAUSED = "UNPAUSED"
    RESTARTED = "RESTARTED"
    UNKNOWN = "UNKNOWN"

class ContainerOperations:
    START  = "start"
    STOP  = "stop"
    RESTART = "restarted"
    PAUSE   = "pause"
    UNPAUSE = "unpause"
    INSPECT = "get_inspect"
    GETTOP = "get_top"
    REGISTER = "register"
    CREATE = "create"
    REMOVE = "remove"

class ContainerNames:
    BUSYBOX = "busybox"
    MYSQL = "mysql"
    TOMCAT = "tomcat"

"""
Data layer: Container encapsulated data
"""

class Container(object):

    def __init__(self, ctype, cname):
        self.ctype = ctype
        self.cname = cname
    def __str__(self):
        return ';'.join([self.ctype, self.cname])

"""
Using Bridge pattern to realise the docker feature testing.
"""

# Implementor
class ContainerController(object):

    def __init__(self, host, guest):
        self.host = host
        self.guest = guest

    def containerSelection(self, container):

        if container.ctype == ContainerNames.BUSYBOX:
            xenrt.TEC().logverbose("Create BusyBox Container using Xapi")
            return "'docker run -d --name " + container.cname + " busybox /bin/sh -c \"while true; do echo Hello World; sleep 1; done\"'"
        elif container.ctype == ContainerNames.MYSQL:
            xenrt.TEC().logverbose("Create MySQL Container using Xapi")
            return "'docker run -d --name " + container.cname + " -e MYSQL_ROOT_PASSWORD=mysecretpassword mysql'"
        elif container.ctype == ContainerNames.TOMCAT:
            xenrt.TEC().logverbose("Create Tomcat Container using Xapi")
            return "'docker run -d --name " + container.cname + " -p 8080:8080 -it tomcat'"
        else:
            raise xenrt.XRTFailure("Docker container type %s is not recognised" % container.ctype)

    def createContainer(self, container): pass
    def rmContainer(self, container): pass

    # Container lifecycle operations.
    def startContainer(self, container): pass
    def stopContainer(self, container): pass
    def pauseContainer(self, container): pass
    def unpauseContainer(self, container): pass
    def restartContainer(self, container): pass

# Concrete Implementor
class UsingXapi(ContainerController):

    def containerXapiLCOperations(self, operation, container):

        args = []
        args.append("plugin=xscontainer")
        args.append("fn=%s" % operation)
        args.append("args:vmuuid=%s" % self.guest.getUUID())
        if operation not in [ContainerOperations.INSPECT, ContainerOperations.GETTOP]:
            args.append("args:container=%s" % container.cname)
        else:
            args.append("args:object=%s" % container.cname)

        cli = self.host.getCLIInstance()
        result = cli.execute("host-call-plugin", "%s host-uuid=%s" %
                                (string.join(args), self.host.getMyHostUUID()))

        #xenrt.TEC().logverbose("containerXapiLCOperations - Result: %s" % result)

        if result[:4] == "True" and result[4:] == None: # True and None -> Failure.
                                                        # True with some docker uuid's is a success.
            raise xenrt.XRTFailure("XSContainer:%s operation on %s:%s is failed" %
                                            (operation, self.guest, container.cname))
        else:
            return result[4:] # stop , start, pause, unpause, retruns empty string.
                              # inspect and gettop leaves an xml.

    def createAndRemoveContainer(self, container, operation=ContainerOperations.CREATE):

        if operation == ContainerOperations.CREATE:
            dockerCmd = self.containerSelection(container)
        elif operation == ContainerOperations.REMOVE:
            dockerCmd ="\"docker ps -a -f name=\'" + container.cname + "\' | tail -n +2 | awk \'{print \$1}\' | xargs docker rm\""
        else:
            raise xenrt.XRTFailure("XSContainer:%s operation is not recognised" % operation)

        args = []
        args.append("plugin=xscontainer")
        args.append("fn=passthrough")
        args.append("args:vmuuid=%s" % self.guest.getUUID())
        args.append("args:command=%s" % dockerCmd)

        cli = self.host.getCLIInstance()
        result = cli.execute("host-call-plugin", "host-uuid=%s %s " %
                                (self.host.getMyHostUUID(), string.join(args)))

        if result[:4] == "True" and result[4:] == None:
            raise xenrt.XRTError("XSContainer:%s Operation failed on a container %s using %s:%s" %
                                                    (operation, container.cname, self.host, self.guest))
        else:
            return result[4:] # create and remove returns some docker uuid's.

    def createContainer(self, container):

        result = self.createAndRemoveContainer(container)
        xenrt.TEC().logverbose("createContainer - result: %s" % result)

        # Inspect the container and fill more details, if required.
        return container

    def rmContainer(self, container):

        if self.statusContainer(container) == ContainerState.STOPPED:
            self.createAndRemoveContainer(container, ContainerOperations.REMOVE)
        else:
            raise xenrt.XRTError("removeContainer: Please stop the container %s before removing it" % container.cname)

    def inspectContainer(self, container):
        dockerInspectXML = self.containerXapiLCOperations(ContainerOperations.INSPECT, container)

        dockerInspectDict = xmltodict.parse(dockerInspectXML)

        if not dockerInspectDict.has_key('docker_inspect'):
                raise xenrt.XRTError("inspectContainer: XSContainer - get_inspect failed to get the xml")
        else:
            return dockerInspectDict['docker_inspect']# has keys State, NetworkSettings, Config etc.

    def statusContainer(self, container):

        inspectXML = self.inspectContainer(container)

        if not inspectXML.has_key('State'):
                raise xenrt.XRTError("statusContainer: XSContainer - state key is missing in docker_inspect xml")
        else:
            containerState = inspectXML['State']

            if containerState['Running'] == "True":
                return ContainerState.RUNNING
            elif containerState['Paused'] == "True":
                return ContainerState.PAUSED
            elif containerState['Paused'] == "False" and containerState['Running'] == "False":
                return ContainerState.STOPPED
            elif containerState['Restarting'] == "True":
                return ContainerState.RESTARTED
            else:
                return ContainerState.UNKNOWN

    # Container lifecycle operations.
    def startContainer(self, container):
        if self.statusContainer(container) == ContainerState.STOPPED:
            self.containerXapiLCOperations(ContainerOperations.START, container)
        else:
            raise xenrt.XRTError("startContainer: Container %s can be started if stopped" % container.cname)

    def stopContainer(self, container):
        if self.statusContainer(container) == ContainerState.RUNNING:
            self.containerXapiLCOperations(ContainerOperations.STOP, container)
        else:
            raise xenrt.XRTError("stopContainer: Container %s can be stopped if running" % container.cname)

    def pauseContainer(self, container):
        if self.statusContainer(container) == ContainerState.RUNNING:
            self.containerXapiLCOperations(ContainerOperations.PAUSE, container)
        else:
            raise xenrt.XRTError("pauseContainer: Container %s can be paused if running" % container.cname)

    def unpauseContainer(self, container):
        if self.statusContainer(container) == ContainerState.PAUSED:
            self.containerXapiLCOperations(ContainerOperations.UNPAUSE, container)
        else:
            raise xenrt.XRTError("pauseContainer: Container %s can be unpaused if paused" % container.cname)

    def restartContainer(self, container):
        raise xenrt.XRTError("XENAPI: host-call-plugin call restart is not supported")

class UsingLinux(ContainerController):

    def createContainer(self, name, ctype): pass

    def rmContainer(self, container): pass


"""
Abstraction
"""

class Docker(object):

    def __init__(self, host, guest, ContainerController):
        self.host = host
        self.guest = guest
        self.containers = []
        self.ContainerController = ContainerController(host, guest)
    def install(self): pass
    def createContainer(self, ctype, cname): pass
    def rmContainer(self, container): pass
    def listContainers(self): pass


"""
Refined abstractions
"""

class RHELDocker(Docker):
    """Represents a docker installed on rhel guest"""

    def install(self):
        xenrt.TEC().logverbose("Docker installation on RHEL to be implemented")

    def createContainer(self, ctype, cname="random"):

        if cname.startswith("random"):
            cname = "%s_%08x" % (ctype, (random.randint(0, 0x7fffffff)))

        container = Container(ctype, cname)
        return self.ContainerController.createContainer(container)

    def rmContainer(self, container):
        self.ContainerController.rmContainer(container)

    def listContainers(self): pass

class UbuntuDocker(Docker):
    """Represents a docker installed on ubuntu guest"""

    def install(self):
        xenrt.TEC().logverbose("Docker installation on Ubuntu to be implemented")

    def createContainer(self, ctype, cname="random"):

        if cname.startswith("random"):
            cname = "%s_%08x" % (ctype, (random.randint(0, 0x7fffffff)))

        container = Container(ctype, cname)
        return self.ContainerController.createContainer(container)

    def rmContainer(self, container):
        self.ContainerController.rmContainer(container)

    def listContainers(self): pass

class CoreOSDocker(Docker):
    """Represents a docker integrated in coreos guest"""

    def install(self):
        xenrt.TEC().logverbose("CoreOS has the docker environment by default")

    def listContainers(self): pass

    def createContainer(self, ctype, cname="random"):

        if cname.startswith("random"):
            cname = "%s_%08x" % (ctype, (random.randint(0, 0x7fffffff)))

        container = Container(ctype, cname)
        return self.ContainerController.createContainer(container)

    def rmContainer(self, container):
        self.containers.pop(self.ContainerController.rmContainer(container))

    # Container lifecycle operations.
    def startContainer(self, container, all=False):

        if all:
         for c in self.containers:
            return self.ContainerController.startContainer(c)
        else:
            return self.ContainerController.startContainer(container)

    def stopContainer(self, container):
        return self.ContainerController.stopContainer(container)
    def pauseContainer(self, container):
        return self.ContainerController.pauseContainer(container)
    def unpauseContainer(self, container):
        return self.ContainerController.unpauseContainer(container)
    def restartContainer(self, container):
        return self.ContainerController.restartContainer(container)
