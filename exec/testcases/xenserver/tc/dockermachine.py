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

    DOCKER_MACHINE_BINARY = 'https://marvin.do.citrite.net/job/docker-machine-gitlab/lastSuccessfulBuild/artifact/docker-machine_linux-amd64'
    COMMAND = os.path.basename(DOCKER_MACHINE_BINARY)

    def prepare(self, arglist=None):
        # Obtain the pool object to retrieve its hosts.
        self.pool = self.getDefaultPool()
        if self.pool is None:
            self.host = self.getDefaultHost()
        else:
            self.host = self.pool.master
        self.vmname = 'test-%s' % time.strftime('%Y%m%d%H%M%S')

    def downloadDockerMachineBinary(self):
        xenrt.TEC().logverbose("Download %r" % self.DOCKER_MACHINE_BINARY)
        cmd = 'curl -O "%s" 2>&1' % self.DOCKER_MACHINE_BINARY
        data = os.popen(cmd).read()
        xenrt.TEC().logverbose(data)
        if not os.path.exists(self.COMMAND):
            raise xenrt.XRTFailure("Download %r error" % self.COMMAND)
        os.system('/bin/rm -rf ~/.docker')
        os.system('chmod +x ./%s' % self.COMMAND)
        xenrt.TEC().logverbose("Download %r OK" % self.DOCKER_MACHINE_BINARY)

    def lifeCycleCreate(self):
        host_ip = self.host.getIP()
        boot2docker_url = 'https://github.com/tianon/boot2docker/releases/download/v1.7.1-rc2/boot2docker.iso'
        cmd = './%s create --driver xenserver --xenserver-boot2docker-url "%s" --xenserver-server %s --xenserver-username root --xenserver-password xenroot %s 2>&1' % (self.COMMAND, boot2docker_url, host_ip, self.vmname)
        data = os.popen(cmd).read()
        xenrt.TEC().logverbose(data)
        if self.vmname not in self.host.listGuests(running=True):
            raise xenrt.XRTFailure("VM(%r) not running at XenServer %s" % (self.vmname, host_ip))

    def lifeCycleRestart(self):
        cmd = './%s restart %s 2>&1' % (self.COMMAND, self.vmname)
        data = os.popen(cmd).read()
        xenrt.TEC().logverbose(data)
        if self.vmname not in self.host.listGuests(running=True):
            raise xenrt.XRTFailure("VM(%r) not running at XenServer %s" % (self.vmname, host_ip))

    def lifeCycleDockerMachine(self):
        self.lifeCycleCreate()
        self.lifeCycleRestart()

    def run(self, arglist=None):
        self.downloadDockerMachineBinary()
        self.lifeCycleDockerMachine()

