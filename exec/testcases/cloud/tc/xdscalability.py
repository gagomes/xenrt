#
# XenRT: Test harness for Xen and the XenServer product family
#
# Testcases for scalability
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and conditions
# as licensed by Citrix Systems, Inc. All other rights reserved.
#

import string, time, re, copy, threading, sys, traceback, urllib, random
import xml.dom.minidom
import xenrt
from xenrt.lazylog import step, comment, log, warning

class _TimedTestCase(xenrt.TestCase):
    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.timings = []

    def addTiming(self, timing):
        self.timings.append(timing)

    def preLogs(self):
        filename = "%s/xenrt-timings.log" % (xenrt.TEC().getLogdir())
        f = file(filename, "w")
        f.write("\n".join(self.timings))
        f.close()


class _TCCloneVMs(_TimedTestCase):

    def __init__(self, tcid=None):
        _TimedTestCase.__init__(self, tcid)
        self.lock = threading.Lock()

    def prepare(self, arglist):
        self.cloud = self.getDefaultToolstack()
        self.zones = [x.name for x in self.cloud.marvin.cloudApi.listZones()]
        for z in self.zones:
            gold = self.cloud.createInstance(distro="debian70_x86-32", zone=z)
        
            # Do any XD tailoring here
            gold.stop()
            self.cloud.createTemplateFromInstance(gold, "xdgold%s" % z)
            gold.start()
            gold.os.execSSH("echo gold2 > /root/gold2")
            gold.stop()
            self.cloud.createTemplateFromInstance(gold, "xdgold2%s" % z)
            gold.destroy()

    # Base class for cloning VMs with worker threads
    def run(self, arglist):
        threading.stack_size(65536)
        threads = None

        args = self.parseArgsKeyValue(arglist)
        threads = int(args['threads'])
        instances = int(args['instances'])

        # Generate the list of VM names, which host they will run on and where they're clones from
        # The name will be of the format clonex.y:
        #   x = zone the VM will run on
        #   y = index of the VM on the zone

        self.vmSpecs = [("clone-%s-%d" % (self.zones[x % len(self.zones)], x/len(self.zones)), self.zones[x % len(self.zones)]) for x in range(instances)]

        # We'll run this with a limited number of workers (threads).
        # Each worker thread will pull a VM Spec from the list, clone it, then move onto the next one. The threads will complete when all VMs are cloned
        pClone = map(lambda x: xenrt.PTask(self.doClones), range(threads))
        xenrt.pfarm(pClone)

    def doClones(self):
        # Worker thread function for cloning VMs.
        while True:
            with self.lock:
                item = None
                # Get a VM spec from the queue
                if len(self.vmSpecs) > 0:
                    item = self.vmSpecs.pop()
            # If we didn't get a VM, then they're all cloned, so finish the thread
            if not item:
                break
            # Clone the VM. The actual mechanism for cloning is in the derived class
            (vmname, zone) = item
            xenrt.TEC().logverbose("Cloning VM to %s on zone %s" % (vmname, zone))
            self.cloneVM(vmname, zone)

    def cloneVM(self, vmname, zone):
        raise xenrt.XRTError("Unimplemented")

