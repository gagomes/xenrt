# XenRT: Test harness for Xen and the XenServer product family
#
# Docker feature tests.
#
# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt, xenrt.lib.xenserver

import os
import time

class TCDockerMachineLifeCycle(xenrt.TestCase):
    """Docker Machine lifecycle tests"""

    DOCKER_MACHINE_URL = 'https://marvin.do.citrite.net/job/docker-machine-gitlab/lastSuccessfulBuild/artifact/docker-machine_linux-amd64'
    BOOT2DOCKER_URL = 'https://github.com/tianon/boot2docker/releases/download/v1.7.1-rc2/boot2docker.iso'

    def prepare(self, arglist=None):
        # Obtain the pool object to retrieve its hosts.
        self.pool = self.getDefaultPool()
        if self.pool is None:
            self.host = self.getDefaultHost()
        else:
            self.host = self.pool.master
        self.vmname = xenrt.randomGuestName()
        self.command = ''

    def downloadDockerMachineBinary(self):
        xenrt.TEC().logverbose("Download %r" % self.DOCKER_MACHINE_URL)
        self.command = xenrt.TEC().getFile(self.DOCKER_MACHINE_URL)
        try:
            xenrt.checkFileExists(self.command)
        except:
            raise xenrt.XRTFailure("Download %r to %r error" % (self.DOCKER_MACHINE_URL, self.command))
        cmd = 'chmod +x %s' % self.command
        if 0 != xenrt.command(cmd, retval="code"):
            raise xenrt.XRTFailure("Failed to %r" % cmd)
        xenrt.TEC().logverbose("Download %r OK" % self.DOCKER_MACHINE_URL)

    def lifeCycleCreate(self):
        host_ip = self.host.getIP()
        cmd = '%s create --driver xenserver --xenserver-boot2docker-url "%s" --xenserver-server %s --xenserver-username root --xenserver-password xenroot %s 2>&1' % (self.command, self.BOOT2DOCKER_URL, host_ip, self.vmname)
        xenrt.command(cmd, timeout=1800)
        if self.vmname not in self.host.listGuests(running=True):
            raise xenrt.XRTFailure("VM(%r) not running at XenServer %s" % (self.vmname, host_ip))

    def lifeCycleRestart(self):
        cmd = '%s restart %s 2>&1' % (self.command, self.vmname)
        xenrt.command(cmd, timeout=600)
        if self.vmname not in self.host.listGuests(running=True):
            raise xenrt.XRTFailure("VM(%r) not running at XenServer %s" % (self.vmname, host_ip))

    def lifeCycleDockerMachine(self):
        self.lifeCycleCreate()
        self.lifeCycleRestart()

    def run(self, arglist=None):
        self.downloadDockerMachineBinary()
        self.lifeCycleDockerMachine()

