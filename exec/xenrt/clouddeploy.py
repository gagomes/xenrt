
import xenrt
import logging
import os, urllib
from datetime import datetime

try:
    from marvin import cloudstackTestClient
    from marvin.integration.lib.base import *
    from marvin import configGenerator
except ImportError:
    pass

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

   
def deploy(cloudSpec, manSvr=None):
    xenrt.TEC().logverbose('Cloud Spec: %s' % (cloudSpec))

    # TODO - Get the ManSvr object from the registry
    if not manSvr:
        manSvrVM = xenrt.TEC().registry.guestGet('CS-MS')
        if not manSvrVM:
            raise xenrt.XRTError('No management server specified')
        manSvr = ManagementServer(manSvrVM)

    xenrt.TEC().comment('Using Management Server: %s' % (manSvr.place.getIP()))
    marvinApi = MarvinApi(manSvr)

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
 
            #TODO - this is nor correct for advanced zone
            ipRange = marvinApi.addNetworkIpRange(pod, phyNetwork, ipRangeSize=20)

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

class ManagementServer(object):
    def __init__(self, place):
        self.place = place
        self.cmdPrefix = 'cloudstack'

    def getLogs(self, destDir):
        sftp = self.place.sftpClient()
        manSvrLogsLoc = self.place.execguest('find /var/log -type f -name management-server.log').strip()
        sftp.copyTreeFrom(os.path.dirname(manSvrLogsLoc), destDir)
        sftp.close()
 
    def checkManagementServerHealth(self):
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
                    urllib.urlopen('http://%s:%s' % (self.place.getIP(), port))
                except IOError, ioErr:
                    xenrt.TEC().logverbose('Attempt to reach Management Server [%s] on Port: %d failed with error: %s' % (self.place.getIP(), port, ioErr.strerror))
                    xenrt.sleep(60)
                    continue

                port = 8096
                try:
                    urllib.urlopen('http://%s:%s' % (self.place.getIP(), port))
                    managementServerOk = True
                    break
                except IOError, ioErr:
                    xenrt.TEC().logverbose('Attempt to reach Management Server [%s] on Port: %d failed with error: %s' % (self.place.getIP(), port, ioErr.strerror))
                    xenrt.sleep(60)

            if not managementServerOk:
                reboots += 1
                xenrt.TEC().logverbose('Restarting Management Server: Attempt: %d of %d' % (reboots, maxReboots))
                self.place.execguest('mysql -u cloud --password=cloud --execute="UPDATE cloud.configuration SET value=8096 WHERE name=\'integration.api.port\'"')
                self.restart(checkHealth=False)

    def restart(self, checkHealth=True, startStop=False):
        if not startStop:
            self.place.execguest('service %s-management restart' % (self.cmdPrefix))
        else:
            self.place.execguest('service %s-management stop' % (self.cmdPrefix))
            xenrt.sleep(120)
            self.place.execguest('service %s-management start' % (self.cmdPrefix))
        
        if checkHealth:
            self.checkManagementServerHealth()

    def installCloudPlatformManagementServer(self):
        if self.place.arch != 'x86-64':
            raise xenrt.XRTError('Cloud Management Server requires a 64-bit guest')

        manSvrInputDir = xenrt.TEC().lookup("CLOUDINPUTDIR", None)
        if not manSvrInputDir:
            raise xenrt.XRTError('Location of management server build not specified')

        if self.place.distro in ['rhel63', 'rhel64', ]:
            self.place.execguest('wget %s -O cp.tar.gz' % (manSvrInputDir))
            self.place.execguest('mkdir cloudplatform')
            self.place.execguest('tar -zxvf cp.tar.gz -C /root/cloudplatform')
            installDir = os.path.dirname(self.place.execguest('find cloudplatform/ -type f -name install.sh'))
            self.place.execguest('cd %s && ./install.sh -m' % (installDir))

            self.place.execguest('setenforce Permissive')
            self.place.execguest('service nfs start')

            self.place.execguest('yum -y install mysql-server mysql')
            self.place.execguest('service mysqld restart')

            self.place.execguest('mysql -u root --execute="GRANT ALL PRIVILEGES ON *.* TO \'root\'@\'%\' WITH GRANT OPTION"')
            self.place.execguest('iptables -I INPUT -p tcp --dport 3306 -j ACCEPT')
            self.place.execguest('mysqladmin -u root password xensource')
            self.place.execguest('service mysqld restart')

            setupDbLoc = self.place.execguest('find /usr/bin -name %s-setup-databases' % (self.cmdPrefix)).strip()
            self.place.execguest('%s cloud:cloud@localhost --deploy-as=root:xensource' % (setupDbLoc))

            self.place.execguest('iptables -I INPUT -p tcp --dport 8096 -j ACCEPT')

            setupMsLoc = self.place.execguest('find /usr/bin -name %s-setup-management' % (self.cmdPrefix)).strip()
            self.place.execguest(setupMsLoc)    

            self.place.execguest('mysql -u cloud --password=cloud --execute="UPDATE cloud.configuration SET value=8096 WHERE name=\'integration.api.port\'"')
        
        self.restart()

