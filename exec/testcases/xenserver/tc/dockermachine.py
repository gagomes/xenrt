# XenRT: Test harness for Xen and the XenServer product family
#
# Docker feature tests.
#
# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt, xenrt.lib.xenserver
from xenrt.lib.xenserver.docker import *

class TCDockerMachineLifeCycle(TCDockerBase):
    """Docker Machine lifecycle tests"""

    # Phus Please modify below 
    NO_OF_CONTAINERS = 5

    def createDockerContainers(self):

        # Create some containers (say 5) of your choice in every guest.
        [docker.createContainer(ContainerType.SLEEP_BUSYBOX) for cnum in range(self.NO_OF_CONTAINERS) for docker in self.docker]

    def lifeCycleDockerContainers(self):

        # Lifecycle tests on all containers in every guest.
        [docker.lifeCycleAllContainers() for docker in self.docker]

    def run(self, arglist=None):
        xenrt.TEC().logverbose("Create enough containers in every guests")
        self.createDockerContainers()
        xenrt.TEC().logverbose("Perform life cycle operations on all containers")
        self.lifeCycleDockerContainers()

