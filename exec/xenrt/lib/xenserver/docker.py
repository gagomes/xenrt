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
           "CoreOSDocker", "CentOSDocker", "UbuntuDocker"]

"""
Factory class for docker container.
"""

class OperationMethod(object):
    XAPI = "XAPI"
    LINUX = "LINUX"

class ContainerState(object):
    RUNNING  = "RUNNING"
    STOPPED  = "STOPPED"
    PAUSED   = "PAUSED"
    UNPAUSED = "UNPAUSED"
    RESTARTED = "RESTARTED"
    UNKNOWN = "UNKNOWN"

class ContainerXapiOperation(object):
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

class ContainerLinuxOperation(object):
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

class ContainerType(object):
    YES_BUSYBOX = "yes_busybox" # Write continuosly yes.
    SLEEP_BUSYBOX = "sleep_busybox" # Sleep 999999999.
    HW_BUSYBOX = "hw_busybox" # Hello World.
    MYSQL = "mysql"
    TOMCAT = "tomcat"
    UBUNTU = "ubuntu"
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

        if container.ctype == ContainerType.SLEEP_BUSYBOX:
            xenrt.TEC().logverbose("Create Infinite Sleep BusyBox Container using %s way" % method)
            dockerCmd = "docker run -d --name " + container.cname + " busybox /bin/sleep 999999999"
        elif container.ctype == ContainerType.YES_BUSYBOX:
            xenrt.TEC().logverbose("Create Simple Yes BusyBox Container using %s way" % method)
            dockerCmd = "docker run -d --name " + container.cname + " busybox /bin/sh -c \"yes\""
        elif container.ctype == ContainerType.HW_BUSYBOX:
            xenrt.TEC().logverbose("Create Hello World BusyBox Container using %s way" % method)
            dockerCmd = "docker run -d --name " + container.cname + " busybox /bin/sh -c \"while true; do echo Hello World; sleep 1; done\""
        elif container.ctype == ContainerType.MYSQL:
            xenrt.TEC().logverbose("Create MySQL Container using %s way" % method)
            dockerCmd = "docker run -d --name " + container.cname + " -e MYSQL_ROOT_PASSWORD=mysecretpassword mysql"
        elif container.ctype == ContainerType.TOMCAT:
            xenrt.TEC().logverbose("Create Tomcat Container using %s way" % method)
            dockerCmd = "docker run -d --name " + container.cname + " -p 8080:8080 -it tomcat"
        elif container.ctype == ContainerType.UBUNTU:
            xenrt.TEC().logverbose("Create Ubuntu Container using %s way" % method)
            dockerCmd = "docker run -d --name " + container.cname + " ubuntu:14.04 /bin/echo \"Hello world\""
        else:
            raise xenrt.XRTError("Docker container type %s is not recognised" % container.ctype)

        if method==OperationMethod.XAPI:
            return "'" + dockerCmd + "'"
        elif method==OperationMethod.LINUX:
            return dockerCmd
        else:
            raise xenrt.XRTError("Operation method %s in defined" % method)

    def prepareToRemoveContainer(self, container):
        """Check the state of the container before removing it"""

        containerState = self.statusContainer(container)

        if containerState == ContainerState.RUNNING:
            self.stopContainer(container)
            return True
        elif containerState == ContainerState.PAUSED:
            self.unpauseContainer(container)
            self.stopContainer(container)
            return True
        else:
            return False

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
            #dockerCmd ="\"docker ps -a -f name=\'" + container.cname + "\' | tail -n +2 | awk \'{print \$1}\' | xargs docker rm\""
            dockerCmd ="\"docker rm " + container.cname + "\""
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

        if not "This call is only enabled when in dev mode" in result and len(result) == 64:
            # Inspect the container and fill more details, if required.
            return container
        else:
            raise xenrt.XRTError("createContainer:%s failed. This call is only enabled when in dev mode" % container.cname)

    def rmContainer(self, container):

        if self.prepareToRemoveContainer(container):
            return self.containerXapiOtherOperation(container, ContainerXapiOperation.REMOVE)
        else:
            raise xenrt.XRTError("rmContainer: The container %s is in a bad state. Can not be removed" %
                                                                                            container.cname)

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

        dockerContainerList = self.getDockerPS() # returns an ordered list of dicts.

        containers = []

        for containerEntry in dockerContainerList:
            if containerEntry.has_key('entry'):
                containerDict = containerEntry['entry']
                if containerDict.has_key('names'):
                    containers.append(containerDict['names'].strip())
                else:
                    xenrt.TEC().logverbose("listContainers: The container =names= could not accessed")
            else:
                xenrt.TEC().logverbose("listContainers: The container =entry= could not accessed")

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

        if dockerGeneralDict and dockerGeneralDict.has_key(dcommand) and dockerGeneralDict[dcommand]:
            return dockerGeneralDict[dcommand]
        else:
            xenrt.TEC().logverbose("dockerGeneralInfo: Returned empty for %s command" % dcommand)
            return {} # return empty dict.

    def getDockerInfo(self):
        """Returns a dictionary of docker environment information"""

        return self.dockerGeneralInfo('docker_info')

    def getDockerPS(self):
        """Returns an ordered list of dictionary of containers"""

        dockerPS = self.dockerGeneralInfo('docker_ps')

        if not dockerPS.has_key('item'):
            xenrt.TEC().logverbose("getDockerPS: Failed to find key =item= in docker_ps xml")
            return []

        dockerContainerInfo = dockerPS['item']

        if isinstance(dockerContainerInfo,dict):
            return [dockerContainerInfo] # one container -> retruns a dict.
        elif isinstance(dockerContainerInfo,list):
            return dockerContainerInfo # more than one container returns a list of ordered dicts.
        else:
            xenrt.TEC().logverbose("getDockerPS: dockerContainerInfo instance is not recognised")
            return []

    def getDockerVersion(self):
        """Returns the running docker version"""

        dockerVersionDict = self.dockerGeneralInfo('docker_version')

        if dockerVersionDict.has_key('Version'): # has other keys such as KernelVersion, ApiVersion, GoVersion etc.
            return dockerVersionDict['Version']
        else:
            xenrt.TEC().logverbose("getDockerVersion: Version key is missing in docker_version xml")
            return "Unknown"

