
# XenRT: Test harness for Xen and the XenServer product family
#
# GPU-passthrough test cases
#
# Copyright (c) 2011 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import re
import tempfile
import xmlrpclib
import copy
import os
import string
import xenrt
import time
import testcases.xenserver.tc.security
import testcases.xenserver.tc.ns
from xenrt.lib.xenserver.call import *
from testcases.xenserver.tc.ns import SRIOVTests
from testcases.benchmarks import graphics
from testcases.xenserver.shellcommandsrunner import Runner

class GPUHelper(object):
    """Helper for GPU related operations"""

    def getGPUHosts(self, pool):
        hosts = pool.getHosts()
        return filter((lambda h: len(self.getGPUGroups(h)) > 0), hosts)

    def getGPUGroups(self, host, check=True, workaround=None, vendor=None):
        """return gpu groups available on some host"""
        def isVendor(gpu_group_uuid, allowedVendor):
            cli = host.getCLIInstance()
            vendor = cli.execute(
                "gpu-group-param-get",
                "uuid=%s param-name=name-label" % (gpu_group_uuid)).strip()
            return (allowedVendor in vendor)
        gpu_group_uuids = host.minimalList(
            "pgpu-list",
            args="params=gpu-group-uuid host-uuid=%s" % host.getMyHostUUID())
        if check and len(gpu_group_uuids) < 1:
            raise xenrt.XRTFailure(
                "This host does not contain a GPU group list as expected")
        # ignore Matrox GPUs for TC13532
        if workaround == "WORKAROUND_CA61226":
            gpu_group_uuids = filter(
                lambda u: not isVendor(u, "Matrox"), gpu_group_uuids)
        if vendor:
            gpu_group_uuids = filter(
                lambda u: isVendor(u, vendor), gpu_group_uuids)
        return gpu_group_uuids

    def getGPUGroup(self, host, name):
        for i in host.minimalList("gpu-group-list"):
            if name in host.genParamGet("gpu-group", i, "name-label"):
                return i
        return None

    # python 2.4 does not have this itertools.combinations() function available
    def combinations(self, iterable, r):
        # combinations('ABCD', 2) --> AB AC AD BC BD CD
        # combinations(range(4), 3) --> 012 013 023 123
        pool = tuple(iterable)
        n = len(pool)
        if r > n:
            return
        indices = range(r)
        yield tuple(pool[i] for i in indices)
        while True:
            for i in reversed(range(r)):
                if indices[i] != i + n - r:
                    break
            else:
                return
            indices[i] += 1
            for j in range(i+1, r):
                indices[j] = indices[j-1] + 1
            yield tuple(pool[i] for i in indices)

    def hostsWithCommonGPUGroup(self, hosts):
        if len(hosts) < 2:
            raise xenrt.XRTError(
                "There must be at least 2 gpu hosts in the list")
        hosts_with_common_gpu_group = filter(
            lambda (h0, h1): len(
                self.commonGPUGroups(h0, h1, check=False)) > 0,
            self.combinations(hosts, 2))
        if len(hosts_with_common_gpu_group) < 1:
            raise xenrt.XRTError(
                "There must be at least a pair of hosts"
                " with a common gpu model in the pool")
        return hosts_with_common_gpu_group

    def hostWithExclusiveGPUGroup(self, hosts):
        if len(hosts) < 2:
            raise xenrt.XRTError(
                "There must be at least 2 gpu hosts in the list")
        for host_pair in self.combinations(hosts, 2):
            host0 = host_pair[0]
            host1 = host_pair[1]
            common_gpu_groups = self.commonGPUGroups(host0, host1, check=False)
            h0_gpu_groups = self.getGPUGroups(host0, check=False)
            h1_gpu_groups = self.getGPUGroups(host1, check=False)
            h0_exclusive_gpu_groups = list(
                set(h0_gpu_groups).difference(set(common_gpu_groups)))
            h1_exclusive_gpu_groups = list(
                set(h1_gpu_groups).difference(set(common_gpu_groups)))
            if len(h0_exclusive_gpu_groups) > 0:
                # (from,to,gpu_only_in_from_not_in_to)
                return (host0, host1, h0_exclusive_gpu_groups)
            if len(h1_exclusive_gpu_groups) > 0:
                # (from,to,gpu_only_in_from_not_in_to)
                return (host1, host0, h1_exclusive_gpu_groups)
        raise xenrt.XRTFailure(
            "no host in the pool has any exclusive GPU group")

    def attachGPU(self, vm, gpu_group_uuid):
        host = vm.getHost()
        cli = host.getCLIInstance()
        # assign a vGPU to this VM
        vgpu_uuid = cli.execute(
            "vgpu-create",
            "gpu-group-uuid=%s vm-uuid=%s" % (
                gpu_group_uuid, vm.getUUID())).strip()
        return vgpu_uuid

    def detachGPU(self, vm):
        host = vm.getHost()
        cli = host.getCLIInstance()
        vm_vgpu_uuids = host.minimalList(
            "vgpu-list", args="params=uuid vm-uuid=%s" % vm.getUUID())
        for vm_vgpu_uuid in vm_vgpu_uuids:
            cli.execute("vgpu-destroy", "uuid=%s" % vm_vgpu_uuid)

    def commonGPUGroups(self, host0, host1, check=True):
        h0_gpu_groups = self.getGPUGroups(host0, check)
        h1_gpu_groups = self.getGPUGroups(host1, check)
        gpu_groups = list(set(h0_gpu_groups).intersection(set(h1_gpu_groups)))
        if check and len(gpu_groups) < 1:
            raise xenrt.XRTFailure(
                "host0=%s and host1=%s do not have a common GPU group" % (
                    host0.getMyHostUUID(), host1.getMyHostUUID()))
        return gpu_groups

    def getPGPUs(self, host, gpu_group_uuid):
        """return pgpus available on some host for some gpu group"""
        pgpu_uuids = host.minimalList(
            "pgpu-list", args="gpu-group-uuid=%s host-uuid=%s" % (
                gpu_group_uuid, host.getMyHostUUID()))
        return pgpu_uuids

    def assertGPUPresentInVM(self, vm, vendor=None):
        if not self.findGPUInVM(vm, vendor):
            raise xenrt.XRTFailure(
                "GPU not detected for vm %s: %s" % (
                    vm.getName(), vm.getUUID()))

    def assertGPUAbsentInVM(self, vm, vendor=None):
        if self.findGPUInVM(vm, vendor):
            raise xenrt.XRTFailure(
                "GPU detected when not expected for vm %s: %s" % (
                    vm.getName(), vm.getUUID()))

    def assertGPURunningInVM(self, vm, vendor=None):
        if not self.checkGPURunningInVM(vm, vendor):
            raise xenrt.XRTFailure(
                "GPU not running in VM %s: %s" % (
                    vm.getName(), vm.getUUID()))

    def assertGPUNotRunningInVM(self, vm, vendor=None):
        if self.checkGPURunningInVM(vm, vendor):
            raise xenrt.XRTFailure(
                "GPU running when not expected in VM %s: %s" % (
                    vm.getName(), vm.getUUID()))

    def checkGPURunningInVM(self, vm, vendor=None):
        gpu = self.findGPUInVM(vm, vendor)
        device = "\\".join(gpu.split("\\")[0:2])
        lines = vm.devcon("status \"%s\"" % device).splitlines()
        for l in lines:
            if "Device has a problem" in l:
                return False
            if "Driver is running" in l:
                return True
        raise xenrt.XRTError("Could not determine whether GPU is running")

    def findGPUInVM(self, vm, vendor=None):
        vm.waitForDaemon(1800, desc="Windows starting up")
        xenrt.TEC().logverbose("Obtaining graphics card maker/model")
        lines = vm.devcon("findall *").splitlines()
        gpu_detected = 0
        if not vendor:
            gpu_patterns = [
                "PCI.VEN_10DE.*(NVIDIA|VGA|Display).*",  # nvidia pci vendor id
                "PCI.VEN_1002.*(ATI|VGA|Display).*",   # ati/amd pci vendor id
                "PCI.VEN_102B.*(Matrox|VGA|Display).*"  # matrox pci vendor id
            ]
        elif vendor == "NVIDIA":
            gpu_patterns = [
                "PCI.VEN_10DE.*(NVIDIA|VGA|Display).*"]  # nvidia pci vendor id
        elif vendor == "ATI":
            gpu_patterns = [
                "PCI.VEN_1002.*(ATI|VGA|Display).*"]  # ati/amd pci vendor id
        elif vendor == "Matrox":
            gpu_patterns = [
                "PCI.VEN_102B.*(Matrox|VGA|Display).*"]  # matrox pci vendor id
        for line in lines:
            if line.startswith("PCI"):
                xenrt.TEC().logverbose("devcon: %s" % line)
                for gpu_pattern in gpu_patterns:
                    gpu_found = (
                        re.search(gpu_pattern, line)
                        and not re.search(".*(Audio).*", line)
                    )
                    if gpu_found:
                        xenrt.TEC().logverbose("Found GPU device: %s" % line)
                        return line.strip()
        return None

    def vmLevelOperations(self, vm):

        try:
            vm.suspend()
            raise xenrt.XRTFailure(
                "GPU-bound VM did not fail suspend as expected")
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose(
                "vm-suspend failed as expected: %s" % str(e))
            pass
        # check that resume fails for this VM
        try:
            vm.resume()
            raise xenrt.XRTFailure(
                "GPU-bound VM did not fail resume as expected")
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose(
                "vm-resume failed as expected: %s" % str(e))
            pass
        # check that checkpoint fails for this VM
        try:
            vm.checkpoint()
            raise xenrt.XRTFailure(
                "GPU-bound VM did not fail checkpoint as expected")
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose(
                "vm-checkpoint failed as expected: %s" % str(e))
            pass
        # check that snapshot succeeds for this VM
        try:
            vm.snapshot()
        except xenrt.XRTFailure, e:
            xenrt.XRTFailure("vm-snapshot failed : %s" % str(e))
        # check that shutdown succeeds for this VM
        vm.shutdown()

        # check that start succeeds for this VM
        vm.start()

        # check that reboot succeeds for this VM
        vm.reboot()

    def runWorkload(self,vm):

        unigine = graphics.UnigineTropics(vm)
        unigine.install()
        unigine.runAsWorkload()

        return unigine



