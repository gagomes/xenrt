import xenrt, xenrt.lib.xenserver
import time
import datetime
import os
import json
import IPy
from lxml import etree
import re
from datetime import datetime
from abc import ABCMeta, abstractmethod, abstractproperty
from xenrt.lazylog import log, step

use_jenkins_api = True
try:
    import jenkinsapi
    from jenkinsapi.jenkins import Jenkins
except ImportError:
    use_jenkins_api = False


class CSStorage(object):
    MS_NFS = 'MS-NFS'
    EXT_NFS = 'EXT-NFS'

    def _createMsNfsExport(self, manSvrVM, name):
        path = '/export/%s' % (name)

        # Check if NFS server is already installed and running
        if not manSvrVM.execguest('service nfs-kernel-server status').strip().endswith('running'):
            manSvrVM.execguest('apt-get install nfs-kernel-server')
            manSvrVM.execguest('mkdir -p /export')
            manSvrVM.execguest('echo "/export  *(rw,async,no_root_squash)" >> /etc/exports')
            manSvrVM.execguest('exportfs -a')
            manSvrVM.execguest('service nfs-kernel-server start')

        # If the directory exists - destroy it
        if manSvrVM.execguest('test -e %s' % (path), retval="code") == 0:
            manSvrVM.execguest('rm -rf %s' % (path))

        manSvrVM.execguest('mkdir -p %s' % (path))
        return '%s:%s' % (manSvrVM.getIP(), path)

    def __init__(self, storageType=EXT_NFS, manSvrVM=None, name=None):
        self.storageType = storageType

        if self.storageType == self.EXT_NFS:
            self.refObj = xenrt.ExternalNFSShare()
            self.serverAndPath = self.refObj.getMount()
        elif self.storageType == self.MS_NFS:
            self.refObj = manSvrVM
            self.serverAndPath = self._createMsNfsExport(manSvrVM, name)            

    def release(self):
        if self.storageType == self.EXT_NFS:
            self.refObj.release()
        elif self.storageType == self.MS_NFS:
            pass


class MarvinConfig(object):

    def __init__(self, manSvrVMAddr):
        self.marvinCfg = {}
        self.marvinCfg['dbSvr'] = {}
        self.marvinCfg['dbSvr']['dbSvr'] = manSvrVMAddr
        self.marvinCfg['dbSvr']['passwd'] = 'cloud'
        self.marvinCfg['dbSvr']['db'] = 'cloud'
        self.marvinCfg['dbSvr']['port'] = 3306
        self.marvinCfg['dbSvr']['user'] = 'cloud'

        self.marvinCfg['logger'] = []
        self.marvinCfg['logger'].append({'name': 'TestClient', 'file': '/tmp/testclient.log'})
        self.marvinCfg['logger'].append({'name': 'TestCase', 'file': '/tmp/testcase.log'})

        self.marvinCfg['globalConfig'] = [
            { "name": "network.gc.wait", "value": "60" },
            { "name": "storage.cleanup.interval", "value": "300" },
            { "name": "vm.op.wait.interval", "value": "5" },
            { "name": "default.page.size", "value": "10000" },
            { "name": "network.gc.interval", "value": "60" },
#            { "name": "instance.name", "value": "QA" },
            { "name": "workers", "value": "10" },
            { "name": "account.cleanup.interval", "value": "600" },
#            { "name": "guest.domain.suffix", "value": "sandbox.simulator" },
            { "name": "expunge.delay", "value": "60" },
            { "name": "vm.allocation.algorithm", "value": "random" },
            { "name": "expunge.interval", "value": "60" },
            { "name": "expunge.workers", "value": "3" },
            { "name": "check.pod.cidrs", "value": "false" },
            { "name": "secstorage.allowed.internal.sites", "value": "10.0.0.0/8,192.168.0.0/16,172.16.0.0/12" },
            { "name": "direct.agent.load.size", "value": "1000" } ]

        self.marvinCfg['mgtSvr'] = []
        self.marvinCfg['mgtSvr'].append({'mgtSvrIp': manSvrVMAddr, 'port': 8096})

        self.marvinCfg['zones'] = []

    def createJSONMarvinConfigFile(self):
        fn = xenrt.TEC().tempFile()
        fh = open(fn, 'w')
        json.dump(self.marvinCfg, fh)
        fh.close()
        return fn

    def addBasicZone(self, name, dnsAddr, secondaryStoragePath):
        zone = { 'name': name, 'networktype': 'Basic', 'pods': [], 'dns1': dnsAddr, 'internaldns1': dnsAddr }
        zone['secondaryStorages'] = [ { 'url': 'nfs://%s' % (secondaryStoragePath), 'provider': 'NFS' } ]
        trafficTypes = [ { 'typ': 'Guest' }, { 'typ': 'Management' } ]  
        providers = [ { 'name': 'VirtualRouter', 'broadcastdomainrange': 'Zone' }, { 'name': 'SecurityGroupProvider', 'broadcastdomainrange': 'Pod' } ]  
        zone['physical_networks'] = [ { 'name': 'basicPyhNetwork', 'traffictypes': trafficTypes, 'providers': providers } ]
        zone['pods'] = []
        self.marvinCfg['zones'].append(zone)
        return zone

    def addPod(self, name, zoneRef, netmask, gateway, sharedNetworkIPRange, managementIPRange):
        pod = { 'name': name, 'netmask': netmask, 'gateway': gateway, 'startip': managementIPRange[0], 'endip': managementIPRange[1], 'clusters': [] }
        pod['guestIpRanges'] = [ { 'netmask': netmask, 'gateway': gateway, 'startip': sharedNetworkIPRange[0], 'endip': sharedNetworkIPRange[1] } ]
        zoneRef['pods'].append(pod)
        return pod

    def addCluster(self, name, podRef, hostAddrList, primaryStoragePath = None, primaryStorageSRName = None):
        cluster = { 'clustername': name, 'hypervisor': 'XenServer', 'clustertype': 'CloudManaged' }
        cluster['hosts'] = map(lambda x: { 'username': 'root', 'password': xenrt.TEC().lookup("ROOT_PASSWORD"), 'url': 'http://%s' % (x) }, hostAddrList)
        if not primaryStoragePath:
            primaryStoragePath = 'presetup://localhost/%s' % (primaryStorageSRName)
        cluster['primaryStorages'] = [ { 'name': 'priStor1', 'url': primaryStoragePath } ]
        podRef['clusters'].append(cluster)
        return cluster 