class LinuxDockerController(DockerController):

    def dockerGeneralInfo(self, dcommand):

        cmd = self.guest.execguest(dcommand).strip()
        dockerGeneralList = cmd.splitlines()

        if len(dockerGeneralList) < 1:
            raise xenrt.XRTError("dockerGeneralInfo: General docker info for %s is not found" % dcommand)

        # In case of 'docker info', remove an element which 
        # starts with ID: VGOY:XML7:MTG5:MG2T:4QAH:5STJ:T3VJ:HD4W:O36M:DEKA:A6IE:PJF7
        dockerGeneralList = [item for item in dockerGeneralList if not item.startswith('ID:')]

        dockerGeneralDict = dict(item.split(":") for item in dockerGeneralList)

        if not dockerGeneralDict:
            raise xenrt.XRTError("getDockerVersion: Unable to obtain docker version")
        else:
            return dockerGeneralDict

    def containerLinuxLCOperation(self, operation, container):

        dockerCmd = "docker " + operation + " " + container.cname
        cmdOut = self.guest.execguest(dockerCmd).strip() # busybox31d3c2d2\n

        if operation not in [ContainerLinuxOperation.INSPECT, ContainerLinuxOperation.REMOVE]:
            if cmdOut == container.cname:
                return True
            else:
                raise xenrt.XRTFailure("XSContainer:%s operation on %s:%s is failed" %
                                                (operation, self.guest, container.cname))
        else:
            return cmdOut # inspect returns a json. remove returns container name.

    def createContainer(self, container):

        dockerCmd = self.containerSelection(container, OperationMethod.LINUX)

        cmdOut = self.guest.execguest(dockerCmd).strip() # 817d4deb9ad84092ee97d9e090732fe335e428e960e8ccc0829a768ad9c92a3c\n

        if cmdOut.isalnum() and len(cmdOut) == 64:
            # Fill more container details, if required.
            return container
        else:
            raise xenrt.XRTError("createContainer: Failed to create a container " + container.cname) 

    def rmContainer(self, container):

        if self.prepareToRemoveContainer(container):
            return self.containerLinuxLCOperation(ContainerLinuxOperation.REMOVE, container)
        else:
            raise xenrt.XRTError("rmContainer: The container %s is in a bad state. Can not be removed" %
                                                                                            container.cname)

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

    def getDockerInfo(self):
        return self.dockerGeneralInfo('docker info')

    def getDockerPS(self):
        dockerCmd = "docker ps -a | tail -n +2 | awk '{print $NF}'"
        containerInfo = self.guest.execguest(dockerCmd).strip()

        if containerInfo:
            containerList = containerInfo.splitlines()
            return containerList # [containername]
        else:
            raise xenrt.XRTError("getDockerPS: There are no containers available to list")

    def getDockerVersion(self):
        dockerVersionDict = self.dockerGeneralInfo('docker version')

        if dockerVersionDict.has_key('Client version'):
            return dockerVersionDict['Client version'].strip()
        else:
            raise xenrt.XRTError("getDockerVersion: Client version key is missing in docker version dict")

    def listContainers(self):
        return self.getDockerPS()

    def gettopContainer(self, container): pass
    def restartContainer(self, container): pass


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
        self.updateGuestSourceRpms()
        self.installDocker()
        self.checkDocker()
        self.enabledPassthroughPlugin() # on host to create containers using Xapi.
        self.registerGuest() # Register VM for XenServer container management.

    def installDocker(self): pass
    def updateGuestSourceRpms(self): pass

    def registerGuest(self):
        """Register VM for XenServer container management"""

        xenrt.TEC().logverbose("registerGuest: Register a guest %s for container monitoring" % self.guest)

        if self.guest.distro.startswith("coreos"):
            self.host.execdom0("xe host-call-plugin host-uuid=%s plugin=xscontainer fn=register args:vmuuid=%s" %
                                                                    (self.host.getMyHostUUID(), self.guest.getUUID()))
        else:
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

    def checkDocker(self):
        """Check for a working docker install"""

        xenrt.TEC().logverbose("checkDocker: Checking the installation of Docker on guest %s" % self.guest)

        guestCmdOut = self.guest.execguest("docker run hello-world").strip() 

        if "Hello from Docker" in guestCmdOut:
            xenrt.TEC().logverbose("Docker installation is running on guest %s" % self.guest)
        else: 
            raise xenrt.XRTError("Failed to find a running instance of Docker on guest %s" % self.guest)

    def enabledPassthroughPlugin(self): 
        """Workaround in Dom0 to enable the passthrough plugin to create docker container"""

        xenrt.TEC().logverbose("enabledPassthroughPlugin: XSContainer passthrough plugin in Dom0 is enabled to create docker containers")

        for host in self.host.getPool().getHosts(): # all hosts in a pool.
            host.execdom0("mkdir -p /opt/xensource/packages/files/xscontainer")
            host.execdom0("touch /opt/xensource/packages/files/xscontainer/devmode_enabled")

    def createContainer(self, ctype=ContainerType.HW_BUSYBOX, cname="random"):
        if cname.startswith("random"):
            cname = "%s%08x" % (ctype, (random.randint(0, 0x7fffffff)))
        container = Container(ctype, cname)
        self.containers.append(self.DockerController.createContainer(container))
        return container

    def rmContainer(self, container):
        containerName = self.DockerController.rmContainer(container)
        if containerName == container.cname:
            self.containers.remove(container)
        else:
            raise xenrt.XRTFailure("rmContainer: xscContainer remove operation failed on %s" %
                                                                                    container.cname)

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
        for cname in self.listContainers():
            self.containers.append(Container(ContainerType.UNKNOWN, cname))

    def listContainers(self):
        return self.DockerController.listContainers() # list of containers.

    def numberOfContainers(self):
        return(len(self.listContainers()))

    def lifeCycleAllContainers(self):
        """Life Cycle operations on all containers in docker environment"""
        """Life Cycle method on all containers"""

        [self.lifeCycleContainer(container) for container in self.containers]

    def stopAllContainers(self):
        """Stop all containers in docker environment"""

        for container in self.containers:
            self.stopContainer(container)
            xenrt.sleep(5)

    def startAllContainers(self):
        """Start all containers in docker environment"""

        for container in self.containers:
            self.startContainer(container)
            xenrt.sleep(5)

    def rmAllContainers(self):
        """Remove all containers in docker environment"""

        while len(self.containers):
            self.rmContainer(self.containers[0])

    def lifeCycleContainer(self, container):
        """Life Cycle method on a specified container in docker environment"""

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

        xenrt.TEC().logverbose("installDocker: CoreOS guest %s has the docker environment by default" % self.guest)

    def updateGuestSourceRpms(self):
        xenrt.TEC().logverbose("updateGuestSourceRpms: Update on CoreOS %s is not required" % self.guest)

class CentOSDocker(Docker):
    """Represents a docker integrated in centos guest"""

    def installDocker(self):

        xenrt.TEC().logverbose("installDocker: Installation of docker environment on guest %s" % self.guest)
        self.guest.execguest("yum install -y nmap-ncat docker")

        # Make sure the docker is running.
        self.guest.execguest("systemctl enable docker")
        cmdOut = self.guest.execguest("service docker restart")

    def updateGuestSourceRpms(self):

        xenrt.TEC().logverbose("updateGuestSourceRpms: Updating source rpms before docker installation on %s" % self.guest)
        self.guest.execguest("mv /etc/yum.repos.d/CentOS-Base.repo.orig /etc/yum.repos.d/CentOS-Base.repo")

class DebianBasedDocker(Docker): # Debain and Ubuntu.
    """Represents a docker installed on debian guest"""

    def installDocker(self):

        xenrt.TEC().logverbose("installDocker: Installation of docker environment on guest %s" % self.guest)
        self.guest.execguest("apt-get -y --force-yes install nmap docker.io")

    def updateGuestSourceRpms(self):

        xenrt.TEC().logverbose("updateGuestSourceRpms: Update on Debian %s is not required" % self.guest)
