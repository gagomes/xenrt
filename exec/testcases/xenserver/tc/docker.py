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

        if self.pool is None:
            self.host = self.getDefaultHost()
        else:
            self.host = self.pool.master

        # Obtain all docker guests from the pool.
        self.guests = [ xenrt.TEC().registry.guestGet(x) for x in self.host.listGuests() ]

        if len(self.guests) < 1:
            raise xenrt.XRTFailure("There are no guests in the pool to continue the test")

        self.docker = [] # for every guest, we need a docker environment.

        # Docker environment can be obtained in 2 ways using guest.getDocker(method)
        # By default method=OperationMethod.XAPI else OperationMethod.LINUX
        [self.docker.append(guest.getDocker()) for guest in self.guests]

    def run(self, arglist=None):pass

    def postRun(self, arglist=None): 
        """Remove all the created containers""" 

        [docker.rmAllContainers() for docker in self.docker]

class TCContainerLifeCycle(TCDockerBase):
    """Docker container lifecycle tests"""

    NO_OF_CONTAINERS = 5

    def createDockerContainers(self):

        # Create some containers (say 5) of your choice in every guest.
        [docker.createContainer(ContainerType.YES_BUSYBOX) for cnum in range(self.NO_OF_CONTAINERS) for docker in self.docker]

        # Lifecycle tests on all containers in every guest.
        [docker.lifeCycleAllContainers() for docker in self.docker]

    def run(self, arglist=None):
        self.createDockerContainers()

class TCContainerVerification(TCDockerBase):
    """Creation and deletion of containers from Docker environment and its verification in XS environment"""

    NO_OF_CONTAINERS = 5

    def run(self, arglist=None):

        # Creation some containers in every guest by SSHing into it. (We call it as LINUX way.)
        dockerLinux = [guest.getDocker(OperationMethod.LINUX) for guest in self.guests]

        # Also, create some simple busybox containers in every guest.
        [dl.createContainer(ContainerType.YES_BUSYBOX) for x in range(self.NO_OF_CONTAINERS) for dl in dockerLinux]

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

        xenrt.TEC().logverbose("Guests [having docker containers] Life Cycle Operations...")
        self.lifeCycleDockerGuest()

class TCGuestsMigration(TCGuestsLifeCycle):
    """Lifecycle and migration tests of guests with docker containers"""

    def migrationDockerGuest(self, host):
        for guest in self.guests:
            self.getLogsFrom(guest)
            guest.migrateVM(host=host, live="true")
            guest.check()

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
            maximumReached = True
            count = 0
            while maximumReached:
                try:
                    docker.createContainer(ContainerType.YES_BUSYBOX)
                    count = count + 1
                except xenrt.XRTFailure, e:
                    maximumReached = False
                    if count > 0: # one or more containers created.
                        xenrt.TEC().logverbose("The number of docker containers created = %s" % count)
                        #docker.lifeCycleAllContainers() - not possible as the system is already out of resource.
                    else:
                        raise xenrt.XRTError(e.reason)

