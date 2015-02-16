# XenRT: Test harness for Xen and the XenServer product family
#
# Docker container class.
#
# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt, string
import xml.dom.minidom, xmltodict

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
    STARTED  = "STARTED"
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
Using Bridge pattern to relaise the docker feature testing.
"""

# Implementor
class ContainerController(object):

    def containerSelection(self, cname):

        if cname == ContainerNames.BUSYBOX:
            xenrt.TEC().logverbose("Create BusyBox Container using Xapi")
            return "'docker run -d --name hadoop busybox /bin/sh -c \"while true; do echo Hello World; sleep 1; done\"'"
        elif cname == ContainerNames.MYSQL:
            xenrt.TEC().logverbose("Create MySQL Container using Xapi")
            return "'docker run -d --name mysql -e MYSQL_ROOT_PASSWORD=mysecretpassword mysql'"
        elif cname == ContainerNames.TOMCAT: 
            xenrt.TEC().logverbose("Create Tomcat Container using Xapi")
            return "'docker run -d --name tomcat -p 8080:8080 -it tomcat'"
        else:
            raise xenrt.XRTFailure("Docker container name is not recognised")

    def registerContainer(self, cname, host, guest): pass

    def createContainer(self, cname, host, guest): pass
    def removeContainer(self, cname, host, guest): pass
    def checkContainer(self, cname, host, guest): pass

    # Other functions.
    def startContainer(self, cname, host, guest): pass
    def stopContainer(self, cname, host, guest): pass
    def pauseContainer(self, cname, host, guest): pass
    def unpauseContainer(self, cname, host, guest): pass
    def restartContainer(self, cname, host, guest): pass

    def inspectContainer(self, cname, host, guest): pass
    def gettopContainer(self, cname, host, guest): pass
    def statusContainer(self, cname, host, guest): pass

    # Other functions.
    def getDockerInfo(self, cname, host, guest): pass
    def getDockerPS(self, cname, host, guest): pass
    def getDockerVersion(self, cname, host, guest): pass
    def getDockerOtherConfig(self, cname, host, guest): pass

# ConcreteImplementor to create containers using Xapi.
class UsingXapi(ContainerController):

    def workaroundInDom0(self, host): 
        """Workaround in Dom0 to enable the passthrough command so that we can create docker container"""

        host.execdom0("mkdir -p /opt/xensource/packages/files/xscontainer")
        host.execdom0("touch /opt/xensource/packages/files/xscontainer/devmode_enabled")

        xenrt.TEC().logverbose("XSContainer passthrough command is enabled")

    def containerXapiLCOperations(self, operation, cname, host, guest):

        args = []
        args.append("plugin=xscontainer")
        args.append("fn=%s" % operation)
        args.append("args:vmuuid=%s" % guest.getUUID())
        if operation not in [ContainerOperations.INSPECT, ContainerOperations.GETTOP]:
            args.append("args:container=%s" % cname)
        else:
            args.append("args:object=%s" % cname)

        cli = host.getCLIInstance()
        result = cli.execute("host-call-plugin", "%s host-uuid=%s" %
                                (string.join(args), host.getMyHostUUID()))

        xenrt.TEC().logverbose("containerXapiLCOperations - Result: %s" % result)

        if not result[:4] == "True":
            raise xenrt.XRTFailure("XSContainer:%s operation on %s:%s is failed" %
                                                                (operation, guest, cname))
        else:
            return result[4:]

    def createAndRemoveContainer(self, operation, cname, host, guest):

        # Enable the passthrough command in Dom0.
        self.workaroundInDom0(host)

        if operation == ContainerOperations.CREATE:
            dockerCmd = self.containerSelection(cname)
        elif operation == ContainerOperations.REMOVE:
            dockerCmd ="\"docker ps -a -f name=\'" + cname + "\' | tail -n +2 | awk \'{print \$1}\' | xargs docker rm\""
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

        xenrt.TEC().logverbose("createAndRemoveContainer - Result: %s" % result)

        if result:
            xenrt.TEC().logverbose("XSContainer:%s Operation succeeded on container %s using %s:%s" %
                                                                        (operation, cname, host, guest))
        else:
            raise xenrt.XRTError("XSContainer:%s Operation failed on a container %s using %s:%s" %
                                                                        (operation, cname, host, guest))

    def registerContainer(self, cname, host, guest):
        self.containerXapiLCOperations(ContainerOperations.REGISTER, cname, host, guest)

    def createContainer(self, cname, host, guest):
        result = self.createAndRemoveContainer(ContainerOperations.CREATE, cname, host, guest)

        xenrt.TEC().logverbose("createContainer - result: %s" % result)

    def removeContainer(self, cname, host, guest):
        self.createAndRemoveContainer(ContainerOperations.REMOVE, cname, host, guest)

    def checkContainer(self, cname, host, guest):
        pass

    # Container lifecycle operations.
    def startContainer(self, cname, host, guest):
        self.containerXapiLCOperations(ContainerOperations.START, cname, host, guest)
    def stopContainer(self, cname, host, guest):
        self.containerXapiLCOperations(ContainerOperations.STOP, cname, host, guest)
    def pauseContainer(self, cname, host, guest):
        self.containerXapiLCOperations(ContainerOperations.PAUSE, cname, host, guest)
    def unpauseContainer(self, cname, host, guest):
        self.containerXapiLCOperations(ContainerOperations.UNPAUSE, cname, host, guest)
    def restartContainer(self, cname, host, guest):
        raise xenrt.XRTError("XENAPI: host-call-plugin call restart is not supported")

    def inspectContainer(self, cname, host, guest):
        dockerInspectXML = self.containerXapiLCOperations(ContainerOperations.INSPECT, cname, host, guest)

        xenrt.TEC().logverbose("inspectContainer - dockerInspectXML: %s" % dockerInspectXML)

        xmldict = xmltodict.

        #xmldoc = xml.dom.minidom.parseString(dockerInspectXML)
        return xmldoc
        #dockerInspect = xmldoc.getElementsByTagName('docker_inspect')

        #if len(dockerInspect) < 1:
        #    raise xenrt.XRTError("inspectContainer: XSContainer - get_inspect returned an empty xml")
        #else:
        #    return dockerInspect[0] # There is only one item in the list.

    def gettopContainer(self, cname, host, guest):
        dockerGetTopXML = self.containerXapiLCOperations(ContainerOperations.GETTOP, cname, host, guest)
        dom = xml.dom.minidom.parseString(dockerGetTopXML)

        xenrt.TEC().logverbose("dockerGetTopXML - xmldoc: %s" % dom)

    def statusContainer(self, cname, host, guest):

        inspectXML = self.inspectContainer(cname, host, guest)
        containerState = inspectXML.getElementsByTagName('State') # There os only one item in the list.

        if len(containerState) < 1:
            raise xenrt.XRTError("statusContainer: XSContainer - get_inspect XML does not have a state item")

        if containerState[0].attributes['Paused'].value == "True":
            return ContainerState.PAUSED
        elif containerState[0].attributes['Restarting'].value == "True":
            return ContainerState.RESTARTED
        elif containerState[0].attributes['Running'].value == "True":
            return ContainerState.STARTED
        if containerState[0].attributes['Paused'].value == "True":
            return ContainerState.PAUSED
        else:
            return ContainerState.UNKNOWN

    # Other functions.
    def getDockerInfo(self, cname, host, guest):pass
    def getDockerPS(self, cname, host, guest):pass
    def getDockerVersion(self, cname, host, guest):pass
    def getDockerOtherConfig(self, cname, host, guest):pass

# ConcreteImplementor to create containers using CoreOS.
class UsingCoreOS(ContainerController):

    def registerContainer(self, cname, host, guest):pass

    def createContainer(self, cname, host, guest):
        guest.execguest(self.containerSelection(cname))

    def removeContainer(self, cname, host, guest):pass

    def checkContainer(self, cname, host, guest):pass

    # Container lifecycle operations.
    def startContainer(self, cname, host, guest):pass
    def stopContainer(self, cname, host, guest):pass
    def pauseContainer(self, cname, host, guest):pass
    def unpauseContainer(self, cname, host, guest):pass
    def restartContainer(self, cname, host, guest):pass

    def inspectContainer(self, cname, host, guest):pass
    def gettopContainer(self, cname, host, guest):pass

    def statusContainer(self, cname, host, guest):pass

    # Other functions.
    def getDockerInfo(self, cname, host, guest):pass
    def getDockerPS(self, cname, host, guest):pass
    def getDockerVersion(self, cname, host, guest):pass
    def getDockerOtherConfig(self, cname, host, guest):pass

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

    def __init__(self, cname, host, guest, ContainerController):
        self.cname = cname
        self.host = host
        self.guest =guest
        self.ContainerController = ContainerController()
 
    def create(self):
        self.ContainerController.createContainer(self.cname, self.host, self.guest)
    def remove(self):
        self.ContainerController.removeContainer(self.cname, self.host, self.guest)
    def check(self):
        self.ContainerController.checkContainer(self.cname, self.host, self.guest)

    # Container lifecycle operations.
    def start(self):
        self.ContainerController.startContainer(self.cname, self.host, self.guest)
    def stop(self):
        self.ContainerController.stopContainer(self.cname, self.host, self.guest)
    def pause(self):
        self.ContainerController.pauseContainer(self.cname, self.host, self.guest)
    def unpause(self):
        self.ContainerController.unpauseContainer(self.cname, self.host, self.guest)
    def restart(self):
        self.ContainerController.restartContainer(self.cname, self.host, self.guest)

    # Other functions.
    def inspect(self):
        self.ContainerController.inspectContainer(self.cname, self.host, self.guest)
    def getTop(self):
        self.ContainerController.gettopContainer(self.cname, self.host, self.guest)
    def getState(self):
        self.ContainerController.statusContainer(self.cname, self.host, self.guest)

    def getInfo(self):
        self.ContainerController.getDockerInfo(self.cname, self.host, self.guest)
    def getPS(self):
        self.ContainerController.getDockerPS(self.cname, self.host, self.guest)
    def getVersion(self):
        self.ContainerController.getDockerVersion(self.cname, self.host, self.guest)
    def getOtherConfig(self):
        self.ContainerController.getDockerOtherConfig(self.cname, self.host, self.guest)