class CitrixCloudBase(xenrt.TestCase):
    CS_MAN_SVR_VM_NAME = 'CS-MS'
    TEST_CONTROLLER_VM_NAME = 'CS-TC'

    EXCLUDED_MARVIN_TESTS = ['test_primary_storage']

    CS_GIT_REPO = 'https://git-wip-us.apache.org/repos/asf/cloudstack.git'

    CLOUD_CONFIG = {
        "mgtSvrIpAddr":     None,
        "dnsAddr":          None,
        "gateway":          None,
        "netmask":          None,
        "publicRange":      None,
        "managementRange":  None,
        "storageRange":     None,
        "infraNetwork":     None,
        "guestNetwork":     None,
        "storageNetwork":   None,
        "guestCIDR":        "192.168.200.0/24",
        "guestVLANRange":   None,
        "hostAddr":         None,
        "priStor":          None,
        "secStor":          None
    }

    CLOUD_ARTIFACTS = {
        'ccp-latest': {
            'release':  'CCP',
            'mansvr':   'http://repo-ccp.citrix.com/releases/release_builds/4.2.0/CloudPlatform-4.2.0-2-rhel6.3.tar.gz',
            'marvin':   'http://repo-ccp.citrix.com/releases/Marvin/4.3-forward/Marvin-master-asfrepo-current.tar.gz',
            'cmdprefix': 'cloudstack',
            'distro':   'rhel63'
            },
        'ccp-campo': {
            'release':  'CCP',
            'mansvr':   'http://repo-ccp.citrix.com/releases/release_builds/4.2.0/CloudPlatform-4.2.0-2-rhel6.3.tar.gz',
            'systemvm': 'http://download.cloud.com/templates/4.2/systemvmtemplate-2013-07-12-master-xen.vhd.bz2',
            'marvin':   'http://repo-ccp.citrix.com/releases/Marvin/4.2-forward/Marvin-master-asfrepo-current.tar.gz',
            'tcbranch': '4.2-forward',
            'cmdprefix': 'cloudstack',
            'distro':   'rhel63'
            },
        'ccp-307kt': {
            'release':  'CCP',
            'mansvr':   'http://download.cloud.com/support/kt/CloudStack-PATCH_C-Beta-3.0.7-4-rhel5.tar.gz',
            'systemvm': 'http://download.cloud.com/templates/acton/acton-systemvm-02062012.vhd.bz2',
            'marvin':   'http://repo-ccp.citrix.com/releases/Marvin/4.2-forward/Marvin-master-asfrepo-current.tar.gz',
            'tcbranch': '4.2-forward',
            'cmdprefix': 'cloud',
            'distro':   'rhel59'
            },
        'ccp-acton': {
            'release':  'CCP',
            'systemvm': 'http://download.cloud.com/templates/acton/acton-systemvm-02062012.vhd.bz2',
            'cmdprefix': 'cloud'
            },
        'acs-42-latest': {
            'release':  'ACS-prerelease',
            'mansvr':    { 'jenkinsurl': 'http://jenkins.buildacloud.org', 'jenkinsjobid': 'package-deb-4.2', 'artifacts': ['cloudstack-management', 'cloudstack-common'] },
            'systemvm':  { 'jenkinsurl': 'http://jenkins.buildacloud.org', 'jenkinsjobid': 'build-systemvm-4.2', 'artifacts': '' },
            'marvin':    { 'jenkinsurl': 'http://jenkins.buildacloud.org', 'jenkinsjobid': 'cloudstack-marvin', 'artifacts': 'Marvin' },
            'tcbranch':  None,
            'cmdprefix': 'cloudstack',
            'distro':    'ubuntu1204'
            },
        'acs-41': {
            'release':  'ACS',
            'mansvr':    { 'package-name': 'cloudstack-management', 'version': '4.1' },
            'systemvm':  'http://download.cloud.com/templates/acton/acton-systemvm-02062012.vhd.bz2',
            'marvin':    { 'jenkinsurl': 'http://jenkins.buildacloud.org', 'jenkinsjobid': 'cloudstack-marvin', 'artifacts': 'Marvin' },
            'tcbranch':  None,
            'cmdprefix': 'cloud',
            'distro':    'ubuntu1204'
            }
        }



############################################################################
# Lib methods
    def updateNetworkNameLabel(self, host, networkUUID, newName):
        if newName:
            host.genParamSet(ptype='network', uuid=networkUUID, param='name-label', value=newName)
        return host.genParamGet(ptype='network', uuid=networkUUID, param='name-label')

    def getResourceRange(self, resourceType, numberRequired):
        if resourceType == "IP6ADDR":
            return xenrt.StaticIP6Addr.getIPRange(numberRequired)
        elif resourceType == "IP4ADDR":
            return xenrt.StaticIP4Addr.getIPRange(numberRequired)
        elif resourceType == "VLAN":
            return xenrt.PrivateVLAN.getVLANRange(numberRequired)

    def reserveNetworkResources(self, publicIpSize=10, managementIpSize=5, storageIpSize=5, guestVLANSize=2, useIPv6=False):
        ipResourceType = useIPv6 and 'IP6ADDR' or 'IP4ADDR'

        self.publicIpResources = self.getResourceRange(resourceType=ipResourceType, numberRequired=publicIpSize)      
        self.managementIpResources = self.getResourceRange(resourceType=ipResourceType, numberRequired=managementIpSize)      
        self.storageIpResources = self.getResourceRange(resourceType=ipResourceType, numberRequired=storageIpSize)
        self.guestVLANResources = self.getResourceRange(resourceType='VLAN', numberRequired=guestVLANSize)
        if self.publicIpResources:
            xenrt.TEC().logverbose('Public IP Address Range: Start: %s, End: %s' % (self.publicIpResources[0].getAddr(), self.publicIpResources[-1].getAddr()))
        if self.managementIpResources:
            xenrt.TEC().logverbose('Management IP Address Range: Start: %s, End: %s' % (self.managementIpResources[0].getAddr(), self.managementIpResources[-1].getAddr()))
        if self.storageIpResources:
            xenrt.TEC().logverbose('Storage IP Address Range: Start: %s, End: %s' % (self.storageIpResources[0].getAddr(), self.storageIpResources[-1].getAddr()))
        if self.guestVLANResources:
            xenrt.TEC().logverbose('Guest VLAN ID Range: Start: %s, End: %s' % (self.guestVLANResources[0].getID(), self.guestVLANResources[-1].getID()))

    def releaseReservedNetworkResources(self):
        xenrt.TEC().logverbose('Releasing network resources')
        map(lambda x:x.release(), self.publicIpResources)
        map(lambda x:x.release(), self.managementIpResources)
        map(lambda x:x.release(), self.storageIpResources)
        map(lambda x:x.release(), self.guestVLANResources)


    def getNfsSrName(self, host):
        nfsSrs = host.getSRs(type='nfs')
        if len(nfsSrs) != 1:
            raise xenrt.XRTError('Invalid number of NFS SRs: Expected 1, Actual: %d' % (len(nfsSrs)))
        return host.genParamGet('sr', nfsSrs[0], 'name-label')


    def installManSvrRHEL(self, manSvrVM, cloudArtifacts):
        if cloudArtifacts['release'] == 'CCP':
            manSvrVM.execguest('wget %s -O cp.tar.gz' % (cloudArtifacts['mansvr']))
            manSvrVM.execguest('mkdir cloudplatform')
            manSvrVM.execguest('tar -zxvf cp.tar.gz -C /root/cloudplatform')
            installDir = os.path.dirname(manSvrVM.execguest('find cloudplatform/ -type f -name install.sh'))
            manSvrVM.execguest('cd %s && ./install.sh -m' % (installDir))
        else:
            raise xenrt.XRTError('Installing release type %s not implemented' % (cloudArtifacts['release']))

        manSvrVM.execguest('setenforce Permissive')
        manSvrVM.execguest('service nfs start')

        manSvrVM.execguest('yum -y install mysql-server mysql')        
        manSvrVM.execguest('service mysqld restart')

        manSvrVM.execguest('mysql -u root --execute="GRANT ALL PRIVILEGES ON *.* TO \'root\'@\'%\' WITH GRANT OPTION"')
        manSvrVM.execguest('iptables -I INPUT -p tcp --dport 3306 -j ACCEPT')
        manSvrVM.execguest('mysqladmin -u root password xensource')
        manSvrVM.execguest('service mysqld restart')

        setupDbLoc = manSvrVM.execguest('find /usr/bin -name %s-setup-databases' % (cloudArtifacts['cmdprefix'])).strip()
        manSvrVM.execguest('%s cloud:cloud@localhost --deploy-as=root:xensource' % (setupDbLoc))

        manSvrVM.execguest('iptables -I INPUT -p tcp --dport 8096 -j ACCEPT')
        setupMsLoc = manSvrVM.execguest('find /usr/bin -name %s-setup-management' % (cloudArtifacts['cmdprefix'])).strip()
        manSvrVM.execguest(setupMsLoc)


    def installCSManSvrUbuntu1204(self, manSvrVM, cloudArtifacts):
        hostname = manSvrVM.execguest('hostname --fqdn').strip()
        # TODO Check host name

        manSvrVM.execguest("echo 'deb http://ftp.ubuntu.com/ubuntu precise universe' >> /etc/apt/sources.list")
        manSvrVM.execguest('apt-get update')
        manSvrVM.execguest('apt-get install openntpd')

        if cloudArtifacts['release'] == 'ACS':
            manSvrVM.execguest('touch /etc/apt/sources.list.d/cloudstack.list')
