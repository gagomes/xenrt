# XenRT: Test harness for Xen, XenServer and CloudStack product family
#
# Testcases for Cloudstack Scalability
#
# Copyright (c) 2014 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and conditions
# as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt
import string, time, re, copy, threading, sys, traceback, urllib, random
import xmlrpclib, IPy, httplib, socket, os, re, bz2
import xml.dom.minidom
from xenrt.lazylog import step, comment, log, warning

class _TimedTestCase(xenrt.TestCase):
    """Class for recording the time taken to perform instance lifecycle"""

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

#TestCase 1: Create instance from ISO, and create template from it.
class _CreateGoldenTemplate(_TimedTestCase):
    """Base class for creating an instance from ISO and a template from it"""

    def __init__(self, tcid=None):
        _TimedTestCase.__init__(self, tcid)
        self.lock = threading.Lock()
        self.cloud = None
        self.goldTemplate = None
        self.instances = []

    def prepare(self, arglist=None):
        instanceDistro = "win7sp1-x86"
        instanceName = "win7sp1"
        templateName = "gold0"

        # Get the sequence variables.
        if arglist and len(arglist) > 0:
            for arg in arglist:
                l = string.split(arg, "=", 1)
                if l[0] == "distro":
                    instanceDistro = l[1]
                if l[0] == "instancename":
                    instanceName = l[1]
                if l[0] == "templatename":
                    templateName = l[1]

        # Get the toolstack
        self.cloud = self.getDefaultToolstack()

        # Create an instance.
        instance = self.cloud.createInstance(distro=instanceDistro, name=instanceName)
        #instance =  self.cloud.existingInstance(instanceName)

        # Create a golden template from the instance.
        self.cloud.createTemplateFromInstance(instance, templateName)
        self.goldTemplate = templateName

    def run(self, arglist):
        threading.stack_size(65536)
        threads = 2
        instancesCount = 4

        # Get the sequence variables.
        if arglist and len(arglist) > 0:
            for arg in arglist:
                l = string.split(arg, "=", 1)
                if l[0] == "threads":
                    threads = int(l[1])
                if l[0] == "instances":
                    instancesCount = int(l[1])                 

        # Generate the list of instance names.
        self.instanceSpecs = map(lambda x: ("clone-%d" % x, self.goldTemplate), range(instancesCount))

        # We'll run this with a limited number of workers (threads).
        # Each worker thread will pull a instance Spec from the list, create from the template, and 
        # then move onto the next one. The threads will complete when all instances are created from template.
        pClone = map(lambda x: xenrt.PTask(self.createInstancesFromTemplate), range(threads))
        xenrt.pfarm(pClone)
        
    def createInstancesFromTemplate(self):
        # Worker thread function for cloning instances.
        while True:
            self.lock.acquire()
            item = None
            try:
                # Get a instance spec from the queue
                if len(self.instanceSpecs) > 0:
                    item = self.instanceSpecs.pop()
            finally:
                self.lock.release()
                
            # If we didn't get a instance, then they're all cloned, so finish the thread
            if not item:
                break

            # Clone the instance. The actual mechanism for cloning is in the derived class
            (instanceName, templateName) = item
            xenrt.TEC().logverbose("Cloning instant to %s" % instanceName)
            self.createInstance(templateName, instanceName)
            
            # Put it in the registry
            self.lock.acquire()
            self.lock.release()

    def createInstance(self, templateName, instanceName):
        """Create instance from a template"""

        raise xenrt.XRTError("Unimplemented")

#TestCase 2: Create n instances from the template
class TCCreateInstancesFromTemplate(_CreateGoldenTemplate):
    """Base class for creating an instance from golden template"""

    def createInstance(self, templateName, instanceName):
        """Create instance from a template"""

        self.addTiming("TIME_INSTANCE_CREATE_START_%s:%.3f" %
                            (instanceName, xenrt.util.timenow(float=True)))

        # Create the instance from golden template.
        instance = self.cloud.createInstanceFromTemplate(templateName, name=instanceName, start=False)
        
        self.addTiming("TIME_INSTANCE_CREATE_COMPLETE_%s:%.3f" %
                            (instanceName, xenrt.util.timenow(float=True)))

        self.lock.acquire()
        self.instances.append(instance)
        self.lock.release()

