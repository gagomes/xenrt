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

        # Obtain the docker environment to work with Xapi plugins.
        self.docker = self.guest.getDocker() # OR CoreOSDocker(self.host, self.coreos, XapiPluginDockerController)
                                             # OR CoreOSDocker(self.host, self.coreos, LinuxDockerController)

    def run(self, arglist=None):pass

class TCLifeCycle(TCDockerBase):
    """Docker container lifecycle tests"""

    def run(self, arglist=None):

        # Create a container of choice.
        self.docker.createContainer(ContainerType.BUSYBOX) # with default container type and name.
        self.docker.createContainer(ContainerType.TOMCAT)

        # Lifecycle tests on all containers.
        self.docker.lifeCycleAllContainers()

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
