# XenRT: Test harness for Xen and the XenServer product family
#
# Docker and docker container library classes.
#
# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt, string, random
import xmltodict, json
from abc import ABCMeta, abstractmethod

__all__ = ["ContainerState", "ContainerXapiOperation", "ContainerType",
           "XapiPluginDockerController", "LinuxDockerController", "OperationMethod",
           "CoreOSDocker", "RHELDocker", "CentOSDocker", "OELDocker", "UbuntuDocker"]

"""
Factory class for docker container.
"""

class OperationMethod:
    XAPI = "XAPI"
    LINUX = "LINUX"

class ContainerState:
    RUNNING  = "RUNNING"
    STOPPED  = "STOPPED"
    PAUSED   = "PAUSED"
    UNPAUSED = "UNPAUSED"
    RESTARTED = "RESTARTED"
    UNKNOWN = "UNKNOWN"

class ContainerXapiOperation:
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
    LIST = "list"

class ContainerLinuxOperation:
    START  = "start"
    STOP  = "stop"
    RESTART = "restarted"
    PAUSE   = "pause"
    UNPAUSE = "unpause"
    INSPECT = "inspect"
    GETTOP = "top"
    CREATE = "create"
    REMOVE = "rm"
    LIST = "list"

class ContainerType:
    BUSYBOX = "busybox"
    MYSQL = "mysql"
    TOMCAT = "tomcat"
    UNKNOWN = "unknown"

"""
Data layer: Container encapsulated data
"""

class Container(object):

    def __init__(self, ctype, cname):
        self.ctype = ctype
        self.cname = cname

"""
Using Bridge pattern to realise the docker feature testing.
"""

# Implementor
class DockerController(object):
    __metaclass__ = ABCMeta

    def __init__(self, host, guest):
        self.host = host
        self.guest = guest

    def containerSelection(self, container, method=OperationMethod.XAPI):

        if container.ctype == ContainerType.BUSYBOX:
            xenrt.TEC().logverbose("Create BusyBox Container using %s way" % method)
            dockerCmd = "docker run -d --name " + container.cname + " busybox /bin/sh -c \"while true; do echo Hello World; sleep 1; done\""
        elif container.ctype == ContainerType.MYSQL:
            xenrt.TEC().logverbose("Create MySQL Container using %s way" % method)
            dockerCmd = "docker run -d --name " + container.cname + " -e MYSQL_ROOT_PASSWORD=mysecretpassword mysql"
        elif container.ctype == ContainerType.TOMCAT:
            xenrt.TEC().logverbose("Create Tomcat Container using %s way" % method)
            dockerCmd = "docker run -d --name " + container.cname + " -p 8080:8080 -it tomcat"
        else:
            raise xenrt.XRTError("Docker container type %s is not recognised" % container.ctype)

        if method==OperationMethod.XAPI:
            return "'" + dockerCmd + "'"
        elif method==OperationMethod.LINUX:
            return dockerCmd
        else:
            raise xenrt.XRTError("Operation method %s in defined" % dockerCmd)

    @abstractmethod
    def createContainer(self, container): pass
    @abstractmethod
    def rmContainer(self, container): pass

    # Container lifecycle operations.
    @abstractmethod
    def startContainer(self, container): pass
    @abstractmethod
    def stopContainer(self, container): pass
    @abstractmethod
    def pauseContainer(self, container): pass
    @abstractmethod
    def unpauseContainer(self, container): pass
    @abstractmethod
    def restartContainer(self, container): pass

    # Other functions.
    @abstractmethod
    def inspectContainer(self, container):pass
    @abstractmethod
    def gettopContainer(self, container):pass
    @abstractmethod
    def statusContainer(self, container):pass
    @abstractmethod
    def listContainers(self): pass

    # Misc functions.
    @abstractmethod
    def getDockerInfo(self):pass
    @abstractmethod
    def getDockerPS(self):pass
    @abstractmethod
    def getDockerVersion(self):pass