class _ScaleInstanceOperations(_TimedTestCase):
    """Base class for performing operations on instannce with worker threads"""

    def __init__(self, tcid=None):
        _TimedTestCase.__init__(self, tcid)
        self.lock = threading.Lock()
        self.cloud = None
        self.instances = None

    def prepare(self, arglist=None):
        # Get the toolstack.
        self.cloud = self.getDefaultToolstack()

    def run(self, arglist):
        threading.stack_size(65536)
        threads = 4
        iterations = 1

        # Get the sequence variables.
        if arglist and len(arglist) > 0:
            for arg in arglist:
                l = string.split(arg, "=", 1)
                if l[0] == "threads":
                    threads = int(l[1])
                if l[0] == "iterations":
                    iterations = int(l[1])

        # Get the list of instances - this is everything that begins with "clone".
        # The clones are created from template in CreateInstancesFromTemplate class.
        instances = map(lambda x: self.cloud.existingInstance(x.name), 
                        filter(lambda x: "clone" in x.name, self.cloud.getAllExistingInstances()))
        self.doInstanceOperations(instances, threads, iterations)
    
    # This is a separate function so that a derived class can override self.instances
    def doInstanceOperations(self, instances, threads, iterations=1, func=None, timestamps=True):

        if func is None:
            func = self.doOperation

        self.instances = instances
        
        # We'll store failed instances here so we don't just bail out at the first failure
        self.failedInstances = []
        
        # Each iteration will wait for the completion of the previous iteration before going again        
        for i in range(iterations):
            # The Instance operation may want to complete asynchronously (e.g. finish booting).
            # It can append a completion thread here, and at the end we'll wait for them all to complete before finishing
            self.completionThreads = []
            # Create a list which is the indexes (in self.instances) of the instances to perform operations on.
            self.instancesToOp = range(len(self.instances))
            # Shuffle the instances for a more realistic workload
            random.shuffle(self.instancesToOp)

            if timestamps is True:
                self.addTiming("TIME_ITERATION%d_START:%.3f" % (i, xenrt.util.timenow(float=True)))

            # Start the worker threads
            pOp = map(lambda x: xenrt.PTask(self.doInstanceWorker, func), range(threads))
            
            # Wait for them to complete. The worker threads will wait for the completion threads.
            xenrt.pfarm(pOp)

            if timestamps is True:
                self.addTiming("TIME_ITERATION%d_COMPLETE:%.3f" % (i, xenrt.util.timenow(float=True)))

        try:
            if len(self.failedInstances) > 0:
                raise xenrt.XRTFailure("Failed to perform operation on %d/%d instances - %s" %
                            (len(self.failedInstances), len(self.instances), ", ".join(self.failedInstances)))
        finally:
            # Verify that all of the hosts and instances are still functional. Required???
            pass

    def doInstanceWorker(self, func):
        # Worker thread function for performing operations on instances.
        while True:
            self.lock.acquire()
            instance = None
            # Get an instance from the queue
            try:
                if len(self.instancesToOp) > 0:
                    instance = self.instances[self.instancesToOp.pop()]
            finally:
                self.lock.release()

            if not instance:
                # If we didn't get an instance, then theye've all been operated on, so we can exit the loop.
                break

            try:
                # Perform the operation on the instance. 
                func(instance)
            except Exception, e:
                xenrt.TEC().reason("Failed to perform operation on %s - %s" % (instance.name, str(e)))
                # Add it to the list of failed instances, but continue for now.
                self.lock.acquire()
                self.failedInstances.append(instance.name)
                self.lock.release()
        
        # Now we wait for the completion threads to finish, then we can exit the worker thread.
        # It's the responsibility of the completion thread to implement any necessary timeouts.
        # An instance operation function may have added a completion thread in order to e.g. wait for instance boot to complete,
        # having exited the function after the instance start is returned.
        for t in self.completionThreads:
            t.join()
        
    def doOperation(self, instance):
        raise xenrt.XRTError("Unimplemented")