#        manSvrVM.execguest("echo 'deb http://cloudstack.apt-get.eu/ubuntu precise 4.0' >> /etc/apt/sources.list.d/cloudstack.list")
            manSvrVM.execguest("echo 'deb http://cloudstack.apt-get.eu/ubuntu precise %s' >> /etc/apt/sources.list.d/cloudstack.list" % (cloudArtifacts['mansvr']['version']))
            manSvrVM.execguest('wget -O - http://cloudstack.apt-get.eu/release.asc|apt-key add -')
            manSvrVM.execguest('apt-get update')

            manSvrVM.execguest('apt-get -y --force-yes install %s' % (cloudArtifacts['mansvr']['package-name']), timeout=60*60)
        elif cloudArtifacts['release'] == 'ACS-prerelease':
            destLocation = '/tmp'
            for pkgUrl in cloudArtifacts['mansvr']:
                manSvrVM.execguest('wget %s -P %s' % (pkgUrl, destLocation))

            try:
                manSvrVM.execguest('dpkg -i %s' % (os.path.join(destLocation, '*.deb')))
            except xenrt.XRTFailure, e:
                xenrt.TEC().logverbose('Expected error: %s' % (e.data))
            manSvrVM.execguest('apt-get -y -f install')
        else:
            raise xenrt.XRTError('Installing release type %s not implemented' % (cloudArtifacts['release']))


#        self.installLastGoodManSvrPkg(manSvrVM, version='4.2')
#        self.install41PublicManSvrPkg(manSvrVM)

       # TODO - needs fixing
#        manSvrVM.execguest('wget http://download.cloud.com.s3.amazonaws.com/tools/vhd-util -O /usr/lib/cloud/common/scripts/vm/hypervisor/xenserver/vhd-util')
        manSvrVM.execguest('wget http://download.cloud.com.s3.amazonaws.com/tools/vhd-util -O /usr/share/cloudstack-common/scripts/vm/hypervisor/xenserver/vhd-util')

#        manSvrVM.execguest('export DEBIAN_FRONTEND=noninteractive')
        manSvrVM.execguest('apt-get -q -y install mysql-server')
        manSvrVM.execguest('mysqladmin -u root password xensource')


        manSvrVM.execguest('cp /etc/mysql/my.cnf /etc/mysql/my.cnf.bak')
        manSvrVM.execguest('sed s/bind-address/#bind-address/ /etc/mysql/my.cnf.bak > /etc/mysql/my.cnf')


        mySqlConfFile = '/etc/mysql/conf.d/cloudstack.cnf'
        fn = xenrt.TEC().tempFile()
        fh = open(fn, 'w')
        fh.write("[mysqld]\n")
        fh.write("innodb_rollback_on_timeout=1\n")
        fh.write("innodb_lock_wait_timeout=600\n")
        fh.write("max_connections=350\n")
        fh.write("log-bin=mysql-bin\n")
        fh.write("binlog-format = 'ROW'\n") 