class _GPU(xenrt.TestCase, GPUHelper):
    """Common parent of all GPU testcases"""


class TC13527(_GPU):
    """GPU-Passthrough: Test tying more than one GPU to a VM fails"""

    def run(self, arglist=None):
        host = self.getDefaultHost()
        cli = host.getCLIInstance()

        # create a vm
        vm_name = xenrt.randomGuestName()
        vm_template = "\"Demo Linux VM\""
        vm = host.guestFactory()(vm_name, vm_template)
        self.uninstallOnCleanup(vm)
        vm.host = host
        self._guestsToUninstall.append(vm)
        args = []
        args.append("new-name-label=%s" % (vm_name))
        args.append("sr-uuid=%s" % host.getLocalSR())
        args.append("template-name=%s" % (vm_template))
        vm_uuid = cli.execute(
            "vm-install", string.join(args), timeout=3600).strip()

        # there's always at least 1 vm (dom0)
        vm_uuids = host.minimalList("vm-list")

        # >0 gpu hw required for this license test
        gpu_group_uuids = host.minimalList("gpu-group-list")

        if len(gpu_group_uuids) < 1:
            raise xenrt.XRTFailure(
                "This host does not contain a GPU group list as expected")
        for vm_uuid in vm_uuids:
            # assign a VGPU to this VM and check this works
            vgpu_uuid = cli.execute(
                "vgpu-create",
                "gpu-group-uuid=%s vm-uuid=%s" % (
                    gpu_group_uuids[0], vm_uuid)).strip()

            # assign another VGPU to this VM and check this fails
            for gpu_group_uuid in gpu_group_uuids:
                try:
                    data = cli.execute(
                        "vgpu-create",
                        "gpu-group-uuid=%s vm-uuid=%s" % (
                            gpu_group_uuid, vm_uuid))
                    raise xenrt.XRTFailure(
                        "Tying more than one GPU to a VM did not fail")
                except xenrt.XRTFailure, e:
                    xenrt.TEC().logverbose(
                        "vgpu-create failed as expected: %s" % str(e))
                    pass
            # clean up vgpu list
            cli.execute("vgpu-destroy", "uuid=%s" % vgpu_uuid)