class _ScaleInstanceLifecycle(_ScaleInstanceOperations):
    def __init__(self, tcid=None):
        _ScaleInstanceOperations.__init__(self, tcid)
    
    def waitForInstanceBoot(self, instance):
    # Thread (called by PTask) Waiting for an instance to boot.
        try:
            instance.poll(3600, desc="Instance boot")
            self.addTiming("TIME_INSTANCE_AVAILABLE_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))
            self.addTiming("TIME_INSTANCE_AGENT_%s:N/A" % (instance.name))
        except Exception, e:
            # If it failed, continue, but mark it as failed for now.
            xenrt.TEC().reason("Instances %s failed to boot - %s" % (instance.name, str(e)))
            self.lock.acquire()
            self.failedInstances.append(instance.name)
            self.lock.release()
    
    def start(self, instance):
        """Conventional start"""
        
        self.addTiming("TIME_INSTANCE_START_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))
        # Start the instance.
        instance.start()
        self.addTiming("TIME_INSTANCE_STARTCOMPLETE_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))

        # Asynchronously wait for it to boot.
        t = xenrt.PTask(self.waitForInstanceBoot, instance)
        self.lock.acquire()
        self.completionThreads.append(t)
        self.lock.release()
        t.start()

    def reboot(self, instance):
        """Conventional reboot"""
        
        self.addTiming("TIME_INSTANCE_REBOOT_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))
        # Reboot the instance.
        instance.reboot()
        self.addTiming("TIME_INSTANCE_REBOOTCOMPLETE_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))

        # Asynchronously wait for it to boot.
        t = xenrt.PTask(self.waitForInstanceBoot, instance)
        self.lock.acquire()
        self.completionThreads.append(t)
        self.lock.release()
        t.start()

    def suspend(self, instance):
        """Conventional suspend"""
        
        self.addTiming("TIME_INSTANCE_SUSPEND_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))
        # suspend the instance.
        instance.suspend()
        self.addTiming("TIME_INSTANCE_SUSPENDCOMPLETE_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))

    def resume(self, instance):
        """Conventional resume"""
        
        self.addTiming("TIME_INSTANCE_RESUME_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))
        # Resume the instance.
        instance.resume()
        self.addTiming("TIME_INSTANCE_RESUMECOMPLETE_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))

        # Asynchronously wait for it to resume.
        t = xenrt.PTask(self.waitForInstanceBoot, instance)
        self.lock.acquire()
        self.completionThreads.append(t)
        self.lock.release()
        t.start()

    def shutdown(self, instance):
        """Conventional shutdown"""

        self.addTiming("TIME_INSTANCE_SHUTDOWN_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))
        # Shutdown Instance.
        instance.stop()
        self.addTiming("TIME_INSTANCE_SHUTDOWNCOMPLETE_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))

    def destroy(self, instance):
        """Conventional destroy"""

        self.addTiming("TIME_INSTANCE_DESTRO_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))
        # Destroy Instance.
        instance.destroy()
        self.addTiming("TIME_INSTANCE_DESTROYCOMPLETE_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))

class _ScaleInstanceXenDesktopLifecycle(_ScaleInstanceLifecycle):
    """Define the XenDesktop style lifecycle ops"""

    def __init__(self, tcid=None):
        _ScaleInstanceLifecycle.__init__(self, tcid)

    def xenDesktopStart(self, instance):
        """XenDesktop style start"""
       
        self.addTiming("TIME_INSTANCE_START_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))
        # Start the instance
        self.cloud.startInstance(instance)
        self.addTiming("TIME_INSTANCE_STARTCOMPLETE_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))

        # Asynchronously wait for it to boot
        t = xenrt.PTask(self.waitForInstanceBoot, instance)
        self.lock.acquire()
        self.completionThreads.append(t)
        self.lock.release()
        t.start()

    def xenDesktopReboot(self, instance):
        """XenDesktop style reboot"""

        self.addTiming("TIME_INSTANCE_REBOOT_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))
        # Reboot instance.
        self.cloud.rebootInstance(instance)
        self.addTiming("TIME_INSTANCE_REBOOTCOMPLETE_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))

        # Asynchronously wait for it to boot
        t = xenrt.PTask(self.waitForInstanceBoot, instance)
        self.lock.acquire()
        self.completionThreads.append(t)
        self.lock.release()
        t.start()

    def xenDesktopShutdown(self, instance):
        """XenDesktop style shutdown"""

        self.addTiming("TIME_INSTANCE_SHUTDOWN_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))
        # Shutdown Instance.
        self.cloud.stopInstance(instance)
        self.addTiming("TIME_INSTANCE_SHUTDOWNCOMPLETE_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))

    def xenDesktopDestroy(self, instance):
        """XenDesktop style destroy"""

        self.addTiming("TIME_INSTANCE_DESTROY_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))
        # Destroy the instance.
        self.cloud.destroyInstance(instance)
        self.addTiming("TIME_INSTANCE_DESTROYCOMPLETE_%s:%.3f" %
                                (instance.name, xenrt.util.timenow(float=True)))

# Concerete test cases.

#TestCase 3:
class TCScaleInstanceXenDesktopStart(_ScaleInstanceXenDesktopLifecycle):
    """Start all these instances, and time when available over XML/RPC"""

    def doOperation(self, instance):
        self.xenDesktopStart(instance)

#TestCase 4:
class TCScaleInstanceXenDesktopReboot(_ScaleInstanceXenDesktopLifecycle):
    """Reboot all instances, and time when available over XML/RPC"""

    def doOperation(self, instance):
        self.xenDesktopReboot(instance)

#TestCase 5:
class TCScaleInstanceXenDesktopStop(_ScaleInstanceXenDesktopLifecycle):
    """Shutdown all instances"""

    def doOperation(self, instance):
        self.xenDesktopShutdown(instance)

#TestCase 6:
class TCScaleInstanceXenDesktopDestroy(_ScaleInstanceXenDesktopLifecycle):
    """Destroy all instances"""

    def doOperation(self, instance):
        self.xenDesktopDestroy(instance)