#        fh.write("bind-address = %s\n" % (manSvrVM.getIP()))
        fh.close()
        sftp = manSvrVM.sftpClient()
        sftp.copyTo(fn, mySqlConfFile)
        sftp.close()

        manSvrVM.execguest('service mysql restart')

        setupDbLoc = manSvrVM.execguest('find /usr/bin -name %s-setup-databases' % (cloudArtifacts['cmdprefix'])).strip()
        manSvrVM.execguest('%s cloud:cloud@localhost --deploy-as=root:xensource' % (setupDbLoc))
 
        setupMsLoc = manSvrVM.execguest('find /usr/bin -name %s-setup-management' % (cloudArtifacts['cmdprefix'])).strip()
        manSvrVM.execguest(setupMsLoc)

    def restartManagementService(self, manSvrVM, cmdPrefix):
        manSvrVM.execguest('service %s-management stop' % (cmdPrefix))
        # Wait for service to stop (Campo bug - service stop completes before service actually stops)
        xenrt.sleep(120)

        manSvrVM.execguest('service %s-management start' % (cmdPrefix))
        # Wait for service to start
        xenrt.sleep(180)

    def createMarvinConfigFile(self, manSvrIPAddr, hostAddrList=None):
        marvinCfg = {}
        marvinCfg['dbSvr'] = {}
        marvinCfg['dbSvr']['dbSvr'] = manSvrIPAddr
        marvinCfg['dbSvr']['passwd'] = 'cloud'
        marvinCfg['dbSvr']['db'] = 'cloud'
        marvinCfg['dbSvr']['port'] = 3306
        marvinCfg['dbSvr']['user'] = 'cloud'

        marvinCfg['logger'] = []
        marvinCfg['logger'].append({'name': 'TestClient', 'file': '/tmp/testclient.log'})
        marvinCfg['logger'].append({'name': 'TestCase', 'file': '/tmp/testcase.log'})

        marvinCfg['globalConfig'] = [
            { "name": "network.gc.wait", "value": "60" },
            { "name": "storage.cleanup.interval", "value": "300" },
            { "name": "vm.op.wait.interval", "value": "5" },
            { "name": "default.page.size", "value": "10000" },
            { "name": "network.gc.interval", "value": "60" },
#            { "name": "instance.name", "value": "QA" },
            { "name": "workers", "value": "10" },
            { "name": "account.cleanup.interval", "value": "600" },
#            { "name": "guest.domain.suffix", "value": "sandbox.simulator" },
            { "name": "expunge.delay", "value": "60" },
            { "name": "vm.allocation.algorithm", "value": "random" },
            { "name": "expunge.interval", "value": "60" },
            { "name": "expunge.workers", "value": "3" },
            { "name": "check.pod.cidrs", "value": "true" },
#            { "name": "secstorage.allowed.internal.sites", "value": "10.147.28.0/24" },
            { "name": "direct.agent.load.size", "value": "1000" } ]

        marvinCfg['mgtSvr'] = []
        marvinCfg['mgtSvr'].append({'mgtSvrIp': manSvrIPAddr, 'port': 8096})

        if hostAddrList:
            hostList = []
            for addr in hostAddrList:
                hostList.append( {"username": "root", "password": xenrt.TEC().lookup("ROOT_PASSWORD"), "url": "http://%s" % (addr)} )
            cluster = {"clustername": "Test Cluster", "hypervisor": "XenServer", "hosts": hostList}
            pod = {"name": "Test Pod", "clusters": [cluster]}
            zone = {"name": "TestZone", "networktype": "Advanced", "pods": [pod]}
            marvinCfg["zones"] = [zone] 

        fn = xenrt.TEC().tempFile()
        fh = open(fn, 'w')
        json.dump(marvinCfg, fh)
        fh.close()
        return fn

    def getArtifactsFromJenkins(self, configDict):
        j = Jenkins(configDict['jenkinsurl'])
        if configDict['jenkinsjobid'] not in j.keys():
            raise xenrt.XRTError('No Jenkins job found with id: %s' % (configDict['jenkinsjobid']))

        lastGoodBuild = j[configDict['jenkinsjobid']].get_last_good_build()
        artifacts = lastGoodBuild.get_artifact_dict()

        if isinstance(configDict['artifacts'], list):
            urlList = []
            for artifactName in configDict['artifacts']:
                artifactList = filter(lambda x:x.startswith(artifactName), artifacts)
                xenrt.TEC().logverbose('Found %d artifacts with name: %s %s' % (len(artifactList), artifactName, artifactList))
                if not len(artifactList) == 1:
                    raise xenrt.XRTError('Could not find unique Jenkins artifact from name %s' % (artifactName))
                urlList.append(artifacts[artifactList[0]].url)
            return urlList
        else:
            artifactList = filter(lambda x:x.startswith(configDict['artifacts']), artifacts)
            xenrt.TEC().logverbose('Found %d artifacts with name: %s %s' % (len(artifactList), configDict['artifacts'], artifactList))
            if not len(artifactList) == 1:
                raise xenrt.XRTError('Could not find unique Jenkins artifact from name %s' % (configDict['artifacts']))
            return artifacts[artifactList[0]].url

    def getCloudArtifacts(self, cloudRelease=None):
        if not cloudRelease:
            cloudRelease = xenrt.TEC().lookup("CLOUD_RELEASE", default='ccp-campo')
            if not self.CLOUD_ARTIFACTS.has_key(cloudRelease):
                raise xenrt.XRTError('Cloud artifacts lookup failed for %s' % (cloudRelease))

        releaseDict = self.CLOUD_ARTIFACTS[cloudRelease]
        if isinstance(releaseDict['mansvr'], dict) and releaseDict['mansvr'].has_key('jenkinsurl'):
            releaseDict['mansvr'] = self.getArtifactsFromJenkins(releaseDict['mansvr'])

        if releaseDict.has_key('systemvm'):
            if isinstance(releaseDict['systemvm'], dict) and releaseDict['systemvm'].has_key('jenkinsurl'):
                releaseDict['systemvm'] = self.getArtifactsFromJenkins(releaseDict['systemvm'])

        if isinstance(releaseDict['marvin'], dict) and releaseDict['marvin'].has_key('jenkinsurl'):
            releaseDict['marvin'] = self.getArtifactsFromJenkins(releaseDict['marvin'])

        for (k,v) in releaseDict.items():
            xenrt.TEC().comment('%s: %s' % (k,v))
        return releaseDict


    def installCSTestControllerUbuntu1204(self, testContVM, cloudArtifacts):
        testContVM.execguest("echo 'deb http://ftp.ubuntu.com/ubuntu precise universe' >> /etc/apt/sources.list")
        testContVM.execguest('apt-get update')
        testContVM.execguest('apt-get -y install python-pip python-dev build-essential git')

        srcMarvinLocation = cloudArtifacts['marvin']
        destMarvinLocation = os.path.join('/tmp', os.path.basename(srcMarvinLocation))
        testContVM.execguest('wget %s -O %s' % (srcMarvinLocation, destMarvinLocation))

        testContVM.execguest('pip install %s' % (destMarvinLocation))
        testContVM.execguest('tar -zxvf %s' % (destMarvinLocation))

        getMarvinTests = xenrt.TEC().lookup("GET_MARVIN_TEST_CODE", True, boolean=True)
        if getMarvinTests:
            branchStr = ''
            if cloudArtifacts.has_key('tcbranch'):
                branchStr = '-b %s' % (cloudArtifacts['tcbranch'])
            testContVM.execguest('git clone --depth=1 %s %s' % (branchStr, self.CS_GIT_REPO), timeout=60*60)

    def parseXUnitResults(self, xUnitResultFile):
        fh = open(xUnitResultFile)
        xmlStr = fh.read()
        fh.close()

        treeData = etree.fromstring(xmlStr)
        resultData = { 'tests':    int(treeData.get('tests')),
                       'errors':   int(treeData.get('errors')), 
                       'failures': int(treeData.get('failures')),
                       'skipped':  int(treeData.get('skip'))
                     }
        return resultData 

    def getLogs(self, logsubdir, marvinLogFolderPath=None, testContVM=None, manSvrVM=None):
        if testContVM:
            sftp = testContVM.sftpClient()
            sftp.copyTreeFrom(marvinLogFolderPath, logsubdir)

