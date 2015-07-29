import xenrt
from datetime import datetime
from pprint import pformat
import re

class SystemVM(object):
    """Object for managing and monitoring CS/CP System VMs"""

    @classmethod
    def systemVMFactory(cls, toolstack, hypervisorHosts, podid=None, systemvmtype=None):
        """Return a list of System VM objects"""
        systemVmData = toolstack.marvin.cloudApi.listSystemVms(podid=podid, systemvmtype=systemvmtype)
        xenrt.TEC().logverbose('Found %d System VMs: %s' % (len(systemVmData), ','.join(map(lambda x:x.name, systemVmData))))
        return map(lambda x:cls(x.name, toolstack, hypervisorHosts), systemVmData)

    def __init__(self, name, toolstack, hypervisorHosts):
        self.cloud = toolstack
        self.hypervisorHosts = hypervisorHosts
        self.name = name
        systemVmData = self.cloud.marvin.cloudApi.listSystemVms(name=self.name)
        xenrt.xrtAssert(len(systemVmData) == 1, 'System VM with name %s not found' % (name))

    def getSystemVMData(self):
        systemVmData = self.cloud.marvin.cloudApi.listSystemVms(name=self.name)
        xenrt.xrtAssert(len(systemVmData) == 1, 'System VM with name %s not found' % (self.name))
        return systemVmData[0]

    def command(self, command):
        systemVmData = self.getSystemVMData()
        if systemVmData.hypervisor == 'XenServer':
            xsHost = filter(lambda x:x.getName() == systemVmData.hostname, self.hypervisorHosts)[0]
            rData = xsHost.execdom0('ssh -i /root/.ssh/id_rsa.cloud -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -p 3922 root@%s %s' % (systemVmData.linklocalip, command)).strip()
            xenrt.TEC().logverbose('Command: %s returned: %s' % (command, rData))
            return rData
        else:
            raise xenrt.XRTError('System VM command execution not supported for non-XS hypervisors')

    def waitForReady(self, timeout=600, pollPeriod=20):
        """This method check the CP host state, CP System VM state and checks that the agent is running"""
        isReady = False
        startTime = datetime.now()
        msAgentState = None
        msVMState = None
        agentRunning = None
        while (datetime.now() - startTime).seconds < timeout:
            systemVmData = self.getSystemVMData()
            if msVMState != systemVmData.state:
                xenrt.TEC().logverbose('[%s] MS VM state changed from %s to %s' % (self.name, msVMState, systemVmData.state))
                msVMState = systemVmData.state
            hostData = self.getManSvrVMData()
            if msAgentState != hostData.state:
                xenrt.TEC().logverbose('[%s] MS Agent state changed from %s to %s' % (self.name, msAgentState, hostData.state))
                msAgentState = hostData.state
            running = self.isAgentRunning()
            if agentRunning != running:
                xenrt.TEC().logverbose('[%s] Agent transitioned from Running: %s to Running: %s' % (self.name, agentRunning, running))
                agentRunning = running

            if msVMState == 'Running' and msAgentState == 'Up' and agentRunning:
                xenrt.TEC().logverbose('System VM [%s] reached ready state in %d seconds' % (self.name, (datetime.now() - startTime).seconds))
                isReady = True
                break

            xenrt.sleep(pollPeriod)

        if not isReady:
            raise xenrt.XRTFailure('System VM [%s] failed to reach ready state in %d seconds' % (self.name, timeout))

    def getManSvrVMData(self):
        hostData = self.cloud.marvin.cloudApi.listHosts(name=self.name)
        xenrt.xrtAssert(len(hostData) == 1, 'ManSvr Host record with name %s not found' % (self.name))
        return hostData[0]

    def isAgentRunning(self):
        isRunning = False
        try:
            rData = self.command('service cloud status')
            isRunning = 'is running' in rData
        except Exception, e:
            pass

        return isRunning

    def stopAgent(self):
        self.command('service cloud stop')

    def killAgent(self):
        rData = self.command('service cloud status')
        pid = int(re.search('process id: (\d+)$', rData).group(1))
        self.command('kill -9 %d' % (pid))

    def inGuestShutdown(self):
        self.command('shutdown -h now')

    def inGuestReboot(self):
        self.command('reboot')

    def reboot(self):
        systemVmData = self.getSystemVMData()
        self.cloud.marvin.cloudApi.rebootSystemVm(id=systemVmData.id)

    def stop(self):
        systemVmData = self.getSystemVMData()
        self.cloud.marvin.cloudApi.stopSystemVm(id=systemVmData.id)

    def forcedStop(self):
        systemVmData = self.getSystemVMData()
        self.cloud.marvin.cloudApi.stopSystemVm(id=systemVmData.id, forced='true')

    def migrateToHost(self, host):
        systemVmData = self.getSystemVMData()
        if systemVmData.hostid != host.id:
            xenrt.TEC().logverbose('Migrating System VM [%s] from host: %s to %s' % (self.name, systemVmData.hostname, host.name))
            self.cloud.marvin.cloudApi.migrateSystemVm(hostid=host.id, virtualmachineid=systemVmData.id)
        else:
            xenrt.TEC().logverbose('System VM [%s] already on host: %s' % (self.name, host.name))