# Concrete Implementor
class XapiPluginDockerController(DockerController):

    def containerXapiLCOperation(self, operation, container):

        args = []
        args.append("plugin=xscontainer")
        args.append("fn=%s" % operation)
        args.append("args:vmuuid=%s" % self.guest.getUUID())
        if operation not in [ContainerXapiOperation.INSPECT, ContainerXapiOperation.GETTOP]:
            args.append("args:container=%s" % container.cname)
        else:
            args.append("args:object=%s" % container.cname)

        cli = self.host.getCLIInstance()
        result = cli.execute("host-call-plugin", "%s host-uuid=%s" %
                                (string.join(args), self.host.getMyHostUUID())).strip()

        #xenrt.TEC().logverbose("containerXapiLCOperation - Result: %s" % result)

        if result[:4] == "True":
            if operation not in [ContainerXapiOperation.INSPECT, ContainerXapiOperation.GETTOP]:
                return True # stop , start, pause, unpause, retruns a boolean.
            else:
                if result[4:] == None: # True and None is a failure.
                    raise xenrt.XRTError("XSContainer:%s operation on %s:%s returned an empty xml" %
                                                                (operation, self.guest, container.cname))
                else:
                    return result[4:] # inspect, getop has an xml that we deal with.
        else:
            raise xenrt.XRTError("XSContainer:%s operation on %s:%s is failed" %
                                            (operation, self.guest, container.cname))

    def containerXapiOtherOperation(self, container, operation=ContainerXapiOperation.CREATE):

        if operation == ContainerXapiOperation.CREATE:
            dockerCmd = self.containerSelection(container)
        elif operation == ContainerXapiOperation.REMOVE:
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
                                (self.host.getMyHostUUID(), string.join(args))).strip()

        if result[:4] == "True" and result[4:] == None: # True and None is a failure.
            raise xenrt.XRTError("XSContainer:%s Operation failed on a container %s using %s:%s" %
                                                    (operation, container.cname, self.host, self.guest))
        else:
            return result[4:] # create and remove returns some docker uuid's.

    def createContainer(self, container):

        result = self.containerXapiOtherOperation(container)
        xenrt.TEC().logverbose("createContainer - result: %s" % result)

        # Inspect the container and fill more details, if required.
        return container

    def rmContainer(self, container):

        if self.statusContainer(container) == ContainerState.STOPPED:
            return self.containerXapiOtherOperation(container, ContainerXapiOperation.REMOVE)
        else:
            raise xenrt.XRTError("removeContainer: Please stop the container %s before removing it" % container.cname)

    # Container lifecycle operations.
    def startContainer(self, container):
        if self.statusContainer(container) == ContainerState.STOPPED:
            return self.containerXapiLCOperation(ContainerXapiOperation.START, container)
        else:
            raise xenrt.XRTError("startContainer: Container %s can be started if stopped" % container.cname)

    def stopContainer(self, container):
        if self.statusContainer(container) == ContainerState.RUNNING:
            return self.containerXapiLCOperation(ContainerXapiOperation.STOP, container)
        else:
            raise xenrt.XRTError("stopContainer: Container %s can be stopped if running" % container.cname)

    def pauseContainer(self, container):
        if self.statusContainer(container) == ContainerState.RUNNING:
            return self.containerXapiLCOperation(ContainerXapiOperation.PAUSE, container)
        else:
            raise xenrt.XRTError("pauseContainer: Container %s can be paused if running" % container.cname)

    def unpauseContainer(self, container):
        if self.statusContainer(container) == ContainerState.PAUSED:
            return self.containerXapiLCOperation(ContainerXapiOperation.UNPAUSE, container)
        else:
            raise xenrt.XRTError("pauseContainer: Container %s can be unpaused if paused" % container.cname)

    def restartContainer(self, container):
        raise xenrt.XRTError("XENAPI: host-call-plugin call restart is not supported")

    # Other functions.

    def inspectContainer(self, container):
        dockerInspectXML = self.containerXapiLCOperation(ContainerXapiOperation.INSPECT, container)

        dockerInspectDict = self.convertToOrderedDict(dockerInspectXML)

        if not dockerInspectDict.has_key('docker_inspect'):
                raise xenrt.XRTError("inspectContainer: XSContainer - get_inspect failed to get the xml")
        else:
            return dockerInspectDict['docker_inspect']# has keys State, NetworkSettings, Config etc.

    def gettopContainer(self, container):
        dockerGetTopXML = self.containerXapiLCOperation(ContainerXapiOperation.GETTOP, container)

        dockerGetTopDict = self.convertToOrderedDict(dockerGetTopXML)

        if not dockerGetTopDict.has_key('docker_top'):
                raise xenrt.XRTError("gettopContainer: XSContainer - docker_top failed to get the xml")
        else:
            return dockerGetTopDict['docker_top']# has keys Process etc.

    def statusContainer(self, container):

        inspectXML = self.inspectContainer(container)

        if not inspectXML.has_key('State'):
                raise xenrt.XRTError("statusContainer: XSContainer - state key is missing in docker_inspect xml")
        else:
            containerState = inspectXML['State']

            if containerState['Paused'] == "False" and containerState['Running'] == "True":
                return ContainerState.RUNNING
            elif containerState['Paused'] == "True" and containerState['Running'] == "True":
                return ContainerState.PAUSED
            elif containerState['Paused'] == "False" and containerState['Running'] == "False":
                return ContainerState.STOPPED
            else:
                return ContainerState.UNKNOWN

    def listContainers(self):
        xenrt.TEC().logverbose("listContainers: Using getDockerPS to list the containers ...")

        containers = []
        dockerPS = self.getDockerPS() # returns a xml with a key 'entry'

        if not dockerPS.has_key('entry'):
            raise xenrt.XRTError("listContainers: Failed to find entry key in docker PS xml")
        dockerContainerList = dockerPS['entry'] # list of ordered dicts.

        if len(dockerContainerList) > 0:
            for containerDict in dockerContainerList:
                if containerDict.has_key('names'):
                    containers.append(containerDict['names'].strip())
                else:
                    raise xenrt.XRTError("listContainers: The container name could not accessed")
        else:
            raise xenrt.XRTError("listContainers: There are no containers to list")

        return containers

    # Misc functions to work with vm:other-config param.

    def convertToOrderedDict(self, xml_data):
        """Converts the given xml into an ordered dictionary"""

        try:
            xml_dict = xmltodict.parse(xml_data)
        except xmltodict.expat.ExpatError:
            raise xenrt.XRTError("convertOrderedDict: The given xml experience ExpatError while parsing")

        return(xml_dict)

    def dockerGeneralInfo(self, dcommand):

        dockerGeneralList = self.host.minimalList("vm-param-get",
                                args="uuid=%s param-name=other-config param-key=%s" %
                                                            (self.guest.getUUID(), dcommand))
        if len(dockerGeneralList) < 1:
            raise xenrt.XRTError("dockerGeneralInfo: General docker info for %s is not found" % dcommand)

        dockerGeneralDict = self.convertToOrderedDict(dockerGeneralList[0])
        if not dockerGeneralDict.has_key(dcommand):
                raise xenrt.XRTError("dockerGeneralInfo: Failed to find %s tag on the xml" % dcommand)
        return dockerGeneralDict[dcommand] # returning ordered dict.

    def getDockerInfo(self):
        return self.dockerGeneralInfo('docker_info')

    def getDockerPS(self):
        return self.dockerGeneralInfo('docker_ps')

    def getDockerVersion(self):

        dockerVersionDict = self.dockerGeneralInfo('docker_version')
        if dockerVersionDict.has_key('Version'): # has other keys such as KernelVersion, ApiVersion, GoVersion etc.
            return dockerVersionDict['Version']
        else:
            raise xenrt.XRTError("getDockerVersion: Version key is missing in docker_version xml")

