
import sys
import marvin
from marvin import cloudstackTestClient
from marvin.cloudstackAPI import *

import logging
import json
import time


class CSAPI(object):
    MS_USER = 'admin'
    MS_PASSWD = 'password'

    CS_API_LOG = 'csApiLogger'

    def __init__(self, mgtSvrIpAddr, logFilename='/tmp/csapilog.log'):
        self.logger = self._createLogger(logFilename)
        self.testCli = cloudstackTestClient.cloudstackTestClient(mgtSvr=mgtSvrIpAddr, user=self.MS_USER, passwd=self.MS_PASSWD, logging=self.logger)
        self.apiCli = self.testCli.getApiClient()

    def _createLogger(self, filename):
        logger = logging.getLogger(self.CS_API_LOG)
        fh = logging.FileHandler(filename)
        fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s"))
        logger.addHandler(fh)
        logger.setLevel(logging.INFO)

        return logger

    def execCmd(self, cmd):
        cliCmdName = str(cmd.__class__).split('.')[-2]
        func = getattr(self.apiCli, cliCmdName)
        resp = func(cmd)
        print "Response from [%s]: %s" % (cliCmdName, resp)
        return resp
       

def createXenRTDeployment(mgtSvrIpAddr, dnsAddr, gateway, netmask, publicRange, managementRange, storageRange, infraNetwork, guestNetwork, storageNetwork, guestCIDR, guestVLANRange, hostAddr, priStor, secStor):
    csapi = CSAPI(mgtSvrIpAddr) 

    zoneC = createZone.createZoneCmd()
    zoneC.name = 'TestZone'

    zoneC.dns1 = dnsAddr
    zoneC.internaldns1 = dnsAddr

    zoneC.networktype = 'Advanced'
    zoneC.guestcidraddress = guestCIDR

    resp = csapi.execCmd(zoneC)
    zoneId = resp.id

    phyNetIdList = []

    phyNetC = createPhysicalNetwork.createPhysicalNetworkCmd()
    phyNetC.name = 'Infrastructure-Network'
    phyNetC.zoneid = zoneId
    resp = csapi.execCmd(phyNetC)
    infraNetId = resp.id
    phyNetIdList.append(infraNetId)

    addTrafficTypeC = addTrafficType.addTrafficTypeCmd()
    addTrafficTypeC.physicalnetworkid = infraNetId
    addTrafficTypeC.traffictype = "Management"
    addTrafficTypeC.isolationmethods=['VLAN']
    addTrafficTypeC.xennetworklabel = infraNetwork
    resp = csapi.execCmd(addTrafficTypeC)

    addTrafficTypeC.traffictype = "Public"
    resp = csapi.execCmd(addTrafficTypeC)

    if storageNetwork:
        phyNetC.name = 'Storage-Network'
        resp = csapi.execCmd(phyNetC)
        storageNetId = resp.id
        phyNetIdList.append(storageNetId)

        addTrafficTypeC.physicalnetworkid = storageNetId
        addTrafficTypeC.traffictype = "Storage"
        addTrafficTypeC.xennetworklabel = storageNetwork        
    else:
        addTrafficTypeC.traffictype = "Storage"

    resp = csapi.execCmd(addTrafficTypeC)
    
    phyNetC.name = 'Guest-Network'
    resp = csapi.execCmd(phyNetC)
    guestNetId = resp.id
    phyNetIdList.append(guestNetId)

    addTrafficTypeC.physicalnetworkid = guestNetId
    addTrafficTypeC.traffictype = "Guest"
    addTrafficTypeC.xennetworklabel = guestNetwork
    resp = csapi.execCmd(addTrafficTypeC)

    updatePhyNetC = updatePhysicalNetwork.updatePhysicalNetworkCmd()
    updatePhyNetC.id = infraNetId
    updatePhyNetC.state = 'Enabled'
    resp = csapi.execCmd(updatePhyNetC) 

    if storageNetwork:
        updatePhyNetC.id = storageNetId
        resp = csapi.execCmd(updatePhyNetC)

    if guestVLANRange != None:
        updatePhyNetC.id = guestNetId
        updatePhyNetC.vlan = '%d-%d' % (guestVLANRange[0], guestVLANRange[1])
        resp = csapi.execCmd(updatePhyNetC)

    listNwServiceProvC = listNetworkServiceProviders.listNetworkServiceProvidersCmd()
    nwSPData = csapi.execCmd(listNwServiceProvC)

    for netId in phyNetIdList:
        nwSPs = filter(lambda x:x.physicalnetworkid == netId, nwSPData)
        for nwSP in nwSPs:
            if nwSP.name in ['VirtualRouter', 'VpcVirtualRouter']:
                listVirtualRouterElementsC = listVirtualRouterElements.listVirtualRouterElementsCmd()
                listVirtualRouterElementsC.nspid = nwSP.id
                resp = csapi.execCmd(listVirtualRouterElementsC)

                configureVirtualRouterElementC = configureVirtualRouterElement.configureVirtualRouterElementCmd()
                configureVirtualRouterElementC.enabled = 'true'
                configureVirtualRouterElementC.id = resp[0].id
                resp = csapi.execCmd(configureVirtualRouterElementC)
            
                updateNetworkServiceProviderC = updateNetworkServiceProvider.updateNetworkServiceProviderCmd()
                updateNetworkServiceProviderC.id = nwSP.id
                updateNetworkServiceProviderC.state = 'Enabled'
                resp = csapi.execCmd(updateNetworkServiceProviderC)

    guestLbSP = filter(lambda x:x.physicalnetworkid == guestNetId and x.name == 'InternalLbVm', nwSPData)[0]
    listIntLBElementsC = listInternalLoadBalancerElements.listInternalLoadBalancerElementsCmd()
    listIntLBElementsC.nspid = guestLbSP.id
    resp = csapi.execCmd(listIntLBElementsC)[0]

    confIntLBC = configureInternalLoadBalancerElement.configureInternalLoadBalancerElementCmd()
    confIntLBC.id = resp.id
    confIntLBC.enabled = 'true'
    resp = csapi.execCmd(confIntLBC)

    updateNetworkServiceProviderC = updateNetworkServiceProvider.updateNetworkServiceProviderCmd()
    updateNetworkServiceProviderC.id = guestLbSP.id
    updateNetworkServiceProviderC.state = 'Enabled'
    resp = csapi.execCmd(updateNetworkServiceProviderC)


    podC = createPod.createPodCmd()
    podC.name = 'Test Pod'
    podC.zoneid = zoneId
    podC.gateway = gateway
    podC.netmask = netmask
    podC.startip = managementRange[0]
    podC.endip = managementRange[1]
    resp = csapi.execCmd(podC)
    podId = resp.id


    clusterC = addCluster.addClusterCmd()
    clusterC.clustername = 'Test Cluster'
    clusterC.clustertype = 'CloudManaged'
    clusterC.hypervisor = 'XenServer'
    clusterC.podid = podId
    clusterC.zoneid = zoneId
    resp = csapi.execCmd(clusterC)
    clusterInfo = filter(lambda x:x.name == 'Test Cluster', resp)[0]
    clusterId = clusterInfo.id


    publicIpRangeC = createVlanIpRange.createVlanIpRangeCmd()
    publicIpRangeC.forvirtualnetwork = 'true'
    publicIpRangeC.vlan = 'untagged'
    publicIpRangeC.gateway = gateway
    publicIpRangeC.netmask = netmask
    publicIpRangeC.startip = publicRange[0]
    publicIpRangeC.endip = publicRange[1]
    publicIpRangeC.physicalnetworkid = infraNetId
    publicIpRangeC.zoneid = zoneId
    resp = csapi.execCmd(publicIpRangeC)

    storageIpRangeC = createStorageNetworkIpRange.createStorageNetworkIpRangeCmd()
    storageIpRangeC.podid = podId
    storageIpRangeC.gateway = gateway
    storageIpRangeC.netmask = netmask
    storageIpRangeC.startip = storageRange[0]
    storageIpRangeC.endip = storageRange[1]
    resp = csapi.execCmd(storageIpRangeC)

    hostC = addHost.addHostCmd()
    hostC.username = 'root'
    hostC.password = 'xenroot'
    hostC.hypervisor = 'XenServer'