#            logFiles = testContVM.execguest('find /tmp -type f -name *.log').splitlines()
#            for logFile in logFiles:
#                sftp.copyFrom(logFile, os.path.join(logsubdir, os.path.basename(logFile)))
            sftp.close()

        if manSvrVM:
            sftp = manSvrVM.sftpClient()
            manSvrLogsLoc = manSvrVM.execguest('find /var/log -type f -name management-server.log').strip()
            sftp.copyTreeFrom(os.path.dirname(manSvrLogsLoc), logsubdir)
            sftp.close()

    def executeMarvinTest(self, testContVM, manSvrVM, configFile, testName=None, tag=None, storeLogs=True, checkResults=True, legacyLogCollection=True):
        pollPeriod = 300
        result = None
        logDir = ''

        marvinLogFolderPath = '/tmp/marvinlogs/'
        if testContVM.execguest('test -e %s' % (marvinLogFolderPath), retval="code") != 0: 
            testContVM.execguest('mkdir %s' % (marvinLogFolderPath))

        marvinConfigLocation = os.path.join(marvinLogFolderPath, 'marvincfg.cfg')
        xunitResultsLocation = os.path.join(marvinLogFolderPath, 'marvin.xml')

        sftp = testContVM.sftpClient()
        sftp.copyTo(configFile, marvinConfigLocation)


        if legacyLogCollection:
            clientLogLocation = os.path.join(marvinLogFolderPath, 'marvin.client.log')
            resultLogLocation = os.path.join(marvinLogFolderPath, 'marvin.results.log')

            execCommand = 'nosetests -v --logging-level=DEBUG --result-log=%s --client-log=%s --with-marvin --marvin-config=%s --with-xunit --xunit-file=%s' % (resultLogLocation, clientLogLocation, marvinConfigLocation, xunitResultsLocation)
        else:
            execCommand = 'nosetests -v --logging-level=DEBUG --log-folder-path=%s --with-marvin --marvin-config=%s --with-xunit --xunit-file=%s' % (marvinLogFolderPath, marvinConfigLocation, xunitResultsLocation)
 
        if testName:
            testLocation = testContVM.execguest('find cloudstack/test/ -type f -name %s' % (testName)).strip()
            execCommand += ' --load %s' % (testLocation)
            logDir = testName
        elif tag:
            execCommand += ' --load -a tags=%s cloudstack/test/integration/smoke' % (tag)
            logDir = tag
        else:
            # Don't get logs when we are just applying Marvin config.
            pollPeriod = 30
            logDir = 'deploy'

        # Specify excluded tests
        testExcludeStr = ''
        for excludedTest in self.EXCLUDED_MARVIN_TESTS:
            xenrt.TEC().comment('Excluding tests that match the REGEX: %s' % (excludedTest))
            testExcludeStr += ' --exclude=%s' % (excludedTest)
        execCommand += testExcludeStr

        pid = int(testContVM.execguest('%s &> /dev/null & echo $!' % (execCommand)).strip())
        xenrt.TEC().logverbose('Marvin nosetests started with PID: %d' % (pid))
        while (testContVM.execguest('ps -p %d' % (pid), retval='code') == 0):
            xenrt.sleep(pollPeriod)

        if storeLogs:
            logsubdir = os.path.join(xenrt.TEC().getLogdir(), 'cloud', logDir)
            if not os.path.exists(logsubdir):
                os.makedirs(logsubdir)
 
            self.getLogs(logsubdir, marvinLogFolderPath, testContVM, manSvrVM)

            if checkResults:
                xmlFileDest = os.path.join(logsubdir, os.path.basename(xunitResultsLocation))
                result = self.parseXUnitResults(xmlFileDest)
        sftp.close()

        return result
 
    def configureCloudstack(self, testContVM, manSvrVMAddr, secondaryStoragePath, hostAddr, networkNames, primaryStorageNameLabel):
        config = self.CLOUD_CONFIG

        config['dnsAddr'] = xenrt.TEC().config.lookup("XENRT_SERVER_ADDRESS")
        config['gateway'] = xenrt.TEC().config.lookup(['NETWORK_CONFIG', 'DEFAULT', 'GATEWAY'])
        config['netmask'] = xenrt.TEC().config.lookup(['NETWORK_CONFIG', 'DEFAULT', 'SUBNETMASK'])

        config['publicRange'] = [self.publicIpResources[0].getAddr(), self.publicIpResources[-1].getAddr()]
        config['managementRange'] = [self.managementIpResources[0].getAddr(), self.managementIpResources[-1].getAddr()]
        config['storageRange'] = [self.storageIpResources[0].getAddr(), self.storageIpResources[-1].getAddr()]
        config['guestVLANRange'] = [int(self.guestVLANResources[0].getID()), int(self.guestVLANResources[-1].getID())]

        config['mgtSvrIpAddr'] = manSvrVMAddr
        config['hostAddr'] = hostAddr
        config['priStor'] = primaryStorageNameLabel
        config['secStor'] = secondaryStoragePath

        config['infraNetwork'] = networkNames['infra']
        config['guestNetwork'] = networkNames['guest']
        config['storageNetwork'] = networkNames['storage']

        xenrt.TEC().logverbose(config)

        fn = xenrt.TEC().tempFile()
        fh = open(fn, 'w')
        json.dump(config, fh)
        fh.close()

        cloudConfigLocation = '/tmp/cloudcfg.cfg'
        configureScriptLocation = '/tmp/cloudConfigure.py'
        sftp = testContVM.sftpClient()
        sftp.copyTo(fn, cloudConfigLocation)

        cloudScriptDir = os.path.join(xenrt.TEC().lookup("LOCAL_SCRIPTDIR"), 'cloud')
        sftp.copyTo(os.path.join(cloudScriptDir, 'cloudConfigure.py'), configureScriptLocation)

        testContVM.execguest('python %s %s' % (configureScriptLocation, cloudConfigLocation))

    def postInstallCSManSvr(self, manSvrVM, secondaryStorageServerPath, cloudArtifacts):
        # Get service VM template
        if cloudArtifacts.has_key('systemvm'):
            sysTemplateUrl = cloudArtifacts['systemvm']
        else:
            sysTemplateFile = xenrt.TEC().getFile('/usr/groups/xenrt/cloud/systemvmtemplate-2013-07-12-master-xen.vhd.bz2')
            webdir = xenrt.WebDirectory()
            webdir.copyIn(sysTemplateFile)
            sysTemplateUrl = webdir.getURL(os.path.basename(sysTemplateFile))

        manSvrVM.execguest('mount %s /media' % (secondaryStorageServerPath))
        installSysTmpltLoc = manSvrVM.execguest('find / -name *install-sys-tmplt').strip()
        manSvrVM.execguest('%s -m /media -u %s -h xenserver -F' % (installSysTmpltLoc, sysTemplateUrl), timeout=60*60)
#        manSvrVM.execguest('/usr/share/cloudstack-common/scripts/storage/secondary/cloud-install-sys-tmplt -m /media -u %s -h xenserver -F' % (systemVMUrl), timeout=60*60)
        manSvrVM.execguest('umount /media')

        # Set the API port
        manSvrVM.execguest('mysql -u cloud --password=cloud --execute="UPDATE cloud.configuration SET value=8096 WHERE name=\'integration.api.port\'"')

        self.restartManagementService(manSvrVM, cloudArtifacts['cmdprefix'])

    def _getConnectedNonManagementPifUUIDs(self, host):
        pifUUIDs = host.minimalList('pif-list', 'uuid', 'management=false')
        connectedPifUUIDs = filter(lambda x:host.genParamGet('pif', x, 'carrier') == 'true', pifUUIDs)
        return connectedPifUUIDs

    def xsHostWorkarounds(self, pool):
        # Tampa + CS 4.1
        pool.master.execdom0('ln -s /usr/bin/vhd-util /opt/xensource/bin')

    def _prepareXSHosts(self, pool):
