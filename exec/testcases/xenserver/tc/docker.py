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
        [docker.createContainer(ContainerType.SLEEP_BUSYBOX) for cnum in range(self.NO_OF_CONTAINERS) for docker in self.docker]

    def startAllContainers(self):

        # After a guest reboot/shutdown all the running containers goes offline.
        [docker.startAllContainers() for docker in self.docker]

    def lifeCycleDockerContainers(self):

        # Lifecycle tests on all containers in every guest.
        [docker.lifeCycleAllContainers() for docker in self.docker]

    def run(self, arglist=None):
        xenrt.TEC().logverbose("Create enough containers in every guests")
        self.createDockerContainers()
        xenrt.TEC().logverbose("Perform life cycle operations on all containers")
        self.lifeCycleDockerContainers()

class TCGuestsLifeCycle(TCContainerLifeCycle):
    """Lifecycle tests of guests with docker containers"""

    NO_OF_CONTAINERS = 10

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
            xenrt.sleep(90)

    def run(self, arglist=None):

        xenrt.TEC().logverbose("Create enough containers in every guests")
        self.createDockerContainers()

        xenrt.TEC().logverbose("Perform life cycle operations on all containers")
        self.lifeCycleDockerContainers()

        xenrt.TEC().logverbose("Guests [having docker containers] Life Cycle Operations")
        self.lifeCycleDockerGuest()

        xenrt.TEC().logverbose("Starting containers again which goes offline after a reboot")
        self.startAllContainers()

        xenrt.TEC().logverbose("Perform life cycle operations on all containers after guests reboots")
        self.lifeCycleDockerContainers()

class TCGuestsMigration(TCGuestsLifeCycle):
    """Lifecycle and migration tests of guests with docker containers"""

    NO_OF_CONTAINERS = 5

    def migrationDockerGuest(self, host):
        for guest in self.guests:
            self.getLogsFrom(guest)
            guest.migrateVM(host=host, live="true")
            guest.check()
            xenrt.sleep(60)

    def run(self, arglist=None):

        xenrt.TEC().logverbose("Creating enough containers in every guests during the migration test")
        self.createDockerContainers()

        xenrt.TEC().logverbose("Perform life cycle operations on all containers - (1)")
        self.lifeCycleDockerContainers()

        xenrt.TEC().logverbose("Life Cycle Operations of guest before migrating to slave")
        self.lifeCycleDockerGuest()

        xenrt.TEC().logverbose("Starting containers again which goes offline after a reboot")
        self.startAllContainers()

        xenrt.TEC().logverbose("Perform life cycle operations on all containers - (2)")
        self.lifeCycleDockerContainers()

        xenrt.TEC().logverbose("Migration of guest to slave ...")
        self.migrationDockerGuest(self.pool.getSlaves()[0])

        xenrt.TEC().logverbose("Perform life cycle operations on all containers - (3)")
        self.lifeCycleDockerContainers()

        xenrt.TEC().logverbose("Life Cycle Operations of guest after migrating to slave")
        self.lifeCycleDockerGuest()

        xenrt.TEC().logverbose("Starting containers again which goes offline after a reboot")
        self.startAllContainers()

        xenrt.TEC().logverbose("Perform life cycle operations on all containers - (4)")
        self.lifeCycleDockerContainers()

        xenrt.TEC().logverbose("Migration of guest back to master ...")
        self.migrationDockerGuest(self.pool.master)

        xenrt.TEC().logverbose("Perform life cycle operations on all containers - (5)")
        self.lifeCycleDockerContainers()

        xenrt.TEC().logverbose("Life Cycle Operations of guest after migrating back to master")
        self.lifeCycleDockerGuest()

        xenrt.TEC().logverbose("Starting containers again which goes offline after a reboot")
        self.startAllContainers()

        xenrt.TEC().logverbose("Perform life cycle operations on all containers - (6)")
        self.lifeCycleDockerContainers()

class TCScaleContainers(TCDockerBase):
    """Number of docker containers that can be managed in XenServer"""

    def run(self, arglist=None):

        for docker in self.docker:
            maximumReached = True
            count = 0
            while maximumReached:
                try:
                    docker.createContainer(ContainerType.SLEEP_BUSYBOX)
                    count = count + 1
                except xenrt.XRTFailure, e:
                    maximumReached = False
                    if count > 0: # one or more containers created.
                        xenrt.TEC().logverbose("The number of docker containers created = %s" % count)
                        #docker.lifeCycleAllContainers() - not possible as the system is already out of resource.
                    else:
                        raise xenrt.XRTError(e.reason)