class _TCCloudSystemVMResiliencyBase(xenrt.TestCase):
    """Base class for CCP System VM resiliency tests"""

    def prepare(self, arglist):
        args = self.parseArgsKeyValue(arglist)
        self.cloud = self.getDefaultToolstack()
        pods = self.cloud.marvin.cloudApi.listPods()
        xenrt.xrtAssert(len(pods) == 1, 'There must be 1 and only 1 pod configured for this test-case')

        systemVmType = 'secondarystoragevm'
        if args.has_key('systemvmtype'):
            systemVmType = args['systemvmtype']

        self.systemVm = SystemVM.systemVMFactory(self.cloud, self.getAllHosts(), podid=pods[0].id, systemvmtype=systemVmType)[0]

        # Check that the system VM is healthy before the test
        self.systemVm.waitForReady()

    def _doResiliencyTest(self, arglist):
        raise xenrt.XRTError('This must be overridden in derived classes')

    def verifySystemVMRecovery(self, arglist):
        self._doResiliencyTest(arglist)
        # Wait for resiliency action to change the state of the system VM
        xenrt.sleep(10)
        self.systemVm.waitForReady()

    def run(self, arglist):
        hosts = self.cloud.marvin.cloudApi.listHosts(type='Routing')
        for host in hosts:
            self.systemVm.migrateToHost(host)
            self.systemVm.waitForReady()
            self.runSubcase('verifySystemVMRecovery', (arglist), 'SystemVMRecovery', 'Host=%s' % (host.name))

    def postRun(self):
        # If the system VM is not running try a force shutdown to reset the state
        try:
            self.systemVm.waitForReady()
        except Exception, e:
            self.systemVm.forcedStop()
            self.systemVm.waitForReady()

class TCSystemVMOpsResiliency(_TCCloudSystemVMResiliencyBase):

    def _doResiliencyTest(self, arglist):
        args = self.parseArgsKeyValue(arglist)
        xenrt.xrtAssert(args.has_key('systemvmoperation'), 'TCSystemVMOpsResiliency requires an systemvmoperation argument')
        xenrt.xrtAssert(hasattr(self.systemVm, args['systemvmoperation']), 'systemvmoperation must be a valid method on SystemVM object')
        getattr(self.systemVm, args['systemvmoperation'])()