class TCXenDesktopCloneVMs(_TCCloneVMs):
    # How to clone a VM, "XenDesktop Style"
    def cloneVM(self, vmname, zone):
        self.addTiming("TIME_VM_CLONE_START_%s:%.3f" % (vmname, xenrt.util.timenow(float=True)))
        # Clone the VM
        instance = self.cloud.createInstanceFromTemplate("xdgold%s" % zone, name=vmname, zone=zone, start=False)
        self.addTiming("TIME_VM_CLONE_COMPLETE_%s:%.3f" % (vmname, xenrt.util.timenow(float=True)))
        # Create extra disks (identity disk and PVD) on the same SR as the golden VDI

        zoneId = [x.id for x in self.cloud.marvin.cloudApi.listZones() if x.name == zone][0]
        diskOfferingId = [x.id for x in self.cloud.marvin.cloudApi.listDiskOfferings() if x.name=="Custom"][0]

        disk1 = self.cloud.marvin.cloudApi.createVolume(name="%s-0" % vmname, size=1, diskofferingid=diskOfferingId, zoneid=zoneId).id
        disk2 = self.cloud.marvin.cloudApi.createVolume(name="%s-1" % vmname, size=1, diskofferingid=diskOfferingId, zoneid=zoneId).id
        self.cloud.marvin.cloudApi.attachVolume(id=disk1, virtualmachineid=instance.toolstackId)
        self.cloud.marvin.cloudApi.attachVolume(id=disk2, virtualmachineid=instance.toolstackId)

        self.addTiming("TIME_VM_CLONE_ATTACHPVD_%s:%.3f" % (vmname, xenrt.util.timenow(float=True)))


class _TCScaleVMOp(_TimedTestCase):

    def __init__(self, tcid=None):
        _TimedTestCase.__init__(self, tcid)
        self.lock = threading.Lock()

    # Base class for performing operations on VMs with worker threads
    def prepare(self, arglist=None):
        # Get the hosts
        self.cloud = self.cloud = self.getDefaultToolstack()

    def run(self, arglist):
        threading.stack_size(65536)
        # Get the sequence variables

        args = self.parseArgsKeyValue(arglist)
        threads = int(args['threads'])
        iterations = int(args.get("interations", 1))

        # Get the list of VMs - this is everything that begins with "clone" (cloned in _TCCloneVMs)
        vms = [x for x in xenrt.TEC().registry.instanceGetAll() if x.name.startswith("clone")]

        self.doVMOperations(vms, threads, iterations)

    # This is a separate function so that a derived class can override self.vms
    def doVMOperations(self, vms, threads, iterations=1, func=None, timestamps=True):

        if func is None:
            func = self.doOperation

        # We'll store failed VMs here so we don't just bail out at the first failure

        self.vms = vms

        self.failedVMs = []
        self.removedVMs = []

        # Each iteration will wait for the completion of the previous iteration before going again
        for i in range(iterations):
            # The VM operation may want to complete asynchronously (e.g. finish booting).
            # It can append a completion thread here, and at the end we'll wait for them all to complete before finishing
            self.completionThreads = []
            # Create a list which is the indexes (in self.vms) of the vms to perform operations on.
            self.vmsToOp = range(len(self.vms))
            # Shuffle the VMs for a more realistic workload
            random.shuffle(self.vmsToOp)
            if timestamps is True:
                self.addTiming("TIME_ITERATION%d_START:%.3f" % (i, xenrt.util.timenow(float=True)))
            # Start the worker threads
            pOp = map(lambda x: xenrt.PTask(self.doVMWorker, func), range(threads))

            # Wait for them to complete. The worker threads will wait for the completion threads.
            xenrt.pfarm(pOp)
            if timestamps is True:
                self.addTiming("TIME_ITERATION%d_COMPLETE:%.3f" % (i, xenrt.util.timenow(float=True)))

            # Do any post-iteration cleanup (e.g. deleting old base disks)
            self.postIterationCleanup()
            if timestamps is True:
                self.addTiming("TIME_ITERATION%d_CLEANUPCOMPLETE:%.3f" % (i, xenrt.util.timenow(float=True)))

        try:
            if len(self.failedVMs) > 0:
                raise xenrt.XRTFailure("Failed to perform operation on %d/%d VMs - %s" % (len(self.failedVMs), len(self.vms), ", ".join(self.failedVMs)))
        finally:
            # Verify that all of the guests are still functional
            if not xenrt.TEC().lookup("NO_HOST_VERIFY", False, boolean=True):
                for i in self.removedVMs:
                    self.vms.remove(i)
                self.vmsToOp = range(len(self.vms))
                pVerify = map(lambda x: xenrt.PTask(self.doVMWorker, self.verifyVM), range(threads))
                xenrt.pfarm(pVerify)

                if len(self.failedVMs) > 0:
                    raise xenrt.XRTFailure("Failed to verify VMs %s" % ", ".join(self.failedVMs))

    def verifyVM(self, vm):
        vm.assertHealthy(quick=True)
        if vm.special.get("gold2") and vm.getPowerState() == xenrt.PowerState.up:
            vm.os.execSSH("test -e /root/gold2")

    def doVMWorker(self, func):
        # Worker thread function for performing operations on VMs.
        while True:
            with self.lock:
                vm = None
                # Get a VM from the queue
                if len(self.vmsToOp) > 0:
                    vm = self.vms[self.vmsToOp.pop()]

            if not vm:
                # If we didn't get a VM, then theye've all been operated on, so we can exit the loop
                break
            try:
                # Perform the operation on the VM. The operation may need to know where it was originally cloned from
                # (e.g. for XD clone on boot), so pass that in too.
                func(vm)
            except Exception, e:
                xenrt.TEC().reason("Failed to perform operation on %s - %s" % (vm.name, str(e)))
                # Add it to the list of failed VMs, but continue for now.
                with self.lock:
                    self.failedVMs.append(vm.name)

        # Now we wait for the completion threads to finish, then we can exit the worker thread.
        # It's the responsibility of the completion thread to implement any necessary timeouts
        # A VM operation function may have added a completion thread in order to e.g. wait for VM boot to complete,
        # having exited the function after vm-start returned
        for t in self.completionThreads:
            t.join()



    def doOperation(self, vm):
        raise xenrt.XRTError("Unimplemented")

    def postIterationCleanup(self):
        pass

