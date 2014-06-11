import xenrt
import logging
import os, urllib
from datetime import datetime
import shutil
import pprint

import xenrt.lib.cloud

__all__ = ["deploy"]

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

        self.initialSecStorageUrl = None
        self.hyperVMsi = None

    def getName(self, key, ref):
        nameValue = None
        if key == 'Zone':
            self.currentZoneIx += 1
            self.currentPodIx = -1
            self.currentClusterIx = -1
            nameValue = 'XenRT-Zone-%d' % (self.currentZoneIx)
        elif key == 'Pod':
            self.currentPodIx += 1
            self.currentClusterIx = -1
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
        if xenrt.TEC().lookup("CIFS_HOST_INDEX", None):
            url = self.marvin.createSecondaryStorage("SMB")
        elif self.initialSecStorageUrl:
            url = self.initialSecStorageUrl
            self.initialSecStorageUrl = None
        else:
            url = self.marvin.createSecondaryStorage("NFS")
        return url

    def getSecondaryStorageProvider(self, key, ref):
        if xenrt.TEC().lookup("CIFS_HOST_INDEX", None):
            return "SMB"
        else:
            return 'NFS'

    def getSecondaryStorageDetails(self, key, ref):
        if xenrt.TEC().lookup("CIFS_HOST_INDEX", None):
            return {"user":"Administrator", "password": "xenroot01T", "domain": "XSQA"}
        else:
            return None 

    def getPrimaryStorageDetails(self, key, ref):
        if xenrt.TEC().lookup("CIFS_HOST_INDEX", None):
            return {"user":"Administrator", "password": "xenroot01T", "domain": "XSQA"}
        else:
            return None

    def getIPRangeStartAddr(self, key, ref):
        xenrt.TEC().logverbose('IP Range, %s, %s' % (key, ref))

    def getPodIPStartAddr(self, key, ref):
        if self.currentIPRange != None:
            raise xenrt.XRTError('Start IP range addr requested on existing IP range')
        ipRangeSize = self.DEFAULT_POD_IP_RANGE
        if ref.has_key('XRT_PodIPRangeSize'):
            ipRangeSize = ref['XRT_PodIPRangeSize']
        self.currentIPRange = xenrt.StaticIP4Addr.getIPRange(ipRangeSize)
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
        self.currentIPRange = xenrt.StaticIP4Addr.getIPRange(ipRangeSize)
        return self.currentIPRange[0].getAddr()

    def getGuestIPRangeEndAddr(self, key, ref):
        if not self.currentIPRange:
            raise xenrt.XRTError('End IP range addr requested before start')
        endAddr = self.currentIPRange[-1].getAddr()
        self.currentIPRange = None
        return endAddr

    def getPhysicalNetworkVLAN(self, key, ref):
        phyNetVLAN = None
        if ref.has_key('XRT_VLANRangeSize') and ref['XRT_VLANRangeSize'] > 0:
            phyNetVLANResources = xenrt.PrivateVLAN.getVLANRange(ref['XRT_VLANRangeSize'])
            phyNetVLAN = '%d-%d' % (int(phyNetVLANResources[0].getID()), int(phyNetVLANResources[-1].getID()))
        return phyNetVLAN

    def getHostUsername(self, key, ref):
        return 'root'

    def getHostPassword(self, key, ref):
        return xenrt.TEC().lookup("ROOT_PASSWORD")

    def getHypervisorType(self, key, ref):
        if ref.has_key('hypervisor'):
            return ref['hypervisor']
        return 'XenServer' # Default to XenServer if not specified

    def getPrimaryStorageName(self, key, ref):
        return '%s-Primary-Store' % (self.currentPodName)

    def getPrimaryStorageUrl(self, key, ref):
        # TODO - Add support for other storage types
        if xenrt.TEC().lookup("CIFS_HOST_INDEX", None):
            cifshost = int(xenrt.TEC().lookup("CIFS_HOST_INDEX"))
            h = xenrt.GEC().registry.hostGet("RESOURCE_HOST_%d" % cifshost)
            ip = h.getIP()
            return "cifs://%s/pristorage" % (ip)
        else:
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
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [h.getName(), "CSIP", self.marvin.mgtSvr.place.getIP()])
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [h.getName(), "CSGUEST", "%s/%s" % (self.marvin.mgtSvr.place.getHost().getName(), self.marvin.mgtSvr.place.getName())])
                except Exception, e:
                    xenrt.TEC().logverbose("Warning - could not update machine info - %s" % str(e))

            hosts.append( { 'url': 'http://%s' % (hostObject.getIP()) } )
        elif ref.has_key('hypervisor') and ref['hypervisor'] == 'KVM' and ref.has_key('XRT_KVMHostIds'):
            hostIds = ref['XRT_KVMHostIds'].split(',')
            for hostId in hostIds:
                h = xenrt.TEC().registry.hostGet('RESOURCE_HOST_%d' % (int(hostId)))
                try:
                    h.tailorForCloudStack(self.marvin.mgtSvr.isCCP)
                except:
                    xenrt.TEC().logverbose("Warning - could not run tailorForCloudStack()")

                try:
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [h.getName(), "CSIP", self.marvin.mgtSvr.place.getIP()])
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [h.getName(), "CSGUEST", "%s/%s" % (self.marvin.mgtSvr.place.getHost().getName(), self.marvin.mgtSvr.place.getName())])
                except Exception, e:
                    xenrt.TEC().logverbose("Warning - could not update machine info - %s" % str(e))

                hosts.append({ 'url': 'http://%s' % (h.getIP()) })
        elif ref.has_key('hypervisor') and ref['hypervisor'] == 'HyperV' and ref.has_key('XRT_HyperVHostIds'):
            hostIds = ref['XRT_HyperVHostIds'].split(',')
            for hostId in hostIds:
                h = xenrt.TEC().registry.hostGet('RESOURCE_HOST_%d' % (int(hostId)))
                self.getHyperVMsi()
                try:
                    h.tailorForCloudStack(self.hyperVMsi)
                except:
                    xenrt.TEC().logverbose("Warning - could not run tailorForCloudStack()")

                try:
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [h.getName(), "CSIP", self.marvin.mgtSvr.place.getIP()])
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [h.getName(), "CSGUEST", "%s/%s" % (self.marvin.mgtSvr.place.getHost().getName(), self.marvin.mgtSvr.place.getName())])
                except Exception, e:
                    xenrt.TEC().logverbose("Warning - could not update machine info - %s" % str(e))

                hosts.append({ 'url': 'http://%s' % (h.getIP()) })
        elif ref.has_key('XRT_NumberOfHosts'):
            map(lambda x:hosts.append({}), range(ref['XRT_NumberOfHosts']))
        return hosts

    def getHyperVMsi(self):
        # Install CloudPlatform packages
        cloudInputDir = xenrt.TEC().lookup("CLOUDINPUTDIR", None)
        if not cloudInputDir:
            raise xenrt.XRTError("No CLOUDINPUTDIR specified")
        xenrt.TEC().logverbose("Downloading %s" % cloudInputDir)
        ccpTar = xenrt.TEC().getFile(cloudInputDir)
        xenrt.TEC().logverbose("Got %s" % ccpTar)
        t = xenrt.TempDirectory()
        xenrt.command("tar -xvzf %s -C %s" % (ccpTar, t.path()))
        self.hyperVMsi = xenrt.command("find %s -type f -name *hypervagent.msi" % t.path()).strip()

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

    def notifyGlobalConfigChanged(self, key, value):
        xenrt.TEC().logverbose("notifyGlobalConfigChanged:\n" + pprint.pformat(value))
        
