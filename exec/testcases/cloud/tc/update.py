import xenrt
from datetime import datetime
import random


class CloudRollingUpdate(xenrt.lib.xenserver.host.RollingPoolUpdate):
    def preMasterUpdate(self):
        self.upgradeHook.call(self.newPool.master, True, True)
        xenrt.lib.xenserver.host.RollingPoolUpdate.preMasterUpdate(self)

    def postMasterUpdate(self):
        self.upgradeHook.call(self.newPool.master, False, True)
        xenrt.lib.xenserver.host.RollingPoolUpdate.postMasterUpdate(self)

    def preSlaveUpdate(self, slave):
        self.upgradeHook.call(slave, True, False)
        xenrt.lib.xenserver.host.RollingPoolUpdate.preSlaveUpdate(self, slave)

    def postSlaveUpdate(self, slave):
        self.upgradeHook.call(slave, False, False)
        xenrt.lib.xenserver.host.RollingPoolUpdate.postSlaveUpdate(self, slave)

    def doUpdateHost(self, host):
        if self.upgradeHook.noUpdate:
            xenrt.TEC().logverbose('SKIPPING Update Host: %s' % (host.getName()))
        else:
            xenrt.lib.xenserver.host.RollingPoolUpdate.doUpdateHost(self, host)

class TCCloudUpdate(xenrt.TestCase):

    def tailorBuiltInTemplate(self, template):
        """Make a built-in template look like a tempalte created by XenRT"""
        if 'password' not in xenrt.TEC().lookup('ROOT_PASSWORDS'):
            xenrt.TEC().config.setVariable('ROOT_PASSWORDS', 'password ' + xenrt.TEC().lookup('ROOT_PASSWORDS'))
            xenrt.TEC().logverbose('ROOT_PASSWORDS: %s' % (xenrt.TEC().lookup('ROOT_PASSWORDS')))
        if len(filter(lambda x:x.key == 'distro', template.tags)) == 0:
            if 'CentOS' in template.ostypename and '5.6' in template.ostypename and '64' in template.ostypename:
                self.cloud.marvin.cloudApi.createTags(resourceids=[template.id],
                                                resourcetype="Template",
                                                tags=[{"key":"distro", "value":'centos56_x86-64'}])
                xenrt.sleep(300)
            else:
                raise xenrt.XRTError('Unknown built in template type')

    def prepare(self, arglist):
        # Ignore hotfix options when running the lib upgrade code
        xenrt.TEC().config.setVariable("OPTION_NO_AUTO_PATCH", True)

        self.distros = []
        self.templates = {}
        self.instances = []

        self.cloud = self.getDefaultToolstack()

        args = self.parseArgsKeyValue(arglist)
        self.zone = self.cloud.marvin.cloudApi.listZones()[0]
        self.noUpdate = args.has_key('noupdate') and args['noupdate']=='true'
        if not args.has_key('distros'):
            existingTemplates = self.cloud.marvin.cloudApi.listTemplates(templatefilter='all', zoneid=self.zone.id)
            templatesToUse = filter(lambda x:x.templatetype != 'SYSTEM' and x.templatetype != 'BUILTIN', existingTemplates)
            if len(templatesToUse) == 0:
                templatesToUse = filter(lambda x:x.templatetype == 'BUILTIN', existingTemplates) 
                map(lambda x:self.tailorBuiltInTemplate(x), templatesToUse)
                templatesToUse = filter(lambda x:x.templatetype == 'BUILTIN', existingTemplates)

            xenrt.TEC().logverbose('Using existing templates: %s' % (','.join(map(lambda x:x.name, templatesToUse))))
            xenrt.TEC().logverbose(str(templatesToUse))
            for template in templatesToUse:
                distro = filter(lambda x:x.key == 'distro', template.tags)[0].value
                distroName = distro.replace('_','-')
                self.templates[distroName] = template.name
                self.distros.append(distro)
        else:
            # Create templates from list of specifed distros
            self.distros = args['distros'].split(',')
            for distro in self.distros:
                distroName = distro.replace('_','-')
                instance = self.cloud.createInstance(distro=distro, name='%s-template' % (distroName))
                templateName = '%s-tplt' % (distroName)
                self.cloud.createTemplateFromInstance(instance, templateName)
                instance.destroy()
                self.templates[distroName] = templateName

        for distro, template in self.templates.items():
            xenrt.TEC().logverbose('Distro: %s, Template: %s' % (distro, template))

        # Create instances
        # Determine how how many instances can be created based on capacity
        capacity = self.cloud.marvin.cloudApi.listCapacity(zoneid=self.zone.id, type=8)[0]
        instancesPerDistro = (capacity.capacitytotal - (capacity.capacityused + 6)) / len(self.distros)

        for distroName in self.templates.keys():
            self.instances += map(lambda x:self.cloud.createInstanceFromTemplate(templateName=self.templates[distroName], name='preUp-%s-%d' % (distroName, x)), range(instancesPerDistro))
