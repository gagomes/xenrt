
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

class CloudStack(object):
    def __init__(self, place):
        self.mgtsvr = ManagementServer(place)
        self.marvin = MarvinApi(self.mgtsvr)

    def createInstance(self,
                       distro,
                       name=None,
                       vcpus=None,
                       memory=None,
                       vifs=None,
                       rootdisk=None,
                       extraConfig={},
                       startOn=None):

        if not name:
            name = xenrt.util.randomGuestName()
        instance = xenrt.lib.Instance(self, name, distro, vcpus, memory, extraConfig=extraConfig, vifs=vifs, rootdisk=rootdisk)

        if not "iso" in instance.os.supportedInstallMethods:
            raise xenrt.XRTError("ISO Install not supported")

        self.marvin.addIsoIfNotPresent(distro, instance.os.isoName, instance.os.isoRepo)

        deployVirtualMachineC = deployVirtualMachine.deployVirtualMachineCmd()
        deployVirtualMachineC.displayname = name
        deployVirtualMachineC.templateid = [x.id for x in self.marvin.apiClient.listIsos(listIsos.listIsosCmd()) if x.name == instance.os.isoName][0]
        # TODO support different service offerings
        deployVirtualMachineC.serviceofferingid = [x.id for x in self.marvin.apiClient.listServiceOfferings(listServiceOfferings.listServiceOfferingsCmd()) if x.name == "Medium Instance"][0]
        # TODO support different disk offerings
        deployVirtualMachineC.diskofferingid = [x.id for x in self.marvin.apiClient.listDiskOfferings(listDiskOfferings.listDiskOfferingsCmd()) if x.disksize == 20]
        # TODO Support different hypervisors
        deployVirtualMachineC.hypervisor = "XenServer"
        deployVirtualMachineC.zoneid = self.marvin.apiClient.listZones(listZones.listZonesCmd())[0].id

        xenrt.TEC().logverbose("Deploying VM")

        rsp = self.marvin.apiClient.deployVirtualMachine(deployVirtualMachineC)

        instance.toolstackId = rsp.id

        createTagsC = createTags.createTagsCmd()
        createTagsC.resourceids.append(instance.toolstackId)
        createTagsC.resourcetype = "userVm"
        createTagsC.tags.append({"key":"distro", "value": distro})
        self.marvin.apiClient.createTags(createTagsC)

        xenrt.TEC().logverbose("Waiting for install complete")
        instance.os.waitForInstallCompleteAndFirstBoot()
        return instance


    def existingInstance(self, name):

        vm = [x for x in self.marvin.apiClient.listVirtualMachines(listVirtualMachines.listVirtualMachinesCmd()) if x.displayname==name][0]
        listTagsC = listTags.listTagsCmd()
        listTagsC.resourceid = vm.id
        tags = self.marvin.apiClient.listTags(listTagsC)
        distro = [x.value for x in tags if x.key=="distro"][0]

        # TODO: Sort out the other arguments here
        instance = xenrt.lib.Instance(self, name, distro, 0, 0, {}, [], 0)
        instance.toolstackId = vm.id
        return instance

    def installPVTools(self, instance):
        listIsosC = listIsos.listIsosCmd()
        listIsosC.name="xs-tools.iso"
        isoId = self.marvin.apiClient.listIsos(listIsosC)[0].id

        attachIsoC = attachIso.attachIsoCmd()
        attachIsoC.id = isoId
        attachIsoC.virtualmachineid = instance.toolstackId
        self.marvin.apiClient.attachIso(attachIsoC)

        # Allow the CD to appear
        xenrt.sleep(30)

        deadline = xenrt.util.timenow() + 300 
        while True:
            try:
                if instance.os.fileExists("D:\\installwizard.msi"):
                    break
            except:
                pass
            if xenrt.util.timenow() > deadline:
                raise xenrt.XRTError("Installer did not appear")
            
            xenrt.sleep(5)

        instance.os.startCmd("D:\\installwizard.msi /passive /liwearcmuopvx c:\\tools_msi_install.log")
        
        deadline = xenrt.util.timenow() + 3600
        while True:
            regValue = ""
            try:
                regValue = instance.os.winRegLookup('HKLM', "SOFTWARE\\Wow6432Node\\Citrix\\XenToolsInstaller", "InstallStatus", healthCheckOnFailure=False)
            except:
                try:
                    regValue = instance.os.winRegLookup('HKLM', "SOFTWARE\\Citrix\\XenToolsInstaller", "InstallStatus", healthCheckOnFailure=False)
                except:
                    pass
                
            if xenrt.util.timenow() > deadline:
                #instanse.os.checkHealth(desc="Waiting for installer registry key to be written")
                
                if regValue and len(regValue) > 0:
                    raise xenrt.XRTFailure("Timed out waiting for installer registry key to be written. Value=%s" % regValue)
                else:
                    raise xenrt.XRTFailure("Timed out waiting for installer registry key to be written.")
            
            elif "Installed" == regValue:
                break
            else:
                xenrt.sleep(30)

    def getIP(self, instance, timeout, level):
        cmd = listNics.listNicsCmd()
        cmd.virtualmachineid=instance.toolstackId
        instance.mainip = [x.ipaddress for x in self.marvin.apiClient.listNics(cmd) if x.isdefault][0]
        return instance.mainip

    def startInstance(self, instance, on):
        cmd = startVirtualMachine.startVirtualMachineCmd()
        cmd.id = instance.toolstackId
        self.marvin.apiClient.startVirtualMachine(cmd)

    def stopInstance(self, instance, force=False):
        cmd = stopVirtualMachine.stopVirtualMachineCmd()
        cmd.id = instance.toolstackId
        if force:
            cmd.forced = force
        self.marvin.apiClient.stopVirtualMachine(cmd)

    def rebootInstance(self, instance, force=False):
        cmd = rebootVirtualMachine.rebootVirtualMachineCmd()
        cmd.id = instance.toolstackId
        if force:
            cmd.forced = force
        self.marvin.apiClient.rebootVirtualMachine(cmd)

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
        isos = [x.name for x in self.apiClient.listIsos(listIsosC)]
        if isoName not in isos:
            xenrt.TEC().logverbose("ISO is not present, registering")
            if isoRepo == "windows":
                url = "%s/%s" % (xenrt.TEC().lookup("EXPORT_ISO_HTTP"), isoName)
            elif isoRepo == "linux":
                url = "%s/%s" % (xenrt.TEC().lookup("EXPORT_ISO_HTTP_STATIC"), isoName)
            else:
                raise xenrt.XRTError("ISO Repository not recognised")

            # TODO: Cope with more zones
            # Should also be able to do "All Zones", but marvin requires a zone to be specified

            zoneid = self.apiClient.listZones(listZones.listZonesCmd())[0].id

            registerIsoC = registerIso.registerIsoCmd()
            registerIsoC.url = url
            registerIsoC.name = isoName
            registerIsoC.displaytext = isoName
            registerIsoC.ispublic = True
            registerIsoC.zoneid = zoneid
            osname = xenrt.TEC().lookup(["CCP_CONFIG", "OS_NAMES", distro])
            osid = [x.id for x in self.apiClient.listOsTypes(listOsTypes.listOsTypesCmd()) if x.description == osname][0]
            registerIsoC.ostypeid = osid
            self.apiClient.registerIso(registerIsoC)

        # Now wait until the ISO is ready
        deadline = xenrt.timenow() + 3600
        xenrt.TEC().logverbose("Waiting for ISO to be ready")
        while xenrt.timenow() <= deadline:
            try:
                iso = [x for x in self.apiClient.listIsos(listIsosC) if x.name == isoName][0]
                if iso.isready:
                    break
                else:
                    xenrt.TEC().logverbose("Status: %s" % iso.status)
            except:
                pass
            xenrt.sleep(15)
   
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

    marvinApi.setCloudGlobalConfig("secstorage.allowed.internal.sites", "10.0.0.0/8,192.168.0.0/16,172.16.0.0/12")
    marvinApi.setCloudGlobalConfig("check.pod.cidrs", "false", restartManagementServer=True)

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