def deploy(cloudSpec, manSvr=None):
    xenrt.TEC().logverbose('Cloud Spec: %s' % (cloudSpec))

    # TODO - Get the ManSvr object from the registry
    if not manSvr:
        manSvrVM = xenrt.TEC().registry.guestGet('CS-MS')
        toolstack = xenrt.TEC().registry.toolstackGet("cloud")
        if manSvrVM:
            manSvr = xenrt.lib.cloud.ManagementServer(manSvrVM)
        elif toolstack:
            manSvr = toolstack.mgtsvr
        else:
            raise xenrt.XRTError('No management server specified') 

    xenrt.TEC().comment('Using Management Server: %s' % (manSvr.place.getIP()))
    marvin = xenrt.lib.cloud.MarvinApi(manSvr)

    deployerPlugin = DeployerPlugin(marvin)
    if manSvr.place.special.has_key('initialSecStorageUrl') and manSvr.place.special['initialSecStorageUrl']:
        deployerPlugin.initialSecStorageUrl = manSvr.place.special['initialSecStorageUrl']
        manSvr.place.special['initialSecStorageUrl'] = None
    marvinCfg = marvin.marvinDeployerFactory()
    marvinCfg.generateMarvinConfig(cloudSpec, deployerPlugin)

    # Store the JSON Marvin config file
    fn = xenrt.TEC().tempFile()
    marvinCfg.outputAsJSONFile(fn)
    deployLogDir = os.path.join(xenrt.TEC().getLogdir(), 'cloud', 'deploy')
    if not os.path.exists(deployLogDir):
        os.makedirs(deployLogDir)
    shutil.copy(fn, os.path.join(deployLogDir, 'marvin-deploy.cfg'))

    try:
        # Create deployment
        marvinCfg.deployMarvinConfig()

        # Restart MS if any global config setting have been changed
        if cloudSpec.has_key('globalConfig'):
            manSvr.restart()

        if xenrt.TEC().lookup("CLOUD_WAIT_FOR_TPLTS", False, boolean=True):
            marvin.waitForBuiltInTemplatesReady()
    finally:
        # Get deployment logs from the MS
        manSvr.getLogs(deployLogDir)