#        self.xsHostWorkarounds(pool)
        networkNames = {'infra': None, 'guest': None, 'storage': None}

        infraNetworkUUID = pool.master.minimalList("pif-list", "network-uuid", "management=true host-uuid=%s" % pool.master.getMyHostUUID())[0]
        networkNames['infra'] = self.updateNetworkNameLabel(pool.master, infraNetworkUUID, newName='cs-infra')

        nonManPIFUUIDs = self._getConnectedNonManagementPifUUIDs(pool.master)
        nwList = pool.master.parameterList('network-list', ['uuid', 'PIF-uuids'])
        nonManNwList = filter(lambda x:x['uuid'] != infraNetworkUUID, nwList)
        connectedNetworkUuids = []
        for nwData in nonManNwList:
            if nwData['PIF-uuids'] != '':
                pifs = nwData['PIF-uuids'].split(';')
                if len(pifs) == len(pool.getHosts()):
                    disconnectedPIFs = filter(lambda x:x.strip() not in nonManPIFUUIDs, pifs)
                    if len(disconnectedPIFs) == 0:
                        connectedNetworkUuids.append(nwData['uuid'])

        if len(connectedNetworkUuids) == 0:
            raise xenrt.XRTError('No physical network available for the guest network')
        elif len(connectedNetworkUuids) > 1:
            storageNetworkUUID = connectedNetworkUuids[1]
            networkNames['storage'] = self.updateNetworkNameLabel(pool.master, storageNetworkUUID, newName='storage')

        guestNetworkUUID = connectedNetworkUuids[0]
        networkNames['guest'] = self.updateNetworkNameLabel(pool.master, guestNetworkUUID, newName='guest')

        return networkNames

    def _prepareCSManSvr(self, infrastructureHost, secondaryStorage, cloudArtifacts): 
        existingGuests = infrastructureHost.listGuests()
        if self.CS_MAN_SVR_VM_NAME in existingGuests:
            manSvrVM = infrastructureHost.getGuest(self.CS_MAN_SVR_VM_NAME)
        else:
            # Create VM
            pass

        if not cloudArtifacts['distro'] == manSvrVM.distro:
            raise xenrt.XRTError('No VM with distro %s' % (cloudArtifacts['distro']))

        if manSvrVM.distro == 'ubuntu1204':
            self.installCSManSvrUbuntu1204(manSvrVM, cloudArtifacts)
        elif manSvrVM.distro.startswith('rhel'):
            self.installManSvrRHEL(manSvrVM, cloudArtifacts)
        else:
            raise xenrt.XRTError('No method for installing Citrix Cloud on %s' % (manSvrVM.distro))

        self.postInstallCSManSvr(manSvrVM, secondaryStorage.getMount(), cloudArtifacts)
        manSvrVM.checkpoint(name='Fresh-Mngmt-Server')
        return manSvrVM

    def _prepareCSTestController(self, infrastructureHost, cloudArtifacts):
        existingGuests = infrastructureHost.listGuests()
        if self.TEST_CONTROLLER_VM_NAME in existingGuests:
            testContVM = infrastructureHost.getGuest(self.TEST_CONTROLLER_VM_NAME)
        else:
            # Create VM
            pass        

        self.installCSTestControllerUbuntu1204(testContVM, cloudArtifacts)
        return testContVM        

    def changeCloudHostProductVersion(self, pool, newVersion='6.2.0'):
        xenrt.TEC().warning('Changing product version to be CCP compatible')

        hosts = [pool.master] + pool.getSlaves()
        for host in hosts:
            inventory = host.execdom0('cat /etc/xensource-inventory')
            newInventory = re.sub("PRODUCT_VERSION='.*'", "PRODUCT_VERSION='%s'" % (newVersion), inventory)

            host.execdom0('echo "%s" > /etc/xensource-inventory' % (newInventory))
            host.restartToolstack()
            if pool.master.genParamGet(ptype='host', uuid=host.uuid, param='software-version', pkey='product_version') != newVersion:
                raise xenrt.XRTError('Failed to modify product version')

    def prepare(self, arglist):
        cloudArtifacts = self.getCloudArtifacts()

        self.infrastructureHost = self.getHost("RESOURCE_HOST_0")
        self.xsPool = self.getDefaultPool()
        version = self.xsPool.master.checkVersion(versionNumber=True)
        # Run trunk against Clearwater templates
        if version == '6.2.50':
            self.changeCloudHostProductVersion(self.xsPool)

        xenrt.TEC().comment('Infrastructure Host: %s, Pool Master: %s, Slaves: %s' % (self.infrastructureHost.getName(), self.xsPool.master.getName(), self.xsPool.listSlaves()))

        self.secondaryStorage = xenrt.ExternalNFSShare()

        prepareTasks = []
        prepareTasks.append(xenrt.PTask(self._prepareCSManSvr, self.infrastructureHost, self.secondaryStorage, cloudArtifacts))
        prepareTasks.append(xenrt.PTask(self._prepareCSTestController, self.infrastructureHost, cloudArtifacts))

        (self.manSvrVM, self.testContVM) = xenrt.pfarm(prepareTasks)

    def run(self, arglist=None):
        pass

    def postRun(self):
        self.releaseReservedNetworkResources()
        self.secondaryStorage.release()
        self.manSvrVM.shutdown()

class TCBasicCloudStack(CitrixCloudBase):

    def run(self, arglist=None):
        self.reserveNetworkResources(publicIpSize=10, managementIpSize=5, storageIpSize=0, guestVLANSize=0, useIPv6=False)
        secondaryStoragePath = self.secondaryStorage.getMount().replace(':','')

        dnsAddr = xenrt.TEC().config.lookup("XENRT_SERVER_ADDRESS")
        gateway = xenrt.TEC().config.lookup(['NETWORK_CONFIG', 'DEFAULT', 'GATEWAY'])
        netmask = xenrt.TEC().config.lookup(['NETWORK_CONFIG', 'DEFAULT', 'SUBNETMASK'])

        marvinConf = MarvinConfig(self.manSvrVM.getIP())
        zone = marvinConf.addBasicZone('TestZone', dnsAddr, secondaryStoragePath)
        pod = marvinConf.addPod('TestPod', zone, netmask, gateway, [self.publicIpResources[0].getAddr(), self.publicIpResources[-1].getAddr()],
                                                                   [self.managementIpResources[0].getAddr(), self.managementIpResources[-1].getAddr()])
        cluster = marvinConf.addCluster('TestCluster', pod, [self.xsPool.master.getIP()], primaryStorageSRName='CS-PRI')
        marvinConfigFile = marvinConf.createJSONMarvinConfigFile()

        self.executeMarvinTest(self.testContVM, self.manSvrVM, marvinConfigFile, storeLogs=True, checkResults=False, legacyLogCollection=False)

        cloudArtifacts = self.getCloudArtifacts()
        self.restartManagementService(self.manSvrVM, cloudArtifacts['cmdprefix'])

    def postRun(self):
        # Don't release the resources - they will be released by the XenRT resource clean-up mechanism
        pass

class TCCloudStackBvt(CitrixCloudBase):

    def run(self, arglist=None):
        self.reserveNetworkResources(publicIpSize=10, managementIpSize=5, storageIpSize=5, guestVLANSize=2, useIPv6=False)
        networkNames = self._prepareXSHosts(self.xsPool)
        secondaryStoragePath = self.secondaryStorage.getMount().replace(':','')

        try:
            self.configureCloudstack(self.testContVM, self.manSvrVM.getIP(), secondaryStoragePath, self.xsPool.master.getIP(), networkNames, self.getNfsSrName(self.xsPool.master))
        except Exception as e:
            raise e
        finally:
            logsubdir = os.path.join(xenrt.TEC().getLogdir(), 'cloud', 'deploy')
            if not os.path.exists(logsubdir):
                os.makedirs(logsubdir)
            self.getLogs(logsubdir, manSvrVM=self.manSvrVM)

        marvinConfigFile = self.createMarvinConfigFile(self.manSvrVM.getIP())
        self.executeMarvinTest(self.testContVM, self.manSvrVM, marvinConfigFile, storeLogs=False)

        cloudArtifacts = self.getCloudArtifacts()
        self.restartManagementService(self.manSvrVM, cloudArtifacts['cmdprefix'])

        marvinConfigFile = self.createMarvinConfigFile(self.manSvrVM.getIP(), map(lambda x:x.getIP(), self.xsPool.getHosts()))
        testResult = self.executeMarvinTest(self.testContVM, self.manSvrVM, marvinConfigFile, tag='smoke')

        xenrt.TEC().comment('Marvin tests executed: %d' % (testResult['tests']))
        xenrt.TEC().comment('Marvin tests failed:   %d' % (testResult['failures']))
        xenrt.TEC().comment('Marvin test errors:    %d' % (testResult['errors']))
        xenrt.TEC().comment('Marvin tests skipped:  %d' % (testResult['skipped']))

