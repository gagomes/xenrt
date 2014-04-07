import xenrt
import logging
import os, urllib
from datetime import datetime
import shutil

import xenrt.lib.cloud
from xenrt.lib.cloud.marvindeploy import MarvinDeployer

__all__ = ["deploy"]

try:
    from marvin import cloudstackTestClient
    from marvin.integration.lib.base import *
    from marvin import configGenerator
except ImportError:
    pass

class DeployerPlugin(object):
    DEFAULT_POD_IP_RANGE = 10
    DEFAULT_GUEST_IP_RANGE = 20

    def __init__(self, marvinApi):
        self.marvin = marvinApi

        self.currentZoneIx = -1
        self.currentPodIx = -1
        self.currentClusterIx = -1

        self.currentZoneName = None
        self.currentPodName = None
        self.currentClusterName = None
        self.currentIPRange = None

    def getName(self, key, ref):
        nameValue = None
        if key == 'Zone':
            self.currentZoneIx += 1
            nameValue = 'XenRT-Zone-%d' % (self.currentZoneIx)
        elif key == 'Pod':
            self.currentPodIx += 1
            nameValue = '%s-Pod-%d' % (self.currentZoneName, self.currentPodIx)            
        elif key == 'Cluster':
            self.currentClusterIx += 1
            nameValue = '%s-Cluster-%d' % (self.currentPodName, self.currentClusterIx)
        xenrt.TEC().logverbose('getName returned: %s for key: %s' % (nameValue, key))
        return nameValue

    def getDNS(self, key, ref):
        return xenrt.TEC().config.lookup(['NETWORK_CONFIG', 'DEFAULT', 'NAMESERVERS']).split(',')[0]

    def getNetmask(self, key, ref):
        return xenrt.TEC().config.lookup(['NETWORK_CONFIG', 'DEFAULT', 'SUBNETMASK'])

    def getGateway(self, key, ref):
        return xenrt.TEC().config.lookup(['NETWORK_CONFIG', 'DEFAULT', 'GATEWAY'])

    def getSecondaryStorageUrl(self, key, ref):
        # TODO - Add support for other storage types
        secondaryStorage = xenrt.ExternalNFSShare()
        storagePath = secondaryStorage.getMount()
        url = 'nfs://%s' % (secondaryStorage.getMount().replace(':',''))
        self.marvin.copySystemTemplateToSecondaryStorage(storagePath, 'NFS')
        return url

    def getSecondaryStorageProvider(self, key, ref):
        return 'NFS'

    def getIPRangeStartAddr(self, key, ref):
        xenrt.TEC().logverbose('IP Range, %s, %s' % (key, ref))

    def getPodIPStartAddr(self, key, ref):
        if self.currentIPRange != None:
            raise xenrt.XRTError('Start IP range addr requested on existing IP range')
        ipRangeSize = self.DEFAULT_POD_IP_RANGE
        if ref.has_key('XRT_PodIPRangeSize'):
            ipRangeSize = ref['XRT_PodIPRangeSize']
        self.currentIPRange = xenrt.resources.getResourceRange('IP4ADDR', ipRangeSize)
        return self.currentIPRange[0].getAddr()

    def getPodIPEndAddr(self, key, ref):
        if not self.currentIPRange:
            raise xenrt.XRTError('End IP range addr requested before start')
        endAddr = self.currentIPRange[-1].getAddr()
        self.currentIPRange = None
        return endAddr

    def getGuestIPRangeStartAddr(self, key, ref):
        if self.currentIPRange != None:
            raise xenrt.XRTError('Start IP range addr requested on existing IP range')
        ipRangeSize = self.DEFAULT_GUEST_IP_RANGE
        if ref.has_key('XRT_GuestIPRangeSize'):
            ipRangeSize = ref['XRT_GuestIPRangeSize']
        self.currentIPRange = xenrt.resources.getResourceRange('IP4ADDR', ipRangeSize)
        return self.currentIPRange[0].getAddr()

    def getGuestIPRangeEndAddr(self, key, ref):
        if not self.currentIPRange:
            raise xenrt.XRTError('End IP range addr requested before start')
        endAddr = self.currentIPRange[-1].getAddr()
        self.currentIPRange = None
        return endAddr

    def getHostUrl(self, key, ref):
        return 'http://%s' % (hostAddr)

    def getHostUsername(self, key, ref):
        return 'root'

    def getHostPassword(self, key, ref):
        return xenrt.TEC().lookup("ROOT_PASSWORD")

    def getHypervisorType(self, key, ref):
        # TODO - enable support for other HVs
        return 'XenServer'

    def getPrimaryStorageName(self, key, ref):
        return '%s-Primary-Store' % (self.currentPodName)

    def getPrimaryStorageUrl(self, key, ref):
        # TODO - Add support for other storage types
        primaryStorage = xenrt.ExternalNFSShare()
        return 'nfs://%s' % (primaryStorage.getMount().replace(':',''))

    def getHostsForCluster(self, key, ref):
        xenrt.TEC().logverbose('getHostsForCluster, %s, %s' % (key, ref))
        hosts = []
        if ref.has_key('hypervisor') and ref['hypervisor'] == 'XenServer' and ref.has_key('XRT_MasterHostId'):
            # TODO - move this to the host notify block (in notifyNewElement)
            hostObject = xenrt.TEC().registry.hostGet('RESOURCE_HOST_%d' % (ref['XRT_MasterHostId']))
            try:
                hostObject.tailorForCloudStack()
            except:
                xenrt.TEC().logverbose("Warning - could not run tailorForCloudStack()")

            if hostObject.pool:
                hostObjects = hostObject.pool.getHosts()
            else:
                hostObjects = [hostObject]
            for h in hostObjects:
                try:
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [h.getName(), "CSIP", manSvr.place.getIP()])
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [h.getName(), "CSGUEST", "%s/%s" % (manSvr.place.getHost().getName(), manSvr.place.getName())])
                except Exception, e:
                    xenrt.TEC().logverbose("Warning - could not update machine info - %s" % str(e))

            hosts.append( { 'url': 'http://%s' % (hostObject.getIP()) } )
        elif ref.has_key('XRT_NumberOfHosts'):
            map(lambda x:hosts.append({}), range(ref['XRT_NumberOfHosts']))
        return hosts

    def notifyNewElement(self, key, name):
        xenrt.TEC().logverbose('New Element, key: %s, value: %s' % (key, name))
        if key == 'Zone':
            self.currentZoneName = name
        elif key == 'Pod':
            self.currentPodName = name
        elif key == 'Cluster':
            self.currentClusterName = name

    def notifyNetworkTrafficTypes(self, key, value):
        xenrt.TEC().logverbose('notifyNetworkTrafficTypes: key: %s, value %s' % (key, value))

