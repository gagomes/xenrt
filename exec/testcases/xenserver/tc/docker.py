# XenRT: Test harness for Xen and the XenServer product family
#
# Docker feature tests.
#
# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt, xenrt.lib.xenserver
from xenrt.lib.xenserver.docker import *

class TCSanityTest(xenrt.TestCase):

    def prepare(self, arglist=None):

        args = self.parseArgsKeyValue(arglist) 
        self.distro = args.get("coreosdistro", "coreos-alpha") 

        # Obtain the pool object to retrieve its hosts. 
        self.pool = self.getDefaultPool() 
        xenrt.TEC().logverbose("self.pool: %s" % self.pool) 
        if self.pool is None: 
            self.host = self.getDefaultHost() 
        else: 
            self.host = self.pool.master 

        # Obtain the CoreOS guest object. 
        self.guest = self.getGuest(self.distro)

        # Obtain the docker environment to work with Xapi plugins.
        self.docker = self.guest.getDocker() # OR CoreOSDocker(self.host, self.coreos, UsingXapi)
                                             # OR CoreOSDocker(self.host, self.coreos, UsingLinux)

        # Register the guest for container monitoring.
        self.docker.registerGuest()

    def run(self, arglist=None):

        # Create a container of choice.
        self.docker.createContainer(ContainerNames.BUSYBOX) # with default container type and name.
        self.docker.createContainer(ContainerNames.MYSQL)
        self.docker.createContainer(ContainerNames.TOMCAT)

        # Lifecycle tests on all containers.
        self.docker.lifeCycleAllContainers()