class TC13529(_GPU):
    """GPU-Passthrough: Test suspend/resume/checkpoint fails for tied VM"""

    def run(self, arglist=None):
        host = self.getDefaultHost()
        cli = host.getCLIInstance()

        # create HVM Windows VM
        vm = host.createGenericWindowsGuest()
        self.uninstallOnCleanup(vm)
        vm.shutdown()
        # assign a vGPU to this VM

        # >0 gpu hw required for this license test
        gpu_group_uuids = host.minimalList("gpu-group-list")
        if len(gpu_group_uuids) < 1:
            raise xenrt.XRTFailure(
                "This host does not contain a GPU group list as expected")
        vgpu_uuid = cli.execute(
            "vgpu-create",
            "gpu-group-uuid=%s vm-uuid=%s" % (
                gpu_group_uuids[0], vm.getUUID())).strip()

        # start this VM
        vm.start(specifyOn=False)
        # check that suspend fails for this VM
        try:
            vm.suspend()
            raise xenrt.XRTFailure(
                "GPU-bound VM did not fail suspend as expected")
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose(
                "vm-suspend failed as expected: %s" % str(e))
            pass
        # check that resume fails for this VM
        try:
            vm.resume()
            raise xenrt.XRTFailure(
                "GPU-bound VM did not fail resume as expected")
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose(
                "vm-resume failed as expected: %s" % str(e))
            pass
        # check that checkpoint fails for this VM
        try:
            vm.checkpoint()
            raise xenrt.XRTFailure(
                "GPU-bound VM did not fail checkpoint as expected")
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose(
                "vm-checkpoint failed as expected: %s" % str(e))
            pass
        # check that live migrate fails for this VM
        try:
            vm.migrateVM(host, live="true")
            raise xenrt.XRTFailure(
                "GPU-bound VM did not fail live migrate as expected")
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose(
                "vm-migrate (live) failed as expected: %s" % str(e))
            pass
        # check that 'dead' migrate fails for this VM
        try:
            vm.migrateVM(host, live="false")
            raise xenrt.XRTFailure(
                "GPU-bound VM did not fail migrate as expected")
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose(
                "vm-migrate failed as expected: %s" % str(e))
            pass
        # check that snapshot succeeds for this VM
        vm.snapshot()
        # check that shutdown succeeds for this VM
        vm.shutdown()


class TC13530(_GPU):
    """
    GPU-Passthrough: Test VM can be moved between hosts with same GPU model
    """

    def run(self, arglist=None):
        host = self.getDefaultHost()
        pool = self.getDefaultPool()
        host_pairs = self.hostsWithCommonGPUGroup(self.getGPUHosts(pool))
        for (host0, host1) in host_pairs:
            if host0 == host1:
                raise xenrt.XRTError("gpu hosts must not be the same")
            # Assume two hosts have been previously installed with the
            # appropriate shared SR.
            # Both hosts should have the same GPU model x
            common_gpu_groups = self.commonGPUGroups(host0, host1)
            defaultSR = pool.master.lookupDefaultSR()
            vm = host0.createGenericWindowsGuest(sr=defaultSR)
            self.uninstallOnCleanup(vm)
            vm.shutdown()
            self.attachGPU(vm, common_gpu_groups[0])
            vm.host = host0
            vm.start(specifyOn=True)
            vm.shutdown()
            for i in range(5):
                vm.host = host1
                vm.start(specifyOn=True)
                vm.shutdown()
                vm.host = host0
                vm.start(specifyOn=True)
                vm.shutdown()