#    hostC.clustername = 'Test Host'
    hostC.zoneid = zoneId
    hostC.podid = podId
    hostC.clusterid = clusterId
    hostC.url = 'http://'+hostAddr
    resp = csapi.execCmd(hostC)

    # Sleep added to allow the hosts to come up
    time.sleep(120)
    primaryStorageC = createStoragePool.createStoragePoolCmd()
    primaryStorageC.name = 'Cluster Primary Storage'
    primaryStorageC.zoneid = zoneId
    primaryStorageC.podid = podId
    primaryStorageC.clusterid = clusterId
    primaryStorageC.scope = 'cluster'
    primaryStorageC.url = 'presetup://localhost/%s' % (priStor)
    resp = csapi.execCmd(primaryStorageC)
 
    secondaryStorageC = addSecondaryStorage.addSecondaryStorageCmd()
    secondaryStorageC.zoneid = zoneId
    secondaryStorageC.url = 'nfs://%s' % (secStor)
    resp = csapi.execCmd(secondaryStorageC)

    # Enable the zone
    updateZoneC = updateZone.updateZoneCmd()
    updateZoneC.id = zoneId
    updateZoneC.allocationstate = 'Enabled'
    resp = csapi.execCmd(updateZoneC)

    # Wait for built in template to be ready
    templateId = None
    listTemplatesC = listTemplates.listTemplatesCmd()
    listTemplatesC.templatefilter = 'self'

    while True:
        resp = csapi.execCmd(listTemplatesC)
        builtinTemplates = filter(lambda x:x.templatetype == 'BUILTIN', resp)
        if len(builtinTemplates) > 1:
            raise Exception('>1 Built in templates found')
        if len(builtinTemplates) == 1:
            templateId = builtinTemplates[0].id
            break
        time.sleep(60)

    if templateId:
        listTemplatesC.id = templateId    
        while True:
            resp = csapi.execCmd(listTemplatesC)
            if resp[0].isready == True:
                break
 
    return csapi


if len(sys.argv) == 2:
    print 'Using config file: %s' % (sys.argv[1])
    conf = json.load(open(sys.argv[1]))

    createXenRTDeployment(**conf)

