
import xenrt
import logging
import os, urllib
try:
    from marvin import cloudstackTestClient
    from marvin.integration.lib.base import *
    from marvin import configGenerator
except ImportError:
    pass

class XenRTLogStream(object):
    def write(self, data):
        xenrt.TEC().logverbose(data)

    def flush(self):
        xenrt.TEC().logverbose('FLUSH CALLED')

class MarvinApi(object):
    MARVIN_LOGGER = 'MarvinLogger'
    
    MS_USERNAME = 'admin'
    MS_PASSWORD = 'password'

    def __init__(self, mgtSvrVM):
        self.mgtSvrVM = mgtSvrVM
        self.xenrtStream = XenRTLogStream()
        logFormat = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
        self.logger = logging.getLogger(self.MARVIN_LOGGER)
        stream = logging.StreamHandler(stream=self.xenrtStream)
        stream.setLevel(logging.INFO)
        self.logger.addHandler(stream)

        mgtSvrDetails = configGenerator.managementServer()
        mgtSvrDetails.mgtSvrIp = mgtSvrVM.getIP()
        mgtSvrDetails.user = self.MS_USERNAME
        mgtSvrDetails.passwd = self.MS_PASSWORD
        
        self.testClient = cloudstackTestClient.cloudstackTestClient(mgmtDetails=mgtSvrDetails, dbSvrDetails=None, logger=self.logger)
        self.apiClient = self.testClient.getApiClient()

        #TODO - Fix this
        self.apiClient.hypervisor = 'XenServer'

    def copySystemTemplateToSecondaryStorage(self, storagePath, provider):
#        sysTemplateLocation = xenrt.TEC().lookup("CLOUD_SYS_TEMPLATE", 'http://download.cloud.com/templates/4.2/systemvmtemplate-2013-07-12-master-xen.vhd.bz2')
        sysTemplateiSrcLocation = xenrt.TEC().lookup("CLOUD_SYS_TEMPLATE", '/usr/groups/xenrt/cloud/systemvmtemplate-2013-07-12-master-xen.vhd.bz2')
        if not sysTemplateiSrcLocation:
            raise xenrt.XRTError('Location of system template not specified')
        sysTemplateFile = xenrt.TEC().getFile(sysTemplateiSrcLocation)
        webdir = xenrt.WebDirectory()
        webdir.copyIn(sysTemplateFile)
        sysTemplateUrl = webdir.getURL(os.path.basename(sysTemplateFile))

        if provider == 'NFS':
            self.mgtSvrVM.execguest('mount %s /media' % (storagePath))
            installSysTmpltLoc = self.mgtSvrVM.execguest('find / -name *install-sys-tmplt').strip()
            self.mgtSvrVM.execguest('%s -m /media -u %s -h xenserver -F' % (installSysTmpltLoc, sysTemplateUrl), timeout=60*60)
            self.mgtSvrVM.execguest('umount /media')

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
        # Wait for host to start up
        while(host.state != 'Up'):
            xenrt.TEC().logverbose('Waiting for host [%s], Current State: %s' % (host.name, host.state))
            xenrt.sleep(10)
            host = Host(host.update(self.apiClient, id=host.id).__dict__)        

   
def deploy(cloudSpec, manSvrVM=None):
    xenrt.TEC().logverbose('Cloud Spec: %s' % (cloudSpec))

    # TODO Get the IP address of the shared
    if not manSvrVM:
        manSvrVM = xenrt.TEC().registry.guestGet('CS-MS')
    if not manSvrVM:
        raise xenrt.XRTError('No management server specified')

    xenrt.TEC().comment('Using Management Server: %s' % (manSvrVM.getIP()))
    marvinApi = MarvinApi(manSvrVM)

    zoneNameIx = 0
    for zoneSpec in cloudSpec['zones']:
        if not zoneSpec.has_key('name'):
            zoneSpec['name'] = 'XenRT-Zone-%d' % (zoneNameIx)
            zoneNameIx += 1

        podSpecs = zoneSpec.pop('pods')
        zone = marvinApi.addZone(**zoneSpec)
        # TODO:  Add more options for Sec Store
        secondaryStroage = marvinApi.addSecondaryStorage(zone)

        if zone.networktype == 'Basic':
            phyNetwork = marvinApi.addPhysicalNetwork(name='BasicPhyNetwork', zone=zone, trafficTypeList=['Management', 'Guest'], 
                                                                                         networkServiceProviderList=['VirtualRouter', 'SecurityGroupProvider'])
            sharedNetwork = marvinApi.addNetwork(name='BasicSharedNetwork', zone=zone)
        else:
            # TODO: Implement advanced zone
            pass


        podNameIx = 0
        for podSpec in podSpecs:
            if not podSpec.has_key('name'):
                podSpec['name'] = '%s-Pod-%d' % (zone.name, podNameIx)
                podNameIx += 1

            clusterSpecs = podSpec.pop('clusters')
            podSpec['zone'] = zone
            pod = marvinApi.addPod(**podSpec)
            ipRange = marvinApi.addNetworkIpRange(pod, phyNetwork)

            clusterNameIx = 0
            for clusterSpec in clusterSpecs:
                if not clusterSpec.has_key('name'):
                    clusterSpec['name'] = '%s-Cluster-%d' % (pod.name, clusterNameIx)
                    clusterNameIx += 1
                
                cluster = marvinApi.addCluster(clusterSpec['name'], pod)

                hostObject = xenrt.TEC().registry.hostGet('RESOURCE_HOST_%d' % (clusterSpec['masterHostId']))
                host = marvinApi.addHost(cluster, hostObject.getIP())

                # TODO - Add support for using other storage
                priStoreName = '%s-PriStore' % (cluster.name)
                priStore = marvinApi.addPrimaryStorage(priStoreName, cluster)

        zone.update(marvinApi.apiClient, allocationstate='Enabled')