class TC13531(_GPU):
    """
    GPU-Passthrough: Test move VM from host with GPU model x
    to host with GPU model y fails.
    """

    def run(self, arglist=None):
        host = self.getDefaultHost()
        pool = self.getDefaultPool()
        defaultSR = pool.master.lookupDefaultSR()
        _hosts = self.getGPUHosts(pool)
        if len(_hosts) < 2:
            raise xenrt.XRTError(
                "There must be at least 2 gpu hosts in the pool")
        (host0, host1, h0_exclusive_gpu_groups) = (
            self.hostWithExclusiveGPUGroup(_hosts)
        )

        if host0 == host1:
            raise xenrt.XRTError("gpu hosts must not be the same")
        # Host0 should have GPU model x and Host1 should have GPU model y != x

        vm = host0.createGenericWindowsGuest(sr=defaultSR)
        self.uninstallOnCleanup(vm)
        vm.shutdown()
        self.attachGPU(vm, h0_exclusive_gpu_groups[0])
        vm.host = host0
        vm.start(specifyOn=True)
        # check that live migrate fails for this VM
        try:
            vm.migrateVM(host1, live="true")
            raise xenrt.XRTFailure("GPU-bound VM did not fail live migrate")
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose(
                "vm-migrate (live) failed as expected: %s" % str(e))
            pass
        vm.shutdown()
        try:
            vm.host = host1
            vm.start(specifyOn=True)
            raise xenrt.XRTFailure(
                "VM bound to GPU x did not fail start"
                " on a different GPU model y")
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose("VM start failed as expected: %s" % str(e))
            pass


class TC13532(_GPU):
    """
    GPU-Passthrough: Test move VM from host with GPU model x
    to host with no GPU fails
    """

    def run(self, arglist=None):
        # host = self.getDefaultHost()
        pool = self.getDefaultPool()
        defaultSR = pool.master.lookupDefaultSR()
        hosts = pool.getHosts()
        if len(hosts) < 2:
            raise xenrt.XRTError("There must be at least 2 hosts in the pool")
        host0 = None
        host1 = None
        for host in hosts:
            groups = self.getGPUGroups(host, workaround="WORKAROUND_CA61226")
            if len(groups) < 1:
                host1 = host
            if len(groups) > 0:
                host0 = host
        if host0 == host1:
            raise xenrt.XRTError("gpu hosts must not be the same")
        if not host0:
            raise xenrt.XRTFailure(
                "A host in the pool must have more than 0 GPU groups")
        if not host1:
            raise xenrt.XRTFailure(
                "A host in the pool must have no GPU groups")
        # from now on, host0 has a gpu and host1 has no gpu
        h0_gpu_groups = self.getGPUGroups(host0)
        h1_gpu_groups = self.getGPUGroups(host1)
        vm = host0.createGenericWindowsGuest(sr=defaultSR)
        self.uninstallOnCleanup(vm)
        vm.shutdown()
        self.attachGPU(vm, h0_gpu_groups[0])
        vm.host = host0
        vm.start(specifyOn=True)
        # check that live migrate fails for this VM
        try:
            vm.migrateVM(host1, live="true")
            raise xenrt.XRTFailure("GPU-bound VM did not fail live migrate")
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose(
                "vm-migrate (live) failed as expected: %s" % str(e))
            pass
        vm.shutdown()
        try:
            vm.host = host1
            vm.start(specifyOn=True)
            raise xenrt.XRTFailure(
                "VM bound to GPU x did not fail start on a host without GPU")
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose(
                "VM start failed as expected on host without GPU: %s" % str(e))
            pass


class TC13533(_GPU):
    """
    GPU-Passthrough: Test move VM from host with GPU model x
    to host with GPU model x which is already assigned to another VM fails
    """

    def run(self, arglist=None):
        host = self.getDefaultHost()
        pool = self.getDefaultPool()
        host_pairs = self.hostsWithCommonGPUGroup(self.getGPUHosts(pool))
        if len(host_pairs) < 1:
            raise xenrt.XRTError(
                "There must be at least a pair of hosts"
                " with same gpu in the pool")
        (host0, host1) = host_pairs[0]
        if host0 == host1:
            raise xenrt.XRTError("gpu hosts must not be the same")
        # Assume two hosts have been previously installed with the
        # appropriate shared SR
        # Both hosts should have the same GPU model x
        common_gpu_groups = self.commonGPUGroups(host0, host1)
        h1_pgpus = self.getPGPUs(host1, common_gpu_groups[0])
        if len(h1_pgpus) > 1:
            raise xenrt.XRTFailure(
                "Host1 cannot have more than 1 PGPU"
                " of the same GPU group as host0")
        defaultSR = pool.master.lookupDefaultSR()
        vm0 = host0.createGenericWindowsGuest(sr=defaultSR)
        self.uninstallOnCleanup(vm0)
        vm0.shutdown()
        vm1 = host1.createGenericWindowsGuest(sr=defaultSR)
        self.uninstallOnCleanup(vm1)
        vm1.shutdown()
        self.attachGPU(vm0, common_gpu_groups[0])
        self.attachGPU(vm1, common_gpu_groups[0])
        vm0.host = host0
        vm0.start(specifyOn=True)
        vm1.host = host1
        vm1.start(specifyOn=True)
        # check that live migrate fails for this VM
        try:
            vm0.migrateVM(host1, live="true")
            raise xenrt.XRTFailure("GPU-bound VM did not fail live migrate")
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose(
                "vm-migrate (live) failed as expected: %s" % str(e))
            pass
        vm0.shutdown()
        try:
            vm0.host = host1
            vm0.start(specifyOn=True)
            raise xenrt.XRTFailure(
                "VM bound to GPU x started on a host without"
                " any available GPU x")
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose(
                "VM started failed as expected due to lack of available GPU"
                " of the expected type in host")


