import xenrt
from datetime import datetime
from pprint import pformat
import random


class CloudRollingUpdate(xenrt.lib.xenserver.host.RollingPoolUpdate):
    """Class for performing updates (upgrades or HFX install) on a
       pool of CloudPlatform managed XenServers"""

    def _logXenServerHfxStatus(self, host):
        patchList = host.parameterList('patch-list', params=['name-label', 'name-description'])
        patchList.sort(key=lambda x:x['name-label'])
        xenrt.TEC().logverbose('HFX Status for Host: %s\n' % (host.getName()) + pformat(patchList))

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
            xenrt.TEC().logverbose('CloudRollingUpdate member state:\n' + pformat(self.__dict__))
            xenrt.TEC().logverbose('SKIPPING Update Host: %s' % (host.getName()))
            host.reboot()
            xenrt.TEC().logverbose('Host %s rebooted' % (host.getName()))
            return

        # Ignore hotfix options when running the lib upgrade code
        xenrt.TEC().config.setVariable('OPTION_NO_AUTO_PATCH', True)
        self._logXenServerHfxStatus(host)
        if self.patch:
            xenrt.TEC().logverbose('Testing applying patch: %s on version: %s' % (self.patch, host.productVersion))
            self.upgrade = False
            self.skipApplyRequiredPatches = True
        elif not self.upgrade:
            # No patch has been specified and upgrade is not set.  Apply all released patches
            xenrt.TEC().logverbose('Testing released HFX apply for version: %s' % (host.productVersion))
            xenrt.TEC().config.setVariable('APPLY_ALL_RELEASED_HFXS', True)
        else:
            xenrt.TEC().logverbose('Testing upgrading from version: %s to version: %s' % (host.productVersion, self.newVersion))

        xenrt.TEC().logverbose('CloudRollingUpdate member state:\n' + pformat(self.__dict__))
        xenrt.lib.xenserver.host.RollingPoolUpdate.doUpdateHost(self, host)
        self._logXenServerHfxStatus(host)

class TCCloudUpdate(xenrt.TestCase):

    def _getTemplateNameStr(self, template):
        """Helper method to get a template string that can be
           used as part of an instnace name"""
        return template.displaytext.replace("_","-")

    def _logCapacity(self):
        zones = self.cloud.marvin.cloudApi.listZones(id=self.zoneid)
        xenrt.xrtAssert(len(zones) == 1, 'There must be 1 and only 1 zone for the stored zone ID')
        capacityTypeId = 8
        if zones[0].networktype == 'Advanced':
            capacityTypeId = 4

        capacityList = self.cloud.marvin.cloudApi.listCapacity(zoneid=self.zoneid, type=capacityTypeId)
        if capacityList == None or len(capacityList) != 1:
            xenrt.TEC().logverbose('Unable to read CCP capacity')

        xenrt.TEC().logverbose('CCP Address Capacity - Total: %d, Used: %d' % (capacityList[0].capacitytotal, capacityList[0].capacityused))

    def prepare(self, arglist):
        self.templates = []
        self.instances = []

        self.cloud = self.getDefaultToolstack()

        args = self.parseArgsKeyValue(arglist)
        self.noUpdate = args.has_key('noupdate') and args['noupdate']=='true'

        zones = self.cloud.marvin.cloudApi.listZones()
        xenrt.xrtAssert(len(zones) == 1, 'There must be 1 and only 1 zone configured for this test-case')
        self.zoneid = zones[0].id

        clusters = self.cloud.marvin.cloudApi.listClusters(zoneid=self.zoneid)
        xenrt.xrtAssert(len(clusters) == 1, 'There must be 1 and only 1 cluster configured for this test-case')
        self.cluster = clusters[0]

        existingTemplates = self.cloud.marvin.cloudApi.listTemplates(templatefilter='all', zoneid=self.zoneid)
        self.templates = filter(lambda x:x.templatetype != 'SYSTEM' and x.templatetype != 'BUILTIN', existingTemplates)

        hostList = self.cloud.marvin.cloudApi.listHosts(clusterid=self.cluster.id, type='Routing')
        xenrt.TEC().logverbose('Updating hosts %s' % (pformat(map(lambda x:x.name, hostList))))

        instancesPerTemplate = ( (len(hostList) - 1) * 3 ) + 2
        xenrt.TEC().logverbose('Creating %d instances per template in list %s' % (instancesPerTemplate, pformat(map(lambda x:x.name, self.templates))))
        self._logCapacity()

        # Create instances
        for template in self.templates:
            self.instances += map(lambda x:self.cloud.createInstanceFromTemplate(templateName=template.name,
                                                                            name='preUp-%s-%d' % (self._getTemplateNameStr(template), x)), range(instancesPerTemplate))
        xenrt.TEC().logverbose('Created the following instances: %s' % (pformat(map(lambda x:x.name, self.instances))))
        self._logCapacity()

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
        xenrt.TEC().logverbose('Check health for instance [VM-Name: %s]' % (instance.name))
        instance.assertHealthy()

    def verifyCloud(self, hostUpdated, postFixString):
        newInstanceName = '%s-%s' % (postFixString, hostUpdated.getName())
        # Check all instances are running
        self.waitForInstancesToReachState(instances=self.instances, state=xenrt.PowerState.up, timeout=120)
        map(lambda x:self.checkInstanceHealth(x), self.instances)
        self._logCapacity()

        # Create new instance
        newInstances = map(lambda x:self.cloud.createInstanceFromTemplate(templateName=x.name, name='%s-%s' % (newInstanceName, self._getTemplateNameStr(x))), self.templates)

        # Create a temp instance
        tempInstances = map(lambda x:self.cloud.createInstanceFromTemplate(templateName=x.name, name='temp-%s' % (self._getTemplateNameStr(x))), self.templates)

        # Wait for new instances to reach the up state
        self.waitForInstancesToReachState(instances=newInstances+tempInstances, state=xenrt.PowerState.up, timeout=120)
        map(lambda x:self.checkInstanceHealth(x), newInstances+tempInstances)

        # Select 1 original instance of each distro at random
        preUpdateInstances = []
        for template in self.templates:
            randomInstance = random.choice(filter(lambda x:x.name.startswith('preUp-%s' % (self._getTemplateNameStr(template))), self.instances))
            preUpdateInstances.append(randomInstance)

        xenrt.TEC().logverbose('New Instances:        %s' % (pformat(map(lambda x:x.name, newInstances))))
        xenrt.TEC().logverbose('Temp Instances:       %s' % (pformat(map(lambda x:x.name, tempInstances))))
        xenrt.TEC().logverbose('Pre-Update Instances: %s' % (pformat(map(lambda x:x.name, preUpdateInstances))))
        self._logCapacity()

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

        xenrt.TEC().logverbose('Current instances: %s' % (pformat(map(lambda x:x.name, self.instances))))
        self._logCapacity()

    def run(self, arglist):
        pool = self.getDefaultPool()
        pool_upgrade = CloudRollingUpdate(poolRef = pool,
                                          newVersion=None,
                                          upgrade = False,
                                          applyAllHFXsBeforeApplyAction=True,
                                          vmActionIfHostRebootRequired=None,
                                          preEvacuate=None,
                                          preReboot=None,
                                          skipApplyRequiredPatches=False)
        setattr(pool_upgrade, "upgradeHook", self)
        self.newPool = pool.upgrade(poolUpgrade=pool_upgrade)

    def postRun(self):
        map(lambda x:x.destroy(), self.instances)