class _TCCloudResiliencyBase(xenrt.TestCase):
    def prepare(self, arglist):
        self.cloud = self.getDefaultToolstack()
        self.instances = []
        args = self.parseArgsKeyValue(arglist)
        for zone in self.cloud.marvin.cloudApi.listZones():
            self.instances += self.createInstances(zoneName=zone.name,
                                                   distroList=args.has_key('distros') and args['distros'].split(','))
        map(lambda x:x.assertHealthy(), self.instances)

    def createInstances(self, zoneName, distroList=None, instancesPerDistro=1):
        instances = []
        zoneid = self.cloud.marvin.cloudApi.listZones(name=zoneName)[0].id
        # Use existing templates (if any)
        existingTemplates = self.cloud.marvin.cloudApi.listTemplates(templatefilter='all', zoneid=zoneid)
        templateList = filter(lambda x:x.templatetype != 'SYSTEM' and x.templatetype != 'BUILTIN', existingTemplates)

        if len(templateList) != 0:
            # Use the template names
            templateList = map(lambda x:x.name, templateList)
        else:
            # Create templates based on the distro list
            for distro in distroList:    
                distroName = distro.replace('_','-')
                instance = self.cloud.createInstance(distro=distro, name='%s-template' % (distroName))
                templateName = '%s-tplt' % (distroName)
                self.cloud.createTemplateFromInstance(instance, templateName)
                instance.destroy()
                templateList.append(templateName)

        xenrt.TEC().logverbose('Using templates: %s' % (','.join(templateList)))

        # Create instances
        for templateName in templateList:
            instances += map(lambda x:self.cloud.createInstanceFromTemplate(templateName=templateName, 
                                                                            name='%s-%d' % (templateName.replace("_","-"), x)), range(instancesPerDistro))
        return instances

    def destroyInstances(self):
        [x.destroy() for x in self.instances]
        self.instances = []

    def postRun(self):
        self.destroyInstances()

    def logCloudHostInfo(self):
        """Log CCP state information about all Hypervisor Hosts and Host up-time information (XS only)"""
        keysToLog = ['state', 'events', 'lastpinged', 'disconnected', 'created', 'resourcestate']
        hosts = self.cloud.marvin.cloudApi.listHosts(type='Routing')
        for host in hosts:
            if host.hypervisor == 'XenServer':
                try:
                    h = filter(lambda x:x.getName() == host.name, self.getAllHosts())[0]
                    xenrt.TEC().logverbose('[%s] BOOT-TIME: %s' % (host.name, datetime.fromtimestamp(int(float(h.getHostParam("other-config", "boot_time")))).strftime('%d-%m %H:%M')))
                    xenrt.TEC().logverbose('[%s] XAPI-TIME: %s' % (host.name, datetime.fromtimestamp(int(float(h.getHostParam("other-config", "agent_start_time")))).strftime('%d-%m %H:%M')))
                    if h == h.pool.master:
                        xenrt.TEC().logverbose('Current Master: %s: [uuid=%s]' % (host.name, h.uuid))
                        xenrt.TEC().logverbose('VM State:\n' + pformat(h.parameterList(command='vm-list', params=['name-label', 'power-state', 'resident-on'], argsString='is-control-domain=false')))
                except Exception, e:
                    xenrt.TEC().logverbose('Reg:\n' + pformat(xenrt.TEC().registry.__dict__))
                    xenrt.TEC().logverbose('Could not get data from XS Host [%s]: Exception: %s' % (host.name, str(e)))
            map(lambda x:xenrt.TEC().logverbose('[%s] %20s = %s' % (host.name, x, getattr(host, x))), keysToLog)

    def diffZoneCapacityWithCurrent(self, zoneid, oldCapacityData=[], capacityTypeIdList=None):
        """Compare CCP reported capacity data with a previous reading.
           When called with just zoneid specifed this will just return the current
           capacity data"""
        newCapacityData = self.cloud.marvin.cloudApi.listCapacity(zoneid=zoneid)
        capacityDataChanged = False
        for oldCapacity in oldCapacityData:
            newCapacity = filter(lambda x:x.type == oldCapacity.type, newCapacityData)
            xenrt.xrtAssert(len(newCapacity) == 1, 'Inconsistent capacity data reported by MS')
            if oldCapacity.__dict__ != newCapacity[0].__dict__:
                diffLogStr = 'DIFF IGNORED: '
                if capacityTypeIdList == None or oldCapacity.type in capacityTypeIdList:
                    diffLogStr = 'DIFF DETECTED: '
                    capacityDataChanged = True
                xenrt.TEC().logverbose(diffLogStr + 'TYPE: %d: Old capacity: %s, new capacity: %s' % (oldCapacity.type, pformat(oldCapacity), pformat(newCapacity[0])))
        return (capacityDataChanged, newCapacityData)

    def waitForCCP(self):
        deadline = xenrt.timenow() + 600
        while True:
            try:
                pods = self.cloud.marvin.cloudApi.listPods()
                break
            except:
                if xenrt.timenow() > deadline:
                    raise xenrt.XRTFailure("Cloudstack Management did not come back after 10 minutes")
                xenrt.sleep(15)
        for pod in pods:
            self.waitForHostState(podid=pod.id, state='Up', timeout=600)

    def waitForSystemVmAgentState(self, podid, state, timeout=300, pollPeriod=20, exitState=False):
        """Wait for all System VMs (associated with the Pod) to reach the specified state"""
        allSystemVmsReachedState = False
        startTime = datetime.now()
        while (datetime.now() - startTime).seconds < timeout:
            systemVmData = self.cloud.marvin.cloudApi.listSystemVms(podid=podid)
            systemVmNameList = map(lambda x:x.name, systemVmData)
            hostData = filter(lambda x:x.name in systemVmNameList, self.cloud.marvin.cloudApi.listHosts())
            self.logCloudHostInfo()
            if len(systemVmData) != len(hostData):
                xenrt.TEC().warning('Inconsistent System VM and Host data reported by MS')
            xenrt.TEC().logverbose('System VM State: %s' % (pformat(map(lambda x:(x.name, x.state), systemVmData))))
            if not exitState:
                systemVmsNotInState = filter(lambda x:x.state != state, hostData)
                if len(systemVmsNotInState) == 0:
                    if state == 'Up':
                        # Check that the system VMs are also all Running
                        systemVmsUpButNotInRunningState = filter(lambda x:x.state != 'Running', systemVmData)
                        if len(systemVmsUpButNotInRunningState) > 0:
                            xenrt.TEC().warning('System VM(s) %s reported as Up but not Running' % (pformat(map(lambda x:(x.name, x.state), systemVmsUpButNotInRunningState))))
                            continue

                    xenrt.TEC().logverbose('System VMs [%s] reached state: %s in %d sec' % (systemVmNameList, state, (datetime.now() - startTime).seconds))
                    allSystemVmsReachedState = True
                    break
                else:
                    xenrt.TEC().logverbose('Waiting for the following system VMs to reach state %s: %s' % (state, pformat(map(lambda x:(x.name, x.state), systemVmsNotInState))))
                    xenrt.sleep(pollPeriod)
            else:
                systemVmsStillInState = filter(lambda x:x.state == state, hostData)
                if len(systemVmsStillInState) == 0:
                    xenrt.TEC().logverbose('System VMs [%s] exited state: %s in %d sec' % (systemVmNameList, state, (datetime.now() - startTime).seconds))
                    xenrt.TEC().logverbose('  New States: %s' % (pformat(map(lambda x:(x.name, x.state), hostData))))
                    allSystemVmsReachedState = True
                    break
                else:
                    xenrt.TEC().logverbose('Waiting for the following system VMs to exit state %s: %s' % (state, pformat(map(lambda x:(x.name, x.state), systemVmsStillInState))))
                    xenrt.sleep(pollPeriod)

        self.logCloudHostInfo()
        if not allSystemVmsReachedState:
            raise xenrt.XRTFailure('Not all System VMs %s state %s in %d seconds' % (exitState and 'exited' or 'reached', state, timeout))

    def waitForHostState(self, podid, state, timeout=300, pollPeriod=20):
        """Wait for all Hosts (associated with the Pod) to reach the specified state"""
        allHostsReachedState = False
        startTime = datetime.now()
        while (datetime.now() - startTime).seconds < timeout:
            hostData = self.cloud.marvin.cloudApi.listHosts(type='Routing', podid=podid)
            allHypervisorsUp = True
            for host in hostData:
                if host.hypervisor == 'XenServer':
                    try:
                        h = filter(lambda x:x.getName() == host.name, self.getAllHosts())[0]
                        h.checkHealth()
                    except Exception, e:
                        xenrt.TEC().logverbose('Health check for host: %s failed' % (host.name))
                        allHypervisorsUp = False

            hostsNotInState = filter(lambda x:x.state != state, hostData)
            if len(hostsNotInState) == 0 and allHypervisorsUp:
                allHostsReachedState = True
                break

            if len(hostsNotInState) > 0:
                xenrt.TEC().logverbose('Waiting for the following Hosts to reach state %s: %s' % (state, pformat(map(lambda x:(x.name, x.state), hostsNotInState))))
            self.logCloudHostInfo()
            xenrt.sleep(pollPeriod)

        self.logCloudHostInfo()
        if not allHostsReachedState:
            raise xenrt.XRTFailure('Not all Hosts reached state %s in %d seconds' % (state, timeout))

    def waitForUserInstanceState(self, instanceNames, state, timeout=300, pollPeriod=20):
        """Wait for all User Instances (specified) to reach the specified state"""
        xenrt.xrtAssert(len(instanceNames) > 0, 'No instance names specifed in call to waitForUserInstanceState')
        allInstancesReachedState = False
        startTime = datetime.now()
        while (datetime.now() - startTime).seconds < timeout:
            instanceData = filter(lambda x:x.name in instanceNames, self.cloud.marvin.cloudApi.listVirtualMachines())
            xenrt.xrtAssert(len(instanceNames) == len(instanceData), 'Did not find instance records for all specified isntance names')   

            instancesNotInState = filter(lambda x:x.state != state, instanceData)
            if len(instancesNotInState) == 0:
                allInstancesReachedState = True
                break
            else:
                xenrt.TEC().logverbose('Waiting for the following User Instances to reach state %s: %s' % (state, pformat(map(lambda x:(x.name, x.state), instancesNotInState))))
                xenrt.sleep(pollPeriod)

        if not allInstancesReachedState:
            raise xenrt.XRTFailure('Not all User Instances reached state %s in %d seconds' % (state, timeout))

