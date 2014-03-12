import xenrt
import logging
import os, urllib
from datetime import datetime

import xenrt.lib.cloud
try:
    from marvin import cloudstackTestClient
    from marvin.integration.lib.base import *
    from marvin import configGenerator
except ImportError:
    pass

__all__ = ["MarvinApi"]

class XenRTLogStream(object):
    def write(self, data):
        xenrt.TEC().logverbose(data.rstrip())

    def flush(self):
        pass

class MarvinApi(object):
    MARVIN_LOGGER = 'MarvinLogger'
    
    MS_USERNAME = 'admin'
    MS_PASSWORD = 'password'

    def __init__(self, mgtSvr):
        self.mgtSvr = mgtSvr
        self.xenrtStream = XenRTLogStream()
        logFormat = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
        self.logger = logging.getLogger(self.MARVIN_LOGGER)
        self.logger.setLevel(logging.DEBUG)
        stream = logging.StreamHandler(stream=self.xenrtStream)
        stream.setLevel(logging.DEBUG)
        stream.setFormatter(logFormat)
        self.logger.addHandler(stream)

        self.mgtSvrDetails = configGenerator.managementServer()
        self.mgtSvrDetails.mgtSvrIp = mgtSvr.place.getIP()
        self.mgtSvrDetails.user = self.MS_USERNAME
        self.mgtSvrDetails.passwd = self.MS_PASSWORD
        
        self.testClient = cloudstackTestClient.cloudstackTestClient(mgmtDetails=self.mgtSvrDetails, dbSvrDetails=None, logger=self.logger)
        self.apiClient = self.testClient.getApiClient()

        #TODO - Fix this
        self.apiClient.hypervisor = 'XenServer'

    def setCloudGlobalConfig(self, name, value, restartManagementServer=False):
        configSetting = Configurations.list(self.apiClient, name=name)
        if configSetting == None or len(configSetting) == 0:
            raise xenrt.XRTError('Could not find setting: %s' % (name))
        elif len(configSetting) > 1:
            configSetting = filter(lambda x:x.name == name, configSetting)
        xenrt.TEC().logverbose('Current value for setting: %s is %s, new value: %s' % (name, configSetting[0].value, value))
        if value != configSetting[0].value:
            Configurations.update(self.apiClient, name=name, value=value)
            if restartManagementServer:
                self.mgtSvr.restart()
        else:
            xenrt.TEC().logverbose('Value of setting %s already %s' % (name, value))

    def waitForTemplateReady(self, name):
        templateReady = False
        startTime = datetime.now()
        while((datetime.now() - startTime).seconds < 1800):
            templateList = Template.list(self.apiClient, templatefilter='all', name=name)
            if not templateList:
                xenrt.TEC().logverbose('Template %s not found' % (name))
            elif len(templateList) == 1:
                xenrt.TEC().logverbose('Template %s, is ready: %s, status: %s' % (name, templateList[0].isready, templateList[0].status))
                templateReady = templateList[0].isready
                if templateReady:
                    break
            else:
                raise xenrt.XRTFailure('>1 template found with name %s' % (name))

            xenrt.sleep(60)

        if not templateReady:
            raise xenrt.XRTFailure('Timeout expired waiting for template %s' % (name))

        xenrt.TEC().logverbose('Template %s ready after %d seconds' % (name, (datetime.now() - startTime).seconds))

    def copySystemTemplateToSecondaryStorage(self, storagePath, provider):
