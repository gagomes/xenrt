import xenrt
import logging
import os, urllib
from datetime import datetime
import shutil
import pprint
import string
import random

import xenrt.lib.cloud
from xenrt.lib.netscaler import NetScaler

__all__ = ["doDeploy"]

class DeployerPlugin(object):
    DEFAULT_POD_IP_RANGE = 10
    DEFAULT_GUEST_IP_RANGE = 20

    def __init__(self, marvinApi):
        self.marvin = marvinApi

        self.currentZoneIx = -1
        self.currentPodIx = -1
        self.currentClusterIx = -1
        self.currentPrimaryStoreZoneIx = -1
        self.currentPrimaryStoreClusterIx = -1

        self.currentZoneName = None
        self.currentPodName = None
        self.currentClusterName = None
        self.currentIPRange = None

        self.initialNFSSecStorageUrl = None
        self.initialSMBSecStorageUrl = None
        self.hyperVMsi = None

    def getName(self, key, ref):
        nameValue = None
        if key == 'Zone':
            self.currentZoneIx += 1
            self.currentPodIx = -1
            self.currentClusterIx = -1
            self.currentPrimaryStoreZoneIx = -1
            nameValue = 'XenRT-Zone-%d' % (self.currentZoneIx)
        elif key == 'Pod':
            self.currentPodIx += 1
            self.currentClusterIx = -1
            nameValue = '%s-Pod-%d' % (self.currentZoneName, self.currentPodIx)
        elif key == 'Cluster':
            self.currentClusterIx += 1
            self.currentPrimaryStoreClusterIx = -1
            nameValue = '%s-Cluster-%d' % (self.currentPodName, self.currentClusterIx)
        xenrt.TEC().logverbose('getName returned: %s for key: %s' % (nameValue, key))
        return nameValue

    def getNetworkDevices(self, key, ref):
        ret = None
        if ref.has_key('XRT_NetscalerVM'):
            networks = ref['XRT_NetscalerNetworks']
            netscaler = xenrt.lib.netscaler.NetScaler.setupNetScalerVpx(ref['XRT_NetscalerVM'], networks=networks)
            xenrt.GEC().registry.objPut("netscaler", ref['XRT_NetscalerVM'], netscaler)
            xenrt.GEC().registry.dump()
            netscaler.applyLicense(netscaler.getLicenseFileFromXenRT())
            netscaler.disableL3()
            for n in networks[1:]:
                netscaler.setupOutboundNAT(n, networks[0])
            ret = [{"username": "nsroot",
                    "publicinterface": "1/1",
                    "hostname": netscaler.managementIp,
                    "privateinterface": "1/2",
                    "lbdevicecapacity": "50",
                    "networkdevicetype": "NetscalerVPXLoadBalancer",
                    "lbdevicededicated": "false",
                    "password": "nsroot",
                    "numretries": "2"}]

        return ret

    def getDNS(self, key, ref):
        if ref.has_key("XRT_ZoneNetwork") and ref['XRT_ZoneNetwork'].lower() != "NPRI":
            if ref['XRT_ZoneNetwork'] == "NSEC":
                return xenrt.TEC().lookup(["NETWORK_CONFIG", "SECONDARY", "ADDRESS"])
            else:
                return xenrt.TEC().lookup(["NETWORK_CONFIG", "VLANS", ref['XRT_ZoneNetwork'], "ADDRESS"])
                
        else:
            return xenrt.TEC().config.lookup("XENRT_SERVER_ADDRESS")

    def getInternalDNS(self, key, ref):
        return xenrt.TEC().config.lookup("XENRT_SERVER_ADDRESS")

    def getDomain(self, key, ref):
        if xenrt.TEC().lookup("MARVIN_SETUP", False, boolean=True):
            return None
        if ref.has_key("XRT_ZoneNetwork") and ref['XRT_ZoneNetwork'].lower() != "NPRI":
            return "%s-xenrtcloud" % ref['XRT_ZoneNetwork'].lower()
        return "xenrtcloud"

    def getNetmask(self, key, ref):
        return xenrt.getNetworkParam(ref.get("XRT_VlanName", "NPRI"), "SUBNETMASK")

    def getGateway(self, key, ref):
        if ref.has_key("XRT_NetscalerGateway"):
            xenrt.GEC().registry.dump()
            xenrt.TEC().logverbose("XRT_NetscalerGateway")
            ns = xenrt.GEC().registry.objGet("netscaler", ref['XRT_NetscalerGateway'])
            return ns.subnetIp(ref.get("XRT_VlanName", "NPRI"))
        else:
            return xenrt.getNetworkParam(ref.get("XRT_VlanName", "NPRI"), "GATEWAY")

    def getSecondaryStorages(self, key, ref):
        storageTypes = []
        ss = []
        for p in ref['pods']:
            for c in p['clusters']:
                if c['hypervisor'] == 'hyperv':
                    if not "SMB" in [x['provider'] for x in ss]:
                        d = {"provider": "SMB"}
                        d['XRT_SMBHostId'] = c['XRT_HyperVHostIds'].split(",")[0]
                        ss.append(d)
                else:
                    if not "NFS" in [x['provider'] for x in ss]:
                        d = {"provider": "NFS"}
                        ss.append(d)
        return ss

    def getSecondaryStorageUrl(self, key, ref):
        if not ref.has_key('provider'):
            provider = "NFS"
        else:
            provider = ref['provider']
            
        if provider == "NFS":
            if ref.has_key("XRT_Guest_NFS"):
                ssGuest = xenrt.TEC().registry.guestGet(ref['XRT_Guest_NFS'])
                xenrt.TEC().logverbose('Using guest %s for secondary NFS storage' % (ssGuest.name))
                shareName = 'SS-%s-%s' % (self.currentZoneName, ''.join(random.sample(string.ascii_lowercase + string.ascii_uppercase, 6)))
                storagePath = ssGuest.createLinuxNfsShare(shareName)
                self.marvin.copySystemTemplatesToSecondaryStorage(storagePath, 'NFS')
                url = 'nfs://%s' % (storagePath.replace(':',''))
            elif self.initialNFSSecStorageUrl:
                url = self.initialNFSSecStorageUrl
                self.initialNFSSecStorageUrl = None
            else:
                secondaryStorage = xenrt.ExternalNFSShare()
                storagePath = secondaryStorage.getMount()
                url = 'nfs://%s' % (secondaryStorage.getMount().replace(':',''))
                self.marvin.copySystemTemplatesToSecondaryStorage(storagePath, 'NFS')
        elif provider== "SMB":
            if self.initialSMBSecStorageUrl:
                url = self.initialSMBSecStorageUrl
                self.initialSMBSecStorageUrl = None
            else:
                if xenrt.TEC().lookup("EXTERNAL_SMB", False, boolean=True):
                    secondaryStorage = xenrt.ExternalSMBShare()
                    url = 'cifs://%s' % (secondaryStorage.getMount().replace(':',''))
                    storagePath = secondaryStorage.getMount()
                else:
                    h = xenrt.GEC().registry.hostGet("RESOURCE_HOST_%s" % ref['XRT_SMBHostId'])
                    ip = h.getIP()
                    url = "cifs://%s/storage/secondary" % ip
                    storagePath = "%s:/storage/secondary" % ip
                    
                self.marvin.copySystemTemplatesToSecondaryStorage(storagePath, 'SMB')

        return url

    def getSecondaryStorageProvider(self, key, ref):
        # If it's not provided explicitly, assume NFS
        return "NFS"

    def getSecondaryStorageDetails(self, key, ref):
        if ref.has_key('provider') and ref['provider'] == "SMB":
            ad = xenrt.getADConfig()
            return {"user":ad.adminUser, "password": ad.adminPassword, "domain": ad.domainName}
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

    def getZonePublicVlan(self, key, ref):
        if ref.has_key("XRT_VlanName"):
            if ref['XRT_VlanName'] == "NPRI":
                return xenrt.TEC().lookup(["NETWORK_CONFIG", "DEFAULT", "VLAN"])
            elif ref['XRT_VlanName'] == "NSEC":
                return xenrt.TEC().lookup(["NETWORK_CONFIG", "SECONDARY", "VLAN"])
            else:
                return xenrt.TEC().lookup(["NETWORK_CONFIG", "VLANS", ref['XRT_VlanName'], "ID"])
        else:
            # It is mandatory to specify a VLAN for public IP ranges in 4.2.x and earlier releases
            if self.marvin.mgtSvr.version in ['3.0.7', '4.1', '4.2']:
                return 0
            else:
                return None

    def getGuestIPRangeStartAddr(self, key, ref):
        if self.currentIPRange != None:
            raise xenrt.XRTError('Start IP range addr requested on existing IP range')
        ipRangeSize = self.DEFAULT_GUEST_IP_RANGE
        if ref.has_key('XRT_GuestIPRangeSize'):
            ipRangeSize = ref['XRT_GuestIPRangeSize']
        if ref.has_key("XRT_VlanName"):
            self.currentIPRange = xenrt.StaticIP4Addr.getIPRange(ipRangeSize, network = ref['XRT_VlanName'])
        else:
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

    def getPrimaryStorages(self, key, ref):
        ps = []
        if ref['hypervisor'] == "hyperv":
            hostid = ref['XRT_HyperVHostIds'].split(",")[0]
            ps.append({"XRT_PriStorageType": "SMB", "XRT_SMBHostId": hostid})
        else:
            ps.append({"XRT_PriStorageType": "NFS"})
        return ps

    def getPrimaryStorageName(self, key, ref):
        if ref.get("scope",False) == "zone":
            if "hypervisor" not in ref:
                raise xenrt.XRTError('hypervisor not specified for zone wide primary storage.')
            elif ref["hypervisor"] not in ["KVM", "vmware"]:
                raise xenrt.XRTError('Only KVM and vmware hypervisor support zone wide primary storage.')
            ref["XRT_PriStorageType"] = "NFS"
            self.currentPrimaryStoreZoneIx += 1
            name = '%s-Primary-Store-%d' % (self.currentZoneName, self.currentPrimaryStoreZoneIx)
        else:
            self.currentPrimaryStoreClusterIx += 1
            name = '%s-Primary-Store-%d' % (self.currentClusterName, self.currentPrimaryStoreClusterIx)
        return name

    def getPrimaryStorageUrl(self, key, ref):
        if not ref.has_key("XRT_PriStorageType"):
            storageType = "NFS"
        else:
            storageType = ref['XRT_PriStorageType']

        if storageType == "NFS":
            if ref.has_key('XRT_Guest_NFS'):
                ssGuest = xenrt.TEC().registry.guestGet(ref['XRT_Guest_NFS'])
                xenrt.TEC().logverbose('Using guest %s for primary NFS storage' % (ssGuest.name))
                shareName = 'PS-%s-%s' % (self.currentClusterName, ''.join(random.sample(string.ascii_lowercase + string.ascii_uppercase, 6)))
                storagePath = ssGuest.createLinuxNfsShare(shareName)
                url = 'nfs://%s' % (storagePath.replace(':',''))
            else:
                primaryStorage = xenrt.ExternalNFSShare()
                url = 'nfs://%s' % (primaryStorage.getMount().replace(':',''))
        elif storageType == "SMB":
            h = xenrt.GEC().registry.hostGet("RESOURCE_HOST_%s" % ref['XRT_SMBHostId'])
            ip = h.getFQDN()
            url =  "cifs://%s/storage/primary" % (ip)
            ad = xenrt.getADConfig()
        return url

    def getPrimaryStorageDetails(self, key, ref):
        if ref.has_key('XRT_PriStorageType') and ref['XRT_PriStorageType'] == "SMB":
            ad = xenrt.getADConfig()
            return {"user":ad.adminUser, "password": ad.adminPassword, "domain": ad.domainName}
        else:
            return None

    def getClusterType(self, key, ref):
        if ref.has_key("hypervisor") and ref['hypervisor'].lower() == "vmware":
            return "ExternalManaged"
        else:
            return "CloudManaged"

    def getClusterUrl(self, key, ref):
        if ref.has_key("hypervisor") and ref['hypervisor'].lower() == "vmware":
            return "http://%s/%s/%s" % (xenrt.TEC().lookup(["VCENTER", "ADDRESS"]), ref['XRT_VMWareDC'], ref['XRT_VMWareCluster'])
        else:
            return None
        
    def getVmWareDc(self, key, ref):
        if ref.has_key("XRT_VMWareDC"):
            vc = xenrt.TEC().lookup("VCENTER")
            return {"name": ref['XRT_VMWareDC'],
                    "vcenter": vc['ADDRESS'],
                    "username": vc['USERNAME'],
                    "password": vc['PASSWORD']}
        else:
            return None

    def getHostsForCluster(self, key, ref):
        xenrt.TEC().logverbose('getHostsForCluster, %s, %s' % (key, ref))
        hosts = []
        if ref.has_key('hypervisor') and ref['hypervisor'].lower() == 'xenserver' and ref.has_key('XRT_MasterHostName'):
            # TODO - move this to the host notify block (in notifyNewElement)
            hostObject = xenrt.TEC().registry.hostGet(ref['XRT_MasterHostName'])
            try:
                hostObject.tailorForCloudStack(isBasic = ref.get("XRT_NetworkType", "Basic").lower() == "basic")
            except Exception, e:
                xenrt.TEC().logverbose("Warning - could not run tailorForCloudStack() - %s" % str(e))

            if hostObject.pool:
                hostObjects = hostObject.pool.getHosts()
            else:
                hostObjects = [hostObject]
            for h in hostObjects:
                try:
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [h.getName(), "CSIP", self.marvin.mgtSvr.ip])
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [h.getName(), "CSGUEST", "%s/%s" % (self.marvin.mgtSvr.primaryManagementServer.getHost().getName(), self.marvin.mgtSvr.primaryManagementServer.getName())])
                except Exception, e:
                    xenrt.TEC().logverbose("Warning - could not update machine info - %s" % str(e))

            hosts.append( { 'url': 'http://%s' % (hostObject.getIP()) } )
        elif ref.has_key('hypervisor') and ref['hypervisor'].lower() == 'kvm' and ref.has_key('XRT_KVMHostIds'):
            hostIds = ref['XRT_KVMHostIds'].split(',')
            for hostId in hostIds:
                h = xenrt.TEC().registry.hostGet('RESOURCE_HOST_%d' % (int(hostId)))
                h.tailorForCloudStack(self.marvin.mgtSvr.isCCP, isBasic = ref.get("XRT_NetworkType", "Basic").lower() == "basic")

                try:
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [h.getName(), "CSIP", self.marvin.mgtSvr.ip])
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [h.getName(), "CSGUEST", "%s/%s" % (self.marvin.mgtSvr.primaryManagementServer.getHost().getName(), self.marvin.mgtSvr.primaryManagementServer.getName())])
                except Exception, e:
                    xenrt.TEC().logverbose("Warning - could not update machine info - %s" % str(e))

                hosts.append({ 'url': 'http://%s' % (h.getIP()) })
        elif ref.has_key('hypervisor') and ref['hypervisor'].lower() == 'lxc' and ref.has_key('XRT_LXCHostIds'):
            hostIds = ref['XRT_LXCHostIds'].split(',')
            for hostId in hostIds:
                h = xenrt.TEC().registry.hostGet('RESOURCE_HOST_%d' % (int(hostId)))
                h.tailorForCloudStack(self.marvin.mgtSvr.isCCP, isLXC=True, isBasic = ref.get("XRT_NetworkType", "Basic").lower() == "basic")

                try:
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [h.getName(), "CSIP", self.marvin.mgtSvr.ip])
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [h.getName(), "CSGUEST", "%s/%s" % (self.marvin.mgtSvr.primaryManagementServer.getHost().getName(), self.marvin.mgtSvr.primaryManagementServer.getName())])
                except Exception, e:
                    xenrt.TEC().logverbose("Warning - could not update machine info - %s" % str(e))

                hosts.append({ 'url': 'http://%s' % (h.getIP()) })
        elif ref.has_key('hypervisor') and ref['hypervisor'].lower() == 'hyperv' and ref.has_key('XRT_HyperVHostIds'):
            hostIds = ref['XRT_HyperVHostIds'].split(',')
            hostObjs = []
            for hostId in hostIds:
                h = xenrt.TEC().registry.hostGet('RESOURCE_HOST_%d' % (int(hostId)))
                self.getHyperVMsi()
                h.tailorForCloudStack(self.hyperVMsi)

                try:
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [h.getName(), "CSIP", self.marvin.mgtSvr.ip])
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [h.getName(), "CSGUEST", "%s/%s" % (self.marvin.mgtSvr.primaryManagementServer.getHost().getName(), self.marvin.mgtSvr.primaryManagementServer.getName())])
                except Exception, e:
                    xenrt.TEC().logverbose("Warning - could not update machine info - %s" % str(e))

                hosts.append({ 'url': 'http://%s' % (h.getFQDN()) })
                hostObjs.append(h)
            for h in hostObjs:
                for j in hostObjs:
                    h.enableDelegation(j, "cifs")
                    h.enableDelegation(j, "Microsoft Virtual System Migration Service")
        elif ref.has_key('hypervisor') and ref['hypervisor'].lower() == 'vmware' and ref.has_key('XRT_VMWareHostIds'):
            hostIds = ref['XRT_VMWareHostIds'].split(',')
            for hostId in hostIds:
                h = xenrt.TEC().registry.hostGet('RESOURCE_HOST_%d' % (int(hostId)))

                try:
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [h.getName(), "CSIP", self.marvin.mgtSvr.ip])
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [h.getName(), "CSGUEST", "%s/%s" % (self.marvin.mgtSvr.primaryManagementServer.getHost().getName(), self.marvin.mgtSvr.primaryManagementServer.getName())])
                except Exception, e:
                    xenrt.TEC().logverbose("Warning - could not update machine info - %s" % str(e))

                hosts.append({ 'url': 'http://%s' % (h.getIP()) })
        elif ref.has_key('XRT_NumberOfHosts'):
            map(lambda x:hosts.append({}), range(ref['XRT_NumberOfHosts']))
        return hosts

    def getHyperVMsi(self):
        if xenrt.TEC().lookup("HYPERV_AGENT", None):
            self.hyperVMsi = xenrt.TEC().getFile(xenrt.TEC().lookup("HYPERV_AGENT"))
        elif xenrt.TEC().lookup("ACS_BUILD", None):
            artifacts = xenrt.lib.cloud.getACSArtifacts(None, [], ["hypervagent.zip"])
            if len(artifacts) > 0:
                self.hyperVMsi = artifacts[0]

        if not self.hyperVMsi:
            # Install CloudPlatform packages
            cloudInputDir = self.marvin.mgtSvr.getCCPInputs()
            if not cloudInputDir:
                raise xenrt.XRTError("No CLOUDINPUTDIR specified")
            xenrt.TEC().logverbose("Downloading %s" % cloudInputDir)
            ccpTar = xenrt.TEC().getFile(cloudInputDir)
            xenrt.TEC().logverbose("Got %s" % ccpTar)
            t = xenrt.TempDirectory()
            xenrt.command("tar -xvzf %s -C %s" % (ccpTar, t.path()))
            self.hyperVMsi = xenrt.command("find %s -type f -name *hypervagent.msi" % t.path()).strip()
        if not self.hyperVMsi:
            self.hyperVMsi = xenrt.TEC().getFile(xenrt.TEC().lookup("HYPERV_AGENT_FALLBACK", "http://repo-ccp.citrix.com/releases/ASF/hyperv/ccp-4.5/CloudPlatform-4.5.0.0-19-hypervagent.msi"))
        if not self.hyperVMsi:
            raise xenrt.XRTError("Could not find Hyper-V agent in build")

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
        