class TCPriStoreSysVMs(_TCCloudResiliencyBase):
    """Primary Storage Resiliency for System VMs"""
    VERIFY_USER_INSTANCES = False

    def prepare(self, arglist):
        self.cloud = self.getDefaultToolstack()
        self.instances = []

        zones = self.cloud.marvin.cloudApi.listZones()
        xenrt.xrtAssert(len(zones) == 1, 'There must be 1 and only 1 zone configured for this test-case')
        self.zoneid = zones[0].zoneid

        pods = self.cloud.marvin.cloudApi.listPods()
        xenrt.xrtAssert(len(pods) == 1, 'There must be 1 and only 1 pod configured for this test-case')
        self.podid = pods[0].id
     
        if self.VERIFY_USER_INSTANCES:
            distros = ['centos59_x86-32', 'win7sp1-x86']
            self.instances = self.createInstances(zoneName=zones[0].name, distroList=distros, instancesPerDistro=1)
            map(lambda x:x.assertHealthy(), self.instances)

        # Check all System VMs are ok before the test is run
        self.waitForSystemVmAgentState(self.podid, state='Up', timeout=60)

        args = self.parseArgsKeyValue(arglist)
        storageVMName = args.has_key('storageVM') and args['storageVM'] or None
        self.storageVM = xenrt.TEC().registry.guestGet(storageVMName)
        self.storageVM.checkHealth()

    def verifySystemVMsRecoverFromOutage(self):
        systemVms = self.cloud.marvin.cloudApi.listSystemVms(podid=self.podid)
        cpvms = filter(lambda x:x.systemvmtype == 'consoleproxy', systemVms)
        ssvms = filter(lambda x:x.systemvmtype == 'secondarystoragevm', systemVms)
        xenrt.xrtAssert(len(cpvms) + len(ssvms) == len(systemVms), 'Unexpected System VM type reported')

        (ignore, originalCapacity) = self.diffZoneCapacityWithCurrent(zoneid=self.zoneid)

        # Stop the storage VM (simulate the outage)
        self.storageVM.shutdown(force=True)
        # Wait for the system VMs to exit the Up state
        self.waitForSystemVmAgentState(self.podid, state='Up', timeout=600, exitState=True)
        
        self.storageVM.start()
        # Wait for the system VMs to recover
        self.waitForSystemVmAgentState(self.podid, state='Up', timeout=1200)

        # Check the number of system VMs has not changed
        newsystemVms = self.cloud.marvin.cloudApi.listSystemVms(podid=self.podid)
        newcpvms = filter(lambda x:x.systemvmtype == 'consoleproxy', newsystemVms)
        newssvms = filter(lambda x:x.systemvmtype == 'secondarystoragevm', newsystemVms)
        xenrt.xrtAssert(len(newcpvms) + len(newssvms) == len(newsystemVms), 'Unexpected System VM type reported')
        xenrt.xrtAssert(len(cpvms) == len(newcpvms), 'Number of Console Proxy VMs not the same after outage')
        xenrt.xrtAssert(len(ssvms) == len(newssvms), 'Number of Secondary Storage VMs not the same after outage')

        # Chkec all Hosts are Up and then recheck that all System VMs are still up
        self.waitForHostState(self.podid, state='Up', timeout=600)
        self.waitForSystemVmAgentState(self.podid, state='Up', timeout=300)

        if self.VERIFY_USER_INSTANCES:
            self.waitForUserInstanceState(instanceNames=map(lambda x:x.name, self.instances), state='Running', timeout=300)

            for instance in self.instances:
                try:
                    instance.assertHealthy()
                except Exception, e:
                    # VMs may fail when their disks are removed - reboot any VMs that are not responding
                    xenrt.TEC().logverbose('Instance: %s health check failed with: %s' % (instance.name, str(e)))
                    xenrt.TEC().logverbose('Reboot instance: %s' % (instance.name))
                    instance.reboot()

            self.waitForUserInstanceState(instanceNames=map(lambda x:x.name, self.instances), state='Running', timeout=300)
            map(lambda x:x.assertHealthy(), self.instances)

            # Verify that all VRs are running
            nonRunningVRs = filter(lambda x:x.state != 'Running', self.cloud.marvin.cloudApi.listRouters(listall='true'))
            if len(nonRunningVRs) > 0:
                xenrt.TEC().logverbose('VRs not in Running state: %s' % (pformat(map(lambda x:(x.name, x.state), nonRunningVRs))))
                raise xenrt.XRTFailure('VR(s) not recovered after Primary Storage Outage')

        (ignore, originalCapacity) = self.diffZoneCapacityWithCurrent(zoneid=self.zoneid, oldCapacityData=originalCapacity)
        # TODO - Run CCP health check

    def run(self, arglist):
        hosts = self.cloud.marvin.cloudApi.listHosts(type='Routing')
        for host in hosts:
            # Move all system VMs and routers to this host
            systemVMsNotOnThisHost = filter(lambda x:x.hostname != host.name, self.cloud.marvin.cloudApi.listSystemVms())
            xenrt.TEC().logverbose('Migrating System VMs %s to host: %s' % (map(lambda x:x.name, systemVMsNotOnThisHost), host.name))
            map(lambda x:self.cloud.marvin.cloudApi.migrateSystemVm(hostid=host.id, virtualmachineid=x.id), systemVMsNotOnThisHost)
            self.waitForSystemVmAgentState(self.podid, state='Up', timeout=60)

            # Move all instances to this host
            instancesNotOnThisHost = filter(lambda x:x.residentOn != host.name, self.instances)
            xenrt.TEC().logverbose('Migrating insstances %s to hosts: %s' % (map(lambda x:x.name, instancesNotOnThisHost), host.name))
            map(lambda x:x.migrate(to=host.name), instancesNotOnThisHost)
            if len(self.instances) > 0:
                self.waitForUserInstanceState(instanceNames=map(lambda x:x.name, self.instances), state='Running', timeout=300)

            self.runSubcase('verifySystemVMsRecoverFromOutage', (), 'SysVMPriStoreResiliency', 'Host=%s' % (host.name))