# Prototype test case for cloud scale
import xenrt.lib.cloud
class TCCloudScale(xenrt.TestCase):
    SERVICE_OFFERING_NAME = 'Small Instance'
    DISK_OFFERING_NAME = 'Small'
    TEMPLATE_NAME = 'CentOS 5.6(64-bit) no GUI (XenServer)'

    def getInstancesInfo(self):
        try:
            instances = self.marvinApi.cloudApi.listVirtualMachines()
        except Exception, e:
            xenrt.TEC().logverbose('Failed to list Instances: %s' % (str(e)))
            return {}

        infoDict = {}
        stateList = map(lambda x:x.state, instances)
        for state in list(set(stateList)):
            infoDict[state] = stateList.count(state)
            xenrt.TEC().logverbose('%d instances in state: %s' % (infoDict[state], state))

        return infoDict

    def waitForAllInstancesToReachState(self, state, timeout=300):
        startTime = datetime.now()
        while(True):
            info = self.getInstancesInfo()
            timeTaken = (datetime.now() - startTime).seconds
            if len(info.keys()) == 1 and info.has_key(state):
                xenrt.TEC().logverbose('All instances reached the %s state in %d seconds' % (state, timeTaken))
                break
            elif timeTaken < timeout:
                xenrt.sleep(60)
            else:
                raise xenrt.XRTFailure('Timeout expired waiting for all instances to reach %s state' % (state))
        return timeTaken

    def start(self, instanceId):
        xenrt.TEC().logverbose('Start instance %s' % (instanceId))
        self.marvinApi.cloudApi.startVirtualMachine(id = instanceId, isAsync = "false")

    def stop(self, instanceId):
        xenrt.TEC().logverbose('stop instance %s' % (instanceId))
        self.marvinApi.cloudApi.stopVirtualMachine(id = instanceId, isAsync = "false")

    def updateInstances(self, operation):
        instances = self.marvinApi.cloudApi.listVirtualMachines()
        instanceIds = map(lambda x:x.id, instances)

        map(lambda x:getattr(self, operation)(x), instanceIds)

    def createInstances(self, number, startInstances=False, basename='Instance'):
        xenrt.TEC().logverbose('Creating %d instances' % (number))
        baseName = basename+'-%d'
        for i in range(number):
            instanceName=baseName % i
            xenrt.TEC().logverbose('Deploying instance: %s' % (instanceName))
            self.marvinApi.cloudApi.deployVirtualMachine(
                    serviceofferingid = self.serviceOffering.id,
                    diskofferingid = self.diskOffering.id,
                    templateid = self.template.id,
                    zoneid = self.zone.id,
                    startvm = startInstances and 'true' or 'false',
                    name=instanceName)
            xenrt.TEC().logverbose('Deployed instance: %s' % (instanceName))

    def prepare(self, arglist):
        self.manSvr = xenrt.lib.cloud.ManagementServer(xenrt.TEC().registry.guestGet('CS-MS'))
        self.marvinApi = xenrt.lib.cloud.MarvinApi(self.manSvr)
        api = self.marvinApi.cloudApi

        self.marvinApi.setCloudGlobalConfig(name='execute.in.sequence.hypervisor.commands', value='false')
        self.marvinApi.setCloudGlobalConfig(name='execute.in.sequence.network.element.commands', value='false', restartManagementServer=True)

        self.marvinApi.waitForTemplateReady(self.TEMPLATE_NAME)
        self.template = api.listTemplates(templatefilter='featured', name=self.TEMPLATE_NAME)[0]
        self.serviceOffering = api.listServiceOfferings(name=self.SERVICE_OFFERING_NAME)[0]
        self.diskOffering = api.listDisckOfferings(name=self.DISK_OFFERING_NAME)[0]
        self.zone = api.listZones()[0]

        capacity = api.listCapacity(zoneid=self.zone.id, type=8)[0]
        self.numberOfInstances = capacity.capacitytotal - (capacity.capacityused + 3)
        self.createInstances(number=self.numberOfInstances)
        self.waitForAllInstancesToReachState('Stopped', timeout=(30*self.numberOfInstances))

    def run(self, arglist):
        self.updateInstances('start')
        self.waitForAllInstancesToReachState('Running', timeout=(60*self.numberOfInstances))

        self.updateInstances('stop')
        self.waitForAllInstancesToReachState('Stopped', timeout=(60*self.numberOfInstances))

    def postRun(self):
        logsubdir = os.path.join(xenrt.TEC().getLogdir(), 'cloud')
        if not os.path.exists(logsubdir):
            os.makedirs(logsubdir)
        self.manSvr.getLogs(logsubdir)


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
        if self.upgradeHook.DO_UPDATE:
            xenrt.lib.xenserver.host.RollingPoolUpdate.doUpdateHost(self, host)
        else:
            xenrt.TEC().logverbose('SKIPPING Update Host: %s' % (host.getName()))