#            self.instances += map(lambda x:self.cloud.existingInstance(name='preUp-%s-%d' % (distroName, x)), range(10))

    def setHostResourceState(self, host, maintenance):
        xenrt.TEC().logverbose('Set host: %s to maintenance = %s' % (host.getName(), maintenance))
        hostId = self.cloud.marvin.cloudApi.listHosts(name=host.getName())[0].id
        if maintenance:
            self.cloud.marvin.cloudApi.prepareHostForMaintenance(id=hostId)
        else:
            self.cloud.marvin.cloudApi.cancelHostMaintenance(id=hostId)

        expectedResourceState = maintenance and 'Maintenance' or 'Enabled'
        resourceState = None
        while(resourceState != expectedResourceState):
            xenrt.sleep(10)
            resourceState = self.cloud.marvin.cloudApi.listHosts(name=host.getName())[0].resourcestate
            xenrt.TEC().logverbose('Waiting for host: %s, Current Resource State: %s, Expected State: %s' % (host.getName(), resourceState, expectedResourceState))

    def setClusterManaged(self, clusterid, managed):
        self.cloud.marvin.cloudApi.updateCluster(id = clusterid,
                                              managedstate = managed and 'Managed' or 'Unmanaged')

        expectedClusterState = managed and 'Managed' or 'Unmanaged'
        expectedHostState = managed and 'Up' or 'Disconnected'

        correctStateReached = False
        while(not correctStateReached):
            xenrt.sleep(10)
            cluster = self.cloud.marvin.cloudApi.listClusters(id=clusterid)[0]
            xenrt.TEC().logverbose('Waiting for Cluster %s, Current state: Managed=%s, Alloc=%s, expected state: %s' % (cluster.name, cluster.managedstate, cluster.allocationstate, expectedClusterState))

            hostList = self.cloud.marvin.cloudApi.listHosts(clusterid=clusterid, type='Routing')
            hostListState = map(lambda x:x.state, hostList)
            xenrt.TEC().logverbose('Waiting for host(s) %s, Current State(s): %s' % (map(lambda x:x.name, hostList), hostListState))

            correctStateReached = (cluster.managedstate == expectedClusterState)
            if managed and correctStateReached:
                correctStateReached = len(hostList) == hostListState.count(expectedHostState)

    def call(self, host, preHook, master):
        xenrt.TEC().logverbose('hook called for host: %s, preHook: %s, master %s' % (host.getName(), preHook, master))
        if master:
            clusterId = self.cloud.marvin.cloudApi.listClusters()[0].id
            if preHook:
                self.setHostResourceState(host, maintenance=True)
                self.setClusterManaged(clusterId, False)
            else:
                self.setHostResourceState(host, maintenance=False)
                self.setClusterManaged(clusterId, True)
                self.verifyCloud(host, 'post-master')
        else:
            if preHook:
                self.setHostResourceState(host, maintenance=True)
                self.verifyCloud(host, 'pre-slave')
            else:
                self.verifyCloud(host, 'post-slave-maint')
                self.setHostResourceState(host, maintenance=False)
                self.verifyCloud(host, 'post-slave')

    def waitForInstancesToReachState(self, instances, state, timeout=60):
        startTime = datetime.now()
        while(True):
            instancesNotReachedState = filter(lambda x:x.getPowerState() != state, instances)
            timeTaken = (datetime.now() - startTime).seconds
            xenrt.TEC().logverbose('%d instances reached state: %s, waiting for %d' % (len(instances) - len(instancesNotReachedState), state, len(instancesNotReachedState)))
            if len(instancesNotReachedState) == 0:
                xenrt.TEC().logverbose('Instances reached the %s state in %d seconds' % (state, timeTaken))
                break
            elif timeTaken < timeout:
                xenrt.sleep(10)
            else:
                raise xenrt.XRTFailure('Timeout expired waiting for instances to reach %s state' % (state))
        return timeTaken

    def checkInstanceHealth(self, instance):
        xenrt.TEC().logverbose('Check health for instance [VM-Name: %s] IP Addr: %s' % (instance.name, instance.getIP()))
        instance.assertHealthy()

    def verifyCloud(self, hostUpdated, postFixString):
        newInstanceName = '%s-%s' % (postFixString, hostUpdated.getName())
        # Check all instances are running
        self.waitForInstancesToReachState(instances=self.instances, state=xenrt.PowerState.up, timeout=120)
        map(lambda x:self.checkInstanceHealth(x), self.instances)

        # Create new instance
        newInstances = map(lambda x:self.cloud.createInstanceFromTemplate(templateName=self.templates[x], name='%s-%s' % (newInstanceName, x)), self.templates.keys())

        # Create a temp instance
        tempInstances = map(lambda x:self.cloud.createInstanceFromTemplate(templateName=self.templates[x], name='temp-%s' % (x)), self.templates.keys())

        # Wait for new instances to reach the up state
        self.waitForInstancesToReachState(instances=newInstances+tempInstances, state=xenrt.PowerState.up, timeout=120)
        map(lambda x:self.checkInstanceHealth(x), newInstances+tempInstances)

        # Select 1 original instance of each distro at random
        preUpdateInstances = []
        for distro in self.distros:
            randomInstance = random.choice(filter(lambda x:x.distro == distro and x.name.startswith('preUp-'), self.instances))
            preUpdateInstances.append(randomInstance)

        # Lifecycle orginal + temp + new instance
        lifecycleInstances = preUpdateInstances + newInstances + tempInstances
        map(lambda x:x.stop(), lifecycleInstances)
        self.waitForInstancesToReachState(instances=lifecycleInstances, state=xenrt.PowerState.down, timeout=120)

        map(lambda x:x.start(), lifecycleInstances)
        self.waitForInstancesToReachState(instances=lifecycleInstances, state=xenrt.PowerState.up, timeout=120)

        map(lambda x:self.checkInstanceHealth(x), lifecycleInstances)

        # destroy original + temp instance
        map(lambda x:x.destroy(), preUpdateInstances+tempInstances)
       
        # Add / remove instances from test list
        map(lambda x:self.instances.remove(x), preUpdateInstances) 
        self.instances += newInstances

    def run(self, arglist):
        pool = self.getDefaultPool()
        pool_upgrade = CloudRollingUpdate(poolRef = pool,
                                          newVersion='Clearwater',
                                          upgrade = True,
                                          applyAllHFXsBeforeApplyAction=True,
                                          vmActionIfHostRebootRequired=None,
                                          preEvacuate=None,
                                          preReboot=None,
                                          skipApplyRequiredPatches=False)
        setattr(pool_upgrade, "upgradeHook", self)
        self.newPool = pool.upgrade(poolUpgrade=pool_upgrade)