class TCPriStoreUserVMs(TCPriStoreSysVMs):
    """Primary Storage Resiliency for User Instances"""
    VERIFY_USER_INSTANCES = True

class _TCManServerResiliencyBase(_TCCloudResiliencyBase):

    def recover(self):
        pass

    def specificCheck(self):
        pass

    def genericCheck(self):
        map(lambda x:x.assertHealthy(), self.instances)
        # TODO - Check CCP health

    def run(self, arglist):
        self.args = self.parseArgsKeyValue(arglist)
        iterations = self.args.has_key('iterations') and self.args['iterations'] or 3

        for i in range(iterations):
            self.runSubcase('outage', (), 'Outage', 'Iter-%d' % (i))
            self.runSubcase('recover', (), 'Recover', 'Iter-%d' % (i))
            self.runSubcase('specificCheck', (), 'SpecificCheck', 'Iter-%d' % (i))
            self.runSubcase('genericCheck', (), 'GenericCheck', 'Iter-%d' % (i))

    def postRun(self):
        # See if the management server is behaving, if not, restart it
        try:
            self.cloud.cloudApi.listHosts()
        except:
            self.cloud.mgtsvr.restart()
        self.waitForCCP()
        _TCCloudResiliencyBase.postRun(self)

class TCManServerVMReboot(_TCManServerResiliencyBase):
    
    def outage(self):
        msvm = self.cloud.mgtsvr.place
        msvm.reboot()

    def recover(self):
        self.waitForCCP()


