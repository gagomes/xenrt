# XenRT: Test harness for Xen and the XenServer product family
#
# Docker container class.
#
# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt, string

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

class ContainerOperations:
    START  = "start"
    STOP  = "stop"
    RESTART = "restarted"
    PAUSE   = "pause"
    UNPAUSE = "unpause"

class ContainerNames:
    BUSYBOX = "busybox"
    MYSQL = "mysql"
    TOMCAT = "tomcat"

"""
Using Bridge pattern to relaise the docker feature testing.
"""

# Implementor
class ContainerController(object):

    def __init__(self, cname, host, guest):
        self.host = host
        self.guest =guest
        self.cname = cname

    def containerSelection(self):
        if self.cname == ContainerNames.BUSYBOX:
            xenrt.TEC().logverbose("Create BusyBox Container using Xapi")
            return "'docker run -d --name hadoop busybox /bin/sh -c \"while true; do echo Hello World; sleep 1; done\"'"
        elif self.cname == ContainerNames.MYSQL:
            xenrt.TEC().logverbose("Create MySQL Container using Xapi")
            return "'docker run -d --name mysql -e MYSQL_ROOT_PASSWORD=mysecretpassword mysql'"
        elif self.cname == ContainerNames.TOMCAT: 
            xenrt.TEC().logverbose("Create Tomcat Container using Xapi")
            return "'docker run -d --name tomcat -p 8080:8080 -it tomcat'"

    def create(self): pass
    def remove(self): pass
    def check(self): pass
    def start(self): pass
    def stop(self): pass
    def restart(self): pass
    def pause(self): pass
    def unpause(self): pass

# ConcreteImplementor to create containers using Xapi.
class UsingXapi(ContainerController):

    def __init__(self, cname, host, guest):
        super(UsingXapi, self).__init__(cname, host, guest)

    def containerXapiOperations(self, operation):

        args = []
        args.append("plugin=xscontainer")
        args.append("fn=%s" % operation)
        args.append("args:vmuuid=%s" % self.guest.getUUID())
        args.append("args:container=%s" % self.cname)

        cli = self.host.getCLIInstance()
        result = cli.execute("host-call-plugin", "%s host-uuid=%s" %
                        (string.join(args), self.host.getMyHostUUID()))

        if result:
            xenrt.TEC().logverbose("Successfully created docker container %s in guest %s" %
                                                                            (self.cname, self.guest))
        else:
            raise xenrt.XRTFailure("Failed to create docker container %s in guest %s" %
                                                                            (self.cname, self.guest))

    def createContainer(self):

        createCmd = self.containerSelection()

        args = []
        args.append("plugin=xscontainer")
        args.append("fn=passthrough")
        args.append("args:vmuuid=%s" % self.guest.getUUID())
        args.append("args:command=%s" % createCmd)

        cli = self.host.getCLIInstance()
        result = cli.execute("host-call-plugin", "%s host-uuid=%s" %
                        (string.join(args), self.host.getMyHostUUID()))

        if result:
            xenrt.TEC().logverbose("Successfully created docker container %s in guest %s" %
                                                                            (self.cname, self.guest))
        else:
            raise xenrt.XRTFailure("Failed to create docker container %s in guest %s" %
                                                                            (self.cname, self.guest))

    def removeContainer(self):
        pass

    def checkContainer(self):
        pass

    def startContainer(self):
        self.containerXapiOperations(ContainerOperations.START)

    def stopContainer(self):
        self.containerXapiOperations(ContainerOperations.STOP)

    def restartContainer(self):
        self.containerXapiOperations(ContainerOperations.RESTART)

    def pauseContainer(self):
        self.containerXapiOperations(ContainerOperations.PAUSE)

    def unpauseContainer(self):
        self.containerXapiOperations(ContainerOperations.UNPAUSE)

# ConcreteImplementor to create containers using CoreOS.
class UsingCoreOS(ContainerController):

    def createContainer(self):
        self.guest.execguest(self.containerSelection())

    def removeContainer(self):pass

    def checkContainer(self):pass

    def startContainer(self):pass

    def stopContainer(self):pass

    def restartContainer(self):pass

    def pauseContainer(self):pass

    def unpauseContainer(self):pass

# Abstraction
class Container(object):

    def create(self): pass
    def remove(self): pass
    def check(self): pass

    def start(self): pass
    def stop(self): pass
    def restart(self): pass
    def pause(self): pass
    def unpause(self): pass

# Refined Abstraction
class GenericContainer(Container):

    def __init__(self, cname, host, guest, ContainerController):
        self.cname = cname
        self.host = host
        self.guest =guest
        self.ContainerController = ContainerController(cname, host, guest)
 
    def create(self):
        self.ContainerController.createContainer()

    def remove(self):
        self.ContainerController.removeContainer()

    def check(self):
        self.ContainerController.checkContainer()

    def start(self):
        self.ContainerController.startContainer()

    def stop(self):
        self.ContainerController.stopContainer()

    def restart(self):
        self.ContainerController.restartContainer()

    def pause(self):
        self.ContainerController.pauseContainer()

    def unpause(self):
        self.ContainerController.unpauseContainer()

