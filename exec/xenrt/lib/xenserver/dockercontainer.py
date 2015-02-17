# XenRT: Test harness for Xen and the XenServer product family
#
# Docker container class.
#
# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt, string, random
import xmltodict

__all__ = ["ContainerCreateMethod",
            "ContainerState", "ContainerOperations", "ContainerNames",
            "UsingXapi", "UsingCoreOS", "GenericContainer"]

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
    BUSYBOX = "hadoop"
    MYSQL = "mysql"
    TOMCAT = "tomcat"

"""
Using Bridge pattern to realise the docker feature testing.
"""

# Implementor
class ContainerController(object):

    def containerSelection(self, ctype, cname):

        if not cname:
            cname = "%s_%08x" % (ctype, (random.randint(0, 0x7fffffff)))

        if ctype == ContainerNames.BUSYBOX:
            xenrt.TEC().logverbose("Create BusyBox Container using Xapi")
            return "'docker run -d --name " + cname + " busybox /bin/sh -c \"while true; do echo Hello World; sleep 1; done\"'"
        elif ctype == ContainerNames.MYSQL:
            xenrt.TEC().logverbose("Create MySQL Container using Xapi")
            return "'docker run -d --name " + cname + " -e MYSQL_ROOT_PASSWORD=mysecretpassword mysql'"
        elif ctype == ContainerNames.TOMCAT: 
            xenrt.TEC().logverbose("Create Tomcat Container using Xapi")
            return "'docker run -d --name " + cname + " -p 8080:8080 -it tomcat'"
        else:
            raise xenrt.XRTFailure("Docker container type %s is not recognised" % ctype)

    def registerContainer(self, ctype, host, guest): pass

    def createContainer(self, ctype, host, guest): pass
    def removeContainer(self, ctype, host, guest): pass
    def checkContainer(self, ctype, host, guest): pass

    # Other functions.
    def startContainer(self, ctype, host, guest): pass
    def stopContainer(self, ctype, host, guest): pass
    def pauseContainer(self, ctype, host, guest): pass
    def unpauseContainer(self, ctype, host, guest): pass
    def restartContainer(self, ctype, host, guest): pass

    def inspectContainer(self, ctype, host, guest): pass
    def gettopContainer(self, ctype, host, guest): pass
    def statusContainer(self, ctype, host, guest): pass

    # Other functions.
    def getDockerInfo(self, ctype, host, guest): pass
    def getDockerPS(self, ctype, host, guest): pass
    def getDockerVersion(self, ctype, host, guest): pass
    def getDockerOtherConfig(self, ctype, host, guest): pass