class TCManServerRestart(_TCManServerResiliencyBase):
    
    def outage(self):
        msvm = self.cloud.mgtsvr.place
        msvm.execcmd("service cloudstack-management restart")

    def recover(self):
        self.waitForCCP()


class TCDBRestart(_TCManServerResiliencyBase):
    
    def outage(self):
        dbvm = self.cloud.mgtsvr.dbServer
        db = self.cloud.mgtsvr.db
        dbvm.execcmd("service %s restart" % db)

    def recover(self):
        self.waitForCCP()


class TCDBOutage(_TCManServerResiliencyBase):
    
    def outage(self):
        dbvm = self.cloud.mgtsvr.dbServer
        db = self.cloud.mgtsvr.db
        dbvm.execcmd("service %s stop" % db)
        xenrt.sleep(120)
        dbvm.execcmd("service %s start" % db)

    def recover(self):
        self.waitForCCP()

class TCManServerStartAfterDB(_TCManServerResiliencyBase):
    
    def outage(self):
        msvm = self.cloud.mgtsvr.place
        dbvm = self.cloud.mgtsvr.dbServer
        db = self.cloud.mgtsvr.db
        dbvm.execcmd("service %s stop" % db)
        msvm.execcmd("service cloudstack-management stop")
        
        msvm.execcmd("service cloudstack-management start")
        
        xenrt.sleep(120)

        dbvm.execcmd("service %s start" % db)

    def recover(self):
        self.waitForCCP()

