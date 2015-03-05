# XenRT: Test harness for Xen and the XenServer product family
#
# Docker feature tests.
#
# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt, xenrt.lib.xenserver
from xenrt.lib.xenserver.docker import *

class TCDockerBase(xenrt.TestCase):

    def prepare(self, arglist=None):

        # Obtain the pool object to retrieve its hosts. 
        self.pool = self.getDefaultPool() 

        self.guests = [] # more guests can be managed.
        args = self.parseArgsKeyValue(arglist) 
        self.distro = args.get("distro", "coreos-alpha") 

        i = 0
        while True:
            guest = self.getGuest("%s-%d" % (self.distro, i))
            if not guest:
                break
            self.guests.append(guest)
            i = i + 1

        if len(self.guests) < 1:
            raise xenrt.XRTFailure("There are no guests in the pool to continue the test")

        # Obtain the docker environment to work with Xapi plugins.
        self.docker = [] # for every guest, we need a docker environment.
        for guest in self.guests:
            self.docker.append(guest.getDocker()) # by default method=OperationMethod.XAPI else OperationMethod.LINUX
                                                  # OR CoreOSDocker(guest.getHost(), guest, XapiPluginDockerController)
                                                  # OR CoreOSDocker(guest.getHost(), guest, LinuxDockerController)

    def run(self, arglist=None):pass

    def postRun(self, arglist=None): 
        """Remove all the created containers""" 
        for docker in self.docker:
            docker.rmAllContainers()

class TCContainerLifeCycle(TCDockerBase):
    """Docker container lifecycle tests"""

    def createDockerContainers(self):
        # Create a container of choice in every guest.
        for docker in self.docker:
            #docker.createContainer(ContainerType.BUSYBOX) # with default container type and name.
            docker.createContainer(ContainerType.YES_BUSYBOX)
            docker.createContainer(ContainerType.YES_BUSYBOX)
            docker.createContainer(ContainerType.YES_BUSYBOX)

        # Lifecycle tests on all containers in every guest.
        for docker in self.docker:
            docker.lifeCycleAllContainers()

    def run(self, arglist=None):
        self.createDockerContainers()

class TCContainerVerification(TCDockerBase):
    """Creation and deletion of containers from Docker environment and its verification in XS environment"""

    def run(self, arglist=None):

        linDocker = []

        for guest in self.guests:
            # Creation some containers in Docker environment.
            d = guest.getDocker(OperationMethod.LINUX)

            d.createContainer(ContainerType.YES_BUSYBOX)
            d.createContainer(ContainerType.YES_BUSYBOX)
            d.createContainer(ContainerType.YES_BUSYBOX)

            linDocker.append(d)

        # Check these containers appeared in XS.
        for docker in self.docker:
            xenrt.TEC().logverbose(" LOG %s" % docker.getDockerPS())

class TCGuestsLifeCycle(TCContainerLifeCycle):
    """Lifecycle tests of guests with docker containers"""

    def run(self, arglist=None):

        # Create enough containers in every guests.
        self.createDockerContainers()

        xenrt.TEC().logverbose("Guests [having docker containers] Life Cycle Operations...")

        for guest in self.guests:
            self.getLogsFrom(guest)
            guest.shutdown()
            guest.start()
            guest.reboot()
            guest.suspend()
            guest.resume()
            guest.shutdown()

class TCGuestsMigration(TCContainerLifeCycle):
    """Lifecycle tests of guests with docker containers"""

    def migrationDockerGuest(self, host):
        for guest in self.guests:
            self.getLogsFrom(guest)
            guest.migrateVM(host=host, live="true")
            guest.check()

    def lifeCycleDockerGuest(self):
        for guest in self.guests:
            self.getLogsFrom(guest)
            guest.shutdown()
            guest.start()
            guest.reboot()
            guest.suspend()
            guest.resume()
            guest.shutdown()
            guest.start()

    def run(self, arglist=None):

        # Create enough containers in every guests.
        self.createDockerContainers()

        xenrt.TEC().logverbose("Guests [having docker containers] Migration tests ...")

        xenrt.TEC().logverbose("Life Cycle Operations...")
        self.lifeCycleDockerGuest()

        xenrt.TEC().logverbose("Migration to slave ...")
        self.migrationDockerGuest(self.pool.getSlaves()[0])

        xenrt.TEC().logverbose("After Migration - Life Cycle Operations...")
        self.lifeCycleDockerGuest()

        xenrt.TEC().logverbose("Migration back to master ...")
        self.migrationDockerGuest(self.pool.master)

        xenrt.TEC().logverbose("Again Life Cycle Operations...")
        self.lifeCycleDockerGuest()

class TCScaleContainers(TCDockerBase):
    """Number of docker containers that can be managed in XenServer"""

    def run(self, arglist=None):

        for docker in self.docker:
            count = 0
            try:
                while True:
                    docker.createContainer(ContainerType.YES_BUSYBOX)
                    count = count + 1
            except xenrt.XRTFailure, e:
                if count > 0: # one or more containers created.
                    xenrt.TEC().logverbose("The number of docker containers created = %s" % count)
                    # Lifecycle tests on all containers.
                    #docker.lifeCycleAllContainers()
                else:
                    raise xenrt.XRTError(e.reason)