class _TCScaleVMLifecycle(_TCScaleVMOp):
    def __init__(self, tcid=None):
        _TCScaleVMOp.__init__(self, tcid)

    def waitForVMBoot(self, vm):
        # Thread (called by PTask) Waiting for a VM to boot
        try:
            vm.os.waitForBoot(3600)
            self.addTiming("TIME_VM_VMAVAILABLE_%s:%.3f" % (vm.name, xenrt.util.timenow(float=True)))
        except Exception, e:
            # If it failed, continue, but mark it as failed for now.
            xenrt.TEC().reason("VM %s failed to boot - %s" % (vm.name, str(e)))
            with self.lock:
                self.failedVMs.append(vm.name)

    def start(self, vm):
        # Conventional start

        self.addTiming("TIME_VM_START_%s:%.3f" % (vm.name, xenrt.util.timenow(float=True)))
        # Start the VM
        self.cloud.startInstance(vm)

        self.addTiming("TIME_VM_STARTCOMPLETE_%s:%.3f" % (vm.name, xenrt.util.timenow(float=True)))
        # Asynchronously wait for it to boot
        t = xenrt.PTask(self.waitForVMBoot, vm)
        with self.lock:
            self.completionThreads.append(t)
        t.start()

    def shutdown(self, vm):
        startTime = xenrt.util.timenow(float=True)

        # Shutdown VM
        vm.stop()

        shutdownCompleteTime = xenrt.util.timenow(float=True)
        self.addTiming("TIME_VM_SHUTDOWN_%s:%.3f" % (vm.name, startTime))
        self.addTiming("TIME_VM_SHUTDOWNCOMPLETE_%s:%.3f" % (vm.name, shutdownCompleteTime))