class TC13539(_GPU):
    """
    GPU-Passthrough: stress test: drive a VM bound to a GPU
    through repeated lifecycle operations
    """

    def run(self, arglist=None):
        host = self.getDefaultHost()
        cli = host.getCLIInstance()

        # create HVM Windows VM
        vm = host.createGenericWindowsGuest()
        self.uninstallOnCleanup(vm)
        vm.shutdown()
        # assign a vGPU to this VM
        # >0 gpu hw required for this license test
        gpu_group_uuids = host.minimalList("gpu-group-list")
        if len(gpu_group_uuids) < 1:
            raise xenrt.XRTFailure(
                "This pool does not contain a GPU group list as expected")
        vgpu_uuid = cli.execute(
            "vgpu-create", "gpu-group-uuid=%s vm-uuid=%s" % (
                gpu_group_uuids[0], vm.getUUID())).strip()

        # TCStartStop,TCReboot,TCSuspendResume,TCMigrate,TCShutdown
        for j in range(3):
            # start this VM
            vm.start(specifyOn=False)
            for i in range(10):
                # shutdown this VM
                vm.shutdown()
                # start this VM
                vm.start(specifyOn=False)

            for i in range(10):
                # reboots this VM
                vm.reboot()

            for i in range(1):
                # check that suspend fails for this VM
                try:
                    vm.suspend()
                    raise xenrt.XRTFailure(
                        "GPU-bound VM did not fail suspend as expected")
                except xenrt.XRTFailure, e:
                    xenrt.TEC().logverbose(
                        "vm-suspend failed as expected: %s" % str(e))
                    pass
                # check that resume fails for this VM
                try:
                    vm.resume()
                    raise xenrt.XRTFailure(
                        "GPU-bound VM did not fail resume as expected")
                except xenrt.XRTFailure, e:
                    xenrt.TEC().logverbose(
                        "vm-resume failed as expected: %s" % str(e))
                    pass

            # check that checkpoint fails for this VM
            try:
                vm.checkpoint()
                raise xenrt.XRTFailure(
                    "GPU-bound VM did not fail checkpoint as expected")
            except xenrt.XRTFailure, e:
                xenrt.TEC().logverbose(
                    "vm-checkpoint failed as expected: %s" % str(e))
                pass
            # check that live migrate fails for this VM
            try:
                vm.migrateVM(host, live="true")
                raise xenrt.XRTFailure(
                    "GPU-bound VM did not fail live migrate as expected")
            except xenrt.XRTFailure, e:
                xenrt.TEC().logverbose(
                    "vm-migrate (live) failed as expected: %s" % str(e))
                pass
            # check that 'dead' migrate fails for this VM
            try:
                vm.migrateVM(host, live="false")
                raise xenrt.XRTFailure(
                    "GPU-bound VM did not fail migrate as expected")
            except xenrt.XRTFailure, e:
                xenrt.TEC().logverbose(
                    "vm-migrate failed as expected: %s" % str(e))
                pass

            snapshots = []
            for i in range(10):
                # check that snapshot succeeds for this VM
                snapshots.append(vm.snapshot())

            vm.shutdown()
            for i in range(10):
                # start this VM
                vm.start(specifyOn=False)
                # check that snapshot succeeds for this VM
                snapshots.append(vm.snapshot())
                # check that shutdown succeeds for this VM
                vm.shutdown()

            for uuid in snapshots:
                vm.removeSnapshot(uuid, force=True)


class TC13540(_GPU):
    """
    GPU-Passthrough: Test to confirm that GPU devices show inside Windows VMs
    """

    def run(self, arglist=None):
        host = self.getDefaultHost()
        cli = host.getCLIInstance()

        # create HVM Windows VM
        # >0 gpu hw required for this license test
        gpu_group_uuids = host.minimalList(
            "pgpu-list", args="params=gpu-group-uuid")
        if len(gpu_group_uuids) < 1:
            raise xenrt.XRTFailure(
                "This pool does not contain a GPU group list as expected")
        vms = []
        vgpu_uuids = []

        # windows_isos = ["win7sp1-x86.iso","vistaeesp2.iso","winxpsp3.iso",
        #                 "ws08sp2-x86.iso","w2k3sesp2.iso"]
        for i in range(len(gpu_group_uuids)):
            vmname = "VM" + str(i)
            # assumes that the corresponding sequence has
            # already created the VMs to test
            vms.append(self.getGuest(vmname))
            if not vms[i]:
                xenrt.TEC().warning(
                    "VM '%s' not found in pool:" % vmname
                    + " creating a generic windows guest")
                vms[i] = host.createGenericWindowsGuest()
            self.uninstallOnCleanup(vms[i])
            if vms[i].paramGet("power-state") == "running":
                vms[i].shutdown()
            # destroy any vgpus associated with this vm
            vm_vgpu_uuids = host.minimalList(
                "vgpu-list",
                args="params=uuid vm-uuid=%s" % vms[i].getUUID())
            for vm_vgpu_uuid in vm_vgpu_uuids:
                cli.execute("vgpu-destroy", "uuid=%s" % vm_vgpu_uuid)
            # freshly assign a vGPU to this VM
            vgpu_uuid = cli.execute(
                "vgpu-create",
                "gpu-group-uuid=%s vm-uuid=%s" % (
                    gpu_group_uuids[i], vms[i].getUUID())).strip()
            vgpu_uuids.append(vgpu_uuid)

        # no need to install video drivers on each VM,
        # devcon reports all pci devices

        # check that the gpu maker/model is detected from inside the VM
        xenrt.TEC().logverbose("Found %d GPU groups" % len(gpu_group_uuids))
        for i in range(len(gpu_group_uuids)):
            # as constructed above, each gpu group entry has at least a pgpu
            # somewhere in the pool
            # xapi should know that and start the vm on a proper host, that's
            # why specifyOn is false here
            vms[i].start(specifyOn=False)
            self.assertGPUPresentInVM(vms[i])

        # best-effort to clean-up vgpu associations
        for vm in vms:
            vm.shutdown()
        vgpu_uuids = host.minimalList("vgpu-list")
        for vgpu_uuid in vgpu_uuids:
            cli.execute("vgpu-destroy", "uuid=%s" % vgpu_uuid)