class TCCloudUpgrade(TCCloudScale):
    TEMPLATE_NAME = 'CentOS 5.6(64-bit) no GUI (XenServer)'
    DO_UPDATE = True

    def prepare(self, arglist):
        # Ignore hotfix options when running the lib upgrade code
        xenrt.TEC().config.setVariable("OPTION_NO_AUTO_PATCH", True)

        self.manSvr = xenrt.lib.cloud.ManagementServer(xenrt.TEC().registry.guestGet('CS-MS'))
        self.marvinApi = xenrt.lib.cloud.MarvinApi(self.manSvr)
        api = self.marvinApi.cloudApi

        self.pool = self.getDefaultPool()

        self.marvinApi.waitForTemplateReady(self.TEMPLATE_NAME)
        self.template = api.listTemplates(templatefilter='featured', name=self.TEMPLATE_NAME)[0]
        self.serviceOffering = api.listServiceOfferings(name=self.SERVICE_OFFERING_NAME)[0]
        self.diskOffering = api.listDiskOfferings(name=self.DISK_OFFERING_NAME)[0]
        self.zone = api.listZones()[0]

        capacity = api.listCapacity(zoneid=self.zone.id, type=8)[0]
        self.numberOfInstances = capacity.capacitytotal - (capacity.capacityused + 6)
        self.createInstances(number=self.numberOfInstances, startInstances=True, basename='preUpdateInst')
        self.waitForAllInstancesToReachState('Running', timeout=(60*5))

    def setHostResourceState(self, host, maintenance):
        xenrt.TEC().logverbose('Set host: %s to maintenance = %s' % (host.getName(), maintenance))
        hostId = self.marvinApi.cloudApi.listHosts(name=host.getName())[0].id
        if maintenance:
            self.marvinApi.cloudApi.prepareHostForMaintenance(id=hostId)
        else:
            self.marvinApi.cloudApi.cancelHostMaintenance(id=hostId)

        expectedResourceState = maintenance and 'Maintenance' or 'Enabled'
        resourceState = None
        while(resourceState != expectedResourceState):
            xenrt.sleep(10)
            resourceState = self.marvinApi.cloudApi.listHosts(name=host.getName())[0].resourcestate
            xenrt.TEC().logverbose('Waiting for host: %s, Current Resource State: %s, Expected State: %s' % (host.getName(), resourceState, expectedResourceState))

    def setClusterManaged(self, clusterid, managed):
        self.marvinApi.cloudApi.updateCluster(id = clusterid,
                                              managedstate = managed and 'Managed' or 'Unmanaged')

        expectedClusterState = managed and 'Managed' or 'Unmanaged'
        expectedHostState = managed and 'Up' or 'Disconnected'

        correctStateReached = False
        while(not correctStateReached):
            xenrt.sleep(10)
            cluster = self.marvinApi.cloudApi.listClusters(id=clusterid)[0]
            xenrt.TEC().logverbose('Waiting for Cluster %s, Current state: Managed=%s, Alloc=%s, expected state: %s' % (cluster.name, cluster.managedstate, cluster.allocationstate, expectedClusterState))
            
            hostList = self.marvinApi.cloudApi.listHosts(clusterid=clusterid, type='Routing')
            hostListState = map(lambda x:x.state, hostList)
            xenrt.TEC().logverbose('Waiting for host(s) %s, Current State(s): %s' % (map(lambda x:x.name, hostList), hostListState))

            correctStateReached = (cluster.managedstate == expectedClusterState)
            if managed and correctStateReached:
                correctStateReached = len(hostList) == hostListState.count(expectedHostState)

    def call(self, host, preHook, master):
        xenrt.TEC().logverbose('hook called for host: %s, preHook: %s, master %s' % (host.getName(), preHook, master))
        if master:
            clusterId = self.marvinApi.cloudApi.listClusters()[0].id
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
                
    def waitForInstancesToReachState(self, instanceId, state, timeout=60):
        startTime = datetime.now()
        while(True):
            instance = self.marvinApi.cloudApi.listVirtualMachines(id=instanceId)[0]
            xenrt.TEC().logverbose('Instance %s, current state: %s, expected state: %s' % (instance.name, instance.state, state))
            timeTaken = (datetime.now() - startTime).seconds
            if instance.state == state:
                xenrt.TEC().logverbose('Instance %s reached the %s state in %d seconds' % (instance.name, state, timeTaken))
                break
            elif timeTaken < timeout:
                xenrt.sleep(10)
            else:
                raise xenrt.XRTFailure('Timeout expired waiting for instance to reach %s state' % (state))
        return timeTaken

    def destroy(self, instanceId):
        xenrt.TEC().logverbose('Destroy instance %s' % (instanceId))
        self.marvinApi.cloudApi.destroyVirtualMachine(id = instanceId, expunge = "true")

    def checkInstanceHealth(self, master, instance):
        xenrt.TEC().logverbose('Check health for instance %s [VM-Name: %s] IP Addr: %s' % (instance.name, instance.instancename, instance.nic[0].ipaddress))
        guest = master.guestFactory()(instance.instancename)
        guest.mainip = instance.nic[0].ipaddress
        guest.password = 'password'

        guest.checkReachable(timeout=300)
        guest.execguest('dd if=/dev/zero of=1GBfile bs=1000 count=10000')
        
    def verifyCloud(self, hostUpdated, postFixString):
        newInstanceName = '%s-%s' % (postFixString, hostUpdated.getName())
        # Check all instances are running
        # TODO - actually check instances are reachable
        self.waitForAllInstancesToReachState(state='Running', timeout=120)
        instances = self.marvinApi.cloudApi.listVirtualMachines()
        map(lambda x:self.checkInstanceHealth(self.pool.master, x), instances)

        # Create new instance
        self.createInstances(number=1, startInstances=True, basename=newInstanceName)

        # Create a temp instance
        self.createInstances(number=1, startInstances=True, basename='temp-%s' % (hostUpdated.getName()))
        self.waitForAllInstancesToReachState(state='Running', timeout=120)
        instances = self.marvinApi.cloudApi.listVirtualMachines()
        map(lambda x:self.checkInstanceHealth(self.pool.master, x), instances)

        # Lifecycle orginal + temp + new instance
        instances = self.marvinApi.cloudApi.listVirtualMachines()
        preUpdateInstance = filter(lambda x:x.name.startswith('preUpdateInst'), instances)[0]
        postHostUpdateInstance = filter(lambda x:x.name.startswith(newInstanceName), instances)[0]
        tempInstance = filter(lambda x:x.name.startswith('temp-%s' % (hostUpdated.getName())), instances)[0]

        map(lambda x:self.stop(x.id), [preUpdateInstance, postHostUpdateInstance, tempInstance])
        map(lambda x:self.waitForInstancesToReachState(x.id, 'Stopped'), [preUpdateInstance, postHostUpdateInstance, tempInstance])
        
        map(lambda x:self.start(x.id), [preUpdateInstance, postHostUpdateInstance, tempInstance])
        map(lambda x:self.waitForInstancesToReachState(x.id, 'Running'), [preUpdateInstance, postHostUpdateInstance, tempInstance])
        instances = self.marvinApi.cloudApi.listVirtualMachines()
        map(lambda x:self.checkInstanceHealth(self.pool.master, x), instances)

        # destroy original + temp instance
        map(lambda x:self.destroy(x.id), [preUpdateInstance, tempInstance])
        instancesDestroyed = False
        while(not instancesDestroyed):
            instances = self.marvinApi.cloudApi.listVirtualMachines()
            instancesToDestroy = filter(lambda x:x.id in [preUpdateInstance, tempInstance], instances)
            if len(instancesToDestroy) == 0:
                break
            else:
                xenrt.TEC().logverbose('Instances %s not destroyed yet. States: %s' % (map(lambda x:x.name, instancesToDestroy), map(lambda x:x.state, instancesToDestroy)))
                xenrt.sleep(10)


    def run(self, arglist):
        pool_upgrade = CloudRollingUpdate(poolRef = self.pool,
                                          newVersion='Clearwater',
                                          upgrade = True,
                                          applyAllHFXsBeforeApplyAction=True,
                                          vmActionIfHostRebootRequired=None,
                                          preEvacuate=None,
                                          preReboot=None,
                                          skipApplyRequiredPatches=False)
        setattr(pool_upgrade, "upgradeHook", self)
        self.newPool = self.pool.upgrade(poolUpgrade=pool_upgrade)


class TCCloudAllocateResources(xenrt.TestCase):
    def run(self, arglist):
        xenrt.TEC().comment('DNS:     %s' % xenrt.TEC().config.lookup("XENRT_SERVER_ADDRESS"))
        xenrt.TEC().comment('GATEWAY: %s' % xenrt.TEC().config.lookup(['NETWORK_CONFIG', 'DEFAULT', 'GATEWAY']))
        xenrt.TEC().comment('NETMASK: %s' % xenrt.TEC().config.lookup(['NETWORK_CONFIG', 'DEFAULT', 'SUBNETMASK']))

        manIP = xenrt.StaticIP4Addr.getIPRange(10)
        xenrt.TEC().comment('MANAGEMENT ADDR RANGE: %s -> %s' % (manIP[0].getAddr(), manIP[-1].getAddr()))
        guestIP = xenrt.StaticIP4Addr.getIPRange(10)
        xenrt.TEC().comment('GUEST ADDR RANGE: %s -> %s' % (guestIP[0].getAddr(), guestIP[-1].getAddr()))

        secondaryStorage = xenrt.ExternalNFSShare()
        primaryStorage = xenrt.ExternalNFSShare()
        xenrt.TEC().comment('SECONDARY STORAGE: %s' % (secondaryStorage.getMount()))
        xenrt.TEC().comment('PRIMARY STORAGE:   %s' % (primaryStorage.getMount()))

        pool = self.getDefaultPool()
        xenrt.TEC().comment('XS MASTER IP ADDR: %s' % (pool.master.getIP()))

