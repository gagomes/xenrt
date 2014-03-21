import xenrt
import logging
import os, urllib
from datetime import datetime
import shutil
import tarfile

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
            self.mgtSvr.place.execcmd('mount %s /media' % (storagePath))
            installSysTmpltLoc = self.mgtSvr.place.execcmd('find / -name *install-sys-tmplt').strip()
            self.mgtSvr.place.execcmd('%s -m /media -u %s -h xenserver -F' % (installSysTmpltLoc, sysTemplateUrl), timeout=60*60)
            self.mgtSvr.place.execcmd('umount /media')
        webdir.remove()

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
            hostList = Host.list(self.apiClient, clustername=cluster.name, type='Routing')
            hostListState = map(lambda x:x.state, hostList)
            xenrt.TEC().logverbose('Cluster: %s - Waiting for host(s) %s, Current State(s): %s' % (cluster.name, map(lambda x:x.name, hostList), hostListState))
            allHostsUp = len(hostList) == hostListState.count('Up')

    def addTemplateIfNotPresent(self, distro, url):
        templates = [x for x in Template.list(self.apiClient, templatefilter="all") if x.displaytext == distro]
        if not templates:
            xenrt.TEC().logverbose("Template is not present, registering")
            # TODO: Cope with more zones
            # Should also be able to do "All Zones", but marvin requires a zone to be specified

            zone = Zone.list(self.apiClient)[0].id

            osname = xenrt.TEC().lookup(["CCP_CONFIG", "OS_NAMES", distro])
            Template.register(self.apiClient, {
                        "zoneid": zone,
                        "ostype": osname,
                        "name": distro,
                        "displaytext": distro,
                        "ispublic": True,
                        "url": url,
                        "format": "VHD"})

        # Now wait until the Template is ready
        deadline = xenrt.timenow() + 3600
        xenrt.TEC().logverbose("Waiting for Template to be ready")
        while xenrt.timenow() <= deadline:
            try:
                template = [x for x in Template.list(self.apiClient, templatefilter="all") if x.displaytext == distro][0]
                if template.isready:
                    break
                else:
                    xenrt.TEC().logverbose("Status: %s" % template.status)
            except:
                pass
            xenrt.sleep(15)

    def addIsoIfNotPresent(self, distro, isoName, isoRepo):
        listIsosC = listIsos.listIsosCmd()
        listIsosC.isofilter = "all"
        isos = Iso.list(self.apiClient, isofilter="all", name=isoName)
        if not isos:
            xenrt.TEC().logverbose("ISO is not present, registering")
            if isoRepo == xenrt.IsoRepository.Windows:
                url = "%s/%s" % (xenrt.TEC().lookup("EXPORT_ISO_HTTP"), isoName)
            elif isoRepo == xenrt.IsoRepository.Linux:
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
  


from lxml import etree
import glob, shutil, os, re, json