class TC13570(_GPU, SRIOVTests):
    """
    GPU-Passthrough: Test VM remains tied to GPU when
    SR-IOV device is bound & unbound
    """

    def prepare(self, arglist=None):
        pool = self.getDefaultPool()
        hosts = self.getGPUHosts(pool)
        if len(hosts) < 1:
            raise xenrt.XRTError(
                "There must be at least 1 gpu host in the pool")
        host = hosts[0]
        self.io = xenrt.lib.xenserver.IOvirt(host)
        self.io.enableIOMMU(restart_host=False)
        host.enableVirtualFunctions()

    def run(self, arglist=None):
        pool = self.getDefaultPool()
        hosts = self.getGPUHosts(pool)
        if len(hosts) < 1:
            raise xenrt.XRTError(
                "There must be at least 1 gpu host in the pool")
        host = hosts[0]
        cli = host.getCLIInstance()
        # create vm on host
        defaultSR = pool.master.lookupDefaultSR()
        host_gpu_groups = self.getGPUGroups(host)
        vm = host.createGenericWindowsGuest(sr=defaultSR)
        self.uninstallOnCleanup(vm)
        vm.shutdown()
        # attach vgpu to vm
        self.attachGPU(vm, host_gpu_groups[0])
        # bind sr-iov device to vm
        self.assignVFsToVM(vm, 1)
        vfs = self.getVFsAssignedToVM(vm)
        xenrt.TEC().logverbose("VFs assigned to VM (%s): %s"
                               % (vm.getUUID(), vfs))
        if len(vfs) < 1:
            raise xenrt.XRTFailure("No VFs assigned to VM (%s)"
                                   % vm.getUUID())
        # start vm
        vm.host = host
        vm.start(specifyOn=True)
        # detect gpu from inside the vm
        self.assertGPUPresentInVM(vm)
        # (optional) detect sr-iov dev from inside the vm
        # self.checkPCIDevicesInVM(vm) #this function does not work for
        # windows vms
        # shutdown vm
        vm.shutdown()
        # unbind sr-iov device from vm
        self.unassignVFsByPCIID(vm)
        vfs = self.getVFsAssignedToVM(vm)
        xenrt.TEC().logverbose("VFs assigned to VM: %s" % vfs)
        if len(vfs) > 0:
            raise xenrt.XRTFailure(
                "VFs assigned to VM (%s)"
                " when none were expected" % vm.getUUID())
        # start vm
        vm.start(specifyOn=True)
        # detect gpu from inside the vm
        self.assertGPUPresentInVM(vm)
        # shutdown the vm
        vm.shutdown()


class GPUBasic(_GPU):

    def cloneGolden(self, goldName, vmname):
        gold = xenrt.TEC().registry.guestGet(goldName)
        vm = gold.cloneVM(name=vmname, noIP=True)
        vm.setHost(self.getDefaultHost())
        self.getDefaultHost().addGuest(vm)
        xenrt.TEC().registry.guestPut(vmname, vm)
 
    def run(self, arglist=None):
        args = self.parseArgsKeyValue(arglist)
        vendor = args['vendor']
        gold = args['gold']
        gpucount = int(args['gpucount'])
        if args.has_key('vmcount'):
            vmcount = int(args['vmcount'])
        else:
            vmcount = gpucount
        host = self.getDefaultHost()
        groups = self.getGPUGroups(host, vendor=vendor)
        for i in range(vmcount):
            if xenrt.TEC().registry.guestGet("%s-clone%d" % (gold, i)):
                g = xenrt.TEC().registry.guestGet("%s-clone%d" % (gold, i))
                try:
                    g.shutdown(force=True)
                except:
                    pass
                g.poll("DOWN", 120, level=xenrt.RC_ERROR)
                g.uninstall()
            self.cloneGolden(gold, "%s-clone%d" % (gold, i))

        # Shutdown all VMs:
        [
            xenrt.TEC().registry.guestGet(x).setState("DOWN")
            for x in xenrt.TEC().registry.guestList()
        ]

        # Attach a GPU to each VM
        vmindex = 0
        workloads = []
        for i in range(gpucount):
            vm = xenrt.TEC().registry.guestGet("%s-clone%d" % (gold, i))
            self.attachGPU(vm, groups[i])
            vm.start()
            # self.assertGPUPresentInVM(vm, vendor)
            # self.assertGPUNotRunningInVM(vm, vendor)
            vm.installGPUDriver()
            self.assertGPURunningInVM(vm, vendor)
            vm.shutdown()

        for i in range(gpucount):
            vm = xenrt.TEC().registry.guestGet("%s-clone%d" % (gold, i))
            vm.start()
            self.assertGPURunningInVM(vm, vendor)
            workloads.append(self.runWorkload(vm))
        # Let the GPU workloads run for a bit
        xenrt.sleep(300)
        # Check the workloads are happy
        for i in range(gpucount):
            workloads[i].checkWorkload()
        for i in range(vmcount):
            vm = xenrt.TEC().registry.guestGet("%s-clone%d" % (gold, i))
            vm.shutdown()