class _TCHostResiliencyBase(_TCCloudResiliencyBase):

    csHost = None

    def _updateParameters(self):

        self._hypervisors = self.cloud.getAllHypervisors()
        self._systemVMs = self._cloudApi.listSystemVms()

    def _populateParam(self):

        self.cloud = self.getDefaultToolstack()
        self._cloudApi = self.cloud.cloudApi
        self._hypervisors = self.cloud.getAllHypervisors()
        self._systemVMs = self._cloudApi.listSystemVms()
        self._clusters = self._cloudApi.listClusters()
        self._pods = self._cloudApi.listPods()
        xenrt.xrtAssert(len(self._pods) == 1, 'There must be 1 and only 1 pod configured for this test-case')

        self._hostsInClusters = []
        for cluster in self._clusters:
            self._hostsInClusters.append(self.cloud.getAllHostInClusterByClusterId(cluster.id))

    def _rearrangeCloud(self,hostInDiffCluster,hostForSystemVm,hostForInstance):

        #moving all the system VMs to the given host
        systemVMsNotOnThisHost = []
        systemVMsToBeMoved = []
        systemVMsNotOnThisHost = filter(lambda x:x.hostname != hostForSystemVm.name, self._systemVMs)
        map(lambda x:xenrt.TEC().logverbose("[MigratesystemVM] VM name %s, host name %s" % (x.name,x.hostname)),self._systemVMs)
        if systemVMsNotOnThisHost:
            systemVMsToBeMoved  = filter(lambda x:x.hostname != hostInDiffCluster.name, systemVMsNotOnThisHost)
            if systemVMsToBeMoved:
                xenrt.TEC().logverbose("[MigratesystemVM] VMs to be migrated %s, to be migrated on %s " % (systemVMsToBeMoved,hostForSystemVm))
                xenrt.TEC().logverbose('[MigratesystemVM] Migrating System VMs %s to host: %s' % (map(lambda x:x.name, systemVMsToBeMoved), hostForSystemVm.name))
                map(lambda x:self._cloudApi.migrateSystemVm(hostid=hostForSystemVm.id, virtualmachineid=x.id), systemVMsToBeMoved)
                self.waitForSystemVmAgentState(self._pods[0].id, state='Up', timeout=60)

        #creating vm instance on the other host
        self._instance = self.cloud.createInstance(distro="debian70_x86-64",startOn = hostForInstance.name)

    def _destroyInstance(self):

        self._instance.destroy() 

    def outage(self,host,csHost):

        raise xenrt.XRTError("Unimplemented")

    def recover(self,host):

        raise xenrt.XRTError("Unimplemented")

    def postOutageCheck(self):

        xenrt.sleep(900)
        if self.csHost.state != 'Down':
            raise xenrt.XRTFailure("Host %s is not reported Down by Cloud" % self.csHost.name)

        self.cloud.healthCheck(ignoreHosts=[self.csHost])

    def postRecoverCheck(self):

        xenrt.sleep(900)
        self.cloud.healthCheck()    

    def _getMultipleHostCluster(self):

        multipleHost = []
        for host in self._hostsInClusters:
            if len(host) > 1:
                multipleHost = host
                break
        return multipleHost

    def _getSingleHostCluster(self):

        singleHost = []
        for host in self._hostsInClusters:
            if len(host) == 1:
                singleHost = host
                break
        return singleHost

    def prepare(self,arglist):

        self._populateParam()
 
    def _resilliencyTest(self,xrtHost,csHost):

        self.csHost = csHost
        self.runSubcase('outage', (xrtHost,csHost), 'Outage', 'Host-%s' % (csHost.name))
        self.runSubcase('postOutageCheck',(),'PostOutageCheck','Host-%s' % (csHost.name))
        self.runSubcase('recover',(xrtHost),'Recover','Host-%s' % (csHost.name))
        self.runSubcase('postRecoverCheck',(),'PostRecoverCheck','Host-%s' % (csHost.name))
        self._destroyInstance()
 
    def run(self,arglist):

        multipleHost = []
        singleHost = []
        multipleHost = self._getMultipleHostCluster()
        singleHost = self._getSingleHostCluster()

        h1 = xenrt.TEC().registry.hostFind(multipleHost[0].name)[0]
        h2 = xenrt.TEC().registry.hostFind(multipleHost[1].name)[0]

        self._rearrangeCloud(singleHost[0],multipleHost[0],multipleHost[1])
        self._resilliencyTest(h1,multipleHost[0]) 

        self._updateParameters()
        self._rearrangeCloud(singleHost[0],multipleHost[1],multipleHost[1])
        self._resilliencyTest(h1,multipleHost[0])

        self._updateParameters()
        self._rearrangeCloud(singleHost[0],multipleHost[0],multipleHost[0])
        self._resilliencyTest(h2,multipleHost[1])

        self._updateParameters()
        self._rearrangeCloud(singleHost[0],multipleHost[1],multipleHost[0])
        self._resilliencyTest(h2,multipleHost[1])