# ConcreteImplementor to create containers using Xapi.
class UsingXapi(ContainerController):

    def workaroundInDom0(self, host): 
        """Workaround in Dom0 to enable the passthrough command so that we can create docker container"""

        host.execdom0("mkdir -p /opt/xensource/packages/files/xscontainer")
        host.execdom0("touch /opt/xensource/packages/files/xscontainer/devmode_enabled")

        xenrt.TEC().logverbose("XSContainer passthrough command is enabled")

    def containerXapiLCOperations(self, operation, host, guest, ctype, cname):

        args = []
        args.append("plugin=xscontainer")
        args.append("fn=%s" % operation)
        args.append("args:vmuuid=%s" % guest.getUUID())
        if operation not in [ContainerOperations.INSPECT, ContainerOperations.GETTOP]:
            args.append("args:container=%s" % ctype)
        else:
            args.append("args:object=%s" % ctype)

        cli = host.getCLIInstance()
        result = cli.execute("host-call-plugin", "%s host-uuid=%s" %
                                (string.join(args), host.getMyHostUUID()))

        #xenrt.TEC().logverbose("containerXapiLCOperations - Result: %s" % result)

        if result[:4] == "True" and result[4:] == None: # True and None -> Failure.
                                                        # True with some docker uuid's is a success.
            raise xenrt.XRTFailure("XSContainer:%s operation on %s:%s is failed" %
                                                                (operation, guest, cname))
        else:
            return result[4:] # stop , start, pause, unpause, retruns empty string.
                              # inspect and gettop leaves an xml.

    def createAndRemoveContainer(self, host, guest, ctype, cname, operation=ContainerOperations.CREATE):

        # Enable the passthrough command in Dom0.
        self.workaroundInDom0(host)

        if operation == ContainerOperations.CREATE:
            dockerCmd = self.containerSelection(ctype, cname)
        elif operation == ContainerOperations.REMOVE:
            dockerCmd ="\"docker ps -a -f name=\'" + ctype + "\' | tail -n +2 | awk \'{print \$1}\' | xargs docker rm\""
        else:
            raise xenrt.XRTFailure("XSContainer:%s operation is not recognised" % operation)

        args = []
        args.append("plugin=xscontainer")
        args.append("fn=passthrough")
        args.append("args:vmuuid=%s" % guest.getUUID())
        args.append("args:command=%s" % dockerCmd)

        cli = host.getCLIInstance()
        result = cli.execute("host-call-plugin", "host-uuid=%s %s " %
                                (host.getMyHostUUID(), string.join(args)))

        #xenrt.TEC().logverbose("createAndRemoveContainer - Result: %s" % result)

        if result[:4] == "True" and result[4:] == None:
            raise xenrt.XRTError("XSContainer:%s Operation failed on a container %s using %s:%s" %
                                                                        (operation, cname, host, guest))
        else:
            return result[4:] # create and remove returns some docker uuid's.

    def registerContainer(self, host, guest, ctype, cname):
        self.containerXapiLCOperations(ContainerOperations.REGISTER, host, guest, ctype, cname)

    def createContainer(self, host, guest, ctype, cname):
        result = self.createAndRemoveContainer(host, guest, ctype, cname)

        xenrt.TEC().logverbose("createContainer - result: %s" % result)

    def removeContainer(self, host, guest, ctype, cname):
        if self.statusContainer(host, guest, ctype, cname) == ContainerState.STOPPED:
            self.createAndRemoveContainer(host, guest, ctype, cname, ContainerOperations.REMOVE)
        else:
            raise xenrt.XRTError("removeContainer: Please stop the container %s before removing it" % cname)

    def checkContainer(self, host, guest, ctype, cname):
        pass

    # Container lifecycle operations.
    def startContainer(self, host, guest, ctype, cname):
        if self.statusContainer(ctype, cname, host, guest) == ContainerState.STOPPED:
            self.containerXapiLCOperations(ContainerOperations.START, host, guest, ctype, cname)
        else:
            raise xenrt.XRTError("startContainer: Container %s can be started if stopped" % cname)

    def stopContainer(self, host, guest, ctype, cname):
        if self.statusContainer(host, guest, ctype, cname) == ContainerState.RUNNING:
            self.containerXapiLCOperations(ContainerOperations.STOP, host, guest, ctype, cname)
        else:
            raise xenrt.XRTError("stopContainer: Container %s can be stopped if running" % cname)

    def pauseContainer(self, host, guest, ctype, cname):
        if self.statusContainer(ctype, cname, host, guest) == ContainerState.RUNNING:
            self.containerXapiLCOperations(ContainerOperations.PAUSE, host, guest, ctype, cname)
        else:
            raise xenrt.XRTError("pauseContainer: Container %s can be paused if running" % cname)

    def unpauseContainer(self, host, guest, ctype, cname):
        if self.statusContainer(host, guest, ctype, cname) == ContainerState.PAUSED:
            self.containerXapiLCOperations(ContainerOperations.UNPAUSE, host, guest, ctype, cname)
        else:
            raise xenrt.XRTError("pauseContainer: Container %s can be unpaused if paused" % cname)

    def restartContainer(self, host, guest, ctype, cname):
        raise xenrt.XRTError("XENAPI: host-call-plugin call restart is not supported")

    def inspectContainer(self, host, guest, ctype, cname):
        dockerInspectXML = self.containerXapiLCOperations(ContainerOperations.INSPECT, host, guest, ctype, cname)

        #xenrt.TEC().logverbose("inspectContainer - dockerInspectXML: %s" % dockerInspectXML)

        dockerInspectDict = xmltodict.parse(dockerInspectXML)

        if not dockerInspectDict.has_key('docker_inspect'):
                raise xenrt.XRTError("inspectContainer: XSContainer - get_inspect failed to get the xml")
        else:
            return dockerInspectDict['docker_inspect']# has keys State, NetworkSettings, Config etc.

    def gettopContainer(self, host, guest, ctype, cname):
        dockerGetTopXML = self.containerXapiLCOperations(ContainerOperations.GETTOP, host, guest, ctype, cname)

        xenrt.TEC().logverbose("gettopContainer - dockerGetTopXML: %s" % dockerGetTopXML)

        dockerGetTopDict = xmltodict.parse(dockerGetTopXML)

        if not dockerGetTopDict.has_key('docker_top'):
                raise xenrt.XRTError("gettopContainer: XSContainer - docker_top failed to get the xml")
        else:
            return dockerGetTopDict['docker_top']# has keys Process etc.

    def statusContainer(self, host, guest, ctype, cname):

        inspectXML = self.inspectContainer(host, guest, ctype, cname)

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

    # Other functions.
    def getDockerInfo(self, host, guest, ctype, cname):pass
    def getDockerPS(self, host, guest, ctype, cname):pass
    def getDockerVersion(self, host, guest, ctype, cname):pass
    def getDockerOtherConfig(self, host, guest, ctype, cname):pass