class TCMarvinTestRunner(xenrt.TestCase):

    def generateMarvinTestConfig(self):
        self.marvinCfg = {}
        self.marvinCfg['dbSvr'] = {}
        self.marvinCfg['dbSvr']['dbSvr'] = self.marvinApi.mgtSvrDetails.mgtSvrIp
        self.marvinCfg['dbSvr']['passwd'] = 'cloud'
        self.marvinCfg['dbSvr']['db'] = 'cloud'
        self.marvinCfg['dbSvr']['port'] = 3306
        self.marvinCfg['dbSvr']['user'] = 'cloud'

        self.marvinCfg['mgtSvr'] = []
        self.marvinCfg['mgtSvr'].append({'mgtSvrIp': self.marvinApi.mgtSvrDetails.mgtSvrIp,
                                         'port'    : self.marvinApi.mgtSvrDetails.port})

        self.marvinCfg['zones'] = map(lambda x:x.__dict__, xenrt.lib.cloud.Zone.list(self.marvinApi.apiClient))
        for zone in self.marvinCfg['zones']:
            zone['pods'] = map(lambda x:x.__dict__, xenrt.lib.cloud.Pod.list(self.marvinApi.apiClient, zoneid=zone['id']))
            for pod in zone['pods']:
                pod['clusters'] = map(lambda x:x.__dict__, xenrt.lib.cloud.Cluster.list(self.marvinApi.apiClient, podid=pod['id']))
                for cluster in pod['clusters']:
                    cluster['hosts'] = map(lambda x:x.__dict__, xenrt.lib.cloud.Host.list(self.marvinApi.apiClient, clusterid=cluster['id']))
                    for host in cluster['hosts']:
                        host['username'] = 'root'
                        host['password'] = xenrt.TEC().lookup("ROOT_PASSWORD")
                        host['url'] = host['ipaddress']

        fn = xenrt.TEC().tempFile()
        fh = open(fn, 'w')
        json.dump(self.marvinCfg, fh)
        fh.close()
        return fn

    def getTestsToExecute(self, nosetestSelectorStr, tagStr=None):
        noseTestList = xenrt.TEC().tempFile()
        tempLogDir = xenrt.TEC().tempDir()
        noseArgs = ['--with-marvin', '--marvin-config=%s' % (self.marvinConfigFile),
                    '--with-xunit', '--xunit-file=%s' % (noseTestList),
                    '--log-folder-path=%s' % (tempLogDir),
                    '--load',
                    nosetestSelectorStr,
                    '--collect-only']

        if tagStr:
            noseArgs.append(tagStr)

        xenrt.TEC().logverbose('Using nosetest args: %s' % (' '.join(noseArgs)))

        try:
            result = xenrt.util.command('/usr/local/bin/nosetests %s' % (' '.join(noseArgs)))
            xenrt.TEC().logverbose('Completed with result: %s' % (result))
        except Exception, e:
            xenrt.TEC().logverbose('Failed to get test information from nose - Exception raised: %s' % (str(e)))
            raise

        testData = open(noseTestList).read()
        treeData = etree.fromstring(testData)
        elements = treeData.getchildren()

        self.testsToExecute = map(lambda x:{ 'name': x.get('name'), 'classname': x.get('classname') }, elements)
        xenrt.TEC().logverbose('Found %d test-cases reported by nose' % (len(self.testsToExecute))) 

        map(lambda x:xenrt.TEC().logverbose('  Testcase: %s, Class path: %s' % (x['name'], x['classname'])), self.testsToExecute)
        failures = filter(lambda x:x['classname'] == 'nose.failure.Failure', self.testsToExecute)

        if len(self.testsToExecute) == 0:
            raise xenrt.XRTError('No nose tests found for %s with tags: %s' % (self.nosetestSelectorStr, self.noseTagStr))

        if len(failures) > 0:
            raise xenrt.XRTError('Nosetest lookup failed')

        testNames = map(lambda x:x['name'], self.testsToExecute)
        if len(testNames) != len(set(testNames)):
            raise xenrt.XRTError('Duplicate Marvin test names found')

    def getMarvinTestCode(self):
        localTestCodeDir = xenrt.TEC().tempDir()
        sourceLocation = xenrt.TEC().lookup('MARVIN_TEST_CODE_PATH', None)
        if not sourceLocation:
            # TODO - add logic to get correct code for SUT
            return '/local/scratch/cloud'

        if not sourceLocation:
            raise xenrt.XRTError('Failed to find source location for Marvin testcode')

        xenrt.TEC().logverbose('Using Marvin testcode from source location: %s' % (sourceLocation))
        sourceFile = xenrt.TEC().getFile(sourceLocation)
        if not sourceFile:
            raise xenrt.XRTError('Failed to getFile from %s' % (sourceLocation))
        
        if os.path.splitext(sourceFile)[1] == '.py':
            xenrt.TEC().logverbose('Moving single python file [%s] to test directory [%s]' % (sourceFile, localTestCodeDir)) 
            shutil.copy(sourceFile, localTestCodeDir)
            os.chmod(os.path.join(localTestCodeDir, os.path.basename(sourceFile)), 0o664)
        elif tarfile.is_tarfile(sourceFile):
            tf = tarfile.open(sourceFile)
            for tarInfo in tf:
                if os.path.splitext(tarInfo.name)[1] == '.py':
                    xenrt.TEC().logverbose('Extracting %s to test directory [%s]' % (tarInfo.name, localTestCodeDir))
                    tf.extract(tarInfo.name, path=localTestCodeDir)
        else:
            raise xenrt.XRTError('Invalid file type: %s (should be .py or tarball)' % (sourceFile))
            
        return localTestCodeDir

    def prepare(self, arglist):
        self.marvinTestCodePath = self.getMarvinTestCode()
        self.nosetestSelectorStr = self.marvinTestCodePath
        self.noseTagStr = None

        if self.marvinTestConfig != None:
            xenrt.TEC().logverbose('Using marvin test config: %s' % (self.marvinTestConfig))
            if self.marvinTestConfig.has_key('path') and self.marvinTestConfig['path'] != None:
                self.nosetestSelectorStr = os.path.join(self.marvinTestCodePath, self.marvinTestConfig['path'])

            if self.marvinTestConfig.has_key('cls') and self.marvinTestConfig['cls'] != None:
                self.nosetestSelectorStr += ':' + self.marvinTestConfig['cls']

            if self.marvinTestConfig.has_key('tags') and self.marvinTestConfig['tags'] != None and len(self.marvinTestConfig['tags']) > 0:
                self.noseTagStr = '-a "%s"' % (','.join(map(lambda x:'tags=%s' % (x), self.marvinTestConfig['tags'])))
                xenrt.TEC().logverbose('Using nose tag str: %s' % (self.noseTagStr))

        xenrt.TEC().logverbose('Using nose selector str: %s' % (self.nosetestSelectorStr))

        cloud = self.getDefaultToolstack()
        self.manSvr = cloud.mgtsvr
        self.marvinApi = cloud.marvin
        self.marvinConfigFile = self.generateMarvinTestConfig()

        self.getTestsToExecute(self.nosetestSelectorStr, self.noseTagStr)

        # Apply test configration
        self.marvinApi.setCloudGlobalConfig("network.gc.wait", "60")
        self.marvinApi.setCloudGlobalConfig("storage.cleanup.interval", "300")
        self.marvinApi.setCloudGlobalConfig("vm.op.wait.interval", "5")
        self.marvinApi.setCloudGlobalConfig("default.page.size", "10000")
        self.marvinApi.setCloudGlobalConfig("network.gc.interval", "60")
        self.marvinApi.setCloudGlobalConfig("workers", "10")
        self.marvinApi.setCloudGlobalConfig("account.cleanup.interval", "600")
        self.marvinApi.setCloudGlobalConfig("expunge.delay", "60")
        self.marvinApi.setCloudGlobalConfig("vm.allocation.algorithm", "random")
        self.marvinApi.setCloudGlobalConfig("expunge.interval", "60")
        self.marvinApi.setCloudGlobalConfig("expunge.workers", "3")
        self.marvinApi.setCloudGlobalConfig("check.pod.cidrs", "true")
        self.marvinApi.setCloudGlobalConfig("direct.agent.load.size", "1000", restartManagementServer=True)

        # Add check to make this optional
        self.marvinApi.waitForTemplateReady('CentOS 5.6(64-bit) no GUI (XenServer)')

    def writeRunInfoLog(self, testcaseName, runInfoFile):
        xenrt.TEC().logverbose('-------------------------- START MARVIN LOGS FOR %s --------------------------' % (testcaseName))
        searchStr = '- DEBUG - %s' % (testcaseName)
        for line in open(runInfoFile):
            if re.search(searchStr, line):
                xenrt.TEC().log(line)
        xenrt.TEC().logverbose('-------------------------- END MARVIN LOGS FOR %s --------------------------' % (testcaseName))

    def handleMarvinTestCaseFailure(self, testData, reasonData):
        reason = reasonData.get('type')
        message = reasonData.get('message')
        if reason == 'unittest.case.SkipTest':
            # TODO - should this fail the test?
            xenrt.TEC().warning('Marvin testcase %s was skipped for reason: %s' % (testData['name'], message))
        else:
            # TODO - do more checking of failure reason
            xenrt.TEC().logverbose('Marvin testcase %s failed/errored with reason: %s, message: %s' % (testData['name'], reason, message))
            raise xenrt.XRTFailure('Marvin testcase %s failed/errored with reason: %s, message: %s' % (testData['name'], reason, message))


    def marvinTestCase(self, testData, runInfoFile, resultData):
        self.writeRunInfoLog(testData['name'], runInfoFile)

        xenrt.TEC().logverbose('Test duration: %s (sec)' % (resultData.get('time')))
        childElements = resultData.getchildren()
        if len(childElements) > 0:
            for childElement in childElements:
                self.handleMarvinTestCaseFailure(testData, childElement)

    def run(self, arglist):
        tempLogDir = xenrt.TEC().tempDir()
        noseTestResults = xenrt.TEC().tempFile()
        noseArgs = ['-v',
                    '--logging-level=DEBUG',
                    '--log-folder-path=%s' % (tempLogDir),
                    '--with-marvin', '--marvin-config=%s' % (self.marvinConfigFile),
                    '--with-xunit', '--xunit-file=%s' % (noseTestResults),
                    '--load']

        if self.noseTagStr:
            noseArgs.append(self.noseTagStr)
        noseArgs.append(self.nosetestSelectorStr)

        xenrt.TEC().logverbose('Using nosetest args: %s' % (' '.join(noseArgs)))

        try:
            result = xenrt.util.command('/usr/local/bin/nosetests %s' % (' '.join(noseArgs)))
            xenrt.TEC().logverbose('Test(s) completed with result: %s' % (result))
        except Exception, e:
            xenrt.TEC().logverbose('Exception raised: %s' % (str(e)))

        testData = open(noseTestResults).read()
        xmlResultData = etree.fromstring(testData)

        if len(self.testsToExecute) != int(xmlResultData.get('tests')):
            xenrt.TEC().warning('Expected %d Marvin tests to be executed, Actual: %d' % (len(self.testsToExecute), int(xmlResultData.get('tests'))))

        xenrt.TEC().comment('Marvin tests executed: %s' % (xmlResultData.get('tests')))
        xenrt.TEC().comment('Marvin tests failed:   %s' % (xmlResultData.get('failures')))
        xenrt.TEC().comment('Marvin test errors:    %s' % (xmlResultData.get('errors')))
        xenrt.TEC().comment('Marvin tests skipped:  %s' % (xmlResultData.get('skipped')))

        logPathList = glob.glob(os.path.join(tempLogDir, '*', 'runinfo.txt'))
        if len(logPathList) != 1:
            xenrt.TEC().logverbose('%d Marvin log directories found' % (len(logPathList)))
            raise xenrt.XRTError('Unique Marvin log directory not found')

        runInfoFile = logPathList[0]
        logPath = os.path.dirname(runInfoFile)
        self.logsubdir = os.path.join(xenrt.TEC().getLogdir(), 'cloud', 'marvintest')
        xenrt.TEC().logverbose('Add full test logs to path %s' % (self.logsubdir))
        shutil.copytree(logPath, self.logsubdir)

        for test in self.testsToExecute:
            resultDataList = filter(lambda x:x.get('name') == test['name'], xmlResultData.getchildren())
            if len(resultDataList) != 1:
                xenrt.TEC().logverbose('%d Marvin test results found for test %s' % (len(resultDataList), test['name']))
                raise xenrt.XRTError('Unique Marvin test result not found')

            self.runSubcase('marvinTestCase', (test, runInfoFile, resultDataList[0]), test['classname'], test['name'])

        self.manSvr.getLogs(self.logsubdir)

