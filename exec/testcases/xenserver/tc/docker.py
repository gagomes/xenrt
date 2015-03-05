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

    NO_OF_CONTAINERS = 5

    def run(self, arglist=None):

        for guest in self.guests:
            # Creation some containers in every guest by SSHing into it. (We call it as LINUX way.)
            dl = guest.getDocker(OperationMethod.LINUX)

            for x in range(self.NO_OF_CONTAINERS): # creat some simple busybox containers.
                dl.createContainer(ContainerType.YES_BUSYBOX)

        # Check these containers appeared in XenServer using Xapi plugins. (We call it as XAPI way.)
        for guest in self.guests:
            dx = guest.getDocker() # by default created as XAPI way.
            dl = guest.getDocker(OperationMethod.LINUX)

            # Firstly, check whether we have the right count.
            if not dx.numberOfContainers() == dl.numberOfContainers():
                raise xenrt.XRTFailure("The number of containers created on %s are not matching when checked through XAPI" % guest)

            # Also, check the containers name matches.
            if not set(dx.listContainers()) == set(dl.listContainers()):
                raise xenrt.XRTFailure("Some containers created on %s are missing when checked through XAPI" % guest)

        # Let us delete all containers using LINUX way.
        for guest in self.guests:
            dl = guest.getDocker(OperationMethod.LINUX)
            dl.loadExistingContainers()
            dl.rmAllContainers()

            dx = guest.getDocker()
            if not dx.numberOfContainers() == 0:
                raise xenrt.XRTFailure("Some containers still exist in %s after removing it through LINUX way" % guest)

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