def deploy(cloudSpec, manSvr=None):
    xenrt.TEC().logverbose('Cloud Spec: %s' % (cloudSpec))

    # TODO - Get the ManSvr object from the registry
    if not manSvr:
        manSvrVM = xenrt.TEC().registry.guestGet('CS-MS')
        if not manSvrVM:
            raise xenrt.XRTError('No management server specified')
        manSvr = xenrt.lib.cloud.ManagementServer(manSvrVM)

    xenrt.TEC().comment('Using Management Server: %s' % (manSvr.place.getIP()))
    marvinApi = xenrt.lib.cloud.MarvinApi(manSvr)

    marvinApi.setCloudGlobalConfig("secstorage.allowed.internal.sites", "10.0.0.0/8,192.168.0.0/16,172.16.0.0/12")
    marvinApi.setCloudGlobalConfig("check.pod.cidrs", "false", restartManagementServer=True)

    deployerPlugin = DeployerPlugin(marvinApi)
    marvinCfg = MarvinDeployer(marvinApi.mgtSvrDetails.mgtSvrIp, marvinApi.logger)
    marvinCfg.generateMarvinConfig(cloudSpec, deployerPlugin)

    # Store the JSON Marvin config file
    fn = xenrt.TEC().tempFile()
    marvinCfg.outputAsJSONFile(fn)
    deployLogDir = os.path.join(xenrt.TEC().getLogdir(), 'cloud', 'deploy')
    if not os.path.exists(deployLogDir):
        os.makedirs(deployLogDir)
    shutil.copy(fn, os.path.join(deployLogDir, 'marvin-deploy.cfg'))

    # Create deployment
    marvinCfg.deployMarvinConfig()
    # Get deployment logs from the MS
    manSvr.getLogs(deployLogDir)