class LinuxDockerController(DockerController):

    def containerLinuxLCOperation(self, operation, container):

        dockerCmd = "docker " + operation + " " + container.cname
        cmdOut = self.guest.execguest(dockerCmd).strip() # busybox31d3c2d2\n

        if operation not in [ContainerLinuxOperation.INSPECT]:
            if cmdOut == container.cname:
                return True
            else:
                raise xenrt.XRTFailure("XSContainer:%s operation on %s:%s is failed" %
                                                (operation, self.guest, container.cname))
        else:
            return cmdOut # inspect returns a json.

    def createContainer(self, container):

        dockerCmd = self.containerSelection(container, OperationMethod.LINUX)

        cmdOut = self.guest.execguest(dockerCmd).strip() # 817d4deb9ad84092ee97d9e090732fe335e428e960e8ccc0829a768ad9c92a3c\n

        if cmdOut.isalnum() and len(cmdOut) == 64:
            # Fill more container details, if required.
            return container
        else:
            raise xenrt.XRTError("createContainer: Failed to create a container " + container.cname) 

    def rmContainer(self, container):

        if self.statusContainer(container) == ContainerState.STOPPED:
            return self.containerLinuxLCOperation(ContainerLinuxOperation.REMOVE, container)
        else:
            raise xenrt.XRTError("rmContainer: Please stop the container %s before removing it" % container.cname)

    # Container lifecycle operations.
    def startContainer(self, container):
        if self.statusContainer(container) == ContainerState.STOPPED:
            return self.containerLinuxLCOperation(ContainerLinuxOperation.START, container)
        else:
            raise xenrt.XRTError("startContainer: Container %s can be started if stopped" % container.cname)

    def stopContainer(self, container):
        if self.statusContainer(container) == ContainerState.RUNNING:
            return self.containerLinuxLCOperation(ContainerLinuxOperation.STOP, container)
        else:
            raise xenrt.XRTError("stopContainer: Container %s can be stopped if running" % container.cname)

    def pauseContainer(self, container):
        if self.statusContainer(container) == ContainerState.RUNNING:
            return self.containerLinuxLCOperation(ContainerLinuxOperation.PAUSE, container)
        else:
            raise xenrt.XRTError("pauseContainer: Container %s can be paused if running" % container.cname)

    def unpauseContainer(self, container):
        if self.statusContainer(container) == ContainerState.PAUSED:
            return self.containerLinuxLCOperation(ContainerLinuxOperation.UNPAUSE, container)
        else:
            raise xenrt.XRTError("pauseContainer: Container %s can be unpaused if paused" % container.cname)

    def inspectContainer(self, container):
        dockerInspectString = self.containerLinuxLCOperation(ContainerLinuxOperation.INSPECT, container)

        dockerInspectString = ' '.join(dockerInspectString.split())
        dockerInspectList = json.loads(dockerInspectString)

        if len(dockerInspectList) < 1:
            raise xenrt.XRTError("inspectContainer: XSContainer - inspect failed to get the json")
        else:
            return dockerInspectList[0] # is a dict has keys State, NetworkSettings, Config etc.

    def statusContainer(self, container):

        inspectXML = self.inspectContainer(container)

        if not inspectXML.has_key('State'):
                raise xenrt.XRTError("statusContainer: XSContainer - state key is missing in docker json")
        else:
            containerState = inspectXML['State']

            if containerState['Paused'] == False and containerState['Running'] == True:
                return ContainerState.RUNNING
            elif containerState['Paused'] == True and containerState['Running'] == True:
                return ContainerState.PAUSED
            elif containerState['Paused'] == False and containerState['Running'] == False:
                return ContainerState.STOPPED
            else:
                return ContainerState.UNKNOWN

    def listContainers(self):

        dockerCmd = "docker ps -a | tail -n +2 | awk '{print $NF}'"
        containerInfo = self.guest.execguest(dockerCmd).strip()

        if containerInfo:
            containerList = containerInfo.splitlines()
            return containerList # [containername]
        else:
            raise xenrt.XRTError("listContainers: There are no containers available to list")

