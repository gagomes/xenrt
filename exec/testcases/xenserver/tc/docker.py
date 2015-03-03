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

        self.guests = [] # more guests can be managed.
        args = self.parseArgsKeyValue(arglist) 
        self.distro = args.get("coreosdistro", "coreos-alpha") 

        # Obtain the pool object to retrieve its hosts. 
        self.pool = self.getDefaultPool() 
        if self.pool is None: 
            self.host = self.getDefaultHost() 
        else: 
            self.host = self.pool.master 

        # Obtain the CoreOS guest object. 
        self.guest = self.getGuest(self.distro)
        self.guests.append(self.guest)

        # Obtain the docker environment to work with Xapi plugins.
        self.docker = self.guest.getDocker() # OR CoreOSDocker(self.host, self.coreos, XapiPluginDockerController)
                                             # OR CoreOSDocker(self.host, self.coreos, LinuxDockerController)

    def run(self, arglist=None):pass

    def postRun(self, arglist=None): 
        """Remove all the created containers""" 
        self.docker.rmAllContainers()

class TCContainerLifeCycle(TCDockerBase):
    """Docker container lifecycle tests"""

    def run(self, arglist=None):

        # Create a container of choice.
        self.docker.createContainer(ContainerType.BUSYBOX) # with default container type and name.
        self.docker.createContainer(ContainerType.TOMCAT)

        # Lifecycle tests on all containers.
        self.docker.lifeCycleAllContainers()

class TCGuestsLifeCycle(TCContainerLifeCycle):
    """Lifecycle tests of guests with docker containers"""

    def run(self, arglist=None):

        xenrt.TEC().logverbose("Guests [having docker containers] Life Cycle Operations...")

        for guest in self.guests:
            self.getLogsFrom(guest)
            guest.shutdown()
            guest.start()
            guest.reboot()
            guest.suspend()
            guest.resume()
            guest.shutdown()

        xenrt.TEC().logverbose("Guests [having docker containers] Migration to slave ...")

        for guest in self.guests:
            self.getLogsFrom(guest)
            guest.migrateVM(host=self.pool.getSlaves()[0], live="true")
            guest.check()

        xenrt.TEC().logverbose("Guests [having docker containers] after Migration - Life Cycle Operations...")

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

    def run(self, arglist=None):

        xenrt.TEC().logverbose("Guests [having docker containers] Life Cycle Operations...")

        for guest in self.guests:
            self.getLogsFrom(guest)
            guest.shutdown()
            guest.start()
            guest.reboot()
            guest.suspend()
            guest.resume()
            guest.shutdown()
            guest.start()

        xenrt.TEC().logverbose("Guests [having docker containers] Migration to slave ...")

        for guest in self.guests:
            self.getLogsFrom(guest)
            guest.migrateVM(host=self.pool.getSlaves()[0], live="true")
            guest.check()

        xenrt.TEC().logverbose("Guests [having docker containers] after Migration - Life Cycle Operations...")

        for guest in self.guests:
            self.getLogsFrom(guest)
            guest.shutdown()
            guest.start()
            guest.reboot()
            guest.suspend()
            guest.resume()
            guest.shutdown()

class TCScaleContainers(TCDockerBase):
    """Number of docker containers that can be managed in XenServer"""

    def run(self, arglist=None):
        count = 0
        try:
            while True:
                self.docker.createContainer(ContainerType.YES_BUSYBOX)
                count = count + 1
        except xenrt.XRTFailure, e:
            if count > 0: # one or more containers created.
                xenrt.TEC().logverbose("The number of docker containers created = %s" % count)
                # Lifecycle tests on all containers.
                self.docker.lifeCycleAllContainers()
            else:
                raise xenrt.XRTError(e.reason)