def checkManagementServerHealth(place, cmdPrefix):
    managementServerOk = False
    maxRetries = 2
    maxReboots = 2
    reboots = 0
    while(reboots < maxReboots and not managementServerOk):
        retries = 0
        while(retries < maxRetries):
            retries += 1
            xenrt.TEC().logverbose('Check Management Server Ports: Attempt: %d of %d' % (retries, maxRetries))

            # Check the management server ports are reachable
            port = 8080
            try:
                urllib.urlopen('http://%s:%s' % (place.getIP(), port))
            except IOError, ioErr:
                xenrt.TEC().logverbose('Attempt to reach Management Server [%s] on Port: %d failed with error: %s' % (place.getIP(), port, ioErr.strerror))
                xenrt.sleep(60)
                continue

            port = 8096
            try:
                urllib.urlopen('http://%s:%s' % (place.getIP(), port))
                managementServerOk = True
                break
            except IOError, ioErr:
                xenrt.TEC().logverbose('Attempt to reach Management Server [%s] on Port: %d failed with error: %s' % (place.getIP(), port, ioErr.strerror))
                xenrt.sleep(60)

        if not managementServerOk:
            reboots += 1
            xenrt.TEC().logverbose('Restarting Management Server: Attempt: %d of %d' % (reboots, maxReboots))
            place.execguest('mysql -u cloud --password=cloud --execute="UPDATE cloud.configuration SET value=8096 WHERE name=\'integration.api.port\'"')
            place.execguest('service %s-management restart' % (cmdPrefix))
            xenrt.sleep(60)

#        place.execguest('service %s-management stop' % (cmdPrefix))
        # Wait for service to stop (Campo bug - service stop completes before service actually stops)
#        xenrt.sleep(120)

#        place.execguest('service %s-management start' % (cmdPrefix))
        # Wait for service to start
#        xenrt.sleep(180)

        # Open the management server port that Marvin will use


def installCloudPlatformManagementServer(place):
    if place.arch != 'x86-64':
        raise xenrt.XRTError('Cloud Management Server requires a 64-bit guest')

    manSvrInputDir = xenrt.TEC().lookup("CLOUDINPUTDIR", None)
    if not manSvrInputDir:
        raise xenrt.XRTError('Location of management server build not specified')

    if place.distro in ['rhel63', 'rhel64', ]:
        place.execguest('wget %s -O cp.tar.gz' % (manSvrInputDir))
        place.execguest('mkdir cloudplatform')
        place.execguest('tar -zxvf cp.tar.gz -C /root/cloudplatform')
        installDir = os.path.dirname(place.execguest('find cloudplatform/ -type f -name install.sh'))
        place.execguest('cd %s && ./install.sh -m' % (installDir))

        place.execguest('setenforce Permissive')
        place.execguest('service nfs start')

        place.execguest('yum -y install mysql-server mysql')
        place.execguest('service mysqld restart')

        place.execguest('mysql -u root --execute="GRANT ALL PRIVILEGES ON *.* TO \'root\'@\'%\' WITH GRANT OPTION"')
        place.execguest('iptables -I INPUT -p tcp --dport 3306 -j ACCEPT')
        place.execguest('mysqladmin -u root password xensource')
        place.execguest('service mysqld restart')

        for cmdPrefix in ['cloud', 'cloudstack']:
            setupDbLoc = place.execguest('find /usr/bin -name %s-setup-databases' % (cmdPrefix)).strip()
            if setupDbLoc != '':
                place.execguest('%s cloud:cloud@localhost --deploy-as=root:xensource' % (setupDbLoc))

                place.execguest('iptables -I INPUT -p tcp --dport 8096 -j ACCEPT')

                setupMsLoc = place.execguest('find /usr/bin -name %s-setup-management' % (cmdPrefix)).strip()
                place.execguest(setupMsLoc)    
                break

        place.execguest('mysql -u cloud --password=cloud --execute="UPDATE cloud.configuration SET value=8096 WHERE name=\'integration.api.port\'"')
        place.execguest('service %s-management restart' % (cmdPrefix))
        xenrt.sleep(60)

        checkManagementServerHealth(place, cmdPrefix)