"""
Abstraction
"""

class Docker(object):

    def __init__(self, host, guest, DockerController):
        self.host = host
        self.guest = guest
        self.containers = []
        self.DockerController = DockerController(host, guest)

    def install(self):
        self.installDocker()
        self.checkDocker()
        self.enabledPassthroughPlugin() # on host to create containers using Xapi.
        self.registerGuest()

    def installDocker(self): pass

    def registerGuest(self):
        """Register a guest for container monitoring""" 

        self.host.execdom0("xe host-call-plugin host-uuid=%s plugin=xscontainer fn=register args:vmuuid=%s" %
                                                                (self.host.getMyHostUUID(), self.guest.getUUID()))

    def checkDocker(self):
        """Check for a working docker install"""

        xenrt.TEC().logverbose("Checking the installation of Docker on guest %s" % self.guest)
    
        guestCmdOut = self.guest.execguest("docker info").strip()
        if "Operating System: CoreOS" in guestCmdOut:
            xenrt.TEC().logverbose("Docker installation is running on guest %s" % self.guest)
        else: 
            raise xenrt.XRTError("Failed to find a running instance of Docker on guest %s" % self.guest)

    def enabledPassthroughPlugin(self): 
        """Workaround in Dom0 to enable the passthrough plugin to create docker container"""

        self.host("mkdir -p /opt/xensource/packages/files/xscontainer")
        self.host("touch /opt/xensource/packages/files/xscontainer/devmode_enabled")

        xenrt.TEC().logverbose("XSContainer: Passthrough plugin in Dom0 to create docker container is enabled")


    def createContainer(self, ctype=ContainerType.BUSYBOX, cname="random"):
        if cname.startswith("random"):
            cname = "%s%08x" % (ctype, (random.randint(0, 0x7fffffff)))
        container = Container(ctype, cname)
        self.containers.append(self.DockerController.createContainer(container))
        return container

    def rmContainer(self, container):
        containerID = self.DockerController.rmContainer(container)
        # receive the container ID: 5fbb53340080 from docker. Populate this ISD in container.
        # check and delete.
        self.containers.remove(container)

    # Container lifecycle operations.

    def startContainer(self, container):
        return self.DockerController.startContainer(container)
    def stopContainer(self, container):
        return self.DockerController.stopContainer(container)
    def pauseContainer(self, container):
        return self.DockerController.pauseContainer(container)
    def unpauseContainer(self, container):
        return self.DockerController.unpauseContainer(container)
    def restartContainer(self, container):
        return self.DockerController.restartContainer(container)

    # Other functions.

    def inspectContainer(self, container):
        return self.DockerController.inspectContainer(container)
    def gettopContainer(self, container):
        return self.DockerController.gettopContainer(container)
    def statusContainer(self, container):
        return self.DockerController.statusContainer(container)

    # Misc functions.

    def getDockerInfo(self):
        return self.DockerController.getDockerInfo()
    def getDockerPS(self):
        return self.DockerController.getDockerPS()
    def getDockerVersion(self):
        return self.DockerController.getDockerVersion()

    # Useful functions.
    def setContainer(self, cname, ctype=ContainerType.UNKNOWN):
        return(Container(ctype, cname)) # returns a container object.

    def loadExistingContainers(self):
        for cname in self.DockerController.listContainers():
            self.containers.append(Container(ContainerType.UNKNOWN, cname))

    def listContainers(self):
        return self.DockerController.listContainers() # list of containers.

    def numberOfContainers(self):
        return(len(self.listContainers()))

    def lifeCycleAllContainers(self):
        """Life Cycle method on all containers"""
        for container in self.containers:
            self.lifeCycleContainer(container)

    def stopAllContainers(self):
        for container in self.containers:
            self.stopContainer(container)
            xenrt.sleep(5)

    def startAllContainers(self):
        for container in self.containers:
            self.startContainer(container)
            xenrt.sleep(5)

    def lifeCycleContainer(self, container):
        """Life Cycle method on a specified container"""
        self.stopContainer(container)
        xenrt.sleep(5)
        self.startContainer(container)
        xenrt.sleep(5)
        self.pauseContainer(container)
        xenrt.sleep(5)
        self.unpauseContainer(container)
        xenrt.sleep(5)