class StartAllGPU(_GPU):

    def run(self, arglist=None):
        args = self.parseArgsKeyValue(arglist)
        self.vendor = args['vendor']
        gold = args['gold']
        gpucount = int(args['gpucount'])
        host = self.getDefaultHost()

        pStart = [
            xenrt.PTask(
                self.startVM, xenrt.TEC().registry.guestGet(
                    "%s-clone%d" % (gold, x))) for x in range(gpucount)]
        xenrt.pfarm(pStart)

        # Let the GPU workloads run for a bit
        xenrt.sleep(5)
        for i in range(gpucount):
            vm = xenrt.TEC().registry.guestGet("%s-clone%d" % (gold, i))
            vm.shutdown()

    def startVM(self, vm):
        vm.start()
        self.assertGPURunningInVM(vm, self.vendor)
        w = self.runWorkload(vm)
        time.sleep(300)
        w.checkWorkload()

class TCGPUSetup(_GPU):
    def parseArgs(self, arglist):
        self.args = {}
        for a in arglist:
            (arg, value) = a.split("=", 1)
            self.args[arg] = value

    def prepare(self, arglist):
        self.parseArgs(arglist)
        if not self.args.has_key("host"):
            self.args['host'] = "0"
        self.host = self.getHost("RESOURCE_HOST_%s" % self.args['host'])
        self.guest = self.getGuest(self.args['guest'])
        if not self.guest:
            self.guest = self.host.createBasicGuest(
                name=self.args['guest'], distro=self.args['distro'])
        # If we have a clean snapshot, revert to it, otherwise create one
        snaps = self.host.minimalList(
            "snapshot-list",
            "uuid",
            "snapshot-of=%s name-label=clean" % self.guest.uuid)
        self.guest.setState("DOWN")
        if len(snaps) == 0:
            self.guest.snapshot("clean")
        else:
            self.guest.revert(snaps[0])

    def run(self, arglist):
        self.guest.setState("DOWN")
        gpuGroup = self.getGPUGroup(self.host, self.args['gpu'])
        self.attachGPU(self.guest, gpuGroup)
        self.guest.setState("UP")
        self.guest.installGPUDriver()
        if not self.args.has_key("vendor"):
            self.args['vendor'] = "NVIDIA"

        self.assertGPURunningInVM(self.guest, self.args['vendor'])
        
class TC20904(xenrt.TestCase):
#This testcase is derived from HFX-929 in Hotfix Samsonite

    def run(self,arglist):
        self.host = self.getDefaultHost()
        output =self.host.execdom0("head -1 /dev/vga_arbiter")
        p = [ s for s in output.split(',') if 'PCI' in s][0]
        pciID = re.search('PCI:(.*)$',p).group(1)
        xenrt.TEC().logverbose("PCI ID of the motherboard: %s" %pciID)
        
        pci_obj = self.host.minimalList("pgpu-list", "uuid", "pci-id=%s" %pciID)        
        if self.host.genParamGet("pgpu", pci_obj[0], "supported-VGPU-types") :
            raise xenrt.XRTFailure("Supported type of pgpu: %s is not Null" %pci_obj[0])
        else :
            xenrt.TEC().logverbose("Supported type of pgpu: %s is Null as expected" %pci_obj[0])


class WorkloadManager(object):
    """Manage workload using shell script runner."""

    def __init__(self, guests, workload="tropics"):
        self.prefix = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "") + "/linux-graphics-workload/"
        self.guests = guests
        self.workload = workload

    def fetchFile(self, filename):
        """Download file from dist master"""

        xenrt.TEC().getFile(filename)
        down = xenrt.TEC().logverbose("getFile %s" % filename)
        if not down:
            raise xenrt.XRTError("Failed to fetch file: %s" % filename)
        content = ""
        with open(down, "r") as fh:
            content = fh.read()
        return content

    def start(self):
        """ start work load"""
        # This is a simple command of executing tropics (or other workload)
        # Can be implemented with execguest if prefered.
        def __start(guest, json):
            runner = Runner(json, guest)
            runner.runThrough()

        json = self.fetchFile(self.prefix + self.workload + "-start.json")
        tasks = []
        for guest in self.guests:
            tasks.append(xenrt.PTask(__start, (guest, json)))
        xenrt.pfarm(tasks)
        xenrt.sleep(5) # Gice some time to settle down.

    def stop(self):
        """Stop running process"""
        # This is a simple command of kill tropics (or workload) with killall command
        # Can be implemented with execguest if prefered.
        def __stop(guest, json):
            runner = Runner(json, guest)
            runner.runThrough()

        json = self.fetchFile(self.prefix + self.workload + "-stop.json")
        tasks = []
        for guest in self.guests:
            tasks.append(xenrt.PTask(__stop, (guest, json)))
        xenrt.pfarm(tasks)

    def check(self):
        """Check runber of running processes on guests.

        @return: number of running processes
        """
        # This is a simple check of workload process by checkinng ps.
        # Can be implemented with execguest if prefered.
        running = 0
        json = self.fetchFile(self.prefix + self.workload + "-check.json")
        for guest in self.guests:
            runner = Runner(json, guest)
            ret = runner.runThrough()
            if ret["returnCode"] == 0:
                running += 1
        return running
        