# ConcreteImplementor to create containers using CoreOS.
class UsingCoreOS(ContainerController):

    def registerContainer(self, host, guest, ctype, cname):pass

    def createContainer(self, host, guest, ctype, cname):
        guest.execguest(self.containerSelection(ctype, cname))

    def removeContainer(self, host, guest, ctype, cname):pass

    def checkContainer(self, host, guest, ctype, cname):pass

    # Container lifecycle operations.
    def startContainer(self, host, guest, ctype, cname):pass
    def stopContainer(self, host, guest, ctype, cname):pass
    def pauseContainer(self, host, guest, ctype, cname):pass
    def unpauseContainer(self, host, guest, ctype, cname):pass
    def restartContainer(self, host, guest, ctype, cname):pass

    def inspectContainer(self, ctype, cname, host, guest):
        return "To be implemented"
    def gettopContainer(self, host, guest, ctype, cname):
        return "To be implemented"
    def statusContainer(self, host, guest, ctype, cname):
        return "To be implemented"

    # Other functions.
    def getDockerInfo(self, host, guest, ctype, cname):pass
    def getDockerPS(self, host, guest, ctype, cname):pass
    def getDockerVersion(self, host, guest, ctype, cname):pass
    def getDockerOtherConfig(self, host, guest, ctype, cname):pass

# Abstraction
class Container(object):

    def create(self): pass
    def remove(self): pass
    def check(self): pass

    def start(self): pass
    def stop(self): pass
    def pause(self): pass
    def unpause(self): pass
    def restart(self): pass

    def inspect(self): pass
    def getTop(self): pass
    def getPS(self): pass
    def getVersion(self): pass
    def getOtherConfig(self): pass

# Refined Abstraction
class GenericContainer(Container):

    def __init__(self, ContainerController, host, guest, ctype, cname="random"):
        self.ctype = ctype
        self.cname = cname
        self.host = host
        self.guest =guest
        self.ContainerController = ContainerController()
 
    def create(self):
        self.ContainerController.createContainer(self.host, self.guest, self.ctype, self.cname)
    def remove(self):
        self.ContainerController.removeContainer(self.host, self.guest, self.ctype, self.cname)
    def check(self):
        self.ContainerController.checkContainer(self.host, self.guest, self.ctype, self.cname)

    # Container lifecycle operations.
    def start(self):
        self.ContainerController.startContainer(self.host, self.guest, self.ctype, self.cname)
    def stop(self):
        self.ContainerController.stopContainer(self.host, self.guest, self.ctype, self.cname)
    def pause(self):
        self.ContainerController.pauseContainer(self.host, self.guest, self.ctype, self.cname)
    def unpause(self):
        self.ContainerController.unpauseContainer(self.host, self.guest, self.ctype, self.cname)
    def restart(self):
        self.ContainerController.restartContainer(self.host, self.guest, self.ctype, self.cname)

    # Other functions.
    def inspect(self):
        return self.ContainerController.inspectContainer(self.host, self.guest, self.ctype, self.cname)
    def getTop(self):
        self.ContainerController.gettopContainer(self.host, self.guest, self.ctype, self.cname)
    def getState(self):
        return self.ContainerController.statusContainer(self.host, self.guest, self.ctype, self.cname)

    def getInfo(self):
        self.ContainerController.getDockerInfo(self.host, self.guest, self.ctype, self.cname)
    def getPS(self):
        self.ContainerController.getDockerPS(self.host, self.guest, self.ctype, self.cname)
    def getVersion(self):
        self.ContainerController.getDockerVersion(self.host, self.guest, self.ctype, self.cname)
    def getOtherConfig(self):
        self.ContainerController.getDockerOtherConfig(self.host, self.guest, self.ctype, self.cname)