"""
Refined abstractions
"""

class CoreOSDocker(Docker):
    """Represents a docker integrated in coreos guest"""

    def installDocker(self):
        xenrt.TEC().logverbose("CoreOS has the docker environment by default")

class CentOSDocker(Docker):
    """Represents a docker integrated in centos guest"""

    def installDocker(self): pass
        # Perform the installation.

    def registerGuest(self):
        """Register VM for XenServer container management"""

        # Workaround having to provide input when setting up VMs for monitoring
        expectscript = """#!/usr/bin/expect -f
# Workaround having to provide input when setting up VMs for monitoring

set vmuuid [lindex $argv 0]
set vmusername [lindex $argv 1]
set vmpassword [lindex $argv 2]

spawn xscontainer-prepare-vm -v $vmuuid -u $vmusername
expect -exact "Answer y/n:"
send "y\n"
sleep 5
expect -exact "Are you sure you want to continue connecting (yes/no)?"
send "yes\n"
sleep 5
interact -o -nobuffer -re ":" return
expect "password"
send "$vmpassword\n"
sleep 5
interact return
"""
        self.host.execdom0("echo '%s' > expectscript.sh; exit 0" % expectscript)
        self.host.execdom0("chmod a+x expectscript.sh; exit 0")
        commandOutput = self.host.execdom0("/root/expectscript.sh %s root xenroot" % (self.guest.getUUID()))

class UbuntuDocker(Docker):
    """Represents a docker installed on ubuntu guest"""

    def installDocker(self):

        # A best practice to ensure the list of available packages
        # are up to date before installing anything new.
        self.guest("apt-get update")

        # Install Docker by installing the docker-io package.
        self.guest("apt-get -y install docker.io")

        # Link and fix paths with the following two commands.
        self.guest("ln -sf /usr/bin/docker.io /usr/local/bin/docker")
        self.guest("sed -i '$acomplete -F _docker docker' /etc/bash_completion.d/docker.io")

        # Configure Docker to start when the server boots.
        self.guest("update-rc.d docker.io defaults")

        xenrt.TEC().logverbose("Docker installation on Ubuntu is complete.")

class RHELDocker(Docker):
    """Represents a docker installed on rhel guest"""

    def installDocker(self):pass

class OELDocker(Docker):
    """Represents a docker integrated in oel guest"""

    def installDocker(self):pass