class _TCScaleVMXenDesktopLifecycle(_TCScaleVMLifecycle):
    # Define the XenDesktop style lifecycle ops
    def __init__(self, tcid=None):
        _TCScaleVMLifecycle.__init__(self, tcid)

    def xenDesktopStart(self, vm):
        # XenDesktop style start - attach a new clone from the golden image and boot
        if vm.special.get('booted'):
            self.addTiming("TIME_VM_RESET_%s:%.3f" % (vm.name, xenrt.util.timenow(float=True)))
            self.cloud.marvin.cloudApi.restoreVirtualMachine(virtualmachineid=vm.toolstackId)
            self.addTiming("TIME_VM_RESETCOMPLETE_%s:%.3f" % (vm.name, xenrt.util.timenow(float=True)))
        self.addTiming("TIME_VM_START_%s:%.3f" % (vm.name, xenrt.util.timenow(float=True)))

        # Start the VM
        self.cloud.startInstance(vm)
        vm.special['booted'] = True

        self.addTiming("TIME_VM_STARTCOMPLETE_%s:%.3f" % (vm.name, xenrt.util.timenow(float=True)))
        # Asynchronously wait for it to boot
        t = xenrt.PTask(self.waitForVMBoot, vm)
        with self.lock:
            self.completionThreads.append(t)
        t.start()


    def xenDesktopShutdown(self, vm=None, force=False, detachVDI=True):
        startTime = xenrt.util.timenow(float=True)

        # Shutdown VM
        vm.stop(force=force)

        shutdownCompleteTime = xenrt.util.timenow(float=True)

        self.addTiming("TIME_VM_SHUTDOWN_%s:%.3f" % (vm.name, startTime))
        self.addTiming("TIME_VM_SHUTDOWNCOMPLETE_%s:%.3f" % (vm.name, shutdownCompleteTime))

    def xenDesktopForceShutdown(self, vm=None):
        self.xenDesktopShutdown(vm, force=True, detachVDI=False)

class TCScaleVMXenDesktopStart(_TCScaleVMXenDesktopLifecycle):
    # Concrete test case to start all of the VMs, XenDesktop Style
    def doOperation(self, vm):
        self.xenDesktopStart(vm)

class TCScaleVMXenDesktopShutdown(_TCScaleVMXenDesktopLifecycle):
    # Concrete test case to shutdown all of the VMs, XenDesktop Style
    def doOperation(self, vm):
        self.xenDesktopShutdown(vm)

class TCScaleVMXenDesktopUpdate(_TCScaleVMXenDesktopLifecycle):
    def doOperation(self, vm):
        # Do the XenDesktop "Update" operation (update to a new base image)
        zone = [x.zonename for x in self.cloud.marvin.cloudApi.listVirtualMachines() if x.id == vm.toolstackId][0]
        templateId = self.cloud.marvin.cloudApi.listTemplates(templatefilter="all", name="xdgold2%s" % zone)[0].id

        self.cloud.marvin.cloudApi.restoreVirtualMachine(virtualmachineid=vm.toolstackId, templateid=templateId)
        del vm.special['booted']
        vm.special['gold2'] = True

class TCScaleVMXenDesktopDelete(_TCScaleVMXenDesktopLifecycle):
    def doOperation(self, vm):
        self.addTiming("TIME_VM_DELETE_START_%s:%.3f" % (vm.name, xenrt.util.timenow(float=True)))
        vm.destroy()
        self.removedVMs.append(vm)
        self.addTiming("TIME_VM_DELETE_COMPLETE_%s:%.3f" % (vm.name, xenrt.util.timenow(float=True)))
        xenrt.TEC().registry.instanceDelete(vm.name)


class TCScaleVMXenDesktopReboot(_TCScaleVMXenDesktopLifecycle):

    # Concrete test case to reboot all of the VMs, XenDesktop Style
    def doOperation(self, vm):
        self.xenDesktopShutdown(vm)
        self.xenDesktopStart(vm)

class TCScaleVMStart(_TCScaleVMLifecycle):
    # Concrete test case to start all of the VMs, Conventional Style
    def doOperation(self, vm):
        self.start(vm)

class TCScaleVMShutdown(_TCScaleVMXenDesktopLifecycle):
    # Concrete test case to shutdown all of the VMs, Conventional Style
    def doOperation(self, vm):
        self.shutdown(vm)

class TCScaleVMReboot(_TCScaleVMXenDesktopLifecycle):

    # Concrete test case to reboot all of the VMs, Conventional Style
    def doOperation(self, vm):
        self.shutdown(vm)
        self.start(vm)