class TCLinuxPTStress(xenrt.TestCase):
    """Runs Stress tests for given time (72 hours by default)
    Creates guests number of GPUs and run workloads on all guests.
    """

    def __init__(self):
        self.pgpus = []
        self.masters = []
        self.guests = []
        self.host = self.getDefaultHost()
        # secs in min * mins in hr * hrs in day * duration of test in day
        self.duration = 60 * 60 * 24 * 3
        self.gpu = "NVIDIA"
        self.prefix = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "") + "/linux-pt-guest-installation/"

    def getGPUGroup(self, name):
        """Return gpu-group of which name contains given name"""
        for group in self.host.minimalList("gpu-group"):
            if name in self.host.genParamGet("gpu-group", group, "name-label"):
                return group
        return None

    def getPTType(self):
        """Return vgpu type uuid of gpu pass-through"""
        for vgputype in self.host.getMinimalList("vgpu-type"):
            if "passthrough" in self.host.genParamGet("vgpu-type", vgputype, "model-name"):
                return vgputype
        return None

    def getSupportedTypesList(self, pgpu):
        """Return list of supported vgpu types of given pgpu"""
        supported = self.host.genParamGet("pgpu", pgpu, "supported-VGPU-types").replace(" ", "")
        if len(supported) > 0:
            return supported.split(";")
        return []

    def getPGPUList(self, vgputype):
        """ Return list of pgpus that support given vgputype """
        return [pgpu for pgpu in self.host.minimalList("pgpu-list") if vgputype in self.getSupportedTypesList(pgpu)]

    def assignPGPU(self, guest, typeuuid, gpugroupuuid):
        """Assign a pgpu onto given VM with given type and gpu group"""
        self.host.getCLIInstance().execute("vgpu-create vgpu-type-uuid=%s vm-uuid=%s gpu-group-uuid=%s" %
            (typeuuid, guest.getUUID(), gpugroupuuid))

    def fetchFile(self, filename):
        """Download file from disk master"""
        xenrt.TEC().getFile(filename)
        down = xenrt.TEC().logverbose("getFile %s" % filename)
        if not down:
            raise xenrt.XRTError("Failed to fetch file: %s" % filename)
        content = ""
        with open(down, "r") as fh:
            content = fh.read()
        return content

    def prepareMasters(self, vms):
        def __prepare(*args):
            guest = args[0]
            json = self.fetchFile(self.prefix + guest.getName() + ".json")
            runner = Runner(json, guest)
            runner.runThrough()

        tasks = []
        for guest in self.guests:
            tasks.append(xenrt.PTask(__prepare, guest))
        xenrt.pfarm(tasks)

    def prepareGuests(self):

        # Check VGPU type uuid of pass-through.
        vgputypeuuid = self.getPTType()
        if not vgputypeuuid:
            raise xenrt.XRTError("Host does not have support GPU pass-through")

        # get List of PGPUs that support passthrough
        self.pgpus = self.getPGUList(vgputypeuuid)
        if not self.pgpus:
            raise xenrt.XRTError("No PGPU supports GPU pass-through")

        # get gpu group
        gpugroup = self.getGPUGroup(self.gpu)
        if not gpugroup:
            raise xenrt.XRTError("Host does not have %s type card or GPU group is not initiated properly." % self.gpu)

        # Clone guests to run and assign pgpu.
        for i in range(len(self.pgpus)):
            guest = self.masters[i % len(self.master)].clone()
            self.uninstallOnCleanup(guest)
            self.assignPGPU(guest, vgputypeuuid, gpugroup)
            self.guests.append(guest)

    def prepare(self, arglist = []):
        # Retian args
        args = self.parseArgsKeyValue(arglist)

        if "gpu" in args:
            self.gpu = args["gpu"]
        if "duration" in args:
            # duration is given in mins.
            self.duration = int(args["duration"]) * 60

        # Retain list of master VMs from sequence.
        if not "vms" in args:
            raise xenrt.XRTError("No Master VMs are passed.")

        # Install required tools on all master vms.
        self.prepareMaster(args["vms"].split(","))

        # Cline required number of VMs and set gpu pass-through on them
        self.prepareGuests()

    def run(self, arglist = []):

        total = len(self.guests)
        wlm = WorkloadManager(self.guests)
        wlm.start()
        start = time.time()

        running = wlm.check()
        if running != total:
            raise xenrt.XRTFailure("Failed to run %d workloads. (%d expected to run)" %
                ((total - running), total))

        while time.time() - start < self.duration:
            xenrt.sleep(60 * 60)
            running = wlm.check()
            xenrt.TEC().logverbose("%d / %d guests are running workloads" % (running, total))
            if running == 0:
                raise xenrt.XRTFailure("(0/%d) workloads are running." % (total))

        running = wlm.check()
        if running != total:
            raise xenrt.XRTFailure("Only %d out of %d workloads ran for %d hours" %
            (running, total, (self.duration /60 /60)))
        xenrt.TEC().logverbose("Successfully ran workloads on %d guests." % (total))