class TCRebootHost(_TCHostResiliencyBase):

    def outage(self,host,csHost):

        host.reboot()

    def recover(self,host):

        xenrt.TEC().logverbose("Not Required")
        pass

    def postOutageCheck(self):

        xenrt.TEC().logverbose("Not Required")
        pass
 
class TCBlockTrafficHost(_TCHostResiliencyBase): 

    def outage(self,host,csHost):

        nic = host.getDefaultInterface()
        macAddress = host.getNICMACAddress(int(re.findall(r'\d+',nic)[0]))
        host.disableNetPort(macAddress)

    def recover(self,host):

        nic = host.getDefaultInterface()
        macAddress = host.getNICMACAddress(int(re.findall(r'\d+',nic)[0]))
        host.enableNetPort(macAddress)

class TCShutdownHost(_TCHostResiliencyBase):

    def outage(self,host,csHost):

        host.poweroff()

    def recover(self,host):

        host.poweron()

class TCXapiStopped(_TCHostResiliencyBase):

    def outage(self,host,csHost):

        if csHost.hypervisor != "XenServer":
            msg = "This testcase is only valid for Xenserver and not for any other Hypervisor"
            xenrt.TEC().logverbose(msg)
            raise xenrt.XRTError(msg)
  
        host.execdom0("service xapi stop")

    def recover(self,host):

        host.execdom0("service xapi start")

class TCBlockVcenter(_TCHostResiliencyBase):

    def outage(self,host,csHost):

        if csHost.hypervisor != "VMware":
            msg = "This testcase is only valid for VMWare and not for any other Hypervisor"
            xenrt.TEC().logverbose(msg)
            raise xenrt.XRTError(msg)

        ms=xenrt.TEC().registry.guestGet('CS-MS')
        vc = xenrt.TEC().lookup("VCENTER")
        ms.execcmd("iptables -I INPUT -s %s -j DROP" % (vc['ADDRESS']))
        ms.execcmd("iptables -I OUTPUT -s %s -j DROP" % (vc['ADDRESS']))
 
    def recover(self,host):

        ms=xenrt.TEC().registry.guestGet('CS-MS')
        vc = xenrt.TEC().lookup("VCENTER")
        ms.execcmd("iptables -D INPUT -s %s -j DROP" % (vc['ADDRESS']))
        ms.execcmd("iptables -D OUTPUT -s %s -j DROP" % (vc['ADDRESS']))        

    def postOutageCheck(self):

        xenrt.sleep(900)
        for host in self._hypervisors:
            if host.state != 'Alert':
                raise xenrt.XRTFailure("Host %s is not reported Alert by Cloud" % self.csHost.name)

    def run(self,arglist):

        multipleHost = []
        singleHost = []
        multipleHost = self._getMultipleHostCluster()
        singleHost = self._getSingleHostCluster()

        h1 = xenrt.TEC().registry.hostFind(multipleHost[0].name)[0]
        h2 = xenrt.TEC().registry.hostFind(multipleHost[1].name)[0]

        self._rearrangeCloud(singleHost[0],multipleHost[0],multipleHost[1])
        self._resilliencyTest(h1,multipleHost[0])
 