#        sysTemplateLocation = xenrt.TEC().lookup("CLOUD_SYS_TEMPLATE", 'http://download.cloud.com/templates/4.2/systemvmtemplate-2013-07-12-master-xen.vhd.bz2')
        sysTemplateiSrcLocation = xenrt.TEC().lookup("CLOUD_SYS_TEMPLATE", '/usr/groups/xenrt/cloud/systemvmtemplate-2013-07-12-master-xen.vhd.bz2')
        if not sysTemplateiSrcLocation:
            raise xenrt.XRTError('Location of system template not specified')
        xenrt.TEC().logverbose('Using System Template: %s' % (sysTemplateiSrcLocation))
        sysTemplateFile = xenrt.TEC().getFile(sysTemplateiSrcLocation)
        webdir = xenrt.WebDirectory()
        webdir.copyIn(sysTemplateFile)
        sysTemplateUrl = webdir.getURL(os.path.basename(sysTemplateFile))

        if provider == 'NFS':
            self.mgtSvr.place.execguest('mount %s /media' % (storagePath))
            installSysTmpltLoc = self.mgtSvr.place.execguest('find / -name *install-sys-tmplt').strip()
            self.mgtSvr.place.execguest('%s -m /media -u %s -h xenserver -F' % (installSysTmpltLoc, sysTemplateUrl), timeout=60*60)
            self.mgtSvr.place.execguest('umount /media')

    def addZone(self, name, networktype='Basic', dns1=None, internaldns1=None):
        args = locals()
        args['dns1'] = dns1 or xenrt.TEC().config.lookup(['NETWORK_CONFIG', 'DEFAULT', 'NAMESERVERS']).split(',')[0]    
        args['internaldns1'] = internaldns1 or xenrt.TEC().config.lookup(['NETWORK_CONFIG', 'DEFAULT', 'NAMESERVERS']).split(',')[0]
        return Zone.create(self.apiClient, args)

    def getZone(self, name=None, id=None):
        args = locals()
        xenrt.TEC().logverbose('Find Zone with args: %s' % (args))
        zoneData = Zone.list(self.apiClient, **args)
        if not zoneData:
            raise xenrt.XRTFailure('Could not find zone')
        if not len(zoneData) == 1:
            raise xenrt.XRTFailure('Could not find unique zone')

        return Zone(zoneData[0].__dict__)

    def addSecondaryStorage(self, zone, url=None, provider='NFS'):
        if not url:
            if provider == 'NFS':
                secondaryStorage = xenrt.ExternalNFSShare()
                storagePath = secondaryStorage.getMount()
                url = 'nfs://%s' % (secondaryStorage.getMount().replace(':',''))

            self.copySystemTemplateToSecondaryStorage(storagePath, provider) 

        secondaryStorageC = addSecondaryStorage.addSecondaryStorageCmd()
        secondaryStorageC.zoneid = zone.id
        secondaryStorageC.url = url
        return self.apiClient.addSecondaryStorage(secondaryStorageC)

    def addPhysicalNetwork(self, name, zone, trafficTypeList=[], networkServiceProviderList=[]):
        args = { 'name': name }
        phyNet = PhysicalNetwork.create(self.apiClient, args, zone.id)
        map(lambda x:phyNet.addTrafficType(self.apiClient, x), trafficTypeList)
        phyNet.update(self.apiClient, state='Enabled')

        networkServiceProvidersFull = NetworkServiceProvider.list(self.apiClient)
        servicesToEnable = filter(lambda x:x.name in networkServiceProviderList and x.physicalnetworkid == phyNet.id, networkServiceProvidersFull)
        if len(servicesToEnable) != len(networkServiceProviderList):
            xenrt.TEC().logverbose('Not all network service providers specifed can be found')

        for service in servicesToEnable:
            if 'VirtualRouter' in service.name:
                listVirtualRouterElementsC = listVirtualRouterElements.listVirtualRouterElementsCmd()
                listVirtualRouterElementsC.nspid = service.id
                vrElement = self.apiClient.listVirtualRouterElements(listVirtualRouterElementsC)[0]
                if vrElement.state != 'Enabled':
                    configureVirtualRouterElementC = configureVirtualRouterElement.configureVirtualRouterElementCmd()
                    configureVirtualRouterElementC.enabled = 'true'
                    configureVirtualRouterElementC.id = vrElement.id
                    self.apiClient.configureVirtualRouterElement(configureVirtualRouterElementC)

            NetworkServiceProvider.update(self.apiClient, id=service.id, state='Enabled')

        return phyNet

    def addNetwork(self, name, zone, vlan='untagged', networkOfferingName='DefaultSharedNetworkOfferingWithSGService'):
        args = locals()
        networkOffering = NetworkOffering.list(self.apiClient, name=args.pop('networkOfferingName'))[0]

        args['zoneid'] = args.pop('zone').id
        args['displaytext'] = '%s For %s' % (networkOfferingName, zone.name)
        args['networkoffering'] = networkOffering.id

        return Network.create(self.apiClient, args)

    def addPod(self, name, zone, netmask=None, gateway=None, managementIpRangeSize=5):
        args = locals()
        ipResources = xenrt.resources.getResourceRange('IP4ADDR', args.pop('managementIpRangeSize'))
        args['zoneid'] = args.pop('zone').id
        args['startip'] = ipResources[0].getAddr()
        args['endip'] = ipResources[-1].getAddr()
        args['netmask'] = netmask or xenrt.TEC().config.lookup(['NETWORK_CONFIG', 'DEFAULT', 'SUBNETMASK'])
        args['gateway'] = gateway or xenrt.TEC().config.lookup(['NETWORK_CONFIG', 'DEFAULT', 'GATEWAY'])
        return Pod.create(self.apiClient, args) 

    def addPublicIpRange(self, pod, networkid=None, forvirtualnetwork='false', netmask=None, gateway=None, publicIpRangeSize=5, vlan='untagged'):
        args = locals()
        ipResources = xenrt.resources.getResourceRange('IP4ADDR', args.pop('publicIpRangeSize'))
        pod = args.pop('pod')
        args['zoneid'] = pod.zoneid
        args['podid'] = None
        args['startip'] = ipResources[0].getAddr()
        args['endip'] = ipResources[-1].getAddr()
        args['netmask'] = netmask or xenrt.TEC().config.lookup(['NETWORK_CONFIG', 'DEFAULT', 'SUBNETMASK'])
        args['gateway'] = gateway or xenrt.TEC().config.lookup(['NETWORK_CONFIG', 'DEFAULT', 'GATEWAY'])

        return PublicIpRange.create(self.apiClient, args)

    def addNetworkIpRange(self, pod, physicalNetwork, netmask=None, gateway=None, ipRangeSize=5, vlan='untagged'):
        ipResources = xenrt.resources.getResourceRange('IP4ADDR', ipRangeSize)
        ipRangeC = createVlanIpRange.createVlanIpRangeCmd()
        ipRangeC.forvirtualnetwork = 'false'
        ipRangeC.vlan = vlan
        ipRangeC.gateway = gateway or xenrt.TEC().config.lookup(['NETWORK_CONFIG', 'DEFAULT', 'GATEWAY'])
        ipRangeC.netmask = netmask or xenrt.TEC().config.lookup(['NETWORK_CONFIG', 'DEFAULT', 'SUBNETMASK'])
        ipRangeC.startip = ipResources[0].getAddr()
        ipRangeC.endip = ipResources[-1].getAddr()
        ipRangeC.physicalnetworkid = physicalNetwork.id
        ipRangeC.podid = pod.id
        ipRangeC.zoneid = pod.zoneid
        return self.apiClient.createVlanIpRange(ipRangeC)

    def addCluster(self, name, pod):
        args = { 'clustername': name, 'zoneid': pod.zoneid, 'podid': pod.id, 'clustertype': 'CloudManaged' }
            
        return Cluster.create(self.apiClient, args)

    def addPrimaryStorage(self, name, cluster, primaryStorageUrl=None, primaryStorageSRName=None):
        args = { 'name': name, 'zoneid': cluster.zoneid, 'podid': cluster.podid, 'clusterid': cluster.id }
        if primaryStorageSRName and self.apiClient.hypervisor == 'XenServer':
            args['url'] = 'presetup://localhost/%s' % (primaryStorageSRName)
        elif primaryStorageUrl:
            args['url'] = primaryStorageUrl
        else:
            primaryNfs = xenrt.ExternalNFSShare()
            args['url'] = 'nfs://%s' % (primaryNfs.getMount().replace(':',''))

        return StoragePool.create(self.apiClient, args)

    def addHost(self, cluster, hostAddr):
        args = { 'url': 'http://%s' % (hostAddr), 'username': 'root', 'password': xenrt.TEC().lookup("ROOT_PASSWORD"), 'zoneid': cluster.zoneid, 'podid': cluster.podid }
        host = Host.create(self.apiClient, cluster, args)

        # Wait for host(s) to start up
        allHostsUp = False
        while(not allHostsUp):
            xenrt.sleep(10)
            hostList = Host.list(self.apiClient, clustername='XenRT-Zone-0-Pod-0-Cluster-0', type='Routing')
            hostListState = map(lambda x:x.state, hostList)
            xenrt.TEC().logverbose('Waiting for host(s) %s, Current State(s): %s' % (map(lambda x:x.name, hostList), hostListState))
            allHostsUp = len(hostList) == hostListState.count('Up')

    def addIsoIfNotPresent(self, distro, isoName, isoRepo):
        listIsosC = listIsos.listIsosCmd()
        listIsosC.isofilter = "all"
        isos = Iso.list(self.apiClient, isofilter="all", name=isoName)
        if not isos:
            xenrt.TEC().logverbose("ISO is not present, registering")
            if isoRepo == "windows":
                url = "%s/%s" % (xenrt.TEC().lookup("EXPORT_ISO_HTTP"), isoName)
            elif isoRepo == "linux":
                url = "%s/%s" % (xenrt.TEC().lookup("EXPORT_ISO_HTTP_STATIC"), isoName)
            else:
                raise xenrt.XRTError("ISO Repository not recognised")

            # TODO: Cope with more zones
            # Should also be able to do "All Zones", but marvin requires a zone to be specified

            zone = Zone.list(self.apiClient)[0].id

            osname = xenrt.TEC().lookup(["CCP_CONFIG", "OS_NAMES", distro])
            Iso.create(self.apiClient, {
                        "zoneid": zone,
                        "ostype": osname,
                        "name": isoName,
                        "displaytext": isoName,
                        "ispublic": True,
                        "url": url})

        # Now wait until the ISO is ready
        deadline = xenrt.timenow() + 3600
        xenrt.TEC().logverbose("Waiting for ISO to be ready")
        while xenrt.timenow() <= deadline:
            try:
                iso = Iso.list(self.apiClient, isofilter="all", name=isoName)[0]
                if iso.isready:
                    break
                else:
                    xenrt.TEC().logverbose("Status: %s" % iso.status)
            except:
                pass
            xenrt.sleep(15)

    def deleteIso(self, isoName):
        iso = Iso.list(self.apiClient, isofilter="all", name=isoName)[0].id
        cmd = deleteIso.deleteIsoCmd()
        cmd.id = iso
        self.apiClient.deleteIso(cmd)

    def deleteTemplate(self, templateName):
        template = [x for x in Template.list(self.apiClient, templatefilter="all") if x.displaytext == templateName][0].id
        cmd = deleteTemplate.deleteTemplateCmd()
        cmd.id = template
        self.apiClient.deleteTemplate(cmd)