def doDeploy(cloudSpec, manSvr=None):
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

    xenrt.TEC().comment('Using Management Server: %s' % (manSvr.ip))
    marvin = xenrt.lib.cloud.MarvinApi(manSvr)

    deployerPlugin = DeployerPlugin(marvin)
    if manSvr.primaryManagementServer.special.has_key('initialNFSSecStorageUrl') and manSvr.primaryManagementServer.special['initialNFSSecStorageUrl']:
        deployerPlugin.initialNFSSecStorageUrl = manSvr.primaryManagementServer.special['initialNFSSecStorageUrl']
        manSvr.primaryManagementServer.special['initialNFSSecStorageUrl'] = None
    if manSvr.primaryManagementServer.special.has_key('initialSMBSecStorageUrl') and manSvr.primaryManagementServer.special['initialSMBSecStorageUrl']:
        deployerPlugin.initialSMBSecStorageUrl = manSvr.primaryManagementServer.special['initialSMBSecStorageUrl']
        manSvr.primaryManagementServer.special['initialSMBSecStorageUrl'] = None
    marvinCfg = marvin.marvinDeployerFactory()
    marvinCfg.generateMarvinConfig(cloudSpec, deployerPlugin)

    # Store the JSON Marvin config file
    fn = xenrt.TEC().tempFile()
    marvinCfg.outputAsJSONFile(fn)
    deployLogDir = os.path.join(xenrt.TEC().getLogdir(), 'cloud', 'deploy')
    if not os.path.exists(deployLogDir):
        os.makedirs(deployLogDir)
    shutil.copy(fn, os.path.join(deployLogDir, 'marvin-deploy.cfg'))
    toolstack.marvinCfg = marvinCfg.marvinCfg

    if not xenrt.TEC().lookup("NO_CLOUDSTACK_DEPLOY", False, boolean=True):
        try:
            # Create deployment
            marvinCfg.deployMarvinConfig()

            # Restart MS if any global config setting have been changed
            if cloudSpec.has_key('globalConfig'):
                manSvr.restart()

            marvin.waitForSystemVmsReady()
            if xenrt.TEC().lookup("CLOUD_WAIT_FOR_TPLTS", False, boolean=True):
                marvin.waitForBuiltInTemplatesReady()

            toolstack.postDeploy()
        finally:
            # Get deployment logs from the MS
            manSvr.getLogs(deployLogDir)
